# `prototypes/map_shade.py`, retired 2026-10-05

`reticle/map_asset.py` now quantises the game's fog texture into the same six
classes and warps them by the same area coverage, so this prototype, its
per-session fits and its `reference/shade/` cache were deleted. Its docstring
follows verbatim as dated evidence: the six classes, what they separate and
the saturation split still hold; the claims that the photometry and the
four-parameter placement need a capture do not (`prototypes/minimap_geometry.py`).

```text
The wiki art's terrain LEVELS, warped into widget pixels and stored.

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
```
