"""Episodes: round phases, duels, engagements, trades, executes, retakes,
rotations and lurks, derived from a match's state timeline.

[owns:episodes]

The definitions, their parameters and the player's open questions are in
docs/EPISODES.md; this module computes them and restates none of them
elsewhere. It reads one `Timeline`: ten player slots with world position,
yaw, pitch and life at any instant, and the match's events (round phases,
plants, defuses, detonations, deaths, damage). The replay layer supplies a
`source = truth` timeline (`from_replay_layer`); a vision timeline with the
same fields and `source = vision` runs through the same `derive_episodes`.

Sight rests on `line_of_sight` (the map's Weapon-blocking triangles) and the
view frustum; regions on `map_regions` (the game's callout volumes labelled
by valorant-api's callouts); the side a team plays on `rounds.side_in_round`
where the timeline names no side. Nothing here reads pixels or a parse.
"""
from __future__ import annotations

import json
from collections import Counter
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .store import DEFAULT_STORE

EPISODES_VERSION = "episodes-0.3.0"

#: Parameters (docs/EPISODES.md section 4). Every one but the eye height,
#: which `line_of_sight` takes from the game files, and the two sampling
#: rates, which are resolutions, is a default awaiting the player's answer.
PARAMS = {
    "HFOV_DEG": 103.0,            # Q1
    "SIGHT_HZ": 16.0,             # resolution
    "CONTACT_MERGE_MS": 500.0,    # Q2
    "DUEL_GAP_MS": 3000.0,        # Q3
    "ENGAGE_JOIN_MS": 5000.0,     # Q4
    "TRADE_WINDOW_MS": 5000.0,    # Q5
    "COMMIT_DWELL_MS": 2000.0,    # Q6
    "ATTEMPT_HOLD_MS": 5000.0,    # Q6
    "ROTATION_MIN_DWELL_MS": 3000.0,  # Q9
    "REGION_HOLD_MS": 1000.0,     # Q9
    "LURK_MIN_MS": 5000.0,        # Q10
    "REGION_HZ": 4.0,             # resolution
    "SIGHT_AT_KILL_MS": 1000.0,   # a report window on a duel, not a bound
}
PARAM_KIND = {
    "HFOV_DEG": "player:Q1", "SIGHT_HZ": "resolution", "CONTACT_MERGE_MS": "player:Q2",
    "DUEL_GAP_MS": "player:Q3", "ENGAGE_JOIN_MS": "player:Q4", "TRADE_WINDOW_MS": "player:Q5",
    "COMMIT_DWELL_MS": "player:Q6", "ATTEMPT_HOLD_MS": "player:Q6", "ROTATION_MIN_DWELL_MS": "player:Q9", "REGION_HOLD_MS": "player:Q9", "LURK_MIN_MS": "player:Q10",
    "REGION_HZ": "resolution", "SIGHT_AT_KILL_MS": "report window",
}
#: The engine keeps the horizontal FOV across aspect ratios
#: (`AspectRatio_MaintainXFOV`); the vertical follows at 16:9.
ASPECT = 16.0 / 9.0
SITES = ("A", "B", "C")
#: valorant-api's super-region for the attackers' spawn and approach.
ATTACKER_SIDE = "Attacker Side"
EVENT_KINDS = ("round_start", "buy_end", "round_end", "plant", "defuse", "detonate",
               "death", "damage", "revive", "match_end")


# ----------------------------------------------------------------- input

@dataclass(frozen=True)
class Slot:
    slot_id: str
    team: str
    agent: str | None = None


@dataclass
class Event:
    kind: str
    t_ms: float
    event_id: str
    actor: str | None = None      # killer, attacker, planter, defuser
    target: str | None = None     # victim
    amount: float | None = None   # damage dealt
    wallbang: bool | None = None
    cause: str | None = None      # damage or death type as the source names it
    position: tuple | None = None  # world xyz, cm
    equippable: str | None = None  # the equippable class behind a damage record
    impact: tuple | None = None   # damage: the hit's world xyz, cm, where the source gives it
    killed: bool | None = None    # damage: this hit killed its target
    side: dict | None = None      # round_start: {team: "attack"|"defence"} when the source knows


class Timeline:
    """A match's state timeline. Subclasses implement `sample`."""

    match: str
    map: str
    source: str
    slots: list[Slot]
    events: list[Event]
    stamps: dict

    def sample(self, t: np.ndarray) -> dict:
        """Arrays (n_slots, len(t)): `x`, `y`, `z` (cm, the capsule centre),
        `yaw`, `pitch` (degrees) and `alive` (bool). NaN where unread."""
        raise NotImplementedError

    @property
    def damage_read(self) -> bool:
        return any(e.kind == "damage" for e in self.events)


class ArrayTimeline(Timeline):
    """Per-slot tracks (sorted `t`, `x`, `y`, `z`, `yaw`, `pitch`) and the
    events. Positions interpolate linearly between samples at most `max_gap_ms`
    apart (NaN across a wider gap); yaw and pitch take the nearer sample.
    `alive` holds from a round's start until the slot's death in it, reopened
    by a revive, and only where a position is read."""

    def __init__(self, match: str, map_name: str, slots: list[Slot], tracks: dict,
                 events: list[Event], source: str = "truth", stamps: dict | None = None,
                 max_gap_ms: float = 250.0, alive_fn=None, children: "ChildTable | None" = None):
        self.match, self.map, self.source = match, map_name, source
        self.slots = list(slots)
        self.tracks = tracks
        self.events = sorted(events, key=lambda e: e.t_ms)
        self.stamps = dict(stamps or {})
        self.max_gap_ms = max_gap_ms
        self._alive_fn = alive_fn
        #: The slots' ability children, a table apart from `slots` and
        #: `sample` so every player-only consumer reads what it read before.
        self.children = children

    def sample(self, t) -> dict:
        t = np.atleast_1d(np.asarray(t, float))
        S = len(self.slots)
        out = {k: np.full((S, t.size), np.nan) for k in ("x", "y", "z", "yaw", "pitch")}
        for s, slot in enumerate(self.slots):
            P = self.tracks.get(slot.slot_id)
            if P is None or len(P["t"]) < 2:
                continue
            tt = np.asarray(P["t"], float)
            i = np.clip(np.searchsorted(tt, t, side="right"), 1, tt.size - 1)
            t0, t1 = tt[i - 1], tt[i]
            ok = (t >= t0) & (t <= t1) & ((t1 - t0) <= self.max_gap_ms)
            w = np.clip((t - t0) / np.where(t1 > t0, t1 - t0, 1.0), 0.0, 1.0)
            for k in ("x", "y", "z"):
                v = np.asarray(P[k], float)
                out[k][s] = np.where(ok, v[i - 1] * (1 - w) + v[i] * w, np.nan)
            near = np.where(w < 0.5, i - 1, i)
            for k in ("yaw", "pitch"):
                v = np.asarray(P.get(k, np.zeros(tt.size)), float)
                out[k][s] = np.where(ok, v[near], np.nan)
        alive = (self._alive_fn(t) if self._alive_fn is not None else alive_from_events(self, t))
        out["alive"] = alive & np.isfinite(out["x"])
        return out


class ChildTable:
    """The replay layer's `child:` entities: every ability actor, the ult
    orbs and the spike, with owner, side, life and position (REPLAY_LAYER.md).

    `cols` holds one numpy column per child: `entity_id`, `guid`, `cls`
    (the actor class), `role`, `agent`, `subject` and `team` of the owner,
    `side_rel` (to the capturing player), `ability`, `tray_key`, `mapped`,
    `unmapped_reason`, `round` (the layer's 0-based round), `t_open`,
    `t_close` (NaN where the layer saw no close), `close_basis`, `spawn_x`,
    `spawn_y` and `n_ticks`. The ticks are flat arrays sorted by child and
    time; a child with one tick (its spawn) is static.

    `position` follows `replay_layer.Layer.state_at`: linear between ticks at
    most `max_gap_ms` apart, else the last tick at or before `t` holds;
    before the first tick, NaN. Life is the caller's: this table states only
    where each child is."""

    def __init__(self, cols: dict, tick_c, tick_t, tick_x, tick_y, max_gap_ms: float):
        self.cols = cols
        self.n = int(len(cols["entity_id"]))
        o = np.lexsort((np.asarray(tick_t, float), np.asarray(tick_c, np.int64)))
        self.tick_c = np.asarray(tick_c, np.int64)[o]
        self.tick_t = np.asarray(tick_t, float)[o]
        self.tick_x = np.asarray(tick_x, float)[o]
        self.tick_y = np.asarray(tick_y, float)[o]
        self.start = np.searchsorted(self.tick_c, np.arange(self.n), side="left")
        self.end = np.searchsorted(self.tick_c, np.arange(self.n), side="right")
        self.max_gap_ms = float(max_gap_ms)

    def position(self, c, t) -> tuple[np.ndarray, np.ndarray]:
        """World x, y (cm) of child `c[i]` at replay ms `t[i]`, vectorised."""
        c = np.asarray(c, np.int64)
        t = np.asarray(t, float)
        x = np.full(c.size, np.nan)
        y = np.full(c.size, np.nan)
        if c.size == 0 or self.tick_t.size == 0:
            return x, y
        s, e = self.start[c], self.end[c]
        # the last tick at or before t within the child's span: one
        # searchsorted on (child, time) keys, the ticks sorted by both
        big = float(max(np.nanmax(np.abs(self.tick_t)), np.nanmax(np.abs(t)))) * 4.0 + 1.0
        key = self.tick_c * big + self.tick_t
        i = np.searchsorted(key, c * big + t, side="right") - 1
        ok = (i >= s) & (e > s)
        i0 = np.where(ok, i, 0)
        i1 = np.minimum(i0 + 1, self.tick_t.size - 1)
        has_next = ok & (i0 + 1 < e)
        t0, t1 = self.tick_t[i0], self.tick_t[i1]
        lerp = has_next & ((t1 - t0) <= self.max_gap_ms) & (t1 > t0)
        w = np.where(lerp, (t - t0) / np.where(t1 > t0, t1 - t0, 1.0), 0.0)
        x[ok] = (self.tick_x[i0] * (1 - w) + self.tick_x[i1] * w)[ok]
        y[ok] = (self.tick_y[i0] * (1 - w) + self.tick_y[i1] * w)[ok]
        return x, y


