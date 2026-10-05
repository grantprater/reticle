r"""Ability CAST coverage: which casts each stored channel witnesses, against Riot.

    .\.venv\Scripts\python.exe prototypes\ability_coverage.py [--record] [--json OUT]
    .\.venv\Scripts\python.exe prototypes\ability_coverage.py --no-replay SESSION [SESSION ...]

What it measures
----------------
The ability design in progress opens each ability instance as a child entity
of its caster on cast evidence that spends a charge. This script asks how many
casts the stored channels witness today, per agent and ability, for the
player, allies and enemies apart. It reads stored events, the stored round
table and Riot's match records only; it decodes nothing and decides nothing.

Truth, and what it can and cannot say
-------------------------------------
Riot's records (`<store>/external/riot/*.json`) give each player's MATCH
cast count per slot (`stats.abilityCasts`: grenade, ability1, ability2,
ultimate). Every round's `playerStats[].ability` is null in all 22 stored
records, so Riot gives no per-round or timed cast. Coverage is therefore
counted per (match, player, slot): `covered = min(witnessed, riot)`,
`missed = riot - covered`, `excess = witnessed - covered`. Excess is a floor
on false or double witnesses; a witness on the wrong round can hide behind a
miss in another, so a match-level count cannot prove one-to-one agreement.

Riot's slot names the ability through valorant-api's slot field, which the
wiki harvest `reference/abilities.json` carries per ability (C Grenade, Q
Ability1, E Ability2, X Ultimate in every kit it lists). Riot records carry
agents as valorant-api uuids (`riot_ground_truth.Reference`, cached
`external/valorant-api/agents.json`, offline).

The one replay kept beside a capture (`external/replays`, match b03fecd3,
session 9acf02f98283) gives timed truth: its `AbilityCastsThisRound`
records (`replay_abilities.Export.casts`). Their undocumented slot byte is
read here as 3 Grenade, 4 Ability1, 5 Ability2, 9 Ultimate, BECAUSE the
per-player per-byte replay counts equal Riot's per-slot counts on that match
in [metric:ability_coverage/replay_timing@9acf02f98283#equal=38] of
[metric:ability_coverage/replay_timing@9acf02f98283#cells=40] cells;
`replay_vs_riot` lists every unequal cell (both are Clove's Ability2, Ruse,
where Riot counts more casts than the replay records). Replay time maps to capture time by the stored `replay_truth`
alignment (`analysis/replay-abilities-20261004/9acf02f98283.json`, `align`).
Replay and Riot data are evaluation truth only; nothing in `reticle/` reads
this file.

The channels (stored streams, each with its counting unit)
----------------------------------------------------------
* `tray` -- `ability_state` verdicts with transition `cast` (the self tray,
  through the state model; one row per spent charge). Self only.
* `audio` -- `ability_state` claims of witness `audio` that name a slot
  (`ability-audio-params`); it scores only drops the gate passed, so it
  corroborates the tray and never finds a cast the tray lacks. Self only.
* `ult_cast` -- `ult_cast` rows of kind `cast`; `player_cast` marks self.
* `minimap_shape` -- `ability_shape` rows found, one per seeded `cast_t_ms`
  (the self casts' minimap rings and beams).
* `minimap_fit` -- `ability_fit` fits found and `ability_wall` walls
  accepted, per (ability, colour side): an episode opens on a hit after
  `EPISODE_GAP_MS` without one. An episode is NOT a cast (two bolts in one
  episode are one); this is the channel's closest count, declared as such.
  Minimap teal is the player's team, self included.
* `smoke` -- `smoke_owner` tracks with a resolved agent, one per `cast_group`,
  slot from the owner's `SMOKE_ABILITY`.
* `killfeed` -- `death` verdicts whose weapon category is `ability`, named
  through `ABILITY_CANONICAL_NAMES`; one witness per (round, killer, ability):
  a kill shows that at least one cast happened that round.
* `assist_icon` -- `assist` verdicts' assisters with an icon read
  (`icon_status == read`); one witness per (round, side, agent, ability).

`any` is the union without double counting across channels: per (player,
slot, round) the largest count any one channel gives, summed over rounds.
Rounds come from the stored round table (`rounds.round_containing`). A
witness whose (side, agent) names no Riot player of that side is
`unresolved` and counted apart.

Streams left out, with the reason: `ability_icon` (unnamed icon candidates,
no ability or caster), `ability_shape_scan` and `ability_gate` (frame gates
that feed `ability_fit`), `tray_kit` (kit spans, not casts), `ability`
(demo clips, no Riot record).

Effect relevance
----------------
`kill`: Riot's own kills by that (agent, slot), counted from the records'
finishing damage (`riot_ground_truth.weapon_name`'s slot table and
`ult_kill_kind`), or, where Riot's finishing damage cannot name the slot,
a stored killfeed KILL by that ability, revives and second lives excluded
(`kill_basis` says which). Chamber's Headhunter kills carry a weapon item
valorant-api does not list, so Riot's data cannot name their slot and they
take the killfeed basis. `block` / `reveal` / `impair`: the wiki harvest's
`functions` words (FUNCTION_TAGS); an ability whose harvest lists none is
`unknown`, never guessed. The gap ranking orders tiers kill, block / reveal
/ impair, unknown, other, then casts missed.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ABILITY_COVERAGE_VERSION = "ability-coverage-proto-0.1.0"
STORE = Path.home() / "reticle-store"
RIOT_SLOTS = ("Grenade", "Ability1", "Ability2", "Ultimate")
RIOT_FIELD = {"Grenade": "grenadeCasts", "Ability1": "ability1Casts",
              "Ability2": "ability2Casts", "Ultimate": "ultimateCasts"}
#: The replay cast record's slot byte, as checked against Riot (`replay_vs_riot`).
REPLAY_SLOT = {3: "Grenade", 4: "Ability1", 5: "Ability2", 9: "Ultimate"}
CHANNELS = ("tray", "audio", "ult_cast", "minimap_shape", "minimap_fit", "smoke",
            "killfeed", "assist_icon")
SIDES = ("self", "ally", "enemy")
#: A minimap fit episode closes after this long without a hit (2 Hz frames).
EPISODE_GAP_MS = 2500.0
#: Replay pairing gates, as `replay_abilities` scores casts and ults.
CAST_GATE_MS = 2000.0
ULT_GATE_MS = 3000.0
#: A kill or assist witness looks back this far for the cast it rests on.
EFFECT_LOOKBACK_MS = 60000.0
REPLAY_SESSION = "9acf02f98283"
REPLAY_MATCH = "b03fecd3-8d80-4e6c-bae0-ac2ec0344567"
#: The wiki harvest's function words, by effect.
FUNCTION_TAGS = {
    "block": {"Smoke", "Wall", "Blocker", "Barrier", "Vision"},
    "reveal": {"Intel"},
    "impair": {"Flash", "Nearsight", "Concuss", "Blind", "Detain", "Slow", "Cripple",
               "Hinder", "Displacement", "Tether", "Limiter", "Molotov", "Deterrent"},
}
TIER_ORDER = ("kill", "block/reveal/impair", "unknown", "other")


# ----------------------------------------------------------------- helpers

def canon(name) -> str | None:
    """One spelling per agent or ability: `KAY/O`, `KAY_O` and `kay/o` agree."""
    if name is None:
        return None
    return " ".join(str(name).replace("/", "_").replace("-", " ").casefold().split())


def _rows(path: Path):
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


def _stats(xs) -> dict | None:
    xs = sorted(float(x) for x in xs)
    if not xs:
        return None
    med = statistics.median(xs)
    return {"n": len(xs), "median": round(med, 1),
            "mad": round(statistics.median(abs(x - med) for x in xs), 1),
            "min": round(xs[0], 1), "max": round(xs[-1], 1)}


# ----------------------------------------------------------------- catalogue

class Catalogue:
    """The wiki harvest's kits: per agent, tray key and ability name -> Riot slot."""

    def __init__(self, data: dict):
        self.by_key, self.by_name, self.info = {}, {}, {}
        for agent, a in data["agents"].items():
            ca = canon(agent)
            for ab in a.get("abilities", []):
                slot = ab.get("slot")
                if slot not in RIOT_SLOTS:
                    continue
                if ab.get("key"):
                    self.by_key[(ca, ab["key"])] = slot
                self.by_name[(ca, canon(ab["name"]))] = slot
                self.info[(ca, slot)] = {"agent": agent, "ability": " ".join(ab["name"].split()),
                                         "functions": (ab.get("functions") or "").split()}

    @classmethod
    def load(cls, store: Path = STORE) -> "Catalogue":
        return cls(json.loads((store / "reference" / "abilities.json").read_text(encoding="utf-8")))

    def slot_of_name(self, agent, name) -> str | None:
        return self.by_name.get((canon(agent), canon(name)))

    def name(self, agent, slot) -> str:
        return (self.info.get((canon(agent), slot)) or {}).get("ability") or f"{agent}:{slot}"

    def tags(self, agent, slot) -> list[str]:
        fn = set((self.info.get((canon(agent), slot)) or {}).get("functions") or [])
        return [t for t, words in FUNCTION_TAGS.items() if fn & words]

    def has_functions(self, agent, slot) -> bool:
        return bool((self.info.get((canon(agent), slot)) or {}).get("functions"))


