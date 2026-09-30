"""The entity-event projection and its read API.

[owns:entity-event]. `docs/ENTITY_EVENTS.md` is the plan. `project_lane`
copies what each owner stored into the one schema `entity_contract` declares
and writes each lane's consumer output and ledger through
`store.write_events`; `EntityEvents` is the only door a consumer reads events
through (`architecture.toml`, `[consumers]`). Stage 1 projects three lanes:
`round_entity`, `death` and `spike`.

It decides nothing. It invents no key, name, time or position; a threshold,
a margin or a vote belongs to an owner, and two owners that disagree go to
the ledger side by side. A projected event is never stored back as evidence.
Every name it copies comes from a resolved verdict of `adjudication.identity`,
so a lane that copies a name rests on the arbiter: `NAME_ARBITER` is the
arbiter stamp this declaration was written against, and a test pins it to
`AGENT_IDENTITY_VERSION`. It is a literal so that importing this module, as
every consumer does, loads no adjudicator.

The drop rule
-------------
A projected row reaches the consumer output only when all four hold, and the
first that fails sets the row's standing in the ledger:

1. its owner accepted it: not a refusal row, not an abstention;
2. every name comes from a resolved arbiter verdict (the contract marks no
   other field required yet); an optional field that fails stays in the row
   as null with `withheld: <ledger id>`, and a ledger row holds it;
3. no stored disagreement names it, and no two owners give different
   resolved values under one shared key -- an equality with no tolerance;
4. every input it rests on is current by `plan.stale`, the owner of
   staleness, which applies the declared waivers.

A withheld row goes to the ledger whole, as the ledger row's `subject`, so
a review tool can draw it apart. The standing a ledger row
carries is a declared translation of the owner's own status
(`IDENTITY_STANDING`, `DEATH_STANDING`), and the owner's reason stays
verbatim.

Between observations
--------------------
An alive ally or self track gets an `estimate` row only where an owner
stores an estimate. None does yet: allies have no estimate owner
(`entity_contract.NO_ESTIMATE_OWNER`), and `position-belief`, the player's,
stores nothing. Each gap the track owner declares (`round_entities.track_gaps`)
is therefore an `unobserved` span in the round's coverage row, with its
cause, and counts as estimate debt in the resolution metric.

Staleness
---------
Each lane file opens with a stamp row whose `inputs` map each input stream to
`<stamp>@<sha256 prefix>` of the stored file, so a rerun that keeps its stamp
still shows. `lane_status` names a lane `plan` must rebuild: code or contract
moved, or an input's stored stamp or bytes differ from what the lane read. A
lane whose inputs are themselves stale is current as projected and is
reported as held: its rows wait in the ledger as `stale` until the input is
refreshed and the lane is rebuilt.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from .entity_contract import (ENTITY_CONTRACT_VERSION, LEDGER_SUFFIX, NO_ESTIMATE_OWNER,
                              STREAM_PREFIX, estimate_gap_reason, validate_lane)

#: The arbiter every naming lane rests on; a change to it rebuilds each lane
#: whose `names` is true (plan section 3, "Version stamp and staleness").
#: Pinned to `adjudication.identity.AGENT_IDENTITY_VERSION` by a test.
NAME_ARBITER = "agent-identity-0.9.0"

#: The lanes, in the plan's order: minimap and screen lanes first, audio
#: last. `inputs` are the stored streams each reads; a lane waiting on an
#: owner that does not exist says so in `waits_for`. The round_entity lane
#: reads the death verdicts too: its one shared key with them is the death a
#: track's end binds, and the equality check needs both answers.
ENTITY_LANES: tuple[dict, ...] = (
    {"lane": "round_entity", "order": 1, "channel": "minimap", "names": True,
     "inputs": ("round_entity", "rounds", "death", "death_identity")},
    {"lane": "death", "order": 1, "channel": "killfeed, HUD, scoreboard", "names": True,
     "inputs": ("death", "death_identity", "rounds")},
    {"lane": "spike", "order": 1, "channel": "minimap, round table", "names": False,
     "inputs": ("rounds", "spike_carrier")},
    {"lane": "players", "order": 2, "channel": "arbiter over every channel", "names": True,
     "inputs": ("rounds",), "waits_for": "the arbiter's stored side verdict (gap 1)"},
    {"lane": "smoke", "order": 2, "channel": "minimap", "names": True,
     "inputs": ("smoke", "smoke_owner", "smoke_owner_identity", "rounds")},
    {"lane": "ping", "order": 2, "channel": "minimap", "names": False,
     "inputs": ("ping", "rounds")},
    {"lane": "enemy", "order": 2, "channel": "minimap", "names": True,
     "inputs": (), "waits_for": "an enemy icon owner and a last-known mark owner (gap 3)"},
    {"lane": "slot_state", "order": 3, "channel": "tray", "names": True,
     "inputs": ("ability_state", "tray_kit", "tray_kit_identity")},
    {"lane": "ult_cast", "order": 4, "channel": "audio", "names": True,
     "inputs": ("ult_cast", "ult_cast_identity", "rounds")},
    {"lane": "disagreement", "order": None, "channel": "every channel", "names": False,
     "inputs": ("spike_carrier",),
     "waits_for": "reconciliation's stored disagreements as a stream"},
)
LANE = {spec["lane"]: spec for spec in ENTITY_LANES}

#: The projection's version per built lane; the consumer file and the ledger
#: share it.
LANE_VERSIONS = {
    "round_entity": "entity-round-entity-0.1.0",
    "death": "entity-death-0.1.0",
    "spike": "entity-spike-0.1.0",
}
PROJECTED = tuple(LANE_VERSIONS)

#: An owner's identity status -> ledger standing (plan section 2, "The
#: ledger row"). `provisional` is round_entity's per-observation status.
IDENTITY_STANDING = {"resolved": "resolved", "abstained": "abstained",
                     "provisional": "abstained", "contested": "ambiguous",
                     "disagreement": "ambiguous", "ambiguous": "ambiguous",
                     "refused": "refused"}
#: The death owner's verdict status -> standing. An abstained verdict fails
#: rule 1; the others concern the victim's name, an optional field.
DEATH_STANDING = {"resolved": "resolved", "abstained": "abstained",
                  "contested": "ambiguous", "disagreement": "ambiguous"}
#: A weapon read's status -> standing.
WEAPON_STANDING = {"resolved": "resolved", "refused": "refused", "abstained": "abstained"}

#: The first-row stamp key of each event stream a lane reads; an identity
#: stream's stamp is its first verdict's `producer_version`.
INPUT_STAMP_KEYS = {"round_entity": "round_entity_version",
                    "death": "death_adjudication_version",
                    "spike_carrier": "spike_carrier_version"}
IDENTITY_INPUTS = ("death_identity",)

#: The owners each lane's rows come from (ownership.toml ids).
OWNER = {"round_entity": "round-entity-session", "death": "death-victim",
         "rounds": "round-bounds", "spike_carrier": "spike-carrier",
         "arbiter": "agent-identity"}

PLAYER_REASON = "not_read: the players lane waits on the arbiter's side verdict (gap 1)"
#: A self track's gap: its estimate owner exists and stores nothing.
NO_STORED_ESTIMATE = "not_observed: no_stored_estimate: position-belief stores none"


class StaleLanes(RuntimeError):
    """A lane whose stored inputs moved since it was projected."""

    def __init__(self, lanes: dict[str, str]):
        self.lanes = dict(lanes)
        super().__init__("stale entity lanes: " + "; ".join(
            f"{k}: {v}" for k, v in sorted(self.lanes.items()))
            + " -- rebuild with `reticle project <session> --lane <lane>`")


def lane_streams(lane: str) -> tuple[str, str]:
    """The consumer stream and the ledger stream of a lane."""
    return f"{STREAM_PREFIX}{lane}", f"{STREAM_PREFIX}{lane}{LEDGER_SUFFIX}"


# ------------------------------------------------------------------ inputs

def _ingest_date(store, sid: str) -> str:
    return store.read_manifest(sid)["ingested_at"][:10]


def _sha16(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def _first(path, needle: bytes | None = None) -> dict | None:
    with open(path, "rb") as f:
        for ln in f:
            if ln.strip() and (needle is None or needle in ln):
                return json.loads(ln)
    return None


def input_stamp(store, sid: str, stream: str) -> str | None:
    """`<stamp>@<sha256 prefix>` of a stored input, or None when it is absent
    or carries no stamp."""
    if stream == "rounds":
        import pyarrow.parquet as pq
        path = store.rounds_path(sid, _ingest_date(store, sid))
        if not path.is_file():
            return None
        meta = pq.read_schema(path).metadata or {}
        stamp = (meta.get(b"round_version") or b"").decode() or None
    else:
        path = store.events_path(stream, sid)
        if not path.is_file():
            return None
        if stream in IDENTITY_INPUTS:
            head = _first(path, b'"event_kind":"identity_distribution"')
            stamp = (head or {}).get("producer_version")
        else:
            stamp = (_first(path) or {}).get(INPUT_STAMP_KEYS.get(stream, f"{stream}_version"))
    return None if not stamp else f"{stamp}@{_sha16(path)}"


def _lane_head(store, sid: str, lane: str) -> dict | None:
    if not hasattr(store, "events_path"):       # a store that holds no files
        return None
    path = store.events_path(lane_streams(lane)[0], sid)
    return _first(path) if path.is_file() else None


def rebuild_reason(store, sid: str, lane: str) -> str | None:
    """Why a projected lane must be rebuilt, or None when it is current
    against what is stored now (or was never projected)."""
    head = _lane_head(store, sid, lane)
    if head is None:
        return None
    consumer, _ledger = lane_streams(lane)
    got = head.get(f"{consumer}_version")
    if got != LANE_VERSIONS.get(lane):
        return f"{got} -> {LANE_VERSIONS.get(lane)}"
    if head.get("contract") != ENTITY_CONTRACT_VERSION:
        return f"contract {head.get('contract')} -> {ENTITY_CONTRACT_VERSION}"
    recorded = head.get("inputs") or {}
    moved = [s for s in LANE[lane]["inputs"] if recorded.get(s) != input_stamp(store, sid, s)]
    return f"inputs moved: {', '.join(moved)}" if moved else None


def lane_status(store, sid: str, moving: set[str]) -> dict:
    """For `plan`: `{"derived": [...], "held": [...]}` over the projected lanes.

    `derived` names each lane to rebuild with its command; `held` names each
    current lane whose inputs are themselves stale (`moving`), so its rows
    wait in the ledger as `stale` until those inputs and then the lane are
    rebuilt."""
    derived, held = [], []
    for lane in PROJECTED:
        head = _lane_head(store, sid, lane)
        if head is None:
            continue
        consumer, _ = lane_streams(lane)
        why = rebuild_reason(store, sid, lane)
        if why is not None:
            derived.append({"stream": consumer, "stored": head.get(f"{consumer}_version"),
                            "current": LANE_VERSIONS[lane], "inputs_moved": [why],
                            "how": "storage",
                            "command": f"reticle project {sid} --lane {lane}"})
            continue
        waiting = sorted(s for s in LANE[lane]["inputs"] if s in moving)
        if waiting:
            held.append({"stream": consumer, "waits_for": waiting})
    return {"derived": derived, "held": held}


def stale_inputs(store, sid: str) -> dict[str, str]:
    """Stream -> why `plan.stale` calls it stale, for rule 4."""
    from . import plan
    p = plan.stale(store, [sid])[sid]
    out = {}
    for d in p["decode"]:
        out[d["stream"]] = f"reread: {d['stored']} -> {d['current']}"
    for d in p["derived"]:
        if d["stream"].startswith(STREAM_PREFIX):
            continue
        why = (f"{d['stored']} -> {d['current']}" if d["stored"] != d["current"]
               else "inputs " + ", ".join(d["inputs_moved"]))
        out[d["stream"]] = why
    return out


def round_rows(store, sid: str) -> list[dict]:
    """The round table's rows, as the round-bounds owner stored them."""
    table = store.read_rounds(sid, _ingest_date(store, sid))
    return [] if table is None else table.to_pylist()


