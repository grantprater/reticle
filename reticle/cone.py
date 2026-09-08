r"""The vision cone as pure geometry: raycast a wedge, union the wedges.

    python -m reticle.cone --self-test

**This module owns no colour, no threshold and no detector.** It takes an
origin, a bearing and a passability map and returns which pixels a ray can
reach. That is deliberate and it is what makes the cone cheap: once origin and
facing are known the mask is a property of the MAP, not of the recording, so
none of the reference-drift that broke every diff-based channel here applies
to it. Where the origin and bearing come from is `minimap.fit_ring`'s problem.

Promoted from `prototypes/minimap_cone.cone_mask` on 2026-09-06, which now
imports it back rather than keeping a copy -- `floor_mask` was forked for ten
days by promotion-by-copy and the two definitions silently diverged.

Two changes were made in the move, and both are corrections
------------------------------------------------------------
**`passable` and `visible` are separate masks.** The original took
`(labels, floor)` and skipped `BOXEDGE` pixels so a ray would pass a low box
-- but it then marked that pixel lit anyway, while the stated domain fact is
that the cone *does not illuminate boxes*. Passing through and being seen are
different questions, so they are different arguments.

**A BOX STOPS THE RAY. Corrected 2026-09-07 by the recorder, who plays the
game: sight terminates at walls AND at boxes, it does not pass them.** The
composition here was `floor | (labels == BOXEDGE)`, which is a no-op --
`BOXEDGE` is already inside `floor_mask`, so boxes were passable *and* lit,
which is neither the old intent nor the truth. Whether to terminate the ray or
to cull the lit pixel afterwards is an implementation choice; terminating is
free, because `raycast` already stops at the first impassable pixel and does
not mark it.

Measured over ~48 frames on each painted map, against the two-state lit mask,
changing only this:

    occluder                 ascent prec / over-claim   lotus prec / over-claim
    floor | BOXEDGE (was)        15.9%   4.36x              19.8%   3.27x
    floor & ~BOXEDGE (is)        33.5%   1.27x              35.4%   1.60x

Recall falls with it, 67% to 43% on Ascent, and that is NOT yet understood --
`BOXEDGE` is a 1-2 px line and may be sealing doorways it should not. Use
`passable_from`, so there is one composition rather than one per caller.

**It is vectorised, and that was not optional.** The loop version is ~10^5
Python iterations per cone; five icons at 15 Hz over a 39-minute session is
~10^10, which is not a performance note, it is the difference between minutes
and days. `_raycast_loop` is kept as the reference and `--self-test` asserts
the two agree exactly, including on a real geometry npz -- the promoted-by-copy
lesson says an unchecked reimplementation is a fork waiting to happen.

Under-claiming is the design rule, not a preference
-----------------------------------------------------
Every enemy-half invariant in the entity model (doc SS11) is written in terms
of the observable area, and they all have the shape *an enemy cannot originate
inside it*. So an area that is too LARGE silently discards legitimate enemy
observations, which is the recall loss this project keeps paying for, while an
area that is too small only fails to fire. Hence: boxes block sight, a refused
facing produces no cone rather than a guessed one, and callers are expected to
keep interpolated bearings out of the aggregate by default.

On reducing over time
---------------------
`observable` answers *what can the team see at this instant*, which is the
question the interior-appearance invariant asks. A window has two honest
reductions and they are not interchangeable -- the union over frames
over-claims (anything anyone glanced at) and the intersection under-claims
(held the whole window). This module refuses to pick: `reduce_window` returns
both, because "THE AGGREGATE IS THE MEASUREMENT" has already inverted three
results in this repo by choosing one silently.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

#: Half-angle of a player's cone, degrees. **51.5, i.e. 103 degrees full.**
#:
#: This repo measured the cone directly over 23 open-space samples on one
#: Ascent clip and got a half-angle of **50-65 degrees** across a run of seven
#: consecutive samples (`prototypes/minimap_cone.py` has the method and the
#: stated exclusions); 56 was the midpoint of that range.
#:
#: Valorant's field of view is reported to be FIXED AT 103 DEGREES, and 103/2 =
#: 51.5 sits inside the measured band, near its low end. Three reasons to
#: prefer it over the midpoint: a round engine constant is a better estimate
#: than the centre of a noisy interval; it is consistent with the direct
#: measurement rather than in tension with it; and it is NARROWER, so it
#: under-claims -- which is this module's standing rule, because an observable
#: area that is too large silently discards real enemy observations.
#:
#: **Provenance is a web search, not a measurement here, and that is stated
#: rather than hidden.** An attempt to confirm it independently -- fitting
#: pixels-per-degree from camera pan, where 103 predicts 13.33 px/deg and 112
#: predicts 11.30 -- FAILED for an unrelated reason and settled nothing; see
#: `prototypes/cone_flip.py`. Treat 103 as the better-supported hypothesis, not
#: as established.
#:
#: Not universal to every cone on the widget: Killjoy's turret is 100 degrees
#: full from the ability reference, so a deployable takes its own value.
CONE_HALF_ANGLE_DEG = 51.5

#: Rays per cone. 240 over ~112 degrees is a ray every 0.47 degrees, which at
#: the widget's ~230 px half-diagonal is under 2 px of arc at the far edge --
#: fine enough that a doorway cannot fall between two rays.
N_RAYS = 240


def passable_from(labels: np.ndarray, floor: np.ndarray) -> np.ndarray:
    """The grid a ray may travel through: the floor, minus the boxes.

    One definition, because two callers composing this by hand is how the
    `floor_mask` fork started. `visible` stays `floor`: a box stops sight and
    is not itself lit, which `raycast` gives for free by not marking the pixel
    it dies on.
    """
    from .minimap import BOXEDGE
    return floor & ~(labels == BOXEDGE)


def raycast(passable: np.ndarray, cx: float, cy: float, facing_deg: float,
            half_angle_deg: float = CONE_HALF_ANGLE_DEG,
            visible: np.ndarray | None = None,
            n_rays: int = N_RAYS, max_r: int | None = None) -> np.ndarray:
    """Pixels a ray from (cx, cy) reaches within the wedge. Vectorised.

    `passable` says where a ray may CONTINUE; `visible` (default: `passable`)
    says which of the pixels it passes are actually lit. A ray stops at the
    first impassable pixel and does not mark it -- a wall is not seen, it is
    what stops sight.

    Angles are degrees, measured the way `cv2`/image coordinates run: 0 is +x,
    and +90 is DOWN the image, because y grows downward. `fit_ring`'s facing
    uses the same convention, so a bearing can be passed straight through.
    """
    h, w = passable.shape
    if visible is None:
        visible = passable
    if max_r is None:
        max_r = max(h, w)
    if not (0 <= int(round(cx)) < w and 0 <= int(round(cy)) < h):
        return np.zeros((h, w), dtype=bool)

    half = np.radians(half_angle_deg)
    facing = np.radians(facing_deg)
    # `n_rays - 1` divisions so both edges of the wedge are sampled, matching
    # the loop reference exactly rather than approximately.
    th = facing - half + (2 * half) * np.arange(n_rays) / (n_rays - 1)
    s = np.arange(int(max_r), dtype=np.float64)          # step 0 IS the origin

    xs = cx + np.cos(th)[:, None] * s[None, :]
    ys = cy + np.sin(th)[:, None] * s[None, :]
    xi = np.rint(xs).astype(np.int64)
    yi = np.rint(ys).astype(np.int64)

    inb = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    # Clip only so the gather is legal; `inb` is what decides, and an
    # out-of-bounds step is impassable so the ray dies there.
    xc = np.clip(xi, 0, w - 1)
    yc = np.clip(yi, 0, h - 1)

    step_ok = passable[yc, xc] & inb
    # A ray is alive at step k only if EVERY step up to k was passable. This
    # is the whole raycast -- the running AND is what "stops at the first
    # wall" means, and it is why no loop is needed.
    alive = np.logical_and.accumulate(step_ok, axis=1)
    lit = alive & visible[yc, xc]

    mask = np.zeros((h, w), dtype=bool)
    mask[yc[lit], xc[lit]] = True
    return mask


def _raycast_loop(passable, cx, cy, facing_deg,
                  half_angle_deg=CONE_HALF_ANGLE_DEG, visible=None,
                  n_rays=N_RAYS, max_r=None):
    """The reference implementation. Kept ONLY so `--self-test` can check the
    vectorised one against it; nothing should call this for real work.
    """
    h, w = passable.shape
    if visible is None:
        visible = passable
    if max_r is None:
        max_r = max(h, w)
    mask = np.zeros((h, w), dtype=bool)
    facing = np.radians(facing_deg)
    half = np.radians(half_angle_deg)
    for i in range(n_rays):
        theta = facing - half + (2 * half) * i / (n_rays - 1)
        dx, dy = np.cos(theta), np.sin(theta)
        for k in range(int(max_r)):
            xi = int(round(cx + dx * k))
            yi = int(round(cy + dy * k))
            if not (0 <= xi < w and 0 <= yi < h) or not passable[yi, xi]:
                break
            if visible[yi, xi]:
                mask[yi, xi] = True
    return mask


def observable(passable: np.ndarray, icons, *,
               half_angle_deg: float = CONE_HALF_ANGLE_DEG,
               visible: np.ndarray | None = None,
               n_rays: int = N_RAYS, max_r: int | None = None):
    """The collective team viewcone: the union of every icon's cone.

    `icons` is an iterable of `(cx, cy, facing_deg)`, or of
    `(cx, cy, facing_deg, half_angle_deg)` where one emitter's field of view
    differs -- a Killjoy turret is 100 degrees full against a player's ~112,
    so the per-icon override is there rather than as a second function.

    Returns `(mask, per_icon)`. `per_icon` is the list of individual masks in
    the order given, because the aggregate alone cannot say WHICH teammate
    saw a pixel and the origin-event model needs that attribution.

    An icon whose facing is None contributes NOTHING and is not an error: a
    refused bearing is the honest answer and guessing one would inflate the
    area in exactly the direction that costs recall.
    """
    if visible is None:
        visible = passable
    per_icon = []
    for icon in icons:
        cx, cy, deg = icon[0], icon[1], icon[2]
        half = icon[3] if len(icon) > 3 else half_angle_deg
        # `track.Tracker.bearings()` returns (x, y, deg, INTERPOLATED) and this
        # function's fourth element is a HALF-ANGLE, so the two APIs collide in
        # a way nothing catches: `half=False` is a legal number and casts a
        # zero-width cone. It happened on the day both were written, and the
        # symptom was an observable area of 0.4% rather than an exception.
        if isinstance(half, bool):
            raise TypeError(
                "observable() got a bool as an icon's half-angle -- this is "
                "almost certainly track.Tracker.bearings()'s `interpolated` "
                "flag. Pass (cx, cy, facing) triples.")
        if deg is None:
            per_icon.append(np.zeros(passable.shape, dtype=bool))
            continue
        per_icon.append(raycast(passable, cx, cy, deg, half, visible,
                                n_rays=n_rays, max_r=max_r))
    if per_icon:
        mask = np.logical_or.reduce(per_icon)
    else:
        mask = np.zeros(passable.shape, dtype=bool)
    return mask, per_icon


def coverage(mask: np.ndarray, floor: np.ndarray) -> float:
    """Share of the walkable floor the mask covers. The headline number."""
    n = int(floor.sum())
    return float((mask & floor).sum()) / n if n else 0.0


def reduce_window(masks):
    """Both honest reductions of a run of per-frame areas: `(union, held)`.

    Union is "anyone looked here at some point in the window" and it
    OVER-claims; the intersection is "the team held this the whole window" and
    it UNDER-claims. Which one a claim rests on has to be said out loud --
    choosing an aggregate silently has inverted three results in this repo.
    """
    masks = list(masks)
    if not masks:
        return None, None
    return np.logical_or.reduce(masks), np.logical_and.reduce(masks)


def _self_test() -> int:
    ok = True

    def check(label, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {label}: got {got!r}, want {want!r}")
        else:
            print(f"  ok   {label}: {got}")

    rng = np.random.default_rng(20260906)

    # -- the vectorised cast must equal the loop, which is the only thing
    #    stopping this promotion becoming another silent fork.
    worst = 0
    for trial in range(12):
        h, w = 60, 70
        p = rng.random((h, w)) > 0.18
        cy, cx = 30.0, 35.0
        p[int(cy) - 3:int(cy) + 4, int(cx) - 3:int(cx) + 4] = True
        deg = float(rng.uniform(0, 360))
        a = raycast(p, cx, cy, deg, 56.0)
        b = _raycast_loop(p, cx, cy, deg, 56.0)
        worst = max(worst, int((a ^ b).sum()))
    check("vectorised == loop over 12 random maps", worst, 0)

    # -- `visible` narrows the mask without shortening the ray. An open room
    #    with a stripe that is passable-but-unlit: the far side must still be
    #    reached, which is exactly the box case.
    p = np.ones((41, 41), dtype=bool)
    v = p.copy()
    v[:, 25:28] = False                      # a low box: see past it, not it
    m = raycast(p, 20, 20, 0.0, 56.0, visible=v)
    check("a box is passed but not lit", bool(m[20, 26]), False)
    check("the floor beyond the box is still seen", bool(m[20, 33]), True)
    blocked = raycast(np.where(v, p, False), 20, 20, 0.0, 56.0)
    check("and blocking it instead stops the ray", bool(blocked[20, 33]), False)

    # -- a wall stops the ray and is NOT itself marked.
    p2 = np.ones((41, 41), dtype=bool)
    p2[:, 30] = False
    m2 = raycast(p2, 20, 20, 0.0, 56.0)
    check("the wall pixel is not lit", bool(m2[20, 30]), False)
    check("nothing past the wall is lit", bool(m2[20, 35:].any()), False)
    check("the floor before it is", bool(m2[20, 29]), True)

    # -- the wedge is a wedge: nothing behind the origin.
    m3 = raycast(np.ones((41, 41), dtype=bool), 20, 20, 0.0, 56.0)
    check("nothing is seen behind the icon", bool(m3[20, :19].any()), False)
    check("the facing direction is seen", bool(m3[20, 30]), True)

    # -- an off-map origin returns empty rather than raising.
    check("an origin outside the widget yields nothing",
          int(raycast(np.ones((10, 10), dtype=bool), 99, 99, 0.0).sum()), 0)

    # -- the union is the union, and a None facing contributes nothing.
    p4 = np.ones((41, 41), dtype=bool)
    agg, per = observable(p4, [(20, 20, 0.0), (20, 20, 180.0)])
    check("two opposed cones cover more than one",
          int(agg.sum()) > int(per[0].sum()), True)
    agg2, per2 = observable(p4, [(20, 20, 0.0), (20, 20, None)])
    check("a refused facing adds no area", int(agg2.sum()), int(per[0].sum()))
    check("but it still gets a slot, so attribution stays positional",
          len(per2), 2)

    # -- a per-icon half-angle override is honoured (the turret case).
    wide, _ = observable(p4, [(20, 20, 0.0, 56.0)])
    narrow, _ = observable(p4, [(20, 20, 0.0, 10.0)])
    check("a narrower emitter sees less", int(narrow.sum()) < int(wide.sum()), True)
    # A bool where the half-angle goes is refused, not silently cast at zero.
    try:
        observable(p4, [(20, 20, 0.0, False)])
        raised = False
    except TypeError:
        raised = True
    check("a bool half-angle raises rather than casting nothing", raised, True)

    # -- both window reductions, and the ordering between them.
    u, held = reduce_window([per[0], per[1]])
    check("union >= intersection", int(u.sum()) >= int(held.sum()), True)
    check("opposed cones share only the origin neighbourhood",
          int(held.sum()) < int(u.sum()), True)

    check("coverage of everything is 1.0", coverage(p4, p4), 1.0)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--bench", metavar="SESSION",
                    help="time the cast against a real geometry npz, and "
                         "check the vectorised path against the loop on it")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.bench:
        return _bench(a.bench)
    ap.print_help()
    return 0


def _bench(session: str) -> int:
    """Equivalence and speed on a REAL map, which random noise cannot stand in
    for: a real floor is one big connected region, so rays run far and the
    accumulate covers thousands of steps rather than dying at step three.
    """
    import time

    from . import geometry
    from .minimap import floor_mask

    z = np.load(geometry.require(session))
    labels, med = z["labels"], z["static"]
    floor = floor_mask(med)
    passable = passable_from(labels, floor)
    ys, xs = np.where(floor)
    rng = np.random.default_rng(7)
    idx = rng.choice(len(ys), 12, replace=False)

    print(f"{session}: widget {floor.shape[1]}x{floor.shape[0]}, "
          f"floor {floor.mean() * 100:.1f}%")
    worst, tv, tl = 0, 0.0, 0.0
    for k in idx:
        cx, cy = float(xs[k]), float(ys[k])
        deg = float(rng.uniform(0, 360))
        t0 = time.perf_counter()
        a = raycast(passable, cx, cy, deg, visible=floor)
        tv += time.perf_counter() - t0
        t0 = time.perf_counter()
        b = _raycast_loop(passable, cx, cy, deg, visible=floor)
        tl += time.perf_counter() - t0
        worst = max(worst, int((a ^ b).sum()))
    n = len(idx)
    print(f"  disagreeing pixels, worst of {n} casts on the real map: {worst}")
    print(f"  vectorised {tv / n * 1000:7.2f} ms/cone")
    print(f"  loop       {tl / n * 1000:7.2f} ms/cone   "
          f"({tl / max(tv, 1e-9):.0f}x slower)")
    # What that means for the thing this is actually for.
    per_frame = 5
    frames = 27757
    print(f"  a 39-min session at 15 Hz ({frames} frames x {per_frame} icons): "
          f"{tv / n * per_frame * frames / 60:.1f} min vectorised, "
          f"{tl / n * per_frame * frames / 3600:.1f} h looped")
    return 0 if worst == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
