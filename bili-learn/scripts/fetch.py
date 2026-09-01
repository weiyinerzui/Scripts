#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch.py — B站/通用视频资源抓取（yt-dlp 封装）

功能:
  1. 元数据: 标题/UP主/时长/简介/章节/封面 → info.json + cover.jpg
  2. 字幕:   官方CC/AI字幕 → subs/*.srt（需要登录 cookies，自动尝试多种来源）
  3. 音频:   bestaudio → audio.m4a（匿名即可下载）
  4. 弹幕:   --danmaku → danmaku.xml（可选，用于分析观众关注点）

用法:
  python fetch.py <URL> [--out DIR] [--cookies FILE] [--browser edge|chrome|firefox]
                   [--no-audio] [--danmaku]

stdout 输出 JSON 结果摘要（供 agent 读取），过程日志走 stderr。
退出码: 0 = 至少拿到元数据; 1 = 失败
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HOME = Path.home()


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- cookies 链

def cookie_candidates(args):
    """返回 [(kind, value), ...] 尝试链。

    默认只走 匿名 + cookies文件（本机 Chrome/Edge DPAPI 解密失效，浏览器尝试
    只会白白消耗B站风控额度）；--browser 显式指定时才尝试浏览器。
    """
    cands = []
    if args.cookies:
        cands.append(("file", args.cookies))
    else:
        for p in (HOME / ".pi" / "bili-cookies.txt", HOME / "bili-cookies.txt"):
            if p.exists():
                cands.append(("file", str(p)))
                eprint(f"[cookies] 使用 cookies 文件: {p}")
                break
    if args.browser:
        for b in ([args.browser] if isinstance(args.browser, str) else args.browser):
            cands.append(("browser", b))
    cands.append(("none", None))
    return cands


def cookie_label(cookie):
    kind, val = cookie
    if kind == "file":
        return f"file:{val}"
    if kind == "browser":
        return f"browser:{val}"
    return "anonymous"


def ytdlp(opts, url, cookie=None, timeout=7200):
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist"]
    if cookie:
        kind, val = cookie
        if kind == "file":
            cmd += ["--cookies", val]
        elif kind == "browser":
            cmd += ["--cookies-from-browser", val]
    cmd += opts + [url]
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def clean_err(r):
    """去掉 stderr 里的 RequestsDependencyWarning 等噪音，保留真实错误。"""
    lines = [l for l in (r.stderr or "").splitlines()
             if "RequestsDependencyWarning" not in l and "warnings.warn" not in l
             and l.strip()]
    return "\n".join(lines)[-400:]


# ---------------------------------------------------------------- 字幕工具

def srt_time(t):
    h, rem = divmod(float(t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def bilibili_json_to_srt(json_path: Path, srt_path: Path) -> bool:
    """B站 json 字幕 → srt。格式: {"body":[{"from":..,"to":..,"content":..}]}"""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        body = data.get("body") or []
        if not body:
            return False
        lines = []
        for i, item in enumerate(body, 1):
            content = (item.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"{i}\n{srt_time(item.get('from', 0))} --> {srt_time(item.get('to', 0))}\n{content}\n")
        if not lines:
            return False
        srt_path.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        eprint(f"[subs] json→srt 转换失败 {json_path.name}: {e}")
        return False


def find_srt(subs_dir: Path):
    return sorted(subs_dir.glob("*.srt")) if subs_dir.exists() else []


def convert_json_subs(subs_dir: Path):
    """把遗留的 .json 字幕转成 .srt（B站 AI 字幕有时是 json 格式）。"""
    if not subs_dir.exists():
        return
    for j in subs_dir.glob("*.json"):
        target = j.with_suffix(".srt")
        if target.exists():
            continue
        if bilibili_json_to_srt(j, target):
            eprint(f"[subs] json→srt: {j.name} -> {target.name}")


# ---------------------------------------------------------------- 主流程

def fetch_metadata(url, cookie_chain, retries=3):
    """返回 (info_dict, used_cookie) 。先匿名（带 412 退避重试），失败再带 cookies 逐个试。"""
    last_err = ""
    attempts = [("none", None)] + [c for c in cookie_chain if c[0] != "none"]
    for attempt_round in range(retries):
        for cookie in attempts:
            r = ytdlp(["--dump-single-json"], url,
                      cookie if cookie[0] != "none" else None, timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                try:
                    info = json.loads(r.stdout.strip().splitlines()[-1])
                    return info, cookie
                except Exception:
                    pass
            last_err = clean_err(r)
            # B站风控(412)：退避后重试匿名
            if "412" in (r.stderr or ""):
                wait = 20 * (attempt_round + 1)
                eprint(f"[meta] B站风控(412)，等 {wait}s 后重试（{attempt_round + 1}/{retries}）…")
                time.sleep(wait)
                break
        else:
            continue
    return None, last_err


def try_subtitles(url, out_dir: Path, cookie_chain):
    """尝试各 cookies 来源下载字幕，返回 (srt_files, used_label, notes)。先匿名（快），再带 cookies。"""
    notes = []
    subs_dir = out_dir / "subs"
    subs_dir.mkdir(parents=True, exist_ok=True)
    ordered = [c for c in cookie_chain if c[0] == "none"] + \
              [c for c in cookie_chain if c[0] != "none"]
    for cookie in ordered:
        label = cookie_label(cookie)
        if cookie[0] == "none":
            eprint("[subs] 尝试匿名获取字幕…")
        else:
            eprint(f"[subs] 尝试获取字幕 (cookies: {label}) …")
        r = ytdlp(
            ["--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", "all,-danmaku", "--convert-subs", "srt",
             "-o", str(subs_dir / "%(id)s.%(ext)s")],
            url, cookie if cookie[0] != "none" else None, timeout=300)
        convert_json_subs(subs_dir)
        srts = find_srt(subs_dir)
        if srts:
            return srts, label, notes
        err = (r.stderr or "")
        if "412" in err:
            time.sleep(15)
            notes.append("B站风控(412)，已退避重试")
        elif "log in" in err.lower() or "cookies" in err.lower():
            notes.append(f"字幕需要登录（{label} 未提供有效 cookies）")
        elif err.strip():
            notes.append(f"{label}: 无可用字幕")
    return [], "none", notes or ["视频没有可用字幕（可能未开启AI字幕或需要登录cookies）"]


def download_audio(url, out_dir: Path, cookie_chain):
    """下载 bestaudio → audio.m4a。返回路径或 None。"""
    target = out_dir / "audio.m4a"
    if target.exists() and target.stat().st_size > 10240:
        return target
    for cookie in cookie_chain:
        label = cookie_label(cookie)
        eprint(f"[audio] 下载音频 (cookies: {label}) …")
        r = ytdlp(
            ["-f", "bestaudio", "-x", "--audio-format", "m4a",
             "--audio-quality", "5", "-o", str(out_dir / "audio.%(ext)s")],
            url, cookie if cookie[0] != "none" else None, timeout=7200)
        if target.exists() and target.stat().st_size > 10240:
            return target
        # 兼容其他扩展名
        for f in out_dir.glob("audio.*"):
            if f.suffix.lower() in (".m4a", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".webm"):
                return f
        if r.returncode != 0:
            eprint(f"[audio] 失败: {clean_err(r)}")
            time.sleep(3)
    return None


def download_danmaku(url, out_dir: Path, cookie_chain):
    for cookie in cookie_chain:
        r = ytdlp(
            ["--skip-download", "--write-subs", "--sub-langs", "danmaku",
             "-o", str(out_dir / "danmaku.%(ext)s")],
            url, cookie if cookie[0] != "none" else None, timeout=300)
        for f in out_dir.glob("danmaku*"):
            return f
    return None


def download_cover(info, out_dir: Path):
    thumb = info.get("thumbnail")
    if not thumb:
        return None
    cover = out_dir / "cover.jpg"
    try:
        req = urllib.request.Request(thumb, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(cover, "wb") as f:
            f.write(resp.read())
        return cover if cover.stat().st_size > 1000 else None
    except Exception as e:
        eprint(f"[cover] 封面下载失败: {e}")
        return None


def fmt_duration(sec):
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description="B站/视频资源抓取")
    ap.add_argument("url", help="视频 URL（bilibili.com / b23.tv 等）")
    ap.add_argument("--out", default=None, help="输出目录（默认 ~/bili-notes/<id>）")
    ap.add_argument("--cookies", default=None, help="cookies.txt 文件路径")
    ap.add_argument("--browser", default=None,
                    help="从浏览器取 cookies（仅必要时显式指定，如 edge/chrome/firefox）")
    ap.add_argument("--no-audio", action="store_true", help="不下载音频")
    ap.add_argument("--danmaku", action="store_true", help="下载弹幕")
    args = ap.parse_args()

    url = args.url.strip()
    cookie_chain = cookie_candidates(args)

    # --- 元数据（匿名优先，412 退避重试） ---
    info, meta_cookie = fetch_metadata(url, cookie_chain)
    if info is None:
        eprint(f"[meta] 元数据获取失败: {meta_cookie}")
        print(json.dumps({"ok": False, "error": "元数据获取失败，请检查链接是否有效（部分视频需登录或为会员专享）；若频繁请求触发B站风控(412)，请等待几分钟再试"}, ensure_ascii=False))
        sys.exit(1)
    time.sleep(2)

    vid = info.get("id") or "video"
    title = info.get("title") or vid
    out_dir = Path(args.out) if args.out else HOME / "bili-notes" / re.sub(r'[\\/:*?"<>|]', "_", vid)
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = info.get("duration") or 0
    meta = {
        "id": vid,
        "title": title,
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration_sec": duration,
        "duration_hms": fmt_duration(duration),
        "upload_date": info.get("upload_date") or "",
        "webpage_url": info.get("webpage_url") or url,
        "description": (info.get("description") or "")[:2000],
        "chapters": [{"title": c.get("title"), "start_time": c.get("start_time")}
                     for c in (info.get("chapters") or [])],
        "pages": len(info.get("entries") or []) or 1,
    }
    (out_dir / "info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    cover = download_cover(info, out_dir)
    eprint(f"[meta] {title} | UP: {meta['uploader']} | 时长: {meta['duration_hms']}")

    # --- 字幕 ---
    srts, cookie_used, sub_notes = try_subtitles(url, out_dir, cookie_chain)
    time.sleep(2)

    # --- 音频 ---
    audio_path = None
    if not args.no_audio:
        audio_path = download_audio(url, out_dir, cookie_chain)
        if audio_path:
            eprint(f"[audio] 音频已保存: {audio_path}")

    # --- 弹幕 ---
    danmaku_path = None
    if args.danmaku:
        danmaku_path = download_danmaku(url, out_dir, cookie_chain)

    result = {
        "ok": True,
        "video_id": vid,
        "title": title,
        "uploader": meta["uploader"],
        "duration": meta["duration_hms"],
        "out_dir": str(out_dir),
        "info_json": str(out_dir / "info.json"),
        "cover": str(cover) if cover else None,
        "subs_found": [str(s) for s in srts],
        "cookies_used": cookie_used if srts else "none",
        "audio": str(audio_path) if audio_path else None,
        "danmaku": str(danmaku_path) if danmaku_path else None,
        "notes": sub_notes,
        "next": "字幕已就绪，直接进入笔记生成" if srts
                else ("无字幕，需用 asr.py 转录音频" if audio_path else "无字幕且音频下载失败"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
