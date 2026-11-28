"""Where the video work folders live on this machine (Windows and Linux/macOS).

Every edited video lives under one root folder, outside the repo:
  Windows        D:/videos
  Linux / macOS  ~/Videos   (e.g. /home/sunny/Videos)
Set VIDEOS_ROOT to override both.
"""

import os
import sys
from pathlib import Path

VOICE_TEMPLATES = "聲音範本"


def videos_root(platform: str = sys.platform, env=os.environ) -> Path:
    """Root folder that holds every video project and the voice templates."""
    if env.get("VIDEOS_ROOT"):
        return Path(env["VIDEOS_ROOT"]).expanduser()
    return Path("D:/videos") if platform == "win32" else Path.home() / "Videos"


def resolve_voice_dir(arg: str, root: Path | None = None) -> Path:
    """--voice-dir accepts a full path or just the template name (e.g. A1_男聲).

    A path that exists as given wins, so old full-path calls keep working;
    otherwise it is looked up under <videos root>/聲音範本/.
    """
    p = Path(arg).expanduser()
    return p if p.exists() else (root or videos_root()) / VOICE_TEMPLATES / p
