r"""Measure and detect the drawn ability areas: Sonic Sensor and Trademark.

    .\.venv\Scripts\python.exe prototypes\drawn_areas.py dump SID T_S [--around S]
    .\.venv\Scripts\python.exe prototypes\drawn_areas.py measure [--record]
    .\.venv\Scripts\python.exe prototypes\drawn_areas.py detect [--record]
    .\.venv\Scripts\python.exe prototypes\drawn_areas.py rendezvous

Reads the minimap crop cache and baked geometry only; decodes no video. Each ability is measured
on its own instances, never by analogy [domain:abilities/ability-rules-are-unique]. The player
named 5822b6646448 at 1901.083 s (two Sonic Sensors), bfad2778a372 at 1682.250 s,
223d636bf8d2 at 882.300 s and e37fdeca944f at 1795.083 s (Trademarks); a06f04a0059f 513.5 s
(two sensors) and 9acf02f98283 1047.333 s (a Trademark) were found by eye and checked.

`measure` fits each area on the median of 13 frames round the named time, reads the tint alpha
from the model `(1 - a) * static + a * 255`, and writes overlays and glyph templates to
`<store>/analysis/drawn-areas-20260930/`.

- Sonic Sensor [domain:abilities/deadlock-sonic-sensor-minimap-white-area]: an axis-aligned square, 25-29 by 24-33 px at scale 1, with the icon on the
  midpoint of one side; interior alpha 0.16-0.18 and rim 0.18-0.20, so no rim; drawn over void
  at the same alpha. A dim (inactive) icon draws no square.
- Trademark [domain:abilities/chamber-trademark-minimap-white-area]: a circle centred on the icon (offset under 1 px, residual under 0.3 px). Its widget
  radius follows the map's zoom: 30.7 (Split), 29.9 (Haven), 30.9 (Sunset), 27.2 (Ascent) px at
  scale 1. Rim alpha 0.41-0.51 over floor and void; interior 0.13-0.16 over floor.
- Neither lights the floor. A cone crossing either area lifts it as much as floor outside
  (`cone_test`); an area that drew lit floor could not be lifted further. The lighting
  reference in `team_vision` learned the bfad Trademark's tint as lit floor, so its
  lit-position reads high there and is no evidence.
- Durations are runs of icon-plus-area presence at 1 s, bridged over 3 missing samples. Gaps in
  the crop cache censor most ends; runs of 17-83 s were seen. The one uncensored Trademark end
  is 223d at 914.3 s; what ended it was not read. At 9acf a Trademark stands on the same spot in
  three runs split by cache gaps (936-978 s, 1030-1080 s, 1108-1121 s).

`detect` finds both areas on one frame from the minimap alone: a dark icon-sized disc inside the
slab, a glyph correlating at least 0.6 with a mined template of the ability (templates from the
frame's own session are excluded), then the ability's area round it. It is scored on ten frames
spread over each measured run and on 120 frames of four sessions with no Deadlock or Chamber in
the stored lineup. The void pass of `icon_candidates`, the sector rim and the two-centre rim
search were added after the e37 and 9acf positives missed, so those two are not held out.

`rendezvous` searches the Chamber sessions for rings round dark icons that are not Trademarks.
It identified no Rendezvous; its appearance stays unmeasured
[domain:abilities/chamber-rendezvous-minimap-white-radius].
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "4"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from ctypes import wintypes  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, team_vision  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

cv2.setNumThreads(4)
VERSION = "drawn-areas-0.1.0"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "drawn-areas-20260930"


def below_normal() -> str:
    """Below Normal priority for this process, checked after it is set."""
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.GetPriorityClass.argtypes = [wintypes.HANDLE]
    h = k.GetCurrentProcess()
    k.SetPriorityClass(h, 0x4000)
    got = k.GetPriorityClass(h)
    if got != 0x4000:
        raise SystemExit(f"priority is {got:#x}, not Below Normal")
    return "below_normal"


class Sess:
    """One session's baked inputs (`team_vision.load_inputs`) and its minimap crop cache."""

    def __init__(self, sid: str):
        self.sid = sid
        man = geometry.manifest(sid, STORE)
        self.capture = man["source"]["path"].replace("\\", "/")
        prof = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        self.inputs, why = team_vision.load_inputs(STORE, sid, prof, w, h)
        if self.inputs is None:
            raise SystemExit(f"{sid}: no inputs ({why})")
        self.box = self.inputs.box
        self.static = self.inputs.static
        self.floor, self.slab, self.ref = self.inputs.floor, self.inputs.slab, self.inputs.light
        self.key = self.inputs.geometry_key
        self.cache, why = RoiCache.load(STORE, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))

    def snap(self, t: float) -> float:
        return float(self.cache_t[int(np.argmin(np.abs(self.cache_t - t)))])

    def crops(self, times):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples([float(t) for t in times], rois=["minimap"]):
            yield smp.t_ms, smp.frame[y0:y1, x0:x1]


def cmd_dump(a) -> int:
    below_normal()
    s = Sess(a.sid)
    d = OUT / "dump"
    d.mkdir(parents=True, exist_ok=True)
    t = a.t * 1000.0
    offs = [float(x) for x in a.offsets.split(",")]
    times = sorted({s.snap(t + o * 1000.0) for o in offs})
    for tt, c in s.crops(times):
        cv2.imwrite(str(d / f"{a.sid}_{int(round(tt))}.png"),
                    cv2.resize(c, None, fx=a.zoom, fy=a.zoom, interpolation=cv2.INTER_NEAREST))
    cv2.imwrite(str(d / f"{a.sid}_static.png"),
                cv2.resize(s.static, None, fx=a.zoom, fy=a.zoom, interpolation=cv2.INTER_NEAREST))
    print(a.sid, s.key, s.box, s.static.shape, [round(x / 1000, 3) for x in times])
    return 0


SENSOR, TRADEMARK = "sonic_sensor", "trademark"

#: The instances the player named (2026-09-30) or that sit beside them, as (ability, session,
#: time s, icon hint x, y on the widget crop). The icon centre is refined from the hint.
INSTANCES = [
    (SENSOR, "5822b6646448", 1901.083, 86, 293),     # C site, near Deadlock (the player)
    (SENSOR, "5822b6646448", 1901.083, 214, 259),    # B site, near Gekko and Omen (the player)
    (SENSOR, "a06f04a0059f", 513.5, 94, 182),        # seen, Deadlock in the stored lineup
    (SENSOR, "a06f04a0059f", 513.5, 137, 169),
    (TRADEMARK, "bfad2778a372", 1682.25, 82, 234),   # the player
    (TRADEMARK, "223d636bf8d2", 882.3, 185, 233),    # the player
    (TRADEMARK, "e37fdeca944f", 1795.083, 143, 123),  # the player
    (TRADEMARK, "9acf02f98283", 1047.333, 204, 144),  # found by `rendezvous`'s ring scan, seen
]

