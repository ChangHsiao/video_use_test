"""OutroExplainer: the end card of the「經典乾貨拆解」series (3b1b-style explainers), 9:16, pure black.

What it shows (one thing at a time, then holds; no fade-out):
    a. the sun mascot hops in from the lower left to the top centre, looks down, lands with a squash
    b. it points down at the brand logo mark, which draws its outline and then fills
    c. the brand name writes in; under it the Latin name in mint with its letter spacing widening
    d. the series slogan writes in; the mascot turns happy
    e. three thin mint pills 追蹤 / 按讚 / 分享 appear one by one while the mascot glances at each
    f. everything holds still to the end (at least HOLD_MIN seconds)

Every text, colour and the logo come from brands/<brand>/brand.json through helpers/registry.py:
    name                     brand name (big white line)
    name_en                  Latin name, set in capitals
    colors.mint              Latin name, icons and pill outlines
    logo.mark                logo SVG (its background tile rect is dropped; the mark keeps its own colours)
    series.explainer.slogan  slogan line;  series.explainer.outro  where the finished video goes
    mascot                   the sun mascot (templates/manim/sun_mascot.py)
To change wording, edit brand.json; nothing brand-specific is written in this file.

Length: OUTRO_SECONDS (default 5.0, valid 4.0-6.5). The beat sheet is laid out for 5 s and scales with
the length, but always leaves a static hold of >= HOLD_MIN seconds at the end (the ~4.5 s spoken
sign-off plays over it). Brand: --brand (required; passed to the Manim process as OUTRO_BRAND).

Render (writes brands/<brand>/<series.explainer.outro>, H.264 yuv420p crf 16, 1080x1920, 30 fps):
    py -3.11 templates/manim/outro_explainer.py --brand 桑尼資料科學                 # 5.0 s
    OUTRO_SECONDS=6 py -3.11 templates/manim/outro_explainer.py --brand 桑尼資料科學 --out D:/somewhere/Outro.mp4
    (PowerShell: $env:OUTRO_SECONDS = '6'; py -3.11 templates/manim/outro_explainer.py --brand ... --out ...)
This runs `manim render --disable_caching --media_dir D:/manim_media/outro --video-codec libx264
--pixel-format yuv420p --encoder-option crf=16 --encoder-option preset=slow templates/manim/outro_explainer.py
OutroExplainer` (one lossy encode; the --video-codec/--encoder-option flags need Manim CE >= 0.22) and
stream-copies the result to the output path.
Do not add saturation to this file at compose time: the colours are the brand's, not 3b1b's.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from manim import (DOWN, LEFT, ORIGIN, PI, RIGHT, UP, Animation, AnimationGroup, Arc, Circle, Create,
                   DrawBorderThenFill, FadeIn, Line, Mobject, MoveAlongPath, Polygon, Rectangle,
                   RoundedRectangle, Scene, SVGMobject, Succession, Text, UpdateFromAlphaFunc, VGroup,
                   VMobject, Write, config, smooth)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "helpers"))
import registry  # noqa: E402
from sun_mascot import SunMascot  # noqa: E402

BRAND = os.environ.get("OUTRO_BRAND", "")  # set by main() from --brand
SECONDS = float(os.environ.get("OUTRO_SECONDS", "5.0"))
# Windows keeps the original JhengHei; elsewhere use the CJK font every Linux/Mac box with Noto has
ZH_FONT = os.environ.get("OUTRO_ZH_FONT", "Microsoft JhengHei" if os.name == "nt" else "Noto Sans CJK TC")
HOLD_MIN = 1.25          # static seconds at the end (brief: >= 1.2)
FRAME_SLACK = 0.15       # each play() rounds up to whole frames: 4 plays can add up to ~0.13 s
BEATS_END = 4.06         # where the 5 s beat sheet's last motion ends (mascot back to happy)
MEDIA_DIR = os.environ.get("OUTRO_MEDIA_DIR", "D:/manim_media/outro" if os.name == "nt"
                           else str(Path(tempfile.gettempdir()) / "manim_media" / "outro"))

config.pixel_width, config.pixel_height, config.frame_rate = 1080, 1920, 30
config.frame_width = 8.0
config.frame_height = 8.0 * 16 / 9
config.background_color = "#000000"


def latin_font(brand):
    """Inter: the brand's own font file if it registers with Pango, else a system Inter, else JhengHei."""
    import manimpango
    for rel in brand.data.get("fonts", {}).get("en", []):
        p = brand.asset(rel)
        if p:
            manimpango.register_font(str(p))
    fams = [f for f in manimpango.list_fonts() if f.startswith("Inter")]
    return "Inter" if "Inter" in fams else (fams[0] if fams else ZH_FONT)


