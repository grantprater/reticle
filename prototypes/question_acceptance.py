r"""Event-level acceptance: what an owning layer emits, scored per question against replay truth.

This file is the start of the one acceptance harness, QUESTION_ACCEPTANCE.md
build step B7, begun early (task `event-harness-20261007`). AGENTS.md:
acceptance scores the events a layer emits; a reader's own score is only a
diagnostic, reported beside; a new scorer extends this file and never adds
another prototype. B7's episode derivations (T1, T2, T2g, matching; QA1-QA3)
join it as subcommands.

It owns evaluation only and changes no reader or lane code. The truth is the
replay layer's entities. T1d decides only whether an enemy player is drawn.
It reuses the truth join and does not restate it:

* the draw truth is `t1_draw_rule.RealDrawMatch(rule="T1d")`;
* the (sample, enemy) pairs and the extras are `enemy_lane_check.build_sets`;
* each track's lane outcome is `real_reader_schedule.track_outcome`, the
  sorting `RealMatch.enemy_reads` applies (`identity_abstained`,
  `agent_not_on_enemy_team`, `named`);
* the extras' classes are `teardrop_refusals.class_extras`; the true false
  accepts are its `TRUE_FA` (ping, x_mark, other);
* the round bootstrap is `teardrop_refusals`' (`N_BOOT`, `SEED`); pooled
  intervals resample rounds within each match and add the matches.

**`lane --tag TAG [SESSION ...]`** scores the enemy lane. It runs
`reticle.enemy_tracks.build`, pure over stored rows, on the tagged reader
arm's `minimap_object` rows
(`<store>/analysis/teardrop-refusals-20261007/<TAG>/<SESSION>.jsonl`) with
the store's rounds, death verdicts, lineup and portrait references, and
writes the tracks to `<store>/analysis/question-acceptance/<TAG>/enemy_track/`.
It never reads the stored `enemy_track` stream: the truth join reads the built
tracks in its place (`teardrop_refusals._Redirect.streams`). It reports:

* (a) the reader's true false accepts by lane outcome: `no_track` (the icon
  joined no track), `identity_abstained`, `agent_not_on_enemy_team`,
  `named_duplicate` (named an enemy, and another icon of the same frame
  carries a track of the same name) and `named`; the counts sum to the
  reader's true false accepts (checked on every run), and a named find whose
  track also holds icons T1d places on a drawn living enemy is counted apart
  (it joined a real enemy's track rather than starting its own);
* (b) per question the lane serves, the emitted tracks' accuracy beside the
  reader's: drawn-enemy presence by named slot (a T1d-drawn enemy has an icon
  in that frame whose track is named him), and position by named slot (that
  icon within `NEAR_CM` of his truth xy), each as recall over the T1d pairs
  beside the reader's hit rate (any icon within `NEAR_CM`); and as precision
  over the accepted icons beside the reader's icon precision (an icon within
  `NEAR_CM` of a drawn living enemy).

First measurement (the `pgb` arm, rows QH in the prediction ledger): of the
reader's pooled true false accepts
[metric:question_acceptance/lane/pgb@dev3#false_accepts=167], the lane
names [metric:question_acceptance/lane/pgb@dev3#fa_named=157] and leaves
[metric:question_acceptance/lane/pgb@dev3#fa_identity_abstained=10]
unnamed; none is named off the enemy team or duplicated in its frame. The
named-slot presence recall is
[metric:question_acceptance/lane/pgb@dev3#lane_presence=0.5677] beside the
reader's hit rate of [metric:question_acceptance/lane/pgb@dev3#reader_hit=0.6077].

**`--reality off|on|paired`** (0.2.0, task `detection-reality-20261007`)
is the arm switch for `round_lifetimes.detection_reality`. `off` builds the
lane without glyph verdicts, so every track is `unassessed` and nothing is
refused: the 0.1.0 measurement. `on` hands `enemy_tracks.build` the glyph
owner's verdicts, adjudicated in memory from the stored `ability_glyph` rows
(`adjudication.ability_glyph.disc_verdicts(compute=True)`; nothing is written
to the store), and a refused track's finds take the outcome
`reality_refused`, counted by reason. `paired` runs both and reports, per
question, the difference on minus off with a paired round bootstrap: the
same resampled rounds score both arms.

First paired measurement (pgb): the rule refused
[metric:question_acceptance/lane/pgb/reality@dev3#fa_reality_refused=79] of
the true false accepts, all Tejo's Stealth Drone on c817691bcd15
[domain:abilities/tejo-stealth-drone-enemy-minimap-icon]; pooled presence
precision rose by
[metric:question_acceptance/lane/pgb/reality-paired@dev3#lane_presence_precision_diff=0.0075]
and presence recall moved by
[metric:question_acceptance/lane/pgb/reality-paired@dev3#lane_presence_diff=-0.0003].
9acf02f98283 stayed unassessed: its stored `ability_glyph` rows predate the
current glyph bank, and the glyph owner refuses stale rows.

**Every replay entity** (0.3.0, task `class-aware-harness-20261007`;
AGENTS.md, "Replay truth covers every entity"). `truth_under` joins every
find (an accepted icon on a valid sample) to the entity under it:

* players through T1d's join, at the find's sample (`M.X`, `M.Y`, alive);
* every `child:` entity T0 carries (`episodes.ChildTable`): its movement
  where it moves, its spawn while a static child is open, at the find's
  frame on the replay clock (`replay_truth.capture_to_replay`, the killfeed
  fit of `capture_replay_context`, `REMOTE_LAG_MS`) within +-`WINDOW_MS`,
  keeping the nearest, and inside its life: [open, close + `LIFE_TAIL_MS`],
  flagged `life_window_unmeasured`, unless its class has a measured onset
  and tail (`MEASURED_LIFE`); a child the layer never closed holds to its
  round's end (`close_unseen`). `NOT_JOINED` names the classes left out;
* one to one per sample by distance within `NEAR_CM`
  (`replay_truth._assign`, its frame ids spread past 64 columns).

`label --tag TAG` writes one row per find (`OUT/TAG/label/SESSION.jsonl`):
the entity's id, actor class, family, agent, ability, `tray_key`, owner,
`side_rel`, distance, window offset and life flag, beside the old class.

`lane` keeps every old number and adds the class-aware outcome of each
find (`CLASS_OUTCOMES`): `right_entity` (a T1d-drawn living enemy:
`name_right`, `name_wrong`, `unnamed` by the track's name);
`other_entity:<family>:<agent>:<ability>` with `drawn_by_fact` read only
from `domain/abilities.toml` (`drawn_by_fact`); `undrawn_truth` (a living
enemy T1d calls undrawn); `nothing_there:<derivation>`
(`held_by_nearer_find`, `kill_x`, `question_swap`, `ping`, `enemy_3_8m`,
`none`); `coverage_gap:<class>:<unmapped reason>`; `ambiguous` (two entity
classes within `AMBIG_CM`). The counts sum to the finds (checked every run).
Recall counts per class, each over its own (sample, live entity) pairs. Every
run prints the coverage report: finds per gap class, each census class with
the vision streams that claim it (`CLAIMERS`) and whether the join scores
it, and each mapped class not joined, with its reason.

First class-aware measurement (pgb, three development matches): of
[metric:question_acceptance/classes/pgb@dev3#finds=10487] finds,
[metric:question_acceptance/classes/pgb@dev3#right_entity=8742] lie on a
drawn enemy, [metric:question_acceptance/classes/pgb@dev3#other_entity=232]
on another entity, [metric:question_acceptance/classes/pgb@dev3#undrawn_truth=953]
on an undrawn enemy, [metric:question_acceptance/classes/pgb@dev3#nothing_there=186]
on nothing and [metric:question_acceptance/classes/pgb@dev3#ambiguous=373]
are ambiguous. Of the old true false accepts,
[metric:question_acceptance/classes/pgb@dev3#true_fa_other_entity=126] lie on
another entity: Tejo's Stealth Drone
[metric:question_acceptance/classes/pgb@dev3#true_fa_tejo_stealth_drone=82]
[domain:abilities/tejo-stealth-drone-enemy-minimap-icon], Fade's Prowler
[metric:question_acceptance/classes/pgb@dev3#true_fa_fade_prowler=13], Reyna's
Leer [metric:question_acceptance/classes/pgb@dev3#true_fa_reyna_leer=11] and
ally players; [metric:question_acceptance/classes/pgb@dev3#true_fa_nothing_there=37]
lie on nothing. Recall of drawn enemies falls from the reader's hit rate to
[metric:question_acceptance/classes/pgb@dev3#recall_player_enemy_drawn=0.5709]
once each find holds one entity and ambiguous finds are set apart. The layer's
enemy px reproduce the scorer's `enemies_px` within 1 px on every compared
entry (the instrument control, recorded per session).

**Steps 5 to 8** (0.4.0 on, task `harness-steps-5-8-20261007`) score other
owners' emitted finds through the same join (`_join_entities`, which
`truth_under` now calls) and the same vocabulary (`claim_outcome`): a find
claims an entity kind and perhaps a name; on that kind it is
`right_entity` (`name_right`, `name_wrong`, `unnamed`) or `undrawn_truth`
where the draw rule says undrawn; any other entity is `other_entity:<key>`
(the player's own icon is `player_self`), an unmapped actor
`coverage_gap:<class>:<reason>`, none `nothing_there:<derivation>`. Each
stream's frames join the grid one sample per frame (`frame_samples`: the
nearest within half a grid step, live play only). Recall counts per
claimed class over its own pairs; the counts sum to the finds on every run;
intervals resample rounds (`teardrop_refusals`' `N_BOOT`, `SEED`); the
coverage report prints per run; the reader's own finds are scored beside,
unnamed, as a diagnostic. `STEP_STREAMS` names each step's owner and
streams. Rows go to `OUT/steps/STEP/SESSION.jsonl` (`reader_SESSION.jsonl`
beside).

*Step 5, `ally`* (0.4.0): `round_entities`' ally observations bound to an
entity, claiming the entity's resolved agent, at the samples of drawn
`ally_icon` frames; the self family is the self-icon owner's and is left
out. On the development matches (`round_entity` rebuilt by `reticle
lifetimes` from stored rows; `ally_icon` and `death` stay stale, see
`reticle plan`), of
[metric:question_acceptance/ally@dev3#finds=127564] finds,
[metric:question_acceptance/ally@dev3#right_entity=113068] lie on a
teammate, [metric:question_acceptance/ally@dev3#right_entity_name_right=103748]
named right and [metric:question_acceptance/ally@dev3#right_entity_name_wrong=1803]
wrong; [metric:question_acceptance/ally@dev3#other_entity=5446] lie on
another entity, most on an ally Sage Barrier Orb about 2 m away on
c817691bcd15, then Raze's Boom Bot, Sova's Owl Drone and the player's own
icon. Recall over (sample, live teammate) pairs is
[metric:question_acceptance/ally@dev3#recall_player_ally_live=0.7544]
beside the reader's
[metric:question_acceptance/ally@dev3#reader_recall_player_ally_live=0.7563]:
the owner keeps nearly every right find the reader makes.

*Step 6, `smoke`* (0.5.0): `adjudication.smoke_owner`'s smokes, one find
per track at each sample of a read `minimap_dark` frame inside the track's
observed life, claiming a smoke child (`t1_draw_rule.SMOKES` classes) of
the ally agent it names. The stored streams are stale (smoke-0.4.0 over
minimap-dark-0.1.0); `reticle smokes` refuses stale `minimap_dark` rows,
and their rescan decodes video, so the stale rows are scored. Of
[metric:question_acceptance/smoke@dev3#finds=6993] finds,
[metric:question_acceptance/smoke@dev3#right_entity=5245] lie on a smoke,
[metric:question_acceptance/smoke@dev3#right_entity_name_right=3924]
named right and none wrong; the rest of the right ones are 9acf02f98283's,
where the owner names no track. All
[metric:question_acceptance/smoke@dev3#nothing_there=1081] finds on
nothing are d3dcfb182ab1's Clove smokes: whole tracks on no entity, or
tails past the child's scored life. No find lies on an enemy smoke
[domain:abilities/enemy-smokes-not-on-minimap]. Recall of ally smokes is
[metric:question_acceptance/smoke@dev3#recall_ability_ally_clove_ruse_smoke=0.7939]
(Clove's Ruse),
[metric:question_acceptance/smoke@dev3#recall_ability_ally_omen_dark_cover_smoke=0.6621]
(Omen's Dark Cover) and
[metric:question_acceptance/smoke@dev3#recall_ability_ally_jett_cloudburst_smoke=0.1775]
(Jett's Cloudburst).

*Step 7, `glyph`* (0.6.0): the glyph owner's verdicts on their disc
tracks' fixes, one find per fix at the sample of its `ability_glyph`
frame, claiming an ability child of either side by `Agent:Slot` (the
child's agent and tray key); an abstained verdict claims a child unnamed.
`reticle ability-glyphs` rebuilt c817691bcd15's and d3dcfb182ab1's verdicts
from stored rows (identical to the stored ones); their `ability_glyph`
rows stay stale, and 9acf02f98283's were scored on an older glyph bank, so
the owner refuses that session: no finds and no recall pairs, the refusal
in the document. Of
[metric:question_acceptance/glyph@dev3#finds=6050] finds,
[metric:question_acceptance/glyph@dev3#right_entity=2898] lie on an
ability child, [metric:question_acceptance/glyph@dev3#right_entity_name_right=449]
named right and
[metric:question_acceptance/glyph@dev3#right_entity_name_wrong=0] wrong;
the rest abstained. [metric:question_acceptance/glyph@dev3#other_entity=1266]
lie on another entity, mostly a teammate's or the player's own icon, and
[metric:question_acceptance/glyph@dev3#nothing_there=1784] on nothing,
most of them d3dcfb182ab1's. The ally smokes are the classes the tracks
hold best: Omen's Dark Cover at
[metric:question_acceptance/glyph@dev3#recall_ability_ally_omen_dark_cover=0.8096]
and Clove's Ruse at
[metric:question_acceptance/glyph@dev3#recall_ability_ally_clove_ruse=0.8011];
the enemy drones the lane confuses with players stay low (Tejo's Stealth
Drone, Fade's Prowler, below 0.11).

*Step 8, `marks --tag TAG`* (0.7.0): the marks the owners emit over the
tag's `minimap_object` rows, one find each, against the truth marks
(`_mark_truth`): each death's X at the victim's last living place until the
round ends [domain:minimap/death-mark-persistence], an ally's always
[domain:minimap/ally-death-mark], an enemy's drawn where T1d drew him at
his last living sample (`DrawRule.dead_mark`,
[domain:minimap/enemy-death-mark]); and each T1d swap's "?" for its
widget lifetime [domain:minimap/last-known-mark-widget-lifetime]. The X
finds are the death owner's births (`stored_xmark_births` over the tag's
rows; the stored `death` stream places no death by X, its
`minimap_object` being stale), each claiming a death X of its colour's
side; the "?" finds are the lane's `mark` rows, each named by the track it
binds. A "?" shares the enemy players' ambiguity class, since its enemy
stands at its place when it appears; a truth mark two finds share stays
with the nearer (`hold_duplicate_marks`). On the pgb arm, of
[metric:question_acceptance/marks/pgb@dev3#claim_ally_finds=165] blue X
births [metric:question_acceptance/marks/pgb@dev3#claim_ally_right_entity=120]
lie on an ally death, and of
[metric:question_acceptance/marks/pgb@dev3#claim_enemy_finds=136] red ones
[metric:question_acceptance/marks/pgb@dev3#claim_enemy_right_entity=80]
on an enemy death; the X births recall
[metric:question_acceptance/marks/pgb@dev3#recall_death_x_ally_always_drawn=0.4511]
of the ally deaths. Of
[metric:question_acceptance/marks/pgb@dev3#claim_question_finds=830] "?"
marks, only [metric:question_acceptance/marks/pgb@dev3#claim_question_right_entity=146]
lie on a T1d swap (named right
[metric:question_acceptance/marks/pgb@dev3#claim_question_right_entity_name_right=125]
times). Of the rest,
[metric:question_acceptance/marks/pgb@dev3#claim_question_other_entity=465]
lie on another entity, most on a living enemy the replay still places there:
the lane reads a "?" before T1d's swap, evidence for the open "?" timing
question.

Stored rows and replay truth only; no decode, rescan or trial. The held-out
capture (cea8ecbc94ab) is refused. Not wired (`"wire": "no"` on its rows in
`notes/predictions.jsonl`): an evaluation.

    python prototypes/question_acceptance.py lane --tag pgb [SESSION ...] [--pings b1]
        [--reality off|on|paired] [--record]
    python prototypes/question_acceptance.py label --tag pgb [SESSION ...] [--reality off|on]
    python prototypes/question_acceptance.py ally [SESSION ...] [--record]
    python prototypes/question_acceptance.py smoke [SESSION ...] [--record]
    python prototypes/question_acceptance.py glyph [SESSION ...] [--record]
    python prototypes/question_acceptance.py marks --tag pgb [SESSION ...] [--pings b1] [--record]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import teardrop_refusals as tr  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "question-acceptance-0.7.0"
TASK = "event-harness-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "question-acceptance"
DEV = tr.DEV
NEAR_CM = tr.NEAR_CM
#: The lane outcomes of a find, in report order.
OUTCOMES = ("no_track", "reality_refused", "identity_abstained", "agent_not_on_enemy_team",
            "named_duplicate", "named")
#: Outcomes the lane drops (the track is no entity, or carries no enemy-team name).
DROPPED = ("reality_refused", "identity_abstained", "agent_not_on_enemy_team")
#: The `--reality` arms and the folder suffix each writes under.
ARMS = {"off": "", "on": "_reality"}

# The truth join (`truth_under`).
#: Time window: the find's frame at t_rep +- WINDOW_MS, keeping the nearest.
#: The remote-render delay lies in a band of [30, 200] ms
#: (`t1_draw_rule.RENDER_BAND_MS`, [domain:capture/minimap-remote-player-lag]):
#: half that width (85 ms) plus one 15 Hz frame (67 ms).
WINDOW_MS = 150.0
WINDOW_STEP_MS = 25.0
#: A child's scoring life is [open, close + LIFE_TAIL_MS] unless its class has
#: a measured onset and tail; the tail is unmeasured for children (each row
#: says `life_window_unmeasured`).
LIFE_TAIL_MS = 600.0
#: Measured (onset, tail) ms by (actor class, owner side): the stored
#: `ability_shape` ring of the player's own Recon Bolt is drawn from a median
#: 315.5 ms after the bolt opens to 108.8 ms before it closes (15 bolts,
#: `prototypes/replay_abilities.py`, 9acf02f98283). Another side's bolt is
#: unmeasured and takes the default; no window is borrowed by analogy.
MEASURED_LIFE = {("GameObject_Hunter_Q_SonarBolt_C", "self"): (315.5, -108.8)}
#: Mapped classes the join leaves out, with the reason the coverage report prints.
NOT_JOINED = {"BombEquippable_C": "the layer holds only the spike item's spawn tick; a carried or "
                                  "dropped spike's place is not decoded, and its spawn would place it falsely"}
#: Two entity classes within AMBIG_CM of one find make it `ambiguous`.
AMBIG_CM = 100.0
#: An enemy "?" lasts 3.0 s and fades over 1.0 s [domain:minimap/last-known-mark-widget-lifetime].
Q_MARK_MS = 4000.0
#: The class-aware outcomes of a find, in report order.
CLASS_OUTCOMES = ("right_entity", "other_entity", "undrawn_truth", "nothing_there", "coverage_gap",
                  "ambiguous")


# ----------------------------------------------------------------- pure parts

def icon_outcomes(icon_p, icon_eid, icon_subj, track_out: dict) -> np.ndarray:
    """Each icon's lane outcome (`OUTCOMES`).

    `icon_p`: the icon's frame position; `icon_eid`: the track its
    observation joined, or None; `icon_subj`: the enemy subject its track is
    named (-1 when dropped); `track_out`: each track's
    `real_reader_schedule.track_outcome`. A named icon is `named_duplicate`
    when another icon of its frame carries a track named the same subject."""
    p = np.asarray(icon_p, np.int64)
    subj = np.asarray(icon_subj, np.int64)
    out = np.array([("no_track" if e is None else track_out[e]) for e in icon_eid], dtype=object)
    named = subj >= 0
    if named.any():
        code = p[named] * (int(subj.max()) + 1) + subj[named]
        _u, inv, cnt = np.unique(code, return_inverse=True, return_counts=True)
        dup = np.zeros(p.size, bool)
        dup[np.flatnonzero(named)] = cnt[inv] > 1
        out[dup & (out == "named")] = "named_duplicate"
    return out


def lane_questions(ks, ic, pair_k, pair_j, icon_p, icon_subj, icon_x, icon_y, X, Y, drawn, alive,
                   p_of, near_cm: float = NEAR_CM) -> dict:
    """Per pair and per accepted icon, whether the emitted tracks answer.

    Pairs (`pair_k`, `pair_j`) are the T1d-drawn (sample, enemy) pairs; the
    accepted icons on valid samples are `ks` (sample) and `ic` (icon index).
    Returns boolean arrays: `pair_named` (an icon of that frame is named j),
    `pair_named_pos` (and within `near_cm` of j's truth), `icon_named`
    (the icon's track is named an enemy), `icon_named_drawn` (that enemy is
    drawn and alive at the sample), `icon_named_pos` (and within `near_cm`),
    and `icon_err_cm` (named icon to its enemy's truth, NaN otherwise)."""
    ks = np.asarray(ks, np.int64)
    ic = np.asarray(ic, np.int64)
    S = X.shape[0]
    subj = np.asarray(icon_subj, np.int64)[ic]
    named = subj >= 0
    sj = np.where(named, subj, 0)
    err = np.hypot(np.asarray(icon_x)[ic] - X[sj, ks], np.asarray(icon_y)[ic] - Y[sj, ks])
    err = np.where(named & np.isfinite(err), err, np.nan)
    on = named & drawn[sj, ks] & alive[sj, ks]
    pos = on & (err <= near_cm)
    # pairs: the (frame, subject) codes the named icons cover
    fp = np.asarray(icon_p, np.int64)[ic]
    code_named = np.unique(fp[named] * S + subj[named])
    pk = np.asarray(pair_k, np.int64)
    pj = np.asarray(pair_j, np.int64)
    pf = np.asarray(p_of, np.int64)[pk]
    pc = pf * S + pj
    pair_named = np.isin(pc, code_named)
    # position: an icon named j in that frame within near_cm of j's truth at the pair's sample
    pair_pos = np.zeros(pk.size, bool)
    if pk.size and named.any():
        order = np.argsort(fp[named] * S + subj[named], kind="stable")
        codes = (fp[named] * S + subj[named])[order]
        ix = np.asarray(icon_x)[ic][named][order]
        iy = np.asarray(icon_y)[ic][named][order]
        lo = np.searchsorted(codes, pc, side="left")
        hi = np.searchsorted(codes, pc, side="right")
        n = hi - lo
        rep = np.repeat(np.arange(pk.size), n)
        idx = np.arange(rep.size) - np.repeat(np.cumsum(n) - n, n) + np.repeat(lo, n)
        d = np.hypot(ix[idx] - X[pj[rep], pk[rep]], iy[idx] - Y[pj[rep], pk[rep]])
        ok = np.where(np.isfinite(d), d <= near_cm, False)
        pair_pos[rep[ok]] = True
    return {"pair_named": pair_named, "pair_named_pos": pair_pos, "icon_named": named,
            "icon_named_drawn": on, "icon_named_pos": pos, "icon_err_cm": err}


# ----------------------------------------------------------------- truth under a find (pure parts)

def entity_key(family: str, agent, ability) -> str:
    """The class key of a truth entity: `family:agent:ability`, `-` for a
    missing part. Ambiguity and recall count by this key."""
    return f"{family}:{agent or '-'}:{ability or '-'}"


def child_family(mapped, agent, side_rel) -> str:
    """`ability_enemy`, `ability_ally`, `spike`, `ult_orb`, or `unmapped`."""
    if mapped is None:
        return "unmapped"
    m = str(mapped)
    if m == "ult orb":
        return "ult_orb"
    if "spike" in m:
        return "spike"
    return f"ability_{side_rel}" if side_rel in ("ally", "enemy") else "ability_unknown_side"


def short_reason(reason) -> str:
    """An unmapped reason without its lists (`instigator chain ends at [...]`)."""
    if reason is None:
        return "-"
    s = str(reason).split("[")[0].strip(" ,;:")
    return s.replace(" at", "").replace(":", "").strip() or "-"


def child_life(cls, side_rel, t_open, t_close, round_end, measured: dict, tail_ms: float = None):
    """Each child's scoring life [lo, hi] in replay ms and its flag.

    A class with a measured onset and tail (`measured[(class, side_rel)]`)
    takes them; every other class is [open, close + tail_ms], flagged
    `life_window_unmeasured`. A child the layer never closed is held to the
    end of its round (`close_unseen`)."""
    tail_ms = LIFE_TAIL_MS if tail_ms is None else tail_ms
    t_open = np.asarray(t_open, float)
    t_close = np.asarray(t_close, float)
    round_end = np.asarray(round_end, float)
    close = np.where(np.isfinite(t_close), t_close, round_end)
    lo = t_open.copy()
    hi = close + tail_ms
    flag = np.array(["life_window_unmeasured"] * t_open.size, dtype=object)
    flag[~np.isfinite(t_close)] = "life_window_unmeasured,close_unseen"
    for i, (c, s) in enumerate(zip(cls, side_rel)):
        m = measured.get((str(c), str(s)))
        if m is not None:
            lo[i] = t_open[i] + m[0]
            hi[i] = close[i] + m[1]
            flag[i] = "measured" + ("" if np.isfinite(t_close[i]) else ",close_unseen")
    return lo, hi, flag


def child_window_dist(position, c, t, fx, fy, lo, hi, window_ms: float = None, step_ms: float = None):
    """Per (child `c[i]`, find time `t[i]`, find xy): the nearest the child
    comes to the find within t ± window_ms while inside its life [lo, hi]
    (the find's own child: `lo[c[i]]`). `position(c, t)` gives the child's
    world xy. Returns (distance cm, the offset ms it was taken at); NaN where
    the child is never live in the window."""
    window_ms = WINDOW_MS if window_ms is None else window_ms
    step_ms = WINDOW_STEP_MS if step_ms is None else step_ms
    c = np.asarray(c, np.int64)
    t = np.asarray(t, float)
    off = np.arange(-window_ms, window_ms + 1e-9, step_ms)
    n = c.size
    if n == 0:
        return np.zeros(0), np.zeros(0)
    T = t[:, None] + off[None, :]
    live = (T >= np.asarray(lo)[c][:, None]) & (T <= np.asarray(hi)[c][:, None])
    cc = np.repeat(c, off.size)
    x, y = position(cc, T.ravel())
    d = np.hypot(x.reshape(n, -1) - np.asarray(fx)[:, None], y.reshape(n, -1) - np.asarray(fy)[:, None])
    d = np.where(live & np.isfinite(d), d, np.inf)
    j = np.argmin(d, axis=1)
    best = d[np.arange(n), j]
    return np.where(np.isfinite(best), best, np.nan), np.where(np.isfinite(best), off[j], np.nan)


def assign_one_to_one(frame, D, gate: float):
    """`replay_truth._assign` (one-to-one per frame, nearest first) over any
    number of truth columns: `_assign` keys a frame's column as
    `frame * 64 + column`, so the frame ids are spread by the column count."""
    import replay_truth as rt
    frame = np.asarray(frame, np.int64)
    if D.shape[0] == 0:
        return np.zeros(0, np.int64), np.zeros(0)
    spread = int(np.ceil(max(D.shape[1], 1) / 64.0))
    j, d = rt._assign(frame * spread, D, gate)
    return np.asarray(j, np.int64), np.asarray(d, float)


def ambiguous_classes(D, keys, within_cm: float = None) -> list:
    """Per find (row of D), the distinct class keys of the columns within
    `within_cm`; a find whose list holds two or more is `ambiguous`."""
    within_cm = AMBIG_CM if within_cm is None else within_cm
    keys = np.asarray(keys, dtype=object)
    near = np.where(np.isfinite(D), D <= within_cm, False)
    return [sorted(set(keys[np.flatnonzero(r)].tolist())) for r in near]


def outcome_of(kind: str, *, ambiguous: bool, assigned: bool, side_rel=None, drawn=None,
               subj_named=None, subj_truth=None, key=None, cls=None, unmapped_reason=None,
               derivation=None) -> tuple[str, str]:
    """A find's class-aware outcome (`CLASS_OUTCOMES`) and its full label.

    `kind`: `player` or `child` for an assigned find, else None. A find on a
    drawn living enemy is `right_entity` (`name_right` when its track names
    him, `name_wrong` when it names another, `unnamed` when none); on an
    undrawn living enemy, `undrawn_truth`; on any other live entity,
    `other_entity:<key>`, or `coverage_gap:<class>:<reason>` for an
    unmapped actor; on none, `nothing_there:<derivation>`."""
    if ambiguous:
        return "ambiguous", "ambiguous"
    if not assigned:
        return "nothing_there", f"nothing_there:{derivation or 'none'}"
    if kind == "player" and side_rel == "enemy":
        if not drawn:
            return "undrawn_truth", "undrawn_truth"
        if subj_named is None or subj_named < 0:
            return "right_entity", "right_entity:unnamed"
        return "right_entity", ("right_entity:name_right" if subj_named == subj_truth
                                else "right_entity:name_wrong")
    if kind == "child" and key is not None and key.startswith("unmapped:"):
        return "coverage_gap", f"coverage_gap:{cls}:{short_reason(unmapped_reason)}"
    return "other_entity", f"other_entity:{key}"


def nothing_derivation(fx, fy, ft, kills, swaps, ping, near_3_8m, held=None,
                       near_cm: float = None, near_name: str = "enemy_3_8m") -> np.ndarray:
    """For finds on no live entity, the first derivation that explains them:
    `held_by_nearer_find` (an entity lies within `near_cm`, but the
    one-to-one join gave it to a nearer find of the same sample: a duplicate),
    `kill_x` (a death earlier in the round within `near_cm` of the victim's
    place: the X [domain:minimap/death-mark-persistence]), `question_swap`
    (within `near_cm` of a T1d swap's place while the "?" lasts
    [domain:minimap/last-known-mark-widget-lifetime]), `ping` (the extras'
    ping class), `enemy_3_8m` (a living enemy 3-8 m away), else `none`.

    `kills` and `swaps`: arrays (n, 4) of (t_from, t_to, x, y) in the find's
    clock and world cm; `ping`, `near_3_8m`: booleans per find."""
    near_cm = NEAR_CM if near_cm is None else near_cm
    fx, fy, ft = (np.asarray(a, float) for a in (fx, fy, ft))
    out = np.array(["none"] * fx.size, dtype=object)

    def hit(ev):
        ev = np.asarray(ev, float).reshape(-1, 4)
        if ev.size == 0 or fx.size == 0:
            return np.zeros(fx.size, bool)
        on = (ft[:, None] >= ev[None, :, 0]) & (ft[:, None] <= ev[None, :, 1])
        d = np.hypot(fx[:, None] - ev[None, :, 2], fy[:, None] - ev[None, :, 3])
        return (on & (d <= near_cm)).any(axis=1)

    held = np.zeros(fx.size, bool) if held is None else np.asarray(held, bool)
    for name, m in ((near_name, np.asarray(near_3_8m, bool)), ("ping", np.asarray(ping, bool)),
                    ("question_swap", hit(swaps)), ("kill_x", hit(kills)), ("held_by_nearer_find", held)):
        out[m] = name                       # later assignments take precedence
    return out


def claim_outcome(desc, *, ambiguous: bool, claimed: bool, drawn=None, name_claim=None,
                  name_truth=None, derivation=None) -> tuple[str, str]:
    """A find's class-aware outcome (`CLASS_OUTCOMES`) for steps 5 to 8,
    where the find claims an entity kind and, perhaps, a name.

    `desc`: the entity the join assigned (None: none); `claimed`: it is of
    the kind the find claims (a teammate, a smoke, an ability child, a death
    X of the claimed side, a "?"). On the claimed kind the find is
    `right_entity` (`name_right` or `name_wrong` by the claimed name against
    the truth's, `unnamed` when the find claims none), or `undrawn_truth`
    where the draw rule says the entity is not drawn (`drawn` False). Any
    other entity is `other_entity:<key>`, or `coverage_gap:<class>:<reason>`
    for an unmapped actor; none is `nothing_there:<derivation>`."""
    if ambiguous:
        return "ambiguous", "ambiguous"
    if desc is None:
        return "nothing_there", f"nothing_there:{derivation or 'none'}"
    if claimed:
        if drawn is False:
            return "undrawn_truth", "undrawn_truth"
        if name_claim is None:
            return "right_entity", "right_entity:unnamed"
        return "right_entity", ("right_entity:name_right" if name_claim == name_truth
                                else "right_entity:name_wrong")
    if desc["kind"] == "child" and str(desc["key"]).startswith("unmapped:"):
        return "coverage_gap", f"coverage_gap:{desc['entity_class']}:{short_reason(desc.get('unmapped_reason'))}"
    return "other_entity", f"other_entity:{desc['key']}"


def drawn_by_fact(facts: dict, agent, ability, side_rel) -> tuple[str, list]:
    """Whether `domain/abilities.toml` says this ability draws on the
    player's minimap from its owner's side (`self`, `ally` or `enemy`):
    `yes`, `no` or `unknown`, with the facts read. The facts are matched by
    subject and fact id alone:

    * `enemy`: a `*-enemy-minimap-*` fact says yes;
    * `self` (the player's own): a `*-minimap-*` fact without `enemy` says
      yes, `*-no-minimap-*` or `*-minimap-none` says no (the demo census
      read the caster's own minimap);
    * `ally` (a teammate's): only a `*-minimap-everyone` fact says yes; the
      caster's-own-minimap facts are not borrowed.

    Nothing is inferred from another ability or another side
    [domain:abilities/ability-rules-are-unique]."""
    if not agent or not ability:
        return "unknown", []

    def norm(s):
        return "".join(ch for ch in str(s).lower() if ch.isalnum())

    want = norm(agent) + ":" + norm(ability)
    mine = [f for f in facts.values() if f.domain == "abilities" and ":" in (f.subject or "")
            and norm(f.subject.split(":", 1)[0]) + ":" + norm(f.subject.split(":", 1)[1]) == want
            and "minimap" in f.id]
    no_ids = [f.key for f in mine if "no-minimap" in f.id or f.id.endswith("minimap-none")]
    if side_rel == "enemy":
        yes = [f.key for f in mine if "enemy-minimap" in f.id and f.key not in no_ids]
        return ("yes", yes) if yes else ("unknown", [])
    if side_rel == "self":
        if no_ids:
            return "no", no_ids
        yes = [f.key for f in mine if "enemy" not in f.id]
        return ("yes", yes) if yes else ("unknown", [])
    yes = [f.key for f in mine if f.id.endswith("minimap-everyone")]
    return ("yes", yes) if yes else ("unknown", [])


# ----------------------------------------------------------------- bootstrap

def _boot_pooled(per_match: list[tuple[np.ndarray, np.ndarray | None]]) -> list:
    """95% interval of a pooled sum (den None) or share, rounds resampled
    within each match and the matches added (`teardrop_refusals` N_BOOT, SEED)."""
    rng = np.random.default_rng(tr.SEED)
    num = np.zeros(tr.N_BOOT)
    den = np.zeros(tr.N_BOOT)
    for a, b in per_match:
        idx = rng.integers(0, len(a), (tr.N_BOOT, len(a)))
        num += a[idx].sum(1)
        if b is not None:
            den += b[idx].sum(1)
    if per_match and per_match[0][1] is None:
        return [int(np.percentile(num, 2.5)), int(np.percentile(num, 97.5))]
    s = num / np.maximum(den, 1)
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def _boot_pooled_diff(per_match: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]) -> list:
    """95% interval of a paired difference of pooled shares, arm A minus arm
    B: each replicate resamples a match's rounds once and scores both arms on
    them (`teardrop_refusals` N_BOOT, SEED). Each item is (num A, den A,
    num B, den B) per round of one match."""
    rng = np.random.default_rng(tr.SEED)
    na, da, nb, db = (np.zeros(tr.N_BOOT) for _ in range(4))
    for a1, b1, a2, b2 in per_match:
        idx = rng.integers(0, len(a1), (tr.N_BOOT, len(a1)))
        na += a1[idx].sum(1)
        da += b1[idx].sum(1)
        nb += a2[idx].sum(1)
        db += b2[idx].sum(1)
    d = na / np.maximum(da, 1) - nb / np.maximum(db, 1)
    return [round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)]


