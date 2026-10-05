r"""A descriptive coaching profile of the player against their lobby peers.

    .\.venv\Scripts\python.exe prototypes\player_profile.py run [--out DIR] [--boot N]

What it reads
-------------
The player's own competitive history as HenrikDev's v4 records
(`<store>/external/ladder/henrikdev/v4/raw`, read through
`ladder_fetch.stored_matches`) and the captured matches' Riot records
(`<store>/external/riot/*.json`, through `riot_ground_truth.riot_records`,
carried into the v4 shape by `ladder_fetch.riot_to_v4`). Both pass through
`ladder_fetch.parse_matches`, the owner of the parsed schema, with the
store's pseudonym salt: every PUUID becomes a pseudonym and the owner row is
`is_owner`. The parser drops per-player damage events and ability casts;
`extras_v4` reads those two fields from the same v4 objects (and
`riot_extras_v4` reshapes Riot's fields into them) with the same pseudonyms.

The player's accounts come from `ladder_fetch.owner_accounts`, which merges
the owner seeds (labels A, B, C) with `riot_ground_truth.identify_player`.
Matches the player kept a replay of without a capture
(`external/replays/manifest.json`, `capture_session` null) are excluded: they
are evaluation truth [REPLAY_KEEPING.md].

What it computes
----------------
Per round and per player: opening duels, deaths traded and trades made,
untraded deaths and the nearest teammate's distance at death, multi-kills,
clutches (1vX) from `winprob_reference.simulate` (the living sets after each
kill, revives included), plants, defuses and post-plant deaths and kills,
loadout against the teammates' mean, buy bands and their outcomes, damage,
headshot share and KAST; per match, ability casts by slot. Every metric is a
ratio of summed counts, the player's against the pooled lobby peers' (every
other player in the same matches, in aggregate only), with a percentile
interval from resampling matches. `docs/PLAYER_PROFILE.md` lists the metrics.

Choices, not domain facts
-------------------------
- `TRADE_WINDOW_MS`: a death is traded when its killer dies to the victim's
  team within 5 s; no domain fact records a window. The report repeats the
  traded share at 3 s and 7 s.
- Sides: Red attacks rounds 0-11 and even overtime rounds (24, 26, ...), Blue
  the rest. No owner states the boundary by round index; the report checks
  the rule against Riot's `winningTeamRole` on the captured records and
  against every planter's team, and counts the disagreements.
- Buy bands by the team's mean loadout: eco below 2000, force from 2000 to
  3899, full from 3900; pistol rounds are the first of each half.
- `ISOLATED_CM` is `winprob_reference.ISOLATED_CM`.

Privacy
-------
The output (numbers, per-match values) goes only to the store
(`<store>/analysis/player-profile-20261004/`). The console prints counts and
paths only. Peers appear only pooled.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
if sys.platform == "win32":  # Below Normal priority, as every script here
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import ladder_fetch as lf  # noqa: E402
import riot_ground_truth as rgt  # noqa: E402
import winprob_reference as wr  # noqa: E402

VERSION = "player-profile-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
OUT_NAME = "player-profile-20261004"

#: A choice: no domain fact records a trade window.
TRADE_WINDOW_MS = 5000.0
TRADE_SENSITIVITY_MS = (3000.0, 7000.0)
#: The side rule, checked in the report against Riot's roles and the planters.
HALF_ROUNDS = 12
REGULATION_ROUNDS = 24
FIRST_ATTACKER = "Red"
#: Buy bands by the team's mean loadout, a choice.
ECO_MAX = 2000.0
FULL_MIN = 3900.0
ISOLATED_CM = wr.ISOLATED_CM
MIN_EVENTS = 30
BOOT = 2000
SEED = 20261004


# ----------------------------------------------------------------- sources

def kept_replay_matches(store: Path) -> set[str]:
    """Match ids of kept replays with no capture beside them."""
    p = Path(store) / "external" / "replays" / "manifest.json"
    if not p.is_file():
        return set()
    files = json.loads(p.read_text(encoding="utf-8")).get("files") or []
    return {Path(f["file"]).stem for f in files if not f.get("capture_session")}


def riot_extras_v4(rec: dict) -> dict:
    """Riot's damage events and ability casts in the v4 field names.

    Field for field: `roundResults[].playerStats[].damage` becomes
    `rounds[].stats[].damage_events`, `players[].stats.abilityCasts` becomes
    `players[].ability_casts`. Nothing is computed.
    """
    m = rec.get("match", rec)
    team_of = {p["subject"]: p["teamId"] for p in m["players"]}

    def who(s):
        return {"puuid": s, "team": team_of.get(s)}

    def casts(p):
        a = (p.get("stats") or {}).get("abilityCasts") or {}
        return {"grenade": a.get("grenadeCasts"),
                "ability1": a.get("ability1Casts"),
                "ability2": a.get("ability2Casts"),
                "ultimate": a.get("ultimateCasts")}
    return {
        "metadata": {"match_id": m["matchInfo"]["matchId"]},
        "players": [{"puuid": p["subject"], "ability_casts": casts(p)}
                    for p in m["players"]],
        "rounds": [{"id": r["roundNum"], "stats": [{
            "player": who(ps["subject"]),
            "damage_events": [{"player": who(d.get("receiver")),
                               "damage": d.get("damage"),
                               "headshots": d.get("headshots"),
                               "bodyshots": d.get("bodyshots"),
                               "legshots": d.get("legshots")}
                              for d in ps.get("damage") or []]}
            for ps in r.get("playerStats") or []]}
            for r in m.get("roundResults") or []]}


def extras_v4(ms: list[dict], pid) -> dict[str, pa.Table]:
    """Ability casts per player-match and damage events per round, from v4.

    The same struct-field and list-flatten reads as `parse_matches`, with its
    helpers; `pid` is its pseudonym function.
    """
    col, explode = lf._col, lf._explode
    empty_casts = pa.table({k: pa.array([], t) for k, t in (
        ("match_id", pa.string()), ("player", pa.string()),
        ("grenade", pa.float64()), ("ability1", pa.float64()),
        ("ability2", pa.float64()), ("ultimate", pa.float64()))})
    if not ms:
        return {"casts": empty_casts, "damage": None}
    M = pa.array(ms)
    mids = col(col(M, "metadata"), "match_id").cast(pa.string())
    pl, ppar = explode(col(M, "players"))
    casts = pa.table({
        "match_id": pc.take(mids, ppar), "player": pid(col(pl, "puuid")),
        **{k: col(pl, "ability_casts", k).cast(pa.float64())
           for k in ("grenade", "ability1", "ability2", "ultimate")}})
    rd, rpar = explode(col(M, "rounds"))
    st, sp = explode(col(rd, "stats"))
    de, dp = explode(col(st, "damage_events"))
    if len(de) == 0:
        return {"casts": casts, "damage": None}
    s_of = dp
    damage = pa.table({
        "match_id": pc.take(mids, pc.take(rpar, pc.take(sp, s_of))),
        "round": pc.take(col(rd, "id"), pc.take(sp, s_of)).cast(pa.int64()),
        "player": pc.take(pid(col(st, "player", "puuid")), s_of),
        "team": pc.take(col(st, "player", "team").cast(pa.string()), s_of),
        "receiver_team": col(de, "player", "team").cast(pa.string()),
        "damage": col(de, "damage").cast(pa.float64()),
        "headshots": col(de, "headshots").cast(pa.float64()),
        "bodyshots": col(de, "bodyshots").cast(pa.float64()),
        "legshots": col(de, "legshots").cast(pa.float64())})
    return {"casts": casts, "damage": damage}


def _concat(ts: list[pa.Table | None]) -> pa.Table | None:
    ts = [t for t in ts if t is not None and t.num_rows]
    if not ts:
        return None
    return pa.concat_tables(ts, promote_options="permissive")


def build_tables(ladder_ms: list[dict], riot_ms: list[dict],
                 riot_extra: list[dict], salt: bytes, owners: set[str],
                 since: str | None = None) -> dict[str, pa.Table]:
    """The parsed tables for both sources plus `casts` and `damage`.

    Each source parses through `ladder_fetch.parse_matches` on its own (one
    nested type per batch), with one salt, so pseudonyms agree; `source` is
    added to `matches`.
    """
    pid, _ = lf._pseudo(salt, owners)
    parts = []
    for name, ms, ex, cap in (("ladder", ladder_ms, ladder_ms, set()),
                              ("riot", riot_ms, riot_extra,
                               {m["metadata"]["match_id"] for m in riot_ms})):
        if not ms:
            continue
        t = lf.parse_matches(ms, salt, owners, cap, since)
        t["matches"] = t["matches"].append_column(
            "source", pa.array([name] * t["matches"].num_rows, pa.string()))
        t.update(extras_v4(ex, pid))
        parts.append(t)
    names = ("matches", "players", "rounds", "economy", "kills", "positions",
             "casts", "damage")
    return {k: _concat([p.get(k) for p in parts]) for k in names}


def load(store: Path) -> dict:
    """Both sources from the store, exclusions applied, accounts labelled."""
    store = Path(store)
    out = lf.out_dir(store)
    state = lf.State.load(out / "state.json")
    salt = lf.salt_of(out)
    accounts = lf.owner_accounts(store)            # label -> puuid
    recs = rgt.riot_records(store)
    ident = rgt.identify_player(recs, store)
    owners = set(accounts.values()) | {v["subject"] for v in ident.values()
                                       if v.get("subject")}
    ref = rgt.Reference(store / "external" / "valorant-api", fetch=False)
    ladder_ms = lf.stored_matches(out, state)
    comp = {s: d for s, d in recs.items()
            if d["match"]["matchInfo"].get("queueID") == "competitive"}
    riot_ms, riot_extra = [], []
    for d in comp.values():
        v = lf.riot_to_v4(d, ref)
        mp = ref.maps.get(d["match"]["matchInfo"]["mapId"]) or {}
        v["metadata"]["map"]["name"] = mp.get("displayName")
        riot_ms.append(v)
        riot_extra.append(riot_extras_v4(d))
    have = {m["metadata"]["match_id"] for m in ladder_ms}
    dup = [m for m in riot_ms if m["metadata"]["match_id"] in have]
    riot_extra = [e for e, m in zip(riot_extra, riot_ms)
                  if m["metadata"]["match_id"] not in have]
    riot_ms = [m for m in riot_ms if m["metadata"]["match_id"] not in have]
    kept = kept_replay_matches(store)
    present = {m["metadata"]["match_id"] for m in ladder_ms + riot_ms}
    ex_present = kept & present
    ladder_ms = [m for m in ladder_ms if m["metadata"]["match_id"] not in kept]
    riot_extra = [e for e, m in zip(riot_extra, riot_ms)
                  if m["metadata"]["match_id"] not in kept]
    riot_ms = [m for m in riot_ms if m["metadata"]["match_id"] not in kept]
    T = build_tables(ladder_ms, riot_ms, riot_extra, salt, owners, state.since)
    pid, _ = lf._pseudo(salt, owners)
    labels = dict(zip(pid(pa.array(list(accounts.values()), pa.string()))
                      .to_pylist(), accounts.keys()))
    return {"tables": T, "labels": labels, "since": state.since,
            "counts": {"ladder_matches": len(ladder_ms),
                       "riot_competitive": len(comp),
                       "riot_unrated_skipped": len(recs) - len(comp),
                       "riot_matches_used": len(riot_ms),
                       "riot_already_in_ladder": len(dup),
                       "kept_replays_uncaptured": len(kept),
                       "kept_replays_excluded_present": len(ex_present),
                       "accounts": len(accounts)},
            "riot_roles": riot_roles(comp)}


def riot_roles(recs: dict) -> pa.Table:
    """Riot's attacking team per round, the check on the side rule."""
    mid, rnd, att = [], [], []
    for d in recs.values():
        m = d["match"]
        for r in m["roundResults"]:
            w = r.get("winningTeam")
            teams = {p["teamId"] for p in m["players"]}
            other = next((t for t in teams if t != w), None)
            mid.append(m["matchInfo"]["matchId"])
            rnd.append(r["roundNum"])
            att.append(w if r.get("winningTeamRole") == "Attacker" else other)
    return pa.table({"match_id": pa.array(mid, pa.string()),
                     "round": pa.array(rnd, pa.int64()),
                     "att_team": pa.array(att, pa.string())})


