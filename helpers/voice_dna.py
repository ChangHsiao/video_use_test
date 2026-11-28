"""Voice DNA: the recipe and measured fingerprint of a brand voice, and a check of new takes against it.

The approved sign-offs are the reference: `build` measures every sign-off the brand lists (brand.json `signoff`
plus each `series.<key>.signoff`) and writes the DNA file brand.json `voice_dna` names for that voice. `check` measures a
new take the same way and reports which trait drifted, so a re-recorded line sounds like the same voice.

Which sign-offs belong to which voice, and where each voice's DNA file lives, is data in brand.json:
  "voice_dna": {"<voice>": "assets/voice_dna/<name>.json"}, and every signoff has "voice": "<voice>"
(<voice> is a key of brand.json "voices"). Adding a voice or a series needs no code change.

Usage:
  python helpers/voice_dna.py build   --brand BRAND --voice VOICE
  python helpers/voice_dna.py check   TAKE --text "…" --brand BRAND --voice VOICE   # exit 1 on FAIL
  python helpers/voice_dna.py measure TAKE --text "…" --brand BRAND --voice VOICE   # print the fingerprint

Traits (all from the speech span, silence trimmed at -45 dBFS like signoff.py):
  f0_median_hz / f0_range_st  pitch centre and spread (librosa pyin, 10th..90th percentile in semitones)
  rate_syl_s                  syllables per second (one per CJK character, vowel groups for Latin words)
  centroid_hz                 median spectral centroid: brightness of the timbre
  mfcc                        mean MFCC 1..12: the timbre itself; compared as a Euclidean distance
  lufs / true_peak_dbtp       loudness of the raw take; informational, the edit sets the final level
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

SR = 22050
SILENCE_DB = -45
# How far a take may drift from the reference centre. Each limit is the larger of this floor and MARGIN x the
# farthest approved reference, so every approved take passes its own DNA and a new take may not stray further.
FLOOR = {"f0_median_st": 1.0, "f0_range_st": 2.0, "rate_pct": 10.0, "centroid_pct": 15.0, "timbre": 25.0}
MARGIN = 1.5


def syllables(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in re.findall(r"[A-Za-z]+", text))
    return cjk + latin


def loudness(path: Path) -> tuple[float, float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    summary = r.stderr[r.stderr.rfind("Summary:"):]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary).group(1))
    return lufs, peak


def speech_span(y: np.ndarray) -> np.ndarray:
    live = np.where(np.abs(y) > 10 ** (SILENCE_DB / 20))[0]
    return y[live[0]: live[-1] + 1] if len(live) else y


def measure(path: Path, text: str) -> dict:
    import librosa  # slow import, only when audio is measured
    y = speech_span(librosa.load(str(path), sr=SR, mono=True)[0])
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=400, sr=SR, frame_length=2048)
    f0 = f0[voiced & ~np.isnan(f0)]
    p10, p50, p90 = np.percentile(f0, [10, 50, 90])
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=13)[1:].mean(axis=1)
    lufs, peak = loudness(path)
    return {
        "duration_s": round(len(y) / SR, 3),
        "f0_median_hz": round(float(p50), 1),
        "f0_range_st": round(float(12 * np.log2(p90 / p10)), 2),
        "rate_syl_s": round(syllables(text) / (len(y) / SR), 2),
        "centroid_hz": round(float(np.median(librosa.feature.spectral_centroid(y=y, sr=SR))), 0),
        "mfcc": [round(float(v), 2) for v in mfcc],
        "lufs": lufs,
        "true_peak_dbtp": peak,
    }


def timbre_distance(a: list[float], b: list[float]) -> float:
    return float(np.linalg.norm(np.array(a) - np.array(b)))


def center(fps: list[dict]) -> dict:
    keys = ["f0_median_hz", "f0_range_st", "rate_syl_s", "centroid_hz", "lufs"]
    c = {k: round(float(np.mean([f[k] for f in fps])), 2) for k in keys}
    c["mfcc"] = [round(float(v), 2) for v in np.mean([f["mfcc"] for f in fps], axis=0)]
    return c


def drifts(fp: dict, c: dict) -> dict[str, float]:
    """How far a fingerprint is from the centre, per trait, in the trait's own unit."""
    return {
        "f0_median_st": 12 * np.log2(fp["f0_median_hz"] / c["f0_median_hz"]),
        "f0_range_st": fp["f0_range_st"] - c["f0_range_st"],
        "rate_pct": 100 * (fp["rate_syl_s"] / c["rate_syl_s"] - 1),
        "centroid_pct": 100 * (fp["centroid_hz"] / c["centroid_hz"] - 1),
        "timbre": timbre_distance(fp["mfcc"], c["mfcc"]),
    }


