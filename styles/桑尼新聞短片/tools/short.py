"""Vertical news short in the reference layout (spc3YBqiC4M), branded with Sunny Data Science CIS.

Usage: python short.py PLAN.json [--out NAME.mp4] [--preview] [--samples]

Layout (1080x1920, measured from the reference at 480x854, x2.25):
  dim blurred copy of the shot fills the frame; the shot itself sits in a band y=327..1327 that fades to
  black at the bottom; fixed title at y~325; info card (red tag + 2 lines) at y~1080; source / credit line;
  bilingual subtitle (zh over en) at y~1372; opening cover with boxed headline; red wipe into a brand outro.

Plan:
{
 "narration": "voice/錄音室版/X_rhythm.mp3", "plan": "voice/錄音室版/X.json",    # from prosody.py
 "title": "黃仁勳下台：|私事變成國安案",                 # text after | is highlighted
 "cover": {"lines": ["黃仁勳下台", "私事怎麼變成|國安案"], "dur": 2.2},
 "music": "music/bed.mp3",                               # optional
 "blocks": [
   {"vo": 0, "shots": [{"line": 0, "src": "../x.mp4", "in": 12.0, "mode": "band|full|anim|still",
                        "credit": "畫面／CNN", "info": {"tag": "...", "lines": ["...", "..."]}}]},
   {"sot": {"src": "../x.mp4", "in": 10.0, "out": 16.0, "tag": "原聲", "who": "...", "source": "...",
            "subs": [[0.0, 2.1, "中文", "English"], ...]}}
 ],
 "outro": {"dur": 3.2}
}
A VO block plays narration section `vo` (index into the prosody plan); each shot starts at its line's
first word and runs to the next shot. A SOT block plays the source with its own audio.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EDIT = Path(__file__).resolve().parent.parent
W, H, FPS = 1080, 1920, 30
BAND_Y, BAND_H, FADE_H = 327, 923, 300   # reference: image fades out by ~y 1250

# CIS palette (brand_guideline.md): Featured Red for tags and wipes, logo mint for highlights
RED = (186, 77, 67)
MINT = (126, 235, 217)
WHITE = (255, 255, 255)
SUB_ZH = MINT
BG = (5, 5, 5)
TEAL_DARK = (15, 45, 43)

# Brand assets: the episode's own copy first, else the shared style in the video-use skill
STYLE_DIR = Path.home() / ".claude" / "skills" / "video-use" / "styles" / "桑尼新聞短片"


def asset(*candidates):
    for c in candidates:
        if Path(c).is_file():
            return Path(c)
    raise SystemExit(f"missing asset, looked in: {candidates}")


FONT_ZH = "C:/Windows/Fonts/NotoSansTC-VF.ttf"
FONT_EN = str(asset(EDIT / "fonts" / "InterVariable.ttf", STYLE_DIR / "fonts" / "InterVariable.ttf"))
LOGO = asset(EDIT.parent / "images" / "logo_main_1x1.png", STYLE_DIR / "brand" / "logo_main_1x1.png")
BRAND = "桑尼資料科學"
TAGLINE = "不只學會，更要交付。"


WEIGHTS = {"Regular": 400, "Medium": 500, "SemiBold": 600, "Bold": 700, "Black": 900}
_FONTS = {}


def font(size, weight="Bold", en=False):
    key = (size, weight, en)
    if key not in _FONTS:
        f = ImageFont.truetype(FONT_EN if en else FONT_ZH, size)
        f.set_variation_by_axes([WEIGHTS[weight]])
        _FONTS[key] = f
    return _FONTS[key]


def run(cmd, tries=3):
    for _ in range(tries):   # the long final encode has crashed silently once; a retry gets through
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if not r.returncode:
            break
    if r.returncode:
        sys.exit(f"command failed: {' '.join(map(str, cmd))[:300]}\n{r.stderr[-1500:]}")
    return r


def probe_dur(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())


# ---------- text drawing ----------

def text_w(d, s, f):
    return d.textlength(s, font=f)


def draw_hl(d, cx, y, text, size, color=WHITE, hl=MINT, shadow=True):
    """Centered single line; the part after '|' is drawn in the highlight color."""
    parts = text.split("|")
    f = font(size)
    total = sum(text_w(d, p, f) for p in parts)
    x = cx - total / 2
    for k, p in enumerate(parts):
        if shadow:
            d.text((x + 2, y + 3), p, font=f, fill=(0, 0, 0, 200))
        d.text((x, y), p, font=f, fill=(hl if k else color) + (255,))
        x += text_w(d, p, f)


def draw_mixed(d, x, y, s, size, weight, fill, anchor="la"):
    """Chinese in Noto Sans TC, Latin runs in Inter (brand rule 4.3)."""
    runs, cur, cur_en = [], "", None
    for ch in s:
        en = ch.isascii() and (ch.isalnum() or ch in " .,'-&%$:/()")
        if cur and en != cur_en:
            runs.append((cur, cur_en)); cur = ""
        cur += ch; cur_en = en
    if cur:
        runs.append((cur, cur_en))
    fonts = [font(size, weight, en=bool(e)) for _, e in runs]
    widths = [d.textlength(t, font=f) for (t, _), f in zip(runs, fonts)]
    if anchor == "ma":
        x -= sum(widths) / 2
    for (t, _), f, w in zip(runs, fonts, widths):
        d.text((x, y), t, font=f, fill=fill)
        x += w
    return sum(widths)


def layer_title(d, title):
    draw_hl(d, W / 2, 300, title, 46)


def backing(img, y0, y1):
    """Soft dark plate so cards stay legible over burned-in source text."""
    plate = Image.new("RGBA", (W, y1 - y0), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    for yy in range(y1 - y0):
        pd.line([(0, yy), (W, yy)], fill=(5, 5, 5, int(170 * min(1, yy / 30, (y1 - y0 - yy) / 30))))
    img.alpha_composite(plate, (0, y0))


def layer_info(d, info):
    """Red tag box, thin rule, then up to two white lines (reference lower-third)."""
    y = 1080
    ft = font(25, "Bold")
    tw = d.textlength(info["tag"], font=ft)
    d.rectangle([99, y, 99 + tw + 24, y + 42], fill=RED + (255,))
    d.text((99 + 12, y + 5), info["tag"], font=ft, fill=WHITE + (255,))
    d.line([99 + tw + 24, y + 41, W - 99, y + 41], fill=RED + (200,), width=2)
    for k, line in enumerate(info.get("lines", [])[:2]):
        draw_mixed(d, 104, y + 62 + k * 50, line, 32, "Medium", WHITE + (255,))


def layer_sot_card(d, tag, who, source):
    """'原聲｜Name, title' red box + small source line (reference SOT card)."""
    y = 1255
    label = f"{tag}｜{who}"
    tw = sum(d.textlength(c, font=font(25, "Bold", en=c.isascii())) for c in label)
    d.rectangle([99, y, 99 + tw + 24, y + 40], fill=RED + (255,))
    draw_mixed(d, 99 + 12, y + 4, label, 25, "Bold", WHITE + (255,))
    if source:
        draw_mixed(d, 104, y + 56, source, 21, "Regular", (230, 230, 230, 255))


def layer_credit(d, credit):
    draw_mixed(d, 104, 1314, credit, 21, "Regular", (230, 230, 230, 235))


def measure(d, s, size, weight):
    probe = Image.new("RGBA", (10, 10))
    return draw_mixed(ImageDraw.Draw(probe), 0, 0, s, size, weight, (0, 0, 0, 0))


def fit_lines(d, s, size, weight, max_w, min_size):
    """One line if it fits (shrinking down to min_size), else two lines split at a full-width space."""
    for sz in range(size, min_size - 1, -2):
        if measure(d, s, sz, weight) <= max_w:
            return [s], sz
    parts = s.split("　")
    if len(parts) > 1:
        best = min(range(1, len(parts)), key=lambda k: abs(len("　".join(parts[:k])) - len("　".join(parts[k:]))))
        return ["　".join(parts[:best]), "　".join(parts[best:])], size
    return [s], min_size


def layer_sub(d, zh, en):
    zl, zs = fit_lines(d, zh, 52, "Bold", 980, 44)
    y = 1350
    for line in zl:
        for dx, dy in ((0, 3), (2, 2)):
            draw_mixed(d, W / 2 + dx, y + dy, line, zs, "Bold", (0, 0, 0, 180), anchor="ma")
        draw_mixed(d, W / 2, y, line, zs, "Bold", SUB_ZH + (255,), anchor="ma")
        y += int(zs * 1.32)
    if en:
        el, es = fit_lines(d, en, 32, "SemiBold", 1000, 26)
        if len(el) == 1 and measure(d, en, es, "SemiBold") > 1000:
            words = en.split()
            el = [" ".join(words[: len(words) // 2]), " ".join(words[len(words) // 2:])]
        y += 6
        for line in el:
            draw_mixed(d, W / 2, y, line, es, "SemiBold", WHITE + (255,), anchor="ma")
            y += int(es * 1.3)


def boxed_line(d, x, y, text, size):
    """Reference cover style: dark box, white text, a white L-bracket offset to the bottom-right."""
    f = font(size, "Black")
    parts = text.split("|")
    tw = sum(d.textlength(p, font=f) for p in parts)
    pad_x, box_h = 22, int(size * 1.45)
    x1, y1 = x + tw + 2 * pad_x, y + box_h
    d.rectangle([x, y, x1, y1], fill=(10, 10, 10, 225))
    d.line([x1 + 7, y + 10, x1 + 7, y1 + 7, x + 10, y1 + 7], fill=WHITE + (255,), width=3)
    cx = x + pad_x
    for k, p in enumerate(parts):
        d.text((cx, y + (box_h - size) / 2 - size * 0.12), p, font=f, fill=(RED if k else WHITE) + (255,))
        cx += d.textlength(p, font=f)
    return y1


def logo_tile(size):
    im = Image.open(LOGO).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    return im


def layer_cover(img, lines):
    d = ImageDraw.Draw(img)
    img.alpha_composite(logo_tile(96), (60, 262))
    d.line([60 + 96 + 6, 262 + 10, 60 + 96 + 6, 262 + 96 + 6, 60 + 10, 262 + 96 + 6], fill=WHITE + (255,), width=3)
    y = boxed_line(d, 180, 300, lines[0], 72)
    boxed_line(d, 40, y + 22, lines[1], 72)


def outro_frame():
    """Brand end card: dark teal gradient, logo, name, follow line, tagline."""
    img = Image.new("RGB", (W, H), BG)
    px = img.load()
    for yy in range(H):
        t = max(0.0, (yy - 600) / (H - 600))
        c = tuple(int(BG[i] + (TEAL_DARK[i] - BG[i]) * t) for i in range(3))
        for xx in range(0, W):
            px[xx, yy] = c
    img = img.convert("RGBA")
    # faint dot grid (reference uses a dotted world map; a neutral grid stays on-brand)
    d = ImageDraw.Draw(img)
    for yy in range(80, 900, 26):
        for xx in range(20, W, 26):
            if (xx * 7 + yy * 13) % 5:
                d.ellipse([xx, yy, xx + 3, yy + 3], fill=(60, 70, 72, 255))
    img.alpha_composite(logo_tile(150), (90, 1000))
    d.text((90, 1175), BRAND, font=font(96, "Black"), fill=WHITE + (255,))
    d.text((94, 1310), "追蹤｜按讚｜分享", font=font(44, "Medium"), fill=(230, 230, 230, 255))
    d.text((94, 1390), TAGLINE, font=font(32, "Regular"), fill=MINT + (255,))
    return img


# ---------- video ----------

_VIGNETTE = None


def vignette(tmp):
    """Static overlay that turns the band's lower edge and everything below it into black."""
    global _VIGNETTE
    if _VIGNETTE:
        return _VIGNETTE
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = img.load()
    for yy in range(H):
        if yy < BAND_Y:
            a = 170
        elif yy < BAND_Y + 90:
            a = int(170 * (1 - (yy - BAND_Y) / 90))
        elif yy < BAND_Y + BAND_H - FADE_H:
            a = 0
        elif yy < BAND_Y + BAND_H:
            t = (yy - (BAND_Y + BAND_H - FADE_H)) / FADE_H
            a = int(255 * min(1.0, t ** 0.7))
        else:
            a = 255
        for xx in range(W):
            px[xx, yy] = (5, 5, 5, a)
    _VIGNETTE = tmp / "vignette.png"
    img.save(_VIGNETTE)
    return _VIGNETTE


