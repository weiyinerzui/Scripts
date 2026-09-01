#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asr.py — 音频转写（多后端，免费优先）

后端（auto 模式按此顺序自动选择）:
  1. bcut        — 必剪云 ASR（B站官方，免费无 key，中文识别优秀，毫秒级时间戳）⭐
  2. groq        — Whisper large-v3-turbo（免费额度大，需 key: GROQ_API_KEY 或 ~/.pi/agent/auth.json）
  3. siliconflow — SenseVoiceSmall 中文（免费模型，需 key: SILICONFLOW_API_KEY）
  4. custom      — 任意 OpenAI 兼容端点（ASR_BASE_URL + ASR_API_KEY + ASR_MODEL）

bcut 实现参考 VideoCaptioner (github.com/WEIFENG2333/VideoCaptioner):
  分块 10 分钟 + 10 秒重叠，重叠中点切分合并；公益接口限流: 100 次/12h、音频 6h/12h（自动跟踪）。

用法:
  python asr.py <audio> [--out DIR] [--lang zh] [--backend auto|bcut|groq|siliconflow|custom]
                  [--chunk-min 10] [--overlap 10] [--concurrency 3] [--api-key KEY]
                  [--base-url URL] [--model MODEL] [--dry-run]

输出: transcript.srt / transcript.txt / transcript.json（stdout 输出 JSON 摘要）
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import subprocess
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
USAGE_FILE = HOME / ".bili-notes" / ".bcut_usage.json"

# ---------------------------------------------------------------- 常量

BCUT_API = "https://member.bilibili.com/x/bcut/rubick-interface"
BCUT_HEADERS = {
    "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
    "Content-Type": "application/json",
}
BCUT_RATE_MAX_CALLS = 100          # 12h 窗口内最多调用次数（公益接口限流）
BCUT_RATE_MAX_AUDIO = 360 * 60     # 12h 窗口内最多音频秒数
BCUT_RATE_WINDOW = 12 * 3600

BCUT_CHUNK_SEC = 600               # bcut 每块 10 分钟
BCUT_OVERLAP_SEC = 10              # 块间重叠 10 秒


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- bcut 限流跟踪

def bcut_usage_load():
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"calls": []}


def bcut_usage_window(usage):
    cutoff = time.time() - BCUT_RATE_WINDOW
    return [c for c in usage.get("calls", []) if c.get("ts", 0) >= cutoff]


def bcut_rate_check(need_sec):
    usage = bcut_usage_window(bcut_usage_load())
    n_calls = len(usage)
    n_sec = sum(c.get("dur", 0) for c in usage)
    if n_calls + 1 > BCUT_RATE_MAX_CALLS:
        return False, f"12h 内调用次数将达上限（{n_calls}/{BCUT_RATE_MAX_CALLS}），请稍后再试或换 --backend groq"
    if n_sec + need_sec > BCUT_RATE_MAX_AUDIO:
        return False, f"12h 内音频时长将达上限（{n_sec/60:.0f}min/{BCUT_RATE_MAX_AUDIO/60:.0f}min），请稍后再试或换 --backend groq"
    return True, ""


def bcut_rate_record(dur):
    usage = bcut_usage_load()
    usage["calls"] = bcut_usage_window(usage) + [{"ts": time.time(), "dur": dur}]
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(usage), encoding="utf-8")


# ---------------------------------------------------------------- 音频工具

def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def reencode_mp3(audio: Path, work_dir: Path):
    """重编码为 16kHz 单声道 mp3（bcut 要求 mp3；whisper 也友好）。"""
    full = work_dir / "full_16k.mp3"
    if full.exists() and full.stat().st_size > 1024:
        return full
    eprint("[audio] 重编码为 16kHz 单声道 mp3 …")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio), "-ac", "1", "-ar", "16000",
         "-b:a", "48k", str(full)],
        capture_output=True, text=True, timeout=7200)
    if r.returncode != 0 or not full.exists():
        raise RuntimeError(f"ffmpeg 重编码失败: {r.stderr[-300:]}")
    return full


