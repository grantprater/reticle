r"""Mine the icon inventory: propose objects with no colour key, then cluster them.

    .\.venv\Scripts\python.exe prototypes\mine_icons.py c40d950031bb \
        --from-s 150 --to-s 900 --hz 2 --sheet out.png

What this is, and what it replaces
------------------------------------
`docs/MINIMAP_APPEARANCE_MATCHING.md` says to mine exemplars from independently
anchored windows and, until now, never said how -- so every icon this repo can
read got a hand-written detector for its own visual family, and every family
without one is invisible. This is the general instrument those detectors were
standing in for: propose everything drawn, then let the clusters be the classes.

**A class-specific detector is a candidate CHANNEL of this, never the reader.**
`ability_disc`'s black-hat is scale-selective where the proposal step here is
not, so it may earn a place as a second channel whose proposals join the pool.
What it must not be is the answer, because then the next icon family needs its
own detector and the one after that needs another.

The four steps
---------------
1. **Propose.** `minimap_occlusion.foreign_fraction` already asks, per pixel,
   whether the grey leaves the map's measured `[lo_gray, hi_gray]` band --
   *something is drawn here* -- and then reduces it to a scalar and throws the
   mask away. The mask is the proposer. It runs inside the OPAQUE SLAB only:
   outside it the widget is see-through and the live world bleeds in, which is
   the documented cause of reading scenery as icons.

2. **Subtract what is always there.** Accumulate a per-pixel foreign RATE over
   the session. A pixel foreign in most frames is furniture or a geometry
   error, not an entity -- `doctor` reports that furniture as a standing
   finding. This calibrates off the corpus instead of off a chosen level, and
   it is what removes the bulk of the proposal tail.

3. **Describe.** `minimap_appearance.describe` gives an upright 11x11
   masked-luma interior with a contrast check. Mining passes an EMPTY colour
   mask: the point is to presume nothing about which key an object belongs to.

4. **Cluster, and relate.** Leader clustering on masked NCC. The clusters are
   the classes. Then test each pair of cluster medoids for the transformations
   the widget actually uses -- a 180-degree rotation above all -- so *the spike
   inverts* [domain:minimap/spike-inversion] comes out as a DISCOVERED
   relation between two clusters
   rather than a sentence someone had to supply.

Why the loose proposer is correct here
----------------------------------------
The proposal count exceeds the real icon count per frame and much of the excess
is furniture. That would be fatal in a reader and is fine in a miner: a
detector needs per-frame precision, a miner needs RECURRENCE. Artwork repeats
across thousands of frames with a consistent appearance and speckle does not,
so junk never forms a cluster. It is the one place in this pipeline where a
loose proposer is the right instrument, and it is why mining must not be built
out of the readers.

What it cannot do
------------------
It produces CLASSES, not names. A one-word name per cluster, or an anchoring
event, is what turns a cluster into a thing -- see the plan's step 5. It also
inherits the standing rule [domain:minimap/coincident-icons], so a
cluster of overlapping pairs is a real class and not a defect.

Diagnostic only. It labels nothing and changes no reader.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle import geometry  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.minimap import (minimap_roi_px, slab_mask, widget_scale)  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from minimap_appearance import (GRID, appearance_similarity, describe)  # noqa: E402

#: Grey margin on the lighting band. Swept in `object_proposals.py`; the middle
#: value is taken here because mining tolerates a loose proposer by design.
MARGIN = 10.0

#: Icon areas in reference px, scaled by the widget. Regions are a separate
#: family and are deliberately not proposed here -- which is the tension in the
#: cap, because a region's extent overlaps an ability's.
#:
#: Re-measured 2026-09-10 against independent human extent labels:
#: [domain:minimap/icon-extent-by-family]. The old cap of 400 is a disc 22.6 px
#: across, so it sat below the ability family's median and bounded at most 59%
#: of 233 labelled icons -- fitted where the evidence was, on players, then
#: applied to a miner whose purpose is the families with no detector. 500 is the
#: knee: 82% of icons bounded against 14% of regions admitted, before 600 admits
#: 62% of them. Those labels are right-censored at 40 px, so they justify a floor
#: under the cap and cannot bound its top.
ICON_AREA_REF = (10, 500)

#: A pixel foreign in more than this share of sampled frames is FURNITURE. Not
#: fitted: an entity that sat still for most of a session would not be an
#: entity, and the two populations are meant to be far apart rather than close.
STATIC_RATE = 0.5

#: Leader-clustering admission on masked NCC. Reported with a sweep rather than
#: defended: the useful output is how the cluster count moves with it.
JOIN = 0.60

#: A cluster with fewer members than this is not recurrence.
MIN_MEMBERS = 8


def proposal_components(grey, lo, hi, slab, static):
    """All residual components before the icon-area decision.

    Keeping the rejected components is necessary to measure acquisition: a
    missed painted icon can have no residual support, fragmented support, or a
    component rejected for size.  Returning only accepted centroids made those
    failures indistinguishable.
    """
    foreign = ((grey < lo - MARGIN) | (grey > hi + MARGIN)) & slab & ~static
    n, lbl, st, cen = cv2.connectedComponentsWithStats(foreign.astype(np.uint8), 8)
    components = []
    for i in range(1, n):
        components.append({
            "id": i,
            "cx": float(cen[i][0]),
            "cy": float(cen[i][1]),
            "area": int(st[i, cv2.CC_STAT_AREA]),
            "bbox": [int(st[i, cv2.CC_STAT_LEFT]),
                     int(st[i, cv2.CC_STAT_TOP]),
                     int(st[i, cv2.CC_STAT_WIDTH]),
                     int(st[i, cv2.CC_STAT_HEIGHT])],
        })
    return components, foreign, lbl


#: Opening element that cuts a NECK. The channel exists because of
#: [domain:minimap/icon-welding]: the area gate was rejecting an icon for its
#: neighbour's extent. Three px is the smallest element that cuts a two px
#: neck; it is a geometric floor, not a fit.
NECK = 3

#: Distance-transform floor for a CORE proposal, in reference px, scaled by the
#: widget. An icon's filled disc has an inradius near the seven reference px the
#: painter marks, so a floor of four admits any core eight px across and rejects
#: wires and sheet edges. On the RAW mask this channel is worthless, and
#: [domain:minimap/icon-residual-is-a-ring] is why. Fill the holes first.
CORE_REF = 4.0

#: Non-max suppression radius between core proposals, in px. Two icons may be
#: [domain:minimap/coincident-icons], so this bounds candidate volume rather
#: than asserting that objects cannot touch.
CORE_SPACING = 6


def fill_holes(mask):
    """Close the enclosed background of a residual mask.

    A background component touching no border is a hole, and an icon's mid-grey
    interior is one [domain:minimap/icon-residual-is-a-ring]. Filling turns the
    ring into the disc the icon actually is.
    """
    inverse = (~mask).astype(np.uint8)
    # 4-connectivity for the BACKGROUND, and it is the whole trick: an
    # 8-connected outline seals a 4-connected interior, while an 8-connected
    # background leaks diagonally through any one px ring and fills nothing.
    n, lbl = cv2.connectedComponents(inverse, connectivity=4)
    border = set(np.unique(np.concatenate(
        [lbl[0], lbl[-1], lbl[:, 0], lbl[:, -1]])).tolist())
    out = mask.copy()
    for i in range(1, n):
        if i not in border:
            out |= lbl == i
    return out


def neck_components(foreign, neck=NECK):
    """Residual components after the necks are cut. Same contract as above."""
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (neck, neck))
    opened = cv2.morphologyEx(foreign.astype(np.uint8), cv2.MORPH_OPEN, element)
    n, lbl, st, cen = cv2.connectedComponentsWithStats(opened, 8)
    components = []
    for i in range(1, n):
        components.append({
            "id": i,
            "cx": float(cen[i][0]),
            "cy": float(cen[i][1]),
            "area": int(st[i, cv2.CC_STAT_AREA]),
            "bbox": [int(st[i, cv2.CC_STAT_LEFT]),
                     int(st[i, cv2.CC_STAT_TOP]),
                     int(st[i, cv2.CC_STAT_WIDTH]),
                     int(st[i, cv2.CC_STAT_HEIGHT])],
        })
    return components, opened.astype(bool), lbl


def core_proposals(foreign, scale, floor_ref=CORE_REF, spacing=CORE_SPACING):
    """Centres of compact cores in the hole-filled residual.

    This is the channel that survives an icon being CONNECTED to extended art:
    it asks where the mask is locally thick rather than how large the component
    is, so a viewcone welded to a spycam costs the cone, not the spycam.
    """
    filled = fill_holes(foreign)
    dt = cv2.distanceTransform(filled.astype(np.uint8), cv2.DIST_L2, 5)
    peak = cv2.dilate(dt, np.ones((5, 5), np.uint8))
    floor = max(3.0, floor_ref * scale)
    ys, xs = np.nonzero((dt >= peak - 1e-6) & (dt >= floor))
    kept = []
    for i in np.argsort(-dt[ys, xs]):
        y, x = int(ys[i]), int(xs[i])
        if all((y - ky) ** 2 + (x - kx) ** 2 > spacing ** 2 for ky, kx in kept):
            kept.append((y, x))
    return [{"id": i + 1, "cx": float(x), "cy": float(y),
             "area": int(round(np.pi * dt[y, x] ** 2)), "dt": float(dt[y, x])}
            for i, (y, x) in enumerate(kept)], filled


#: The acquisition pool, scored in `proposal_audit.py`. It is a UNION, so
#: adding a channel can only raise recall. On d95cfad5693a `core` alone reaches
#: 100% recall at 66.7% precision and 6 proposals per frame against `base`'s
#: 77.1% and 43 per frame -- and `base` is kept anyway, for a MEASURED reason:
#: [domain:minimap/dim-devices-defeat-the-residual]. `core` needs a
#: substantially filled disc; `base`'s area-gated centroid survives the sparse
#: speckle a dim device leaves, which is what finds seven of a06f04a0059f's ten.
#: Whether such a miss MATTERS is an OWNERSHIP question, not a detector one:
#: [domain:minimap/dim-first-only-for-enemies].
POOL = ("base", "neck", "core")


def propose(grey, lo, hi, slab, static, lo_a, hi_a, scale=1.0, pool=POOL):
    """Accepted icon-band centroids, preserving the original miner contract.

    `base` is the original one-centroid-per-component channel.  `neck` cuts the
    thin welds first, `core` asks where the hole-filled mask is thick; both
    exist because 12 of 14 audited misses were one icon on one component the
    area band rejected for a NEIGHBOUR's extent.
    """
    components, foreign, _lbl = proposal_components(grey, lo, hi, slab, static)
    out = []
    if "base" in pool:
        for component in components:
            if lo_a <= component["area"] <= hi_a:
                out.append((component["cx"], component["cy"], component["area"]))
    if "neck" in pool:
        cut, _opened, _labels = neck_components(foreign)
        for component in cut:
            if lo_a <= component["area"] <= hi_a:
                out.append((component["cx"], component["cy"], component["area"]))
    if "core" in pool:
        cores, _filled = core_proposals(foreign, scale)
        out.extend((c["cx"], c["cy"], c["area"]) for c in cores)
    return out, foreign


def cluster(items, join=JOIN):
    """Leader clustering: join the first cluster whose leader is close enough."""
    clusters: list[dict] = []
    for it in items:
        best, best_s = None, -2.0
        for c in clusters:
            s = appearance_similarity(it["d"], c["leader"])
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s >= join:
            best["members"].append(it)
        else:
            clusters.append({"leader": it["d"], "members": [it]})
    return sorted(clusters, key=lambda c: -len(c["members"]))


#: Members sampled when picking a medoid. The medoid is O(n^2) in the cluster
#: and a recurring class has thousands of members, so an exact one costs more
#: than the decode. A sample is the right exemplar for the same reason the
#: clustering works at all: the class is consistent.
SAMPLE = 48


def medoid(members, rng=None):
    """The member most like all the others -- the cluster's own exemplar."""
    if len(members) == 1:
        return members[0]
    pool = members
    if len(pool) > SAMPLE:
        rng = rng or np.random.default_rng(0)
        pool = [members[i] for i in rng.choice(len(members), SAMPLE, replace=False)]
    best, best_s = pool[0], -2.0
    for a in pool:
        s = sum(appearance_similarity(a["d"], b["d"]) for b in pool) / len(pool)
        if s > best_s:
            best, best_s = a, s
    return best


