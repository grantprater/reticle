r"""Ability actors in VALORANT replays as external truth for evaluation.

    .\.venv\Scripts\python.exe prototypes\replay_abilities.py census MATCH [--record]
    .\.venv\Scripts\python.exe prototypes\replay_abilities.py score SESSION [--record]
    .\.venv\Scripts\python.exe prototypes\replay_abilities.py survey [--record]

What this is, and what it is not
--------------------------------
The sibling of `replay_truth.py`. Where that file scores players' positions,
this one reads what the replay holds of the abilities: every non-player actor
the server spawned (projectiles, placed game objects, pawns, ground patches,
ult orbs, the planted spike), with its class, spawn point, rotation, open and
close times and the `Owner`/`Instigator` references; and the server's cast
records (`AbilityCastsThisRound`) and ult state (`bUltimateActive`).

What replay data may fit is the use policy in
`docs/EXTERNAL_GROUND_TRUTH.md`. This module uses it
for evaluation only. Nothing in `reticle/` reads this file or its outputs.

How a class is mapped to an ability, from evidence for that ability
--------------------------------------------------------------------
Never by name keyword and never by analogy between abilities. A class maps to
an ability when all three hold:

1. its replicated class path lies in an ability folder,
   `/Game/Characters/<code>/S0/Ability_<L>/...`;
2. the extracted game files (`<store>/reference/game-files/<build>/
   ability-data`) hold a `UIData*` for that folder, whose display name names
   the ability; the folder letter is the game's, not the tray key
   [domain:abilities/minimap-textures-sova];
3. every instance's `Instigator` chain ends at a player pawn of class
   `<code>_PC_C`, and the replay's playerLoadouts name that player's agent.

A class failing any of the three stays unmapped, with the reason. A class
outside `/Game/Characters` (ult orbs, the spike) is named by its own path.

The cast records' `Slot` byte is not documented; `census` derives its meaning
per agent by pairing each cast with the first world actor of the same player
that opens after it, and reports the table rather than assuming it.

The three commands
------------------
`census` lists every non-player actor class of one parse with its counts,
fields and mapping, the cast records and the ult transitions.

`score` aligns replay time to capture time through STORED deaths
(`replay_truth.session_context`, the same fit `replay_truth score` reports)
with one constant offset: on 9acf02f98283,
[metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#align_offset_ms=112619.5] ms, 180 of 181 stored
deaths paired, residual MAD [metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#align_mad_ms=145.0] ms.
The capture clock drifts against the replay's: the stored alignment's slope is
1.00013, 282 ms over the match (`align.slope` and `align.drift_ms_over_match`
in analysis/replay-abilities-20261004/9acf02f98283.json), so the constant offset's
timing error spans up to 282 ms across the match. It then scores 9acf02f98283-style stored streams: `tray_drop` player casts,
`ability_state` cast and death verdicts, `ability_shape` Recon Bolt rings and
Hunter's Fury beams, `ult_cast`, `spike` (through `replay_truth.score_spike`),
`smoke`, and the player's own tray-object marks and minimap-glyph labels.
Positions go through `riot_ground_truth.MapFrame` exactly as `replay_truth`
does. Agreement is consistency, not accuracy; disagreements are stored.

`survey` counts the ability classes in every parse (counts only).

What `score` measured on 9acf02f98283
-------------------------------------
Reader accuracy, not a domain fact: the stored `ability_shape` ring of the
player's Recon Bolt is centred a median
[metric:replay_abilities/score#rb_err_px_median=0.96] px from the replay's
stuck bolt, and drawn from about 0.3 s after the bolt opens until about
0.1 s before it closes (medians 315.5 and -108.8 ms over 15 bolts,
`ability_shape.recon_bolt` in analysis/replay-abilities-20261004/
9acf02f98283.json).

Facts this file established
---------------------------
The cast records and their delta replication [domain:replay/vrf-cast-records],
the Recon Bolt's actors [domain:replay/vrf-sova-recon-bolt-actors], the ult
state [domain:replay/vrf-ult-active], the planted spike and ult orbs
[domain:replay/vrf-planted-spike-actor], and the truth each replay carries
[domain:replay/vrf-ability-truth-per-replay]. Keeping replays:
docs/REPLAY_KEEPING.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import replay_truth as rt  # noqa: E402
import riot_ground_truth as rg  # noqa: E402

REPLAY_ABILITIES_VERSION = "replay-abilities-0.1.0"
STORE = rt.STORE
ANALYSIS = STORE / "analysis" / "replay-abilities-20261004"
#: A stored cast or ult pairs with a replay one within this many ms.
CAST_GATE_MS = 2000.0
ULT_GATE_MS = 3000.0
# The actor reader, the class-to-ability mapping and the cast records live in
# the pipeline (`reticle.replay_actors`) since 2026-10-05; these names stay
# for callers.
from reticle.replay_actors import (CAST_ARRAY, CAST_FIELDS,  # noqa: E402,F401
                                   GAME_BUILD, NON_CHARACTER, PAIR_POST_MS, PAIR_PRE_MS,
                                   ROLE_PREFIX, SLOT_MIN_PAIRED, SLOT_MIN_SHARE, Export, _FOLDER,
                                   _leaf, _role, ability_display, handoff, slot_map)
from reticle.replay_actors import class_census  # noqa: E402

_stats = rt._stats


def actor_census(match: str, ex: Export | None = None) -> dict:
    """`reticle.replay_actors.class_census`, stamped with this scorer's version."""
    return {**class_census(match, ex), "replay_abilities_version": REPLAY_ABILITIES_VERSION}