# ----------------------------------------------------------------- riot truth

def riot_players(d: dict, me: str, agent_of) -> list[dict]:
    """Each Riot player: subject, agent, side relative to the player, slot casts."""
    ps = d["match"]["players"]
    team = next(p["teamId"] for p in ps if p["subject"] == me)
    out = []
    for p in ps:
        ac = (p.get("stats") or {}).get("abilityCasts") or {}
        out.append({"subject": p["subject"], "agent": agent_of(p["characterId"]),
                    "side": "self" if p["subject"] == me else
                            ("ally" if p["teamId"] == team else "enemy"),
                    "casts": {s: int(ac.get(RIOT_FIELD[s]) or 0) for s in RIOT_SLOTS}})
    return out


def riot_ability_kills(d: dict, players: list[dict]) -> Counter:
    """(subject, slot) -> Riot's kills finished by that ability."""
    import riot_ground_truth as rg
    agent = {p["subject"]: p["agent"] for p in players}
    out = Counter()
    for k in d["match"]["kills"]:
        if k.get("killer") == k.get("victim"):
            continue    # Clove's expiry is recorded as her ult killing her [domain:rounds/riot-records-clove-expiry]
        fd = k.get("finishingDamage") or {}
        slot = None
        if fd.get("damageType") == "Ability":
            slot = {"GrenadeAbility": "Grenade"}.get(fd.get("damageItem"), fd.get("damageItem"))
        elif rg.ult_kill_kind(k, rg.asset_agent(agent.get(k["killer"]))):
            slot = "Ultimate"
        if slot in RIOT_SLOTS:
            out[(k["killer"], slot)] += 1
    return out


