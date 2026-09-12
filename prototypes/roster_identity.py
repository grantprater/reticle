r"""WHICH agents are alive at each instant, on both teams, by name.

    .\.venv\Scripts\python.exe prototypes\roster_identity.py SESSION [--hz 1]

Why this is step one
--------------------
`CLAUDE.md`'s north star is an event stream CARRYING IDENTITY, and identity is
the primary means by which any rule of movement or existence can be verified --
a position with no name cannot contradict a speed limit, a continuity rule, a
teleport, or an origin-event invariant. Nothing stored carries it. `l1/roster`
holds COUNTS, `l1/hud` holds TEAM masks, `l1/minimap` holds positional
`ally0..3` slots over a track identity that already churns.

Deaths are the entry point rather than the goal, because two independent
channels bracket a death and identity is sharpest there. This produces the half
that is missing: the SET of agents alive at t. Differencing that set at a
killfeed death time names the victim, which is step two.

THE PACKING IS THE PROBLEM, AND THE ORDER IS THE SOLUTION
----------------------------------------------------------
`roster.alive_from_detail` reads the living as a CONTIGUOUS run anchored at the
scoreline edge, so a dead player is dropped and the survivors SHIFT. Slot 2 is a
different agent before and after a death, which is why `lineup.Lineup.add`
accumulates only from a side that is fully alive -- five alive is the only state
in which the index is an identity.

But the survivors keep TEAM ORDER, which `prototypes/CLAUDE.md` already states:
*slot index is not identity -- the sequence is.* So with the side's five agents
known from the stored lineup, the k occupied cells are a k-SUBSEQUENCE of those
five, in order. That is at most ten candidate subsets for a five-slot bar, and
the order constraint is doing most of the work: it refuses the assignment that
independent per-slot classification would happily make.

**So this is a 5-choose-k ordered assignment, not a 29-way classification.**
The lineup narrows the candidates to five per side before a single pixel is
compared, which is the same move that made the cold bootstrap work -- the top
bar proposes only five candidates, and among those five the answer wins by a
margin the open-set matcher could not reach.

What it refuses, and why that matters more than what it answers
---------------------------------------------------------------
* a side whose `alive_from_detail` is unreadable produces NO answer for that
  side on that frame, never a guess;
* a side with no stored lineup, or whose lineup REFUSED a slot on a thin
  margin, is reported as unnamed. `lineup` writes `agent: null` with a reason
  where the margin is below `MARGIN_MIN`, and a refused slot must produce an
  unnamed death rather than a named wrong one;
* a frame whose best ordered assignment beats the runner-up by less than
  `MARGIN_MIN` is recorded with its margin so a caller can gate on it.

Diagnostic. It writes an alive-set series and changes no reader.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle import metrics                                       # noqa: E402
from reticle.lineup import (MARGIN_MIN, load_gallery, load_lineup,  # noqa: E402
                            slot_crops, _composition)
from reticle.profiles import get_profile                          # noqa: E402
from reticle.roster import (N_SLOTS, alive_counts, roster_rois)   # noqa: E402
from reticle.store import DEFAULT_STORE                           # noqa: E402

IDENTITY_VERSION = "roster-identity-0.1.0"

#: Sides, in the order the profile's ROIs come.
SIDES = ("ally", "enemy")


def lineup_agents(session: str, store: Path) -> dict[str, list[str | None]]:
    """The five agents per side, in slot order. `None` where lineup refused.

    Read from the STORED lineup rather than recomputed: it is a per-session
    verdict accumulated over ~130 frames, and re-deriving it per frame would
    be both slower and worse than the thing it already agreed on.
    """
    stored = load_lineup(session, store)
    out: dict[str, list[str | None]] = {}
    if not stored:
        return out
    for side, rows in (stored.get("sides") or {}).items():
        by_slot: dict[int, str | None] = {}
        for row in rows:
            by_slot[int(row["slot"])] = row.get("agent")
        out[side] = [by_slot.get(i) for i in range(N_SLOTS)]
    return out


def _histograms(frame, roi) -> list[np.ndarray | None]:
    """One composition histogram per roster cell, left to right."""
    if roi is None:
        return [None] * N_SLOTS
    x0, y0, x1, y1 = roi
    cells = slot_crops(frame[y0:y1, x0:x1])
    out: list[np.ndarray | None] = []
    for cell in cells:
        out.append(_composition(cell) if cell.size else None)
    return out + [None] * (N_SLOTS - len(out))


def _score(hist, agent: str | None, gallery) -> float:
    """Histogram intersection against every official surface of one agent."""
    if hist is None or agent is None or agent not in gallery:
        return 0.0
    return sum(float(np.minimum(hist, g).sum()) for g in gallery[agent])


def assign_alive(hists: list[np.ndarray | None], roster: list[str | None],
                 alive: int, gallery) -> dict:
    """The best ORDERED assignment of `alive` roster agents to the packed cells.

    The survivors keep team order, so the answer is a subsequence of `roster`
    rather than a free permutation -- ten candidates at most for five slots.
    Returns the chosen agents, the score, and the MARGIN over the runner-up,
    because the margin is the only thing here that knows whether the answer is
    worth having.
    """
    if alive is None or alive <= 0 or alive > N_SLOTS:
        return {"agents": [], "score": 0.0, "margin": None, "reason": "no_alive"}
    cells = list(hists[:alive])
    if any(h is None for h in cells):
        return {"agents": [], "score": 0.0, "margin": None, "reason": "no_cells"}
    # A REFUSED lineup slot poisons the whole side, and quietly. An unnamed
    # agent scores zero against every cell, so every subset containing it loses
    # and the assignment silently prefers the NAMED slots -- reporting a named
    # agent alive in a cell whose true occupant lineup declined to name. That
    # is precisely the "named wrong one" the plan forbids, so the side refuses.
    unnamed = sum(1 for a in roster if not a)
    if unnamed:
        return {"agents": [], "score": 0.0, "margin": None,
                "reason": f"roster_incomplete:{N_SLOTS - unnamed}/{N_SLOTS}"}
    scored = []
    for pick in itertools.combinations(range(N_SLOTS), alive):
        agents = [roster[i] for i in pick]
        total = sum(_score(h, a, gallery) for h, a in zip(cells, agents))
        scored.append((total, agents))
    scored.sort(key=lambda r: -r[0])
    best, agents = scored[0]
    if len(scored) == 1:
        # Every roster agent is alive, so there is no choice to report a margin
        # over. Calling that 1.0 was a bug: it made the most trivial case look
        # like the most confident one and dominated the median.
        return {"agents": agents, "score": round(best, 4), "margin": None,
                "reason": None}
    runner = scored[1][0]
    margin = (best - runner) / best if best > 0 else 0.0
    return {"agents": agents, "score": round(best, 4),
            "margin": round(margin, 4), "reason": None}


def read_alive_series(session: str, store: Path, hz: float = 1.0,
                 limit: int | None = None) -> dict:
    """Sample the match and name the living on both sides at each instant."""
    manifest = json.loads((store / "manifests" / f"{session}.json")
                          .read_text(encoding="utf-8"))
    source = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    width, height = int(source["width"]), int(source["height"])
    rois = dict(zip(SIDES, roster_rois(profile, width, height)))
    roster = lineup_agents(session, store)
    gallery = load_gallery(store)

    capture = cv2.VideoCapture(source["path"])
    fps = float(source["fps"])
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(fps / hz)))
    series, counts = [], {"frames": 0, "unreadable": 0, "thin": 0}
    index = 0
    while index < total:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok:
            break
        t_ms = int(round(index / fps * 1000.0))
        alive = dict(zip(SIDES, alive_counts(frame, profile, width, height)))
        row = {"t_ms": t_ms}
        for side in SIDES:
            got = assign_alive(_histograms(frame, rois.get(side)),
                               roster.get(side, [None] * N_SLOTS),
                               alive.get(side), gallery)
            row[side] = {"alive": alive.get(side), "agents": got["agents"],
                         "margin": got["margin"], "reason": got["reason"]}
            if got["reason"]:
                counts["unreadable"] += 1
            elif got["margin"] is not None and got["margin"] < MARGIN_MIN:
                counts["thin"] += 1
        series.append(row)
        counts["frames"] += 1
        if limit and counts["frames"] >= limit:
            break
        index += step
    capture.release()
    return {"session": session, "series": series, "counts": counts,
            "roster": roster}


from reticle.adjudication.death import shrink_events  # promoted to adjudication.death



def report(result: dict) -> str:
    series, counts = result["series"], result["counts"]
    lines = [f"{result['session']}  {counts['frames']} frames sampled",
             f"  roster: " + "; ".join(
                 f"{s}=" + ",".join(a or "?" for a in result['roster'].get(s, []))
                 for s in SIDES if result['roster'].get(s))]
    for side in SIDES:
        named = [r for r in series if r[side]["agents"]]
        margins = [r[side]["margin"] for r in named
                   if r[side]["margin"] is not None]
        thin = [m for m in margins if m < MARGIN_MIN]
        reasons = {}
        for r in series:
            if r[side]["reason"]:
                reasons[r[side]["reason"]] = reasons.get(r[side]["reason"], 0) + 1
        lines.append(
            f"  {side:5}  named {len(named)}/{len(series)} frames"
            + (f"  median margin {np.median(margins):.3f} over {len(margins)}"
               if margins else "  no contested frame")
            + f"  thin(<{MARGIN_MIN}) {len(thin)}")
        if reasons:
            lines.append(f"         refused: {reasons}")
        events = shrink_events(series, side)
        lines.append(f"         {len(events)} shrink event(s)"
                     + (f", first: {events[0]['gone']} at "
                        f"{events[0]['t_ms'] / 1000:.1f}s" if events else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions", nargs="+")
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N sampled frames")
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--write", action="store_true",
                        help="write the series to <store>/alive/<session>.json")
    args = parser.parse_args(argv)
    store = Path(args.store)

    for session in args.sessions:
        if not lineup_agents(session, store):
            print(f"{session}: no stored lineup -- run `reticle lineup` first; "
                  f"identity cannot be named without one")
            metrics.record("roster_identity", part="alive_set", session=session,
                           status=metrics.CANNOT_ANSWER,
                           note="no stored lineup",
                           deps={"version": IDENTITY_VERSION}, context={})
            continue
        result = read_alive_series(session, store, args.hz, args.limit)
        print(report(result))
        values = {"frames": result["counts"]["frames"],
                  "unreadable_sides": result["counts"]["unreadable"],
                  "thin_sides": result["counts"]["thin"]}
        for side in SIDES:
            named = [r for r in result["series"] if r[side]["agents"]]
            values[f"{side}_named_frames"] = len(named)
            values[f"{side}_named_frac"] = (
                round(len(named) / max(1, result["counts"]["frames"]), 4))
            values[f"{side}_shrink_events"] = len(
                shrink_events(result["series"], side))
            contested = [r[side]["margin"] for r in named
                         if r[side]["margin"] is not None]
            values[f"{side}_contested_frames"] = len(contested)
            values[f"{side}_median_margin"] = (
                round(float(np.median(contested)), 4) if contested else None)
        metrics.record(
            "roster_identity", part="alive_set", session=session, values=values,
            deps={"version": IDENTITY_VERSION,
                  "assignment": metrics.fingerprint(assign_alive,
                                                    MARGIN_MIN=MARGIN_MIN),
                  "lineup": "stored"},
            context={"hz": args.hz, "roster": {s: result["roster"].get(s)
                                               for s in SIDES}})
        if args.write:
            out = store / "alive" / f"{session}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(
                {"version": IDENTITY_VERSION, "hz": args.hz,
                 "roster": result["roster"], "series": result["series"]}),
                encoding="utf-8")
            print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
