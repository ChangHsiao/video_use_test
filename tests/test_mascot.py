"""Brand mascot (helpers/mascot.py, helpers/mascot_track.py) tests. No network."""

import json
import math
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

# helpers/ is not a package; mascot_track imports mascot/compose/registry by name, so use the same modules
sys.path.insert(0, str(Path(__file__).parents[1] / "helpers"))
import mascot as ms  # noqa: E402
import mascot_qa as qa  # noqa: E402
import mascot_track as mt  # noqa: E402
import registry  # noqa: E402

BRAND = "桑尼資料科學"
STYLE = "桑尼新聞短片"  # a style whose brand has a mascot


def cue(start, end, show):
    return {"seg": 0, "start": start, "end": end, "show": show, "say": show + "，", "en": None}


CUES = [cue(0.1, 0.4, "這是在程式裡"), cue(0.5, 0.9, "不是 0.3"), cue(1.0, 1.4, "而是這一長串"), cue(1.5, 1.8, "不是 0.3")]


class SpecTest(unittest.TestCase):
    def test_spec_from_brand_json(self):
        spec = ms.load_spec(BRAND)
        self.assertEqual(spec["color"].upper(), "#F59E0B")
        self.assertEqual(int(spec["geometry"]["rays"]), 8)
        self.assertEqual(spec["expressions"], ["idle", "blink", "look", "surprised", "thinking", "happy", "squash", "point",
                                               "wave", "spin", "shiver", "jump", *ms.EMOTIONS])
        self.assertEqual(spec["emotes"]["names"], list(ms.EMOTES))
        self.assertEqual(spec["motion"]["mouth"]["shape"], "d")
        for state in spec["expressions"]:
            self.assertIn(state, ms.STATES)

    def test_style_without_brand_is_a_clear_error(self):
        style = ms.registry.load_style("暗色科技風")
        with self.assertRaises(ms.registry.ConfigError):
            ms.spec_from_style(style)
        self.assertEqual(ms.spec_from_style(ms.registry.load_style(STYLE)), ms.load_spec(BRAND))


class RenderTest(unittest.TestCase):
    spec = ms.load_spec(BRAND)

    def test_every_state_renders(self):
        amber = np.array(ms.registry.hex_rgb(self.spec["color"]))
        for state in ms.STATES:
            with self.subTest(state=state):
                img = ms.render_frame(self.spec, state, 300, dir="right" if state in ("look", "point", "wave") else None)
                self.assertEqual((img.mode, img.size), ("RGBA", (300, 300)))
                a = np.asarray(img)
                for y, x in ((0, 0), (0, 299), (299, 0), (299, 299)):
                    self.assertEqual(a[y, x, 3], 0)
                opaque = a[a[..., 3] == 255][:, :3].astype(int)
                self.assertGreater((np.abs(opaque - amber).sum(1) < 6).sum(), 3000)
                if state not in ("blink",):
                    self.assertGreater((opaque.min(1) > 245).sum(), 20)  # white eyes

    def test_point_extends_the_notch_toward_dir(self):
        ext = ms.view_extent(self.spec)
        x = round(150 + 1.9 / ext * 150)  # 1.9 body units to the right: beyond the normal notch (1.48)
        idle = np.asarray(ms.render_frame(self.spec, "idle", 300))
        point = np.asarray(ms.render_frame(self.spec, "point", 300, dir="right"))
        self.assertEqual(idle[150, x, 3], 0)
        self.assertEqual(point[150, x, 3], 255)
        rays = dict((n, p) for n, p, _ in ms.shapes(self.spec, ms.target_pose(self.spec, "point", "right")))
        k = ms.nearest_ray(self.spec, "right")
        self.assertAlmostEqual(rays[f"ray{k}"][:, 0].max(), ms.motion(self.spec)["point_reach"], places=2)
        self.assertLess(np.abs(rays["ray0"]).max(), 1.5)  # the others stay short

    def test_timeline_returns_to_idle_and_blinks_are_seeded(self):
        tl = ms.Timeline(self.spec, [ms.Event(1.0, "surprised", hold=1.0)], seed=3, duration=20)
        self.assertEqual(tl.held_pose(1.5).eye_h, ms.motion(self.spec)["surprised_eye_h"])
        self.assertEqual(tl.held_pose(3.0), ms.IDLE)
        self.assertEqual(tl.blinks, ms.Timeline(self.spec, [ms.Event(1.0, "surprised", hold=1.0)], seed=3, duration=20).blinks)
        gaps = np.diff(tl.blinks)
        self.assertTrue(len(tl.blinks) >= 4 and gaps.min() >= 2.5)
        self.assertGreater(len(set(tl.blink_kinds.values())), 1)  # varied: single / double / slow / squint