# ----------------------------------------------------------------- features

def connect(T: dict[str, pa.Table]) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("SET threads=1")
    for k, t in T.items():
        if t is not None:
            c.register(f"t_{k}", t)
    if T.get("damage") is None:
        c.execute("create view t_damage as select null::varchar match_id, "
                  "null::bigint round, null::varchar player, null::varchar team,"
                  " null::varchar receiver_team, 0.0 damage, 0.0 headshots, "
                  "0.0 bodyshots, 0.0 legshots where false")
    return c


def side_sql(round_col: str = "round") -> str:
    """The attacking team of a round by the side rule (checked, not owned)."""
    r = round_col
    other = "Blue" if FIRST_ATTACKER == "Red" else "Red"
    return (f"case when {r} < {HALF_ROUNDS} or ({r} >= {REGULATION_ROUNDS} "
            f"and ({r} - {REGULATION_ROUNDS}) % 2 = 0) then '{FIRST_ATTACKER}' "
            f"else '{other}' end")


def features(c: duckdb.DuckDBPyConnection, trade_ms: float = TRADE_WINDOW_MS,
             sens_ms=TRADE_SENSITIVITY_MS) -> None:
    """Per player-round feature table `pr` and per death table `dd`."""
    w = float(trade_ms)
    c.execute(f"""
    create or replace table rnd as
    select match_id, round, winning_team, plant_ms, defuse_ms, planter,
           defuser, {side_sql()} as att_team
    from t_rounds where coalesce(result, '') <> 'Surrendered'""")
    c.execute("""
    create or replace table k as
    select k.*, (k.killer is not null and k.killer_team <> k.victim_team) xk,
           r.plant_ms
    from t_kills k join rnd r using (match_id, round)""")
    # first cross-team kill of each round
    c.execute("""
    create or replace table fk as
    select match_id, round, killer, victim from (
      select *, row_number() over (partition by match_id, round
        order by time_in_round_ms, kill) rn from k where xk) where rn = 1""")
    # trades: the killer dies to the victim's team within the window
    tw = [w, *[float(x) for x in sens_ms]]
    cols = ", ".join(f"max((t.time_in_round_ms - d.time_in_round_ms <= {x})"
                     f"::int) tr_{i}" for i, x in enumerate(tw))
    c.execute(f"""
    create or replace table trd as
    select d.match_id, d.kill, {cols},
      arg_min(t.killer, t.time_in_round_ms) filter
        (where t.time_in_round_ms - d.time_in_round_ms <= {w}) trader
    from k d join k t on t.match_id = d.match_id and t.round = d.round
      and t.victim = d.killer and t.killer_team = d.victim_team
      and t.time_in_round_ms >= d.time_in_round_ms and t.kill <> d.kill
    where d.xk group by d.match_id, d.kill""")
    # nearest listed teammate at each death to an enemy
    c.execute("""
    create or replace table dd as
    select k.match_id, k.round, k.kill, k.victim player, k.victim_team team,
      k.time_in_round_ms t, k.plant_ms,
      min(sqrt((p.x - k.victim_x) ^ 2 + (p.y - k.victim_y) ^ 2)) near_cm,
      count(p.player) mates_listed,
      coalesce(any_value(tr.tr_0), 0) traded,
      coalesce(any_value(tr.tr_1), 0) traded_lo,
      coalesce(any_value(tr.tr_2), 0) traded_hi
    from k left join t_positions p on p.match_id = k.match_id
      and p.event = 'kill' and p.kill = k.kill and p.team = k.victim_team
      and p.player <> k.victim
    left join trd tr on tr.match_id = k.match_id and tr.kill = k.kill
    where k.xk
    group by k.match_id, k.round, k.kill, k.victim, k.victim_team,
      k.time_in_round_ms, k.plant_ms""")
    c.execute(f"""
    create or replace table pr as
    with e as (
      select e.match_id, e.round, e.player, e.team,
        coalesce(e.loadout_value, 0)::double lv, r.att_team, r.winning_team,
        r.plant_ms, r.planter, r.defuser
      from t_economy e join rnd r using (match_id, round)),
    tm as (
      select match_id, round, team, sum(lv) s, count(*) n
      from e group by 1, 2, 3),
    kc as (
      select match_id, round, killer player, count(*) kills,
        count(*) filter (where plant_ms is not null
                         and time_in_round_ms > plant_ms) pp_kills
      from k where xk group by 1, 2, 3),
    dc as (
      select match_id, round, victim player, count(*) deaths,
        min(time_in_round_ms) first_death_t
      from k group by 1, 2, 3),
    ddc as (
      select match_id, round, player, count(*) deaths_x, sum(traded) traded,
        sum(traded_lo) traded_lo, sum(traded_hi) traded_hi,
        count(*) filter (where mates_listed > 0) dist_n,
        sum(near_cm) filter (where mates_listed > 0) dist_sum,
        count(*) filter (where mates_listed > 0 and traded = 0) dist_u_n,
        sum(near_cm) filter (where mates_listed > 0 and traded = 0) dist_u_sum,
        count(*) filter (where mates_listed > 0 and near_cm > {ISOLATED_CM})
          isolated
      from dd group by 1, 2, 3),
    ac as (
      select match_id, round, a player, count(*) assists from (
        select match_id, round, unnest(assistants) a from k where xk)
      group by 1, 2, 3),
    tc as (
      select d.match_id, d.round, tr.trader player, count(*) trades
      from trd tr join k d on d.match_id = tr.match_id and d.kill = tr.kill
      where tr.trader is not null group by 1, 2, 3),
    f1 as (select match_id, round, killer player, 1 fk from fk),
    f2 as (select match_id, round, victim player, 1 fd from fk),
    dm as (
      select match_id, round, player, sum(damage) dmg, sum(headshots) hs,
        sum(bodyshots) bs, sum(legshots) ls
      from t_damage where receiver_team <> team group by 1, 2, 3)
    select e.match_id, e.round, e.player, e.team,
      case when e.team = e.att_team then 'attack' else 'defense' end side,
      (e.team = e.winning_team)::int won, 1 rounds, e.lv,
      tm.s / tm.n team_mean_lv,
      case when tm.n > 1 then (tm.s - e.lv) / (tm.n - 1) end mates_mean_lv,
      case when e.round in (0, {HALF_ROUNDS}) then 'pistol'
           when tm.s / tm.n < {ECO_MAX} then 'eco'
           when tm.s / tm.n < {FULL_MIN} then 'force'
           else 'full' end buy,
      coalesce(kc.kills, 0) kills, coalesce(dc.deaths, 0) deaths,
      coalesce(ac.assists, 0) assists,
      coalesce(ddc.deaths_x, 0) deaths_x, coalesce(ddc.traded, 0) traded,
      coalesce(ddc.traded_lo, 0) traded_lo,
      coalesce(ddc.traded_hi, 0) traded_hi,
      coalesce(ddc.dist_n, 0) dist_n, coalesce(ddc.dist_sum, 0) dist_sum,
      coalesce(ddc.dist_u_n, 0) dist_u_n,
      coalesce(ddc.dist_u_sum, 0) dist_u_sum,
      coalesce(ddc.isolated, 0) isolated,
      coalesce(tc.trades, 0) trades,
      coalesce(f1.fk, 0) fk, coalesce(f2.fd, 0) fd,
      (e.planter = e.player)::int planted, (e.defuser = e.player)::int defused,
      (e.plant_ms is not null)::int plant_round,
      (e.plant_ms is not null and (dc.first_death_t is null
        or dc.first_death_t > e.plant_ms))::int alive_at_plant,
      (e.plant_ms is not null and dc.first_death_t > e.plant_ms)::int pp_death,
      coalesce(kc.pp_kills, 0) pp_kills,
      coalesce(dm.dmg, 0) dmg, coalesce(dm.hs, 0) hs, coalesce(dm.bs, 0) bs,
      coalesce(dm.ls, 0) ls
    from e join tm using (match_id, round, team)
    left join kc using (match_id, round, player)
    left join dc using (match_id, round, player)
    left join ddc using (match_id, round, player)
    left join ac using (match_id, round, player)
    left join tc using (match_id, round, player)
    left join f1 using (match_id, round, player)
    left join f2 using (match_id, round, player)
    left join dm using (match_id, round, player)""")
    c.execute("""
    alter table pr add column kast int;
    update pr set kast = (kills > 0 or assists > 0 or deaths = 0
                          or traded > 0)::int;
    alter table pr add column mk2 int; alter table pr add column mk3 int;
    update pr set mk2 = (kills >= 2)::int, mk3 = (kills >= 3)::int;""")