# ----------------------------------------------------------------- witnesses

def _w(channel, side, agent, slot, t_ms, key, ability=None):
    return {"channel": channel, "side": side, "agent": agent, "slot": slot,
            "t_ms": None if t_ms is None else float(t_ms), "key": key, "ability": ability}


def witnesses_tray_audio(rows: list[dict], cat: Catalogue) -> tuple[list[dict], str | None]:
    """Self casts from `ability_state`: cast verdicts (`tray`) and audio claims."""
    cov = next((r for r in rows if r.get("kind") == "coverage"), {})
    agent = (cov.get("agent") or {}).get("agent")
    kit = cov.get("kit") or {}
    out = []
    for r in rows:
        if r.get("kind") == "verdict" and r.get("transition") == "cast":
            slot = cat.slot_of_name(agent, kit.get(r["slot"])) or cat.by_key.get((canon(agent), r["slot"]))
            out.append(_w("tray", "self", agent, slot, r["t_ms"], ("tray", r["slot"], r["t_ms"])))
        elif (r.get("kind") == "claim" and r.get("witness") == "audio"
              and r.get("observed") in ("C", "Q", "E", "X")):
            key = r["observed"]
            slot = cat.slot_of_name(agent, kit.get(key)) or cat.by_key.get((canon(agent), key))
            out.append(_w("audio", "self", agent, slot, r.get("observed_at_ms"),
                          ("audio", r["claim_id"])))
    return out, agent


def witnesses_ult(rows: list[dict]) -> list[dict]:
    return [_w("ult_cast", "self" if r.get("player_cast") else r.get("side"), r.get("agent"),
               "Ultimate", r["t_ms"], ("ult", r.get("entity_id")))
            for r in rows if r.get("kind") == "cast"]


def witnesses_shape(rows: list[dict], cat: Catalogue) -> list[dict]:
    seen = {}
    for r in rows:
        if r.get("kind") == "shape" and r.get("found") and r.get("cast_t_ms") is not None:
            k = (r["cast_t_ms"], r.get("ability"))
            seen.setdefault(k, r)
    return [_w("minimap_shape", "self", r["agent"], cat.slot_of_name(r["agent"], r["ability"]),
               r["cast_t_ms"], ("shape",) + k, r["ability"]) for k, r in seen.items()]


def fit_episodes(hits: list[tuple[float, str, str]], gap_ms: float = EPISODE_GAP_MS) -> list[dict]:
    """(t_ms, ability, colour side) hits -> one episode per run without a gap > `gap_ms`."""
    last, out = {}, []
    for t, ab, side in sorted(hits):
        k = (ab, side)
        if k not in last or t - last[k] > gap_ms:
            out.append({"t_ms": t, "ability": ab, "colour": side})
        last[k] = t
    return out