def children_from_layer(L, max_gap_ms: float) -> ChildTable:
    """The layer's `child:` entities as a `ChildTable` (`L` a loaded
    `replay_layer.Layer`)."""
    E, T = L.entities, L.ticks
    idx = np.flatnonzero(E["kind"] == "child")
    pos = np.full(len(E["kind"]), -1, np.int64)
    pos[idx] = np.arange(idx.size)

    def col(name, num=False):
        v = E[name][idx] if name in E else np.full(idx.size, None, object)
        if num:
            return np.array([np.nan if a is None else float(a) for a in v], float)
        return np.asarray(v, dtype=object)

    keep = np.isin(T["e"], idx)
    tick_c = pos[T["e"][keep]]
    n_ticks = np.bincount(tick_c, minlength=idx.size)
    cols = {"entity_id": col("entity_id"), "guid": col("guid"), "cls": col("class"), "role": col("role"),
            "agent": col("agent"), "subject": col("subject"), "team": col("team"),
            "side_rel": col("side_rel"), "ability": col("ability"), "tray_key": col("tray_key"),
            "mapped": col("mapped"), "unmapped_reason": col("unmapped_reason"),
            "round": col("round", num=True), "t_open": col("t_open_rep", num=True),
            "t_close": col("t_close_rep", num=True), "close_basis": col("close_basis"),
            "spawn_x": col("spawn_x", num=True), "spawn_y": col("spawn_y", num=True), "n_ticks": n_ticks}
    return ChildTable(cols, tick_c, T["t_rep"][keep], T["x"][keep], T["y"][keep], max_gap_ms)


def alive_from_events(tl: Timeline, t: np.ndarray) -> np.ndarray:
    """(n_slots, len(t)): alive from each round's start until the slot's death
    in that round, reopened by a revive. Before the first round, nobody."""
    t = np.atleast_1d(np.asarray(t, float))
    starts = np.array(sorted(e.t_ms for e in tl.events if e.kind == "round_start"))
    out = np.zeros((len(tl.slots), t.size), bool)
    if starts.size == 0:
        return out
    r_of_t = np.searchsorted(starts, t, side="right") - 1
    out[:, r_of_t >= 0] = True
    idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
    for e in tl.events:
        if e.kind not in ("death", "revive") or e.target not in idx:
            continue
        r = int(np.searchsorted(starts, e.t_ms, side="right") - 1)
        m = (r_of_t == r) & (t >= e.t_ms)
        out[idx[e.target], m] = e.kind == "revive"
    return out


# ----------------------------------------------------------------- rounds

def timeline_rounds(tl: Timeline) -> list[dict]:
    """The rounds in time order: start, buy end, end (decided), next start,
    and the plant, defuse and detonation inside each. A plant after the
    round is decided changes nothing [domain:rounds/post-round-plant-no-graphic]
    and is kept apart as `post_round_plant`."""
    ev = sorted(tl.events, key=lambda e: e.t_ms)
    starts = [e for e in ev if e.kind == "round_start"]
    match_end = max([e.t_ms for e in ev if e.kind == "match_end"] or [ev[-1].t_ms if ev else 0.0])
    out = []
    for k, s in enumerate(starts):
        nxt = starts[k + 1].t_ms if k + 1 < len(starts) else match_end
        inside = [e for e in ev if s.t_ms <= e.t_ms < nxt] if nxt > s.t_ms else []
        first = lambda kind: next((e for e in inside if e.kind == kind), None)  # noqa: E731
        be, re_, pl = first("buy_end"), first("round_end"), first("plant")
        late = None
        if pl is not None and re_ is not None and pl.t_ms >= re_.t_ms:
            pl, late = None, pl
        out.append({"round": k + 1, "start": s, "t_start": s.t_ms, "t_next": nxt,
                    "buy_end": be, "t_live": be.t_ms if be else None,
                    "end": re_, "t_end": re_.t_ms if re_ else None,
                    "plant": pl, "post_round_plant": late,
                    "defuse": first("defuse"), "detonate": first("detonate"),
                    "side": s.side})
    return out


def round_at(rounds: list[dict], t: float) -> dict | None:
    for r in rounds:
        if r["t_start"] <= t < r["t_next"]:
            return r
    return None


def attack_teams(tl: Timeline, rounds: list[dict], spawns: dict | None) -> tuple[dict, list[dict]]:
    """round -> attacking team, and the disagreements.

    The timeline's own side wins where it names one. Otherwise each team's
    living players are measured over the second half of the buy phase, held
    behind their barrier: the team whose median distance to the attackers'
    `Spawn` callout, less its distance to the defenders', is smaller
    attacks. A planter's team, where the timeline names one, is a second
    witness. `rounds.side_in_round` then checks every round against round
    1's side; a disagreement is stored, never used to fill a round."""
    from .rounds import SIDES, side_in_round

    teams = sorted({s.team for s in tl.slots})
    team = np.array([s.team for s in tl.slots])
    out, notes, basis = {}, [], {}
    for r in rounds:
        side = r.get("side") or {}
        att = next((tm for tm, sd in side.items() if sd == "attack"), None)
        if att is not None:
            out[r["round"]], basis[r["round"]] = att, "timeline"
            continue
        spawn = None
        if spawns and {"attack", "defence"} <= set(spawns) and r["t_live"] is not None:
            g = np.linspace((r["t_start"] + r["t_live"]) / 2.0, r["t_live"], 9)
            smp = tl.sample(g)
            xy = np.stack([smp["x"], smp["y"]], -1)
            lean = (np.linalg.norm(xy - spawns["attack"], axis=-1)
                    - np.linalg.norm(xy - spawns["defence"], axis=-1))
            lean = np.where(smp["alive"], lean, np.nan)
            med = {tm: float(np.nanmedian(lean[team == tm])) if np.isfinite(lean[team == tm]).any()
                   else np.nan for tm in teams}
            if len(teams) == 2 and all(np.isfinite(v) for v in med.values()):
                a, b = teams
                if med[a] != med[b]:
                    spawn = a if med[a] < med[b] else b
        planter = None
        if r["plant"] is not None and r["plant"].actor is not None:
            planter = next((s.team for s in tl.slots if s.slot_id == r["plant"].actor), None)
        if spawn and planter and spawn != planter:
            notes.append({"round": r["round"], "kind": "spawn_planter_disagree",
                          "spawn": spawn, "planter": planter})
        att = spawn or planter
        if att is not None:
            out[r["round"]], basis[r["round"]] = att, "spawn" if spawn else "planter"
    if rounds and 1 in out and len(teams) == 2:
        t0 = out[1]
        for r in rounds:
            side, _why = side_in_round(r["round"], SIDES[0])
            rule = t0 if side == SIDES[0] else next(tm for tm in teams if tm != t0)
            if r["round"] in out and out[r["round"]] != rule:
                notes.append({"round": r["round"], "kind": "side_rule_disagree",
                              "observed": out[r["round"]], "rule_from_round_1": rule,
                              "basis": basis.get(r["round"])})
    for r in rounds:
        if r["round"] not in out:
            notes.append({"round": r["round"], "kind": "attack_team_unread"})
    return out, notes


# ----------------------------------------------------------------- sight

def frustum(yaw_deg, pitch_deg, d, hfov_deg: float) -> np.ndarray:
    """True where direction `d` (..., 3) lies inside the view frustum of a
    camera at `yaw_deg`, `pitch_deg` (pitch wrapped to +-180, up positive)."""
    y = np.radians(yaw_deg)
    p = np.radians(((np.asarray(pitch_deg, float) + 180.0) % 360.0) - 180.0)
    cy, sy, cp, sp = np.cos(y), np.sin(y), np.cos(p), np.sin(p)
    f = np.stack([cp * cy, cp * sy, sp], -1)
    r = np.stack([-sy, cy, np.zeros_like(y)], -1)
    u = np.stack([-sp * cy, -sp * sy, cp], -1)
    df, dr, du = (d * f).sum(-1), (d * r).sum(-1), (d * u).sum(-1)
    th = math.tan(math.radians(hfov_deg) / 2.0)
    tv = th / ASPECT
    with np.errstate(invalid="ignore"):
        return (df > 0) & (np.abs(dr) <= df * th) & (np.abs(du) <= df * tv)