def widget_placement(manifest: dict) -> dict:
    """Where the lanes' `baked:` frame sits in the capture: the capture box
    the minimap crops came from (None keeps the profile's ROI), and whether
    the widget is a variant read through a stored transform."""
    from .widget_frame import capture_box, is_variant
    return {"capture_box": capture_box(manifest), "variant": is_variant(manifest)}


# -------------------------------------------------------------- row makers

def _reasoned(row: dict, field: str, value, reason: str) -> None:
    row[field] = value
    if value is None:
        row[f"{field}_reason"] = reason


def _producer(owner: str, version: str) -> dict:
    return {"owner": owner, "version": version}


def _name_block(agent: str, ref: str, arbiter: str) -> dict:
    return {"agent": agent, "ref": ref, "arbiter": arbiter}


class _Lane:
    """One lane's rows as they are built: consumer rows, ledger rows by
    subject, and the verdict statuses the identities cite."""

    def __init__(self, lane: str, held: dict[str, str]):
        self.lane = lane
        self.held = held                  # input stream -> why stale
        self.rows: list[dict] = []
        self.ledger: dict[str, dict] = {}
        self.verdicts: dict[str, str] = {}
        self.debt = Counter()

    def ledger_id(self, key: str) -> str:
        return f"{self.lane}:{key}"

    def withhold(self, key: str, subject: dict, standing: str, reason: str,
                 fields: dict, returns_to: list[str]) -> str:
        lid = self.ledger_id(key)
        row = self.ledger.get(lid)
        if row is None:
            self.ledger[lid] = {"row": "withheld", "ledger_id": lid, "lane": self.lane,
                                "subject": subject, "standing": standing, "reason": reason,
                                "fields": dict(fields), "returns_to": list(returns_to),
                                "residual": False, "contract": ENTITY_CONTRACT_VERSION}
        else:
            row["fields"].update(fields)
            row["returns_to"] += [r for r in returns_to if r not in row["returns_to"]]
        return lid

    def withhold_row(self, key: str, subject: dict, standing: str, reason: str,
                     projected: dict, owner: str, evidence: list, returns_to: list[str],
                     extra: dict | None = None) -> None:
        """Withhold a whole row: the ledger's `subject` is the projected row
        itself (its producer names the owner and its evidence the rows it
        copies), so review can draw it apart; `extra` holds the fields in
        question with their alternatives. `subject`, `owner` and `evidence`
        name the row where it has no projection of its own."""
        whole = projected if projected is not None else subject
        self.withhold(key, whole, standing, reason, dict(extra or {}), returns_to)

    def stale_reason(self, rests_on) -> str | None:
        moved = [f"{s} ({self.held[s]})" for s in rests_on if s in self.held]
        return ("stale input: " + "; ".join(moved)) if moved else None


