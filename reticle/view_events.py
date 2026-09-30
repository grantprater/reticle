"""The stored event streams a round viewer draws, loaded and nothing more.

`round_view` draws a round from what the pipeline emitted. This module is its
only door to the store. It turns each stored row into an `Item` -- a time, a
place in one of three drawing spaces (`minimap`, `killfeed`, `panel`), a
label, and the row's own status and reason. It calls no reader, tracker or
adjudicator, and it decides nothing: every value on an `Item` is a stored
field or a join of two stored rows on a stored key. A field the stream lacks
stays None, and the viewer draws that absence rather than filling it.

Three layers read the projected entity lanes through `entity_events`
(`docs/ENTITY_EVENTS.md`, stage 1): round entities, deaths and the spike.
Each lane is two streams: the consumer rows, drawn as usual, and the ledger's
withheld rows, drawn apart in amber with their standing and reason. The round
table comes through `entity_events` too. The other layers still read their
streams' files (`read_rows`) until their lanes exist; `architecture.toml`
dates that exemption.

`STREAMS` declares, per stream, the owner, the row kinds drawn, the time base
and entity key, and where each field the architecture needs sits in the row --
or None where the schema has no such field. `census` measures those fields
over a session's stored rows, and `gap_rows` turns the two into the gap table
`reticle view SESSION --gaps` prints and `docs/EVENT_GAPS.md` explains.

Display holds are not claims. A sampled stream's item stays drawn until its
next sample, for at most `hold_ms`; past that the viewer draws nothing, which
reads as *no stored observation*, never as *absent*.
"""
from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import entity_events as ee

VIEW_EVENTS_VERSION = "view-events-0.2.0"

#: The layers drawn from a projected lane: layer name -> lane.
LANE_LAYERS = {"round_entity": "round_entity", "death": "death", "spike": "spike"}

#: Layer key, layer name, and the streams drawn under it, in key order. A
#: lane layer draws the lane's consumer stream and its ledger.
LAYERS = (
    ("1", "round_entity", ee.lane_streams("round_entity")),
    ("2", "team_vision", ("team_vision",)),
    ("3", "death", ee.lane_streams("death")),
    ("4", "ability", ("ability_state", "ability_shape", "smoke", "smoke_owner_identity",
                      "ult_cast", "ult_cast_identity")),
    ("5", "spike", ee.lane_streams("spike")),
    ("6", "ping", ("ping",)),
    ("7", "killfeed", ("killfeed_name", "killfeed_portrait", "killfeed_weapon")),
)
#: The gap census still measures the owners' own streams under the layer a
#: lane now draws.
LAYER_OF = {**{s: name for _k, name, streams in LAYERS for s in streams},
            "round_entity": "round_entity", "death": "death", "death_identity": "death",
            "spike": "spike", "spike_carrier": "spike"}

#: Item statuses drawn amber: a refusal, an abstention, an unread value, or a
#: ledger standing (a withheld row), never a negative.
NOT_READ = ("refused", "abstained", "unread", "ambiguous", "not_observed", "disputed",
            "stale", "withheld")

#: A lane stream's display hold (ms) for its sampled items: a pose shows
#: until the next, as `round_entity`'s observations did.
LANE_HOLD = {"entity_round_entity": 200.0, "entity_round_entity_ledger": 200.0}

#: The fields a consumer needs from an event, in the architecture's words:
#: time, location, orientation, entity-specific state, identity with its
#: uncertainty, and links to the evidence.
FIELDS = ("event_id", "version", "t_ms", "t_end", "entity_id", "entity_kind", "identity",
          "identity_status", "alternatives", "position", "orientation", "state",
          "uncertainty", "evidence")


@dataclass(frozen=True)
class StreamSpec:
    stream: str
    owner: str               # the ownership.toml entry id
    module: str              # the owning module
    kinds: tuple             # the row kinds drawn (None matches a row with no kind)
    time_base: str
    entity_key: str
    identity: str            # how the stream names an agent, if it does
    fields: dict             # FIELDS name -> stored key path, or None if absent
    hold_ms: float = 0.0     # display hold for a sampled stream; 0 = interval rows
    notes: str = ""


def _f(**kw):
    out = {k: None for k in FIELDS}
    out.update(kw)
    return out


