"""Screen outline candidates, promoted from enemy_detect_eval without tuning.

The prototype docstring retains evaluations and failure classes. These are
outline candidates, not established living enemies. The optional minimap box
excludes the actual profile ROI; default calls reproduce the original eval.

Owns [owns:screen-outline].
"""
import cv2
import numpy as np

SCREEN_VERSION = "screen-outline-0.1.0"
THR, K, AREA, HMIN, CK = 25, 11, 120, 22, 13
AR   = (1.15, 5.0)        # 1.20 rejects a real enemy at 1.18; below 1.15 buys nothing
HUE_MAGENTA, HUE_ORANGE = 130, 6
SAT, AST = 130, 155
WEAP = (0.50, 0.66)
# Left-handed weapon is a toggleable setting, and it mirrors the view model
# across the vertical axis. Getting this wrong fails in BOTH directions at once
# and silently: the mask covers empty screen on one side, costing recall on
# enemies peeking there, while the actual weapon sits unmasked on the other,
# costing precision. Nothing in the output would look wrong.
HANDED = "right"
# UI box finder
SCALE, GRAD, TOL, PAD = 4, 10, 12, 6
MINRUN, MINROWS, MINSPAN = 380, 3, 15
# Fragmentation: an enemy's rim shatters into many pieces with no dominant one,
# a false positive concentrates its mass in one. Reject a blob whose largest
# piece holds more than this share of the raw rim. 0.90 is deliberately mild --
# it costs 2.2 points of recall for 6.6 of precision; 0.60 is much sharper
# (recall 84.8%, precision 57.4%) but the cut is fitted to one session.
TOP1 = 0.90

KER = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (K, K))
CKER = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CK, CK*2))

def _opt(cfg, name, default):
    """One operating-point field, from a caller's cfg or this module's default.

    The two callers parameterise differently and both are legitimate: the
    evaluator's CLI sweep REBINDS the module constants (so the default has to be
    read at call time, not bound at def time), while the feature core passes a
    frozen `Cfg` it may hold several of at once. Reading through here is what
    lets one implementation serve both instead of two copies drifting apart.
    """
    return default if cfg is None else getattr(cfg, name)


def hud_mask(h, w, cfg=None):
    """Regions excluded by measurement, not by guess.

    Every rectangle here was measured at zero recall cost against the hand
    labels. The combat report is deliberately NOT among them -- it moves, and
    the region it occupies is where an enemy peeking your right side appears,
    so it is found structurally by `find_boxes` instead.
    """
    weap, handed = _opt(cfg, "weap", WEAP), _opt(cfg, "handed", HANDED)
    m = np.ones((h, w), bool)
    m[:120, :] = False; m[h-190:, :] = False       # top and bottom HUD bands
    m[:360, :360] = False                          # minimap
    m[60:360, w-520:] = False                      # killfeed
    # The player's own weapon: red-rimmed like everything else and in frame
    # constantly. Persistence cannot find it (the model bobs and sways), so this
    # is a measured region -- 21% of false positives, 0 of 47 labels. Measured
    # right-handed; a left-handed view model is the same region mirrored, and
    # getting it wrong fails in BOTH directions at once, silently.
    if handed == "right":
        m[int(h*weap[1]):, int(w*weap[0]):] = False
    else:
        m[int(h*weap[1]):, :int(w*(1.0 - weap[0]))] = False
    # Bottom-left corner HUD. Corner, not mid-screen, which is what makes a
    # positional mask defensible here where it was not for the combat report.
    m[int(0.75*h):, :int(0.09*w)] = False
    return m


def _runs(b):
    if not b.any(): return []
    idx = np.flatnonzero(np.diff(np.concatenate(([0], b.view(np.int8), [0]))))
    return list(zip(idx[::2], idx[1::2]))


