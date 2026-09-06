r"""Which agent is the LOCAL PLAYER? Named from official art, no labels.

    .\.venv\Scripts\python.exe prototypes\self_agent.py <session> [--n 160]
    .\.venv\Scripts\python.exe prototypes\self_agent.py --demo-corpus

Why this is the unblocking piece
---------------------------------
`reticle/track.py` makes motion a property of IDENTITY -- a teleport is legal
for Omen, Chamber, Veto, Waylay and Yoru and for nobody else. `jump_census.py`
then found the model has nothing to chew on: **not one session in the store
records which agent the player played**, so the whole split between a real teleport
and a phantom is unresolvable, and 54.7% of what `filter_track` drops sits at
teleport distance with no way to adjudicate it.

This derives it, per session, with no labelling and no scoreboard opening.

The method is not new, and that is the point
----------------------------------------------
`minimap_portrait_official.py` already established every piece:

* Riot's own `minimapPortrait` art is in the store for all 29 agents,
  `ability_reference.py harvest` having downloaded it;
* **pixel-wise matching against it is dead** -- 41.8% against a 70.4% bar, and
  the module says plainly that it re-ran a method already recorded as dead;
* **composition matching works** -- histogram intersection over the icon's
  interior disc, 78.5% at zero free parameters, beating the scoreboard-derived
  source (77.2%) while needing no scoreboard opening and covering all 29 agents
  rather than the ten a board shows.

The only new thing here is pointing it at the SELF ring rather than at enemy
icons, and voting over frames.

Three things that make the self icon the easy case
----------------------------------------------------
* **the colour key is exact and exclusive** (`minimap.self_rings`), where enemy
  icons need a population filter that has never worked well;
* **there is exactly one**, so a frame either answers or does not -- no
  assignment, no confusion between two candidates of the same team;
* **it recurs thousands of times a session**, so a per-frame rate of ~78%
  becomes a per-session vote. The margin between first and second is reported
  because a vote without one is a claim without a confidence.

Where this is weaker than the 78.5% it inherits, and it must not be quoted
--------------------------------------------------------------------------
**That figure is 5-WAY and this is 29-WAY.** It was measured against the five
agents present in one session's lineup, chance 20%; here the candidate set is
every agent in the game, chance 3.4%. Nothing licenses carrying the number
across, and this file measures its own.

Two further differences, both unmeasured until this runs: the self ring is
yellow-green rather than red, so a different colour is masked out of the
interior; and the facing triangle is thicker on the self icon than an enemy's
rim, so it covers more of the portrait it is being asked about.

Validation, and why the demo corpus is the right place
--------------------------------------------------------
The 28 one-agent-per-clip demo sessions carry the agent in their INGEST TAGS,
placed there by the player when he recorded them and long before this question
existed. That is ground truth of the strongest kind available here -- a label
from a different population than the thing being scored, recorded for another
purpose. `--demo-corpus` scores every one of them.

They are also solo, which is a caveat as well as a convenience: no ally rings
means no chance for the self key to pick up a teammate, so a real match may do
worse than the corpus says.

RESULT, 2026-09-06: 10/26 (38%) at 29-way, chance 3.4%
-------------------------------------------------------
Eleven times chance, so the signal is real -- and **not good enough to name an
agent per session**, which is what the tracker needs. It is reported as a
number rather than shipped as an answer.

**A bug of mine cost 34 points of that, and it is the more useful half of the
result.** The first run scored 1/26 -- indistinguishable from chance -- and
read as a clean negative about the METHOD. It was not: `minimap.self_rings`
returns `(AREA, cx, cy)` and this file read the first field as a radius, so
every crop was a disc of `area x 0.55` -- 50-90 px where an icon is 11 across.
Every query was a sample of the map rather than of a portrait. The tell was in
the numbers before it was in the code: mean cross-agent QUERY similarity 0.712
against the art's 0.329, and one class (`sova`) taking 19 of 26 answers. **A
sink is a measurement artefact until proven otherwise**, and reading that first
table as a negative result would have closed a line that works.

    before the fix   1/26   query similarity 0.712   sova sink 19/26
    after            10/26  query similarity 0.502   sova sink  9/26

**The null control did not help, and that is recorded rather than tuned away.**
`prototypes/CLAUDE.md`'s lesson -- *the correct statistic is
resemblance-to-own-agent minus resemblance-to-others* -- is implemented as
`generality()` and subtracted per source. It moves WHICH sessions are right
(astra gains, viper loses) and leaves the count at exactly 10/26. So the sink
is not a source being centrally located in colour space, and something else
explains it.

**The margin does not separate right from wrong**, so no refusal gate rescues
this: `chamber -> sova` is wrong at a 92% margin while `phoenix -> phoenix` is
right at 8%. Reporting a confidence that does not correlate with correctness
would be worse than reporting none.

The prime suspect was the CROP GEOMETRY, and it is FALSIFIED (2026-09-06)
--------------------------------------------------------------------------
The suspect, as `BACKLOG.md` recorded it: the self glyph is a ring with a
facing triangle hanging off it, so the centroid and the bounding-box centre are
both dragged toward where the player is looking, the framing disc is displaced
in a direction that rotates through the session, and the histogram is blurred
differently in every clip. `minimap_ring_fit.fit_ring` -- the machinery that
solved this exact teardrop for enemy icons -- should therefore lift the number.

It does not. Three geometries, the same corpus, the same everything else:

    --geom bbox   half the larger side of the component box    10/26   38%
    --geom ring   fit_ring, the enemy machinery unchanged        9/26   35%
    --geom pin    fit_ring scored coverage MINUS interior        9/26   35%

`ring` and `pin` are identical answer for answer; against `bbox` they share
eight of the ten, losing `phoenix` and `killjoy` and gaining `brimstone`. The
sinks barely move either -- `sova` x8 -> x7, `yoru` x2 -> x4. Whatever is
capping this at ten, **it is not where the crop is centred.**

What the falsification cost, and what it bought
-------------------------------------------------
Two measurements now describe the self glyph properly, and neither was known
before -- the earlier text was reasoning from the enemy icon's shape:

* **the self key survives only over the LOWER HALF of the rim.** Sampled around
  the fitted circle over five sessions, the key is present on 61-67% of the
  bearings from 150 to 240 degrees and on **22-23% at 330-30** -- a dropout
  fixed in SCREEN space, not one that rotates with facing. Rendering the mask
  beside the crop shows the same thing: an open-topped arc with a solid tail;
* **so there is no hole to find.** A closed rim would give the portrait as the
  largest hole in the key, which is a centre with no fitting at all. Measured:
  **0 holes in 347 frames across six sessions.** Do not re-try it.

`--geom pin` was the answer to why a circle fit might still fail here -- the
tail is solid and comparable in area to the surviving arc, so a circle slid
down onto it scores well on coverage. Scoring `coverage - interior` cancels
that, needs no new threshold, and **changes nothing** (9/26, the same nine).
So the tail is not stealing the fit either.

THE DESCRIPTOR SWAP, and it re-reads the result above (2026-09-06)
--------------------------------------------------------------------
`--desc ncc` replaces the colour histogram with `minimap_portrait`'s masked
NCC against the same official art. Crossed with the geometry:

                        --geom bbox        --geom pin
        --desc hist       10/26  38%         9/26  35%
        --desc ncc         0/26   0%         8/26  31%

**Neither wins, and the interaction is the finding.** Under the histogram the
geometry is worth -1; under NCC it is worth +8, from BELOW CHANCE to 31%. A
histogram is alignment-blind by construction, so it could not see a better
centre; NCC decorrelates under misalignment, so it can see nothing else. The
fitted ring was therefore not useless -- **it was measured with an instrument
that could not detect it**, and the honest version of the falsification above
is narrower than it first read: the crop is not what caps the HISTOGRAM at ten.

The wash hypothesis is confirmed on its own terms. `chamber -> sova`, the
confident wrong answer that motivated the swap, becomes **`chamber -> chamber`**
under NCC. So the ring's glow was displacing that histogram, exactly as
predicted -- removing the per-channel mean fixes that session.

**The two descriptors are COMPLEMENTARY, and that is the result worth acting
on.** They agree on only 4 of the 26 (brimstone, astra, veto, gekko), and the
union of what they get right is **13/26 -- 50%, against 38% for the better one
alone**. NCC alone recovers clove, phoenix, chamber and killjoy; the histogram
alone recovers sova, yoru, breach, miks and omen. An oracle picking between
them doubles chance-adjusted performance, so the ceiling is not the problem and
neither descriptor is the answer.

NCC brings its own sink -- `cypher` x12 -- and its per-frame shares collapse to
18-50% where the histogram reached 99%. A vote that thin is a vote that is
barely deciding, which is consistent with 121 grid cells masked down to the
low twenties on a glyph whose rim only reads over half its circumference.

Where this goes: STOP CHOOSING A DESCRIPTOR
---------------------------------------------
Two descriptors that fail on disjoint agents, both of them discarding most of
the glyph -- the histogram throws away position, NCC throws away level, and
both mask out the ring and the tail as nuisance -- is the signature of the
wrong question. The forward model is the right one, and `BACKLOG.md`'s
analysis-by-synthesis entry is where it is argued: hypothesise agent X, DRAW
the glyph agent X would produce (the art, the glow that washes it, the tail at
the observed facing), subtract, and score the residual. The wash stops being a
nuisance to remove and becomes part of the prediction; the tail stops being
masked out and becomes evidence.

`self_agent` is the smallest instance of that idea anywhere in this repo: ONE
entity, 29 hypotheses, no assignment problem, and a ground truth that already
exists in the ingest tags. If analysis-by-synthesis cannot be made to work
here, it will not work on overlapping icons or spatialised audio.

The evidence that named the descriptor, kept for the record
--------------------------------------------------------------
`chamber -> sova` at a 99% share and a 98% margin is not a blurred histogram;
it is a confident wrong answer, and it survives every geometry. The renders
show why it might: the ring is a thick glow and it **washes the portrait
yellow-green**, hard on pale agents and barely at all on a dark one like Omen
-- and `composition` is a colour histogram, so a wash moves it bodily.

`minimap_portrait.similarity` is masked NCC with the per-channel mean removed,
chosen for exactly this reason on the enemy path -- *the widget is composited
over live scenery and the whole icon shifts in level with what is behind it*.
That descriptor is level-invariant and this one is not. Swapping it is the next
experiment, and `descriptor()` already exists. 38% is still the number to beat.
"""
from __future__ import annotations