def _frame_of(store, sid: str, manifest: dict) -> tuple[str | None, str | None]:
    """The lanes' position frame, or None with the reason no frame is named."""
    from . import geometry
    key = geometry.key_of(sid, store.root)
    if key is None:
        return None, "not_read: the session's map or profile is not recorded"
    if widget_placement(manifest)["variant"]:
        return None, ("not_read: the widget is a variant; no stored transform takes its "
                      "pixels to the baked frame")
    return f"baked:{key}", None


# ------------------------------------------------------------ death verdicts

def _death_verdicts(store, sid: str) -> tuple[dict, dict, str | None]:
    """death_id -> verdict row, identity ref -> (status, top agent), arbiter."""
    deaths = {r["death_id"]: r for r in store.read_events("death", sid)
              if r.get("kind") == "death_verdict"}
    verdicts, arbiter = {}, None
    for r in store.read_events("death_identity", sid):
        if r.get("event_kind") != "identity_distribution":
            continue
        arbiter = arbiter or r.get("producer_version")
        dist = (r.get("identity_distribution") or {}).get("distribution") or {}
        top = max(sorted(dist), key=lambda a: dist[a]) if dist else None
        verdicts[r["entity_id"]] = ((r.get("metadata") or {}).get("status"), top)
    return deaths, verdicts, arbiter


def _named(verdicts: dict, ref: str, agent) -> tuple[str | None, str]:
    """The name a resolved verdict gives, and the verdict's status.

    The owner's copy and the arbiter's verdict must agree; a stored name the
    verdict does not resolve, or resolves to another agent, is no name."""
    status, top = verdicts.get(ref, (None, None))
    if status == "resolved" and agent and top == agent:
        return agent, "resolved"
    if status == "resolved" and agent and top != agent:
        return None, "disagreement"
    return None, status or "not_stored"


# ------------------------------------------------------------------ lanes