def features(loud, gate, pitch=None, fps=30):
    loud, gate = np.asarray(loud, float), np.asarray(gate, float)
    return ms.VoiceFeatures(loud, np.full(len(loud), 0.5) if pitch is None else np.asarray(pitch, float), gate, fps)


HOME = (150, 1528, 300)
LANE = {"x": [110, 970], "y": [1470, 1600]}


class LiveTimelineTest(unittest.TestCase):
    spec = ms.load_spec(BRAND)

    @staticmethod
    def mouth_px(img):
        a = np.asarray(img).astype(int)
        dark = (a[..., 3] > 200) & (a[..., :3].max(2) < 40)
        return int(dark[a.shape[0] // 2:].sum())  # dark pixels in the lower half: the mouth

    def test_mouth_hidden_in_silence_and_open_when_loud(self):
        loud = np.r_[np.zeros(30), np.full(30, 1.0), np.zeros(30)]
        gate = np.r_[np.zeros(30), np.ones(30), np.zeros(30)]
        tl = ms.MascotTimeline(self.spec, [], features(loud, gate), home=HOME, lane=LANE, auto_blink=False)
        silent, talking = tl.state(0.5).pose, tl.state(1.5).pose
        self.assertEqual((silent.mouth, silent.mouth_open), (0.0, 0.0))
        self.assertEqual(len(dict((k, p) for k, p, _ in ms.shapes(self.spec, silent))["mouth"]), 0)
        self.assertEqual(self.mouth_px(tl.frame(0.5)[0]), 0)
        self.assertEqual(self.mouth_px(tl.frame(2.5)[0]), 0)  # hidden again after speech
        self.assertGreater(self.mouth_px(tl.frame(1.5)[0]), 150)
        self.assertGreater(talking.sy, silent.sy * 1.02)  # loud: slight stretch
        quiet = ms.MascotTimeline(self.spec, [], features(np.r_[np.zeros(30), np.full(30, 0.2), np.zeros(30)], gate),
                                  home=HOME, auto_blink=False)
        self.assertLess(self.mouth_px(quiet.frame(1.5)[0]), self.mouth_px(tl.frame(1.5)[0]) / 2)

    def test_mouth_shape_comes_from_motion(self):
        for shape in ms.MOUTH_SHAPES:
            spec = dict(self.spec, motion={"mouth": {"shape": shape}})
            mouth = dict((k, p) for k, p, _ in ms.shapes(spec, ms.Pose(mouth=1, mouth_open=1)))["mouth"]
            self.assertGreater(len(mouth), 3, shape)
            self.assertEqual(ms.motion(spec)["mouth"]["w"], ms.MOTION["mouth"]["w"])  # other mouth keys kept
        with self.assertRaises(ms.registry.ConfigError):
            ms._check_spec(dict(self.spec, motion={"mouth": {"shape": "star"}}), "test")

    def test_high_pitch_lifts_only_while_speaking(self):
        on = features(np.full(60, 0.5), np.ones(60), pitch=np.ones(60))
        off = features(np.full(60, 0.5), np.zeros(60), pitch=np.ones(60))
        a = ms.MascotTimeline(self.spec, [], on, home=HOME, auto_blink=False).state(1.0)
        b = ms.MascotTimeline(self.spec, [], off, home=HOME, auto_blink=False).state(1.0)
        self.assertAlmostEqual(b.y - a.y, ms.motion(self.spec)["pitch_lift_px"], delta=1.5)
        self.assertNotEqual(a.pose.tilt, b.pose.tilt)

    def test_hop_reaches_target_and_rests_at_both_ends(self):
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "move", to=(800, 1500), move="hop")], home=HOME, lane=LANE,
                               auto_blink=False)
        self.assertEqual(tl.place(0.99)[:3], HOME)
        self.assertIsNone(tl.place(0.99)[3])
        self.assertEqual(tl.place(1.0 + ms.motion(self.spec)["hop"])[:3], (800.0, 1500.0, 300.0))
        self.assertIsNone(tl.place(5.0)[3])
        ys = [tl.place(1.0 + i / 100)[1] for i in range(61)]
        self.assertLess(min(ys), 1500 - 30)  # it rises
        self.assertGreaterEqual(min(ys), LANE["y"][0] - ms.motion(self.spec)["lane_rise_px"] - 1e-6)  # not into content
        sy = [tl.state(1.0 + i / 100).pose.sy for i in range(61)]
        self.assertLess(min(sy), 0.9)  # anticipation / landing squash
        self.assertEqual(tl.warnings, [])

    def test_to_is_clamped_into_the_lane_with_a_warning(self):
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "look", "up", to=(540, 800))], home=HOME, lane=LANE)
        self.assertEqual(tl.place(5.0)[:2], (540.0, 1470.0))
        self.assertEqual(len(tl.warnings), 1)
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "move", to="right"), ms.Event(3.0, "move", to="home", size=200)],
                               home=HOME, lane=LANE)
        self.assertEqual(tl.place(2.5)[:3], (970.0, 1528.0, 300.0))
        self.assertEqual(tl.place(5.0)[:3], HOME[:2] + (200.0,))
        self.assertEqual(tl.warnings, [])

    def test_glide_eyes_look_where_it_goes(self):
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "move", to="right")], home=HOME, lane=LANE, auto_blink=False)
        self.assertGreater(tl.state(1.4).pose.look_x, 0.05)
        self.assertAlmostEqual(tl.state(3.0).pose.look_x, 0.0)

    def test_gestures(self):
        m = ms.motion(self.spec)
        ev = [ms.Event(1.0, "surprised"), ms.Event(3.0, "point", "right", hold=1.0), ms.Event(5.0, "wave", "up-left"),
              ms.Event(7.0, "spin"), ms.Event(9.0, "shiver")]
        tl = ms.MascotTimeline(self.spec, ev, home=HOME, auto_blink=False)
        rest = tl.state(0.5)
        self.assertLess(min(tl.state(1.0 + i / 30).y for i in range(18)), rest.y - m["jump_height_px"] * 0.8)  # jump
        p = tl.state(3.6)
        self.assertLess(p.pose.tilt, rest.pose.tilt - 0.05)  # leans right
        self.assertGreater(p.x, rest.x + 4)
        k = ms.nearest_ray(self.spec, "up-left")
        rot = [tl.state(5.0 + i / 30).pose.ray_rot[k] for i in range(33)]
        self.assertGreater(max(rot), 0.2)
        self.assertLess(min(rot), -0.2)  # waggles both ways
        self.assertGreater(tl.state(7.0 + m["spin"] / 2).pose.ring_rot, 0.1)   # turning during the spin
        self.assertAlmostEqual(tl.state(8.0).pose.ring_rot % (math.tau / 8), 0.0)  # finished: notch indices unchanged
        xs = [tl.state(9.0 + i / 60).x for i in range(20)]
        self.assertGreater(max(xs) - min(xs), 6)
        self.assertAlmostEqual(tl.state(9.5).x, HOME[0], delta=0.01)

    def test_timeline_is_deterministic(self):
        f = features(np.abs(np.sin(np.arange(300) / 5)), np.ones(300), np.linspace(0, 1, 300))
        ev = [ms.Event(1.0, "happy"), ms.Event(2.0, "move", to="center", move="hop"), ms.Event(4.0, "blink")]
        a = ms.MascotTimeline(self.spec, ev, f, home=HOME, lane=LANE, seed=5, duration=10)
        b = ms.MascotTimeline(self.spec, ev, f, home=HOME, lane=LANE, seed=5, duration=10)
        for t in (0.3, 1.1, 2.3, 4.05, 7.7):
            self.assertEqual(a.key(t, 0.5), b.key(t, 0.5))
            self.assertEqual(a.frame(t, 0.5)[0].tobytes(), b.frame(t, 0.5)[0].tobytes())

    def test_frame_size_follows_display_size(self):
        tl = ms.MascotTimeline(self.spec, [], home=HOME, auto_blink=False)
        for scale in (0.5, 1.0):
            img, cx, cy = tl.frame(0.0, scale)
            r = HOME[2] * scale / (2 * ms.motion(self.spec)["size_extent"])
            area = int((np.asarray(img)[..., 3] > 128).sum())
            self.assertAlmostEqual(area / (math.pi * r * r), 1.07, delta=0.12)  # body + notches
            self.assertEqual(round(cx), round(HOME[0] * scale))