def clutches(c: duckdb.DuckDBPyConnection) -> pa.Table:
    """1vX situations per player-round from `winprob_reference.simulate`.

    A player is in a clutch at the first kill state, before the decision,
    where they are their team's only living player and an enemy lives; X is
    the enemies alive then. The simulation's alive sets include revives.
    """
    team_rows = c.execute("""select match_id, player, team from t_players
                             where player is not null""").fetchall()
    team_of: dict[str, dict] = defaultdict(dict)
    for m, p, t in team_rows:
        team_of[m][p] = t
    rows = c.execute("""
    select k.match_id, k.round, k.kill, k.time_in_round_ms, k.victim,
      list(p.player) filter (where p.player is not null) listed,
      any_value(r.plant_ms), any_value(r.defuse_ms), any_value(r.att_team)
    from k join rnd r using (match_id, round)
    left join t_positions p on p.match_id = k.match_id and p.event = 'kill'
      and p.kill = k.kill
    group by k.match_id, k.round, k.kill, k.time_in_round_ms, k.victim
    order by k.match_id, k.round, k.time_in_round_ms, k.kill""").fetchall()
    by_round: dict[tuple, list] = defaultdict(list)
    meta = {}
    for m, r, kill, t, v, listed, plant, defuse, att in rows:
        by_round[(m, r)].append({"roundTime": t, "victim": v,
                                 "playerLocations": [{"subject": s}
                                                     for s in listed or ()]})
        meta[(m, r)] = (plant, defuse, att)
    out = {"match_id": [], "round": [], "player": [], "x": []}
    for (m, r), kills in by_round.items():   # one simulation per round
        plant, defuse, att = meta[(m, r)]
        tof = team_of.get(m) or {}
        if not tof:
            continue
        _dec, _p, kst, _n = wr.simulate(kills, plant, defuse, att, tof)
        seen = set()
        for s in kst:
            if s["deciding"]:
                break
            for team in set(tof.values()) - seen:
                mine = [p for p in s["alive"] if tof.get(p) == team]
                foes = sum(1 for p in s["alive"] if tof.get(p) != team)
                if len(mine) == 1 and foes >= 1:
                    seen.add(team)
                    out["match_id"].append(m)
                    out["round"].append(r)
                    out["player"].append(mine[0])
                    out["x"].append(foes)
    return pa.table({"match_id": pa.array(out["match_id"], pa.string()),
                     "round": pa.array(out["round"], pa.int64()),
                     "player": pa.array(out["player"], pa.string()),
                     "x": pa.array(out["x"], pa.int64())})


