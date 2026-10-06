"""Ability actors in a replay: which class is which ability, and who cast it.

[owns:replay-ability-actors]

Every non-player actor the server spawned (projectiles, placed game objects,
pawns, ground patches, ult orbs, the planted spike) with its class, spawn
point, rotation, open and close times and its `Owner`/`Instigator`
references, and the server's cast records (`AbilityCastsThisRound`) and ult
state (`bUltimateActive`). `prototypes/replay_abilities.py` scored the stored
ability streams against these until 2026-10-05; the reading and the mapping
moved here when the replay layer (`replay_layer`) joined the pipeline, and the
prototype imports them.

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

The cast records' `Slot` byte is not documented; `class_census` derives its
meaning per agent by pairing each cast with the first world actor of the same
player that opens after it (`slot_map`), and reports the table rather than
assuming it.

Facts: [domain:replay/vrf-ability-actors], [domain:replay/vrf-cast-records],
[domain:replay/vrf-ult-active].
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .replay_source import Reference, Replay, sample_stats, parsed_dir
from .store import DEFAULT_STORE

REPLAY_ACTORS_VERSION = "replay-actors-0.1.0"
GAME_BUILD = "release-13.06-shipping-18-5590001"


def ability_data_dir(root=DEFAULT_STORE) -> Path:
    """The extracted game files' character folders for `GAME_BUILD`."""
    return (Path(root) / "reference" / "game-files" / GAME_BUILD / "ability-data"
            / "ShooterGame" / "Content" / "Characters")


#: The cast-record array and the fields of one record (vrfkit names carry a
#: Blueprint suffix after the field's own name).
CAST_ARRAY = "AbilityCastsThisRound"
CAST_FIELDS = ("Player", "Slot", "Round", "RoundPhase", "CastTime", "CastLocation")
#: A cast pairs with the first world actor of the same player that opens in
#: [cast - PRE, cast + POST] ms.
PAIR_PRE_MS, PAIR_POST_MS = 250.0, 2000.0
#: Classes outside `/Game/Characters` that carry minimap truth, named by path.
NON_CHARACTER = {"/Game/GameObjects/CollectibleOrbs/UltPointOrb": "ult orb",
                 "/Game/GameModes/Bomb/TimedBomb": "planted spike",
                 "/Game/Equippables/Bomb/BombEquippable": "spike item (carried or dropped)"}
ROLE_PREFIX = (("Projectile_", "projectile"), ("GameObject_", "game object"),
               ("Pawn_", "pawn"), ("Patch_", "ground patch"), ("Ability_", "ability item"),
               ("Equippable_", "equippable"), ("Gun_", "equippable"), ("Actor_", "actor"))
_FOLDER = re.compile(r"^/Game/Characters/([^/]+)/S0/(Ability_[^/]+)/")
#: The most references `owner_path` follows from an actor to a player pawn.
OWNER_HOPS = 4


def _leaf(cp: str | None) -> str:
    return (cp or "").rsplit(".", 1)[-1]


def _role(short: str) -> str:
    if short.endswith("_PC_C"):
        return "character"
    for p, r in ROLE_PREFIX:
        if short.startswith(p):
            return r
    return "other"


# ----------------------------------------------------------------- game files

_UI_CACHE: dict = {}


def ability_display(code: str, folder: str, root=DEFAULT_STORE) -> dict:
    """The game files' display name for one ability folder (`UIData*` under it)."""
    key = (str(root), code, folder)
    if key in _UI_CACHE:
        return _UI_CACHE[key]
    base = ability_data_dir(root)
    d = base / code / "S0" / folder
    names, files = [], []
    for f in sorted(d.rglob("UIData*.json")) if d.is_dir() else []:
        files.append(f.relative_to(base).as_posix())
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        stack = [o]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                v = x.get("DisplayName")
                if isinstance(v, dict) and v.get("SourceString"):
                    names.append(v["SourceString"].strip())
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    # the ability's own name is its title-case DisplayName (the kit also
    # carries an upper-case copy on some agents)
    uniq = sorted(set(names), key=lambda s: (s.isupper(), s))
    out = {"display": uniq[0] if uniq else None, "names": uniq, "uidata": files}
    _UI_CACHE[key] = out
    return out


