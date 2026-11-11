"""compose.py（合成.json → 預覽影片）的測試。"""

import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
from PIL import Image


HELPERS = Path(__file__).parents[1] / "helpers"


# 用檔案路徑載入 helpers 裡的程式（helpers 不是套件，不能直接 import）
def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cp = load_helper("compose")


# 做一句測試用的字幕資料，格式同 align_voice.py 輸出的 cues.json
def make_cue(seg, start, end, show, en=None):
    return {"seg": seg, "start": start, "end": end, "show": show, "say": show + "，", "en": en}


# 三段配音、五句字幕：第 0 段兩句、第 1 段兩句、第 2 段一句
CUES = [
    make_cue(0, 0.3, 1.5, "0.81 秒"),
    make_cue(0, 1.8, 3.0, "從靜止衝到時速 97 公里"),
    make_cue(1, 4.0, 5.0, "先看這個畫面"),
    make_cue(1, 5.2, 6.5, "車子沿著軌道往上開"),
    make_cue(2, 7.5, 9.0, "預計 2028 年量產"),
]


class FindCueTest(unittest.TestCase):
    # 比對時忽略空白和標點：「從靜止，衝到時速97公里。」也找得到
    def test_ignores_spaces_and_punctuation(self):
        self.assertEqual(cp.find_cue(CUES, "從靜止，衝到時速97公里。"), 1)

    # 只寫一句字幕的一部分也找得到
    def test_matches_part_of_cue(self):
        self.assertEqual(cp.find_cue(CUES, "沿著軌道"), 3)

    # 找不到時報錯，訊息裡有那段文字
    def test_not_found(self):
        with self.assertRaisesRegex(cp.ComposeError, "找不到.*不存在的句子"):
            cp.find_cue(CUES, "不存在的句子")

    # 只寫一部分、往後有好幾句都包含時報錯，提醒寫長一點
    def test_ambiguous(self):
        with self.assertRaisesRegex(cp.ComposeError, "2 句"):
            cp.find_cue(CUES, "0")  # 「0.81 秒」和「2028」都有

    # 只從 after 那句的下一句開始找：前面的句子不算
    def test_searches_after(self):
        self.assertEqual(cp.find_cue(CUES, "0", after=1), 4)
        with self.assertRaisesRegex(cp.ComposeError, "之後"):
            cp.find_cue(CUES, "0.81 秒", after=0)

    # 整句完全相同的優先：第一句就是「0.81 秒」，後面還有句子包含「0.81 秒」也不算重複
    def test_exact_match_wins(self):
        cues = [make_cue(0, 0.3, 1.0, "0.81 秒"), make_cue(1, 5.0, 6.0, "最後 回到 0.81 秒")]
        self.assertEqual(cp.find_cue(cues, "0.81 秒"), 0)

    # 同一句出現兩次：從前一個鏡頭之後找，第二次用到的是後面那句
    def test_repeated_sentence(self):
        cues = [make_cue(0, 0.3, 1.0, "跟空氣借力"), make_cue(0, 1.2, 2.0, "先看這個畫面"),
                make_cue(1, 3.0, 4.0, "跟空氣借力")]
        self.assertEqual(cp.find_cue(cues, "跟空氣借力"), 0)
        self.assertEqual(cp.find_cue(cues, "跟空氣借力", after=1), 2)


class LoadPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "a.mp4").write_bytes(b"")
        (self.dir / "anim.mp4").write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    # 把 shots 寫成 合成.json 再讀回來
    def load(self, shots):
        path = self.dir / "合成.json"
        path.write_text(json.dumps({"title": {"text": "標題"}, "shots": shots}, ensure_ascii=False), encoding="utf-8")
        return cp.load_plan(path)

    # 路徑相對於 合成.json，讀進來變成完整路徑
    def test_resolves_relative_paths(self):
        plan = self.load([{"from": "x", "broll": "a.mp4", "in": 1.0}])
        self.assertEqual(plan["shots"][0]["broll"], self.dir / "a.mp4")

    # 一個鏡頭同時寫兩種畫面要報錯
    def test_two_pictures(self):
        with self.assertRaisesRegex(cp.ComposeError, "第 1 個鏡頭"):
            self.load([{"from": "x", "broll": "a.mp4", "in": 0, "animation": "anim.mp4"}])

    # 畫面和段落標題都沒寫要報錯（擋住漏寫，避免成品出現黑畫面）
    def test_no_picture(self):
        with self.assertRaisesRegex(cp.ComposeError, "沒有畫面"):
            self.load([{"from": "x"}])

    # 只寫段落標題、不寫畫面是允許的：整個鏡頭是全螢幕標題卡
    def test_section_only(self):
        plan = self.load([{"from": "x", "section": {"small": "第三招", "big": "0.81 秒"}}])
        self.assertIsNone(plan["shots"][0]["picture"])

    # B-roll 沒寫起點秒數要報錯
    def test_broll_needs_in(self):
        with self.assertRaisesRegex(cp.ComposeError, "in"):
            self.load([{"from": "x", "broll": "a.mp4"}])

    # 素材檔不存在要報錯，訊息裡有路徑
    def test_missing_file(self):
        with self.assertRaisesRegex(cp.ComposeError, "nope.mp4"):
            self.load([{"from": "x", "broll": "nope.mp4", "in": 0}])

    # 數字卡的顏色只能用風格表裡有的
    def test_unknown_color(self):
        with self.assertRaisesRegex(cp.ComposeError, "purple"):
            self.load([{"from": "x", "broll": "a.mp4", "in": 0,
                        "number": {"big": "1", "label": "x", "color": "purple"}}])


