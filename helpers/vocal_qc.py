"""Check a narration file against the studio spec (recipes/錄音室級旁白.md).

Usage: python helpers/vocal_qc.py FILE [FILE...]
"""

import json
import re
import subprocess
import sys

import librosa
import numpy as np
from pathlib import Path

SPEC = {  # name: (low, high)
    "loudness LUFS": (-17.0, -15.0),
    "true peak dBTP": (-99.0, -1.0),
    "LRA LU": (3.0, 6.0),
    "noise floor dBFS": (-99.0, -65.0),
    "breath below speech dB": (24.0, 99.0),
    "longest breath s": (0.0, 0.40),
    "breaths per min": (3.0, 9.0),
    "dropouts per min": (0.0, 3.0),
}


def dropouts(y, sr, speech):
    """Times (s) where the voice falls from speech level to near silence within 30 ms.

    A natural stop decays over 100-270 ms (median of the A1 take); a cut into digital silence does it in one
    or two 10 ms frames and sounds like the signal dropping out. Raw ElevenLabs takes measure ~35/min, the
    old per-comma rhythm pass ~80/min; sentence cuts plus the room tail in prosody.py bring it under 2.
    """
    hop = int(sr * 0.01)
    m = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: m * hop].reshape(m, hop) ** 2).mean(1)) + 1e-12)
    hi, lo = speech - 20, speech - 40
    return [i / 100 for i in range(3, m) if db[i - 3] > hi and db[i] < lo]



def ebur(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    summary = r[r.rfind("Summary:"):]

    def get(pat):
        m = re.search(pat, summary)
        if not m:
            sys.exit(f"ebur128 summary missing {pat} for {path}")
        return float(m.group(1))
    return get(r"I:\s+(-?[\d.]+) LUFS"), get(r"Peak:\s+(-?[\d.]+) dBFS"), get(r"LRA:\s+(-?[\d.]+) LU")


def measure(path):
    lufs, tp, lra = ebur(path)
    y, sr = librosa.load(path, sr=48000)
    hop = 960  # 20 ms
    rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    db = 20 * np.log10(rms + 1e-9)
    floor = float(np.percentile(db, 5))
    speech = float(np.percentile(db[db > -40], 70))
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=hop * 2, hop_length=hop)[0]
    n = min(len(db), len(zcr))
    # Breath: noisy (many zero crossings), clearly above the floor, well under the speech level
    cand = (db[:n] > floor + 8) & (db[:n] < speech - 12) & (zcr[:n] > 0.09)
    breaths, start = [], None
    for i, c in enumerate(np.append(cand, False)):
        if c and start is None:
            start = i
        elif not c and start is not None:
            # breaths follow a pause; fricatives sit between voiced frames
            after_pause = np.any(db[max(0, start - 12):start] < floor + 12)
            if 6 <= i - start <= 60 and after_pause:
                breaths.append((start, i))
            start = None
    # Exact breath positions when prosody.py left its plan next to the file
    plan = Path(path).with_name(Path(path).stem.removesuffix("_rhythm") + ".json")
    if plan.is_file():
        marks = [l for sec in json.loads(plan.read_text(encoding="utf-8")) for l in sec["lines"] if "breath_at" in l]
        breaths = [(int(l["breath_at"] * sr / hop), int((l["breath_at"] + l["breath_kept"]) * sr / hop) - 1) for l in marks]
    blen = [(b - a) * hop / sr for a, b in breaths]
    blev = [float(np.max(db[a:b])) for a, b in breaths]
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)) ** 2
    fr = librosa.fft_frequencies(sr=sr, n_fft=2048)
    loud = db[: S.shape[1]] > speech - 10
    Sl = S[:, : len(loud)][:, loud]
    sib = 10 * np.log10(Sl[(fr >= 5000) & (fr < 9000)].sum() / Sl[(fr >= 300) & (fr < 3000)].sum())
    mins = len(y) / sr / 60
    return {
        "loudness LUFS": lufs, "true peak dBTP": tp, "LRA LU": lra, "noise floor dBFS": floor,
        "speech level dBFS": speech,
        "breath below speech dB": speech - max(blev) if blev else 99.0,
        "breath below speech (median) dB": speech - float(np.median(blev)) if blev else 99.0,
        "longest breath s": max(blen) if blen else 0.0,
        "breaths per min": len(breaths) / mins,
        "sibilance 5-9k vs 0.3-3k dB": float(sib),
        "dropouts per min": len(dropouts(y, sr, speech)) / mins,
    }


def main():
    for path in sys.argv[1:]:
        m = measure(path)
        print(path)
        for k, v in m.items():
            lo, hi = SPEC.get(k, (None, None))
            mark = "" if lo is None else ("OK  " if lo <= v <= hi else "FAIL")
            print(f"  {mark:4} {k:30} {v:7.2f}" + ("" if lo is None else f"   spec {lo:g}..{hi:g}"))
        if not SPEC["dropouts per min"][0] <= m["dropouts per min"] <= SPEC["dropouts per min"][1]:
            y, sr = librosa.load(path, sr=48000)
            at = dropouts(y, sr, m["speech level dBFS"])
            print("       dropouts at (s): " + ", ".join(f"{s:.2f}" for s in at[:20]) + (" ..." if len(at) > 20 else ""))


if __name__ == "__main__":
    main()
