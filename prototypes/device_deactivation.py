r"""Does a deployed device dim because its owner died?

    .\.venv\Scripts\python.exe prototypes\device_deactivation.py [--session S]

the player, mid-labelling on 2026-09-09: a sonic sensor is *much dimmer* because the
ally Deadlock who placed it died, and *the only deployed abilities that don't
deactivate on death are walls and barriers*. Killjoy's devices also deactivate
when she leaves their activation radius, which is a SECOND cause and a
reversible one.

That is a cross-channel prediction, and both channels are already stored, so it
needs no detector work:

    the killfeed says when an ally died      reticle.ability_phases.ally_deaths
    the widget says when a device is dim     patch contrast at a labelled device

CLAUDE.md's rule is to cross-reference before tuning, and to STORE THE
DISAGREEMENTS rather than report agreement as accuracy. So this measures the
association and keeps every case that does not fit, because those are the
interesting ones: a dim device with no death before it is a different
deactivation cause, and a death with no dimming is a wall, a barrier, or a
device that was not the dead player's.

What this is NOT
----------------
It does not identify WHICH ally died. The roster bar packs survivors toward the
scoreline, so a slot index is not an identity, and no per-agent death time is
stored for these sessions. So the test is deliberately weaker than the claim:
if dimming follows owner death, dim devices should sit shortly AFTER an ally
death far more often than live ones do. A positive result corroborates the rule
without proving it, and that asymmetry is stated rather than hidden.

The null is the same statistic computed at random times in the same session,
which is what says whether "shortly after a death" means anything at all in a
match where allies die every thirty seconds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry as _G                                   # noqa: E402
# Imported under a private alias, never redefined here: `doctor` matches names
# ACROSS the two trees, and a re-export shim still counts as a fork.
from reticle.ability_phases import ally_deaths as _ally_deaths       # noqa: E402
from reticle.profiles import get_profile                             # noqa: E402
from reticle.store import DEFAULT_STORE                              # noqa: E402

STORE = Path(DEFAULT_STORE)
PATCH_R = 4
#: The gap that separated the two appearance modes on 2026-09-09: 24 labelled
#: sensors at contrast 122-175 against 47 at 231-241, with nothing between.
DIM_CONTRAST_MAX = 203.0
#: Walls and barriers persist through their owner's death, so they are excluded
#: from the prediction rather than counted as failures of it.
PERSISTS_THROUGH_DEATH = ("barrier mesh", "toxic screen", "cyber cage",
                          "blade storm", "wall", "barrier")


def named_labels(session: str) -> list[dict]:
    path = STORE / "labels" / "ability" / f"{session}.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("agent") and row.get("ability") and not row.get("not_ability"):
            row["ability_id"] = f"{row['agent'].casefold()}:{row['ability'].casefold()}"
            out.append(row)
    return out


def measure_contrast(session: str, rows: list[dict]) -> list[dict]:
    """Patch contrast at each label, in the ROI crop the readers index."""
    man = json.loads((STORE / "manifests" / f"{session}.json").read_text(encoding="utf-8"))
    src = man["source"]
    prof = get_profile(man["source_profile"])
    x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(
        int(src["width"]), int(src["height"]))
    cap = cv2.VideoCapture(src["path"])
    fps = float(src["fps"])
    out = []
    for row in rows:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(row["t_ms"] / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            continue
        grey = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        x, y = int(row["x"]), int(row["y"])
        patch = grey[max(0, y - PATCH_R):y + PATCH_R + 1,
                     max(0, x - PATCH_R):x + PATCH_R + 1]
        if patch.size == 0:
            continue
        out.append({**row, "contrast": float(patch.max() - patch.min())})
    cap.release()
    return out


def since_previous(t: float, events: list[float]) -> float | None:
    prior = [e for e in events if e <= t]
    return None if not prior else t - prior[-1]


def report(session: str, rng: np.random.Generator) -> dict:
    deaths = _ally_deaths(STORE, session)
    labels = measure_contrast(session, named_labels(session))
    devices = [r for r in labels
               if not any(w in r["ability_id"] for w in PERSISTS_THROUGH_DEATH)]
    for row in devices:
        row["dim"] = row["contrast"] <= DIM_CONTRAST_MAX
        row["since_death_ms"] = since_previous(row["t_ms"], deaths)

    dim = [r for r in devices if r["dim"]]
    live = [r for r in devices if not r["dim"]]
    # The null: the same statistic at times drawn uniformly over the session,
    # which says whether "shortly after a death" is informative at all when
    # allies die every half-minute.
    span = max((r["t_ms"] for r in devices), default=0.0)
    null = [since_previous(float(t), deaths)
            for t in rng.uniform(0.0, span or 1.0, 400)]
    null = [v for v in null if v is not None]

    def med(rows, key="since_death_ms"):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return float(np.median(vals)) if vals else float("nan")

    return {
        "session": session,
        "ally_death_events": len(deaths),
        "devices": len(devices), "dim": len(dim), "live": len(live),
        "median_since_death_ms": {
            "dim": med(dim), "live": med(live),
            "null_random_times": float(np.median(null)) if null else float("nan"),
        },
        "within_10s_of_a_death": {
            "dim": sum(1 for r in dim if (r["since_death_ms"] or 1e9) <= 10000),
            "live": sum(1 for r in live if (r["since_death_ms"] or 1e9) <= 10000),
            "null": sum(1 for v in null if v <= 10000) / max(1, len(null)),
        },
        "disagreements": {
            "dim_with_no_prior_death": [
                {"t_ms": r["t_ms"], "ability": r["ability_id"]}
                for r in dim if r["since_death_ms"] is None],
            "dim_long_after_any_death": [
                {"t_ms": r["t_ms"], "ability": r["ability_id"],
                 "since_death_ms": r["since_death_ms"]}
                for r in dim if (r["since_death_ms"] or 0) > 60000],
        },
        "excluded_persisting": sorted({r["ability_id"] for r in labels
                                       if r not in devices}),
        "permutation": permutation_gap(devices, rng),
        "_devices": devices,
    }


def permutation_gap(devices: list[dict], rng, n: int = 2000) -> dict:
    """Is the dim/live gap in time-since-death more than a coincidence?

    Shuffling which devices are called dim keeps the session, the death times
    and both group sizes, so what survives is only the association being tested.
    """
    vals = np.array([r["since_death_ms"] for r in devices
                     if r.get("since_death_ms") is not None], float)
    flags = np.array([r["dim"] for r in devices
                      if r.get("since_death_ms") is not None], bool)
    if flags.sum() < 2 or (~flags).sum() < 2:
        return {"observed_gap_ms": None, "p_value": None, "n": int(flags.size)}
    observed = float(np.median(vals[~flags]) - np.median(vals[flags]))
    count = 0
    for _ in range(n):
        shuffled = rng.permutation(flags)
        gap = float(np.median(vals[~shuffled]) - np.median(vals[shuffled]))
        count += gap >= observed
    return {"observed_gap_ms": round(observed, 1),
            "p_value": round((count + 1) / (n + 1), 4),
            "n": int(flags.size), "n_dim": int(flags.sum())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", action="append",
                        help="repeat for several; default is the two real matches")
    parser.add_argument("--seed", type=int, default=20260909)
    args = parser.parse_args(argv)
    sessions = args.session or ["a06f04a0059f", "5822b6646448"]
    rng = np.random.default_rng(args.seed)
    pooled = []
    for session in sessions:
        out = report(session, rng)
        pooled += out.pop("_devices")
        print(json.dumps(out, indent=1, sort_keys=True))
    if len(sessions) > 1:
        print()
        print("POOLED across sessions:")
        print(json.dumps(permutation_gap(pooled, rng), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
