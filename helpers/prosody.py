"""Rhythm pass for narration: varied pace, pauses, pitch arc and breaths instead of one fixed rate.

Usage: python helpers/prosody.py --voice-dir D:/videos/聲音範本/A1_男聲 --tag NAME [--sections 0,1] [--edit DIR]
       python helpers/prosody.py --voice ID --tag NAME --breath-from OLDTAG
  --edit is the episode edit/ folder (default: the current folder).
  reads  edit/voice/台詞_v2.txt
  writes edit/voice/錄音室版/NAME_raw.mp3   (model take as is, podcast chain)
         edit/voice/錄音室版/NAME_rhythm.mp3 (after the rhythm pass)
         edit/voice/錄音室版/NAME.json      (per-line plan + measured result)

Per line (one caption line = one breath phrase) the plan sets:
  role   - from the text: punch / reveal / context / question / normal
  target - spoken rate for that phrase (chars/s); each phrase is time-stretched from the model's own rate to it
  pitch  - semitone offset (raised for reveals, lowered on sentence endings)
  pause  - silence after it, from the punctuation level (Tseng 2009: ~0.43 / 0.74 / 1.15 s) with jitter
  breath - a breath slot before the phrase once enough time has passed since the last one
The model's own breaths are kept only at breath slots, shortened and pulled down under the voice (studio
breath control); --breath-tags also asks the model for an [inhales] there (sounds staged, off by default).
Output follows the studio spec in recipes/錄音室級旁白.md; check it with vocal_qc.py.
"""

import argparse
import base64
import json
import random
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_tts import EDIT, PUNCT, load_key, parse_script  # noqa: E402

OUT = EDIT / "voice" / "錄音室版"
MODEL = "eleven_v4"
SR = 48000
SETTINGS = {"stability": 0.35, "similarity_boost": 0.8, "style": 0.35, "speed": 1.15}
TAG = re.compile(r"\[[^\]]*\]")

# Pause after a phrase by its closing punctuation (seconds, before role scaling and jitter)
PAUSE = {"、": 0.16, "，": 0.30, "：": 0.42, "；": 0.48, "。": 0.62, "！": 0.62, "？": 0.80}
PAUSE_SECTION = 1.2
BREATH_EVERY = 7.0     # seconds of speech between inserted breaths
BREATH_MIN_PAUSE = 0.55   # breathe only at sentence-level pauses
BREATH_BELOW = 32.0       # breath peak under speech before the chain; compression lifts it ~4 dB (18 dB final was too loud)
BREATH_MAX = 0.32         # seconds
SECTION_LIFT_HOOK = 1.5   # dB: the hook is delivered with more energy than the body
LUFS, PEAK = -16.0, 0.87  # integrated target; sample-peak ceiling (~ -1.2 dBFS)
# Studio vocal chain: rumble/plosive cut, de-mud, presence, air, de-ess, two-stage dynamics
STUDIO_CHAIN = ("highpass=f=75:poles=2,equalizer=f=300:t=q:w=1:g=-2,equalizer=f=4000:t=q:w=1.2:g=1.5,"
                "highshelf=f=10000:g=1.5,deesser=i=0.35:m=0.5:f=0.5,"
                "acompressor=threshold=-20dB:ratio=2:attack=12:release=180:makeup=1.5,"
                "acompressor=threshold=-8dB:ratio=6:attack=2:release=60")
# Treated-room floor, about -68 dBFS RMS: present, never heard over the voice
ROOM_TONE = "anoisesrc=color=pink:amplitude=0.0025:sample_rate=48000,highpass=f=120,lowpass=f=4000"