def sight(smp: dict, slots: list[Slot], occ, hfov_deg: float) -> np.ndarray:
    """sees[i, j, k]: slot i sees opposing slot j at sample k: j's body centre
    or eye lies in i's frustum and the segment from i's eye to it is clear."""
    from .line_of_sight import EYE_ABOVE_CENTRE_CM

    S, T = smp["x"].shape
    c = np.stack([smp["x"], smp["y"], smp["z"]], -1)         # (S, T, 3)
    e = c.copy()
    e[..., 2] += EYE_ABOVE_CENTRE_CM
    team = np.array([s.team for s in slots])
    sees = np.zeros((S, S, T), bool)
    pairs = [(i, j) for i in range(S) for j in range(S) if team[i] != team[j]]
    if not pairs:
        return sees
    I = np.array([p[0] for p in pairs])
    J = np.array([p[1] for p in pairs])
    live = smp["alive"][I] & smp["alive"][J]                   # (P, T)
    origin = e[I]                                              # (P, T, 3)
    hit = np.zeros(live.shape, bool)
    for tgt in (c, e):
        d = tgt[J] - origin
        cand = live & frustum(smp["yaw"][I], smp["pitch"][I], d, hfov_deg)
        cand &= ~hit
        if cand.any():
            pi, ti = np.nonzero(cand)
            blocked = occ.blocked(origin[pi, ti], tgt[J][pi, ti])
            hit[pi[~blocked], ti[~blocked]] = True
    sees[I, J] = hit
    return sees


def merged_runs(mask: np.ndarray, merge: int) -> list[tuple[int, int]]:
    """(first, last) sample indices of True runs, runs joined across False
    gaps of at most `merge` samples."""
    m = np.asarray(mask, bool)
    if not m.any():
        return []
    idx = np.flatnonzero(m)
    cut = np.flatnonzero(np.diff(idx) > merge + 1)
    starts = np.concatenate([[idx[0]], idx[cut + 1]])
    ends = np.concatenate([idx[cut], [idx[-1]]])
    return list(zip(starts.tolist(), ends.tolist()))


# ----------------------------------------------------------------- derive

@dataclass
class Derived:
    header: dict
    episodes: list[dict] = field(default_factory=list)
    contacts: list[dict] = field(default_factory=list)
    unassigned_deaths: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    acts: list[dict] = field(default_factory=list)

    def rows(self) -> list[dict]:
        return ([{"row": "header", **self.header}]
                + [{"row": "episode", **e} for e in self.episodes]
                + [{"row": "act", **a} for a in self.acts]
                + [{"row": "contact", **c} for c in self.contacts]
                + [{"row": "unassigned_death", **d} for d in self.unassigned_deaths]
                + [{"row": "note", **n} for n in self.notes])


def derive_episodes(tl: Timeline, occ=None, regions=None, params: dict | None = None,
                    spawns: dict | None = None, pen=None) -> Derived:
    """Every episode of the match. `occ` (`line_of_sight.Occluders`),
    `regions` (`map_regions.Regions`), `spawns` (`map_regions.spawn_points`)
    and `pen` (`wall_penetration.Penetration`) default to the map's stored
    tables."""
    P = dict(PARAMS, **(params or {}))
    if occ is None:
        from .line_of_sight import Occluders
        occ = Occluders(tl.map)
    if pen is None and getattr(occ, "table", "synthetic") != "synthetic":
        from .wall_penetration import Penetration
        pen = Penetration(occ)
    if regions is None:
        from .map_regions import Regions
        try:
            regions = Regions.load(tl.map)
        except FileNotFoundError:
            regions = None
    rounds = timeline_rounds(tl)
    if spawns is None:
        from .map_regions import spawn_points
        spawns = spawn_points(tl.map)
    attack, side_notes = attack_teams(tl, rounds, spawns)
    team_of = {s.slot_id: s.team for s in tl.slots}
    idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
    out = Derived(header={
        "version": EPISODES_VERSION, "match": tl.match, "map": tl.map, "source": tl.source,
        "stamps": tl.stamps, "inputs": {}, "params": P, "param_kind": PARAM_KIND,
        "damage_read": tl.damage_read,
        "line_of_sight": occ.provenance() if hasattr(occ, "provenance") else None,
        "regions": regions.provenance() if regions is not None else None,
        "slots": [{"slot_id": s.slot_id, "team": s.team} for s in tl.slots],
        "attack_team": {str(k): v for k, v in attack.items()},
        "wall_penetration": pen.provenance() if pen is not None and hasattr(pen, "provenance") else None,
    }, notes=list(side_notes))
    acts = classify_acts(tl, occ, pen, team_of)
    out.header["act_counts"] = dict(Counter(a["class"] for a in acts.values()))
    out.acts = [a for a in acts.values()
                if a["act"] == "death" or a["killing"] or a["class"] in ("gun_wallbang", "gun_blocked")]

    deaths = [e for e in tl.events if e.kind == "death"]
    for d in deaths:
        r = round_at(rounds, d.t_ms)
        why = ("outside_round" if r is None else
               "no_killer" if d.actor is None or d.actor not in team_of else
               "same_team" if team_of.get(d.actor) == team_of.get(d.target) else None)
        if why:
            out.unassigned_deaths.append({"event_id": d.event_id, "t_ms": d.t_ms,
                                          "round": r["round"] if r else None,
                                          "victim": d.target, "killer": d.actor,
                                          "cause": d.cause, "reason": why})

    for r in rounds:
        out.episodes.extend(_phases(r, attack.get(r["round"]), tl, team_of))
        if r["t_live"] is None:
            out.notes.append({"round": r["round"], "kind": "no_buy_end",
                              "reason": "sight sampled from the round's start"})
        t0 = r["t_live"] if r["t_live"] is not None else r["t_start"]
        dt = 1000.0 / P["SIGHT_HZ"]
        grid = np.arange(t0, r["t_next"], dt)
        if grid.size == 0:
            continue
        smp = tl.sample(grid)
        sees = sight(smp, tl.slots, occ, P["HFOV_DEG"])
        contacts = _contacts(r, grid, sees, tl.slots, P)
        out.contacts.extend(contacts)
        bouts = _duels(r, tl, grid, sees, contacts, team_of, idx, P, acts)
        duels = [b for b in bouts if b["kind"] == "duel"]
        engagements = _engagements(r, duels, contacts, tl, team_of, P)
        out.episodes.extend(bouts)
        out.episodes.extend(engagements)
        out.episodes.extend(_trades(r, tl, grid, sees, smp, duels, engagements, team_of, idx, P))
        if regions is not None and r["t_live"] is not None:
            ex = _execute_retake_lurk(r, tl, regions, attack.get(r["round"]), team_of, idx,
                                      engagements, contacts, P)
            out.episodes.extend(ex)
            out.episodes.extend(_rotations(r, tl, regions, idx, P))
    return out


# ----------------------------------------------------------------- phases

def _ep(kind: str, r: dict, t0, t1, **kw) -> dict:
    return {"episode_id": f"{kind}:R{r['round']}:{int(round(t0 or 0))}", "kind": kind,
            "round": r["round"], "t_start_ms": t0, "t_end_ms": t1, **kw}


def _phases(r: dict, att: str | None, tl: Timeline, team_of: dict) -> list[dict]:
    out = []
    t_end = r["t_end"]
    pl = r["plant"]
    ev_ids = lambda *es: [e.event_id for e in es if e is not None]  # noqa: E731
    if r["t_live"] is not None:
        out.append(_ep("phase_buy", r, r["t_start"], r["t_live"],
                       evidence=ev_ids(r["start"], r["buy_end"])))
    live_end = pl.t_ms if pl is not None else t_end
    if r["t_live"] is not None:
        out.append(_ep("phase_live", r, r["t_live"], live_end,
                       evidence=ev_ids(r["buy_end"], pl, r["end"])))
    if pl is not None:
        out.append(_ep("phase_post_plant", r, pl.t_ms, t_end,
                       participants={"planter": pl.actor},
                       evidence=ev_ids(pl, r["defuse"], r["detonate"], r["end"])))
    if t_end is not None:
        out.append(_ep("phase_round_over", r, t_end, r["t_next"], evidence=ev_ids(r["end"])))
    # Outcome on the round's last play phase.
    reason, winner, decisive = _round_result(r, att, tl, team_of)
    last = next((e for e in reversed(out) if e["kind"] in ("phase_post_plant", "phase_live")), None)
    if last is not None:
        last["outcome"] = {"end_reason": reason, "winner": winner, "attack_team": att,
                           "decisive_ms": decisive,
                           "end_lag_ms": None if (decisive is None or t_end is None)
                           else round(t_end - decisive, 1)}
    return out


#: Deaths are logged up to a few tens of ms after the round-end phase
#: change; life is read this long after it.
END_SETTLE_MS = 100.0


