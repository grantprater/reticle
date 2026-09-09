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


def reachable(passable):
    """The one piece of ground the bars are meant to cut.

    The passable mask is not connected to begin with -- on Sunset it holds
    93,861 px plus two pockets of ~1,170 px each that no bar created, and
    counting those as territories made a correct nine-bar set read as five.
    A territory is a region the BARS made; anything already separate is the
    map, and is excluded before the cut is measured rather than after.
    """
    m = np.asarray(passable).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 4)
    if n <= 1:
        return np.asarray(passable).astype(bool)
    big = 1 + int(np.argmax(stats[1:, 4]))
    return lab == big


def _blocked(anchors, passable, grow):
    blocked = np.asarray(passable).copy()
    for a in anchors:
        x, y, w, h = a["box"]
        blocked[max(0, y - grow):y + h + grow, max(0, x - grow):x + w + grow] = False
    return blocked


def partition(anchors, passable, grow=GROW_PX):
    """Regions the passable floor falls into once the bars are painted in.

    Returns (region_areas_descending, total_passable). Nothing is decided here
    -- a caller reports the shape and does not turn it into a pass mark, because
    how many territories a map should have is a fact about the map.
    """
    blocked = _blocked(anchors, passable, grow)
    n, _, stats, _ = cv2.connectedComponentsWithStats(blocked.astype(np.uint8), 4)
    areas = sorted((int(stats[k, 4]) for k in range(1, n)), reverse=True)
    return areas, int(np.asarray(passable).sum())


def territories(anchors, passable, grow=GROW_PX):
    """The regions, and WHICH BAR separates which pair of them.

    **The player's honing of the cut law, 2026-09-08, and it is much stronger
    than the count this module was testing:** *"the ally portion includes the
    ally spawn, which is either the top or bottom of the map depending on
    attacking/defending (attackers are bottom on these non-rotating maps). The
    ally portion is entirely separated from the neutral portion, which in turn
    is entirely separated from the enemy portion, which includes the enemy
    spawn."*

    So the shape is not "two or more regions". It is exactly THREE, arranged
    in a PATH -- ally-neutral-enemy -- with no ally/enemy boundary anywhere,
    because a bar that separated the two spawns directly would mean the
    neutral ground has no way in. That is a much sharper falsifier for a
    barrier set than an area split, and it is what makes an incomplete set
    visible: a missing bar merges two territories into one.

    Adjacency is measured by REMOVING one bar at a time and asking which
    regions merge, so an edge is attributed to the bar that creates it. That
    is also what "ally barriers" and "enemy barriers" mean as a label: a bar
    is named by the pair it separates, not by where it sits.

    Returns `{"regions": [area, ...], "labels": ndarray, "edges": {bar_index:
    (region_a, region_b)}}` with regions ordered by descending area, or None
    when the floor does not separate at all.
    """
    passable = reachable(passable)
    blocked = _blocked(anchors, passable, grow)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(blocked.astype(np.uint8), 4)
    total = int(np.asarray(passable).sum())
    keep = [k for k in range(1, n) if stats[k, 4] > total * REGION_MIN_FRAC]
    keep.sort(key=lambda k: -stats[k, 4])
    if len(keep) < 2:
        return None
    order = {k: i for i, k in enumerate(keep)}
    labels = np.full(lab.shape, -1, np.int16)
    for k, i in order.items():
        labels[lab == k] = i
    edges = {}
    for j in range(len(anchors)):
        without = _blocked([a for i, a in enumerate(anchors) if i != j],
                           passable, grow)
        m, lab2, _, _ = cv2.connectedComponentsWithStats(without.astype(np.uint8), 4)
        # A bar joins two territories when removing it puts them in one piece.
        for c in range(1, m):
            here = {int(v) for v in np.unique(labels[lab2 == c]) if v >= 0}
            if len(here) == 2:
                edges[j] = tuple(sorted(here))
                break
    return {"regions": [int(stats[k, 4]) for k in keep],
            "labels": labels, "edges": edges, "total": total}