def _round_entity_lane(store, sid, L: _Lane, manifest) -> dict:
    from .round_entities import track_gaps
    from .adjudication.identity import player_entity

    rows = store.read_events("round_entity", sid)
    head = rows[0] if rows else {}
    version = head.get("round_entity_version")
    arbiter = head.get("agent_identity_version")
    ally_icon_version = store.events_version("ally_icon", sid)
    frame, frame_reason = _frame_of(store, sid, manifest)
    deaths, dverdicts, _darb = _death_verdicts(store, sid)
    producer = _producer(OWNER["round_entity"], version)
    rests_on = ("round_entity", "rounds")
    player_ref = f"identity:{player_entity(sid)}"

    ents = [r for r in rows if r.get("kind") == "entity"]
    obs_by: dict[str, list[dict]] = {}
    refused = []
    for r in rows:
        if r.get("kind") != "observation":
            continue
        if r.get("entity_id") is None:
            refused.append(r)
        else:
            obs_by.setdefault(r["entity_id"], []).append(r)

    def pose(o, entity_id):
        ev = {"row": "event", "event_id": f"pose:{o['observation_id']}",
              "entity_id": entity_id, "kind": "pose", "round": o["round_no"],
              "observed_ms": o["t_ms"]}
        _reasoned(ev, "observed_last_ms", None, "not_applicable: one frame")
        _reasoned(ev, "occurred", None, "not_applicable: observed")
        pos = None
        if frame is not None and o.get("x") is not None and o.get("y") is not None:
            pos = {"frame": frame, "x": o["x"], "y": o["y"]}
            if isinstance(o.get("r"), (int, float)):
                pos["r"] = o["r"]
        _reasoned(ev, "position", pos, frame_reason or "not_read: the observation has no x, y")
        _reasoned(ev, "orientation", None,
                  "not_read: no pose owner keys a facing by this observation")
        _reasoned(ev, "state", None, "not_applicable")
        evidence = [{"stream": "round_entity", "id": o["observation_id"], "version": version}]
        if o.get("observation_key") and ally_icon_version:
            evidence.append({"stream": "ally_icon", "id": o["observation_key"],
                             "version": ally_icon_version})
        ev.update(evidence=evidence, producer=producer, lane=L.lane,
                  contract=ENTITY_CONTRACT_VERSION)
        return ev

    rounds_rows: dict[int, dict] = {}
    for e in ents:
        eid, fam = e["id"], e["family"]
        family, kind = (("furniture", "barrier") if fam == "barrier" else ("icon_track", fam))
        row = {"row": "entity", "entity_id": eid, "family": family, "kind": kind}
        _reasoned(row, "side", "ally" if family == "icon_track" else None,
                  "not_applicable: furniture has no side")
        row["round"] = e["round_no"]
        life = {"first_observed_ms": e.get("first_seen_ms"),
                "last_observed_ms": e.get("last_seen_ms")}
        began = (None if e.get("origin_ms") is None else
                 {"lo_ms": e["origin_ms"], "hi_ms": e["origin_ms"],
                  "basis": f"round_entity origin_ms: {e.get('origin_reason')}"})
        _reasoned(life, "began", began, f"not_observed: {e.get('origin_reason')}")
        ended = (None if e.get("end_ms") is None else
                 {"lo_ms": e["end_ms"], "hi_ms": e["end_ms"],
                  "basis": f"round_entity end_ms: {e.get('end_reason')}"
                           + (f" ({e['death_id']})" if e.get("death_id") else "")})
        _reasoned(life, "ended", ended, f"not_observed: {e.get('end_reason')}")
        _reasoned(life, "censored_at_ms", e.get("right_censored_at_ms"),
                  "not_applicable: the track's end is stored")
        row["lifetime"] = life

        # Rule 2: the name, from the arbiter's verdict only.
        fields_withheld = {}
        id_detail = None
        identity, id_reason = None, "not_applicable: furniture carries no name"
        if family == "icon_track":
            ref = player_ref if fam == "self" else f"identity:{eid}"
            status = e.get("identity_status")
            L.verdicts[ref] = status
            if status == "resolved" and e.get("agent"):
                identity = _name_block(e["agent"], ref, arbiter)
            else:
                standing = IDENTITY_STANDING.get(status, "abstained")
                id_reason = f"withheld: {L.ledger_id(eid)}"
                fields_withheld["identity"] = {
                    "standing": standing,
                    "alternatives": [{"value": a, "owner": OWNER["arbiter"],
                                      "evidence": [f"round_entity:{eid}"]}
                                     for a in sorted(e.get("identity_votes") or {})]}
                id_detail = e.get("identity_reason") or status
        _reasoned(row, "identity", identity, id_reason)
        _reasoned(row, "player", None, PLAYER_REASON)
        row.update(producer=producer, lane=L.lane, contract=ENTITY_CONTRACT_VERSION)
        evidence = [f"round_entity:{eid}"]
        subject = {"row": "entity", "entity_id": eid, "round": e["round_no"]}
        obs = sorted(obs_by.get(eid, []), key=lambda o: (o["t_ms"], o["observation_id"]))
        events = [pose(o, eid) for o in obs]

        # Rule 3: one shared key, the death the track's end binds.
        standing, reason, returns, extra = None, None, [], {}
        if identity is not None and e.get("death_id") in deaths:
            d = deaths[e["death_id"]]
            victim, vstatus = _named(dverdicts, f"identity:{e['death_id']}", d.get("victim"))
            if victim is not None and victim != identity["agent"]:
                standing = "disputed"
                reason = (f"binding: round_entity binds {e['death_id']} to an entity named "
                          f"{identity['agent']}; the death owner names its victim {victim}")
                returns = [OWNER["round_entity"]]
                extra = {"identity": {"standing": "disputed", "alternatives": [
                    {"value": identity["agent"], "owner": OWNER["round_entity"],
                     "evidence": evidence},
                    {"value": victim, "owner": OWNER["death"],
                     "evidence": [e["death_id"]]}]}}
        # Rule 4.
        if standing is None:
            why = L.stale_reason(rests_on)
            if why is not None:
                standing, reason, returns = "stale", why, [OWNER["round_entity"]]
        if standing is not None:
            L.withhold_row(eid, subject, standing, reason, row, OWNER["round_entity"],
                           evidence, returns, {**fields_withheld, **extra})
            for ev in events:
                L.withhold_row(ev["event_id"], {"row": "event", "event_id": ev["event_id"],
                                                "entity_id": eid, "round": e["round_no"],
                                                "observed_ms": ev["observed_ms"]},
                               standing, f"entity {eid} withheld: {standing}", ev,
                               OWNER["round_entity"], ev["evidence"], returns)
            continue
        if fields_withheld:
            L.withhold(eid, subject, fields_withheld["identity"]["standing"],
                       f"identity: {id_detail}", fields_withheld, [OWNER["arbiter"]])
        L.rows.append(row)
        L.rows.extend(events)

        # Coverage: observed runs and the owner's gaps.
        times = [o["t_ms"] for o in obs]
        cov = rounds_rows.setdefault(e["round_no"], {"observed": [], "unobserved": []})
        gaps = track_gaps(times)
        cause = (estimate_gap_reason(family, kind) or
                 (NO_STORED_ESTIMATE if (family, kind) == ("icon_track", "self")
                  else "not_observed: between observations"))
        lo = times[0] if times else None
        for a, b in gaps:
            cov["observed"].append({"lo_ms": lo, "hi_ms": a, "entity_id": eid})
            cov["unobserved"].append({"lo_ms": a, "hi_ms": b, "entity_id": eid,
                                      "cause": cause})
            if cause in (NO_ESTIMATE_OWNER, NO_STORED_ESTIMATE):
                L.debt["estimate_spans"] += 1
                L.debt["estimate_ms"] += b - a
            lo = b
        if times:
            cov["observed"].append({"lo_ms": lo, "hi_ms": times[-1], "entity_id": eid})

    for o in sorted(refused, key=lambda o: (o["t_ms"], o["observation_id"])):
        ev = pose(o, None)
        ev["entity_id_reason"] = f"not_read: {o.get('state')}"
        L.withhold_row(ev["event_id"], {"row": "event", "event_id": ev["event_id"],
                                        "round": o["round_no"],
                                        "observed_ms": o["t_ms"]},
                       "refused", str(o.get("state")), ev, OWNER["round_entity"],
                       ev["evidence"], [OWNER["round_entity"]])
    for rn in sorted(rounds_rows):
        cov = rounds_rows[rn]
        L.rows.append({"row": "coverage", "lane": L.lane, "round": rn,
                       "observed": cov["observed"], "unobserved": cov["unobserved"],
                       "contract": ENTITY_CONTRACT_VERSION})
    return {"arbiter": arbiter}


