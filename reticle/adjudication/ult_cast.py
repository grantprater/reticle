r"""Which ultimate was cast, by which side, when: from stored voice-line peaks.

    .\.venv\Scripts\python.exe -m reticle ult-cast <session> | --all [--record]

Owns [owns:ult-cast].

Reads storage only: the `ult_line` peaks `ult_lines` stored, the lineup with
its board override (`lineup.load_lineup`), the rounds table, and the tray's
`tray_drop` rows with the HUD table that dates the player's deaths and the game
phase. It decodes nothing, so a change here reruns in seconds.

**Selection.** A peak is selected when its score reaches THRESHOLD, 0.0443,
formulation F-B's operating point in `prototypes/voice_lines.py`
[metric:voice_lines/evaluate-F-B@all-matches#tau_op=0.0443]: the score at which
lineup-impossible detections fall to a tenth per live minute
[metric:voice_lines/evaluate-F-B@all-matches#impossible_per_min=0.099], where
the player's own ultimates are found at
[metric:voice_lines/evaluate-F-B@all-matches#own_recall=0.667]. It was chosen
on the same 19 match sessions it is scored on, so those two numbers are fitted
values. Held out, it stands: picked on either alternate half, the point is
[metric:voice_lines/heldout-0.1.0@all-matches#tau_a=0.044322] or
[metric:voice_lines/heldout-0.1.0@all-matches#tau_b=0.044166], and the other
half's impossible rate is
[metric:voice_lines/heldout-0.1.0@all-matches#heldout_impossible_per_min_a=0.0976]
or [metric:voice_lines/heldout-0.1.0@all-matches#heldout_impossible_per_min_b=0.1101]
per live minute (`docs/VOICE_LINES.md`, "Held-out threshold"). Every peak above
it stays: two templates that peak at one onset are two selections
(`docs/VOICE_LINES.md`, "Verdicts at 0.2.0"). The threshold was set on the
wiki templates of ult-line-0.1.0; the game's own lines that replace them at
ult-line-0.2.0 are the same recordings for 57 of 58 templates (GCC-PHAT at
least 0.96 clip against clip, `prototypes/vo_ref_eval.py`), Harbor's ally
line being the exception.

**Classing** (`template_class`), against the lineup's identity verdicts:

* `own` -- the ally line of the player's agent; the caster hears their own ally
  line [domain:abilities/caster-hears-own-ult-line].
* `possible` -- the agent is named on the side the variant implies. The ally
  line is heard by the caster's team and the enemy line by the other
  [domain:abilities/ult-lines-heard-by-both-teams], so the variant is the
  caster's side relative to the player.
* `impossible` -- an ally line whose agent is neither named on the ally side
  nor the best guess or rival of an unresolved ally slot; an enemy line whose
  agent the fully named enemy side lacks. It is stored as a `refusal` row with
  its reason, and its claim abstains.
* `unknown` -- everything else, and every peak but the player's of a session
  without a lineup. A session without a lineup has no player either, so all of
  its peaks are `unknown`; the prototype read a demo's player from its tags.

**Names.** Each selected peak is one entity, `<sid>:ult_cast:<t_ms>:<template>`,
and publishes one claim through `adjudication.identity` on channel `ult_line`:
the template's agent (none for an impossible peak), with the score as evidence
and `depends_on` the lineup's slot verdicts of the variant's side, because the
class rests on them. A cast row's `agent` is the arbiter's verdict and nothing
else. The formal identity events go to their own stream, since a stream of
formal events holds nothing else.

**The tray.** The adjudicator asks `ability_timeline.player_tray_casts` which
stored tray drops are the player's casts (`ability_timeline.player_x_drops`) and keeps the X
slot's drops with the owner's verdict; it restates none of the tray's rules.
An own selection binds to the nearest X cast whose drop lies within the
player's agent's cast window (`cast_window`): its `tray_witness` holds onset
minus drop, `dt_s`, and the drop's time, or is null with a reason. An
unwitnessed own line also stores the nearest X drop the owner refused within
the window, with the owner's reason (`tray_refused`), so the two channels'
disagreement is kept, not settled here. An X cast inside a round with no own
selection in its window is a `missed_line` row: the cast, its round, the
player's agent, and the best stored peak of the own template within the
window, which lies below THRESHOLD, or null with `no_peak_above_floor` when the
reader stored none there. The window binds two observations of one cast. A
session without current tray drops, or without the player's agent, binds
nothing and says why in its coverage row.

**Bursts** (0.3.0). A selected peak with BURST_N or more selected peaks (itself
included) within BURST_S of its onset lies in a burst, and bursts chained within
BURST_S are one: a sound that fires many templates, since a line fires its own
template and at most one other (`docs/VOICE_LINES.md`, "Verdicts at 0.2.0"). In
a burst, every peak under BURST_BOUND is refused with reason `burst`; a peak at
or above it stands. A burst whose best peak is weak is so refused whole, and a
strong line keeps its place while its crosstalk is refused. The refused row
keeps its class and the burst's size and best score; nothing is deleted. The
bound was fitted on the dev half of the Riot sessions
(`prototypes/riot_ground_truth.py`; split by sorted session id, even places dev):
the midpoint between the strongest dev burst whose best row Riot's count does not
hold (0.0753, 23 templates in 2 s) and the weakest whose best row it holds live
(0.0908).

**Burst floor** (0.4.0). The burst counts every stored peak at or above
BURST_FLOOR, selected or not: a weak selection among two or more other
templates' sub-threshold peaks is the same many-template sound as a burst of
selections, and at 0.3.0 it stood as a cast. The selected peaks alone still
decide what is refused. BURST_FLOOR was fitted on the dev half: per cast under
BURST_BOUND, the third-highest stored peak within BURST_S of its onset; the
floor is the midpoint of the highest such value of a row Riot's count holds
(0.0334) and the lowest of an excess row above it (0.0378).

**Heard-line check** (0.4.0). The coverage row's `vo_heard` states whether any
template's best stored peak reaches VO_HEARD_BOUND. A match capture whose cast
voice lines are absent from its audio scores no line above the noise, and its
want of casts then means "not heard", not "not cast". The bound is the midpoint,
on the dev half, of the best peak of the one capture without lines (0.065) and
the lowest best peak of the other matches (0.345). The check refuses nothing.

**Witnessed peaks** (0.3.0). A peak under THRESHOLD but at or above
WITNESS_FLOOR is a cast only with an independent witness of that cast, and the
row names it in `rests_on` and `witness`:

* `tray_x_cast` -- one of the player's X casts (`ability_timeline.player_x_drops`) in a round
  with no own selection in its window: the best own-template peak in the
  window.
* `ult_kill` -- a stored `death` verdict whose resolved killfeed icon is an
  ultimate (`adjudication.weapon.ABILITY_CANONICAL_NAMES`, the agent by
  `weapon.ability_agent`) and whose actor the death owner names as that agent
  or leaves unnamed: the best peak of the agent's template for the actor's
  side in that round, at most DEATH_SLACK_S after the earliest such death,
  where no selected cast of that template already stands there. The actor's
  side is the victim's for a same-side entry (a revive) and the other side
  otherwise, as `adjudication.death` binds the killer's plate. NULL/cmd names
  the revived, not the actor (`weapon.REVIVED_CASTER_ICONS`), so it witnesses
  nothing here.

A witnessed peak the lineup classes `impossible` stays unselected and is
counted. A witness may also reinstate a peak a burst refused. The witnessed
claim `depends_on` the death's killer entity as well, since the icon named the
agent the selection rests on. WITNESS_FLOOR is the 95th percentile, on the dev
half, of the best live peak of a template in a round that holds neither a
selection nor a witness of it (12525 template rounds). The global THRESHOLD is
unchanged.

**Barrier drop** (0.5.0). Every cast and refusal row carries `drop`: its
round's barrier drop as `gametime` schedules it (`t_live_ms`)
[domain:rounds/buy-phase-barriers], the onset minus the drop (`dt_s`), and a
phase: `buy` more than DROP_WINDOW_S before the drop, `at_drop` within it,
`live` after it. A row outside every round, or in a round without a drop, has
`drop` null and a `drop_reason`. The row's `t_ms` stays the onset, an
observation time: a line at the drop may announce a cast made earlier in the
buy phase [domain:abilities/chamber-tour-de-force-enemy-line-at-drop]. The
window was fixed from the drop's precision before any line was read. Per
round, the drops the HUD's live clock reads imply spread
[metric:ult_phase/precision@all-matches#implied_spread_ms_p95=1000.0] ms at
the 95th percentile, and Riot's round zero falls
[metric:ult_phase/precision@all-matches#riot_zero_minus_drop_ms_median=973.0]
ms after the scheduled drop at the median (at most
[metric:ult_phase/precision@all-matches#riot_zero_minus_drop_ms_p95=1290.2]
ms at the 95th percentile), a lead partly the killfeed alignment's own. The
phase selects, refuses and names nothing. `prototypes/ult_phase_audit.py`
measured the phases per agent and the Chamber lines against Riot's count
(`docs/VOICE_LINES.md`, "Buy phase and the barrier drop").
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from ..agent_names import canonical_agent
from ..version import ULT_CAST_VERSION
from .identity import (AGENT_IDENTITY_VERSION, adjudicate_agent_identity, identity_claim,
                       identity_events, player_identity)

#: A peak at or above this score is selected. See the module docstring for the
#: run that set it and the sessions it was chosen on.
THRESHOLD = 0.0443
#: The identity channel every claim from an ultimate's voice line is made on.
CHANNEL = "ult_line"
VARIANTS = ("ally", "enemy")
CLASSES = ("own", "possible", "impossible", "unknown")
#: The tray slot that holds the ultimate.
ULT_SLOT = "X"
#: An own line binds to an X cast when its onset minus the drop lies in the
#: player's agent's window, in seconds. Every agent: OWN_WINDOW_S either side,
#: since onset minus drop has a median of
#: [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#onset_median_s=-0.43] s.
#: Phoenix: from 20 s before, because Run it Back's pips fall at expiry
#: [domain:abilities/phoenix-run-it-back-expiry-flash] while the caster hears
#: the line at the cast [domain:abilities/caster-hears-own-ult-line]. With
#: these windows the 0.2.0 prototype found
#: [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#own_recall_agent_window=0.844]
#: of the player's X casts at THRESHOLD, against
#: [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#own_recall=0.667]
#: with 1.5 s for every agent. `prototypes/voice_lines.py` imports both.
OWN_WINDOW_S = 1.5
CAST_WINDOW = {"Phoenix": (-20.0, OWN_WINDOW_S)}
#: The fields `tray.drops` writes, its gold `witness` included, so every caller
#: of the gate hands it the same drop. The stored gate's fields stay behind, so
#: the owner decides afresh on the rounds this adjudicator reads.
DROP_FIELDS = ("t_ms", "slot", "from", "to", "suspect", "forced", "cooccur", "across_gap",
               "witness")
#: A burst: at least BURST_N selected peaks within BURST_S of one onset.
BURST_N = 3
BURST_S = 2.0
#: In a burst, peaks under this score are refused. Fitted on the dev half; see
#: the module docstring.
BURST_BOUND = 0.083
#: A burst counts every stored peak at or above this score, selected or not.
#: Fitted on the dev half; see the module docstring.
BURST_FLOOR = 0.0356
#: A capture whose best stored peak falls under this score holds no heard
#: line (`vo_heard`). Fitted on the dev half; see the module docstring.
VO_HEARD_BOUND = 0.205
#: The lowest score a witnessed peak may have. Fitted on the dev half; see the
#: module docstring.
WITNESS_FLOOR = 0.030
#: A line counts for an ultimate's killfeed entry up to this long after it (s):
#: on the dev half, revive entries follow their own line by 0.0-0.3 s and some
#: Not Dead Yet entries precede it by up to 0.3 s.
DEATH_SLACK_S = 1.5
#: A line whose onset lies within this of its round's barrier drop (s) is
#: `at_drop`. Fixed from the drop's precision before any line was read; see
#: the module docstring, "Barrier drop".
DROP_WINDOW_S = 1.5
DROP_PHASES = ("buy", "at_drop", "live")
_OTHER = {"ally": "enemy", "enemy": "ally"}


def lineup_sides(lineup: dict | None, session_id: str) -> dict | None:
    """Per side, the agents the identity arbiter names, the best guess and
    rival of each slot it leaves unresolved, how many it leaves unresolved,
    whether all five are named, and the slot entity ids."""
    if not lineup or not lineup.get("sides"):
        return None
    verdicts = {v.get("entity_id"): v for v in lineup.get("agent_identity") or []}
    out = {}
    for side in VARIANTS:
        rows = lineup["sides"].get(side) or []
        named, soft, refused, slots = [], set(), 0, []
        for i, s in enumerate(rows):
            eid = f"{session_id}:{side}:slot:{s.get('slot', i)}"
            slots.append(eid)
            v = verdicts.get(eid) or {}
            if v.get("status") == "resolved" and v.get("agent"):
                named.append(canonical_agent(v["agent"]))
            else:
                refused += 1
                soft |= {canonical_agent(a) for a in (s.get("best_guess"), s.get("rival")) if a}
        out[side] = {"named": named, "soft": sorted(soft), "refused": refused,
                     "complete": refused == 0 and len(rows) == 5, "slots": slots}
    return out


def player_agent(lineup: dict | None, session_id: str) -> str | None:
    """The player's agent, where the arbiter names it (`identity.player_identity`)."""
    agent = player_identity(lineup, session_id)["agent"]
    return canonical_agent(agent) if agent else None