def player_match(c: duckdb.DuckDBPyConnection, labels: dict[str, str]
                 ) -> None:
    """`pm`: per player-match context, casts and the round sums by side."""
    c.register("t_clutch", clutches(c))
    c.register("t_labels", pa.table({
        "player": pa.array(list(labels), pa.string()),
        "account": pa.array(list(labels.values()), pa.string())}))
    c.execute("""
    alter table pr add column clutch int; alter table pr add column clutch_x int;
    update pr set clutch = 0, clutch_x = 0;
    update pr set clutch = 1, clutch_x = cl.x from t_clutch cl
      where cl.match_id = pr.match_id and cl.round = pr.round
        and cl.player = pr.player;
    alter table pr add column clutch_won int;
    update pr set clutch_won = clutch * won;""")
    c.execute("""
    create or replace table pm as
    select pl.match_id, pl.player, pl.is_owner::int is_owner, pl.team,
      coalesce(pl.agent, 'unknown') agent,
      coalesce(lb.account, '-') account, coalesce(m.map, 'unknown') "map",
      coalesce(m.season, 'unknown') season,
      substr(m.started_at, 1, 7) as "month", coalesce(m.stratum, 'unknown') stratum,
      m.source, m.started_at,
      ca.grenade, ca.ability1, ca.ability2, ca.ultimate,
      (ca.grenade is not null)::int has_casts
    from t_players pl join t_matches m using (match_id)
    left join t_labels lb using (player)
    left join t_casts ca using (match_id, player)
    where pl.player is not null""")


# ----------------------------------------------------------------- metrics

#: name, family, numerator, denominator, level ('round' sums pr by side;
#: 'match' reads pm casts over pr rounds), text, rankable.
METRICS = [
    ("kills_per_round", "fragging", "kills", "rounds", "round", "Kills per round", True),
    ("deaths_per_round", "fragging", "deaths", "rounds", "round", "Deaths per round", True),
    ("kd", "fragging", "kills", "deaths", "round", "Kills per death", True),
    ("adr", "fragging", "dmg", "rounds", "round", "Damage to enemies per round", True),
    ("hs_share", "fragging", "hs", "hs + bs + ls", "round", "Headshot share of hits", True),
    ("kast", "fragging", "kast", "rounds", "round", "KAST: rounds with a kill, assist, survival or traded death", True),
    ("mk2_rate", "multikill", "mk2", "rounds", "round", "Rounds with 2+ kills", True),
    ("mk3_rate", "multikill", "mk3", "rounds", "round", "Rounds with 3+ kills", True),
    ("opening_involvement", "opening", "fk + fd", "rounds", "round", "Rounds in the opening duel (first kill or first death)", True),
    ("opening_win", "opening", "fk", "fk + fd", "round", "Opening duels won", True),
    ("first_kill_rate", "opening", "fk", "rounds", "round", "First kills per round", True),
    ("first_death_rate", "opening", "fd", "rounds", "round", "First deaths per round", True),
    ("traded_share", "trade", "traded", "deaths_x", "round", "Deaths to enemies traded within the window", True),
    ("traded_share_3s", "trade", "traded_lo", "deaths_x", "round", "Deaths traded within 3 s (sensitivity)", False),
    ("traded_share_7s", "trade", "traded_hi", "deaths_x", "round", "Deaths traded within 7 s (sensitivity)", False),
    ("untraded_deaths_per_round", "trade", "deaths_x - traded", "rounds", "round", "Untraded deaths per round", True),
    ("trades_per_round", "trade", "trades", "rounds", "round", "Trades made per round", True),
    ("near_mate_m", "spacing", "dist_sum / 100", "dist_n", "round", "Distance to the nearest listed teammate at death (m)", True),
    ("near_mate_m_untraded", "spacing", "dist_u_sum / 100", "dist_u_n", "round", "Distance to the nearest teammate at an untraded death (m)", True),
    ("isolated_death_share", "spacing", "isolated", "dist_n", "round", f"Deaths with no teammate within {ISOLATED_CM / 100:.0f} m", True),
    ("clutch_rate", "clutch", "clutch", "rounds", "round", "Rounds in a 1vX", True),
    ("clutch_win", "clutch", "clutch_won", "clutch", "round", "1vX rounds won", True),
    ("clutch_win_1v1", "clutch", "clutch_won * (clutch_x = 1)::int", "clutch * (clutch_x = 1)::int", "round", "1v1 rounds won", True),
    ("clutch_win_1v2plus", "clutch", "clutch_won * (clutch_x >= 2)::int", "clutch * (clutch_x >= 2)::int", "round", "1v2+ rounds won", True),
    ("plants_per_attack_round", "postplant", "planted * (side = 'attack')::int", "(side = 'attack')::int", "round", "Plants per attack round", True),
    ("defuses_per_defense_plant", "postplant", "defused * (side = 'defense')::int", "plant_round * (side = 'defense')::int", "round", "Defuses per defense round with a plant", True),
    ("pp_death_attack", "postplant", "pp_death * (side = 'attack')::int", "alive_at_plant * (side = 'attack')::int", "round", "Deaths after the plant, attacking, per round alive at the plant", True),
    ("pp_death_defense", "postplant", "pp_death * (side = 'defense')::int", "alive_at_plant * (side = 'defense')::int", "round", "Deaths after the plant (retake), per round alive at the plant", True),
    ("pp_kills_attack", "postplant", "pp_kills * (side = 'attack')::int", "alive_at_plant * (side = 'attack')::int", "round", "Kills after the plant, attacking, per round alive at the plant", True),
    ("pp_kills_defense", "postplant", "pp_kills * (side = 'defense')::int", "alive_at_plant * (side = 'defense')::int", "round", "Kills after the plant (retake), per round alive at the plant", True),
    ("buy_vs_mates", "economy", "(lv - mates_mean_lv) * (buy <> 'pistol')::int", "(buy <> 'pistol' and mates_mean_lv is not null)::int", "round", "Own loadout minus teammates' mean, non-pistol rounds (credits)", True),
    ("offsync_buy", "economy", "(lv >= %F and mates_mean_lv < %E and buy <> 'pistol')::int", "(buy <> 'pistol')::int", "round", "Full buy while teammates save (share of non-pistol rounds)", True),
    ("offsync_save", "economy", "(lv < %E and mates_mean_lv >= %F and buy <> 'pistol')::int", "(buy <> 'pistol')::int", "round", "Saving while teammates full-buy (share of non-pistol rounds)", True),
    ("eco_win", "economy", "won * (buy = 'eco')::int", "(buy = 'eco')::int", "round", "Eco rounds won (team mean loadout < eco band)", True),
    ("force_win", "economy", "won * (buy = 'force')::int", "(buy = 'force')::int", "round", "Force rounds won", True),
    ("full_win", "economy", "won * (buy = 'full')::int", "(buy = 'full')::int", "round", "Full-buy rounds won", True),
    ("pistol_win", "economy", "won * (buy = 'pistol')::int", "(buy = 'pistol')::int", "round", "Pistol rounds won", True),
    ("death_rate_high_loadout", "economy", "(deaths > 0)::int * (lv >= %F)::int", "(lv >= %F)::int", "round", "Rounds died in, of rounds with own loadout in the full band", True),
    ("round_win", "outcome", "won", "rounds", "round", "Rounds won", False),
]
CAST_SLOTS = ("grenade", "ability1", "ability2", "ultimate")
#: Casts depend on the agent: these rank on the agent-matched comparison only.
MATCHED_ONLY = "utility"
for _s in CAST_SLOTS:
    METRICS.append((f"casts_{_s}_per_round", "utility", _s, "rounds", "cast",
                    f"{_s} casts per round", True))
