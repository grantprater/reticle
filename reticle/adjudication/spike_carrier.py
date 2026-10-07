r"""The spike's carrier, cross-checked across the channels that see it.

    .\.venv\Scripts\python.exe -m reticle spike <session> [--from-store]

Owns [owns:spike-carrier].

Pure over stored data: the `spike` rows (`reticle.spike`: the minimap glyph
and the roster marker per grid frame), the rounds table (`rounds`: the plant)
and the stored roster's alive counts (owner `alive-count`). It decodes nothing
and it names nobody. Three checks, each storing its disagreements as rows
rather than resolving them:

**The roster marker against the minimap glyph.** Our team's carrier is always
drawn on our minimap [domain:minimap/spike-carrier-overlay] and marked on our
roster [domain:hud/spike-carrier-marker], so on a frame where both channels
read, a marker without a carried glyph, or a carried glyph without a marker,
is a disagreement (`marker_without_glyph`, `glyph_without_marker`). The
carried glyph's icon is found by `spike.carrier_offset`; which channel carries
(`self` or `ally`) is stored beside the marker's slot, so the table of slot
against channel can be read for the player's own slot.

**The carrier against the plant.** A planted spike is carried by nobody, so a
marker or carried glyph more than PLANT_TOL_MS after a round's `plant_t_ms`
is `carried_after_plant`. On a round where our team carried the spike, the
planter carried it just before: no carrier read in the PRE_PLANT_MS before the
plant, while frames were read there, is `no_carrier_before_plant`. The
marker's last slot before the plant is stored as the planter's slot.

**A lost carrier against the alive count and the dropped glyph.** The marker
leaving the bar outside a plant window means the spike left the carrier: by
death, when the roster's alive count falls within DEATH_GAP_MS, or by a drop.
Either way the spike is on the ground, so a dropped glyph should follow within
DROP_GAP_MS. The "SPIKE CARRIER KILLED" banner would be a third witness; no
channel reads it yet. A loss with a death and no dropped glyph is
`death_without_dropped_glyph`; one with neither is `loss_unwitnessed`.

**The slot names nobody.** The marker's slot is the bar's packed position
(`spike` explains why); it equals the lineup's slot only while all five allies
live, which each claim records as `slot_is_lineup_slot`. The carrier's agent is
the lineup's answer for that slot (`agent-from-slot`), decided by the identity
arbiter, so each carrier row `depends_on` it rather than carrying a name.
"""
from __future__ import annotations

import numpy as np

from ..spike import carrier_offset
from ..version import SPIKE_CARRIER_VERSION, SPIKE_VERSION

#: A marker or carried glyph this long after the plant contradicts it.
PLANT_TOL_MS = 3000.0
#: The window before a plant in which the planter must be read carrying.
PRE_PLANT_MS = 10000.0
#: How near a lost marker the roster's alive count must fall to be its death.
DEATH_GAP_MS = 1500.0
#: How soon after a lost marker a dropped glyph must appear.
DROP_GAP_MS = 3000.0
#: The identity question a carrier's slot defers to.
DEPENDS_ON = "agent-from-slot"


def _alive_at(rt: np.ndarray, ra: list[int], t: float) -> int | None:
    if not len(rt):
        return None
    j = int(np.argmin(np.abs(rt - t)))
    return ra[j] if abs(rt[j] - t) <= 1000.0 and ra[j] >= 0 else None


def head_scale(head: dict) -> float:
    """The scale a stored `spike` read's icon offsets take: the map's
    (`map_scale.scale`, widget x zoom, which spike-0.3.0 heads store), else
    the head's `widget_scale`, the scale an older read was taken at."""
    ms = head.get("map_scale") or {}
    if ms.get("scale") is not None:
        return float(ms["scale"])
    return float(head.get("widget_scale") or 1.0)


def frame_state(row: dict, sc: float) -> dict:
    """One grid frame's spike state from its stored reading: `glyph`
    ("carried", "dropped", "none" or None where the minimap was not read),
    `carrier_channel` (the icon under a carried glyph, found at the offset the
    row's widget `rotation` turns, or None), `slot` (the marker's, or None)
    and `marker_read` (the roster was read, marker or not)."""
    mk = row.get("marker") or {}
    out = {"t_ms": row["t_ms"], "slot": mk.get("slot"),
           "marker_read": mk.get("reason") in (None, "no_marker"),
           "glyph": None, "carrier_channel": None}
    if row.get("reason") is not None:
        return out
    acc = [g for g in row.get("glyphs", []) if g.get("reason") is None]
    car = [g for g in acc if g["state"] == "carried"]
    out["glyph"] = "carried" if car else "dropped" if acc else "none"
    if car:
        ic = carrier_offset(car[0], row.get("icons", []), sc, row.get("rotation") or 0)
        out["carrier_channel"] = ic["channel"] if ic else None
    return out


