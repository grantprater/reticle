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

Owns [owns:death-victim]. Also owns [owns:killfeed-entry-type]: which of
the three entry types an entry is (`entry_type`, which `decide_entry_type`
decides over every revive witness's claim: the icon, the ring, the plates and
the context gate) and which agent acts in it (`entry_actor`).
"""
from __future__ import annotations

import bisect
import math
from collections import Counter
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
from ..usage import step
from .identity import (NAME_CLUSTER_CHANNEL, adjudicate_agent_identity,
                       claim_from_killfeed_portrait, identity_claim, identity_events,
                       side_candidates, _channel_verdict)
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
# 0.12.0 (2026-09-25): an entry's portrait views follow it up the stack by its
# own key (`follow_entry_portraits`), not its first slot until the next entry;
# a refusing view abstains, and two agreeing named views name the entry.
# 0.13.0 (2026-09-26): a final pass replaces each role's per-entry portrait
# vote with its name cluster's claim where the cluster is named
# (`killfeed_names`, `identity.name_cluster_claims`); fragments keep the vote.
# 0.14.0 (2026-09-26): an entry whose icon names nothing is a revive when most
# of its views read killer and victim plates on one side and the victim's side
# fields a reviver (`plate_revive`); a named weapon vetoes the plates, and a
# self entry, whose killer and victim print one name, is not a revive
# (`killfeed_names.self_entry`).
# 0.15.0 (2026-09-28): the board interval closes ON its closing opening: an
# entry whose onset equals that opening's time counts toward it, since the board
# at that frame already dims its victim (a1a995e6b19b 1656.0 s, ff636d173b07
# 2255.5 s, 587c15b07779 776.5 s; docs/VICTIM_DISAGREEMENTS.md).
# 0.16.0 (2026-09-28): the board names no death by elimination in an interval
# whose independent names repeat an agent; each claim refuses with
# `elimination_collision`, and the collision is stored as its own row
# (`board_collisions`), since elimination copied the repeated name's error to
# both deaths (223d636bf8d2 817.0 and 820.5 s; docs/VICTIM_DISAGREEMENTS.md).
# 0.17.0 (2026-09-28): a death carrying the repeated name is CONTESTED, not
# named by the killfeed alone: the board's claim carries a `contest` with both
# names, and the arbiter resolves it only on a channel outside
# `COLLISION_IMPLICATED` (the player HUD, a minimap track). 0.16.0 turned five
# of twelve flagged deaths into silent errors.
# 0.18.0 (2026-09-28): an entry track ends where its victim plate's side flips
# (`checks.track_entries` given `sides`), unless it has read a one-colour
# banner; the player's death at 59c70f1ef720 moves from the enemy-victim entry
# at 1619.5 s to the ally-victim one at 1625.0 s (E1; stamped 0.15.0 on
# e1-agreement-20260927, renumbered on landing above master's 0.17.0).
# 0.19.0 (2026-09-28): a name-cluster role whose two views read no name tries
# its other followed views (`killfeed-name-cluster-0.2.0`); 223d636bf8d2's
# victim at 335.5 s joins its player's cluster and is named Fade, not Iso.
# 0.20.0 (2026-09-29): an entry that rises into the slot an expired entry
# vacated keeps its own track (`checks.track_entries`, the stack rule
# [domain:killfeed/stack-order]), where their dividers and victim sides agree;
# the player's death at 043bafca271a 1506.5 s now runs to 1511.0 s and the
# entry above it ends at 1505.0 s.
# 0.21.0 (2026-09-30): a death takes its location from a stored minimap X
# (`xmark_births` over the `minimap_object` stream): an X of the victim's
# side's colour, shape-confirmed (`minimap_x_marks`), born at the killfeed
# time where an icon of that side ended at its place
# [domain:minimap/death-icon-becomes-mark]. Exactly one such birth places the
# death; two or more leave it unplaced. The first matcher took any mark of
# either colour inside `max_dt_ms`, and no caller passed one.
# 0.22.0 (2026-10-01): a player kill or death track joins the entry whose
# divider agrees at the track's onset, not at the entry track's last read
# (`session_entries`); bdfdcf009dba 294.0 s and 3694746e4e54 1454.0 s become
# the player's kills, their entry tracks having run on into a later entry.
# 0.23.0 (2026-10-01): the final pass names each entry's weapon again with
# its acting role's agent (`entry_actor`, the arbiter over the left name's
# claims without the icon's) narrowing the candidates to that agent's kit
# (`adjudication.weapon.entry_weapon`, weapon-adjudication-0.7.0). An ability
# the kit shaped yields a caster claim that depends on the actor's entity.
# 0.24.0 (2026-10-01): KAY/O's NULL/cmd in the weapon slot marks a revive
# entry (`REVIVE_ICONS`), and its icon makes no caster claim on the reviver
# (weapon-adjudication-0.8.0).
# 0.25.0 (2026-10-01): every revive witness is its own claim on the entry
# (`entry_witnesses`): the icon the weapon owner names, the weapon-slot ring
# (`ringed`, killfeed-weapon-0.5.0) and the one-colour plates, with a context
# gate (`revive_context`: a reviver fielded, a prior death on the side, a
# named Sage dead, KAY/O's named down). `decide_entry_type` publishes the type
# with its alternatives; a disagreement refuses with its reason and is stored
# (`entry_type`), where one witness ("icon" or "plates") decided before.
# 0.26.0 (2026-10-02): an entry track never takes a detection above an entry
# it was below that still reads (`checks.track_entries`, the order rule
# [domain:killfeed/stack-order]). At bdfdcf009dba 674.0 s an entry whose
# divider sat unread under the Shooting Error overlay took the entry above's
# seam misread two slots up, past Me -> Waylay; two false deaths followed.
# An entry whose victim plate went unread where it appeared takes the first
# side its own track read (`session_entries`), not "unknown".
# 0.27.0 (2026-10-03): an entry's follow keys on the in-window frame of its
# first slot whose key the longest follow fits, not on its first frame, whose
# crop edge the slide-in or a second edge reading often moves
# (`follow_entry_portraits`); the first frame still binds. On five matches
# 13 killers and 6 victims refused before were named, none wrongly.
# 0.28.0 (2026-10-03): no entry track outlives one entry
# [domain:killfeed/entry-lifetime]: `checks.track_entries` cuts a welded track
# at the sample its slot missed, else at the divider's step or one life in,
# and refuses a cut-off piece shorter than a life that read no divider
# (`weld_fragment`). Over the 21 Riot-scored matches, in memory: missed
# deaths 58 -> 33, false deaths 50 -> 49; all 26 deaths missed as two entries
# welded into one track match. b3b9defb6fd7 1661 s trades a match for a false
# death: its slot-5 phantom reads no longer carry the entry below them.
# 0.29.0 (2026-10-03): an entry whose first slot shows no killer portrait
# within `FOLLOW_START_MS` seeds its portrait follow from its own hud track's
# reads (`session_entries` `reads`, `entry_follow` seed "track"); the claim's
# evidence names the seed and rests on the track. Over the 21 Riot-scored
# matches, in memory: of 43 killers refused with no_stored_portrait_at_entry,
# 36 are named right and 1 wrong (b3b9defb6fd7 1573.0 s, a Vyse portrait read
# Clove); killer refused 88 -> 51, victim refused 75 -> 62. One victim turns
# right -> refused: 223d636bf8d2 1868.5 s now reads Reyna for Clove, and the
# board's collision contests Reyna at 1866.0 s.
# 0.30.0 (2026-10-03): the portrait channel names from the art ZNCC
# (killfeed-portrait-0.12.0, agent-identity-0.10.0), with a "none of them"
# hypothesis; the two-view unanimous rule stands.
# 0.31.0 (2026-10-03): the hud track places an entry's portrait views and the
# key only confirms them (`entry_follow_evidence`); the queue rule filters the
# track (`entry_slot_path`), and a view the key fits where the track or the
# victim plate contradicts the entry is stored as a surprise, never bound.
# The first-slot seed bound the newcomer that rose into the slot the entry had
# left (043bafca271a 578.0 s) or that the slide-in misread placed it in
# (3694746e4e54 1638.0 s).
# 0.32.0 (2026-10-03): a death whose victim name agrees with an earlier
# death's, inside one entry life and the queue, is that entry's second track
# and merges into it, stored with its evidence (`merge_split_entries`; ten
# split duplicates over the 21 Riot-scored matches, each a new divider read
# after a rise or a misread); a death no channel names and nothing else
# observes is refused (`refuse_unwitnessed`: recap panels, the round-start
# banner, scenery). Capture-stall spans (stalls-0.2.0) count an entry drawn
# at a stall's release (`checks.track_entries`) and discount stall time in
# the merge.
# 0.33.0 (2026-10-03): every entry votes its own second life from the badge rows
# read at its admitted track reads (`entry_second_life`), not only the entry a
# player death track owns; the player track's window vote counts only the
# player's own rows. Rows store the vote as `second_life_vote`.
# 0.34.0 (2026-10-03): a round that ended by elimination inside a capture
# stall's gap kills every member of the losing side the killfeed prior holds
# alive before the gap (`infer_stall_deaths`): `inferred_death` rows with the
# gap as their window, no time and no killer, resting on the prior's deaths
# and the round's outcome claim (`adjudication.round_outcome`).
# 0.35.0 (2026-10-04): name clusters join a name read whole and cut at its
# word gap (`killfeed-name-cluster-0.3.0`); a revive drawn below a split
# track's later piece no longer blocks the merge (`same_entry`); an entry
# whose victim side went unread takes only a roster drop no sided entry took
# (`_match_shrinks`).
# 0.35.1 (2026-10-04): name clusters from `killfeed-name-cluster-0.5.1`,
# through three cluster changes since 0.35.0's 0.3.0:
# * `killfeed-name-cluster-0.4.0` makes every row change: a crop read once
#   joins only the one recurring group it links to, never another crop read
#   once. On 043bafca271a and c62c2b06bcfb one killer crop read once each no
#   longer joins its name (it linked only another crop read once), so its
#   killer rests on the portrait alone, naming the same agent; beyond
#   version stamps,
#   [metric:riot_residuals/death_rows_cc7_dff#member_count_rows=67] death
#   rows there differ from 0.35.0 in the cluster's member count and
#   [metric:riot_residuals/death_rows_cc7_dff#killer_channel_rows=2] in the
#   killer's channel, and the two sessions'
#   [metric:riot_residuals/death_rows_cc7_dff#summary_rows=2] summary rows
#   differ too; no name and no Riot score changes.
# * `killfeed-name-cluster-0.5.0` and `-0.5.1` guard every bridge between two
#   recurring names, a junk crop or a shared word, and change no row on the
#   21 Riot matches.
# `entry_victim_side` owns the victim-side rule `_match_shrinks` and
# `adjudicate_round_deaths` restated.
DEATH_ADJUDICATION_VERSION = "death-adjudication-0.35.1"

#: Channels an elimination collision implicates: the two killfeed readings
#: that repeated a name, the board that dimmed another agent, and the roster
#: difference, whose name comes from a living set the earlier killfeed
#: verdicts built. Only a channel outside these confirms a contested name.
COLLISION_IMPLICATED = ("killfeed_portrait", "killfeed_name_cluster", "scoreboard_dim",
                        "roster_diff")

#: Weapon-slot icons that mark a revive entry, which is not a death
#: [domain:killfeed/revive-entries]: by icon, the agent the entry's side must
#: field, the reviver for Not Dead Yet and Resurrection and the revived KAY/O
#: for NULL/cmd, whose revive entry any teammate makes
#: [domain:killfeed/kayo-downed-entry]. The icon is the witness; the top bar
#: is not one for Clove, whose death it never shows when Not Dead Yet follows
#: within two seconds.
REVIVE_ICONS = {"Not Dead Yet": "Clove", "Resurrection": "Sage", "NULL/cmd": "KAY_O"}
MAX_DEATH_ALIGNMENT_DT_MS = 2500.0


#: How far the killer crop's left edge and the weapon icon's box width may move
#: between frames of one entry, and how soon the entry must be seen in its
#: first slot for the follow to start.
FOLLOW_X0_TOL = 4
FOLLOW_WIDTH_TOL = 3
FOLLOW_START_MS = 1000.0


def follow_entry_portraits(entry: dict, portraits: list[dict],
                           icon_width: dict | None = None,
                           others: list[dict] | None = None) -> set[tuple[float, int]]:
    """The (frame time, slot) pairs one killfeed entry occupies over its track;
    `entry_follow` without its seed."""
    return entry_follow_evidence(entry, portraits, icon_width, others)["bound"]


def entry_follow(entry: dict, portraits: list[dict], icon_width: dict | None = None,
                 others: list[dict] | None = None
                 ) -> tuple[set[tuple[float, int]], str | None]:
    """`entry_follow_evidence`'s bound views and seed."""
    ev = entry_follow_evidence(entry, portraits, icon_width, others)
    return ev["bound"], ev["seed"]


def entry_slot_path(entry: dict, others: list[dict] | None = None
                    ) -> tuple[list[tuple[float, int]] | None, list[dict]]:
    """The entry's hud track reads (`session_entries` `reads`) that the queue
    rule admits, and a surprise for each read it rejects; (None, []) for an
    entry without reads.

    New entries land at the bottom and an entry never moves down; when an
    entry above expires, every entry below rises one slot
    [domain:killfeed/stack-order]. So a read below the entry's last admitted
    slot is a surprise (`slot_fell`), and with the session's other tracks
    (`others`) every rise must be paid for by an older track that expired
    since this entry arrived: the slots risen since the first admitted read
    never exceed the older tracks whose last read precedes the rise. When
    an unpaid rise is paid once the arrival slot's reads are dropped, and
    those reads all lie within `FOLLOW_START_MS` of arrival, they are the
    slide-in reading the entry a slot low and are rejected
    (`arrival_slot_contradicts_queue`): 3694746e4e54 1638.0 s read slot 2
    with one entry above; 043bafca271a 759.5 s read 2, 1, then 0 after the
    one entry above expired. Otherwise the unpaid read is rejected
    (`rise_without_expiry`).
    """
    reads = sorted((float(t), int(s)) for t, s in entry.get("reads") or ())
    if not reads:
        return None, []
    t_first = float(entry["t_first"])
    older = None
    if others is not None:
        older = sorted(float(o["t_last"]) for o in others
                       if o is not entry and o.get("t_last") is not None
                       and (float(o["t_first"]), int(o["slot"])) < (t_first, int(entry["slot"]))
                       and float(o["t_last"]) >= t_first)
    kept, surprises = [reads[0]], []
    for t, s in reads[1:]:
        last = kept[-1][1]
        if s > last:
            surprises.append({"t_ms": t, "slot": s, "reason": "slot_fell", "from_slot": last})
            continue
        if s < last and older is not None:
            paid = sum(1 for u in older if u < t)
            if kept[0][1] - s > paid:
                run = [k for k in kept if k[1] == kept[0][1]]
                rest = kept[len(run):]
                if (run[-1][0] - t_first <= FOLLOW_START_MS
                        and (rest[0][1] if rest else s) - s <= paid):
                    surprises.extend({"t_ms": u, "slot": k, "reason":
                                      "arrival_slot_contradicts_queue", "risen_to": s}
                                     for u, k in run)
                    kept = rest
                else:
                    surprises.append({"t_ms": t, "slot": s, "reason": "rise_without_expiry",
                                      "from_slot": last})
                    continue
        kept.append((t, s))
    return kept, surprises


