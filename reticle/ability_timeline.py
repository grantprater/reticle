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
             ) -> tuple[float | None, list[list]]:
    """(the first of the player's deaths in the round `window` that ends the
    player's kit, or None; the deaths before it that the game undid, each as
    [t_ms, why]). `player_tray_casts` says how a death is undone."""
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
    if agent == "Clove":
        revives = inside(revives_ms)
        for t, nxt in zip(deaths, deaths[1:] + [float("inf")]):
            if any(t <= r < nxt for r in revives):
                undone[t] = "not_dead_yet"
    end = next((t for t in deaths if t not in undone), None)
    return end, [[t, undone[t]] for t in deaths if t in undone and (end is None or t < end)]


def kit_windows(rounds: list[dict], player_deaths_ms: list[float], *,
                agent: str | None = None, second_lives_ms=(), revives_ms=(),
                report_deaths: dict | None = None, kit_changes_ms=(),
                kit_returns_ms=()) -> list[dict]:
    """Per stored round, in order: its `window` (start, end, close), the
    `kit_end_ms` that ends the player's kit in it or None, the
    `undone_deaths` before that end, each as [t_ms, why], the
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
        end, undone = _kit_end(w, ends, player_deaths_ms, agent, second_lives_ms,
                               revives_ms, report_deaths)
        change = min((c["t_first"] for c in in_round_window(changes, *w, ends)), default=None)
        back = (None if change is None else
                min((c["t_first"] for c in in_round_window(returns, *w, ends)
                     if c["t_first"] > change), default=None))
        out.append({"round_no": r.get("round_no"), "window": w, "kit_end_ms": end,
                    "undone_deaths": undone, "kit_change_ms": change, "kit_return_ms": back})
    return out


def round_window_of(t_ms: float, kits: list[dict]) -> dict | None:
    """The entry of `kit_windows` whose round holds the instant `t_ms`, by
    `rounds.in_round_window`, or None."""
    ends = {k["window"][1] for k in kits}
    return next((k for k in kits if in_round_window([{"t_first": t_ms}], *k["window"], ends)),
                None)


def player_tray_casts(drops: list[dict], phase_of, rounds: list[dict],
                      player_deaths_ms: list[float], *, agent: str | None = None,
                      second_lives_ms=(), revives_ms=(),
                      report_deaths: dict | None = None, kit_changes_ms=(),
                      kit_returns_ms=(), menu_at=None) -> list[dict]:
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
    arbiter names it. A death ends the kit unless the game undid it, and among
    the player's agents it undoes one for two only
    [domain:rounds/resurrection-mechanics]:

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
    * **Clove.** Not Dead Yet needs Clove's death
      [domain:abilities/clove-c-and-x-need-a-target], and its killfeed entry
      is the revive itself [domain:killfeed/revive-entries]. A death followed
      by the player's own revive entry (`revives_ms`) before her next death in
      the round does not end her kit, so a drop between the death and the
      revive meets the remaining tests like any other.

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

    Every test names its refusal, and a drop keeps the first that refuses it,
    in this order: `no_round`, `after_player_death`, `after_kit_change`,
    `phase:<name>`, `forced` or `cooccur_among_casts`, `partial_charge`,
    `pips_lit`, `equip_release`.

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

    Every drop comes back with `player_cast`, the first `reason` that refused
    it, the round's `first_player_death_ms`, the `kit_end_ms` the gate used,
    the `undone_deaths` before it, and the round's `kit_change_ms`.
    """
    ends = {r["t_end_ms"] for r in rounds}
    deaths = [{"t_first": x} for x in player_deaths_ms]
    kits = kit_windows(rounds, player_deaths_ms, agent=agent, second_lives_ms=second_lives_ms,
                       revives_ms=revives_ms, report_deaths=report_deaths,
                       kit_changes_ms=kit_changes_ms, kit_returns_ms=kit_returns_ms)
    rows = []
    for d in drops:
        t = d["t_ms"]
        k = round_window_of(t, kits)
        rnd = k["window"] if k else None
        first = (min((e["t_first"] for e in in_round_window(deaths, *rnd, ends)), default=None)
                 if rnd else None)
        end, undone = (k["kit_end_ms"], k["undone_deaths"]) if k else (None, [])
        change, back = (k["kit_change_ms"], k["kit_return_ms"]) if k else (None, None)
        phase = phase_of(t)
        reason = ("menu_open" if menu_at is not None and menu_at(t) is True
                  else "no_round" if rnd is None
                  else "after_player_death" if end is not None and t >= end - DEATH_LEAD_MS
                  else "after_kit_change" if (change is not None and t >= change
                                              and (back is None or t < back))
                  else None if phase in CAST_PHASES else f"phase:{phase}")
        rows.append({**d, "phase": phase,
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
    for r in rows:
        r["player_cast"] = r["reason"] is None
    return rows


def stored_gate_inputs(store, session_id: str, date: str, rounds: list[dict],
                       agent: str | None) -> tuple[dict, dict]:
    """(the keyword inputs of `player_tray_casts` beyond the drops and rounds,
    read from storage; their stamps). Decodes nothing.

    The phase is `gametime`'s over the stored HUD, and the deaths are the HUD's
    killfeed tracks. Second lives come from the stored badge reads, which only
    a current `killfeed_portrait` stream carries
    (`adjudication.death.stored_second_life`). Revives are the player's own
    revive entries among the stored `death` verdicts. The report's death
    counts are the stored `combat_report_round` rows where a report was read.
    The kit changes are the stored `tray_kit` rows
    (`adjudication.tray_kit.stored_kit_witness`), used only where they are
    current and name the same player agent; otherwise the list is empty and
    the stamp says why. The menu witness is the stored `menu_open` rows
    (`menu.stored_menu`), used only where current; otherwise `menu_at` is None
    and the stamp says why.
    """
    from . import gametime, stalls
    from .adjudication.death import stored_second_life
    from .adjudication.tray_kit import stored_kit_witness
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .menu import stored_menu
    from .rounds import player_death_times, player_second_life_times
    from .version import PLAYER_CAST_VERSION

    hud = store.read_hud(session_id, date)
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
        "revives_ms": sorted(float(r["t_ms"]) for r in verdicts
                             if r.get("is_revive") and r.get("kf_player_kill")),
        "report_deaths": {float(r["t_start_ms"]): int(r["deaths"]) for r in report
                          if r.get("verdict_source") == "combat_report"
                          and r.get("deaths") is not None},
    }
    kit = stored_kit_witness(store.read_events("tray_kit", session_id), agent=agent)
    inputs["kit_changes_ms"] = kit["kit_changes_ms"]
    inputs["kit_returns_ms"] = kit["kit_returns_ms"]
    menu, menu_stamp = stored_menu(store, session_id)
    inputs["menu_at"] = menu.at if menu is not None else None
    head = lambda rows, key: rows[0].get(key) if rows else None
    stamps = {"player_cast": PLAYER_CAST_VERSION,
              "hud": (hud.schema.metadata or {}).get(b"hud_version", b"").decode() or "unstamped",
              "gametime": gametime.GAMETIME_VERSION,
              "killfeed_portrait": KILLFEED_PORTRAIT_VERSION if badges is not None else None,
              "death": head(verdicts, "death_adjudication_version"),
              "combat_report_round": head(report, "combat_report_round_version"),
              "tray_kit": kit["version"] if kit["reason"] is None else kit["reason"],
              "menu_open": menu_stamp}
    return inputs, stamps


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
