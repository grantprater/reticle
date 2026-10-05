r"""Sizing probe for the slot-state design (docs/ENTITY_STATE.md).

    .\.venv\Scripts\python.exe prototypes\entity_state_probe.py reach [--record]
    .\.venv\Scripts\python.exe prototypes\entity_state_probe.py cost [--record]

Not wired (`"wire": "no"` in the store's `notes/predictions.jsonl`, task
entity-state-20261004): it sizes two choices of the design and decides
nothing. It reads no capture, no stored stream and no truth.

`reach`
-------
A slot nobody has seen for `dt` seconds may be anywhere its last fix can
reach along walkable floor. The design stores that region as an anchor cell
and a path radius, read against the all-pairs path-distance table that
`prototypes/sightlines.py` (branch engagement-reach-20261004) bakes per map
from baked geometry. A Euclidean disc of the same radius is the old bound
(`belief.Fix.radius_px`, "a generous one, because it is a disk"). For each
baked map this samples `N_CELLS` walkable cells with a fixed seed and
reports, per radius, the median over cells of

    (cells within path distance R) / (walkable cells within Euclidean R)

and the median path-region size in cells (1 m squares, so square metres),
also as a share of the full disc pi R^2 that a pixel radius draws over
walls and void alike (`disc_share`).
A path distance is never shorter than the straight line, so the ratio lies
in (0, 1]; lower is sharper.

`cost`
------
One vectorised slot-state update for ten slots, on synthetic arrays over
one real map's tables: the reach membership of each unseen slot (one row
compare of the path table), a negative-evidence cut (a boolean mask), a
prior-weighted assignment of up to eight fits to five slots
(`scipy.optimize.linear_sum_assignment`), and the struct-of-arrays write.
It reports the median and 95th percentile wall time per update.

Compute: single-threaded, Below Normal priority, in-memory tables only.
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import hashlib
import os
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROBE_VERSION = "entity-state-probe-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
SIGHTLINES = STORE / "sightlines"
#: The sightline table's own constants (`prototypes/sightlines.py`).
UNREACHABLE = 65535
SIGHTLINES_VERSION = "sightlines-0.1.0"
#: Cells sampled per map, and the seed.
N_CELLS = 500
SEED = 0
#: Radii in metres: about one second of running, and two.
RADII_M = (2.0, 5.0, 10.0)
#: Updates timed by `cost`, and the warm-up discarded first.
N_UPDATES = 3000
WARMUP = 200


def _below_normal() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass


def _tables():
    """Each baked sightline table's path, sorted."""
    return sorted(glob.glob(str(SIGHTLINES / "*.npz")))


def _metres(cell_xy: np.ndarray) -> np.ndarray:
    """Cell centres in metres. The table stores Riot world units, which
    `prototypes/sightlines.py` reads as centimetres (`UNITS_PER_M`); the
    nearest-neighbour spacing of a 1 m grid confirms the unit here."""
    step = np.median(np.abs(np.diff(np.unique(np.round(cell_xy[:, 0], 3)))))
    return cell_xy / (100.0 if step > 10.0 else 1.0)