# Cinematic look for quoted footage: gentle contrast, a little less saturation, cool shadows / warm
# highlights; then a soft vignette and fine moving grain over the composited frame
GRADE = ("eq=contrast=1.07:saturation=0.86:gamma=0.97,"
         "colorbalance=rs=-0.02:bs=0.03:rh=0.03:gh=0.01:bh=-0.03")
FINISH = "vignette=angle=PI/5,noise=alls=5:allf=t+u"
NEWS = ("cnn", "cbs", "cnbc", "nbc", "bbc")       # sources with a burned-in ticker along the bottom
TICKER = 0.27                                     # bottom share of news frames: headline bar + ticker
_FACE = None


def auto_frame(src, start, dur, trim_bottom, zoom):
    """Find faces in a few frames; return (fx, fit). fit=True when the people don't fit the band crop."""
    import cv2
    import numpy as np
    global _FACE
    if _FACE is None:
        _FACE = (cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"),
                 cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml"))
    faces = []
    for k in range(3):
        t = start + dur * (0.15 + 0.35 * k)
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=640:360,format=gray", "-f", "rawvideo", "-"], capture_output=True)
        if len(r.stdout) != 640 * 360:
            continue
        img = np.frombuffer(r.stdout, np.uint8).reshape(360, 640)[: int(360 * (1 - trim_bottom))]
        for casc in _FACE:
            faces += [(x, w) for (x, _, w, _) in casc.detectMultiScale(img, 1.1, 6, minSize=(22, 22))]
    src_aspect = (16 / 9) / (1 - trim_bottom)
    cw = (W / BAND_H) / src_aspect / zoom          # visible fraction of the source width
    if not faces:
        return 0.5, False
    # main subjects only: background faces far smaller than the largest one don't drive the crop
    big = max(w for _, w in faces)
    main = [(x + w / 2) / 640 for x, w in faces if w >= 0.45 * big]
    lo, hi = min(main), max(main)
    # several people who can't share the crop (with a head-width of room each side) -> show the whole frame;
    # a single person is simply centered
    if hi - lo + 2.2 * big / 640 > cw and hi - lo > 0.08:
        return 0.5, True
    c = (lo + hi) / 2
    left = min(max(c - cw / 2, 0.0), 1.0 - cw)
    return (left / (1.0 - cw) if cw < 1 else 0.5), False


def shot_cmd(src, start, dur, mode, out, tmp, keep_audio=False, zoom=1.0, fx=0.5, fy=0.5,
             trim_bottom=0.0, fit=False, push=0.0, grade=True):
    src = (EDIT / src).resolve() if not Path(src).is_absolute() else Path(src)
    still = src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    inp = (["-loop", "1", "-t", f"{dur:.3f}", "-i", str(src)] if still
           else ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)])
    g = f",{GRADE}" if grade else ""
    tail = f"fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration={dur:.3f}"
    if mode == "anim":
        vf = f"[0:v]scale={W}:{H},{tail}[v]"
        inputs = inp
    elif mode == "full":
        vf = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}{g},{FINISH},{tail}[v]"
        inputs = inp
    else:
        trim = f"crop=iw:ih*{1 - trim_bottom:.3f}:0:0," if trim_bottom else ""
        if fit:
            # the whole frame stays visible, centered in the band, blurred fill around it
            fg = f"[b]{trim}scale={W}:-2,setsar=1{g}[fg];"
            place = f"overlay=0:{BAND_Y}+({BAND_H}-h)/2"
        else:
            pz = (f",scale=w='trunc({W}*(1+{push}*t/{dur:.3f})/2)*2':h=-2:eval=frame,crop={W}:{BAND_H}"
                  if push else "")
            fg = (f"[b]{trim}scale={int(W * zoom)}:{int(BAND_H * zoom)}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{BAND_H}:(iw-{W})*{fx:.3f}:(ih-{BAND_H})*{fy:.3f}{pz},setsar=1{g}[fg];")
            place = f"overlay=0:{BAND_Y}"
        vf = (f"[0:v]split[a][b];"
              f"[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
              f"boxblur=10:2,eq=brightness=-0.28:saturation=0.8,scale={W}:{H}[bg];"
              f"{fg}[bg][fg]{place}[c];[c][1:v]overlay=0:0,{FINISH},{tail}[v]")
        inputs = inp + ["-i", str(vignette(tmp))]
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", vf, "-map", "[v]"]
    if keep_audio:
        cmd += ["-map", "0:a", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
            "-r", str(FPS), str(out)]
    return cmd


