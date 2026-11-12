"""讀 Claude 照分鏡表寫的 合成.json，把 B-roll、說明動畫、配音、疊加層組成預覽影片（也能只輸出樣張或一段樣片）。

用法（在 skill 資料夾）：
    uv run --project . python helpers/compose.py <資料夾>/edit/合成.json [--full] [--samples] [--clip 開始秒數 [長度]] [--font 字型檔]

同一個資料夾要有 align_voice.py 的輸出 cues.json 和它讀的 voice_lines.json。合成.json 的格式和使用步驟見 sop/科普短片.md 第 13 步。
"""

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ---------- 風格表：位置、字級、顏色都照 sop/風格_暗色科技風.md，座標以 1080×1920 為準 ----------
COLORS = {
    "red": "#ff5a3c", "cyan": "#7fd8ff", "amber": "#ffb340", "green": "#5be08a", "white": "#ffffff",
    "line": "#c9d1db", "dim": "#8a93a0", "small": "#aab3bf", "sub": "#ffd43b",
}
NUMBER_COLORS = ("red", "cyan", "amber", "green", "white")  # 數字卡可以用的顏色
WIDTH, HEIGHT = 1080, 1920
BROLL_TOP = 560  # 橫式 B-roll 原畫面離頂部的距離（上方留給頂部標題）
BG_ZOOM = 1.15  # 橫式 B-roll 的背景：同一個畫面放大、模糊、調暗，填滿上下空白
BG_DIM = 0.45
# 疊加層：(字級, 中心 y)。值照 11/6 試做的 overlay.py
TITLE_STYLE = (52, 120)  # 頂部標題，整支片都在
NUMBER_STYLE = {"big": (120, 1300), "label": (42, 1405), "note": (30, 1465)}  # 數字卡：大數字、說明、估算小字
SECTION_STYLE = {"small": (40, 850), "big": (110, 960)}  # 段落標題卡
SUB_STYLE = {"zh": (58, 1640), "en": (36, 1712)}  # 字幕：中文黃色、英文白色
TEXT_MAX_W = 1000  # 一行最寬多少，超過就縮小字級
SECTION_LEAD = 0.3  # 段落標題卡在切點前幾秒開始淡入，切點那一格完整顯示（11/6 有 2 處閃是因為切過去才淡入）
SECTION_HOLD = 1.8  # 段落標題卡從切點起顯示幾秒（最後 0.3 秒淡出）
NUMBER_FADE = 0.35
TAIL = 1.5  # 最後一段配音結束後，片尾多留幾秒
AUDIO_FADE = 0.03  # 每段配音頭尾淡入淡出的秒數，避免接縫爆音
LOUDNESS, TRUE_PEAK = -14, -1  # 配音音量校正的目標：-14 LUFS（YouTube 的標準音量）、峰值 -1 dBTP
SEGMENT_LEAD = 0.5  # 段落第一句的鏡頭提早幾秒換：從段落之間的空檔開始，不等念出第一個字
PICTURES = ("broll", "animation", "presenter")  # 鏡頭底下的畫面，三選一
FPS = 30

# 換鏡頭檢查：看 B-roll 頭尾各 0.6 秒，某一格的變化比前後各 4 格的中位數大 2 倍以上就算換畫面。
# 2026-11-11 用 11/6 試做的 26 個 B-roll 鏡頭頭尾實測：13 處真的換畫面都抓到，誤報 1 次（推進器突然噴煙）。
# 不用 ffmpeg 的 scene，因為它在暗的畫面會漏抓；不和整段平常的變化比，因為講者揮手這類畫面會被誤認
CUT_WINDOW = 0.6
CUT_NEIGHBORS = 4
CUT_RATIO = 2.0
CUT_FLOOR = 0.5  # 前後幾格幾乎沒變化時，中位數至少算 0.5，不然靜止畫面的一點雜訊也會變成好幾倍
SUGGEST_RANGE = 10.0  # 建議新起點時，在原本起點前後幾秒內找
SUGGEST_MARGIN = 0.1  # 建議的起點離換畫面至少 0.6 + 0.1 秒


# 合成.json、cues.json 有問題時用的錯誤，訊息直接給使用者看
class ComposeError(Exception):
    pass


# 比對字幕前拿掉空白和標點，規則同 Remotion 零件庫的 cues.ts
def normalize(text):
    return re.sub(r"[\s　，。；：？！、,.;:?!「」『』（）()\"'“”‘’…—-]", "", text)


# 用字幕文字找那一句字幕，回傳第幾句（從 0 算）。只找 after 那句之後的字幕，所以同一句出現兩次時，
# 鏡頭依序對到前後兩句；整句完全相同的優先；只是包含又有好幾句符合就報錯，避免鏡頭悄悄對錯時間
def find_cue(cues, text, after=-1):
    key = normalize(text)
    hits = [i for i in range(after + 1, len(cues))
            if key and (key in normalize(cues[i]["show"]) or key in normalize(cues[i].get("say", "")))]
    exact = [i for i in hits if normalize(cues[i]["show"]) == key or normalize(cues[i].get("say", "")) == key]
    if exact:
        return exact[0]
    if not hits:
        where = "" if after < 0 else f"在第 {after + 1} 句字幕之後"
        raise ComposeError(f"cues.json {where}找不到字幕「{text}」（鏡頭的順序要和字幕順序相同）")
    if len(hits) > 1:
        raise ComposeError(f"cues.json 有 {len(hits)} 句字幕都含「{text}」，請寫長一點")
    return hits[0]