import argparse
import collections
import io
import contextlib
import json
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    from minimap_portrait import (composition, classify_composition,
                                  classify, descriptor)
    from minimap_portrait_official import (ART, art_composition, art_path,
                                           template_set)
    import minimap_ring_fit as rf
from reticle.decode import sample_at                              # noqa: E402
from reticle.minimap import (SELF_B_UNDER_G, SELF_G_MIN,          # noqa: E402
                             SELF_R_MIN, floor_mask, minimap_roi_px,
                             self_rings, widget_scale)
from reticle.profiles import get_profile                          # noqa: E402
from reticle.store import Store                                   # noqa: E402

STORE = pathlib.Path.home() / "reticle-store"
#: Fraction of the fitted ring radius taken as the portrait interior. The value
#: `minimap_portrait` uses, unchanged -- it is the one that transfers, and
#: re-fitting it here on a different surface is how a crop family becomes
#: degenerate (see `minimap_portrait_transform`, 24.7% against a 20% chance).
INTERIOR_FRAC = 0.55
#: Disc of the official art to take. 1.0 -- the whole thing -- is the
#: zero-parameter setting that scored 78.5%, and the fitted 0.70 is NOT used
#: because its held-out-by-agent number was never computed.
ART_FRAC = 1.0


def agents_available() -> list[str]:
    """Every agent Riot publishes minimap art for."""
    return sorted(p.name[: -len("_minimap_portrait.png")].lower()
                  for p in ART.glob("*_minimap_portrait.png"))