def _round_result(r: dict, att, tl: Timeline, team_of: dict):
    """(end_reason, winning team, the deciding event's time).

    Before a plant a team with nobody alive just after the round's end loses
    (`elimination`), and with both teams standing the defenders win (`time`).
    After a plant only a defuse wins for the defenders; with every defender
    dead it is `elimination`, else `detonation`, decided at the round's end
    (the timeline carries no detonation event where its source has none).
    Life comes from the timeline, which carries revives; the deciding time is
    the eliminated team's last death."""
    teams = sorted(set(team_of.values()))
    defe = next((tm for tm in teams if tm != att), None) if att else None
    if r["defuse"] is not None:
        return "defuse", defe, r["defuse"].t_ms
    if r["detonate"] is not None:
        return "detonation", att, r["detonate"].t_ms
    t_end = r["t_end"]
    if t_end is None:
        return None, None, None
    t_look = min(t_end + END_SETTLE_MS, r["t_next"] - 1.0)
    smp = tl.sample(np.array([t_look]))
    alive = {s.slot_id: bool(smp["alive"][k, 0]) for k, s in enumerate(tl.slots)}
    out = [tm for tm in teams if not any(alive[s] for s, t2 in team_of.items() if t2 == tm)]

    def last_death(tm):
        return max((e.t_ms for e in tl.events if e.kind == "death" and team_of.get(e.target) == tm
                    and r["t_start"] <= e.t_ms <= t_look), default=None)

    if r["plant"] is not None:
        if defe is not None and defe in out:
            return "elimination", att, last_death(defe)
        return "detonation", att, None
    if len(out) == 1:
        loser = out[0]
        return "elimination", next(tm for tm in teams if tm != loser), last_death(loser)
    return "time", defe, None


# ----------------------------------------------------------------- contacts

def _contacts(r: dict, grid: np.ndarray, sees: np.ndarray, slots: list[Slot], P: dict) -> list[dict]:
    dt = 1000.0 / P["SIGHT_HZ"]
    merge = int(round(P["CONTACT_MERGE_MS"] / dt))
    out = []
    S = len(slots)
    for i in range(S):
        for j in range(i + 1, S):
            if slots[i].team == slots[j].team:
                continue
            a, b = sees[i, j], sees[j, i]
            for s, e in merged_runs(a | b, merge):
                ab, ba = a[s:e + 1], b[s:e + 1]
                first = ("both" if ab[0] and ba[0] else slots[i].slot_id if ab[0]
                         else slots[j].slot_id)
                out.append({"contact_id": f"contact:R{r['round']}:{slots[i].slot_id[:8]}:"
                                          f"{slots[j].slot_id[:8]}:{int(grid[s])}",
                            "round": r["round"], "a": slots[i].slot_id, "b": slots[j].slot_id,
                            "t_start_ms": float(grid[s]), "t_end_ms": float(grid[e]),
                            "first_seer": first, "mutual": bool(ab.any() and ba.any()),
                            "a_sees_share": round(float(ab.mean()), 3),
                            "b_sees_share": round(float(ba.mean()), 3),
                            "sample_ms": dt})
    return out


def _pair_contacts(contacts: list[dict], a: str, b: str) -> list[dict]:
    return [c for c in contacts if {c["a"], c["b"]} == {a, b}]


# ----------------------------------------------------------------- acts

#: A killing record is logged this close to its death event.
KILL_MATCH_MS = 500.0
ACT_CLASSES = ("gun_sight", "gun_wallbang", "gun_blocked", "ability", "melee", "other", "unread")


def classify_acts(tl: Timeline, occ, pen, team_of: dict) -> dict[str, dict]:
    """Every damage and death act between opponents, classed by what reached
    the target (docs/EPISODES.md 2.1) [domain:weapons/kill-line-of-sight].

    The equippable's kind (`equippables.equippable_kind`) and the replay's
    own `wall_penetration` flag decide the class; the map's table only tests
    it: a gun hit with no flag needs a clear line from the shooter's eye to
    the hit (`gun_sight`, else `gun_blocked`); a flagged one is a
    `gun_wallbang`, and `wall_penetration` lists what lies on its line. A
    death takes the class of its killing hit (the damage record marked
    `killed` on the same victim within `KILL_MATCH_MS`), else `unread`."""
    from .equippables import equippable_kind
    from .line_of_sight import EYE_ABOVE_CENTRE_CM

    idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
    opp = [e for e in tl.events if e.kind in ("damage", "death") and e.actor in idx
           and e.target in idx and team_of.get(e.actor) != team_of.get(e.target)]
    dmg = [e for e in opp if e.kind == "damage"]
    out: dict[str, dict] = {}
    if dmg:
        t = np.array([e.t_ms for e in dmg])
        smp = tl.sample(t)
        ia = np.array([idx[e.actor] for e in dmg])
        iv = np.array([idx[e.target] for e in dmg])
        n = np.arange(len(dmg))
        eye = np.stack([smp["x"][ia, n], smp["y"][ia, n], smp["z"][ia, n] + EYE_ABOVE_CENTRE_CM], -1)
        body = np.stack([smp["x"][iv, n], smp["y"][iv, n], smp["z"][iv, n]], -1)
        head = body + np.array([0.0, 0.0, EYE_ABOVE_CENTRE_CM])
        has_imp = np.array([e.impact is not None for e in dmg])
        tgt = np.where(has_imp[:, None], np.array([e.impact if e.impact is not None else (0, 0, 0)
                                                   for e in dmg], float), body)
        ok = np.isfinite(eye).all(1) & np.isfinite(tgt).all(1)
        clear = ok & ~occ.blocked(eye, tgt)
        clear |= ok & ~has_imp & ~occ.blocked(eye, head)
        kinds = [equippable_kind(e.equippable) for e in dmg]
        cls = []
        for e, k, c, o in zip(dmg, kinds, clear, ok):
            if k == "gun":
                cls.append("gun_wallbang" if e.wallbang else "gun_sight" if c else
                           "gun_blocked" if o else "unread")
            else:
                cls.append({"ability": "ability", "melee": "melee", "unread": "unread"}.get(k, "other"))
        geo = {}
        want = [i for i, c in enumerate(cls) if c in ("gun_wallbang", "gun_blocked")]
        if pen is not None and want:
            for i, g in zip(want, pen.lines(eye[want], tgt[want])):
                geo[i] = g
        for i, e in enumerate(dmg):
            out[e.event_id] = {
                "event_id": e.event_id, "t_ms": e.t_ms, "act": "damage", "actor": e.actor,
                "target": e.target, "class": cls[i], "equippable": e.equippable,
                "equippable_kind": kinds[i], "wall_penetration": e.wallbang,
                "line_clear": bool(clear[i]) if ok[i] else None,
                "line_to": "impact" if has_imp[i] else "body_or_eye",
                "killing": bool(e.killed), "geometry": geo.get(i)}
    for d in (e for e in opp if e.kind == "death"):
        hit = min((a for a in out.values() if a["act"] == "damage" and a["killing"]
                   and a["target"] == d.target and abs(a["t_ms"] - d.t_ms) <= KILL_MATCH_MS),
                  key=lambda a: abs(a["t_ms"] - d.t_ms), default=None)
        out[d.event_id] = {"event_id": d.event_id, "t_ms": d.t_ms, "act": "death",
                           "actor": d.actor, "target": d.target,
                           "class": hit["class"] if hit else "unread",
                           "killing_act": hit["event_id"] if hit else None,
                           "reason": None if hit else "no_killing_record",
                           "killing": False}
    return out


# ----------------------------------------------------------------- duels

def _duels(r, tl, grid, sees, contacts, team_of, idx, P, act_class=None) -> list[dict]:
    t_lo, t_hi = r["t_start"], r["t_next"]
    acts = [e for e in tl.events
            if e.kind in ("damage", "death") and t_lo <= e.t_ms < t_hi
            and e.actor in team_of and e.target in team_of
            and team_of[e.actor] != team_of[e.target]]
    deaths = [e for e in tl.events if e.kind == "death" and t_lo <= e.t_ms < t_hi]
    first_kill = min((e.t_ms for e in deaths if e.actor in team_of
                      and team_of.get(e.actor) != team_of.get(e.target)), default=None)
    by_pair: dict[tuple, list[Event]] = {}
    for e in sorted(acts, key=lambda e: (e.t_ms, e.kind != "damage")):
        by_pair.setdefault(tuple(sorted((e.actor, e.target))), []).append(e)
    dt = 1000.0 / P["SIGHT_HZ"]
    out = []
    for (a, b), evs in by_pair.items():
        pc = _pair_contacts(contacts, a, b)
        bouts, cur = [], []
        for e in evs:
            if cur:
                kill = next((x for x in cur if x.kind == "death"), None)
                if kill is not None:
                    # A kill ends the bout; the pair's later acts within the gap
                    # are its tail: the killing hit logged after the death, or
                    # damage a dead player's utility still deals.
                    split = e.kind == "death" or e.t_ms - kill.t_ms > P["DUEL_GAP_MS"]
                else:
                    gap_ok = e.t_ms - cur[-1].t_ms <= P["DUEL_GAP_MS"]
                    spanned = any(c["t_start_ms"] <= cur[-1].t_ms
                                  and c["t_end_ms"] >= e.t_ms - dt for c in pc)
                    split = not (gap_ok or spanned)
                if split:
                    bouts.append(cur)
                    cur = []
            cur.append(e)
        if cur:
            bouts.append(cur)
        for bout in bouts:
            out.append(_duel(r, a, b, bout, pc, deaths, grid, sees, idx, first_kill, P, act_class or {}))
    return out


def _covering(pc: list[dict], t: float, slack: float) -> dict | None:
    hits = [c for c in pc if c["t_start_ms"] - slack <= t <= c["t_end_ms"] + slack]
    return min(hits, key=lambda c: c["t_start_ms"]) if hits else None