def witnesses_fit(fit_rows: list[dict], wall_rows: list[dict], cat: Catalogue,
                  me_agent: str | None) -> list[dict]:
    """Minimap fit and wall episodes; the agent is the ability's only owner in the
    catalogue, teal (`ally`) is the player's team, self when the agent is the player's."""
    owner = defaultdict(set)
    for (ca, nm), _slot in cat.by_name.items():
        owner[nm].add(ca)
    hits = []
    for r in fit_rows:
        for x in r.get("fits") or []:
            if x.get("found"):
                hits.append((float(r["t_ms"]), x["ability"], x.get("side")))
    for r in wall_rows:
        for x in r.get("walls") or []:
            if x.get("accepted") or x.get("found"):
                hits.append((float(r["t_ms"]), x["ability"], x.get("side")))
    out = []
    for e in fit_episodes(hits):
        ags = owner.get(canon(e["ability"])) or set()
        agent = next(iter(ags)) if len(ags) == 1 else None
        agent_name = cat.info.get((agent, cat.by_name.get((agent, canon(e["ability"])))), {}).get("agent") \
            if agent else None
        side = e["colour"]
        if side == "ally" and agent and canon(me_agent) == agent:
            side = "self"
        out.append(_w("minimap_fit", side, agent_name,
                      cat.by_name.get((agent, canon(e["ability"]))) if agent else None,
                      e["t_ms"], ("fit", e["ability"], e["colour"], e["t_ms"]), e["ability"]))
    return out


def witnesses_smoke(rows: list[dict], cat: Catalogue, me_agent: str | None) -> list[dict]:
    from reticle.adjudication.smoke_owner import SMOKE_ABILITY
    seen, out = set(), []
    for r in rows:
        if r.get("kind") != "smoke_owner" or not r.get("agent"):
            continue
        g = tuple(sorted(r.get("cast_group") or [r["entity_id"]]))
        if g in seen:
            continue
        seen.add(g)
        key = (SMOKE_ABILITY.get(r["agent"]) or (None,))[0]
        side = "self" if canon(r["agent"]) == canon(me_agent) else "ally"
        out.append(_w("smoke", side, r["agent"], cat.by_key.get((canon(r["agent"]), key)),
                      r.get("first_ms"), ("smoke", g)))
    return out


def witnesses_killfeed(rows: list[dict], cat: Catalogue) -> list[dict]:
    """Ability kills; one per (round, killer side, killer, ability)."""
    seen, out = set(), []
    for r in rows:
        we = r.get("weapon_evidence") or {}
        if r.get("kind") != "death_verdict" or we.get("category") != "ability":
            continue
        if r.get("kf_player_kill"):
            side = "self"
        elif r.get("side") in ("ally", "enemy"):
            side = r["side"] if r.get("same_side") else \
                {"ally": "enemy", "enemy": "ally"}[r["side"]]
        else:
            side = None
        k = (r.get("round_no"), side, r.get("killer"), r.get("weapon"))
        if k in seen:
            continue
        seen.add(k)
        x = _w("killfeed", side, r.get("killer"), cat.slot_of_name(r.get("killer"), r.get("weapon")),
               r.get("t_ms"), ("kf",) + k, r.get("weapon"))
        x["kill"] = not (r.get("is_revive") or r.get("is_second_life"))
        out.append(x)
    return out


def witnesses_assist(rows: list[dict], cat: Catalogue) -> list[dict]:
    """Assist-panel ability icons; one per (round, side, agent, ability)."""
    seen, out = set(), []
    for r in rows:
        if r.get("kind") != "assist_verdict":
            continue
        for a in r.get("assisters") or []:
            if a.get("icon_status") != "read" or not a.get("icon") or a.get("icon") == "none":
                continue
            agent = a.get("icon_agent") or a.get("agent")
            k = (r.get("round_no"), r.get("killer_side"), agent, a["icon"])
            if k in seen:
                continue
            seen.add(k)
            out.append(_w("assist_icon", r.get("killer_side"), agent,
                          cat.slot_of_name(agent, a["icon"]), r.get("t_ms"), ("as",) + k, a["icon"]))
    return out


# ----------------------------------------------------------------- tally

def resolve_subject(w: dict, players: list[dict]) -> str | None:
    """The Riot subject a witness names: self is the player; an ally or enemy is
    that side's player of the witness's agent (an ally of the player's agent is
    the player). None when no such player exists."""
    if w["side"] == "self":
        return next((p["subject"] for p in players if p["side"] == "self"), None)
    if w["side"] not in ("ally", "enemy"):
        return None
    sides = ("self", "ally") if w["side"] == "ally" else ("enemy",)
    hits = [p for p in players if p["side"] in sides and canon(p["agent"]) == canon(w["agent"])]
    return hits[0]["subject"] if len(hits) == 1 else None