NUM = re.compile(r"[零一二三四五六七八九十百千萬兩0-9]+\s*(萬|億|顆|成|%|倍)")
DATE = re.compile(r"^[一二三四五六七八九十]+月|^[一二三四五六七八九十]+天後|^接下來")
ROLE = {  # target rate (chars/s), pitch (semitones), pause scale, level (dB)
    "punch":    (3.9, -0.3, 1.25, -0.5),
    "reveal":   (4.1, +0.6, 1.15, +2.5),
    "question": (3.9, +0.4, 1.30, +1.5),
    "context":  (5.3, 0.0, 0.85, -2.0),
    "normal":   (4.8, 0.0, 1.00, 0.0),
}
TEMPO_RANGE = (0.80, 1.15)   # beyond this the stretch starts to sound processed
MID_TARGET = 5.1             # middle clause of a long sentence
PAUSE_SCALE = 1.0
LATIN_WORD = re.compile(r"[A-Za-z]+")
# Delivery profiles. podcast: the calm reading above. news: matched to the reference short
# (spc3YBqiC4M): articulation 7.3 syl/s (sd 0.9), pauses median 0.40 s, p90 0.72 s.
PROFILES = {
    "podcast": None,
    "news": {"speed": 1.2, "tempo": (0.85, 1.55), "mid": 7.8, "pause": 0.72, "breath_min_pause": 0.36,
             "targets": {"punch": 6.4, "reveal": 6.6, "question": 6.6, "context": 8.0, "normal": 7.4}},
}


def use_profile(name):
    global TEMPO_RANGE, MID_TARGET, PAUSE_SCALE, BREATH_MIN_PAUSE
    prof = PROFILES[name]
    if prof is None:
        return
    SETTINGS["speed"] = prof["speed"]
    TEMPO_RANGE, MID_TARGET, PAUSE_SCALE = prof["tempo"], prof["mid"], prof["pause"]
    BREATH_MIN_PAUSE = prof.get("breath_min_pause", BREATH_MIN_PAUSE)
    for role, rate in prof["targets"].items():
        ROLE[role] = (rate, *ROLE[role][1:])


def syllables(say):
    """Spoken syllables: one per CJK char or digit, ~1.6 per Latin word."""
    t = TAG.sub("", say)
    return len(clean(LATIN_WORD.sub("", t))) + 1.6 * len(LATIN_WORD.findall(t))


def clean(say):
    return "".join(c for c in TAG.sub("", say) if c not in PUNCT)


def role_of(say, last_in_sentence):
    t = TAG.sub("", say).strip()
    if t.endswith("？"):
        return "question"
    if NUM.search(t):
        return "reveal"
    if DATE.search(t):
        return "context"
    if last_in_sentence and len(clean(t)) <= 9:
        return "punch"
    return "normal"


def plan_section(sec, tags=False):
    """Annotate each line with role/tempo/pitch/pause/breath; returns the text to send with [inhales] tags."""
    lines, since_breath = [], BREATH_EVERY  # breathe before the first phrase of a section
    for s in sec["sentences"]:
        for j, l in enumerate(s["lines"]):
            last = j == len(s["lines"]) - 1
            role = role_of(l["say"], last)
            target, pitch, pscale, gain = ROLE[role]
            if role == "normal" and 0 < j < len(s["lines"]) - 1:
                target = MID_TARGET              # middle of a long sentence moves faster
            if last and role in ("normal", "context"):
                pitch = -0.3                     # sentence endings settle down
            mark = TAG.sub("", l["say"]).strip()[-1]
            rng = random.Random(l["say"])
            pause = PAUSE.get(mark, 0.2) * pscale * PAUSE_SCALE * rng.uniform(0.85, 1.15)
            lines.append({"n": s["n"], "say": l["say"], "role": role, "target": round(target * rng.uniform(0.95, 1.05), 2),
                          "pitch": pitch, "gain": gain, "pause": round(pause, 3), "breath": False, "tagged": False,
                          "show": l["show"], "en": l["en"]})
    # Pre-reveal beat: a little extra air before the number lands
    for a, b in zip(lines, lines[1:]):
        if b["role"] == "reveal":
            a["pause"] = round(a["pause"] + 0.18, 3)
    for k, l in enumerate(lines):
        before = lines[k - 1]["pause"] if k else 1.0
        if since_breath >= BREATH_EVERY and before >= BREATH_MIN_PAUSE:
            l["breath"], l["tagged"], since_breath = True, tags, 0.0
        since_breath += syllables(l["say"]) / l["target"] + l["pause"]
    lines[-1]["pause"] = PAUSE_SECTION
    text = "".join(("[inhales] " if l["tagged"] else "") + l["say"] for l in lines)
    return lines, text


def tts(key, voice_id, text, prev_text, next_text):
    body = {"text": text, "model_id": MODEL, "voice_settings": SETTINGS}
    if prev_text:
        body["previous_text"] = prev_text
    if next_text:
        body["next_text"] = next_text
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_192",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"xi-api-key": key, "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"TTS failed {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")