# ----------------------------------------------------------------- export

class Export:
    """One vrfkit parse: the replay (players, events) plus its ability actors,
    their references and movement, the cast records and the ult state."""

    FIELD_NAMES = ["Owner", "Instigator", "ReplicatedMovement", "Subject",
                   "bUltimateActive", "MulticastSetPhase.NewPhase"]

    def __init__(self, match: str, light: bool = False, rp=None, root=DEFAULT_STORE):
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        self.match = match
        self.root = Path(root)
        self.dir = parsed_dir(match, root)
        ex = self.dir / "export"
        self.manifest = json.loads((ex / "manifest.json").read_text(encoding="utf-8"))
        A = pq.read_table(ex / "actors.parquet")
        self.a_t = A["time_ms"].to_numpy().astype(np.float64)
        self.a_g = A["actor_net_guid"].to_numpy().astype(np.int64)
        self.a_ev = np.array(A["event"].to_pylist(), dtype=object)
        cp = pc.cast(A["class_path"], pa.string()).to_pylist()
        self.a_cp = np.array([c or "" for c in cp], dtype=object)
        self.a_xyz = np.stack([A[k].to_numpy(zero_copy_only=False).astype(np.float64)
                               for k in ("spawn_x", "spawn_y", "spawn_z")], axis=1)
        self.a_yaw = A["spawn_yaw"].to_numpy(zero_copy_only=False).astype(np.float64)
        op = self.a_ev == "open"
        self.cls = dict(zip(self.a_g[op].tolist(), self.a_cp[op].tolist()))
        if light:
            return
        self.rp = rp if rp is not None else Replay(match, root)
        F = pq.read_table(ex / "fields.parquet",
                          columns=["time_ms", "actor_net_guid", "group_path", "field_name",
                                   "value_i64", "value_f64", "value_bool", "value_str"])
        fn = pc.cast(F["field_name"], pa.string())
        keep = pc.or_(pc.is_in(fn, value_set=pa.array(self.FIELD_NAMES)),
                      pc.starts_with(fn, CAST_ARRAY + "["))
        F = F.filter(keep)
        self.f_t = F["time_ms"].to_numpy().astype(np.float64)
        self.f_g = F["actor_net_guid"].to_numpy().astype(np.int64)
        self.f_gp = np.array(pc.cast(F["group_path"], pa.string()).to_pylist(), dtype=object)
        self.f_n = np.array(pc.cast(F["field_name"], pa.string()).to_pylist(), dtype=object)
        self.f_i = F["value_i64"].to_numpy(zero_copy_only=False)
        self.f_f = F["value_f64"].to_numpy(zero_copy_only=False)
        self.f_b = np.array(F["value_bool"].to_pylist(), dtype=object)
        self.f_s = np.array(pc.cast(F["value_str"], pa.string()).to_pylist(), dtype=object)
        self.f_has_s = np.array([s is not None for s in self.f_s], bool)
        self._refs = {k: self._ref(k) for k in ("Owner", "Instigator")}

    # -- references
    def _ref(self, name: str) -> dict:
        """actor guid -> its first non-null `name` reference on its own class group."""
        m = self.f_n == name
        out = {}
        for g, gp, v in zip(self.f_g[m], self.f_gp[m], self.f_i[m]):
            if v is None or not np.isfinite(v) or int(v) == 0:
                continue
            g = int(g)
            if g in out:
                continue
            own = _leaf(self.cls.get(g)).removesuffix("_C")
            if own and own in (gp or ""):
                out[g] = int(v)
        return out

    def owner_path(self, g: int, hops: int = OWNER_HOPS) -> tuple[str | None, list[dict]]:
        """Follow `Instigator` (then `Owner`) from actor `g` to a player pawn.

        Returns the player's subject (or None) and the path walked: one
        `{guid, class, via}` per actor, `via` naming the reference that led to
        the NEXT actor (`Instigator` or `Owner`), None on the last. A Spycam's
        tracking dart reaches its Cypher through the camera pawn; each of two
        players of one agent is reached through his own pawn's guid, never
        through an agent name."""
        path = []
        for _ in range(hops):
            s = self.rp.guid_subject.get(g)
            step = {"guid": int(g), "class": _leaf(self.cls.get(g)), "via": None}
            path.append(step)
            if s is not None:
                return s, path
            inst = self._refs["Instigator"].get(g)
            nxt = inst or self._refs["Owner"].get(g)
            if nxt is None:
                return None, path
            step["via"] = "Instigator" if inst else "Owner"
            g = nxt
        return None, path

    def owner_subject(self, g: int, hops: int = OWNER_HOPS) -> tuple[str | None, list[str]]:
        """`owner_path`'s subject and the class chain walked."""
        s, path = self.owner_path(g, hops)
        return s, [p["class"] for p in path]

    # -- lifetimes
    def instances(self, class_short: str | None = None, path_prefix: str | None = None):
        """One row per open: guid, open/close ms, spawn xyz and yaw, class path."""
        op = np.flatnonzero(self.a_ev == "open")
        if class_short is not None:
            op = op[[_leaf(self.a_cp[i]) == class_short for i in op]]
        if path_prefix is not None:
            op = op[[self.a_cp[i].startswith(path_prefix) for i in op]]
        cl = np.flatnonzero(self.a_ev == "close")
        key = self.a_g[cl] * 10**10 + self.a_t[cl].astype(np.int64)
        o = np.argsort(key)
        ck, ct = key[o], self.a_t[cl][o]
        rows = []
        for i in op:
            g, t = int(self.a_g[i]), self.a_t[i]
            k = np.searchsorted(ck, g * 10**10 + int(t), side="left")
            close = float(ct[k]) if k < ck.size and ck[k] // 10**10 == g else None
            rows.append({"guid": g, "open_ms": float(t), "close_ms": close,
                         "xyz": self.a_xyz[i].tolist(), "yaw": float(self.a_yaw[i]),
                         "class_path": self.a_cp[i]})
        return rows

    def rep_movement(self, g: int):
        """(t, x, y, z) of one actor's `ReplicatedMovement` rows, world units.

        A row vrfkit left without a decoded value (`value_str` null, as some of
        60c7f1e0's are) carries no location and is skipped."""
        m = (self.f_g == g) & (self.f_n == "ReplicatedMovement")
        m &= self.f_has_s
        if not m.any():
            return None
        loc = [json.loads(s)["location"] for s in self.f_s[m]]
        return (self.f_t[m], np.array([p["x"] for p in loc], float),
                np.array([p["y"] for p in loc], float), np.array([p["z"] for p in loc], float))

    def pawn_track(self, g: int):
        """(t, x, y) of a non-player pawn's movement rows (park slot removed)."""
        R = self.rp.raw
        m = (R["g"] == g) & ~R["park"]
        o = np.argsort(R["t"][m], kind="stable")
        return R["t"][m][o], R["x"][m][o], R["y"][m][o]

    # -- rounds, casts, ults
    def buy_end_ms(self) -> np.ndarray:
        """`MulticastSetPhase.NewPhase` == 4 (`ClientBuyPhaseEnd`), in order: the
        epoch of `CastTime` (vrfkit docs/DATA.md, "CastTime is not measured from
        roundStarted")."""
        m = (self.f_n == "MulticastSetPhase.NewPhase") & (self.f_i == 4)
        return np.unique(self.f_t[m])

    def casts(self) -> dict:
        """Deduplicated cast records: subject, slot byte, round, phase, replay ms.

        The array replicates by delta: a snapshot carries only the fields of an
        element that changed. Each element's state (per replicator actor and
        index) is carried forward, and a record is read after every update of
        the time step in which its `CastTime` arrives."""
        m = np.flatnonzero([n.startswith(CAST_ARRAY + "[") for n in self.f_n])
        m = m[np.argsort(self.f_t[m], kind="stable")]
        upd = []
        for i in m:
            head, _, field = self.f_n[i].partition("].")
            if not field or "." in field:
                continue      # the Effects[...] children
            name = field.split("_", 1)[0]
            if name not in CAST_FIELDS:
                continue
            v = (self.f_s[i] if name in ("Player", "CastLocation") else
                 None if self.f_f[i] is None else float(self.f_f[i]) if name == "CastTime" else
                 None if self.f_i[i] is None else int(self.f_i[i]))
            upd.append((float(self.f_t[i]), (int(self.f_g[i]), head), name, v))
        state = defaultdict(dict)
        reads = []
        j = 0
        while j < len(upd):
            t = upd[j][0]
            fresh = set()
            while j < len(upd) and upd[j][0] == t:
                _t, k, name, v = upd[j]
                state[k][name] = v
                if name == "CastTime":
                    fresh.add(k)
                j += 1
            reads.extend((t, dict(state[k])) for k in fresh)
        be = self.buy_end_ms()
        seen, out, partial = set(), [], 0
        for t, r in reads:
            if not all(r.get(k) is not None for k in ("Player", "Slot", "Round", "CastTime")):
                partial += 1
                continue
            key = (r["Player"], int(r["Round"]), int(r["Slot"]), round(float(r["CastTime"]), 3))
            if key in seen:
                continue
            seen.add(key)
            rd = int(r["Round"])
            t_abs = be[rd] + 1000.0 * float(r["CastTime"]) if rd < be.size else None
            loc = None
            if r.get("CastLocation"):
                loc = [float(v) for v in r["CastLocation"].strip("()").split(",")]
            out.append({"subject": r["Player"], "slot": int(r["Slot"]), "round": rd,
                        "phase": None if r.get("RoundPhase") is None else int(r["RoundPhase"]),
                        "cast_time_s": float(r["CastTime"]), "t_ms": t_abs,
                        "first_send_ms": float(t), "location": loc})
        return {"casts": out, "partial_reads": partial, "buy_ends": int(be.size)}

    def player_state_subjects(self) -> dict:
        """Player-state actor guid -> the subject its `Subject` field names."""
        m = self.f_n == "Subject"
        ps_sub = {}
        for g, s, gp in zip(self.f_g[m], self.f_s[m], self.f_gp[m]):
            if s and "PlayerState" in (gp or ""):
                ps_sub.setdefault(int(g), s)
        return ps_sub

    def ult_intervals(self) -> list[dict]:
        """`bUltimateActive` false-to-true transitions per player state, with the
        following true-to-false; the player state's `Subject` names the player."""
        ps_sub = self.player_state_subjects()
        m = self.f_n == "bUltimateActive"
        rows = sorted(zip(self.f_g[m].tolist(), self.f_t[m].tolist(), self.f_b[m].tolist()))
        out, state = [], {}
        for g, t, b in rows:
            prev = state.get(g, (False, None))
            if b and not prev[0]:
                state[g] = (True, t)
            elif not b and prev[0]:
                out.append({"subject": ps_sub.get(g), "on_ms": prev[1], "off_ms": t})
                state[g] = (False, None)
        for g, (on, t) in state.items():
            if on:
                out.append({"subject": ps_sub.get(g), "on_ms": t, "off_ms": None})
        return sorted(out, key=lambda r: r["on_ms"])


