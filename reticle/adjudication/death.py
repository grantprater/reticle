"""Adjudication of death events, victim identity, and death locations.

Cross-references killfeed death entries, roster living-set shrink events, and
terminating minimap tracks to answer: *which agent died at this killfeed time,
and where?*

Observability rules:
- Ally deaths are always observable via cyan/blue minimap marks or local HUD
  [domain:minimap/ally-death-mark].
- Gun kills are two-sided: both death location and killer location are observable
  [domain:minimap/enemy-death-mark].
- Non-gun kills (ability or environmental, e.g. falling off Abyss or door crushed
  [domain:minimap/environmental-death]) are observable for allies, but may be
  unobserved for enemies when outside team vision; in such cases, enemy death
  location is explicitly abstained.
- Resurrection and second-life mechanics are limited to the closed four-agent set
  (Phoenix Run It Back, Sage Resurrection, Clove Not Dead Yet, and KAY/O NULL/cmd)
  [domain:rounds/resurrection-mechanics].

This module decides WHICH death a witness speaks about and never decides the
name. Each witness becomes an `identity_claim` keyed by the death id, and
`adjudication.identity` returns the victim; see that module for why.

Owns [owns:death-victim].
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from ..events import (
    EntityState,
    EventKind,
    SourceChannel,
    entity_deleted_event,
    entity_state_event,
    session_boundary_event,
)
from ..killfeed import (SECOND_LIFE_RUN_MIN, detect_second_life_badge,  # noqa: F401 -- re-exported
                        fit_arc)
from ..roster import N_SLOTS
from .identity import (adjudicate_agent_identity, claim_from_killfeed_portrait,
                       identity_claim, identity_events, side_candidates, _channel_verdict)
from .weapon import caster_claim, classify_killfeed_icon, entry_weapon

# 0.7.0 (2026-09-24): deaths keyed by entry onset and slot (`death_key`), not
# list index; `reticle deaths` stores verdicts from stored data only.
# 0.8.0 (2026-09-24): each entry's weapon and cause from the stored
# `killfeed_weapon` descriptors, named by `adjudication.weapon.entry_weapon`.
# 0.9.0 (2026-09-24): an entry whose icon names a revive is stored as a revive,
# not a death (`REVIVE_ICONS`).
# 0.10.0 (2026-09-25): an ability icon is a witness of the killer (its caster,
# `ability_agent`), and the lineup bounds which abilities an icon can name.
# 0.11.0 (2026-09-25): a killer the icon named labels portrait exemplars.
DEATH_ADJUDICATION_VERSION = "death-adjudication-0.11.0"

#: Weapon-slot icons that mark a revive entry, which is not a death
#: [domain:killfeed/revive-entries]: the reviving agent by icon. The icon is
#: the witness; the top bar is not one for Clove, whose death it never shows
#: when Not Dead Yet follows within two seconds.
REVIVE_ICONS = {"Not Dead Yet": "Clove", "Resurrection": "Sage"}
MAX_DEATH_ALIGNMENT_DT_MS = 2500.0


def attach_stored_killfeed_portraits(
    entries: list[dict], observations: list[dict], lineup: dict, gallery: dict,
    *, source_version: str, exemplars: list[dict] = (),
) -> list[dict]:
    """Join raw portraits to their first entry interval without reading media.

    A stack slot is only stable until the next new entry. A single named frame
    is retained as evidence but cannot promote a victim: its appearance has no
    within-entry repeat check. Every view must name the same admitted lineup
    candidate before this channel publishes a name. Refused lineup slots stay
    rivals in every comparison, including after earlier deaths.

    `exemplars` (`portrait_exemplars`) widen each agent's references with this
    session's own labelled portraits, never the entry's own; a name one of
    them decided carries `depends_on` on the death that labelled it.
    """
    out = []
    portraits = [r for r in observations if r.get("kind") == "portrait_observation"]
    for i, original in enumerate(entries):
        entry = dict(original)
        start = float(entry["t_ms"])
        end = min(start + 2000.0,
                  float(entries[i + 1]["t_ms"]) if i + 1 < len(entries) else float("inf"))
        side = entry.get("side")
        killer_side = {"ally": "enemy", "enemy": "ally"}.get(side)
        entry["claim"] = _portrait_channel(
            portraits, "victim", side, entry.get("slot"), start, end, lineup, gallery,
            entity_id=f"death:{int(start)}:victim", source_version=source_version,
            exemplars=exemplars)
        entry["killer_claim"] = _portrait_channel(
            portraits, "killer", killer_side, entry.get("slot"), start, end, lineup, gallery,
            entity_id=f"death:{int(start)}:killer", source_version=source_version,
            exemplars=exemplars)
        out.append(entry)
    return out


def _portrait_channel(portraits, role, side, slot, start, end, lineup, gallery, *,
                      entity_id, source_version, exemplars=()):
    """One role's stored portrait views in an entry window, as one channel claim.

    The killer's plate is the side opposite the victim's; a view whose plate
    says otherwise (a team kill, or a misread) names nothing.
    """
    split = side_candidates(lineup.get("sides", {}).get(side, []))
    views = sorted((r for r in portraits
                    if start <= float(r.get("t_ms", -1)) < end
                    and r.get("slot") == slot and r.get("role") == role),
                   key=lambda r: (r["t_ms"], r.get("frame_idx", -1)))
    claims = []
    for view in views:
        if ("ally" if view.get("ally") is True else
            "enemy" if view.get("ally") is False else None) != side:
            claim = {"agent": None, "reason": "portrait_side_disagrees_with_entry",
                     "evidence": {"observation_key": view.get("observation_key"),
                                  "observed_side": view.get("ally")}}
        elif split["blind"]:
            claim = {"agent": None, "reason": "lineup_has_blind_rival",
                     "evidence": {"blind": split["blind"]}}
        else:
            claim = claim_from_killfeed_portrait(
                view, entity_id=entity_id,
                candidates=split["named"], rivals=split["rivals"],
                gallery=gallery, source_version=source_version,
                exemplars=exemplars, exclude_entry=start)
        claims.append({"observation_key": view.get("observation_key"),
                       "t_ms": view.get("t_ms"), "frame_idx": view.get("frame_idx"),
                       "agent": claim.get("agent"), "reason": claim.get("reason"),
                       "depends_on": claim.get("depends_on", []),
                       "composition": view.get("composition"),
                       "evidence": claim.get("evidence", {})})
    names = {c["agent"] for c in claims if c["agent"]}
    unanimous = len(claims) >= 2 and len(names) == 1 and all(c["agent"] for c in claims)
    reason = (None if unanimous else
              "no_stored_portrait_at_entry" if not claims else
              "portrait_single_view" if len(claims) == 1 else
              "portrait_views_refused_or_disagree")
    return {
        "channel": "killfeed_portrait", "agent": next(iter(names)) if unanimous else None,
        "reason": reason, "source_version": source_version,
        "depends_on": (sorted({d for c in claims for d in c["depends_on"]})
                       if unanimous else []),
        "evidence": {"window_ms": [start, end], "slot": slot, "role": role, "side": side,
                     "named_candidates": split["named"],
                     "refused_rivals": split["rivals"], "blind_rivals": split["blind"],
                     "observations": claims},
    }


def scoreboard_death_claims(entries: list[dict], openings: list[dict],
                            named: dict[int, str | None],
                            second_life: set[int] = frozenset(),
                            contradicted: set[tuple[float, str]] = frozenset()) -> list[dict]:
    """A victim witness per killfeed entry from the scoreboard's dimmed rows.

    Between the last accepted opening before a death and the first after it,
    the side's NEWLY dimmed agents are the players who died in that interval
    [domain:rounds/scoreboard-dead-dimmed]. The count must equal the killfeed
    deaths on that side in the same interval, or the claim refuses: the two
    channels disagreeing is output, not something to average.

    One death and one newly dimmed agent is a binding. Several deaths are not
    ordered by the board, so a death is named only by ELIMINATION: every other
    death in the interval already carries a name from an independent channel
    (`named`, which must not come from this witness), those names are all in
    the dimmed set, and exactly one agent is left. The names it rested on are
    stored with the claim.

    What dimming means is a player rule [domain:rounds/scoreboard-dim-is-dead]:
    a Run It Back death does not dim, so second-life deaths (`second_life`
    indices, or an entry flag) are left out of the count and name nothing
    here; a dimmed agent lit again was revived, which is recorded and is not a
    contradiction. A revive entry (`revive_entry`) is not a death and names
    nothing; an interval holding one on the side refuses, since the revived
    agent can die again and stay dim at both ends. A downed KAY/O is unknown
    to it, and a count that disagrees still refuses.

    `contradicted` holds the (opening time, side) pairs whose lit count the
    roster contradicts (`reconciliation.audit_board_alive`). The board relights
    its rows a moment after the top bar resets at a round start
    [domain:rounds/scoreboard-relights-after-top-bar], so such an
    opening carries the previous round's dead; the witness skips it on that
    side and counts the skips in the evidence.
    """
    from .scoreboard import SCOREBOARD_AGENT_VERSION, side_state
    accepted = [o for o in openings if o["accepted"]]
    claims = []
    for i, entry in enumerate(entries):
        t_ms, side = float(entry["t_ms"]), entry.get("side")
        usable = [o for o in accepted if (o["t_ms"], side) not in contradicted]
        before = [o for o in usable if o["t_ms"] < t_ms]
        after = [o for o in usable if o["t_ms"] > t_ms]
        claim = {"channel": "scoreboard_dim", "agent": None, "reason": None,
                 "source_version": SCOREBOARD_AGENT_VERSION, "evidence": {}}
        claims.append(claim)
        if side not in ("ally", "enemy"):
            claim["reason"] = "entry_side_unknown"
            continue
        if revive_entry(entry):
            claim["reason"] = "revive_entry_is_not_a_death"
            continue
        if _second_life(i, entries, second_life):
            claim["reason"] = "second_life_death_does_not_dim"
            continue
        if not before or not after:
            claim["reason"] = ("no_accepted_opening_before" if not before
                               else "no_accepted_opening_after")
            continue
        lo, hi = before[-1], after[0]
        was, now = side_state(lo, side), side_state(hi, side)
        newly = now["dim"] - was["dim"]
        revived = was["dim"] - now["dim"]
        deaths = [j for j, e in enumerate(entries)
                  if e.get("side") == side and lo["t_ms"] < float(e["t_ms"]) < hi["t_ms"]
                  and not _second_life(j, entries, second_life) and not revive_entry(e)]
        claim["evidence"] = {
            "opening_before": {"t_ms": lo["t_ms"], "frame_idx": lo["frame_idx"],
                               "dim": sorted(was["dim"])},
            "opening_after": {"t_ms": hi["t_ms"], "frame_idx": hi["frame_idx"],
                              "dim": sorted(now["dim"])},
            "newly_dim": sorted(newly),
            "revived": sorted(revived),
            "interval_deaths": [float(entries[j]["t_ms"]) for j in deaths],
            "skipped_contradicted": sum(lo["t_ms"] < t < hi["t_ms"] for t, s in contradicted
                                        if s == side),
            "observation_keys": [s["observation_key"] for s in hi["rows"]
                                 if s["team"] == side and s["agent"] in newly],
        }
        # A revived agent can die again before the next opening and stay dim
        # at both ends (b3b9defb6fd7 1289.5 s, Skye), so the difference no
        # longer counts the interval's deaths.
        revives = [float(e["t_ms"]) for e in entries if revive_entry(e)
                   and e.get("side") == side and lo["t_ms"] < float(e["t_ms"]) < hi["t_ms"]]
        if revives:
            claim["evidence"]["interval_revives"] = revives
            claim["reason"] = "revive_in_interval"
        elif len(newly) != len(deaths):
            claim["reason"] = (f"newly_dim_{len(newly)}_disagrees_with_"
                               f"killfeed_deaths_{len(deaths)}")
        elif len(newly) == 1:
            claim["agent"] = next(iter(newly))
        else:
            others = [j for j in deaths if j != i]
            names = [named.get(j) for j in others]
            claim["evidence"]["by_elimination"] = [
                {"t_ms": float(entries[j]["t_ms"]), "agent": named.get(j)} for j in others]
            if not all(names):
                claim["reason"] = f"interval_unordered {sorted(newly)}"
            elif not set(names) <= newly or len(set(names)) != len(names):
                claim["reason"] = (f"other_names_not_in_newly_dim {sorted(names)} "
                                   f"vs {sorted(newly)}")
            else:
                left = newly - set(names)
                if len(left) == 1:
                    claim["agent"] = next(iter(left))
                    claim["depends_on_entries"] = others
                else:
                    claim["reason"] = f"interval_unordered {sorted(left)}"
    return claims


#: Channels whose name may label an exemplar. The portrait channel is not one:
#: its own output labelling its own references is a model grading itself.
#: The ability icon's caster (`killfeed_weapon`) is one too: other pixels than
#: the portrait, named by a gallery the player labelled.
EXEMPLAR_LABEL_CHANNELS = ("scoreboard_dim", "player_hud", "killfeed_weapon")


def portrait_exemplars(verdicts: list["DeathVerdict"], entries: list[dict]) -> list[dict]:
    """This session's portraits, labelled by a witness other than the portrait.

    A death whose victim the arbiter resolved, with an INDEPENDENT claim from
    `EXEMPLAR_LABEL_CHANNELS` naming that agent, lends its victim views; a
    killer the player HUD or the ability icon named lends its killer views. A claim that rests on
    another verdict (`depends_on`, as elimination does) labels nothing, so an
    exemplar never carries a name that was itself inferred from portraits.
    `entries` are the attached entries the verdicts came from, in order.
    """
    out = []
    for verdict, entry in zip(verdicts, entries):
        for key, role, claim in (("identity", "victim", entry.get("claim")),
                                 ("killer_identity", "killer", entry.get("killer_claim"))):
            v = verdict.metadata.get(key)
            if not v or v["status"] != "resolved" or not claim:
                continue
            labels = [c for c in v["claims"] if c["channel"] in EXEMPLAR_LABEL_CHANNELS
                      and c["agent"] == v["agent"] and not c["depends_on"]]
            if not labels:
                continue
            for view in claim.get("evidence", {}).get("observations", []):
                if view.get("composition") is None:
                    continue
                out.append({"agent": v["agent"], "composition": view["composition"],
                            "role": role, "entry_t_ms": float(entry["t_ms"]),
                            "label_entity": v["entity_id"],
                            "label_channel": labels[0]["channel"],
                            "observation_key": view.get("observation_key")})
    return out


def _second_life(i: int, entries: list[dict], second_life) -> bool:
    e = entries[i]
    return i in second_life or bool(e.get("is_second_life") or e.get("is_run_it_back"))


def revive_entry(entry: dict) -> bool:
    """Whether a killfeed entry is a revive rather than a death: its weapon,
    named by `adjudication.weapon.entry_weapon`, is one of `REVIVE_ICONS`."""
    return (entry.get("weapon_evidence") or {}).get("name") in REVIVE_ICONS


BLUE_X_H = (95, 118)
BLUE_X_S_MIN = 100
BLUE_X_V_MIN = 100

RED_X_H1 = (0, 10)
RED_X_H2 = (165, 180)
RED_X_S_MIN = 90
RED_X_V_MIN = 120
XMARK_AREA_RANGE = (15, 150)
#: Blue marks only. Over 240 s of a06f04a0059f at 1 Hz, blue components
#: cluster at 100-130 px (one X) and 200-212 px (two overlapping X marks),
#: with nothing above 212; the shared 150 px cap dropped every merged pair.
#: Red has no such gap (a continuous tail past 500 px from enemy icon rings
#: and pings), so red keeps `XMARK_AREA_RANGE`. Area / ~115 px estimates how
#: many blue marks a blob holds.
BLUE_XMARK_AREA_RANGE = (15, 300)

#: Slack around a killfeed track's lifetime when collecting its badge reads.
SECOND_LIFE_SLACK_MS = 500.0


def second_life_death(t_first: float, t_last: float, observations: list[dict]) -> bool | None:
    """Whether the player's killfeed death seen from `t_first` to `t_last` is a
    second life (Run It Back, a downed KAY/O) rather than a death.

    A majority vote over the stored `second_life_observation` rows inside the
    track's lifetime. None when no observation falls there: unread, which a
    caller keeps apart from "no badge".
    """
    votes = [o["has_badge"] for o in observations
             if o.get("kind") == "second_life_observation"
             and t_first - SECOND_LIFE_SLACK_MS <= o["t_ms"] <= t_last + SECOND_LIFE_SLACK_MS]
    if not votes:
        return None
    return sum(votes) * 2 > len(votes)


def death_key(session_id: str, t_ms: float, slot: int) -> str:
    """A death's stable entity key: the session, the first-seen time of its
    killfeed entry track and the slot it appeared in. Two entries cannot
    appear in one slot of one frame, and the key does not move when detection
    adds or drops another entry."""
    return f"death:{session_id}:{int(float(t_ms))}:{int(slot)}"


def session_entries(hud: dict, second_life: list[dict] | None = None) -> list[dict]:
    """One dict per counted killfeed entry track over the whole session, from
    stored HUD columns only: first-seen time, the slot it appeared in, the
    victim's plate side there, and whether it is the player's kill or death.

    Tracked over the session, not per round: a death on a round's last sample
    is a one-frame track inside the round and would be refused. The player's
    kill and death are the tracks `rounds` counts (`merge_split_tracks`), each
    given to the entry on screen at its onset whose divider agrees. A player death
    that `second_life_death` calls a second life carries `is_second_life`.
    """
    from ..checks import KF_SIG_TOL, merge_split_tracks, track_entries
    t = hud["t_ms"]
    at = {x: i for i, x in enumerate(t)}
    col = lambda c: hud.get(c) or [None] * len(t)
    mine = {kind: merge_split_tracks([e for e in track_entries(t, hud[f"kf_{kind}_mask"],
                                                                col(f"kf_{kind}_wx"))
                                      if e["counted"]])
            for kind in ("kill", "death")}
    tracks = [e for e in track_entries(t, hud["kf_entry_mask"], col("kf_entry_wx")) if e["counted"]]
    # A player track belongs to the entry on screen when it was first seen
    # whose divider agrees, the latest such onset first (the attribution can
    # come a sample after the plate), then the one that appeared in its slot.
    owner = {"kill": {}, "death": {}}
    for kind, seq in mine.items():
        for k in seq:
            fits = [j for j, e in enumerate(tracks)
                    if e["t_first"] <= k["t_first"] <= e["t_last"]
                    and (k.get("sig") is None or e.get("sig") is None
                         or abs(k["sig"] - e["sig"]) <= KF_SIG_TOL)]
            if fits:
                owner[kind].setdefault(max(fits, key=lambda j: (
                    tracks[j]["t_first"], tracks[j]["slot_first"] == k["slot_first"])), k)
    out = []
    for j, e in enumerate(tracks):
        i, slot = at[e["t_first"]], e["slot_first"]
        bit = lambda c: bool((hud[c][i] or 0) & (1 << slot))
        ally, enemy = bit("kf_ally_mask"), bit("kf_enemy_mask")
        pk = j in owner["kill"]
        dt = owner["death"].get(j)
        out.append({"t_ms": e["t_first"], "t_first": e["t_first"], "t_last": e["t_last"],
                    "slot": slot, "sig": e.get("sig"), "side": "ally" if ally else "enemy" if enemy else "unknown",
                    "victim_ally": ally, "kf_player_kill": pk, "kf_player_death": dt is not None,
                    "is_second_life": bool(dt is not None and second_life is not None
                                           and second_life_death(dt["t_first"], dt["t_last"],
                                                                 second_life)),
                    "claim": None, "location": None, "killer_location": None})
    return out


def stored_second_life(portrait_rows: list[dict], version: str) -> list[dict] | None:
    """The `second_life_observation` rows among a session's stored
    `killfeed_portrait` events, or None when the stream is absent or not at
    `version`: only a current stream carries badge reads, and a caller given
    None counts every death rather than trusting a stale one."""
    if not portrait_rows or portrait_rows[0].get("killfeed_portrait_version") != version:
        return None
    return [r for r in portrait_rows if r.get("kind") == "second_life_observation"]


def split_second_lives(deaths: list[dict], observations: list[dict] | None
                       ) -> tuple[list[dict], list[dict]]:
    """The player's killfeed death tracks split into (deaths, second lives) by
    `second_life_death`. An unread track stays a death; None observations
    split nothing."""
    if observations is None:
        return list(deaths), []
    lives = [d for d in deaths if second_life_death(d["t_first"], d["t_last"], observations)]
    return [d for d in deaths if d not in lives], lives


REVIVE_ABILITY_ICONS = {
    "Sage": "Sage_Ultimate.png",
    "Clove": "Clove_Ultimate.png",
    "Phoenix": "Phoenix_Ultimate.png",
    "KAY/O": "KAY_O_Ultimate.png",
}

_REVIVE_ICONS_CACHE: dict[str, np.ndarray] = {}


@dataclass(frozen=True)
class DeathVerdict:
    """Adjudicated result for one killfeed death instant."""

    death_id: str
    t_ms: float
    side: str  # "ally" or "enemy"
    victim: Optional[str] = None
    killer: Optional[str] = None
    death_cause: str = "gun"  # "gun" | "ability" | "environmental" | "melee" | "other"
    weapon: Optional[str] = None
    location: Optional[tuple[float, float]] = None
    killer_location: Optional[tuple[float, float]] = None
    status: str = "abstained"  # "resolved" | "abstained" | "disagreement"
    is_second_life: bool = False
    is_revive: bool = False
    channels: list[str] = field(default_factory=list)
    independent_channels: int = 0
    witnesses: list[dict] = field(default_factory=list)
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "death_id": self.death_id,
            "t_ms": self.t_ms,
            "side": self.side,
            "victim": self.victim,
            "killer": self.killer,
            "death_cause": self.death_cause,
            "weapon": self.weapon,
            "location": list(self.location) if self.location else None,
            "killer_location": list(self.killer_location) if self.killer_location else None,
            "status": self.status,
            "is_second_life": self.is_second_life,
            "is_revive": self.is_revive,
            "channels": list(self.channels),
            "independent_channels": self.independent_channels,
            "witnesses": self.witnesses,
            "reason": self.reason,
            "metadata": self.metadata,
            "adjudication_version": DEATH_ADJUDICATION_VERSION,
        }


def extract_minimap_death_marks(
    crop: np.ndarray,
    floor: Optional[np.ndarray] = None,
) -> tuple[list[tuple[int, float, float]], list[tuple[int, float, float]]]:
    """Detect blue (ally) and red (enemy) death X marks and pings from a minimap crop.

    Returns:
        tuple of (blue_blobs, red_blobs), where each blob is (area, x, y).
    """
    import cv2

    if floor is None:
        floor = np.ones(crop.shape[:2], dtype=bool)

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = (hsv[:, :, i].astype(np.int16) for i in range(3))

    # Blue mask (ally death X)
    blue_mask = (hh > BLUE_X_H[0]) & (hh < BLUE_X_H[1]) & (ss > BLUE_X_S_MIN) & (vv > BLUE_X_V_MIN) & floor
    n_b, _, st_b, cen_b = cv2.connectedComponentsWithStats(blue_mask.astype(np.uint8), 8)
    blue_blobs = [
        (int(st_b[i, 4]), float(cen_b[i][0]), float(cen_b[i][1]))
        for i in range(1, n_b)
        if BLUE_XMARK_AREA_RANGE[0] <= st_b[i, 4] <= BLUE_XMARK_AREA_RANGE[1]
    ]

    # Red mask (enemy death X / enemy pings)
    red_mask = ((hh < RED_X_H1[1]) | (hh > RED_X_H2[0])) & (ss > RED_X_S_MIN) & (vv > RED_X_V_MIN) & floor
    n_r, _, st_r, cen_r = cv2.connectedComponentsWithStats(red_mask.astype(np.uint8), 8)
    red_blobs = [
        (int(st_r[i, 4]), float(cen_r[i][0]), float(cen_r[i][1]))
        for i in range(1, n_r)
        if XMARK_AREA_RANGE[0] <= st_r[i, 4] <= XMARK_AREA_RANGE[1]
    ]

    return blue_blobs, red_blobs


def extract_killer_location(
    killer_side: str,
    killer_agent: Optional[str] = None,
    t_ms: float = 0.0,
    victim_location: Optional[tuple[float, float]] = None,
    *,
    player_agent: Optional[str] = None,
    player_position: Optional[tuple[float, float]] = None,
    ally_positions: Optional[list[tuple[float, float]]] = None,
    enemy_sightings: Optional[list[tuple[float, float]]] = None,
) -> Optional[tuple[float, float]]:
    """Attribute killer location based on side, player position, ally rings, or enemy sightings."""
    if killer_side == "ally":
        if (player_agent and killer_agent and killer_agent.lower() == player_agent.lower()) or (player_position and not ally_positions):
            return player_position
        if ally_positions:
            if victim_location:
                return min(ally_positions, key=lambda pt: math.hypot(pt[0] - victim_location[0], pt[1] - victim_location[1]))
            return ally_positions[0]
        return player_position
    elif killer_side == "enemy":
        if enemy_sightings:
            if victim_location:
                return min(enemy_sightings, key=lambda pt: math.hypot(pt[0] - victim_location[0], pt[1] - victim_location[1]))
            return enemy_sightings[0]
    return None


def classify_revive_icon(
    crop: np.ndarray,
    assets_dir: Optional[Any] = None,
    min_score: float = 0.60,
    min_margin: float = 0.10,
) -> tuple[Optional[str], float, dict[str, Any]]:
    """Classify ability icon crop against known revive/second-life abilities.

    Matches against Sage Resurrection, Clove Not Dead Yet, Phoenix Run It Back,
    and KAY/O NULL/cmd.

    Returns:
        tuple (matched_agent, score, metadata) where matched_agent is None if below margin/score.
    """
    import cv2
    from pathlib import Path

    if crop is None or crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None, 0.0, {"scores": {}, "margin": 0.0}

    if assets_dir is None:
        from ..store import Store
        try:
            assets_dir = Store().root / "reference" / "assets" / "abilities"
        except Exception:
            assets_dir = Path("reticle-store/reference/assets/abilities")
    else:
        assets_dir = Path(assets_dir)

    # Load / cache templates
    if not _REVIVE_ICONS_CACHE and assets_dir.is_dir():
        for ag, fname in REVIVE_ABILITY_ICONS.items():
            fpath = assets_dir / fname
            if fpath.is_file():
                raw = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
                if raw is not None:
                    _REVIVE_ICONS_CACHE[ag] = raw

    if not _REVIVE_ICONS_CACHE:
        return None, 0.0, {"scores": {}, "margin": 0.0, "reason": "no_revive_assets"}

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white_mask = ((hsv[:, :, 2] > 185) & (hsv[:, :, 1] < 75)).astype(np.float32)
    ch, cw = white_mask.shape[:2]

    scores: dict[str, float] = {}
    for agent, raw in _REVIVE_ICONS_CACHE.items():
        best_agent_score = 0.0
        min_th = max(12, ch - 8)
        max_th = min(ch + 1, 28)
        for th in range(min_th, max_th):
            tw = int(round(raw.shape[1] * (th / raw.shape[0])))
            if ch >= th and cw >= tw:
                resized = cv2.resize(raw, (tw, th))
                tpl_mask = (resized[:, :, 3] > 128).astype(np.float32)
                res = cv2.matchTemplate(white_mask, tpl_mask, cv2.TM_CCOEFF_NORMED)
                _, max_v, _, _ = cv2.minMaxLoc(res)
                if not math.isnan(max_v) and max_v > best_agent_score:
                    best_agent_score = float(max_v)
        scores[agent] = round(best_agent_score, 3)

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if not sorted_scores:
        return None, 0.0, {"scores": {}, "margin": 0.0}

    top_agent, top_score = sorted_scores[0]
    runner_up = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    margin = round(top_score - runner_up, 3)

    matched = top_agent if (top_score >= min_score and margin >= min_margin) else None
    return matched, top_score, {"scores": scores, "margin": margin, "top_agent": top_agent}


def adjudicate_death(
    *,
    death_id: str,
    t_ms: float,
    side: str,
    killfeed_claim: Optional[dict] = None,
    scoreboard_claim: Optional[dict] = None,
    roster_shrink: Optional[dict] = None,
    track_termination: Optional[dict] = None,
    xmark_location: Optional[tuple[float, float]] = None,
    killer_location: Optional[tuple[float, float]] = None,
    death_cause: str = "gun",
    weapon: Optional[str] = None,
    player_agent: Optional[str] = None,
    is_player_kill: bool = False,
    is_player_death: bool = False,
    is_second_life: bool = False,
    is_revive: bool = False,
    victim_depends_on: Optional[dict] = None,
    killer_claim: Optional[dict] = None,
) -> DeathVerdict:
    """Adjudicate victim identity, killer, and location for one death instant.

    `victim_depends_on` maps a channel to the death ids its name rested on, so
    the arbiter can refuse to count it as independent.

    The killer is a second entity, `<death_id>:killer`, named by the same
    arbiter: the player HUD on a player kill, and `killer_claim`, the killer
    portraits (`attach_stored_killfeed_portraits`). An environmental death has
    no killer claim at all.

    Corroborates four independent candidate channels:
    1. `killfeed_claim`: portrait/role claim from killfeed plate.
    2. `scoreboard_claim`: the agent the Tab scoreboard newly dimmed around
       this death (`scoreboard_death_claims`).
    3. `roster_shrink`: agent differenced from living set occupancy.
    4. `track_termination`: terminating minimap track and its identity.

    Cross-channel disagreements are preserved explicitly as `disagreement`
    verdicts rather than masked by majority vote. Refused or thin witnesses
    stay in evidence and yield `abstained`.
    """
    witnesses = []
    channels = []
    victim_candidates = {}

    if not is_second_life and killfeed_claim:
        is_second_life = bool(killfeed_claim.get("is_second_life") or killfeed_claim.get("is_run_it_back"))

    # 1. Killfeed witness
    if killfeed_claim:
        witnesses.append(killfeed_claim)
        ch = killfeed_claim.get("channel", "killfeed_portrait")
        channels.append(ch)
        kf_agent = killfeed_claim.get("agent")
        if kf_agent:
            victim_candidates[ch] = kf_agent
        if not weapon and killfeed_claim.get("weapon"):
            weapon = killfeed_claim["weapon"]
        if death_cause == "gun" and killfeed_claim.get("death_cause"):
            death_cause = killfeed_claim["death_cause"]

    # Scoreboard dimmed-row witness
    if scoreboard_claim:
        witnesses.append(scoreboard_claim)
        channels.append("scoreboard_dim")
        if scoreboard_claim.get("agent"):
            victim_candidates["scoreboard_dim"] = scoreboard_claim["agent"]

    # 2. Roster shrink witness
    if roster_shrink:
        witnesses.append({
            "channel": "roster_diff",
            "t_ms": roster_shrink.get("t_ms"),
            "gone": roster_shrink.get("gone"),
            "margin": roster_shrink.get("margin"),
            "named": roster_shrink.get("named"),
        })
        channels.append("roster_diff")
        gone = roster_shrink.get("gone") or []
        if len(gone) == 1:
            victim_candidates["roster_diff"] = gone[0]
        elif len(gone) > 1:
            # Multiple agents dropped simultaneously
            victim_candidates["roster_diff"] = None

    # 3. Minimap track termination witness
    if track_termination:
        witnesses.append({
            "channel": "minimap_track",
            "entity_id": track_termination.get("entity_id"),
            "last_seen_ms": track_termination.get("last_seen_ms"),
            "location": track_termination.get("location"),
            "agent": track_termination.get("agent"),
        })
        channels.append("minimap_track")
        tr_agent = track_termination.get("agent")
        if tr_agent:
            victim_candidates["minimap_track"] = tr_agent

    # Killer attribution: a second entity, named by the identity arbiter.
    killer_id = f"{death_id}:killer"
    killer_claims = []
    if death_cause == "environmental":
        # Falling off map (Abyss) or crushed by door (Summit) has no killer unless credited
        killer_location = None
    else:
        if is_player_kill and player_agent:
            killer_claims.append(identity_claim(killer_id, player_agent, channel="player_hud"))
        if killer_claim:
            killer_claims.append(identity_claim(
                killer_id, killer_claim.get("agent"), channel="killfeed_portrait",
                reason=killer_claim.get("reason"),
                source_version=killer_claim.get("source_version"),
                evidence=killer_claim.get("evidence"),
                depends_on=killer_claim.get("depends_on")))
        elif killfeed_claim and killfeed_claim.get("killer"):
            killer_claims.append(identity_claim(killer_id, killfeed_claim["killer"],
                                                channel="killfeed_portrait"))
        # An ability icon names its caster: other pixels than the portraits, so
        # a witness that can disagree with them. A revive's "killer" is the
        # reviver, which the icon names the same way.
        caster = caster_claim(killer_id, weapon) if death_cause == "ability" else None
        if caster:
            killer_claims.append(caster)
    killer_identity = (adjudicate_agent_identity(killer_claims) or [None])[0]
    killer = killer_identity["agent"] if killer_identity else None

    # If local player died, player_agent is the definitive victim witness
    if is_player_death and player_agent:
        witnesses.append({
            "channel": "player_hud",
            "victim": player_agent,
            "evidence": "kf_player_death",
        })
        channels.append("player_hud")
        victim_candidates["player_hud"] = player_agent

    # Location attribution
    location = None
    if xmark_location:
        location = xmark_location
        channels.append("xmark")
        witnesses.append({
            "channel": "xmark",
            "location": xmark_location,
        })
    elif track_termination and track_termination.get("location"):
        location = track_termination["location"]

    # Killer location attribution
    if killer_location:
        channels.append("killer_location")
        witnesses.append({
            "channel": "killer_location",
            "killer": killer,
            "location": killer_location,
        })

    # The name is decided by the identity arbiter, keyed by this death.
    named_votes = {ch: ag for ch, ag in victim_candidates.items() if ag}
    depends = dict(victim_depends_on or {})
    if killfeed_claim and killfeed_claim.get("depends_on"):
        depends.setdefault("killfeed_portrait", killfeed_claim["depends_on"])
    claims = [identity_claim(death_id, agent, channel=ch, depends_on=depends.get(ch))
              for ch, agent in named_votes.items()]
    for w in witnesses:
        ch = w.get("channel")
        if ch in ("killfeed_portrait", "scoreboard_dim") and ch not in named_votes:
            claims.append(identity_claim(death_id, None, channel=ch,
                                         reason=w.get("reason")))
    identity = (adjudicate_agent_identity(claims) or [None])[0]
    status = identity["status"] if identity else "abstained"
    victim = identity["agent"] if identity else None
    reason = None
    if status == "disagreement":
        reason = f"witnesses disagree: {named_votes}"
    elif status == "abstained":
        reason = "no witness provided a confident candidate"

    # Location observability rules:
    # Enemy ability or environmental deaths can be unobserved by the team;
    # in that case, the location is abstained [domain:minimap/environmental-death].
    if side == "enemy" and death_cause in ("ability", "environmental") and location is None:
        if reason is None:
            reason = f"unobserved enemy {death_cause} death location"

    return DeathVerdict(
        death_id=death_id,
        t_ms=t_ms,
        side=side,
        victim=victim,
        killer=killer,
        death_cause=death_cause,
        weapon=weapon,
        location=location,
        killer_location=killer_location,
        status=status,
        is_second_life=is_second_life,
        is_revive=is_revive,
        channels=sorted(set(channels)),
        independent_channels=identity["independent_channels"] if identity else 0,
        witnesses=witnesses,
        reason=reason,
        metadata={
            "is_player_kill": is_player_kill,
            "is_player_death": is_player_death,
            "named_votes": named_votes,
            "identity": identity,
            "killer_identity": killer_identity,
        },
    )


def shrink_events(series: list[dict], side: str) -> list[dict]:
    """Instants where a NAMED agent left the living set.

    Reported per side with the agent that vanished, so it can be matched
    against killfeed death times. An unnamed drop (the count fell but the
    assignment refused) is kept with gone=None and named=False.
    """
    out = []
    previous: set[str] | None = None
    prev_count: int | None = None
    for row in series:
        got = row.get(side)
        if got is None:
            # Check for direct L1 roster columns (alive_ally / alive_enemy)
            count_val = row.get(f"alive_{side}")
            got = {"alive": count_val, "agents": []}
        agents = got.get("agents") or []
        current = set(a for a in agents if a) if agents else None
        count = got.get("alive")

        if previous and current is not None and len(current) < len(previous):
            gone = sorted(previous - current)
            out.append({
                "t_ms": float(row.get("t_ms", 0.0)),
                "side": side,
                "gone": gone or None,
                "margin": got.get("margin"),
                "named": bool(gone),
            })
        elif prev_count is not None and count is not None and count < prev_count:
            # Unnamed drop when count falls without resolved agent set
            out.append({
                "t_ms": float(row.get("t_ms", 0.0)),
                "side": side,
                "gone": None,
                "margin": got.get("margin"),
                "named": False,
            })

        if current:
            previous = current
        if count is not None:
            prev_count = count
    return out


def expand_events(series: list[dict], side: str) -> list[dict]:
    """Instants where a team's living set EXPANDED (e.g. revive or stabilization).

    Reported per side with the agent that returned, or added=None and named=False
    if the count increased without resolved agent identities.
    """
    out = []
    previous: set[str] | None = None
    prev_count: int | None = None
    for row in series:
        got = row.get(side)
        if got is None:
            # Check for direct L1 roster columns (alive_ally / alive_enemy)
            count_val = row.get(f"alive_{side}")
            got = {"alive": count_val, "agents": []}
        agents = got.get("agents") or []
        current = set(a for a in agents if a) if agents else None
        count = got.get("alive")

        if previous and current is not None and len(current) > len(previous):
            added = sorted(current - previous)
            out.append({
                "t_ms": float(row.get("t_ms", 0.0)),
                "side": side,
                "added": added or None,
                "margin": got.get("margin"),
                "named": bool(added),
            })
        elif prev_count is not None and count is not None and count > prev_count:
            # Unnamed increase when count rises without resolved agent set
            out.append({
                "t_ms": float(row.get("t_ms", 0.0)),
                "side": side,
                "added": None,
                "margin": got.get("margin"),
                "named": False,
            })

        if current:
            previous = current
        if count is not None:
            prev_count = count
    return out


def adjudicate_round_deaths(
    session_id: str,
    killfeed_entries: list[dict],
    roster_series: list[dict],
    *,
    tracks: list[dict] = (),
    xmarks: list[dict] = (),
    killer_locations: list[dict] = (),
    revives: list[dict] = (),
    player_agent: Optional[str] = None,
    lineup: Optional[dict] = None,
    gallery: Optional[dict] = None,
    scoreboard_claims: Optional[list] = None,
    max_dt_ms: float = MAX_DEATH_ALIGNMENT_DT_MS,
) -> list[DeathVerdict]:
    """Align killfeed entries to roster drops and minimap tracks across a round.

    `scoreboard_claims`, when given, holds one `scoreboard_death_claims` claim
    per entry, in entry order.
    """
    ally_shrinks = shrink_events(roster_series, "ally")
    enemy_shrinks = shrink_events(roster_series, "enemy")
    ally_expands = expand_events(roster_series, "ally")
    enemy_expands = expand_events(roster_series, "enemy")

    living_agents: dict[str, set[str]] = {}
    if lineup and isinstance(lineup, dict) and "sides" in lineup:
        living_agents = {
            "ally": {r["agent"] for r in lineup["sides"].get("ally", []) if r.get("agent")},
            "enemy": {r["agent"] for r in lineup["sides"].get("enemy", []) if r.get("agent")},
        }

    all_revives = [dict(r) for r in revives]
    eliminated_agents: dict[str, set[str]] = {"ally": set(), "enemy": set()}
    for exp in ally_expands + enemy_expands:
        if exp.get("named") and exp.get("added"):
            for ag in exp["added"]:
                all_revives.append({
                    "t_ms": exp["t_ms"],
                    "side": exp["side"],
                    "agent": ag,
                    "channel": "roster_diff",
                })
        elif not exp.get("named"):
            all_revives.append({
                "t_ms": exp["t_ms"],
                "side": exp["side"],
                "agent": None,
                "channel": "roster_diff",
            })

    verdicts = []
    used_shrinks = set()
    death_ids = []
    for i, kf in enumerate(killfeed_entries):
        side_i = kf.get("side") or ("ally" if kf.get("victim_ally") is True else "enemy" if kf.get("victim_ally") is False else kf.get("victim_side", "enemy"))
        # The stable key when the entry knows its slot; the list index only
        # for callers that never had one, since it moves with detection.
        death_ids.append(death_key(session_id, kf["t_ms"], kf["slot"]) if kf.get("slot") is not None
                         else f"death:{session_id}:{int(float(kf.get('t_ms', 0.0)))}:{side_i}:{i}")
    sorted_revives = sorted(all_revives, key=lambda r: float(r.get("t_ms", 0.0)))
    applied_revives = set()

    for i, kf in enumerate(killfeed_entries):
        t_ms = float(kf.get("t_ms", 0.0))
        side = kf.get("side") or ("ally" if kf.get("victim_ally") is True else "enemy" if kf.get("victim_ally") is False else kf.get("victim_side", "enemy"))
        death_id = death_ids[i]

        # Apply any pending revives prior to this death instant
        for r_item in sorted_revives:
            r_t = float(r_item.get("t_ms", 0.0))
            if r_t <= t_ms and id(r_item) not in applied_revives:
                r_side = r_item.get("side")
                r_ag = r_item.get("agent")
                if not r_ag and eliminated_agents.get(r_side) and len(eliminated_agents[r_side]) == 1:
                    r_ag = next(iter(eliminated_agents[r_side]))
                if r_side and r_ag and r_side in living_agents:
                    living_agents[r_side].add(r_ag)
                    if r_ag in eliminated_agents.get(r_side, set()):
                        eliminated_agents[r_side].discard(r_ag)
                applied_revives.add(id(r_item))

        # If killfeed claim is missing/abstained, and multi-frame compositions + gallery are available:
        # Evaluate with the surviving living candidates
        kf_claim = kf.get("claim")
        v_comps = kf.get("v_comps")
        k_comps = kf.get("k_comps")
        slot = kf.get("slot", 0)
        is_ally = side == "ally"

        if gallery is not None and living_agents.get(side):
            curr_victim_agent = (kf_claim or {}).get("agent")
            if not curr_victim_agent and v_comps is not None:
                cands_victim = sorted(living_agents[side])
                v_claims = []
                for comp in v_comps:
                    if np.all(comp == 0):
                        continue
                    obs = {"composition": comp, "role": "victim", "slot": slot, "ally": is_ally}
                    vc = claim_from_killfeed_portrait(
                        obs,
                        entity_id=f"kf:{int(t_ms)}:victim:{slot}",
                        candidates=cands_victim,
                        gallery=gallery,
                        margin_min=0.07,
                    )
                    v_claims.append(vc)
                v_verdict = _channel_verdict(v_claims)
                v_agent = v_verdict.get("agent")

                curr_killer_agent = (kf_claim or {}).get("killer")
                if not curr_killer_agent and k_comps is not None and lineup:
                    killer_side = "enemy" if side == "ally" else "ally"
                    cands_killer = sorted({r["agent"] for r in lineup["sides"].get(killer_side, []) if r.get("agent")})
                    k_claims = []
                    for comp in k_comps:
                        if np.all(comp == 0):
                            continue
                        obs = {"composition": comp, "role": "killer", "slot": slot, "ally": not is_ally}
                        kc = claim_from_killfeed_portrait(
                            obs,
                            entity_id=f"kf:{int(t_ms)}:killer:{slot}",
                            candidates=cands_killer,
                            gallery=gallery,
                            margin_min=0.07,
                        )
                        k_claims.append(kc)
                    k_verdict = _channel_verdict(k_claims)
                    curr_killer_agent = k_verdict.get("agent")

                if v_agent or curr_killer_agent:
                    kf_claim = {
                        "channel": "killfeed_portrait",
                        "agent": v_agent,
                        "killer": curr_killer_agent,
                    }

        # Match candidate roster shrink on the victim's side within max_dt_ms;
        # a revive removes no one, so it takes none.
        is_revive = revive_entry(kf)
        shrinks = [] if is_revive else ally_shrinks if side == "ally" else enemy_shrinks
        matched_shrink = None
        for si, s in enumerate(shrinks):
            if (side, si) in used_shrinks:
                continue
            if abs(s["t_ms"] - t_ms) <= max_dt_ms:
                matched_shrink = s
                used_shrinks.add((side, si))
                break

        # Match candidate minimap death mark
        matched_xmark = kf.get("location")
        if matched_xmark is None:
            for xm in xmarks:
                if abs(xm.get("t_ms", 0.0) - t_ms) <= max_dt_ms:
                    matched_xmark = (float(xm["x"]), float(xm["y"]))
                    break

        # Match candidate killer location
        matched_killer_loc = kf.get("killer_location")
        if matched_killer_loc is None:
            for kl in killer_locations:
                if abs(kl.get("t_ms", 0.0) - t_ms) <= max_dt_ms:
                    matched_killer_loc = (float(kl["x"]), float(kl["y"]))
                    break

        # Match candidate terminating track on the victim's side
        matched_track = kf.get("track")
        if matched_track is None:
            candidate_tracks = [
                tr for tr in tracks
                if tr.get("side", "enemy" if not tr.get("ally") else "ally") == side
                and -500.0 <= (t_ms - tr.get("last_seen_ms", 0.0)) <= max_dt_ms
            ]
            if len(candidate_tracks) == 1:
                matched_track = candidate_tracks[0]
            elif len(candidate_tracks) > 1:
                # Disambiguate multiple candidate tracks:
                # 1. Spatially closest track if death mark location is known
                if matched_xmark is not None:
                    matched_track = min(
                        candidate_tracks,
                        key=lambda tr: math.hypot(tr["location"][0] - matched_xmark[0], tr["location"][1] - matched_xmark[1]) if tr.get("location") else float("inf")
                    )
                else:
                    # 2. Prefer track that corroborates the killfeed portrait claim if present
                    kf_agent = (kf_claim or {}).get("agent")
                    corroborating = [
                        tr for tr in candidate_tracks
                        if tr.get("agent") and kf_agent and tr.get("agent").lower() == kf_agent.lower()
                    ]
                    if len(corroborating) == 1:
                        matched_track = corroborating[0]
                    else:
                        matched_track = min(candidate_tracks, key=lambda tr: abs(tr.get("last_seen_ms", 0.0) - t_ms))

        is_player_kill = bool(kf.get("kf_player_kill") or kf.get("player_kill"))
        is_player_death = bool(kf.get("kf_player_death") or kf.get("player_death"))
        is_second_life = bool(kf.get("is_second_life") or kf.get("is_run_it_back"))
        badge_metrics = None

        if not is_second_life:
            crop_to_test = kf.get("band_crop")
            if crop_to_test is None and kf.get("crop") is not None:
                crop_to_test = kf["crop"]
            if crop_to_test is not None:
                vr0 = None
                vr_val = kf.get("victim_run")
                if isinstance(vr_val, (list, tuple)) and len(vr_val) > 0:
                    vr0 = vr_val[0]
                has_badge, b_info = detect_second_life_badge(crop_to_test, vr0)
                if has_badge:
                    is_second_life = True
                    badge_metrics = b_info

        death_cause = kf.get("death_cause")
        weapon = kf.get("weapon") or kf.get("ability_name")

        # Weapon / Ability icon classification if icon crop is provided
        if kf.get("icon_crop") is not None and not weapon:
            w_verdict = classify_killfeed_icon(kf["icon_crop"], active_agent=player_agent)
            if w_verdict.status == "resolved" and w_verdict.name:
                weapon = w_verdict.name
                if not death_cause:
                    death_cause = w_verdict.category
                if w_verdict.name in ("Run It Back", "NULL/cmd") or (
                    w_verdict.metadata and w_verdict.metadata.get("asset_stem") in ("Phoenix_Ultimate", "KAY_O_Ultimate")
                ):
                    is_second_life = True
            elif w_verdict.category != "gun" and not death_cause:
                death_cause = w_verdict.category

        # Revive icon fallback if still unclassified
        if kf.get("icon_crop") is not None and not weapon:
            matched_ab, ab_score, ab_info = classify_revive_icon(kf["icon_crop"])
            if matched_ab:
                weapon = f"{matched_ab} Ultimate"
                if not death_cause:
                    death_cause = "ability"
                if matched_ab in ("Phoenix", "KAY/O"):
                    is_second_life = True

        if badge_metrics:
            if kf_claim is None:
                kf_claim = {"channel": "killfeed_badge", "is_second_life": True, "badge": badge_metrics}
            else:
                kf_claim["is_second_life"] = True
                kf_claim["badge"] = badge_metrics

        if not death_cause:
            death_cause = (
                "environmental" if kf.get("is_environmental") or kf.get("is_fall")
                else "ability" if kf.get("is_ability")
                else "gun"
            )

        verdict = adjudicate_death(
            death_id=death_id,
            t_ms=t_ms,
            side=side,
            killfeed_claim=kf_claim,
            killer_claim=kf.get("killer_claim"),
            scoreboard_claim=scoreboard_claims[i] if scoreboard_claims else None,
            victim_depends_on=({"scoreboard_dim": [death_ids[j] for j in
                                scoreboard_claims[i].get("depends_on_entries", [])]}
                               if scoreboard_claims and scoreboard_claims[i].get("depends_on_entries")
                               else None),
            roster_shrink=matched_shrink,
            track_termination=matched_track,
            xmark_location=matched_xmark,
            killer_location=matched_killer_loc,
            death_cause=death_cause,
            weapon=weapon,
            player_agent=player_agent,
            is_player_kill=is_player_kill,
            is_player_death=is_player_death,
            is_second_life=is_second_life,
            is_revive=is_revive,
        )

        # Chronologically update living set for subsequent deaths: a revive
        # returns its victim, a second life removes no one.
        if verdict.status == "resolved" and verdict.victim and verdict.side in living_agents:
            if verdict.is_revive:
                living_agents[verdict.side].add(verdict.victim)
                eliminated_agents[verdict.side].discard(verdict.victim)
            elif not verdict.is_second_life:
                living_agents[verdict.side].discard(verdict.victim)
                eliminated_agents[verdict.side].add(verdict.victim)

        verdicts.append(verdict)

    return verdicts


def death_verdict_to_events(verdict: DeathVerdict, session_id: str) -> list[dict]:
    """Convert a DeathVerdict into formal ENTITY_DELETED and IDENTITY_DISTRIBUTION events."""
    events = []
    if verdict.is_revive:
        # A revive deletes no entity; its portraits still name agents.
        for key in ("identity", "killer_identity"):
            identity = verdict.metadata.get(key)
            if identity and identity["status"] in ("resolved", "disagreement"):
                events.extend(identity_events([identity], session_id, verdict.t_ms))
        return events

    # 1. ENTITY_DELETED event
    deletion_reason = "second_life" if verdict.is_second_life else "eliminated"
    del_event = entity_deleted_event(
        session_id=session_id,
        entity_id=verdict.death_id,
        t_ms=verdict.t_ms,
        deletion_reason=deletion_reason,
        source_channel=SourceChannel.KILLFEED,
        producer_version=DEATH_ADJUDICATION_VERSION,
        metadata={
            "side": verdict.side,
            "victim": verdict.victim,
            "killer": verdict.killer,
            "death_cause": verdict.death_cause,
            "weapon": verdict.weapon,
            "location": list(verdict.location) if verdict.location else None,
            "killer_location": list(verdict.killer_location) if verdict.killer_location else None,
            "status": verdict.status,
            "is_second_life": verdict.is_second_life,
            "independent_channels": verdict.independent_channels,
            "channels": verdict.channels,
            "reason": verdict.reason,
        },
    )
    events.append(del_event.to_dict())

    # 2. IDENTITY_DISTRIBUTION event, from the identity arbiter only.
    for key in ("identity", "killer_identity"):
        identity = verdict.metadata.get(key)
        if identity and identity["status"] in ("resolved", "disagreement"):
            events.extend(identity_events([identity], session_id, verdict.t_ms))

    return events


@dataclass
class TeamRoster:
    """The canonical lineup and current living state for one side."""

    side: str  # "ally" or "enemy"
    canonical_agents: list[str]  # 5 agents in initial slot sequence [0..4]
    living_agents: set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self.living_agents:
            self.living_agents = set(self.canonical_agents)

    @property
    def alive_count(self) -> int:
        return len(self.living_agents)

    def living_sequence(self) -> list[str]:
        """Living agents in canonical slot order (packed inward on HUD)."""
        return [a for a in self.canonical_agents if a in self.living_agents]

    def slot_mapping(self) -> dict[str, int]:
        """Mapping from living agent name to current occupied HUD slot index (0..4).

        Allies pack right towards scoreline: occupied slots are [N_SLOTS - k .. N_SLOTS - 1].
        Enemies pack left towards scoreline: occupied slots are [0 .. k - 1].
        """
        seq = self.living_sequence()
        k = len(seq)
        if self.side == "ally":
            start_slot = N_SLOTS - k
            return {agent: start_slot + idx for idx, agent in enumerate(seq)}
        else:
            return {agent: idx for idx, agent in enumerate(seq)}

    def eliminate(self, agent: str) -> bool:
        """Remove agent on death. Returns True if agent was living."""
        if agent in self.living_agents:
            self.living_agents.remove(agent)
            return True
        return False

    def revive(self, agent: str) -> bool:
        """Restore agent on revive. Returns True if agent belongs to canonical lineup."""
        if agent in self.canonical_agents:
            self.living_agents.add(agent)
            return True
        return False

    def reset(self) -> None:
        """Reset all canonical agents to alive at round start."""
        self.living_agents = set(self.canonical_agents)


@dataclass(frozen=True)
class RoundRosterSnapshot:
    """Instantaneous snapshot of both teams' living rosters."""

    t_ms: float
    round_no: int
    event: str
    ally_alive: int
    ally_agents: list[str]
    ally_role: str  # "attackers" | "defenders"
    enemy_alive: int
    enemy_agents: list[str]
    enemy_role: str  # "attackers" | "defenders"
    ally_slots: dict[str, int] = field(default_factory=dict)
    enemy_slots: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "t_ms": self.t_ms,
            "round_no": self.round_no,
            "event": self.event,
            "ally": {
                "alive": self.ally_alive,
                "agents": list(self.ally_agents),
                "role": self.ally_role,
                "slots": dict(self.ally_slots),
            },
            "enemy": {
                "alive": self.enemy_alive,
                "agents": list(self.enemy_agents),
                "role": self.enemy_role,
                "slots": dict(self.enemy_slots),
            },
        }


