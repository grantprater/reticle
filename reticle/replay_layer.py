"""The replay layer: one match's state, from its kept replay, on one schema.

[owns:replay-tables]

    reticle replay-layer MATCH|SESSION [...]      build (or rebuild) the layer
    reticle replay-layer --all                    every parsed replay
    reticle replay-layer --status [MATCH|SESSION] current, stale or absent

What it is
----------
Every consumer of a replay used to re-derive the same joins: net guids to
players, the replay clock to the capture clock, interpolation, world units to
minimap pixels, actors to abilities and casters. This module does them once
per match and stores the result as versioned Parquet tables, so the slot
model, the scorers, the overlay and the episode builder read one schema and
never touch vrfkit's export. The schema is documented in
docs/REPLAY_LAYER.md; `load` is the read API.

Every row carries `source`: `truth` for what the replay holds. `observed`,
`inferred` and `unknown` are reserved for the vision pipeline's estimates of
the same fields (docs/ENTITY_STATE.md), so one table can hold a truth row
beside the estimate it scores.

Times: `t_rep` is the replay's server clock (ms); `t_cap` the capture's
(ms), `t_rep + a` with `a` the offset `replay_source.capture_replay_context`
fits on the STORED deaths. A match with no capture, or whose alignment
refuses, has `t_cap` null and the reason in the head. Positions are world
units (cm); `px`, `py` and `facing_px` are baked-widget pixels through
`MapFrame` of the named geometry, null without a capture.

The use policy (docs/EXTERNAL_GROUND_TRUTH.md) holds: nothing here is shown
during play. The held-out match (`HELD_OUT`) is built so `plan` is complete,
and its head carries no statistics; no command here prints its contents.

Where it is stored, and why
---------------------------
`<store>/analysis/replay-layer/<match>/`. `l2/` holds the pipeline's own
observation tables, which `Store` serves to readers and consumers; truth
stored there would sit one call from a reader. `analysis/` is where
evaluation truth already lives (`replay-truth-*`, `replay-abilities-*`).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .replay_actors import (GAME_BUILD, NON_CHARACTER, REPLAY_ACTORS_VERSION, Export, _leaf,
                            class_census, handoff_pairs, slot_map)
from .replay_source import (MAX_GAP_MS, MINIMAP_LAG_MS, REPLAY_SOURCE_VERSION, VRFKIT_VERSION,
                            Reference, Replay, capture_replay_context, facing_px_deg,
                            frames_to_replay, parsed_dir, parsed_root, replay_entry,
                            replay_manifest, sample_stats, to_px)
from .store import DEFAULT_STORE

REPLAY_LAYER_VERSION = "replay-layer-0.1.2"
#: The held-out match (docs/EXTERNAL_GROUND_TRUTH.md, "a match that scores a
#: fitted reader or model is held out from its fit"): built, never summarised.
HELD_OUT = ("bd7efa02",)
#: The values `source` may take. Only `truth` is written here.
SOURCES = ("truth", "observed", "inferred", "unknown")
#: A dead player's own damage or effects this long after his death show him
#: alive again; earlier ones are his death's own effects.
REVIVE_QUIET_MS = 3000.0
#: Teams without a Riot record: each player's position this long after the
#: round's start (buy phase, players in spawn) splits the ten into two
#: spawn groups.
SPAWN_PROBE_MS = 2000.0
#: `MulticastSetPhase.NewPhase` values read here: 3 opens the buy phase (it
#: coincides with `roundStarted`), 4 ends it (`ClientBuyPhaseEnd`, the
#: `CastTime` epoch), 5 is read as the round's end. Phase 5 as round end is
#: this module's reading, checked per round in the head (`round_end_check`).
PHASE_BUY_END, PHASE_ROUND_END = 4, 5
#: Abilities' inventory items carry charges, not world positions.
INVENTORY_ROLES = ("ability item", "equippable")
#: One-shot effect RPCs: the cosmetic effects, sounds among them.
EFFECT_RPCS = ("ClientPlayOneShotEffectAtLocation", "ReplayPlayOneShotEffectAtLocation",
               "MulticastPlayOneShotEffect", "ReplayRecordOneShotEffect")
#: Equippables a player holds (guns, the knife) live under this path; their
#: damage shows its holder alive.
HELD_EQUIPPABLE_PATH = "/Game/Equippables/"
DAMAGE_RPCS = ("MulticastNotifyDamage_Point", "MulticastNotifyDamage_Base")
TABLES = ("entities", "ticks", "frames", "events", "state", "rounds", "lives")


# ----------------------------------------------------------------- paths

def layer_root(root=DEFAULT_STORE) -> Path:
    return Path(root) / "analysis" / "replay-layer"


def layer_dir(match: str, root=DEFAULT_STORE) -> Path:
    return layer_root(root) / match


def parsed_matches(root=DEFAULT_STORE) -> list[str]:
    """Every parsed replay with an export."""
    d = parsed_root(root)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if (p / "export" / "actors.parquet").is_file())


def is_held_out(match: str) -> bool:
    return any(match.startswith(h) for h in HELD_OUT)


def resolve(key: str, root=DEFAULT_STORE) -> tuple[str | None, str | None]:
    """(match, session) for a match id, a match prefix or a capture session."""
    man = replay_manifest(root)
    e = replay_entry(key, root, man)
    if e is not None:
        return Path(e["file"]).stem, key
    hits = [m for m in parsed_matches(root) if m.startswith(key)]
    if len(hits) != 1:
        return None, None
    match = hits[0]
    e = next((f for f in man.get("files") or [] if Path(f["file"]).stem == match), None)
    return match, (e or {}).get("capture_session")


# ----------------------------------------------------------------- staleness

def current_inputs(match: str, root=DEFAULT_STORE, geometry: Path | None = None) -> dict:
    """The stamps a layer of `match` built now would record: the code, the
    parse, and for a captured match the Riot record, the stored deaths the
    clock is fitted on, the geometry, the frame grid and the lineup."""
    from . import geometry as _geo
    from .input_stamps import file_sha16
    from .replay_source import riot_record_path

    root = Path(root)
    _m, sid = resolve(match, root)
    out = {"replay_layer": REPLAY_LAYER_VERSION, "replay_source": REPLAY_SOURCE_VERSION,
           "replay_actors": REPLAY_ACTORS_VERSION, "game_files": GAME_BUILD,
           "vrfkit": VRFKIT_VERSION,
           "parse": file_sha16(parsed_dir(match, root) / "provenance.json"),
           "session": sid}
    if sid:
        rp = riot_record_path(sid, root)
        out["riot_record"] = file_sha16(rp) if rp else None
        out["deaths"] = file_sha16(root / "events" / "death" / f"{sid}.jsonl")
        gp = Path(geometry) if geometry else _geo.path_of(sid, root)
        out["geometry"] = (f"{gp.name}@{file_sha16(gp)}" if gp is not None and Path(gp).is_file()
                           else None)
        out["frames"] = file_sha16(root / "events" / "ally_icon" / f"{sid}.jsonl")
        out["lineup"] = file_sha16(root / "lineups" / f"{sid}.json")
    return out


def status(match: str, root=DEFAULT_STORE) -> dict:
    """`{state, moved}`: `absent` with no layer, `stale` when its version or
    any recorded input differs from `current_inputs`, else `current`. A layer
    built on another geometry than the session's own records it, and is
    compared against that file."""
    head_p = layer_dir(match, root) / "layer.json"
    if not head_p.is_file():
        return {"state": "absent", "moved": []}
    head = json.loads(head_p.read_text(encoding="utf-8"))
    rec = head.get("inputs") or {}
    gp = (head.get("geometry_override") or None)
    now = current_inputs(match, root, gp)
    moved = sorted(k for k in set(now) | set(rec) if now.get(k) != rec.get(k))
    return {"state": "stale" if moved else "current", "moved": moved,
            "stored": rec.get("replay_layer"), "current": REPLAY_LAYER_VERSION}


def session_status(sid: str, root=DEFAULT_STORE) -> dict | None:
    """The layer status of the replay a session's manifest entry names, or
    None where no kept replay names the session."""
    e = replay_entry(sid, root)
    if e is None:
        return None
    match = Path(e["file"]).stem
    if not (parsed_dir(match, root) / "export" / "actors.parquet").is_file():
        return {"match": match, "state": "unparsed", "moved": [],
                "command": f"reticle replay-keep {sid}"}
    return {"match": match, **status(match, root), "command": f"reticle replay-layer {sid}"}


# ----------------------------------------------------------------- helpers

def _json(o) -> str:
    return json.dumps(o, separators=(",", ":"), default=str)


def _vec(s: str | None) -> tuple[float, float, float] | None:
    """`(x,y,z)` as vrfkit writes a vector, or None."""
    if not s or not s.startswith("("):
        return None
    try:
        v = [float(t) for t in s.strip("()").split(",")]
    except ValueError:
        return None
    return (v[0], v[1], v[2]) if len(v) == 3 else None


_NAMES: dict = {}


def _read_fields(match: str, root, names: list[str] | None = None, prefixes=(),
                 guids: list[int] | None = None):
    """fields.parquet rows whose field name is in `names` or starts with one of
    `prefixes` (and, with `guids`, whose actor is one of them), file order
    kept in `row`. Column selection and a predicate on the dictionary keep the
    read small."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    path = parsed_dir(match, root) / "export" / "fields.parquet"
    want = set(names or ())
    if prefixes:
        if path not in _NAMES:
            col = pq.read_table(path, columns=["field_name"])["field_name"]
            _NAMES[path] = set(pc.unique(pc.cast(col, pa.string())).to_pylist())
        vals = _NAMES[path]
        want |= {v for v in vals if v and v.startswith(tuple(prefixes))}
    if not want:
        return None
    filt = [("field_name", "in", sorted(want))]
    if guids is not None:
        filt.append(("actor_net_guid", "in", sorted({int(g) for g in guids})))
    t = pq.read_table(path, columns=["time_ms", "packet_id", "actor_net_guid", "object_net_guid",
                                     "group_path", "field_name", "value_i64", "value_f64",
                                     "value_str", "value_bool"], filters=filt)
    return {"t": t["time_ms"].to_numpy().astype(np.float64),
            "packet": t["packet_id"].to_numpy().astype(np.int64),
            "g": t["actor_net_guid"].to_numpy().astype(np.int64),
            "obj": t["object_net_guid"].to_numpy(zero_copy_only=False),
            "gp": np.array(pc.cast(t["group_path"], pa.string()).to_pylist(), dtype=object),
            "n": np.array(pc.cast(t["field_name"], pa.string()).to_pylist(), dtype=object),
            "i": t["value_i64"].to_numpy(zero_copy_only=False),
            "f": t["value_f64"].to_numpy(zero_copy_only=False),
            "s": np.array(pc.cast(t["value_str"], pa.string()).to_pylist(), dtype=object),
            "b": np.array(t["value_bool"].to_pylist(), dtype=object)}