# ----------------------------------------------------------------- the lane

def build_lane(sid: str, tag: str, reality: str = "off") -> tuple[Path, dict]:
    """`enemy_tracks.build` over the tag's rows, written under OUT; returns
    the folder's file and the summary row. `reality` "on" hands the build the
    glyph owner's verdicts, adjudicated in memory from stored rows."""
    from reticle import enemy_tracks
    from reticle.adjudication.ability_glyph import disc_verdicts
    from reticle.adjudication.identity import load_ally_portrait_references
    from reticle.lineup import load_lineup
    from reticle.store import Store

    store = Store(STORE)
    with tr.rows_path(tag, sid).open(encoding="utf-8") as f:
        rows = [json.loads(ln) for ln in f if ln.strip()]
    man = store.read_manifest(sid)
    rounds = store.read_rounds(sid, man["ingested_at"][:10])
    if rounds is None:
        raise SystemExit(f"{sid}: no stored rounds")
    glyph = disc_verdicts(store, sid, compute=True) if reality == "on" else None
    if reality == "on" and glyph.get("skipped"):
        # the glyph owner refuses (stale or missing rows): every track is
        # `unassessed` with the reason, as production would leave it
        print(f"{sid}: reality arm unassessed: {glyph['skipped']}", flush=True)
    res = enemy_tracks.build(sid, rows, rounds.to_pylist(), store.read_events("death", sid) or [],
                             load_lineup(sid, store.root), load_ally_portrait_references(store.root),
                             glyph=glyph)
    p = OUT / tag / f"enemy_track{ARMS[reality]}" / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in res["rows"]:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    os.replace(tmp, p)
    return p, res["rows"][0]


def _prepare(sid: str, tag: str, ptag: str | None, reality: str = "off") -> dict:
    """The lane built over the tag's rows and the T1d join over it: the
    inputs `lane` and `truth_under` share."""
    import enemy_lane_check as elc
    import t1_draw_rule as tdr

    tr.refuse(sid)
    t0 = time.perf_counter()
    p_et, summary = build_lane(sid, tag, reality)
    with p_et.open(encoding="utf-8") as f:
        why_refused = {r["id"]: r.get("reality_reason") for r in map(json.loads, f)
                       if r.get("kind") == "entity" and r.get("reality_status") == "refused"}
    tr._point_store(tag)
    tr._Redirect.streams = {"enemy_track": p_et.parent}
    M = tdr.RealDrawMatch(sid, rule="T1d")
    R = elc.build_sets(sid, M=M)
    J = R["join"]
    E = J["reads"]
    if E["stamp"].get("enemy_track_version") != summary["enemy_track_version"] or \
            E["tracks"] != summary["tracks"]:
        raise SystemExit(f"{sid}: the join read other tracks than the ones built ({E['stamp']})")
    ext = tr.class_extras(sid, tag, R, ptag)
    return {"sid": sid, "tag": tag, "ptag": ptag, "reality": reality, "t0": t0, "summary": summary,
            "why_refused": why_refused, "M": M, "R": R, "J": J, "E": E, "ext": ext}


