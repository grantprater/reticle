"""Round entity lifetimes for a whole session, from stored observations only.

`round_lifetimes.RoundLifetimes` decides which observations are one entity.
This runs it over every round of a session from what is already stored -- the
`ally_icon` events (ally fits, their descriptors and the player's own fit), the
HUD's round bounds, the roster's alive count, and stored death verdicts -- and
writes `round_entity` events. Nothing here decodes video or reads pixels.
Ally segments are split where the best teammate changes and stays changed, and
`adjudication.identity` names the pieces per round (`assign_ally_pieces`, then
the arbiter). Killfeed deaths bind to segment ends, and since 0.8.0 they also
bar a dead teammate from the pieces observed while it is dead
(`ally_dead_intervals`), so they are no longer an independent check of the names;
the player's labels and blind labels are. Named pieces carry persistent
teammate keys. Since 0.10.0 `death_binding_refusal` decides which entity may
take which death: only players die, the player's death ends only the self
entity, and the X and name checks are the enemy lane's
(`round_lifetimes.death_refusal`).

Observation mapping, and why
-----------------------------
* an ally fit with a described interior is an `ally` carrying its composition
  as `appearance`, which `RoundLifetimes` may use only to RANK reacquisition;
* an ally fit refused as `interior_is_map` is a `barrier`: the reader found
  map pixels inside the ring, and a barrier is static furniture, so it must
  not compete with teammates for continuity;
* any other refused ally fit is an `ally` with no appearance -- a thin
  interior is an unread descriptor, not a missing teammate;
* the frame's self fit is `self`.

A widget-absent frame is passed as `source_state="absent"`, which suspends
association rather than ending anything.

Owns [owns:round-entity-session].
"""
from __future__ import annotations

from collections import Counter

from .round_lifetimes import (ROUND_LIFETIME_VERSION, RoundLifetimes, death_rank, death_refusal,
                              seen_after_death)

# 0.8.0 (2026-09-26): `ally_dead_intervals` gives `identity.assign_ally_pieces`
# each round's killfeed dead intervals, and the owner bars a dead teammate
# from the pieces observed inside them.
# 0.7.0 (2026-09-26): ally segments split where the best teammate changes and
# stays changed; `identity.assign_ally_pieces` names the pieces per round.
# Killfeed deaths bind to segment ends and no longer name anything; the
# in-session exemplar pass is gone.
# 0.6.0 (2026-09-26): an ally segment whose icons fit no teammate's rendered
# art (`identity.teammate_fit_refusal`) is refused as not a teammate.
# 0.9.0 (2026-09-28): a frame the stored menu witness finds covered steps the
# lifetimes with no observation, as `source_state="menu_open"`.
# 0.10.0 (2026-09-30): deaths bind through `death_binding_refusal` inside
# `RoundLifetimes.finish`, not after it: no barrier takes a death or a roster
# drop, the player's death (and a drop beside it) ends only the self entity,
# a teammate's only an ally piece, revives and second lives end no one, and
# the X and the arbiter's name must agree, as on the enemy lane.
# 0.11.0 (2026-10-01): a death binds to the admitted piece the arbiter named
# as its victim first, then the nearest last sighting, then the nearest
# position to its X (`round_lifetimes.death_rank`), in `finish` and in the
# pairing of the deaths it left; the most observed piece no longer binds first.
# 0.12.0 (2026-10-01): an ally piece seen more than the dead-icon lag after a
# death is not its victim (`round_lifetimes.seen_after_death`), in `finish`,
# in the check of its bound pairs and in the pairing of the deaths it left.
# 0.13.0 (2026-10-01): the pairing of the deaths `finish` left also offers
# each piece before a segment's last, with that piece's own last sighting and
# name; a piece that takes a death ends there, and the pieces after it carry
# `after_piece_death`.
ROUND_ENTITY_VERSION = "round-entity-0.13.0"