def cut_chunks_with_overlap(full: Path, work_dir: Path, chunk_sec, overlap):
    """从重编码后的 mp3 切出带重叠的块（-c copy，快）。返回 [(path, offset)]。"""
    duration = ffprobe_duration(full)
    if duration <= 0:
        raise RuntimeError("无法读取音频时长")
    if chunk_sec <= overlap:
        raise ValueError("chunk 长度必须大于 overlap")
    step = int(chunk_sec - overlap)
    starts = list(range(0, max(1, int(math.ceil(duration)) - int(overlap)), step))
    # 保证最后能覆盖到结尾
    if starts and starts[-1] + chunk_sec < duration:
        starts.append(max(0, int(duration) - int(chunk_sec)))
    chunks = []
    for i, st in enumerate(starts):
        p = work_dir / f"bcut_{i:03d}.mp3"
        if not p.exists():
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(st), "-t", str(chunk_sec),
                 "-i", str(full), "-c", "copy", str(p)],
                capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not p.exists():
                raise RuntimeError(f"切块失败 {p.name}: {r.stderr[-200:]}")
        chunks.append((p, float(st)))
    return chunks, duration


def cut_chunks_plain(full: Path, work_dir: Path, chunk_sec, prefix="chunk"):
    """无重叠切块（whisper 类后端用）。返回 [(path, offset)]。"""
    duration = ffprobe_duration(full)
    n = max(1, math.ceil(duration / chunk_sec))
    chunks = []
    for i in range(n):
        st = i * chunk_sec
        p = work_dir / f"{prefix}_{i:03d}.mp3"
        if not p.exists():
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(st), "-t", str(chunk_sec),
                 "-i", str(full), "-c", "copy", str(p)],
                capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not p.exists():
                raise RuntimeError(f"切块失败 {p.name}: {r.stderr[-200:]}")
        chunks.append((p, float(st)))
    return chunks, duration


# ---------------------------------------------------------------- bcut 后端