# ----------------------------------------------------------------- census

def class_census(match: str, ex: Export | None = None) -> dict:
    ex = ex if ex is not None else Export(match)
    rp = ex.rp
    ref = Reference(ex.root / "external" / "valorant-api", fetch=False)
    agent = {s: ref.agent(c) for s, c in rp.loadouts().items()}
    player_guids = set(rp.guid_subject)
    # movement rows of non-player pawns, by class
    R = rp.raw
    u, n = np.unique(R["g"], return_counts=True)
    np_rows = {int(g): int(k) for g, k in zip(u, n) if int(g) not in player_guids}
    rm_rows = Counter(int(g) for g in ex.f_g[ex.f_n == "ReplicatedMovement"])
    ops = Counter(_leaf(c) for c, e in zip(ex.a_cp, ex.a_ev) if e == "open")
    classes = []
    by_class = defaultdict(list)
    for r in ex.instances():
        by_class[r["class_path"]].append(r)
    for cp, inst in sorted(by_class.items(), key=lambda kv: _leaf(kv[0])):
        short = _leaf(cp)
        if not cp or int(next(iter([inst[0]["guid"]]))) in player_guids:
            continue
        path = cp.rsplit(".", 1)[0]
        f = _FOLDER.match(cp)
        other = (not f and path not in NON_CHARACTER
                 and (path.startswith("/Game/Characters/") or "_GEN_VARIABLE" in cp))
        if not f and path not in NON_CHARACTER and not other:
            continue
        guids = [r["guid"] for r in inst]
        life = [r["close_ms"] - r["open_ms"] for r in inst if r["close_ms"] is not None]
        owners = Counter()
        chains = Counter()
        for g in guids:
            s, ch = ex.owner_subject(g)
            owners[(agent.get(s) if s else None, ch[-1] if ch else None)] += 1
            chains[" > ".join(ch)] += 1
        row = {"class": short, "class_path": cp, "role": _role(short), "opens": len(inst),
               "closes": len(life), "lifetime_s": sample_stats(np.array(life) / 1000.0),
               "spawn_xyz": int(sum(np.isfinite(r["xyz"][0]) for r in inst)),
               "spawn_yaw": int(sum(np.isfinite(r["yaw"]) for r in inst)),
               "rep_movement_rows": int(sum(rm_rows.get(g, 0) for g in guids)),
               "movement_rows": int(sum(np_rows.get(g, 0) for g in guids)),
               "instigator_resolved": int(sum(v for (a, _c), v in owners.items() if a)),
               "owner_agents": {f"{a}|{c}": v for (a, c), v in owners.items()},
               "owner_chains": dict(chains.most_common(3))}
        own = ex.f_n[np.isin(ex.f_g, guids)]
        row["typed_fields_read"] = sorted(set(own.tolist()))
        if f:
            code, folder = f.group(1), f.group(2)
            ui = ability_display(code, folder, ex.root)
            pcs = {c for (a, c) in owners if c}
            agents = {a for (a, c) in owners if a}
            row.update({"code": code, "folder": folder, "ability": ui["display"],
                        "uidata": ui["uidata"][:2]})
            if row["role"] in ("ability item", "equippable"):
                row["mapped"] = None
                row["unmapped_reason"] = "inventory item: no world position"
            elif ui["display"] is None:
                row["mapped"] = None
                row["unmapped_reason"] = "no UIData display name in the folder's game files"
            elif pcs != {f"{code}_PC_C"} or len(agents) != 1 or None in agents:
                row["mapped"] = None
                row["unmapped_reason"] = (f"instigator chain ends at {sorted(map(str, pcs))}, "
                                          f"agents {sorted(map(str, agents))}")
            else:
                row["mapped"] = f"{next(iter(agents))}: {ui['display']}"
        elif other:
            row["mapped"] = None
            row["code"] = None
            row["unmapped_reason"] = ("character-folder actor outside an ability folder"
                                      if path.startswith("/Game/Characters/") else
                                      "child actor without a class path in the game index")
        else:
            row["mapped"] = NON_CHARACTER[path]
            row["code"] = None
        classes.append(row)
    # cast records: Slot byte per agent against the folder of the first actor after it
    C = ex.casts()
    world = [r for r in classes if r.get("code") and r["role"] in
             ("projectile", "game object", "pawn", "ground patch")]
    opens = []
    for r in world:
        for i in by_class[r["class_path"]]:
            s, _ = ex.owner_subject(i["guid"])
            opens.append((i["open_ms"], s, r["folder"], r["class"]))
    opens.sort()
    o_t = np.array([o[0] for o in opens])
    slot_tab = defaultdict(Counter)
    lag = defaultdict(list)
    unpaired = defaultdict(list)
    for c in C["casts"]:
        if c["t_ms"] is None:
            continue
        lo = np.searchsorted(o_t, c["t_ms"] - PAIR_PRE_MS)
        hi = np.searchsorted(o_t, c["t_ms"] + PAIR_POST_MS, side="right")
        hit = next((opens[k] for k in range(lo, hi) if opens[k][1] == c["subject"]), None)
        ag = agent.get(c["subject"])
        slot_tab[(ag, c["slot"])][hit[2] if hit else "none"] += 1
        if hit:
            lag[(ag, c["slot"], hit[3])].append(hit[0] - c["t_ms"])
        else:
            # the nearest open of the same player within 60 s, any class: says
            # whether an unpaired cast has a late or early actor or none
            lo = np.searchsorted(o_t, c["t_ms"] - 60000.0)
            hi = np.searchsorted(o_t, c["t_ms"] + 60000.0, side="right")
            cand = [(abs(opens[k][0] - c["t_ms"]), opens[k][0] - c["t_ms"], opens[k][3])
                    for k in range(lo, hi) if opens[k][1] == c["subject"]]
            if cand:
                _d, dt, k3 = min(cand)
                unpaired[(ag, c["slot"], k3)].append(dt)
            else:
                unpaired[(ag, c["slot"], "none_within_60s")].append(np.nan)
    be = ex.buy_end_ms()
    rs = rp.round_starts()
    in_round = [bool(c["t_ms"] is not None and rs.size and
                     rs[max(np.searchsorted(rs, c["t_ms"], side="right") - 1, 0)] <= c["t_ms"])
                for c in C["casts"]]
    ults = ex.ult_intervals()
    ev = [e for e in rp.events if e["group"] == "characterUltimateUsed"]
    ev_t = np.array([e["t"] for e in ev])
    on_t = np.array([u["on_ms"] for u in ults])
    near = (np.min(np.abs(ev_t[:, None] - on_t[None, :]), axis=1)
            if ev_t.size and on_t.size else np.array([]))
    out = {"match": match, "replay_actors_version": REPLAY_ACTORS_VERSION,
           "game_files": GAME_BUILD, "agents": sorted(Counter(agent.values()).items()),
           "classes": classes,
           "non_player_movement": {"rows": int(sum(np_rows.values())),
                                   "pawns": len(np_rows),
                                   "by_class": dict(Counter(
                                       {_leaf(ex.cls.get(g)): 0 for g in np_rows}))},
           "casts": {"records": len(C["casts"]), "partial_reads": C["partial_reads"],
                     "buy_ends": C["buy_ends"], "rounds": int(rs.size),
                     "after_round_start": int(sum(in_round)),
                     "by_agent_slot": {f"{a}|{s}": dict(v) for (a, s), v in
                                       sorted(slot_tab.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))},
                     "open_after_cast_ms": {f"{a}|{s}|{k}": sample_stats(v, 1) for (a, s, k), v in
                                            sorted(lag.items(), key=lambda kv: str(kv[0]))},
                     "unpaired_nearest_open_ms": {f"{a}|{s}|{k}": {"n": len(v), **(sample_stats(v, 1) or {})}
                                                  for (a, s, k), v in
                                                  sorted(unpaired.items(), key=lambda kv: str(kv[0]))}},
           "ults": {"transitions": len(ults), "events": int(ev_t.size),
                    "events_within_100ms_of_transition": int(np.sum(near <= 100)) if near.size else 0,
                    "by_agent": dict(Counter(agent.get(u["subject"]) for u in ults)),
                    "duration_s": sample_stats([(u["off_ms"] - u["on_ms"]) / 1000.0 for u in ults
                                          if u["off_ms"] is not None])}}
    for g in np_rows:
        out["non_player_movement"]["by_class"][_leaf(ex.cls.get(g))] += np_rows[g]
    out["handoff"] = handoff(ex, classes, by_class)
    out["plant_events"] = len(rp.group("spikePlanted"))
    out["mapped_classes"] = sum(1 for r in classes if r["mapped"])
    out["unmapped_classes"] = [(r["class"], r.get("unmapped_reason")) for r in classes
                               if not r["mapped"]]
    return out