#: Viterbi switch penalty, in units of the claims' margin gate: a segment is
#: cut only where the best teammate changes and stays changed.
SWITCH = 5.0
#: Roster reads either side of a frame; the largest stands, because the count
#: drops at a death while the dying teammate's icon may still show.
ROSTER_LAG_MS = 500.0
#: A teammate counts as dead from its killfeed death plus this lag: its icon
#: may still draw for a moment after the entry. Starting the interval before
#: the death instead unnamed victims' own last pieces and lost most right
#: labels (`ally-alive-constraint` in the store's predictions).
DEAD_AFTER_MS = 700.0
#: A dead interval ends this long before the revive entry or roster rise that
#: ends it, so the returning teammate's first icons stay admissible.
REVIVE_SLACK_MS = 700.0
#: A roster rise this close to a revive entry is that revive, and lifts no
#: other teammate's interval.
REVIVE_ROSTER_MS = 3000.0


#: Two observations of one entity further apart than this leave a gap: the
#: entity is not observed between them (an entity row's `gaps`).
GAP_MS = 150.0


def track_gaps(times) -> list[tuple[float, float]]:
    """`(last observed, next observed)` for each gap in one entity's sorted
    observation times: the spans nothing observed it."""
    return [(a, b) for a, b in zip(times, times[1:]) if b - a > GAP_MS]


#: The families that are players, and so the only ones a death or a roster
#: drop may end. A barrier is furniture: it has no death.
PLAYER_FAMILIES = ("ally", "self")
#: A roster drop this close to the player's own death counts the player: the
#: window `RoundLifetimes.finish` binds a drop within.
PLAYER_DROP_MS = 2500.0


def death_binding_refusal(ent: dict, death: dict, *, player_agent: str | None,
                          agent: str | None, last_xy=None, scale: float = 1.0,
                          deaths=()) -> str | None:
    """Why the ally-side `death` may not end `ent`, or None when it may.

    An ally piece seen more than the dead-icon lag after the death is not its
    victim (`round_lifetimes.seen_after_death`, which reads the round's
    revive entries from `deaths`). The self entity is exempt: after the
    player dies it shows the spectated teammate, so a later self sighting
    says nothing about the player's icon.

    Only a player entity takes a death. The player's own death -- the
    killfeed's player-death mask, or the player's agent as victim -- ends
    only the self entity, and a teammate's death ends only an ally piece:
    the self icon follows the spectated teammate after the player dies
    [domain:minimap/self-icon-shows-spectated]. The rest is
    `round_lifetimes.death_refusal`, the rule the enemy lane binds by: the
    death owner's revive and second-life flags, the death's X against the
    entity's last position, and the victim against `agent`, the arbiter's
    name for the entity (the player's agent for the self entity)."""
    fam = ent.get("family")
    if fam not in PLAYER_FAMILIES:
        return f"{fam}_is_not_a_player"
    mine = _is_player_death(death, player_agent)
    if fam == "self" and not mine:
        return "victim_is_not_the_player"
    if fam == "ally" and mine:
        return "victim_is_the_player"
    if fam == "ally" and ent.get("last_seen_ms") is not None:
        late = seen_after_death(death, last_seen_ms=ent["last_seen_ms"], deaths=deaths)
        if late:
            return late
    return death_refusal(death, agent=binding_agent(ent, player_agent, agent),
                         last_xy=last_xy, scale=scale)


def binding_agent(ent: dict, player_agent: str | None, agent: str | None) -> str | None:
    """The name a death is checked and ranked against: the player's agent
    for the self entity, the arbiter's name `agent` for any other."""
    return player_agent if ent.get("family") == "self" else agent


def drop_binding_refusal(ent: dict, t_drop: float, player_deaths) -> str | None:
    """Why a roster alive drop at `t_drop` may not end `ent`, or None.

    A drop counts a player, so only a player entity takes one. A drop within
    `PLAYER_DROP_MS` of the player's own death (`player_deaths`, their times)
    counts the player and ends only the self entity; any other drop counts a
    teammate and ends only an ally piece."""
    fam = ent.get("family")
    if fam not in PLAYER_FAMILIES:
        return f"{fam}_is_not_a_player"
    mine = any(abs(t_drop - t) <= PLAYER_DROP_MS for t in player_deaths)
    if fam == "ally" and mine:
        return "drop_is_the_player"
    if fam == "self" and not mine:
        return "drop_is_a_teammate"
    return None


def _is_player_death(death: dict, player_agent: str | None) -> bool:
    """The death owner's player-death flag, or the player's agent as victim."""
    return bool(death.get("kf_player_death")) or bool(
        player_agent and death.get("victim") == player_agent)