def check(rows: list[dict], rounds: list[dict] | None, roster_t, roster_alive) -> list[dict]:
    """The carrier rows and disagreements for one session's stored `spike`
    rows: a coverage row first. `roster_t`/`roster_alive` are the stored
    roster's times and ally alive counts (-1 unread)."""
    head = rows[0]
    sc = head_scale(head)
    states = [frame_state(r, sc) for r in rows[1:] if r.get("kind") == "frame"]
    rt = np.asarray(roster_t, float)
    ra = [int(a) for a in roster_alive]
    out: list[dict] = []

    def dis(kind, t, **kw):
        out.append({"kind": "disagreement", "check": kind, "t_ms": t, **kw})

    # 1. the roster marker against the minimap glyph, where both read
    both = [s for s in states if s["glyph"] is not None and s["marker_read"]]
    agree = {"carried": 0, "none": 0}
    pairs: dict[str, int] = {}
    for s in both:
        marked, carried = s["slot"] is not None, s["glyph"] == "carried"
        if marked and carried:
            agree["carried"] += 1
            key = f"{s['slot']}:{s['carrier_channel']}"
            pairs[key] = pairs.get(key, 0) + 1
        elif not marked and not carried:
            agree["none"] += 1
        elif marked:
            dis("marker_without_glyph", s["t_ms"], slot=s["slot"], glyph=s["glyph"])
        else:
            dis("glyph_without_marker", s["t_ms"], carrier_channel=s["carrier_channel"])

    # 2. the carrier against the plant, per round
    carried_at = [s for s in states if s["slot"] is not None or s["glyph"] == "carried"]
    round_rows = []
    for rd in rounds or []:
        # The round's own span: after `t_end_ms` the next round's buy phase
        # hands the spike to a new carrier.
        a, b = rd.get("t_start_ms"), rd.get("t_end_ms")
        if a is None or b is None:
            continue
        inside = [s for s in carried_at if a <= s["t_ms"] <= b]
        rr = {"kind": "round", "round_no": rd.get("round_no"), "carrier_seen": bool(inside),
              "spike_planted": rd.get("spike_planted"), "plant_t_ms": rd.get("plant_t_ms"),
              "planter_slot": None}
        p = rd.get("plant_t_ms")
        if rd.get("spike_planted") and p is not None:
            late = [s for s in inside if s["t_ms"] > p + PLANT_TOL_MS]
            for s in late:
                dis("carried_after_plant", s["t_ms"], round_no=rd.get("round_no"),
                    plant_t_ms=p, slot=s["slot"], glyph=s["glyph"])
            if inside:
                before = [s for s in inside if p - PRE_PLANT_MS <= s["t_ms"] <= p]
                read = [s for s in states if p - PRE_PLANT_MS <= s["t_ms"] <= p
                        and (s["glyph"] is not None or s["marker_read"])]
                if not before and read:
                    dis("no_carrier_before_plant", p, round_no=rd.get("round_no"),
                        frames_read=len(read))
                slots = [s for s in before if s["slot"] is not None]
                if slots:
                    last = slots[-1]
                    alive = _alive_at(rt, ra, last["t_ms"])
                    rr["planter_slot"] = {"slot": last["slot"], "t_ms": last["t_ms"],
                                          "slot_is_lineup_slot": alive == 5,
                                          "depends_on": DEPENDS_ON}
        round_rows.append(rr)

    # 3. a lost marker against the alive count and a dropped glyph
    plants = [rd["plant_t_ms"] for rd in rounds or []
              if rd.get("spike_planted") and rd.get("plant_t_ms") is not None]
    read = [s for s in states if s["marker_read"]]
    losses = []
    for prev, cur in zip(read, read[1:]):
        if prev["slot"] is None or cur["slot"] is not None:
            continue
        t = cur["t_ms"]
        if any(p - PLANT_TOL_MS <= t <= p + PLANT_TOL_MS for p in plants):
            continue
        a0, a1 = _alive_at(rt, ra, prev["t_ms"] - DEATH_GAP_MS), _alive_at(rt, ra, t + DEATH_GAP_MS)
        death = None if a0 is None or a1 is None else a1 < a0
        dropped = any(s["glyph"] == "dropped" for s in states
                      if prev["t_ms"] <= s["t_ms"] <= t + DROP_GAP_MS)
        loss = {"kind": "carrier_lost", "t_ms": t, "last_marked_ms": prev["t_ms"],
                "slot": prev["slot"], "death": death, "dropped_glyph_seen": dropped,
                "depends_on": DEPENDS_ON}
        losses.append(loss)
        if death and not dropped:
            dis("death_without_dropped_glyph", t, slot=prev["slot"])
        elif death is False and not dropped:
            dis("loss_unwitnessed", t, slot=prev["slot"])

    counts: dict[str, int] = {}
    for d in out:
        counts[d["check"]] = counts.get(d["check"], 0) + 1
    cov = {"kind": "coverage", "session": head.get("session"),
           "spike_carrier_version": SPIKE_CARRIER_VERSION, "spike_version": SPIKE_VERSION,
           "stored_spike_version": head.get("spike_version"),
           "parameters": {"PLANT_TOL_MS": PLANT_TOL_MS, "PRE_PLANT_MS": PRE_PLANT_MS,
                          "DEATH_GAP_MS": DEATH_GAP_MS, "DROP_GAP_MS": DROP_GAP_MS},
           "frames": len(states), "both_read": len(both), "agree": agree,
           "slot_by_channel": dict(sorted(pairs.items())), "disagreements": counts,
           "rounds": len(round_rows),
           "rounds_carrier_seen": sum(r["carrier_seen"] for r in round_rows),
           "losses": len(losses),
           "losses_by_witness": {
               "death_and_drop": sum(bool(l["death"]) and l["dropped_glyph_seen"] for l in losses),
               "death_only": sum(bool(l["death"]) and not l["dropped_glyph_seen"] for l in losses),
               "drop_only": sum(l["death"] is False and l["dropped_glyph_seen"] for l in losses),
               "neither": sum(l["death"] is False and not l["dropped_glyph_seen"] for l in losses),
               "alive_unread": sum(l["death"] is None for l in losses)}}
    rows_out = [cov] + round_rows + losses + out
    for r in rows_out:
        r["spike_carrier_version"] = SPIKE_CARRIER_VERSION
    return rows_out
