"""Fit the ONE crop that turns scoreboard art into a minimap icon template.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_portrait_transform.py <session> \\
        --enemy omen,jett,killjoy,skye,iso

Why this is the whole game
--------------------------
`minimap_portrait.py` identifies enemies at 88.6% using a gallery mined from
the minimap itself -- which means every session needs its own hand-labelled
gallery before it can identify anything. That does not scale, and it is the
only reason identification is not already a shipped stage.

Grant: **the minimap icon is a circular CROP of the agent's art, at a
consistent size and scale**, and the Tab scoreboard holds that art in the same
orientation. If that is true then ONE crop -- a centre and a radius, in units
of scoreboard row height -- converts any agent's scoreboard portrait into a
minimap-domain template. Fit it once, and a new capture needs no labels at all:
read the ten agent names off the scoreboard, cut the ten portraits, synthesize
ten templates, classify.

The protocol, and why it is this one
------------------------------------
Fitting a crop by maximising agreement with the icons it is being fitted to is
how I got 46 of 71 icons called the same agent the first time I tried this: a
free-floating objective finds a degenerate window and reports a great score on
it. So the crop is fitted and judged on DIFFERENT AGENTS:

    for each agent A of the five:
        fit (cx, cy, R) on the OTHER four agents' icons
        synthesize all five templates with it
        score A's icons against those five

A is never in the fit, so a crop that works by memorising cannot score. The
number that matters is the mean over the five held-out agents, and the spread
across them matters nearly as much -- one agent carrying the average is a
different result from five agreeing.

The flip is fitted as a control rather than assumed. Grant says the scoreboard
and the minimap share an orientation and the ENEMY ROSTER is the mirrored
surface; this tests that on the pixels instead of taking it on trust, and the
answer should be that unflipped wins clearly.

RESULT, 2026-08-26: the premise is FALSE. The minimap icon is not a crop of
the scoreboard bust
--------------------------------------------------------------------------
Held-out accuracy came out at **24.7% against a 20% chance rate** (mirrored
17.3%, so the orientation claim itself holds -- as-is beats mirrored, as Grant
said). But the number that settles it is not that one, because a weak held-out
score could always be blamed on the fit. This is the one that settles it:

    crop fitted to ONE agent's own icons, no generalisation asked for at all
    -- the best case the parametrisation can possibly produce

        agent     best resemblance      in-domain icon-to-icon
        omen             0.215                   0.513
        jett             0.236                   0.624
        killjoy          0.160                   0.904
        skye             0.630                   0.974
        iso              0.649                   0.891

For Omen, Jett and Killjoy **no crop of the scoreboard art resembles their
minimap icons at all**, and the per-agent optima disagree on where the crop is
(cy 0.22 for Omen against 0.50 for Skye, r 0.17 for Jett against 0.26 for
Skye). Two agents reach 0.63-0.65 and still fall far short of the 0.89-0.97
that two real icons of the same agent reach.

A wrong crop is a fixable problem; three agents at 0.16-0.24 in the best case
is a different asset. The minimap avatar appears to be its own render -- not
the bust rescaled -- and the agents it fails on are the ones with strong
silhouette furniture: Omen's hood, Jett's hair, Killjoy's beanie and glasses.
Those are exactly what a differently-framed render would move.

Grant's underlying observation is not what failed here. The icon IS a circle at
a consistent scale, and orientation does match. What failed is the inference I
drew from it -- that the circle is cut from the surface the scoreboard shows.

**Still untested: the KILLFEED portrait**, which is the surface Grant named
first and the only one this has not tried. It is small and square, closer to
the icon in scale than a 42 px bust, and `killfeed.py` already locates entry
geometry. If that fails the same way, then no surface in the capture carries
the minimap's art and a cross-session gallery has to be seeded from the minimap
itself -- one labelled session per agent, reused forever, which is still far
better than one per capture.

What "working" would mean here
------------------------------
Not 88.6%. A synthesized template is one exemplar per agent, and the in-domain
result already showed that a single template per agent loses ~23 points to a
gallery of exemplars, because the triangle and the background move. So the bar
is: does the synthesized template beat chance decisively and land near the
70.4% that ONE in-domain median template scored? If it does, the transform is
real and the remaining gap is appearance modes -- which can be manufactured
(rotate a triangle over it, composite it on sampled map backgrounds) rather
than labelled. If it lands near 20%, the crop family is wrong again.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import minimap_portrait as mp                                     # noqa: E402

STORE = Path.home() / "reticle-store"

# Search grid, in units of scoreboard ROW HEIGHT so it is resolution-free.
# Deliberately wide: the point of the exercise is that I do not know where the
# crop is, and the last time I guessed a family I guessed wrong.
CX = np.arange(0.15, 0.70, 0.04)
CY = np.arange(0.10, 0.85, 0.04)
RR = np.arange(0.14, 0.60, 0.03)


def synth(art, cx, cy, r, flip):
    """A minimap-domain template from scoreboard art: circular crop, resampled.

    `cx`, `cy`, `r` are fractions of the row height, which is `art.shape[0]`.
    Cut as a square and resized with INTER_AREA, exactly as `descriptor` does
    to a real icon, so the two are the same kind of thing before they are
    compared.
    """
    h = art.shape[0]
    px, py, pr = cx * h, cy * h, r * h
    x0, y0 = int(round(px - pr)), int(round(py - pr))
    side = max(3, int(round(2 * pr)))
    if x0 < 0 or y0 < 0 or y0 + side > art.shape[0] or x0 + side > art.shape[1]:
        return None
    sub = art[y0:y0 + side, x0:x0 + side]
    if flip:
        sub = sub[:, ::-1]
    return cv2.resize(sub, (mp.N_GRID, mp.N_GRID),
                      interpolation=cv2.INTER_AREA).astype(np.float32)


def prepare(icons, names):
    """Pre-normalise every icon once, so the crop search only touches templates.

    The search evaluates thousands of crops against the same icons, and the
    icon side of a masked correlation does not depend on the crop at all --
    only the template does. Hoisting it out is the difference between a fit
    that takes minutes and one that takes an hour, and it changes no arithmetic.

    Each icon becomes its mask, its mean-subtracted unit-norm vector per
    channel, and the index of its true agent.
    """
    out = []
    for p, m, name in icons:
        if name not in names:
            continue
        v = np.empty((3, int(m.sum())), np.float32)
        ok = True
        for ch in range(3):
            a = p[:, :, ch][m].astype(np.float32)
            a = a - a.mean()
            n = np.linalg.norm(a)
            if n <= 0:
                ok = False
                break
            v[ch] = a / n
        if ok:
            out.append((m, v, names.index(name)))
    return out


def score(prepped, tpl_stack):
    """Accuracy of nearest synthesized template, over pre-normalised icons.

    `tpl_stack` is (n_agents, N, N, 3). The template has to be re-normalised
    inside each icon's own mask -- a mean taken over the full disc is not the
    mean over the part of it that survived the ring -- so that is what happens
    here, but for all agents at once.
    """
    if not prepped:
        return 0.0
    ok = 0
    for m, v, y in prepped:
        # (n_agents, cells, 3) -> per channel, mean-subtract inside the mask
        t = tpl_stack[:, m, :]
        t = t - t.mean(axis=1, keepdims=True)
        nrm = np.linalg.norm(t, axis=1, keepdims=True)
        np.maximum(nrm, 1e-6, out=nrm)
        t /= nrm
        # t is (agents, cells, channels) and v is (channels, cells); sum over
        # both cells and channels. A constant factor does not move an argmax,
        # so this is the per-channel mean up to a factor of three.
        s = np.einsum("ack,kc->a", t, v)
        ok += int(np.argmax(s)) == y
    return ok / len(prepped)


def resemblance(prepped, tpl_stack):
    """Mean correlation between each icon and the template of its OWN agent.

    This, not accuracy, is what the crop is fitted on -- and the first version
    got it wrong. Fitted on discrimination the search chose a 7 px window on the
    mouth and chin: a small distinctive patch separates four known agents
    in-sample better than the correct framing does, so the objective rewarded a
    crop that looks nothing like an icon. Held-out accuracy then came out at
    16.4% against a 20% chance rate -- below chance, which is the signature of a
    fit that memorised.

    Resemblance has a physical meaning the crop either has or does not: the
    transform is supposed to REPRODUCE the icon. It also cannot be gamed the
    same way, because correlation against a flat or tiny patch is near zero
    rather than high.
    """
    if not prepped:
        return -1.0
    tot = 0.0
    for m, v, y in prepped:
        t = tpl_stack[y][m]
        s = 0.0
        for ch in range(3):
            a = t[:, ch].astype(np.float32)
            a = a - a.mean()
            n = np.linalg.norm(a)
            if n > 0:
                s += float(a @ v[ch]) / n
        tot += s / 3
    return tot / len(prepped)


def fit(prepped, art_by_agent, names, flip):
    """Best (cx, cy, r) by RESEMBLANCE over `prepped`."""
    best = None
    for r in RR:
        for cx in CX:
            for cy in CY:
                ts = [synth(art_by_agent[n], cx, cy, r, flip) for n in names]
                if any(t is None for t in ts):
                    continue
                a = resemblance(prepped, np.stack(ts))
                if best is None or a > best[0]:
                    best = (a, cx, cy, r)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--enemy", required=True,
                    help="the five enemy agent names in scoreboard ROW order")
    ap.add_argument("--sheet")
    args = ap.parse_args()
    enemy = [s.strip() for s in args.enemy.split(",")]

    z = np.load(STORE / "rosters" / f"{args.session}.scoreboard.npz")
    teams = list(z["teams"])
    rows = [z[f"row{k}"] for k in range(len(teams))]
    art = {name: rows[i] for name, i in
           zip(enemy, [k for k, t in enumerate(teams) if str(t) == "enemy"])}
    if len(art) != 5:
        print(f"expected 5 enemy rows, found {len(art)}")
        return 1
    print(f"scoreboard art: {', '.join(art)}  (row height {rows[0].shape[0]} px)")

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    labels = [r for r in mp.load_agent_labels(args.session) if r["agent"] != "question"]
    g = mp.build_gallery(args.session, man["source"], labels)
    icons = [(p, m, n) for p, m, n, _, _ in g]
    per = {n: sum(1 for x in icons if x[2] == n) for n in art}
    print(f"{len(icons)} labelled enemy icons: {per}")
    missing = [n for n in art if per.get(n, 0) == 0]
    if missing:
        print(f"  no icons for {missing} -- they can be templates but not tests")

    for flip in (False, True):
        print(f"\n{'MIRRORED' if flip else 'AS-IS'} scoreboard art")
        held = []
        names = list(art)
        for a in names:
            if per.get(a, 0) == 0:
                continue
            train = prepare([x for x in icons if x[2] != a], names)
            test = prepare([x for x in icons if x[2] == a], names)
            acc, cx, cy, r = fit(train, art, names, flip)
            h = score(test, np.stack([synth(art[n], cx, cy, r, flip) for n in names]))
            held.append(h)
            print(f"  held out {a:>8s}  n={len(test):3d}   resemblance on the "
                  f"other four {acc:5.3f}   HELD OUT acc {h*100:5.1f}%   "
                  f"(cx {cx:.2f} cy {cy:.2f} r {r:.2f})")
        if held:
            print(f"  mean held-out {np.mean(held)*100:.1f}%  "
                  f"spread {min(held)*100:.1f}-{max(held)*100:.1f}%  "
                  f"(chance {100/len(art):.0f}%)")

    # And the crop fitted on everything, for the record and for the sheet. This
    # one is NOT a held-out number and must never be quoted as accuracy.
    names = list(art)
    acc, cx, cy, r = fit(prepare(icons, names), art, names, False)
    print(f"\ncrop fitted on all five (in-sample, NOT an accuracy): "
          f"{acc*100:.1f}% at cx {cx:.2f} cy {cy:.2f} r {r:.2f}")
    out = STORE / "rosters" / f"{args.session}.transform.json"
    out.write_text(json.dumps({"cx": float(cx), "cy": float(cy), "r": float(r),
                               "flip": False, "in_sample_resemblance": float(acc),
                               "n_grid": mp.N_GRID}, indent=1))
    print(f"  wrote {out}")
    if args.sheet:
        S = 84
        tps = {n: synth(v, cx, cy, r, False) for n, v in art.items()}
        top = np.hstack([cv2.resize(art[n], (S, S), interpolation=cv2.INTER_NEAREST)
                         for n in art])
        mid = np.hstack([cv2.resize(tps[n].astype(np.uint8), (S, S),
                                    interpolation=cv2.INTER_NEAREST) for n in art])
        bot = []
        for n in art:
            ex = next((x[4] for x in g if x[2] == n), np.zeros((S, S, 3), np.uint8))
            bot.append(cv2.resize(ex, (S, S), interpolation=cv2.INTER_NEAREST))
        sheet = np.vstack([top, mid, np.hstack(bot)])
        cv2.imwrite(args.sheet, sheet)
        print(f"  wrote {args.sheet} -- scoreboard art / synthesized / a real icon")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
