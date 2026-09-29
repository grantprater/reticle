"""Where a session draws its minimap widget, measured against the baked geometry.

The player, 2026-09-28, on the Iso capture whose widget is larger than the
baked Split static and rotated in one half: "on scaling is it not a pretty easy
scale + reposition transform for minimap variants? I don't think we need to
abstain really, make a note of it I guess so analytics are counted separately
maybe". So a widget drawn at another scale, placement or orientation is read
through a transform, not abstained on, and its session carries
`minimap:variant` so reports can count it apart (`cohort`).

What the capture may decide. A capture determines only the widget's size,
placement and orientation [domain:capture/session-pixels-are-not-the-map].
The fit here measures exactly those three things -- a scale, a rotation and a
translation of the BAKED static -- and nothing else: it never builds a static
map, a floor or a lighting reference from session pixels. Every map value
still comes from the `(map, profile)` npz.

How it is applied: once, at the frame source. `normalise` resamples the
session's widget into the baked widget frame (the inverse of the fitted
transform) and writes it where the profile's minimap ROI sits, so every reader
downstream -- `widget_drawn`, the self and ally readers, `lit_mask`, the
vision raycasts -- meets baked geometry in the frame it was baked in, and every
stored coordinate stays in that frame. A session with no stored placement, or
an identity one, is never touched, so its readers see the same bytes.

A placement the capture crop cannot hold is refused by name,
`crop_clips_widget`, with the fraction of the baked floor that falls outside
the crop; it is never read as an absent widget.

Owns [owns:minimap-widget-frame].
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

WIDGET_FRAME_VERSION = "widget-frame-0.1.0"
#: The manifest key that holds a session's placements and capture box.
MANIFEST_KEY = "minimap_widget"
#: The tag a session with a non-identity placement carries.
VARIANT_TAG = "minimap:variant"

#: The scale search, coarse then fine. 0.80-1.30 brackets every widget size
#: the settings offer relative to a baked profile; the fine step is what the
#: stored scale is quoted to.
SCALES = (0.80, 1.30, 0.01)
FINE_STEP = 0.002
ROTATIONS = (0, 180)
#: Below this normalised correlation a frame names no placement: the widget is
#: not drawn (death screen, map key) or scenery dominates. A cut in an empty
#: band on the fit that set it: 13 Iso frames fitted 0.53-0.88 and the one
#: undrawn frame 0.23.
MIN_NCC = 0.40
#: The largest fraction of the baked floor a capture crop may lose before the
#: placement is refused. A declared tolerance, not a fit: an identity placement
#: loses nothing, and the Iso capture's lost 4.8-8.3% through its profile crop.
MAX_CLIP = 0.005
#: Translation and scale tolerances under which a placement IS the baked one.
IDENTITY_PX = 0.5
IDENTITY_SCALE = 0.005


# ---------------------------------------------------------------- geometry

def affine(rotation: int, sx: float, sy: float, ox: float, oy: float,
           shape: tuple[int, int], origin: tuple[int, int]) -> np.ndarray:
    """The 2x3 map from baked-static pixel (u, v) to frame pixel (x, y).

    The baked static (`shape` = (h, w)) is rotated by `rotation` about its own
    centre, scaled by (`sx`, `sy`) the way `cv2.resize` scales pixel centres,
    and its corner placed at (`ox`, `oy`) in a crop whose corner is `origin`
    in the frame.
    """
    h, w = shape
    if rotation == 0:
        r = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    elif rotation == 180:
        r = np.array([[-1.0, 0.0, w - 1.0], [0.0, -1.0, h - 1.0]])
    else:
        raise ValueError(f"rotation {rotation} is not 0 or 180")
    s = np.array([[sx, 0.0, 0.5 * sx - 0.5 + ox + origin[0]],
                  [0.0, sy, 0.5 * sy - 0.5 + oy + origin[1]]])
    return np.hstack([s[:, :2] @ r[:, :2], s[:, :2] @ r[:, 2:3] + s[:, 2:3]])


def identity_affine(baked_roi) -> np.ndarray:
    """The placement of a widget drawn exactly where it was baked."""
    x0, y0 = int(baked_roi[0]), int(baked_roi[1])
    return np.array([[1.0, 0.0, x0], [0.0, 1.0, y0]])


def is_identity(a, baked_roi) -> bool:
    a = np.asarray(a, float)
    ident = identity_affine(baked_roi)
    return (np.abs(a[:, :2] - ident[:, :2]).max() <= IDENTITY_SCALE
            and np.abs(a[:, 2] - ident[:, 2]).max() <= IDENTITY_PX)


def _to_gray(img) -> np.ndarray:
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img.astype(np.float32)


def placement_ncc(sgray, crop, origin, a) -> float:
    """Normalised correlation of the baked static placed by `a` against a crop
    whose corner is `origin` in the frame, over the pixels they share."""
    g = _to_gray(crop)
    h, w = g.shape
    m = np.asarray(a, np.float64).copy()
    m[:, 2] -= origin
    s = _to_gray(sgray)
    warped = cv2.warpAffine(s, m, (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpAffine(np.ones_like(s), m, (w, h), flags=cv2.INTER_NEAREST) > 0
    if valid.sum() < 100:
        return 0.0
    x, y = warped[valid], g[valid]
    x, y = x - x.mean(), y - y.mean()
    d = float(np.sqrt((x * x).sum() * (y * y).sum()))
    return float((x * y).sum() / d) if d else 0.0


def fit_crop(sgray, crop, origin, scales=SCALES, rotations=ROTATIONS) -> dict | None:
    """The placement of the baked static that best explains one capture crop.

    Searches rotation and scale; for each, `cv2.matchTemplate` finds the
    translation. The crop is the template and the scaled static, padded, the
    image, so a widget larger than the crop and one smaller both fit. Returns
    None when no placement reaches `MIN_NCC`.
    """
    s = _to_gray(sgray)
    g = _to_gray(crop)
    h, w = s.shape
    pad_val = float(s.mean())

    def best_at(rot, sc):
        base = s if rot == 0 else cv2.rotate(s, cv2.ROTATE_180)
        dw, dh = max(8, int(round(w * sc))), max(8, int(round(h * sc)))
        img = cv2.resize(base, (dw, dh), interpolation=cv2.INTER_LINEAR)
        # Correlate over the pixels the two share. A placed static that fits
        # inside the crop is the template, searched over the crop padded by a
        # quarter; one larger than the crop is the image, and the crop the
        # template. Either way no flat padding or unrelated scenery enters the
        # correlation as if it were widget.
        gh, gw = g.shape
        if dw <= gw and dh <= gh:
            px, py = gw // 4, gh // 4
            pad = cv2.copyMakeBorder(g, py, py, px, px, cv2.BORDER_CONSTANT,
                                     value=float(g.mean()))
            r = cv2.matchTemplate(pad, img, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            return float(mx), rot, dw / w, dh / h, loc[0] - px, loc[1] - py
        # Room for the crop to overhang the placed static on every side by a
        # quarter of itself: a widget larger than the crop sits partly outside it.
        px = max(0, gw - dw) + gw // 4
        py = max(0, gh - dh) + gh // 4
        img = cv2.copyMakeBorder(img, py, py, px, px, cv2.BORDER_CONSTANT, value=pad_val)
        r = cv2.matchTemplate(img, g, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        return float(mx), rot, dw / w, dh / h, -(loc[0] - px), -(loc[1] - py)

    lo, hi, step = scales
    coarse = [best_at(rot, sc) for rot in rotations
              for sc in np.arange(lo, hi + step / 2, step)]
    top = max(coarse)
    fine = [best_at(top[1], sc) for sc in
            np.arange(top[2] - step, top[2] + step + FINE_STEP / 2, FINE_STEP)]
    ncc, rot, sx, sy, ox, oy = max(fine + [top])
    if ncc < MIN_NCC:
        return None
    a = affine(rot, sx, sy, ox, oy, (h, w), origin)
    return {"ncc": round(ncc, 4), "rotation": rot, "scale": round((sx + sy) / 2, 4),
            "affine": [[round(float(v), 4) for v in row] for row in a]}


def placement_segments(fits: list[tuple[float, dict | None]]) -> list[dict]:
    """Consecutive fitted frames that agree, as time segments.

    `fits` is `(t_ms, fit_crop result)` in time order. Frames with no fit are
    skipped; a new segment starts at the first frame whose placement differs
    from the running one by a rotation, 0.01 of scale or 2 px of corner.
    The first segment opens at the capture start and the last closes at its
    end (`None`), so every time names one placement.
    """
    out: list[dict] = []
    for t, f in fits:
        if f is None:
            continue
        if out:
            cur = out[-1]
            same = (cur["rotation"] == f["rotation"]
                    and abs(cur["scale"] - f["scale"]) <= 0.01
                    and np.abs(np.asarray(cur["affine"])[:, 2]
                               - np.asarray(f["affine"])[:, 2]).max() <= 2.0)
            if same:
                cur["n"] += 1
                cur["ncc"].append(f["ncc"])
                cur["t_last_ms"] = t
                continue
        out.append({"t0_ms": t, "t_last_ms": t, "rotation": f["rotation"],
                    "scale": f["scale"], "affine": f["affine"], "n": 1,
                    "ncc": [f["ncc"]]})
    for i, seg in enumerate(out):
        seg["ncc_min"] = round(min(seg.pop("ncc")), 4)
        seg["t1_ms"] = out[i + 1]["t0_ms"] if i + 1 < len(out) else None
    if out:
        out[0]["t0_ms"] = None
    return out


# ---------------------------------------------------------------- manifest

def record(segs: list[dict], key: str, baked_roi, capture_box, source: str,
           n_frames: int) -> dict:
    """The manifest entry for a fitted session, with provenance and stamp."""
    return {
        "version": WIDGET_FRAME_VERSION,
        "method": "baked static NCC fit over rotation, scale and translation "
                  "(reticle.widget_frame.fit_crop)",
        "geometry_key": key,
        "baked_roi": [int(v) for v in baked_roi],
        "capture_box": None if capture_box is None else [int(v) for v in capture_box],
        "fitted_from": source,
        "fitted_frames": int(n_frames),
        "fitted_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "segments": segs,
    }


def entry(manifest: dict) -> dict | None:
    """The session's stored widget placement, or None."""
    e = (manifest or {}).get(MANIFEST_KEY)
    return e if isinstance(e, dict) and e.get("segments") else None


