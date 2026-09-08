r"""The wiki art's terrain LEVELS, warped into widget pixels and stored.

    .\.venv\Scripts\python.exe prototypes\map_shade.py maps
    .\.venv\Scripts\python.exe prototypes\map_shade.py levels ascent
    .\.venv\Scripts\python.exe prototypes\map_shade.py paint ascent --out a.png
    .\.venv\Scripts\python.exe prototypes\map_shade.py build --all
    .\.venv\Scripts\python.exe prototypes\map_shade.py check --all

Why this exists
---------------
`minimap_geometry`'s `labels` collapses every terrain grey into one flat
`FLOOR`, and `cone_terrain.py` measured what that costs: pixels the art draws a
step lighter than the main floor are called "lit" in over 85% of frames at
about 3x the rate of the main shade. A cone lights a pixel SOMETIMES; a shade
step lights it ALWAYS. A classifier blind to the shade cannot separate them, so
every cone number is limited by it.

This writes the levels the art states into the geometry npz, **additively**.
Nothing existing reads these arrays; `labels`, `static`, `lo_gray`, `hi_gray`
and the two SD maps are untouched, which is deliberate -- `floor_mask` feeds the
shipped self-position track and two independent ground truths validate it, so
changing its geometry source is a re-validation job with its own session.
Adding an array beside it is not.

    shade          uint8   representative art grey at this pixel, 0 off-map
    shade_kind     uint8   VOID / FLOOR / RAMP / SHADOW / LINE / SITE
    shade_step     int8    rungs above the map's base level, within kind
    shade_purity   uint8   255 x the winning class's area share of the pixel
    shade_fit      f4[6]   rot, scale, dx, dy, iou, ncc -- the transform used
    shade_map      str     which art was warped
    shade_built_by str     hash of this file and `wiki_map.py`

`shade` is the level VALUE, so it can be read against the art's own histogram
with no table; `shade_step` is the same fact as an ORDINAL, so a consumer can
say "one step up" without knowing the base is 118. They answer different
questions and both are one byte.

WHAT IS PERMANENT AND WHAT IS PER-SESSION. ANSWERED 2026-09-07, DO NOT RE-ASK
-----------------------------------------------------------------------------
Asked directly -- *once the geometry is built it is permanent and does not have
to be rebuilt for each session, correct?* **Yes for the geometry. No for the
photometry, and they were in one file, which is what made the question worth
asking.** This directory's own "The static map does TWO jobs" says the same
thing from the other end:

    PERMANENT, and now stored as such
      reference/shade/<map>.npz              the art quantised into classes.
                                             Map only. No session, no profile,
                                             no capture -- computable for a map
                                             nobody has ever recorded
      reference/shade/<map>__<profile>.npz   the same, warped into widget
                                             pixels. Map and profile only

    FROM A CAPTURE, and unavoidably so -- one per (map, profile), built from
    that key's reference recording
      static, lo_gray, hi_gray, sd_lo/sd_hi  what THESE pixels look like with
                                             nothing on them. The widget is
                                             semi-transparent over live world,
                                             so no external render can say it

So a key's `shade*` arrays are a **CACHE FILL**, not a derivation: `build`
copies the (map, profile) reference in, and only does real work the first time
a pair is ever placed. Measured over 35 per-session npz it was 13 s with 4 of
them doing any work at all; now that the geometry is keyed the same way, "once
per pair" and "once per npz" are the same sentence.

**And a geometry rebuild no longer drops them.** `minimap_geometry.reattach_shade`
runs after its write and says so out loud when a rebuild loses shade that was
there. It once had two write paths -- a decode and a `--geometry-from` borrow --
and the first version of this paragraph was written after testing only one of
them, which is why the sentence is this specific. Keying geometry per
(map, profile) removed the borrow entirely: there is one write path now, and
`minimap_geometry.py --all` verifies shade coverage after it runs.

**`reticle doctor` now reports it** -- `check_shade`, beside `check_geometry`:
a stale `shade_built_by` and a missing shade are separate WARNs, because the
first is refilled in seconds and the second usually wants a `map:` tag.

**THE SCALE IS A PER-PROFILE CONSTANT; THE OFFSET IS NOT.** Normalising each
fitted scale to a 2048 px art render, over three different maps:

    ascent  bigmap  0.2246        lotus   bigmap  0.2248 / 0.2240
    split   bigmap  0.2238        ascent  16x9    0.1421

A 0.4% spread -- one step of the refine search -- across maps whose art ships at
two different resolutions. The game draws every map at the same metres per
widget pixel, so a map's scale needs no capture. **The four-parameter PLACEMENT
still does**: the canvas centres of the three bigmap fits sit 13 px apart, so
the map is not centred on a fixed widget point and the offset cannot be
predicted. `maps` prints which pairs are placed and which are waiting for their
first capture.

SIX CLASSES, AND THE ART EARNS EVERY ONE
----------------------------------------
Recorded 2026-09-07: *there is a darker gray for the overhang on B site, and I
believe there was lighter gray for high ground in some areas.* Both are in the
art, both were checked before anything was baked, and a level table alone would
have carried only the second:

* **FLOOR** -- terrain on a quantised level. The ladder is derived per map, and
  every map fetched has 118 as its base:

        ascent  118 122 133 136 139 145      split   118 133 138 143
        haven   118 125 131 135 145          sunset  118 133
        lotus   118 133 145                  abyss   118 133 138

  Five rungs of high ground on Ascent, and they are the lighter grey. Painted
  (`map_shade.py paint ascent`) the rungs are CONTIGUOUS REGIONS in sensible
  places -- +4 is one long strip running the length of the map's centre, +5 is
  two large plateaus, +2 is the scatter of small squares where boxes stand --
  which is what says the ladder is elevation and not a histogram artefact. The
  callouts are not named here because nobody has checked them;
* **SHADOW** -- terrain DARKER than the base. **Ascent has exactly one region**,
  4643 px in a single component against a next-largest of 622, and its greys run
  94..114 as a GRADIENT rather than a level. It sits along one edge of a bomb
  site. Haven has one (3054 px, a flat 105) and Abyss a small one (445 px);
  Lotus, Split and Sunset have none at all. **A share threshold drops it** -- it
  is 0.06% of Ascent's art -- so it is kept by being a COHERENT REGION instead,
  which is the property that makes it terrain rather than an edge;
* **RAMP** -- coherent terrain BETWEEN two rungs, 0.45-2.77% per map, largest
  component 2141-12814 px. These are the slopes: a gradient is what a ramp looks
  like drawn flat, and painted they sit along the borders of the raised regions
  exactly where stairs are. The same coherence test is what separates them from
  the antialiasing specks, whose median area is 5 px and which snap to their
  nearest rung instead;
* **LINE** -- the white line-work, which is not terrain and is the brightest
  thing on the widget, so a lit test that does not know about it is reading
  walls. Two things reach it: grey at or above `LINE_MIN`, and a thin off-rung
  region far from any rung -- which is how **Lotus's 186, 4521 px in 106
  components of inscribed radius 2**, gets classed as the wall edging it is
  rather than as high ground 41 greys above the top rung;
* **SITE** -- the bomb sites, with their own ladder. Ascent 148/151, Lotus
  148/152/159/170, Sunset 148/151/154/160 -- sites have elevation too;
* **VOID** -- off the map, from the alpha channel, which is near-binary.

WHAT IT SEPARATES, MEASURED
---------------------------
`a06f04a0059f`, 105 frames, `cone_terrain.py`'s lit-frequency map split by the
stored classes over the 52767 usable pixels the art also covers. A cone lights a
pixel SOMETIMES; a static feature lights it ALWAYS:

    class                    n     always lit (>85%)    sometimes (20-50%)
    FLOOR base           38025           8.1%                  7.7%
    FLOOR +1              1378          14.9%                  4.3%
    FLOOR +2               932          24.5%                  5.4%
    FLOOR +3               769          35.2%                  0.9%
    FLOOR +4              2994          18.8%                  1.8%
    FLOOR +5              1498          35.8%                  0.1%
    RAMP                   915          22.6%                  5.7%
    SHADOW                 322           9.3%                  5.9%
    LINE                   969          21.4%                  2.3%
    SITE                  4965          22.0%                  0.8%

**The artefact rate climbs with the rung and the real cones fall away with it**
-- 7.7% of base-shade pixels are sometimes-lit against 0.1% at +5. **51.9% of
every always-lit pixel is off the base shade**, so over half of what the derived
`FLOOR` calls a cone is now labelled rather than merely counted.

**And the grey-only bucketing is wrong about what it is looking at.**
`cone_terrain.py`'s "two or more steps lighter" bucket, split by class:

    FLOOR   4492 px  42.9%      LINE    969 px   9.3%
    SITE    4965 px  47.5%      RAMP     37 px   0.4%

Nearly half of it is bomb site and a tenth is line-work. The 23.4% it reports is
a real artefact rate for a population that is mostly not elevation.

**SHADOW is the exception and it fails in the other direction**: 9.3%
always-lit, no worse than the base shade, because darker terrain does not read
as lit. What it costs is the sometimes-lit share -- a cone crossing the overhang
is likelier to be missed than invented.

**`shade_purity` earns less than expected and the number is here rather than in
its favour**: boundary pixels (purity < 200) are always-lit 13.7% against the
interior's 12.2%. Real, small, and not a gate worth building on yet.

SATURATION SPLITS SITE FROM TERRAIN, AND IT HAS TO
--------------------------------------------------
The bomb sites are drawn `BGR (118,152,152)`, an olive whose GREY VALUE IS 148
-- and 148 is also a plausible terrain rung. Quantising the warped grey alone
therefore files every bomb site under "two or more steps lighter than the
floor", which is what `cone_terrain.py` does: on Ascent that bucket is 6.1% of
the art while the grey-only histogram has no 148 in it at all, so the bucket is
bomb site, not elevation. The families are split on saturation BEFORE
quantising and each carries its own ladder.

**That split is also this file's independent alignment check, and it is the
strongest evidence here.** The art's SITE class and the derived `labels ==
PLANT` are found by two methods sharing nothing -- an olive in a clean render
against a hue rule fitted to a capture median -- and over four independent
statics on three maps they agree at **87.4-87.9% IoU**, with pixel counts within
3% (Ascent 5243 art against 5247 derived). The alpha fit can only say the
FOOTPRINT lines up; this says the interior does.

WHY EACH CLASS IS WARPED SEPARATELY
-----------------------------------
The art is 2048 px and the widget slab is about 400: a 5x downsample. Warping
the quantised grey with INTER_AREA blends 118 and 148 into 133, inventing a
rung that is not on the map; INTER_NEAREST throws away four pixels in five and
turns the 1 px line-work into noise. So each class is warped as its own
coverage mask under INTER_AREA -- area-weighted, nothing invented -- and the
pixel takes the class with the most coverage. `shade_purity` is that winner's
share, which is what says whether a pixel is interior (one class) or a boundary
(a mixture). A per-pixel test has no business trusting a boundary.

THE FIT IS A PER-(MAP, PROFILE) CONSTANT, TO WITHIN THE SEARCH'S OWN STEP
-------------------------------------------------------------------------
Measured 2026-09-07 over every session with art, while geometry was still
stored per session. Ascent's 29 npz shared ONE static median -- they borrowed
from a single donor -- so their agreeing was not evidence. Lotus had two
INDEPENDENT statics and they landed at scale 0.4495 and 0.4479, dy -62 and -61:
one step apart in every parameter, where the refine searches scale in 0.4% steps
and offset in 2 px. That is the strongest form the claim can take on this
corpus, and the store now takes it as its shape: geometry and fit are both
keyed `<map>__<profile>`, so warping once per key IS warping once per npz.

**Two stored fits were STALE and both were worse than the code's own answer.**
`a06f04a0059f` was cached on 2026-09-05 at IoU 79.9% / NCC 0.530 and recomputes
at 94.6% / 0.752; `5822b6646448` at 94.6% / 0.550 recomputes at 95.4% / 0.659.
An unstamped cache cannot report that, which is the argument for
`shade_built_by`. Every number `cone_terrain.py` published was measured through
the worse of the two Ascent alignments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_map as WM                                             # noqa: E402
from reticle import geometry as G                                 # noqa: E402
from reticle import minimap as M                                  # noqa: E402

STORE = WM.STORE

VOID, FLOOR, RAMP, SHADOW, LINE, SITE = 0, 1, 2, 3, 4, 5
KIND_NAME = {VOID: "VOID", FLOOR: "FLOOR", RAMP: "RAMP",
             SHADOW: "SHADOW", LINE: "LINE", SITE: "SITE"}

#: Above this HSV saturation the art is a bomb site, not terrain. The olive is
#: the ONLY non-grey the art draws -- 4-8% of the opaque pixels on every map
#: fetched -- so this separates two populations with nothing in between rather
#: than cutting one in half.
SAT_MAX = 30

#: At or above this grey the art is line-work, not terrain. Measured gap, per
#: map (highest terrain rung -> lowest line rung): ascent 145->221,
#: split 143->221, sunset 146->221, lotus 186->221, haven 145->230,
#: abyss 186->196. Nothing on any fetched map lands between 196 and 221.
LINE_MIN = 190

#: A grey has to hold this share of its family's INTERIOR to be a rung.
#:
#: Interior, because a plain histogram cannot tell a rung from the antialiasing
#: between two rungs: on Ascent the real rungs hold 0.9-4.5% each and the
#: continuum between them holds 0.24-0.35% at EVERY value from 119 to 138, so a
#: share threshold either invents five rungs or loses 136. A pixel counts as
#: interior when its whole neighbourhood is one grey -- an antialiasing shell
#: is one or two pixels wide and vanishes; a rung is a region and does not.
MIN_SHARE = 0.002

#: Greys this close are the same rung drawn twice (118 and 119 on every map).
MERGE_GAP = 2

#: An off-rung grey is TERRAIN if its region is at least this share of the art
#: and at least `MIN_RADIUS` thick, and it is DRAWING otherwise. Both halves
#: are needed: Lotus's 186 is 1.3% of the grey family in 106 components whose
#: largest inscribed radius is 2 px -- the dim inner edge of the wall line-work
#: -- while Ascent's ramps and its one shadow are single regions 12 to 22 px
#: thick. Area alone passes the wall edging; thickness alone passes specks.
MIN_REGION = 3e-4
MIN_RADIUS = 5.0                       # at 2048 px of art, scaled by side

#: A thin off-rung region this close to a rung is that rung's antialiasing;
#: further than this and it is drawing the art does in its own colour.
SNAP_MAX = 8

#: Off-rung greys are banded this wide, so a ramp keeps roughly where on the
#: slope it is instead of collapsing to one value.
BAND = 4

#: Below this total coverage the pixel is off the map. The alpha channel is
#: near-binary, so this only ever fires on the slab's outer edge.
COVER_MIN = 0.5


def stamp() -> str:
    """Hash of this file and the transform it borrows. See `source_stamp`."""
    h = hashlib.sha256()
    for p in (Path(__file__), Path(__file__).with_name("wiki_map.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def _rungs(g: np.ndarray, fam: np.ndarray, flat: np.ndarray,
           k: np.ndarray) -> np.ndarray:
    """The quantised levels of one family, off its INTERIOR. See `MIN_SHARE`."""
    interior = (cv2.erode(fam.astype(np.uint8), k) > 0) & flat
    if interior.sum() < 100:
        interior = fam
    v, c = np.unique(g[interior], return_counts=True)
    keep = c >= MIN_SHARE * c.sum()
    v, c = v[keep], c[keep]
    out: list[int] = []
    for i in np.argsort(-c):                      # most populous first, so a
        r = int(v[i])                             # merge keeps the real rung
        if all(abs(r - o) > MERGE_GAP for o in out):
            out.append(r)
    return np.array(sorted(out), np.int16)


def art_classes(map_name: str):
    """The art, cropped to its alpha bbox, as (kind, shade, step) per pixel.

    Also returns the terrain ladder and its base, which `levels` prints and
    `paint` colours by. Everything here happens at ART resolution: quantise
    first, warp second, because the warp is a 5x downsample and it cannot
    un-blend two rungs it has averaged.
    """
    p = WM.ART / f"{map_name}.png"
    if not p.is_file():
        raise SystemExit(f"no art for {map_name} -- "
                         f"run: wiki_map.py fetch {map_name}")
    im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if im is None or im.shape[2] < 4:
        raise SystemExit(f"{p} has no alpha channel")
    a = im[:, :, 3] > WM.ALPHA_MIN
    ys, xs = np.where(a)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    a = a[sl]
    bgr = im[sl][:, :, :3]
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]

    site = a & (sat > SAT_MAX)
    grey = a & ~site
    kind = np.zeros(a.shape, np.uint8)
    shade = np.zeros(a.shape, np.uint8)
    step = np.zeros(a.shape, np.int8)
    band = np.clip(g // BAND * BAND + BAND // 2, 1, 255).astype(np.uint8)

    # The interior test has to be read in ART pixels, and the art ships at two
    # sizes -- a 1 px shell at 1024 is a 2 px shell at 2048.
    side = max(a.shape)
    kern = np.ones((5, 5) if side > 1024 else (3, 3), np.uint8)
    flat = cv2.dilate(g.astype(np.uint8), kern) == cv2.erode(g.astype(np.uint8), kern)

    ladder = _rungs(g, grey & (g < LINE_MIN), flat, kern)
    if not len(ladder):
        raise SystemExit(f"{map_name}: no terrain rungs under {LINE_MIN}")
    base = int(ladder[int(np.argmax([(grey & (np.abs(g - r) <= MERGE_GAP)).sum()
                                     for r in ladder]))])
    base_i = int(np.where(ladder == base)[0][0])

    def ordinal(v):
        """Which rung a grey belongs to, as steps from the base."""
        return (np.abs(np.asarray(v)[..., None] - ladder[None, :]).argmin(-1)
                - base_i).astype(np.int8)

    line = grey & (g >= LINE_MIN)                 # the white line-work, stated
    kind[line] = LINE
    shade[line] = band[line]

    on = np.zeros(a.shape, bool)                  # on a rung, or within its
    for r in ladder:                              # own antialiasing of one
        m = grey & ~line & (np.abs(g - r) <= MERGE_GAP)
        on |= m
        kind[m] = FLOOR
        shade[m] = r
        step[m] = int(np.where(ladder == r)[0][0]) - base_i

    # Off-rung. A region that is BIG and THICK is terrain the art draws between
    # two rungs -- a ramp, or the shadow under an overhang. A thin one is
    # drawing: either a rung's own edge, or line-work in its own dim grey.
    off = grey & ~line & ~on
    n, lab, st, _ = cv2.connectedComponentsWithStats(off.astype(np.uint8), 8)
    dist = cv2.distanceTransform(off.astype(np.uint8), cv2.DIST_L2, 5)
    terrain = np.zeros(n, bool)
    for i in range(1, n):
        if st[i, 4] < MIN_REGION * a.sum():
            continue
        terrain[i] = dist[lab == i].max() >= MIN_RADIUS * side / 2048.0
    coherent, stray = off & terrain[lab], off & ~terrain[lab]

    dark = g < base - MERGE_GAP
    kind[coherent] = np.where(dark[coherent], SHADOW, RAMP)
    shade[coherent] = band[coherent]
    # A ramp reports the rung it is nearest, so `shade_step` stays one ordinal
    # over one ladder; a shadow is under the bottom rung by construction.
    step[coherent] = np.where(dark[coherent], -1, ordinal(g[coherent]))

    if stray.any():
        gs = g[stray]
        snap = np.abs(gs[:, None] - ladder[None, :]).min(1) <= SNAP_MAX
        # Below the base and off-rung is the shadow's own fringe, not drawing.
        k_s = np.where(snap, FLOOR, np.where(gs < base - MERGE_GAP, SHADOW, LINE))
        kind[stray] = k_s
        shade[stray] = np.where(snap,
                                ladder[np.abs(gs[:, None] - ladder[None, :]).argmin(1)],
                                band[stray])
        step[stray] = np.where(snap, ordinal(gs), np.where(k_s == SHADOW, -1, 0))

    # The sites carry their own ladder: Lotus and Sunset draw a raised one.
    if site.any():
        srungs = _rungs(g, site, flat, kern)
        sbase_i = int(np.argmax([(site & (np.abs(g - r) <= MERGE_GAP)).sum()
                                 for r in srungs]))
        idx = np.abs(g[site, None] - srungs[None, :]).argmin(1)
        kind[site] = SITE
        shade[site] = srungs[idx]
        step[site] = (idx - sbase_i).astype(np.int8)

    return kind, shade, step, ladder, base


def _warp(img: np.ndarray, rot: float, scale: float) -> np.ndarray:
    """`wiki_map`'s transform, exactly -- the fit is stored against it."""
    h0, w0 = img.shape
    Mx = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, scale)
    side = int(max(h0, w0) * scale * 1.6)
    Mx[0, 2] += side / 2 - w0 / 2
    Mx[1, 2] += side / 2 - h0 / 2
    return cv2.warpAffine(np.ascontiguousarray(img, np.float32), Mx,
                          (side, side), flags=cv2.INTER_AREA)


