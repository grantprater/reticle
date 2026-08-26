"""Shared pixel core for the enemy detector: proposal, features, tracking.

This is `enemy_detect_eval.py`'s `detect()` split into two halves that were
tangled together:

    propose(fr, cfg)   pixels -> candidate blobs, each carrying every feature
                       that has ever been measured on it
    gate(f, cfg)       the shipped AND-chain of thresholds, as a pure function
                       of those features

`detect(fr, cfg)` is the composition of the two and is **bit-identical** to the
shipped `enemy_detect_eval.detect()` at `SHIPPED` -- `enemy_equiv_check.py`
asserts that frame by frame, and it is the reason this refactor can be trusted
before anything is built on it.

Why the split. The shipped detector is a **conjunction of hard gates**: a blob
with textbook hue, textbook `frag_top1` and textbook aspect still dies at
`AREA >= 120`, and no amount of other evidence can speak for it. That is exactly
where the largest adjudicated recall class lives (the six Lotus "size floor
after gating" misses). Separating proposal from gating lets the teacher run the
proposer wide open and decide later, with the whole video in hand, instead of
deciding per frame with one threshold per feature.

Nothing here changes a cut point. `SHIPPED` is the measured operating point and
must stay that way; `PERMISSIVE` is the teacher's, and is not an operating point
at all -- on its own it is roughly 5% precision.

The feature set is the one the eval docstring already measured, plus two it
described but never emitted:

    frag_top1     share of raw rim mass in the largest piece. The strongest
                  shape signal found (49.2%), and scale-free, which matters
                  because the smallest band is where the misses live.
    seal21        does the rim close into a silhouette at 21 px (2.6:1). The
                  eval measured this and never used it.
    hollow_frac   emitted UNCONDITIONALLY, with `hollow_valid` saying whether
                  the blob was big enough for the question to mean anything.
                  The shipped gate skips the test on small blobs, which is
                  correct -- a sliver has no interior -- but "not asked" and
                  "asked and passed" are different facts and a score needs to
                  tell them apart.

Position (`cx`, `cy`, `r_cross`) is emitted for DIAGNOSTICS ONLY and must never
be fitted on. 97.9% of the hand labels fall in the middle third of the screen
because half the frames were sampled just before a kill; a position prior scores
well on that corpus and is wrong, and exposure analysis needs peripheral enemies
most of all.
"""
from dataclasses import dataclass, replace

import cv2
import numpy as np


@dataclass(frozen=True)
class Cfg:
    """An operating point. Defaults are the shipped, measured ones."""
    thr: int = 25             # top-hat strength
    k: int = 11               # top-hat kernel, must exceed rim width
    area: int = 120           # closed-component area floor
    hmin: int = 22            # closed-component height floor
    ck: int = 13              # closing kernel; vertical (ck x 2*ck)
    ar: tuple = (1.15, 5.0)   # 1.20 rejects a real enemy at 1.18
    hue_magenta: int = 130    # rim runs red THROUGH magenta; tinting shifts it
    hue_orange: int = 6       # stays tight: orange scenery lives just above 10
    sat: int = 130
    ast: int = 155
    top1: float = 0.90        # 1.01 disables (no share can exceed 1.0)
    weap: tuple = (0.50, 0.66)
    handed: str = "right"
    shapes: bool = True       # aspect + hollowness gates
    # UI box finder
    scale: int = 4
    grad: int = 10
    tol: int = 12
    pad: int = 6
    minrun: int = 380
    minrows: int = 3
    minspan: int = 15


SHIPPED = Cfg()

# The teacher's proposal point. Not an operating point: ~5% precision on its
# own. Everything it gives up in precision is recovered downstream from the
# track, which is evidence the frame does not have.
PERMISSIVE = replace(SHIPPED, area=8, hmin=6, top1=1.01, shapes=False)

# Feature order for the student's design matrix. Position is deliberately
# absent -- see the module docstring.
FEATURES = (
    "area_raw", "area_closed", "bw", "bh", "aspect",
    "frag_top1", "fragments", "frag_valid",
    "hue_axis", "sat_med", "ast_med", "top_mean", "top_max",
    "hollow_frac", "hollow_valid", "seal21",
)