# ----------------------------------------------------------------- score

def _pair(det_t, tru_t, gate):
    """One-to-one nearest pairing of two time lists within `gate` (ms).
    Returns (det index, truth index, det - truth ms) triples."""
    det_t, tru_t = np.asarray(det_t, float), np.asarray(tru_t, float)
    if not det_t.size or not tru_t.size:
        return []
    D = det_t[:, None] - tru_t[None, :]
    i, j = np.nonzero(np.abs(D) <= gate)
    o = np.argsort(np.abs(D[i, j]), kind="stable")
    used_i, used_j, out = set(), set(), []
    for k in o:
        a, b = int(i[k]), int(j[k])
        if a in used_i or b in used_j:
            continue
        used_i.add(a)
        used_j.add(b)
        out.append((a, b, float(D[a, b])))
    return out


def _cast_score(det, tru, gate=CAST_GATE_MS):
    """Detections (t_cap ms, ability) against truth (t_cap ms, ability)."""
    res = {}
    for ab in sorted({d[1] for d in det} | {t[1] for t in tru}, key=str):
        dt = [d[0] for d in det if d[1] == ab]
        tt = [t[0] for t in tru if t[1] == ab]
        p = _pair(dt, tt, gate)
        e = np.array([x[2] for x in p])
        res[ab] = {"stored": len(dt), "replay": len(tt), "paired": len(p),
                   "within_1s": int(np.sum(np.abs(e) <= 1000)) if e.size else 0,
                   "false": len(dt) - len(p), "missed": len(tt) - len(p),
                   "recall": round(len(p) / len(tt), 4) if tt else None,
                   "stored_minus_replay_ms": _stats(e, 1)}
    return res