def template_class(agent: str, variant: str, sides: dict | None,
                   player: str | None) -> tuple[str, str | None]:
    """(own, possible, impossible or unknown; the reason for any but possible)
    for one template in one session. See the module docstring."""
    if variant == "ally" and player is not None and agent == player:
        return "own", None
    if sides is None:
        return "unknown", "no_lineup"
    s = sides[variant]
    if agent in s["named"]:
        return "possible", None
    if variant == "ally":
        if agent in s["soft"]:
            return "unknown", "agent_is_a_guess_for_an_unresolved_ally_slot"
        return "impossible", "agent_not_on_ally_side"
    if s["complete"]:
        return "impossible", "agent_not_on_complete_enemy_side"
    return "unknown", f"enemy_side_has_{s['refused']}_unresolved_slots"


def round_of(t_ms: float, rounds: list[dict]) -> int | None:
    """The round an instant belongs to, by `rounds.in_round_window`: the
    post-round period is the round's own."""
    from ..rounds import round_containing as owner_round
    r = owner_round(t_ms, rounds)
    return None if r is None else int(r["round_no"])


def cast_window(agent: str | None) -> tuple[float, float]:
    """(earliest, latest) onset minus X drop, in seconds, at which an own line
    of `agent` binds to the drop."""
    return CAST_WINDOW.get(agent, (-OWN_WINDOW_S, OWN_WINDOW_S))