# ---------- timeline ----------

SOT_PRE, SOT_POST = 0.35, 0.5     # picture and room sound around a quote, so it doesn't snap in or out
VO_HOLD = 0.6                      # air after the last narration line of a block
X_IN, X_BLOCK = 0.3, 0.45          # dissolve inside a block / between blocks


def build_timeline(plan, prosody):
    """Returns shots [(t0, dur, shot, dissolve_in)], overlay events, audio pieces, total length."""
    secs = prosody
    shots, events, audio, t = [], [], [], 0.0
    cover_end = plan.get("cover", {}).get("dur", 0)
    for bi, blk in enumerate(plan["blocks"]):
        xb = X_BLOCK if bi else 0.0
        if "vo" in blk:
            sec = secs[blk["vo"]]
            lines = sec["lines"]
            a = lines[0]["t0"] - 0.12
            b = lines[-1]["t1"] + max(VO_HOLD, min(lines[-1]["pause"], 0.9))
            dur = b - a
            audio.append(("vo", a, b, t))
            for ln in lines:
                events.append(("sub", t + ln["t0"] - a, t + ln["t1"] - a + 0.12, (ln["show"], ln["en"])))
            # cut in the middle of the pause before the line, not on its first word
            starts = [0.0 if not sh.get("line") else
                      (lines[sh["line"] - 1]["t1"] + lines[sh["line"]]["t0"]) / 2 - a for sh in blk["shots"]]
            starts[0] = 0.0
            ends = starts[1:] + [dur]
            for k, (sh, s0, s1) in enumerate(zip(blk["shots"], starts, ends)):
                shots.append((t + s0, s1 - s0, sh, xb if k == 0 else X_IN))
                if sh.get("info"):
                    events.append(("info", t + s0 + 0.2, t + s1, sh["info"]))
                if sh.get("credit"):
                    events.append(("credit", t + s0 + 0.2, t + s1, sh["credit"]))
            t += dur
        elif "signoff" in blk:
            so = blk["signoff"]
            sd = probe_dur(EDIT / so["audio"])
            dur = sd + VO_HOLD
            audio.append(("file", so["audio"], t + 0.05))
            events.append(("sub", t + 0.05, t + sd + 0.1, (so["show"], so.get("en", ""))))
            starts = [0.0]
            for sh in blk["shots"][1:]:
                starts.append(sh.get("at", 0.0))
            ends = starts[1:] + [dur]
            for k, (sh, s0, s1) in enumerate(zip(blk["shots"], starts, ends)):
                shots.append((t + s0, s1 - s0, sh, xb if k == 0 else X_IN))
                if sh.get("credit"):
                    events.append(("credit", t + s0 + 0.2, t + s1, sh["credit"]))
            t += dur
        else:
            s = blk["sot"]
            dur = s["out"] - s["in"] + SOT_PRE + SOT_POST
            sh = {k: s[k] for k in ("src", "mode", "zoom", "fx", "fy", "fit", "trim_bottom") if k in s}
            sh.update({"in": s["in"] - SOT_PRE, "sot": True})
            shots.append((t, dur, sh, xb))
            audio.append(("sot", s["src"], s["in"] - SOT_PRE, s["out"] + SOT_POST, t))
            events.append(("sot", t + 0.2, t + dur - 0.15, (s.get("tag", "原聲"), s["who"], s.get("source", ""))))
            for a0, a1, zh, en in s["subs"]:
                events.append(("sub", t + SOT_PRE + a0, t + SOT_PRE + a1, (zh, en)))
            t += dur
    # trim subtitle overlaps (each sub ends where the next begins)
    subs = sorted([e for e in events if e[0] == "sub"], key=lambda e: e[1])
    others = [e for e in events if e[0] != "sub"]
    fixed = []
    for e, nxt in zip(subs, subs[1:] + [None]):
        end = min(e[2], nxt[1]) if nxt else e[2]
        fixed.append(("sub", e[1], end, e[3]))
    events = others + fixed
    if cover_end and plan["cover"].get("image"):
        events.append(("coverimg", 0.0, cover_end, plan["cover"]["image"]))
    elif cover_end:
        events.append(("cover", 0.0, cover_end, plan["cover"]["lines"]))
    events.append(("title", cover_end, t, plan["title"]))
    return shots, events, audio, t