#: Key paths: `a.b` descends a dict, `a[].b` any element of a list, `a|b` both
#: keys must be present (a position is x and y), `a/b` either one will do (a
#: stream whose row kinds name the same field differently).
STREAMS = {s.stream: s for s in (
    StreamSpec(
        "round_entity", "round-entity-session", "round_entities", ("observation",),
        "capture ms of the stored ally_icon frame (15 Hz roi cache)",
        "entity_id `<sid>:R<n>:E<k>/P<j>`, round-scoped; entity rows join on `id`",
        "observation `name` is a placeholder (`ally 3`, `you`); the agent sits on the "
        "entity row (`agent`, `teammate_key`), joined here by entity_id",
        _f(event_id="observation_id", version="round_entity_version", t_ms="t_ms",
           entity_id="entity_id", entity_kind="family", identity="name",
           identity_status="identity_status", alternatives="alternatives",
           position="x|y", state="state", evidence="observation_key"),
        hold_ms=200.0,
        notes="no facing, no radius, no position uncertainty; `state` is association "
              "state (continuation, refit), not game state (alive, dead); self, ally and "
              "barrier only"),
    StreamSpec(
        "team_vision", "team-vision", "team_vision", ("frame",),
        "capture ms of the roi-cache minimap frame (15 Hz)",
        "per-icon `track_id`, a tracker association id in its own key space; no link "
        "to round_entity's entity_id",
        "none: icons carry a role (self, ally) and no agent",
        _f(version="team_vision_version", t_ms="t_ms", entity_kind="icons[].role", position="icons[].x|icons[].y",
           orientation="icons[].facing", state="icons[].eligible",
           evidence="frame_idx"),
        hold_ms=200.0,
        notes="cones stored only as the frame's union mask (`observable`); no per-icon "
              "cone, no event id, no facing uncertainty"),
    StreamSpec(
        "death", "death-victim", "adjudication.death", ("death_verdict",),
        "capture ms of the killfeed entry's first sample (2 Hz)",
        "`death_id` `death:<sid>:<t>:<slot>`; victim and killer are agent names with "
        "no minimap entity id",
        "victim/killer by name; the arbiter's distribution is in death_identity",
        _f(event_id="death_id", version="death_adjudication_version", t_ms="t_ms",
           entity_id="death_id", entity_kind="side", identity="victim",
           identity_status="status", alternatives="witnesses", position="location",
           state="death_cause", evidence="witnesses"),
        hold_ms=6000.0,
        notes="`location` and `killer_location` are null on every row"),
    StreamSpec(
        "death_identity", "agent-identity", "adjudication.identity",
        ("identity_distribution",),
        "the death's t_ms",
        "`subject_entity_id` = the death's death_id",
        "a distribution over agents per death",
        _f(event_id="event_id", version="producer_version", t_ms="t_ms",
           entity_id="identity_distribution.subject_entity_id", entity_kind="event_kind",
           identity="identity_distribution.distribution", alternatives="alternatives",
           position="position", orientation="orientation", state="state",
           uncertainty="identity_distribution.distribution", evidence="evidence_refs"),
        hold_ms=6000.0,
        notes="the formal event contract; position, orientation and evidence_refs empty"),
    StreamSpec(
        "ability_state", "ability-state", "adjudication.ability_state", ("state", "verdict"),
        "state rows are intervals `t_first_ms..t_last_ms` over tray samples (2 Hz); "
        "verdicts at `t_ms`",
        "slot letter plus `agent_entity_id` `<sid>:ally:slot:0` (a third key space)",
        "the player's agent only",
        _f(version="ability_state_version", t_ms="t_first_ms/t_ms", t_end="t_last_ms",
           entity_id="agent_entity_id", entity_kind="slot", identity="agent",
           state="mode/transition", uncertainty="charges_range", evidence="claims"),
        notes="the player's own kit only; no ability entity, position or owner for "
              "teammates or enemies; state and verdict rows carry no event id"),
    StreamSpec(
        "ability_shape", "ability-shape", "ability_shapes", ("shape",),
        "the player's cast time",
        "none; keyed by cast_t_ms and slot",
        "the player's agent only",
        _f(version="ability_shape_version", t_ms="t_ms", identity="agent",
           entity_kind="ability", position="cx|cy", state="found", uncertainty="score"),
        hold_ms=2500.0,
        notes="one fit per player cast; no lifetime, no end"),
    StreamSpec(
        "smoke", "minimap-smoke", "adjudication.smokes", ("track",),
        "track interval `first_ms..last_ms`",
        "`track` index; the owner stream builds `<sid>:smoke:<first_ms>:<track>` itself",
        "owner in smoke_owner_identity",
        _f(version="smoke_version", t_ms="first_ms", t_end="last_ms", entity_id="track",
           position="cx|cy", state="end_status", uncertainty="r"),
        notes="one position per track; the row carries no entity_id string"),
    StreamSpec(
        "smoke_owner_identity", "agent-identity", "adjudication.identity",
        ("identity_distribution",),
        "the smoke's first_ms",
        "`subject_entity_id` `<sid>:smoke:<first_ms>:<track>`",
        "distribution over agents",
        _f(event_id="event_id", version="producer_version", t_ms="t_ms",
           entity_id="identity_distribution.subject_entity_id",
           identity="identity_distribution.distribution", position="position",
           orientation="orientation", uncertainty="identity_distribution.distribution",
           evidence="evidence_refs")),
    StreamSpec(
        "ult_cast", "ult-cast", "adjudication.ult_cast", ("cast", "missed_line"),
        "the voice line's audio peak (ms)",
        "`entity_id` `<sid>:ult_cast:<t>:<template>`",
        "agent and side from the voice line; distribution in ult_cast_identity",
        _f(event_id="entity_id", version="ult_cast_version", t_ms="t_ms",
           entity_id="entity_id", entity_kind="side", identity="agent",
           identity_status="identity_status", state="class", uncertainty="score"),
        hold_ms=4000.0,
        notes="audio only: no position, no caster entity on the minimap"),
    StreamSpec(
        "ult_cast_identity", "agent-identity", "adjudication.identity",
        ("identity_distribution",),
        "the cast's t_ms", "`subject_entity_id` = the cast's entity_id",
        "distribution over agents",
        _f(event_id="event_id", version="producer_version", t_ms="t_ms",
           entity_id="identity_distribution.subject_entity_id",
           identity="identity_distribution.distribution", position="position",
           orientation="orientation", uncertainty="identity_distribution.distribution",
           evidence="evidence_refs"),
        hold_ms=4000.0),
    StreamSpec(
        "spike", "spike-observation", "spike", ("frame",),
        "capture ms of the 1 Hz grid",
        "none; the carrier is a roster `marker.slot`",
        "none",
        _f(version="spike_version", t_ms="t_ms", entity_kind="glyphs[].state",
           position="glyphs[].cx|glyphs[].cy", state="glyphs[].state",
           uncertainty="glyphs[].ncc", evidence="frame_idx"),
        hold_ms=1100.0,
        notes="the spike has no entity id; a planted spike's position is not stored"),
    StreamSpec(
        "spike_carrier", "spike-carrier", "adjudication.spike_carrier",
        ("round", "carrier_lost", "disagreement"),
        "carrier_lost and disagreement at t_ms; round rows per round",
        "roster `slot`, marked `depends_on: agent-from-slot`",
        "none: a slot, not an agent",
        _f(version="spike_carrier_version", t_ms="t_ms", state="kind/check", evidence="depends_on"),
        hold_ms=3000.0,
        notes="no carrier entity id or agent; no spike position"),
    StreamSpec(
        "ping", "ping-event", "ping", (None, "standard", "danger", "on_my_way", "need_help"),
        "the ping's first sighting (ms), shown for `lifetime_s`",
        "none", "none: who pinged is not stored",
        _f(version="ping_version", t_ms="t_ms", t_end="lifetime_s", entity_kind="kind",
           position="x|y", orientation="drivers.bearing"),
        notes="no event id and no owner"),
    StreamSpec(
        "killfeed_name", "killfeed-name-descriptor", "killfeed", ("name_observation",),
        "capture ms of the 2 Hz roi cache", "`observation_key` `<sid>:<frame>:<slot>:<role>`",
        "none: a descriptor; names come from adjudication.killfeed_names",
        _f(event_id="observation_key", version="killfeed_name_version", t_ms="t_ms",
           entity_kind="role", position="y0|y1", state="me", evidence="observation_key"),
        hold_ms=600.0, notes="a per-sample observation; no entry id binds it to its death"),
    StreamSpec(
        "killfeed_portrait", "killfeed-portrait", "killfeed", ("portrait_observation",),
        "capture ms of the 2 Hz roi cache", "`observation_key`",
        "none: a composition vector; the agent is named in death witnesses",
        _f(event_id="observation_key", version="killfeed_portrait_version", t_ms="t_ms",
           entity_kind="role", position="x0|y0", state="ally", uncertainty="art_fraction",
           evidence="observation_key"),
        hold_ms=600.0, notes="a per-sample observation; no entry id binds it to its death"),
    StreamSpec(
        "killfeed_weapon", "killfeed-weapon-descriptor", "killfeed",
        ("weapon_icon_observation",),
        "capture ms of the 2 Hz roi cache", "none: frame_idx and slot",
        "none",
        _f(version="killfeed_weapon_version", t_ms="t_ms", position="wx0|y0",
           state="verdict", evidence="frame_idx"),
        hold_ms=600.0, notes="no observation key and no entry id"),
)}