# 讀 合成.json 並檢查欄位：畫面三選一（或只有段落標題）、B-roll 要有起點、素材檔要存在；路徑換成完整路徑
def load_plan(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ComposeError(f"讀不到 {path}：{e}")
    shots = data.get("shots") or []
    if not shots:
        raise ComposeError(f"{path.name} 沒有 shots")
    out = []
    for i, raw in enumerate(shots, 1):
        where = f"第 {i} 個鏡頭（from「{raw.get('from', '')}」）"
        if not str(raw.get("from", "")).strip():
            raise ComposeError(f"第 {i} 個鏡頭少了 from")
        shot = dict(raw)
        kinds = [k for k in PICTURES if k in raw]
        if len(kinds) > 1:
            raise ComposeError(f"{where}同時寫了 {'、'.join(kinds)}，畫面只能選一種")
        if not kinds and "section" not in raw:
            raise ComposeError(f"{where}沒有畫面：要寫 broll、animation、presenter 其中一個，或只寫 section 做全螢幕標題卡")
        shot["picture"] = kinds[0] if kinds else None
        if shot["picture"]:
            src = path.parent / raw[shot["picture"]]
            if not src.is_file():
                raise ComposeError(f"{where}找不到素材：{src}")
            shot[shot["picture"]] = src
        if shot["picture"] == "broll":
            if not isinstance(raw.get("in"), (int, float)) or raw["in"] < 0:
                raise ComposeError(f"{where}的 broll 要寫起點秒數 in（0 以上的數字）")
        number = raw.get("number")
        if number:
            if not number.get("big") or not number.get("label"):
                raise ComposeError(f"{where}的 number 要有 big 和 label")
            if number.get("color", "white") not in NUMBER_COLORS:
                raise ComposeError(f"{where}的數字卡顏色 {number['color']} 不在風格表裡（可用：{'、'.join(NUMBER_COLORS)}）")
        section = raw.get("section")
        if section is not None and (not section.get("small") or not section.get("big")):
            raise ComposeError(f"{where}的 section 要有 small 和 big")
        out.append(shot)
    return {"title": data.get("title") or {}, "shots": out, "path": path}


# 算每個鏡頭的開始、結束秒數；鏡頭放到下一個鏡頭開始，最後一個放到片尾。素材不夠長就報錯
def build_timeline(plan, cues, total, durations):
    shots, last = [], -1
    for i, shot in enumerate(plan["shots"]):
        try:
            k = find_cue(cues, shot["from"], after=last)
            at_k = find_cue(cues, shot["number"]["at"], after=k - 1) if (shot.get("number") or {}).get("at") else None
        except ComposeError as e:
            raise ComposeError(f"第 {i + 1} 個鏡頭：{e}")
        start = cues[k]["start"]
        if i == 0:
            start = 0.0
        elif cues[k]["seg"] != cues[k - 1]["seg"]:  # 段落第一句
            start = max(start - SEGMENT_LEAD, 0.0)
        if shots and start <= shots[-1]["start"]:
            raise ComposeError(f"第 {i + 1} 個鏡頭（from「{shot['from']}」）和前一個鏡頭太近，長度會是 0")
        s = dict(shot, start=round(start, 3))
        if shot.get("number"):
            s["number"] = dict(shot["number"], at=round(cues[at_k]["start"], 3) if at_k is not None else s["start"])
        shots.append(s)
        last = k
    for i, s in enumerate(shots):
        s["end"] = shots[i + 1]["start"] if i + 1 < len(shots) else round(total, 3)
        if s["end"] <= s["start"]:
            raise ComposeError(f"第 {i + 1} 個鏡頭的長度是 0：from「{s['from']}」和下一個鏡頭從同一句開始")
        if s["picture"]:
            src = s[s["picture"]]
            begin = s.get("in", 0.0) if s["picture"] == "broll" else 0.0
            need = begin + s["end"] - s["start"]
            have = durations(src)
            if need > have + 1e-3:
                raise ComposeError(f"第 {i + 1} 個鏡頭（from「{s['from']}」）要用到 {src.name} 的 {need:.2f} 秒，素材只有 {have:.2f} 秒")
    return shots


# 讀素材的影格率（每秒幾格）
def frame_rate(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        num, _, den = out.stdout.strip().partition("/")
        return float(num) / float(den or 1)
    except ValueError:
        raise ComposeError(f"讀不到 {path} 的影格率：{out.stderr.strip()}")


# 讀素材一段時間的畫面，縮小成 64×36 灰階，回傳 (格數, 36, 64) 的陣列。
# 用素材原本的影格率讀：轉成每秒 30 格會插入重複的格（變化是 0），把比較用的中位數拉低，造成誤報（11/11 實測）
def gray_frames(path, start, length):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0.0):.3f}", "-i", str(path), "-t", f"{length:.3f}",
         "-vf", "scale=64:36,format=gray", "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if out.returncode != 0:
        raise ComposeError(f"讀不到 {path} 的畫面：{out.stderr.decode('utf-8', 'replace').strip()}")
    return np.frombuffer(out.stdout, np.uint8).reshape(-1, 36, 64).astype(np.float32)