#: Views a portrait's best match must hold, to the follow's end, before the
#: change is taken for a successor entry rather than a misread.
FOLLOW_TAIL_MIN_VIEWS = 2


def _cut_changed_tail(bound: set[tuple[float, int]], tops: dict, t_first: float
                      ) -> tuple[set[tuple[float, int]], list[dict]]:
    """`bound` without a tail whose victim or killer portrait's best art
    match changed and held to the end, with a surprise for each view cut.

    One entry's victim and killer never change. A hud track can run on into
    the next entry in the same slot when both share a divider column, and no
    gap or second full life lets `checks._weld_cuts` cut it (bfad2778a372
    2227.0 s: Sage -> Fade, then Sage -> Miks risen into its slot, both
    divider 175 px, one 6.5 s track). Placed by that track, the follow bound
    the successor's views. A change to a new agent that holds for at least
    `FOLLOW_TAIL_MIN_VIEWS` views to the follow's end, after as many views
    past the slide-in (`FOLLOW_START_MS`) agreed on one agent, is that
    successor; a change that reverts, or that follows only slide-in views,
    is a misread, stays bound, and the unanimous
    rule weighs it (`_portrait_channel`). The best match is the reader's raw art
    score, compared only with this entry's own views, never a verdict.
    """
    views = sorted(bound)
    cut_at = None
    for role in ("victim", "killer"):
        named = [(t, s, tops[(t, s, role)]) for t, s in views if (t, s, role) in tops]
        if len(named) <= FOLLOW_TAIL_MIN_VIEWS:
            continue
        last, k = named[-1][2], len(named) - 1
        while k > 0 and named[k - 1][2] == last:
            k -= 1
        # The tail's agent is new to the entry, and the head had settled on
        # one agent after the slide-in: a return to an earlier agent ends a
        # misread, and views within `FOLLOW_START_MS` of arrival catch the
        # slide-in (043bafca271a 744.5 s, one view; 5822b6646448 1258.0 s,
        # two views read Skye before the killer settled as Sage).
        head = {a for _, _, a in named[:k]}
        settled = Counter(a for t, _, a in named[:k] if t > t_first + FOLLOW_START_MS)
        if (k > 0 and len(named) - k >= FOLLOW_TAIL_MIN_VIEWS and last not in head
                and settled and max(settled.values()) >= FOLLOW_TAIL_MIN_VIEWS):
            t_change = named[k][0]
            cut_at = t_change if cut_at is None else min(cut_at, t_change)
    if cut_at is None:
        return bound, []
    return ({v for v in bound if v[0] < cut_at},
            [{"t_ms": t, "slot": s, "reason": "portrait_changed_to_end"}
             for t, s in views if t >= cut_at])


def entry_follow_evidence(entry: dict, portraits: list[dict], icon_width: dict | None = None,
                          others: list[dict] | None = None) -> dict:
    """The (frame time, slot) pairs one killfeed entry occupies over its track
    (`bound`), where the follow was seeded (`seed`: `"first_slot"`, `"track"`
    or None), and the surprises the follow met (`surprises`).

    **An entry does not keep its slot.** The stack rises as older entries
    expire, and a newer entry arrives BELOW [domain:killfeed/stack-order].
    Reading only the first slot until
    the next entry lost every view after the stack rose, and ended the window
    at a newcomer that never moved this entry: 25 of 51 nameable killers on the
    player's uniform labels abstained on one view where up to four existed
    (2026-09-25). Borrowing `adjudication.weapon.bind_entry` instead drifted
    onto the next entry, which two entries with one gun share.

    So the entry is followed by its own key: the killer crop's left edge (set by
    the killer's name and the icon), the weapon icon's box width from the same
    frame and slot (`icon_width`, when stored), and the killer's plate side.
    Each frame it stays or rises one slot. A frame where both slots fit the
    key is ambiguous and binds nothing: that surprise is where a neighbour
    would be taken for it.

    **The key is the one the entry's track supports.** The first frame's
    crop edge is often not the entry's lasting one: the slide-in catches it
    mid-animation (x0 61, then 16 16 16 at 043bafca271a 500.0 s; 142, then
    32 32 at 744.5 s), and some entries' edges alternate between two readings
    (144 and 130 at 587c15b07779 254.5 s). A key taken there fits no later
    frame: 63 killer and 15 victim entries over 21 matches were refused on one
    view (2026-10-03). So every seed in the first seed's slot within
    `FOLLOW_START_MS` proposes a key and is followed, and the longest follow
    wins, the earliest on a tie; the first seed binds as before. A proposal
    stops at the first frame where an earlier follow has the entry risen: from
    then on the slot holds a newer entry, whose longer track would otherwise be
    taken for this one (043bafca271a 153.5 s).

    **The hud track places the entry; the key only confirms it.** The track
    (`session_entries` `reads`) follows the entry's slot as it rises; the
    queue rule filters it (`entry_slot_path`). The seeds are the admitted
    reads that hold a stored killer portrait, and each frame's follow may
    take only the slot the track read then, or, between reads, the slot of
    the read before or after. Seeding from the entry's first slot for
    `FOLLOW_START_MS` regardless of the track bound the newcomer that rose
    into the slot after the entry had left it: at 043bafca271a 578.0 s the
    entry arrived at slot 1 and rose to 0 by 579.0 s, before slot 1 showed a
    portrait; the follow took Phoenix -> Sova at slot 1. At 3694746e4e54
    1638.0 s the slide-in read the entry at slot 2 and the follow took the
    next entry, Reyna -> Cypher, which arrived there at 1639.0 s. A view the
    key fits in a slot the track contradicts, or whose victim plate reads the
    other side from the entry's, is stored as a surprise (`surprises`) and
    never bound. Such a follow rests on the hud track, which the caller
    declares (`attach_stored_killfeed_portraits`) unless the seed is the
    entry's first slot within `FOLLOW_START_MS` of arrival (`"first_slot"`).
    A tail of views whose portraits changed to another agent and held to
    the end is a successor the track ran on into; it is cut and stored
    (`_cut_changed_tail`).

    An entry without `reads` keeps the earlier rule: it is seeded from its
    first slot within `FOLLOW_START_MS`, and stays or rises by its key alone.
    An entry whose admitted reads hold no portrait binds nothing.
    """
    icon_width = icon_width or {}
    by: dict[float, dict[int, tuple]] = {}
    victim_side: dict[tuple[float, int], Any] = {}
    tops: dict[tuple[float, int, str], str] = {}
    for p in portraits:
        if not entry["t_first"] <= float(p["t_ms"]) <= entry["t_last"]:
            continue
        if p.get("art_zncc") and not p.get("art_reason"):
            tops[(float(p["t_ms"]), p["slot"], p.get("role"))] = max(
                p["art_zncc"], key=p["art_zncc"].get)
        if p.get("role") == "killer" and "x0" in p:
            by.setdefault(float(p["t_ms"]), {})[p["slot"]] = (
                p["x0"], icon_width.get((float(p["t_ms"]), p["slot"])), p.get("ally"))
        elif p.get("role") == "victim" and p.get("ally") is not None:
            victim_side[(float(p["t_ms"]), p["slot"])] = (
                "ally" if p["ally"] is True else "enemy")
    path, surprises = entry_slot_path(entry, others)
    side = entry.get("side") if entry.get("side") in ("ally", "enemy") else None

    if path:
        at = dict(path)
        path_t = [t for t, _ in path]

        def allowed(t: float) -> set[int]:
            if t in at:
                return {at[t]}
            i = bisect.bisect_left(path_t, t)
            return ({at[path_t[i - 1]]} if i else set()) | (
                {at[path_t[i]]} if i < len(path_t) else set())
    else:
        allowed = None

    def fits(here: dict, slot: int, key: tuple) -> list[int]:
        return [s for s in (slot, slot - 1) if s in here
                and abs(here[s][0] - key[0]) <= FOLLOW_X0_TOL and here[s][2] == key[2]
                and (here[s][1] is None or key[1] is None
                     or abs(here[s][1] - key[1]) <= FOLLOW_WIDTH_TOL)]

    times = sorted(by)
    index = {t: i for i, t in enumerate(times)}

    def follow(t0: float, s0: int) -> tuple[set[tuple[float, int]], list[dict]]:
        s, key, out, met = s0, by[t0][s0], {(t0, s0)}, []
        for t in times[index[t0] + 1:]:
            here = by[t]
            fit = fits(here, s, key)
            ok = allowed(t) if allowed is not None else None
            for f in fit:
                if ok is not None and f not in ok:
                    met.append({"t_ms": t, "slot": f, "reason": "slot_contradicts_track",
                                "track_slots": sorted(ok)})
                elif side and victim_side.get((t, f), side) != side:
                    met.append({"t_ms": t, "slot": f, "reason": "victim_side_contradicts_entry",
                                "observed_side": victim_side[(t, f)]})
            fit = [f for f in fit if (ok is None or f in ok)
                   and (not side or victim_side.get((t, f), side) == side)]
            if len(fit) != 1:
                continue
            s = fit[0]
            key = (here[s][0], key[1] if here[s][1] is None else here[s][1], key[2])
            out.add((t, s))
        return out, met

    def propose(seeds: list[tuple[float, int]]) -> tuple[set[tuple[float, int]], list[dict]]:
        # Each seed in the first seed's slot within the window proposes a key,
        # until a follow shows the entry has risen: from then on a newer entry
        # holds that slot.
        tracks, risen = [], math.inf
        t_start, slot = seeds[0]
        for t, s in seeds:
            if t > t_start + FOLLOW_START_MS or t >= risen or s != slot:
                break
            tracks.append(follow(t, s))
            risen = min([risen] + [u for u, s_ in tracks[-1][0] if s_ < slot])
        best = max(tracks, key=lambda x: len(x[0]))
        met = {(m["t_ms"], m["slot"], m["reason"]): m for m in tracks[0][1] + best[1]}
        return best[0] | tracks[0][0], [met[k] for k in sorted(met)]

    def seeded_ok(t: float, s: int) -> bool:
        return not side or victim_side.get((t, s), side) == side

    if path is None:
        first = [(t, entry["slot"]) for t in times
                 if t <= entry["t_first"] + FOLLOW_START_MS and entry["slot"] in by[t]]
        if first:
            bound, met = propose(first)
            return {"bound": bound, "seed": "first_slot", "surprises": surprises + met}
        return {"bound": set(), "seed": None, "surprises": surprises}
    seeds = []
    for t, s in path:
        if t in by and s in by[t]:
            if seeded_ok(t, s):
                seeds.append((t, s))
            else:
                surprises.append({"t_ms": t, "slot": s, "reason": "victim_side_contradicts_entry",
                                  "observed_side": victim_side[(t, s)]})
    if not seeds:
        return {"bound": set(), "seed": None, "surprises": surprises}
    bound, met = propose(seeds)
    bound, cut = _cut_changed_tail(bound, tops, float(entry["t_first"]))
    met = met + cut
    t0, s0 = seeds[0]
    seed = ("first_slot" if s0 == entry["slot"] and t0 <= entry["t_first"] + FOLLOW_START_MS
            else "track")
    # A seed the victim plate refused is met again by the follow: one surprise.
    once = {(m["t_ms"], m["slot"], m["reason"]): m for m in surprises + met}
    return {"bound": bound, "seed": seed, "surprises": [once[k] for k in sorted(once)]}