def _player_desc(M, j: int) -> dict:
    side = "enemy" if j in set(M.ei.tolist()) else "ally"
    ag = M.agent.get(M.sid[j])
    return {"entity_id": f"player:{M.sid[j]}", "kind": "player", "entity_class": "player",
            "family": f"player_{side}", "agent": ag, "ability": None, "tray_key": None,
            "owner": M.sid[j], "side_rel": side, "key": entity_key(f"player_{side}", ag, None),
            "amb_key": f"player_{side}"}


def _child_desc(ct, c: int, me: str) -> dict:
    C = ct.cols
    fam = child_family(C["mapped"][c], C["agent"][c], C["side_rel"][c])
    ab = C["ability"][c] if C["ability"][c] is not None else C["mapped"][c]
    # the spike and the ult orbs are one class whoever holds or owns them
    key = (f"unmapped:{C['cls'][c]}" if fam == "unmapped" else
           entity_key(fam, None if fam in ("spike", "ult_orb") else C["agent"][c], ab))
    side = C["side_rel"][c]
    return {"entity_id": C["entity_id"][c], "kind": "child", "entity_class": C["cls"][c], "family": fam,
            "agent": C["agent"][c], "ability": ab, "tray_key": C["tray_key"][c], "owner": C["subject"][c],
            "side_rel": side, "fact_side": "self" if C["subject"][c] is not None and C["subject"][c] == me
            else side, "key": key, "amb_key": key, "unmapped_reason": C["unmapped_reason"][c]}


def _death_and_swap_marks(M, J) -> tuple[np.ndarray, np.ndarray]:
    """Truth derivations on the grid's clock: each death's X (t_from, t_to,
    x, y: from the last living sample to the round's end, at the victim's
    last living place) and each T1d swap's "?" (from the first undrawn
    sample of a living enemy, for `Q_MARK_MS` or until he is drawn again, at
    his last drawn place)."""
    A = np.asarray(J["alive"], bool)
    D = np.asarray(J["drawn"], bool)
    G, Rn = M.G, M.G_round
    same = np.r_[False, Rn[1:] == Rn[:-1]]
    end_of = {r["round"]: r["t_next"] for r in M.rounds}
    r_end = np.array([end_of.get(int(r), np.inf) for r in Rn], float)
    kills = []
    j, k = np.nonzero(A[:, :-1] & ~A[:, 1:] & same[None, 1:])
    k = k + 1
    kills = np.stack([G[k - 1], r_end[k], M.X[j, k - 1], M.Y[j, k - 1]], 1) if k.size else np.zeros((0, 4))
    # "?" marks: drawn at k-1, undrawn and alive at k, same round
    j2, k2 = np.nonzero(D[:, :-1] & ~D[:, 1:] & A[:, 1:] & same[None, 1:])
    k2 = k2 + 1
    if not k2.size:
        return kills, np.zeros((0, 4))
    K = G.size
    nxt = np.where(D, np.arange(K)[None, :], K)
    nxt = np.minimum.accumulate(nxt[:, ::-1], axis=1)[:, ::-1]        # next drawn sample at or after k
    back = nxt[j2, k2]
    t_back = np.where(back < K, G[np.minimum(back, K - 1)], np.inf)
    t_to = np.minimum(np.minimum(G[k2] + Q_MARK_MS, t_back), r_end[k2])
    swaps = np.stack([G[k2], t_to, M.X[j2, k2 - 1], M.Y[j2, k2 - 1]], 1)
    return kills, swaps


def _join_entities(M, alive, ks, t_rep, fx, fy, frame_key=None, marks: dict | None = None) -> dict:
    """The truth join of `truth_under`, for any finds: find i at grid sample
    `ks[i]`, frame time `t_rep[i]` on the replay clock, world cm (`fx`,
    `fy`). Players are taken at the sample (alive only); every joinable
    `child:` entity within `WINDOW_MS` of the frame and inside its life;
    `marks` (steps 8: truth marks, `_mark_truth`) while the frame lies in
    [t_from - WINDOW_MS, t_to + WINDOW_MS]. One to one by distance within
    `NEAR_CM` per `frame_key` (default: the sample), round by round.

    Returns `col_kind` (`player`, `child`, `mark` or None), `col_idx`,
    `dist`, `win_dt`, `amb_keys`, `held`, the child descriptions and lives,
    and `Dp` (find to each player, NaN where dead)."""
    ct = M.tl0.children
    if ct is None:
        raise SystemExit(f"{M.cap}: T0 carries no children (episodes.from_replay_layer)")
    ks = np.asarray(ks, np.int64)
    t_rep = np.asarray(t_rep, float)
    fx = np.asarray(fx, float)
    fy = np.asarray(fy, float)
    fk = ks if frame_key is None else np.asarray(frame_key, np.int64)
    n = ks.size
    S = M.X.shape[0]
    alive = np.asarray(alive, bool)
    Dp = np.hypot(M.X[:, ks].T - fx[:, None], M.Y[:, ks].T - fy[:, None])
    Dp = np.where(alive[:, ks].T & np.isfinite(Dp), Dp, np.nan)
    # children: life, then the pairs whose life meets the find's window
    end_of = {r["round"]: r["t_next"] for r in M.rounds}         # 1-based: the layer's round + 1
    C = ct.cols
    r_end = np.array([end_of.get(int(r) + 1, np.nan) if np.isfinite(r) else np.nan for r in C["round"]], float)
    me = M.me
    side_f = np.array([("self" if s is not None and s == me else sr) for s, sr in zip(C["subject"], C["side_rel"])],
                      dtype=object)
    lo, hi, flag = child_life(C["cls"], side_f, C["t_open"], C["t_close"], r_end, MEASURED_LIFE)
    has_pos = (C["n_ticks"] > 0) | np.isfinite(C["spawn_x"])
    joinable = np.isfinite(lo) & np.isfinite(hi) & has_pos & ~np.isin(C["cls"].astype(str), list(NOT_JOINED))
    cj = np.flatnonzero(joinable)
    fpair, cpair = [], []
    for a in range(0, n, 512):
        b = min(n, a + 512)
        m = (lo[cj][None, :] <= t_rep[a:b, None] + WINDOW_MS) & (hi[cj][None, :] >= t_rep[a:b, None] - WINDOW_MS)
        f_, c_ = np.nonzero(m)
        fpair.append(f_ + a)
        cpair.append(cj[c_])
    fpair = np.concatenate(fpair) if fpair else np.zeros(0, np.int64)
    cpair = np.concatenate(cpair) if cpair else np.zeros(0, np.int64)
    dch, dt = child_window_dist(ct.position, cpair, t_rep[fpair], fx[fpair], fy[fpair], lo, hi)
    # one-to-one per frame key, round by round (a round's children and marks only)
    descs_c = {}
    col_kind = np.full(n, None, dtype=object)
    col_idx = np.full(n, -1, np.int64)
    dist = np.full(n, np.nan)
    win_dt = np.full(n, np.nan)
    amb_keys = [[] for _ in range(n)]
    held = np.zeros(n, bool)          # unassigned, yet an entity lies within NEAR_CM: a nearer find holds it
    pkeys = [_player_desc(M, j)["amb_key"] for j in range(S)]
    rn = M.G_round[ks]
    for r in np.unique(rn):
        fi = np.flatnonzero(rn == r)
        sel = np.isin(fpair, fi)
        cs = np.unique(cpair[sel])
        mi = np.zeros(0, np.int64) if marks is None else np.flatnonzero(marks["round"] == r)
        colc = {int(c): S + i for i, c in enumerate(cs)}
        row = {int(f): i for i, f in enumerate(fi)}
        Dg = np.full((fi.size, S + cs.size + mi.size), np.nan)
        Dg[:, :S] = Dp[fi]
        Tg = np.full((fi.size, S + cs.size + mi.size), np.nan)
        if sel.any():
            rr = np.array([row[int(f)] for f in fpair[sel]], np.int64)
            cc = np.array([colc[int(c)] for c in cpair[sel]], np.int64)
            Dg[rr, cc] = dch[sel]
            Tg[rr, cc] = dt[sel]
        if mi.size:
            on = ((t_rep[fi][:, None] >= marks["t_from"][mi][None, :] - WINDOW_MS)
                  & (t_rep[fi][:, None] <= marks["t_to"][mi][None, :] + WINDOW_MS))
            dm = np.hypot(fx[fi][:, None] - marks["x"][mi][None, :], fy[fi][:, None] - marks["y"][mi][None, :])
            Dg[:, S + cs.size:] = np.where(on & np.isfinite(dm), dm, np.nan)
        for c in cs:
            if int(c) not in descs_c:
                descs_c[int(c)] = _child_desc(ct, int(c), me)
        keys = pkeys + [descs_c[int(c)]["amb_key"] for c in cs] + \
            ([marks["desc"][int(q)]["amb_key"] for q in mi] if mi.size else [])
        jj, dd = assign_one_to_one(fk[fi], Dg, NEAR_CM)
        amb = ambiguous_classes(Dg, keys)
        cand = np.where(np.isfinite(Dg), Dg <= NEAR_CM, False).any(axis=1)
        for i, f in enumerate(fi):
            amb_keys[f] = amb[i]
            if jj[i] < 0:
                held[f] = bool(cand[i])
                continue
            dist[f] = dd[i]
            if jj[i] < S:
                col_kind[f], col_idx[f] = "player", int(jj[i])
            elif jj[i] < S + cs.size:
                col_kind[f], col_idx[f] = "child", int(cs[jj[i] - S])
                win_dt[f] = Tg[i, jj[i]]
            else:
                col_kind[f], col_idx[f] = "mark", int(mi[jj[i] - S - cs.size])
    return {"Dp": Dp, "lo": lo, "hi": hi, "flag": flag, "joinable": joinable, "descs_c": descs_c,
            "col_kind": col_kind, "col_idx": col_idx, "dist": dist, "win_dt": win_dt, "amb_keys": amb_keys,
            "held": held}


def _truth_under(ctx: dict) -> dict:
    """Every find (accepted icon on a valid sample) with the truth entity
    under it: players through T1d's join at the find's sample, every replay
    child (T0's `children`) within `WINDOW_MS` of the find's frame on the
    replay clock and inside its life; one to one per sample by distance
    within `NEAR_CM`. See the module docstring."""
    import replay_truth as rt
    from reticle.domain import load as load_facts

    sid, M, R, J, E, ext = ctx["sid"], ctx["M"], ctx["R"], ctx["J"], ctx["E"], ctx["ext"]
    MO = E["MO"]
    ks = np.asarray(J["ks"], np.int64)
    ic = np.asarray(J["ic"], np.int64)
    n = ks.size
    p = np.asarray(E["icon_p"], np.int64)[ic]
    t_cap = np.asarray(MO["t_ms"], float)[p]
    t_rep = np.asarray(M.to_rep(t_cap, rt.REMOTE_LAG_MS), float)
    fx = np.asarray(E["icon_x"], float)[ic]
    fy = np.asarray(E["icon_y"], float)[ic]
    ei = set(M.ei.tolist())
    G_ = _join_entities(M, J["alive"], ks, t_rep, fx, fy)
    Dp, lo, hi, flag, joinable = G_["Dp"], G_["lo"], G_["hi"], G_["flag"], G_["joinable"]
    descs_c, col_kind, col_idx, dist = G_["descs_c"], G_["col_kind"], G_["col_idx"], G_["dist"]
    win_dt, amb_keys, held = G_["win_dt"], G_["amb_keys"], G_["held"]
    ct, me = M.tl0.children, M.me
    # derivations for finds on nothing
    kills, swaps = _death_and_swap_marks(M, J)
    nothing = col_kind == None  # noqa: E711
    foe = np.array(sorted(ei), np.int64)
    d_foe = Dp[:, foe] if foe.size else np.full((n, 0), np.nan)
    near38 = np.where(np.isfinite(d_foe), (d_foe > NEAR_CM) & (d_foe <= tr.OFFSET_CM), False).any(axis=1)
    # the ping class, by the extras' own rule (`teardrop_refusals.class_extras`)
    ping = np.zeros(n, bool)
    nf = np.flatnonzero(nothing)
    if nf.size:
        pseudo = [{"nearest_enemy_m": None, "nearest_enemy_alive": False, "t_cap": float(t_cap[f]),
                   "frame_idx": int(MO["frame_idx"][p[f]]),
                   "icon_px": [float(MO["enemy_x"][ic[f]]), float(MO["enemy_y"][ic[f]])], "_f": int(f)}
                  for f in nf]
        for e in tr.class_extras(sid, ctx["tag"], {"info": R["info"], "extras": pseudo}, ctx["ptag"]):
            ping[e["_f"]] = e["cls"] == "ping"
    deriv = np.full(n, None, dtype=object)
    deriv[nothing] = nothing_derivation(fx[nothing], fy[nothing], M.G[ks][nothing], kills, swaps,
                                        ping[nothing], near38[nothing], held[nothing])
    facts = load_facts()
    fact_cache = {}
    old_cls = {(int(e["k"]), int(e["icon"])): e["cls"] for e in ext}
    rows = []
    subj = np.asarray(E["icon_subj"], np.int64)[ic]
    drawn = np.asarray(J["drawn"], bool)
    for f in range(n):
        k = int(ks[f])
        if col_kind[f] == "player":
            d = _player_desc(M, int(col_idx[f]))
            dr = bool(drawn[col_idx[f], k]) if d["side_rel"] == "enemy" else None
            fact, facts_read, life = "n/a", [], None
        elif col_kind[f] == "child":
            d = descs_c[int(col_idx[f])]
            dr = None
            fk = (d["agent"], d["ability"], d["fact_side"])
            if fk not in fact_cache:
                fact_cache[fk] = drawn_by_fact(facts, *fk)
            fact, facts_read = fact_cache[fk]
            life = flag[int(col_idx[f])]
        else:
            d, dr, fact, facts_read, life = None, None, None, [], None
        o, label = outcome_of(col_kind[f], ambiguous=len(amb_keys[f]) >= 2, assigned=d is not None,
                              side_rel=d and d["side_rel"], drawn=dr, subj_named=int(subj[f]),
                              subj_truth=int(col_idx[f]) if col_kind[f] == "player" else None,
                              key=d and d["key"], cls=d and d["entity_class"],
                              unmapped_reason=d and d.get("unmapped_reason"), derivation=deriv[f])
        rows.append({"session": sid, "round": int(M.G_round[k]), "k": k, "frame_idx": int(MO["frame_idx"][p[f]]),
                     "t_cap": round(float(t_cap[f]), 1), "t_rep_frame": round(float(t_rep[f]), 1),
                     "t_rep_sample": round(float(M.G[k]), 1), "icon": int(ic[f]),
                     "icon_px": [round(float(MO["enemy_x"][ic[f]]), 1), round(float(MO["enemy_y"][ic[f]]), 1)],
                     "old_class": old_cls.get((k, int(ic[f])), "hit"),
                     "entity_id": d and d["entity_id"], "entity_class": d and d["entity_class"],
                     "family": d and d["family"], "agent": d and d["agent"], "ability": d and d["ability"],
                     "tray_key": d and d["tray_key"], "owner": d and d["owner"], "side_rel": d and d["side_rel"],
                     "dist_m": None if not np.isfinite(dist[f]) else round(float(dist[f]) / 100, 3),
                     "window_dt_ms": None if not np.isfinite(win_dt[f]) else float(win_dt[f]),
                     "life": life, "t1d_drawn": dr, "drawn_by_fact": fact, "drawn_facts": facts_read,
                     "ambiguous_keys": amb_keys[f] if len(amb_keys[f]) >= 2 else [],
                     "derivation": deriv[f], "outcome": o, "label": label})
    census = _census(ct, joinable, flag, me, facts, fact_cache)
    claims(sid, census)
    return {"rows": rows, "ks": ks, "ic": ic, "t_rep": t_rep, "col_kind": col_kind, "col_idx": col_idx,
            "lo": lo, "hi": hi, "joinable": joinable, "census": census, "descs_c": descs_c,
            "instrument": _instrument(ctx, ks)}


def _census(ct, joinable, flag, me, facts, fact_cache) -> dict:
    """Per child class key in this match: children, side, scored or not and
    why, the drawn-ness fact, and the life flag."""
    out = {}
    for c in range(ct.n):
        d = _child_desc(ct, c, me)
        e = out.setdefault(d["key"], {"family": d["family"], "agent": d["agent"], "ability": d["ability"],
                                      "classes": set(), "children": 0, "joined": 0, "not_joined": Counter(),
                                      "life": set(), "sides": set(), "tray_keys": set()})
        e["classes"].add(str(d["entity_class"]))
        e["tray_keys"].add(str(d["tray_key"]))
        e["sides"].add(str(d["fact_side"]))
        e["children"] += 1
        e["life"].add(str(flag[c]))
        if joinable[c]:
            e["joined"] += 1
        else:
            cls = str(d["entity_class"])
            e["not_joined"][NOT_JOINED.get(cls) or ("no open time" if not np.isfinite(ct.cols["t_open"][c])
                                                    else "no position")] += 1
    for key, e in out.items():
        fk = (e["agent"], e["ability"], sorted(e["sides"])[0])
        if fk not in fact_cache:
            fact_cache[fk] = drawn_by_fact(facts, *fk)
        e["drawn_by_fact"] = fact_cache[fk][0]
        for s in ("classes", "life", "sides", "tray_keys"):
            e[s] = sorted(e[s])
        e["not_joined"] = dict(e["not_joined"])
    for side in ("enemy", "ally"):
        out[f"player_{side}"] = {"family": f"player_{side}", "agent": None, "ability": None,
                                 "classes": ["player"], "children": 0, "joined": 5, "not_joined": {},
                                 "life": ["lives"], "sides": [side], "tray_keys": [], "drawn_by_fact": "n/a"}
    return out


#: The vision streams that claim an entity class, and how each names one.
CLAIMERS = {
    "enemy_track": "enemy players (the enemy lane this harness scores)",
    "ally_icon": "ally players",
    "ability_glyph_name": "a verdict naming `Agent:Slot` claims that agent's children of that tray key",
    "smoke_owner": "a smoke track naming an agent (or none) claims that agent's smoke classes "
                   "(`t1_draw_rule.SMOKES`)",
    "ability_shape": "a shape naming an ability claims that ability's children",
    "spike": "the spike's classes", "plant_graphic": "the planted spike",
    "spike_carrier": "the carried spike item",
}


