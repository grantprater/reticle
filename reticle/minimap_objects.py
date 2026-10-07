r"""Enemy icons, death X marks and red "?" marks, read from stored minimap crops.

    .\.venv\Scripts\python.exe -m reticle minimap-objects <session>

Owns [owns:enemy-icon] and [owns:last-known-mark]. The X marks come from the
death owner's detector (`adjudication.death.minimap_x_marks`); this module
reads them in the same pass and stores them beside the enemies.

Each cached minimap frame becomes one `minimap_object` row: the enemy icons
it holds, each with its position and, where the icon-pose owner reads it, its
facing; the X marks of both colours; the red "?" marks; and every refused
candidate with its reason. A frame the widget does not draw is a row with a
reason, not a missing row, so coverage stays unbiased. Decodes no video.

**The enemy.** The red key's ring fit proposes each icon (`minimap.icons`
with the enemy ring's gates, the detector stage 2 scored), and the icon-pose
owner's enemy class fits the teardrop from it (`teardrop.fit_icon`), whose
lobe is translucent [domain:minimap/enemy-lobe-translucent]. A read fit gives
the centre and facing (image degrees, y down). Facing never reaches the
entity lane yet: the contract names no orientation convention.

**The "?".** A red blob the X shape test rejects and no enemy icon covers,
whose red run, walked back frame by frame, begins where an enemy icon ended:
the icon's last frame lies at most `Q_SWAP_MS` before the run's first frame,
and that first frame at most `Q_GONE_MS` before now
[domain:minimap/last-known-mark] [domain:minimap/last-known-mark-timing].
The walk reads this stream's own earlier frames, so the "?" is pure over
what the pass stored.

**The icon scale.** Icons follow the map zoom
[domain:minimap/icons-follow-map-zoom], so every icon length here is a base
value times `icon_scale`, the one transform (`geometry.MapScale`: widget
scale x map zoom); the head records it and its source. The X owner is still
given the widget's scale, so the death stream's inputs do not move. Read at
the widget's scale alone (0.71 on the 331 px widget, against 0.64 with the
zoom), the enemy teardrop was 12% too large, and it refused visible enemy
icons as `no_ring` and `low_ncc`; the enemy class now also scores its ring
softly and refuses a lobeless ring as `no_lobe` (`teardrop.ICON_CLASSES`,
ENEMY_TEARDROP_VERSION). Against T1d on 9acf02f98283 the lane's hit rate rose
from [metric:teardrop_refusals/lane/stored@9acf02f98283#hit_rate=0.442] to
[metric:teardrop_refusals/lane/final@9acf02f98283#hit_rate=0.6313], and the
misses beside a `no_ring` refusal fell from
[metric:teardrop_refusals/lane/stored@9acf02f98283#no_ring=767] to
[metric:teardrop_refusals/lane/final@9acf02f98283#no_ring=27]
(`prototypes/teardrop_refusals.py`).

**Three fixes, each switchable and stamped.** `FIXES` names them and
`ENABLED` turns each on; the stamp is the base version plus the fixes on, so
turning one off changes the stamp and `reticle plan` names the stream stale.

- `teardrop_box`: an enemy is boxed at the teardrop's fitted centre with
  radius the fitted tip distance plus `TIP_PAD` * scale, which holds the tip
  at either facing; a fit refused only as `ambiguous_facing` is kept as
  position only, its facing null with that reason. Off, only a read
  teardrop is kept, boxed by the fixed ring `RING` * scale (stage 2's
  teardrop mode). On a held-out sample the box held the whole icon on
  [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK4_n=14]
  of [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK4_of=14].
  Either way a fit the teardrop refuses for another reason (`low_ncc`,
  `no_ring`) is no enemy: it is stored refused at the ring's centre with no
  extent, and where a shape-confirmed red X lies within `X_OWN_PX` * scale
  it is the X classifier's (`owned_by_x_classifier`), not a missed enemy.
- `slab_gate`: a red candidate (enemy, red X, or the red blob a "?" is read
  from) is kept only when at least `RED_SHARE` of the redness within
  `ICON_PX` * scale lies on the baked slab. Void just off the map makes
  false red candidates [domain:minimap/transparency]; the slab comes from
  baked geometry only [domain:capture/session-pixels-are-not-the-map]. A
  disc with no red abstains and keeps. On the held-out sample the gate
  dropped [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK1_n=0]
  of [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK1_of=16]
  marks the player called an enemy, X or "?".

- `owner_gate`: a teardrop read is the X classifier's where a
  shape-confirmed red X lies within `X_OWN_PX` * scale, and the ping
  reader's where a confirmed ping of the stored `ping` stream is drawn
  within `ICON_PX` * scale at that time (`stored_pings`; no ping stream, the
  gate abstains). Danger pings the ping reader rejects by lifetime
  [domain:minimap/danger-ping-pulses] stay unowned and may still read.

The first two fixes were measured in `prototypes/enemy_lane_bounds.py`
(enemy-lane-bounds-0.1.0) before they were wired; the third and the icon
scale in `prototypes/teardrop_refusals.py`.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .version import ALLY_PORTRAIT_FEATURES_VERSION, ENEMY_TEARDROP_VERSION, TEARDROP_VERSION

#: 0.2.0 (2026-10-07): icons are read at base x widget scale x map zoom
#: (`icon_scale`), the enemy teardrop scores its ring softly
#: (ENEMY_TEARDROP_VERSION 0.2.0), and the `owner_gate` fix.
MINIMAP_OBJECT_BASE = "minimap-object-0.2.0"

#: The switchable fixes, in stamp order.
FIXES = ("teardrop_box", "slab_gate", "owner_gate")
#: Which fixes are on. A caller may pass its own map; the stamp records it.
ENABLED = {"teardrop_box": True, "slab_gate": True, "owner_gate": True}


def minimap_object_version(fixes: dict | None = None) -> str:
    """The stream's stamp: the base version plus each fix that is on."""
    fixes = ENABLED if fixes is None else fixes
    on = [f for f in FIXES if fixes.get(f)]
    return f"{MINIMAP_OBJECT_BASE}+{'+'.join(on) if on else 'nofix'}"


