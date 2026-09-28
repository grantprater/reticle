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
`DEATH_LEAD_MS`). The agent is the identity arbiter's verdict on the player's
slot as the lineup stores it (`adjudication.ult_cast.player_agent`), carried
with its provenance and never decided here; the slots' abilities are
`lineup.abilities_for`'s.

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

**Charges** come from the level and the slot's `max_charges`, read from the
`*-charges` facts of `domain/abilities.toml` (`charge_facts`): a two-charge
slot reads 1.0, 0.5 and 0 [domain:hud/ability-tray-charge-segments]. Every
rule is per ability [domain:abilities/ability-rules-are-unique], so a slot
with no fact stores `charges` null with the reason
`no-fact:<agent>:<slot>:max_charges` and only the range the reading bounds:
at least one where the bar is full, none where it is empty, and anything up
to `MAX_CHARGES_ANY` where it reads half, since a half bar on a slot of
unknown kind need not be one charge of two. An unreadable slot keeps the
range `[0, max]`, never a guess. A regain of charges, within a round or
between rounds, is recorded where the tray shows it and never inferred.

**Rows**, stored whole as `events/ability_state/<sid>.jsonl`:

* one `coverage` row: every input's stamp, the agent's provenance, the kit and
  its parameters with the facts they came from, counts, the unreadable
  reasons, the reproduction checks, and the invariant counts
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
  state, with `charges`, `charges_range`, `level`, the fills, `mode`
  (idle, equipped, active, unreadable), `castable`, `pips`, `owner_alive`,
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
from ..ability_timeline import (CAST_PHASES, DEATH_LEAD_MS, FULL_AFTER_MIN,
                                FULL_MIN, ULT_SLOT, round_window_of)
from ..version import ABILITY_STATE_VERSION
from .identity import AGENT_IDENTITY_VERSION

SLOTS = tray.SLOT_KEYS
#: The phases whose tray is the player's kit: the gate's cast phases and the
#: buy phase, when charges are bought. After the round the tray dims
#: [domain:hud/tray-after-player-death].
READABLE_PHASES = ("buy_phase",) + tuple(CAST_PHASES)
#: The reasons a sample is unreadable, in the order they are tested.
UNREADABLE_REASONS = ("no_round", "kit_frozen:after_player_death", "phase",
                      "tray_not_drawn", "guard_rows_flooded")
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
#: 1.1-1.2; the stored releases start at or above it
#: ([metric:ability_state/step1@all-sessions#release_from_at_equip_min=120] of
#: [metric:ability_state/step1@all-sessions#release_drops=121]).
EQUIP_MIN = 1.2
#: No ability has more than two charges [domain:hud/ability-tray-charge-segments].
MAX_CHARGES_ANY = 2
#: The level each charge count draws, per max_charges; the inverse is `charges_of`.
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3}
_CHARGE_CLAUSE = re.compile(r"\b(one|two|three)\s+([^.,;]*?)\s+in slot ([CQEX])\b", re.I)
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*seconds?\b")

#: What each of the gate's reasons stood for in the state, and the transition
#: its drop becomes. `phase:<name>` is looked up by its prefix.
STOOD_FOR = {
    None: ("cast", "a charge spent: the slot held one (the ult: the bar was lit), "
                   "its owner alive, in a live phase"),
    "no_round": ("none", "unreadable: outside every round"),
    "after_player_death": ("none", "kit frozen: the tray shows no kit of the player's"),
    "phase:buy_phase": ("unresolved", "the buy phase: a fall the gate does not read as a cast"),
    "phase": ("none", "unreadable: a phase whose tray is not the player's kit"),
    "forced": ("none", "unreadable: the tray is not drawn on the drop's sample"),
    "cooccur_among_casts": ("unresolved", "several slots fell together: a spectator "
                                          "switch, a flash or a dim, or casts beside one another"),
    "partial_charge": ("none", "the ult bar was not full before the fall: no cast"),
    "pips_lit": ("none", "the ult stayed castable: the bar did not empty"),
    "equip_release": ("unequip", "an equipped ability released: nothing spent"),
}