def score(sid: str) -> dict:
    ctx = rt.session_context(sid)
    out = dict(ctx["out"])
    if "refused" in out:
        return out
    out["replay_abilities_version"] = REPLAY_ABILITIES_VERSION
    rp, mf, a, me, team = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"], ctx["team"]
    allies, foes, agent = ctx["allies"], ctx["foes"], ctx["agent"]
    lag = rg.MINIMAP_LAG_MS
    out["rests_on"] = {"alignment": "stored deaths (death-adjudication) against replay "
                                    "characterDeath, replay_truth.session_context",
                       "player_and_teams": "Riot match record",
                       "map_frame": "baked geometry shade_fit + valorant-api map constants",
                       "minimap_lag_ms": lag}
    ex = Export(rp.match, rp=rp)
    cen = actor_census(rp.match, ex)
    smap = slot_map(cen)
    out["slot_map"] = smap
    my_agent = agent.get(me)
    my_code = None
    # the player's own world actors and casts, by ability display name
    mine = defaultdict(list)
    for r in cen["classes"]:
        if not r.get("code") or not r["mapped"]:
            continue
        for i in ex.instances(class_short=r["class"]):
            s, _ = ex.owner_subject(i["guid"])
            if s == me:
                my_code = r["code"]
                mine[r["class"]].append({**i, "ability": r["ability"]})
    C = ex.casts()["casts"]
    folder_name = {}
    for r in cen["classes"]:
        if r.get("folder"):
            folder_name[(r["code"], r["folder"])] = r["ability"]
    my_casts = []
    for c in C:
        if c["subject"] != me or c["t_ms"] is None:
            continue
        f = smap.get(f"{my_agent}|{c['slot']}")
        my_casts.append({**c, "ability": folder_name.get((my_code, f)) if f else None})
    ults = ex.ult_intervals()
    my_ults = [u for u in ults if u["subject"] == me]
    # the replay's casts of the player in capture time; an ult cast is its transition
    truth = [(c["t_ms"] + a, c["ability"]) for c in my_casts if c["ability"]]
    unk = [c for c in my_casts if not c["ability"]]
    out["player_replay_casts"] = {"records": len(my_casts), "by_ability": dict(Counter(t[1] for t in truth)),
                                  "slot_unmapped": dict(Counter(c["slot"] for c in unk)),
                                  "ult_transitions": len(my_ults)}
    x_name = next((r["ability"] for r in cen["classes"] if r.get("code") == my_code
                   and r.get("folder") == "Ability_X"), None)
    if x_name is None and my_code:
        x_name = ability_display(my_code, "Ability_X")["display"]
    truth_x = [(u["on_ms"] + a, x_name) for u in my_ults]
    truth_all = [t for t in truth if t[1] != x_name] + truth_x

    # slot key (tray catalogue) -> ability name, from the stored ability_state rows
    key_name = {}
    for r in rt._rows(STORE / "events" / "ability_state" / f"{sid}.jsonl", '"kind":"state"'):
        key_name.setdefault(r["slot"], r.get("ability"))
    out["tray_keys"] = key_name

    # -- tray_drop: player casts, and the drops refused for a reason
    drops = [r for r in rt._rows(STORE / "events" / "tray_drop" / f"{sid}.jsonl")
             if r.get("kind") == "drop"]
    det = [(r["t_ms"], key_name.get(r["slot"])) for r in drops if r.get("player_cast")]
    out["tray_drop"] = {"casts": _cast_score(det, truth_all)}
    # a refused drop that sits on a replay cast the player-cast set missed
    paired_truth = set()
    for ab in {t[1] for t in truth_all}:
        idx = [k for k, t in enumerate(truth_all) if t[1] == ab]
        dt = [d[0] for d in det if d[1] == ab]
        for _i, j, _e in _pair(dt, [truth_all[k][0] for k in idx], CAST_GATE_MS):
            paired_truth.add(idx[j])
    missed = [truth_all[k] for k in range(len(truth_all)) if k not in paired_truth]
    ref_d = [r for r in drops if not r.get("player_cast")]
    why = Counter()
    for t, ab in missed:
        near = [r for r in ref_d if key_name.get(r["slot"]) == ab and abs(r["t_ms"] - t) <= CAST_GATE_MS]
        why[(ab, near[0].get("reason") if near else "no_drop")] += 1
    out["tray_drop"]["missed_by_reason"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(why.items(), key=str)}
    rr = Counter()
    for r in ref_d:
        ab = key_name.get(r["slot"])
        hit = any(t[1] == ab and abs(t[0] - r["t_ms"]) <= CAST_GATE_MS for t in truth_all)
        rr[(r.get("reason"), "on_replay_cast" if hit else "no_replay_cast")] += 1
    out["tray_drop"]["refused_drops"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(rr.items(), key=str)}

    # -- ability_state: cast verdicts, and kit_end against the player's deaths
    st = list(rt._rows(STORE / "events" / "ability_state" / f"{sid}.jsonl", '"kind":"verdict"'))
    det = [(r["t_ms"], key_name.get(r["slot"])) for r in st if r["transition"] == "cast"]
    out["ability_state"] = {"cast_verdicts": _cast_score(det, truth_all),
                            "transitions": dict(Counter(r["transition"] for r in st))}
    my_deaths = np.array([e["t"] + a for e in rp.group("characterDeath") if e.get("victim") == me])
    kd = sorted({r["t_ms"] for r in st if r["transition"] == "owner_death"})
    p = _pair(kd, my_deaths, 3000.0)
    out["ability_state"]["owner_death"] = {
        "stored": len(kd), "replay_deaths": int(my_deaths.size), "paired": len(p),
        "stored_minus_replay_ms": _stats([x[2] for x in p], 1)}

    # -- ability_shape: Recon Bolt rings and Hunter's Fury beams
    out["ability_shape"] = score_shape(sid, rp, mf, a, lag, me, mine, my_ults, ex)

    # -- player's tray-object marks and the glyph eval's labelled points
    out["labels"] = score_labels(sid, rp, mf, a, lag, me, mine, my_ults, ex)

    # -- ult_cast
    out["ult_cast"] = score_ults(sid, a, ults, agent, team, me)

    # -- spike: replay_truth's carrier check plus the planted spike's placement
    sp = rt.score_spike(sid, rp, mf, a, allies, foes, team, me)
    sp["planted"] = score_planted(sid, rp, mf, a, lag, ex)
    out["spike"] = sp

    # -- smoke and the other minimap ability streams: stored rows or a refusal
    out["streams_without_rows"] = {}
    for name in ("smoke", "smoke_owner", "ability", "ability_icon", "ability_fit", "ability_gate",
                 "ability_light", "ability_wall", "minimap_object", "ability_shape_scan"):
        pth = STORE / "events" / name / f"{sid}.jsonl"
        if not pth.is_file():
            out["streams_without_rows"][name] = "no_stored_rows_for_session"
    out["replay_truth_available"] = {
        r["mapped"]: r["opens"] for r in cen["classes"] if r["mapped"]}
    return out


def _bolt_truth(rows, t_rep):
    """(n, k) world x, y of the instances in `rows` alive at replay times `t_rep`."""
    n, k = t_rep.size, len(rows)
    X, Y = np.full((n, k), np.nan), np.full((n, k), np.nan)
    for c, r in enumerate(rows):
        end = r["close_ms"] if r["close_ms"] is not None else np.inf
        live = (t_rep >= r["open_ms"]) & (t_rep <= end)
        X[live, c], Y[live, c] = r["xyz"][0], r["xyz"][1]
    return X, Y


