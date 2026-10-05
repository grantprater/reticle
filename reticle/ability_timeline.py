"""Build ability-use claims from independent stored evidence.

Milestone B of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  Tray drops are
bounded observations of a state transition, not unconditional casts.  This
module preserves the possible transition meanings and never requires a minimap
candidate.  Optional materialization drives the existing prototype reader over
demo sources, then consumes its version-stamped caches.

Owns [owns:ability-cast].
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import tray
from .ability_coverage import build_inventory
from .rounds import in_round_window
from .store import DEFAULT_STORE
from .usage import step


ABILITY_TIMELINE_VERSION = "ability-timeline-0.1.0"
_STEP = re.compile(r"\.step(\d+(?:\.\d+)?)\.")
TRANSITION_ALTERNATIVES = ("commit", "activation", "mode_transition", "end")


def _step_ms(source_path: str) -> float | None:
    match = _STEP.search(Path(source_path).name)
    if not match:
        return None
    try:
        step = float(match.group(1)) * 1000.0
    except ValueError:
        return None
    return step if step > 0 else None


def _audio_references(root: Path) -> list[dict]:
    out = []
    folder = root / "reference" / "assets" / "ability_sfx"
    # The established filename contract ends in __SESSION_TIMEs.ext.  Earlier
    # name portions are descriptive only and cannot override reference identity.
    pattern = re.compile(r"__(?P<session>[0-9a-f]+)_(?P<time>[0-9.]+)s\.[^.]+$")
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        if not path.is_file():
            continue
        match = pattern.search(path.name)
        if not match:
            continue
        out.append({
            "path": path.relative_to(root).as_posix(),
            "session_id": match.group("session"),
            "t_ms": float(match.group("time")) * 1000.0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return out


#: A drop this long before the death that ends the player's kit already
#: belongs to it: the death verdict's time is the killfeed entry, which trails
#: the death screen that blanks the tray.
DEATH_LEAD_MS = 1000.0
#: The phases whose drops can be the player's casts (`gametime`'s names).
CAST_PHASES = ("round_live", "post_plant")
#: The ultimate's slot; `tray` reads slot 3 as the ultimate.
ULT_SLOT = tray.SLOT_KEYS[3]
#: The least `from` fill of an X slot that the gate reads as full; an X drop
#: from less is `partial_charge`. `player_tray_casts` gives the measurement.
FULL_MIN = 0.8
#: The most `to` fill of an X slot that the gate reads as emptied; an X drop
#: to more is `pips_lit`. `player_tray_casts` gives the measurement.
EMPTY_MAX = 0.2
#: The least `to` fill that the gate reads as the slot's full level, midway
#: between a two-charge slot's half and full levels; a drop to at least this
#: much is `equip_release`. `player_tray_casts` gives the measurement.
FULL_AFTER_MIN = 0.75
#: A full slot's fill: `tray.fills` scales each slot to its p90 clean count.
#: An `equip_release` drop from above it is a release, which taints no drop
#: beside it. `player_tray_casts` gives the measurement.
FULL_LEVEL = 1.0


def _charge_reason(drop: dict) -> str | None:
    """The first of the charge tests that refuses `drop`, or None.
    `player_tray_casts` gives the tests."""
    if drop["slot"] == ULT_SLOT and drop["from"] < FULL_MIN:
        return "partial_charge"
    if drop["slot"] == ULT_SLOT and drop["to"] > EMPTY_MAX:
        return "pips_lit"
    if drop["to"] >= FULL_AFTER_MIN:
        return "equip_release"
    return None


def _kit_end(window: tuple, ends: set, deaths_ms, agent: str | None,
             second_lives_ms, revives_ms, report_deaths: dict | None
             ) -> tuple[float | None, list[list], list[list]]:
    """(the first of the player's deaths in the round `window` that ends the
    player's kit, or None; the deaths before it that the game undid, each as
    [t_ms, why]; the spans [death, revive] before it in which a teammate's
    revive left the player dead). `player_tray_casts` says how a death is
    undone."""
    a, z, close = window
    inside = lambda xs: sorted(e["t_first"] for e in in_round_window(
        [{"t_first": float(x)} for x in xs], a, z, close, ends))
    deaths = inside(deaths_ms)
    undone = {}
    if agent == "Phoenix":
        lives = set(inside(second_lives_ms))
        counted = (report_deaths or {}).get(a)
        if counted is None or counted <= sum(t not in lives for t in deaths):
            undone.update({t: "run_it_back" for t in deaths if t in lives})
    revives = inside(revives_ms)
    dead = []
    for t, nxt in zip(deaths, deaths[1:] + [float("inf")]):
        back = min((r for r in revives if t <= r < nxt), default=None)
        if t in undone or back is None:
            continue
        undone[t] = "not_dead_yet" if agent == "Clove" else "revived"
        if agent != "Clove":
            dead.append([t, back])
    end = next((t for t in deaths if t not in undone), None)
    keep = lambda t: end is None or t < end
    return (end, [[t, undone[t]] for t in deaths if t in undone and keep(t)],
            [d for d in dead if keep(d[0])])


def kit_windows(rounds: list[dict], player_deaths_ms: list[float], *,
                agent: str | None = None, second_lives_ms=(), revives_ms=(),
                report_deaths: dict | None = None, kit_changes_ms=(),
                kit_returns_ms=()) -> list[dict]:
    """Per stored round, in order: its `window` (start, end, close), the
    `kit_end_ms` that ends the player's kit in it or None, the
    `undone_deaths` before that end, each as [t_ms, why], the
    `dead_spans`, the [death, revive] spans before that end in which a
    teammate's revive left the player dead, the
    `kit_change_ms`, the round's first stored kit change
    (`adjudication.tray_kit`), or None, and the `kit_return_ms`, the first
    stored return to the player's kit after that change in the round, or None.
    The deaths and the rules that undo one are `player_tray_casts`'s; the gate
    reads its kit ends from here, and `adjudication.ability_state` asks the
    same question for every tray sample. The kit change is a second witness,
    kept apart from the killfeed's end."""
    ends = {r["t_end_ms"] for r in rounds}
    changes = [{"t_first": float(t)} for t in kit_changes_ms]
    returns = [{"t_first": float(t)} for t in kit_returns_ms]
    out = []
    for r in rounds:
        w = (r["t_start_ms"], r["t_end_ms"], r["t_close_ms"])
        end, undone, dead = _kit_end(w, ends, player_deaths_ms, agent, second_lives_ms,
                                     revives_ms, report_deaths)
        change = min((c["t_first"] for c in in_round_window(changes, *w, ends)), default=None)
        back = (None if change is None else
                min((c["t_first"] for c in in_round_window(returns, *w, ends)
                     if c["t_first"] > change), default=None))
        out.append({"round_no": r.get("round_no"), "window": w, "kit_end_ms": end,
                    "undone_deaths": undone, "dead_spans": dead, "kit_change_ms": change,
                    "kit_return_ms": back})
    return out


def round_window_of(t_ms: float, kits: list[dict]) -> dict | None:
    """The entry of `kit_windows` whose round holds the instant `t_ms`, by
    `rounds.in_round_window`, or None."""
    ends = {k["window"][1] for k in kits}
    return next((k for k in kits if in_round_window([{"t_first": t_ms}], *k["window"], ends)),
                None)


