import contextlib
import importlib.util
import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote


MODULE_PATH = Path(__file__).parents[1] / "helpers" / "export_xml.py"
SPEC = importlib.util.spec_from_file_location("video_use_export_xml", MODULE_PATH)
assert SPEC and SPEC.loader
export_xml = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_xml)

URL_PREFIX = "file://localhost/"
NTSC_24 = Fraction(24000, 1001)
SOURCE_DURATION_S = 365.03  # round(365.03 * 24000/1001) = 8752 格


def fake_probe(path):
    """代替 ffprobe：影片一律 1280x720、23.976 fps、立體聲；圖片 1920x1080。"""
    if Path(path).suffix.lower() == ".png":
        return {"width": 1920, "height": 1080}
    return {
        "fps": NTSC_24,
        "duration_s": SOURCE_DURATION_S,
        "width": 1280,
        "height": 720,
        "audio_channels": 2,
        "sample_rate": 44100,
    }


class FpsToRateTests(unittest.TestCase):
    def test_ntsc_and_integer_rates(self):
        expected = {
            Fraction(24000, 1001): (24, True),
            Fraction(30000, 1001): (30, True),
            Fraction(25, 1): (25, False),
        }
        for fps, rate in expected.items():
            with self.subTest(fps=fps):
                self.assertEqual(export_xml.fps_to_rate(fps), rate)


class PathToUrlTests(unittest.TestCase):
    def test_encodes_non_ascii_but_keeps_slashes_and_drive_colon(self):
        path = Path("C:/Users/長/clip one.mp4")
        url = export_xml.path_to_url(path)
        self.assertTrue(url.startswith(URL_PREFIX))
        self.assertIn("%E9%95%B7", url)  # 長
        self.assertIn("clip%20one.mp4", url)
        self.assertNotIn("%2F", url)
        self.assertNotIn("%3A", url)
        self.assertEqual(unquote(url[len(URL_PREFIX):]), path.resolve().as_posix())