def spans(lines, text, alignment):
    """(start, end) of spoken chars per line; works whether the alignment includes the tag text or not."""
    chars = alignment["characters"]
    st, en = alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
    got = "".join(chars)
    if got == text:
        strip = False
    elif got == TAG.sub("", text):
        strip = True
    else:
        raise SystemExit(f"alignment text mismatch: {got[:60]}...")
    out, pos = [], 0
    for l in lines:
        prefix = "[inhales] " if l["tagged"] else ""
        prefix = TAG.sub("", prefix) if strip else prefix
        pos += len(prefix)
        idx = [i for i in range(pos, pos + len(l["say"])) if chars[i] not in PUNCT]
        out.append((st[idx[0]], en[idx[-1]]))
        pos += len(l["say"])
    return out


def decode(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def stretch(x, tempo, semitones):
    if abs(tempo - 1) < 1e-3 and abs(semitones) < 1e-3:
        return x
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.wav", Path(d) / "b.wav"
        sf.write(a, x, SR)
        # Pitch by resampling (no phase vocoder), tempo by WSOLA (atempo): both stay clean on speech,
        # where rubberband at 1.3x+ left a phasey, processed tone
        r = 2 ** (semitones / 12)
        t = tempo / r
        chain = [f"asetrate={SR * r:.2f}", f"aresample={SR}:resampler=soxr"] if abs(semitones) > 1e-3 else []
        while t > 2.0:
            chain.append("atempo=2.0"); t /= 2.0
        chain.append(f"atempo={t:.5f}")
        f = ",".join(chain)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a), "-af", f, str(b)], check=True)
        y, _ = sf.read(b, dtype="float32")
    return y


def fade(x, ms=12):
    n = min(int(SR * ms / 1000), len(x) // 2)
    if n:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def breath_in_gap(g):
    """Start index of a breath-like stretch in a gap (energy well above digital silence), or None."""
    hop = int(SR * 0.01)
    if len(g) < hop * 12:
        return None
    rms = np.sqrt(np.convolve(g ** 2, np.ones(hop) / hop, "valid")[::hop])
    loud = 20 * np.log10(rms + 1e-9) > -50
    run = 0
    for i, v in enumerate(loud):
        run = run + 1 if v else 0
        if run >= 12:
            return max(0, (i - run - 5)) * hop
    return None


def trim_tail(x, floor_db=-55.0):
    """Drop the digital near-silence the model leaves between a breath and the next word."""
    hop = int(SR * 0.01)
    if len(x) < hop:
        return x
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, "valid")[::hop])
    live = np.where(20 * np.log10(rms + 1e-9) > floor_db)[0]
    return x[: (live[-1] + 1) * hop] if len(live) else x[:0]


