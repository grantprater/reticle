r"""Enemy tracks for a whole session, from stored observations only.

    .\.venv\Scripts\python.exe -m reticle enemy-tracks <session>

Owns [owns:enemy-track-session]. `round_lifetimes.RoundLifetimes` decides
which enemy icons are one entity, round by round, over the `minimap_object`
stream's enemies; nothing here decodes video or reads pixels.

**Endings.** Each round finishes with the stored enemy death verdicts
(`death`, side enemy, revives excluded). A track bound to a death is unbound
again when the death's X places it farther than `BIND_PX` * scale from the
track's last position, or when the track's adjudicated name is not the
victim's: the X and the name are two witnesses the binding must agree with.

**The "?".** The `minimap_object` stream's "?" detections each carry the
observation key of the enemy icon they replaced. Detections of one key
cluster into one mark. A mark binds to the track that held that icon when
the track is not observed again before the mark's last detection; otherwise
it stands alone, with the reason.

**Identity.** The enemy icons of each frame are named together by
`identity.claims_from_ally_icons(side="enemy")` against the lineup's enemy
five (`lineup.load_lineup`, which applies the scoreboard constraint). Each
claim is re-keyed from the observation to its track and declares
`depends_on` the lineup's enemy slots, whose verdicts supplied the
candidates; `adjudicate_agent_identity` decides each track's name and
`identity_events` publishes it. No lineup, or one that cannot name the
enemy five, refuses every claim with the reason.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .round_lifetimes import ROUND_LIFETIME_VERSION, RoundLifetimes

ENEMY_TRACK_VERSION = "enemy-track-0.1.0"

#: A death's X lies within this of its track's last position (px * scale):
#: twice the icon radius `minimap_objects.ICON_PX`.
BIND_PX = 20.0

#: The identity channel the claims come from, and the binding's own name.
CHANNEL = "minimap_portrait"
BINDING = "enemy_track"


def _observation(t: float, i: int, e: dict) -> dict:
    r = float(e["r"])
    return {"x": float(e["x"]), "y": float(e["y"]), "r": r,
            "box": [e["x"] - r, e["y"] - r, 2 * r, 2 * r], "family": "enemy",
            "view": "minimap", "label": "enemy", "observation_key": f"{t:.1f}:{i}"}


def _track_icon(t: float, i: int, e: dict, features_version: str | None) -> dict:
    """An enemy as `claims_from_ally_icons` reads it."""
    return {"frame_idx": int(round(t)), "t_ms": t, "index": i,
            "observation_key": f"{t:.1f}:{i}", "cx": e["x"], "cy": e["y"], "r": e["r"],
            "composition": None, "reason": None,
            "portrait_features": e.get("portrait_features"),
            "portrait_features_version": features_version}


def track_claims(sid: str, frames: list[dict], obs_entity: dict, lineup: dict | None,
                 references: dict | None, source_version: str,
                 features_version: str | None = None) -> list[dict]:
    """Identity claims for the tracks, re-keyed from each observation.
    `features_version` is the portrait features' stamp the frames carry."""
    from .adjudication.identity import claims_from_ally_icons, identity_claim

    icons = [_track_icon(f["t_ms"], i, e, features_version) for f in frames if f.get("reason") is None
             for i, e in enumerate(f.get("enemies") or ())]
    rows = ((lineup or {}).get("sides") or {}).get("enemy") or []
    slots = sorted(f"{sid}:enemy:slot:{r['slot']}" for r in rows if r.get("slot") is not None)
    if not lineup:
        raw = [identity_claim(f"{sid}:enemy_icon:{ic['observation_key']}", None,
                              channel=CHANNEL, reason="no_lineup",
                              source_version=source_version, observed_at_ms=ic["t_ms"])
               for ic in icons]
    else:
        raw = claims_from_ally_icons(icons, lineup, gallery={}, session_id=sid,
                                     source_version=source_version, references=references,
                                     side="enemy")
    prefix = f"{sid}:enemy_icon:"
    out = []
    for c in raw:
        key = c["entity_id"][len(prefix):]
        track = obs_entity.get(key)
        if track is None:
            continue
        out.append({**c, "entity_id": track, "binding_from": BINDING,
                    "depends_on": slots,
                    "evidence": {**(c.get("evidence") or {}), "observation_key": key}})
    return out


def _identity_reason(v: dict | None, why: Counter | None) -> str | None:
    """The verdict's reason; for an all-abstained track, its claims' common reason."""
    if v is None:
        return "no_claims"
    if v["status"] == "abstained" and why and len(why) == 1:
        return next(iter(why))
    return v["reason"] or None