METRICS.append(("casts_per_round", "utility", "casts", "rounds", "cast",
                "All ability casts per round", True))
METRICS.append(("assists_per_cast", "utility", "assists", "casts", "cast",
                "Assists per ability cast (ratio of totals)", True))
METRICS.append(("kills_assists_per_cast", "utility", "kills + assists",
                "casts", "cast", "Kills plus assists per cast (ratio of "
                "totals)", True))

HEADLINE = ("kd", "adr", "kast", "hs_share", "opening_involvement",
            "opening_win", "traded_share", "untraded_deaths_per_round",
            "near_mate_m_untraded", "isolated_death_share", "first_death_rate",
            "casts_per_round", "clutch_win", "round_win")

HYPOTHESES = {
    "kills_per_round": ("gets more kills per round than the lobby", "gets fewer kills per round than the lobby"),
    "deaths_per_round": ("dies more often per round than the lobby: test whether the deaths come from engagements taken without a man advantage", "survives more rounds than the lobby: test whether survival costs round impact"),
    "kd": ("wins the duel trade-off more than the lobby", "loses more duels than the lobby wins: test whether duels are taken at a disadvantage"),
    "adr": ("deals more damage per round than the lobby", "deals less damage per round than the lobby"),
    "hs_share": ("lands a larger share of hits as headshots than the lobby", "lands a smaller share of hits as headshots than the lobby: crosshair placement is a candidate"),
    "kast": ("contributes in more rounds than the lobby", "has more rounds with no kill, assist, survival or trade than the lobby: test which component is missing"),
    "mk2_rate": ("converts openings into multi-kills more than the lobby", "converts fewer rounds into multi-kills"),
    "mk3_rate": ("converts openings into 3+ kill rounds more than the lobby", "converts fewer rounds into 3+ kills"),
    "opening_involvement": ("takes the opening duel more often than the lobby: test whether the entries are set up with team support", "is in fewer opening duels than the lobby"),
    "opening_win": ("wins the opening duel more than the lobby: entries are a strength to schedule", "loses the opening duel more than the lobby: test whether the openings are taken alone, without utility or a trade partner"),
    "first_kill_rate": ("gets the first kill more often", "gets the first kill less often"),
    "first_death_rate": ("dies first more often than the lobby: test whether the position or timing gives away the first man advantage", "dies first less often"),
    "traded_share": ("is traded more often than the lobby: spacing keeps a partner in range", "is traded less often than the lobby: test whether deaths come out of a teammate's trade range (spacing, lurk timing)"),
    "untraded_deaths_per_round": ("dies untraded more per round than the lobby: each is a man advantage given away; test spacing and lurk timing", "dies untraded less per round"),
    "trades_per_round": ("trades teammates more than the lobby", "trades teammates less than the lobby: test whether the player is in trade range of the entry"),
    "near_mate_m": ("dies farther from the nearest teammate than the lobby: a spacing or lurk hypothesis", "dies closer to a teammate than the lobby"),
    "near_mate_m_untraded": ("untraded deaths happen farther from a teammate than the lobby's: the lurk or rotation leaves no trade", "untraded deaths happen close to a teammate: the trade partner did not convert"),
    "isolated_death_share": ("dies with no teammate nearby more often than the lobby: a spacing, rotation or lurk-timing hypothesis", "dies isolated less often than the lobby"),
    "clutch_rate": ("ends up last alive more often than the lobby: test whether that is lurk position or late rotation", "is last alive less often"),
    "clutch_win": ("wins 1vX more than the lobby", "wins 1vX less than the lobby: test the decision in the clutch (time, info, spike)"),
    "clutch_win_1v1": ("wins 1v1 more than the lobby", "wins 1v1 less than the lobby"),
    "clutch_win_1v2plus": ("wins 1v2+ more than the lobby", "wins 1v2+ less than the lobby"),
    "plants_per_attack_round": ("carries and plants more than the lobby", "plants less than the lobby"),
    "defuses_per_defense_plant": ("defuses more than the lobby", "defuses less than the lobby"),
    "pp_death_attack": ("dies after the plant more than the lobby: test post-plant positions and the man advantage held", "survives post-plant more than the lobby"),
    "pp_death_defense": ("dies in retakes more than the lobby: test whether retakes are entered without a man advantage or together", "survives retakes more than the lobby"),
    "pp_kills_attack": ("gets more post-plant kills than the lobby", "gets fewer post-plant kills than the lobby"),
    "pp_kills_defense": ("gets more retake kills than the lobby", "gets fewer retake kills than the lobby"),
    "buy_vs_mates": ("buys above the team's mean: test whether the extra loadout is converted or lost", "buys below the team's mean"),
    "offsync_buy": ("full-buys while teammates save more than the lobby: a team-economy coordination hypothesis", "rarely full-buys alone"),
    "offsync_save": ("saves while teammates buy more than the lobby: a team-economy coordination hypothesis", "rarely saves alone"),
    "eco_win": ("wins more eco rounds than the lobby", "wins fewer eco rounds than the lobby"),
    "force_win": ("wins more force rounds than the lobby", "wins fewer force rounds than the lobby: test the force-buy decision"),
    "full_win": ("wins more full-buy rounds than the lobby", "wins fewer full-buy rounds than the lobby"),
    "pistol_win": ("wins more pistol rounds than the lobby", "wins fewer pistol rounds than the lobby"),
    "death_rate_high_loadout": ("dies more when full-bought than the lobby: test whether the loadout is risked in engagements without a man advantage", "keeps the full loadout alive more than the lobby"),
    "casts_per_round": ("casts more utility per round than same-agent peers", "casts less utility per round than same-agent peers: test whether unused utility leaves engagements unprepared (dying earlier also leaves less time to cast)"),
    "casts_grenade_per_round": ("casts the grenade slot more than same-agent peers", "casts the grenade slot less than same-agent peers"),
    "casts_ability1_per_round": ("casts the ability1 slot more than same-agent peers", "casts the ability1 slot less than same-agent peers"),
    "casts_ability2_per_round": ("casts the ability2 slot more than same-agent peers", "casts the ability2 slot less than same-agent peers"),
    "casts_ultimate_per_round": ("casts the ultimate more than same-agent peers", "casts the ultimate less than same-agent peers: test whether ultimates are held past their value"),
    "assists_per_cast": ("earns more assists per cast than same-agent peers", "earns fewer assists per cast than same-agent peers: test whether utility is thrown for a teammate's duel"),
    "kills_assists_per_cast": ("earns more kills and assists per cast than same-agent peers", "earns fewer kills and assists per cast than same-agent peers"),
}


def _expr(s: str) -> str:
    return s.replace("%F", repr(FULL_MIN)).replace("%E", repr(ECO_MAX))


