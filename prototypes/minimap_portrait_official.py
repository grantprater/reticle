"""Score Riot's OWN minimap portrait art as a cross-session agent template set.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_portrait_official.py <session>
    .\\.venv\\Scripts\\python.exe prototypes\\minimap_portrait_official.py <session> --sweep

What this settles
-----------------
`minimap_portrait.py` identifies enemies at 93.0% (1-NN) using a gallery mined
from the minimap itself, which means every capture needs its own hand-labelled
gallery before it can identify anybody. That is the only reason identification
is not a shipped stage.

`minimap_portrait_transform.py` tried to remove that cost by synthesizing
templates from the Tab scoreboard bust and found the premise FALSE -- Omen,
Jett and Killjoy sat at 0.16-0.24 resemblance in the best case the crop family
could produce, against the 0.89-0.97 two real icons of one agent reach. Its
verdict:

    "The minimap avatar appears to be its own render -- not the bust rescaled."

That render was untestable then because no surface in the CAPTURE carries it.
It is not in the capture. It is `minimapPortrait` in Riot's asset catalogue,
64x64 RGBA, one per agent, and `ability_reference.py` downloads all 29. This
scores it against the labelled icons.

The protocol, and why it is this one
------------------------------------
The transform module's lesson was that fitting a crop by maximising agreement
with the icons it is fitted to finds a degenerate window and reports a great
score on it. So the headline number here has **no free parameters at all**:

    the in-capture descriptor takes a box of side 2 * r * INTERIOR_FRAC across
    an icon of radius r -- 55% of the icon's diameter. If the 64x64 art frames
    the same disc, the matching box is 55% of the art. Take exactly that.

`--sweep` varies the crop as a DIAGNOSTIC, and reports it leave-one-agent-out:
the fraction is fitted on four agents and scored on the fifth, so a value that
works by memorising one agent cannot score. Two things are worth as much as the
accuracy: whether the swept optimum lands near the principled 0.55 (corroboration
that the art frames the icon disc), and whether the per-agent spread is tight
(one agent carrying the mean is a different result from five agreeing).

The mirror is a control, not an assumption. `minimap_portrait.py` records that
the ENEMY ROSTER is the mirrored surface and that the minimap and scoreboard
share an orientation, so unmirrored should win clearly. If it does not, the
orientation claim is what to re-examine, not this.

The bar, pre-registered
-----------------------
A synthesized template is ONE exemplar per agent, and `minimap_portrait.py`
measured what that costs in-domain: a gallery of exemplars scores 93.0%, one
median template per agent scores **70.4%**. So 70.4% is the target and the
majority-class rate on this label set is the floor. Landing near the floor means
the art fails the way the bust did; landing near 70% means cross-session
identity needs no gallery ever again.

Provenance, 2026-09-04
----------------------
All 107 agent labels on `a06f04a0059f` now read `by: human` -- the 71
`claude-provisional` rows the module docstrings still warn about were
relabelled. 79 of the 107 carry an agent name; the other 28 are `question`
icons, which have no portrait to match and are excluded. Nothing here is
scored against my own clustering.

RESULT, 2026-09-04: it MISSES the pre-registered bar
-----------------------------------------------------
    zero free parameters (crop 0.55)            41.8%
    scale fitted leave-one-agent-out            46.8%
    ---------------------------------------------------
    majority-class floor                        29.1%
    in-domain ONE median template (the bar)     70.4%
    in-domain gallery 1-NN, same 107 labels     83.2%

Above chance, well short of the bar. It does not replace a hand-labelled
gallery. The mirror control behaved as `minimap_portrait.py` says it should --
as-is 41.8% beats mirrored 32.9%.

The per-agent resemblance is what says WHY, at the unfitted 0.55:

    agent    official vs own icons   icon-to-icon mean   icon-to-icon BEST
    iso              0.518                 0.539               0.891
    jett             0.134                 0.036               0.624
    killjoy          0.023                 0.036               0.904
    omen             0.046                 0.061               0.513
    skye             0.548                 0.500               0.974

Two things to read off it. First, the BEST column reproduces
`minimap_portrait_transform.py`'s in-domain figures to three decimals
(omen 0.513, jett 0.624, killjoy 0.904, skye 0.974, iso 0.891), which is the
cross-check that this harness measures the same quantity that experiment did --
so the two are directly comparable, and its fitted bust crop reached 0.215 /
0.236 / 0.160 / 0.630 / 0.649 where this unfitted central crop reaches 0.046 /
0.134 / 0.023 / 0.548 / 0.518. The official art is NOT beating the bust.

Second, **Killjoy settles that this is not a resolution limit.** Killjoy icons
resemble each other at 0.904 -- the highest of the five, at the same ~11 px --
while the official Killjoy art resembles them at 0.023. Whatever the game draws
for Killjoy on the minimap, it is stable across frames and it is not a centred
crop of `minimapportrait.png`.

The same two agents win and the same three lose as in the bust experiment
(Skye and Iso against Omen, Jett, Killjoy), which is worth holding onto: two
unrelated source assets failing on the same three agents points at something
those three icons share in the CAPTURE, not at the source.

THE ABOVE RE-RAN A METHOD ALREADY RECORDED AS DEAD
---------------------------------------------------
`prototypes/CLAUDE.md` says it plainly: pixel-wise resemblance has **zero**
signal on both surfaces once a null control is applied, and identity at 11 px
*"lives in the palette"* rather than in layout, because there is barely any
layout left to match. Scoring official art by NCC was re-running a known-dead
method with a new asset. The composition result below is the one that counts;
the NCC table above is kept because it is the like-for-like comparison against
the bust experiment, not because 41.8% means anything on its own.

RESULT, `--composition`: the art is on par with the scoreboard, and needs no scoreboard
----------------------------------------------------------------------------------------
Same 79 icons, same `minimap_portrait.composition()` histogram-intersection
rule, official art as the source instead of scoreboard busts:

    disc frac   accuracy    iso     jett    killjoy   omen    skye
    1.00 (none)   78.5%    20/21    9/9      10/23    7/7    16/19
    0.70          84.8%    21/21    9/9      12/23    7/7    18/19
    0.30          83.5%    19/21    3/9      20/23    7/7    17/19

    scoreboard art, same rule:  77.2% no parameters, 83.5% held out by agent,
                                92.4% fitted in-sample, 91.1% in-domain control

Read it honestly in both directions. At **zero parameters the official art wins,
78.5% against 77.2%**. Fitted, it loses -- 84.8% in-sample against the
scoreboard's 92.4% in-sample -- and the held-out-by-agent number for this source
has not been computed, so it must not be compared to 83.5%.

What is unambiguous is operational rather than statistical: this source needs no
scoreboard opening. Scoreboard portrait extraction is recorded as wrong on two
sessions of three, and it is the blocker on the cold bootstrap. It also covers
all 29 agents rather than the ten a given scoreboard shows.

**Killjoy is the whole error budget, and it is not amorphousness.** Every other
agent is at or near perfect (iso 21/21, jett 9/9, omen 7/7, skye 18/19). Killjoy
runs 10-12 of 23 at the fractions that suit the others and climbs to 20/23 at
frac 0.30 -- where Jett collapses to 3/9. So the agents disagree about WHICH
RADIUS carries their identity, and one global disc cannot serve both. That is a
concrete, addressable shape, and it argues for concentric-ring histograms
(centre disc plus annuli, concatenated) over picking a single radius: it keeps
where-the-colour-sits without asking layout to align.

What has NOT been tried, and the trap next to it
-------------------------------------------------
This fitted ONE scalar -- the crop fraction. The bust experiment fitted a
CENTRE and a RADIUS as well, so the official art has not had the same search
applied to it and the comparison above is not symmetric. That search is the
obvious next test.

It is also exactly where the degenerate objective lives: fitting a crop by
maximising agreement with the icons it is fitted to is what produced "46 of 71
icons called the same agent". If it is run, it is run leave-one-agent-out, and
a per-agent optimum that disagrees about WHERE the crop is means the family is
wrong again rather than nearly right.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from minimap_portrait import (                                       # noqa: E402
    INSIDE, INTERIOR_FRAC, MIN_CELLS, N_GRID,
    build_gallery, load_agent_labels, similarity,
)

STORE = Path.home() / "reticle-store"
ART = STORE / "reference" / "assets" / "agents"


def art_path(agent: str) -> Path | None:
    """Label name -> downloaded asset. Labels are lowercase; assets are slugged display names."""
    want = re.sub(r"[^a-z0-9]", "", agent.lower())
    for p in sorted(ART.glob("*_minimap_portrait.png")):
        stem = p.name[: -len("_minimap_portrait.png")]
        if re.sub(r"[^a-z0-9]", "", stem.lower()) == want:
            return p
    return None


def template(path: Path, frac: float = INTERIOR_FRAC, mirror: bool = False):
    """Official art -> a descriptor in the same space `minimap_portrait.descriptor` produces.

    INTER_AREA, matching the in-capture path. Point-sampling a 64 px source
    down to 11 aliases it into something that correlates with nothing -- the
    failure that once had 46 of 71 icons called the same agent.

    The mask is the art's own alpha intersected with the descriptor's unit
    disc. The alpha is exact, which is the one advantage this has over any
    capture-derived template: no background comes with it.
    """
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None:
        return None, None
    if mirror:
        im = im[:, ::-1]
    h, w = im.shape[:2]
    side = int(round(min(h, w) * frac))
    y0, x0 = (h - side) // 2, (w - side) // 2
    box = im[y0:y0 + side, x0:x0 + side]
    bgr = box[:, :, :3].astype(np.float32)
    p = cv2.resize(bgr, (N_GRID, N_GRID), interpolation=cv2.INTER_AREA)
    if box.shape[2] == 4:
        a = cv2.resize(box[:, :, 3], (N_GRID, N_GRID), interpolation=cv2.INTER_AREA)
        m = (a > 128) & INSIDE
    else:
        m = INSIDE.copy()
    return (p, m) if m.sum() >= MIN_CELLS else (None, None)


def template_set(agents, frac=INTERIOR_FRAC, mirror=False):
    out = []
    for a in agents:
        p = art_path(a)
        if p is None:
            continue
        pa, ma = template(p, frac, mirror)
        if pa is not None:
            out.append((pa, ma, a))
    return out


def score(icons, templates):
    """(accuracy, per-agent dict, results). One template per agent, nearest wins."""
    res = []
    for p, m, true, *_ in icons:
        best, bs = None, -2.0
        second = -2.0
        for tp, tm, name in templates:
            s = similarity(p, m, tp, tm)
            if s > bs:
                best, second, bs = name, bs, s
            elif s > second:
                second = s
        res.append((best == true, bs - second, best, true))
    if not res:
        return 0.0, {}, res
    acc = sum(r[0] for r in res) / len(res)
    per: dict[str, list[int]] = {}
    for ok, _, _, true in res:
        per.setdefault(true, [0, 0])
        per[true][0] += int(ok)
        per[true][1] += 1
    return acc, per, res


def icon_compositions(sid, src, rows):
    """Colour composition of every labelled icon interior, ring red excluded.

    The same disc the NCC descriptor uses (r * INTERIOR_FRAC), so the two
    representations are scored over identical pixels and any difference between
    them is the representation rather than the sampling.
    """
    from reticle.profiles import get_profile
    from minimap_icons import red_mask
    from minimap_portrait import composition

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    fps = float(src["fps"])
    cap = cv2.VideoCapture(src["path"])
    out = []
    for t in sorted({r["t_ms"] for r in rows}):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[my0:my1, mx0:mx1]
        red = red_mask(crop, 100)
        for r in [q for q in rows if q["t_ms"] == t]:
            rr = max(2, int(round(r["r"] * INTERIOR_FRAC)))
            y0, x0 = r["y"] - rr, r["x"] - rr
            if y0 < 0 or x0 < 0 or y0 + 2 * rr > crop.shape[0] or x0 + 2 * rr > crop.shape[1]:
                continue
            yy, xx = np.mgrid[0:2 * rr, 0:2 * rr]
            msk = (((yy - rr) ** 2 + (xx - rr) ** 2) <= rr * rr) \
                & ~red[y0:y0 + 2 * rr, x0:x0 + 2 * rr]
            if msk.sum() < 12:
                continue
            out.append((composition(crop[y0:y0 + 2 * rr, x0:x0 + 2 * rr], msk), r["agent"]))
    cap.release()
    return out


def art_composition(agent: str, frac: float = 1.0):
    """Composition of the official art over a central disc, intersected with its alpha."""
    from minimap_portrait import composition

    im = cv2.imread(str(art_path(agent)), cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    h, w = im.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = frac * min(h, w) / 2
    m = ((yy - h / 2) ** 2 + (xx - w / 2) ** 2) <= r * r
    if im.shape[2] == 4:
        m &= im[:, :, 3] > 128
    return composition(im[:, :, :3], m)


def run_composition(sid, src, rows, agents) -> None:
    from minimap_portrait import classify_composition

    icons = icon_compositions(sid, src, rows)
    print(f"\n=== composition (the method CLAUDE.md records as the one that transfers) ===")
    print(f"  {len(icons)} icons   scoreboard bars: 77.2% no-param, 83.5% held-out, "
          f"92.4% in-sample, 91.1% in-domain")
    for frac in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
        srcs = {a: art_composition(a, frac) for a in agents}
        per: dict[str, list[int]] = {}
        for hq, true in icons:
            name, _, _ = classify_composition(hq, srcs)
            per.setdefault(true, [0, 0])
            per[true][0] += int(name == true)
            per[true][1] += 1
        tot = sum(v[0] for v in per.values())
        tag = "   <- ZERO parameters" if frac == 1.0 else ""
        print(f"  disc frac {frac:.2f}   {tot/len(icons)*100:5.1f}%   " +
              "  ".join(f"{n[:4]}:{v[0]}/{v[1]}" for n, v in sorted(per.items())) + tag)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session")
    ap.add_argument("--sweep", action="store_true", help="leave-one-agent-out crop diagnostic")
    ap.add_argument("--composition", action="store_true",
                    help="score by colour composition instead of pixel NCC")
    a = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{a.session}.json").read_text())
    rows = load_agent_labels(a.session)
    if not rows:
        print(f"no agent labels for {a.session}")
        return 1
    prov: dict[str, int] = {}
    for r in rows:
        prov[r.get("by", "human")] = prov.get(r.get("by", "human"), 0) + 1
    print(f"{len(rows)} labelled icons   labelled by: {prov}")

    icons = [g for g in build_gallery(a.session, man["source"], rows) if g[2] != "question"]
    agents = sorted({g[2] for g in icons})
    counts = {n: sum(1 for g in icons if g[2] == n) for n in agents}
    print(f"{len(icons)} icons with an agent name, {len(agents)} classes: {counts}")
    if not icons:
        return 1
    floor = max(counts.values()) / len(icons)
    print(f"majority-class floor {floor*100:.1f}%   chance {100/len(agents):.1f}%"
          f"   in-domain one-template bar 70.4%")

    missing = [x for x in agents if art_path(x) is None]
    if missing:
        print(f"\nNO OFFICIAL ART for {missing} -- run ability_reference.py harvest")
        return 1

    if a.composition:
        run_composition(a.session, man["source"], [r for r in rows if r["agent"] != "question"],
                        agents)
        return 0

    print("\n=== zero free parameters: crop = INTERIOR_FRAC = %.2f ===" % INTERIOR_FRAC)
    for mirror in (False, True):
        acc, per, res = score(icons, template_set(agents, INTERIOR_FRAC, mirror))
        tag = "mirrored" if mirror else "as-is   "
        print(f"  {tag}  {acc*100:5.1f}%   " +
              "  ".join(f"{n}:{v[0]}/{v[1]}" for n, v in sorted(per.items())))
        if not mirror:
            base = res

    print("\n  confusions (as-is):")
    conf: dict[tuple[str, str], int] = {}
    for ok, _, pred, true in base:
        if not ok:
            conf[(true, pred)] = conf.get((true, pred), 0) + 1
    for (true, pred), c in sorted(conf.items(), key=lambda kv: -kv[1]):
        print(f"    {true:<9} -> {pred:<9} x{c}")

    if a.sweep:
        fracs = [round(0.25 + 0.05 * i, 2) for i in range(16)]
        print("\n=== crop sweep, leave-one-agent-out ===")
        print("  frac   overall   " + "  ".join(f"{n[:6]:>6}" for n in agents))
        table = {}
        for f in fracs:
            acc, per, _ = score(icons, template_set(agents, f))
            table[f] = per
            print(f"  {f:.2f}   {acc*100:5.1f}%   " +
                  "  ".join(f"{per.get(n,[0,1])[0]/max(1,per.get(n,[0,1])[1])*100:5.1f}%"
                            for n in agents))
        print("\n  held out per agent (frac fitted on the OTHER four):")
        tot = n_tot = 0
        for held in agents:
            best_f, best_v = None, -1.0
            for f in fracs:
                per = table[f]
                c = sum(per.get(n, [0, 0])[0] for n in agents if n != held)
                t = sum(per.get(n, [0, 1])[1] for n in agents if n != held)
                v = c / max(1, t)
                if v > best_v:
                    best_f, best_v = f, v
            got, n = table[best_f].get(held, [0, 0])
            tot += got
            n_tot += n
            print(f"    {held:<9} frac={best_f:.2f} (fit {best_v*100:.1f}%)"
                  f"   held-out {got}/{n} = {got/max(1,n)*100:.1f}%")
        print(f"    MEAN held-out {tot}/{n_tot} = {tot/max(1,n_tot)*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
