r"""Where scene-stack-0.5.0's unexplained floor light comes from: the instrument first, then one class per pixel.

    .\.venv\Scripts\python.exe prototypes\light_diagnosis.py --instrument [--record]
    .\.venv\Scripts\python.exe prototypes\light_diagnosis.py --lag [--record]
    .\.venv\Scripts\python.exe prototypes\light_diagnosis.py --classify [--record] [--sheet] [--limit N]
    .\.venv\Scripts\python.exe prototypes\light_diagnosis.py --instrument --lag --classify --reuse --record

(`--reuse` re-summarises the stored rows of an earlier run and measures nothing.)

`scene_stack.py` (0.5.0) predicts a known floor pixel lit iff a team icon's
cone reaches it, draws the measured non-cone sources as tints, and calls
compared floor that reads lit anyway (`e2_lit + c_u < e2_unlit`) UNEXPLAINED
LIGHT. This tool fits nothing and changes no scene_stack number; it reads
scene_stack's 0.5.0 items (`analysis/scene-tint-20260930/items.json`), its
calibrations and its renderer.

**The player's rules bound the causes.** The drawn light is binary and
uniform: a cone lights its whole angular breadth evenly, without a range
limit, until it meets geometry or a light-stopping obstacle
[domain:minimap/vision-light-binary]. It does not linger after a cone sweeps
away, with a minute lag possible [domain:minimap/vision-trailing-persistence].
So a patchy lit reading inside one region is the reader's noise, and a
coherent lit region no cone explains names a cause.

**`--instrument`: is the lit/unlit classifier right?** Two sets of floor
whose state is certain, every value from the baked `(map, profile)`
geometry [domain:capture/session-pixels-are-not-the-map]:

- CERTAIN UNLIT: the first cached frames of each round (`ROUNDSTART_OFFS_S`
  after a crop-cache span that opens within `ROUNDSTART_MAX_S` of a stored
  round start; the barriers are drawn and the team stands in spawn), known
  floor that no team icon's 360-degree raycast reaches (walls and boxes,
  `cone.raycast`), at least `UNLIT_AWAY_PX` from every team icon (detected,
  and the stored `team_vision` tracks), off the self audio circle's two
  sizes;
- CERTAIN LIT: the core of a confident owner teardrop's cone
  (`facing_fusion.fit`, the calibration's gates) on unlabelled frames at
  least `scene_stack.CAL_AWAY_MS` from any labelled instant: `CORE_IN_DEG`
  inside the edge, `CORE_R` from the origin, every 8-neighbour reached by the
  owner's raycast, clear of every other icon.

Each pixel is read three ways: the scene's rule with its costs, the nearer
state, and the owner's `lighting.raw_lit`. A REGION (a connected piece of
certain-unlit floor; one icon's cone core) is read by majority. The
stop rule was logged first: the classifier is wrong if region-level error
exceeds 10% or per-pixel error 25% on either set.

**`--lag`: does the light follow the pose of the same frame?** For
confident team icons that move or turn between the cached frames t-2 and
t+2 (15 Hz), the light read at t is compared with the cone cast from the
teardrop pose read at each of t-2 .. t+2, over the union of those cones; the
best offset per icon is reported. A negative best offset means the drawn
light lags the pose read from the same frame.

**`--classify`: one class per unexplained pixel**, in this order:

0. NOISE. Cells are connected pieces (4-connectivity) of predicted-unlit
   compared floor with one signature over every cause mask below; the baked
   walls, not being floor, bound them. By the binary rule a cell's state is
   one state; it is decided by a binomial likelihood with the instrument's
   per-pixel error rates at that scale (equal prior). An unexplained pixel in
   a cell decided unlit, or in a cell under `MIN_CELL_PX` (scale squared),
   is the reader's noise. This fits the shape of the light rather than
   repairing pixels [domain:minimap/fit-not-repair].
   Within cells decided lit (coherent unexplained light):
1. e TEAM_VISION: inside the stored `team_vision` product's `observable_all`
   at the frame (within `TV_TOL_MS`): the tracked icons' cones, interpolated
   tracks included [owns:team-vision].
2. d UTILITY: inside a stored spatial ability observation of the session:
   `ability_shape` shapes found (a disc of the stored radius, within
   `WINDOW_MS`), `smoke` tracks (the stored disc over its interval), the
   player's ability labels (`labels/ability`, `labels/ability_paint`,
   `labels/minimap_dynamic` points, a disc of `ABILITY_R`). Only what the
   store holds; no ability's area is inferred from another's
   [domain:abilities/ability-rules-are-unique].
3. b OCCLUDER: inside a posed team icon's wedge and reached when its rays pass
   the baked boxes (`box`) or every occluder (`wall`), but not by the model's
   raycast [domain:minimap/boxes-block-unless-raised].
4. a EDGE_RANGE: reached by a posed team icon's 360-degree raycast and within
   `EDGE_DEG` outside its wedge (the width), or reached only when a team icon
   outside the scene casts over the whole widget rather than the scene
   window's diagonal (the range cap).
5. c LINGERING: inside stored `observable_all` at some frame in the last
   `LINGER_S`; the decay is measured over `LINGER_WINDOWS_S`.
6. f RESIDUAL.

Every share is set beside the CONTROL: compared floor predicted unlit that
reads unlit, given the same masks. The unlabelled scenes are the
calibration's construction (one confident team icon per frame as the scene,
the frame's other team icons outside it, teardrop poses), on the certain-lit
sample frames. GPU first (scene_stack's torch renderer), crop cache only, no
decode, no store stream writes; `--record` writes `metrics` series
`light_diagnosis`; rows and sheets go to the store's
`analysis/light-diagnosis-20260930/`. Not wired: nothing in `reticle/` reads it.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "4"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cone_origin as co  # noqa: E402
import facing_fusion as ff  # noqa: E402
import scene_stack as ss  # noqa: E402
from reticle import cone, lighting  # noqa: E402
from reticle import teardrop as td  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "light-diagnosis-0.1.0"
SERIES = "light_diagnosis"
OUT = ss.sem.STORE / "analysis" / "light-diagnosis-20260930"
ITEMS = ss.OUT / "items.json"
SIDS = ("223d636bf8d2", "bfad2778a372", "c40d950031bb", "e37fdeca944f", "5822b6646448", "a06f04a0059f",
        "e78e75b2d191")

# ---- the instrument (constants logged with the predictions)
ROUNDSTART_OFFS_S = (0.0, 0.5)     # after the span opens: the barriers are drawn, the team in spawn
ROUNDSTART_MAX_S = 40.0            # a cache span opening this long after a stored round start is a round start
ROUNDS_PER_SESSION = 6
UNLIT_AWAY_PX = 40.0               # scale 1.0
AUDIO_BAND_PX = 4.0                # scale 1.0, either side of each session audio size round the self
CORE_IN_DEG = 15.0
CORE_R = (3.0, 18.0)               # scale 1.0, past the icon's apex L
ICON_CLEAR_PX = 3.0                # scale 1.0, past another icon's apex reach
LIT_FRAMES = 15                    # unlabelled frames per session
REGION_MIN_PX = 30
SEED = 20260930

# ---- the lag test
LAG_OFFS = (-2, -1, 0, 1, 2)
LAG_TOL_MS = 20.0                  # a cached frame this near t + k/15 s is frame t + k
LAG_TURN_DEG = 10.0
LAG_SHIFT_PX = 1.5                 # scale 1.0
LAG_MATCH_PX = 6.0                 # scale 1.0: the same icon in a neighbouring frame

# ---- the classes
MIN_CELL_PX = 4.0                  # scale 1.0 squared: a smaller cell cannot show a region's state
TV_TOL_MS = 70.0
WINDOW_MS = 1000.0
ABILITY_R = 24.0                   # scale 1.0 (light_causes' radius; unmeasured per ability)
EDGE_DEG = 10.0
LINGER_S = 1.0
LINGER_WINDOWS_S = (0.067, 0.133, 0.267, 0.5, 1.0, 2.0, 3.0, 5.0)
CLASSES = ("noise", "team_vision", "utility", "occluder", "edge_range", "lingering", "residual")


def setup():
    ss._idle()
    ss.CAL = json.loads(ss.CAL_PATH.read_text(encoding="utf-8"))
    ss.LCAL = json.loads(ss.LIGHT_CAL_PATH.read_text(encoding="utf-8"))
    ss.TCAL = json.loads((ss.OUT / ss.TINT_CAL_NAME).read_text(encoding="utf-8"))
    if ss.LCAL.get("version") != ss.VERSION:
        raise SystemExit(f"{ss.LIGHT_CAL_PATH} is {ss.LCAL.get('version')}, not {ss.VERSION}")


def captures() -> dict:
    from reticle import geometry
    return {sid: geometry.manifest(sid, ss.sem.STORE)["source"]["path"].replace("\\", "/") for sid in SIDS}


def label_times() -> dict:
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    out = defaultdict(list)
    for rows in data["sets"].values():
        for r in rows:
            out[r["session"]].append(float(r["t_ms"]))
    return out


def snap(s, t: float, tol: float = LAG_TOL_MS):
    ct = s.cache_t
    j = int(np.argmin(np.abs(ct - t)))
    return float(ct[j]) if abs(ct[j] - t) <= tol else None


def crop_at(s, t: float):
    for _t, c in s.crops([t]):
        return c
    return None


# ---------------------------------------------------------------- the per-pixel reading

def e2_widget(s, crop, sc, tint=None):
    """Per-pixel error (2, H, W) of the crop against the blurred two-state baked floor, in sigma^2: the
    scene's `_err2` over the whole widget with no icon drawn (icon pixels are excluded by the callers)."""
    torch, DEV = ss.torch, ss.DEV
    bg, sd = ss.backgrounds(s)
    scal = ss.CAL["scales"][ss._skey(sc)]
    k = ss._kernel(scal["sigma_blur"])
    B = torch.tensor(bg.transpose(0, 3, 1, 2).copy(), dtype=torch.float32, device=DEV)     # (2, 3, H, W)
    if tint is not None:
        A, C, _band = tint
        At = torch.tensor(A, dtype=torch.float32, device=DEV)
        Ct = torch.tensor(C.transpose(2, 0, 1).copy(), dtype=torch.float32, device=DEV)
        B = B * (1.0 - At)[None, None] + Ct[None]
    P = ss.blur(B, k)
    obs = torch.tensor(crop.transpose(2, 0, 1).copy() / 255.0, dtype=torch.float32, device=DEV)
    sig = torch.sqrt(scal["sigma_noise"] ** 2 + torch.tensor(sd, dtype=torch.float32, device=DEV) ** 2)
    e2 = (((obs[None] - P) / sig[None, None]) ** 2).sum(1)
    return e2.cpu().numpy(), P.cpu().numpy()