class LivingRosterTracker:
    """Tracks living roster state across match rounds, deaths, and revives.

    Maintains the canonical 5-agent sequence per side, handles survivor
    inward packing, side-swaps at half-time (round 13), and revive re-insertion.
    """

    def __init__(
        self,
        lineup: dict,
        local_player: Optional[str] = None,
        starting_role: str = "defenders",
    ):
        self.canonical = {
            "ally": [r["agent"] for r in lineup.get("sides", {}).get("ally", []) if r.get("agent")],
            "enemy": [r["agent"] for r in lineup.get("sides", {}).get("enemy", []) if r.get("agent")],
        }
        self.local_player = local_player
        self.starting_role = starting_role
        self.rosters = {
            "ally": TeamRoster("ally", self.canonical["ally"]),
            "enemy": TeamRoster("enemy", self.canonical["enemy"]),
        }
        self.current_round = 0

    def start_round(self, round_no: int, t_start_ms: float = 0.0) -> RoundRosterSnapshot:
        """Initialize living roster state at round start (all 10 alive)."""
        self.current_round = round_no
        self.rosters["ally"].reset()
        self.rosters["enemy"].reset()
        return self.snapshot(t_ms=t_start_ms, event="round_start")

    def role_of_side(self, side: str, round_no: int) -> str:
        """Attacker/Defender role for side, accounting for halftime flip at round 13."""
        is_first_half = round_no <= 12
        if is_first_half:
            ally_role = self.starting_role
        else:
            ally_role = "attackers" if self.starting_role == "defenders" else "defenders"
        enemy_role = "attackers" if ally_role == "defenders" else "defenders"
        return ally_role if side == "ally" else enemy_role

    def apply_death(self, t_ms: float, side: str, victim: str, is_second_life: bool = False) -> RoundRosterSnapshot:
        """Record death event and update living roster."""
        if not is_second_life:
            self.rosters[side].eliminate(victim)
            event_name = f"death:{victim}"
        else:
            event_name = f"second_life:{victim}"
        return self.snapshot(t_ms=t_ms, event=event_name)

    def apply_revive(self, t_ms: float, side: str, agent: str) -> RoundRosterSnapshot:
        """Record revive event and re-insert agent into canonical living sequence."""
        self.rosters[side].revive(agent)
        return self.snapshot(t_ms=t_ms, event=f"revive:{agent}")

    def living_agents(self, side: str) -> set[str]:
        return set(self.rosters[side].living_agents)

    def living_sequence(self, side: str) -> list[str]:
        return self.rosters[side].living_sequence()

    def snapshot(self, t_ms: float, event: str = "") -> RoundRosterSnapshot:
        return RoundRosterSnapshot(
            t_ms=t_ms,
            round_no=self.current_round,
            event=event,
            ally_alive=self.rosters["ally"].alive_count,
            ally_agents=self.rosters["ally"].living_sequence(),
            ally_role=self.role_of_side("ally", self.current_round),
            enemy_alive=self.rosters["enemy"].alive_count,
            enemy_agents=self.rosters["enemy"].living_sequence(),
            enemy_role=self.role_of_side("enemy", self.current_round),
            ally_slots=self.rosters["ally"].slot_mapping(),
            enemy_slots=self.rosters["enemy"].slot_mapping(),
        )

    def build_round_timeline(
        self,
        round_no: int,
        death_verdicts: list[DeathVerdict],
        t_start_ms: float = 0.0,
        revives: list[dict] = (),
    ) -> list[RoundRosterSnapshot]:
        """Build the complete chronological timeline of living roster snapshots for a round."""
        snapshots = [self.start_round(round_no, t_start_ms)]
        events = []
        for dv in death_verdicts:
            if dv.status == "resolved" and dv.victim:
                events.append({
                    "kind": "death",
                    "t_ms": dv.t_ms,
                    "side": dv.side,
                    "agent": dv.victim,
                    "is_second_life": dv.is_second_life,
                })
        for rev in revives:
            events.append({
                "kind": "revive",
                "t_ms": float(rev["t_ms"]),
                "side": rev["side"],
                "agent": rev["agent"],
            })

        events.sort(key=lambda e: (e["t_ms"], 0 if e["kind"] == "death" else 1))

        for ev in events:
            if ev["kind"] == "death":
                snap = self.apply_death(ev["t_ms"], ev["side"], ev["agent"], is_second_life=ev.get("is_second_life", False))
                snapshots.append(snap)
            elif ev["kind"] == "revive":
                snap = self.apply_revive(ev["t_ms"], ev["side"], ev["agent"])
                snapshots.append(snap)

        return snapshots

    def build_match_timeline(
        self,
        rounds: list[dict],
    ) -> list[RoundRosterSnapshot]:
        """Build the complete chronological timeline of living roster snapshots across a full match.

        Each entry in `rounds` is a dict with:
        - round_no: int
        - t_start_ms: float
        - death_verdicts: list[DeathVerdict]
        - revives: optional list[dict]

        Handles round transitions, 10-player alive resets, and halftime role flips (round 13).
        """
        all_snapshots = []
        for r_info in sorted(rounds, key=lambda r: r["round_no"]):
            round_no = r_info["round_no"]
            t_start_ms = float(r_info.get("t_start_ms", 0.0))
            d_verdicts = r_info.get("death_verdicts", [])
            r_revives = r_info.get("revives", [])
            snaps = self.build_round_timeline(
                round_no=round_no,
                death_verdicts=d_verdicts,
                t_start_ms=t_start_ms,
                revives=r_revives,
            )
            all_snapshots.extend(snaps)
        return all_snapshots

    def to_events(
        self,
        session_id: str,
        snapshots: Optional[list[RoundRosterSnapshot]] = None,
    ) -> list[dict]:
        """Convert snapshots into formal Reticle events."""
        if snapshots is None:
            snapshots = [self.snapshot(0.0, "current_state")]

        events = []
        for snap in snapshots:
            if snap.event == "round_start":
                ev = session_boundary_event(
                    session_id=session_id,
                    t_ms=snap.t_ms,
                    boundary_type="round_start",
                    round_no=snap.round_no,
                    source_channel=SourceChannel.ROUNDS,
                    producer_version=DEATH_ADJUDICATION_VERSION,
                    metadata=snap.to_dict(),
                )
                events.append(ev.to_dict())
            elif snap.event.startswith("death:"):
                victim = snap.event.split(":", 1)[1]
                ev = entity_deleted_event(
                    session_id=session_id,
                    entity_id=f"roster:player:{victim}",
                    t_ms=snap.t_ms,
                    deletion_reason="eliminated",
                    source_channel=SourceChannel.ROSTER,
                    producer_version=DEATH_ADJUDICATION_VERSION,
                    metadata=snap.to_dict(),
                )
                events.append(ev.to_dict())
            elif snap.event.startswith("revive:"):
                agent = snap.event.split(":", 1)[1]
                ev = entity_state_event(
                    session_id=session_id,
                    entity_id=f"roster:player:{agent}",
                    t_ms=snap.t_ms,
                    position=(0.0, 0.0),
                    state=EntityState.REVIVED,
                    source_channel=SourceChannel.ROSTER,
                    producer_version=DEATH_ADJUDICATION_VERSION,
                    metadata=snap.to_dict(),
                )
                events.append(ev.to_dict())
        return events