def shade_arrays(map_name: str, fit, shape):
    """Warp the art's classes into widget pixels. See WHY EACH CLASS."""
    rot, scale, dx, dy = float(fit[0]), float(fit[1]), int(fit[2]), int(fit[3])
    kind, shade, step, _ladder, _base = art_classes(map_name)
    blank = np.zeros(shape, np.float32)

    best = np.zeros(shape, np.float32)
    total = np.zeros(shape, np.float32)
    o_kind = np.zeros(shape, np.uint8)
    o_shade = np.zeros(shape, np.uint8)
    o_step = np.zeros(shape, np.int8)

    classes = np.unique(np.stack([kind[kind > 0], shade[kind > 0],
                                  step[kind > 0].astype(np.uint8)]), axis=1)
    for k, s, t in classes.T:
        m = (kind == k) & (shade == s) & (step.astype(np.uint8) == t)
        cov = WM._place(_warp(m.astype(np.float32), rot, scale), blank, dx, dy)
        total += cov
        win = cov > best
        best[win] = cov[win]
        o_kind[win] = k
        o_shade[win] = s
        o_step[win] = np.int8(t)

    on = total >= COVER_MIN
    o_kind[~on] = VOID
    o_shade[~on] = 0
    o_step[~on] = 0
    purity = np.zeros(shape, np.uint8)
    purity[on] = np.clip(best[on] / total[on] * 255.0, 0, 255).astype(np.uint8)
    return o_shade, o_kind, o_step, purity