def _observation(icon: dict) -> dict:
    r = float(icon["r"])
    # New reader revisions carry adjudication's family. Historical events
    # lack it, so retain their recorded refusal for stored-data replay.
    family = icon.get("family") or (
        "barrier" if icon.get("reason") == "interior_is_map" else "ally")
    obs = {"x": icon["cx"], "y": icon["cy"], "r": r,
           "box": [icon["cx"] - r, icon["cy"] - r, 2 * r, 2 * r],
           "family": family, "view": "minimap", "label": family,
           "observation_key": icon["observation_key"]}
    if family == "ally" and not icon.get("reason") and icon.get("composition"):
        obs["appearance"] = icon["composition"]
    return obs


def _self_observation(frame: dict) -> dict | None:
    if not frame.get("self"):
        return None
    x, y, r = frame["self"]
    return {"x": x, "y": y, "r": r, "box": [x - r, y - r, 2 * r, 2 * r],
            "family": "self", "view": "minimap", "label": "self",
            "observation_key": f"{frame['session_id']}:{frame['frame_idx']}:self"}


def _roster_at(times: list[float], alive: list, t_ms: float):
    """The latest roster read at or before `t_ms`, as `RoundLifetimes` wants it."""
    import bisect

    i = bisect.bisect_right(times, t_ms) - 1
    if i < 0 or alive[i] is None:
        return None
    return {"alive_ally": int(alive[i])}