# 讀素材 [start, start+length) 每一格和下一格的變化量。回傳 (變化量陣列, 實際開始秒數, 影格率)；
# diffs[i] 是「第 i 格 → 第 i+1 格」的變化，第 i 格的時間是 begin + i / fps
def frame_diffs(path, start, length):
    fps = frame_rate(path)
    begin = max(start, 0.0)
    frames = gray_frames(path, begin, length - (begin - start))
    if len(frames) < 2:
        return np.zeros(0, np.float32), begin, fps
    return np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)), begin, fps


# 在讀好的變化量上，看 t0 開始的 0.6 秒內有沒有換畫面；有的話回傳換畫面的秒數，沒有回傳 None
def window_jump(diffs, begin, fps, t0, window=CUT_WINDOW):
    first = round((t0 - begin) * fps)  # 視窗裡第一格；diffs[first] 是它換到下一格的變化
    # 視窗裡有 n 格會播出，格和格之間只有 n-1 次變化；不算「最後一格 → 視窗外下一格」，那一格不會播出
    inside = diffs[max(first, 0):first + round(window * fps) - 1]
    if len(inside) == 0:
        return None
    k = max(first, 0) + int(inside.argmax())
    neighbors = np.concatenate([diffs[max(0, k - CUT_NEIGHBORS):k], diffs[k + 1:k + 1 + CUT_NEIGHBORS]])
    base = max(float(np.median(neighbors)) if len(neighbors) else 0.0, CUT_FLOOR)
    if diffs[k] / base < CUT_RATIO:
        return None
    return round(begin + (k + 1) / fps, 3)


# 看素材從 t0 開始的 0.6 秒內有沒有換畫面；有的話回傳換畫面的秒數，沒有回傳 None
def find_jump(path, t0, window=CUT_WINDOW):
    pad = (CUT_NEIGHBORS + 1) / frame_rate(path)  # 視窗前後多讀幾格，當作比較用的鄰居
    diffs, begin, fps = frame_diffs(path, t0 - pad, window + 2 * pad)
    return window_jump(diffs, begin, fps, t0, window)


# 在原本起點前後 search 秒內，找頭尾 0.6 秒內都不會換畫面、又最接近原本起點的 in；找不到回傳 None。
# 鏡頭中間換畫面是正常剪接，不算閃，所以只檢查頭尾
def suggest_in(path, length, current, search=SUGGEST_RANGE):
    fps = frame_rate(path)
    lo, hi = max(current - search, 0.0), min(current + search, media_duration(path) - length)
    if hi < lo:
        return None
    pad = (CUT_NEIGHBORS + 1) / fps
    diffs, begin, fps = frame_diffs(path, lo - pad, hi - lo + length + 2 * pad)
    steps = int((hi - lo) * fps) + 1
    confirmations = 0
    for x in sorted((lo + j / fps for j in range(steps)), key=lambda x: abs(x - current)):
        x = round(x, 2)  # 建議值寫成兩位小數，檢查的也是這個值
        if x < lo or x > hi:
            continue
        # 建議時多留 SUGGEST_MARGIN 秒，不建議剛好踩在 0.6 秒邊界上的起點
        w = min(CUT_WINDOW + SUGGEST_MARGIN, length / 2)
        head = window_jump(diffs, begin, fps, x, w)
        tail = window_jump(diffs, begin, fps, x + length - w, w)
        if head is not None or tail is not None:
            continue
        # 再用 check_cuts 本身的讀法驗一次：從不同位置開始讀畫面，格的時間可能差 1 格，
        # 換畫面剛好在頭尾邊界時兩邊會判斷不同（11/11 實測）。兩邊都過才建議，下一輪檢查才一定會過
        confirmations += 1
        if find_jump(path, x, min(CUT_WINDOW, length)) is None and (
                length <= CUT_WINDOW or find_jump(path, x + length - CUT_WINDOW) is None):
            return x
        if confirmations >= 20:
            break
    return None


# 把換畫面前後 12 格排成一張對照圖（6×2），給 Claude 看是不是真的會閃
def save_contact_sheet(path, t, out_file):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t - 6 / FPS, 0.0):.3f}", "-i", str(path),
         "-vf", f"fps={FPS},scale=320:-2,tile=6x2", "-frames:v", "1", str(out_file)],
        check=True,
    )


