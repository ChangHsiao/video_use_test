"""news_short.py（新聞短片合成）的測試：用一份小的假分鏡，不讀真的影片。

2026-11-22 從 styles/桑尼新聞短片/tools/short.py 搬過來改讀 style.json 時，另外用 EP.01 的分鏡比對過
搬移前後的時間軸、每個鏡頭的 ffmpeg 指令和疊加層畫面，三項完全相同；那份比對要用影片資料夾，不在這裡。
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HELPERS = Path(__file__).resolve().parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
spec = importlib.util.spec_from_file_location("video_use_news_short", HELPERS / "news_short.py")
ns = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ns
spec.loader.exec_module(ns)


def line(t0, t1, show, en="", pause=0.4):
    return {"t0": t0, "t1": t1, "show": show, "en": en, "pause": pause}


class NewsShortTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.edit = Path(cls.tmp.name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        str(cls.edit / "signoff.wav")], check=True)
        ns.configure(cls.edit)
        cls.prosody = [{"lines": [line(0.5, 2.0, "第一句", "first"), line(2.4, 4.0, "第二句", "second")]}]
        cls.plan = {
            "title": "一段私事，怎麼變成|國安疑雲",
            "cover": {"lines": ["黃仁勳下台", "私事怎麼變成|國安案"], "dur": 1.2},
            "blocks": [
                {"vo": 0, "shots": [{"src": "a.mp4", "in": 1.0, "info": {"tag": "人事", "lines": ["一行", "兩行"]}},
                                    {"line": 1, "src": "b.mp4", "in": 3.0, "credit": "畫面／某台"}]},
                {"sot": {"src": "c.mp4", "in": 10.0, "out": 13.0, "who": "某人、職稱", "source": "某台",
                         "subs": [[0.0, 1.5, "原聲一", "quote one"], [1.5, 3.0, "原聲二", "quote two"]]}},
                {"signoff": {"audio": "signoff.wav", "show": "收尾", "en": "sign-off"}, "shots": [{"src": "d.mp4"}]},
            ],
        }
        cls.shots, cls.events, cls.audio, cls.total = ns.build_timeline(cls.plan, cls.prosody)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # 數值都來自風格：版面、顏色、轉場
    def test_configured_from_style(self):
        st = ns.STYLE
        self.assertEqual((ns.BAND_Y, ns.BAND_H), (st["band"]["y"], st["band"]["h"]))
        self.assertEqual(ns.MINT, st.rgb("mint"))
        self.assertEqual((ns.X_IN, ns.X_BLOCK), (st["transitions"]["in_block"], st["transitions"]["between_blocks"]))
        self.assertIn(f"contrast={st['grade']['contrast']}", ns.GRADE)
        self.assertTrue(Path(ns.FONT_EN).is_file())
        self.assertTrue(Path(ns.LOGO).is_file())

    # 版型不是 news_band 的風格不能用
    def test_rejects_other_layout(self):
        with self.assertRaises(SystemExit):
            ns.configure(self.edit, "暗色科技風")
        ns.configure(self.edit)

    # 時間軸：旁白區塊 → 原聲區塊（前後留白）→ 口播收尾；第二個鏡頭切在兩句之間停頓的中點
    def test_timeline(self):
        vo_start = 0.5 - 0.12
        self.assertAlmostEqual(self.shots[1][0], (2.0 + 2.4) / 2 - vo_start, places=3)
        sot = next(s for s in self.shots if s[2].get("sot"))
        self.assertAlmostEqual(sot[1], 3.0 + ns.SOT_PRE + ns.SOT_POST, places=3)
        self.assertEqual([a[0] for a in self.audio], ["vo", "sot", "file"])
        kinds = {e[0] for e in self.events}
        self.assertTrue({"sub", "info", "credit", "sot", "cover", "title"} <= kinds)

    # 字幕不重疊：每句在下一句開始時結束
    def test_subtitles_do_not_overlap(self):
        subs = sorted((e for e in self.events if e[0] == "sub"), key=lambda e: e[1])
        for a, b in zip(subs, subs[1:]):
            self.assertLessEqual(a[2], b[1] + 1e-9)

    # 疊加層畫在風格指定的位置：固定標題在 title.y、中文字幕在 subtitle.zh.y 附近
    def test_overlay_positions(self):
        img = np.asarray(ns.render_state([("title", self.plan["title"]), ("sub", ("第一句", "first"))]))
        rows = np.where(img[..., 3].max(axis=1) > 0)[0]
        ty, zy = ns.STYLE["title"]["y"], ns.STYLE["subtitle"]["zh"]["y"]
        self.assertTrue(any(ty - 5 <= r <= ty + 80 for r in rows))
        self.assertTrue(any(zy - 5 <= r <= zy + 80 for r in rows))
        self.assertEqual(int(img[100, :, 3].max()), 0)

    # 鏡頭指令：主畫面帶用風格的位置、調色和暗角
    def test_shot_command(self):
        tmp = Path(self.tmp.name)
        cmd = " ".join(map(str, ns.shot_cmd("a.mp4", 1.0, 2.0, "band", tmp / "o.mp4", tmp, push=0.04)))
        self.assertIn(f"overlay=0:{ns.BAND_Y}", cmd)
        self.assertIn(ns.GRADE, cmd)
        self.assertIn(ns.FINISH, cmd)

    # --samples：每種疊加層各一張
    def test_samples(self):
        plan_path = self.edit / "短片.json"
        self.plan["plan"] = "prosody.json"
        (self.edit / "prosody.json").write_text(json.dumps(self.prosody, ensure_ascii=False), encoding="utf-8")
        plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
        sys.argv = ["news_short.py", str(plan_path), "--samples"]
        ns.main()
        names = {p.name for p in (self.edit / "verify").glob("sample_*.png")}
        self.assertTrue({"sample_title.png", "sample_sub.png", "sample_info.png", "sample_sot.png"} <= names)


if __name__ == "__main__":
    unittest.main()
