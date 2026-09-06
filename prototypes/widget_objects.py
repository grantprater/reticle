r"""One segmentation of the widget per frame, grouped into OBJECTS, not blobs.

    .\.venv\Scripts\python.exe prototypes\widget_objects.py <session> --against-pings
    .\.venv\Scripts\python.exe prototypes\widget_objects.py <session> --sheet out.png

the player, 2026-09-05, on the ping detector's 26% precision:

> Is there a way to structure the detection so that it all happens at once? An
> example is tightly clustered or overlapping icons. If there were a way to
> recognize groupings, and do all the recognition at once in some way, that
> could be considerably more efficient.

This is step one of that: **segment once, group fragments into objects, and
measure objects.** No classifier, no fitted cost model, nothing that needs
labels -- so it can be checked immediately and either pays or does not.

Why blob-level detection failed, concretely
--------------------------------------------
Five detectors threshold the same crop independently -- `self_rings`,
`ally_rings`, `ping.sightings`, the ring fit, the colour-free diff -- each with
its own gates, each emitting blobs, and nothing arbitrates between them. On a
real match that produced the exact collision measured in
`prototypes/ping_match_eval.py`: 13 of 31 confirmed "pings" are ALLY ICONS,
because an ally icon is a cyan blob of icon size and so is a standard ping.

**The obvious fix -- veto a ping wherever `ally_rings` fires -- was tried and
is dead.** Distance to the nearest ring is median 0.9 px for real PINGS and
4.0 px for allies, because a cyan blob of icon size is precisely what that
detector is built to find. Any gate keeps 1 of 8 pings. That failure is the
argument for grouping rather than against it: a veto is the wrong shape when
two detectors legitimately claim the same pixels, and joint assignment over
objects is the right one.

The hypothesis this file tested, and it is FALSIFIED
-----------------------------------------------------
An ally icon is a RING around a portrait with a facing CONE hanging off it, so
in the saturated mask it should be two or more fragments spanning a wide box,
while a ping is one compact filled glyph. The prediction was that
`n_fragments` and object EXTENT would separate what blob-level area and fill
could not. Scored against `ping_match_eval`'s by-eye labels on 587c15b07779:

    gap 2 px   n_fragments  ping 1-1     ally 1-3     overlapping
               extent       ping  8-12   ally 10-22   overlapping
               area         ping 38-63   ally 40-83   overlapping

**No object-shape feature separates them at any grouping distance.** Some ally
icons come through as a single fragment -- the cone does not always clear the
saturation floor -- so "an ally is many fragments" is simply not true often
enough to gate on. Grouping is worth having, but not for this.

`GAP_PX` is the closing-radius trap again, and I walked into it
----------------------------------------------------------------
`CLAUDE.md` records, four times over, that *a closing radius that reconnects a
broken rim is the radius that merges adjacent icons*. The first version of this
docstring argued the trap did not apply, because **grouping RETAINS its
fragments** where closing destroys them, so a merge is recoverable -- and it
therefore set `GAP_PX` generously, on the reasoning that over-merging was the
safe direction.

The sweep says otherwise. At gap 6 a ping's object reaches 4 fragments and
extent 31 -- because pings are placed ON teammates, so the ping and the ally
merge into one object and every feature above is measuring the pair:

    gap  1-2    ping n=1      extent  8-12   area  38-63
    gap  3-4    ping n=1-3    extent  8-30   area  38-106
    gap  6      ping n=1-4    extent  8-31   area  38-136

"Recoverable in principle" is not recoverable by anything that exists, and
until a splitter does exist the generous gap is just the old trap with the
fragments kept as a souvenir. The default is 2.

That pings sit on teammates is itself the useful part of this result: the
ally/ping collision is not only a collision in FEATURE space, it is a collision
in SPACE, which is why every per-object shape feature fails on it and why the
answer has to come from constraints rather than from appearance.

What is NOT in this yet
-----------------------
* **only the saturated-on-floor channel.** That is the population that
  collided -- pings, ally and self icons, X marks, bars. The colour-free
  channel (black-and-white ability glyphs, invisible to any colour mask) is a
  second layer and belongs in the same segmentation eventually;
* **no assignment.** Objects are described, not labelled. Mutual exclusion,
  the roster's alive counts and the causal constraints the player named -- an
  ability implies a living caster, overlapping X marks imply two deaths the
  killfeed already knows about -- all need this layer to exist first and none
  of them is here.

**And the constraint that matters most is NOT AVAILABLE YET.** CLAUDE.md says
the roster bars draw a portrait only for a living player, calls the resulting
alive count "the densest validity signal available", and says it "costs one new
ROI". The ROIs exist (`hud_roster`, `hud_roster_enemy`) and **no alive-count
column is in the store** -- `l1/hud` has 34 columns and not one of them is a
roster read. So "at most N allies on the widget" cannot be asked of stored data
today, which is why this file could not test it.

Reading it is a READER, not a re-read: per-frame state at 2 Hz, riding the pass
`scan` already runs, writing its own small table with its own version so it does
not invalidate `hud`. That is the next thing to build here, and it is what turns
the object layer from plumbing into a detector.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.minimap import floor_mask, minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from reticle.store import Store                                   # noqa: E402

#: Saturation/value floor for "something is drawn on the opaque slab". The same
#: values `reticle.ping` uses, deliberately -- this is meant to be the SAME
#: segmentation those readers do separately, not a new one.
SAT_MIN, VAL_MIN = 120, 120
#: A fragment smaller than this is noise. Scales as an AREA.
FRAG_MIN_AREA = 8
#: How far apart two fragments may be and still be one object. Scales as a
#: LENGTH. Small on purpose: the sweep in the docstring shows a generous gap
#: merges a ping with the teammate it was placed on.
GAP_PX = 2


@dataclass
class Fragment:
    x: int
    y: int
    w: int
    h: int
    area: int
    cx: float
    cy: float
    hue: int


@dataclass
class Object:
    frags: list[Fragment]

    @property
    def n(self) -> int:
        return len(self.frags)

    @property
    def area(self) -> int:
        return sum(f.area for f in self.frags)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        x0 = min(f.x for f in self.frags)
        y0 = min(f.y for f in self.frags)
        x1 = max(f.x + f.w for f in self.frags)
        y1 = max(f.y + f.h for f in self.frags)
        return x0, y0, x1, y1

    @property
    def extent(self) -> int:
        """Longest side of the object's bounding box, in widget pixels."""
        x0, y0, x1, y1 = self.bbox
        return max(x1 - x0, y1 - y0)

    @property
    def fill(self) -> float:
        x0, y0, x1, y1 = self.bbox
        return self.area / float(max(1, (x1 - x0) * (y1 - y0)))

    @property
    def centroid(self) -> tuple[float, float]:
        a = float(max(1, self.area))
        return (sum(f.cx * f.area for f in self.frags) / a,
                sum(f.cy * f.area for f in self.frags) / a)

    @property
    def hue(self) -> int:
        """Area-weighted median hue of the LARGEST fragment.

        Not of the whole object: an ally's cone and its ring differ, and the
        identity lives in the biggest piece.
        """
        return max(self.frags, key=lambda f: f.area).hue


