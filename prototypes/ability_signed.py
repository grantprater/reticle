"""Does the SIGN of the two-state residual separate ability glyphs from viewcone noise?

    .\\.venv\\Scripts\\python.exe prototypes\\ability_signed.py <session>...

The question
------------
`minimap_dynamic.detect` computes

    raw = max(lo - g, g - hi, 0)

(`minimap_dynamic.py`, the `static_gray2` branch) which is the right test for
"outside the interval the two legitimate resting colours span" -- and it
**collapses the sign**. Two physically opposite things end up in one channel:

* the **viewcone is a brightness LIFT** -- measured p90 +51 on Split, +8 on
  Ascent (`prototypes/CLAUDE.md`). A cone edge sweeping past a pixel pushes it
  ABOVE `hi`;
* **every placed Cypher device at rest is a black/near-achromatic disc**
  (the controlled clips, 2026-09-02). Ink on the map pushes a pixel BELOW
  `lo`.

So the dominant nuisance and the class we most want are opposite excursions of
the same statistic, competing in one magnitude. Splitting them costs one line
and cannot lose information -- the current channel is recoverable as the max.

Why it is measured HERE and not by re-running the scanner
----------------------------------------------------------
Re-running `scan_ability_clip.py` would rewrite
`labels/ability_candidates/<sid>.jsonl` and **orphan every answer the player has
given**, since the label store keys on `(t_ms, x, y)` -- the defect
`ability_eval.py` documents and that already cost 19 of 50 labels on
`eb10db50b1fb` and 39 of 40 on `2ba870ccbd50`. So this recomputes the feature at
the ALREADY-LABELLED positions instead, the pattern `dynamic_eval.features`
established: a label row carries the answer and enough to find the pixel again,
and everything else is recomputed. Nothing is written to the label store.

`WIN` is the sampling radius. The excursion is read as a max over a small window
rather than at the exact pixel because the labelled `(x, y)` is a blob centroid
and a thin glyph's ink need not sit under its own centroid -- the same reason
`dynamic_eval` reads `tophat` over a 5x5.

What it measured, 2026-09-03
-----------------------------
The sign inverts cleanly between the two classes, pooled over both sessions
(9 real, 88 not):

                  dark (below lo)        bright (above hi)
    REAL          med 102                med 10
    NOT           med   0                med 59

and `dark > bright` is worth more than every shape feature tried on this class
put together. Per session, so the transfer is visible rather than pooled away:

                                    79a706a7ce4c      eb10db50b1fb
                                    (bigmap)          (small widget)
    no filter                        100% /   6.1%     100% /  16.1%
    self_icon_dist >= 7 (SHIPPED)    100% /   7.3%     100% /  21.7%
    self>=7, nobs>=5, born>0         100% /  13.8%     100% /  55.6%
       + dark > bright               100% /  40.0%     100% / 100.0%
    dark > bright ALONE              100% /  16.7%     100% /  38.5%

It has never cost a true positive on either session, and **on the small widget
it removes every false positive**. `dark > bright` on its own, with no other
gate, already beats the shipped `self_icon_dist` filter on both.

Why this is more likely to transfer than the features that did not: it is a
MECHANISM, not a fitted threshold. `device_glyph_score` and `host_span` were
guesses about shape that happened to fit one object; this says ink is darker
than the map and a viewcone is brighter, which is a fact about how the widget is
drawn. There is no number in it to overfit -- `dark > bright` has no parameter.

**The population limit, and it is the one that matters.** All 9 positives are
`colour: none` -- the black/achromatic Cypher devices. So this is measured on
ONE class, and there is a predictable failure mode for the others:
`minimap_dynamic.detect` fires a second way, `sat > COLOUR_SAT`, which exists
precisely because **Brimstone's Orbital Strike marker measured gray 114 against
an unlit reference of 117** -- invisible to brightness differencing at any
threshold. For such a candidate `dark` and `bright` are both ~0, so
`dark > bright` is FALSE and a naive gate would DELETE it. That is the
aspect-filter mistake in a new costume (*0 of 55 hand-marked icons have
aspect >= 2.0* -- true, and about the wrong population).

So `sign_ok` below is an OR mirroring the OR already in `detect()`: a coloured
candidate is never rejected on sign. **The coloured branch is unmeasured** --
there is not one coloured positive in the label set to test it against, and the
right way to get one is a controlled clip for an agent whose kit tints
(Brimstone, Skye), not a threshold argued from here.
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
from reticle import metrics                                       # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from ability_eval import join, gate, _sha, STORE                  # noqa: E402

#: Half-width of the window the excursion is read over, in minimap pixels.
WIN = 2


def signed_at(sid, rows):
    """Add `dark` and `bright` excursions to each row, in place.

    dark   = max(lo_gray - g, 0)   ink laid over the map: below the darker of
                                   the two legitimate resting colours
    bright = max(g - hi_gray, 0)   a lift above the brighter one, which is what
                                   the viewcone does

    Both are zero for a pixel resting at either legitimate state, so a pixel
    that is merely mid-transition between unlit and lit scores zero on both --
    which is the two-state model's whole point, preserved.
    """
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    z = np.load(STORE / "geometry" / f"{sid}.npz")
    lo = z["lo_gray"].astype(np.int16)
    hi = z["hi_gray"].astype(np.int16)
    cap = cv2.VideoCapture(src["path"])
    byt: dict = {}
    for r in rows:
        byt.setdefault(r["t_ms"], []).append(r)
    for t, rs in sorted(byt.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        g = cv2.cvtColor(fr[my0:my1, mx0:mx1], cv2.COLOR_BGR2GRAY).astype(np.int16)
        if g.shape != lo.shape:
            print(f"   {sid}: frame crop {g.shape} != geometry {lo.shape} -- skipping")
            break
        dark = np.maximum(lo - g, 0)
        bright = np.maximum(g - hi, 0)
        for r in rs:
            x, y = int(r["x"]), int(r["y"])
            sl = (slice(max(0, y - WIN), y + WIN + 1), slice(max(0, x - WIN), x + WIN + 1))
            r["dark"] = int(dark[sl].max())
            r["bright"] = int(bright[sl].max())
    cap.release()
    return [r for r in rows if "dark" in r]


def sign_ok(r):
    """The shippable form of the sign test. Never rejects a COLOURED candidate.

    `dark > bright` is measured only on achromatic positives (see the module
    docstring). A candidate that reached the stream through `detect`'s
    saturation trigger rather than its brightness trigger can legitimately have
    both excursions near zero -- Orbital Strike's marker sits at gray 114
    against an unlit 117 -- so applying the sign test to it would delete the one
    class the saturation trigger was added for.

    `colour_local` is the field to read, not `colour`: `ability_shape.local_colour`
    exists because the production blob dilutes colour when it fuses with
    achromatic geometry (one instance read HSV sat 206 and still scored
    `colour_frac` 0.06, under the 0.08 cutoff).
    """
    if (r.get("colour_local") or r.get("colour") or "none") != "none":
        return True
    return r.get("dark", 0) > r.get("bright", 0)


def q(vals):
    if not vals:
        return "  --"
    v = sorted(vals)
    return (f"n={len(v):3d} p10={v[len(v) // 10]:4d} med={v[len(v) // 2]:4d} "
            f"p90={v[min(len(v) - 1, 9 * len(v) // 10)]:4d}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    args = ap.parse_args()

    pool = []
    for sid in args.sessions:
        rows, diag = join(sid)
        if diag["n_pos"] == 0 or diag["n_neg"] == 0:
            print(f"\n=== {sid} === refused: {diag['n_pos']} pos / {diag['n_neg']} neg")
            continue
        rows = signed_at(sid, rows)
        pos = [r for r in rows if r["_true"]]
        neg = [r for r in rows if not r["_true"]]
        print(f"\n=== {sid} ===  {len(pos)} real, {len(neg)} not")
        print(f"   REAL  dark   {q([r['dark'] for r in pos])}")
        print(f"   NOT   dark   {q([r['dark'] for r in neg])}")
        print(f"   REAL  bright {q([r['bright'] for r in pos])}")
        print(f"   NOT   bright {q([r['bright'] for r in neg])}")
        for r in rows:
            r["_sid"] = sid
        pool += rows

    if not pool:
        return 1
    pos = [r for r in pool if r["_true"]]
    neg = [r for r in pool if not r["_true"]]
    print(f"\n=== POOLED ===  {len(pos)} real, {len(neg)} not")
    print(f"   REAL  dark   {q([r['dark'] for r in pos])}")
    print(f"   NOT   dark   {q([r['dark'] for r in neg])}")
    print(f"   REAL  bright {q([r['bright'] for r in pos])}")
    print(f"   NOT   bright {q([r['bright'] for r in neg])}")

    print("\n   operating points, pooled (recall / precision):")
    base = (7, 5, True)                       # the fixed point ability_eval ships
    rows_b = [r for r in pool if gate(r, *base)]

    def sc(name, keep, src):
        tp = sum(1 for r in src if r["_true"] and keep(r))
        fp = sum(1 for r in src if not r["_true"] and keep(r))
        fn = sum(1 for r in src if r["_true"] and not keep(r))
        rec = tp / (tp + fn) if (tp + fn) else float("nan")
        pr = tp / (tp + fp) if (tp + fp) else float("nan")
        print(f"   {name:<44} TP {tp:3d} FP {fp:3d}  "
              f"recall {rec * 100:5.1f}%  prec {pr * 100:5.1f}%")
        return {"tp": tp, "fp": fp, "recall": round(rec, 4), "precision": round(pr, 4)}

    sc("self>=7,nobs>=5,born>0  (ability_eval point)", lambda r: True, rows_b)
    got = sc("   + sign_ok (SHIPPABLE)", sign_ok, rows_b)
    sc("   + dark > bright (raw, no colour escape)",
       lambda r: r["dark"] > r["bright"], rows_b)
    for d in (10, 20, 30):
        sc(f"   + dark >= {d}", lambda r, d=d: r["dark"] >= d, rows_b)
    print("\n   sign alone, no other gate:")
    sc("sign_ok", sign_ok, pool)
    sc("dark > bright", lambda r: r["dark"] > r["bright"], pool)

    print("\n   per session, so transfer is visible rather than pooled away:")
    for sid in args.sessions:
        s = [r for r in pool if r["_sid"] == sid]
        if s:
            sc(f"{sid}: no filter", lambda r: True, s)
            sc(f"{sid}: self>=7,nobs>=5,born>0 + sign_ok",
               lambda r: gate(r, *base) and sign_ok(r), s)

    metrics.record(
        "ability_signed", part="pooled", session="+".join(args.sessions),
        values=got,
        # `recorded_gate` is a DEP. The first run of this file recorded the
        # `dark>=20` line and the second recorded `sign_ok`; with only the
        # feature fingerprint in deps that read as BROKEN -- same deps, moved
        # numbers -- which is the harness being right. Naming the gate makes the
        # two INCOMPARABLE, which is what they are: different quantities, not a
        # regression.
        deps={"features": metrics.fingerprint(signed_at, gate, sign_ok, WIN=WIN),
              "base_point": "self>=7,nobs>=5,onset=1",
              "recorded_gate": "sign_ok",
              "candidates_sha": "+".join(
                  _sha(STORE / "labels" / "ability_candidates" / f"{s}.jsonl")
                  for s in args.sessions)},
        context={"n_pos": len(pos), "n_neg": len(neg)},
    )
    print()
    print(metrics.report(tool="ability_signed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
