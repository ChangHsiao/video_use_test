"""把 EDL 匯出成 Final Cut Pro 7 XML 時間軸，給 DaVinci Resolve / Premiere 接手細剪。

render.py 算繪出來的影片把剪輯決定都壓扁了。這支程式把同一份剪輯改寫成
可以編輯的時間軸：每一段 range 變成一個片段，指向原始素材並記錄起訖點，
剪輯師可以把任何一刀重新拉開。

- V1：剪輯片段；聲音跟著畫面，來源有幾個聲道就幾條聲音軌（最多 2 條）
- V2：疊圖（問題卡）。旁邊有同名 .png 時改用 PNG 當靜態圖片，
  因為 DaVinci 免費版不一定能解 qtrle 的 .mov

不匯出：調色、30ms 音訊淡入淡出、音量標準化、疊圖淡入淡出。
字幕不放進 XML（FCP 7 XML 沒有字幕軌），請另外匯入 master.srt
（DaVinci：File → Import → Subtitle）。

用法：
    python helpers/export_xml.py <edl.json>
    python helpers/export_xml.py <edl.json> -o timeline.xml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote


def probe_media(path: Path) -> dict:
    """用 ffprobe 讀素材資訊：幀率、長度、寬高、聲道。圖片只需要寬高。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    info = {"width": int(video.get("width", 0)), "height": int(video.get("height", 0))}
    if path.suffix.lower() == ".png":
        return info
    info.update(
        fps=Fraction(video.get("r_frame_rate") or "24/1"),
        duration_s=float(data.get("format", {}).get("duration") or 0),
        audio_channels=int(audio.get("channels", 0)),
        sample_rate=int(audio.get("sample_rate") or 48000),
    )
    return info


def fps_to_rate(fps: Fraction) -> tuple[int, bool]:
    """FCP 7 XML 用「整數 timebase + NTSC 旗標（×1000/1001）」表示幀率，例如 23.976 = 24 + NTSC。"""
    if fps.denominator == 1001:
        return round(fps), True
    if fps.denominator == 1:
        return fps.numerator, False
    print(f"warning: frame rate {float(fps):.3f} is neither integer nor NTSC; using {round(fps)}", file=sys.stderr)
    return round(fps), False


def path_to_url(path: Path) -> str:
    """轉成 file://localhost/C:/... 格式；中文等非 ASCII 字元做 percent-encode，斜線和磁碟機的冒號不編碼。"""
    return "file://localhost/" + quote(Path(path).resolve().as_posix(), safe="/:")