def rpc_calls(F: dict, prefix: str) -> dict | None:
    """One row per call of the RPC `prefix` (`<prefix>.<field>` rows): the
    calling actor, time, packet and each field's value (the decoded one of
    i64, f64, str, bool). A call's rows share actor, object and packet, and a
    new call starts where the family's first field repeats."""
    if F is None:
        return None
    m = np.flatnonzero(np.array([n.startswith(prefix + ".") for n in F["n"]], bool))
    if m.size == 0:
        return None
    suf = np.array([F["n"][k][len(prefix) + 1:] for k in m], dtype=object)
    obj = np.array([-1 if v is None or (isinstance(v, float) and not np.isfinite(v)) else int(v)
                    for v in F["obj"][m]], np.int64)
    key = np.stack([F["g"][m], obj, F["packet"][m]], axis=1)
    change = np.ones(m.size, bool)
    change[1:] = np.any(key[1:] != key[:-1], axis=1)
    first = suf[0]
    start = change | (suf == first)
    call = np.cumsum(start) - 1
    n = int(call[-1]) + 1
    head = np.flatnonzero(start)
    out = {"t": F["t"][m][head], "g": F["g"][m][head], "obj": obj[head],
           "packet": F["packet"][m][head], "fields": {}}
    for name in np.unique(suf):
        k = np.flatnonzero(suf == name)
        vals = np.full(n, None, dtype=object)
        for j, src in zip(k, m[k]):
            v = F["i"][src]
            if v is None or (isinstance(v, float) and not np.isfinite(v)):
                v = F["f"][src]
                if v is None or (isinstance(v, float) and not np.isfinite(v)):
                    v = F["s"][src] if F["s"][src] is not None else F["b"][src]
            vals[call[j]] = v
        out["fields"][str(name)] = vals
    return out


def _net_guid_paths(match: str, root) -> dict:
    import pyarrow.parquet as pq
    t = pq.read_table(parsed_dir(match, root) / "export" / "net_guids.parquet",
                      columns=["net_guid", "path"])
    return dict(zip(t["net_guid"].to_numpy().astype(np.int64).tolist(), t["path"].to_pylist()))


def _write_table(path: Path, cols: dict, meta: dict) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq
    t = pa.table(cols)
    t = t.replace_schema_metadata({**{k.encode(): str(v).encode() for k, v in meta.items()}})
    pq.write_table(t, path, compression="zstd")
    return t.num_rows


# ----------------------------------------------------------------- teams

def spawn_teams(rp: Replay, rs: np.ndarray) -> dict:
    """Two spawn groups per round from each player's position `SPAWN_PROBE_MS`
    after the round starts, split by 2-means seeded with the two farthest
    players. Labels `A`/`B` follow round 0's split; `agree` counts the rounds
    whose split equals it."""
    subs = list(rp.subjects)
    parts = []
    for t0 in rs:
        xy = np.array([[rp.sample(s, [t0 + SPAWN_PROBE_MS])[k][0] for k in ("x", "y")]
                       for s in subs])
        ok = np.all(np.isfinite(xy), axis=1)
        if ok.sum() < 4:
            parts.append(None)
            continue
        d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
        d[~ok, :] = 0
        d[:, ~ok] = 0
        i, j = np.unravel_index(np.argmax(d), d.shape)
        c = np.array([xy[i], xy[j]])
        lab = np.zeros(len(subs), np.int64)
        for _ in range(10):
            dd = np.hypot(xy[:, None, 0] - c[None, :, 0], xy[:, None, 1] - c[None, :, 1])
            lab = np.argmin(dd, axis=1)
            c = np.array([xy[ok & (lab == q)].mean(axis=0) for q in (0, 1)])
        parts.append(np.where(ok, lab, -1))
    ref = next((p for p in parts if p is not None and (p >= 0).all()), None)
    if ref is None:
        return {"team": {}, "agree": 0, "rounds": len(parts), "basis": "spawn_cluster_failed"}
    agree = 0
    for p in parts:
        if p is None:
            continue
        ok = p >= 0
        if np.all(p[ok] == ref[ok]) or np.all(p[ok] == 1 - ref[ok]):
            agree += 1
    return {"team": {s: "AB"[int(ref[k])] for k, s in enumerate(subs)}, "agree": agree,
            "rounds": len(parts), "basis": "spawn_cluster"}


# ----------------------------------------------------------------- rounds, lives

def round_table(rp: Replay, ex: Export) -> list[dict]:
    """Per replay round: start (`roundStarted`), buy end and round end
    (`MulticastSetPhase` 4 and 5), the next start, plants and defuses."""
    rs = rp.round_starts()
    m = ex.f_n == "MulticastSetPhase.NewPhase"
    ph_t, ph_v = ex.f_t[m], np.array([int(v) for v in ex.f_i[m]])
    o = np.argsort(ph_t, kind="stable")
    ph_t, ph_v = ph_t[o], ph_v[o]
    plants = np.array([e["t"] for e in rp.group("spikePlanted")])
    defuses = np.array([e["t"] for e in rp.group("spikeDefused")])
    out = []
    for r, t0 in enumerate(rs):
        nxt = float(rs[r + 1]) if r + 1 < rs.size else float(rp.duration_ms)
        sel = (ph_t > t0) & (ph_t <= nxt)
        be = ph_t[sel & (ph_v == PHASE_BUY_END)]
        en = ph_t[sel & (ph_v == PHASE_ROUND_END)]
        pl = plants[(plants >= t0) & (plants < nxt)] if plants.size else plants
        df = defuses[(defuses >= t0) & (defuses < nxt)] if defuses.size else defuses
        out.append({"round": r, "t_start": float(t0),
                    "t_buy_end": float(be[0]) if be.size else None,
                    "t_end": float(en[0]) if en.size else None,
                    "end_basis": "phase_5" if en.size else "next_round_start",
                    "t_next_start": nxt,
                    "t_plant": float(pl[0]) if pl.size else None,
                    "t_defuse": float(df[0]) if df.size else None})
    return out