#: What no stored stream carries at all. The architecture needs each of them.
MISSING_STREAMS = (
    ("enemy icons", "ally-candidates (minimap)",
     "no stream stores an enemy icon's position, facing or name; `round_entity` covers "
     "self, ally and barrier"),
    ("per-icon cones", "team-vision",
     "team_vision stores the union mask only; a consumer cannot say whose cone saw what"),
    ("teammate and enemy abilities", "ability-detection / ability-owner",
     "ability_state is the player's tray; `ability-owner` is unowned"),
    ("round_entity <-> team_vision link", "round-entity-session / team-vision",
     "the entity id and the track id live in separate key spaces; facing and identity "
     "never meet on one row"),
    ("death position", "death-victim",
     "`location` and `killer_location` are declared and null"),
    ("killfeed entry", "killfeed-event",
     "the per-frame kill/death verdict lives in the L1 hud table, not in an event stream"),
)

_T_RE = re.compile(rb'"t_ms":(-?[0-9.eE+]+)')


@dataclass
class Item:
    """One drawable thing, straight from one stored row."""

    layer: str
    stream: str
    row_kind: str | None
    t_ms: float
    t_end_ms: float
    space: str                      # minimap | killfeed | panel
    label: str
    status: str = "ok"              # ok | uncertain | abstained | refused | unread
    reason: str | None = None
    x: float | None = None
    y: float | None = None
    r: float | None = None
    facing: float | None = None
    box: tuple | None = None        # (x0, y0, x1, y1) in its space
    event_id: str | None = None
    id_source: str = "stored"       # stored | line (the row has no id)
    version: str | None = None
    entity_id: str | None = None
    colour: str = "ink"
    mask: dict | None = None        # a packed mask (team_vision observable)
    detail: dict = field(default_factory=dict)


def unpack_mask(packed: dict):
    """A mask stored by `lighting.pack_mask`, as a boolean array.

    A storage format, restated so the viewer imports no reader; the test pins
    it to `lighting.unpack_mask`."""
    import base64
    import zlib

    import numpy as np

    shape = tuple(packed["shape"])
    bits = np.frombuffer(zlib.decompress(base64.b64decode(packed["bits"])), np.uint8)
    return np.unpackbits(bits)[:shape[0] * shape[1]].reshape(shape).astype(bool)


# ------------------------------------------------------------------ reading

def read_rows(store, stream: str, session_id: str, window=None):
    """`(line_no, row)` pairs of one stream, optionally inside `window` (ms).

    A row with a `t_ms` outside the window is skipped before it is parsed;
    rows without one are kept for the converter to place. Association rows
    are skipped: they are hypotheses over observations, and the largest rows
    in the store."""
    path = store.events_path(stream, session_id)
    if not path.is_file():
        return None
    out = []
    with open(path, "rb") as f:
        for no, ln in enumerate(f, 1):
            if not ln.strip():
                continue
            head = ln[:400]
            if b'"kind":"associations"' in head:
                continue
            if window is not None:
                m = _T_RE.search(ln)
                if m:
                    t = float(m.group(1))
                    if t < window[0] or t > window[1]:
                        continue
            out.append((no, json.loads(ln)))
    return out


def session_rounds(store, manifest: dict) -> list[dict]:
    """The session's stored rounds, as dicts, or [] when none are stored."""
    return ee.round_rows(store, manifest["session_id"])


def lane_streams_of(layer: str) -> tuple[str, str]:
    """A lane layer's consumer stream and ledger stream."""
    return ee.lane_streams(LANE_LAYERS[layer])


#: Where the widget sits in the capture, re-exported for the drawing.
widget_placement = ee.widget_placement