def build_round_roster_timeline(
    lineup: dict,
    death_verdicts: list[DeathVerdict],
    round_no: int,
    t_start_ms: float = 0.0,
    revives: list[dict] = (),
    starting_role: str = "defenders",
) -> list[RoundRosterSnapshot]:
    """Convenience helper to build a round's living roster timeline."""
    tracker = LivingRosterTracker(lineup, starting_role=starting_role)
    return tracker.build_round_timeline(round_no, death_verdicts, t_start_ms, revives=revives)


def build_match_roster_timeline(
    lineup: dict,
    rounds: list[dict],
    starting_role: str = "defenders",
) -> list[RoundRosterSnapshot]:
    """Convenience helper to build a full match's living roster timeline."""
    tracker = LivingRosterTracker(lineup, starting_role=starting_role)
    return tracker.build_match_timeline(rounds)


#: Exemplar passes before giving up on the exemplar set settling.
MAX_EXEMPLAR_PASSES = 4


def adjudicate_session_deaths(session_id: str, rounds: list[dict], hud_table, roster_table,
                              portraits: list[dict], board_rows: list[dict], lineup: dict,
                              gallery: dict, *, source_version: str,
                              second_life: list[dict] | None = None,
                              weapon_observations: list[dict] | None = None) -> dict:
    """Every round's deaths from stored data only; decodes no video.

    Per round: the stored killfeed portraits against the official art, then the
    scoreboard's dimmed rows gated on the roster (`scoreboard_death_claims`).
    `portrait_exemplars` then takes the portraits of every death a non-portrait
    witness named, and the next pass also scores against those, never an
    entry's own, until the exemplar set stops changing. Returns the entries and
    verdicts per round of the last pass and the number of passes.

    `weapon_observations` are the stored `killfeed_weapon` rows; given them,
    `adjudication.weapon.entry_weapon` names each entry's weapon or ability and
    the entry carries its evidence. Without them no weapon is named, and no
    entry is a revive (`revive_entry`).
    """
    from ..reconciliation import audit_board_alive, contradicted_openings
    from .scoreboard import scoreboard_openings
    from ..rounds import in_round_window
    hud, roster = hud_table.to_pydict(), roster_table.to_pylist()
    player_agent = (lineup.get("player") or {}).get("agent")
    entries = session_entries(hud, second_life)
    # Both sides: an icon's caster may be on either team (a revive, a team kill).
    agents = {r["agent"] for side in (lineup.get("sides") or {}).values()
              for r in side if r.get("agent")}
    if weapon_observations is not None:
        for e in entries:
            ev = entry_weapon(e, weapon_observations, agents=agents or None)
            e["weapon_evidence"] = ev
            if ev["status"] == "resolved":
                e["weapon"] = ev["name"]
                e["death_cause"] = ev["category"]
    ends = {r["t_end_ms"] for r in rounds}
    base = [(r, in_round_window(entries, r["t_start_ms"], r["t_end_ms"],
                                r.get("t_close_ms") or r["t_end_ms"], ends)) for r in rounds]
    exemplars, keys, n = [], None, 0
    while True:
        results = []
        for r, raw in base:
            a, z = r["t_start_ms"], r.get("t_close_ms") or r["t_end_ms"]
            entries = attach_stored_killfeed_portraits(raw, portraits, lineup, gallery,
                                                       source_version=source_version,
                                                       exemplars=exemplars)
            window = [row for row in roster if a <= row["t_ms"] <= z]
            first = adjudicate_round_deaths(session_id, entries, window,
                                            player_agent=player_agent)
            openings = scoreboard_openings([row for row in board_rows
                                            if a <= float(row.get("t_ms", -1)) <= z])
            board = scoreboard_death_claims(
                entries, openings, {i: v.victim for i, v in enumerate(first)},
                {i for i, v in enumerate(first) if v.is_second_life},
                contradicted_openings(audit_board_alive(openings, hud_table, roster_table)))
            verdicts = adjudicate_round_deaths(session_id, entries, window,
                                               player_agent=player_agent,
                                               scoreboard_claims=board)
            results.append({"round_no": r["round_no"], "entries": entries, "verdicts": verdicts})
        n += 1
        harvested = portrait_exemplars([v for x in results for v in x["verdicts"]],
                                       [e for x in results for e in x["entries"]])
        new = {x["observation_key"] for x in harvested}
        if new == keys or n >= MAX_EXEMPLAR_PASSES:
            return {"rounds": results, "passes": n}
        keys, exemplars = new, harvested