class BuildTimelineTest(unittest.TestCase):
    # 不讀真的影片：每支素材都當作 100 秒長
    @staticmethod
    def long_enough(_path):
        return 100.0

    def shot(self, frm, **kw):
        base = {"from": frm, "picture": "broll", "broll": Path("a.mp4"), "in": 0.0}
        base.update(kw)
        return base

    def build(self, shots, total=10.5, durations=None):
        return cp.build_timeline({"shots": shots}, CUES, total, durations or self.long_enough)

    # 第一個鏡頭從 0 秒開始，最後一個放到片尾，中間的鏡頭從那句字幕開始
    def test_starts_and_ends(self):
        tl = self.build([self.shot("0.81 秒"), self.shot("從靜止"), self.shot("車子沿著")])
        self.assertEqual([(s["start"], s["end"]) for s in tl], [(0.0, 1.8), (1.8, 5.2), (5.2, 10.5)])

    # 段落第一句的鏡頭提早 0.5 秒換，從段落之間的空檔開始，不等念出第一個字
    def test_segment_first_shot_starts_in_gap(self):
        tl = self.build([self.shot("0.81 秒"), self.shot("先看這個畫面")])
        self.assertEqual(tl[1]["start"], 3.5)
        self.assertEqual(tl[0]["end"], 3.5)

    # 數字卡預設在鏡頭開始出現；寫了 at 就在那句字幕開始時出現
    def test_number_time(self):
        tl = self.build([
            self.shot("0.81 秒", number={"big": "1", "label": "x", "color": "red"}),
            self.shot("先看這個畫面", number={"big": "2", "label": "y", "color": "red", "at": "沿著軌道"}),
        ])
        self.assertEqual(tl[0]["number"]["at"], 0.0)
        self.assertEqual(tl[1]["number"]["at"], 5.2)

    # 鏡頭的順序和字幕順序不同時報錯：往後找不到，訊息提醒檢查順序
    def test_out_of_order(self):
        with self.assertRaisesRegex(cp.ComposeError, "順序"):
            self.build([self.shot("0.81 秒"), self.shot("車子沿著"), self.shot("從靜止")])

    # 同一句出現兩次時，兩個鏡頭依序對到前後兩句
    def test_repeated_sentence_in_shots(self):
        cues = [make_cue(0, 0.3, 1.0, "跟空氣借力"), make_cue(0, 1.2, 2.0, "先看這個畫面"),
                make_cue(0, 3.0, 4.0, "跟空氣借力")]
        tl = cp.build_timeline({"shots": [self.shot("跟空氣借力"), self.shot("先看這個畫面"), self.shot("跟空氣借力")]},
                               cues, 5.0, self.long_enough)
        self.assertEqual([s["start"] for s in tl], [0.0, 1.2, 3.0])

    # 數字卡的 at 從這個鏡頭那句開始往後找，不會對到前面的同一句
    def test_number_at_searches_from_shot(self):
        cues = [make_cue(0, 0.3, 1.0, "2G"), make_cue(0, 1.2, 2.0, "先看這個畫面"), make_cue(0, 3.0, 4.0, "2G")]
        tl = cp.build_timeline({"shots": [self.shot("2G"), self.shot("先看這個畫面", number={
            "big": "2G", "label": "x", "color": "red", "at": "2G"})]}, cues, 5.0, self.long_enough)
        self.assertEqual(tl[1]["number"]["at"], 3.0)

    # B-roll 起點＋鏡頭長度超過素材長度時，合成前就報錯並指出是哪個鏡頭
    def test_broll_too_short(self):
        with self.assertRaisesRegex(cp.ComposeError, "第 2 個鏡頭"):
            self.build([self.shot("0.81 秒"), self.shot("從靜止", **{"in": 97.0})])

    # 說明動畫比鏡頭短也要報錯（不然動畫放完會停在最後一格）
    def test_animation_too_short(self):
        shots = [self.shot("0.81 秒"), {"from": "從靜止", "picture": "animation", "animation": Path("anim.mp4")}]
        with self.assertRaisesRegex(cp.ComposeError, "第 2 個鏡頭"):
            self.build(shots, durations=lambda p: 2.0)

    # 全螢幕標題卡沒有素材，不檢查長度
    def test_section_only_has_no_source(self):
        shots = [self.shot("0.81 秒"), {"from": "從靜止", "picture": None, "section": {"small": "a", "big": "b"}}]
        self.assertEqual(self.build(shots)[1]["end"], 10.5)