class TrackTest(unittest.TestCase):
    def test_events_resolve_in_order(self):
        plan = {"mascot": {"events": [
            {"at": "不是 0.3", "do": "surprised"},
            {"at": "長串", "do": "point", "dir": "right", "offset": 0.2, "hold": 0.5},
            {"at": "不是 0.3", "do": "squash"}]}}
        got = [(e.t, e.do, e.dir, idx) for e, idx in mt.resolve_events(plan, CUES)]
        self.assertEqual(got, [(0.5, "surprised", None, 1), (1.2, "point", "right", 2), (1.5, "squash", None, 3)])
        with self.assertRaises(mt.TrackError):
            mt.resolve_events({"mascot": {"events": [{"at": "沒有這句", "do": "happy"}]}}, CUES)

    def test_two_second_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            (edit / "voice").mkdir()
            sr = 16000
            t = np.arange(int(0.5 * sr)) / sr
            with wave.open(str(edit / "voice" / "a.wav"), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
                w.writeframes((np.sin(2 * np.pi * 220 * t) * 12000).astype("<i2").tobytes())
            (edit / "voice_lines.json").write_text(json.dumps({"segments": [{"audio": "voice/a.wav", "start": 0.0}]}), "utf-8")
            (edit / "cues.json").write_text(json.dumps(CUES, ensure_ascii=False), "utf-8")
            plan = {"style": STYLE, "mascot": {"events": [{"at": "這是在程式裡", "do": "happy", "hold": 0.5},
                                                           {"at": "而是這一長串", "do": "squash"}]}}
            (edit / "合成.json").write_text(json.dumps(plan, ensure_ascii=False), "utf-8")
            out, resolved, *_ = mt.build(edit / "合成.json")
            self.assertEqual(out, edit / "mascot" / "track.mov")
            probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height,pix_fmt,nb_read_frames,r_frame_rate", "-of", "json", str(out)],
                                   capture_output=True, text=True, check=True)
            s = json.loads(probe.stdout)["streams"][0]
            self.assertEqual((s["width"], s["height"]), (300, 300))
            self.assertEqual(int(s["nb_read_frames"]), 60)
            self.assertEqual(s["r_frame_rate"], "30/1")
            self.assertIn("a", s["pix_fmt"].replace("yuv", ""))  # argb / rgba: has alpha

    def test_loudness_is_zero_in_silence_and_rises_with_voice(self):
        sr = mt.SR
        x = np.zeros(sr * 2, np.float32)
        x[sr // 2:sr] = 0.3 * np.sin(np.arange(sr // 2) * 0.1)
        lv = mt.loudness(x, 60, 0.12)
        self.assertEqual(lv[5], 0.0)
        self.assertGreater(lv[28], 0.8)
        self.assertLess(lv[59], 0.05)



class SpinThenPointTest(unittest.TestCase):
    """2026-11-22: three happy spins (90 deg each) left the ring at 270 deg, so a later point("up-right")
    extended the notch that had rotated to down-right. Finished spins must not shift the notch indices."""

    def test_point_after_spins_faces_dir(self):
        import math
        spec = ms.spec_from_brand(registry.load_brand("桑尼資料科學"))
        ev = [ms.Event(1.0, "happy", None, 1.0), ms.Event(3.0, "happy", None, 1.0), ms.Event(5.0, "happy", None, 1.0),
              ms.Event(8.0, "point", "up-right", 2.0)]
        tl = ms.MascotTimeline(spec, ev, None, home=(540, 1500, 300), auto_blink=False)
        pose = tl.state(9.0).pose
        n = len(pose.rays)
        k = max(range(n), key=lambda i: pose.rays[i])
        a = ms.ray_angle(n, k) + pose.ring_rot
        self.assertGreater(math.cos(a), 0.5)   # right
        self.assertGreater(math.sin(a), 0.5)   # up (maths orientation: +y is up)


# ---------- emotions, emotes, aiming at targets ----------

CIS = {"#FFFFFF", "#3B82F6", "#EF4444", "#10B981", "#BA4D43", "#F59E0B", "#7EEBD9", "#2C918C"}


class EmotionTest(unittest.TestCase):
    spec = ms.load_spec(BRAND)

    def test_every_emotion_is_a_distinct_held_state(self):
        poses = {}
        for e in ms.EMOTIONS:
            self.assertIn(e, ms.HELD)
            pose = ms.target_pose(self.spec, e)
            self.assertNotEqual(pose, ms.IDLE, e)
            poses[e] = pose
        self.assertEqual(len(set(poses.values())), len(poses))  # no two emotions look the same
        self.assertGreater(poses["joy"].scale, 1.0)
        self.assertGreater(poses["sad"].sink, 0)
        self.assertGreater(poses["angry"].lid_tilt, 0)   # inner corners low
        self.assertLess(poses["sad"].lid_tilt, 0)        # outer corners low
        self.assertEqual((poses["love"].heart, poses["excited"].star, poses["embarrassed"].blush), (1.0, 1.0, 1.0))

    def test_old_state_names_still_work(self):
        for s in ("idle", "look", "surprised", "thinking", "happy", "point", "blink", "squash", "wave", "spin",
                  "shiver", "jump"):
            ms.target_pose(self.spec, s, "right" if s in ("look", "point", "wave") else None)

    def test_lids_cut_the_eyes(self):
        def eye_top(pose):
            return dict((k, p) for k, p, _ in ms.shapes(self.spec, pose))["eye_l"][:, 1].max()
        self.assertLess(eye_top(ms.target_pose(self.spec, "sad")), eye_top(ms.IDLE) - 0.03)
        self.assertLess(eye_top(ms.target_pose(self.spec, "proud")), eye_top(ms.IDLE) - 0.03)

    def test_blush_is_translucent_featured_red(self):
        img = np.asarray(ms.render_frame(self.spec, "embarrassed", 400)).astype(int)
        red, op = ms.blush_color(self.spec)
        amber = np.array(ms.registry.hex_rgb(self.spec["color"]))
        want = amber * (1 - op) + np.array(red) * op
        near = (np.abs(img[..., :3] - want).sum(2) < 12) & (img[..., 3] == 255)
        self.assertGreater(int(near.sum()), 100)
        self.assertEqual(red, ms.registry.hex_rgb("#BA4D43"))

    def test_live_emotions_move(self):
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "angry", hold=2.0), ms.Event(5.0, "excited", hold=2.0),
                                           ms.Event(9.0, "worried", hold=2.0)], home=HOME, auto_blink=False)
        xs = [tl.state(1.5 + i / 30).x for i in range(15)]
        self.assertGreater(max(xs) - min(xs), 1.5)   # tremble
        ys = [tl.state(5.4 + i / 30).y for i in range(30)]
        self.assertGreater(max(ys) - min(ys), 6)     # bounces
        lx = [tl.state(9.3 + i / 10).pose.look_x for i in range(15)]
        self.assertGreater(max(lx), 0.03)
        self.assertLess(min(lx), -0.03)              # eyes look side to side
        self.assertEqual(tl.state(0.5).pose.lid, 0.0)


