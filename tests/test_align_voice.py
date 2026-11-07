"""align_voice.py（配音的停頓 → 每句字幕的時間）的測試。"""

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


HELPERS = Path(__file__).parents[1] / "helpers"


# 用檔案路徑載入 helpers 裡的程式（helpers 不是套件，不能直接 import）
def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


av = load_helper("align_voice")

EN_SPACE = " "


# 用 ffmpeg 做一段合成音：("tone", 秒) 是聲音、("gap", 秒) 是靜音，依序接起來
def make_audio(path, parts):
    inputs, labels = [], []
    for i, (kind, sec) in enumerate(parts):
        if kind == "tone":
            inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=16000:duration={sec}"]
        else:
            inputs += ["-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono:d={sec}"]
        labels.append(f"[{i}:a]")
    graph = "".join(labels) + f"concat=n={len(parts)}:v=0:a=1[out]"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[out]", "-ac", "1", str(path)],
        check=True,
    )


# 做一句測試用的字幕資料（合併、輸出的測試直接用，不經過聲音）
def make_cue(start, end, show, say=None, en=None, seg=0):
    return {"seg": seg, "start": start, "end": end, "show": show,
            "say": say if say is not None else show + "，", "en": en, "virtual": False}


class EstimateLengthTest(unittest.TestCase):
    # 中文一個字算 1，英文單字依字母數算（單一字母的 G 算 1、Roadster 算 3），標點不算
    def test_cjk_and_english_words(self):
        self.assertEqual(av.estimate_length("零點八一秒，"), 5)
        self.assertEqual(av.estimate_length("兩 G。"), 2)
        self.assertEqual(av.estimate_length("新 Roadster。"), 4)
        self.assertEqual(av.estimate_length("It flies."), 3)


class SentenceEndTest(unittest.TestCase):
    # 句號、問號、驚嘆號（中英文）算一句結束，逗號不算
    def test_end_marks(self):
        for say in ["它還會飛。", "怎麼辦？", "好！", "It flies.", "Why?", "Go!"]:
            self.assertTrue(av.ends_sentence(say), say)
        for say in ["而且，", "車尾有主推進器，", "答案是：", "沒有標點"]:
            self.assertFalse(av.ends_sentence(say), say)

    # 結尾的引號、括號先去掉再判斷
    def test_closing_quotes_and_brackets(self):
        self.assertTrue(av.ends_sentence("他說：「好。」"))
        self.assertTrue(av.ends_sentence("（示意圖。）"))
        self.assertTrue(av.ends_sentence('He said "yes."'))
        self.assertFalse(av.ends_sentence("「而且，」"))


class PlaceBoundariesTest(unittest.TestCase):
    # 停頓數剛好等於分界數時，每個分界都落在對的停頓上
    def test_exact_pauses(self):
        pauses = [(1.0, 1.3), (3.3, 3.6)]
        spans = av.place_boundaries(pauses, 0.0, 4.6, [5, 10, 5])
        self.assertEqual(len(spans), 3)
        expected = [(0.0, 1.0), (1.3, 3.3), (3.6, 4.6)]
        for (st, en, virtual), (est, een) in zip(spans, expected):
            self.assertAlmostEqual(st, est, places=2)
            self.assertAlmostEqual(en, een, places=2)
            self.assertFalse(virtual)

    # 停頓比較多時（例如換氣），離估計位置遠的停頓被跳過
    def test_extra_pause_skipped(self):
        pauses = [(1.0, 1.3), (2.3, 2.6)]
        spans = av.place_boundaries(pauses, 0.0, 3.6, [5, 10])
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[0][1], 1.0, places=2)
        self.assertAlmostEqual(spans[1][0], 1.3, places=2)
        self.assertAlmostEqual(spans[1][1], 3.6, places=2)

    # 停頓比較少時不會當掉，硬切的分界標成 virtual
    def test_fewer_pauses_than_lines(self):
        spans = av.place_boundaries([], 0.0, 3.0, [5, 5, 5])
        self.assertEqual(len(spans), 3)
        self.assertTrue(spans[0][2])
        self.assertTrue(spans[1][2])
        self.assertAlmostEqual(spans[0][1], 1.0, delta=0.1)
        self.assertAlmostEqual(spans[1][1], 2.0, delta=0.1)
        self.assertAlmostEqual(spans[2][1], 3.0, places=2)

    # 只有一小段時，直接從開始念到結束
    def test_single_line(self):
        self.assertEqual(av.place_boundaries([(1.0, 1.2)], 0.2, 2.5, [8]), [(0.2, 2.5, False)])


