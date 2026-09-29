r"""Why the ally channel reads too few icons, and a track-window re-search for the lost ones.

    .\.venv\Scripts\python.exe prototypes\ally_prior_search.py [--sessions A,B] [--limit N] [--record]

Experiment 1 of docs/PRIOR_DRIVEN_READERS.md, approved by the player on
2026-09-29 with the amendment that a reader may take a prior under guards: the
result declares what it `rests_on`, the prior is counted once, a full search
on a fixed cadence is stored apart as the audit, and every surprise is stored.

**Population.** In-round frames (`rounds.build_rounds`) of the stored
`ally_icon` stream (ally-icon-0.4.0) with the widget drawn and a self fit,
where the latest roster read at or before the frame (`roster`) is read. A
frame is *under* when its non-barrier icons number fewer than the roster's
alive allies less one (`round_lifetimes.ally_capacity`); the deficit is the
number of missing slots. The audit run `prior-audit-20260929` counted the
same thing with a script that is not in the repo; this reconstruction differs
from it by about 2% of frames and is the population every number here uses.

**Split** (stored rows only; `split`):

* ``menu`` -- the stored menu witness (`menu.stored_menu`) finds the menu open.
* each teammate track -- a `round_entity` ally entity (round-entity-0.8.0,
  built from the same ally_icon revision) -- last fitted within
  `round_lifetimes.MERGED_BUDGET_S` before the frame, in the same round, after
  the last hole (widget absent, menu open, no self fit: the prior expires
  there), and not observed at the frame, is a *missing track*, unless an
  entity born after its last fit is observed within walking reach of it
  (`track.admits`, walker, plus `track.association_tolerance`): that is the
  same teammate re-born under a new id, which the association fragments.
* a missing track is ``stacked`` when, at its last fit, the self icon lay
  within `round_lifetimes.OCCLUSION_RADIUS_PX` or another ally within
  `STACK_RADIUS_PX`, and at the frame an icon still lies that near the last
  fit: two icons merged and one is drawn over the other. Otherwise ``lost``.
* a missing track is ``died`` when a stored ally death verdict (the
  killfeed's channel, `events/death`; the player's own excluded) lies within
  `DEATH_MATCH_MS` of its last fit: the widget draws a death X while the
  roster still counts the teammate (0.2.0, after the full run's sheets).
* the deficit's slots go to the missing tracks most recently seen first;
  slots beyond them are ``no_prior``, with why: ``stale`` (a track last fitted
  over the budget ago), ``hole`` (cut by a hole) or ``unseen``. The frame's
  class is the first of menu, lost, died, stacked, no_prior that holds a slot.

**Re-search** (the minimap crop cache; no decode; `search`). For each lost
slot, the reader's own ally fits (`minimap.icons` on the ally key, surface
seed, slab support, the same code the reader runs) are made over the frame,
with the blob area floor relaxed to `RELAXED_MIN_AREA`, plus a fit at every
peak of the coverage surface (`peak_fits`: the reader fits one circle per
blob, so touching teammates make one fit; added after the smoke sheets, and
logged as a protocol correction before the full run), and kept only inside
the track's window: a fit the walker law admits from the track's last fit
over the elapsed time (`track.admits`, after subtracting
`track.association_tolerance`). Inside the window the test is relaxed to
coverage `RELAXED_COV` (the 0.20 row of the `ALLY_COV_MIN` sweep) and no
facing is required. The barrier gate (`ALLY_MAP_DIFF_MIN`, its interior
masked by the kept icons as the reader masks it), the spike-glyph gate
(`spike.on_glyph`) and `MIN_ICON_SEPARATION_PX` from every fit the reader
kept at that frame (ally, barrier and self) stay, and a fit on a kept icon's
teardrop lobe is refused (`on_lobe`; added with the peaks, same correction). The highest coverage
wins; one fit per track, at most the deficit per frame. Every recovered fit
carries ``rests_on: "track"`` with the entity, the prior fit and the window.
The prior is never moved by a recovered fit: it stays the last fit a full
search made (the stored reader's).

**Audit** (`audit` rows, stored apart). Every `AUDIT_EVERY`-th population
frame by position, fixed before any result, plus the first frame of each run
of under frames: the same relaxed test over the whole widget, with no window.
Each relaxed fit the reader did not keep is placed: inside a lost track's
window, inside any recent track's window, or outside every window. On frames
the reader already reads exact, relaxed fits are phantoms by the roster,
which estimates what relaxing the test costs without the prior.

**Surprises** (`surprise` rows): a lost slot whose window holds nothing that
passes (with the best rejected fit and the gates it failed), a relaxed audit
fit outside every window, and a reader-gated refit inside a window that the
stored row does not hold (the instrument disagreeing with storage).

Writes `analysis/prior-ally-20260929/` in the store (rows, summary, sheets);
`--record` appends a `metrics` row. Unwired (`"wire": "no"`, task
`prior-ally-20260929` in the store's `notes/predictions.jsonl`); the blind
labeller is `prototypes/label_prior_ally.py`.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import bisect  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, spike, team_vision  # noqa: E402
from reticle.menu import stored_menu  # noqa: E402
from reticle.minimap import (ALLY_COV_MIN, ALLY_INNER_MAX, ALLY_MAP_DIFF_MIN,  # noqa: E402
                             MIN_ICON_AREA, MIN_ICON_SEPARATION_PX, R_MAX, R_MIN,
                             _interior, _ring_at, ally_mask, coverage_surface, icons,
                             self_mask, widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.round_lifetimes import (MERGED_BUDGET_S, OCCLUSION_RADIUS_PX,  # noqa: E402
                                     STACK_RADIUS_PX, ally_capacity)
from reticle.rounds import build_rounds  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from reticle.track import CLASSES, admits, association_tolerance  # noqa: E402

# 0.2.0: a missing track the stored ally death verdicts saw die is `died`,
# not lost (the full run's missed sheets showed death X marks at the priors).
# 0.2.1: a fit's barrier interior is no longer masked by the kept icon it
# sits on (which emptied it and failed every kept fit on `barrier`), and a
# miss is counted by its decisive gate. Recovered and audit rows unchanged.
VERSION = "ally-prior-search-0.2.1"
TASK = "prior-ally-20260929"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
SESSIONS = ("a06f04a0059f", "5822b6646448")
CAPTURES = {"a06f04a0059f": "C:/Users/grant/Videos/2026-08-26 09-56-37.mp4 (Ascent)",
            "5822b6646448": "C:/Users/grant/Videos/2026-08-26 12-38-38.mp4 (Lotus)"}
#: The 0.20 row of the ALLY_COV_MIN sweep (minimap.py): +0.24 residual over
#: the roster with no prior, against -0.15 at the shipped 0.25.
RELAXED_COV = 0.20
#: The blob area floor inside a window; the reader's is MIN_ICON_AREA * sc^2.
RELAXED_MIN_AREA = 4
#: Audit cadence over the population, by position; fixed before any result.
AUDIT_EVERY = 15
#: A cache frame this near a stored frame's instant is that frame.
CACHE_MATCH_MS = 20.0
#: A run of frames with no self fit this long is the player's death (the view
#: spectates); a shorter one is a missed self fit and cuts no prior.
SELF_GAP_S = 1.0
#: A stored ally death this near a missing track's last fit is that track's
#: death: the killfeed rows sit on the HUD's 2 Hz grid.
DEATH_MATCH_MS = 1000.0
WALKER = CLASSES["walker"]


def _idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    except Exception:
        pass


# ------------------------------------------------------------------ stored rows
class Session:
    """The stored rows one session's split and search read."""

    def __init__(self, sid: str, store: Store):
        self.sid = sid
        man = json.loads((store.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
        date = man["ingested_at"][:10]
        ev = store.read_events("ally_icon", sid)
        self.ally_version = ev[0].get("ally_icon_version")
        self.frames = sorted((e for e in ev if e["kind"] == "frame"), key=lambda e: e["t_ms"])
        self.icons: dict[int, list[dict]] = defaultdict(list)
        self.barriers: dict[int, list[dict]] = defaultdict(list)
        for e in ev:
            if e["kind"] != "icon":
                continue
            (self.barriers if e.get("reason") == "interior_is_map"
             else self.icons)[e["frame_idx"]].append(e)
        del ev
        self.rounds = build_rounds(store.read_hud(sid, date))
        t = store.read_roster(sid, date)
        self.rt = t.column("t_ms").to_pylist()
        self.ra = t.column("alive_ally").to_pylist()
        self.menu, self.menu_stamp = stored_menu(store, sid)
        # Teammates' deaths from the stored death verdicts (the killfeed's
        # channel), the player's own excluded: his death ends the population.
        self.ally_deaths: dict[int, list[float]] = defaultdict(list)
        deaths = store.read_events("death", sid) if store.has_events("death", sid) else []
        for d in deaths:
            if (d.get("kind") == "death_verdict" and d.get("side") == "ally"
                    and not d.get("kf_player_death") and not d.get("is_revive")):
                self.ally_deaths[d["round_no"]].append(float(d["t_ms"]))
        self.death_version = next((d.get("death_adjudication_version") for d in deaths), None)
        self.entity_of: dict[str, str] = {}
        self.first_seen: dict[str, float] = {}
        with open(store.events_path("round_entity", sid), encoding="utf-8") as f:
            head = json.loads(f.readline())
            self.round_entity_version = head.get("round_entity_version")
            self.round_entity_source = head.get("ally_icon_revision")
            for line in f:
                if '"observation"' not in line:
                    continue
                r = json.loads(line)
                if r.get("kind") != "observation" or r.get("family") != "ally":
                    continue
                self.entity_of[r["observation_key"]] = r["entity_id"]
                e = r["entity_id"]
                if e not in self.first_seen or r["t_ms"] < self.first_seen[e]:
                    self.first_seen[e] = r["t_ms"]
        geo = geometry.manifest(sid, store.root)
        self.profile = get_profile(geo["source_profile"])
        self.wh = (int(geo["source"]["width"]), int(geo["source"]["height"]))
        self.man = geo

    def round_of(self, t: float):
        for r in self.rounds:
            if r["t_start_ms"] <= t < r["t_end_ms"]:
                return r["round_no"]
        return None

    def capacity(self, t: float, self_seen: bool):
        i = bisect.bisect_right(self.rt, t) - 1
        if i < 0:
            return None
        return ally_capacity(self.ra[i], self_seen)


def _near(x, y, pts, radius):
    return any(np.hypot(x - px, y - py) <= radius for px, py in pts)


def split(s: Session, sc: float) -> tuple[list[dict], list[dict]]:
    """Per population frame: its class and slots. Returns (population, under rows)."""
    tol = association_tolerance(sc)
    pop, under = [], []
    tracks: dict[str, dict] = {}      # entity -> last fit
    cur_round, hole_t = None, -1e18
    # A self fit missing for a moment is a detection miss; missing for
    # SELF_GAP_S or longer, the player is dead and the view spectates, which
    # expires every prior (guard 6 of docs/PRIOR_DRIVEN_READERS.md).
    long_gap, run = set(), []
    for f in s.frames + [{"frame_idx": None, "t_ms": float("inf"), "self": True,
                          "widget_drawn": True}]:
        if f["widget_drawn"] and not f.get("self"):
            run.append(f)
            continue
        if run and run[-1]["t_ms"] - run[0]["t_ms"] >= SELF_GAP_S * 1000.0:
            long_gap.update(g["frame_idx"] for g in run)
        run = []
    for f in s.frames:
        t = f["t_ms"]
        rnd = s.round_of(t)
        if rnd != cur_round:
            tracks, cur_round, hole_t = {}, rnd, t
        if rnd is None:
            continue
        menu_open = s.menu is not None and s.menu.at(t) is True
        if not f["widget_drawn"] or not f.get("self") or menu_open:
            if not f["widget_drawn"] or menu_open or f["frame_idx"] in long_gap:
                hole_t = t
            if menu_open and f["widget_drawn"] and f.get("self"):
                cap = s.capacity(t, True)
                n = len(s.icons.get(f["frame_idx"], []))
                if cap is not None:
                    row = {"frame_idx": f["frame_idx"], "t_ms": t, "round_no": rnd,
                           "icons": n, "capacity": cap}
                    pop.append(row)
                    if n < cap:
                        under.append({**row, "deficit": cap - n, "class": "menu",
                                      "slots": [{"kind": "menu"}] * (cap - n)})
            continue
        me = f["self"]
        now = s.icons.get(f["frame_idx"], [])
        now_ent = {s.entity_of.get(i["observation_key"]) for i in now}
        pts_now = [(i["cx"], i["cy"]) for i in now]
        cap = s.capacity(t, True)
        if cap is not None:
            n = len(now)
            row = {"frame_idx": f["frame_idx"], "t_ms": t, "round_no": rnd,
                   "icons": n, "capacity": cap}
            pop.append(row)
            if n < cap:
                missing, expired = [], []
                for ent, lf in tracks.items():
                    if ent in now_ent:
                        continue
                    dt = (t - lf["t_ms"]) / 1000.0
                    if lf["t_ms"] <= hole_t or dt > MERGED_BUDGET_S:
                        # Not a prior: say why, for the no_prior slots.
                        expired.append(("hole" if lf["t_ms"] <= hole_t else "stale",
                                        lf["t_ms"], ent))
                        continue
                    # Re-born under a new id: an entity first seen after this
                    # track's last fit, observed now within walking reach.
                    reborn = None
                    for i in now:
                        e2 = s.entity_of.get(i["observation_key"])
                        if e2 is None or s.first_seen.get(e2, 0) <= lf["t_ms"]:
                            continue
                        d = float(np.hypot(i["cx"] - lf["x"], i["cy"] - lf["y"]))
                        if admits(WALKER, max(0.0, d - tol), dt, sc)[0]:
                            reborn = e2
                            break
                    if reborn:
                        continue
                    stacked = lf["crowded"] and (
                        _near(lf["x"], lf["y"], [(me[0], me[1])], OCCLUSION_RADIUS_PX * sc)
                        or _near(lf["x"], lf["y"], pts_now, STACK_RADIUS_PX * sc))
                    missing.append({"entity_id": ent, "kind": "stacked" if stacked else "lost",
                                    "prior": dict(lf), "dt_s": round(dt, 3)})
                # A teammate the killfeed saw die as its icon vanished draws a
                # death X, not an icon, while the roster still counts it: the
                # roster lags. Each stored ally death names at most one track,
                # the missing one whose last fit is nearest it.
                for td in s.ally_deaths.get(rnd, ()):
                    near = [m for m in missing if m["kind"] != "died"
                            and abs(m["prior"]["t_ms"] - td) <= DEATH_MATCH_MS]
                    if near:
                        m = min(near, key=lambda m: abs(m["prior"]["t_ms"] - td))
                        m["kind"], m["death_t_ms"] = "died", td
                missing.sort(key=lambda m: -m["prior"]["t_ms"])
                d = cap - n
                # A no_prior slot names why: a track too old for the budget
                # (stale), one cut by a hole, or no track this round to lose
                # (unseen: the teammate was never read, or the roster counts
                # one the widget no longer draws).
                expired.sort(key=lambda e: -e[1])
                rest = max(0, d - len(missing))
                slots = missing[:d] + [
                    {"kind": "no_prior", "why": expired[j][0] if j < len(expired) else "unseen",
                     "age_s": (round((t - expired[j][1]) / 1000.0, 2)
                               if j < len(expired) else None)}
                    for j in range(rest)]
                kinds = {sl["kind"] for sl in slots}
                cls = next(k for k in ("lost", "died", "stacked", "no_prior") if k in kinds)
                under.append({**row, "deficit": d, "class": cls, "slots": slots,
                              "missing_tracks": len(missing),
                              "self": me})
        # Update the track state from this frame's stored fits (full search).
        for i in now:
            ent = s.entity_of.get(i["observation_key"])
            if ent is None:
                continue
            others = [(o["cx"], o["cy"]) for o in now if o is not i]
            crowded = (_near(i["cx"], i["cy"], others, STACK_RADIUS_PX * sc)
                       or _near(i["cx"], i["cy"], [(me[0], me[1])], OCCLUSION_RADIUS_PX * sc))
            tracks[ent] = {"t_ms": t, "frame_idx": f["frame_idx"], "x": i["cx"], "y": i["cy"],
                           "r": i["r"], "observation_key": i["observation_key"],
                           "crowded": bool(crowded)}
    return pop, under


# ------------------------------------------------------------------ pixels
class Pixels:
    """Baked geometry and the minimap crop cache for one session."""

    def __init__(self, s: Session, store: Store):
        inputs, why = team_vision.load_inputs(store.root, s.sid, s.profile, *s.wh)
        if inputs is None:
            raise SystemExit(f"{s.sid}: no geometry ({why})")
        self.floor, self.slab, self.static, self.box = (inputs.floor, inputs.slab,
                                                        inputs.static, inputs.box)
        self.ref = cv2.cvtColor(self.static, cv2.COLOR_BGR2GRAY).astype(np.float32)
        self.cache, why = RoiCache.load(store.root, s.man, s.profile, "minimap")
        if self.cache is None:
            raise SystemExit(f"{s.sid}: no minimap crop cache ({why})")
        if self.cache.widget is not None:
            raise SystemExit(f"{s.sid}: a variant widget; this prototype reads baked-frame caches only")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))
        self.sc = widget_scale(self.box[2] - self.box[0])

    def nearest(self, t: float):
        j = int(np.searchsorted(self.cache_t, t))
        best = min((k for k in (j - 1, j) if 0 <= k < len(self.cache_t)),
                   key=lambda k: abs(self.cache_t[k] - t))
        tc = float(self.cache_t[best])
        return tc if abs(tc - t) <= CACHE_MATCH_MS else None

    def crops(self, times):
        """(asked t, cache t, crop) for each asked instant the cache holds."""
        pairs = [(t, self.nearest(t)) for t in times]
        want = sorted({tc for _t, tc in pairs if tc is not None})
        x0, y0, x1, y1 = self.box
        got = {smp.t_ms: smp.frame[y0:y1, x0:x1].copy()
               for smp in self.cache.samples(want, rois=["minimap"])}
        for t, tc in pairs:
            if tc is not None and tc in got:
                yield t, tc, got[tc]