class EmoteTest(unittest.TestCase):
    spec = ms.load_spec(BRAND)

    def test_emote_colours_are_cis(self):
        for name in ms.EMOTES:
            self.assertIn("#%02X%02X%02X" % ms.emote_color(self.spec, name), CIS, name)
        self.assertEqual(ms.emote_color(self.spec, "sweat"), ms.registry.hex_rgb("#3B82F6"))
        self.assertEqual(ms.emote_color(self.spec, "check"), ms.registry.hex_rgb("#10B981"))

    def test_every_emote_renders_in_its_colour_above_right(self):
        idle = np.asarray(ms.render_frame(self.spec, "idle", 400))
        for name in ms.EMOTES:
            with self.subTest(name=name):
                img = np.asarray(ms.render_frame(self.spec, "idle", 400, emotes=((name, 1.0, 1.0, 1.0, 1),)))
                diff = np.abs(img.astype(int) - idle.astype(int)).sum(2) > 30
                ys, xs = np.nonzero(diff)
                self.assertGreater(len(xs), 150)
                self.assertGreater(xs.mean(), 200)   # right of the centre
                self.assertLess(ys.mean(), 200)      # above it
                col = np.array(ms.emote_color(self.spec, name))
                self.assertGreater(int((np.abs(img[..., :3].astype(int) - col).sum(2) < 10).sum()), 40)
                for k in (0.3, 2.0):  # the number of parts never changes over time
                    self.assertEqual(len(ms.emote_glyph(name, k)), len(ms.emote_glyph(name, 1.0)))

    def test_pop_in_timing(self):
        m = ms.motion(self.spec)
        a, b = m["emote_pop"]
        self.assertEqual(ms.emote_env(self.spec, 0.0, 1.0)[0], 0.0)
        self.assertAlmostEqual(ms.emote_env(self.spec, a, 1.0)[0], m["emote_overshoot"], places=3)
        self.assertAlmostEqual(b, 0.2)
        self.assertAlmostEqual(ms.emote_env(self.spec, b, 1.0)[0], 1.0)
        self.assertEqual(ms.emote_env(self.spec, 0.6, 1.0), (1.0, 1.0))
        s, alpha = ms.emote_env(self.spec, 1.0 + m["emote_fade"] / 2, 1.0)
        self.assertTrue(0 < alpha < 1 and s < 1)
        self.assertIsNone(ms.emote_env(self.spec, 1.0 + m["emote_fade"] + 0.01, 1.0))
        self.assertIsNone(ms.emote_env(self.spec, -0.01, 1.0))
        scales = [ms.emote_env(self.spec, i / 100, 1.0)[0] for i in range(0, 21)]
        self.assertGreater(max(scales), 1.05)  # overshoots, then settles

    def test_timeline_emotes(self):
        m = ms.motion(self.spec)
        ev = [ms.Event(1.0, "happy", emote="check"), ms.Event(4.0, "confused", hold=2.0),
              ms.Event(8.0, "move", emote="idea", emote_hold=0.5)]
        tl = ms.MascotTimeline(self.spec, ev, home=HOME, lane=LANE, auto_blink=False)
        self.assertEqual(tl.state(0.9).emotes, ())
        self.assertEqual([e[0] for e in tl.state(1.5).emotes], ["check"])
        self.assertEqual(tl.state(1.0 + m["emote_hold"] + m["emote_fade"] + 0.05).emotes, ())
        self.assertEqual([e[0] for e in tl.state(5.5).emotes], ["question"])  # confused brings "?"
        self.assertEqual(tl.state(8.3).emotes[0][0], "idea")
        self.assertEqual(tl.state(8.0 + 0.5 + m["emote_fade"] + 0.05).emotes, ())
        self.assertNotEqual(tl.key(1.5), tl.key(0.9))
        with self.assertRaises(ValueError):
            ms.MascotTimeline(self.spec, [ms.Event(1.0, "move", emote="banana")], home=HOME)

    def test_emote_stays_inside_the_frame(self):
        right = ms.MascotTimeline(self.spec, [ms.Event(0.0, "move", emote="exclaim")], home=(1030, 1540, 280),
                                  auto_blink=False)
        left = ms.MascotTimeline(self.spec, [ms.Event(0.0, "move", emote="exclaim")], home=(540, 1540, 280),
                                 auto_blink=False)
        self.assertEqual(right.state(0.5).emotes[0][4], -1)  # flips to up-left near the right edge
        self.assertEqual(left.state(0.5).emotes[0][4], 1)
        img = np.asarray(right.frame(0.5)[0])[..., 3] > 0
        ys, xs = np.nonzero(img)
        top = ys < img.shape[0] * 0.3
        self.assertLess(xs[top].mean(), img.shape[1] / 2)  # the emote is drawn up-left of the head

    def test_events_with_emote_and_target_resolve(self):
        plan = {"mascot": {"events": [{"at": "不是 0.3", "emote": "question"},
                                      {"at": "長串", "do": "point", "target": [700, 900], "emote": "exclaim",
                                       "emote_hold": 0.8}]}}
        got = [(e.do, e.emote, e.emote_hold, e.target) for e, _ in mt.resolve_events(plan, CUES)]
        self.assertEqual(got, [("move", "question", None, None), ("point", "exclaim", 0.8, (700.0, 900.0))])
        with self.assertRaises(mt.TrackError):
            mt.resolve_events({"mascot": {"events": [{"at": "長串", "do": "point", "target": [1]}]}}, CUES)


