r"""Show the player what the self icon does when the ring fit refuses.

    .\.venv\Scripts\python.exe prototypes\refusal_clip.py c40d950031bb

Two derivations have now failed to explain the refusal. Appearance matching
recovered only isolated cases, and `minimap_occlusion.py` refuted overlap at
1.06x. The standing candidate is the self key's own screen-space dropout over
the upper rim, measured in `BACKLOG.md` over five sessions -- but that is a
hypothesis about pixels, and the person can see the pixels.

So this asks rather than derives. It renders the seconds around a refusal with
the reader's own reading drawn on top, and it draws **the self colour key
itself**, which is the thing the dropout hypothesis is about. Refusal runs are
sampled across the whole length distribution, not taken in order: the bracketed
measurements could only see isolated refusals, and the mass is elsewhere.

It labels nothing and scores nothing. It changes no reader.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle import geometry  # noqa: E402
from reticle.belief import absent_instants  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.minimap import (ally_icons, floor_mask, minimap_roi_px,  # noqa: E402
                             self_icons, self_mask, slab_mask, widget_drawn,
                             widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

READ = (90, 240, 90)
REFUSED = (70, 70, 245)
INFERRED = (60, 190, 250)
ALLY = (230, 190, 90)
KEY = (255, 120, 255)


def refusal_runs(rows: list[dict], step_ms: float) -> list[dict]:
    """Contiguous stretches the reader refused while the widget was drawn."""
    absent = set(absent_instants(rows))
    runs, cur = [], None
    for r in rows:
        refused = r["self_x"] is None and r["t_ms"] not in absent
        if refused:
            if cur is None:
                cur = {"t0": r["t_ms"], "t1": r["t_ms"], "n": 1}
            elif r["t_ms"] - cur["t1"] <= step_ms * 1.6:
                cur["t1"], cur["n"] = r["t_ms"], cur["n"] + 1
            else:
                runs.append(cur)
                cur = {"t0": r["t_ms"], "t1": r["t_ms"], "n": 1}
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    for run in runs:
        run["ms"] = run["t1"] - run["t0"] + step_ms
    return runs


def representative(runs: list[dict], want: int) -> list[dict]:
    """One run from each length band, so the sample is not all easy cases.

    Every bracket-based measurement so far sampled ISOLATED refusals, because
    those are the only ones with a fit either side. Taking the modal case alone
    would repeat that mistake in a viewer.
    """
    bands = [(0, 100, "single frame"), (100, 400, "short"),
             (400, 1200, "medium"), (1200, 3000, "long"),
             (3000, 1e9, "very long")]
    out = []
    for lo, hi, name in bands:
        pool = [r for r in runs if lo <= r["ms"] < hi]
        if not pool:
            continue
        # The longest of its band, so the band's character is visible.
        pick = max(pool, key=lambda r: r["ms"])
        out.append({**pick, "band": name, "in_band": len(pool)})
    return out[:want] if want < len(out) else out


def panel(crop, mask, fits, allies, expected, run, t_ms, scale, zoom=6):
    """The widget at 2x beside a zoom on the icon, both fully annotated."""
    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    tint = big.copy()
    m2 = cv2.resize(mask.astype(np.uint8), None, fx=2, fy=2,
                    interpolation=cv2.INTER_NEAREST).astype(bool)
    tint[m2] = KEY
    big = cv2.addWeighted(big, 0.45, tint, 0.55, 0)
    for a in allies:
        cv2.circle(big, (int(a["cx"] * 2), int(a["cy"] * 2)),
                   int(a["r"] * 2), ALLY, 1, cv2.LINE_AA)
    for f in fits:
        cv2.circle(big, (int(f["cx"] * 2), int(f["cy"] * 2)),
                   int(f["r"] * 2), READ, 2, cv2.LINE_AA)
    if expected is not None:
        cv2.drawMarker(big, (int(expected[0] * 2), int(expected[1] * 2)),
                       INFERRED, cv2.MARKER_TILTED_CROSS, 18, 1)

    centre = expected if expected is not None else (
        (fits[0]["cx"], fits[0]["cy"]) if fits else None)
    half = 26
    if centre is None:
        z = np.full((2 * half * zoom, 2 * half * zoom, 3), 24, np.uint8)
    else:
        cx, cy = int(round(centre[0])), int(round(centre[1]))
        x0, y0 = max(0, cx - half), max(0, cy - half)
        x1, y1 = min(crop.shape[1], cx + half), min(crop.shape[0], cy + half)
        patch = crop[y0:y1, x0:x1].copy()
        pm = mask[y0:y1, x0:x1]
        patch[pm] = KEY
        z = cv2.resize(patch, (patch.shape[1] * zoom, patch.shape[0] * zoom),
                       interpolation=cv2.INTER_NEAREST)
        for f in fits:
            cv2.circle(z, (int((f["cx"] - x0) * zoom), int((f["cy"] - y0) * zoom)),
                       int(f["r"] * zoom), READ, 2, cv2.LINE_AA)
        if expected is not None:
            cv2.drawMarker(z, (int((expected[0] - x0) * zoom),
                               int((expected[1] - y0) * zoom)), INFERRED,
                           cv2.MARKER_TILTED_CROSS, 22, 2)
        z = cv2.copyMakeBorder(z, 0, max(0, 2 * half * zoom - z.shape[0]),
                               0, max(0, 2 * half * zoom - z.shape[1]),
                               cv2.BORDER_CONSTANT, value=(24, 24, 24))

    h = max(big.shape[0], z.shape[0])
    left = cv2.copyMakeBorder(big, 0, h - big.shape[0], 0, 0,
                              cv2.BORDER_CONSTANT, value=(24, 24, 24))
    right = cv2.copyMakeBorder(z, 0, h - z.shape[0], 8, 8,
                               cv2.BORDER_CONSTANT, value=(24, 24, 24))
    body = np.hstack([left, right])
    bar = np.full((78, body.shape[1], 3), 20, np.uint8)

    def put(text, row, colour=(225, 225, 225)):
        cv2.putText(bar, text, (10, 20 + row * 19), cv2.FONT_HERSHEY_SIMPLEX,
                    0.46, colour, 1, cv2.LINE_AA)

    inside = run["t0"] <= t_ms <= run["t1"]
    if fits:
        f = fits[0]
        put(f"READ   cov {f['cov']:.2f}  r {f['r']}  "
            f"facing {('%.0f deg' % f['facing']) if f['facing'] is not None else 'none'}"
            f"  lobe {f['lobe']:.2f}", 0, READ)
    else:
        put("REFUSED   no fit passed the shape gate", 0, REFUSED)
    put(f"t {t_ms/1000:8.2f}s   {'INSIDE the refusal run' if inside else 'outside'}"
        f"   run {run['ms']:.0f} ms, {run['n']} instants, band {run['band']}", 1,
        REFUSED if inside else (170, 170, 170))
    put(f"key px near icon {int(np.count_nonzero(mask))}   allies {len(allies)}"
        f"   magenta = self colour key   cyan cross = INFERRED, not observed", 2,
        (170, 170, 170))
    return np.vstack([bar, body])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--before-s", type=float, default=3.0)
    ap.add_argument("--after-s", type=float, default=5.0)
    ap.add_argument("--fps", type=float, default=15.0, help="output frame rate")
    ap.add_argument("--want", type=int, default=5)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    store = Store(args.store)
    manifest = json.loads((Path(args.store) / "manifests" /
                           f"{args.session}.json").read_text(encoding="utf-8"))
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    box = minimap_roi_px(profile, int(src["width"]), int(src["height"]))
    med = geometry.reference_static(args.session, store.root)
    sd = geometry.stability(args.session, store.root, med.shape[:2])
    floor, slab = floor_mask(med, sd=sd), slab_mask(med, sd=sd)
    sgray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)

    date = next(p.parent.parent.name.split("=")[1]
                for p in Path(args.store).glob("l1/minimap/**/*.parquet")
                if args.session in str(p))
    rows = sorted(store.read_minimap(args.session, date).to_pylist(),
                  key=lambda r: r["t_ms"])
    step = float(np.median(np.diff([r["t_ms"] for r in rows])))
    runs = refusal_runs(rows, step)
    picks = representative(runs, args.want)
    print(f"{len(runs)} refusal runs; showing {len(picks)}")

    out_dir = Path(args.out_dir) if args.out_dir else \
        Path(args.store) / "notes" / "refusal-clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = box
    written = []
    for k, run in enumerate(picks, 1):
        t0 = max(0.0, run["t0"] - args.before_s * 1000.0)
        # A run longer than the tail still has to show its end.
        t1 = max(run["t0"] + args.after_s * 1000.0, run["t1"] + 2000.0)
        spans = [(t0, t1)]
        frames = []
        for _who, smp in sample_windows(src["path"], float(src["fps"]),
                                        {"c": (float(src["fps"]) * 4.0, spans)}):
            crop = smp.frame[y0:y1, x0:x1]
            drawn = widget_drawn(crop, sgray, floor)
            fits = (sorted(self_icons(crop, floor, require_facing=False,
                                      support=slab),
                           key=lambda d: -d["cov"]) if drawn else [])
            allies = ally_icons(crop, floor, require_facing=False,
                                support=slab) if drawn else []
            frames.append({"t_ms": smp.t_ms, "crop": crop.copy(),
                           "mask": self_mask(crop), "fits": fits,
                           "allies": allies, "drawn": drawn})
        if not frames:
            continue
        # Expected position while refused: straight interpolation between the
        # reads either side, or the last read held. Drawn as INFERRED.
        seen = [(f["t_ms"], f["fits"][0]["cx"], f["fits"][0]["cy"])
                for f in frames if f["fits"]]
        for f in frames:
            f["expected"] = None
            if f["fits"]:
                continue
            before = [s for s in seen if s[0] <= f["t_ms"]]
            after = [s for s in seen if s[0] >= f["t_ms"]]
            if before and after:
                a, b = before[-1], after[0]
                q = 0.0 if b[0] == a[0] else (f["t_ms"] - a[0]) / (b[0] - a[0])
                f["expected"] = (a[1] + q * (b[1] - a[1]), a[2] + q * (b[2] - a[2]))
            elif before:
                f["expected"] = (before[-1][1], before[-1][2])
        scale = widget_scale(frames[0]["crop"].shape[1])
        first = panel(frames[0]["crop"], frames[0]["mask"], frames[0]["fits"],
                      frames[0]["allies"], frames[0]["expected"], run,
                      frames[0]["t_ms"], scale)
        h, w = first.shape[:2]
        name = f"{k:02d}-{run['band'].replace(' ', '-')}-{run['ms']:.0f}ms.mp4"
        target = out_dir / name
        writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"),
                                 args.fps, (w, h))
        for f in frames:
            writer.write(panel(f["crop"], f["mask"], f["fits"], f["allies"],
                               f["expected"], run, f["t_ms"], scale))
        writer.release()
        written.append(target)
        print(f"  {name}  onset {run['t0']/1000:.2f}s  {run['n']} refused "
              f"instants  {len(frames)} frames  ({run['in_band']} runs in band)")
    for t in written:
        print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