def bcut_transcribe_blob(blob: bytes):
    """单次 bcut 转写（整块）。返回 utterances 列表（块内相对时间，毫秒）。"""
    # 1) 申请上传
    r = requests.post(
        f"{BCUT_API}/resource/create",
        data=json.dumps({"type": 2, "name": "audio.mp3", "size": len(blob),
                         "ResourceFileType": "mp3", "model_id": "8"}),
        headers=BCUT_HEADERS, timeout=30)
    r.raise_for_status()
    d = r.json()["data"]
    in_boss_key, resource_id, upload_id = d["in_boss_key"], d["resource_id"], d["upload_id"]
    urls, per_size = d["upload_urls"], d["per_size"]

    # 2) 分片上传（PUT）
    etags = []
    for i, u in enumerate(urls):
        part = blob[i * per_size:(i + 1) * per_size]
        pr = requests.put(u, data=part, headers=BCUT_HEADERS, timeout=300)
        pr.raise_for_status()
        etags.append(pr.headers.get("Etag", ""))

    # 3) 提交合并
    r = requests.post(
        f"{BCUT_API}/resource/create/complete",
        data=json.dumps({"InBossKey": in_boss_key, "ResourceId": resource_id,
                         "Etags": ",".join(etags), "UploadId": upload_id,
                         "model_id": "8"}),
        headers=BCUT_HEADERS, timeout=30)
    r.raise_for_status()
    download_url = r.json()["data"]["download_url"]

    # 4) 创建任务
    r = requests.post(f"{BCUT_API}/task",
                      json={"resource": download_url, "model_id": "8"},
                      headers=BCUT_HEADERS, timeout=30)
    r.raise_for_status()
    task_id = r.json()["data"]["task_id"]

    # 5) 轮询结果
    for _ in range(600):
        r = requests.get(f"{BCUT_API}/task/result",
                         params={"model_id": 7, "task_id": task_id},
                         headers=BCUT_HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json()["data"]
        if d.get("state") == 4:
            result = json.loads(d["result"])
            return result.get("utterances", [])
        if d.get("state", 0) < 0 or d.get("state") == 5:
            raise RuntimeError(f"bcut 任务失败: state={d.get('state')}")
        time.sleep(1)
    raise RuntimeError("bcut 任务轮询超时（10 分钟）")


def run_bcut(full: Path, work_dir: Path, out_dir: Path, args):
    chunks, duration = cut_chunks_with_overlap(
        full, work_dir, args.chunk_min * 60, args.overlap)
    total_sec = sum(ffprobe_duration(c) for c, _ in chunks)
    eprint(f"[bcut] 总时长 {duration/60:.1f} 分钟 → {len(chunks)} 块（含重叠共 {total_sec/60:.1f} 分钟）")

    ok, why = bcut_rate_check(total_sec)
    if not ok:
        raise RuntimeError(f"bcut 限流: {why}")

    def do_chunk(item):
        idx, (path, offset) = item
        dur = ffprobe_duration(path)
        for attempt in range(3):
            try:
                utterances = bcut_transcribe_blob(path.read_bytes())
                segs = [{"start": (u["start_time"] / 1000) + offset,
                         "end": (u["end_time"] / 1000) + offset,
                         "text": (u.get("transcript") or "").strip()}
                        for u in utterances if (u.get("transcript") or "").strip()]
                return idx, segs, dur
            except Exception as e:
                eprint(f"[bcut] 块 {idx + 1} 失败（{attempt + 1}/3）: {e}")
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"bcut 块 {idx + 1} 连续失败")

    results = [None] * len(chunks)
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(do_chunk, (i, item)): i for i, item in enumerate(chunks)}
        done_n = 0
        for fut in cf.as_completed(futs):
            idx, segs, dur = fut.result()
            results[idx] = segs
            bcut_rate_record(dur)
            done_n += 1
            eprint(f"[bcut] {done_n}/{len(chunks)} 块完成（{len(segs)} 段）")

    # 合并：重叠中点切分
    merged = []
    for i, (segs, (path, offset)) in enumerate(zip(results, chunks)):
        if not segs:
            continue
        if i == 0:
            merged.extend(segs)
        else:
            prev_end = merged[-1]["end"] if merged else offset
            mid = offset + args.overlap / 2  # 重叠区中点（近似）
            merged.extend(s for s in segs if s["start"] >= mid - 0.05)
    merged.sort(key=lambda s: s["start"])
    merged = dedup_boundary(merged)
    merged = [s for s in merged if s["text"]]
    return merged, {"backend": "bcut", "model": "bcut-rubick (B站必剪云ASR)",
                    "chunks": len(chunks), "overlap": args.overlap,
                    "elapsed": round(time.time() - t0, 1)}


def dedup_boundary(segs):
    """去除分块边界重复：相邻两句文本相同/相似，且第二句在第一句说完前就开始 → 同一句被两块各转了一次。"""
    from difflib import SequenceMatcher
    out = []
    for s in segs:
        if out:
            prev = out[-1]
            dur = max(prev["end"] - prev["start"], 0.5)
            similar = (prev["text"] == s["text"]) or \
                SequenceMatcher(None, prev["text"], s["text"]).ratio() > 0.8
            starts_close = (s["start"] - prev["start"]) < dur + 1.0
            if similar and starts_close:
                # 保留时间更长的一份
                if (s["end"] - s["start"]) > (prev["end"] - prev["start"]):
                    out[-1] = s
                continue
        out.append(s)
    return out


# ---------------------------------------------------------------- OpenAI 兼容后端