# The enemy ring fit: the HSV key and gates stage 2 used
# (prototypes/minimap_icons.enemy_red_mask, prototypes/minimap_ring_fit).
HUE_LO, HUE_HI, SAT_MIN, VAL_MIN = 8, 168, 100, 90
COV_MIN, INNER_RED_MAX = 0.30, 0.25
RING = 11.0          # the fixed box radius with teardrop_box off, * scale
TIP_PAD = 1.5        # the teardrop box's pad past the fitted tip, * scale
RED_SHARE = 0.25     # the slab gate's floor
ICON_PX = 10.0       # an icon's radius for the gate disc and for "under an icon", * scale
X_OWN_PX = 6.0       # a ring find this near a shape-confirmed red X is the X's, * scale
# The "?" witness (prototypes/minimap_objects_s2.question_at).
Q_GONE_MS = 3300.0   # the measured gone time's maximum (3.28 s), rounded up
Q_SWAP_MS = 200.0    # the icon's last frame lies this near the run's first
PLACE_PX = 6.0       # a red blob at the "?"'s place, * scale
GAP_FRAMES = 2       # frames the red run may miss

REFUSALS = ("widget_not_drawn", "widget_shape")


def enemy_red_mask(crop: np.ndarray) -> np.ndarray:
    """The enemy ring fit's key: saturated, bright red in HSV."""
    import cv2

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(np.int16) for i in range(3))
    return ((h < HUE_LO) | (h > HUE_HI)) & (s > SAT_MIN) & (v > VAL_MIN)