def round_window(store, manifest: dict, round_no: int) -> tuple[float, float, dict]:
    """A round's stored window: its start to the next round's buy snap."""
    for r in session_rounds(store, manifest):
        if int(r["round_no"]) == int(round_no):
            end = r.get("t_close_ms") or r.get("t_end_ms")
            return float(r["t_start_ms"]), float(end), r
    raise SystemExit(f"round {round_no} is not in the stored rounds of "
                     f"{manifest['session_id']}")


def _version(row: dict, stream: str) -> str | None:
    for k in (f"{stream}_version", "producer_version"):
        if row.get(k):
            return row[k]
    for k, v in row.items():
        if k.endswith("_version") and isinstance(v, str):
            return v
    return None


def _kind(row):
    return row.get("kind") or row.get("event_kind")


def _hms(ms: float) -> str:
    s = max(0.0, ms) / 1000.0
    return f"{int(s // 60)}:{s % 60:04.1f}"


def _dist_text(d: dict | None) -> str:
    if not d:
        return "no distribution"
    top = sorted(d.items(), key=lambda kv: -kv[1])[:3]
    return " ".join(f"{a} {p:.2f}" for a, p in top)


# --------------------------------------------------------- stream -> items

def _team_vision(rows, t0, t1):
    out = []
    for no, r in rows:
        if r.get("kind") != "frame" or not (t0 <= r["t_ms"] <= t1):
            continue
        ver = r.get("team_vision_version")
        if r.get("widget") != "drawn":
            out.append(Item("team_vision", "team_vision", "frame", r["t_ms"], r["t_ms"],
                            "panel", f"vision: widget {r.get('widget')}", "unread",
                            r.get("reason"), event_id=f"team_vision@{no}", id_source="line",
                            version=ver))
            continue
        out.append(Item("team_vision", "team_vision", "frame", r["t_ms"], r["t_ms"],
                        "minimap", "observable", mask=r.get("observable"),
                        event_id=f"team_vision@{no}", id_source="line", version=ver,
                        colour="cone", detail={"observable_px": r.get("observable_px"),
                                               "widget_px": r.get("widget_px")}))
        for ic in r.get("icons") or []:
            facing = ic.get("facing")
            status, reason = "ok", None
            if facing is None:
                status, reason = "unread", "facing not read: casts no cone"
            elif not ic.get("eligible"):
                status, reason = "uncertain", "not eligible: cone left out of observable"
            out.append(Item(
                "team_vision", "team_vision", "frame.icon", r["t_ms"], r["t_ms"], "minimap",
                f"{ic.get('role', '?')[0].upper()}{ic.get('track_id')}", status, reason,
                x=ic.get("x"), y=ic.get("y"), facing=facing,
                event_id=f"team_vision@{no}", id_source="line", version=ver,
                entity_id=f"track:{ic.get('track_id')}",
                colour="self" if ic.get("role") == "self" else "ally",
                detail={"casts": ic.get("casts"), "eligible": ic.get("eligible"),
                        "self_cone": ic.get("self_cone")}))
    return out


def _ability_state(rows, t0, t1):
    out = []
    for no, r in rows:
        k = r.get("kind")
        ver = r.get("ability_state_version")
        if k == "state":
            a, z = r.get("t_first_ms"), r.get("t_last_ms")
            if a is None or z is None or z < t0 or a > t1:
                continue
            mode = r.get("mode")
            ch = r.get("charges")
            chs = (f"{ch}" if ch is not None else
                   f"{r.get('charges_range')}" if r.get("charges_range") else "?")
            status = "unread" if mode == "unreadable" else "ok"
            out.append(Item(
                "ability", "ability_state", "state", a, z + 500.0, "panel",
                f"{r.get('slot')} {r.get('ability')} {mode} lvl {r.get('level')} "
                f"charges {chs}", status,
                r.get("unreadable_reason") if status != "ok" else None,
                event_id=f"ability_state@{no}", id_source="line", version=ver,
                entity_id=r.get("agent_entity_id"), colour="ability",
                detail={"phase": r.get("phase"), "agent": r.get("agent")}))
        elif k == "verdict":
            t = r.get("t_ms")
            if t is None or not (t0 - 3000 <= t <= t1) or r.get("transition") == "none":
                continue
            tr = r.get("transition")
            status = "refused" if tr == "unresolved" else "ok"
            out.append(Item(
                "ability", "ability_state", "verdict", t, t + 3000.0, "panel",
                f"{_hms(t)} {r.get('slot')} {tr}  agreed {','.join(r.get('agreed') or [])}",
                status, r.get("reason") or (r.get("stood_for") if status != "ok" else None),
                event_id=f"ability_state@{no}", id_source="line", version=ver,
                colour="ability", detail={"disagreed": r.get("disagreed")}))
    return out


def _ability_shape(rows, t0, t1):
    out = []
    for no, r in rows or []:
        if r.get("kind") != "shape" or not (t0 - 2500 <= r.get("t_ms", -1) <= t1):
            continue
        found = r.get("found")
        out.append(Item(
            "ability", "ability_shape", "shape", r["t_ms"], r["t_ms"] + 2500.0, "minimap",
            f"{r.get('ability')} {r.get('shape')}", "ok" if found else "refused",
            None if found else r.get("reason"), x=r.get("cx"), y=r.get("cy"), r=r.get("r"),
            event_id=f"ability_shape@{no}", id_source="line",
            version=r.get("ability_shape_version"), colour="ability"))
    return out


