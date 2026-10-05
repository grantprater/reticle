r"""The dead Clove's smoke-range circle on the minimap, read in her death windows.

Owns [owns:clove-circle].

While a dead Clove places a Ruse smoke, her team's minimaps draw a large
circle centred on her death location
[domain:abilities/clove-dead-smoke-range-circle]; no living Clove and no other
agent draws one [domain:abilities/clove-smokes-after-death]. This reader looks
for that circle and stores what it saw. It names no agent and decides no
cast: `adjudication.smoke_owner` takes a present circle as evidence that a
disc born beside it is Clove's, and `ability_timeline.dead_ruse_casts` counts
the player's dead casts from those discs.

The gate is the opportunity, never the outcome. A window opens at each
stored ally-side death verdict whose victim is Clove (the death owner's
verdict, taken as a gate) and runs to her round's end, her stored revive, or
her next death, whichever comes first (`opportunity_windows`). The reader
reads nothing outside the windows, so a session with no ally Clove costs
nothing. A window carries a seed where a stored position gives the death
location: for the player's own death, the stored self track's last position
before it (`stored_windows`). A window with no seed searches the whole widget
until it finds a circle and then continues that circle's centre, which is
fixed at the death location; both paths are stored per row (`searched`).

The fit. The circle is a thin bright rim over the static-subtracted grey
(the baked static [domain:capture/session-pixels-are-not-the-map]; the
widget is semi-transparent [domain:minimap/transparency], so the rim is a
brightness step, not a colour). The centre search is a ring matched filter:
the inner rim band's mean minus the outer band's, correlated at every centre
by `cv2.filter2D` on the grey shrunk with `INTER_AREA`, one kernel per radius
in a window round the fact's radius. The best centre and radius seed a shape
fit at full size: on 360 rays (`cv2.remap`, linear) the steepest outward drop
near the radius is the rim, and a least-squares circle with residual
rejection fits those points (`fit_rim`, after `prototypes/clove_circle.py`).
The score is the median over rays of the rim contrast at the fitted circle,
soft; `present` cuts it once, at `PRESENT_MIN`. A frame whose rim fit is no
circle (rms above `RIM_RMS_MAX`), whose rim lies mostly outside the widget,
or whose fit leaves the radius window is unread, with that reason.

Sizes are base px at `geometry.SCALE_REF_KEY`, turned into widget px by the
key's `geometry.MapScale`. The radius comes from the fact's
`values.base_radius` for the session's map where it has one, else from the
fact's Lotus measurement, and the radius window is the search range of the
fit, not an acceptance band: each row stores the radius it fitted.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .geometry import MapScale
from .usage import step as usage_step
from .version import CLOVE_CIRCLE_VERSION

#: The domain fact whose values give the circle's radius.
CIRCLE_FACT = "abilities/clove-dead-smoke-range-circle"
#: The map whose measured radius stands in where the session's map has none.
FALLBACK_MAP = "lotus"
#: The search range of the fit, as a share of the expected radius, where the
#: radius stands in from another map: the radii of one world size differ by
#: several percent between maps after the transform (Lotus 140.87 against
#: Sunset 152.06 base px here).
RADIUS_WINDOW = (0.85, 1.15)
#: The search range where the fact measures the session's own map: the
#: measured radius is constant to a fraction of a pixel while drawn.
RADIUS_WINDOW_MEASURED = (0.96, 1.04)
#: Base px between two searched radii; the rim bands are wider than this, so
#: a circle between two radii still scores on both.
RADIUS_STEP_BASE = 3.0
#: The rim bands in base px from the radius, inside and outside: the
#: prototype's (-3, -1) and (+2, +4) baked px on Lotus over Lotus's scale.
RIM_IN_BASE = (-4.7, -1.6)
RIM_OUT_BASE = (3.1, 6.3)
#: The rim search on each ray, in base px either side of the radius.
EDGE_WIN_BASE = 9.0
#: The shrink of the grey for the centre search (`INTER_AREA`).
SEARCH_SHRINK = 0.5
#: Base px a seeded centre search may move from its seed.
SEED_TOL_BASE = 16.0
#: The cut on the rim contrast (grey levels): the prototype's drawn test on
#: the same score, between a control maximum of 3.9 and a drawn minimum of 22.6
#: [domain:abilities/clove-dead-smoke-range-circle].
PRESENT_MIN = 10.0
#: Fewer rays than this share inside the widget leave the frame unread.
VALID_RAYS_MIN = 0.5
#: The rim fit leaves the frame unread above this rms in px: the drawn rim is
#: a crisp circle (rms at most 0.37 px on the 144 drawn dev samples of
#: a1a995e6b19b, 0.36 px median on the Lotus capture), and a fit to no circle
#: lands on scattered edges (1.72 px least on that session's absent samples).
RIM_RMS_MAX = 1.0
#: The living player's own sounds draw a pale circle round the self icon
#: [domain:minimap/self-audio-circle]. A circle centred within this many base
#: px (about one self-icon radius) of the stored self position, while the
#: player is not the dead Clove, is that circle, not hers; the stored position
#: is taken from the nearest self sample within `SELF_DT_MS`.
SELF_TOL_BASE = 12.0
SELF_DT_MS = 1000.0
#: Rays of the shape fit.
N_RAYS = 360
ANG = np.deg2rad(np.arange(0.0, 360.0, 360.0 / N_RAYS))


def fact_radius(facts: dict | None, map_name: str | None) -> tuple[float | None, str | None]:
    """(base radius, the map it was measured on) from the circle fact's
    `values.base_radius`: the session's map where measured, else
    `FALLBACK_MAP`; (None, None) where the fact gives none."""
    if facts is None:
        from .domain import load
        facts = load()
    f = facts.get(CIRCLE_FACT)
    radii = ((f.values or {}).get("base_radius") or {}) if f is not None else {}
    if map_name in radii:
        return float(radii[map_name]), map_name
    if FALLBACK_MAP in radii:
        return float(radii[FALLBACK_MAP]), FALLBACK_MAP
    return None, None


def ray_profile(img: np.ndarray, c, rs: np.ndarray, ang: np.ndarray = ANG) -> np.ndarray:
    """`img` sampled on rays from centre `c` at radii `rs` (linear; NaN
    outside), one row per ray."""
    xs = (c[0] + np.outer(np.cos(ang), rs)).astype(np.float32)
    ys = (c[1] + np.outer(np.sin(ang), rs)).astype(np.float32)
    return cv2.remap(img.astype(np.float32, copy=False), xs, ys, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=float("nan"))


def ring_score(img: np.ndarray, c, r: float, rim_in, rim_out) -> tuple[float, float]:
    """(median over rays of inner-band minus outer-band grey, share of rays
    read inside the image) at circle (c, r)."""
    v = ray_profile(img, c, np.array([r + rim_in[0], r + rim_in[1], r + rim_out[0], r + rim_out[1]]))
    s = 0.5 * (v[:, 0] + v[:, 1]) - 0.5 * (v[:, 2] + v[:, 3])
    ok = np.isfinite(s)
    if not ok.any():
        return float("nan"), 0.0
    return float(np.median(s[ok])), float(ok.mean())


def kasa_circle(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """The algebraic (Kasa) least-squares circle through points."""
    a = np.c_[2 * x, 2 * y, np.ones_like(x)]
    s = np.linalg.lstsq(a, x * x + y * y, rcond=None)[0]
    return float(s[0]), float(s[1]), float(np.sqrt(max(s[2] + s[0] ** 2 + s[1] ** 2, 0.0)))


def fit_rim(img: np.ndarray, c0, r0: float, win: float, iters: int = 3) -> dict | None:
    """The rim as a shape: on each ray the steepest outward drop within
    `win` px of the radius, then a least-squares circle with residual
    rejection, iterated with a halving window. None where too few rays read."""
    c, r = np.array(c0, float), float(r0)
    x = y = m = None
    for _ in range(iters):
        rs = np.arange(r - win, r + win, 0.25)
        v = ray_profile(img, c, rs)
        g = -(v[:, 4:] - v[:, :-4])
        fin = np.isfinite(g)
        ok = fin.all(1)
        if ok.sum() < 8:
            return None
        k = np.argmax(np.where(fin, g, -np.inf), 1)
        re, amp = rs[k + 2], g[np.arange(len(k)), k]
        x, y = c[0] + re * np.cos(ANG), c[1] + re * np.sin(ANG)
        m = ok & (amp > np.percentile(amp[ok], 30)) & (amp > 0)
        if m.sum() < 8:
            return None
        for _ in range(3):
            cx, cy, rr = kasa_circle(x[m], y[m])
            res = np.hypot(x - cx, y - cy) - rr
            keep = ok & (np.abs(res) < max(1.5, 2.5 * float(np.std(res[m])))) & (amp > 0)
            if keep.sum() < 8:
                break
            m = keep
        c, r, win = np.array([cx, cy]), rr, max(3.5, win / 2)
    res = np.hypot(x - c[0], y - c[1]) - r
    return {"cx": float(c[0]), "cy": float(c[1]), "r": float(r),
            "rms": float(np.sqrt(np.mean(res[m] ** 2))), "inliers": float(m.mean())}


class RingSearch:
    """Ring matched filters over a shrunk grey, one per searched radius."""

    def __init__(self, r_expect: float, rim_in, rim_out, step: float,
                 shrink: float = SEARCH_SHRINK, window: tuple = RADIUS_WINDOW):
        self.shrink = shrink
        lo, hi = window
        self.radii = np.arange(lo * r_expect, hi * r_expect + 1e-6, step)
        self.kernels = [self._kernel(r * shrink, [v * shrink for v in rim_in],
                                     [v * shrink for v in rim_out]) for r in self.radii]

    @staticmethod
    def _kernel(r: float, rim_in, rim_out) -> np.ndarray:
        """+1/n over the inner band, -1/n over the outer band; bands at
        least one shrunk px wide."""
        half = int(math.ceil(r + rim_out[1] + 1))
        yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
        d = np.hypot(xx, yy).astype(np.float32)
        a0, a1 = r + rim_in[0], max(r + rim_in[1], r + rim_in[0] + 1.0)
        b0, b1 = r + rim_out[0], max(r + rim_out[1], r + rim_out[0] + 1.0)
        inn = ((d >= a0) & (d <= a1)).astype(np.float32)
        out = ((d >= b0) & (d <= b1)).astype(np.float32)
        return inn / max(1.0, inn.sum()) - out / max(1.0, out.sum())

    def best(self, img: np.ndarray, near=None, tol: float | None = None) -> tuple:
        """(cx, cy, r, mean contrast) of the best ring over every centre, or
        over centres within `tol` px of `near`."""
        small = cv2.resize(img, None, fx=self.shrink, fy=self.shrink,
                           interpolation=cv2.INTER_AREA)
        h, w = small.shape
        mask = None
        if near is not None:
            yy, xx = np.mgrid[:h, :w]
            mask = np.hypot(xx - near[0] * self.shrink, yy - near[1] * self.shrink) <= tol * self.shrink
        top = (-np.inf, None, None, None)
        for r, k in zip(self.radii, self.kernels):
            resp = cv2.filter2D(small, cv2.CV_32F, k, borderType=cv2.BORDER_CONSTANT)
            if mask is not None:
                resp = np.where(mask, resp, -np.inf)
            j = int(np.argmax(resp))
            v = float(resp.flat[j])
            if v > top[0]:
                top = (v, (j % w) / self.shrink, (j // w) / self.shrink, float(r))
        return top[1], top[2], top[3], top[0]


def opportunity_windows(deaths: list[dict], rounds: list[dict], revives_ms=()) -> list[dict]:
    """One window per death, from the death to the first of its round's end,
    a revive after it, or the same victim's next death. `deaths` are
    {"t_ms", "death_id", "player_death", "seed" (optional [x, y]),
    "seed_from"}; `rounds`
    carry `t_start_ms` and `t_end_ms`. A death in no round gets no window."""
    out = []
    ds = sorted(deaths, key=lambda d: float(d["t_ms"]))
    rv = sorted(float(t) for t in revives_ms)
    for i, d in enumerate(ds):
        t = float(d["t_ms"])
        rnd = next((r for r in rounds if r.get("t_start_ms") is not None
                    and float(r["t_start_ms"]) <= t <= float(r.get("t_end_ms") or -1)), None)
        if rnd is None:
            continue
        ends = [(float(rnd["t_end_ms"]), "round_end")]
        ends += [(v, "revive") for v in rv if v > t]
        if i + 1 < len(ds) and float(ds[i + 1]["t_ms"]) > t:
            ends.append((float(ds[i + 1]["t_ms"]), "next_death"))
        t1, why = min(ends)
        out.append({"t0_ms": t, "t1_ms": t1, "end": why, "death_ms": t,
                    "death_id": d.get("death_id"), "round_no": rnd.get("round_no"),
                    "player_death": bool(d.get("player_death")),
                    "seed": d.get("seed"), "seed_from": d.get("seed_from")})
    return out


def _last_self(mt: np.ndarray, sx, sy, t: float, before_ms: float = 3000.0):
    """The self track's last position in the `before_ms` before `t`, or None."""
    j = int(np.searchsorted(mt, t, side="right")) - 1
    while j >= 0 and mt[j] >= t - before_ms:
        if sx[j] is not None and sy[j] is not None and np.isfinite(sx[j]) and np.isfinite(sy[j]):
            return [float(sx[j]), float(sy[j])]
        j -= 1
    return None