def _death_lane(store, sid, L: _Lane, manifest) -> dict:
    rows = store.read_events("death", sid)
    head = rows[0] if rows else {}
    version = head.get("death_adjudication_version")
    deaths, verdicts, arbiter = _death_verdicts(store, sid)
    producer = _producer(OWNER["death"], version)
    rests_on = ("death", "death_identity", "rounds")
    for did in sorted(deaths, key=lambda k: (deaths[k]["t_ms"], k)):
        d = deaths[did]
        eid = f"death:{did}"
        ev = {"row": "event", "event_id": eid, "entity_id": did, "kind": "death",
              "round": d.get("round_no"), "observed_ms": d["t_ms"]}
        _reasoned(ev, "observed_last_ms", d.get("t_last_ms"), "not_read: t_last_ms null")
        _reasoned(ev, "occurred", None, "not_read: no_owner_bound")
        loc = d.get("location")
        pos = None
        _reasoned(ev, "position", pos, "not_read: location null" if loc is None else
                  "not_read: the death owner's location has no declared frame")
        _reasoned(ev, "orientation", None, "not_applicable")
        fields = {}
        state = {"cause": d.get("death_cause")}
        wev = d.get("weapon_evidence") or {}
        wstanding = WEAPON_STANDING.get(wev.get("status"), "abstained")
        if d.get("weapon") and wstanding == "resolved":
            state["weapon"] = d["weapon"]
        else:
            state["weapon"] = None
            state["weapon_reason"] = f"withheld: {L.ledger_id(did)}"
            fields["weapon"] = {"standing": wstanding, "alternatives": []}
        state["second_life"] = d.get("is_second_life")
        state["revive"] = d.get("is_revive")
        for k in ("second_life", "revive"):
            if state[k] is None:
                state[f"{k}_reason"] = "not_read: the death owner stores none"
        if state["cause"] is None:
            state["cause_reason"] = "not_read: death_cause null"
        ev["state"] = state
        # Rule 2: the victim and killer names, from resolved verdicts only.
        vref, kref = f"identity:{did}", f"identity:{did}:killer"
        victim, vstatus = _named(verdicts, vref, d.get("victim"))
        L.verdicts[vref] = "resolved" if victim else vstatus
        if victim:
            ev["identity"] = _name_block(victim, vref, arbiter)
        else:
            ev["identity"] = None
            ev["identity_reason"] = f"withheld: {L.ledger_id(did)}"
            fields["identity"] = {"standing": IDENTITY_STANDING.get(vstatus, "abstained"),
                                  "alternatives": []}
        _reasoned(ev, "player", None, "not_read: unbound: the death owner publishes no slot key")
        killer, kstatus = _named(verdicts, kref, d.get("killer"))
        L.verdicts[kref] = "resolved" if killer else kstatus
        if killer:
            parts = {"killer": {"entity_id": f"{did}:killer",
                                "identity": _name_block(killer, kref, arbiter)}}
        else:
            parts = {"killer": None, "killer_reason": f"withheld: {L.ledger_id(did)}"}
            fields["killer"] = {"standing": IDENTITY_STANDING.get(kstatus, "abstained"),
                                "alternatives": []}
        ev["participants"] = parts
        evidence = [{"stream": "death", "id": did, "version": version}]
        seen = set()
        for w in d.get("witnesses") or []:
            wv = w.get("source_version")
            wevid = w.get("evidence") if isinstance(w.get("evidence"), dict) else {}
            for o in wevid.get("observations") or []:
                key = o.get("observation_key") if isinstance(o, dict) else None
                if key and wv and (w.get("channel"), key) not in seen:
                    seen.add((w.get("channel"), key))
                    evidence.append({"stream": w["channel"], "id": key, "version": wv})
        ev.update(evidence=evidence, producer=producer, lane=L.lane,
                  contract=ENTITY_CONTRACT_VERSION)
        subject = {"row": "event", "event_id": eid, "entity_id": did,
                   "round": d.get("round_no"), "observed_ms": d["t_ms"]}
        status = d.get("status")
        # Rule 1, then rule 4; the death owner's disagreement concerns the
        # victim's name, an optional field, so it withholds the name alone.
        standing, reason = None, None
        if DEATH_STANDING.get(status) == "abstained":
            standing, reason = "abstained", str(d.get("reason") or status)
        elif L.stale_reason(rests_on):
            standing, reason = "stale", L.stale_reason(rests_on)
        if standing is not None:
            L.withhold_row(did, subject, standing, reason, ev, OWNER["death"],
                           [did], [OWNER["death"]], fields)
            continue
        if fields:
            lead = next(iter(fields))
            L.withhold(did, subject, fields[lead]["standing"],
                       "; ".join(filter(None, (
                           f"victim: {d.get('reason')}" if "identity" in fields else None,
                           f"killer: {kstatus}" if "killer" in fields else None,
                           f"weapon: {wev.get('reason') or wev.get('status')}"
                           if "weapon" in fields else None))),
                       fields, [OWNER["arbiter"] if f != "weapon" else OWNER["death"]
                                for f in fields])
            row = L.ledger[L.ledger_id(did)]
            row["returns_to"] = sorted(set(row["returns_to"]))
        L.rows.append(ev)
    return {"arbiter": arbiter}


