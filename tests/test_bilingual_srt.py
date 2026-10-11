"""bilingual_srt.py（翻譯結果 → 雙語字幕、審稿清單）的測試。"""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


HELPERS = Path(__file__).parents[1] / "helpers"


def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bi = load_helper("bilingual_srt")

YELLOW = "#FFD54F"
PURPLE = "#CE93D8"

# 四句的日文草稿：前三句田中（黃），第四句高橋（紫）
DRAFT = """1
00:00:01,000 --> 00:00:02,000
<font color="#FFD54F">もう私は</font>

2
00:00:02,100 --> 00:00:03,000
<font color="#FFD54F">やばいって思ってるんで</font>

3
00:00:03,200 --> 00:00:04,500
<font color="#FFD54F">バスタオルを持っていこうと</font>

4
00:00:04,600 --> 00:00:05,000
<font color="#CE93D8">思って</font>
"""


def group(a, b, src, tr, **extra):
    return {"from": a, "to": b, "src": src, "tr": tr, **extra}


def translation(cues, drop=None, **extra):
    return {"draft": "master.srt", "source_lang": "ja", "target_lang": "zh-tw",
            "cues": cues, "drop": drop or [], **extra}


class ParseSrtTest(unittest.TestCase):
    def test_reads_times_text_and_colour(self):
        cues = bi.parse_srt(DRAFT)
        self.assertEqual([c.index for c in cues], [1, 2, 3, 4])
        self.assertEqual((cues[0].start, cues[0].end), (1.0, 2.0))
        self.assertEqual(cues[1].text, "やばいって思ってるんで")
        self.assertEqual(cues[3].colour, PURPLE)

    def test_cue_without_colour(self):
        cues = bi.parse_srt("1\n00:00:00,000 --> 00:00:01,500\nこんにちは\n")
        self.assertEqual(cues[0].text, "こんにちは")
        self.assertIsNone(cues[0].colour)
        self.assertEqual(cues[0].end, 1.5)


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.cues = bi.parse_srt(DRAFT)

    def errors(self, groups, drop=None):
        return bi.validate(translation(groups, drop), self.cues)

    def test_complete_cover_is_ok(self):
        self.assertEqual(self.errors([group(1, 2, "a", "甲"), group(3, 4, "b", "乙")]), [])

    def test_drop_counts_as_covered(self):
        self.assertEqual(self.errors([group(1, 3, "a", "甲")], drop=[4]), [])

    def test_missing_cue(self):
        errs = self.errors([group(1, 2, "a", "甲")])
        self.assertTrue(any("3" in e and "4" in e for e in errs), errs)

    def test_overlapping_groups(self):
        errs = self.errors([group(1, 2, "a", "甲"), group(2, 4, "b", "乙")])
        self.assertTrue(errs)

    def test_out_of_order(self):
        errs = self.errors([group(3, 4, "b", "乙"), group(1, 2, "a", "甲")])
        self.assertTrue(errs)

    def test_out_of_range(self):
        errs = self.errors([group(1, 5, "a", "甲")])
        self.assertTrue(any("5" in e for e in errs), errs)

    def test_from_after_to(self):
        errs = self.errors([group(2, 1, "a", "甲"), group(3, 4, "b", "乙")])
        self.assertTrue(errs)

    def test_empty_text(self):
        errs = self.errors([group(1, 2, "a", " "), group(3, 4, "", "乙")])
        self.assertEqual(len(errs), 2, errs)

    def test_dropped_cue_also_in_group(self):
        errs = self.errors([group(1, 2, "a", "甲"), group(3, 4, "b", "乙")], drop=[4])
        self.assertTrue(errs)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.cues = bi.parse_srt(DRAFT)

    def build(self, groups, max_width=28, **kw):
        return bi.build(self.cues, translation(groups), max_width=max_width,
                        src_font="Yu Gothic", **kw)

    def test_time_from_first_and_last_cue(self):
        r = self.build([group(1, 2, "もう私はやばいって思ってるんで", "我已經覺得一定會哭"),
                        group(3, 3, "バスタオルを持っていこうと", "所以要帶浴巾"),
                        group(4, 4, "思って", "去")])
        self.assertEqual([(a, b) for a, b, _ in r.bilingual], [(1.0, 3.0), (3.2, 4.5), (4.6, 5.0)])

    def test_bilingual_line_format(self):
        r = self.build([group(1, 3, "もう私はやばいって思ってるんで", "我已經覺得會哭爆"), group(4, 4, "思って", "嗯")])
        text = r.bilingual[0][2]
        self.assertEqual(
            text,
            f'<font color="{YELLOW}">我已經覺得會哭爆\n'
            f'<font face="Yu Gothic" size="14">もう私はやばいって思ってるんで</font></font>',
        )

    def test_single_language_tracks_keep_colour(self):
        r = self.build([group(1, 3, "もう私は", "我"), group(4, 4, "思って", "嗯")])
        self.assertEqual(r.src_only[1][2], f'<font color="{PURPLE}">思って</font>')
        self.assertEqual(r.tr_only[0][2], f'<font color="{YELLOW}">我</font>')

    def test_no_colour_in_draft(self):
        cues = bi.parse_srt("1\n00:00:00,000 --> 00:00:01,000\nはい\n")
        r = bi.build(cues, translation([group(1, 1, "はい", "好")]), max_width=28, src_font="Yu Gothic")
        self.assertEqual(r.bilingual[0][2], '好\n<font face="Yu Gothic" size="14">はい</font>')

    def test_src_scale_sets_size(self):
        r = self.build([group(1, 4, "a", "甲")], src_scale=0.5)
        self.assertIn('size="9"', r.bilingual[0][2])

    def test_warns_when_group_spans_speakers(self):
        r = self.build([group(1, 2, "a", "甲"), group(3, 4, "b", "乙")])
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("3", r.warnings[0])

    def test_warns_when_translation_too_wide(self):
        # 上限 28 = 14 個全形字；剛好 14 個不警告，15 個才警告
        ok = self.build([group(1, 3, "a", "一" * 14), group(4, 4, "b", "乙")])
        self.assertEqual(ok.warnings, [])
        long = self.build([group(1, 3, "a", "一" * 15), group(4, 4, "b", "乙")])
        self.assertEqual(len(long.warnings), 1)

    def test_warns_when_source_too_wide(self):
        # 原文行縮成 0.75：上限 28 / 0.75 = 37.3 → 18 個全形字可以，19 個警告
        ok = self.build([group(1, 3, "あ" * 18, "甲"), group(4, 4, "b", "乙")])
        self.assertEqual(ok.warnings, [])
        long = self.build([group(1, 3, "あ" * 19, "甲"), group(4, 4, "b", "乙")])
        self.assertEqual(len(long.warnings), 1)

    def test_merge_only_is_not_a_fix(self):
        r = self.build([group(1, 3, "もう私は、やばいって思ってるんで バスタオルを持っていこうと", "甲"),
                        group(4, 4, "思って。", "乙")])
        self.assertEqual(r.fixes, [])

    def test_changed_source_is_listed(self):
        cues = bi.parse_srt("1\n00:00:00,000 --> 00:00:01,000\nこの秋生の朗読劇\n")
        r = bi.build(cues, translation([group(1, 1, "この終章の朗読劇", "這次終章的朗讀劇")]),
                     max_width=28, src_font="Yu Gothic")
        self.assertEqual(len(r.fixes), 1)
        self.assertEqual(r.fixes[0][1:], ("この秋生の朗読劇", "この終章の朗読劇"))

    def test_checks_are_collected(self):
        r = self.build([group(1, 3, "a", "甲", check="やばい：推測"), group(4, 4, "b", "乙")])
        self.assertEqual(len(r.checks), 1)
        self.assertIn("推測", r.checks[0]["check"])