#: A slot byte maps to a folder only when at least this many of its casts, and
#: this share of all its casts, pair with that folder's first world actor.
SLOT_MIN_PAIRED, SLOT_MIN_SHARE = 3, 0.9


def handoff_pairs(ex: Export, classes: list, by_class: dict) -> dict:
    """Projectile -> game object of one ability: which projectile, if any, each
    game object of a mapped class succeeds.

    Each game-object instance takes the latest projectile of the same player
    and folder that opened before it and had not closed more than 1 s before
    it. Per object class: the projectile classes it may come from, its
    instance count and one row per paired instance, with the object's open
    minus the projectile's close (ms; negative while the projectile still
    exists) and the distance from the projectile's last replicated location
    at or before the open to the object's spawn (world cm, None without one)."""
    out = {}
    proj = [r for r in classes if r["role"] == "projectile" and r.get("mapped")]
    objs = [r for r in classes if r["role"] == "game object" and r.get("mapped")]
    for o in objs:
        ps = [p for p in proj if p["code"] == o["code"] and p["folder"] == o["folder"]]
        if not ps:
            continue
        flights = []
        for p in ps:
            for i in by_class[p["class_path"]]:
                s, _ = ex.owner_subject(i["guid"])
                flights.append((i["open_ms"], i["close_ms"] if i["close_ms"] is not None else np.inf,
                                s, ex.rep_movement(i["guid"]), i["guid"], p["class"]))
        flights.sort(key=lambda f: f[0])
        f_t = np.array([f[0] for f in flights])
        rows, n = [], 0
        for i in by_class[o["class_path"]]:
            n += 1
            s, _ = ex.owner_subject(i["guid"])
            k = int(np.searchsorted(f_t, i["open_ms"], side="right")) - 1
            while k >= 0 and (flights[k][2] != s or flights[k][1] + 1000.0 < i["open_ms"]):
                k -= 1
            if k < 0:
                continue
            dd = None
            rm = flights[k][3]
            if rm is not None:
                j = int(np.searchsorted(rm[0], i["open_ms"], side="right")) - 1
                if j >= 0:
                    last = np.array([rm[1][j], rm[2][j], rm[3][j]])
                    dd = float(np.linalg.norm(np.array(i["xyz"]) - last))
            rows.append({"object_guid": i["guid"], "projectile_guid": flights[k][4],
                         "projectile_class": flights[k][5],
                         "open_minus_projectile_close_ms": i["open_ms"] - flights[k][1],
                         "spawn_to_projectile_location_cm": dd})
        out[o["class"]] = {"from": sorted({p["class"] for p in ps}), "instances": n, "pairs": rows}
    return out