def score_shape(sid, rp, mf, a, lag, me, mine, my_ults, ex) -> dict:
    rows = [r for r in rt._rows(STORE / "events" / "ability_shape" / f"{sid}.jsonl")
            if r.get("kind") == "shape"]
    out = {}
    rb = [r for r in rows if r["ability"] == "Recon Bolt"]
    bolts = mine.get("GameObject_Hunter_Q_SonarBolt_C", [])
    if rb:
        t = np.array([r["t_ms"] for r in rb], float)
        t_rep = rt._frames_to_replay(t, a, lag)
        X, Y = _bolt_truth(bolts, t_rep)
        PX, PY = rt.to_px(mf, X, Y)
        cx = np.array([r["cx"] for r in rb], float)[:, None]
        cy = np.array([r["cy"] for r in rb], float)[:, None]
        D = np.hypot(PX - cx, PY - cy)
        alive = np.isfinite(D).any(axis=1)
        dmin = np.where(alive, np.nanmin(np.where(np.isfinite(D), D, np.inf), axis=1), np.nan)
        found = np.array([bool(r["found"]) for r in rb])
        rr = np.array([r.get("r") or np.nan for r in rb], float)
        out["recon_bolt"] = {
            "rows": len(rb), "found": int(found.sum()),
            "replay_bolts_of_player": len(bolts),
            "rows_with_bolt_alive": int(alive.sum()),
            "found_with_bolt": int((found & alive).sum()),
            "found_without_bolt": int((found & ~alive).sum()),
            "not_found_with_bolt": int((~found & alive).sum()),
            "not_found_without_bolt": int((~found & ~alive).sum()),
            "recall_rows": round(float((found & alive).sum() / alive.sum()), 4) if alive.any() else None,
            "found_centre_err_px": _stats(dmin[found & alive]),
            "found_centre_err_cm": _stats(dmin[found & alive] / mf.px_per_unit, 0),
            "found_centre_inside_ring": int(np.sum(dmin[found & alive] <= rr[found & alive])),
            "not_found_fit_err_px": _stats(dmin[~found & alive])}
        # per cast: the stored rows' span against the bolt's replay lifetime
        per = []
        for ct in sorted({r["cast_t_ms"] for r in rb}):
            m = np.array([r["cast_t_ms"] == ct for r in rb])
            ctr = ct - a
            b = [x for x in bolts if ctr - 500 <= x["open_ms"] <= ctr + 6000]
            fm = m & found
            per.append({"cast_t_ms": round(ct, 1), "rows": int(m.sum()), "found": int(fm.sum()),
                        "replay_bolt": bool(b),
                        "bolt_open_after_cast_ms": round(b[0]["open_ms"] - ctr, 1) if b else None,
                        "bolt_life_s": (round((b[0]["close_ms"] - b[0]["open_ms"]) / 1000.0, 3)
                                        if b and b[0]["close_ms"] else None),
                        "found_first_minus_open_ms": (round(float(t[fm].min() - lag - a - b[0]["open_ms"]), 1)
                                                      if b and fm.any() else None),
                        "found_last_minus_close_ms": (round(float(t[fm].max() - lag - a - b[0]["close_ms"]), 1)
                                                      if b and fm.any() and b[0]["close_ms"] else None)})
        out["recon_bolt"]["per_cast"] = per
        out["recon_bolt"]["casts_with_replay_bolt"] = sum(p["replay_bolt"] for p in per)
        L = [p["bolt_life_s"] for p in per if p["bolt_life_s"]]
        out["recon_bolt"]["bolt_life_s"] = _stats(L, 3)
        f0 = [p["found_first_minus_open_ms"] for p in per if p["found_first_minus_open_ms"] is not None]
        f1 = [p["found_last_minus_close_ms"] for p in per if p["found_last_minus_close_ms"] is not None]
        out["recon_bolt"]["found_first_minus_open_ms"] = _stats(f0, 1)
        out["recon_bolt"]["found_last_minus_close_ms"] = _stats(f1, 1)
    hf = [r for r in rows if r["ability"] == "Hunter's Fury"]
    if hf:
        t = np.array([r["t_ms"] for r in hf], float)
        t_rep = rt._frames_to_replay(t, a, lag)
        on = np.zeros(t.size, bool)
        for u in my_ults:
            on |= (t_rep >= u["on_ms"]) & (t_rep <= (u["off_ms"] or np.inf))
        q = rp.sample(me, t_rep)
        sx, sy = rt.to_px(mf, q["x"], q["y"])
        fyaw = rt.facing_px_deg(mf, q["x"], q["y"], q["yaw"])
        x0 = np.array([r["x0"] for r in hf]); y0 = np.array([r["y0"] for r in hf])
        x1 = np.array([r["x1"] for r in hf]); y1 = np.array([r["y1"] for r in hf])
        dx, dy = x1 - x0, y1 - y0
        L = np.hypot(dx, dy)
        perp = np.abs(dx * (sy - y0) - dy * (sx - x0)) / np.where(L > 0, L, np.nan)
        th = np.mod(np.degrees(np.arctan2(dy, dx)), 180.0)
        dth = np.abs(np.mod(th - np.mod(fyaw, 180.0) + 90.0, 180.0) - 90.0)
        found = np.array([bool(r["found"]) for r in hf])
        out["hunters_fury"] = {"rows": len(hf), "found": int(found.sum()),
                               "rows_in_replay_ult": int(on.sum()),
                               "found_outside_ult": int((found & ~on).sum()),
                               "line_to_sova_px": _stats(perp[found & on]),
                               "line_vs_view_yaw_deg": _stats(dth[found & on]),
                               "ult_windows": len(my_ults)}
    return out