def claims(sid: str, census: dict) -> None:
    """Add `claimed_by` to each census class: the stored vision streams
    (`CLAIMERS`) whose rows name it, read from the store's own streams."""
    import t1_draw_rule as tdr
    from reticle.agent_names import agent_key

    ev = STORE / "events"

    def rows(stream, needle=None):
        p = ev / stream / f"{sid}.jsonl"
        if not p.is_file():
            return
        with p.open(encoding="utf-8") as f:
            for ln in f:
                if ln.strip() and (needle is None or needle in ln):
                    yield json.loads(ln)

    def norm(s):
        return "".join(ch for ch in str(s).lower() if ch.isalnum())

    tray, smoke, named = set(), set(), set()
    for r in rows("ability_glyph_name", '"verdict"'):
        a = r.get("ability")
        if r.get("kind") == "verdict" and isinstance(a, dict) and a.get("agent") and a.get("slot"):
            tray.add((agent_key(a["agent"]), str(a["slot"])))
    for r in rows("smoke_owner", '"smoke_owner"'):
        if r.get("kind") == "smoke_owner":
            smoke.add(agent_key(r["agent"]) if r.get("agent") else None)
    for r in rows("ability_shape", '"shape"'):
        if r.get("kind") == "shape" and r.get("ability"):
            named.add(norm(r["ability"]))
    have = {s for s in ("enemy_track", "ally_icon", "spike", "spike_carrier", "plant_graphic")
            if (ev / s / f"{sid}.jsonl").is_file()}
    for key, e in census.items():
        by = set()
        fam = e["family"]
        if fam == "player_enemy" and "enemy_track" in have:
            by.add("enemy_track")
        elif fam == "player_ally" and "ally_icon" in have:
            by.add("ally_icon")
        elif fam == "spike":
            want = ("spike", "plant_graphic") if "TimedBomb_C" in e["classes"] else ("spike", "spike_carrier")
            by |= {s for s in want if s in have}
        ak = agent_key(e["agent"]) if e["agent"] else None
        if ak and any((ak, tk) in tray for tk in e["tray_keys"]):
            by.add("ability_glyph_name")
        if any(c in tdr.SMOKES for c in e["classes"]) and (ak in smoke or None in smoke):
            by.add("smoke_owner")
        if e["ability"] and norm(e["ability"]) in named:
            by.add("ability_shape")
        e["claimed_by"] = sorted(by)
        why = "; ".join(e["not_joined"])
        e["scored"] = ("yes" if not why else f"partly ({e['joined']} of {e['children']}): {why}") \
            if e["joined"] else f"no: {why or 'not joined'}"


def _instrument(ctx: dict, ks: np.ndarray) -> dict:
    """The instrument control: the replay layer's enemy px (its own ticks,
    linear between ticks at most `MAX_GAP_MS` apart) at each find's sample
    against the scorer's `enemies_px` (`replay_source.to_px` of T0 at the
    sample, as `enemy_error_budget` stores it), within 1 px; and against the
    stored `enemy_error_budget` rows of this tag where they exist."""
    from reticle.replay_layer import load
    from reticle.replay_source import MAX_GAP_MS, to_px
    import entity_state as es

    sid, M, tag = ctx["sid"], ctx["M"], ctx["tag"]
    L = load(sid)
    E = L.entities
    e_of = {str(E["subject"][e]): int(e) for e in L.players()}
    (mf, _to_m, _mpp), _why = es.world_frame(sid)
    PX, PY = to_px(mf, M.X, M.Y)
    k = np.unique(ks)
    diffs, n = [], 0
    lay = {}
    for j in M.ei:
        T = L.track(e_of[M.sid[j]])
        t = T["t_rep"].astype(float)
        px = np.asarray(T["px"], float)
        py = np.asarray(T["py"], float)
        g = M.G[k]
        i = np.clip(np.searchsorted(t, g, side="right"), 1, t.size - 1)
        ok = (g >= t[i - 1]) & (g <= t[i]) & ((t[i] - t[i - 1]) <= MAX_GAP_MS)
        w = np.clip((g - t[i - 1]) / np.where(t[i] > t[i - 1], t[i] - t[i - 1], 1.0), 0, 1)
        lx = np.where(ok, px[i - 1] * (1 - w) + px[i] * w, np.nan)
        ly = np.where(ok, py[i - 1] * (1 - w) + py[i] * w, np.nan)
        lay[int(j)] = (lx, ly)
        dd = np.hypot(lx - PX[j, k], ly - PY[j, k])
        diffs.append(dd[np.isfinite(dd)])
    d = np.concatenate(diffs) if diffs else np.zeros(0)
    out = {"name": "layer enemy px reproduces the scorer's enemies_px (to_px of T0) within 1 px",
           "n": int(d.size), "max_px": None if not d.size else round(float(d.max()), 3),
           "share_le_1px": None if not d.size else round(float((d <= 1.0).mean()), 4)}
    stored = STORE / "analysis" / "enemy-error-budget-20261007" / tag / f"classed_{sid}.jsonl"
    if stored.is_file():
        pos = {int(kk): i for i, kk in enumerate(k)}
        sd = []
        with stored.open(encoding="utf-8") as f:
            for ln in f:
                r = json.loads(ln)
                kk = r.get("k")
                if kk is None or int(kk) not in pos or not r.get("enemies_px"):
                    continue
                # the stored list holds the living enemies other than the
                # row's own, in M.ei order: each point against the nearest
                # layer enemy at that sample
                i = pos[int(kk)]
                for q in r["enemies_px"]:
                    sd.append(min(math.hypot(lay[int(j)][0][i] - q[0], lay[int(j)][1][i] - q[1])
                                  for j in M.ei))
        sd = np.array([v for v in sd if np.isfinite(v)])
        out["stored"] = {"file": str(stored), "n": int(sd.size),
                         "max_px": None if not sd.size else round(float(sd.max()), 3),
                         "share_le_1px": None if not sd.size else round(float((sd <= 1.0).mean()), 4)}
    out["ok"] = bool(out["share_le_1px"] == 1.0 and (out.get("stored") is None
                                                       or out["stored"]["share_le_1px"] in (None, 1.0)))
    return out


def truth_under(sid: str, tag: str, ptag: str | None = "b1", reality: str = "off") -> dict:
    """Which replay entity lies under each vision find of the tag's enemy
    lane (ownership question `replay-truth-under`, held here while the
    harness is a prototype): one row per find (see `_truth_under`),
    with the instrument control and the match's class census. Evaluation
    only: the replay never feeds a reader."""
    return _truth_under(_prepare(sid, tag, ptag, reality))


def lane(sid: str, tag: str, ptag: str | None, reality: str = "off", ctx: dict | None = None) -> dict:
    ctx = ctx or _prepare(sid, tag, ptag, reality)
    t0, summary, why_refused = ctx["t0"], ctx["summary"], ctx["why_refused"]
    M, R, J, E, ext = ctx["M"], ctx["R"], ctx["J"], ctx["E"], ctx["ext"]
    pairs = R["pairs"]
    rounds = sorted({r["round"] for r in pairs} | {r["round"] for r in R["extras"]})
    ri = {rn: i for i, rn in enumerate(rounds)}
    nr = len(rounds)

    # (a) the reader's true false accepts by lane outcome
    out_icon = icon_outcomes(E["icon_p"], E["icon_eid"], E["icon_subj"], E["track_outcome"])
    fa = [e for e in ext if e["cls"] in tr.TRUE_FA]
    by = {o: np.zeros(nr) for o in OUTCOMES}
    fa_rows = []
    for e in fa:
        o = str(out_icon[e["icon"]])
        by[o][ri[e["round"]]] += 1
        eid = E["icon_eid"][e["icon"]]
        fa_rows.append({**{k: e[k] for k in ("round", "k", "frame_idx", "t_cap", "icon_px", "cls", "icon",
                                             "nearest_enemy_m")},
                        "outcome": o, "track": eid, "agent": E["track_agent"].get(eid),
                        "track_observations": E["track_obs"].get(eid),
                        "reality_reason": why_refused.get(eid)})
    fa_n = np.zeros(nr)
    for e in fa:
        fa_n[ri[e["round"]]] += 1
    # a diagnostic: does a find's track also hold icons T1d places on a drawn
    # living enemy (it joined a real enemy's track), or only extras (its own)?
    extra_icons = np.unique([e["icon"] for e in R["extras"]]).astype(np.int64)
    u_all = np.unique(J["ic"])
    real = u_all[~np.isin(u_all, extra_icons)]
    real_of = Counter(e for e in E["icon_eid"][real] if e is not None)
    for r in fa_rows:
        r["track_real_icons"] = real_of.get(r["track"], 0) if r["track"] is not None else None
    if sum(v.sum() for v in by.values()) != fa_n.sum():
        raise SystemExit(f"{sid}: the outcomes do not sum to the false accepts")
    in_real = np.zeros(nr)
    for e, r in zip(fa, fa_rows):
        in_real[ri[e["round"]]] += r["outcome"].startswith("named") and bool(r["track_real_icons"])

    # (b) questions
    S = M.X.shape[0]
    pk = np.array([r["k"] for r in pairs], np.int64)
    pj = np.array([r["j"] for r in pairs], np.int64)
    Q = lane_questions(J["ks"], J["ic"], pk, pj, E["icon_p"], E["icon_subj"], E["icon_x"], E["icon_y"],
                       M.X, M.Y, J["drawn"], J["alive"], J["p_of"])
    pr = np.array([ri[r["round"]] for r in pairs], np.int64)
    hit = np.array([r["set"] == "hit" for r in pairs], bool)
    ir = np.array([ri.get(int(M.G_round[k]), -1) for k in J["ks"]], np.int64)
    if (ir < 0).any():
        raise SystemExit(f"{sid}: an accepted icon's round has no pair or extra")
    ext_icon = np.zeros(nr)
    for e in R["extras"]:
        ext_icon[ri[e["round"]]] += 1

    def per_round(mask, rr):
        return np.bincount(rr[mask], minlength=nr).astype(float)

    nums = {
        "reader_hit": (per_round(hit, pr), per_round(np.ones_like(hit), pr)),
        "lane_presence": (per_round(Q["pair_named"], pr), per_round(np.ones_like(hit), pr)),
        "lane_position": (per_round(Q["pair_named_pos"], pr), per_round(np.ones_like(hit), pr)),
        "reader_icon_precision": (per_round(np.ones(ir.size, bool), ir) - ext_icon,
                                  per_round(np.ones(ir.size, bool), ir)),
        "lane_named_share": (per_round(Q["icon_named"], ir), per_round(np.ones(ir.size, bool), ir)),
        "lane_presence_precision": (per_round(Q["icon_named_drawn"], ir), per_round(Q["icon_named"], ir)),
        "lane_position_precision": (per_round(Q["icon_named_pos"], ir), per_round(Q["icon_named"], ir)),
    }
    # same-agent duplicates in one frame, over frames holding a named icon
    # (each icon once: two samples can join one frame)
    u_ic = np.unique(J["ic"])
    fp = np.asarray(E["icon_p"], np.int64)[u_ic]
    sj = np.asarray(E["icon_subj"], np.int64)[u_ic]
    nm = sj >= 0
    fr_named = np.unique(fp[nm])
    code, cnt = np.unique(fp[nm] * S + sj[nm], return_counts=True)
    fr_dup = np.unique(code[cnt > 1] // S)
    err = Q["icon_err_cm"][Q["icon_named_drawn"]]
    refused_by = Counter(r["reality_reason"] for r in fa_rows if r["outcome"] == "reality_refused")
    res = {"session": sid, "tag": tag, "version": VERSION, "rule": "T1d", "pings_from": ptag or "store",
           "reality": reality, "detection_reality": summary.get("detection_reality"),
           "detection_reality_version": summary.get("detection_reality_version"),
           "fa_reality_refused_by_reason": dict(refused_by),
           "rounds": nr, "tracks": summary["tracks"], "track_identity": summary["identity"],
           "enemy_track_version": summary["enemy_track_version"],
           "minimap_object_version": summary["minimap_object_version"],
           "lineup_version": summary["lineup_version"],
           "death_adjudication_version": summary["death_adjudication_version"],
           "drops": E["drops"],
           "false_accepts": int(fa_n.sum()), "false_accepts_ci": tr._boot_count(rounds, fa_n),
           "fa_by_outcome": {o: int(v.sum()) for o, v in by.items()},
           "fa_by_outcome_ci": {o: tr._boot_count(rounds, v) for o, v in by.items()},
           "fa_dropped_share": round(float(sum(by[o].sum() for o in DROPPED)) / max(fa_n.sum(), 1), 4),
           "fa_dropped_share_ci": tr._boot_share(rounds, sum(by[o] for o in DROPPED), fa_n),
           "fa_named_in_real_track": int(in_real.sum()),
           "fa_named_in_real_track_ci": tr._boot_count(rounds, in_real),
           "fa_track_obs_median": _median([r["track_observations"] for r in fa_rows]),
           "track_obs_median": _median(list(E["track_obs"].values())),
           "questions": {}, "pairs": int(pk.size), "icons_valid": int(J["ks"].size),
           "named_frames": int(fr_named.size), "dup_frames": int(fr_dup.size),
           "dup_frame_share": round(fr_dup.size / max(fr_named.size, 1), 4),
           "named_err_m_median": None if not err.size else round(float(np.nanmedian(err)) / 100, 3),
           "secs": round(time.perf_counter() - t0, 1)}
    for q, (a, b) in nums.items():
        res["questions"][q] = {"value": round(float(a.sum() / max(b.sum(), 1)), 4),
                               "ci": tr._boot_share(rounds, a, b), "num": int(a.sum()), "den": int(b.sum())}
    stored = tr.OUT / tag / f"score_{sid}.json"
    res["reader_score_file"] = None
    if stored.is_file():
        s = json.loads(stored.read_text(encoding="utf-8"))
        res["reader_score_file"] = {"false_accepts": s["false_accepts"], "hits": s["hits"],
                                    "hit_rate": s["hit_rate"], "pings_from": s.get("pings_from")}
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / tag / f"fa{ARMS[reality]}_{sid}.jsonl", "w", encoding="utf-8") as f:
        for r in fa_rows:
            f.write(json.dumps(r) + "\n")
    # the class-aware lane: every find against every replay entity
    under = _truth_under(ctx)
    cdoc, cper = class_lane(ctx, under, out_icon, ri, nr, rounds)
    res["classes"] = cdoc
    p_cl = OUT / tag / f"classes{ARMS[reality]}_{sid}.jsonl"
    with open(p_cl, "w", encoding="utf-8") as f:
        for r in under["rows"]:
            f.write(json.dumps(r, default=str) + "\n")
    res["_per_round"] = {"fa": fa_n, "by": by, "nums": nums, "in_real": in_real, "rounds": rounds,
                         "classes": cper}
    return res


def _dist(v) -> dict:
    v = np.asarray([x for x in v if x is not None], float)
    if not v.size:
        return {"n": 0}
    return {"n": int(v.size), "median_m": round(float(np.median(v)), 3),
            "p90_m": round(float(np.percentile(v, 90)), 3), "max_m": round(float(v.max()), 3)}


def class_lane(ctx: dict, under: dict, out_icon, ri: dict, nr: int, rounds: list) -> tuple[dict, dict]:
    """The class-aware lane of one session: each find's outcome
    (`CLASS_OUTCOMES`) and label counted per round, the old classes beside
    them, recall per enemy-side class with its own denominator, distance
    distributions, the instrument control and the coverage report. Adds the
    lane's naming to `under["rows"]` in place."""
    import replay_truth as rt

    M, J, E, R = ctx["M"], ctx["J"], ctx["E"], ctx["R"]
    rows = under["rows"]
    n = len(rows)
    for r in rows:
        eid = E["icon_eid"][r["icon"]]
        r["lane_outcome"] = str(out_icon[r["icon"]])
        r["track"] = eid
        r["track_agent"] = E["track_agent"].get(eid) if eid is not None else None
        r["reality_reason"] = ctx["why_refused"].get(eid)
    rr = np.array([ri[r["round"]] for r in rows], np.int64)
    top = np.array([r["outcome"] for r in rows], dtype=object)
    lab = np.array([r["label"] for r in rows], dtype=object)

    def per_round(mask):
        return np.bincount(rr[np.asarray(mask, bool)], minlength=nr).astype(float)

    by_out = {o: per_round(top == o) for o in CLASS_OUTCOMES}
    by_lab = {lb: per_round(lab == lb) for lb in sorted(set(lab.tolist()))}
    if sum(v.sum() for v in by_out.values()) != n:
        raise SystemExit(f"{ctx['sid']}: the class-aware outcomes do not sum to the finds")
    old = np.array([r["old_class"] for r in rows], dtype=object)
    fa = np.isin(old, tr.TRUE_FA)
    lane_o = np.array([r["lane_outcome"] for r in rows], dtype=object)
    cross = Counter((o, t) for o, t in zip(old.tolist(), top.tolist()))
    # recall per enemy-side class, each with its own denominator
    rec = {}
    ks, ci = under["ks"], under["col_idx"]
    kind = under["col_kind"]
    ok = ~np.isin(top, ["ambiguous"])
    got_p = set(zip(ks[ok & (kind == "player")].tolist(), ci[ok & (kind == "player")].tolist()))
    pairs = R["pairs"]
    pk = np.array([p_["k"] for p_ in pairs], np.int64)
    pj = np.array([p_["j"] for p_ in pairs], np.int64)
    pr = np.array([ri[p_["round"]] for p_ in pairs], np.int64)
    hitp = np.array([(int(a), int(b)) in got_p for a, b in zip(pk, pj)], bool)
    rec["player_enemy:drawn (T1d)"] = (np.bincount(pr[hitp], minlength=nr).astype(float),
                                       np.bincount(pr, minlength=nr).astype(float))
    ct = M.tl0.children
    vk = np.flatnonzero(J["valid"])
    MO = E["MO"]
    tv = np.asarray(M.to_rep(np.asarray(MO["t_ms"], float)[J["p_of"][vk]], rt.REMOTE_LAG_MS), float)
    o = np.argsort(tv, kind="stable")
    vk, tv = vk[o], tv[o]
    lo, hi, joinable = under["lo"], under["hi"], under["joinable"]
    enemy_c = np.flatnonzero(joinable & (ct.cols["side_rel"] == "enemy"))
    a = np.searchsorted(tv, lo[enemy_c], side="left")
    b = np.searchsorted(tv, hi[enemy_c], side="right")
    cnt = np.maximum(b - a, 0)
    rep = np.repeat(np.arange(enemy_c.size), cnt)
    idx = np.arange(rep.size) - np.repeat(np.cumsum(cnt) - cnt, cnt) + np.repeat(a, cnt)
    den_k, den_c = vk[idx], enemy_c[rep]
    sel = ok & (kind == "child")
    got_c = np.unique(ks[sel].astype(np.int64) * (ct.n + 1) + ci[sel])
    covered = np.isin(den_k.astype(np.int64) * (ct.n + 1) + den_c, got_c)
    den_r = np.array([ri.get(int(M.G_round[k]), -1) for k in den_k], np.int64)
    keep = den_r >= 0
    keys = np.array([_child_desc(ct, int(c), M.me)["key"] for c in den_c], dtype=object) if den_c.size else \
        np.zeros(0, dtype=object)
    for key in sorted(set(keys.tolist())):
        m = keep & (keys == key)
        rec[key] = (np.bincount(den_r[m & covered], minlength=nr).astype(float),
                    np.bincount(den_r[m], minlength=nr).astype(float))
    fact_of = {r["label"]: r["drawn_by_fact"] for r in rows if r["outcome"] == "other_entity"}
    dists = {o_: _dist([r["dist_m"] for r in rows if r["outcome"] == o_])
             for o_ in ("right_entity", "other_entity", "undrawn_truth", "coverage_gap", "ambiguous")}
    dists["other_entity_child_in_life"] = _dist([r["dist_m"] for r in rows if r["outcome"] == "other_entity"
                                                 and r["family"] not in ("player_ally",)])
    dists["true_fa_other_entity"] = _dist([r["dist_m"] for r, f in zip(rows, fa) if f
                                           and r["outcome"] == "other_entity"])
    census = under["census"]
    gap = Counter(r["label"] for r in rows if r["outcome"] == "coverage_gap")
    doc = {"finds": n, "outcomes": {o_: int(v.sum()) for o_, v in by_out.items()},
           "outcomes_ci": {o_: tr._boot_count(rounds, v) for o_, v in by_out.items()},
           "labels": {lb: int(v.sum()) for lb, v in sorted(by_lab.items(), key=lambda kv: -kv[1].sum())},
           "labels_ci": {lb: tr._boot_count(rounds, v) for lb, v in by_lab.items()},
           "drawn_by_fact": fact_of,
           "true_fa": int(fa.sum()),
           "true_fa_labels": dict(Counter(lab[fa].tolist()).most_common()),
           "true_fa_outcomes": dict(Counter(top[fa].tolist()).most_common()),
           "refused_labels": dict(Counter(lab[lane_o == "reality_refused"].tolist()).most_common()),
           "old_x_new": {f"{a_}|{b_}": v for (a_, b_), v in sorted(cross.items())},
           "ambiguous_keys": dict(Counter(" + ".join(r["ambiguous_keys"]) for r in rows
                                          if r["outcome"] == "ambiguous").most_common(15)),
           "recall": {k_: {"value": round(float(a_.sum() / max(b_.sum(), 1)), 4),
                           "ci": tr._boot_share(rounds, a_, b_), "num": int(a_.sum()), "den": int(b_.sum()),
                           "drawn_by_fact": (census.get(k_) or {}).get("drawn_by_fact")}
                      for k_, (a_, b_) in rec.items()},
           "distances": dists, "instrument": under["instrument"],
           "coverage": {"gap_finds_by_class": dict(gap.most_common()),
                        "census": census,
                        "not_joined": {k_: e["not_joined"] for k_, e in census.items() if e["not_joined"]}}}
    per = {"out": by_out, "lab": by_lab, "rec": rec}
    return doc, per