def sums(c: duckdb.DuckDBPyConnection) -> dict[str, np.ndarray]:
    """Per player-match-side sums of every metric's numerator and
    denominator, with the context columns; arrays aligned by row."""
    rm = [(n, num, den) for n, _f, num, den, lvl, _t, _r in METRICS
          if lvl == "round"]
    sel = ", ".join(f"sum({_expr(num)})::double n_{n}, "
                    f"sum({_expr(den)})::double d_{n}" for n, num, den in rm)
    q = f"""
    with s as (select match_id, player, side, sum(rounds)::double rounds,
                 sum(kills)::double kills, sum(assists)::double assists,
                 {sel} from pr group by 1, 2, 3)
    select s.*, pm.is_owner, pm.agent, pm.account, pm."map", pm.season,
      pm."month", pm.stratum, pm.source, pm.has_casts,
      coalesce(pm.grenade, 0) grenade, coalesce(pm.ability1, 0) ability1,
      coalesce(pm.ability2, 0) ability2, coalesce(pm.ultimate, 0) ultimate
    from s join pm using (match_id, player)
    order by match_id, player, side"""
    a = c.execute(q).fetchnumpy()
    out = {k: (np.asarray(v) if not hasattr(v, "filled") else
               np.asarray(v.filled(np.nan) if v.dtype.kind == "f"
                          else v.filled(None)))
           for k, v in a.items()}
    # casts belong to the match: count them on one side row only
    first = np.ones(len(out["side"]), bool)
    key = np.char.add(out["match_id"].astype(str), out["player"].astype(str))
    first[1:] = key[1:] != key[:-1]
    hc = out["has_casts"].astype(float)
    casts = sum(out[s] for s in CAST_SLOTS)
    for s in CAST_SLOTS:
        out[f"n_casts_{s}_per_round"] = out[s] * first * hc
        out[f"d_casts_{s}_per_round"] = out["rounds"] * hc
    out["n_casts_per_round"] = casts * first * hc
    out["d_casts_per_round"] = out["rounds"] * hc
    out["n_assists_per_cast"] = out["assists"] * hc
    out["d_assists_per_cast"] = casts * first * hc
    out["n_kills_assists_per_cast"] = (out["kills"] + out["assists"]) * hc
    out["d_kills_assists_per_cast"] = casts * first * hc
    return out


def boot_weights(n: int, boot: int, seed: int = SEED) -> np.ndarray:
    """Resampled match counts, (boot, n): each row draws n matches."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n, np.full(n, 1.0 / n), size=boot).astype(float)


def compare(S: dict, name: str, mask: np.ndarray, peer_mask=None,
            boot: int = BOOT, W_cache: dict | None = None) -> dict:
    """The player's ratio against the pooled peers', match-bootstrapped.

    `mask` selects rows (a group); `peer_mask` narrows the peers further
    (the same agent). Matches are the resampling unit; both ratios use the
    same draws, so the difference's interval keeps their correlation.
    """
    num, den = S[f"n_{name}"], S[f"d_{name}"]
    num = np.nan_to_num(num.astype(float))
    den = np.nan_to_num(den.astype(float))
    own = S["is_owner"].astype(bool)
    om = mask & own
    pmk = mask & ~own if peer_mask is None else mask & ~own & peer_mask
    keep = (om | pmk) & (den > 0)
    mids, inv = np.unique(S["match_id"][keep], return_inverse=True)
    n = len(mids)
    res = {"metric": name, "matches": int(n)}
    if n == 0:
        return res | {"owner": None, "peers": None, "owner_n": 0.0,
                      "peers_n": 0.0}
    o, p = om[keep], pmk[keep]
    on = np.bincount(inv, num[keep] * o, n)
    od = np.bincount(inv, den[keep] * o, n)
    pn = np.bincount(inv, num[keep] * p, n)
    pd = np.bincount(inv, den[keep] * p, n)
    res.update(owner_n=float(od.sum()), peers_n=float(pd.sum()),
               owner_matches=int((od > 0).sum()))
    res["owner"] = float(on.sum() / od.sum()) if od.sum() > 0 else None
    res["peers"] = float(pn.sum() / pd.sum()) if pd.sum() > 0 else None
    if res["owner"] is None or res["peers"] is None:
        return res
    key = (n, boot)
    W = None if W_cache is None else W_cache.get(key)
    if W is None:
        W = boot_weights(n, boot)
        if W_cache is not None:
            W_cache[key] = W
    with np.errstate(invalid="ignore", divide="ignore"):
        ob = (W @ on) / (W @ od)
        pb = (W @ pn) / (W @ pd)
    d = ob - pb
    ok = np.isfinite(d)
    if ok.sum() < boot // 2:
        return res | {"ci_owner": None, "ci_diff": None}
    res["diff"] = res["owner"] - res["peers"]
    res["ci_owner"] = [float(np.percentile(ob[ok], 2.5)),
                       float(np.percentile(ob[ok], 97.5))]
    res["ci_peers"] = [float(np.nanpercentile(pb[ok], 2.5)),
                       float(np.nanpercentile(pb[ok], 97.5))]
    res["ci_diff"] = [float(np.percentile(d[ok], 2.5)),
                      float(np.percentile(d[ok], 97.5))]
    res["boot_ok"] = int(ok.sum())
    return res


def compare_agent_matched(S: dict, name: str, mask: np.ndarray,
                          boot: int = BOOT, W_cache: dict | None = None
                          ) -> dict:
    """The player's ratio against peers on the same agents, standardised.

    For each agent the player played, the peers' ratio on that agent is
    weighted by the player's denominator on it; the sum is what the lobby
    would score with the player's agent mix. Same match resamples as
    `compare`.
    """
    num = np.nan_to_num(S[f"n_{name}"].astype(float))
    den = np.nan_to_num(S[f"d_{name}"].astype(float))
    own = S["is_owner"].astype(bool)
    agent = S["agent"].astype(str)
    mine = sorted(set(agent[mask & own & (den > 0)]))
    keep = mask & (den > 0) & np.isin(agent, mine)
    mids, inv = np.unique(S["match_id"][keep], return_inverse=True)
    n = len(mids)
    if n == 0 or not mine:
        return {}
    o = own[keep]
    a_idx = np.searchsorted(mine, agent[keep])
    A = len(mine)
    cell = inv * A + a_idx

    def grid(w):
        return np.bincount(cell, w, n * A).reshape(n, A)
    on, od = grid(num[keep] * o), grid(den[keep] * o)
    pn, pd = grid(num[keep] * ~o), grid(den[keep] * ~o)

    def std(on_, od_, pn_, pd_):
        with np.errstate(invalid="ignore", divide="ignore"):
            pr = np.where(pd_ > 0, pn_ / pd_, np.nan)
        wgt = np.where(np.isfinite(pr), od_, 0.0)
        tot = wgt.sum(-1)
        with np.errstate(invalid="ignore", divide="ignore"):
            owner = (on_ * (wgt > 0)).sum(-1) / tot
            peers = np.nansum(pr * wgt, -1) / tot
        return owner, peers
    o0, p0 = std(on.sum(0), od.sum(0), pn.sum(0), pd.sum(0))
    res = {"owner_matched": float(o0), "peers_matched": float(p0),
           "diff_matched": float(o0 - p0), "agents_matched": A}
    key = (n, boot)
    W = None if W_cache is None else W_cache.get(key)
    if W is None:
        W = boot_weights(n, boot)
        if W_cache is not None:
            W_cache[key] = W
    ob, pb = std(W @ on, W @ od, W @ pn, W @ pd)
    d = ob - pb
    ok = np.isfinite(d)
    if ok.sum() >= boot // 2:
        res["ci_diff_matched"] = [float(np.percentile(d[ok], 2.5)),
                                  float(np.percentile(d[ok], 97.5))]
    return res


def low_n(r: dict) -> bool:
    return (r.get("owner_n") or 0.0) < MIN_EVENTS


def per_match(S: dict, names) -> list[dict]:
    """The player's per-match counts and values for `names` (store only)."""
    own = S["is_owner"].astype(bool)
    mids = np.unique(S["match_id"][own])
    out = []
    for m in mids:
        sel = own & (S["match_id"] == m)
        row = {"match_id": str(m),
               "map": str(S["map"][sel][0]), "agent": str(S["agent"][sel][0]),
               "account": str(S["account"][sel][0]),
               "month": str(S["month"][sel][0]),
               "season": str(S["season"][sel][0]),
               "stratum": str(S["stratum"][sel][0]),
               "source": str(S["source"][sel][0]),
               "rounds": float(S["rounds"][sel].sum())}
        for nme in names:
            num = float(np.nansum(S[f"n_{nme}"][sel]))
            den = float(np.nansum(S[f"d_{nme}"][sel]))
            row[nme] = num / den if den > 0 else None
        out.append(row)
    return out