def session_lifetimes(session_id: str, events: list[dict], rounds: list[dict],
                      scale: float, roster: dict | None = None,
                      source_revision: str | None = None,
                      deaths: list[dict] | None = None,
                      lineup: dict | None = None,
                      gallery: dict | None = None,
                      references: dict | None = None, menu=None) -> list[dict]:
    """`round_entity` event rows for every round the stored frames reach.

    `events` are the session's `ally_icon` rows; `rounds` come from
    `rounds.build_rounds`; `roster` is `{"t_ms": [...], "alive_ally": [...]}`;
    `deaths` are `events/death` rows. Frames outside every round are not
    associated -- an entity does not outlive its round. `menu(t_ms)` is the
    stored menu witness (`menu.MenuWitness.at`): the menu dims the widget,
    which still passes the widget test [domain:hud/menu-dims-tray], so a
    frame it finds covered observes nothing and says `menu_open`.
    """
    frames = sorted((e for e in events if e["kind"] == "frame"), key=lambda e: e["t_ms"])
    icons: dict[int, list[dict]] = {}
    for e in events:
        if e["kind"] == "icon":
            icons.setdefault(e["frame_idx"], []).append(e)
    rt, ra = (roster or {}).get("t_ms", []), (roster or {}).get("alive_ally", [])
    common = {"session_id": session_id, "round_entity_version": ROUND_ENTITY_VERSION,
              "round_lifetime_version": ROUND_LIFETIME_VERSION,
              "ally_icon_revision": source_revision,
              "candidate_revision": events[0].get("candidate_revision")}
    obs_entity_map: dict[str, str] = {}
    obs_by_ent: dict[str, list[str]] = {}
    round_records: list[dict] = []
    coverage = Counter()
    for rnd in rounds:
        a, z = rnd["t_start_ms"], rnd["t_end_ms"]
        inside = [f for f in frames if a <= f["t_ms"] < z]
        if not inside:
            coverage["rounds_without_frames"] += 1
            continue
        life = RoundLifetimes(f"{session_id}:R{rnd['round_no']}", a, scale)
        obs_rows = []
        for f in inside:
            if not f["widget_drawn"]:
                life.step(f["t_ms"], [], source_state="absent")
                coverage["absent_frames"] += 1
                continue
            if menu is not None and menu(f["t_ms"]) is True:
                life.step(f["t_ms"], [], source_state="menu_open")
                coverage["menu_open_frames"] += 1
                continue
            obs = [_observation(i) for i in icons.get(f["frame_idx"], [])]
            me = _self_observation(f)
            if me:
                obs.append(me)
            out = life.step(f["t_ms"], obs,
                            roster=_roster_at(rt, ra, f["t_ms"]) if rt else None)
            coverage["frames"] += 1
            for o in out:
                if o.get("observation_key") and o.get("entity_id"):
                    obs_entity_map[o["observation_key"]] = o["entity_id"]
                    obs_by_ent.setdefault(o["entity_id"], []).append(o["observation_key"])
                obs_rows.append({**common, "kind": "observation", "round_no": rnd["round_no"],
                                 "t_ms": f["t_ms"], "frame_idx": f["frame_idx"],
                                 "observation_key": o["observation_key"],
                                 "observation_id": o["observation_id"],
                                 "family": o["family"], "entity_id": o["entity_id"],
                                 "name": o["name"], "state": o["state"],
                                 "identity_status": o["identity_status"],
                                 "alternatives": o["alternatives"],
                                 "component": o["association_component_id"],
                                 "acquisition": o["acquisition"],
                                 "x": round(o["x"], 2), "y": round(o["y"], 2)})
        rnd_deaths = [d for d in (deaths or [])
                      if d.get("kind") == "death_verdict" and d.get("round_no") == rnd["round_no"]
                      and d.get("side") == "ally"]
        rnd_drops = [rt[i] for i in range(1, len(rt))
                     if ra[i] is not None and ra[i-1] is not None and ra[i] < ra[i-1]
                     and a <= rt[i] <= z]
        round_records.append({
            "round_no": rnd["round_no"],
            "life": life,
            "deaths": rnd_deaths,
            "drops": rnd_drops,
            "z": z,
            "obs_rows": obs_rows,
        })
        coverage["rounds"] += 1

    player_agent = (lineup.get("player") or {}).get("agent") if lineup else None
    named = _name_pieces(session_id, events, round_records, rt, ra, lineup, gallery,
                         references) if lineup and gallery else None
    named = named or {}
    pieces, verdicts = named.get("pieces", {}), named.get("verdicts", {})
    last_piece = named.get("last_piece", {})

    def agent_of(seg_id):
        v = verdicts.get(last_piece.get(seg_id, seg_id))
        return v.get("agent") if v else None

    # Death witnesses BIND a death to a segment's end; they never name it.
    # The killfeed stays the independent check of the portrait names.
    death_by_id = {d["death_id"]: d for rec in round_records for d in rec["deaths"]
                   if d.get("death_id")}
    unbound = Counter()
    piece_deaths: dict[str, dict] = {}

    for rec in round_records:
        last_xy = {eid: (e["last_observation"]["x"], e["last_observation"]["y"])
                   for eid, e in rec["life"].entities.items() if e.get("last_observation")}

        def refusal(ent, d, last_xy=last_xy, deaths=rec["deaths"]):
            return death_binding_refusal(ent, d, player_agent=player_agent,
                                         agent=agent_of(ent["id"]),
                                         last_xy=last_xy.get(ent["id"]), scale=scale,
                                         deaths=deaths)

        def rank(ent, d, last_xy=last_xy):
            return death_rank(d, agent=binding_agent(ent, player_agent, agent_of(ent["id"])),
                              last_seen_ms=ent["last_seen_ms"], last_xy=last_xy.get(ent["id"]))

        mine = [d["t_ms"] for d in rec["deaths"] if d.get("t_ms") is not None
                and _is_player_death(d, player_agent)
                and death_refusal(d) not in ("revive", "second_life")]
        finished = rec["life"].finish(
            rec["z"], deaths=rec["deaths"], roster_drops=rec["drops"],
            admit=lambda ent, d: refusal(ent, d) is None, rank=rank,
            admit_drop=lambda ent, t, mine=mine: drop_binding_refusal(ent, t, mine) is None)
        rec["finished"] = finished
        # The same rule on the bound pairs; any disagreement is counted.
        for ent in finished:
            d = death_by_id.get(ent.get("death_id"))
            why = None if d is None else refusal(ent, d)
            if why:
                unbound[why] += 1
                ent.update(death_id=None, end_ms=None, death_evidence=None,
                           end_reason="last observation does not establish destruction/death",
                           right_censored_at_ms=ent["last_seen_ms"], death_unbound=why)
        # Pair any remaining unlinked deaths with a nearby segment end, or with
        # the end of a piece before a segment's last: a segment's last sighting
        # can be a stray fit the tracker joined after the victim's icon went
        # (5822b6646448 R8: Omen's piece seen 0.3 s before the death, then one
        # fit 40 px off 1.07 s after it), so `seen_after_death` is asked of
        # each piece's own last sighting. A piece that takes a death ends
        # there; the pieces after it keep the segment's continuity, which the
        # death disputes, and say so (`after_piece_death`).
        claimed = {ent["death_id"] for ent in finished if ent.get("death_id")}
        inner = []
        for ent in finished:
            ids = named.get("pieces_of", {}).get(ent["id"], [])
            if ent.get("family") == "ally" and not ent.get("death_id") and len(ids) > 1:
                inner += [{"id": pid, "family": "ally", "segment": ent,
                           "last_seen_ms": pieces[pid]["t"][-1]} for pid in ids[:-1]]
        piece_xy = {}
        for o in rec["obs_rows"]:
            pid = named.get("piece_of", {}).get(o["observation_key"])
            if pid:
                piece_xy[pid] = (o["x"], o["y"])
        both_xy = {**last_xy, **piece_xy}
        for d in sorted(rec["deaths"], key=lambda x: x.get("t_ms", 0)):
            did, t_d = d.get("death_id"), d.get("t_ms", 0)
            if did in claimed:
                continue
            cands = [(rank(ent, d, last_xy=both_xy), ent)
                     for ent in finished + inner
                     if ent.get("family") == "ally"
                     and not (ent.get("segment") or ent).get("death_id")
                     and not (ent.get("segment") or ent).get("piece_death_id")
                     and abs(ent["last_seen_ms"] - t_d) <= 3000.0
                     and refusal(ent, d, last_xy=both_xy) is None]
            if cands:
                best_ent = min(cands, key=lambda x: x[0])[1]
                if "segment" in best_ent:
                    seg = best_ent["segment"]
                    seg["piece_death_id"] = did
                    piece_deaths[best_ent["id"]] = d
                else:
                    best_ent.update(death_id=did, end_ms=t_d, end_reason="death",
                                    death_evidence="killfeed_verdict")
                claimed.add(did)
    coverage["death_unbound"] = dict(unbound)

    rows: list[dict] = []
    piece_of = named.get("piece_of", {})
    for rec in round_records:
        for o in rec["obs_rows"]:
            pid = piece_of.get(o["observation_key"])
            rows.append({**o, "segment_id": o["entity_id"], "entity_id": pid}
                        if pid and pid != o["entity_id"] else o)
        for ent in rec.get("finished", []):
            fam = ent.get("family")
            body = {k: v for k, v in ent.items()
                    if k not in ("appearance", "anchor_observation", "kind", "piece_death_id")}
            body["agent"], body["teammate_key"] = None, None
            if fam == "self":
                body["agent"] = player_agent
                body["identity_status"] = "resolved" if player_agent else "provisional"
                body["teammate_key"] = (f"{session_id}:teammate:{player_agent}"
                                        if player_agent else None)
            elif fam == "barrier":
                body["identity_status"], body["identity_reason"] = "abstained", "barrier"
            head = {**common, "kind": "entity", "entity_kind": ent.get("kind"),
                    "round_no": rec["round_no"]}
            if fam == "ally" and ent["id"] in named.get("pieces_of", {}):
                for piece in _piece_bodies(body, pieces, verdicts,
                                           named["pieces_of"][ent["id"]], session_id,
                                           piece_deaths):
                    rows.append({**head, **piece})
                continue
            if fam == "ally" and lineup:
                body["identity_status"], body["identity_reason"] = "abstained", "no_claims"
            rows.append({**head, **body})
        report = rec["life"].association_report()
        rows.append({**common, "kind": "associations", "round_no": rec["round_no"],
                     **report})

    return [{**common, "kind": "coverage", **coverage}] + rows