def stored_self_track(store, sid: str):
    """(t_ms, self_x, self_y) arrays of the stored minimap self track, NaN
    where unread, or None where no minimap table is stored."""
    man = store.read_manifest(sid)
    path = store.minimap_path(sid, man["ingested_at"][:10])
    if not path.is_file():
        return None
    import pyarrow.parquet as pq
    mm = pq.read_table(path, columns=["t_ms", "self_x", "self_y"])
    col = lambda c: np.asarray([np.nan if v is None else v  # noqa: E731
                                for v in mm.column(c).to_pylist()], float)
    return col("t_ms"), col("self_x"), col("self_y")


def self_position_at(track, t: float, dt_ms: float = SELF_DT_MS):
    """The self position at `t`, linear between the read samples on either
    side where both lie within `dt_ms`, else the nearer one within it; None
    where neither does."""
    if track is None or not len(track[0]):
        return None
    mt, sx, sy = track
    ok = np.isfinite(sx) & np.isfinite(sy)
    mt, sx, sy = mt[ok], sx[ok], sy[ok]
    j = int(np.searchsorted(mt, t))
    a = j - 1 if j - 1 >= 0 and t - mt[j - 1] <= dt_ms else None
    b = j if j < len(mt) and mt[j] - t <= dt_ms else None
    if a is not None and b is not None and mt[b] > mt[a]:
        w = (t - mt[a]) / (mt[b] - mt[a])
        return (float(sx[a] + w * (sx[b] - sx[a])), float(sy[a] + w * (sy[b] - sy[a])))
    k = a if b is None else b if a is None else (a if t - mt[a] <= mt[b] - t else b)
    return None if k is None else (float(sx[k]), float(sy[k]))