def fit_of(gkey: str):
    """The stored (rot, scale, dx, dy, iou, ncc), fitting it if need be."""
    if WM.fit_for_key(gkey) is None:
        return None
    z = np.load(G.fit_path(gkey, STORE))
    return np.array([float(z["rot"]), float(z["scale"]), float(z["dx"]),
                     float(z["dy"]), float(z["iou"]), float(z["ncc"])], np.float32)


REF = STORE / "reference" / "shade"


def art_reference(map_name: str, rebuild=False):
    """The art-space class map for one map. **Permanent, and map-only.**

    No session, no profile, no capture: this is the wiki art quantised, and it
    changes only when the art or this file does. It is the expensive and the
    judgement-laden half -- every rung, ramp, shadow and line decision lives
    here -- and it is computable for a map nobody has ever recorded.
    """
    p = REF / f"{map_name}.npz"
    if p.is_file() and not rebuild:
        # Read EAGERLY and close. `np.load` on an npz is lazy and keeps the
        # file open, and on Windows an open handle refuses the atomic replace
        # below -- so a stale reference could never be rewritten in place.
        with np.load(p) as z:
            if str(z["built_by"]) == stamp():
                return (z["kind"], z["shade"], z["step"], z["ladder"],
                        int(z["base"]))
    kind, shade, step, ladder, base = art_classes(map_name)
    REF.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, kind=kind, shade=shade, step=step, ladder=ladder,
                        base=base, built_by=np.array(stamp()))
    tmp.replace(p)
    return kind, shade, step, ladder, base


