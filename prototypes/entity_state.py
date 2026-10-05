r"""Ally player slots and a position belief for every living slot, every frame.

    .\.venv\Scripts\python.exe prototypes\entity_state.py score SESSION [SESSION ...] --pool NAME [--binding post_round|causal] [--record]
    .\.venv\Scripts\python.exe prototypes\entity_state.py replay 9acf02f98283 [--binding post_round|causal] [--record]

Stages 1 and 2a of [docs/ENTITY_STATE.md](../docs/ENTITY_STATE.md), as a
prototype. `--binding post_round` (the default) binds fits as stage 1 did;
`--binding causal` binds them frame by frame (`entity_binding.py`, stage
2a). Outputs of both go to `<store>/analysis/entity-binding-20261004/`,
named by mode.
Not wired (`"wire": "no"` in the store's `notes/predictions.jsonl`): nothing
in `reticle/` reads it. It reads STORED rows only (`ally_icon` frames,
`round_entity` observations and entities, the death verdicts, the lineup,
the round table) through `crowd_region.Session`, decodes nothing and reads
no crop.

Slots
-----
Five ally slots, keyed `<session>:ally:slot:<k>` as the lineup keys them;
each slot's agent is the arbiter's verdict on that lineup slot
(`lineup.load_lineup`, its `agent_identity`). A slot opens `alive` at each
round's start (`rounds.round_bounds`' clock reset) and stays open through
the post-round period [domain:rounds/post-round-period] until the next
round starts. The death owner's verdicts close it: a named ally victim
(`adjudication.death`, `kind == death_verdict`) closes its slot at the
verdict's time; a second-life death leaves it open
[domain:rounds/resurrection-mechanics]; a revive entry reopens it
[domain:killfeed/revive-entries]; an unnamed ally victim closes nothing and
counts as `maybe_dead`. Nothing here infers a disconnect.

Binding fits to slots (the post-round path; `entity_binding.py` holds the causal one)
--------------------------------------------------------------------------------------
Stored fits are bound through the `round_entity` entities the tracker owner
built (`round_lifetimes`), never re-tracked here. The self entity binds to
the player's slot (`lineup.load_lineup`'s `player`, the arbiter's), and its
fits count only while that slot is open: after the player dies the self
icon shows the spectated teammate [domain:minimap/self-icon-shows-spectated],
and those fits are left unbound (the spectating witness is not read here).
A named entity binds to the slot the arbiter names for its agent; its
verdict pools the entity's whole life, so this is the post-round answer,
`rests_on` the stored verdict. An unnamed entity, or a named one whose slot
another entity already holds over more than `CONFLICT_SHARE` of its frames,
binds by continuity to the free open slot whose last fix it lies nearest in
excess of the reach bound; with no free open slot it is a non-player
(`no_free_slot`), counted and never dropped silently.

Beliefs (amended design, section 2)
-----------------------------------
Every open slot holds one belief per frame, computed by array operations
over (slot, frame):

* `fit`: a disc of `r_fit = r_icon + v_max * dt_frame` round the bound fit,
  `r_icon` the reader's measured icon radius in metres;
* `crowd`: no fit, and the last fix lay within one icon diameter of another
  slot's fit (the host) [domain:minimap/coincident-icons], which still has
  a fit: the point is the host's fit; the region is the core disc
  (`2 r_icon + r_fit` round the host) together with the slot's own reach
  disc. The core is scored apart and never stands as the region;
* `reach`: the Euclidean disc of `R = v_max * (t - t_fix) + r_fit` round the
  last fix of the round. `v_max` is the character's top ground speed from
  the game files [domain:game_data/character-movement-speeds] in metres
  [domain:game_data/game-units-centimetres]. Negative evidence is off
  (`p_det = 0`): the stored reader records neither its search nor a floor
  residual;
* `unanchored`: no fix since the round opened; the region is the map.

World metres come from valorant-api's map constants and the geometry's
`shade_fit` (`riot_ground_truth.MapFrame`, built from the map name the
geometry stores, never from a Riot record), inverted as one affine.

Scoring (truth is evaluation only)
----------------------------------
`score`: at each Riot kill instant (`riot_ground_truth.py`'s alignment and
`truth_locations`), every living teammate, the player excluded and reported
apart: whether its slot is open (`has_slot`, which must hold for all),
whether the reported region holds the truth (calibration, by kind and by
time since the last fix), region radius and area by kind, the crowd core's
containment, the fit point error, and the stored ring fits' located share
on the same instants (ring fits within `riot_ground_truth.GATE_M`, the
`ally_prior` baseline). `replay`: the same on every drawn frame of a
capture with a replay. Each session writes one output under
`<store>/analysis/entity-state-20261004/` and is skipped when that output
exists (`--force` reruns it).

Outcome (2026-10-04, entity-state-0.2.0)
----------------------------------------
Pre-registered at 0.1.0; 0.2.0 is one development revision on the dev
scores (a death closes only inside its own round; only witnessed fits
anchor a reach region). Held out (six Riot matches chosen by a fixed hash
before measuring, scored once), of
[metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#n=1799] living teammates at kill
instants, the reported region holds the truth on
[metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#calibration=0.9355], short of the
0.98 target: fit [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#fit_calibration=0.9503],
crowd [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#crowd_calibration=0.9722]
(its core alone [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#crowd_core_calibration=0.75]),
reach [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#reach_calibration=0.9146] with
a median radius of [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#reach_radius_m_median=10.38] m.
[metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#has_slot_missing=8] living-teammate
instants found their slot closed: two post-round deaths carry the next
round's `round_no` where that round's start fell back to the score
increment. Fits lie a median
[metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#fit_point_err_m_median=0.54] m from
the truth. On the replay's every drawn frame the teammates' calibration is
[metric:entity_state/replay@9acf02f98283#calibration=0.944], reach
[metric:entity_state/replay@9acf02f98283#reach_calibration=0.912]. A third of
the reach misses lie within 3 m of the disc; the rest are anchored on a fit
bound to the wrong teammate, or on a witnessed fit that sits on a non-player
drawing or off the map, so the region is only as good as the binding and
the fits it binds. The 8 closed-slot kill instants sample a larger
every-frame gap: on `c62c2b06bcfb` the judge counted 504 of 41617 alive
teammate-frames with no open slot, 416 of them Sage's, closed by a
post-round death stamped with the next round, and 22 all-slot closures at
round starts; the stage 2a hunt, which skips 3 s after each buy start,
counts [metric:entity_state/riot_pool@heldout6es_post_round#c62c2b06bcfb.hunt_no_slot=414]
of [metric:entity_state/riot_pool@heldout6es_post_round#c62c2b06bcfb.hunt_alive_frames=41309].
The belief law costs at most
[metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#cost_us_per_frame_max=5.49] us a
frame as a post-round batch and
[metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#record_bytes_per_frame=120] bytes a
frame raw.

Outcome (2026-10-04, entity-state-0.3.0, stage 2a)
--------------------------------------------------
The second look at the held-out six, scored once per mode, and the causal
mode rescored once after the entity-binding-0.1.1 causal-leak correction
(a correction, not a third look): the causal binding holds a living teammate on
[metric:entity_state/riot_pool@heldout6es_causal#calibration=0.9689] of kill
instants, the post-round binding on
[metric:entity_state/riot_pool@heldout6es_post_round#calibration=0.9355]
(unchanged from 0.2.0). Its outcome, the every-frame hunt and the viewed
misses are in `entity_binding.py`'s docstring.

The every-frame hunt (`hunt_riot`) counts, over Riot's alive intervals of
each teammate, the drawn frames whose slot is closed (`no_slot`), open
with no fit bound since its round opened (`no_position`), or open with
only unwitnessed fits (`unbounded`).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: 0.1.0 (2026-10-04): the design as pre-registered (store `notes/predictions.jsonl`,
#: task entity-state-20261004, ts 2026-10-05T04:20:38Z). 0.2.0 (development, after the
#: dev scores, before any held-out score): a death closes a slot only inside its own
#: round (`round_no`), and only witnessed fits (self, named ring) anchor a reach region;
#: continuity and named stack fits are `fit_unnamed`. 0.3.0 (stage 2, 2026-10-04): a
#: `binding` mode, `post_round` (0.2.0's binding, unchanged) or `causal`
#: (`entity_binding`); the scorer adds `fit_bound_share` and the every-frame hunt.
ENTITY_STATE_VERSION = "entity-state-0.3.0"
STORE = Path.home() / "reticle-store"
ANALYSIS = STORE / "analysis" / "entity-state-20261004"
#: Stage 2 outputs, both binding modes, file names carrying the mode.
ANALYSIS_BINDING = STORE / "analysis" / "entity-binding-20261004"

#: Belief kinds, as stored (u1). `fit_unnamed` (0.2.0) is a fit whose
#: binding no witness names: a continuity binding or a named stack fit.
CLOSED, FIT, CROWD, REACH, UNANCHORED, FIT_UNNAMED = 0, 1, 2, 3, 4, 5
KINDS = {CLOSED: "closed", FIT: "fit", CROWD: "crowd", REACH: "reach", UNANCHORED: "unanchored",
         FIT_UNNAMED: "fit_unnamed"}
#: How a fit was bound to its slot (u1): the self channel, a named ring fit,
#: a named stack fit, continuity. Only the first two are witnessed.
HOW_SELF, HOW_NAMED_RING, HOW_NAMED_STACK, HOW_CONTINUITY = 1, 2, 3, 4
WITNESSED = (HOW_SELF, HOW_NAMED_RING)
#: A named entity whose slot another entity holds over more than this share
#: of its frames binds by continuity instead.
CONFLICT_SHARE = 0.2
#: Strata of time since the slot's last fix, in seconds (section 8).
STRATA_S = (0.0, 1.0, 5.0, 15.0)


def _below_normal() -> None:
    """Below Normal priority and one OpenCV thread: other work shares this CPU."""
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:                                   # noqa: BLE001 -- best effort
        pass
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:                                   # noqa: BLE001
        pass


def v_max_m_s() -> float:
    """The top speed the game's movement tuning allows, in m/s
    [domain:game_data/character-movement-speeds]: the base top speed times
    the largest state multiplier, 6.75 x 1.1 = 7.425 m/s. The 1.1 is the
    Jumping state's multiplier, the largest of the states; running's is
    unserialized and taken as 1. The bound is a reach ceiling, not the run
    speed (6.75 m/s)."""
    from reticle import domain
    sp = domain.load()["game_data/character-movement-speeds"].values
    return float(sp["speed"]["base_max_speed_m_s"]) * max(1.0, *sp["state_multiplier"].values())


def units_per_m() -> float:
    """Game units per metre [domain:game_data/game-units-centimetres]."""
    from reticle import domain
    return float(domain.load()["game_data/game-units-centimetres"].values["units_per_m"])


# ----------------------------------------------------------------- the belief law (pure)

def last_fix(has: np.ndarray, seg_start: np.ndarray) -> np.ndarray:
    """(S, F) index of each slot's last fit at or before each frame within the
    frame's round segment, -1 where none. `seg_start[f]` is the first frame of
    f's segment."""
    S, F = has.shape
    idx = np.where(has, np.arange(F)[None, :], -1)
    lf = np.maximum.accumulate(idx, axis=1)
    return np.where(lf >= seg_start[None, :], lf, -1)