def _piece_bodies(body, pieces, verdicts, ids, session_id, piece_deaths=None):
    """Entity bodies for one segment's pieces: each carries its own span and
    name; only the last inherits the segment's ending, unless a death in
    `piece_deaths` ended an earlier piece, whose later pieces then carry
    `after_piece_death`."""
    piece_deaths = piece_deaths or {}
    died = None
    out = []
    for j, pid in enumerate(ids):
        p, v = pieces[pid], verdicts[pid]
        ts = p["t"]
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        row = {**body, "id": pid, "segment_id": body["id"], "piece_index": j,
               "pieces_of_segment": len(ids), "first_seen_ms": ts[0], "last_seen_ms": ts[-1],
               "observations": len(ts), "gaps": len(track_gaps(ts)),
               "max_gap_ms": max(gaps, default=0),
               "agent": v["agent"], "identity_status": v["status"],
               "teammate_key": f"{session_id}:teammate:{v['agent']}" if v["agent"] else None,
               "identity_evidence": {k: v[k] for k in ("evidence_sum", "reference_source",
                                                       "gap", "fit", "exact")},
               "identity_votes": v["votes"]}
        if v.get("barred"):
            row["identity_barred"] = v["barred"]
        if v["reason"]:
            row["identity_reason"] = v["reason"]
        d = piece_deaths.get(pid)
        if d is not None:
            row.update(end_ms=d.get("t_ms"), right_censored_at_ms=None,
                       death_id=d.get("death_id"), death_evidence="killfeed_verdict",
                       end_reason="death")
        elif j < len(ids) - 1:
            row.update(end_ms=None, right_censored_at_ms=ts[-1], death_id=None,
                       death_evidence=None, end_reason="split: best teammate changed")
        if died is not None and d is None:
            row["after_piece_death"] = died
        if d is not None:
            died = d.get("death_id")
        out.append(row)
    return out


