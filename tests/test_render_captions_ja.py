"""日文字幕（--sub-lang ja）和日文逐字稿打包的測試。

Scribe 回傳日文的樣子和中文一樣：一個字一個 token、標點自成一個 token。
"""

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
    if str(HELPERS) not in sys.path:
        sys.path.insert(0, str(HELPERS))
    return importlib.import_module("zh_text")


def w(text, start, end, speaker=None):
    d = {"type": "word", "text": text, "start": start, "end": end}
    if speaker:
        d["speaker_id"] = speaker
    return d


def chars(text, start, step=0.1, speaker=None):
    return [w(c, round(start + i * step, 2), round(start + (i + 1) * step, 2), speaker) for i, c in enumerate(text)]


def texts(chunks):
    return ["".join(x["text"] for x in c) for c in chunks]


# B 段實際的句子（FGO 廣播）
LONG_JA = "もうね、これも現在期間限定で公開中ですから、絶対にこの終章の朗読劇の前に見た方がいいなって思います。"


def build_srt(words, sub_lang, language_code="jpn"):
    d = tempfile.TemporaryDirectory()
    edit = Path(d.name)
    (edit / "transcripts").mkdir()
    (edit / "transcripts" / "A.json").write_text(
        json.dumps({"language_code": language_code, "words": words}, ensure_ascii=False), encoding="utf-8"
    )
    end = max(x["end"] for x in words) + 1.0
    edl = {"sources": {"A": "A.mp4"}, "ranges": [{"source": "A", "start": 0.0, "end": end}]}
    out = edit / "master.srt"
    err = io.StringIO()
    with redirect_stderr(err):
        render.build_master_srt(edl, edit, out, sub_lang=sub_lang)
    cues = [b.splitlines() for b in out.read_text(encoding="utf-8").strip().split("\n\n")]
    d.cleanup()
    return cues, err.getvalue()