def _print_classes(scope: str, c: dict, fa: bool = True) -> None:
    print(f"   class-aware ({scope}): {c['finds']} finds", flush=True)
    for o_ in CLASS_OUTCOMES:
        print(f"     {o_:16s} {c['outcomes'][o_]:6d} {c['outcomes_ci'][o_]}", flush=True)
    for lb, v in c["labels"].items():
        if lb.split(":")[0] in ("right_entity", "nothing_there", "coverage_gap") or v >= 3:
            f_ = c.get("drawn_by_fact", {}).get(lb)
            print(f"       {lb:64s} {v:6d} {c['labels_ci'][lb]}" + (f"  drawn_by_fact={f_}" if f_ else ""),
                  flush=True)
    if fa:
        print(f"     old true false accepts {c['true_fa']}: {c['true_fa_outcomes']}", flush=True)
        for lb, v in c["true_fa_labels"].items():
            print(f"       {v:4d} {lb}", flush=True)
    if c.get("refused_labels"):
        print(f"     detection-reality refusals: {c['refused_labels']}", flush=True)
    print("     recall per class (own denominator):", flush=True)
    for k_, v in c["recall"].items():
        print(f"       {k_:56s} {v['value']:.4f} {v['ci']} ({v['num']}/{v['den']}) "
              f"drawn_by_fact={v.get('drawn_by_fact')}", flush=True)
    print(f"     distances {c['distances']}", flush=True)
    if c.get("ambiguous_keys"):
        print(f"     ambiguous by classes {c['ambiguous_keys']}", flush=True)


def _print_coverage(scope: str, cov: dict, instrument=None) -> None:
    print(f"   coverage ({scope}): finds per coverage_gap class {cov['gap_finds_by_class'] or 'none'}", flush=True)
    for k_, e in sorted(cov["census"].items()):
        print(f"     {k_:60s} children {e['children']:4d} claimed_by {e.get('claimed_by') or ['none']} "
              f"scored {e.get('scored')} drawn_by_fact {e['drawn_by_fact']}", flush=True)
    for k_, why in cov["not_joined"].items():
        print(f"     NOT JOINED {k_}: {why}", flush=True)
    if instrument:
        print(f"   instrument: {instrument}", flush=True)


def _median(v):
    v = [x for x in v if x is not None]
    return None if not v else float(np.median(v))


def _print(res: dict) -> None:
    q = res["questions"]
    print(f"{res['session']} {res['tag']} reality {res['reality']}: true false accepts {res['false_accepts']} "
          f"{res['false_accepts_ci']} (teardrop_refusals score: "
          f"{(res.get('reader_score_file') or {}).get('false_accepts')}); refused by reason "
          f"{res['fa_reality_refused_by_reason']}", flush=True)
    for o in OUTCOMES:
        print(f"   {o:24s} {res['fa_by_outcome'][o]:5d} {res['fa_by_outcome_ci'][o]}", flush=True)
    print(f"   dropped share {res['fa_dropped_share']} {res['fa_dropped_share_ci']}; named in a track holding "
          f"T1d-placed icons {res['fa_named_in_real_track']} {res['fa_named_in_real_track_ci']}; "
          f"FA track obs median {res['fa_track_obs_median']} (all tracks {res['track_obs_median']})", flush=True)
    for name in q:
        print(f"   {name:26s} {q[name]['value']:.4f} {q[name]['ci']} ({q[name]['num']}/{q[name]['den']})", flush=True)
    print(f"   duplicate frames {res['dup_frames']}/{res['named_frames']} = {res['dup_frame_share']}; "
          f"named error median {res['named_err_m_median']} m; {res['secs']} s", flush=True)
    if res.get("classes"):
        _print_classes(res["session"], res["classes"])
        _print_coverage(res["session"], res["classes"]["coverage"], res["classes"]["instrument"])


def _pool_classes(per: list[dict], arrays: list[dict]) -> dict:
    """The class-aware lane pooled over sessions: rounds resampled within
    each match and the matches added."""
    cs = [r["classes"] for r in per]
    pa = [a["classes"] for a in arrays]
    out = {"finds": sum(c["finds"] for c in cs),
           "outcomes": {o: sum(c["outcomes"][o] for c in cs) for o in CLASS_OUTCOMES},
           "outcomes_ci": {o: _boot_pooled([(a["out"][o], None) for a in pa]) for o in CLASS_OUTCOMES}}
    labs = sorted({lb for c in cs for lb in c["labels"]})
    z = [np.zeros(len(a["out"][CLASS_OUTCOMES[0]])) for a in pa]
    out["labels"] = dict(sorted({lb: sum(c["labels"].get(lb, 0) for c in cs) for lb in labs}.items(),
                                key=lambda kv: -kv[1]))
    out["labels_ci"] = {lb: _boot_pooled([(a["lab"].get(lb, zz), None) for a, zz in zip(pa, z)]) for lb in labs}
    out["drawn_by_fact"] = {k: v for c in cs for k, v in c["drawn_by_fact"].items()}
    out["true_fa"] = sum(c["true_fa"] for c in cs)
    for k in ("true_fa_labels", "true_fa_outcomes", "refused_labels", "ambiguous_keys", "old_x_new"):
        out[k] = dict(sum((Counter(c[k]) for c in cs), Counter()).most_common())
    keys = sorted({k for a in pa for k in a["rec"]})
    out["recall"] = {}
    for k in keys:
        items = [a["rec"].get(k, (zz, zz)) for a, zz in zip(pa, z)]
        num = sum(x[0].sum() for x in items)
        den = sum(x[1].sum() for x in items)
        fact = next((c["recall"][k].get("drawn_by_fact") for c in cs if k in c["recall"]), None)
        out["recall"][k] = {"value": round(float(num / max(den, 1)), 4), "ci": _boot_pooled(items),
                            "num": int(num), "den": int(den), "drawn_by_fact": fact}
    dist_keys = cs[0]["distances"].keys()
    out["distances"] = {"note": "per session in sessions[*].classes.distances"}
    out["distances"].update({k: [c["distances"][k] for c in cs] for k in dist_keys})
    cen = {}
    for c in cs:
        for k, e in c["coverage"]["census"].items():
            m = cen.setdefault(k, {"children": 0, "claimed_by": set(), "scored": set(), "drawn_by_fact": set(),
                                   "not_joined": Counter()})
            m["children"] += e["children"]
            m["claimed_by"] |= set(e.get("claimed_by") or [])
            m["scored"].add(e.get("scored"))
            m["drawn_by_fact"].add(e["drawn_by_fact"])
            m["not_joined"].update(e["not_joined"])
    for m in cen.values():
        m["claimed_by"] = sorted(m["claimed_by"])
        m["scored"] = " | ".join(sorted(m["scored"]))
        m["drawn_by_fact"] = "/".join(sorted(m["drawn_by_fact"]))
        m["not_joined"] = dict(m["not_joined"])
    out["coverage"] = {"gap_finds_by_class": dict(sum((Counter(c["coverage"]["gap_finds_by_class"]) for c in cs),
                                                      Counter()).most_common()),
                       "census": cen, "not_joined": {k: m["not_joined"] for k, m in cen.items() if m["not_joined"]}}
    out["instrument"] = {c_["session"]: c_["classes"]["instrument"] for c_ in per}
    return out


def run_lane(sessions: list[str], tag: str, ptag: str | None, record: bool,
             reality: str = "off") -> int:
    if reality == "paired":
        return run_paired(sessions, tag, ptag, record)
    for sid in sessions:
        tr.refuse(sid)
    per = [lane(sid, tag, ptag, reality) for sid in sessions]
    _, doc = _pool_lane(per, tag)
    _write_doc(doc, sessions, tag, reality)
    if record:
        _record(doc)
        _record_classes(doc, arm=None if reality == "off" else "reality")
    return 0


def _pool_lane(per: list[dict], tag: str) -> tuple[list[dict], dict]:
    """Print each session's result and the pooled one; returns the per-round
    arrays (popped from the results) and the document."""
    for r in per:
        _print(r)
    pooled = None
    if len(per) > 1:
        fa = [r["_per_round"]["fa"] for r in per]
        pooled = {"sessions": [r["session"] for r in per], "false_accepts": int(sum(a.sum() for a in fa)),
                  "false_accepts_ci": _boot_pooled([(a, None) for a in fa]),
                  "fa_by_outcome": {o: int(sum(r["_per_round"]["by"][o].sum() for r in per)) for o in OUTCOMES},
                  "fa_by_outcome_ci": {o: _boot_pooled([(r["_per_round"]["by"][o], None) for r in per])
                                       for o in OUTCOMES},
                  "questions": {}}
        dropped = [sum(r["_per_round"]["by"][o] for o in DROPPED) for r in per]
        pooled["fa_dropped_share"] = round(float(sum(d.sum() for d in dropped)) / max(pooled["false_accepts"], 1), 4)
        pooled["fa_dropped_share_ci"] = _boot_pooled(list(zip(dropped, fa)))
        inr = [r["_per_round"]["in_real"] for r in per]
        pooled["fa_named_in_real_track"] = int(sum(a.sum() for a in inr))
        pooled["fa_named_in_real_track_ci"] = _boot_pooled([(a, None) for a in inr])
        for q in per[0]["questions"]:
            a = [r["_per_round"]["nums"][q][0] for r in per]
            b = [r["_per_round"]["nums"][q][1] for r in per]
            pooled["questions"][q] = {"value": round(float(sum(x.sum() for x in a) / max(sum(x.sum() for x in b), 1)), 4),
                                      "ci": _boot_pooled(list(zip(a, b))),
                                      "num": int(sum(x.sum() for x in a)), "den": int(sum(x.sum() for x in b))}
        pooled["dup_frames"] = sum(r["dup_frames"] for r in per)
        pooled["named_frames"] = sum(r["named_frames"] for r in per)
        pooled["dup_frame_share"] = round(pooled["dup_frames"] / max(pooled["named_frames"], 1), 4)
        print(f"pooled {tag}: true false accepts {pooled['false_accepts']} {pooled['false_accepts_ci']}", flush=True)
        for o in OUTCOMES:
            print(f"   {o:24s} {pooled['fa_by_outcome'][o]:5d} {pooled['fa_by_outcome_ci'][o]}", flush=True)
        print(f"   dropped share {pooled['fa_dropped_share']} {pooled['fa_dropped_share_ci']}; named in a track "
              f"holding T1d-placed icons {pooled['fa_named_in_real_track']} {pooled['fa_named_in_real_track_ci']}",
              flush=True)
        for name, v in pooled["questions"].items():
            print(f"   {name:26s} {v['value']:.4f} {v['ci']} ({v['num']}/{v['den']})", flush=True)
        print(f"   duplicate frames {pooled['dup_frames']}/{pooled['named_frames']} = {pooled['dup_frame_share']}",
              flush=True)
    arrays = [r.pop("_per_round") for r in per]
    if pooled and all(r.get("classes") for r in per):
        pooled["classes"] = _pool_classes(per, arrays)
        _print_classes("pooled", pooled["classes"])
        _print_coverage("pooled", pooled["classes"]["coverage"], pooled["classes"]["instrument"])
    doc = {"tag": tag, "version": VERSION, "boot": f"{tr.N_BOOT} round resamples, seed {tr.SEED}",
           "reality": per[0]["reality"] if per else None,
           "sessions": {r["session"]: r for r in per}, "pooled": pooled}
    if pooled:
        pooled["fa_reality_refused_by_reason"] = dict(sum(
            (Counter(r["fa_reality_refused_by_reason"]) for r in per), Counter()))
    return arrays, doc


def _write_doc(doc: dict, sessions: list[str], tag: str, reality: str, kind: str = "lane") -> None:
    # the development set writes lane_TAG[_reality].json; any other set names its sessions
    name = (f"{kind}_{tag}{ARMS.get(reality, '_' + reality)}" if sorted(sessions) == sorted(DEV) else
            f"{kind}_{tag}{ARMS.get(reality, '_' + reality)}_{'_'.join(sessions)}")
    (OUT / f"{name}.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")


def run_paired(sessions: list[str], tag: str, ptag: str | None, record: bool) -> int:
    """Both arms, and per question the paired difference on minus off with a
    round bootstrap that resamples the same rounds for both arms."""
    for sid in sessions:
        tr.refuse(sid)
    arms = {}
    for arm in ("off", "on"):
        per = [lane(sid, tag, ptag, arm) for sid in sessions]
        arrays, doc = _pool_lane(per, tag)
        _write_doc(doc, sessions, tag, arm)
        arms[arm] = (arrays, doc)
    (a_off, d_off), (a_on, d_on) = arms["off"], arms["on"]
    for x, y in zip(a_off, a_on):
        if x["rounds"] != y["rounds"]:
            raise SystemExit("the arms resample different rounds; a paired bootstrap needs one set")
    diff = {"sessions": {}, "pooled": {}}
    questions = list(d_on["sessions"][sessions[0]]["questions"])
    for q in questions:
        for i, sid in enumerate(sessions):
            a1, b1 = a_on[i]["nums"][q]
            a2, b2 = a_off[i]["nums"][q]
            v = d_on["sessions"][sid]["questions"][q]["value"] - d_off["sessions"][sid]["questions"][q]["value"]
            diff["sessions"].setdefault(sid, {})[q] = {"diff": round(v, 4),
                                                       "ci": _boot_pooled_diff([(a1, b1, a2, b2)])}
        if len(sessions) > 1:
            v = d_on["pooled"]["questions"][q]["value"] - d_off["pooled"]["questions"][q]["value"]
            diff["pooled"][q] = {"diff": round(v, 4), "ci": _boot_pooled_diff(
                [(a_on[i]["nums"][q][0], a_on[i]["nums"][q][1], a_off[i]["nums"][q][0], a_off[i]["nums"][q][1])
                 for i in range(len(sessions))])}
    print("paired on - off (same resampled rounds):", flush=True)
    for scope, block in [(sid, diff["sessions"][sid]) for sid in sessions] + [("pooled", diff["pooled"])]:
        for q, v in block.items():
            print(f"   {scope:13s} {q:26s} {v['diff']:+.4f} {v['ci']}", flush=True)
    doc = {"tag": tag, "version": VERSION, "boot": f"{tr.N_BOOT} round resamples, seed {tr.SEED}, paired",
           "sessions": sessions, "diff": diff,
           "fa_by_outcome": {"off": (d_off["pooled"] or d_off["sessions"][sessions[0]])["fa_by_outcome"],
                             "on": (d_on["pooled"] or d_on["sessions"][sessions[0]])["fa_by_outcome"]}}
    _write_doc(doc, sessions, tag, "paired", kind="paired")
    if record:
        _record(d_off)
        _record(d_on, arm="reality")
        _record_paired(doc)
        _record_classes(d_off)
        _record_classes(d_on, arm="reality")
    return 0


def _metric_values(r: dict) -> tuple[dict, dict]:
    vals, ci = {"false_accepts": r["false_accepts"], "fa_dropped_share": r["fa_dropped_share"],
                "dup_frame_share": r["dup_frame_share"],
                "fa_named_in_real_track": r["fa_named_in_real_track"]}, {}
    ci["false_accepts"] = r["false_accepts_ci"]
    ci["fa_named_in_real_track"] = r["fa_named_in_real_track_ci"]
    ci["fa_dropped_share"] = r["fa_dropped_share_ci"]
    for o in OUTCOMES:
        vals[f"fa_{o}"] = r["fa_by_outcome"][o]
        ci[f"fa_{o}"] = r["fa_by_outcome_ci"][o]
    for q, v in r["questions"].items():
        vals[q] = v["value"]
        ci[q] = v["ci"]
    return vals, ci


def _record_paired(doc: dict) -> None:
    from reticle.metrics import record as rec
    vals = {f"{q}_diff": v["diff"] for q, v in doc["diff"]["pooled"].items()}
    ci = {f"{q}_diff": v["ci"] for q, v in doc["diff"]["pooled"].items()}
    rec("question_acceptance", part=f"lane/{doc['tag']}/reality-paired", session="dev3", values=vals, ci=ci,
        deps={"version": VERSION, "rule": "T1d"},
        context={"task": "detection-reality-20261007", "boot": doc["boot"], "sessions": doc["sessions"]},
        note="detection_reality on minus off, per question, pooled over the development matches; "
             "one set of resampled rounds scores both arms")


def _record(doc: dict, arm: str | None = None) -> None:
    from reticle.metrics import record as rec
    tag = doc["tag"] + (f"/{arm}" if arm else "")
    for sid, r in doc["sessions"].items():
        vals, ci = _metric_values(r)
        ctl = []
        if r.get("reader_score_file"):
            ctl.append({"name": "reader false accepts reproduce teardrop_refusals score",
                        "observed": r["false_accepts"], "expected": r["reader_score_file"]["false_accepts"],
                        "tol": 0})
        rec("question_acceptance", part=f"lane/{tag}", session=sid, values=vals, ci=ci, controls=ctl,
            deps={"version": VERSION, "rule": "T1d", "enemy_track_version": r["enemy_track_version"],
                  "minimap_object_version": r["minimap_object_version"], "lineup_version": r["lineup_version"],
                  "death_adjudication_version": r["death_adjudication_version"], "pings_from": r["pings_from"]},
            context={"task": TASK, "boot": doc["boot"], "rounds": r["rounds"], "tracks": r["tracks"],
                     "drops": r["drops"]},
            note="enemy_tracks.build over the tag's minimap_object rows; true false accepts (T1d extras "
                 "ping+x_mark+other) by the lane outcome of the track each joined; questions: reader hit "
                 "rate and icon precision beside named-slot presence/position recall and precision")
    if doc["pooled"]:
        vals, ci = _metric_values(doc["pooled"])
        rec("question_acceptance", part=f"lane/{tag}", session="dev3", values=vals, ci=ci,
            deps={"version": VERSION, "rule": "T1d"}, context={"task": TASK, "boot": doc["boot"],
                                                               "sessions": doc["pooled"]["sessions"]},
            note="pooled over the development matches; rounds resampled within each match")