def stored_windows(store, sid: str) -> tuple[list[dict] | None, dict]:
    """(windows, inputs) from storage: ally-side death verdicts whose victim
    the death owner names Clove, the stored rounds, the stored revives of a
    Clove, and for the player's own deaths the stored self track's last
    position as the seed. (None, inputs with a reason) where no death stream
    or round table is stored."""
    man = store.read_manifest(sid)
    date = man["ingested_at"][:10]
    rows = store.read_events("death", sid)
    head = next((r for r in rows if r.get("kind") == "summary"), {})
    inputs = {"death": head.get("death_adjudication_version"), "reason": None}
    if not rows:
        return None, {**inputs, "reason": "no_death_stream"}
    tbl = store.read_rounds(sid, date)
    if tbl is None:
        return None, {**inputs, "reason": "no_rounds"}
    rounds = tbl.to_pylist()
    verdicts = [r for r in rows if r.get("kind") == "death_verdict" and r.get("t_ms") is not None
                and r.get("side") == "ally" and r.get("victim") == "Clove"]
    deaths = [r for r in verdicts if not r.get("is_revive")]
    revives = [float(r["t_ms"]) for r in verdicts if r.get("is_revive")]
    track = stored_self_track(store, sid) if deaths else None
    ds = []
    for r in deaths:
        mine = bool(r.get("kf_player_death"))
        seed = _last_self(*track, float(r["t_ms"])) if (track is not None and mine) else None
        ds.append({"t_ms": float(r["t_ms"]), "death_id": r.get("death_id"), "seed": seed,
                   "seed_from": "self_track" if seed else None, "player_death": mine})
    inputs["clove_deaths"] = len(deaths)
    inputs["clove_revives"] = len(revives)
    return opportunity_windows(ds, rounds, revives), inputs