#: A fit centred within this angle of a kept icon's facing, and within
#: LOBE_REACH_R of its radius from it, sits on that icon's teardrop. The smoke
#: sheets' audit fits outside every window were nearly all such peaks, 16-26
#: px out along the facing; the barrier gate passes them because the lobe
#: points into the lit floor of the teammate's own view.
LOBE_ANGLE_DEG = 40.0
LOBE_REACH_R = 2.6


def on_lobe(f: dict, lobes: list[tuple[float, float, float, float]], sc: float) -> bool:
    """`lobes` are (cx, cy, r, facing degrees) of the kept icons with a bearing."""
    for x, y, r, face in lobes:
        dx, dy = f["cx"] - x, f["cy"] - y
        d = float(np.hypot(dx, dy))
        if d > LOBE_REACH_R * r:
            continue
        diff = abs((np.degrees(np.arctan2(dy, dx)) - face + 180.0) % 360.0 - 180.0)
        if diff <= LOBE_ANGLE_DEG:
            return True
    return False


def relaxed_fits(px: Pixels, crop: np.ndarray, kept: list[tuple[float, float]],
                 kept_lobes=()) -> list[dict]:
    """Every ally fit of the frame, each with the gates it passes.

    `kept` are the centres the stored reader kept at this frame (allies,
    barriers and self); a fit within MIN_ICON_SEPARATION_PX of one is that
    icon, not another. `kept_lobes` are the stored allies' (cx, cy, r,
    facing); the self icon's bearing is refitted here, as the frame row
    stores none."""
    sc = px.sc
    amask = ally_mask(crop)
    smask = self_mask(crop)
    keyed = amask | smask
    lobes = list(kept_lobes)
    if kept:
        sx, sy = kept[-1]
        for g in icons(smask, crop, px.floor, support=px.slab, gates=False):
            if g["facing"] is not None and np.hypot(g["cx"] - sx, g["cy"] - sy) <= 2.0 * sc:
                lobes.append((g["cx"], g["cy"], g["r"], g["facing"]))
                break
    raw = icons(amask, crop, px.floor, support=px.slab, seed="surface", gates=False,
                min_area=RELAXED_MIN_AREA)
    for f in raw:
        f["seed"] = "blob"
    raw += peak_fits(px, crop, amask)
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    glyphs = spike.accepted(spike.glyph_fits(crop, px.slab))
    shaped = [f for f in raw if f["cov"] >= ALLY_COV_MIN and f["inner"] <= ALLY_INNER_MAX]
    reader_area = max(4, int(round(MIN_ICON_AREA * sc * sc)))
    sep = MIN_ICON_SEPARATION_PX * sc
    out = []
    # Pixels nearer a kept icon are that icon's portrait, as in the reader's
    # own barrier test (`_mark_barriers` passes its fits as `others`); without
    # this a peak on a kept icon's teardrop lobe reads the neighbour's
    # portrait as its own and passes the barrier gate.
    for f in raw:
        # A kept icon within the separation IS this fit's icon, not a
        # neighbour: masking by it would empty the interior.
        others = [{"cx": x, "cy": y} for x, y in kept
                  if np.hypot(f["cx"] - x, f["cy"] - y) >= sep]
        win, keep = _interior(f, keyed, others)
        f["map_diff"] = (float(np.abs(grey[win][keep] - px.ref[win][keep]).mean())
                         if keep.any() else None)
        near = [g for g in glyphs if np.hypot(g["cx"] - f["cx"], g["cy"] - f["cy"])
                <= spike.ON_GLYPH_PX * sc]
        fails = []
        if f["cov"] < RELAXED_COV:
            fails.append("cov")
        if f["inner"] > ALLY_INNER_MAX:
            fails.append("inner")
        if f["map_diff"] is None or f["map_diff"] < ALLY_MAP_DIFF_MIN:
            fails.append("barrier")
        if spike.on_glyph(f["cx"], f["cy"], near, sc, shaped) is not None:
            fails.append("spike_glyph")
        if _near(f["cx"], f["cy"], kept, sep):
            fails.append("kept_icon")
        elif on_lobe(f, lobes, sc):
            fails.append("kept_icon_lobe")
        relaxed = []
        if f["cov"] < ALLY_COV_MIN:
            relaxed.append("cov_below_reader")
        if f["facing"] is None:
            relaxed.append("facing_unread")
        if f["seed"] == "peak":
            relaxed.append("second_fit_in_blob")
        elif f["area"] < reader_area:
            relaxed.append("area_below_reader")
        f["fails"], f["relaxed"] = fails, relaxed
        # What the reader itself would have kept here, before separation.
        f["reader_pass"] = not relaxed and "inner" not in fails and "barrier" not in fails \
            and "spike_glyph" not in fails
        out.append(f)
    # Two blobs of one broken surround yield near-identical fits: keep the
    # best coverage of any pair closer than the separation, as `_gated` does.
    # A blob's own fit is a surface peak too, so a tie is the same circle:
    # the blob seed (the reader's) is kept.
    out.sort(key=lambda d: (-d["cov"], d["seed"] == "peak"))
    dedup = []
    for f in out:
        if any(np.hypot(f["cx"] - o["cx"], f["cy"] - o["cy"]) < sep for o in dedup):
            continue
        dedup.append(f)
    return dedup