def _smoke(rows, owners, sid, t0, t1):
    own = {}
    for _n, r in owners or []:
        d = r.get("identity_distribution") or {}
        own[d.get("subject_entity_id")] = r
    out = []
    for no, r in rows or []:
        if r.get("kind") != "track":
            continue
        a, z = r.get("first_ms"), r.get("last_ms")
        if a is None or z is None or z < t0 or a > t1:
            continue
        key = f"{sid}:smoke:{int(a)}:{r.get('track')}"
        o = own.get(key)
        who = _dist_text((o or {}).get("identity_distribution", {}).get("distribution")) \
            if o else "no owner event"
        out.append(Item(
            "ability", "smoke", "track", a, z, "minimap", f"smoke {r.get('track')}: {who}",
            "ok" if o else "uncertain", None if o else "no smoke_owner_identity row",
            x=r.get("cx"), y=r.get("cy"), r=r.get("r"), event_id=key, id_source="line",
            version=r.get("smoke_version"), entity_id=key, colour="smoke",
            detail={"onset": r.get("onset_status"), "end": r.get("end_status"),
                    "owner_event": (o or {}).get("event_id")}))
    return out


def _ult(rows, ident, t0, t1):
    dist = {}
    for _n, r in ident or []:
        d = r.get("identity_distribution") or {}
        dist[d.get("subject_entity_id")] = r
    out = []
    for no, r in rows or []:
        k = r.get("kind")
        t = r.get("t_ms")
        if k not in ("cast", "missed_line") or t is None or not (t0 - 4000 <= t <= t1):
            continue
        if k == "cast":
            idr = dist.get(r.get("entity_id"))
            st = r.get("identity_status")
            out.append(Item(
                "ability", "ult_cast", "cast", t, t + 4000.0, "panel",
                f"{_hms(t)} ULT {r.get('agent')} ({r.get('side')}) class {r.get('class')}"
                f"  id: {_dist_text((idr or {}).get('identity_distribution', {}).get('distribution'))}",
                "ok" if st == "resolved" else "refused",
                None if st == "resolved" else r.get("identity_reason") or st,
                event_id=r.get("entity_id"), version=r.get("ult_cast_version"),
                entity_id=r.get("entity_id"), colour="ability"))
        else:
            out.append(Item(
                "ability", "ult_cast", "missed_line", t, t + 4000.0, "panel",
                f"{_hms(t)} ULT line missed ({r.get('template')})", "refused",
                r.get("best_peak_reason"), event_id=f"ult_cast@{no}", id_source="line",
                version=r.get("ult_cast_version")))
    return out


def _ping(rows, t0, t1):
    out = []
    for no, r in rows or []:
        t = r.get("t_ms")
        life = r.get("lifetime_s")
        if t is None:
            continue
        z = t + 1000.0 * (life if life is not None else 0.0)
        if z < t0 or t > t1:
            continue
        out.append(Item(
            "ping", "ping", r.get("kind"), float(t), z, "minimap",
            f"ping {r.get('kind')}", "ok" if life is not None else "unread",
            None if life is not None else "no lifetime stored",
            x=r.get("x"), y=r.get("y"), event_id=f"ping@{no}", id_source="line",
            version=r.get("ping_version"), colour="ping",
            detail={"lifetime_s": life}))
    return out


def _killfeed(stream, rows, t0, t1):
    out = []
    for no, r in rows or []:
        k = r.get("kind")
        if k in ("coverage", None) or not (t0 <= r.get("t_ms", -1) <= t1):
            continue
        ver = _version(r, stream)
        reason = r.get("reason") or None
        common = dict(event_id=r.get("observation_key") or f"{stream}@{no}",
                      id_source="stored" if r.get("observation_key") else "line",
                      version=ver)
        if stream == "killfeed_portrait" and k == "portrait_observation":
            box = (r.get("x0"), r.get("y0"), r.get("x1"), r.get("y1"))
            out.append(Item("killfeed", stream, k, r["t_ms"], r["t_ms"], "killfeed",
                            f"{r.get('role')[0].upper()}{r.get('slot')}"
                            + (" ally" if r.get("ally") else ""),
                            "refused" if reason else "ok", reason, box=box,
                            colour="ally" if r.get("ally") else "ink", **common))
        elif stream == "killfeed_name" and k == "name_observation":
            out.append(Item("killfeed", stream, k, r["t_ms"], r["t_ms"], "killfeed",
                            f"name {r.get('role')} s{r.get('slot')}"
                            + (" ME" if r.get("me") else ""),
                            "refused" if reason else "ok", reason,
                            box=(None, r.get("y0"), None, r.get("y1")),
                            colour="self" if r.get("me") else "ink", **common))
        elif stream == "killfeed_weapon" and k == "weapon_icon_observation":
            v = r.get("verdict")
            out.append(Item("killfeed", stream, k, r["t_ms"], r["t_ms"], "killfeed",
                            f"s{r.get('slot')} {v}", "refused" if reason else "ok", reason,
                            box=(r.get("wx0"), r.get("y0"), r.get("wx1"), r.get("y1")),
                            colour={"kill": "kill", "death": "death"}.get(v, "ink"),
                            **common))
    return out


# ------------------------------------------------------------ lanes -> items

def _agent(identity) -> str | None:
    return identity.get("agent") if isinstance(identity, dict) else None


def _withheld_by(ledger: dict, row: dict, field_name: str):
    """The ledger row a consumer row's `withheld: <id>` reason points at."""
    why = row.get(f"{field_name}_reason") or ""
    return ledger.get(why[len("withheld: "):]) if why.startswith("withheld: ") else None


def _alternatives(lrow: dict | None) -> list[str]:
    alts = (((lrow or {}).get("fields") or {}).get("identity") or {}).get("alternatives") or []
    return [str(a.get("value")) for a in alts]


def _lane_version(ev, lane: str) -> str | None:
    stamp = ev.stamp(lane) or {}
    return stamp.get(f"{ee.lane_streams(lane)[0]}_version")


