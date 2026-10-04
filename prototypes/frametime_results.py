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
* An arm PASSES when both costs are at most `BUDGET` (0.20) and every one of
  its repeats has a load log showing the harness kept pace: `pace` (stored
  over wall seconds, a whole-run ratio) at least `PACE_MIN` and its
  95th-percentile call lateness `lag_s.p95` at most `LAG_P95_MAX` seconds. A
  missing log fails the level: nothing shows its load ran. The chosen level
  is the highest reticle level that passes.
* Measuring against `base` charges OBS's cost to reticle. That reference is
  the kit's choice, not the player's; `chosen_vs_obs` applies the same rule
  against `obs` so both answers sit side by side.
* NOISE: the spread of the `base` repeats. A cost below it is within noise;
  a spread above `DRIFT_MAX` makes the whole session undecided, and an
  undecided session names no level (`best_within_budget` keeps what the rule
  would have chosen, for the record only).
* `00_check.csv`, the protocol's 10 s PresentMon check, is not an arm and is
  skipped (`SKIP_ARMS`).

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
#: ...and one whose calls ran this many seconds late at the 95th percentile fell
#: behind in stretches even when its whole-run `pace` held.
LAG_P95_MAX = 1.0
#: Files named like arms that are not arms: the protocol's 10 s check.
SKIP_ARMS = ("check",)
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


def kept_pace(a: dict) -> tuple[bool, str | None]:
    """Whether every repeat of a level has a load log showing its harness kept
    pace, and why not."""
    logs = a.get("loads") or []
    if len(logs) < len(a.get("repeats") or []) or any(x is None for x in logs):
        return False, "no load log for every repeat"
    for x in logs:
        pace, p95 = x.get("pace"), (x.get("lag_s") or {}).get("p95")
        if pace is None or pace < PACE_MIN:
            return False, f"harness fell behind (pace {pace})"
        if p95 is None or p95 > LAG_P95_MAX:
            return False, f"harness calls ran late (lag p95 {p95} s)"
    return True, None


def decide(arms: dict) -> dict:
    """The decision table from per-arm pooled summaries (`arms[name]` holds
    `pooled`, `repeats` and `loads`, one load log or None per repeat)."""
    out = {"budget": BUDGET, "drift_max": DRIFT_MAX, "pace_min": PACE_MIN,
           "lag_p95_max": LAG_P95_MAX, "rows": {}, "chosen": None, "chosen_vs_obs": None,
           "best_within_budget": None, "verdict": None}
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
            paced, why = kept_pace(a)
            row["passes"] = bool(fits and paced)
            row["why"] = None if row["passes"] else "over budget" if not fits else why
            fits_obs = all(c is not None and c <= BUDGET
                           for c in (row["cost_median_vs_obs"], row["cost_low1_vs_obs"]))
            row["passes_vs_obs"] = bool(fits_obs and paced)
            if row["passes"]:
                out["best_within_budget"] = name
            if row["passes_vs_obs"]:
                out["best_vs_obs"] = name
        out["rows"][name] = row
    if drift is None:
        out["verdict"] = "undecided: base has fewer than two repeats"
    elif drift > DRIFT_MAX:
        out["verdict"] = f"undecided: base repeats drift {drift:.1%} > {DRIFT_MAX:.0%}"
    else:
        out["chosen"] = out["best_within_budget"]
        out["chosen_vs_obs"] = out.get("best_vs_obs")
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
        if arm in SKIP_ARMS:
            continue
        if arm not in ARMS:
            raise SystemExit(f"{p.name}: arm {arm!r} is not one of {', '.join(ARMS)}")
        ft, col, note = frame_times(p, game)
        a = arms.setdefault(arm, {"files": [], "repeats": [], "ft": [], "loads": []})
        a["files"].append({"file": p.name, "column": col, **note})
        a["repeats"].append(summary(ft))
        a["ft"].append(ft)
        load = p.with_name(p.stem + ".load.json")
        log = json.loads(load.read_text(encoding="utf-8")) if load.is_file() else None
        a["loads"].append(None if log is None else
                          {"pace": log.get("pace"),
                           "lag_s": {"p95": (log.get("lag_s") or {}).get("p95")}})
    if not arms:
        raise SystemExit(f"{d}: no arm files, only {', '.join(SKIP_ARMS)}")
    for a in arms.values():
        a["pooled"] = summary(np.concatenate(a.pop("ft")))
        paces = [x["pace"] for x in a["loads"] if x and x["pace"] is not None]
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
    if dec.get("chosen") is not None or dec.get("chosen_vs_obs") is not None:
        lines.append(f"against the game with OBS instead of the game alone: "
                     f"{dec.get('chosen_vs_obs') or 'no level'}")
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