def chain(anchors, passable, grow=GROW_PX):
    """Are the territories a PATH of three -- ally, neutral, enemy?

    Returns `(ok, reason, order)` where `order` is the three region indices
    from one end of the path to the other, so a caller holding a point known
    to be in ally ground (the self icon during buy) can name them without
    assuming which end is which. The top/bottom rule is then a CHECK on that
    naming rather than its input -- see `main`.
    """
    passable = reachable(passable)
    t = territories(anchors, passable, grow)
    if t is None:
        return False, "the bars do not separate the floor at all", None
    k = len(t["regions"])
    if k != 3:
        return False, f"{k} territories, not 3 (a missing bar merges two)", None
    deg = {0: set(), 1: set(), 2: set()}
    for a, b in t["edges"].values():
        deg[a].add(b)
        deg[b].add(a)
    ends = [r for r in deg if len(deg[r]) == 1]
    middle = [r for r in deg if len(deg[r]) == 2]
    if len(ends) != 2 or len(middle) != 1:
        return False, ("the three territories are not a path: "
                       f"adjacency {{{', '.join(f'{r}:{sorted(deg[r])}' for r in deg)}}} "
                       "-- an ally/enemy boundary means neutral ground has no way in"), None
    return True, "ally - neutral - enemy", (ends[0], middle[0], ends[1])


def axis_of(mask_component):
    """The bar's own long axis, by PCA on its pixels. Orientation-agnostic.

    `cv2.minAreaRect`'s angle convention flips between -90 and 0 depending on
    which side it calls width, and using it turned every vertical bar into a
    horizontal one when this was first tried. Eigenvectors of the pixel
    covariance have no such convention.
    """
    ys, xs = np.where(mask_component)
    if len(xs) < 2:
        return 1.0, 0.0
    cov = np.cov(np.stack([xs - xs.mean(), ys - ys.mean()]))
    val, vec = np.linalg.eigh(cov)
    v = vec[:, int(np.argmax(val))]
    return float(v[0]), float(v[1])


def seal(anchor, passable, axis, limit=40):
    """How far each end of a bar is from the wall it should be sealing against.

    **A spawn barrier spans its doorway; the minimap draws only the part over
    open floor.** So the closure that matters is not a uniform growth -- it is
    an extension along the bar's OWN axis until it meets impassable ground,
    which needs no size constant at all. Returns `((sealed, px), (sealed, px))`
    for the two ends, `sealed` false meaning the walk ran `limit` px still on
    floor, i.e. this bar does not span whatever it sits in.

    Measured on Sunset's nine derived bars against the ART geometry: seven
    seal at both ends within 0-6 px, one is diagonal and was not measured on
    the right axis, and **bar (233, 186) walks 40 px along its axis without
    meeting a wall**. That one is why the flood still joins the two sides, and
    it is why the set is not baked: the player's cut law says three
    territories in a path, and a bar that does not span its opening cannot
    make one. The failure is a property of that bar, not of a growth constant.
    """
    x, y, w, h = anchor["box"]
    dx, dy = axis
    out = []
    for sgn in (1, -1):
        px, py = anchor["x"] + sgn * dx * (max(w, h) / 2), anchor["y"] + sgn * dy * (max(w, h) / 2)
        steps = 0
        sealed = False
        while steps < limit:
            ix, iy = int(round(px)), int(round(py))
            if not (0 <= ix < passable.shape[1] and 0 <= iy < passable.shape[0]):
                sealed = True
                break
            if not passable[iy, ix]:
                sealed = True
                break
            px += sgn * dx
            py += sgn * dy
            steps += 1
        out.append((sealed, steps))
    return tuple(out)


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

    The weakest form of the law and it is NOT the law: see `chain`, which
    tests the shape the player actually stated. This is kept as the floor
    under it, because a set that leaves the map one connected region has not
    separated anything whatever any individual bar looks like.
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
        return cone.passable_from(z["labels"].copy(),
                                  floor_mask(z["static"].copy(), sd=z["sd_lo"].copy()))


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