def _lane_round_entity(ev, t0, t1):
    """Poses of the round's entities: consumer rows drawn as tracks, ledger
    rows (whole withheld entities and refused poses) drawn apart in amber."""
    consumer, ledger_stream = ee.lane_streams("round_entity")
    version = _lane_version(ev, "round_entity")
    ledger = {r["ledger_id"]: r for r in ev.ledger(lane="round_entity")}
    held_ent = {}                     # entity_id -> (projected entity row, ledger row)
    for r in ledger.values():
        v = ee.ledger_value(r)
        if isinstance(v, dict) and v.get("row") == "entity":
            held_ent[v["entity_id"]] = (v, r)

    def item(stream, pose, ent, status, reason, lrow):
        pos = pose.get("position") or {}
        agent = _agent((ent or {}).get("identity"))
        kind = (ent or {}).get("kind")
        label = agent or {"self": "you", "ally": "ally", "barrier": "barrier"}.get(
            kind, "unassigned")
        return Item(
            "round_entity", stream, "pose", pose["observed_ms"], pose["observed_ms"],
            "minimap", label, status, reason, x=pos.get("x"), y=pos.get("y"),
            r=pos.get("r"), event_id=pose["event_id"], version=version,
            entity_id=pose.get("entity_id"),
            colour={"self": "self", "ally": "ally"}.get(kind, "barrier"),
            detail={"family": kind, "identity_status": status,
                    "alternatives": _alternatives(lrow),
                    "ledger_id": (lrow or {}).get("ledger_id"),
                    "position_reason": pose.get("position_reason")})

    out = []
    for pose in ev.events(lane="round_entity", kinds=("pose",), t0_ms=t0, t1_ms=t1):
        ent = ev.entity(pose["entity_id"]) or {}
        lrow = _withheld_by(ledger, ent, "identity")
        status = "ok" if lrow is None else lrow["standing"]
        out.append(item(consumer, pose, ent, status,
                        None if lrow is None else lrow["reason"], lrow))
    for r in ev.ledger(lane="round_entity", t0_ms=t0, t1_ms=t1):
        v = ee.ledger_value(r)
        if not (isinstance(v, dict) and v.get("row") == "event" and v.get("kind") == "pose"):
            continue
        if not (t0 <= v["observed_ms"] <= t1):
            continue
        ent, erow = held_ent.get(v.get("entity_id"), (None, None))
        reason = (erow or r)["reason"]
        out.append(item(ledger_stream, v, ent, r["standing"], reason, erow or r))
    return out


def _death_label(d: dict) -> str:
    killer = ((d.get("participants") or {}).get("killer") or {}).get("identity")
    weapon = (d.get("state") or {}).get("weapon")
    return (f"{_hms(d['observed_ms'])} {_agent(killer) or 'killer?'} [{weapon or '?'}] > "
            f"{_agent(d.get('identity')) or 'victim?'}")


def _lane_death(ev, t0, t1):
    """Deaths: consumer events in the panel; a death with a withheld field
    carries its ledger row's standing and reason, and a death withheld whole
    is drawn from the ledger."""
    consumer, ledger_stream = ee.lane_streams("death")
    version = _lane_version(ev, "death")
    hold = STREAMS["death"].hold_ms
    ledger = {r["ledger_id"]: r for r in ev.ledger(lane="death")}
    out = []
    for d in ev.events(lane="death", kinds=("death",), t0_ms=t0 - hold, t1_ms=t1):
        lrow = ledger.get(f"death:{d['entity_id']}")
        status = "ok" if lrow is None else lrow["standing"]
        ident = d.get("identity")
        idtxt = (f"victim {_agent(ident)} by {ident.get('arbiter')}" if ident
                 else d.get("identity_reason") or "")
        out.append(Item(
            "death", consumer, "death", d["observed_ms"], d["observed_ms"] + hold, "panel",
            _death_label(d), status,
            None if lrow is None else f"{', '.join(sorted(lrow['fields']))}: {lrow['reason']}",
            event_id=d["event_id"], version=version, entity_id=d.get("entity_id"),
            detail={"identity": idtxt, "ledger_id": (lrow or {}).get("ledger_id")}))
    for r in ledger.values():
        v = ee.ledger_value(r)
        if not (isinstance(v, dict) and v.get("kind") == "death"):
            continue
        if not (t0 - hold <= v["observed_ms"] <= t1):
            continue
        out.append(Item(
            "death", ledger_stream, "death", v["observed_ms"], v["observed_ms"] + hold,
            "panel", _death_label(v), r["standing"], r["reason"], event_id=v["event_id"],
            version=version, entity_id=v.get("entity_id"),
            detail={"identity": f"withheld whole: {r['standing']}",
                    "ledger_id": r["ledger_id"]}))
    return out


def _lane_spike(ev, t0, t1):
    """Plants from the round table, and the ledger's disputed plants and
    carrier losses, in the panel."""
    consumer, ledger_stream = ee.lane_streams("spike")
    version = _lane_version(ev, "spike")
    out = []
    for s in ev.events(lane="spike", kinds=("spike",), t0_ms=t0 - 3000, t1_ms=t1):
        out.append(Item("spike", consumer, "spike", s["observed_ms"], max(t1, s["observed_ms"]),
                        "panel", f"R{s.get('round')} spike planted at {_hms(s['observed_ms'])}",
                        event_id=s["event_id"], version=version, colour="spike",
                        detail={"planter_reason":
                                (s.get("participants") or {}).get("planter_reason")}))
    for r in ev.ledger(lane="spike", t0_ms=t0 - 3000, t1_ms=t1):
        v = ee.ledger_value(r)
        if not isinstance(v, dict):
            continue
        if v.get("kind") == "spike":
            t, label, end = v["observed_ms"], (f"R{v.get('round')} spike planted at "
                                               f"{_hms(v['observed_ms'])}"), None
        elif "t_ms" in v:
            t, label, end = v["t_ms"], (f"{_hms(v['t_ms'])} carrier lost: slot "
                                        f"{v.get('slot')} death {v.get('death')}"), 3000.0
        else:
            continue
        if not (t0 - 3000 <= t <= t1):
            continue
        out.append(Item("spike", ledger_stream, v.get("kind") or "carrier_lost", t,
                        t + end if end else max(t1, t), "panel", label, r["standing"],
                        r["reason"], event_id=r["ledger_id"], version=version,
                        colour="spike", detail={"ledger_id": r["ledger_id"]}))
    return out