def tally(witnesses: list[dict], players: list[dict], round_of) -> dict:
    """Per (subject, slot): Riot casts, each channel's count, the union, and the
    witnesses no player or slot takes (`unresolved`, by channel and reason).

    The union is, per round, the largest count of one channel, summed."""
    per = {(p["subject"], s): {"riot": p["casts"][s], "channels": Counter(),
                               "rounds": defaultdict(Counter)}
           for p in players for s in RIOT_SLOTS}
    unresolved = Counter()
    for w in witnesses:
        sub = resolve_subject(w, players)
        if sub is None:
            unresolved[(w["channel"], "no_player_of_side_and_agent")] += 1
            continue
        if w["slot"] not in RIOT_SLOTS:
            unresolved[(w["channel"], "ability_not_in_catalogue")] += 1
            continue
        cell = per[(sub, w["slot"])]
        cell["channels"][w["channel"]] += 1
        cell["kf_kills"] = cell.get("kf_kills", 0) + int(bool(w.get("kill")))
        rnd = round_of(w["t_ms"]) if w["t_ms"] is not None else None
        cell["rounds"][rnd][w["channel"]] += 1
    for cell in per.values():
        cell["any"] = sum(max(c.values()) for c in cell["rounds"].values() if c)
    return {"cells": per, "unresolved": unresolved}


def aggregate(sessions: list[dict], cat: Catalogue) -> list[dict]:
    """Rows per (side, agent, slot) over sessions: Riot casts, covered, missed and
    excess per channel and for the union, and the effect tags."""
    acc = {}
    for s in sessions:
        side_of = {p["subject"]: p for p in s["players"]}
        for (sub, slot), cell in s["tally"]["cells"].items():
            p = side_of[sub]
            k = (p["side"], p["agent"], slot)
            a = acc.setdefault(k, {"side": p["side"], "agent": p["agent"], "slot": slot,
                                   "ability": cat.name(p["agent"], slot), "matches": 0,
                                   "riot": 0, "any": 0, "missed": 0, "excess": 0,
                                   "riot_kills": 0, "by_channel": Counter(),
                                   "covered_by_channel": Counter()})
            a["matches"] += 1
            a["riot"] += cell["riot"]
            a["any"] += min(cell["any"], cell["riot"])
            a["missed"] += max(0, cell["riot"] - cell["any"])
            a["excess"] += max(0, cell["any"] - cell["riot"])
            a["riot_kills"] += s["kills"].get((sub, slot), 0)
            a["killfeed_kills"] = a.get("killfeed_kills", 0) + cell.get("kf_kills", 0)
            for ch, n in cell["channels"].items():
                a["by_channel"][ch] += n
                a["covered_by_channel"][ch] += min(n, cell["riot"])
    out = []
    for a in acc.values():
        tags = cat.tags(a["agent"], a["slot"])
        a["kill_basis"] = ("riot" if a["riot_kills"] else
                           "killfeed" if a.get("killfeed_kills") else None)
        if a["kill_basis"]:
            tier = "kill"
        elif tags:
            tier = "block/reveal/impair"
        elif not cat.has_functions(a["agent"], a["slot"]):
            tier = "unknown"
        else:
            tier = "other"
        a.update(tags=tags, tier=tier, by_channel=dict(a["by_channel"]),
                 covered_by_channel=dict(a["covered_by_channel"]),
                 recall=round(a["any"] / a["riot"], 4) if a["riot"] else None)
        out.append(a)
    return rank(out)


def rank(rows: list[dict]) -> list[dict]:
    """Gaps: effect tier first (kill, block/reveal/impair, unknown, other), then casts missed."""
    return sorted(rows, key=lambda a: (TIER_ORDER.index(a["tier"]), -a["missed"], a["side"],
                                       str(a["agent"]), a["slot"]))


def side_totals(rows: list[dict]) -> dict:
    out = {}
    for side in SIDES:
        rs = [a for a in rows if a["side"] == side]
        riot = sum(a["riot"] for a in rs)
        out[side] = {"riot": riot, "any": sum(a["any"] for a in rs),
                     "missed": sum(a["missed"] for a in rs),
                     "excess": sum(a["excess"] for a in rs),
                     "recall": round(sum(a["any"] for a in rs) / riot, 4) if riot else None,
                     "covered_by_channel": dict(sum((Counter(a["covered_by_channel"]) for a in rs),
                                                    Counter()))}
    return out


# ----------------------------------------------------------------- sessions

