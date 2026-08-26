"""Sweep the ring-fit finder's cut points against the minimap labels.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_ring_sweep.py <session>

Decoding is the expensive part and the labels grow while Grant works, so every
frame's ring fits are cached to `<store>/labels/minimap/<session>.fits.json`
keyed by timestamp. Re-running after another labelling batch only decodes the
new frames, which makes sweeping free -- the same reason `segment` recomputes
spans from stored L1 rather than reopening the capture.

The cache holds the RAW fits, before any threshold, so cut points can move
without re-decoding. It is invalidated by the fitter's geometry, not by its
thresholds: bump `FIT_VERSION` when R_MIN/R_MAX/SEARCH/N_THETA change, and never
for COV_MIN or INNER_RED_MAX.

Pools are reported separately and the pre-kill WINDOW is reported separately
within them. The first labelling batch sampled 300-1400 ms before the killfeed
entry and mostly caught the approach rather than the duel -- most of those frames
hold no enemy yet, which is what produced a "58%, so not a proof gate" reading
that was entirely an artefact of the window. Pooling the two batches would bury
that difference again.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import minimap_ring_fit as rf                                     # noqa: E402
from minimap_icons import floor_mask, static_map                  # noqa: E402
from minimap_icon_eval import hits                                # noqa: E402

STORE = Path.home() / "reticle-store"
FIT_VERSION = f"r{rf.R_MIN}-{rf.R_MAX}_s{rf.SEARCH}_t{rf.N_THETA}"


def load_labels(sid):
    rows = {}
    for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["t_ms"]] = r
    return [r for r in rows.values() if not r.get("uncertain")]


def batch_of(r):
    """Which sampling window this row came from."""
    if r["pool"] != "prekill":
        return "uniform"
    w = r.get("window")
    return f"prekill {w[0]}-{w[1]}ms" if w else "prekill 300-1400ms (old)"


def fits_for(sid, rows, sat):
    cache_path = STORE / "labels" / "minimap" / f"{sid}.fits.json"
    cache = {}
    if cache_path.is_file():
        blob = json.loads(cache_path.read_text())
        if blob.get("version") == FIT_VERSION and blob.get("sat") == sat:
            cache = blob["fits"]
    need = [r for r in rows if str(r["t_ms"]) not in cache]
    if need:
        man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
        src = man["source"]
        fps = float(src["fps"])
        x0, y0, x1, y1 = rows[0]["roi"]
        cap = cv2.VideoCapture(str(src["path"]))
        tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        med = []
        for i in np.linspace(0, tot - 1, 150).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, fr = cap.read()
            if ok:
                med.append(fr[y0:y1, x0:x1])
        floor = floor_mask(static_map(med))
        print(f"decoding {len(need)} new frames ({len(cache)} cached)")
        for n, r in enumerate(need):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * fps)))
            ok, fr = cap.read()
            if not ok:
                continue
            cache[str(r["t_ms"])] = rf.find(fr[y0:y1, x0:x1], floor, sat)
            if (n + 1) % 40 == 0:
                print(f"  ... {n+1}/{len(need)}", flush=True)
        cap.release()
        cache_path.write_text(json.dumps(
            {"version": FIT_VERSION, "sat": sat, "fits": cache}))
    return cache


def score(rows, cache, cov_min, ired_max):
    out = {}
    for r in rows:
        fs = cache.get(str(r["t_ms"]))
        if fs is None:
            continue
        cs = [{"box": (f["cx"] - f["r"], f["cy"] - f["r"], 2 * f["r"], 2 * f["r"]),
               "xy": (f["cx"], f["cy"])}
              for f in fs if f["cov"] >= cov_min and f["inner_red"] <= ired_max]
        b = out.setdefault(batch_of(r), dict(tp=0, fn=0, fp=0, on_q=0, n_q=0, frames=0))
        b["frames"] += 1
        used = set()
        for m in [m for m in r["marks"] if m["kind"] == "enemy"]:
            j = next((j for j, c in enumerate(cs)
                      if j not in used and hits(m["x"], m["y"], c)), None)
            if j is None:
                b["fn"] += 1
            else:
                b["tp"] += 1
                used.add(j)
        for m in [m for m in r["marks"] if m["kind"] == "question"]:
            b["n_q"] += 1
            j = next((j for j, c in enumerate(cs)
                      if j not in used and hits(m["x"], m["y"], c)), None)
            if j is not None:
                used.add(j)
                b["on_q"] += 1
        for m in [m for m in r["marks"] if m["kind"] == "other_red"]:
            j = next((j for j, c in enumerate(cs)
                      if j not in used and hits(m["x"], m["y"], c)), None)
            if j is not None:
                used.add(j)
        b["fp"] += len(cs) - len(used)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--sat", type=int, default=100)
    args = ap.parse_args()

    rows = load_labels(args.session)
    cache = fits_for(args.session, rows, args.sat)
    from collections import Counter
    print(f"\n{len(rows)} labelled frames: "
          f"{dict(Counter(batch_of(r) for r in rows))}")

    for ired in (0.25, 0.35, 0.50):
        print(f"\ninner_red <= {ired}")
        for cov in (0.15, 0.20, 0.25, 0.30, 0.35, 0.42, 0.50, 0.60):
            st = score(rows, cache, cov, ired)
            parts = []
            for name in sorted(st):
                s = st[name]
                if not (s["tp"] + s["fn"]):
                    continue
                rec = s["tp"] / max(s["tp"] + s["fn"], 1)
                pre = s["tp"] / max(s["tp"] + s["fp"], 1)
                parts.append(f"{name}: R {rec*100:5.1f}% P {pre*100:5.1f}% "
                             f"(TP{s['tp']:3d} FN{s['fn']:3d} FP{s['fp']:3d})")
            print(f"  cov>={cov:.2f}  " + "   ".join(parts))
    # Question marks: does the finder confuse them for enemies? Reported at the
    # chosen operating point only, since it is a yes/no property not a curve.
    st = score(rows, cache, rf.COV_MIN, rf.INNER_RED_MAX)
    tot_q = sum(s["n_q"] for s in st.values())
    on_q = sum(s["on_q"] for s in st.values())
    print(f"\nat the shipped cut (cov>={rf.COV_MIN}, inner_red<={rf.INNER_RED_MAX}): "
          f"fired on {on_q}/{tot_q} question marks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