def score_labels(sid, rp, mf, a, lag, me, mine, my_ults, ex) -> dict:
    """The player's tray-object marks and the glyph eval's labelled points
    against the replay's actor of the named ability.

    Owl Drone: the drone pawn's track, point error. Recon Bolt: the stuck bolt;
    the player marked the bolt once and the ring round it otherwise
    [domain:abilities/sova-recon-bolt-minimap-ring], so a mark within half the
    ring's radius scores as a centre mark (distance to the bolt) and any other
    as a ring mark (distance minus the stored descriptor's radius). Hunter's
    Fury: the perpendicular distance to the line from Sova's replay position
    along the view yaw, while the replay's ult is active."""
    marks = []
    for r in rt._rows(STORE / "labels" / "tray_object" / f"{sid}.jsonl"):
        for m in r.get("marks") or []:
            marks.append((r["ability"], float(m["t_ms"]), float(m["x"]), float(m["y"])))
    gi = STORE / "analysis" / "minimap-glyphs-20261004" / "items.json"
    glyph = []
    if gi.is_file():
        items = json.loads(gi.read_text(encoding="utf-8"))
        for it in (items if isinstance(items, list) else items.get("items") or []):
            if it.get("sid") == sid:
                glyph.append((it["cat"].split(":")[-1].strip(), float(it["t_ms"]),
                              float(it["x"]), float(it["y"])))
    drones = mine.get("Pawn_Hunter_E_Drone_C", [])
    bolts = mine.get("GameObject_Hunter_Q_SonarBolt_C", [])
    ring_r = next((r["descriptor"]["radius_px"] for r in
                   rt._rows(STORE / "events" / "ability_shape" / f"{sid}.jsonl", '"Recon Bolt"')
                   if r.get("kind") == "shape" and r.get("descriptor")), None)

    def drone_px(t_rep):
        for d in drones:
            if d["open_ms"] <= t_rep <= (d["close_ms"] or np.inf):
                tt, xx, yy = ex.pawn_track(d["guid"])
                if tt.size < 2:
                    return None
                k = int(np.clip(np.searchsorted(tt, t_rep), 1, tt.size - 1))
                if min(abs(tt[k] - t_rep), abs(tt[k - 1] - t_rep)) > rt.MAX_GAP_MS:
                    return None
                w = float(np.clip((t_rep - tt[k - 1]) / max(tt[k] - tt[k - 1], 1.0), 0, 1))
                px, py = rt.to_px(mf, [xx[k - 1] * (1 - w) + xx[k] * w],
                                  [yy[k - 1] * (1 - w) + yy[k] * w])
                return float(px[0]), float(py[0])
        return None

    def bolt_px(t_rep):
        for b in bolts:
            if b["open_ms"] <= t_rep <= (b["close_ms"] or np.inf):
                px, py = rt.to_px(mf, [b["xyz"][0]], [b["xyz"][1]])
                return float(px[0]), float(py[0])
        return None

    def judge(ability, t_cap, x, y):
        t_rep = t_cap - a - lag
        ab = ability.lower()
        if ab == "owl drone":
            w = drone_px(t_rep)
            return None if w is None else ("point", float(np.hypot(w[0] - x, w[1] - y)))
        if ab == "recon bolt":
            w = bolt_px(t_rep)
            if w is None:
                return None
            d = float(np.hypot(w[0] - x, w[1] - y))
            if ring_r is None or d <= ring_r / 2.0:
                return ("centre", d)
            return ("ring", d - float(ring_r))
        if ab == "hunter's fury":
            if not any(u["on_ms"] <= t_rep <= (u["off_ms"] or np.inf) for u in my_ults):
                return None
            q = rp.sample(me, [t_rep])
            if not np.isfinite(q["x"][0]):
                return None
            sx, sy = rt.to_px(mf, q["x"], q["y"])
            th = np.radians(rt.facing_px_deg(mf, q["x"], q["y"], q["yaw"])[0])
            return ("line", float(abs(np.cos(th) * (y - sy[0]) - np.sin(th) * (x - sx[0]))))
        return None

    out = {"ring_radius_px": ring_r}
    for name, rows in (("tray_object_marks", marks), ("glyph_eval_points", glyph)):
        res = defaultdict(list)
        unscored = Counter()
        for ab, t, x, y in rows:
            j = judge(ab, t, x, y)
            if j is None:
                unscored[ab] += 1
                continue
            res[f"{ab}|{j[0]}"].append(round(j[1], 2))
        out[name] = {"n": len(rows), "unscored_no_replay_actor": dict(unscored),
                     "err_px": {k: _stats(v) for k, v in sorted(res.items())}}
    # the player's "nothing on the minimap" answers against the replay
    nothing = []
    for r in rt._rows(STORE / "labels" / "tray_object" / f"{sid}.jsonl"):
        if r.get("class") == "nothing_on_minimap":
            t_rep = r["t_drop_s"] * 1000.0 - a
            hit = {}
            for k, v in mine.items():
                for x in v:
                    if t_rep - 1000 <= x["open_ms"] <= t_rep + 3000:
                        hit[k] = (round(x["open_ms"] - t_rep, 1), None if x["close_ms"] is None
                                  else round((x["close_ms"] - x["open_ms"]) / 1000.0, 3))
            nothing.append({"ability": r["ability"], "t_drop_s": r["t_drop_s"],
                            "replay_actors_open_after_drop_ms_life_s": hit})
    out["nothing_on_minimap"] = nothing
    return out