def session_witnesses(sid: str, cat: Catalogue, store: Path = STORE) -> tuple[list[dict], str | None, dict]:
    ev = store / "events"
    st = _rows(ev / "ability_state" / f"{sid}.jsonl")
    w, me_agent = witnesses_tray_audio(st, cat)
    w += witnesses_ult(_rows(ev / "ult_cast" / f"{sid}.jsonl"))
    w += witnesses_shape(_rows(ev / "ability_shape" / f"{sid}.jsonl"), cat)
    w += witnesses_fit(_rows(ev / "ability_fit" / f"{sid}.jsonl"),
                       _rows(ev / "ability_wall" / f"{sid}.jsonl"), cat, me_agent)
    w += witnesses_smoke(_rows(ev / "smoke_owner" / f"{sid}.jsonl"), cat, me_agent)
    w += witnesses_killfeed(_rows(ev / "death" / f"{sid}.jsonl"), cat)
    w += witnesses_assist(_rows(ev / "assist" / f"{sid}.jsonl"), cat)
    streams = {name: (ev / name / f"{sid}.jsonl").is_file()
               for name in ("ability_state", "ult_cast", "ability_shape", "ability_fit",
                            "ability_wall", "smoke_owner", "death", "assist")}
    return w, me_agent, streams


def load_sessions(only=None, store: Path = STORE) -> tuple[list[dict], Catalogue]:
    import riot_ground_truth as rg
    from reticle.rounds import round_containing
    from reticle.store import Store
    cat = Catalogue.load(store)
    ref = rg.Reference(store / "external" / "valorant-api", fetch=False)
    recs = rg.riot_records(store)
    ident = rg.identify_player(recs, store)
    st = Store(store)
    out = []
    for sid, d in sorted(recs.items()):
        if only and sid not in only:
            continue
        if not (store / "events" / "ability_state" / f"{sid}.jsonl").is_file():
            out.append({"session": sid, "refused": "no_stored_ability_state"})
            continue
        idn = rg.resolve_lineup_player(d, ident[sid], ref)
        if not idn.get("subject"):
            out.append({"session": sid, "refused": f"player_unidentified:{idn.get('basis')}"})
            continue
        players = riot_players(d, idn["subject"], ref.agent)
        man = st.read_manifest(sid)
        table = st.read_rounds(sid, man["ingested_at"][:10])
        rounds = table.to_pylist() if table is not None else []

        def round_of(t, rounds=rounds):
            r = round_containing(t, rounds)
            return r["round_no"] if r else None

        w, me_agent, streams = session_witnesses(sid, cat, store)
        me = next(p for p in players if p["side"] == "self")
        out.append({"session": sid, "players": players, "witnesses": w,
                    "tally": tally(w, players, round_of), "kills": riot_ability_kills(d, players),
                    "stored_agent": me_agent, "riot_agent": me["agent"],
                    "player_basis": idn.get("basis"), "rounds": len(rounds), "streams": streams})
    return out, cat


# ----------------------------------------------------------------- replay timing

def pair_times(det, tru, gate: float):
    """One-to-one nearest pairing within `gate`: (det index, truth index, det - truth)."""
    cand = sorted(((abs(d - t), i, j, d - t) for i, d in enumerate(det) for j, t in enumerate(tru)
                   if abs(d - t) <= gate))
    ui, uj, out = set(), set(), []
    for _, i, j, dt in cand:
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        out.append((i, j, dt))
    return out


def lag_after(det, tru, lookback: float):
    """Per witness, its time less the latest truth time at or before it, within `lookback`."""
    tru = sorted(tru)
    out = []
    for d in det:
        prev = [t for t in tru if 0 <= d - t <= lookback]
        if prev:
            out.append(d - prev[-1])
    return out


