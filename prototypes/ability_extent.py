r"""Group ability fragments by (origin, BEARING) instead of (onset, distance).

    .\.venv\Scripts\python.exe prototypes\ability_extent.py

the model, 2026-09-05: an ability is an origin plus a deployment vector, and
**abilities have animations -- quite a few extend along a line or region.** If
that is right, the fragments of a wall or a beam are not "one object that grew",
they are the animation tracing the orientation. They share a BEARING from the
origin and their distance along it increases with time.

That predicts a different grouping rule from the one in use. `ability_corpus`
groups on (onset within 300 ms, centroid within 60 px), which encodes "appeared
at the same moment" -- right for a device that pops into existence, wrong for
anything that extends.

Measured over the 12 multi-candidate cast windows in `ability_cast`:

    objects under (onset, distance)   49
    objects under (origin, bearing)   30

**The one case with independent ground truth comes out right.** on
Viper's Toxic Screen: *it's a long straight line.* Its window holds 5
candidates, which the onset rule splits into 5 objects and this rule resolves
into **+10 deg x3** -- the three collinear fragments at (243,367), (283,375),
(306,376), with the two off-bearing candidates correctly rejected at -96 and
-61 deg. Sova's Hunter's Fury comes back as +46 deg x4 and +78 deg x3, i.e. two
bolt directions from one origin, which is what that ultimate does.

**Read the caveat before quoting the 30.** This rule was designed AFTER looking
at the Toxic Screen window, so that case is not evidence for it -- it is the
case it was fitted to. The other eleven are unvalidated, and at a 15 degree
tolerance a random pair agrees about 8% of the time, so any group of size two
(origin plus one) is worth nothing on its own.

**And the reason it cannot be validated today is worth naming: NOTHING IN THE
LABEL STORE SAYS WHICH CANDIDATES ARE ONE OBJECT.** Grouping has been in this
pipeline since `ability_corpus` and has never been scored against anything. That
is a cheap labelling ask -- the player marking fragments that belong together -- and
it would settle this rule, the onset rule, and the `position_ambiguous` refusals
in `ability_cast` at the same time.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_cast as ac

BEARING_TOL = 15.0   # degrees


def bearing_group(rows):
    """[(t,x,y,...)] -> groups sharing a bearing from the earliest candidate."""
    if len(rows) < 2:
        return [list(rows)] if rows else []
    rows = sorted(rows, key=lambda c: c[0])
    ox, oy = rows[0][1], rows[0][2]
    groups = []
    for r in rows[1:]:
        b = math.degrees(math.atan2(r[2] - oy, r[1] - ox))
        for g in groups:
            d = abs((b - g["bearing"] + 180) % 360 - 180)
            if d <= BEARING_TOL:
                g["rows"].append(r)
                g["bearing"] = sum(g["b"] + [b]) / (len(g["b"]) + 1)
                g["b"].append(b)
                break
        else:
            groups.append({"bearing": b, "b": [b], "rows": [r]})
    return [[rows[0]] + g["rows"] for g in groups] or [[rows[0]]]


print(f"bearing tolerance {BEARING_TOL:.0f} deg\n")
print(f"{'session':<10}{'t':>7}  {'ability':<16}{'cand':>5}{'onset/dist':>11}"
      f"{'bearing':>9}   orientation(s)")
tot_old = tot_new = tot_ev = 0
for sid in ("02cf738b1c8f", "6ab7a9e99235", "6bb88dba5d2c",
            "dae6f33f3f48", "ff19748eea8c"):
    cs, agent = ac.tray_casts(sid)
    cands = ac.candidates(sid)
    for t, slot, ab, sus in cs:
        win = [c for c in cands if -ac.POS_PRE <= (c[0] - t) <= ac.POS_POST]
        if len(win) < 2:
            continue
        old = ac.group(win)
        new = bearing_group(win)
        tot_ev += 1
        tot_old += len(old)
        tot_new += len(new)
        ors = []
        for g in new:
            if len(g) < 2:
                continue
            ox, oy = g[0][1], g[0][2]
            bs = [math.degrees(math.atan2(r[2] - oy, r[1] - ox)) for r in g[1:]]
            ors.append(f"{sum(bs) / len(bs):+.0f}deg x{len(g)}")
        print(f"{sid[:8]:<10}{t:7.2f}  {str(ab)[:16]:<16}{len(win):>5}"
              f"{len(old):>11}{len(new):>9}   {', '.join(ors) or '--'}")
print(f"\n{tot_ev} multi-candidate windows")
print(f"  objects under (onset, distance): {tot_old}")
print(f"  objects under (origin, bearing): {tot_new}")
print("\nFewer objects is only better if the merges are REAL. Check the"
      " orientation column:")
print("a group whose members share a bearing and increase in distance is an"
      " extending animation;")
print("one that merely happens to fall inside the tolerance is a coincidence,"
      " and at 15 deg")
print("a random pair agrees about 8% of the time.")
