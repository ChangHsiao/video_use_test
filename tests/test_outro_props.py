"""outro_props.py（片尾 A 的文字，從 brand.json 產生 Remotion props）的測試。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_registry import load_helper, reg  # noqa: E402

props = load_helper("outro_props")

DATA = {
    "name": "品牌", "name_en": "Brand", "slogan": "品牌口號。", "outro_a": {"footer": "品牌小字"},
    "series": {
        "own": {"slogan": "系列口號。", "outro_a": {"slogan": "片尾專用口號。", "footer": "系列小字"}},
        "plain": {"slogan": "只有口號。"},
    },
}


class OutroPropsTest(unittest.TestCase):
    def setUp(self):
        self.brand = reg.Brand("品牌", Path("."), DATA)

    def test_brand_level(self):
        self.assertEqual(props.outro_props(self.brand),
                         {"name": "品牌", "nameEn": "Brand", "slogan": "品牌口號。", "footer": "品牌小字"})

    # 系列的 outro_a.slogan 優先；品牌名稱永遠用品牌的
    def test_series_overrides(self):
        p = props.outro_props(self.brand, "own")
        self.assertEqual((p["name"], p["slogan"], p["footer"]), ("品牌", "片尾專用口號。", "系列小字"))

    # 系列沒寫 outro_a 時，退回系列自己的口號，小字留空（不會借用品牌的小字）
    def test_series_without_outro_a(self):
        p = props.outro_props(self.brand, "plain")
        self.assertEqual((p["slogan"], p["footer"]), ("只有口號。", ""))

    def test_unknown_series(self):
        with self.assertRaises(props.registry.ConfigError):
            props.outro_props(self.brand, "nope")

    # 真實品牌：每個系列都產得出完整文字
    def test_repo_brands(self):
        for name in reg.available(reg.BRANDS_DIR, "brand.json"):
            brand = reg.load_brand(name)
            for series in [None, *brand.data.get("series", {})]:
                with self.subTest(brand=name, series=series):
                    p = props.outro_props(brand, series)
                    self.assertTrue(p["name"] and p["slogan"], p)


if __name__ == "__main__":
    unittest.main()