def reads(s, crop, sc, e2):
    """`{rule_lit, rule_unlit, nearer_lit, raw_lit}` (H, W) bool: the scene's rule read where it predicts
    unlit (lit wins by more than c_u) and where it predicts lit (unlit wins by more than c_m), the nearer
    state, and the owner's grey test."""
    c = ss.light_costs(sc)
    return {"rule_lit": e2[1] + c["c_u"] < e2[0], "rule_unlit": e2[0] + c["c_m"] < e2[1],
            "nearer_lit": e2[1] < e2[0], "raw_lit": lighting.raw_lit(crop, s.ref)}


def icon_discs(shape, icons, sc, pad):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.zeros(shape, bool)
    for x, y in icons:
        m |= np.hypot(xx - x, yy - y) <= (td.L + pad) * sc
    return m


def audio_band(sid, shape, me, sc):
    """The two session audio sizes' rims round the stored self (`scene_stack.session_sizes`)."""
    m = np.zeros(shape, bool)
    sz = ss.session_sizes(sid)
    if sz is None or me is None:
        return m
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - me[0], yy - me[1])
    for r in (sz["footstep"], sz["reload"]):
        m |= np.abs(d - r) <= AUDIO_BAND_PX * sc
    return m


def self_at(sid, t):
    S, _why = ss._ac_session(sid)
    if S is None:
        return None
    me, _d = S.self_at(t)
    return me


def vis360(s, x, y, max_r=None, passable=None):
    return cone.raycast(s.passable if passable is None else passable, x, y, 0.0, half_angle_deg=180.0,
                        visible=s.floor, n_rays=ss.LIGHT_RAYS, max_r=max_r)


def wedge(shape, ox, oy, deg, half):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    a = np.degrees(np.arctan2(yy - oy, xx - ox))
    diff = (a - deg + 180.0) % 360.0 - 180.0
    return np.abs(diff), np.hypot(xx - ox, yy - oy)


# ---------------------------------------------------------------- --instrument

def round_start_frames(s, sid):
    from reticle.cli import _date_of
    from reticle.store import Store
    st = Store()
    tb = st.read_rounds(sid, _date_of(st.read_manifest(sid)))
    starts = sorted(float(r["t_start_ms"]) for r in (tb.to_pylist() if tb is not None else []))
    ct = s.cache_t
    opens = [float(ct[0])] + [float(ct[i + 1]) for i in np.nonzero(np.diff(ct) > 200)[0]]
    out = []
    for o in opens:
        prev = [a for a in starts if a <= o]
        if not prev or o - prev[-1] > ROUNDSTART_MAX_S * 1000 or prev[-1] == 0.0:
            continue
        out.append(o)
    out = out[:ROUNDS_PER_SESSION]
    return [t for o in out for t in (snap(s, o + 1000 * d) for d in ROUNDSTART_OFFS_S) if t is not None]


