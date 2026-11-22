"""Generate narration per sentence via ElevenLabs, then lay out the timeline.

Usage: python helpers/voice_tts.py [--edit DIR] [--voice ID] [--only 7,12] [--dry]
  --edit is the episode edit/ folder (default: the current folder); prosody.py and signoff.py take it too.
  reads  edit/voice/台詞.txt
  writes edit/voice/sNN.mp3 + sNN.json (cached; delete a file to regenerate that sentence)
         edit/voice_lines.json, edit/cues.json, edit/master.srt, edit/timeline.json
"""

import argparse
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path



def edit_dir(argv=None):
    """Episode edit/ folder for the voice tools: --edit DIR anywhere on the command line, else the current folder.
    Read before argparse so the module-level output folders of prosody.py and signoff.py follow it."""
    argv = sys.argv if argv is None else argv
    if "--edit" in argv and argv.index("--edit") + 1 < len(argv):
        return Path(argv[argv.index("--edit") + 1]).resolve()
    return Path.cwd()


EDIT = edit_dir()
VOICE_DIR = EDIT / "voice"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"   # the skill's .env, same as transcribe.py
VOICE_ID = "Z9RJEkFYQw307BCQULDR"   # default narration voice; --voice overrides it
MODEL = "eleven_multilingual_v2"
SEED = 1112

LEAD_IN = 1.2          # silence before the first word (fade in from black)
GAP = 0.45             # pause between sentences
GAP_QUESTION = 0.9     # pause after a question
GAP_SECTION = 1.0      # pause before a section without a chapter card
GAP_CHAPTER = 3.4      # pause that holds a chapter card
CARD_PAD = 0.4         # chapter card starts/ends this far from the voice
CUE_HOLD = 0.25        # caption stays this long after its last character
PUNCT = set("，。、；：？！「」 ")


def load_key():
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("ELEVENLABS_API_KEY not found")


# Parse 台詞.txt into sections: [{"name", "card", "sentences": [{"n", "lines": [...]}]}]
def parse_script(path):
    sections = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith("##")):
            continue
        if line.startswith("##"):
            parts = line[2:].strip().split("|")
            sections.append({"name": parts[0], "card": parts[1] if len(parts) > 1 else None, "sentences": []})
            continue
        n, say, show, en = line.split("|")
        sents = sections[-1]["sentences"]
        if not sents or sents[-1]["n"] != int(n):
            sents.append({"n": int(n), "lines": []})
        sents[-1]["lines"].append({"say": say, "show": show, "en": en})
    return sections


def sentence_text(s):
    return "".join(l["say"] for l in s["lines"])


def tts(key, text, prev_text, next_text):
    body = {"text": text, "model_id": MODEL, "seed": SEED}
    if prev_text:
        body["previous_text"] = prev_text
    if next_text:
        body["next_text"] = next_text
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps?output_format=mp3_44100_128",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"xi-api-key": key, "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


# Per line: (first spoken char start, last spoken char end) in seconds, from the character alignment
def line_spans(sentence, alignment):
    chars, starts, ends = alignment["characters"], alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
    text = sentence_text(sentence)
    if "".join(chars) != text:
        raise ValueError(f"alignment text mismatch for #{sentence['n']}")
    spans, pos = [], 0
    for l in sentence["lines"]:
        idx = [i for i in range(pos, pos + len(l["say"])) if chars[i] not in PUNCT]
        spans.append((starts[idx[0]], ends[idx[-1]]))
        pos += len(l["say"])
    return spans