_LANE_ITEMS = {"round_entity": _lane_round_entity, "death": _lane_death, "spike": _lane_spike}


def load_lanes(store, session_id: str, t0: float, t1: float):
    """The lane layers' items, presence and versions, read through
    `EntityEvents`. A stale lane is still drawn, and its presence says it is
    stale and how to rebuild it."""
    try:
        ev = ee.EntityEvents(store, session_id)
        stale = {}
    except ee.StaleLanes as e:
        ev = ee.EntityEvents(store, session_id, check=False)
        stale = e.lanes
    items, presence, versions = {}, {}, {}
    for lane, build in _LANE_ITEMS.items():
        streams = ee.lane_streams(lane)
        if lane in ev.missing:
            for s in streams:
                items[s], presence[s] = [], ev.missing[lane]
            continue
        got = build(ev, t0, t1)
        for s in streams:
            items[s] = [it for it in got if it.stream == s]
            presence[s] = (f"{len(items[s])} items in window"
                           + (f"; STALE ({stale[lane]}): `reticle project {session_id} "
                              f"--lane {lane}`" if lane in stale else ""))
            versions[s] = _lane_version(ev, lane) or ""
    return items, presence, versions


# ---------------------------------------------------------------- the view

@dataclass
class Loaded:
    """Every item of a window, with each sampled stream's sample times."""

    session_id: str
    t0: float
    t1: float
    items: dict            # stream -> list[Item], sorted by t_ms
    presence: dict         # stream -> "loaded N rows" | "no stream for this session"
    versions: dict         # stream -> version stamp of its first drawn row
    round: dict | None = None
    _sampled: dict = field(default_factory=dict)
    _times: dict = field(default_factory=dict)
    _spans: dict = field(default_factory=dict)

    def __post_init__(self):
        for s, items in self.items.items():
            items.sort(key=lambda it: it.t_ms)
            self._sampled[s] = [it for it in items if it.t_end_ms == it.t_ms]
            self._times[s] = [it.t_ms for it in self._sampled[s]]
            self._spans[s] = [it for it in items if it.t_end_ms != it.t_ms]

    def active(self, stream: str, t: float) -> list[Item]:
        """The stream's items drawn at `t`.

        An instantaneous item (a sample) shows while it is the stream's latest
        sample at or before `t` and no older than the stream's `hold_ms`; an
        interval item shows while `t_ms <= t <= t_end_ms`."""
        out = [it for it in self._spans.get(stream, ()) if it.t_ms <= t <= it.t_end_ms]
        times = self._times.get(stream) or []
        i = bisect.bisect_right(times, t)
        hold = STREAMS[stream].hold_ms if stream in STREAMS else LANE_HOLD.get(stream, 0.0)
        if i and t - times[i - 1] <= hold:
            j = bisect.bisect_left(times, times[i - 1])
            out.extend(self._sampled[stream][j:i])
        return out

    def layer_items(self, layer: str) -> list[Item]:
        streams = next(s for _k, n, s in LAYERS if n == layer)
        return [it for s in streams for it in self.items.get(s, [])]


#: The streams still read from their own files: every layer without a lane.
FILE_STREAMS = tuple(s for s in STREAMS if LAYER_OF[s] not in LANE_LAYERS)


def load(store, manifest: dict, t0: float, t1: float, round_row: dict | None = None,
         pad_ms: float = 8000.0) -> Loaded:
    """Every drawable item of every layer between `t0` and `t1` (ms)."""
    sid = manifest["session_id"]
    win = (t0 - pad_ms, t1 + pad_ms)
    raw = {s: read_rows(store, s, sid, win) for s in FILE_STREAMS}
    a, z = win
    items = {
        "team_vision": _team_vision(raw["team_vision"] or [], a, z),
        "ability_state": _ability_state(raw["ability_state"] or [], a, z),
        "ability_shape": _ability_shape(raw["ability_shape"], a, z),
        "smoke": _smoke(raw["smoke"], raw["smoke_owner_identity"], sid, a, z),
        "smoke_owner_identity": [],
        "ult_cast": _ult(raw["ult_cast"], raw["ult_cast_identity"], a, z),
        "ult_cast_identity": [],
        "ping": _ping(raw["ping"], a, z),
        "killfeed_name": _killfeed("killfeed_name", raw["killfeed_name"], a, z),
        "killfeed_portrait": _killfeed("killfeed_portrait", raw["killfeed_portrait"], a, z),
        "killfeed_weapon": _killfeed("killfeed_weapon", raw["killfeed_weapon"], a, z),
    }
    presence, versions = {}, {}
    for s, rows in raw.items():
        presence[s] = ("no stream for this session" if rows is None
                       else f"{len(rows)} rows in window")
        if rows:   # one stream may hold rows from several producers
            versions[s] = ", ".join(sorted({_version(r, s) for _n, r in rows} - {None}))
    lane_items, lane_presence, lane_versions = load_lanes(store, sid, a, z)
    items.update(lane_items)
    presence.update(lane_presence)
    versions.update(lane_versions)
    return Loaded(sid, t0, t1, items, presence, versions, round_row)