def player_tray_casts(drops: list[dict], phase_of, rounds: list[dict] | None,
                      player_deaths_ms: list[float], *, agent: str | None = None,
                      second_lives_ms=(), revives_ms=(),
                      report_deaths: dict | None = None, kit_changes_ms=(),
                      kit_returns_ms=(), menu_at=None, kit_spans=None,
                      own_lines_ms=(), pool_slots=(), countdown_reads=None,
                      step_ms: float = 500.0) -> list[dict]:
    """Which of a session's tray drops (`tray.drops`) are the local player's casts.

    The tray shows the player's kit only while the player lives; afterwards it
    shows a spectated teammate's, and the switch empties several slots at once.
    So a drop is the player's cast when it falls in a live phase, before the
    death that ends the player's kit in its round less DEATH_LEAD_MS, and is
    not suspect once `tray.flag_suspect` is recomputed among the drops that
    pass, so a cast is not tainted by the spectator switch after it (measured
    and labelled in `prototypes/tray_suspect_reasons.py` and
    `prototypes/label_tray_objects.py`).

    `phase_of(t_ms)` is the game phase; `rounds` are the stored round rows, and
    `rounds.in_round_window` decides the round of a drop and of a death, so a
    death on the instant two rounds touch belongs to the round it ends.
    `player_deaths_ms` are the player's killfeed deaths
    (`rounds.player_death_times`), and `agent` is the player's agent as the
    arbiter names it. A death ends the kit unless the game undid it: a second
    life or a revive [domain:rounds/resurrection-mechanics]:

    * **Phoenix.** A death the killfeed badge calls a second life
      (`second_lives_ms`, `rounds.player_second_life_times`) is a Run It Back
      death, after which Phoenix returns alive. His X pips do not fall while
      the ult runs [domain:abilities/phoenix-run-it-back-expiry-flash] and
      fall at its end [domain:abilities/caster-hears-own-ult-line], so that
      drop is his cast. The combat report flags KILLED YOU on the real death
      only [domain:rounds/run-it-back-in-report]; where the round's report
      (`report_deaths`, its KILLED YOU count keyed by the round's start)
      counts more deaths than the killfeed's real ones, the killfeed missed a
      real death, no instant after the second life is known to be Phoenix's,
      and the second life still ends the kit.
    * **A revive.** A revive entry names the reviver and the revived
      [domain:killfeed/revive-entries]: a teammate Sage's Resurrection of the
      player, whatever the player's agent, or Clove's Not Dead Yet, which
      needs Clove's death [domain:abilities/clove-c-and-x-need-a-target] and
      whose entry is the revive itself. A KAY/O stabilised from NULL/cmd's
      downed state is no revive here: how his tray draws while downed is
      no recorded fact, and the mechanics sheet asks it. A death followed by a revive of the
      player (`revives_ms`, `adjudication.death.player_revive_times`) before
      the player's next death in the round does not end the kit (`revived`,
      or `not_dead_yet` for Clove). Clove casts Not Dead Yet while dead, so a
      drop between her death and her revive meets the remaining tests like
      any other. Any other player stays dead until the revive, so a drop
      from DEATH_LEAD_MS before the death to the revive (`dead_spans` of
      `kit_windows`) is `after_player_death`: the death screen empties the
      tray there as at any death, and a death-screen drop let through would
      taint the cast before it. The span ends at the revive for every drop,
      bridged (`across_gap`) or not: from `player-cast-0.9.0` to `0.12.0` a
      bridged drop's span ran on `tray.GAP_S` past the revive, a clause
      chosen on one held-half drop (`b7d24102a6f6` Q 1866.5 s); the one
      dev-half drop it reached (`b3b9defb6fd7` X 845.55 s) is refused as
      `pips_lit` without it, so the dev half never supported it, and
      `player-cast-0.13.0` dropped it. Before `player-cast-0.9.0` only Clove's own revive counted: on
      `b3b9defb6fd7` and `b7d24102a6f6` a Sage revived the Skye player three
      times and the gate refused every later cast of those rounds as
      `after_player_death`.

    The tray itself is the second witness. `kit_changes_ms` are the stored kit
    changes (`adjudication.tray_kit`): the first sample of a round at which the
    tray's icons show another agent's kit after the player's. A drop at or
    after the round's first change, and before the tray returns to the
    player's kit in the round (`kit_returns_ms`), is `after_kit_change`,
    tested after the killfeed's `after_player_death`, so each refusal names
    its witness. A return inside a round comes where the rounds table closes
    a round late or a teammate revives the player; the tray shows the
    player's kit again either way. A
    capture whose killfeed prints no entry for the player (`4f207c0c4e39`)
    has only this one. The kit change trails the death by the death camera.
    The drops between the player's last own-kit sample and the change fall
    while the tray is dark or several slots fall at once, and on the three
    sessions of docs/TRAY_KIT_WITNESS.md the `forced` and co-occurrence tests
    refused every one, so the change needs no lead.

    The change alone misses a drop under another agent's kit where the round
    shows no span of the player's kit before it, and on `4f207c0c4e39` the
    stored rows named no player agent, so no change was stored at all: 28 of
    52 drops the gate passed fell under a teammate's kit. So the gate also
    reads the kit at each drop. `kit_spans` are the spans the arbiter named
    (`adjudication.tray_kit.stored_kit_witness`); `tray_kit.kit_agents_at`
    names the kit the tray showed at the drop. A drop under a named kit is
    `kit_not_player` where that kit is not `agent`'s, and
    `kit_owner_unresolved` where the arbiter names no player agent, since no
    kit can then be called the player's. A drop under no named span passes
    this test. `kit_spans` None (no current `tray_kit` rows) applies no test.
    Both names are tested after `after_kit_change`, and each row carries the
    `kit_agent` read at its drop.

    The menu is refused before every other test. Opening it dims the whole
    tray, which reads as a fall on every slot at one instant
    [domain:hud/menu-dims-tray]. `menu_at(t_ms)` is the stored menu witness
    (`menu.MenuWitness.at`); a drop at an instant it answers True is
    `menu_open`, kept and named, and taints no drop beside it. A witness that
    answers None there, or no witness, refuses nothing.

    A drop that passes those tests must still have spent a charge, and three
    more tests ask whether it did, in this order:

    * `partial_charge`: an X drop from a slot that was not full, and
    * `pips_lit`: an X drop that left the slot short of empty, both by
      [domain:abilities/ult-charge-pips];
    * `equip_release`: a drop that left its slot at the full level
      [domain:hud/ability-tray-charge-segments]. An X drop that reaches this
      test has emptied its slot, so it refuses only C, Q and E drops.

    They name a drop only after the co-occurrence test, but that test asks them
    first which drops are releases. A release is a C, Q or E drop that
    `equip_release` refuses from above the full level (`from` over FULL_LEVEL,
    1.0): the player equipped the ability, which brightens its slot, and
    switched away. A release spends nothing, so it taints no drop beside it;
    every other drop taints, an X drop the charge tests refuse included
    (*A release beside a cast*, below). A drop falls by at least
    `tray.CAST_DROP`, so one that lands at FULL_AFTER_MIN or more starts at
    1.0 or more; the clause excludes only a slot read at its full level that
    falls to FULL_AFTER_MIN, which was never brightened.

    A capture with no rounds table (`rounds` None: a solo demo or a range
    capture) has no round to place a drop in, no phase and no deaths the gate
    reads, so every drop is refused as `no_rounds` and stored rather than
    guessed into a round. An empty table is not a missing one: its drops are
    `no_round`. The menu witness still reads there, and a covered drop is
    `menu_open`, not `no_rounds`: the menu outranks a missing table as it
    outranks a missing round, so a demo's settings drops read as the menu's.

    Every test names its refusal, and a drop keeps the first that refuses it,
    in this order: `menu_open`, `no_rounds`, `no_round`, `after_player_death`,
    `after_kit_change`, `kit_not_player` or `kit_owner_unresolved`,
    `phase:<name>`, `forced` or `cooccur_among_casts`,
    `partial_charge`, `pips_lit`, `equip_release`.

    *Full* is read from the drop's own `from`: the slot's teal count on the
    last clean sample before the drop over the slot's p90 clean count in the
    session (`tray.fills`), so no per-agent constant enters. The reading has
    two states. A full slot also lights the bar under its pips and reads about
    1; a slot short of full lights only its lit pips. On six sessions' stored
    crops, [metric:tray/x-fill-states@six-sessions#not_full=9685] of
    [metric:tray/x-fill-states@six-sessions#clean_samples=11747] clean samples
    read 0.2 or less (99th percentile at most
    [metric:tray/x-fill-states@six-sessions#not_full_p99_max=0.164]),
    [metric:tray/x-fill-states@six-sessions#full=1998] read 0.8 to 1.1, and
    [metric:tray/x-fill-states@six-sessions#between=39] fell between. The slot
    was full when `from` reaches FULL_MIN, 0.80. The
    [metric:ult_lines/x-fill-full@all-sessions#x_casts_with_line=46] in-round
    X casts with an own ult line on the 19 lineup sessions fell from
    [metric:ult_lines/x-fill-full@all-sessions#with_line_from_min=0.9] to
    [metric:ult_lines/x-fill-full@all-sessions#with_line_from_max=1.18],
    median [metric:ult_lines/x-fill-full@all-sessions#with_line_from_median=0.98]
    with a median absolute deviation of
    [metric:ult_lines/x-fill-full@all-sessions#with_line_from_mad=0.03].
    FULL_MIN sits [metric:ult_lines/x-fill-full@all-sessions#margin_below_lowest_with_line=0.1]
    under the lowest of them, more than three deviations, and far above a
    part-charged slot's reading. Until `player-cast-0.5.0` no X drop the other
    tests passed on those sessions fell from between 0.58 and 0.90, so any
    value in that gap gave the same verdicts; the value is not fitted to the
    four drops it refused
    ([metric:ult_lines/x-fill-full@all-sessions#partial_from_min=0.36] to
    [metric:ult_lines/x-fill-full@all-sessions#partial_from_max=0.58]).
    Since a release stopped tainting, one X drop the other tests pass falls in
    the gap ([metric:tray/cooccur-taint@all-sessions#x_other_tests_pass_from_0_58_to_0_9=1]):
    Phoenix's at `587c15b07779` 952.5 s, from
    [metric:tray/cooccur-taint@all-sessions#x_partial_charge_587c15b07779_952_from=0.76]
    to [metric:tray/cooccur-taint@all-sessions#x_partial_charge_587c15b07779_952_to=0.0],
    with his own ult line at
    [metric:tray/cooccur-taint@all-sessions#x_partial_charge_587c15b07779_952_line_dt_s=-9.43] s
    from it. FULL_MIN alone refuses it now, so a value at or below its fill
    would accept it; it is recorded here, not refitted.

    Those four drops, and every fill above 1, are teal added to the bar's box
    for one sample by something drawn behind or over the tray, which is
    semi-transparent. On `ff636d173b07` in round 1, every X pip unlit, the
    map's teal trim crossed the box at 47.55 s: the slot read
    [metric:tray/x-fill-states@six-sessions#ff636d173b07_48_x_before=0.08],
    [metric:tray/x-fill-states@six-sessions#ff636d173b07_48_x_from=0.36] and
    [metric:tray/x-fill-states@six-sessions#ff636d173b07_48_x_at=0.0], and the
    trim's leaving read as a drop. On `c40d950031bb` at 769.0 s Sova's glowing
    bow lifted a part-lit slot from
    [metric:tray/x-fill-states@six-sessions#c40d950031bb_769_x_before=0.07]
    to [metric:tray/x-fill-states@six-sessions#c40d950031bb_769_x_from=0.58]
    and it fell back to
    [metric:tray/x-fill-states@six-sessions#c40d950031bb_769_x_at=0.12].
    Nothing emptied either slot. The lined cast's 1.18 (`75a55a296d3b`
    1010.5 s) is a teal glow behind the X icon on the last sample before the
    cast, over a slot that read a median of
    [metric:tray/x-fill-states@six-sessions#75a55a296d3b_1011_x_prior10_median=0.96]
    on the ten samples before. A fill above 1 is a full slot plus added teal,
    never more charge, and the teal can lift a part-charged slot past FULL_MIN
    only by adding most of a full bar in one sample; none of the four did.

    *Emptied* is read from the drop's own `to`, on the same scale: the slot
    emptied when `to` is at most EMPTY_MAX, 0.2, the ceiling of the unlit
    reading above. Of the X casts with an own ult line above,
    [metric:ult_lines/x-fill-full@all-sessions#with_line_to_zero=45] fell to 0
    and one to [metric:ult_lines/x-fill-full@all-sessions#with_line_to_max=0.76]:
    `7010b3d62460` at 1509.55 s, 1.5 s before the same slot fell from 0.99 to
    0, the drop that stays the cast. `3694746e4e54` at 1062.0 s fails too: the
    bow's glow lifted a full slot to
    [metric:tray/x-fill-states@six-sessions#3694746e4e54_1062_x_from=1.33], and
    the slot still read
    [metric:tray/x-fill-states@six-sessions#3694746e4e54_1062_x_at=1.08] after
    the "drop". The shape fitter found Hunter's Fury's line on
    [metric:tray/full-after-shapes@all-sessions#fury_full_after_found=3] of
    [metric:tray/full-after-shapes@all-sessions#fury_full_after_crops=13] crops
    after it, against
    [metric:tray/full-after-shapes@all-sessions#fury_empty_found=220] of
    [metric:tray/full-after-shapes@all-sessions#fury_empty_crops=221] after the
    X drops that emptied the slot. On the 19 lineup sessions under
    `player-cast-0.4.0` the two tests left
    [metric:tray/equip-release@all-sessions#x_casts=48] of
    [metric:tray/equip-release@all-sessions#x_casts_before=50] X casts, none
    falling to more than
    [metric:tray/equip-release@all-sessions#x_to_max=0.03]. The gate now
    passes [metric:tray/cooccur-taint@all-sessions#x_casts=52] (*A release
    beside a cast*, below), the highest landing at
    [metric:tray/cooccur-taint@all-sessions#x_to_max=0.13] (`bfad2778a372`
    405.57 s), under EMPTY_MAX.

    *The full level* is read from `to` as well. A two-charge slot's bar reads
    1, 0.5 or 0 of its reference [domain:hud/ability-tray-charge-segments], and
    FULL_AFTER_MIN, 0.75, lies midway between the half and full levels, so a
    drop to at least that much left the slot full. No drop the other tests
    pass on the 19 lineup sessions landed between
    [metric:tray/equip-release@all-sessions#to_half_max=0.53] and
    [metric:tray/equip-release@all-sessions#to_full_min=0.76], so any value in
    that gap gives the same verdicts. Of the
    [metric:tray/equip-release@all-sessions#accepted_before=493] drops the
    gate passed without `pips_lit` and `equip_release`, the full-level test
    refuses [metric:tray/equip-release@all-sessions#equip_release=75], every
    one from a fill of
    [metric:tray/equip-release@all-sessions#equip_release_from_min=1.05] or
    more: teal over a full slot, released without a charge spent. A cut at
    0.9 would pass [metric:tray/equip-release@all-sessions#equip_release_0_75_to_0_9=8]
    of them, and the landings between 0.75 and 0.9 behave like those above:
    [metric:tray/equip-release@all-sessions#landings_0_75_to_0_9_then_fall=5]
    of the [metric:tray/equip-release@all-sessions#landings_0_75_to_0_9=9]
    there, and [metric:tray/equip-release@all-sessions#landings_at_0_9_then_fall=23]
    of the [metric:tray/equip-release@all-sessions#landings_at_0_9=68] at 0.9
    or more, are followed within 5 s by a drop of the same slot: the release,
    then the cast.

    The player named what 120 gated drops drew on the minimap
    (`labels/tray_object`). The tests refuse
    [metric:tray/equip-release@all-sessions#labels_refused_nothing_on_minimap=21]
    that drew nothing and
    [metric:tray/equip-release@all-sessions#labels_refused_object=2] that drew
    an object, both Skye's: Trailblazer at `b3b9defb6fd7` 1627.0 s (1.45 to
    0.95), whose view tints the screen [domain:hud/controlled-entity-view-tint],
    and Regrowth at `e37fdeca944f` 364.6 s (1.31 to 1.0). The tray and the
    labels disagree on those two, and the gate refuses both.

    *A release beside a cast.* The player equips one ability, switches to
    another and casts it, and the release and the cast land within
    `tray.SUSPECT_S`, often in one sample. Under `player-cast-0.4.0` the release tainted the
    cast:
    [metric:tray/equip-release@all-sessions#cooccur_beside_charge_refusals_only=58]
    drops the charge tests pass were refused as co-occurring with nothing but
    drops those tests refuse. On `3694746e4e54` at 664.52 s the X slot emptied
    0.11 s after the player's own ult line, beside C released from
    [metric:tray/cooccur-taint@all-sessions#example_3694746e4e54_664_c_from=1.32]
    to [metric:tray/cooccur-taint@all-sessions#example_3694746e4e54_664_c_to=0.99].
    The 58 had [metric:tray/cooccur-taint@all-sessions#partners=68] partners:
    [metric:tray/cooccur-taint@all-sessions#partners_equip_release=58]
    releases, from
    [metric:tray/cooccur-taint@all-sessions#release_from_min=1.08] to
    [metric:tray/cooccur-taint@all-sessions#release_from_max=1.96], and
    [metric:tray/cooccur-taint@all-sessions#partners_partial_charge=6]
    `partial_charge` and
    [metric:tray/cooccur-taint@all-sessions#partners_pips_lit=4] `pips_lit` X
    drops. Those X drops are teal leaving the ult slot, and teal leaves the
    whole tray the same way: on `96aa1ae9b96f` at 673.0 s
    [metric:tray/cooccur-taint@all-sessions#flash_96aa1ae9b96f_673_slots=4]
    slots fell in one sample, E from
    [metric:tray/cooccur-taint@all-sessions#flash_96aa1ae9b96f_673_e_from=0.88]
    to 0 beside C and Q falling to their full level and a part-charged X. So
    only a release is quiet, and the gate passes
    [metric:tray/cooccur-taint@all-sessions#accepted_of_58=48] of the 58,
    [metric:tray/cooccur-taint@all-sessions#accepted_of_58_X=4] of them X
    casts. None has a partner that landed below
    [metric:tray/cooccur-taint@all-sessions#accepted_partner_to_min=0.78] or
    fell from below
    [metric:tray/cooccur-taint@all-sessions#accepted_partner_from_min=1.08],
    and [metric:tray/cooccur-taint@all-sessions#accepted_in_same_sample_group_3plus=0]
    lie in a sample where three or more slots fell. The settings menu dims
    every slot at one instant [domain:hud/menu-dims-tray]; the
    [metric:tray/cooccur-taint@all-sessions#demo_menu_drops=18] demo drops it
    covers all read the tray as not drawn
    ([metric:tray/cooccur-taint@all-sessions#demo_menu_drops_forced=18]
    `forced`). A dim that left the bars drawn would lower every slot at once,
    and each slot it leaves below the full level is no release and still
    taints the others. No labelled drop changes its verdict
    ([metric:tray/cooccur-taint@all-sessions#labels_verdict_changed=0]).

    *A numeral beside a co-occurring drop.* Sova's Recon Bolt and Skye's
    Guiding Light, spent, draw a countdown numeral over the slot
    [domain:hud/ability-tray-restock-countdown] (NUMERAL_SLOTS; the fact is
    observed on those two only), and the numeral is read apart from the bar
    (`tray_countdown`). So a drop of such a slot the co-occurrence test
    refuses as `cooccur_among_casts` meets the charge tests instead where
    the numeral witnesses it (`countdown_reads`, `tray.gold_witness` asked
    of the drop with the sample `step_ms` before it, or `tray.GAP_S` before
    a bridged one, as the last the spent charge read on): a numeral that
    appeared or restarted over its slot within `tray.WITNESS_AFTER_S` after
    (NUMERAL_SPENDS). The row keeps the verdict as `numeral`. A `forced`
    drop stays refused, and the witnessed drop still taints its partners,
    so the rule passes one spend of a crowd and refuses the rest. Without
    reads (`countdown_reads` None) nothing changes. The witness was chosen
    on the dev half of the 21 Riot-paired matches: the numeral alone, since
    the icon's brightness is read on no stored row and the audio verdict was
    not measured here. Scored against Riot's counts
    (`prototypes/own_cast_gate_eval.py`), the rules since
    `player-cast-0.8.0` raised the dev half from
    [metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_dev_covered=239] to
    [metric:tray/own-cast-gate@riot-21#gate_dev_covered=259] of
    [metric:tray/own-cast-gate@riot-21#dev_riot=300] casts covered, beyond
    held at [metric:tray/own-cast-gate@riot-21#gate_dev_beyond=2], and the
    held half from
    [metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_held_covered=286] to
    [metric:tray/own-cast-gate@riot-21#gate_held_covered=300] of
    [metric:tray/own-cast-gate@riot-21#held_riot=310], beyond from
    [metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_held_beyond=6] to
    [metric:tray/own-cast-gate@riot-21#gate_held_beyond=8]
    (docs/ABILITY_STATE_MODEL.md, "The cast gate against Riot's counts").

    *A gold drop of a pool is marked, not judged.* A slot a resource-bar
    fact names for the player's agent (`pool_slots`,
    `adjudication.ability_state.pool_facts`) draws a pool, not charges:
    Skye's Regrowth in C [domain:abilities/skye-regrowth-resource-bar]. Why
    Regrowth turns gold is the player's to answer
    [domain:hud/ability-tray-restocked-charge-gold], and what a gold Regrowth
    bar going empty means is a question on the mechanics sheet. So a drop
    read from gold halves alone (a row with the gold `witness`,
    `tray.drops`) in such a slot keeps its verdict and carries
    `pool_gold_drop`, for the answer to judge. From `player-cast-0.11.0` to
    `0.12.0` the gate refused it as `resource_pool`, a rule reasoned from
    the gold of Recon Bolt and Guiding Light and chosen on two held-half
    drops; `player-cast-0.13.0` withdrew it.

    *A line overturns a death or a dark tray.* The player hears their own
    ultimate's line at the cast [domain:abilities/caster-hears-own-ult-line],
    so an own line (`own_lines_ms`, `ult_cast` rows of the player's own
    class that rest on no tray cast) witnesses an X cast the tray dates
    badly. An X drop refused as `forced` (Clove's Not Dead Yet empties X on
    the death screen, `a1a995e6b19b` 632.5 s, its line 0.98 s after) or as
    `after_player_death` (Run It Back's pips fall at its end, when Phoenix
    dies in it [domain:abilities/phoenix-run-it-back-expiry-flash], so
    where the badge goes unread the drop trails the death that ends the kit)
    or, since `player-cast-0.12.0`, as `cooccur_among_casts` (with the badge
    read, the same drops fall beside the death screen's: `7010b3d62460`
    586.0 s and `a06f04a0059f` 1894.0 s)
    passes where an own line lies in the agent's cast window of it
    (`adjudication.ult_cast.cast_window`, `in_window`), the line came before
    the kit's end, the drop meets the charge tests, and no X drop the gate
    passed already lies in that line's window; one line passes one drop, the
    nearest. The row keeps the refusal as `refused_as`, the line as
    `line_ms`, and `rests_on` names the line (`ult_cast`), so the cast never
    witnesses that line back: `ult_cast` asks this gate with no own lines
    and binds no tray cast that rests on one. No line, no change.

    Every drop comes back with `player_cast`, the first `reason` that refused
    it, the round's `first_player_death_ms`, the `kit_end_ms` the gate used,
    the `undone_deaths` before it, and the round's `kit_change_ms`.
    """
    covered = lambda t: menu_at is not None and menu_at(t) is True
    if rounds is None:
        return [{**d, "phase": None, "round_ms": None, "first_player_death_ms": None,
                 "kit_end_ms": None, "undone_deaths": [], "kit_change_ms": None,
                 "kit_agent": None,
                 "reason": "menu_open" if covered(d["t_ms"]) else "no_rounds",
                 "player_cast": False} for d in drops]
    from .adjudication.tray_kit import kit_agents_at, same_agent
    ends = {r["t_end_ms"] for r in rounds}
    deaths = [{"t_first": x} for x in player_deaths_ms]
    kits = kit_windows(rounds, player_deaths_ms, agent=agent, second_lives_ms=second_lives_ms,
                       revives_ms=revives_ms, report_deaths=report_deaths,
                       kit_changes_ms=kit_changes_ms, kit_returns_ms=kit_returns_ms)
    seen_at = (kit_agents_at([d["t_ms"] for d in drops], kit_spans) if kit_spans is not None
               else [None] * len(drops))
    rows = []
    for d, seen in zip(drops, seen_at):
        t = d["t_ms"]
        k = round_window_of(t, kits)
        rnd = k["window"] if k else None
        first = (min((e["t_first"] for e in in_round_window(deaths, *rnd, ends)), default=None)
                 if rnd else None)
        end, undone = (k["kit_end_ms"], k["undone_deaths"]) if k else (None, [])
        dead = (any(a - DEATH_LEAD_MS <= t < b for a, b in k["dead_spans"])
                if k else False)
        change, back = (k["kit_change_ms"], k["kit_return_ms"]) if k else (None, None)
        phase = phase_of(t)
        reason = ("menu_open" if covered(t)
                  else "no_round" if rnd is None
                  else "after_player_death" if (dead or end is not None
                                                and t >= end - DEATH_LEAD_MS)
                  else "after_kit_change" if (change is not None and t >= change
                                              and (back is None or t < back))
                  else "kit_owner_unresolved" if seen is not None and agent is None
                  else "kit_not_player" if same_agent(seen, agent) is False
                  else None if phase in CAST_PHASES else f"phase:{phase}")
        rows.append({**d, "phase": phase, "kit_agent": seen,
                     "round_ms": None if rnd is None else [float(rnd[0]), float(rnd[2])],
                     "first_player_death_ms": first, "kit_end_ms": end,
                     "undone_deaths": undone, "kit_change_ms": change, "reason": reason})
    keep = [r for r in rows if r["reason"] is None]
    # The charge tests read first, because the co-occurrence test asks them
    # which drops are releases; a drop still keeps the first reason in order.
    charge = [_charge_reason(r) for r in keep]
    quiet = [why == "equip_release" and r["from"] > FULL_LEVEL for r, why in zip(keep, charge)]
    for r, why, (*_x, sus) in zip(keep, charge, tray.flag_suspect(
            [(r["t_ms"] / 1000.0, r["slot"], r["from"], r["to"], r["forced"]) for r in keep],
            quiet=quiet)):
        r["reason"] = ("forced" if r["forced"] else "cooccur_among_casts") if sus else why
        if (r["reason"] == "cooccur_among_casts" and countdown_reads is not None
                and NUMERAL_SLOTS.get(agent) == r["slot"]):
            seen = _numeral_witness(r, countdown_reads, step_ms)
            r["numeral"] = seen
            if seen in NUMERAL_SPENDS:
                r["reason"] = why
    for r in rows:
        if r["slot"] in pool_slots and "witness" in r:
            r["pool_gold_drop"] = True
    _admit_lined_x(rows, own_lines_ms, agent)
    for r in rows:
        r["player_cast"] = r["reason"] is None
    return rows


