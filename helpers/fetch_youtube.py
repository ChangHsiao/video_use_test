"""從 YouTube 網址下載影片和字幕，字幕直接轉成 Scribe 格式的逐字稿。

用法：
    python fetch_youtube.py <網址> --out-dir <影片資料夾> [--name <檔名>] [--lang en] [--no-video]

產出：
    <影片資料夾>/<檔名>.mp4                     影片，優先 H.264＋AAC、最高 1080p
    <影片資料夾>/edit/transcripts/<檔名>.json   逐字稿，pack_transcripts.py 直接讀得到

用 YouTube 字幕當逐字稿不花轉錄額度。沒有字幕時本程式不會自動轉錄：
轉錄會花 ElevenLabs 額度，要先問使用者，再用 transcribe.py。

已經有同名的影片或逐字稿就跳過，不覆蓋（逐字稿可能已經手動改過）。
任何一項失敗，結束碼為 1。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yt_dlp

# 每個字最長只算這麼久。YouTube 字幕每個字只有開始時間，
# 用「下一個字的開始」當結束，長停頓前的字會拖得很長
MAX_WORD_S = 0.6

# H.264 優先：幾乎所有電腦和剪輯軟體都能順暢解碼。YouTube 預設常給 AV1（2026-11-05 實測），
# 沒有 AV1 硬體解碼的電腦，切片時每段都要靠 CPU 解碼，會很慢。代價是最高 1080p，直式短片夠用
VIDEO_FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]"
    "/b[vcodec^=avc1][height<=1080]"
    "/bv*[height<=1080]+ba/b"
)

# pack_transcripts.py 用 language_code 判斷中文、日文，要用 Scribe 的三碼
LANG_CODES = {"en": "eng", "zh": "zho", "ja": "jpn"}


def scribe_language_code(lang: str) -> str:
    """YouTube 的語言代碼（en、zh-TW、zh-Hant…）→ Scribe 的三碼；不認得的原樣回傳。"""
    return LANG_CODES.get(lang.split("-")[0].lower(), lang)


def json3_to_scribe(data: dict, lang: str, source: str) -> dict:
    """YouTube json3 字幕 → Scribe 格式。

    - 結束時間 = 下一個字的開始時間，最多 MAX_WORD_S 秒
    - 字和字之間有空檔就補一個 spacing（pack_transcripts.py 靠它判斷停頓、分句）
    - [Music] 這類方括號標記轉成 audio_event
    """
    events = data.get("events", [])
    tokens = []
    for ev in events:
        for seg in ev.get("segs", []):
            text = seg.get("utf8", "").strip()
            if text:
                tokens.append(((ev["tStartMs"] + seg.get("tOffsetMs", 0)) / 1000, text))
    tokens.sort(key=lambda t: t[0])
    last_ev = events[-1] if events else {"tStartMs": 0}
    media_end = (last_ev["tStartMs"] + last_ev.get("dDurationMs", 0)) / 1000

    words = []
    for i, (start, text) in enumerate(tokens):
        nxt = tokens[i + 1][0] if i + 1 < len(tokens) else media_end
        end = min(nxt, start + MAX_WORD_S)
        is_event = text.startswith("[") and text.endswith("]")
        words.append({
            "text": text.strip("[]") if is_event else text,
            "start": round(start, 3),
            "end": round(end, 3),
            "type": "audio_event" if is_event else "word",
            "speaker_id": "speaker_0",
        })
        if nxt > end:
            words.append({"text": " ", "start": round(end, 3), "end": round(nxt, 3),
                          "type": "spacing", "speaker_id": "speaker_0"})

    return {
        "language_code": scribe_language_code(lang),
        "language_probability": 1.0,
        "text": " ".join(w["text"] for w in words if w["type"] == "word"),
        "words": words,
        "transcription_id": f"youtube-captions:{source}",
        "audio_duration_secs": media_end,
    }


def explain_error(err: Exception, out_dir: Path) -> str:
    """把 yt-dlp 的錯誤翻成一行給使用者看的說明。"""
    msg = str(err)
    if "429" in msg or "Too Many Requests" in msg or "not a bot" in msg:
        return f"YouTube 暫時擋下載（{msg.splitlines()[0][:80]}）。請自己下載影片，放進 {out_dir}"
    if "unavailable" in msg.lower() or "does not exist" in msg.lower() or "Incomplete YouTube ID" in msg:
        return "找不到這支影片，請檢查網址"
    return f"下載失敗：{msg.splitlines()[0][:200]}"


def pick_track(tracks: dict, lang: str):
    """在字幕清單裡找 json3 格式：先找完全相同的語言，再找同語系（en → en-US）。"""
    keys = [lang] + sorted(k for k in tracks if k.split("-")[0] == lang.split("-")[0] and k != lang)
    for key in keys:
        for fmt in tracks.get(key) or []:
            if fmt.get("ext") == "json3":
                return key, fmt["url"]
    return None


def fetch_captions(ydl, info: dict, lang: str):
    """人工字幕優先，沒有才用自動字幕。回傳 (json3 dict, 說明)，沒有字幕回傳 None。"""
    for kind, tracks in (("人工字幕", info.get("subtitles") or {}),
                         ("自動字幕", info.get("automatic_captions") or {})):
        found = pick_track(tracks, lang)
        if found:
            key, url = found
            resp = ydl.urlopen(url)
            try:
                return json.loads(resp.read().decode("utf-8")), f"{kind} {key}"
            finally:
                resp.close()
    return None


def probe(path: Path) -> str:
    """ffprobe 讀編碼、尺寸、長度，印摘要用。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        data = json.loads(out.stdout)
        s = data["streams"][0]
        return f"{s['codec_name']} {s['width']}x{s['height']}，{float(data['format']['duration']):.1f} 秒"
    except (ValueError, KeyError, IndexError):
        return "（ffprobe 讀不到資訊）"