def notch_error(spec, tl, t, target):
    st = tl.state(t)
    _, d, ext = ms.extended_notch(spec, st.pose)
    return ms.angle_error((st.x, st.y), d, target), ext


class AimTest(unittest.TestCase):
    spec = ms.load_spec(BRAND)
    home = (540, 1540, 280)

    def test_sixteen_directions_near_and_far(self):
        talk = features(np.full(150, 0.6), np.ones(150), np.ones(150))  # talking: stretch, lift, tilt
        for r in (140, 420, 900):
            for i in range(16):
                a = i * math.tau / 16
                target = (self.home[0] + r * math.cos(a), self.home[1] - r * math.sin(a))
                tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "point", hold=2.0, target=target)], talk,
                                       home=self.home, auto_blink=False)
                for t in (1.5, 2.0, 2.9):
                    err, ext = notch_error(self.spec, tl, t, target)
                    with self.subTest(r=r, i=i, t=t):
                        self.assertGreater(ext, 0.99)
                        self.assertLess(err, 3.0)

    def test_target_overrides_dir(self):
        target = (200, 900)  # up-left, while dir says right
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "point", "right", hold=2.0, target=target)], home=self.home,
                               auto_blink=False)
        err, _ = notch_error(self.spec, tl, 2.0, target)
        self.assertLess(err, 3.0)
        st = tl.state(2.0)
        self.assertLess(st.pose.look_x, 0)
        self.assertGreater(st.pose.look_y, 0)   # eyes look up-left too
        self.assertLess(st.x, self.home[0])     # leans toward it
        plain = ms.MascotTimeline(self.spec, [ms.Event(1.0, "point", "right", hold=2.0)], home=self.home,
                                  auto_blink=False)
        _, d, _ = ms.extended_notch(self.spec, plain.state(2.0).pose)
        self.assertGreater(d[0], 0.9)           # dir still works without a target

    def test_point_after_spins_and_a_move_aims_right(self):
        target = (900, 1000)
        ev = [ms.Event(1.0, "happy", hold=1.0), ms.Event(3.0, "happy", hold=1.0), ms.Event(5.0, "spin"),
              ms.Event(7.0, "point", hold=2.0, to=(300, 1540), target=target)]
        tl = ms.MascotTimeline(self.spec, ev, home=self.home, lane=LANE, auto_blink=False)
        err, _ = notch_error(self.spec, tl, 8.4, target)  # after the glide to x 300
        self.assertLess(err, 3.0)

    def test_look_target(self):
        target = (900, 1200)
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "look", hold=2.0, target=target)], home=self.home,
                               auto_blink=False)
        st = tl.state(2.0)
        self.assertLess(ms.angle_error((st.x, st.y), (st.pose.look_x, -st.pose.look_y), target), 3.0)

    def test_qa_angle_catches_a_20_degree_miss(self):
        centre, target = (540, 1540), (840, 1240)
        good = (math.cos(math.radians(-45)), math.sin(math.radians(-45)))
        miss = (math.cos(math.radians(-25)), math.sin(math.radians(-25)))
        self.assertLess(qa.aim_error(centre, good, target), 0.01)
        self.assertAlmostEqual(qa.aim_error(centre, miss, target), 20.0, places=6)
        self.assertGreater(qa.aim_error(centre, miss, target), qa.ANGLE_FAIL)
        # a mascot pointing by dir (right) at a target 20 degrees above that fails the same check
        target = (540 + 500 * math.cos(math.radians(20)), 1540 - 500 * math.sin(math.radians(20)))
        tl = ms.MascotTimeline(self.spec, [ms.Event(1.0, "point", "right", hold=2.0)], home=self.home,
                               auto_blink=False)
        err, _ = notch_error(self.spec, tl, 2.0, target)
        self.assertGreater(err, qa.ANGLE_FAIL)


if __name__ == "__main__":
    unittest.main()