#: The restock numeral's verdicts (`tray.gold_witness`'s `countdown`) that
#: witness a spend of the slot it is drawn over.
NUMERAL_SPENDS = ("restarted", "appeared")
#: The slots whose restock numeral witnesses a spend, by agent: the two
#: abilities the countdown was observed on, Sova's Recon Bolt and Skye's
#: Guiding Light [domain:hud/ability-tray-restock-countdown]. Over Skye's Q a
#: numeral shows that does not count down, and no other ability's numeral is
#: a recorded fact [domain:abilities/ability-rules-are-unique].
NUMERAL_SLOTS = {"Sova": "E", "Skye": "E"}


def _numeral_witness(drop: dict, reads: list[dict], step_ms: float) -> str:
    """The restock numeral's verdict on `drop` (`tray.gold_witness`'s
    `countdown`), asked with the sample `step_ms` before it as the last the
    spent charge read on, or `tray.GAP_S` before for a bridged drop."""
    back = 1000.0 * tray.GAP_S if drop.get("across_gap") else step_ms
    tb = drop["t_ms"] - back
    return tray.gold_witness({"t_ms": drop["t_ms"], "slot": drop["slot"], "t_before_ms": tb,
                              "t_gold_ms": tb, "gold_run": None}, reads, {})["countdown"]