def slab_red_share(red: np.ndarray, slab: np.ndarray, x: float, y: float, scale: float) -> float | None:
    """The share of the redness within ICON_PX * scale of (x, y) that lies on
    the slab; None where the disc holds no red."""
    r = ICON_PX * scale
    h, w = red.shape
    x0, x1 = max(0, int(x - r)), min(w, int(x + r) + 2)
    y0, y1 = max(0, int(y - r)), min(h, int(y + r) + 2)
    if x0 >= x1 or y0 >= y1:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    disc = np.hypot(xx - x, yy - y) <= r
    sub = red[y0:y1, x0:x1]
    tot = float(sub[disc].sum())
    if tot <= 0:
        return None
    return float(sub[disc & slab[y0:y1, x0:x1]].sum()) / tot


def _gate(fixes, red, slab, x, y, scale) -> tuple[float | None, str | None]:
    """The slab gate's share and, where it drops the candidate, the reason."""
    if not fixes.get("slab_gate"):
        return None, None
    share = slab_red_share(red, slab, x, y, scale)
    if share is not None and share < RED_SHARE:
        return share, f"off_slab: red share {share:.2f} < {RED_SHARE}"
    return share, None


def _rnd(v, n=2):
    return None if v is None else round(float(v), n)


def _owned(fixes, marks, pings, t_ms, x, y, scale) -> tuple[str, str] | None:
    """The `owner_gate`: the channel that observes a teardrop read's place, as
    `(cls, reason)`, or None. A shape-confirmed red X within `X_OWN_PX` *
    scale is the X classifier's; a confirmed ping drawn at `t_ms` within
    `ICON_PX` * scale is the ping reader's. Each owner is asked, not restated:
    the X is `minimap_x_marks`' answer, the ping a stored `ping` event."""
    if not fixes.get("owner_gate"):
        return None
    if any(math.hypot(q["x"] - x, q["y"] - y) <= X_OWN_PX * scale for q in marks["red"]):
        return "x_mark", "owned_by_x_classifier: teardrop read"
    if pings is not None and pings.size and t_ms is not None:
        on = (pings[:, 0] <= t_ms) & (t_ms <= pings[:, 1])
        if on.any():
            d = np.hypot(pings[on, 2] - x, pings[on, 3] - y)
            if d.min() <= ICON_PX * scale:
                return "ping", "owned_by_ping: teardrop read"
    return None


