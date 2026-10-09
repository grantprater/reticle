r"""The replay clock and the stored streams the harness joins to truth.

Moved from `prototypes/replay_truth.py` on 2026-10-09 (task
`harness-t1d-20261009`): the lag constants (`SELF_LAG_MS`, `REMOTE_LAG_MS`),
`capture_to_replay`, the stream loaders and the `replay-score` scorer's
helpers. Replay data is evaluation truth only.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from reticle import replay_source as src
# The acceptance core and the replay reader own these; `run` reads them here.
from reticle.acceptance import assign_per_frame as _assign  # noqa: F401
from reticle.replay_source import (MAX_GAP_MS, MINIMAP_LAG_MS, SELF_ID_MARGIN,  # noqa: F401
                                   SELF_ID_MIN_FRAMES, SELF_ID_MIN_SHARE, SELF_ID_RADIUS_M,
                                   VRFKIT_VERSION, facing_px_deg, to_px)
from reticle.replay_source import canon_name as canon  # noqa: F401
from reticle.replay_source import frames_to_replay as _frames_to_replay  # noqa: F401
from reticle.replay_source import living_widget_px as truth_px  # noqa: F401


REPLAY_TRUTH_VERSION = "replay-truth-0.4.0"
STORE = Path.home() / "reticle-store"


ANALYSIS = STORE / "analysis" / "replay-truth-20261006-lag"

#: 0.4.0 reads truth on the killfeed fit's own clock (`capture = a_ls + slope *
#: replay`, `capture_to_replay`) and per class: the self icon at `SELF_LAG_MS`,
#: every other player (teammates, enemies) at `REMOTE_LAG_MS`. Each is the median
#: over the development matches (9acf02f98283, c817691bcd15, d3dcfb182ab1) of the
#: best extra lag on moving isolated icons (`prototypes/minimap_lag.py --posthoc`,
#: task `teammate-lag-20261006`): self +33.3 ms (-50.0, +33.3, +33.3), teammates
#: +83.3 ms (+133.3, +83.3, +83.3) over `MINIMAP_LAG_MS`. The held-out match never
#: informed them. Remote players draw later than self
#: [domain:capture/minimap-remote-player-lag].
SELF_LAG_MS = MINIMAP_LAG_MS + 100.0 / 3.0
REMOTE_LAG_MS = MINIMAP_LAG_MS + 250.0 / 3.0

#: The stored minimap streams sample at 15 Hz; track minutes count frames of this grid.
GRID_HZ = 15.0


_stats = src.sample_stats


def _ang_deg(a, b):
    """Absolute angular difference in degrees, elementwise, in [0, 180]."""
    d = np.mod(np.asarray(a, float) - np.asarray(b, float), 360.0)
    return np.minimum(d, 360.0 - d)


def _rows(path: Path, needle: str | None = None):
    """Stream JSONL rows, skipping lines without `needle` before parsing."""
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if needle and needle not in line:
                continue
            if line.strip():
                yield json.loads(line)


def session_context(sid: str, geometry: Path | None = None) -> dict:
    """`reticle.replay_source.capture_replay_context` (the replay, player,
    teams, agents, the clock offset `a` fitted on stored deaths, the stored
    rounds and the baked `MapFrame`), plus this scorer's version, the stored
    `ally_icon` streams (`AI`) and its 8 m teammate gate in widget px.
    `score` and `replay_abilities` both use it.

    The context names the player (`replay_source.decide_player`): Riot's
    player where its record names one, with the replay's pick on the stored
    self track a cross-check in `out["self_identity"]`; without one the
    replay's pick, or a refusal with its reason."""
    ctx = src.capture_replay_context(sid, geometry, STORE)
    out = ctx["out"]
    out["replay_truth_version"] = REPLAY_TRUTH_VERSION
    if "refused" in out:
        return ctx
    al = out["align"]
    ctx["clock"] = (float(al["a_ls_ms"]), float(al["slope"]))
    out["clock"] = {"rule": "capture = a_ls + slope * replay (the killfeed least-squares fit)",
                    "a_ls_ms": round(ctx["clock"][0], 1), "slope": ctx["clock"][1],
                    "self_lag_ms": round(SELF_LAG_MS, 3), "remote_lag_ms": round(REMOTE_LAG_MS, 3)}
    ctx["AI"] = load_ally_icon(sid)
    ctx["gate"] = GATE_M * 100.0 * ctx["mf"].px_per_unit
    out["gate_px"] = round(ctx["gate"], 2)
    return ctx


