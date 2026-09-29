r"""Decompose team vision's error against the drawn light, pixel by pixel, by cause.

    .\.venv\Scripts\python.exe prototypes\team_vision_errors.py [--sessions SID ...] [--record]
    .\.venv\Scripts\python.exe prototypes\team_vision_errors.py --peek SID

E7 of [the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md). The
player's direction of 2026-09-29: team vision is a team signal, so the whole
team's joined cones must explain the lit area, not the self cone alone. This
scores the stored `team_vision` product (`observable`, the union of the
eligible cones) against the drawn light and gives every disagreeing pixel one
cause, by ordered rules fixed before the run.

**Two arms, both stored.** `prod` is the product, `observable`: the union of
the cones the lifecycle calls eligible. `any` is `observable_all`, every
stored bearing with the lifecycle gate off. Each frame's cones are recast
from its stored icons (`cone.raycast` at the stored origin and facing: the
self icon's `self_cone` origin, every other icon's `x`, `y`), and their union
must equal the stored mask; the mismatch is counted, as a check of the
instrument.

**The witnesses.** `lighting.raw_lit` on known floor, outside every team
icon's own pixels (the teardrop rendered at its fit, grown by
`cone_origin.PAD`; a disc where no facing reads):

    all     the team's joined light (below), plus every other lit component
            that survives the owner's speckle filter (`lighting.clean_lit`):
            the raw decision's per-pixel noise and the map's static glyphs
            would otherwise fill cause f
    team    the lit components (8-connected) that touch a band of
            `cone_origin.JOIN_PX` round any team icon: E4's joined light,
            joined to the whole team instead of the self icon
    self    E4's own witness (`cone_origin.joined` within 90 px of the self
            teardrop), to reproduce E5's self-only figures on stored rows

**The causes**, first rule wins; FP is a cast pixel the light leaves dark, FN
a lit pixel no cast cone covers. Scored against `all`:

    a  geometry     within EDGE_PX of an impassable pixel (wall or box edge)
                    that touches a cast cone: a line the cone stops at
    b  smoke        FP: in a cast cone but not in the cone recast with the live
                    smoke discs as walls (inside or behind the disc);
                    FN: inside a live disc
    c  ally facing  the ally's ring-fit facing is over BAD_FACING_DEG from its
                    teardrop's (`icon_teardrop.fit`): FP in its stored cone,
                    FN in the cone cast from its teardrop
    d  angle edge   FP: in the cast cones but not in the cones narrowed by
                    EDGE_DEG; FN: in the cones widened by EDGE_DEG
    e  uncast icon  FN only: the lit component touches a team icon that cast
                    no cone this frame, split in this order: `ineligible` (a
                    bearing the lifecycle quarantined; `prod` only),
                    `no_facing` (the track refused the bearing), `untracked`
                    (a detection no stored icon explains)
    f  no caster    FN only: the lit component touches no team icon
    g  other

Smoke discs are the stored `smoke` tracks (`adjudication.smokes`) where the
session has them; elsewhere this computes `minimap_dark` rows with the
owner's reader over the crop cache at 4 Hz, round each scored window, and
asks `adjudication.smokes.tracks` for the tracks, in memory. A track's birth
radius comes from a hatched component's area and sits 1-5 px inside the
drawn disc, so each frame measures the disc's edge (`smoke_radius`, the
owner's `grey_dark` test on rings outward from the birth radius). Ally teardrops
at other widget sizes scale the class's radii by `minimap.widget_scale`,
which E6 recommended and no label has checked.

**Fixes**, each alone, recast and rescored: allies from their teardrops, smoke
discs as walls, every box edge passable, only the box-edge pixels beside
missed light passable (an oracle: it reads the witness, so it bounds doorways
from above), the half-angle 4 degrees either way, uncast icons cast from
their teardrops, the lifecycle gate off (`prod` only), and each cone turned by
up to 40 degrees to the light (an oracle, like the doorways). A fix's gain is
the error pixels it removes, net, and its change in F1.

**Diagnostics inside g** (FP only, not causes): the self cone cast along a
teardrop facing over SELF_FLIP_DEG from the track's own bearing, and frames
whose cast cones find under 5% of their pixels lit ("cones cast, no light").

**The instrument.** Cause-f light found on at least `STATIC_FRAC` of a
session's scored frames is counted apart: it is the map's own drawing (a site
glyph) that the lighting reference reads as lit. It is reported, not removed;
the witness takes no per-session map value.

Uncertainty is a bootstrap over windows (E4's twenty 6 s windows; 3 s blocks
on e78e75b2d191, E4's held-out half). It reads the crop cache and stored rows
only, decodes no video, and writes to the store only with `--record` (one
`metrics` row) and the sheets under `analysis/`.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402
import cone_origin as co  # noqa: E402
import teardrop_tip as tt  # noqa: E402
import icon_teardrop as itd  # noqa: E402
from reticle import cone, geometry, lighting, metrics, minimap, team_vision  # noqa: E402
from reticle.adjudication import smokes as smokes_adj  # noqa: E402
from reticle.menu import MenuWitness  # noqa: E402
from reticle.minimap import BOXEDGE  # noqa: E402
from reticle.minimap_dark import DarkRegionReader, grey_dark  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache, grid_times  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.teardrop import SelfConeReader  # noqa: E402

VERSION = "team-vision-errors-0.1.0"
STORE = sem.STORE
SESSIONS = ("e78e75b2d191", "5822b6646448", "c40d950031bb")
TAGS = {"e78e75b2d191": "e78e", "5822b6646448": "lotus", "c40d950031bb": "c40d"}
EDGE_PX = 2.0
EDGE_DEG = 4.0
BAD_FACING_DEG = 45.0
MATCH_PX = 6.0            # a detection within this (scaled) of a casting icon is that icon
SMOKE_PAD_PX = 1.0        # a disc's wall reaches this past its measured edge
SMOKE_EDGE_SHARE = 0.5    # a ring with less grey dark than this lies outside the disc
SMOKE_MAX_GROW = 6.0      # the edge is sought at most this far past the birth radius
SELF_FLIP_DEG = 90.0      # a self teardrop facing this far from the track's bearing
ORACLE_STEPS = (-40.0, -30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0, 40.0)   # facing oracle, deg
SMOKE_LEAD_MS = 25000.0   # dark rows read before each window, so a smoke's birth is seen
N_BOOT = 1000
STATIC_FRAC = 0.5         # cause-f light on at least this share of frames is the map's drawing
CAUSES = ("a", "b", "c", "d", "e", "f", "g")
CAUSE_NAMES = {"a": "geometry at pixel scale", "b": "smoke not modelled",
               "c": "ally ring-fit facing", "d": "cone angular edge",
               "e": "icon uncast", "f": "no plausible caster", "g": "other"}
FIXES = ("ally_teardrop", "smoke_walls", "boxedge_open", "doorway_oracle", "half_minus4",
         "half_plus4", "cast_uncast")
HALF = cone.CONE_HALF_ANGLE_DEG


def idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)      # IDLE_PRIORITY_CLASS
    except Exception:
        pass
    cv2.setNumThreads(1)


def angdiff(a, b) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


class Sess:
    """Baked geometry, the crop cache, and the stored rows for one session."""

    def __init__(self, sid: str, times_wanted=None):
        self.sid = sid
        man = geometry.manifest(sid, STORE)
        self.capture = man["source"]["path"]
        prof = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        self.inputs, why = team_vision.load_inputs(STORE, sid, prof, w, h)
        if self.inputs is None or self.inputs.light is None:
            raise SystemExit(f"{sid}: no team-vision inputs ({why})")
        self.box = self.inputs.box
        self.floor, self.passable, self.ref = self.inputs.floor, self.inputs.passable, self.inputs.light
        with np.load(geometry.path_of(sid, STORE)) as z:
            self.labels = z["labels"].copy()
        self.boxedge = self.labels == BOXEDGE
        self.width = self.box[2] - self.box[0]
        self.sc = minimap.widget_scale(self.width)
        self.cache, why = RoiCache.load(STORE, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))
        st = Store(STORE)
        self.menu = MenuWitness(st.read_events("menu_open", sid)) if \
            st.events_path("menu_open", sid).is_file() else None
        self.vision, self.vision_version = {}, None
        want = None if times_wanted is None else {float(t) for t in times_wanted}
        with open(st.events_path("team_vision", sid), encoding="utf-8") as f:
            for ln in f:
                if '"kind":"frame"' not in ln[:200]:
                    if '"kind":"coverage"' in ln[:200]:
                        self.vision_version = json.loads(ln).get("team_vision_version")
                    continue
                r = json.loads(ln)
                if want is None or float(r["t_ms"]) in want:
                    self.vision[float(r["t_ms"])] = r
        yy, xx = np.mgrid[0:self.passable.shape[0], 0:self.passable.shape[1]]
        self.yy, self.xx = yy.astype(np.float32), xx.astype(np.float32)
        self.smokes, self.smoke_source = [], None

    def crops(self, times):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples([float(t) for t in times], rois=["minimap"]):
            yield smp.t_ms, smp.frame[y0:y1, x0:x1]

    def load_smokes(self, plan) -> None:
        """Smoke tracks: the stored ones, else the owners' rules run in memory."""
        st = Store(STORE)
        rows = [r for r in st.read_events("smoke", self.sid) if r.get("kind") == "track"]
        if st.events_path("smoke", self.sid).is_file():
            self.smokes, self.smoke_source = rows, "stored smoke rows"
            return
        spans = []
        for w in sorted({w for w, _t in plan}):
            ts = [t for ww, t in plan if ww == w]
            a, b = min(ts) - SMOKE_LEAD_MS, max(ts)
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        times = [t for a, b in spans for t in grid_times(self.cache_t, a, b, 0.25)]
        rd = DarkRegionReader(self.floor, self.inputs.sgray, self.inputs.static, self.ref,
                              self.box, hz=4.0)
        for smp in self.cache.samples(times, rois=["minimap"]):
            rd.feed(smp)
        dark = rd.events(self.sid, self.inputs.geometry_key)
        menu = self.menu.at if self.menu is not None else None
        self.smokes = smokes_adj.tracks(dark, self.ref.known, menu=menu)
        self.smoke_source = f"minimap_dark rows computed from the crop cache ({len(times)} frames)"

    def live_smokes(self, t: float):
        return [s for s in self.smokes if s["first_ms"] <= t <= s["last_ms"]]

    def disc(self, x, y, r):
        return (self.xx - x) ** 2 + (self.yy - y) ** 2 <= r * r

    def footprint(self, x, y, deg, cls="self"):
        """An icon's own pixels: its teardrop grown by PAD, or a disc without a facing."""
        c = itd.CLASSES[cls]
        if deg is None:
            return self.disc(x, y, (c.L + co.PAD) * self.sc)
        m = tt.render(self.xx - x, self.yy - y, math.radians(deg), r_in=0.0,
                      r_out=(c.r_out + co.PAD) * self.sc, L_=(c.L + co.PAD) * self.sc, edge=1.0)
        return m > 0