def load_auth_keys():
    try:
        return {k: v.get("key", "") for k, v in
                json.loads(AUTH_JSON.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def discover_oai_backend(args):
    """返回 (name, base, key, model) 或 (None, 原因)。"""
    auth = load_auth_keys()
    cands = []
    if args.backend in ("groq",):
        key = args.api_key or os.environ.get("GROQ_API_KEY") or auth.get("groq", "")
        cands.append(("groq", "https://api.groq.com/openai/v1", key,
                      args.model or "whisper-large-v3-turbo"))
    if args.backend in ("siliconflow",):
        key = args.api_key or os.environ.get("SILICONFLOW_API_KEY") or ""
        cands.append(("siliconflow", "https://api.siliconflow.cn/v1", key,
                      args.model or "FunAudioLLM/SenseVoiceSmall"))
    if args.backend in ("custom",):
        base = args.base_url or os.environ.get("ASR_BASE_URL", "")
        key = args.api_key or os.environ.get("ASR_API_KEY", "")
        if base and key:
            cands.append(("custom", base.rstrip("/"), key,
                          args.model or os.environ.get("ASR_MODEL", "whisper-large-v3")))
        else:
            return (None, "custom 后端需要 --base-url 与 --api-key（或 ASR_BASE_URL/ASR_API_KEY）")
    for name, base, key, model in cands:
        if not key:
            return (None, f"{name}: 未找到 API key")
        try:
            r = requests.get(f"{base}/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=20)
            if r.status_code in (200, 404, 405):
                return (name, base, key, model)
            return (None, f"{name}: key 无效（HTTP {r.status_code}）")
        except Exception as e:
            return (None, f"{name}: 不可达（{e}）")
    return (None, "未知后端")


def oai_transcribe_chunk(base, key, model, chunk: Path, lang, prompt):
    url = f"{base}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {key}"}
    for attempt in range(5):
        try:
            with open(chunk, "rb") as f:
                files = {"file": (chunk.name, f, "audio/mpeg")}
                data = {"model": model, "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment"}
                if lang:
                    data["language"] = lang
                if prompt:
                    data["prompt"] = prompt[:224]
                r = requests.post(url, headers=headers, files=files, data=data, timeout=600)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                wait = int(r.headers.get("Retry-After", 0)) or (10 * (attempt + 1))
                eprint(f"[asr] HTTP {r.status_code}，{wait}s 后重试 …")
                time.sleep(min(wait, 60))
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            eprint(f"[asr] 网络错误: {e}，重试 …")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"块 {chunk.name} 转写失败（已重试 5 次）")


def synth_segments_from_text(text, offset, chunk_dur):
    """后端只返回纯文本时：按句切分、按字数比例近似分配时间。"""
    import re
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；;.])\s*", text) if s.strip()]
    if not sentences:
        return []
    total = sum(len(s) for s in sentences) or 1
    segs, t = [], offset
    for s in sentences:
        d = chunk_dur * len(s) / total
        segs.append({"start": round(t, 3), "end": round(t + d, 3), "text": s})
        t += d
    return segs