#: Miss classes, assigned in this fixed order: the first that holds names the
#: miss (the M0 design of `minimap-replay-plan-20261005`).
MISS_CLASSES = ("widget_absent", "stacked", "under_stored_occluder", "edge", "isolated")
#: A facing error above this many degrees is a flip: the icon read backwards.
FLIP_DEG = 135.0
#: A wrong name this soon after its teammate left a stack counts as stack-born.
STACK_LEAVE_MS = 1000.0
#: The minimap lags (ms) a lag scan tries in place of the class's lag, on the
#: killfeed fit's clock.
LAG_SCAN_MS = tuple(range(-1000, 501, 50))
#: How far the nearest row of a slower occluder stream may lie from the frame
#: it stands for: half its step (`ability_glyph` 2 Hz, `minimap_dark` 4 Hz,
#: `spike` 15 Hz).
DISC_TOL_MS, DARK_TOL_MS, SPIKE_TOL_MS = 250.0, 125.0, 34.0


def classify_misses(flags: dict) -> np.ndarray:
    """One class per missed truth frame: the first of `MISS_CLASSES` whose
    boolean array in `flags` holds there, else `isolated`. A class absent from
    `flags` never holds."""
    n = len(next(iter(flags.values()))) if flags else 0
    names = MISS_CLASSES[:-1]
    conds = [np.asarray(flags[k], bool) if k in flags else np.zeros(n, bool) for k in names]
    if n == 0:
        return np.array([], dtype=object)
    return np.select(conds, list(names), default=MISS_CLASSES[-1]).astype(object)


def track_metrics(life, t, ent, n_obs: int, hz: float = GRID_HZ, flag=None) -> dict:
    """Identity switches, fragments and IDF1 of stored tracks against truth lives.

    One row per living truth frame: `life` (a truth life: one player in one
    round), `t` (its frame time, ms) and `ent` (the stored entity matched to
    it, -1 where none was). A switch is a matched frame whose entity differs
    from its life's previous matched frame; a fragment is a maximal run of a
    life's consecutive rows matched to one entity, which a miss or a switch
    ends; an entity run is a run a switch ends but a miss does not. IDF1 pairs lives with entities one to one (scipy's Hungarian
    solver) to maximise co-matched frames: 2 IDTP / (T + P), T the truth rows
    and P the `n_obs` stored observations of the class. `flag`, a boolean per
    row, counts the switches whose row it marks (`switches_flagged`)."""
    from scipy.optimize import linear_sum_assignment

    life = np.asarray(life, np.int64)
    t = np.asarray(t, float)
    ent = np.asarray(ent, np.int64)
    o = np.lexsort((t, life))
    life, t, ent = life[o], t[o], ent[o]
    m = ent >= 0
    lm, em = life[m], ent[m]
    sw = (lm[1:] == lm[:-1]) & (em[1:] != em[:-1])
    switches = int(np.sum(sw))
    flagged = None if flag is None else int(np.sum(sw & np.asarray(flag, bool)[o][m][1:]))
    new_life = np.r_[True, life[1:] != life[:-1]] if life.size else np.zeros(0, bool)
    prev = np.r_[-1, ent[:-1]] if ent.size else np.zeros(0, np.int64)
    fragments = int(np.sum(m & (new_life | (prev != ent))))
    # runs of one entity a switch ends but a miss does not
    lm_new = np.r_[True, lm[1:] != lm[:-1]] if lm.size else np.zeros(0, bool)
    entity_runs = int(np.sum(lm_new | np.r_[True, em[1:] != em[:-1]])) if lm.size else 0
    idtp = 0.0
    if m.any():
        ul, li = np.unique(lm, return_inverse=True)
        ue, ei = np.unique(em, return_inverse=True)
        C = np.zeros((ul.size, ue.size))
        np.add.at(C, (li, ei), 1.0)
        r, c = linear_sum_assignment(-C)
        idtp = float(C[r, c].sum())
    minutes = t.size / hz / 60.0
    lives_matched = int(np.unique(lm).size)
    return {"truth_frames": int(t.size), "matched_frames": int(m.sum()),
            "truth_minutes": round(minutes, 2), "lives": int(np.unique(life).size),
            "lives_matched": lives_matched, "entities": int(np.unique(em).size),
            "switches": switches, "switches_flagged": flagged,
            "switches_per_truth_minute": round(switches / minutes, 3) if minutes else None,
            "fragments": fragments,
            "fragments_per_matched_life": round(fragments / lives_matched, 3) if lives_matched else None,
            "entity_runs": entity_runs,
            "entity_runs_per_matched_life": (round(entity_runs / lives_matched, 3)
                                             if lives_matched else None),
            "idtp": int(idtp), "observations": int(n_obs),
            "idf1": round(2.0 * idtp / (t.size + n_obs), 4) if (t.size + n_obs) else None,
            "id_precision": round(idtp / n_obs, 4) if n_obs else None,
            "id_recall": round(idtp / t.size, 4) if t.size else None}


