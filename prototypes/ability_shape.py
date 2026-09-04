"""Raw-frame shape and colour re-checks for ability candidates, built
2026-09-02 after `scan_ability_clip.py`'s first real run on `eb10db50b1fb`
came back 19 of 20 `not_ability` -- and the player, looking at the junk, named the
actual visual test that should have separated them: a real device icon is a
high-contrast, hard-edged ring; the junk was flat gray patches and smooth
lighting gradients.

Why this doesn't reuse the diff/top-hat pipeline
-------------------------------------------------
Two earlier numeric attempts both failed by measuring the wrong thing --
grayscale patch variance and diff-blob circularity, both computed from the
TOP-HATTED DIFFERENCE blob rather than the object's real appearance. That
blob's shape is an artefact of `DIFF_MIN` and the top-hat kernel size, not the
icon: it can merge a real icon with adjacent geometry the top-hat fused in
(diluting anything measured over its area), or barely register a long-placed
device that baked into its own static reference (`a06f04a0059f`'s Sonic
Sensor scored a 4px blob this way -- absurd for an object that renders at
200-500px). Both functions here work on the RAW FRAME instead: no static
reference, no top-hat, immune to both failure modes.

`device_glyph_score` -- what it does and does not cover
----------------------------------------------------------
Reuses `minimap_ring_fit.fit_ring`'s circumference-coverage technique (already
shipped for the enemy ring, tolerant of a fragmented arc), pointed at a Canny
edge mask of the raw grayscale crop instead of a colour mask. Measured against
every session with real ground truth (`a06f04a0059f`, `5822b6646448`,
`2ba870ccbd50`, `eb10db50b1fb`): raw circumference coverage alone is noisy
(map lines and wall corners are edges too), but INTERIOR edge density --
`inner_edge`, the fraction of edge pixels inside the fitted disc -- separates
cleanly: median 0.89 on real device glyphs against 0.33 on junk, and it holds
in the right direction on the one true same-session controlled comparison
available (`2ba870ccbd50`, mixed-class, same clip: 0.59 vs 0.34).

**CORRECTED 2026-09-02, against the real labels on the regenerated
`eb10db50b1fb` candidates: this does NOT hold for the trapwire, and must not
be used as an actual filter (`--device-inner-min`) yet.** the player named 5 real
`Cypher:Trapwire` instances, `inner_edge` 0.72-0.82 -- but 9 confirmed
`not_ability` candidates in the SAME session scored just as high (0.70-1.00),
including the player icon at 1.00. Precision at a 0.70 cut is 36%, not
the 82-94% the earlier pooled numbers suggested. The likely cause: a trapwire
is a straight BAR, not a ring, so a circle-fit was never testing what it was
built for there -- it accepts any strong local edge, circular or not, and a
straight edge or a sharp icon boundary of ANY shape satisfies that just as
well. The earlier validation was dominated by the Deadlock Sonic Sensor, which
genuinely is a compact ring; it does not transfer to a differently-shaped
object. Fix needed before this is trustworthy as a filter: verify the found
edge actually CURVES along the fitted circle (e.g. check coverage falls off
sharply just outside the fitted radius, which a true ring does and a straight
edge or an unrelated nearby corner does not), not just that pixels along one
circular path happen to be edge-positive.

**This targets device-glyph icons specifically -- Cypher's cam/trapwire/cage,
Deadlock's Sonic Sensor -- a small, sharp, ring-shaped, roughly-fixed-radius
object.** It is NOT a general ability detector and must not be used to drop
candidates outright: `2ba870ccbd50`'s real ability positives are Brimstone's
Orbital Strike, a LARGE translucent colour wash with no hard boundary at any
radius this searches, and scored low on this test precisely because it is
correctly not what this test looks for. `label_dynamic.py`'s own class list
already keeps `ability` (glyph) and `area` (overlay) apart for the same
reason; area/ultimate overlays are already caught by the saturation trigger
in `minimap_dynamic.detect`, a different mechanism for a different visual
phenomenon. Report this score, do not filter on it, unless the caller has
independently established the candidate is glyph-shaped.

`local_colour` -- fixing a dilution bug in `blob_colour`
------------------------------------------------------------
`minimap_dynamic.blob_colour(bgr, mask)` divides coloured pixels by the WHOLE
mask's pixel count, and `mask` there is the production top-hat/threshold
blob's own connected component -- which can span far more than the coloured
object once it fuses with adjacent achromatic geometry (the same closing/
merging failure mode this project has hit before, just in the colour channel
instead of the shape one). Measured directly on `2ba870ccbd50`'s ping/
portrait markers: one instance's exact candidate pixel reads HSV saturation
206 (unambiguously coloured), yet the production blob scored `frac` 0.06,
just under the 0.08 cutoff -- background pixels merged into the same
component diluted it under threshold. `local_colour` re-tests colour on a
small FIXED-RADIUS disc anchored at the candidate point instead of the
production blob's shape, which removes that dilution. It agreed with
`blob_colour` on the clearly-coloured instances and caught the diluted one
`blob_colour` missed.
"""
import numpy as np
import cv2

