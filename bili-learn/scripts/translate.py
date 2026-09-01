#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translate.py — 字幕批量翻译 → 双语 SRT

读取 transcript.srt（或 .json），用 LLM 批量翻译字幕行，输出:
  transcript.bilingual.srt  # 原文 + 译文 双语字幕（可直接导入播放器）
  transcript.<lang>.srt     # 纯译文字幕（可选）

LLM 后端（auto 顺序，key 自动从 ~/.pi/agent/auth.json / 环境变量发现）:
  1. openrouter — z-ai/glm-5.2:free（免费模型）
  2. deepseek  — deepseek-chat（极便宜）
  3. moonshot  — moonshot-v1-8k / kimi（可选）
  4. custom    — OPENAI 兼容端点（TRANSLATE_BASE_URL/TRANSLATE_API_KEY/TRANSLATE_MODEL）

用法:
  python translate.py <transcript.srt|transcript.json> [--target en] [--backend auto]
                      [--out DIR] [--batch 40] [--pure] [--dry-run]
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HOME = Path.home()
AUTH_JSON = HOME / ".pi" / "agent" / "auth.json"


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- SRT 解析/生成

def srt_time(t):
    h, rem = divmod(float(t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def parse_srt(path: Path):
    content = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content.strip())
    cues = []
    for b in blocks:
        lines = [l for l in b.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = re.match(r"(\d+)", lines[0])
        tm = re.search(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})", " ".join(lines))
        if not tm:
            continue
        text = " ".join(lines[1:]) if not m or len(lines) < 3 else " ".join(lines[2:])
        # 更稳的提取：时间码行之后的都是文本
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None:
            continue
        text = " ".join(lines[ti + 1:]).strip()
        cues.append({"idx": m.group(1) if m else str(len(cues) + 1),
                     "start": tm.group(1).replace(",", ","),
                     "end": tm.group(2).replace(",", ","),
                     "text": text})
    return cues


def ts_to_seconds(ts):
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


def parse_json_segments(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{"idx": str(i + 1),
             "start": srt_time(s["start"]), "end": srt_time(s["end"]),
             "text": s["text"]}
            for i, s in enumerate(data.get("segments", []))]


def write_bilingual(cues, translations, out_path: Path, pure_only=False):
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues):
            tr = (translations.get(str(i)) or translations.get(c["idx"]) or "").strip()
            if not tr or tr.upper() in ("N/A", "NULL", "NONE"):
                tr = c["text"]  # 翻译缺失时保留原文
            f.write(f"{i + 1}\n{c['start']} --> {c['end']}\n{c['text']}\n{tr}\n\n")
            n += 1
    return n


def write_pure(cues, translations, out_path: Path, lang):
    with open(out_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues):
            tr = (translations.get(str(i)) or translations.get(c["idx"]) or "").strip() or c["text"]
            f.write(f"{i + 1}\n{c['start']} --> {c['end']}\n{tr}\n\n")


# ---------------------------------------------------------------- LLM 后端

def load_auth_keys():
    try:
        return {k: v.get("key", "") for k, v in
                json.loads(AUTH_JSON.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def discover_llm(args):
    auth = load_auth_keys()
    cands = []
    if args.backend in ("auto", "openrouter"):
        key = auth.get("openrouter", "") or os.environ.get("OPENROUTER_API_KEY", "")
        if key:
            cands.append(("openrouter", "https://openrouter.ai/api/v1", key,
                          args.model or "z-ai/glm-5.2:free"))
    if args.backend in ("auto", "deepseek"):
        key = auth.get("deepseek", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        if key:
            cands.append(("deepseek", "https://api.deepseek.com/v1", key,
                          args.model or "deepseek-chat"))
    if args.backend in ("auto", "moonshot"):
        key = auth.get("kimi-coding", "") or auth.get("moonshot", "") or os.environ.get("MOONSHOT_API_KEY", "")
        if key:
            cands.append(("moonshot", "https://api.moonshot.cn/v1", key,
                          args.model or "moonshot-v1-8k"))
    if args.backend == "custom" or (os.environ.get("TRANSLATE_BASE_URL") and args.backend == "auto"):
        base = args.base_url or os.environ.get("TRANSLATE_BASE_URL", "")
        key = args.api_key or os.environ.get("TRANSLATE_API_KEY", "")
        if base and key:
            cands.append(("custom", base.rstrip("/"), key,
                          args.model or os.environ.get("TRANSLATE_MODEL", "gpt-4o-mini")))

    for name, base, key, model in cands:
        try:
            r = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "user", "content": "ping"}],
                      "max_tokens": 4},
                timeout=30)
            if r.status_code == 200:
                return (name, base, key, model)
            eprint(f"[llm] {name}: 探测失败 HTTP {r.status_code}，跳过")
        except Exception as e:
            eprint(f"[llm] {name}: 不可达（{e}），跳过")
    return (None, "没有可用的 LLM 后端（openrouter/deepseek/moonshot 均未配置或不可达）")


