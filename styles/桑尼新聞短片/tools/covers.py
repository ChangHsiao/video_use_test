"""Three cover options (1080x1920) for the short, one per title system in design/封面與標題系統.md.

Usage: python covers.py  -> edit/design/cover_A.png, cover_B.png, cover_C.png, covers_compare.png
Text stays inside the Shorts safe zone: y 300..1500, x 80..940 (right rail of buttons kept clear).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from short import BG, MINT, RED, TEAL_DARK, W, H, font, logo_tile

EDIT = Path(__file__).resolve().parent.parent
OUT = EDIT / "design"
STAGE = OUT / "still_c.png"      # NVIDIA GTC keynote frame (NVIDIA's own footage)
CHIP = OUT / "still_b.png"       # holding a chip at GTC
TEAL = (44, 145, 140)


def grade(im, sat=0.55, bright=0.9):
    im = ImageEnhance.Color(im).enhance(sat)
    im = ImageEnhance.Brightness(im).enhance(bright)
    # cool shadows: blend toward dark teal in the low end
    tint = Image.new("RGB", im.size, TEAL_DARK)
    return Image.blend(im, tint, 0.18)


def portrait(src, cx, cy_top=0.0, zoom=1.0):
    """Vertical crop around x=cx (0..1) of a 16:9 frame, scaled to 1080x1920."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    ch = int(h / zoom)
    cw = int(ch * W / H)
    x0 = int(min(max(cx * w - cw / 2, 0), w - cw))
    y0 = int(cy_top * (h - ch))
    return im.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.Resampling.LANCZOS)


def vgrad(img, y0, y1, a0, a1, color=BG):
    """Vertical gradient of `color` from alpha a0 at y0 to a1 at y1."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(y0, y1):
        t = (y - y0) / max(1, y1 - y0)
        d.line([(0, y), (W, y)], fill=color + (int(a0 + (a1 - a0) * t),))
    img.alpha_composite(layer)


def text(d, xy, s, size, weight="Black", fill=(255, 255, 255), stroke=0, anchor="la"):
    d.text(xy, s, font=font(size, weight), fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0), anchor=anchor)


def brand_corner(img, x=80, y=300, size=64):
    img.alpha_composite(logo_tile(size), (x, y))
    d = ImageDraw.Draw(img)
    text(d, (x + size + 18, y + size / 2), "桑尼資料科學", 30, "Bold", anchor="lm")


def series_pill(d, x, y, label):
    f = font(30, "Bold")
    w = d.textlength(label, font=f)
    d.rounded_rectangle([x, y, x + w + 44, y + 56], radius=28, fill=TEAL + (255,))
    d.text((x + 22, y + 9), label, font=f, fill=(255, 255, 255))


def cover_a():
    """A 人物＋關鍵詞: news photo of the subject, two short lines, one mint keyword."""
    img = grade(portrait(STAGE, 0.67, 0.0, 1.15)).convert("RGBA")
    vgrad(img, 0, 700, 235, 40)
    vgrad(img, 1250, H, 0, 250)
    d = ImageDraw.Draw(img)
    brand_corner(img)
    text(d, (80, 430), "黃仁勳下台", 150, stroke=2)
    text(d, (80, 610), "私事變", 120, stroke=2)
    x = 80 + d.textlength("私事變", font=font(120, "Black"))
    text(d, (x, 610), "國安疑雲", 120, fill=MINT, stroke=2)
    d.rectangle([80, 780, 240, 790], fill=RED + (255,))
    series_pill(d, 80, 1420, "科技大事拆解｜EP.01")
    return img


def cover_b():
    """B 數據卡: one big number with a one-line meaning, a falling line behind it, small photo as support."""
    img = Image.new("RGBA", (W, H), BG + (255,))
    vgrad(img, 700, H, 0, 255, TEAL_DARK)
    d = ImageDraw.Draw(img)
    # schematic falling line (decorative, not data)
    pts = [(60, 820), (220, 790), (360, 860), (520, 900), (650, 1010), (800, 1060), (1020, 1180)]
    d.line(pts, fill=RED + (200,), width=8, joint="curve")
    d.ellipse([1004, 1164, 1036, 1196], fill=RED + (255,))
    brand_corner(img)
    text(d, (80, 470), "2", 420, fill=MINT)
    x = 80 + d.textlength("2", font=font(420, "Black")) + 20
    text(d, (x, 690), "週", 170)
    text(d, (84, 940), "從第一篇報導到下台", 58, "Bold", fill=(230, 230, 230))
    text(d, (84, 1030), "黃仁勳的國安疑雲", 74, "Black")
    # supporting photo, circular, low in the frame
    ph = grade(portrait(CHIP, 0.47, 0.0, 1.0), sat=0.6).resize((340, 604)).crop((0, 120, 340, 460))
    mask = Image.new("L", (340, 340), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 339, 339], fill=255)
    ring = Image.new("RGBA", (356, 356), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([0, 0, 355, 355], outline=MINT + (255,), width=6)
    img.paste(ph, (540, 1140), mask)
    img.alpha_composite(ring, (532, 1132))
    series_pill(d, 80, 1420, "科技大事拆解｜EP.01")
    return img


def cover_c():
    """C 系列問題卡: fixed brand surface, faint photo underlay, three short lines, series bar on top."""
    under = grade(portrait(CHIP, 0.47, 0.0, 1.0), sat=0.3, bright=0.6).filter(ImageFilter.GaussianBlur(2))
    img = Image.blend(Image.new("RGB", (W, H), TEAL_DARK), under, 0.38).convert("RGBA")
    vgrad(img, 0, H, 60, 200)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 300, W, 380], fill=TEAL + (255,))
    text(d, (80, 340), "科技大事 2 分鐘", 40, "Black", anchor="lm")
    text(d, (940, 340), "EP.01", 40, "Black", anchor="rm")
    for k, (s, color) in enumerate((("一段私事", (255, 255, 255)), ("怎麼變成", (255, 255, 255)), ("國安疑雲", MINT))):
        text(d, (80, 560 + k * 175), s, 150, fill=color)
    d.rectangle([80, 1110, 300, 1122], fill=RED + (255,))
    text(d, (84, 1160), "黃仁勳下台始末", 56, "Bold", fill=(225, 225, 225))
    img.alpha_composite(logo_tile(72), (80, 1380))
    text(d, (172, 1416), "桑尼資料科學", 36, "Bold", anchor="lm")
    return img


def main():
    covers = {"A": cover_a(), "B": cover_b(), "C": cover_c()}
    for k, im in covers.items():
        im.convert("RGB").save(OUT / f"cover_{k}.png")
    # side by side, with the Shorts UI zones shaded so the safe area is visible
    sheet = Image.new("RGB", (3 * 540 + 40, 960 + 60), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, (k, im) in enumerate(covers.items()):
        th = im.convert("RGB").resize((540, 960))
        ov = Image.new("RGBA", (540, 960), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.rectangle([0, 0, 540, 150], fill=(255, 0, 0, 40))
        od.rectangle([0, 750, 540, 960], fill=(255, 0, 0, 40))
        od.rectangle([470, 150, 540, 750], fill=(255, 0, 0, 40))
        th = Image.alpha_composite(th.convert("RGBA"), ov).convert("RGB")
        sheet.paste(th, (10 + i * 550, 50))
        d.text((10 + i * 550, 10), f"封面 {k}", font=font(30, "Bold"), fill=(255, 255, 255))
    sheet.save(OUT / "covers_compare.png")
    print("covers ->", OUT)


if __name__ == "__main__":
    main()