def _sub(parent: ET.Element, tag: str, text: object | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = str(text)
    return el


def _rate(parent: ET.Element, fps: Fraction) -> None:
    timebase, ntsc = fps_to_rate(fps)
    rate = _sub(parent, "rate")
    _sub(rate, "timebase", timebase)
    _sub(rate, "ntsc", "TRUE" if ntsc else "FALSE")


def _resolve(maybe_path: str, base: Path) -> Path:
    p = Path(maybe_path)
    return p if p.is_absolute() else (base / p)


class _Files:
    """每個檔案只寫一次完整的 <file>，之後用到同一個檔案時只寫 id 引用。"""

    def __init__(self) -> None:
        self.ids: dict[Path, str] = {}

    def add(self, parent: ET.Element, path: Path, info: dict, duration: int, fps: Fraction) -> None:
        key = path.resolve()
        if key in self.ids:
            _sub(parent, "file", id=self.ids[key])
            return
        file_id = self.ids[key] = f"file-{len(self.ids) + 1}"
        f = _sub(parent, "file", id=file_id)
        _sub(f, "name", path.name)
        _sub(f, "pathurl", path_to_url(path))
        _rate(f, fps)
        _sub(f, "duration", duration)
        # DaVinci 靠素材的起始時間碼接回聲音片段，沒寫的話聲音會離線（畫面不受影響）
        tc = _sub(f, "timecode")
        _sub(tc, "string", "00:00:00:00")
        _sub(tc, "displayformat", "NDF")
        _rate(tc, fps)
        media = _sub(f, "media")
        vchar = _sub(_sub(media, "video"), "samplecharacteristics")
        _rate(vchar, fps)
        _sub(vchar, "width", info["width"])
        _sub(vchar, "height", info["height"])
        if info.get("audio_channels"):
            audio = _sub(media, "audio")
            achar = _sub(audio, "samplecharacteristics")
            _sub(achar, "depth", 16)
            _sub(achar, "samplerate", info["sample_rate"])
            _sub(audio, "channelcount", info["audio_channels"])


def _clip(track: ET.Element, clip_id: str, name: str, duration: int, fps: Fraction,
          start: int, end: int, in_f: int, out_f: int) -> ET.Element:
    c = _sub(track, "clipitem", id=clip_id)
    _sub(c, "name", name)
    _sub(c, "enabled", "TRUE")
    _sub(c, "duration", duration)
    _rate(c, fps)
    _sub(c, "start", start)
    _sub(c, "end", end)
    _sub(c, "in", in_f)
    _sub(c, "out", out_f)
    return c


def _snap(frame: int, cuts: set[int]) -> int:
    """離剪接點只差 1 格時對齊剪接點（秒數換算的誤差），否則不動。"""
    near = [c for c in cuts if abs(c - frame) <= 1]
    return min(near, key=lambda c: abs(c - frame)) if near else frame


def build_xmeml(edl: dict, edl_dir: Path, probe=probe_media) -> ET.ElementTree:
    """把 EDL 轉成 FCP 7 XML 樹。`probe` 可以替換，測試時不用真的執行 ffprobe。"""
    sources = {name: _resolve(p, edl_dir) for name, p in edl["sources"].items()}
    infos: dict[str, dict] = {}

    def info_for(name: str) -> dict:
        if name not in infos:
            infos[name] = probe(sources[name])
        return infos[name]

    ranges = edl["ranges"]
    first = info_for(ranges[0]["source"])
    seq_fps = first["fps"]
    channels = min(first.get("audio_channels", 0), 2)
    files = _Files()

    root = ET.Element("xmeml", version="5")
    seq = _sub(root, "sequence", id="sequence-1")
    seq_name = edl_dir.parent.name if edl_dir.name == "edit" else edl_dir.name
    _sub(seq, "name", seq_name)
    seq_duration = _sub(seq, "duration")
    _rate(seq, seq_fps)
    tc = _sub(seq, "timecode")
    _rate(tc, seq_fps)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")

    media = _sub(seq, "media")
    video = _sub(media, "video")
    fchar = _sub(_sub(video, "format"), "samplecharacteristics")
    _rate(fchar, seq_fps)
    _sub(fchar, "width", first["width"])
    _sub(fchar, "height", first["height"])
    _sub(fchar, "pixelaspectratio", "square")
    _sub(fchar, "fielddominance", "none")
    v1 = _sub(video, "track")
    v2 = _sub(video, "track") if edl.get("overlays") else None

    audio = _sub(media, "audio")
    if channels:
        _sub(audio, "numOutputChannels", channels)
        achar = _sub(_sub(audio, "format"), "samplecharacteristics")
        _sub(achar, "depth", 16)
        _sub(achar, "samplerate", first["sample_rate"])
    a_tracks = [_sub(audio, "track") for _ in range(channels)]

    cursor = 0
    for i, r in enumerate(ranges, start=1):
        info = info_for(r["source"])
        fps = info["fps"]
        if fps != seq_fps:
            print(f"warning: {r['source']} is {float(fps):.3f} fps, timeline is {float(seq_fps):.3f}", file=sys.stderr)
        total = round(info["duration_s"] * fps)
        in_f, out_f = round(r["start"] * fps), round(r["end"] * fps)
        # 時間軸位置用影格累加，不用秒數，避免四捨五入的誤差越積越多
        start, end = cursor, cursor + (out_f - in_f)
        cursor = end
        name = r.get("beat") or f"{r['source']} {i}"

        ids = [f"clip-v-{i}"] + [f"clip-a{ch}-{i}" for ch in range(1, channels + 1)]
        clips = [_clip(v1, ids[0], name, total, fps, start, end, in_f, out_f)]
        files.add(clips[0], sources[r["source"]], info, total, fps)
        for ch, track in enumerate(a_tracks, start=1):
            c = _clip(track, ids[ch], name, total, fps, start, end, in_f, out_f)
            files.add(c, sources[r["source"]], info, total, fps)
            src = _sub(c, "sourcetrack")
            _sub(src, "mediatype", "audio")
            _sub(src, "trackindex", ch)
            clips.append(c)
        for c in clips:
            for k, clip_id in enumerate(ids):
                link = _sub(c, "link")
                _sub(link, "linkclipref", clip_id)
                _sub(link, "mediatype", "video" if k == 0 else "audio")
                _sub(link, "trackindex", max(k, 1))
                _sub(link, "clipindex", i)

    cuts = {int(c.findtext("start")) for c in v1.findall("clipitem")} | {cursor}
    for j, ov in enumerate(edl.get("overlays") or [], start=1):
        path = _resolve(ov["file"], edl_dir)
        png = path.with_suffix(".png")
        still = path.suffix.lower() == ".png" or png.exists()
        if still:
            path = png
        else:
            print(f"warning: no PNG next to overlay {path.name}; exporting the original file", file=sys.stderr)
        info = probe(path)
        # 起點和終點各自從秒數換算，不用「起點 + 長度」：兩次四捨五入的誤差相加，
        # 會讓緊接的兩張卡片重疊 1 格
        start = _snap(round(ov["start_in_output"] * seq_fps), cuts)
        end = _snap(round((ov["start_in_output"] + ov["duration"]) * seq_fps), cuts)
        # 卡片不能超過影片結尾：秒數和影格累加的誤差可能讓最後一張卡片多出幾格黑畫面
        end = min(end, cursor)
        length = end - start
        total = length if still else round(info["duration_s"] * info["fps"])
        c = _clip(v2, f"card-{j}", path.stem, total, seq_fps, start, end, 0, length)
        if still:
            _sub(c, "stillframe", "TRUE")
        files.add(c, path, info, total, seq_fps)

    seq_duration.text = str(cursor)
    return ET.ElementTree(root)


def write_xml(tree: ET.ElementTree, out_path: Path) -> None:
    ET.indent(tree, space="  ")
    body = ET.tostring(tree.getroot(), encoding="unicode")
    out_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n", encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Export an EDL as a Final Cut Pro 7 XML timeline")
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="Output XML path (default: timeline.xml next to the EDL)")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl not found: {edl_path}")
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    edit_dir = edl_path.parent
    out_path = (args.output or edit_dir / "timeline.xml").resolve()

    tree = build_xmeml(edl, edit_dir)
    write_xml(tree, out_path)

    root = tree.getroot()
    seq = root.find("sequence")
    timebase = int(seq.findtext("rate/timebase"))
    fps = Fraction(timebase * 1000, 1001) if seq.findtext("rate/ntsc") == "TRUE" else Fraction(timebase)
    tracks = seq.findall("media/video/track")
    n_clips = len(tracks[0].findall("clipitem"))
    n_cards = len(tracks[1].findall("clipitem")) if len(tracks) > 1 else 0
    print(f"timeline → {out_path}")
    print(f"  clips: {n_clips}, overlays: {n_cards}, duration: {int(seq.findtext('duration')) / fps:.2f}s")

    subs = edl.get("subtitles")
    srt = _resolve(subs, edit_dir) if subs else edit_dir / "master.srt"
    if srt.exists():
        print(f"  subtitles are not in the XML — import {srt.name} separately (Resolve: File → Import → Subtitle)")


if __name__ == "__main__":
    main()