def tolerance(fps: list[dict], c: dict) -> dict[str, float]:
    far = [drifts(fp, c) for fp in fps]
    return {k: round(max(floor, MARGIN * max(abs(d[k]) for d in far)), 2) for k, floor in FLOOR.items()}


def compare(fp: dict, dna: dict) -> list[tuple[str, float, float, bool]]:
    """(trait, drift, limit, ok) for each trait."""
    tol = dna["tolerance"]
    return [(k, round(float(d), 2), tol[k], abs(d) <= tol[k]) for k, d in drifts(fp, dna["center"]).items()]


def references(brand: registry.Brand, voice: str) -> dict[str, dict]:
    """Every approved sign-off the brand lists for this voice: {key: {"file", "text"}}.
    key is "brand" for the brand-level sign-off and the series key for series.<key>.signoff."""
    so = {"brand": brand.data.get("signoff", {})}
    so.update({k: s.get("signoff") for k, s in brand.data.get("series", {}).items()})
    return {k: {"file": v["audio"], "text": v["text"]}
            for k, v in so.items() if isinstance(v, dict) and v.get("voice") == voice}


def recipe() -> dict:
    import signoff  # the sign-off recorder owns the settings; the DNA only copies them
    return {"model_id": signoff.MODEL_ID, "output_format": signoff.OUTPUT_FORMAT,
            "voice_settings": signoff.SETTINGS, "seed": signoff.SEED, "recorder": "helpers/signoff.py"}


def dna_path(brand: registry.Brand, voice: str) -> Path:
    files = brand.data.get("voice_dna", {})
    if voice not in files:
        raise registry.ConfigError(f"brand.json 的 voice_dna 沒有「{voice}」。有的聲音：{'、'.join(files) or '沒有'}")
    return brand.root / files[voice]


def build(brand: registry.Brand, voice: str) -> Path:
    refs = references(brand, voice)
    if not refs:
        raise registry.ConfigError(f"品牌沒有標 \"voice\": \"{voice}\" 的口播收尾，量不出 DNA")
    for r in refs.values():
        r["fingerprint"] = measure(brand.asset(r["file"]), r["text"])
    fps = [r["fingerprint"] for r in refs.values()]
    c = center(fps)
    out = dna_path(brand, voice)
    old = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    dna = {"voice": voice, "voice_id": brand.data["voices"][voice], "measured": date.today().isoformat(),
           "recipe": recipe(), "references": refs, "center": c,
           "tolerance": old.get("tolerance") or tolerance(fps, c)}  # a hand-tuned tolerance survives a rebuild
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dna, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "check", "measure"])
    ap.add_argument("take", nargs="?", type=Path)
    ap.add_argument("--text", help="the words spoken in TAKE (for the speech rate)")
    ap.add_argument("--brand", required=True, help="brands/<name>/")
    ap.add_argument("--voice", required=True, help="a key of brand.json voices / voice_dna, e.g. male")
    a = ap.parse_args()
    brand = registry.load_brand(a.brand)
    if a.cmd == "build":
        print(build(brand, a.voice))
        return 0
    if not (a.take and a.text):
        ap.error(f"{a.cmd} needs TAKE and --text")
    fp = measure(a.take, a.text)
    if a.cmd == "measure":
        print(json.dumps(fp, ensure_ascii=False, indent=2))
        return 0
    rows = compare(fp, json.loads(dna_path(brand, a.voice).read_text(encoding="utf-8")))
    for name, drift, lim, ok in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<13} drift {drift:+7.2f}  limit ±{lim}")
    print(f"loudness {fp['lufs']} LUFS, true peak {fp['true_peak_dbtp']} dBTP (informational)")
    return 0 if all(ok for *_, ok in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
