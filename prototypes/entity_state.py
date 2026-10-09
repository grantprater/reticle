r"""Ally player slots and a position belief for every living slot, every frame.

    .\.venv\Scripts\python.exe prototypes\entity_state.py score SESSION [SESSION ...] --pool NAME [--binding post_round|causal] [--record]
    .\.venv\Scripts\python.exe prototypes\entity_state.py replay 9acf02f98283 [--binding post_round|causal] [--record]

Stages 1 and 2a of [docs/ENTITY_STATE.md](../docs/ENTITY_STATE.md), as a
prototype. `--binding post_round` (the default) binds fits as stage 1 did;
`--binding causal` binds them frame by frame (`entity_binding.py`, stage
2a). Outputs of both go to `<store>/analysis/entity-binding-20261004/`,
named by mode.
Promoted (2026-10-09, QUESTION_ACCEPTANCE B1): the slots, both bindings
and the belief law live in `reticle/slot_state.py` (slot-state-0.1.0), and
this file keeps only the scorers, which read truth (Riot records, replays)
for evaluation and call the module for the slots. Its old names
(`build_slots`, `beliefs`, `lifecycle`, `world_frame`, ...) stay as aliases.
The module reads STORED rows only (`ally_icon` frames, `round_entity`
observations and entities, the death verdicts, the lineup, the round
table), decodes nothing and reads no crop. The sections below describe the
law the module ports unchanged.

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
#: 0.4.0 (2026-10-09): the slot model lives in `reticle/slot_state.py`
#: (slot-state-0.1.0); this file keeps the scorers and calls it. Its output
#: equals 0.3.0's on the three development matches, both bindings.
ENTITY_STATE_VERSION = "entity-state-0.4.0"
STORE = Path.home() / "reticle-store"
ANALYSIS = STORE / "analysis" / "entity-state-20261004"
#: Stage 2 outputs, both binding modes, file names carrying the mode.
ANALYSIS_BINDING = STORE / "analysis" / "entity-binding-20261004"

# The slot model, promoted (QUESTION_ACCEPTANCE B1). These names stay for callers.
from reticle import slot_state as ss  # noqa: E402
from reticle.slot_state import (CLOSED, CONFLICT_SHARE, CROWD, FIT, FIT_UNNAMED,  # noqa: E402,F401
                                HOW_CONTINUITY, HOW_NAMED_RING, HOW_NAMED_STACK, HOW_SELF, KINDS,
                                REACH, UNANCHORED, WITNESSED, bind_entities, beliefs, build_slots, contains,
                                last_fix, lineup_slots, nearest_other, region_area,
                                storage_record, union_area, units_per_m, v_max_m_s,
                                world_frame)

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


# Moved into the acceptance harness (`reticle/harness/schedule.py`, task
# harness-t1d-20261009); these names stay for this module's callers.
from reticle.harness.schedule import (  # noqa: E402,F401
    _canon, truth_slot_map)


def lifecycle(sid: str, S, slots: list[dict]) -> dict:
    """`slot_state.player_lifecycle` (the session id is unused)."""
    return ss.player_lifecycle(S, slots)


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
    G = G or build_slots(sid, binding="post_round")
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
           "player_basis": ctx["player_basis"], "rests_on": _rests_on(G)}
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


def _rests_on(G: dict) -> list[str]:
    """What the session's beliefs rest on, by binding mode."""
    return ss.rests_on(G.get("binding", "post_round"), G.get("spect"))


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
    G = G or build_slots(sid, binding="post_round")
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
           "rests_on": _rests_on(G), "scores": {}}
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
        d["binding_params"] = ss.binding_params()
    d["slot_state_version"] = ss.SLOT_STATE_VERSION
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
