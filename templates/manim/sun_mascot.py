"""SunMascot: the brand mascot as a Manim Community VGroup (no LaTeX).

Geometry, colours and motion come from brands/<brand>/brand.json "mascot" through helpers/mascot.py
(the same shapes() the PIL renderer and helpers/mascot_track.py draw), so the Manim mascot and the
video track are pixel-for-pixel the same character. Usage rules: brands/桑尼資料科學/mascot/MASCOT.md.

Usage (run Manim from anywhere; this file finds the repo's helpers/ by its own path):

    import sys; sys.path.insert(0, r"<repo>/templates/manim")
    from manim import *
    from sun_mascot import SunMascot

    class Demo(Scene):
        def construct(self):
            sun = SunMascot(size=0.6).to_corner(DL)   # size = body radius in Manim units
            self.add(sun)
            self.play(sun.idle(1.5))                  # breathing + seeded blinks
            self.play(sun.look("right"))
            self.play(sun.surprised()); self.wait(0.8)
            self.play(sun.thinking()); self.wait(0.8)
            self.play(sun.point("up-right")); self.wait(0.8)
            self.play(sun.to_idle())                  # held states stay until to_idle() (point retracts)
            self.play(sun.squash())                   # one-shot: squash and ease back
            self.play(sun.happy()); self.play(sun.blink())
            self.play(sun.talk([0.2, 0.9, 0.4, 1.0, 0.1], run_time=1.0))   # mouth follows a loudness envelope
            self.play(sun.wave("up-left")); self.play(sun.spin()); self.play(sun.shiver()); self.play(sun.jump())

Methods return animations: blink(kind), look(dir), surprised(), thinking(), happy(), squash(), point(dir),
to_idle(), idle(run_time), talk(loudness, run_time), wave(dir), spin(), shiver(), jump(height),
emotion(name) (joy, sad, angry, worried, confused, proud, love, sleepy, excited, embarrassed) and
emote(name, hold) (question, exclaim, interrobang, sweat, heart, sparkle, anger, idea, zzz, dots, check,
cross, music: pops up next to the head, then fades; play it together with an emotion via AnimationGroup).
dir is one of right/left/up/down/up-right/up-left/down-right/down-left. talk() shows the mouth only
while it runs (the brand rule: mouth only while the narrator speaks); loudness is one value 0..1 or a
list of values spread over run_time (e.g. a per-frame envelope from mascot.voice_features).
Held states take the brand's transition time (0.25 s) with ease in/out; move/scale the mascot with
the usual Mobject methods (move_to, shift, scale, to_corner).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from manim import Animation, VGroup, VMobject, Square, linear

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "helpers"))
import mascot as M  # noqa: E402


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


def _opacity(rgb):
    return rgb[3] / 255 if len(rgb) == 4 else 1.0


class SunMascot(VGroup):
    def __init__(self, brand=M.DEFAULT_BRAND, size=0.5, **kwargs):
        super().__init__(**kwargs)
        self.spec = M.load_spec(brand)
        self.motion = M.motion(self.spec)
        self.pose = M.IDLE
        self.state = "idle"
        # invisible frame that follows move/scale: its centre and width define where the mascot is drawn
        self._anchor = Square(side_length=2 * size).set_stroke(opacity=0).set_fill(opacity=0)
        self.add(self._anchor)
        self.parts = {}
        for name, _, rgb in M.shapes(self.spec, self.pose):
            part = VMobject(stroke_width=0).set_fill(_hex(rgb), opacity=1)
            self.parts[name] = part
            self.add(part)
        self.set_pose(self.pose)

    def set_pose(self, pose):
        self.pose = pose
        centre = self._anchor.get_center()
        k = self._anchor.width / 2
        for name, pts, rgb in M.shapes(self.spec, pose):
            part = self.parts[name]
            if len(pts) < 3:
                part.set_points_as_corners([centre, centre]).set_fill(opacity=0)
                continue
            p3 = np.column_stack([pts * k, np.zeros(len(pts))]) + centre
            part.set_points_as_corners([*p3, p3[0]]).set_fill(opacity=_opacity(rgb))
        return self

    # ----- animations -----

    def _to(self, state, dir=None, run_time=None):
        self.state = state
        return _PoseAnim(self, [(1.0, M.target_pose(self.spec, state, dir))],
                         run_time=run_time or self.motion["transition"])

    def to_idle(self, run_time=None):
        return self._to("idle", run_time=run_time)

    def look(self, dir="right", run_time=None):
        return self._to("look", dir, run_time)

    def surprised(self, run_time=None):
        return self._to("surprised", run_time=run_time)

    def thinking(self, run_time=None):
        return self._to("thinking", run_time=run_time)

    def happy(self, run_time=None):
        return self._to("happy", run_time=run_time)

    def point(self, dir="up-right", run_time=None):
        return self._to("point", dir, run_time)

    # an emotion (joy, sad, angry, worried, confused, proud, love, sleepy, excited, embarrassed); held until
    # the next state. Live-only motion (tremble, bounce) and companion emotes are not added here: use emote()
    def emotion(self, name, run_time=None):
        if name not in M.EMOTIONS:
            raise ValueError(f"emotion 要是 {'、'.join(M.EMOTIONS)} 其中之一：{name}")
        return self._to(name, run_time=run_time)

    # an emote (question, exclaim, ..., see mascot.EMOTES) pops up next to the head, stays hold seconds, fades
    def emote(self, name, hold=None, side=1):
        return _EmoteAnim(self, name, self.motion["emote_hold"] if hold is None else hold, side)

    def blink(self, kind="single"):
        return _OverlayAnim(self, M.blink_length(self.spec, kind), lambda dt: dict(blink=M.blink_amount(self.spec, kind, dt)))

    def squash(self):
        return _OverlayAnim(self, self.motion["squash_in"] + self.motion["squash_out"],
                            lambda dt: dict(squash=M.squash_env(self.spec, dt)))

    # breathing + seeded varied blinks around the current held pose
    def idle(self, run_time=2.0, seed=0):
        tl = M.Timeline(self.spec, seed=seed, duration=run_time)
        return _OverlayAnim(self, run_time, lambda dt: dict(blink=tl.blink_at(dt), t=dt, breathe=True))

    # mouth open with loudness (one value or an envelope spread over run_time); hidden again at the end
    def talk(self, loudness=0.7, run_time=1.0):
        env = np.atleast_1d(np.asarray(loudness, float))
        m = self.motion

        def pose(base, dt):
            u = dt / run_time
            x = float(np.interp(u * (len(env) - 1), np.arange(len(env)), env)) if len(env) > 1 else float(env[0])
            vis = min(1.0, dt / 0.08, (run_time - dt) / 0.08)
            return replace(base, mouth=max(vis, 0.0), mouth_open=x,
                             sy=base.sy * (1 + m["talk_stretch"] * x), sx=base.sx * (1 - m["talk_stretch"] * x / 2))
        return _PoseFnAnim(self, run_time, pose)

    # one notch extends and waggles (wave_times times)
    def wave(self, dir="up-right", run_time=None):
        k, n = M.nearest_ray(self.spec, dir), int(M.geometry(self.spec)["rays"])
        m = self.motion
        rt = run_time or m["wave"]

        def pose(base, dt):
            u = dt / rt
            env = M.ease(u / 0.15) * M.ease((1 - u) / 0.2)
            rays = list(M._pad(base.rays, (0.0,) * n)[0])
            rot = list(M._pad(base.ray_rot, (0.0,) * n)[0])
            rays[k] = max(rays[k], m["wave_reach"] * env)
            rot[k] += np.radians(m["wave_deg"]) * np.sin(2 * np.pi * m["wave_times"] * u) * env
            return replace(base, rays=tuple(rays), ray_rot=tuple(rot))
        return _PoseFnAnim(self, rt, pose)

    # the notch ring turns spin_deg (the ring looks the same before and after)
    def spin(self, run_time=None):
        rt = run_time or self.motion["spin"]
        deg = np.radians(self.motion["spin_deg"])
        return _PoseFnAnim(self, rt, lambda base, dt: replace(base, ring_rot=base.ring_rot + deg * M.ease(dt / rt)))

    # fast small horizontal jitter with a squint; amplitude in Manim units (default: shiver_px of a 300 px mascot)
    def shiver(self, amplitude=None, run_time=None):
        m = self.motion
        rt = run_time or m["shiver"]
        amp = amplitude if amplitude is not None else self._px(m["shiver_px"])

        def offset(dt):
            u = dt / rt
            return np.array([amp * np.sin(2 * np.pi * m["shiver_hz"] * dt) * (1 - u), 0, 0])
        return _PoseFnAnim(self, rt, lambda base, dt: replace(base, eye_open=base.eye_open * (1 - 0.4 * np.sin(np.pi * dt / rt))),
                           offset)

    # jump up and down in place with anticipation and landing squash; height in Manim units
    def jump(self, height=None, run_time=None):
        m = self.motion
        rt = run_time or m["jump"]
        h = height if height is not None else self._px(m["jump_height_px"])

        def pose(base, dt):
            _, _, sx, sy = M.leap(self.spec, dt / rt, ant=0.14, land=0.26)
            return replace(base, sx=base.sx * sx, sy=base.sy * sy)
        return _PoseFnAnim(self, rt, pose, lambda dt: np.array([0, h * M.leap(self.spec, dt / rt, ant=0.14, land=0.26)[1], 0]))

    # display px (1080x1920, at a 300 px home size) -> Manim units for this mascot's size
    def _px(self, px):
        body_r = self._anchor.width / 2
        return px / (300 / (2 * self.motion["size_extent"])) * body_r


class _EmoteAnim(Animation):
    """An emote glyph (mascot.emote_glyph) placed like mascot.emote_shapes, popping in and fading out."""

    def __init__(self, sun, name, hold, side):
        self.sun, self.emote_name, self.hold, self.side = sun, name, hold, side  # Animation owns .name
        self.group = VGroup(*[VMobject(stroke_width=0) for _ in M.emote_glyph(name)])
        sun.add(self.group)
        super().__init__(self.group, run_time=hold + sun.motion["emote_fade"], rate_func=linear)

    def interpolate_mobject(self, alpha):
        dt = alpha * self.run_time
        env = M.emote_env(self.sun.spec, dt, self.hold) if alpha < 1 else None
        centre, k = self.sun._anchor.get_center(), self.sun._anchor.width / 2
        if env is None:
            for part in self.group:
                part.set_points_as_corners([centre, centre]).set_fill(opacity=0)
            return
        for part, (_, pts, rgb) in zip(self.group, M.emote_shapes(self.sun.spec, ((self.emote_name, dt, env[0], env[1], self.side),))):
            p3 = np.column_stack([pts * k, np.zeros(len(pts))]) + centre
            part.set_points_as_corners([*p3, p3[0]]).set_fill(_hex(rgb), opacity=_opacity(rgb))

    def clean_up_from_scene(self, scene):
        super().clean_up_from_scene(scene)
        self.sun.remove(self.group)


class _PoseAnim(Animation):
    """Ease from the mascot's current pose through keyframes [(fraction, Pose)]."""

    def __init__(self, sun, keys, **kwargs):
        self.sun, self.keys = sun, keys
        super().__init__(sun, rate_func=linear, **kwargs)

    def begin(self):
        self.start = self.sun.pose
        super().begin()

    def interpolate_mobject(self, alpha):
        frm, f0 = self.start, 0.0
        for f1, tgt in self.keys:
            if alpha <= f1:
                self.sun.set_pose(M.lerp_pose(frm, tgt, M.ease((alpha - f0) / max(f1 - f0, 1e-9))))
                return
            frm, f0 = tgt, f1
        self.sun.set_pose(frm)