def _spike_lane(store, sid, L: _Lane, manifest) -> dict:
    rounds = round_rows(store, sid)
    rstamp = (input_stamp(store, sid, "rounds") or "@").split("@")[0]
    sc = store.read_events("spike_carrier", sid)
    scv = (sc[0] if sc else {}).get("spike_carrier_version")
    sc_round = {r["round_no"]: r for r in sc if r.get("kind") == "round"}
    after_plant: dict[int, list[dict]] = {}
    for r in sc:
        if r.get("kind") == "disagreement" and r.get("check") == "carried_after_plant":
            after_plant.setdefault(r.get("round_no"), []).append(r)
    for rr in rounds:
        n = rr["round_no"]
        if not rr.get("spike_planted") or rr.get("plant_t_ms") is None:
            continue
        eid = f"spike:{sid}:R{n}:planted"
        ev = {"row": "event", "event_id": eid}
        _reasoned(ev, "entity_id", None, "not_read: no owner publishes a per-round spike key")
        ev.update(kind="spike", round=n, observed_ms=rr["plant_t_ms"])
        _reasoned(ev, "observed_last_ms", None, "not_applicable: one instant")
        _reasoned(ev, "occurred", None, "not_applicable: observed")
        _reasoned(ev, "position", None, "not_read: rounds stores no plant site")
        _reasoned(ev, "orientation", None, "not_applicable")
        ev["state"] = {"phase": "planted"}
        evidence = [{"stream": "rounds", "id": f"{sid}:round:{n}", "version": rstamp}]
        c = sc_round.get(n)
        if c is not None and scv:
            evidence.append({"stream": "spike_carrier", "id": f"{sid}:round:{n}",
                             "version": scv})
        ev["participants"] = {"planter": None, "planter_reason": (
            "not_read: planter_slot null" if not (c or {}).get("planter_slot") else
            "not_read: the planter is a roster slot (depends_on agent-from-slot), not a verdict")}
        ev.update(evidence=evidence, producer=_producer(OWNER["rounds"], rstamp),
                  lane=L.lane, contract=ENTITY_CONTRACT_VERSION)
        subject = {"row": "event", "event_id": eid, "round": n, "observed_ms": rr["plant_t_ms"]}
        standing, reason, returns, extra = None, None, [], {}
        # Rule 3: the shared key is the round; the plant, and any stored
        # disagreement that names it.
        if c is not None and (c.get("spike_planted"), c.get("plant_t_ms")) != (
                rr.get("spike_planted"), rr.get("plant_t_ms")):
            standing = "disputed"
            reason = (f"round {n}: rounds plants at {rr.get('plant_t_ms')}; spike_carrier "
                      f"stores {c.get('spike_planted')} at {c.get('plant_t_ms')}")
            returns = [OWNER["rounds"], OWNER["spike_carrier"]]
            extra = {"state": {"standing": "disputed", "alternatives": [
                {"value": rr.get("plant_t_ms"), "owner": OWNER["rounds"], "evidence": [eid]},
                {"value": c.get("plant_t_ms"), "owner": OWNER["spike_carrier"],
                 "evidence": [f"spike_carrier:{sid}:round:{n}"]}]}}
        elif after_plant.get(n):
            dis = after_plant[n]
            standing = "disputed"
            reason = (f"spike_carrier carried_after_plant: the carried glyph is read "
                      f"{len(dis)} times after the plant rounds stores at {rr['plant_t_ms']}")
            returns = [OWNER["rounds"], "spike-observation"]
            extra = {"state": {"standing": "disputed", "alternatives": [
                {"value": "planted", "owner": OWNER["rounds"],
                 "evidence": [f"rounds:{sid}:round:{n}"]},
                {"value": "carried", "owner": OWNER["spike_carrier"],
                 "evidence": [{"stream": "spike_carrier", "check": r["check"],
                               "t_ms": r.get("t_ms")} for r in dis]}]}}
        if standing is None:
            why = L.stale_reason(("rounds", "spike_carrier"))
            if why is not None:
                standing, reason, returns = "stale", why, [OWNER["rounds"]]
        if standing is not None:
            L.withhold_row(eid, subject, standing, reason, ev, OWNER["rounds"],
                           [eid], returns, extra)
            continue
        L.rows.append(ev)
    # A carrier loss: the owner stores no spike phase and names the carrier
    # only by roster slot, so the contract has no event for it yet.
    for r in sc:
        if r.get("kind") != "carrier_lost":
            continue
        eid = f"spike:{sid}:carrier_lost:{r['t_ms']}:{r.get('slot')}"
        L.withhold(eid, {"row": "event", "event_id": eid, "observed_ms": r["t_ms"]},
                   "abstained",
                   f"carrier_lost: the owner stores no spike phase (death={r.get('death')}, "
                   f"dropped_glyph_seen={r.get('dropped_glyph_seen')}) and names the carrier "
                   f"by roster slot {r.get('slot')} ({r.get('depends_on')})",
                   {"row": {"standing": "abstained", "alternatives": [
                       {"value": {"t_ms": r["t_ms"], "last_marked_ms": r.get("last_marked_ms"),
                                  "slot": r.get("slot"), "death": r.get("death"),
                                  "dropped_glyph_seen": r.get("dropped_glyph_seen")},
                        "owner": OWNER["spike_carrier"],
                        "evidence": [f"spike_carrier:{sid}:carrier_lost:{r['t_ms']}"]}]}},
                   [OWNER["spike_carrier"]])
    return {}


