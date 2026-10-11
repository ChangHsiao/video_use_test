"""把 Claude 寫的翻譯（translation.json）組成雙語字幕和審稿清單。

流程：剪輯確定 → render.py --subtitles-only 產生原文草稿 master.srt（規則斷句、
說話者顏色）→ Claude 照意思把草稿裡連續的幾句合成一組、修正聽錯的詞並翻譯，
寫成 translation.json → 這支程式 → master_bilingual.srt 等檔案。

Claude 只寫文字和「第幾句到第幾句」，時間和顏色由這支程式從草稿取得：
一組的開始時間是第 from 句的開始，結束時間是第 to 句的結束，顏色是第 from 句的顏色。

translation.json：
    {
      "draft": "master.srt",            # 原文草稿，相對於 translation.json
      "source_lang": "ja",              # render.py 的 --sub-lang 名稱
      "target_lang": "zh-tw",
      "cues": [{"from": 1, "to": 3, "src": "修正後的原文", "tr": "譯文",
                "check": "（選填）拿不準的原因"}],
      "drop": [4]                       # 不顯示的草稿句子編號
    }

輸出（和 translation.json 同一個資料夾）：
- master_bilingual.srt：譯文在上、原文在下（原文用原文語言的字型、縮小）
- master_<source_lang>.srt、master_<target_lang>.srt：單一語言，給之後匯入剪輯軟體
- translation_review.md：審稿清單（Claude 標記的句子、原文被修正的地方、警告）

這些輸出每次都從 translation.json 重新產生、直接覆蓋；要修改請改 translation.json。

第一次執行時把草稿的 SHA-256 寫進 translation.json；草稿之後被重新產生
（剪輯改了，句子編號跟著變）就停下來，不會把字幕默默配到錯的時間。

用法：
    python helpers/bilingual_srt.py <translation.json>
    python helpers/bilingual_srt.py <translation.json> --max-chars 14 --src-scale 0.75 --src-font "Yu Gothic"
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple


def _load_render():
    # render.py 不是套件；照測試檔的方式從同一個資料夾載入，沿用它的字型和字寬上限
    path = Path(__file__).with_name("render.py")
    spec = importlib.util.spec_from_file_location("video_use_render", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load_render()
display_width = render.display_width

DEFAULT_SRC_SCALE = 0.75
# 譯文一行的字數上限（16:9）。中文字幕單獨使用時是 14 字（render.ZH_CHUNK_MAX_WIDTH），
# 雙語時放寬：16:9 一行放得下 30 字以上，14 字會把同一個人的一句話切得太碎、閃太快。
# 直式畫面仍依實際寬度（約 10 字）。
BILINGUAL_MAX_CHARS = 18


# 不用 dataclass：測試用檔案路徑載入這支程式（不在 sys.modules 裡），dataclass 會找不到模組
class Cue(NamedTuple):
    index: int
    start: float
    end: float
    text: str
    colour: str | None


class Result:
    def __init__(self) -> None:
        self.bilingual: list[tuple[float, float, str]] = []
        self.src_only: list[tuple[float, float, str]] = []
        self.tr_only: list[tuple[float, float, str]] = []
        self.warnings: list[str] = []
        self.fixes: list[tuple[str, str, str]] = []  # (組, 草稿文字, 修正後)
        self.checks: list[dict] = []


# -------- SRT 讀寫 -------------------------------------------------------------

_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
_COLOUR = re.compile(r'<font\s+color="(#[0-9A-Fa-f]{6})"\s*>')
_TAG = re.compile(r"</?font[^>]*>")


def _seconds(stamp: str) -> float:
    h, m, s, ms = _TIME.fullmatch(stamp.strip()).groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_srt(text: str) -> list[Cue]:
    """讀 render.py 產生的 SRT；顏色取最外層的 <font color>，文字去掉標籤。"""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a, b = lines[1].split("-->")
        body = "\n".join(lines[2:])
        m = _COLOUR.match(body)
        cues.append(Cue(int(lines[0]), _seconds(a), _seconds(b), _TAG.sub("", body).strip(),
                        m.group(1) if m else None))
    return cues


def format_srt(entries: list[tuple[float, float, str]]) -> str:
    lines: list[str] = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines += [str(i), f"{render._srt_timestamp(a)} --> {render._srt_timestamp(b)}", t, ""]
    return "\n".join(lines)


# -------- 檢查 -----------------------------------------------------------------


def validate(tr: dict, cues: list[Cue]) -> list[str]:
    """群組的錯誤清單（空的就是沒問題）。一次列出全部，方便一次改完。"""
    errors: list[str] = []
    numbers = [c.index for c in cues]
    valid = set(numbers)
    seen: dict[int, str] = {}
    last_to = 0
    for i, g in enumerate(tr.get("cues") or [], start=1):
        label = f"cues[{i}] ({g.get('from')}–{g.get('to')})"
        a, b = g.get("from"), g.get("to")
        if not isinstance(a, int) or not isinstance(b, int):
            errors.append(f"{label}: from / to must be draft cue numbers")
            continue
        if a > b:
            errors.append(f"{label}: from is after to")
            continue
        outside = [n for n in range(a, b + 1) if n not in valid]
        if outside:
            errors.append(f"{label}: draft has no cue {', '.join(map(str, outside))}")
        if a <= last_to:
            errors.append(f"{label}: overlaps or comes before the previous group (ends at {last_to})")
        last_to = max(last_to, b)
        for n in range(a, b + 1):
            if n in seen:
                errors.append(f"{label}: cue {n} is already in {seen[n]}")
            seen[n] = label
        for key in ("src", "tr"):
            if not str(g.get(key) or "").strip():
                errors.append(f"{label}: {key} is empty")
    for n in tr.get("drop") or []:
        if n in seen:
            errors.append(f"drop: cue {n} is also in {seen[n]}")
        seen[n] = "drop"
    missing = [n for n in numbers if n not in seen]
    if missing:
        errors.append(f"draft cues not in any group or drop: {', '.join(map(str, missing))}")
    return errors


def _bare(text: str) -> str:
    """比對原文有沒有被改字用：去掉空白（含 En space）和標點，只留字。"""
    return "".join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


# -------- 組字幕 ---------------------------------------------------------------


def _font_size() -> int:
    return int(re.search(r"FontSize=(\d+)", render.SUB_FORCE_STYLE).group(1))


def default_font(lang: str) -> str:
    return re.search(r"FontName=([^,]*)", render.SUB_LANGS[lang]["force_style"]).group(1)


def _wrap_colour(text: str, colour: str | None) -> str:
    return f'<font color="{colour}">{text}</font>' if colour else text


def build(cues: list[Cue], tr: dict, max_width: int, src_font: str,
          src_scale: float = DEFAULT_SRC_SCALE, src_max_width: float | None = None) -> Result:
    """依 translation.json 的群組組出三種字幕；假設 validate() 已經通過。

    max_width：譯文一行的字寬上限（全形 = 2，同 render.zh_max_width）。
    src_max_width：原文行的上限；None 時用 max_width / src_scale（和譯文一樣寬）。
    run() 傳入畫面實際放得下的寬度：原文比譯文長是語言差異，不用遷就譯文的長度。
    """
    by_index = {c.index: c for c in cues}
    size = round(_font_size() * src_scale)
    src_cap = src_max_width if src_max_width is not None else max_width / src_scale
    res = Result()
    for g in tr["cues"]:
        a, b = g["from"], g["to"]
        group = [by_index[n] for n in range(a, b + 1)]
        label = f"{a}–{b}" if a != b else str(a)
        start, end, colour = group[0].start, group[-1].end, group[0].colour
        src, text = g["src"].strip(), g["tr"].strip()

        res.bilingual.append(
            (start, end, _wrap_colour(f'{text}\n<font face="{src_font}" size="{size}">{src}</font>', colour)))
        res.src_only.append((start, end, _wrap_colour(src, colour)))
        res.tr_only.append((start, end, _wrap_colour(text, colour)))

        others = sorted({c.colour for c in group if c.colour != colour} - {None})
        if others:
            res.warnings.append(
                f"{label}: mixes speakers (colours {colour}, {', '.join(others)}) — "
                f"the whole group shows in {colour}; split it at the speaker change")
        if display_width(text) > max_width:
            res.warnings.append(f"{label}: translation is {display_width(text)} wide, over {max_width} — "
                                f"it may wrap to two lines")
        if display_width(src) > src_cap:
            res.warnings.append(f"{label}: source line is {display_width(src)} wide, over "
                                f"{src_cap:.0f} — it may wrap to two lines")

        draft_text = "".join(c.text for c in group)
        if _bare(draft_text) != _bare(src):
            res.fixes.append((label, draft_text, src))
        if g.get("check"):
            res.checks.append({"label": label, "start": start, "end": end, "colour": colour,
                               "src": src, "tr": text, "check": g["check"]})
    return res


# -------- 審稿清單 -------------------------------------------------------------


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _clock(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def review_markdown(res: Result, tr: dict, speaker_names: dict[str, str]) -> str:
    def who(colour):
        return speaker_names.get(colour or "", colour or "—")

    out = ["# 翻譯審稿清單", "",
           f"{tr.get('source_lang')} → {tr.get('target_lang')}，共 {len(res.bilingual)} 句。"
           "改 translation.json 後重跑 bilingual_srt.py，再算繪。", ""]

    out += [f"## 1. 拿不準的句子（{len(res.checks)}）", ""]
    if res.checks:
        out += ["| 組 | 時間 | 說話者 | 原文 | 譯文 | 原因 |", "|---|---|---|---|---|---|"]
        out += [f"| {c['label']} | {_clock(c['start'])} | {who(c['colour'])} | {_cell(c['src'])} | "
                f"{_cell(c['tr'])} | {_cell(c['check'])} |" for c in res.checks]
    else:
        out.append("沒有。")
    out.append("")

    out += [f"## 2. 原文被修正的地方（{len(res.fixes)}）", "",
            "草稿是轉錄的結果；修正是 Claude 依詞彙表或上下文改的，請確認。", ""]
    if res.fixes:
        out += ["| 組 | 草稿 | 修正後 |", "|---|---|---|"]
        out += [f"| {label} | {_cell(d)} | {_cell(s)} |" for label, d, s in res.fixes]
    else:
        out.append("沒有。")
    out.append("")

    out += [f"## 3. 警告（{len(res.warnings)}）", ""]
    out += [f"- {w}" for w in res.warnings] or ["沒有。"]
    out.append("")
    return "\n".join(out)


def _speaker_names(edl_path: Path) -> dict[str, str]:
    """EDL speakers 的 {顏色: 名字}，讓審稿清單顯示人名而不是色碼。"""
    try:
        edl = json.loads(edl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {info["color"]: info.get("name", info["color"])
            for speakers in (edl.get("speakers") or {}).values()
            for info in (speakers or {}).values() if info and info.get("color")}


def _frame_dims(edl_path: Path) -> tuple[int, int] | None:
    """EDL 第一個素材的畫面尺寸（和 render.py --subtitles-only 一樣）；拿不到就是 None。"""
    try:
        edl = json.loads(edl_path.read_text(encoding="utf-8"))
        first = edl["ranges"][0]["source"]
        return render.probe_display_dimensions(render.resolve_path(edl["sources"][first], edl_path.parent))
    except (OSError, json.JSONDecodeError, KeyError, IndexError):
        return None


def _max_width_from_edl(edl_path: Path) -> int:
    """譯文的字寬上限：照 render.py 的算法，封頂 BILINGUAL_MAX_CHARS 字；拿不到尺寸就用 BILINGUAL_MAX_CHARS。"""
    dims = _frame_dims(edl_path)
    cap = 2 * BILINGUAL_MAX_CHARS
    return render.zh_max_width(*dims, cap=cap) if dims else cap


def _line_fit_from_edl(edl_path: Path) -> int:
    """原尺寸字幕一行實際放得下的字寬（render.zh_max_width 不封頂）；拿不到尺寸就當作 1920×1080。"""
    dims = _frame_dims(edl_path) or (1920, 1080)
    return render.zh_max_width(*dims, cap=10**6)


# -------- 主程式 ---------------------------------------------------------------


def run(tr_path: Path, max_chars: int | None = None, src_scale: float = DEFAULT_SRC_SCALE,
        src_font: str | None = None) -> Result:
    tr_path = tr_path.resolve()
    folder = tr_path.parent
    tr = json.loads(tr_path.read_text(encoding="utf-8"))
    for key in ("source_lang", "target_lang"):
        if tr.get(key) not in render.SUB_LANGS:
            sys.exit(f"{key} must be one of {', '.join(sorted(render.SUB_LANGS))}, got {tr.get(key)!r}")

    draft_path = folder / tr.get("draft", "master.srt")
    if not draft_path.exists():
        sys.exit(f"draft not found: {draft_path}")
    draft_bytes = draft_path.read_bytes()
    digest = hashlib.sha256(draft_bytes).hexdigest()
    if tr.get("draft_sha256") and tr["draft_sha256"] != digest:
        sys.exit(
            f"{draft_path.name} changed since translation.json was written, so its cue numbers no "
            f"longer match. Rewrite translation.json for the new draft, or restore the old draft "
            f"(look for {draft_path.name}.bak-*).")

    cues = parse_srt(draft_bytes.decode("utf-8"))
    errors = validate(tr, cues)
    if errors:
        sys.exit("translation.json has problems, nothing written:\n  " + "\n  ".join(errors))

    if not tr.get("draft_sha256"):
        tr["draft_sha256"] = digest
        tr_path.write_text(json.dumps(tr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  recorded the draft's SHA-256 in {tr_path.name}")

    edl_path = folder / "edl.json"
    max_width = 2 * max_chars if max_chars else _max_width_from_edl(edl_path)
    res = build(cues, tr, max_width=max_width, src_font=src_font or default_font(tr["source_lang"]),
                src_scale=src_scale, src_max_width=_line_fit_from_edl(edl_path) / src_scale)

    # 直接覆蓋，不留備份：這些都是 translation.json 的產物，translation.json 才是要保存的
    (folder / "master_bilingual.srt").write_text(format_srt(res.bilingual), encoding="utf-8")
    (folder / f"master_{tr['source_lang']}.srt").write_text(format_srt(res.src_only), encoding="utf-8")
    (folder / f"master_{tr['target_lang']}.srt").write_text(format_srt(res.tr_only), encoding="utf-8")
    (folder / "translation_review.md").write_text(
        review_markdown(res, tr, _speaker_names(edl_path)), encoding="utf-8")

    for w in res.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    print(f"master_bilingual.srt ({len(res.bilingual)} cues, {max_width // 2} characters per line), "
          f"master_{tr['source_lang']}.srt, master_{tr['target_lang']}.srt, translation_review.md")
    print(f"  to review: {len(res.checks)} flagged, {len(res.fixes)} source fixes, {len(res.warnings)} warnings")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble bilingual captions from translation.json")
    ap.add_argument("translation", type=Path, help="Path to translation.json")
    ap.add_argument("--max-chars", type=int, default=None,
                    help="Max full-width characters per translated line. Default: from the EDL's "
                         f"first source frame, capped at {BILINGUAL_MAX_CHARS} "
                         f"({BILINGUAL_MAX_CHARS} on 16:9, about 10 on 9:16).")
    ap.add_argument("--src-scale", type=float, default=DEFAULT_SRC_SCALE,
                    help="Size of the source-language line relative to the translation (default 0.75)")
    ap.add_argument("--src-font", default=None,
                    help="Font for the source-language line. Default: render.py's font for source_lang.")
    args = ap.parse_args()
    if not 0.3 <= args.src_scale <= 1.0:
        ap.error("--src-scale must be between 0.3 and 1.0")
    run(args.translation, max_chars=args.max_chars, src_scale=args.src_scale, src_font=args.src_font)


if __name__ == "__main__":
    main()