def read_frame(crop: np.ndarray, ctx: dict, *, scale: float, fixes: dict | None = None,
               turn: bool = False, t_ms: float | None = None) -> dict:
    """One drawn frame: enemies, X marks, red blobs, refusals.

    `ctx` holds the baked `floor` and `slab` (`minimap.floor_mask`,
    `slab_mask`). `scale` is the icon scale (`object_context`'s
    `icon_scale`); `ctx["scale"]`, the widget's, is what the X owner is
    given. `turn` rotates each enemy's aligned portrait 180 degrees,
    for a widget drawn turned over [domain:minimap/upright-icons-on-turned-map].
    The "?" marks need earlier frames and are added by `last_known`.
    """
    from . import ally_portrait, minimap, teardrop
    from .adjudication.death import minimap_x_marks

    fixes = ENABLED if fixes is None else fixes
    floor, slab = ctx["floor"], ctx["slab"]
    red = teardrop.redness(crop)
    enemies, refused = [], []
    # The X classifier owns every shape-confirmed X: a ring find the
    # teardrop does not read at an X is the X's, not a missed enemy.
    # The X owner is asked at the scale it has always been given (the
    # widget's), so the death stream's inputs do not move with this reader.
    marks = minimap_x_marks(crop, floor, ctx.get("scale", scale))
    finds = minimap.icons(enemy_red_mask(crop), crop, floor, cov_min=COV_MIN,
                          inner_max=INNER_RED_MAX, require_facing=False, support=slab,
                          seed="centroid")
    for d in finds:
        ring = {"x": _rnd(d["cx"]), "y": _rnd(d["cy"]), "r": _rnd(d.get("r"))}
        f = teardrop.fit_icon(None, "enemy", d["cx"], d["cy"], scale=scale, key=red)
        reason = None if f.get("read") else f.get("reason")
        position_only = (reason == "ambiguous_facing" and fixes.get("teardrop_box")
                         and "x" in f)
        if reason is not None and not position_only:
            # A refused fit is never emitted with the fixed ring as its
            # extent, which cuts the icon [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK6_n=6];
            # it is stored at the ring's centre with no extent and its reason.
            at_x = any(math.hypot(q["x"] - d["cx"], q["y"] - d["cy"]) <= X_OWN_PX * scale
                       for q in marks["red"])
            refused.append({"cls": "x_mark" if at_x else "enemy", "x": ring["x"],
                            "y": ring["y"],
                            "reason": ("owned_by_x_classifier: teardrop " if at_x
                                       else "teardrop: ") + str(reason),
                            "ncc": _rnd(f.get("ncc"), 3)})
            continue
        x, y = float(f["x"]), float(f["y"])
        own = _owned(fixes, marks, ctx.get("pings"), t_ms, x, y, scale)
        if own:
            refused.append({"cls": own[0], "x": _rnd(x), "y": _rnd(y), "reason": own[1],
                            "ncc": _rnd(f.get("ncc"), 3)})
            continue
        tip_d = math.hypot(f["tip_x"] - x, f["tip_y"] - y)
        box = tip_d + TIP_PAD * scale if fixes.get("teardrop_box") else RING * scale
        share, drop = _gate(fixes, red, slab, x, y, scale)
        if drop:
            refused.append({"cls": "enemy", "x": _rnd(x), "y": _rnd(y), "reason": drop})
            continue
        img = ally_portrait.align_icon(crop, x, y)
        if turn:
            img = np.ascontiguousarray(img[::-1, ::-1])
        feats = ally_portrait.stored(ally_portrait.portrait_features(img, minimap.portrait_key(img)))
        enemies.append({
            "x": _rnd(x), "y": _rnd(y), "r": _rnd(box),
            "facing": None if position_only else _rnd(float(f["deg"]) % 360.0, 1),
            "facing_reason": "ambiguous_facing" if position_only else None,
            "tip": [_rnd(f["tip_x"]), _rnd(f["tip_y"])], "ncc": _rnd(f.get("ncc"), 3),
            "margin": _rnd(f.get("margin"), 3), "ring": ring, "slab_red_share": _rnd(share, 3),
            "portrait_features": feats})
    xr = []
    for q in marks["red"]:
        share, drop = _gate(fixes, red, slab, q["x"], q["y"], scale)
        if drop:
            refused.append({"cls": "x_mark", "x": q["x"], "y": q["y"], "reason": drop})
        else:
            xr.append(q)
    blobs = []
    for a, bx, by in marks["red_other"]:
        if any(math.hypot(e["x"] - bx, e["y"] - by) <= ICON_PX * scale for e in enemies):
            continue
        share, drop = _gate(fixes, red, slab, bx, by, scale)
        if drop:
            refused.append({"cls": "red_blob", "x": bx, "y": by, "reason": drop})
            continue
        blobs.append([a, bx, by])
    return {"reason": None, "enemies": enemies,
            "x_marks": {"blue": marks["blue"], "red": xr}, "red_blobs": blobs,
            "refused": refused}