def peak_fits(px: Pixels, crop: np.ndarray, amask: np.ndarray) -> list[dict]:
    """Ring fits at every local peak of the coverage surface, not one per blob.

    The reader fits one circle per connected blob of the ally key
    (`minimap.icons`), so two teammates whose surrounds touch make one blob
    and one fit. The first sheets of this experiment showed clearly drawn
    icons beside another with no raw fit at all. A peak must lie on the
    slab's support (a keyed pixel on the slab inside its disc) and reach
    RELAXED_COV; peaks nearer than MIN_ICON_SEPARATION_PX keep the best."""
    sc = px.sc
    r_min, r_max = max(3, int(round(R_MIN * sc))), max(4, int(round(R_MAX * sc)))
    keyed = amask & px.floor
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    surf, surf_r = coverage_surface(keyed, r_min, r_max)
    sep = MIN_ICON_SEPARATION_PX * sc
    ks = 2 * int(sep // 2) + 1
    mx = cv2.dilate(surf, np.ones((ks, ks), np.uint8))
    ys, xs = np.where((surf >= RELAXED_COV) & (surf >= mx))
    order = np.argsort(-surf[ys, xs], kind="stable")
    on_slab = keyed & px.slab
    H, W = keyed.shape
    out: list[dict] = []
    for j in order:
        x, y = int(xs[j]), int(ys[j])
        if any(np.hypot(x - o["cx"], y - o["cy"]) < sep for o in out):
            continue
        r = int(surf_r[y, x])
        a, b = max(0, y - r - 2), min(H, y + r + 3)
        c, d = max(0, x - r - 2), min(W, x + r + 3)
        if not on_slab[a:b, c:d].any():
            continue
        f = _ring_at(keyed, grey, float(surf[y, x]), x, y, r)
        if f is None:
            continue
        out.append({"cx": float(x), "cy": float(y), "r": r, "cov": float(f["cov"]),
                    "inner": float(f["inner_red"]), "inner_v": float(f["inner_v"]),
                    "facing": f["facing"], "lobe": float(f["lobe"]),
                    "area": int(keyed[a:b, c:d].sum()), "seed": "peak"})
    return out


def _fit_row(f: dict) -> dict:
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()
            if k in ("cx", "cy", "r", "cov", "inner", "inner_v", "facing", "lobe", "area",
                     "map_diff", "fails", "relaxed", "reader_pass", "seed")}