def rests_on_line(drop: dict) -> bool:
    """Whether the gate passed `drop` on an own ult line (`rests_on` names
    `ult_cast`), so it may never witness a line."""
    return any(x.get("stream") == "ult_cast" for x in drop.get("rests_on") or ())


def in_window(onset_ms: float, cast_ms: float, window: tuple[float, float]) -> bool:
    """Whether onset minus drop lies in `window` (seconds)."""
    return window[0] <= (onset_ms - cast_ms) / 1000.0 <= window[1]


def nearest_cast(t_ms: float, casts_ms: list[float],
                 window: tuple[float, float]) -> dict | None:
    """The X cast nearest a line's onset among those whose onset minus drop lies
    in `window`, as {dt_s, cast_t_ms}, or None."""
    near = [(abs(t_ms - c), c) for c in casts_ms if in_window(t_ms, c, window)]
    if not near:
        return None
    c = min(near)[1]
    return {"dt_s": round((t_ms - c) / 1000.0, 3), "cast_t_ms": c}


def burst_of(t_s, scores, n: int = BURST_N, span_s: float = BURST_S) -> list[dict | None]:
    """Per selected peak (onsets `t_s` in seconds, `scores`), the burst it lies
    in as {n, best_score, t0_s}, or None. A peak lies in a burst when at least
    `n` peaks, itself included, lie within `span_s` of its onset; in-burst peaks
    chained within `span_s` are one burst."""
    t = np.asarray(t_s, dtype=float)
    s = np.asarray(scores, dtype=float)
    out: list[dict | None] = [None] * len(t)
    if len(t) < n:
        return out
    order = np.argsort(t, kind="stable")
    ts = t[order]
    count = np.searchsorted(ts, ts + span_s, "right") - np.searchsorted(ts, ts - span_s, "left")
    inb = np.flatnonzero(count >= n)
    if not inb.size:
        return out
    gid = np.concatenate([[0], np.cumsum(np.diff(ts[inb]) > span_s)])
    for g in np.unique(gid):
        members = order[inb[gid == g]]
        info = {"n": int(members.size), "best_score": float(s[members].max()),
                "t0_s": float(t[members].min())}
        for i in members:
            out[int(i)] = info
    return out