def _record_classes(doc: dict, arm: str | None = None) -> None:
    """The class-aware lane's pooled and per-session values: finds per
    outcome, the old true false accepts per outcome and per drone class, the
    drone classes' recall and the instrument control."""
    from reticle.metrics import record as rec
    tag = doc["tag"] + (f"/{arm}" if arm else "")
    scopes = [(sid, r["classes"]) for sid, r in doc["sessions"].items() if r.get("classes")]
    if doc.get("pooled") and doc["pooled"].get("classes"):
        scopes.append(("dev3", doc["pooled"]["classes"]))
    for scope, c in scopes:
        vals = {"finds": c["finds"], **{o: c["outcomes"][o] for o in CLASS_OUTCOMES},
                "true_fa": c["true_fa"]}
        ci = {o: c["outcomes_ci"][o] for o in CLASS_OUTCOMES}
        for o in CLASS_OUTCOMES:
            vals[f"true_fa_{o}"] = c["true_fa_outcomes"].get(o, 0)
        for lb, v in c["true_fa_labels"].items():
            if lb.startswith("other_entity:ability_enemy:"):
                vals["true_fa_" + lb.split(":", 2)[2].replace(":", "_").replace(" ", "_").lower()] = v
        vals["finds_reality_refused"] = sum(c.get("refused_labels", {}).values())
        for k, v in c["recall"].items():
            if v.get("drawn_by_fact") == "yes" or k.startswith("player_enemy"):
                name = ("recall_player_enemy_drawn" if k.startswith("player_enemy") else
                        "recall_" + k.split(":", 1)[-1].replace(":", "_").replace(" ", "_").lower())
                vals[name] = v["value"]
                ci[name] = v["ci"]
        inst = c["instrument"] if scope != "dev3" else None
        ctl = [] if inst is None else [{"name": inst["name"], "observed": inst["share_le_1px"], "expected": 1.0,
                                        "tol": 0}]
        rec("question_acceptance", part=f"classes/{tag}", session=scope, values=vals, ci=ci, controls=ctl,
            deps={"version": VERSION, "rule": "T1d", "window_ms": WINDOW_MS, "near_cm": NEAR_CM,
                  "ambig_cm": AMBIG_CM, "life_tail_ms": LIFE_TAIL_MS},
            context={"task": "class-aware-harness-20261007", "boot": doc["boot"]},
            note="every find of the tag's enemy lane against every replay entity (truth_under): "
                 "class-aware outcomes, the old true false accepts by outcome and drone class, "
                 "recall per drawn class with its own denominator")


def run_label(sessions: list[str], tag: str, ptag: str | None, reality: str = "off") -> int:
    """`label`: `truth_under` per session, one row per find written to
    OUT/TAG/label[_reality]/SESSION.jsonl, with the label distribution, the
    distances, the instrument control and the coverage report printed."""
    for sid in sessions:
        tr.refuse(sid)
    summary = {}
    for sid in sessions:
        ctx = _prepare(sid, tag, ptag, reality)
        u = _truth_under(ctx)
        rows = u["rows"]
        if len(rows) != int(np.asarray(ctx["J"]["ks"]).size):
            raise SystemExit(f"{sid}: a find has no label row")
        p = OUT / tag / f"label{ARMS[reality]}" / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        labels = Counter(r["label"] for r in rows)
        fams = sorted({r["family"] for r in rows if r["family"]})
        dists = {fm: _dist([r["dist_m"] for r in rows if r["family"] == fm]) for fm in fams}
        fa = Counter(r["label"] for r in rows if r["old_class"] in tr.TRUE_FA)
        summary[sid] = {"finds": len(rows), "labels": dict(labels.most_common()), "distances": dists,
                        "true_fa_labels": dict(fa.most_common()), "instrument": u["instrument"],
                        "census": u["census"], "file": str(p)}
        print(f"{sid} {tag}: {len(rows)} finds -> {p}", flush=True)
        for lb, v in labels.most_common():
            print(f"   {v:6d} {lb}", flush=True)
        print(f"   distances by family {dists}", flush=True)
        print(f"   old true false accepts ({sum(fa.values())}): {dict(fa.most_common())}", flush=True)
        gap = Counter(r["label"] for r in rows if r["outcome"] == "coverage_gap")
        _print_coverage(sid, {"gap_finds_by_class": dict(gap), "census": u["census"],
                              "not_joined": {k: e["not_joined"] for k, e in u["census"].items() if e["not_joined"]}},
                        u["instrument"])
    name = f"label_{tag}{ARMS[reality]}" + ("" if sorted(sessions) == sorted(DEV) else "_" + "_".join(sessions))
    (OUT / f"{name}.json").write_text(json.dumps({"tag": tag, "version": VERSION, "sessions": summary},
                                                 indent=1, default=str), encoding="utf-8")
    return 0


# ----------------------------------------------------------------- steps 5 to 8: other owners' finds

#: Per step: the owner whose emitted rows are scored, the stored stream, the
#: frame stream that sets the samples, and the reader rows reported beside
#: as a diagnostic.
STEP_STREAMS = {
    "ally": {"owner": "round_entities (ownership round-entity-session)", "stream": "round_entity",
             "frames": "ally_icon", "reader": "ally_icon"},
    "smoke": {"owner": "adjudication.smoke_owner (smoke-owner) over adjudication.smokes (minimap-smoke)",
              "stream": "smoke_owner", "frames": "minimap_dark", "reader": "smoke"},
    "glyph": {"owner": "adjudication.ability_glyph (ability-glyph-name)", "stream": "ability_glyph_name",
              "frames": "ability_glyph", "reader": "ability_glyph"},
    "marks": {"owner": "adjudication.death.stored_xmark_births (death-victim) and the enemy lane's "
                       "\"?\" marks (enemy_tracks, last-known-mark)",
              "stream": "the tag's minimap_object rows", "frames": "minimap_object", "reader": "minimap_object"},
}
#: A frame joins the grid sample nearest its replay time within half a grid step.
FRAME_HALF_STEP = 0.5


def _stream(sid: str, stream: str, needle: str | None = None) -> list | None:
    """A stored event stream's rows (those whose line holds `needle`), or None."""
    p = STORE / "events" / stream / f"{sid}.jsonl"
    if not p.is_file():
        return None
    out = []
    with p.open(encoding="utf-8") as f:
        for ln in f:
            if ln.strip() and (needle is None or needle in ln):
                out.append(json.loads(ln))
    return out


def _stream_stamp(sid: str, stream: str) -> dict:
    """The stream head's version fields (its first row), for labelling."""
    p = STORE / "events" / stream / f"{sid}.jsonl"
    if not p.is_file():
        return {"stream": stream, "missing": True}
    with p.open(encoding="utf-8") as f:
        head = json.loads(f.readline())
    return {"stream": stream, **{k: v for k, v in head.items() if k.endswith("_version")}}


def _truth_ctx(sid: str) -> dict:
    """The replay truth on T1d's grid, without any reader: `M`, and `J`'s
    `alive` and `drawn` as `enemy_lane_check.build_sets` builds them."""
    import t1_draw_rule as tdr
    tr.refuse(sid)
    t0 = time.perf_counter()
    M = tdr.RealDrawMatch(sid, rule="T1d")
    return {"sid": sid, "M": M, "J": {"alive": M.alive_grid(), "drawn": M.drawn(M.C)}, "t0": t0}


def _to_cm(sid: str):
    """Widget px to world cm, as `enemy_lane_check.build_sets` converts icons."""
    import entity_state as es
    (_mf, to_m, _mpp), _why = es.world_frame(sid)
    upm = es.units_per_m()

    def f(px, py):
        px = np.asarray(px, float)
        if not px.size:
            return np.zeros(0), np.zeros(0)
        mx, my = to_m(px, np.asarray(py, float))
        return np.asarray(mx, float) * upm, np.asarray(my, float) * upm
    return f


def frame_samples(G, t_rep, ok, half_step_ms: float) -> np.ndarray:
    """Per frame, its grid sample: the nearest within `half_step_ms` of its
    replay time, where `ok` (read, live, inside the capture's spans); one
    frame per sample, the nearest. -1 for a frame that joins none."""
    G = np.asarray(G, float)
    t_rep = np.asarray(t_rep, float)
    out = np.full(t_rep.size, -1, np.int64)
    if not t_rep.size or G.size < 2:
        return out
    i = np.clip(np.searchsorted(G, t_rep), 1, G.size - 1)
    k = np.where(np.abs(G[i - 1] - t_rep) <= np.abs(G[i] - t_rep), i - 1, i)
    dt = np.abs(G[k] - t_rep)
    idx = np.flatnonzero(np.asarray(ok, bool) & (dt <= half_step_ms))
    if idx.size:
        o = idx[np.lexsort((dt[idx], k[idx]))]
        first = np.r_[True, k[o][1:] != k[o][:-1]]
        out[o[first]] = k[o[first]]
    return out


def _frames_on_grid(M, t_cap, read) -> tuple[np.ndarray, np.ndarray]:
    """A stream's frames on the grid (`frame_samples`): (sample per frame,
    replay time per frame), live play only (`enemy_lane_check.live_samples`)."""
    import enemy_lane_check as elc
    import replay_truth as rt
    t_cap = np.asarray(t_cap, float)
    t_rep = np.asarray(M.to_rep(t_cap, rt.REMOTE_LAG_MS), float)
    live, _ = elc.live_samples(M)
    step = float(np.median(np.diff(M.G)))
    i = np.clip(np.searchsorted(M.G, t_rep), 0, M.G.size - 1)
    ok = np.asarray(read, bool) & np.asarray(M.in_spans(t_cap), bool) & live[i]
    k = frame_samples(M.G, t_rep, ok, FRAME_HALF_STEP * step)
    k[(k >= 0) & ~live[np.clip(k, 0, None)]] = -1
    return k, t_rep


def _mark_truth(M, J) -> dict:
    """The marks the replay implies, on the grid's clock, as columns for
    `_join_entities`: each death's X at the victim's last living place from
    his last living sample to the round's end
    [domain:minimap/death-mark-persistence], an ally's always drawn
    [domain:minimap/ally-death-mark], an enemy's drawn where T1d drew him at
    his last living sample (`t1_draw_rule.DrawRule.dead_mark`,
    [domain:minimap/enemy-death-mark]); and each T1d swap's "?" as
    `_death_and_swap_marks` places it."""
    A = np.asarray(J["alive"], bool)
    D = np.asarray(J["drawn"], bool)
    G, Rn = M.G, M.G_round
    same = np.r_[False, Rn[1:] == Rn[:-1]]
    end_of = {r["round"]: r["t_next"] for r in M.rounds}
    r_end = np.array([end_of.get(int(r), np.inf) for r in Rn], float)
    ei = set(M.ei.tolist())
    K = G.size
    j, k = np.nonzero(A[:, :-1] & ~A[:, 1:] & same[None, 1:])
    k = k + 1
    # the X's last sample: the last of its round
    last_of = {}
    for i_, r in enumerate(Rn):
        last_of[int(r)] = i_
    cols = {"t_from": [], "t_to": [], "x": [], "y": [], "round": [], "k_from": [], "k_to": [], "desc": []}

    def add(t_from, t_to, x, y, rnd, k_from, k_to, desc):
        for a, v in (("t_from", t_from), ("t_to", t_to), ("x", x), ("y", y), ("round", rnd), ("k_from", k_from),
                     ("k_to", k_to), ("desc", desc)):
            cols[a].append(v)

    for jj, kk in zip(j.tolist(), k.tolist()):
        side = "enemy" if jj in ei else "ally"
        fam = f"death_x_{side}"
        drawn = bool(D[jj, kk - 1]) if side == "enemy" else True
        ag = M.agent.get(M.sid[jj])
        add(float(G[kk - 1]), float(r_end[kk]), float(M.X[jj, kk - 1]), float(M.Y[jj, kk - 1]), int(Rn[kk]),
            kk - 1, last_of[int(Rn[kk])],
            {"entity_id": f"death_x:{M.sid[jj]}:{kk}", "kind": "mark", "entity_class": "death_x", "family": fam,
             "agent": ag, "ability": None, "tray_key": None, "owner": M.sid[jj], "side_rel": side,
             "key": entity_key(fam, None, None), "amb_key": fam, "drawn": drawn,
             "recall_key": (f"{fam} (always drawn)" if side == "ally" else
                            f"{fam} ({'T1d drawn' if drawn else 'T1d undrawn'} at death)")})
    j2, k2 = np.nonzero(D[:, :-1] & ~D[:, 1:] & A[:, 1:] & same[None, 1:])
    k2 = k2 + 1
    if k2.size:
        nxt = np.where(D, np.arange(K)[None, :], K)
        nxt = np.minimum.accumulate(nxt[:, ::-1], axis=1)[:, ::-1]
        back = nxt[j2, k2]
        t_back = np.where(back < K, G[np.minimum(back, K - 1)], np.inf)
        t_to = np.minimum(np.minimum(G[k2] + Q_MARK_MS, t_back), r_end[k2])
        for jj, kk, tt in zip(j2.tolist(), k2.tolist(), t_to.tolist()):
            ag = M.agent.get(M.sid[jj])
            k_to = int(np.searchsorted(G, tt, side="right") - 1)
            # a "?" stands for its enemy, who stands at its place when it
            # appears: it shares the enemy players' ambiguity class, and the
            # join's distance decides between the mark and a player
            add(float(G[kk]), float(tt), float(M.X[jj, kk - 1]), float(M.Y[jj, kk - 1]), int(Rn[kk]), kk,
                max(k_to, kk),
                {"entity_id": f"question:{M.sid[jj]}:{kk}", "kind": "mark", "entity_class": "last_known",
                 "family": "question_enemy", "agent": ag, "ability": None, "tray_key": None, "owner": M.sid[jj],
                 "side_rel": "enemy", "key": entity_key("question_enemy", None, None), "amb_key": "player_enemy",
                 "drawn": True, "recall_key": "question_enemy (T1d swap)"})
    out = {a: np.asarray(v, float if a in ("t_from", "t_to", "x", "y") else np.int64) for a, v in cols.items()
           if a != "desc"}
    out["desc"] = cols["desc"]
    return out


def _score_finds(ctx: dict, F: dict, *, claimed, name_of=None, drawn_of=None, marks=None,
                 near_side: str = "enemy", frame_key=None) -> tuple[list, dict]:
    """Every find of `F` against every replay entity (`_join_entities`),
    with its outcome (`claim_outcome`). `F`: arrays `k` (grid sample),
    `t_cap`, `t_rep`, `fx`, `fy` (world cm), `px`, `py`, `claim` (the
    claimed name, or None), and `meta` (a dict per find, copied to its row).
    `claimed(desc)`: the entity is of the kind the find claims;
    `name_of(desc)`: its name in the claim's spelling; `drawn_of(desc, k)`:
    whether the draw rule draws it (None: not decided)."""
    from reticle.domain import load as load_facts
    M, J = ctx["M"], ctx["J"]
    ks = np.asarray(F["k"], np.int64)
    n = ks.size
    G_ = _join_entities(M, J["alive"], ks, F["t_rep"], F["fx"], F["fy"], frame_key=frame_key, marks=marks)
    kills, swaps = _death_and_swap_marks(M, J)
    nothing = G_["col_kind"] == None  # noqa: E711
    if near_side == "enemy":
        side = np.asarray(M.ei, np.int64)
    else:
        side = np.array([j for j in M.ci if M.sid[j] != M.me], np.int64)
    d = G_["Dp"][:, side] if side.size else np.full((n, 0), np.nan)
    near38 = np.where(np.isfinite(d), (d > NEAR_CM) & (d <= tr.OFFSET_CM), False).any(axis=1)
    deriv = np.full(n, None, dtype=object)
    if nothing.any():
        deriv[nothing] = nothing_derivation(np.asarray(F["fx"])[nothing], np.asarray(F["fy"])[nothing],
                                            M.G[ks][nothing], kills, swaps, np.zeros(int(nothing.sum()), bool),
                                            near38[nothing], G_["held"][nothing], near_name=f"{near_side}_3_8m")
    if "_facts" not in ctx:
        ctx["_facts"] = load_facts()
    facts = ctx["_facts"]
    fact_cache = ctx.setdefault("_fact_cache", {})
    rows = []
    for f in range(n):
        kind, idx = G_["col_kind"][f], int(G_["col_idx"][f])
        fact, facts_read, life = None, [], None
        if kind == "player":
            desc = _player_desc(M, idx)
            if M.sid[idx] == M.me:
                desc = {**desc, "family": "player_self", "key": entity_key("player_self", desc["agent"], None)}
            fact = "n/a"
        elif kind == "child":
            desc = G_["descs_c"][idx]
            fk = (desc["agent"], desc["ability"], desc["fact_side"])
            if fk not in fact_cache:
                fact_cache[fk] = drawn_by_fact(facts, *fk)
            fact, facts_read = fact_cache[fk]
            life = G_["flag"][idx]
        elif kind == "mark":
            desc = marks["desc"][idx]
            fact = "n/a"
        else:
            desc = None
        is_claimed = desc is not None and bool(claimed(desc))
        dr = drawn_of(desc, int(ks[f])) if (is_claimed and drawn_of is not None) else None
        nt = name_of(desc) if (is_claimed and name_of is not None) else None
        amb = G_["amb_keys"][f]
        o, label = claim_outcome(desc, ambiguous=len(amb) >= 2, claimed=is_claimed, drawn=dr,
                                 name_claim=F["claim"][f], name_truth=nt, derivation=deriv[f])
        k = int(ks[f])
        rows.append({"session": ctx["sid"], "round": int(M.G_round[k]), "k": k,
                     "t_cap": round(float(F["t_cap"][f]), 1), "t_rep_frame": round(float(F["t_rep"][f]), 1),
                     "t_rep_sample": round(float(M.G[k]), 1),
                     "px": [round(float(F["px"][f]), 1), round(float(F["py"][f]), 1)], "claim": F["claim"][f],
                     **(F["meta"][f] if F.get("meta") is not None else {}),
                     "entity_id": desc and desc["entity_id"], "entity_class": desc and desc["entity_class"],
                     "family": desc and desc["family"], "agent": desc and desc["agent"],
                     "ability": desc and desc["ability"], "tray_key": desc and desc["tray_key"],
                     "owner": desc and desc["owner"], "side_rel": desc and desc["side_rel"],
                     "truth_name": nt,
                     "dist_m": None if not np.isfinite(G_["dist"][f]) else round(float(G_["dist"][f]) / 100, 3),
                     "window_dt_ms": None if not np.isfinite(G_["win_dt"][f]) else float(G_["win_dt"][f]),
                     "life": life, "drawn": dr, "drawn_by_fact": fact, "drawn_facts": facts_read,
                     "ambiguous_keys": amb if len(amb) >= 2 else [], "derivation": deriv[f],
                     "outcome": o, "label": label})
    return rows, G_


def _assigned(rows, G_, kind: str) -> set:
    """(sample, column) of the finds the join gave an entity of `kind`, ambiguous finds left out."""
    return {(r["k"], int(G_["col_idx"][i])) for i, r in enumerate(rows)
            if G_["col_kind"][i] == kind and r["outcome"] != "ambiguous"}


def _recall_players(M, J, VK, js, got: set, ri: dict, nr: int) -> tuple[np.ndarray, np.ndarray]:
    """Recall over (sample, player) pairs: samples `VK`, players `js` alive there."""
    VK = np.asarray(VK, np.int64)
    num, den = np.zeros(nr), np.zeros(nr)
    alive = np.asarray(J["alive"], bool)
    for j in js:
        kk = VK[alive[j, VK]]
        r = np.array([ri[int(M.G_round[k])] for k in kk], np.int64)
        hit = np.array([(int(k), int(j)) in got for k in kk], bool)
        den += np.bincount(r, minlength=nr)
        num += np.bincount(r[hit], minlength=nr) if hit.any() else 0
    return num, den