def _agent_key(name: str | None) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def charge_facts(facts: dict) -> dict:
    """{(agent key, slot): {"max_charges", "fact", "clause"}} from every fact
    in `domain/abilities.toml` whose id ends in `-charges`. The agent is the
    fact's subject before the colon; each "<count> <words> in slot <K>" clause
    of its claim gives one slot. Two facts that disagree on a slot leave it
    with `max_charges` None and the reason `conflicting-facts`."""
    out: dict = {}
    for key, f in sorted(facts.items()):
        if f.domain != "abilities" or not f.id.endswith("-charges") or ":" not in f.subject:
            continue
        agent = _agent_key(f.subject.split(":")[0])
        for word, words, slot in _CHARGE_CLAUSE.findall(" ".join(f.claim.split())):
            n = _COUNT_WORDS[word.lower()]
            got = out.get((agent, slot.upper()))
            if got and got["max_charges"] not in (None, n):
                out[(agent, slot.upper())] = {"max_charges": None, "fact": None,
                                              "clause": None,
                                              "reason": f"conflicting-facts:{got['fact']}:{key}"}
            elif not got:
                out[(agent, slot.upper())] = {"max_charges": n, "fact": key,
                                              "clause": f"{word} {words} in slot {slot}",
                                              "reason": None}
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
            out[(_agent_key(who), _agent_key(what))] = {
                "duration_ms": float(m.group(1)) * 1000.0, "fact": key,
                "about": "about" in claim[:m.start()].lower()}
    return out


def slot_parameters(agent: str | None, kit: dict, facts: dict) -> dict:
    """Per slot: the ability, `max_charges` with the fact it came from or the
    reason it is unread, and a duration with its fact where one exists."""
    charges, durations = charge_facts(facts), duration_facts(facts)
    a = _agent_key(agent)
    out = {}
    for slot in SLOTS:
        ability = kit.get(slot)
        row = {"ability": ability, "max_charges": None, "max_charges_fact": None,
               "max_charges_reason": None, "duration_ms": None, "duration_about": None,
               "duration_fact": None,
               "duration_reason": None}
        if agent is None:
            row["max_charges_reason"] = row["duration_reason"] = "no_player_agent"
            out[slot] = row
            continue
        if slot == ULT_SLOT:
            row["max_charges_reason"] = "ult_slot:read_as_castable"
        else:
            got = charges.get((a, slot))
            if got is None:
                row["max_charges_reason"] = f"no-fact:{a}:{slot}:max_charges"
            elif got["reason"]:
                row["max_charges_reason"] = got["reason"]
            elif ability and _agent_key(ability) not in _agent_key(got["clause"]):
                row["max_charges_reason"] = f"fact-names-another-ability:{got['fact']}"
            else:
                row["max_charges"], row["max_charges_fact"] = got["max_charges"], got["fact"]
        d = durations.get((a, _agent_key(ability)))
        if d:
            row["duration_ms"], row["duration_fact"] = d["duration_ms"], d["fact"]
            row["duration_about"] = d["about"]
        else:
            row["duration_reason"] = f"no-fact:{a}:{slot}:duration"
        out[slot] = row
    return out


