"""Spawn-barrier anchors as MAP state, and the cut law that validates a set.

A barrier is furniture. It is drawn across the same doorway every round, in
team colour, and only during buy phase -- so detecting it per session is
paying every round for a fact about the map. `geometry` already made this
move for the floor; this is the same move for the bars, keyed the same way.

**The set is validated as a SET, which is the whole point.** The player's rule
is that barriers sit over chokepoints and *taken in aggregate separate the map
into ally, neutral and enemy territory* -- so the test is whether painting them
onto the passable floor cuts it into regions, and that is a property no single
bar has. It caught a real gap the first time it ran: Sunset's eight bars split
the floor 46/43 with a third region appearing as they thicken, while Lotus's
six never split it at all, which says Lotus is MISSING a barrier rather than
that any bar it found is wrong.

The bars are keyed on team colour and the key catches only part of each bar, so
`GROW_PX` closes the drawn bar to its blocking extent. It is not fitted to the
answer: the cut is reported at every growth so a set that only "works" at one
value is visible as such.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from . import geometry

BARRIER_VERSION = "barriers-0.1.0"

#: How far a drawn bar is grown before testing the cut. The team-colour key
#: catches the middle of a bar and not its ends; without this every set leaks
#: around every bar and the law cannot be tested at all.
GROW_PX = 6

#: How near a keyed component must sit to a baked anchor to BE that barrier.
#: The bar is furniture and does not move, so this is fit error, not motion.
ANCHOR_PX = 10

#: A region smaller than this share of the passable floor is a pocket behind a
#: bar, not a territory. Used only for REPORTING the partition.
REGION_MIN_FRAC = 0.01


def path(k: str, store) -> Path:
    return Path(store) / "barriers" / f"{k}.json"


def load(session: str, store) -> dict | None:
    """The baked anchors this session reads, or None when nothing is baked."""
    k = geometry.key_of(session, store)
    if k is None:
        return None
    p = path(k, store)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def merge(sets, tolerance=10.0):
    """Anchors from one or more rounds on ONE map, clustered by position.

    `seen_in` is kept per anchor rather than averaged away: an anchor found in
    one round of three is a different claim from one found in all three, and
    which it is decides whether a missing bar is a gap or a bad round.
    """
    out: list[dict] = []
    for i, bars in enumerate(sets):
        for b in bars:
            x, y = float(b["x"]), float(b["y"])
            for a in out:
                if (a["x"] - x) ** 2 + (a["y"] - y) ** 2 <= tolerance ** 2:
                    a["seen_in"].append(i)
                    break
            else:
                out.append({"x": x, "y": y, "box": [int(v) for v in b["box"]],
                            "seen_in": [i]})
    for a in out:
        a["seen_in"] = sorted(set(a["seen_in"]))
    return sorted(out, key=lambda a: (a["x"], a["y"]))


def partition(anchors, passable, grow=GROW_PX):
    """Regions the passable floor falls into once the bars are painted in.

    Returns (region_areas_descending, total_passable). Nothing is decided here
    -- a caller reports the shape and does not turn it into a pass mark, because
    how many territories a map should have is a fact about the map.
    """
    blocked = np.asarray(passable).copy()
    for a in anchors:
        x, y, w, h = a["box"]
        blocked[max(0, y - grow):y + h + grow, max(0, x - grow):x + w + grow] = False
    n, _, stats, _ = cv2.connectedComponentsWithStats(blocked.astype(np.uint8), 4)
    areas = sorted((int(stats[k, 4]) for k in range(1, n)), reverse=True)
    return areas, int(np.asarray(passable).sum())


def cut_report(anchors, passable, grows=(0, 2, 4, 6, 8, 10, 12)):
    """The cut at several growths, so a set that works at one is visible."""
    rows = []
    for g in grows:
        areas, total = partition(anchors, passable, g)
        big = [a for a in areas if a > total * REGION_MIN_FRAC]
        rows.append({"grow_px": g, "regions": len(big),
                     "fractions": [round(a / total, 4) for a in big[:5]]})
    return rows


def separates(anchors, passable, grow=GROW_PX):
    """Does this set cut the floor into more than one territory at all.

    The weakest form of the law, and the only one worth asserting from here:
    a set that leaves the map one connected region has not separated anything,
    whatever any individual bar looks like.
    """
    areas, total = partition(anchors, passable, grow)
    big = [a for a in areas if a > total * REGION_MIN_FRAC]
    # Two territories is the minimum, and the larger must not still be most of
    # the map -- eight pockets behind eight bars is not a partition.
    return len(big) >= 2 and areas[0] < total * 0.75


def _passable_for(session, store):
    from . import cone
    from .minimap import floor_mask
    with np.load(geometry.require(session, store)) as z:
        return cone.passable_from(z["labels"].copy(), floor_mask(z["static"].copy()))


def main(argv=None):
    """Bake barrier anchors for one map from rendered rounds, and test the cut.

        python -m reticle.barriers SESSION ROUND_DIR [ROUND_DIR ...] [--write]
    """
    import argparse
    from .store import Store
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("session")
    ap.add_argument("rounds", nargs="+", type=Path,
                    help="round export directories holding barrier-candidates.json")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    store = Store().root
    k = geometry.key_of(args.session, store)
    if k is None:
        raise SystemExit(f"{args.session} has no `map:` tag, so it keys no barriers")
    sets = [json.loads((d / "barrier-candidates.json").read_text(encoding="utf-8"))
            for d in args.rounds]
    anchors = merge(sets)
    passable = _passable_for(args.session, store)
    report = cut_report(anchors, passable)
    print(f"{k}: {len(anchors)} anchors from {len(sets)} round(s)")
    for a in anchors:
        w, h = a["box"][2], a["box"][3]
        print(f"   ({a['x']:6.1f},{a['y']:6.1f})  {w:3}x{h:<3} "
              f"{'horizontal' if w > h else 'vertical':10} seen in {len(a['seen_in'])}/{len(sets)}")
    print("   cut of the passable floor:")
    for r in report:
        print(f"     grow {r['grow_px']:2} px -> {r['regions']} regions  "
              f"{[f'{f:.0%}' for f in r['fractions']]}")
    ok = separates(anchors, passable)
    print(f"   SEPARATES THE MAP: {ok}"
          + ("" if ok else "  -- the set is INCOMPLETE, a barrier is missing"))
    if args.write:
        out = path(k, store)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"version": BARRIER_VERSION, "key": k,
                                   "grow_px": GROW_PX, "anchors": anchors,
                                   "cut": report, "separates": ok,
                                   "rounds": [str(d) for d in args.rounds]},
                                  indent=2), encoding="utf-8")
        print(f"   wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