import minimap_dynamic as md

# Per-widget-size icon radius varies (old widget ~6px, enlarged 'bigmap'
# widget 8-13px per minimap_ring_fit.R_MIN/R_MAX) -- this label set spans
# both, so the search is wide enough to cover either without needing the
# caller to know which widget produced the frame.
R_MIN, R_MAX = 5, 15
SEARCH = 6
N_THETA = 48


def _ring_pts(r):
    th = np.arange(N_THETA) / N_THETA * 2 * np.pi
    return np.unique(np.stack([np.round(r * np.cos(th)),
                               np.round(r * np.sin(th))], 1).astype(int), axis=0)


def edge_mask(grey):
    """Canny edges at thresholds set from the patch's own median brightness.

    A local threshold rather than a fixed one: the minimap's own brightness
    varies by region (lit vs unlit geometry, see `minimap_geometry.
    two_state_gray`), and Canny responds to LOCAL gradient magnitude either
    way, which is exactly what operationalises "high contrast boundary" vs "a
    smooth lighting gradient" -- a gradient has low local gradient by
    definition, however large its total brightness range.
    """
    v = float(np.median(grey))
    lo, hi = int(max(0, 0.5 * v)), int(min(255, 1.5 * v + 30))
    e = cv2.Canny(grey, lo, hi)
    return cv2.dilate(e, np.ones((2, 2), np.uint8)) > 0


def device_glyph_score(crop, x, y):
    """Circumference coverage + interior edge density of a raw-frame ring fit
    at (x, y). See module docstring for what this does and does not cover."""
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = edge_mask(grey)
    h, w = edges.shape
    best = None
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            y0, x0 = int(round(y + dy)), int(round(x + dx))
            for r in range(R_MIN, R_MAX + 1):
                pts = _ring_pts(r)
                xs, ys = x0 + pts[:, 0], y0 + pts[:, 1]
                ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
                if ok.sum() < len(pts) * 0.75:
                    continue
                cov = float(edges[ys[ok], xs[ok]].mean())
                if best is None or cov > best[0]:
                    best = (cov, x0, y0, r)
    if best is None:
        return {"cov": 0.0, "inner_edge": 0.0, "r": 0}
    cov, x0, y0, r = best
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    inner = (yy ** 2 + xx ** 2) <= (r * 0.62) ** 2
    xs, ys = x0 + xx[inner], y0 + yy[inner]
    ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
    inner_edge = float(edges[ys[ok], xs[ok]].mean()) if ok.any() else 0.0
    return {"cov": round(cov, 3), "inner_edge": round(inner_edge, 3), "r": int(r)}


def local_colour(crop, x, y, r=8, sat_min=md.COLOUR_SAT, val_min=md.COLOUR_VAL, frac_min=0.08):
    """`blob_colour`, re-scoped to a fixed disc at (x, y). See module docstring."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    hh, ww = h.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    mask = ((xx - x) ** 2 + (yy - y) ** 2) <= r * r
    lit = mask & (s > sat_min) & (v > val_min)
    if int(lit.sum()) < 4:
        return "none", 0.0
    best, frac = "none", 0.0
    for name, spans in md.BANDS.items():
        m = np.zeros(h.shape, bool)
        for lo, hi in spans:
            m |= (h >= lo) & (h <= hi)
        f = float((m & lit).sum()) / max(1, int(mask.sum()))
        if f > frac:
            best, frac = name, f
    return (best, frac) if frac >= frac_min else ("none", frac)