def activity_by_subject(EV: dict, e_of: dict) -> dict:
    """subject -> sorted replay times of the damage he dealt with an
    equippable he held (a gun or the knife, `HELD_EQUIPPABLE_PATH`): only a
    living player fires one, where his placed abilities and effects outlive
    him."""
    sub = {e: s for (kind, s), e in e_of.items() if kind == "player"}
    out = defaultdict(list)
    for k, e, t, d in zip(EV["kind"], EV["e"], EV["t_rep"], EV["detail"]):
        if k == "damage" and e is not None and e in sub and json.loads(d).get("by_held_equippable"):
            out[sub[e]].append(float(t))
    return {s: np.sort(np.asarray(v)) for s, v in out.items()}


def lives_table(rp: Replay, rounds: list[dict], activity: dict) -> list[dict]:
    """Per player per round: alive from the round's start to his first death
    in it or the next round's start, since play continues through the
    post-round period [domain:rounds/post-round-period]. A later life opens where the replay shows him
    alive again after a death in the same round: a second death
    (`second_death`), or damage he deals with a held gun or knife more than
    `REVIVE_QUIET_MS` after it (`own_activity`, `activity_by_subject`),
    opened at the first such hit. A second death with no activity before it opens at the death
    itself, its open unknown before (`t_open_lo` holds the earlier death).
    His body's own movement is not evidence: the death throws it about 3 m
    within half a second (`docs/REPLAY_LAYER.md`)."""
    deaths = defaultdict(list)
    for e in rp.group("characterDeath"):
        if e.get("victim"):
            deaths[e["victim"]].append(e)
    out = []
    for s in rp.subjects:
        act = activity.get(s, np.zeros(0))
        for R in rounds:
            # play continues through the post-round period to the next buy
            # phase [domain:rounds/post-round-period]
            end = R["t_next_start"]
            t_open, lo, basis, ev = R["t_start"], None, "round_start", None
            ds = sorted((e for e in deaths[s] if R["t_start"] <= e["t"] < R["t_next_start"]),
                        key=lambda e: e["t"])
            for n, e in enumerate(ds):
                out.append({"subject": s, "round": R["round"], "t_open": t_open, "t_open_lo": lo,
                            "open_basis": basis, "t_close": e["t"], "close_basis": "death",
                            "killer": e.get("killer"), "evidence": ev})
                nxt = ds[n + 1]["t"] if n + 1 < len(ds) else end
                k = int(np.searchsorted(act, e["t"] + REVIVE_QUIET_MS, side="left"))
                if k < act.size and act[k] < nxt:
                    t_open, lo, basis = float(act[k]), e["t"], "own_activity"
                    ev = _json({"after_death_ms": round(float(act[k]) - e["t"], 1),
                                "second_death": n + 1 < len(ds)})
                elif n + 1 < len(ds):
                    t_open, lo, basis = ds[n + 1]["t"], e["t"], "second_death"
                    ev = _json({"open_unknown_between": [e["t"], ds[n + 1]["t"]]})
                else:
                    t_open = None
                    break
            else:
                if t_open is not None:
                    out.append({"subject": s, "round": R["round"], "t_open": t_open,
                                "t_open_lo": lo, "open_basis": basis, "t_close": end,
                                "close_basis": "next_round_start", "killer": None,
                                "evidence": ev})
    return out


def alive_mask(lives: list[dict], subject: str, t) -> np.ndarray:
    t = np.asarray(t, float)
    out = np.zeros(t.shape, bool)
    for L in lives:
        if L["subject"] == subject:
            out |= (t >= L["t_open"]) & (t < L["t_close"])
    return out


# ----------------------------------------------------------------- build