GROUPS = ("side", "map", "agent", "account", "season", "month", "stratum",
          "source")
TREND_GROUPS = ("season", "month", "stratum", "account")
TREND_METRICS = ("kd", "opening_involvement", "traded_share",
                 "isolated_death_share", "casts_per_round")


def profile(S: dict, boot: int = BOOT) -> dict:
    """Pooled comparisons for every metric and grouped ones for the
    headline metrics; utility also against same-agent peers."""
    W: dict = {}
    allrows = np.ones(len(S["match_id"]), bool)
    pooled = {}
    for n, fam, _num, _den, _lvl, text, rank in METRICS:
        r = compare(S, n, allrows, boot=boot, W_cache=W)
        r |= compare_agent_matched(S, n, allrows, boot=boot, W_cache=W)
        pooled[n] = r | {"family": fam, "text": text, "rankable": rank,
                         "low_n": low_n(r)}
    own = S["is_owner"].astype(bool)
    grouped = {}
    for g in GROUPS:
        vals = sorted(set(S[g][own].astype(str)))
        if g == "season":   # in time order: by each season's first month
            first = {v: min(S["month"][own & (S[g].astype(str) == v)]
                            .astype(str)) for v in vals}
            vals = sorted(vals, key=lambda v: (v == "unknown", first[v]))
        grouped[g] = {}
        for v in vals:
            # for `agent` the peers are those on the same agent too
            gm = S[g].astype(str) == v
            grouped[g][v] = {}
            extra = (("casts_per_round", "assists_per_cast")
                     + tuple(f"casts_{s}_per_round" for s in CAST_SLOTS)
                     if g == "agent" else ())
            for n in HEADLINE + extra:
                r = compare(S, n, gm, boot=boot, W_cache=W)
                grouped[g][v][n] = r | {"low_n": low_n(r)}
    return {"pooled": pooled, "grouped": grouped}


def _z(diff, ci):
    """Distance from zero in half-interval units, 0 if the interval holds 0."""
    if diff is None or not ci or ci[0] <= 0 <= ci[1]:
        return 0.0
    half = (ci[1] - ci[0]) / 2.0
    return abs(diff) / half if half > 0 else 0.0


def strongest(pooled: dict, k: int = 3) -> list[dict]:
    """The k pooled differences furthest from zero in interval units, at
    most one per family, among rankable metrics with enough events.

    A signal must hold twice, in the same direction: against every peer and
    against peers on the player's agents (`compare_agent_matched`); its score
    is the smaller of the two. Utility, which the agent decides, ranks on
    the agent-matched comparison alone.
    """
    cand = []
    for n, r in pooled.items():
        if not r.get("rankable") or r.get("low_n"):
            continue
        zm = _z(r.get("diff_matched"), r.get("ci_diff_matched"))
        if r.get("family") == MATCHED_ONLY:
            z, d = zm, r.get("diff_matched")
        else:
            zr = _z(r.get("diff"), r.get("ci_diff"))
            same = (r.get("diff") or 0) * (r.get("diff_matched") or 0) > 0
            z, d = (min(zr, zm) if same else 0.0), r.get("diff")
        if z > 0:
            cand.append((z, n, d))
    cand.sort(reverse=True)
    out, fams = [], set()
    for z, n, d in cand:
        if pooled[n]["family"] in fams:
            continue
        fams.add(pooled[n]["family"])
        hi, lo = HYPOTHESES.get(n, ("scores higher than the lobby",
                                    "scores lower than the lobby"))
        out.append({"metric": n, "z_like": z, "family": pooled[n]["family"],
                    "hypothesis": hi if d > 0 else lo})
        if len(out) == k:
            break
    return out


# ----------------------------------------------------------------- checks

def side_check(c: duckdb.DuckDBPyConnection, roles: pa.Table | None) -> dict:
    """The side rule against Riot's roles and against every planter."""
    out = {}
    if roles is not None and roles.num_rows:
        c.register("t_roles", roles)
        n, ok = c.execute(f"""select count(*), sum((att_team = {side_sql()})
            ::int) from t_roles""").fetchone()
        out["riot_rounds"], out["riot_agree"] = int(n), int(ok or 0)
    n, ok = c.execute("""
      select count(*), sum((p.team = r.att_team)::int) from rnd r
      join t_players p on p.match_id = r.match_id and p.player = r.planter
      where r.planter is not null""").fetchone()
    out["plant_rounds"], out["planter_on_attack"] = int(n), int(ok or 0)
    return out


def data_coverage(c: duckdb.DuckDBPyConnection) -> dict:
    q = lambda s: c.execute(s).fetchone()  # noqa: E731
    out = {}
    out["matches"], out["owner_matches"] = q(
        """select count(distinct match_id),
           count(distinct match_id) filter (where is_owner) from t_players""")
    out["matches_without_owner"] = q(
        """select count(*) from (select match_id from t_players group by 1
           having not bool_or(is_owner))""")[0]
    out["owner_rounds"] = q("""select count(*) from pr join pm
        using (match_id, player) where pm.is_owner = 1""")[0]
    out["deaths_to_enemies"], out["deaths_with_mate_listed"] = q(
        "select count(*), count(*) filter (where mates_listed > 0) from dd")
    out["matches_with_casts"] = q(
        "select count(distinct match_id) from pm where has_casts = 1")[0]
    out["matches_with_damage"] = q(
        "select count(distinct match_id) from t_damage")[0]
    # the derived totals against the records' own per-player totals
    rec = c.execute("""
      with d as (select match_id, player, sum(kills) k, sum(deaths) dth,
                   sum(assists) a from pr group by 1, 2)
      select p.is_owner, sum(d.k), sum(p.kills), sum(d.dth), sum(p.deaths),
        sum(d.a), sum(p.assists)
      from d join t_players p using (match_id, player) group by 1""").fetchall()
    for own, k, rk, de, rde, a, ra in rec:
        who = "player" if own else "peers"
        out[f"{who}_kills_derived"], out[f"{who}_kills_recorded"] = k, rk
        out[f"{who}_deaths_derived"], out[f"{who}_deaths_recorded"] = de, rde
        out[f"{who}_assists_derived"], out[f"{who}_assists_recorded"] = a, ra
    return {k: int(v or 0) for k, v in out.items()}


# ----------------------------------------------------------------- report

def _num_text(x, nd=3):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _ci(ci):
    return f"[{_num_text(ci[0])}, {_num_text(ci[1])}]" if ci else "-"


