"""Render a video from an EDL.

Implements the HEURISTICS render pipeline in the correct order:

  1. Per-segment extract with color grade + 30ms audio fades baked in
  2. Lossless -c copy concat into base.mp4
  3. If overlays or subtitles: single filter graph that overlays animations
     (with PTS shift so frame 0 lands at the overlay window start)
     and applies `subtitles` filter LAST → final.mp4

Optionally builds a master SRT from the per-source transcripts + EDL
output-timeline offsets, applies the proven force_style (2-word
UPPERCASE chunks, Helvetica 18 Bold, MarginV=35).

Usage:
    python helpers/render.py <edl.json> -o final.mp4
    python helpers/render.py <edl.json> -o preview.mp4 --preview
    python helpers/render.py <edl.json> -o final.mp4 --build-subtitles
    python helpers/render.py <edl.json> -o final.mp4 --no-subtitles
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

try:
    from grade import get_preset, auto_grade_for_clip  # same directory
except Exception:
    def get_preset(name: str) -> str:
        return ""

    def auto_grade_for_clip(video, start=0.0, duration=None, verbose=False):  # type: ignore
        return "eq=contrast=1.03:saturation=0.98", {}

# helpers/ is only on sys.path when render.py runs as a script; tests load it by file path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zh_text import (  # noqa: E402
    ZH_PUNCT_BREAK,
    ZH_TRAILING_STRIP,
    display_width,
    inner_punct_to_space,
    is_number,
    is_punct,
    join_zh,
    looks_chinese,
    starts_cjk,
    to_traditional,
    transcript_lang,
    word_boundaries,
)


# -------- Subtitle style (bold-overlay, proven at 1920×1080 and 1080×1920) --
#
# MarginV is NOT taste — it is a platform safe-zone rule.
# TikTok / IG Reels / Shorts UI (caption, username, music, right-rail actions)
# covers roughly the bottom ~25–30% of a 1080×1920 frame. Captions placed near
# the bottom edge get clipped or obscured by the UI. libass auto-scales the
# render canvas relative to PlayResY=288, so MarginV=90 lands the caption
# baseline roughly 30% up from the bottom on any aspect — clear of the UI on
# every major vertical-video platform. Do not drop this below ~75 without a
# specific reason.
SUB_FORCE_STYLE = (
    "FontName=Helvetica,FontSize=18,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=90"
)

# 上面的安全區規則只針對直式短影音。橫式沒有 App 按鈕，MarginV=90 會把字幕放在
# 人物胸口，所以橫式和方形改成離底部約 8%（一般字幕安全範圍是離邊緣 5～10%）。
# 畫面在 render.py 之後才裁切時（16:9 算繪後依鏡頭裁成 9:16），量到的比例不對，
# 用 --sub-margin 指定。
SUB_MARGIN_V_PORTRAIT = 90
SUB_MARGIN_PCT_LANDSCAPE = 8
SUB_PLAY_RES_Y = 288  # libass renders SRT on this canvas height; MarginV is in these units


def sub_margin_v(width: int | None, height: int | None, pct: float | None = None) -> int:
    """字幕離底部的 MarginV。pct（--sub-margin，畫面高度的百分比）優先；
    量不到尺寸或直式時用官方的 90；橫式和方形用 SUB_MARGIN_PCT_LANDSCAPE。"""
    if pct is not None:
        return round(SUB_PLAY_RES_Y * pct / 100)
    if not width or not height or height > width:
        return SUB_MARGIN_V_PORTRAIT
    return round(SUB_PLAY_RES_Y * SUB_MARGIN_PCT_LANDSCAPE / 100)

# -------- Helpers ------------------------------------------------------------


def run(cmd: list[str], quiet: bool = False) -> None:
    if not quiet:
        print(f"  $ {' '.join(str(c) for c in cmd[:6])}{' …' if len(cmd) > 6 else ''}")
    subprocess.run(cmd, check=True)


def resolve_grade_filter(grade_field: str | None) -> str:
    """The EDL's 'grade' field can be a preset name, a raw ffmpeg filter, or 'auto'.

    Returns the filter string to embed into the per-segment -vf chain.
    For 'auto', returns the sentinel "__AUTO__" which is resolved per-segment.
    """
    if not grade_field:
        return ""
    if grade_field == "auto":
        return "__AUTO__"
    # Preset names are short identifiers, filter strings contain '=' or ','.
    if re.fullmatch(r"[a-zA-Z0-9_\-]+", grade_field):
        try:
            return get_preset(grade_field)
        except KeyError:
            print(f"warning: unknown preset '{grade_field}', using as raw filter")
            return grade_field
    return grade_field


def resolve_path(maybe_path: str, base: Path) -> Path:
    """Resolve a path that may be absolute or relative to `base`."""
    p = Path(maybe_path)
    if p.is_absolute():
        return p
    return (base / p).resolve()


def resolve_subtitles_path(maybe_path: str, edit_dir: Path) -> Path:
    """Resolve the EDL's subtitles path: relative to the EDL's directory, else the
    current directory (agents often write "edit/master.srt"). A missing file is an
    error: rendering on without it silently ships a video with no captions."""
    candidates = [resolve_path(maybe_path, edit_dir)]
    if not Path(maybe_path).is_absolute():
        candidates.append(Path(maybe_path).resolve())
    for c in candidates:
        if c.exists():
            return c
    tried = ", ".join(str(c) for c in candidates)
    sys.exit(f"subtitles file in EDL not found (tried {tried}). Fix the path or pass --no-subtitles.")


# -------- HDR → SDR tone mapping (HLG / PQ sources) --------------------------
#
# iPhone defaults to HLG HDR in Rec.2020 (and many mirrorless cameras ship PQ).
# If the source is HDR and we only downconvert bit depth (yuv420p10le → yuv420p)
# without tone-mapping, the output is 8-bit but still carries HLG/PQ transfer
# metadata. Players that honor the metadata (screen recorders, most social
# upload re-encodes) interpret 8-bit values in an HDR container and the result
# looks oversaturated / blown out. QuickTime on macOS can hide this locally —
# screen recording and uploaded renders cannot.
#
# Fix: detect HDR via color_transfer and prepend a zscale+tonemap chain to the
# vf graph so the output is clean Rec.709 SDR.

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10) and HLG

TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)


def is_hdr_source(video: Path) -> bool:
    """Return True if the source uses a PQ or HLG transfer function."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() in HDR_TRANSFERS
    except subprocess.CalledProcessError:
        return False


