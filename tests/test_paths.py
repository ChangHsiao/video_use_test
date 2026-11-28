"""helpers/paths.py: video root detection on Windows / Linux, and --voice-dir lookup."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "helpers"))
from paths import resolve_voice_dir, videos_root  # noqa: E402


class VideosRootTest(unittest.TestCase):
    def test_windows_uses_d_drive(self):
        self.assertEqual(videos_root("win32", {}), Path("D:/videos"))

    def test_linux_uses_home_videos(self):
        self.assertEqual(videos_root("linux", {}), Path.home() / "Videos")

    def test_macos_uses_home_videos(self):
        self.assertEqual(videos_root("darwin", {}), Path.home() / "Videos")

    def test_env_overrides_every_platform(self):
        for plat in ("win32", "linux", "darwin"):
            self.assertEqual(videos_root(plat, {"VIDEOS_ROOT": "/mnt/vid"}), Path("/mnt/vid"))

    def test_empty_env_is_ignored(self):
        self.assertEqual(videos_root("win32", {"VIDEOS_ROOT": ""}), Path("D:/videos"))


class ResolveVoiceDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "聲音範本" / "A1_男聲").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bare_name_resolves_under_root(self):
        self.assertEqual(resolve_voice_dir("A1_男聲", self.root), self.root / "聲音範本" / "A1_男聲")

    def test_existing_full_path_is_kept(self):
        full = self.root / "聲音範本" / "A1_男聲"
        self.assertEqual(resolve_voice_dir(str(full), Path("/elsewhere")), full)

    def test_missing_absolute_path_stays_absolute(self):
        # old Windows-style call on a Linux box: error message must show what the user typed
        missing = self.root / "nope"
        self.assertEqual(resolve_voice_dir(str(missing), self.root), missing)


if __name__ == "__main__":
    unittest.main()
