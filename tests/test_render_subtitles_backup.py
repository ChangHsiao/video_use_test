"""重新產生 master.srt 時保留舊檔（備份）、--subtitles-only 用的畫面尺寸的測試。"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


HELPERS = Path(__file__).parents[1] / "helpers"


def load_helper(name):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = load_helper("render")

NOW = datetime(2026, 10, 10, 8, 30, 15)


class ReplaceWithBackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.out = self.dir / "master.srt"
        self.new = self.dir / "master.srt.tmp"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_existing_file_just_writes(self):
        self.new.write_text("new", encoding="utf-8")
        backup = render.replace_with_backup(self.new, self.out, now=NOW)
        self.assertIsNone(backup)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "new")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["master.srt"])

    def test_same_content_keeps_file_and_no_backup(self):
        self.out.write_text("same", encoding="utf-8")
        self.new.write_text("same", encoding="utf-8")
        backup = render.replace_with_backup(self.new, self.out, now=NOW)
        self.assertIsNone(backup)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["master.srt"])

    def test_different_content_backs_up_old_file(self):
        # 校對過的字幕被重新產生的版本取代時，校對過的內容要留在備份裡
        self.out.write_text("proofread", encoding="utf-8")
        self.new.write_text("rebuilt", encoding="utf-8")
        backup = render.replace_with_backup(self.new, self.out, now=NOW)
        self.assertEqual(backup, self.dir / "master.srt.bak-20261010-083015")
        self.assertEqual(backup.read_text(encoding="utf-8"), "proofread")
        self.assertEqual(self.out.read_text(encoding="utf-8"), "rebuilt")
        self.assertFalse(self.new.exists())

    def test_two_backups_in_same_second_do_not_collide(self):
        self.out.write_text("v1", encoding="utf-8")
        self.new.write_text("v2", encoding="utf-8")
        first = render.replace_with_backup(self.new, self.out, now=NOW)
        self.new.write_text("v3", encoding="utf-8")
        second = render.replace_with_backup(self.new, self.out, now=NOW)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_text(encoding="utf-8"), "v1")
        self.assertEqual(second.read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.out.read_text(encoding="utf-8"), "v3")


class DisplayDimensionsTests(unittest.TestCase):
    def _dims(self, stream: dict):
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"streams": [stream]}), stderr=""
        )
        with patch.object(render.subprocess, "run", return_value=result):
            return render.probe_display_dimensions(Path("source.mp4"))

    def test_plain_landscape(self):
        self.assertEqual(self._dims({"width": 1920, "height": 1080}), (1920, 1080))

    def test_quarter_turn_swaps(self):
        # 手機直拍：檔案存成橫的，靠旋轉資訊顯示成直的
        stream = {"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}
        self.assertEqual(self._dims(stream), (1080, 1920))

    def test_probe_failure_returns_none(self):
        with patch.object(render.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(render.probe_display_dimensions(Path("missing.mp4")))


if __name__ == "__main__":
    unittest.main()