# 檢查每個 B-roll 鏡頭頭尾各 0.6 秒，素材本身有沒有換畫面（會閃一下）。
# 回傳問題清單：每個有問題的鏡頭一則，附對照圖，和一個頭尾都不會閃的建議起點（找得到的話）
def check_cuts(shots, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)  # 舊的對照圖會誤導，每次重新檢查都清掉
    issues = []
    for i, s in enumerate(shots, 1):
        if s["picture"] != "broll" or s.get("cut_ok"):
            continue
        src, start_in = s["broll"], float(s["in"])
        length = s["end"] - s["start"]
        found = []
        head = find_jump(src, start_in, min(CUT_WINDOW, length))
        if head is not None:
            found.append(("開頭", head))
        if length > CUT_WINDOW:
            tail = find_jump(src, start_in + length - CUT_WINDOW)
            if tail is not None and tail != head:
                found.append(("結尾", tail))
        if not found:
            continue
        sheets = []
        for part, t in found:
            sheet = out_dir / (f"{i}.jpg" if len(found) == 1 else f"{i}_{'head' if part == '開頭' else 'tail'}.jpg")
            save_contact_sheet(src, t, sheet)
            sheets.append(f"{part}在 {t:.2f} 秒（{sheet}）")
        new_in = suggest_in(src, length, start_in)
        if new_in is not None:
            fix = f"把 in 改成 {new_in}（頭尾 0.6 秒內都不會換畫面；看一下新起點的畫面合不合適）"
        else:
            fix = (f"in 前後 {SUGGEST_RANGE:.0f} 秒內找不到頭尾都不會換畫面的起點（素材剪接太密），"
                   "換一段素材，或把這個鏡頭拆成兩個")
        issues.append(f"第 {i} 個鏡頭（from「{s['from']}」）：{src.name} {'、'.join(sheets)}換畫面，成品會閃一下。"
                      f"看對照圖後二選一：{fix}；或加上 \"cut_ok\": true（判斷是誤報）")
    return issues


# 讀素材的寬高；手機直拍的影片會記錄旋轉角度，轉 90 度時寬高對調
def video_size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        stream = json.loads(out.stdout)["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError):
        raise ComposeError(f"讀不到 {path} 的寬高：{out.stderr.strip()}")
    w, h = int(stream["width"]), int(stream["height"])
    rotation = next((int(d.get("rotation", 0)) for d in stream.get("side_data_list", []) if "rotation" in d), 0)
    return (h, w) if abs(rotation) % 180 == 90 else (w, h)


# 做一個鏡頭的底層畫面：橫式 B-roll 中間放原畫面、上下用模糊背景填滿；直式素材鋪滿；只有標題卡的鏡頭放黑畫面
def shot_command(shot, frames, out_file, scale, encode):
    w, h = int(WIDTH * scale), int(HEIGHT * scale)
    if shot["picture"] is None:
        return ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={FPS}",
                "-frames:v", str(frames), *encode, str(out_file)]
    src = shot[shot["picture"]]
    # B-roll 從 in 開始取；動畫和講者從頭開始，只合成一段樣片時從 offset 開始
    start = float(shot.get("in", 0.0)) if shot["picture"] == "broll" else float(shot.get("offset", 0.0))
    sw, sh = video_size(src)
    if shot["picture"] == "broll" and sw > sh:
        bh = int(h * BG_ZOOM)
        graph = (f"[0:v]fps={FPS},split[a][b];"
                 f"[a]scale=-2:{bh // 4},boxblur=6:2,scale=-2:{bh},crop={w}:{h},"
                 f"colorchannelmixer=rr={BG_DIM}:gg={BG_DIM}:bb={BG_DIM}[bg];"
                 f"[b]scale={w}:-2[fg];[bg][fg]overlay=0:{int(BROLL_TOP * scale)},setsar=1[v]")
    else:
        graph = f"[0:v]fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[v]"
    return ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-filter_complex", graph,
            "-map", "[v]", "-frames:v", str(frames), *encode, str(out_file)]


