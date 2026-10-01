r"""Fast and pure-CV fits of the minimap ability shapes, and a whole-match scan.

    .\.venv\Scripts\python.exe prototypes\ability_shape_fast.py marks   OUT.json
    .\.venv\Scripts\python.exe prototypes\ability_shape_fast.py null    OUT.json
    .\.venv\Scripts\python.exe prototypes\ability_shape_fast.py generic OUT.json
    .\.venv\Scripts\python.exe prototypes\ability_shape_fast.py scan SID OUT.json [HZ]
    .\.venv\Scripts\python.exe prototypes\ability_shape_fast.py icons OUT.json [SHEETDIR]

Why. `reticle.ability_shapes` fits Regrowth's and Recon Bolt's rings and
Hunter's Fury's beam on one crop after each of the player's tray casts. To
find the same shapes for every caster it must read every sampled crop of a
match, and its free ring search costs about 1.6 s a crop at 331 px: every
third centre of the widget, each scored by two bincounts over a 165 px window
(`_Radial.scores`, 0.17 ms a call, 9 491 calls). This prototype measures the
alternatives the design doc `docs/ABILITY_DETECTION.md` weighs, on the
player's marks (`ability_shape_eval`'s truth), its null sample and the crop
cache only; nothing decodes the capture.

The alternatives, each fitted to the SAME objective unless it says otherwise:

- `RingSurface` (exact): the ring score of `ability_shapes.fit_ring` at every
  centre and radius at once. A band sum round centre c is a disc sum at the
  outer edge minus one at the inner edge, and a disc sum at every c is a
  convolution of the teal weight with that disc, so one FFT of the crop and
  one inverse FFT per half-pixel radius give every band; the mask's counts
  depend on the widget's size alone and are cached.
- `RingSurface(scale=0.5)` then `refine` (coarse to fine): the same surface on
  the teal weight averaged 2x2, its best few local maxima rescored by the
  exact scorer on a 7x7 window.
- `hough_rings` (pure CV): `cv2.HoughCircles` on the teal weight, each circle
  rescored by the exact scorer round it. Not the objective; a proposer.
- `component_rings` (pure CV): connected teal components at least GATE_EXTENT
  of R across, a RANSAC circle through each, rescored the same way. Its first
  half is the gate a whole-match scan applies before any fit.
- `beam_sweep` (exact up to binning): the beam score of `fit_beam` for every
  angle at once. A pixel at distance rho and bearing phi from the origin lies
  in the strip of angle theta when |theta - phi| <= asin(half/rho), so each
  pixel adds its teal to one interval of a 0.2 deg angle grid, and a
  difference array sums them all in one pass.

The icon proposer (`icon_candidates`, `icon-proposer-0.2.0` with a floor) is
not an `ability_shapes` objective: the dark share of a disc minus that of a
band outside it, on the baked slab only. `icon_candidates_fast` caches the
slab terms a session (`ICON_STEP` coarsens the radii); `icon_candidates_window`
and `icon_verify` are the tracking prior's two measured forms, a window
search and a pointwise rescore of a tracked icon.

`fit_shape` itself runs unchanged with its ring and beam functions swapped
(`swapped`), so the seeded, widened and free paths and the acceptance are the
module's own.

Not for. Shipping: the plan's stage 1 moves the winner into
`reticle/ability_shapes.py` under a new version. Naming a caster, an onset or
an end.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import contextlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_shape_eval as E  # noqa: E402
from reticle import ability_shapes as S_  # noqa: E402

FAST_VERSION = "ability-shape-fast-0.1.0"
#: The gate: teal at least this strong, in a component at least this many R across.
GATE_TEAL, GATE_EXTENT = 0.25, 0.2
REFINE_K, REFINE_HALF = 5, 3
STEP_DEG = 0.2


def fast_len(n: int) -> int:
    """The smallest 5-smooth integer >= n (pocketfft is fastest on those)."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


def below_normal():
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


# ------------------------------------------------------------------ rings

