"""Round entity lifetimes for a whole session, from stored observations only.

`round_lifetimes.RoundLifetimes` decides which observations are one entity.
This runs it over every round of a session from what is already stored -- the
`ally_icon` events (ally fits, their descriptors and the player's own fit), the
HUD's round bounds, the roster's alive count, and stored death verdicts -- and
writes `round_entity` events. Nothing here decodes video or reads pixels.
Ally segments are split where the best teammate changes and stays changed, and
`adjudication.identity` names the pieces per round (`assign_ally_pieces`, then
the arbiter); killfeed deaths bind to segment ends and never name them, so
they stay the independent check. Named pieces carry persistent teammate keys.

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

# 0.7.0 (2026-09-26): ally segments split where the best teammate changes and
# stays changed; `identity.assign_ally_pieces` names the pieces per round.
# Killfeed deaths bind to segment ends and no longer name anything; the
# in-session exemplar pass is gone.
# 0.6.0 (2026-09-26): an ally segment whose icons fit no teammate's rendered
# art (`identity.teammate_fit_refusal`) is refused as not a teammate.
ROUND_ENTITY_VERSION = "round-entity-0.7.0"

#: Viterbi switch penalty, in units of the claims' margin gate: a segment is
#: cut only where the best teammate changes and stays changed.
SWITCH = 5.0
#: Roster reads either side of a frame; the largest stands, because the count
#: drops at a death while the dying teammate's icon may still show.
ROSTER_LAG_MS = 500.0


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
    teammate_deaths = [d for d in (deaths or [])
                       if d.get("kind") == "death_verdict" and d.get("side") == "ally"
                       and (not player_agent or d.get("victim") != player_agent)]
    death_by_id = {d["death_id"]: d for d in teammate_deaths if d.get("death_id")}
    death_by_rnd: dict[int, list[dict]] = {}
    for d in teammate_deaths:
        death_by_rnd.setdefault(d.get("round_no"), []).append(d)

    for rec in round_records:
        finished = rec["life"].finish(rec["z"], deaths=rec["deaths"], roster_drops=rec["drops"])
        rec["finished"] = finished
        # A pairing whose segment carries another agent's name is undone.
        for ent in finished:
            did = ent.get("death_id")
            if did in death_by_id:
                vic, p_agent = death_by_id[did].get("victim"), agent_of(ent["id"])
                if p_agent is not None and vic and p_agent != vic:
                    ent["death_id"] = None
                    ent["end_reason"] = "last observation does not establish destruction/death"
                    ent["death_evidence"] = None
                    ent["end_ms"] = None
                    ent["right_censored_at_ms"] = ent["last_seen_ms"]
        # Pair any remaining unlinked deaths with a nearby segment end.
        claimed = {ent["death_id"] for ent in finished if ent.get("death_id")}
        for d in sorted(death_by_rnd.get(rec["round_no"], []), key=lambda x: x.get("t_ms", 0)):
            did, vic, t_d = d.get("death_id"), d.get("victim"), d.get("t_ms", 0)
            if did in claimed:
                continue
            cands = [(abs(ent["last_seen_ms"] - t_d), ent) for ent in finished
                     if ent.get("family") == "ally" and not ent.get("death_id")
                     and abs(ent["last_seen_ms"] - t_d) <= 3000.0
                     and agent_of(ent["id"]) in (vic, None)]
            if cands:
                best_ent = min(cands, key=lambda x: x[0])[1]
                best_ent.update(death_id=did, end_ms=t_d, end_reason="death",
                                death_evidence="killfeed_verdict")
                claimed.add(did)

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
                    if k not in ("appearance", "anchor_observation", "kind")}
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
                                           named["pieces_of"][ent["id"]], session_id):
                    rows.append({**head, **piece})
                continue
            if fam == "ally" and lineup:
                body["identity_status"], body["identity_reason"] = "abstained", "no_claims"
            rows.append({**head, **body})
        report = rec["life"].association_report()
        rows.append({**common, "kind": "associations", "round_no": rec["round_no"],
                     **report})

    return [{**common, "kind": "coverage", **coverage}] + rows


def _piece_bodies(body, pieces, verdicts, ids, session_id):
    """Entity bodies for one segment's pieces: each carries its own span and
    name; only the last inherits the segment's ending."""
    out = []
    for j, pid in enumerate(ids):
        p, v = pieces[pid], verdicts[pid]
        ts = p["t"]
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        row = {**body, "id": pid, "segment_id": body["id"], "piece_index": j,
               "pieces_of_segment": len(ids), "first_seen_ms": ts[0], "last_seen_ms": ts[-1],
               "observations": len(ts), "gaps": sum(g > 150 for g in gaps),
               "max_gap_ms": max(gaps, default=0),
               "agent": v["agent"], "identity_status": v["status"],
               "teammate_key": f"{session_id}:teammate:{v['agent']}" if v["agent"] else None,
               "identity_evidence": {k: v[k] for k in ("evidence_sum", "reference_source",
                                                       "gap", "fit", "exact")},
               "identity_votes": v["votes"]}
        if v["reason"]:
            row["identity_reason"] = v["reason"]
        if j < len(ids) - 1:
            row.update(end_ms=None, right_censored_at_ms=ts[-1], death_id=None,
                       death_evidence=None, end_reason="split: best teammate changed")
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
    assigned = assign_ally_pieces(pieces, frames, capacity,
                                  teammate_fit=(references or {}).get("teammate_fit"))
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
