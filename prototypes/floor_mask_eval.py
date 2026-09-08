r"""Score a `floor_mask` variant against the painted map masks.

    .\.venv\Scripts\python.exe prototypes\floor_mask_eval.py [--variants both]

Why this file exists
--------------------
`floor_mask` was defined TWICE with different behaviour -- `reticle/minimap.py`
gating on `sat < 60 & val > 110`, `prototypes/minimap_icons.py` on
`sat < 20 & val > 100` plus a largest-component-and-bridge rule -- and the two
had been diverging since 2026-08-27 while `CLAUDE.md` recorded the fork as
byte-identical and therefore harmless. Fifteen prototypes imported one of them
and the shipped position track imported the other, so "which is right" was an
unanswered question sitting underneath every minimap number in the store.

Nothing scored them against each other, which is the whole reason the fork
survived: two implementations agree until one of them changes, and then nothing
notices unless something is measuring.

What the referee is, and what it is not
---------------------------------------
the `labels/map_mask/<sid>.png`, painted 2026-08-26 with `paint_map.py`.
Both are `compared_against_derived: false`, i.e. UNSEEDED -- the player painted the map,
not a correction to a derived mask -- which is the condition that makes them
usable at all. Seeding is the mistake this repo has recorded three times.

**The painting is the SEARCHABLE area and `floor_mask` is the OPAQUE SLAB.**
Those are related targets, not the same one, and the verdict on the
first painting was *that's not even close to pixel perfect ... but that's the
gist*. So this file reports a COMPARISON between two variants against a common
referee. It does not certify either one as correct, and an IoU here is not on
the same scale as one from `dynamic_eval --mask`, which scores `searchable`.

Read `recall` with suspicion and `IoU` as the answer
-----------------------------------------------------
The `sat < 60` variant is a near-strict SUPERSET of the `sat < 20` one -- the
latter adds 0.01% of the widget on Ascent and 0.11% on Lotus, none of it inside
the painting. A superset of the answer trivially contains the answer, so the
looser variant scores 100% recall on both sessions while admitting the
semi-transparent void that every content-based minimap approach has drowned in.
`IoU` is the column that separates them.

First run, 2026-09-06, before any change:

    a06f04a0059f  Ascent   sat<60   area 51.5%  recall 100.0%  prec 57.8%  IoU 57.8%
                           sat<20   area 36.2%  recall  94.9%  prec 78.0%  IoU 74.8%
    5822b6646448  Lotus    sat<60   area 42.2%  recall 100.0%  prec 74.0%  IoU 74.0%
                           sat<20   area 39.1%  recall  96.8%  prec 77.4%  IoU 75.5%

and the 15.2% of the widget the loose variant adds on Ascent is 90.1% OUTSIDE
the painting. That is the arbitration.

The residual is the BOMB SITES, and it is not a defect
--------------------------------------------------------
The 5.1% of the painting the tight gate misses on Ascent came out as two
compact blobs and three on Lotus -- each map's site count exactly -- all five at
saturation ~58, value ~153 where the slab is S=0 V=118. A site is TINTED, so it
fails `sat < 20` by construction. It is `minimap_geometry`'s PLANT class, and
`minimap_dynamic.searchable` already ORs it back in:

    floor_mask alone     Ascent recall  94.9%   Lotus  96.8%
    floor_mask | PLANT   Ascent recall 100.0%   Lotus 100.0%

That is the row callers actually run on, and it is why `--render` exists but
did not end in a question for the render localised the loss to five
blobs, and the blobs' own saturation named them without costing the player a minute.
**Look at the image before measuring it, then measure it before asking.**

The control is the painting's own metadata
-------------------------------------------
`metrics.record` wants an EXTERNAL truth, never this tool's own prior output.
The `.json` beside each painting carries `painted_frac`, written by
`paint_map.py` at paint time, and this file recomputes it off the `.png`. If
they disagree the label pair is corrupt and every number below is void -- which
is a real failure this cannot otherwise see, and it is checked before anything
is scored rather than after.
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
from reticle import geometry as _G                                  # noqa: E402
from reticle import minimap as mm                                 # noqa: E402

STORE = Path.home() / "reticle-store"

#: `minimap_geometry.PLANT`, inlined rather than imported so this file does not
#: drag in a module that rebuilds geometry on import.
PLANT = 5

#: Painted, unseeded, and on two different maps. Both are needed: the variants
#: differ by 15.2% of the widget on Ascent and only 3.3% on Lotus, so a single
#: session would make this look like a much closer call than it is.
SESSIONS = ("a06f04a0059f", "5822b6646448")


def painting(sid):
    """the mask and its metadata, or None. Refuses a SEEDED painting."""
    p = STORE / "labels" / "map_mask" / f"{sid}.png"
    if not p.is_file():
        return None
    meta = json.loads(p.with_suffix(".json").read_text())
    if meta.get("compared_against_derived"):
        # Scoring a rule against a painting seeded from that rule is the
        # `minimap_agent` mistake in a third costume. Refuse, do not discount.
        return None
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) > 127, meta


def geometry_static(sid):
    """The session's cached median widget. `static` is what floor_mask reads."""
    p = _G.path_of(sid, STORE)
    if p is None or not p.is_file():
        return None
    return np.load(p, allow_pickle=True)["static"]