def nearest_other(X: np.ndarray, Y: np.ndarray, has: np.ndarray, d_max: float) -> np.ndarray:
    """(S, F) the nearest OTHER slot with a fit in the same frame within
    `d_max` metres of each slot's fit, -1 where none (or the slot has no fit)."""
    S, F = has.shape
    dx = X[:, None, :] - X[None, :, :]
    dy = Y[:, None, :] - Y[None, :, :]
    D = np.hypot(dx, dy)                                 # (S, S, F)
    ok = has[:, None, :] & has[None, :, :] & ~np.eye(S, dtype=bool)[:, :, None]
    D = np.where(ok, D, np.inf)
    j = np.argmin(D, axis=1)                             # (S, F)
    dmin = np.take_along_axis(D, j[:, None, :], axis=1)[:, 0, :]
    return np.where(dmin <= d_max, j, -1)


def beliefs(t_ms: np.ndarray, X: np.ndarray, Y: np.ndarray, has: np.ndarray,
            open_: np.ndarray, seg_start: np.ndarray, *, r_fit: float, r_icon: float,
            v_max: float, wit: np.ndarray | None = None) -> dict:
    """Every slot's belief at every frame, as arrays over (slot, frame).

    `X, Y` are the bound fits in metres (NaN where none); `has` marks them,
    and only fits inside an open slot count. `wit` marks the fits whose
    binding a witness names (default: all); only those anchor a reach region,
    and an unwitnessed fit is `fit_unnamed`, its region the fit disc together
    with the reach grown from the last witnessed fix (0.2.0). Returns the
    kind, the point, the reach anchor and radius, and the crowd core's centre
    and radius."""
    S, F = has.shape
    has = has & open_
    wit = has if wit is None else (wit & has)
    lf = last_fix(wit, seg_start)
    valid = lf >= 0
    lfc = np.where(valid, lf, 0)
    rows = np.arange(S)[:, None]
    ax = np.where(valid, X[rows, lfc], np.nan)
    ay = np.where(valid, Y[rows, lfc], np.nan)
    dt_s = np.where(valid, (t_ms[None, :] - t_ms[lfc]) / 1000.0, np.nan)
    R = v_max * dt_s + r_fit
    host_now = nearest_other(X, Y, has, 2.0 * r_icon)
    host = np.where(valid, host_now[rows, lfc], -1)
    hc = np.where(host >= 0, host, 0)
    cols = np.arange(F)[None, :]
    host_has = (host >= 0) & has[hc, cols]
    kind = np.full((S, F), CLOSED, np.uint8)
    kind[open_ & ~has & ~valid] = UNANCHORED
    kind[open_ & ~has & valid] = REACH
    kind[open_ & ~has & valid & host_has] = CROWD
    kind[has & ~wit] = FIT_UNNAMED
    kind[wit] = FIT
    fitlike = (kind == FIT) | (kind == FIT_UNNAMED)
    hx = np.where(kind == CROWD, X[hc, cols], np.nan)
    hy = np.where(kind == CROWD, Y[hc, cols], np.nan)
    px = np.where(fitlike, X, np.where(kind == CROWD, hx, ax))
    py = np.where(fitlike, Y, np.where(kind == CROWD, hy, ay))
    return {"kind": kind, "x": px, "y": py, "ax": ax, "ay": ay,
            "R": np.where(kind == FIT, r_fit, R), "dt_s": np.where(kind == FIT, 0.0, dt_s),
            "hx": hx, "hy": hy, "rc": 2.0 * r_icon + r_fit, "host": np.where(kind == CROWD, host, -1),
            "lf": lf, "lf_any": last_fix(has, seg_start), "r_fit": r_fit}


def contains(B: dict, s: np.ndarray, f: np.ndarray, x: np.ndarray, y: np.ndarray,
             tol: float = 0.0) -> dict:
    """Whether each query point lies in its slot's region at its frame.

    Returns `region` (the reported region: the fit disc; the fit disc
    together with the reach for `fit_unnamed`; the crowd core together with
    the reach disc; the reach disc; True for `unanchored` and for a
    `fit_unnamed` with no witnessed fix; False for a closed slot) and `core`
    (the crowd core alone, the fit disc alone for `fit_unnamed`, else
    `region`). `tol` widens every radius: the scorer's registration
    tolerance, never the belief's."""
    k = B["kind"][s, f]
    d_pt = np.hypot(x - B["x"][s, f], y - B["y"][s, f])
    d_an = np.hypot(x - B["ax"][s, f], y - B["ay"][s, f])
    d_h = np.hypot(x - B["hx"][s, f], y - B["hy"][s, f])
    R = B["R"][s, f]
    in_fit = np.isin(k, (FIT, FIT_UNNAMED)) & (d_pt <= B["r_fit"] + tol)
    in_reach = np.isin(k, (REACH, CROWD, FIT_UNNAMED)) & (d_an <= R + tol)
    in_core = (k == CROWD) & (d_h <= B["rc"] + tol)
    free = (k == UNANCHORED) | ((k == FIT_UNNAMED) & ~np.isfinite(R))
    region = in_fit | in_reach | in_core | free
    core = np.where(k == CROWD, in_core, np.where(k == FIT_UNNAMED, in_fit, region))
    return {"region": region, "core": core, "kind": k, "point_err": d_pt,
            "dt_s": B["dt_s"][s, f], "R": R}