class _Kernels:
    """Disc-kernel FFTs and mask counts for one widget size and scale, cached."""

    cache: dict = {}

    @classmethod
    def of(cls, shape, R, scale):
        key = (tuple(shape), round(R, 3), scale)
        if key not in cls.cache:
            cls.cache[key] = cls(shape, R, scale)
        return cls.cache[key]

    def __init__(self, shape, R, scale):
        h, w = shape
        full = np.arange(S_.RING_R[0] * R, S_.RING_R[1] * R + 0.01, 0.5)
        self.radii = full if scale == 1.0 else full[::2]
        r = self.radii * scale
        s = scale
        self.i = [np.clip(np.round(a * 2).astype(int), 0, None) for a in (r - 1.5 * s, r - 6 * s, r + 3 * s)]
        self.j = [np.clip(np.round(b * 2).astype(int), 0, None) for b in (r + 1.5 * s, r - 3 * s, r + 6 * s)]
        self.ks = np.unique(np.concatenate(self.i + self.j))
        self.kpos = {int(k): n for n, k in enumerate(self.ks)}
        self.jn = [np.array([self.kpos[int(k)] for k in a]) for a in self.j]
        self.im = [np.array([self.kpos[int(k)] for k in a]) for a in self.i]
        W = int(np.ceil(r.max() + 7 * s))
        self.P = (fast_len(h + W + 1), fast_len(w + W + 1))
        yy, xx = np.mgrid[-W:W + 1, -W:W + 1]
        d2 = np.floor(np.hypot(xx, yy) * 2).astype(int)
        self.KF = np.empty((len(self.ks), self.P[0], self.P[1] // 2 + 1), np.complex64)
        for n, k in enumerate(self.ks):
            kp = np.zeros(self.P, np.float32)
            kp[yy % self.P[0], xx % self.P[1]] = (d2 < k).astype(np.float32)
            self.KF[n] = np.fft.rfft2(kp)
        hs, ws = shape
        R_, mask = S_.widget((hs, ws))
        self.mask = mask
        self.M = self._conv(mask.astype(np.float32), (hs, ws))
        self.M = np.rint(self.M)

    def _conv(self, img, shape):
        h, w = shape
        F = np.fft.rfft2(img, s=self.P).astype(np.complex64)
        out = np.empty((len(self.ks), h, w), np.float32)
        for n in range(len(self.ks)):
            out[n] = np.fft.irfft2(F * self.KF[n], s=self.P)[:h, :w]
        return out


class RingSurface:
    """Every centre's best ring score (the `fit_ring` objective) and its radius."""

    def __init__(self, tl: np.ndarray, R: float, scale: float = 1.0):
        self.scale = scale
        if scale != 1.0:
            small = cv2.resize(tl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            Rs = R
        else:
            small, Rs = tl, R
        K = _Kernels.of(small.shape, Rs, scale)
        self.K = K
        T = K._conv((small * K.mask).astype(np.float32), small.shape)
        M = K.M

        best = np.full(small.shape, -2.0, np.float32)
        arg = np.zeros(small.shape, np.int32)
        for q in range(len(K.radii)):
            vals = []
            for b in range(3):
                jn, im = K.jn[b][q], K.im[b][q]
                cnt = M[jn] - M[im]
                with np.errstate(invalid="ignore", divide="ignore"):
                    vals.append(np.where(cnt >= 8, (T[jn] - T[im]) / np.maximum(cnt, 1), np.nan))
            out = vals[0] - np.fmax(vals[1], vals[2])
            out = np.where(np.isnan(out), -1.0, out).astype(np.float32)
            better = out > best
            best[better] = out[better]
            arg[better] = q
        best[~K.mask] = -2.0
        self.best, self.arg = best, arg

    def at(self, x, y):
        """The (score, cx, cy, r) of a full-resolution centre's cell."""
        s = self.scale
        yi, xi = int(round(y * s)), int(round(x * s))
        return float(self.best[yi, xi]), x, y, float(self.K.radii[self.arg[yi, xi]])

    def argmax(self, centre=None, half=None):
        s = self.scale
        b = self.best
        if centre is not None:
            m = np.full(b.shape, -2.0, np.float32)
            x0 = max(0, int((centre[0] - half) * s)); x1 = min(b.shape[1], int((centre[0] + half) * s) + 1)
            y0 = max(0, int((centre[1] - half) * s)); y1 = min(b.shape[0], int((centre[1] + half) * s) + 1)
            m[y0:y1, x0:x1] = b[y0:y1, x0:x1]
            b = m
        yi, xi = np.unravel_index(int(np.argmax(b)), b.shape)
        return float(b[yi, xi]), xi / s, yi / s, float(self.K.radii[self.arg[yi, xi]])

    def peaks(self, k=REFINE_K, sep_frac=0.1, R=None, centre=None, half=None):
        """The k best local maxima at least sep_frac R apart, in full-res pixels."""
        s = self.scale
        b = self.best.copy()
        if centre is not None:
            m = np.full(b.shape, -2.0, np.float32)
            x0 = max(0, int((centre[0] - half) * s)); x1 = min(b.shape[1], int((centre[0] + half) * s) + 1)
            y0 = max(0, int((centre[1] - half) * s)); y1 = min(b.shape[0], int((centre[1] + half) * s) + 1)
            m[y0:y1, x0:x1] = b[y0:y1, x0:x1]
            b = m
        sep = max(1, int(round(sep_frac * R * s)))
        out = []
        for _ in range(k):
            yi, xi = np.unravel_index(int(np.argmax(b)), b.shape)
            if b[yi, xi] <= -1.0:
                break
            out.append((float(b[yi, xi]), xi / s, yi / s))
            b[max(0, yi - sep):yi + sep + 1, max(0, xi - sep):xi + sep + 1] = -2.0
        return out


def refine(tl, mask, R, cands, rad=None):
    """The exact `fit_ring` score on a 7x7 window round each candidate; the best."""
    radii = np.arange(S_.RING_R[0] * R, S_.RING_R[1] * R + 0.01, 0.5)
    rad = rad or S_._Radial(tl, mask, radii)
    best = {"score": -2.0, "cx": None, "cy": None, "r": None}
    for c in cands:
        f = S_._ORIG_FIT_RING(tl, mask, R, (c[-2], c[-1]), REFINE_HALF, 1, rad)
        if f["score"] > best["score"]:
            best = f
    return best


def hough_rings(tl, mask, R, param1=60, param2=0.5):
    img = cv2.GaussianBlur((tl * mask * 255).astype(np.uint8), (5, 5), 1.2)
    c = cv2.HoughCircles(img, cv2.HOUGH_GRADIENT_ALT, 1.5, max(8, int(0.1 * R)), param1=param1,
                         param2=param2, minRadius=int(S_.RING_R[0] * R) - 2,
                         maxRadius=int(S_.RING_R[1] * R) + 2)
    return [] if c is None else [(float(r), float(x), float(y)) for x, y, r in c.reshape(-1, 3)]


def components(tl, mask, R):
    """Teal components at least GATE_EXTENT R across: (label image, list of (n, ys, xs))."""
    b = ((tl >= GATE_TEAL) & mask).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    keep = [i for i in range(1, n) if max(st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]) >= GATE_EXTENT * R]
    return lab, keep


def ransac_circle(xs, ys, R, rng, iters=200, tol=2.0):
    lo, hi = S_.RING_R[0] * R - 3, S_.RING_R[1] * R + 3
    pts = np.c_[xs, ys].astype(float)
    if len(pts) < 12:
        return None
    best, bc = 0, None
    for _ in range(iters):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        A = np.array([[b[0] - a[0], b[1] - a[1]], [c[0] - a[0], c[1] - a[1]]]) * 2
        rhs = np.array([b @ b - a @ a, c @ c - a @ a])
        if abs(np.linalg.det(A)) < 1e-6:
            continue
        cx, cy = np.linalg.solve(A, rhs)
        r = float(np.hypot(*(a - (cx, cy))))
        if not lo <= r <= hi:
            continue
        inl = int((np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r) < tol).sum())
        if inl > best:
            best, bc = inl, (float(inl), float(cx), float(cy))
    return bc


def component_rings(tl, mask, R, seed=0):
    lab, keep = components(tl, mask, R)
    rng = np.random.default_rng(seed)
    out = []
    for i in keep:
        ys, xs = np.nonzero(lab == i)
        if len(xs) > 600:
            sel = rng.choice(len(xs), 600, replace=False)
            xs, ys = xs[sel], ys[sel]
        c = ransac_circle(xs, ys, R, rng)
        if c is not None:
            out.append(c)
    return sorted(out, reverse=True)


# ------------------------------------------------------------------ beam

def beam_sweep(tl, mask, ox, oy, R, step=STEP_DEG):
    """The `fit_beam` strip-minus-collar score at every angle on a `step` grid."""
    ys, xs = np.nonzero(mask)
    vx, vy = xs - ox, ys - oy
    rho = np.hypot(vx, vy)
    sel = (rho >= S_.BEAM_NEAR_PX) & (rho <= S_.BEAM_REACH * R)
    rho, phi = rho[sel], np.degrees(np.arctan2(vy[sel], vx[sel])) % 360.0
    t = tl[ys[sel], xs[sel]].astype(np.float64)
    hw, col = S_.BEAM_HALF * R, S_.BEAM_COLLAR * R
    nb = int(round(360.0 / step))

    def interval(alpha, wts):
        lo = np.ceil((phi - alpha) / step - 1e-9).astype(int) + nb
        hi = np.floor((phi + alpha) / step + 1e-9).astype(int) + nb + 1
        d = np.bincount(lo, wts, 3 * nb + 2) - np.bincount(hi, wts, 3 * nb + 2)
        c = np.cumsum(d)[:3 * nb]
        return c[:nb] + c[nb:2 * nb] + c[2 * nb:]

    a1 = np.degrees(np.arcsin(np.clip(hw / rho, 0, 1)))
    a2 = np.degrees(np.arcsin(np.clip((hw + col) / rho, 0, 1)))
    one = np.ones_like(t)
    s1, n1 = interval(a1, t), interval(a1, one)
    s2, n2 = interval(a2, t) - s1, interval(a2, one) - n1
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = np.where((n1 >= 20) & (n2 >= 20), s1 / n1 - s2 / n2, -1.0)
    return np.arange(nb) * step, sc


def fast_fit_beam(tl, mask, ox, oy, R, around=None):
    """`fit_beam`'s output fields from the swept score; the run's end as `fit_beam` finds it."""
    th, sc = beam_sweep(tl, mask, ox, oy, R)
    if around is not None:
        d = np.abs((th - around + 180) % 360 - 180)
        sc = np.where(d <= 8.0, sc, -2.0)
    k = int(np.argmax(sc))
    best, thb = float(sc[k]), float(th[k])
    h, w = tl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    _, lp, strip = S_._beam(tl, mask, xx - ox, yy - oy, thb, R)
    bins = np.floor(lp[strip] / 2.0).astype(int)
    prof = np.bincount(bins, weights=tl[strip]) / np.maximum(np.bincount(bins), 1)
    l0 = l1 = S_.BEAM_NEAR_PX
    on = np.nonzero(prof >= 0.5 * prof.max())[0] if prof.size and prof.max() > 0 else []
    if len(on):
        run = [on[0]]
        for b in on[1:]:
            if b - run[-1] <= 3:
                run.append(b)
            elif len(run) < 5:
                run = [b]
            else:
                break
        l0, l1 = run[0] * 2.0, run[-1] * 2.0 + 2.0
    c, s = np.cos(np.radians(thb)), np.sin(np.radians(thb))
    return {"score": best, "theta_deg": thb % 360, "x0": float(ox + l0 * c), "y0": float(oy + l0 * s),
            "x1": float(ox + l1 * c), "y1": float(oy + l1 * s), "length": l1 - l0}


# ------------------------------------------------------------------ swapping

S_._ORIG_FIT_RING = S_.fit_ring
S_._ORIG_FIT_BEAM = S_.fit_beam
_SURF: dict = {}


def _surface(tl, R, scale):
    key = (id(tl), scale)
    if key not in _SURF:
        _SURF.clear()
        _SURF[key] = RingSurface(tl, R, scale)
    return _SURF[key]


def ring_exact(tl, mask, R, centre=None, half=None, step=1, _radial=None):
    s, cx, cy, r = _surface(tl, R, 1.0).argmax(centre, half)
    return {"score": s, "cx": int(round(cx)), "cy": int(round(cy)), "r": r}


def ring_c2f(tl, mask, R, centre=None, half=None, step=1, _radial=None):
    cands = _surface(tl, R, 0.5).peaks(REFINE_K, R=R, centre=centre, half=half)
    if centre is not None:          # the seeded window stays the module's own
        cands = [c for c in cands if abs(c[1] - centre[0]) <= half + 1 and abs(c[2] - centre[1]) <= half + 1]
    return refine(tl, mask, R, cands or [(0, centre[0], centre[1])] if centre else cands)


def ring_hough(tl, mask, R, centre=None, half=None, step=1, _radial=None):
    cands = [(r, x, y) for r, x, y in hough_rings(tl, mask, R)
             if centre is None or (abs(x - centre[0]) <= half and abs(y - centre[1]) <= half)]
    return refine(tl, mask, R, cands) if cands else {"score": -2.0, "cx": None, "cy": None, "r": None}


def ring_components(tl, mask, R, centre=None, half=None, step=1, _radial=None):
    cands = [c for c in component_rings(tl, mask, R)
             if centre is None or (abs(c[1] - centre[0]) <= half and abs(c[2] - centre[1]) <= half)]
    return refine(tl, mask, R, cands[:REFINE_K]) if cands else {"score": -2.0, "cx": None, "cy": None, "r": None}


RINGS = {"current": None, "exact": ring_exact, "c2f": ring_c2f, "hough": ring_hough,
         "components": ring_components}
BEAMS = {"current": None, "sweep": fast_fit_beam}


@contextlib.contextmanager
def swapped(ring=None, beam=None):
    S_.fit_ring = ring or S_._ORIG_FIT_RING
    S_.fit_beam = beam or S_._ORIG_FIT_BEAM
    try:
        yield
    finally:
        S_.fit_ring, S_.fit_beam = S_._ORIG_FIT_RING, S_._ORIG_FIT_BEAM
        _SURF.clear()


def gate(crop) -> bool:
    tl = S_.teal(crop)
    R, mask = S_.widget(crop.shape)
    return bool(components(tl, mask, R)[1])


# ------------------------------------------------------------------ marks

def mark_panels():
    labs = [r for r in E.labels().values() if r.get("ability") in E.SHAPES and r.get("class") == "object"]
    out = []
    for r in sorted(labs, key=lambda r: r["key"]):
        kind = E.SHAPES[r["ability"]]
        by = defaultdict(list)
        for m in r["marks"]:
            by[m["panel"]].append(m)
        t_drop = float(r["key"].split(":")[1])
        out.append({"sid": r["session_id"], "ability": r["ability"], "kind": kind, "key": r["key"],
                    "panel": "pre", "t": t_drop - 1000.0, "pts": None})
        for pan, ms in sorted(by.items()):
            if pan == 0 or (kind != "beam" and len(ms) < 5) or len(ms) < 3:
                continue
            out.append({"sid": r["session_id"], "ability": r["ability"], "kind": kind, "key": r["key"],
                        "panel": pan, "t": ms[0]["t_ms"], "pts": [[m["x"], m["y"]] for m in ms]})
    return out


def truth(p):
    pts = np.array(p["pts"], float)
    if p["kind"] == "beam":
        _, d = E.axis(pts)
        return {"theta": float(np.degrees(np.arctan2(d[1], d[0])) % 180)}
    cx, cy, r = E.lsq_circle(pts) if p["kind"] == "ring_self" else E.ransac_circle(pts)
    return {"cx": float(cx), "cy": float(cy), "r": float(r)}


def run_marks(out: Path):
    sessions, rows = {}, []
    panels = mark_panels()
    for p in panels:
        S = sessions.get(p["sid"]) or sessions.setdefault(p["sid"], E.Session(p["sid"]))
        img, _ = S.crop(p["t"])
        if img is None:
            rows.append({**p, "no_crop": True})
            continue
        me = S.self_at(p["t"])
        tr = truth(p) if p["pts"] else None
        row = {**{k: p[k] for k in ("sid", "ability", "kind", "key", "panel", "t")}, "truth": tr,
               "gate": gate(img), "fits": {}}
        names = (("current", None, None), ("exact", "exact", None), ("c2f", "c2f", None),
                 ("hough", "hough", None), ("components", "components", None)) if p["kind"] != "beam" \
            else (("current", None, None), ("sweep", None, "sweep"))
        for name, rn, bn in names:
            with swapped(RINGS.get(rn), BEAMS.get(bn)):
                t0 = time.perf_counter()
                f = S_.fit_shape(img, p["ability"], me, S.support)
                dt = time.perf_counter() - t0
            fr = {"s": dt, "found": f.get("found"), "path": f.get("path"), "score": f.get("score"),
                  "reason": f.get("reason")}
            if tr and f.get("cx") is not None:
                fr["c_err"] = float(np.hypot(f["cx"] - tr["cx"], f["cy"] - tr["cy"]))
                fr["r"] = f.get("r")
            if tr and "theta_deg" in f:
                fr["a_err"] = E.ang_err(f["theta_deg"], tr["theta"])
            row["fits"][name] = fr
        rows.append(row)
        print(json.dumps({"key": row["key"], "panel": row["panel"], "gate": row["gate"],
                          **{n: (round(v["s"], 3), v["found"], round(v.get("c_err", v.get("a_err", -1)), 1))
                             for n, v in row["fits"].items()}}), flush=True)
    out.write_text(json.dumps(rows, indent=0, default=str), encoding="utf-8")


# ------------------------------------------------------------------ null

def run_null(out: Path, per_session=10, gap_s=10.0):
    """`ability_shape_eval.null_sample`'s crops; the exhaustive and fast scores beside the module's."""
    import hashlib
    import pickle
    import tray_suspect_reasons as tsr
    from reticle import gametime, stalls
    from reticle.cli import _date_of
    slots = {"Sova": ("E", "X"), "Skye": ("C",)}
    rows = []
    for pk in sorted(tsr.WORK.glob("*.pkl")):
        sid = pk.stem
        lp = E.STORE.root / "lineups" / f"{sid}.json"
        agent = ((json.loads(lp.read_text(encoding="utf-8")).get("player") or {}).get("agent")
                 if lp.exists() else None)
        if agent not in slots:
            continue
        with open(pk, "rb") as f:
            d = pickle.load(f)
        drops = [r["t"] * 1000.0 for r in tsr.drop_rows(d) if r["slot"] in slots[agent]]
        man = E.STORE.read_manifest(sid)
        date = _date_of(man)
        gt = gametime.build_session_gametime(
            sid, E.STORE.read_hud(sid, date), E.STORE.read_rounds(sid, date).to_pylist(),
            stall_list=stalls.for_session(E.STORE, sid, date))
        S = E.Session(sid)
        ts = [float(t) for t in S.cache.t_ms]
        picked, k = [], 0
        while len(picked) < per_session and k < 5000:
            h = int(hashlib.sha1(f"{sid}:{k}".encode()).hexdigest()[:8], 16)
            k += 1
            t = ts[h % len(ts)]
            if gt.game_time_at(t).phase not in ("round_live", "post_plant") or any(
                    abs(t - x) < gap_s * 1000 for x in drops):
                continue
            picked.append(t)
        for t in sorted(picked):
            img, _ = S.crop(t)
            if img is None:
                continue
            me = S.self_at(t)
            tl = S_.teal(img)
            R, mask = S_.widget(img.shape)
            row = {"sid": sid, "agent": agent, "t_ms": t, "shape": list(img.shape[:2]), "gate": gate(img)}
            t0 = time.perf_counter(); f = S_._ORIG_FIT_RING(tl, mask, R, step=3)
            row["ring_step3"], row["ring_step3_s"] = f["score"], time.perf_counter() - t0
            t0 = time.perf_counter(); surf = RingSurface(tl, R, 1.0)
            row["ring_exact"], row["ring_exact_s"] = surf.argmax()[0], time.perf_counter() - t0
            row["ring_exact_xyr"] = surf.argmax()[1:]
            t0 = time.perf_counter(); f = ring_c2f(tl, mask, R)
            row["ring_c2f"], row["ring_c2f_s"] = f["score"], time.perf_counter() - t0
            t0 = time.perf_counter(); f = ring_components(tl, mask, R)
            row["ring_components"], row["ring_components_s"] = f["score"], time.perf_counter() - t0
            if me is not None:
                t0 = time.perf_counter(); fb = S_._ORIG_FIT_BEAM(tl, mask, me[0], me[1], R)
                row["beam_seeded"], row["beam_seeded_s"] = fb["score"], time.perf_counter() - t0
                row["beam_seeded_on_map"] = S_.on_map(fb, S.support) if S.support is not None else None
                t0 = time.perf_counter(); fb = fast_fit_beam(tl, mask, me[0], me[1], R)
                row["beam_sweep"], row["beam_sweep_s"] = fb["score"], time.perf_counter() - t0
                row["beam_sweep_on_map"] = S_.on_map(fb, S.support) if S.support is not None else None
            rows.append(row)
            _SURF.clear()
        print(sid, agent, len(picked), flush=True)
    out.write_text(json.dumps(rows, indent=0, default=str), encoding="utf-8")


# ------------------------------------------------------------------ generic

#: The round viewer's magnified inset (`round_view.render`, round-view-0.1.0):
#: the widget at INSET_K, its top-left at (W - iw - 16, H - ih - 150).
INSET_K = 2


def inset_to_widget(x, y, rect, frame_wh=(1920, 1080)):
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    ix, iy = frame_wh[0] - INSET_K * w - 16, frame_wh[1] - INSET_K * h - 150
    return (x - ix) / INSET_K, (y - iy) / INSET_K


class _EmptyTrack:
    def to_pydict(self):
        return {"t_ms": [], "self_x": [], "self_y": []}


class Generic:
    """`minimap.detect_ability_*` with the inputs the benchmarks give them, from the cache."""

    def __init__(self, sid):
        from reticle import minimap
        self.mm = minimap
        try:
            self.S = E.Session(sid)
        except SystemExit:
            # No stored minimap table (d95cfad5693a): no self seed; the detectors run unseeded.
            orig = E.STORE.read_minimap
            E.STORE.read_minimap = lambda *a, **k: _EmptyTrack()
            try:
                self.S = E.Session(sid)
            finally:
                E.STORE.read_minimap = orig
        self.ts = np.asarray(self.S.cache.t_ms, float)
        st = self.S.static
        self.floor = minimap.slab_mask(st)
        g = cv2.cvtColor(st, cv2.COLOR_BGR2GRAY)
        self.static_peaks = [(d["cx"], d["cy"], d["response"])
                             for d in minimap.detect_ability_discs(g, self.floor, k=27, bh_min=80)]
        self.static_lines = minimap.extract_static_lines(st, self.floor, min_length=8.0)

    def crop(self, t):
        k = int(np.argmin(np.abs(self.ts - t)))
        img, tt = self.S.crop(float(self.ts[k]))
        return img, tt, float(abs(self.ts[k] - t))

    def detect(self, img, t):
        me = self.S.self_at(t)
        out, dt = {}, {}
        t0 = time.perf_counter()
        out["discs"] = self.mm.detect_ability_discs(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), self.floor,
                                                    self.static_peaks, me, k=27, bh_min=120)
        dt["discs"] = time.perf_counter() - t0; t0 = time.perf_counter()
        out["walls"] = self.mm.detect_ability_walls(img, self.floor, self.static_lines, me)
        dt["walls"] = time.perf_counter() - t0; t0 = time.perf_counter()
        out["trapwire"] = self.mm.detect_trapwire_anchors(img, self.floor, self.static_lines, me)
        dt["trapwire"] = time.perf_counter() - t0
        return out, dt, me