def _table_row(n, r):
    flag = "LOW n" if r.get("low_n") else ""
    return (f"| {n} | {_num_text(r.get('owner'))} | {_ci(r.get('ci_owner'))} "
            f"| {_num_text(r.get('peers'))} | {_num_text(r.get('diff'))} "
            f"| {_ci(r.get('ci_diff'))} | {_num_text(r.get('peers_matched'))} "
            f"| {_num_text(r.get('diff_matched'))} "
            f"| {_ci(r.get('ci_diff_matched'))} "
            f"| {r.get('owner_n', 0):.0f} | {r.get('matches', 0)} | {flag} |")


HDR = ("| metric | player | player 95% | peers | diff | diff 95% "
       "| same-agent peers | diff | diff 95% | player n | matches | flag |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|")


def report_md(R: dict) -> str:
    P, G = R["profile"]["pooled"], R["profile"]["grouped"]
    L = [f"# Player profile ({R['version']})", "",
         f"Written {R['written']}. Private: the player's own statistics. "
         "Peers are every other player in the same matches, pooled.", "",
         "## Data", ""]
    for k, v in R["counts"].items():
        L.append(f"- {k}: {v}")
    for k, v in R["coverage"].items():
        L.append(f"- {k}: {v}")
    sc = R["side_check"]
    L += ["", "## Choices and checks", "",
          f"- Trade window {TRADE_WINDOW_MS / 1000:.0f} s, a choice (no domain "
          "fact records one); 3 s and 7 s are reported beside it.",
          f"- Side rule: {FIRST_ATTACKER} attacks rounds below {HALF_ROUNDS} "
          f"and even overtime rounds. Riot's roles agree on "
          f"{sc.get('riot_agree', '-')} of {sc.get('riot_rounds', '-')} "
          f"captured rounds; the planter is on the rule's attacking team in "
          f"{sc['planter_on_attack']} of {sc['plant_rounds']} plants.",
          f"- Buy bands by the team's mean loadout: eco < {ECO_MAX:.0f}, force "
          f"< {FULL_MIN:.0f}, full otherwise; pistol rounds 0 and "
          f"{HALF_ROUNDS}. A choice.",
          f"- Isolated: no listed teammate within {ISOLATED_CM / 100:.0f} m "
          "(`winprob_reference.ISOLATED_CM`). A kill lists only some players, "
          "so a missing teammate may be alive and unlisted.",
          "- Same-agent peers: the peers' ratio on each agent the player "
          "played, weighted by the player's denominator on it (the lobby with "
          "the player's agent mix). Grouped tables leave it empty.",
          "- Kills, deaths and assists are derived from the kill list; the "
          "records' own per-player totals are listed under Data. Kills agree; "
          "the derived deaths and assists differ slightly, by causes not "
          "examined here.",
          f"- Intervals: {R['boot']} match resamples, percentile 95%. "
          f"`LOW n` marks fewer than {MIN_EVENTS} player events in the "
          "denominator. An interval resampled from fewer than ten matches "
          "is rough; the matches column says how many.",
          f"- {len(P)} pooled metrics: at 95% about one in twenty intervals "
          "excludes zero by chance alone.", "",
          "## Three strongest signals", ""]
    for i, s in enumerate(R["strongest"], 1):
        r = P[s["metric"]]
        L.append(f"{i}. **{s['metric']}** ({r['text']}): player "
                 f"{_num_text(r['owner'])} against peers {_num_text(r['peers'])}, "
                 f"difference {_num_text(r['diff'])} "
                 f"[{_num_text(r['ci_diff'][0])}, {_num_text(r['ci_diff'][1])}], "
                 f"{r['owner_n']:.0f} player events over {r['matches']} "
                 f"matches; against same-agent peers "
                 f"{_num_text(r.get('peers_matched'))}, difference "
                 f"{_num_text(r.get('diff_matched'))} "
                 f"{_ci(r.get('ci_diff_matched'))}. "
                 f"Hypothesis for the decision-value models: the "
                 f"player {s['hypothesis']}.")
    L += ["", "## Pooled", ""]
    fams = []
    for n, r in P.items():
        if r["family"] not in fams:
            fams.append(r["family"])
    for f in fams:
        L += [f"### {f}", "", HDR]
        L += [_table_row(n, r) for n, r in P.items() if r["family"] == f]
        L += [""]
        for n, r in P.items():
            if r["family"] == f:
                L.append(f"- `{n}`: {r['text']}")
        L.append("")
    L += ["## Trends", "",
          "Player minus pooled peers, with the 95% interval and the player's "
          "denominator; the full tables follow under By group.", ""]
    for g in TREND_GROUPS:
        L += [f"### by {g}", "",
              "| " + g + " | matches | " + " | ".join(TREND_METRICS) + " |",
              "|---" * (len(TREND_METRICS) + 2) + "|"]
        for v, ms in G[g].items():
            cells = []
            for n in TREND_METRICS:
                r = ms.get(n) or {}
                cells.append(f"{_num_text(r.get('diff'))} {_ci(r.get('ci_diff'))} "
                             f"n={r.get('owner_n', 0):.0f}"
                             + (" LOW" if r.get("low_n") else ""))
            m0 = (ms.get(TREND_METRICS[0]) or {}).get("owner_matches", 0)
            L.append(f"| {v} | {m0} | " + " | ".join(cells) + " |")
        L.append("")
    L += ["## By group", "",
          "Headline metrics per group; for `agent`, the peers are those on "
          "the same agent, and utility casts compare like with like.", ""]
    for g, vals in G.items():
        L += [f"### by {g}", ""]
        for v, ms in vals.items():
            L += [f"#### {g} = {v}", "", HDR]
            L += [_table_row(n, r) for n, r in ms.items()]
            L.append("")
    L += ["## Not done", ""] + [f"- {x}" for x in R["not_done"]] + [""]
    return "\n".join(L)


NOT_DONE = [
    "No spatial decision model: rotations and lurks are seen only through "
    "deaths' distance to teammates and trades, not paths between kills.",
    "Ability casts are match totals; Riot and HenrikDev give no per-round "
    "cast counts here, so casts are not split by side or tied to kills.",
    "Assists per cast is a ratio of totals, not cast-to-assist attribution.",
    "No adjustment for multiple comparisons beyond ranking on interval width.",
    "No per-peer statistics, by design; no comparison against other lobbies.",
    "Captured Riot records carry no tier name, so their lobby rank band is "
    "`unknown`, and no season short name, so their season is `unknown`.",
]


def run_profile(store: Path, out: Path, boot: int = BOOT) -> dict:
    L = load(store)
    c = connect(L["tables"])
    features(c)
    player_match(c, L["labels"])
    S = sums(c)
    prof = profile(S, boot)
    R = {"version": VERSION, "parser": lf.PARSER_VERSION,
         "written": dt.datetime.now().isoformat(timespec="seconds"),
         "boot": boot, "trade_window_ms": TRADE_WINDOW_MS,
         "counts": L["counts"], "coverage": data_coverage(c),
         "side_check": side_check(c, L["riot_roles"]),
         "profile": prof, "strongest": strongest(prof["pooled"]),
         "per_match": per_match(S, HEADLINE), "not_done": NOT_DONE}
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.json").write_text(json.dumps(R, indent=1, default=str),
                                      encoding="utf-8")
    (out / "report.md").write_text(report_md(R), encoding="utf-8")
    return R


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--store", type=Path, default=STORE)
    r.add_argument("--out", type=Path, default=None)
    r.add_argument("--boot", type=int, default=BOOT)
    a = ap.parse_args(argv)
    out = a.out or (a.store / "analysis" / OUT_NAME)
    R = run_profile(a.store, out, a.boot)
    print(f"{VERSION}: {R['coverage']['owner_matches']} matches with the "
          f"player, {R['coverage']['owner_rounds']} rounds; wrote "
          f"{out / 'profile.json'} and {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