def widget_reference(map_name: str, profile: str, fit=None, shape=None,
                     rebuild=False):
    """The same classes warped into widget pixels for one (map, PROFILE).

    **Also permanent**, and it is the artefact a session copies rather than
    computes. The map does not move inside the widget and the widget does not
    move inside the frame, so this depends on nothing a session contributes --
    which is the measurement `reticle/geometry.py` acts on, and why Lotus's two
    INDEPENDENT statics landed within one search step of each other.

    Returns None when it does not exist and no `fit` was supplied to make it:
    the four placement parameters are the ONE thing that needs a capture. The
    scale does not (see `SCALE_PER_PROFILE`), but the offset does.
    """
    p = REF / f"{map_name}__{profile}.npz"
    if p.is_file() and not rebuild:
        with np.load(p) as z:                    # eagerly -- see `art_reference`
            if str(z["built_by"]) == stamp():
                return (z["shade"], z["kind"], z["step"], z["purity"], z["fit"])
    if fit is None or shape is None:
        return None
    arrays = shade_arrays(map_name, fit, tuple(shape))
    REF.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, shade=arrays[0], kind=arrays[1], step=arrays[2],
                        purity=arrays[3], fit=np.asarray(fit, np.float32),
                        built_by=np.array(stamp()))
    tmp.replace(p)
    return arrays + (np.asarray(fit, np.float32),)


