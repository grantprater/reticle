r"""Dark ability icons on the minimap: proposals and their pointwise verify.

    .\.venv\Scripts\python.exe -m reticle scan <session> --only ability

Owns [owns:ability-icon].

Why. A thrown or sent ability draws a round dark disc on the minimap
[domain:abilities/minimap-thrown-ability-icon]; the generic disc detectors
found few of the player's labelled icons at 331 px
(`docs/ABILITY_DETECTION.md`, section 3). This module ports the dark-icon
proposer of `prototypes/ability_shape_fast.py` (`icon_candidates_fast`,
`icon_verify`) and the reader that rides the ability pass.

The proposer (`icon-proposer-0.3.0`). For each radius from ICON_R_BASE[0]
to ICON_R_BASE[1] in RADIUS_STEP px, it scores the dark share (HSV value
under ICON_DARK_V) of a disc minus the dark share of a band ICON_GAP outside
it. Every length is a base value times the key's `geometry.map_scale`
(`ability_shapes`' scale section); RADIUS_STEP is the search's pixel grid and
stays 1 px.
Darkness counts only on the baked slab (`minimap.slab_mask` of the
geometry's reference static) and each share is taken over slab pixels, so
the map's void holes and the world behind the widget stop reading as dark
discs. A centre whose disc or band holds too little slab (ICON_FLOOR_MIN) is
not scored. Peaks at or above ICON_MIN, suppressed where two discs overlap,
are the candidates. Each carries its rim colour (teal, red) and its white
glyph share, which later stages read as side and kind evidence. It names no
ability, caster or side.

On the player's labels at radius step 1 it hit
[metric:ability_shape_fast/icons@player-labels#hit_step1=123] of
[metric:ability_shape_fast/icons@player-labels#targets=151] icons with
[metric:ability_shape_fast/icons@player-labels#null_per_crop_step1=5.8]
candidates per null crop (`tools/ability_icon_benchmark.py` reruns it on
this module).

The verify. Each candidate of the previous sample is rescored at centres
within VERIFY_HALF_BASE, at its own radius and the two beside it. A verify
whose best score falls under ICON_MIN stores `score` None: the icon is lost,
a stored surprise. The reader runs the full search on every live 2 Hz
sample as well, so the verify rows let the tracked schedule be replayed from
storage and audited against the full search (section 4, audits) with no
second pass.

The disabled drawing (`icon-proposer-0.4.0`). A deployed device whose owner
dies stays drawn, dimmer (player, 2026-10-09)
[domain:minimap/device-dim-on-deactivation]; the game files give the one
dimming they hold as an opacity, 0.5
[domain:game_data/stealthing-trap-disabled-minimap-opacity]. A dim disc is
mid-grey on grey floor, so the dark-share verify loses it
[domain:minimap/dim-devices-defeat-the-residual]. Where a tracked disc's
live verify fails, `verify_disabled` rescores its place as its own last
live drawing composited over the baked map at that opacity: per pixel of
the disc, the drawing's departure from the base map, I - B, is a(L - B) + c
for the last live luma L, with a one of three hypotheses, live (1),
disabled (`DISABLED_OPACITY`) or gone (0), and c a free offset for the
map's lighting. Each hypothesis's residual under the free fit's noise gives
a posterior; `disabled_dim` is the disabled one's, a soft score cut once,
at `DISABLED_DIM_MIN`, where the verify decides continuation
(`verified_continuations`). A disc held this way joins the sample's
candidates with `state` "disabled", so the next sample verifies it again,
against the same last live drawing. The base map is the geometry's baked
static [domain:capture/session-pixels-are-not-the-map]; the last live
drawing is the same object's own pixels one fix earlier, never a mined
template. A device first seen dim has no live drawing and is not read.

Not for. Teal rings and beams (`ability_shapes`, `ability_scan`); smokes
(`minimap_dark`); tracks, kinds and names (`adjudication.ability`, the
arbiter).
"""
from __future__ import annotations

import cv2
import numpy as np

from .ability_scan import LIVE_PHASES, _rounded
from .ability_shapes import SET_AT, _b
from .geometry import MapScale
from .usage import step as usage_step
from .version import ABILITY_ICON_VERSION