# 做整支片的底層影片（還沒有文字）：每個鏡頭各自切好、轉成直式，再照順序無損接起來。
# 鏡頭長度用格數算（開始、結束各自四捨五入到格），接起來的總格數才會剛好等於總長 × 30
def build_base(shots, total, out_path, full=False):
    scale = 1.0 if full else 0.5
    encode = ["-c:v", "libx264", "-preset", "medium" if full else "ultrafast", "-crf", "18" if full else "26",
              "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
    with tempfile.TemporaryDirectory(prefix="compose_base_") as tmp:
        tmp = Path(tmp)
        jobs = []
        for i, s in enumerate(shots):
            frames = round(s["end"] * FPS) - round(s["start"] * FPS)
            jobs.append(shot_command(s, frames, tmp / f"{i:03d}.mp4", scale, encode))

        def run(cmd):
            out = subprocess.run(cmd, capture_output=True)
            if out.returncode != 0:
                raise ComposeError(f"做底層畫面失敗：{out.stderr.decode('utf-8', 'replace').strip()}")

        with ThreadPoolExecutor(4) as pool:
            list(pool.map(run, jobs))
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{i:03d}.mp4'\n" for i in range(len(jobs))), encoding="utf-8")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path)])
    return out_path


# 依作業系統找中文字型檔，回傳 (粗體檔, 一般檔, .ttc 裡的第幾個字型)；找不到就報錯請使用者用 --font 指定。
# 不沿用 render.py：它只寫字型名稱、不分作業系統，這裡畫字要的是字型檔的路徑
def default_font(platform=sys.platform):
    if platform == "win32":
        candidates = [("C:/Windows/Fonts/msjhbd.ttc", "C:/Windows/Fonts/msjh.ttc", 0)]  # 微軟正黑體
    elif platform == "darwin":
        candidates = [("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc", 3)]  # 蘋方（沒測過）
    else:
        candidates = [(f"{d}/NotoSansCJK-Bold.ttc", f"{d}/NotoSansCJK-Regular.ttc", 3)  # 第 3 個是繁體中文
                      for d in ("/usr/share/fonts/opentype/noto", "/usr/share/fonts/noto-cjk")]
    for bold, regular, index in candidates:
        if Path(bold).is_file() and Path(regular).is_file():
            return (bold, regular, index)
    raise ComposeError("找不到預設的中文字型，請用 --font 指定字型檔（例如 --font C:/Windows/Fonts/msjh.ttc）")


# 主要字型缺字時用的備用字型 [(粗體檔, 一般檔)]，只回傳這台電腦有的。
# 例如微軟正黑體沒有「≈」和 align_voice.py 合併字幕時插入的空白（U+2002），會畫成方框（11/11 實測）
def fallback_fonts(platform=sys.platform):
    if platform == "win32":
        candidates = [("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf")]
    elif platform == "darwin":
        candidates = []
    else:
        candidates = [("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    return [(b, r) for b, r in candidates if Path(b).is_file() and Path(r).is_file()]


# 把標題拆成 [(文字, 顏色)]：強調字用紅色，其他白色
def title_parts(text, accents):
    parts, i = [], 0
    while i < len(text):
        hits = [(text.find(a, i), a) for a in accents if a and text.find(a, i) >= 0]
        if not hits:
            parts.append((text[i:], "white"))
            break
        pos, word = min(hits)
        if pos > i:
            parts.append((text[i:pos], "white"))
        parts.append((word, "red"))
        i = pos + len(word)
    return parts


# 緩動：一開始快、最後慢慢停下（0→1）
def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


# 疊加層：算某個時間點畫面上有哪些文字，畫成透明背景的圖。座標以 1080×1920 設計，乘上 scale 輸出
class Overlay:
    def __init__(self, title, shots, cues, scale, font, fallback=None):
        self.shots, self.cues, self.scale = shots, cues, scale
        self.bold, self.regular, self.index = font
        self.fallback = fallback_fonts() if fallback is None else fallback
        self.title = title_parts(title.get("text", ""), title.get("accent", [])) if title.get("text") else []
        self.w, self.h = int(WIDTH * scale), int(HEIGHT * scale)
        self._fonts, self._texts, self._glyphs = {}, {}, {}
        self.gradient = self._make_gradient()

    # 讀字型（同樣字級只讀一次）；which 是 -1 時讀主要字型，0 以上讀第幾個備用字型
    def font(self, size, bold=True, which=-1):
        key = (size, bold, which)
        if key not in self._fonts:
            px = max(1, round(size * self.scale))
            if which < 0:
                self._fonts[key] = ImageFont.truetype(self.bold if bold else self.regular, px, index=self.index)
            else:
                self._fonts[key] = ImageFont.truetype(self.fallback[which][0 if bold else 1], px)
        return self._fonts[key]

    # 字型有沒有這個字：沒有的字會畫成和「不存在的字（U+FFFF）」一樣的方框
    def has_glyph(self, font, ch):
        key = (id(font), ch)
        if key not in self._glyphs:
            self._glyphs[key] = ch.isspace() and ch == " " or bytes(font.getmask(ch)) != bytes(font.getmask("￿"))
        return self._glyphs[key]

    # 把一段文字切成 [(文字, 字型)]：主要字型缺的字，改用第一個有這個字的備用字型
    def glyph_runs(self, text, size, bold=True):
        runs = []
        for ch in text:
            f = self.font(size, bold)
            if not self.has_glyph(f, ch):
                f = next((self.font(size, bold, k) for k in range(len(self.fallback))
                          if self.has_glyph(self.font(size, bold, k), ch)), f)
            if runs and runs[-1][1] is f:
                runs[-1] = (runs[-1][0] + ch, f)
            else:
                runs.append((ch, f))
        return runs

    # 把 [(文字, 顏色)] 畫成一張置中用的透明圖，太寬就縮小字級；shadow 時加一層模糊的黑影，在亮的畫面上也看得清楚
    def text_image(self, parts, size, bold=True, shadow=True):
        key = (tuple(parts), size, bold, shadow)
        if key in self._texts:
            return self._texts[key]
        while True:
            runs = [(r, f, c) for t, c in parts for r, f in self.glyph_runs(t, size, bold)]
            widths = [f.getlength(r) for r, f, _ in runs]
            if sum(widths) <= TEXT_MAX_W * self.scale or size <= 20:
                break
            size -= 2
        ascent, descent = self.font(size, bold).getmetrics()
        pad = max(1, round(12 * self.scale))
        img = Image.new("RGBA", (int(sum(widths)) + 2 * pad, ascent + descent + 2 * pad), (0, 0, 0, 0))
        draw, x = ImageDraw.Draw(img), pad
        for (r, f, c), tw in zip(runs, widths):
            # 備用字型的基線和主要字型不同，對齊基線（主要字型的 ascent）再畫
            draw.text((x, pad + ascent), r, font=f, fill=COLORS.get(c, c), anchor="ls")
            x += tw
        if shadow:
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sh.putalpha(img.split()[3].point(lambda v: int(v * 0.85)))
            sh = sh.filter(ImageFilter.GaussianBlur(4 * self.scale))
            out = Image.new("RGBA", img.size, (0, 0, 0, 0))
            out.alpha_composite(sh, (0, round(3 * self.scale)))
            out.alpha_composite(img)
            img = out
        self._texts[key] = img
        return img

    # 把文字畫在畫面中線、y = cy 的位置；alpha 是透明度，dy 是往下偏移（做滑入效果）
    def put_text(self, canvas, parts, style, alpha=1.0, dy=0.0, bold=True, shadow=True):
        size, cy = style
        img = self.text_image(parts, size, bold, shadow)
        if alpha < 1.0:
            img = img.copy()
            img.putalpha(img.split()[3].point(lambda v: int(v * alpha)))
        canvas.alpha_composite(img, (int(self.w / 2 - img.width / 2), int((cy + dy) * self.scale - img.height / 2)))

    # 段落標題卡的底色：由中間往外的暗色漸層
    def _make_gradient(self):
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        r = np.sqrt(((xx - self.w / 2) / (self.w / 2)) ** 2 + ((yy - self.h / 2) / (self.h / 2)) ** 2) / math.sqrt(2)
        r = np.clip(r, 0, 1)[..., None]
        rgb = np.array([0x1c, 0x21, 0x29], np.float32) * (1 - r) + np.array([0x0b, 0x0d, 0x10], np.float32) * r
        alpha = np.full((self.h, self.w, 1), 255, np.float32)
        return Image.fromarray(np.concatenate([rgb, alpha], 2).astype(np.uint8), "RGBA")

    # 第 i 個鏡頭的段落標題卡在時間 t 的透明度（0 是不顯示）。只有標題卡的鏡頭一直顯示到鏡頭結束、不淡出
    def section_alpha(self, i, t):
        s = self.shots[i]
        if not s.get("section"):
            return 0.0
        cut = s["start"]
        end = s["end"] if s["picture"] is None else cut + SECTION_HOLD
        if t < cut - SECTION_LEAD or t >= end:
            return 0.0
        a = 1.0 if t >= cut else ease_out((t - (cut - SECTION_LEAD)) / SECTION_LEAD)
        if s["picture"] is not None and end - t < 0.3:
            a = min(a, max(0.0, (end - t) / 0.3))
        return round(a, 3)

    # 第 i 個鏡頭的數字卡在時間 t 的出現進度（0→1）；不顯示時回傳 None
    def number_progress(self, i, t):
        n = self.shots[i].get("number")
        if not n or t < n["at"] or t >= self.shots[i]["end"]:
            return None
        return round(ease_out((t - n["at"]) / NUMBER_FADE), 3)

    # 時間 t 正在顯示的字幕（沒有就回傳 None）
    def cue_at(self, t):
        return next((i for i, c in enumerate(self.cues) if c["start"] <= t < c["end"]), None)

    # 這一格畫面的「狀態」：兩格狀態相同就表示畫出來一樣，直接沿用上一張圖
    def frame_key(self, t):
        key = []
        for i in range(len(self.shots)):
            a = self.section_alpha(i, t)
            if a > 0:
                key.append(("s", i, a, round(min(t - self.shots[i]["start"] + SECTION_LEAD, 0.4), 2)))
            p = self.number_progress(i, t)
            if p is not None:
                key.append(("n", i, p))
        key.append(("c", self.cue_at(t)))
        return tuple(key)

    # 畫出時間 t 的疊加層：段落標題卡 → 數字卡 → 頂部標題 → 字幕（字幕最後畫，不會被蓋住）
    def render(self, t):
        canvas = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        for i, s in enumerate(self.shots):
            a = self.section_alpha(i, t)
            if a > 0:
                g = self.gradient.copy()
                g.putalpha(int(255 * a))
                canvas.alpha_composite(g)
                slide = 20 * (1 - ease_out((t - (s["start"] - SECTION_LEAD)) / 0.4))
                self.put_text(canvas, [(s["section"]["small"], "small")], SECTION_STYLE["small"], a, shadow=False)
                self.put_text(canvas, [(s["section"]["big"], "red")], SECTION_STYLE["big"], a, dy=slide, shadow=False)
        for i, s in enumerate(self.shots):
            p = self.number_progress(i, t)
            if p is None or p <= 0:
                continue
            n = s["number"]
            self.put_text(canvas, [(n["big"], n.get("color", "white"))], NUMBER_STYLE["big"], p, dy=30 * (1 - p))
            self.put_text(canvas, [(n["label"], "line")], NUMBER_STYLE["label"], p)
            if n.get("note"):
                self.put_text(canvas, [(n["note"], "dim")], NUMBER_STYLE["note"], p, bold=False)
        if self.title:
            self.put_text(canvas, self.title, TITLE_STYLE)
        k = self.cue_at(t)
        if k is not None:
            self.put_text(canvas, [(self.cues[k]["show"], "sub")], SUB_STYLE["zh"])
            if self.cues[k].get("en"):
                self.put_text(canvas, [(self.cues[k]["en"], "white")], SUB_STYLE["en"])
        return canvas


# 把疊加層逐格畫好，透過管線送進 ffmpeg 疊在底層影片上，再接上配音（audio 是 None 時沒有聲音）。
# 畫面狀態沒變的格直接重送上一張圖，不重畫；回傳實際重畫了幾格
def write_video(base, overlay, total, out_path, full=False, audio=None, first_frame=0):
    frames = round(total * FPS) - first_frame
    encode = ["-c:v", "libx264", "-preset", "medium" if full else "veryfast", "-crf", "18" if full else "24",
              "-pix_fmt", "yuv420p"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(base),
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{overlay.w}x{overlay.h}", "-r", str(FPS), "-i", "pipe:0"]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-filter_complex", "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]", "-map", "[v]"]
    if audio:
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "192k"]
    cmd += [*encode, "-r", str(FPS), "-frames:v", str(frames), "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    last_key, last_bytes, drawn = None, None, 0
    try:
        for i in range(frames):
            t = (first_frame + i) / FPS
            key = overlay.frame_key(t)
            if key != last_key:
                last_bytes, last_key = overlay.render(t).tobytes(), key
                drawn += 1
            proc.stdin.write(last_bytes)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace").strip()
    if proc.wait() != 0:
        raise ComposeError(f"合成影片失敗：{err}")
    return drawn


# 讀影片或音檔的長度（秒）
def media_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise ComposeError(f"讀不到 {path} 的長度：{out.stderr.strip()}")


# 讀 voice_lines.json，算出每段配音在片子裡的開始秒數和片子總長（最後一段結束後留 TAIL 秒）。
# start 沒寫的接在上一段後面，規則和 align_voice.py 相同，字幕和聲音才對得上
def load_voice(path):
    path = Path(path)
    try:
        segments = json.loads(path.read_text(encoding="utf-8"))["segments"]
    except (OSError, json.JSONDecodeError, KeyError) as e:
        raise ComposeError(f"讀不到 {path}：{e}")
    voice, cursor = [], 0.0
    for i, seg in enumerate(segments, 1):
        audio = path.parent / seg.get("audio", "")
        if not audio.is_file():
            raise ComposeError(f"voice_lines.json 第 {i} 段找不到音檔：{audio}")
        start = cursor if seg.get("start") is None else float(seg["start"])
        dur = media_duration(audio)
        voice.append({"file": audio, "start": start, "dur": dur})
        cursor = start + dur
    if not voice:
        raise ComposeError(f"{path.name} 沒有 segments")
    return voice, round(voice[-1]["start"] + voice[-1]["dur"] + TAIL, 3)


# 做配音音軌：每段放在自己的開始秒數，頭尾各淡入淡出 0.03 秒（避免接縫爆音），
# 再用兩次 loudnorm（先量、再照量到的值校正）調到 -14 LUFS、峰值 -1 dBTP
def build_audio(voice, total, out_path, start=0.0):
    out_path = Path(out_path)
    inputs, chains = [], []
    for i, v in enumerate(voice):
        inputs += ["-i", str(v["file"])]
        delay = max(int(round((v["start"] - start) * 1000)), 0)
        skip = max(start - v["start"], 0.0)  # 只合成一段樣片時，起點之前的部分剪掉
        chains.append(f"[{i}:a]atrim=start={skip:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:st=0:d={AUDIO_FADE},afade=t=out:st={max(v['dur'] - skip - AUDIO_FADE, 0):.3f}:d={AUDIO_FADE},"
                      f"aresample=48000,adelay={delay}:all=1[a{i}]")
    length = total - start
    mix = "".join(f"[a{i}]" for i in range(len(voice))) + f"amix=inputs={len(voice)}:normalize=0,apad,atrim=0:{length:.3f}[m]"
    raw = out_path.with_name(out_path.stem + "_raw.wav")
    run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains + [mix]),
               "-map", "[m]", "-ar", "48000", str(raw)])
    if out.returncode != 0:
        raise ComposeError(f"混配音失敗：{out.stderr.strip()}")
    target = f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11"
    measured = run(["ffmpeg", "-i", str(raw), "-af", target + ":print_format=json", "-f", "null", "-"]).stderr
    try:
        m = json.loads(measured[measured.rindex("{"):measured.rindex("}") + 1])
    except ValueError:
        raise ComposeError(f"量不到配音音量：{measured.strip()[-300:]}")
    if m["input_i"] == "-inf":
        shutil.move(raw, out_path)  # 整段都沒有聲音，不用校正
        return out_path
    af = (f"{target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    out = run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", af, "-ar", "48000", str(out_path)])
    raw.unlink(missing_ok=True)
    if out.returncode != 0:
        raise ComposeError(f"校正配音音量失敗：{out.stderr.strip()}")
    return out_path