# 用 ffmpeg 做測試影片：parts 是 [(顏色, 秒數), ...] 依序接起來；fade=True 時整段慢慢變暗（沒有換畫面）
def make_video(path, parts, fade=False, rate=30):
    inputs = []
    for color, sec in parts:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s=160x90:r={rate}:d={sec}"]
    graph = "".join(f"[{i}:v]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0"
    if fade:
        total = sum(sec for _, sec in parts)
        graph += f",fade=t=out:st=0:d={total}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph + "[v]", "-map", "[v]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


class CheckCutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.cut = cls.dir / "cut.mp4"  # 第 2 秒從紅色換成藍色
        make_video(cls.cut, [("red", 2), ("blue", 2)])
        cls.fade = cls.dir / "fade.mp4"  # 4 秒慢慢變暗，沒有換畫面
        make_video(cls.fade, [("white", 4)], fade=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def shot(self, src, start_in, length, **kw):
        s = {"from": "x", "picture": "broll", "broll": src, "in": start_in, "start": 0.0, "end": length}
        s.update(kw)
        return s

    # 視窗裡有換畫面：抓到，回報換畫面的秒數
    def test_find_jump_detects_cut(self):
        t = cp.find_jump(self.cut, 1.7)
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t, 2.0, delta=0.05)

    # 每秒 24 格的素材：用素材自己的影格率算，換畫面的秒數一樣準
    def test_find_jump_24fps(self):
        path = self.dir / "cut24.mp4"
        make_video(path, [("red", 2), ("blue", 2)], rate=24)
        self.assertAlmostEqual(cp.find_jump(path, 1.7), 2.0, delta=0.05)

    # 視窗裡沒有換畫面：不報
    def test_find_jump_no_cut(self):
        self.assertIsNone(cp.find_jump(self.cut, 0.5))

    # 畫面慢慢變暗不是換畫面：不誤報
    def test_find_jump_slow_change(self):
        self.assertIsNone(cp.find_jump(self.fade, 1.0))

    # 起點剛好在換畫面的那一格：沒有閃（一開始就是新畫面），不報
    def test_cut_exactly_at_start(self):
        self.assertIsNone(cp.find_jump(self.cut, 2.0))

    # 鏡頭開頭 0.6 秒內換畫面：列出問題、輸出對照圖
    def test_check_cuts_head(self):
        out = self.dir / "check_head"
        issues = cp.check_cuts([self.shot(self.cut, 1.7, 1.5)], out)
        self.assertEqual(len(issues), 1)
        self.assertIn("開頭", issues[0])
        self.assertTrue((out / "1.jpg").is_file())

    # 鏡頭結尾 0.6 秒內換畫面也要抓：素材 0.5～2.3 秒，2.0 秒換畫面
    def test_check_cuts_tail(self):
        issues = cp.check_cuts([self.shot(self.cut, 0.5, 1.8)], self.dir / "check_tail")
        self.assertEqual(len(issues), 1)
        self.assertIn("結尾", issues[0])

    # 建議的起點：頭尾 0.6 秒內都沒有換畫面，而且是最接近原本起點的。素材 3、6 秒換畫面，鏡頭 4 秒，
    # 原本從 2.7 開始（開頭會閃）；中間經過換畫面沒關係
    def test_suggest_in(self):
        path = self.dir / "three.mp4"
        make_video(path, [("red", 3), ("blue", 3), ("green", 3)])
        x = cp.suggest_in(path, 4.0, 2.7)
        self.assertIsNotNone(x)
        self.assertLess(abs(x - 2.7), 0.5)
        self.assertIsNone(cp.find_jump(path, x))
        self.assertIsNone(cp.find_jump(path, x + 4.0 - 0.6))

    # 素材每 0.5 秒換一次畫面：頭尾 0.6 秒內一定會碰到，找不到建議的起點，訊息請使用者換素材
    def test_suggest_none_when_cuts_too_dense(self):
        path = self.dir / "dense.mp4"
        make_video(path, [(c, 0.5) for c in ["red", "blue"] * 6])
        self.assertIsNone(cp.suggest_in(path, 4.0, 1.0))
        issues = cp.check_cuts([self.shot(path, 1.2, 4.0)], self.dir / "check_dense")
        self.assertIn("換一段素材", issues[0])

    # 標了 cut_ok（看過圖、判斷是誤報）就不再檢查
    def test_cut_ok_skips(self):
        self.assertEqual(cp.check_cuts([self.shot(self.cut, 1.7, 1.5, cut_ok=True)], self.dir / "check_ok"), [])

    # 說明動畫、講者、全螢幕標題卡不檢查
    def test_only_broll(self):
        shots = [{"from": "x", "picture": "animation", "animation": self.cut, "start": 0.0, "end": 3.0},
                 {"from": "y", "picture": None, "start": 3.0, "end": 4.0}]
        self.assertEqual(cp.check_cuts(shots, self.dir / "check_other"), [])


# 讀影片某一秒的畫面，回傳 RGB 陣列
def frame_at(path, t):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(out[0]), int(out[1])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


class BuildBaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.wide = cls.dir / "wide.mp4"  # 橫的紅色 B-roll
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90:r=30:d=5",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.wide)], check=True)
        cls.tall = cls.dir / "tall.mp4"  # 直的藍色說明動畫
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=108x192:r=30:d=5",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.tall)], check=True)
        shots = [
            {"from": "a", "picture": "broll", "broll": cls.wide, "in": 1.0, "start": 0.0, "end": 1.0},
            {"from": "b", "picture": "animation", "animation": cls.tall, "start": 1.0, "end": 2.0},
            {"from": "c", "picture": None, "start": 2.0, "end": 2.5},
        ]
        cls.out = cls.dir / "base.mp4"
        cp.build_base(shots, 2.5, cls.out, full=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # 預覽是 540×960，總格數 = 總長 × 30
    def test_size_and_frames(self):
        out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height,nb_read_frames", "-of", "csv=p=0", str(self.out)],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "540,960,75")

    # 橫的 B-roll：中間是原畫面（亮紅），上面是放大模糊、調暗的同一個畫面（暗紅）
    def test_wide_broll_layout(self):
        f = frame_at(self.out, 0.5)
        self.assertGreater(f[432, 270, 0], 200)  # 原畫面在離頂部 280 的位置，高 304
        self.assertTrue(60 < f[50, 270, 0] < 160)  # 上方背景亮度約 45%

    # 直的說明動畫鋪滿畫面
    def test_tall_fills(self):
        f = frame_at(self.out, 1.5)
        self.assertGreater(f[20, 270, 2], 200)
        self.assertGreater(f[940, 270, 2], 200)

    # 只有標題卡的鏡頭先放黑畫面，標題卡之後由疊加層畫
    def test_section_only_is_black(self):
        self.assertLess(frame_at(self.out, 2.2).max(), 30)


class OverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cues = [make_cue(0, 0.3, 1.5, "0.81 秒", en="0.81 seconds"), make_cue(0, 2.0, 3.0, "先看這個畫面")]
        cls.shots = [
            {"from": "a", "picture": "broll", "start": 0.0, "end": 2.0,
             "number": {"big": "0.81 秒", "label": "0–97 km/h", "color": "red", "at": 0.3}},
            {"from": "b", "picture": "broll", "start": 2.0, "end": 4.0, "section": {"small": "第一招", "big": "黏地"}},
        ]
        cls.ov = cp.Overlay({"text": "0.81 秒加速、還會飛", "accent": ["0.81 秒", "會飛"]},
                            cls.shots, cls.cues, scale=0.5, font=cp.default_font())

    # 這台電腦找得到預設的中文字型檔
    def test_default_font_exists(self):
        self.assertTrue(Path(cp.default_font()[0]).is_file())

    # 主要字型缺的字（Windows 的微軟正黑體沒有「≈」）改用備用字型，其他字照用主要字型
    @unittest.skipUnless(sys.platform == "win32", "只在 Windows 檢查微軟正黑體缺字")
    def test_fallback_for_missing_glyph(self):
        runs = self.ov.glyph_runs("≈ 8 噸", 120)
        self.assertEqual(runs[0][0], "≈")
        self.assertIsNot(runs[0][1], self.ov.font(120))
        self.assertIs(runs[-1][1], self.ov.font(120))

    # 標題裡的強調字拆出來換顏色，其他是白色
    def test_title_parts(self):
        self.assertEqual(cp.title_parts("0.81 秒加速、還會飛", ["0.81 秒", "會飛"]),
                         [("0.81 秒", "red"), ("加速、還", "white"), ("會飛", "red")])

    # 段落標題卡：切點前 0.3 秒開始淡入，切點那一格完整顯示，1.8 秒後消失
    def test_section_timing(self):
        self.assertEqual(self.ov.section_alpha(1, 1.69), 0.0)
        self.assertGreater(self.ov.section_alpha(1, 1.85), 0.0)
        self.assertEqual(self.ov.section_alpha(1, 2.0), 1.0)
        self.assertEqual(self.ov.section_alpha(1, 3.81), 0.0)

    # 只有標題卡的鏡頭：標題卡一直顯示到鏡頭結束，不淡出
    def test_section_only_holds(self):
        shots = [dict(self.shots[0]), {"from": "c", "picture": None, "start": 2.0, "end": 6.0,
                                       "section": {"small": "第三招", "big": "0.81 秒"}}]
        ov = cp.Overlay({}, shots, self.cues, scale=0.5, font=cp.default_font())
        self.assertEqual(ov.section_alpha(1, 5.9), 1.0)

    # 數字卡在 at 那一刻才出現，鏡頭結束就消失
    def test_number_timing(self):
        self.assertIsNone(self.ov.number_progress(0, 0.2))
        self.assertGreater(self.ov.number_progress(0, 0.5), 0.0)
        self.assertIsNone(self.ov.number_progress(0, 2.1))

    # 字幕畫在下方（中文黃色），沒有字幕的時間不畫
    def test_subtitle_drawn(self):
        band = slice(int(1600 * 0.5), int(1680 * 0.5))
        img = np.asarray(self.ov.render(1.0))
        yellow = (img[band, :, 0] > 200) & (img[band, :, 1] > 180) & (img[band, :, 2] < 120) & (img[band, :, 3] > 200)
        self.assertGreater(yellow.sum(), 50)
        img = np.asarray(self.ov.render(1.7))
        self.assertEqual(int(img[band, :, 3].max()), 0)

    # 畫面沒變的兩格，key 相同（沿用上一張，不重畫）；字幕換句時 key 不同
    def test_frame_key_reuse(self):
        self.assertEqual(self.ov.frame_key(1.0), self.ov.frame_key(1.2))
        self.assertNotEqual(self.ov.frame_key(1.2), self.ov.frame_key(1.6))


# 用 ffmpeg 做一段 sec 秒的測試音（440 Hz）
def make_tone(path, sec):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={sec}",
                    "-ac", "1", str(path)], check=True)


class AudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "voice").mkdir()
        make_tone(cls.dir / "voice" / "a.wav", 1.0)
        make_tone(cls.dir / "voice" / "b.wav", 1.0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def write_lines(self, segments):
        path = self.dir / "voice_lines.json"
        path.write_text(json.dumps({"segments": segments}), encoding="utf-8")
        return path

    # 有寫 start 的照寫的放；沒寫的接在上一段後面（和 align_voice.py 相同，字幕和聲音才對得上）
    def test_voice_starts(self):
        voice, total = cp.load_voice(self.write_lines([
            {"audio": "voice/a.wav", "start": 0.3, "lines": []},
            {"audio": "voice/b.wav", "lines": []},
        ]))
        self.assertEqual([round(v["start"], 2) for v in voice], [0.3, 1.3])
        self.assertAlmostEqual(total, 1.3 + 1.0 + 1.5, places=2)  # 片尾留 1.5 秒

    # 音檔不存在時報錯，訊息裡有路徑
    def test_missing_audio(self):
        with self.assertRaisesRegex(cp.ComposeError, "nope.wav"):
            cp.load_voice(self.write_lines([{"audio": "voice/nope.wav", "start": 0, "lines": []}]))

    # 音軌長度等於片長；兩段之間安靜；整體音量校正到約 -14 LUFS
    def test_build_audio(self):
        voice, total = cp.load_voice(self.write_lines([
            {"audio": "voice/a.wav", "start": 0.3, "lines": []},
            {"audio": "voice/b.wav", "start": 2.0, "lines": []},
        ]))
        out = cp.build_audio(voice, total, self.dir / "mix.wav")
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                                   capture_output=True, text=True).stdout)
        self.assertAlmostEqual(dur, total, delta=0.02)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "f32le", "-ac", "1", "-"], capture_output=True).stdout
        samples = np.frombuffer(raw, np.float32)
        gap = samples[int(1.5 * 48000):int(1.8 * 48000)]
        self.assertLess(float(np.abs(gap).max()), 0.01)
        stats = subprocess.run(["ffmpeg", "-i", str(out), "-af", "ebur128", "-f", "null", "-"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        loudness = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", stats)[-1])
        self.assertAlmostEqual(loudness, -14.0, delta=1.5)


# 讀影片的長度和有哪些軌（video、audio）
def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    info = json.loads(out)
    return float(info["format"]["duration"]), sorted(s["codec_type"] for s in info["streams"])


class MainTest(unittest.TestCase):
    # 做一個小專案：紅色 B-roll（第 3 秒換成藍色）、兩段測試音、兩句字幕
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self.tmp.name) / "中文資料夾" / "edit"  # 中文路徑也要能跑
        (self.edit / "voice").mkdir(parents=True)
        make_video(self.edit / "broll.mp4", [("red", 3), ("blue", 3)])
        make_tone(self.edit / "voice" / "a.wav", 1.0)
        make_tone(self.edit / "voice" / "b.wav", 1.0)
        (self.edit / "voice_lines.json").write_text(json.dumps({"segments": [
            {"audio": "voice/a.wav", "start": 0.3, "lines": []},
            {"audio": "voice/b.wav", "start": 1.8, "lines": []}]}), encoding="utf-8")
        (self.edit / "cues.json").write_text(json.dumps([
            make_cue(0, 0.3, 1.3, "0.81 秒", en="0.81 seconds"), make_cue(1, 1.8, 2.8, "先看這個畫面")],
            ensure_ascii=False), encoding="utf-8")
        self.write_plan(0.0)

    def tearDown(self):
        self.tmp.cleanup()

    # 寫 合成.json：第二個鏡頭的 B-roll 從 in2 開始取
    def write_plan(self, in2, cut_ok=False):
        shot2 = {"from": "先看這個畫面", "broll": "broll.mp4", "in": in2, "section": {"small": "第一招", "big": "黏地"}}
        if cut_ok:
            shot2["cut_ok"] = True
        (self.edit / "合成.json").write_text(json.dumps({
            "title": {"text": "0.81 秒加速", "accent": ["0.81 秒"]},
            "shots": [{"from": "0.81 秒", "broll": "broll.mp4", "in": 0.0,
                       "number": {"big": "0.81 秒", "label": "0–97 km/h", "color": "red"}}, shot2]},
            ensure_ascii=False), encoding="utf-8")

    def run_main(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = cp.main([str(self.edit / "合成.json"), *args])
        return code, err.getvalue()

    # 預設輸出預覽：片長 = 最後一段配音結束 + 1.5 秒，有畫面也有聲音
    def test_preview(self):
        code, err = self.run_main()
        self.assertEqual(code, 0, err)
        dur, streams = probe(self.edit / "preview.mp4")
        self.assertAlmostEqual(dur, 1.8 + 1.0 + 1.5, delta=0.1)
        self.assertEqual(streams, ["audio", "video"])

    # --clip 只合成一段：從 1 秒開始取 2 秒
    def test_clip(self):
        code, err = self.run_main("--clip", "1", "2")
        self.assertEqual(code, 0, err)
        self.assertAlmostEqual(probe(self.edit / "clip.mp4")[0], 2.0, delta=0.1)

    # --samples：開場、數字卡、段落標題卡各一張，1080×1920
    def test_samples(self):
        code, err = self.run_main("--samples")
        self.assertEqual(code, 0, err)
        files = sorted((self.edit / "samples").glob("*.png"))
        self.assertEqual(len(files), 3)
        with Image.open(files[0]) as img:
            self.assertEqual(img.size, (1080, 1920))

    # 素材在鏡頭開頭換畫面：停下來、輸出對照圖、不合成；加上 cut_ok 後就能合成
    def test_stops_on_cut(self):
        self.write_plan(2.7)  # 素材 3.0 秒換畫面，落在第二個鏡頭開頭 0.6 秒內
        code, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("compose_check", err)
        self.assertFalse((self.edit / "preview.mp4").exists())
        self.write_plan(2.7, cut_ok=True)
        self.assertEqual(self.run_main()[0], 0)


if __name__ == "__main__":
    unittest.main()
