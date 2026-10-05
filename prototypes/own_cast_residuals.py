r"""Attribute each own cast the store misses against Riot, and each it holds
beyond Riot, to one primary cause from stored evidence.

    .\.venv\Scripts\python.exe prototypes\own_cast_residuals.py [SID ...] [--cache DIR]
        [--json OUT] [--view DIR] [--record]

`prototypes/tray_gold_eval.py` scores the player's own casts against Riot's
per-ability counts on the 21 Riot-paired matches: covered is min(ours,
Riot's) per session and ability. Riot's records carry per-match totals only
(`stats.abilityCasts`; each round's `ability` effects are null), so the slot
this prototype explains is (session, ability), and an item's round is the
round of the evidence that places it. Riot's records are evaluation truth
only; nothing here is fitted to them.

Inputs. The tray pass `reticle tray` runs over the minimap crop cache
(`tray_gold_eval._pass`, kept in `--cache`), `tray.drops`, the gold witness
(`cli._gold_witness`) and the cast gate
(`ability_timeline.player_tray_casts`) over its stored inputs
(`stored_gate_inputs`), as `tray_gold_eval` runs them at the wired
`GOLD_PERSIST_MIN`. Beside them, stored witnesses that give a missed cast a
time or a sign: the player's own ult lines (`ult_cast` rows with
`player_cast`); the state model's falls without a drop (`ability_state`
verdicts `fall_without_a_drop` and `unlit_without_a_drop` while the owner
lived) and the charges it saw held at each death (`owner_death`); and, at
each refused drop, three readings by their owners: the kit the slot icons
show (`adjudication.tray_kit.read_sample`, its candidate set from the stored
lineup), a spend witness (`tray.gold_witness` asked of the drop: a restock
numeral appearing or restarting, or the slot's icon dimming while no other
lit icon dims) and the audio's verdict (`ability_audio.cast_verdicts` under
the agent's stored parameters). Decodes no video and writes nothing to the
store but the optional metrics row.

The gate is rerun beside the stored one with two inputs it does not read
(`rejudge_inputs`): the second lives from the stored badge rows whatever their
`killfeed_portrait` version (the gate reads only a current stream, and on
2026-10-05 every Phoenix session stored 0.18.0 against the code's 0.19.0),
and the teammate revives of the player (stored `death_verdict` revives on
the ally side whose victim is the player's agent, from any reviver but the
player; the gate undoes a death only for Phoenix's second life and Clove's
own revive). A drop the
stored gate refused as `after_player_death` that the rerun judges otherwise
carries the rerun's reason and kit end, and the input that changed it as its
`root`: `second_life_unread` or `teammate_revive`. The candidate tests judge
it by the rerun's reason; its cause stays the stored gate's reason.

Each missing cast takes ONE class, by the first evidence that holds, in this
order (`attribute_slot`):

1. an own ult line with no gated X cast from 3 s before it to 15 s after it
   (Run it Back's pips fall at its end
   [domain:abilities/phoenix-run-it-back-expiry-flash]): the refused X drop
   there that emptied the slot, nearest the line (class 3, its gate reason),
   a gold drop the witness refused (class 2), else no drop (class 1);
2. a refused drop of the slot under the player's own kit by the icons that
   could be a cast (`attribute_slot`, `solo`): one the rerun gate passes; not
   refused for its phase; a death refusal only in the second before the
   kit's end (the rerun's, where a root undid the stored one) and with a
   numeral or the audio; a landing at the full level only with a spend witness; a
   drop onto an undrawn tray only with no other slot falling within
   `tray.SUSPECT_S`; else fewer than two other slots falling on the same or
   the next sample (`SAME_SAMPLE_MS`; `_others_falling`, this classifier's
   rule, not `tray.flag_suspect`, which marks a drop with any other slot
   falling within `tray.SUSPECT_S`). Those with a spend witness or the
   audio rank first: class 3;
3. a gold-only drop the witness refused (`tray.gold_witness`): class 2;
4. a charge held at the player's death, where the agent spends while dead
   (`SPENT_WHILE_DEAD`): class 1, the tray showing a spectated kit;
5. a fall of the slot's level without a drop, while the owner lived, with no
   drop of the slot within `tray.SUSPECT_S` and no cast of it in the
   `FALL_SAME_MS` before: class 1, with the tray's state over the fall;
6. a candidate drop whose kit the icons left unread, its reason not a death
   or kit refusal: class 3;
7. otherwise class 7, unexplained.

A missing item whose drop lies within `tray.SUSPECT_S` of a cast the gate
passed in another slot that holds more casts than Riot's becomes class 4.
No Riot-side rule (class 5) is held: no domain fact on 2026-10-05 says Riot's
count records a cast the tray cannot show (`RIOT_SIDE`). Each excess cast
(class 6) is the gated cast of the slot that the stored evidence trusts
least (`excess_order`); `EXCESS_EYE` holds the eye's label of each pick on
the tray strip, and a pick the eye calls a real spend leaves its slot's
extra cast unplaced. Where a slot holds more candidates than casts
missing, which candidate stands for the cast is a ranking, not a
measurement; each item carries the count left over
(`slot_candidates_unused`).

The candidate tests, their ranking (`spent_first`), the excess ranking
(`excess_order`) and `_others_falling` are this prototype's own classifier
rules, refined on tray strips viewed by eye; the gate, the drops, the
witnesses, the kit read and the scoring (`tray_gold_eval.score_slots`,
`total`) are their owners'.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OWN_CAST_RESIDUALS_VERSION = "own-cast-residuals-0.2.0"
CLASSES = {1: "no_tray_drop", 2: "witness_refused", 3: "gate_refused", 4: "wrong_slot",
           5: "riot_side", 6: "excess", 7: "unexplained"}
#: The window round an own ult line in which a gated X cast is its cast: the
#: pips fall at Run it Back's end, about 10 s after the line.
LINE_BEFORE_MS, LINE_AFTER_MS = 3000.0, 15000.0
#: The refusals that say the tray was not the player's; a drop they refuse is
#: a candidate only where the icons read the player's own kit.
NOT_OWN = ("after_player_death", "after_kit_change", "kit_not_player", "kit_owner_unresolved",
           "menu_open", "no_round", "no_rounds")
#: Riot-side rules: an ability whose cast Riot counts with no tray signature,
#: each with the domain fact that says so. None held on 2026-10-05.
RIOT_SIDE: dict = {}
#: The state model's transitions that read a fall with no drop.
STATE_FALLS = ("fall_without_a_drop", "unlit_without_a_drop")
#: Two other slots falling within this of a drop make it part of a fall of
#: the whole tray (a death screen, a spectator switch, a round's reset): the
#: tray is read every 0.5 s, so this is the same or the next sample. Iso's
#: Kill Contract empties X a second before the tray goes dark, and a wider
#: window would call that cast a transition.
SAME_SAMPLE_MS = 600.0
#: A fall without a drop this soon after a cast or a taken drop of its slot is
#: that cast read late. On b3b9defb6fd7, by eye, the Q bar was full with a
#: white fox icon from 343.98 s to 346.48 s and grey from 346.98 s, the icon
#: tinted red as Trailblazer flew: a spend at about 346.9 s. The state model,
#: its guard rows flooded, read the slot full at 346.6 s and empty only at
#: 350.6 s, 3.7 s after the spend.
FALL_SAME_MS = 5000.0
#: The slots a dead caster still spends, by agent: the agent from
#: `ability_candidates.CASTS_WHILE_DEAD`, the slot from its fact. After the
#: death the tray shows a spectated kit [domain:hud/tray-after-player-death],
#: so such a cast has no drop; the charges the state model saw held at the
#: death bound how many there can be.
SPENT_WHILE_DEAD = {"Clove": ("E", "abilities/clove-smokes-after-death")}
#: The eye's label of each excess pick (session, slot, time in s rounded to
#: 0.1) on its tray strip, 2026-10-05: a real spend leaves the slot's extra
#: cast unplaced; the others name what made the false drop. 043bafca271a C
#: 1774.0 s: the C bar teal to 1773.5 s, then grey with no refill to the
#: round's end (Owl Drone).
EXCESS_EYE = {
    ("043bafca271a", "C", 1774.0): "real_spend",
    ("b7d24102a6f6", "Q", 1062.5): "real_spend",
    ("e37fdeca944f", "E", 1441.5): "real_spend",
    ("b7d24102a6f6", "C", 375.1): "regrowth_pool",
    ("e37fdeca944f", "C", 1714.0): "regrowth_pool",
    ("5822b6646448", "E", 1279.5): "flash_streak_or_tint",
    ("a06f04a0059f", "Q", 1412.5): "flash_streak_or_tint",
    ("bfad2778a372", "X", 405.6): "flash_streak_or_tint",
}
#: The roots `rejudge_inputs` names, by the gate input each supplies.
ROOTS = {"second_lives_ms": "second_life_unread", "player_deaths_ms": "teammate_revive"}


# ---------------------------------------------------------------- attribution

def _others_falling(row: dict, rows: list[dict], near_ms: float, full_level: float) -> int:
    """Other slots' drops within `near_ms` of `row`, a release from above the
    full level not counted. A rule of this classifier, not
    `tray.flag_suspect`: that marks a drop with ANY other slot falling within
    `tray.SUSPECT_S` among the drops; this counts them, so `solo` can tell a
    fall of the whole tray (two or more on the same or the next sample) from
    a cast beside one other."""
    return sum(1 for y in rows if y["slot"] != row["slot"]
               and abs(y["t_ms"] - row["t_ms"]) <= near_ms
               and not (y.get("reason") == "equip_release" and y["from"] > full_level))


def attribute_slot(s: dict, near_ms: float = 1500.0, full_level: float = 1.0,
                   same_ms: float = SAME_SAMPLE_MS, full_after: float = 0.75,
                   empty_max: float = 0.2) -> list[dict]:
    """The items of one (session, ability) slot. `s` holds `riot`, `ours`,
    `agent`, `slot`, `rows` (this slot's gate rows, each with `reason`,
    `player_cast`, `t_ms`, `from`, `to`, `kit_read`), `all_rows` (every
    slot's, for the solo test), `unwitnessed` (this slot's refused gold-only
    drops with `kit_read`), `lines` (own ult line times, X only),
    `state_falls` ((the state's last reading before, the fall) times),
    `held_at_death` (one entry per charge the state model saw held at a
    death, as {t_ms, charges, fact}, only where `SPENT_WHILE_DEAD` names the
    slot), `excess_casts` (other slots' gated casts in slots over Riot's
    count, as (slot, t_ms)) and `tray_state` (a function of a time, and of
    the time the fall began, giving the tray's state, or None). A refused
    row may carry `spend_witness`, `audio` and `forced`. Each item is
    `{"kind": "missing"|"extra", "class", "cause", "t_ms", "evidence"}`."""
    deficit = s["riot"] - s["ours"]
    items = []
    if deficit < 0:
        for r in excess_order(s)[:-deficit]:
            eye = _excess_eye(s.get("session"), s.get("slot"), r["t_ms"])
            items.append({"kind": "extra", "class": 6, "cause": r["why"], "t_ms": r["t_ms"],
                          "evidence": r["evidence"] | {"eye": eye},
                          "unplaced": eye == "real_spend"})
        return items
    if deficit == 0:
        return items
    rows, gated = s["rows"], [r for r in s["rows"] if r["player_cast"]]
    used = set()

    def take(cls, cause, r, how, **ev):
        used.add(id(r) if r is not None else None)
        items.append({"kind": "missing", "class": cls, "cause": cause,
                      "t_ms": None if r is None else r["t_ms"], "how": how,
                      "evidence": ({} if r is None else _row_evidence(r)) | ev})

    # 1. own ult lines with no gated cast near them
    free = sorted(gated, key=lambda r: r["t_ms"])
    for t in sorted(s.get("lines") or []):
        win = [r for r in free if t - LINE_BEFORE_MS <= r["t_ms"] <= t + LINE_AFTER_MS]
        if win:
            free.remove(min(win, key=lambda r: abs(r["t_ms"] - t)))
            continue
        if len(items) >= deficit:
            break
        near = [r for r in rows if not r["player_cast"] and id(r) not in used
                and t - LINE_BEFORE_MS <= r["t_ms"] <= t + LINE_AFTER_MS]
        gold = [u for u in s["unwitnessed"] if id(u) not in used
                and t - LINE_BEFORE_MS <= u["t_ms"] <= t + LINE_AFTER_MS]
        if near:
            # The drop that emptied the slot, nearest the line: a flash
            # leaving a lit bar also reads as a fall (`pips_lit`).
            r = min(near, key=lambda r: (r["to"] > empty_max, abs(r["t_ms"] - t)))
            take(3, r["reason"], r, "ult_line", line_t_ms=t)
        elif gold:
            take(2, _witness_cause(gold[0]), gold[0], "ult_line", line_t_ms=t)
        else:
            st = s["tray_state"](t) if s.get("tray_state") else None
            items.append({"kind": "missing", "class": 1, "cause": (st or {}).get("why", "unknown"),
                          "t_ms": t, "how": "ult_line", "evidence": {"line_t_ms": t,
                                                                     "tray": st}})

    def solo(r):
        # A forced drop lands on an undrawn sample, so any other slot falling
        # beside it is the tray going dark (by eye, 223d636bf8d2 577.5 s and
        # 3694746e4e54 334.1 s: one blank sample, the bar full again after);
        # a drop after the kit's end is the death screen or a spectated kit.
        # A drop the phase refused is no candidate unless a line places it:
        # the replay of 9acf02f98283 holds 41 of the player's casts and none
        # in the buy phase; by eye the three buy-phase drops this rule first
        # took (223d636bf8d2 2281.5 s, c40d950031bb 216.5 s, 7010b3d62460
        # 942.5 s) were the whole tray dimming as the phase began, and the
        # round-end ones (223d636bf8d2 577.5 s, 3694746e4e54 334.1 s) a blank
        # sample, with the tray dimming at the round's end beside them.
        reason = _eff(r)
        if reason is None:
            # The gate rerun with the second lives and teammate revives it
            # does not read passes it: the stored gate's death refusal is
            # the whole cause (`root`).
            return True
        if reason.startswith("phase:"):
            return False
        wit = r.get("spend_witness") or []
        heard = r.get("audio") == r["slot"]
        if reason == "after_player_death":
            # Before the kit's end only, with a numeral read over the slot
            # after it, or heard with the icon dimming: the death screen
            # blanks the tray and dims its icons in that second
            # (9acf02f98283 1300.0 s by eye, where the
            # replay's Shock Bolt was at 967.5 s; a1a995e6b19b 2154.0 s, heard
            # as Q, was the death screen too), while 223d636bf8d2 943.5 s, a
            # Recon Bolt 1 s before the death, drew its numeral, its icon
            # dimmed and the audio named E.
            if r["t_ms"] >= (_eff_kit_end(r) or 0.0):
                return False
            numeral = (r.get("spend_evidence") or {}).get("countdown") in (
                "appeared", "restarted", "unread_before")
            if not (numeral or (heard and "icon" in wit)):
                return False
        if r["to"] >= full_after and not wit:
            # Landed at the full level with no numeral or icon: by eye the
            # eight such drops this rule first took (7010b3d62460 156.0,
            # 872.0 and 1673.5 s, ff636d173b07 468.1 and 682.1 s,
            # 223d636bf8d2 1865.0 s, and 587c15b07779 306.1 s and
            # a1a995e6b19b 1941.5 s, which the audio alone named) kept a
            # full bar throughout, teal or a glow passing over.
            return False
        if r.get("forced"):
            # The tray is undrawn after a forced drop, so every icon dims:
            # only a numeral or the audio witnesses it (4f207c0c4e39
            # 1048.6 s, the tray gone with no other witness, by eye no cast).
            return (_others_falling(r, s["all_rows"], near_ms, full_level) == 0
                    and ("countdown" in wit or heard))
        return _others_falling(r, s["all_rows"], same_ms, full_level) < 2

    def spent_first(r):
        # A drop that left its slot below the full level spent a charge; one
        # that landed at it (a release, or a view tint over the bar) did not
        # by the tray's reading, so it ranks after. Then the audio around the
        # drop naming this slot ranks first, naming another slot last.
        # Before both, a spend witness: the restock numeral or the slot
        # icon (`tray.gold_witness`) or the audio saw the spend; then a drop
        # in the second before the kit's end, where the death screen blanks
        # the tray (`ability_timeline.DEATH_LEAD_MS`), ranks after the rest.
        a = r.get("audio")
        heard = 0 if a == r["slot"] else 2 if a else 1
        seen = bool(r.get("spend_witness")) or a == r["slot"]
        return (not seen, _eff(r) == "after_player_death", r["to"] >= full_after, heard,
                r["t_ms"])

    def same_cast(t):
        # One cast can read as two drops: a release then the spend, or a
        # spend split across a flash. A candidate this near a cast the gate
        # passed, or an item already taken, in this slot is that cast.
        return (any(abs(g["t_ms"] - t) <= near_ms for g in gated)
                or any(i["t_ms"] is not None and abs(i["t_ms"] - t) <= 2 * near_ms
                       for i in items))

    own = [r for r in rows if not r["player_cast"] and id(r) not in used and solo(r)
           and r.get("kit_read") == s["agent"] and r["reason"] not in ("menu_open", "no_round")]
    unread = [r for r in rows if not r["player_cast"] and id(r) not in used and solo(r)
              and r.get("kit_read") is None and _eff(r) not in NOT_OWN]
    gold = [u for u in s["unwitnessed"] if id(u) not in used
            and u.get("kit_read") in (s["agent"], None) and u.get("eye") in (None, "real")]
    tested = [r for r in rows if r["reason"] is not None or r["player_cast"]]
    falls = [f for f in s.get("state_falls") or []
             if not any(abs(r["t_ms"] - f[1]) <= near_ms for r in tested)]
    held = list(s.get("held_at_death") or [])
    for pool, cls, how in ((own, 3, "own_kit_drop"), (gold, 2, "gold_refused"),
                           (held, 1, "held_at_death"), (falls, 1, "state_fall"),
                           (unread, 3, "unread_kit_drop")):
        key = (spent_first if cls == 3 else
               (lambda r: r[1] if isinstance(r, tuple) else r["t_ms"]))
        for r in sorted(pool, key=key):
            if len(items) >= deficit:
                break
            if cls != 1 and same_cast(r["t_ms"]):
                continue
            if how == "held_at_death":
                items.append({"kind": "missing", "class": 1, "cause": "spectated_kit_after_death",
                              "t_ms": r["t_ms"], "how": how, "evidence": dict(r)})
            elif cls == 1:
                t0, t = r
                if (any(t0 - FALL_SAME_MS <= g["t_ms"] <= t for g in gated)
                        or any(i["t_ms"] is not None and t0 - FALL_SAME_MS <= i["t_ms"] <= t
                               for i in items)):
                    continue
                st = s["tray_state"](t, t0) if s.get("tray_state") else None
                items.append({"kind": "missing", "class": 1,
                              "cause": (st or {}).get("why", "level_fell_without_a_drop"),
                              "t_ms": t, "how": how,
                              "evidence": {"tray": st, "level_read_before_ms": t0}})
            elif cls == 2:
                take(2, _witness_cause(r), r, how)
            else:
                take(3, r["reason"], r, how)
    while len(items) < deficit:
        items.append({"kind": "missing", "class": 7, "cause": "no_drop_no_witness", "t_ms": None,
                      "how": None, "evidence": {}})
    for it in items:
        if it["t_ms"] is None or it["class"] not in (1, 2, 3):
            continue
        hit = [x for x in s.get("excess_casts") or [] if abs(x[1] - it["t_ms"]) <= near_ms]
        if hit:
            it["evidence"]["was_class"], it["class"] = it["class"], 4
            it["cause"] = f"cast_in_{hit[0][0]}"
    surplus = (len(own) + len(gold) + len(held) + len(falls) + len(unread)
               - sum(1 for i in items if i.get("how") in ("own_kit_drop", "gold_refused",
                                                          "held_at_death", "state_fall",
                                                          "unread_kit_drop")))
    for it in items:
        it["evidence"]["slot_candidates_unused"] = surplus
    return items


def _excess_eye(sid, slot, t_ms: float):
    """The `EXCESS_EYE` label of an excess pick within 0.3 s, or None."""
    return next((v for (s2, k, t), v in EXCESS_EYE.items()
                 if s2 == sid and k == slot and abs(1000.0 * t - t_ms) <= 300.0), None)


def _eff(r: dict):
    """The gate's reason for a refused row as the rerun gate judges it: the
    rerun's where a `root` changed it, else the stored gate's."""
    return r["rejudged_reason"] if r.get("root") else r["reason"]


def _eff_kit_end(r: dict):
    return r.get("rejudged_kit_end_ms") if r.get("root") else r.get("kit_end_ms")


def excess_order(s: dict) -> list[dict]:
    """The slot's gated casts, the least trusted first: an X cast with no own
    ult line near it where the session has lines, a gold-only cast that no
    restock numeral witnessed, a cast compared across refused samples, a
    cast whose kit the icons left unread, then the rest; latest first within
    a rank. A numeral restarting over the slot is a spend: by eye
    e37fdeca944f E 426.6 s, which read 0.2 then 50, is Guiding Light's."""
    lines = s.get("lines") or []
    out = []
    for r in (r for r in s["rows"] if r["player_cast"]):
        w = r.get("witness") or {}
        no_line = bool(lines) and not any(t - LINE_BEFORE_MS <= r["t_ms"] <= t + LINE_AFTER_MS
                                          for t in lines)
        rank, why = ((0, "x_cast_without_own_line") if no_line else
                     (1, "gold_persisted_only") if w and w.get("by") == ["persisted"] else
                     (2, "gold_only_cast") if w and "countdown" not in (w.get("by") or []) else
                     (3, "across_gap") if r.get("across_gap") else
                     (4, "kit_unread") if r.get("kit_read") is None else
                     (5, "no_flag"))
        out.append({"rank": rank, "why": why, "t_ms": r["t_ms"], "evidence": _row_evidence(r)})
    return sorted(out, key=lambda x: (x["rank"], -x["t_ms"]))


def _witness_cause(u: dict) -> str:
    w = u.get("witness") or {}
    return f"countdown:{w.get('countdown')}|icon:{w.get('icon')}|gold_run:{w.get('gold_run')}"


def _row_evidence(r: dict) -> dict:
    keep = ("slot", "from", "to", "reason", "by", "spent_halves", "across_gap", "forced",
            "phase", "kit_end_ms", "kit_read", "kit_read_reason", "round_no", "gold_run",
            "audio", "audio_best", "spend_witness", "spend_evidence", "root",
            "rejudged_reason", "rejudged_kit_end_ms")
    ev = {k: r[k] for k in keep if k in r}
    if "witness" in r:
        w = r["witness"]
        ev["witness"] = {k: w.get(k) for k in ("by", "countdown", "icon", "gold_run")}
    return ev


# ---------------------------------------------------------------- evidence

def _round_no(rounds: list[dict], t: float):
    return next((r.get("round_no") for r in rounds if r["t_start_ms"] <= t <= r["t_close_ms"]),
                None)


def collect_session(store, sid: str, riot: dict, cache_dir: Path | None) -> dict:
    """One session's evidence for `attribute_slot`, slot by slot."""
    import numpy as np
    import tray_gold_eval as tge
    from reticle import stalls, tray, tray_icons
    from reticle.ability_timeline import (EMPTY_MAX, FULL_AFTER_MIN, FULL_LEVEL,
                                          player_tray_casts, stored_gate_inputs)
    from reticle.adjudication.tray_kit import candidate_sets, read_sample
    from reticle.adjudication.ult_cast import player_agent
    from reticle.cli import _gold_witness
    from reticle.lineup import load_lineup
    cache, ts, counts, clean, real, segs, icons, reads = tge._pass(store, sid, cache_dir)
    man = store.read_manifest(sid)
    date = man["ingested_at"][:10]
    rounds = store.read_rounds(sid, date).to_pylist()
    lineup = load_lineup(sid, store.root)
    agent = player_agent(lineup, sid)
    gate, _stamps = stored_gate_inputs(store, sid, date, rounds, agent)
    witness, unw = _gold_witness(cache, ts, counts, clean, real, segs, icons, reads)
    drops = tray.drops(ts, counts, clean, segs, icons, witness)
    rows = player_tray_casts(
        drops, gate["phase_of"], rounds, gate["player_deaths_ms"], agent=gate["agent"],
        second_lives_ms=gate["second_lives_ms"], revives_ms=gate["revives_ms"],
        report_deaths=gate["report_deaths"], kit_changes_ms=gate["kit_changes_ms"],
        kit_returns_ms=gate["kit_returns_ms"], menu_at=gate["menu_at"],
        kit_spans=gate["kit_spans"])
    # The gate rerun with the inputs it does not read: each alone names the
    # root of a death refusal it undoes; both together judge the candidate.
    rj = rejudge_inputs(store, sid, date, rounds, agent, gate["player_deaths_ms"])
    variants = {name: _run_gate(drops, gate, rounds, {k: rj[k] for k in keys},
                                rows if "player_deaths_ms" in keys else None,
                                rj["dead_windows_ms"])
                for name, keys in CF_INPUTS.items()}
    at = {name: {(r["slot"], r["t_ms"]): r for r in v} for name, v in variants.items()}

    def changed(alt, r):
        return alt is not None and (alt["reason"], alt.get("kit_end_ms")) != (r["reason"],
                                                                             r.get("kit_end_ms"))
    for r in rows:
        if r["reason"] != "after_player_death":
            continue
        key = (r["slot"], r["t_ms"])
        if not changed(at["both"].get(key), r):
            continue
        r["root"] = "+".join(ROOTS[CF_INPUTS[n][0]] for n in ("second_lives", "teammate_revives")
                             if changed(at[n].get(key), r)) or "both_inputs"
        r["rejudged_reason"] = at["both"][key]["reason"]
        r["rejudged_kit_end_ms"] = at["both"][key].get("kit_end_ms")
    ts_arr = np.asarray(ts, float)
    f = tray.fills(np.asarray(counts, float), np.asarray(clean, bool))
    dr = tray.drawn_mask(f, tray.segment_index(segs), icons)
    ok = np.asarray(clean, bool)

    # The kit the icons show on the two samples before each refused drop and
    # each refused gold drop, read by the kit owner (`tray_kit.read_sample`).
    sets = candidate_sets(lineup, sid)
    refs = tray_icons.load_slot_icons(store.root)
    everyone = sorted(refs)
    # The spend witness at each refused drop: the gold drop's own witness
    # (`tray.gold_witness`), asked of the drop with its earlier sample as the
    # last one the spent charge read on: a restock numeral appearing or
    # restarting over the slot, or its icon lit there and dimming after.
    refused = [r for r in rows if not r["player_cast"]] + unw
    ask, after = {}, {}
    span = 1000.0 * tray.WITNESS_AFTER_S
    for r in refused:
        j = int(np.searchsorted(ts_arr, r["t_ms"]))
        ask[id(r)] = [float(ts_arr[i]) for i in (j - 1, j - 2) if i >= 0 and real[i]]
        after[id(r)] = [float(t) for t in ts_arr[(ts_arr >= r["t_ms"])
                                                 & (ts_arr <= r["t_ms"] + span)]]
    want = sorted({t for v in ask.values() for t in v} | {t for v in after.values() for t in v})
    kit_at = {t for v in ask.values() for t in v}
    kit, bright = {}, {}
    for smp in cache.samples(want, rois=["hud_abilities"]):
        t = float(smp.t_ms)
        bright[t] = [float(v) for v in tray_icons.slot_brightness(smp.frame)]
        if t not in kit_at:
            continue
        i = int(np.searchsorted(ts_arr, t))
        patches = tray_icons.slot_patches(smp.frame)
        kit[t] = read_sample(
            bool(dr[i]), lambda agents: tray_icons.slot_scores(patches, refs, agents), sets,
            everyone)
    for r in refused:
        got = [kit[t] for t in ask[id(r)] if t in kit]
        named = next((g for g in got if g["kit_agent"]), None)
        r["kit_read"] = named["kit_agent"] if named else None
        r["kit_read_reason"] = None if named else (got[0]["reason"] if got else "no_sample")
        tb = ask[id(r)][0] if ask[id(r)] else r["t_ms"]
        icon = {t: bright[t] for t in [tb] + after[id(r)] if t in bright}
        w = tray.gold_witness({"t_ms": r["t_ms"], "slot": r["slot"], "t_before_ms": tb,
                               "t_gold_ms": tb, "gold_run": None}, reads, icon)
        # A spend dims its own icon; a death screen, a dim or a round's
        # reset dims every lit icon at once, which witnesses no spend.
        k = tray.SLOT_KEYS.index(r["slot"])
        lit = [j for j in range(len(tray.SLOT_KEYS)) if j != k and tb in bright
               and bright[tb][j] >= tray.ICON_LIT_MIN]
        dimmed = [j for j in lit if any(bright[t][j] <= tray.ICON_DIM_MAX
                                        for t in after[id(r)] if t in bright)]
        r["spend_witness"] = [b for b in w["by"] if b != "persisted"
                              and not (b == "icon" and dimmed)]
        r["spend_evidence"] = {**{k2: w[k2] for k2 in ("countdown", "icon", "icon_on_gold",
                                                       "icon_least_after")},
                               "other_icons_dimmed": len(dimmed)}
    # The audio witness at each refused drop: the kit ability the audio
    # around it sounds like, by the owner's verdict (`ability_audio`).
    audio_why = _audio_at(store, sid, rows, agent, gate["kit_spans"],
                          [r for r in rows if not r["player_cast"]] + unw)
    for r in rows:
        r["round_no"] = _round_no(rounds, r["t_ms"])
    for u in unw:
        u["round_no"] = _round_no(rounds, u["t_ms"])
        # The eye's label of a refused gold drop, where the gold-persist
        # check gave one (`tray_gold_eval.EYE`): a misread or a switch is no
        # spend.
        u["eye"] = tge.EYE.get(tge.eye_key(sid, u))
    stall = stalls.for_session(store, sid, date)

    def tray_state(t: float, t0: float | None = None, half_ms: float = 2000.0) -> dict:
        """The tray's samples from `t0` (else `t` less `half_ms`) to `t`
        (plus `half_ms` without `t0`): drawn, clean, a stall."""
        a, b = (t0, t) if t0 is not None else (t - half_ms, t + half_ms)
        m = (ts_arr > a) & (ts_arr < b) & np.asarray(real, bool)
        n = int(m.sum())
        stalled = stalls.stalled_at(stall, t)
        st = {"samples": n, "drawn": int(dr[m].sum()), "clean": int((dr & ok)[m].sum()),
              "stalled": bool(stalled)}
        st["why"] = ("stall" if stalled else "no_samples" if n == 0 else
                     "tray_not_drawn" if st["drawn"] * 2 < n else
                     "guard_rows_flooded" if st["clean"] * 2 < st["drawn"] else
                     "read_without_a_fall")
        return st

    lines = sorted(1000.0 * float(r["t_s"]) for r in store.read_events("ult_cast", sid)
                   if r.get("kind") == "cast" and r.get("player_cast"))
    falls, held = defaultdict(list), defaultdict(list)
    from reticle.ability_candidates import CASTS_WHILE_DEAD
    dead_slot, dead_fact = (SPENT_WHILE_DEAD.get(agent, (None, None)) if agent in CASTS_WHILE_DEAD
                            else (None, None))
    for r in store.read_events("ability_state", sid):
        if r.get("kind") != "verdict":
            continue
        if r.get("transition") in STATE_FALLS and r.get("owner_alive_at_t"):
            falls[r["slot"]].append((float((r.get("before") or {}).get("t_ms", r["t_ms"])),
                                     float(r["t_ms"])))
        if r.get("transition") == "owner_death" and r["slot"] == dead_slot:
            n = int((r.get("before") or {}).get("charges") or 0)
            held[r["slot"]] += [{"t_ms": float(r["t_ms"]), "charges": n, "fact": dead_fact}] * n
    ours = Counter(r["slot"] for r in rows if r["player_cast"])
    over = {k for k in tge.SLOTS if ours.get(k, 0) > riot[k]}
    slots = {}
    for k in tge.SLOTS:
        slots[k] = {
            "session": sid, "agent": agent, "slot": k, "riot": int(riot[k]),
            "ours": int(ours.get(k, 0)), "rows": [r for r in rows if r["slot"] == k],
            "all_rows": rows, "unwitnessed": [u for u in unw if u["slot"] == k],
            "lines": lines if k == "X" else [], "state_falls": sorted(falls.get(k, [])),
            "held_at_death": held.get(k, []),
            "excess_casts": [(r["slot"], r["t_ms"]) for r in rows
                             if r["player_cast"] and r["slot"] in over and r["slot"] != k],
            "tray_state": tray_state, "full_level": FULL_LEVEL, "full_after": FULL_AFTER_MIN,
            "empty_max": EMPTY_MAX, "near_ms": 1000.0 * tray.SUSPECT_S,
            "rounds": rounds}
    return {"agent": agent, "slots": slots, "audio": audio_why, "date": date,
            "variants": variants, "rows": rows,
            "gate_inputs": {"second_lives": len(gate["second_lives_ms"]),
                            "revives": len(gate["revives_ms"]),
                            "kit_spans": gate["kit_spans"] is not None,
                            "player_deaths": len(gate["player_deaths_ms"]),
                            "stored_second_lives": len(rj["second_lives_ms"]),
                            "teammate_revives_ms": rj["teammate_revives_ms"],
                            "revived_deaths_ms": rj["revived_deaths_ms"]}}


#: The counterfactual gate runs: each names the gate inputs `rejudge_inputs`
#: replaces.
CF_INPUTS = {"second_lives": ("second_lives_ms",), "teammate_revives": ("player_deaths_ms",),
             "both": ("second_lives_ms", "player_deaths_ms")}
_GATE_KW = ("agent", "second_lives_ms", "revives_ms", "report_deaths", "kit_changes_ms",
            "kit_returns_ms", "menu_at", "kit_spans")


def _run_gate(drops, gate: dict, rounds, over: dict, stored=None, dead=()) -> list[dict]:
    """`player_tray_casts` over the stored gate inputs with `over` replacing
    some of them. Where a revived death is removed (`stored` given), a drop
    from the death's lead (`ability_timeline.DEATH_LEAD_MS`) to the revive
    keeps the stored gate's row: the kit ends at the death and resumes at the
    revive, and the death screen's drops stay refused. The window opens
    `tray.SUSPECT_S` earlier, because the gate marks a passing drop that
    falls beside another (`tray.flag_suspect`), and a death-screen drop the
    removed death let through would taint the cast before it (b7d24102a6f6
    Q 1857.0 s, a Trailblazer spent 1.5 s before the death)."""
    from reticle import tray
    from reticle.ability_timeline import DEATH_LEAD_MS, player_tray_casts
    g = gate | over
    rows = player_tray_casts(drops, g["phase_of"], rounds, g["player_deaths_ms"],
                             **{k: g[k] for k in _GATE_KW})
    if stored is None:
        return rows
    old = {(r["slot"], r["t_ms"]): r for r in stored}
    return [old.get((r["slot"], r["t_ms"]), r)
            if any(d - DEATH_LEAD_MS - 1000.0 * tray.SUSPECT_S <= r["t_ms"] < v for d, v in dead)
            else r for r in rows]


def rejudge_inputs(store, sid: str, date: str, rounds: list[dict], agent,
                   deaths_ms: list[float]) -> dict:
    """The gate inputs the stored gate does not read, from storage:
    `second_lives_ms` from the stored badge rows whatever their version
    (`adjudication.death.stored_second_life` asked at the stored stream's own
    version); `teammate_revives_ms`, the stored `death_verdict` revives on the
    ally side whose victim is the player's agent and that are not the
    player's own revive entry (`kf_player_kill`, which the gate already reads
    for Clove); and `player_deaths_ms`, the stored deaths less each that such
    a revive follows before the player's next death in its round
    (`revived_deaths_ms`), each with its revive (`dead_windows_ms`). The gate
    undoes a death only for Phoenix and Clove, so the counterfactual removes a
    revived death from its input and keeps the stored rows from the death to
    the revive (`_run_gate`). A
    Resurrection returns the ally alive [domain:rounds/resurrection-mechanics]
    and draws an entry naming the revived [domain:killfeed/revive-entries];
    the tray icons then read the player's own kit (`kit_read`).
    Evaluation only: nothing is stored."""
    import math
    from reticle.adjudication.death import stored_second_life
    from reticle.rounds import in_round_window, player_second_life_times
    pr = store.read_events_kind("killfeed_portrait", sid, "second_life_observation")
    badges = stored_second_life(pr, pr[0].get("killfeed_portrait_version")) if pr else None
    revives = sorted(float(r["t_ms"]) for r in store.read_events("death", sid)
                     if r.get("kind") == "death_verdict" and r.get("is_revive")
                     and r.get("side") == "ally" and agent is not None
                     and r.get("victim") == agent and not r.get("kf_player_kill"))
    ends = {r["t_end_ms"] for r in rounds}
    revived = set()
    for r in rounds:
        w = (r["t_start_ms"], r["t_end_ms"], r["t_close_ms"])
        ds = sorted(e["t_first"] for e in in_round_window([{"t_first": t} for t in deaths_ms],
                                                          *w, ends))
        rv = [e["t_first"] for e in in_round_window([{"t_first": t} for t in revives], *w, ends)]
        for t, nxt in zip(ds, ds[1:] + [math.inf]):
            if any(t <= x < nxt for x in rv):
                revived.add(t)
    return {"second_lives_ms": player_second_life_times(store.read_hud(sid, date), badges),
            "player_deaths_ms": [t for t in deaths_ms if t not in revived],
            "teammate_revives_ms": revives, "revived_deaths_ms": sorted(revived),
            "dead_windows_ms": sorted((t, min(x for x in revives if x >= t)) for t in revived)}


def _audio_at(store, sid: str, rows: list[dict], agent, kit_spans, ask: list[dict]):
    """Set `audio` on each row of `ask`: the slot the audio witness names at
    its frame (`ability_audio.cast_verdicts` under the agent's stored
    parameters), or None; returns why no row was scored, or None."""
    from reticle.ability_timeline import audio_cast_witness
    from reticle.adjudication.ability_audio import FPS, cast_verdicts, load_params
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    for r in ask:
        r["audio"] = None
    if agent is None:
        return "no_player_agent"
    params, why = load_params(store.root, ABILITY_AUDIO_PARAMS_VERSION, agent)
    if params is None:
        return why
    aw = audio_cast_witness(store.root, sid, rows, agent, kit_spans, params=params)
    if "tracks" not in aw:
        return aw["coverage"].get("reason")
    n = len(aw["session"]["X"])
    keep = [r for r in ask if 0 <= int(r["t_ms"] / 1000.0 * FPS) < n]
    if not keep:
        return None
    got = cast_verdicts(aw["tracks"], [int(r["t_ms"] / 1000.0 * FPS) for r in keep],
                        aw["session"]["neighbours"], params)
    for r, v in zip(keep, got):
        r["audio"] = v.get("verdict")
        r["audio_best"] = v.get("best_ref")
    return None


def counterfactuals(sid: str, riot: dict, ev: dict) -> dict:
    """Fixes measured against Riot's counts, per session, each as the gate's
    casts per slot scored by `tray_gold_eval.score_slots`: `second_lives`,
    `teammate_revives` and `both` rerun the gate with the inputs
    `rejudge_inputs` supplies; `witnessed_cooccur` passes a drop the
    co-occurrence test refused under the player's own kit where a restock
    numeral appeared or restarted over its slot or the audio named its slot.
    Each is {"slots": score_slots's result, "changes": the slots whose count
    moved, as {session, agent, slot, riot, ours, then}}; evaluation only,
    nothing stored."""
    import tray_gold_eval as tge
    base = Counter(r["slot"] for r in ev["rows"] if r["player_cast"])
    runs = {name: Counter(r["slot"] for r in rows if r["player_cast"])
            for name, rows in ev["variants"].items()}
    ours = Counter(base)
    for r in ev["rows"]:
        if (r["reason"] == "cooccur_among_casts" and r.get("kit_read") == ev["agent"]
                and ("countdown" in (r.get("spend_witness") or [])
                     or r.get("audio") == r["slot"])):
            ours[r["slot"]] += 1
    runs["witnessed_cooccur"] = ours
    return {name: {"slots": tge.score_slots(got, riot),
                   "changes": [{"session": sid, "agent": ev["agent"], "slot": k,
                                "riot": int(riot[k]), "ours": base.get(k, 0),
                                "then": got.get(k, 0)}
                               for k in riot if got.get(k, 0) != base.get(k, 0)]}
            for name, got in runs.items()}


# ---------------------------------------------------------------- summary

def summarise(items: list[dict]) -> dict:
    """Counts per class, per (class, agent ability), and the gate reasons."""
    miss = [i for i in items if i["kind"] == "missing"]
    extra = [i for i in items if i["kind"] == "extra"]
    gate = [i for i in miss if i["class"] == 3]
    by_line = [i for i in gate if i.get("how") == "ult_line"]
    rest = [i for i in gate if i.get("how") != "ult_line"]
    by_ability, roots = defaultdict(Counter), defaultdict(Counter)
    for i in items:
        by_ability[i["class"]][f"{i['agent']}:{i['slot']}"] += 1
    for i in gate:
        roots[_root(i)][f"{i['agent']}:{i['slot']}"] += 1
    return {"missing": len(miss), "extra": len(extra),
            "by_class": dict(sorted(Counter(i["class"] for i in items).items())),
            "by_class_ability": {c: dict(v.most_common()) for c, v in sorted(by_ability.items())},
            "gate_reasons": dict(Counter(i["cause"] for i in miss if i["class"] == 3)
                                 .most_common()),
            "class1_why": dict(Counter(i["cause"] for i in miss if i["class"] == 1)),
            "how": dict(Counter(i.get("how") for i in miss)),
            # A class 3 item placed by an own ult line, seen by a spend
            # witness or the audio, or neither; of the last, those whose slot
            # held more candidates than casts missing are a ranking's pick.
            "class3_by_line": len(by_line),
            "class3_witnessed": sum(1 for i in rest if _seen(i)),
            "class3_unwitnessed": sum(1 for i in rest if not _seen(i)),
            "class3_unwitnessed_with_spare_candidates": sum(
                1 for i in rest if not _seen(i)
                and (i.get("evidence") or {}).get("slot_candidates_unused")),
            # The class 3 casts by the gate input the stored gate did not
            # read (`root`), each with the rerun gate's reason for its drop.
            "class3_roots": dict(Counter(_root(i) for i in gate).most_common()),
            "class3_root_ability": {r: dict(v.most_common()) for r, v in sorted(roots.items())},
            "class3_rejudged": dict(Counter(_rejudged(i) for i in gate
                                            if _root(i) != "none").most_common()),
            "class3_rejudged_ability": dict(Counter(
                f"{_rejudged(i)}|{i['agent']}:{i['slot']}" for i in gate
                if _root(i) != "none").most_common()),
            "class3_cause_ability": dict(Counter(
                f"{i['cause']}|{i['agent']}:{i['slot']}" for i in gate).most_common()),
            "class6_eye": dict(Counter(str((i.get("evidence") or {}).get("eye"))
                                       for i in extra).most_common()),
            "extra_unplaced": sum(1 for i in extra if i.get("unplaced"))}


def _rejudged(item: dict) -> str:
    return f"{_root(item)}->{(item.get('evidence') or {}).get('rejudged_reason')}"


def _root(item: dict) -> str:
    return (item.get("evidence") or {}).get("root") or "none"


def _seen(item: dict) -> bool:
    ev = item.get("evidence") or {}
    return bool(ev.get("spend_witness")) or ev.get("audio") == item.get("slot")


def view(cache, items: list[dict], out: Path, sid: str) -> list[str]:
    """Write, per item with a time, the tray strip at native size on seven
    samples from 1.5 s before to 1.5 s after it, stacked, each labelled."""
    import cv2
    import numpy as np
    out.mkdir(parents=True, exist_ok=True)
    grid = np.asarray(cache.t_ms, float)
    paths = []
    for i, it in enumerate(items):
        if it["t_ms"] is None:
            continue
        want = [float(grid[np.abs(grid - (it["t_ms"] + d)).argmin()])
                for d in (-1500, -1000, -500, 0, 500, 1000, 1500)]
        strips = []
        for smp in cache.samples(sorted(set(want)), rois=["hud_abilities"]):
            s = smp.frame[975:1060, 730:1190].copy()
            cv2.putText(s, f"{smp.t_ms / 1000:.2f}", (2, 12), cv2.FONT_HERSHEY_PLAIN, 0.9,
                        (0, 255, 255), 1)
            strips.append(s)
        if not strips:
            continue
        p = out / f"{sid}_{it['slot']}_{int(it['t_ms'])}_c{it['class']}_{i}.png"
        cv2.imwrite(str(p), np.vstack(strips))
        paths.append(str(p))
    return paths


def _token_key(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)


def record_residuals(summ: dict, sessions: list[str], scored: dict) -> dict:
    """One metrics row, series own_cast/residuals@riot-21."""
    from reticle import metrics
    from reticle.version import PLAYER_CAST_VERSION, TRAY_KIT_VERSION, TRAY_VERSION
    values = {**scored, "missing": summ["missing"], "extra": summ["extra"],
              "extra_unplaced": summ["extra_unplaced"],
              **{f"cf_{name}_{k}": n for name, got in summ["counterfactual"].items()
                 for k, n in got.items()},
              **{f"cf_{c['cf']}_{c['session']}_{c['slot']}_{k}": c[k]
                 for c in summ["cf_changes"] for k in ("covered_gain", "beyond_gain")},
              **{f"class3_root_{_token_key(k)}": n for k, n in summ["class3_roots"].items()},
              **{f"class3_root_{_token_key(r)}_{_token_key(a)}": n
                 for r, per in summ["class3_root_ability"].items() for a, n in per.items()},
              **{f"class3_rejudged_{_token_key(k)}": n
                 for k, n in summ["class3_rejudged"].items()},
              **{f"class3_rejudged_{_token_key(k)}": n
                 for k, n in summ["class3_rejudged_ability"].items()},
              **{f"class3_gate_{_token_key(k)}": n
                 for k, n in summ["class3_cause_ability"].items()},
              **{f"class6_eye_{_token_key(k)}": n for k, n in summ["class6_eye"].items()},
              **{k: summ[k] for k in ("class3_by_line", "class3_witnessed", "class3_unwitnessed",
                                      "class3_unwitnessed_with_spare_candidates")},
              **{f"class{c}": n for c, n in summ["by_class"].items()},
              **{f"gate_{_token_key(k)}": n for k, n in summ["gate_reasons"].items()},
              **{f"class1_{_token_key(k)}": n for k, n in summ["class1_why"].items()},
              **{f"how_{_token_key(str(k))}": n for k, n in summ["how"].items()},
              **{f"class{c}_{_token_key(a)}": n
                 for c, per in summ["by_class_ability"].items() for a, n in per.items()}}
    import tray_gold_eval as tge
    return metrics.record(
        "own_cast", part="residuals", session="riot-21", values=values,
        deps={"tray_version": TRAY_VERSION, "player_cast_version": PLAYER_CAST_VERSION,
              "tray_kit_version": TRAY_KIT_VERSION,
              "own_cast_residuals_version": OWN_CAST_RESIDUALS_VERSION},
        context={"sessions": sessions, "script": "prototypes/own_cast_residuals.py --record",
                 "inputs": "minimap crop cache through reticle tray's pass at the wired "
                           f"GOLD_PERSIST_MIN; stored gate inputs, ult_cast and ability_state; "
                           "slot icons read by tray_kit.read_sample; the gate rerun with the "
                           "stored second lives at any killfeed_portrait version and the "
                           "stored teammate revives of the player (rejudge_inputs); no decode",
                 "truth": "Riot match records stats.abilityCasts (own subject), per match, "
                          "evaluation only",
                 "slots": list(tge.SLOTS)},
        log_path=tge.STORE / "notes" / "metrics.jsonl")


def main(argv=None) -> int:
    import tray_gold_eval as tge
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="*", default=list(tge.SESSIONS))
    ap.add_argument("--cache", type=Path, help="keep each session's tray pass here")
    ap.add_argument("--json", type=Path, help="write every item here")
    ap.add_argument("--view", type=Path, help="write each timed item's tray strip here")
    ap.add_argument("--record", action="store_true", help="append the metrics row")
    args = ap.parse_args(argv)
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                0x4000)
    except (AttributeError, OSError):
        pass
    from reticle.store import Store
    store = Store(tge.STORE)
    truth = tge.riot_casts()
    items, gates, base, cf, changes = [], {}, [], defaultdict(list), []
    for sid in args.sessions:
        t0 = time.perf_counter()
        riot = truth[sid]["casts"]
        ev = collect_session(store, sid, riot, args.cache)
        gates[sid] = ev["gate_inputs"]
        base.append(tge.score_slots({k: s["ours"] for k, s in ev["slots"].items()}, riot))
        for name, got in counterfactuals(sid, riot, ev).items():
            cf[name].append(got["slots"])
            for c in got["changes"]:
                was, now = tge.score_slots({c["slot"]: c["ours"]}, {c["slot"]: c["riot"]}),                     tge.score_slots({c["slot"]: c["then"]}, {c["slot"]: c["riot"]})
                changes.append(c | {"cf": name, "covered_gain": now[c["slot"]]["covered"]
                                    - was[c["slot"]]["covered"],
                                    "beyond_gain": now[c["slot"]]["beyond"]
                                    - was[c["slot"]]["beyond"]})
        mine = []
        for k, s in ev["slots"].items():
            for it in attribute_slot(s, s["near_ms"], s["full_level"],
                                     full_after=s["full_after"], empty_max=s["empty_max"]):
                it.update(session=sid, agent=ev["agent"], slot=k,
                          round_no=None if it["t_ms"] is None else _round_no(s["rounds"],
                                                                             it["t_ms"]))
                mine.append(it)
        items += mine
        print(sid, ev["agent"], " ".join(f"{k}:{s['ours']}/{s['riot']}" for k, s in
                                         ev["slots"].items()),
              dict(Counter(i["class"] for i in mine)), f"{time.perf_counter() - t0:.0f}s",
              flush=True)
        if args.view and mine:
            from reticle.profiles import get_profile
            from reticle.roi_cache import RoiCache
            man = store.read_manifest(sid)
            cache, _why = RoiCache.load(store.root, man, get_profile(man["source_profile"]),
                                        "minimap")
            view(cache, mine, args.view, sid)
    summ = summarise(items)
    tot = tge.total(base)
    scored = {"riot_casts": tot["riot"], "covered": tot["covered"], "beyond": tot["beyond"]}
    summ["scored"] = scored
    summ["counterfactual"] = {k: {n: v for n, v in tge.total(got).items() if n != "riot"}
                              for k, got in cf.items()}
    summ["counterfactual"]["second_lives"]["second_lives"] = sum(
        g["stored_second_lives"] for g in gates.values())
    summ["counterfactual"]["teammate_revives"]["revived_deaths"] = sum(
        len(g["revived_deaths_ms"]) for g in gates.values())
    summ["cf_changes"] = changes
    print(json.dumps(summ, indent=1))
    if args.json:
        args.json.write_text(json.dumps({"summary": summ, "gate_inputs": gates,
                                         "items": items}, indent=1, default=str))
    if args.record:
        if sorted(args.sessions) != sorted(tge.SESSIONS):
            raise SystemExit("--record scores the riot-21 set only")
        row = record_residuals(summ, list(tge.SESSIONS), dict(scored))
        print("recorded", json.dumps(row["values"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