def _kernels(cfg):
    return (cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.k, cfg.k)),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.ck, cfg.ck * 2)))


_SEAL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))


def hud_mask(h, w, cfg=SHIPPED):
    """Regions excluded by measurement, not by guess.

    Every rectangle here was measured at zero recall cost against the hand
    labels. The combat report is deliberately NOT among them -- it moves, and
    the region it occupies is where an enemy peeking your right side appears,
    so it is found structurally by `find_boxes` instead.
    """
    m = np.ones((h, w), bool)
    m[:120, :] = False
    m[h - 190:, :] = False                         # top and bottom HUD bands
    m[:360, :360] = False                          # minimap
    m[60:360, w - 520:] = False                    # killfeed
    # The player's own weapon: red-rimmed and in frame constantly. Persistence
    # cannot find it (the model bobs and sways, so no pixel responds often
    # enough), so this is a measured region -- 21% of false positives, 0 of 47
    # labels. Left-handed is the same region mirrored, and getting it wrong
    # fails in BOTH directions at once, silently.
    if cfg.handed == "right":
        m[int(h * cfg.weap[1]):, int(w * cfg.weap[0]):] = False
    else:
        m[int(h * cfg.weap[1]):, :int(w * (1.0 - cfg.weap[0]))] = False
    # Bottom-left corner HUD. A corner, not mid-screen, which is what makes a
    # positional mask defensible here where it was not for the combat report.
    m[int(0.75 * h):, :int(0.09 * w)] = False
    return m


def _runs(b):
    if not b.any():
        return []
    idx = np.flatnonzero(np.diff(np.concatenate(([0], b.view(np.int8), [0]))))
    return list(zip(idx[::2], idx[1::2]))