def write_shade(gkey: str, quiet=False, refit=False):
    """Copy the (map, profile) reference into that key's geometry npz.

    **This is a CACHE FILL, not a derivation.** The reference is the artefact;
    the npz gets a copy so existing loaders reach it with no new file to open.
    Real work happens once, ever, per key -- and since 2026-09-07 the key IS
    the geometry's key, so "once per (map, profile)" is a fact about the store
    rather than a claim about how often it is called.
    """
    p = G.path(gkey, STORE)
    if not p.is_file():
        return None
    try:
        map_name, prof = G.parse(gkey)
    except ValueError:
        return None
    if not (WM.ART / f"{map_name}.png").is_file():
        return None
    with np.load(p, allow_pickle=False) as _z:
        z = dict(_z)
    ref = widget_reference(map_name, prof, rebuild=refit)
    how = "cached"
    if ref is None or refit:
        fit = fit_of(gkey)
        if fit is None:
            print(f"  {gkey}  no fit and no reference -- skipped")
            return None
        ref = widget_reference(map_name, prof, fit=fit,
                               shape=z["labels"].shape, rebuild=True)
        how = "PLACED"
    shade, kind, step, purity, fit = ref
    if kind.shape != z["labels"].shape:
        print(f"  {gkey}  reference is {kind.shape}, this npz is "
              f"{z['labels'].shape} -- refusing")
        return None
    z.update(shade=shade, shade_kind=kind, shade_step=step, shade_purity=purity,
             shade_fit=fit, shade_map=np.array(map_name),
             shade_built_by=np.array(stamp()))
    tmp = p.with_name(p.stem + ".tmp.npz")   # savez appends .npz otherwise
    np.savez_compressed(tmp, **z)
    tmp.replace(p)
    if not quiet:
        print(f"  {gkey:32s} {how:6s} "
              f"shade on {float((kind > 0).mean()) * 100:5.1f}%  "
              f"IoU {fit[4]:.3f} NCC {fit[5]:.3f}")
    return ref