#: Grey levels a pixel must rise over the baked static to count as drawn area.
LIFT_MIN = 8
#: The ability icon: a dark disc. Grey below this is icon body.
DARK_MAX = 60
#: Icon radius prior per ability, px at scale 1.0: the sensor's disc is 22 px across on the 465 px
#: widget, the Trademark's about 17 (read off the named frames, then measured below).
ICON_R_BY = {"sonic_sensor": 10.5, "trademark": 8.6}


def scale_of(static: np.ndarray) -> float:
    return static.shape[1] / 465.0


def gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


#: The icon disc differs from the static by more than this: its dark body falls, its white glyph
#: rises, and together they fill the disc (the drawn areas lift 16-25 levels, less than this).
ICON_DIFF = 40


def refine_icon(g: np.ndarray, st: np.ndarray, hx: int, hy: int, sc: float,
                icon_r: float) -> tuple[float, float, float] | None:
    """The icon disc's centre and radius near the hint: the component under the hint of pixels
    differing from the static by ICON_DIFF, fitted by its enclosing circle."""
    ICON_R = icon_r  # noqa: N806
    r = int(round(ICON_R * sc * 1.6))
    y0, x0 = max(0, hy - r), max(0, hx - r)
    sub = (np.abs(g - st)[y0:hy + r + 1, x0:hx + r + 1] > ICON_DIFF).astype(np.uint8)
    # dark things beyond the icon's own reach (void, a passing icon's outline) are cut off first
    yy, xx = np.mgrid[0:sub.shape[0], 0:sub.shape[1]]
    sub[np.hypot(xx + x0 - hx, yy + y0 - hy) > 1.35 * ICON_R * sc] = 0
    # a disc touching dark void merges with it: retry with the mask eroded one pixel
    for grow, m in ((0.0, sub), (1.0, cv2.erode(sub, np.ones((3, 3), np.uint8)))):
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        best = None
        for c in cs:
            (cx, cy), rad = cv2.minEnclosingCircle(c)
            rad += grow
            d = math.hypot(cx + x0 - hx, cy + y0 - hy)
            if 0.6 * ICON_R * sc <= rad <= 1.5 * ICON_R * sc and d <= ICON_R * sc:
                if best is None or d < best[0]:
                    best = (d, cx + x0, cy + y0, rad)
        if best is not None:
            return best[1], best[2], best[3]
    return None


def window(s: "Sess", t_s: float, half_s: float, step_s: float) -> tuple[list[float], np.ndarray]:
    times = sorted({s.snap(t_s * 1000 + k * step_s * 1000)
                    for k in range(-int(half_s / step_s), int(half_s / step_s) + 1)})
    ts, cs = [], []
    for tt, c in s.crops(times):
        ts.append(tt)
        cs.append(c)
    return ts, np.stack(cs)


DIRS = ("up", "down", "left", "right")
#: The square search, px at scale 1.0: width across the icon's side, height away from it, the
#: side's offset past the icon centre (positive: the icon sits inside the square) and the lateral
#: offset of the icon from the side's midpoint.
SQ_W, SQ_H, SQ_E, SQ_LAT = (16, 36), (16, 36), (-3, 10), (-4, 4)
#: The band outside the square its lift is compared with, px at scale 1.0.
SQ_BAND = 3