def reach(record: bool = False) -> dict:
    rng = np.random.default_rng(SEED)
    out, digests = {}, {}
    for path in _tables():
        key = Path(path).stem
        z = np.load(path)
        version = str(z["version"])
        if version != SIGHTLINES_VERSION:
            print(f"{key}: skipped, version {version}")
            continue
        xy = _metres(z["cell_xy"].astype(np.float64))
        dist = z["dist_dm"]
        n = len(xy)
        pick = rng.choice(n, size=min(N_CELLS, n), replace=False)
        row = {}
        for r in RADII_M:
            within_path = (dist[pick] <= int(round(r * 10))).sum(1)
            d2 = ((xy[pick, None, :] - xy[None, :, :]) ** 2).sum(-1)
            within_eucl = (d2 <= r * r).sum(1)
            ratio = within_path / within_eucl
            tag = f"{int(r)}m"
            row[f"ratio_{tag}"] = round(float(np.median(ratio)), 4)
            row[f"cells_{tag}"] = float(np.median(within_path))
            row[f"eucl_cells_{tag}"] = float(np.median(within_eucl))
            # against the full disc a pixel radius draws, void and walls included
            row[f"disc_share_{tag}"] = round(float(np.median(within_path)) / (np.pi * r * r), 4)
        row["cells"] = int(n)
        out[key] = row
        with open(path, "rb") as fh:
            digests[key] = hashlib.sha256(fh.read()).hexdigest()[:12]
        print(key, row)
    ratios5 = [v["ratio_5m"] for v in out.values()]
    drop = sum(v["ratio_10m"] < v["ratio_5m"] for v in out.values())
    summary = {"maps": len(out), "ratio_5m_min": min(ratios5), "ratio_5m_max": max(ratios5),
               "maps_ratio_drops_5_to_10": int(drop)}
    print(summary)
    if record:
        from reticle import metrics
        values = dict(summary)
        for key, row in out.items():
            m = key.split("__")[0]
            for k, v in row.items():
                values[f"{m}.{k}"] = v
        metrics.record("entity_state_probe", part="reach_ratio", values=values,
                       deps={"probe": PROBE_VERSION, "sightlines": SIGHTLINES_VERSION,
                             "tables": digests, "n_cells": N_CELLS, "seed": SEED,
                             "radii_m": list(RADII_M)},
                       note="path-distance reach region against a Euclidean disc, per baked map")
    return summary


def cost(record: bool = False) -> dict:
    path = _tables()[0]
    z = np.load(path)
    dist = z["dist_dm"]
    n = dist.shape[0]
    rng = np.random.default_rng(SEED)
    n_slots, n_fits = 10, 8
    # Struct of arrays: one row per slot.
    mean = np.zeros((n_slots, 2), np.float32)
    sigma = np.ones(n_slots, np.float32)
    anchor = rng.integers(0, n, n_slots).astype(np.int32)
    radius_dm = rng.integers(10, 100, n_slots).astype(np.uint16)
    alive = np.ones(n_slots, bool)
    seen = np.zeros(n_slots, bool)
    seen[:5] = True                       # five fitted, five unseen
    cell_xy = _metres(z["cell_xy"].astype(np.float64)).astype(np.float32)
    times = []
    for i in range(N_UPDATES + WARMUP):
        fits = cell_xy[rng.integers(0, n, n_fits)]
        visible = rng.random(n) < 0.3      # cells where an icon would show
        t0 = time.perf_counter()
        unseen = np.flatnonzero(alive & ~seen)
        region = dist[anchor[unseen]] <= radius_dm[unseen, None]
        region &= ~visible[None, :]        # negative evidence: drawn nowhere there
        size = region.sum(1)
        cand = np.flatnonzero(alive)[:5]
        d2 = ((fits[:, None, :] - mean[None, cand, :]) ** 2).sum(-1)
        cost_m = d2 / (2.0 * sigma[cand] ** 2)
        r, c = linear_sum_assignment(cost_m)
        mean[cand[c]] = fits[r]
        sigma[cand[c]] = 0.5
        radius_dm[unseen] = np.minimum(radius_dm[unseen] + 4, UNREACHABLE - 1)
        _ = size
        dt = time.perf_counter() - t0
        if i >= WARMUP:
            times.append(dt)
    us = np.asarray(times) * 1e6
    summary = {"median_us": round(float(np.median(us)), 1),
               "p95_us": round(float(np.percentile(us, 95)), 1),
               "updates": int(N_UPDATES), "cells": int(n)}
    print(Path(path).stem, summary)
    if record:
        from reticle import metrics
        metrics.record("entity_state_probe", part="update_cost", values=summary,
                       deps={"probe": PROBE_VERSION, "sightlines": SIGHTLINES_VERSION,
                             "table": Path(path).stem, "slots": n_slots, "fits": n_fits,
                             "threads": 1, "priority": "below_normal"},
                       note="one synthetic ten-slot update over one map's path table")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("reach", "cost"))
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    _below_normal()
    (reach if a.command == "reach" else cost)(a.record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