def build(key: str, root=DEFAULT_STORE, geometry: Path | None = None) -> dict:
    """Build the layer of one match (a match id, prefix or capture session)
    from stored data and write it; returns the head."""
    root = Path(root)
    match, sid = resolve(key, root)
    if match is None:
        return {"key": key, "refused": "no_parsed_replay"}
    held = is_held_out(match)
    rp = Replay(match, root)
    ex = Export(match, rp=rp, root=root)
    ref = Reference(root / "external" / "valorant-api", fetch=False)
    agent = {s: ref.agent(c) for s, c in rp.loadouts().items()}
    head = {"match": match, "session": sid, "replay_layer_version": REPLAY_LAYER_VERSION,
            "built_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "held_out": held, "inputs": current_inputs(match, root, geometry),
            "geometry_override": str(geometry).replace("\\", "/") if geometry else None,
            "source": "truth"}
    prov_p = parsed_dir(match, root) / "provenance.json"
    prov = json.loads(prov_p.read_text(encoding="utf-8")) if prov_p.is_file() else {}
    head["provenance"] = {"vrfkit": prov.get("vrfkit"), "input_sha256": prov.get("input_sha256"),
                          "input_sha256_matches_manifest": prov.get("input_sha256_matches_manifest"),
                          "map": rp.map_url()}

    # -- the capture: clock, player, teams, map frame
    ctx = None
    a, mf, me, riot_team = None, None, None, {}
    if sid:
        ctx = capture_replay_context(sid, geometry, root)
        out = ctx["out"]
        head["capture"] = {k: out.get(k) for k in ("capture", "profile", "player_basis",
                                                   "team_source", "refused", "geometry",
                                                   "px_per_m", "widget")}
        if "align" in out:
            head["capture"]["align"] = {k: out["align"].get(k) for k in (
                "a_ms", "slope", "matched", "n_riot", "n_store", "residual_mad_ms",
                "drift_ms_over_match", "stored_round_start_minus_replay_ms")}
        a = ctx.get("a")
        mf = ctx.get("mf")
        me = ctx.get("me")
        riot_team = ctx.get("team") or {}
        head["capture"]["minimap_lag_ms"] = MINIMAP_LAG_MS
    else:
        head["capture"] = {"refused": "no_capture_session"}

    def cap(t):
        if a is None:
            return np.full(np.shape(t), np.nan)
        return np.asarray(t, float) + a

    rounds = round_table(rp, ex)
    rs = rp.round_starts()
    spawn = spawn_teams(rp, rs)
    team = {s: riot_team.get(s) or spawn["team"].get(s) for s in rp.subjects}
    team_basis = "riot_record" if riot_team else spawn["basis"]
    head["teams"] = {"basis": team_basis, "spawn_cluster_rounds_agreeing": spawn["agree"],
                     "spawn_cluster_rounds": spawn["rounds"]}
    if riot_team and spawn["team"]:
        # the spawn split against Riot's teams: one label per Riot team
        pairs = Counter((riot_team.get(s), spawn["team"].get(s)) for s in rp.subjects)
        head["teams"]["spawn_vs_riot"] = {f"{k[0]}|{k[1]}": v for k, v in pairs.items()}

    # -- players
    subs = list(rp.subjects)
    my_team = team.get(me) if me else None
    slot_of, slot_basis = _slot_keys(sid, root, subs, agent, team, my_team)
    E = defaultdict(list)          # the entities table, column-wise
    e_of = {}

    def add_entity(row):
        e = len(E["entity_id"])
        for k in ENTITY_COLUMNS:
            E[k].append(row.get(k))
        return e

    for s in subs:
        gs = sorted(g for g, v in rp.guid_subject.items() if v == s)
        e_of[("player", s)] = add_entity({
            "entity_id": f"player:{s}", "kind": "player", "subject": s,
            "agent": agent.get(s), "character_id": rp.loadouts().get(s), "team": team.get(s),
            "team_basis": team_basis,
            "side_rel": None if my_team is None else ("ally" if team.get(s) == my_team else "enemy"),
            "is_me": None if me is None else s == me,
            "slot_key": slot_of.get(s), "slot_key_basis": slot_basis.get(s),
            "guid": gs[0] if gs else None, "guids": _json(gs), "source": "truth"})

    T = defaultdict(list)

    # -- children
    cen = class_census(match, ex)
    by_cp = {r["class_path"]: r for r in cen["classes"]}
    # an ability folder's world actors, and the named non-character actors
    # (ult orbs, the spike); never the replay controller or other
    # character-folder infrastructure
    inst = [i for i in ex.instances() if i["class_path"] in by_cp
            and by_cp[i["class_path"]]["role"] not in INVENTORY_ROLES
            and (by_cp[i["class_path"]].get("code") is not None
                 or i["class_path"].rsplit(".", 1)[0] in NON_CHARACTER)]
    child_guids = {i["guid"] for i in inst}
    by_class = defaultdict(list)
    for i in ex.instances():
        by_class[i["class_path"]].append(i)
    hand = handoff_pairs(ex, cen["classes"], by_class)
    pred = {r["object_guid"]: r for h in hand.values() for r in h["pairs"]}
    undecoded = _undecoded(match, root, sorted(child_guids))
    kits = {}
    for i in inst:
        r = by_cp[i["class_path"]]
        s, path = ex.owner_path(i["guid"])
        own_ref = ex._refs["Owner"].get(i["guid"])
        parent = own_ref if own_ref in child_guids else None
        code_agent = agent.get(s) if s else None
        tray = None
        if r.get("mapped") and r.get("ability") and code_agent:
            if code_agent not in kits:
                from .lineup import abilities_for
                kits[code_agent] = abilities_for(code_agent, root)
            tray = next((k for k, nm in kits[code_agent].items()
                         if str(nm).casefold() == str(r["ability"]).casefold()), None)
        close = i["close_ms"]
        rnd = int(np.searchsorted(rs, i["open_ms"], side="right") - 1) if rs.size else None
        x, y, z = i["xyz"]
        e_of[("child", i["guid"])] = add_entity({
            "entity_id": f"child:{i['guid']}", "kind": "child", "subject": s,
            "agent": code_agent, "team": team.get(s) if s else None,
            "team_basis": team_basis if s else None,
            "side_rel": (None if my_team is None or not s else
                         ("ally" if team.get(s) == my_team else "enemy")),
            "guid": i["guid"], "class": _leaf(i["class_path"]), "class_path": i["class_path"],
            "role": r["role"], "code": r.get("code"), "folder": r.get("folder"),
            "ability": r.get("ability"), "mapped": r.get("mapped"),
            "unmapped_reason": r.get("unmapped_reason"), "tray_key": tray,
            "owner_path": _json(path), "owner_resolved": s is not None,
            "owner_ref_guid": own_ref, "owner_ref_class": _leaf(ex.cls.get(own_ref)) if own_ref else None,
            "parent_guid": parent, "parent_basis": "Owner" if parent else None,
            "predecessor_guid": pred.get(i["guid"], {}).get("projectile_guid"),
            "predecessor_basis": "handoff" if i["guid"] in pred else None,
            "t_open_rep": i["open_ms"], "t_close_rep": close,
            "close_basis": "actor_close" if close is not None else "open_at_end",
            "round": rnd, "spawn_x": x, "spawn_y": y, "spawn_z": z, "spawn_yaw": i["yaw"],
            "undecoded": _json(undecoded.get(i["guid"], [])), "source": "truth"})
        # the spawn is the child's first sample
        e = e_of[("child", i["guid"])]
        for k, v in (("e", np.array([e], np.int32)), ("t_rep", np.array([i["open_ms"]])),
                     ("x", np.array([x])), ("y", np.array([y])), ("z", np.array([z])),
                     ("yaw", np.array([i["yaw"]])), ("pitch", np.array([np.nan])),
                     ("alive", np.array([True])), ("sample", np.array(["spawn"], dtype=object))):
            T[k].append(v)
    # co-opened: same owner, same folder, same replay ms (a trapwire's anchors)
    E["co_open_guids"] = _co_open(E)
    # moving children: ReplicatedMovement and non-player movement rows
    _child_tracks(ex, rp, child_guids, e_of, T)

    # -- events, then lives: a revive is read from the dead player's own
    # later activity, which the events hold
    EV = _events(match, root, rp, ex, rounds, rs, e_of, agent, cen)
    lives = lives_table(rp, rounds, activity_by_subject(EV, e_of))
    for L in lives:
        if L["open_basis"] != "round_start":
            _ev(EV, kind="revive", t_rep=L["t_open"], e=e_of[("player", L["subject"])],
                value_num=L["round"], value_str=L["open_basis"], detail=L["evidence"],
                provenance="lives_table: a second death, or his held gun's or knife's "
                           "damage after his death")

    # -- ticks: players at the server tick
    for s in subs:
        P = rp.players[s]
        n = P["t"].size
        e = e_of[("player", s)]
        T["e"].append(np.full(n, e, np.int32))
        T["t_rep"].append(P["t"])
        for k in ("x", "y", "z", "yaw", "pitch"):
            T[k].append(P[k])
        T["alive"].append(alive_mask(lives, s, P["t"]))
        T["sample"].append(np.full(n, "movement", dtype=object))

    ticks = {k: np.concatenate(v) for k, v in T.items()}
    o = np.lexsort((ticks["t_rep"], ticks["e"]))
    ticks = {k: v[o] for k, v in ticks.items()}
    ticks["t_cap"] = cap(ticks["t_rep"])
    if mf is not None:
        px, py = to_px(mf, ticks["x"], ticks["y"])
        ticks["px"], ticks["py"] = px, py
        ticks["facing_px"] = facing_px_deg(mf, ticks["x"], ticks["y"], ticks["yaw"])
    else:
        ticks["px"] = ticks["py"] = ticks["facing_px"] = np.full(ticks["t_rep"].size, np.nan)
    ticks["source"] = np.full(ticks["t_rep"].size, "truth", dtype=object)
    for k in ("x", "y", "z", "yaw", "pitch", "px", "py", "facing_px"):
        ticks[k] = ticks[k].astype(np.float32)

    # child spawn px and capture times
    E["t_open_cap"] = [None if a is None or t is None else t + a for t in E["t_open_rep"]]
    E["t_close_cap"] = [None if a is None or t is None else t + a for t in E["t_close_rep"]]
    if mf is not None:
        sx = np.array([np.nan if v is None else v for v in E["spawn_x"]], float)
        sy = np.array([np.nan if v is None else v for v in E["spawn_y"]], float)
        qx, qy = to_px(mf, sx, sy)
        E["spawn_px"] = [None if not np.isfinite(v) else float(v) for v in qx]
        E["spawn_py"] = [None if not np.isfinite(v) else float(v) for v in qy]
    else:
        E["spawn_px"] = E["spawn_py"] = [None] * len(E["entity_id"])

    # -- frames: players at the capture's stored minimap frame grid
    frames = _frame_rows(sid, root, rp, subs, e_of, lives, a, mf, rs) if a is not None else None

    # -- sparse state
    ST = _state(match, root, rp, ex, e_of)
    for tab in (EV, ST):
        tab["t_cap"] = [None if a is None or t is None else t + a for t in tab["t_rep"]]
        tab["round"] = [None if t is None or not rs.size else
                        int(np.searchsorted(rs, t, side="right") - 1) for t in tab["t_rep"]]
        tab["source"] = ["truth"] * len(tab["t_rep"])
    for R in rounds:
        for k in ("t_start", "t_buy_end", "t_end", "t_next_start", "t_plant", "t_defuse"):
            R[k.replace("t_", "tcap_", 1)] = None if a is None or R[k] is None else R[k] + a
    for L in lives:
        L["e"] = e_of[("player", L["subject"])]
        L["tcap_open"] = None if a is None else L["t_open"] + a
        L["tcap_close"] = None if a is None else L["t_close"] + a
        L["source"] = "truth"

    # -- write
    d = layer_dir(match, root)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"replay_layer_version": REPLAY_LAYER_VERSION, "match": match, "session": sid or "",
            "a_ms": "" if a is None else a}
    counts = {"entities": _write_table(d / "entities.parquet", dict(E), meta),
              "ticks": _write_table(d / "ticks.parquet", ticks, meta),
              "events": _write_table(d / "events.parquet", EV, meta),
              "state": _write_table(d / "state.parquet", ST, meta),
              "rounds": _write_table(d / "rounds.parquet", _columns(rounds), meta),
              "lives": _write_table(d / "lives.parquet", _columns(lives), meta)}
    if frames is not None:
        counts["frames"] = _write_table(d / "frames.parquet", frames, meta)
    elif (d / "frames.parquet").is_file():
        (d / "frames.parquet").unlink()
    head["tables"] = counts
    head["a_ms"] = a
    head["frames"] = ({"source": "ally_icon frame grid", "lag_ms": MINIMAP_LAG_MS}
                      if frames is not None else {"refused": "no_capture_clock"})
    head["round_end_check"] = None if held else _round_end_check(rp, rounds)
    head["summary"] = None if held else layer_summary(match, root, d, E, EV, ex, cen, agent, rs)
    (d / "layer.json").write_text(json.dumps(head, indent=1, default=str), encoding="utf-8")
    return head