def replay_timing(sess: dict, store: Path = STORE) -> dict:
    """Timing of each channel's witnesses against the replay's cast records."""
    import replay_abilities as ra
    stored = json.loads((store / "analysis" / "replay-abilities-20261004" /
                         f"{REPLAY_SESSION}.json").read_text(encoding="utf-8"))
    a = float(stored["align"]["a_ms"])
    ex = ra.Export(REPLAY_MATCH)
    casts = ex.casts()["casts"]
    truth = defaultdict(list)
    for c in casts:
        slot = REPLAY_SLOT.get(c["slot"])
        if slot and c["t_ms"] is not None:
            truth[(c["subject"], slot)].append(float(c["t_ms"]) + a)
    # the slot-byte reading, cell by cell, against Riot's match counts
    vs = []
    for p in sess["players"]:
        for s in RIOT_SLOTS:
            vs.append({"agent": p["agent"], "side": p["side"], "slot": s,
                       "riot": p["casts"][s], "replay": len(truth[(p["subject"], s)])})
    other = Counter(c["slot"] for c in casts if c["slot"] not in REPLAY_SLOT)
    out = {"align_a_ms": a, "align_source": "replay_truth stored align (analysis/replay-abilities-20261004)",
           "replay_vs_riot": {"cells": len(vs), "equal": sum(v["riot"] == v["replay"] for v in vs),
                              "unequal": [v for v in vs if v["riot"] != v["replay"]],
                              "other_slot_bytes": dict(other),
                              "riot_total": sum(v["riot"] for v in vs),
                              "replay_total": sum(v["replay"] for v in vs)},
           "channels": {}}
    players = sess["players"]
    by_ch = defaultdict(lambda: defaultdict(list))
    for w in sess["witnesses"]:
        sub = resolve_subject(w, players)
        if sub and w["slot"] in RIOT_SLOTS and w["t_ms"] is not None:
            by_ch[w["channel"]][(sub, w["slot"])].append(w["t_ms"])
    side_of = {p["subject"]: p["side"] for p in players}
    for ch, cells in sorted(by_ch.items()):
        res = {"witnesses": 0, "paired": 0, "truth_in_cells": 0, "dt_ms": [], "by_side": Counter()}
        effect = ch in ("killfeed", "assist_icon")
        for (sub, slot), det in cells.items():
            tru = truth.get((sub, slot), [])
            res["witnesses"] += len(det)
            res["truth_in_cells"] += len(tru)
            if effect:
                lags = lag_after(det, tru, EFFECT_LOOKBACK_MS)
                res["paired"] += len(lags)
                res["dt_ms"] += lags
                res["by_side"][side_of[sub]] += len(lags)
            else:
                p = pair_times(det, tru, ULT_GATE_MS if slot == "Ultimate" else CAST_GATE_MS)
                res["paired"] += len(p)
                res["dt_ms"] += [x[2] for x in p]
                res["by_side"][side_of[sub]] += len(p)
        res["measure"] = ("witness minus the latest replay cast of that player and slot "
                          f"within {EFFECT_LOOKBACK_MS / 1000:.0f} s" if effect else
                          "witness minus the nearest replay cast of that player and slot, one to one, "
                          f"within {CAST_GATE_MS / 1000:.0f} s ({ULT_GATE_MS / 1000:.0f} s ult)")
        res["dt_ms"] = _stats(res["dt_ms"])
        res["by_side"] = dict(res["by_side"])
        out["channels"][ch] = res
    return out


# ----------------------------------------------------------------- report

def build_report(only=None, replay: bool = True, store: Path = STORE) -> dict:
    sessions, cat = load_sessions(only, store)
    ok = [s for s in sessions if "refused" not in s]
    rows = aggregate(ok, cat)
    unresolved = Counter()
    for s in ok:
        for (ch, why), n in s["tally"]["unresolved"].items():
            unresolved[f"{ch}|{why}"] += n
    witnessed = Counter(w["channel"] for s in ok for w in s["witnesses"])
    out = {"version": ABILITY_COVERAGE_VERSION, "sessions": len(ok),
           "refused": {s["session"]: s["refused"] for s in sessions if "refused" in s},
           "self_agent_disagrees": {s["session"]: [s["stored_agent"], s["riot_agent"]] for s in ok
                                    if canon(s["stored_agent"]) != canon(s["riot_agent"])},
           "streams_present": {ch: sum(s["streams"][ch] for s in ok)
                               for ch in (ok[0]["streams"] if ok else {})},
           "witness_rows": dict(witnessed), "unresolved": dict(unresolved),
           "sides": side_totals(rows), "rows": rows}
    rp = next((s for s in ok if s["session"] == REPLAY_SESSION), None)
    if replay and rp is not None:
        out["replay_timing"] = replay_timing(rp, store)
    return out