def _pts(name, cands):
    if name == "walls":
        return [(c["cx"], c["cy"], c["x1"], c["y1"], c["x2"], c["y2"]) for c in cands]
    if name == "trapwire":
        return [(c["cx"], c["cy"], *c["anchor1"], *c["anchor2"]) for c in cands]
    return [(c["cx"], c["cy"]) for c in cands]


def _near(p, cand):
    """Distance from p to a candidate: its centre, or the nearest point of its segment."""
    if len(cand) == 2:
        return float(np.hypot(cand[0] - p[0], cand[1] - p[1]))
    from reticle.minimap import _point_to_segment_dist
    return _point_to_segment_dist(p[0], p[1], *cand[2:6])


def run_generic(out: Path, sheet_dir: Path | None = None):
    rows = {"paint": [], "trapwire": [], "review": []}
    # 1. The player's exhaustive paint frames.
    for f in sorted((E.STORE.root / "labels" / "ability_paint").glob("*.jsonl")):
        sid = f.stem
        G = Generic(sid)
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            img, tt, dts = G.crop(float(r["t_ms"]))
            if img is None or dts > 70:
                rows["paint"].append({"sid": sid, "t_ms": r["t_ms"], "no_crop": True}); continue
            out_, dt, me = G.detect(img, tt)
            icons = [i for i in r.get("icons", []) if i.get("ability") != "self"]
            selves = [i for i in r.get("icons", []) if i.get("ability") == "self"]
            regions = r.get("regions", [])
            rec = {"sid": sid, "t_ms": r["t_ms"], "dt_ms": dts, "icons": len(icons), "time": dt,
                   "abilities": [i.get("ability") for i in icons], "regions": len(regions)}
            for name, cands in out_.items():
                P = _pts(name, cands)
                hit = [any(_near((i["x"], i["y"]), c) <= max(10.0, i.get("r", 0) + 3) for c in P) for i in icons]

                def explained(c):
                    if any(_near((i["x"], i["y"]), c) <= max(10.0, i.get("r", 0) + 3) for i in icons + selves):
                        return True
                    for g in regions:
                        x, y, w, h = g["bbox"]
                        if x - 5 <= c[0] <= x + w + 5 and y - 5 <= c[1] <= y + h + 5:
                            return True
                    return False
                rec[name] = {"cands": len(P), "icons_hit": int(sum(hit)),
                             "hit_by_ability": [a for a, h in zip(rec["abilities"], hit) if h],
                             "explained": int(sum(explained(c) for c in P))}
            rows["paint"].append(rec)
        print("paint", sid, flush=True)
    # 2. Trapwire point labels, as the wall benchmark scores them.
    for f in sorted((E.STORE.root / "labels" / "ability").glob("*.jsonl")):
        if "bak" in f.name:
            continue
        labs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        tw = [l for l in labs if l.get("ability") == "Trapwire" and not l.get("not_ability")]
        if not tw:
            continue
        G = Generic(f.stem)
        for l in tw:
            img, tt, dts = G.crop(float(l["t_ms"]))
            if img is None or dts > 70:
                rows["trapwire"].append({"sid": f.stem, "t_ms": l["t_ms"], "no_crop": True}); continue
            c = G.mm.detect_trapwire_anchors(img, G.floor, static_lines=G.static_lines,
                                             min_wire_length=5.0, max_wire_length=45.0)
            def matched(gx, gy):
                return any(np.hypot(k["cx"] - gx, k["cy"] - gy) < 14.0
                           or np.hypot(k["anchor1"][0] - gx, k["anchor1"][1] - gy) < 12.0
                           or np.hypot(k["anchor2"][0] - gx, k["anchor2"][1] - gy) < 12.0 for k in c)
            gx, gy = float(l["x"]), float(l["y"])
            # The control: the label's point turned 180 deg about the widget centre,
            # kept only where it lands on the slab, so a match there is chance.
            h, w = img.shape[:2]
            mx, my = w - 1 - gx, h - 1 - gy
            on_slab = bool(G.floor[int(np.clip(my, 0, h - 1)), int(np.clip(mx, 0, w - 1))])
            rows["trapwire"].append({"sid": f.stem, "t_ms": l["t_ms"], "dt_ms": dts,
                                     "matched": bool(matched(gx, gy)), "cands": len(c),
                                     "control_on_slab": on_slab,
                                     "control_matched": bool(matched(mx, my)) if on_slab else None})
        print("trapwire", f.stem, flush=True)
    # 3. The player's round-viewer marks on the ability layer.
    for f in sorted((E.STORE.root / "labels" / "round_review").glob("*.jsonl")):
        sid = f.stem
        marks = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        gone = {m["mark_id"] for m in marks if m["kind"] == "retract"}
        G = Generic(sid)
        tiles = []
        for m in marks:
            if m["kind"] != "wrong_here" or not m.get("point"):
                continue
            wx, wy = inset_to_widget(m["point"]["x"], m["point"]["y"], G.S.rect)
            img, tt, dts = G.crop(float(m["t_ms"]))
            if img is None:
                continue
            out_, dt, me = G.detect(img, tt)
            tl = S_.teal(img)
            R, mask = S_.widget(img.shape)
            ring = ring_c2f(tl, mask, R)
            _SURF.clear()
            seg = S_.longest_segment(tl, mask, R, G.S.support)
            near = {n: (min((_near((wx, wy), c) for c in _pts(n, cs)), default=None)) for n, cs in out_.items()}
            near["ring"] = (None if ring["cx"] is None else
                            abs(float(np.hypot(ring["cx"] - wx, ring["cy"] - wy)) - ring["r"]))
            yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
            win = np.hypot(xx - wx, yy - wy) <= 8
            rec = {"mark_id": m["mark_id"], "retracted": m["mark_id"] in gone, "layer": m["layer"],
                   "t_ms": m["t_ms"], "widget_xy": [round(wx, 1), round(wy, 1)], "near_px": near,
                   "ring": ring, "segment": seg, "teal_8px": float(tl[win].mean()),
                   "teal_8px_max": float(tl[win].max()),
                   "bgr_8px": [float(v) for v in img[win].mean(0)]}
            rows["review"].append(rec)
            if sheet_dir is not None:
                v = img.copy()
                cv2.drawMarker(v, (int(wx), int(wy)), (255, 0, 255), cv2.MARKER_CROSS, 14, 1)
                for c in out_["discs"]:
                    cv2.circle(v, (int(c["cx"]), int(c["cy"])), 6, (0, 0, 255), 1)
                for c in out_["walls"]:
                    cv2.line(v, (int(c["x1"]), int(c["y1"])), (int(c["x2"]), int(c["y2"])), (0, 255, 255), 1)
                v = cv2.resize(v, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
                cv2.putText(v, f"{m['mark_id'][:6]} {m['layer']} {m['t_ms'] / 1000:.1f}s"
                            f"{' RETRACTED' if m['mark_id'] in gone else ''}", (6, 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                tiles.append(v)
        if sheet_dir is not None and tiles:
            sheet_dir.mkdir(parents=True, exist_ok=True)
            for n in range(0, len(tiles), 6):
                grp = tiles[n:n + 6]
                while len(grp) % 3:
                    grp.append(np.zeros_like(grp[0]))
                rows_ = [np.hstack(grp[i:i + 3]) for i in range(0, len(grp), 3)]
                cv2.imwrite(str(sheet_dir / f"{sid}_review_{n // 6}.png"), np.vstack(rows_))
        print("review", sid, flush=True)
    # 4. The player's tray-object marks as an icon-recall set: every marked panel of an
    #    ability the player classed "object". Icon abilities are scored per mark, drawn
    #    outlines (rings, the Fury line) at the marks' centroid, the Blaze wall per mark
    #    against the wall detector's segments.
    rows["tray_icons"] = []
    outline = {"Recon Bolt", "Regrowth", "Hunter's Fury"}
    for f in sorted((E.STORE.root / "labels" / "tray_object").glob("*.jsonl")):
        labs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        labs = [l for l in labs if l.get("class") == "object" and l.get("marks")]
        if not labs:
            continue
        G = Generic(f.stem)
        for l in labs:
            by_t = defaultdict(list)
            for m in l["marks"]:
                by_t[float(m["t_ms"])].append((float(m["x"]), float(m["y"])))
            for t, pts in sorted(by_t.items()):
                img, tt, dts = G.crop(t)
                if img is None or dts > 70:
                    continue
                out_, dt, me = G.detect(img, tt)
                ab = l["ability"]
                targets = [tuple(np.mean(pts, 0))] if ab in outline else pts
                det = "walls" if ab == "Blaze" else "discs"
                P = _pts(det, out_[det])
                d = [min((_near(p, c) for c in P), default=None) for p in targets]
                rows["tray_icons"].append({"sid": f.stem, "ability": ab, "t_ms": t, "dt_s": tt / 1000 - l["t_drop_s"],
                                           "targets": len(targets), "detector": det,
                                           "hit10": int(sum(x is not None and x <= 10 for x in d)),
                                           "near_px": d, "cands": len(P),
                                           "self_d": (None if me is None else
                                                      [float(np.hypot(p[0] - me[0], p[1] - me[1])) for p in targets])})
        print("tray_icons", f.stem, flush=True)
    out.write_text(json.dumps(rows, indent=0, default=str), encoding="utf-8")


# ------------------------------------------------------------------ scan

def _allies(sid):
    """Round-entity observations by frame time: (x, y, family, agent) per icon."""
    rows = [json.loads(l) for l in (E.STORE.root / "events" / "round_entity" / f"{sid}.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    ent = {r["id"]: r for r in rows if r.get("kind") == "entity"}
    by_t = defaultdict(list)
    for r in rows:
        if r.get("kind") != "observation" or r.get("x") is None:
            continue
        eid = r.get("entity_id") or ""
        e = ent.get(eid) or ent.get(eid.split("/")[0]) or {}
        by_t[round(float(r["t_ms"]), 1)].append((float(r["x"]), float(r["y"]), r.get("family"), e.get("agent")))
    return by_t


def run_scan(sid, out: Path, hz=2.0):
    """Every live-phase crop at `hz`: the teal gate, the best rings and the widened beam."""
    from reticle import gametime, stalls
    from reticle.cli import _date_of
    from reticle.roi_cache import grid_times
    man = E.STORE.read_manifest(sid)
    date = _date_of(man)
    gt = gametime.build_session_gametime(
        sid, E.STORE.read_hud(sid, date), E.STORE.read_rounds(sid, date).to_pylist(),
        stall_list=stalls.for_session(E.STORE, sid, date))
    S = E.Session(sid)
    ts = np.asarray(S.cache.t_ms, float)
    times = [t for t in grid_times(ts, ts[0], ts[-1], 1.0 / hz)
             if gt.game_time_at(t).phase in ("round_live", "post_plant")]
    allies = _allies(sid)
    akeys = np.array(sorted(allies))
    rows, t_start, n_gate = [], time.perf_counter(), 0
    for smp in S.cache.samples(times, rois=["minimap"]):
        x0, y0, x1, y1 = S.rect
        img = smp.frame[y0:y1, x0:x1]
        t = float(smp.t_ms)
        tl = S_.teal(img)
        R, mask = S_.widget(img.shape)
        t0 = time.perf_counter()
        lab, keep = components(tl, mask, R)
        row = {"t_ms": t, "gate": bool(keep)}
        k = int(np.searchsorted(akeys, t)) if len(akeys) else 0
        near = [akeys[j] for j in (k - 1, k) if 0 <= j < len(akeys) and abs(akeys[j] - t) <= 70]
        icons = allies[near[0]] if near else []
        row["icons"] = [[round(a, 1), round(b, 1), fam, ag] for a, b, fam, ag in icons]
        if keep:
            n_gate += 1
            surf = RingSurface(tl, R, 0.5)
            pk = [c for c in surf.peaks(REFINE_K, R=R) if c[0] >= 0.10]
            rings = []
            if pk:
                radii = np.arange(S_.RING_R[0] * R, S_.RING_R[1] * R + 0.01, 0.5)
                rad = S_._Radial(tl, mask, radii)
                for c in pk:
                    f = refine(tl, mask, R, [c], rad)
                    rings.append([round(f["score"], 4), f["cx"], f["cy"], f["r"], round(c[0], 4)])
            row["rings"] = sorted(rings, reverse=True)
            seg = S_.longest_segment(tl, mask, R, S.support)
            if seg is not None:
                (ax, ay), (bx, by) = seg
                th = float(np.degrees(np.arctan2(by - ay, bx - ax)))
                ox, oy = ax - S_.BEAM_NEAR_PX * np.cos(np.radians(th)), ay - S_.BEAM_NEAR_PX * np.sin(np.radians(th))
                fb = fast_fit_beam(tl, mask, ox, oy, R, around=th)
                row["beam"] = [round(fb["score"], 4), round(S_.on_map(fb, S.support), 3) if S.support is not None
                               else None, round(fb["theta_deg"], 1), round(fb["x0"], 1), round(fb["y0"], 1),
                               round(fb["x1"], 1), round(fb["y1"], 1)]
        row["fit_s"] = round(time.perf_counter() - t0, 4)
        rows.append(row)
        if len(rows) % 500 == 0:
            print(sid, len(rows), "of", len(times), "gated", n_gate, "%.0f s" % (time.perf_counter() - t_start),
                  flush=True)
    out.write_text(json.dumps({"sid": sid, "hz": hz, "times": len(times), "shape": list(img.shape[:2]),
                               "rows": rows, "wall_s": time.perf_counter() - t_start}, default=str),
                   encoding="utf-8")


# ------------------------------------------------------------------ icons

#: Icon radii as a share of the widget radius R. A thrown ability's icon is a
#: round dark disc 16-24 px across at 465 px [domain:abilities/minimap-thrown-ability-icon];
#: team smokes are larger grey discs; the range spans both.
ICON_R = (0.025, 0.075)
ICON_DARK_V = 75          # HSV value under which a pixel is "dark"
ICON_MIN = 0.35           # dark share of the disc minus the dark share round it
ICON_VERSION = "icon-proposer-0.1.0"


#: 0.2.0: with `floor` (the baked slab, `minimap.slab_mask(geometry.reference_static)`)
#: darkness counts only on slab pixels and each share is over slab pixels, so the
#: map's own void holes and the world behind the widget stop reading as dark discs.
ICON_FLOOR_MIN = (0.5, 0.3)   # slab share a disc, and its outer band, must have


def icon_candidates(img, R, min_score=ICON_MIN, floor=None):
    """Dark compact discs: the dark share of a disc minus that of a band 1.5-4 px outside it.

    Each candidate carries its rim colour (teal, red) and its white-glyph share, which
    later stages read as side and kind evidence; the proposer itself names nothing.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    V = hsv[..., 2].astype(np.float32)
    dark = (V < ICON_DARK_V).astype(np.float32)
    fl = None if floor is None else (floor > 0).astype(np.float32)
    if fl is not None:
        dark = dark * fl
    best = np.full(dark.shape, -9.0, np.float32)
    arg = np.zeros(dark.shape, np.float32)
    for r in np.arange(ICON_R[0] * R, ICON_R[1] * R + 0.01, 0.5):
        n = int(np.ceil(r + 5))
        yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
        d = np.hypot(xx, yy)
        kd = (d <= r).astype(np.float32); kd /= kd.sum()
        out_w = max(3.0, 0.4 * r)
        ka = ((d > r + 1.5) & (d <= r + 1.5 + out_w)).astype(np.float32); ka /= ka.sum()
        if fl is None:
            s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) - \
                cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_REPLICATE)
        else:
            fd = cv2.filter2D(fl, -1, kd, borderType=cv2.BORDER_CONSTANT)
            fa = cv2.filter2D(fl, -1, ka, borderType=cv2.BORDER_CONSTANT)
            s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) / np.maximum(fd, 1e-3) - \
                cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_CONSTANT) / np.maximum(fa, 1e-3)
            s[(fd < ICON_FLOOR_MIN[0]) | (fa < ICON_FLOOR_MIN[1])] = -9.0
        up = s > best
        best[up], arg[up] = s[up], r
    k = max(3, int(2 * ICON_R[0] * R) | 1)
    peak = (best >= min_score) & (best == cv2.dilate(best, np.ones((k, k), np.uint8)))
    ys, xs = np.nonzero(peak)
    order = np.argsort(-best[ys, xs])
    keep = []
    for i in order:
        x, y, r = int(xs[i]), int(ys[i]), float(arg[ys[i], xs[i]])
        if any(np.hypot(x - c["cx"], y - c["cy"]) < 0.8 * (r + c["r"]) for c in keep):
            continue
        keep.append({"cx": x, "cy": y, "r": r, "score": float(best[y, x])})
    H, S_, Hh = hsv[..., 2], hsv[..., 1], hsv[..., 0]
    h, w = dark.shape
    yy, xx = np.mgrid[0:h, 0:w]
    for c in keep:
        dd = np.hypot(xx - c["cx"], yy - c["cy"])
        rim = (dd > c["r"] - 1) & (dd <= c["r"] + 2.5)
        sat = rim & (S_ >= 70)
        c["rim_teal"] = float(((Hh >= 75) & (Hh <= 105) & sat).sum() / max(rim.sum(), 1))
        c["rim_red"] = float((((Hh <= 10) | (Hh >= 170)) & sat).sum() / max(rim.sum(), 1))
        core = dd <= 0.7 * c["r"]
        c["glyph_white"] = float(((H > 190) & core).sum() / max(core.sum(), 1))
    return keep


_ICON_TERMS: dict = {}


def _icon_terms(floor, R, step):
    """Per radius: the disc and band kernels and the slab terms, which depend on the
    baked slab alone and so are computed once a session rather than once a crop."""
    key = (id(floor), floor.shape, round(R, 3), step)
    if key not in _ICON_TERMS:
        fl = (floor > 0).astype(np.float32)
        out = []
        for r in np.arange(ICON_R[0] * R, ICON_R[1] * R + 0.01, step):
            n = int(np.ceil(r + 5))
            yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
            d = np.hypot(xx, yy)
            kd = (d <= r).astype(np.float32); kd /= kd.sum()
            out_w = max(3.0, 0.4 * r)
            ka = ((d > r + 1.5) & (d <= r + 1.5 + out_w)).astype(np.float32); ka /= ka.sum()
            fd = cv2.filter2D(fl, -1, kd, borderType=cv2.BORDER_CONSTANT)
            fa = cv2.filter2D(fl, -1, ka, borderType=cv2.BORDER_CONSTANT)
            bad = (fd < ICON_FLOOR_MIN[0]) | (fa < ICON_FLOOR_MIN[1])
            out.append((float(r), kd, ka, 1.0 / np.maximum(fd, 1e-3), 1.0 / np.maximum(fa, 1e-3), bad))
        _ICON_TERMS[key] = (fl, out)
    return _ICON_TERMS[key]


def icon_candidates_fast(img, R, floor, min_score=ICON_MIN, step=0.5):
    """`icon_candidates(floor=...)` with the slab terms cached a session and the rim read
    in a window: the same scores at step 0.5, cheaper; `step` coarsens the radii."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    fl, terms = _icon_terms(floor, R, step)
    dark = (hsv[..., 2] < ICON_DARK_V).astype(np.float32) * fl
    best = np.full(dark.shape, -9.0, np.float32)
    arg = np.zeros(dark.shape, np.float32)
    for r, kd, ka, ifd, ifa, bad in terms:
        s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) * ifd - \
            cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_CONSTANT) * ifa
        s[bad] = -9.0
        up = s > best
        best[up], arg[up] = s[up], r
    k = max(3, int(2 * ICON_R[0] * R) | 1)
    peak = (best >= min_score) & (best == cv2.dilate(best, np.ones((k, k), np.uint8)))
    ys, xs = np.nonzero(peak)
    order = np.argsort(-best[ys, xs])
    keep = []
    for i in order:
        x, y, r = int(xs[i]), int(ys[i]), float(arg[ys[i], xs[i]])
        if any(np.hypot(x - c["cx"], y - c["cy"]) < 0.8 * (r + c["r"]) for c in keep):
            continue
        keep.append({"cx": x, "cy": y, "r": r, "score": float(best[y, x])})
    h, w = dark.shape
    for c in keep:
        m = int(np.ceil(c["r"] + 3))
        x0, x1, y0, y1 = max(0, c["cx"] - m), min(w, c["cx"] + m + 1), max(0, c["cy"] - m), min(h, c["cy"] + m + 1)
        win = hsv[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dd = np.hypot(xx - c["cx"], yy - c["cy"])
        rim = (dd > c["r"] - 1) & (dd <= c["r"] + 2.5)
        sat = rim & (win[..., 1] >= 70)
        Hh = win[..., 0]
        c["rim_teal"] = float(((Hh >= 75) & (Hh <= 105) & sat).sum() / max(rim.sum(), 1))
        c["rim_red"] = float((((Hh <= 10) | (Hh >= 170)) & sat).sum() / max(rim.sum(), 1))
        core = dd <= 0.7 * c["r"]
        c["glyph_white"] = float(((win[..., 2] > 190) & core).sum() / max(core.sum(), 1))
    return keep


def icon_candidates_window(img, R, floor, centres, radius, min_score=ICON_MIN, step=1.0):
    """`icon_candidates_fast` restricted to squares of half-side `radius` round each of
    `centres`: the prior's search (near a caster's icon, near a tracked icon). Each square
    is read with a margin of the largest kernel, so a score inside it equals the full
    search's; candidates are merged across squares by the same suppression."""
    hsv_full = None
    fl, terms = _icon_terms(floor, R, step)
    h, w = img.shape[:2]
    m = int(np.ceil(ICON_R[1] * R + 5 + max(3.0, 0.4 * ICON_R[1] * R) + 2))
    k = max(3, int(2 * ICON_R[0] * R) | 1)
    found = []
    for cx, cy in centres:
        bx0, bx1 = max(0, int(cx - radius)), min(w, int(cx + radius) + 1)
        by0, by1 = max(0, int(cy - radius)), min(h, int(cy + radius) + 1)
        if bx1 <= bx0 or by1 <= by0:
            continue
        x0, x1, y0, y1 = max(0, bx0 - m), min(w, bx1 + m), max(0, by0 - m), min(h, by1 + m)
        hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        dark = (hsv[..., 2] < ICON_DARK_V).astype(np.float32) * fl[y0:y1, x0:x1]
        best = np.full(dark.shape, -9.0, np.float32)
        arg = np.zeros(dark.shape, np.float32)
        for r, kd, ka, ifd, ifa, bad in terms:
            s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) * ifd[y0:y1, x0:x1] - \
                cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_CONSTANT) * ifa[y0:y1, x0:x1]
            s[bad[y0:y1, x0:x1]] = -9.0
            up = s > best
            best[up], arg[up] = s[up], r
        peak = (best >= min_score) & (best == cv2.dilate(best, np.ones((k, k), np.uint8)))
        ys, xs = np.nonzero(peak)
        for yy, xx in zip(ys, xs):
            X, Y = int(xx) + x0, int(yy) + y0
            if bx0 <= X < bx1 and by0 <= Y < by1:
                found.append((float(best[yy, xx]), X, Y, float(arg[yy, xx])))
    keep = []
    for sc, x, y, r in sorted(set(found), reverse=True):
        if any(np.hypot(x - c["cx"], y - c["cy"]) < 0.8 * (r + c["r"]) for c in keep):
            continue
        keep.append({"cx": x, "cy": y, "r": r, "score": sc})
    return keep


def icon_verify(img, R, floor, tracks, half=2, step=1.0, min_score=ICON_MIN):
    """The prior's verify step: each tracked icon `{cx, cy, r}` rescored only at centres
    within `half` px and at its own radius and the two beside it, on the same terms as
    `icon_candidates_fast`. Returns one dict per track, `score` None when no centre and
    radius pass `min_score` (the track is lost: a surprise for the full search)."""
    fl, terms = _icon_terms(floor, R, step)
    radii = np.array([t[0] for t in terms])
    n = int(np.ceil(ICON_R[1] * R + 5))
    h, w = img.shape[:2]
    out = []
    for tr in tracks:
        cx, cy = int(tr["cx"]), int(tr["cy"])
        x0, x1, y0, y1 = max(0, cx - half - n), min(w, cx + half + n + 1), max(0, cy - half - n), min(h, cy + half + n + 1)
        hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        dark = (hsv[..., 2] < ICON_DARK_V).astype(np.float32) * fl[y0:y1, x0:x1]
        i = int(np.argmin(np.abs(radii - tr["r"])))
        cx0, cx1, cy0, cy1 = max(0, cx - half) - x0, min(w, cx + half + 1) - x0, max(0, cy - half) - y0, min(h, cy + half + 1) - y0
        best = (-9.0, None, None, None)
        for j in range(max(0, i - 1), min(len(terms), i + 2)):
            r, kd, ka, ifd, ifa, bad = terms[j]
            s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) * ifd[y0:y1, x0:x1] - \
                cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_CONSTANT) * ifa[y0:y1, x0:x1]
            s[bad[y0:y1, x0:x1]] = -9.0
            core = s[cy0:cy1, cx0:cx1]
            k = np.unravel_index(int(np.argmax(core)), core.shape)
            if core[k] > best[0]:
                best = (float(core[k]), cx0 + k[1] + x0, cy0 + k[0] + y0, r)
        sc, x, y, r = best
        out.append({"cx": x, "cy": y, "r": r, "score": sc if sc >= min_score else None})
    return out


