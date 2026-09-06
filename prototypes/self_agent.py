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

The next thing to try, and why it is the prime suspect
-------------------------------------------------------
**The crop is probably off-centre, systematically.** The self glyph is a ring
with a FACING TRIANGLE hanging off it, and both the component centroid and its
bounding-box centre are pulled toward whichever way the player is looking. So
the disc that is supposed to frame the portrait is displaced by a few pixels in
a direction that rotates through the session -- which blurs the very histogram
that is meant to carry identity, and does it differently for every clip.

`minimap_portrait.fit_ring` fits a CIRCLE to the rim and is the machinery that
already solved this for enemy icons, where the same teardrop shape defeated a
closure test. Pointing it at the self key is the obvious next step and it needs
no new labels.
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
    from minimap_portrait import composition, classify_composition
    from minimap_portrait_official import ART, art_composition, art_path
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


def self_icon(crop, floor):
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
    """
    b, g, rd = (crop[:, :, i].astype(np.int16) for i in range(3))
    m = ((g > SELF_G_MIN) & (rd > SELF_R_MIN)
         & ((g - b) > SELF_B_UNDER_G) & floor).astype(np.uint8)
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(st[1:, 4]))
    x, y, w, h, area = (int(v) for v in st[i])
    if area < 4:
        return None
    return float(cen[i][0]), float(cen[i][1]), max(w, h) / 2.0


def self_composition(crop, floor):
    """Composition of the self icon's interior, or None if no icon was found.

    The SELF ring colour is masked out rather than red: the interior is what
    carries identity and the ring is the same yellow-green for every agent, so
    leaving it in would make all 29 look alike in exactly the histogram that
    is supposed to separate them.
    """
    got = self_icon(crop, floor)
    if got is None:
        return None
    cx, cy, r = got
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
    return composition(patch, msk)


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


def vote(sid: str, n: int, sources: dict, gen: dict | None = None) -> dict:
    store = Store()
    man = store.read_manifest(sid)
    src = man["source"]
    prof = get_profile(man["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(prof, int(src["width"]), int(src["height"]))

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
    for smp in sample_at(src["path"], times, float(src["fps"])):
        crop = smp.frame[y0:y1, x0:x1]
        hq = self_composition(crop, floor)
        if hq is None:
            continue
        seen += 1
        if gen is None:
            name, _, _ = classify_composition(hq, sources)
        else:
            name, _ = classify_nulled(hq, sources, gen)
        if name:
            tally[name] += 1
    if not tally:
        return {"error": "no self ring found in any sampled frame"}
    top = tally.most_common(2)
    first, n1 = top[0]
    n2 = top[1][1] if len(top) > 1 else 0
    return {"agent": first, "votes": n1, "runner_up": top[1][0] if len(top) > 1 else None,
            "runner_votes": n2, "frames": seen, "asked": n,
            "share": n1 / seen, "margin": (n1 - n2) / seen}


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
    a = ap.parse_args(argv)

    store = Store()
    names = agents_available()
    sources = {n: art_composition(n, ART_FRAC) for n in names}
    sources = {k: v for k, v in sources.items() if v is not None}
    gen = None if a.raw else generality(sources)
    print(f"{len(sources)} agents with official minimap art "
          f"(chance {100 / len(sources):.1f}%), null control "
          f"{'OFF' if a.raw else 'ON'}\n")

    if a.demo_corpus:
        truth = tagged_agents(store)
        if not truth:
            raise SystemExit("no sessions carry an agent tag")
        print(f"{'session':<14}{'tagged':<12}{'read':<12}{'share':>7}"
              f"{'margin':>8}{'frames':>8}  ok")
        ok = tot = 0
        for sid, want in truth:
            r = vote(sid, a.n, sources, gen)
            if "error" in r:
                print(f"{sid:<14}{want:<12}{'--':<12}{'':>7}{'':>8}{'':>8}  "
                      f"{r['error']}")
                continue
            tot += 1
            good = r["agent"] == want
            ok += good
            print(f"{sid:<14}{want:<12}{r['agent']:<12}{r['share'] * 100:>6.0f}%"
                  f"{r['margin'] * 100:>7.0f}%{r['frames']:>8}  "
                  f"{'YES' if good else 'no'}")
        if tot:
            print(f"\n{ok}/{tot} correct ({ok / tot * 100:.0f}%), "
                  f"29-way, chance {100 / len(sources):.1f}%")
        return 0

    if not a.session:
        ap.error("give a session or --demo-corpus")
    r = vote(a.session, a.n, sources, gen)
    if "error" in r:
        raise SystemExit(r["error"])
    print(f"{a.session}: {r['agent']}  "
          f"({r['votes']}/{r['frames']} frames, {r['share'] * 100:.0f}%, "
          f"margin {r['margin'] * 100:.0f}% over {r['runner_up']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
