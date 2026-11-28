"""registry.py（風格、品牌、版型的登記處）的測試。"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).resolve().parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))


def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reg = load_helper("registry")


class RepoStylesTest(unittest.TestCase):
    # styles/ 底下每個風格都要能載入：版型有登記、欄位齊全、用到的顏色都有定義、品牌找得到
    def test_every_style_loads(self):
        names = reg.available(reg.STYLES_DIR, "style.json")
        self.assertIn("暗色科技風", names)
        for name in names:
            with self.subTest(style=name):
                style = reg.load_style(name)
                self.assertIn(style.layout, reg.LAYOUTS)

    def test_every_brand_loads(self):
        for name in reg.available(reg.BRANDS_DIR, "brand.json"):
            with self.subTest(brand=name):
                self.assertTrue(reg.load_brand(name).colors)

    # 品牌寫到的素材（logo、片尾、口播收尾、英文字型）都要在品牌資料夾裡
    def test_brand_assets_exist(self):
        for name in reg.available(reg.BRANDS_DIR, "brand.json"):
            brand = reg.load_brand(name)
            series = brand.data.get("series", {}).values()
            files = [*brand.data.get("logo", {}).values(), *brand.data.get("outro", {}).values(),
                     brand.data.get("signoff", {}).get("audio"), *brand.data.get("voice_dna", {}).values(),
                     *(s.get("outro") for s in series), *(s.get("outro_a", {}).get("video") for s in series),
                     *(s.get("signoff", {}).get("audio") for s in series)]
            for rel in filter(None, files):
                with self.subTest(brand=name, file=rel):
                    self.assertIsNotNone(brand.asset(rel), rel)
            if "en" in brand.data.get("fonts", {}):
                self.assertTrue(any(brand.asset(f) for f in brand.data["fonts"]["en"]))

    # 風格的配樂檔要存在
    def test_style_music_exists(self):
        for name in reg.available(reg.STYLES_DIR, "style.json"):
            style = reg.load_style(name)
            music = (style.get("music") or {}).get("file")
            if music:
                with self.subTest(style=name):
                    self.assertTrue(style.asset(music).is_file())

    # 每個有品牌的風格，品牌的顏色都併進來了
    def test_brand_colors_merged(self):
        style = reg.load_style("桑尼新聞短片")
        self.assertEqual(style.brand.name, "桑尼資料科學")
        self.assertEqual(style.rgb("mint"), (0x7E, 0xEB, 0xD9))
        self.assertIn("sub", style.colors)


class FakeTreeTest(unittest.TestCase):
    """在暫存資料夾做 styles/、brands/，測讀取規則本身。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.styles, self.brands = self.root / "styles", self.root / "brands"
        base = json.loads((reg.STYLES_DIR / "暗色科技風" / "style.json").read_text(encoding="utf-8"))
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, kind, name, data, files=()):
        d = (self.styles if kind == "style" else self.brands) / name
        d.mkdir(parents=True)
        (d / f"{kind}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text(name, encoding="utf-8")
        return d

    def load(self, name):
        return reg.load_style(name, root=self.styles, brands_root=self.brands)

    def test_missing_style_lists_available(self):
        self.write("style", "甲", self.base)
        with self.assertRaisesRegex(reg.ConfigError, "找不到風格「乙」.*甲"):
            self.load("乙")

    def test_default_layout(self):
        data = {k: v for k, v in self.base.items() if k != "layout"}
        self.write("style", "甲", data)
        self.assertEqual(self.load("甲").layout, "broll_top")

    def test_unknown_layout(self):
        self.write("style", "甲", dict(self.base, layout="沒有這種"))
        with self.assertRaisesRegex(reg.ConfigError, "沒有登記.*broll_top"):
            self.load("甲")

    def test_missing_field_for_layout(self):
        data = dict(self.base)
        data.pop("broll")
        self.write("style", "甲", data)
        with self.assertRaisesRegex(reg.ConfigError, "格式不對.*broll"):
            self.load("甲")

    # 橫式版型 broll_wide：多 canvas、text_max_w，broll 不需要 top
    def wide(self, **change):
        data = dict(self.base, layout="broll_wide", canvas={"w": 1920, "h": 1080}, text_max_w=1700,
                    broll={"bg_zoom": 1.15, "bg_dim": 0.45})
        data.update(change)
        return data

    def test_broll_wide_loads(self):
        self.write("style", "甲", self.wide())
        self.assertEqual(self.load("甲").layout, "broll_wide")

    def test_broll_wide_needs_canvas(self):
        data = self.wide()
        data.pop("canvas")
        self.write("style", "甲", data)
        with self.assertRaisesRegex(reg.ConfigError, "格式不對.*canvas"):
            self.load("甲")

    # 橫式還不支援 logo、吉祥物：寫了就報錯，不會合成出位置錯的畫面
    def test_broll_wide_rejects_logo(self):
        self.write("style", "甲", self.wide(logo={"x": 100, "y": 100, "size": 80}))
        with self.assertRaisesRegex(reg.ConfigError, "logo"):
            self.load("甲")

    def test_undefined_color(self):
        self.write("style", "甲", dict(self.base, title=dict(self.base["title"], accent="purple")))
        with self.assertRaisesRegex(reg.ConfigError, "purple"):
            self.load("甲")

    def test_missing_brand(self):
        self.write("style", "甲", dict(self.base, brand="沒有"))
        with self.assertRaisesRegex(reg.ConfigError, "找不到品牌「沒有」"):
            self.load("甲")

    # 品牌的顏色先載入，風格同名的顏色蓋過去；風格可以直接用品牌的顏色名稱
    def test_brand_colors_and_override(self):
        self.write("brand", "乙", {"colors": {"red": "#111111", "brandonly": "#222222"}})
        colors = dict(self.base["colors"])
        colors.pop("red")
        style = dict(self.base, brand="乙", colors=dict(colors, white="#fefefe"))
        self.write("style", "甲", style)
        s = self.load("甲")
        self.assertEqual(s.colors["red"], "#111111")
        self.assertEqual(s.colors["brandonly"], "#222222")
        self.assertEqual(s.colors["white"], "#fefefe")

    # 找素材：影片資料夾 → 風格資料夾 → 品牌資料夾
    def test_asset_chain(self):
        self.write("brand", "乙", {"colors": {}}, files=["logo.png", "only_brand.txt"])
        self.write("style", "甲", dict(self.base, brand="乙"), files=["logo.png"])
        episode = self.root / "ep"
        episode.mkdir()
        s = self.load("甲")
        self.assertEqual(s.asset("only_brand.txt").read_text(encoding="utf-8"), "乙")
        self.assertEqual(s.asset("logo.png").read_text(encoding="utf-8"), "甲")
        (episode / "logo.png").write_text("ep", encoding="utf-8")
        self.assertEqual(s.asset("logo.png", extra=[episode]).read_text(encoding="utf-8"), "ep")
        with self.assertRaisesRegex(reg.ConfigError, "找不到素材"):
            s.asset("nope.png")

    # 給好幾個候選時用第一個存在的（例如字型：品牌資料夾的檔案 → 系統字型）
    def test_asset_candidates(self):
        self.write("style", "甲", self.base, files=["b.ttf"])
        self.assertEqual(self.load("甲").asset("a.ttf", "b.ttf").name, "b.ttf")


if __name__ == "__main__":
    unittest.main()