def self_mask(crop):
    """The self colour key. Exact and exclusive, unlike the enemy red."""
    b, g, rd = (crop[:, :, i].astype(np.int16) for i in range(3))
    return (g > SELF_G_MIN) & (rd > SELF_R_MIN) & ((g - b) > SELF_B_UNDER_G)


def _biggest(m):
    """Largest component of the key, as (cx, cy, w, h, area), or None."""
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(st[1:, 4]))
    x, y, w, h, area = (int(v) for v in st[i])
    if area < 4:
        return None
    return float(cen[i][0]), float(cen[i][1]), w, h, area


def fit_self_ring(m, r_min, r_max):
    """`fit_ring`'s search, scored so the SOLID TAIL cannot win it.

    `minimap_ring_fit.fit_ring` picks the circle whose circumference is most
    covered by the key. On an enemy icon that is right: the ring is 1-2 px and
    the facing triangle is a small lobe outside it. **On the self glyph it is
    not.** The self icon is a map pin -- a ringed portrait with a SOLID
    triangle whose area is comparable to the arc -- and the key only survives
    over the lower half of the rim (present 61-67% at bearings 150-240 deg,
    22-23% at 330-30, pooled over five sessions). So a circle slid DOWN onto
    the tail scores a high coverage on a solid blob, and that is what the fit
    does: sampled around the winning circle, the top is neutral grey
    (B159 G152 R164) and the bottom is ring yellow (G228 R225, G-B 59).

    The correction needs no new threshold, and it is the same statistic the
    null control already uses here -- evidence FOR minus evidence AGAINST:

        score = circumference covered - interior covered

    A true rim has the key on the circle and the PORTRAIT inside it, so its
    interior term is near zero; a circle parked on the tail has both, and
    cancels itself out. `fit_ring` already computes the interior fraction, as
    `inner_red`; it simply does not score with it.
    """
    got = _biggest(m)
    if got is None:
        return None
    cx, cy = got[0], got[1]
    h, w = m.shape
    best = None
    for dy in range(-rf.SEARCH, rf.SEARCH + 1):
        for dx in range(-rf.SEARCH, rf.SEARCH + 1):
            y0, x0 = int(round(cy + dy)), int(round(cx + dx))
            for r in range(r_min, r_max + 1):
                pts, disc = rf._offsets(r)
                xs, ys = x0 + pts[:, 0], y0 + pts[:, 1]
                ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
                if ok.sum() < len(pts) * 0.75:
                    continue
                cov = float(m[ys[ok], xs[ok]].mean())
                dxs, dys = x0 + disc[:, 0], y0 + disc[:, 1]
                dok = (dxs >= 0) & (dys >= 0) & (dxs < w) & (dys < h)
                if not dok.any():
                    continue
                inner = float(m[dys[dok], dxs[dok]].mean())
                sc = cov - inner
                if best is None or sc > best[0]:
                    best = (sc, x0, y0, r, cov)
    if best is None:
        return None
    _sc, x0, y0, r, cov = best
    return float(x0), float(y0), float(r), cov


