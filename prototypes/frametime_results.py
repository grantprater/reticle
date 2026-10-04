r"""Turn the frame-time session's PresentMon CSVs into the decision table.

    .\.venv\Scripts\python.exe prototypes\frametime_results.py DIR [--json OUT.json]

Why this exists, 2026-10-04
---------------------------
docs/FRAMETIME_PROTOCOL.md has the player record VALORANT's frame times with
PresentMon under five arms, each twice, in a fixed order. This script reads
the files that session leaves, `NN_ARM.csv` (PresentMon) and `NN_ARM.load.json`
(`prototypes/live_load.py --out`), and applies the rule the protocol fixed
before the session:

* Per file: the game's frames only (`Application` is VALORANT's process;
  where several swap chains present, the one with the most frames).
  Frame time is `MsBetweenPresents` (PresentMon 1.x, or 2.x with
  `--v1_metrics`) or `FrameTime` (PresentMon 2.x); the column used is printed.
* Per arm, frames pooled over its repeats: median FPS (1000 over the median
  frame time), 1% low FPS (1000 over the 99th-percentile frame time), p99
  frame time, and the spread of the repeats' median FPS.
* Cost of an arm = 1 - its FPS over the reference arm's, for median FPS and
  1% low FPS. The reference is `base` (the game alone); costs against `obs`
  are printed beside.
* An arm PASSES when both costs are at most `BUDGET` (0.20) and, where its
  load log exists, the harness kept pace (`pace` >= `PACE_MIN`). The
  chosen level is the highest reticle level that passes.
* NOISE: the spread of the `base` repeats. A cost below it is within noise;
  a spread above `DRIFT_MAX` makes the whole session undecided.

Reads only the files named; writes only `--json`. No per-row Python: the CSVs
are read by pyarrow and reduced with numpy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

FRAMETIME_RESULTS_VERSION = "frametime-results-0.1.0"
GAME = "VALORANT-Win64-Shipping.exe"
ARMS = ("base", "obs", "light", "medium", "full")
LEVELS = ("light", "medium", "full")
#: The player's budget: about a fifth of his frame rate (2026-10-04).
BUDGET = 0.20
#: The base repeats' median FPS may differ by at most this share.
DRIFT_MAX = 0.05
#: A load log whose harness ran slower than this did not apply its level's load.
PACE_MIN = 0.98
FT_COLUMNS = ("MsBetweenPresents", "FrameTime", "msBetweenPresents")
NAME = re.compile(r"^(\d+)_([a-z]+)\.csv$")


def frame_times(path: Path, game: str = GAME) -> tuple[np.ndarray, str, dict]:
    """The game's frame times (ms) in one PresentMon CSV, the column read, and
    what was dropped."""
    import pyarrow.compute as pc
    from pyarrow import csv

    t = csv.read_csv(path, convert_options=csv.ConvertOptions(strings_can_be_null=True))
    col = next((c for c in FT_COLUMNS if c in t.column_names), None)
    if col is None:
        raise SystemExit(f"{path.name}: no frame-time column (looked for "
                         f"{', '.join(FT_COLUMNS)}); columns are {t.column_names[:12]}")
    note = {"rows": t.num_rows}
    if "Application" in t.column_names:
        keep = pc.equal(pc.utf8_lower(t["Application"]), game.lower())
        t = t.filter(keep)
        note["other_apps"] = note["rows"] - t.num_rows
    if "SwapChainAddress" in t.column_names and t.num_rows:
        chains = pc.value_counts(t["SwapChainAddress"])
        best = max(chains.to_pylist(), key=lambda d: d["counts"])["values"]
        n = t.num_rows
        t = t.filter(pc.equal(t["SwapChainAddress"], best))
        note["other_swapchains"] = n - t.num_rows
    ft = np.asarray(pc.cast(t[col], "float64").to_numpy(zero_copy_only=False), float)
    ok = np.isfinite(ft) & (ft > 0)
    note["invalid"] = int((~ok).sum())
    return ft[ok], col, note


def summary(ft: np.ndarray) -> dict:
    """Median FPS, 1% low FPS and p99 frame time of a set of frame times."""
    if not len(ft):
        return {"frames": 0, "seconds": 0.0, "fps_median": None, "fps_low1": None,
                "p99_ms": None, "fps_mean": None}
    med, p99 = np.percentile(ft, [50, 99])
    secs = float(ft.sum()) / 1000.0
    return {"frames": int(len(ft)), "seconds": round(secs, 1),
            "fps_median": round(1000.0 / med, 2), "fps_low1": round(1000.0 / p99, 2),
            "p99_ms": round(float(p99), 3), "fps_mean": round(len(ft) / secs, 2)}


def cost(arm: dict, ref: dict, key: str) -> float | None:
    if arm.get(key) is None or not ref.get(key):
        return None
    return round(1.0 - arm[key] / ref[key], 4)


def decide(arms: dict) -> dict:
    """The decision table from per-arm pooled summaries (`arms[name]` holds
    `pooled`, `repeats` and `pace`)."""
    out = {"budget": BUDGET, "drift_max": DRIFT_MAX, "pace_min": PACE_MIN, "rows": {},
           "chosen": None, "verdict": None}
    base = arms.get("base")
    if base is None or base["pooled"]["frames"] == 0:
        out["verdict"] = "undecided: no base arm"
        return out
    reps = [r["fps_median"] for r in base["repeats"] if r["fps_median"]]
    drift = (max(reps) - min(reps)) / float(np.mean(reps)) if len(reps) > 1 else None
    out["base_drift"] = None if drift is None else round(drift, 4)
    for name in ARMS:
        a = arms.get(name)
        if a is None or name == "base":
            continue
        p = a["pooled"]
        row = {"cost_median": cost(p, base["pooled"], "fps_median"),
               "cost_low1": cost(p, base["pooled"], "fps_low1"),
               "cost_median_vs_obs": (cost(p, arms["obs"]["pooled"], "fps_median")
                                      if "obs" in arms and name != "obs" else None),
               "cost_low1_vs_obs": (cost(p, arms["obs"]["pooled"], "fps_low1")
                                    if "obs" in arms and name != "obs" else None),
               "pace": a.get("pace")}
        within = drift is not None and all(
            c is not None and abs(c) <= drift for c in (row["cost_median"], row["cost_low1"]))
        row["within_noise"] = within
        if name in LEVELS:
            fits = all(c is not None and c <= BUDGET
                       for c in (row["cost_median"], row["cost_low1"]))
            paced = a.get("pace") is None or a["pace"] >= PACE_MIN
            row["passes"] = bool(fits and paced)
            row["why"] = (None if row["passes"] else
                          "over budget" if not fits else
                          f"harness fell behind (pace {a['pace']})")
            if row["passes"]:
                out["chosen"] = name
        out["rows"][name] = row
    if drift is None:
        out["verdict"] = "undecided: base has fewer than two repeats"
    elif drift > DRIFT_MAX:
        out["verdict"] = f"undecided: base repeats drift {drift:.1%} > {DRIFT_MAX:.0%}"
    else:
        out["verdict"] = (f"highest level within budget: {out['chosen']}" if out["chosen"]
                          else "no reticle level fits the budget")
    return out


def collect_arms(d: Path, game: str = GAME) -> dict:
    files = sorted(p for p in d.iterdir() if NAME.match(p.name))
    if not files:
        raise SystemExit(f"{d}: no NN_ARM.csv files")
    arms: dict[str, dict] = {}
    for p in files:
        _, arm = NAME.match(p.name).groups()
        if arm not in ARMS:
            raise SystemExit(f"{p.name}: arm {arm!r} is not one of {', '.join(ARMS)}")
        ft, col, note = frame_times(p, game)
        a = arms.setdefault(arm, {"files": [], "repeats": [], "ft": [], "paces": []})
        a["files"].append({"file": p.name, "column": col, **note})
        a["repeats"].append(summary(ft))
        a["ft"].append(ft)
        load = p.with_name(p.stem + ".load.json")
        if load.is_file():
            a["paces"].append(json.loads(load.read_text(encoding="utf-8")).get("pace"))
    for a in arms.values():
        a["pooled"] = summary(np.concatenate(a.pop("ft")))
        paces = [x for x in a.pop("paces") if x is not None]
        a["pace"] = min(paces) if paces else None
    return arms


def table(arms: dict, dec: dict) -> str:
    lines = [f"{'arm':8} {'frames':>7} {'medFPS':>7} {'1%low':>7} {'p99ms':>7} "
             f"{'cost_med':>9} {'cost_low':>9} {'vs_obs':>7} {'pace':>5}  verdict"]
    for name in ARMS:
        a = arms.get(name)
        if a is None:
            continue
        p, r = a["pooled"], dec["rows"].get(name, {})
        f = lambda v, w=7, k="{:.2f}": (k.format(v) if v is not None else "-").rjust(w)
        verdict = ("reference" if name == "base" else
                   ("PASS" if r.get("passes") else f"fail: {r.get('why')}") if name in LEVELS
                   else "")
        if r.get("within_noise"):
            verdict += " (within noise)"
        lines.append(f"{name:8} {p['frames']:>7} {f(p['fps_median'])} {f(p['fps_low1'])} "
                     f"{f(p['p99_ms'])} {f(r.get('cost_median'), 9, '{:.1%}')} "
                     f"{f(r.get('cost_low1'), 9, '{:.1%}')} "
                     f"{f(r.get('cost_median_vs_obs'), 7, '{:.1%}')} "
                     f"{f(a.get('pace'), 5)}  {verdict}")
    drift = dec.get("base_drift")
    lines.append(f"base repeat drift {'-' if drift is None else f'{drift:.1%}'}; "
                 f"budget {BUDGET:.0%} on median and 1% low FPS; {dec['verdict']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", help="the session folder of NN_ARM.csv files")
    ap.add_argument("--game", default=GAME, help=f"process name (default {GAME})")
    ap.add_argument("--json", default=None, help="also write the table as JSON here")
    a = ap.parse_args(argv)
    arms = collect_arms(Path(a.dir), a.game)
    dec = decide(arms)
    print(table(arms, dec))
    if a.json:
        Path(a.json).write_text(json.dumps({"version": FRAMETIME_RESULTS_VERSION,
                                            "arms": arms, "decision": dec}, indent=1) + "\n",
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