def attach_stored_killfeed_portraits(
    entries: list[dict], observations: list[dict], lineup: dict, gallery: dict,
    *, source_version: str, exemplars: list[dict] = (),
    weapon_observations: list[dict] | None = None,
) -> list[dict]:
    """Join raw portraits to their entry without reading media.

    An entry carrying its track (`t_first`, `t_last`, from `session_entries`)
    takes the views `entry_follow_evidence` binds, with the icon widths from
    `weapon_observations` and the other entries as the queue
    (`entry_slot_path`); one without a track takes its first slot until the
    next entry, at most 2 s. Each claim's evidence carries the follow's `seed`
    (None without a track) and the follow's surprises (`follow_surprises`);
    one seeded from the entry's hud track declares `rests_on` that track in
    its evidence. A single named frame is retained as evidence but
    cannot promote a name: its appearance has no within-entry repeat check.
    At least two views must name, and every view that names must name the same
    admitted lineup candidate, before this channel publishes a name; a view
    that refuses abstains. Refused lineup slots stay rivals in every comparison,
    including after earlier deaths.

    `exemplars` (`portrait_exemplars`) widen each agent's references with this
    session's own labelled portraits, never the entry's own; a name one of
    them decided carries `depends_on` on the death that labelled it.
    """
    out = []
    portraits = [r for r in observations if r.get("kind") == "portrait_observation"]
    widths = icon_widths(weapon_observations)
    for i, original in enumerate(entries):
        entry = dict(original)
        start = float(entry["t_ms"])
        slot, views, seed, surprises = entry.get("slot"), portraits, None, None
        if entry.get("t_last") is not None and entry.get("t_first") is not None:
            ev = entry_follow_evidence(entry, portraits, widths, others=entries)
            bound, seed, surprises = ev["bound"], ev["seed"], ev["surprises"]
            views = [dict(p, slot=slot) for p in portraits
                     if (float(p["t_ms"]), p["slot"]) in bound]
            end = max((t for t, _ in bound), default=start) + 1.0
        else:
            end = min(start + 2000.0,
                      float(entries[i + 1]["t_ms"]) if i + 1 < len(entries) else float("inf"))
        side = entry.get("side")
        # A revive's reviver sits on the revived's side (`revive_entry`). The
        # portrait reader stores every killer view on the victim's opposite
        # side, so those views refuse until it reads the killer's plate itself.
        killer_side = (side if revive_entry(entry)
                       else {"ally": "enemy", "enemy": "ally"}.get(side))
        entry["claim"] = _portrait_channel(
            views, "victim", side, slot, start, end, lineup, gallery,
            entity_id=f"death:{int(start)}:victim", source_version=source_version,
            exemplars=exemplars)
        entry["killer_claim"] = _portrait_channel(
            views, "killer", killer_side, slot, start, end, lineup, gallery,
            entity_id=f"death:{int(start)}:killer", source_version=source_version,
            exemplars=exemplars)
        for role in ("claim", "killer_claim"):
            # The evidence travels into the identity claim; a top-level key
            # would not (`identity.identity_claim`).
            entry[role]["evidence"]["seed"] = seed
            # Views the key fitted where the track or the victim plate
            # contradicts the entry: stored, never bound.
            entry[role]["evidence"]["follow_surprises"] = surprises
            if seed == "track":
                # The hud track placed these views: a prior, never a second
                # witness of the name.
                entry[role]["evidence"]["rests_on"] = [
                    {"context": "hud_track", "t_first": entry["t_first"], "slot": slot}]
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
    # A view that refuses abstains; it does not dissent. Requiring every view to
    # name made the rule stricter the longer an entry was followed: one thin
    # margin among ten views blocked a name four views gave.
    names = {c["agent"] for c in claims if c["agent"]}
    unanimous = sum(1 for c in claims if c["agent"]) >= 2 and len(names) == 1
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
                            contradicted: set[tuple[float, str]] = frozenset(),
                            witnesses: dict[int, list] | None = None) -> list[dict]:
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

    Elimination refuses an interval whose independent names repeat an agent
    (`elimination_collision`): two deaths carrying one name means the
    killfeed misread one of them or the agent died twice, and elimination
    would hand both the one agent left over, copying the error to both
    (223d636bf8d2 817.0 and 820.5 s, Reyna twice for Clove and Reyna). Every
    claim in such an interval carries the `collision` (the openings, each
    death's name and the `witnesses` that named it); `board_collisions` keeps
    one per interval, also where the count already refused.

    Where the count matched and no revive intervened, the board's dimmed set
    is the interval's victims, so a death carrying the repeated name has two
    candidates: its own name and the dimmed agent no death was given. Its
    claim carries a `contest` (reason `contested_by_collision`) for the
    arbiter, which names it only on a channel outside `COLLISION_IMPLICATED`.

    What dimming means is a player rule [domain:rounds/scoreboard-dim-is-dead]:
    a Run It Back death does not dim, so second-life deaths (`second_life`
    indices, or an entry flag) are left out of the count and name nothing
    here; a dimmed agent lit again was revived, which is recorded and is not a
    contradiction. A revive entry (`revive_entry`) is not a death and names
    nothing; an interval holding one on the side refuses, since the revived
    agent can die again and stay dim at both ends. A downed KAY/O is unknown
    to it, and a count that disagrees still refuses.

    The interval is (opening before, opening after]: an entry whose onset
    equals an opening's time belongs to the interval that opening closes. A
    killfeed entry appears at or after its death, so the board at that frame
    already dims the victim; leaving it out made the count match by
    coincidence where a second life was also uncounted (a1a995e6b19b 1656.0 s,
    KAY/O downed and killed; docs/VICTIM_DISAGREEMENTS.md).

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
        after = [o for o in usable if o["t_ms"] >= t_ms]
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
                  if e.get("side") == side and lo["t_ms"] < float(e["t_ms"]) <= hi["t_ms"]
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
        given = [named.get(j) for j in deaths if named.get(j)]
        repeated = sorted({a for a in given if given.count(a) > 1})
        if repeated:
            claim["collision"] = {
                "side": side, "opening_before_ms": lo["t_ms"], "opening_after_ms": hi["t_ms"],
                "newly_dim": sorted(newly), "agents": repeated,
                "deaths": [{"t_ms": float(entries[j]["t_ms"]), "slot": entries[j].get("slot"),
                            "agent": named.get(j), "witnesses": (witnesses or {}).get(j, [])}
                           for j in deaths]}
        # A revived agent can die again before the next opening and stay dim
        # at both ends (b3b9defb6fd7 1289.5 s, Skye), so the difference no
        # longer counts the interval's deaths.
        revives = [float(e["t_ms"]) for e in entries if revive_entry(e)
                   and e.get("side") == side and lo["t_ms"] < float(e["t_ms"]) <= hi["t_ms"]]
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
            if repeated:
                claim["reason"] = f"elimination_collision {repeated}"
                if named.get(i) in repeated:
                    claim["contest"] = {
                        "reason": "contested_by_collision",
                        "alternatives": [{"agent": named[i],
                                          "witnesses": (witnesses or {}).get(i, [])}] + [
                            {"agent": a, "witnesses": [["scoreboard_dim", a]],
                             "observation_keys": [s["observation_key"] for s in hi["rows"]
                                                  if s["team"] == side and s["agent"] == a]}
                            for a in sorted(newly - set(given))],
                        "implicated": list(COLLISION_IMPLICATED)}
            elif not all(names):
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


def board_collisions(session_id: str, round_no, claims: list[dict]) -> list[dict]:
    """One `collision` row per board interval whose independent names repeat
    an agent (`scoreboard_death_claims`), with the board's reason and each
    death's key. A finding for the killfeed, a misread or an uncounted second
    life; it names no one."""
    rows = {}
    for c in claims:
        col = c.get("collision")
        if col is None:
            continue
        key = (col["side"], col["opening_before_ms"], col["opening_after_ms"])
        rows.setdefault(key, {
            "kind": "collision", "round_no": round_no, **col, "board_reason": c["reason"],
            "deaths": [dict(d, death_id=death_key(session_id, d["t_ms"], d["slot"])
                            if d["slot"] is not None else None) for d in col["deaths"]]})
    return list(rows.values())


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


#: The roles of the left and right names of each killfeed entry type
#: [domain:killfeed/entry-types]. Stored rows keep the names `killer` and
#: `victim` for both roles of every type.
ENTRY_ROLES = {"kill": ("killer", "victim"), "second_life_death": ("killer", "victim"),
               "revive": ("reviver", "revived")}


def entry_type(entry: dict, is_second_life: bool | None = None) -> str:
    """`kill`, `second_life_death` or `revive`: a revive as `revive_entry`
    says, a second life as the death's own vote says (`is_second_life`, else
    the entry's), a kill otherwise. An entry whose type refused
    (`decide_entry_type`) takes the roles of a death here, as the roster
    counts it; its stored `entry_type` keeps the refusal."""
    if revive_entry(entry):
        return "revive"
    second = entry.get("is_second_life") if is_second_life is None else is_second_life
    return "second_life_death" if second else "kill"


def entry_actor(entry: dict, killer_identity: dict | None,
                is_second_life: bool | None = None) -> dict | None:
    """The agent acting in an entry, the left name: the killer of a kill or a
    second-life death, the reviver of a revive (`entry_type`). The arbiter
    names it from the left-name entity's claims other than the weapon icon's
    (`killer_identity`, a verdict's `metadata["killer_identity"]`), so the
    weapon owner can narrow the icon by this agent's kit without the icon
    vouching for itself. None when no other claim names one agent."""
    claims = [c for c in (killer_identity or {}).get("claims") or ()
              if c.get("channel") != "killfeed_weapon"]
    v = (adjudicate_agent_identity(claims) or [None])[0] if claims else None
    if v is None or v["status"] != "resolved":
        return None
    return {"agent": v["agent"], "entity_id": v["entity_id"],
            "role": ENTRY_ROLES[entry_type(entry, is_second_life)][0],
            "channels": v["channels"], "independent_channels": v["independent_channels"],
            "depends_on": v["depends_on"]}


def narrow_entry_weapon(entry: dict, verdict: "DeathVerdict", weapon_observations: list[dict],
                        agents, sides: dict, session_id: str,
                        store_root=None) -> dict:
    """The entry with its weapon named again by `entry_weapon` given its
    acting agent (`entry_actor`); unchanged when no actor is named. Its icon
    witness is asked again (`icon_witness`); the caller types the round again
    (`type_round_entries`)."""
    actor = entry_actor(entry, verdict.metadata.get("killer_identity"), verdict.is_second_life)
    if actor is None:
        return entry
    ev = entry_weapon(entry, weapon_observations, store_root=store_root,
                      agents=agents or None, actor=actor,
                      key=death_key(session_id, entry["t_ms"], entry["slot"]))
    e = {k: v for k, v in entry.items() if k not in ("weapon", "death_cause")}
    e["weapon_evidence"] = ev
    if ev["status"] == "resolved":
        e["weapon"], e["death_cause"] = ev["name"], ev["category"]
    e["revive_witnesses"] = dict(entry.get("revive_witnesses") or {}, icon=icon_witness(e))
    return e


#: A ring witness needs this many of an entry's bound frames to give a
#: confident `ringed` verdict, and the majority this share of them. One frame
#: suffices: on the labelled entries the ring separates per frame (all 22
#: revives cover 1.0, none of 115 other entries above 0.84;
#: [domain:killfeed/revive-ring]), and the killfeed reader parses a
#: one-colour revive banner on few frames (4f207c0c4e39 799.5 s: one row).
RING_MIN_FRAMES = 1
RING_MIN_SHARE = 0.8

#: The revive mechanisms the context gate checks, by the agent the entry's
#: side must field [domain:killfeed/entry-types]: Sage's Resurrection of a
#: dead teammate, Clove's Not Dead Yet after her own death, a teammate's
#: revive of KAY/O after his down [domain:killfeed/kayo-downed-entry].
REVIVE_MECHANISMS = {"Sage": "Resurrection", "Clove": "Not Dead Yet", "KAY_O": "NULL/cmd"}


def _claim(witness: str, value, reason: str | None, evidence: dict) -> dict:
    return {"witness": witness, "value": value, "reason": None if value is not None else reason,
            "evidence": evidence}


def icon_witness(entry: dict) -> dict:
    """The weapon-slot icon's claim: True when `adjudication.weapon` names a
    revive icon (`REVIVE_ICONS`), False when it names any other icon, None
    with its refusal reason otherwise. The name is the weapon owner's answer
    (`entry_weapon`, stored as `weapon_evidence`); this reads it and never
    names an icon. An answer that names only an unattributed ability says
    nothing of a revive (`unattributed_ability`)."""
    ev = entry.get("weapon_evidence")
    if ev is None:
        return _claim("icon", None, "no_weapon_stream", {})
    name = ev.get("name")
    evidence = {"owner": "adjudication.weapon", "version": ev.get("version"),
                "status": ev.get("status"), "name": name,
                "observations": ev.get("observations"), "rests_on": ev.get("rests_on")}
    if name in REVIVE_ICONS:
        return _claim("icon", True, None, evidence)
    if name is not None:
        return _claim("icon", False, None, evidence)
    if ev.get("status") == "resolved":
        return _claim("icon", None, "unattributed_ability", evidence)
    return _claim("icon", None, f"icon_{ev.get('reason') or 'unnamed'}", evidence)


def ring_witness(entry: dict, weapon_observations: list[dict] | None) -> dict:
    """The weapon-slot ring's claim [domain:killfeed/revive-ring]: the
    majority of the confident `ringed` verdicts on the entry's frames, which
    `adjudication.weapon.bind_entry` binds. True or False when RING_MIN_FRAMES
    decide and the majority holds RING_MIN_SHARE of them; None with a reason
    otherwise: no stream, a stream before the ring (`no_ring_field`), no bound
    frame, too few confident frames (`ring_` and the commonest frame reason),
    or frames that split (`ring_frames_disagree`)."""
    from .weapon import bind_entry
    if weapon_observations is None:
        return _claim("ring", None, "no_weapon_stream", {})
    bound = bind_entry(entry, weapon_observations)
    frames = [[float(o["t_ms"]), o["slot"], o.get("ringed"),
               (o.get("ring") or {}).get("cover")] for o in bound]
    evidence = {"stream": "killfeed_weapon", "frames": frames}
    if not bound:
        return _claim("ring", None, "no_bound_frame", evidence)
    if not any("ringed" in o for o in bound):
        return _claim("ring", None, "no_ring_field", evidence)
    votes = [o["ringed"] for o in bound if o.get("ringed") is not None]
    evidence["votes"] = {"ringed": sum(votes), "unringed": len(votes) - sum(votes),
                         "unread": len(bound) - len(votes)}
    if len(votes) < RING_MIN_FRAMES:
        why = Counter(o.get("ring_reason") or "unread" for o in bound).most_common(1)[0][0]
        return _claim("ring", None, f"ring_{why}", evidence)
    top = sum(votes) * 2 >= len(votes)
    if votes.count(top) < RING_MIN_SHARE * len(votes):
        return _claim("ring", None, "ring_frames_disagree", evidence)
    return _claim("ring", bool(top), None, evidence)


def plate_revive(entry: dict, names: tuple[bool | None, str | None] = (None, "no_name_check"),
                 ) -> dict:
    """The one-colour plates' claim [domain:killfeed/revive-entries]. A
    revive banner is one colour end to end, so plates that read two colours
    (`session_entries`' `same_side`, a majority of the entry's views) say
    False. One colour says True, a weaker claim: an environmental death and
    a team kill are one colour too, so `decide_entry_type` counts it for a
    revive only where no weapon-slot witness speaks. A self entry is one
    colour too, so `names`, `killfeed_names.self_entry`'s answer
    (`entry_names`), must read two names: one name refuses (`self_entry`;
    a Clove self-revive and its expiry both print one name), and an unread
    name refuses with its reason. 59c70f1ef720 1849.5 s, a Clove revive's
    expiry whose icon went unnamed, was taken for a revive before the name
    check; bdfdcf009dba 1310.0 s, a Sage revive whose Resurrection icon went
    unnamed on all six views, was stored as a death before the plates."""
    same = entry.get("same_side")
    evidence = {"stream": "hud", "same_side": same, "side": entry.get("side"),
                "names": list(names)}
    if same is None:
        return _claim("plates", None, "plates_unread", evidence)
    if not same:
        return _claim("plates", False, None, evidence)
    one, why = names
    if one is None:
        return _claim("plates", None, why or "names_unread", evidence)
    return _claim("plates", None, "self_entry", evidence) if one else _claim("plates", True, None,
                                                                              evidence)


def entry_witnesses(entry: dict, weapon_observations: list[dict] | None,
                    names: tuple[bool | None, str | None] = (None, "no_name_check")) -> dict:
    """Every revive witness of one entry, each its own claim: the icon
    (`icon_witness`), the ring (`ring_witness`) and the plates
    (`plate_revive`)."""
    return {"icon": icon_witness(entry), "ring": ring_witness(entry, weapon_observations),
            "plates": plate_revive(entry, names)}


def revive_context(entry: dict, earlier: list[dict], sides: dict, *,
                   lineup_version: str | None = None, mechanism: str | None = None,
                   victims: dict | None = None) -> dict:
    """The context gate on a revive [domain:killfeed/entry-types]: whether a
    revive this entry could be is possible at all, never whether it is one.

    `earlier` holds the round's entries before this one, each typed
    (`entry_type`). A mechanism (`REVIVE_MECHANISMS`, narrowed to `mechanism`,
    the agent the icon named, when given) is open when its agent is fielded on
    the entry's side by the lineup, and the side has a non-revive entry
    earlier in the round: a dead teammate for Sage, Clove's own death, KAY/O's
    down. `victims`, {entry time: (victim agent, death id)} from the round's
    verdicts, sharpens two checks: a Sage named dead earlier in the round and
    not revived since cannot revive, and a KAY/O revive needs an earlier
    entry whose victim is named KAY/O [domain:killfeed/kayo-downed-entry].

    Value True when some mechanism is open, False when every one is closed,
    None when none is closed but one cannot be checked (an unnamed lineup
    slot, an unnamed earlier victim). Declares `rests_on` the lineup, a
    prior the lineup owner placed, and `depends_on` each death whose victim
    name it used."""
    side = entry.get("side")
    agents = {r.get("agent") for r in (sides or {}).get(side) or []}
    unnamed_slot = None in agents or not agents
    t = float(entry["t_ms"])
    prior = [e for e in earlier
             if e.get("side") == side and float(e["t_ms"]) < t and not revive_entry(e)]
    revived = [e for e in earlier if e.get("side") == side and float(e["t_ms"]) < t
               and revive_entry(e)]
    depends: list[str] = []
    checks: dict[str, dict] = {}
    for agent in ([mechanism] if mechanism else REVIVE_MECHANISMS):
        c = {"fielded": (True if agent in agents else None if unnamed_slot else False)}
        c["prior_death"] = bool(prior)
        if agent == "Sage" and victims is not None:
            dead = [e for e in prior if (victims.get(float(e["t_ms"])) or (None,))[0] == "Sage"]
            back = [e for e in revived if dead and float(e["t_ms"]) > float(dead[-1]["t_ms"])]
            if dead:
                depends.append(victims[float(dead[-1]["t_ms"])][1])
            c["reviver_alive"] = not dead or bool(back)
        if agent == "KAY_O":
            named = [victims.get(float(e["t_ms"])) for e in prior] if victims is not None else []
            if any(v and v[0] == "KAY_O" for v in named):
                depends.extend(v[1] for v in named if v and v[0] == "KAY_O")
                c["kayo_down"] = True
            elif not prior or (victims is not None and named and all(v and v[0] for v in named)):
                c["kayo_down"] = False
            else:
                c["kayo_down"] = None
        vals = list(c.values())
        c["open"] = False if False in vals else None if None in vals else True
        checks[agent] = c
    opens = [c["open"] for c in checks.values()]
    value = True if True in opens else None if None in opens else False
    closed = {a: [k for k, v in c.items() if v is False and k != "open"]
              for a, c in checks.items() if c["open"] is False}
    reason = None
    if value is False:
        reason = ";".join(f"{a}:{','.join(ks)}" for a, ks in closed.items())
    elif value is None:
        reason = "context_unchecked"
    return {"witness": "context", "value": value, "reason": reason, "checks": checks,
            "mechanism": mechanism,
            "rests_on": [{"context": "lineup", "version": lineup_version}],
            "depends_on": sorted(set(depends))}


def decide_entry_type(witnesses: dict, context: dict | None,
                      is_second_life: bool = False) -> dict:
    """The entry's type from every revive witness at once.

    Each witness is its own claim (`entry_witnesses`): True says a revive,
    False says not a revive, None says nothing and carries why. The rule:

    1. The weapon-slot witnesses, the icon and the ring, decide when they
       speak. Both True, or one True and the other silent: a revive
       candidate. Both False, or one False and the other silent: not a
       revive. One True and one False: refused, `slot_witnesses_disagree`.
    2. The plates bear on the slot's answer only as a contradiction: a
       revive banner is one colour, so plates reading two colours against a
       slot revive refuse (`plates_two_colours_against_slot`). One-colour
       plates beside a slot's False are no disagreement: a team kill and an
       environmental death are one colour too.
    3. With the slot silent, one-colour plates make a revive candidate, two
       colours make a non-revive, and silent plates refuse
       (`no_revive_witness`): nothing witnessed the entry.
    4. The context gate (`revive_context`) checks a revive candidate: a
       closed gate refuses (`revive_against_context`), never turning the
       entry into a kill; an unchecked gate lets the candidate stand and says
       so (`context_unchecked`). It never makes a revive.
    5. A non-revive is a `second_life_death` when the death's second-life
       vote says so, a `kill` otherwise.

    No witness decides alone against another that speaks. A refusal names
    its reason, keeps both alternatives with the witnesses for and against
    each, and stores the disagreement; nothing is averaged. A caller counts
    a refused entry as a death for the roster, as before, and the stored
    type stays None with the refusal.
    """
    vals = {k: (w or {}).get("value") for k, w in witnesses.items()}
    slot = {k: vals.get(k) for k in ("icon", "ring") if vals.get(k) is not None}
    plates = vals.get("plates")
    death = "second_life_death" if is_second_life else "kill"
    for_revive = sorted(k for k, v in vals.items() if v is True)
    against = sorted(k for k, v in vals.items() if v is False)
    disagreement, reason, revive, rule = None, None, None, None
    if True in slot.values() and False in slot.values():
        reason, rule = "slot_witnesses_disagree", 1
    elif True in slot.values():
        if plates is False:
            reason, rule = "plates_two_colours_against_slot", 2
        else:
            revive, rule = True, 1
    elif False in slot.values():
        revive, rule = False, 1
        # One-colour plates are consistent with a team kill: not counted against.
        for_revive = [k for k in for_revive if k != "plates"]
    elif plates is True:
        revive, rule = True, 3
    elif plates is False:
        revive, rule = False, 3
    else:
        reason, rule = "no_revive_witness", 3
    if reason in ("slot_witnesses_disagree", "plates_two_colours_against_slot"):
        disagreement = {"revive": for_revive, "not_revive": against}
    if revive and context is not None and context.get("value") is False:
        revive, rule, reason = None, 4, "revive_against_context"
        disagreement = {"revive": for_revive, "not_revive": against,
                        "context": context.get("reason")}
    alternatives = [{"type": "revive", "for": for_revive, "against": against},
                    {"type": death, "for": against, "against": for_revive}]
    out = {"status": "refused" if revive is None else "resolved",
           "type": None if revive is None else "revive" if revive else death,
           "reason": reason, "rule": rule, "alternatives": alternatives,
           "disagreement": disagreement, "witnesses": witnesses, "context": context}
    if revive and context is not None and context.get("value") is None:
        out["context_unchecked"] = context.get("reason")
    return out


def entry_type_claim(entry: dict) -> dict:
    """The entry's stored type decision (`type_round_entries`), or one
    decided now from the witnesses the entry carries, without context."""
    if entry.get("entry_type") is not None:
        return entry["entry_type"]
    w = dict(entry.get("revive_witnesses") or {})
    w.setdefault("icon", icon_witness(entry))
    w.setdefault("ring", _claim("ring", None, "not_bound", {}))
    w.setdefault("plates", plate_revive(entry, tuple(entry.get("plate_names")
                                                     or (None, "no_name_check"))))
    return decide_entry_type(w, None, bool(entry.get("is_second_life")))


def type_round_entries(entries: list[dict], sides: dict, *, lineup_version: str | None = None,
                       victims: dict | None = None) -> list[dict]:
    """The round's entries, in onset order, each carrying its `entry_type`
    decision (`decide_entry_type`) over its `revive_witnesses` and the
    context gate (`revive_context`) built from the entries typed before it.
    `victims` ({entry time: (victim, death id)}) comes from the round's
    verdicts when a caller has them."""
    order = sorted(range(len(entries)), key=lambda i: float(entries[i]["t_ms"]))
    out: list[dict | None] = [None] * len(entries)
    done: list[dict] = []
    for i in order:
        e = {k: v for k, v in entries[i].items() if k != "entry_type"}
        w = dict(e.get("revive_witnesses") or {})
        w.setdefault("icon", icon_witness(e))
        w.setdefault("ring", _claim("ring", None, "not_bound", {}))
        w.setdefault("plates", plate_revive(e, tuple(e.get("plate_names")
                                                     or (None, "no_name_check"))))
        icon = w["icon"]
        named = (icon.get("evidence") or {}).get("name") if icon.get("value") else None
        mech = next((a for a, n in REVIVE_MECHANISMS.items() if n == named), None)
        ctx = revive_context(e, done, sides, lineup_version=lineup_version, mechanism=mech,
                             victims=victims)
        e["entry_type"] = decide_entry_type(w, ctx, bool(e.get("is_second_life")))
        done.append(e)
        out[i] = e
    return out


def entry_victim_side(entry: dict) -> str | None:
    """The side of a killfeed entry's victim: its `side`, else its
    `victim_ally` flag (True is "ally", False "enemy"), else its
    `victim_side`, which defaults to "enemy" when the key is absent and
    stays None when it is stored as None."""
    if entry.get("side"):
        return entry["side"]
    ally = entry.get("victim_ally")
    if ally is True:
        return "ally"
    if ally is False:
        return "enemy"
    return entry.get("victim_side", "enemy")


def revive_entry(entry: dict) -> bool:
    """Whether a killfeed entry is a revive rather than a death: its type
    decision (`entry_type_claim`) resolved to `revive`."""
    return entry_type_claim(entry).get("type") == "revive"


def entry_names(entry: dict, portraits: list[dict], widths: dict,
                name_observations: list[dict] | None,
                session_id: str, others: list[dict] | None = None
                ) -> tuple[bool | None, str | None]:
    """`killfeed_names.self_entry` at the views `follow_entry_portraits` binds
    the entry to, or None with a reason when no name stream is stored."""
    from .killfeed_names import followed_views, self_entry
    if name_observations is None:
        return None, "no_killfeed_name_stream"
    bound = follow_entry_portraits(entry, portraits, widths, others)
    obs = [p for p in portraits
           if p.get("role") == "killer" and (float(p["t_ms"]), p["slot"]) in bound]
    return self_entry(followed_views(obs), name_observations, session_id)


def icon_widths(weapon_observations: list[dict] | None) -> dict:
    """{(t_ms, slot): the weapon icon box's width} from `killfeed_weapon` rows."""
    return {(float(o["t_ms"]), o["slot"]): o["wx1"] - o["wx0"]
            for o in weapon_observations or []
            if o.get("kind") == "weapon_icon_observation" and o.get("wx1") is not None}


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
    second life rather than a death, by the badge reader's vote.

    The vote runs over the rows of `killfeed.second_life_observations`,
    which fit a ring at the left end of the victim's plate
    (`killfeed.badge_ring`) and name no icon: Phoenix's Run It Back badge and
    the KAY/O down icon [domain:killfeed/kayo-downed-entry] both read as one.
    The reader's lineup gate (`killfeed.second_life_gate`) reads only entries
    whose victim may be Phoenix or KAY/O, and the player's own deaths.

    A majority vote over the stored `second_life_observation` rows of the
    player's own death entries (`player_death`) inside the track's lifetime:
    `rounds` has the player's death tracks, not the entry's slots. Another
    entry's rows never vote here; an entry's own vote is `entry_second_life`.
    An uncertain read (`has_badge` None) does not vote. None when no read
    falls there: unread, which a caller keeps apart from "no badge".
    """
    votes = [o["has_badge"] for o in observations
             if o.get("kind") == "second_life_observation" and o.get("player_death")
             and o.get("has_badge") is not None
             and t_first - SECOND_LIFE_SLACK_MS <= o["t_ms"] <= t_last + SECOND_LIFE_SLACK_MS]
    if not votes:
        return None
    return sum(votes) * 2 > len(votes)


def entry_second_life(entry: dict, observations: list[dict] | None,
                      others: list[dict] | None = None) -> dict:
    """Whether one killfeed entry is a second-life death, by the badge rows
    read at the views it occupies.

    The views are the entry's hud track reads the queue rule admits
    (`entry_slot_path`); a row votes when its `(t_ms, slot)` is one of them,
    so a badge on one entry never votes on another on screen beside it. A
    majority vote over the confident reads, as `second_life_death`'s; an
    uncertain read (`has_badge` None) does not vote. Returns `{"value",
    "badges", "reads", "binding"}`: `value` None when no confident read fell
    at the entry (`binding` says why), which a caller keeps apart from "no
    badge"."""
    if observations is None:
        return {"value": None, "badges": 0, "reads": 0, "binding": "no_badge_stream"}
    path, _ = entry_slot_path(entry, others)
    if path is None:
        return {"value": None, "badges": 0, "reads": 0, "binding": "no_track_reads"}
    at = set(path)
    votes = [bool(o["has_badge"]) for o in observations
             if o.get("kind") == "second_life_observation" and o.get("has_badge") is not None
             and (float(o["t_ms"]), int(o["slot"])) in at]
    if not votes:
        return {"value": None, "badges": 0, "reads": 0, "binding": "unread"}
    return {"value": sum(votes) * 2 > len(votes), "badges": sum(votes), "reads": len(votes),
            "binding": "entry_reads"}


def death_key(session_id: str, t_ms: float, slot: int) -> str:
    """A death's stable entity key: the session, the first-seen time of its
    killfeed entry track and the slot it appeared in. Two entries cannot
    appear in one slot of one frame, and the key does not move when detection
    adds or drops another entry."""
    return f"death:{session_id}:{int(float(t_ms))}:{int(slot)}"


def session_entries(hud: dict, second_life: list[dict] | None = None,
                    stalls: list[dict] | None = None) -> list[dict]:
    """One dict per counted killfeed entry track over the whole session, from
    stored HUD columns only: first-seen time, the slot it appeared in, the
    victim's plate side there, whether it is the player's kill or death, and
    the track's per-sample `(t_ms, slot)` reads (`reads`), which follow the
    entry as it rises and seed `entry_follow` where its first slot shows no
    portrait. `stalls`, the session's capture-stall spans, count an entry
    drawn at a stall's release (`checks.track_entries`); such an entry carries
    `released`, the span.

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
                                                                col(f"kf_{kind}_wx"),
                                                                stalls=stalls)
                                      if e["counted"]])
            for kind in ("kill", "death")}
    # Stored from hud-0.15.0; an older table reads no entry's plates as one side.
    same = hud.get("kf_same_side_mask")
    # The victim plate's side and the same-side mask let `track_entries` split
    # two entries that held one slot in turn and keep a revive whole.
    sides = (list(zip(hud["kf_ally_mask"], hud["kf_enemy_mask"], same or [None] * len(t)))
             if hud.get("kf_ally_mask") and hud.get("kf_enemy_mask") else None)
    tracks = [e for e in track_entries(t, hud["kf_entry_mask"], col("kf_entry_wx"),
                                       flags={"same_side": same} if same else None,
                                       sides=sides, stalls=stalls)
              if e["counted"]]
    # A player track belongs to the entry on screen when it was first seen
    # whose divider agrees, the latest such onset first (the attribution can
    # come a sample after the plate), then the one that appeared in its slot.
    # The dividers compared are the two read at the player track's onset: a
    # track's `sig` is its last read, and an entry track that ran on into a
    # later entry carries that entry's divider (bdfdcf009dba 294.0 s, 233 px
    # at the kill, 223 px at its end; 3694746e4e54 1454.0 s, 184 against 177).
    from ..killfeed import wx_at

    def divider_at(track, column, t0):
        reads = [(t, s) for t, s, _ in track.get("assigned") or () if t <= t0]
        if not reads or not hud.get(column):
            return track.get("sig")
        t, s = reads[-1]
        return wx_at(hud[column][at[t]], s)

    owner = {"kill": {}, "death": {}}
    for kind, seq in mine.items():
        for k in seq:
            sig = divider_at(k, f"kf_{kind}_wx", k["t_first"])
            fits = [j for j, e in enumerate(tracks)
                    if e["t_first"] <= k["t_first"] <= e["t_last"]
                    and (sig is None or (d := divider_at(e, "kf_entry_wx", k["t_first"])) is None
                         or abs(sig - d) <= KF_SIG_TOL)]
            if fits:
                owner[kind].setdefault(max(fits, key=lambda j: (
                    tracks[j]["t_first"], tracks[j]["slot_first"] == k["slot_first"])), k)
    out = []
    for j, e in enumerate(tracks):
        i, slot = at[e["t_first"]], e["slot_first"]
        bit = lambda c, i, s: bool((hud[c][i] or 0) & (1 << s))
        ally, enemy = bit("kf_ally_mask", i, slot), bit("kf_enemy_mask", i, slot)
        if not (ally or enemy):
            # The victim plate went unread where the entry appeared (under the
            # Shooting Error overlay, bdfdcf009dba 672.0 s): its side is the
            # first one its own track read, since one entry's victim never
            # changes team.
            read = [(a, n) for t_, s_, _ in e.get("assigned") or ()
                    for a, n in [(bit("kf_ally_mask", at[t_], s_),
                                  bit("kf_enemy_mask", at[t_], s_))] if a or n]
            ally, enemy = read[0] if read else (False, False)
        pk = j in owner["kill"]
        dt = owner["death"].get(j)
        out.append({"t_ms": e["t_first"], "t_first": e["t_first"], "t_last": e["t_last"],
                    "slot": slot, "sig": e.get("sig"), "side": "ally" if ally else "enemy" if enemy else "unknown",
                    "reads": [(float(t_), int(s_)) for t_, s_, _ in e.get("assigned") or ()],
                    "victim_ally": ally, "kf_player_kill": pk, "kf_player_death": dt is not None,
                    "same_side": (None if not same else
                                  2 * e["flag_hits"].get("same_side", 0) > e["n_obs"]),
                    "player_track": None if dt is None else (dt["t_first"], dt["t_last"]),
                    "claim": None, "location": None, "killer_location": None,
                    **({"released": e["released"]} if e.get("released") else {})})
    # Each entry's own badge rows decide its second life (`entry_second_life`);
    # the player's death track's window vote (`second_life_death`) stands in
    # only where none was read at the entry's views. 587c15b07779 1294.5 s:
    # a badge read on the player's Phoenix entry, but no player death track
    # owned the entry, so the track vote never ran.
    for e in out:
        vote = entry_second_life(e, second_life, out)
        span = e.pop("player_track")
        if vote["value"] is None and span is not None and second_life is not None:
            v = second_life_death(span[0], span[1], second_life)
            if v is not None:
                vote = {**vote, "value": v, "binding": "player_track"}
        e["second_life_vote"] = vote
        e["is_second_life"] = bool(vote["value"])
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


def _unstalled_ms(a: float, b: float, stalls) -> float:
    """`b - a` less the time inside capture-stall spans."""
    inside = sum(max(0.0, min(b, s["t_end_ms"]) - max(a, s["t_start_ms"])) for s in stalls or ())
    return (b - a) - inside


def _slot_at(entry: dict, t: float) -> int:
    """The slot an entry track held at its last read at or before `t`, else
    its first slot."""
    held = [s for t_, s in entry.get("reads") or () if t_ <= t]
    return held[-1] if held else entry["slot"]


def _onset_slot(entry: dict, step: float) -> int:
    """The highest slot an entry track reads within one sample of its onset:
    one read in a slot below its true one is a slot misread
    (59c70f1ef720 1271.0 s, read in slot 1 then slot 0)."""
    t0 = float(entry["t_first"])
    return min([s for t_, s in entry.get("reads") or () if t_ <= t0 + step] or [entry["slot"]])


def same_entry(earlier: tuple[dict, "DeathVerdict"], later: tuple[dict, "DeathVerdict"], *,
               stalls=None, step: float = 500.0, revives=()) -> dict | None:
    """Whether two adjudicated deaths are one killfeed entry read as two
    tracks: the merge rule with its evidence, or None.

    The tracks' dividers cannot say it -- each split here took a new divider
    read -- so the evidence is a second channel, the names, checked against
    the queue [domain:killfeed/stack-order] and the entry's lifetime
    [domain:killfeed/entry-lifetime]:

      names  -- both victims named and equal, the killers not named apart.
                One agent dies once per entry life; a revive between the two
                (`revives`, the revive verdicts' times and sides) or a second
                life breaks that, so neither may be a revive and both must be
                second lives or neither. A revive whose entry (`entry`) sits
                below the later track's onset slot at that time arrived after
                it [domain:killfeed/stack-order], so the later track is the
                older entry and the revive separates nothing: at
                9acf02f98283 one Killjoy -> Clove entry held slot 1 from 966.0
                to 970.5 s, the Not Dead Yet revive drew below it in slot 2 at
                967.0 s, and the track split at 968.5 s. Where a victim is unnamed, both
                killers named and equal suffice only for `continuation`.
      side   -- the victim plates do not read opposite sides.
      queue  -- the later track starts in the slot the earlier held at that
                time or above it, since an entry never moves down
                (`_onset_slot` forgives a one-sample slot misread).
      life   -- `queue`: the two together fit one entry's life outside stall
                time, `t_last(later) - t_first(earlier) + step`;
                `stall_release`: the later is first read within one sample of
                a stall's end and the earlier was read within a track gap of
                that stall's start, so the release redrew it
                (3694746e4e54 143.5 s, the 125 s entry, stall 130.6-144.0 s);
                `continuation` (killers agree, a victim unnamed): the later
                is read the very next sample in the slot the earlier left,
                the earlier too young to have expired, and the two fit one
                life. One killer's next kill lands in a new slot below, never
                in the slot of an entry still on screen (96aa1ae9b96f 600.5
                and 601.0 s, Clove, slot 1, dividers 199 and 215).
    """
    from ..checks import KF_ENTRY_LIFE_MS, KF_ENTRY_LIFE_TOL_MS, KF_TRACK_GAP_MS
    (e, ve), (l, vl) = earlier, later
    if ve.is_revive or vl.is_revive or bool(ve.is_second_life) != bool(vl.is_second_life):
        return None
    if ve.victim and vl.victim and ve.victim != vl.victim:
        return None
    if ve.killer and vl.killer and ve.killer != vl.killer:
        return None
    by_victim = bool(ve.victim and vl.victim)
    if not (by_victim or (ve.killer and vl.killer)):
        return None
    sides = {e.get("side"), l.get("side")} & {"ally", "enemy"}
    if len(sides) > 1:
        return None
    t_e, t_l = float(e["t_first"]), float(l["t_first"])
    e_slot, l_slot = _slot_at(e, t_l), _onset_slot(l, step)
    if t_l < t_e or any(t_e < float(r["t_ms"]) <= t_l
                        and (not sides or r.get("side") not in ("ally", "enemy")
                             or r.get("side") in sides)
                        and not (r.get("entry") is not None and l_slot < _slot_at(r["entry"], t_l))
                        for r in revives):
        return None
    if l_slot > e_slot:
        return None
    ev = {"victim": [ve.victim, vl.victim], "killer": [ve.killer, vl.killer],
          "slots": [e_slot, l_slot], "t_last": [float(e["t_last"]), float(l["t_last"])],
          "life_ms": _unstalled_ms(t_e, float(l["t_last"]), stalls) + step}
    one_life = ev["life_ms"] <= KF_ENTRY_LIFE_MS + KF_ENTRY_LIFE_TOL_MS
    if not by_victim:
        young = float(e["t_last"]) - t_e + step < KF_ENTRY_LIFE_MS - KF_ENTRY_LIFE_TOL_MS
        next_sample = 0.0 < t_l - float(e["t_last"]) <= 1.5 * step
        if one_life and young and next_sample and int(l["slot"]) == e_slot:
            return {"rule": "continuation", "evidence": ev}
        return None
    if one_life:
        return {"rule": "queue", "evidence": ev}
    for s in stalls or ():
        if (abs(t_l - s["t_end_ms"]) <= step
                and s["t_start_ms"] - KF_TRACK_GAP_MS <= float(e["t_last"]) <= s["t_end_ms"]):
            return {"rule": "stall_release",
                    "evidence": {**ev, "stall": [s["t_start_ms"], s["t_end_ms"]]}}
    return None


def merge_split_entries(rounds: list[dict], *, stalls=None, step: float = 500.0) -> list[dict]:
    """Fold each death that `same_entry` calls an earlier death's second
    track into that earlier death, over the whole session; returns the merges.

    The earlier death keeps its key, its verdict and its row, unless it
    names no victim and the later one does: the victim is the death's
    identity, so the named piece survives (96aa1ae9b96f 601.0 s over the
    600.5 s release frame). The survivor's entry takes the union of the two
    `t_last`, reads and player flags and carries `merged`, the absorbed death
    ids with each rule and its evidence. The absorbed death leaves its round's
    `entries` and `verdicts` for the round's `merged`, as
    `(entry, verdict, merge)`; nothing is dropped. A later death is compared
    with each surviving earlier one, nearest first. Names never pass between
    the two verdicts: each stays the arbiter's verdict on its own key.
    """
    items = sorted(((float(e["t_first"]), int(e["slot"]), ri, k)
                    for ri, x in enumerate(rounds) for k, e in enumerate(x["entries"])))
    revives = [{"t_ms": float(v.t_ms), "side": e.get("side"), "entry": e}
               for x in rounds for e, v in zip(x["entries"], x["verdicts"]) if v.is_revive]
    alive: list[tuple[int, int]] = []
    gone: dict[tuple[int, int], dict] = {}
    for _, _, ri, k in items:
        e, v = rounds[ri]["entries"][k], rounds[ri]["verdicts"][k]
        hit = None
        for n, (rj, j) in reversed(list(enumerate(alive))):
            pe, pv = rounds[rj]["entries"][j], rounds[rj]["verdicts"][j]
            if float(e["t_first"]) - float(pe["t_first"]) > 60_000:
                break
            m = same_entry((pe, pv), (e, v), stalls=stalls, step=step, revives=revives)
            if m:
                hit = (n, rj, j, m)
                break
        if hit is None:
            alive.append((ri, k))
            continue
        n, rj, j, m = hit
        pe, pv = rounds[rj]["entries"][j], rounds[rj]["verdicts"][j]
        keep, lose = ((ri, k), (rj, j)) if (pv.victim is None and v.victim) else ((rj, j), (ri, k))
        se, sv = rounds[keep[0]]["entries"][keep[1]], rounds[keep[0]]["verdicts"][keep[1]]
        le, lv = rounds[lose[0]]["entries"][lose[1]], rounds[lose[0]]["verdicts"][lose[1]]
        merge = {"into": sv.death_id, "absorbed": lv.death_id, **m}
        se["t_last"] = max(float(se["t_last"]), float(le["t_last"]))
        se["reads"] = sorted(set(map(tuple, se.get("reads") or ()))
                             | set(map(tuple, le.get("reads") or ())))
        for flag in ("kf_player_kill", "kf_player_death"):
            se[flag] = bool(se.get(flag) or le.get(flag))
        se["merged"] = le.pop("merged", []) + se.get("merged", []) + [merge]
        for prior in se["merged"]:
            prior["into"] = sv.death_id
        alive[n] = keep
        gone[lose] = merge
    for ri, x in enumerate(rounds):
        drop = [k for k in range(len(x["entries"])) if (ri, k) in gone]
        x["merged"] = x.get("merged", []) + [(x["entries"][k], x["verdicts"][k], gone[(ri, k)])
                                             for k in drop]
        x["entries"] = [en for k, en in enumerate(x["entries"]) if (ri, k) not in gone]
        x["verdicts"] = [vd for k, vd in enumerate(x["verdicts"]) if (ri, k) not in gone]
    return list(gone.values())


#: Channels that observe a death without the killfeed: the living set's
#: drop, a minimap X or track, and the player's own HUD.
DEATH_OBSERVERS = ("roster_diff", "xmark", "minimap_track", "player_hud")


def unwitnessed_entry(entry: dict, verdict: "DeathVerdict") -> dict | None:
    """Why a killfeed entry is no death, or None when something attests it.

    A band of plate colour that is not an entry -- a death-recap panel, the
    round-start banner, red and green scenery -- tracks like one, and nothing
    else sees it: no channel names its victim or its killer, no other channel
    observes a death then (`DEATH_OBSERVERS`), no weapon icon is read in it,
    and the player is in neither role. Over the 21 Riot-scored matches seven
    of the ten phantom deaths were exactly that (b3b9defb6fd7 1650.5 s, the
    recap panel in slot 5; bdfdcf009dba 128.0 s, the DEFENDING banner), while
    every unnamed real death had a roster drop or a read weapon icon. A
    revive's type witnesses attest it, so a revive is never refused.
    """
    if verdict.is_revive:
        return None
    md = verdict.metadata or {}
    claims = [c for key in ("identity", "killer_identity")
              for c in ((md.get(key) or {}).get("claims") or [])]
    if any(c.get("agent") for c in claims):
        return None
    observers = [c for c in verdict.channels if c in DEATH_OBSERVERS]
    weapon = (entry.get("weapon_evidence") or {}).get("status") == "resolved"
    player = bool(entry.get("kf_player_kill") or entry.get("kf_player_death"))
    if observers or weapon or player:
        return None
    return {"reason": "no_role_named_no_observer",
            "evidence": {"channels": list(verdict.channels),
                         "claims": [[c.get("channel"), c.get("reason")] for c in claims],
                         "weapon": (entry.get("weapon_evidence") or {}).get("status"),
                         "slot": entry.get("slot"), "side": entry.get("side")}}


def refuse_unwitnessed(rounds: list[dict]) -> list[dict]:
    """Move each death `unwitnessed_entry` refuses from its round's `entries`
    and `verdicts` to the round's `refused`, as `(entry, verdict, refusal)`;
    returns the refusals."""
    out = []
    for x in rounds:
        keep, refused = [], list(x.get("refused", []))
        for e, v in zip(x["entries"], x["verdicts"]):
            why = unwitnessed_entry(e, v)
            if why is None:
                keep.append((e, v))
            else:
                refused.append((e, v, why))
                out.append({"death_id": v.death_id, **why})
        x["entries"], x["verdicts"] = [e for e, _ in keep], [v for _, v in keep]
        x["refused"] = refused
    return out


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


# The minimap X: the colour blobs above, then a shape test. Stage 2 of the
# minimap object classifier (prototypes/minimap_objects_s2.py,
# minimap-objects-s2-0.1.0) measured it; the constants are its own.
X_R = 9.0            # the patch half-size round a blob (px at scale 1)
X_DIAG_PX = 1.6      # a pixel lies on a diagonal within this
X_DIAG_MIN = 0.75    # share of the blob's pixels on the two diagonals
X_ARM_MIN = 0.12     # each of the four arms' share of the arm pixels
X_EXT = (3.5, 9.0)   # the 90th-percentile radius
X_MIN_PX = 10.0      # the blob's least pixel count, * scale squared


def _x_key(patch: np.ndarray, colour: str) -> np.ndarray:
    c = patch.astype(np.float32)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    if colour == "red":
        return (r - np.maximum(b, g)) > 40
    return ((b - r) > 50) & (b >= g - 10)


def x_shape(crop: np.ndarray, colour: str, x: float, y: float, scale: float = 1.0) -> dict:
    """Is the `colour` blob nearest (x, y) an X: its pixels on two crossing
    diagonals, four arms, and an X's size? `x` is the verdict, `why` the
    reason it is not, and `cx`, `cy` the blob's centre.

    One test serves both colours. The colour blobs alone call every red
    enemy icon and "?" an X; on the player's labels the shape test passes
    [metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_enemy_x=5]
    of the enemy icons (rejecting
    [metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_enemy_not_x=281]),
    no "?" (rejecting
    [metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_question_not_x=83]),
    and every labelled X mark
    ([metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#dynamic_x_mark_x=3]).
    It also passes
    [metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_other_red_x=194]
    of the player's unnamed other-red marks, whose truth the labels do not
    give."""
    import cv2

    R = int(round(X_R * scale))
    h, w = crop.shape[:2]
    x0, y0 = max(0, int(round(x)) - R), max(0, int(round(y)) - R)
    x1, y1 = min(w, int(round(x)) + R + 1), min(h, int(round(y)) + R + 1)
    m = _x_key(crop[y0:y1, x0:x1], colour).astype(np.uint8)
    n, lab = cv2.connectedComponents(m, connectivity=8)
    if n <= 1:
        return {"x": False, "why": "no_pixels"}
    ys, xs = np.nonzero(lab)
    k = np.argmin(np.hypot(xs + x0 - x, ys + y0 - y))
    comp = lab == lab[ys[k], xs[k]]
    py, px = np.nonzero(comp)
    if len(px) < X_MIN_PX * scale * scale:
        return {"x": False, "why": "small", "n": int(len(px))}
    cx, cy = px.mean(), py.mean()
    dx, dy = px - cx, py - cy
    d = np.minimum(np.abs(dx - dy), np.abs(dx + dy)) / math.sqrt(2)
    on = d <= X_DIAG_PX * scale
    r = np.hypot(dx, dy)
    ext = float(np.percentile(r, 90))
    arm = on & (r >= 2.5 * scale)
    na = max(1, int(arm.sum()))
    q = [int((arm & ((dx > 0) == a) & ((dy > 0) == b)).sum()) / na
         for a in (False, True) for b in (False, True)]
    ok = (on.mean() >= X_DIAG_MIN and min(q) >= X_ARM_MIN
          and X_EXT[0] * scale <= ext <= X_EXT[1] * scale)
    return {"x": bool(ok), "frac": round(float(on.mean()), 3), "arms": round(min(q), 3),
            "ext": round(ext, 2), "n": int(len(px)), "cx": round(float(cx + x0), 1),
            "cy": round(float(cy + y0), 1), "why": None if ok else "shape"}


def minimap_x_marks(crop: np.ndarray, floor: Optional[np.ndarray], scale: float = 1.0) -> dict:
    """The death X marks of one minimap crop, both colours: the colour blobs
    (`extract_minimap_death_marks`), then `x_shape`.

    Returns `{"blue": [...], "red": [...], "red_other": [...]}`: each X is
    `{"x", "y", "area", "frac", "arms"}`; `red_other` holds the red blobs the
    shape test rejects, `(area, x, y)`, which a last-known mark or a ping may
    be.
    """
    blue, red = extract_minimap_death_marks(crop, floor)
    out: dict[str, list] = {"blue": [], "red": [], "red_other": []}
    for colour, found in (("blue", blue), ("red", red)):
        for a, bx, by in found:
            t = x_shape(crop, colour, bx, by, scale)
            if t["x"]:
                out[colour].append({"x": t["cx"], "y": t["cy"], "area": int(a),
                                    "frac": t["frac"], "arms": t["arms"]})
            elif colour == "red":
                out["red_other"].append((int(a), round(float(bx), 1), round(float(by), 1)))
    return out


#: An X bound to a death is born this near the killfeed time (ms).
X_BORN_MS = (-2000.0, 1000.0)
#: Detections of one X lie within this of each other (px * scale).
X_CLUSTER_PX = 4.0
#: The icon whose end makes the X lies within this of it (px * scale).
X_ICON_PX = 10.0
#: The icon's last frame lies in [first - X_ICON_BEFORE_MS, first + X_ORDER_TOL_MS];
#: the tolerance is one cache frame, since the icon's last frame may share the X's first.
X_ICON_BEFORE_MS = 1500.0
X_ORDER_TOL_MS = 70.0
#: An X holds its place [domain:minimap/death-mark-persistence]: seen on at
#: least X_AFTER_MIN of the frames in the X_HOLD_MS after its first, and on at
#: most X_BEFORE_MAX of those in the X_HOLD_MS ending 300 ms before it.
X_HOLD_MS = 3000.0
X_AFTER_MIN = 0.5
X_BEFORE_MAX = 0.2


def xmark_births(frames: list[dict], icons_at, *, rounds: list[dict],
                 scale: float = 1.0) -> list[dict]:
    """The X marks born in a session, per side, from stored frames only.

    `frames` are the `minimap_object` frame rows in time order, each with
    `x_marks` `{"blue": [...], "red": [...]}`, or a refusal `reason`;
    `icons_at(side, t_ms)` returns the stored icon centres `(x, y)` of a side
    at a frame time: the ally side reads `ally_icon` (ally and self fits), the
    enemy side `minimap_object`'s enemies. X detections cluster per round and
    colour; a cluster is born at its first frame and kept when it holds its
    place after that and was not there before. `icon_last_ms` is the last
    frame of a same-side icon at its place in the window before its birth
    [domain:minimap/death-icon-becomes-mark]; a birth without one keeps
    `icon_last_ms` None.
    """
    read = [f for f in frames if f.get("reason") is None and f.get("x_marks") is not None]
    out = []
    for rnd in rounds:
        a = rnd["t_start_ms"]
        z = rnd.get("t_close_ms") or rnd["t_end_ms"]
        inside = [f for f in read if a <= f["t_ms"] <= z]
        T = [f["t_ms"] for f in inside]
        for side, colour in (("ally", "blue"), ("enemy", "red")):
            clusters: list[dict] = []
            for f in inside:
                for q in f["x_marks"].get(colour, []):
                    c = next((c for c in clusters if math.hypot(c["x"] - q["x"], c["y"] - q["y"])
                              <= X_CLUSTER_PX * scale), None)
                    if c is None:
                        clusters.append({"x": q["x"], "y": q["y"], "seen": [f["t_ms"]]})
                    else:
                        c["seen"].append(f["t_ms"])
            for c in clusters:
                first = min(c["seen"])
                seen = set(c["seen"])
                after = [t for t in T if first <= t <= first + X_HOLD_MS]
                before = [t for t in T if first - X_HOLD_MS <= t <= first - 300.0]
                fa = sum(t in seen for t in after) / max(1, len(after))
                fb = sum(t in seen for t in before) / len(before) if before else 0.0
                if fa < X_AFTER_MIN or fb > X_BEFORE_MAX:
                    continue
                icon_last = None
                for t in T:
                    if first - X_ICON_BEFORE_MS <= t <= first + X_ORDER_TOL_MS and any(
                            math.hypot(ix - c["x"], iy - c["y"]) <= X_ICON_PX * scale
                            for ix, iy in icons_at(side, t)):
                        icon_last = t
                out.append({"side": side, "round_no": rnd["round_no"], "t_ms": first,
                            "x": round(float(c["x"]), 1), "y": round(float(c["y"]), 1),
                            "frames": len(seen), "frac_after": round(fa, 2),
                            "icon_last_ms": icon_last})
    return sorted(out, key=lambda b: (b["t_ms"], b["side"]))


def match_xmark(births: list[dict], side: str, t_ms: float, used: set) -> tuple:
    """The X birth that places a death of `side` at `t_ms`: `(birth, status)`.

    `placed` where exactly one unused birth of the side, born within
    `X_BORN_MS` of the death, follows an icon of the side at its place;
    `ambiguous` where more than one does; `x_without_icon` where births lie
    in the window and none follows an icon; `no_x_at_time` otherwise.
    """
    near = [b for b in births if b.get("side") == side and id(b) not in used
            and X_BORN_MS[0] <= b["t_ms"] - t_ms <= X_BORN_MS[1]]
    with_icon = [b for b in near if b.get("icon_last_ms") is not None]
    if len(with_icon) == 1:
        return with_icon[0], "placed"
    return None, ("ambiguous" if with_icon else "x_without_icon" if near else "no_x_at_time")


def stored_xmark_births(object_rows: list[dict], ally_rows: list[dict], rounds: list[dict],
                        scale: float) -> list[dict]:
    """`xmark_births` over stored streams: the `minimap_object` frames give the
    X marks and the enemy icons; the `ally_icon` stream gives the ally and
    self icons, taken from its frame nearest each X frame within
    `X_ORDER_TOL_MS`."""
    import bisect

    frames = sorted((r for r in object_rows if r.get("kind") == "frame"),
                    key=lambda r: r["t_ms"])
    enemy = {f["t_ms"]: [(e["x"], e["y"]) for e in f.get("enemies") or ()] for f in frames}
    ally: dict[int, list] = {}
    at: dict[int, float] = {}
    for r in ally_rows:
        if r.get("kind") == "frame":
            at[r["frame_idx"]] = r["t_ms"]
            if r.get("self"):
                ally.setdefault(r["frame_idx"], []).append((r["self"][0], r["self"][1]))
        elif r.get("kind") == "icon":
            ally.setdefault(r["frame_idx"], []).append((r["cx"], r["cy"]))
    order = sorted((t, i) for i, t in at.items())
    T = [t for t, _ in order]

    def icons_at(side, t):
        if side == "enemy":
            return enemy.get(t, ())
        k = bisect.bisect_left(T, t)
        best = min((j for j in (k - 1, k) if 0 <= j < len(T)), key=lambda j: abs(T[j] - t),
                   default=None)
        if best is None or abs(T[best] - t) > X_ORDER_TOL_MS:
            return ()
        return ally.get(order[best][1], ())

    return xmark_births(frames, icons_at, rounds=rounds, scale=scale)


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
    victim_name_claim: Optional[dict] = None,
    killer_name_claim: Optional[dict] = None,
    weapon_rests_on: Optional[list] = None,
) -> DeathVerdict:
    """Adjudicate victim identity, killer, and location for one death instant.

    `victim_depends_on` maps a channel to the death ids its name rested on, so
    the arbiter can refuse to count it as independent.

    `victim_name_claim` and `killer_name_claim` are the roles'
    `identity.name_cluster_claims`. A named one REPLACES the role's per-entry
    `killfeed_portrait` vote, which abstains with the name it gave in evidence:
    the cluster's ratio already holds this role's portrait views, and counting
    both would weigh them twice.

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

    # The name cluster: this role's portrait views pooled with its name's other
    # entries. A named cluster takes the portrait's vote.
    replaced = {}
    if victim_name_claim:
        witnesses.append(victim_name_claim)
        channels.append(NAME_CLUSTER_CHANNEL)
        if victim_name_claim.get("agent"):
            victim_candidates[NAME_CLUSTER_CHANNEL] = victim_name_claim["agent"]
            for ch in [c for c in victim_candidates if c == "killfeed_portrait"]:
                replaced[ch] = victim_candidates.pop(ch)

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
        named_cluster = bool(killer_name_claim and killer_name_claim.get("agent"))
        if killer_claim:
            said = killer_claim.get("agent")
            killer_claims.append(identity_claim(
                killer_id, None if named_cluster else said, channel="killfeed_portrait",
                reason=(f"replaced_by_name_cluster: per-entry said {said}"
                        if named_cluster else killer_claim.get("reason")),
                source_version=killer_claim.get("source_version"),
                evidence=(dict(killer_claim.get("evidence") or {}, per_entry_agent=said)
                          if named_cluster else killer_claim.get("evidence")),
                depends_on=None if named_cluster else killer_claim.get("depends_on")))
        if killer_name_claim:
            killer_claims.append(identity_claim(
                killer_id, killer_name_claim.get("agent"), channel=NAME_CLUSTER_CHANNEL,
                reason=killer_name_claim.get("reason"),
                source_version=killer_name_claim.get("source_version"),
                evidence=killer_name_claim.get("evidence")))
        elif killfeed_claim and killfeed_claim.get("killer"):
            killer_claims.append(identity_claim(killer_id, killfeed_claim["killer"],
                                                channel="killfeed_portrait"))
        # An ability icon names its caster: other pixels than the portraits, so
        # a witness that can disagree with them. A revive's "killer" is the
        # reviver, which the icon names the same way.
        caster = (caster_claim(killer_id, weapon, weapon_rests_on)
                  if death_cause == "ability" else None)
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
    # The portrait follow's seed, and the hud track a "track" seed rests on,
    # stay on the victim's portrait claim (`attach_stored_killfeed_portraits`).
    follow = {k: v for k, v in ((killfeed_claim or {}).get("evidence") or {}).items()
              if k in ("seed", "rests_on")} or None
    claims = [identity_claim(death_id, agent, channel=ch, depends_on=depends.get(ch),
                             evidence=follow if ch == "killfeed_portrait" else None)
              if ch != NAME_CLUSTER_CHANNEL else
              identity_claim(death_id, agent, channel=ch,
                             source_version=victim_name_claim.get("source_version"),
                             evidence=victim_name_claim.get("evidence"))
              for ch, agent in named_votes.items()]
    for w in witnesses:
        ch = w.get("channel")
        if ch in replaced:
            claims.append(identity_claim(
                death_id, None, channel=ch,
                reason=f"replaced_by_name_cluster: per-entry said {replaced[ch]}",
                evidence={"per_entry_agent": replaced[ch], **(follow or {})}))
        elif (ch in ("killfeed_portrait", "scoreboard_dim", NAME_CLUSTER_CHANNEL)
              and ch not in named_votes):
            claims.append(identity_claim(death_id, None, channel=ch, reason=w.get("reason"),
                                         evidence=(w.get("evidence")
                                                   if ch == NAME_CLUSTER_CHANNEL else
                                                   follow if ch == "killfeed_portrait"
                                                   else None),
                                         contest=w.get("contest")))
    identity = (adjudicate_agent_identity(claims) or [None])[0]
    status = identity["status"] if identity else "abstained"
    victim = identity["agent"] if identity else None
    reason = None
    if status == "disagreement":
        reason = f"witnesses disagree: {named_votes}"
    elif status == "abstained":
        reason = "no witness provided a confident candidate"
    elif status == "contested":
        reason = (f"{identity['reason']}: "
                  f"{sorted({a['agent'] for a in identity.get('alternatives', [])})}")

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


def _match_shrinks(entries: list[dict], ally_shrinks: list[dict], enemy_shrinks: list[dict],
                   max_dt_ms: float) -> list[dict | None]:
    """The roster drop each killfeed entry takes as its `roster_diff` witness,
    in entry order; None for none. A revive removes no one, so it takes none.

    An entry whose victim plate read a side takes, in entry order, the first
    drop on that side within `max_dt_ms` that no earlier entry took. An entry
    whose side went unread then takes the nearest drop of either side that no
    entry took: a drop a sided entry explains witnesses no second death. Keyed
    by its own side, the unread entry used to take the enemy drop a sided
    entry had already taken, and so escaped `refuse_unwitnessed`:
    b7d24102a6f6 1582.0 s, a third track of two kills, held the 1582.0 s
    enemy drop the 1581.5 s Reyna death held."""
    lists = {"ally": ally_shrinks, "enemy": enemy_shrinks}
    used: set[tuple[str, int]] = set()
    out: list[dict | None] = [None] * len(entries)
    unread = []
    for i, kf in enumerate(entries):
        if revive_entry(kf):
            continue
        side = entry_victim_side(kf)
        if side not in lists:
            unread.append(i)
            continue
        t = float(kf.get("t_ms", 0.0))
        for si, s in enumerate(lists[side]):
            if (side, si) not in used and abs(s["t_ms"] - t) <= max_dt_ms:
                out[i] = s
                used.add((side, si))
                break
    for i in unread:
        t = float(entries[i].get("t_ms", 0.0))
        free = [(abs(s["t_ms"] - t), side, si) for side, ls in lists.items()
                for si, s in enumerate(ls)
                if (side, si) not in used and abs(s["t_ms"] - t) <= max_dt_ms]
        if free:
            _, side, si = min(free)
            out[i] = lists[side][si]
            used.add((side, si))
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
    shrink_of = _match_shrinks(killfeed_entries, ally_shrinks, enemy_shrinks, max_dt_ms)
    used_xmarks: set[int] = set()
    death_ids = []
    for i, kf in enumerate(killfeed_entries):
        side_i = entry_victim_side(kf)
        # The stable key when the entry knows its slot; the list index only
        # for callers that never had one, since it moves with detection.
        death_ids.append(death_key(session_id, kf["t_ms"], kf["slot"]) if kf.get("slot") is not None
                         else f"death:{session_id}:{int(float(kf.get('t_ms', 0.0)))}:{side_i}:{i}")
    sorted_revives = sorted(all_revives, key=lambda r: float(r.get("t_ms", 0.0)))
    applied_revives = set()

    for i, kf in enumerate(killfeed_entries):
        t_ms = float(kf.get("t_ms", 0.0))
        side = entry_victim_side(kf)
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

        # The roster shrink `_match_shrinks` gave this entry.
        is_revive = revive_entry(kf)
        matched_shrink = shrink_of[i]

        # Match candidate minimap death mark
        # `xmarks` are `xmark_births`: one of the victim's side, born at its
        # time after an icon of that side at its place, and no other.
        matched_xmark = kf.get("location")
        xmark = None
        if matched_xmark is None and xmarks and side in ("ally", "enemy") and not is_revive:
            birth, xstatus = match_xmark(xmarks, side, t_ms, used_xmarks)
            xmark = {"status": xstatus, "frame": "minimap_crop", "birth": birth}
            if birth is not None:
                used_xmarks.add(id(birth))
                matched_xmark = (float(birth["x"]), float(birth["y"]))

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
            # The match's agents, both sides: a caster may be either team's.
            match_agents = ({r["agent"] for rows in (lineup or {}).get("sides", {}).values()
                             for r in rows if r.get("agent")} or None)
            w_verdict = classify_killfeed_icon(kf["icon_crop"], agents=match_agents)
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
            victim_name_claim=kf.get("name_claim"),
            killer_name_claim=kf.get("killer_name_claim"),
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
            weapon_rests_on=(kf.get("weapon_evidence") or {}).get("rests_on"),
        )
        if xmark is not None:
            verdict.metadata["xmark"] = xmark

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
            if identity and identity["status"] in ("resolved", "disagreement", "contested"):
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
        if identity and identity["status"] in ("resolved", "disagreement", "contested"):
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
                              weapon_observations: list[dict] | None = None,
                              name_observations: list[dict] | None = None,
                              reliability: dict | None = None,
                              xmarks: list[dict] | None = None,
                              store_root=None, stalls: list[dict] | None = None) -> dict:
    """Every round's deaths from stored data only; decodes no video.

    `stalls`, the session's capture-stall spans, count entries drawn at a
    stall's release (`session_entries`) and discount stall time when two
    deaths are tested as one entry. After the last pass, `merge_split_entries`
    folds each death that is an earlier death's second track into it and
    `refuse_unwitnessed` refuses each death nothing attests; each round then
    carries `merged` and `refused`, and the result `merges` and `refusals`.

    `xmarks` are the session's `xmark_births`; each round's verdicts may take
    a location from the births of that round only.

    Per round: the stored killfeed portraits against the official art, then the
    scoreboard's dimmed rows gated on the roster (`scoreboard_death_claims`).
    `portrait_exemplars` then takes the portraits of every death a non-portrait
    witness named, and the next pass also scores against those, never an
    entry's own, until the exemplar set stops changing. Returns the entries and
    verdicts per round of the last pass and the number of passes.

    `weapon_observations` are the stored `killfeed_weapon` rows; given them,
    `adjudication.weapon.entry_weapon` names each entry's weapon or ability and
    the entry carries its evidence. Without them no weapon is named, and no
    entry is a revive (`revive_entry`). `store_root` is the store whose mined
    weapon gallery names the icons; None means the default store.

    `name_observations` are the stored `killfeed_name` rows. Given them, the
    converged pass's roles are joined into name clusters
    (`killfeed_names.name_clusters`), the arbiter assigns each side's large
    clusters its agents (`identity.name_cluster_claims`, weighting the
    reference channels by the `reliability` table when given), and one final
    pass adjudicates every round with those claims in place of the roles'
    per-entry portrait votes. The result then carries `name_clusters`.
    """
    from ..reconciliation import board_alive_auditor, contradicted_openings
    from .scoreboard import scoreboard_openings
    from ..rounds import in_round_window
    from ..checks import sample_step_ms
    hud, roster = hud_table.to_pydict(), roster_table.to_pylist()
    player_agent = (lineup.get("player") or {}).get("agent")
    entries = session_entries(hud, second_life, stalls=stalls)
    step_ms = sample_step_ms(hud["t_ms"])

    def settle(rounds: list[dict]) -> dict:
        merges = merge_split_entries(rounds, stalls=stalls, step=step_ms)
        return {"merges": merges, "refusals": refuse_unwitnessed(rounds)}
    # Both sides: an icon's caster may be on either team (a revive, a team kill).
    agents = {r["agent"] for side in (lineup.get("sides") or {}).values()
              for r in side if r.get("agent")}
    with step("entry_weapons"):
        if weapon_observations is not None:
            kf_portraits = [r for r in portraits if r.get("kind") == "portrait_observation"]
            widths = icon_widths(weapon_observations)
            for e in entries:
                ev = entry_weapon(e, weapon_observations, store_root=store_root,
                                  agents=agents or None,
                                  key=death_key(session_id, e["t_ms"], e["slot"]))
                e["weapon_evidence"] = ev
                if ev["status"] == "resolved":
                    e["weapon"] = ev["name"]
                    e["death_cause"] = ev["category"]
                names = (entry_names(e, kf_portraits, widths, name_observations, session_id,
                                     others=entries)
                         if e.get("same_side") else (None, None))
                e["plate_names"] = names
                e["revive_witnesses"] = entry_witnesses(e, weapon_observations, names)
    audit_board = board_alive_auditor(hud_table, roster_table)
    xm: dict = {r["round_no"]: [] for r in rounds}
    for b in xmarks or ():
        xm.setdefault(b.get("round_no"), []).append(b)
    ends = {r["t_end_ms"] for r in rounds}
    sides, lineup_version = lineup.get("sides") or {}, lineup.get("version")
    base = [(r, type_round_entries(in_round_window(entries, r["t_start_ms"], r["t_end_ms"],
                                                   r.get("t_close_ms") or r["t_end_ms"], ends),
                                   sides, lineup_version=lineup_version)) for r in rounds]
    exemplars, keys, n = [], None, 0
    with step("passes"):
        while True:
            results = []
            for r, raw in base:
                a, z = r["t_start_ms"], r.get("t_close_ms") or r["t_end_ms"]
                with step("attach_portraits"):
                    entries = attach_stored_killfeed_portraits(raw, portraits, lineup, gallery,
                                                               source_version=source_version,
                                                               exemplars=exemplars,
                                                               weapon_observations=weapon_observations)
                window = [row for row in roster if a <= row["t_ms"] <= z]
                with step("verdict_first"):
                    first = adjudicate_round_deaths(session_id, entries, window,
                                                    player_agent=player_agent, xmarks=xm[r["round_no"]])
                with step("board_claims"):
                    openings = scoreboard_openings([row for row in board_rows
                                                    if a <= float(row.get("t_ms", -1)) <= z])
                    board = scoreboard_death_claims(
                        entries, openings, {i: v.victim for i, v in enumerate(first)},
                        {i for i, v in enumerate(first) if v.is_second_life},
                        contradicted_openings(audit_board(openings)), _named_by(first))
                with step("verdict_final"):
                    verdicts = adjudicate_round_deaths(session_id, entries, window,
                                                       player_agent=player_agent,
                                                       scoreboard_claims=board, xmarks=xm[r["round_no"]])
                results.append({"round_no": r["round_no"], "entries": entries, "verdicts": verdicts,
                                "collisions": board_collisions(session_id, r["round_no"], board)})
            n += 1
            harvested = portrait_exemplars([v for x in results for v in x["verdicts"]],
                                           [e for x in results for e in x["entries"]])
            new = {x["observation_key"] for x in harvested}
            if new == keys or n >= MAX_EXEMPLAR_PASSES:
                break
            keys, exemplars = new, harvested
    if name_observations is None:
        return {"rounds": results, "passes": n, **settle(results)}
    with step("name_clusters"):
        claims, summary = _name_cluster_claims(session_id, results, portraits, name_observations,
                                               lineup, gallery, reliability)
    final = []
    with step("final_pass"):
        for (r, _), x in zip(base, results):
            a, z = r["t_start_ms"], r.get("t_close_ms") or r["t_end_ms"]
            entries = [dict(e, name_claim=claims.get(v.death_id),
                            killer_name_claim=claims.get(f"{v.death_id}:killer"))
                       for e, v in zip(x["entries"], x["verdicts"])]
            window = [row for row in roster if a <= row["t_ms"] <= z]
            first = adjudicate_round_deaths(session_id, entries, window, player_agent=player_agent,
                                            xmarks=xm[r["round_no"]])
            if weapon_observations is not None:
                # Narrow each icon by its acting agent's kit, the agent named
                # without the icon, then adjudicate the round again on the result.
                with step("narrow_weapons"):
                    entries = [narrow_entry_weapon(e, v, weapon_observations, agents,
                                                   lineup.get("sides") or {}, session_id,
                                                   store_root)
                               for e, v in zip(entries, first)]
            # Type the round again with its verdicts' victim names: a Sage named
            # dead cannot revive, and a KAY/O revive needs his named down.
            entries = type_round_entries(
                entries, sides, lineup_version=lineup_version,
                victims={float(e["t_ms"]): (v.victim, v.death_id)
                         for e, v in zip(entries, first) if v.victim and not v.is_revive})
            first = adjudicate_round_deaths(session_id, entries, window,
                                            player_agent=player_agent, xmarks=xm[r["round_no"]])
            openings = scoreboard_openings([row for row in board_rows
                                            if a <= float(row.get("t_ms", -1)) <= z])
            board = scoreboard_death_claims(
                entries, openings, {i: v.victim for i, v in enumerate(first)},
                {i for i, v in enumerate(first) if v.is_second_life},
                contradicted_openings(audit_board(openings)), _named_by(first))
            verdicts = adjudicate_round_deaths(session_id, entries, window,
                                               player_agent=player_agent, scoreboard_claims=board,
                                               xmarks=xm[r["round_no"]])
            final.append({"round_no": r["round_no"], "entries": entries, "verdicts": verdicts,
                          "collisions": board_collisions(session_id, r["round_no"], board)})
    return {"rounds": final, "passes": n + 1, "name_clusters": summary, **settle(final)}


def _named_by(verdicts) -> dict[int, list]:
    """Per death index, the [channel, agent] pairs that named its victim."""
    return {i: [[ch, row["agent"]] for ch, row in
                ((v.metadata.get("identity") or {}).get("by_channel") or {}).items()
                if row.get("agent")] for i, v in enumerate(verdicts)}


def _name_cluster_claims(session_id, results, portraits, name_observations, lineup,
                         gallery, reliability) -> tuple[dict, dict]:
    """({entity_id: name-cluster claim}, summary) from one converged pass.

    Each role takes the portrait views its entry was followed through and the
    reference-channel claims its verdict holds that rest on no other verdict;
    the clusters and the names are their owners' (`killfeed_names`,
    `identity.name_cluster_claims`). Revives stay out: a revive's two names sit
    on one side, which the plate-side rule does not cover."""
    from .identity import name_cluster_claims, name_role_evidence
    from .killfeed_names import (KILLFEED_NAME_CLUSTER_VERSION, OTHER_SIDE, followed_views,
                                 name_clusters, role_crops)
    from .reliability import REFERENCE_CHANNELS
    by_key = {r["observation_key"]: r for r in portraits
              if r.get("kind") == "portrait_observation" and r.get("observation_key")}
    sides = lineup.get("sides", {})
    roles, evidence = [], {}
    for x in results:
        for e, v in zip(x["entries"], x["verdicts"]):
            if v.is_revive:
                continue
            obs = ((e.get("killer_claim") or {}).get("evidence") or {}).get("observations")                 or ((e.get("claim") or {}).get("evidence") or {}).get("observations") or []
            views = followed_views(obs, every=True)
            every = sorted({(float(o["t_ms"]), o["observation_key"]) for o in obs
                            if o.get("observation_key")})
            for role, key, team in (("killer", "killer_identity", OTHER_SIDE.get(v.side)),
                                    ("victim", "identity", v.side)):
                if team is None:
                    continue
                eid = f"{v.death_id}:killer" if role == "killer" else v.death_id
                roles.append({"entity_id": eid, "role": role, "team": team, "views": views})
                split = side_candidates(sides.get(team, []))
                admitted = split["named"] + split["rivals"]
                rows = []
                for _, k in every:
                    p = by_key.get(k.rsplit(":", 1)[0] + ":" + role)
                    if p is not None and ("ally" if p.get("ally") else "enemy") == team:
                        rows.append(p)
                verdict = v.metadata.get(key) or {}
                evidence[eid] = {
                    "portrait": name_role_evidence(rows, admitted, gallery) if admitted else None,
                    "channels": [(c["channel"], c["agent"]) for c in verdict.get("claims", [])
                                 if c["channel"] in REFERENCE_CHANNELS and c.get("agent")
                                 and c.get("agent") in admitted and not c.get("depends_on")]}
    crops = role_crops(roles, name_observations, session_id)
    clusters = name_clusters(crops)
    claims = name_cluster_claims(clusters, evidence, lineup, reliability=reliability,
                                 source_version=KILLFEED_NAME_CLUSTER_VERSION)
    summary = {"version": KILLFEED_NAME_CLUSTER_VERSION, "roles": len(roles),
               "clusters": {t: [len(c) for c in cl] for t, cl in clusters["sides"].items()},
               "left_out": dict(Counter(clusters["left_out"].values())),
               "claims": len(claims), "named": sum(1 for c in claims if c["agent"]),
               "channels_weighted": reliability is not None}
    return {c["entity_id"]: c for c in claims}, summary



# --- Deaths a capture stall swallowed, from how the round ended -------------

#: A stored round end this far after a stall's release still falls in it: the
#: round end the stall swallowed is read at the first frame after release.
STALL_ROUND_END_SLACK_MS = 1000.0
#: A round end read later than that, up to this long after release, still
#: fell in the gap when no sample between release and the end read the
#: scoring side's score: the first readable score already held the point.
#: Over the 21 Riot-scored matches the stored end follows the last kill of an
#: elimination round by a median 0.28 s, p95 3.0 s; 3694746e4e54's round 12
#: ended in its stall and its score was first read 4.4 s after release.
STALL_ROUND_END_READ_MS = 6000.0
#: A killfeed entry first seen inside the gap or this long after release,
#: naming a victim the rule infers, binds to the inferred death as its witness.
LATE_WITNESS_MS = 6000.0
#: The identity channel of a name the round's elimination implies.
ELIMINATION_CHANNEL = "round_elimination"


def _score_unread(hud, side_cols, a: float, b: float) -> bool:
    """True when no HUD sample in (a, b) reads a score in `side_cols`."""
    t = np.asarray(hud["t_ms"], dtype=np.float64)
    i, j = int(np.searchsorted(t, a, side="right")), int(np.searchsorted(t, b, side="left"))
    for col in side_cols:
        vals = hud[col][i:j]
        vals = vals.to_pylist() if hasattr(vals, "to_pylist") else list(vals)
        if any(v is not None for v in vals):
            return False
    return True


def _stall_holding(span_list, stored: dict, hud=None):
    """(the stall whose gap holds round `stored`'s end, how it is known), or
    (None, None): `release` where the end was read by
    `STALL_ROUND_END_SLACK_MS` after release; `score_unread_after_release`
    where it was read later, within `STALL_ROUND_END_READ_MS`, and no sample
    in between read the scoring side's score."""
    t_end = float(stored["t_end_ms"])
    won_left = stored.get("won_left")
    cols = (("score_left",) if won_left else ("score_right",)) if won_left is not None \
        else ("score_left", "score_right")
    for s in span_list or ():
        a, b = float(s["t_start_ms"]), float(s["t_end_ms"])
        if a <= t_end <= b + STALL_ROUND_END_SLACK_MS:
            return s, "release"
        if (hud is not None and b < t_end <= b + STALL_ROUND_END_READ_MS
                and _score_unread(hud, cols, b, t_end)):
            return s, "score_unread_after_release"
    return None, None


def _roster_before(roster, t0: float, t_start: float) -> dict | None:
    """The roster reader's last living counts in [t_start, t0), or None."""
    if roster is None:
        return None
    t = np.asarray(roster["t_ms"], dtype=np.float64)
    i = int(np.searchsorted(t, t0, side="left")) - 1
    if i < 0 or t[i] < t_start:
        return None
    return {"t_ms": float(t[i]), "ally": int(roster["alive_ally"][i]),
            "enemy": int(roster["alive_enemy"][i])}


def infer_stall_deaths(session_id: str, results: list[dict], rounds: list[dict], stall_spans,
                       outcome_claims: list[dict] | None, lineup: dict, roster=None,
                       hud=None) -> dict:
    """Deaths that fell in a capture stall where the round ended by elimination.

    For each stored round whose end lies in a stall's gap (`_stall_holding`:
    read at release, or read soon after it with the score unread in between,
    from the HUD table `hud`): when the round's
    outcome claim (`adjudication.round_outcome`) reads `elimination`, every
    member of the losing side still alive before the gap died in it. The
    living set is the killfeed prior: this round's resolved verdicts before
    the gap through `build_round_roster_timeline`, revives returning their
    agent. Each such member becomes one `inferred_death` row: `inferred:
    true`, `t_ms: null` with `t_ms_reason`, `t_window_ms` the gap, `killer:
    null` with `killer_reason: "unobserved interval"`, `rests_on` the prior's
    death ids and the outcome claim, and the victim named through the
    identity arbiter on channel `round_elimination`, `depends_on` the prior
    deaths (a name by elimination is never an independent witness).

    A killfeed verdict first seen inside the gap (a sample the stall span
    holds at its edge) or within `LATE_WITNESS_MS` after it
    that names one of these victims binds to it as `late_witness`; the
    inferred death keeps its window and the verdict keeps its own time.

    Refusals, one row per stalled round: `outcome_unread` (no claim, or the
    claim refused), `ended_by_<reason>` (not an elimination: the gap's deaths
    are unknown), `prior_count_disagrees` (the roster reader's last living
    count before the gap is not the prior's), `none_alive` (the prior already
    holds the side dead). An unknown stall list (None) infers nothing.

    Allies follow the same rule as enemies. Gaps inside a round that the
    roster difference shows are out of scope. Returns `{"inferred",
    "refused"}` row lists without session-common fields."""
    out = {"inferred": [], "refused": []}
    if not stall_spans:
        return out
    claims = {c["round_no"]: c for c in (outcome_claims or ())}
    by_round = {x["round_no"]: x for x in results}
    for r in sorted(rounds, key=lambda r: r["round_no"]):
        if r.get("t_end_ms") is None:
            continue
        stall, how = _stall_holding(stall_spans, r, hud)
        if stall is None:
            continue
        a, b = float(stall["t_start_ms"]), float(stall["t_end_ms"])
        claim = claims.get(r["round_no"])
        base = {"round_no": r["round_no"], "t_window_ms": [a, b], "end_in_gap": how,
                "outcome_claim": None if claim is None else claim.get("claim_id")}
        if claim is None or claim.get("refusal") or not claim.get("end_reason"):
            out["refused"].append({**base, "refusal": "outcome_unread",
                                   "claim_refusal": None if claim is None else claim.get("refusal")})
            continue
        if claim["end_reason"] != "elimination":
            out["refused"].append({**base, "refusal": f"ended_by_{claim['end_reason']}"})
            continue
        side = "enemy" if claim["winner"] == "ally" else "ally"
        x = by_round.get(r["round_no"], {"entries": [], "verdicts": []})
        before = [v for v in x["verdicts"] if v.t_ms < a]
        deaths = [v for v in before if not v.is_revive]
        revives = [{"t_ms": float(v.t_ms), "side": v.side, "agent": v.victim} for v in before
                   if v.is_revive and v.status == "resolved" and v.victim]
        snap = build_round_roster_timeline(lineup, deaths, r["round_no"],
                                           float(r.get("t_start_ms") or 0.0), revives=revives)[-1]
        living = list(snap.ally_agents if side == "ally" else snap.enemy_agents)
        prior_ids = [v.death_id for v in before]
        seen = _roster_before(roster, a, float(r.get("t_start_ms") or 0.0))
        base = {**base, "side": side, "prior_living": living, "prior_deaths": prior_ids,
                "roster_before": seen}
        if seen is not None and seen[side] != len(living):
            out["refused"].append({**base, "refusal": "prior_count_disagrees"})
            continue
        if not living:
            out["refused"].append({**base, "refusal": "none_alive"})
            continue
        late = [v for v in x["verdicts"] if a <= v.t_ms <= b + LATE_WITNESS_MS
                and not v.is_revive and v.side == side and v.status == "resolved" and v.victim]
        for agent in living:
            death_id = f"{session_id}:inferred:{r['round_no']}:{side}:{agent}"
            ident = adjudicate_agent_identity([identity_claim(
                death_id, agent, channel=ELIMINATION_CHANNEL,
                reason="alive_before_gap_side_eliminated", source_version=DEATH_ADJUDICATION_VERSION,
                evidence={"outcome_claim": claim["claim_id"], "prior_deaths": prior_ids},
                depends_on=prior_ids)])[0]
            witness = next((v for v in late if v.victim == agent), None)
            out["inferred"].append({
                **{k: base[k] for k in ("round_no", "t_window_ms", "end_in_gap",
                                        "outcome_claim", "side")},
                "death_id": death_id, "inferred": True, "victim": agent,
                "t_ms": None, "t_ms_reason": "died_in_capture_stall",
                "killer": None, "killer_reason": "unobserved interval",
                "rests_on": {"deaths": prior_ids, "outcome_claim": claim["claim_id"]},
                "identity": ident, "roster_before": seen,
                "late_witness": None if witness is None else
                {"death_id": witness.death_id, "t_ms": float(witness.t_ms)}})
    return out