def call_llm(base, key, model, messages, max_tokens=8000, retries=4):
    for attempt in range(retries):
        try:
            r = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": model, "messages": messages,
                      "temperature": 0.1, "max_tokens": max_tokens},
                timeout=180)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code in (429, 500, 502, 503, 504):
                wait = int(r.headers.get("Retry-After", 0)) or (15 * (attempt + 1))
                eprint(f"[llm] HTTP {r.status_code}，等 {wait}s 重试（{attempt + 1}/{retries}）")
                time.sleep(min(wait, 90))
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            eprint(f"[llm] 网络错误: {e}")
            time.sleep(10)
    raise RuntimeError("LLM 调用连续失败")


def extract_json(text):
    """从模型输出中稳健提取 JSON 对象。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("输出中未找到 JSON")
    return json.loads(m.group(0))


LANG_NAME = {"en": "English", "zh": "简体中文", "ja": "日本語", "ko": "한국어",
             "zh-TW": "繁體中文", "fr": "Français", "de": "Deutsch", "es": "Español"}


def translate_batch(base, key, model, items, target, batch_no, total_batches):
    """翻译一批字幕行。items: [(i, text)]，返回 {i: 译文}。"""
    lines = "\n".join(f'"{i}": {json.dumps(t, ensure_ascii=False)}' for i, t in items)
    tgt = LANG_NAME.get(target, target)
    sys_prompt = (
        f"You are a professional subtitle translator. Translate each subtitle line "
        f"into {tgt}. Preserve meaning and tone; keep it concise enough for subtitles. "
        f"Keep proper nouns, code, and technical terms accurate. "
        f"Respond with ONLY a JSON object mapping each id to its translation, no extra text.")
    user_prompt = f"Translate these subtitle lines (id → text):\n{{{lines}}}\n\nOutput JSON: {{\"<id>\": \"<{tgt} translation>\"}}"

    for attempt in range(3):
        out = call_llm(base, key, model,
                       [{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt}])
        try:
            data = extract_json(out)
            result = {}
            for i, _ in items:
                v = data.get(str(i))
                if isinstance(v, str) and v.strip():
                    result[str(i)] = v.strip()
            missing = [i for i, _ in items if str(i) not in result]
            if missing and attempt < 2:
                eprint(f"[batch {batch_no}/{total_batches}] 缺 {len(missing)} 行，重试…")
                continue
            return result
        except (ValueError, json.JSONDecodeError):
            if attempt < 2:
                eprint(f"[batch {batch_no}/{total_batches}] JSON 解析失败，重试…")
                continue
            raise
    return {}


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="字幕翻译 → 双语 SRT")
    ap.add_argument("input", help="transcript.srt 或 transcript.json")
    ap.add_argument("--target", default="en", help="目标语言（默认 en）")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "openrouter", "deepseek", "moonshot", "custom"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--out", default=None, help="输出目录（默认输入所在目录）")
    ap.add_argument("--batch", type=int, default=40, help="每批行数（默认 40）")
    ap.add_argument("--pure", action="store_true", help="同时输出纯译文字幕")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(json.dumps({"ok": False, "error": f"文件不存在: {src}"}, ensure_ascii=False))
        sys.exit(1)
    out_dir = Path(args.out) if args.out else src.parent

    cues = parse_srt(src) if src.suffix.lower() == ".srt" else parse_json_segments(src)
    if not cues:
        print(json.dumps({"ok": False, "error": "未解析到字幕行"}, ensure_ascii=False))
        sys.exit(1)
    eprint(f"[parse] {len(cues)} 条字幕")

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "cues": len(cues)}, ensure_ascii=False))
        return

    name, base, key, model = discover_llm(args)
    if name is None:
        print(json.dumps({"ok": False, "error": base}, ensure_ascii=False))
        sys.exit(2)
    eprint(f"[llm] 使用 {name} ({model})")

    translations = {}
    batches = [cues[i:i + args.batch] for i in range(0, len(cues), args.batch)]
    t0 = time.time()
    for bi, batch in enumerate(batches, 1):
        items = [(str(cues.index(c)), c["text"]) for c in batch]
        # 用全局索引，避免批次内 idx 冲突
        start_idx = (bi - 1) * args.batch
        items = [(str(start_idx + j), c["text"]) for j, c in enumerate(batch)]
        eprint(f"[translate] 批 {bi}/{len(batches)}（{len(batch)} 行）…")
        translations.update(translate_batch(base, key, model, items, args.target, bi, len(batches)))

    bi_path = out_dir / f"transcript.bilingual.srt"
    n = write_bilingual(cues, translations, bi_path)
    outputs = {"bilingual_srt": str(bi_path)}
    if args.pure:
        pure_path = out_dir / f"transcript.{args.target}.srt"
        write_pure(cues, translations, pure_path, args.target)
        outputs["pure_srt"] = str(pure_path)

    print(json.dumps({
        "ok": True, "backend": name, "model": model,
        "cues": len(cues), "translated": len(translations),
        "target": args.target, "elapsed_sec": round(time.time() - t0, 1),
        **outputs,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