def in_window(f: dict, prior: dict, t: float, sc: float) -> tuple[bool, str, float]:
    dt = (t - prior["t_ms"]) / 1000.0
    d = float(np.hypot(f["cx"] - prior["x"], f["cy"] - prior["y"]))
    slack = association_tolerance(sc, r_a=prior.get("r"), r_b=f.get("r"))
    ok, why = admits(WALKER, max(0.0, d - slack), dt, sc)
    return ok, why, d


def window_px(prior: dict, t: float, sc: float) -> float:
    """The window's radius, for sheets only; the decision is `in_window`."""
    return WALKER.max_px_s * sc * (t - prior["t_ms"]) / 1000.0 + association_tolerance(sc)


def search(s: Session, px: Pixels, pop: list[dict], under: list[dict], limit: int | None,
           seed: int = 7) -> dict:
    sc = px.sc
    lost_frames = [u for u in under if any(sl["kind"] == "lost" for sl in u["slots"])]
    if limit:
        rng = random.Random(seed)
        lost_frames = sorted(rng.sample(lost_frames, min(limit, len(lost_frames))),
                             key=lambda u: u["t_ms"])
    under_by_idx = {u["frame_idx"]: u for u in under}
    # The audit: every AUDIT_EVERY-th population frame, plus the first frame
    # of each run of under frames. Both fixed before any pixel is read.
    audit_idx = {p["frame_idx"] for k, p in enumerate(pop) if k % AUDIT_EVERY == 0}
    prev_under = False
    for p in pop:
        is_under = p["frame_idx"] in under_by_idx
        if is_under and not prev_under:
            audit_idx.add(p["frame_idx"])
        prev_under = is_under
    audit_pop = [p for p in pop if p["frame_idx"] in audit_idx]
    if limit:
        rng = random.Random(seed + 1)
        audit_pop = sorted(rng.sample(audit_pop, min(limit, len(audit_pop))),
                           key=lambda p: p["t_ms"])
    frame_of = {f["frame_idx"]: f for f in s.frames}
    need = sorted({u["t_ms"] for u in lost_frames} | {p["t_ms"] for p in audit_pop})
    lost_t = {u["t_ms"]: u for u in lost_frames}
    audit_t = {p["t_ms"]: p for p in audit_pop}
    # Recent track priors at audit frames that are not under, for placing
    # relaxed audit fits: recomputed from the stored fits.
    recovered, misses, audits, surprises = [], [], [], []
    unread = Counter()
    t0 = time.time()
    for k, (t, tc, crop) in enumerate(px.crops(need)):
        fidx = (lost_t.get(t) or audit_t.get(t))["frame_idx"]
        fr = frame_of[fidx]
        stored = s.icons.get(fidx, [])
        kept = ([(i["cx"], i["cy"]) for i in stored]
                + [(b["cx"], b["cy"]) for b in s.barriers.get(fidx, [])]
                + [(fr["self"][0], fr["self"][1])])
        fits = relaxed_fits(px, crop, kept,
                            [(i["cx"], i["cy"], i["r"], i["facing"]) for i in stored
                             if i.get("facing") is not None])
        u = under_by_idx.get(fidx)
        if t in lost_t:
            taken = set()
            for sl in u["slots"]:
                if sl["kind"] != "lost":
                    continue
                cands = []
                for f in fits:
                    ok, why, d = in_window(f, sl["prior"], t, sc)
                    if ok:
                        cands.append((f, why, d))
                passing = [(f, why, d) for f, why, d in cands if not f["fails"]
                           and id(f) not in taken]
                reader_in = [f for f, _w, _d in cands if f["reader_pass"]
                             and "kept_icon" not in f["fails"]]
                if reader_in:
                    surprises.append({"kind": "surprise", "surprise": "reader_refit_not_stored",
                                      "session_id": s.sid, "t_ms": t, "cache_t_ms": tc,
                                      "frame_idx": fidx, "entity_id": sl["entity_id"],
                                      "fits": [_fit_row(f) for f in reader_in]})
                base = {"session_id": s.sid, "t_ms": t, "cache_t_ms": tc, "frame_idx": fidx,
                        "round_no": u["round_no"], "entity_id": sl["entity_id"],
                        "deficit": u["deficit"], "capacity": u["capacity"],
                        "icons": u["icons"], "dt_s": sl["dt_s"],
                        "prior": {k2: sl["prior"][k2] for k2 in ("t_ms", "x", "y", "r",
                                                                 "observation_key")},
                        "window_px": round(window_px(sl["prior"], t, sc), 2),
                        "self": fr["self"]}
                if passing:
                    f, why, d = max(passing, key=lambda c: c[0]["cov"])
                    taken.add(id(f))
                    recovered.append({**base, "kind": "recovered", "fit": _fit_row(f),
                                      "dist_px": round(d, 2), "admits": why,
                                      "rests_on": "track",
                                      "scope": {"window": "track.admits walker + "
                                                          "association_tolerance",
                                                "source": f"round_entity {s.round_entity_version}",
                                                "entity_id": sl["entity_id"],
                                                "prior_observation": sl["prior"]["observation_key"],
                                                "widened": False},
                                      "version": VERSION})
                else:
                    best = max(cands, key=lambda c: c[0]["cov"]) if cands else None
                    row = {**base, "kind": "surprise", "surprise": "lost_nothing_in_window",
                           "in_window": len(cands),
                           "best": _fit_row(best[0]) if best else None,
                           "best_dist_px": round(best[2], 2) if best else None,
                           "version": VERSION}
                    misses.append(row)
                    surprises.append(row)
        if t in audit_t:
            p = audit_t[t]
            relaxed_new = [f for f in fits if not f["fails"]]
            placed = []
            priors = [sl for sl in (u["slots"] if u else []) if sl["kind"] in ("lost", "stacked")]
            for f in relaxed_new:
                where = "outside_every_window"
                for sl in priors:
                    if in_window(f, sl["prior"], t, sc)[0]:
                        where = f"in_{sl['kind']}_window"
                        break
                placed.append({**_fit_row(f), "where": where})
            arow = {"kind": "audit", "session_id": s.sid, "t_ms": t, "cache_t_ms": tc,
                    "frame_idx": fidx, "icons": p["icons"], "capacity": p["capacity"],
                    "under": u is not None, "class": u["class"] if u else None,
                    "relaxed_extra": placed,
                    "reader_refit": sum(1 for f in fits if f["reader_pass"]
                                        and "kept_icon" in f["fails"]),
                    "reader_refit_unstored": sum(1 for f in fits if f["reader_pass"]
                                                 and "kept_icon" not in f["fails"]),
                    "version": VERSION}
            audits.append(arow)
            for f in placed:
                if f["where"] == "outside_every_window":
                    surprises.append({"kind": "surprise", "surprise": "audit_fit_outside_windows",
                                      "session_id": s.sid, "t_ms": t, "cache_t_ms": tc,
                                      "frame_idx": fidx, "under": u is not None,
                                      "fit": f, "version": VERSION})
        if k and k % 500 == 0:
            print(f"    {s.sid}: {k}/{len(need)} frames, {time.time() - t0:.0f}s", flush=True)
    for tt in need:
        if px.nearest(tt) is None:
            unread["no_cache_frame"] += 1
    print(f"    {s.sid}: {len(need)} frames read in {time.time() - t0:.0f}s", flush=True)
    return {"recovered": recovered, "misses": misses, "audits": audits,
            "surprises": surprises, "unread": dict(unread),
            "lost_frames_searched": len(lost_frames), "audit_frames": len(audit_pop)}