ENTITY_COLUMNS = ("entity_id", "kind", "subject", "agent", "character_id", "team", "team_basis",
                  "side_rel", "is_me", "slot_key", "slot_key_basis", "guid", "guids", "class",
                  "class_path", "role", "code", "folder", "ability", "mapped", "unmapped_reason",
                  "tray_key", "owner_path", "owner_resolved", "owner_ref_guid", "owner_ref_class",
                  "parent_guid", "parent_basis", "predecessor_guid", "predecessor_basis",
                  "t_open_rep", "t_close_rep", "close_basis", "round", "spawn_x", "spawn_y",
                  "spawn_z", "spawn_yaw", "undecoded", "source")


def _columns(rows: list[dict]) -> dict:
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    return {k: [r.get(k) for r in rows] for k in keys}


def _slot_keys(sid, root, subs, agent, team, my_team) -> tuple[dict, dict]:
    """Replay player -> the lineup slot whose resolved agent verdict names the
    same agent on the same side; the key rests on that verdict."""
    from .replay_source import canon_name
    out, why = {}, {}
    if not sid or my_team is None:
        return out, {s: "no_capture" for s in subs}
    p = Path(root) / "lineups" / f"{sid}.json"
    if not p.is_file():
        return out, {s: "no_lineup" for s in subs}
    lu = json.loads(p.read_text(encoding="utf-8"))
    verdicts = [v for v in lu.get("agent_identity") or [] if v.get("status") == "resolved"]
    for s in subs:
        side = "ally" if team.get(s) == my_team else "enemy"
        hits = [v["entity_id"] for v in verdicts
                if f":{side}:slot:" in v["entity_id"]
                and canon_name(v.get("agent")) == canon_name(agent.get(s))]
        if len(hits) == 1:
            out[s], why[s] = hits[0], "lineup_agent_verdict"
        else:
            why[s] = f"lineup_agent_match:{len(hits)}"
    return out, why


def _undecoded(match: str, root, guids: list[int]) -> dict:
    """actor guid -> the `group:field` names vrfkit left undecoded on it."""
    F = _read_fields(match, root, prefixes=("__vrfkit",), guids=guids)
    out = defaultdict(set)
    if F is None:
        return {}
    for g, gp, n in zip(F["g"], F["gp"], F["n"]):
        out[int(g)].add(f"{(gp or '').rsplit('/', 1)[-1]}:{n}")
    return {g: sorted(v) for g, v in out.items()}


def _co_open(E: dict) -> list:
    key = defaultdict(list)
    for k, kind in enumerate(E["kind"]):
        if kind == "child" and E["subject"][k]:
            key[(E["subject"][k], E["folder"][k], E["t_open_rep"][k])].append(E["guid"][k])
    out = []
    for k, kind in enumerate(E["kind"]):
        if kind != "child" or not E["subject"][k]:
            out.append(None)
            continue
        same = [g for g in key[(E["subject"][k], E["folder"][k], E["t_open_rep"][k])]
                if g != E["guid"][k]]
        out.append(_json(same) if same else None)
    return out


def _child_tracks(ex: Export, rp: Replay, guids: set, e_of: dict, T: dict) -> None:
    m = (ex.f_n == "ReplicatedMovement") & ex.f_has_s & np.isin(ex.f_g, list(guids))
    if m.any():
        loc = [json.loads(s) for s in ex.f_s[m]]
        g = ex.f_g[m]
        T["e"].append(np.array([e_of[("child", int(x))] for x in g], np.int32))
        T["t_rep"].append(ex.f_t[m])
        T["x"].append(np.array([p["location"]["x"] for p in loc], float))
        T["y"].append(np.array([p["location"]["y"] for p in loc], float))
        T["z"].append(np.array([p["location"]["z"] for p in loc], float))
        T["yaw"].append(np.array([(p.get("rotation") or {}).get("yaw", np.nan) for p in loc], float))
        T["pitch"].append(np.array([(p.get("rotation") or {}).get("pitch", np.nan) for p in loc],
                                   float))
        T["alive"].append(np.ones(g.size, bool))
        T["sample"].append(np.full(g.size, "rep_movement", dtype=object))
    R = rp.raw
    m = np.isin(R["g"], list(guids)) & ~R["park"]
    if m.any():
        T["e"].append(np.array([e_of[("child", int(x))] for x in R["g"][m]], np.int32))
        T["t_rep"].append(R["t"][m])
        for k in ("x", "y", "z", "yaw", "pitch"):
            T[k].append(R[k][m])
        T["alive"].append(np.ones(int(m.sum()), bool))
        T["sample"].append(np.full(int(m.sum()), "movement", dtype=object))


def _frame_rows(sid, root, rp, subs, e_of, lives, a, mf, rs) -> dict | None:
    """Every player at each stored `ally_icon` frame time: the replay time
    that frame shows (`frames_to_replay`, the minimap lag), `Replay.sample`'s
    position and yaw, alive by the lives table, and widget px."""
    p = Path(root) / "events" / "ally_icon" / f"{sid}.jsonl"
    if not p.is_file():
        return None
    fi, ft = [], []
    with p.open(encoding="utf-8") as f:
        for line in f:
            if '"kind":"frame"' in line or '"kind": "frame"' in line:
                r = json.loads(line)
                if r.get("kind") == "frame":
                    fi.append(r["frame_idx"])
                    ft.append(r["t_ms"])
    if not fi:
        return None
    fi, ft = np.asarray(fi, np.int64), np.asarray(ft, float)
    o = np.argsort(fi, kind="stable")
    fi, ft = fi[o], ft[o]
    t_rep = frames_to_replay(ft, a, MINIMAP_LAG_MS)
    cols = defaultdict(list)
    for s in subs:
        q = rp.sample(s, t_rep)
        live = alive_mask(lives, s, t_rep) & np.isfinite(q["x"])
        cols["frame_idx"].append(fi)
        cols["t_cap"].append(ft)
        cols["t_rep"].append(t_rep)
        cols["e"].append(np.full(fi.size, e_of[("player", s)], np.int32))
        for k in ("x", "y", "z", "yaw"):
            cols[k].append(q[k])
        cols["alive"].append(live)
        if mf is not None:
            px, py = to_px(mf, q["x"], q["y"])
            cols["px"].append(px)
            cols["py"].append(py)
            cols["facing_px"].append(facing_px_deg(mf, q["x"], q["y"], q["yaw"]))
        cols["round"].append((np.searchsorted(rs, t_rep, side="right") - 1).astype(np.int32))
    out = {k: np.concatenate(v) for k, v in cols.items()}
    out["source"] = np.full(out["t_cap"].size, "truth", dtype=object)
    return out


EVENT_COLUMNS = ("kind", "t_rep", "e", "e2", "guid", "guid2", "x", "y", "z", "value_num",
                 "value_str", "detail", "provenance")


def _ev(EV, **kw):
    for k in EVENT_COLUMNS:
        EV[k].append(kw.get(k))