def nearest_event(loaded: Loaded, layer: str, t: float, point=None, to_frame=None) -> dict | None:
    """The layer's stored event nearest a mark, for the mark row to cite.

    With `point` (frame pixels) and `to_frame` (an item's frame position or
    None), the item drawn at `t` nearest the point wins: a click points at
    what is on screen. Otherwise, or when nothing drawn has a position, the
    item nearest in time wins, where an interval containing `t` is at zero."""
    def dt_of(it):
        return 0.0 if it.t_ms <= t <= it.t_end_ms else min(abs(it.t_ms - t),
                                                           abs(it.t_end_ms - t))

    best = None
    if point is not None and to_frame is not None:
        streams = next(s for _k, n, s in LAYERS if n == layer)
        for it in (it for s in streams for it in loaded.active(s, t)):
            q = to_frame(it)
            if q is None:
                continue
            d = ((q[0] - point[0]) ** 2 + (q[1] - point[1]) ** 2) ** 0.5
            if best is None or d < best[2]:
                best = (it, dt_of(it), d)
    if best is None:
        for it in loaded.layer_items(layer):
            if best is None or dt_of(it) < best[1]:
                best = (it, dt_of(it), None)
    if best is None:
        return None
    it, dt, dist = best
    return {"stream": it.stream, "row_kind": it.row_kind, "event_id": it.event_id,
            "id_source": it.id_source, "version": it.version, "t_ms": it.t_ms,
            "dt_ms": round(dt, 1), "distance_px": None if dist is None else round(dist, 1),
            "entity_id": it.entity_id, "label": it.label, "status": it.status}


# ---------------------------------------------------------------- the gaps

def _field_values(row, path):
    """Every value a key path reaches in `row` (a list path fans out)."""
    cur = [row]
    for part in path.split("."):
        nxt = []
        many = part.endswith("[]")
        key = part[:-2] if many else part
        for c in cur:
            if not isinstance(c, dict):
                continue
            v = c.get(key)
            if many:
                nxt.extend(v or [])
            else:
                nxt.append(v)
        cur = nxt
    return cur


def _present(v) -> bool:
    return v not in (None, [], {}, "")


def field_fraction(rows, path: str) -> float | None:
    """The share of the reached values that are present.

    `a|b` needs every part present; `a/b` counts a row when any alternative
    is present in it."""
    alts = path.split("/")
    hit = tot = 0
    for r in rows:
        best = None
        for alt in alts:
            parts = alt.split("|")
            vals = [_field_values(r, p) for p in parts]
            n = max((len(v) for v in vals), default=0)
            got = sum(all(i < len(v) and _present(v[i]) for v in vals) for i in range(n))
            if n and (best is None or got / n > best[0] / best[1]):
                best = (got, n)
        if best:
            hit += best[0]
            tot += best[1]
    return None if tot == 0 else hit / tot


def census(store, session_id: str) -> dict:
    """Per stream: rows drawn, and the measured share of each declared field."""
    out = {}
    for s, spec in STREAMS.items():
        rows = read_rows(store, s, session_id)
        if rows is None:
            out[s] = {"rows": None}
            continue
        drawn = [r for _n, r in rows if _kind(r) in spec.kinds]
        fr = {}
        for f in FIELDS:
            path = spec.fields.get(f)
            fr[f] = "absent" if path is None else field_fraction(drawn, path)
        out[s] = {"rows": len(drawn), "fields": fr,
                  "version": _version(drawn[0], s) if drawn else None}
    return out


def gap_rows(store, session_id: str) -> list[dict]:
    """The gap table: per stream, what it carries and what it lacks."""
    cen = census(store, session_id)
    rows = []
    for s, spec in STREAMS.items():
        c = cen[s]
        have, part, lack = [], [], []
        if c["rows"] is None:
            have = [f for f in FIELDS if spec.fields.get(f) is not None]
            part = ["no rows in this session: `has` is the declared schema, unmeasured"]
            lack = [f for f in FIELDS if spec.fields.get(f) is None]
        for f in FIELDS if c["rows"] is not None else ():
            v = (c.get("fields") or {}).get(f, "absent" if spec.fields.get(f) is None
                                            else None)
            if v == "absent":
                lack.append(f)
            elif v is None:
                part.append(f"{f} (no rows)")
            elif v >= 0.995:
                have.append(f)
            elif v <= 0.005:
                lack.append(f"{f} (declared, null)")
            else:
                part.append(f"{f} {v:.0%}")
        rows.append({"stream": s, "layer": LAYER_OF[s], "owner": spec.owner,
                     "module": spec.module, "rows": c["rows"], "version": c.get("version"),
                     "time_base": spec.time_base, "entity_key": spec.entity_key,
                     "identity": spec.identity, "have": have, "partial": part,
                     "lack": lack, "notes": spec.notes})
    return rows


def format_gaps(rows: list[dict], session_id: str) -> str:
    lines = [f"event gaps for {session_id} ({VIEW_EVENTS_VERSION}); fields the architecture "
             f"needs: {', '.join(FIELDS)}", ""]
    for r in rows:
        n = "no stream for this session" if r["rows"] is None else f"{r['rows']} rows"
        lines += [f"{r['stream']}  [{r['layer']}]  owner {r['owner']} ({r['module']})  "
                  f"{n}  {r['version'] or ''}",
                  f"   time base   {r['time_base']}",
                  f"   entity key  {r['entity_key']}",
                  f"   identity    {r['identity']}",
                  f"   has         {', '.join(r['have']) or '-'}"]
        if r["partial"]:
            lines.append(f"   partial     {', '.join(r['partial'])}")
        lines.append(f"   lacks       {', '.join(r['lack']) or '-'}")
        if r["notes"]:
            lines.append(f"   note        {r['notes']}")
        lines.append("")
    lines.append("no stream at all:")
    for what, owner, why in MISSING_STREAMS:
        lines.append(f"   {what:34s} {owner:36s} {why}")
    return "\n".join(lines)


def round_review_path(store, session_id: str) -> Path:
    return Path(store.root) / "labels" / "round_review" / f"{session_id}.jsonl"