def self_icon_ring(m, grey, r_min, r_max):
    """The self icon's centre and radius by FITTING A CIRCLE to its rim.

    The reason this exists is written out in the module docstring: the bbox
    geometry below measures a teardrop, so its centre is dragged toward the
    facing triangle and its radius is inflated by it, in a direction that
    rotates through the session. `minimap_ring_fit.fit_ring` brute-forces the
    circle whose circumference is most covered by the key and was built for
    exactly this shape on enemy icons; the mask it takes is any binary ring, so
    the self key goes in unchanged.

    Returns `(cx, cy, r, coverage)`. Coverage is reported rather than gated:
    a floor on it would be a new free parameter, and this measures first.
    """
    got = _biggest(m)
    if got is None:
        return None
    cx, cy = got[0], got[1]
    f = rf.fit_ring(m, grey, cx, cy, r_min, r_max)
    if f is None:
        return None
    return float(f["cx"]), float(f["cy"]), float(f["r"]), float(f["cov"])


def self_icon_bbox(m):
    """The self icon's centre and RADIUS, measured from its own component.

    **`minimap.self_rings` returns `(AREA, cx, cy)`, not a radius** -- `_rings`
    takes `st[i, 4]` straight off `connectedComponentsWithStats`. The first
    version of this file read that tuple as `(r, cx, cy)` and cropped a disc of
    `area * 0.55`, which on the enlarged widget is 50-90 px where an icon is
    about 11 across. Every query histogram was then a sample of the MAP rather
    than of a portrait, all 26 sessions looked alike (mean cross-agent
    similarity 0.712 against the art's 0.329), and the classifier collapsed to
    a single sink -- `sova` on 19 of 26. The measured cost of the bug was a
    clean-looking 1/26 that read as a negative result about the METHOD.

    So the geometry is measured here rather than inferred: the same colour key,
    its own components pass, and the radius from the component's bounding box.
    Half the larger side, because the self glyph is a ring with a facing
    triangle hanging off it -- the box is wider than the ring in one axis, and
    taking the smaller side would crop into the portrait.

    **Superseded by `self_icon_ring`, and kept so the two are comparable under
    `--geom`.** Both of the properties this docstring describes as safe are the
    defect: half the larger side is a radius inflated by the triangle, and the
    centroid it pairs with is displaced by it.
    """
    got = _biggest(m)
    if got is None:
        return None
    cx, cy, w, h, _area = got
    return cx, cy, max(w, h) / 2.0, float("nan")