# 切出 [start, end) 這段時間用到的鏡頭，時間改成從 0 開始；被切到的鏡頭，素材起點跟著往後移
def clip_shots(shots, start, end):
    out = []
    for s in shots:
        if s["end"] <= start or s["start"] >= end:
            continue
        c = dict(s, start=round(max(s["start"], start) - start, 3), end=round(min(s["end"], end) - start, 3))
        skipped = max(start - s["start"], 0.0)
        if s["picture"] == "broll":
            c["in"] = float(s["in"]) + skipped
        else:
            c["offset"] = skipped
        out.append(c)
    return out


# 樣張要截的時間點：開場（頂部標題＋字幕）、每張數字卡、每張段落標題卡各一張。回傳 [(檔名, 秒數)]
def sample_times(shots, cues):
    times = [("01_開場.png", round(cues[0]["start"] + 0.5, 3) if cues else 0.5)]
    for i, s in enumerate(shots, 1):
        if s.get("number"):
            times.append((f"{len(times) + 1:02d}_數字卡_鏡頭{i}.png", round(s["number"]["at"] + NUMBER_FADE + 0.2, 3)))
        if s.get("section"):
            times.append((f"{len(times) + 1:02d}_段落標題卡_鏡頭{i}.png", round(s["start"] + 0.3, 3)))
    return times