def _events(match, root, rp, ex, rounds, rs, e_of, agent, cen) -> dict:
    """The transitions: rounds, kills, plants, defuses, revives, casts, ults,
    children opening and closing, damage and one-shot effects."""
    EV = defaultdict(list)
    pe = lambda s: e_of.get(("player", s)) if s else None
    for R in rounds:
        _ev(EV, kind="round_start", t_rep=R["t_start"], value_num=R["round"],
            provenance="events.roundStarted")
        if R["t_buy_end"] is not None:
            _ev(EV, kind="buy_end", t_rep=R["t_buy_end"], value_num=R["round"],
                provenance="fields.MulticastSetPhase.NewPhase=4")
        if R["t_end"] is not None:
            _ev(EV, kind="round_end", t_rep=R["t_end"], value_num=R["round"],
                provenance="fields.MulticastSetPhase.NewPhase=5")
    for e in rp.events:
        g = e["group"]
        if g == "characterDeath":
            _ev(EV, kind="kill", t_rep=e["t"], e=pe(e.get("killer")), e2=pe(e.get("victim")),
                guid=e.get("word0"), guid2=e.get("word1"), provenance="events.characterDeath")
        elif g in ("spikePlanted", "spikeDefused", "switchTeams"):
            _ev(EV, kind={"spikePlanted": "plant", "spikeDefused": "defuse",
                          "switchTeams": "switch_teams"}[g], t_rep=e["t"],
                value_str=e.get("metadata") or None, provenance=f"events.{g}")
        elif g == "characterUltimateUsed":
            s = rp.guid_subject.get(e.get("word0"))
            _ev(EV, kind="ult_used", t_rep=e["t"], e=pe(s), guid=e.get("word0"),
                provenance="events.characterUltimateUsed")
    smap = slot_map(cen)
    for c in ex.casts()["casts"]:
        if c["t_ms"] is None:
            continue
        loc = c["location"] or [None, None, None]
        _ev(EV, kind="cast", t_rep=c["t_ms"], e=pe(c["subject"]), x=loc[0], y=loc[1], z=loc[2],
            value_num=c["slot"],
            value_str=smap.get(f"{agent.get(c['subject'])}|{c['slot']}"),
            detail=_json({"round": c["round"], "phase": c["phase"], "cast_time_s": c["cast_time_s"],
                          "first_send_ms": c["first_send_ms"]}),
            provenance="fields.AbilityCastsThisRound (value_str: slot_map folder)")
    for u in ex.ult_intervals():
        _ev(EV, kind="ult_on", t_rep=u["on_ms"], e=pe(u["subject"]),
            provenance="fields.bUltimateActive")
        if u["off_ms"] is not None:
            _ev(EV, kind="ult_off", t_rep=u["off_ms"], e=pe(u["subject"]),
                provenance="fields.bUltimateActive")
    _damage_events(match, root, rp, ex, e_of, EV)
    _effect_events(match, root, rp, ex, e_of, EV)
    return EV


def _subject_of_guid(g, rp, ex, ps_sub) -> str | None:
    if g is None:
        return None
    g = int(g)
    if g in rp.guid_subject:
        return rp.guid_subject[g]
    if g in ps_sub:
        return ps_sub[g]
    s, _p = ex.owner_path(g)
    return s


def _damage_events(match, root, rp, ex, e_of, EV) -> None:
    """`MulticastNotifyDamage_*` calls: the damaged actor (the call's actor),
    the damager (`EventInstigatorPawn`, else `DamagerPlayerState`), the
    causer and the equippable used, amounts, kill flag, origin and impact,
    and each life change (component, delta, result) in `detail`."""
    paths = _net_guid_paths(match, root)
    ps_sub = ex.player_state_subjects()
    F = _read_fields(match, root, prefixes=tuple(p + "." for p in DAMAGE_RPCS))
    for rpc in DAMAGE_RPCS:
        C = rpc_calls(F, rpc)
        if C is None:
            continue
        f = C["fields"]
        n = C["t"].size
        get = lambda k, i: f[k][i] if k in f else None
        for i in range(n):
            victim = int(C["g"][i])
            dmgr = _subject_of_guid(get("EventInstigatorPawn", i) or None, rp, ex, ps_sub) \
                or _subject_of_guid(get("DamagerPlayerState", i) or None, rp, ex, ps_sub)
            vs = rp.guid_subject.get(victim)
            ve = e_of.get(("player", vs)) if vs else e_of.get(("child", victim))
            org = _vec(get("DamageOrigin", i))
            life = []
            for j in range(4):
                comp = get(f"LifeChangeEvents[{j}].ChangedComponent", i)
                if comp is None:
                    continue
                life.append({"component": _leaf(paths.get(int(comp)) or ex.cls.get(int(comp))),
                             "component_guid": int(comp),
                             "delta": get(f"LifeChangeEvents[{j}].DeltaLife", i),
                             "result": get(f"LifeChangeEvents[{j}].LifeResult", i),
                             "alive_after": get(f"LifeChangeEvents[{j}].bAliveAfterChange", i)})
            eq = get("EquippableUsed", i)
            dt = get("DamageType", i)
            _ev(EV, kind="damage", t_rep=float(C["t"][i]),
                e=e_of.get(("player", dmgr)) if dmgr else None, e2=ve,
                guid=get("DamageCauser", i), guid2=victim,
                x=org[0] if org else None, y=org[1] if org else None, z=org[2] if org else None,
                value_num=get("DamageTaken", i),
                value_str=_leaf(paths.get(int(eq)) or ex.cls.get(int(eq))) if eq else None,
                detail=_json({"rpc": rpc, "dealt": get("DamageDealt", i),
                              "equippable_path": paths.get(int(eq)) if eq else None,
                              "by_held_equippable": bool(eq) and str(
                                  paths.get(int(eq)) or "").startswith(HELD_EQUIPPABLE_PATH),
                              "killed": get("bDamageKilledTarget", i),
                              "alive_after": get("bAliveAfterDamage", i),
                              "damage_type": _leaf(paths.get(int(dt))) if dt else None,
                              "impact": get("DamageImpactLocation", i),
                              "wall_penetration": get("bIsWallPenetration", i),
                              "victim_class": _leaf(ex.cls.get(victim)), "life": life}),
                provenance=f"fields.{rpc}")


def _effect_events(match, root, rp, ex, e_of, EV) -> None:
    """One-shot effect RPCs (cosmetic effects, sounds among them): the effect
    container's path, the location, the alliance filter, and the owner: the
    first `ObjectValues` object that resolves to a player (a pawn, a player
    state, or an actor whose `Instigator` chain ends at one), with its tag
    kept in `detail.owner_tag`; the tags' meanings are not documented."""
    paths = _net_guid_paths(match, root)
    ps_sub = ex.player_state_subjects()
    F = _read_fields(match, root, prefixes=tuple(p + "." for p in EFFECT_RPCS))
    for rpc in EFFECT_RPCS:
        C = rpc_calls(F, rpc)
        if C is None:
            continue
        f = C["fields"]
        for i in range(C["t"].size):
            get = lambda k: f[k][i] if k in f else None
            cont = get("EffectContainer")
            ov = get("ObjectValues")
            pawn, s, tag = None, None, None
            try:
                objs = json.loads(ov) if ov else []
            except ValueError:
                objs = []
            for o in objs:
                v = o.get("value")
                if not v:
                    continue
                s = _subject_of_guid(int(v), rp, ex, ps_sub)
                if s is not None:
                    pawn, tag = int(v), o.get("tag")
                    break
            loc = _vec(get("248")) or _vec(get("Translation"))
            _ev(EV, kind="effect", t_rep=float(C["t"][i]),
                e=e_of.get(("player", s)) if s else None, guid=pawn, guid2=int(C["g"][i]),
                x=loc[0] if loc else None, y=loc[1] if loc else None, z=loc[2] if loc else None,
                value_num=get("AllianceFilter"),
                value_str=(paths.get(int(cont)) if cont else None),
                detail=_json({"rpc": rpc, "owner_tag": tag, "object_values": ov,
                              "float_values": get("FloatValues")}),
                provenance=f"fields.{rpc}")


#: State fields read, each a sparse change table: the field name in
#: fields.parquet, the state's name, and how the value is read.
STATE_FIELDS = (("Money", "money", "i64"), ("NumUltimatePoints", "ult_points", "i64"),
                ("CurrentEquippable", "equipped", "class"),
                ("CurrentRegion", "region", "path"), ("bCrouchHeld", "crouch", "bool"),
                ("AuthResourceAmount", "charges", "i64"))