def last_known(frames: list[dict], scale: float) -> None:
    """Mark each read frame's red blobs as "?" marks or leave them, in place.

    For each red blob of frame t, walk back over the earlier read frames: an
    enemy icon within ICON_PX * scale ends the walk (`icon_last`); a red blob
    within PLACE_PX * scale extends the run (`onset`); more than GAP_FRAMES
    misses end it. A "?" is a blob whose run begins at most Q_SWAP_MS after
    the icon's last frame and at most Q_GONE_MS before t. `questions` holds
    each with the key of the icon it replaced; `red_other` holds the rest,
    each with why it is no "?".
    """
    read = [f for f in frames if f.get("reason") is None]
    T = [f["t_ms"] for f in read]
    for idx, f in enumerate(read):
        qs, other = [], []
        t = f["t_ms"]
        for a, bx, by in f["red_blobs"]:
            on, miss, k, icon_last, icon_key = t, 0, idx, None, None
            while k - 1 >= 0 and t - T[k - 1] <= Q_GONE_MS + Q_SWAP_MS + 200.0:
                k -= 1
                g = read[k]
                hit = next((i for i, e in enumerate(g["enemies"])
                            if math.hypot(e["x"] - bx, e["y"] - by) <= ICON_PX * scale), None)
                if hit is not None:
                    icon_last, icon_key = g["t_ms"], f"{g['t_ms']:.1f}:{hit}"
                    break
                if any(math.hypot(x - bx, y - by) <= PLACE_PX * scale
                       for _a, x, y in g["red_blobs"]):
                    on, miss = g["t_ms"], 0
                else:
                    miss += 1
                    if miss > GAP_FRAMES:
                        break
            why = ("no_icon_before" if icon_last is None
                   else "icon_ended_early" if on - icon_last > Q_SWAP_MS
                   else "older_than_gone" if t - on > Q_GONE_MS else None)
            if why is None:
                qs.append({"x": bx, "y": by, "onset_ms": on, "icon_last_ms": icon_last,
                           "icon_key": icon_key, "age_ms": round(t - on, 1)})
            else:
                other.append({"x": bx, "y": by, "area": a, "reason": why})
        f["questions"], f["red_other"] = qs, other
    for f in read:
        f.pop("red_blobs", None)


def object_context(store, sid: str) -> tuple[dict | None, str | None]:
    """The crop cache and the baked masks one session's read needs, or None
    with the reason."""
    import cv2

    from . import geometry
    from .minimap import floor_mask, slab_mask, widget_scale
    from .profiles import get_profile
    from .roi_cache import RoiCache

    man = store.read_manifest(sid)
    cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
    if cache is None:
        return None, f"no minimap crop cache ({why})"
    geo = geometry.path_of(sid, store.root)
    if geo is None or not geo.is_file():
        return None, "no baked geometry"
    med = geometry.reference_static(sid, store.root)
    sd = geometry.stability(sid, store.root, med.shape[:2])
    floor = floor_mask(med, sd=sd)
    pings, ping_version = stored_pings(store, sid)
    # Icons follow the map zoom [domain:minimap/icons-follow-map-zoom]: the
    # one transform is base x widget scale x map zoom (`geometry.MapScale`).
    ws = widget_scale(floor.shape[1])
    ms = geometry.map_scale_of(sid, store.root)
    icon_scale, icon_scale_source = ((ms.scale, ms.provenance()) if ms is not None else
                                     (ws, "widget_scale: the geometry has no art fit"))
    return {"cache": cache, "floor": floor, "slab": slab_mask(med, sd=sd),
            "sgray": cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64),
            "rect": cache.rect_of("minimap"), "scale": widget_scale(floor.shape[1]),
            "geometry_key": geometry.key_of(sid, store.root),
            "pings": pings, "ping_version": ping_version,
            "icon_scale": icon_scale, "icon_scale_source": icon_scale_source}, None


def stored_pings(store, sid: str) -> tuple[np.ndarray | None, str | None]:
    """The ping reader's confirmed pings, `(t0_ms, t1_ms, x, y)` rows in widget
    px, and the stream's stamp; `(None, None)` where no ping stream is stored,
    so the gate abstains rather than calling every place unpinged."""
    rows = store.read_events("ping", sid)
    if not rows:
        return None, None
    stamp = next((r.get("producer_version") or r.get("ping_version") for r in rows), None)
    on, out = {}, []
    for r in rows:
        if r.get("event_kind") == "entity_state":
            on[r["entity_id"]] = (float(r["t_ms"]), r["position"])
        elif r.get("event_kind") == "entity_deleted" and r.get("entity_id") in on:
            t0, (x, y) = on.pop(r["entity_id"])
            out.append((t0, float(r["t_ms"]), float(x), float(y)))
    return np.asarray(out, float).reshape(-1, 4), stamp