class AudioTest(unittest.TestCase):
    # 從合成音找出停頓，以及前後的靜音（說話從哪裡開始、到哪裡結束）
    def test_find_pauses(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "a.wav"
            make_audio(wav, [("gap", 0.3), ("tone", 1.0), ("gap", 0.3), ("tone", 1.0), ("gap", 0.4)])
            pauses, speech_start, speech_end = av.find_pauses(wav, -40, 0.12)
        self.assertAlmostEqual(speech_start, 0.3, delta=0.03)
        self.assertAlmostEqual(speech_end, 2.6, delta=0.03)
        self.assertEqual(len(pauses), 1)
        self.assertAlmostEqual(pauses[0][0], 1.3, delta=0.03)
        self.assertAlmostEqual(pauses[0][1], 1.6, delta=0.03)


class MergeShortTest(unittest.TestCase):
    # 短於 0.8 秒的併進同一句的下一段，中間用 En space
    def test_merge_into_next(self):
        cues = [make_cue(0.0, 0.4, "而且", "而且，", en="And it flies."),
                make_cue(0.6, 1.8, "它還會飛", "它還會飛。")]
        out = av.merge_short(cues, 0.8, 40)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["show"], "而且" + EN_SPACE + "它還會飛")
        self.assertEqual((out[0]["start"], out[0]["end"]), (0.0, 1.8))
        self.assertEqual(out[0]["en"], "And it flies.")

    # 下一段是別的句子時，不往後併，改併進同一句的上一段
    def test_merge_into_previous_not_across_sentence(self):
        cues = [make_cue(0.0, 1.5, "車尾有主推進器", "車尾有主推進器，"),
                make_cue(1.6, 2.0, "很強", "很強。"),
                make_cue(2.2, 4.0, "下一句", "下一句。")]
        out = av.merge_short(cues, 0.8, 40)
        self.assertEqual([c["show"] for c in out], ["車尾有主推進器" + EN_SPACE + "很強", "下一句"])

    # 一句的最後一段很短、前一段又是別句時，維持原樣，交給抽查清單
    def test_no_merge_across_sentence(self):
        cues = [make_cue(0.0, 1.5, "上一句", "上一句。"),
                make_cue(1.6, 2.0, "好", "好。"),
                make_cue(2.2, 4.0, "下一句", "下一句。")]
        out = av.merge_short(cues, 0.8, 40)
        self.assertEqual(len(out), 3)

    # 併完會超過一行寬度（全形算 2）時不併
    def test_width_limit(self):
        cues = [make_cue(0.0, 0.4, "短", "短，"), make_cue(0.5, 3.0, "長" * 20, "長" * 20 + "。")]
        self.assertEqual(len(av.merge_short(cues, 0.8, 40)), 2)

    # 不同段配音的小段不互相合併
    def test_no_merge_across_segments(self):
        cues = [make_cue(0.0, 0.4, "而且", "而且，", seg=0), make_cue(0.6, 1.8, "它還會飛", "它還會飛。", seg=1)]
        self.assertEqual(len(av.merge_short(cues, 0.8, 40)), 2)

    # 兩段都有英文時，合併後英文用空白接在一起
    def test_merge_joins_english(self):
        cues = [make_cue(0.0, 0.4, "吸氣", "吸氣，", en="Suck in air,"),
                make_cue(0.5, 1.8, "黏住地面", "黏住地面。", en="and it sticks.")]
        self.assertEqual(av.merge_short(cues, 0.8, 40)[0]["en"], "Suck in air, and it sticks.")