# 輸出樣張：截底層畫面的那一格，疊上那一刻的疊加層，存成 1080×1920 的 PNG
def write_samples(shots, overlay, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    written = []
    with tempfile.TemporaryDirectory(prefix="compose_sample_") as tmp:
        for name, t in sample_times(shots, overlay.cues):
            frame = round(t * FPS)
            shot = next(s for s in clip_shots(shots, frame / FPS, (frame + 1) / FPS))
            base = Path(tmp) / "base.png"
            out = subprocess.run(shot_command(shot, 1, base, overlay.scale, []), capture_output=True)
            if out.returncode != 0:
                raise ComposeError(f"截樣張底圖失敗：{out.stderr.decode('utf-8', 'replace').strip()}")
            img = Image.open(base).convert("RGBA")
            img.alpha_composite(overlay.render(frame / FPS))
            img.convert("RGB").save(out_dir / name)
            written.append(out_dir / name)
    return written


# 讀參數、依序執行：讀清單 → 算時間 → 換鏡頭檢查（有問題就停）→ 依模式輸出預覽、正式版、樣張或樣片
def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="合成.json → 預覽影片（換鏡頭檢查沒過時不合成）")
    p.add_argument("plan", help="edit/合成.json；同一個資料夾要有 cues.json、voice_lines.json")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="輸出 1080×1920 正式版 edit/final.mp4")
    mode.add_argument("--samples", action="store_true", help="輸出確認點 4 的樣張到 edit/samples/")
    mode.add_argument("--clip", nargs="+", type=float, metavar=("開始秒數", "長度"),
                      help="只合成一段樣片 edit/clip.mp4，長度預設 12 秒")
    p.add_argument("--font", help="字型檔（.ttf、.ttc），預設依作業系統")
    args = p.parse_args(argv)
    try:
        edit = Path(args.plan).parent
        plan = load_plan(args.plan)
        cues_path = edit / "cues.json"
        if not cues_path.is_file():
            raise ComposeError(f"找不到 {cues_path}：先跑 align_voice.py")
        cues = json.loads(cues_path.read_text(encoding="utf-8"))
        voice, total = load_voice(edit / "voice_lines.json")
        shots = build_timeline(plan, cues, total, media_duration)
        issues = check_cuts(shots, edit / "compose_check")
        if issues:
            print(f"有 {len(issues)} 處素材本身換畫面，會閃一下，沒有合成：", file=sys.stderr)
            for x in issues:
                print(f"- {x}", file=sys.stderr)
            return 2
        font = (args.font, args.font, 0) if args.font else default_font()
        if args.font and not Path(args.font).is_file():
            raise ComposeError(f"找不到字型檔：{args.font}")
        full = args.full or args.samples
        overlay = Overlay(plan["title"], shots, cues, 1.0 if full else 0.5, font)

        if args.samples:
            written = write_samples(shots, overlay, edit / "samples")
            print(f"寫入 {len(written)} 張樣張到 {edit / 'samples'}（覆蓋舊的樣張）")
            return 0

        start, end = 0.0, total
        if args.clip:
            if len(args.clip) > 2:
                raise ComposeError("--clip 只接受開始秒數和長度兩個數字")
            start = round(args.clip[0] * FPS) / FPS  # 對齊到格，底層和疊加層的格數才一致
            end = min(start + (args.clip[1] if len(args.clip) > 1 else 12.0), total)
            if start >= end:
                raise ComposeError(f"--clip 的開始秒數超過片長 {total:.2f} 秒")
        out = edit / ("final.mp4" if args.full else "clip.mp4" if args.clip else "preview.mp4")
        note = "（覆蓋舊檔）" if out.exists() else ""
        with tempfile.TemporaryDirectory(prefix="compose_") as tmp:
            tmp = Path(tmp)
            base = build_base(clip_shots(shots, start, end), end - start, tmp / "base.mp4", full=args.full)
            audio = build_audio(voice, end, tmp / "voice.wav", start=start)
            write_video(base, overlay, end, out, full=args.full, audio=audio, first_frame=round(start * FPS))
        print(f"寫入 {out}{note}")
        return 0
    except ComposeError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