def segment(crop: np.ndarray, floor: np.ndarray) -> list[Fragment]:
    """Everything saturated drawn on the opaque slab. ONE pass, no gates.

    Deliberately ungated beyond a noise floor: the size and shape filters that
    each detector applies privately are what threw away the evidence that two
    blobs were one object, so they belong AFTER grouping, not before it.
    """
    sc = widget_scale(crop.shape[1])
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    m = (floor & (hsv[:, :, 1] > SAT_MIN)
         & (hsv[:, :, 2] > VAL_MIN)).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    lo = max(3, int(round(FRAG_MIN_AREA * sc * sc)))
    out = []
    for k in range(1, n):
        if st[k, 4] < lo:
            continue
        out.append(Fragment(int(st[k, 0]), int(st[k, 1]), int(st[k, 2]),
                            int(st[k, 3]), int(st[k, 4]),
                            float(cen[k][0]), float(cen[k][1]),
                            int(np.median(hsv[:, :, 0][lab == k]))))
    return out


def group(frags: list[Fragment], scale: float = 1.0,
          gap_px: int = GAP_PX) -> list[Object]:
    """Fragments whose boxes come within `gap_px` are one object.

    Union-find over inflated bounding boxes. Boxes rather than pixels because
    an ally's cone touches its ring only at a corner, and a pixel-distance rule
    that reaches round that corner also reaches the next icon.
    """
    g = max(2, int(round(gap_px * scale)))
    parent = list(range(len(frags)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for i, fi in enumerate(frags):
        for j in range(i + 1, len(frags)):
            fj = frags[j]
            if (fi.x - g < fj.x + fj.w and fj.x - g < fi.x + fi.w
                    and fi.y - g < fj.y + fj.h and fj.y - g < fi.y + fi.h):
                union(i, j)
    buckets: dict[int, list[Fragment]] = {}
    for i, f in enumerate(frags):
        buckets.setdefault(find(i), []).append(f)
    return [Object(v) for v in buckets.values()]


def objects_at(crop: np.ndarray, floor: np.ndarray) -> list[Object]:
    return group(segment(crop, floor), widget_scale(crop.shape[1]))


# --------------------------------------------------------------------- scoring

#: The by-eye labels from `ping_match_eval`, same order as the stored events.
#: CLAUDE-PROVENANCE: these falsify, they do not license a threshold.
TRUTH_587c15b07779 = (
    ["ally"] * 6 + ["p"] + ["ally"] * 3 + ["p"] + ["ally"] * 2
    + ["world", "ally", "world", "world", "world", "p", "icon", "xmark",
       "bar", "p", "ally", "icon", "p", "p", "icon", "xmark", "p", "p"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--gap", type=int, default=GAP_PX,
                    help="fragment grouping distance, widget px")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--against-pings", action="store_true",
                    help="score object features against ping_match_eval's labels")
    a = ap.parse_args(argv)

    store = Store()
    man = store.read_manifest(a.session)
    src = man["source"]
    prof = get_profile(man["source_profile"])
    box = minimap_roi_px(prof, int(src["width"]), int(src["height"]))
    x0, y0, x1, y1 = box
    floor = floor_mask(store.read_static_map(a.session))
    rows = store.read_events("ping", a.session)
    truth = globals().get(f"TRUTH_{a.session}")
    if not rows:
        raise SystemExit(f"no ping events -- run `reticle scan {a.session}`")
    if truth and len(truth) != len(rows):
        print(f"! {len(rows)} events against {len(truth)} labels -- orphaned")
        truth = None

    from reticle.decode import sample_at

    frames = {}
    for s in sample_at(src["path"], sorted(r["t_ms"] + 1000 for r in rows),
                       float(src["fps"])):
        frames[round(s.t_ms / 1000.0, 1)] = s.frame[y0:y1, x0:x1].copy()

    by: dict[str, list[Object]] = {}
    print(f"gap        {a.gap} px")
    if not a.quiet:
        print(f"{'#':>3} {'kind':<14}{'truth':<7}{'nfrag':>6}{'extent':>8}"
              f"{'area':>7}{'fill':>7}{'hue':>5}")
    n_obj_total = 0
    for i, r in enumerate(rows):
        f = frames.get(round((r["t_ms"] + 1000) / 1000.0, 1))
        if f is None:
            continue
        objs = group(segment(f, floor), widget_scale(f.shape[1]), a.gap)
        n_obj_total = max(n_obj_total, len(objs))
        # the object containing the ping detector's blob
        o = min(objs, key=lambda o: (o.centroid[0] - r["x"]) ** 2
                + (o.centroid[1] - r["y"]) ** 2)
        cx, cy = o.centroid
        if (cx - r["x"]) ** 2 + (cy - r["y"]) ** 2 > 40 ** 2:
            continue
        cls = truth[i] if truth else "?"
        by.setdefault(cls, []).append(o)
        if not a.quiet:
            print(f"{i:>3} {r['kind']:<14}{cls:<7}{o.n:>6}{o.extent:>8}"
                  f"{o.area:>7}{o.fill:>7.2f}{o.hue:>5}")

    print()
    print(f"{'class':<8}{'n':>4}{'nfrag':>14}{'extent':>16}{'area':>16}{'fill':>14}")
    for cls, v in sorted(by.items()):
        def rng(fn):
            s_ = sorted(fn(o) for o in v)
            return f"{s_[0]}-{s_[-1]}"
        fills = sorted(o.fill for o in v)
        print(f"{cls:<8}{len(v):>4}{rng(lambda o: o.n):>14}"
              f"{rng(lambda o: o.extent):>16}{rng(lambda o: o.area):>16}"
              f"{f'{fills[0]:.2f}-{fills[-1]:.2f}':>14}")

    if truth:
        pings = by.get("p", [])
        allies = by.get("ally", [])
        if pings and allies:
            print()
            for name, fn in (("n_fragments", lambda o: o.n),
                             ("extent", lambda o: o.extent),
                             ("area", lambda o: o.area)):
                p_ = sorted(fn(o) for o in pings)
                a_ = sorted(fn(o) for o in allies)
                sep = p_[-1] < a_[0] or a_[-1] < p_[0]
                print(f"{name:<14} ping {p_[0]}-{p_[-1]}   ally {a_[0]}-{a_[-1]}"
                      f"   SEPARATES: {sep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