def render_state(active):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for kind, payload in active:
        if kind == "title":
            layer_title(d, payload)
        elif kind == "info":
            backing(img, 1060, 1200 if len(payload.get("lines", [])) < 2 else 1250)
            layer_info(d, payload)
        elif kind == "sot":
            backing(img, 1240, 1320)
            layer_sot_card(d, *payload)
        elif kind == "credit":
            layer_credit(d, payload)
        elif kind == "sub":
            layer_sub(d, *payload)
        elif kind == "coverimg":
            img.alpha_composite(Image.open(EDIT / payload).convert("RGBA").resize((W, H)))
        elif kind == "cover":
            layer_cover(img, payload)
    return img


ORDER = {"coverimg": 0, "cover": 0, "title": 1, "info": 2, "sot": 3, "credit": 4, "sub": 5}


def overlay_track(events, total, tmp):
    """Render one RGBA PNG per distinct overlay state and stitch them with the concat demuxer."""
    fr = lambda x: round(x * FPS) / FPS   # cut only on frame boundaries; sub-frame states broke the stream
    cuts = sorted({0.0, fr(total)} | {fr(e[1]) for e in events} | {fr(min(e[2], total)) for e in events})
    cuts = [c for c in cuts if 0 <= c <= total]
    lines, cache, f = [], {}, None
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.5 / FPS:
            continue
        mid = (a + b) / 2
        active = sorted([(e[0], e[3]) for e in events if e[1] <= mid < e[2]], key=lambda x: ORDER[x[0]])
        if any(k in ("cover", "coverimg") for k, _ in active):
            active = [x for x in active if x[0] in ("cover", "coverimg")]   # reference cover carries no other text
        key = hashlib.md5(json.dumps(active, ensure_ascii=False).encode()).hexdigest()[:12]
        f = tmp / f"ov_{key}.png"
        if key not in cache:
            render_state(active).save(f)
            cache[key] = f
        lines.append(f"file '{f.as_posix()}'\nduration {b - a:.3f}\n")
    lines.append(f"file '{f.as_posix()}'\n")
    lst = tmp / "overlay.txt"
    lst.write_text("".join(lines), encoding="utf-8")
    out = tmp / "overlay.mov"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS},format=argb",
         "-c:v", "qtrle", str(out)])
    return out, len(cache)