def score_ults(sid, a, ults, agent, team, me) -> dict:
    rows = [r for r in rt._rows(STORE / "events" / "ult_cast" / f"{sid}.jsonl")
            if r.get("kind") in ("cast", "refusal")]
    side = {s: ("ally" if team.get(s) == team[me] else "enemy") for s in team}
    tru = [(u["on_ms"] + a, f"{agent.get(u['subject'])}|{'own' if u['subject'] == me else side.get(u['subject'])}")
           for u in ults]

    def lab(r):
        v = r.get("side") or r.get("variant")
        v = "own" if v in ("own", "self") or r.get("player_cast") else v
        return f"{r.get('agent') or r.get('template_agent')}|{v}"

    casts = [r for r in rows if r["kind"] == "cast"]
    det = [(float(r["t_ms"]), lab(r)) for r in casts]
    # any agent and side: does a replay ult sit under each stored cast at all?
    p_any = _pair([d[0] for d in det], [t[0] for t in tru], ULT_GATE_MS)
    res = {"stored_casts": len(det), "replay_ults": len(tru),
           "replay_by_label": dict(Counter(t[1] for t in tru)),
           "stored_by_label": dict(Counter(d[1] for d in det)),
           "by_label": _cast_score(det, tru, ULT_GATE_MS),
           "paired_any_label": len(p_any),
           "any_label_stored_minus_replay_ms": _stats([x[2] for x in p_any], 1)}
    pl = _pair([d[0] for d in det], [t[0] for t in tru], ULT_GATE_MS)
    res["paired_label_agrees"] = sum(det[i][1] == tru[j][1] for i, j, _ in pl)
    pr = sum(v["paired"] for v in res["by_label"].values())
    res["paired_same_label"] = pr
    res["recall"] = round(pr / len(tru), 4) if tru else None
    res["precision"] = round(pr / len(det), 4) if det else None
    # refusals: was a replay ult of the template's agent near?
    rf = Counter()
    for r in rows:
        if r["kind"] != "refusal":
            continue
        ag = r.get("template_agent")
        hit = any(abs(t[0] - float(r["t_ms"])) <= ULT_GATE_MS and t[1].split("|")[0] == ag for t in tru)
        rf[(r.get("reason"), "replay_ult_of_agent" if hit else "no_replay_ult_of_agent")] += 1
    res["refusals"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(rf.items(), key=str)}
    return res


def score_planted(sid, rp, mf, a, lag, ex) -> dict:
    """Dropped-or-planted spike glyphs against the planted spike (`TimedBomb_C`)."""
    bombs = ex.instances(class_short="TimedBomb_C")
    gx, gy, gt = [], [], []
    for r in rt._rows(STORE / "events" / "spike" / f"{sid}.jsonl", '"kind":"frame"'):
        if r.get("reason") is not None:
            continue
        for g in r.get("glyphs") or []:
            if g.get("reason") is None and g.get("state") == "dropped":
                gx.append(g["cx"]); gy.append(g["cy"]); gt.append(r["t_ms"])
    if not gt:
        return {"refused": "no_dropped_glyphs"}
    t_rep = rt._frames_to_replay(np.array(gt, float), a, lag)
    X, Y = _bolt_truth(bombs, t_rep)
    PX, PY = rt.to_px(mf, X, Y)
    D = np.hypot(PX - np.array(gx)[:, None], PY - np.array(gy)[:, None])
    alive = np.isfinite(D).any(axis=1)
    dmin = np.where(alive, np.nanmin(np.where(np.isfinite(D), D, np.inf), axis=1), np.nan)
    # frames where the replay has a planted spike: how many carry a dropped glyph
    grid = sorted({r["t_ms"] for r in rt._rows(STORE / "events" / "spike" / f"{sid}.jsonl", '"kind":"frame"')
                   if r.get("reason") is None})
    g_rep = rt._frames_to_replay(np.array(grid, float), a, lag)
    Xg, _ = _bolt_truth(bombs, g_rep)
    planted_frames = np.isfinite(Xg).any(axis=1)
    have = set(np.round(gt, 1).tolist())
    with_glyph = np.array([round(t, 1) in have for t in grid])
    return {"plants": len(bombs), "dropped_glyphs": len(gt),
            "glyphs_while_planted": int(alive.sum()),
            "glyph_err_px_while_planted": _stats(dmin[alive]),
            "planted_frames": int(planted_frames.sum()),
            "planted_frames_with_glyph": int((planted_frames & with_glyph).sum())}


# ----------------------------------------------------------------- survey