#: Icon radii, base values set at 0.025-0.075 of the 331 px crop's half width
#: (165.5 px); the range spans thrown icons and team smokes' grey discs.
ICON_R_BASE = (_b(0.025 * 165.5), _b(0.075 * 165.5))
#: The band's gap outside the disc and its least width (set at 1.5 and 3 px;
#: it is otherwise 0.4 r), the rim colour band (r - 1 to r + 2.5 px), and the
#: kernel's reach past r (5 px).
ICON_GAP, ICON_BAND_MIN = _b(1.5), _b(3.0)
ICON_RIM = (_b(1.0), _b(2.5))
ICON_REACH = _b(5.0)
#: HSV value under which a pixel is dark.
ICON_DARK_V = 75
#: The disc's dark share minus the band's that a candidate needs.
ICON_MIN = 0.35
#: Slab share a disc, and its outer band, must have to be scored.
ICON_FLOOR_MIN = (0.5, 0.3)
#: Radii read at this step in px (the stage-3 plan: 1 px).
RADIUS_STEP = 1.0
#: The verify's centre search half-width (set at 2 px), rounded to px.
VERIFY_HALF_BASE = _b(2.0)
#: At most this many candidates are stored per sample, best first.
MAX_CANDIDATES = 40
#: Two discs whose centres lie closer than this share of their radii's sum
#: are one disc: the full search suppresses the weaker, and a verified disc
#: binds to the candidate it overlaps (`verified_continuations`).
OVERLAP = 0.8
#: The disabled drawing's opacity, the game files' one value
#: [domain:game_data/stealthing-trap-disabled-minimap-opacity].
DISABLED_OPACITY = 0.5
#: The hypotheses `verify_disabled` weighs, as opacities of the last live
#: drawing: live, disabled, gone.
DIM_HYPOTHESES = (1.0, DISABLED_OPACITY, 0.0)
#: The one cut on `disabled_dim`: the disabled hypothesis holds the majority
#: of the posterior.
DISABLED_DIM_MIN = 0.5
#: The least residual noise (grey levels) the posterior assumes: the
#: capture's 8-bit quantisation, so a perfect fit never divides by zero.
DIM_NOISE_MIN = 1.0


class IconTerms:
    """Per radius: the disc and band kernels and the slab terms. They depend
    on the baked slab alone, so a session builds them once."""

    def __init__(self, slab: np.ndarray, ms: MapScale = SET_AT, step: float = RADIUS_STEP):
        self.ms, self.step = ms, float(step)
        self.fl = (slab > 0).astype(np.float32)
        self.shape = self.fl.shape
        self.terms = []
        gap, wmin, reach = ms.px(ICON_GAP), ms.px(ICON_BAND_MIN), ms.px(ICON_REACH)
        self.r_lo, self.r_hi = ms.px(ICON_R_BASE[0]), ms.px(ICON_R_BASE[1])
        self.verify_half = int(round(ms.px(VERIFY_HALF_BASE)))
        self.rim = (ms.px(ICON_RIM[0]), ms.px(ICON_RIM[1]))
        self.reach = reach
        for r in np.arange(self.r_lo, self.r_hi + 0.01, step):
            n = int(np.ceil(r + reach))
            yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
            d = np.hypot(xx, yy)
            kd = (d <= r).astype(np.float32)
            kd /= kd.sum()
            out_w = max(wmin, 0.4 * r)
            ka = ((d > r + gap) & (d <= r + gap + out_w)).astype(np.float32)
            ka /= ka.sum()
            fd = cv2.filter2D(self.fl, -1, kd, borderType=cv2.BORDER_CONSTANT)
            fa = cv2.filter2D(self.fl, -1, ka, borderType=cv2.BORDER_CONSTANT)
            bad = (fd < ICON_FLOOR_MIN[0]) | (fa < ICON_FLOOR_MIN[1])
            self.terms.append((float(r), kd, ka, 1.0 / np.maximum(fd, 1e-3),
                               1.0 / np.maximum(fa, 1e-3), bad))
        self.radii = np.array([t[0] for t in self.terms])


def _dark(hsv, fl):
    return (hsv[..., 2] < ICON_DARK_V).astype(np.float32) * fl