class MaxWidthTest(unittest.TestCase):
    """雙語的上限放寬到 18 字；render.zh_max_width 不傳 cap 時和原本一樣。"""

    def test_render_default_unchanged(self):
        self.assertEqual(bi.render.zh_max_width(1920, 1080), 28)
        self.assertEqual(bi.render.zh_max_width(1080, 1920), 20)

    def test_bilingual_cap(self):
        cap = 2 * bi.BILINGUAL_MAX_CHARS
        self.assertEqual(bi.render.zh_max_width(1920, 1080, cap=cap), 36)
        self.assertEqual(bi.render.zh_max_width(1080, 1920, cap=cap), 20)  # 直式仍依實際寬度

    def test_no_edl_falls_back_to_bilingual_cap(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(bi._max_width_from_edl(Path(d) / "edl.json"), 36)

    def test_source_line_uses_what_fits_on_screen(self):
        # 原文行的上限是畫面放得下的長度（1920×1080 原尺寸 35 字），不是譯文上限 ÷ 0.75
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(bi._line_fit_from_edl(Path(d) / "edl.json"), 70)
        cues = bi.parse_srt(DRAFT)
        groups = [group(1, 3, "あ" * 30, "甲"), group(4, 4, "b", "乙")]
        loose = bi.build(cues, translation(groups), max_width=36, src_font="Yu Gothic", src_max_width=70 / 0.75)
        self.assertEqual(loose.warnings, [])
        strict = bi.build(cues, translation(groups), max_width=36, src_font="Yu Gothic")
        self.assertEqual(len(strict.warnings), 1)


class RunTest(unittest.TestCase):
    """端對端：檔案讀寫、草稿雜湊、輸出檔名。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "master.srt").write_text(DRAFT, encoding="utf-8")
        self.tr_path = self.dir / "translation.json"
        data = translation([group(1, 3, "もう私はやばいって思ってるんで", "我已經覺得會哭爆", check="推測"),
                            group(4, 4, "思って", "嗯")])
        self.tr_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            bi.run(self.tr_path, max_chars=14, src_font="Yu Gothic")
        return out.getvalue(), err.getvalue()

    def test_writes_outputs_and_stamps_hash(self):
        self.run_tool()
        for name in ("master_bilingual.srt", "master_ja.srt", "master_zh-tw.srt", "translation_review.md"):
            self.assertTrue((self.dir / name).exists(), name)
        stamped = json.loads(self.tr_path.read_text(encoding="utf-8"))
        self.assertEqual(len(stamped["draft_sha256"]), 64)
        self.assertEqual(stamped["cues"][0]["tr"], "我已經覺得會哭爆")  # 其他欄位原樣保留
        srt = (self.dir / "master_bilingual.srt").read_text(encoding="utf-8")
        self.assertTrue(srt.startswith("1\n00:00:01,000 --> 00:00:04,500\n"))
        review = (self.dir / "translation_review.md").read_text(encoding="utf-8")
        self.assertIn("推測", review)

    def test_same_draft_runs_again(self):
        self.run_tool()
        self.run_tool()

    def test_changed_draft_stops(self):
        self.run_tool()
        (self.dir / "master.srt").write_text(DRAFT.replace("思って", "思った"), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_tool()

    def test_rerun_overwrites_without_backup(self):
        self.run_tool()
        data = json.loads(self.tr_path.read_text(encoding="utf-8"))
        data["cues"][1]["tr"] = "對"
        self.tr_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.run_tool()
        self.assertIn("對", (self.dir / "master_zh-tw.srt").read_text(encoding="utf-8"))
        self.assertEqual(list(self.dir.glob("*.bak-*")), [])

    def test_invalid_groups_stop_without_output(self):
        data = translation([group(1, 2, "a", "甲")])
        self.tr_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_tool()
        self.assertFalse((self.dir / "master_bilingual.srt").exists())


if __name__ == "__main__":
    unittest.main()