def _duel(r, a, b, bout, pc, deaths, grid, sees, idx, first_kill, P, act_class) -> dict:
    dt = 1000.0 / P["SIGHT_HZ"]
    a0, aL = bout[0].t_ms, bout[-1].t_ms
    c0 = _covering(pc, a0, P["CONTACT_MERGE_MS"])
    start = min(a0, c0["t_start_ms"]) if c0 else a0
    kill = next((e for e in bout if e.kind == "death"), None)
    if kill is not None:
        end, outcome = kill.t_ms, {"result": "killed", "killer": kill.actor, "victim": kill.target}
    else:
        cL = _covering(pc, aL, P["CONTACT_MERGE_MS"])
        end = max(aL, cL["t_end_ms"]) if cL else aL
        third = next((e for e in deaths if e.target in (a, b) and e.actor not in (a, b)
                      and start <= e.t_ms <= end), None)
        if third is not None:
            end = third.t_ms
            outcome = {"result": "third_party", "victim": third.target, "killer": third.actor}
        else:
            outcome = {"result": "disengaged"}
    k0 = int(np.searchsorted(grid, start - dt / 2))
    k1 = int(np.searchsorted(grid, end + dt / 2))
    ia, ib = idx[a], idx[b]
    ab, ba = sees[ia, ib, k0:k1], sees[ib, ia, k0:k1]
    fa = int(np.argmax(ab)) if ab.any() else None
    fb = int(np.argmax(ba)) if ba.any() else None
    first_seer = (None if fa is None and fb is None else a if fb is None
                  else b if fa is None else a if fa < fb else b if fb < fa else "both")
    dmg = [e for e in bout if e.kind == "damage"]
    sight_at_kill = None
    if kill is not None:
        ik, iv = idx[kill.actor], idx[kill.target]
        k_lo = int(np.searchsorted(grid, kill.t_ms - P["SIGHT_AT_KILL_MS"]))
        k_hi = int(np.searchsorted(grid, kill.t_ms, side="right"))
        sight_at_kill = bool(sees[ik, iv, k_lo:k_hi].any())
    # Wallbangs and ability acts need no sight [domain:weapons/kill-line-of-sight];
    # a bout with no kill, no sight and only gun hits the geometry calls
    # blocked is `remote_damage`, a disagreement between the replay and the table.
    classes = Counter(act_class[e.event_id]["class"] for e in bout if e.event_id in act_class)
    kill_act = act_class.get(kill.event_id) if kill is not None else None
    blind_ok = bool(classes.get("gun_wallbang") or classes.get("ability"))
    kind = "duel" if (kill is not None or ab.any() or ba.any() or blind_ok) else "remote_damage"
    return _ep(kind, r, start, end,
               participants={"a": a, "b": b},
               outcome=outcome,
               first_seer=first_seer,
               first_hitter=dmg[0].actor if dmg else None,
               first_hitter_reason=None if dmg else "no_damage_events",
               mutual=bool(ab.any() and ba.any()),
               sight=bool(ab.any() or ba.any()),
               sight_at_kill=sight_at_kill,
               wallbang=any(bool(e.wallbang) for e in dmg) if dmg else None,
               damage={a: round(sum(e.amount or 0.0 for e in dmg if e.actor == a), 1),
                       b: round(sum(e.amount or 0.0 for e in dmg if e.actor == b), 1)},
               hits=len(dmg),
               opening=bool(kill is not None and first_kill is not None
                            and kill.t_ms == first_kill),
               kill_event=kill.event_id if kill is not None else None,
               kill_class=kill_act["class"] if kill_act else None,
               act_classes=dict(classes),
               members=[e.event_id for e in bout],
               evidence=[e.event_id for e in bout] + ([c0["contact_id"]] if c0 else []))


# ----------------------------------------------------------------- engagements

def _engagements(r, duels, contacts, tl, team_of, P) -> list[dict]:
    n = len(duels)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    ppl = [set(d["participants"].values()) for d in duels]
    for x in range(n):
        for y in range(x + 1, n):
            dx, dy = duels[x], duels[y]
            gap = max(dx["t_start_ms"], dy["t_start_ms"]) - min(dx["t_end_ms"], dy["t_end_ms"])
            if ppl[x] & ppl[y] and gap <= P["ENGAGE_JOIN_MS"]:
                union(x, y)
            elif gap <= 0:
                lo = max(dx["t_start_ms"], dy["t_start_ms"])
                hi = min(dx["t_end_ms"], dy["t_end_ms"])
                linked = any(c["t_start_ms"] <= hi and c["t_end_ms"] >= lo
                             and ((c["a"] in ppl[x] and c["b"] in ppl[y])
                                  or (c["a"] in ppl[y] and c["b"] in ppl[x]))
                             for c in contacts)
                if linked:
                    union(x, y)
    groups: dict[int, list[int]] = {}
    for x in range(n):
        groups.setdefault(find(x), []).append(x)
    out = []
    teams = sorted(set(team_of.values()))
    for members in sorted(groups.values(), key=lambda g: min(duels[i]["t_start_ms"] for i in g)):
        ds = [duels[i] for i in members]
        t0 = min(d["t_start_ms"] for d in ds)
        t1 = max(d["t_end_ms"] for d in ds)
        combat = set().union(*(ppl[i] for i in members))
        kills = [d["outcome"] for d in ds if d["outcome"]["result"] == "killed"]
        k_by = {tm: sum(1 for k in kills if team_of[k["killer"]] == tm) for tm in teams}
        d_by = {tm: sum(1 for k in kills if team_of[k["victim"]] == tm) for tm in teams}
        dead = {k["victim"] for k in kills} | {d["outcome"]["victim"] for d in ds
                                               if d["outcome"]["result"] == "third_party"}
        surv = {tm: sorted(p for p in combat if team_of[p] == tm and p not in dead) for tm in teams}
        witnesses = sorted({p for c in contacts if c["t_start_ms"] <= t1 and c["t_end_ms"] >= t0
                            for p, q in ((c["a"], c["b"]), (c["b"], c["a"]))
                            if q in combat and p not in combat})
        best = sorted(k_by.items(), key=lambda kv: -kv[1])
        winner = ("even" if len(best) > 1 and best[0][1] == best[1][1] else best[0][0])
        eng = _ep("engagement", r, t0, t1,
                  participants={"combatants": sorted(combat), "witnesses": witnesses},
                  outcome={"kills": k_by, "deaths": d_by, "survivors": surv, "winner": winner},
                  members=[d["episode_id"] for d in ds],
                  kill_events=[d["kill_event"] for d in ds if d["kill_event"]])
        for d in ds:
            d["engagement_id"] = eng["episode_id"]
        out.append(eng)
    return out


# ----------------------------------------------------------------- trades

def _trades(r, tl, grid, sees, smp, duels, engagements, team_of, idx, P) -> list[dict]:
    kills = sorted([e for e in tl.events if e.kind == "death" and r["t_start"] <= e.t_ms < r["t_next"]
                    and e.actor in team_of and e.target in team_of
                    and team_of[e.actor] != team_of[e.target]], key=lambda e: e.t_ms)
    eng_of = {}
    for d in duels:
        if d["outcome"]["result"] == "killed":
            eng_of[d["kill_event"]] = d.get("engagement_id")
    revives = [e for e in tl.events if e.kind == "revive" and r["t_start"] <= e.t_ms < r["t_next"]]
    out = []
    for k1 in kills:
        A, B = k1.actor, k1.target
        k2 = next((e for e in kills if e.target == A and team_of[e.actor] == team_of[B]
                   and 0 < e.t_ms - k1.t_ms <= P["TRADE_WINDOW_MS"]), None)
        if k2 is None:
            continue
        C = k2.actor
        k = int(np.clip(np.searchsorted(grid, k1.t_ms), 0, len(grid) - 1))
        saw = bool(sees[idx[C], idx[A], max(0, k - 1):k + 2].any())
        d = None
        pc, pa = idx[C], idx[A]
        x = np.array([smp["x"][pc, k] - smp["x"][pa, k], smp["y"][pc, k] - smp["y"][pa, k],
                      smp["z"][pc, k] - smp["z"][pa, k]])
        if np.isfinite(x).all():
            d = round(float(np.linalg.norm(x)) / 100.0, 2)
        out.append(_ep("trade", r, k1.t_ms, k2.t_ms,
                       participants={"traded": B, "killer": A, "trader": C},
                       outcome={"result": "traded", "lag_ms": round(k2.t_ms - k1.t_ms, 1)},
                       same_engagement=(eng_of.get(k1.event_id) is not None
                                        and eng_of.get(k1.event_id) == eng_of.get(k2.event_id)),
                       trader_saw_killer_at_t1=saw, trader_distance_m=d,
                       traded_revived=any(v.target == B and v.t_ms > k1.t_ms for v in revives),
                       members=[k1.event_id, k2.event_id], evidence=[k1.event_id, k2.event_id]))
    return out


# ----------------------------------------------------------------- regions