def capture_to_replay(t_cap, a_ms: float, slope: float, lag_ms: float):
    """Capture ms of a stored minimap frame -> the replay ms it shows, by the
    killfeed fit `capture = a_ms + slope * replay` and a minimap lag
    `lag_ms`. With slope 1 this is `replay_source.frames_to_replay`."""
    return (np.asarray(t_cap, float) - float(a_ms)) / float(slope) - float(lag_ms)


def _stamp(row: dict, *keys) -> dict:
    return {k: row.get(k) for k in keys if row.get(k) is not None}


def load_ally_icon(sid: str) -> dict:
    """`ally_icon` frames (index, time, widget drawn, self fit) and icons
    (frame, centre, teardrop facing)."""
    f_i, f_t, f_d, f_sx, f_sy = [], [], [], [], []
    i_f, i_t, i_x, i_y, i_fac = [], [], [], [], []
    stamp = {}
    for r in _rows(STORE / "events" / "ally_icon" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "frame":
            f_i.append(r["frame_idx"])
            f_t.append(r["t_ms"])
            f_d.append(bool(r.get("widget_drawn")))
            s_ = r.get("self")
            f_sx.append(s_[0] if s_ else np.nan)
            f_sy.append(s_[1] if s_ else np.nan)
        elif k == "icon":
            i_f.append(r["frame_idx"])
            i_t.append(r["t_ms"])
            i_x.append(r["cx"])
            i_y.append(r["cy"])
            i_fac.append(np.nan if r.get("facing") is None else r["facing"])
        elif k == "coverage":
            stamp = _stamp(r, "ally_icon_version", "teardrop_version", "icon_teardrop_version",
                           "stack_fit_version", "candidate_revision")
    o = np.argsort(np.asarray(f_i), kind="stable")
    return {"frame_idx": np.asarray(f_i, np.int64)[o], "t_ms": np.asarray(f_t, float)[o],
            "drawn": np.asarray(f_d, bool)[o], "self_x": np.asarray(f_sx, float)[o],
            "self_y": np.asarray(f_sy, float)[o],
            "icon_frame": np.asarray(i_f, np.int64), "icon_t": np.asarray(i_t, float),
            "icon_x": np.asarray(i_x, float), "icon_y": np.asarray(i_y, float),
            "icon_facing": np.asarray(i_fac, float), "stamp": stamp}


def load_round_entity(sid: str) -> dict:
    """`round_entity` teammate observations (family ally or self) with their
    entity's id and agent."""
    ents, stamp = {}, {}
    o_f, o_t, o_x, o_y, o_e, o_fam = [], [], [], [], [], []
    for r in _rows(STORE / "events" / "round_entity" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "observation" and r.get("family") in ("ally", "self"):
            o_f.append(r["frame_idx"])
            o_t.append(r["t_ms"])
            o_x.append(r["x"])
            o_y.append(r["y"])
            o_e.append(r.get("entity_id"))
            o_fam.append(r["family"])
        elif k == "entity":
            ents[r["id"]] = r.get("agent")
        elif k == "coverage":
            stamp = _stamp(r, "round_entity_version", "round_lifetime_version",
                           "agent_identity_version", "ally_icon_revision") | {
                "inputs": r.get("inputs")}
    codes = {e: i for i, e in enumerate(sorted({e for e in o_e if e}))}
    return {"frame_idx": np.asarray(o_f, np.int64), "t_ms": np.asarray(o_t, float),
            "x": np.asarray(o_x, float), "y": np.asarray(o_y, float),
            "entity": np.asarray([codes.get(e, -1) for e in o_e], np.int64),
            "agent": np.asarray([ents.get(e) for e in o_e], dtype=object),
            "family": np.asarray(o_fam, dtype=object), "stamp": stamp}


def load_team_vision(sid: str) -> dict:
    """`team_vision` frames' widget state and its self and ally icons with a facing."""
    f_i, f_w = [], []
    i_f, i_t, i_x, i_y, i_fac, i_role = [], [], [], [], [], []
    stamp = {}
    for r in _rows(STORE / "events" / "team_vision" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "frame":
            f_i.append(r["frame_idx"])
            f_w.append(r.get("widget"))
            for ic in r.get("icons") or []:
                if ic.get("role") in ("ally", "self") and ic.get("facing") is not None:
                    i_f.append(r["frame_idx"])
                    i_t.append(r["t_ms"])
                    i_x.append(ic["x"])
                    i_y.append(ic["y"])
                    i_fac.append(ic["facing"])
                    i_role.append(ic["role"])
        elif k == "coverage":
            stamp = _stamp(r, "team_vision_version", "teardrop_version", "track_version",
                           "lifecycle_version")
    return {"frame_idx": np.asarray(f_i, np.int64), "widget": np.asarray(f_w, dtype=object),
            "icon_frame": np.asarray(i_f, np.int64), "icon_t": np.asarray(i_t, float),
            "icon_x": np.asarray(i_x, float), "icon_y": np.asarray(i_y, float),
            "icon_facing": np.asarray(i_fac, float), "icon_role": np.asarray(i_role, dtype=object),
            "stamp": stamp}


def load_minimap_object(sid: str) -> dict:
    """`minimap_object` frames (index, time, refusal) and enemy icons."""
    f_i, f_t, f_r = [], [], []
    e_f, e_t, e_x, e_y, e_fac = [], [], [], [], []
    stamp = {}
    for r in _rows(STORE / "events" / "minimap_object" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "frame":
            f_i.append(r["frame_idx"])
            f_t.append(r["t_ms"])
            f_r.append(r.get("reason"))
            if r.get("reason") is None:
                for e in r.get("enemies") or []:
                    e_f.append(r["frame_idx"])
                    e_t.append(r["t_ms"])
                    e_x.append(e["x"])
                    e_y.append(e["y"])
                    e_fac.append(e["facing"] if e.get("facing") is not None
                                 and e.get("facing_reason") is None else np.nan)
        elif k == "coverage":
            stamp = _stamp(r, "minimap_object_version", "teardrop_version", "geometry_key")
    return {"frame_idx": np.asarray(f_i, np.int64), "t_ms": np.asarray(f_t, float),
            "reason": np.asarray(f_r, dtype=object),
            "enemy_frame": np.asarray(e_f, np.int64), "enemy_t": np.asarray(e_t, float),
            "enemy_x": np.asarray(e_x, float), "enemy_y": np.asarray(e_y, float),
            "enemy_facing": np.asarray(e_fac, float), "stamp": stamp}


def load_enemy_track(sid: str) -> dict | None:
    """`enemy_track` observations with their entity's id and agent, or None."""
    p = STORE / "events" / "enemy_track" / f"{sid}.jsonl"
    if not p.is_file():
        return None
    ents, stamp = {}, {}
    o_f, o_t, o_x, o_y, o_e = [], [], [], [], []
    for r in _rows(p):
        k = r.get("kind")
        if k == "observation":
            o_f.append(r["frame_idx"])
            o_t.append(r["t_ms"])
            o_x.append(r["x"])
            o_y.append(r["y"])
            o_e.append(r.get("entity_id"))
        elif k == "entity":
            ents[r["id"]] = r.get("agent")
        elif k == "summary":
            stamp = _stamp(r, "enemy_track_version", "minimap_object_version",
                           "agent_identity_version", "lineup_version")
    codes = {e: i for i, e in enumerate(sorted({e for e in o_e if e}))}
    return {"frame_idx": np.asarray(o_f, np.int64), "t_ms": np.asarray(o_t, float),
            "x": np.asarray(o_x, float), "y": np.asarray(o_y, float),
            "entity": np.asarray([codes.get(e, -1) for e in o_e], np.int64),
            "agent": np.asarray([ents.get(e) for e in o_e], dtype=object), "stamp": stamp}


def load_occluders(sid: str) -> dict:
    """Stored things that can cover an icon: pings (active spans), accepted
    spike glyphs, ability glyph discs and `minimap_dark`'s grey-dark masks
    (smoke-like cover; its `occluded` mask marks teammate icons themselves,
    so it is not read), plus each frame's widget state where a witness other
    than `ally_icon` reads it."""
    ev = STORE / "events"
    pings = defaultdict(dict)
    for r in _rows(ev / "ping" / f"{sid}.jsonl"):
        p = pings[r["entity_id"]]
        if r.get("state") == "active" and r.get("position"):
            p["t0"], p["x"], p["y"] = float(r["t_ms"]), *map(float, r["position"])
        elif r.get("event_kind") == "entity_deleted":
            p["t1"] = float(r["t_ms"])
    ping = np.array([[p["t0"], p.get("t1", p["t0"] + 1000.0 * 8), p["x"], p["y"]]
                     for p in pings.values() if "t0" in p], float).reshape(-1, 4)
    sg = []
    for r in _rows(ev / "spike" / f"{sid}.jsonl", '"kind":"frame"'):
        for g in r.get("glyphs") or []:
            if g.get("reason") is None:
                sg.append((r["t_ms"], g["cx"], g["cy"], 0.5 * float(g.get("side") or 0.0)))
    discs = []
    for r in _rows(ev / "ability_glyph" / f"{sid}.jsonl", '"kind":"disc"'):
        discs.append((r["t_ms"], r["cx"], r["cy"], float(r.get("r") or 0.0)))
    dark_t, dark_m, dark_drawn = [], [], []
    stamps = {}
    for r in _rows(ev / "minimap_dark" / f"{sid}.jsonl"):
        if r.get("kind") == "frame":
            dark_t.append(r["t_ms"])
            dark_drawn.append(bool(r.get("widget_drawn")))
            dark_m.append(r.get("grey_dark") if r.get("reason") is None else None)
        elif r.get("kind") == "coverage":
            stamps["minimap_dark"] = r.get("minimap_dark_version")
    sg = np.array(sorted(sg), float).reshape(-1, 4)
    discs = np.array(sorted(discs), float).reshape(-1, 4)
    o = np.argsort(np.asarray(dark_t, float), kind="stable")
    return {"ping": ping, "spike_glyph": sg, "disc": discs,
            "dark_t": np.asarray(dark_t, float)[o], "dark_drawn": np.asarray(dark_drawn, bool)[o],
            "dark_mask": [dark_m[i] for i in o], "stamps": stamps}


def _near_points(t, x, y, pts, tol_ms, reach):
    """Per query (t, x, y), whether a point row (t, x, y, radius) of `pts`
    (sorted by t) lies within `tol_ms` and within `reach` + its radius."""
    hit = np.zeros(np.asarray(t).shape, bool)
    if pts.size == 0 or hit.size == 0:
        return hit
    lo = np.searchsorted(pts[:, 0], t - tol_ms, side="left")
    hi = np.searchsorted(pts[:, 0], t + tol_ms, side="right")
    for k in range(int((hi - lo).max(initial=0))):
        i = lo + k
        ok = i < hi
        ii = np.clip(i, 0, len(pts) - 1)
        d = np.hypot(pts[ii, 1] - x, pts[ii, 2] - y)
        hit |= ok & (d <= reach + pts[ii, 3])
    return hit


def _under_dark(t, x, y, occ, reach):
    """Per query, whether the nearest `minimap_dark` frame within
    `DARK_TOL_MS` marks grey-dark floor within `reach` px."""
    from reticle.lighting import unpack_mask

    hit = np.zeros(np.asarray(t).shape, bool)
    dt = occ["dark_t"]
    if dt.size == 0 or hit.size == 0:
        return hit
    j = np.clip(np.searchsorted(dt, t), 1, dt.size - 1) if dt.size > 1 else np.zeros(t.shape, int)
    if dt.size > 1:
        j = np.where(np.abs(dt[j - 1] - t) <= np.abs(dt[j] - t), j - 1, j)
    ok = np.abs(dt[j] - t) <= DARK_TOL_MS
    r = int(math.ceil(reach))
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    keep = dx ** 2 + dy ** 2 <= reach ** 2
    dx, dy = dx[keep], dy[keep]
    for u in np.unique(j[ok]):
        packed = occ["dark_mask"][u]
        if not packed:
            continue
        m = unpack_mask(packed)
        sel = np.flatnonzero(ok & (j == u))
        xs = np.clip(np.rint(x[sel])[:, None] + dx[None, :], 0, m.shape[1] - 1).astype(int)
        ys = np.clip(np.rint(y[sel])[:, None] + dy[None, :], 0, m.shape[0] - 1).astype(int)
        hit[sel] = m[ys, xs].any(axis=1)
    return hit


def _facing_block(err) -> dict:
    e = np.asarray(err, float)
    e = e[np.isfinite(e)]
    return {"n": int(e.size), "err_deg": _stats(e),
            "flip_share": round(float(np.mean(e > FLIP_DEG)), 4) if e.size else None,
            "within_30deg": round(float(np.mean(e <= 30.0)), 4) if e.size else None}


def _facing_lag_scan(rp, mf, subj, t_cap, fac, clock) -> dict:
    """Median facing error per minimap lag in `LAG_SCAN_MS`, the pairs fixed."""
    subj = np.asarray(subj, dtype=object)
    scan = {}
    for L in LAG_SCAN_MS:
        err = np.full(t_cap.size, np.nan)
        for s in set(subj.tolist()):
            m = subj == s
            q = rp.sample(s, capture_to_replay(t_cap[m], *clock, L))
            err[m] = _ang_deg(facing_px_deg(mf, q["x"], q["y"], q["yaw"]), fac[m])
        scan[int(L)] = round(float(np.nanmedian(err)), 3) if np.isfinite(err).any() else None
    ok = {k: v for k, v in scan.items() if v is not None}
    return {"median_err_deg_by_lag_ms": scan, "best_lag_ms": min(ok, key=ok.get) if ok else None}


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Counter):
        return dict(o)
    raise TypeError(type(o))


#: Teammate gate in metres (Riot units are centimetres).
GATE_M = 8.0
