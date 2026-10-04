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

Replay data is EVALUATION TRUTH ONLY [domain:replay/vrf-ability-actors]: never
a reader input, never a prior, never shown during play. Nothing in `reticle/`
reads this file or its outputs.

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
[metric:replay_truth/score#align_offset_ms=112619.5] ms, 180 of 181 stored
deaths paired, residual MAD [metric:replay_truth/score#align_mad_ms=145.0] ms.
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
GAME_BUILD = "release-13.06-shipping-18-5590001"
ABILITY_DATA = (STORE / "reference" / "game-files" / GAME_BUILD / "ability-data"
                / "ShooterGame" / "Content" / "Characters")
ANALYSIS = STORE / "analysis" / "replay-abilities-20261004"
#: The cast-record array and the fields of one record (vrfkit names carry a
#: Blueprint suffix after the field's own name).
CAST_ARRAY = "AbilityCastsThisRound"
CAST_FIELDS = ("Player", "Slot", "Round", "RoundPhase", "CastTime", "CastLocation")
#: A cast pairs with the first world actor of the same player that opens in
#: [cast - PRE, cast + POST] ms.
PAIR_PRE_MS, PAIR_POST_MS = 250.0, 2000.0
#: A stored cast or ult pairs with a replay one within this many ms.
CAST_GATE_MS = 2000.0
ULT_GATE_MS = 3000.0
#: Classes outside `/Game/Characters` that carry minimap truth, named by path.
NON_CHARACTER = {"/Game/GameObjects/CollectibleOrbs/UltPointOrb": "ult orb",
                 "/Game/GameModes/Bomb/TimedBomb": "planted spike",
                 "/Game/Equippables/Bomb/BombEquippable": "spike item (carried or dropped)"}
ROLE_PREFIX = (("Projectile_", "projectile"), ("GameObject_", "game object"),
               ("Pawn_", "pawn"), ("Patch_", "ground patch"), ("Ability_", "ability item"),
               ("Equippable_", "equippable"), ("Gun_", "equippable"), ("Actor_", "actor"))
_FOLDER = re.compile(r"^/Game/Characters/([^/]+)/S0/(Ability_[^/]+)/")


def _leaf(cp: str | None) -> str:
    return (cp or "").rsplit(".", 1)[-1]


def _role(short: str) -> str:
    if short.endswith("_PC_C"):
        return "character"
    for p, r in ROLE_PREFIX:
        if short.startswith(p):
            return r
    return "other"


def _stats(x, nd=2):
    return rt._stats(x, nd)


# ----------------------------------------------------------------- game files

_UI_CACHE: dict = {}


def ability_display(code: str, folder: str) -> dict:
    """The game files' display name for one ability folder (`UIData*` under it)."""
    key = (code, folder)
    if key in _UI_CACHE:
        return _UI_CACHE[key]
    d = ABILITY_DATA / code / "S0" / folder
    names, files = [], []
    for f in sorted(d.rglob("UIData*.json")) if d.is_dir() else []:
        files.append(f.relative_to(ABILITY_DATA).as_posix())
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

    def __init__(self, match: str, light: bool = False, rp=None):
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        self.match = match
        self.dir = rt.parsed_dir(match)
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
        self.rp = rp if rp is not None else rt.Replay(match)
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

    def owner_subject(self, g: int, hops: int = 4) -> tuple[str | None, list[str]]:
        """Follow `Instigator` (then `Owner`) from actor `g` to a player pawn.

        Returns the player's subject (or None) and the class chain walked."""
        chain = []
        for _ in range(hops):
            s = self.rp.guid_subject.get(g)
            chain.append(_leaf(self.cls.get(g)))
            if s is not None:
                return s, chain
            nxt = self._refs["Instigator"].get(g) or self._refs["Owner"].get(g)
            if nxt is None:
                return None, chain
            g = nxt
        return None, chain

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
        """(t, x, y, z) of one actor's `ReplicatedMovement` rows, world units."""
        m = (self.f_g == g) & (self.f_n == "ReplicatedMovement")
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

    def ult_intervals(self) -> list[dict]:
        """`bUltimateActive` false-to-true transitions per player state, with the
        following true-to-false; the player state's `Subject` names the player."""
        m = self.f_n == "Subject"
        ps_sub = {}
        for g, s, gp in zip(self.f_g[m], self.f_s[m], self.f_gp[m]):
            if s and "PlayerState" in (gp or ""):
                ps_sub.setdefault(int(g), s)
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

def actor_census(match: str, ex: Export | None = None) -> dict:
    ex = ex if ex is not None else Export(match)
    rp = ex.rp
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
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
               "closes": len(life), "lifetime_s": _stats(np.array(life) / 1000.0),
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
            ui = ability_display(code, folder)
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
    out = {"match": match, "replay_abilities_version": REPLAY_ABILITIES_VERSION,
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
                     "open_after_cast_ms": {f"{a}|{s}|{k}": _stats(v, 1) for (a, s, k), v in
                                            sorted(lag.items(), key=lambda kv: str(kv[0]))},
                     "unpaired_nearest_open_ms": {f"{a}|{s}|{k}": {"n": len(v), **(_stats(v, 1) or {})}
                                                  for (a, s, k), v in
                                                  sorted(unpaired.items(), key=lambda kv: str(kv[0]))}},
           "ults": {"transitions": len(ults), "events": int(ev_t.size),
                    "events_within_100ms_of_transition": int(np.sum(near <= 100)) if near.size else 0,
                    "by_agent": dict(Counter(agent.get(u["subject"]) for u in ults)),
                    "duration_s": _stats([(u["off_ms"] - u["on_ms"]) / 1000.0 for u in ults
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


def handoff(ex: Export, classes: list, by_class: dict) -> dict:
    """Projectile -> game object of one ability: does the game object open where
    and while the same player's projectile of that ability folder flies?

    Each game-object instance takes the latest projectile of the same player
    and folder that opened before it and had not closed more than 1 s before
    it. The report gives the object's open minus the projectile's close (ms;
    negative while the projectile still exists) and the distance from the
    projectile's last replicated location at or before the open to the
    object's spawn, world cm."""
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
                                s, ex.rep_movement(i["guid"])))
        flights.sort(key=lambda f: f[0])
        f_t = np.array([f[0] for f in flights])
        dts, dds, n = [], [], 0
        for i in by_class[o["class_path"]]:
            n += 1
            s, _ = ex.owner_subject(i["guid"])
            k = int(np.searchsorted(f_t, i["open_ms"], side="right")) - 1
            while k >= 0 and (flights[k][2] != s or flights[k][1] + 1000.0 < i["open_ms"]):
                k -= 1
            if k < 0:
                continue
            dts.append(i["open_ms"] - flights[k][1])
            rm = flights[k][3]
            if rm is not None:
                j = int(np.searchsorted(rm[0], i["open_ms"], side="right")) - 1
                if j >= 0:
                    last = np.array([rm[1][j], rm[2][j], rm[3][j]])
                    dds.append(float(np.linalg.norm(np.array(i["xyz"]) - last)))
        out[o["class"]] = {"from": sorted({p["class"] for p in ps}), "instances": n,
                           "paired": len(dts), "open_minus_projectile_close_ms": _stats(dts, 1),
                           "spawn_to_projectile_location_cm": _stats(dds, 1)}
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