def square_rect(icon: tuple, d: str, W: float, H: float, e: float, lat: float) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1), exclusive ends, of an axis-aligned square whose one side runs past the icon."""
    cx, cy = icon[0], icon[1]
    if d == "up":
        x0, x1, y1 = cx + lat - W / 2, cx + lat + W / 2, cy + e
        y0 = y1 - H
    elif d == "down":
        x0, x1, y0 = cx + lat - W / 2, cx + lat + W / 2, cy - e
        y1 = y0 + H
    elif d == "left":
        y0, y1, x1 = cy + lat - W / 2, cy + lat + W / 2, cx + e
        x0 = x1 - H
    else:
        y0, y1, x0 = cy + lat - W / 2, cy + lat + W / 2, cx - e
        x1 = x0 + H
    return int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))


def fit_square(L: np.ndarray, ok: np.ndarray, icon: tuple, sc: float) -> dict | None:
    """The drawn square as a matched filter on the lift over the static: the axis-aligned rectangle,
    one side running past the icon, whose mean lift most exceeds the lift in a band just outside
    it. Only opaque-slab pixels off the icon count. Axis-aligned only: every instance seen lies
    on an axis-aligned wall; a rotated square would score low and show in `edge_contrast`."""
    h, w = L.shape
    yy, xx = np.mgrid[0:h, 0:w]
    use = ok & (np.hypot(xx - icon[0], yy - icon[1]) > icon[2] + 1)
    I1 = cv2.integral(np.where(use, L, 0).astype(np.float64))
    I0 = cv2.integral(use.astype(np.float64))

    def box(I, x0, y0, x1, y1):
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        return I[y1, x1] - I[y0, x1] - I[y1, x0] + I[y0, x0]

    b = max(2, int(round(SQ_BAND * sc)))
    best = None
    rng = lambda lo_hi, step=1.0: np.arange(lo_hi[0] * sc, lo_hi[1] * sc + 1e-6, step)  # noqa: E731
    for d in DIRS:
        for W in rng(SQ_W):
            for H in rng(SQ_H):
                for e in rng(SQ_E):
                    for lat in rng(SQ_LAT):
                        x0, y0, x1, y1 = square_rect(icon, d, W, H, e, lat)
                        n_in = box(I0, x0, y0, x1, y1)
                        n_out = box(I0, x0 - b, y0 - b, x1 + b, y1 + b) - n_in
                        if n_in < 0.4 * W * H or n_out < 4 * b:
                            continue
                        m_in = box(I1, x0, y0, x1, y1) / n_in
                        m_out = (box(I1, x0 - b, y0 - b, x1 + b, y1 + b) - box(I1, x0, y0, x1, y1)) / n_out
                        s = m_in - m_out
                        if best is None or s > best[0]:
                            best = (s, d, W, H, e, lat, (x0, y0, x1, y1), m_in, m_out)
    if best is None:
        return None
    s, d, W, H, e, lat, (x0, y0, x1, y1), m_in, m_out = best
    # per side: the lift just inside the edge minus just outside (a drawn edge is a step)
    def strip(xa, ya, xb, yb):
        n = box(I0, xa, ya, xb, yb)
        return box(I1, xa, ya, xb, yb) / n if n else float("nan")
    ec = {"left": strip(x0, y0, x0 + b, y1) - strip(x0 - b, y0, x0, y1),
          "right": strip(x1 - b, y0, x1, y1) - strip(x1, y0, x1 + b, y1),
          "top": strip(x0, y0, x1, y0 + b) - strip(x0, y0 - b, x1, y0),
          "bottom": strip(x0, y1 - b, x1, y1) - strip(x0, y1, x1, y1 + b)}
    mask = np.zeros((h, w), bool)
    mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    return {"dir": d, "rect": [x0, y0, x1, y1], "w": round(float(W), 1), "h": round(float(H), 1),
            "icon_inset": round(float(e), 1), "icon_lateral": round(float(lat), 1),
            "lift_in": round(m_in, 1), "lift_band": round(m_out, 1), "score": round(s, 1),
            "edge_contrast": {k: (None if math.isnan(v) else round(v, 1)) for k, v in ec.items()},
            "_mask": mask}


def fit_circle(g: np.ndarray, icon: tuple, sc: float, r0: float) -> dict | None:
    """The drawn circle: along 72 rays from the icon centre, the brightest pixel between 0.6 and
    1.4 of the prior radius (the white rim), then a least-squares circle with one trim pass."""
    cx, cy, _ = icon
    h, w = g.shape
    pts = []
    for a in np.arange(0, 360, 5):
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        rs = np.arange(0.6 * r0, 1.4 * r0, 0.5)
        xs, ys = np.rint(cx + ca * rs).astype(int), np.rint(cy + sa * rs).astype(int)
        okk = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
        if okk.sum() < len(rs) * 0.8:
            continue
        v = g[ys[okk], xs[okk]]
        i = int(np.argmax(v))
        pts.append((xs[okk][i], ys[okk][i], float(v[i])))
    if len(pts) < 12:
        return None
    P = np.array(pts, float)

    def lsq(P):
        A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]
        b = P[:, 0] ** 2 + P[:, 1] ** 2
        (a0, b0, c0), *_ = np.linalg.lstsq(A, b, rcond=None)
        return a0, b0, math.sqrt(max(1e-6, c0 + a0 * a0 + b0 * b0))

    a0, b0, r = lsq(P)
    res = np.abs(np.hypot(P[:, 0] - a0, P[:, 1] - b0) - r)
    keep = res <= max(1.5, np.percentile(res, 75))
    a0, b0, r = lsq(P[keep])
    res = np.abs(np.hypot(P[keep, 0] - a0, P[keep, 1] - b0) - r)
    return {"cx": round(a0, 2), "cy": round(b0, 2), "r": round(r, 2), "rays": int(keep.sum()),
            "resid_px": round(float(np.median(res)), 2),
            "offset_px": round(math.hypot(a0 - cx, b0 - cy), 2)}


def alphas(v: np.ndarray, st: np.ndarray, m: np.ndarray) -> float | None:
    """Median tint alpha over mask m under (1-a)*static + a*255."""
    if not m.any():
        return None
    a = (v[m] - st[m]) / np.maximum(1.0, 255.0 - st[m])
    return round(float(np.median(a)), 3)


#: The Trademark radius prior, px at scale 1.0 (22.5 px seen at the 331 px widget).
TRADEMARK_R0 = 31.6
#: Presence per frame: the area's lift over its outer band must reach this share of the named
#: frame's, with the icon's dark disc present.
PRESENT_SHARE = 0.5
DURATION_HALF_S, DURATION_STEP_S = 120.0, 1.0
#: The glyph template spans this many icon radii either side of the centre (the disc only).
TEMPLATE_SPAN = 0.9
#: A run bridges this many absent samples (an icon crossing the area hides it for a second or two).
RUN_BRIDGE = 3
#: Samples further apart than this straddle a gap in the crop cache: the run's end there is censored.
CACHE_GAP_MS = 2500


def area_masks(ability: str, fit: dict, icon: tuple, shape, sc: float) -> dict:
    """Interior, rim and outer-band masks for one fitted area, the icon disc removed."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    di = np.hypot(xx - icon[0], yy - icon[1])
    off_icon = di > icon[2] + 1.5
    if ability == TRADEMARK:
        d = np.hypot(xx - fit["cx"], yy - fit["cy"])
        r = fit["r"]
        return {"interior": (d < r - 1.5) & off_icon, "rim": np.abs(d - r) <= 0.75,
                "outer": (d >= r + 2.5) & (d <= r + 2.5 + 5 * sc)}
    inside = fit["_mask"].astype(np.uint8)
    k3 = np.ones((3, 3), np.uint8)
    inner = cv2.erode(inside, k3, iterations=max(1, int(round(1.5 * sc))))
    outer = cv2.dilate(inside, k3, iterations=int(round(7 * sc)))
    outer2 = cv2.dilate(inside, k3, iterations=int(round(2 * sc)))
    edge = inside.astype(bool) & ~inner.astype(bool)
    return {"interior": inner.astype(bool) & off_icon, "rim": edge & off_icon,
            "outer": outer.astype(bool) & ~outer2.astype(bool)}


def icon_share(g: np.ndarray, icon: tuple) -> float:
    """The dark share of the icon disc. Presence is judged against the named frame's own share,
    because discs differ: the Ascent Trademark disc is 0.38 dark at its named frame, the others 0.45-0.62."""
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    disc = np.hypot(xx - icon[0], yy - icon[1]) <= icon[2] * 0.9
    return float((g[disc] < DARK_MAX).mean())


