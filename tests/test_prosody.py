"""prosody.py（配音韻律處理）和 vocal_qc.py 斷點量測的測試：用合成的假聲音，不呼叫 ElevenLabs。

2026-11-22 一支 3b1b 測試片的配音被聽出「卡一下、像訊號突然消失」。量測結果：原始 TTS 每分鐘約 35 個斷點，
逐逗號切的韻律處理約 70 個；改成只在句子之間切、加小房間尾巴之後約 2 個。這裡把那次的修法固定下來。
需要 soundfile：uv run --extra news python -m unittest tests.test_prosody
"""

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

HELPERS = Path(__file__).resolve().parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))


def load(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pr = load("prosody")
qc = load("vocal_qc")
SR = pr.SR


def voiced(sec, freq=150.0, amp=0.3):
    """A steady 'vowel': harmonic tone at roughly speech level."""
    t = np.arange(int(sec * SR)) / SR
    return (amp * (np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * 2 * freq * t))).astype(np.float32)


def take():
    """Two sentences of two lines each. Inside a sentence the voice runs on through the comma (no pause),
    like the model does; between sentences there is 0.5 s of digital silence, like ElevenLabs output."""
    parts = [np.zeros(int(0.3 * SR), np.float32), voiced(1.0), voiced(1.0, 170), np.zeros(int(0.5 * SR), np.float32),
             voiced(1.0, 160), voiced(1.0, 140), np.zeros(int(0.3 * SR), np.float32)]
    audio = np.concatenate(parts)
    sp = [(0.3, 1.3), (1.3, 2.3), (2.8, 3.8), (3.8, 4.8)]
    lines = []
    for n, say in [(1, "第一句前半，"), (1, "第一句後半。"), (2, "第二句前半，"), (2, "第二句後半。")]:
        lines.append({"n": n, "say": say, "show": say.rstrip("，。"), "en": "", "target": 5.0, "tempo": 1.0,
                      "pitch": 0.0, "gain": 0.0, "pause": 0.4, "breath": False})
    return audio, lines, sp


def speech_db(y):
    hop = int(SR * 0.02)
    m = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: m * hop].reshape(m, hop) ** 2).mean(1)) + 1e-9)
    return float(np.percentile(db[db > -40], 70))


class DropoutMetricTest(unittest.TestCase):
    def test_hard_cut_counts_slow_decay_does_not(self):
        v = voiced(1.0)
        hard = np.concatenate([v, np.zeros(SR // 2, np.float32)])
        fade = v.copy()
        n = int(0.25 * SR)
        fade[-n:] *= np.linspace(1, 0, n, dtype=np.float32) ** 2
        soft = np.concatenate([fade, np.zeros(SR // 2, np.float32)])
        self.assertGreaterEqual(len(qc.dropouts(hard, SR, speech_db(hard))), 1)
        self.assertEqual(qc.dropouts(soft, SR, speech_db(soft)), [])

    def test_spec_has_dropouts(self):
        self.assertEqual(qc.SPEC["dropouts per min"], (0.0, 3.0))


class SentenceCutTest(unittest.TestCase):
    def test_no_cut_inside_a_sentence(self):
        audio, lines, sp = take()
        out, _ = pr.rebuild_sentences(audio, lines, sp, bank=[])
        # line mode cuts at the comma, where the voice is still loud; sentence mode keeps it whole
        _, line_lines, _ = take()
        line_out, _ = pr.rebuild(audio, line_lines, sp, bank=[])
        spd = speech_db(audio)
        self.assertLess(len(qc.dropouts(out, SR, spd)), len(qc.dropouts(line_out, SR, spd)))

    def test_line_times_follow_the_take(self):
        audio, lines, sp = take()
        pr.rebuild_sentences(audio, lines, sp, bank=[])
        t = [(l["t0"], l["t1"]) for l in lines]
        for (a0, a1), (b0, _) in zip(t, t[1:]):
            self.assertLess(a0, a1)
            self.assertLessEqual(a1, b0 + 1e-6)
        # same tempo within a sentence, so the two halves keep their relative timing
        self.assertEqual(lines[0]["tempo"], lines[1]["tempo"])
        self.assertAlmostEqual(lines[1]["t0"] - lines[0]["t0"], (sp[1][0] - sp[0][0]) / lines[0]["tempo"], places=2)

    def test_room_tail_softens_a_stop(self):
        hard = np.concatenate([voiced(1.0), np.zeros(SR // 2, np.float32)])
        spd = speech_db(hard)
        self.assertEqual(len(pr.add_room(hard)), len(hard))
        self.assertLessEqual(len(qc.dropouts(pr.add_room(hard), SR, spd)), len(qc.dropouts(hard, SR, spd)))
        tail = pr.add_room(hard)[SR + int(0.02 * SR): SR + int(0.06 * SR)]
        self.assertGreater(float(np.abs(tail).max()), 1e-4)   # something rings on after the voice stops


class ProfileTest(unittest.TestCase):
    def tearDown(self):
        pr.CHUNK, pr.BREATH_BELOW = "line", 32.0

    def test_explainer_cuts_by_sentence(self):
        pr.use_profile("explainer")
        self.assertEqual(pr.CHUNK, "sentence")
        self.assertEqual(pr.SETTINGS["speed"], 1.15)   # same TTS speed as podcast, so cached takes are reused

    def test_news_keeps_line_cuts(self):
        pr.use_profile("news")
        self.assertEqual(pr.CHUNK, "line")


class CuesTest(unittest.TestCase):
    def test_cues_from_report(self):
        report = [{"lines": [{"say": "一，", "show": "一", "en": "one", "t0": 0.5, "t1": 1.0},
                             {"say": "二。", "show": "二", "en": "", "t0": 1.1, "t1": 1.6}]},
                  {"lines": [{"say": "三。", "show": "三", "en": "three", "t0": 3.0, "t1": 3.5}]}]
        cues = pr.cues_from_report(report, "v1_rhythm.wav")
        self.assertEqual([c["seg"] for c in cues], [0, 0, 1])
        self.assertLessEqual(cues[0]["end"], cues[1]["start"])     # hold never runs into the next line
        self.assertAlmostEqual(cues[2]["end"], 3.5 + pr.CUE_HOLD)
        self.assertIsNone(cues[1]["en"])
        self.assertEqual(set(cues[0]), {"seg", "audio", "start", "end", "say", "show", "en"})


if __name__ == "__main__":
    unittest.main()