def handoff(ex: Export, classes: list, by_class: dict) -> dict:
    """`handoff_pairs` summarised per object class: instances, pairs, and the
    time and distance from each paired projectile."""
    out = {}
    for cls, h in handoff_pairs(ex, classes, by_class).items():
        dts = [r["open_minus_projectile_close_ms"] for r in h["pairs"]]
        dds = [r["spawn_to_projectile_location_cm"] for r in h["pairs"]
               if r["spawn_to_projectile_location_cm"] is not None]
        out[cls] = {"from": h["from"], "instances": h["instances"], "paired": len(dts),
                    "open_minus_projectile_close_ms": sample_stats(dts, 1),
                    "spawn_to_projectile_location_cm": sample_stats(dds, 1)}
    return out


def slot_map(cen: dict) -> dict:
    """(agent, slot byte) -> ability folder, where one folder takes at least
    `SLOT_MIN_SHARE` of ALL the slot's casts (unpaired ones count against it)
    and `SLOT_MIN_PAIRED` casts; else None. An ability that opens no world
    actor at its cast (an ult beam, a dash) stays unmapped here."""
    out = {}
    for k, v in cen["casts"]["by_agent_slot"].items():
        hit = {f: n for f, n in v.items() if f != "none"}
        tot = sum(v.values())
        out[k] = None
        if hit:
            f, n = max(hit.items(), key=lambda kv: kv[1])
            if n >= SLOT_MIN_PAIRED and n / tot >= SLOT_MIN_SHARE:
                out[k] = f
    return out