def vo_heard(peaks: list[dict], bound: float = VO_HEARD_BOUND) -> dict:
    """Whether any template's best stored peak reaches `bound`: {heard, best_score,
    best_template, bound, reason}. See the module docstring."""
    best = max(peaks, key=lambda p: p["score"], default=None)
    if best is None:
        return {"heard": None, "best_score": None, "best_template": None, "bound": bound,
                "reason": "no_peaks"}
    heard = best["score"] >= bound
    return {"heard": heard, "best_score": best["score"], "best_template": best["template"],
            "bound": bound, "reason": None if heard else "no_line_above_bound"}


def drop_phase(t_ms: float, round_no: int | None, drops_ms: dict | None,
               window_s: float = DROP_WINDOW_S) -> tuple[dict | None, str | None]:
    """(the line's place against its round's barrier drop as {t_drop_ms, dt_s,
    phase, window_s}, or None; the reason for None). `drops_ms` maps a round
    number to its drop (`gametime`'s `t_live_ms`). See the module docstring."""
    if drops_ms is None:
        return None, "no_drops"
    if round_no is None:
        return None, "outside_round"
    t_drop = drops_ms.get(int(round_no))
    if t_drop is None:
        return None, "round_has_no_drop"
    dt = (float(t_ms) - float(t_drop)) / 1000.0
    phase = "at_drop" if abs(dt) <= window_s else "buy" if dt < 0 else "live"
    return {"t_drop_ms": float(t_drop), "dt_s": round(dt, 3), "phase": phase,
            "window_s": window_s}, None


