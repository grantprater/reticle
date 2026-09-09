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
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

ABILITY_PHASE_VERSION = "ability-phases-0.1.0"

#: The empty gap measured on 2026-09-09 between the two appearance modes of the
#: 71 labelled sonic sensors: 24 at contrast 122-175, 47 at 231-241.
DIM_CONTRAST_MAX = 203.0
#: A phase has to persist to be a phase rather than a flicker or an occlusion.
MIN_PHASE_MS = 700.0
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
PERSISTS_THROUGH_OWNER_DEATH = ("barrier mesh", "toxic screen", "cyber cage",
                                "wall", "barrier")


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
            min_ms: float = MIN_PHASE_MS) -> list[dict]:
    """Runs of one appearance mode, with flickers absorbed into their neighbour.

    A single frame on the far side of the split is an occlusion or a dropped
    read, not a state the object entered, so a run shorter than ``min_ms`` is
    merged rather than emitted. Merging INTO the previous run keeps the phase
    count honest: inventing a phase per flicker would make every entity look
    like it transforms constantly.
    """
    if times.size == 0:
        return []
    modes = np.where(contrast > split, "live", "dim")
    runs = []
    start = 0
    for i in range(1, len(modes) + 1):
        if i == len(modes) or modes[i] != modes[start]:
            runs.append({"mode": str(modes[start]),
                         "from_ms": float(times[start]),
                         "to_ms": float(times[i - 1]),
                         "samples": int(i - start)})
            start = i
    merged: list[dict] = []
    for run in runs:
        short = run["to_ms"] - run["from_ms"] < min_ms
        if merged and (short or run["mode"] == merged[-1]["mode"]):
            # Absorbing a flicker leaves the runs either side of it adjacent and
            # in the SAME mode. Appending regardless is what turned one steady
            # object into four phases and reported live->live as a transition.
            merged[-1]["to_ms"] = run["to_ms"]
            merged[-1]["samples"] += run["samples"]
            if short:
                merged[-1]["absorbed_flickers"] = merged[-1].get("absorbed_flickers", 0) + 1
        elif short:
            continue
        else:
            merged.append(dict(run))
    return merged


def candidate_causes(transition_ms: float, ability_id: str | None,
                     from_mode: str, to_mode: str,
                     deaths: list[float]) -> list[dict]:
    """Causes the evidence can currently offer, each with what supports it.

    A cause is never asserted. Where the channel that would settle one does not
    exist yet -- no owner track, so no radius test -- the cause is still listed,
    marked `unavailable` with the reason, so the gap is visible rather than
    silently absent. That is the same treatment the origin model gives a birth
    it cannot explain.
    """
    out = []
    persists = bool(ability_id) and any(w in ability_id for w in PERSISTS_THROUGH_OWNER_DEATH)
    if to_mode == "dim" and not persists:
        prior = [d for d in deaths if 0 <= transition_ms - d <= CAUSE_WINDOW_MS]
        out.append({
            "cause": "owner_death",
            "status": "supported" if prior else "unsupported",
            "evidence": ({"nearest_ally_death_ms": round(transition_ms - max(prior), 1)}
                         if prior else None),
            "limit": ("the killfeed says an ALLY died, not that this device's OWNER "
                      "died: survivors pack in the roster bar so a slot is not an "
                      "identity"),
        })
    if to_mode == "dim" and persists:
        out.append({
            "cause": "owner_death", "status": "excluded",
            "evidence": None,
            "limit": f"{ability_id} persists through its owner's death",
        })
    direction = "owner_left_radius" if to_mode == "dim" else "owner_returned_radius"
    out.append({
        "cause": direction, "status": "unavailable",
        "evidence": None,
        "limit": ("no owner track exists for a non-local player, so the radius "
                  "test cannot be run; reversible, so it is a live alternative"),
    })
    if to_mode == "live" and from_mode == "dim":
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
        phases = segment(times, contrast)
        if not phases:
            continue
        transitions = []
        for before, after in zip(phases, phases[1:]):
            at = after["from_ms"]
            causes = candidate_causes(at, component.get("label_ability_id"),
                                      before["mode"], after["mode"], deaths)
            supported = [c for c in causes if c["status"] == "supported"]
            transitions.append({
                "at_ms": at, "from_mode": before["mode"], "to_mode": after["mode"],
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
            "phases": phases,
            "transitions": transitions,
            # The two structural rules, carried on the row so a consumer cannot
            # quietly reintroduce either.
            "entity_count": 1,
            "lifetime_ms": [phases[0]["from_ms"], phases[-1]["to_ms"]],
            "lifetime_note": ("an interval spanning every phase: a transition is not "
                              "an ending, and a dim phase may be reversible"),
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
            f"{t['from_mode']}->{t['to_mode']}" for t in transitions).items())),
        "resolved": sum(1 for t in transitions if t["resolved"]),
        "unexplained": sum(1 for t in transitions if t["unexplained"]),
        "phases_per_entity": dict(sorted(Counter(
            len(r["phases"]) for r in rows).items())),
    }