def union_area(r1, r2, d) -> np.ndarray:
    """Area of the union of two discs of radii r1, r2 whose centres lie d apart."""
    r1, r2, d = (np.asarray(v, float) for v in (r1, r2, d))
    a = np.pi * r1 ** 2 + np.pi * r2 ** 2
    lo, hi = np.abs(r1 - r2), r1 + r2
    inner = d <= lo
    sep = d >= hi
    with np.errstate(invalid="ignore", divide="ignore"):
        c1 = np.clip((d ** 2 + r1 ** 2 - r2 ** 2) / (2 * d * r1), -1, 1)
        c2 = np.clip((d ** 2 + r2 ** 2 - r1 ** 2) / (2 * d * r2), -1, 1)
        lens = (r1 ** 2 * np.arccos(c1) + r2 ** 2 * np.arccos(c2)
                - 0.5 * np.sqrt(np.clip((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2)
                                        * (d + r1 + r2), 0, None)))
    lens = np.where(inner, np.pi * np.minimum(r1, r2) ** 2, np.where(sep, 0.0, lens))
    return a - lens


def region_area(B: dict, s: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Area in m^2 of each queried region (NaN for `unanchored`, a
    `fit_unnamed` with no witnessed fix, and closed)."""
    k = B["kind"][s, f]
    R = B["R"][s, f]
    d = np.hypot(B["hx"][s, f] - B["ax"][s, f], B["hy"][s, f] - B["ay"][s, f])
    crowd = union_area(R, np.full_like(R, B["rc"]), np.nan_to_num(d))
    du = np.hypot(B["x"][s, f] - B["ax"][s, f], B["y"][s, f] - B["ay"][s, f])
    unnamed = union_area(np.full_like(R, B["r_fit"]), R, np.nan_to_num(du))
    return np.where(k == CROWD, crowd, np.where(k == FIT_UNNAMED, unnamed,
                    np.where(np.isin(k, (FIT, REACH)), np.pi * R ** 2, np.nan)))


def storage_record(B: dict, obs: np.ndarray) -> np.ndarray:
    """The per-frame struct-of-arrays this prototype would store: frames by
    slots, one record per slot-frame."""
    S, F = B["kind"].shape
    rec = np.zeros((F, S), dtype=[("kind", "u1"), ("host", "i1"), ("x", "f4"), ("y", "f4"),
                                  ("ax", "f4"), ("ay", "f4"), ("R", "f2"), ("obs", "i4")])
    rec["kind"] = B["kind"].T
    rec["host"] = B["host"].T
    rec["x"], rec["y"] = B["x"].T, B["y"].T
    rec["ax"], rec["ay"] = B["ax"].T, B["ay"].T
    rec["R"] = np.minimum(np.nan_to_num(B["R"], nan=0.0), 6.0e4).T
    rec["obs"] = obs.T
    return rec


# ----------------------------------------------------------------- the world frame

def world_frame(sid: str):
    """The (map, profile) geometry's map frame from valorant-api's constants,
    found by the map name the geometry stores (no Riot record), and its
    inverse as metres from baked px: (mf, to_m, m_per_px) or (None, reason)."""
    import riot_ground_truth as rg
    from reticle import geometry
    from reticle.store import Store
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    mname = geometry.map_of(sid, STORE)
    mi = [m for m in ref.maps.values() if rg.canon(m.get("displayName")) == rg.canon(mname)]
    if len(mi) != 1:
        return None, f"no_map_record:{mname}"
    man = Store(STORE).read_manifest(sid)
    mf, why = rg.map_frame_for(sid, man, ref, {"match": {"matchInfo": {"mapId": mi[0]["mapUrl"]}}},
                               STORE)
    if mf is None:
        return None, why
    p0 = np.asarray(mf.to_px(0.0, 0.0))
    M = np.column_stack([np.asarray(mf.to_px(1000.0, 0.0)) - p0,
                         np.asarray(mf.to_px(0.0, 1000.0)) - p0]) / 1000.0
    Mi = np.linalg.inv(M)
    upm = units_per_m()

    def to_m(px, py):
        q = np.stack([np.asarray(px, float) - p0[0], np.asarray(py, float) - p0[1]])
        u = np.tensordot(Mi, q, axes=1)
        return u[0] / upm, u[1] / upm

    m_per_px = 1.0 / (mf.px_per_unit * upm)
    return (mf, to_m, m_per_px), None


# ----------------------------------------------------------------- slots from stored rows

def lineup_slots(sid: str) -> dict:
    """The ally slots: agent per lineup slot from the arbiter, and the player's slot."""
    from reticle import lineup
    L = lineup.load_lineup(sid, STORE)
    if L is None:
        return {"refused": "no_lineup"}
    ver = {v.get("entity_id"): v for v in L.get("agent_identity") or []}
    slots = []
    for k in range(5):
        v = ver.get(f"{sid}:ally:slot:{k}") or {}
        slots.append({"key": f"{sid}:ally:slot:{k}", "agent": v.get("agent"),
                      "status": v.get("status"), "reason": v.get("reason")})
    pl = L.get("player") or {}
    return {"slots": slots, "player_slot": pl.get("slot"), "player_agent": pl.get("agent"),
            "lineup_version": L.get("version")}


def _canon(a):
    return None if a is None else str(a).strip().lower().replace("/", "")


def lifecycle(sid: str, S, slots: list[dict]) -> dict:
    """(5, F) open mask from rounds and the death owner's verdicts, plus the
    events that set it."""
    F = S.fr_t.size
    t = S.fr_t
    rounds = sorted(S.rounds, key=lambda r: float(r["t_start_ms"]))
    starts = np.asarray([float(r["t_start_ms"]) for r in rounds], float)
    round_idx = {r.get("round_no"): i for i, r in enumerate(rounds) if r.get("round_no") is not None}
    seg = np.searchsorted(starts, t, side="right") - 1            # -1 before the first round
    seg_start_idx = np.searchsorted(t, starts)
    seg_start = np.where(seg >= 0, seg_start_idx[np.clip(seg, 0, None)], F)
    open_ = np.repeat((seg >= 0)[None, :], 5, axis=0)
    by_agent = {_canon(s["agent"]): k for k, s in enumerate(slots) if s["agent"]}
    ev = Counter()
    events = []
    rows = sorted((d for d in S.deaths if d.get("side") == "ally"), key=lambda d: d["t_ms"])
    for d in rows:
        if d.get("is_second_life"):
            ev["second_life"] += 1
            continue
        k = by_agent.get(_canon(d.get("victim")))
        if d.get("victim") is None:
            ev["maybe_dead_unnamed"] += 1
            continue
        if k is None:
            ev["victim_no_slot"] += 1
            events.append({"t_ms": d["t_ms"], "victim": d.get("victim"), "what": "victim_no_slot"})
            continue
        f0 = int(np.searchsorted(t, float(d["t_ms"])))
        if f0 >= F:
            continue
        # the death owner's round, not the time segment: a round whose start
        # fell back to the score increment would put a post-round death into
        # the next round (0.2.0)
        r = round_idx.get(d.get("round_no"), seg[f0])
        f1 = int(seg_start_idx[r + 1]) if r + 1 < starts.size else F
        if f0 >= f1:
            ev["death_past_its_round"] += 1
            continue
        if d.get("is_revive"):
            open_[k, f0:f1] = True
            ev["revive"] += 1
            events.append({"t_ms": d["t_ms"], "slot": k, "what": "revive", "death_id": d.get("death_id")})
        else:
            if not open_[k, f0]:
                ev["death_of_closed_slot"] += 1
            open_[k, f0:f1] = False
            ev["close"] += 1
            events.append({"t_ms": d["t_ms"], "slot": k, "what": "close", "death_id": d.get("death_id")})
    return {"open": open_, "seg": seg, "seg_start": seg_start, "events": events, "counts": dict(ev),
            "starts": starts}


def bind_entities(S, slots: list[dict], player_slot, open_: np.ndarray, seg_start: np.ndarray,
                  to_m, v_max: float, r_fit: float) -> dict:
    """Bind the stored entities' fits to slots (module docstring). Returns
    (5, F) X, Y in metres, the observation row per slot-frame and counts."""
    F = S.fr_t.size
    t = S.fr_t
    fpos = np.searchsorted(S.fr_f, S.ob_f)
    ok = (fpos < F) & (S.fr_f[np.clip(fpos, 0, F - 1)] == S.ob_f)
    mx, my = to_m(S.ob_x, S.ob_y)
    X = np.full((5, F), np.nan)
    Y = np.full((5, F), np.nan)
    obs = np.full((5, F), -1, np.int64)
    occ = np.zeros((5, F), bool)
    by_agent = {_canon(s["agent"]): k for k, s in enumerate(slots) if s["agent"]}
    c = Counter()
    order = np.argsort(S.ob_e, kind="stable")
    e_sorted = S.ob_e[order]
    bounds = np.searchsorted(e_sorted, np.arange(len(S.ent_ids) + 1))
    ents = []
    for code, eid in enumerate(S.ent_ids):
        idx = order[bounds[code]:bounds[code + 1]]
        idx = idx[ok[idx]]
        if not idx.size:
            continue
        fr = fpos[idx]
        fr, first = np.unique(fr, return_index=True)       # one fit per entity-frame
        idx = idx[first]
        row = S.ents.get(eid) or {}
        ents.append({"id": eid, "idx": idx, "fr": fr, "self": bool(S.ob_self[idx].any()),
                     "agent": row.get("agent")})

    how = np.zeros((5, F), np.uint8)
    stack = np.asarray(getattr(S, "ob_stack", np.zeros(S.ob_f.size, bool)), bool)

    def put(k, e, keep, route):
        fr, idx = e["fr"][keep], e["idx"][keep]
        X[k, fr], Y[k, fr] = mx[idx], my[idx]
        obs[k, fr] = idx
        occ[k, fr] = True
        if route == HOW_NAMED_RING:
            how[k, fr] = np.where(stack[idx], HOW_NAMED_STACK, HOW_NAMED_RING)
        else:
            how[k, fr] = route
        return int(keep.sum())

    unnamed = [e for e in ents if not (e["self"] or e["agent"])]
    c["unnamed_entities"] = len(unnamed)
    # self first, then named entities, longest first
    named = sorted((e for e in ents if e["self"] or e["agent"]),
                   key=lambda e: (not e["self"], -e["fr"].size))
    for e in named:
        k = player_slot if e["self"] else by_agent.get(_canon(e["agent"]))
        if k is None:
            c["named_no_slot"] += 1
            unnamed.append(e)
            continue
        live = open_[k, e["fr"]]
        if e["self"]:
            n = put(k, e, live & ~occ[k, e["fr"]], HOW_SELF)
            c["self_fits"] += n
            c["self_fits_after_close"] += int((~live).sum())
            continue
        clash = occ[k, e["fr"]]
        if clash.mean() > CONFLICT_SHARE or live.mean() < 0.5:
            c["named_conflict" if clash.mean() > CONFLICT_SHARE else "named_slot_closed"] += 1
            unnamed.append(e)
            continue
        c["named_bound"] += 1
        c["named_fits"] += put(k, e, live & ~clash, HOW_NAMED_RING)
        c["named_fits_dropped"] += int((~(live & ~clash)).sum())
    unnamed.sort(key=lambda e: e["fr"][0])
    for e in unnamed:
        f0 = int(e["fr"][0])
        best = None
        for k in range(5):
            if not open_[k, f0] or occ[k, e["fr"]].mean() > CONFLICT_SHARE:
                continue
            prev = np.flatnonzero(occ[k, seg_start[f0]:f0])
            if prev.size:
                fl = int(seg_start[f0] + prev[-1])
                d = math.hypot(X[k, fl] - mx[e["idx"][0]], Y[k, fl] - my[e["idx"][0]])
                excess = max(0.0, d - (v_max * (t[f0] - t[fl]) / 1000.0 + r_fit))
            else:
                d, excess = float("inf"), 0.0
            key = (excess, d)
            if best is None or key < best[0]:
                best = (key, k)
        if best is None:
            c["non_player_no_free_slot"] += 1
            c["non_player_fits"] += int(e["fr"].size)
            continue
        k = best[1]
        c["continuity_bound"] += 1
        c["continuity_relocation"] += int(best[0][0] > 0)
        keep = open_[k, e["fr"]] & ~occ[k, e["fr"]]
        c["continuity_fits"] += put(k, e, keep, HOW_CONTINUITY)
    return {"X": X, "Y": Y, "obs": obs, "has": occ, "how": how, "counts": dict(c)}


def build_slots(sid: str, binding: str = "post_round") -> dict:
    """Slots and beliefs for one session from stored rows; timed.

    `binding` is `post_round` (stage 1: stored entity verdicts and
    continuity, `bind_entities`) or `causal` (stage 2: per-frame assignment
    from what was bound before, `entity_binding.causal_bind`)."""
    import crowd_region as v1
    t_load = time.process_time()
    S = v1.Session(sid)
    L = lineup_slots(sid)
    if "refused" in L:
        return {"session": sid, "refused": L["refused"]}
    wf, why = world_frame(sid)
    if wf is None:
        return {"session": sid, "refused": why}
    mf, to_m, m_per_px = wf
    v_max = v_max_m_s()
    dt_frame = float(np.median(np.diff(S.fr_t))) / 1000.0
    r_icon = float(S.r) * m_per_px
    r_fit = r_icon + v_max * dt_frame
    extra = {}
    if binding == "causal":
        import entity_binding as eb
        fits = eb.load_fits(sid, S, L["slots"], L["player_slot"], to_m, float(S.r))
        spect = eb.spectated_slots(sid, S, L["slots"], L["player_agent"])
        extra = {"fits": fits, "spect": spect}
    load_s = time.process_time() - t_load
    t0 = time.process_time()
    life = lifecycle(sid, S, L["slots"])
    t1 = time.process_time()
    if binding == "causal":
        log_area = math.log(fits["map_px"] * m_per_px ** 2)
        bind = eb.causal_bind(S.fr_t, fits, life["open"], life["seg_start"], L["player_slot"],
                              spect["slot"], r_fit=r_fit, v_max=v_max, log_area=log_area,
                              r_dup_m=2.0 * r_icon, margin_min=fits["margin_min"])
        wit = np.isin(bind["wit"], eb.ANCHORING)
        bind["counts"]["spectate_witness"] = spect["reason"] or "read"
    else:
        bind = bind_entities(S, L["slots"], L["player_slot"], life["open"], life["seg_start"],
                             to_m, v_max, r_fit)
        wit = np.isin(bind["how"], WITNESSED)
    t2 = time.process_time()
    B = beliefs(S.fr_t, bind["X"], bind["Y"], bind["has"], life["open"], life["seg_start"],
                r_fit=r_fit, r_icon=r_icon, v_max=v_max, wit=wit)
    t3 = time.process_time()
    rec = storage_record(B, bind["obs"])
    F = S.fr_t.size
    return {"session": sid, "S": S, "L": L, "mf": mf, "to_m": to_m, "m_per_px": m_per_px,
            "life": life, "bind": bind, "B": B, "rec": rec, "binding": binding, **extra,
            "params": {"v_max_m_s": v_max, "dt_frame_s": dt_frame, "r_icon_m": r_icon,
                       "r_fit_m": r_fit, "crowd_core_m": 2 * r_icon + r_fit,
                       "conflict_share": CONFLICT_SHARE, "binding": binding,
                       **({"binding_params": eb.params()} if binding == "causal" else {})},
            "cost": {"frames": int(F), "load_cpu_s": round(load_s, 2),
                     "lifecycle_us_per_frame": round((t1 - t0) / F * 1e6, 2),
                     "bind_us_per_frame": round((t2 - t1) / F * 1e6, 2),
                     "beliefs_us_per_frame": round((t3 - t2) / F * 1e6, 2),
                     "total_us_per_frame": round((t3 - t0) / F * 1e6, 2),
                     "record_bytes_per_frame": int(rec.dtype.itemsize * rec.shape[1])}}


# ----------------------------------------------------------------- scoring

def _summary(c: dict, inside, kinds, area, R, dt, err, core, inside_tol=None) -> dict:
    out = {}
    inside, kinds = np.asarray(inside, bool), np.asarray(kinds, int)
    n = inside.size
    out["n"] = int(n)
    out["calibration"] = round(float(inside.mean()), 4) if n else None
    if inside_tol is not None and n:
        out["calibration_tol1m"] = round(float(np.asarray(inside_tol, bool).mean()), 4)
    by = {}
    for k, name in KINDS.items():
        m = kinds == k
        if not m.any():
            continue
        a = np.asarray(area)[m]
        r = np.asarray(R)[m]
        row = {"n": int(m.sum()), "calibration": round(float(inside[m].mean()), 4)}
        if np.isfinite(a).any():
            row["area_m2"] = _q(a)
            row["radius_m"] = _q(r)
        if inside_tol is not None:
            row["calibration_tol1m"] = round(float(np.asarray(inside_tol, bool)[m].mean()), 4)
        if k in (CROWD, FIT_UNNAMED):
            row["core_calibration"] = round(float(np.asarray(core)[m].mean()), 4)
        if k in (FIT, CROWD, FIT_UNNAMED):
            row["point_err_m"] = _q(np.asarray(err)[m])
        by[name] = row
    out["by_kind"] = by
    dt = np.asarray(dt, float)
    strata = {}
    edges = list(STRATA_S) + [np.inf]
    unseen = ~np.isin(kinds, (FIT, CLOSED))    # a closed slot counts under has_slot, not here
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = unseen & (dt > lo) & (dt <= hi) if lo > 0 else unseen & (dt <= hi)
        if m.any():
            strata[f"{lo:g}-{hi:g}s"] = {"n": int(m.sum()), "calibration": round(float(inside[m].mean()), 4),
                                         "radius_m_median": round(float(np.nanmedian(np.asarray(R)[m])), 2)}
    out["by_time_since_fix_unseen"] = strata
    return out


def _q(a) -> dict | None:
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if not a.size:
        return None
    return {"median": round(float(np.median(a)), 2), "p10": round(float(np.percentile(a, 10)), 2),
            "p90": round(float(np.percentile(a, 90)), 2), "mean": round(float(a.mean()), 2)}


def truth_slot_map(slots: list[dict], truth_agents: list[str]) -> tuple[dict, list]:
    """Truth agent -> slot index: the arbiter's names, then one-to-one
    elimination of what is left (evaluation only)."""
    by = {_canon(s["agent"]): k for k, s in enumerate(slots) if s["agent"]}
    out, notes = {}, []
    left_t = []
    for a in truth_agents:
        if _canon(a) in by:
            out[_canon(a)] = by[_canon(a)]
        else:
            left_t.append(a)
    left_s = [k for k in range(5) if k not in out.values()]
    if len(left_t) == 1 and len(left_s) == 1:
        out[_canon(left_t[0])] = left_s[0]
        notes.append({"truth": left_t[0], "slot": left_s[0], "how": "elimination",
                      "slot_agent": slots[left_s[0]]["agent"]})
    elif left_t:
        notes.append({"unmapped_truth": left_t, "free_slots": left_s})
    return out, notes


def riot_context(sid: str) -> dict:
    """`crowd_region.riot_context`, with the player resolved through the
    lineup's player where no recurring account names him
    (`riot_ground_truth.resolve_lineup_player`, evaluation pairing only)."""
    import riot_ground_truth as rg
    recs = rg.riot_records(STORE)
    d = recs[sid]
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    ident = rg.resolve_lineup_player(d, rg.identify_player(recs, STORE).get(sid, {}), ref)
    m = d["match"]
    who = {p["subject"]: p for p in m["players"]}
    me = ident.get("subject")
    if me not in who:
        raise SystemExit(f"{sid}: player unidentified ({ident.get('basis')})")
    kill_like, _ = rg.split_deaths(rg.stored_deaths(STORE, sid))
    kills = sorted(m["kills"], key=lambda k: k["gameTime"])
    al = rg.fit_alignment([k["gameTime"] for k in kills], [float(r["t_ms"]) for r in kill_like])
    return {"kills": kills, "a": al["a_ms"], "who": who, "me": me, "team": who[me]["teamId"],
            "agent_of": {s: ref.agent(p["characterId"]) for s, p in who.items()},
            "player_basis": ident.get("basis")}


def score_riot(sid: str, G: dict | None = None) -> dict:
    """Every living teammate at each Riot kill instant against its slot."""
    import riot_ground_truth as rg
    G = G or build_slots(sid)
    if "refused" in G:
        return {"session": sid, "refused": G["refused"]}
    S, B = G["S"], G["B"]
    ctx = riot_context(sid)
    upm = units_per_m()
    agents_team = [ctx["agent_of"][s] for s, p in ctx["who"].items() if p["teamId"] == ctx["team"]]
    tmap, tnotes = truth_slot_map(G["L"]["slots"], agents_team)
    want = np.asarray([ctx["a"] + k["gameTime"] + rg.MINIMAP_LAG_MS for k in ctx["kills"]])
    fi = np.clip(np.searchsorted(S.fr_t, want), 1, S.fr_t.size - 1)
    fi = np.where(np.abs(S.fr_t[fi - 1] - want) <= np.abs(S.fr_t[fi] - want), fi - 1, fi)
    ok_f = (np.abs(S.fr_t[fi] - want) <= rg.FRAME_TOL_MS) & S.fr_drawn[fi]
    dying_at = defaultdict(list)
    for k in ctx["kills"]:
        dying_at[(k["round"], k["gameTime"])].append(k)
    c = Counter()
    T = []   # (frame, slot, x, y, role, agent, t_ms)
    ring_hits = 0
    gate_m = rg.GATE_M
    self_slot = G["L"]["player_slot"]
    for k, f, okk in zip(ctx["kills"], fi, ok_f):
        if not okk:
            c["kill_no_frame"] += 1
            continue
        c["kill_frames"] += 1
        locs = rg.truth_locations(k, dying_at)
        for s, p in locs.items():
            if ctx["who"][s]["teamId"] != ctx["team"]:
                continue
            ag = ctx["agent_of"].get(s)
            role = ("self" if s == ctx["me"] else "teammate") + ("_victim" if p.get("victim_added") else "")
            slot = tmap.get(_canon(ag), -1)
            T.append((int(f), slot, p["location"]["x"] / upm, p["location"]["y"] / upm, role, ag,
                      float(S.fr_t[f])))
        # the stored ring fits' located share on the same instants (the ally_prior baseline)
        a_, b_ = np.searchsorted(S.ob_f, [S.fr_f[f], S.fr_f[f] + 1])
        ring = ~S.ob_self[a_:b_] & ~S.ob_stack[a_:b_]
        rx, ry = G["to_m"](S.ob_x[a_:b_][ring], S.ob_y[a_:b_][ring])
        mates = [(p["location"]["x"] / upm, p["location"]["y"] / upm) for s, p in locs.items()
                 if ctx["who"][s]["teamId"] == ctx["team"] and s != ctx["me"]
                 and not p.get("victim_added")]
        ring_hits += len(rg.greedy_pairs(mates, list(zip(rx, ry)), gate_m))
    out = {"session": sid, "capture": S.manifest["source"]["path"], "version": ENTITY_STATE_VERSION,
           "ally_icon_version": S.ally_icon_version, "round_entity_inputs": S.round_entity_inputs,
           "params": G["params"], "cost": G["cost"], "lineup": G["L"], "truth_slot_notes": tnotes,
           "lifecycle": G["life"]["counts"], "binding": G["bind"]["counts"],
           "binding_mode": G.get("binding", "post_round"),
           "player_basis": ctx["player_basis"], "rests_on": rests_on(G)}
    if G.get("binding") == "causal":
        out["non_player"] = {"by_reason": G["bind"]["np_by_reason"],
                             "flags": G["bind"]["flag_counts"]}
        out["portrait_unread"] = G["fits"]["llr_unread"]
    out["hunt"] = hunt_riot(G, ctx)
    if not T:
        out["refused"] = "no_truth_rows"
        return out
    fr = np.asarray([r[0] for r in T])
    sl = np.asarray([r[1] for r in T])
    xs = np.asarray([r[2] for r in T])
    ys = np.asarray([r[3] for r in T])
    role = np.asarray([r[4] for r in T])
    has_map = sl >= 0
    slc = np.where(has_map, sl, 0)
    open_at = has_map & G["life"]["open"][slc, fr]
    out["exceptions"] = []
    for i in np.flatnonzero(~open_at & ((role == "teammate") | (role == "self"))):
        r = T[i]
        why = "no_slot_for_agent" if not has_map[i] else (
            "before_first_round" if G["life"]["seg"][r[0]] < 0 else "closed_by_death")
        ev = None
        if why == "closed_by_death":
            ev = [e for e in G["life"]["events"] if e.get("slot") == r[1] and e["t_ms"] <= r[6]][-1:]
        out["exceptions"].append({"t_ms": round(r[6]), "agent": r[5], "role": r[4], "slot": int(r[1]),
                                  "why": why, "event": ev})
    C = contains(G["B"], slc, fr, xs, ys)
    inside_tol = contains(G["B"], slc, fr, xs, ys, tol=1.0)["region"] & open_at
    area = region_area(G["B"], slc, fr)
    inside = C["region"] & open_at
    fit_bound = open_at & np.isin(C["kind"], (FIT, FIT_UNNAMED)) & (C["point_err"] <= gate_m)
    res = {}
    for name, m in (("teammates", role == "teammate"), ("self", role == "self"),
                    ("teammates_dying_now", role == "teammate_victim"),
                    ("all_living_allies", (role == "teammate") | (role == "self"))):
        if not m.any():
            continue
        r = _summary(c, inside[m], C["kind"][m], area[m], C["R"][m], C["dt_s"][m],
                     C["point_err"][m], C["core"][m], inside_tol[m])
        r["has_slot"] = int(open_at[m].sum())
        r["has_slot_share"] = round(float(open_at[m].mean()), 4)
        r["fit_located_share"] = round(float((inside[m] & (C["kind"][m] == FIT)).mean()), 4)
        r["fit_bound_share"] = round(float(fit_bound[m].mean()), 4)
        res[name] = r
    n_mates = int((role == "teammate").sum())
    res["teammates"]["ring_located"] = ring_hits
    res["teammates"]["ring_located_share"] = round(ring_hits / max(1, n_mates), 4)
    out["kill_instants"] = dict(c)
    out["scores"] = res
    out["rows"] = {"frame": fr, "slot": sl, "x": xs, "y": ys, "role": role, "inside": inside,
                   "kind": C["kind"], "area": area, "R": C["R"], "dt_s": C["dt_s"],
                   "point_err": C["point_err"], "core": C["core"], "has_slot": open_at,
                   "inside_tol": inside_tol, "fit_bound": fit_bound}
    return out


def rests_on(G: dict) -> list[str]:
    """What the session's beliefs rest on, by binding mode."""
    common = ["lineup agent_identity", "death_verdict rows", "round table"]
    if G.get("binding") == "causal":
        sp = (G.get("spect") or {}).get("reason")
        return ["ally_icon fits (all, causal, per frame)", "identity.rendered_art_scores per fit",
                "identity.teammate_fit_refusal", "ping and spike events", "baked geometry labels",
                (G.get("spect") or {}).get("rests_on", "tray_kit spectating witness")
                + (f" (unused: {sp})" if sp else "")] + common
    return ["round_entity entity verdicts (post-round, pooled)"] + common


#: The every-frame hunt's exclusions (the orchestrator's brief): frames within
#: this long of a teammate's own death, and this long after the buy start.
HUNT_DEATH_MS = 1500.0
HUNT_BUY_MS = 3000.0


def hunt_riot(G: dict, ctx: dict) -> dict:
    """Every drawn frame on which Riot says a teammate lives, against its slot:
    how many have no open slot, and how many an open slot holds with no
    position (`unanchored`), by cause.

    Riot's alive intervals (evaluation only): a teammate lives in round `n`
    from its buy start plus `HUNT_BUY_MS` to its death less `HUNT_DEATH_MS`,
    or, surviving, to the next round's buy start. The combat start is the
    kills' `gameTime - roundTime` mapped by the kill alignment and
    `MINIMAP_LAG_MS`; the buy start lies the session's median gap between a
    stored clock-reset round start and the combat start before it (gaps of
    25-32 s; a round whose start fell back to the score increment is not
    counted in the median). Rounds without a kill have no combat start and
    are skipped."""
    import riot_ground_truth as rg
    S, life = G["S"], G["life"]
    tmap, _ = truth_slot_map(G["L"]["slots"], [ctx["agent_of"][s] for s, p in ctx["who"].items()
                                               if p["teamId"] == ctx["team"]])
    rstart = {}
    for k in ctx["kills"]:
        rstart.setdefault(k["round"], k["gameTime"] - k["roundTime"])
    if not rstart:
        return {"refused": "no_kills"}
    lag = rg.MINIMAP_LAG_MS
    combat = {n: ctx["a"] + g + lag for n, g in rstart.items()}
    starts = life["starts"]
    gaps = []
    for c in combat.values():
        j = np.searchsorted(starts, c) - 1
        if j >= 0 and 25000.0 <= c - starts[j] <= 32000.0:
            gaps.append(c - starts[j])
    buy_gap = float(np.median(gaps)) if gaps else 28700.0
    rounds = sorted(combat)
    buy = {n: combat[n] - buy_gap for n in rounds}
    deaths = defaultdict(dict)
    for k in ctx["kills"]:
        deaths[k["round"]].setdefault(k["victim"], ctx["a"] + k["gameTime"] + lag)
    t = S.fr_t
    drawn = S.fr_drawn
    kind = G["B"]["kind"]
    out = Counter()
    by_mate = {}
    starts_f = life["seg_start"]
    for s, p in ctx["who"].items():
        if p["teamId"] != ctx["team"] or s == ctx["me"]:
            continue
        slot = tmap.get(_canon(ctx["agent_of"][s]), -1)
        m = np.zeros(t.size, bool)
        late = np.zeros(t.size, bool)      # before the stored start of the Riot round's segment
        seg = life["seg"]
        for i, n in enumerate(rounds):
            t0 = buy[n] + HUNT_BUY_MS
            if s in deaths[n]:
                t1 = deaths[n][s] - HUNT_DEATH_MS
            elif i + 1 < len(rounds) and rounds[i + 1] == n + 1:
                t1 = buy[n + 1]
            else:
                t1 = max(deaths[n].values()) + HUNT_DEATH_MS if deaths[n] else t0
            w = (t >= t0) & (t < t1)
            fc = min(int(np.searchsorted(t, combat[n])), t.size - 1)
            late |= w & (seg < seg[fc])
            m |= w
        m &= drawn
        n_alive = int(m.sum())
        if slot < 0:
            out["alive_frames"] += n_alive
            out["no_slot_for_agent"] += n_alive
            continue
        closed = m & (kind[slot] == CLOSED)
        # no position: no fit bound to the slot since its round opened; an
        # unanchored slot with an unwitnessed fit has a point but no bound
        never = G["B"]["lf_any"][slot] < 0
        unanch = m & (kind[slot] == UNANCHORED) & never
        out["unbounded"] += int((m & (kind[slot] == UNANCHORED) & ~never).sum())
        pre = closed & (seg < 0)
        out["no_slot_stored_start_late"] += int((closed & late & ~pre).sum())
        out["no_slot_closed_by_death"] += int((closed & ~late & ~pre).sum())
        # since the stored round start, in seconds, for the unanchored frames
        since = (t - t[np.clip(starts_f, 0, t.size - 1)]) / 1000.0
        out["alive_frames"] += n_alive
        out["no_slot"] += int(closed.sum())
        out["no_slot_before_first_round"] += int(pre.sum())
        out["no_position"] += int(unanch.sum())
        out["no_position_within_10s_of_round_start"] += int((unanch & (since <= 10.0)).sum())
        by_mate[ctx["agent_of"][s]] = {"slot": int(slot), "alive_frames": n_alive,
                                       "no_slot": int(closed.sum()),
                                       "no_position": int(unanch.sum())}
    out = dict(out)
    out["buy_gap_ms"] = round(buy_gap, 1)
    out["rounds"] = len(rounds)
    out["by_teammate"] = by_mate
    return out


def score_replay(sid: str, G: dict | None = None) -> dict:
    """Every living teammate on every drawn frame against its slot (replay truth)."""
    import replay_truth as rt
    import crowd_region as v1
    G = G or build_slots(sid)
    if "refused" in G:
        return {"session": sid, "refused": G["refused"]}
    S = G["S"]
    ctx = v1.replay_context(sid)
    upm = units_per_m()
    tmap, tnotes = truth_slot_map(G["L"]["slots"], ctx["agents"])
    drawn = np.flatnonzero(S.fr_drawn)
    t_rep = rt._frames_to_replay(S.fr_t[drawn], ctx["a"], ctx["lag"])
    rows = defaultdict(list)
    for s, ag in zip(ctx["allies"], ctx["agents"]):
        q = ctx["rp"].sample(s, t_rep)
        live = ctx["rp"].alive(s, t_rep) & np.isfinite(q["x"])
        role = "self" if s == ctx["me"] else "teammate"
        slot = tmap.get(_canon(ag), -1)
        rows["frame"].append(drawn[live])
        rows["slot"].append(np.full(int(live.sum()), slot))
        rows["x"].append(q["x"][live] / upm)
        rows["y"].append(q["y"][live] / upm)
        rows["role"].append(np.full(int(live.sum()), role))
    fr = np.concatenate(rows["frame"])
    sl = np.concatenate(rows["slot"])
    xs, ys = np.concatenate(rows["x"]), np.concatenate(rows["y"])
    role = np.concatenate(rows["role"])
    has_map = sl >= 0
    slc = np.where(has_map, sl, 0)
    open_at = has_map & G["life"]["open"][slc, fr]
    C = contains(G["B"], slc, fr, xs, ys)
    inside_tol = contains(G["B"], slc, fr, xs, ys, tol=1.0)["region"] & open_at
    area = region_area(G["B"], slc, fr)
    inside = C["region"] & open_at
    out = {"session": sid, "version": ENTITY_STATE_VERSION, "params": G["params"],
           "cost": G["cost"], "truth_slot_notes": tnotes, "lifecycle": G["life"]["counts"],
           "binding": G["bind"]["counts"], "binding_mode": G.get("binding", "post_round"),
           "rests_on": rests_on(G), "scores": {}}
    if G.get("binding") == "causal":
        out["non_player"] = {"by_reason": G["bind"]["np_by_reason"],
                             "flags": G["bind"]["flag_counts"]}
    import riot_ground_truth as rg
    fit_bound = open_at & np.isin(C["kind"], (FIT, FIT_UNNAMED)) & (C["point_err"] <= rg.GATE_M)
    never = G["B"]["lf_any"][slc, fr] < 0
    for name, m in (("teammates", role == "teammate"), ("self", role == "self"),
                    ("all_living_allies", np.ones(role.size, bool))):
        r = _summary(None, inside[m], C["kind"][m], area[m], C["R"][m], C["dt_s"][m],
                     C["point_err"][m], C["core"][m], inside_tol[m])
        r["has_slot_share"] = round(float(open_at[m].mean()), 4)
        r["fit_located_share"] = round(float((inside[m] & (C["kind"][m] == FIT)).mean()), 4)
        r["fit_bound_share"] = round(float(fit_bound[m].mean()), 4)
        r["no_position_frames"] = int((m & open_at & (C["kind"] == UNANCHORED) & never).sum())
        out["scores"][name] = r
    # where a teammate's slot is closed while the replay says alive: by cause
    bad = ~open_at & (role == "teammate")
    out["closed_while_alive"] = {"frames": int(bad.sum()),
                                 "no_slot": int((bad & ~has_map).sum()),
                                 "before_first_round": int((bad & has_map
                                                            & (G["life"]["seg"][fr] < 0)).sum())}
    return out


# ----------------------------------------------------------------- pooling and output

def pool(results: list[dict], who: str = "teammates") -> dict:
    """Pool kill-instant rows over sessions, recomputing every share."""
    keys = ("inside", "kind", "area", "R", "dt_s", "point_err", "core", "has_slot", "role",
            "inside_tol", "fit_bound")
    have = [r for r in results if "rows" in r]
    R = {k: np.concatenate([r["rows"][k] if k in r["rows"] else np.zeros(len(r["rows"]["role"]), bool)
                            for r in have]) for k in keys}
    out = {}
    for name, m in (("teammates", R["role"] == "teammate"), ("self", R["role"] == "self"),
                    ("all_living_allies", (R["role"] == "teammate") | (R["role"] == "self"))):
        s = _summary(None, R["inside"][m], R["kind"][m], R["area"][m], R["R"][m], R["dt_s"][m],
                     R["point_err"][m], R["core"][m], R["inside_tol"][m])
        s["has_slot_share"] = round(float(R["has_slot"][m].mean()), 4)
        s["has_slot_missing"] = int((~R["has_slot"][m]).sum())
        s["fit_located_share"] = round(float((R["inside"][m] & (R["kind"][m] == FIT)).mean()), 4)
        s["fit_bound_share"] = round(float(R["fit_bound"][m].mean()), 4)
        known = m & (R["kind"] != UNANCHORED)
        s["calibration_anchored"] = round(float(R["inside"][known].mean()), 4) if known.any() else None
        out[name] = s
    rl = sum(r["scores"]["teammates"]["ring_located"] for r in results if "scores" in r)
    out["teammates"]["ring_located_share"] = round(rl / max(1, out["teammates"]["n"]), 4)
    out["by_session"] = {}
    for r in have:
        m = r["rows"]["role"] == "teammate"
        k = r["rows"]["kind"][m]
        ins = r["rows"]["inside"][m]
        row = {"n": int(m.sum()), "calibration": round(float(ins.mean()), 4) if m.any() else None,
               "by_kind": {KINDS[int(v)]: [int((k == v).sum()), round(float(ins[k == v].mean()), 4)]
                           for v in np.unique(k)}}
        if "fit_bound" in r["rows"]:
            row["fit_bound_share"] = round(float(r["rows"]["fit_bound"][m].mean()), 4)
        out["by_session"][r["session"]] = row
    hunts = [r["hunt"] for r in results if isinstance(r.get("hunt"), dict) and "refused" not in r["hunt"]]
    if hunts:
        hk = sorted({k for h in hunts for k, v in h.items() if isinstance(v, int) and k != "rounds"})
        out["hunt"] = {k: sum(h.get(k, 0) for h in hunts) for k in hk}
        out["hunt"]["by_session"] = {r["session"]: {k: r["hunt"].get(k) for k in hk}
                                     for r in results if isinstance(r.get("hunt"), dict)}
    nps = [r["non_player"]["by_reason"] for r in results if "non_player" in r]
    if nps:
        out["non_player_by_reason"] = dict(sum((Counter(n) for n in nps), Counter()))
        out["binding_counts"] = dict(sum((Counter({k: v for k, v in r["binding"].items()
                                                   if isinstance(v, int)}) for r in results
                                          if "binding" in r), Counter()))
    out["sessions"] = [r["session"] for r in results]
    out["refused"] = {r["session"]: r["refused"] for r in results if "refused" in r}
    out["exceptions"] = [dict(e, session=r["session"]) for r in results for e in r.get("exceptions", [])]
    costs = [r["cost"] for r in results if "cost" in r]
    out["cost"] = {"total_us_per_frame_max": max(c["total_us_per_frame"] for c in costs),
                   "total_us_per_frame_median": float(np.median([c["total_us_per_frame"] for c in costs])),
                   "bind_us_per_frame_max": max(c["bind_us_per_frame"] for c in costs),
                   "load_cpu_s_max": max(c["load_cpu_s"] for c in costs),
                   "record_bytes_per_frame": costs[0]["record_bytes_per_frame"]}
    return out


def _default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, default=_default, indent=1), encoding="utf-8")
    tmp.replace(path)