_BUILD = {"round_entity": _round_entity_lane, "death": _death_lane, "spike": _spike_lane}


# ------------------------------------------------------------- projection

def project_lane(store, session_id: str, lane: str, *, stale: dict | None = None,
                 write: bool = True) -> dict:
    """Project one lane from storage and write its consumer file and ledger.

    `stale` maps an input stream to why it is stale (default: `plan.stale`).
    Returns the lane's summary: rows by kind, ledger rows by standing, the
    estimate debt and the resolution shares. Raises ValueError when a row
    breaks the contract; nothing is written then.
    """
    if lane not in _BUILD:
        raise ValueError(f"lane {lane!r} is not built; stage 1 projects {', '.join(PROJECTED)}")
    manifest = store.read_manifest(session_id)
    inputs = {}
    for s in LANE[lane]["inputs"]:
        stamp = input_stamp(store, session_id, s)
        if stamp is None:
            raise ValueError(f"{lane}: input {s} is not stored for {session_id}")
        inputs[s] = stamp
    stale = stale_inputs(store, session_id) if stale is None else stale
    held = {s: stale[s] for s in LANE[lane]["inputs"] if s in stale}
    L = _Lane(lane, held)
    _BUILD[lane](store, session_id, L, manifest)
    consumer, ledger = lane_streams(lane)
    version = LANE_VERSIONS[lane]
    head = {"row": "stamp", f"{consumer}_version": version,
            "contract": ENTITY_CONTRACT_VERSION, "inputs": inputs}
    lhead = {"row": "stamp", f"{ledger}_version": version,
             "contract": ENTITY_CONTRACT_VERSION, "inputs": inputs}
    crow = [head] + L.rows
    lrows = [lhead] + [L.ledger[k] for k in sorted(L.ledger)]
    errors = (validate_lane(consumer, crow, verdicts=L.verdicts)
              + validate_lane(ledger, lrows))
    if errors:
        msg = "\n".join(f"  row {i}: {e}" for i, e in errors[:10])
        raise ValueError(f"{lane}: {len(errors)} contract errors:\n{msg}")
    if write:
        store.write_events(consumer, session_id, crow)
        store.write_events(ledger, session_id, lrows)
    return lane_summary(lane, L.rows, lrows[1:], L.debt, held)


def lane_summary(lane: str, rows: list[dict], ledger: list[dict], debt: Counter,
              held: dict) -> dict:
    """The `entity_events/resolution` values of one lane."""
    kinds = Counter(r["row"] for r in rows)
    standing = Counter(r["standing"] for r in ledger)
    residual = sum(1 for r in ledger if r.get("residual"))
    consumer = kinds["entity"] + kinds["event"]
    total = consumer + len(ledger)
    return {"lane": lane, "consumer_rows": consumer, "consumer_entities": kinds["entity"],
            "consumer_events": kinds["event"], "coverage_rows": kinds["coverage"],
            "ledger_rows": len(ledger),
            **{f"ledger_{s}": standing[s] for s in sorted(standing)},
            "residual": residual,
            "resolved_share": round(consumer / total, 4) if total else None,
            "debt_share": round((len(ledger) - residual) / total, 4) if total else None,
            "estimate_debt_spans": debt.get("estimate_spans", 0),
            "estimate_debt_s": round(debt.get("estimate_ms", 0) / 1000.0, 1),
            "held_inputs": sorted(held)}