def _viterbi(E, penalty: float) -> list[int]:
    """Best state path over rows of per-icon evidence, `penalty` per switch."""
    import numpy as np

    n, k = E.shape
    V, back = E[0].copy(), np.zeros((n, k), int)
    for t in range(1, n):
        stay, j = V, int(np.argmax(V))
        move = V[j] - penalty
        back[t] = np.where(stay >= move, np.arange(k), j)
        V = np.maximum(stay, move) + E[t]
    path = [int(np.argmax(V))]
    for t in range(n - 1, 0, -1):
        path.append(int(back[t][path[-1]]))
    return path[::-1]


def ally_dead_intervals(deaths: list[dict] | None, round_ends: dict, rt: list, ra: list) -> dict:
    """`{round: {agent: [(start_ms, end_ms, why)]}}` from the stored ally
    `death_verdict`s, for `identity.assign_ally_pieces(dead=...)`.

    `adjudication.death` decides who died and flags a revive entry
    (`is_revive`) and a death that removes no one (`is_second_life`)
    [domain:rounds/resurrection-mechanics]; this only turns its verdicts into
    intervals. A named victim is dead from its death + `DEAD_AFTER_MS` until
    a later revive entry in the round names it, or the roster's alive_ally
    count rises with no revive entry within `REVIVE_ROSTER_MS` (a revive the
    killfeed did not name), less `REVIVE_SLACK_MS`; otherwise until the
    round's end (`round_ends`). A Clove expiry entry is a death
    [domain:rounds/clove-revive-expiry-entry] and opens a new interval.
    """
    rows = [d for d in deaths or () if d.get("kind") == "death_verdict"
            and d.get("side") == "ally" and d.get("victim") and d.get("round_no") in round_ends]
    revives = [(float(d["t_ms"]), d["victim"], d["round_no"]) for d in rows if d.get("is_revive")]
    rises = [rt[i] for i in range(1, len(rt))
             if ra[i] is not None and ra[i - 1] is not None and ra[i] > ra[i - 1]
             and not any(abs(rt[i] - t) <= REVIVE_ROSTER_MS for t, _, _ in revives)]
    out: dict = {}
    for d in rows:
        if d.get("is_revive") or d.get("is_second_life"):
            continue
        t, a, r = float(d["t_ms"]), d["victim"], d["round_no"]
        start, end = t + DEAD_AFTER_MS, round_ends[r]
        ends = [(tr, "revive entry") for tr, ar, rr in revives if ar == a and rr == r and tr > t]
        ends += [(tr, "roster rise") for tr in rises if start < tr < end]
        why = f"dead from killfeed death at {t:.0f} ms"
        if ends:
            te, how = min(ends)
            end = te - REVIVE_SLACK_MS
            why += f" until {how} at {te:.0f} ms"
        if end > start:
            out.setdefault(r, {}).setdefault(a, []).append((start, end, why))
    return out


def _roster_window(times: list[float], alive: list, t_ms: float) -> list:
    """The roster reads within `ROSTER_LAG_MS` of `t_ms`, with the read in
    force at the window's start."""
    import bisect

    lo = max(0, bisect.bisect_right(times, t_ms - ROSTER_LAG_MS) - 1)
    hi = bisect.bisect_right(times, t_ms + ROSTER_LAG_MS)
    return alive[lo:hi]