def rebuild(audio, lines, sp, bank):
    """Cut the take into phrases, reshape each, re-space them with planned pauses; keep real breaths at slots only."""
    pad_a, pad_b = int(0.04 * SR), int(0.07 * SR)
    hop = int(SR * 0.02)
    frames = np.sqrt(np.convolve(audio ** 2, np.ones(hop) / hop, "valid")[::hop])
    speech_db = 20 * np.log10(np.percentile(frames[frames > 10 ** (-40 / 20)], 70) + 1e-9)
    out, kept = [np.zeros(int(0.5 * SR), np.float32)], 0
    for k, (l, (a, b)) in enumerate(zip(lines, sp)):
        s, e = max(0, int(a * SR) - pad_a), int(b * SR) + pad_b
        nxt = int(sp[k + 1][0] * SR) - pad_a if k + 1 < len(sp) else e
        e = min(e, max(nxt, int(b * SR)))
        phrase = stretch(audio[s:e], l["tempo"], l["pitch"]).astype(np.float32) * 10 ** (l["gain"] / 20)
        l["t0"] = sum(map(len, out)) / SR + pad_a / SR * l["tempo"] ** -1
        out.append(fade(phrase))
        l["t1"] = sum(map(len, out)) / SR - pad_b / SR / l["tempo"]
        gap = audio[e:nxt] if nxt > e else np.zeros(0, np.float32)
        bi = breath_in_gap(gap)
        tail = np.zeros(0, np.float32)
        if k + 1 < len(lines) and lines[k + 1]["breath"] and (bi is not None or bank):
            # the model's own breath if it took one here, else one of this voice's harvested breaths
            src = trim_tail(gap[bi:] if bi is not None else bank[kept % len(bank)])
            tail = src[-int(BREATH_MAX * random.Random(k).uniform(0.75, 1.0) * SR):].copy()
            hop10 = int(SR * 0.01)   # peak of 10 ms RMS: breaths are spiky, the mean understates them
            level = 20 * np.log10(np.sqrt(np.convolve(tail ** 2, np.ones(hop10) / hop10, "valid")).max() + 1e-9)
            gain_db = speech_db - BREATH_BELOW + random.Random(k).uniform(-1.5, 1.5) - level
            tail *= 10 ** (min(gain_db, 20.0) / 20)
            n_in, n_out = min(int(0.08 * SR), len(tail) // 2), int(0.015 * SR)
            tail[:n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)
            tail[-n_out:] *= np.linspace(1, 0.3, n_out, dtype=np.float32)
            kept += 1
        l["breath_kept"] = round(len(tail) / SR, 2)
        out.append(np.zeros(int(max(l["pause"] - len(tail) / SR, 0.08) * SR), np.float32))
        if len(tail):
            l["breath_at"] = sum(map(len, out)) / SR   # offset inside this section's rebuilt audio
        out.append(tail)
    return np.concatenate(out), kept


def harvest(tags):
    """Breaths from earlier takes of the same voice (OUT/<tag>_s*.json), longest-first, as raw audio."""
    bank = []
    for tag in tags:
        for meta in sorted(m for m in OUT.glob(f"{tag}_s*.json") if re.fullmatch(rf"{re.escape(tag)}_s\d+", m.stem)):
            d = json.loads(meta.read_text(encoding="utf-8"))
            mp3 = meta.with_suffix(".mp3")
            mp3.write_bytes(base64.b64decode(d["audio_base64"]))
            audio = decode(mp3)
            al = d["alignment"]
            text = "".join(al["characters"])
            tagged = [False] * len(text)
            for m in TAG.finditer(text):
                tagged[m.start():m.end()] = [True] * (m.end() - m.start())
            # spoken characters only: a tag's own time span is where the breath sits
            spoken = [i for i, c in enumerate(text) if not tagged[i] and c not in PUNCT]
            ends = [al["character_end_times_seconds"][i] for i in spoken]
            starts = [al["character_start_times_seconds"][i] for i in spoken]
            for a, b in zip(ends, starts[1:]):
                gap = audio[int(a * SR) + int(0.07 * SR): int(b * SR) - int(0.04 * SR)]
                bi = breath_in_gap(gap) if len(gap) > 0 else None
                if bi is not None:
                    br = trim_tail(gap[bi:])
                    if int(0.2 * SR) <= len(br):
                        bank.append(br.copy())
    # loudest first: the quiet ones are room noise, not breaths
    return sorted(bank, key=lambda x: -np.sqrt(np.mean(x ** 2)))[:8]


def integrated_lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])