def charges_of(level: float | None, max_charges: int | None, reason: str | None):
    """(charges or None, the reason it is None, [lo, hi]) for a C, Q or E
    level; see the module docstring for the range of a slot with no fact."""
    if level is None:
        return None, "unread_level", [0, max_charges or MAX_CHARGES_ANY]
    if max_charges is None:
        rng = {1.0: [1, MAX_CHARGES_ANY], 0.5: [0, MAX_CHARGES_ANY], 0.0: [0, 0]}[level]
        return (0 if level == 0.0 else None), (None if level == 0.0 else reason), rng
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
    from .ult_cast import player_agent
    name = player_agent(lineup, session_id)
    slot = ((lineup or {}).get("player") or {}).get("slot")
    eid = f"{session_id}:ally:slot:{slot}" if slot is not None else None
    v = next((v for v in (lineup or {}).get("agent_identity") or []
              if v.get("entity_id") == eid), None) if eid else None
    return {"agent": name, "entity_id": eid,
            "status": v.get("status") if v else None,
            "reason": (v.get("reason") if v else
                       "no_lineup" if not lineup else "no_player_slot_verdict"),
            "channels": v.get("channels") if v else None,
            "independent_channels": v.get("independent_channels") if v else None,
            "adjudication_version": v.get("adjudication_version") if v else None,
            "arbiter_current": bool(v) and v.get("adjudication_version") == AGENT_IDENTITY_VERSION,
            "lineup_version": (lineup or {}).get("version"),
            "board_state": (lineup or {}).get("board_state")}


def _context(ts, drawn, clean, kits, phase_of) -> list[dict]:
    """Per sample: its round, the owner's state and why it is unreadable."""
    out = []
    for t, dr, ok in zip(ts, drawn, clean):
        k = round_window_of(t, kits)
        end = k["kit_end_ms"] if k else None
        frozen = end is not None and t >= end - DEATH_LEAD_MS
        phase = phase_of(t)
        undone = [u for u in (k["undone_deaths"] if k else []) if u[0] <= t]
        why = ("no_round" if k is None
               else "kit_frozen:after_player_death" if frozen
               else f"phase:{phase}" if phase not in READABLE_PHASES
               else "tray_not_drawn" if not dr
               else "guard_rows_flooded" if not ok else None)
        out.append({"t": float(t), "round": k["round_no"] if k else None,
                    "phase": phase, "unreadable": why,
                    "owner_alive": None if k is None else not frozen,
                    "owner_life": (None if k is None else "dead" if frozen
                                   else f"after_undone_death:{undone[-1][1]}" if undone
                                   else "first")})
    return out


def _reading(slot: str, f: float) -> dict:
    """What one readable sample says of one slot, before charges are held."""
    f = float(f)
    if slot == ULT_SLOT:
        lit = f >= X_LIT_MIN
        return {"level": 1.0 if lit else 0.0, "equipped": lit and f >= EQUIP_MIN,
                "castable": lit}
    if f >= EQUIP_MIN:
        return {"level": None, "equipped": True, "castable": None}
    return {"level": 1.0 if f >= LEVEL_FULL_MIN else 0.5 if f > HALF_MIN else 0.0,
            "equipped": False, "castable": None}


def _state(slot, par, ctx, f, held, active_until) -> dict:
    """The state of one slot at one sample. `held` is the slot's last
    unequipped reading in the round, which an equip keeps."""
    base = {"owner_alive": ctx["owner_alive"], "owner_life": ctx["owner_life"],
            "round": ctx["round"], "phase": ctx["phase"]}
    cap = par["max_charges"] or MAX_CHARGES_ANY
    ult = slot == ULT_SLOT
    pips = {"pips": None, "pips_reason": ("not_read:the_tray_reads_teal_not_pips" if ult
                                          else "not_an_ult_slot")}
    if ctx["unreadable"]:
        return {**base, **pips, "readable": [], "unreadable_reason": ctx["unreadable"],
                "level": None, "level_reason": ctx["unreadable"], "held_level": None,
                "fill": None, "charges": None,
                "charges_reason": par["max_charges_reason"] if ult else ctx["unreadable"],
                "charges_range": None if ult else [0, cap],
                "mode": "unreadable", "castable": None,
                "castable_reason": ctx["unreadable"] if ult else "not_an_ult_slot",
                "equipped": None, "until_ms": None, "until_reason": ctx["unreadable"]}
    r = _reading(slot, f)
    held_level = None
    if ult:
        charges, why, rng = None, par["max_charges_reason"], None
    elif r["equipped"]:
        if held is None:
            charges, why, rng = None, "equipped_before_a_reading_this_round", [0, cap]
        else:
            charges, why, rng = held["charges"], held["charges_reason"], list(held["charges_range"])
            held_level = held["level"]
    else:
        charges, why, rng = charges_of(r["level"], par["max_charges"], par["max_charges_reason"])
    active = active_until is not None and ctx["t"] <= active_until
    mode = "equipped" if r["equipped"] else "active" if active else "idle"
    return {**base, **pips, "readable": ["tray"], "unreadable_reason": None,
            "level": r["level"],
            "level_reason": "equipped:teal_over_the_bar" if r["level"] is None else None,
            "held_level": held_level, "fill": round(float(f), 3), "charges": charges,
            "charges_reason": why, "charges_range": rng, "mode": mode,
            "castable": r["castable"], "castable_reason": None if ult else "not_an_ult_slot",
            "equipped": r["equipped"],
            "until_ms": active_until if active else None,
            "until_reason": None if active else (par["duration_reason"] or "not_active")}