#: The refusals a player's own ult line can overturn for an X drop
#: (`_admit_lined_x`): the tray was undrawn at the drop, the drop fell at the
#: death that ended the kit, or another slot fell beside it.
LINE_ADMITS = ("forced", "after_player_death", "cooccur_among_casts")


def _admit_lined_x(rows: list[dict], own_lines_ms, agent: str | None) -> None:
    """Pass, in place, the X drops `player_tray_casts` refused as one of
    LINE_ADMITS where the player's own ult line witnesses the cast. Each row
    passed keeps its refusal as `refused_as`, names the line as `line_ms`
    and rests on it (`rests_on`). `player_tray_casts` gives the rule."""
    from .adjudication.ult_cast import cast_window, in_window
    if not own_lines_ms:
        return
    win = cast_window(agent)
    xs = [r for r in rows if r["slot"] == ULT_SLOT]
    taken = [r["t_ms"] for r in xs if r["reason"] is None]
    for line in sorted(float(t) for t in own_lines_ms):
        if any(in_window(line, t, win) for t in taken):
            continue
        near = [r for r in xs if r["reason"] in LINE_ADMITS and in_window(line, r["t_ms"], win)
                and (r["kit_end_ms"] is None or line < r["kit_end_ms"])
                and _charge_reason(r) is None]
        if not near:
            continue
        r = min(near, key=lambda r: (abs(r["t_ms"] - line), r["t_ms"]))
        r.update({"refused_as": r["reason"], "reason": None, "line_ms": line,
                  "rests_on": [{"stream": "ult_cast", "owner": "adjudication.ult_cast",
                                "t_ms": line}]})
        taken.append(r["t_ms"])