# ------------------------------------------------------------------ sheets
RING_FIT = (60, 230, 250)
RING_PRIOR = (250, 120, 255)


def tile(crop: np.ndarray, cx: float, cy: float, prior=None, window=None, fit=None,
         caption: str = "", half: int = 32, zoom: int = 4) -> np.ndarray:
    x0, y0 = int(cx) - half, int(cy) - half
    pad = cv2.copyMakeBorder(crop, half, half, half, half, cv2.BORDER_CONSTANT)
    patch = pad[y0 + half:y0 + 3 * half, x0 + half:x0 + 3 * half]
    big = cv2.resize(patch, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    to = lambda x, y: (int((x - x0) * zoom), int((y - y0) * zoom))
    if prior is not None:
        p = to(*prior)
        cv2.drawMarker(big, p, RING_PRIOR, cv2.MARKER_CROSS, 14, 2)
        if window is not None:
            cv2.circle(big, p, int(window * zoom), RING_PRIOR, 1, cv2.LINE_AA)
    if fit is not None:
        cv2.circle(big, to(fit[0], fit[1]), int(fit[2] * zoom), RING_FIT, 1, cv2.LINE_AA)
    bar = np.full((18, big.shape[1], 3), 24, np.uint8)
    cv2.putText(bar, caption[:40], (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                (220, 220, 220), 1, cv2.LINE_AA)
    return np.vstack([bar, big])


def write_sheet(path: Path, tiles: list[np.ndarray], cols: int = 8) -> None:
    if not tiles:
        return
    h = max(t.shape[0] for t in tiles)
    w = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, w - t.shape[1],
                                cv2.BORDER_CONSTANT, value=(10, 10, 10)) for t in tiles]
    tiles = [cv2.copyMakeBorder(t, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(60, 60, 60))
             for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    cv2.imwrite(str(path), np.vstack(rows))


def sheets(px: Pixels, sid: str, res: dict, n: int = 48, seed: int = 3) -> list[Path]:
    rng = random.Random(seed)
    out = []
    groups = {
        "recovered": res["recovered"],
        "missed": res["misses"],
        "audit-outside": [s for s in res["surprises"]
                          if s["surprise"] == "audit_fit_outside_windows"],
    }
    for name, rows in groups.items():
        pick = sorted(rng.sample(rows, min(n, len(rows))), key=lambda r: r["t_ms"])
        crops = {t: c for t, _tc, c in px.crops(sorted({r["t_ms"] for r in pick}))}
        tiles = []
        for r in pick:
            crop = crops.get(r["t_ms"])
            if crop is None:
                continue
            fit = r.get("fit") or r.get("best")
            prior = (r["prior"]["x"], r["prior"]["y"]) if "prior" in r else None
            # Centred on the fit where there is one, so a far fit in a wide
            # window is on the tile; the prior's cross shows where it was.
            centre = (fit["cx"], fit["cy"]) if fit else prior
            cap = f"{r['t_ms'] / 1000:.1f}s"
            if "dt_s" in r:
                cap += f" dt{r['dt_s']:.1f}"
            if fit:
                cap += f" c{fit['cov']:.2f}"
                if fit.get("relaxed"):
                    cap += " " + ",".join(x.split("_")[0] for x in fit["relaxed"])
                if name == "missed" and fit.get("fails"):
                    cap += " !" + ",".join(fit["fails"])
            tiles.append(tile(crop, *centre, prior=prior, window=r.get("window_px"),
                              fit=(fit["cx"], fit["cy"], fit["r"]) if fit else None,
                              caption=cap))
        path = OUT / f"sheet-{name}-{sid}.png"
        write_sheet(path, tiles)
        if tiles:
            out.append(path)
    return out


# ------------------------------------------------------------------ main
def summarise(sid: str, pop: list[dict], under: list[dict], res: dict | None) -> dict:
    cls = Counter(u["class"] for u in under)
    slots = Counter(sl["kind"] for u in under for sl in u["slots"])
    v = {"frames": len(pop), "under": len(under),
         "exact": sum(1 for p in pop if p["icons"] == p["capacity"]),
         "over": sum(1 for p in pop if p["icons"] > p["capacity"]),
         **{f"under_{k}": cls.get(k, 0) for k in ("menu", "stacked", "lost", "died", "no_prior")},
         **{f"slots_{k}": slots.get(k, 0) for k in ("menu", "stacked", "lost", "died", "no_prior")}}
    why = Counter(sl["why"] for u in under for sl in u["slots"] if sl["kind"] == "no_prior")
    for k in ("stale", "hole", "unseen"):
        v[f"slots_no_prior_{k}"] = why.get(k, 0)
    if res is not None:
        rec, mis = res["recovered"], res["misses"]
        v["lost_slots_searched"] = len(rec) + len(mis)
        v["recovered"] = len(rec)
        v["recovery_rate"] = round(len(rec) / max(1, len(rec) + len(mis)), 4)
        rel = Counter(tuple(sorted(r["fit"]["relaxed"])) for r in rec)
        v["recovered_reader_cov_facing_only"] = rel.get(("facing_unread",), 0)
        v["recovered_cov_below_reader"] = sum(n for k, n in rel.items() if "cov_below_reader" in k)
        v["recovered_area_below_reader"] = sum(n for k, n in rel.items() if "area_below_reader" in k)
        v["recovered_second_fit_in_blob"] = sum(n for k, n in rel.items()
                                                if "second_fit_in_blob" in k)
        v["recovered_no_relaxation"] = rel.get((), 0)
        v["missed_empty_window"] = sum(1 for m in mis if not m["in_window"])
        # A miss with fits in its window, by the best fit's decisive gate: a
        # kept icon first (the teammate may be drawn, under another track's
        # id), then the lobe, then the shape and barrier gates.
        order = ("kept_icon", "kept_icon_lobe", "spike_glyph", "cov", "inner", "barrier")
        failed = Counter(next((g for g in order if g in m["best"]["fails"]), "none")
                         for m in mis if m["best"])
        for k2, n in failed.items():
            v[f"missed_best_{k2}"] = n
        au = res["audits"]
        v["audit_frames"] = len(au)
        v["audit_frames_outside_fit"] = sum(1 for a in au if any(
            f["where"] == "outside_every_window" for f in a["relaxed_extra"]))
        ex = [a for a in au if a["icons"] == a["capacity"]]
        v["audit_exact_frames"] = len(ex)
        v["audit_exact_frames_with_relaxed_extra"] = sum(1 for a in ex if a["relaxed_extra"])
        v["audit_reader_refit_unstored"] = sum(a["reader_refit_unstored"] for a in au)
        v["surprises"] = len(res["surprises"])
        v["unread"] = sum(res["unread"].values())
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sessions", default=",".join(SESSIONS))
    ap.add_argument("--limit", type=int, default=None,
                    help="sample this many lost frames and audit frames (a smoke run)")
    ap.add_argument("--split-only", action="store_true")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _idle()
    store = Store(STORE)
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for sid in args.sessions.split(","):
        print(f"{sid}  {CAPTURES.get(sid, '')}", flush=True)
        s = Session(sid, store)
        px = None if args.split_only else Pixels(s, store)
        sc = px.sc if px else widget_scale(465)
        pop, under = split(s, sc)
        res = None
        if px is not None:
            res = search(s, px, pop, under, args.limit)
            tag = "" if not args.limit else f".limit{args.limit}"
            for name in ("recovered", "audits", "surprises"):
                with open(OUT / f"{name}-{sid}{tag}.jsonl", "w", encoding="utf-8") as f:
                    for r in res[name]:
                        f.write(json.dumps(r) + "\n")
            paths = sheets(px, sid + tag, res)
            for p in paths:
                print(f"  sheet {p}")
        with open(OUT / f"split-{sid}.jsonl", "w", encoding="utf-8") as f:
            for u in under:
                f.write(json.dumps(u) + "\n")
        v = summarise(sid, pop, under, res)
        summary[sid] = v
        for k2, n in v.items():
            print(f"  {k2:40s} {n}")
    (OUT / f"summary{'' if not args.limit else '.limit' + str(args.limit)}.json").write_text(
        json.dumps({"version": VERSION, "sessions": summary}, indent=1), encoding="utf-8")
    if args.record and not args.limit:
        from reticle import metrics
        for sid, v in summary.items():
            metrics.record("prior_ally_search", part=f"split-and-search-{VERSION}", session=sid,
                           values={k2: n for k2, n in v.items() if isinstance(n, (int, float))},
                           deps={"script": VERSION, "ally_icon": "ally-icon-0.4.0",
                                 "round_entity": "round-entity-0.8.0",
                                 "relaxed_cov": RELAXED_COV,
                                 "relaxed_min_area": RELAXED_MIN_AREA,
                                 "audit_every": AUDIT_EVERY},
                           note="stored rows and the minimap crop cache; no decode",
                           run_id=TASK)
        print("recorded metrics prior_ally_search")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