def lit_frames(s, sid, lts):
    rng = np.random.default_rng(SEED + int(sid[:6], 16) % 1000)
    ct = s.cache_t
    opens = np.array([float(ct[0])] + [float(ct[i + 1]) for i in np.nonzero(np.diff(ct) > 200)[0]])
    lts = np.asarray(sorted(lts)) if len(lts) else np.array([-1e12])
    ok = [t for t in ct if np.min(np.abs(lts - t)) >= ss.CAL_AWAY_MS
          and t - opens[opens <= t].max() >= 3000.0]
    if not ok:
        return []
    pick = sorted(rng.choice(len(ok), min(LIT_FRAMES, len(ok)), replace=False))
    return [float(ok[i]) for i in pick]


def confident(s, crop, sc):
    """The frame's team icons (`facing_fusion.team_icons`) and those whose teardrop passes the calibration's
    gates (NCC, margin) and stands clear of every other icon."""
    team = ff.team_icons(s, crop, sc)
    min_ncc = ss.CAL_MIN_NCC if sc >= 0.99 else ss.CAL_MIN_NCC_SMALL
    dets = [(c, d) for c in ("self", "ally", "enemy") for d in ss.it_.detections(crop, c, s)]
    good = []
    for ic in team:
        f = ic["fit"]
        if ic["deg"] is None or f.get("ncc", 0) < min_ncc or f.get("margin", 1.0) < ss.CAL_MIN_MARGIN:
            continue
        if any(math.hypot(d["cx"] - ic["cx"], d["cy"] - ic["cy"]) > ss.SAME_PX * sc
               and math.hypot(d["cx"] - ic["x"], d["cy"] - ic["y"]) <= (2 * td.L + 4) * sc for _c, d in dets):
            continue
        good.append(ic)
    return team, dets, good