def is_variant(manifest: dict) -> bool:
    """Whether any stored placement differs from the baked one."""
    e = entry(manifest)
    if e is None:
        return False
    return any(not is_identity(s["affine"], e["baked_roi"]) for s in e["segments"])


def cohort(manifest: dict) -> str:
    """The analytics cohort a session belongs to: `minimap-variant` for a
    session read through a transform (or tagged so), else `standard`. Reports
    that pool minimap-derived numbers across sessions group by this."""
    tags = (manifest or {}).get("tags") or []
    return "minimap-variant" if (VARIANT_TAG in tags or is_variant(manifest)) else "standard"


def capture_box(manifest: dict) -> list[int] | None:
    """The frame rectangle this session's minimap crops are taken from, when it
    differs from the profile's ROI; None keeps the profile's."""
    e = (manifest or {}).get(MANIFEST_KEY)
    box = e.get("capture_box") if isinstance(e, dict) else None
    return [int(v) for v in box] if box else None


# ---------------------------------------------------------------- application

def clipped_fraction(a, floor: np.ndarray, box) -> float:
    """The fraction of the baked `floor` that placement `a` puts outside `box`."""
    ys, xs = np.nonzero(floor)
    if not len(xs):
        return 0.0
    a = np.asarray(a, float)
    x = a[0, 0] * xs + a[0, 1] * ys + a[0, 2]
    y = a[1, 0] * xs + a[1, 1] * ys + a[1, 2]
    x0, y0, x1, y1 = box
    inside = (x >= x0) & (x <= x1 - 1) & (y >= y0) & (y <= y1 - 1)
    return float(1.0 - inside.mean())