def _region_series(tl, regions, t0, t1, P, mode: str = "super"):
    """Grid, region codes (n_slots, n) into `regions.super_labels` (-1 none)
    and life, at `REGION_HZ`. Mode `site` codes only a site's own `Site`
    volume, `hold` every volume but a `Link`; each gives the rest -1. A
    sample outside every volume keeps the last code held."""
    dt = 1000.0 / P["REGION_HZ"]
    g = np.arange(t0, t1 + dt / 2, dt)
    if g.size == 0:
        return g, None, None
    smp = tl.sample(g)
    S = len(tl.slots)
    pts = np.stack([smp["x"], smp["y"], smp["z"]], -1).reshape(-1, 3)
    code_of = {"super": regions.super_code_of, "site": regions.site_code_of,
               "hold": regions.hold_code_of}[mode]
    c = code_of(pts).reshape(S, g.size)
    have = np.where(c != -1, np.arange(g.size)[None, :], -1)
    last = np.maximum.accumulate(have, axis=1)
    filled = np.where(last >= 0, np.take_along_axis(c, np.maximum(last, 0), axis=1), -1)
    filled = np.maximum(filled, -1)
    hold = int(round(P["REGION_HOLD_MS"] / dt))
    for s in range(S):
        filled[s] = _debounce(filled[s], hold)
    return g, filled.astype(np.int16), smp["alive"]


def _debounce(row: np.ndarray, hold: int) -> np.ndarray:
    """A super-region entered for fewer than `hold` samples (a step over a
    boundary and back) keeps the one held before it."""
    out = row.copy()
    runs = _label_runs(out)
    for i, (_v, a, b) in enumerate(runs):
        if i > 0 and b - a + 1 < hold and i + 1 < len(runs):
            out[a:b + 1] = out[a - 1]
    return out


def _label_runs(row: np.ndarray) -> list[tuple[int, int, int]]:
    """(value, first, last) runs of equal values in a 1-D int array."""
    if row.size == 0:
        return []
    cut = np.flatnonzero(np.diff(row) != 0)
    starts = np.concatenate([[0], cut + 1])
    ends = np.concatenate([cut, [row.size - 1]])
    return list(zip(row[starts].tolist(), starts.tolist(), ends.tolist()))


def _site_codes(regions) -> dict[int, str]:
    return {i: x for i, x in enumerate(regions.super_labels) if x in SITES}


def _execute_retake_lurk(r, tl, regions, att, team_of, idx, engagements, contacts, P) -> list[dict]:
    """The round's site attempts (`execute`) and their lurks, and its retake
    or contested plant."""
    out = []
    if att is None:
        return out
    pl = r["plant"]
    t_end = r["t_end"] if r["t_end"] is not None else r["t_next"]
    g, code, alive = _region_series(tl, regions, r["t_live"], t_end, P)
    if code is None:
        return out
    _g, on_site, _a = _region_series(tl, regions, r["t_live"], t_end, P, mode="site")
    sites = _site_codes(regions)
    labels = regions.super_labels
    atk = np.array([k for k, s in enumerate(tl.slots) if s.team == att])
    dfn = np.array([k for k, s in enumerate(tl.slots) if s.team != att])
    ids = np.array([s.slot_id for s in tl.slots], dtype=object)
    plant_site = None
    if pl is not None:
        pos = pl.position
        if pos is None and pl.actor in idx:
            sp = tl.sample(np.array([pl.t_ms]))
            k = idx[pl.actor]
            pos = (sp["x"][k, 0], sp["y"][k, 0], sp["z"][k, 0])
        if pos is not None:
            pc = int(regions.super_code_of(np.array([pos], float))[0])
            plant_site = labels[pc] if pc >= 0 else None
    attempts = _attempts(r, tl, g, on_site, code, alive, atk, dfn, ids, sites, labels, pl,
                         plant_site, contacts, t_end, P)
    out.extend(attempts)
    seen: set = set()
    for ex in attempts:
        for lk in _lurks(r, tl, g, code, alive, atk, ex, ids, labels, engagements, P):
            key = (lk["participants"]["lurker"], lk["t_start_ms"])
            if key not in seen:
                seen.add(key)
                out.append(lk)
    # Retake, or a plant with a defender on site.
    if pl is not None and plant_site is not None:
        kp = int(np.clip(np.searchsorted(g, pl.t_ms), 0, g.size - 1))
        sc = labels.index(plant_site)
        d_alive = alive[dfn, kp]
        living = ids[dfn][d_alive].tolist()
        on_site_d = ids[dfn][d_alive & (code[dfn, kp] == sc)].tolist()
        if living and not on_site_d:
            dd = sorted(e.t_ms for e in tl.events if e.kind == "death" and e.target in living
                        and pl.t_ms <= e.t_ms <= t_end)
            if r["defuse"] is not None:
                t1, res = r["defuse"].t_ms, "defused"
            elif r["detonate"] is not None:
                t1, res = r["detonate"].t_ms, "detonated"
            elif len(dd) >= len(living):
                t1, res = dd[len(living) - 1], "defenders_eliminated"
            else:
                t1, res = t_end, "unresolved"
            inside = (alive[dfn][:, kp:] & (code[dfn][:, kp:] == sc)).any(0)
            entry = float(g[kp + int(np.argmax(inside))]) if inside.any() else None
            out.append(_ep("retake", r, pl.t_ms, t1,
                           participants={"defenders": living,
                                         "attackers": ids[atk][alive[atk, kp]].tolist()},
                           outcome={"result": res, "site": plant_site}, entry_ms=entry))
        elif living:
            out.append(_ep("contested_plant", r, pl.t_ms, pl.t_ms,
                           participants={"on_site": on_site_d, "defenders": living},
                           outcome={"site": plant_site}))
    return out


def _attempts(r, tl, g, on_site, code, alive, atk, dfn, ids, sites, labels, pl, plant_site,
              contacts, t_end, P) -> list[dict]:
    """Site attempts before the plant (docs/EPISODES.md 3.5).

    An attacker commits to a site when he stands on its site callout and
    stays `COMMIT_DWELL_MS`, makes contact with a defender, trades an act
    with one, or plants there; the attempt opens at his entry. Attackers who
    commit to the same site while it is held, or within `ATTEMPT_HOLD_MS` of
    its last committed presence, join it. A plant no committed attacker
    covers opens a `plant` attempt of the attackers in the site's area."""
    dt = 1000.0 / P["REGION_HZ"]
    t_cut = pl.t_ms if pl is not None else t_end
    atk_ids = set(ids[atk].tolist())
    def_ids = set(ids[dfn].tolist())
    acts = [e for e in tl.events if e.kind in ("damage", "death") and g[0] <= e.t_ms <= t_cut
            and ((e.actor in atk_ids and e.target in def_ids)
                 or (e.actor in def_ids and e.target in atk_ids))]
    commits, presence = [], {}
    for a in atk.tolist():
        sid = ids[a]
        row = np.where(alive[a] & (g <= t_cut + 1e-6), on_site[a], -1)
        for c, s, e in _label_runs(row):
            if c not in sites:
                continue
            t0, t1 = float(g[s]), float(g[e]) + dt
            presence.setdefault((a, c), []).append((t0, t1))
            cand = []
            if t1 - t0 >= P["COMMIT_DWELL_MS"]:
                cand.append((t0 + P["COMMIT_DWELL_MS"], "dwell"))
            cc = [max(x["t_start_ms"], t0) for x in contacts if sid in (x["a"], x["b"])
                  and x["t_start_ms"] <= t1 and x["t_end_ms"] >= t0]
            if cc:
                cand.append((min(cc), "contact"))
            aa = [x.t_ms for x in acts if sid in (x.actor, x.target) and t0 <= x.t_ms <= t1]
            if aa:
                cand.append((min(aa), "act"))
            if pl is not None and plant_site == sites[c] and t0 <= pl.t_ms <= t1:
                cand.append((pl.t_ms, "plant"))
            if cand:
                t_conf, how = min(cand)
                commits.append((t0, a, c, t1, how, t_conf))
    groups = []
    for c in sorted({x[2] for x in commits}):
        cur = None
        for t_in, a, _c, t_out, how, t_conf in sorted((x for x in commits if x[2] == c),
                                                      key=lambda x: x[0]):
            if cur is not None and t_in <= cur["last"] + P["ATTEMPT_HOLD_MS"]:
                cur["members"].setdefault(a, (t_in, how, t_conf))
                cur["last"] = max(cur["last"], t_out)
            else:
                if cur is not None:
                    groups.append(cur)
                cur = {"code": c, "open": t_in, "members": {a: (t_in, how, t_conf)}, "last": t_out}
        if cur is not None:
            groups.append(cur)
    for G in groups:                      # a member's later stays on the site keep it held
        grew = True
        while grew:
            grew = False
            for a in G["members"]:
                for t0, t1 in presence.get((a, G["code"]), []):
                    if t0 <= G["last"] + P["ATTEMPT_HOLD_MS"] and t1 > G["last"]:
                        G["last"], grew = t1, True
    if pl is not None and plant_site in sites.values():
        pc = labels.index(plant_site)
        covered = any(sites[G["code"]] == plant_site and G["open"] <= pl.t_ms
                      <= G["last"] + P["ATTEMPT_HOLD_MS"] for G in groups)
        if not covered:
            kp = int(np.clip(np.searchsorted(g, pl.t_ms), 0, g.size - 1))
            there = [a for a in atk.tolist() if alive[a, kp] and code[a, kp] == pc]
            groups.append({"code": pc, "open": pl.t_ms, "last": pl.t_ms, "plant_only": True,
                           "members": {a: (pl.t_ms, "plant", pl.t_ms) for a in there}})
    deaths = [e for e in tl.events if e.kind == "death" and g[0] <= e.t_ms <= t_end]
    out = []
    for G in sorted(groups, key=lambda G: G["open"]):
        site = labels[G["code"]]
        t_open = G["open"]
        close_by = min(G["last"] + P["ATTEMPT_HOLD_MS"], t_end)
        k_open = int(np.clip(np.searchsorted(g, t_open), 0, g.size - 1))
        k_close = int(np.clip(np.searchsorted(g, close_by), 0, g.size - 1))
        members = sorted(G["members"].items(), key=lambda kv: kv[1][0])
        joins = [t for _a, (t, _h, _c) in members]
        mids = [ids[a] for a, _v in members]
        if pl is not None and plant_site == site and t_open <= pl.t_ms <= close_by:
            end, res = pl.t_ms, "planted"
        elif not alive[atk, k_close].any():
            end = max((e.t_ms for e in deaths if e.target in atk_ids and t_open <= e.t_ms), default=close_by)
            res = "wiped"
        elif not alive[dfn, k_close].any():
            end = max((e.t_ms for e in deaths if e.target in def_ids and t_open <= e.t_ms), default=close_by)
            res = "cleared"
        elif close_by >= t_end and r["t_end"] is not None:
            end, res = t_end, "timed_out"
        else:
            end, res = G["last"], "abandoned"
        k_peak = int(np.clip(np.searchsorted(g, joins[-1] if joins else t_open), 0, g.size - 1))
        spread = None
        if len(members) > 1:
            smp = tl.sample(np.array([g[k_peak]]))
            xy = np.array([[smp["x"][a, 0], smp["y"][a, 0]] for a, _v in members])
            if np.isfinite(xy).all():
                spread = round(float(np.max(np.linalg.norm(xy[:, None] - xy[None], axis=-1))) / 100.0, 1)
        n_open = int(alive[atk, k_open].sum())
        dead = sorted({e.target for e in deaths if e.target in set(mids) and t_open <= e.t_ms <= end})
        away = [ids[a] for a in atk.tolist() if alive[a, k_peak] and ids[a] not in set(mids)]
        out.append(_ep("execute", r, t_open, end,
                       participants={"committed": mids, "elsewhere": away},
                       commitment={"committed": len(mids), "alive_at_open": n_open,
                                   "share": round(len(mids) / n_open, 3) if n_open else None,
                                   "join_ms": [round(t - t_open, 1) for t in joins],
                                   "entry_spread_ms": round(joins[-1] - joins[0], 1) if joins else None,
                                   "spread_m": spread},
                       outcome={"result": res, "site": site, "plant_site": plant_site,
                                "committed_dead": len(dead)},
                       trigger="plant" if G.get("plant_only") else members[0][1][1],
                       peak_ms=float(g[k_peak])))
    return out


