"""Record sign-off (spoken slogan) candidates once, in the studio chain, for reuse in every episode.

Usage: python helpers/signoff.py --voice-dir A1_男聲 [--edit DIR]
  writes edit/voice/signoff/<key>.wav (+ .mp3) for each candidate below
A sign-off is a sonic logo: generate it once, keep the chosen file, never regenerate it per episode.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prosody import SR, decode, finish  # noqa: E402
from paths import resolve_voice_dir  # noqa: E402
from voice_tts import EDIT, load_key  # noqa: E402

OUT = EDIT / "voice" / "signoff"
# Slower and steadier than the news read: it has to sound the same every time and land on the name
SETTINGS = {"stability": 0.65, "similarity_boost": 0.85, "style": 0.25, "speed": 0.98}
SEED = 2026
MODEL_ID = "eleven_v4"
OUTPUT_FORMAT = "mp3_44100_192"

CANDIDATES = {
    "A_數據說話": "科技大事，數據說話。我是桑尼資料科學。",
    "B_看門道": "別人看熱鬧，我們看數據。桑尼資料科學。",
    "C_就看桑尼": "看懂科技大事，就看桑尼資料科學。",
    "D_每週拆解": "這裡是桑尼資料科學，每週用數據，拆解一則科技大事。",
}


def tts(key, voice_id, text):
    body = {"text": text, "model_id": MODEL_ID, "seed": SEED, "voice_settings": SETTINGS}
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={OUTPUT_FORMAT}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"xi-api-key": key, "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", help="episode edit/ folder (default: the current folder)")
    ap.add_argument("--voice-dir", required=True,
                    help="full path, or a template name under <videos root>/聲音範本/ (see helpers/paths.py)")
    ap.add_argument("--say", action="append", metavar="KEY=TEXT",
                    help="candidate to record instead of the built-in news ones (repeatable), e.g. --say A=這裡是…")
    args = ap.parse_args()
    candidates = dict(s.split("=", 1) for s in args.say) if args.say else CANDIDATES
    voice_id = json.loads((resolve_voice_dir(args.voice_dir) / "voice.json").read_text(encoding="utf-8"))["voice_id"]
    OUT.mkdir(parents=True, exist_ok=True)
    key = load_key()
    for name, text in candidates.items():
        raw = OUT / f"{name}_raw.mp3"
        if not raw.is_file():
            raw.write_bytes(tts(key, voice_id, text))
        x = decode(raw)
        # trim silence at both ends, keep 80 ms of air
        live = np.where(np.abs(x) > 10 ** (-45 / 20))[0]
        x = x[max(0, live[0] - int(0.08 * SR)): live[-1] + int(0.08 * SR)]
        finish(x, OUT / f"{name}.mp3")
        print(f"{name}: {len(x) / SR:.2f}s  {text}")


if __name__ == "__main__":
    main()