class TranscriptLangTests(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(zh_text().transcript_lang({"language_code": "zho", "words": []}), "zh")
        self.assertEqual(zh_text().transcript_lang({"language_code": "jpn", "words": []}), "ja")
        self.assertEqual(zh_text().transcript_lang({"language_code": "ja", "words": []}), "ja")

    def test_kana_without_code(self):
        self.assertEqual(zh_text().transcript_lang({"words": chars("学校で勉強した", 0)}), "ja")

    def test_chinese_without_code(self):
        self.assertEqual(zh_text().transcript_lang({"words": chars("我們今天來介紹", 0)}), "zh")

    def test_english(self):
        self.assertIsNone(zh_text().transcript_lang({"language_code": "eng", "words": [w("hello", 0, 0.3)]}))


class PackJaTests(unittest.TestCase):
    def test_japanese_joined_without_spaces_not_converted(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "A.json"
        words = chars("第", 0) + [w("2", 0.1, 0.2)] + chars("部の学校で勉強しました", 0.2) + [w("。", 1.3, 1.3)]
        path.write_text(json.dumps({"language_code": "jpn", "words": words}, ensure_ascii=False), encoding="utf-8")
        _, _, phrases = pack_transcripts.pack_one_file(path, 0.5)
        # 不加空格；「学」不能被轉成繁體的「學」
        self.assertEqual([p["text"] for p in phrases], ["第2部の学校で勉強しました。"])


class WordBoundariesJaTests(unittest.TestCase):
    def test_budoux_phrases(self):
        # BudouX：バスタオルを | 持っていこうと | 思って
        self.assertEqual(zh_text().word_boundaries(list("バスタオルを持っていこうと思って"), lang="ja"), {5, 12, 15})


class ChunkWordsJaTests(unittest.TestCase):
    def test_width_cap_breaks_at_phrase_boundary(self):
        words = chars(LONG_JA, 0.0)
        chunks = render.chunk_words_ja(words, max_width=20)
        bounds = zh_text().word_boundaries([x["text"] for x in words], lang="ja")
        self.assertEqual("".join(texts(chunks)), LONG_JA)
        pos = -1
        for c in chunks[:-1]:
            pos += len(c)
            self.assertIn(pos, bounds, texts(chunks))
        for c in texts(chunks):
            self.assertLessEqual(render.display_width(c.rstrip("、。")), 20, c)

    def test_speaker_change_splits(self):
        words = chars("本当に", 0.0, speaker="speaker_0") + chars("すごいよね", 0.3, speaker="speaker_1")
        self.assertEqual(texts(render.chunk_words_ja(words)), ["本当に", "すごいよね"])


class FormatCueJaTests(unittest.TestCase):
    def fmt(self, text):
        return render._format_cue_ja(chars(text, 0.0))

    def test_no_spaces_no_conversion(self):
        self.assertEqual(self.fmt("学校で勉強しました"), "学校で勉強しました")

    def test_inner_punctuation_becomes_en_space(self):
        self.assertEqual(self.fmt("学校で、勉強しました。"), "学校で 勉強しました")

    def test_question_mark_kept(self):
        self.assertEqual(self.fmt("どう思います？"), "どう思います？")

    def test_no_space_beside_digits(self):
        # 日文習慣：數字兩邊不加空格（中文模式維持「第 2 部」）
        words = chars("第", 0.0) + [w("2", 0.1, 0.2)] + chars("部と", 0.2) + [w("21", 0.4, 0.5)] + chars("時", 0.5)
        self.assertEqual(render._format_cue_ja(words), "第2部と21時")

    def test_space_beside_latin_words_kept(self):
        words = chars("今日は", 0.0) + [w("Claude", 0.3, 0.6), w("Code", 0.6, 0.9)] + chars("で", 0.9)
        self.assertEqual(render._format_cue_ja(words), "今日は Claude Code で")


class BuildMasterSrtJaTests(unittest.TestCase):
    def test_ja_cues(self):
        cues, err = build_srt(chars("マスターたち、マジで受け取るのうまいよなって思ってた。", 0.0), "ja")
        self.assertTrue(all(" " not in c[2] for c in cues), cues)
        self.assertNotIn("--sub-lang", err)

    def test_ja_transcript_in_en_mode_warns(self):
        _, err = build_srt(chars("学校で勉強した", 0.0), "en")
        self.assertIn("--sub-lang ja", err)

    def test_backchannel_dropped_and_no_overlap(self):
        # 長度 0 的「うん」緊接另一位說話者：只會閃一下，拿掉（和中文規則一樣）
        words = [w("うん", 1.0, 1.0, "speaker_1")] + chars("確かにそうですね", 1.06, 0.2, "speaker_0")
        cues, _ = build_srt(words, "ja")
        self.assertEqual([c[2] for c in cues], ["確かにそうですね"])


def srt_seconds(ts):
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


class ShortCueRescueTests(unittest.TestCase):
    """太短的句子先延長、再借字，都不行才拿掉（B 段實測發現「する」「いや」消失）。"""

    def test_short_tail_extended_into_silence(self):
        # 16 字超過上限，切完剩下 0.16 秒的「する。」；後面有 1.2 秒空白 → 延長到 0.8 秒
        words = chars("多分すごいもらう日になる気が", 73.58, 0.1, "speaker_1") + [
            w("す", 75.12, 75.2, "speaker_1"), w("る", 75.2, 75.28, "speaker_1"), w("。", 75.28, 75.28, "speaker_1"),
        ] + chars("感覚が", 76.5, 0.14, "speaker_1")
        cues, _ = build_srt(words, "ja")
        texts_ = [c[2] for c in cues]
        self.assertIn("する", "".join(texts_))
        cue = next(c for c in cues if c[2].endswith("する"))
        start, end = (srt_seconds(x) for x in cue[1].split(" --> "))
        self.assertGreaterEqual(end - start, 0.79)

    def test_short_cue_borrows_from_next(self):
        # 「いや、」只有 0.16 秒，前一句以「。」結束、後面沒有空白 → 向下一句借字
        words = chars("お気をつけいただいて", 147.1, 0.1, "speaker_1") + [w("。", 148.1, 148.1, "speaker_1")] + [
            w("い", 148.3, 148.34, "speaker_1"), w("や", 148.34, 148.46, "speaker_1"), w("、", 148.46, 148.46, "speaker_1"),
        ] + chars("リンさんも頑張ってください", 148.52, 0.12, "speaker_1") + [w("。", 150.08, 150.08, "speaker_1")]
        cues, _ = build_srt(words, "ja")
        joined = "".join(c[2] for c in cues)
        self.assertIn("いや", joined)
        self.assertTrue(any(c[2].startswith("いや") and len(c[2]) > 3 for c in cues), [c[2] for c in cues])

    def test_readable_short_cue_does_not_borrow(self):
        # 0.78 秒的「我90分可不可以，」看得清楚，不能向下一句借字變成「…，但」（podcast 實測）
        words = chars("我", 0.0, 0.1) + [w("90", 0.1, 0.3)] + chars("分可不可以", 0.3, 0.09) + [w("，", 0.78, 0.78)] + \
            chars("但我剩下", 0.78, 0.2) + [w("10", 1.58, 1.8)] + chars("分", 1.8, 0.2)
        cues, _ = build_srt(words, "zh-tw", "zho")
        self.assertEqual([c[2] for c in cues], ["我 90 分可不可以", "但我剩下 10 分"])

    def test_zero_length_cue_not_stacked(self):
        # Scribe 把搶話的「確かに。」壓成長度 0、起點和下一句相同 → 不能兩句同時出現
        words = chars("思います", 11.0, 0.3, "speaker_0") + [w("。", 12.2, 12.2, "speaker_0")] + [
            w(c, 12.3, 12.3, "speaker_1") for c in "確かに。"
        ] + chars("なんかちょっとね", 12.3, 0.08, "speaker_1") + [w("、", 12.94, 12.94, "speaker_1")] + chars(
            "尺あるから", 13.0, 0.25, "speaker_1")
        cues, _ = build_srt(words, "ja")
        self.assertIn("確かに", "".join(c[2] for c in cues))
        times = [[srt_seconds(x) for x in c[1].split(" --> ")] for c in cues]
        for (_, end), (start, _) in zip(times, times[1:]):
            self.assertLessEqual(end, start + 1e-6)


class SubFontTests(unittest.TestCase):
    def test_ja_default_font_per_platform(self):
        self.assertEqual(render.ja_default_font("win32"), "Yu Gothic")
        self.assertEqual(render.ja_default_font("darwin"), "Hiragino Sans")
        self.assertEqual(render.ja_default_font("linux"), "Noto Sans CJK JP")

    def test_font_override(self):
        style = render.sub_force_style("en", font="Arial")
        self.assertIn("FontName=Arial", style)
        self.assertNotIn("Helvetica", style)

    def test_no_override_keeps_language_font(self):
        self.assertIn("FontName=Microsoft JhengHei", render.sub_force_style("zh-tw"))
        self.assertIn("FontName=Helvetica", render.sub_force_style("en"))


class LazyBudouxTests(unittest.TestCase):
    def test_en_and_zh_do_not_load_budoux(self):
        script = f"""
import importlib.util, json, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("render", {str(HELPERS / "render.py")!r})
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
for lang, code, text in (("en", "eng", "hello"), ("zh-tw", "zho", "你好")):
    edit = Path(tempfile.mkdtemp())
    (edit / "transcripts").mkdir()
    words = [{{"type": "word", "text": text, "start": 0.0, "end": 0.9}}]
    (edit / "transcripts" / "A.json").write_text(json.dumps({{"language_code": code, "words": words}}), encoding="utf-8")
    edl = {{"sources": {{"A": "A.mp4"}}, "ranges": [{{"source": "A", "start": 0.0, "end": 1.0}}]}}
    render.build_master_srt(edl, edit, edit / "master.srt", sub_lang=lang)
print("budoux" in sys.modules)
"""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, encoding="utf-8", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "False")


if __name__ == "__main__":
    unittest.main()
