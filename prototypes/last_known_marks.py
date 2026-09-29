r"""Measure the enemy "?" mark: its delay after the enemy's icon and how long it stays.

    .\.venv\Scripts\python.exe prototypes\last_known_marks.py [--limit N] [--record]

The player recalls that the red "?" appears after a delay and stays "a
couple seconds", and asked for both to be measured
[domain:minimap/last-known-mark]. No owner reads the mark. This prototype
takes the player's `?` marks in `labels/minimap` as anchors (one instance per
place and time; `labels/minimap_agent` repeats the same Ascent marks, so it
adds no anchor) and follows each through the minimap crop cache:

  1. presence: the death owner's red extractor
     (`adjudication.death.extract_minimap_death_marks`, red list) holds a
     blob within PLACE_PX of the anchor, at every cached frame from
     WINDOW_MS before to WINDOW_MS after it. The red run containing the
     anchor, bridged over gaps of at most GAP_FRAMES frames, is the
     candidate.
  2. the icon: the enemy ring detector (`icon_teardrop.detections`, enemy)
     at every frame from ICON_BACK_MS before the run to its start. A
     detection within ICON_PX of the anchor is the enemy's icon; red frames
     that hold one are the icon's own red, not the "?". Onset is the first
     red frame after the last icon frame; the delay is onset less the last
     icon frame.
  3. offset: the last frame of the run; the duration is offset less onset.
     After it, the enemy detector over OUT_MS says whether an icon returns
     within ICON_PX (`icon_returned`) or not (`vanished`); a stored enemy
     death within DEATH_MS of the offset is recorded beside it.

A run that touches the window's edge or a hole in the cache (a step over
HOLE_MS: the map closed, a stall) is censored on that side and keeps its
reason; a run with no icon in ICON_BACK_MS has no delay (`no_icon_seen`).
The last icon observation stands in for "left vision": the team's drawn
light is not read here, and an enemy stays drawn briefly after leaving
vision [domain:minimap/vision-trailing-persistence].

Reads the crop cache and stored rows only; decodes no video; writes to the
store only with `--record` (a `metrics` row) and its sheet. Unwired
(`"wire": "no"`, task `minimap-objects-b-20260929` in the store's
`notes/predictions.jsonl`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icon_portrait_gate as gate_  # noqa: E402
import icon_teardrop as it_  # noqa: E402
from reticle.adjudication.death import extract_minimap_death_marks  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "last-known-marks-0.1.0"
STORE = gate_.STORE
OUT = STORE / "analysis" / "minimap-objects-b-20260929"
SESSIONS = gate_.LABELLED

WINDOW_MS = 10000.0
#: After the anchor the window runs longer, to follow the mark's fade.
AFTER_MS = 16000.0
#: The fade: the "?" pixels' red contrast against a floor annulus, relative to
#: its first half second. It has begun to fade under FADE_HIGH of that, and
#: is gone under FADE_LOW, each held FADE_RUN frames.
FADE_HIGH = 0.8
FADE_LOW = 0.15
FADE_RUN = 3
PLACE_PX = 6.0
GAP_FRAMES = 2
ICON_PX = 10.0
ICON_BACK_MS = 4000.0
OUT_MS = 1000.0
HOLE_MS = 250.0
DEATH_MS = 1000.0
SAME_PX = 8.0       # two anchors are one instance within this and inside one run


def anchors(sid: str) -> list[dict]:
    p = STORE / "labels" / "minimap" / f"{sid}.jsonl"
    last = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            last[r["t_ms"]] = r
    out = []
    for r in sorted(last.values(), key=lambda r: r["t_ms"]):
        if r.get("uncertain"):
            continue
        for m in r.get("marks", []):
            if m["kind"] == "question":
                out.append({"session": sid, "t_ms": float(r["t_ms"]), "x": float(m["x"]),
                            "y": float(m["y"]), "roi": r.get("roi")})
    return out


def red_near(crop, floor, x, y, r):
    _blue, red = extract_minimap_death_marks(crop, floor)
    best = min(((math.hypot(bx - x, by - y), a, bx, by) for a, bx, by in red), default=None)
    return best if best is not None and best[0] <= r else None


def icon_near(crop, s, x, y, r):
    ds = [d for d in it_.detections(crop, "enemy", s) if math.hypot(d["cx"] - x, d["cy"] - y) <= r]
    return min(ds, key=lambda d: math.hypot(d["cx"] - x, d["cy"] - y)) if ds else None


def enemy_deaths(sid: str) -> list[float]:
    p = STORE / "events" / "death" / f"{sid}.jsonl"
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [float(r["t_ms"]) for r in rows if r.get("kind") == "death_verdict" and r.get("side") == "enemy"]


def measure(s, a: dict, deaths: list[float]) -> dict:
    T = [float(t) for t in s.cache_t if -WINDOW_MS <= t - a["t_ms"] <= AFTER_MS]
    crops = dict(s.crops(T))
    T = [t for t in T if t in crops]
    sc = widget_scale(next(iter(crops.values())).shape[1]) if crops else 1.0
    red = {t: red_near(crops[t], s.floor, a["x"], a["y"], PLACE_PX * sc) for t in T}
    i0 = min(range(len(T)), key=lambda i: abs(T[i] - a["t_ms"]))
    if red[T[i0]] is None:
        return {"status": "no_red_at_anchor"}
    # The run: extend both ways over gaps of at most GAP_FRAMES frames.
    lo = hi = i0
    miss = 0
    for i in range(i0 - 1, -1, -1):
        if red[T[i]] is not None:
            lo, miss = i, 0
        else:
            miss += 1
            if miss > GAP_FRAMES or T[i + 1] - T[i] > HOLE_MS:
                break
    miss = 0
    for i in range(i0 + 1, len(T)):
        if red[T[i]] is not None:
            hi, miss = i, 0
        else:
            miss += 1
            if miss > GAP_FRAMES or T[i] - T[i - 1] > HOLE_MS:
                break

    def edge(i, step):
        j = i + step
        if j < 0 or j >= len(T):
            return "window_edge"
        k = i
        while 0 <= k + step < len(T) and abs(k - i) <= GAP_FRAMES + 1:
            if abs(T[k + step] - T[k]) > HOLE_MS:
                return "cache_hole"
            k += step
        return None

    # The icon: enemy detections from ICON_BACK_MS before the run to its end.
    icon_t = {}
    for i in range(len(T)):
        if T[lo] - ICON_BACK_MS <= T[i] <= T[hi]:
            d = icon_near(crops[T[i]], s, a["x"], a["y"], ICON_PX * sc)
            if d is not None:
                icon_t[T[i]] = (d["cx"], d["cy"])
    # Onset: the first red frame of the run after the last icon frame at or
    # before the anchor; the anchor frame itself is the player's "?".
    icons_before = [t for t in icon_t if t <= T[i0]]
    last_icon = max(icons_before) if icons_before else None
    run = [T[i] for i in range(lo, hi + 1) if red[T[i]] is not None]
    after = [t for t in run if last_icon is None or t > last_icon]
    if not after:
        return {"status": "icon_at_anchor"}
    onset, offset = after[0], run[-1]
    on_cens = edge(lo, -1) if last_icon is None or last_icon < T[lo] else None
    off_cens = edge(hi, +1)
    # Did the icon stay drawn over the gap? (frames between last icon and onset)
    gap_frames = [t for t in T if last_icon is not None and last_icon < t < onset]
    ret = None
    if off_cens is None:
        for t in T:
            if offset < t <= offset + OUT_MS:
                d = icon_near(crops[t], s, a["x"], a["y"], 30.0 * sc)
                if d is not None:
                    ret = t
                    break
    dth = [td for td in deaths if abs(td - offset) <= DEATH_MS]
    li = icon_t.get(last_icon)
    fd = fade(crops, T, onset, a["x"], a["y"], sc) if ret is None and off_cens is None else {}
    return {**fd,"status": "measured", "onset_ms": onset, "offset_ms": offset,
            "last_icon_ms": last_icon,
            "delay_ms": None if last_icon is None else round(onset - last_icon, 1),
            "delay_reason": None if last_icon is not None else "no_icon_seen",
            "gap_frames": len(gap_frames),
            "duration_ms": round(offset - onset, 1),
            "onset_censored": on_cens if last_icon is None else None,
            "offset_censored": off_cens,
            "ending": None if off_cens else ("icon_returned" if ret else "vanished"),
            "icon_return_ms": None if ret is None else round(ret - offset, 1),
            "enemy_death_near_offset": dth,
            "icon_to_mark_px": None if li is None else round(math.hypot(li[0] - a["x"], li[1] - a["y"]), 1),
            "red_area": int(np.median([red[t][1] for t in run])),
            "frames": {"T": T, "lo": lo, "hi": hi}, "_crops": crops, "scale": sc}


def rednum(crop: np.ndarray) -> np.ndarray:
    c = crop.astype(np.float32)
    return c[..., 2] - np.maximum(c[..., 0], c[..., 1])


def fade(crops: dict, T: list[float], onset: float, x: float, y: float, sc: float) -> dict:
    """The mark's red contrast from onset on: the "?" pixels (R - max(G, B)
    over 40, within PLACE_PX + 3 of the anchor, at the frame 0.2 s after
    onset) less a floor annulus 11-15 px out, relative to its median over
    the first 0.5 s. Returns when it began to fade and when it was gone,
    each after onset, or the reason it could not be read. The extractor's
    offset comes before the mark is gone: the "?" fades, and the extractor
    loses it while it is still pale red."""
    after = [t for t in T if t >= onset]
    ref_t = next((t for t in after if t >= onset + 200.0), None)
    if ref_t is None:
        return {"fade_reason": "no_frames"}
    h, w = crops[ref_t].shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.hypot(xx - x, yy - y)
    mask = (rr <= (PLACE_PX + 3) * sc) & (rednum(crops[ref_t]) > 40)
    ann = (rr >= 11 * sc) & (rr <= 15 * sc)
    if mask.sum() < 5:
        return {"fade_reason": "no_mark_pixels"}
    sig = []
    for t in after:
        k = rednum(crops[t])
        sig.append((t, float(np.median(k[mask]) - np.median(k[ann]))))
    base = [v for t, v in sig if t <= onset + 500.0]
    plateau = float(np.median(base)) if base else 0.0
    if plateau <= 10:
        return {"fade_reason": "weak_plateau", "plateau": plateau}

    def first_below(frac):
        run = 0
        for i, (t, v) in enumerate(sig):
            run = run + 1 if v < frac * plateau else 0
            if run == FADE_RUN:
                return sig[i - FADE_RUN + 1][0]
        return None
    start, gone = first_below(FADE_HIGH), first_below(FADE_LOW)
    return {"plateau": round(plateau, 1),
            "fade_start_ms": None if start is None else round(start - onset, 1),
            "gone_ms": None if gone is None else round(gone - onset, 1),
            "fade_reason": None if gone is not None else "not_gone_in_window",
            "_sig": sig}


def strip_frame(r: dict, K: int = 16, Z: int = 4) -> np.ndarray:
    """Onset and offset sequences: 5 frames round each edge, the anchor ringed."""
    crops, T = r["_crops"], r["frames"]["T"]

    def at(t):
        c = crops[t]
        x0, y0 = int(round(r["x"])) - K, int(round(r["y"])) - K
        pad = cv2.copyMakeBorder(c, K, K, K, K, cv2.BORDER_CONSTANT)
        big = cv2.resize(pad[y0 + K:y0 + 3 * K, x0 + K:x0 + 3 * K], None, fx=Z, fy=Z,
                         interpolation=cv2.INTER_NEAREST)
        cv2.circle(big, (K * Z, K * Z), int(ICON_PX * Z), (0, 220, 0), 1)
        return big

    def seq(t_edge, label):
        i = T.index(t_edge)
        idx = [min(max(k, 0), len(T) - 1) for k in range(i - 2, i + 3)]
        tiles = []
        for k in idx:
            tl = at(T[k])
            txt = f"{label} {(T[k] - t_edge) / 1000:+.2f}s"
            cv2.putText(tl, txt, (2, 12), 0, 0.38, (0, 0, 0), 3)
            cv2.putText(tl, txt, (2, 12), 0, 0.38, (255, 255, 255), 1)
            tiles.append(tl)
        return np.hstack(tiles)

    sep = np.zeros((32 * 4, 6, 3), np.uint8)
    parts = [seq(r["onset_ms"], "on"), sep, seq(r["offset_ms"], "ext")]
    if r.get("gone_ms") is not None:
        tg = r["onset_ms"] + r["gone_ms"]
        tg = min(T, key=lambda t: abs(t - tg))
        parts += [sep, seq(tg, "gone")]
    row = np.hstack(parts)
    head = np.zeros((16, row.shape[1], 3), np.uint8)
    d = "-" if r["delay_ms"] is None else f"{r['delay_ms'] / 1000:.2f}"
    g = "-" if r.get("gone_ms") is None else f"{r['gone_ms'] / 1000:.2f}"
    txt = (f"{r['session'][:4]} anchor {r['t_ms'] / 1000:.1f}s delay {d}s extractor {r['duration_ms'] / 1000:.2f}s "
           f"gone {g}s {r['ending'] or r['offset_censored']} {r.get('fade_reason') or ''}")
    cv2.putText(head, txt, (3, 12), 0, 0.42, (255, 255, 255), 1)
    return np.vstack([head, row])


def dist(v: list[float]) -> dict:
    if not v:
        return {"n": 0}
    a = np.asarray(v, float)
    return {"n": len(a), "min": round(float(a.min()), 3), "p25": round(float(np.percentile(a, 25)), 3),
            "median": round(float(np.median(a)), 3), "p75": round(float(np.percentile(a, 75)), 3),
            "max": round(float(a.max()), 3)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--limit", type=int, default=0, help="anchors per session (0: all)")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    gate_._idle()
    rows = []
    for sid in SESSIONS:
        s = gate_.Lite(sid)
        deaths = enemy_deaths(sid)
        seen = []  # (x, y, onset, offset) of measured instances
        an = [a for a in anchors(sid) if list(a["roi"] or []) == list(s.box)]
        if args.limit:
            an = an[:args.limit]
        for a in an:
            dup = next((q for q in seen if math.hypot(q[0] - a["x"], q[1] - a["y"]) <= SAME_PX
                        and q[2] - 200 <= a["t_ms"] <= q[3] + 200), None)
            if dup is not None:
                continue
            r = {**a, **measure(s, a, deaths)}
            if r["status"] == "measured":
                seen.append((a["x"], a["y"], r["onset_ms"], r["offset_ms"]))
            rows.append(r)
            print(sid, round(a["t_ms"] / 1000, 1), r["status"], r.get("delay_ms"), r.get("duration_ms"),
                  r.get("ending"), r.get("offset_censored"), flush=True)
    m = [r for r in rows if r["status"] == "measured"]
    delays = [r["delay_ms"] / 1000 for r in m if r["delay_ms"] is not None]
    durs = [r["duration_ms"] / 1000 for r in m if not r["offset_censored"] and r["delay_ms"] is not None]
    summary = {"anchors": sum(len(anchors(s)) for s in SESSIONS), "instances": len(rows),
               "status": dict(Counter(r["status"] for r in rows)),
               "delay_s": dist(delays), "duration_s": dist(durs),
               "ending": dict(Counter(r["ending"] or f"censored:{r['offset_censored']}" for r in m)),
               "no_icon_seen": sum(r["delay_ms"] is None for r in m),
               "death_near_offset": sum(bool(r["enemy_death_near_offset"]) for r in m),
               "icon_to_mark_px": dist([r["icon_to_mark_px"] for r in m if r["icon_to_mark_px"] is not None]),
               "fade_start_s": dist([r["fade_start_ms"] / 1000 for r in m if r.get("fade_start_ms") is not None
                                     and r.get("gone_ms") is not None and r["delay_ms"] is not None]),
               "gone_s": dist([r["gone_ms"] / 1000 for r in m if r.get("gone_ms") is not None
                               and r["delay_ms"] is not None]),
               "returned_after_s": dist([r["duration_ms"] / 1000 for r in m if r["ending"] == "icon_returned"]),
               "fade_reason": dict(Counter(str(r.get("fade_reason")) for r in m if r["ending"] == "vanished"))}
    print(json.dumps(summary, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    strips = [strip_frame(r) for r in m]
    if strips:
        w = max(x.shape[1] for x in strips)
        strips = [np.pad(x, ((0, 4), (0, w - x.shape[1]), (0, 0))) for x in strips]
        for k in range(0, len(strips), 20):
            cv2.imwrite(str(OUT / f"question_marks_{k // 20 + 1}.png"), np.vstack(strips[k:k + 20]))
    (OUT / "question_marks.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if k not in ("_crops", "frames", "_sig")} for r in rows], indent=1),
        encoding="utf-8")
    if args.record:
        from reticle import metrics
        values = {"instances": summary["instances"], "measured": len(m), "no_icon_seen": summary["no_icon_seen"],
                  "death_near_offset": summary["death_near_offset"]}
        values |= {f"delay_{k}": v for k, v in summary["delay_s"].items()}
        values |= {f"duration_{k}": v for k, v in summary["duration_s"].items()}
        values |= {f"fade_start_{k}": v for k, v in summary["fade_start_s"].items()}
        values |= {f"gone_{k}": v for k, v in summary["gone_s"].items()}
        values |= {f"returned_after_{k}": v for k, v in summary["returned_after_s"].items()}
        values |= {f"ending_{k.replace(':', '_')}": v for k, v in summary["ending"].items()}
        values |= {f"status_{k}": v for k, v in summary["status"].items()}
        metrics.record("last_known_marks", part="timing", session="+".join(SESSIONS), values=values,
                       deps={"prototype": VERSION, "teardrop": it_.VERSION, "place_px": PLACE_PX,
                             "icon_px": ICON_PX, "gap_frames": GAP_FRAMES, "window_ms": WINDOW_MS,
                             "anchors": "labels/minimap question marks"},
                       note="enemy '?' mark: delay after the last enemy icon at its place, and duration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