def lufs(path, start=None, dur=None):
    cmd = ["ffmpeg", "-hide_banner"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}"]
    r = subprocess.run(cmd + ["-i", str(path), "-af", "ebur128", "-f", "null", "-"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace").stderr
    import re
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
    return float(m[-1]) if m else -23.0


def static_outro(body, outro, tmp):
    """Static brand card with a red wipe, concatenated after the body."""
    op = tmp / "outro.png"
    outro_frame().convert("RGB").save(op)
    of = tmp / "outro.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", f"{outro:.3f}", "-i", str(op),
         "-f", "lavfi", "-t", f"{outro:.3f}", "-i", f"color=c=0x{RED[0]:02X}{RED[1]:02X}{RED[2]:02X}:s={W}x{H}:r={FPS}",
         "-filter_complex", "[0:v]fps=30,format=yuv420p[b];[b][1:v]overlay=x='if(lt(t,0.22),-W+W*t/0.22,W*(t-0.22)/0.25)':y=0[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), str(of)])
    lst = tmp / "concat.txt"
    lst.write_text(f"file '{body.as_posix()}'\nfile '{of.as_posix()}'\n", encoding="utf-8")
    base = tmp / "base.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(base)])
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--out", default="short_preview.mp4")
    ap.add_argument("--samples", action="store_true", help="write one PNG per overlay type and stop")
    args = ap.parse_args()
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    prosody = json.loads((EDIT / plan["plan"]).read_text(encoding="utf-8"))
    shots, events, audio, total = build_timeline(plan, prosody)
    outro = plan.get("outro", {}).get("dur", 3.2)
    outro_video = plan.get("outro", {}).get("video")
    if outro_video:
        # animated brand outro (Remotion) dissolves in as the last shot of the chain
        outro = probe_dur(EDIT / outro_video)
        shots.append((total, outro, {"src": outro_video, "in": 0.0, "mode": "anim"}, X_BLOCK))
    print(f"body {total:.2f}s + outro {outro:.1f}s, {len(shots)} shots, {len(events)} overlay events")

    tmp = Path(tempfile.mkdtemp(prefix="short_", dir=EDIT / "verify"))
    if args.samples:
        for kind in ORDER:
            ev = next((e for e in events if e[0] == kind), None)
            if ev:
                active = [("title", plan["title"])] if kind not in ("title", "cover") else []
                render_state(active + [(kind, ev[3])]).save(EDIT / "verify" / f"sample_{kind}.png")
        print("samples in verify/")
        return

    # 1. shots, each with a tail handle that the next shot dissolves over
    seg_files = []
    for k, (t0, dur, s, _) in enumerate(shots):
        f = tmp / f"s{k:03d}.mp4"
        handle = shots[k + 1][3] if k + 1 < len(shots) else 0.0
        # the boxed-text cover sits on a full-bleed shot; an image cover hides the shot, so keep the band layout
        text_cover = "lines" in plan.get("cover", {})
        mode = "full" if (text_cover and t0 < plan["cover"]["dur"] - 0.01) else s.get("mode", "band")
        src = EDIT / s["src"]
        start = s.get("in", 0.0)
        if mode == "anim" and "in" not in s:
            start = max(0.0, probe_dur(src) - dur - handle - 0.1)   # land on the finished frame
        news = any(n in Path(s["src"]).name.lower() for n in NEWS)
        tb = s.get("trim_bottom", TICKER if news else 0.0)
        zoom = s.get("zoom", 1.0)
        fx, fit = s.get("fx"), s.get("fit", False if "fx" in s else None)
        if mode == "band" and (fx is None or fit is None):
            afx, afit = auto_frame(src.resolve(), start, dur, tb, zoom)
            fx = afx if fx is None else fx
            fit = afit if fit is None else fit
        fx = 0.5 if fx is None else fx
        push = 0.0 if s.get("sot") or mode != "band" else s.get("push", 0.04)
        run(shot_cmd(s["src"], start, dur + handle, mode, f, tmp, zoom=zoom, fx=fx, fy=s.get("fy", 0.4),
                     trim_bottom=tb, fit=bool(fit), push=push, grade=mode != "anim"))
        seg_files.append(f)
        print(f"  shot {k:2d} {t0:6.2f}s {dur:5.2f}s {mode:4} fx={fx:.2f} fit={bool(fit)} {Path(s['src']).name}@{start:.1f}")
    # one dissolve chain over all shots; each xfade starts where the next shot is due
    body = tmp / "body.mp4"
    ins, graph, last = [], [], "[0:v]"
    for f in seg_files:
        ins += ["-i", str(f)]
    for k in range(1, len(seg_files)):
        t0, _, _, xin = shots[k]
        lab = f"[x{k}]"
        if xin > 0:
            graph.append(f"{last}[{k}:v]xfade=transition=fade:duration={xin:.3f}:offset={t0:.3f}{lab}")
        else:
            graph.append(f"{last}[{k}:v]concat=n=2:v=1:a=0{lab}")
        last = lab
    run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(graph), "-map", last,
         "-t", f"{total + (outro if outro_video else 0):.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
         "-r", str(FPS), str(body)])
    # 2. outro: already in the chain when it's a video, else the static card with a red wipe
    base = body if outro_video else static_outro(body, outro, tmp)

    # 3. overlays
    ov, n_states = overlay_track(events, total, tmp)
    print(f"{n_states} overlay states")

    # 4. audio: narration slices + SOT audio (levelled to the narration) + music bed
    narr = EDIT / plan["narration"]
    if narr.with_suffix(".wav").is_file():
        narr = narr.with_suffix(".wav")   # lossless master from prosody.py
    inputs, chains, labels = [], [], []
    narr_lufs = lufs(narr)
    for k, a in enumerate(audio):
        if a[0] == "vo":
            _, s0, s1, at = a
            inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", str(narr)]
            gain = 0.0
            d = s1 - s0
        elif a[0] == "file":
            _, fpath, at = a
            fp = EDIT / fpath
            inputs += ["-i", str(fp)]
            gain = narr_lufs - lufs(fp)
            d = probe_dur(fp)
        else:
            _, src, s0, s1, at = a
            srcp = (EDIT / src).resolve()
            inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", str(srcp)]
            gain = narr_lufs - lufs(srcp, s0, s1 - s0) - 1.0
            d = s1 - s0
        i = len(labels)
        fin = 0.25 if a[0] == "sot" else 0.03   # quotes ease in and out over their pre/post roll
        chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain:.2f}dB,"
                      f"afade=t=in:d={fin},afade=t=out:st={d - fin:.3f}:d={fin},adelay={int(at * 1000)}:all=1[a{i}]")
        labels.append(f"[a{i}]")
    full = total + outro
    mix_in = "".join(labels)
    n = len(labels)
    if plan.get("music"):
        mp = (EDIT / plan["music"]).resolve()
        inputs += ["-stream_loop", "-1", "-i", str(mp)]
        i = n
        # bed ~20 dB under the voice, rising to ~-8 dB under it over the last 25 s, full at the outro
        lift = f"if(lt(t,{total - 25:.2f}),0.1,if(lt(t,{total:.2f}),0.1+0.3*(t-{total - 25:.2f})/25,0.9))"
        chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{full:.3f},"
                      f"volume='{lift}':eval=frame,volume={narr_lufs - lufs(mp) - 0:.2f}dB,"
                      f"afade=t=out:st={full - 1.2:.3f}:d=1.2[m]")
        mix_in += "[m]"
        n += 1
    # one static gain to -16 LUFS + a peak limiter (a riding loudnorm pumped the voice under the music)
    pre = tmp / "premix.wav"
    mix = f"{mix_in}amix=inputs={n}:normalize=0:duration=longest,atrim=0:{full:.3f}[aout]"
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains + [mix]), "-map", "[aout]",
         "-ar", "48000", "-c:a", "pcm_s24le", str(pre)])
    aud = tmp / "mix.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(pre), "-af",
         f"volume={-16.0 - lufs(pre):.2f}dB,alimiter=limit=0.87:attack=3:release=60:level=false",
         "-c:a", "pcm_s24le", str(aud)])

    # 5. final
    out = EDIT / args.out
    final = tmp / "final.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(base), "-i", str(ov), "-i", str(aud), "-filter_complex",
         "[0:v][1:v]overlay=0:0:eof_action=pass[v]", "-map", "[v]", "-map", "2:a", "-c:v", "libx264",
         "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
         "-movflags", "+faststart", "-t", f"{full:.3f}", str(final)])
    # the previous cut is often still open in a player: never fail on that, pick the next free name
    k = 1
    while True:
        try:
            final.replace(out)
            break
        except PermissionError:
            k += 1
            out = EDIT / f"{Path(args.out).stem}_{k}{Path(args.out).suffix}"
    print(f"-> {out} ({full:.1f}s); temp {tmp}")


if __name__ == "__main__":
    main()