PAINT = {FLOOR: None, RAMP: (255, 0, 255), SHADOW: (255, 0, 0),
         LINE: (255, 255, 255), SITE: (120, 150, 150)}
STEPC = [(70, 70, 70), (0, 140, 255), (0, 220, 255), (0, 255, 140),
         (0, 230, 0), (255, 180, 0), (200, 120, 255)]


def paint(kind, step) -> np.ndarray:
    """Colour the classes so they can be LOOKED at. FLOOR is by step."""
    vis = np.zeros(kind.shape + (3,), np.uint8)
    for k, c in PAINT.items():
        if c is not None:
            vis[kind == k] = c
    for i, c in enumerate(STEPC):
        vis[(kind == FLOOR) & (step == i)] = c
    return vis


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lv = sub.add_parser("levels", help="the ladder the art states")
    lv.add_argument("maps", nargs="+")
    mp = sub.add_parser("maps", help="the PERMANENT per-map references")
    mp.add_argument("maps", nargs="*")
    mp.add_argument("--rebuild", action="store_true")
    pt = sub.add_parser("paint", help="render the classes, at art resolution")
    pt.add_argument("map")
    pt.add_argument("--out", required=True)
    pt.add_argument("--width", type=int, default=900)
    bd = sub.add_parser("build", help="write shade into the geometry npz")
    bd.add_argument("keys", nargs="*", help="geometry keys, `<map>__<profile>`")
    bd.add_argument("--all", action="store_true")
    bd.add_argument("--refit", action="store_true",
                    help="re-derive the placement instead of using the "
                         "(map, profile) reference")
    ck = sub.add_parser("check", help="score the shade against what we had")
    ck.add_argument("keys", nargs="*", help="geometry keys, `<map>__<profile>`")
    ck.add_argument("--all", action="store_true")
    ck.add_argument("--dump", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "levels":
        for m in a.maps:
            kind, shade, step, ladder, base = art_classes(m)
            tot = int((kind > 0).sum())
            print(f"{m}:  base {base}, ladder {list(map(int, ladder))}")
            for k in (FLOOR, RAMP, SHADOW, LINE, SITE):
                mk = kind == k
                if not mk.sum():
                    continue
                print(f"  {KIND_NAME[k]:7s}{mk.sum() / tot * 100:6.2f}% of the art")
                for s in sorted(set(step[mk].tolist())):
                    ms = mk & (step == s)
                    v = shade[ms]
                    lo, hi = int(v.min()), int(v.max())
                    rng = f"{lo}" if lo == hi else f"{lo}-{hi}"
                    print(f"      step {s:+d}  grey {rng:9s}"
                          f"{ms.sum() / tot * 100:6.2f}%"
                          + ("   <- base" if k == FLOOR and s == 0 else ""))
        return 0

    if a.cmd == "maps":
        names = a.maps or sorted(p.stem for p in WM.ART.glob("*.png"))
        placed = {}
        for f in REF.glob("*__*.npz"):
            m, prof = f.stem.split("__", 1)
            placed.setdefault(m, []).append(prof)
        for m in names:
            kind, _sh, step, ladder, base = art_reference(m, rebuild=a.rebuild)
            tot = int((kind > 0).sum())
            bits = "  ".join(
                f"{KIND_NAME[k]} {(kind == k).sum() / tot * 100:.1f}%"
                for k in (FLOOR, RAMP, SHADOW, LINE, SITE) if (kind == k).any())
            where = ", ".join(sorted(placed.get(m, []))) or "NOT PLACED -- needs one capture"
            print(f"{m:8s} base {base}  ladder {list(map(int, ladder))}")
            print(f"         {bits}")
            print(f"         {where}")
        return 0

    if a.cmd == "paint":
        kind, _shade, step, _ladder, _base = art_classes(a.map)
        vis = paint(kind, step)
        rot = WM.ROTATION.get(a.map, 0.0)
        if rot:
            vis = cv2.rotate(vis, cv2.ROTATE_90_COUNTERCLOCKWISE)
        h = int(a.width * vis.shape[0] / vis.shape[1])
        cv2.imwrite(a.out, cv2.resize(vis, (a.width, h),
                                      interpolation=cv2.INTER_NEAREST))
        print(f"  wrote {a.out}   FLOOR by step: grey, orange, yellow, "
              f"spring, green, cyan;  magenta RAMP, blue SHADOW, "
              f"white LINE, olive SITE")
        return 0

    keys = a.keys
    if a.all:
        keys = sorted(p.stem for p in (STORE / "geometry").glob("*.npz"))

    if a.cmd == "build":
        done = 0
        for k in keys:
            done += write_shade(k, refit=a.refit) is not None
        print(f"{done} of {len(keys)} geometry npz carry the shade")
        for k in keys:
            if not G.path(k, STORE).is_file():
                print(f"  {k}  no shade -- no geometry built for this key")
                continue
            with np.load(G.path(k, STORE), allow_pickle=False) as z:
                if "shade" in z.files:
                    continue
            m = G.parse(k)[0]
            print(f"  {k}  no shade -- no art fetched for {m}")
        return 0

    for sid in keys:
        z = np.load(G.path(sid, STORE))
        if "shade" not in z.files:
            continue
        kind, step, purity, lab = (z["shade_kind"], z["shade_step"],
                                   z["shade_purity"], z["labels"])
        on = kind > 0
        plant, site = lab == M.PLANT, kind == SITE
        floor = M.floor_mask(z["static"])
        derived = (lab == M.FLOOR) | plant

        def iou(x, y):
            return (x & y).sum() / max((x | y).sum(), 1) * 100
        print(f"{sid}  {str(z['shade_map'])}  fit IoU {z['shade_fit'][4]:.3f} "
              f"NCC {z['shade_fit'][5]:.3f}")
        print(f"    on map {on.mean() * 100:5.1f}%   vs labels FLOOR|PLANT "
              f"{iou(on, derived):5.1f}%   vs floor_mask {iou(on, floor):5.1f}%")
        print(f"    SITE vs labels PLANT {iou(site, plant):5.1f}%  "
              f"({int(site.sum())} px art, {int(plant.sum())} px derived)")
        print(f"    interior (purity >= 200) {(purity[on] >= 200).mean() * 100:5.1f}%")
        for k in (FLOOR, RAMP, SHADOW, LINE, SITE):
            for s in sorted(set(step[kind == k].tolist())):
                m = (kind == k) & (step == s)
                print(f"      {KIND_NAME[k]:7s} step {s:+d}  "
                      f"grey {int(np.median(z['shade'][m])):3d}  "
                      f"{m.mean() * 100:5.2f}% of the widget  "
                      f"{int(m.sum()):6d} px")
        if a.dump:
            vis = paint(kind, step)
            vis[~on] = z["static"][~on] // 3
            cv2.imwrite(a.dump, cv2.resize(vis, None, fx=2, fy=2,
                                           interpolation=cv2.INTER_NEAREST))
            print(f"    wrote {a.dump}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
