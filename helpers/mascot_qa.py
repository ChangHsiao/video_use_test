"""Mascot QA: does every gesture hit the real thing on screen, and does the mascot stay off the content?

Usage (from the repo):
    uv run python helpers/mascot_qa.py <edit>/合成.json [--out <edit>/mascot_qa]

Reads the same plan, cues, voice and timeline code as compose.py (compose.load_plan, build_timeline,
make_mascot) and checks:
  a. aim     every point / look event: the composited frame (picture exactly as compose builds it, plus the
             mascot and the text overlay) at the middle of its hold, with a crosshair on the target and a line
             along the extended notch (look: along the eyes) -> <n>_<at>.png. FAIL when the angle between that
             direction and the vector from the mascot's centre to the target is over 8 degrees, or when the notch
             is not extended; WARN when the event has no "target".
  b. overlap every 0.2 s: content = base-picture pixels clearly brighter than black (captions and titles are
             not content); FAIL when the mascot's opaque pixels (emotes included) cover more than 40 content
             pixels (1080x1920 scale) -> overlap_<time>.png for each failure.
  c. lane    every frame: the mascot's position stays inside the style's lane (hops may rise lane_rise_px).
Writes <out>/report.md and exits 1 on any FAIL (0 otherwise).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compose as cp  # noqa: E402
import mascot as ms  # noqa: E402
import registry  # noqa: E402

FPS = cp.FPS
ANGLE_FAIL = 8.0          # degrees
OVERLAP_FAIL_PX = 40      # content pixels under the mascot, at 1080x1920
SAMPLE_STEP = 0.2         # seconds between overlap samples (a multiple of 1/FPS)
CONTENT_LUMA = 60         # 0..255: base-picture pixels brighter than this count as content
AIM_EVENTS = ("point", "look")


class QAError(Exception):
    pass


# angle (degrees) between direction (screen orientation, +y down) from centre and the vector centre -> target
def aim_error(centre, direction, target):
    return ms.angle_error(centre, direction, target)


# plan, cues, shots, voice features and the live mascot timeline, exactly as compose.main builds them
def load(plan_path):
    plan_path = Path(plan_path)
    edit = plan_path.parent
    try:
        plan = cp.load_plan(plan_path)
        if not plan["mascot"]:
            raise QAError(f"{plan_path.name} 沒有 mascot")
        cues = json.loads((edit / "cues.json").read_text(encoding="utf-8"))
        voice, total = cp.load_voice(edit / "voice_lines.json")
        shots = cp.build_timeline(plan, cues, total, cp.media_duration)
        spec = ms.spec_from_brand(cp.STYLE["brand"])
        features = ms.voice_features(voice, total, edit / "mascot" / "voice_features.npz", spec, FPS)
        live = cp.make_mascot(plan, cues, features, total)
        raw = plan["mascot"].get("events") or []
        resolved = cp.resolve_mascot_events(raw, cues)
    except (cp.ComposeError, registry.ConfigError, OSError, json.JSONDecodeError, RuntimeError) as e:
        raise QAError(str(e))
    return {"edit": edit, "plan": plan, "cues": cues, "total": total, "shots": shots, "live": live, "raw": raw,
            "resolved": resolved, "spec": spec, "style": cp.STYLE}


# middle of an event's hold: halfway between the end of its transition and the next held change
def hold_middle(live, e):
    T = live.m["transition"]
    starts = [ct for ct, _, _ in live.changes]
    i = next((j for j, ev in enumerate(live.change_events) if ev is not None and ev.t == e.t and ev.do == e.do), None)
    end = starts[i + 1] if i is not None and i + 1 < len(starts) else e.t + (live.m["hold"] if e.hold is None else e.hold)
    return round(((e.t + T) + end) / 2 * FPS) / FPS


def _safe(text):
    return re.sub(r'[\\/:*?"<>|\s，、：？。！]+', "_", text).strip("_")[:24] or "event"


def _font(size):
    try:
        bold, _, index = cp.default_font()
        return ImageFont.truetype(bold, size, index=index)
    except (cp.ComposeError, OSError):
        return ImageFont.load_default()


# the composited 1080x1920 frame at t: base picture (compose.shot_command, one frame) + mascot + text overlay
def composite(shots, overlay, t, tmp):
    frame = round(t * FPS)
    shot = next(iter(cp.clip_shots(shots, frame / FPS, (frame + 1) / FPS)))
    base = Path(tmp) / "base.png"
    out = subprocess.run(cp.shot_command(shot, 1, base, overlay.scale, []), capture_output=True)
    if out.returncode != 0:
        raise QAError(f"截底圖失敗：{out.stderr.decode('utf-8', 'replace').strip()}")
    img = Image.open(base).convert("RGBA")
    img.alpha_composite(overlay.render(frame / FPS))
    return img.convert("RGB")


def _annotate(img, centre, direction, target, label, ok):
    d = ImageDraw.Draw(img)
    col = (16, 185, 129) if ok else (239, 68, 68)
    cx, cy = centre
    length = math.hypot(target[0] - cx, target[1] - cy) if target else 420
    d.line([(cx, cy), (cx + direction[0] * length, cy + direction[1] * length)], fill=(255, 255, 0), width=3)
    if target:
        tx, ty = target
        d.ellipse([tx - 26, ty - 26, tx + 26, ty + 26], outline=col, width=4)
        d.line([(tx - 44, ty), (tx + 44, ty)], fill=col, width=3)
        d.line([(tx, ty - 44), (tx, ty + 44)], fill=col, width=3)
    d.rectangle([0, 1820, 1080, 1920], fill=(0, 0, 0))
    d.text((24, 1840), label, fill=col, font=_font(40))


# a. every point / look event
def check_aims(ctx, out_dir, overlay):
    live, rows = ctx["live"], []
    with tempfile.TemporaryDirectory(prefix="mascot_qa_") as tmp:
        for n, (raw, (e, idx)) in enumerate(zip(ctx["raw"], ctx["resolved"]), 1):
            if e.do not in AIM_EVENTS:
                continue
            label = f"{n}. {e.do}「{raw['at']}」"
            t = hold_middle(live, e)
            st = live.state(t)
            target = raw.get("target")
            if e.do == "point":
                _, direction, ext = ms.extended_notch(live.spec, st.pose)
            else:
                lx, ly = st.pose.look_x, -st.pose.look_y
                norm = math.hypot(lx, ly)
                direction, ext = ((lx / norm, ly / norm) if norm > 1e-6 else (0.0, 0.0)), (1.0 if norm > 1e-6 else 0.0)
            err = aim_error((st.x, st.y), direction, target) if target and ext > 0 else None
            if not overlay.mascot_on(t):
                result, note = "WARN", "這個鏡頭不畫角色"
            elif target is None:
                result, note = "WARN", "沒有 target：方向沒辦法驗證"
            elif e.do == "point" and ext < 0.9:
                result, note = "FAIL", f"刻痕沒有伸出來（{ext:.2f}）"
            elif ext <= 0:
                result, note = "FAIL", "眼睛沒有看任何方向"
            else:
                result, note = ("PASS", "") if err <= ANGLE_FAIL else ("FAIL", f"偏了 {err:.1f}°")
            name = f"{n:02d}_{t:.2f}_{_safe(raw['at'])}.png"
            img = composite(ctx["shots"], overlay, t, tmp)
            text = f"{result} {e.do} {t:.2f}s" + (f"  err {err:.1f} deg" if err is not None else "  no target")
            _annotate(img, (st.x, st.y), direction, target, text, result == "PASS")
            img.save(out_dir / name)
            rows.append({"event": label, "time": t, "check": "aim", "result": result,
                         "angle": err, "image": name, "note": note})
    return rows


# base picture (no text) at 0.5 scale, one gray frame every SAMPLE_STEP seconds: yields (t, HxW uint8)
def base_samples(shots, total, tmp):
    base = cp.build_base(shots, total, Path(tmp) / "base.mp4", full=False)
    w, h = int(cp.WIDTH * 0.5), int(cp.HEIGHT * 0.5)
    step = round(SAMPLE_STEP * FPS)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(base), "-vf", f"select='not(mod(n\\,{step}))'",
                             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    i = 0
    try:
        while True:
            buf = proc.stdout.read(w * h)
            if len(buf) < w * h:
                break
            yield i * step / FPS, np.frombuffer(buf, np.uint8).reshape(h, w)
            i += 1
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


# opaque mascot pixels (alpha > 128) on a w x h canvas at scale
def mascot_mask(live, t, scale, w, h):
    img, cx, cy = live.frame(t, scale, ss=2)
    a = np.asarray(img)[..., 3] > 128
    x0, y0 = int(round(cx - img.width / 2)), int(round(cy - img.height / 2))
    out = np.zeros((h, w), bool)
    xs, ys = max(x0, 0), max(y0, 0)
    xe, ye = min(x0 + img.width, w), min(y0 + img.height, h)
    if xe > xs and ye > ys:
        out[ys:ye, xs:xe] = a[ys - y0:ye - y0, xs - x0:xe - x0]
    return out


# b. content overlap
def check_overlap(ctx, out_dir, overlay):
    live, rows, worst = ctx["live"], [], (0, 0.0)
    scale = 0.5
    with tempfile.TemporaryDirectory(prefix="mascot_qa_base_") as tmp:
        for t, gray in base_samples(ctx["shots"], ctx["total"], tmp):
            if t >= ctx["total"] or not overlay.mascot_on(t):
                continue
            h, w = gray.shape
            content = gray > CONTENT_LUMA
            m = mascot_mask(live, t, scale, w, h)
            px = int((m & content).sum()) * 4  # at 1080x1920
            worst = max(worst, (px, t))
            if px > OVERLAP_FAIL_PX:
                name = f"overlap_{t:07.2f}.png"
                vis = np.stack([gray] * 3, -1).copy()
                vis[m] = (vis[m] * 0.4 + np.array([245, 158, 11]) * 0.6).astype(np.uint8)
                vis[m & content] = (239, 68, 68)
                Image.fromarray(vis).save(out_dir / name)
                rows.append({"event": "—", "time": t, "check": "overlap", "result": "FAIL", "angle": None,
                             "image": name, "note": f"蓋住內容 {px} px"})
    rows.append({"event": "全片每 0.2 秒", "time": worst[1], "check": "overlap",
                 "result": "PASS" if not rows else "FAIL", "angle": None, "image": "",
                 "note": f"最多蓋住 {worst[0]} px（門檻 {OVERLAP_FAIL_PX}）"})
    return rows


# c. lane: the roaming position (and the drawn centre, with float / lift / bounce slack) stays in the lane
def check_lane(ctx):
    live, style = ctx["live"], ctx["style"]
    lane = (style.get("mascot") or {}).get("lane")
    if not lane:
        return [{"event": "—", "time": 0.0, "check": "lane", "result": "WARN", "angle": None, "image": "",
                 "note": "風格沒有角色走道"}]
    (x0, x1), (y0, y1) = sorted(lane["x"]), sorted(lane["y"])
    m = live.m
    rise = m["lane_rise_px"]
    bad = []
    for i in range(round(ctx["total"] * FPS)):
        t = i / FPS
        x, y, size, _ = live.place(t)
        k = size / live.home[2]
        slack = (m["bob_px"] + m["pitch_lift_px"] + m["excited_bounce_px"]) * k + 1
        st = live.state(t)
        ok = (x0 - 0.5 <= x <= x1 + 0.5 and y0 - rise - 0.5 <= y <= y1 + 0.5 and st.y >= y0 - rise - slack)
        if not ok:
            bad.append((t, x, y))
    if not bad:
        return [{"event": "全片每一格", "time": 0.0, "check": "lane", "result": "PASS", "angle": None, "image": "",
                 "note": f"x {x0:.0f}–{x1:.0f}、y {y0 - rise:.0f}–{y1:.0f}"}]
    rows, start = [], bad[0]
    for prev, cur in zip(bad, bad[1:] + [None]):
        if cur is None or cur[0] - prev[0] > 1.5 / FPS:
            rows.append({"event": "—", "time": start[0], "check": "lane", "result": "FAIL", "angle": None, "image": "",
                         "note": f"{start[0]:.2f}–{prev[0]:.2f}s 在走道外（[{start[1]:.0f}, {start[2]:.0f}]）"})
            start = cur
    return rows


def write_report(rows, out_dir, plan_path):
    counts = {r: sum(1 for x in rows if x["result"] == r) for r in ("PASS", "WARN", "FAIL")}
    angles = [x["angle"] for x in rows if x["angle"] is not None]
    lines = [f"# 角色 QA：{Path(plan_path).parent.parent.name}", "",
             f"- 分鏡：`{plan_path}`",
             f"- 結果：PASS {counts['PASS']}、WARN {counts['WARN']}、FAIL {counts['FAIL']}",
             f"- 指向誤差最大：{max(angles):.2f}°（門檻 {ANGLE_FAIL}°）" if angles else "- 沒有可量的指向",
             "", "| 事件 | 時間 | 檢查 | 結果 | 角度誤差 | 圖 | 說明 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        ang = f"{r['angle']:.2f}°" if r["angle"] is not None else ""
        img = f"[{r['image']}]({r['image']})" if r["image"] else ""
        lines.append(f"| {r['event']} | {r['time']:.2f}s | {r['check']} | {r['result']} | {ang} | {img} | {r['note']} |")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts


def run(plan_path, out_dir=None):
    ctx = load(plan_path)
    out_dir = Path(out_dir) if out_dir else ctx["edit"] / "mascot_qa"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    try:
        overlay = cp.Overlay(ctx["plan"]["title"], ctx["shots"], ctx["cues"], 1.0, cp.default_font(), mascot=ctx["live"])
    except cp.ComposeError as e:
        raise QAError(str(e))
    rows = check_aims(ctx, out_dir, overlay) + check_overlap(ctx, out_dir, overlay) + check_lane(ctx)
    return rows, write_report(rows, out_dir, plan_path), out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description="角色 QA：指向是否對準、有沒有蓋住內容、有沒有離開走道")
    ap.add_argument("plan", help="<edit>/合成.json")
    ap.add_argument("--out", help="預設 <edit>/mascot_qa")
    args = ap.parse_args(argv)
    try:
        rows, counts, out_dir = run(args.plan, args.out)
    except QAError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 2
    for r in rows:
        if r["result"] != "PASS" or r["check"] == "aim":
            ang = f" {r['angle']:.2f}°" if r["angle"] is not None else ""
            print(f"{r['result']:<4} {r['check']:<7} {r['time']:7.2f}s {r['event']}{ang} {r['note']}")
    print(f"PASS {counts['PASS']}、WARN {counts['WARN']}、FAIL {counts['FAIL']}；報告 {out_dir / 'report.md'}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