def stored_gate_inputs(store, session_id: str, date: str, rounds: list[dict],
                       agent: str | None) -> tuple[dict, dict]:
    """(the keyword inputs of `player_tray_casts` beyond the drops and rounds,
    read from storage; their stamps). Decodes nothing.

    The phase is `gametime`'s over the stored HUD, and the deaths are the HUD's
    killfeed tracks. Second lives come from the stored badge reads, which only
    a current `killfeed_portrait` stream carries
    (`adjudication.death.stored_second_life`). Revives are the stored `death`
    verdicts that revive the player, from any reviver
    (`adjudication.death.player_revive_times`). The report's death
    counts are the stored `combat_report_round` rows where a report was read.
    The kit changes and the named kit spans are the stored `tray_kit` rows
    (`adjudication.tray_kit.stored_kit_witness`), used only where they are
    current, with own and other judged against `agent`; otherwise the lists
    are empty, `kit_spans` is None, and the stamp says why. Without an
    `agent` the spans are still handed on, so the gate refuses a drop under
    a named kit as `kit_owner_unresolved`. The menu witness is the stored `menu_open` rows
    (`menu.stored_menu`), used only where current; otherwise `menu_at` is None
    and the stamp says why. The player's own ult lines are the stored
    `ult_cast` rows `own_line_times` keeps, used only where they are at
    ULT_CAST_VERSION; otherwise none come back and `ult_cast_reason` says
    why. `ult_cast` reads this gate in turn, but asks it with no own lines
    (`adjudication.ult_cast.player_x_drops`), so the stream never reads its
    own output. The restock
    numeral reads are the stored `tray_countdown` rows where current
    (`stored_countdown`); `reticle tray` writes them in the pass that writes
    the drops and hands its own reads to the gate instead.
    """
    from . import gametime, stalls
    from .adjudication.death import player_revive_times, stored_second_life
    from .adjudication.tray_kit import stored_kit_witness
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .menu import stored_menu
    from .rounds import player_death_times, player_second_life_times
    from .version import PLAYER_CAST_VERSION

    hud = store.read_hud(session_id, date)
    with step("gametime"):
        gt = gametime.build_session_gametime(session_id, hud, rounds,
                                             stall_list=stalls.for_session(store, session_id, date))
    badges = stored_second_life(store.read_events_kind(
        "killfeed_portrait", session_id, "second_life_observation"), KILLFEED_PORTRAIT_VERSION)
    verdicts = [r for r in store.read_events("death", session_id)
                if r.get("kind") == "death_verdict"]
    report = [r for r in store.read_events("combat_report_round", session_id)
              if r.get("kind") == "round"]
    inputs = {
        "phase_of": lambda t: gt.game_time_at(t).phase,
        "player_deaths_ms": player_death_times(hud),
        "agent": agent,
        "second_lives_ms": player_second_life_times(hud, badges),
        "revives_ms": player_revive_times(verdicts, agent),
        "report_deaths": {float(r["t_start_ms"]): int(r["deaths"]) for r in report
                          if r.get("verdict_source") == "combat_report"
                          and r.get("deaths") is not None},
    }
    kit = stored_kit_witness(store.read_events("tray_kit", session_id), agent=agent)
    inputs["kit_changes_ms"] = kit["kit_changes_ms"]
    inputs["kit_returns_ms"] = kit["kit_returns_ms"]
    inputs["kit_spans"] = (kit["spans"] if kit["reason"] in (None, "no_player_agent")
                           else None)
    menu, menu_stamp = stored_menu(store, session_id)
    inputs["menu_at"] = menu.at if menu is not None else None
    inputs["own_lines_ms"], lines_why = stored_own_lines(store, session_id)
    inputs["pool_slots"], pools = pool_slots(agent)
    inputs["countdown_reads"], inputs["step_ms"] = stored_countdown(store, session_id)
    # Each stored input's own stamp, read from its first row (`no_rows` where
    # none is stored), used or not: `plan` compares these with the stored
    # heads, so a stream written after this read makes the result stale.
    from .input_stamps import NO_ROWS, event_stamp
    stamps = {"player_cast": PLAYER_CAST_VERSION,
              "hud": (hud.schema.metadata or {}).get(b"hud_version", b"").decode() or "unstamped",
              "gametime": gametime.GAMETIME_VERSION,
              "killfeed_portrait": event_stamp(store, "killfeed_portrait", session_id,
                                               "killfeed_portrait_version"),
              "death": event_stamp(store, "death", session_id, "death_adjudication_version"),
              "combat_report_round": event_stamp(store, "combat_report_round", session_id,
                                                 "combat_report_round_version"),
              "tray_kit": kit["version"] or NO_ROWS, "tray_kit_reason": kit["reason"],
              "tray_kit_own_basis": kit["own_basis"],
              "menu_open": menu_stamp,
              "ult_cast": event_stamp(store, "ult_cast", session_id, "ult_cast_version"),
              "ult_cast_reason": lines_why,
              "pool_facts": pools,
              "tray_countdown": event_stamp(store, "tray_countdown", session_id,
                                            "tray_countdown_version")}
    return inputs, stamps