def later(delay, anim):
    return Succession(Animation(Mobject(), run_time=delay), anim) if delay > 1e-3 else anim


# ---------- icons (mint thin outlines, about 0.3 units) ----------

def icon_follow():
    head = Circle(radius=0.075).move_to([-0.03, 0.07, 0])
    body = Arc(radius=0.13, start_angle=0, angle=PI).move_to([-0.03, -0.08, 0])
    body.shift(DOWN * (body.get_bottom()[1] + 0.14))
    plus = VGroup(Line([0.12, 0.0, 0], [0.22, 0.0, 0]), Line([0.17, -0.05, 0], [0.17, 0.05, 0]))
    return VGroup(head, body, plus)


def icon_like():
    cuff = Rectangle(width=0.06, height=0.17).move_to([-0.135, -0.055, 0])
    hand = Polygon(*[np.array([x, y, 0]) for x, y in
                     [(-0.08, -0.14), (-0.08, 0.02), (-0.02, 0.07), (0.0, 0.16), (0.05, 0.16),
                      (0.05, 0.05), (0.14, 0.05), (0.12, -0.14)]]).round_corners(0.025)
    return VGroup(cuff, hand)


def icon_share():
    arc = Arc(radius=0.21, start_angle=PI, angle=-PI * 0.55).move_to([0.0, 0.0, 0])
    arc.shift(np.array([-0.02, -0.03, 0]) - arc.get_center())
    tip = arc.get_end()
    head = VGroup(Line(tip + np.array([-0.08, 0.06, 0]), tip), Line(tip + np.array([-0.07, -0.08, 0]), tip))
    return VGroup(arc, head)


def pill(icon, label, mint, w=1.8, h=0.6):
    box = RoundedRectangle(width=w, height=h, corner_radius=h / 2).set_stroke(mint, 2.5).set_fill(opacity=0)
    icon.set_stroke(mint, 2.5).set_fill(opacity=0)
    text = Text(label, font=ZH_FONT, font_size=26, color="#FFFFFF")
    VGroup(icon, text).arrange(RIGHT, buff=0.14).move_to(box)
    return VGroup(box, icon, text)


def hop_path(start, end, peak):
    """Quadratic Bezier with control point 'peak': one hop, no bounce."""
    t = np.linspace(0, 1, 40)[:, None]
    pts = (1 - t) ** 2 * start + 2 * t * (1 - t) * peak + t ** 2 * end
    return VMobject().set_points_smoothly(list(pts))