def probe_dimensions(video: Path) -> tuple[int, int] | None:
    """Width and height of a rendered video's first stream, or None if ffprobe fails."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        stream = (json.loads(out.stdout).get("streams") or [{}])[0]
        return int(stream["width"]), int(stream["height"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError, FileNotFoundError):
        return None


def is_portrait_source(video: Path) -> bool:
    """Return True if the displayed video is portrait, including rotation."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries",
             "stream=width,height:stream_side_data=rotation",
             "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(out.stdout).get("streams") or []
        if not streams:
            return False
        stream = streams[0]
        w, h = int(stream["width"]), int(stream["height"])

        # ffmpeg autorotates display-matrix side data before applying filters.
        # Swap coded dimensions for quarter-turns so the scale axis is selected
        # from the dimensions the filter actually sees. A plain metadata tag is
        # intentionally ignored because it does not guarantee autorotation.
        rotation = 0
        for side_data in stream.get("side_data_list") or []:
            if side_data.get("rotation") is not None:
                rotation = side_data["rotation"]
                break
        if int(round(float(rotation))) % 360 in (90, 270):
            w, h = h, w
        return h > w
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        OSError,
        OverflowError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return False


def parse_fps(value: str) -> str:
    """Validate and canonicalize an ffmpeg frame rate."""
    text = value.strip()
    if len(text) > 32 or not re.fullmatch(
        r"(?:[0-9]+(?:\.[0-9]+)?|[0-9]+/[0-9]+)", text
    ):
        raise argparse.ArgumentTypeError(
            "FPS must be a positive number or rational, e.g. 30 or 30000/1001"
        )
    try:
        rate = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError(
            "FPS must be a positive number or rational, e.g. 30 or 30000/1001"
        ) from exc
    if rate <= 0:
        raise argparse.ArgumentTypeError("FPS must be greater than zero")
    # FFmpeg stores video rates as AVRational (signed 32-bit components).
    # Bounding the reduced fraction keeps every accepted canonical value safe
    # for ffmpeg and makes parse_fps(parse_fps(value)) idempotent.
    max_component = 2_147_483_647
    if rate.numerator > max_component or rate.denominator > max_component:
        raise argparse.ArgumentTypeError("FPS precision or magnitude is too large")
    return f"{rate.numerator}/{rate.denominator}"


def probe_source_fps(video: Path) -> str | None:
    """Return an ffmpeg-ready source rate, preferring the average frame rate.

    ``avg_frame_rate`` represents the observed average and is the better default
    for variable-frame-rate inputs. ``r_frame_rate`` remains a fallback for
    streams where the average is unavailable. Values are normalized to an exact
    rational so rates such as ``30000/1001`` survive without rounding.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate,r_frame_rate",
             "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(out.stdout).get("streams") or []
        if not streams:
            return None
        for field in ("avg_frame_rate", "r_frame_rate"):
            value = streams[0].get(field)
            if value and value != "0/0":
                try:
                    return parse_fps(value)
                except argparse.ArgumentTypeError:
                    continue
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return None
    return None


# -------- Per-segment extraction (Rule 2 + Rule 3) --------------------------


def extract_segment(
    source: Path,
    seg_start: float,
    duration: float,
    grade_filter: str,
    out_path: Path,
    preview: bool = False,
    draft: bool = False,
    rate: str | None = None,
) -> None:
    """Extract a cut range as its own MP4 with grade + 30ms audio fades baked in.

    `-ss` before `-i` for fast accurate seeking. Scale to 1080p from 4K.
    Portrait sources (height > width) are scaled by height to preserve orientation.

    Quality ladder:
      - final (default): 1080p libx264 fast CRF 20
      - preview:         1080p libx264 medium CRF 22 (evaluable for QC)
      - draft:           720p libx264 ultrafast CRF 28 (cut-point check only)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    portrait = is_portrait_source(source)
    if draft:
        scale = "scale=-2:1280" if portrait else "scale=1280:-2"
    else:
        scale = "scale=-2:1920" if portrait else "scale=1920:-2"

    vf_parts: list[str] = []
    if is_hdr_source(source):
        vf_parts.append(TONEMAP_CHAIN)
    vf_parts.append(scale)
    if grade_filter:
        vf_parts.append(grade_filter)
    vf = ",".join(vf_parts)

    # 30ms audio fades at both edges (Rule 3) — prevent pops
    fade_out_start = max(0.0, duration - 0.03)
    af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_start:.3f}:d=0.03"

    if draft:
        preset, crf = "ultrafast", "28"
    elif preview:
        preset, crf = "medium", "22"
    else:
        preset, crf = "fast", "20"

    # Frame rate: use the rate the caller resolved once for the whole render
    # (every segment must share it — concat -c copy in Rule 2 requires a uniform
    # frame rate). When called standalone with no rate, preserve this source's
    # own rate; fall back to 24 only if it can't be probed.
    out_rate = rate if rate is not None else (probe_source_fps(source) or "24")

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg_start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p", "-r", out_rate,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def extract_all_segments(
    edl: dict,
    edit_dir: Path,
    preview: bool,
    draft: bool = False,
    fps: str | None = None,
) -> list[Path]:
    """Extract every EDL range into edit_dir/clips_graded/seg_NN.mp4.
    Returns the ordered list of segment paths.

    If the EDL `grade` is "auto", analyze each segment range with
    `auto_grade_for_clip` and apply a per-segment subtle correction.
    Otherwise, apply the same preset/raw filter to every segment.
    """
    resolved = resolve_grade_filter(edl.get("grade"))
    is_auto = resolved == "__AUTO__"
    clips_dir = edit_dir / (
        "clips_draft" if draft else ("clips_preview" if preview else "clips_graded")
    )
    clips_dir.mkdir(parents=True, exist_ok=True)

    ranges = edl["ranges"]
    sources = edl["sources"]

    # Resolve ONE output frame rate for the entire render and apply it to every
    # segment. The lossless concat (Rule 2, `-c copy`) requires all segments to
    # share a frame rate; probing per-segment would diverge for multi-source
    # EDLs that mix rates (e.g. a 30fps and a 60fps source) and break the concat.
    # Explicit --fps wins; otherwise preserve the first source's rate.
    if fps is not None:
        out_rate = parse_fps(str(fps))
    elif ranges:
        first_src = resolve_path(sources[ranges[0]["source"]], edit_dir)
        out_rate = probe_source_fps(first_src) or "24"
    else:
        out_rate = "24"

    seg_paths: list[Path] = []
    print(f"extracting {len(ranges)} segment(s) → {clips_dir.name}/  @ {out_rate} fps"
          f"{' (forced)' if fps is not None else ' (from source)'}")
    if is_auto:
        print("  (auto-grade per segment: analyzing each range)")
    for i, r in enumerate(ranges):
        src_name = r["source"]
        src_path = resolve_path(sources[src_name], edit_dir)
        start = float(r["start"])
        end = float(r["end"])
        duration = end - start
        out_path = clips_dir / f"seg_{i:02d}_{src_name}.mp4"

        if is_auto:
            seg_filter, _stats = auto_grade_for_clip(src_path, start=start, duration=duration, verbose=False)
        else:
            seg_filter = resolved

        note = r.get("beat") or r.get("note") or ""
        print(f"  [{i:02d}] {src_name}  {start:7.2f}-{end:7.2f}  ({duration:5.2f}s)  {note}")
        if is_auto:
            print(f"        grade: {seg_filter or '(none)'}")
        extract_segment(src_path, start, duration, seg_filter, out_path, preview=preview, draft=draft, rate=out_rate)
        seg_paths.append(out_path)

    return seg_paths