class CloveCircleReader:
    """`passes.Reader` writing the `clove_circle` stream: per sample inside
    an opportunity window, the best circle the fit finds and its score."""

    cache_resample = True
    records_clip = True

    def __init__(self, sgray, floor, box, windows: list[dict], ms: MapScale | None,
                 r_base: float | None, r_from: str | None, hz: float = 4.0,
                 name: str = "clove_circle", window_inputs: dict | None = None,
                 map_name: str | None = None, self_track=None):
        self.name, self.hz = name, hz
        self.windows = windows
        self.spans = [(w["t0_ms"], w["t1_ms"]) for w in windows]
        self.frames_from = "video"
        self.cv_threads = 1
        self.sgray = np.asarray(sgray, np.float32)
        self.floor, self.box, self.ms = floor, box, ms
        self.r_base, self.r_from, self.map_name = r_base, r_from, map_name
        self.window_inputs = window_inputs or {}
        self.self_track = self_track
        self.rows: list[dict] = []
        self._search: RingSearch | None = None
        self._found: dict[int, tuple] = {}
        if ms is not None and r_base is not None:
            self.r_expect = ms.px(r_base)
            self.rim_in = tuple(ms.px(v) for v in RIM_IN_BASE)
            self.rim_out = tuple(ms.px(v) for v in RIM_OUT_BASE)
            self.edge_win = ms.px(EDGE_WIN_BASE)
            self.seed_tol = ms.px(SEED_TOL_BASE)
            self.step = ms.px(RADIUS_STEP_BASE)
            self.self_tol = ms.px(SELF_TOL_BASE)

    def _window_of(self, t: float) -> int | None:
        for i, w in enumerate(self.windows):
            if w["t0_ms"] <= t <= w["t1_ms"]:
                return i
        return None

    @property
    def radius_window(self) -> tuple[float, float]:
        """`RADIUS_WINDOW_MEASURED` where the fact measures this map,
        `RADIUS_WINDOW` where its radius stands in from another map."""
        return RADIUS_WINDOW_MEASURED if self.r_from == self.map_name else RADIUS_WINDOW

    def search(self) -> RingSearch:
        if self._search is None:
            self._search = RingSearch(self.r_expect, self.rim_in, self.rim_out, self.step,
                                      window=self.radius_window)
        return self._search

    def _fit(self, d: np.ndarray, near) -> dict:
        """The best ring near `near` (or anywhere), its shape fit, the soft
        score and its one cut."""
        with usage_step("search"):
            cx, cy, r, mean = self.search().best(d, near, self.seed_tol)
        if cx is None:
            return {"present": False, "score": None, "reason": "no_candidate"}
        with usage_step("fit"):
            fit = fit_rim(d, (cx, cy), r, self.edge_win)
        if fit is None:
            fit = {"cx": cx, "cy": cy, "r": r, "rms": None, "inliers": None}
        score, valid = ring_score(d, (fit["cx"], fit["cy"]), fit["r"], self.rim_in, self.rim_out)
        lo, hi = self.radius_window
        reason = None
        if fit["rms"] is None or fit["rms"] > RIM_RMS_MAX:
            reason = "no_rim_fit"
        elif valid < VALID_RAYS_MIN:
            reason = "rim_outside_widget"
        elif not lo * self.r_expect <= fit["r"] <= hi * self.r_expect:
            reason = "fit_left_radius_window"
        present = bool(reason is None and np.isfinite(score) and score >= PRESENT_MIN)
        return {"search_contrast": round(mean, 3),
                "cx": round(fit["cx"], 2), "cy": round(fit["cy"], 2), "r": round(fit["r"], 2),
                "rms": None if fit["rms"] is None else round(fit["rms"], 3),
                "inliers": None if fit["inliers"] is None else round(fit["inliers"], 3),
                "score": None if not np.isfinite(score) else round(score, 3),
                "valid_rays": round(valid, 3), "present": present, "reason": reason}

    def read(self, crop: np.ndarray, window: dict | None, prior=None) -> dict:
        """The circle on one widget crop. A window's circle is centred on one
        death location, so a found centre is continued; where the circle is
        not there, the whole widget is searched, since a first find may have
        been wrong. `searched` says which answered."""
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        d = cv2.GaussianBlur(g - self.sgray, (0, 0), 0.7)
        got, searched = None, "full"
        if prior is not None:
            got, searched = self._fit(d, prior), "continued"
            if not got["present"]:
                got, searched = None, "full_after_continued"
        if got is None:
            got = self._fit(d, None)
        seed = None if window is None else window.get("seed")
        off = (None if seed is None or got.get("cx") is None
               else round(float(math.hypot(got["cx"] - seed[0], got["cy"] - seed[1])), 2))
        return {"searched": searched, **got, "seed_offset": off}

    def feed(self, smp) -> None:
        from .minimap import widget_drawn
        t = float(smp.t_ms)
        wi = self._window_of(t)
        row = {"kind": "frame", "frame_idx": int(smp.frame_idx), "t_ms": t, "window": wi}
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        reason = None
        if wi is None:
            reason = "outside_windows"
        elif self.ms is None:
            reason = "no_map_scale"
        elif self.r_base is None:
            reason = "no_radius_fact"
        elif crop.shape[:2] != self.sgray.shape[:2]:
            reason = "geometry_size_mismatch"
        else:
            with usage_step("widget"):
                if not widget_drawn(crop, self.sgray, self.floor):
                    reason = "widget_not_drawn"
        if reason is not None:
            self.rows.append({**row, "present": None, "score": None, "reason": reason})
            return
        got = self.read(crop, self.windows[wi], self._found.get(wi))
        if got["present"] and not self.windows[wi].get("player_death"):
            # Cross-reference the self channel: a circle round the living
            # player's own icon is the self audio circle.
            me = self_position_at(self.self_track, t)
            if me is not None and math.hypot(got["cx"] - me[0], got["cy"] - me[1]) <= self.self_tol:
                got = {**got, "present": False, "reason": "concentric_with_self",
                       "self_offset": round(math.hypot(got["cx"] - me[0], got["cy"] - me[1]), 2)}
        if got["present"]:
            # The circle's centre is the death location: later samples of
            # the window continue it.
            self._found[wi] = (got["cx"], got["cy"])
        self.rows.append({**row, **got})

    def events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = {"session_id": session_id, "source": "minimap", "geometry_key": geometry_key,
                  "clove_circle_version": CLOVE_CIRCLE_VERSION}
        by: dict = {}
        for r in self.rows:
            k = r["reason"] or ("present" if r["present"] else "absent")
            by[k] = by.get(k, 0) + 1
        head = {**common, "kind": "coverage", "hz": self.hz, "frames": len(self.rows),
                "frames_from": self.frames_from, "by_reason": by,
                "present": sum(bool(r.get("present")) for r in self.rows),
                "windows": self.windows,
                # The stored death stream the windows came from; the counts
                # and any refusal of the window source stand apart.
                "inputs": {k: v for k, v in self.window_inputs.items() if k == "death"},
                "window_source": {k: v for k, v in self.window_inputs.items() if k != "death"},
                "fact": CIRCLE_FACT, "radius_base": self.r_base, "radius_from": self.r_from,
                "radius_window": list(self.radius_window), "present_min": PRESENT_MIN,
                "rim_rms_max": RIM_RMS_MAX, "self_tol_base": SELF_TOL_BASE,
                "self_track": self.self_track is not None,
                "rim_in_base": list(RIM_IN_BASE), "rim_out_base": list(RIM_OUT_BASE),
                "search_shrink": SEARCH_SHRINK, "seed_tol_base": SEED_TOL_BASE,
                "map_scale": None if self.ms is None else self.ms.provenance()}
        clip = getattr(self, "spans_clip", None)
        if clip is not None:
            head["spans_clip"] = clip
        return [head] + [{**common, **r} for r in self.rows]


def circle_reader(ctx, windows: list[dict], window_inputs: dict | None = None, hz: float = 4.0,
                  floor=None, sgray=None, self_track=False) -> CloveCircleReader:
    """The `CloveCircleReader` `scan` builds for a session: the baked
    static's grey, the key's transform and the fact's radius, over the
    profile's minimap ROI, reading only `windows`, with the stored self track
    as the audio circle's cross-reference (`self_track`, default from storage)."""
    from . import geometry
    from .minimap import minimap_roi_px
    ms = geometry.map_scale_of(ctx.session_id, ctx.store.root)
    key = geometry.key_of(ctx.session_id, ctx.store.root)
    map_name = key.split("__")[0] if key else None
    r_base, r_from = fact_radius(None, map_name)
    r = CloveCircleReader(sgray=ctx.sgray() if sgray is None else sgray,
                          floor=ctx.floor() if floor is None else floor,
                          box=minimap_roi_px(ctx.profile, *ctx.wh), windows=windows, ms=ms,
                          r_base=r_base, r_from=r_from, hz=hz, window_inputs=window_inputs,
                          map_name=map_name,
                          self_track=(stored_self_track(ctx.store, ctx.session_id)
                                      if self_track is False else self_track))
    r.geometry_key = key
    return r
