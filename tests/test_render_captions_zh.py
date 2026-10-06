import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


HELPERS = Path(__file__).parents[1] / "helpers"


def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = load_helper("render")
pack_transcripts = load_helper("pack_transcripts")


def zh_text():
    # imported per test, so a missing zh_text fails only the tests that use it
    if str(HELPERS) not in sys.path:
        sys.path.insert(0, str(HELPERS))
    return importlib.import_module("zh_text")


def w(text, start, end):
    return {"type": "word", "text": text, "start": start, "end": end}


def chars(text, start, step=0.1):
    """One token per character, back to back — the way Scribe returns Chinese."""
    return [w(c, round(start + i * step, 2), round(start + (i + 1) * step, 2)) for i, c in enumerate(text)]


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

    def test_zh_cues_traditional(self):
        cues, _ = self.build({"language_code": "zho", "words": chars("用软件剪视频", 0.0)}, "zh-tw")
        self.assertEqual([c[2] for c in cues], ["用軟體剪影片"])


class ChunkWordsZhScribeTests(unittest.TestCase):
    """Scribe's real shape: one token per character, punctuation its own token, Simplified."""

    def test_pause_inside_word_does_not_split(self):
        # 全 ... 0.34 s ... 力: the pause falls inside the word 全力
        words = chars("某个同学全", 9.4) + chars("力挥棒之后", 10.24)
        self.assertEqual(texts(render.chunk_words_zh(words)), ["某个同学全力挥棒之后"])

    def test_width_cap_breaks_at_word_boundary(self):
        # 19 characters with no pause; a plain cut at 14 characters falls between 伤 and 得
        words = chars("惊吓与困惑让我搞不清楚自己伤得有多重", 57.0)
        chunks = texts(render.chunk_words_zh(words))
        self.assertEqual(chunks, ["惊吓与困惑让我搞不清楚自己", "伤得有多重"])
        for c in chunks:
            self.assertLessEqual(render.display_width(c), render.ZH_CHUNK_MAX_WIDTH)

    def test_punctuation_after_pause_stays_with_previous_cue(self):
        # 折 ... 0.34 s ... ，: the comma must not open the next cue
        words = chars("颅骨多处骨折", 38.34) + [w("，", 40.02, 40.06)] + chars("两个眼窝也碎了", 40.06)
        self.assertEqual(texts(render.chunk_words_zh(words)), ["颅骨多处骨折，", "两个眼窝也碎了"])


class ToTraditionalTests(unittest.TestCase):
    def test_converts_to_taiwan_terms(self):
        self.assertEqual(zh_text().to_traditional("软件"), "軟體")
        self.assertEqual(zh_text().to_traditional("视频"), "影片")

    def test_traditional_unchanged(self):
        self.assertEqual(zh_text().to_traditional("原子習慣改變了我的人生"), "原子習慣改變了我的人生")


class WordBoundariesTests(unittest.TestCase):
    def test_token_ending_inside_word_is_not_boundary(self):
        # 某个/同学/全力/挥棒: "某个同" ends inside 同学
        self.assertEqual(zh_text().word_boundaries(["某个同", "学全力", "挥棒"]), {1, 2})

    def test_one_char_tokens(self):
        self.assertEqual(zh_text().word_boundaries(list("自己伤得")), {1, 3})

    def test_mixed_latin(self):
        self.assertEqual(zh_text().word_boundaries(["用", "Claude", "Code", "剪", "辑"]), {0, 1, 2, 4})

    def test_last_token_always_boundary(self):
        # 全 alone ends mid-word, but nothing follows it
        self.assertIn(1, zh_text().word_boundaries(["学", "全"]))


class EnModeImportTests(unittest.TestCase):
    def test_en_mode_does_not_load_chinese_libraries(self):
        # a fresh process: other tests in this run may already have imported jieba / opencc
        script = f"""
import importlib.util, json, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("render", {str(HELPERS / "render.py")!r})
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
edit = Path(tempfile.mkdtemp())
(edit / "transcripts").mkdir()
words = [{{"type": "word", "text": "hello", "start": 0.0, "end": 0.4}}]
(edit / "transcripts" / "A.json").write_text(json.dumps({{"language_code": "eng", "words": words}}), encoding="utf-8")
edl = {{"sources": {{"A": "A.mp4"}}, "ranges": [{{"source": "A", "start": 0.0, "end": 1.0}}]}}
render.build_master_srt(edl, edit, edit / "master.srt", sub_lang="en")
print(sorted(m for m in ("jieba", "opencc") if m in sys.modules))
"""
        # render.py prints "→"; force UTF-8 both ways so a cp950 console cannot break the pipe
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, encoding="utf-8", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "[]")


class PackTranscriptsTests(unittest.TestCase):
    def pack(self, transcript):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "A.json"
        # UTF-8 with real Chinese characters, not \u escapes
        path.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
        _, _, phrases = pack_transcripts.pack_one_file(path, 0.5)
        return [p["text"] for p in phrases]

    def test_chinese_traditional_without_spaces(self):
        words = chars("某个同学全力挥棒之后", 9.4) + [w("，", 10.4, 10.4)] + chars("用", 10.4) + [
            w("Claude", 10.5, 10.9), w("Code", 10.9, 11.2)] + chars("剪视频", 11.2)
        self.assertEqual(self.pack({"language_code": "zho", "words": words}),
                         ["某個同學全力揮棒之後，用 Claude Code 剪影片"])

    def test_english_unchanged(self):
        def s(start, end):
            return {"type": "spacing", "text": " ", "start": start, "end": end}
        words = [w("So", 0.0, 0.2), s(0.2, 0.25), w(",", 0.25, 0.25), s(0.25, 0.3), w("hello", 0.3, 0.6),
                 s(0.6, 0.62), w("world.", 0.62, 1.0), s(1.0, 2.0), w("Next", 2.0, 2.3), s(2.3, 2.32),
                 w("take?", 2.32, 2.7)]
        self.assertEqual(self.pack({"language_code": "eng", "words": words}), ["So, hello world.", "Next take?"])


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