def read_times(ctx: dict, times, fixes: dict | None = None) -> list[dict]:
    """Frame rows at cache `times` (each held by the cache), "?" marks included."""
    from .minimap import widget_drawn

    cache = ctx["cache"]
    x0, y0, x1, y1 = ctx["rect"]
    frames = []
    for smp in cache.samples(sorted(float(t) for t in times), rois=["minimap"]):
        crop = smp.frame[y0:y1, x0:x1]
        row = {"kind": "frame", "t_ms": float(smp.t_ms), "frame_idx": int(smp.frame_idx)}
        if crop.shape[:2] != ctx["floor"].shape:
            row["reason"] = "widget_shape"
        elif not widget_drawn(crop, ctx["sgray"], ctx["floor"]):
            row["reason"] = "widget_not_drawn"
        else:
            seg = cache.widget.at(smp.t_ms) if cache.widget is not None else None
            turn = bool(seg) and int(seg.get("rotation", 0)) == 180
            row.update(read_frame(crop, ctx, scale=ctx["icon_scale"], fixes=fixes, turn=turn,
                                  t_ms=float(smp.t_ms)))
        frames.append(row)
    frames.sort(key=lambda r: r["t_ms"])
    last_known(frames, ctx["icon_scale"])
    return frames


def read_session(store, sid: str, fixes: dict | None = None) -> dict:
    """Every frame of the session's minimap crop cache, read.

    Returns `{"rows": [...]}`, a coverage row first and a row per cached
    frame, or `{"skipped": why}`."""
    from .roi_cache import ROI_CACHE_VERSION

    fixes = dict(ENABLED if fixes is None else fixes)
    ctx, why = object_context(store, sid)
    if ctx is None:
        return {"skipped": why}
    times = ctx["cache"].holds()
    frames = read_times(ctx, times, fixes)
    version = minimap_object_version(fixes)
    read = [f for f in frames if f.get("reason") is None]
    head = {"kind": "coverage", "session": sid, "minimap_object_version": version,
            "fixes": {f: bool(fixes.get(f)) for f in FIXES},
            "roi_cache_version": ROI_CACHE_VERSION, "teardrop_version": TEARDROP_VERSION,
            "enemy_teardrop_version": ENEMY_TEARDROP_VERSION,
            "inputs": {"ping": ctx.get("ping_version")},
            "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION,
            "geometry_key": ctx["geometry_key"], "scale": ctx["scale"],
            "icon_scale": ctx["icon_scale"], "icon_scale_source": ctx["icon_scale_source"],
            "parameters": {"COV_MIN": COV_MIN, "INNER_RED_MAX": INNER_RED_MAX, "RING": RING,
                           "X_OWN_PX": X_OWN_PX,
                           "TIP_PAD": TIP_PAD, "RED_SHARE": RED_SHARE, "ICON_PX": ICON_PX,
                           "Q_GONE_MS": Q_GONE_MS, "Q_SWAP_MS": Q_SWAP_MS,
                           "PLACE_PX": PLACE_PX, "GAP_FRAMES": GAP_FRAMES},
            "frames": len(frames), "read": len(read),
            "refused": {k: sum(f.get("reason") == k for f in frames) for k in REFUSALS},
            "enemies": sum(len(f["enemies"]) for f in read),
            "enemies_position_only": sum(e["facing"] is None for f in read for e in f["enemies"]),
            "x_blue": sum(len(f["x_marks"]["blue"]) for f in read),
            "x_red": sum(len(f["x_marks"]["red"]) for f in read),
            "questions": sum(len(f["questions"]) for f in read),
            "candidates_refused": dict(sorted(Counter(
                f"{x['cls']}:{x['reason'].split(':')[0]}" for f in read
                for x in f["refused"]).items()))}
    for f in frames:
        f["minimap_object_version"] = version
    return {"rows": [head] + frames}