def score(mask, truth):
    tp = int((mask & truth).sum())
    fp = int((mask & ~truth).sum())
    fn = int((~mask & truth).sum())
    return {
        "area": mask.mean(),
        "recall": tp / max(1, tp + fn),
        "precision": tp / max(1, tp + fp),
        "iou": tp / max(1, tp + fp + fn),
    }


def _with_plant(med, _cache={}):
    """`floor_mask` plus the tinted bomb sites -- what `searchable` composes.

    Scored as its own row because the two answer different questions and the
    difference is the whole residual: the slab is what is opaque, the site is
    what is opaque AND tinted, and only the union is the area a detection may
    occupy.
    """
    return mm.floor_mask(med) | (_cache["labels"] == PLANT)


def variants():
    """What gets scored: the slab, the slab plus sites, and any surviving fork.

    The first two are COMPOSITIONS and always both present -- they answer
    different questions (§ the bomb-sites note above) and reporting only one
    was how the residual looked like a defect for an afternoon.

    The third row is the CHECK. `prototypes.minimap_icons` appears only if it
    still defines its own `floor_mask` rather than re-exporting, so a fork
    reopening makes this print three rows instead of two. That is cheaper than
    remembering, which is the standard every convention here is held to.
    """
    out = {"reticle.minimap": mm.floor_mask,
           "reticle.minimap | PLANT": _with_plant}
    try:
        import minimap_icons as mi
        if mi.floor_mask.__module__ != mm.floor_mask.__module__:
            out["prototypes.minimap_icons"] = mi.floor_mask
    except Exception:
        pass
    return out


#: Ignore specks when rendering the misses -- the question is which ROOMS are
#: lost, and a 40 px fleck is not a room. Not a detector threshold: it only
#: decides what gets a label drawn on it.
RENDER_MIN_AREA = 200