class _SilentLogger:
    """不讓 yt-dlp 自己印英文 ERROR／WARNING；錯誤由 explain_error 翻成中文印出。"""

    def debug(self, msg):
        pass

    warning = error = debug


def main() -> int:
    # Windows 終端機預設不是 UTF-8，中文訊息會變亂碼
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="下載 YouTube 影片和字幕（字幕轉成 Scribe 格式）")
    ap.add_argument("url")
    ap.add_argument("--out-dir", required=True, type=Path, help="影片資料夾")
    ap.add_argument("--name", help="檔名（不含副檔名）；預設用 YouTube 影片 ID")
    ap.add_argument("--lang", default="en", help="字幕語言，YouTube 的代碼，例如 en、zh-TW、ja（預設 en）")
    ap.add_argument("--no-video", action="store_true", help="只抓字幕（影片已經有了）")
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = True

    base_opts = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _SilentLogger()}
    with yt_dlp.YoutubeDL(base_opts) as ydl:
        try:
            info = ydl.extract_info(args.url, download=False)
        except yt_dlp.utils.DownloadError as err:
            print(explain_error(err, out_dir), file=sys.stderr)
            return 1

        name = args.name or info["id"]
        video_path = out_dir / f"{name}.mp4"
        transcript_path = out_dir / "edit" / "transcripts" / f"{name}.json"
        print(f"影片：{info.get('title', '')}（{info.get('duration', 0)} 秒）")

        # 逐字稿（檔案小、先做：影片被擋時至少還有逐字稿）
        if transcript_path.exists():
            print(f"已有逐字稿 {transcript_path}，跳過")
        else:
            try:
                found = fetch_captions(ydl, info, args.lang)
            except Exception as err:  # urlopen 也可能被 429 擋
                print(explain_error(err, out_dir), file=sys.stderr)
                found, ok = None, False
            if found:
                data, kind = found
                result = json3_to_scribe(data, args.lang, f"{info['id']}:{kind}")
                transcript_path.parent.mkdir(parents=True, exist_ok=True)
                transcript_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
                n_words = sum(w["type"] == "word" for w in result["words"])
                print(f"逐字稿（{kind}）：{n_words} 字，{result['audio_duration_secs']:.1f} 秒 -> {transcript_path}")
            elif ok:
                print(f"這支影片沒有 {args.lang} 字幕。要逐字稿得轉錄（會花額度），請先問使用者",
                      file=sys.stderr)
                ok = False

    # 影片
    if args.no_video:
        pass
    elif video_path.exists():
        print(f"已有影片 {video_path}，跳過")
    else:
        opts = {**base_opts, "format": VIDEO_FORMAT, "merge_output_format": "mp4",
                "outtmpl": str(out_dir / f"{name}.%(ext)s")}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([args.url])
            print(f"影片：{probe(video_path)} -> {video_path}")
        except yt_dlp.utils.DownloadError as err:
            print(explain_error(err, out_dir), file=sys.stderr)
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