@dataclass
class WidgetFrame:
    """A session's non-identity placements, ready to normalise frames."""

    segments: list[dict]
    baked_roi: list[int]
    shape: tuple[int, int]               # baked static (h, w)
    box: list[int]                       # the capture crop
    refusal: dict | None = None

    def at(self, t_ms: float) -> dict | None:
        """The placement at `t_ms`, or None where it is the baked one."""
        for s in self.segments:
            if ((s["t0_ms"] is None or t_ms >= s["t0_ms"])
                    and (s["t1_ms"] is None or t_ms < s["t1_ms"])):
                return None if is_identity(s["affine"], self.baked_roi) else s
        return None

    def normalise(self, frame: np.ndarray, t_ms: float) -> np.ndarray:
        """`frame` with the baked ROI replaced by the session widget resampled
        into the baked frame; the same array when the placement is identity."""
        seg = self.at(t_ms)
        if seg is None:
            return frame
        h, w = self.shape
        x0, y0 = self.baked_roi[0], self.baked_roi[1]
        crop = cv2.warpAffine(frame, np.asarray(seg["affine"], np.float64), (w, h),
                              flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        out = frame.copy()
        out[y0:y0 + h, x0:x0 + w] = crop
        return out


def for_session(manifest: dict, box, store_root: Path | str) -> WidgetFrame | None:
    """The session's widget frame, or None when it reads the baked placement.

    `box` is the frame rectangle the session's minimap pixels come from (the
    capture box, or the profile's ROI). A placement that puts more than
    `MAX_CLIP` of the baked floor outside `box` sets `refusal`.
    """
    e = entry(manifest)
    if e is None or not is_variant(manifest):
        return None
    from . import geometry
    from .minimap import floor_mask
    sid = manifest["session_id"]
    static = geometry.reference_static(sid, store_root)
    floor = floor_mask(static, sd=geometry.stability(sid, store_root, static.shape[:2]))
    wf = WidgetFrame(segments=e["segments"], baked_roi=list(e["baked_roi"]),
                     shape=tuple(static.shape[:2]), box=[int(v) for v in box])
    worst = max(((clipped_fraction(s["affine"], floor, box), s) for s in e["segments"]),
                key=lambda p: p[0])
    if worst[0] > MAX_CLIP:
        wf.refusal = {"reason": "crop_clips_widget", "clipped": round(worst[0], 4),
                      "t0_ms": worst[1]["t0_ms"], "t1_ms": worst[1]["t1_ms"]}
    return wf


def refusal_text(r: dict) -> str:
    return (f"crop_clips_widget: {r['clipped'] * 100:.1f}% of the baked floor falls "
            f"outside the minimap crop in the segment from {r['t0_ms']} ms -- "
            f"re-decode the minimap cache with the session's capture box")


# ---------------------------------------------------------------- fitting a session

def needed_box(segs: list[dict], shape: tuple[int, int], wh: tuple[int, int],
               margin: int = 4) -> list[int]:
    """The frame rectangle that holds the whole placed static of every segment,
    plus `margin`, clipped to the frame."""
    h, w = shape
    corners = np.array([[0, 0, 1], [w - 1, 0, 1], [0, h - 1, 1], [w - 1, h - 1, 1]], float)
    pts = np.vstack([corners @ np.asarray(s["affine"], float).T for s in segs])
    x0, y0 = np.floor(pts.min(0)) - margin
    x1, y1 = np.ceil(pts.max(0)) + 1 + margin
    return [int(max(0, x0)), int(max(0, y0)), int(min(wh[0], x1)), int(min(wh[1], y1))]


def fit_session(manifest: dict, cache, store_root, n: int = 24) -> dict:
    """Fit a session's widget placement from its minimap crop cache (no decode).

    Fits `n` cached frames spread over the capture, groups them into segments
    (`placement_segments`), then moves each segment boundary to the first cached frame
    between the two fitted frames whose crop the later placement explains
    better. Returns `{"segments", "frames", "box", "shape"}`.
    """
    from . import geometry
    sid = manifest["session_id"]
    static = geometry.reference_static(sid, store_root)
    sgray = _to_gray(static)
    box = cache.rect_of("minimap")
    x0, y0, x1, y1 = box
    ts = np.unique(np.asarray(cache.t_ms, float))
    if not len(ts):
        raise SystemExit(f"{sid}: the minimap cache holds no frames")
    pick = [float(t) for t in ts[np.linspace(0, len(ts) - 1, min(n, len(ts))).astype(int)]]
    fits = [(smp.t_ms, fit_crop(sgray, smp.frame[y0:y1, x0:x1], (x0, y0)))
            for smp in cache.samples(pick, rois=("minimap",), normalise=False)]
    segs = placement_segments(fits)
    for a, b in zip(segs, segs[1:]):
        between = [float(t) for t in ts if a["t_last_ms"] < t < b["t0_ms"]]
        for smp in cache.samples(between, rois=("minimap",), normalise=False):
            crop = smp.frame[y0:y1, x0:x1]
            sb = placement_ncc(sgray, crop, (x0, y0), b["affine"])
            if sb >= MIN_NCC and sb > placement_ncc(sgray, crop, (x0, y0), a["affine"]):
                b["t0_ms"] = a["t1_ms"] = smp.t_ms
                break
    for s in segs:
        s.pop("t_last_ms", None)
    return {"segments": segs, "frames": len(fits), "box": box,
            "shape": tuple(static.shape[:2])}


class Normalised:
    """A minimap reader on a decode pass, fed frames through `WidgetFrame.normalise`.

    A cache pass needs no wrapper (`RoiCache.samples` normalises); a decode
    pass hands every reader the same frame, and the cache writer beside these
    readers must store the raw one."""

    def __init__(self, inner, wf: WidgetFrame):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_wf", wf)

    def feed(self, smp) -> None:
        from .decode import Sample
        self._inner.feed(Sample(frame_idx=smp.frame_idx, t_ms=smp.t_ms,
                                frame=self._wf.normalise(smp.frame, smp.t_ms)))

    def __getattr__(self, k):
        return getattr(self._inner, k)

    def __setattr__(self, k, v):
        setattr(self._inner, k, v)