def render_misses(sid, med, truth, mask, scale=2):
    """What the kept mask LOSES off the painting, as one labelled image.

    This exists because the answer is the and not derivable. The Boathouse --
    a real room rendered entirely void by a largest-component rule -- was named
    by eye in seconds after three analysis scripts had not found it, and the
    convention that came out of that is *on the FIRST failure of a perceptual
    question, build the tool that asks the player*.

    So this draws the question rather than a verdict: the widget as it actually
    looks, the painted area outlined, and each lost component ringed with its
    area. It states its own magnification, per `glance.py`'s rule that a
    rendering without a stated factor cannot be read back.
    """
    miss = (~mask & truth).astype(np.uint8)
    n, lbl, st, cen = cv2.connectedComponentsWithStats(miss, 8)
    big = [i for i in range(1, n) if st[i, 4] >= RENDER_MIN_AREA]

    img = cv2.resize(med, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    img = (img * 0.55).astype(np.uint8)          # dim, so the overlay reads

    up = lambda m: cv2.resize(m.astype(np.uint8), None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_NEAREST) > 0
    # Structural colour for the QUESTION, matching overlay.py and glance.py:
    # teal = kept by the mask, magenta = painted but LOST. Domain colour is not
    # in play here, so the two do not collide.
    img[up(mask & truth)] = (img[up(mask & truth)] * 0.6 + np.array([90, 60, 0]) * 0.4)
    for i in big:
        img[up(lbl == i)] = (0, 40, 235)

    for i in big:
        cx, cy = int(cen[i][0] * scale), int(cen[i][1] * scale)
        r = int(max(14, (st[i, 4] ** 0.5) * scale))
        cv2.circle(img, (cx, cy), r, (0, 40, 235), 2)
        cv2.putText(img, f"{int(st[i, 4])}px", (cx - r, cy - r - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, f"{int(st[i, 4])}px", (cx - r, cy - r - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 40, 235), 1, cv2.LINE_AA)

    bar = int(10 * scale)                        # a 10-SOURCE-pixel scale bar
    h = img.shape[0]
    cv2.line(img, (12, h - 16), (12 + bar, h - 16), (255, 255, 255), 3)
    cv2.putText(img, f"{sid}  INTER_NEAREST {scale}x  |--| 10px source",
                (12, h - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
                cv2.LINE_AA)
    cv2.putText(img, "teal = kept   RED = painted by the player, LOST by the mask",
                (12, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
                cv2.LINE_AA)
    return img, [(int(st[i, 4]), int(cen[i][0]), int(cen[i][1])) for i in big]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="*", default=None)
    ap.add_argument("--render", metavar="DIR",
                    help="write a labelled image of what the mask LOSES, for the player")
    args = ap.parse_args()
    sids = args.sessions or list(SESSIONS)

    impls = variants()
    print(f"{len(impls)} reachable floor_mask implementation"
          f"{'' if len(impls) == 1 else 's'}: {', '.join(impls)}\n")

    print(f"{'session':>14} {'variant':>26} {'area':>7} {'recall':>8} "
          f"{'prec':>7} {'IoU':>7}")
    for sid in sids:
        got = painting(sid)
        if got is None:
            print(f"{sid:>14}   no unseeded painting -- skipped")
            metrics.record("floor_mask_eval", session=sid, values={},
                           deps={"referee": "labels/map_mask"},
                           status=metrics.CANNOT_ANSWER,
                           note="no unseeded painted mask")
            continue
        truth, meta = got
        med = geometry_static(sid)
        if med is None or med.shape[:2] != truth.shape:
            print(f"{sid:>14}   no geometry npz, or shape mismatch -- skipped")
            metrics.record("floor_mask_eval", session=sid, values={},
                           deps={"referee": "labels/map_mask"},
                           status=metrics.CANNOT_ANSWER,
                           note="no geometry static, or it does not match the painting")
            continue

        # EXTERNAL control: the painting's own recorded fraction, written by
        # paint_map.py at paint time, against what the png actually holds.
        control = [{"name": "painted_frac", "observed": round(float(truth.mean()), 4),
                    "expected": round(float(meta["painted_frac"]), 4), "tol": 0.001,
                    "truth_source": meta.get("by", "human")}]

        _with_plant.__defaults__[0]["labels"] = np.load(
            _G.require(sid, STORE), allow_pickle=True)["labels"]
        for name, fn in impls.items():
            s = score(fn(med), truth)
            print(f"{sid:>14} {name:>26} {100 * s['area']:6.1f}% "
                  f"{100 * s['recall']:7.1f}% {100 * s['precision']:6.1f}% "
                  f"{100 * s['iou']:6.1f}%")
            metrics.record(
                "floor_mask_eval", part=name, session=sid,
                values={k: round(float(v), 4) for k, v in s.items()},
                deps={"impl": metrics.fingerprint(fn),
                      "referee": "labels/map_mask",
                      "seeded": str(meta["compared_against_derived"])},
                context={"painted_frac": round(float(truth.mean()), 4),
                         "widget_w": int(med.shape[1])},
                controls=control,
            )

        if args.render:
            out = Path(args.render)
            out.mkdir(parents=True, exist_ok=True)
            img, lost = render_misses(sid, med, truth, mm.floor_mask(med))
            f = out / f"{sid}.floor_mask_misses.png"
            cv2.imwrite(str(f), img)
            print(f"{'':>14} lost components >= {RENDER_MIN_AREA}px: "
                  f"{[a for a, _, _ in lost]} at {[(x, y) for _, x, y in lost]}")
            print(f"{'':>14} -> {f}")

        if len(impls) == 2:
            a, b = (fn(med) for fn in impls.values())
            for m, other, nm in ((a, b, list(impls)[0]), (b, a, list(impls)[1])):
                extra = m & ~other
                if extra.sum():
                    print(f"{'':>14} {nm:>26}  adds {100 * extra.mean():.2f}% of the "
                          f"widget, {100 * (extra & truth).sum() / extra.sum():.1f}% "
                          f"of it inside the painting")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