def record_ledger(rep: dict) -> list[str]:
    from reticle import metrics
    deps = {"version": ABILITY_COVERAGE_VERSION,
            "code": metrics.fingerprint(tally, aggregate, rank, witnesses_tray_audio, witnesses_ult,
                                        witnesses_shape, witnesses_fit, fit_episodes, witnesses_smoke,
                                        witnesses_killfeed, witnesses_assist, resolve_subject, riot_players,
                                        riot_ability_kills, EPISODE_GAP_MS=EPISODE_GAP_MS)}
    ctx = {"sessions": rep["sessions"], "refused": sorted(rep["refused"])}
    out = []
    vals = {"sessions": rep["sessions"]}
    for side, v in rep["sides"].items():
        vals[f"{side}.riot"] = v["riot"]
        vals[f"{side}.any"] = v["any"]
        vals[f"{side}.missed"] = v["missed"]
        vals[f"{side}.excess"] = v["excess"]
        vals[f"{side}.recall"] = v["recall"]
        for ch, n in v["covered_by_channel"].items():
            vals[f"{side}.{ch}"] = n
    metrics.record("ability_coverage", part="sides", values=vals, deps=deps, context=ctx)
    out.append("ability_coverage/sides")
    gaps = {}
    for i, a in enumerate(rep["rows"][:25]):
        k = f"{a['side']}:{a['agent']}:{a['slot']}".replace(" ", "_").replace("/", "_")
        gaps[f"{k}.riot"] = a["riot"]
        gaps[f"{k}.any"] = a["any"]
        gaps[f"{k}.missed"] = a["missed"]
    metrics.record("ability_coverage", part="gaps", values=gaps, deps=deps, context=ctx)
    out.append("ability_coverage/gaps")
    rt = rep.get("replay_timing")
    if rt:
        rv = {"cells": rt["replay_vs_riot"]["cells"], "equal": rt["replay_vs_riot"]["equal"],
              "riot_total": rt["replay_vs_riot"]["riot_total"],
              "replay_total": rt["replay_vs_riot"]["replay_total"]}
        for ch, r in rt["channels"].items():
            rv[f"{ch}.witnesses"] = r["witnesses"]
            rv[f"{ch}.paired"] = r["paired"]
            rv[f"{ch}.truth"] = r["truth_in_cells"]
            rv[f"{ch}.dt_median_ms"] = (r["dt_ms"] or {}).get("median")
            rv[f"{ch}.dt_mad_ms"] = (r["dt_ms"] or {}).get("mad")
        metrics.record("ability_coverage", part="replay_timing", session=REPLAY_SESSION,
                       values=rv, deps=deps, context=dict(ctx, align_a_ms=rt["align_a_ms"]))
        out.append(f"ability_coverage/replay_timing@{REPLAY_SESSION}")
    return out


def table(rows: list[dict], n: int = 40) -> str:
    chans = ("tray", "audio", "ult_cast", "minimap_shape", "minimap_fit", "smoke", "killfeed",
             "assist_icon")
    short = ("tray", "aud", "ult", "shp", "fit", "smk", "kf", "ast")
    head = (f"{'tier':<8} {'side':<5} {'agent':<10} {'ability':<22} {'slot':<8} {'riot':>5} "
            f"{'any':>5} {'miss':>5} {'exc':>4} {'kills':>5} " + " ".join(f"{s:>4}" for s in short))
    lines = [head]
    for a in rows[:n]:
        cv = a["covered_by_channel"]
        lines.append(f"{a['tier'][:8]:<8} {a['side']:<5} {str(a['agent'])[:10]:<10} "
                     f"{a['ability'][:22]:<22} {a['slot']:<8} {a['riot']:>5} {a['any']:>5} "
                     f"{a['missed']:>5} {a['excess']:>4} {a['riot_kills']:>5} "
                     + " ".join(f"{cv.get(c, 0):>4}" for c in chans))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--no-replay", action="store_true")
    ap.add_argument("--rows", type=int, default=40)
    args = ap.parse_args(argv)
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except (AttributeError, OSError):
        pass
    rep = build_report(set(args.sessions) or None, replay=not args.no_replay)
    print(f"{rep['sessions']} sessions; refused {rep['refused']}")
    if rep["self_agent_disagrees"]:
        print("stored self agent differs from Riot:", rep["self_agent_disagrees"])
    for side, v in rep["sides"].items():
        print(f"{side:<6} riot {v['riot']:>5} witnessed {v['any']:>5} missed {v['missed']:>5} "
              f"excess {v['excess']:>4} recall {v['recall']}  {v['covered_by_channel']}")
    print("unresolved witnesses:", rep["unresolved"])
    print(table(rep["rows"], args.rows))
    rt = rep.get("replay_timing")
    if rt:
        print(f"\nreplay {REPLAY_SESSION}: slot bytes vs Riot {rt['replay_vs_riot']['equal']}/"
              f"{rt['replay_vs_riot']['cells']} cells equal; unequal {rt['replay_vs_riot']['unequal']}")
        for ch, r in rt["channels"].items():
            print(f"  {ch:<14} witnesses {r['witnesses']:>4} paired {r['paired']:>4} "
                  f"truth {r['truth_in_cells']:>4} dt {r['dt_ms']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        slim = {k: v for k, v in rep.items()}
        args.json.write_text(json.dumps(slim, indent=1, default=str), encoding="utf-8")
        print("wrote", args.json)
    if args.record:
        print("recorded:", record_ledger(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