def measure_one(s: "Sess", ability: str, t_s: float, hx: int, hy: int) -> dict:
    sc = scale_of(s.static)
    st = gray(s.static)
    ts, cs = window(s, t_s, 3.0, 0.5)
    med = np.median(cs, 0).astype(np.uint8)
    # the icon is refined on the median frame: a player icon passing beside it is gone there
    icon = refine_icon(gray(med), st, hx, hy, sc, ICON_R_BY[ability])
    out = {"ability": ability, "session": s.sid, "capture": s.capture, "t_s": t_s, "key": s.key,
           "scale": round(sc, 4), "hint": [hx, hy]}
    if icon is None:
        out["refused"] = "no dark icon disc at the hint"
        return out
    out["icon"] = {"cx": round(icon[0], 1), "cy": round(icon[1], 1), "r": round(icon[2], 1),
                   "r_scale1": round(icon[2] / sc, 1)}
    gm = gray(med)
    # the fit reads the 25th percentile of 13 frames: a cone or icon passing lifts fewer than a quarter
    g25 = np.percentile(np.stack([gray(c) for c in cs]), 25, axis=0).astype(np.float32)
    L = g25 - st
    slab = s.slab.astype(bool)
    if ability == SENSOR:
        fit = fit_square(L, slab, icon, sc)
    else:
        fit = fit_circle(L, icon, sc, TRADEMARK_R0 * sc)      # on the lift: the static's own lines cancel
    if fit is None:
        out["refused"] = "no area fitted"
        return out
    out["fit"] = {k: v for k, v in fit.items() if not k.startswith("_")}
    if ability == SENSOR:
        out["fit"]["wh_scale1"] = [round(fit["w"] / sc, 1), round(fit["h"] / sc, 1)]
        out["fit"]["inset_lateral_scale1"] = [round(fit["icon_inset"] / sc, 1), round(fit["icon_lateral"] / sc, 1)]
    else:
        out["fit"]["r_scale1"] = round(fit["r"] / sc, 1)
    M = area_masks(ability, fit, icon, st.shape, sc)
    floor = s.floor.astype(bool)
    void = ~slab
    out["alpha"] = {"interior_floor": alphas(gm, st, M["interior"] & floor),
                    "interior_void": alphas(gm, st, M["interior"] & void),
                    "rim_floor": alphas(gm, st, M["rim"] & floor),
                    "rim_void": alphas(gm, st, M["rim"] & void),
                    "outer_floor": alphas(gm, st, M["outer"] & floor),
                    "n_interior_floor": int((M["interior"] & floor).sum()),
                    "n_interior_void": int((M["interior"] & void).sum())}
    # the floor state: the interior against the lighting reference's two states, beside the band outside
    lo, hi = s.ref.lo.astype(np.float32), s.ref.hi.astype(np.float32)
    known = s.ref.known.astype(bool) if getattr(s.ref, "known", None) is not None else floor

    def state(m):
        m = m & floor & known
        if not m.any():
            return None
        v = gm[m]
        pos = (v - lo[m]) / np.maximum(1.0, hi[m] - lo[m])
        return {"n": int(m.sum()), "pos_median": round(float(np.median(pos)), 3),
                "over_hi_median": round(float(np.median(v - hi[m])), 1),
                "share_above_hi_plus5": round(float((v > hi[m] + 5).mean()), 3)}

    out["state"] = {"interior": state(M["interior"]), "outer": state(M["outer"])}
    # Does a cone crossing the area lift it further? Over 30 s either side, a pixel-frame is
    # "brightened" when it rises 8 levels over the pixel's own median. If the area already drew
    # the floor lit, a cone could not lift the interior; a tint lets it lift as much as outside.
    ts2, cs2 = window(s, t_s, 30.0, 0.5)
    G = np.stack([gray(c) for c in cs2])
    ct = {"frames": len(ts2)}
    for name in ("interior", "outer"):
        m = M[name] & floor
        if not m.any():
            continue
        V = G[:, m]
        ex = V - np.median(V, 0)
        up = ex > 8
        ct[name] = {"brightened_share": round(float(up.mean()), 4),
                    "excess_median": round(float(np.median(ex[up])), 1) if up.sum() >= 20 else None,
                    "frames_with_5pct": int((up.mean(1) >= 0.05).sum())}
    out["cone_test"] = ct
    # duration: presence once a second round the named frame
    ts3, cs3 = window(s, t_s, DURATION_HALF_S, DURATION_STEP_S)
    reg, band = M["interior"] & slab, M["outer"] & slab
    pres = []
    for tt, c in zip(ts3, cs3):
        g = gray(c)
        lift = float(np.median((g - st)[reg]) - np.median((g - st)[band])) if reg.any() and band.any() else 0.0
        pres.append((tt, lift, icon_share(g, icon)))
    k0 = int(np.argmin([abs(p[0] - t_s * 1000) for p in pres]))
    named, named_share = pres[k0][1], pres[k0][2]
    pres = [(p[0], p[1], p[2] >= PRESENT_SHARE * named_share) for p in pres]
    on = [p[1] >= PRESENT_SHARE * named and p[2] for p in pres]

    def walk(k, step):
        """The last present sample from k in one direction, bridging up to RUN_BRIDGE absent samples
        (a player icon crossing the area) but stopping at a gap in the crop cache, which censors."""
        last, miss, j = k, 0, k
        while 0 <= j + step < len(on):
            if abs(pres[j + step][0] - pres[j][0]) > CACHE_GAP_MS:
                return last, True
            j += step
            if on[j]:
                last, miss = j, 0
            else:
                miss += 1
                if miss > RUN_BRIDGE:
                    return last, False
        return last, True

    a, cens_a = walk(k0, -1)
    b, cens_b = walk(k0, 1)
    out["duration"] = {"named_lift": round(named, 1), "named_icon_share": round(named_share, 3), "start_s": round(pres[a][0] / 1000, 2),
                       "end_s": round(pres[b][0] / 1000, 2),
                       "seconds": round((pres[b][0] - pres[a][0]) / 1000, 1),
                       "start_censored": cens_a, "end_censored": cens_b,
                       "icon_without_area_s": [round(p[0] / 1000, 1) for p, o in zip(pres, on)
                                               if p[2] and not o and abs(p[0] - t_s * 1000) < 20000],
                       "trace": [[round(p[0] / 1000, 1), round(p[1], 1), int(p[2])] for p in pres]}
    out["_masks"], out["_med"], out["_icon"], out["_fit"] = M, med, icon, fit
    # the icon's glyph as a mined template: the median frame's grey round the refined centre
    R = int(math.ceil(icon[2] * TEMPLATE_SPAN))
    x0, y0 = int(round(icon[0])) - R, int(round(icon[1])) - R
    if x0 >= 0 and y0 >= 0 and x0 + 2 * R + 1 <= gm.shape[1] and y0 + 2 * R + 1 <= gm.shape[0]:
        out["_template"] = gm[y0:y0 + 2 * R + 1, x0:x0 + 2 * R + 1].astype(np.uint8)
    return out


