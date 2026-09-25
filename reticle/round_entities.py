"""Round entity lifetimes for a whole session, from stored observations only.

`round_lifetimes.RoundLifetimes` decides which observations are one entity.
This runs it over every round of a session from what is already stored -- the
`ally_icon` events (ally fits, their descriptors and the player's own fit), the
HUD's round bounds and the roster's alive count -- and writes `round_entity`
events. Nothing here decodes video or reads pixels; agent names are bound to
track segments through `adjudication.identity`.

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

from .round_lifetimes import ROUND_LIFETIME_VERSION, RoundLifetimes

ROUND_ENTITY_VERSION = "round-entity-0.4.0"


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
                      gallery: dict | None = None) -> list[dict]:
    """`round_entity` event rows for every round the stored frames reach.

    `events` are the session's `ally_icon` rows; `rounds` come from
    `rounds.build_rounds`; `roster` is `{"t_ms": [...], "alive_ally": [...]}`;
    `deaths` are `events/death` rows. Frames outside every round are not
    associated -- an entity does not outlive its round.
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

    verdicts: dict[str, dict] = {}
    player_agent = (lineup.get("player") or {}).get("agent") if lineup else None
    if lineup and gallery:
        from .adjudication.identity import (
            AgentIdentityArbiter,
            claims_from_ally_icons,
        )
        icon_events = [e for e in events if e.get("kind") == "icon"]
        if icon_events:
            claims = claims_from_ally_icons(
                icon_events, lineup, gallery=gallery, session_id=session_id)
            prefix = f"{session_id}:ally_icon:"
            track_claims = []
            for c in claims:
                eid = c.get("entity_id", "")
                obs_key = eid[len(prefix):] if eid.startswith(prefix) else eid
                target_ent = obs_entity_map.get(obs_key)
                if target_ent:
                    track_claims.append({
                        **c,
                        "entity_id": target_ent,
                        "binding_from": "round_entity",
                    })
            if track_claims:
                arbiter = AgentIdentityArbiter()
                arbiter.extend(track_claims)
                verdicts = {v["entity_id"]: v for v in arbiter.verdict()}

    rows: list[dict] = []
    for rec in round_records:
        rows.extend(rec["obs_rows"])
        finished = rec["life"].finish(rec["z"], deaths=rec["deaths"], roster_drops=rec["drops"])
        for ent in finished:
            eid = ent["id"]
            fam = ent.get("family")
            agent = None
            status = ent.get("identity_status", "provisional")
            reason = None
            votes = None

            if fam == "self":
                agent = player_agent
                status = "resolved" if player_agent else "provisional"
            elif fam == "barrier":
                status = "abstained"
                reason = "barrier"
            elif fam == "ally":
                if eid in verdicts:
                    v = verdicts[eid]
                    agent = v["agent"]
                    status = v["status"]
                    reason = v["reason"]
                    ch = v.get("by_channel", {}).get("minimap_portrait", {})
                    votes = ch.get("votes")
                elif lineup:
                    status = "abstained"
                    reason = "no_claims"

            body = {k: v for k, v in ent.items()
                    if k not in ("appearance", "anchor_observation", "kind")}
            body["agent"] = agent
            body["identity_status"] = status
            if reason is not None:
                body["identity_reason"] = reason
            if votes is not None:
                body["identity_votes"] = votes

            rows.append({**common, **body, "kind": "entity",
                         "entity_kind": ent.get("kind"), "round_no": rec["round_no"]})
        report = rec["life"].association_report()
        rows.append({**common, "kind": "associations", "round_no": rec["round_no"],
                     **report})

    return [{**common, "kind": "coverage", **coverage}] + rows
