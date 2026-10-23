"""YouTube チャンネルの全動画から字幕（文字起こし）を取得する。"""
import json
import re
import subprocess
import sys
from pathlib import Path


def list_videos(channel_url: str, limit: int | None = None) -> list[dict]:
    """チャンネル内の動画 ID とタイトルを一覧する（ダウンロードはしない）。

    チャンネル URL には /videos を付けて取得するので、ショート動画（/shorts タブ）は含まれない。
    """
    url = channel_url.rstrip("/")
    if not re.search(r"/(videos|streams|shorts)$", url) and "list=" not in url:
        url += "/videos"
    cmd = ["yt-dlp", "--flat-playlist", "--dump-json", url]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    videos = []
    for line in out.splitlines():
        item = json.loads(line)
        if "/shorts/" in (item.get("url") or ""):
            continue
        videos.append({"id": item["id"], "title": item.get("title", "")})
    return videos


def vtt_to_text(vtt: str) -> str:
    """VTT 字幕からタイムスタンプ・タグ・自動字幕の重複行を除いた本文を作る。"""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def fetch_transcript(video_id: str, workdir: Path, lang: str = "ja") -> str | None:
    """手動字幕を優先し、無ければ自動生成字幕を取得する。どちらも無ければ None。"""
    tmp = workdir / "_vtt"
    tmp.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", lang, "--sub-format", "vtt",
        "-o", str(tmp / "%(id)s.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    subprocess.run(cmd, check=False, capture_output=True, text=True)
    files = sorted(tmp.glob(f"{video_id}*.vtt"))
    if not files:
        return None
    text = vtt_to_text(files[0].read_text(encoding="utf-8"))
    for f in files:
        f.unlink()
    return text or None


def crawl(channel_url: str, outdir: Path, limit: int | None = None) -> None:
    """outdir/transcripts/<id>.txt と outdir/videos.json を作る。取得済みはスキップする。"""
    tdir = outdir / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    videos = list_videos(channel_url, limit)
    print(f"{len(videos)} 本の動画を検出", file=sys.stderr)
    for i, v in enumerate(videos, 1):
        path = tdir / f"{v['id']}.txt"
        if path.exists():
            v["has_transcript"] = True
            continue
        text = fetch_transcript(v["id"], outdir)
        v["has_transcript"] = text is not None
        if text:
            path.write_text(text, encoding="utf-8")
        print(f"[{i}/{len(videos)}] {v['title']} {'OK' if text else '字幕なし'}", file=sys.stderr)
    (outdir / "videos.json").write_text(
        json.dumps({"channel": channel_url, "videos": videos}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