def _lurks(r, tl, g, code, alive, atk, ex, ids, labels, engagements, P) -> list[dict]:
    """Attackers who, at an attempt's peak (its last join), stand alive
    outside both the attempted site's super-region and the attackers' side:
    each one's run outside the two, around the peak, lasting at least
    `LURK_MIN_MS`."""
    out = []
    site = ex["outcome"]["site"]
    if site is None or ex["trigger"] == "plant" or site not in labels:
        return out
    sc = labels.index(site)
    k0 = int(np.clip(np.searchsorted(g, ex["peak_ms"]), 0, g.size - 1))
    home = labels.index(ATTACKER_SIDE) if ATTACKER_SIDE in labels else -2
    dt = 1000.0 / P["REGION_HZ"]
    committed = set(ex["participants"]["committed"])
    for a in atk.tolist():
        sid = ids[a]
        away = alive[a] & (code[a] != sc) & (code[a] != home) & (code[a] >= 0)
        if not away[k0]:
            continue
        s = k0 - int(np.argmin(away[k0::-1])) + 1 if not away[:k0 + 1].all() else 0
        e = k0 + int(np.argmin(away[k0:])) - 1 if not away[k0:].all() else g.size - 1
        t0, t1 = float(g[s]), float(g[e])
        if t1 - t0 + dt < P["LURK_MIN_MS"]:
            continue
        held = sorted({labels[c] for c in code[a, s:e + 1].tolist() if c >= 0})
        ev = next((x for x in tl.events if x.kind == "death" and t0 <= x.t_ms <= t1 + dt
                   and sid in (x.actor, x.target)), None)
        with_team = None
        if ev is not None:
            for eng in engagements:
                if ev.event_id in eng.get("kill_events", []):
                    with_team = bool(committed & set(eng["participants"]["combatants"]))
        out.append(_ep("lurk", r, t0, t1, participants={"lurker": sid},
                       outcome={"first_event": None if ev is None else
                                ("kill" if ev.actor == sid else "death"),
                                "first_event_id": None if ev is None else ev.event_id,
                                "with_committed_teammate": with_team},
                       regions=held, execute_id=ex["episode_id"]))
    return out


def _rotations(r, tl, regions, idx, P) -> list[dict]:
    """Per player: a site's super-region, its `Link` volumes aside, held at
    least `ROTATION_MIN_DWELL_MS`, then another held as long, alive
    throughout. Anything crossed between, a site passed through included,
    is the path."""
    t_end = r["t_end"] if r["t_end"] is not None else r["t_next"]
    g, code, alive = _region_series(tl, regions, r["t_live"], t_end, P, mode="hold")
    if code is None:
        return []
    labels = regions.super_labels
    sites = _site_codes(regions)
    dt = 1000.0 / P["REGION_HZ"]
    dead = -9
    cues = [e for e in tl.events if e.kind in ("death", "plant") and r["t_start"] <= e.t_ms < t_end]
    out = []
    for s, slot in enumerate(tl.slots):
        rr = _label_runs(np.where(alive[s], code[s], dead))
        held = [(i, x) for i, x in enumerate(rr) if x[0] in sites
                and (x[2] - x[1] + 1) * dt >= P["ROTATION_MIN_DWELL_MS"]]
        for (i1, (c1, a1, b1)), (i2, (c2, a2, _b2)) in zip(held, held[1:]):
            between = [x[0] for x in rr[i1 + 1:i2]]
            if c1 == c2 or dead in between:
                continue
            t0, t1 = float(g[b1]), float(g[a2])
            cue = [{"event_id": e.event_id, "kind": e.kind, "lag_ms": round(t0 - e.t_ms, 1)}
                   for e in cues if 0 <= t0 - e.t_ms <= P["TRADE_WINDOW_MS"]]
            out.append(_ep("rotation", r, t0, t1, participants={"rotator": slot.slot_id},
                           outcome={"from_site": sites[c1], "to_site": sites[c2]},
                           path=[sites[c1]] + [labels[x] for x in between if x >= 0] + [sites[c2]],
                           duration_ms=round(t1 - t0, 1), cues=cue))
    return out


# ----------------------------------------------------------------- storage

def episodes_dir(source: str, root=DEFAULT_STORE) -> Path:
    """`<store>/analysis/episodes/<source>/`: truth episodes live with the
    other evaluation truth, one call away from no reader."""
    return Path(root) / "analysis" / "episodes" / source


def episodes_path(key: str, source: str = "truth", root=DEFAULT_STORE) -> Path:
    return episodes_dir(source, root) / f"{key}.jsonl"