class _PoseFnAnim(Animation):
    """One-shot: pose_fn(base pose, dt) on top of the held pose, optional offset_fn(dt) moving the mascot;
    ends exactly on the held pose and position."""

    def __init__(self, sun, run_time, pose_fn, offset_fn=None):
        self.sun, self.pose_fn, self.offset_fn = sun, pose_fn, offset_fn
        super().__init__(sun, run_time=run_time, rate_func=linear)

    def begin(self):
        self.base, self.centre = self.sun.pose, self.sun._anchor.get_center().copy()
        super().begin()

    def interpolate_mobject(self, alpha):
        dt = alpha * self.run_time
        if self.offset_fn is not None:
            self.sun._anchor.move_to(self.centre + (self.offset_fn(dt) if alpha < 1 else 0))
        self.sun.set_pose(self.pose_fn(self.base, dt) if alpha < 1 else self.base)


class _OverlayAnim(Animation):
    """One-shot overlay (blink, squash, breathing) on top of the held pose; ends on the held pose."""

    def __init__(self, sun, run_time, overlay):
        self.sun, self.overlay = sun, overlay
        super().__init__(sun, run_time=run_time, rate_func=linear)

    def begin(self):
        self.base = self.sun.pose
        super().begin()

    def interpolate_mobject(self, alpha):
        kw = dict(breathe=False)
        kw.update(self.overlay(alpha * self.run_time))
        self.sun.set_pose(M.apply_overlays(self.sun.spec, self.base, **kw) if alpha < 1 else self.base)
