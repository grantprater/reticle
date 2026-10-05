r"""Engagement reach: who can join a fight, confirmed on the player's own history.

    .\.venv\Scripts\python.exe prototypes\engagement_reach.py gate [--record]
    .\.venv\Scripts\python.exe prototypes\engagement_reach.py score --set dev [--record]
    .\.venv\Scripts\python.exe prototypes\engagement_reach.py score --set confirm [--record]
    .\.venv\Scripts\python.exe prototypes\engagement_reach.py score --set confirm --tag T [--exclude-holdout] [--shuffles N] [--record]
    .\.venv\Scripts\python.exe prototypes\engagement_reach.py fidelity [--record]

Why this exists
---------------
`prototypes/decision_value.py reach` asked, on the 22 captured Riot records,
whether who can JOIN a fight (walk a few metres to a cell that sees the
opposing duelist) predicts the fight better than who stands near it, and
chose its parameters there. This file scores those choices once on a second
set, the player's own competitive history fetched through HenrikDev, and
reads the coaching questions off the same features: did the player and his
team take fights with fewer able to join than the enemy, and what did that
cost in round win probability. Weapons and utility reach stay out.

Sets
----
- **dev**: the 22 captured Riot records, as `decision_value.Dev` reads them.
- **confirm**: `<store>/external/ladder/henrikdev/v4/parsed/ladder-parse-0.2.0`
  (`docs/LADDER_SAMPLE.md`), every match except the captured ones (in
  `external/riot/` or flagged `captured`) and the held-out replay matches
  (`decision_value.held_out_ids`), each excluded and counted. `ladder_records`
  rebuilds Riot-shaped records from the six tables so the development code
  reads them unchanged. The tables carry no attacker role; the attacking team
  is Red in rounds 0-11 and in even overtime rounds, Blue otherwise, the
  pattern every planted round of both sets follows (checked in
  `ladder_records`, which counts planters on the other team). The player is
  the match's `is_owner` row. Matches on maps without a sightline table are
  excluded and counted. The confirmation run kept the ladder's one-in-five
  `holdout` matches (22 of its 123); `--exclude-holdout` drops them, a post
  hoc sensitivity. `--tag` writes `score_<set>_<tag>.json` and the ledger part
  `<set>/<tag>`, so a rerun never overwrites the confirmation's files.

The sightline map per map (`gate`)
----------------------------------
Two instruments exist: the 2D minimap map (`prototypes/sightlines.py`, every
map with baked geometry) and the 3D map from the game's collision
(`prototypes/sightlines_3d.py`; the confirmation used it on Ascent and Split,
the two maps built then). The rule, fixed after the development gate ran and
before any confirmation feature, fit or score: use the 3D map where the 3D
probe's instrument gate (its ledger row `sightlines_3d/gate/<map>`: line of
sight killer eye to victim at exact positions, development gun kills)
beats the 2D map's on the same kills; else the 2D map. `gate` also measures
the cell tables the reach features actually read (killer cell to victim
cell, strict and one-cell-tolerant in 2D, strict in 3D) with a control (the
killer against the victim's other living teammates), and writes
`<out>/gate.json`, which `score` and `fidelity` read. A stricter table rule
(3D strict above both 2D shares), written first and replaced after this gate
ran, would have kept Split on 2D; it is reported as post hoc. `gate.json`
stays as the confirmation read it: 3D tables built later for other maps do
not enter this analysis.

`Map3D` is `sightlines.Sightlines3D` (see its module docstring): lowest
standable cell of the grid column, strict eye-to-eye visibility, the table's
walk graph, callout regions from the 2D table by (x, y).

Models (parameters chosen on dev by `decision_value.py reach`)
-------------------------------------------------------------
A fight is a gun kill between opposite teams; the label is "the attacking
duelist won"; features count each side's OTHER living players
(`decision_value.reach_features`).

- baseline: alive terms, planted, pre-plant round-time bins;
- reach: baseline + swing (walk <= 2 m to a cell seeing the opposing
  duelist), trade (<= 5 m) and node (same or adjacent callout region as
  either duelist) counts per side;
- radius: baseline + others within 5 m of the own duelist, per side;
- own: baseline + the reach counts of the player's team only (the side
  reticle always sees), each column zero when that side is the enemy;
- join: baseline + the count able to join by swing or trade (walk <= 5 m),
  per side;
- plant: alive counts and plant time, plus each side's players within 5 m of
  a cell seeing the spike and the defenders' mean path metres to it;
- trade (deaths): among deaths with a living teammate, trade within 5 s from
  the number of the victim's teammates within 5 m of a cell seeing the
  killer, against the nearest teammate's straight-line distance, each with
  the same alive and plant terms.

Scores leave one match out; log-loss intervals resample matches (2000) over
the per-row held-out differences, as `decision_value` does; coefficient
intervals come from 101 match-bootstrap refits. A position-shuffle null
(`decision_value.shuffle_positions`, 20 permutations) scores the reach model
on shuffled positions.

Coaching readout
----------------
Each fight is read from both duelists' sides. Join counts are walk <= 5 m.
Reach balance is (own swing + trade) - (enemy swing + trade). A fight is
taken outnumbered when the own join count is below the enemy's; its cost is
(p_cf - p) x dV, where p is the held-out reach model's chance the own
duelist wins, p_cf the same with the own side's swing, trade and node counts
set to the enemy's, and dV = V(defenders lose one) - V(attackers lose one)
from winprob_reference's B1 model fitted with the match left out. Groups:
the player, his team (the player included), lobby peers (the other nine),
opponents. Intervals resample matches.

Real-time fidelity
------------------
Reticle sees teammates always and enemies only when spotted. `score` fits
the own-team model (REACH3) and a region-precision variant: each own-team
player stands at his callout region's representative cell (the region cell
nearest its centroid), the crowd rule's precision. `fidelity` compares, at
development fight instants, own-team swing and trade counts (the own duelist
included) from reticle's stored `round_entity` ally and self icons against
Riot's positions; the opposing duelist keeps Riot's position.

Data rules
----------
The Riot records and the player's own history fit nothing that reaches a
reader, a reader threshold or anything shown in play. Match ids and player
pseudonyms stay in the store's results; nothing here prints them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import decision_value as dv  # noqa: E402
import riot_ground_truth as rgt  # noqa: E402
import sightlines as sl  # noqa: E402
import sightlines_3d as s3  # noqa: E402
import winprob_reference as wr  # noqa: E402

VERSION = "engagement-reach-0.1.0"
STORE = dv.STORE
OUT = STORE / "analysis" / "engagement-reach-20261004"
LADDER = STORE / "external" / "ladder" / "henrikdev" / "v4" / "parsed" / "ladder-parse-0.2.0"
#: Chosen on development log loss by `decision_value.py reach` (ledger row decision_value/reach).
SWING_S = 2.0
TRADE_T = 5.0
RADIUS_R = 5.0
NODE_GRAPH = "callout"
PLANT_T = 5.0
SHUFFLES = 20
BOOT = 101
UNREACHABLE = int(sl.UNREACHABLE)


def source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def quiet() -> None:
    """Below Normal and one logical CPU (Embree's threads included)."""
    try:
        s3.quiet()
    except Exception:  # noqa: BLE001 -- best effort
        dv._below_normal()


# ----------------------------------------------------------------- the confirmation set

def attacking_team(n: np.ndarray) -> np.ndarray:
    """Red attacks rounds 0-11 and even overtime rounds; Blue the rest."""
    n = np.asarray(n)
    return np.where((n < 12) | ((n >= 24) & (n % 2 == 0)), "Red", "Blue")


def ladder_records(maps_with_table: set[str] | None = None,
                   exclude_holdout: bool = False) -> tuple[dict, dict, dict]:
    """(records, me, counts): Riot-shaped records keyed by match id, the
    player's pseudonym per match, and what was excluded and why. With
    `exclude_holdout`, the ladder's `holdout` matches (docs/LADDER_SAMPLE.md)
    drop out last, counted as `holdout_excluded`."""
    import pyarrow.parquet as pq
    T = {n: pq.read_table(LADDER / f"{n}.parquet").to_pylist()
         for n in ("matches", "players", "rounds", "economy", "kills", "positions")}
    ref = rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
    url_of = {m["uuid"]: url for url, m in ref.maps.items()}
    held = dv.held_out_ids()
    riot_ids = {d["match"]["matchInfo"]["matchId"] for d in rgt.riot_records(STORE).values()}
    counts = Counter(matches_listed=len(T["matches"]))
    keep = {}
    for m in T["matches"]:
        mid = m["match_id"]
        if mid in held:
            counts["held_out_excluded"] += 1
        elif mid in riot_ids or m["captured"]:
            counts["captured_excluded"] += 1
        elif m["map_id"] not in url_of:
            counts["no_map_url_excluded"] += 1
        elif maps_with_table is not None and m["map"].lower() not in maps_with_table:
            counts[f"no_table_excluded:{m['map'].lower()}"] += 1
            counts["no_table_excluded"] += 1
        elif exclude_holdout and m["holdout"]:
            counts["holdout_excluded"] += 1
        else:
            keep[mid] = m
    by = {k: defaultdict(list) for k in ("players", "rounds", "economy", "kills")}
    for k in by:
        for r in T[k]:
            if r["match_id"] in keep:
                by[k][r["match_id"]].append(r)
    kpos, ppos = defaultdict(list), defaultdict(list)
    for r in T["positions"]:
        if r["match_id"] not in keep:
            continue
        loc = {"subject": r["player"], "location": {"x": r["x"], "y": r["y"]}}
        if r["event"] == "kill":
            kpos[(r["match_id"], r["kill"])].append(loc)
        elif r["event"] == "plant":
            ppos[(r["match_id"], r["round"])].append(loc)
    records, me = {}, {}
    planter_side = Counter()
    for mid, m in keep.items():
        team = {p["player"]: p["team"] for p in by["players"][mid]}
        owner = [p["player"] for p in by["players"][mid] if p["is_owner"]]
        me[mid] = owner[0] if len(owner) == 1 else None
        counts["owner_found"] += len(owner) == 1
        econ = defaultdict(list)
        for e in by["economy"][mid]:
            econ[e["round"]].append(e)
        kills = []
        for k in by["kills"][mid]:
            locs = kpos.get((mid, k["kill"]), [])
            counts["kills"] += 1
            counts["kills_listing_victim"] += any(p["subject"] == k["victim"] for p in locs)
            kills.append({"round": k["round"], "roundTime": k["time_in_round_ms"], "gameTime": k["time_in_match_ms"],
                          "killer": k["killer"], "victim": k["victim"],
                          "playerLocations": [p for p in locs if p["subject"] != k["victim"]],
                          "victimLocation": ({"x": k["victim_x"], "y": k["victim_y"]}
                                             if k["victim_x"] is not None else None),
                          "finishingDamage": {"damageType": k["weapon_type"]}})
        results = []
        for r in by["rounds"][mid]:
            n = r["round"]
            att = str(attacking_team(n))
            if r["planter"] is not None:
                planter_side["agrees" if team.get(r["planter"]) == att else "disagrees"] += 1
            rr = {"roundNum": n, "roundResultCode": r["result"], "winningTeam": r["winning_team"],
                  "winningTeamRole": "Attacker" if r["winning_team"] == att else "Defender",
                  "playerStats": [{"subject": e["player"], "wasAfk": bool(e["was_afk"]),
                                   "wasPenalized": bool(e["received_penalty"])} for e in econ[n]],
                  "playerEconomies": [{"subject": e["player"], "loadoutValue": e["loadout_value"]} for e in econ[n]],
                  "bombPlanter": r["planter"], "plantRoundTime": r["plant_ms"],
                  "bombDefuser": r["defuser"], "defuseRoundTime": r["defuse_ms"],
                  "plantLocation": ({"x": r["plant_x"], "y": r["plant_y"]} if r["planter"] is not None else None),
                  "plantPlayerLocations": ppos.get((mid, n), [])}
            results.append(rr)
        records[mid] = {"match": {"matchInfo": {"matchId": mid, "mapId": url_of[m["map_id"]], "queueID": "competitive"},
                                  "players": [{"subject": p, "teamId": t} for p, t in team.items()],
                                  "kills": kills, "roundResults": results}}
    counts["matches"] = len(records)
    counts["planter_on_attacking_team"] = planter_side["agrees"]
    counts["planter_on_other_team"] = planter_side["disagrees"]
    return records, me, dict(counts)


# ----------------------------------------------------------------- the 3D map

Map3D = sl.Sightlines3D


_TABLES: dict[tuple[str, str], object] = {}


def table(mname: str, kind: str):
    """The map's 2D or 3D table, built once per process; None if missing."""
    key = (mname, kind)
    if key not in _TABLES:
        if kind == "3d":
            _TABLES[key] = Map3D(mname) if s3.out_path(mname).is_file() and sl.load_2d(mname) is not None else None
        else:
            _TABLES[key] = sl.load_2d(mname)
    return _TABLES[key]


def chosen_loader():
    g = json.loads((OUT / "gate.json").read_text(encoding="utf-8"))
    choice = g["choice"]

    def loader(mname):
        kind = choice.get(mname)
        return None if kind is None else table(mname, kind)
    return loader, choice, g


# ----------------------------------------------------------------- step 1: the gate

def probe_gate(mname: str) -> dict | None:
    """The 3D probe's instrument gate for the map: the latest pass row of
    ledger series sightlines_3d/gate/<map>."""
    from reticle import metrics
    rows = [r for r in metrics.load() if r.get("tool") == "sightlines_3d" and r.get("part") == f"gate/{mname}"
            and r.get("status") == "pass"]
    if not rows:
        return None
    v = rows[-1]["values"]
    return {k: v.get(k) for k in ("los3d_share_on_2d_set", "los2d_share", "los2d_n", "control_los3d_share",
                                  "control_los2d_share")} | {"at": rows[-1]["at"]}


def gate(args) -> dict:
    dev = dv.Dev()
    F = dv.Fights(dev)
    kl = dev.killer[F.rr, F.kk]
    vi = dev.victim[F.rr, F.kk]
    ar = np.arange(F.n)
    pk, pv = F.P[ar, kl], F.P[ar, vi]
    vside_att = dev.att[F.rr, vi]
    res = {"version": VERSION, "source": source_hash(), "held_out_excluded": len(dev.held_excluded),
           "rule": "3d where the 3D probe's instrument gate (ledger sightlines_3d/gate/<map>, exact positions, "
                   "development gun kills) beats the 2D map's on the same kills; else 2d",
           "maps": {}, "choice": {}}
    for mname in sorted(set(F.map.tolist()) | {m for m in s3.CODENAMES if sl.load_2d(m) is not None}):
        S2 = sl.load_2d(mname)
        if S2 is None:
            continue
        fm = np.flatnonzero(F.map == mname)
        row = {"gun_kills": int(len(fm))}
        c2k, c2v = S2.cells(pk[fm])[0], S2.cells(pv[fm])[0]
        row["los2d_strict"] = float(S2.los(c2k, c2v).mean()) if len(fm) else None
        row["los2d_tolerant"] = float(S2.los_near(pk[fm], pv[fm]).mean()) if len(fm) else None
        # control: the killer against the victim's other living teammates
        mside = np.where(vside_att[fm][:, None], F.side_mask["att"][fm], F.side_mask["def"][fm])
        fi, sj = np.nonzero(mside)
        po = F.P[fm[fi], sj]
        row["control_pairs"] = int(len(fi))
        row["control2d_strict"] = float(S2.los(S2.cells(pk[fm[fi]])[0], S2.cells(po)[0]).mean()) if len(fi) else None
        row["control2d_tolerant"] = float(S2.los_near(pk[fm[fi]], po).mean()) if len(fi) else None
        T3 = table(mname, "3d")
        if T3 is not None:
            c3k, c3v = T3.cells(pk[fm])[0], T3.cells(pv[fm])[0]
            row["los3d_strict"] = float(T3.los(c3k, c3v).mean())
            row["control3d_strict"] = float(T3.los(T3.cells(pk[fm[fi]])[0], T3.cells(po)[0]).mean())
            row["map3d_build_s"] = T3.seconds
            row["map3d_edges"] = T3.edges_check
            row["off_cell_m_median"] = float(np.median(np.r_[T3.cells(pk[fm])[1], T3.cells(pv[fm])[1]]))
            pg = probe_gate(mname)
            row["probe_gate"] = pg
            use3 = pg is not None and pg["los3d_share_on_2d_set"] > pg["los2d_share"]
            res["choice"][mname] = "3d" if use3 else "2d"
            row["why"] = ("the probe's gate: 3D beats 2D on the same kills" if use3
                          else "the probe's gate does not favour 3D")
            # post hoc: the stricter cell-table rule written first, and discrimination
            row["table_rule_post_hoc"] = {
                "rule": "3D strict cell-table share exceeds the 2D table's strict and tolerant shares",
                "favours_3d": bool(row["los3d_strict"] > max(row["los2d_strict"], row["los2d_tolerant"])),
                "hit_minus_control_3d": round(row["los3d_strict"] - row["control3d_strict"], 4),
                "hit_minus_control_2d_strict": round(row["los2d_strict"] - row["control2d_strict"], 4),
                "hit_minus_control_2d_tolerant": round(row["los2d_tolerant"] - row["control2d_tolerant"], 4)}
        else:
            res["choice"][mname] = "2d"
            row["why"] = "no 3D table"
        res["maps"][mname] = row
    print(json.dumps(res, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gate.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if args.record:
        from reticle import metrics
        vals = {}
        for m, r in res["maps"].items():
            for k in ("gun_kills", "los2d_strict", "los2d_tolerant", "los3d_strict", "control2d_strict",
                      "control2d_tolerant", "control3d_strict"):
                if r.get(k) is not None:
                    vals[f"{m}.{k}"] = round(float(r[k]), 4)
        metrics.record("engagement_reach", part="gate", values=vals,
                       deps={"version": VERSION, "source": res["source"], "sightlines": sl.VERSION,
                             "sightlines_3d": s3.VERSION},
                       context={"set": "development: 22 captured Riot records, gun kills", "choice": res["choice"],
                                "rule": res["rule"]},
                       note="cell-table line of sight killer to victim; control: killer to the victim's other living teammates")
    return res


# ----------------------------------------------------------------- features

def load_set(name: str, loader_maps: set[str], exclude_holdout: bool = False):
    if name == "dev":
        return dv.Dev(), {"set": "development: 22 captured Riot records"}
    records, me, counts = ladder_records(loader_maps, exclude_holdout=exclude_holdout)
    dev = dv.Dev(records=records, me=me)
    counts["admitted_rounds"] = dev.R
    counts["round_admission"] = {k: v for k, v in dev.why.items() if not k.startswith("note_")}
    return dev, counts


def observer_att(dev, F) -> np.ndarray:
    """Whether the player's team attacks in each fight's round (-1 rows: unknown)."""
    ms = dev.me_slot[F.rr]
    return np.where(ms >= 0, dev.att[F.rr, np.clip(ms, 0, None)], False), ms >= 0


def fight_columns(feat: dict) -> dict:
    sw = dv.family_cols(feat, "swing", SWING_S)
    tr = dv.family_cols(feat, "trade", TRADE_T)
    nd = dv.family_cols(feat, "node", NODE_GRAPH)
    return {"reach": np.column_stack([sw, tr, nd]), "radius": dv.family_cols(feat, "radius", RADIUS_R),
            "join": tr, "swing": sw, "trade": tr, "node": nd}


def own_mask(own_att: np.ndarray, k: int) -> np.ndarray:
    """(F, 2k) mask keeping att columns where the player's team attacks, def columns where it defends."""
    return np.tile(np.column_stack([own_att, ~own_att]), k).astype(float)


def reach_rows(S, cells: np.ndarray, vis: np.ndarray, row: np.ndarray, batch: int = 1024) -> np.ndarray:
    """Walk metres from cells[i] to the nearest cell of vis[row[i]], in batches."""
    out = np.empty(len(cells))
    for b0 in range(0, len(cells), batch):
        b = slice(b0, b0 + batch)
        out[b] = S.reach_m(cells[b], vis[row[b]])
    return out


def region_reps(S) -> np.ndarray:
    """Per callout region, the region cell nearest the region's centroid."""
    reg = S.region[NODE_GRAPH]
    nreg = int(reg.max()) + 1
    ok = reg >= 0
    cnt = np.bincount(reg[ok], minlength=nreg).astype(float)
    cx = np.bincount(reg[ok], weights=S.cell_xy[ok, 0], minlength=nreg) / np.maximum(cnt, 1)
    cy = np.bincount(reg[ok], weights=S.cell_xy[ok, 1], minlength=nreg) / np.maximum(cnt, 1)
    d = np.hypot(S.cell_xy[:, 0] - cx[np.clip(reg, 0, None)], S.cell_xy[:, 1] - cy[np.clip(reg, 0, None)])
    d = np.where(ok, d, np.inf)
    order = np.lexsort((d, reg))
    o = order[ok[order]]
    first = o[np.r_[True, reg[o][1:] != reg[o][:-1]]]
    rep = np.full(nreg, -1, np.int64)
    rep[reg[first]] = first
    return rep


def region_reach(F, loader) -> dict:
    """Per side, each other player's walk metres to a cell seeing the opposing
    duelist when he stands at his callout region's representative cell."""
    out = {side: np.full((F.n, dv.SLOTS), np.inf) for side in ("att", "def")}
    for mname in np.unique(F.map):
        S = loader(mname)
        if S is None:
            continue
        rep = region_reps(S)
        fm = np.flatnonzero(F.map == mname)
        for side, other in (("att", "def"), ("def", "att")):
            pO = F.P[fm, F.duel[other][fm]]
            vis = S.vis_near(pO)
            fi, sj = np.nonzero(F.side_mask[side][fm])
            cp = S.cells(F.P[fm[fi], sj])[0]
            rg = S.region[NODE_GRAPH][cp]
            cr = np.where(rg >= 0, rep[np.clip(rg, 0, None)], cp)
            cr = np.where(cr >= 0, cr, cp)
            out[side][fm[fi], sj] = reach_rows(S, cr, vis, fi)
    return out


def death_rows(dev, loader) -> dict:
    """Deaths with a living teammate: trade within 5 s, the victim's
    teammates within TRADE_T m of a cell seeing the killer, and the nearest
    teammate's straight-line distance."""
    trade, revived = dev.deaths()
    ok = dev.valid & (dev.victim >= 0) & (dev.killer >= 0) & ~revived
    rr, kk = np.nonzero(ok)
    v, k = dev.victim[rr, kk], dev.killer[rr, kk]
    vatt = dev.att[rr, v]
    opp = dev.att[rr, k] != vatt
    pv, pk = dev.pos[rr, kk, v], dev.pos[rr, kk, k]
    mates = dev.alive[rr, kk] & (dev.att[rr] == vatt[:, None]) & ~np.isnan(dev.pos[rr, kk, :, 0])
    mates[np.arange(len(rr)), v] = False
    keep = opp & ~np.isnan(pv[:, 0]) & ~np.isnan(pk[:, 0]) & mates.any(1) & np.isin(dev.map[rr], list(_maps_of(loader, dev)))
    rr, kk, v, k, vatt, pv, pk, mates = rr[keep], kk[keep], v[keep], k[keep], vatt[keep], pv[keep], pk[keep], mates[keep]
    n = len(rr)
    P = dev.pos[rr, kk]
    eu = np.where(mates, np.linalg.norm(P - pv[:, None, :], axis=-1) / sl.UNITS_PER_M, np.inf)
    reach = np.full((n, dv.SLOTS), np.inf)
    mp = dev.map[rr]
    for mname in np.unique(mp):
        S = loader(mname)
        fm = np.flatnonzero(mp == mname)
        vis = S.vis_near(pk[fm])
        fi, sj = np.nonzero(mates[fm])
        cp = S.cells(P[fm[fi], sj])[0]
        reach[fm[fi], sj] = reach_rows(S, cp, vis, fi)
    al = dev.alive[rr, kk]
    own = (al & (dev.att[rr] == vatt[:, None])).sum(1)
    enemy = (al & (dev.att[rr] != vatt[:, None])).sum(1)
    return {"rr": rr, "kk": kk, "victim": v, "killer": k, "sid": dev.sid[rr], "map": mp, "vatt": vatt,
            "y": trade[rr, kk].astype(float), "able": (reach <= TRADE_T).sum(1), "nearest_m": eu.min(1),
            "own": own, "enemy": enemy, "planted": dev.planted[rr, kk], "n": n,
            "is_me": v == dev.me_slot[rr], "me_team": vatt == np.where(dev.me_slot[rr] >= 0,
                                                                     dev.att[rr, np.clip(dev.me_slot[rr], 0, None)], ~vatt)}


def _maps_of(loader, dev) -> set:
    return {m for m in np.unique(dev.map) if loader(m) is not None}


# ----------------------------------------------------------------- statistics

def refit_coefs(X, y, groups, pen, boot=BOOT, seed=5) -> np.ndarray:
    u = np.unique(groups)
    rows_of = {g: np.flatnonzero(groups == g) for g in u}
    rng = np.random.default_rng(seed)
    out = []
    for _b in range(boot):
        pick = rng.choice(u, len(u), replace=True)
        rows = np.concatenate([rows_of[g] for g in pick])
        out.append(wr.fit_logit(X[rows], y[rows], np.ones(len(rows)), pen))
    return np.array(out)


def ci(a) -> list:
    return [round(float(v), 5) for v in np.quantile(np.asarray(a), [0.025, 0.975])]


def ratio_ci(num, den, groups, boot=2000, seed=7) -> dict:
    """Ratio of sums with a match-resampled interval."""
    u, inv = np.unique(groups, return_inverse=True)
    sn = np.bincount(inv, weights=num, minlength=len(u))
    sd = np.bincount(inv, weights=den, minlength=len(u))
    rng = np.random.default_rng(seed)
    dr = rng.integers(0, len(u), (boot, len(u)))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = sn[dr].sum(1) / sd[dr].sum(1)
    point = float(sn.sum() / sd.sum()) if sd.sum() != 0 else None
    return {"value": None if point is None else round(point, 5), "ci95": ci(r[np.isfinite(r)]) if np.isfinite(r).any() else None,
            "num": round(float(sn.sum()), 5), "den": round(float(sd.sum()), 5), "matches": int(len(u))}


def group_mean(v, groups, mask, boot=2000, seed=9) -> dict:
    """Mean of v over mask rows, match-resampled interval."""
    m = np.asarray(mask, bool)
    if not m.any():
        return {"n": 0}
    out = ratio_ci(np.where(m, v, 0.0), m.astype(float), groups, boot, seed)
    return {"n": int(m.sum()), "mean": out["value"], "ci95": out["ci95"], "matches": int(len(np.unique(groups[m])))}


def diff_mean(v, groups, ma, mb, boot=2000, seed=11) -> dict:
    """Mean over ma minus mean over mb, resampling matches jointly."""
    u, inv = np.unique(groups, return_inverse=True)
    sa = np.bincount(inv, weights=np.where(ma, v, 0.0), minlength=len(u))
    na = np.bincount(inv, weights=ma.astype(float), minlength=len(u))
    sb = np.bincount(inv, weights=np.where(mb, v, 0.0), minlength=len(u))
    nb = np.bincount(inv, weights=mb.astype(float), minlength=len(u))
    rng = np.random.default_rng(seed)
    dr = rng.integers(0, len(u), (boot, len(u)))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = sa[dr].sum(1) / na[dr].sum(1) - sb[dr].sum(1) / nb[dr].sum(1)
    pt = sa.sum() / max(na.sum(), 1) - sb.sum() / max(nb.sum(), 1)
    return {"diff": round(float(pt), 5), "ci95": ci(d[np.isfinite(d)])}


def lomo_cf(X, Xcfs, y, groups, pen):
    """Held-out probabilities on X and on each counterfactual design."""
    p = np.zeros(len(y))
    pc = [np.zeros(len(y)) for _ in Xcfs]
    for g in np.unique(groups):
        k = groups == g
        beta = wr.fit_logit(X[~k], y[~k], np.ones(int((~k).sum())), pen)
        p[k] = wr.sig(X[k] @ beta)
        for j, Xc in enumerate(Xcfs):
            pc[j][k] = wr.sig(Xc[k] @ beta)
    return p, pc


# ----------------------------------------------------------------- step 3: scoring

def score(args) -> dict:
    t0 = time.time()
    loader, choice, g = chosen_loader()
    exclude_holdout = bool(getattr(args, "exclude_holdout", False))
    tag = getattr(args, "tag", None)
    dev, counts = load_set(args.set, set(choice), exclude_holdout=exclude_holdout)
    F = dv.Fights(dev)
    keep_maps = _maps_of(loader, dev)
    res = {"version": VERSION, "source": source_hash(), "set": args.set, "tag": tag,
           "exclude_holdout": exclude_holdout, "counts": counts,
           "map_choice": choice, "params": {"swing_s": SWING_S, "trade_t": TRADE_T, "radius_r": RADIUS_R,
                                            "node": NODE_GRAPH, "plant_t": PLANT_T},
           "held_out_excluded_by_dev": len(dev.held_excluded), "fights": F.n,
           "fights_dropped_no_position": F.dropped, "matches": int(len(np.unique(F.sid))),
           "fights_by_map": dict(Counter(F.map.tolist())),
           "fights_on_3d_maps": int(sum(1 for m in F.map if choice.get(m) == "3d"))}
    assert set(np.unique(F.map)) <= keep_maps, "a fight on a map without a table"
    y = F.y
    Xb, penb = F.baseline()
    lb = dv.bin_ll(dv.lomo_logit(Xb, y, F.sid, penb), y)
    feat = dv.reach_features(F, loader=loader, graphs=(NODE_GRAPH,))
    C = fight_columns(feat)
    oa, has_obs = observer_att(dev, F)
    res["fights_with_player_team"] = int(has_obs.sum())
    Xr = np.column_stack([Xb, C["reach"]])
    penr = penb + [dv.RIDGE] * 6
    Xrad = np.column_stack([Xb, C["radius"]])
    Xown = np.column_stack([Xb, C["reach"] * own_mask(oa, 3) * has_obs[:, None]])
    Xjoin = np.column_stack([Xb, C["join"]])
    # held-out probabilities; counterfactuals for the coaching readout
    cf_att = C["reach"].copy()
    cf_att[:, 0::2] = C["reach"][:, 1::2]          # attackers' counts set to the defenders'
    cf_def = C["reach"].copy()
    cf_def[:, 1::2] = C["reach"][:, 0::2]          # defenders' counts set to the attackers'
    pr, (pcf_att, pcf_def) = lomo_cf(Xr, [np.column_stack([Xb, cf_att]), np.column_stack([Xb, cf_def])], y, F.sid, penr)
    lr = dv.bin_ll(pr, y)
    lrad = dv.bin_ll(dv.lomo_logit(Xrad, y, F.sid, penb + [dv.RIDGE] * 2), y)
    lown = dv.bin_ll(dv.lomo_logit(Xown, y, F.sid, penr), y)
    ljoin = dv.bin_ll(dv.lomo_logit(Xjoin, y, F.sid, penb + [dv.RIDGE] * 2), y)
    res["baseline_nats"] = round(float(lb.mean()), 5)
    res["attacker_duel_win_rate"] = round(float(y.mean()), 4)
    res["mean_counts"] = {k: [round(float(C[k][:, 0].mean() * 4), 3), round(float(C[k][:, 1].mean() * 4), 3)]
                          for k in ("swing", "trade", "node", "radius")}
    # REACH1
    imp = dv.cluster_ci(lb - lr, F.sid)
    rng = np.random.default_rng(13)
    null = []
    for _i in range(args.shuffles):
        Ps = dv.shuffle_positions(F, rng)
        fs = fight_columns(dv.reach_features(F, Ps, loader=loader, graphs=(NODE_GRAPH,)))
        p = dv.lomo_logit(np.column_stack([Xb, fs["reach"]]), y, F.sid, penr)
        null.append(float((lb - dv.bin_ll(p, y)).mean()))
    res["REACH1"] = {"improvement": imp, "null": {"n": len(null), "mean": round(float(np.mean(null)), 5),
                                                  "p95": round(float(np.quantile(null, 0.95)), 5),
                                                  "share_ge_observed": round(float(np.mean(np.array(null) >= imp["mean"])), 3)},
                     "held": bool(imp["mean"] >= 0.01 and imp["ci95"][0] > 0
                                  and imp["mean"] > float(np.quantile(null, 0.95)))}
    # REACH2
    vs = dv.cluster_ci(lrad - lr, F.sid)
    res["REACH2"] = {"reach_minus_radius_gain": vs, "radius_improvement": dv.cluster_ci(lb - lrad, F.sid),
                     "held": bool(vs["ci95"][0] > 0)}
    # REACH3
    rown = ratio_ci((lb - lown)[has_obs], (lb - lr)[has_obs], F.sid[has_obs])
    res["REACH3"] = {"own_improvement": dv.cluster_ci(lb - lown, F.sid), "share_of_reach_gain": rown,
                     "held": bool(rown["value"] is not None and rown["den"] > 0 and rown["value"] >= 0.5)}
    # REACH4
    bj = wr.fit_logit(Xjoin, y, np.ones(len(y)), penb + [dv.RIDGE] * 2)
    BJ = refit_coefs(Xjoin, y, F.sid, penb + [dv.RIDGE] * 2)
    br = wr.fit_logit(Xr, y, np.ones(len(y)), penr)
    BR = refit_coefs(Xr, y, F.sid, penr)
    names = ["swing_att", "swing_def", "trade_att", "trade_def", "node_att", "node_def"]
    nb = Xb.shape[1]
    res["REACH4"] = {"join_model": {"improvement": dv.cluster_ci(lb - ljoin, F.sid),
                                    "coef_att_per_player": round(float(bj[nb] / 4), 4), "ci95_att": ci(BJ[:, nb] / 4),
                                    "coef_def_per_player": round(float(bj[nb + 1] / 4), 4), "ci95_def": ci(BJ[:, nb + 1] / 4),
                                    "note": "label: attacking duelist wins; per player = coefficient / 4"},
                     "reach_model_coefs_per_player": {nm: {"beta": round(float(br[nb + i] / 4), 4), "ci95": ci(BR[:, nb + i] / 4)}
                                                      for i, nm in enumerate(names)},
                     "held": bool(ci(BJ[:, nb])[0] > 0 and ci(BJ[:, nb + 1])[1] < 0)}
    # REACH5
    res["REACH5"] = plant_test(dev, loader)
    # REACH6
    D6 = death_rows(dev, loader)
    res["REACH6"] = trade_test(D6)
    # region precision (fidelity, own team)
    rr_ = region_reach(F, loader)
    ex_sw = np.where(oa, (feat["att"]["reach"] <= SWING_S).sum(1), (feat["def"]["reach"] <= SWING_S).sum(1))
    ex_tr = np.where(oa, (feat["att"]["reach"] <= TRADE_T).sum(1), (feat["def"]["reach"] <= TRADE_T).sum(1))
    rg_sw = np.where(oa, (rr_["att"] <= SWING_S).sum(1), (rr_["def"] <= SWING_S).sum(1))
    rg_tr = np.where(oa, (rr_["att"] <= TRADE_T).sum(1), (rr_["def"] <= TRADE_T).sum(1))
    featR = {s_: dict(feat[s_]) for s_ in ("att", "def")}
    for s_ in ("att", "def"):
        featR[s_]["reach"] = rr_[s_]
    CR = fight_columns(featR)
    XownR = np.column_stack([Xb, CR["reach"] * own_mask(oa, 3) * has_obs[:, None]])
    lownR = dv.bin_ll(dv.lomo_logit(XownR, y, F.sid, penr), y)
    res["region_precision"] = {
        "own_swing_equal_share": round(float((ex_sw == rg_sw)[has_obs].mean()), 4),
        "own_trade_equal_share": round(float((ex_tr == rg_tr)[has_obs].mean()), 4),
        "own_swing_mean_abs_diff": round(float(np.abs(ex_sw - rg_sw)[has_obs].mean()), 4),
        "own_trade_mean_abs_diff": round(float(np.abs(ex_tr - rg_tr)[has_obs].mean()), 4),
        "own_region_improvement": dv.cluster_ci(lb - lownR, F.sid),
        "own_region_minus_own_exact": dv.cluster_ci(lown - lownR, F.sid),
        "note": "own team's other players at their callout region's representative cell; opposing duelist exact"}
    # coaching readout
    res["coaching"] = coaching(dev, F, C, y, pr, pcf_att, pcf_def, D6)
    res["seconds"] = round(time.time() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"score_{args.set}" + (f"_{tag}" if tag else "")
    (OUT / f"{name}.json").write_text(json.dumps(res, indent=1, default=_js), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("set", "fights", "matches", "baseline_nats", "REACH1", "REACH2", "REACH3",
                                         "REACH4", "REACH5", "REACH6", "region_precision")}, indent=1, default=_js))
    if args.record:
        record_score(res)
    return res


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(type(o))


def plant_test(dev, loader) -> dict:
    pf = dv.plant_features(dev, loader)
    keep = np.isin(pf["map"], list(_maps_of(loader, dev)))
    n = int(keep.sum())
    a, d, tp, y, sid = pf["a"][keep], pf["d"][keep], pf["tp"][keep], pf["y"][keep], pf["sid"][keep]
    reach_m, path_m = pf["reach_m"][keep], pf["path_m"][keep]
    is_att, present = pf["is_att"][keep], pf["present"][keep]
    deff = present & ~is_att
    md = np.where(deff, np.minimum(path_m, 150.0), 0.0).sum(1) / np.maximum(deff.sum(1), 1)
    Xb = np.column_stack([np.ones(n), (a - d) / 5.0, (a - d) / np.maximum(a + d, 1.0), tp / 100.0])
    penb = [0.0, dv.RIDGE, dv.RIDGE, dv.RIDGE]
    lb = dv.bin_ll(dv.lomo_logit(Xb, y, sid, penb), y)
    att_r = ((reach_m <= PLANT_T) & is_att & present).sum(1)
    def_r = ((reach_m <= PLANT_T) & deff).sum(1)
    X = np.column_stack([Xb, att_r / 5.0, def_r / 5.0, md / 50.0])
    pen = penb + [dv.RIDGE] * 3
    lt = dv.bin_ll(dv.lomo_logit(X, y, sid, pen), y)
    imp = dv.cluster_ci(lb - lt, sid)
    beta = wr.fit_logit(X, y, np.ones(n), pen)
    B = refit_coefs(X, y, sid, pen)
    out = {"planted_rounds": n, "baseline_nats": round(float(lb.mean()), 5), "improvement": imp,
           "mean_att_reach": round(float(att_r.mean()), 3), "mean_def_reach": round(float(def_r.mean()), 3),
           "def_mean_path_m": round(float(md.mean()), 1),
           "coef_def_reach_per_player": round(float(beta[5] / 5), 4), "ci95_def_reach": ci(B[:, 5] / 5),
           "coef_att_reach_per_player": round(float(beta[4] / 5), 4), "ci95_att_reach": ci(B[:, 4] / 5),
           "coef_def_mean_path_per_50m": round(float(beta[6]), 4), "ci95_def_mean_path": ci(B[:, 6]),
           "note": "label: attackers win the round; a negative def_reach coefficient raises the defenders' odds"}
    out["held"] = bool(imp["mean"] >= 0.01 and imp["ci95"][0] > 0 and ci(B[:, 5])[1] < 0)
    return out


def trade_test(D6) -> dict:
    n = D6["n"]
    base = [np.ones(n), (D6["own"] - D6["enemy"]) / 5.0, D6["own"] / 5.0, D6["planted"].astype(float)]
    pen = [0.0, dv.RIDGE, dv.RIDGE, dv.RIDGE, dv.RIDGE]
    XA = np.column_stack(base + [D6["able"] / 4.0])
    XB = np.column_stack(base + [np.minimum(D6["nearest_m"], 150.0) / 10.0])
    y, sid = D6["y"], D6["sid"]
    la = dv.bin_ll(dv.lomo_logit(XA, y, sid, pen), y)
    lbn = dv.bin_ll(dv.lomo_logit(XB, y, sid, pen), y)
    l0 = dv.bin_ll(dv.lomo_logit(np.column_stack(base), y, sid, pen[:-1]), y)
    d = dv.cluster_ci(lbn - la, sid)
    BA = refit_coefs(XA, y, sid, pen)
    return {"deaths": int(n), "traded": int(y.sum()), "trade_rate": round(float(y.mean()), 4),
            "mean_able": round(float(D6["able"].mean()), 3),
            "able_nats": round(float(la.mean()), 5), "distance_nats": round(float(lbn.mean()), 5),
            "z_only_nats": round(float(l0.mean()), 5),
            "able_minus_distance_gain": d, "able_improvement_over_z": dv.cluster_ci(l0 - la, sid),
            "distance_improvement_over_z": dv.cluster_ci(l0 - lbn, sid),
            "coef_able_per_player": round(float(wr.fit_logit(XA, y, np.ones(n), pen)[-1] / 4), 4),
            "ci95_able": ci(BA[:, -1] / 4),
            "held": bool(d["ci95"][0] > 0)}


# ----------------------------------------------------------------- step 4: coaching

def coaching(dev, F, C, y, pr, pcf_att, pcf_def, D6) -> dict:
    V = dv.Value(dev)
    rr, kk = F.rr, F.kk
    econ = dev.econ[rr]
    before = dev.alive_before[rr, kk]
    attm = dev.att[rr]
    aload = (econ * (before & attm)).sum(1)
    dload = (econ * (before & ~attm)).sum(1)
    ar = np.arange(F.n)
    ea, ed = econ[ar, F.duel["att"]], econ[ar, F.duel["def"]]
    v_def_loses = V.v(F.sid, F.a, F.d - 1, aload, dload - ed, F.planted)
    v_att_loses = V.v(F.sid, F.a - 1, F.d, aload - ea, dload, F.planted)
    dV = v_def_loses - v_att_loses
    raw = {k: np.rint(C[k] * 4).astype(int) for k in ("swing", "trade")}
    rows = []
    for side, si, oi in (("att", 0, 1), ("def", 1, 0)):
        own_join, en_join = raw["trade"][:, si], raw["trade"][:, oi]
        bal = (raw["swing"][:, si] + raw["trade"][:, si]) - (raw["swing"][:, oi] + raw["trade"][:, oi])
        p_own = pr if side == "att" else 1 - pr
        p_cf = pcf_att if side == "att" else 1 - pcf_def
        won = y.astype(bool) if side == "att" else ~y.astype(bool)
        rows.append({"slot": F.duel[side], "side_att": np.full(F.n, side == "att"), "own_join": own_join,
                     "en_join": en_join, "balance": bal, "won": won, "cost": (p_cf - p_own) * dV,
                     "sid": F.sid, "map": F.map, "rr": rr})
    R = {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}
    me = dev.me_slot[R["rr"]]
    has = me >= 0
    is_me = has & (R["slot"] == me)
    my_att = np.where(has, dev.att[R["rr"], np.clip(me, 0, None)], False)
    own_is_my_team = has & (R["side_att"] == my_att)
    groups = {"player": is_me, "team": own_is_my_team, "peers": has & ~is_me, "opponents": has & ~own_is_my_team}
    out_n = R["own_join"] < R["en_join"]
    lost = ~R["won"]
    res = {"fights_read_from_both_sides": int(len(R["slot"])), "groups": {}}
    sid = R["sid"]
    for gname, gm in groups.items():
        died = gm & lost
        cost_out = np.where(out_n, R["cost"], 0.0)
        g = {"fights": int(gm.sum()), "deaths": int(died.sum()),
             "reach_balance": group_mean(R["balance"].astype(float), sid, gm),
             "share_fights_outnumbered": group_mean(out_n.astype(float), sid, gm),
             "share_deaths_outnumbered": group_mean(out_n.astype(float), sid, died),
             "share_wins_outnumbered": group_mean(out_n.astype(float), sid, gm & R["won"]),
             "duel_win_rate": group_mean(R["won"].astype(float), sid, gm),
             "duel_win_rate_outnumbered": group_mean(R["won"].astype(float), sid, gm & out_n),
             "wp_cost_per_outnumbered_fight": group_mean(R["cost"], sid, gm & out_n),
             "wp_cost_per_fight": group_mean(cost_out, sid, gm)}
        res["groups"][gname] = g
    res["player_minus_peers"] = {
        "reach_balance": diff_mean(R["balance"].astype(float), sid, groups["player"], groups["peers"]),
        "share_deaths_outnumbered": diff_mean(out_n.astype(float), sid, groups["player"] & lost, groups["peers"] & lost),
        "wp_cost_per_fight": diff_mean(np.where(out_n, R["cost"], 0.0), sid, groups["player"], groups["peers"])}
    res["team_minus_opponents"] = {
        "reach_balance": diff_mean(R["balance"].astype(float), sid, groups["team"], groups["opponents"]),
        "share_deaths_outnumbered": diff_mean(out_n.astype(float), sid, groups["team"] & lost, groups["opponents"] & lost),
        "wp_cost_per_fight": diff_mean(np.where(out_n, R["cost"], 0.0), sid, groups["team"], groups["opponents"])}
    # untraded deaths a teammate could have traded
    able = D6["able"] > 0
    untr = able & (D6["y"] == 0)
    me6 = D6["is_me"]
    team6 = D6["me_team"]
    res["deaths_tradeable_untraded"] = {
        "player": {"deaths_with_living_teammate": int(me6.sum()),
                   "share": group_mean(untr.astype(float), D6["sid"], me6),
                   "share_untraded_given_able": group_mean((D6["y"] == 0).astype(float), D6["sid"], me6 & able)},
        "team": {"deaths_with_living_teammate": int(team6.sum()),
                 "share": group_mean(untr.astype(float), D6["sid"], team6)},
        "peers": {"deaths_with_living_teammate": int((~me6).sum()),
                  "share": group_mean(untr.astype(float), D6["sid"], ~me6)},
        "opponents": {"deaths_with_living_teammate": int((~team6).sum()),
                      "share": group_mean(untr.astype(float), D6["sid"], ~team6)},
        "player_minus_peers": diff_mean(untr.astype(float), D6["sid"], me6, ~me6)}
    # by map and side, the player and his team
    res["by_map"], res["by_side"] = {}, {}
    for gname in ("player", "team"):
        gm = groups[gname]
        res["by_map"][gname] = {}
        for m in sorted(np.unique(R["map"])):
            mm = gm & (R["map"] == m)
            if int((mm & lost).sum()) < 20:
                res["by_map"][gname][m] = {"fights": int(mm.sum()), "note": "under 20 deaths: not reported"}
                continue
            res["by_map"][gname][m] = {"fights": int(mm.sum()),
                                       "reach_balance": group_mean(R["balance"].astype(float), sid, mm),
                                       "share_deaths_outnumbered": group_mean(out_n.astype(float), sid, mm & lost),
                                       "wp_cost_per_fight": group_mean(np.where(out_n, R["cost"], 0.0), sid, mm)}
        res["by_side"][gname] = {}
        for s_, sm in (("attack", R["side_att"]), ("defence", ~R["side_att"])):
            mm = gm & sm
            res["by_side"][gname][s_] = {"fights": int(mm.sum()),
                                         "reach_balance": group_mean(R["balance"].astype(float), sid, mm),
                                         "share_deaths_outnumbered": group_mean(out_n.astype(float), sid, mm & lost),
                                         "wp_cost_per_fight": group_mean(np.where(out_n, R["cost"], 0.0), sid, mm)}
    # post hoc (added after the confirmation readout): the player against
    # lobby peers on the same side, since defence is outnumbered by structure
    res["post_hoc_player_minus_peers_by_side"] = {}
    for s_, sm in (("attack", R["side_att"]), ("defence", ~R["side_att"])):
        pm, qm = groups["player"] & sm, groups["peers"] & sm
        res["post_hoc_player_minus_peers_by_side"][s_] = {
            "peers_reach_balance": group_mean(R["balance"].astype(float), sid, qm),
            "peers_share_deaths_outnumbered": group_mean(out_n.astype(float), sid, qm & lost),
            "reach_balance": diff_mean(R["balance"].astype(float), sid, pm, qm),
            "share_deaths_outnumbered": diff_mean(out_n.astype(float), sid, pm & lost, qm & lost),
            "wp_cost_per_fight": diff_mean(np.where(out_n, R["cost"], 0.0), sid, pm, qm)}
    res["dV_mean"] = round(float(dV.mean()), 4)
    res["pricing"] = f"V: {wr.VERSION} B1 (alive, load, side, flag), fitted with the fight's match left out"
    return res


# ----------------------------------------------------------------- step 5: stored allies

def fidelity(args) -> dict:
    """Own-team swing and trade counts at development fight instants, from
    reticle's stored ally and self icons against Riot's positions."""
    loader, choice, _g = chosen_loader()
    dev = dv.Dev()
    F = dv.Fights(dev)
    why = Counter()
    frames = wr.capture_frames(dev.rounds, dev.ref, dev.records, dv.OUT / "cache", why)
    oa, has_obs = observer_att(dev, F)
    dO = np.where(oa, F.duel["def"], F.duel["att"])
    pO = F.P[np.arange(F.n), dO]
    # Riot: the player's team's living players before the kill, own duelist included
    own_mask_ = dev.alive_before[F.rr, F.kk] & (dev.att[F.rr] == oa[:, None]) & ~np.isnan(F.P[..., 0])
    riot_sw = np.zeros(F.n, int)
    riot_tr = np.zeros(F.n, int)
    st_sw = np.full(F.n, -1)
    st_tr = np.full(F.n, -1)
    st_n = np.full(F.n, -1)
    versions = {}
    # stored icons at each fight instant (vectorised per session)
    icon_f, icon_xy = [], []
    rstart = np.array([dev.rounds[r]["rstart_game"] if dev.rounds[r]["rstart_game"] is not None else np.nan
                       for r in F.rr])
    for sid in np.unique(F.sid):
        ii = np.flatnonzero((F.sid == sid) & has_obs)
        fr = frames.get(sid)
        if fr is None or fr["mf"] is None:
            why["no_frame_session"] += len(ii)
            continue
        t, f, x, yv, ver = dv.stored_allies(sid, dv.OUT / "cache")
        versions[sid] = ver
        ts = fr["a_ms"] + rgt.MINIMAP_LAG_MS + rstart[ii] + F.t[ii] * 1000.0
        k = np.clip(np.searchsorted(t, ts), 1, len(t) - 1)
        tf = np.where(np.abs(t[k - 1] - ts) <= np.abs(t[k] - ts), t[k - 1], t[k])
        good = np.abs(tf - ts) <= dv.FRAME_TOL_MS
        why["no_frame_within_tol"] += int((~good).sum())
        lo = np.searchsorted(t, tf, "left")
        hi = np.searchsorted(t, tf, "right")
        cnt = np.where(good, hi - lo, 0)
        tot = int(cnt.sum())
        start = np.repeat(lo, cnt)
        offs = np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        idx = start + offs
        p0 = np.array(fr["mf"].to_px(0.0, 0.0))
        J = np.column_stack([np.array(fr["mf"].to_px(1000.0, 0.0)) - p0,
                             np.array(fr["mf"].to_px(0.0, 1000.0)) - p0]) / 1000.0
        g_xy = (np.column_stack([x[idx], yv[idx]]) - p0) @ np.linalg.inv(J).T
        icon_f.append(np.repeat(ii, cnt))
        icon_xy.append(g_xy)
        st_n[ii[good]] = cnt[good]
    icon_f = np.concatenate(icon_f) if icon_f else np.zeros(0, int)
    icon_xy = np.concatenate(icon_xy) if icon_xy else np.zeros((0, 2))
    for mname in np.unique(F.map):
        S = loader(mname)
        fm = np.flatnonzero(F.map == mname)
        loc = np.full(F.n, -1, np.int64)
        loc[fm] = np.arange(len(fm))
        vis = S.vis_near(pO[fm])
        fi, sj = np.nonzero(own_mask_[fm])
        cp = S.cells(F.P[fm[fi], sj])[0]
        r = reach_rows(S, cp, vis, fi)
        riot_sw[fm] = np.bincount(fi, weights=(r <= SWING_S), minlength=len(fm)).astype(int)
        riot_tr[fm] = np.bincount(fi, weights=(r <= TRADE_T), minlength=len(fm)).astype(int)
        im = np.flatnonzero(np.isin(icon_f, fm))
        if len(im):
            ci_ = S.cells(icon_xy[im])[0]
            li = loc[icon_f[im]]
            rs = reach_rows(S, ci_, vis, li)
            sw_ = np.bincount(li, weights=(rs <= SWING_S), minlength=len(fm)).astype(int)
            tr_ = np.bincount(li, weights=(rs <= TRADE_T), minlength=len(fm)).astype(int)
            covered = st_n[fm] >= 0
            st_sw[fm[covered]] = sw_[covered]
            st_tr[fm[covered]] = tr_[covered]
    cov = (st_n >= 0) & has_obs
    riot_n = own_mask_.sum(1)
    res = {"version": VERSION, "source": source_hash(), "set": "development: 22 captured Riot records, gun kills",
           "map_choice": choice, "fights": int(F.n), "fights_with_player_team": int(has_obs.sum()),
           "covered": int(cov.sum()), "coverage": round(float(cov.sum() / max(1, has_obs.sum())), 4),
           "why": dict(why), "stream": "round_entity (families ally, self)",
           "versions": sorted(set(versions.values())),
           "own_count_equal_share": round(float((st_n == riot_n)[cov].mean()), 4),
           "swing_equal_share": round(float((st_sw == riot_sw)[cov].mean()), 4),
           "trade_equal_share": round(float((st_tr == riot_tr)[cov].mean()), 4),
           "swing_within_one_share": round(float((np.abs(st_sw - riot_sw) <= 1)[cov].mean()), 4),
           "trade_within_one_share": round(float((np.abs(st_tr - riot_tr) <= 1)[cov].mean()), 4),
           "swing_mean_diff": round(float((st_sw - riot_sw)[cov].mean()), 4),
           "trade_mean_diff": round(float((st_tr - riot_tr)[cov].mean()), 4),
           "riot_mean_swing": round(float(riot_sw[cov].mean()), 3), "riot_mean_trade": round(float(riot_tr[cov].mean()), 3),
           "note": "counts include the own duelist; the opposing duelist keeps Riot's position"}
    res["swing_kappa"] = kappa(st_sw[cov], riot_sw[cov])
    res["trade_kappa"] = kappa(st_tr[cov], riot_tr[cov])
    print(json.dumps(res, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fidelity.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if args.record:
        from reticle import metrics
        vals = {k: res[k] for k in ("fights", "covered", "coverage", "own_count_equal_share", "swing_equal_share",
                                     "trade_equal_share", "swing_within_one_share", "trade_within_one_share",
                                     "swing_mean_diff", "trade_mean_diff", "swing_kappa", "trade_kappa")}
        metrics.record("engagement_reach", part="fidelity", values=vals,
                       deps={"version": VERSION, "source": res["source"], "stream": res["stream"],
                             "versions": res["versions"], "map_choice": choice},
                       context={"set": res["set"], "why": res["why"]},
                       note="stored events only; frame within 250 ms of the aligned kill instant")
    return res


def kappa(a, b) -> float:
    """Cohen's kappa of two count labelings."""
    a, b = np.asarray(a, int), np.asarray(b, int)
    if not len(a):
        return float("nan")
    k = int(max(a.max(), b.max())) + 1
    M = np.zeros((k, k))
    np.add.at(M, (a, b), 1)
    M /= M.sum()
    po = np.trace(M)
    pe = (M.sum(0) * M.sum(1)).sum()
    return round(float((po - pe) / (1 - pe)), 4) if pe < 1 else 1.0


# ----------------------------------------------------------------- ledger

def record_score(res: dict) -> None:
    from reticle import metrics
    v, c = {}, {}

    def put(key, block, field="mean"):
        v[key] = block[field]
        if block.get("ci95") is not None:
            c[key] = block["ci95"]
    v.update({"fights": res["fights"], "matches": res["matches"], "baseline_nats": res["baseline_nats"],
              "fights_on_3d_maps": res["fights_on_3d_maps"]})
    for k in ("matches_listed", "held_out_excluded", "captured_excluded", "no_table_excluded", "holdout_excluded",
              "admitted_rounds", "planter_on_attacking_team", "planter_on_other_team"):
        if k in res["counts"]:
            v[f"set.{k}"] = res["counts"][k]
    v["REACH6.able_improvement_over_z_nats"] = res["REACH6"]["able_improvement_over_z"]["mean"]
    v["REACH6.distance_improvement_over_z_nats"] = res["REACH6"]["distance_improvement_over_z"]["mean"]
    v["REACH5.baseline_nats"] = res["REACH5"]["baseline_nats"]
    v["region.own_region_minus_own_exact_nats"] = res["region_precision"]["own_region_minus_own_exact"]["mean"]
    c["region.own_region_minus_own_exact_nats"] = res["region_precision"]["own_region_minus_own_exact"]["ci95"]
    pt = res["coaching"]["deaths_tradeable_untraded"]["player"]["share_untraded_given_able"]
    if pt.get("n"):
        v["coach.player.share_untraded_given_able"], c["coach.player.share_untraded_given_able"] = pt["mean"], pt["ci95"]
    for g in ("player", "peers"):
        b = res["coaching"]["groups"][g]["duel_win_rate"]
        v[f"coach.{g}.duel_win_rate"], c[f"coach.{g}.duel_win_rate"] = b["mean"], b["ci95"]
    v["coach.dV_mean"] = res["coaching"]["dV_mean"]
    put("REACH1.improvement_nats", res["REACH1"]["improvement"])
    v["REACH1.null_p95"] = res["REACH1"]["null"]["p95"]
    v["REACH1.null_mean"] = res["REACH1"]["null"]["mean"]
    v["REACH1.null_n"] = res["REACH1"]["null"]["n"]
    v["REACH1.null_share_ge_observed"] = res["REACH1"]["null"]["share_ge_observed"]
    put("REACH2.reach_minus_radius_nats", res["REACH2"]["reach_minus_radius_gain"])
    put("REACH2.radius_improvement_nats", res["REACH2"]["radius_improvement"])
    put("REACH3.own_improvement_nats", res["REACH3"]["own_improvement"])
    put("REACH3.own_share", res["REACH3"]["share_of_reach_gain"], "value")
    j = res["REACH4"]["join_model"]
    v["REACH4.coef_att_per_player"], c["REACH4.coef_att_per_player"] = j["coef_att_per_player"], j["ci95_att"]
    v["REACH4.coef_def_per_player"], c["REACH4.coef_def_per_player"] = j["coef_def_per_player"], j["ci95_def"]
    put("REACH4.join_improvement_nats", j["improvement"])
    p5 = res["REACH5"]
    v["REACH5.planted_rounds"] = p5["planted_rounds"]
    put("REACH5.improvement_nats", p5["improvement"])
    v["REACH5.coef_def_reach_per_player"], c["REACH5.coef_def_reach_per_player"] = p5["coef_def_reach_per_player"], p5["ci95_def_reach"]
    p6 = res["REACH6"]
    v["REACH6.deaths"] = p6["deaths"]
    put("REACH6.able_minus_distance_nats", p6["able_minus_distance_gain"])
    for k in ("REACH1", "REACH2", "REACH3", "REACH4", "REACH5", "REACH6"):
        v[f"{k}.held"] = int(bool(res[k]["held"]))
    rp = res["region_precision"]
    v["region.own_swing_equal_share"] = rp["own_swing_equal_share"]
    v["region.own_trade_equal_share"] = rp["own_trade_equal_share"]
    put("region.own_region_improvement_nats", rp["own_region_improvement"])
    co = res["coaching"]
    for g in ("player", "team", "peers", "opponents"):
        b = co["groups"][g]
        for k in ("reach_balance", "share_deaths_outnumbered", "wp_cost_per_outnumbered_fight", "wp_cost_per_fight",
                  "share_fights_outnumbered", "duel_win_rate_outnumbered"):
            if b[k].get("n"):
                put(f"coach.{g}.{k}", b[k])
        put(f"coach.{g}.share_deaths_tradeable_untraded", co["deaths_tradeable_untraded"][g]["share"])
    for k, b in co["player_minus_peers"].items():
        put(f"coach.player_minus_peers.{k}", b, "diff")
    for k, b in co["team_minus_opponents"].items():
        put(f"coach.team_minus_opponents.{k}", b, "diff")
    put("coach.player_minus_peers.share_deaths_tradeable_untraded",
        co["deaths_tradeable_untraded"]["player_minus_peers"], "diff")
    for g in ("player", "team"):
        for s_, b in co["by_side"][g].items():
            for k in ("reach_balance", "share_deaths_outnumbered", "wp_cost_per_fight"):
                if b[k].get("n"):
                    put(f"coach.{g}.{s_}.{k}", b[k])
    for s_, b in co.get("post_hoc_player_minus_peers_by_side", {}).items():
        for k in ("reach_balance", "share_deaths_outnumbered", "wp_cost_per_fight"):
            put(f"coach.post_hoc.player_minus_peers.{s_}.{k}", b[k], "diff")
    label = "development: 22 captured Riot records" if res["set"] == "dev" else \
        "confirmation: the player's own HenrikDev history, captured and held-out matches excluded"
    if res.get("exclude_holdout"):
        label += "; post hoc sensitivity: the ladder's holdout matches excluded as well"
    part = res["set"] + (f"/{res['tag']}" if res.get("tag") else "")
    metrics.record("engagement_reach", part=part, values=v, ci=c,
                   deps={"version": VERSION, "source": res["source"], "params": res["params"],
                         "map_choice": res["map_choice"], "sightlines": sl.VERSION, "sightlines_3d": s3.VERSION,
                         "value_model": wr.VERSION + " B1", "shuffles": res["REACH1"]["null"]["n"], "boot": BOOT},
                   context={"set": label, "counts": {k: v_ for k, v_ in res["counts"].items() if k != "round_admission"}},
                   note="parameters fixed on development; leave one match out; intervals resample matches")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--record", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--set", choices=("dev", "confirm"), required=True)
    s.add_argument("--record", action="store_true")
    s.add_argument("--shuffles", type=int, default=SHUFFLES)
    s.add_argument("--exclude-holdout", action="store_true",
                   help="post hoc: drop the ladder's holdout matches as well")
    s.add_argument("--tag", default=None, help="suffix for the results file and the ledger part")
    f = sub.add_parser("fidelity")
    f.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    quiet()
    {"gate": gate, "score": score, "fidelity": fidelity}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