class OutroExplainer(Scene):
    def construct(self):
        if not BRAND:
            raise registry.ConfigError("沒有指定品牌：用 --brand（或環境變數 OUTRO_BRAND）")
        brand = registry.load_brand(BRAND)
        d = brand.data
        latin_name = d["name_en"].upper()
        series = d["series"]["explainer"]
        mint = brand.colors["mint"]
        T = SECONDS
        s = min(T / 5.0, (T - HOLD_MIN - FRAME_SLACK) / BEATS_END)  # beat sheet scale
        B = lambda t: t * s  # noqa: E731

        # ----- layout (all centred, x within +-3.6, y within about -2.8..3.4) -----
        sun_pos = np.array([0.0, 2.6, 0])
        sun = SunMascot(brand=BRAND, size=0.5)
        sun.move_to(np.array([-4.6, -2.4, 0]))

        logo = SVGMobject(str(brand.asset(d["logo"]["mark"])))
        logo.remove(logo.submobjects[0])  # the dark rounded tile: on pure black only the mark stays
        logo = VGroup(*logo.submobjects)
        for part in logo:
            part.set_stroke(part.get_fill_color(), 2)
        logo.set(height=1.15).move_to([0, 0.82, 0])

        name = Text(d["name"], font=ZH_FONT, weight="BOLD", font_size=44, color="#FFFFFF").move_to([0, -0.2, 0])

        lat_font = latin_font(brand)
        chars = [Text(c, font=lat_font, font_size=17, color=mint) for c in latin_name]
        latin = VGroup(*chars)
        space_w = 0.07
        lat_y = name.get_bottom()[1] - 0.38

        def lay_out(spacing):
            x = 0.0
            for c, ch in zip(latin_name, chars):
                if c == " ":
                    x += space_w + spacing
                    continue
                ch.move_to([x + ch.width / 2, 0, 0]).align_to([0, lat_y, 0], DOWN)
                x += ch.width + spacing
            latin.shift(LEFT * latin.get_center()[0])

        lay_out(0.0)
        latin.set_opacity(0)

        slogan = Text(series["slogan"], font=ZH_FONT, font_size=30, color="#FFFFFF").move_to([0, -1.45, 0])

        pills = VGroup(pill(icon_follow(), "追蹤", mint), pill(icon_like(), "按讚", mint),
                       pill(icon_share(), "分享", mint)).arrange(RIGHT, buff=0.3).move_to([0, -2.45, 0])
        # a long slogan never gets wider than the pill row (keeps it clear of the Shorts side buttons)
        slogan.scale(min(1.0, pills.width / slogan.width))

        # ----- a + b: hop in, look at the centre, land, point at the logo while it draws -----
        hop = MoveAlongPath(sun, hop_path(sun.get_center(), sun_pos, np.array([-1.6, 4.3, 0])),
                            run_time=B(0.4), rate_func=smooth)
        look_rt = B(0.25)
        t_point = max(B(0.4) + 0.47, B(0.95))  # squash length is fixed by the brand (squash_in + squash_out)
        mascot_ab = Succession(
            Animation(Mobject(), run_time=B(0.1)), sun.look("down", run_time=look_rt),
            Animation(Mobject(), run_time=max(B(0.4) - B(0.1) - look_rt, 0.0) + 1e-3), sun.squash(),
            Animation(Mobject(), run_time=max(t_point - B(0.4) - 0.47, 0.0) + 1e-3),
            sun.point("down", run_time=look_rt))
        self.add(sun)
        self.play(AnimationGroup(hop, mascot_ab, later(B(0.6), DrawBorderThenFill(logo, run_time=B(0.9))),
                                 Animation(Mobject(), run_time=B(1.6))))

        # ----- c: brand name, Latin name with widening letter spacing -----
        self.add(latin)

        def grow(mob, a):
            lay_out(0.015 + 0.075 * smooth(a))
            mob.set_opacity(min(1.0, a * 2.5))

        self.play(AnimationGroup(Write(name, run_time=B(0.6)),
                                 later(B(0.25), UpdateFromAlphaFunc(latin, grow, run_time=B(0.55)))))

        # ----- d: slogan, mascot happy -----
        self.play(AnimationGroup(Write(slogan, run_time=B(0.7)),
                                 later(B(0.3), sun.happy(run_time=B(0.25))),
                                 Animation(Mobject(), run_time=B(0.8))))

        # ----- e: pills one by one, mascot glances at each, ends happy -----
        glance = B(0.18)
        pill_anims = [later(B(0.2 * i), AnimationGroup(Create(p[0]), Create(p[1]),
                                                        FadeIn(p[2], shift=UP * 0.08), run_time=B(0.3)))
                      for i, p in enumerate(pills)]
        mascot_e = Succession(sun.look("down-left", run_time=glance), Animation(Mobject(), run_time=B(0.2) - glance),
                              sun.look("down", run_time=glance), Animation(Mobject(), run_time=B(0.2) - glance),
                              sun.look("down-right", run_time=glance),
                              Animation(Mobject(), run_time=B(0.1)),
                              sun.happy(run_time=glance))
        self.play(AnimationGroup(*pill_anims, mascot_e))

        # ----- f: hold, exactly to the requested length -----
        fps = config.frame_rate
        left = round(T * fps) - round(self.renderer.time * fps)  # whole frames, no float drift
        if left > 0:
            self.wait((left + 0.5) / fps)  # a static wait writes int(run_time * fps) frames



# ---------- render + encode ----------

def main():
    ap = argparse.ArgumentParser(description="Render OutroExplainer and encode it to the brand's series outro path")
    ap.add_argument("--brand", required=True, help="brands/<name>/")
    ap.add_argument("--out", help="output mp4 (default: brands/<brand>/<series.explainer.outro>)")
    args = ap.parse_args()
    os.environ["OUTRO_BRAND"] = args.brand  # the manim subprocess below reads it
    brand = registry.load_brand(args.brand)
    out = Path(args.out) if args.out else brand.root / brand.data["series"]["explainer"]["outro"]
    # one lossy encode only: Manim's own libx264 encoder at the delivery settings, then a stream copy
    subprocess.run([sys.executable, "-m", "manim", "render", "--disable_caching", "--media_dir", MEDIA_DIR,
                    "--video-codec", "libx264", "--pixel-format", "yuv420p",
                    "--encoder-option", "crf=16", "--encoder-option", "preset=slow",
                    str(Path(__file__)), "OutroExplainer"], check=True)
    videos = Path(MEDIA_DIR) / "videos" / Path(__file__).stem
    src = max(videos.rglob("OutroExplainer.mp4"), key=lambda p: p.stat().st_mtime)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c", "copy", "-an",
                    "-movflags", "+faststart", str(out)], check=True)
    print(out)


if __name__ == "__main__":
    main()