def self_composition(crop, floor, geom="pin", r_min=None, r_max=None):
    """Composition of the self icon's interior, or None if no icon was found.

    The SELF ring colour is masked out rather than red: the interior is what
    carries identity and the ring is the same yellow-green for every agent, so
    leaving it in would make all 29 look alike in exactly the histogram that
    is supposed to separate them.

    Returns `(histogram, coverage)`; coverage is NaN under `--geom bbox`, which
    has no fit to report one from.
    """
    m = self_mask(crop) & floor
    if geom == "pin":
        got = fit_self_ring(m, r_min, r_max)
    elif geom == "ring":
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        got = self_icon_ring(m, grey, r_min, r_max)
    else:
        got = self_icon_bbox(m)
    if got is None:
        return None
    cx, cy, r, cov = got
    rr = max(2, int(round(r * INTERIOR_FRAC)))
    y0, x0 = int(round(cy)) - rr, int(round(cx)) - rr
    if y0 < 0 or x0 < 0 or y0 + 2 * rr > crop.shape[0] or x0 + 2 * rr > crop.shape[1]:
        return None
    patch = crop[y0:y0 + 2 * rr, x0:x0 + 2 * rr]
    b, g, rd = (patch[:, :, i].astype(np.int16) for i in range(3))
    ring = (g > SELF_G_MIN) & (rd > SELF_R_MIN) & ((g - b) > SELF_B_UNDER_G)
    yy, xx = np.mgrid[0:2 * rr, 0:2 * rr]
    msk = (((yy - rr) ** 2 + (xx - rr) ** 2) <= rr * rr) & ~ring
    if msk.sum() < 12:
        return None
    return composition(patch, msk), cov


def self_descriptor(crop, floor, geom="pin", r_min=None, r_max=None):
    """The self interior as an 11x11 masked patch, for NCC instead of a histogram.

    Why this exists, when `self_composition` already answers the same question:
    **a colour histogram has no invariance to a level shift, and this surface
    has one.** The self ring is a thick glow that washes the portrait
    yellow-green -- hard on a pale agent, barely at all on a dark one like Omen
    -- so the query histogram is displaced bodily toward the ring colour by an
    amount that depends on the agent. That is a confident wrong answer waiting
    to happen, and `chamber -> sova` at a 99% share and a 98% margin is what it
    looks like when it does.

    `minimap_portrait.similarity` removes the per-channel mean and normalises,
    so an additive wash and a multiplicative one both cancel. It is also
    SPATIAL where a histogram is not. The cost is the other side of that coin:
    NCC decorrelates under misalignment, and this glyph's centre is the least
    certain thing about it -- the rim reads over its lower half only. So this
    is a real experiment either way, not a free upgrade.

    Returns `(patch, mask, coverage)` in `descriptor`'s own space, so the
    official-art templates need no conversion.
    """
    m = self_mask(crop)
    mf = m & floor
    if geom == "pin":
        got = fit_self_ring(mf, r_min, r_max)
    elif geom == "ring":
        got = self_icon_ring(mf, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY),
                             r_min, r_max)
    else:
        got = self_icon_bbox(mf)
    if got is None:
        return None
    cx, cy, r, cov = got
    pa, ma = descriptor(crop, m, int(round(cx)), int(round(cy)), r)
    if pa is None:
        return None
    return pa, ma, cov