def _name_pieces(session_id, events, round_records, rt, ra, lineup, gallery, references):
    """Split ally segments where the best teammate changes and stays changed,
    then ask `identity.assign_ally_pieces` to name the pieces per round."""
    import numpy as np

    from .adjudication.identity import (AGENT_IDENTITY_VERSION, AgentIdentityArbiter,
                                        assign_ally_pieces, claims_from_ally_icons,
                                        identity_claim)
    from .round_lifetimes import ally_capacity

    icons = [e for e in events if e.get("kind") == "icon"]
    if not icons:
        return None
    prefix = f"{session_id}:ally_icon:"
    claims = {c["entity_id"][len(prefix):]: c
              for c in claims_from_ally_icons(icons, lineup, gallery=gallery,
                                              session_id=session_id, references=references)
              if c["entity_id"].startswith(prefix)}
    scored = [c["evidence"] for c in claims.values() if (c.get("evidence") or {}).get("scores")]
    name_sets = Counter(tuple(sorted(e["scores"])) for e in scored)
    names = list(name_sets.most_common(1)[0][0]) if name_sets else []
    penalty = SWITCH * max([e["margin_min"] for e in scored] or [0.0])
    pieces, pieces_of, piece_of, last_piece = {}, {}, {}, {}
    frames: dict[tuple, set] = {}
    self_seen = set()
    for rec in round_records:
        rno, segs = rec["round_no"], {}
        for o in rec["obs_rows"]:
            if o["family"] == "self":
                self_seen.add((rno, o["t_ms"]))
            elif o["family"] == "ally" and o["entity_id"]:
                segs.setdefault(o["entity_id"], []).append((o["t_ms"], o["observation_key"]))
        for seg, ob in segs.items():
            ob.sort()
            path = [0] * len(ob)
            if len(names) > 1:
                E = np.array([[(((claims.get(k) or {}).get("evidence") or {}).get("scores")
                                or {}).get(a, 0.0) for a in names] for _, k in ob])
                path = _viterbi(E, penalty)
            cuts = [0] + [i for i in range(1, len(path)) if path[i] != path[i - 1]] + [len(ob)]
            ids = [seg] if len(cuts) == 2 else [f"{seg}/P{j}" for j in range(len(cuts) - 1)]
            pieces_of[seg], last_piece[seg] = ids, ids[-1]
            for j, pid in enumerate(ids):
                part = ob[cuts[j]:cuts[j + 1]]
                pieces[pid] = {"round": rno, "t": [t for t, _ in part],
                               "claims": [claims[k] for _, k in part if k in claims]}
                for t, k in part:
                    piece_of[k] = pid
                    frames.setdefault((rno, t), set()).add(pid)
    capacity = {f: ally_capacity(_roster_window(rt, ra, f[1]) if rt else None, f in self_seen)
                for f in frames}
    dead = ally_dead_intervals([d for rec in round_records for d in rec["deaths"]],
                          {rec["round_no"]: rec["z"] for rec in round_records}, rt, ra)
    assigned = assign_ally_pieces(pieces, frames, capacity,
                                  teammate_fit=(references or {}).get("teammate_fit"), dead=dead)
    # The assignment is the piece's witness; the arbiter decides its name.
    arb = AgentIdentityArbiter()
    arb.extend(identity_claim(
        pid, v["agent"], channel="ally_track", reason=v["reason"],
        source_version=AGENT_IDENTITY_VERSION, observed_at_ms=pieces[pid]["t"][-1],
        binding_from="round_entity", evidence={k: v[k] for k in (
            "evidence_sum", "reference_source", "gap", "fit", "exact", "votes")})
        for pid, v in assigned.items())
    verdicts = {}
    for row in arb.verdict():
        ch = row["by_channel"].get("ally_track", {})
        verdicts[row["entity_id"]] = {
            **assigned[row["entity_id"]], "agent": row["agent"], "status": row["status"],
            "reason": row["reason"] if row["agent"] or row["status"] != "abstained"
            else ch.get("reason")}
    return {"pieces": pieces, "pieces_of": pieces_of, "piece_of": piece_of,
            "last_piece": last_piece, "verdicts": verdicts}
