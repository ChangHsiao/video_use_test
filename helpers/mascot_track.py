"""Brand mascot track: 合成.json mascot events + voice loudness -> transparent MOV for the composer.

Usage (from the repo):
    uv run python helpers/mascot_track.py <edit>/合成.json [--out <edit>/mascot/track.mov]

合成.json:
    "style": "<style name>"            (default 暗色科技風; the style's brand must have a "mascot" block)
    "mascot": {"seed": 0, "events": [
        {"at": "<caption text>", "do": "surprised", "dir": "right", "hold": 1.6, "offset": 0.0,
         "emote": "exclaim", "emote_hold": 1.2, "target": [x, y]}, ...]}
"at" is matched against <edit>/cues.json with compose.find_cue, each event searching after the previous
event's cue; the event starts at that cue's start + offset. Held states last "hold" seconds, then the
mascot returns to idle; blink, squash, wave, spin, shiver and jump are one-shot. The pose comes from the
same mascot.MascotTimeline compose.py draws live (mouth and stretch follow the narration in
voice_lines.json, cached in <edit>/mascot/voice_features.npz); this fixed-size track ignores position
(moves "to", hops, jumps, floating). compose.py no longer needs this track: it draws the mascot live.

Output: square brand mascot.track_px, 30 fps, MOV with alpha (qtrle), exactly round(total * 30) frames
where total = compose.load_voice(...)[1].
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compose  # noqa: E402
import mascot  # noqa: E402
import registry  # noqa: E402

SR = mascot.VOICE_SR
SILENCE_DB = mascot.SILENCE_DB


class TrackError(Exception):
    pass


def load_spec_for_plan(plan, styles_root=None, brands_root=None):
    name = plan.get("style") or compose.DEFAULT_STYLE
    try:
        return mascot.spec_from_style(registry.load_style(name, styles_root, brands_root))
    except registry.ConfigError as e:
        raise TrackError(str(e))


# plan["mascot"]["events"] -> [(mascot.Event, cue index)]; same resolution as compose.resolve_mascot_events
def resolve_events(plan, cues):
    try:
        return compose.resolve_mascot_events((plan.get("mascot") or {}).get("events"), cues)
    except compose.ComposeError as e:
        raise TrackError(str(e))


# the voice track as one mono float array at SR (each segment at its start time)
def voice_samples(voice, total):
    try:
        return mascot.voice_samples(voice, total, SR)
    except RuntimeError as e:
        raise TrackError(str(e))


# per-frame loudness 0..1: RMS in dB between SILENCE_DB and the loud end of the voice, then smoothed
def loudness(samples, frames, smooth):
    return mascot.loudness(samples, frames, smooth, SR, mascot.FPS)


def build(plan_path, out=None):
    plan_path = Path(plan_path)
    edit = plan_path.parent
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        cues = json.loads((edit / "cues.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise TrackError(f"讀不到 {e}")
    spec = load_spec_for_plan(plan)
    resolved = resolve_events(plan, cues)
    try:
        voice, total = compose.load_voice(edit / "voice_lines.json")
    except compose.ComposeError as e:
        raise TrackError(str(e))
    frames = round(total * mascot.FPS)
    seed = int((plan.get("mascot") or {}).get("seed", 0))
    try:
        features = mascot.voice_features(voice, total, edit / "mascot" / "voice_features.npz", spec)
        # the same live timeline compose.py draws; a fixed track ignores position ("to", hops, jumps, float)
        tl = mascot.MascotTimeline(spec, [e for e, _ in resolved], features, mascot.FPS, seed=seed, duration=total)
    except ValueError as e:
        raise TrackError(f"mascot.events：{e}")
    except RuntimeError as e:
        raise TrackError(str(e))
    px = int(spec.get("track_px", 300))
    out = Path(out) if out else edit / "mascot" / "track.mov"
    extent = mascot.view_extent(spec)
    def draw(t):
        st = tl.state(t)  # pose and emotes (an emote sits up-right of the head inside the square)
        return mascot.render_frame(spec, pose=st.pose, px=px, extent=extent, emotes=st.emotes)

    gen = (draw(i / mascot.FPS) for i in range(frames))
    mascot.encode(gen, frames, px, out, alpha=True)
    return out, resolved, cues, total, frames, px


def main(argv=None):
    ap = argparse.ArgumentParser(description="品牌角色的透明軌（MOV 含 alpha）")
    ap.add_argument("plan", help="<edit>/合成.json")
    ap.add_argument("--out", help="預設 <edit>/mascot/track.mov")
    args = ap.parse_args(argv)
    try:
        note = " （覆蓋舊檔）" if args.out and Path(args.out).exists() else ""
        out, resolved, cues, total, frames, px = build(args.plan, args.out)
    except (TrackError, RuntimeError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    print(f"角色事件 {len(resolved)} 個：")
    for e, idx in resolved:
        label = f"{e.do} {e.dir}" if e.dir else e.do
        print(f"  {e.t:7.2f}s  {label:<17} ← 第 {idx + 1} 句「{cues[idx]['show']}」")
    print(f"寫入 {out}{note}（{px}×{px}，{frames} 格，{total:.2f} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