def rotated(d):
    """The same descriptor turned 180 degrees, for relating two clusters."""
    from minimap_appearance import Descriptor
    return Descriptor(luma=np.rot90(d.luma, 2).copy(),
                      residual=np.rot90(d.residual, 2).copy(),
                      mask=np.rot90(d.mask, 2).copy(), contrast=d.contrast)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--from-s", type=float, required=True)
    ap.add_argument("--to-s", type=float, required=True)
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--join", type=float, default=JOIN)
    ap.add_argument("--sheet", default=None)
    args = ap.parse_args(argv)

    store = Store(args.store)
    manifest = json.loads((Path(args.store) / "manifests" /
                           f"{args.session}.json").read_text(encoding="utf-8"))
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(profile, int(src["width"]), int(src["height"]))
    med = geometry.reference_static(args.session, store.root)
    sd = geometry.stability(args.session, store.root, med.shape[:2])
    slab = slab_mask(med, sd=sd)
    with np.load(geometry.require(args.session, store.root)) as z:
        lo = z["lo_gray"].astype(np.float32)
        hi = z["hi_gray"].astype(np.float32)
    sc = widget_scale(med.shape[1])
    lo_a = max(4, int(round(ICON_AREA_REF[0] * sc * sc)))
    hi_a = int(round(ICON_AREA_REF[1] * sc * sc))
    icon_r = max(3.0, 10.0 * sc)
    empty = np.zeros(med.shape[:2], np.uint8)

    spans = [(args.from_s * 1000.0, args.to_s * 1000.0)]
    frames = []
    for _who, smp in sample_windows(src["path"], float(src["fps"]),
                                    {"mine": (args.hz, spans)}):
        frames.append((smp.t_ms, smp.frame[y0:y1, x0:x1].copy()))
    if not frames:
        raise SystemExit("no frames sampled")

    # Step 2 needs the rate before step 1 can use it, and the decode is the
    # cost -- so hold the sampled crops and walk them twice rather than twice
    # decoding. `--hz` bounds the memory this spends.
    rate = np.zeros(med.shape[:2], np.float64)
    for _t, crop in frames:
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        rate += (((g < lo - MARGIN) | (g > hi + MARGIN)) & slab)
    rate /= len(frames)
    static = rate > STATIC_RATE
    print(f"{len(frames)} frames at {args.hz} Hz; slab {int(slab.sum())} px; "
          f"always-foreign {int(static.sum())} px "
          f"({static.sum() / max(1, slab.sum()) * 100:.1f}% of slab) removed")

    items, n_prop = [], 0
    for t, crop in frames:
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        props, _f = propose(g, lo, hi, slab, static, lo_a, hi_a, sc)
        n_prop += len(props)
        for cx, cy, a in props:
            d = describe(crop, empty, cx, cy, icon_r, lo, hi)
            if d is None:
                continue
            items.append({"t": t, "x": cx, "y": cy, "area": a, "d": d,
                          "crop": crop})
    print(f"{n_prop} proposals, {len(items)} described "
          f"({n_prop / len(frames):.1f} per frame)")

    # Sweep on a subsample. The question is how the cluster count MOVES with
    # the admission, and paying the full pass six times to answer it would cost
    # more than the decode did.
    rng = np.random.default_rng(0)
    sub = (items if len(items) <= 700
           else [items[i] for i in rng.choice(len(items), 700, replace=False)])
    floor = max(2, MIN_MEMBERS * len(sub) // max(1, len(items)))
    print(f"\n{'join':>6s} {'clusters':>9s} {'recurring':>10s} {'in recurring':>13s}"
          f"    (on {len(sub)} sampled proposals, recurring >= {floor})")
    for j in (0.50, 0.60, 0.70):
        cs = cluster(sub, j)
        rec = [c for c in cs if len(c["members"]) >= floor]
        print(f"{j:6.2f} {len(cs):9d} {len(rec):10d} "
              f"{sum(len(c['members']) for c in rec):13d}")

    cs = cluster(items, args.join)
    rec = [c for c in cs if len(c["members"]) >= MIN_MEMBERS]
    print(f"\nat join {args.join}: {len(rec)} recurring clusters "
          f"of {len(cs)}, holding {sum(len(c['members']) for c in rec)} "
          f"of {len(items)} proposals")
    meds = [medoid(c["members"]) for c in rec]
    for i, (c, m) in enumerate(zip(rec, meds)):
        xs = [it["x"] for it in c["members"]]
        ys = [it["y"] for it in c["members"]]
        spread = float(np.hypot(np.std(xs), np.std(ys)))
        print(f"   cluster {i:2d}  n={len(c['members']):4d}  "
              f"medoid ({m['x']:5.1f},{m['y']:5.1f})  position spread {spread:6.1f} px  "
              f"contrast {m['d'].contrast:5.1f}")

    # Step 4: relate. A 180-degree rotation is the widget transformation this
    # repo has a stated case for -- the spike's ground and carried states.
    print("\ncluster pairs related by a 180-degree ROTATION "
          "(upright similarity -> rotated similarity):")
    found = False
    for i in range(len(meds)):
        for j in range(i + 1, len(meds)):
            up = appearance_similarity(meds[i]["d"], meds[j]["d"])
            rot = appearance_similarity(rotated(meds[i]["d"]), meds[j]["d"])
            if rot > up + 0.15 and rot >= 0.5:
                found = True
                print(f"   {i:2d} <-> {j:2d}   upright {up:5.2f}  rotated {rot:5.2f}")
    if not found:
        print("   none: no pair is better explained turned over than upright")

    if args.sheet and rec:
        _sheet(rec, meds, icon_r, args.sheet)
        print(f"\n{args.sheet}")
    return 0


def _sheet(rec, meds, icon_r, path):
    """Six members per cluster, at source resolution, magnified."""
    half, zoom, per = int(round(icon_r * 1.6)), 10, 6
    rows = []
    for c, m in zip(rec, meds):
        pick = [m] + [it for it in c["members"] if it is not m][:per - 1]
        tiles = []
        for it in pick:
            cx, cy = int(round(it["x"])), int(round(it["y"]))
            crop = it["crop"]
            p = crop[max(0, cy - half):cy + half + 1, max(0, cx - half):cx + half + 1]
            if p.size == 0:
                continue
            big = cv2.resize(p, ((2 * half + 1) * zoom, (2 * half + 1) * zoom),
                             interpolation=cv2.INTER_NEAREST)
            tiles.append(cv2.copyMakeBorder(big, 2, 2, 2, 2,
                                            cv2.BORDER_CONSTANT, value=(40, 40, 40)))
        if not tiles:
            continue
        h = max(t.shape[0] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0,
                                    cv2.BORDER_CONSTANT, value=(40, 40, 40))
                 for t in tiles]
        band = np.hstack(tiles)
        lab = np.full((22, band.shape[1], 3), 25, np.uint8)
        cv2.putText(lab, f"n={len(c['members'])}", (6, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (225, 225, 225), 1)
        rows.append(np.vstack([lab, band]))
    if not rows:
        return
    w = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 0, 0, w - r.shape[1],
                               cv2.BORDER_CONSTANT, value=(25, 25, 25)) for r in rows]
    cv2.imwrite(path, np.vstack(rows))


if __name__ == "__main__":
    raise SystemExit(main())