def survey() -> dict:
    """Counts only: ability-folder classes, ult orbs and plants in every parse."""
    rows, per_class = [], defaultdict(Counter)
    rep = json.loads((rt.REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    meta = {Path(f["file"]).stem: f for f in rep["files"]}
    for d in sorted(p for p in rt.PARSED.iterdir() if (p / "export" / "actors.parquet").is_file()):
        ex = Export(d.name, light=True)
        op = ex.a_ev == "open"
        cps = ex.a_cp[op]
        info = meta.get(d.name, {})
        build = (info.get("build") or {}).get("branch", "").rsplit("+", 1)[-1] or None
        cnt = Counter()
        codes = set()
        for cp in cps:
            f = _FOLDER.match(cp)
            short = _leaf(cp)
            if short.endswith("_PC_C") and cp.startswith("/Game/Characters/"):
                codes.add(cp.split("/")[3])
            if f and _role(short) in ("projectile", "game object", "pawn", "ground patch"):
                cnt[short] += 1
            elif cp.rsplit(".", 1)[0] in NON_CHARACTER:
                cnt[short] += 1
        world = sum(v for k, v in cnt.items() if k not in ("UltPointOrb_C", "TimedBomb_C", "BombEquippable_C"))
        rows.append({"match": d.name[:8], "build": build,
                     "map": (info.get("map") or "").rsplit("/", 1)[-1] or None,
                     "capture_session": info.get("capture_session"), "agent_codes": sorted(codes),
                     "ability_world_opens": world, "classes": len(cnt),
                     "ult_orbs": cnt.get("UltPointOrb_C", 0), "plants": cnt.get("TimedBomb_C", 0)})
        for k, v in cnt.items():
            per_class[k][d.name[:8]] = v
    w = np.array([r["ability_world_opens"] for r in rows], float)
    return {"replay_abilities_version": REPLAY_ABILITIES_VERSION, "parsed": len(rows),
            "ability_world_opens": _stats(w, 1), "replays": rows,
            "classes": {k: {"replays": len(v), "opens": sum(v.values())}
                        for k, v in sorted(per_class.items())}}


# ----------------------------------------------------------------- record

def record_census(c: dict) -> list[str]:
    from reticle import metrics
    v = {"classes": len(c["classes"]), "mapped": c["mapped_classes"],
         "unmapped": len(c["unmapped_classes"]),
         "non_player_movement_rows": c["non_player_movement"]["rows"],
         "non_player_pawns": c["non_player_movement"]["pawns"],
         "cast_records": c["casts"]["records"], "ult_transitions": c["ults"]["transitions"],
         "ult_events": c["ults"]["events"],
         "ult_events_within_100ms": c["ults"]["events_within_100ms_of_transition"]}
    v["plant_events"] = c.get("plant_events")
    for r in c["classes"]:
        k = re.sub(r"[^a-z0-9]", "_", r["class"].lower().removesuffix("_c"))
        if r.get("mapped") and r["role"] != "ability item":
            v[f"{k}_opens"] = r["opens"]
            v[f"{k}_life_s_median"] = (r["lifetime_s"] or {}).get("median")
    sm = slot_map(c)
    for key, f in sm.items():
        if f is None:
            continue
        row = c["casts"]["by_agent_slot"][key]
        k = re.sub(r"[^a-z0-9]", "_", key.lower())
        v[f"slot_{k}_paired"] = row.get(f, 0)
        v[f"slot_{k}_casts"] = sum(row.values())
    for key, st in c["casts"]["open_after_cast_ms"].items():
        k = re.sub(r"[^a-z0-9]", "_", key.lower().removesuffix("_c"))
        v[f"open_after_cast_{k}_ms_median"] = (st or {}).get("median")
    for key, h in c["handoff"].items():
        k = re.sub(r"[^a-z0-9]", "_", key.lower().removesuffix("_c"))
        v[f"handoff_{k}_paired"] = h["paired"]
        v[f"handoff_{k}_ms_median"] = (h["open_minus_projectile_close_ms"] or {}).get("median")
        v[f"handoff_{k}_cm_median"] = (h["spawn_to_projectile_location_cm"] or {}).get("median")
        v[f"handoff_{k}_cm_max"] = (h["spawn_to_projectile_location_cm"] or {}).get("max")
    metrics.record("replay_abilities", part="census", session=c["match"][:8], values=v,
                   deps={"replay_abilities": REPLAY_ABILITIES_VERSION, "vrfkit": rt.VRFKIT_VERSION,
                         "game_files": GAME_BUILD})
    return [f"[metric:replay_abilities/census#{k}={x}]" for k, x in v.items()]


def record_score(s: dict) -> list[str]:
    from reticle import metrics
    v = {}
    for ab, x in s["tray_drop"]["casts"].items():
        k = re.sub(r"[^a-z]", "_", str(ab).lower())
        v[f"tray_{k}_paired"] = x["paired"]
        v[f"tray_{k}_replay"] = x["replay"]
        v[f"tray_{k}_false"] = x["false"]
        if x["stored_minus_replay_ms"]:
            v[f"tray_{k}_dt_ms_median"] = x["stored_minus_replay_ms"]["median"]
    for ab, x in s["ability_state"]["cast_verdicts"].items():
        k = re.sub(r"[^a-z]", "_", str(ab).lower())
        v[f"state_{k}_paired"] = x["paired"]
        v[f"state_{k}_replay"] = x["replay"]
    rb = s["ability_shape"].get("recon_bolt") or {}
    for k in ("rows", "found", "rows_with_bolt_alive", "found_with_bolt", "found_without_bolt",
              "not_found_with_bolt", "recall_rows", "replay_bolts_of_player", "casts_with_replay_bolt"):
        v[f"rb_{k}"] = rb.get(k)
    v["rb_err_px_median"] = (rb.get("found_centre_err_px") or {}).get("median")
    v["rb_err_px_p90"] = (rb.get("found_centre_err_px") or {}).get("p90")
    v["rb_bolt_life_s_median"] = (rb.get("bolt_life_s") or {}).get("median")
    hf = s["ability_shape"].get("hunters_fury") or {}
    v["hf_line_to_sova_px_median"] = (hf.get("line_to_sova_px") or {}).get("median")
    v["hf_angle_deg_median"] = (hf.get("line_vs_view_yaw_deg") or {}).get("median")
    u = s["ult_cast"]
    v.update({"ult_stored": u["stored_casts"], "ult_replay": u["replay_ults"],
              "ult_paired_same_label": u["paired_same_label"], "ult_paired_any": u["paired_any_label"],
              "ult_recall": u["recall"], "ult_precision": u["precision"],
              "ult_dt_ms_median": (u["any_label_stored_minus_replay_ms"] or {}).get("median")})
    lb = s["labels"]
    for name, short in (("glyph_eval_points", "glyph"), ("tray_object_marks", "marks")):
        for k, st in (lb[name]["err_px"] or {}).items():
            key = re.sub(r"[^a-z]", "_", k.lower())
            v[f"{short}_{key}_n"] = (st or {}).get("n")
            v[f"{short}_{key}_px_median"] = (st or {}).get("median")
    pl = s["spike"].get("planted") or {}
    v["planted_glyph_err_px_median"] = (pl.get("glyph_err_px_while_planted") or {}).get("median")
    v["planted_frames"] = pl.get("planted_frames")
    v["planted_frames_with_glyph"] = pl.get("planted_frames_with_glyph")
    metrics.record("replay_abilities", part="score", session=s["session"], values=v,
                   deps={"replay_abilities": REPLAY_ABILITIES_VERSION, "vrfkit": rt.VRFKIT_VERSION,
                         "minimap_lag_ms": rg.MINIMAP_LAG_MS, "cast_gate_ms": CAST_GATE_MS,
                         "ult_gate_ms": ULT_GATE_MS})
    return [f"[metric:replay_abilities/score#{k}={x}]" for k, x in v.items()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, arg in (("census", "match"), ("score", "session")):
        p = sub.add_parser(name)
        p.add_argument(arg)
        p.add_argument("--record", action="store_true")
    p = sub.add_parser("survey")
    p.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    rt._below_normal()
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    if args.cmd == "census":
        c = actor_census(args.match)
        (ANALYSIS / f"census-{args.match[:8]}.json").write_text(
            json.dumps(c, indent=1, default=rt._default), encoding="utf-8")
        print(json.dumps({k: v for k, v in c.items() if k != "classes"}, indent=1, default=rt._default))
        for r in c["classes"]:
            print(json.dumps({k: r.get(k) for k in ("class", "role", "opens", "closes", "mapped",
                                                    "unmapped_reason", "rep_movement_rows",
                                                    "movement_rows", "instigator_resolved")},
                             default=rt._default))
        if args.record:
            print("\n".join(record_census(c)))
        return 0
    if args.cmd == "score":
        s = score(args.session)
        (ANALYSIS / f"{args.session}.json").write_text(json.dumps(s, indent=1, default=rt._default),
                                                      encoding="utf-8")
        print(json.dumps({k: v for k, v in s.items() if k not in ("align",)}, indent=1,
                         default=rt._default)[:20000])
        if args.record and "refused" not in s:
            print("\n".join(record_score(s)))
        return 0
    if args.cmd == "survey":
        sv = survey()
        (ANALYSIS / "survey.json").write_text(json.dumps(sv, indent=1, default=rt._default),
                                              encoding="utf-8")
        for r in sv["replays"]:
            print(json.dumps(r))
        print(json.dumps({k: v for k, v in sv["classes"].items()}, indent=0)[:6000])
        if args.record:
            from reticle import metrics
            v = {"parsed": sv["parsed"], "world_opens_median": sv["ability_world_opens"]["median"],
                 "world_opens_min": min(r["ability_world_opens"] for r in sv["replays"]),
                 "classes": len(sv["classes"])}
            metrics.record("replay_abilities", part="survey", values=v,
                           deps={"replay_abilities": REPLAY_ABILITIES_VERSION, "vrfkit": rt.VRFKIT_VERSION})
            print(" ".join(f"[metric:replay_abilities/survey#{k}={x}]" for k, x in v.items()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