def ult_kill_witnesses(death_rows: list[dict] | None, rounds: list[dict]) -> tuple[list[dict], dict]:
    """(each stored death verdict whose resolved killfeed icon is an ultimate,
    as {template, agent, side, round, t_ms, death_id, weapon, version}; counts
    of the ultimate icons left out, by reason). See the module docstring."""
    from .weapon import ABILITY_CANONICAL_NAMES, REVIVED_CASTER_ICONS, ability_agent
    ults = {name for stem, name in ABILITY_CANONICAL_NAMES.items() if stem.endswith("_Ultimate")}
    out, skipped = [], Counter()
    for d in death_rows or ():
        name = d.get("weapon")
        if d.get("kind") != "death_verdict" or name not in ults:
            continue
        if name in REVIVED_CASTER_ICONS:
            skipped["icon_names_the_revived"] += 1
            continue
        if (d.get("weapon_evidence") or {}).get("status", "resolved") != "resolved":
            skipped["icon_unresolved"] += 1
            continue
        agent, killer = canonical_agent(ability_agent(name)), canonical_agent(d.get("killer"))
        if killer is not None and killer != agent:
            skipped["actor_named_another_agent"] += 1
            continue
        if d.get("side") not in _OTHER:
            skipped["side_unread"] += 1
            continue
        side = d["side"] if d.get("same_side") else _OTHER[d["side"]]
        t = float(d["t_ms"])
        out.append({"template": f"{agent}_ult_{side}", "agent": agent, "side": side,
                    "round": round_of(t, rounds), "t_ms": t, "death_id": d.get("death_id"),
                    "weapon": name, "version": d.get("death_adjudication_version")})
    return out, dict(sorted(skipped.items()))


