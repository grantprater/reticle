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

A side-based widget turns at the side switch. A session whose manifest or
profile declares `minimap_mode.orientation` `per_side`, or whose stored
`widget_drawn` rate collapses at the halftime switch
[domain:rounds/halftime-side-swap] (`drawn_collapse`), needs a stored
placement before any reader reads its minimap: unread, the turned half meets
the unturned static and reads as an absent widget (b3b9defb6fd7 read 0 of
5018 second-half frames drawn). `placement_status` names such a session and
`fit_command` the fix; `unplaced_refusal` makes the crop cache and a decode
pass refuse it by name; `scan` fits it from the crop cache (`fit_session`,
which fits a frame in each stored round as well as the evenly spread ones)
and writes the placement through `write_placement`, the path `widget-fit
--write` takes, with its provenance. A per-side session that never turns
stores its identity placement, so it is not fitted again. A fitted turn
starts at the stored start of the round it opens, not at the first cached
frame that reads turned (`snap_switch`)
[domain:minimap/side-based-widget-turns-between-rounds].

The capture box a session's minimap cache is cut with holds the widget
under every stored placement and the profile's own ROI (`capture_box_for`):
one crop serves both halves of a side-based match.

Portraits keep their on-screen orientation on a turned map
[domain:minimap/upright-icons-on-turned-map], so the readers that score a
portrait turn it back where `turned_at` says the placement is turned.

Owns [owns:minimap-widget-frame].
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