def _store_record(sid: str, G: dict, out_dir: Path = ANALYSIS) -> dict:
    """Write the per-frame record (one npz per session) and measure it."""
    p = out_dir / f"slots_{sid}.{G.get('binding', 'post_round')}.npz"
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(p, rec=G["rec"], t_ms=G["S"].fr_t.astype("f8"),
                        frame_idx=G["S"].fr_f.astype("i4"), open=G["life"]["open"])
    F = G["S"].fr_t.size
    return {"npz": str(p), "npz_bytes": p.stat().st_size,
            "npz_bytes_per_frame": round(p.stat().st_size / F, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("score")
    a.add_argument("sessions", nargs="+")
    a.add_argument("--pool", required=True)
    a.add_argument("--force", action="store_true")
    a.add_argument("--record", action="store_true")
    b = sub.add_parser("replay")
    b.add_argument("session")
    b.add_argument("--force", action="store_true")
    b.add_argument("--record", action="store_true")
    for x in (a, b):
        x.add_argument("--binding", choices=("post_round", "causal"), default="post_round")
    args = ap.parse_args(argv)
    _below_normal()
    out_dir = ANALYSIS_BINDING
    mode = args.binding
    if args.cmd == "score":
        results = []
        for sid in args.sessions:
            p = out_dir / f"riot_{sid}.{mode}.json"
            rows_p = out_dir / f"riot_{sid}.{mode}.rows.npz"
            if p.is_file() and rows_p.is_file() and not args.force:
                r = json.loads(p.read_text(encoding="utf-8"))
                with np.load(rows_p, allow_pickle=False) as z:
                    r["rows"] = {k: z[k] for k in z.files}
                print(f"{sid}: cached {p}")
                results.append(r)
                continue
            t0 = time.time()
            G = build_slots(sid, binding=mode)
            r = score_riot(sid, G)
            if "refused" not in G:
                r["storage"] = _store_record(sid, G, out_dir)
            rows = r.pop("rows", None)
            r["seconds"] = round(time.time() - t0, 1)
            _write(p, r)
            if rows is not None:
                np.savez_compressed(rows_p, **{k: np.asarray(v) for k, v in rows.items()})
                r["rows"] = rows
            print(f"{sid}: {json.dumps(r.get('scores', {}).get('teammates', r.get('refused')), default=_default)[:600]}")
            results.append(r)
        P = pool(results)
        P["binding"] = mode
        _write(out_dir / f"pool_{args.pool}.json", P)
        print(json.dumps(P, default=_default, indent=1)[:8000])
        if args.record:
            record_pool(P, args.pool)
    else:
        p = out_dir / f"replay_{args.session}.{mode}.json"
        if p.is_file() and not args.force:
            r = json.loads(p.read_text(encoding="utf-8"))
        else:
            t0 = time.time()
            G = build_slots(args.session, binding=mode)
            r = score_replay(args.session, G)
            r["seconds"] = round(time.time() - t0, 1)
            _write(p, r)
        print(json.dumps(r, default=_default, indent=1)[:6000])
        if args.record:
            record_replay(r, mode)
    return 0


def _deps(mode: str = "post_round") -> dict:
    d = {"version": ENTITY_STATE_VERSION, "v_max_m_s": v_max_m_s(),
         "conflict_share": CONFLICT_SHARE, "binding": mode}
    if mode == "causal":
        import entity_binding as eb
        d["binding_params"] = eb.params()
    return d


def _flat_scores(score: dict) -> dict:
    f = {"n": score["n"], "calibration": score["calibration"],
         "calibration_tol1m": score.get("calibration_tol1m"),
         "has_slot_share": score["has_slot_share"], "fit_located_share": score["fit_located_share"]}
    if "has_slot_missing" in score:
        f["has_slot_missing"] = score["has_slot_missing"]
    if "ring_located_share" in score:
        f["ring_located_share"] = score["ring_located_share"]
    for k in ("fit_bound_share", "calibration_anchored"):
        if score.get(k) is not None:
            f[k] = score[k]
    for kind, row in score["by_kind"].items():
        f[f"{kind}_n"] = row["n"]
        f[f"{kind}_calibration"] = row["calibration"]
        if "calibration_tol1m" in row:
            f[f"{kind}_calibration_tol1m"] = row["calibration_tol1m"]
        if row.get("radius_m"):
            f[f"{kind}_radius_m_median"] = row["radius_m"]["median"]
            f[f"{kind}_area_m2_median"] = row["area_m2"]["median"]
        if row.get("point_err_m"):
            f[f"{kind}_point_err_m_median"] = row["point_err_m"]["median"]
        if "core_calibration" in row:
            f[f"{kind}_core_calibration"] = row["core_calibration"]
    return f


def record_pool(P: dict, name: str) -> None:
    from reticle import metrics
    flat = _flat_scores(P["teammates"])
    flat.update({f"all_{k}": v for k, v in _flat_scores(P["all_living_allies"]).items()})
    flat["cost_us_per_frame_max"] = P["cost"]["total_us_per_frame_max"]
    flat["cost_us_per_frame_median"] = P["cost"]["total_us_per_frame_median"]
    flat["record_bytes_per_frame"] = P["cost"]["record_bytes_per_frame"]
    for k, v in (P.get("hunt") or {}).items():
        if isinstance(v, int):
            flat[f"hunt_{k}"] = v
    for k, v in (P.get("non_player_by_reason") or {}).items():
        flat[f"non_player_{k}"] = v
    for sid, row in (P.get("by_session") or {}).items():
        flat[f"{sid}.calibration"] = row["calibration"]
    for sid, h in ((P.get("hunt") or {}).get("by_session") or {}).items():
        for k in ("alive_frames", "no_slot", "no_position", "unbounded"):
            if h.get(k) is not None:
                flat[f"{sid}.hunt_{k}"] = h[k]
    mode = P.get("binding", "post_round")
    metrics.record("entity_state", part="riot_pool", session=name, values=flat, deps=_deps(mode),
                   context={"sessions": P["sessions"], "binding": mode})
    print(" ".join(f"[metric:entity_state/riot_pool@{name}#{k}={v}]" for k, v in flat.items()))


def record_replay(r: dict, mode: str = "post_round") -> None:
    from reticle import metrics
    flat = _flat_scores(r["scores"]["teammates"])
    flat["cost_us_per_frame"] = r["cost"]["total_us_per_frame"]
    name = f"{r['session']}_{mode}"
    metrics.record("entity_state", part="replay", session=name, values=flat,
                   deps=_deps(mode), context={"binding": mode})
    print(" ".join(f"[metric:entity_state/replay@{name}#{k}={v}]" for k, v in flat.items()))


if __name__ == "__main__":
    raise SystemExit(main())