#: The fields of a state that make it the same state; a record is a run of them.
_KEY = ("round", "phase", "readable", "unreadable_reason", "level", "held_level", "charges",
        "charges_reason", "charges_range", "mode", "castable", "equipped", "owner_alive",
        "owner_life", "until_ms")
#: The state fields a verdict's before and after carry.
_SNAP = ("level", "held_level", "fill", "charges", "charges_range", "mode", "castable",
         "equipped", "owner_alive", "readable", "unreadable_reason")


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


def _fill_change(slot: str, sp: dict, sj: dict, phase: str):
    """(transition, surprise or None) for a change between two consecutive
    readable samples of one round that no drop covers, or None."""
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
    if lj > lp:
        return ("buy" if phase == "buy_phase" else "recharge"), None
    return "fall_without_a_drop", "level_fell_without_a_drop"


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
               inputs: dict, checks: dict | None = None) -> list[dict]:
    """The session's coverage, claim, verdict and state rows.

    `drops` are the stored `tray_drop` drop rows and `gate_rows` the gate's
    verdicts on them (`player_tray_casts`), in the same order; `kits` are
    `ability_timeline.kit_windows`; `samples` holds the tray's real samples
    (no separator rows): `t_ms`, `fills` (n x 4), `drawn` and `clean`;
    `agent` is `player_agent_verdict`; `params` is `slot_parameters`;
    `inputs` are the input stamps; `checks` are the reproduction checks the
    caller measured. Deterministic in its inputs."""
    ts = [float(t) for t in samples["t_ms"]]
    fills = np.asarray(samples["fills"], float).reshape(len(ts), len(SLOTS))
    ctx = _context(ts, samples["drawn"], samples["clean"], kits, phase_of)
    at = {t: i for i, t in enumerate(ts)}
    common = {"session_id": session_id, "ability_state_version": ABILITY_STATE_VERSION}
    death_src = {k: inputs.get(k) for k in ("hud", "death", "killfeed_portrait",
                                            "combat_report_round", "round")}
    claims, verdicts, records = [], [], []

    def claim(slot, t, witness, observed, since, evidence, version, depends_on=()):
        cid = f"{session_id}:{slot}:{t:.0f}:{witness}"
        claims.append({**common, "kind": "claim", "claim_id": cid, "slot": slot,
                       "witness": witness, "observed": observed, "observed_at_ms": float(t),
                       "interval_ms": [float(since), float(t)], "source_version": version,
                       "evidence": evidence, "depends_on": sorted(depends_on)})
        return cid

    def ctx_at(t):
        return ctx[at[t]] if t in at else _context([t], [True], [True], kits, phase_of)[0]

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
            s = _state(slot, par, c, fills[i, k], held, active_until)
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
            if transition in ("cast", "unequip") and sb is not None and sa is not None:
                fell = _fell(slot, sb, sa)
                (agreed if fell == (transition == "cast") else disagreed).append("tray_fill")
            dur = transition == "cast" and par["duration_ms"]
            verdicts.append(_verdict(
                common, slot, t, transition, reason=why, stood_for=stood, claims=[c1, c2],
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
                change, stood = _fill_change(slot, sp, sj, ctx[j]["phase"]), None
            if change is None:
                continue
            transition, surprise = change
            cid = claim(slot, t, "tray_fill", transition, ts[p],
                        {"stream": "hud_abilities crops", "t_before_ms": ts[p],
                         "fill_before": sp["fill"], "fill_after": sj["fill"],
                         "round_before": sp["round"], "round_after": sj["round"]},
                        inputs.get("tray_fill"))
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
            if kw["kit_end_ms"] is None:
                continue
            end = float(kw["kit_end_ms"])
            frozen = end - DEATH_LEAD_MS
            cid = claim(slot, end, "kit_end", "owner_death", frozen,
                        {"stream": "death", "kit_end_ms": end, "frozen_from_ms": frozen,
                         "round": rnd}, death_src)
            verdicts.append(_verdict(
                common, slot, end, "owner_death", stood_for="the kit freezes until the round ends",
                claims=[cid], agreed=["kit_end"], before=_snap(states, before(frozen, rnd), ts),
                owner_alive=False))

        records += _records(slot, par, states, ts, agent, common)

    claims.sort(key=lambda r: (r["observed_at_ms"], SLOTS.index(r["slot"]), r["claim_id"]))
    verdicts.sort(key=lambda r: (r["t_ms"], SLOTS.index(r["slot"]), r["transition"]))
    records.sort(key=lambda r: (r["t_first_ms"], SLOTS.index(r["slot"])))
    rows = claims + verdicts + records
    return [_coverage(rows, ctx, params, agent, inputs, checks or {}, common, len(drops))] + rows


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
                    "held_level": s["held_level"],
                    "fills": ({"min": min(got), "median": round(float(np.median(got)), 3),
                               "max": max(got)} if got else None),
                    "charges": s["charges"], "charges_reason": s["charges_reason"],
                    "charges_range": s["charges_range"], "max_charges": par["max_charges"],
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
    unread, by_phase = Counter(), Counter()
    for r in states:
        why = r["unreadable_reason"]
        if why:
            unread["phase" if why.startswith("phase:") else why] += r["samples"]
            if why.startswith("phase:"):
                by_phase[why] += r["samples"]
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
    cov["invariants"] = invariant_violations(rows)
    return cov


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
    changes = ("cast", "equip", "unequip", "recharge", "buy", "ult_ready",
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
    """The player's tray-cast labels (`labels/tray_object`) against one
    session's rows: each label is a cast the player saw; its key is
    `<sid>:<round(t_ms)>:<slot>`. Returns, per label, the transition its drop
    became, and for the drops the gate accepts, whether the state before
    held a charge (C, Q, E: `charges_range[0] >= 1`) or a lit bar (X)."""
    by_key = {f"{v['session_id']}:{round(v['t_ms'])}:{v['slot']}": v
              for v in rows if v.get("kind") == "verdict" and "tray_drop" in v["agreed"]}
    out = []
    for lab in labels:
        v = by_key.get(lab["key"])
        if v is None:
            out.append({"key": lab["key"], "transition": None, "reason": "no_drop_verdict"})
            continue
        b = v["before"]
        held = (None if v["transition"] != "cast" or b is None
                else bool(b["castable"]) if v["slot"] == ULT_SLOT
                else b["charges_range"][0] >= 1)
        out.append({"key": lab["key"], "slot": v["slot"], "agent": lab.get("agent"),
                    "transition": v["transition"], "reason": v["reason"],
                    "held_before": held,
                    "before_level": None if b is None else b["level"],
                    "before_held_level": None if b is None else b["held_level"],
                    "before_charges_range": None if b is None else b["charges_range"],
                    "before_fill": None if b is None else b["fill"],
                    "surprise_reason": v["surprise_reason"]})
    return {"labels": out}