def find_boxes(fr, cfg=None):
    """UI boxes, from the one thing a box has and scenery does not: several
    horizontal rules of the same width at the same x.

    Grouped by shared x-span, NOT by y-proximity: the longest run in one row and
    the longest in the next are frequently different structures, so a median
    over y-neighbours describes no real rectangle. `minrun` is the whole
    ballgame -- 380 masks furniture, 300 masks the game.
    """
    scale, grad = _opt(cfg, "scale", SCALE), _opt(cfg, "grad", GRAD)
    tol, pad = _opt(cfg, "tol", TOL), _opt(cfg, "pad", PAD)
    minrun = _opt(cfg, "minrun", MINRUN)
    minrows, minspan = _opt(cfg, "minrows", MINROWS), _opt(cfg, "minspan", MINSPAN)
    h, w = fr.shape[:2]
    g = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (w//scale, h//scale),
                   interpolation=cv2.INTER_AREA)
    hot = np.abs(cv2.Sobel(g, cv2.CV_16S, 0, 1, ksize=3)) > grad
    cand = [(y, a, b)
            for y in range(120//scale, min((h-190)//scale, hot.shape[0]))
            for a, b in _runs(hot[y]) if (b-a)*scale >= minrun]
    boxes, used = [], [False]*len(cand)
    for i, (y, a, b) in enumerate(cand):
        if used[i]: continue
        grp = [(y, a, b)]; used[i] = True
        for j in range(i+1, len(cand)):
            if not used[j] and abs(cand[j][1]-a) <= tol and abs(cand[j][2]-b) <= tol:
                grp.append(cand[j]); used[j] = True
        ys = sorted({z[0] for z in grp})
        if len(ys) >= minrows and (ys[-1]-ys[0]) >= minspan:
            x0 = min(z[1] for z in grp)*scale; x1 = max(z[2] for z in grp)*scale
            boxes.append((max(0, x0-pad), max(0, ys[0]*scale-pad),
                          min(w, x1+pad), min(h, ys[-1]*scale+pad)))
    return boxes


def outline_candidates(fr, *, minimap_box=None):
    h, w = fr.shape[:2]
    lab = cv2.cvtColor(fr, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.int16)              # red-green opponent axis
    top = cv2.morphologyEx(lab[:, :, 1], cv2.MORPH_TOPHAT, KER)
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    hu, sa = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1].astype(np.int16)
    # Relative test (is this a thin rim) AND absolute (is it the colour at all).
    # Neither substitutes for the other: top-hat alone fires on a grey line
    # beside cyan, and an absolute floor alone fires on any terracotta wall.
    keep = ((top > THR)
            & ((hu < HUE_ORANGE) | (hu > HUE_MAGENTA))
            & (sa > SAT) & (a > AST)
            & hud_mask(h, w))
    if minimap_box is not None:
        mx0, my0, mx1, my1 = minimap_box
        keep[my0:my1, mx0:mx1] = False
    for bx in find_boxes(fr):
        keep[bx[1]:bx[3], bx[0]:bx[2]] = False
    # Join the rim into ONE region before measuring it: it is broken by the body,
    # by limbs and by occlusion. A human is taller than wide, so the kernel is.
    m = cv2.morphologyEx(keep.astype(np.uint8), cv2.MORPH_CLOSE, CKER)
    n, lbl, st, _cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, ar = st[i]
        if ar < AREA or bh < HMIN: continue
        # Fragmentation, measured on the RAW rim inside this component -- the
        # closing above deliberately destroys the very structure this reads, so
        # it must come from `keep`, not from `m`.
        raw_i = (keep & (lbl == i))[y:y+bh, x:x+bw].astype(np.uint8)
        a_raw = int(raw_i.sum())
        if a_raw >= 10:
            fn_, _fl, fst, _fc = cv2.connectedComponentsWithStats(raw_i, 8)
            top1 = (fst[1:, 4].max()/a_raw) if fn_ > 1 else 1.0
            if top1 > TOP1: continue
        # Shape tests only where the shape exists. A sliver of an enemy has no
        # interior to be hollow, and demanding one filters out precisely the
        # detections that matter most.
        big = bw >= 14 and bh >= 30
        if big and not (AR[0] <= bh/max(bw, 1) <= AR[1]): continue
        ix0, iy0 = x + bw//4, y + bh//4
        ix1, iy1 = x + bw - bw//4, y + bh - bh//4
        if bw >= 14 and bh >= 24 and ix1 > ix0 and iy1 > iy0:
            inner = top[iy0:iy1, ix0:ix1]
            # the interior must be LESS red than the rim: a model sits inside an
            # outline, so the middle is the agent, not more outline
            if inner.size and float((inner > THR).mean()) > 0.45: continue
        out.append((x, y, bw, bh, ar))
    return out


def main(argv=None):
    """Inspect screen outline candidates in a source image."""
    import argparse
    import json
    parser=argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('image')
    args=parser.parse_args(argv)
    frame=cv2.imread(args.image)
    if frame is None:
        raise SystemExit('could not read source image')
    print(json.dumps([list(map(int,b)) for b in outline_candidates(frame)]))


if __name__ == "__main__":
    main()


