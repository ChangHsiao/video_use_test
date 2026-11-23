"""Brand mascot engine: brand.json "mascot" spec + state + time (+ narration) -> shapes -> PIL frames.

The mascot (for 桑尼資料科學: an amber sun with 8 notches and two white dot eyes, plus a small dark
mouth that only shows while the narrator speaks) is defined entirely by the brand's brand.json
"mascot" block (colours, geometry, optional motion overrides). This module turns that spec into
filled polygons; every renderer (the PIL renderer here, compose.py's live mascot, helpers/mascot_track.py,
and the Manim component templates/manim/sun_mascot.py) draws the same polygons and uses the same
motion logic, so there is one geometry and motion source.

Layers:
    load_spec(brand) / spec_from_style(style)   read the spec through registry.py
    Pose                                        continuous parameters (body, eyes, notches, mouth, tilt)
    target_pose(spec, state, dir)               the held pose of a state (idle, look, surprised, ...)
    Timeline(spec, events, seed).pose_at(t)     expressions + transitions + blinks + breathing over time
    voice_features(voice, total, cache)         narration -> per-frame loudness, pitch, speaking gate
    MascotTimeline(spec, events, voice, fps,    Timeline + voice-driven motion + roaming in a lane:
                   home=, lane=).frame(t)       -> (RGBA image, centre x, centre y) at display size
    shapes(spec, pose)                          Pose -> [(name, Nx2 points in body units, rgb)]
    render_frame(spec, state, px, ...)          -> antialiased RGBA PIL image

Usage (from the repo):
    uv run python helpers/mascot.py --stickers [<dir>] [--brand 桑尼資料科學]   one PNG per state + sheet.png
    uv run python helpers/mascot.py --demo <out.mp4> [--px 1080]               ~10 s preview cycling all states
Stickers default to the brand's mascot.stickers folder. Usage rules: brands/<brand>/mascot/MASCOT.md.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# helpers/ is only on sys.path when this runs as a script; tests and templates load it by file path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

DEFAULT_BRAND = "桑尼資料科學"
FPS = 30

BASE_HELD = ("idle", "look", "surprised", "thinking", "happy", "point")
# emotions: held states like happy / thinking (the original states keep their names and looks)
EMOTIONS = ("joy", "sad", "angry", "worried", "confused", "proud", "love", "sleepy", "excited", "embarrassed")
HELD = BASE_HELD + EMOTIONS  # states that last for "hold" seconds
MOMENTARY = ("blink", "squash", "wave", "spin", "shiver", "jump")  # one-shot; they do not change the held state
STATES = BASE_HELD[:2] + ("blink",) + BASE_HELD[2:5] + ("squash", "point") + MOMENTARY[2:] + EMOTIONS
# emotes: flat symbols that pop up next to the head, then fade ("emote" on an event; some emotions bring one)
EMOTES = ("question", "exclaim", "interrobang", "sweat", "heart", "sparkle", "anger", "idea", "zzz", "dots",
          "check", "cross", "music")
EMOTION_EMOTE = {"worried": "sweat", "confused": "question", "proud": "sparkle", "sleepy": "zzz"}
CALM_EYES = ("happy", "surprised", "joy", "love", "excited", "sleepy")  # no auto blink over these eyes
FRAME = (1080, 1920)  # display coordinates of MascotTimeline positions and targets
BLINK_KINDS = ("single", "double", "slow", "squint")
MOVES = ("glide", "hop")

DIRS = {
    "right": (1, 0), "left": (-1, 0), "up": (0, 1), "down": (0, -1),
    "up-right": (1, 1), "up-left": (-1, 1), "down-right": (1, -1), "down-left": (-1, -1),
}

# Motion (how much and how fast each expression moves). Engine defaults for any mascot; a brand can
# override any key in brand.json mascot.motion (dict values such as "mouth" merge key by key).
# Lengths are in body units (body radius = 1) unless the key says px: px are 1080x1920 display pixels
# at the style's home size (they scale with the mascot's current display size).
MOTION = {
    "transition": 0.25,          # seconds between held states (ease in/out)
    "hold": 1.6,                 # default seconds an event's state is held before returning to idle
    "look": 0.07,                # eye shift toward dir
    "surprised_eye_h": 1.7,      # eye height factor
    "surprised_body": [0.97, 1.06],
    "thinking_eye": 1.45,        # eye size factor
    "thinking_look_up": 0.04,    # whole eye shifts up a little
    "pupil_r": 0.42,             # pupil radius / eye radius
    "squash": [1.12, 0.86],
    "squash_in": 0.12,
    "squash_out": 0.35,
    "point_reach": 2.6,          # pointing notch's outer end
    "point_thicken": 1.5,        # pointing notch's width factor
    "point_lean": 7.0,           # degrees the body leans toward the pointing direction (live timeline)
    "point_lean_px": 8.0,        # and the shift toward it
    "blink": [0.05, 0.06, 0.06],  # close, closed, open (seconds) of a single blink
    "blink_every": [2.5, 5.0],   # idle blink interval range (seeded)
    "blink_mix": {"single": 0.5, "double": 0.2, "slow": 0.15, "squint": 0.15},  # seeded blink variety
    "blink_double_gap": 0.22,    # seconds between the two blinks of a double blink
    "blink_slow": 2.4,           # a slow blink is a single blink stretched this much
    "squint": [0.55, 0.1, 0.4, 0.15],  # depth, close, hold, open (seconds)
    "breath_period": 3.4,
    "breath_amp": 0.012,         # idle breathing: y +-1.2 %, x -+0.6 %
    "loud_gain": 0.05,           # Timeline.pose_at(loud): body scale 1.00 .. 1.05 (fixed-track compatibility)
    "loud_smooth": 0.12,         # seconds
    "happy_arc_r": 1.25,         # happy arc radius / eye radius
    "happy_arc_span": 170,       # degrees
    "eye_line": 0.28,            # half thickness of a closed eye / happy arc, / eye radius
    # mouth: shown only while the narrator speaks; opens with loudness. shape: oval | d | round_rect
    "mouth": {"shape": "d", "w": 0.3, "h_open": 0.28, "h_closed": 0.045, "y": -0.33, "round": 0.5,
              "follow_look": 0.6},
    "mouth_attack": 0.05,        # loudness envelope for the mouth (seconds); release slower than attack, like real
    "mouth_release": 0.12,       # speech (0.03 / 0.05 snapped open/shut in one frame: up to 0.67 of full per frame)
    "mouth_slew": 6.0,           # the mouth opening changes at most this much per second (1 = fully open)
    "gate_attack": 0.08,         # the mouth fades in/out over these (seconds) instead of popping
    "gate_release": 0.15,
    "stretch_attack": 0.08,      # body stretch follows a slower envelope than the mouth (no per-frame jitter)
    "stretch_release": 0.25,
    "lift_attack": 0.18,         # pitch lift / tilt (pitch x speaking) eases in and out over these (seconds)
    "lift_release": 0.35,
    "mouth_range_db": 12.0,      # the mouth opens over the top 12 dB of the voice (fully open at its loud end)
    "mouth_curve": 2.0,          # > 1: syllable peaks open, softer sounds stay nearly closed
    "talk_gate": 0.12,           # voice level (0..1) above which the narrator counts as speaking
    "talk_hang": 0.18,           # gaps shorter than 2x this keep the mouth visible (closed) between words
    "talk_stretch": 0.04,        # body stretches up to 4 % taller with loudness
    "pitch_lift_px": 10.0,       # high pitch lifts the body
    "pitch_tilt": 4.0,           # and tilts it (degrees)
    "pitch_smooth": 0.12,
    "size_extent": 2.6,          # half of the display size (style mascot.size) covers this many body units
    "bob_px": 6.0,               # idle float
    "bob_period": 2.4,
    "sway": 3.0,                 # idle sway, degrees
    "sway_period": 3.9,
    "glide": 0.8,                # seconds of a glide move
    "glide_float_px": 8.0,       # glides rise this much at mid-way
    "glide_tilt": 5.0,           # and lean into the motion (degrees)
    "hop": 0.6,                  # seconds of a hop move (anticipation, flight, landing)
    "hop_height_px": 80.0,
    "hop_squash": [1.14, 0.84],  # anticipation / landing squash
    "hop_stretch": 1.1,          # stretch at take-off and touch-down
    "lane_rise_px": 60.0,        # hops and jumps never rise more than this above the lane's top
    "jump": 0.6,                 # surprised / jump: up and down in place
    "jump_height_px": 40.0,
    "spin": 0.7,                 # spin / happy: the notch ring turns
    "spin_deg": 90.0,
    "wave": 1.1,                 # wave: one notch extends and waggles
    "wave_deg": 24.0,
    "wave_reach": 0.6,           # extension 0..1 of the way to point_reach
    "wave_times": 3,
    "shiver": 0.35,              # shiver: fast small horizontal jitter
    "shiver_px": 6.0,
    "shiver_hz": 18.0,
    # emotions (held poses; see target_pose) and their live motion
    "joy_puff": 1.05,            # joy: body scale
    "joy_lift": 0.14,            # joy: notches tilt up (radians, negative droop) and move out
    "joy_out": 0.06,
    "sad_sink": 0.06,            # sad: body sinks (body units), notches droop and shorten
    "sad_droop": 0.28,
    "sad_short": -0.35,
    "lid_sad": [0.42, -0.38],    # lids: fraction of the eye cut from the top, tilt (radians; + = inner corner low)
    "lid_angry": [0.42, 0.45],
    "lid_worried": [0.12, -0.25],
    "lid_proud": [0.5, 0.0],
    "angry_long": 0.35,          # angry: notches longer and pointed
    "angry_tremble_px": 1.6,
    "angry_tremble_hz": 21.0,
    "worried_eye": 0.78,
    "worried_look": 0.06,        # worried: eyes look side to side
    "worried_look_hz": 0.8,
    "confused_eyes": 0.28,       # confused: right eye this much larger (left 60 % of it smaller)
    "confused_tilt": 10.0,       # degrees
    "proud_scale": 1.06,
    "sleepy_sink": 0.03,
    "excited_bounce_px": 10.0,   # excited: small bounces
    "excited_bounce_hz": 2.2,
    "embarrassed_look": [-0.03, -0.065],
    "shape_eye": 1.5,            # heart / star eyes: size / eye radius
    "blush": [0.47, -0.13, 0.13, 0.07],  # blush ovals: x, y, rx, ry (body units)
    # emotes
    "emote_at": [1.45, 1.5],     # emote centre relative to the body centre (body units; x mirrors near the edge)
    "emote_size": 0.8,           # emote glyph height (body units)
    "emote_pop": [0.13, 0.2],    # pop-in: scale 0 -> overshoot by the first time, -> 1 by the second
    "emote_overshoot": 1.1,
    "emote_hold": 1.2,           # default seconds a one-shot emote stays (then fades)
    "emote_fade": 0.25,
    "emote_bob": 0.04,           # gentle bob while shown (body units)
    "emote_bob_period": 1.6,
}


# ---------- spec ----------

def _check_spec(spec, where):
    try:
        g = spec["geometry"]
        for k in ("body_r", "rays", "ray_inner", "ray_outer", "ray_width", "eye_dx", "eye_y", "eye_r"):
            float(g[k])
        for k in ("color", "eye", "pupil"):
            registry.hex_rgb(spec[k])
        shape = motion(spec)["mouth"]["shape"]
        if shape not in MOUTH_SHAPES:
            raise ValueError(f"mouth.shape 要是 {'、'.join(MOUTH_SHAPES)} 其中之一：{shape}")
        emotes = spec.get("emotes", {})
        for name, c in emotes.get("colors", {}).items():
            if name not in EMOTES:
                raise ValueError(f"emotes.colors 的 {name} 不是符號名稱（{'、'.join(EMOTES)}）")
            registry.hex_rgb(c)
        if "blush" in emotes:
            registry.hex_rgb(emotes["blush"])
    except (KeyError, TypeError, ValueError) as e:
        raise registry.ConfigError(f"{where} 的 mascot 欄位不對：{e!r}")
    return spec


# brands/<name>/brand.json "mascot" (raises ConfigError when the brand has no mascot)
def load_spec(brand=DEFAULT_BRAND, brands_root=None):
    return spec_from_brand(registry.load_brand(brand, brands_root))


def spec_from_brand(brand):
    if not brand.data.get("mascot"):
        raise registry.ConfigError(f"品牌「{brand.name}」的 brand.json 沒有 mascot")
    return _check_spec(brand.data["mascot"], brand.root / "brand.json")


# the mascot of a registry.Style's brand
def spec_from_style(style):
    if style.brand is None:
        raise registry.ConfigError(f"風格「{style.name}」沒有指定品牌（style.json 的 \"brand\"），沒有角色可用")
    if not style.brand.data.get("mascot"):
        raise registry.ConfigError(f"風格「{style.name}」的品牌「{style.brand.name}」沒有 mascot")
    return spec_from_brand(style.brand)


def motion(spec):
    out = dict(MOTION)
    for k, v in spec.get("motion", {}).items():
        out[k] = {**MOTION[k], **v} if isinstance(MOTION.get(k), dict) and isinstance(v, dict) else v
    return out


def geometry(spec):
    return {k: float(v) for k, v in spec["geometry"].items()}


# body units the square frame must cover so no notch, stretch or squash ever clips
def view_extent(spec):
    m, g = motion(spec), geometry(spec)
    wave_reach = g["ray_outer"] + (m["point_reach"] - g["ray_outer"]) * m["wave_reach"]
    reach = max(m["point_reach"], g["ray_outer"], wave_reach) + g["ray_width"] * m["point_thicken"] / 2
    stretch = max(m["squash"][0], m["surprised_body"][1], m["hop_squash"][0], m["hop_stretch"])
    return reach * stretch * (1 + max(m["loud_gain"], m["talk_stretch"])) * (1 + m["breath_amp"]) * 1.03


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# emote colour (brand.json mascot.emotes.colors; default: the eye colour) and the blush colour / opacity
def emote_color(spec, name):
    return registry.hex_rgb(spec.get("emotes", {}).get("colors", {}).get(name, spec["eye"]))


def blush_color(spec):
    e = spec.get("emotes", {})
    return registry.hex_rgb(e.get("blush", spec["pupil"])), float(e.get("blush_opacity", 0.6))


# a direction name (DIRS) or an (x, y) vector (maths orientation: +y up) -> unit vector
def unit(dir):
    if isinstance(dir, (tuple, list)) and len(dir) == 2:
        x, y = float(dir[0]), float(dir[1])
        n = math.hypot(x, y)
        if n < 1e-9:
            raise ValueError("方向向量不能是 0")
        return x / n, y / n
    if dir not in DIRS:
        raise ValueError(f"方向要是 {'、'.join(DIRS)} 其中之一：{dir}")
    x, y = DIRS[dir]
    n = math.hypot(x, y)
    return x / n, y / n


# ---------- pose ----------

@dataclass(frozen=True)
class Pose:
    sx: float = 1.0          # body scale (squash / stretch)
    sy: float = 1.0
    scale: float = 1.0       # uniform (loudness)
    look_x: float = 0.0      # eye offset, body units
    look_y: float = 0.0
    eye_open: float = 1.0    # 0 = closed line
    eye_h: float = 1.0       # eye height factor
    eye_size: float = 1.0
    pupil: float = 0.0       # 0..1 pupil size
    pupil_x: float = 0.0     # pupil direction inside the eye
    pupil_y: float = 0.0
    happy: float = 0.0       # 0 dot eyes .. 1 arc eyes
    rays: tuple = field(default_factory=tuple)  # per-notch extension 0..1 (empty = all 0)
    tilt: float = 0.0        # whole-body rotation, radians, counter-clockwise
    ring_rot: float = 0.0    # notch ring rotation, radians
    ray_rot: tuple = field(default_factory=tuple)  # per-notch angle offset, radians
    mouth: float = 0.0       # 0 hidden .. 1 shown (only while speaking)
    mouth_open: float = 0.0  # 0 closed line .. 1 fully open
    lid: float = 0.0         # fraction of each eye cut away from the top (sad, angry, proud, worried)
    lid_tilt: float = 0.0    # lid angle, radians: + = inner corners lower (angry), - = outer corners lower (sad)
    eye_asym: float = 0.0    # right eye 1 + a, left eye 1 - 0.6 a (confused)
    heart: float = 0.0       # 0 dot eyes .. 1 heart eyes (love)
    star: float = 0.0        # 0 dot eyes .. 1 star eyes (excited)
    blush: float = 0.0       # 0 .. 1 blush ovals under the eyes (embarrassed)
    droop: float = 0.0       # notches turn toward down by this (radians at the sides; negative lifts them)
    ray_out: float = 0.0     # notches move outward (body units)
    ray_len: float = 0.0     # notch length change, fraction of the normal length
    ray_sharp: float = 0.0   # 0 round notches .. 1 pointed
    sink: float = 0.0        # whole body lower by this (body units)


def _pad(a, b):
    n = max(len(a), len(b))
    return tuple(a) + (0.0,) * (n - len(a)), tuple(b) + (0.0,) * (n - len(b))


def lerp_pose(a, b, w):
    if w <= 0:
        return a
    if w >= 1:
        return b
    out = {}
    for f in fields(Pose):
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if isinstance(va, tuple):
            va, vb = _pad(va, vb)
            out[f.name] = tuple(x + (y - x) * w for x, y in zip(va, vb))
        else:
            out[f.name] = va + (vb - va) * w
    return Pose(**out)


IDLE = Pose()


# index of the notch closest to dir (notch 0 points up, then clockwise)
def nearest_ray(spec, dir):
    n = int(geometry(spec)["rays"])
    x, y = unit(dir)
    ang = math.atan2(y, x)
    return min(range(n), key=lambda k: abs(math.remainder(ray_angle(n, k) - ang, math.tau)))


def ray_angle(n, k):
    return math.pi / 2 - k * math.tau / n


def _one_ray(spec, k, value):
    n = int(geometry(spec)["rays"])
    out = [0.0] * n
    out[k] = value
    return tuple(out)


# the held pose of a state; momentary states return their peak for still images
def target_pose(spec, state, dir=None):
    m = motion(spec)
    if state == "idle":
        return IDLE
    if state == "look":
        x, y = unit(dir or "right")
        return Pose(look_x=x * m["look"], look_y=y * m["look"])
    if state == "surprised":
        sx, sy = m["surprised_body"]
        return Pose(sx=sx, sy=sy, eye_h=m["surprised_eye_h"])
    if state == "thinking":
        return Pose(eye_size=m["thinking_eye"], look_y=m["thinking_look_up"], pupil=1.0, pupil_x=-0.25, pupil_y=0.95)
    if state == "happy":
        return Pose(happy=1.0)
    if state == "point":
        dir = dir or "up-right"
        x, y = unit(dir)
        return Pose(look_x=x * m["look"], look_y=y * m["look"], rays=_one_ray(spec, nearest_ray(spec, dir), 1.0))
    if state == "blink":
        return Pose(eye_open=0.0)
    if state == "squash":
        sx, sy = m["squash"]
        return Pose(sx=sx, sy=sy)
    if state == "wave":
        k = nearest_ray(spec, dir or "up-right")
        return Pose(rays=_one_ray(spec, k, m["wave_reach"]), ray_rot=_one_ray(spec, k, math.radians(m["wave_deg"])))
    if state == "spin":
        return Pose(happy=1.0, ring_rot=math.radians(m["spin_deg"]) / 4)
    if state == "shiver":
        return Pose(sx=1.04, sy=0.96, eye_open=0.6)
    if state == "jump":
        s = m["hop_stretch"]
        return Pose(sx=1 - (s - 1) / 2, sy=s, eye_h=m["surprised_eye_h"])
    if state in EMOTIONS:
        return _emotion_pose(m, state)
    raise ValueError(f"表情要是 {'、'.join(STATES)} 其中之一：{state}")


# held poses of the emotions (live motion such as tremble, bounce and side looks is added by MascotTimeline)
def _emotion_pose(m, state):
    if state == "joy":
        return Pose(happy=1.0, scale=m["joy_puff"], droop=-m["joy_lift"], ray_out=m["joy_out"])
    if state == "sad":
        lid, tilt = m["lid_sad"]
        return Pose(lid=lid, lid_tilt=tilt, sink=m["sad_sink"], sx=1.02, sy=0.97, droop=m["sad_droop"],
                    ray_len=m["sad_short"], look_y=-0.03)
    if state == "angry":
        lid, tilt = m["lid_angry"]
        return Pose(lid=lid, lid_tilt=tilt, ray_len=m["angry_long"], ray_sharp=1.0, sx=1.02, sy=0.98)
    if state == "worried":
        lid, tilt = m["lid_worried"]
        return Pose(eye_size=m["worried_eye"], lid=lid, lid_tilt=tilt, sy=0.98, droop=0.08)
    if state == "confused":
        return Pose(eye_asym=m["confused_eyes"], tilt=math.radians(m["confused_tilt"]), look_y=0.02)
    if state == "proud":
        lid, tilt = m["lid_proud"]
        return Pose(lid=lid, lid_tilt=tilt, scale=m["proud_scale"], look_y=0.025, droop=-0.06)
    if state == "love":
        return Pose(heart=1.0, scale=1.02)
    if state == "sleepy":
        return Pose(eye_open=0.0, sink=m["sleepy_sink"], droop=0.1, look_y=-0.02)
    if state == "excited":
        return Pose(star=1.0, scale=1.03, ray_out=0.04)
    lx, ly = m["embarrassed_look"]  # embarrassed
    return Pose(look_x=lx, look_y=ly, blush=1.0, eye_size=0.9)


# 0..1 eye closure, dt seconds after a blink starts
def blink_env(spec, dt):
    c, h, o = motion(spec)["blink"]
    if dt < 0 or dt > c + h + o:
        return 0.0
    if dt < c:
        return ease(dt / c)
    if dt < c + h:
        return 1.0
    return 1.0 - ease((dt - c - h) / o)


def _env(dt, c, h, o):
    if dt < 0 or dt > c + h + o:
        return 0.0
    if dt < c:
        return ease(dt / c)
    if dt < c + h:
        return 1.0
    return 1.0 - ease((dt - c - h) / o)


# eye closure 0..1 of a blink of a given kind (single, double, slow, squint)
def blink_amount(spec, kind, dt):
    m = motion(spec)
    if kind == "double":
        return max(blink_env(spec, dt), blink_env(spec, dt - m["blink_double_gap"]))
    if kind == "slow":
        k = m["blink_slow"]
        return _env(dt, *(x * k for x in m["blink"]))
    if kind == "squint":
        depth, c, h, o = m["squint"]
        return depth * _env(dt, c, h, o)
    return blink_env(spec, dt)


def blink_length(spec, kind):
    m = motion(spec)
    if kind == "double":
        return sum(m["blink"]) + m["blink_double_gap"]
    if kind == "slow":
        return sum(m["blink"]) * m["blink_slow"]
    if kind == "squint":
        return sum(m["squint"][1:])
    return sum(m["blink"])


def squash_env(spec, dt):
    m = motion(spec)
    a, b = m["squash_in"], m["squash_out"]
    if dt < 0 or dt > a + b:
        return 0.0
    return ease(dt / a) if dt < a else 1.0 - ease((dt - a) / b)


# breathing, blink, squash and loudness on top of a held pose
def apply_overlays(spec, pose, t=0.0, blink=0.0, squash=0.0, loud=0.0, breathe=True):
    m = motion(spec)
    b = math.sin(math.tau * t / m["breath_period"]) * m["breath_amp"] if breathe else 0.0
    qx, qy = m["squash"]
    sx = pose.sx * (1 + (qx - 1) * squash) * (1 - b / 2)
    sy = pose.sy * (1 + (qy - 1) * squash) * (1 + b)
    return replace(pose, sx=sx, sy=sy, scale=pose.scale * (1 + m["loud_gain"] * loud),
                   eye_open=pose.eye_open * (1 - blink))


# a leap (hop or jump) at progress u 0..1: anticipation squash, flight, landing squash.
# -> (horizontal fraction 0..1, height fraction 0..1, sx, sy)
def leap(spec, u, ant=0.18, land=0.22):
    m = motion(spec)
    qx, qy = m["hop_squash"]
    st = m["hop_stretch"] - 1
    u = min(max(u, 0.0), 1.0)
    if u < ant:
        q = ease(u / ant)
        return 0.0, 0.0, 1 + (qx - 1) * q, 1 + (qy - 1) * q
    if u > 1 - land:
        w = (u - (1 - land)) / land
        q = math.sin(math.pi * w) * (1 - 0.3 * w)
        return 1.0, 0.0, 1 + (qx - 1) * q, 1 + (qy - 1) * q
    v = (u - ant) / (1 - ant - land)
    s = st * abs(2 * v - 1)
    release = ease(v / 0.15)  # blend out of the anticipation squash
    sx = (1 + (qx - 1) * (1 - release)) * (1 - s / 2)
    sy = (1 + (qy - 1) * (1 - release)) * (1 + s)
    return v, 4 * v * (1 - v), sx, sy


# ---------- timeline: events -> pose at t ----------

@dataclass(frozen=True)
class Event:
    t: float
    do: str                    # a state, or "move" for a move without an expression
    dir: str | None = None
    hold: float | None = None
    to: object = None          # [x, y] in 1080x1920 coords, or "home" / "left" / "right" / "center"
    move: str | None = None    # glide (default) | hop
    size: float | None = None  # display size after the move
    emote: str | None = None   # a symbol that pops up next to the head (EMOTES)
    emote_hold: float | None = None  # seconds the emote stays before it fades
    target: tuple | None = None  # [x, y] (1080x1920) that point / look aim at (and an emote faces)


def _sorted_events(events):
    return sorted((e if isinstance(e, Event) else Event(**e) for e in events), key=lambda e: e.t)


# (scale, alpha) of an emote dt seconds after it appears and shown for hold seconds; None when not shown.
# pop-in: 0 -> overshoot -> 1 over emote_pop; fade-out (alpha and a little scale) over emote_fade after hold
def emote_env(spec, dt, hold):
    m = motion(spec)
    a, b = m["emote_pop"]
    over, fade = m["emote_overshoot"], m["emote_fade"]
    if dt < 0 or dt > hold + fade:
        return None
    if dt < a:
        s = over * ease(dt / a)
    elif dt < b:
        s = over + (1 - over) * ease((dt - a) / (b - a))
    else:
        s = 1.0
    alpha = 1.0
    if dt > hold:
        f = ease((dt - hold) / fade)
        alpha, s = 1 - f, s * (1 - 0.08 * f)
    return s, alpha


class Timeline:
    """Held states change with smooth transitions; one-shots are overlays; idle gets seeded varied blinks."""

    def __init__(self, spec, events=(), seed=0, duration=None, auto_blink=True):
        self.spec, self.m = spec, motion(spec)
        events = _sorted_events(events)
        for e in events:
            if e.do != "move":
                target_pose(spec, e.do, e.dir)  # validate state / dir
            if e.move is not None and e.move not in MOVES:
                raise ValueError(f"move 要是 {'、'.join(MOVES)} 其中之一：{e.move}")
            if e.emote is not None and e.emote not in EMOTES:
                raise ValueError(f"emote 要是 {'、'.join(EMOTES)} 其中之一：{e.emote}")
            if e.target is not None and (len(e.target) != 2 or not all(isinstance(v, (int, float)) for v in e.target)):
                raise ValueError(f"target 要是 [x, y]：{e.target}")
        self.events = events
        held = [e for e in events if e.do in HELD]
        self.changes = [(0.0, "idle", IDLE)]  # (time, state name, target pose)
        self.change_events = [None]           # the event behind each change (None for a return to idle)
        held_len = {}
        for i, e in enumerate(held):
            end = e.t + (self.m["hold"] if e.hold is None else float(e.hold))
            nxt = held[i + 1].t if i + 1 < len(held) else math.inf
            self.changes.append((e.t, e.do, target_pose(spec, e.do, e.dir)))
            self.change_events.append(e)
            held_len[id(e)] = min(end, nxt) - e.t
            if end < nxt and e.do != "idle":
                self.changes.append((end, "idle", IDLE))
                self.change_events.append(None)
        # emotes: (start, name, hold, target); an emotion with a companion emote brings it for as long as it is held
        self.emotes = []
        for e in events:
            name = e.emote or EMOTION_EMOTE.get(e.do)
            if name is None:
                continue
            if e.emote_hold is not None:
                hold = float(e.emote_hold)
            elif e.emote is None or e.do in EMOTION_EMOTE:
                hold = held_len.get(id(e), self.m["emote_hold"]) if e.do in HELD else self.m["emote_hold"]
            else:
                hold = self.m["emote_hold"]
            self.emotes.append((e.t, name, max(hold, 0.25), e.target))
        self.blinks = [e.t for e in events if e.do == "blink"]
        self.blink_kinds = {t: "single" for t in self.blinks}
        self.squashes = [e.t for e in events if e.do == "squash"]
        if auto_blink:
            auto = self._auto_blinks(seed, duration or (events[-1].t + 10 if events else 30))
            self.blink_kinds.update(auto)
            self.blinks = sorted(self.blinks + list(auto))

    def _auto_blinks(self, seed, duration):
        rng, lo_hi = random.Random(seed), self.m["blink_every"]
        mix = self.m["blink_mix"]
        kinds, weights = [k for k in BLINK_KINDS if k in mix], [float(mix[k]) for k in BLINK_KINDS if k in mix]
        out, t = {}, rng.uniform(1.0, lo_hi[0])
        while t < duration:
            kind = rng.choices(kinds, weights)[0]
            # no auto blink over arc eyes (happy) or wide surprised eyes
            calm = all(self.state_at(x) not in CALM_EYES for x in (t, t + 0.5))
            if calm and all(abs(t - b) > 0.8 for b in self.blinks):
                out[round(t, 4)] = kind
            t += rng.uniform(*lo_hi)
        return out

    def state_at(self, t):
        return [name for ct, name, _ in self.changes if ct <= t][-1]

    def _change_index(self, t):
        return max(i for i, (ct, _, _) in enumerate(self.changes) if ct <= t)

    # 0..1: how much the held state `name` is in effect at t (eased in over the transition, eased out after)
    def state_weight(self, t, name):
        T = self.m["transition"]
        i = self._change_index(t)
        ct = self.changes[i][0]
        if self.changes[i][1] == name:
            w = ease((t - ct) / T)
            if i > 0 and self.changes[i - 1][1] == name:
                w = 1.0
            return w
        if i > 0 and self.changes[i - 1][1] == name and t - ct < T:
            return 1 - ease((t - ct) / T)
        return 0.0

    # emotes shown at t: [(name, seconds since it appeared, scale, alpha, target)]
    def emotes_at(self, t):
        out = []
        for t0, name, hold, target in self.emotes:
            env = emote_env(self.spec, t - t0, hold)
            if env is not None and env[0] > 1e-3 and env[1] > 1e-3:
                out.append((name, t - t0, env[0], env[1], target))
        return out

    # the held pose at t, including transitions (each transition starts from wherever the last one was)
    def held_pose(self, t):
        T = self.m["transition"]
        frm, (t0, _, tgt) = IDLE, self.changes[0]
        for ct, _, nxt in self.changes[1:]:
            if ct > t:
                break
            frm = lerp_pose(frm, tgt, ease((ct - t0) / T))
            t0, tgt = ct, nxt
        return lerp_pose(frm, tgt, ease((t - t0) / T))

    def blink_at(self, t):
        return max([blink_amount(self.spec, self.blink_kinds.get(b, "single"), t - b) for b in self.blinks
                    if -0.01 < t - b < 1.5] + [0.0])

    def pose_at(self, t, loud=0.0):
        squash = max([squash_env(self.spec, t - s) for s in self.squashes] + [0.0])
        return apply_overlays(self.spec, self.held_pose(t), t, self.blink_at(t), squash, loud)


# ---------- narration -> voice features ----------

VOICE_SR = 16000
SILENCE_DB = -45.0  # RMS below this counts as silent
FEATURES_VERSION = 2


# the voice track as one mono float array at sr (each segment {"file", "start"} at its start time)
def voice_samples(voice, total, sr=VOICE_SR):
    out = np.zeros(int(math.ceil(total * sr)) + sr, np.float32)
    for seg in voice:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(seg["file"]), "-f", "f32le", "-ac", "1",
                              "-ar", str(sr), "-"], capture_output=True, timeout=300)
        if raw.returncode != 0:
            raise RuntimeError(f"讀不到 {seg['file']}：{raw.stderr.decode('utf-8', 'replace').strip()}")
        x = np.frombuffer(raw.stdout, np.float32)
        a = int(round(seg["start"] * sr))
        n = max(min(len(x), len(out) - a), 0)
        out[a:a + n] += x[:n]
    return out


def frame_db(samples, frames, sr=VOICE_SR, fps=FPS):
    hop = sr / fps
    db = np.full(frames, -120.0)
    for i in range(frames):
        w = samples[int(i * hop):int((i + 1) * hop)]
        if len(w):
            db[i] = 20 * math.log10(float(np.sqrt(np.mean(w.astype(np.float64) ** 2))) + 1e-9)
    return db


def voice_ref(db):
    voiced = db[db > SILENCE_DB]
    return float(np.percentile(voiced, 95)) if len(voiced) else -12.0


# dB -> 0..1 between SILENCE_DB and the loud end (95th percentile) of the voiced frames
def db_level(db):
    return np.clip((db - SILENCE_DB) / max(voice_ref(db) - SILENCE_DB, 1.0), 0, 1)


# dB -> mouth opening 0..1 over the top range_db of the voice, shaped by curve
def mouth_level(db, range_db, curve):
    return np.clip((db - (voice_ref(db) - range_db)) / range_db, 0, 1) ** curve


# one-pole follower with separate attack / release time constants (seconds)
def follow(x, attack, release, fps=FPS):
    up, down = (1 - math.exp(-1 / (fps * max(s, 1e-6))) for s in (attack, release))
    out, y = np.zeros(len(x)), 0.0
    for i, v in enumerate(x):
        y += (up if v > y else down) * (v - y)
        out[i] = y
    return out


# per-frame loudness 0..1, smoothed (the slow body envelope of the original fixed track)
def loudness(samples, frames, smooth, sr=VOICE_SR, fps=FPS):
    return follow(db_level(frame_db(samples, frames, sr, fps)), smooth, smooth, fps)


# per-frame pitch 0..1: librosa pyin F0 in semitones, normalised to this video's 10th..90th percentile,
# gaps filled by interpolation, smoothed
def pitch_track(samples, frames, sr=VOICE_SR, fps=FPS, smooth=0.12):
    import librosa  # slow import; only needed when features are not cached

    hop = 512
    f0, voiced, _ = librosa.pyin(samples.astype(np.float32), fmin=65, fmax=450, sr=sr, frame_length=2048,
                                 hop_length=hop, fill_na=np.nan)
    ok = voiced & np.isfinite(f0)
    if ok.sum() < 3:
        return np.full(frames, 0.5)
    st = 12 * np.log2(np.where(ok, f0, 1.0))
    lo, hi = np.percentile(st[ok], [10, 90])
    tf = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop)
    p = np.interp(np.arange(frames) / fps, tf[ok], np.clip((st[ok] - lo) / max(hi - lo, 1e-6), 0, 1))
    return follow(p, smooth, smooth, fps)


# frames where the narrator speaks: level above the gate, short gaps bridged; smoothed 0..1
def speaking_gate(level, gate, hang, fps=FPS, attack=0.04, release=0.1):
    on = level > gate
    k = int(round(hang * fps))
    if k > 0 and on.any():
        on = np.convolve(on.astype(float), np.ones(2 * k + 1), "same") > 0  # dilate
        on = np.convolve((~on).astype(float), np.ones(2 * k + 1), "same") == 0  # erode back: gaps < 2*hang closed
        on |= level > gate
    return follow(on.astype(float), attack, release, fps)


# limit how fast x may change: at most rate (units per second)
def slew(x, rate, fps=FPS):
    out, y, step = np.zeros(len(x)), 0.0, rate / fps
    for i, v in enumerate(x):
        y += min(max(v - y, -step), step)
        out[i] = y
    return out


@dataclass
class VoiceFeatures:
    loud: np.ndarray    # fast loudness envelope 0..1 (mouth opening, stretch)
    pitch: np.ndarray   # normalised pitch 0..1
    gate: np.ndarray    # speaking 0..1 (mouth shown)
    fps: int = FPS

    def at(self, t):
        i = int(round(t * self.fps))
        if i < 0 or i >= len(self.loud):
            return 0.0, 0.5, 0.0
        return float(self.loud[i]), float(self.pitch[i]), float(self.gate[i])

    @classmethod
    def silent(cls, frames=0, fps=FPS):
        return cls(np.zeros(frames), np.full(frames, 0.5), np.zeros(frames), fps)


def features_from_samples(samples, frames, spec=None, sr=VOICE_SR, fps=FPS, pitch=True):
    m = motion(spec or {})
    db = frame_db(samples, frames, sr, fps)
    level = db_level(db)
    loud = follow(mouth_level(db, m["mouth_range_db"], m["mouth_curve"]), m["mouth_attack"], m["mouth_release"], fps)
    loud = slew(loud, m["mouth_slew"], fps)
    gate = speaking_gate(level, m["talk_gate"], m["talk_hang"], fps, m["gate_attack"], m["gate_release"])
    p = pitch_track(samples, frames, sr, fps, m["pitch_smooth"]) if pitch else np.full(frames, 0.5)
    return VoiceFeatures(loud, p, gate, fps)


# narration (compose.load_voice segments) -> VoiceFeatures, cached in an .npz keyed by the audio files'
# paths, start times and mtimes (and the motion keys the features depend on)
def voice_features(voice, total, cache=None, spec=None, fps=FPS):
    m = motion(spec or {})
    frames = round(total * fps)
    key = json.dumps({"v": FEATURES_VERSION, "fps": fps, "frames": frames,
                      "m": [m[k] for k in ("mouth_attack", "mouth_release", "mouth_slew", "mouth_range_db", "mouth_curve",
                                                "talk_gate", "talk_hang", "gate_attack", "gate_release", "pitch_smooth")],
                      "seg": [[str(s["file"]), round(float(s["start"]), 3), Path(s["file"]).stat().st_mtime_ns]
                              for s in voice]}, ensure_ascii=False)
    if cache and Path(cache).is_file():
        try:
            z = np.load(cache, allow_pickle=False)
            if str(z["key"]) == key:
                return VoiceFeatures(z["loud"], z["pitch"], z["gate"], fps)
        except (OSError, KeyError, ValueError):
            pass
    f = features_from_samples(voice_samples(voice, total), frames, spec, fps=fps)
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, key=np.array(key), loud=f.loud, pitch=f.pitch, gate=f.gate)
    return f


# ---------- live timeline: expressions + voice + roaming ----------

@dataclass(frozen=True)
class MascotState:
    pose: Pose
    x: float      # centre, 1080x1920 display coords
    y: float
    size: float   # display size (style mascot.size semantics)
    emotes: tuple = ()  # ((name, seconds shown, scale, alpha, side), ...); side +1 = right of the head, -1 = left


class MascotTimeline(Timeline):
    """The mascot over time as one object: expressions, varied blinks, voice-driven mouth/stretch/lift,
    idle float and sway, gestures (point lean, wave, spin, shiver, jump) and roaming moves (glide, hop)
    inside a lane. state(t) -> MascotState; frame(t, scale) -> (RGBA image, centre x, centre y).

    home = (x, y, size) start position and display size (style.json mascot); lane = {"x": [x0, x1],
    "y": [y0, y1]} allowed centre positions (every "to" is clamped into it, with a warning in .warnings).

    target: a point / look event with "target" [x, y] aims at that spot. The notch nearest the vector from the
    mascot's resting centre (after any move) is chosen, and every frame the notch ring turns by the residual so
    the extended notch points exactly at the target from where the body is drawn (lean, tilt, sway and squash
    included); the eyes look along the same vector and the body leans along it."""

    def __init__(self, spec, events=(), voice=None, fps=FPS, *, home=(540, 1500, 300), lane=None, seed=0,
                 duration=None, auto_blink=True, frame=FRAME):
        self.spec, self.m = spec, motion(spec)
        self.voice, self.fps = voice, fps
        self.home = tuple(float(v) for v in home)
        self.lane = None if lane is None else {k: sorted(float(v) for v in lane[k]) for k in ("x", "y")}
        self.frame_size = tuple(float(v) for v in frame)
        self.warnings = []
        ev = _sorted_events(events)
        for e in ev:
            if e.move is not None and e.move not in MOVES:
                raise ValueError(f"move 要是 {'、'.join(MOVES)} 其中之一：{e.move}")
        self.moves = self._build_moves(ev)
        # aimed events: the direction toward the target from where the mascot rests at that time
        aimed = []
        for e in ev:
            if e.target is not None and e.do in ("point", "look"):
                if len(e.target) != 2:
                    raise ValueError(f"target 要是 [x, y]：{e.target}")
                rx, ry = self._rest_at(e.t)
                v = (float(e.target[0]) - rx, -(float(e.target[1]) - ry))
                if math.hypot(*v) > 1e-6:
                    e = replace(e, dir=v)
            aimed.append(e)
        super().__init__(spec, aimed, seed, duration, auto_blink)
        ev = self.events
        self.jumps = [e.t for e in ev if e.do in ("jump", "surprised")]
        self.spins = [e.t for e in ev if e.do in ("spin", "happy")]
        self.waves = [(e.t, nearest_ray(spec, e.dir or "up-right")) for e in ev if e.do == "wave"]
        self.shivers = [e.t for e in ev if e.do == "shiver"]
        self._last = (None, None)

    # where the mascot rests once every move started by t has finished
    def _rest_at(self, t):
        mv = next((mv for mv in reversed(self.moves) if mv["t0"] <= t + 1e-9), None)
        if mv is None:
            return self.home[:2]
        return tuple(mv["cut"][:2]) if "cut" in mv else tuple(mv["p1"][:2])

    # the aimed point / look event in effect at t (also while it eases out), or None
    def aim_at(self, t):
        i = self._change_index(t)
        for j, fading in ((i, False), (i - 1, True)):
            if j < 0:
                continue
            e = self.change_events[j]
            if e is not None and e.target is not None and e.do in ("point", "look"):
                if not fading or t - self.changes[i][0] < self.m["transition"]:
                    return e
        return None

    # ----- roaming -----

    def _named(self, name):
        x0, x1 = self.lane["x"] if self.lane else (150.0, 930.0)
        return {"home": self.home[:2], "left": (x0, self.home[1]), "right": (x1, self.home[1]),
                "center": ((x0 + x1) / 2, self.home[1])}.get(name)

    def resolve_to(self, to, t=None):
        if isinstance(to, str):
            xy = self._named(to)
            if xy is None:
                raise ValueError(f"to 要是 [x, y] 或 home、left、right、center：{to}")
            return xy if to == "home" else self._clamp(xy, t)
        x, y = (float(v) for v in to)
        return self._clamp((x, y), t)

    def _clamp(self, xy, t=None):
        if not self.lane:
            return xy
        (x0, x1), (y0, y1) = self.lane["x"], self.lane["y"]
        out = (min(max(xy[0], x0), x1), min(max(xy[1], y0), y1))
        if abs(out[0] - xy[0]) > 0.5 or abs(out[1] - xy[1]) > 0.5:
            when = "" if t is None else f"{t:.2f}s 的"
            self.warnings.append(f"{when}角色移動目標 [{xy[0]:.0f}, {xy[1]:.0f}] 超出角色走道"
                                 f"（x {x0:.0f}–{x1:.0f}、y {y0:.0f}–{y1:.0f}），改成 [{out[0]:.0f}, {out[1]:.0f}]")
        return out

    def _build_moves(self, events):
        moves, cur = [], (self.home[0], self.home[1], self.home[2])
        for e in events:
            if e.to is None and e.size is None:
                continue
            if moves and e.t < moves[-1]["t1"]:  # interrupt the running move where it is
                x, y, s, _ = self._place_in(moves[-1], e.t)
                moves[-1] = dict(moves[-1], t1=e.t, cut=(x, y, s))
                cur = (x, y, s)
            x1, y1 = cur[:2] if e.to is None else self.resolve_to(e.to, e.t)
            s1 = cur[2] if e.size is None else float(e.size)
            if s1 <= 0:
                raise ValueError(f"size 要大於 0：{e.size}")
            kind = e.move or "glide"
            d = self.m["hop"] if kind == "hop" else self.m["glide"]
            moves.append(dict(t0=e.t, t1=e.t + d, d=d, kind=kind, p0=cur, p1=(x1, y1, s1)))
            cur = (x1, y1, s1)
        return moves

    # position during a move: (x, y, size, info) where info = (dx dir, dy dir, weight, sx, sy, tilt)
    def _place_in(self, mv, t):
        if "cut" in mv and t >= mv["t1"]:
            return (*mv["cut"], None)
        u = (t - mv["t0"]) / mv["d"]
        if u >= 1:
            return (*mv["p1"], None)
        (x0, y0, s0), (x1, y1, s1) = mv["p0"], mv["p1"]
        dist = math.hypot(x1 - x0, y1 - y0)
        dx, dy = ((x1 - x0) / dist, (y1 - y0) / dist) if dist > 1e-6 else (0.0, 0.0)
        look_w = min(1.0, 4 * u, 4 * (1 - u))
        if mv["kind"] == "hop":
            f, h, sx, sy = leap(self.spec, u)
            k = max(s0, s1) / self.home[2]
            ceiling = min(y0, y1) - self._lane_top_limit()
            height = max(0.0, min(self.m["hop_height_px"] * k, ceiling))
            x, y, s = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f - height * h, s0 + (s1 - s0) * f
            return x, y, s, (dx, dy, look_w, sx, sy, 0.0)
        f = u * u * u * (u * (u * 6 - 15) + 10)  # smootherstep
        k = (s0 + (s1 - s0) * f) / self.home[2]
        lift = self.m["glide_float_px"] * k * math.sin(math.pi * u) if dist > 1 else 0.0
        tilt = -math.copysign(1, dx) * math.radians(self.m["glide_tilt"]) * math.sin(math.pi * u) if abs(dx) > 0.2 else 0.0
        return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f - lift, s0 + (s1 - s0) * f, (dx, dy, look_w, 1.0, 1.0, tilt)

    def _lane_top_limit(self):
        return (self.lane["y"][0] if self.lane else 0.0) - self.m["lane_rise_px"]

    def place(self, t):
        mv = next((mv for mv in reversed(self.moves) if mv["t0"] <= t), None)
        if mv is None:
            return (*self.home, None)
        return self._place_in(mv, t)

    # ----- the full state at t -----

    def state(self, t):
        if self._last[0] == t:
            return self._last[1]
        m, spec = self.m, self.spec
        loud, pitch, gate = self.voice.at(t) if self.voice is not None else (0.0, 0.5, 0.0)
        body = self._body_at(t)
        x, y, size, mv = self.place(t)
        k = size / self.home[2]
        r_px = size / (2 * m["size_extent"])  # body radius in display px
        held = self.held_pose(t)
        squash = max([squash_env(spec, t - s) for s in self.squashes] + [0.0])
        pose = apply_overlays(spec, held, t, self.blink_at(t), squash, 0.0)
        sx, sy, tilt, dx, dy = pose.sx, pose.sy, pose.tilt, 0.0, 0.0
        look_x, look_y = pose.look_x, pose.look_y
        n = int(geometry(spec)["rays"])
        rays = list(_pad(pose.rays, (0.0,) * n)[0])
        ray_rot = list(_pad(pose.ray_rot, (0.0,) * n)[0])

        # point: lean toward the extended notch(es), or along the vector to the target
        aim, aim_k, aim_w = self.aim_at(t), None, 0.0
        if aim is not None:
            ux, uy = self._toward(aim.target, x, y)
            mag = math.hypot(look_x, look_y)
            look_x, look_y = ux * mag, uy * mag
        if aim is not None and aim.do == "point":
            aim_k = nearest_ray(spec, aim.dir)
            aim_w = rays[aim_k]
            lx, ly = ux * aim_w, uy * aim_w
        else:
            lx = sum(rays[i] * math.cos(ray_angle(n, i)) for i in range(n))
            ly = sum(rays[i] * math.sin(ray_angle(n, i)) for i in range(n))
        tilt -= math.radians(m["point_lean"]) * lx
        dx += m["point_lean_px"] * k * lx
        dy -= m["point_lean_px"] * k * ly

        # talking: stretch with loudness, mouth shown while speaking; pitch lifts and tilts
        sy *= 1 + m["talk_stretch"] * body
        sx *= 1 - m["talk_stretch"] * body / 2
        lift, hi = self._lift_at(t)
        dy -= m["pitch_lift_px"] * k * lift
        tilt += math.radians(m["pitch_tilt"]) * hi

        # idle float and sway
        dy += m["bob_px"] * k * math.sin(math.tau * t / m["bob_period"])
        tilt += math.radians(m["sway"]) * math.sin(math.tau * t / m["sway_period"] + 0.7)

        # emotions that move: angry trembles, excited bounces, worried eyes look side to side
        w = self.state_weight(t, "angry")
        if w:
            dx += m["angry_tremble_px"] * k * math.sin(math.tau * m["angry_tremble_hz"] * t) * w
        w = self.state_weight(t, "excited")
        if w:
            dy -= m["excited_bounce_px"] * k * abs(math.sin(math.pi * m["excited_bounce_hz"] * t)) * w
        w = self.state_weight(t, "worried")
        if w:
            look_x += m["worried_look"] * math.sin(math.tau * m["worried_look_hz"] * t) * w

        # emotes: an emote with a target turns the eyes toward it
        emotes = self.emotes_at(t)
        for name, et, _, alpha, target in emotes:
            if target is not None:
                ux, uy = self._toward(target, x, y)
                ew = alpha * ease(et / 0.2)
                look_x += (ux * m["look"] - look_x) * ew
                look_y += (uy * m["look"] - look_y) * ew

        # one-shots
        # a finished spin keeps only its remainder modulo one notch step: with spin_deg a multiple of 360/n the ring
        # looks the same and notch indices stay put, so a later point() still extends the notch facing dir
        step, ring = math.tau / n, 0.0
        for s in self.spins:
            if t >= s:
                u = (t - s) / m["spin"]
                a = math.radians(m["spin_deg"]) * ease(min(u, 1.0))
                ring += a % step if u >= 1 else a
        for t0, ray in self.waves:
            u = (t - t0) / m["wave"]
            if 0 <= u <= 1:
                env = ease(u / 0.15) * ease((1 - u) / 0.2)
                rays[ray] = max(rays[ray], m["wave_reach"] * env)
                ray_rot[ray] += math.radians(m["wave_deg"]) * math.sin(math.tau * m["wave_times"] * u) * env
        eye_open = pose.eye_open
        for t0 in self.shivers:
            u = (t - t0) / m["shiver"]
            if 0 <= u <= 1:
                dx += m["shiver_px"] * k * math.sin(math.tau * m["shiver_hz"] * (t - t0)) * (1 - u)
                eye_open *= 1 - 0.4 * math.sin(math.pi * u)
        for t0 in self.jumps:
            u = (t - t0) / m["jump"]
            if 0 <= u <= 1:
                _, h, jx, jy = leap(spec, u, ant=0.14, land=0.26)
                height = max(0.0, min(m["jump_height_px"] * k, y - self._lane_top_limit()))
                dy -= height * h
                sx, sy = sx * jx, sy * jy

        # moving: hop squash/stretch, glide lean, eyes look where it is going
        if mv is not None:
            mdx, mdy, w, mx, my, mtilt = mv
            sx, sy, tilt = sx * mx, sy * my, tilt + mtilt
            look_x += (mdx * m["look"] * 1.3 - look_x) * w
            look_y += (-mdy * m["look"] * 1.3 - look_y) * w

        dy += r_px * (1 - sy) if sy < 1 else 0.0  # squash stays on the ground

        # aim: turn the ring by the residual so the extended notch points exactly at the target, as drawn
        # (shapes() scales by sx, sy then rotates by tilt; invert that for the pre-transform notch angle)
        if aim_k is not None and aim_w > 1e-4:
            cx, cy = x + dx, y + dy + pose.sink * r_px
            d = math.atan2(-(float(aim.target[1]) - cy), float(aim.target[0]) - cx)
            tsx, tsy = sx * pose.scale, sy * pose.scale
            want = math.atan2(math.sin(d - tilt) / tsy, math.cos(d - tilt) / tsx)
            have = ray_angle(n, aim_k) + ring + ray_rot[aim_k]
            if pose.droop:
                have -= pose.droop * math.cos(have)
            ring += aim_w * math.remainder(want - have, math.tau)

        # emotes sit up-right of the head, or up-left when that would leave the frame
        reach = (m["emote_at"][0] + 0.5 * m["emote_size"] * m["emote_overshoot"]) * r_px
        side = 1 if x + reach <= self.frame_size[0] - 2 else -1  # roaming x only: no flicker from shiver or lean
        shown = tuple((name, et, s, a, side) for name, et, s, a, _ in emotes)

        pose = replace(pose, sx=sx, sy=sy, tilt=tilt, look_x=look_x, look_y=look_y, eye_open=eye_open,
                       rays=tuple(rays), ray_rot=tuple(ray_rot), ring_rot=ring, mouth=gate, mouth_open=loud)
        st = MascotState(pose, x + dx, y + dy, size, shown)
        self._last = (t, st)
        return st

    # unit vector (maths orientation, +y up) from display point (x, y) toward a display target
    @staticmethod
    def _toward(target, x, y):
        vx, vy = float(target[0]) - x, -(float(target[1]) - y)
        n = math.hypot(vx, vy)
        return (vx / n, vy / n) if n > 1e-6 else (0.0, 0.0)

    def pose_at(self, t, loud=None):
        return self.state(t).pose

    # pitch x speaking, eased: the lift and tilt no longer jump when the mouth gate opens (was up to 3 px per frame)
    def _lift_at(self, t):
        if self.voice is None:
            return 0.0, 0.0
        if getattr(self, "_lift", None) is None:
            p, g = np.asarray(self.voice.pitch, float), np.asarray(self.voice.gate, float)
            a, r, fps = self.m["lift_attack"], self.m["lift_release"], self.voice.fps
            self._lift = (follow(p * g, a, r, fps), follow(np.maximum(2 * p - 1, 0.0) * g, a, r, fps))
        i = int(round(t * self.voice.fps))
        if not 0 <= i < len(self._lift[0]):
            return 0.0, 0.0
        return float(self._lift[0][i]), float(self._lift[1][i])

    # slow loudness envelope for the body stretch (the mouth keeps the fast one)
    def _body_at(self, t):
        if self.voice is None:
            return 0.0
        if getattr(self, "_body", None) is None:
            self._body = follow(np.asarray(self.voice.loud, float), self.m["stretch_attack"], self.m["stretch_release"],
                                self.voice.fps)
        i = int(round(t * self.voice.fps))
        return float(self._body[i]) if 0 <= i < len(self._body) else 0.0

    # hashable summary of what frame(t, scale) would draw (two equal keys draw the same image)
    def key(self, t, scale=1.0):
        st = self.state(t)
        vals = []
        for f in fields(Pose):
            v = getattr(st.pose, f.name)
            vals.append(tuple(round(x, 3) for x in v) if isinstance(v, tuple) else round(v, 3))
        emotes = tuple((name, round(et, 3), round(es, 3), round(ea, 3), side) for name, et, es, ea, side in st.emotes)
        return (tuple(vals), round(st.x * scale, 2), round(st.y * scale, 2), round(st.size * scale), emotes)

    # RGBA image of the mascot at t, scaled by scale, and where its centre goes (output pixels)
    def frame(self, t, scale=1.0, ss=4):
        st = self.state(t)
        r_px = st.size * scale / (2 * self.m["size_extent"])
        px = max(8, int(math.ceil(2 * view_extent(self.spec) * r_px / 2)) * 2)
        # sub-pixel placement: the fractional part of the top-left goes into the supersampled drawing, and the image
        # is returned with a centre whose top-left is a whole pixel (callers paste at round(cx - w/2)). Rounding the
        # position instead made slow floats move in 1 px stairs (78 % of preview frames still, then a jump)
        ox, oy = st.x * scale - px / 2, st.y * scale - px / 2
        ix, iy = math.floor(ox), math.floor(oy)
        img = draw_pose(self.spec, st.pose, px, extent=px / (2 * r_px), ss=ss, pad=1, shift=(ox - ix, oy - iy),
                        emotes=st.emotes)
        return img, ix - 1 + img.width / 2, iy - 1 + img.height / 2


# ---------- shapes: Pose -> polygons in body units (y up, centre 0,0) ----------

def ellipse(cx, cy, rx, ry, n=96):
    a = np.linspace(0, math.tau, n, endpoint=False)
    return np.stack([cx + rx * np.cos(a), cy + ry * np.sin(a)], axis=1)


# a thick polyline with round caps, as one closed outline (centreline Nx2, half width hw)
def stroke(line, hw, cap_n=14):
    line = np.asarray(line, float)
    d = np.gradient(line, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)
    nrm = np.stack([-d[:, 1], d[:, 0]], axis=1)
    left, right = line + nrm * hw, line - nrm * hw

    def cap(p, direction):
        base = math.atan2(direction[1], direction[0])
        a = np.linspace(base + math.pi / 2, base - math.pi / 2, cap_n)
        return np.stack([p[0] + hw * np.cos(a), p[1] + hw * np.sin(a)], axis=1)

    return np.concatenate([left, cap(line[-1], d[-1])[1:-1], right[::-1], cap(line[0], -d[0])[1:-1]])


# horizontal stadium (pill) centred at cx, cy: total half width w, half height h (h <= w)
def stadium(cx, cy, w, h):
    return stroke(np.array([[cx - (w - h), cy], [cx + (w - h) + 1e-6, cy]]), h)


def _eye(cx, cy, rx, ry):
    return ellipse(cx, cy, rx, ry) if ry >= rx else stadium(cx, cy, rx, ry)


# rounded rectangle centred at cx, cy with half sizes w, h and corner radius r
def round_rect(cx, cy, w, h, r, n=10):
    r = min(r, w, h)
    pts = []
    for (qx, qy), a0 in (((1, 1), 0.0), ((-1, 1), math.pi / 2), ((-1, -1), math.pi), ((1, -1), 1.5 * math.pi)):
        ccx, ccy = cx + qx * (w - r), cy + qy * (h - r)
        a = np.linspace(a0, a0 + math.pi / 2, n)
        pts.append(np.stack([ccx + r * np.cos(a), ccy + r * np.sin(a)], 1))
    return np.concatenate(pts)


MOUTH_SHAPES = ("oval", "d", "round_rect")


# the mouth outline (body units) for visibility vis 0..1 and opening 0..1; empty when hidden
def mouth_shape(mouth, cx, cy, vis, opening):
    if vis < 0.03:
        return np.zeros((0, 2))
    w = mouth["w"] / 2 * (0.4 + 0.6 * vis)
    h = (mouth["h_closed"] + (mouth["h_open"] - mouth["h_closed"]) * min(max(opening, 0.0), 1.0)) / 2 * vis
    h = max(h, 0.004)
    if mouth["shape"] == "d":  # flat top, round bottom (an open "D" on its side)
        a = np.linspace(0, math.pi, 40)
        top = cy + h
        return np.concatenate([np.array([[-w + cx, top], [w + cx, top]]),
                               np.stack([cx + w * np.cos(a), top - 2 * h * np.sin(a)], 1)[1:-1]])
    if mouth["shape"] == "round_rect":
        return round_rect(cx, cy, w, h, min(w, h) * (1 + mouth.get("round", 0.5)) / 1.5)
    return ellipse(cx, cy, w, h, 64)


# a tapered bar with round ends: circle r0 at p0, circle r1 at p1 and their outer tangents
def taper(p0, p1, r0, r1, cap_n=14):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    d = p1 - p0
    length = max(float(np.hypot(*d)), 1e-9)
    ang = math.atan2(d[1], d[0])
    b = math.acos(min(1.0, max(-1.0, (r0 - r1) / length)))
    a1 = np.linspace(ang + b, ang - b, cap_n)
    a0 = np.linspace(ang - b, ang + b - math.tau, cap_n * 2)
    return np.concatenate([np.stack([p1[0] + r1 * np.cos(a1), p1[1] + r1 * np.sin(a1)], 1),
                           np.stack([p0[0] + r0 * np.cos(a0), p0[1] + r0 * np.sin(a0)], 1)])


# keep the part of a convex polygon where y <= y0 + slope * (x - x0) (Sutherland-Hodgman, one edge)
def clip_below(pts, x0, y0, slope):
    if len(pts) < 3:
        return pts
    f = y0 + slope * (pts[:, 0] - x0) - pts[:, 1]
    out = []
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        if f[i] >= 0:
            out.append(pts[i])
        if (f[i] >= 0) != (f[j] >= 0):
            w = f[i] / (f[i] - f[j])
            out.append(pts[i] + (pts[j] - pts[i]) * w)
    return np.array(out) if len(out) >= 3 else np.zeros((0, 2))


# heart outline, centred, width about 2 r (classic parametric heart)
def heart(cx, cy, r, n=72):
    a = np.linspace(0, math.tau, n, endpoint=False)
    x = 16 * np.sin(a) ** 3
    y = 13 * np.cos(a) - 5 * np.cos(2 * a) - 2 * np.cos(3 * a) - np.cos(4 * a)
    k = r / 16.5
    return np.stack([cx + x * k, cy + (y + 2.5) * k], 1)


# star with `points` tips (outer radius r, inner radius r * inner), one tip up
def star(cx, cy, r, points=5, inner=0.45):
    a = math.pi / 2 + np.arange(2 * points) * math.pi / points
    rr = np.where(np.arange(2 * points) % 2 == 0, r, r * inner)
    return np.stack([cx + rr * np.cos(a), cy + rr * np.sin(a)], 1)


# four-point sparkle with concave sides (superellipse with exponent > 2)
def sparkle(cx, cy, r, p=2.7, n=64):
    a = np.linspace(0, math.tau, n, endpoint=False)
    c, s = np.cos(a), np.sin(a)
    return np.stack([cx + r * np.sign(c) * np.abs(c) ** p, cy + r * np.sign(s) * np.abs(s) ** p], 1)


def _rotate(pts, ang, cx=0.0, cy=0.0):
    c, s = math.cos(ang), math.sin(ang)
    q = pts - [cx, cy]
    return np.stack([q[:, 0] * c - q[:, 1] * s, q[:, 0] * s + q[:, 1] * c], 1) + [cx, cy]


def _bar(a, b, hw):
    return stroke(np.array([a, b], float) + [[0, 0], [1e-6, 1e-6]], hw)


def _question(cx=0.0, cy=0.0, k=1.0):
    a = np.radians(np.linspace(160, -50, 30))
    arc = np.stack([0.19 * np.cos(a), 0.17 + 0.19 * np.sin(a)], 1)
    tail = np.array([[0.04, -0.03], [0.0, -0.09], [0.0, -0.14]])
    line = np.concatenate([arc, tail]) * k + [cx, cy]
    return [stroke(line, 0.075 * k), ellipse(cx, cy - 0.36 * k, 0.085 * k, 0.085 * k, 32)]


def _exclaim(cx=0.0, cy=0.0, k=1.0):
    return [taper([cx, cy + 0.4 * k], [cx, cy - 0.15 * k], 0.1 * k, 0.055 * k),
            ellipse(cx, cy - 0.36 * k, 0.085 * k, 0.085 * k, 32)]


def _z(cx, cy, s, hw):
    h = s / 2
    return [_bar((cx - h, cy + h), (cx + h, cy + h), hw), _bar((cx + h, cy + h), (cx - h, cy - h), hw),
            _bar((cx - h, cy - h), (cx + h, cy - h), hw)]


# one emote glyph at time dt since it appeared: [(Nx2 points, role)] in glyph units (height ~1, centre 0, y up).
# role "main" uses the emote's colour, "body" the mascot colour. The number of parts never changes with dt.
def emote_glyph(name, dt=1.0):
    main = []
    if name == "question":
        main = _question()
    elif name == "exclaim":
        main = _exclaim()
    elif name == "interrobang":
        main = _question(-0.15, 0.0, 0.9) + _exclaim(0.24, 0.0, 0.9)
    elif name == "sweat":
        r, a = 0.22, np.radians(np.linspace(30, -210, 48))
        drop = np.concatenate([np.stack([r * np.cos(a), -0.12 + r * np.sin(a)], 1), [[0.0, -0.12 + 2 * r]]])
        main = [drop - [0, 0.06 * min(dt, 1.5)]]  # slides down a little
    elif name == "heart":
        beat = 1 + 0.08 * max(0.0, math.sin(math.tau * 1.4 * dt)) ** 4
        main = [heart(0, 0, 0.45 * beat)]
    elif name == "sparkle":
        main = [sparkle(x, y, r * (1 + 0.18 * math.sin(math.tau * 1.3 * dt + ph)))
                for x, y, r, ph in ((-0.05, 0.0, 0.36, 0.0), (0.33, 0.3, 0.15, 2.0), (-0.32, -0.3, 0.12, 4.0))]
    elif name == "anger":
        pulse = 1 + 0.07 * math.sin(math.tau * 2.0 * dt)
        for qx, qy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
            c = np.array([qx, qy]) * 0.36 * pulse
            mid = math.atan2(-qy, -qx)
            a = np.linspace(mid - math.radians(62), mid + math.radians(62), 20)
            main.append(stroke(np.stack([c[0] + 0.26 * np.cos(a), c[1] + 0.26 * np.sin(a)], 1), 0.065))
    elif name == "idea":
        parts = [(ellipse(0, 0.1, 0.3, 0.3, 64), "main"), (ellipse(0, 0.1, 0.22, 0.22, 64), "body"),
                 (stadium(0, -0.27, 0.15, 0.05), "main"), (stadium(0, -0.38, 0.11, 0.045), "main")]
        glow = 0.04 * math.sin(math.tau * 1.2 * dt)
        for deg in (35, 90, 145):
            u = np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg))])
            parts.append((_bar(u * (0.4 + glow) + [0, 0.1], u * (0.52 + glow) + [0, 0.1], 0.035), "main"))
        return parts
    elif name == "zzz":
        for i, (x, y, s) in enumerate(((-0.38, -0.34, 0.2), (0.0, -0.03, 0.26), (0.4, 0.32, 0.32))):
            g = ease((dt - 0.25 * i) / 0.25)  # the z's appear one after another
            rise = 0.05 * math.sin(math.tau * 0.7 * dt + i)
            main += _z(x, y + rise, max(s * g, 1e-3), max(0.055 * s / 0.3 * g, 1e-4))
    elif name == "dots":
        for i in range(3):
            hop = 0.08 * max(0.0, math.sin(math.tau * (1.1 * dt - 0.18 * i)))
            main.append(ellipse(-0.3 + 0.3 * i, -0.1 + hop, 0.085, 0.085, 32))
    elif name == "check":
        main = [_bar((-0.32, 0.0), (-0.08, -0.26), 0.08), _bar((-0.08, -0.26), (0.36, 0.3), 0.08)]
    elif name == "cross":
        main = [_bar((-0.27, 0.27), (0.27, -0.27), 0.08), _bar((-0.27, -0.27), (0.27, 0.27), 0.08)]
    elif name == "music":
        sway = math.radians(8) * math.sin(math.tau * 0.9 * dt)
        flag = np.array([[0.04, 0.36], [0.14, 0.28], [0.22, 0.17], [0.23, 0.04]])
        main = [_rotate(ellipse(-0.1, -0.27, 0.15, 0.105, 48), math.radians(20), -0.1, -0.27),
                _bar((0.03, -0.25), (0.03, 0.36), 0.04), stroke(flag, 0.04)]
        main = [_rotate(p, sway, 0, -0.27) for p in main]
    else:
        raise ValueError(f"emote 要是 {'、'.join(EMOTES)} 其中之一：{name}")
    return [(p, "main") for p in main]


# emotes placed next to the body: [(name, points in body units, (r, g, b, alpha))]; emotes is MascotState.emotes
def emote_shapes(spec, emotes):
    m = motion(spec)
    amber = registry.hex_rgb(spec["color"])
    out = []
    for i, (name, dt, s, alpha, side) in enumerate(emotes):
        ax, ay = m["emote_at"]
        ay += m["emote_bob"] * math.sin(math.tau * dt / m["emote_bob_period"])
        k = m["emote_size"] * s
        col = emote_color(spec, name)
        a = int(round(255 * min(max(alpha, 0.0), 1.0)))
        for j, (pts, role) in enumerate(emote_glyph(name, dt)):
            rgb = amber if role == "body" else col
            out.append((f"emote{i}:{name}:{j}", pts * k + [side * ax, ay], rgb + (a,)))
    return out


def shapes(spec, pose):
    """[(name, Nx2 points, colour)] in drawing order: body, ray0..n-1, blush_l, blush_r, eye_l, eye_r, pupil_l,
    pupil_r, mouth. Colours are (r, g, b), or (r, g, b, alpha 0..255) for the translucent blush.

    The list always has the same names; a hidden pupil, blush or mouth has an empty point array."""
    g, m = geometry(spec), motion(spec)
    amber, white, dark = (registry.hex_rgb(spec[k]) for k in ("color", "eye", "pupil"))
    n = int(g["rays"])
    out = [("body", ellipse(0, 0, g["body_r"], g["body_r"], 160), amber)]

    for k in range(n):
        ext = pose.rays[k] if k < len(pose.rays) else 0.0
        a = ray_angle(n, k) + pose.ring_rot + (pose.ray_rot[k] if k < len(pose.ray_rot) else 0.0)
        if pose.droop:
            a -= pose.droop * math.cos(a)  # the side notches hang down (or lift, when negative)
        hw = g["ray_width"] * (1 + (m["point_thicken"] - 1) * ext) / 2
        inner = g["ray_inner"] + pose.ray_out
        rest = g["ray_outer"] + pose.ray_out + (g["ray_outer"] - g["ray_inner"]) * pose.ray_len
        rest = max(rest, inner + 2 * hw + 0.02)
        outer = rest + (m["point_reach"] - rest) * ext
        u = np.array([math.cos(a), math.sin(a)])
        if pose.ray_sharp > 1e-3:
            tip = hw * (1 - 0.75 * min(pose.ray_sharp, 1.0))
            out.append((f"ray{k}", taper(u * (inner + hw), u * (outer - tip), hw, tip), amber))
        else:
            out.append((f"ray{k}", stroke([u * (inner + hw), u * (outer - hw)], hw), amber))

    blush_rgb, blush_op = blush_color(spec)
    bx, by, brx, bry = m["blush"]
    ba = int(round(255 * blush_op * min(max(pose.blush, 0.0), 1.0)))
    for side in (-1, 1):
        pts = ellipse(side * bx + pose.look_x * 0.3, by, brx, bry, 48) if ba > 2 else np.zeros((0, 2))
        out.append(("blush_l" if side < 0 else "blush_r", pts, blush_rgb + (ba,)))

    line_hw = m["eye_line"] * g["eye_r"]
    arc_r = m["happy_arc_r"] * g["eye_r"]
    half_span = math.radians(m["happy_arc_span"]) / 2
    closed_w = arc_r * math.sin(half_span) + line_hw  # a closed eye is the flattened happy arc
    dot_open = pose.eye_open * (1 - ease(2 * pose.happy))  # happy: dot closes, then the arc opens
    arc_open = ease(2 * pose.happy - 1)
    special = max(pose.heart, pose.star)
    pupils = []
    for side in (-1, 1):
        asym = 1 + pose.eye_asym if side > 0 else 1 - 0.6 * pose.eye_asym
        r = g["eye_r"] * pose.eye_size * asym
        cx, cy = side * g["eye_dx"] + pose.look_x, g["eye_y"] + pose.look_y
        name = "eye_l" if side < 0 else "eye_r"
        if special > 0.5:  # heart / star eyes grow out of the shrunk dot
            q = ease(2 * special - 1) * m["shape_eye"] * r
            pts = heart(cx, cy, q) if pose.heart >= pose.star else star(cx, cy, q * 1.05)
            pts = np.stack([pts[:, 0], cy + (pts[:, 1] - cy) * max(pose.eye_open, 0.12)], 1)
            out.append((name, pts, white))
        elif pose.happy < 0.5:
            rx = closed_w + (r - closed_w) * dot_open
            ry = line_hw + (r * pose.eye_h - line_hw) * dot_open
            pts = _eye(cx, cy, rx, ry)
            if pose.lid > 1e-3 and dot_open > 0.3:
                # the lid cuts the top of the eye along a tilted line (inner corner = toward the face centre)
                slope = math.tan(pose.lid_tilt) * side
                pts = clip_below(pts, cx, cy + ry - 2 * ry * min(pose.lid, 0.9), slope)
            if special > 1e-3:
                pts = (pts - [cx, cy]) * max(1 - 2 * special, 0.0) + [cx, cy]
                if 1 - 2 * special < 0.05:
                    pts = np.zeros((0, 2))
            out.append((name, pts, white))
        else:
            a = np.linspace(math.pi / 2 + half_span, math.pi / 2 - half_span, 40)
            base = arc_r * math.cos(half_span)
            pts = np.stack([cx + arc_r * np.cos(a), cy + (arc_r * np.sin(a) - base) * arc_open - line_hw * 0.5], 1)
            out.append((name, stroke(pts, line_hw), white))
        pr = r * m["pupil_r"] * pose.pupil * min(dot_open, 1.0) * (1 - min(special * 2, 1.0))
        if pr > 1e-4:
            px, py = pose.pupil_x, pose.pupil_y
            reach = max(r * pose.eye_h * dot_open - pr - 0.12 * r, 0)
            pupils.append(ellipse(cx + px * reach, cy + py * reach, pr, pr, 48))
        else:
            pupils.append(np.zeros((0, 2)))
    out += [("pupil_l", pupils[0], dark), ("pupil_r", pupils[1], dark)]
    mo = m["mouth"]
    fl = mo.get("follow_look", 0.6)
    out.append(("mouth", mouth_shape(mo, pose.look_x * fl, mo["y"] + pose.look_y * fl, pose.mouth, pose.mouth_open), dark))

    tx, ty = pose.sx * pose.scale, pose.sy * pose.scale
    c, s = math.cos(pose.tilt), math.sin(pose.tilt)
    rot = np.array([[c, s], [-s, c]])  # row vectors: p @ rot rotates counter-clockwise by tilt
    shift = np.array([0.0, -pose.sink])
    return [(name, (pts * np.array([tx, ty])) @ rot + shift if len(pts) else pts, rgb) for name, pts, rgb in out]


# direction of the most extended notch as drawn: (index, (ux, uy) in screen orientation, +y down, extension)
def extended_notch(spec, pose):
    n = int(geometry(spec)["rays"])
    rays = _pad(pose.rays, (0.0,) * n)[0]
    k = max(range(n), key=lambda i: rays[i])
    pts = dict((nm, p) for nm, p, _ in shapes(spec, pose))[f"ray{k}"] + [0.0, pose.sink]  # from the body centre
    tip = pts[int(np.argmax(np.hypot(pts[:, 0], pts[:, 1])))]
    norm = float(np.hypot(*tip))
    return k, (float(tip[0]) / norm, -float(tip[1]) / norm), float(rays[k])


# degrees between a direction (screen orientation) from centre and the vector from centre to target
def angle_error(centre, direction, target):
    vx, vy = target[0] - centre[0], target[1] - centre[1]
    a = math.atan2(vy, vx) - math.atan2(direction[1], direction[0])
    return abs(math.degrees(math.remainder(a, math.tau)))


# ---------- PIL renderer ----------

def draw_pose(spec, pose, px, extent=None, ss=4, pad=0, shift=(0.0, 0.0), emotes=()):
    """Pose (+ emotes) -> RGBA image (px + 2*pad) square, transparent background, supersampled ss x then downsampled.
    The body centre sits at pad + shift + px/2 output pixels from the top-left (shift in [0, 1): sub-pixel moves).
    Opaque parts are filled directly; translucent groups (blush, fading emotes) are drawn on their own layer and
    composited, so overlapping parts of one group do not double their opacity."""
    extent = extent or view_extent(spec)
    size = px + 2 * pad
    big = size * ss
    amber = registry.hex_rgb(spec["color"])
    img = Image.new("RGBA", (big, big), amber + (0,))  # transparent amber: no dark fringe when resampling
    draw = ImageDraw.Draw(img)
    k = px * ss / (2 * extent)
    cx, cy = (pad + shift[0] + px / 2) * ss, (pad + shift[1] + px / 2) * ss
    items = shapes(spec, pose) + (emote_shapes(spec, emotes) if emotes else [])
    i = 0
    while i < len(items):
        name, pts, rgb = items[i]
        if len(rgb) == 3:
            if len(pts) >= 3:
                draw.polygon([(cx + x * k, cy - y * k) for x, y in pts], fill=rgb + (255,))
            i += 1
            continue
        group = name.rsplit(":", 1)[0]
        j = i
        while j < len(items) and len(items[j][2]) == 4 and items[j][0].rsplit(":", 1)[0] == group:
            j += 1
        alpha = rgb[3]
        polys = [(p, c) for _, p, c in items[i:j] if len(p) >= 3]
        if alpha > 0 and polys:
            layer = Image.new("RGBA", (big, big), tuple(polys[0][1][:3]) + (0,))
            ld = ImageDraw.Draw(layer)
            for p, c in polys:
                ld.polygon([(cx + x * k, cy - y * k) for x, y in p], fill=tuple(c[:3]) + (255,))
            if alpha < 255:
                layer.putalpha(layer.getchannel("A").point(lambda v: v * alpha // 255))
            img.alpha_composite(layer)
            draw = ImageDraw.Draw(img)
        i = j
    return img.resize((size, size), Image.LANCZOS)


# one still frame of a state; pose (from Timeline.pose_at) overrides state/dir
def render_frame(spec, state="idle", px=300, *, dir=None, pose=None, extent=None, ss=4, emotes=()):
    return draw_pose(spec, pose if pose is not None else target_pose(spec, state, dir), px, extent, ss, emotes=emotes)


# ---------- stickers and demo ----------

# sticker sections: (title, [(state, dir, emote)]); emotions show their companion emote, emotes sit on idle
STICKER_SECTIONS = [
    ("emotions", [("idle", None, None), ("happy", None, None), ("surprised", None, None), ("thinking", None, None)]
     + [(e, None, EMOTION_EMOTE.get(e)) for e in EMOTIONS]),
    ("emotes", [("idle", None, e) for e in EMOTES]),
    ("gestures", [("blink", None, None), ("look", "right", None), ("point", "up-right", None),
                  ("wave", "up-left", None), ("spin", None, None), ("squash", None, None), ("shiver", None, None),
                  ("jump", None, None), ("talking", None, None)]),
]
STICKERS = [(s, d) for _, items in STICKER_SECTIONS for s, d, e in items if e is None or s != "idle"]


def sticker_name(state, dir, emote=None):
    if emote and state == "idle":
        return f"emote_{emote}"
    return f"{state}_{dir.replace('-', '_')}" if dir else state


# a sticker's pose: a state's peak, or "talking" (idle with the mouth open)
def sticker_pose(spec, state, dir=None):
    if state == "talking":
        return replace(IDLE, mouth=1.0, mouth_open=0.8)
    return target_pose(spec, state, dir)


# an emote at full size, as it looks once popped in (all z's of zzz shown)
def sticker_emotes(emote):
    return ((emote, 1.0, 1.0, 1.0, 1),) if emote else ()


def _label_font(brand, size):
    for rel in brand.data.get("fonts", {}).get("en", []) + brand.data.get("fonts", {}).get("zh", []):
        p = Path(rel) if Path(rel).is_absolute() else brand.root / rel
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def write_stickers(brand_name, out_dir=None, px=512):
    brand = registry.load_brand(brand_name)
    spec = load_spec(brand_name)
    out_dir = Path(out_dir) if out_dir else brand.root / spec.get("stickers", "mascot/stickers")
    out_dir.mkdir(parents=True, exist_ok=True)
    cell, label_h, head_h, cols = 300, 40, 76, 7
    rows = [math.ceil(len(items) / cols) for _, items in STICKER_SECTIONS]
    sheet = Image.new("RGB", (cols * cell, sum(head_h + r * (cell + label_h) for r in rows)), (5, 5, 5))
    font, head = _label_font(brand, 26), _label_font(brand, 40)
    draw = ImageDraw.Draw(sheet)
    written, y0 = [], 0
    for (title, items), nrows in zip(STICKER_SECTIONS, rows):
        draw.text((24, y0 + 18), title, fill=registry.hex_rgb(spec["color"]), font=head)
        draw.line([(24, y0 + head_h - 8), (cols * cell - 24, y0 + head_h - 8)], fill=(70, 70, 70), width=2)
        for i, (state, dir, emote) in enumerate(items):
            name = sticker_name(state, dir, emote)
            pose, emotes = sticker_pose(spec, state, dir), sticker_emotes(emote)
            img = render_frame(spec, pose=pose, px=px, emotes=emotes)
            img.save(out_dir / f"{name}.png")
            written.append(out_dir / f"{name}.png")
            x, y = (i % cols) * cell, y0 + head_h + (i // cols) * (cell + label_h)
            small = render_frame(spec, pose=pose, px=cell, emotes=emotes)
            sheet.paste(small, (x, y), small)
            label = name.replace("emote_", "")
            tw = draw.textlength(label, font=font)
            draw.text((x + (cell - tw) / 2, y + cell - 4), label, fill=(200, 200, 200), font=font)
        y0 += head_h + nrows * (cell + label_h)
    sheet.save(out_dir / "sheet.png")
    return written + [out_dir / "sheet.png"]


# frames (RGBA images) -> video via ffmpeg; alpha=True writes a MOV with alpha (qtrle)
def encode(frames, n, px, out, alpha, background=(0, 0, 0)):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    codec = ["-c:v", "qtrle", "-pix_fmt", "argb"] if alpha else \
        ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", "-movflags", "+faststart"]
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba" if alpha else "rgb24",
           "-s", f"{px}x{px}", "-r", str(FPS), "-i", "-", "-frames:v", str(n), *codec, str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    bg = Image.new("RGB", (px, px), background)
    try:
        for img in frames:
            if alpha:
                proc.stdin.write(img.tobytes())
            else:
                frame = bg.copy()
                frame.paste(img, (0, 0), img)
                proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    proc.stderr.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg 失敗：{err.strip()}")
    return out


DEMO = [(0.0, "blink", None, None), (1.2, "look", "right", 1.2), (2.4, "surprised", None, 1.2),
        (3.6, "thinking", None, 1.2), (4.8, "point", "up-right", 1.2), (6.15, "squash", None, None),
        (7.2, "happy", None, 1.2)]


def write_demo(brand_name, out, px=1080, seconds=10.0):
    spec = load_spec(brand_name)
    events = [Event(t + (0.6 if do == "blink" else 0), do, d, h) for t, do, d, h in DEMO]
    tl = Timeline(spec, events, auto_blink=False)
    n = round(seconds * FPS)
    return encode((render_frame(spec, pose=tl.pose_at(i / FPS), px=px, ss=2) for i in range(n)), n, px, out, alpha=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="品牌角色：產生貼圖或預覽影片")
    ap.add_argument("--brand", default=DEFAULT_BRAND)
    ap.add_argument("--stickers", nargs="?", const="", metavar="DIR", help="每個表情一張 512×512 透明 PNG＋sheet.png")
    ap.add_argument("--demo", metavar="MP4", help="約 10 秒的預覽（黑底、H.264）")
    ap.add_argument("--px", type=int, default=1080, help="--demo 的邊長")
    args = ap.parse_args(argv)
    if args.stickers is None and not args.demo:
        ap.error("要給 --stickers 或 --demo")
    try:
        if args.stickers is not None:
            for p in write_stickers(args.brand, args.stickers or None):
                print(f"寫入 {p}")
        if args.demo:
            print(f"寫入 {write_demo(args.brand, args.demo, args.px)}")
    except (registry.ConfigError, RuntimeError, ValueError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
