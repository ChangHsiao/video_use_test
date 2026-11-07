"""依配音的停頓，算出每句字幕的開始和結束時間，輸出 master.srt、cues.json、align_review.md。

給沒有逐字時間的配音用（例如在 ElevenLabs 網站手動生成）。用 API 配音、已經拿到每個字的時間時，不需要這支。

用法（在 skill 資料夾）：
    uv run --project . python helpers/align_voice.py <資料夾>/voice_lines.json

voice_lines.json 的格式見 docs 的規格 specs/2026-11-07-voice-align.md。讀的是最後放進片子的音檔：
配音要加速的話，先加速再跑這支。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

EN_SPACE = " "  # 合併兩段字幕時中間放的空白，和中文字幕的停頓標點一致
SENTENCE_END = "。？！.?!"
CLOSERS = "」』）)]】\"'”’》〉"
CLAUSE_PUNCT = "，。；：？！,.;:?!"
VIRTUAL_PENALTY = 1.0  # 分界不在停頓上時加的成本，只有真的沒有停頓可用時才會選
GRID_STEP = 0.05  # 找不到停頓時，硬切的位置每隔幾秒試一次
RATE_RANGE = (0.13, 0.32)  # 每字秒數在這個範圍外就列進抽查清單


# 對照表或音檔有問題時用的錯誤，訊息直接給使用者看
class AlignError(Exception):
    pass


# 估計一小段要念多久：中日韓字和數字一個算 1，英文單字依字母數算（字母數 ÷ 2.5，至少 1），標點和空白不算
def estimate_length(text):
    cjk = len(re.findall(r"[぀-ヿ㐀-鿿豈-﫿가-힯]", text))
    digits = len(re.findall(r"[0-9]", text))
    words = sum(max(1, round(len(w) / 2.5)) for w in re.findall(r"[A-Za-z]+", text))
    return cjk + digits + words


# 判斷念的字是不是一句的結尾：先去掉結尾的引號、括號，再看最後一個字是不是句號、問號、驚嘆號
def ends_sentence(say):
    text = say.rstrip().rstrip(CLOSERS).rstrip()
    return bool(text) and text[-1] in SENTENCE_END


# 算字幕一行的寬度：全形字算 2，半形字算 1
def display_width(text):
    return sum(1 if ord(ch) < 0x2E80 else 2 for ch in text)


# 讀音檔長度（秒）
def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise AlignError(f"讀不到音檔長度：{path}\n{out.stderr.strip()}")
    return float(out.stdout.strip())


# 找出配音裡夠安靜、夠長的地方；回傳（中間的停頓、開始說話的秒數、說完的秒數）
def find_pauses(path, threshold_db, min_pause):
    total = audio_duration(path)
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=n={threshold_db}dB:d={min_pause}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    if len(ends) < len(starts):  # 檔案結尾還在靜音時，有些 ffmpeg 版本不印 silence_end
        ends.append(total)
    silences = list(zip(starts, ends))
    speech_start = next((b for a, b in silences if a < 0.05), 0.0)
    speech_end = next((a for a, b in silences if b >= total - 0.05), total)
    inner = [(a, b) for a, b in silences if a > 0.05 and b < total - 0.05]
    return inner, speech_start, speech_end


# 把每個小段的分界放到停頓上，讓每段的實際長度和估計長度整體最接近；回傳每段的（開始、結束、分界是否硬切）
def place_boundaries(pauses, speech_start, speech_end, weights):
    n = len(weights)
    if n == 1:
        return [(speech_start, speech_end, False)]
    speech = speech_end - speech_start - sum(min(b, speech_end) - a for a, b in pauses)
    rate = speech / max(sum(weights), 1)

    # 候選分界：每個停頓，加上不靠近停頓的格點（硬切用）
    cands = [(a, b, 0.0) for a, b in pauses]
    g = speech_start + 0.3
    while g < speech_end - 0.3:
        if all(not (a - 0.15 < g < b + 0.15) for a, b in pauses):
            cands.append((g, g, VIRTUAL_PENALTY))
        g += GRID_STEP
    cands.sort()
    m_count = len(cands)
    if m_count < n - 1:
        raise AlignError(f"配音太短（{speech_end - speech_start:.2f} 秒），放不下 {n} 個小段")

    # 一段的成本：實際長度和估計長度的差，除以估計長度（至少 0.4 秒）再平方
    def seg_cost(t0, t1, k):
        est = weights[k] * rate
        return ((t1 - t0 - est) / max(est, 0.4)) ** 2

    inf = float("inf")
    dp = [[inf] * m_count for _ in range(n - 1)]  # dp[k][m]：第 k 段結束在候選 m 時的最小成本
    back = [[-1] * m_count for _ in range(n - 1)]
    for m, (ps, _pe, pen) in enumerate(cands):
        dp[0][m] = seg_cost(speech_start, ps, 0) + pen
    for k in range(1, n - 1):
        for m in range(k, m_count):
            ps, _pe, pen = cands[m]
            best, arg = inf, -1
            for mp in range(k - 1, m):
                if dp[k - 1][mp] < inf:
                    c = dp[k - 1][mp] + seg_cost(cands[mp][1], ps, k)
                    if c < best:
                        best, arg = c, mp
            dp[k][m], back[k][m] = best + pen, arg

    last = min(range(m_count), key=lambda m: dp[n - 2][m] + seg_cost(cands[m][1], speech_end, n - 1))
    chosen = [last]
    for k in range(n - 2, 0, -1):
        chosen.append(back[k][chosen[-1]])
    chosen.reverse()

    spans, t = [], speech_start
    for k in range(n):
        if k < n - 1:
            ps, pe, pen = cands[chosen[k]]
            spans.append((t, ps, pen > 0))
            t = pe
        else:
            spans.append((t, speech_end, False))
    return spans


# 把短於最短顯示時間的字幕，併進同一句、同一段配音的下一段（不行就上一段），合併後不超過一行寬度
def merge_short(cues, min_dur, max_width):
    def can_join(a, b):
        return (a["seg"] == b["seg"] and not ends_sentence(a["say"])
                and display_width(a["show"] + b["show"]) <= max_width)

    def join(a, b):
        en = " ".join(x for x in (a.get("en"), b.get("en")) if x) or None
        return {**a, "end": b["end"], "show": a["show"] + EN_SPACE + b["show"], "say": a["say"] + b["say"],
                "en": en, "virtual": b["virtual"]}

    forward, i = [], 0
    while i < len(cues):
        c = dict(cues[i])
        while c["end"] - c["start"] < min_dur and i + 1 < len(cues) and can_join(c, cues[i + 1]):
            c = join(c, cues[i + 1])
            i += 1
        forward.append(c)
        i += 1

    result = []
    for c in forward:
        if result and c["end"] - c["start"] < min_dur and can_join(result[-1], c):
            result[-1] = join(result[-1], c)
        else:
            result.append(c)
    return result


# 把秒數寫成 SRT 的時間格式 00:00:00,000
def srt_time(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# 把字幕寫成 SRT 文字：有英文的句子兩行（中文在上、英文在下）
def to_srt(cues):
    blocks = []
    for i, c in enumerate(cues, 1):
        lines = [str(i), f"{srt_time(c['start'])} --> {srt_time(c['end'])}", c["show"]]
        if c.get("en"):
            lines.append(c["en"])
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


# 讀 voice_lines.json，檢查欄位；回傳每段配音（音檔的絕對路徑、開始秒數或 None、小段清單）
def load_lines(json_path):
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AlignError(f"找不到對照表：{json_path}")
    except json.JSONDecodeError as e:
        raise AlignError(f"對照表不是正確的 JSON（第 {e.lineno} 行）：{e.msg}")
    segments = data.get("segments") if isinstance(data, dict) else None
    if not segments:
        raise AlignError("對照表要有 segments，而且至少一段")
    base = Path(json_path).parent
    out = []
    for si, seg in enumerate(segments, 1):
        if not seg.get("audio"):
            raise AlignError(f"第 {si} 段少了 audio（音檔路徑）")
        lines = seg.get("lines") or []
        if not lines:
            raise AlignError(f"第 {si} 段沒有 lines")
        for li, line in enumerate(lines, 1):
            for key in ("say", "show"):
                if not str(line.get(key, "")).strip():
                    raise AlignError(f"第 {si} 段第 {li} 條少了 {key}")
        audio = base / seg["audio"]
        if not audio.is_file():
            raise AlignError(f"第 {si} 段找不到音檔：{audio}")
        out.append({"audio": audio, "start": seg.get("start"), "lines": lines})
    return out


# 對齊所有配音段：每段找停頓、放分界，加上這段在整支片的開始秒數；回傳合併前的字幕
def align_all(segments, threshold_db, min_pause):
    cues, cursor = [], 0.0
    for si, seg in enumerate(segments):
        offset = cursor if seg["start"] is None else float(seg["start"])
        pauses, s0, s1 = find_pauses(seg["audio"], threshold_db, min_pause)
        weights = [max(estimate_length(l["say"]), 1) for l in seg["lines"]]
        for line, (st, en, virtual) in zip(seg["lines"], place_boundaries(pauses, s0, s1, weights)):
            cues.append({"seg": si, "audio": seg["audio"].name, "start": round(offset + st, 3),
                         "end": round(offset + en, 3), "say": line["say"], "show": line["show"],
                         "en": line.get("en") or None, "virtual": virtual})
        cursor = offset + audio_duration(seg["audio"])
    return cues


# 標出可能不準的字幕：分界硬切、語速太快或太慢、合併後還是太短
def flag_cues(cues, min_dur):
    for c in cues:
        dur = c["end"] - c["start"]
        c["rate"] = round(dur / max(estimate_length(c["say"]), 1), 3)
        flags = []
        if c["virtual"]:
            flags.append("結尾沒有停頓，是硬切的")
        if not RATE_RANGE[0] < c["rate"] < RATE_RANGE[1]:
            flags.append(f"語速可疑（每字 {c['rate']} 秒）")
        if dur < min_dur:
            flags.append(f"太短（{dur:.2f} 秒）")
        c["flags"] = flags
    return cues


# 寫抽查清單的內容：列出有旗標的字幕和它們的時間
def review_text(cues):
    rows = [c for c in cues if c["flags"]]
    head = ["# 字幕對齊抽查清單", "",
            "下面這些字幕的時間可能不準，請播放預覽影片確認。", ""]
    if not rows:
        return "\n".join(head + ["沒有需要抽查的字幕。", ""])
    table = ["| # | 時間 | 字幕 | 原因 |", "|---|---|---|---|"]
    for i, c in enumerate(cues, 1):
        if c["flags"]:
            table.append(f"| {i} | {srt_time(c['start'])} → {srt_time(c['end'])} | {c['show']} | {'；'.join(c['flags'])} |")
    return "\n".join(head + table + [""])


# 命令列進入點：讀對照表、對齊、合併、寫出 3 個檔；成功回傳 0，出錯回傳 1
def main(argv=None):
    p = argparse.ArgumentParser(description="依配音的停頓算出字幕時間，輸出 master.srt")
    p.add_argument("voice_lines", help="voice_lines.json 的路徑；輸出寫在同一個資料夾")
    p.add_argument("--threshold-db", type=float, default=-40, help="比這個音量小算靜音（dB，預設 -40）")
    p.add_argument("--min-pause", type=float, default=0.12, help="靜音至少多久才算停頓（秒，預設 0.12）")
    p.add_argument("--min-dur", type=float, default=0.8, help="字幕最短顯示時間（秒，預設 0.8）")
    p.add_argument("--max-width", type=int, default=40, help="一行最大寬度（全形算 2，預設 40）")
    args = p.parse_args(argv)
    try:
        segments = load_lines(args.voice_lines)
        cues = align_all(segments, args.threshold_db, args.min_pause)
        cues = flag_cues(merge_short(cues, args.min_dur, args.max_width), args.min_dur)
    except AlignError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1

    out_dir = Path(args.voice_lines).parent
    outputs = {
        "master.srt": to_srt(cues),
        "cues.json": json.dumps(cues, ensure_ascii=False, indent=1),
        "align_review.md": review_text(cues),
    }
    for name, text in outputs.items():
        path = out_dir / name
        note = "（覆蓋舊檔）" if path.exists() else ""
        path.write_text(text, encoding="utf-8")
        print(f"寫入 {path}{note}")
    flagged = sum(1 for c in cues if c["flags"])
    print(f"共 {len(cues)} 句字幕，{flagged} 句要抽查（見 align_review.md）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