def _recall_children(M, G_, VK, tv, select: np.ndarray, got: set, ri: dict, nr: int,
                     key_of) -> dict:
    """Recall per child class over (sample, live child) pairs, as
    `class_lane` counts them: the valid samples `VK` (frame replay times
    `tv`) inside each selected joinable child's life."""
    ct = M.tl0.children
    o = np.argsort(tv, kind="stable")
    VK, tv = np.asarray(VK, np.int64)[o], np.asarray(tv, float)[o]
    cs = np.flatnonzero(G_["joinable"] & np.asarray(select, bool))
    a = np.searchsorted(tv, G_["lo"][cs], side="left")
    b = np.searchsorted(tv, G_["hi"][cs], side="right")
    cnt = np.maximum(b - a, 0)
    rep = np.repeat(np.arange(cs.size), cnt)
    idx = np.arange(rep.size) - np.repeat(np.cumsum(cnt) - cnt, cnt) + np.repeat(a, cnt)
    den_k, den_c = VK[idx], cs[rep]
    covered = np.array([(int(k), int(c)) in got for k, c in zip(den_k, den_c)], bool)
    den_r = np.array([ri.get(int(M.G_round[k]), -1) for k in den_k], np.int64)
    keep = den_r >= 0
    descs = {}
    keys = np.array([key_of(descs.setdefault(int(c), _child_desc(ct, int(c), M.me))) for c in den_c],
                    dtype=object) if den_c.size else np.zeros(0, dtype=object)
    out = {}
    for key in sorted(set(keys.tolist())):
        m = keep & (keys == key)
        out[key] = (np.bincount(den_r[m & covered], minlength=nr).astype(float),
                    np.bincount(den_r[m], minlength=nr).astype(float))
    return out


def _recall_marks(marks: dict, valid: np.ndarray, got_marks: set, ri: dict, nr: int) -> dict:
    """Recall per mark class over the truth marks whose window holds a valid sample."""
    cs = np.r_[0, np.cumsum(np.asarray(valid, bool))]
    out = {}
    for q, d in enumerate(marks["desc"]):
        a, b = int(marks["k_from"][q]), int(marks["k_to"][q])
        if cs[b + 1] - cs[a] <= 0 or int(marks["round"][q]) not in ri:
            continue
        num, den = out.setdefault(d["recall_key"], (np.zeros(nr), np.zeros(nr)))
        r = ri[int(marks["round"][q])]
        den[r] += 1
        num[r] += q in got_marks
    return out


def _step_summary(rows: list, rec: dict, rounds: list, census: dict | None, extra: dict | None = None) -> tuple:
    """One session's step document in `class_lane`'s shape (so `_pool_classes`
    pools it) and its per-round arrays; the outcomes must sum to the finds."""
    ri = {r: i for i, r in enumerate(rounds)}
    nr = len(rounds)
    n = len(rows)
    rr = np.array([ri[r["round"]] for r in rows], np.int64)
    top = np.array([r["outcome"] for r in rows], dtype=object)
    lab = np.array([r["label"] for r in rows], dtype=object)

    def per_round(mask):
        return np.bincount(rr[np.asarray(mask, bool)], minlength=nr).astype(float) if n else np.zeros(nr)

    by_out = {o: per_round(top == o) for o in CLASS_OUTCOMES}
    by_lab = {lb: per_round(lab == lb) for lb in sorted(set(lab.tolist()))}
    if sum(v.sum() for v in by_out.values()) != n:
        raise SystemExit("the class-aware outcomes do not sum to the finds")
    fact_of = {r["label"]: r["drawn_by_fact"] for r in rows if r["outcome"] == "other_entity"}
    gap = Counter(r["label"] for r in rows if r["outcome"] == "coverage_gap")
    cen = census or {}
    doc = {"finds": n, "outcomes": {o: int(v.sum()) for o, v in by_out.items()},
           "outcomes_ci": {o: tr._boot_count(rounds, v) for o, v in by_out.items()} if nr else {},
           "labels": {lb: int(v.sum()) for lb, v in sorted(by_lab.items(), key=lambda kv: -kv[1].sum())},
           "labels_ci": {lb: tr._boot_count(rounds, v) for lb, v in by_lab.items()},
           "drawn_by_fact": fact_of, "true_fa": 0, "true_fa_labels": {}, "true_fa_outcomes": {},
           "refused_labels": {}, "old_x_new": {},
           "ambiguous_keys": dict(Counter(" + ".join(r["ambiguous_keys"]) for r in rows
                                          if r["outcome"] == "ambiguous").most_common(15)),
           "recall": {k: {"value": round(float(a.sum() / max(b.sum(), 1)), 4), "ci": tr._boot_share(rounds, a, b),
                          "num": int(a.sum()), "den": int(b.sum()),
                          "drawn_by_fact": (cen.get(k.rsplit(" (", 1)[0]) or {}).get("drawn_by_fact")}
                      for k, (a, b) in rec.items()},
           "distances": {o: _dist([r["dist_m"] for r in rows if r["outcome"] == o])
                         for o in ("right_entity", "other_entity", "undrawn_truth", "coverage_gap", "ambiguous")},
           "instrument": {},
           "coverage": {"gap_finds_by_class": dict(gap.most_common()), "census": cen,
                        "not_joined": {k: e["not_joined"] for k, e in cen.items() if e.get("not_joined")}}}
    if extra:
        doc.update(extra)
    return doc, {"out": by_out, "lab": by_lab, "rec": rec}


def _session_census(ctx: dict, G_) -> dict:
    """The match's class census and claims (`_census`, `claims`)."""
    from reticle.domain import load as load_facts
    M = ctx["M"]
    if "_facts" not in ctx:
        ctx["_facts"] = load_facts()
    census = _census(M.tl0.children, G_["joinable"], G_["flag"], M.me, ctx["_facts"],
                     ctx.setdefault("_fact_cache", {}))
    claims(ctx["sid"], census)
    return census


def _empty_join(ctx: dict) -> dict:
    """`_join_entities` over no finds: the child lives and the census inputs."""
    return _join_entities(ctx["M"], ctx["J"]["alive"], np.zeros(0, np.int64), np.zeros(0), np.zeros(0), np.zeros(0))


def _finds(k, t_cap, t_rep, px, py, to_cm, claim, meta) -> dict:
    fx, fy = to_cm(px, py)
    return {"k": np.asarray(k, np.int64), "t_cap": np.asarray(t_cap, float), "t_rep": np.asarray(t_rep, float),
            "px": np.asarray(px, float), "py": np.asarray(py, float), "fx": fx, "fy": fy,
            "claim": list(claim), "meta": list(meta)}


def _claim_key(a) -> str | None:
    from reticle.agent_names import agent_key
    return agent_key(a) if a else None


# step 5: ally finds -------------------------------------------------------------------------------------

def step_ally(sid: str) -> dict:
    """Step 5: the teammates `round_entities` emits (`round_entity`
    observations of the ally family, each bound to an entity whose `agent`
    the arbiter resolved), at one sample per `ally_icon` frame where the
    widget is drawn. Right entity: the teammate the find claims, by the
    entity's resolved agent (`unnamed` where the arbiter abstained). The
    reader's own icons (`ally_icon` rows of the ally family) are scored
    beside, unnamed, as a diagnostic. The self family is the self-icon
    owner's and is left out."""
    ctx = _truth_ctx(sid)
    M = ctx["M"]
    to_cm = _to_cm(sid)
    fr = [r for r in (_stream(sid, "ally_icon", '"kind":"frame"') or []) if r.get("kind") == "frame"]
    if not fr:
        raise SystemExit(f"{sid}: no ally_icon frames")
    fr.sort(key=lambda r: r["t_ms"])
    t_f = np.array([r["t_ms"] for r in fr], float)
    k_f, trep_f = _frames_on_grid(M, t_f, [bool(r.get("widget_drawn")) for r in fr])
    on = k_f >= 0
    at = {int(fr[i]["frame_idx"]): i for i in np.flatnonzero(on)}
    RE = _stream(sid, "round_entity") or []
    agent_of = {r["id"]: (_claim_key(r.get("agent")) if r.get("identity_status") == "resolved" else None)
                for r in RE if r.get("kind") == "entity"}
    status_of = {r["id"]: r.get("identity_status") for r in RE if r.get("kind") == "entity"}
    obs_all = [r for r in RE if r.get("kind") == "observation" and r.get("family") == "ally"]
    unbound = sum(1 for r in obs_all if not r.get("entity_id"))
    obs = [r for r in obs_all if r.get("entity_id") and int(r["frame_idx"]) in at]
    i_ = np.array([at[int(r["frame_idx"])] for r in obs], np.int64)
    F = _finds(k_f[i_] if i_.size else [], t_f[i_] if i_.size else [], trep_f[i_] if i_.size else [],
               [r["x"] for r in obs], [r["y"] for r in obs], to_cm,
               [agent_of.get(r["entity_id"]) for r in obs],
               [{"entity": r["entity_id"], "identity_status": status_of.get(r["entity_id"]), "state": r.get("state"),
                 "frame_idx": int(r["frame_idx"])} for r in obs])
    ally_js = [int(j) for j in M.ci if M.sid[j] != M.me]

    def claimed(d):
        return d["family"] == "player_ally"

    def name_of(d):
        return _claim_key(d["agent"])

    rows, G_ = _score_finds(ctx, F, claimed=claimed, name_of=name_of, near_side="ally")
    # the reader's icons, unnamed
    icons = [r for r in (_stream(sid, "ally_icon", '"kind":"icon"') or [])
             if r.get("kind") == "icon" and r.get("family") == "ally" and int(r["frame_idx"]) in at]
    j_ = np.array([at[int(r["frame_idx"])] for r in icons], np.int64)
    Fr = _finds(k_f[j_] if j_.size else [], t_f[j_] if j_.size else [], trep_f[j_] if j_.size else [],
                [r["cx"] for r in icons], [r["cy"] for r in icons], to_cm, [None] * len(icons),
                [{"frame_idx": int(r["frame_idx"]), "reason": r.get("reason")} for r in icons])
    rrows, G_r = _score_finds(ctx, Fr, claimed=claimed, name_of=name_of, near_side="ally")
    VK = k_f[on]
    rounds = sorted({int(M.G_round[k]) for k in VK})
    ri = {r: i for i, r in enumerate(rounds)}
    nr = len(rounds)
    rec = {"player_ally (live)": _recall_players(M, ctx["J"], VK, ally_js, _assigned(rows, G_, "player"), ri, nr)}
    rrec = {"player_ally (live)": _recall_players(M, ctx["J"], VK, ally_js, _assigned(rrows, G_r, "player"), ri, nr)}
    census = _session_census(ctx, G_)
    stamps = [_stream_stamp(sid, s) for s in ("round_entity", "ally_icon")]
    doc, per = _step_summary(rows, rec, rounds, census, {"stamps": stamps, "unbound_observations": unbound,
                                                        "frames": int(len(fr)), "frames_on_grid": int(on.sum())})
    rdoc, rper = _step_summary(rrows, rrec, rounds, census)
    return {"session": sid, "step": "ally", "rows": rows, "reader_rows": rrows, "classes": doc, "reader": rdoc,
            "_per": per, "_rper": rper, "secs": round(time.perf_counter() - ctx["t0"], 1)}


# step 6: smokes ----------------------------------------------------------------------------------------

def step_smoke(sid: str) -> dict:
    """Step 6: the smokes `adjudication.smoke_owner` emits (`smoke_owner`
    rows, one per `smoke` track, each with the agent it names), one find per
    track at each sample of a read `minimap_dark` frame inside the track's
    observed life. Right entity: a replay smoke child (`t1_draw_rule.SMOKES`
    classes) of the named agent. Enemy smokes are not drawn
    [domain:abilities/enemy-smokes-not-on-minimap]; their recall is listed
    apart. The `smoke` tracks place the same smokes unnamed; the owner adds
    only the name, so the diagnostic is the unnamed count."""
    import t1_draw_rule as tdr
    ctx = _truth_ctx(sid)
    M = ctx["M"]
    to_cm = _to_cm(sid)
    fr = [r for r in (_stream(sid, "minimap_dark", '"kind":"frame"') or []) if r.get("kind") == "frame"]
    fr.sort(key=lambda r: r["t_ms"])
    t_f = np.array([r["t_ms"] for r in fr], float)
    k_f, trep_f = _frames_on_grid(M, t_f, [r.get("reason") is None and bool(r.get("widget_drawn", True))
                                           for r in fr])
    on = np.flatnonzero(k_f >= 0)
    SO = [r for r in (_stream(sid, "smoke_owner", '"kind":"smoke_owner"') or []) if r.get("kind") == "smoke_owner"]
    n_tracks = sum(1 for r in (_stream(sid, "smoke", '"kind":"track"') or []) if r.get("kind") == "track")
    ii, tt = [], []
    for t_i, r in enumerate(SO):
        m = on[(t_f[on] >= r["first_ms"]) & (t_f[on] <= r["last_ms"])]
        ii.extend(m.tolist())
        tt.extend([t_i] * m.size)
    ii = np.asarray(ii, np.int64)
    F = _finds(k_f[ii] if ii.size else [], t_f[ii] if ii.size else [], trep_f[ii] if ii.size else [],
               [SO[t]["cx"] for t in tt], [SO[t]["cy"] for t in tt], to_cm,
               # the owner names the ally caster ("Which ally agent cast this minimap smoke?")
               [("ally:" + _claim_key(SO[t]["agent"]) if SO[t].get("identity_status") == "resolved" else None)
                for t in tt],
               [{"smoke": SO[t]["entity_id"], "identity_status": SO[t].get("identity_status"),
                 "owner_reason": SO[t].get("reason")} for t in tt])
    smoke_cls = set(tdr.SMOKES)

    def claimed(d):
        return d["kind"] == "child" and str(d["entity_class"]) in smoke_cls

    def name_of(d):
        return f"{d['side_rel']}:{_claim_key(d['agent'])}"

    rows, G_ = _score_finds(ctx, F, claimed=claimed, name_of=name_of, near_side="ally")
    VK = k_f[on]
    rounds = sorted({int(M.G_round[k]) for k in VK})
    ri = {r: i for i, r in enumerate(rounds)}
    C = M.tl0.children.cols
    sel = np.isin(C["cls"].astype(str), list(smoke_cls))
    rec = _recall_children(M, G_, VK, trep_f[on], sel, _assigned(rows, G_, "child"), ri, len(rounds),
                           key_of=lambda d: f"{d['key']} (smoke)")
    census = _session_census(ctx, G_)
    stamps = [_stream_stamp(sid, s) for s in ("smoke_owner", "smoke", "minimap_dark")]
    doc, per = _step_summary(rows, rec, rounds, census,
                             {"stamps": stamps, "tracks": len(SO), "smoke_tracks": n_tracks,
                              "tracks_named": sum(1 for r in SO if r.get("identity_status") == "resolved"),
                              "frames": int(len(fr)), "frames_on_grid": int(on.size)})
    if len(SO) != n_tracks:
        print(f"{sid}: smoke_owner rows {len(SO)} differ from smoke tracks {n_tracks}", flush=True)
    return {"session": sid, "step": "smoke", "rows": rows, "classes": doc, "_per": per,
            "secs": round(time.perf_counter() - ctx["t0"], 1)}


# step 7: ability glyphs --------------------------------------------------------------------------------

def step_glyph(sid: str) -> dict:
    """Step 7: the glyph owner's verdicts (`ability_glyph_name`, each naming
    `Agent:Slot` or abstaining with a reason) on their disc tracks'
    fixes (`ability_disc_track`), one find per fix at the sample of its
    `ability_glyph` frame. Right entity: a replay ability child (either
    side) of the named agent and tray key. The reader's discs
    (`ability_glyph` disc rows) are scored beside, unnamed. A session
    without a stored verdict stream takes the owner's verdicts adjudicated
    in memory (`disc_verdicts(compute=True)`), or none with the owner's
    refusal."""
    from reticle.adjudication.ability_glyph import disc_verdicts
    from reticle.store import Store
    ctx = _truth_ctx(sid)
    M = ctx["M"]
    to_cm = _to_cm(sid)
    rows_g = _stream(sid, "ability_glyph") or []
    fr = sorted((r for r in rows_g if r.get("kind") == "frame"), key=lambda r: r["t_ms"])
    t_f = np.array([r["t_ms"] for r in fr], float)
    k_f, trep_f = _frames_on_grid(M, t_f, [r.get("reason") in (None, "read") for r in fr])
    on = np.flatnonzero(k_f >= 0)
    at = {round(float(t_f[i]), 1): i for i in on}
    tracks = [r for r in (_stream(sid, "ability_disc_track") or []) if r.get("kind") == "track"]
    verdicts = {r["track"]: r for r in (_stream(sid, "ability_glyph_name") or []) if r.get("kind") == "verdict"}
    source, refusal = "stored", None
    if not verdicts:
        g = disc_verdicts(Store(STORE), sid, compute=True)
        if g.get("skipped"):
            source, refusal = "none", str(g["skipped"])
        else:
            source = "computed in memory (no stored stream)"
            tracks = g["tracks"]
            verdicts = {t: v for t, v in g["verdicts"].items()}
    ii, meta, px, py, claim = [], [], [], [], []
    for t in tracks:
        v = verdicts.get(t["track"]) or {}
        ab = v.get("ability")
        cl = f"{_claim_key(ab['agent'])}:{ab['slot']}" if isinstance(ab, dict) and ab.get("agent") else None
        fx_ = t.get("fix") or {}
        for tm, cx, cy in zip(fx_.get("t_ms", []), fx_.get("cx", []), fx_.get("cy", [])):
            i = at.get(round(float(tm), 1))
            if i is None:
                continue
            ii.append(i)
            px.append(cx)
            py.append(cy)
            claim.append(cl)
            meta.append({"track": t["track"], "verdict_reason": v.get("reason"), "rule": v.get("rule")})
    ii = np.asarray(ii, np.int64)
    F = _finds(k_f[ii] if ii.size else [], t_f[ii] if ii.size else [], trep_f[ii] if ii.size else [],
               px, py, to_cm, claim, meta)

    def claimed(d):
        return d["kind"] == "child" and str(d["family"]).startswith("ability_")

    def name_of(d):
        return f"{_claim_key(d['agent'])}:{d['tray_key']}"

    rows, G_ = _score_finds(ctx, F, claimed=claimed, name_of=name_of, near_side="ally")
    discs = [r for r in rows_g if r.get("kind") == "disc" and round(float(r["t_ms"]), 1) in at]
    jj = np.array([at[round(float(r["t_ms"]), 1)] for r in discs], np.int64)
    Fr = _finds(k_f[jj] if jj.size else [], t_f[jj] if jj.size else [], trep_f[jj] if jj.size else [],
                [r["cx"] for r in discs], [r["cy"] for r in discs], to_cm, [None] * len(discs),
                [{"disc": r.get("disc"), "set": r.get("set"), "reason": r.get("reason")} for r in discs])
    rrows, G_r = _score_finds(ctx, Fr, claimed=claimed, name_of=name_of, near_side="ally")
    VK = k_f[on]
    rounds = sorted({int(M.G_round[k]) for k in VK})
    ri = {r: i for i, r in enumerate(rounds)}
    fam = np.array([child_family(m, a, s) for m, a, s in zip(M.tl0.children.cols["mapped"],
                                                             M.tl0.children.cols["agent"],
                                                             M.tl0.children.cols["side_rel"])], dtype=object)
    sel = np.array([str(f_).startswith("ability_") for f_ in fam], bool)
    # an owner that refused the session emitted nothing: its pairs are no
    # misses, and the refusal stands in the document instead
    rec = {} if source == "none" else _recall_children(M, G_, VK, trep_f[on], sel, _assigned(rows, G_, "child"),
                                                       ri, len(rounds), key_of=lambda d: d["key"])
    rrec = _recall_children(M, G_r, VK, trep_f[on], sel, _assigned(rrows, G_r, "child"), ri, len(rounds),
                            key_of=lambda d: d["key"])
    census = _session_census(ctx, G_)
    stamps = [_stream_stamp(sid, s) for s in ("ability_glyph_name", "ability_disc_track", "ability_glyph")]
    extra = {"stamps": stamps, "verdict_source": source, "verdict_refusal": refusal, "tracks": len(tracks),
             "tracks_named": sum(1 for v in verdicts.values() if isinstance(v.get("ability"), dict)),
             "frames": int(len(fr)), "frames_on_grid": int(on.size),
             "claims": dict(Counter(c for c in claim if c).most_common(20))}
    doc, per = _step_summary(rows, rec, rounds, census, extra)
    rdoc, rper = _step_summary(rrows, rrec, rounds, census)
    return {"session": sid, "step": "glyph", "rows": rows, "reader_rows": rrows, "classes": doc, "reader": rdoc,
            "_per": per, "_rper": rper, "secs": round(time.perf_counter() - ctx["t0"], 1)}