class _Times:
    def __init__(self, sid, cache_t):
        self.sid, self.cache_t = sid, cache_t


def cache_times(sid: str) -> _Times:
    """The crop cache's times alone, to plan frames before reading any row."""
    man = geometry.manifest(sid, STORE)
    cache, _ = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")
    return _Times(sid, np.unique(np.asarray(cache.t_ms, dtype=float)))


def plan_of(s, step: int):
    """`[(window, t)]`: E4's held-out 3 s blocks on the demo, else E4's twenty windows."""
    if s.sid == sem.DEMO:
        return [(int(t // co.BLOCK_MS), float(t)) for t in s.cache_t
                if (t // co.BLOCK_MS) % 2 == 1 and all(abs(t - h) > sem.HOLDOUT_MS for h in sem.SLIVERS)]
    return [(w, float(t)) for w, sel in co.windows(s) for t in sel[::step]]


def ally_fit(s: Sess, crop, key, x, y):
    c = itd.CLASSES["ally"]
    return itd.fit(None, "ally", x, y, key=key, r_in=c.r_in * s.sc, r_out=c.r_out * s.sc,
                   L_=c.L * s.sc)


def components_touching(lit, band):
    """The 8-connected components of `lit` that touch `band`."""
    n, lab = cv2.connectedComponents(lit.astype(np.uint8), connectivity=8)
    keep = np.unique(lab[band & lit])
    keep = keep[keep > 0]
    return np.isin(lab, keep) if len(keep) else np.zeros(lit.shape, bool)


def dilate(m, px):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(px) + 1,) * 2)
    return cv2.dilate(m.astype(np.uint8), k) > 0


def counts(pred, wit):
    tp = int((pred & wit).sum())
    return tp, int(pred.sum()) - tp, int(wit.sum()) - tp


ARMS = ("prod", "any")
E_SUB = ("ineligible", "no_facing", "untracked")


def smoke_radius(s: Sess, gd, sm) -> float:
    """The disc's drawn radius this frame: the first 1 px ring at or past the
    track's birth radius whose grey-dark share (`minimap_dark.grey_dark`, the
    owner's test) falls under SMOKE_EDGE_SHARE, at most SMOKE_MAX_GROW px out.

    The birth radius comes from the area of a hatched component and sits 1-5 px
    inside the drawn edge on the discs inspected; a ray must stop at the edge.
    """
    d = np.hypot(s.xx - sm["cx"], s.yy - sm["cy"])
    r = float(sm["r"])
    k = s.ref.known
    for step in np.arange(0.0, SMOKE_MAX_GROW + 0.01, 1.0):
        ring = (d >= r + step) & (d < r + step + 1.0) & k
        if not ring.any() or gd[ring].mean() < SMOKE_EDGE_SHARE:
            return r + step + SMOKE_PAD_PX
    return r + SMOKE_MAX_GROW + SMOKE_PAD_PX


def icons_of(row):
    """The stored icons: cone origin, facing, and why the product casts no cone.

    `why` is None for a cone in the product; `ineligible` where the lifecycle
    quarantined a bearing (`casts` false with a facing); `no_facing` where the
    track refused the bearing.
    """
    out, self_tf = [], None
    for ic in row.get("icons") or []:
        ox, oy = ic["x"], ic["y"]
        sc_ = ic.get("self_cone") if ic["role"] == "self" else None
        if sc_ is not None:
            ox, oy = sc_["x"], sc_["y"]
            if sc_.get("origin") == "teardrop":
                self_tf = {"x": sc_["x"], "y": sc_["y"], "deg": sc_["deg"]}
        why = None if ic["casts"] else ("no_facing" if ic["facing"] is None else "ineligible")
        flip = bool(sc_ is not None and sc_.get("facing") == "teardrop"
                    and sc_.get("track_deg") is not None and ic["facing"] is not None
                    and angdiff(ic["facing"], sc_["track_deg"]) > SELF_FLIP_DEG)
        out.append({"role": ic["role"], "x": ic["x"], "y": ic["y"], "ox": ox, "oy": oy,
                    "deg": ic["facing"], "why": why, "carried": bool(ic["interpolated"]),
                    "self_flip": flip})
    return out, self_tf


def frame_errors(s: Sess, t: float, crop, row, keep=False) -> dict:
    """One frame: scores, the error by cause, and each fix's rescore, for both arms.

    `prod` is the stored product (`observable`, eligible cones only); `any`
    casts every stored bearing (`observable_all`, the lifecycle gate off).
    """
    shape = s.passable.shape
    menu = s.menu.at(t) if s.menu is not None else None
    out = {"t": t, "widget": row["widget"], "frames": 1, "menu_open": int(menu is True)}
    icons, self_tf = icons_of(row)

    # Icons on the widget: stored ones, and detections no stored icon explains.
    key = itd.CLASSES["ally"].key(crop)
    allies = minimap.ally_icons(crop, s.floor, require_facing=False, support=s.inputs.slab,
                                static=s.inputs.static)
    selves = minimap.self_icons(crop, s.floor, require_facing=False, support=s.inputs.slab)
    for c in icons:
        if c["role"] == "ally":
            f = ally_fit(s, crop, key, c["x"], c["y"])
            c["td"] = f if f.get("read") else None
            c["fp"] = s.footprint(f["x"], f["y"], f["deg"], "ally") if f.get("read") else \
                s.footprint(c["x"], c["y"], None, "ally")
        else:
            c["td"] = None
            c["fp"] = s.footprint(self_tf["x"], self_tf["y"], self_tf["deg"]) if self_tf else \
                s.footprint(c["x"], c["y"], None)
    known_xy = [(c["x"], c["y"]) for c in icons]
    scr = SelfConeReader(scale=s.sc)
    for cls, dets in (("ally", allies), ("self", selves)):
        for d in dets:
            if any(math.hypot(d["cx"] - x, d["cy"] - y) <= MATCH_PX * s.sc for x, y in known_xy):
                continue
            if cls == "ally":
                f = ally_fit(s, crop, key, d["cx"], d["cy"])
                deg = f["deg"] if f.get("read") else None
                x, y = (f["x"], f["y"]) if f.get("read") else (d["cx"], d["cy"])
            else:
                r = scr.read(crop, d["cx"], d["cy"])
                x, y, deg = r["x"], r["y"], r["deg"]
            icons.append({"role": cls, "x": x, "y": y, "ox": x, "oy": y, "deg": None,
                          "td_deg": deg, "why": "untracked", "carried": False, "td": None,
                          "fp": s.footprint(x, y, deg, cls)})
            known_xy.append((d["cx"], d["cy"]))
    foot = cone.union([c["fp"] for c in icons], shape)
    band_all = dilate(foot, co.JOIN_PX)
    region = s.ref.known & s.floor & ~foot
    raw = lighting.raw_lit(crop, s.ref)
    W_raw = raw & region
    joined = components_touching(W_raw, band_all)
    W_team = W_raw & joined
    # Raw light joined to a team icon is E4's witness; light joined to none
    # must also pass the owner's speckle filter (`lighting.clean_lit`), or the
    # raw decision's per-pixel noise would fill cause f.
    W_all = W_team | (lighting.clean_lit(raw, s.ref) & region)
    out["lit_all"], out["lit_team"] = int(W_all.sum()), int(W_team.sum())
    out["why"] = [c["why"] for c in icons]
    out["why_n"] = {}
    for c in icons:
        k = c["why"] or "cast"
        out["why_n"][k] = out["why_n"].get(k, 0) + 1

    # Every cone each icon could cast, once.
    live = s.live_smokes(t)
    wall = np.zeros(shape, bool)
    gd = grey_dark(crop, s.ref) if live else None
    out["smoke_discs"], out["smoke_r_gain"] = len(live), 0.0
    for sm in live:
        r = smoke_radius(s, gd, sm)
        out["smoke_r_gain"] += r - sm["r"]
        wall |= s.disc(sm["cx"], sm["cy"], r)
    out["smoke_frames"] = int(bool(live))
    zero = np.zeros(shape, bool)
    for c in icons:
        if c["deg"] is None:
            continue
        a = (c["ox"], c["oy"], c["deg"])
        c["cone"] = cone.raycast(s.passable, *a, HALF, s.floor)
        c["narrow"] = cone.raycast(s.passable, *a, HALF - EDGE_DEG, s.floor)
        c["wide"] = cone.raycast(s.passable, *a, HALF + EDGE_DEG, s.floor)
        c["open"] = cone.raycast(s.passable | s.boxedge, *a, HALF, s.floor)
        c["smoke"] = cone.raycast(s.passable & ~wall, *a, HALF, s.floor & ~wall) if live else c["cone"]
        f = c["td"]
        if f is not None:
            c["td_cone"] = cone.raycast(s.passable, f["x"], f["y"], f["deg"], HALF, s.floor)
            c["bad"] = angdiff(c["deg"], f["deg"]) > BAD_FACING_DEG
        else:
            c["td_cone"], c["bad"] = c["cone"], False
    # An uncast icon's cone, where a teardrop gives it a facing.
    for c in icons:
        if c["deg"] is not None:
            continue
        f, deg = c["td"], c.get("td_deg")
        c["cast_td"] = (cone.raycast(s.passable, f["x"], f["y"], f["deg"], HALF, s.floor)
                        if f is not None else
                        cone.raycast(s.passable, c["ox"], c["oy"], deg, HALF, s.floor)
                        if deg is not None else zero)

    stored = {"prod": lighting.unpack_mask(row["observable"]),
              "any": lighting.unpack_mask(row["observable_all"])}
    red = itd.redness(crop) > 0.3
    sat = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1] > 120
    allies_cast = [c for c in icons if c["role"] == "ally" and c["why"] is None]
    out["allies_cast"] = len(allies_cast)
    out["allies_td_read"] = sum(1 for c in allies_cast if c["td"] is not None)
    out["allies_bad"] = sum(1 for c in allies_cast if c["bad"])

    # E5's self witness, where E5 would have scored the frame.
    det = tt.self_start(crop, s.floor)
    tf = tt.fit(crop, det["cx"], det["cy"]) if det else None
    e5wit = None
    if tf and tf.get("read"):
        reg = co.region_of(s, tf)
        wit = co.joined(raw, reg, tf)
        if int(wit.sum()) >= co.MIN_LIT:
            e5wit = (reg, wit)

    masks = {}
    for arm in ARMS:
        casting = [c for c in icons if c["deg"] is not None and (arm == "any" or c["why"] is None)]
        uncast = [c for c in icons if c not in casting]
        o = {}
        P0 = cone.union([c["cone"] for c in casting], shape)
        o["mask_mismatch_px"] = int((P0 ^ stored[arm]).sum())
        P = P0 & region
        selfs = [c for c in casting if c["role"] == "self"]
        S = cone.union([c["cone"] for c in selfs], shape) & region
        o["team_all"], o["team_team"] = counts(P, W_all), counts(P, W_team)
        o["self_all"], o["self_team"] = counts(S, W_all), counts(S, W_team)
        o["self_frames"] = int(bool(selfs))
        if e5wit is not None:
            reg, wit = e5wit
            ms = cone.union([c["cone"] for c in selfs], shape)
            o["e5"] = [int((ms & wit).sum()), int((ms & reg).sum()), int(wit.sum()), 1]
            o["e5_cast"] = o["e5"] if selfs else [0, 0, 0, 0]
        else:
            o["e5"] = o["e5_cast"] = [0, 0, 0, 0]

        FP, FN = P & ~W_all, W_all & ~P
        line = ~s.passable & dilate(P0, 1)
        near = (cv2.distanceTransform((~line).astype(np.uint8), cv2.DIST_L2, 3) <= EDGE_PX) \
            if line.any() else zero
        Psm = cone.union([c["smoke"] for c in casting], shape) & region
        b_fp, b_fn = (P & ~Psm, wall) if live else (zero, zero)
        bad = [c for c in casting if c["bad"]]
        c_fp = cone.union([c["cone"] for c in bad], shape)
        c_fn = cone.union([c["td_cone"] for c in bad], shape)
        narrow = cone.union([c["narrow"] for c in casting], shape) & region
        wide = cone.union([c["wide"] for c in casting], shape) & region
        d_fp, d_fn = P & ~narrow, wide & ~P
        e_by = {}
        for why in E_SUB:
            fps_ = [c["fp"] for c in uncast if c["why"] == why]
            e_by[why] = components_touching(W_raw, dilate(cone.union(fps_, shape), co.JOIN_PX)) \
                if fps_ else zero
        f_fn = W_all & ~joined
        rest_fp, rest_fn = FP.copy(), FN.copy()
        fp_by, fn_by, e_sub, by = {}, {}, {}, {}
        rules = {"a": (near, near), "b": (b_fp, b_fn), "c": (c_fp, c_fn), "d": (d_fp, d_fn),
                 "f": (zero, f_fn)}
        for k in CAUSES[:-1]:
            if k == "e":
                hit_fn = zero.copy()
                for why in E_SUB:
                    h = rest_fn & e_by[why] & ~hit_fn
                    e_sub[why] = int(h.sum())
                    hit_fn |= h
                hit_fp = zero
            else:
                mf, mn = rules[k]
                hit_fp, hit_fn = rest_fp & mf, rest_fn & mn
            fp_by[k], fn_by[k] = int(hit_fp.sum()), int(hit_fn.sum())
            rest_fp &= ~hit_fp
            rest_fn &= ~hit_fn
            by[k] = (hit_fp, hit_fn)
        fp_by["g"], fn_by["g"] = int(rest_fp.sum()), int(rest_fn.sum())
        by["g"] = (rest_fp, rest_fn)
        # Diagnostic inside g: the self cone cast along a teardrop facing that
        # disagrees with the track's own bearing (a teardrop misread or a turn).
        flips = [c["cone"] for c in casting if c.get("self_flip")]
        o["g_self_flip_fp"] = int((rest_fp & cone.union(flips, shape)).sum()) if flips else 0
        o["g_dark_fp"] = int(rest_fp.sum()) if (FP.sum() > 300 and (P & W_all).sum() < 0.05 * P.sum()) else 0
        o["fp_by"], o["fn_by"], o["e_sub"] = fp_by, fn_by, e_sub
        o["fp_red"], o["fn_sat"] = int((FP & red).sum()), int((FN & sat).sum())
        o["dark"] = int(FP.sum() > 300 and (P & W_all).sum() < 0.05 * P.sum())
        o["dark_fp"] = int(FP.sum()) if o["dark"] else 0

        fix = {}
        fix["ally_teardrop"] = cone.union([c["td_cone"] for c in casting], shape) & region
        fix["smoke_walls"] = Psm
        fix["boxedge_open"] = cone.union([c["open"] for c in casting], shape) & region
        # An oracle bound: open only the box-edge pixels beside missed light. It
        # reads the witness, so it bounds what doorways could remove from above.
        door = s.boxedge & dilate(FN, EDGE_PX)
        fix["doorway_oracle"] = cone.union([cone.raycast(s.passable | door, c["ox"], c["oy"], c["deg"],
                                                     HALF, s.floor) for c in casting],
                                      shape) & region if door.any() else P
        fix["half_minus4"], fix["half_plus4"] = narrow, wide
        # An oracle bound on facing: each cone turned by up to ORACLE_DEG to the
        # rotation whose own cone best matches the light (hits less false lit).
        best = []
        for c in casting:
            top, top_m = None, c["cone"]
            for dd in ORACLE_STEPS:
                m = c["cone"] if dd == 0 else cone.raycast(s.passable, c["ox"], c["oy"],
                                                           c["deg"] + dd, HALF, s.floor)
                mr = m & region
                sc_ = int((mr & W_all).sum()) - int((mr & ~W_all).sum())
                if top is None or sc_ > top:
                    top, top_m = sc_, m
            best.append(top_m)
        fix["facing_oracle"] = cone.union(best, shape) & region
        fix["cast_uncast"] = (P0 | cone.union([c["cast_td"] for c in uncast if c["deg"] is None],
                                          shape)) & region
        if arm == "prod":
            fix["lifecycle_off"] = stored["any"] & region
        o["fix"] = {k: counts(m, W_all) for k, m in fix.items()}
        if arm == "prod":
            out["_f"] = f_fn & FN
        out[arm] = o
        masks[arm] = {"P": P, "by": by, "casting": casting, "uncast": uncast, "bad": bad}
    if keep:
        m = masks["prod"]
        out["_m"] = {"P": m["P"], "W_all": W_all, "W_team": W_team, "wall": wall,
                     "casters": m["casting"], "uncast": m["uncast"],
                     "bad": [{"x": c["x"], "y": c["y"], "td": c["td"]["deg"]} for c in m["bad"]],
                     "by": m["by"], "crop": crop, "live": live, "any": masks["any"]}
    return out


def _log(msg):
    print(msg, flush=True)


def score_session(sid: str, step: int, log=_log) -> dict:
    t0 = time.time()
    plan = plan_of(cache_times(sid), step)
    s = Sess(sid, times_wanted=[t for _w, t in plan])
    s.load_smokes(plan)
    log(f"{sid}: {len(plan)} frames planned, {len(s.smokes)} smoke tracks ({s.smoke_source}), "
        f"vision {s.vision_version}, width {s.width}")
    win = dict((t, w) for w, t in plan)
    rows, skipped = [], {}
    f_count = np.zeros(s.passable.shape, np.int32)
    for t, crop in s.crops([t for _w, t in plan]):
        row = s.vision.get(float(t))
        if row is None:
            skipped["no_row"] = skipped.get("no_row", 0) + 1
            continue
        if row["widget"] != "drawn" or row.get("observable") is None:
            skipped["widget_" + row["widget"]] = skipped.get("widget_" + row["widget"], 0) + 1
            continue
        r = frame_errors(s, float(t), crop, row)
        f_count += r.pop("_f")
        r["w"] = win[float(t)]
        rows.append(r)
        if len(rows) % 100 == 0:
            log(f"  {sid}: {len(rows)} frames, {time.time() - t0:.0f} s")
    # Instrument: cause-f light lit on most scored frames is the map's own
    # drawing (a site glyph the lighting reference calls lit), not light.
    static = f_count >= STATIC_FRAC * max(1, len(rows))
    log(f"{sid}: {len(rows)} frames scored in {time.time() - t0:.0f} s, skipped {skipped}")
    return {"rows": rows, "skipped": skipped, "smokes": s.smokes, "smoke_source": s.smoke_source,
            "vision_version": s.vision_version, "width": s.width, "capture": s.capture,
            "f_static_px": int(f_count[static].sum()), "f_static_area": int(static.sum()),
            "f_px": int(f_count.sum())}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else float("nan")
    return p, r, f


def _add(acc, x):
    if isinstance(x, dict):
        acc = {} if acc is None else acc
        for k, v in x.items():
            acc[k] = _add(acc.get(k), v)
        return acc
    if isinstance(x, (list, tuple)) and x and all(isinstance(i, (int, float)) for i in x):
        return [a + b for a, b in zip(acc or [0] * len(x), x)]
    if isinstance(x, (bool, int, float)):
        return (acc or 0) + x
    return acc


def aggregate(rows) -> dict:
    """Frames (or windows) summed into one: every count adds."""
    g = None
    for r in rows:
        g = _add(g, {k: v for k, v in r.items() if k not in ("t", "w", "widget", "why")})
    return g


def stats(aggs) -> dict:
    g = aggregate(aggs)
    nan = float("nan")
    o = {"frames": g["frames"], "menu_frames": g["menu_open"], "smoke_frames": g["smoke_frames"]}
    for arm in ARMS:
        a = g[arm]
        for k in ("team_all", "team_team", "self_all", "self_team"):
            p, r, f = prf(*a[k])
            o[f"{arm}_{k}_precision"], o[f"{arm}_{k}_recall"], o[f"{arm}_{k}_f1"] = p, r, f
        for k in ("e5", "e5_cast"):
            h, n, lit, nf = a[k]
            o[f"{arm}_{k}_precision"] = h / n if n else nan
            o[f"{arm}_{k}_recall"] = h / lit if lit else nan
            o[f"{arm}_{k}_f1"] = 2 * h / (n + lit) if n + lit else nan
            o[f"{arm}_{k}_frames"] = nf
        o[f"{arm}_self_frames"] = a["self_frames"]
        FP, FN = sum(a["fp_by"].values()), sum(a["fn_by"].values())
        o[f"{arm}_FP"], o[f"{arm}_FN"] = FP, FN
        for k in CAUSES:
            o[f"{arm}_fp_{k}"] = a["fp_by"][k] / FP if FP else nan
            o[f"{arm}_fn_{k}"] = a["fn_by"][k] / FN if FN else nan
            o[f"{arm}_err_{k}"] = (a["fp_by"][k] + a["fn_by"][k]) / (FP + FN) if FP + FN else nan
        for k in E_SUB:
            o[f"{arm}_fn_e_{k}"] = a["e_sub"].get(k, 0) / FN if FN else nan
        base = a["team_all"][1] + a["team_all"][2]
        for fx, cnt in a["fix"].items():
            tp, fp, fn = cnt
            o[f"{arm}_fix_{fx}_removed"] = (base - (fp + fn)) / base if base else nan
            o[f"{arm}_fix_{fx}_f1"] = prf(tp, fp, fn)[2]
            o[f"{arm}_fix_{fx}_df1"] = prf(tp, fp, fn)[2] - o[f"{arm}_team_all_f1"]
        o[f"{arm}_fp_red"] = a["fp_red"] / FP if FP else nan
        o[f"{arm}_fn_sat"] = a["fn_sat"] / FN if FN else nan
        o[f"{arm}_fp_g_self_flip"] = a["g_self_flip_fp"] / FP if FP else nan
        o[f"{arm}_fp_g_dark"] = a["g_dark_fp"] / FP if FP else nan
        o[f"{arm}_dark_frames"] = a["dark"]
        o[f"{arm}_fp_dark"] = a["dark_fp"] / FP if FP else nan
        o[f"{arm}_mask_mismatch_px"] = a["mask_mismatch_px"]
    ac = g["allies_cast"]
    o["ally_cones"] = ac
    o["ally_td_read"] = g["allies_td_read"] / ac if ac else nan
    o["ally_bad"] = g["allies_bad"] / ac if ac else nan
    for k in ("ineligible", "no_facing", "untracked"):
        o[f"icons_{k}_per_frame"] = g["why_n"].get(k, 0) / max(1, g["frames"])
    o["icons_cast_per_frame"] = g["why_n"].get("cast", 0) / max(1, g["frames"])
    o["smoke_r_gain_mean"] = g["smoke_r_gain"] / g["smoke_discs"] if g["smoke_discs"] else nan
    return o


def summarise(rows, seed=20260929) -> dict:
    """Pooled scores, cause shares and fix gains, with window bootstrap intervals."""
    wins = sorted({r["w"] for r in rows})
    per = {w: aggregate([r for r in rows if r["w"] == w]) for w in wins}
    full = stats([per[w] for w in wins])
    rng = np.random.default_rng(seed)
    keys = [k for k, v in full.items() if isinstance(v, float)]
    boots = {k: [] for k in keys}
    for _ in range(N_BOOT):
        pick = rng.choice(wins, size=len(wins), replace=True)
        b = stats([per[w] for w in pick])
        for k in keys:
            boots[k].append(b[k])
    with np.errstate(all="ignore"):
        full["ci"] = {k: (float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5)))
                      if np.isfinite(v).any() else (float("nan"), float("nan"))
                      for k, v in ((k, np.asarray(v, float)) for k, v in boots.items())}
    full["windows"] = len(wins)
    return full