#: 0.2.0 (2026-10-04): the fit also fits a cached frame inside each stored
#: round and records the rounds its segments start in (`switch_rounds`); a
#: per-side session that fits identity stores that placement; the capture box
#: is the union of every segment's box and the profile's ROI (`capture_box_for`).
#: 0.3.0 (2026-10-04): a turn starts at the stored start of the round that
#: holds its first turned cached frame, not at that frame, and `switch_round`
#: names that round (0.2.0 named the next one wherever a cache gap followed
#: the round start); a turn the bracketing frames cannot place at exactly one
#: round start is refused (`snap_switch`).
WIDGET_FRAME_VERSION = "widget-frame-0.3.0"
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
#: The stored `widget_drawn` collapse that names a turned widget read without
#: its placement: at some round boundary, the rate inside the rounds before it
#: at least DRAWN_BEFORE_MIN and inside the rounds from it on at most
#: DRAWN_AFTER_MAX. Declared cuts in an empty band: over the 20 stored matches
#: with a round 13 and no placement, the rates before and after round 13 ran
#: 0.950-0.986, except b3b9defb6fd7's 0.977 then 0.000.
DRAWN_BEFORE_MIN = 0.60
DRAWN_AFTER_MAX = 0.20
#: The fewest rounds on each side of a boundary the collapse test weighs.
COLLAPSE_MIN_ROUNDS = 3


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
           n_frames: int, rounds_from: str | None = None, why: str | None = None) -> dict:
    """The manifest entry for a fitted session, with provenance and stamp.
    `rounds_from` names the round table whose rounds were fitted, `why` what
    asked for the fit (`placement_status`'s reason, or `widget-fit`)."""
    return {
        "version": WIDGET_FRAME_VERSION,
        "method": "baked static NCC fit over rotation, scale and translation "
                  "(reticle.widget_frame.fit_crop)",
        "geometry_key": key,
        "baked_roi": [int(v) for v in baked_roi],
        "capture_box": None if capture_box is None else [int(v) for v in capture_box],
        "fitted_from": source,
        "fitted_frames": int(n_frames),
        "fitted_rounds_from": rounds_from,
        "fitted_because": why,
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


#: The identity of reading the baked placement: no stored placement, or one
#: whose every segment is identity (`for_session` returns None for both).
NO_PLACEMENT = "none"


def placement_digest(e: dict | None) -> str:
    """A content hash of the segments a reader resamples by: each segment's
    span, rotation and affine. The fit's diagnostics (`n`, `ncc_min`, the
    bracketing frames, `switch_round`) and its stamp move no pixel, so they
    are left out. `NO_PLACEMENT` where readers read the baked frame."""
    import hashlib
    import json
    if e is None or not e.get("segments") or all(
            is_identity(s["affine"], e["baked_roi"]) for s in e["segments"]):
        return NO_PLACEMENT
    r = lambda v: None if v is None else round(float(v), 3)
    segs = [[r(s.get("t0_ms")), r(s.get("t1_ms")), int(s.get("rotation") or 0) % 360,
             [[round(float(v), 4) for v in row] for row in s["affine"]]]
            for s in e["segments"]]
    blob = json.dumps({"baked_roi": [int(v) for v in e["baked_roi"]], "segments": segs},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def placement_identity(manifest: dict) -> str:
    """The stored placement a reader reads the widget through, as a stream
    records it: `<stamp>#<placement_digest>`, or `NO_PLACEMENT`."""
    e = entry(manifest)
    d = placement_digest(e)
    return d if d == NO_PLACEMENT else f"{e.get('version')}#{d}"


def placement_changed_at(manifest: dict) -> str | None:
    """When the stored placement last changed what a reader reads: the
    `fitted_at` of the oldest entry, in `minimap_widget_history` and the
    current one, of the unbroken run of entries ending at the current one
    whose `placement_digest` matches it. None where the session has never
    stored a placement that reads differently from the baked one, and
    `unknown` where the entry that changed it records no time. A refit
    that moves only the stamp or the diagnostics changes nothing here."""
    cur = entry(manifest)
    if cur is None:
        return None
    hist = [h for h in (manifest.get(MANIFEST_KEY + "_history") or [])
            if isinstance(h, dict) and h.get("segments")]
    chain = hist + [cur]
    want = placement_digest(cur)
    i = len(chain) - 1
    while i > 0 and placement_digest(chain[i - 1]) == want:
        i -= 1
    if i == 0 and want == NO_PLACEMENT:
        return None
    # An entry with no `fitted_at` changed the placement at an unknown time.
    return chain[i].get("fitted_at") or "unknown"


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


# ---------------------------------------------------------------- side-based widgets

def declared_orientation(manifest: dict) -> str:
    """The minimap orientation the session declares: the manifest's
    `minimap_mode.orientation`, else its profile's, else `always_same`."""
    mode = (manifest or {}).get("minimap_mode") or {}
    if mode.get("orientation"):
        return str(mode["orientation"])
    try:
        from .profiles import get_profile
        return get_profile(manifest["source_profile"]).minimap.orientation
    except (KeyError, SystemExit, ValueError):
        return "always_same"


def fit_command(sid: str) -> str:
    """The command that fits and stores a session's placement."""
    return f"reticle widget-fit {sid} --write"


def unplaced_refusal(manifest: dict) -> str | None:
    """Why a minimap read of this session is refused before it has a stored
    placement: it declares a side-based orientation, so half the match draws
    the widget turned. None once any placement is stored."""
    if entry(manifest) is not None or declared_orientation(manifest) != "per_side":
        return None
    return (f"per_side_unplaced: the session declares a side-based minimap and stores "
            f"no placement -- run `{fit_command(manifest['session_id'])}`")


def drawn_collapse(t_ms, drawn, rounds: list[dict]) -> dict | None:
    """The round boundary where the stored `widget_drawn` rate collapses, or None.

    `t_ms` and `drawn` are a minimap stream's sample times and flags; `rounds`
    the stored round rows (`round_no`, `t_start_ms`, `t_end_ms`). The rate is
    taken inside rounds only. The boundary returned is the round start with
    the rounds before it drawn at `DRAWN_BEFORE_MIN` or more and the rounds
    from it on at `DRAWN_AFTER_MAX` or less, each side `COLLAPSE_MIN_ROUNDS`
    rounds or more; the largest drop wins."""
    if len(rounds) < 2 * COLLAPSE_MIN_ROUNDS:
        return None
    rs = sorted(rounds, key=lambda r: r["t_start_ms"])
    t = np.asarray(t_ms, float)
    d = np.asarray(drawn, float)
    a = np.asarray([r["t_start_ms"] for r in rs], float)
    z = np.asarray([r["t_end_ms"] for r in rs], float)
    k = np.searchsorted(a, t, side="right") - 1
    ok = (k >= 0) & (t < z[np.clip(k, 0, None)])
    k, d = k[ok], d[ok]
    n = np.bincount(k, minlength=len(rs)).astype(float)
    s = np.bincount(k, weights=d, minlength=len(rs))
    cn, cs = np.cumsum(n), np.cumsum(s)
    best = None
    for i in range(COLLAPSE_MIN_ROUNDS, len(rs) - COLLAPSE_MIN_ROUNDS + 1):
        nb, na = cn[i - 1], cn[-1] - cn[i - 1]
        if nb == 0 or na == 0:
            continue
        before, after = cs[i - 1] / nb, (cs[-1] - cs[i - 1]) / na
        if before >= DRAWN_BEFORE_MIN and after <= DRAWN_AFTER_MAX:
            if best is None or before - after > best["before"] - best["after"]:
                best = {"round_no": int(rs[i]["round_no"]), "t_ms": float(a[i]),
                        "before": round(float(before), 3), "after": round(float(after), 3),
                        "frames_before": int(nb), "frames_after": int(na)}
    return best


def stored_collapse(store, manifest: dict) -> dict | None:
    """`drawn_collapse` over the session's stored minimap table and rounds;
    None where either is not stored."""
    import pyarrow.parquet as pq
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    mp, rp = store.minimap_path(sid, date), store.rounds_path(sid, date)
    if not mp.is_file() or not rp.is_file():
        return None
    if not ({"t_ms", "widget_drawn"} <= set(pq.read_schema(mp).names)
            and {"round_no", "t_start_ms", "t_end_ms"} <= set(pq.read_schema(rp).names)):
        return None
    m = pq.read_table(mp, columns=["t_ms", "widget_drawn"]).to_pydict()
    r = pq.read_table(rp, columns=["round_no", "t_start_ms", "t_end_ms"]).to_pylist()
    return drawn_collapse(m["t_ms"], [bool(v) for v in m["widget_drawn"]], r)


def placement_status(store, manifest: dict) -> dict | None:
    """Why this session needs a placement fit before its minimap is read, or
    None: `per_side_unplaced` (declared side-based, nothing stored) or
    `drawn_collapse_unplaced` (the stored `widget_drawn` rate collapses at a
    round boundary, nothing stored). Each names `fit_command`."""
    if entry(manifest) is not None:
        return None
    sid = manifest["session_id"]
    if declared_orientation(manifest) == "per_side":
        return {"reason": "per_side_unplaced", "command": fit_command(sid),
                "detail": "declares a side-based minimap (minimap_mode.orientation per_side)"}
    c = stored_collapse(store, manifest)
    if c is not None:
        return {"reason": "drawn_collapse_unplaced", "command": fit_command(sid),
                "detail": (f"widget_drawn {c['before']:.3f} before round {c['round_no']} "
                           f"and {c['after']:.3f} from it"), "collapse": c}
    return None


def upright_throughout(store, manifest: dict) -> tuple[bool | None, str]:
    """Whether every minimap frame of the session is read upright, with why.

    True where a stored placement holds no turned segment, or where none is
    stored and the session is not side-based: it declares no `per_side`
    orientation and its stored `widget_drawn` rate does not collapse at a
    round boundary (`placement_status` is None over a stored minimap table and
    round table that hold the columns `drawn_collapse` reads). False where a
    stored segment is turned (`turned_at`). None where it is unknown: a
    side-based session with no placement stored, or no stored minimap or round
    table to look for a collapse in."""
    import pyarrow.parquet as pq
    e = entry(manifest)
    if e is not None:
        if turned_at(manifest) is not None:
            return False, "turned: a stored placement segment is rotated 180 degrees"
        return True, f"upright: {len(e['segments'])} stored placement segments, none turned"
    status = placement_status(store, manifest)
    if status is not None:
        return None, f"unknown: {status['reason']}, no placement stored"
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    need = ((store.minimap_path(sid, date), {"t_ms", "widget_drawn"}),
            (store.rounds_path(sid, date), {"round_no", "t_start_ms", "t_end_ms"}))
    if not all(p.is_file() and cols <= set(pq.read_schema(p).names) for p, cols in need):
        return None, "unknown: no stored minimap and round tables to look for a side switch in"
    return True, "upright: not side-based (always_same, no widget_drawn collapse), baked placement"


def turned_at(manifest: dict):
    """A function of `t_ms` that is True where the session's stored placement
    is rotated 180 degrees; None where no stored segment is turned.

    Portraits keep their on-screen orientation on a turned map
    [domain:minimap/upright-icons-on-turned-map], so a portrait read in the
    baked frame there arrives upside down and its reader turns it back."""
    e = entry(manifest)
    if e is None:
        return None
    spans = [(s.get("t0_ms"), s.get("t1_ms")) for s in e["segments"]
             if int(s.get("rotation") or 0) % 360 == 180]
    if not spans:
        return None

    def turned(t_ms: float) -> bool:
        return any((a is None or t_ms >= a) and (b is None or t_ms < b) for a, b in spans)
    return turned


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


def capture_box_for(segs: list[dict], shape: tuple[int, int], wh: tuple[int, int],
                    profile_rect, margin: int = 4) -> list[int]:
    """The minimap crop a session's cache is cut with: the union of every
    segment's placed widget (`needed_box`) and the profile's own minimap ROI,
    so one crop holds the widget under every stored placement and never less
    than the profile crops."""
    need = needed_box(segs, shape, wh, margin)
    p = [int(v) for v in profile_rect]
    return [min(need[0], p[0]), min(need[1], p[1]), max(need[2], p[2]), max(need[3], p[3])]


def write_placement(store, manifest: dict, rec: dict, variant: bool) -> Path:
    """Store a fitted placement on the manifest (`record`'s entry): a previous
    one moves to `minimap_widget_history`, never overwritten, and a variant
    is tagged `VARIANT_TAG`. The one path `widget-fit --write` and `scan`'s
    automatic fit both take."""
    import json
    man = manifest
    if man.get(MANIFEST_KEY):
        man.setdefault(MANIFEST_KEY + "_history", []).append(man[MANIFEST_KEY])
    man[MANIFEST_KEY] = rec
    if variant and VARIANT_TAG not in man.setdefault("tags", []):
        man["tags"].append(VARIANT_TAG)
    path = store.manifest_path(man["session_id"])
    path.write_text(json.dumps(man, indent=2), encoding="utf-8")
    return path


def round_frames(ts: np.ndarray, rounds: list[dict] | None) -> list[float]:
    """One cached time per stored round, the one nearest its middle, so a
    side switch at any round boundary is fitted on both sides."""
    if not rounds or not len(ts):
        return []
    out = []
    for r in rounds:
        mid = 0.5 * (float(r["t_start_ms"]) + float(r["t_end_ms"]))
        i = int(np.argmin(np.abs(ts - mid)))
        if r["t_start_ms"] <= ts[i] < r["t_end_ms"]:
            out.append(float(ts[i]))
    return out


def fit_session(manifest: dict, cache, store_root, n: int = 24,
                rounds: list[dict] | None = None) -> dict:
    """Fit a session's widget placement from its minimap crop cache (no decode).

    Fits `n` cached frames spread over the capture and, given the stored
    `rounds`, one cached frame inside each round (`round_frames`), groups them
    into segments (`placement_segments`), then moves each segment boundary to
    the first cached frame between the two fitted frames whose crop the later
    placement explains better. Each later segment records the cached frames
    that bracket its change (`t_prev_last_ms`, `t_first_ms`); with `rounds`,
    a turn moves to the start of the round that holds its first turned frame
    and records that round as `switch_round`, or is refused by name
    (`snap_switch`). Returns `{"segments", "frames", "box", "shape"}`.
    """
    from . import geometry
    sid = manifest["session_id"]
    static = geometry.reference_static(sid, store_root)
    sgray = _to_gray(static)
    box = cache.stored_rect("minimap")
    x0, y0, x1, y1 = box
    ts = np.unique(np.asarray(cache.t_ms, float))
    if not len(ts):
        raise SystemExit(f"{sid}: the minimap cache holds no frames")
    pick = [float(t) for t in ts[np.linspace(0, len(ts) - 1, min(n, len(ts))).astype(int)]]
    pick = sorted(set(pick) | set(round_frames(ts, rounds)))
    fits = [(smp.t_ms, fit_crop(sgray, smp.frame[y0:y1, x0:x1], (x0, y0)))
            for smp in cache.samples(pick, rois=("minimap",), normalise=False)]
    segs = placement_segments(fits)
    for a, b in zip(segs, segs[1:]):
        between = [float(t) for t in ts if a["t_last_ms"] < t < b["t0_ms"]]
        for smp in cache.samples(between, rois=("minimap",), normalise=False):
            crop = smp.frame[y0:y1, x0:x1]
            sb = placement_ncc(sgray, crop, (x0, y0), b["affine"])
            sa = placement_ncc(sgray, crop, (x0, y0), a["affine"])
            if sb >= MIN_NCC and sb > sa:
                b["t0_ms"] = a["t1_ms"] = smp.t_ms
                break
            if sa >= MIN_NCC:
                a["t_last_ms"] = smp.t_ms
        # The cached frames that bracket the change: the last one the earlier
        # placement explains and the first one the later one does.
        b["t_prev_last_ms"], b["t_first_ms"] = a["t_last_ms"], b["t0_ms"]
    for a, b in zip(segs, segs[1:]):
        if rounds:
            snap_switch(a, b, rounds)
    for s in segs:
        s.pop("t_last_ms", None)
    return {"segments": segs, "frames": len(fits), "box": box,
            "shape": tuple(static.shape[:2])}


#: How late a stored round start may stand after the instant it marks: the
#: rounds table reads its starts from the HUD at 2 Hz (`rounds`), so a start
#: lags the buy phase by up to one 500 ms sample. b3b9defb6fd7's widget reads
#: turned from 1430216.67 ms, 283 ms before its stored round 13 start of
#: 1430500 ms.
ROUND_START_LAG_MS = 500.0


def snap_switch(a: dict, b: dict, rounds: list[dict]) -> None:
    """Move the turn between segments `a` and `b` to the stored start of the
    round it opens, and record that round as `switch_round`.

    The sides swap at halftime [domain:rounds/halftime-side-swap], and a
    side-based widget turns only then, between two rounds
    [domain:minimap/side-based-widget-turns-between-rounds]. The first cached
    frame that reads turned bounds the turn from above only: a cache gap at a
    round start would otherwise mark the round's first seconds upright.

    The round is the one stored round whose start lies after the last cached
    frame the earlier placement explains (`t_prev_last_ms`) and no later than
    `ROUND_START_LAG_MS` after the first the later one explains
    (`t_first_ms`). The turn moves to that start, or to the first turned frame
    where the frame comes first: a stored start may lag the turn by one HUD
    sample, and a frame that reads turned is never marked upright.

    The turn is refused, `switch_round` None with `switch_refusal`, and the
    boundary left at the first turned frame, where the change is not a turn
    or where the bracket holds no round start or more than one: then the fit
    cannot place the turn at one round boundary, which falsifies the fact
    above for this session or names a fit error."""
    lo, hi = float(b["t_prev_last_ms"]), float(b["t_first_ms"])
    starts = sorted((float(r["t_start_ms"]), int(r["round_no"])) for r in rounds
                    if lo < float(r["t_start_ms"]) <= hi + ROUND_START_LAG_MS)
    why = None
    if a["rotation"] == b["rotation"]:
        why = "not_a_turn: the placements differ in scale or corner, not rotation"
    elif len(starts) != 1:
        why = (f"unbracketed: {len(starts)} round starts lie after the last earlier "
               f"frame {lo} ms and by {ROUND_START_LAG_MS:g} ms after the first later "
               f"frame {hi} ms")
    if why is not None:
        b["switch_round"], b["switch_refusal"] = None, why
        return
    b["t0_ms"] = a["t1_ms"] = min(starts[0][0], hi)
    b["switch_round"] = starts[0][1]


def fit_placement(store, manifest: dict, n: int = 24) -> dict:
    """Fit a session's placement from its raw minimap crops and the stored
    rounds, and the capture box it needs. Writes nothing.

    Returns `{"segments", "frames", "held", "need", "box", "fits", "variant",
    "record", "store"}`: `held` is the cache's crop, `need` the box every
    segment's widget needs (`capture_box_for`), `fits` whether `held` holds
    it, `record` the manifest entry to store, `store` whether to store it (a
    variant, or a session `placement_status` names, whose identity fit must
    be stored so the question is answered)."""
    from . import geometry
    from .profiles import get_profile
    from .roi_cache import RoiCache, roi_rects
    sid = manifest["session_id"]
    profile = get_profile(manifest["source_profile"])
    cache, why = RoiCache.load(store.root, manifest, profile, "minimap", raw=True)
    if cache is None:
        raise SystemExit(f"{sid}: no minimap cache ({why})")
    date = manifest["ingested_at"][:10]
    table = store.read_rounds(sid, date) if store.rounds_path(sid, date).is_file() else None
    rounds = None if table is None else table.select(
        ["round_no", "t_start_ms", "t_end_ms"]).to_pylist()
    got = fit_session(manifest, cache, store.root, n=n, rounds=rounds)
    segs = got["segments"]
    if not segs:
        raise SystemExit(f"{sid}: no cached frame reached ncc {MIN_NCC}")
    with np.load(geometry.require(sid, store.root)) as z:
        baked_roi = [int(v) for v in z["roi"]]
    wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
    variant = any(not is_identity(sg["affine"], baked_roi) for sg in segs)
    profile_rect = roi_rects("minimap", profile, wh)[0]
    need = capture_box_for(segs, got["shape"], wh, profile_rect)
    held = got["box"]
    fits = (need[0] >= held[0] and need[1] >= held[1]
            and need[2] <= held[2] and need[3] <= held[3])
    # The crop that holds every placement: the one stored, where it holds
    # them, else the union. None keeps the profile's own crop.
    box = (capture_box(manifest) if fits else need)
    status = placement_status(store, manifest)
    rec = record(segs, geometry.key_of(sid, store.root), baked_roi, box,
                 f"roi_cache {cache.record['version']} rect {held}", got["frames"],
                 rounds_from=(None if rounds is None else "rounds " + (
                     table.schema.metadata or {}).get(b"round_version", b"unstamped").decode()),
                 why=status["reason"] if status else "widget-fit")
    return {"segments": segs, "frames": got["frames"], "held": held, "need": need,
            "box": box, "fits": fits, "variant": variant, "record": rec,
            "store": variant or status is not None, "status": status,
            "cache_record": cache.record}


def fit_if_needed(store, manifest: dict, n: int = 24) -> dict | None:
    """`scan`'s automatic step: fit and store the placement of a session
    `placement_status` names, from its minimap crop cache. None where the
    session needs none; `{"refused"}` where no cache can be fitted, else
    `fit_placement`'s result with `path`, the manifest it wrote."""
    status = placement_status(store, manifest)
    if status is None:
        return None
    try:
        got = fit_placement(store, manifest, n=n)
    except SystemExit as e:
        return {"refused": f"{status['reason']}: {e} -- {status['command']} needs a minimap cache"}
    got["path"] = write_placement(store, manifest, got["record"], got["variant"])
    return got


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