def _state(match, root, rp, ex, e_of) -> dict:
    """Sparse state changes per player: credits, ult points, the equippable
    held, the callout region, crouch, each ability item's charges (`field`
    `charges:<item class>`), the armor item worn (`armor`), and health and
    armor life from each damage call's life changes are in `events`."""
    paths = _net_guid_paths(match, root)
    ps_sub = ex.player_state_subjects()
    F = _read_fields(match, root, names=[f for f, _n, _k in STATE_FIELDS])
    ST = defaultdict(list)

    def put(t, e, field, num, txt, prov):
        ST["t_rep"].append(float(t))
        ST["e"].append(e)
        ST["field"].append(field)
        ST["value_num"].append(num)
        ST["value_str"].append(txt)
        ST["provenance"].append(prov)

    kind = {f: (n, k) for f, n, k in STATE_FIELDS}
    if F is not None:
        for t, g, gp, n, vi, vb in zip(F["t"], F["g"], F["gp"], F["n"], F["i"], F["b"]):
            name, how = kind[n]
            if n == "AuthResourceAmount" and "EquipmentChargeComponent" not in (gp or ""):
                continue        # ammo, not ability charges
            s = _subject_of_guid(int(g), rp, ex, ps_sub)
            if s is None:
                continue
            e = e_of.get(("player", s))
            if how == "i64":
                v = None if vi is None or (isinstance(vi, float) and not np.isfinite(vi)) else int(vi)
                field = name if n != "AuthResourceAmount" else f"charges:{_leaf(ex.cls.get(int(g)))}"
                put(t, e, field, v, None, f"fields.{n}")
            elif how == "bool":
                put(t, e, name, None if vb is None else float(bool(vb)), None, f"fields.{n}")
            else:
                v = None if vi is None or (isinstance(vi, float) and not np.isfinite(vi)) else int(vi)
                txt = None
                if v:
                    txt = _leaf(ex.cls.get(v)) if how == "class" else paths.get(v)
                    if how == "class" and not txt:
                        txt = _leaf(paths.get(v))
                put(t, e, name, v, txt, f"fields.{n}")
    # the armor item a player wears: its actor's life, owned by his pawn
    for i in ex.instances():
        cls = _leaf(i["class_path"])
        if "ArmorItem" not in cls:
            continue
        s, _p = ex.owner_path(i["guid"])
        if s is None:
            continue
        e = e_of.get(("player", s))
        put(i["open_ms"], e, "armor", i["guid"], cls, "actors.open (Owner/Instigator)")
        if i["close_ms"] is not None:
            put(i["close_ms"], e, "armor", None, None, "actors.close")
    return {k: list(v) for k, v in ST.items()}


def _round_end_check(rp: Replay, rounds: list[dict]) -> dict:
    """Phase 5 against each round's last decisive event (the last death, or
    the defuse): how long after it phase 5 arrives."""
    d = np.array([e["t"] for e in rp.group("characterDeath")])
    gaps = []
    for R in rounds:
        if R["t_end"] is None:
            continue
        cand = [R["t_defuse"]] if R["t_defuse"] is not None else []
        if d.size:
            dd = d[(d >= R["t_start"]) & (d <= R["t_end"])]
            if dd.size:
                cand.append(float(dd.max()))
        if cand:
            gaps.append(R["t_end"] - max(cand))
    return {"rounds": len(rounds), "with_phase_5": sum(R["t_end"] is not None for R in rounds),
            "phase5_minus_last_death_or_defuse_ms": sample_stats(gaps, 1)}


# ----------------------------------------------------------------- summary

def layer_summary(match, root, d, E, EV, ex, cen, agent, rs) -> dict:
    """Children per owner and ability, owner-resolution coverage, life spans
    per ability, the cast cross-check, and decoding coverage."""
    kids = [k for k, kind in enumerate(E["kind"]) if kind == "child"]
    per = Counter()
    life = defaultdict(list)
    resolved = Counter()
    paths = Counter()
    for k in kids:
        key = f"{E['agent'][k]}|{E['subject'][k] and E['subject'][k][:8]}|{E['ability'][k] or E['class'][k]}"
        per[key] += 1
        resolved[bool(E["owner_resolved"][k])] += 1
        p = json.loads(E["owner_path"][k])
        paths[" > ".join(x["via"] or "end" for x in p)] += 1
        if E["t_close_rep"][k] is not None:
            life[E["ability"][k] or E["class"][k]].append(
                (E["t_close_rep"][k] - E["t_open_rep"][k]) / 1000.0)
    out = {"children": len(kids),
           "owner_resolved": resolved[True], "owner_unresolved": resolved[False],
           "owner_paths": dict(paths.most_common()),
           "children_by_owner_ability": dict(sorted(per.items())),
           "life_s_by_ability": {k: sample_stats(v, 2) for k, v in sorted(life.items())},
           "casts_vs_children": cast_crosscheck(E, EV, cen, agent),
           "undecoded_children": sum(1 for k in kids if E["undecoded"][k] != "[]")}
    kinds = Counter(EV["kind"])
    out["events"] = dict(kinds)
    eff = Counter(_leaf(v) for k, v in zip(EV["kind"], EV["value_str"]) if k == "effect")
    out["effect_containers_top"] = dict(eff.most_common(40))
    out["effect_owner_resolved"] = sum(1 for k, e in zip(EV["kind"], EV["e"])
                                       if k == "effect" and e is not None)
    out["damage_damager_resolved"] = sum(1 for k, e in zip(EV["kind"], EV["e"])
                                         if k == "damage" and e is not None)
    return out


def cast_crosscheck(E, EV, cen, agent) -> dict:
    """Per player and ability folder: the cast records (`AbilityCastsThisRound`
    through `slot_map`) against the root children (no parent, no
    predecessor) of each class in that folder, per round.

    Each (player, folder) gets one verdict: `class_equals` where one class's
    count equals the casts in every round (that class is one per cast),
    `classes_sum_equals` where the classes' sum does (a cast opens one of
    several classes, as a thrown and an underhand flash), `no_cast_records`
    where the folder has children and no mapped cast, else `disagree`, with
    the rounds that differ. A slot byte `slot_map` cannot map is counted
    apart, never guessed."""
    casts = Counter()
    unmapped = Counter()
    for k, kind in enumerate(EV["kind"]):
        if kind != "cast":
            continue
        det = json.loads(EV["detail"][k])
        if EV["value_str"][k] is None:
            unmapped[(EV["e"][k], int(EV["value_num"][k]))] += 1
            continue
        casts[(EV["e"][k], EV["value_str"][k], det["round"])] += 1
    sub_e = {E["subject"][k]: k for k, kind in enumerate(E["kind"]) if kind == "player"}
    roots = Counter()
    for k, kind in enumerate(E["kind"]):
        if kind != "child" or not E["subject"][k] or not E["folder"][k]:
            continue
        if E["parent_guid"][k] is not None or E["predecessor_guid"][k] is not None:
            continue
        roots[(sub_e[E["subject"][k]], E["folder"][k], E["class"][k], E["round"][k])] += 1
    out = {"rows": [], "casts_slot_unmapped": {
        f"{E['agent'][e]}|{(E['subject'][e] or '')[:8]}|slot{s}": n
        for (e, s), n in sorted(unmapped.items(), key=str)}}
    keys = sorted({(e, f) for (e, f, _r) in casts} | {(e, f) for (e, f, _c, _r) in roots}, key=str)
    for e, f in keys:
        rounds = sorted({r for (ee, ff, r) in casts if (ee, ff) == (e, f)}
                        | {r for (ee, ff, _c, r) in roots if (ee, ff) == (e, f)}, key=str)
        cls = sorted({c for (ee, ff, c, _r) in roots if (ee, ff) == (e, f)})
        per_c = {c: [roots[(e, f, c, r)] for r in rounds] for c in cls}
        cr = [casts[(e, f, r)] for r in rounds]
        summed = [sum(per_c[c][i] for c in cls) for i in range(len(rounds))]
        if not any(cr):
            verdict = "no_cast_records"
        elif any(per_c[c] == cr for c in cls):
            verdict = "class_equals"
        elif summed == cr:
            verdict = "classes_sum_equals"
        else:
            verdict = "disagree"
        row = {"player": f"{E['agent'][e]}|{(E['subject'][e] or '')[:8]}", "folder": f,
               "verdict": verdict, "casts": sum(cr),
               "children": {c: sum(v) for c, v in per_c.items()}}
        if verdict == "disagree":
            best = min(cls, key=lambda c: sum(abs(a - b) for a, b in zip(per_c[c], cr))) if cls else None
            row["rounds_differing"] = [
                {"round": r, "casts": cr[i], "children": per_c[best][i] if best else 0}
                for i, r in enumerate(rounds) if best is None or per_c[best][i] != cr[i]]
            row["closest_class"] = best
        out["rows"].append(row)
    out["verdicts"] = dict(Counter(r["verdict"] for r in out["rows"]))
    return out


# ----------------------------------------------------------------- read API