def stored_countdown(store, session_id: str) -> tuple[list[dict] | None, float]:
    """(the stored restock numeral reads, `tray_countdown` rows of kind
    `read`, or None where the stream is absent or not at
    TRAY_COUNTDOWN_VERSION; the sample step in ms of the pass that read
    them, from their coverage row, 500 where none is stored)."""
    from .version import TRAY_COUNTDOWN_VERSION
    rows = store.read_events("tray_countdown", session_id)
    current = bool(rows) and rows[0].get("tray_countdown_version") == TRAY_COUNTDOWN_VERSION
    cov = [r for r in rows if r.get("kind") == "coverage"]
    step = float(cov[0].get("step_s") or 0.5) if cov else 0.5
    return ([r for r in rows if r.get("kind") == "read"] if current else None), 1000.0 * step


def stored_own_lines(store, session_id: str) -> tuple[list[float], str | None]:
    """(the player's own ult lines among the stored `ult_cast` rows
    (`own_line_times`), or none where the stream is absent or not at
    ULT_CAST_VERSION; None, `no_ult_cast` or `ult_cast_stale`)."""
    from .version import ULT_CAST_VERSION
    rows = store.read_events("ult_cast", session_id)
    if not rows:
        return [], "no_ult_cast"
    if rows[0].get("ult_cast_version") != ULT_CAST_VERSION:
        return [], "ult_cast_stale"
    return own_line_times(rows), None


def pool_slots(agent: str | None) -> tuple[tuple[str, ...], list[str]]:
    """(the slots of `agent` that a resource-bar fact makes a pool, the facts'
    keys), by `adjudication.ability_state.pool_facts` over `domain/*.toml`;
    none without an agent."""
    if agent is None:
        return (), []
    from . import domain
    from .adjudication.ability_state import _agent_key, pool_facts
    hits = sorted((slot, key) for (a, slot), key in pool_facts(domain.load()).items()
                  if a == _agent_key(agent))
    return tuple(s for s, _k in hits), [k for _s, k in hits]


def own_line_times(ult_rows: list[dict]) -> list[float]:
    """The instants of the player's own ult lines among a session's stored
    `ult_cast` rows: casts of the player's own class (`player_cast`) that
    rest on nothing (`rests_on` empty). A line the adjudicator selected
    because a tray X cast witnessed it rests on the gate and never witnesses
    the gate back."""
    return sorted(float(r["t_ms"]) for r in ult_rows
                  if r.get("kind") == "cast" and r.get("player_cast") and not r.get("rests_on"))


#: The stored audio-gate log-mel and labels, under the store root.
AUDIO_GATE_DIR = Path("analysis") / "audio-gate" / "0.1.0"
#: The player's tray-cast labels (`prototypes/label_tray_objects.py`) and the
#: corrections the player made to them, stored beside them, never over them.
TRAY_OBJECT_DIR = Path("labels") / "tray_object"
TRAY_OBJECT_CORRECTIONS_DIR = Path("labels") / "tray_object_corrections"
#: The fields a correction may change.
CORRECTED_FIELDS = ("slot", "ability")