def overlay_one(r: dict, z: int = 6) -> np.ndarray:
    icon = r["_icon"]
    R = int(45 * r["scale"])
    x0, y0 = max(0, int(icon[0]) - R), max(0, int(icon[1]) - R)
    x1, y1 = x0 + 2 * R, y0 + 2 * R
    a = cv2.resize(r["_med"][y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    b = a.copy()
    for name, col in (("interior", (0, 200, 0)), ("rim", (0, 0, 255)), ("outer", (255, 150, 0))):
        m = r["_masks"][name][y0:y1, x0:x1].astype(np.uint8)
        cs, _ = cv2.findContours(cv2.resize(m, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST),
                                 cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(b, cs, -1, col, 1)
    cv2.circle(b, (int((icon[0] - x0) * z), int((icon[1] - y0) * z)), int(icon[2] * z), (255, 0, 255), 1)
    cap = np.full((22, a.shape[1] * 2, 3), 255, np.uint8)
    cv2.putText(cap, f"{r['ability']} {r['session']} {r['t_s']:.3f} s  median of 13 frames  green interior,"
                f" red rim, orange outer band, magenta icon", (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    return np.vstack([cap, np.hstack([a, b])])


_SESS: dict = {}


def sess(sid: str) -> "Sess":
    if sid not in _SESS:
        _SESS[sid] = Sess(sid)
    return _SESS[sid]


#: Frames where the same sensor spots show a dim (grey) icon, seen before measuring: (session,
#: time s, index into INSTANCES of the bright instance at that spot).
DIM = [("a06f04a0059f", 1106.3, 2), ("a06f04a0059f", 1106.3, 3),
       ("a06f04a0059f", 1245.717, 2), ("a06f04a0059f", 1245.717, 3)]


def dim_check(s: "Sess", t_s: float, r: dict) -> dict:
    """The bright instance's fitted square read on a frame with a dim icon at the same spot."""
    st = gray(s.static)
    (tt, c), = list(s.crops([s.snap(t_s * 1000)]))
    g = gray(c)
    M, icon = r["_masks"], r["_icon"]
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    disc = np.hypot(xx - icon[0], yy - icon[1]) <= icon[2] * 0.9
    reg, band = M["interior"] & s.slab.astype(bool), M["outer"] & s.slab.astype(bool)
    return {"session": s.sid, "t_s": round(tt / 1000, 3), "spot": [round(icon[0], 1), round(icon[1], 1)],
            "icon_gray_median": round(float(np.median(g[disc])), 1),
            "icon_dark_share": round(float((g[disc] < DARK_MAX).mean()), 3),
            "area_lift_minus_band": round(float(np.median((g - st)[reg]) - np.median((g - st)[band])), 1),
            "bright_named_lift": r["duration"]["named_lift"]}


SERIES = "drawn_areas"


def _flat_values(r: dict) -> dict:
    """The numbers of one measured instance, flat, for the metrics log."""
    v = {"icon_r": r["icon"]["r"], "icon_r_scale1": r["icon"]["r_scale1"]}
    f = r["fit"]
    if r["ability"] == SENSOR:
        v.update(w=f["w"], h=f["h"], icon_inset=f["icon_inset"], icon_lateral=f["icon_lateral"],
                 lift_in=f["lift_in"], lift_band=f["lift_band"], dir=f["dir"])
    else:
        v.update(r=f["r"], r_scale1=f["r_scale1"], centre_offset=f["offset_px"], resid=f["resid_px"])
    for k, x in r["alpha"].items():
        v[f"alpha_{k}"] = x
    st = r["state"]["interior"]
    if st:
        v["interior_lit_position"] = st["pos_median"]
    for k in ("interior", "outer"):
        c = r["cone_test"].get(k)
        if c:
            v[f"cone_{k}_brightened_share"] = c["brightened_share"]
            v[f"cone_{k}_excess"] = c["excess_median"]
    d = r["duration"]
    v.update(start_s=d["start_s"], end_s=d["end_s"], seconds=d["seconds"])
    return v


def record_measure(rows: list[dict], dims: list[dict]) -> None:
    from reticle import metrics
    deps = {"version": VERSION, "lift_min": LIFT_MIN, "dark_max": DARK_MAX, "icon_r": ICON_R_BY,
            "trademark_r0": TRADEMARK_R0, "present_share": PRESENT_SHARE,
            "sq": [SQ_W, SQ_H, SQ_E, SQ_LAT, SQ_BAND]}
    for r in rows:
        if "fit" not in r or "duration" not in r:
            continue
        part = f"{r['ability']}_{r['hint'][0]}_{r['hint'][1]}"
        metrics.record(SERIES, part=part, session=r["session"], values=_flat_values(r), deps=deps,
                       context={"t_s": r["t_s"], "key": r["key"], "capture": r["capture"]},
                       note="minimap crop cache only; the baked static as background")
    for i, d in enumerate(dims):
        metrics.record(SERIES, part=f"dim_{i}", session=d["session"],
                       values={k: v for k, v in d.items() if isinstance(v, (int, float))}, deps=deps,
                       context={"spot": d["spot"]}, note="a dim sensor icon at a bright instance's spot")


def cmd_measure(a) -> int:
    below_normal()
    OUT.mkdir(parents=True, exist_ok=True)
    rows, full = [], []
    tdir = OUT / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    index = []
    for ab, sid, t, hx, hy in INSTANCES:
        r = measure_one(sess(sid), ab, t, hx, hy)
        full.append(r)
        if "_template" in r:
            name = f"{ab}_{sid}_{hx}_{hy}.png"
            cv2.imwrite(str(tdir / name), r["_template"])
            index.append({"ability": ab, "session": sid, "file": name, "scale": r["scale"],
                          "icon_r": r["icon"]["r"]})
        if "_med" in r:
            cv2.imwrite(str(OUT / f"measure_{ab}_{sid}_{int(t * 1000)}_{hx}_{hy}.png"), overlay_one(r))
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        rows.append(clean)
        print(json.dumps({k: v for k, v in clean.items() if k != "duration"}),
              json.dumps({k: v for k, v in clean.get("duration", {}).items() if k != "trace"}))
    (tdir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    dims = []
    for sid, t, i in DIM:
        if "_masks" in full[i]:
            dims.append(dim_check(sess(sid), t, full[i]))
            print("dim", json.dumps(dims[-1]))
    (OUT / "measure.json").write_text(json.dumps({"version": VERSION, "instances": rows, "dim": dims}, indent=1),
                                      encoding="utf-8")
    if a.record:
        record_measure(rows, dims)
    return 0


# ---------------------------------------------------------------- detector

#: The measured shapes the detector renders (px at scale 1.0; `measure` on the named instances).
DET_SQ_W, DET_SQ_H = 26.0, 28.0
DET_SQ_E = (-3, 4)
DET_TM_R = 30.5
#: The Trademark's widget radius depends on the map's zoom (Split 30.7, Haven 29.9, Ascent 26.0
#: px at scale 1.0), so the detector searches this range, px at scale 1.0.
DET_TM_R_RANGE = (23.0, 35.0)
#: Detection thresholds on the lift over the static (grey levels): the sensor square's mean lift
#: over its outer band, and the Trademark rim's lift over the rings either side of it plus the
#: interior's lift over the band outside. Measured instances score 17-25 (square), rims 40-60.
DET_SQ_MIN, DET_SQ_MAX_IN = 9.0, 40.0
DET_RIM_MIN, DET_TM_IN_MIN = 15.0, 6.0
#: The rim contrast is judged per angular sector, then the sectors' median taken.
TM_SECTORS = 16
#: Sessions whose stored lineup holds neither Deadlock nor Chamber on either side, and that the
#: player named no Trademark in: every detection there is false.
NEGATIVE_SESSIONS = ("3694746e4e54", "4f207c0c4e39", "75a55a296d3b", "b3b9defb6fd7")
NEG_FRAMES = 30


#: An icon pixel over void must read this much darker than the void static.
VOID_DARKER = 12


def icon_candidates(g: np.ndarray, st: np.ndarray, sc: float) -> list[tuple[float, float, float]]:
    """Dark discs of an ability icon's size: components of dark pixels, closed so a glyph's
    white does not split the ring, whose enclosing circle fits either ability's icon. The first
    pass takes pixels dark where the static is not (drawn, not void). A second pass adds pixels
    well below a dark static, for an icon half over void (e37 1795.083 s: 16-28 grey where the
    void static is 34-48). Both passes' discs are kept, since either may be the one centred on
    the icon; detect_frame recentres each on its glyph and suppresses duplicates."""
    rmin = 0.6 * min(ICON_R_BY.values()) * sc
    rmax = 1.35 * max(ICON_R_BY.values()) * sc

    def discs(dark):
        dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, lab, stt, cen = cv2.connectedComponentsWithStats(dark, connectivity=8)
        found = []
        for i in range(1, n):
            if stt[i, 4] < 0.3 * math.pi * rmin * rmin:
                continue
            w_, h_ = stt[i, 2], stt[i, 3]
            if not (2 * rmin <= max(w_, h_) <= 2 * rmax) or min(w_, h_) < 0.7 * max(w_, h_):
                continue
            ys, xs = np.nonzero(lab[stt[i, 1]:stt[i, 1] + h_, stt[i, 0]:stt[i, 0] + w_] == i)
            (cx, cy), r = cv2.minEnclosingCircle(np.c_[xs + stt[i, 0], ys + stt[i, 1]].astype(np.float32))
            if rmin <= r <= rmax:
                found.append((float(cx), float(cy), float(r)))
        return found

    strict = (g < DARK_MAX) & (st > DARK_MAX + 20)
    out = discs(strict)
    loose = (g < DARK_MAX) & (strict | (g < st.astype(np.float32) - VOID_DARKER))
    for c in discs(loose):
        if all(math.hypot(c[0] - o[0], c[1] - o[1]) > 1.0 for o in out):
            out.append(c)
    return out


class Scorer:
    """The lift over the static for one frame, with integral images for box sums."""

    def __init__(self, g: np.ndarray, st: np.ndarray, slab: np.ndarray):
        self.L = g - st
        self.slab = slab
        self.h, self.w = g.shape
        self.yy, self.xx = np.mgrid[0:self.h, 0:self.w]

    def sensor(self, icon, sc) -> dict | None:
        use = self.slab & (np.hypot(self.xx - icon[0], self.yy - icon[1]) > icon[2] + 1)
        I1 = cv2.integral(np.where(use, self.L, 0).astype(np.float64))
        I0 = cv2.integral(use.astype(np.float64))
        w, h = self.w, self.h

        def box(I, x0, y0, x1, y1):
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            return 0.0 if x1 <= x0 or y1 <= y0 else I[y1, x1] - I[y0, x1] - I[y1, x0] + I[y0, x0]

        b = max(2, int(round(SQ_BAND * sc)))
        best = None
        for d in DIRS:
            for e in np.arange(DET_SQ_E[0] * sc, DET_SQ_E[1] * sc + 1e-6, 1.0):
                for lat in (-1.0, 0.0, 1.0):
                    x0, y0, x1, y1 = square_rect(icon, d, DET_SQ_W * sc, DET_SQ_H * sc, e, lat)
                    n_in = box(I0, x0, y0, x1, y1)
                    n_out = box(I0, x0 - b, y0 - b, x1 + b, y1 + b) - n_in
                    if n_in < 0.4 * (x1 - x0) * (y1 - y0) or n_out < 4 * b:
                        continue
                    m_in = box(I1, x0, y0, x1, y1) / n_in
                    m_out = (box(I1, x0 - b, y0 - b, x1 + b, y1 + b) - box(I1, x0, y0, x1, y1)) / n_out
                    if best is None or m_in - m_out > best["score"]:
                        best = {"score": m_in - m_out, "lift_in": m_in, "dir": d, "rect": [x0, y0, x1, y1]}
        return best

    def trademark(self, icon, sc) -> dict:
        """The best rim over DET_TM_R_RANGE (the circle's widget radius follows the map's zoom),
        and the interior's lift over the band outside it at that radius. The rim contrast is the
        median over TM_SECTORS angular sectors of each sector's own contrast, so a cone lighting
        one side of the circle (9acf 1047 s) does not sink the whole rim."""
        d = np.hypot(self.xx - icon[0], self.yy - icon[1])
        sec = ((np.arctan2(self.yy - icon[1], self.xx - icon[0]) + math.pi)
               / (2 * math.pi) * TM_SECTORS).astype(int) % TM_SECTORS
        L = self.L
        best = {"rim": -99.0, "inside": -99.0, "r": None}
        for r in np.arange(DET_TM_R_RANGE[0] * sc, DET_TM_R_RANGE[1] * sc + 1e-6, 0.5):
            rim = np.abs(d - r) <= 0.8
            near_in = (d >= r - 3.5) & (d <= r - 2)
            near_out = (d >= r + 2) & (d <= r + 3.5)
            vs = []
            for k in range(TM_SECTORS):
                a, b_, c_ = rim & (sec == k), near_in & (sec == k), near_out & (sec == k)
                if a.any() and b_.any() and c_.any():
                    vs.append(float(np.median(L[a]) - max(np.median(L[b_]), np.median(L[c_]))))
            if len(vs) < TM_SECTORS // 2:
                continue
            v = float(np.median(vs))
            if v > best["rim"]:
                best = {"rim": v, "r": float(r)}
        if best["r"] is None:
            return {"rim": -99.0, "inside": -99.0, "r": None}
        r = best["r"]
        inside = (d > icon[2] + 2) & (d < r - 3) & self.slab
        band = (d > r + 4) & (d < r + 4 + 5 * sc) & self.slab
        best["inside"] = (float(np.median(L[inside]) - np.median(L[band]))
                          if inside.any() and band.any() else -99.0)
        return best


#: The glyph must correlate this well with a mined template of the same ability (masked Pearson
#: over the disc, best of +-2 px); set before any detection was scored.
DET_GLYPH_MIN = 0.6
#: The square's interior must read as the measured tint (alpha 0.16-0.18 on the named instances).
DET_SQ_ALPHA = (0.10, 0.26)


def load_glyph_templates() -> list[dict]:
    tdir = OUT / "templates"
    out = []
    for t in json.loads((tdir / "index.json").read_text(encoding="utf-8")):
        t["img"] = cv2.imread(str(tdir / t["file"]), cv2.IMREAD_GRAYSCALE).astype(np.float32)
        out.append(t)
    return out


def glyph_score(g: np.ndarray, icon: tuple, sc: float, tpls: list[dict], shift: bool = False):
    """The best masked correlation of the frame round `icon` with any of `tpls`, each resized from
    its own scale to this frame's; with `shift`, also the (dx, dy) of that best match, which
    recentres the icon on its glyph (a template is cut round the measured icon centre)."""
    best, bdx, bdy = -1.0, 0, 0
    for t in tpls:
        img = t["img"]
        k = sc / t["scale"]
        if abs(k - 1) > 0.02:
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_LINEAR)
        n = img.shape[0]
        R = n // 2
        yy, xx = np.mgrid[0:n, 0:n]
        disc = np.hypot(xx - R, yy - R) <= R
        tv = img[disc] - img[disc].mean()
        tn = np.sqrt((tv * tv).sum()) + 1e-6
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                x0, y0 = int(round(icon[0])) - R + dx, int(round(icon[1])) - R + dy
                if x0 < 0 or y0 < 0 or x0 + n > g.shape[1] or y0 + n > g.shape[0]:
                    continue
                p = g[y0:y0 + n, x0:x0 + n][disc]
                pv = p - p.mean()
                v = float((pv * tv).sum() / (np.sqrt((pv * pv).sum()) * tn + 1e-6))
                if v > best:
                    best, bdx, bdy = v, dx, dy
    return (best, bdx, bdy) if shift else best


def detect_frame(g: np.ndarray, st: np.ndarray, slab: np.ndarray, sc: float, tpls: list[dict],
                 exclude_session: str | None = None, keep_scores: list | None = None) -> list[dict]:
    """Every sensor square and Trademark circle found on one minimap frame: an icon-sized dark
    disc whose glyph matches the ability's mined template, with the ability's drawn area round it.
    Templates mined from `exclude_session` are not used (scoring a session on its own glyphs)."""
    sco = Scorer(g, st, slab)
    by = {ab: [t for t in tpls if t["ability"] == ab and t["session"] != exclude_session]
          for ab in (SENSOR, TRADEMARK)}
    out = []
    for icon0 in icon_candidates(g, st, sc):
        gsh = {ab: glyph_score(g, icon0, sc, by[ab], shift=True) if by[ab] else (-1.0, 0, 0) for ab in by}
        gs = {ab: v[0] for ab, v in gsh.items()}
        if keep_scores is not None:
            keep_scores.append({"x": round(icon0[0], 1), "y": round(icon0[1], 1),
                                **{f"glyph_{k}": round(v, 3) for k, v in gs.items()}})
        if gs[TRADEMARK] >= DET_GLYPH_MIN:
            # the rim is sought round the candidate's own centre and round the centre its glyph
            # match gives (a template is cut round a measured icon centre); the better rim wins
            _, dx, dy = gsh[TRADEMARK]
            tm, icon = max(((sco.trademark(c, sc), c) for c in
                            {icon0, (round(icon0[0]) + dx, round(icon0[1]) + dy, icon0[2])}),
                           key=lambda x: x[0]["rim"])
            if tm["rim"] >= DET_RIM_MIN and tm["inside"] >= DET_TM_IN_MIN:
                out.append({"ability": TRADEMARK, "x": round(icon[0], 1), "y": round(icon[1], 1),
                            "glyph": round(gs[TRADEMARK], 3), "rim": round(tm["rim"], 1),
                            "inside": round(tm["inside"], 1), "r_scale1": round(tm["r"] / sc, 1)})
                continue
        if gs[SENSOR] >= DET_GLYPH_MIN:
            icon = icon0
            sq = sco.sensor(icon, sc)
            if sq and sq["score"] >= DET_SQ_MIN:
                x0, y0, x1, y1 = [max(0, v) for v in sq["rect"]]
                m = np.zeros(g.shape, bool)
                m[y0:y1, x0:x1] = True
                m &= slab & (np.hypot(sco.xx - icon[0], sco.yy - icon[1]) > icon[2] + 1)
                alpha = float(np.median(sco.L[m] / np.maximum(1.0, 255.0 - st[m]))) if m.any() else -1.0
                if DET_SQ_ALPHA[0] <= alpha <= DET_SQ_ALPHA[1]:
                    out.append({"ability": SENSOR, "x": round(icon[0], 1), "y": round(icon[1], 1),
                                "glyph": round(gs[SENSOR], 3), "score": round(float(sq["score"]), 1),
                                "alpha": round(alpha, 3), "dir": sq["dir"], "rect": sq["rect"]})
    # the two candidate passes can find one icon twice: keep the best glyph per icon and ability
    rmax = 1.35 * max(ICON_R_BY.values()) * sc
    keep = []
    for d in sorted(out, key=lambda d: -d["glyph"]):
        if all(k["ability"] != d["ability"] or math.hypot(k["x"] - d["x"], k["y"] - d["y"]) > rmax
               for k in keep):
            keep.append(d)
    return keep


def cmd_detect(a) -> int:
    below_normal()
    OUT.mkdir(parents=True, exist_ok=True)
    meas = json.loads((OUT / "measure.json").read_text(encoding="utf-8"))["instances"]
    tpls = load_glyph_templates()
    pos, neg, cand_pos, cand_neg = [], [], [], []
    # positives: ten frames spread over each measured run, the instance's icon as truth
    for r in meas:
        if "duration" not in r:
            continue
        s = sess(r["session"])
        sc, st, slab = scale_of(s.static), gray(s.static), s.slab.astype(bool)
        d = r["duration"]
        times = sorted({s.snap(t * 1000) for t in np.linspace(d["start_s"], d["end_s"], 10)})
        for tt, c in s.crops(times):
            dets = detect_frame(gray(c), st, slab, sc, tpls, exclude_session=r["session"], keep_scores=cand_pos)
            hit = [x for x in dets if x["ability"] == r["ability"]
                   and math.hypot(x["x"] - r["icon"]["cx"], x["y"] - r["icon"]["cy"]) <= 4 * sc]
            wrong = [x for x in dets if x["ability"] != r["ability"]
                     and math.hypot(x["x"] - r["icon"]["cx"], x["y"] - r["icon"]["cy"]) <= 4 * sc]
            pos.append({"ability": r["ability"], "session": r["session"], "t_s": round(tt / 1000, 3),
                        "truth": [r["icon"]["cx"], r["icon"]["cy"]], "found": bool(hit),
                        "wrong_ability": bool(wrong), "other_detections": len(dets) - len(hit) - len(wrong)})
    # negatives: frames spread over whole sessions with no Deadlock and no Chamber
    for sid in NEGATIVE_SESSIONS:
        try:
            s = sess(sid)
        except SystemExit as e:
            neg.append({"session": sid, "skipped": str(e)})
            continue
        sc, st, slab = scale_of(s.static), gray(s.static), s.slab.astype(bool)
        idx = np.linspace(0, len(s.cache_t) - 1, NEG_FRAMES).astype(int)
        for tt, c in s.crops(s.cache_t[idx]):
            dets = detect_frame(gray(c), st, slab, sc, tpls, keep_scores=cand_neg)
            neg.append({"session": sid, "t_s": round(tt / 1000, 3), "detections": dets})
    summ = {}
    for ab in (SENSOR, TRADEMARK):
        p = [x for x in pos if x["ability"] == ab]
        summ[ab] = {"positive_frames": len(p), "found": sum(x["found"] for x in p),
                    "recall": round(sum(x["found"] for x in p) / max(1, len(p)), 3),
                    "wrong_ability": sum(x["wrong_ability"] for x in p),
                    "false_on_negatives": sum(1 for x in neg for dd in x.get("detections", []) if dd["ability"] == ab)}
    summ["negative_frames"] = sum(1 for x in neg if "detections" in x)
    # the glyph channel alone: how many negative-session icon candidates pass it, per ability
    for ab in (SENSOR, TRADEMARK):
        vals = [c[f"glyph_{ab}"] for c in cand_neg]
        summ[ab]["neg_candidates"] = len(vals)
        summ[ab]["neg_candidates_glyph_pass"] = sum(v >= DET_GLYPH_MIN for v in vals)
        summ[ab]["neg_glyph_max"] = round(max(vals), 3) if vals else None
    print(json.dumps(summ, indent=1))
    for x in neg:
        if x.get("detections"):
            print("FP", x["session"], x["t_s"], x["detections"])
    for x in pos:
        if not x["found"]:
            print("MISS", x)
    (OUT / "detect.json").write_text(json.dumps({"version": VERSION, "summary": summ, "positives": pos,
                                                 "negatives": neg}, indent=1), encoding="utf-8")
    if a.record:
        from reticle import metrics
        deps = {"version": VERSION, "sq": [DET_SQ_W, DET_SQ_H, DET_SQ_E], "tm_r": DET_TM_R,
                "sq_min": DET_SQ_MIN, "sq_max_in": DET_SQ_MAX_IN, "rim_min": DET_RIM_MIN,
                "tm_in_min": DET_TM_IN_MIN, "dark_max": DARK_MAX, "icon_r": ICON_R_BY}
        for ab in (SENSOR, TRADEMARK):
            metrics.record(SERIES, part=f"detect_{ab}", session="named-instances", values=summ[ab], deps=deps,
                           context={"negative_sessions": list(NEGATIVE_SESSIONS), "neg_frames": NEG_FRAMES,
                                    "negative_frames": summ["negative_frames"]},
                           note="positives: 10 frames over each measured run; negatives: sessions with no "
                                "Deadlock and no Chamber in the stored lineup")
    return 0


#: Sessions where stored data or the player place a Chamber: the ally slot by the stored lineup
#: (223d636bf8d2 named, 043bafca271a and 9acf02f98283 best guess) or the player's Trademark
#: (bfad2778a372, e37fdeca944f, whose stored lineups put Chamber on the rival side or nowhere).
CHAMBER_SESSIONS = ("223d636bf8d2", "043bafca271a", "9acf02f98283", "bfad2778a372", "e37fdeca944f")
RDV_FRAMES = 80
#: Rim radii searched round each icon candidate, px at scale 1.0.
RDV_R = (12, 64)


def ring_scan(sco: "Scorer", icon: tuple, sc: float) -> list[tuple[float, float]]:
    """(radius, rim lift over the rings either side) for every radius in RDV_R where a drawn rim
    circles the icon."""
    d = np.hypot(sco.xx - icon[0], sco.yy - icon[1])
    out = []
    for r in np.arange(RDV_R[0] * sc, RDV_R[1] * sc, 1.0):
        rim = np.abs(d - r) <= 0.8
        a_in = (d >= r - 3.5) & (d <= r - 2)
        a_out = (d >= r + 2) & (d <= r + 3.5)
        if rim.sum() < 20:
            continue
        v = float(np.median(sco.L[rim]) - max(np.median(sco.L[a_in]), np.median(sco.L[a_out])))
        if v >= DET_RIM_MIN:
            out.append((round(float(r / sc), 1), round(v, 1)))
    return out


def cmd_rendezvous(a) -> int:
    """Search the Chamber sessions for a drawn circle round any dark icon other than a Trademark."""
    below_normal()
    tpls = load_glyph_templates()
    found, n_frames = [], 0
    for sid in CHAMBER_SESSIONS:
        try:
            s = sess(sid)
        except SystemExit as e:
            print(sid, "skipped", e)
            continue
        sc, st, slab = scale_of(s.static), gray(s.static), s.slab.astype(bool)
        idx = np.linspace(0, len(s.cache_t) - 1, RDV_FRAMES).astype(int)
        for tt, c in s.crops(s.cache_t[idx]):
            n_frames += 1
            g = gray(c)
            sco = Scorer(g, st, slab)
            for icon in icon_candidates(g, st, sc):
                rings = ring_scan(sco, icon, sc)
                if not rings:
                    continue
                gt = glyph_score(g, icon, sc, [t for t in tpls if t["ability"] == TRADEMARK])
                is_tm = gt >= DET_GLYPH_MIN and any(DET_TM_R_RANGE[0] <= x[0] <= DET_TM_R_RANGE[1] for x in rings)
                found.append({"session": sid, "t_s": round(tt / 1000, 3), "x": round(icon[0], 1),
                              "y": round(icon[1], 1), "rings": rings, "glyph_trademark": round(gt, 3),
                              "trademark": is_tm})
    n_tm = sum(f["trademark"] for f in found)
    print(json.dumps({"frames": n_frames, "trademark_rings": n_tm, "other_rings": len(found) - n_tm}))
    for f in found:
        print(f)
    (OUT / "rendezvous.json").write_text(json.dumps({"version": VERSION, "frames": n_frames, "found": found}, indent=1),
                                         encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump")
    p.add_argument("sid")
    p.add_argument("t", type=float)
    p.add_argument("--offsets", default="-20,-5,-1,0,1,5,20")
    p.add_argument("--zoom", type=int, default=2)
    p = sub.add_parser("measure")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("detect")
    p.add_argument("--record", action="store_true")
    sub.add_parser("rendezvous")
    a = ap.parse_args(argv)
    return {"dump": cmd_dump, "measure": cmd_measure, "detect": cmd_detect,
            "rendezvous": cmd_rendezvous}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