class SrtTest(unittest.TestCase):
    # 有英文時每句兩行（中文在上、英文在下），格式和 WSL 測試的 master.srt 相同
    def test_bilingual_format(self):
        cues = [make_cue(0.3, 1.34, "0.81 秒", en="0.81 seconds"),
                make_cue(1.67, 3.99, "從靜止衝到時速 97 公里", en="from standstill to 97 km/h")]
        self.assertEqual(av.to_srt(cues), (
            "1\n00:00:00,300 --> 00:00:01,340\n0.81 秒\n0.81 seconds\n\n"
            "2\n00:00:01,670 --> 00:00:03,990\n從靜止衝到時速 97 公里\nfrom standstill to 97 km/h\n"))

    # 全部都沒寫英文時只輸出中文
    def test_chinese_only(self):
        self.assertEqual(av.to_srt([make_cue(61.0, 62.5, "好")]),
                         "1\n00:01:01,000 --> 00:01:02,500\n好\n")


class MainTest(unittest.TestCase):
    # 執行整支程式，回傳結束代碼和印出的錯誤訊息
    def run_main(self, json_path):
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            code = av.main([str(json_path)])
        return code, err.getvalue()

    # 音檔放在中文名稱的資料夾裡也能跑，輸出 3 個檔，停頓不夠的句子列進抽查清單
    def test_end_to_end_chinese_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "中文 資料夾"
            (root / "配音").mkdir(parents=True)
            make_audio(root / "配音" / "01.wav", [("gap", 0.2), ("tone", 1.0), ("gap", 0.3), ("tone", 2.0), ("gap", 0.3)])
            make_audio(root / "配音" / "02.wav", [("tone", 3.0)])
            data = {"segments": [
                {"audio": "配音/01.wav", "start": 0.5,
                 "lines": [{"say": "零點八一秒，", "show": "0.81 秒", "en": "0.81 seconds"},
                           {"say": "從靜止衝到時速九十七公里。", "show": "從靜止衝到時速 97 公里", "en": "to 97 km/h"}]},
                {"audio": "配音/02.wav",
                 "lines": [{"say": "第一句話。", "show": "第一句話"}, {"say": "第二句話。", "show": "第二句話"},
                           {"say": "第三句話。", "show": "第三句話"}]},
            ]}
            path = root / "voice_lines.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            code, err = self.run_main(path)
            self.assertEqual(code, 0, err)
            srt = (root / "master.srt").read_text(encoding="utf-8")
            cues = json.loads((root / "cues.json").read_text(encoding="utf-8"))
            review = (root / "align_review.md").read_text(encoding="utf-8")
        self.assertIn("00:00:00,700 --> 00:00:01,700\n0.81 秒\n0.81 seconds", srt)
        self.assertEqual(len(cues), 5)
        # 第 2 段沒寫 start，接在第 1 段後面（0.5 + 3.8 秒）
        self.assertAlmostEqual(cues[2]["start"], 4.3, delta=0.03)
        self.assertIn("第一句話", review)
        self.assertIn("第二句話", review)

    # 對照表少了 say 時，印出哪一段哪一條少了什麼，不跳出程式錯誤
    def test_missing_field_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "voice_lines.json"
            path.write_text(json.dumps({"segments": [{"audio": "a.wav", "lines": [{"show": "好"}]}]}), encoding="utf-8")
            code, err = self.run_main(path)
        self.assertNotEqual(code, 0)
        self.assertIn("say", err)
        self.assertIn("第 1 段", err)
        self.assertNotIn("Traceback", err)

    # 找不到音檔時，印出找不到的路徑
    def test_missing_audio_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "voice_lines.json"
            path.write_text(json.dumps({"segments": [{"audio": "沒有.wav", "lines": [{"say": "好。", "show": "好"}]}]},
                                       ensure_ascii=False), encoding="utf-8")
            code, err = self.run_main(path)
        self.assertNotEqual(code, 0)
        self.assertIn("沒有.wav", err)


if __name__ == "__main__":
    unittest.main()
