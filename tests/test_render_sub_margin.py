"""字幕高度依畫面比例決定（--sub-margin）的測試。"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


HELPERS = Path(__file__).parents[1] / "helpers"


def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = load_helper("render")


class SubMarginVTests(unittest.TestCase):
    def test_portrait_keeps_official_value(self):
        # 直式短影音要避開 App 按鈕，維持官方的 90
        self.assertEqual(render.sub_margin_v(1080, 1920), 90)

    def test_landscape_lowered(self):
        # 橫式沒有 App 按鈕，放到離底部約 8%（288 × 8% ≈ 23）
        self.assertEqual(render.sub_margin_v(1920, 1080), 23)
        self.assertEqual(render.sub_margin_v(1280, 720), 23)

    def test_square_lowered(self):
        self.assertEqual(render.sub_margin_v(1080, 1080), 23)

    def test_unknown_size_keeps_official_value(self):
        self.assertEqual(render.sub_margin_v(None, None), 90)

    def test_pct_overrides(self):
        self.assertEqual(render.sub_margin_v(1920, 1080, pct=5), 14)
        # 16:9 算繪後才裁成 9:16：傳 31% 就和直式原本的高度一樣
        self.assertEqual(render.sub_margin_v(1920, 1080, pct=31), 89)
        self.assertEqual(render.sub_margin_v(1080, 1920, pct=5), 14)


class ForceStyleMarginTests(unittest.TestCase):
    def test_margin_replaced(self):
        style = render.sub_force_style("ja", margin_v=23)
        self.assertIn("MarginV=23", style)
        self.assertNotIn("MarginV=90", style)

    def test_default_unchanged(self):
        for lang in ("en", "zh-tw", "ja"):
            self.assertEqual(render.sub_force_style(lang), render.SUB_LANGS[lang]["force_style"])

    def test_font_and_margin_together(self):
        style = render.sub_force_style("zh-tw", font="Noto Sans TC", margin_v=14)
        self.assertIn("FontName=Noto Sans TC", style)
        self.assertIn("MarginV=14", style)


class SubMarginArgTests(unittest.TestCase):
    def test_out_of_range_rejected(self):
        argv = ["render.py", "missing_edl.json", "-o", "out.mp4", "--sub-margin", "60"]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                render.main()
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