# -------- Lossless concat ----------------------------------------------------


def concat_segments(segment_paths: list[Path], out_path: Path, edit_dir: Path) -> None:
    """Lossless concat via the concat demuxer. No re-encode."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = edit_dir / "_concat.txt"
    # ffmpeg reads the list as UTF-8; Windows' default code page would garble non-ASCII paths
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in segment_paths), encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"concat → {out_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    concat_list.unlink(missing_ok=True)


# -------- Master SRT (Rule 5) ------------------------------------------------


PUNCT_BREAK = set(".,!?;:")


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_in_range(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    out: list[dict] = []
    for w in transcript.get("words", []):
        if w.get("type") != "word":
            continue
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if we <= t_start or ws >= t_end:
            continue
        out.append(w)
    return out


CHUNK_WORDS = 2         # target words per cue
CHUNK_MAX_WORDS = 3     # a too-short chunk may grow to this many words
CHUNK_MIN_S = 0.35      # a cue shorter than this reads as a flash
CHUNK_PAUSE_S = 0.3     # a gap this long between words ends the cue


def chunk_words(words: list[dict]) -> list[list[dict]]:
    """Group transcript words into caption cues.

    A cue closes on trailing punctuation or on a pause before the next word.
    Otherwise it closes at CHUNK_WORDS words, unless it would be on screen for
    less than CHUNK_MIN_S; then it takes up to CHUNK_MAX_WORDS words. So
    "does | is" across a pause stays split, and fast "what a" does not flash.
    """
    words = [w for w in words if (w.get("text") or "").strip()]
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for i, w in enumerate(words):
        current.append(w)
        text = w["text"].strip()
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 0.0
        dur = w["end"] - current[0]["start"]
        if (
            nxt is None
            or text[-1] in PUNCT_BREAK
            or gap >= CHUNK_PAUSE_S
            or len(current) >= CHUNK_MAX_WORDS
            or (len(current) >= CHUNK_WORDS and dur >= CHUNK_MIN_S)
        ):
            chunks.append(current)
            current = []
    return chunks


def _format_cue_en(chunk: list[dict]) -> str:
    text = " ".join((w.get("text") or "").strip() for w in chunk)
    text = re.sub(r"\s+", " ", text).strip()
    # Strip trailing punctuation for cleaner uppercase look
    text = text.rstrip(",;:")
    return text.upper()


# Traditional Chinese: text rules (display width, joining, punctuation) live in zh_text.py.
ZH_CHUNK_MAX_WIDTH = 28   # about 14 Chinese characters per cue on a landscape frame
ZH_CHUNK_MIN_S = 0.8      # a cue shorter than this merges into a neighbour
ZH_MERGE_MAX_GAP_S = 1.0  # ...unless the silence between them is longer than this
ZH_CUT_PAUSE_S = 0.15     # a gap this long makes a better place to split an over-long cue
ZH_SENTENCE_END = "。？！?!"  # always closes a cue; a short result is fixed by _merge_short_cues
ZH_MIN_VISIBLE_S = 0.2    # a cue still shorter than this (after merging and clamping) is dropped
ZH_BORROW_ROOM_S = 0.3    # 短句到下一句開始不到這麼久時，向下一句借字（見 _merge_short_cues）


def zh_max_width(width: int, height: int) -> int:
    """Cue width cap that fits one caption line on a width×height frame.

    libass scales FontSize=18 against PlayResY=288, and a CJK glyph in the zh-tw
    style is about 0.75 of the font height wide (measured ~90 px at 1080×1920).
    One character of slack; never above the landscape cap ZH_CHUNK_MAX_WIDTH.
    1080×1920 → 20 (10 characters), 1920×1080 → 28.
    """
    char_px = 0.75 * 18 * height / 288
    per_line = int(width * 0.95 // char_px) - 1
    return max(8, min(ZH_CHUNK_MAX_WIDTH, 2 * per_line))


def _cue_width(words: list[dict]) -> int:
    # measure the cue as it will be shown, without the trailing punctuation _format_cue_zh drops
    return display_width(join_zh([x["text"] for x in words]).rstrip(ZH_TRAILING_STRIP))


def _speaker_changes(a: dict, b: dict) -> bool:
    sa, sb = a.get("speaker_id"), b.get("speaker_id")
    return sa is not None and sb is not None and sa != sb


def _pick_cut(words: list[dict], start: int, i: int, bounds: set[int], max_width: int) -> int:
    """Where to end the cue words[start:i+1] that ran past max_width.

    Prefer a cut after punctuation, then at a pause, then the latest word
    boundary that fits. Never cut right before punctuation (it would open the
    next cue) or between a number and its unit ("100 | 分").
    """
    best: tuple[tuple[bool, bool, int], int] | None = None
    for k in range(start, i):
        if k not in bounds or _cue_width(words[start:k + 1]) > max_width:
            continue
        nxt = words[k + 1]["text"]
        if is_punct(nxt) or (is_number(words[k]["text"]) and starts_cjk(nxt)):
            continue
        key = (
            words[k]["text"].strip()[-1] in ZH_PUNCT_BREAK,
            words[k + 1]["start"] - words[k]["end"] >= ZH_CUT_PAUSE_S,
            k,
        )
        if best is None or key > best[0]:
            best = (key, k)
    if best is not None:
        return best[1]
    return next((k for k in range(i - 1, start - 1, -1) if k in bounds), i - 1)


def _cue_dur(c: list[dict]) -> float:
    return c[-1]["end"] - c[0]["start"]


def _ends_with(c: list[dict], marks: str | set[str]) -> bool:
    return c[-1]["text"].strip()[-1] in marks


def _rebalance(
    prev: list[dict], c: list[dict], max_width: int, lang: str = "zh", forward: bool = False
) -> tuple[list[dict], list[dict]] | None:
    """Move the end of prev onto the short cue c so both last ZH_CHUNK_MIN_S.

    Used when prev was cut mid-sentence by the width cap and left a short tail
    ("…自己的 | 生理上嗎？" → "…反映在 | 自己的生理上嗎？"). Prefers a cut after
    punctuation, then at a pause, then the most even split — the cut that
    moves the fewest words tends to start the tail on a particle ("的生理上嗎").

    forward=True：反過來，prev 是太短的句子，從後一句 c 的開頭借字過來
    （「いや、 | リンさんも頑張ってください」→「いや、リンさんも | 頑張ってください」）。
    後面沒有空白能延長時才用，所以兩句只要求看得到（ZH_MIN_VISIBLE_S），
    能都滿 ZH_CHUNK_MIN_S 的切法優先。
    """
    both = prev + c
    bounds = word_boundaries([w["text"] for w in both], lang)
    min_dur = ZH_MIN_VISIBLE_S if forward else ZH_CHUNK_MIN_S
    cuts = range(len(prev), len(both) - 1) if forward else range(len(prev) - 1)
    best: tuple[tuple[bool, bool, bool, int], int] | None = None
    for k in cuts:
        left, right = both[:k + 1], both[k + 1:]
        if k not in bounds or is_punct(right[0]["text"]):
            continue
        if is_number(both[k]["text"]) and starts_cjk(right[0]["text"]):
            continue
        if _cue_width(left) > max_width or _cue_width(right) > max_width:
            continue
        if _cue_dur(left) < min_dur or _cue_dur(right) < min_dur:
            continue
        key = (
            min(_cue_dur(left), _cue_dur(right)) >= ZH_CHUNK_MIN_S,
            _ends_with(left, ZH_PUNCT_BREAK),
            right[0]["start"] - left[-1]["end"] >= ZH_CUT_PAUSE_S,
            -abs(_cue_width(left) - _cue_width(right)),
        )
        if best is None or key > best[0]:
            best = (key, k)
    if best is None:
        return None
    return both[:best[1] + 1], both[best[1] + 1:]


def _merge_short_cues(chunks: list[list[dict]], max_width: int, lang: str = "zh") -> list[list[dict]]:
    """Fix cues shown for less than ZH_CHUNK_MIN_S, when the neighbour has the
    same speaker and the silence between them is short:

    - prev was cut mid-sentence (no punctuation at its end): merge into it if
      the result fits, else move words from prev's end onto the short cue
    - prev ends a clause ("，") but not a sentence ("。？！"): merge into it
    - otherwise merge into the next cue if the result fits
    - 合併不下、後面又沒有空白能延長顯示時間時：從下一句的開頭借字（forward rebalance）
    - else keep it; build_master_srt then stretches it into the silence after it
    """
    def joinable(a: list[dict], b: list[dict]) -> bool:
        return not _speaker_changes(a[-1], b[0]) and b[0]["start"] - a[-1]["end"] <= ZH_MERGE_MAX_GAP_S

    pending = list(chunks)
    out: list[list[dict]] = []
    for idx, c in enumerate(pending):
        if _cue_dur(c) < ZH_CHUNK_MIN_S:
            prev = out[-1] if out else None
            if prev and joinable(prev, c):
                fits = _cue_width(prev + c) <= max_width
                if not _ends_with(prev, ZH_PUNCT_BREAK):
                    if fits:
                        out[-1] = prev + c
                        continue
                    pair = _rebalance(prev, c, max_width, lang)
                    if pair:
                        out[-1] = pair[0]
                        out.append(pair[1])
                        continue
                elif not _ends_with(prev, ZH_SENTENCE_END) and fits:
                    out[-1] = prev + c
                    continue
            nxt = pending[idx + 1] if idx + 1 < len(pending) else None
            if nxt and joinable(c, nxt) and _cue_width(c + nxt) <= max_width:
                pending[idx + 1] = c + nxt
                continue
            # 下一句幾乎馬上接上，延長也只能閃一下（「いや、」0.22 秒、被壓成 0 秒的
            # 「確かに。」）：向下一句借字，不然會被拿掉。有 0.3 秒以上就照舊顯示，
            # 借字反而會在句尾留下「…，但」「…，所以」
            room = nxt[0]["start"] - c[0]["start"] if nxt else 0.0
            if nxt and joinable(c, nxt) and room < ZH_BORROW_ROOM_S:
                pair = _rebalance(c, nxt, max_width, lang, forward=True)
                if pair:
                    out.append(pair[0])
                    pending[idx + 1] = pair[1]
                    continue
        out.append(c)
    return out


def chunk_words_zh(words: list[dict], max_width: int = ZH_CHUNK_MAX_WIDTH, lang: str = "zh") -> list[list[dict]]:
    """Group Chinese transcript words into caption cues.

    Cues only break at word boundaries (jieba), since Scribe gives one token per
    character and a pause can fall inside a word ("全 … 力"). A cue closes on a
    pause after a word, on a change of speaker, or on punctuation once it has
    been on screen for ZH_CHUNK_MIN_S (so a lone "好，" does not flash). A cue
    that runs past max_width is split at the best point (_pick_cut).
    Punctuation that would open a cue goes on the end of the previous one, and
    cues still shorter than ZH_CHUNK_MIN_S merge into a neighbour.
    lang="ja"：規則相同，只是「詞」改成 BudouX 的文節（見 chunk_words_ja）。
    """
    words = [w for w in words if (w.get("text") or "").strip()]
    bounds = word_boundaries([w["text"] for w in words], lang)
    chunks: list[list[dict]] = []
    start = 0  # the open cue is words[start:i]
    for i, w in enumerate(words):
        text = w["text"].strip()
        if start == i and chunks and is_punct(text):
            chunks[-1].append(w)
            start = i + 1
            continue
        while start < i and _cue_width(words[start:i + 1]) > max_width:
            cut = _pick_cut(words, start, i, bounds, max_width)
            chunks.append(words[start:cut + 1])
            start = cut + 1
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 0.0
        dur = w["end"] - words[start]["start"]
        if (
            nxt is None
            or _speaker_changes(w, nxt)
            or (gap >= CHUNK_PAUSE_S and i in bounds)
            or text[-1] in ZH_SENTENCE_END
            or (text[-1] in ZH_PUNCT_BREAK and dur >= ZH_CHUNK_MIN_S)
        ):
            chunks.append(words[start:i + 1])
            start = i + 1
    return _merge_short_cues(chunks, max_width, lang)


def chunk_words_ja(words: list[dict], max_width: int = ZH_CHUNK_MAX_WIDTH) -> list[list[dict]]:
    """日文字幕：和中文同一套規則（字寬上限、標點和停頓優先、說話者換人斷句、
    短句合併），只在 BudouX 的文節邊界切開（終章の | 朗読劇の | 前に）。"""
    return chunk_words_zh(words, max_width, lang="ja")


def _cue_text_cjk(chunk: list[dict], space_digits: bool = True) -> str:
    text = join_zh([w.get("text") or "" for w in chunk], space_digits)
    # a cut can carry the previous sentence's "，" into this cue's first word
    text = text.lstrip("".join(ZH_PUNCT_BREAK) + " ").rstrip(ZH_TRAILING_STRIP)
    return inner_punct_to_space(text)


def _format_cue_zh(chunk: list[dict]) -> str:
    return to_traditional(_cue_text_cjk(chunk))


def _format_cue_ja(chunk: list[dict]) -> str:
    # 和中文相同的標點處理（日本電視字幕也常用空白代替句中標點），但不轉繁體、
    # 數字兩邊不加空格
    return _cue_text_cjk(chunk, space_digits=False)


# Same look as the English style, in a face that has Chinese glyphs
# (Helvetica has none; libass would fall back silently or draw boxes).
SUB_FORCE_STYLE_ZH = SUB_FORCE_STYLE.replace("FontName=Helvetica", "FontName=Microsoft JhengHei")


def ja_default_font(platform: str = sys.platform) -> str:
    """各作業系統內建、有日文字形的字型；用 --sub-font 可以換掉。"""
    if platform == "win32":
        return "Yu Gothic"
    if platform == "darwin":
        return "Hiragino Sans"
    return "Noto Sans CJK JP"


SUB_FORCE_STYLE_JA = SUB_FORCE_STYLE.replace("FontName=Helvetica", f"FontName={ja_default_font()}")


# Per-language caption rules: how words group into cues, how a cue's words
# become text, and the libass style used when burning. Selected by --sub-lang.
# "cjk": 不加空格、用字寬計算的語言，共用字寬上限（依畫面寬度）、不重疊、
# 拿掉太短句子這些規則。
SUB_LANGS = {
    "en": {
        "chunk": chunk_words,
        "format": _format_cue_en,
        "force_style": SUB_FORCE_STYLE,
        "cjk": False,
    },
    "zh-tw": {
        "chunk": chunk_words_zh,
        "format": _format_cue_zh,
        "force_style": SUB_FORCE_STYLE_ZH,
        "cjk": True,
    },
    "ja": {
        "chunk": chunk_words_ja,
        "format": _format_cue_ja,
        "force_style": SUB_FORCE_STYLE_JA,
        "cjk": True,
    },
}

# 逐字稿語言 → 建議的 --sub-lang（en 規則遇到這些語言時發出警告）
SUB_LANG_FOR = {"zh": "zh-tw", "ja": "ja"}


def sub_force_style(sub_lang: str, font: str | None = None, margin_v: int | None = None) -> str:
    """該語言燒字幕用的樣式；font（--sub-font）會換掉預設字型，
    margin_v（見 sub_margin_v）會換掉字幕離底部的高度。"""
    style = SUB_LANGS[sub_lang]["force_style"]
    if font:
        style = re.sub(r"FontName=[^,]*", f"FontName={font}", style)
    if margin_v is not None:
        style = re.sub(r"MarginV=\d+", f"MarginV={margin_v}", style)
    return style


_HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


def _speaker_colours(edl: dict) -> dict[str, dict[str, str]]:
    """EDL 的 speakers → {source: {speaker_id: "#RRGGBB"}}；顏色格式錯就報錯，指出是哪個說話者。"""
    out: dict[str, dict[str, str]] = {}
    for src, speakers in (edl.get("speakers") or {}).items():
        for sid, info in (speakers or {}).items():
            colour = (info or {}).get("color")
            if colour is None:
                continue
            if not isinstance(colour, str) or not _HEX_COLOUR.fullmatch(colour):
                raise ValueError(f'speakers.{src}.{sid}.color must look like "#RRGGBB", got {colour!r}')
            out.setdefault(src, {})[sid] = colour
    return out


def _apply_speaker_fixes(words: list[dict], fixes: list[dict]) -> list[dict]:
    """把開始時間落在 [start, end) 的字改成指定的說話者。
    複製字典再改，不動到逐字稿原本的資料（Scribe 的判斷留著可查）。"""
    if not fixes:
        return words
    out: list[dict] = []
    for w in words:
        s = w.get("start")
        for f in fixes:
            if s is not None and float(f["start"]) <= s < float(f["end"]):
                w = {**w, "speaker_id": f["speaker"]}
        out.append(w)
    return out


def _speaker_runs(words: list[dict]) -> list[list[dict]]:
    """依說話者切成連續的段落，讓英文兩字一句不會把兩個人的字放在同一句。"""
    runs: list[list[dict]] = []
    for w in words:
        if runs and not _speaker_changes(runs[-1][-1], w):
            runs[-1].append(w)
        else:
            runs.append([w])
    return runs


def build_master_srt(
    edl: dict, edit_dir: Path, out_path: Path, sub_lang: str = "en", max_width: int | None = None
) -> None:
    """Build an output-timeline SRT from per-source transcripts.

    - chunking and text rules from SUB_LANGS[sub_lang]: "en" is phrase-aware
      ~2-word UPPERCASE chunks (chunk_words), "zh-tw" is width-capped Chinese
      cues (chunk_words_zh), "ja" the same rules on BudouX phrases (chunk_words_ja)
    - max_width: zh-tw / ja cue width cap (see zh_max_width); None keeps ZH_CHUNK_MAX_WIDTH
    - Output times computed as word.start - segment_start + segment_offset
    - EDL speaker_fixes：斷句前先修正說話者；EDL speakers：每句依第一個字的
      說話者包上 <font color="#RRGGBB">（libass 燒字幕時會用這個顏色）
    """
    speaker_colours = _speaker_colours(edl)
    lang = SUB_LANGS[sub_lang]
    chunk_fn = lang["chunk"]
    if lang["cjk"]:
        cap = max_width or ZH_CHUNK_MAX_WIDTH
        base_chunk = lang["chunk"]
        chunk_fn = lambda ws: base_chunk(ws, max_width=cap)  # noqa: E731
    transcripts_dir = edit_dir / "transcripts"
    sources = edl["sources"]

    entries: list[tuple[float, float, str]] = []
    seg_offset = 0.0
    warned_zh = False

    for r in edl["ranges"]:
        src_name = r["source"]
        seg_start = float(r["start"])
        seg_end = float(r["end"])
        seg_duration = seg_end - seg_start

        tr_path = transcripts_dir / f"{src_name}.json"
        if not tr_path.exists():
            print(f"  no transcript for {src_name}, skipping captions for this segment")
            seg_offset += seg_duration
            continue

        transcript = json.loads(tr_path.read_text(encoding="utf-8"))
        speech = transcript_lang(transcript) if sub_lang == "en" and not warned_zh else None
        if speech in SUB_LANG_FOR:
            name = {"zh": "Chinese", "ja": "Japanese"}[speech]
            print(
                f"  warning: {src_name} looks like {name} speech but captions use English rules "
                f"(spaces between characters, 2-word cues, no {name} font). "
                f"Re-run with --sub-lang {SUB_LANG_FOR[speech]}.",
                file=sys.stderr,
            )
            warned_zh = True
        words_in_seg = _words_in_range(transcript, seg_start, seg_end)
        fixes = [f for f in edl.get("speaker_fixes") or [] if f.get("source") == src_name]
        words_in_seg = _apply_speaker_fixes(words_in_seg, fixes)
        colours = speaker_colours.get(src_name)
        # 中日文的斷句本來就在換人時斷開；其他語言有設定顏色時先依說話者分段
        groups = _speaker_runs(words_in_seg) if colours and not lang["cjk"] else [words_in_seg]

        for chunk in (c for g in groups for c in chunk_fn(g)):
            local_start = max(seg_start, chunk[0].get("start", seg_start))
            local_end = min(seg_end, chunk[-1].get("end", seg_end))
            out_start = max(0.0, local_start - seg_start) + seg_offset
            out_end = max(0.0, local_end - seg_start) + seg_offset
            if out_end <= out_start:
                out_end = out_start + 0.4
            text = lang["format"](chunk)
            colour = colours.get(chunk[0].get("speaker_id")) if colours else None
            if colour:
                text = f'<font color="{colour}">{text}</font>'
            entries.append((out_start, out_end, text))

        seg_offset += seg_duration

    # Sort and write as SRT
    entries.sort(key=lambda e: e[0])
    if lang["cjk"]:
        # 太短的句子先延長到 ZH_CHUNK_MIN_S，用掉後面的空白（字幕顯示時間不必
        # 和說話時間一樣長，例：切剩的「する」0.16 秒、後面停了 1.2 秒）。
        # Never let a cue run into the next one, or both are on screen at once,
        # stacked — this includes a cue starting at the same moment as the next
        # (Scribe squeezes cross-talk to zero length). A cue still shorter than
        # ZH_MIN_VISIBLE_S (a backchannel "嗯" right before the other speaker)
        # would only flicker, so it is dropped.
        entries = [
            (a, min(max(b, a + ZH_CHUNK_MIN_S), entries[i + 1][0]) if i + 1 < len(entries)
             else max(b, a + ZH_CHUNK_MIN_S), t)
            for i, (a, b, t) in enumerate(entries)
        ]
        entries = [e for e in entries if e[1] - e[0] >= ZH_MIN_VISIBLE_S]
    lines: list[str] = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(a)} --> {_srt_timestamp(b)}")
        lines.append(t)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"master SRT → {out_path.name} ({len(entries)} cues)")


# -------- Loudness normalization (social-ready audio) -----------------------


# Social-media standard: -14 LUFS integrated, -1 dBTP peak, LRA 11 LU.
# Matches YouTube / Instagram / TikTok / X / LinkedIn normalization targets.
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.0
LOUDNORM_LRA = 11.0


def measure_loudness(video_path: Path) -> dict[str, str] | None:
    """Run ffmpeg loudnorm first pass and parse the JSON measurement.

    Returns a dict with measured_i, measured_tp, measured_lra, measured_thresh,
    target_offset, or None if measurement failed.
    """
    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(video_path),
        "-af", filter_str,
        "-vn", "-f", "null", "-",
    ]
    # stderr echoes the input path; decode as UTF-8 so a non-ASCII path does not
    # fail decoding on Windows (which leaves proc.stderr as None)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # loudnorm prints the JSON to stderr at the end of the run
    stderr = proc.stderr

    # Find the JSON block — loudnorm output contains a `{ ... }` block
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not needed.issubset(data.keys()):
        return None
    return data


def apply_loudnorm_two_pass(
    input_path: Path,
    output_path: Path,
    preview: bool = False,
) -> bool:
    """Run two-pass loudnorm on input_path, write normalized copy to output_path.

    Returns True on success, False if measurement failed (caller should fall
    back to copying the input unchanged).

    In preview mode, skips the measurement pass and uses a one-pass approximation
    for speed. Final mode always does the proper two-pass.
    """
    if preview:
        # One-pass approximation — faster, slightly less accurate.
        filter_str = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", filter_str,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(output_path),
        ]
        print(f"  loudnorm (1-pass preview) → {output_path.name}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True

    # Full two-pass
    print(f"  loudnorm pass 1: measuring {input_path.name}")
    measurement = measure_loudness(input_path)
    if measurement is None:
        print("  loudnorm measurement failed — falling back to 1-pass")
        return apply_loudnorm_two_pass(input_path, output_path, preview=True)

    print(f"    measured: I={measurement['input_i']} LUFS  "
          f"TP={measurement['input_tp']}  LRA={measurement['input_lra']}")

    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        f":measured_I={measurement['input_i']}"
        f":measured_TP={measurement['input_tp']}"
        f":measured_LRA={measurement['input_lra']}"
        f":measured_thresh={measurement['input_thresh']}"
        f":offset={measurement['target_offset']}"
        f":linear=true"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-c:v", "copy",
        "-af", filter_str,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ]
    print(f"  loudnorm pass 2: normalizing → {output_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return True


# -------- Final compositing (Rule 1 + Rule 4) -------------------------------


def build_final_composite(
    base_path: Path,
    overlays: list[dict],
    subtitles_path: Path | None,
    out_path: Path,
    edit_dir: Path,
    sub_lang: str = "en",
    sub_font: str | None = None,
    margin_v: int | None = None,
) -> None:
    """Final pass: base → overlays (PTS-shifted) → subtitles LAST → out.

    If there are no overlays and no subtitles, just copy base to out.
    """
    has_overlays = bool(overlays)
    has_subs = subtitles_path is not None and subtitles_path.exists()

    if not has_overlays and not has_subs:
        # Nothing to do — just rename/copy base to final name
        run(["ffmpeg", "-y", "-i", str(base_path), "-c", "copy", str(out_path)], quiet=True)
        return

    inputs: list[str] = ["-i", str(base_path)]
    for ov in overlays:
        ov_path = resolve_path(ov["file"], edit_dir)
        inputs += ["-i", str(ov_path)]

    filter_parts: list[str] = []
    # PTS-shift every overlay so its frame 0 lands at start_in_output
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov["start_in_output"])
        filter_parts.append(f"[{idx}:v]setpts=PTS-STARTPTS+{t}/TB[a{idx}]")

    # Chain overlays on top of base
    current = "[0:v]"
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov["start_in_output"])
        dur = float(ov["duration"])
        end = t + dur
        next_label = f"[v{idx}]"
        filter_parts.append(
            f"{current}[a{idx}]overlay=enable='between(t,{t:.3f},{end:.3f})'{next_label}"
        )
        current = next_label

    # Subtitles LAST — Rule 1
    if has_subs:
        # Forward slashes: the filter option parser treats backslashes as escapes,
        # so a Windows path like C:\Users\... would lose its separators.
        subs_abs = subtitles_path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
        filter_parts.append(
            f"{current}subtitles='{subs_abs}':force_style='{sub_force_style(sub_lang, sub_font, margin_v)}'[outv]"
        )
        out_label = "[outv]"
    else:
        # Rename the last overlay output to [outv] for consistency
        if has_overlays:
            filter_parts.append(f"{current}null[outv]")
            out_label = "[outv]"
        else:
            out_label = "[0:v]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", out_label,
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"compositing → {out_path.name}")
    print(f"  overlays: {len(overlays)}, subtitles: {'yes' if has_subs else 'no'}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


# -------- Main ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a video from an EDL")
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output video path")
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 1080p, medium, CRF 22 — evaluable for QC, faster than final.",
    )
    ap.add_argument(
        "--draft",
        action="store_true",
        help="Draft mode: 720p, ultrafast, CRF 28 — cut-point verification only.",
    )
    ap.add_argument(
        "--build-subtitles",
        action="store_true",
        help="Build master.srt from transcripts + EDL offsets before compositing",
    )
    ap.add_argument(
        "--sub-lang",
        choices=sorted(SUB_LANGS),
        default="en",
        help="Caption rules and font: en (2-word UPPERCASE, Helvetica), "
             "zh-tw (width-capped Traditional Chinese cues, Microsoft JhengHei) or "
             "ja (width-capped Japanese cues on BudouX phrases, OS Japanese font). Default: en.",
    )
    ap.add_argument(
        "--sub-font",
        default=None,
        help="Font name for burned captions, overriding the --sub-lang default "
             "(e.g. a font installed on this machine).",
    )
    ap.add_argument(
        "--sub-max-chars",
        type=int,
        default=None,
        help="zh-tw / ja only: max characters per caption cue. Default: computed from the "
             "rendered frame (about 14 on 16:9, 10 on 9:16). Pass it when the frame is cropped "
             "after render.py, e.g. per-shot vertical reframing of a 16:9 render.",
    )
    ap.add_argument(
        "--sub-margin",
        type=float,
        default=None,
        metavar="PCT",
        help="Caption height above the bottom edge, as a percentage of the frame height (0–50). "
             "Default: from the rendered frame — 9:16 keeps the short-form safe zone (~31%%), "
             "16:9 and square sit ~8%% up. Pass it when the frame is cropped after render.py "
             "(e.g. --sub-margin 31 for a 16:9 render later reframed to 9:16).",
    )
    ap.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Skip subtitles even if the EDL references one",
    )
    ap.add_argument(
        "--no-loudnorm",
        action="store_true",
        help="Skip audio loudness normalization. Default is on (-14 LUFS, -1 dBTP, LRA 11).",
    )
    ap.add_argument(
        "--fps",
        type=parse_fps,
        default=None,
        help="Output frame rate. Default: preserve the source's frame rate "
             "(falls back to 24 if it can't be probed). Pass e.g. --fps 30 or "
             "--fps 30000/1001 to force.",
    )
    args = ap.parse_args()
    if args.sub_margin is not None and not 0 <= args.sub_margin <= 50:
        ap.error("--sub-margin must be between 0 and 50 (percent of the frame height)")

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl not found: {edl_path}")

    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    edit_dir = edl_path.parent
    out_path = args.output.resolve()

    # 1. Extract per-segment (auto-grade per range if EDL grade is "auto")
    segment_paths = extract_all_segments(
        edl, edit_dir, preview=args.preview, draft=args.draft, fps=args.fps
    )

    # 2. Concat → base
    if args.draft:
        base_name = "base_draft.mp4"
    elif args.preview:
        base_name = "base_preview.mp4"
    else:
        base_name = "base.mp4"
    base_path = edit_dir / base_name
    concat_segments(segment_paths, base_path, edit_dir)

    # 3. Subtitles: build if requested, resolve final path
    subs_path: Path | None = None
    margin_v: int | None = None
    if not args.no_subtitles:
        dims = probe_dimensions(base_path)
        margin_v = sub_margin_v(*(dims or (None, None)), pct=args.sub_margin)
        print(f"subtitle margin: MarginV={margin_v} (~{100 * margin_v / SUB_PLAY_RES_Y:.0f}% from bottom)")
        if args.build_subtitles:
            subs_path = edit_dir / "master.srt"
            max_width = None
            if SUB_LANGS[args.sub_lang]["cjk"]:
                if args.sub_max_chars:
                    max_width = 2 * args.sub_max_chars
                else:
                    max_width = zh_max_width(*dims) if dims else None
                print(f"{args.sub_lang} caption cap: {(max_width or ZH_CHUNK_MAX_WIDTH) // 2} characters per cue")
            build_master_srt(edl, edit_dir, subs_path, sub_lang=args.sub_lang, max_width=max_width)
        elif edl.get("subtitles"):
            subs_path = resolve_subtitles_path(edl["subtitles"], edit_dir)

    # 4. Composite (overlays + subtitles LAST) → intermediate (pre-loudnorm) path
    overlays = edl.get("overlays") or []
    if args.no_loudnorm:
        # Composite directly to final output
        build_final_composite(
            base_path, overlays, subs_path, out_path, edit_dir, sub_lang=args.sub_lang, sub_font=args.sub_font,
            margin_v=margin_v,
        )
    else:
        # Composite to a temp file, then run loudnorm → final output
        tmp_composite = out_path.with_suffix(".prenorm.mp4")
        build_final_composite(
            base_path, overlays, subs_path, tmp_composite, edit_dir, sub_lang=args.sub_lang, sub_font=args.sub_font,
            margin_v=margin_v,
        )
        print("loudness normalization → social-ready (-14 LUFS / -1 dBTP / LRA 11)")
        apply_loudnorm_two_pass(tmp_composite, out_path, preview=args.draft)
        tmp_composite.unlink(missing_ok=True)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\ndone: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
