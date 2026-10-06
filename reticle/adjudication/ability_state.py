r"""The local player's kit as a state per slot: step 1 of the ability state model.

    .\.venv\Scripts\python.exe -m reticle ability-state <session> | --all [--record]

Owns [owns:ability-state].

`docs/ABILITY_STATE_MODEL.md` designs one record per ability slot, updated by
witnesses; this module builds its first step, the local player's four slots
from the tray alone. It decodes nothing. It reads the stored `tray_drop` rows,
the rounds table, the deaths and phases the tray gate already reads
(`ability_timeline.stored_gate_inputs`), the lineup's identity verdict for the
player's slot, and the tray's fills, which `tray` computes from the stored
crops of the `hud_abilities` ROI (the command reads them; this module is pure
over what it is handed). The drops carry only the two fills around each fall;
the fills carry what the drops cannot: a slot's level between drops, the teal
an equipped ability adds above it, whether the X bar is lit, and every rise.

**Who decides what.** The gate `ability_timeline.player_tray_casts` still
decides which drop is the player's cast, and this step keeps its behaviour:
each drop becomes a transition by the gate's verdict and reason, and the
state names what the refusal stood for (`STOOD_FOR`). The design's later steps
invert the dependency, so that the gate publishes claims and this model
decides the transition; the gate's stored verdicts are then the regression
set. The player's kit ends where the gate's does (`ability_timeline.kit_windows`,
`DEATH_LEAD_MS`). Two witnesses end it, each under its own reason: the
killfeed's death (`kit_frozen:after_player_death`) and the kit witness
(`adjudication.tray_kit`), whose icons show another agent's kit
(`kit:spectating:<agent>`) and whose first change in a round makes the owner
dead from then on (`owner_dead:kit_witness`) where the killfeed prints no
death (docs/TRAY_KIT_WITNESS.md). The agent is the identity arbiter's
verdict on the player's slot as the lineup stores it
(`adjudication.ult_cast.player_agent`), carried with its provenance and never
decided here; the slots' abilities are `lineup.abilities_for`'s.

**The reading, per readable sample and slot.** A sample is readable when it
lies in a round, before the kit ends, in a phase whose tray is the player's
(`READABLE_PHASES`), and the tray is drawn with clean guard rows (`tray`).
Otherwise every slot is `unreadable` with the first reason that applies, in
`UNREADABLE_REASONS` order. On a readable sample:

* C, Q and E read a level from the fill: full at `LEVEL_FULL_MIN` or more,
  empty at `HALF_MIN` or less, half between. A fill of `EQUIP_MIN` or more is
  teal an equipped ability adds over its bar; the level is then unread, and
  the charges are held from the last unequipped reading of the round, since
  an equip spends nothing and a release returns to the level it left.
* X is castable when its fill reaches `X_LIT_MIN`: the bar lights only while
  every pip is lit [domain:abilities/ult-slot-lights-when-castable], and the
  tray reader counts teal, not pips, so `pips` stays unread.

The level thresholds sit at the density minima of the fills, not at the
gate's `FULL_AFTER_MIN` and `FULL_MIN`: those test a drop's ends and lie on
the low tail of the full and lit levels, where a state read at them flickers
(`LEVEL_FULL_MIN`, `X_LIT_MIN`).

**Charges** come from the level and the slot's `max_charges`: a two-charge
slot reads 1.0, 0.5 and 0 [domain:hud/ability-tray-charge-segments]. The
count is a prior, weighed once (`charge_priors`). A `*-charges` fact of
`domain/abilities.toml` gives it first (`charge_facts`, source `player`,
whether the player or a measurement recorded it); where no fact speaks, the
wiki harvest the command hands in (`reference/abilities.json`, built by
`prototypes/ability_reference.py`) gives it: source `catalogue-confirmed`
where a fact confirms that harvest's counts
[domain:abilities/catalogue-charge-counts-confirmed], `catalogue` (a prior,
never an oracle) where none does. A fact outranks the catalogue: where both
give a count and differ, the fact's stands and the slot records the
`conflict`; a fact that makes the slot a resource bar, or one pool that
several slots share [domain:abilities/astra-stars-shared], refuses the
catalogue's count the same way. Every state row whose charges rest on a
count names its `charges_source`. Every rule is per ability
[domain:abilities/ability-rules-are-unique], so a slot with no count stores
`charges` null with the reason `no-fact:<agent>:<slot>:max_charges` (the
parameters say why the catalogue gave none) and only the range the reading
bounds: at least one where the bar is full, none where it is empty, and
anything up to `MAX_SEGMENTS_READ` where it reads half, since a half bar on a
slot of unknown kind need not be one charge of two. That top assumes a slot
without a count draws at most the two segments the reader interprets; a slot
without a count that holds more (Astra's stars, if she holds more than two)
falsifies it. A count above `MAX_SEGMENTS_READ` (Brimstone's Sky Smoke,
Chamber's Headhunter) is kept, never clamped, but the tray's drawing of it is
unobserved: its full and half bars store `charges` null with the reason
`segments_unobserved_above_two` and the range `[1, max]` or `[0, max]`, its
empty bar none (`charges_of`). An unreadable slot keeps the range
`[0, max]`, never a guess.
A regain of charges, within a round or between rounds, is recorded where the
tray shows it and never inferred.

**The bar's halves.** The tray reader also classes each half of a bar as
teal, gold, empty or unreadable (`tray.segment_classes`). The client draws a
charge that came back during the round as a gold segment
[domain:hud/ability-tray-restocked-charge-gold], which the teal fill cannot
see, so a C, Q or E level is the teal and gold halves over two wherever the
teal halves agree with the fill's level; where they disagree (a screen streak
lifting the teal count), the level is unread (`SEGMENTS_DISAGREE`) and the
charges are held. A rise in a live phase that adds a gold half, with no
player kill within `RETURN_KILL_MS` before it, is a `live_return`; its claim
carries both samples' halves and the kill check as evidence. What gold means
beyond that is the player's to say. Over the eight Sova sessions every Recon
Bolt spend watched for 51.5 s returned within 49 to 51.5 s
([metric:tray_segments/recon_bolt@all-sessions#t1_returned_49_51_5=7] of
[metric:tray_segments/recon_bolt@all-sessions#t1_watched_51_5=7]), the
returns' median at [metric:tray_segments/recon_bolt@all-sessions#median_s=50.0] s;
on the six Skye sessions Guiding Light's median was
[metric:tray_segments/guiding_light@all-sessions#median_s=49.73] s. On samples
with no gold half the level moved on
[metric:tray_segments/regression@all-sessions#nogold_level_changed=44] of
[metric:tray_segments/regression@all-sessions#nogold_readable_slot_samples=68130]
readable slot-samples. A live return needs a restock fact for the slot's
ability (`restock_facts`): gold was also seen on kits with none, and a gold
rise there is a `recharge` with its own surprise. The tray reader stores a
drop where a teal or gold half goes empty (`tray.drops`), a gold-only one
only where the countdown or the slot icon witnessed it or the spent half
read gold on `tray.GOLD_PERSIST_MIN` readable samples in a row before it
(`tray.gold_witness`), so spending a returned charge is a drop the gate
judges; a fall that takes a gold half with no drop stored (an unwitnessed
gold drop, a half unreadable on the later sample, or a fall across a gap)
stays `fall_without_a_drop` with its own surprise reason.

**The tray drawn.** A sample is drawn where some slot's teal fill shows
the tray, or every C, Q and E half reads as a bar class while the slot
icons witness the tray (`tray.drawn_mask`), which the command hands in as
`samples["drawn"]`. An all-spent tray (3694746e4e54 778.5-828.5 s) is drawn,
so a gold return onto it is read. On the 21 Riot-paired sessions, against
teal-only drops and the fill's drawn test, the gold falls with no drop went
from [metric:ability_state/gold@riot-21#gold_fell_without_a_drop_before=12] to
[metric:ability_state/gold@riot-21#gold_fell_without_a_drop_after=0]; the live returns on
Recon Bolt and Guiding Light from
[metric:ability_state/gold@riot-21#live_return_restock_abilities_before=12] to
[metric:ability_state/gold@riot-21#live_return_after=15]; and
[metric:ability_state/gold@riot-21#gold_rise_without_a_restock_fact_after=4] gold rises on
Phoenix's and Clove's kits became surprises.

**The reading against the count.** A half bar is the one observation of a
slot's segments: a count that draws a segment at half agrees with it, a
one-charge count disagrees. The coverage row counts both per slot
(`segments`); the reading stands either way, and a half bar on a one-charge
slot stores `charges` null with its reason, never a count the prior imposes.

**Rows**, stored whole as `events/ability_state/<sid>.jsonl`:

* one `coverage` row: every input's stamp, the agent's provenance, the kit and
  its parameters with the facts they came from, the source of each count, the
  conflicts between a fact and the catalogue, the slots still without a
  count, the half readings against each count (`segments`), counts, the
  unreadable reasons, the reproduction checks, and the invariant counts
  (`invariant_violations`);
* `claim` rows, raw observations: a drop (`tray_drop`), the gate's verdict on
  it (`player_cast`), a level change the fills show and the reader stores no
  drop for (`tray_fill`), and the end of the kit (`kit_end`), each with its
  observation time, the interval it happened in, its source stamp, a pointer
  to its evidence and what it `depends_on`;
* `verdict` rows: the transition, the state before and after, the witnesses
  that agreed and disagreed, the gate's `reason`, what that reason
  `stood_for`, and `surprise` with its reason where the reading contradicts
  the transition or no allowed transition explains a change;
* `state` rows: the per-slot record, one per run of samples that share a
  state, with `charges`, `charges_range`, `charges_source`, `level`, the
  fills, `mode` (idle, equipped, active, unreadable), `castable`, `pips`, `owner_alive`,
  `readable`, and `until_ms` where a duration fact dates an active span. An
  unread value is null with its reason.

What step 1 does not build: entities, the timer bar, audio, allies and enemies
(steps 2 to 5 of the design).
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np

from .. import tray
from ..agent_names import agent_key
from ..ability_timeline import (CAST_PHASES, DEATH_LEAD_MS, FULL_AFTER_MIN,
                                FULL_MIN, ULT_SLOT, round_window_of)
from ..version import ABILITY_STATE_VERSION
from .identity import AGENT_IDENTITY_VERSION
from .tray_kit import spectated_agent

SLOTS = tray.SLOT_KEYS
#: The phases whose tray is the player's kit: the gate's cast phases and the
#: buy phase, when charges are bought. After the round the tray dims
#: [domain:hud/tray-after-player-death].
READABLE_PHASES = ("buy_phase",) + tuple(CAST_PHASES)
#: The reasons a sample is unreadable, in the order they are tested.
UNREADABLE_REASONS = ("no_round", "kit_frozen:after_player_death", "kit:spectating",
                      "owner_dead:kit_witness", "phase", "tray_not_drawn",
                      "guard_rows_flooded")
#: The most fill of a C, Q or E slot read as an empty bar: inside the sparse
#: gap between the empty level (0 to 0.1) and the half level (from 0.35).
HALF_MIN = 0.25
#: The least fill of a C, Q or E slot read as a full bar: the density minimum
#: between the half and full levels, where the 0.65-0.70 bin holds
#: [metric:ability_state/level-edges@all-sessions#hist_C_0_65_to_0_7=1] (C),
#: [metric:ability_state/level-edges@all-sessions#hist_Q_0_65_to_0_7=3] (Q) and
#: [metric:ability_state/level-edges@all-sessions#hist_E_0_65_to_0_7=3] (E) of
#: [metric:ability_state/level-edges@all-sessions#hist_E_all=45899] samples each.
#: The gate's FULL_AFTER_MIN (0.75) sits on the full level's low tail: read
#: there, [metric:ability_state/level-edges@all-sessions#fall_without_a_drop_on_0_6_0_75=16]
#: of [metric:ability_state/level-edges@all-sessions#fall_without_a_drop=26]
#: level falls without a drop and both casts without a fall lay on 0.6-0.75.
LEVEL_FULL_MIN = 0.65
#: The least X fill read as a lit bar: midway across the gap between the
#: unlit pips and the lit bar, where 0.25-0.75 holds
#: [metric:ability_state/level-edges@all-sessions#hist_X_0_25_to_0_75=37] samples.
#: Read at the gate's FULL_MIN (0.8), the lit bar flickered dark:
#: [metric:ability_state/level-edges@all-sessions#x_unlit_without_a_drop_to_0_5_0_8=24]
#: of [metric:ability_state/level-edges@all-sessions#x_unlit_without_a_drop=26]
#: went dark to a fill of 0.5-0.8.
X_LIT_MIN = 0.5
#: The least fill read as teal over a lit bar, an equipped ability. The full
#: level spreads past 1.0 by the p90 normalisation and thins out through
#: 1.1-1.2; on the 20 sessions before the Iso capture the stored releases
#: start at or above it
#: ([metric:ability_state/step1@all-sessions-seven-facts#release_from_at_equip_min=120] of
#: [metric:ability_state/step1@all-sessions-seven-facts#release_drops=121]).
EQUIP_MIN = 1.2
#: Why a C, Q or E level is unread where the bar's half classes
#: (`tray.segment_classes`) disagree with the fill: the teal halves, as
#: halves of the bar, are not the fill's level. A cyan screen streak over the
#: bar lifts the teal count without drawing a teal half (`96aa1ae9b96f`
#: 672.0 s, `e37fdeca944f` 396.6 s); the charges are held from the slot's
#: last reading, as an equip holds them.
SEGMENTS_DISAGREE = "segments_disagree_with_fill"
#: Why a level is unread where a half is unreadable beside a gold half, or
#: while the slot held gold: the hidden half's gold is not known.
GOLD_HALF_UNREAD = "half_unreadable_beside_gold"
#: A player kill this long before a rise's earlier sample, or within its
#: interval, keeps the rise from being a live return (ms): a charge returned
#: on kills [domain:abilities/recharge-kinds] is then not ruled out. The
#: restock measurement's window (`prototypes/restock_measure.py`, KILL_S).
RETURN_KILL_MS = 3000.0
#: The most segments the reader interprets on a C, Q or E bar: a two-charge
#: slot draws two [domain:hud/ability-tray-charge-segments]. It bounds the
#: drawing the reader can read, not a slot's charges: Brimstone's Sky Smoke
#: holds three [domain:abilities/brimstone-sky-smoke-charges] and Chamber's
#: Headhunter eight [domain:abilities/chamber-headhunter-charges], and how the
#: tray draws either is unobserved. A count above it keeps its value and the
#: slot's segment reading is refused (`SEGMENTS_UNOBSERVED`).
MAX_SEGMENTS_READ = 2
#: Why a slot of more than `MAX_SEGMENTS_READ` charges stores no count per level.
SEGMENTS_UNOBSERVED = "segments_unobserved_above_two"
#: The count words a `*-charges` fact may use; digits parse too (`charge_facts`).
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_CHARGE_CLAUSE = re.compile(
    r"\b(" + "|".join(_COUNT_WORDS) + r"|\d+)\s+([^.,;]*?)\s+in slot ([CQEX])\b", re.I)
_POOL_SLOT = re.compile(r"\bin slot ([CQEX])\b")
#: The fact that confirms the wiki harvest's C, Q and E counts; its claim names
#: the harvest date it confirms, and a harvest of another date stays a prior.
CONFIRM_FACT = "abilities/catalogue-charge-counts-confirmed"
_CONFIRMED_HARVEST = re.compile(r"\bharvest of (\d{4}-\d{2}-\d{2})\b")
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*seconds?\b")
#: Where the command reads the wiki harvest, relative to the store root.
CATALOGUE_PATH = "reference/abilities.json"
#: The harvest's slot names and the tray keys they bind to
#: (`prototypes/ability_reference.py`, SLOT_KEY); the passive has no slot.
CATALOGUE_SLOTS = {"Grenade": "C", "Ability1": "Q", "Ability2": "E", "Ultimate": "X"}

#: What each of the gate's reasons stood for in the state, and the transition
#: its drop becomes. `phase:<name>` is looked up by its prefix.
STOOD_FOR = {
    None: ("cast", "a charge spent: the slot held one (the ult: the bar was lit), "
                   "its owner alive, in a live phase"),
    "no_round": ("none", "unreadable: outside every round"),
    "after_player_death": ("none", "kit frozen: the tray shows no kit of the player's"),
    "after_kit_change": ("none", "kit frozen: the tray's icons show another agent's kit"),
    "kit_not_player": ("none", "the tray's icons at the drop show another agent's kit"),
    "kit_owner_unresolved": ("unresolved", "the tray's icons name a kit, and the arbiter "
                                           "names no player agent to call it the player's"),
    "phase:buy_phase": ("unresolved", "the buy phase: a fall the gate does not read as a cast"),
    "phase": ("none", "unreadable: a phase whose tray is not the player's kit"),
    "forced": ("none", "unreadable: the tray is not drawn on the drop's sample"),
    "cooccur_among_casts": ("unresolved", "several slots fell together: a spectator "
                                          "switch, a flash or a dim, or casts beside one another"),
    "partial_charge": ("none", "the ult bar was not full before the fall: no cast"),
    "pips_lit": ("none", "the ult stayed castable: the bar did not empty"),
    "equip_release": ("unequip", "an equipped ability released: nothing spent"),
    "pool_rest": ("none", "the rest of a Regrowth pool the gate counted at its opening: "
                          "no new purchase [domain:abilities/skye-regrowth-gold-bar-partly-spent]"),
}


def charge_facts(facts: dict) -> dict:
    """{(agent key, slot): {"max_charges", "fact", "clause"}} from every fact
    in `domain/abilities.toml` whose id ends in `-charges`. The agent is the
    fact's subject before the colon; each "<count> <words> in slot <K>" clause
    of its claim gives one slot, the count a word from one to twelve or
    digits. Two facts that disagree on a slot leave it with `max_charges`
    None and the reason `conflicting-facts`."""
    out: dict = {}
    for key, f in sorted(facts.items()):
        if f.domain != "abilities" or not f.id.endswith("-charges") or ":" not in f.subject:
            continue
        agent = agent_key(f.subject.split(":")[0])
        for word, words, slot in _CHARGE_CLAUSE.findall(" ".join(f.claim.split())):
            n = int(word) if word.isdigit() else _COUNT_WORDS[word.lower()]
            got = out.get((agent, slot.upper()))
            if got and got["max_charges"] not in (None, n):
                out[(agent, slot.upper())] = {"max_charges": None, "fact": None,
                                              "clause": None,
                                              "reason": f"conflicting-facts:{got['fact']}:{key}"}
            elif not got:
                out[(agent, slot.upper())] = {"max_charges": n, "fact": key,
                                              "clause": f"{word} {words} in slot {slot}",
                                              "known": f.known, "reason": None}
    return out


def pool_facts(facts: dict) -> dict:
    """{(agent key, slot): fact key} from every fact in `domain/abilities.toml`
    whose id ends in `-resource-bar`: the slot draws a pool, not charges, so
    no count applies to it [domain:abilities/skye-regrowth-resource-bar]."""
    out = {}
    for key, f in sorted(facts.items()):
        if f.domain != "abilities" or not f.id.endswith("-resource-bar") or ":" not in f.subject:
            continue
        m = _POOL_SLOT.search(" ".join(f.claim.split()))
        if m:
            out[(agent_key(f.subject.split(":")[0]), m.group(1))] = key
    return out


def shared_pool_facts(facts: dict) -> dict:
    """{(agent key, slot): fact key} from every fact in `domain/abilities.toml`
    whose id ends in `-shared`: every slot its claim names ("in slot <K>")
    spends one pool that the named slots share, so no count per slot applies
    [domain:abilities/astra-stars-shared]."""
    out = {}
    for key, f in sorted(facts.items()):
        if f.domain != "abilities" or not f.id.endswith("-shared") or ":" not in f.subject:
            continue
        agent = agent_key(f.subject.split(":")[0])
        for slot in _POOL_SLOT.findall(" ".join(f.claim.split())):
            out[(agent, slot)] = key
    return out


def _confirmed_harvest(facts: dict) -> tuple[str | None, str | None, str | None]:
    """(the confirming fact's key, its `known`, the harvest date its claim
    names), or Nones where no fact confirms the harvest's counts
    [domain:abilities/catalogue-charge-counts-confirmed]."""
    f = facts.get(CONFIRM_FACT)
    if f is None:
        return None, None, None
    m = _CONFIRMED_HARVEST.search(" ".join(f.claim.split()))
    return CONFIRM_FACT, f.known, (m.group(1) if m else None)


def _catalogue_slots(catalogue: dict | None, path: str) -> dict:
    """{(agent key, slot): the harvest's entry} for every agent and slot of
    the wiki harvest, with the raw `charges` string it states."""
    out = {}
    for name, entry in sorted(((catalogue or {}).get("agents") or {}).items()):
        for a in entry.get("abilities") or []:
            slot = CATALOGUE_SLOTS.get(a.get("slot"))
            if slot is None:
                continue
            out[(agent_key(name), slot)] = {
                "path": path, "harvested": catalogue.get("harvested"), "agent": name,
                "ability": a.get("name"), "slot": a.get("slot"), "charges": a.get("charges")}
    return out


def _catalogue_count(cat: dict | None) -> tuple[int | None, str | None]:
    """(the harvest's count, or None with the reason it gives none)."""
    if cat is None or cat["charges"] is None:
        return None, "catalogue_missing"
    raw = str(cat["charges"]).strip()
    if not re.fullmatch(r"\d+", raw):
        return None, "catalogue_non_numeric"
    return int(raw), None


def charge_priors(facts: dict, *, catalogue: dict | None = None,
                  path: str = CATALOGUE_PATH) -> dict:
    """{(agent key, slot): the slot's charge count and where it came from},
    for every agent a charge fact or the catalogue names, and each of C, Q, E
    and X.

    Each entry holds `max_charges`, `source` (`player` for a per-ability
    domain fact, whether the player or a measurement recorded it,
    `catalogue-confirmed` for a wiki harvest count a domain fact confirms,
    `catalogue` for a harvest count nothing confirms, None without a count),
    the `fact` and its `known`, the `catalogue` entry (path, harvest date,
    agent, ability, raw `charges`), `reason` where no count applies, and
    `conflict` where a fact and the catalogue disagree. A fact outranks the
    catalogue:

    * a fact's count stands; a different catalogue count is a `count` conflict;
    * facts that disagree leave the slot without a count (`conflicting-facts`),
      and the catalogue does not settle a dispute between facts;
    * a resource-bar fact (`pool_facts`) leaves the slot without a count
      (`resource_bar`); a catalogue count there is a `resource_bar` conflict;
    * a shared-pool fact (`shared_pool_facts`) does the same (`shared_pool`,
      a `shared_pool` conflict) [domain:abilities/astra-stars-shared].

    Any count stands whatever its size: a count above `MAX_SEGMENTS_READ`
    bounds the reading, not the count (`charges_of`)
    [domain:hud/ability-tray-charge-segments].

    The player confirmed the harvest's C, Q and E counts
    [domain:abilities/catalogue-charge-counts-confirmed]. Where that fact is
    handed in and names the harvest's date, a harvest count takes the source
    `catalogue-confirmed` and the fact's key, and keeps its `catalogue` entry;
    the ult slot's text and a harvest of another date stay `catalogue`. A
    distinct source, rather than `player`, keeps a count the player confirmed
    in bulk apart from one a per-ability fact states, so a later harvest or a
    per-ability conflict points at the right witness.

    Without a fact the catalogue gives the count, or the reason it gives none:
    `no_fact` (no catalogue was handed in), `catalogue_missing` (no entry, or
    no `charges`), `catalogue_non_numeric` (a string that is not a count, such
    as the ult table's functions or "2 (shared charges)"). Reads neither
    stored data nor the model's output."""
    counts, pools = charge_facts(facts), pool_facts(facts)
    shared = shared_pool_facts(facts)
    confirm, confirm_known, confirm_date = _confirmed_harvest(facts)
    cat = _catalogue_slots(catalogue, path)
    agents = ({a for a, _s in counts} | {a for a, _s in pools} | {a for a, _s in shared}
              | {a for a, _s in cat})
    out = {}
    for agent in sorted(agents):
        for slot in SLOTS:
            got, c = counts.get((agent, slot)), cat.get((agent, slot))
            pool = pools.get((agent, slot))
            n_cat, why_cat = _catalogue_count(c) if catalogue is not None else (None, "no_fact")
            row = {"max_charges": None, "source": None, "fact": None, "known": None,
                   "clause": None, "catalogue": c, "reason": None, "conflict": None}
            if got is not None and got["max_charges"] is not None:
                row.update(max_charges=got["max_charges"], source="player", fact=got["fact"],
                           known=got.get("known"), clause=got["clause"])
                if n_cat is not None and n_cat != got["max_charges"]:
                    row["conflict"] = {"kind": "count", "player": got["max_charges"],
                                       "catalogue": n_cat, "fact": got["fact"]}
            elif got is not None:
                row["reason"] = got["reason"]
            elif pool is not None or (agent, slot) in shared:
                kind = "resource_bar" if pool is not None else "shared_pool"
                fact = pool if pool is not None else shared[(agent, slot)]
                row.update(fact=fact, reason=kind)
                if n_cat is not None:
                    row["conflict"] = {"kind": kind, "player": kind,
                                       "catalogue": n_cat, "fact": fact}
            elif n_cat is not None and slot != ULT_SLOT and confirm and (
                    confirm_date == (c or {}).get("harvested")):
                row.update(max_charges=n_cat, source="catalogue-confirmed", fact=confirm,
                           known=confirm_known)
            elif n_cat is not None:
                row.update(max_charges=n_cat, source="catalogue")
            else:
                row["reason"] = why_cat
            out[(agent, slot)] = row
    return out


def duration_facts(facts: dict) -> dict:
    """{(agent key, ability key): {"duration_ms", "fact", "about"}} from every
    fact in `domain/abilities.toml` whose id ends in `-duration`: the first
    "<n> seconds" of its claim. The subject is `<agent>:<ability>`."""
    out = {}
    for key, f in sorted(facts.items()):
        if f.domain != "abilities" or not f.id.endswith("-duration") or ":" not in f.subject:
            continue
        claim = " ".join(f.claim.split())
        m = _SECONDS.search(claim)
        if m:
            who, what = f.subject.split(":", 1)
            out[(agent_key(who), agent_key(what))] = {
                "duration_ms": float(m.group(1)) * 1000.0, "fact": key,
                "about": "about" in claim[:m.start()].lower()}
    return out


def restock_facts(facts: dict) -> dict:
    """{(agent key, ability key): fact key} from every fact in
    `domain/abilities.toml` whose id ends in `-restock` or
    `-restock-observed`: the ability's spent charge comes back by itself
    within the round [domain:abilities/sova-recon-bolt-restock-observed].
    The subject is `<agent>:<ability>`. A gold rise is a `live_return` only
    on an ability one of these names (`_fill_change`)."""
    out = {}
    for key, f in sorted(facts.items()):
        if (f.domain != "abilities" or ":" not in f.subject
                or not (f.id.endswith("-restock") or f.id.endswith("-restock-observed"))):
            continue
        who, what = f.subject.split(":", 1)
        out.setdefault((agent_key(who), agent_key(what)), key)
    return out


def slot_parameters(agent: str | None, kit: dict, facts: dict, *,
                    catalogue: dict | None = None, catalogue_path: str = CATALOGUE_PATH) -> dict:
    """Per slot: the ability, `max_charges` with its source (`charge_priors`),
    the fact or catalogue entry it came from or the reason it is unread, any
    conflict between a fact and the catalogue, a duration with its fact
    where one exists, and the restock fact (`restock_facts`) or the reason
    there is none. A catalogue count applies only where the catalogue names
    the kit's ability in that slot."""
    priors = charge_priors(facts, catalogue=catalogue, path=catalogue_path)
    durations = duration_facts(facts)
    restocks = restock_facts(facts)
    a = agent_key(agent)
    out = {}
    for slot in SLOTS:
        ability = kit.get(slot)
        row = {"ability": ability, "max_charges": None, "max_charges_fact": None,
               "max_charges_reason": None, "max_charges_source": None,
               "max_charges_known": None, "max_charges_catalogue": None,
               "max_charges_prior_reason": None, "max_charges_conflict": None,
               "duration_ms": None, "duration_about": None, "duration_fact": None,
               "duration_reason": None, "restock_fact": None, "restock_reason": None}
        if agent is None:
            row["max_charges_reason"] = row["duration_reason"] = "no_player_agent"
            row["restock_reason"] = "no_player_agent"
            out[slot] = row
            continue
        got = priors.get((a, slot))
        if got is not None:
            row["max_charges_catalogue"] = got["catalogue"]
            row["max_charges_conflict"] = got["conflict"]
        if slot == ULT_SLOT:
            row["max_charges_reason"] = "ult_slot:read_as_castable"
        elif got is None:
            row["max_charges_reason"] = f"no-fact:{a}:{slot}:max_charges"
            row["max_charges_prior_reason"] = ("no_fact" if catalogue is None
                                               else "catalogue_missing")
        elif got["source"] == "player":
            if ability and agent_key(ability) not in agent_key(got["clause"]):
                row["max_charges_reason"] = f"fact-names-another-ability:{got['fact']}"
            else:
                row.update(max_charges=got["max_charges"], max_charges_fact=got["fact"],
                           max_charges_source="player", max_charges_known=got["known"])
        elif got["reason"] and got["reason"].startswith("conflicting-facts"):
            row["max_charges_reason"] = got["reason"]
        elif got["source"] in ("catalogue", "catalogue-confirmed"):
            named = got["catalogue"]["ability"]
            if ability and agent_key(ability) != agent_key(named):
                row["max_charges_reason"] = f"no-fact:{a}:{slot}:max_charges"
                row["max_charges_prior_reason"] = f"catalogue-names-another-ability:{named}"
            else:
                row.update(max_charges=got["max_charges"], max_charges_source=got["source"])
                if got["source"] == "catalogue-confirmed":
                    row.update(max_charges_fact=got["fact"], max_charges_known=got["known"])
        else:
            row["max_charges_reason"] = f"no-fact:{a}:{slot}:max_charges"
            row["max_charges_prior_reason"] = (f"{got['reason']}:{got['fact']}" if got["fact"]
                                               else got["reason"])
        d = durations.get((a, agent_key(ability)))
        if d:
            row["duration_ms"], row["duration_fact"] = d["duration_ms"], d["fact"]
            row["duration_about"] = d["about"]
        else:
            row["duration_reason"] = f"no-fact:{a}:{slot}:duration"
        row["restock_fact"] = restocks.get((a, agent_key(ability))) if ability else None
        if row["restock_fact"] is None:
            row["restock_reason"] = f"no-fact:{a}:{slot}:restock"
        out[slot] = row
    return out


def charges_of(level: float | None, max_charges: int | None, reason: str | None):
    """(charges or None, the reason it is None, [lo, hi]) for a C, Q or E
    level; see the module docstring for the range of a slot with no fact.
    A slot of more than `MAX_SEGMENTS_READ` charges keeps its count as the
    range's top, but its full and half bars store no count
    (`SEGMENTS_UNOBSERVED`): the tray's drawing of it is unobserved
    [domain:hud/ability-tray-charge-segments]."""
    if level is None:
        return None, "unread_level", [0, max_charges or MAX_SEGMENTS_READ]
    if max_charges is None or max_charges > MAX_SEGMENTS_READ:
        top = max_charges or MAX_SEGMENTS_READ
        why = reason if max_charges is None else SEGMENTS_UNOBSERVED
        rng = {1.0: [1, top], 0.5: [0, top], 0.0: [0, 0]}[level]
        return (0 if level == 0.0 else None), (None if level == 0.0 else why), rng
    n = round(level * max_charges, 3)
    if n != int(n):
        return None, f"level_{level:g}_on_a_{max_charges}_charge_slot", [0, max_charges]
    return int(n), None, [int(n), int(n)]


def player_kit(agent: str | None, store_root) -> dict:
    """{slot: ability name} of the player's agent (`lineup.abilities_for`)."""
    from ..lineup import abilities_for
    return abilities_for(agent, store_root) if agent else {}


def player_agent_verdict(lineup: dict | None, session_id: str) -> dict:
    """The player's agent as the identity arbiter names it in the stored
    lineup (`ult_cast.player_agent`), with the verdict's provenance."""
    from .identity import player_identity
    from .ult_cast import player_agent
    name = player_agent(lineup, session_id)
    who = player_identity(lineup, session_id)
    eid = who["entity_id"]
    v = next((v for v in (lineup or {}).get("agent_identity") or []
              if v.get("entity_id") == eid), None) if eid else None
    return {"agent": name, "entity_id": eid,
            "status": v.get("status") if v else who["status"],
            "reason": v.get("reason") if v else who["reason"],
            "channels": v.get("channels") if v else None,
            "independent_channels": v.get("independent_channels") if v else None,
            "adjudication_version": v.get("adjudication_version") if v else None,
            "arbiter_current": bool(v) and v.get("adjudication_version") == AGENT_IDENTITY_VERSION,
            "lineup_version": (lineup or {}).get("version"),
            "board_state": (lineup or {}).get("board_state")}


def _context(ts, drawn, clean, kits, phase_of, spectated=()) -> list[dict]:
    """Per sample: its round, the owner's state and why it is unreadable.
    `spectated` are the stored spans of another agent's kit, (t_first_ms,
    t_last_ms, agent) (`adjudication.tray_kit.stored_kit_witness`); each kit
    window's `kit_change_ms` is the round's first kit change, and the owner is
    dead by it until the `kit_return_ms` after it, if any."""
    out = []
    for t, dr, ok in zip(ts, drawn, clean):
        k = round_window_of(t, kits)
        end = k["kit_end_ms"] if k else None
        frozen = end is not None and t >= end - DEATH_LEAD_MS
        change, back = (k.get("kit_change_ms"), k.get("kit_return_ms")) if k else (None, None)
        changed = change is not None and t >= change and (back is None or t < back)
        seen = spectated_agent(t, spectated)
        phase = phase_of(t)
        undone = [u for u in (k["undone_deaths"] if k else []) if u[0] <= t]
        why = ("no_round" if k is None
               else "kit_frozen:after_player_death" if frozen
               else f"kit:spectating:{seen}" if seen
               else "owner_dead:kit_witness" if changed
               else f"phase:{phase}" if phase not in READABLE_PHASES
               else "tray_not_drawn" if not dr
               else "guard_rows_flooded" if not ok else None)
        out.append({"t": float(t), "round": k["round_no"] if k else None,
                    "phase": phase, "unreadable": why, "spectating": seen,
                    "owner_alive": None if k is None else not (frozen or changed),
                    "owner_life": (None if k is None else "dead" if frozen
                                   else "dead:kit_witness" if changed
                                   else f"after_undone_death:{undone[-1][1]}" if undone
                                   else "first")})
    return out


def _reading(slot: str, f: float, halves=None) -> dict:
    """What one readable sample says of one slot, before charges are held.
    `halves` are the bar's two half classes (`tray.segment_classes`), or None
    where the caller read none: the level is then the fill's alone."""
    f = float(f)
    if slot == ULT_SLOT:
        lit = f >= X_LIT_MIN
        return {"level": 1.0 if lit else 0.0, "equipped": lit and f >= EQUIP_MIN,
                "castable": lit, "gold": None, "why": None}
    if f >= EQUIP_MIN:
        return {"level": None, "equipped": True, "castable": None, "gold": None,
                "why": "equipped:teal_over_the_bar"}
    level = 1.0 if f >= LEVEL_FULL_MIN else 0.5 if f > HALF_MIN else 0.0
    if halves is None:
        return {"level": level, "equipped": False, "castable": None, "gold": None, "why": None}
    teal, gold = list(halves).count("teal"), list(halves).count("gold")
    if teal / 2 != level:
        # The fill's teal is not the bar's: a streak or flash over the slot.
        return {"level": None, "equipped": False, "castable": None, "gold": None,
                "why": SEGMENTS_DISAGREE}
    return {"level": (teal + gold) / 2, "equipped": False, "castable": None, "gold": gold,
            "why": None}


def _state(slot, par, ctx, f, held, active_until, halves=None) -> dict:
    """The state of one slot at one sample. `held` is the slot's last
    unequipped reading in the round, which an equip keeps, and so does a
    reading whose halves disagree with the fill (`SEGMENTS_DISAGREE`)."""
    base = {"owner_alive": ctx["owner_alive"], "owner_life": ctx["owner_life"],
            "round": ctx["round"], "phase": ctx["phase"]}
    cap = par["max_charges"] or MAX_SEGMENTS_READ
    ult = slot == ULT_SLOT
    # The count's source, wherever the charges or their range rest on it.
    source = None if ult or par["max_charges"] is None else par.get("max_charges_source")
    base["charges_source"] = source
    pips = {"pips": None, "pips_reason": ("not_read:the_tray_reads_teal_not_pips" if ult
                                          else "not_an_ult_slot")}
    if ctx["unreadable"]:
        return {**base, **pips, "readable": [], "unreadable_reason": ctx["unreadable"],
                "level": None, "level_reason": ctx["unreadable"], "held_level": None,
                "fill": None, "halves": None, "gold": None, "charges": None,
                "charges_reason": par["max_charges_reason"] if ult else ctx["unreadable"],
                "charges_range": None if ult else [0, cap],
                "mode": "unreadable", "castable": None,
                "castable_reason": ctx["unreadable"] if ult else "not_an_ult_slot",
                "equipped": None, "until_ms": None, "until_reason": ctx["unreadable"]}
    r = _reading(slot, f, halves)
    if (not ult and r["level"] is not None and halves is not None
            and tray.SEG_UNREADABLE in halves and (r["gold"] or (held or {}).get("gold"))):
        # An unreadable half beside gold, or where the slot held gold, may hide
        # a gold charge: the gold count is unread, so the level is held.
        r = {**r, "level": None, "gold": None, "why": GOLD_HALF_UNREAD}
    held_level, gold = None, r["gold"]
    if ult:
        charges, why, rng = None, par["max_charges_reason"], None
    elif r["level"] is None:
        if held is None:
            charges, why, rng = None, (
                "equipped_before_a_reading_this_round" if r["equipped"]
                else f"{r['why']}_before_a_reading_this_round"), [0, cap]
        else:
            charges, why, rng = held["charges"], held["charges_reason"], list(held["charges_range"])
            held_level, gold = held["level"], held["gold"]
    else:
        charges, why, rng = charges_of(r["level"], par["max_charges"], par["max_charges_reason"])
    active = active_until is not None and ctx["t"] <= active_until
    mode = "equipped" if r["equipped"] else "active" if active else "idle"
    return {**base, **pips, "readable": ["tray"], "unreadable_reason": None,
            "level": r["level"], "level_reason": r["why"],
            "held_level": held_level, "fill": round(float(f), 3),
            "halves": list(halves) if halves is not None and not ult else None,
            "gold": gold, "charges": charges,
            "charges_reason": why, "charges_range": rng, "mode": mode,
            "castable": r["castable"], "castable_reason": None if ult else "not_an_ult_slot",
            "equipped": r["equipped"],
            "until_ms": active_until if active else None,
            "until_reason": None if active else (par["duration_reason"] or "not_active")}


#: The fields of a state that make it the same state; a record is a run of them.
_KEY = ("round", "phase", "readable", "unreadable_reason", "level", "level_reason",
        "held_level", "gold", "charges", "charges_reason", "charges_range", "mode", "castable",
        "equipped", "owner_alive", "owner_life", "until_ms")
#: The state fields a verdict's before and after carry.
_SNAP = ("level", "level_reason", "held_level", "fill", "halves", "gold", "charges",
         "charges_range", "charges_source", "mode", "castable", "equipped", "owner_alive",
         "readable", "unreadable_reason")


def _snap(states: list[dict], i: int | None, ts) -> dict | None:
    if i is None:
        return None
    return {"t_ms": float(ts[i]), **{k: states[i][k] for k in _SNAP}}


def _level(s: dict):
    """A C, Q or E reading's level, or the held one where the slot is equipped."""
    return s["level"] if s["level"] is not None else s.get("held_level")


def _fell(slot: str, sb: dict, sa: dict) -> bool:
    """Whether the later of two readable states is lower: the ult bar went
    dark, or a C, Q or E level (held through an equip) fell."""
    if slot == ULT_SLOT:
        return bool(sb["castable"]) and sa["castable"] is False
    lb, la = _level(sb), _level(sa)
    return lb is not None and la is not None and la < lb


def _drop_surprise(slot: str, transition: str, sb, sa, fell_at_t: bool) -> str | None:
    """Why the reading contradicts the transition a drop became, or None."""
    if transition == "cast":
        if sb is None:
            return "cast_with_no_reading_before"
        if slot == ULT_SLOT:
            if sb["castable"] is False:
                return "x_cast_from_an_unlit_bar"
            if sa is not None and sa["castable"]:
                return "x_cast_left_the_bar_lit"
            return None
        if sb["charges_range"][1] < 1:
            return "cast_without_a_charge"
        if sa is not None and not _fell(slot, sb, sa):
            return "cast_without_a_level_fall"
        return None
    if transition == "unequip" and sb is not None and sa is not None and _fell(slot, sb, sa):
        return "unequip_lowered_the_level"
    if transition == "unresolved" and fell_at_t:
        return "level_fell_without_a_cast"
    return None


def _fill_change(slot: str, sp: dict, sj: dict, phase: str, kill: bool | None = None,
                 restock: str | None = None):
    """(transition, surprise or None) for a change between two consecutive
    readable samples of one round that no drop covers, or None. A rise in a
    live phase that adds a gold half with no player kill near it (`kill`
    False; None where the kills went unread) is a `live_return`
    [domain:hud/ability-tray-restocked-charge-gold] on an ability with a
    restock fact (`restock`, `restock_facts`); on any other ability it stays
    a `recharge` with the surprise `gold_rise_without_a_restock_fact`, since
    gold was seen on other kits' slots and what it means there is the
    player's to say. Any other rise outside the buy phase stays a
    `recharge`. A fall that takes a gold half where the tray reader stored
    no drop (a half it could not read, or a fall across a gap) stays a
    surprise."""
    if not sp["equipped"] and sj["equipped"]:
        dry = slot != ULT_SLOT and sp["charges_range"][1] < 1
        return "equip", ("equip_without_a_charge" if dry else None)
    if sp["equipped"] and not sj["equipped"]:
        if _fell(slot, sp, sj):
            return "unequip", "unequip_lowered_the_level_without_a_drop"
        return "unequip", None
    if slot == ULT_SLOT:
        if sp["castable"] is False and sj["castable"]:
            return "ult_ready", None
        if sp["castable"] and sj["castable"] is False:
            return "unlit_without_a_drop", "x_bar_went_dark_without_a_drop"
        return None
    lp, lj = _level(sp), _level(sj)
    if lp is None or lj is None or lp == lj:
        return None
    gp, gj = sp.get("gold") or 0, sj.get("gold") or 0
    if lj > lp:
        if phase == "buy_phase":
            return "buy", None
        if gj > gp and phase in CAST_PHASES and kill is False:
            if restock is None:
                return "recharge", "gold_rise_without_a_restock_fact"
            return "live_return", None
        return "recharge", None
    if gj < gp:
        return "fall_without_a_drop", "gold_charge_fell_without_a_drop"
    return "fall_without_a_drop", "level_fell_without_a_drop"


#: The audio witness's fields an `audio` claim carries as evidence.
AUDIO_FIELDS = ("best", "score", "runner_up", "runner_up_score", "margin", "threshold",
                "reason", "verdict", "scores", "slot_referenced", "params_version",
                "best_ref", "margin_ref", "p_right", "p_right_reason", "calibration_basis",
                "phase")
#: The audio witness's window opens this long before the drop (ms).
PRE_MS = 2000.0


def _verdict(common, slot, t, transition, *, reason=None, stood_for=None, claims=(),
             agreed=(), disagreed=(), before=None, after=None, surprise=None,
             owner_alive=None, until_ms=None, until_fact=None) -> dict:
    return {**common, "kind": "verdict", "slot": slot, "t_ms": float(t),
            "transition": transition, "reason": reason, "stood_for": stood_for,
            "claims": list(claims), "agreed": list(agreed), "disagreed": list(disagreed),
            "before": before, "after": after, "owner_alive_at_t": owner_alive,
            "surprise": surprise is not None, "surprise_reason": surprise,
            "until_ms": until_ms, "until_fact": until_fact}


def adjudicate(session_id: str, *, drops: list[dict], gate_rows: list[dict],
               kits: list[dict], phase_of, samples: dict, agent: dict, params: dict,
               inputs: dict, checks: dict | None = None, spectated=(),
               audio: dict | None = None, kills_ms=None) -> list[dict]:
    """The session's coverage, claim, verdict and state rows.

    `drops` are the stored `tray_drop` drop rows and `gate_rows` the gate's
    verdicts on them (`player_tray_casts`), in the same order; `kits` are
    `ability_timeline.kit_windows`; `samples` holds the tray's real samples
    (no separator rows): `t_ms`, `fills` (n x 4), `drawn` and `clean`, and
    optionally `halves`, each sample's half classes (n x 4 x 2,
    `tray.segment_classes`), without which a level is the fill's alone;
    `kills_ms` are the player's kills (`ability_timeline.stored_gate_inputs`),
    none of which may fall in a rise's interval or `RETURN_KILL_MS` before it
    for the rise to be a live return (None: unread, and no rise is one);
    `agent` is `player_agent_verdict`; `params` is `slot_parameters`;
    `inputs` are the input stamps; `checks` are the reproduction checks the
    caller measured; `spectated` are the stored spans of another agent's kit
    (`_context`); `audio` is the audio witness on the gate's casts
    (`ability_timeline.audio_cast_witness`): each cast's verdict carries its
    row as an `audio` claim, in `agreed` or `disagreed` only where the
    witness named a slot, and the state never reads it. Deterministic in its
    inputs."""
    ts = [float(t) for t in samples["t_ms"]]
    fills = np.asarray(samples["fills"], float).reshape(len(ts), len(SLOTS))
    halves = samples.get("halves")
    kills = None if kills_ms is None else np.sort(np.asarray(kills_ms, float))
    ctx = _context(ts, samples["drawn"], samples["clean"], kits, phase_of, spectated)
    at = {t: i for i, t in enumerate(ts)}
    common = {"session_id": session_id, "ability_state_version": ABILITY_STATE_VERSION}
    death_src = {k: inputs.get(k) for k in ("hud", "death", "killfeed_portrait",
                                            "combat_report_round", "round")}
    claims, verdicts, records = [], [], []
    heard = {(r["slot"], float(r["t_ms"])): r for r in (audio or {}).get("rows", [])}

    def claim(slot, t, witness, observed, since, evidence, version, depends_on=()):
        cid = f"{session_id}:{slot}:{t:.0f}:{witness}"
        claims.append({**common, "kind": "claim", "claim_id": cid, "slot": slot,
                       "witness": witness, "observed": observed, "observed_at_ms": float(t),
                       "interval_ms": [float(since), float(t)], "source_version": version,
                       "evidence": evidence, "depends_on": sorted(depends_on)})
        return cid

    def ctx_at(t):
        return (ctx[at[t]] if t in at
                else _context([t], [True], [True], kits, phase_of, spectated)[0])

    for k, slot in enumerate(SLOTS):
        par = params[slot]
        mine = [(d, g) for d, g in zip(drops, gate_rows) if d["slot"] == slot]
        casts_at = {float(g["t_ms"]) for _d, g in mine if g["player_cast"]}
        # The state at every sample: an equip holds the charges it found, and
        # an accepted cast of an ability with a duration fact opens its span.
        states, held, active_until = [], None, None
        for i, c in enumerate(ctx):
            if states and c["round"] != states[-1]["round"]:
                held, active_until = None, None
            if c["t"] in casts_at and par["duration_ms"]:
                active_until = c["t"] + par["duration_ms"]
            s = _state(slot, par, c, fills[i, k], held, active_until,
                       None if halves is None else halves[i][k])
            if s["readable"] and not s["equipped"] and slot != ULT_SLOT:
                held = s
            states.append(s)
        readable = [i for i, s in enumerate(states) if s["readable"]]
        r_ts = [ts[i] for i in readable]

        def before(t, rnd):
            j = int(np.searchsorted(r_ts, t, side="left")) - 1
            return readable[j] if j >= 0 and ctx[readable[j]]["round"] == rnd else None

        def after(t, rnd):
            j = int(np.searchsorted(r_ts, t, side="left"))
            return (readable[j] if j < len(readable) and ctx[readable[j]]["round"] == rnd
                    else None)

        # Each drop: the reader's fall and the gate's verdict as claims, and
        # the transition the verdict stands for.
        for d, g in mine:
            t = float(d["t_ms"])
            why = g["reason"]
            key = (why if why in STOOD_FOR
                   else "phase" if str(why).startswith("phase:") else why)
            transition, stood = STOOD_FOR.get(key, ("unresolved", f"unknown_reason:{why}"))
            c = ctx_at(t)
            b, a = before(t, c["round"]), after(t, c["round"])
            sb, sa = _snap(states, b, ts), _snap(states, a, ts)
            # The fall happened after the last readable sample of the slot: a
            # drop across a refused gap is uncertain over the whole gap.
            i_t = at.get(t)
            prev = sb["t_ms"] if sb is not None else (ts[i_t - 1] if i_t else t)
            ev = {"stream": "tray_drop", "t_ms": t, "slot": slot,
                  **{f: d.get(f) for f in ("from", "to", "forced", "cooccur", "across_gap")}}
            c1 = claim(slot, t, "tray_drop", "fall", prev, ev, inputs.get("tray_drop"))
            c2 = claim(slot, t, "player_cast", "cast" if g["player_cast"] else "refused",
                       prev, {**ev, "reason": why, "kit_end_ms": g.get("kit_end_ms"),
                              "first_player_death_ms": g.get("first_player_death_ms")},
                       inputs.get("player_cast"), depends_on=[c1])
            fell_at_t = (sb is not None and sa is not None and sa["t_ms"] == t
                         and _fell(slot, sb, sa))
            agreed, disagreed = ["tray_drop", "player_cast"], []
            ids = [c1, c2]
            h = heard.get((slot, t)) if g["player_cast"] else None
            if h is not None:
                ids.append(claim(
                    slot, t, "audio", h.get("verdict") or f"refused:{h['reason']}",
                    t - PRE_MS, {"stream": "ability_audio",
                                 **{f: h.get(f) for f in AUDIO_FIELDS}},
                    h.get("ability_audio_version"), depends_on=[c2]))
                if h.get("verdict") is not None:
                    (agreed if h["verdict"] == slot else disagreed).append("audio")
            if transition in ("cast", "unequip") and sb is not None and sa is not None:
                fell = _fell(slot, sb, sa)
                (agreed if fell == (transition == "cast") else disagreed).append("tray_fill")
            dur = transition == "cast" and par["duration_ms"]
            verdicts.append(_verdict(
                common, slot, t, transition, reason=why, stood_for=stood, claims=ids,
                agreed=agreed, disagreed=disagreed, before=sb, after=sa,
                surprise=_drop_surprise(slot, transition, sb, sa, fell_at_t),
                owner_alive=c["owner_alive"],
                until_ms=t + par["duration_ms"] if dur else None,
                until_fact=par["duration_fact"] if dur else None))

        # Changes the fills show between consecutive readable samples that no
        # drop covers: equips, releases, rises, a fall the reader did not
        # store, and a regain or loss across a round's end.
        dropped = {float(d["t_ms"]) for d, _g in mine}
        for p, j in zip(readable, readable[1:]):
            t, sp, sj = ts[j], states[p], states[j]
            if t in dropped:
                continue
            if ctx[p]["round"] != ctx[j]["round"]:
                change = (None if _level(sp) == _level(sj) and sp["castable"] == sj["castable"]
                          else ("refill_between_rounds", None)
                          if (slot == ULT_SLOT and sj["castable"]) or
                          (slot != ULT_SLOT and (_level(sj) or 0) > (_level(sp) or 0))
                          else ("fall_between_rounds", None))
                stood = "a regain or loss between rounds, observed, per ability"
            else:
                near = (None if kills is None else
                        kills[(kills >= ts[p] - RETURN_KILL_MS) & (kills <= t)])
                kill = None if near is None or not len(near) else float(near[-1])
                change = _fill_change(slot, sp, sj, ctx[j]["phase"],
                                      kill=None if kills is None else kill is not None,
                                      restock=par.get("restock_fact"))
                stood = None
            if change is None:
                continue
            transition, surprise = change
            ev = {"stream": "hud_abilities crops", "t_before_ms": ts[p],
                  "fill_before": sp["fill"], "fill_after": sj["fill"],
                  "round_before": sp["round"], "round_after": sj["round"]}
            gold_seen = transition in ("live_return", "recharge") or (
                surprise == "gold_charge_fell_without_a_drop")
            if gold_seen and ctx[p]["round"] == ctx[j]["round"]:
                ev.update({"halves_before": sp["halves"], "halves_after": sj["halves"],
                           "gold_before": sp["gold"], "gold_after": sj["gold"],
                           "player_kill_ms": kill,
                           "kills": "unread" if kills is None else "read",
                           "restock_fact": par.get("restock_fact")})
            cid = claim(slot, t, "tray_fill", transition, ts[p], ev,
                        inputs.get("tray_segment") if "halves_after" in ev
                        else inputs.get("tray_fill"))
            verdicts.append(_verdict(common, slot, t, transition, stood_for=stood,
                                     claims=[cid], agreed=["tray_fill"],
                                     before=_snap(states, p, ts), after=_snap(states, j, ts),
                                     surprise=surprise, owner_alive=ctx[j]["owner_alive"]))

        # The kit's end in each round, and the deaths the game undid before it.
        for kw in kits:
            rnd = kw["round_no"]
            for t_u, why in kw["undone_deaths"]:
                t_u = float(t_u)
                cid = claim(slot, t_u, "undone_death", why, t_u,
                            {"stream": "death", "t_ms": t_u, "why": why, "round": rnd},
                            death_src)
                verdicts.append(_verdict(
                    common, slot, t_u, "second_life" if why == "run_it_back" else "revive",
                    reason=why, stood_for="the kit is kept", claims=[cid],
                    agreed=["undone_death"], before=_snap(states, before(t_u, rnd), ts),
                    after=_snap(states, after(t_u, rnd), ts), owner_alive=True))
            change = kw.get("kit_change_ms")
            if kw["kit_end_ms"] is None and change is None:
                continue
            # The killfeed's end and the kit witness's change are separate
            # claims; the killfeed's dates the verdict where it exists, and a
            # change before its freeze disagrees with it.
            ids, agreed, disagreed = [], [], []
            if kw["kit_end_ms"] is not None:
                end = float(kw["kit_end_ms"])
                frozen = end - DEATH_LEAD_MS
                ids.append(claim(slot, end, "kit_end", "owner_death", frozen,
                                 {"stream": "death", "kit_end_ms": end,
                                  "frozen_from_ms": frozen, "round": rnd}, death_src))
                agreed.append("kit_end")
            if change is not None:
                change = float(change)
                ids.append(claim(slot, change, "tray_kit", "kit_change", change,
                                 {"stream": "tray_kit", "kit_change_ms": change, "round": rnd},
                                 inputs.get("tray_kit")))
                (disagreed if kw["kit_end_ms"] is not None and change < frozen
                 else agreed).append("tray_kit")
            if kw["kit_end_ms"] is None:
                end, frozen = change, change
            verdicts.append(_verdict(
                common, slot, end, "owner_death",
                reason=None if kw["kit_end_ms"] is not None else "owner_dead:kit_witness",
                stood_for="the kit freezes until the round ends",
                claims=ids, agreed=agreed, disagreed=disagreed,
                before=_snap(states, before(frozen, rnd), ts), owner_alive=False))

        records += _records(slot, par, states, ts, agent, common)

    claims.sort(key=lambda r: (r["observed_at_ms"], SLOTS.index(r["slot"]), r["claim_id"]))
    verdicts.sort(key=lambda r: (r["t_ms"], SLOTS.index(r["slot"]), r["transition"]))
    records.sort(key=lambda r: (r["t_first_ms"], SLOTS.index(r["slot"])))
    rows = claims + verdicts + records
    cov = _coverage(rows, ctx, params, agent, inputs, checks or {}, common, len(drops))
    if audio is not None:
        heard_claims = [r for r in claims if r["witness"] == "audio"]
        cov["audio"] = {**audio["coverage"], "claims": len(heard_claims),
                        "agreed": sum("audio" in v["agreed"] for v in verdicts),
                        "disagreed": sum("audio" in v["disagreed"] for v in verdicts),
                        "refused": dict(sorted(Counter(
                            r["observed"] for r in heard_claims
                            if r["observed"].startswith("refused:")).items()))}
    return [cov] + rows


def _records(slot, par, states, ts, agent, common) -> list[dict]:
    """Runs of samples that share a state, one `state` row each."""
    out = []
    keyed = [tuple(repr(s[f]) for f in _KEY) for s in states]
    i = 0
    while i < len(states):
        j = i
        while j + 1 < len(states) and keyed[j + 1] == keyed[i]:
            j += 1
        s = states[i]
        got = [states[m]["fill"] for m in range(i, j + 1) if states[m]["fill"] is not None]
        out.append({**common, "kind": "state", "slot": slot, "ability": par["ability"],
                    "agent": agent.get("agent"), "agent_entity_id": agent.get("entity_id"),
                    "round": s["round"], "phase": s["phase"],
                    "t_first_ms": ts[i], "t_last_ms": ts[j], "samples": j - i + 1,
                    "readable": s["readable"], "unreadable_reason": s["unreadable_reason"],
                    "level": s["level"], "level_reason": s["level_reason"],
                    "held_level": s["held_level"], "gold": s["gold"],
                    "fills": ({"min": min(got), "median": round(float(np.median(got)), 3),
                               "max": max(got)} if got else None),
                    # The half classes the run's samples read, and how many each.
                    "halves": (dict(sorted(Counter(
                        "/".join(states[m]["halves"]) for m in range(i, j + 1)
                        if states[m]["halves"] is not None).items())) or None),
                    "charges": s["charges"], "charges_reason": s["charges_reason"],
                    "charges_range": s["charges_range"], "charges_source": s["charges_source"],
                    "max_charges": par["max_charges"],
                    "max_charges_fact": par["max_charges_fact"],
                    "mode": s["mode"], "equipped": s["equipped"],
                    "castable": s["castable"], "castable_reason": s["castable_reason"],
                    "pips": s["pips"], "pips_reason": s["pips_reason"],
                    "owner_alive": s["owner_alive"], "owner_life": s["owner_life"],
                    "until_ms": s["until_ms"], "until_reason": s["until_reason"],
                    "until_fact": par["duration_fact"] if s["until_ms"] else None})
        i = j + 1
    return out


def _coverage(rows, ctx, params, agent, inputs, checks, common, n_drops) -> dict:
    states = [r for r in rows if r["kind"] == "state"]
    verdicts = [r for r in rows if r["kind"] == "verdict"]
    unread, by_phase, by_kit = Counter(), Counter(), Counter()
    for r in states:
        why = r["unreadable_reason"]
        if why:
            unread["phase" if why.startswith("phase:")
                   else "kit:spectating" if why.startswith("kit:spectating:")
                   else why] += r["samples"]
            if why.startswith("phase:"):
                by_phase[why] += r["samples"]
            if why.startswith("kit:spectating:"):
                by_kit[why] += r["samples"]
    cqe_readable = [r for r in states if r["readable"] and r["slot"] != ULT_SLOT]
    cov = {**common, "kind": "coverage",
           "tray_version": inputs.get("tray_drop"),
           "player_cast_version": inputs.get("player_cast"),
           "inputs": dict(sorted(inputs.items())), "checks": dict(sorted(checks.items())),
           "agent": agent, "kit": {s: params[s]["ability"] for s in SLOTS},
           "parameters": params,
           "thresholds": {"HALF_MIN": HALF_MIN, "LEVEL_FULL_MIN": LEVEL_FULL_MIN,
                          "EQUIP_MIN": EQUIP_MIN, "X_LIT_MIN": X_LIT_MIN,
                          "DEATH_LEAD_MS": DEATH_LEAD_MS},
           "gate_thresholds": {"FULL_AFTER_MIN": FULL_AFTER_MIN, "FULL_MIN": FULL_MIN},
           "readable_phases": list(READABLE_PHASES),
           "samples": len(ctx), "slot_samples": sum(r["samples"] for r in states),
           "readable_slot_samples": sum(r["samples"] for r in states if r["readable"]),
           "unreadable_slot_samples": dict(sorted(unread.items())),
           "unreadable_by_phase": dict(sorted(by_phase.items())),
           "unreadable_by_kit": dict(sorted(by_kit.items())),
           # Samples (not slot-samples) the kit witness puts in another
           # agent's kit, and how many of them the killfeed already froze.
           "kit_witness": {
               "samples_spectating": sum(c["spectating"] is not None for c in ctx),
               "samples_spectating_killfeed_frozen": sum(
                   c["spectating"] is not None
                   and c["unreadable"] == "kit_frozen:after_player_death" for c in ctx),
               "samples_after_kit_change_only": sum(
                   c["owner_life"] == "dead:kit_witness" for c in ctx)},
           # The bar's half classes on readable C, Q and E samples: those
           # with a gold half, and those whose halves disagree with the fill.
           "gold_readable_slot_samples": sum(r["samples"] for r in cqe_readable
                                             if r["level"] is not None and r["gold"]),
           "segments_disagree_slot_samples": sum(r["samples"] for r in cqe_readable
                                                 if r["level_reason"] == SEGMENTS_DISAGREE),
           "gold_half_unread_slot_samples": sum(r["samples"] for r in cqe_readable
                                                if r["level_reason"] == GOLD_HALF_UNREAD),
           "charges_unread_readable_slot_samples": dict(sorted(Counter(
               ("no-fact" if (r["charges_reason"] or "").startswith("no-fact")
                else r["charges_reason"]) for r in cqe_readable for _ in range(r["samples"])
               if r["charges"] is None).items())),
           "drops": n_drops, "claims": sum(r["kind"] == "claim" for r in rows),
           "verdicts": len(verdicts), "records": len(states),
           "by_transition": dict(sorted(Counter(r["transition"] for r in verdicts).items())),
           "surprises": dict(sorted(Counter(r["surprise_reason"] for r in verdicts
                                            if r["surprise"]).items())),
           "no_fact": sorted({p["max_charges_reason"] for p in params.values()
                              if (p["max_charges_reason"] or "").startswith("no-fact")})}
    cov.update(_count_provenance(states, params, agent))
    cov["invariants"] = invariant_violations(rows)
    return cov


def _count_provenance(states, params, agent) -> dict:
    """Each slot's count source, the conflicts between a fact and the
    catalogue, the C, Q and E slots still without a count, and the half
    readings against each count: a half bar agrees with a count that draws a
    segment at half (an even count) and disagrees with an odd one. A count
    above `MAX_SEGMENTS_READ` draws in a way no session has shown, so its half
    readings stay unscored. The reading is never changed by the count; this
    only tallies them."""
    who = agent_key(agent.get("agent")) if agent.get("agent") else None
    by_source, halves = Counter(), Counter()
    for r in states:
        if r["slot"] == ULT_SLOT or not r["readable"]:
            continue
        if r["charges_source"]:
            by_source[r["charges_source"]] += r["samples"]
        if r["level"] == 0.5:
            halves[r["slot"]] += r["samples"]
    segments = {}
    for s in SLOTS:
        if s == ULT_SLOT:
            continue
        n, h = params[s]["max_charges"], halves[s]
        scored = n is not None and n <= MAX_SEGMENTS_READ
        segments[s] = {"agent": who, "ability": params[s]["ability"], "max_charges": n,
                       "source": params[s].get("max_charges_source"), "half_samples": h,
                       "agree": h if scored and n % 2 == 0 else 0,
                       "disagree": h if scored and n % 2 == 1 else 0,
                       "unscored": 0 if scored else h}
    return {
        "charges_source": {s: params[s].get("max_charges_source") for s in SLOTS},
        "charges_source_readable_slot_samples": dict(sorted(by_source.items())),
        "charge_conflicts": [{"agent": who, "slot": s, "ability": params[s]["ability"],
                              **params[s]["max_charges_conflict"]}
                             for s in SLOTS if params[s].get("max_charges_conflict")],
        "slots_without_count": [{"agent": who, "slot": s, "ability": params[s]["ability"],
                                 "reason": params[s]["max_charges_reason"],
                                 "prior_reason": params[s].get("max_charges_prior_reason")}
                                for s in SLOTS
                                if s != ULT_SLOT and params[s]["max_charges"] is None],
        "segments": segments,
        "segments_agree": sum(v["agree"] for v in segments.values()),
        "segments_disagree": sum(v["disagree"] for v in segments.values()),
    }


def invariant_violations(rows: list[dict]) -> dict:
    """Counts of the design's invariants broken in one session's stored rows
    (`docs/ABILITY_STATE_MODEL.md`, "Invariants and evaluation"). A cast is a
    `cast` verdict; its `before` is the slot's last readable state before it
    in its round. An invariant step 1 cannot test stores the reason."""
    verdicts = [r for r in rows if r.get("kind") == "verdict"]
    states = [r for r in rows if r.get("kind") == "state"]
    casts = [v for v in verdicts if v["transition"] == "cast"]
    cqe = [v for v in casts if v["slot"] != ULT_SLOT and v["before"]]
    x = [v for v in casts if v["slot"] == ULT_SLOT]
    changes = ("cast", "equip", "unequip", "recharge", "live_return", "buy", "ult_ready",
               "fall_without_a_drop", "unlit_without_a_drop")
    return {
        # 1. charges stay within [0, max_charges]; a cast needs a charge.
        "1_level_outside_the_segments": sum(
            r["samples"] for r in states
            if str(r["charges_reason"]).startswith("level_")),
        "1_cast_without_a_charge": sum(v["before"]["charges_range"][1] < 1 for v in cqe),
        "1_cast_charge_unconfirmed": sum(
            v["before"]["charges_range"][0] < 1 <= v["before"]["charges_range"][1] for v in cqe),
        "1_cast_with_no_reading_before": sum(v["before"] is None for v in casts),
        # 2. an ult casts only from a lit bar, and its cast empties the pips.
        "2_x_cast_from_an_unlit_bar": sum(
            bool(v["before"]) and v["before"]["castable"] is False for v in x),
        "2_x_cast_left_the_bar_lit": sum(bool(v["after"]) and bool(v["after"]["castable"])
                                         for v in x),
        # 3. an equipped slot that returns to idle at the same level spent nothing.
        "3_unequip_lowered_the_level": sum(
            v["transition"] == "unequip" and bool(v["surprise"]) for v in verdicts),
        # 4. one owning slot per entity: step 1 builds no entities.
        "4_entities": "not_built:step_3",
        # 5. a frozen kit changes only by revive, second life or round reset.
        "5_frozen_kit_changed": sum(
            v["transition"] in changes and v["owner_alive_at_t"] is False for v in verdicts),
        # 6. one cast per ability per range round: no session is a range session.
        "6_range_one_cast_per_round": "not_applicable:no_range_session",
        "surprises": sum(bool(v["surprise"]) for v in verdicts),
    }


def score_labels(rows: list[dict], labels: list[dict]) -> dict:
    """The player's tray-cast labels against one session's rows, as
    `ability_timeline.tray_object_labels` reads them, corrections applied:
    each label is a cast the player saw at a drop; its key is
    `<sid>:<round(t_ms)>:<drop slot>`. Returns, per label, the transition
    its drop became, and for the drops the gate accepts, whether the state
    before held a charge (C, Q, E: `charges_range[0] >= 1`) or a lit bar (X).

    A label says its drop is a cast of the drop's slot unless a correction
    moved its slot elsewhere (`label_cast_of_drop`); it `agrees` where the
    drop's transition is a cast exactly when the label says so. Each row
    keeps the label's original slot and the value's source."""
    by_key = {f"{v['session_id']}:{round(v['t_ms'])}:{v['slot']}": v
              for v in rows if v.get("kind") == "verdict" and "tray_drop" in v["agreed"]}
    out = []
    for lab in labels:
        v = by_key.get(lab["key"])
        drop_slot = lab["key"].rsplit(":", 1)[-1]
        says_cast = lab.get("slot", drop_slot) == drop_slot
        src = {"value_source": lab.get("value_source", "player_label"),
               "label_slot": lab.get("label_slot", lab.get("slot")),
               "labelled_slot": lab.get("slot", drop_slot),
               "label_cast_of_drop": says_cast,
               "correction": lab.get("correction")}
        if v is None:
            out.append({"key": lab["key"], "transition": None, "reason": "no_drop_verdict",
                        "agrees": None, **src})
            continue
        b = v["before"]
        held = (None if v["transition"] != "cast" or b is None
                else bool(b["castable"]) if v["slot"] == ULT_SLOT
                else b["charges_range"][0] >= 1)
        out.append({"key": lab["key"], "slot": v["slot"], "agent": lab.get("agent"),
                    **src,
                    "agrees": (v["transition"] == "cast") == says_cast,
                    "transition": v["transition"], "reason": v["reason"],
                    "held_before": held,
                    "before_level": None if b is None else b["level"],
                    "before_held_level": None if b is None else b["held_level"],
                    "before_charges_range": None if b is None else b["charges_range"],
                    "before_fill": None if b is None else b["fill"],
                    "surprise_reason": v["surprise_reason"]})
    return {"labels": out}