def finish(x, path):
    """Studio chain -> gain to the loudness target -> peak limit -> treated-room floor underneath."""
    with tempfile.TemporaryDirectory() as d:
        a, v = Path(d) / "a.wav", Path(d) / "v.wav"
        sf.write(a, x, SR)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a), "-af", STUDIO_CHAIN, str(v)], check=True)
        gain = LUFS - integrated_lufs(v)
        dur = len(x) / SR
        fc = (f"[0:a]volume={gain:.2f}dB,alimiter=limit={PEAK}:attack=3:release=50:level=false[v];"
              f"{ROOM_TONE},atrim=0:{dur:.3f}[rt];[v][rt]amix=inputs=2:normalize=0[m]")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(v), "-filter_complex", fc, "-map", "[m]",
                        "-ar", "48000", "-b:a", "192k", str(path)], check=True)
        # lossless master next to the mp3: the edit mixes from this, never from the mp3
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(v), "-filter_complex", fc, "-map", "[m]",
                        "-ar", "48000", "-c:a", "pcm_s24le", str(Path(path).with_suffix(".wav"))], check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--voice-dir", help="voice template folder (voice.json + breaths/*.wav), e.g. D:/videos/聲音範本/A1_男聲")
    p.add_argument("--voice", help="voice id; read from --voice-dir when omitted")
    p.add_argument("--edit", help="episode edit/ folder (default: the current folder)")
    p.add_argument("--tag", required=True)
    p.add_argument("--profile", choices=sorted(PROFILES), default="podcast")
    p.add_argument("--script", default=str(EDIT / "voice" / "台詞_v2.txt"))
    p.add_argument("--sections", default="0,1")
    p.add_argument("--breath-tags", action="store_true", help="ask the model for [inhales] at breath slots")
    p.add_argument("--breath-from", default="", help="comma-separated earlier tags of this voice to harvest breaths from")
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    use_profile(args.profile)
    sections = parse_script(Path(args.script))
    pick = [int(x) for x in args.sections.split(",")]
    key = load_key()

    bank = harvest([t for t in args.breath_from.split(",") if t])
    if args.voice_dir:
        vdir = Path(args.voice_dir)
        args.voice = args.voice or json.loads((vdir / "voice.json").read_text(encoding="utf-8"))["voice_id"]
        bank += [sf.read(f, dtype="float32")[0] for f in sorted((vdir / "breaths").glob("*.wav"))]
    if not args.voice:
        sys.exit("need --voice or --voice-dir")
    print(f"breath bank: {len(bank)} samples")
    raw_all, new_all, report = [], [], []
    for i in pick:
        lines, text = plan_section(sections[i], args.breath_tags)
        cache = OUT / f"{args.tag}_s{i}.json"
        if cache.is_file() and json.loads(cache.read_text(encoding="utf-8")).get("key") == [text, SETTINGS]:
            d = json.loads(cache.read_text(encoding="utf-8"))
        else:
            prev_text = TAG.sub("", plan_section(sections[i - 1])[1]) if i else None
            next_text = TAG.sub("", plan_section(sections[i + 1])[1]) if i + 1 < len(sections) else None
            d = tts(key, args.voice, text, prev_text, next_text)
            d["text"], d["key"] = text, [text, SETTINGS]
            cache.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        mp3 = OUT / f"{args.tag}_s{i}.mp3"
        mp3.write_bytes(base64.b64decode(d["audio_base64"]))
        audio = decode(mp3)
        sp = spans(lines, text, d["alignment"])
        for l, (a, b) in zip(lines, sp):
            l["model_rate"] = round(syllables(l["say"]) / max(b - a, 0.05), 2)
            t = l["target"] / l["model_rate"]
            l["tempo"] = round(min(max(t, TEMPO_RANGE[0]), TEMPO_RANGE[1]), 3)
            l["final_rate"] = round(l["model_rate"] * l["tempo"], 2)
        offset = sum(map(len, new_all)) / SR
        rebuilt, kept = rebuild(audio, lines, sp, bank)
        if i == 0:
            rebuilt *= 10 ** (SECTION_LIFT_HOOK / 20)
        for l in lines:
            if "breath_at" in l:
                l["breath_at"] = round(l["breath_at"] + offset, 3)
            l["t0"], l["t1"] = round(l["t0"] + offset, 3), round(l["t1"] + offset, 3)
        raw_all += [audio, np.zeros(int(1.0 * SR), np.float32)]
        new_all.append(rebuilt)
        report.append({"section": sections[i]["name"], "start": round(offset, 3),
                       "end": round(offset + len(rebuilt) / SR, 3), "breaths_kept": kept, "lines": lines})

    finish(np.concatenate(raw_all), OUT / f"{args.tag}_raw.mp3")
    finish(np.concatenate(new_all), OUT / f"{args.tag}_rhythm.mp3")
    (OUT / f"{args.tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for sec in report:
        print(f"## {sec['section']}  (breaths kept from the take: {sec['breaths_kept']})")
        for l in sec["lines"]:
            print(f"  {l['role']:8} tempo {l['tempo']:.2f} pitch {l['pitch']:+.1f} pause {l['pause']:.2f}"
                  f" {'B' if l['breath'] else ' '} kept {l['breath_kept']:.2f}  rate {l['model_rate']:.1f}->{l['final_rate']:.1f}"
                  f"  {TAG.sub('', l['say'])}")


if __name__ == "__main__":
    main()