# ------------------------------------------------------------------ sheets

COL = {"tp": (60, 160, 60), "fp": (40, 40, 220), "fn": (220, 120, 30)}


def render(s: Sess, a: dict, cause: str | None = None, box=None, zoom=3) -> np.ndarray:
    """Left: the crop. Right: the light and cones; `cause`'s pixels bright, others dim."""
    m = a["_m"]
    crop = m["crop"]
    base = cv2.cvtColor(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    base = (base * 0.55).astype(np.uint8)
    ov = base.copy()
    P, W = m["P"], m["W_all"]
    ov[~s.floor] = (90, 60, 60)
    ov[s.boxedge] = (0, 140, 200)
    tp, fp, fn = P & W, P & ~W, W & ~P
    dim = 0.45 if cause else 1.0
    for msk, col in ((tp, COL["tp"]), (fp, COL["fp"]), (fn, COL["fn"])):
        ov[msk] = (np.array(col) * dim).astype(np.uint8)
    if cause:
        hf, hn = m["by"][cause]
        ov[hf] = (80, 80, 255)
        ov[hn] = (255, 200, 60)
    for sm in m["live"]:
        cv2.circle(ov, (int(round(sm["cx"])), int(round(sm["cy"]))), int(round(sm["r"])),
                   (255, 0, 255), 1)
    for c in m["casters"]:
        x, y = int(round(c["ox"])), int(round(c["oy"]))
        th = math.radians(c["deg"])
        col = (255, 255, 0) if c["role"] == "ally" else (0, 255, 255)
        cv2.line(ov, (x, y), (int(x + 16 * math.cos(th)), int(y + 16 * math.sin(th))), col, 1)
    for b in m["bad"]:
        x, y = int(round(b["x"])), int(round(b["y"]))
        th = math.radians(b["td"])
        cv2.line(ov, (x, y), (int(x + 16 * math.cos(th)), int(y + 16 * math.sin(th))), (0, 128, 255), 1)
    for u in m["uncast"]:
        cv2.circle(ov, (int(round(u["x"])), int(round(u["y"]))), 12, (255, 255, 255), 1)
    if box is not None:
        x0, y0, x1, y1 = box
        crop, ov = crop[y0:y1, x0:x1], ov[y0:y1, x0:x1]
    im = np.concatenate([crop, np.full((crop.shape[0], 2, 3), 255, np.uint8), ov], axis=1)
    return cv2.resize(im, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)


def cause_box(s: Sess, a: dict, cause: str, half=60):
    hf, hn = a["_m"]["by"][cause]
    ys, xs = np.nonzero(hf | hn)
    h, w = s.passable.shape
    if not len(xs):
        cx, cy = w // 2, h // 2
    else:
        cx, cy = int(np.median(xs)), int(np.median(ys))
    x0 = int(np.clip(cx - half, 0, max(0, w - 2 * half)))
    y0 = int(np.clip(cy - half, 0, max(0, h - 2 * half)))
    return x0, y0, min(w, x0 + 2 * half), min(h, y0 + 2 * half)


def label(im, text):
    out = np.concatenate([np.zeros((22, im.shape[1], 3), np.uint8), im], axis=0)
    cv2.putText(out, text, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def grid(tiles, cols=3):
    if not tiles:
        return None
    h = max(t.shape[0] for t in tiles)
    w = max(t.shape[1] for t in tiles)
    pad = [np.pad(t, ((0, h - t.shape[0]), (0, w - t.shape[1]), (0, 0))) for t in tiles]
    while len(pad) % cols:
        pad.append(np.zeros_like(pad[0]))
    rows_ = [np.concatenate(pad[i:i + cols], axis=1) for i in range(0, len(pad), cols)]
    return np.concatenate(rows_, axis=0)


def sheets(sid: str, rows: list[dict], out: Path, n=6, whole=4) -> list[str]:
    """For each cause of the product's error, the frames (one per window) with most of its pixels."""
    s = Sess(sid, times_wanted=[r["t"] for r in rows])
    s.load_smokes([(r["w"], r["t"]) for r in rows])
    written, crops = [], {}

    def frame(t):
        if t not in crops:
            crops[t] = next(iter(s.crops([t])))[1]
        return frame_errors(s, t, crops[t], s.vision[t], keep=True)

    for k in CAUSES:
        for kind, by in (("fp", "fp_by"), ("fn", "fn_by")):
            ranked = sorted(rows, key=lambda r: -r["prod"][by][k])
            seen_w, pick = set(), []
            for r in ranked:
                if r["prod"][by][k] <= 0 or r["w"] in seen_w:
                    continue
                seen_w.add(r["w"])
                pick.append(r)
                if len(pick) >= n:
                    break
            if not pick:
                continue
            tiles = []
            for r in pick:
                a = frame(r["t"])
                hf, hn = a["_m"]["by"][k]
                a["_m"]["by"][k] = (hf if kind == "fp" else np.zeros_like(hf),
                                    hn if kind == "fn" else np.zeros_like(hn))
                im = render(s, a, k, cause_box(s, a, k))
                tiles.append(label(im, f"{sid} {r['t'] / 1000:.2f}s {kind}-{k} {r['prod'][by][k]}px"))
            p = out / f"{sid}_{kind}_{k}.png"
            cv2.imwrite(str(p), grid(tiles))
            written.append(str(p))
    ranked = sorted(rows, key=lambda r: -(sum(r["prod"]["fp_by"].values())
                                          + sum(r["prod"]["fn_by"].values())))
    seen_w, tiles = set(), []
    for r in ranked:
        if r["w"] in seen_w:
            continue
        seen_w.add(r["w"])
        a = frame(r["t"])
        tiles.append(label(render(s, a, None, zoom=2), f"{sid} {r['t'] / 1000:.2f}s whole"))
        if len(tiles) >= whole:
            break
    p = out / f"{sid}_whole.png"
    cv2.imwrite(str(p), grid(tiles, cols=2))
    written.append(str(p))
    dark = [r for r in rows if r["prod"]["dark"]]
    seen, tiles = set(), []
    for r in dark:
        if int(r["t"] // 5000) in seen:
            continue
        seen.add(int(r["t"] // 5000))
        a = frame(r["t"])
        tiles.append(label(render(s, a, None, zoom=2), f"{sid} {r['t'] / 1000:.2f}s cones cast, no light"))
        if len(tiles) >= 8:
            break
    if tiles:
        p = out / f"{sid}_dark_frames.png"
        cv2.imwrite(str(p), grid(tiles, cols=2))
        written.append(str(p))
    return written


def peek(sid: str, out: Path, n=6) -> str:
    """Before measuring: a few frames with the light and the stored cones drawn."""
    plan = plan_of(cache_times(sid), 1)
    rng = np.random.default_rng(7)
    pick = sorted(rng.choice([t for _w, t in plan], size=min(n * 3, len(plan)), replace=False))
    s = Sess(sid, times_wanted=pick)
    s.load_smokes([(0, t) for t in pick])
    tiles = []
    for t, crop in s.crops(pick):
        row = s.vision.get(float(t))
        if row is None or row["widget"] != "drawn":
            continue
        a = frame_errors(s, float(t), crop, row, keep=True)
        tiles.append(label(render(s, a, None, zoom=2), f"{sid} {t / 1000:.2f}s"))
        if len(tiles) >= n:
            break
    p = out / f"peek_{sid}.png"
    cv2.imwrite(str(p), grid(tiles, cols=2))
    return str(p)


def report(sid, r, sm, values, tag):
    ci = sm["ci"]

    def v(k, digits=4):
        x = sm[k]
        values[f"{tag}_{k}"] = round(float(x), digits)
        if k in ci:
            values[f"{tag}_{k}_lo"], values[f"{tag}_{k}_hi"] = (round(ci[k][0], digits),
                                                                round(ci[k][1], digits))
        return x

    print(f"\n== {sid} ({tag}) frames {sm['frames']} windows {sm['windows']} skipped {r['skipped']} "
          f"smokes {len(r['smokes'])} ({r['smoke_source']}) width {r['width']}")
    for arm in ARMS:
        print(f" -- arm {arm} ({'stored observable, eligible cones' if arm == 'prod' else 'every stored bearing, observable_all'})")
        for k in ("team_all", "team_team", "self_all", "self_team", "e5", "e5_cast"):
            p, rc, f = (v(f"{arm}_{k}_{m}") for m in ("precision", "recall", "f1"))
            lo, hi = ci.get(f"{arm}_{k}_f1", (float("nan"),) * 2)
            extra = f" ({sm[f'{arm}_{k}_frames']} frames)" if k.startswith("e5") else ""
            print(f"  {k:10s} P {p:.3f} R {rc:.3f} F1 {f:.3f} [{lo:.3f}, {hi:.3f}]{extra}")
            if k.startswith("e5"):
                values[f"{tag}_{arm}_{k}_frames"] = sm[f"{arm}_{k}_frames"]
        print(f"  FP {sm[arm + '_FP']} FN {sm[arm + '_FN']}  frames with a self cone {sm[arm + '_self_frames']}")
        for k in CAUSES:
            fp, fn, al = v(f"{arm}_fp_{k}"), v(f"{arm}_fn_{k}"), v(f"{arm}_err_{k}")
            print(f"  {k} {CAUSE_NAMES[k]:24s} FP {fp:.3f} [{ci[f'{arm}_fp_{k}'][0]:.3f}, "
                  f"{ci[f'{arm}_fp_{k}'][1]:.3f}]  FN {fn:.3f} [{ci[f'{arm}_fn_{k}'][0]:.3f}, "
                  f"{ci[f'{arm}_fn_{k}'][1]:.3f}]  all {al:.3f} [{ci[f'{arm}_err_{k}'][0]:.3f}, "
                  f"{ci[f'{arm}_err_{k}'][1]:.3f}]")
        print("    e split (of FN): " + ", ".join(f"{k} {v(f'{arm}_fn_e_{k}'):.3f}" for k in E_SUB))
        for fx in [k[len(arm) + 5:-8] for k in sm if k.startswith(arm + "_fix_") and k.endswith("_removed")]:
            rm, f1, df = v(f"{arm}_fix_{fx}_removed"), v(f"{arm}_fix_{fx}_f1"), v(f"{arm}_fix_{fx}_df1")
            lo, hi = ci[f"{arm}_fix_{fx}_removed"]
            dlo, dhi = ci[f"{arm}_fix_{fx}_df1"]
            print(f"  fix {fx:14s} removes {rm:+.3f} [{lo:+.3f}, {hi:+.3f}] of the error; "
                  f"F1 {f1:.3f} ({df:+.3f} [{dlo:+.3f}, {dhi:+.3f}])")
        for k in ("fp_red", "fn_sat", "fp_dark", "fp_g_self_flip", "fp_g_dark"):
            print(f"  {k} {v(arm + '_' + k):.4f}")
        for k in ("dark_frames", "mask_mismatch_px", "FP", "FN", "self_frames"):
            values[f"{tag}_{arm}_{k}"] = sm[f"{arm}_{k}"]
            print(f"  {k} {sm[arm + '_' + k]}")
    for k in ("frames", "menu_frames", "smoke_frames", "ally_cones", "windows"):
        values[f"{tag}_{k}"] = sm[k]
        print(f"  {k} {sm[k]}")
    for k in ("ally_td_read", "ally_bad", "icons_cast_per_frame", "icons_ineligible_per_frame",
              "icons_no_facing_per_frame", "icons_untracked_per_frame", "smoke_r_gain_mean"):
        print(f"  {k} {v(k):.3f}")
    values[f"{tag}_smoke_tracks"] = len(r["smokes"])
    fs = r["f_static_px"] / (sm["prod_FN"] or 1)
    print(f"  cause-f light on static map drawing: {fs:.3f} of the product's FN "
          f"({r['f_static_area']} px area; {r['f_static_px']} of {r['f_px']} f px)")
    values[f"{tag}_prod_fn_f_static"] = round(fs, 4)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sessions", nargs="+", default=list(SESSIONS))
    ap.add_argument("--step", type=int, default=2, help="every n-th frame of each 6 s window")
    ap.add_argument("--peek", metavar="SID")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--load", action="store_true", help="reuse the saved rows")
    ap.add_argument("--work", type=Path, default=Path(sem.tempfile.gettempdir()) / "team-vision-errors")
    ap.add_argument("--out", type=Path, default=STORE / "analysis" / "team-vision-errors-20260929")
    args = ap.parse_args(argv)
    idle()
    args.work.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.peek:
        print(peek(args.peek, args.out))
        return 0
    res = {}
    for sid in args.sessions:
        path = args.work / f"{sid}.json"
        if args.load and path.is_file():
            res[sid] = json.loads(path.read_text(encoding="utf-8"))
        else:
            res[sid] = score_session(sid, args.step)
            path.write_text(json.dumps(res[sid]), encoding="utf-8")
    values = {}
    for sid, r in res.items():
        report(sid, r, summarise(r["rows"]), values, TAGS.get(sid, sid[:4]))
    if not args.no_sheets:
        for sid, r in res.items():
            for p in sheets(sid, r["rows"], args.out):
                print("sheet", p, flush=True)
    if args.record:
        from reticle.version import TEAM_VISION_VERSION
        metrics.record("team_vision_errors", part="causes", session="+".join(res),
                       values=values,
                       deps={"prototype": VERSION, "team_vision": TEAM_VISION_VERSION,
                             "lighting": lighting.LIGHTING_VERSION, "witness": co.VERSION,
                             "ally_teardrop": itd.VERSION,
                             "smoke": {s: res[s]["smoke_source"] for s in res},
                             "edge_px": EDGE_PX, "edge_deg": EDGE_DEG,
                             "bad_facing_deg": BAD_FACING_DEG, "step": args.step},
                       context={"captures": {s: res[s]["capture"] for s in res}})
        print("recorded metrics row team_vision_errors/causes")
    (args.work / "summary.json").write_text(json.dumps(values, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
