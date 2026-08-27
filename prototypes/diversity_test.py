"""Does appearance-diverse selection see more KINDS than random? Test offline.

    .\\.venv\\Scripts\\python.exe prototypes\\diversity_test.py a06f04a0059f

Why this exists
---------------
Grant, mid-pass: *the vast majority of abilities caught in this are stationary
deployed abilities ... ideally the search would be for unique ability icons.*
Positional dedup cannot deliver that, because five Sonic Sensors at five places
are five positions showing one glyph.

Two candidate fixes were proposed. The first, **onset sampling**, was tested
against Grant's existing Ascent labels and FAILED -- badly enough that shipping
it would have made the pass worse:

    onset (new)     n=130   32% real objects   88 nothing    8 ability
    already there   n=107   57% real objects   46 nothing   45 ability

Noise is maximally novel, so preferring new blobs prefers flicker. Onset stays
as a FEATURE -- `player` is 21/23 onset against `ability` 8/53, which separates
two classes the current features do not -- but it is a bad sampler.

This tests the second fix the same way, on the same rows, before it costs a
keypress: **farthest-point selection over an appearance descriptor.** Pick
greedily, each new question being the candidate most unlike everything already
picked. The comparison is against random selection of the same size, scored on
what a labeller would actually have SEEN:

* how many of the nine kinds appear at all;
* how many RARE-kind rows are seen (ping, spike, question, barrier, other) --
  the classes a uniform sample starves;
* how many `nothing` rows are spent.

Random is run many times and reported as a mean, because a single random draw
is not a baseline.

The descriptor is deliberately plain: a z-scored 12x12 grey patch (shape) plus
`minimap_portrait.composition()` (colour, layout-free), each L2-normalised and
concatenated. A Cypher cam ROTATES, so shape will over-split it into several
clusters -- for SELECTION that is harmless, since over-splitting only costs a
mildly redundant question, where under-splitting costs a whole class.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import minimap_dynamic as md                                      # noqa: E402
from minimap_portrait import composition                          # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402

STORE = Path.home() / "reticle-store"
PATCH = 24          # source pixels cropped around a blob
GRID = 12           # resized to this before z-scoring
RARE = {"ping", "spike", "question", "barrier", "other"}


def descriptor(crop, x, y):
    """Shape (z-scored grey patch) + colour (layout-free histogram)."""
    h, w = crop.shape[:2]
    r = PATCH // 2
    y0, x0 = max(0, y - r), max(0, x - r)
    tile = crop[y0:min(h, y + r), x0:min(w, x + r)]
    if tile.size == 0:
        return None
    g = cv2.resize(cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY), (GRID, GRID),
                   interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    g = (g - g.mean()) / (g.std() + 1e-6)
    g /= np.linalg.norm(g) + 1e-6
    c = composition(cv2.resize(tile, (GRID, GRID), interpolation=cv2.INTER_AREA))
    c = c / (np.linalg.norm(c) + 1e-6)
    return np.concatenate([g, c]).astype(np.float32)


def farthest_point(vecs, n, seed=0):
    """Greedy max-min: each pick is the point most unlike everything picked."""
    n = min(n, len(vecs))
    rng = random.Random(seed)
    first = rng.randrange(len(vecs))
    chosen = [first]
    d = np.linalg.norm(vecs - vecs[first], axis=1)
    for _ in range(n - 1):
        i = int(np.argmax(d))
        chosen.append(i)
        d = np.minimum(d, np.linalg.norm(vecs - vecs[i], axis=1))
    return chosen


def score(kinds, name):
    c = collections.Counter(kinds)
    rare = sum(v for k, v in c.items() if k in RARE)
    return (f"{name:<22} kinds {len(c):2d}/9   rare {rare:3d}   "
            f"nothing {c.get('nothing', 0):3d}/{len(kinds)}   "
            f"ability {c.get('ability', 0):3d}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--pick", type=int, default=100)
    ap.add_argument("--trials", type=int, default=200)
    a = ap.parse_args(argv)

    man = json.loads((STORE / "manifests" / f"{a.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)

    p = STORE / "labels" / "minimap_dynamic" / f"{a.session}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    last = {}
    for r in rows:
        last[(r["t_ms"], r["x"], r["y"])] = r
    rows = [r for r in last.values() if r.get("by") == "grant" and r.get("kind")]
    print(f"{len(rows)} answered rows")

    byt = collections.defaultdict(list)
    for r in rows:
        byt[r["t_ms"]].append(r)
    cap = cv2.VideoCapture(src["path"])
    vecs, kinds = [], []
    for t, rs in sorted(byt.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        for r in rs:
            v = descriptor(crop, r["x"], r["y"])
            if v is None:
                continue
            vecs.append(v)
            kinds.append(r["kind"])
    cap.release()
    vecs = np.stack(vecs)
    print(f"{len(vecs)} descriptors, {vecs.shape[1]} dims")
    print()
    print(score(kinds, "WHOLE SET"))

    idx = farthest_point(vecs, a.pick)
    print(score([kinds[i] for i in idx], f"farthest-point n={a.pick}"))

    rng = random.Random(5)
    accum = collections.Counter()
    nk = rare = noth = abil = 0
    for _ in range(a.trials):
        s = rng.sample(range(len(kinds)), min(a.pick, len(kinds)))
        ks = [kinds[i] for i in s]
        c = collections.Counter(ks)
        nk += len(c)
        rare += sum(v for k, v in c.items() if k in RARE)
        noth += c.get("nothing", 0)
        abil += c.get("ability", 0)
        accum.update(ks)
    t = a.trials
    print(f"{'random mean of ' + str(t):<22} kinds {nk / t:4.1f}/9   "
          f"rare {rare / t:5.1f}   nothing {noth / t:5.1f}/{a.pick}   "
          f"ability {abil / t:5.1f}")
    print()
    print("Rare classes are the ones a uniform sample starves, and they are why")
    print("the first pass was relaunched six times. `nothing` is the budget line:")
    print("questions spent confirming an artefact teach the least per keypress.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