def find_boxes(fr, cfg=SHIPPED):
    """UI boxes, from the one thing a box has and scenery does not: several
    horizontal rules of the same width at the same x.

    Grouped by shared x-span, NOT by y-proximity: the longest run in one row and
    the longest in the next are frequently different structures, so a median
    over y-neighbours describes no real rectangle. `minrun` is the whole
    ballgame -- 380 masks furniture, 300 masks the game.
    """
    h, w = fr.shape[:2]
    g = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY),
                   (w // cfg.scale, h // cfg.scale), interpolation=cv2.INTER_AREA)
    hot = np.abs(cv2.Sobel(g, cv2.CV_16S, 0, 1, ksize=3)) > cfg.grad
    cand = [(y, a, b)
            for y in range(120 // cfg.scale, min((h - 190) // cfg.scale, hot.shape[0]))
            for a, b in _runs(hot[y]) if (b - a) * cfg.scale >= cfg.minrun]
    boxes, used = [], [False] * len(cand)
    for i, (y, a, b) in enumerate(cand):
        if used[i]:
            continue
        grp = [(y, a, b)]
        used[i] = True
        for j in range(i + 1, len(cand)):
            if not used[j] and abs(cand[j][1] - a) <= cfg.tol and abs(cand[j][2] - b) <= cfg.tol:
                grp.append(cand[j])
                used[j] = True
        ys = sorted({z[0] for z in grp})
        if len(ys) >= cfg.minrows and (ys[-1] - ys[0]) >= cfg.minspan:
            x0 = min(z[1] for z in grp) * cfg.scale
            x1 = max(z[2] for z in grp) * cfg.scale
            boxes.append((max(0, x0 - cfg.pad), max(0, ys[0] * cfg.scale - cfg.pad),
                          min(w, x1 + cfg.pad), min(h, ys[-1] * cfg.scale + cfg.pad)))
    return boxes


def _hue_axis(hu_vals):
    """OpenCV hue unwrapped onto one continuous axis through red.

    The accepted band wraps zero (`hu < 6 | hu > 130`), so raw hue is
    discontinuous exactly where the signal is and cannot be fitted on directly:
    a magenta-tinted rim at 175 and an orange wall at 2 are three degrees apart
    on the circle and read as 173 apart on the number line.

    Mapping `hu >= 90` to `hu - 180` puts magenta at -50..0, red at 0 and orange
    at 0..6, monotone and continuous across the whole band. **The sign matters
    and must survive**: the two edges are not symmetric. Tinting shifts the rim
    DOWN toward magenta -- smoke, Reyna's ult -- which is why the lower edge was
    widened to 130 for 22 points of recall. Orange scenery sits just above 10,
    which is why the upper edge stays at 6: widening it to 10 recovers one
    green-tinted Clove and costs a fifth of Lotus's precision. A feature that
    folded the two sides together would hide precisely that.
    """
    return np.where(hu_vals >= 90, hu_vals - 180, hu_vals)


def rim_mask(fr, cfg=SHIPPED, boxes=None):
    """The rim mask and the channels it was built from.

    Split out of `propose()` so the mask itself can be measured -- the codec
    test needs the rim before it becomes blobs, because chroma subsampling acts
    on pixels and the blob stage would hide how much of the rim survived.

    Returns `(keep, top, hu, sa, a)`.
    """
    h, w = fr.shape[:2]
    ker, _cker = _kernels(cfg)
    lab = cv2.cvtColor(fr, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.int16)                  # red-green opponent axis
    top = cv2.morphologyEx(lab[:, :, 1], cv2.MORPH_TOPHAT, ker)
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    hu, sa = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1].astype(np.int16)
    # Relative test (is this a thin rim) AND absolute (is it the colour at all).
    # Neither substitutes for the other: top-hat alone fires on a grey line
    # beside cyan, and an absolute floor alone fires on any terracotta wall.
    keep = ((top > cfg.thr)
            & ((hu < cfg.hue_orange) | (hu > cfg.hue_magenta))
            & (sa > cfg.sat) & (a > cfg.ast)
            & hud_mask(h, w, cfg))
    for bx in (find_boxes(fr, cfg) if boxes is None else boxes):
        keep[bx[1]:bx[3], bx[0]:bx[2]] = False
    return keep, top, hu, sa, a


def propose(fr, cfg=PERMISSIVE, boxes=None):
    """Candidate blobs with every measured feature attached.

    Returns a list of dicts. At `SHIPPED` plus `gate()` this reproduces the
    shipped detector exactly; at `PERMISSIVE` it is the teacher's proposal set.

    `boxes` lets a caller pass in `find_boxes(fr)` when it already has them --
    the teacher runs the proposer once per frame, so this is only for callers
    that want both the boxes and the blobs.
    """
    h, w = fr.shape[:2]
    _ker, cker = _kernels(cfg)
    keep, top, hu, sa, a = rim_mask(fr, cfg, boxes)
    # Join the rim into ONE region before measuring it: it is broken by the
    # body, by limbs and by occlusion. A human is taller than wide, so the
    # kernel is. This is also what merges adjacent enemies in a cluster, which
    # is a known unfixed recall class.
    m = cv2.morphologyEx(keep.astype(np.uint8), cv2.MORPH_CLOSE, cker)
    n, lbl, st, _cen = cv2.connectedComponentsWithStats(m, 8)
    cx0, cy0 = w / 2.0, h / 2.0
    out = []
    for i in range(1, n):
        x, y, bw, bh, area_closed = st[i]
        if area_closed < cfg.area or bh < cfg.hmin:
            continue
        # Fragmentation is measured on the RAW rim inside this component. The
        # closing above deliberately destroys the very structure this reads, so
        # it must come from `keep`, never from `m`.
        raw_i = (keep & (lbl == i))[y:y + bh, x:x + bw].astype(np.uint8)
        a_raw = int(raw_i.sum())
        frag_valid = a_raw >= 10
        top1, nfrag = 1.0, 1
        if frag_valid:
            fn_, _fl, fst, _fc = cv2.connectedComponentsWithStats(raw_i, 8)
            nfrag = max(fn_ - 1, 1)
            top1 = (fst[1:, 4].max() / a_raw) if fn_ > 1 else 1.0
        # Colour of the rim itself, over the raw pixels -- the closed component
        # is mostly the scenery the rim encloses, which is what made every
        # motion measurement read background against background.
        sel = raw_i.astype(bool)
        if a_raw:
            hu_i = hu[y:y + bh, x:x + bw][sel]
            sat_med = float(np.median(sa[y:y + bh, x:x + bw][sel]))
            ast_med = float(np.median(a[y:y + bh, x:x + bw][sel]))
            top_v = top[y:y + bh, x:x + bw][sel]
            top_mean, top_max = float(top_v.mean()), float(top_v.max())
            hue_axis = float(np.median(_hue_axis(hu_i)))
        else:
            sat_med = ast_med = top_mean = top_max = hue_axis = 0.0
        # Hollowness: the interior must be LESS red than the rim, because a
        # model sits inside an outline so the middle is the agent. Asked
        # unconditionally; `hollow_valid` says whether it meant anything.
        ix0, iy0 = x + bw // 4, y + bh // 4
        ix1, iy1 = x + bw - bw // 4, y + bh - bh // 4
        hollow_valid = bw >= 14 and bh >= 24 and ix1 > ix0 and iy1 > iy0
        hollow_frac = 0.0
        if ix1 > ix0 and iy1 > iy0:
            inner = top[iy0:iy1, ix0:ix1]
            if inner.size:
                hollow_frac = float((inner > cfg.thr).mean())
            else:
                hollow_valid = False
        else:
            hollow_valid = False
        out.append({
            "box": (int(x), int(y), int(bw), int(bh), int(area_closed)),
            "area_raw": float(a_raw), "area_closed": float(area_closed),
            "bw": float(bw), "bh": float(bh), "aspect": bh / max(bw, 1),
            "frag_top1": float(top1), "fragments": float(nfrag),
            "frag_valid": float(frag_valid),
            "hue_axis": hue_axis, "sat_med": sat_med, "ast_med": ast_med,
            "top_mean": top_mean, "top_max": top_max,
            "hollow_frac": hollow_frac, "hollow_valid": float(hollow_valid),
            "seal21": _seal21(raw_i),
            # DIAGNOSTIC ONLY -- never fit on these. See the module docstring.
            "cx": x + bw / 2.0, "cy": y + bh / 2.0,
            "r_cross": float(np.hypot(x + bw / 2.0 - cx0, y + bh / 2.0 - cy0)),
        })
    return out


def _seal21(raw_i):
    """Share of the closed blob that is enclosed hole, closing at 21 px.

    Measured at 54% of enemies against 21% of false positives. A convex hull
    seals 98% against 89% and is useless -- convexifying swallows the very
    concavities that carry the shape -- so this is a closing, not a hull.

    Returned as the fraction rather than the boolean the eval measured: the
    boolean is recoverable from it and the fraction is not recoverable from the
    boolean.
    """
    if raw_i.size == 0 or not raw_i.any():
        return 0.0
    c = cv2.morphologyEx(raw_i, cv2.MORPH_CLOSE, _SEAL)
    pad = cv2.copyMakeBorder(c, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = pad.copy()
    cv2.floodFill(ff, np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8),
                  (0, 0), 1)
    holes = int(((ff == 0) & (pad == 0)).sum())
    filled = int(c.sum()) + holes
    return holes / filled if filled else 0.0


def gate(f, cfg=SHIPPED):
    """The shipped AND-chain, as a pure function of a proposal's features.

    Mirrors `enemy_detect_eval.detect()` condition for condition, including the
    two conditionals that make it size-aware:

    * the fragmentation test applies only when there is enough raw rim to
      fragment (`frag_valid`);
    * the aspect and hollowness tests apply only to blobs big enough to HAVE a
      shape. Demanding hollowness of a shoulder past a corner -- which is where
      peeking happens -- asks a question with no answer, and the filter answers
      no.

    The size-conditionality is the part a calibrated score is meant to replace,
    not the thresholds inside it.
    """
    if f["area_closed"] < cfg.area or f["bh"] < cfg.hmin:
        return False
    if f["frag_valid"] and f["frag_top1"] > cfg.top1:
        return False
    if cfg.shapes:
        big = f["bw"] >= 14 and f["bh"] >= 30
        if big and not (cfg.ar[0] <= f["aspect"] <= cfg.ar[1]):
            return False
        if f["hollow_valid"] and f["hollow_frac"] > 0.45:
            return False
    return True


def detect(fr, cfg=SHIPPED):
    """Boxes, exactly as the shipped detector returns them."""
    return [f["box"] for f in propose(fr, cfg) if gate(f, cfg)]


def vector(f):
    """A proposal's features as a fixed-order row, for the student."""
    return np.array([f[k] for k in FEATURES], dtype=np.float64)
