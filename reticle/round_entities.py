"""Round entity lifetimes for a whole session, from stored observations only.

`round_lifetimes.RoundLifetimes` decides which observations are one entity.
This runs it over every round of a session from what is already stored -- the
`ally_icon` events (ally fits, their descriptors and the player's own fit), the
HUD's round bounds, the roster's alive count, and stored death verdicts -- and
writes `round_entity` events. Nothing here decodes video or reads pixels; agent
names are bound to track segments through `adjudication.identity`, augmented with
in-session minimap exemplars and identity-gated death witnesses, assigning
persistent teammate keys across the match.

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

ROUND_ENTITY_VERSION = "round-entity-0.5.0"


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
                      references: dict | None = None) -> list[dict]:
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
    arb = None
    verdicts: dict[str, dict] = {}

    if lineup and gallery:
        import numpy as np
        from .adjudication.identity import (
            AgentIdentityArbiter,
            claims_from_ally_icons,
            identity_claim,
        )

        icon_events = [e for e in events if e.get("kind") == "icon"]
        prefix = f"{session_id}:ally_icon:"

        # Pass 1: Base claims with official art gallery
        if icon_events:
            claims1 = claims_from_ally_icons(
                icon_events, lineup, gallery=gallery, session_id=session_id,
                references=references)
            track_claims1 = []
            for c in claims1:
                eid = c.get("entity_id", "")
                obs_key = eid[len(prefix):] if eid.startswith(prefix) else eid
                tgt = obs_entity_map.get(obs_key)
                if tgt:
                    track_claims1.append({
                        **c,
                        "entity_id": tgt,
                        "binding_from": "round_entity",
                    })
            if track_claims1:
                arb1 = AgentIdentityArbiter()
                arb1.extend(track_claims1)
                verdicts1 = {v["entity_id"]: v for v in arb1.verdict()}

                # Pass 2: In-session minimap exemplars from confident tracks
                icons_by_key = {e["observation_key"]: e["composition"]
                                for e in icon_events if e.get("composition")}
                augmented_gallery = {agent: list(vecs) for agent, vecs in gallery.items()}
                harvested = 0
                for eid, v in verdicts1.items():
                    agent = v.get("agent")
                    if agent and len(v.get("claims", [])) >= 80:
                        ent_obs_keys = obs_by_ent.get(eid, [])
                        comps = [icons_by_key[k] for k in ent_obs_keys if k in icons_by_key]
                        if comps:
                            step = max(1, len(comps) // 3)
                            for comp in comps[::step][:3]:
                                augmented_gallery[agent].append(np.array(comp, dtype=np.float32))
                                harvested += 1

                if harvested > 0:
                    claims2 = claims_from_ally_icons(
                        icon_events, lineup, gallery=augmented_gallery, session_id=session_id,
                        references=references)
                    track_claims2 = []
                    for c in claims2:
                        eid = c.get("entity_id", "")
                        obs_key = eid[len(prefix):] if eid.startswith(prefix) else eid
                        tgt = obs_entity_map.get(obs_key)
                        if tgt:
                            track_claims2.append({
                                **c,
                                "entity_id": tgt,
                                "binding_from": "round_entity",
                            })
                    arb = AgentIdentityArbiter()
                    arb.extend(track_claims2)
                else:
                    arb = arb1
                verdicts = {v["entity_id"]: v for v in arb.verdict()}

    # Pass 3: Finish entities with identity-gated death witness pairing
    teammate_deaths = [d for d in (deaths or [])
                       if d.get("kind") == "death_verdict" and d.get("side") == "ally"
                       and (not player_agent or d.get("victim") != player_agent)]
    death_by_id = {d["death_id"]: d for d in teammate_deaths if d.get("death_id")}
    death_by_rnd: dict[int, list[dict]] = {}
    for d in teammate_deaths:
        death_by_rnd.setdefault(d.get("round_no"), []).append(d)

    for rec in round_records:
        rno = rec["round_no"]
        life = rec["life"]
        finished = life.finish(rec["z"], deaths=rec["deaths"], roster_drops=rec["drops"])
        rec["finished"] = finished
        rnd_deaths = death_by_rnd.get(rno, [])

        # Check existing pairings from life.finish
        for ent in finished:
            did = ent.get("death_id")
            if did in death_by_id:
                d = death_by_id[did]
                vic = d.get("victim")
                v = verdicts.get(ent["id"])
                p_agent = v.get("agent") if v else None
                # Unpair impossible identity conflicts
                if p_agent is not None and vic and p_agent != vic:
                    ent["death_id"] = None
                    ent["end_reason"] = "last observation does not establish destruction/death"
                    ent["death_evidence"] = None
                    ent["end_ms"] = None
                    ent["right_censored_at_ms"] = ent["last_seen_ms"]
                elif p_agent is None and vic and arb is not None:
                    death_c = identity_claim(
                        ent["id"], vic, channel="death_victim", reason="vanished_at_death",
                        source_version=d.get("adjudication_version", "death-adjudication"),
                        observed_at_ms=d.get("t_ms"),
                        evidence={"death_id": did, "killer": d.get("killer"), "weapon": d.get("weapon")},
                        depends_on=[did],
                    )
                    arb.add(death_c)

        # Pair any remaining unlinked deaths with candidate tracks
        claimed = {ent["death_id"] for ent in finished if ent.get("death_id")}
        for d in sorted(rnd_deaths, key=lambda x: x.get("t_ms", 0)):
            did = d.get("death_id")
            if did in claimed:
                continue
            vic = d.get("victim")
            t_d = d.get("t_ms", 0)
            cands = []
            for ent in finished:
                if ent.get("family") != "ally" or ent.get("death_id"):
                    continue
                v = verdicts.get(ent["id"])
                p_agent = v.get("agent") if v else None
                if abs(ent["last_seen_ms"] - t_d) <= 3000.0 and (p_agent == vic or p_agent is None):
                    cands.append((abs(ent["last_seen_ms"] - t_d), ent, p_agent))
            if cands:
                cands.sort(key=lambda x: x[0])
                _, best_ent, p_agent = cands[0]
                best_ent["death_id"] = did
                best_ent["end_ms"] = t_d
                best_ent["end_reason"] = "death"
                best_ent["death_evidence"] = "killfeed_verdict"
                claimed.add(did)
                if p_agent is None and vic and arb is not None:
                    death_c = identity_claim(
                        best_ent["id"], vic, channel="death_victim", reason="vanished_at_death",
                        source_version=d.get("adjudication_version", "death-adjudication"),
                        observed_at_ms=t_d,
                        evidence={"death_id": did, "killer": d.get("killer"), "weapon": d.get("weapon")},
                        depends_on=[did],
                    )
                    arb.add(death_c)

    if arb is not None:
        verdicts = {v["entity_id"]: v for v in arb.verdict()}

    rows: list[dict] = []
    for rec in round_records:
        rows.extend(rec["obs_rows"])
        for ent in rec.get("finished", []):
            eid = ent["id"]
            fam = ent.get("family")
            agent = None
            status = ent.get("identity_status", "provisional")
            reason = None
            votes = None
            teammate_key = None

            if fam == "self":
                agent = player_agent
                status = "resolved" if player_agent else "provisional"
                teammate_key = f"{session_id}:teammate:{player_agent}" if player_agent else None
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
                    if agent:
                        teammate_key = f"{session_id}:teammate:{agent}"
                elif lineup:
                    status = "abstained"
                    reason = "no_claims"

            body = {k: v for k, v in ent.items()
                    if k not in ("appearance", "anchor_observation", "kind")}
            body["agent"] = agent
            body["teammate_key"] = teammate_key
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
