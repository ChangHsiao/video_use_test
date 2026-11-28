"""voice_dna.py（聲音 DNA：配方、量測指紋、比對新錄音檔）的測試。用合成的「人聲」，不打 API。"""

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_registry import load_helper, reg  # noqa: E402

dna = load_helper("voice_dna")
SR = 22050


def fake_voice(path, f0, seconds=2.5):
    """Harmonic tone with a slow pitch wobble and syllable-like gating: enough for pyin and the MFCCs."""
    t = np.arange(int(SR * seconds)) / SR
    phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.04 * np.sin(2 * np.pi * 1.5 * t))) / SR
    y = sum(np.sin(k * phase) / k for k in range(1, 12))
    y *= 0.6 + 0.4 * (np.sin(2 * np.pi * 4 * t) > -0.5)
    pcm = (0.3 * y / np.abs(y).max() * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(pcm.tobytes())


class SyllablesTest(unittest.TestCase):
    # 中文一字一音節，英文照母音組估：這裡是(3) Sunny(2) 資料科學(4)
    def test_mixed_text(self):
        self.assertEqual(dna.syllables("這裡是 Sunny 資料科學，"), 9)


class ToleranceTest(unittest.TestCase):
    def fp(self, f0, rate, centroid, mfcc):
        return {"f0_median_hz": f0, "f0_range_st": 10.0, "rate_syl_s": rate, "centroid_hz": centroid,
                "lufs": -16.0, "mfcc": mfcc}

    # 每一支核准過的參考音檔都要通過自己的 DNA，就算它們彼此差很多
    def test_every_reference_passes(self):
        fps = [self.fp(110, 4.4, 1800, [0.0] * 12), self.fp(150, 4.0, 1500, [40.0] * 12)]
        c = dna.center(fps)
        d = {"center": c, "tolerance": dna.tolerance(fps, c)}
        for fp in fps:
            self.assertTrue(all(ok for *_, ok in dna.compare(fp, d)))

    # 比參考音檔偏更遠的錄音要被抓出來，而且指出是哪一項
    def test_drift_beyond_references_fails(self):
        fps = [self.fp(120, 4.4, 1800, [0.0] * 12), self.fp(125, 4.4, 1800, [1.0] * 12)]
        c = dna.center(fps)
        d = {"center": c, "tolerance": dna.tolerance(fps, c)}
        failed = [name for name, _, _, ok in dna.compare(self.fp(170, 4.4, 1800, [0.5] * 12), d) if not ok]
        self.assertEqual(failed, ["f0_median_st"])


class BuildAndCheckTest(unittest.TestCase):
    # 從品牌的口播收尾建 DNA：哪段口播屬於哪個聲音、DNA 存哪裡，都照 brand.json
    def test_build_from_brand_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "brands"
            b = root / "測試品牌"
            (b / "assets").mkdir(parents=True)
            fake_voice(b / "assets/a.wav", 120)
            fake_voice(b / "assets/b.wav", 126)
            fake_voice(b / "assets/other.wav", 220)
            (b / "brand.json").write_text(json.dumps({
                "name": "測試品牌", "colors": {"bg": "#000000"},
                "voices": {"male": "id-m", "female": "id-f"},
                "voice_dna": {"male": "assets/dna/m.json"},
                "signoff": {"audio": "assets/a.wav", "text": "這裡是測試品牌", "voice": "male"},
                "series": {"s1": {"signoff": {"audio": "assets/b.wav", "text": "這裡是測試品牌", "voice": "male"}},
                           "s2": {"signoff": {"audio": "assets/other.wav", "text": "女聲", "voice": "female"}}},
            }, ensure_ascii=False), encoding="utf-8")
            brand = reg.load_brand("測試品牌", root)
            out = dna.build(brand, "male")
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(out, b / "assets/dna/m.json")
            self.assertEqual(sorted(data["references"]), ["brand", "s1"])  # the female line is not in it
            self.assertEqual(data["voice_id"], "id-m")
            self.assertIn("voice_settings", data["recipe"])
            self.assertAlmostEqual(data["center"]["f0_median_hz"], 123, delta=3)
            far = dna.measure(b / "assets/other.wav", "這裡是測試品牌")
            self.assertFalse(dict((n, ok) for n, _, _, ok in dna.compare(far, data))["f0_median_st"])

    def test_unknown_voice_is_a_config_error(self):
        brand = reg.Brand("x", Path("."), {"voice_dna": {"male": "m.json"}})
        with self.assertRaises(dna.registry.ConfigError):
            dna.dna_path(brand, "female")


if __name__ == "__main__":
    unittest.main()