def _propose(img, R, floor):
    """0.1.0 without a slab, 0.2.0 with one; ICON_STEP selects the cached variant."""
    step = os.environ.get("ICON_STEP")
    if step and floor is not None:
        return icon_candidates_fast(img, R, floor, step=float(step))
    return icon_candidates(img, R, floor=floor)


def _player_icons(sid):
    """Round-entity positions by frame time: the players' own icons, to explain candidates."""
    try:
        return _allies(sid)
    except FileNotFoundError:
        return {}


def run_icons(out: Path, sheet_dir: Path | None = None):
    """The icon proposer on the player's icon labels, and its candidate rate on the null crops."""
    rows = {"targets": [], "null": []}
    outline = {"Recon Bolt", "Regrowth", "Hunter's Fury"}
    tiles = []

    def score(sid, S, ts, floor, t, pts, source, ability):
        k = int(np.argmin(np.abs(ts - t)))
        if abs(ts[k] - t) > 70:
            return
        img, tt = S.crop(float(ts[k]))
        R = img.shape[1] / 2.0
        t0 = time.perf_counter()
        cands = _propose(img, R, floor)
        dt = time.perf_counter() - t0
        for p in pts:
            d = [(float(np.hypot(c["cx"] - p[0], c["cy"] - p[1])), c) for c in cands]
            d.sort(key=lambda z: z[0])
            hit = d[0] if d and d[0][0] <= max(6.0, d[0][1]["r"]) else None
            rows["targets"].append({"sid": sid, "source": source, "ability": ability, "t_ms": tt,
                                    "hit": hit is not None, "near_px": d[0][0] if d else None,
                                    "cand": hit[1] if hit else None, "cands": len(cands), "s": dt})
        if sheet_dir is not None and len(tiles) < 36:
            v = img.copy()
            for c in cands:
                cv2.circle(v, (c["cx"], c["cy"]), int(round(c["r"])) + 2, (0, 0, 255), 1)
            for p in pts:
                cv2.drawMarker(v, (int(p[0]), int(p[1])), (255, 0, 255), cv2.MARKER_CROSS, 8, 1)
            v = cv2.resize(v, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            cv2.putText(v, f"{sid[:6]} {ability} {tt / 1000:.1f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1)
            tiles.append(v)

    sessions = {}

    def sess(sid):
        if sid not in sessions:
            try:
                S = E.Session(sid)
            except SystemExit:
                orig = E.STORE.read_minimap
                E.STORE.read_minimap = lambda *a, **k: _EmptyTrack()
                try:
                    S = E.Session(sid)
                finally:
                    E.STORE.read_minimap = orig
            from reticle import minimap
            floor = minimap.slab_mask(S.static) if os.environ.get("ICON_FLOOR") else None
            sessions[sid] = (S, np.asarray(S.cache.t_ms, float), floor)
        return sessions[sid]

    # The tray-object icon marks (the player's own thrown and sent abilities).
    for f in sorted((E.STORE.root / "labels" / "tray_object").glob("*.jsonl")):
        for l in (json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()):
            if l.get("class") != "object" or l["ability"] in outline or l["ability"] == "Blaze":
                continue
            by_t = defaultdict(list)
            for m in l["marks"]:
                by_t[float(m["t_ms"])].append((float(m["x"]), float(m["y"])))
            S, ts, fl = sess(f.stem)
            for t, pts in sorted(by_t.items()):
                score(f.stem, S, ts, fl, t, pts, "tray_object", l["ability"])
        print("icons tray", f.stem, flush=True)
    # The paint frames' icons.
    for f in sorted((E.STORE.root / "labels" / "ability_paint").glob("*.jsonl")):
        S, ts, fl = sess(f.stem)
        for r in (json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()):
            for i in r.get("icons", []):
                if i.get("ability") != "self":
                    score(f.stem, S, ts, fl, float(r["t_ms"]), [(float(i["x"]), float(i["y"]))], "paint", i["ability"])
        print("icons paint", f.stem, flush=True)
    # The round-viewer ability marks.
    for f in sorted((E.STORE.root / "labels" / "round_review").glob("*.jsonl")):
        marks = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        gone = {m["mark_id"] for m in marks if m["kind"] == "retract"}
        S, ts, fl = sess(f.stem)
        for m in marks:
            if m["kind"] != "wrong_here" or m.get("layer") != "ability" or m["mark_id"] in gone:
                continue
            wx, wy = inset_to_widget(m["point"]["x"], m["point"]["y"], S.rect)
            score(f.stem, S, ts, fl, float(m["t_ms"]), [(wx, wy)], "round_review", "unnamed")
        print("icons review", f.stem, flush=True)
    # The null crops: candidates per crop, and how many a player icon explains.
    null = json.loads(Path(os.environ["NULL_JSON"]).read_text(encoding="utf-8")) if os.environ.get("NULL_JSON") else []
    ntiles, picons = [], {}
    for r in null:
        S, ts, fl = sess(r["sid"])
        img, tt = S.crop(float(r["t_ms"]))
        R = img.shape[1] / 2.0
        cands = _propose(img, R, fl)
        icons = picons.setdefault(r["sid"], _player_icons(r["sid"]) if r["sid"] not in picons else None)
        keys = np.array(sorted(icons)) if icons else np.array([])
        near = []
        if len(keys):
            j = int(np.argmin(np.abs(keys - tt)))
            if abs(keys[j] - tt) <= 70:
                near = icons[keys[j]]
        expl = [any(np.hypot(c["cx"] - a, c["cy"] - b) <= 0.04 * R + c["r"] for a, b, _, _ in near) for c in cands]
        rows["null"].append({"sid": r["sid"], "t_ms": tt, "cands": len(cands), "player_icon": int(sum(expl)),
                             "icons_known": len(near), "list": cands})
        if sheet_dir is not None and len(ntiles) < 24 and len(cands) > sum(expl):
            v = img.copy()
            for c, e in zip(cands, expl):
                cv2.circle(v, (c["cx"], c["cy"]), int(round(c["r"])) + 2, (0, 255, 0) if e else (0, 0, 255), 1)
            v = cv2.resize(v, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            cv2.putText(v, f"null {r['sid'][:6]} {tt / 1000:.1f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1)
            ntiles.append(v)
    print("icons null", len(rows["null"]), flush=True)
    if sheet_dir is not None:
        sheet_dir.mkdir(parents=True, exist_ok=True)
        for name, tl_ in (("targets", tiles), ("null", ntiles)):
            for n in range(0, len(tl_), 6):
                grp = tl_[n:n + 6]
                while len(grp) % 3:
                    grp.append(np.zeros_like(grp[0]))
                cv2.imwrite(str(sheet_dir / f"icons_{name}_{n // 6}.png"),
                            np.vstack([np.hstack(grp[i:i + 3]) for i in range(0, len(grp), 3)]))
    out.write_text(json.dumps(rows, default=str), encoding="utf-8")


# ------------------------------------------------------------------ main

def main(argv):
    below_normal()
    cmd = argv[0]
    if cmd == "marks":
        run_marks(Path(argv[1]))
    elif cmd == "null":
        run_null(Path(argv[1]))
    elif cmd == "generic":
        run_generic(Path(argv[1]), Path(argv[2]) if len(argv) > 2 else None)
    elif cmd == "icons":
        run_icons(Path(argv[1]), Path(argv[2]) if len(argv) > 2 else None)
    elif cmd == "scan":
        run_scan(argv[1], Path(argv[2]), float(argv[3]) if len(argv) > 3 else 2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