def adjudicate(session_id: str, peak_rows: list[dict], lineup: dict | None,
               rounds: list[dict], round_version: str | None,
               threshold: float = THRESHOLD, tray_drops: list[dict] | None = None,
               tray_reason: str | None = "no_tray_drops",
               tray_inputs: dict | None = None, deaths: list[dict] | None = None,
               death_reason: str | None = "no_deaths", burst_bound: float = BURST_BOUND,
               witness_floor: float = WITNESS_FLOOR, burst_floor: float = BURST_FLOOR,
               drops_ms: dict | None = None) -> dict:
    """The session's stored rows, its claims, the arbiter's verdicts and the
    formal identity events, from stored peaks, the lineup and the rounds.

    `tray_drops` are the X drops with the owner's verdict from
    `ability_timeline.player_x_drops`, or None with `tray_reason`; `tray_inputs` are their
    stamps for the coverage row. `deaths` are the stored `death` verdicts, or
    None with `death_reason`. `drops_ms` maps each round number to its barrier
    drop as `gametime` schedules it, or is None. `burst_bound`, `witness_floor`
    and `burst_floor` exist for the scorer's sweep; production passes none of
    them."""
    cover = next((r for r in peak_rows if r.get("kind") == "coverage"), {}) or {}
    peaks = [r for r in peak_rows if r.get("kind") == "peak"]
    sides = lineup_sides(lineup, session_id)
    player = player_agent(lineup, session_id)
    selected = sorted((p for p in peaks if p["score"] >= threshold),
                      key=lambda p: (p["frame"], p["template"]))
    source = cover.get("ult_line_version") or (peaks[0].get("ult_line_version") if peaks else None)
    window = cast_window(player)
    if tray_drops is not None and player is None:
        tray_reason = "no_player_agent"
    bind = tray_drops is not None and player is not None
    # A cast the gate passed on an own line rests on this adjudicator: it is
    # kept as a refused drop that names the line it rests on, never a witness.
    tray_casts = ([c for c in tray_drops if c["player_cast"] and not rests_on_line(c)]
                  if bind else [])
    casts_ms = [float(c["t_ms"]) for c in tray_casts]
    refused = {float(c["t_ms"]): ("rests_on_own_line" if c["player_cast"] else c["reason"])
               for c in tray_drops or [] if not c["player_cast"] or rests_on_line(c)}

    # 1. Selection, class and bursts. A burst counts every peak at or above
    # the burst floor; the selected peaks are among them.
    meta = {}
    floor = min(burst_floor, threshold)
    counted = [p for p in peaks if p["score"] >= floor]
    by_peak = {id(p): b for p, b in zip(counted, burst_of([p["t_s"] for p in counted],
                                                          [p["score"] for p in counted]))}
    bursts = [by_peak[id(p)] for p in selected]
    for p, b in zip(selected, bursts):
        agent, t_ms = canonical_agent(p["agent"]), round(p["t_s"] * 1000.0)
        cls, why = template_class(agent, p["variant"], sides, player)
        eid = f"{session_id}:ult_cast:{t_ms}:{p['template']}"
        meta[eid] = {"t_ms": t_ms, "peak": p, "agent": agent, "class": cls, "reason": why,
                     "burst": b, "refused": (why if cls == "impossible" else
                                             "burst" if b and p["score"] < burst_bound else None),
                     "witness": None}

    def standing(template, keep=lambda m: True):
        return [m for m in meta.values() if m["refused"] is None
                and m["peak"]["template"] == template and keep(m)]

    def candidate(template, keep):
        """The best peak of `template` that `keep` admits, at or above the
        witness floor, that is not already a standing cast: (peak, entity id)."""
        best = None
        for p in peaks:
            if p["template"] != template or p["score"] < witness_floor or not keep(p):
                continue
            eid = f"{session_id}:ult_cast:{round(p['t_s'] * 1000.0)}:{template}"
            if eid in meta and meta[eid]["refused"] is None:
                continue
            if best is None or (p["score"], -p["t_s"]) > (best[0]["score"], -best[0]["t_s"]):
                best = (p, eid)
        return best

    def accept(p, eid, witness, rests_on, depends=()):
        agent, t_ms = canonical_agent(p["agent"]), round(p["t_s"] * 1000.0)
        cls, why = template_class(agent, p["variant"], sides, player)
        if cls == "impossible":
            return False
        old = meta.get(eid) or {}
        meta[eid] = {"t_ms": t_ms, "peak": p, "agent": agent, "class": cls, "reason": why,
                     "burst": old.get("burst"), "refused": None, "witness": witness,
                     "rests_on": rests_on, "depends": list(depends),
                     "burst_refusal_overridden": old.get("refused") == "burst"}
        return True

    # 2. Witnesses for peaks under the threshold. The tray first: it binds by time.
    wit = Counter()
    own_tpl = f"{player}_ult_ally"
    for c in tray_casts:
        t = float(c["t_ms"])
        if round_of(t, rounds) is None or standing(
                own_tpl, lambda m: in_window(m["t_ms"], t, window)):
            continue
        got = candidate(own_tpl, lambda p: in_window(p["t_s"] * 1000.0, t, window))
        if got is None:
            wit["tray_below_floor"] += 1
            continue
        w = {"kind": "tray_x_cast", "cast_t_ms": t,
             "dt_s": round((got[0]["t_s"] * 1000.0 - t) / 1000.0, 3)}
        ok = accept(*got, w, [{"stream": "tray_drop", "owner": "ability_timeline.player_tray_casts",
                               "cast_t_ms": t}])
        wit["tray_accepted" if ok else "tray_impossible"] += 1
    kills, skipped = ult_kill_witnesses(deaths, rounds) if deaths is not None else ([], {})
    by_key = defaultdict(list)
    for k in kills:
        if k["round"] is not None:
            by_key[(k["template"], k["round"])].append(k)
    for (tpl, rnd), ks in sorted(by_key.items(), key=lambda x: (x[0][1], x[0][0])):
        first = min(ks, key=lambda k: k["t_ms"])
        hi_ms = first["t_ms"] + DEATH_SLACK_S * 1000.0
        if standing(tpl, lambda m: round_of(m["t_ms"], rounds) == rnd and m["t_ms"] <= hi_ms):
            wit["ult_kill_explained"] += 1
            continue
        got = candidate(tpl, lambda p: p["t_s"] * 1000.0 <= hi_ms
                        and round_of(p["t_s"] * 1000.0, rounds) == rnd)
        if got is None:
            wit["ult_kill_below_floor"] += 1
            continue
        w = {"kind": "ult_kill", "death_id": first["death_id"], "weapon": first["weapon"],
             "death_t_ms": first["t_ms"], "lead_s": round((first["t_ms"] / 1000.0) - got[0]["t_s"], 3),
             "deaths": len(ks)}
        ok = accept(*got, w, [{"stream": "death", "owner": "adjudication.death",
                               "death_id": k["death_id"], "version": k["version"]} for k in ks],
                    depends=[f"{k['death_id']}:killer" for k in ks if k["death_id"]])
        wit["ult_kill_accepted" if ok else "ult_kill_impossible"] += 1

    # 3. Claims, one per selected or witnessed peak, through the arbiter.
    claims = []
    ordered = sorted(meta.items(), key=lambda x: (x[1]["peak"]["frame"], x[1]["peak"]["template"]))
    for eid, m in ordered:
        p, variant = m["peak"], m["peak"]["variant"]
        on = list(sides[variant]["slots"]) if sides else []
        on += m.get("depends", [])
        claims.append(identity_claim(
            eid, None if m["refused"] else m["agent"], channel=CHANNEL,
            observed_at_ms=m["t_ms"], reason=m["refused"] if m["refused"] == "burst" else m["reason"],
            source_version=source,
            evidence={"template": p["template"], "variant": variant, "score": p["score"],
                      "floor": p.get("floor"), "class": m["class"], "threshold": threshold,
                      "selected_by": "witness" if m["witness"] else "threshold",
                      **({"witness": m["witness"]} if m["witness"] else {})},
            depends_on=on or None))
    verdicts = adjudicate_agent_identity(claims)
    by_id = {v["entity_id"]: v for v in verdicts}
    common = {"session_id": session_id, "ult_cast_version": ULT_CAST_VERSION}
    rows, events = [], []
    for eid, m in ordered:
        p, v = m["peak"], by_id[eid]
        rnd = round_of(m["t_ms"], rounds)
        drop, drop_why = drop_phase(m["t_ms"], rnd, drops_ms)
        base = {**common, "entity_id": eid, "t_ms": m["t_ms"], "t_s": p["t_s"],
                "variant": p["variant"], "template": p["template"], "score": p["score"],
                "floor": p.get("floor"), "class": m["class"],
                "round": rnd, "burst": m["burst"], "drop": drop, "drop_reason": drop_why}
        if m["refused"]:
            rows.append({**base, "kind": "refusal", "template_agent": m["agent"],
                         "reason": m["refused"], "class_reason": m["reason"]})
        else:
            rows.append({**base, "kind": "cast", "side": p["variant"],
                         "player_cast": m["class"] == "own",
                         "agent": v["agent"] if v["status"] == "resolved" else None,
                         "identity_status": v["status"], "identity_reason": v["reason"],
                         "class_reason": m["reason"],
                         "selected_by": "witness" if m["witness"] else "threshold",
                         "witness": m["witness"], "rests_on": m.get("rests_on") or [],
                         **({"burst_refusal_overridden": True}
                            if m.get("burst_refusal_overridden") else {})})
            if m["class"] == "own":
                w = nearest_cast(m["t_ms"], casts_ms, window) if bind else None
                rows[-1]["tray_witness"] = w
                rows[-1]["tray_witness_reason"] = (
                    None if w else "no_x_cast_in_window" if bind else tray_reason)
                if bind and w is None:
                    r = nearest_cast(m["t_ms"], list(refused), window)
                    rows[-1]["tray_refused"] = None if r is None else {
                        "dt_s": r["dt_s"], "drop_t_ms": r["cast_t_ms"],
                        "reason": refused[r["cast_t_ms"]]}
        events += identity_events([v], session_id, m["t_ms"])

    # 4. The player's X casts inside a round with no own cast in their window.
    missed, outside = [], 0
    own_ms = [r["t_ms"] for r in rows if r["kind"] == "cast" and r["class"] == "own"]
    own_peaks = [p for p in peaks if p["template"] == own_tpl]
    for c in tray_casts:
        t = float(c["t_ms"])
        rnd = round_of(t, rounds)
        if rnd is None:
            outside += 1
            continue
        if any(in_window(o, t, window) for o in own_ms):
            continue
        inside = [p for p in own_peaks if in_window(p["t_s"] * 1000.0, t, window)]
        best = max(inside, key=lambda p: (p["score"], -p["t_s"]), default=None)
        missed.append({
            **common, "kind": "missed_line", "t_ms": t, "cast_t_ms": t, "round": rnd,
            "player_agent": player, "template": own_tpl, "window_s": list(window),
            "tray": {k: c.get(k) for k in ("from", "to", "suspect", "cooccur", "forced",
                                           "across_gap")},
            "best_peak": None if best is None else {
                "score": best["score"], "floor": best.get("floor"), "t_s": best["t_s"],
                "dt_s": round(best["t_s"] - t / 1000.0, 3)},
            "best_peak_reason": None if best else "no_peak_above_floor"})
    rows += missed

    sel_rows = [r for r in rows if r["kind"] in ("cast", "refusal")]
    by_class = Counter(r["class"] for r in sel_rows)
    own_rows = [r for r in rows if r["kind"] == "cast" and r["class"] == "own"]
    groups = {(b["t0_s"], b["n"]): b for b in bursts if b}
    coverage = {**common, "kind": "coverage", "threshold": threshold,
                "inputs": {"ult_line": source,
                           "lineup": (lineup or {}).get("version"),
                           "board_state": (lineup or {}).get("board_state"),
                           "agent_identity": AGENT_IDENTITY_VERSION,
                           "round": round_version},
                "templates_key": cover.get("templates_key"),
                "ult_line_reason": cover.get("reason"),
                "lineup": sides is not None, "player_agent": player,
                "peaks": len(peaks), "selected": len(selected),
                "by_class": {c: by_class.get(c, 0) for c in CLASSES},
                "casts": sum(r["kind"] == "cast" for r in rows),
                "refusals": sum(r["kind"] == "refusal" for r in rows),
                "refusal_reasons": dict(sorted(Counter(
                    "burst" if r["reason"] == "burst" else "impossible"
                    for r in rows if r["kind"] == "refusal").items())),
                "rounds": len(rounds),
                "vo_heard": vo_heard(peaks),
                "drop": {"window_s": DROP_WINDOW_S,
                         "rounds": None if drops_ms is None else len(drops_ms),
                         "reason": None if drops_ms is not None else "no_drops",
                         **{f"{k}_{ph}": sum(r["kind"] == k and (r["drop"] or {}).get("phase") == ph
                                             for r in rows)
                            for k in ("cast", "refusal") for ph in DROP_PHASES},
                         "unplaced": sum(r["kind"] in ("cast", "refusal") and r["drop"] is None
                                         for r in rows)},
                "burst": {"n": BURST_N, "span_s": BURST_S, "bound": burst_bound,
                          "floor": floor, "bursts": len(groups),
                          "weak": sum(b["best_score"] < burst_bound for b in groups.values()),
                          "in_burst": sum(b is not None for b in bursts),
                          "refused": sum(r["kind"] == "refusal" and r["reason"] == "burst"
                                         for r in rows)},
                "witness": {"floor": witness_floor, "death_slack_s": DEATH_SLACK_S,
                            "deaths": len(deaths) if deaths is not None else None,
                            "death_reason": None if deaths is not None else death_reason,
                            "ult_kill_icons": len(kills), "ult_kill_icons_left_out": skipped,
                            **{k: wit.get(k, 0) for k in (
                                "tray_accepted", "tray_impossible", "tray_below_floor",
                                "ult_kill_accepted", "ult_kill_impossible",
                                "ult_kill_below_floor", "ult_kill_explained")}},
                "tray": {"bound": bind, "reason": None if bind else tray_reason,
                         "x_drops": len(tray_drops) if tray_drops is not None else None,
                         "player_x_casts": (sum(c["player_cast"] for c in tray_drops)
                                            if tray_drops is not None else None),
                         "casts_outside_round": outside, "window_s": list(window)},
                "own_witnessed": sum(r["tray_witness"] is not None for r in own_rows),
                "own_unwitnessed": sum(r["tray_witness"] is None for r in own_rows),
                "own_beside_refused_drop": dict(sorted(Counter(
                    r["tray_refused"]["reason"] for r in own_rows
                    if r.get("tray_refused")).items())),
                "missed_lines": len(missed),
                "missed_with_peak": sum(r["best_peak"] is not None for r in missed)}
    coverage["inputs"].update(tray_inputs or {})
    return {"rows": [coverage] + rows, "claims": claims, "verdicts": verdicts,
            "events": events}
