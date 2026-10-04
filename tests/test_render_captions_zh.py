import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "helpers" / "render.py"
SPEC = importlib.util.spec_from_file_location("video_use_render", MODULE_PATH)
assert SPEC and SPEC.loader
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def w(text, start, end):
    return {"type": "word", "text": text, "start": start, "end": end}


# "今天我們來介紹，怎麼用 Claude Code 剪影片。你覺得好用嗎？"
TAKE_ZH = [
    w("今天", 0.00, 0.30), w("我們", 0.32, 0.55), w("來", 0.57, 0.70), w("介紹，", 0.72, 1.10),
    w("怎麼", 1.30, 1.50), w("用", 1.52, 1.65), w("Claude", 1.67, 2.00), w("Code", 2.02, 2.30),
    w("剪影片。", 2.32, 3.00),
    w("你", 3.60, 3.70), w("覺得", 3.72, 3.95), w("好用", 3.97, 4.20), w("嗎？", 4.22, 4.50),
]


def texts(chunks):
    return [render.join_zh([x["text"] for x in c]) for c in chunks]


class JoinZhTests(unittest.TestCase):
    def test_no_space_between_chinese(self):
        self.assertEqual(render.join_zh(["今天", "我們", "來"]), "今天我們來")

    def test_space_around_latin(self):
        self.assertEqual(render.join_zh(["用", "Claude", "Code", "剪片"]), "用 Claude Code 剪片")

    def test_strips_token_whitespace(self):
        self.assertEqual(render.join_zh([" 今天", "我們 "]), "今天我們")


class ChunkWordsZhTests(unittest.TestCase):
    def test_take(self):
        self.assertEqual(
            texts(render.chunk_words_zh(TAKE_ZH)),
            ["今天我們來介紹，", "怎麼用 Claude Code 剪影片。", "你覺得好用嗎？"],
        )

    def test_pause_splits(self):
        words = [w("這是", 0.0, 0.3), w("第一段", 0.32, 0.8), w("這是", 1.3, 1.5), w("第二段", 1.52, 2.0)]
        self.assertEqual(texts(render.chunk_words_zh(words)), ["這是第一段", "這是第二段"])

    def test_width_cap(self):
        # 30 characters spoken without a pause, one token per character
        chars = "我們今天要來介紹一個可以用對話剪輯影片的工具它叫做影片剪輯"
        words = [w(c, i * 0.1, i * 0.1 + 0.1) for i, c in enumerate(chars)]
        chunks = render.chunk_words_zh(words)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(render.display_width(render.join_zh([x["text"] for x in c])), render.ZH_CHUNK_MAX_WIDTH)
        self.assertEqual("".join(texts(chunks)), chars)

    def test_trailing_punctuation_not_counted(self):
        # width 29 with "。", 27 once the "。" is stripped from the cue: stays one cue
        words = [w("怎麼", 1.55, 1.75), w("用", 1.77, 1.90), w("Claude", 1.92, 2.25), w("Code", 2.27, 2.55),
                 w("剪輯", 2.57, 2.85), w("影片。", 2.87, 3.40)]
        self.assertEqual(texts(render.chunk_words_zh(words)), ["怎麼用 Claude Code 剪輯影片。"])

    def test_short_cue_merges_across_punctuation(self):
        # "好，" alone would flash for 0.2 s
        words = [w("好，", 0.0, 0.2), w("我們", 0.22, 0.5), w("開始", 0.52, 0.9)]
        self.assertEqual(texts(render.chunk_words_zh(words)), ["好，我們開始"])

    def test_short_cue_kept_across_pause(self):
        words = [w("好。", 0.0, 0.2), w("我們", 0.8, 1.1), w("開始", 1.12, 1.6)]
        self.assertEqual(texts(render.chunk_words_zh(words)), ["好。", "我們開始"])

    def test_skips_empty_words(self):
        self.assertEqual(texts(render.chunk_words_zh([w(" ", 0, 0.1), w("好", 0.1, 0.9)])), ["好"])


class DisplayWidthTests(unittest.TestCase):
    def test_widths(self):
        self.assertEqual(render.display_width("中文"), 4)
        self.assertEqual(render.display_width("ab c"), 4)
        self.assertEqual(render.display_width("好，"), 4)


class BuildMasterSrtZhTests(unittest.TestCase):
    def build(self, transcript, sub_lang):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        edit = Path(d.name)
        (edit / "transcripts").mkdir()
        (edit / "transcripts" / "A.json").write_text(
            json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
        )
        edl = {"sources": {"A": "A.mp4"}, "ranges": [{"source": "A", "start": 0.0, "end": 5.0}]}
        out = edit / "master.srt"
        err = io.StringIO()
        with redirect_stderr(err):
            render.build_master_srt(edl, edit, out, sub_lang=sub_lang)
        cues = [b.splitlines() for b in out.read_text(encoding="utf-8").strip().split("\n\n")]
        return cues, err.getvalue()

    def test_zh_cues(self):
        cues, _ = self.build({"language_code": "zho", "words": TAKE_ZH}, "zh-tw")
        # trailing ，。 dropped, ？ kept, no uppercasing of Latin words
        self.assertEqual([c[2] for c in cues], ["今天我們來介紹", "怎麼用 Claude Code 剪影片", "你覺得好用嗎？"])
        self.assertEqual(cues[1][1], "00:00:01,300 --> 00:00:03,000")

    def test_zh_transcript_in_en_mode_warns(self):
        _, err = self.build({"language_code": "zho", "words": TAKE_ZH}, "en")
        self.assertIn("--sub-lang zh-tw", err)

    def test_zh_mode_does_not_warn(self):
        _, err = self.build({"language_code": "zho", "words": TAKE_ZH}, "zh-tw")
        self.assertNotIn("--sub-lang", err)


class LooksChineseTests(unittest.TestCase):
    def test_language_code(self):
        for code in ("zh", "zho", "cmn", "yue"):
            self.assertTrue(render.looks_chinese({"language_code": code, "words": []}), code)

    def test_english(self):
        words = [w("hello", 0, 0.3), w("world", 0.3, 0.6)]
        self.assertFalse(render.looks_chinese({"language_code": "eng", "words": words}))

    def test_cjk_text_without_language_code(self):
        self.assertTrue(render.looks_chinese({"words": TAKE_ZH}))


if __name__ == "__main__":
    unittest.main()