# step 8: X and "?" marks -------------------------------------------------------------------------------

def step_marks(sid: str, tag: str, ptag: str | None) -> dict:
    """Step 8: the marks the owners emit over the tag's `minimap_object`
    rows, against the replay's deaths and T1d's swaps (`_mark_truth`):

    * X marks: the death owner's births (`adjudication.death.stored_xmark_births`
      over the tag's rows and the stored `ally_icon`), one find per birth,
      claiming a death X of the birth's side;
    * "?" marks: the enemy lane's `mark` rows (`enemy_tracks.build` over the
      tag's rows, as `lane` builds it), one find per mark at its onset,
      claiming a "?" named by the track it binds.

    One to one per round. Right entity: a truth mark of the claimed kind
    (`name_right`/`name_wrong` for a "?" by the track's agent; an X claims
    no name, so `unnamed`), `undrawn_truth` on an enemy death T1d did not
    draw at its last living sample. The reader's per-frame X detections and
    "?" detections are scored beside as a diagnostic."""
    from reticle.adjudication.death import stored_xmark_births
    from reticle.store import Store
    ctx = _prepare(sid, tag, ptag, "off")
    M, J = ctx["M"], ctx["J"]
    to_cm = _to_cm(sid)
    store = Store(STORE)
    with tr.rows_path(tag, sid).open(encoding="utf-8") as f:
        mo = [json.loads(ln) for ln in f if ln.strip()]
    head = next(r for r in mo if r.get("kind") == "coverage")
    frames = sorted((r for r in mo if r.get("kind") == "frame"), key=lambda r: r["t_ms"])
    man = store.read_manifest(sid)
    rounds_s = store.read_rounds(sid, man["ingested_at"][:10]).to_pylist()
    births = stored_xmark_births(mo, store.read_events("ally_icon", sid) or [], rounds_s,
                                 float(head.get("scale") or 1.0))
    t_f = np.array([r["t_ms"] for r in frames], float)
    k_f, trep_f = _frames_on_grid(M, t_f, [r.get("reason") is None for r in frames])
    marks = _mark_truth(M, J)
    with (OUT / tag / "enemy_track" / f"{sid}.jsonl").open(encoding="utf-8") as f:
        lane_rows = [json.loads(ln) for ln in f if ln.strip()]
    q_marks = [r for r in lane_rows if r.get("kind") == "mark"]
    agent_of = {r["id"]: (r.get("agent") if r.get("identity_status") == "resolved" else None)
                for r in lane_rows if r.get("kind") == "entity"}
    import enemy_lane_check as elc
    import replay_truth as rt
    live, _ = elc.live_samples(M)
    step = float(np.median(np.diff(M.G)))

    def at_time(t_cap):
        t_cap = np.asarray(t_cap, float)
        t_rep = np.asarray(M.to_rep(t_cap, rt.REMOTE_LAG_MS), float) if t_cap.size else np.zeros(0)
        k = np.clip(np.searchsorted(M.G, t_rep), 0, max(M.G.size - 1, 0))
        k = np.where((k > 0) & (np.abs(M.G[np.maximum(k - 1, 0)] - t_rep) < np.abs(M.G[k] - t_rep)), k - 1, k)
        ok = (np.abs(M.G[k] - t_rep) <= FRAME_HALF_STEP * step) & live[k] if t_cap.size else np.zeros(0, bool)
        return k, t_rep, ok

    kx, tx, okx = at_time([b["t_ms"] for b in births])
    kq, tq, okq = at_time([m["onset_ms"] for m in q_marks])
    bx = [b for b, o in zip(births, okx) if o]
    qm = [m for m, o in zip(q_marks, okq) if o]
    Fx = _finds(kx[okx], [b["t_ms"] for b in bx], tx[okx], [b["x"] for b in bx], [b["y"] for b in bx], to_cm,
                [None] * len(bx), [{"mark": "x", "side": b["side"], "frames": b["frames"],
                                     "icon_last_ms": b["icon_last_ms"]} for b in bx])
    Fq = _finds(kq[okq], [m["onset_ms"] for m in qm], tq[okq], [m["x"] for m in qm], [m["y"] for m in qm], to_cm,
                [(_claim_key(agent_of.get(m["entity_id"])) if m.get("entity_id") else None) for m in qm],
                [{"mark": "question", "track": m.get("entity_id"), "binding_reason": m.get("binding_reason"),
                  "detections": m.get("detections"), "last_ms": m.get("last_ms")} for m in qm])
    F = {key: (np.r_[Fx[key], Fq[key]] if key not in ("claim", "meta") else Fx[key] + Fq[key]) for key in Fx}
    side_of = [m["side"] if m["mark"] == "x" else "question" for m in F["meta"]]

    def claimed_for(i):
        def c(d):
            if d["kind"] != "mark":
                return False
            if side_of[i] == "question":
                return d["family"] == "question_enemy"
            return d["family"] == f"death_x_{side_of[i]}"
        return c

    # the claim differs per find: score each claim kind apart, then merge in find order
    rows = [None] * len(F["meta"])
    G_all = {}
    for kind_ in ("ally", "enemy", "question"):
        sel = [i for i, s in enumerate(side_of) if s == kind_]
        if not sel:
            continue
        Fs = {key: ([F[key][i] for i in sel] if key in ("claim", "meta") else np.asarray(F[key])[sel]) for key in F}
        rs, G_ = _score_finds(ctx, Fs, claimed=claimed_for(sel[0]),
                              name_of=lambda d: _claim_key(d["agent"]) if d["family"] == "question_enemy" else None,
                              drawn_of=lambda d, k: d["drawn"], marks=marks, near_side="enemy")
        hold_duplicate_marks(rs, G_["col_kind"], G_["col_idx"])
        G_all[kind_] = (sel, G_, rs)
        for i, r in zip(sel, rs):
            rows[i] = r
    got = set()
    for sel, G_, rs in G_all.values():
        for i, r in enumerate(rs):
            # a mark is recalled by a find that claims its kind: an X that
            # lies on a "?" recalls neither
            if G_["col_kind"][i] == "mark" and r["outcome"] in ("right_entity", "undrawn_truth"):
                got.add(int(G_["col_idx"][i]))
    valid = np.asarray(J["valid"], bool)
    rounds = sorted({int(r) for r in M.G_round[valid]} | {r["round"] for r in rows})
    ri = {r: i for i, r in enumerate(rounds)}
    rec = _recall_marks(marks, valid, got, ri, len(rounds))
    # the reader's per-frame detections, unnamed: red and blue X, and "?"
    rf, rx, ry, rt_, rm = [], [], [], [], []
    for i in np.flatnonzero(k_f >= 0):
        fr_ = frames[i]
        for colour in ("red", "blue"):
            for q in (fr_.get("x_marks") or {}).get(colour, []):
                rf.append(i)
                rx.append(q["x"])
                ry.append(q["y"])
                rm.append({"mark": "x", "side": "enemy" if colour == "red" else "ally"})
        for q in fr_.get("questions") or []:
            rf.append(i)
            rx.append(q["x"])
            ry.append(q["y"])
            rm.append({"mark": "question", "side": "question"})
    rf = np.asarray(rf, np.int64)
    Fr = _finds(k_f[rf] if rf.size else [], t_f[rf] if rf.size else [], trep_f[rf] if rf.size else [], rx, ry,
                to_cm, [None] * len(rm), rm)
    rrows = [None] * len(rm)
    for kind_ in ("ally", "enemy", "question"):
        sel = [i for i, m in enumerate(rm) if m["side"] == kind_]
        if not sel:
            continue
        Fs = {key: ([Fr[key][i] for i in sel] if key in ("claim", "meta") else np.asarray(Fr[key])[sel]) for key in Fr}
        fam = "question_enemy" if kind_ == "question" else f"death_x_{kind_}"
        rs, _G = _score_finds(ctx, Fs, claimed=lambda d, fam=fam: d["kind"] == "mark" and d["family"] == fam,
                              drawn_of=lambda d, k: d["drawn"], marks=marks, near_side="enemy")
        for i, r in zip(sel, rs):
            rrows[i] = r
    census = _session_census(ctx, _empty_join(ctx))
    extra = {"stamps": [{"rows": str(tr.rows_path(tag, sid)), "minimap_object_version":
                         head.get("minimap_object_version")}, _stream_stamp(sid, "ally_icon"),
                        _stream_stamp(sid, "death")],
             "births": len(births), "births_on_grid": len(bx), "question_marks": len(q_marks),
             "question_marks_on_grid": len(qm),
             "truth_marks": dict(Counter(d["recall_key"] for d in marks["desc"])),
             "by_claim": {k_: dict(Counter(r["label"] for r, s in zip(rows, side_of) if s == k_).most_common())
                          for k_ in ("ally", "enemy", "question")}}
    doc, per = _step_summary(rows, rec, rounds, census, extra)
    rrounds = sorted(set(rounds) | {r["round"] for r in rrows})
    rdoc, rper = _step_summary(rrows, {}, rrounds, census,
                               {"by_claim": {k_: dict(Counter(r["label"] for r, m in zip(rrows, rm)
                                                              if m["side"] == k_).most_common())
                                             for k_ in ("ally", "enemy", "question")}})
    return {"session": sid, "step": "marks", "rows": rows, "reader_rows": rrows, "classes": doc, "reader": rdoc,
            "_per": per, "_rper": rper, "secs": round(time.perf_counter() - ctx["t0"], 1)}


def hold_duplicate_marks(rows: list, col_kind, col_idx) -> None:
    """A truth mark is one object: where the per-sample join gave one mark
    to two or more finds (a mark born twice, a "?" read twice), the nearest
    keeps it and each other becomes `nothing_there:held_by_nearer_find`,
    naming the mark it repeats (`duplicate_of`). In place."""
    by = defaultdict(list)
    for i, r in enumerate(rows):
        if col_kind[i] == "mark" and r["outcome"] != "ambiguous":
            by[int(col_idx[i])].append(i)
    for idx in by.values():
        if len(idx) < 2:
            continue
        keep = min(idx, key=lambda i: (rows[i]["dist_m"], rows[i]["t_cap"]))
        for i in idx:
            if i == keep:
                continue
            r = rows[i]
            r["duplicate_of"] = r["entity_id"]
            for k in ("entity_id", "entity_class", "family", "agent", "ability", "tray_key", "owner", "side_rel",
                      "truth_name", "drawn"):
                r[k] = None
            r["derivation"] = "held_by_nearer_find"
            r["outcome"], r["label"] = "nothing_there", "nothing_there:held_by_nearer_find"


STEP_FUNCS = {"ally": step_ally, "smoke": step_smoke, "glyph": step_glyph, "marks": step_marks}


def _pool_step(res: list, which: str = "classes", per_key: str = "_per") -> dict:
    """A step's sessions pooled (`_pool_classes`: rounds resampled within each match, matches added)."""
    per = [{"session": r["session"], "classes": r[which]} for r in res]
    arrays = [{"classes": r[per_key]} for r in res]
    return _pool_classes(per, arrays)


def run_step(step: str, sessions: list[str], tag: str | None, ptag: str | None, record: bool) -> int:
    """Steps 5 to 8: score the owner's emitted finds on each session, print
    the class-aware outcomes, recall per class and the coverage report, the
    reader's diagnostic beside, and write rows and the document under OUT."""
    for sid in sessions:
        tr.refuse(sid)
    res = []
    for sid in sessions:
        r = STEP_FUNCS[step](sid, tag, ptag) if step == "marks" else STEP_FUNCS[step](sid)
        sub = OUT / (tag or "") / step if step == "marks" else OUT / "steps" / step
        sub.mkdir(parents=True, exist_ok=True)
        with open(sub / f"{sid}.jsonl", "w", encoding="utf-8") as f:
            for row in r["rows"]:
                f.write(json.dumps(row, default=str) + "\n")
        if r.get("reader_rows") is not None:
            with open(sub / f"reader_{sid}.jsonl", "w", encoding="utf-8") as f:
                for row in r["reader_rows"]:
                    f.write(json.dumps(row, default=str) + "\n")
        c = r["classes"]
        print(f"{sid} step {step}: {c['finds']} finds; {r['secs']} s; "
              + "; ".join(f"{k}={c[k]}" for k in ("stamps", "verdict_source", "verdict_refusal", "tracks",
                                                    "tracks_named", "unbound_observations", "births",
                                                    "question_marks", "truth_marks", "by_claim") if k in c),
              flush=True)
        _print_classes(f"{sid} {step}", c, fa=False)
        if r.get("reader") is not None:
            _print_classes(f"{sid} {step} reader diagnostic", r["reader"], fa=False)
        res.append(r)
    pooled = reader = None
    if len(res) > 1:
        pooled = _pool_step(res)
        if all("by_claim" in r["classes"] for r in res):
            pooled["by_claim"] = {k: dict(sum((Counter(r["classes"]["by_claim"].get(k, {})) for r in res),
                                              Counter()).most_common())
                                  for k in res[0]["classes"]["by_claim"]}
            print(f"   by claim (pooled {step}): {pooled['by_claim']}", flush=True)
        _print_classes(f"pooled {step}", pooled, fa=False)
        _print_coverage(f"pooled {step}", pooled["coverage"])
        if all(r.get("reader") is not None for r in res):
            reader = _pool_step(res, "reader", "_rper")
            _print_classes(f"pooled {step} reader diagnostic", reader, fa=False)
    elif res:
        _print_coverage(f"{res[0]['session']} {step}", res[0]["classes"]["coverage"])
    doc = {"step": step, "version": VERSION, "tag": tag, "owner": STEP_STREAMS[step],
           "boot": f"{tr.N_BOOT} round resamples, seed {tr.SEED}",
           "sessions": {r["session"]: {"classes": r["classes"], "reader": r.get("reader"), "secs": r["secs"]}
                        for r in res},
           "pooled": pooled, "pooled_reader": reader}
    name = f"step_{step}" + (f"_{tag}" if step == "marks" else "") + \
        ("" if sorted(sessions) == sorted(DEV) else "_" + "_".join(sessions))
    (OUT / f"{name}.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    if record:
        _record_step(doc, sessions)
    return 0


def _metric_name(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(s).lower()).strip("_").replace("__", "_")


def _record_step(doc: dict, sessions: list[str]) -> None:
    """A step's values per session and pooled: finds, outcomes, the
    right-entity labels, recall per claimed class and the reader's
    outcomes beside."""
    from reticle.metrics import record as rec
    step = doc["step"]
    scopes = [(sid, v["classes"], v.get("reader")) for sid, v in doc["sessions"].items()]
    if doc.get("pooled"):
        scopes.append(("dev3", doc["pooled"], doc.get("pooled_reader")))
    part = f"{step}/{doc['tag']}" if step == "marks" else step
    for scope, c, rd in scopes:
        vals = {"finds": c["finds"], **{o: c["outcomes"][o] for o in CLASS_OUTCOMES}}
        ci = {o: c["outcomes_ci"].get(o) for o in CLASS_OUTCOMES if c.get("outcomes_ci")}
        for lb in ("right_entity:name_right", "right_entity:name_wrong", "right_entity:unnamed"):
            vals[_metric_name(lb)] = c["labels"].get(lb, 0)
            if lb in c.get("labels_ci", {}):
                ci[_metric_name(lb)] = c["labels_ci"][lb]
        for k, v in c["recall"].items():
            nm = "recall_" + _metric_name(k)
            vals[nm] = v["value"]
            ci[nm] = v["ci"]
            vals[nm + "_den"] = v["den"]
        for claim, labs in (c.get("by_claim") or {}).items():
            vals[f"claim_{claim}_finds"] = sum(labs.values())
            for o in CLASS_OUTCOMES:
                vals[f"claim_{claim}_{o}"] = sum(v for lb, v in labs.items() if lb.split(":")[0] == o)
            for lb in ("right_entity:name_right", "right_entity:name_wrong"):
                vals[f"claim_{claim}_{_metric_name(lb)}"] = labs.get(lb, 0)
        if rd:
            vals["reader_finds"] = rd["finds"]
            for o in CLASS_OUTCOMES:
                vals[f"reader_{o}"] = rd["outcomes"][o]
            for k, v in rd["recall"].items():
                vals["reader_recall_" + _metric_name(k)] = v["value"]
                ci["reader_recall_" + _metric_name(k)] = v["ci"]
        rec("question_acceptance", part=part, session=scope, values=vals, ci=ci,
            deps={"version": VERSION, "rule": "T1d", "window_ms": WINDOW_MS, "near_cm": NEAR_CM,
                  "ambig_cm": AMBIG_CM, "life_tail_ms": LIFE_TAIL_MS,
                  "stamps": (c.get("stamps") if scope != "dev3" else None)},
            context={"task": "harness-steps-5-8-20261007", "boot": doc["boot"], "owner": doc["owner"],
                     "sessions": sessions},
            note=f"step {step}: the owner's emitted finds against every replay entity (claim_outcome); "
                 "recall per claimed class over its own pairs; the reader's finds beside as a diagnostic")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("label", help="the replay entity under every find (truth_under)")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", default="b1")
    p.add_argument("--reality", choices=("off", "on"), default="off")
    p = sub.add_parser("lane", help="the enemy lane's emitted tracks against T1d")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", default="b1",
                   help="the teardrop_refusals ping reread classing the extras (the tag's score used b1)")
    p.add_argument("--reality", choices=("off", "on", "paired"), default="off",
                   help="the detection_reality arm: off (no glyph verdicts), on, or both paired")
    p.add_argument("--record", action="store_true")
    for step, hlp in (("ally", "step 5: round_entities' teammates"), ("smoke", "step 6: smoke_owner's smokes"),
                      ("glyph", "step 7: the glyph owner's verdicts"), ("marks", "step 8: X and \"?\" marks")):
        p = sub.add_parser(step, help=hlp)
        p.add_argument("sessions", nargs="*", default=list(DEV))
        p.add_argument("--tag", required=step == "marks", default=None)
        p.add_argument("--pings", default="b1")
        p.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    tr._idle()
    if a.cmd in STEP_FUNCS:
        return run_step(a.cmd, a.sessions or list(DEV), a.tag, a.pings, a.record)
    if a.cmd == "label":
        return run_label(a.sessions or list(DEV), a.tag, a.pings, a.reality)
    return run_lane(a.sessions or list(DEV), a.tag, a.pings, a.record, a.reality)


if __name__ == "__main__":
    raise SystemExit(main())