def propose_icons(img: np.ndarray, terms: IconTerms, min_score: float = ICON_MIN) -> list[dict]:
    """The full search: dark compact discs on the slab, best first, each
    with `cx, cy, r, score, rim_teal, rim_red, glyph_white`."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    dark = _dark(hsv, terms.fl)
    best = np.full(dark.shape, -9.0, np.float32)
    arg = np.zeros(dark.shape, np.float32)
    for r, kd, ka, ifd, ifa, bad in terms.terms:
        s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) * ifd - \
            cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_CONSTANT) * ifa
        s[bad] = -9.0
        up = s > best
        best[up], arg[up] = s[up], r
    k = max(3, int(2 * terms.r_lo) | 1)
    peak = (best >= min_score) & (best == cv2.dilate(best, np.ones((k, k), np.uint8)))
    ys, xs = np.nonzero(peak)
    order = np.argsort(-best[ys, xs])
    keep: list[dict] = []
    for i in order:
        x, y, r = int(xs[i]), int(ys[i]), float(arg[ys[i], xs[i]])
        if any(np.hypot(x - c["cx"], y - c["cy"]) < OVERLAP * (r + c["r"]) for c in keep):
            continue
        keep.append({"cx": x, "cy": y, "r": r, "score": float(best[y, x])})
    h, w = dark.shape
    for c in keep:
        m = int(np.ceil(c["r"] + terms.rim[1] + 0.5))
        x0, x1 = max(0, c["cx"] - m), min(w, c["cx"] + m + 1)
        y0, y1 = max(0, c["cy"] - m), min(h, c["cy"] + m + 1)
        win = hsv[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dd = np.hypot(xx - c["cx"], yy - c["cy"])
        rim = (dd > c["r"] - terms.rim[0]) & (dd <= c["r"] + terms.rim[1])
        sat = rim & (win[..., 1] >= 70)
        hh = win[..., 0]
        c["rim_teal"] = float(((hh >= 75) & (hh <= 105) & sat).sum() / max(rim.sum(), 1))
        c["rim_red"] = float((((hh <= 10) | (hh >= 170)) & sat).sum() / max(rim.sum(), 1))
        core = dd <= 0.7 * c["r"]
        c["glyph_white"] = float(((win[..., 2] > 190) & core).sum() / max(core.sum(), 1))
    return keep


def verify_icons(img: np.ndarray, terms: IconTerms, tracks: list[dict], half: int | None = None,
           min_score: float = ICON_MIN) -> list[dict]:
    """Each tracked icon `{cx, cy, r}` rescored at centres within `half` px
    (the terms' VERIFY_HALF_BASE), at its own radius and the two beside it, on
    `propose_icons`'s terms. One dict per track; `score` None when nothing
    passes `min_score` (the icon is lost)."""
    half = terms.verify_half if half is None else half
    n = int(np.ceil(terms.r_hi + terms.reach))
    h, w = img.shape[:2]
    out = []
    for tr in tracks:
        cx, cy = int(tr["cx"]), int(tr["cy"])
        x0, x1 = max(0, cx - half - n), min(w, cx + half + n + 1)
        y0, y1 = max(0, cy - half - n), min(h, cy + half + n + 1)
        hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        dark = _dark(hsv, terms.fl[y0:y1, x0:x1])
        i = int(np.argmin(np.abs(terms.radii - tr["r"])))
        cx0, cx1 = max(0, cx - half) - x0, min(w, cx + half + 1) - x0
        cy0, cy1 = max(0, cy - half) - y0, min(h, cy + half + 1) - y0
        best = (-9.0, None, None, None)
        for j in range(max(0, i - 1), min(len(terms.terms), i + 2)):
            r, kd, ka, ifd, ifa, bad = terms.terms[j]
            s = cv2.filter2D(dark, -1, kd, borderType=cv2.BORDER_CONSTANT) * ifd[y0:y1, x0:x1] - \
                cv2.filter2D(dark, -1, ka, borderType=cv2.BORDER_CONSTANT) * ifa[y0:y1, x0:x1]
            s[bad[y0:y1, x0:x1]] = -9.0
            core = s[cy0:cy1, cx0:cx1]
            if core.size == 0:
                continue
            k = np.unravel_index(int(np.argmax(core)), core.shape)
            if core[k] > best[0]:
                best = (float(core[k]), int(cx0 + k[1] + x0), int(cy0 + k[0] + y0), r)
        sc, x, y, r = best
        out.append({"cx": x, "cy": y, "r": r, "score": sc if sc >= min_score else None,
                    "best": sc if x is not None else None})
    return out


def live_ref(gray: np.ndarray, base: np.ndarray, cx: float, cy: float, r: float,
             terms: IconTerms) -> dict | None:
    """A disc's live drawing as `verify_disabled` compares it: per pixel
    within its rim (r + the rim's outer reach), the luma's departure from the
    baked map, L - B, with the pixels' offsets from the centre. None where
    the disc lies off the crop."""
    R = float(r) + terms.rim[1]
    n = int(np.ceil(R))
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
    keep = np.hypot(xx, yy) <= R
    dy, dx = yy[keep], xx[keep]
    ys, xs = int(round(cy)) + dy, int(round(cx)) + dx
    h, w = gray.shape[:2]
    if ys.min() < 0 or xs.min() < 0 or ys.max() >= h or xs.max() >= w:
        return None
    return {"dy": dy, "dx": dx, "d": gray[ys, xs].astype(np.float64) - base[ys, xs]}


def verify_disabled(gray: np.ndarray, base: np.ndarray, ref: dict | None, cx: float, cy: float,
                    half: int) -> dict | None:
    """The disabled drawing's score at a tracked disc whose live verify
    failed: at each centre within `half` px of (`cx`, `cy`), the luma's
    departure from the baked map, I - B, fitted as a(L - B) + c over the
    last live drawing `ref` (`live_ref`). The centre with the least free-fit
    residual is read. Each opacity of `DIM_HYPOTHESES` (live, disabled,
    gone) scores its residual (its own best c) under the free fit's noise;
    the posterior, flat prior, is soft, and `disabled_dim` is the disabled
    hypothesis's share. Returns `{cx, cy, disabled_dim, opacity, posterior}`,
    or None where the reference is flat or the place lies off the crop."""
    if ref is None:
        return None
    lv = ref["d"]
    if lv.size < 3 or float(np.var(lv)) < DIM_NOISE_MIN ** 2:
        return None
    h, w = gray.shape[:2]
    sh = np.arange(-int(half), int(half) + 1)
    sy, sx = np.meshgrid(sh, sh, indexing="ij")
    sy, sx = sy.ravel(), sx.ravel()
    ys = int(round(cy)) + sy[:, None] + ref["dy"][None, :]
    xs = int(round(cx)) + sx[:, None] + ref["dx"][None, :]
    ok = (ys.min(1) >= 0) & (xs.min(1) >= 0) & (ys.max(1) < h) & (xs.max(1) < w)
    if not ok.any():
        return None
    ys, xs, sy, sx = ys[ok], xs[ok], sy[ok], sx[ok]
    x = gray[ys, xs].astype(np.float64) - base[ys, xs]                      # (S, P)
    lc = lv - lv.mean()
    xc = x - x.mean(1, keepdims=True)
    a = (xc @ lc) / float(lc @ lc)                                          # (S,)
    sse_free = ((xc - a[:, None] * lc[None, :]) ** 2).sum(1)
    k = int(np.argmin(sse_free))
    p = lv.size
    var = max(float(sse_free[k]) / max(p - 2, 1), DIM_NOISE_MIN ** 2)
    hyp = np.asarray(DIM_HYPOTHESES, float)
    sse = ((xc[k][None, :] - hyp[:, None] * lc[None, :]) ** 2).sum(1)
    ll = -sse / (2.0 * var)
    post = np.exp(ll - ll.max())
    post /= post.sum()
    return {"cx": int(round(cx)) + int(sx[k]), "cy": int(round(cy)) + int(sy[k]),
            "disabled_dim": float(post[1]), "opacity": float(a[k]),
            "posterior": {"live": float(post[0]), "disabled": float(post[1]), "gone": float(post[2])}}


def held_disabled(v: dict) -> bool:
    """Whether a stored verify row holds its disc through the disabled
    drawing: the live score failed and `disabled_dim` passes the one cut."""
    return v.get("score") is None and (v.get("disabled_dim") or 0.0) >= DISABLED_DIM_MIN


def held(v: dict) -> bool:
    """Whether a stored verify row continues its disc, live or disabled."""
    return v.get("score") is not None or held_disabled(v)


def verified_continuations(verify: dict | None, candidates: list[dict] | None) -> dict[int, int]:
    """{this sample's candidate index: the previous sample's candidate index
    it continues}, from one stored `ability_icon` frame row: each verify row
    that holds (`held`: its live score, or its disabled drawing) binds to the candidate of the same
    sample it overlaps (OVERLAP, the full search's own suppression rule),
    one to one, nearest first (`scipy.optimize.linear_sum_assignment`). A
    lost verify (`score` None) continues nothing; a candidate no verify binds
    is new to this sample. Pure over the stored row, so a reader of the
    stream asks this rather than linking discs by a reach of its own."""
    rows = [v for v in ((verify or {}).get("rows") or ()) if held(v)]
    cands = candidates or []
    if not rows or not cands:
        return {}
    from scipy.optimize import linear_sum_assignment
    v = np.array([[r["cx"], r["cy"], r["r"]] for r in rows], float)
    c = np.array([[x["cx"], x["cy"], x["r"]] for x in cands], float)
    d = np.hypot(v[:, None, 0] - c[None, :, 0], v[:, None, 1] - c[None, :, 1])
    ok = d < OVERLAP * (v[:, None, 2] + c[None, :, 2])
    if not ok.any():
        return {}
    i, j = linear_sum_assignment(np.where(ok, d, 1e9))
    return {int(b): int(rows[a]["of"]) for a, b in zip(i, j) if ok[a, b]}


class AbilityIconReader:
    """`passes.Reader` writing the `ability_icon` stream: per live 2 Hz
    sample, the full search's candidates and the verify of the previous
    sample's candidates."""

    cache_resample = True
    records_clip = True

    def __init__(self, slab, floor, sgray, box, phase_at=None, hz=2.0, spans=None,
                 name="ability_icon", step=RADIUS_STEP, ms: MapScale | None = SET_AT,
                 phase_reason: str | None = None):
        self.live = LIVE_PHASES
        self.name, self.hz, self.spans = name, hz, spans
        self.frames_from = "video"
        self.cv_threads = 1
        self.slab, self.floor, self.sgray, self.box = slab, floor, sgray, box
        self.phase_at, self.step = phase_at, step
        #: Why `phase_at` is None (e.g. "no HUD stream"), stored in the head.
        self.phase_reason = None if phase_at is not None else phase_reason
        #: The key's transform from base values; None refuses every sample.
        self.ms = ms
        self._terms: IconTerms | None = None
        self._prev: dict | None = None
        self.rows: list[dict] = []

    def terms(self, shape) -> IconTerms:
        if self._terms is None:
            self._terms = IconTerms(self.slab, self.ms, self.step)
        return self._terms

    def feed(self, smp) -> None:
        from .minimap import widget_drawn
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        row = {"kind": "frame", "frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms)}
        phase = None if self.phase_at is None else self.phase_at(float(smp.t_ms))
        row["phase"] = phase
        reason = None
        if self.phase_at is not None and phase not in self.live:
            reason = "not_live"
        elif crop.shape[:2] != self.slab.shape[:2]:
            reason = "geometry_size_mismatch"
        elif self.ms is None:
            reason = "no_map_scale"
        else:
            # The named steps (`usage.step`) time this feed for `reticle usage`.
            with usage_step("widget"):
                if not widget_drawn(crop, self.sgray, self.floor):
                    reason = "widget_not_drawn"
        if reason is not None:
            self.rows.append({**row, "reason": reason, "candidates": None, "verify": None})
            self._prev = None
            return
        with usage_step("terms"):
            terms = self.terms(crop.shape)
        with usage_step("propose"):
            cands = propose_icons(crop, terms)[:MAX_CANDIDATES]
        prev = self._prev
        ver = None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            with usage_step("verify"):
                rows = []
                for i, v in enumerate(verify_icons(crop, terms, prev["candidates"])):
                    vr = {"of": i, "cx": v["cx"], "cy": v["cy"], "r": v["r"],
                          "score": _rounded(v["score"])}
                    if v["score"] is None:
                        dim = self._disabled(gray, prev, i, terms)
                        vr["disabled_dim"] = None if dim is None else _rounded(dim["disabled_dim"])
                        vr["opacity"] = None if dim is None else _rounded(dim["opacity"], 3)
                        pc = prev["candidates"][i]
                        if dim is not None and held_disabled(vr) and not any(
                                np.hypot(dim["cx"] - c["cx"], dim["cy"] - c["cy"])
                                < OVERLAP * (pc["r"] + c["r"]) for c in cands):
                            vr["cx"], vr["cy"], vr["r"] = dim["cx"], dim["cy"], pc["r"]
                            # The held disc joins this sample's candidates, so the
                            # glyph reader scores it and the next verify reads it.
                            cands.append({"cx": dim["cx"], "cy": dim["cy"], "r": pc["r"],
                                          "score": v["best"], "rim_teal": None, "rim_red": None,
                                          "glyph_white": None, "state": "disabled",
                                          "disabled_dim": dim["disabled_dim"],
                                          "opacity": dim["opacity"], "_ref": dim["ref"]})
                    rows.append(vr)
                ver = {"of_t_ms": prev["t_ms"], "rows": rows}
        out = [{"cx": c["cx"], "cy": c["cy"], "r": c["r"], "score": _rounded(c["score"]),
                "rim_teal": _rounded(c["rim_teal"], 3), "rim_red": _rounded(c["rim_red"], 3),
                "glyph_white": _rounded(c["glyph_white"], 3),
                **({"state": "disabled", "disabled_dim": _rounded(c["disabled_dim"]),
                    "opacity": _rounded(c["opacity"], 3)} if c.get("state") == "disabled" else {})}
               for c in cands]
        self.rows.append({**row, "reason": None, "candidates": out, "verify": ver})
        self._prev = {"t_ms": row["t_ms"], "candidates": cands, "gray": gray}

    def _disabled(self, gray, prev: dict, i: int, terms: IconTerms) -> dict | None:
        """`verify_disabled` at the previous sample's candidate `i`, against
        its last live drawing: its own where it was live, else the one it
        carries from the sample it turned disabled."""
        pc = prev["candidates"][i]
        ref = pc.get("_ref") if pc.get("state") == "disabled" else \
            live_ref(prev["gray"], self.sgray, pc["cx"], pc["cy"], pc["r"], terms)
        dim = verify_disabled(gray, self.sgray, ref, pc["cx"], pc["cy"], terms.verify_half)
        return None if dim is None else {**dim, "ref": ref}

    def events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = {"session_id": session_id, "source": "minimap", "geometry_key": geometry_key,
                  "ability_icon_version": ABILITY_ICON_VERSION}
        by: dict = {}
        for r in self.rows:
            k = r["reason"] or "read"
            by[k] = by.get(k, 0) + 1
        head = {**common, "kind": "coverage", "hz": self.hz, "frames": len(self.rows),
                "frames_from": self.frames_from, "by_reason": by, "radius_step": self.step,
                "icon_min": ICON_MIN, "icon_r_base": [round(v, 4) for v in ICON_R_BASE],
                "dark_v": ICON_DARK_V, "floor_min": list(ICON_FLOOR_MIN),
                "verify_half_base": round(VERIFY_HALF_BASE, 4),
                "map_scale": None if self.ms is None else self.ms.provenance(),
                "slab": "minimap.slab_mask(geometry reference static)",
                "candidates": sum(len(r["candidates"] or ()) for r in self.rows),
                "verify_lost": sum(sum(not held(v) for v in r["verify"]["rows"])
                                   for r in self.rows if r["verify"]),
                "verify_held_disabled": sum(sum(held_disabled(v) for v in r["verify"]["rows"])
                                            for r in self.rows if r["verify"]),
                "disabled": {"opacity": DISABLED_OPACITY,
                             "opacity_fact": "game_data/stealthing-trap-disabled-minimap-opacity",
                             "hypotheses": list(DIM_HYPOTHESES), "cut": DISABLED_DIM_MIN,
                             "noise_min": DIM_NOISE_MIN,
                             "base": "geometry reference static, grey (ctx.sgray)"}}
        clip = getattr(self, "spans_clip", None)
        if clip is not None:
            head["spans_clip"] = clip
        if self.phase_reason is not None:
            # No phase gate: every row's `phase` is null for this reason.
            head["phase_reason"] = self.phase_reason
        return [head] + [{**common, **r} for r in self.rows]


def icon_reader(ctx, spans, phase_at=None, hz: float = 2.0, floor=None,
                sgray=None, phase_reason: str | None = None) -> AbilityIconReader:
    """The `AbilityIconReader` `scan` builds for a session: the slab of the
    geometry's reference static and the key's transform
    (`geometry.map_scale`), over the profile's minimap ROI."""
    from . import geometry
    from .minimap import minimap_roi_px, slab_mask
    box = minimap_roi_px(ctx.profile, *ctx.wh)
    return AbilityIconReader(slab=slab_mask(ctx.map_reference()),
                             floor=ctx.floor() if floor is None else floor,
                             sgray=ctx.sgray() if sgray is None else sgray,
                             box=box, phase_at=phase_at, hz=hz, spans=spans,
                             ms=geometry.map_scale_of(ctx.session_id, ctx.store.root),
                             phase_reason=phase_reason)