def _marks(sid: str, rno: int, frames: list[dict], obs_entity: dict,
           seen: dict[str, list[float]]) -> list[dict]:
    """One mark per replaced icon: its "?" detections, and the track it binds."""
    groups: dict[str, list] = defaultdict(list)
    for f in frames:
        for q in f.get("questions") or ():
            groups[q["icon_key"]].append((f["t_ms"], q))
    out = []
    for key, dets in sorted(groups.items(), key=lambda kv: kv[1][0][0]):
        dets.sort(key=lambda d: d[0])
        xs = sorted(q["x"] for _t, q in dets)
        ys = sorted(q["y"] for _t, q in dets)
        first, last = dets[0][0], dets[-1][0]
        icon_last = dets[0][1]["icon_last_ms"]
        track = obs_entity.get(key)
        reason = None
        if track is None:
            reason = "icon_not_tracked"
        elif any(icon_last < t <= last for t in seen.get(track, ())):
            reason = "track_observed_during_mark"
        out.append({"kind": "mark", "round_no": rno, "mark_id": f"{sid}:R{rno}:Q:{key}",
                    "icon_key": key, "entity_id": None if reason else track,
                    "candidate_entity_id": track, "binding_reason": reason,
                    "x": xs[len(xs) // 2], "y": ys[len(ys) // 2],
                    "onset_ms": min(q["onset_ms"] for _t, q in dets),
                    "icon_last_ms": icon_last, "first_ms": first, "last_ms": last,
                    "detections": len(dets)})
    return out


def build(sid: str, object_rows: list[dict], rounds: list[dict], deaths: list[dict],
          lineup: dict | None, references: dict | None) -> dict:
    """`{"rows", "identity"}`: the `enemy_track` rows and the identity events.

    `object_rows` are the `minimap_object` rows (a coverage row, then frames);
    `rounds` come from `rounds.build_rounds`; `deaths` are `death` rows.
    """
    from .adjudication.identity import (AGENT_IDENTITY_VERSION, adjudicate_agent_identity,
                                        identity_events)

    head = next((r for r in object_rows if r.get("kind") == "coverage"), {})
    scale = float(head.get("scale") or 1.0)
    mo_version = head.get("minimap_object_version")
    frames = sorted((r for r in object_rows if r.get("kind") == "frame"),
                    key=lambda r: r["t_ms"])
    common = {"session_id": sid, "enemy_track_version": ENEMY_TRACK_VERSION}
    enemy_deaths = [d for d in deaths if d.get("kind") == "death_verdict"
                    and d.get("side") == "enemy" and not d.get("is_revive")]
    obs_entity: dict[str, str] = {}
    seen: dict[str, list[float]] = defaultdict(list)
    last_pos: dict[str, tuple] = {}
    records = []
    coverage = Counter()
    for rnd in rounds:
        a, z = rnd["t_start_ms"], rnd["t_end_ms"]
        inside = [f for f in frames if a <= f["t_ms"] < z]
        if not inside:
            coverage["rounds_without_frames"] += 1
            continue
        life = RoundLifetimes(f"{sid}:R{rnd['round_no']}", a, scale)
        obs_rows = []
        for f in inside:
            if f.get("reason") is not None:
                life.step(f["t_ms"], [], source_state="absent")
                coverage["absent_frames"] += 1
                continue
            enemies = f.get("enemies") or []
            out = life.step(f["t_ms"], [_observation(f["t_ms"], i, e)
                                        for i, e in enumerate(enemies)])
            coverage["frames"] += 1
            for o in out:
                i = int(o["observation_key"].split(":")[1])
                e = enemies[i]
                eid = o.get("entity_id")
                if eid:
                    obs_entity[o["observation_key"]] = eid
                    seen[eid].append(f["t_ms"])
                    last_pos[eid] = (o["x"], o["y"])
                obs_rows.append({"kind": "observation", "round_no": rnd["round_no"],
                                 "t_ms": f["t_ms"], "frame_idx": f.get("frame_idx"),
                                 "observation_key": o["observation_key"],
                                 "observation_id": o["observation_id"], "entity_id": eid,
                                 "state": o["state"], "identity_status": o["identity_status"],
                                 "alternatives": o["alternatives"],
                                 "x": round(o["x"], 2), "y": round(o["y"], 2),
                                 "r": e.get("r"), "facing": e.get("facing"),
                                 "facing_reason": e.get("facing_reason")})
        records.append({"round_no": rnd["round_no"], "life": life, "z": z, "obs": obs_rows,
                        "frames": inside,
                        "deaths": [d for d in enemy_deaths if d.get("round_no") == rnd["round_no"]]})
        coverage["rounds"] += 1

    claims = track_claims(sid, frames, obs_entity, lineup, references, mo_version,
                          head.get("portrait_features_version"))
    verdicts = {v["entity_id"]: v for v in adjudicate_agent_identity(claims)}
    # The arbiter reports an all-abstained track as such; the claims' own
    # refusal reasons (no_lineup, lineup_incomplete, ...) are the cause.
    abstain_why: dict[str, Counter] = defaultdict(Counter)
    for c in claims:
        if c.get("agent") is None:
            abstain_why[c["entity_id"]][str(c.get("reason") or "").split(":")[0]] += 1
    death_by_id = {d["death_id"]: d for d in enemy_deaths if d.get("death_id")}
    rows = []
    unbound = Counter()
    for rec in records:
        finished = rec["life"].finish(rec["z"], deaths=rec["deaths"])
        marks = _marks(sid, rec["round_no"], rec["frames"], obs_entity, seen)
        mark_of = {m["entity_id"]: m["mark_id"] for m in marks if m["entity_id"]}
        for ent in finished:
            v = verdicts.get(ent["id"])
            agent = v["agent"] if v else None
            d = death_by_id.get(ent.get("death_id"))
            why = None
            if d is not None:
                loc = d.get("location")
                lp = last_pos.get(ent["id"])
                if loc and lp and math.hypot(loc[0] - lp[0], loc[1] - lp[1]) > BIND_PX * scale:
                    why = "death_x_elsewhere"
                elif agent and d.get("victim") and d["victim"] != agent:
                    why = "victim_is_another_agent"
            if why:
                unbound[why] += 1
                ent.update(death_id=None, end_ms=None, death_evidence=None,
                           end_reason="last observation does not establish destruction/death",
                           right_censored_at_ms=ent["last_seen_ms"], death_unbound=why)
            lp = last_pos.get(ent["id"])
            rows.append({**common, "kind": "entity", "round_no": rec["round_no"],
                         **{k: ent.get(k) for k in (
                             "id", "name", "first_seen_ms", "last_seen_ms", "observations",
                             "gaps", "max_gap_ms", "end_reason", "end_ms", "death_id",
                             "death_evidence", "right_censored_at_ms", "death_unbound")},
                         "last_x": None if lp is None else round(lp[0], 2),
                         "last_y": None if lp is None else round(lp[1], 2),
                         "agent": agent,
                         "identity_status": v["status"] if v else "abstained",
                         "identity_reason": _identity_reason(v, abstain_why.get(ent["id"])),
                         "mark_id": mark_of.get(ent["id"])})
        rows += [{**common, **o} for o in rec["obs"]]
        rows += [{**common, **m} for m in marks]
    identity = []
    for v in verdicts.values():
        t = max((c.get("observed_at_ms") or 0.0) for c in v["claims"])
        identity += identity_events([v], sid, t)
    status = Counter(v["status"] for v in verdicts.values())
    refusal = Counter(v["reason"] for v in verdicts.values() if v["status"] != "resolved")
    ents = [r for r in rows if r["kind"] == "entity"]
    summary = {**common, "kind": "summary", "minimap_object_version": mo_version,
               "round_lifetime_version": ROUND_LIFETIME_VERSION,
               "agent_identity_version": AGENT_IDENTITY_VERSION,
               "lineup_version": (lineup or {}).get("version"),
               "references_version": (references or {}).get("version"),
               "death_adjudication_version": next(
                   (r.get("death_adjudication_version") for r in deaths
                    if r.get("kind") == "summary"), None),
               "scale": scale, "tracks": len(ents), "rounds": coverage["rounds"],
               "coverage": dict(coverage), "identity": dict(status),
               "identity_refusals": dict(refusal.most_common(8)),
               "deaths": sum(r["end_reason"] == "death" for r in ents),
               "death_unbound": dict(unbound),
               "marks": sum(r["kind"] == "mark" for r in rows),
               "marks_bound": sum(r["kind"] == "mark" and r["entity_id"] is not None
                                  for r in rows)}
    return {"rows": [summary] + rows, "identity": identity}


def enemy_session_tracks(store, sid: str) -> dict:
    """`build` over a session's stored streams, or `{"skipped": why}`."""
    from .adjudication.identity import load_ally_portrait_references
    from .lineup import load_lineup
    from .minimap_objects import minimap_object_version

    got = store.events_version("minimap_object", sid)
    if got != minimap_object_version():
        return {"skipped": f"minimap_object is {got}, not {minimap_object_version()} -- "
                           f"run `reticle minimap-objects {sid}`"}
    man = store.read_manifest(sid)
    rounds = store.read_rounds(sid, man["ingested_at"][:10])
    if rounds is None:
        return {"skipped": f"no stored rounds -- run `reticle rounds {sid}`"}
    return build(sid, store.read_events("minimap_object", sid), rounds.to_pylist(),
                 store.read_events("death", sid) or [], load_lineup(sid, store.root),
                 load_ally_portrait_references(store.root))