# --------------------------------------------------------------- read API

def _event_time(r: dict) -> float | None:
    if isinstance(r.get("observed_ms"), (int, float)):
        return float(r["observed_ms"])
    occ = r.get("occurred")
    return float(occ["lo_ms"]) if isinstance(occ, dict) else None


class EntityEvents:
    """A session's projected lanes, read-only: the one door a consumer reads
    events through.

    Raises `StaleLanes` when a projected lane's stored inputs moved since it
    was written (`check=False` skips the check). A lane never projected is
    absent, and `missing` says so; the round table is read either way.
    """

    def __init__(self, store, session_id: str, lanes=None, *, check: bool = True):
        self.store, self.session_id = store, session_id
        self.lane_names = tuple(lanes or PROJECTED)
        if check:
            stale = {lane: why for lane in self.lane_names
                     if (why := rebuild_reason(store, session_id, lane)) is not None}
            if stale:
                raise StaleLanes(stale)
        self._rows: dict[str, list[dict]] = {}
        self._ledger: dict[str, list[dict]] = {}
        self._stamps: dict[str, dict] = {}
        self.missing: dict[str, str] = {}
        for lane in self.lane_names:
            consumer, ledger = lane_streams(lane)
            path = store.events_path(consumer, session_id)
            if not path.is_file():
                self.missing[lane] = (f"not projected: run `reticle project {session_id} "
                                      f"--lane {lane}`")
                continue
            rows = store.read_events(consumer, session_id)
            self._stamps[lane] = rows[0]
            self._rows[lane] = rows[1:]
            self._ledger[lane] = store.read_events(ledger, session_id)[1:]
        self._entities = {r["entity_id"]: r for rows in self._rows.values()
                          for r in rows if r["row"] == "entity"}
        self._rounds: list[dict] | None = None

    def stamp(self, lane: str) -> dict | None:
        return self._stamps.get(lane)

    def frame(self) -> dict:
        """Where positions sit: the capture box and whether the widget is a
        variant (`widget_placement`)."""
        return widget_placement(self.store.read_manifest(self.session_id))

    def rounds(self) -> list[dict]:
        """The round table's rows: numbers and bounds, as the owner stored them."""
        if self._rounds is None:
            self._rounds = round_rows(self.store, self.session_id)
        return self._rounds

    def round(self, round_no: int) -> dict | None:
        return next((r for r in self.rounds() if int(r["round_no"]) == int(round_no)), None)

    def entities(self, round=None, family=None, side=None, lane=None) -> list[dict]:
        out = []
        for ln, rows in self._rows.items():
            if lane is not None and ln != lane:
                continue
            out += [r for r in rows if r["row"] == "entity"
                    and (round is None or r.get("round") == round)
                    and (family is None or r.get("family") == family)
                    and (side is None or r.get("side") == side)]
        return out

    def entity(self, entity_id: str) -> dict | None:
        return self._entities.get(entity_id)

    def events(self, round=None, entity_id=None, kinds=None, t0_ms=None, t1_ms=None,
               lane=None) -> list[dict]:
        """Events ordered by time (`observed_ms`, else `occurred.lo_ms`)."""
        out = []
        for ln, rows in self._rows.items():
            if lane is not None and ln != lane:
                continue
            for r in rows:
                if r["row"] != "event":
                    continue
                t = _event_time(r)
                if ((round is None or r.get("round") == round)
                        and (entity_id is None or r.get("entity_id") == entity_id)
                        and (kinds is None or r.get("kind") in kinds)
                        and (t0_ms is None or (t is not None and t >= t0_ms))
                        and (t1_ms is None or (t is not None and t <= t1_ms))):
                    out.append(r)
        return sorted(out, key=lambda r: (_event_time(r) is None, _event_time(r) or 0.0,
                                          r["event_id"]))

    def latest(self, t_ms: float, families=None) -> list[dict]:
        """The last event per entity at or before `t_ms`, with its age in ms.
        Nothing is interpolated."""
        best: dict[str, dict] = {}
        for r in self.events(t1_ms=t_ms):
            eid = r.get("entity_id")
            if eid is None:
                continue
            ent = self._entities.get(eid)
            if families is not None and (ent or {}).get("family") not in families:
                continue
            best[eid] = r
        return [{"event": r, "age_ms": t_ms - _event_time(r)} for r in best.values()]

    def coverage(self, round, lane=None) -> list[dict]:
        return [r for ln, rows in self._rows.items() if lane is None or ln == lane
                for r in rows if r["row"] == "coverage" and r.get("round") == round]

    def ledger(self, lane=None, round=None, t0_ms=None, t1_ms=None) -> list[dict]:
        """Withheld rows, for review tools only (`[consumers] review`)."""
        out = []
        for ln, rows in self._ledger.items():
            if lane is not None and ln != lane:
                continue
            for r in rows:
                s = r.get("subject") or {}
                t = s.get("observed_ms")
                if ((round is None or s.get("round") == round)
                        and (t0_ms is None or t is None or t >= t0_ms)
                        and (t1_ms is None or t is None or t <= t1_ms)):
                    out.append(r)
        return out


def ledger_value(row: dict):
    """The withheld row a ledger row holds whole, or None when it withholds
    fields of a consumer row (its subject then only names that row)."""
    subject = row.get("subject") or {}
    if "producer" in subject:
        return subject
    alts = ((row.get("fields") or {}).get("row") or {}).get("alternatives") or []
    return alts[0].get("value") if alts else None


__all__ = ["ENTITY_LANES", "NAME_ARBITER", "LANE_VERSIONS", "EntityEvents", "StaleLanes",
           "project_lane", "lane_status", "input_stamp", "widget_placement", "round_rows",
           "ledger_value"]