def core_mask(s, ic, sc, shape, others):
    ox, oy = ic["x"], ic["y"]
    sn = cone.snap_origin(s.passable, ox, oy, ic["deg"], None)
    if sn is None:
        return None
    ox, oy = sn
    vis = cone.raycast(s.passable, ox, oy, ic["deg"], visible=s.floor, snap_px=0)
    vis = cv2.erode(vis.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    dang, dist = wedge(shape, ox, oy, ic["deg"], cone.CONE_HALF_ANGLE_DEG)
    m = vis & (dang <= cone.CONE_HALF_ANGLE_DEG - CORE_IN_DEG)
    m &= (dist >= (td.L + CORE_R[0]) * sc) & (dist <= (td.L + CORE_R[1]) * sc)
    m &= ~icon_discs(shape, others, sc, ss.REACH_PAD + ICON_CLEAR_PX)
    return m & s.ref.known.astype(bool)


def instrument(sess, lts) -> dict:
    acc = defaultdict(lambda: defaultdict(float))
    regions = defaultdict(list)
    colour = defaultdict(lambda: defaultdict(list))
    frames_used = defaultdict(list)
    for sid in SIDS:
        s = sess(sid)
        for kind, times in (("unlit", round_start_frames(s, sid)), ("lit", lit_frames(s, sid, lts.get(sid, [])))):
            tracks = ss.TrackIndex(sid, times) if kind == "unlit" else None
            for t, crop in s.crops(times):
                sc = widget_scale(crop.shape[1])
                skey = ss._skey(sc)
                shape = crop.shape[:2]
                src, _srcm, tint = ss.scene_sources(None, sid, t, crop, sc)
                e2, P = e2_widget(s, crop, sc, tint)
                rd = reads(s, crop, sc, e2)
                me = self_at(sid, t)
                band = audio_band(sid, shape, me, sc)
                team, dets, good = confident(s, crop, sc)
                allpos = [(d["cx"], d["cy"]) for _c, d in dets] + [(ic["x"], ic["y"]) for ic in team]
                if kind == "unlit":
                    pos = [(ic["x"], ic["y"]) for ic in team]
                    _tp, prior = tracks.prior(t + 2.0)
                    pos += [(x, y) for _role, x, y, _tid in prior]
                    if not pos:
                        continue
                    vis = np.zeros(shape, bool)
                    for x, y in pos:
                        vis |= vis360(s, x, y)
                    m = s.ref.known.astype(bool) & ~vis & ~band
                    m &= ~icon_discs(shape, pos + allpos, sc, UNLIT_AWAY_PX - td.L)
                    masks = [m]
                    want = "rule_lit"
                else:
                    masks = []
                    for ic in good:
                        others = [p for p in allpos if math.hypot(p[0] - ic["x"], p[1] - ic["y"]) > ss.SAME_PX * sc]
                        cm = core_mask(s, ic, sc, shape, others)
                        if cm is not None and cm.any():
                            masks.append(cm & ~band)
                    want = "rule_unlit"
                if not masks or not any(mm.any() for mm in masks):
                    continue
                frames_used[(kind, skey)].append((sid, t))
                a = acc[(kind, skey)]
                for m in masks:
                    n = int(m.sum())
                    a["px"] += n
                    a["rule_wrong"] += int((m & rd[want]).sum())
                    a["nearer_wrong"] += int((m & (rd["nearer_lit"] if kind == "unlit" else ~rd["nearer_lit"])).sum())
                    a["raw_wrong"] += int((m & (rd["raw_lit"] if kind == "unlit" else ~rd["raw_lit"])).sum())
                    a["rule_lit"] += int((m & rd["rule_lit"]).sum())
                    a["rule_unlit"] += int((m & rd["rule_unlit"]).sum())
                    st = 1 if kind == "lit" else 0
                    dif = (crop[m].astype(np.float32) - P[st][:, m].T * 255.0)
                    colour[(kind, skey)]["err"].append(np.sqrt((dif ** 2).sum(1)))
                    colour[(kind, skey)]["grey"].append(dif.mean(1))
                    comps = [m] if kind == "lit" else _pieces(m)
                    for cm in comps:
                        nn = int(cm.sum())
                        if nn < REGION_MIN_PX * sc * sc:
                            continue
                        wrong_px = (cm & (rd["nearer_lit"] if kind == "unlit" else ~rd["nearer_lit"])).sum()
                        rule_px = (cm & rd[want]).sum()
                        regions[(kind, skey)].append({"sid": sid, "t_ms": t, "n": nn,
                                                      "nearer_wrong_share": round(float(wrong_px) / nn, 4),
                                                      "rule_wrong_share": round(float(rule_px) / nn, 4)})
        print(f"  instrument {sid}: {dict((k, len(v)) for k, v in frames_used.items())}", flush=True)
    out = {}
    for key, a in sorted(acc.items()):
        kind, skey = key
        rg = regions[key]
        err = np.concatenate(colour[key]["err"]) if colour[key]["err"] else np.array([])
        grey = np.concatenate(colour[key]["grey"]) if colour[key]["grey"] else np.array([])
        n = max(a["px"], 1)
        out[f"{kind}@{skey}"] = {
            "frames": len(frames_used[key]), "px": int(a["px"]),
            "sessions": sorted({x for x, _t in frames_used[key]}),
            "rule_wrong_share": round(a["rule_wrong"] / n, 4),
            "nearer_wrong_share": round(a["nearer_wrong"] / n, 4),
            "raw_wrong_share": round(a["raw_wrong"] / n, 4),
            "rule_lit_share": round(a["rule_lit"] / n, 4), "rule_unlit_share": round(a["rule_unlit"] / n, 4),
            "regions": len(rg),
            "region_wrong_share": round(float(np.mean([r["nearer_wrong_share"] > 0.5 for r in rg])), 4) if rg else None,
            "region_rule_wrong_share": round(float(np.mean([r["rule_wrong_share"] > 0.5 for r in rg])), 4) if rg else None,
            "region_wrong_share_median": round(float(np.median([r["nearer_wrong_share"] for r in rg])), 4) if rg else None,
            "colour_err_median": round(float(np.median(err)), 2) if len(err) else None,
            "colour_err_p90": round(float(np.percentile(err, 90)), 2) if len(err) else None,
            "grey_bias_median": round(float(np.median(grey)), 2) if len(grey) else None,
            "worst_regions": sorted(rg, key=lambda r: -r["nearer_wrong_share"])[:5]}
    return out


def _pieces(m, conn=8):
    n, lab = cv2.connectedComponents(m.astype(np.uint8), connectivity=conn)
    return [lab == k for k in range(1, n)]


# ---------------------------------------------------------------- --lag

def cone_at(s, shape, x, y, deg):
    return cone.raycast(s.passable, x, y, deg, visible=s.floor, n_rays=cone.N_RAYS)


def lag(sess, lts) -> dict:
    rows = []
    for sid in SIDS:
        s = sess(sid)
        n0 = len(rows)
        for t in lit_frames(s, sid, lts.get(sid, [])):
            ts = {k: snap(s, t + k * 1000.0 / 15.0) for k in LAG_OFFS}
            if any(v is None for v in ts.values()):
                continue
            crops = dict(s.crops(sorted(ts.values())))
            crop = crops[ts[0]]
            sc = widget_scale(crop.shape[1])
            shape = crop.shape[:2]
            team, dets, good = confident(s, crop, sc)
            src, _srcm, tint = ss.scene_sources(None, sid, ts[0], crop, sc)
            e2, _P = e2_widget(s, crop, sc, tint)
            lit = e2[1] < e2[0]
            teams = {k: (team if k == 0 else ff.team_icons(s, crops[ts[k]], sc)) for k in LAG_OFFS}
            allpos = [(d["cx"], d["cy"]) for _c, d in dets] + [(ic["x"], ic["y"]) for ic in team]
            known = s.ref.known.astype(bool)
            for ic in good:
                poses = {}
                for k in LAG_OFFS:
                    m = [q for q in teams[k] if q["role"] == ic["role"] and q["deg"] is not None
                         and math.hypot(q["x"] - ic["x"], q["y"] - ic["y"]) <= LAG_MATCH_PX * sc]
                    if m:
                        q = min(m, key=lambda q: math.hypot(q["x"] - ic["x"], q["y"] - ic["y"]))
                        poses[k] = (q["x"], q["y"], q["deg"])
                if len(poses) < len(LAG_OFFS):
                    continue
                turn = abs(td._signed_deg(poses[2][2] - poses[-2][2]))
                shift = math.hypot(poses[2][0] - poses[-2][0], poses[2][1] - poses[-2][1])
                moving = bool(turn >= LAG_TURN_DEG or shift >= LAG_SHIFT_PX * sc)
                turn, shift = float(turn), float(shift)
                cones = {k: cone_at(s, shape, *poses[k]) for k in LAG_OFFS}
                others = [p for p in allpos if math.hypot(p[0] - ic["x"], p[1] - ic["y"]) > ss.SAME_PX * sc]
                oth_light = np.zeros(shape, bool)
                for q in team:
                    if q is ic or q["deg"] is None:
                        continue
                    oth_light |= cone_at(s, shape, q["x"], q["y"], q["deg"])
                union = np.zeros(shape, bool)
                for m in cones.values():
                    union |= m
                union &= known & ~oth_light & ~icon_discs(shape, allpos, sc, ss.REACH_PAD)
                n = int(union.sum())
                if n < 20:
                    continue
                agree = {k: int((union & (cones[k] == lit)).sum()) for k in LAG_OFFS}
                best = max(LAG_OFFS, key=lambda k: (agree[k], -abs(k)))
                rows.append({"sid": sid, "t_ms": ts[0], "role": ic["role"], "sc": sc, "moving": moving,
                             "turn_deg": round(turn, 1), "shift_px": round(shift, 2), "union_px": n,
                             "agree": {str(k): v for k, v in agree.items()}, "best": best,
                             "gain_share": round((agree[best] - agree[0]) / n, 4),
                             "gain_m1_share": round((agree[-1] - agree[0]) / n, 4)})
        print(f"  lag {sid}: {len(rows) - n0} icons", flush=True)
    return {"summary": lag_summary(rows), "rows": rows}


def _k(k):
    return ("m" if k < 0 else "p" if k > 0 else "") + str(abs(k))


def lag_summary(rows) -> dict:
    """Per widget size, moving and still icons: the share whose best offset is each k (`best_m2` .. `best_p2`),
    before (`best_neg`) or after (`best_pos`) the frame, and the median agreement gains; plus moving icons
    pooled over sizes."""
    out = {}
    groups = [(f"{'moving' if mv else 'still'}@{skey}",
               [r for r in rows if ss._skey(r["sc"]) == skey and r["moving"] == mv])
              for skey in sorted({ss._skey(r["sc"]) for r in rows}) for mv in (True, False)]
    groups.append(("moving@pooled", [r for r in rows if r["moving"]]))
    for tag, rr in groups:
        if not rr:
            continue
        out[tag] = {"icons": len(rr),
                    **{f"best_{_k(k)}_share": round(float(np.mean([r['best'] == k for r in rr])), 4)
                       for k in LAG_OFFS},
                    "best_neg_n": sum(r["best"] < 0 for r in rr), "best_pos_n": sum(r["best"] > 0 for r in rr),
                    "best_zero_n": sum(r["best"] == 0 for r in rr),
                    "gain_share_median": round(float(np.median([r["gain_share"] for r in rr])), 4),
                    "gain_m1_share_median": round(float(np.median([r["gain_m1_share"] for r in rr])), 4),
                    "sessions": sorted({r["sid"] for r in rr})}
    return out


# ---------------------------------------------------------------- --classify

BEAM_HALF_PX = 8.0                 # scale 1.0: a found beam's half-width (unmeasured; the stored row has none)
SHAPE_LIFE_MS = 1000.0             # a found shape counts from its t_ms to this long after (unmeasured)
EDGE_BANDS = ((0, 5), (5, 10), (10, 20), (20, 40))
N_SHEETS = 12
SHEETS_PER_SESSION = 2
RATES: dict = {}                   # {skey: (p_lit_read | unlit, p_lit_read | lit)}, from instrument.json


def rates():
    got = json.loads((OUT / "instrument.json").read_text(encoding="utf-8"))
    for skey in ("0.712", "1.000"):
        RATES[skey] = (got[f"unlit@{skey}"]["rule_lit_share"], got[f"lit@{skey}"]["rule_lit_share"])
    return RATES


class TVIndex:
    """The stored `team_vision` frames of one session near the wanted times: `t -> observable_all` (packed)."""

    def __init__(self, sid, wanted, before_ms):
        self.rows = {}
        p = ss.sem.STORE / "events" / "team_vision" / f"{sid}.jsonl"
        if not p.is_file() or not wanted:
            self.t = np.array([])
            return
        lo = sorted((t - before_ms - 1.0, t + TV_TOL_MS + 1.0) for t in wanted)
        with p.open(encoding="utf-8") as f:
            for line in f:
                i = line.find('"t_ms":')
                if i < 0 or '"kind":"frame"' not in line[:300]:
                    continue
                t = float(line[i + 7:line.find(",", i)])
                if not any(a <= t <= b for a, b in lo):
                    continue
                d = json.loads(line)
                if d.get("observable_all"):
                    self.rows[t] = d["observable_all"]
        self.t = np.array(sorted(self.rows))
        self._m = {}

    def mask(self, t):
        m = self._m.get(t)
        if m is None:
            m = self._m[t] = lighting.unpack_mask(self.rows[t])
        return m

    def at(self, t, shape):
        if not len(self.t):
            return None
        j = int(np.argmin(np.abs(self.t - t)))
        if abs(self.t[j] - t) > TV_TOL_MS:
            return None
        m = self.mask(float(self.t[j]))
        return m if m.shape == shape else None

    def union(self, t0, t1, shape):
        """Union of observable_all over stored frames with t0 <= t < t1; None when there is none."""
        sel = self.t[(self.t >= t0) & (self.t < t1)] if len(self.t) else []
        if not len(sel):
            return None
        m = np.zeros(shape, bool)
        for tt in sel:
            mm = self.mask(float(tt))
            if mm.shape == shape:
                m |= mm
        return m


def shape_sources(sid):
    """The stored `ability_shape` rows found in the session, as `ability_mask` sources (ring: disc of its r;
    beam: the segment)."""
    p = ss.sem.STORE / "events" / "ability_shape" / f"{sid}.jsonl"
    out = []
    if not p.is_file():
        return out
    for line in p.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("kind") != "shape" or not r.get("found"):
            continue
        t0 = float(r["t_ms"])
        if r.get("shape") == "beam":
            out.append({"kind": "beam", "t0": t0, "t1": t0 + SHAPE_LIFE_MS, "seg": (r["x0"], r["y0"], r["x1"], r["y1"]),
                        "x": r["x0"], "y": r["y0"], "name": r["ability"], "source": "events/ability_shape"})
        elif r.get("cx") is not None:
            out.append({"kind": "disc", "t0": t0, "t1": t0 + SHAPE_LIFE_MS, "x": r["cx"], "y": r["cy"],
                        "r": float(r["r"]), "name": r["ability"], "source": "events/ability_shape"})
    return out


def utility_mask(shape, srcs, t, sc):
    import light_causes as lc
    disc = [x for x in srcs if x["kind"] != "beam"]
    m, used = lc.ability_mask(shape, disc, t, WINDOW_MS, ABILITY_R, sc)
    names = {u["name"] for u, a in used}
    h, w = shape
    for x in srcs:
        if x["kind"] != "beam" or not (x["t0"] - WINDOW_MS <= t <= x["t1"] + WINDOW_MS):
            continue
        b = np.zeros(shape, np.uint8)
        x0, y0, x1, y1 = x["seg"]
        cv2.line(b, (int(round(x0)), int(round(y0))), (int(round(x1)), int(round(y1))), 1,
                 max(1, int(round(2 * BEAM_HALF_PX * sc))))
        m |= b > 0
        names.add(x["name"])
    return m, sorted(names)


def _origin(s, x, y, deg):
    pas = s.passable
    h, w = pas.shape
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < w and 0 <= yi < h and pas[yi, xi]:
        return float(x), float(y)
    return cone.snap_origin(pas, float(x), float(y), float(deg))


def cause_masks(s, shape, posed, L):
    """Full-widget masks from the posed team icons `[(x, y, deg)]`: `box` (reached with the baked boxes open,
    in the wedge, not by the model's cast), `wall` (in the wedge past every baked occluder), `edge` (reached,
    within EDGE_DEG outside the wedge), `range` (reached in the wedge at full range but not lit by the scene:
    the scene window's range cap), and `edge_deg` (degrees outside the nearest reaching wedge, inf if none)."""
    H = cone.CONE_HALF_ANGLE_DEG
    z = np.zeros(shape, bool)
    out = {"box": z.copy(), "wall": z.copy(), "edge": z.copy(), "range": z.copy(), "edge_deg": np.full(shape, np.inf)}
    known = s.ref.known.astype(bool)
    ob = getattr(s.inputs, "open_boxes", None)
    for x, y, deg in posed:
        o = _origin(s, x, y, deg)
        if o is None:
            continue
        ox, oy = o
        vis = cone.raycast(s.passable, ox, oy, 0.0, half_angle_deg=180.0, visible=s.floor, n_rays=ss.LIGHT_RAYS,
                           snap_px=0)
        dang, _dist = wedge(shape, ox, oy, deg, H)
        inw = dang <= H
        if ob is not None:
            vb = cone.raycast(ob, ox, oy, 0.0, half_angle_deg=180.0, visible=s.floor, n_rays=ss.LIGHT_RAYS, snap_px=0)
        else:
            vb = vis
        out["box"] |= inw & vb & ~vis
        out["wall"] |= inw & known & ~vb & ~vis
        out["edge"] |= vis & (dang > H) & (dang <= H + EDGE_DEG)
        out["range"] |= vis & inw & ~L
        out["edge_deg"] = np.where(vis & (dang > H), np.minimum(out["edge_deg"], dang - H), out["edge_deg"])
    return out


def scene_masks(scene, order, poses, shape):
    """Full-widget masks of one scene at fixed poses, computed as `RGBScene.light_stats` does: compared floor
    `comp`, predicted light `L`, the rule's lit read `lit` (lit wins by more than c_u) and its unlit read."""
    K, Wn, (L, free) = scene.stack(order, poses)
    e2 = scene._err2(K[None])[0]
    lt = scene.light
    comp = (scene.keep > 0) & (Wn > 0.5) & lt.known & ~free
    lit = e2[1] + lt.c_u < e2[0]
    x0, y0, x1, y1 = scene.win
    h, w = y1 - y0, x1 - x0

    def full(m):
        a = np.zeros(shape, bool)
        a[y0:y1, x0:x1] = m.reshape(h, w).cpu().numpy()
        return a
    return {"comp": full(comp), "L": full(L), "lit": full(lit), "unex_n": int((comp & ~L & lit).sum())}


def labelled_scenes(sess, limit):
    """The 0.5.0 labelled items rebuilt at their stored joint poses: yields `(meta, s, crop, scene, order,
    poses, posed)`; the rebuild must reproduce the stored `unexplained_n`."""
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = [dict(r, set=k) for k, rows in data["sets"].items() for r in rows
             if r.get("light") and r.get("joint") is not None]
    if limit:
        items = items[:limit]
    need = defaultdict(list)
    for r in items:
        need[r["session"]].append(float(r["t_ms"]))
    for sid, ts in need.items():
        s = sess(sid)
        tracks = ss.TrackIndex(sid, ts)
        got = dict(s.crops(sorted(set(ts))))
        for r in [r for r in items if r["session"] == sid]:
            r["_crop"] = crop = got[float(r["t_ms"])]
            sc = widget_scale(crop.shape[1])
            nb = ss.neighbourhood(s, crop, r, r["cls"], tracks, sc)
            team = ss.frame_team(s, r, sc)
            outside = ss.outside_icons(team, sc, nb["icons"])
            _src, srcm, tint = ss.scene_sources(r, sid, r["t_ms"], crop, sc)
            scene = ss.RGBScene(crop, s, nb["icons"], sc, ss.CAL, outside=outside, light_costs=ss.light_costs(sc),
                                src=srcm, tint=tint)
            jg = r.get("joint_gains") or (0.0, 0.0)
            poses = {0: (r["joint_xy"][0], r["joint_xy"][1], r["joint"], jg[0], jg[1])}
            for i, p in enumerate(r.get("neighbour_poses") or [], start=1):
                poses[i] = tuple(p)
            posed = [(p[0], p[1], p[2]) for i, p in poses.items()
                     if p is not None and nb["icons"][i]["cls"] != "enemy"]
            posed += [(o["x"], o["y"], o["deg"]) for o in outside if o.get("deg") is not None]
            meta = {"kind": "labelled", "set": r["set"], "session": sid, "t_ms": float(r["t_ms"]),
                    "stored_unexplained_n": int(r["light"]["unexplained_n"])}
            yield meta, s, crop, scene, list(r["order"]), poses, posed


def unlabelled_scenes(sess, lts, limit):
    """The calibration's construction on the certain-lit sample frames: each confident, clear team icon is a
    one-icon scene at its owner teardrop pose; the frame's other team icons are outside it."""
    n = 0
    for sid in SIDS:
        s = sess(sid)
        for t, crop in s.crops(lit_frames(s, sid, lts.get(sid, []))):
            sc = widget_scale(crop.shape[1])
            team, _dets, good = confident(s, crop, sc)
            for ic in good:
                cls = "self" if ic["role"] == "self" else "ally"
                scene_ic = [{"cls": cls, "x0": ic["x"], "y0": ic["y"]}]
                outside = ss.outside_icons(team, sc, scene_ic)
                _src, srcm, tint = ss.scene_sources(None, sid, t, crop, sc)
                scene = ss.RGBScene(crop, s, scene_ic, sc, ss.CAL, outside=outside,
                                    light_costs=ss.light_costs(sc), src=srcm, tint=tint)
                poses = {0: (ic["x"], ic["y"], ic["deg"], 0.0, 0.0)}
                posed = [(ic["x"], ic["y"], ic["deg"])] + [(o["x"], o["y"], o["deg"]) for o in outside
                                                            if o.get("deg") is not None]
                yield ({"kind": "unlabelled", "set": f"cal-{cls}", "session": sid, "t_ms": float(t)},
                       s, crop, scene, [0], poses, posed)
                n += 1
                if limit and n >= limit:
                    return


def cells(region, sig):
    """4-connected pieces of `region` with one value of the signature image `sig`."""
    out = []
    for v in np.unique(sig[region]):
        n, lab = cv2.connectedComponents((region & (sig == v)).astype(np.uint8), connectivity=4)
        out += [lab == k for k in range(1, n)]
    return out


def classify_scene(meta, s, crop, scene, order, poses, posed, tv, util_srcs):
    shape = crop.shape[:2]
    sc = scene.sc
    skey = ss._skey(sc)
    sm = scene_masks(scene, order, poses, shape)
    t = meta["t_ms"]
    comp, L, lit = sm["comp"], sm["L"], sm["lit"]
    region = comp & ~L
    U, C = region & lit, region & ~lit
    cm = cause_masks(s, shape, posed, L)
    z = np.zeros(shape, bool)
    tvm = tv.at(t, shape)
    tvm = z if tvm is None else tvm
    util, names = utility_mask(shape, util_srcs, t, sc)
    ling = tv.union(t - LINGER_S * 1000.0, t - TV_TOL_MS / 2, shape)
    ling = z if ling is None else ling
    masks = [("team_vision", tvm), ("utility", util), ("occluder", cm["box"] | cm["wall"]),
             ("edge_range", cm["edge"] | cm["range"]), ("lingering", ling)]
    sig = np.zeros(shape, np.int32)
    for b, (_n, m) in enumerate(masks):
        sig |= m.astype(np.int32) << b
    sig |= cm["box"].astype(np.int32) << 8
    sig |= cm["range"].astype(np.int32) << 9
    p0, p1 = RATES[skey]
    l1, l0 = math.log(p1 / p0), math.log((1 - p1) / (1 - p0))
    min_cell = MIN_CELL_PX * sc * sc
    coherent = np.zeros(shape, bool)
    small = np.zeros(shape, bool)
    decided_unlit = np.zeros(shape, bool)
    ccells = []
    for c in cells(region, sig):
        n = int(c.sum())
        k = int((c & lit).sum())
        if k == 0:
            continue
        if n < min_cell:
            small |= c & lit
            continue
        if k * l1 + (n - k) * l0 > 0:
            coherent |= c
            ccells.append((k, c))
        else:
            decided_unlit |= c & lit
    Uc = U & coherent
    row = {**meta, "size": int(crop.shape[1]), "skey": skey, "unexplained_n": int(U.sum()),
           "rebuild_unexplained_n": sm["unex_n"], "control_n": int(C.sum()), "region_n": int(region.sum()),
           "noise_small_n": int(small.sum()), "noise_cell_n": int(decided_unlit.sum()), "coherent_n": int(Uc.sum()),
           "utility_names": names, "tv_present": bool(tvm.any()), "linger_present": bool(ling.any())}
    left_u, left_c = Uc.copy(), C.copy()
    for name, m in masks:
        row[f"U_{name}"], row[f"C_{name}"] = int((left_u & m).sum()), int((left_c & m).sum())
        if name == "occluder":
            row["U_occluder_box"] = int((left_u & cm["box"]).sum())
        if name == "edge_range":
            row["U_edge_range_cap"] = int((left_u & cm["range"] & ~cm["edge"]).sum())
        left_u &= ~m
        left_c &= ~m
    row["U_residual"], row["C_residual"] = int(left_u.sum()), int(left_c.sum())
    for name, m in masks + [("box", cm["box"]), ("wall", cm["wall"]), ("edge", cm["edge"]), ("range", cm["range"])]:
        row[f"raw_{name}"] = [int((Uc & m).sum()), int((C & m).sum())]
    ed = cm["edge_deg"]
    row["edge_profile"] = {f"{a}-{b}": [int((region & lit & (ed > a) & (ed <= b)).sum()),
                                        int((region & (ed > a) & (ed <= b)).sum())] for a, b in EDGE_BANDS}
    decay = {}
    for N in LINGER_WINDOWS_S:
        m = tv.union(t - N * 1000.0, t - TV_TOL_MS / 2, shape)
        m = z if m is None else m
        decay[str(N)] = [int((Uc & ~tvm & m).sum()), int((Uc & ~tvm).sum()), int((C & ~tvm & m).sum()),
                         int((C & ~tvm).sum())]
    row["linger_decay"] = decay
    # the largest coherent cell's residual, for the sheet
    best = None
    for k, c in ccells:
        res = int((c & left_u).sum())
        cls = "residual" if res * 2 >= k else next((n for n, m in masks if (c & U & m).sum() * 2 >= k), "mixed")
        if best is None or k > best[0]:
            best = (k, c, cls, res)
    row["largest_cell"] = None if best is None else {"lit_n": best[0], "class": best[2], "residual_n": best[3]}
    draw = None if best is None else {"crop": crop, "cell": best[1], "L": L, "U": U, "tv": tvm, "util": util,
                                      "occ": cm["box"] | cm["wall"], "edge": cm["edge"] | cm["range"], "ling": ling,
                                      "posed": posed, "sc": sc}
    return row, draw


def _sum(rows):
    tot = lambda k: sum(r[k] for r in rows)  # noqa: E731
    U = max(tot("unexplained_n"), 1)
    Uc = max(tot("coherent_n"), 1)
    Cn = max(tot("control_n"), 1)
    out = {"scenes": len(rows), "sessions": sorted({r["session"] for r in rows}),
           "unexplained_n": tot("unexplained_n"), "region_n": tot("region_n"),
           "unexplained_share": round(tot("unexplained_n") / max(tot("region_n"), 1), 4),
           "noise_share": round((tot("noise_small_n") + tot("noise_cell_n")) / U, 4),
           "noise_small_share": round(tot("noise_small_n") / U, 4),
           "coherent_share": round(tot("coherent_n") / U, 4)}
    for name in CLASSES[1:]:
        out[f"{name}_share"] = round(tot(f"U_{name}") / U, 4)              # of all unexplained pixels
        out[f"{name}_coherent_share"] = round(tot(f"U_{name}") / Uc, 4)    # of the coherent ones
        out[f"{name}_control_share"] = round(tot(f"C_{name}") / Cn, 4)
    out["occluder_box_share"] = round(tot("U_occluder_box") / U, 4)
    out["edge_range_cap_share"] = round(tot("U_edge_range_cap") / U, 4)
    for name in ("team_vision", "utility", "occluder", "edge_range", "lingering", "box", "wall", "edge", "range"):
        u = sum(r[f"raw_{name}"][0] for r in rows) / Uc
        c = sum(r[f"raw_{name}"][1] for r in rows) / Cn
        out[f"raw_{name}_U"] = round(u, 4)
        out[f"raw_{name}_C"] = round(c, 4)
        out[f"raw_{name}_ratio"] = round(u / c, 2) if c > 0 else None
    for band in (f"{a}-{b}" for a, b in EDGE_BANDS):
        k = sum(r["edge_profile"][band][0] for r in rows)
        n = sum(r["edge_profile"][band][1] for r in rows)
        out[f"edge_lit_{band.replace('-', '_')}"] = round(k / n, 4) if n else None
    for N in LINGER_WINDOWS_S:
        a = [sum(r["linger_decay"][str(N)][j] for r in rows) for j in range(4)]
        u = a[0] / max(a[1], 1)
        c = a[2] / max(a[3], 1)
        ms = f"{int(round(N * 1000))}ms"
        out[f"linger_{ms}_U"] = round(u, 4)
        out[f"linger_{ms}_C"] = round(c, 4)
        out[f"linger_{ms}_ratio"] = round(u / c, 2) if c > 0 else None
    return out


def classify_summary(rows) -> dict:
    parts = {}
    for kind in ("labelled", "unlabelled"):
        for skey in ("0.712", "1.000"):
            rr = [r for r in rows if r["kind"] == kind and r["skey"] == skey]
            if rr:
                parts[f"{kind}@{skey}"] = _sum(rr)
        rr = [r for r in rows if r["kind"] == kind]
        if rr:
            parts[f"{kind}@pooled"] = _sum(rr)
    parts["pooled"] = _sum(rows)
    return parts


def classify(sess, lts, limit, sheet) -> dict:
    rates()
    caps = captures()
    rows, cands = [], []
    util = {}
    tvs = {}
    import light_causes as lc

    def prep(sid, times):
        if sid not in tvs:
            tvs[sid] = TVIndex(sid, times, max(LINGER_WINDOWS_S) * 1000.0)
            util[sid] = lc.ability_sources(sid) + shape_sources(sid)

    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    lab_t = defaultdict(list)
    for rr in data["sets"].values():
        for r in rr:
            lab_t[r["session"]].append(float(r["t_ms"]))
    for sid in SIDS:
        s = sess(sid)
        prep(sid, sorted(set(lab_t.get(sid, []) + lit_frames(s, sid, lts.get(sid, [])))))
    bad = []
    for gen in (labelled_scenes(sess, limit), unlabelled_scenes(sess, lts, limit)):
        for meta, s, crop, scene, order, poses, posed in gen:
            if scene.light is None:
                continue
            sid = meta["session"]
            row, draw = classify_scene(meta, s, crop, scene, order, poses, posed, tvs[sid], util[sid])
            if meta["kind"] == "labelled" and row["rebuild_unexplained_n"] != meta["stored_unexplained_n"]:
                bad.append((sid, meta["t_ms"], meta["stored_unexplained_n"], row["rebuild_unexplained_n"]))
            rows.append(row)
            if draw is not None:
                cands.append((row["largest_cell"]["lit_n"], row, draw))
                cands.sort(key=lambda c: -c[0])
                del cands[40:]
            if len(rows) % 20 == 0:
                print(f"  classify {len(rows)} scenes", flush=True)
    for b in bad:
        print("NOT REPRODUCED", b)
    parts = classify_summary(rows)
    picked, per = [], defaultdict(int)
    for _k, row, draw in cands:
        if per[row["session"]] >= SHEETS_PER_SESSION:
            continue
        per[row["session"]] += 1
        picked.append((row, draw))
        if len(picked) >= N_SHEETS:
            break
    paths = []
    if sheet:
        for i, (row, draw) in enumerate(picked, 1):
            p = OUT / f"sheet_{i:02d}_{row['session']}_{int(row['t_ms'])}.png"
            cv2.imwrite(str(p), render(row, draw, caps[row["session"]]))
            paths.append(str(p).replace("\\", "/"))
            row["sheet"] = paths[-1]
    return {"version": VERSION, "not_reproduced": bad, "summary": parts, "rows": rows, "sheets": paths,
            "sheet_rule": (f"the {N_SHEETS} scenes whose largest coherent unexplained cell is biggest, at most "
                           f"{SHEETS_PER_SESSION} per session")}


def _outline(img, m, z, col):
    big = cv2.resize(m.astype(np.uint8), None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    cnts, _ = cv2.findContours(big, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, col, 1)


def render(row, draw, capture):
    """Native crop, a x4 zoom round the largest coherent unexplained cell raw and with overlays, and a caption."""
    crop, cell, sc = draw["crop"], draw["cell"], draw["sc"]
    h, w = crop.shape[:2]
    ys, xs = np.nonzero(cell)
    cx, cy = int(xs.mean()), int(ys.mean())
    R = 45
    x0, x1 = max(0, cx - R), min(w, cx + R)
    y0, y1 = max(0, cy - R), min(h, cy + R)
    Z = 4
    raw = cv2.resize(crop[y0:y1, x0:x1], None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
    ov = raw.copy()
    sub = lambda m: m[y0:y1, x0:x1]  # noqa: E731
    uc = cv2.resize((sub(draw["U"]) & sub(cell)).astype(np.uint8), None, fx=Z, fy=Z,
                    interpolation=cv2.INTER_NEAREST) > 0
    ov[uc] = (0.45 * ov[uc] + 0.55 * np.array([0, 0, 255])).astype(np.uint8)
    for m, col in ((draw["L"], (0, 255, 0)), (draw["tv"], (255, 255, 0)), (draw["util"], (255, 0, 255)),
                   (draw["occ"], (0, 255, 255)), (draw["edge"], (0, 140, 255)), (draw["ling"], (180, 105, 255)),
                   (cell, (255, 255, 255))):
        _outline(ov, sub(m), Z, col)
    nat = crop.copy()
    for x, y, deg in draw["posed"]:
        cv2.line(nat, (int(x), int(y)), (int(x + 14 * sc * math.cos(math.radians(deg))),
                                         int(y + 14 * sc * math.sin(math.radians(deg)))), (0, 255, 0), 1)
    cv2.rectangle(nat, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 255), 1)
    Hh = max(nat.shape[0], raw.shape[0])
    pad = lambda im: cv2.copyMakeBorder(im, 0, Hh - im.shape[0], 0, 6, cv2.BORDER_CONSTANT,  # noqa: E731
                                        value=(40, 40, 40))
    body = np.hstack([pad(nat), pad(raw), pad(ov)])
    lc_ = row["largest_cell"]
    lines = [f"t = {row['t_ms'] / 1000:.3f} s   session {row['session']}   {row['size']} px   {row['set']}",
             capture,
             f"largest coherent unexplained cell: {lc_['lit_n']} lit px, class {lc_['class']} "
             f"(residual {lc_['residual_n']})   utility: {', '.join(row['utility_names']) or 'none stored'}",
             "red: unexplained lit in the cell  white: cell  green: predicted light  cyan: team_vision",
             "magenta: stored utility  yellow: occluder (box/wall)  orange: edge/range  pink: team_vision last 1 s"]
    cap = np.full((30 * len(lines) + 12, body.shape[1], 3), 255, np.uint8)
    for i, ln in enumerate(lines):
        cv2.putText(cap, ln, (8, 28 + 30 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.75 if i < 2 else 0.6, (0, 0, 0),
                    2 if i == 0 else 1, cv2.LINE_AA)
    return np.vstack([cap, body])


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--instrument", action="store_true")
    ap.add_argument("--lag", action="store_true")
    ap.add_argument("--classify", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reuse", action="store_true", help="re-summarise and record the stored instrument/lag/classify rows; no measurement")
    args = ap.parse_args(argv)
    setup()
    sess = ff._sessions()
    lts = label_times()
    OUT.mkdir(parents=True, exist_ok=True)
    from reticle import metrics
    deps = {"prototype": VERSION, "scene_stack": ss.VERSION, "items": str(ITEMS),
            "light_cal": str(ss.LIGHT_CAL_PATH), "tint_cal": str(ss.OUT / ss.TINT_CAL_NAME)}
    if args.instrument:
        if args.reuse and (OUT / "instrument.json").is_file():
            got = json.loads((OUT / "instrument.json").read_text(encoding="utf-8"))
        else:
            got = instrument(sess, lts)
        (OUT / "instrument.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
        for k, v in got.items():
            print(k, {a: b for a, b in v.items() if a != "worst_regions"})
        if args.record:
            d = dict(deps, roundstart_offs_s=list(ROUNDSTART_OFFS_S), unlit_away_px=UNLIT_AWAY_PX,
                     core_in_deg=CORE_IN_DEG, core_r=list(CORE_R), lit_frames=LIT_FRAMES, seed=SEED)
            for k, v in got.items():
                vals = {a: b for a, b in v.items() if a not in ("worst_regions", "sessions")}
                metrics.record(SERIES, part=f"instrument-{k.replace('@', '-')}", session="+".join(v["sessions"]), values=vals, deps=d)
            print("recorded instrument")
    if args.lag:
        if args.reuse and (OUT / "lag.json").is_file():
            got = json.loads((OUT / "lag.json").read_text(encoding="utf-8"))
            got["summary"] = lag_summary(got["rows"])
        else:
            got = lag(sess, lts)
        (OUT / "lag.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
        for k, v in got["summary"].items():
            print(k, v)
        if args.record:
            d = dict(deps, lag_offs=list(LAG_OFFS), turn_deg=LAG_TURN_DEG, shift_px=LAG_SHIFT_PX, seed=SEED)
            for k, v in got["summary"].items():
                vals = {a: b for a, b in v.items() if a != "sessions"}
                metrics.record(SERIES, part=f"lag-{k.replace('@', '-')}", session="+".join(v["sessions"]), values=vals, deps=d)
            print("recorded lag")
    if args.classify:
        if args.reuse and (OUT / "classify.json").is_file():
            got = json.loads((OUT / "classify.json").read_text(encoding="utf-8"))
            got["summary"] = classify_summary(got["rows"])
            rates()
        else:
            got = classify(sess, lts, args.limit, args.sheet)
        (OUT / "classify.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
        for k, v in got["summary"].items():
            print(k, json.dumps(v))
        if args.record and not args.limit:
            d = dict(deps, classes=list(CLASSES), min_cell_px=MIN_CELL_PX, tv_tol_ms=TV_TOL_MS, window_ms=WINDOW_MS,
                     ability_r=ABILITY_R, beam_half_px=BEAM_HALF_PX, edge_deg=EDGE_DEG, linger_s=LINGER_S,
                     seed=SEED, instrument_rates=RATES)
            for k, v in got["summary"].items():
                vals = {a: b for a, b in v.items() if a != "sessions"}
                metrics.record(SERIES, part=f"classify-{k.replace('@', '-')}", session="+".join(v["sessions"]), values=vals, deps=d)
            print("recorded classify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
