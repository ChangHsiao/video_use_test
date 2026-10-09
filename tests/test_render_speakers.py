"""說話者顏色（EDL speakers）和說話者修正（EDL speaker_fixes）的測試。"""

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


render = load_helper("render")

YELLOW = "#FFD54F"
PURPLE = "#CE93D8"
SPEAKERS = {"A": {"speaker_0": {"name": "田中", "color": YELLOW}, "speaker_1": {"name": "高橋", "color": PURPLE}}}


def w(text, start, end, speaker):
    return {"type": "word", "text": text, "start": start, "end": end, "speaker_id": speaker}


def chars(text, start, speaker, step=0.15):
    return [w(c, round(start + i * step, 2), round(start + (i + 1) * step, 2), speaker) for i, c in enumerate(text)]


def build(words, sub_lang="ja", code="jpn", **edl_extra):
    with tempfile.TemporaryDirectory() as d:
        edit = Path(d)
        (edit / "transcripts").mkdir()
        (edit / "transcripts" / "A.json").write_text(
            json.dumps({"language_code": code, "words": words}, ensure_ascii=False), encoding="utf-8"
        )
        end = max(x["end"] for x in words) + 1.0
        edl = {"sources": {"A": "A.mp4"}, "ranges": [{"source": "A", "start": 0.0, "end": end}], **edl_extra}
        out = edit / "master.srt"
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            render.build_master_srt(edl, edit, out, sub_lang=sub_lang)
        return [b.splitlines()[2] for b in out.read_text(encoding="utf-8").strip().split("\n\n")]


# 田中問、高橋答（中間停 0.5 秒）
TALK = chars("どう思います？", 0.0, "speaker_0") + chars("まだ信じきれてない", 1.6, "speaker_1")


class SpeakerColorTests(unittest.TestCase):
    def test_cues_wrapped_in_speaker_colour(self):
        self.assertEqual(build(TALK, speakers=SPEAKERS), [
            f'<font color="{YELLOW}">どう思います？</font>',
            f'<font color="{PURPLE}">まだ信じきれてない</font>',
        ])

    def test_no_speakers_no_tags(self):
        self.assertEqual(build(TALK), ["どう思います？", "まだ信じきれてない"])

    def test_unknown_speaker_left_plain(self):
        only_one = {"A": {"speaker_0": {"name": "田中", "color": YELLOW}}}
        self.assertEqual(build(TALK, speakers=only_one)[1], "まだ信じきれてない")

    def test_other_source_ignored(self):
        self.assertEqual(build(TALK, speakers={"B": SPEAKERS["A"]}), ["どう思います？", "まだ信じきれてない"])

    def test_bad_colour_rejected(self):
        bad = {"A": {"speaker_0": {"name": "田中", "color": "yellow"}}}
        with self.assertRaises(ValueError) as cm:
            build(TALK, speakers=bad)
        self.assertIn("speaker_0", str(cm.exception))

    def test_english_cues_split_by_speaker(self):
        # 英文的兩字一句不會在換人時斷開；設定顏色後要斷開，不然一句會有兩個人的字
        words = [w("so", 0.0, 0.2, "speaker_0"), w("yes", 0.25, 0.5, "speaker_1"), w("right", 0.55, 0.8, "speaker_1")]
        cues = build(words, "en", "eng", speakers=SPEAKERS)
        self.assertEqual(cues, [f'<font color="{YELLOW}">SO</font>', f'<font color="{PURPLE}">YES RIGHT</font>'])

    def test_english_without_speakers_unchanged(self):
        words = [w("so", 0.0, 0.2, "speaker_0"), w("yes", 0.25, 0.5, "speaker_1"), w("right", 0.55, 0.8, "speaker_1")]
        self.assertEqual(build(words, "en", "eng"), ["SO YES", "RIGHT"])


class SpeakerFixTests(unittest.TestCase):
    def test_fix_relabels_words_in_range(self):
        # Scribe 把高橋的回答標成田中（同一個說話者 → 原本會併成一句）
        words = chars("どう思います？", 0.0, "speaker_0") + chars("まだ信じきれてない", 1.6, "speaker_0")
        fixes = [{"source": "A", "start": 1.5, "end": 3.0, "speaker": "speaker_1"}]
        cues = build(words, speakers=SPEAKERS, speaker_fixes=fixes)
        self.assertEqual(cues[-1], f'<font color="{PURPLE}">まだ信じきれてない</font>')

    def test_fix_splits_cue_at_new_speaker(self):
        # 「でも」是田中、後面是高橋：修正後要斷成兩句（不會因為太短就併回同一句）
        words = chars("でも終章の結末までを描くんですよ", 0.0, "speaker_1", 0.2)
        fixes = [{"source": "A", "start": 0.0, "end": 0.35, "speaker": "speaker_0"}]
        cues = build(words, speakers=SPEAKERS, speaker_fixes=fixes)
        self.assertTrue(cues[0].startswith(f'<font color="{YELLOW}">でも'), cues)
        self.assertNotIn("終章", cues[0])

    def test_fix_for_other_source_ignored(self):
        words = chars("まだ信じきれてない", 0.0, "speaker_1")
        fixes = [{"source": "B", "start": 0.0, "end": 9.0, "speaker": "speaker_0"}]
        self.assertEqual(build(words, speakers=SPEAKERS, speaker_fixes=fixes),
                         [f'<font color="{PURPLE}">まだ信じきれてない</font>'])

    def test_fix_does_not_change_transcript_file(self):
        with tempfile.TemporaryDirectory() as d:
            edit = Path(d)
            (edit / "transcripts").mkdir()
            path = edit / "transcripts" / "A.json"
            original = json.dumps({"language_code": "jpn", "words": TALK}, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            edl = {"sources": {"A": "A.mp4"}, "ranges": [{"source": "A", "start": 0.0, "end": 5.0}],
                   "speaker_fixes": [{"source": "A", "start": 0.0, "end": 5.0, "speaker": "speaker_1"}]}
            with redirect_stdout(io.StringIO()):
                render.build_master_srt(edl, edit, edit / "master.srt", sub_lang="ja")
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