def write_episodes(derived: Derived, key: str, root=DEFAULT_STORE) -> Path:
    """Write the match's rows, replacing an older version's file only after
    the new file is complete."""
    p = episodes_path(key, derived.header["source"], root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in derived.rows():
            f.write(json.dumps(row, default=_json_default) + "\n")
    tmp.replace(p)
    return p


def read_header(key: str, source: str = "truth", root=DEFAULT_STORE) -> dict | None:
    p = episodes_path(key, source, root)
    if not p.is_file():
        return None
    with p.open("r", encoding="utf-8") as f:
        first = f.readline()
    try:
        row = json.loads(first)
    except ValueError:
        return None
    return row if row.get("row") == "header" else None


def read_episodes(key: str, source: str = "truth", root=DEFAULT_STORE) -> list[dict]:
    p = episodes_path(key, source, root)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


# ----------------------------------------------------------------- the replay layer

def _impact(v) -> tuple | None:
    """'(x,y,z)' -> (x, y, z); the origin and an absent value read None."""
    if v is None:
        return None
    try:
        xyz = tuple(float(c) for c in str(v).strip("()").split(","))
    except ValueError:
        return None
    return None if len(xyz) != 3 or not any(xyz) else xyz


def from_replay_layer(key: str, root=DEFAULT_STORE) -> ArrayTimeline:
    """The `source = truth` timeline of a match from its stored replay layer
    (`replay_layer.load`, docs/REPLAY_LAYER.md): the ten players' ticks, life
    from the layer's `lives`, and its round, kill, damage, plant, defuse and
    revive events. Times are the replay's clock (`t_rep`); the header keeps
    the layer's capture offset. The plant's place is the planted spike's
    spawn (the `TimedBomb_C` child opened at the plant); the layer names no
    planter or defuser.

    T0 keeps the ten players only, short of level 1's definition in
    docs/EPISODES.md ("every player slot and its ability children"): the
    layer's `child:` entities (owner, side, life, position) are dropped.
    Carrying them is open work (BACKLOG item 1, class-aware harness step 2)."""
    from .replay_layer import load
    from .replay_source import MAX_GAP_MS

    L = load(key, root)
    E, Ev, R, Lv = L.entities, L.events, L.rounds, L.lives
    players = L.players()
    subj = {e: str(E["subject"][e]) for e in players}
    slots = [Slot(subj[e], str(E["team"][e]), E["agent"][e]) for e in players]
    tracks = {}
    for e in players:
        T = L.track(e)
        tracks[subj[e]] = {"t": T["t_rep"].astype(float), "x": T["x"], "y": T["y"], "z": T["z"],
                           "yaw": T["yaw"], "pitch": T["pitch"]}
    lives = {s.slot_id: [] for s in slots}
    for i in range(Lv["e"].size):
        e = int(Lv["e"][i])
        if e in subj:
            lives[subj[e]].append((float(Lv["t_open"][i]), float(Lv["t_close"][i])))

    def alive_fn(t):
        out = np.zeros((len(slots), t.size), bool)
        for k, s in enumerate(slots):
            for a, b in lives[s.slot_id]:
                out[k] |= (t >= a) & (t < b)
        return out

    def who(x):
        return None if x is None or not np.isfinite(x) or int(x) not in subj else subj[int(x)]

    events: list[Event] = []
    for i in range(R["round"].size):
        rn = int(R["round"][i])
        events.append(Event("round_start", float(R["t_start"][i]), f"round_start:{rn}"))
        if np.isfinite(R["t_buy_end"][i]):
            events.append(Event("buy_end", float(R["t_buy_end"][i]), f"buy_end:{rn}"))
        if np.isfinite(R["t_end"][i]):
            events.append(Event("round_end", float(R["t_end"][i]), f"round_end:{rn}"))
    if R["round"].size:
        last = float(R["t_next_start"][-1])
        if np.isfinite(last):
            events.append(Event("match_end", last, "match_end"))
    bombs = [(float(E["t_open_rep"][k]), (float(E["spawn_x"][k]), float(E["spawn_y"][k]),
                                          float(E["spawn_z"][k])))
             for k in np.flatnonzero(E["kind"] == "child")
             if str(E["class"][k]) == "TimedBomb_C" and np.isfinite(E["t_open_rep"][k])]
    for i in range(Ev["kind"].size):
        kind, t = str(Ev["kind"][i]), float(Ev["t_rep"][i])
        eid = f"{kind}:{i}"
        if kind == "kill":
            events.append(Event("death", t, eid, actor=who(Ev["e"][i]), target=who(Ev["e2"][i])))
        elif kind == "damage":
            a, v = who(Ev["e"][i]), who(Ev["e2"][i])
            if v is None:
                continue
            det = json.loads(Ev["detail"][i]) if Ev["detail"][i] else {}
            eq = Ev["value_str"][i]
            events.append(Event("damage", t, eid, actor=a, target=v,
                                amount=float(Ev["value_num"][i]),
                                wallbang=det.get("wall_penetration"),
                                cause=det.get("damage_type"),
                                equippable=None if eq is None or str(eq) == "None" else str(eq),
                                impact=_impact(det.get("impact")),
                                killed=det.get("killed")))
        elif kind == "plant":
            pos = min(bombs, key=lambda b: abs(b[0] - t)) if bombs else None
            events.append(Event("plant", t, eid,
                                position=pos[1] if pos and abs(pos[0] - t) <= 2000.0 else None))
        elif kind == "defuse":
            events.append(Event("defuse", t, eid))
        elif kind == "revive":
            events.append(Event("revive", t, eid, target=who(Ev["e"][i])))
    stamps = {"replay_layer": L.head.get("replay_layer_version"),
              "replay_layer_built": L.head.get("built_utc"),
              "replay_layer_inputs": L.head.get("inputs"),
              "a_ms": L.a_ms, "session": L.head.get("session"),
              "held_out": bool(L.head.get("held_out")),
              "round_numbering": "1-based: the layer's round + 1"}
    map_url = (L.head.get("provenance") or {}).get("map")
    # level 1's ability children, a table apart from the slots (`ChildTable`)
    return ArrayTimeline(L.match, map_url or "", slots, tracks, events, source="truth",
                         stamps=stamps, max_gap_ms=MAX_GAP_MS, alive_fn=alive_fn,
                         children=children_from_layer(L, MAX_GAP_MS))


# ----------------------------------------------------------------- staleness

def current_inputs(match: str, root=DEFAULT_STORE) -> dict:
    """The stamps a truth build of `match` would record now: this code, the
    sight, region, penetration and equippable owners, the replay layer's
    head, the map's sightline table, valorant-api's map list and the set of
    exported penetration meshes (a new export reads surfaces once unread)."""
    from .equippables import EQUIPPABLES_VERSION
    from .input_stamps import file_sha16
    from .line_of_sight import LINE_OF_SIGHT_VERSION, sightline_table
    from .map_regions import MAP_REGIONS_VERSION
    from .replay_layer import layer_dir
    from .wall_penetration import WALL_PENETRATION_VERSION, build_root

    head = layer_dir(match, root) / "layer.json"
    mesh_set = build_root(root) / "wallpen-meshes"
    manifests = sorted(p.name for p in mesh_set.glob("manifest_*.jsonl")) if mesh_set.is_dir() else []
    out = {"episodes": EPISODES_VERSION, "line_of_sight": LINE_OF_SIGHT_VERSION,
           "map_regions": MAP_REGIONS_VERSION, "wall_penetration": WALL_PENETRATION_VERSION,
           "equippables": EQUIPPABLES_VERSION, "replay_layer": file_sha16(head),
           "valorant_api_maps": file_sha16(Path(root) / "external" / "valorant-api" / "maps.json"),
           "wallpen_meshes": ",".join(manifests) or None,
           "sightline_table": None}
    if head.is_file():
        url = ((json.loads(head.read_text(encoding="utf-8")).get("provenance") or {}).get("map"))
        tp = sightline_table(url, root) if url else None
        out["sightline_table"] = f"{tp.name}:{tp.stat().st_size}" if tp else None
    return out


def status(match: str, root=DEFAULT_STORE, out_root=None) -> dict:
    """`{state, moved}` of a match's truth episodes (under `out_root`, else
    the store): `absent`, `stale` when a recorded input differs from
    `current_inputs`, else `current`."""
    head = read_header(match, "truth", out_root or root)
    if head is None:
        return {"state": "absent", "moved": [], "stored": None, "current": EPISODES_VERSION}
    rec = head.get("inputs") or {}
    now = current_inputs(match, root)
    moved = sorted(k for k in set(now) | set(rec) if now.get(k) != rec.get(k))
    return {"state": "stale" if moved else "current", "moved": moved,
            "stored": head.get("version"), "current": EPISODES_VERSION}


def session_status(sid: str, root=DEFAULT_STORE) -> dict | None:
    """The episodes status of the replay a capture session keeps, or None
    where it keeps none."""
    from .replay_source import replay_entry
    e = replay_entry(sid, root)
    if e is None:
        return None
    match = Path(e["file"]).stem
    return {"match": match, **status(match, root), "command": f"reticle episodes {sid}"}


def build(key: str, root=DEFAULT_STORE, out_root=None) -> dict:
    """Derive and write a match's truth episodes from the store's replay
    layer, under `out_root` (a scratch store for an experiment on a branch)
    else the store; the header records the inputs `status` compares."""
    tl = from_replay_layer(key, root)
    inputs = current_inputs(tl.match, root)
    d = derive_episodes(tl)
    d.header["inputs"] = inputs
    write_episodes(d, tl.match, out_root or root)
    return d.header


def command(keys: list[str], *, all_: bool = False, status_only: bool = False,
            root=DEFAULT_STORE, out_root=None) -> int:
    """`reticle episodes`: derive each named match's episodes (every match
    with a replay layer under `--all`), or with `--status` say which are
    current, stale or absent (every match when no key is named). `out_root`
    writes and reads the episodes under another root (`--out`), never the
    shared store's. A held-out match is built and never counted."""
    from .replay_layer import is_held_out, layer_dir, layer_root, resolve

    all_ = all_ or (status_only and not keys)

    matches = ([p.name for p in sorted(layer_root(root).iterdir())
                if (p / "layer.json").is_file()] if all_ and layer_root(root).is_dir() else [])
    for k in keys:
        m, _s = resolve(k, root)
        if m is None or not (layer_dir(m, root) / "layer.json").is_file():
            print(f"{k}: no replay layer -- run `reticle replay-layer {k}` first")
            continue
        matches.append(m)
    rc = 0
    for m in dict.fromkeys(matches):
        if status_only:
            st = status(m, root, out_root)
            print(f"{m}  {st['state']}" + (f"  moved: {', '.join(st['moved'])}" if st["moved"] else ""))
            continue
        h = build(m, root, out_root)
        if is_held_out(m):
            print(f"{m}: built (held out: no statistics)")
            continue
        kinds = Counter(r["kind"] for r in read_episodes(m, "truth", out_root or root)
                        if r["row"] == "episode")
        print(f"{m}: built {h['version']} on {h['map']}: "
              + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    return rc