def run_oai(full: Path, work_dir: Path, args):
    found = discover_oai_backend(args)
    if found[0] is None:
        raise RuntimeError(found[1])
    name, base, key, model = found
    eprint(f"[backend] 使用 {name} ({model} @ {base})")
    chunk_sec = 15 * 60 if name in ("groq", "custom") else 10 * 60
    chunks, duration = cut_chunks_plain(full, work_dir, chunk_sec, prefix=f"{name}_c")
    eprint(f"[{name}] 总时长 {duration/60:.1f} 分钟 → {len(chunks)} 块")

    all_segs, approx, carry = [], False, ""
    t0 = time.time()
    for i, (path, offset) in enumerate(chunks):
        eprint(f"[{name}] 转写块 {i + 1}/{len(chunks)} …")
        resp = oai_transcribe_chunk(base, key, model, path, args.lang, carry)
        segs = resp.get("segments") or []
        if segs:
            for s in segs:
                txt = (s.get("text") or "").strip()
                if txt:
                    all_segs.append({"start": float(s.get("start", 0)) + offset,
                                     "end": float(s.get("end", 0)) + offset,
                                     "text": txt})
            carry = " ".join(s["text"] for s in all_segs[-3:])
        else:
            text = (resp.get("text") or "").strip()
            if text:
                all_segs.extend(synth_segments_from_text(text, offset, ffprobe_duration(path)))
                approx = True
                carry = text[-224:]
    return all_segs, {"backend": name, "model": model, "chunks": len(chunks),
                      "approx_timestamps": approx,
                      "elapsed": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- 输出

def srt_time(t):
    h, rem = divmod(float(t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def write_outputs(segments, out_dir: Path, meta):
    srt_path = out_dir / "transcript.srt"
    txt_path = out_dir / "transcript.txt"
    json_path = out_dir / "transcript.json"
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n{seg['text']}\n\n")
    text = ""
    for seg in segments:
        t = seg["text"].rstrip()
        if t:
            text += t + ("\n" if len(t) > 40 else " ")
    txt_path.write_text(text.strip(), encoding="utf-8")
    json_path.write_text(json.dumps({"meta": meta, "segments": segments},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    return srt_path, txt_path, json_path


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="音频转写（免费 API 多后端，bcut 优先）")
    ap.add_argument("audio")
    ap.add_argument("--out", default=None)
    ap.add_argument("--lang", default=None, help="语言提示 zh/en（bcut 忽略，自动识别）")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "bcut", "groq", "siliconflow", "custom"])
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--chunk-min", type=float, default=10, help="每块分钟数（默认 10）")
    ap.add_argument("--overlap", type=float, default=10, help="bcut 块重叠秒数（默认 10）")
    ap.add_argument("--concurrency", type=int, default=3, help="bcut 并发数（默认 3）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print(json.dumps({"ok": False, "error": f"音频不存在: {audio}"}, ensure_ascii=False))
        sys.exit(1)
    out_dir = Path(args.out) if args.out else audio.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / ".asr_work"
    work_dir.mkdir(exist_ok=True)

    full = reencode_mp3(audio, work_dir)
    duration = ffprobe_duration(full)

    if args.dry_run:
        chunks, _ = cut_chunks_with_overlap(full, work_dir, args.chunk_min * 60, args.overlap)
        print(json.dumps({"ok": True, "dry_run": True, "duration_min": round(duration / 60, 1),
                          "chunks": len(chunks)}, ensure_ascii=False))
        return

    # 后端选择
    segments, meta, errors = None, None, []
    order = []
    if args.backend == "auto":
        order = ["bcut", "groq", "siliconflow", "custom"]
    else:
        order = [args.backend]
    for be in order:
        try:
            if be == "bcut":
                segments, meta = run_bcut(full, work_dir, out_dir, args)
            else:
                if be in ("groq", "siliconflow", "custom"):
                    segments, meta = run_oai(full, work_dir, args)
                else:
                    continue
            if segments:
                meta["language"] = args.lang
                break
        except Exception as e:
            errors.append(f"{be}: {e}")
            eprint(f"[backend] {be} 失败 → {e}")
            segments, meta = None, None

    if not segments:
        print(json.dumps({"ok": False, "error": "所有后端均失败", "errors": errors},
                         ensure_ascii=False, indent=2))
        sys.exit(2)

    srt, txt, jsn = write_outputs(segments, out_dir, meta)
    print(json.dumps({
        "ok": True,
        "backend": meta["backend"], "model": meta.get("model"),
        "segments": len(segments),
        "duration_hms": srt_time(duration)[:-4],
        "elapsed_sec": meta.get("elapsed"),
        "srt": str(srt), "txt": str(txt), "json": str(jsn),
        "out_dir": str(out_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