def _label_file_stamp(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def tray_object_labels(store_root, session_id: str) -> tuple[list[dict], dict]:
    """(the player's tray-cast labels of a session, their stamps), each
    correction (TRAY_OBJECT_CORRECTIONS_DIR, keyed by the label's `key`)
    applied at read time. A corrected label carries the corrected `slot` and
    `ability`, its original values as `label_slot` and `label_ability`, and
    `correction` (the correction's basis, by, at and file); every label says
    its `value_source`, `player_correction` or `player_label`. Neither file
    is rewritten. The stamps are each file's sha256, `no_rows` where it is
    absent. Every consumer of the labels reads them here."""
    from .input_stamps import NO_ROWS
    root = Path(store_root)
    lp = root / TRAY_OBJECT_DIR / f"{session_id}.jsonl"
    cp = root / TRAY_OBJECT_CORRECTIONS_DIR / f"{session_id}.jsonl"
    read = lambda p: [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
                      if x.strip()] if p.is_file() else []
    fix = {c["key"]: c for c in read(cp)}
    out = []
    for lab in read(lp):
        c = fix.get(lab["key"])
        if c is None:
            out.append({**lab, "value_source": "player_label"})
            continue
        out.append({**lab, **{f: c[f] for f in CORRECTED_FIELDS if f in c},
                    **{f"label_{f}": lab.get(f) for f in CORRECTED_FIELDS},
                    "value_source": "player_correction",
                    "correction": {k: c.get(k) for k in ("basis", "by", "at")}
                    | {"file": (TRAY_OBJECT_CORRECTIONS_DIR / cp.name).as_posix()}})
    stamp = lambda p: _label_file_stamp(p) if p.is_file() else NO_ROWS
    return out, {"labels_tray_object": stamp(lp), "labels_tray_object_corrections": stamp(cp)}
#: The refusals a drop gets for showing another kit than the player's: a
#: teammate's sound at that instant, known, so never background.
KIT_REFUSALS = ("after_kit_change", "kit_not_player", "kit_owner_unresolved")


def features_stamp(z, path) -> str:
    """The stamp of a stored audio-gate log-mel npz `z`, read from `path`."""
    return str(z["version"]) if "version" in z.files else f"unstamped:{Path(path).name}"


def audio_input_stamps(store_root, session_id: str) -> dict[str, str]:
    """The stamps of the audio-gate log-mel and labels `audio_session` reads
    for a session, as stored now (`no_rows` where a file is absent), which
    `plan` compares with what `ability-state` recorded. Loads only the npz's
    `version` member."""
    import numpy as np

    from .input_stamps import NO_ROWS
    gate = Path(store_root) / AUDIO_GATE_DIR
    fp = gate / "features" / f"{session_id}.npz"
    lp = gate / "labels" / f"{session_id}.json"
    out = {"audio_features": NO_ROWS, "audio_labels": NO_ROWS}
    if fp.is_file():
        with np.load(fp, allow_pickle=True) as z:
            out["audio_features"] = features_stamp(z, fp)
    if lp.is_file():
        out["audio_labels"] = (json.loads(lp.read_text(encoding="utf-8")).get("version")
                               or "unstamped")
    return out


def audio_session(store_root, session_id: str, gate_rows: list[dict], agent: str | None,
                  kit_spans=None, *, features_path=None, labels_path=None,
                  span_s: tuple[float, float] | None = None) -> tuple[dict | None, str | None]:
    """(the stored audio a cast's witness reads, None) or (None, why not).

    The frames are the audio gate's stored log-mel (`AUDIO_GATE_DIR`
    `features/<sid>.npz`) less its median. Live frames are the audio gate's
    (alive in a live phase, at its 0.1 s step) where the log-mel window lies
    inside the audio, and, where `kit_spans` name kits, near a span of
    `agent`'s kit (`tray_kit.own_kit_mask`): the tray shows the player's kit
    while the player lives. The casts are the gate's (`player_tray_casts`
    rows with `player_cast`) on a frame the audio gate calls live. The null
    frames are `ability_audio.background`: live, the gate's background class,
    and no own cast, gunfire span or known other sound within
    `ability_audio.EXPLAIN_S`; the drops refused for another kit
    (KIT_REFUSALS) are known other sounds. `span_s` keeps only frames and
    casts inside [start, end) s, how one session is split in two.
    `neighbours` holds the frames of every cast the gate passes, which cut
    each cast's window (`ability_audio.clip_bounds`). Decodes nothing."""
    import numpy as np

    from .adjudication.ability_audio import FPS, background, explained, session_frames
    from .adjudication.tray_kit import own_kit_mask
    root = Path(store_root)
    fp = Path(features_path) if features_path else root / AUDIO_GATE_DIR / "features" / f"{session_id}.npz"
    lp = Path(labels_path) if labels_path else root / AUDIO_GATE_DIR / "labels" / f"{session_id}.json"
    if not fp.is_file():
        return None, "no_audio_features"
    if not lp.is_file():
        return None, "no_audio_labels"
    z = np.load(fp, allow_pickle=True)
    med = z["med"] if "med" in z.files else np.median(z["L"].astype(np.float32), axis=0)
    X = session_frames(z["L"], med)
    n = len(X)
    lab = json.loads(lp.read_text(encoding="utf-8"))
    lz = np.load(lp.with_suffix(".npz"))
    rep = int(round(float(lab["step_s"]) * FPS))
    up = lambda a: np.concatenate([np.repeat(a, rep), np.zeros(max(0, n - rep * len(a)), a.dtype)])[:n]
    gate_live = up(lz["live"]).astype(bool)
    live = gate_live & z["ok"][:n].astype(bool)
    cls = up(lz["cls"])
    if kit_spans:
        live &= own_kit_mask(np.arange(n) * (1000.0 / FPS), kit_spans, agent)
    keep = np.ones(n, bool)
    if span_s is not None:
        keep[:] = False
        keep[int(span_s[0] * FPS):int(span_s[1] * FPS)] = True
        live &= keep
    casts = []
    for r in gate_rows:
        k = int(r["t_ms"] / 1000.0 * FPS)
        if r["player_cast"] and 0 <= k < n and gate_live[k] and keep[k]:
            casts.append({"t_ms": float(r["t_ms"]), "slot": r["slot"], "frame": k})
    others = ([float(o["t"]) for o in lab.get("known_others", [])]
              + [r["t_ms"] / 1000.0 for r in gate_rows if r.get("reason") in KIT_REFUSALS])
    code = explained(n, [c["t_ms"] / 1000.0 for c in casts], lab.get("fires", []), others)
    bg = background(live, cls, code)
    stamps = {"audio_features": features_stamp(z, fp),
              "audio_labels": lab.get("version"), "features_path": fp.as_posix(),
              "labels_path": lp.as_posix()}
    # Every own cast the gate passes, live or not, bounds a cast's window.
    neighbours = np.array([int(r["t_ms"] / 1000.0 * FPS) for r in gate_rows
                           if r["player_cast"]], int)
    return {"X": X, "live": live, "code": code, "bg": bg, "casts": casts,
            "neighbours": neighbours,
            "live_min": float(live.sum()) / (60.0 * FPS), "stamps": stamps}, None


def audio_cast_witness(store_root, session_id: str, gate_rows: list[dict], agent: str | None,
                       kit_spans=None, *, params=None, session=None, xp=None,
                       **where) -> dict:
    """The audio witness for each of the player's casts: which kit ability
    the audio around the drop sounds like (`adjudication.ability_audio`),
    with its scores, margin and refusal, and beside the margin `p_right`:
    P(the best referenced class, `best_ref`, is the slot) from the set's
    stored calibration (`ability_audio.ref_margin`, `p_right`), None with
    `p_right_reason` where the set carries none. Where the set declares a
    phase group (abilities sharing a sound, e.g. Sova's bolts sharing their
    release), the group is one kit class and its later phase names the slot
    (`ability_audio.cast_verdicts`); the row's `phase` holds that evidence.
    The candidate set is the player's
    kit, named by the identity arbiter's agent (`agent`) through the
    parameter set's classes; a cast of a slot with no reference can only be
    refused or named as another slot, and the row says the slot is
    unreferenced. Returns {"rows", "coverage"}; without an agent, parameters,
    features or labels every cast row carries the reason and no score.
    `where` passes `features_path`, `labels_path` and `span_s` to
    `audio_session`."""
    from . import ult_lines
    from .adjudication.ability_audio import (cast_verdicts, kit_classes, load_params,
                                             referenced_slots, session_tracks, whiten_frames)
    from .version import ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION
    casts = [r for r in gate_rows if r["player_cast"]]
    base = {"ability_audio_version": ABILITY_AUDIO_VERSION,
            "params_version": ABILITY_AUDIO_PARAMS_VERSION}

    def refuse(why, stamps=None):
        return {"rows": [{**base, "t_ms": float(r["t_ms"]), "slot": r["slot"], "reason": why,
                          "verdict": None} for r in casts],
                "coverage": {**base, "agent": agent, "reason": why, "casts": len(casts),
                             "inputs": stamps or {}}}

    if agent is None:
        return refuse("no_player_agent")
    if params is None:
        params, why = load_params(store_root, ABILITY_AUDIO_PARAMS_VERSION, agent)
        if params is None:
            return refuse(why)
    if session is None:
        session, why = audio_session(store_root, session_id, gate_rows, agent, kit_spans,
                                     **where)
        if session is None:
            return refuse(why)
    xp = xp or ult_lines.array_module()
    Xw = whiten_frames(session["X"], params["mu"], params["P"], params["ar"])
    tracks = session_tracks(Xw, params, session["bg"], xp)
    groups = params.get("groups") or []
    classes = kit_classes(list(tracks), groups)
    referenced = referenced_slots(classes, groups)
    # The kit-level verdict, a phase group's later phase where one wins, and
    # the calibrated probability beside the margin, never in its place.
    cal = params.get("calibration")
    ids = cast_verdicts(tracks, [c["frame"] for c in session["casts"]],
                        session.get("neighbours", ()), params)
    at = {c["t_ms"]: (c, v) for c, v in zip(session["casts"], ids)}
    rows = []
    for r in casts:
        c, v = at.get(float(r["t_ms"]), (None, None))
        if v is None:
            rows.append({**base, "t_ms": float(r["t_ms"]), "slot": r["slot"],
                         "reason": "audio_not_live", "verdict": None})
            continue
        rows.append({**base, "t_ms": c["t_ms"], "slot": c["slot"],
                     "slot_referenced": c["slot"] in referenced, **v,
                     "agrees": None if v["verdict"] is None else v["verdict"] == c["slot"]})
    cov = {**base, "agent": agent, "reason": None, "candidate_set": {
               "classes": classes, "why": "the player's kit: the tray shows it while the player "
                                          "lives, and the gate passes only drops under it; "
                                          "`none` holds the agent's unmapped files"},
           "params": {k: params["provenance"].get(k) for k in ("version", "reference", "fitted_at")},
           "dev_sessions": params["dev"], "thresholds": params["thresholds"],
           "groups": groups, "calibration": cal,
           "casts": len(casts), "scored": len(ids), "null_frames": int(session["bg"].sum()),
           "live_min": round(session["live_min"], 2), "inputs": session["stamps"],
           "verdicts": dict(sorted(Counter(r.get("verdict") or f"refused:{r['reason']}"
                                           for r in rows).items()))}
    return {"rows": rows, "coverage": cov, "tracks": tracks, "session": session}


def build_timeline(root: str | Path) -> dict:
    """Return deterministic use claims from the current evidence inventory."""
    root = Path(root).resolve()
    inventory = build_inventory(root)
    source_hashes = {r["path"]: r["sha256"]
                     for r in inventory["manifest"]["source_files"]}
    audio = _audio_references(root)
    spectated = {row["session_id"] for row in inventory["sessions"]
                 if "spectator" in (row.get("tags") or [])}
    labels_by_ability = defaultdict(list)
    for row in inventory["source_windows"]:
        if row["source_kind"] == "human_ability_label" and row.get("ability_id"):
            labels_by_ability[(row["session_id"], row["ability_id"])].append(row)

    claims = []
    for row in inventory["source_windows"]:
        if row["source_kind"] != "tray_cast_candidate":
            continue
        t_ms = float(row["t_observed_ms"])
        step_ms = _step_ms(row["source_path"])
        occurrence_start = max(0.0, t_ms - step_ms) if step_ms else None
        label_candidates = [
            r["window_id"] for r in labels_by_ability.get(
                (row["session_id"], row.get("ability_id")), [])
            if t_ms - 2000.0 <= r["t_observed_ms"] <= t_ms + 15000.0
        ] if row.get("ability_id") else []
        audio_candidates = [
            a for a in audio if a["session_id"] == row["session_id"]
            and abs(a["t_ms"] - t_ms) <= max(step_ms or 0.0, 100.0)
        ]
        source_ref = {
            "path": row["source_path"],
            "record": row["source_record"],
            "sha256": source_hashes.get(row["source_path"]),
        }
        claims.append({
            "use_claim_id": f"use:{row['session_id']}:{Path(row['source_path']).name}:"
                            f"{row['source_record']}",
            "session_id": row["session_id"],
            "agent": row.get("agent"),
            "ability_id": row.get("ability_id"),
            "ability": row.get("ability"),
            "slot": row.get("key"),
            # A spectator clip reads the OBSERVED player's tray, so the caster is
            # whoever the camera is on, not whoever is holding the mouse.
            "owner": (None if not row.get("agent")
                      else "observed_player" if row["session_id"] in spectated
                      else "local_player"),
            "observed_t_ms": t_ms,
            "available_t_ms": t_ms,
            "occurrence_interval_ms": [occurrence_start, t_ms],
            "sampling_step_ms": step_ms,
            "transition": None,
            "transition_alternatives": list(TRANSITION_ALTERNATIVES),
            "status": "suspect" if row.get("suspect") else "candidate",
            "status_reason": ("reader_flagged_drop" if row.get("suspect")
                              else "single_slot_drop"),
            "identity_status": ("setup_agent_and_reference_slot" if row.get("ability_id")
                                else "unresolved"),
            "source_evidence": [source_ref],
            "audio_reference_candidates": audio_candidates,
            "human_label_candidates": sorted(label_candidates),
            "minimap_required": False,
            "raw": row.get("raw"),
        })

    # A reader change creates a new cache beside the old one.  Equivalent rows
    # are two provenance roots for one observation, not two game events.
    equivalent = defaultdict(list)
    for claim in claims:
        key = (claim["session_id"], claim["observed_t_ms"], claim["slot"],
               json.dumps(claim.get("raw"), sort_keys=True))
        equivalent[key].append(claim)
    merged_claims = []
    for key, same in equivalent.items():
        claim = dict(same[0])
        claim["source_evidence"] = sorted(
            (e for row in same for e in row["source_evidence"]),
            key=lambda e: (e["path"], e["record"]),
        )
        raw_key = hashlib.sha256(key[3].encode()).hexdigest()[:8]
        claim["use_claim_id"] = (f"use:{key[0]}:{key[1]:g}:{key[2]}:{raw_key}")
        merged_claims.append(claim)
    claims = merged_claims

    conflicts = list(inventory["conflicts"])
    grouped = defaultdict(list)
    for claim in claims:
        grouped[(claim["session_id"], claim["observed_t_ms"], claim["slot"])].append(claim)
    for key, alternatives in grouped.items():
        raw_values = {json.dumps(c.get("raw"), sort_keys=True) for c in alternatives}
        if len(raw_values) > 1:
            conflicts.append({
                "reason": "multiple_cast_cache_interpretations",
                "session_id": key[0], "observed_t_ms": key[1], "slot": key[2],
                "use_claim_ids": sorted(c["use_claim_id"] for c in alternatives),
            })

    claims.sort(key=lambda r: (r["session_id"], r["observed_t_ms"], r["use_claim_id"]))
    summary = {
        "use_claims": len(claims),
        "equivalent_cache_rows_collapsed": sum(len(v) - 1 for v in equivalent.values()),
        "sessions_with_claims": len({r["session_id"] for r in claims}),
        "clean_candidates": sum(r["status"] == "candidate" for r in claims),
        "suspect_candidates": sum(r["status"] == "suspect" for r in claims),
        "identified_candidates": sum(r["ability_id"] is not None for r in claims),
        "audio_reference_candidates": sum(bool(r["audio_reference_candidates"]) for r in claims),
        "label_candidate_links": sum(len(r["human_label_candidates"]) for r in claims),
        "by_slot": dict(sorted(Counter(r["slot"] for r in claims).items())),
        "conflicts": len(conflicts),
    }
    return {
        "manifest": {
            "schema_version": 1,
            "producer_version": ABILITY_TIMELINE_VERSION,
            "store_root": str(root),
            "coverage_producer_version": inventory["manifest"]["producer_version"],
            "source_files": inventory["manifest"]["source_files"],
            "audio_reference_files": audio,
            "summary": summary,
            "limits": [
                "Tray drops are use candidates, not resolved cast semantics.",
                "Source-linked audio cuts are references, not independent detections.",
                "Human label links are temporal candidates, not parent-child adjudications.",
            ],
        },
        "use_claims": claims,
        "conflicts": sorted(conflicts, key=lambda r: json.dumps(r, sort_keys=True)),
    }


def write_timeline(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("use_claims", "conflicts"):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in bundle[name]),
            encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    return out


def materialize_demo_casts(root: str | Path, step_s: float = 0.5) -> dict:
    """Drive the existing tray reader over every tagged demo source.

    This is the only media-reading part of milestone B.  It writes new,
    reader-hash-keyed cache files and never replaces labels or old caches.
    """
    if step_s <= 0:
        raise ValueError("step must be positive")
    root = Path(root).resolve()
    # The reader still owns prototype-specific calibration.  Bind its existing
    # path parameters explicitly so a non-default test store cannot leak into
    # the user's store.
    from prototypes import ability_cast as cast
    from prototypes import ability_hud as hud

    cast.STORE = hud.STORE = root
    cast.LAB = root / "labels" / "ability"
    cast.CACHE = root / "casts"
    cast.CAND = root / "labels" / "ability_candidates"
    cast.EVENTS = root / "events" / "ability"
    manifests = []
    for path in sorted((root / "manifests").glob("*.json")):
        man = json.loads(path.read_text(encoding="utf-8"))
        if "ability-demo" in man.get("tags", []):
            manifests.append(man)
    result = []
    for man in manifests:
        sid = man["session_id"]
        before = set((root / "casts").glob(f"{sid}.step{step_s}.*.json"))
        rows, agent = cast.tray_casts(sid, step_s=step_s, use_cache=True)
        after = set((root / "casts").glob(f"{sid}.step{step_s}.*.json"))
        result.append({
            "session_id": sid, "agent": agent, "n_candidates": len(rows),
            "cache_paths": sorted(p.relative_to(root).as_posix() for p in after),
            "created": sorted(p.relative_to(root).as_posix() for p in after - before),
        })
    return {"sessions": result, "candidates": sum(r["n_candidates"] for r in result)}


def run(root: str | Path = DEFAULT_STORE, out: str | Path | None = None,
        *, materialize: bool = False, step_s: float = 0.5) -> tuple[dict, dict | None]:
    materialized = materialize_demo_casts(root, step_s) if materialize else None
    bundle = build_timeline(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-timeline"
    write_timeline(bundle, target)
    return bundle, materialized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--step", type=float, default=0.5)
    args = parser.parse_args(argv)
    bundle, materialized = run(args.store, args.out, materialize=args.materialize,
                               step_s=args.step)
    if materialized:
        print(f"materialized {materialized['candidates']} candidates across "
              f"{len(materialized['sessions'])} demos")
    summary = bundle["manifest"]["summary"]
    print(f"{summary['use_claims']} use claims across {summary['sessions_with_claims']} sessions; "
          f"{summary['suspect_candidates']} suspect; {summary['conflicts']} conflicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