def generality(sources: dict) -> dict:
    """How close each source sits to every OTHER source.

    `prototypes/CLAUDE.md` records the lesson this implements, from the
    killfeed-portrait experiment: *resemblance numbers without a null control
    are uninterpretable, and mine did not have one. The correct statistic is
    resemblance-to-own-agent minus resemblance-to-others.*

    A source whose histogram is central in colour space wins by default against
    any query, which is exactly the SINK this file measured: before the
    correction `sova` took 9 of the 16 wrong answers on the demo corpus.
    Subtracting a source's own generality is the null control applied per
    class, and it costs one pass over 29 histograms.
    """
    out = {}
    for a, ha in sources.items():
        others = [float(np.minimum(ha, hb).sum())
                  for b, hb in sources.items() if b != a]
        out[a] = sum(others) / max(1, len(others))
    return out


def classify_nulled(hq, sources, gen) -> tuple[str | None, float]:
    """Nearest source by intersection MINUS that source's generality."""
    best = sorted(((float(np.minimum(hq, hs).sum()) - gen[n], n)
                   for n, hs in sources.items()), reverse=True)
    if not best:
        return None, 0.0
    return best[0][1], best[0][0] - (best[1][0] if len(best) > 1 else 0.0)


def vote(sid: str, n: int, sources: dict, gen: dict | None = None,
         geom: str = "pin", desc: str = "hist") -> dict:
    store = Store()
    man = store.read_manifest(sid)
    src = man["source"]
    prof = get_profile(man["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(prof, int(src["width"]), int(src["height"]))

    # The icon radius is a WIDGET constant, so the fit's radius range scales
    # with the widget rather than being the enlarged-widget pair everywhere.
    # `rf.R_MIN/R_MAX` were measured at scale 1.0; a 331 px widget wants 6-9.
    sc = widget_scale(x1 - x0)
    r_min = max(3, int(round(rf.R_MIN * sc)))
    r_max = max(r_min + 1, int(round(rf.R_MAX * sc)))

    # Floor from the session's own geometry static -- every session with
    # geometry has one, where `masks/<sid>.static.npy` exists for only a few.
    g = STORE / "geometry" / f"{sid}.npz"
    if not g.is_file():
        return {"error": "no geometry"}
    floor = floor_mask(np.load(g, allow_pickle=True)["static"])

    dur = float(src["duration_ms"])
    times = [dur * (i + 0.5) / n for i in range(n)]
    tally: collections.Counter = collections.Counter()
    seen = 0
    covs: list[float] = []
    for smp in sample_at(src["path"], times, float(src["fps"])):
        crop = smp.frame[y0:y1, x0:x1]
        if desc == "ncc":
            got = self_descriptor(crop, floor, geom, r_min, r_max)
            if got is None:
                continue
            pa, ma, cov = got
            # `sources` is a gallery of (patch, mask, name) here, and `classify`
            # is the same nearest-exemplar the enemy path uses. The null control
            # is a histogram-path device and does not apply: NCC has already
            # removed the per-channel mean, which is what generality corrected
            # for by subtraction.
            name, _score, _margin = classify(pa, ma, sources)
        else:
            got = self_composition(crop, floor, geom, r_min, r_max)
            if got is None:
                continue
            hq, cov = got
            if gen is None:
                name, _, _ = classify_composition(hq, sources)
            else:
                name, _ = classify_nulled(hq, sources, gen)
        covs.append(cov)
        seen += 1
        if name:
            tally[name] += 1
    if not tally:
        return {"error": "no self ring found in any sampled frame"}
    top = tally.most_common(2)
    first, n1 = top[0]
    n2 = top[1][1] if len(top) > 1 else 0
    return {"agent": first, "votes": n1, "runner_up": top[1][0] if len(top) > 1 else None,
            "runner_votes": n2, "frames": seen, "asked": n,
            "share": n1 / seen, "margin": (n1 - n2) / seen,
            "cov": float(np.nanmedian(covs)) if covs else float("nan"),
            "r_range": (r_min, r_max)}


def tagged_agents(store) -> list[tuple[str, str]]:
    """Demo sessions whose ingest tags name the agent. Ground truth."""
    known = set(agents_available())
    out = []
    for f in sorted((STORE / "manifests").glob("*.json")):
        tags = json.loads(f.read_text(encoding="utf-8")).get("tags") or []
        hit = [t for t in tags if t.lower() in known]
        if len(hit) == 1:
            out.append((f.stem, hit[0].lower()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="?")
    ap.add_argument("--n", type=int, default=160, help="frames to sample")
    ap.add_argument("--demo-corpus", action="store_true",
                    help="score every session whose tags name an agent")
    ap.add_argument("--raw", action="store_true",
                    help="score WITHOUT the null control, to reproduce the sink")
    ap.add_argument("--desc", choices=("hist", "ncc"), default="hist",
                    help="interior descriptor: colour-histogram intersection "
                         "(the 38%% baseline) or masked NCC on an 11x11 grid, "
                         "which is level-invariant and spatial")
    ap.add_argument("--geom", choices=("pin", "ring", "bbox"), default="pin",
                    help="how the crop is centred and sized: a fitted circle "
                         "(default) or the component's bounding box (the "
                         "geometry that scored 38%%)")
    a = ap.parse_args(argv)

    store = Store()
    names = agents_available()
    if a.desc == "ncc":
        sources = template_set(names)
        gen = None
        n_src = len(sources)
    else:
        sources = {n: art_composition(n, ART_FRAC) for n in names}
        sources = {k: v for k, v in sources.items() if v is not None}
        gen = None if a.raw else generality(sources)
        n_src = len(sources)
    print(f"{n_src} agents with official minimap art "
          f"(chance {100 / n_src:.1f}%), descriptor {a.desc.upper()}, "
          f"null control {'n/a' if a.desc == 'ncc' else ('OFF' if a.raw else 'ON')}"
          f", geometry {a.geom.upper()}\n")

    if a.demo_corpus:
        truth = tagged_agents(store)
        if not truth:
            raise SystemExit("no sessions carry an agent tag")
        print(f"{'session':<14}{'tagged':<12}{'read':<12}{'share':>7}"
              f"{'margin':>8}{'frames':>8}{'cov':>7}  ok")
        ok = tot = 0
        wrong: collections.Counter = collections.Counter()
        for sid, want in truth:
            r = vote(sid, a.n, sources, gen, a.geom, a.desc)
            if "error" in r:
                print(f"{sid:<14}{want:<12}{'--':<12}{'':>7}{'':>8}{'':>8}"
                      f"{'':>7}  {r['error']}")
                continue
            tot += 1
            good = r["agent"] == want
            ok += good
            if not good:
                wrong[r["agent"]] += 1
            print(f"{sid:<14}{want:<12}{r['agent']:<12}{r['share'] * 100:>6.0f}%"
                  f"{r['margin'] * 100:>7.0f}%{r['frames']:>8}"
                  f"{r['cov'] * 100:>6.0f}%  "
                  f"{'YES' if good else 'no'}")
        if tot:
            print(f"\n{ok}/{tot} correct ({ok / tot * 100:.0f}%), "
                  f"29-way, chance {100 / n_src:.1f}%")
            if wrong:
                # The sink is the diagnostic, not a curiosity: one class taking
                # most of the misses is what said the first run of this file was
                # a measurement artefact rather than a negative result.
                top = ", ".join(f"{n} x{c}" for n, c in wrong.most_common(3))
                print(f"largest sinks among the {sum(wrong.values())} wrong: {top}")
        return 0

    if not a.session:
        ap.error("give a session or --demo-corpus")
    r = vote(a.session, a.n, sources, gen, a.geom, a.desc)
    if "error" in r:
        raise SystemExit(r["error"])
    print(f"{a.session}: {r['agent']}  "
          f"({r['votes']}/{r['frames']} frames, {r['share'] * 100:.0f}%, "
          f"margin {r['margin'] * 100:.0f}% over {r['runner_up']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