class BuildXmemlTests(unittest.TestCase):
    """兩個來源（一個在中文資料夾裡）剪三段，加四張疊圖：

    - q1：有 PNG
    - q2：緊接在 q1 後面，故意沒有 PNG
    - q3：再用一次 q1.png，起點離剪接點差 1 格，應該對齊剪接點
    - q4：超過影片結尾，應該截在結尾
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.edit_dir = Path(self._tmp.name) / "長" / "edit"
        (self.edit_dir / "cards").mkdir(parents=True)
        (self.edit_dir / "cards" / "q1.png").write_bytes(b"")  # q2 故意沒有 PNG
        self.edl = {
            "version": 1,
            "sources": {
                "A": str(self.edit_dir.parent / "a.mp4"),
                "B": str(self.edit_dir.parent / "b.mp4"),
            },
            "ranges": [
                {"source": "A", "start": 1.0, "end": 2.0, "beat": "HOOK"},
                {"source": "B", "start": 10.0, "end": 12.5},
                {"source": "A", "start": 5.0, "end": 6.0, "beat": "END"},
            ],
            "overlays": [
                {"file": "cards/q1.mov", "start_in_output": 0.32, "duration": 1.53},
                {"file": "cards/q2.mov", "start_in_output": 1.85, "duration": 1.65},
                {"file": "cards/q1.mov", "start_in_output": 3.46, "duration": 0.5},
                {"file": "cards/q1.mov", "start_in_output": 4.0, "duration": 1.0},
            ],
            "subtitles": "master.srt",
        }
        self.stderr = io.StringIO()
        with contextlib.redirect_stderr(self.stderr):
            self.root = export_xml.build_xmeml(self.edl, self.edit_dir, probe=fake_probe).getroot()
        self.seq = self.root.find("sequence")
        tracks = self.seq.findall("media/video/track")
        self.v1 = tracks[0].findall("clipitem")
        self.v2 = tracks[1].findall("clipitem")
        self.audio_tracks = self.seq.findall("media/audio/track")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def frames(clip, tag):
        return int(clip.findtext(tag))

    def test_root_and_sequence(self):
        self.assertEqual(self.root.tag, "xmeml")
        self.assertEqual(self.root.get("version"), "5")
        self.assertEqual(self.seq.findtext("rate/timebase"), "24")
        self.assertEqual(self.seq.findtext("rate/ntsc"), "TRUE")
        self.assertEqual(self.seq.findtext("media/video/format/samplecharacteristics/width"), "1280")
        self.assertEqual(self.seq.findtext("media/video/format/samplecharacteristics/height"), "720")
        self.assertEqual(self.seq.findtext("duration"), "108")

    def test_source_in_out_in_frames(self):
        # round(秒 * 24000/1001)：1.0→24、2.0→48、10.0→240、12.5→300、5.0→120、6.0→144
        got = [(self.frames(c, "in"), self.frames(c, "out")) for c in self.v1]
        self.assertEqual(got, [(24, 48), (240, 300), (120, 144)])

    def test_timeline_positions_accumulate_frames(self):
        got = [(self.frames(c, "start"), self.frames(c, "end")) for c in self.v1]
        self.assertEqual(got, [(0, 24), (24, 84), (84, 108)])

    def test_clip_duration_is_whole_source_so_edges_can_be_extended(self):
        for clip in self.v1:
            self.assertEqual(self.frames(clip, "duration"), 8752)

    def test_clip_names_use_beat_or_source_and_index(self):
        self.assertEqual([c.findtext("name") for c in self.v1], ["HOOK", "B 2", "END"])

    def test_each_source_file_defined_once_then_referenced(self):
        full = [f for f in self.root.iter("file") if f.find("pathurl") is not None]
        source_urls = [f.findtext("pathurl") for f in full if not f.findtext("pathurl").endswith((".png", ".mov"))]
        self.assertEqual(len(source_urls), 2)
        self.assertEqual(len(set(source_urls)), 2)
        ids = {f.get("id") for f in full}
        for clip in self.v1:
            self.assertIn(clip.find("file").get("id"), ids)

    def test_source_pathurl_is_encoded_absolute_path(self):
        urls = {f.findtext("pathurl") for f in self.root.iter("file") if f.find("pathurl") is not None}
        expected = Path(self.edl["sources"]["A"]).resolve().as_posix()
        matches = [u for u in urls if unquote(u[len(URL_PREFIX):]) == expected]
        self.assertEqual(len(matches), 1)
        self.assertIn("%E9%95%B7", matches[0])

    def test_file_has_start_timecode_so_davinci_links_audio(self):
        # 沒有 <timecode>，DaVinci 21.1 匯入後聲音片段會離線（2026-10-09 實測）
        full = [f for f in self.root.iter("file") if f.find("pathurl") is not None]
        for f in full:
            self.assertEqual(f.findtext("timecode/string"), "00:00:00:00")
            self.assertEqual(f.findtext("timecode/displayformat"), "NDF")
            self.assertEqual(f.findtext("timecode/rate/timebase"), f.findtext("rate/timebase"))

    def test_audio_follows_video_on_one_track_per_channel(self):
        self.assertEqual(len(self.audio_tracks), 2)
        for ch, track in enumerate(self.audio_tracks, start=1):
            clips = track.findall("clipitem")
            self.assertEqual(len(clips), 3)
            for a, v in zip(clips, self.v1):
                self.assertEqual(a.findtext("sourcetrack/trackindex"), str(ch))
                self.assertEqual((a.findtext("in"), a.findtext("out")), (v.findtext("in"), v.findtext("out")))
                self.assertEqual((a.findtext("start"), a.findtext("end")), (v.findtext("start"), v.findtext("end")))

    def test_video_and_audio_clips_are_linked(self):
        audio_ids = [{c.get("id") for c in t.findall("clipitem")} for t in self.audio_tracks]
        for i, v in enumerate(self.v1):
            linked = {link.findtext("linkclipref") for link in v.findall("link")}
            self.assertIn(v.get("id"), linked)
            for ids in audio_ids:
                self.assertTrue(linked & ids, f"V1 clip {i} not linked to every audio track")

    def test_overlay_uses_png_still_when_present(self):
        card = self.v2[0]
        self.assertTrue(card.find("file").findtext("pathurl").endswith("/q1.png"))
        self.assertEqual(card.findtext("stillframe"), "TRUE")
        # 起點 round(0.32 * 23.976) = 8，終點 round(1.85 * 23.976) = 44
        self.assertEqual((self.frames(card, "start"), self.frames(card, "end")), (8, 44))

    def test_overlay_without_png_keeps_original_file_and_warns(self):
        card = self.v2[1]
        self.assertTrue(card.find("file").findtext("pathurl").endswith("/q2.mov"))
        self.assertIsNone(card.find("stillframe"))
        self.assertIn("q2", self.stderr.getvalue())

    def test_adjacent_overlays_do_not_overlap(self):
        # 舊算法「起點 + 長度」：8 + round(1.53 * 23.976) = 45，會和 q2 的起點 44 重疊 1 格
        # 正確：q1 終點 round(1.85 * 23.976) = 44 = q2 起點
        self.assertEqual(self.frames(self.v2[0], "end"), self.frames(self.v2[1], "start"))

    def test_overlay_edges_snap_to_cuts_within_one_frame(self):
        # q2 終點 round(3.5 * 23.976) = 84，剛好是剪接點；
        # q3 起點 round(3.46 * 23.976) = 83，離剪接點 84 只差 1 格 → 對齊到 84
        self.assertEqual(self.frames(self.v2[1], "end"), 84)
        self.assertEqual(self.frames(self.v2[2], "start"), 84)
        # q3 終點 round(3.96 * 23.976) = 95，附近沒有剪接點 → 不動
        self.assertEqual(self.frames(self.v2[2], "end"), 95)

    def test_same_png_used_twice_is_defined_once(self):
        pngs = [f for f in self.root.iter("file")
                if f.find("pathurl") is not None and f.findtext("pathurl").endswith("/q1.png")]
        self.assertEqual(len(pngs), 1)
        self.assertEqual(self.v2[0].find("file").get("id"), self.v2[2].find("file").get("id"))

    def test_overlay_is_clipped_at_timeline_end(self):
        # q4 終點 round(5.0 * 23.976) = 120，超過影片結尾 108 → 截在 108
        self.assertEqual(self.frames(self.v2[3], "start"), 96)
        self.assertEqual(self.frames(self.v2[3], "end"), 108)
        self.assertEqual(self.seq.findtext("duration"), "108")

    def test_written_file_has_declaration_doctype_and_parses(self):
        out = self.edit_dir / "timeline.xml"
        with contextlib.redirect_stderr(io.StringIO()):
            tree = export_xml.build_xmeml(self.edl, self.edit_dir, probe=fake_probe)
        export_xml.write_xml(tree, out)
        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn("<!DOCTYPE xmeml>", text)
        self.assertEqual(ET.parse(out).getroot().tag, "xmeml")


if __name__ == "__main__":
    unittest.main()