class Layer:
    """One match's stored layer: `head` (layer.json) and the tables as dicts
    of numpy arrays (`entities`, `ticks`, `frames` where a capture exists,
    `events`, `state`, `rounds`, `lives`). `clock` is `capture` or `replay`
    for every time argument; `capture` needs a fitted offset (`head['a_ms']`)."""

    def __init__(self, match: str, root=DEFAULT_STORE):
        import pyarrow.parquet as pq
        self.match = match
        self.dir = layer_dir(match, root)
        self.head = json.loads((self.dir / "layer.json").read_text(encoding="utf-8"))
        self.a_ms = self.head.get("a_ms")
        self.tables = {}
        for name in TABLES:
            p = self.dir / f"{name}.parquet"
            if p.is_file():
                t = pq.read_table(p)
                self.tables[name] = {c: t[c].to_numpy(zero_copy_only=False) for c in t.column_names}
        T = self.tables["ticks"]
        o = np.lexsort((T["t_rep"], T["e"]))
        self.tables["ticks"] = {k: v[o] for k, v in T.items()}
        e = self.tables["ticks"]["e"]
        bounds = np.flatnonzero(np.r_[True, e[1:] != e[:-1], True])
        self._span = {int(e[bounds[i]]): (bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)}

    def __getattr__(self, name):
        if name in TABLES and name in self.__dict__.get("tables", {}):
            return self.tables[name]
        raise AttributeError(name)

    def _rep(self, t, clock: str):
        t = np.asarray(t, float)
        if clock == "replay":
            return t
        if self.a_ms is None:
            raise ValueError(f"{self.match}: no capture clock (layer head a_ms is null)")
        return t - self.a_ms

    def rows(self, name: str) -> int:
        """Row count of a table; each table is a dict of numpy columns, so
        `len(L.ticks)` counts columns."""
        T = self.tables.get(name)
        return 0 if not T else int(next(iter(T.values())).size)

    def players(self) -> list[int]:
        k = self.tables["entities"]["kind"]
        return [int(i) for i in np.flatnonzero(k == "player")]

    def entity(self, e: int) -> dict:
        return {c: v[e] for c, v in self.tables["entities"].items()}

    def track(self, e: int) -> dict:
        """Every tick of entity `e`, time-ordered."""
        a, b = self._span.get(int(e), (0, 0))
        return {k: v[a:b] for k, v in self.tables["ticks"].items()}

    def state_at(self, t: float, clock: str = "capture", entities=None) -> list[dict]:
        """Each entity's state at one time. Position, z, pitch, px and py are
        linear between the bracketing ticks when they lie within
        `MAX_GAP_MS` (`position_basis` "interpolated"); yaw and facing come
        from the nearer tick. Across a longer gap, or after an entity's last
        tick, the last tick at or before `t` holds (`position_basis` "held",
        with `held_from_tick_ms`); before an entity's first tick the position
        is null (`position_basis` "before_first_tick"). A player's `alive`
        comes from `lives` (revives included), so a dead player carries his
        last position with alive False; a child is listed only while open.
        Players also carry the latest sparse `state` values at or before `t`
        as `state:<field>`."""
        tr = float(self._rep([t], clock)[0])
        E = self.tables["entities"]
        out = []
        ids = range(len(E["entity_id"])) if entities is None else entities
        S = self.tables.get("state")
        cols = ("x", "y", "z", "yaw", "pitch", "px", "py", "facing_px")

        def num(v):
            return None if v is None or not np.isfinite(v) else float(v)

        for e in ids:
            player = E["kind"][e] == "player"
            if not player:
                t0, t1 = E["t_open_rep"][e], E["t_close_rep"][e]
                if not (t0 <= tr and (t1 is None or not np.isfinite(t1) or tr < t1)):
                    continue
            k = self.track(e)
            row = {"e": int(e), "entity_id": E["entity_id"][e], "kind": E["kind"][e],
                   "t_rep": tr, "source": "truth"}
            row.update({c: None for c in cols})
            n = k["t_rep"].size
            i = int(np.searchsorted(k["t_rep"], tr, side="right"))  # ticks <= tr: [0, i)
            if n and i == 0:
                row["position_basis"] = "before_first_tick"
            elif n:
                i0 = i - 1
                t0 = k["t_rep"][i0]
                if t0 == tr or (i < n and k["t_rep"][i] - t0 <= MAX_GAP_MS):
                    i1 = i0 if t0 == tr else i
                    t1 = k["t_rep"][i1]
                    w = 0.0 if t1 == t0 else (tr - t0) / (t1 - t0)
                    for c in ("x", "y", "z", "pitch", "px", "py"):
                        a0, a1 = k[c][i0], k[c][i1]
                        row[c] = None if a0 is None or a1 is None else num(a0 * (1 - w) + a1 * w)
                    near = i0 if w < 0.5 else i1
                    for c in ("yaw", "facing_px"):
                        row[c] = num(k[c][near])
                    row["position_basis"] = "interpolated"
                else:
                    for c in cols:
                        row[c] = num(k[c][i0])
                    row["position_basis"] = "held"
                    row["held_from_tick_ms"] = float(t0)
            else:
                row["position_basis"] = "no_ticks"
            row["alive"] = bool(self.alive_at(e, tr, "replay")) if player else True
            if E["kind"][e] == "player" and S is not None:
                m = (S["e"] == e) & (S["t_rep"] <= tr)
                for f in np.unique(S["field"][m]):
                    j = np.flatnonzero(m & (S["field"] == f))[-1]
                    row[f"state:{f}"] = (S["value_str"][j] if S["value_str"][j] is not None
                                         else S["value_num"][j])
            out.append(row)
        return out

    def alive_at(self, e: int, t, clock: str = "capture"):
        L = self.tables["lives"]
        tr = self._rep(t, clock)
        m = L["e"] == e
        out = np.zeros(np.shape(tr), bool)
        for a, b in zip(L["t_open"][m], L["t_close"][m]):
            out |= (tr >= a) & (tr < b)
        return out

    def round_at(self, t, clock: str = "capture") -> int | None:
        R = self.tables["rounds"]
        tr = float(self._rep([t], clock)[0])
        k = int(np.searchsorted(R["t_start"], tr, side="right")) - 1
        return None if k < 0 else int(R["round"][k])

    def intervals(self, kind: str) -> list[dict]:
        """`lives` (per player per round), `rounds` (start..end), `buy`
        (start..buy end), or `children` (open..close), on both clocks."""
        if kind == "lives":
            L = self.tables["lives"]
            return [{"e": int(L["e"][i]), "round": int(L["round"][i]), "t_rep": (L["t_open"][i], L["t_close"][i]),
                     "open": L["open_basis"][i], "close": L["close_basis"][i]}
                    for i in range(L["e"].size)]
        if kind in ("rounds", "buy"):
            R = self.tables["rounds"]
            hi = R["t_end"] if kind == "rounds" else R["t_buy_end"]
            return [{"round": int(R["round"][i]), "t_rep": (R["t_start"][i], hi[i])}
                    for i in range(R["round"].size)]
        if kind == "children":
            E = self.tables["entities"]
            return [{"e": int(k), "ability": E["ability"][k], "t_rep": (E["t_open_rep"][k], E["t_close_rep"][k])}
                    for k in np.flatnonzero(E["kind"] == "child")]
        raise ValueError(kind)

    def events_of(self, kind: str) -> dict:
        Ev = self.tables["events"]
        m = Ev["kind"] == kind
        return {k: v[m] for k, v in Ev.items()}


def load(key: str, root=DEFAULT_STORE) -> Layer:
    """The stored layer of a match id, prefix or capture session."""
    match, _sid = resolve(key, root)
    if match is None:
        raise FileNotFoundError(f"no parsed replay for {key}")
    return Layer(match, root)


# ----------------------------------------------------------------- command

def command(keys: list[str], *, all_: bool = False, status_only: bool = False,
            geometry: Path | None = None, root=DEFAULT_STORE) -> int:
    """`reticle replay-layer`: build each named layer (all parsed replays with
    `--all`), or with `--status` say which are current, stale or absent."""
    matches = parsed_matches(root) if all_ else []
    for k in keys:
        m, _s = resolve(k, root)
        if m is None:
            print(f"{k}: no parsed replay")
            continue
        matches.append(m)
    if not matches and status_only:
        matches = parsed_matches(root)
    rc = 0
    for m in dict.fromkeys(matches):
        if status_only:
            st = status(m, root)
            print(f"{m}  {st['state']}" + (f"  moved: {', '.join(st['moved'])}" if st["moved"] else ""))
            continue
        h = build(m, root, geometry)
        if "refused" in h:
            print(f"{m}: refused {h['refused']}")
            rc = 1
            continue
        if h["held_out"]:
            print(f"{m}: built (held out: no statistics)")
            continue
        c = h.get("capture") or {}
        s = h.get("summary") or {}
        print(f"{m}  session {h['session']}  a_ms {h['a_ms']}  tables {h['tables']}  "
              f"capture {c.get('refused') or 'aligned'}  children {s.get('children')} "
              f"(owner resolved {s.get('owner_resolved')})")
    return rc
