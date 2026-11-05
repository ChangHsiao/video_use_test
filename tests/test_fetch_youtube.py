"""fetch_youtube.py 的字幕轉換測試（不連網）。"""
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "helpers" / "fetch_youtube.py"
SPEC = importlib.util.spec_from_file_location("video_use_fetch_youtube", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_youtube = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_youtube)


# 假的 YouTube json3 字幕：兩個 event，第二個裡有 [Music] 標記
JSON3 = {
    "events": [
        {"tStartMs": 1000, "dDurationMs": 2000, "segs": [
            {"utf8": "hello"},
            {"utf8": " world", "tOffsetMs": 300},
        ]},
        {"tStartMs": 1350, "dDurationMs": 10, "segs": [{"utf8": "\n"}]},  # 只有換行，要略過
        {"tStartMs": 3000, "dDurationMs": 2500, "segs": [
            {"utf8": "[Music]"},
            {"utf8": " again", "tOffsetMs": 200},
        ]},
    ]
}


def convert(lang="en"):
    return fetch_youtube.json3_to_scribe(JSON3, lang=lang, source="test.json3")


class Json3ToScribeTest(unittest.TestCase):
    def test_word_times(self):
        words = [w for w in convert()["words"] if w["type"] != "spacing"]
        self.assertEqual([w["text"] for w in words], ["hello", "world", "Music", "again"])
        # hello：下一個字 1.3 秒才開始，間隔 0.3 秒，沒超過 0.6
        self.assertEqual((words[0]["start"], words[0]["end"]), (1.0, 1.3))
        # world：下一個字 3.0 秒，最多只算 0.6 秒
        self.assertEqual((words[1]["start"], words[1]["end"]), (1.3, 1.9))
        # again：最後一個字，結束時間以影片結尾（5.5 秒）為上限，再套 0.6 秒
        self.assertEqual((words[3]["start"], words[3]["end"]), (3.2, 3.8))

    def test_spacing_fills_gaps(self):
        words = convert()["words"]
        gaps = [(w["start"], w["end"]) for w in words if w["type"] == "spacing"]
        self.assertIn((1.9, 3.0), gaps)  # world 結束到 [Music] 開始
        # 每個字和下一個字之間沒有空洞
        for a, b in zip(words, words[1:]):
            self.assertEqual(a["end"], b["start"])

    def test_bracket_becomes_audio_event(self):
        music = [w for w in convert()["words"] if w["text"] == "Music"][0]
        self.assertEqual(music["type"], "audio_event")

    def test_duration_and_text(self):
        result = convert()
        self.assertEqual(result["audio_duration_secs"], 5.5)
        self.assertEqual(result["text"], "hello world again")

    def test_language_code(self):
        cases = {"en": "eng", "en-US": "eng", "zh": "zho", "zh-TW": "zho",
                 "zh-Hant": "zho", "ja": "jpn", "ko": "ko"}
        for lang, code in cases.items():
            with self.subTest(lang=lang):
                self.assertEqual(convert(lang)["language_code"], code)


if __name__ == "__main__":
    unittest.main()