def fmt_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main():
    global VOICE_ID
    p = argparse.ArgumentParser()
    p.add_argument("--edit", help="episode edit/ folder (default: the current folder)")
    p.add_argument("--voice", help=f"ElevenLabs voice id (default {VOICE_ID})")
    p.add_argument("--only", help="comma-separated sentence numbers to (re)generate")
    p.add_argument("--dry", action="store_true", help="only lay out cached audio, no API calls")
    args = p.parse_args()
    VOICE_ID = args.voice or VOICE_ID
    only = {int(x) for x in args.only.split(",")} if args.only else None

    sections = parse_script(VOICE_DIR / "台詞.txt")
    flat = [s for sec in sections for s in sec["sentences"]]
    key = None if args.dry else load_key()

    billed = 0
    for i, s in enumerate(flat):
        mp3, meta = VOICE_DIR / f"s{s['n']:02d}.mp3", VOICE_DIR / f"s{s['n']:02d}.json"
        cached = mp3.is_file() and meta.is_file() and json.loads(meta.read_text(encoding="utf-8"))["text"] == sentence_text(s)
        if args.dry or (cached and not (only and s["n"] in only)):
            continue
        prev_text = sentence_text(flat[i - 1]) if i else None
        next_text = sentence_text(flat[i + 1]) if i + 1 < len(flat) else None
        d = tts(key, sentence_text(s), prev_text, next_text)
        mp3.write_bytes(base64.b64decode(d["audio_base64"]))
        meta.write_text(json.dumps({"text": sentence_text(s), "alignment": d["alignment"]}, ensure_ascii=False), encoding="utf-8")
        billed += len(sentence_text(s))
        print(f"#{s['n']:02d} generated ({len(sentence_text(s))} chars)")

    # Lay out: each file starts so that its first word lands after the chosen gap
    segments, cues, chapters, sentence_times = [], [], [], []
    speech_end, first = 0.0, True
    for sec in sections:
        for k, s in enumerate(sec["sentences"]):
            meta = json.loads((VOICE_DIR / f"s{s['n']:02d}.json").read_text(encoding="utf-8"))
            spans = line_spans(s, meta["alignment"])
            if first:
                word_at = LEAD_IN
            elif k == 0:
                word_at = speech_end + (GAP_CHAPTER if sec["card"] else GAP_SECTION)
                if sec["card"]:
                    chapters.append({"name": sec["name"], "title": sec["card"],
                                     "start": round(speech_end + CARD_PAD, 3), "end": round(word_at - CARD_PAD, 3)})
            else:
                prev_say = sentence_text(sec["sentences"][k - 1])
                word_at = speech_end + (GAP_QUESTION if prev_say.endswith("？") else GAP)
            file_start = word_at - spans[0][0]
            segments.append({"audio": f"voice/s{s['n']:02d}.mp3", "start": round(file_start, 3), "lines": s["lines"]})
            for l, (a, b) in zip(s["lines"], spans):
                cues.append({"seg": len(segments) - 1, "n": s["n"], "audio": f"s{s['n']:02d}.mp3",
                             "start": round(file_start + a, 3), "end": round(file_start + b, 3),
                             "say": l["say"], "show": l["show"], "en": l["en"]})
            speech_end = file_start + spans[-1][1]
            sentence_times.append({"n": s["n"], "section": sec["name"], "start": round(word_at, 3), "end": round(speech_end, 3)})
            first = False

    # Caption display: hold briefly after the last char, never overlap the next cue
    for a, b in zip(cues, cues[1:]):
        a["end"] = round(min(a["end"] + CUE_HOLD, b["start"]) if b["start"] - a["end"] < 0.3 else a["end"] + CUE_HOLD, 3)
    cues[-1]["end"] = round(cues[-1]["end"] + CUE_HOLD, 3)

    (EDIT / "voice_lines.json").write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=1), encoding="utf-8")
    (EDIT / "cues.json").write_text(json.dumps(cues, ensure_ascii=False, indent=1), encoding="utf-8")
    (EDIT / "timeline.json").write_text(json.dumps({"sentences": sentence_times, "chapters": chapters,
                                                    "speech_end": round(speech_end, 3)}, ensure_ascii=False, indent=1), encoding="utf-8")
    srt = "".join(f"{i}\n{fmt_srt(c['start'])} --> {fmt_srt(c['end'])}\n{c['show']}\n{c['en']}\n\n" for i, c in enumerate(cues, 1))
    (EDIT / "master.srt").write_text(srt, encoding="utf-8")
    print(f"billed ~{billed} chars; {len(cues)} cues; speech ends at {speech_end:.2f}s; {len(chapters)} chapter cards")


if __name__ == "__main__":
    main()
