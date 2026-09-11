"""An entity TRANSFORMS; it does not move, end, or become a second entity.

the player, 2026-09-09, on a Deadlock sensor going dim: *this is a phase shift of the
ability conditioned on other game state. The ability does not move, it
transforms. This is a general pattern that I had hoped to capture and thought we
already had.*

We did not. `docs/ABILITY_ENTITY_INFERENCE_DESIGN.md` says "phase transitions"
once in prose, `ability_timeline` carries unresolved transition alternatives for
the CAST, and the gallery's `pre/onset/early/sustained` are time bins relative to
an observation rather than states of an object -- its own limits say so. Nothing
modelled a deployed entity changing state and staying itself. Two consequences
were live in the pipeline before this module:

* **grouping split one entity in two.** Onset-and-distance grouping keys on a
  fresh appearance, so a device that dims reads as a new object at the same
  place rather than the same object in a new state;
* **lifetimes ended at the transition.** An interval that stops when the bright
  pixels stop reports a destruction that did not happen -- which is the third
  termination story the capture matrix does not have, beside expiry and
  destruction.

The model
---------
An entity holds an ordered list of PHASES. A phase is an interval plus an
appearance mode. A TRANSITION between consecutive phases carries candidate
CAUSES from a closed set, and `unresolved` when none of them has evidence:

    owner_death            an ally died near the transition   (killfeed)
    owner_left_radius      REVERSIBLE, Killjoy and Chamber    (needs owner track)
    owner_returned_radius  the reverse of it
    triggered_activation   Vyse's vines becoming a circle
    destroyed              an ending with a cause
    expired                an ending without one

This mirrors the ORIGIN EVENT model already recorded in `prototypes/CLAUDE.md`:
a birth comes from a closed set, so an unexplained birth is a flag rather than a
silent row. A transition is the same claim applied to the middle of a life, and
it earns the same property -- an unexplained transition is visible.

Two rules are structural rather than tuned, and both are asserted by tests:

* a phase change never creates a new entity;
* a lifetime never ends at a phase boundary, only at a terminal phase.

Stored data only. Contrast comes from the series' own `g_max - g_min`, so no
frame is decoded here.

Owns [owns:ability-phase].
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

ABILITY_PHASE_VERSION = "ability-phases-0.2.0"

#: The empty gap measured on 2026-09-09 between the two appearance modes of the
#: 71 labelled sonic sensors: 24 at contrast 122-175, 47 at 231-241.
DIM_CONTRAST_MAX = 203.0
#: A phase has to persist to be a phase rather than a flicker or an occlusion.
MIN_PHASE_MS = 700.0
#: A missing interval is not evidence that an appearance continued.  Three
#: ordinary sample periods tolerates timestamp jitter without bridging a real
#: hole in the trace.
MAX_SAMPLE_GAP_PERIODS = 3.0
#: How near a candidate cause must sit to be offered for a transition at all.
CAUSE_WINDOW_MS = 12000.0

TRANSITION_CAUSES = (
    "owner_death",
    "owner_left_radius",
    "owner_returned_radius",
    "triggered_activation",
    "destroyed",
    "expired",
)
#: Reversible causes: a device that dims for one of these can come back, so a
#: dim phase is not an ending. The player named Killjoy; Chamber is the other
#: candidate and is not confirmed.
REVERSIBLE = ("owner_left_radius", "owner_returned_radius")
#: The player: the only deployed abilities that do NOT deactivate on owner death.
PERSISTS_THROUGH_OWNER_DEATH = frozenset({
    "deadlock:barrier mesh", "viper:toxic screen", "cypher:cyber cage",
    "sage:barrier orb",
})


def load_series(root: Path, session: str):
    path = Path(root) / "series" / f"{session}.npz"
    if not path.is_file():
        return None
    z = np.load(path, allow_pickle=True)
    queries = json.loads(str(z["queries"]))
    return {
        "t_ms": np.asarray(z["t_ms"], float),
        "queries": queries,
        "g_max": z["g_max"], "g_min": z["g_min"],
        "win_lo": z["win_lo"], "win_hi": z["win_hi"],
        "index": {(int(q["x"]), int(q["y"]), float(q["t_ms"])): i
                  for i, q in enumerate(queries)},
    }


def segment(times: np.ndarray, contrast: np.ndarray,
            split: float = DIM_CONTRAST_MAX,
            min_ms: float = MIN_PHASE_MS,
            max_gap_ms: float | None = None) -> list[dict]:
    """Contiguous support for measured appearance, never operational state.

    Bright/dim are photometric candidates.  A short run is retained as transient
    evidence on its neighbour; it is not promoted to a durable appearance and
    is not erased.  A sampling hole starts a new support interval even when both
    sides look alike.  Nothing here asserts active/inactive, existence through a
    hole, or a causal game transition.
    """
    times = np.asarray(times, float)
    contrast = np.asarray(contrast, float)
    if times.size != contrast.size:
        raise ValueError("times and contrast must have equal length")
    if times.size == 0:
        return []
    if (not np.isfinite(times).all() or not np.isfinite(contrast).all()
            or np.any(np.diff(times) <= 0)):
        raise ValueError("phase evidence needs finite, strictly increasing timestamps")
    diffs = np.diff(times)
    ordinary_period = float(np.median(diffs)) if diffs.size else 0.0
    if max_gap_ms is None:
        max_gap_ms = ordinary_period * MAX_SAMPLE_GAP_PERIODS
    if not np.isfinite(max_gap_ms) or max_gap_ms < 0:
        raise ValueError("max_gap_ms must be finite and nonnegative")

    appearances = np.where(contrast > split, "bright", "dim")
    raw = []
    start = 0
    for i in range(1, len(appearances) + 1):
        gap = i < len(appearances) and times[i] - times[i - 1] > max_gap_ms
        change = i == len(appearances) or appearances[i] != appearances[start]
        if change or gap:
            raw.append({"appearance": str(appearances[start]),
                        "from_ms": float(times[start]),
                        "to_ms": float(times[i - 1]),
                        "samples": int(i - start),
                        "coverage_break_before_ms": (None if start == 0 else
                            float(times[start] - times[start - 1])
                            if times[start] - times[start - 1] > max_gap_ms else None)})
            start = i
    merged: list[dict] = []
    for run in raw:
        short = run["to_ms"] - run["from_ms"] < min_ms
        separated = run["coverage_break_before_ms"] is not None
        if (merged and not separated
                and run["appearance"] == merged[-1]["appearance"]):
            merged[-1]["to_ms"] = run["to_ms"]
            merged[-1]["samples"] += run["samples"]
        elif merged and short and not separated:
            evidence = {**run, "status": "transient_unresolved"}
            merged[-1].setdefault("transient_evidence", []).append(evidence)
            merged[-1]["to_ms"] = run["to_ms"]
            merged[-1]["samples"] += run["samples"]
            merged[-1]["absorbed_transients"] = merged[-1].get("absorbed_transients", 0) + 1
        elif short:
            merged.append({**run, "status": "transient_unresolved",
                           "operational_state": "unknown"})
        else:
            merged.append({**run, "status": "stable_appearance",
                           "operational_state": "unknown"})
    return merged


def candidate_causes(transition_ms: float, ability_id: str | None,
                     from_appearance: str, to_appearance: str,
                     deaths: list[float]) -> list[dict]:
    """Causes the evidence can currently offer, each with what supports it.

    A cause is never asserted. Where the channel that would settle one does not
    exist yet -- no owner track, so no radius test -- the cause is still listed,
    marked `unavailable` with the reason, so the gap is visible rather than
    silently absent. That is the same treatment the origin model gives a birth
    it cannot explain.
    """
    out = []
    persists = ability_id in PERSISTS_THROUGH_OWNER_DEATH
    if to_appearance == "dim" and not persists:
        prior = [d for d in deaths if 0 <= transition_ms - d <= CAUSE_WINDOW_MS]
        out.append({
            "cause": "owner_death",
            "status": "conditional" if prior else "unsupported",
            "evidence": ({"nearby_ally_death_ms": round(transition_ms - max(prior), 1)}
                         if prior else None),
            "limit": ("the killfeed says an ALLY died, not that this device's OWNER "
                      "died; owner identity is a required unresolved prerequisite"),
            "prerequisites": {"owner_identity": "unknown",
                              "ability_rule_applicable": "unknown"},
        })
    if to_appearance == "dim" and persists:
        out.append({
            "cause": "owner_death", "status": "excluded",
            "evidence": None,
            "limit": f"{ability_id} persists through its owner's death",
        })
    direction = "owner_left_radius" if to_appearance == "dim" else "owner_returned_radius"
    out.append({
        "cause": direction, "status": "unavailable",
        "evidence": None,
        "limit": ("no owner track exists for a non-local player, so the radius "
                  "test cannot be run; reversible, so it is a live alternative"),
    })
    if to_appearance == "bright" and from_appearance == "dim":
        out.append({
            "cause": "triggered_activation", "status": "candidate",
            "evidence": None,
            "limit": "a dim-to-live step is also what a reactivation looks like",
        })
    return out


def entity_phases(root: str | Path, session: str, components: list[dict],
                  deaths: list[float]) -> list[dict]:
    """One record per component, holding its phases and their transitions."""
    root = Path(root)
    series = load_series(root, session)
    if series is None:
        return []
    out = []
    for component in components:
        key = (int(component["x"]), int(component["y"]),
               float(component["observed_t_ms"]))
        row = series["index"].get(key)
        if row is None:
            continue
        lo, hi = int(series["win_lo"][row]), int(series["win_hi"][row])
        times = series["t_ms"][lo:hi]
        contrast = (np.asarray(series["g_max"][row][lo:hi], float)
                    - np.asarray(series["g_min"][row][lo:hi], float))
        appearances = segment(times, contrast)
        if not appearances:
            continue
        transitions = []
        for before, after in zip(appearances, appearances[1:]):
            if after["coverage_break_before_ms"] is not None:
                continue
            at = after["from_ms"]
            causes = candidate_causes(at, component.get("label_ability_id"),
                                      before["appearance"], after["appearance"], deaths)
            supported = [c for c in causes if c["status"] == "supported"]
            transitions.append({
                "at_ms": at,
                "from_appearance": before["appearance"],
                "to_appearance": after["appearance"],
                "operational_state_before": "unknown",
                "operational_state_after": "unknown",
                "causes": causes,
                "resolved": bool(supported) and len(supported) == 1,
                "unexplained": not supported,
            })
        out.append({
            "component_id": component["component_id"],
            "session_id": session,
            "ability_id": component.get("label_ability_id"),
            "x": component["x"], "y": component["y"],
            "observed_window_ms": [float(times[0]), float(times[-1])],
            "appearance_segments": appearances,
            "coverage_gaps": [{"from_ms": before["to_ms"],
                               "to_ms": after["from_ms"],
                               "duration_ms": after["coverage_break_before_ms"]}
                              for before, after in zip(appearances, appearances[1:])
                              if after["coverage_break_before_ms"] is not None],
            "transitions": transitions,
            # The two structural rules, carried on the row so a consumer cannot
            # quietly reintroduce either.
            "entity_count": 1,
            "observed_support_ms": [[p["from_ms"], p["to_ms"]] for p in appearances],
            "existence_interval_ms": None,
            "existence_status": "unresolved_from_appearance",
            "terminal": False,
        })
    return out


def summarise(rows: list[dict]) -> dict:
    transitions = [t for r in rows for t in r["transitions"]]
    return {
        "entities": len(rows),
        "entities_with_a_transition": sum(1 for r in rows if r["transitions"]),
        "transitions": len(transitions),
        "by_direction": dict(sorted(Counter(
            f"{t['from_appearance']}->{t['to_appearance']}" for t in transitions).items())),
        "resolved": sum(1 for t in transitions if t["resolved"]),
        "unexplained": sum(1 for t in transitions if t["unexplained"]),
        "phases_per_entity": dict(sorted(Counter(
            len(r["appearance_segments"]) for r in rows).items())),
    }
