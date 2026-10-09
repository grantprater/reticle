r"""Event-level acceptance: what an owning layer emits, scored per question against replay truth.

This module holds the commands of the one acceptance harness,
QUESTION_ACCEPTANCE.md build step B7, begun early (task
`event-harness-20261007`) in `prototypes/question_acceptance.py` and moved
here on 2026-10-09 (task `harness-t1d-20261009`). AGENTS.md: acceptance
scores the events a layer emits; a reader's own score is only a diagnostic,
reported beside; a new scorer extends this harness and never adds another
prototype. B7's episode derivations (T1, T2, T2g, matching; QA1-QA3)
join it as subcommands.

It owns evaluation only and changes no reader or lane code. The truth is the
replay layer's entities. T1d decides only whether an enemy player is drawn.
It reuses the truth join and does not restate it:

* the draw truth is `harness.draw.RealDrawMatch(rule="T1d")`;
* the (sample, enemy) pairs and the extras are `harness.sets.build_sets`;
* each track's lane outcome is `harness.schedule.track_outcome`, the
  sorting `RealMatch.enemy_reads` applies (`identity_abstained`,
  `agent_not_on_enemy_team`, `named`);
* the extras' classes are `harness.extras.class_extras`; the true false
  accepts are its `TRUE_FA` (ping, x_mark, other);
* the round bootstrap is the core's (`N_BOOT`, `SEED`); pooled
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
reader's hit rate of [metric:question_acceptance/lane/pgb@dev3#reader_hit=0.6076].

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
[metric:question_acceptance/classes/pgb@dev3#recall_player_enemy_drawn=0.5708]
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

**Step 9** (0.8.0, task `harness-step9-20261009`) folds the other replay
scorers into this file, so one scorer remains; their modules keep thin
wrappers that forward here.

*`replay-score`* is `replay_truth score`, moved whole (`replay_score`; on
9acf02f98283 its report equals the old command's field for field). It adds
`replay_classes`: each phantom of the report (a `round_entity` teammate
observation or a `minimap_object` enemy icon with no living player of its
side within 8 m) joins every replay entity at its frame's grid sample and
takes `claim_outcome`'s outcome. On the development matches, of
[metric:question_acceptance/replay@dev3#enemy_finds=451] enemy phantoms on
the grid, [metric:question_acceptance/replay@dev3#enemy_other_entity=309]
lie on another entity, most on Tejo's Stealth Drone
[metric:question_acceptance/replay@dev3#enemy_other_entity_ability_enemy_tejo_stealth_drone=101]
and Reyna's Leer
[metric:question_acceptance/replay@dev3#enemy_other_entity_ability_enemy_reyna_leer=84],
and [metric:question_acceptance/replay@dev3#enemy_nothing_there=124] on
nothing. Of [metric:question_acceptance/replay@dev3#teammate_finds=6311]
teammate phantoms, [metric:question_acceptance/replay@dev3#teammate_other_entity=3539]
lie on another entity, most on an ally Sage Barrier Orb
[metric:question_acceptance/replay@dev3#teammate_other_entity_ability_ally_sage_barrier_orb=2162],
and [metric:question_acceptance/replay@dev3#teammate_nothing_there=2698] on
nothing. A few phantoms (`right_entity:unnamed`) land within 3 m of a
player on the grid's clock though 8 m off on the report's frame clock.

*`replay-abilities`* is `replay_abilities score`, moved whole
(`replay_abilities_score`). Its spike block now takes the killfeed fit's
clock: since `replay_truth` 0.4.0 the old command passed a constant offset
and failed; with that one call fixed, master's code gives the same report
on 9acf02f98283. It adds `replay_ability_classes`: of
[metric:question_acceptance/replay_abilities@dev3#shape_finds=66] found
`ability_shape` ring centres,
[metric:question_acceptance/replay_abilities@dev3#shape_right_entity=65]
lie on the player's Recon Bolt, whose stuck bolt
(`GameObject_Hunter_Q_SonarBolt_C`) the ring recalls at
[metric:question_acceptance/replay_abilities@dev3#shape_recall_ability_ally_sova_recon_bolt_gameobject_hunter_q_sonarbolt_c=0.7451]
over the shape rows' samples. The stored `spike` stream never reads a
glyph while a spike is planted: the planted spike's recall is
[metric:question_acceptance/replay_abilities@dev3#spike_recall_spike__planted_spike=0.0],
and the [metric:question_acceptance/replay_abilities@dev3#spike_left_out_spike_not_planted=508]
dropped glyphs read without a planted spike lie on the spike item, which
the join leaves out (`NOT_JOINED`): a named coverage gap.

*`budget --tag TAG`* moves `enemy_error_budget`'s commands in (`budget-feats`,
`budget-eye`, `budget-eye-score`, `budget-levers`, `budget-sample`,
`budget-peek` run its library unchanged). Each extra starts from the entity
`truth_under` puts under it (the lane run's class rows); the players-only
class refines only an enemy-player label (`budget_class`). The players-only
budget is the control: recomputed, its classed rows and tables equal the
stored ones on all three development matches. Of
[metric:question_acceptance/budget/pgb@dev3#extra_total=1455] extras,
[metric:question_acceptance/budget/pgb@dev3#extra_undrawn_truth_vu_unseen=473]
lie on an undrawn enemy never seen, [metric:question_acceptance/budget/pgb@dev3#extra_nothing_there_kill_x=123]
on a death's X, [metric:question_acceptance/budget/pgb@dev3#extra_other_entity_ability_enemy_tejo_stealth_drone=100]
on Tejo's Stealth Drone and
[metric:question_acceptance/budget/pgb@dev3#extra_ambiguous=113] are
ambiguous; the old `other` and `other_ally_stack` classes resolve to
entities.

*The 2026-10-07 replay captures* (cadaadeb2d8b, 066741deafe5,
9912c382130b) have current inputs, and since 2026-10-09 they are the
development set (`DEV`, `reticle.dev_set`, pool `new3`). Teammates against a fresh `ally_icon` recall
[metric:question_acceptance/ally@new3#recall_player_ally_live=0.7651]
beside the reader's
[metric:question_acceptance/ally@new3#reader_recall_player_ally_live=0.7653],
naming [metric:question_acceptance/ally@new3#right_entity_name_right=107984]
finds right and [metric:question_acceptance/ally@new3#right_entity_name_wrong=1231]
wrong. Smokes recall Miks's Waveform at
[metric:question_acceptance/smoke@new3#recall_ability_ally_miks_waveform_smoke=0.9166]
and Clove's Ruse at
[metric:question_acceptance/smoke@new3#recall_ability_ally_clove_ruse_smoke=0.8726].
Glyphs recall Clove's Ruse at
[metric:question_acceptance/glyph@new3#recall_ability_ally_clove_ruse=0.8436]
and Tejo's Stealth Drone at
[metric:question_acceptance/glyph@new3#recall_ability_enemy_tejo_stealth_drone=0.0696].
Every subcommand scores `DEV` by default.

The old development matches (`FROZEN_DEV`, pool `dev3`) are frozen at their
stored versions with the stale inputs steps 5 to 8 named: `ally_icon` and
`death` (`reticle plan`), `minimap_dark` (its rescan decodes),
`ability_glyph` rows (9acf02f98283's on an older glyph bank) and the
`ability` scan; the player excluded their rereads. They stay scorable when
named, and every output they feed carries `frozen` with their stale streams.

**The core moved to `reticle/acceptance.py`** (0.9.0, task
`harness-promote-20261009`), which owns `replay-truth-under`: the join, the
outcomes, lane and class scoring, recall, the steps' summaries and the round
bootstrap, pure over the grid this harness builds. This module keeps the
IO: the lane build, the stores' streams, the claimers, the instrument
control, printing and recording.

**The grid moved too** (0.11.0, task `harness-t1d-20261009`): the truth grid
(`harness.match`), the clock (`harness.clock`), the real reads and the QA5r3
score (`harness.schedule`), T1d (`harness.draw`), the join's sets
(`harness.sets`), the extras' classes (`harness.extras`) and the error
budget (`harness.budget`) live beside this module, so every subcommand runs
in process (`harness.commands`); `reticle acceptance summary` rescores the
stored rows. The prototypes keep thin wrappers.

Stored rows and replay truth only; no decode, rescan or trial. The frozen
held-out capture (cea8ecbc94ab) is refused. Not wired (`"wire": "no"` on its rows in
`notes/predictions.jsonl`): an evaluation.

    reticle acceptance lane --tag pgb [SESSION ...] [--pings b1] [--reality off|on|paired] [--record]
    reticle acceptance label --tag pgb [SESSION ...] [--reality off|on]
    reticle acceptance ally|smoke|glyph [SESSION ...] [--record]
    reticle acceptance marks --tag pgb [SESSION ...] [--pings b1] [--record]
    reticle acceptance replay-score [SESSION ...] [--geometry NPZ] [--legacy-out NAME]
        [--record] [--record-score]
    reticle acceptance replay-abilities [SESSION ...] [--legacy-out] [--record] [--record-score]
    reticle acceptance budget --tag pgb [SESSION ...] [--record] [--rewrite]
    reticle acceptance slots [SESSION ...] [--record]
    reticle acceptance budget-feats SESSION ... --tag TAG (and budget-eye,
        budget-eye-score, budget-levers, budget-sample, budget-peek)
    reticle acceptance hook SESSION ... | hook-report [--record] | arms-report [--rule QA5r3]
    reticle acceptance draw-persist [SESSION ...] | draw-smokes [MATCH ...]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from reticle import acceptance as acc
# The core's names, as the harness's callers and tests spell them.
from reticle.acceptance import (ACCEPTANCE_VERSION, AMBIG_CM, CLASS_OUTCOMES, DROPPED,  # noqa: F401
                                LIFE_TAIL_MS, MEASURED_LIFE, NEAR_CM, NOT_JOINED, OUTCOMES, Q_MARK_MS,
                                WINDOW_MS, WINDOW_STEP_MS, ambiguous_classes, assign_one_to_one,
                                child_family, child_life, child_window_dist, claim_outcome, drawn_by_fact,
                                entity_key, frame_samples, hold_duplicate_marks, icon_outcomes,
                                lane_questions, nothing_derivation, outcome_of, short_reason)
from reticle.store import DEFAULT_STORE

from . import abilities as ra
from . import clock as rt
from . import extras as tr


# The core moved to `reticle.acceptance` (task `harness-promote-20261009`);
# these names keep the prototype's spelling for its callers and tests.
_boot_pooled = acc.boot_pooled
_boot_pooled_diff = acc.boot_pooled_diff


_join_entities = acc.join_entities
_census = acc.census
_dist = acc.dist_summary


_pool_classes = acc.pool_classes
_mark_truth = acc.mark_truth
_assigned = acc.assigned
_recall_players = acc.recall_players
_recall_children = acc.recall_children
_recall_marks = acc.recall_marks
_step_summary = acc.step_summary

#: 0.10.0 (task teardrop-new-sessions-20261009): `NEW` and `SCORED` come from
#: `teardrop_refusals`; every pooled metric record names its scope by `_pool_name`.
#: 0.11.0 (task harness-t1d-20261009): the grid, T1d and every subcommand run
#: in process from `reticle/harness/` (`reticle acceptance ...`); the scores
#: are unchanged.
#: 0.12.0 (task dev-set-new3-20261009): `DEV` is the 2026-10-07 three
#: (`reticle.dev_set`) and every default scores it; the old development
#: matches (`FROZEN_DEV`) stay scorable, and each document and metric row they
#: feed carries `frozen` with their stale streams (`extras.label`, `record`).
VERSION = "question-acceptance-0.12.0"


TASK = "event-harness-20261007"
TASK9 = "harness-step9-20261009"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "question-acceptance"
DEV = tr.DEV
FROZEN_DEV = tr.FROZEN_DEV
SCORED = tr.SCORED
#: The `--reality` arms and the folder suffix each writes under.
ARMS = {"off": "", "on": "_reality"}


def _refuse(sid: str) -> None:
    """The held-out matches are never read; the steps score `SCORED` only."""
    tr.refuse(sid)


def _pool_name(sessions) -> str:
    """The metrics session of a pooled scope (`dev_set.pool_name`): `new3`
    (`DEV`), `dev3` (`FROZEN_DEV`), else the sessions joined."""
    return tr.pool_name(sessions)


def _suffix(sessions) -> str:
    """A document's name suffix: none for the frozen development matches, whose
    stored documents carry none, else the sessions joined."""
    return "" if sorted(sessions) == sorted(FROZEN_DEV) else "_" + "_".join(sessions)


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
    from . import sets as elc
    from . import draw as tdr

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


def _truth_under(ctx: dict) -> dict:
    """Every find (accepted icon on a valid sample) with the truth entity
    under it (`reticle.acceptance.truth_under_rows`), the census's claimers
    (`claims`) and the instrument control (`_instrument`)."""
    from . import clock as rt
    from reticle.domain import load as load_facts

    sid, R, E = ctx["sid"], ctx["R"], ctx["E"]
    MO = E["MO"]
    ic = np.asarray(ctx["J"]["ic"], np.int64)

    def ping_of(nf, p, t_cap):
        # the ping class, by the extras' own rule (`teardrop_refusals.class_extras`)
        pseudo = [{"nearest_enemy_m": None, "nearest_enemy_alive": False, "t_cap": float(t_cap[f]),
                   "frame_idx": int(MO["frame_idx"][p[f]]),
                   "icon_px": [float(MO["enemy_x"][ic[f]]), float(MO["enemy_y"][ic[f]])], "_f": int(f)}
                  for f in nf]
        pos = {int(f): i for i, f in enumerate(nf)}
        out = np.zeros(len(nf), bool)
        for e in tr.class_extras(sid, ctx["tag"], {"info": R["info"], "extras": pseudo}, ctx["ptag"]):
            out[pos[e["_f"]]] = e["cls"] == "ping"
        return out

    under = acc.truth_under_rows(sid, ctx["M"], ctx["J"], E, ctx["ext"], remote_lag_ms=rt.REMOTE_LAG_MS,
                                 ping_of=ping_of, facts=load_facts())
    claims(sid, under["census"])
    under["instrument"] = _instrument(ctx, under["ks"])
    return under


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
    from . import draw as tdr
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
    from .. import slot_state as es

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
    lane (ownership question `replay-truth-under`): one row per find (see
    `_truth_under`), with the instrument control and the match's class
    census. Evaluation only: the replay never feeds a reader."""
    return _truth_under(_prepare(sid, tag, ptag, reality))


def lane(sid: str, tag: str, ptag: str | None, reality: str = "off", ctx: dict | None = None) -> dict:
    ctx = ctx or _prepare(sid, tag, ptag, reality)
    res, fa_rows, per, out_icon = acc.score_lane(sid, ctx["M"], ctx["R"], ctx["J"], ctx["E"], ctx["ext"],
                                                 ctx["summary"], ctx["why_refused"], tag=tag, version=VERSION,
                                                 ptag=ptag, reality=reality, true_fa=tr.TRUE_FA)
    res["secs"] = round(time.perf_counter() - ctx["t0"], 1)
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
    cdoc, cper = _class_lane(ctx, under, out_icon, per["ri"], per["nr"], per["rounds"])
    res["classes"] = cdoc
    p_cl = OUT / tag / f"classes{ARMS[reality]}_{sid}.jsonl"
    with open(p_cl, "w", encoding="utf-8") as f:
        for r in under["rows"]:
            f.write(json.dumps(r, default=str) + "\n")
    res["_per_round"] = {"fa": per["fa"], "by": per["by"], "nums": per["nums"], "in_real": per["in_real"],
                         "rounds": per["rounds"], "classes": cper}
    return res


def _class_lane(ctx: dict, under: dict, out_icon, ri: dict, nr: int, rounds: list) -> tuple[dict, dict]:
    """`reticle.acceptance.class_lane` over a prepared session."""
    from . import clock as rt

    return acc.class_lane(ctx["sid"], ctx["M"], ctx["J"], ctx["E"], ctx["R"], under, out_icon, ri, nr, rounds,
                          ctx["why_refused"], remote_lag_ms=rt.REMOTE_LAG_MS, true_fa=tr.TRUE_FA)


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
    name = (f"{kind}_{tag}{ARMS.get(reality, '_' + reality)}" if sorted(sessions) == sorted(FROZEN_DEV) else
            f"{kind}_{tag}{ARMS.get(reality, '_' + reality)}_{'_'.join(sessions)}")
    (OUT / f"{name}.json").write_text(json.dumps(tr.label(doc, sessions), indent=1, default=str), encoding="utf-8")


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
    from .extras import record as rec
    vals = {f"{q}_diff": v["diff"] for q, v in doc["diff"]["pooled"].items()}
    ci = {f"{q}_diff": v["ci"] for q, v in doc["diff"]["pooled"].items()}
    rec("question_acceptance", part=f"lane/{doc['tag']}/reality-paired", session=_pool_name(doc["sessions"]),
        values=vals, ci=ci,
        deps={"version": VERSION, "rule": "T1d"},
        context={"task": "detection-reality-20261007", "boot": doc["boot"], "sessions": doc["sessions"]},
        note="detection_reality on minus off, per question, pooled over the development matches; "
             "one set of resampled rounds scores both arms")


def _record(doc: dict, arm: str | None = None) -> None:
    from .extras import record as rec
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
        rec("question_acceptance", part=f"lane/{tag}", session=_pool_name(doc["pooled"]["sessions"]),
            values=vals, ci=ci,
            deps={"version": VERSION, "rule": "T1d"}, context={"task": TASK, "boot": doc["boot"],
                                                               "sessions": doc["pooled"]["sessions"]},
            note="pooled over the sessions; rounds resampled within each match")


def _record_classes(doc: dict, arm: str | None = None) -> None:
    """The class-aware lane's pooled and per-session values: finds per
    outcome, the old true false accepts per outcome and per drone class, the
    drone classes' recall and the instrument control."""
    from .extras import record as rec
    tag = doc["tag"] + (f"/{arm}" if arm else "")
    scopes = [(sid, r["classes"]) for sid, r in doc["sessions"].items() if r.get("classes")]
    if doc.get("pooled") and doc["pooled"].get("classes"):
        scopes.append((_pool_name(doc["pooled"]["sessions"]), doc["pooled"]["classes"]))
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
        inst = c["instrument"] if scope in doc["sessions"] else None
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
    name = f"label_{tag}{ARMS[reality]}" + _suffix(sessions)
    (OUT / f"{name}.json").write_text(json.dumps(tr.label({"tag": tag, "version": VERSION, "sessions": summary}, sessions),
                                                 indent=1, default=str), encoding="utf-8")
    return 0


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
    from . import draw as tdr
    _refuse(sid)
    t0 = time.perf_counter()
    M = tdr.RealDrawMatch(sid, rule="T1d")
    return {"sid": sid, "M": M, "J": {"alive": M.alive_grid(), "drawn": M.drawn(M.C)}, "t0": t0}


def _to_cm(sid: str):
    """Widget px to world cm, as `enemy_lane_check.build_sets` converts icons."""
    from .. import slot_state as es
    (_mf, to_m, _mpp), _why = es.world_frame(sid)
    upm = es.units_per_m()

    def f(px, py):
        px = np.asarray(px, float)
        if not px.size:
            return np.zeros(0), np.zeros(0)
        mx, my = to_m(px, np.asarray(py, float))
        return np.asarray(mx, float) * upm, np.asarray(my, float) * upm
    return f


def _frames_on_grid(M, t_cap, read) -> tuple[np.ndarray, np.ndarray]:
    """A stream's frames on the grid (`frame_samples`): (sample per frame,
    replay time per frame), live play only (`enemy_lane_check.live_samples`)."""
    from . import sets as elc
    from . import clock as rt
    t_cap = np.asarray(t_cap, float)
    t_rep = np.asarray(M.to_rep(t_cap, rt.REMOTE_LAG_MS), float)
    live, _ = elc.live_samples(M)
    step = float(np.median(np.diff(M.G)))
    i = np.clip(np.searchsorted(M.G, t_rep), 0, M.G.size - 1)
    ok = np.asarray(read, bool) & np.asarray(M.in_spans(t_cap), bool) & live[i]
    k = frame_samples(M.G, t_rep, ok, FRAME_HALF_STEP * step)
    k[(k >= 0) & ~live[np.clip(k, 0, None)]] = -1
    return k, t_rep


def _score_finds(ctx: dict, F: dict, *, claimed, name_of=None, drawn_of=None, marks=None,
                 near_side: str = "enemy", frame_key=None) -> tuple[list, dict]:
    """`reticle.acceptance.score_finds` over a prepared session, the domain
    facts loaded once per session."""
    from reticle.domain import load as load_facts
    if "_facts" not in ctx:
        ctx["_facts"] = load_facts()
    return acc.score_finds(ctx["sid"], ctx["M"], ctx["J"], F, ctx["_facts"], ctx.setdefault("_fact_cache", {}),
                           claimed=claimed, name_of=name_of, drawn_of=drawn_of, marks=marks,
                           near_side=near_side, frame_key=frame_key)


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


def step_smoke(sid: str) -> dict:
    """Step 6: the smokes `adjudication.smoke_owner` emits (`smoke_owner`
    rows, one per `smoke` track, each with the agent it names), one find per
    track at each sample of a read `minimap_dark` frame inside the track's
    observed life. Right entity: a replay smoke child (`t1_draw_rule.SMOKES`
    classes) of the named agent. Enemy smokes are not drawn
    [domain:abilities/enemy-smokes-not-on-minimap]; their recall is listed
    apart. The `smoke` tracks place the same smokes unnamed; the owner adds
    only the name, so the diagnostic is the unnamed count."""
    from . import draw as tdr
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
    from . import sets as elc
    from . import clock as rt
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
        (tr.refuse if step == "marks" else _refuse)(sid)
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
        _suffix(sessions)
    (OUT / f"{name}.json").write_text(json.dumps(tr.label(doc, sessions), indent=1, default=str), encoding="utf-8")
    if record:
        _record_step(doc, sessions)
    return 0


def _metric_name(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(s).lower()).strip("_").replace("__", "_")


def _record_step(doc: dict, sessions: list[str]) -> None:
    """A step's values per session and pooled: finds, outcomes, the
    right-entity labels, recall per claimed class and the reader's
    outcomes beside."""
    from .extras import record as rec
    step = doc["step"]
    scopes = [(sid, v["classes"], v.get("reader")) for sid, v in doc["sessions"].items()]
    if doc.get("pooled"):
        scopes.append((_pool_name(sessions), doc["pooled"], doc.get("pooled_reader")))
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
                  "stamps": (c.get("stamps") if scope not in (_pool_name(sessions),) else None)},
            context={"task": "harness-steps-5-8-20261007", "boot": doc["boot"], "owner": doc["owner"],
                     "sessions": sessions},
            note=f"step {step}: the owner's emitted finds against every replay entity (claim_outcome); "
                 "recall per claimed class over its own pairs; the reader's finds beside as a diagnostic")


def replay_score(sid: str, geometry: Path | None = None, finds: bool = False) -> dict:
    """Score one capture's stored minimap streams against its replay
    (`replay_truth score`'s report, folded into the harness at step 9).

    The denominator is the `ally_icon` frame grid restricted to the minimap
    crop cache's spans (`roi_cache`) and to frames where `ally_icon` reads the
    widget drawn; frames outside the spans or with the widget absent are
    counted apart and never enter a share. Within it: teammates per frame
    (`round_entity` observations, located within 8 m one to one, phantoms with
    no living teammate within 8 m), names, tracks (switches, fragments, IDF1),
    each missed teammate frame's class (`rt.MISS_CLASSES`, in order), the self
    fit, enemies (`minimap_object`, names through `enemy_track`) and facing per
    class with a lag scan. `geometry` overrides the baked geometry
    (`rt.session_context`). With `finds`, the report carries `_finds`: the
    teammate and enemy phantoms, for `replay_classes` to join to every
    replay entity."""
    from reticle import roi_cache

    ctx = rt.session_context(sid, geometry)
    out = ctx["out"]
    if "refused" in out:
        return out
    rp, mf, clock, me, team = ctx["rp"], ctx["mf"], ctx["clock"], ctx["me"], ctx["team"]
    allies, foes, agent = ctx["allies"], ctx["foes"], ctx["agent"]
    cm_per_px, gate = ctx["cm_per_px"], ctx["gate"]
    H, W = mf.widget_shape
    r_icon = float(mf.icon_px)
    rs = rp.round_starts()
    out["r_icon_px"] = round(r_icon, 3)
    stamps = {}

    # -- the denominator: ally_icon's frames inside the crop cache, widget drawn
    AI = ctx["AI"]
    stamps["ally_icon"] = AI["stamp"]
    rec = roi_cache.stored_record(rt.STORE, sid, "minimap")
    spans = (rec or {}).get("spans") or []
    # An absent crop cache bounds nothing; `cache_absent` keeps the reason.
    in_sp = (roi_cache.spans_mask(AI["t_ms"], spans) if rec is not None
             else np.ones(AI["t_ms"].shape, bool))
    sc = in_sp & AI["drawn"]
    S_idx, S_t = AI["frame_idx"][sc], AI["t_ms"][sc]
    S_rep = rt.capture_to_replay(S_t, *clock, rt.REMOTE_LAG_MS)        # teammates
    S_rep_self = rt.capture_to_replay(S_t, *clock, rt.SELF_LAG_MS)     # the player
    n = int(S_idx.size)
    out["frames"] = {
        "rule": "ally_icon frames inside the minimap crop cache's spans with widget_drawn",
        "ally_icon_frames": int(AI["t_ms"].size), "outside_cache_spans": int((~in_sp).sum()),
        "in_spans_widget_absent": int((in_sp & ~AI["drawn"]).sum()), "scored": n,
        "cache": None if rec is None else {"version": rec.get("version"), "hz": rec.get("hz"),
                                           "spans": len(spans)}}
    if rec is None:
        out["frames"]["cache_absent"] = (roi_cache.CACHE_RETIRED
                                         if roi_cache.cache_retirement(rt.STORE, sid, "minimap")
                                         else "no_cache")

    def rows_of(fi):
        fi = np.asarray(fi, np.int64)
        if n == 0:
            return np.zeros(fi.shape, np.int64), np.zeros(fi.shape, bool)
        k = np.clip(np.searchsorted(S_idx, fi), 0, n - 1)
        return k, S_idx[k] == fi

    mates = list(allies)
    c_me = mates.index(me)
    TX, TY, TYAW, TL = rt.truth_px(rp, mf, mates, S_rep)
    # the player's column at the self lag: the capture draws the player earlier
    sX, sY, sYAW, sL = rt.truth_px(rp, mf, [me], S_rep_self)
    TX[:, c_me], TY[:, c_me], TYAW[:, c_me], TL[:, c_me] = sX[:, 0], sY[:, 0], sYAW[:, 0], sL[:, 0]
    rnd = np.searchsorted(rs, S_rep, side="right") - 1
    # truth-side context per (frame, teammate)
    dd = np.hypot(TX[:, :, None] - TX[:, None, :], TY[:, :, None] - TY[:, None, :])
    dd[:, np.arange(len(mates)), np.arange(len(mates))] = np.inf
    stacked = TL & (np.nanmin(np.where(np.isfinite(dd), dd, np.inf), axis=2) <= 2.0 * r_icon)
    edge = TL & ((TX < r_icon) | (TX > W - 1 - r_icon) | (TY < r_icon) | (TY > H - 1 - r_icon))
    # time since each teammate was last stacked (frames in time order)
    last_st = np.where(stacked, S_t[:, None], -np.inf)
    last_st = np.maximum.accumulate(last_st, axis=0)
    since_stack = S_t[:, None] - last_st

    # -- teammates: round_entity observations
    RE = rt.load_round_entity(sid)
    stamps["round_entity"] = RE["stamp"]
    k, ok = rows_of(RE["frame_idx"])
    rows = k[ok]
    ox, oy, eid = RE["x"][ok], RE["y"][ok], RE["entity"][ok]
    fam, oname = RE["family"][ok], RE["agent"][ok]
    D = np.hypot(TX[rows] - ox[:, None], TY[rows] - oy[:, None])
    j, dist = rt._assign(rows, D, gate)
    hit = j >= 0
    nearest = np.min(np.where(np.isfinite(D), D, np.inf), axis=1) if D.size else np.zeros(0)
    phantom = ~(nearest <= gate)
    if finds:
        out["_finds"] = {"teammate": {"t_cap": S_t[rows][phantom], "px": ox[phantom], "py": oy[phantom],
                                       "frame_idx": S_idx[rows][phantom], "family": fam[phantom]}}
    G = np.zeros(TL.shape, bool)          # located by any observation
    G[rows[hit], j[hit]] = True
    M = np.full(TL.shape, -1, np.int64)   # the located observation's entity
    M[rows[hit], j[hit]] = eid[hit]
    obs_class = np.where(fam == "self", "self", "ally")
    truth_cls = np.array(["self" if c == c_me else "ally" for c in range(len(mates))])
    tm = {"observations": int(RE["x"].size), "observations_outside_scored_frames": int((~ok).sum()),
          "observations_scored": int(ok.sum()),
          "observations_without_entity": int(np.sum(eid < 0))}

    def mate_block(cols, obs_mask):
        live = TL[:, cols]
        got = G[:, cols]
        hm = hit & obs_mask
        return {"living_truth_frames": int(live.sum()), "matched": int(got.sum()),
                "recall": round(float(got.sum() / max(1, live.sum())), 4),
                "observations": int(obs_mask.sum()), "phantom": int((phantom & obs_mask).sum()),
                "phantom_share": round(float((phantom & obs_mask).sum() / max(1, obs_mask.sum())), 4),
                "duplicate": int((~hit & ~phantom & obs_mask).sum()),
                "err_px": rt._stats(dist[hm]), "err_cm": rt._stats(dist[hm] * cm_per_px, 0),
                "within_r_icon": round(float(np.mean(dist[hm] <= r_icon)), 4) if hm.any() else None}

    all_cols = list(range(len(mates)))
    ally_cols = [c for c in all_cols if c != c_me]
    tm["pooled"] = mate_block(all_cols, np.ones(hit.shape, bool))
    tm["self"] = mate_block([c_me], obs_class == "self")
    tm["ally"] = mate_block(ally_cols, obs_class == "ally")
    tm["family_vs_truth"] = {f"{o_}->{t_}": int(np.sum(hit & (obs_class == o_) & (truth_cls[np.clip(j, 0, None)] == t_)))
                             for o_ in ("self", "ally") for t_ in ("self", "ally")}

    # names: the entity's agent against the replay's
    truth_agent = np.array([agent.get(mates[c]) if c >= 0 else None for c in j], dtype=object)
    named = hit & np.array([g is not None for g in oname], bool)
    right = named & np.array([rt.canon(g) == rt.canon(t_) for g, t_ in zip(oname, truth_agent)], bool)
    wrong = named & ~right
    jc = np.clip(j, 0, None)
    w_stacked = stacked[rows, jc] & wrong
    w_left = wrong & ~w_stacked & (since_stack[rows, jc] <= rt.STACK_LEAVE_MS)
    wrong_pairs = Counter((t_, g) for t_, g, w in zip(truth_agent, oname, wrong) if w)
    tm["names"] = {"named": int(named.sum()), "right": int(right.sum()), "wrong": int(wrong.sum()),
                   "refused": int((hit & ~named).sum()),
                   "agreement": round(float(right.sum() / named.sum()), 4) if named.any() else None,
                   "wrong_share": round(float(wrong.sum() / named.sum()), 4) if named.any() else None,
                   "wrong_stacked": int(w_stacked.sum()),
                   "wrong_within_1s_of_leaving_stack": int(w_left.sum()),
                   "wrong_stack_share": (round(float((w_stacked | w_left).sum() / wrong.sum()), 4)
                                         if wrong.any() else None),
                   "unnamed_reason": None if named.any() else "no located observation's entity names an agent",
                   "wrong_pairs_truth_got": [[t_, g, c] for (t_, g), c in wrong_pairs.most_common(12)]}

    # tracks: one truth life is one teammate in one replay round
    # a second observation the one-to-one pass left beside a teammate
    dup = ~hit & ~phantom
    dupm = np.zeros(TL.shape, bool)
    if dup.any():
        dupm[rows[dup], np.argmin(np.where(np.isfinite(D[dup]), D[dup], np.inf), axis=1)] = True
    t_r, t_c = np.nonzero(TL)
    life = t_c * 1000 + rnd[t_r]
    tm["tracks"] = {}
    for name, cols, om in (("pooled", all_cols, np.ones(hit.shape, bool)),
                           ("self", [c_me], obs_class == "self"),
                           ("ally", ally_cols, obs_class == "ally")):
        sel = np.isin(t_c, cols)
        tm["tracks"][name] = rt.track_metrics(life[sel], S_t[t_r[sel]], M[t_r[sel], t_c[sel]],
                                           int(om.sum()), flag=stacked[t_r[sel], t_c[sel]])
        tm["tracks"][name]["switches_beside_duplicate"] = rt.track_metrics(
            life[sel], S_t[t_r[sel]], M[t_r[sel], t_c[sel]], int(om.sum()),
            flag=dupm[t_r[sel], t_c[sel]])["switches_flagged"]
        tm["tracks"][name]["switches_stacked_or_duplicate"] = rt.track_metrics(
            life[sel], S_t[t_r[sel]], M[t_r[sel], t_c[sel]], int(om.sum()),
            flag=(stacked | dupm)[t_r[sel], t_c[sel]])["switches_flagged"]
    tm["tracks"]["switches_flagged_means"] = "the teammate is stacked at the switch frame"
    tm["tracks"]["switches_beside_duplicate_means"] = ("another observation the one-to-one pass "
                                                       "left within 8 m lies nearest this "
                                                       "teammate at the switch frame")

    # misses: every living truth frame no observation located, one class each
    mr, mc = np.nonzero(TL & ~G)
    occ = rt.load_occluders(sid)
    TV = rt.load_team_vision(sid)
    MO = rt.load_minimap_object(sid)
    stamps["team_vision"] = TV["stamp"]
    stamps["minimap_object"] = MO["stamp"]
    stamps["minimap_dark"] = occ["stamps"].get("minimap_dark")
    absent_fi = set(TV["frame_idx"][TV["widget"] == "not_drawn"].tolist())
    absent_fi |= set(MO["frame_idx"][MO["reason"] == "widget_not_drawn"].tolist())
    dk = np.clip(np.searchsorted(occ["dark_t"], S_t), 0, max(occ["dark_t"].size - 1, 0))
    if occ["dark_t"].size:
        dark_absent = (np.abs(occ["dark_t"][dk] - S_t) <= 1.0) & ~occ["dark_drawn"][dk]
    else:
        dark_absent = np.zeros(n, bool)
    frame_absent = np.isin(S_idx, list(absent_fi)) | dark_absent
    mx, my, mt = TX[mr, mc], TY[mr, mc], S_t[mr]
    # a ping holds a span, not an instant: active from t0 to t1
    ph = np.zeros(mr.size, bool)
    for t0, t1, px, py in occ["ping"]:
        ph |= (mt >= t0) & (mt <= t1) & (np.hypot(mx - px, my - py) <= r_icon)
    under = {"ping": ph}
    under["spike_glyph"] = rt._near_points(mt, mx, my, occ["spike_glyph"], rt.SPIKE_TOL_MS, r_icon)
    under["ability_glyph"] = rt._near_points(mt, mx, my, occ["disc"], rt.DISC_TOL_MS, r_icon)
    under["minimap_dark"] = rt._under_dark(mt, mx, my, occ, r_icon)
    any_under = np.zeros(mr.size, bool)
    for v in under.values():
        any_under |= v
    # the same tests on located frames: how often cover sits near a teammate
    # the stream did locate, so a miss class is read against its base rate
    lr, lc = np.nonzero(TL & G)
    lx, ly, lt = TX[lr, lc], TY[lr, lc], S_t[lr]
    lp = np.zeros(lr.size, bool)
    for t0, t1, px, py in occ["ping"]:
        lp |= (lt >= t0) & (lt <= t1) & (np.hypot(lx - px, ly - py) <= r_icon)
    base = {"ping": lp,
            "spike_glyph": rt._near_points(lt, lx, ly, occ["spike_glyph"], rt.SPIKE_TOL_MS, r_icon),
            "ability_glyph": rt._near_points(lt, lx, ly, occ["disc"], rt.DISC_TOL_MS, r_icon),
            "minimap_dark": rt._under_dark(lt, lx, ly, occ, r_icon)}
    base_any = np.zeros(lr.size, bool)
    for v in base.values():
        base_any |= v
    cls = rt.classify_misses({"widget_absent": frame_absent[mr], "stacked": stacked[mr, mc],
                           "under_stored_occluder": any_under, "edge": edge[mr, mc]})
    # minimap_dark's grey-dark floor lies within r_icon of most located
    # teammates too (`occluder_share_located`), so the same order without it
    # is reported beside the fixed rule, never in its place
    no_dark = under["ping"] | under["spike_glyph"] | under["ability_glyph"]
    cls_nd = rt.classify_misses({"widget_absent": frame_absent[mr], "stacked": stacked[mr, mc],
                              "under_stored_occluder": no_dark, "edge": edge[mr, mc]})

    def miss_block(mask, cls=cls):
        c = Counter(cls[mask].tolist())
        tot = int(mask.sum())
        return {"missed": tot, **{f"{k}": int(c.get(k, 0)) for k in rt.MISS_CLASSES},
                "shares": {k: round(c.get(k, 0) / tot, 4) if tot else None for k in rt.MISS_CLASSES}}
    tm["misses"] = {"order": list(rt.MISS_CLASSES),
                    "pooled": miss_block(np.ones(mr.size, bool)),
                    "self": miss_block(mc == c_me), "ally": miss_block(mc != c_me),
                    "pooled_without_minimap_dark": miss_block(np.ones(mr.size, bool), cls_nd),
                    "occluder_kinds_any_order": {k: int(v.sum()) for k, v in under.items()},
                    "occluder_share_missed": {k: round(float(v.mean()), 4) if v.size else None
                                              for k, v in (under | {"any": any_under}).items()},
                    "occluder_share_located": {k: round(float(v.mean()), 4) if v.size else None
                                               for k, v in (base | {"any": base_any}).items()},
                    "stacked_share_located": round(float(stacked[lr, lc].mean()), 4) if lr.size else None,
                    "rules": {"widget_absent": "team_vision widget not_drawn, minimap_object "
                                               "widget_not_drawn or minimap_dark widget_drawn false "
                                               "at the frame",
                              "stacked": "another living teammate (or the self) within 2 r_icon",
                              "under_stored_occluder": "an active ping within r_icon; an accepted "
                                                       "spike glyph or ability glyph disc within "
                                                       "r_icon plus its radius; grey-dark "
                                                       "minimap_dark floor within r_icon",
                              "edge": "within r_icon of the widget's border",
                              "isolated": "none of the above"}}
    out["teammates"] = tm

    # -- the self fit (ally_icon), within the scored frames
    fx, fy = AI["self_x"][sc], AI["self_y"][sc]
    q = rp.sample(me, S_rep_self)
    me_live = TL[:, c_me]
    sx, sy = rt.to_px(mf, q["x"], q["y"])
    has = np.isfinite(fx)
    e_self = np.hypot(sx - fx, sy - fy)
    m_ = has & me_live
    selfo = {"self_fits": int(has.sum()), "self_fits_player_alive": int(m_.sum()),
             "self_fits_player_dead": int((has & ~me_live).sum()),
             "living_frames": int(me_live.sum()),
             "located_within_gate": int(np.sum(m_ & (e_self <= gate))),
             "recall": round(float(np.sum(m_ & (e_self <= gate)) / max(1, me_live.sum())), 4),
             "err_px": rt._stats(e_self[m_]), "err_cm": rt._stats(e_self[m_] * cm_per_px, 0),
             "beyond_gate": int(np.sum(e_self[m_] > gate))}
    scan = {}
    for L in rt.LAG_SCAN_MS:
        qq = rp.sample(me, rt.capture_to_replay(S_t[m_], *clock, L))
        px, py = rt.to_px(mf, qq["x"], qq["y"])
        scan[int(L)] = round(float(np.nanmedian(np.hypot(px - fx[m_], py - fy[m_]))), 3) if m_.any() else None
    selfo["lag_scan_median_px"] = scan
    okscan = {k_: v for k_, v in scan.items() if v is not None}
    selfo["best_lag_ms"] = min(okscan, key=okscan.get) if okscan else None
    w = m_ & (e_self <= gate)
    if w.sum() > 20:
        A = np.column_stack([q["x"][w], q["y"][w], np.ones(w.sum())])
        cx, *_ = np.linalg.lstsq(A, fx[w], rcond=None)
        cy, *_ = np.linalg.lstsq(A, fy[w], rcond=None)
        res = np.hypot(A @ cx - fx[w], A @ cy - fy[w])
        selfo["affine_fit_on_self"] = {"n": int(w.sum()), "residual_px": rt._stats(res),
                                       "baked_transform_err_px": rt._stats(e_self[w]),
                                       "coef_x": [round(float(c), 6) for c in cx],
                                       "coef_y": [round(float(c), 6) for c in cy]}
    out["self"] = selfo

    # -- enemies: minimap_object icons, names through enemy_track
    out["enemies"] = _replay_enemies(sid, rp, mf, clock, foes, agent, gate, cm_per_px, r_icon, MO,
                                     rs, stamps)
    if finds:
        out["_finds"]["enemy"] = out["enemies"].pop("_phantoms")
    else:
        out["enemies"].pop("_phantoms")

    # -- facing per class
    fac = {}
    # self: team_vision's self icon against the player
    kk, okk = rows_of(TV["icon_frame"])
    sel = okk & (TV["icon_role"] == "self")
    rr = kk[sel]
    d_ = np.hypot(TX[rr, c_me] - TV["icon_x"][sel], TY[rr, c_me] - TV["icon_y"][sel])
    good = np.isfinite(d_) & (d_ <= gate)
    err = rt._ang_deg(TYAW[rr, c_me], TV["icon_facing"][sel])[good]
    fac["self_team_vision"] = {**rt._facing_block(err), "source": "team_vision role self",
                               **rt._facing_lag_scan(rp, mf, [me] * int(good.sum()),
                                                  TV["icon_t"][sel][good],
                                                  TV["icon_facing"][sel][good], clock)}

    def ally_facing(fr, fx_, fy_, ff, ft, source):
        kk2, ok2 = rows_of(fr)
        ok2 &= np.isfinite(ff)
        r2 = kk2[ok2]
        D2 = np.hypot(TX[r2][:, ally_cols] - fx_[ok2][:, None], TY[r2][:, ally_cols] - fy_[ok2][:, None])
        j2, _d2 = rt._assign(r2, D2, gate)
        h2 = j2 >= 0
        cols = np.asarray(ally_cols)[np.clip(j2, 0, None)]
        e2 = rt._ang_deg(TYAW[r2, cols], ff[ok2])[h2]
        subj = [mates[c] for c in cols[h2]]
        return {**rt._facing_block(e2), "icons": int(ok2.sum()), "located": int(h2.sum()),
                "source": source,
                **rt._facing_lag_scan(rp, mf, subj, ft[ok2][h2], ff[ok2][h2], clock)}

    fac["ally_ally_icon"] = ally_facing(AI["icon_frame"], AI["icon_x"], AI["icon_y"],
                                        AI["icon_facing"], AI["icon_t"],
                                        "ally_icon icon teardrop facing, non-self teammates")
    am = TV["icon_role"] == "ally"
    fac["ally_team_vision"] = ally_facing(TV["icon_frame"][am], TV["icon_x"][am], TV["icon_y"][am],
                                          TV["icon_facing"][am], TV["icon_t"][am],
                                          "team_vision role ally")
    fac["enemy_minimap_object"] = out["enemies"].pop("_facing", None)
    out["facing"] = fac

    # -- spike: the HUD marker and the minimap glyph against the replay's carrier
    out["spike"] = _replay_spike(sid, rp, mf, clock, allies, foes, team, me)
    out["stamps"] = stamps
    out["agents"] = None   # never written: subjects stay in the store
    return out


def _replay_enemies(sid, rp, mf, clock, foes, agent, gate, cm_per_px, r_icon, MO, rs, stamps) -> dict:
    """`replay_score`'s enemies: `minimap_object` enemy icons against the replay's living foes, and
    `enemy_track`'s names and tracks.

    An icon is located when one-to-one assignment within 8 m gives it a
    living foe; a phantom has no living foe within 8 m. Recall is not scored:
    whether the minimap must draw a foe is unknown here. `enemy_track`
    observations are located the same way and their entity's agent compared
    with the replay's; track metrics count only located observations."""
    lag = rt.REMOTE_LAG_MS
    read = MO["reason"] == None  # noqa: E711 (object array)
    out = {"frames": int(MO["frame_idx"].size), "frames_read": int(read.sum()),
           "frames_refused": dict(Counter(r for r in MO["reason"].tolist() if r is not None)),
           "icons": int(MO["enemy_x"].size)}
    out["_phantoms"] = {"t_cap": np.zeros(0), "px": np.zeros(0), "py": np.zeros(0),
                        "frame_idx": np.zeros(0, np.int64)}
    if MO["enemy_x"].size:
        t_rep = rt.capture_to_replay(MO["enemy_t"], *clock, lag)
        X, Y, YAW, _L = rt.truth_px(rp, mf, foes, t_rep)
        D = np.hypot(X - MO["enemy_x"][:, None], Y - MO["enemy_y"][:, None])
        j, dist = rt._assign(MO["enemy_frame"], D, gate)
        hit = j >= 0
        nearest = np.min(np.where(np.isfinite(D), D, np.inf), axis=1)
        phantom = ~(nearest <= gate)
        out["_phantoms"] = {"t_cap": np.asarray(MO["enemy_t"], float)[phantom],
                            "px": np.asarray(MO["enemy_x"], float)[phantom],
                            "py": np.asarray(MO["enemy_y"], float)[phantom],
                            "frame_idx": np.asarray(MO["enemy_frame"], np.int64)[phantom]}
        out.update(matched=int(hit.sum()), phantom=int(phantom.sum()),
                   phantom_share=round(float(phantom.mean()), 4),
                   duplicate=int((~hit & ~phantom).sum()),
                   err_px=rt._stats(dist[hit]), err_cm=rt._stats(dist[hit] * cm_per_px, 0),
                   within_r_icon=round(float(np.mean(dist[hit] <= r_icon)), 4) if hit.any() else None)
        ff = MO["enemy_facing"]
        fh = hit & np.isfinite(ff)
        jc = np.clip(j, 0, None)
        e = rt._ang_deg(YAW[np.arange(j.size), jc], ff)[fh]
        out["_facing"] = {**rt._facing_block(e), "source": "minimap_object enemy teardrop",
                          **rt._facing_lag_scan(rp, mf, [foes[c] for c in jc[fh]], MO["enemy_t"][fh],
                                             ff[fh], clock)}
    ET = rt.load_enemy_track(sid)
    if ET is None:
        out["enemy_track"] = {"refused": "no_stored_enemy_track"}
        return out
    stamps["enemy_track"] = ET["stamp"]
    t_rep = rt.capture_to_replay(ET["t_ms"], *clock, lag)
    X, Y, _YAW, _L = rt.truth_px(rp, mf, foes, t_rep)
    D = np.hypot(X - ET["x"][:, None], Y - ET["y"][:, None])
    j, dist = rt._assign(ET["frame_idx"], D, gate)
    hit = j >= 0
    nearest = np.min(np.where(np.isfinite(D), D, np.inf), axis=1) if D.size else np.zeros(0)
    phantom = ~(nearest <= gate)
    truth_agent = np.array([agent.get(foes[c]) if c >= 0 else None for c in j], dtype=object)
    named = hit & np.array([g is not None for g in ET["agent"]], bool)
    right = named & np.array([rt.canon(g) == rt.canon(t_) for g, t_ in zip(ET["agent"], truth_agent)],
                             bool)
    wrong_pairs = Counter((t_, g) for t_, g, w in zip(truth_agent, ET["agent"], named & ~right) if w)
    rnd = np.searchsorted(rs, t_rep, side="right") - 1
    life = np.clip(j, 0, None) * 1000 + rnd
    trk = rt.track_metrics(life[hit], ET["t_ms"][hit], ET["entity"][hit], int(ET["x"].size))
    # truth frames are only the located ones (drawn-ness is unknown): IDF1 and
    # id_recall would read as precision, so only id_precision stands
    for k in ("idf1", "id_recall", "truth_frames", "truth_minutes", "switches_per_truth_minute"):
        trk.pop(k, None)
    mins = hit.sum() / rt.GRID_HZ / 60.0
    trk["switches_per_located_minute"] = round(trk["switches"] / mins, 3) if mins else None
    out["enemy_track"] = {"observations": int(ET["x"].size), "matched": int(hit.sum()),
                          "phantom": int(phantom.sum()),
                          "phantom_share": round(float(phantom.mean()), 4) if phantom.size else None,
                          "err_px": rt._stats(dist[hit]),
                          "names": {"named": int(named.sum()), "right": int(right.sum()),
                                    "wrong": int((named & ~right).sum()),
                                    "refused": int((hit & ~named).sum()),
                                    "agreement": (round(float(right.sum() / named.sum()), 4)
                                                  if named.any() else None),
                                    "wrong_pairs_truth_got": [[t_, g, c] for (t_, g), c
                                                              in wrong_pairs.most_common(8)]},
                          "tracks": trk}
    return out


def _replay_spike(sid, rp, mf, clock, allies, foes, team, me) -> dict:
    """`replay_score`'s spike: the HUD marker and the minimap glyph
    against the replay's carrier, and the stored per-round carrier."""
    import pyarrow.parquet as pq

    p = rp.dir / "spike_carrier.parquet"
    if not p.is_file():
        return {"refused": "no_replay_spike_carrier"}
    iv = pq.read_table(p).to_pylist()
    held = [r for r in iv if r["holder_kind"] in ("player", "proxy") and r["carrier_subject"]]
    f0 = np.array([r["from_ms"] for r in held], float)
    f1 = np.array([r["to_ms"] if r["to_ms"] is not None else np.inf for r in held], float)
    who = np.array([r["carrier_subject"] for r in held], dtype=object)

    def carrier_at(t):
        t = np.asarray(t, float)
        k = np.searchsorted(f0, t, side="right") - 1
        ok = (k >= 0) & (t < f1[np.clip(k, 0, None)])
        return np.where(ok, who[np.clip(k, 0, None)], None)

    s_t, s_slot, s_glyph = [], [], []
    for r in rt._rows(rt.STORE / "events" / "spike" / f"{sid}.jsonl", '"kind":"frame"'):
        if r.get("reason") is not None:
            continue
        s_t.append(r["t_ms"])
        s_slot.append((r.get("marker") or {}).get("slot"))
        g = [x for x in r.get("glyphs") or [] if x.get("reason") is None]
        s_glyph.append(g)
    if not s_t:
        return {"refused": "no_spike_frames"}
    s_t = np.array(s_t)
    # the carrier is another player's state as the minimap draws it: the remote lag
    t_rep = rt.capture_to_replay(s_t, *clock, rt.REMOTE_LAG_MS)
    car = carrier_at(t_rep)
    ally_car = np.array([c is not None and team.get(c) == team[me] for c in car])
    foe_car = np.array([c is not None and team.get(c) != team[me] for c in car])
    marker = np.array([s is not None for s in s_slot])
    out = {"frames": int(s_t.size),
           "marker_vs_ally_carrier": {"both": int((marker & ally_car).sum()),
                                      "marker_only": int((marker & ~ally_car).sum()),
                                      "carrier_only": int((~marker & ally_car).sum()),
                                      "neither": int((~marker & ~ally_car).sum())},
           "frames_enemy_carries": int(foe_car.sum())}
    # carried glyph position against the carrier
    errs, kinds = [], Counter()
    gx, gy, gt, gc = [], [], [], []
    for t, gl, c in zip(t_rep, s_glyph, car):
        for g in gl:
            kinds[(g["state"], "ally" if c in allies else "foe" if c in foes else "none")] += 1
            if g["state"] == "carried" and c is not None:
                gx.append(g["cx"])
                gy.append(g["cy"])
                gt.append(t)
                gc.append(c)
    if gx:
        gx, gy, gt = np.array(gx, float), np.array(gy, float), np.array(gt)
        tx, ty = np.full(gt.size, np.nan), np.full(gt.size, np.nan)
        for s in set(gc):
            m = np.array([c == s for c in gc])
            q = rp.sample(s, gt[m])
            tx[m], ty[m] = rt.to_px(mf, q["x"], q["y"])
        errs = np.hypot(tx - gx, ty - gy)
    out["glyph_state_by_replay_carrier"] = {f"{k[0]}|{k[1]}": n for k, n in sorted(kinds.items())}
    out["carried_glyph_err_px"] = rt._stats(errs) if len(errs) else None
    # stored per-round carrier_seen against the replay's rounds with an allied carrier
    rs = rp.round_starts()
    rounds_ally = set()
    for r in held:
        if team.get(r["carrier_subject"]) == team[me]:
            rounds_ally.add(int(np.searchsorted(rs, r["from_ms"], side="right")))
    stored = [r for r in rt._rows(rt.STORE / "events" / "spike_carrier" / f"{sid}.jsonl", '"kind":"round"')]
    seen = {r["round_no"] for r in stored if r.get("carrier_seen")}
    out["rounds"] = {"replay_ally_carrier_rounds": len(rounds_ally),
                     "stored_carrier_seen_rounds": len(seen),
                     "seen_and_ally_carrier": len(seen & rounds_ally),
                     "seen_without_ally_carrier": sorted(seen - rounds_ally),
                     "ally_carrier_not_seen": sorted(rounds_ally - seen)}
    return out


def record_replay_score(s: dict) -> list[str]:
    """`replay_score`'s values in the `replay_truth` series, part `score`, as
    `replay_truth score --record` wrote them."""
    from reticle import metrics
    geo = s.get("geometry") or {}
    deps = {"replay_truth": rt.REPLAY_TRUTH_VERSION, "vrfkit": rt.VRFKIT_VERSION,
            "minimap_lag_ms": s["minimap_lag_ms"], "gate_m": rt.GATE_M, "max_gap_ms": rt.MAX_GAP_MS,
            "geometry": geo.get("path"), "shade_fit": geo.get("shade_fit"),
            "stamps": s.get("stamps"), "player_basis": s.get("player_basis"),
            "team_source": s.get("team_source"),
            "self_id": {"radius_m": rt.SELF_ID_RADIUS_M, "min_frames": rt.SELF_ID_MIN_FRAMES,
                        "min_share": rt.SELF_ID_MIN_SHARE, "margin": rt.SELF_ID_MARGIN}}
    T, S, E, F = s["teammates"], s["self"], s["enemies"], s["facing"]
    SI = s.get("self_identity") or {}
    SR, SX = SI.get("replay") or {}, SI.get("riot_cross_check") or {}
    P, MS = T["pooled"], T["misses"]["pooled"]["shares"]
    ET = E.get("enemy_track") or {}

    def fv(cls, key):
        b = F.get(cls) or {}
        if key in ("median", "p90"):
            return (b.get("err_deg") or {}).get(key)
        return b.get(key)
    v = {"self_id_frames": SR.get("frames"),
         "self_id_best_share": (SR.get("best") or {}).get("share_within"),
         "self_id_runner_up_share": (SR.get("runner_up") or {}).get("share_within"),
         "self_id_margin": SR.get("margin"),
         "self_id_riot_present": SX.get("present"),
         "self_id_riot_self_agrees": SX.get("self_agrees"),
         "self_id_riot_team_agrees": SX.get("team_agrees"),
         "align_offset_ms": round(s["align"]["a_ms"], 1),
         "align_mad_ms": round(s["align"]["residual_mad_ms"], 1),
         "align_matched": s["align"]["matched"],
         "frames_scored": s["frames"]["scored"],
         "frames_outside_spans": s["frames"]["outside_cache_spans"],
         "frames_in_spans_widget_absent": s["frames"]["in_spans_widget_absent"],
         "self_err_px_median": (S["err_px"] or {}).get("median"),
         "self_err_px_p90": (S["err_px"] or {}).get("p90"),
         "self_err_cm_median": (S["err_cm"] or {}).get("median"),
         "self_err_cm_p90": (S["err_cm"] or {}).get("p90"),
         "self_recall": S["recall"], "self_best_lag_ms": S["best_lag_ms"],
         "self_affine_residual_px_median":
             ((S.get("affine_fit_on_self") or {}).get("residual_px") or {}).get("median"),
         "self_baked_err_px_median":
             ((S.get("affine_fit_on_self") or {}).get("baked_transform_err_px") or {}).get("median"),
         "mate_recall": P["recall"], "mate_phantom_share": P["phantom_share"],
         "mate_self_recall": T["self"]["recall"], "mate_ally_recall": T["ally"]["recall"],
         "ally_err_px_median": (P["err_px"] or {}).get("median"),
         "ally_err_px_p90": (P["err_px"] or {}).get("p90"),
         "ally_err_cm_median": (P["err_cm"] or {}).get("median"),
         "mate_within_r_icon": P["within_r_icon"],
         "ally_id_agreement": T["names"]["agreement"],
         "mate_wrong_name_share": T["names"]["wrong_share"],
         "mate_wrong_name_stack_share": T["names"]["wrong_stack_share"],
         **{f"miss_{k}_share": MS[k] for k in rt.MISS_CLASSES},
         "mate_switches_per_min": T["tracks"]["pooled"]["switches_per_truth_minute"],
         "mate_ally_switches_per_min": T["tracks"]["ally"]["switches_per_truth_minute"],
         "mate_fragments_per_life": T["tracks"]["pooled"]["fragments_per_matched_life"],
         "mate_idf1": T["tracks"]["pooled"]["idf1"],
         "mate_self_idf1": T["tracks"]["self"]["idf1"],
         "mate_ally_idf1": T["tracks"]["ally"]["idf1"],
         "enemy_icons": E.get("icons"), "enemy_phantom_share": E.get("phantom_share"),
         "enemy_err_px_median": (E.get("err_px") or {}).get("median"),
         "enemy_track_id_agreement": (ET.get("names") or {}).get("agreement"),
         "enemy_track_id_precision": (ET.get("tracks") or {}).get("id_precision"),
         **{f"facing_{c}_{k}": fv(c, k)
            for c in ("self_team_vision", "ally_ally_icon", "ally_team_vision",
                      "enemy_minimap_object")
            for k in ("median", "p90", "flip_share", "best_lag_ms")}}
    metrics.record("replay_truth", part="score", session=s["session"], values=v, deps=deps)
    return [f"[metric:replay_truth/score@{s['session']}#{key}={val}]" for key, val in v.items()]


def _ra_pair(det_t, tru_t, gate):
    """One-to-one nearest pairing of two time lists within `gate` (ms).
    Returns (det index, truth index, det - truth ms) triples."""
    det_t, tru_t = np.asarray(det_t, float), np.asarray(tru_t, float)
    if not det_t.size or not tru_t.size:
        return []
    D = det_t[:, None] - tru_t[None, :]
    i, j = np.nonzero(np.abs(D) <= gate)
    o = np.argsort(np.abs(D[i, j]), kind="stable")
    used_i, used_j, out = set(), set(), []
    for k in o:
        a, b = int(i[k]), int(j[k])
        if a in used_i or b in used_j:
            continue
        used_i.add(a)
        used_j.add(b)
        out.append((a, b, float(D[a, b])))
    return out


def _ra_cast_score(det, tru, gate=ra.CAST_GATE_MS):
    """Detections (t_cap ms, ability) against truth (t_cap ms, ability)."""
    res = {}
    # one pass groups each side's times by ability, in input order
    by_det, by_tru = defaultdict(list), defaultdict(list)
    for t_, ab_ in det:
        by_det[ab_].append(t_)
    for t_, ab_ in tru:
        by_tru[ab_].append(t_)
    for ab in sorted(set(by_det) | set(by_tru), key=str):
        dt, tt = by_det.get(ab, []), by_tru.get(ab, [])
        p = _ra_pair(dt, tt, gate)
        e = np.array([x[2] for x in p])
        res[ab] = {"stored": len(dt), "replay": len(tt), "paired": len(p),
                   "within_1s": int(np.sum(np.abs(e) <= 1000)) if e.size else 0,
                   "false": len(dt) - len(p), "missed": len(tt) - len(p),
                   "recall": round(len(p) / len(tt), 4) if tt else None,
                   "stored_minus_replay_ms": ra._stats(e, 1)}
    return res


def replay_abilities_score(sid: str) -> dict:
    """`replay_abilities score`'s report, folded into the harness at step 9:
    the player's casts (`tray_drop`, `ability_state`), `ability_shape`, the
    player's labels, `ult_cast` and the spike against the replay's actors
    and cast records. The spike block is `_replay_spike` on the session's
    clock (the killfeed fit); 0.1.0 passed it the constant offset and
    failed."""
    ctx = rt.session_context(sid)
    out = dict(ctx["out"])
    if "refused" in out:
        return out
    out["replay_abilities_version"] = ra.REPLAY_ABILITIES_VERSION
    rp, mf, a, me, team = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"], ctx["team"]
    allies, foes, agent = ctx["allies"], ctx["foes"], ctx["agent"]
    lag = rt.MINIMAP_LAG_MS
    out["rests_on"] = {"alignment": "stored deaths (death-adjudication) against replay "
                                    "characterDeath, replay_truth.session_context",
                       "player_and_teams": "Riot match record",
                       "map_frame": "baked geometry shade_fit + valorant-api map constants",
                       "minimap_lag_ms": lag}
    ex = ra.Export(rp.match, rp=rp)
    cen = ra.actor_census(rp.match, ex)
    smap = ra.slot_map(cen)
    out["slot_map"] = smap
    my_agent = agent.get(me)
    my_code = None
    # the player's own world actors and casts, by ability display name
    mine = defaultdict(list)
    for r in cen["classes"]:
        if not r.get("code") or not r["mapped"]:
            continue
        for i in ex.instances(class_short=r["class"]):
            s, _ = ex.owner_subject(i["guid"])
            if s == me:
                my_code = r["code"]
                mine[r["class"]].append({**i, "ability": r["ability"]})
    C = ex.casts()["casts"]
    folder_name = {}
    for r in cen["classes"]:
        if r.get("folder"):
            folder_name[(r["code"], r["folder"])] = r["ability"]
    my_casts = []
    for c in C:
        if c["subject"] != me or c["t_ms"] is None:
            continue
        f = smap.get(f"{my_agent}|{c['slot']}")
        my_casts.append({**c, "ability": folder_name.get((my_code, f)) if f else None})
    ults = ex.ult_intervals()
    my_ults = [u for u in ults if u["subject"] == me]
    # the replay's casts of the player in capture time; an ult cast is its transition
    truth = [(c["t_ms"] + a, c["ability"]) for c in my_casts if c["ability"]]
    unk = [c for c in my_casts if not c["ability"]]
    out["player_replay_casts"] = {"records": len(my_casts), "by_ability": dict(Counter(t[1] for t in truth)),
                                  "slot_unmapped": dict(Counter(c["slot"] for c in unk)),
                                  "ult_transitions": len(my_ults)}
    x_name = next((r["ability"] for r in cen["classes"] if r.get("code") == my_code
                   and r.get("folder") == "Ability_X"), None)
    if x_name is None and my_code:
        x_name = ra.ability_display(my_code, "Ability_X")["display"]
    truth_x = [(u["on_ms"] + a, x_name) for u in my_ults]
    truth_all = [t for t in truth if t[1] != x_name] + truth_x

    # slot key (tray catalogue) -> ability name, from the stored ability_state rows
    key_name = {}
    for r in rt._rows(ra.STORE / "events" / "ability_state" / f"{sid}.jsonl", '"kind":"state"'):
        key_name.setdefault(r["slot"], r.get("ability"))
    out["tray_keys"] = key_name

    # -- tray_drop: player casts, and the drops refused for a reason
    drops = [r for r in rt._rows(ra.STORE / "events" / "tray_drop" / f"{sid}.jsonl")
             if r.get("kind") == "drop"]
    det = [(r["t_ms"], key_name.get(r["slot"])) for r in drops if r.get("player_cast")]
    out["tray_drop"] = {"casts": _ra_cast_score(det, truth_all)}
    # a refused drop that sits on a replay cast the player-cast set missed
    paired_truth = set()
    idx_of, det_of = defaultdict(list), defaultdict(list)
    for k, (_t, ab_) in enumerate(truth_all):
        idx_of[ab_].append(k)
    for t_, ab_ in det:
        det_of[ab_].append(t_)
    for ab in {t[1] for t in truth_all}:
        idx = idx_of[ab]
        for _i, j, _e in _ra_pair(det_of.get(ab, []), [truth_all[k][0] for k in idx], ra.CAST_GATE_MS):
            paired_truth.add(idx[j])
    missed = [truth_all[k] for k in range(len(truth_all)) if k not in paired_truth]
    ref_d = [r for r in drops if not r.get("player_cast")]
    # the refused drops and the replay casts as arrays: each test below is one
    # vectorised pass instead of a scan of the other list per element
    ref_t = np.array([r["t_ms"] for r in ref_d], float)
    ref_ab = np.array([key_name.get(r["slot"]) for r in ref_d] + [None], object)[:-1]
    tru_t = np.array([t[0] for t in truth_all], float)
    tru_ab = np.array([t[1] for t in truth_all] + [None], object)[:-1]
    why = Counter()
    for t, ab in missed:
        near = np.flatnonzero((ref_ab == ab) & (np.abs(ref_t - t) <= ra.CAST_GATE_MS))
        why[(ab, ref_d[near[0]].get("reason") if near.size else "no_drop")] += 1
    out["tray_drop"]["missed_by_reason"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(why.items(), key=str)}
    rr = Counter()
    for r in ref_d:
        ab = key_name.get(r["slot"])
        hit = bool(((tru_ab == ab) & (np.abs(tru_t - r["t_ms"]) <= ra.CAST_GATE_MS)).any())
        rr[(r.get("reason"), "on_replay_cast" if hit else "no_replay_cast")] += 1
    out["tray_drop"]["refused_drops"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(rr.items(), key=str)}

    # -- ability_state: cast verdicts, and kit_end against the player's deaths
    st = list(rt._rows(ra.STORE / "events" / "ability_state" / f"{sid}.jsonl", '"kind":"verdict"'))
    det = [(r["t_ms"], key_name.get(r["slot"])) for r in st if r["transition"] == "cast"]
    out["ability_state"] = {"cast_verdicts": _ra_cast_score(det, truth_all),
                            "transitions": dict(Counter(r["transition"] for r in st))}
    my_deaths = np.array([e["t"] + a for e in rp.group("characterDeath") if e.get("victim") == me])
    kd = sorted({r["t_ms"] for r in st if r["transition"] == "owner_death"})
    p = _ra_pair(kd, my_deaths, 3000.0)
    out["ability_state"]["owner_death"] = {
        "stored": len(kd), "replay_deaths": int(my_deaths.size), "paired": len(p),
        "stored_minus_replay_ms": ra._stats([x[2] for x in p], 1)}

    # -- ability_shape: Recon Bolt rings and Hunter's Fury beams
    out["ability_shape"] = _ra_shape(sid, rp, mf, a, lag, me, mine, my_ults, ex)

    # -- player's tray-object marks and the glyph eval's labelled points
    out["labels"] = _ra_labels(sid, rp, mf, a, lag, me, mine, my_ults, ex)

    # -- ult_cast
    out["ult_cast"] = _ra_ults(sid, a, ults, agent, team, me)

    # -- spike: replay_truth's carrier check plus the planted spike's placement
    sp = _replay_spike(sid, rp, mf, ctx["clock"], allies, foes, team, me)
    sp["planted"] = _ra_planted(sid, rp, mf, a, lag, ex)
    out["spike"] = sp

    # -- smoke and the other minimap ability streams: stored rows or a refusal
    out["streams_without_rows"] = {}
    for name in ("smoke", "smoke_owner", "ability", "ability_icon", "ability_fit", "ability_gate",
                 "ability_light", "ability_wall", "minimap_object", "ability_shape_scan"):
        pth = ra.STORE / "events" / name / f"{sid}.jsonl"
        if not pth.is_file():
            out["streams_without_rows"][name] = "no_stored_rows_for_session"
    out["replay_truth_available"] = {
        r["mapped"]: r["opens"] for r in cen["classes"] if r["mapped"]}
    return out


def _ra_bolt_truth(rows, t_rep):
    """(n, k) world x, y of the instances in `rows` alive at replay times `t_rep`."""
    n, k = t_rep.size, len(rows)
    X, Y = np.full((n, k), np.nan), np.full((n, k), np.nan)
    for c, r in enumerate(rows):
        end = r["close_ms"] if r["close_ms"] is not None else np.inf
        live = (t_rep >= r["open_ms"]) & (t_rep <= end)
        X[live, c], Y[live, c] = r["xyz"][0], r["xyz"][1]
    return X, Y


def _ra_shape(sid, rp, mf, a, lag, me, mine, my_ults, ex) -> dict:
    rows = [r for r in rt._rows(ra.STORE / "events" / "ability_shape" / f"{sid}.jsonl")
            if r.get("kind") == "shape"]
    out = {}
    rb = [r for r in rows if r["ability"] == "Recon Bolt"]
    bolts = mine.get("GameObject_Hunter_Q_SonarBolt_C", [])
    if rb:
        t = np.array([r["t_ms"] for r in rb], float)
        t_rep = rt._frames_to_replay(t, a, lag)
        X, Y = _ra_bolt_truth(bolts, t_rep)
        PX, PY = rt.to_px(mf, X, Y)
        cx = np.array([r["cx"] for r in rb], float)[:, None]
        cy = np.array([r["cy"] for r in rb], float)[:, None]
        D = np.hypot(PX - cx, PY - cy)
        alive = np.isfinite(D).any(axis=1)
        dmin = np.where(alive, np.nanmin(np.where(np.isfinite(D), D, np.inf), axis=1), np.nan)
        found = np.array([bool(r["found"]) for r in rb])
        rr = np.array([r.get("r") or np.nan for r in rb], float)
        out["recon_bolt"] = {
            "rows": len(rb), "found": int(found.sum()),
            "replay_bolts_of_player": len(bolts),
            "rows_with_bolt_alive": int(alive.sum()),
            "found_with_bolt": int((found & alive).sum()),
            "found_without_bolt": int((found & ~alive).sum()),
            "not_found_with_bolt": int((~found & alive).sum()),
            "not_found_without_bolt": int((~found & ~alive).sum()),
            "recall_rows": round(float((found & alive).sum() / alive.sum()), 4) if alive.any() else None,
            "found_centre_err_px": ra._stats(dmin[found & alive]),
            "found_centre_err_cm": ra._stats(dmin[found & alive] / mf.px_per_unit, 0),
            "found_centre_inside_ring": int(np.sum(dmin[found & alive] <= rr[found & alive])),
            "not_found_fit_err_px": ra._stats(dmin[~found & alive])}
        # per cast: the stored rows' span against the bolt's replay lifetime
        per = []
        bolt_open = np.array([x["open_ms"] for x in bolts], float)
        for ct in sorted({r["cast_t_ms"] for r in rb}):
            m = np.array([r["cast_t_ms"] == ct for r in rb])
            ctr = ct - a
            b = [bolts[i] for i in np.flatnonzero((ctr - 500 <= bolt_open) & (bolt_open <= ctr + 6000))]
            fm = m & found
            per.append({"cast_t_ms": round(ct, 1), "rows": int(m.sum()), "found": int(fm.sum()),
                        "replay_bolt": bool(b),
                        "bolt_open_after_cast_ms": round(b[0]["open_ms"] - ctr, 1) if b else None,
                        "bolt_life_s": (round((b[0]["close_ms"] - b[0]["open_ms"]) / 1000.0, 3)
                                        if b and b[0]["close_ms"] else None),
                        "found_first_minus_open_ms": (round(float(t[fm].min() - lag - a - b[0]["open_ms"]), 1)
                                                      if b and fm.any() else None),
                        "found_last_minus_close_ms": (round(float(t[fm].max() - lag - a - b[0]["close_ms"]), 1)
                                                      if b and fm.any() and b[0]["close_ms"] else None)})
        out["recon_bolt"]["per_cast"] = per
        out["recon_bolt"]["casts_with_replay_bolt"] = sum(p["replay_bolt"] for p in per)
        L = [p["bolt_life_s"] for p in per if p["bolt_life_s"]]
        out["recon_bolt"]["bolt_life_s"] = ra._stats(L, 3)
        f0 = [p["found_first_minus_open_ms"] for p in per if p["found_first_minus_open_ms"] is not None]
        f1 = [p["found_last_minus_close_ms"] for p in per if p["found_last_minus_close_ms"] is not None]
        out["recon_bolt"]["found_first_minus_open_ms"] = ra._stats(f0, 1)
        out["recon_bolt"]["found_last_minus_close_ms"] = ra._stats(f1, 1)
    hf = [r for r in rows if r["ability"] == "Hunter's Fury"]
    if hf:
        t = np.array([r["t_ms"] for r in hf], float)
        t_rep = rt._frames_to_replay(t, a, lag)
        on = np.zeros(t.size, bool)
        for u in my_ults:
            on |= (t_rep >= u["on_ms"]) & (t_rep <= (u["off_ms"] or np.inf))
        q = rp.sample(me, t_rep)
        sx, sy = rt.to_px(mf, q["x"], q["y"])
        fyaw = rt.facing_px_deg(mf, q["x"], q["y"], q["yaw"])
        x0 = np.array([r["x0"] for r in hf]); y0 = np.array([r["y0"] for r in hf])
        x1 = np.array([r["x1"] for r in hf]); y1 = np.array([r["y1"] for r in hf])
        dx, dy = x1 - x0, y1 - y0
        L = np.hypot(dx, dy)
        perp = np.abs(dx * (sy - y0) - dy * (sx - x0)) / np.where(L > 0, L, np.nan)
        th = np.mod(np.degrees(np.arctan2(dy, dx)), 180.0)
        dth = np.abs(np.mod(th - np.mod(fyaw, 180.0) + 90.0, 180.0) - 90.0)
        found = np.array([bool(r["found"]) for r in hf])
        out["hunters_fury"] = {"rows": len(hf), "found": int(found.sum()),
                               "rows_in_replay_ult": int(on.sum()),
                               "found_outside_ult": int((found & ~on).sum()),
                               "line_to_sova_px": ra._stats(perp[found & on]),
                               "line_vs_view_yaw_deg": ra._stats(dth[found & on]),
                               "ult_windows": len(my_ults)}
    return out


def _ra_labels(sid, rp, mf, a, lag, me, mine, my_ults, ex) -> dict:
    """The player's tray-object marks and the glyph eval's labelled points
    against the replay's actor of the named ability.

    Owl Drone: the drone pawn's track, point error. Recon Bolt: the stuck bolt;
    the player marked the bolt once and the ring round it otherwise
    [domain:abilities/sova-recon-bolt-minimap-ring], so a mark within half the
    ring's radius scores as a centre mark (distance to the bolt) and any other
    as a ring mark (distance minus the stored descriptor's radius). Hunter's
    Fury: the perpendicular distance to the line from Sova's replay position
    along the view yaw, while the replay's ult is active."""
    marks = []
    for r in rt._rows(ra.STORE / "labels" / "tray_object" / f"{sid}.jsonl"):
        for m in r.get("marks") or []:
            marks.append((r["ability"], float(m["t_ms"]), float(m["x"]), float(m["y"])))
    gi = ra.STORE / "analysis" / "minimap-glyphs-20261004" / "items.json"
    glyph = []
    if gi.is_file():
        items = json.loads(gi.read_text(encoding="utf-8"))
        for it in (items if isinstance(items, list) else items.get("items") or []):
            if it.get("sid") == sid:
                glyph.append((it["cat"].split(":")[-1].strip(), float(it["t_ms"]),
                              float(it["x"]), float(it["y"])))
    drones = mine.get("Pawn_Hunter_E_Drone_C", [])
    bolts = mine.get("GameObject_Hunter_Q_SonarBolt_C", [])
    ring_r = next((r["descriptor"]["radius_px"] for r in
                   rt._rows(ra.STORE / "events" / "ability_shape" / f"{sid}.jsonl", '"Recon Bolt"')
                   if r.get("kind") == "shape" and r.get("descriptor")), None)

    def drone_px(t_rep):
        for d in drones:
            if d["open_ms"] <= t_rep <= (d["close_ms"] or np.inf):
                tt, xx, yy = ex.pawn_track(d["guid"])
                if tt.size < 2:
                    return None
                k = int(np.clip(np.searchsorted(tt, t_rep), 1, tt.size - 1))
                if min(abs(tt[k] - t_rep), abs(tt[k - 1] - t_rep)) > rt.MAX_GAP_MS:
                    return None
                w = float(np.clip((t_rep - tt[k - 1]) / max(tt[k] - tt[k - 1], 1.0), 0, 1))
                px, py = rt.to_px(mf, [xx[k - 1] * (1 - w) + xx[k] * w],
                                  [yy[k - 1] * (1 - w) + yy[k] * w])
                return float(px[0]), float(py[0])
        return None

    def bolt_px(t_rep):
        for b in bolts:
            if b["open_ms"] <= t_rep <= (b["close_ms"] or np.inf):
                px, py = rt.to_px(mf, [b["xyz"][0]], [b["xyz"][1]])
                return float(px[0]), float(py[0])
        return None

    def judge(ability, t_cap, x, y):
        t_rep = t_cap - a - lag
        ab = ability.lower()
        if ab == "owl drone":
            w = drone_px(t_rep)
            return None if w is None else ("point", float(np.hypot(w[0] - x, w[1] - y)))
        if ab == "recon bolt":
            w = bolt_px(t_rep)
            if w is None:
                return None
            d = float(np.hypot(w[0] - x, w[1] - y))
            if ring_r is None or d <= ring_r / 2.0:
                return ("centre", d)
            return ("ring", d - float(ring_r))
        if ab == "hunter's fury":
            if not any(u["on_ms"] <= t_rep <= (u["off_ms"] or np.inf) for u in my_ults):
                return None
            q = rp.sample(me, [t_rep])
            if not np.isfinite(q["x"][0]):
                return None
            sx, sy = rt.to_px(mf, q["x"], q["y"])
            th = np.radians(rt.facing_px_deg(mf, q["x"], q["y"], q["yaw"])[0])
            return ("line", float(abs(np.cos(th) * (y - sy[0]) - np.sin(th) * (x - sx[0]))))
        return None

    out = {"ring_radius_px": ring_r}
    for name, rows in (("tray_object_marks", marks), ("glyph_eval_points", glyph)):
        res = defaultdict(list)
        unscored = Counter()
        for ab, t, x, y in rows:
            j = judge(ab, t, x, y)
            if j is None:
                unscored[ab] += 1
                continue
            res[f"{ab}|{j[0]}"].append(round(j[1], 2))
        out[name] = {"n": len(rows), "unscored_no_replay_actor": dict(unscored),
                     "err_px": {k: ra._stats(v) for k, v in sorted(res.items())}}
    # the player's "nothing on the minimap" answers against the replay
    nothing = []
    for r in rt._rows(ra.STORE / "labels" / "tray_object" / f"{sid}.jsonl"):
        if r.get("class") == "nothing_on_minimap":
            t_rep = r["t_drop_s"] * 1000.0 - a
            hit = {}
            for k, v in mine.items():
                for x in v:
                    if t_rep - 1000 <= x["open_ms"] <= t_rep + 3000:
                        hit[k] = (round(x["open_ms"] - t_rep, 1), None if x["close_ms"] is None
                                  else round((x["close_ms"] - x["open_ms"]) / 1000.0, 3))
            nothing.append({"ability": r["ability"], "t_drop_s": r["t_drop_s"],
                            "replay_actors_open_after_drop_ms_life_s": hit})
    out["nothing_on_minimap"] = nothing
    return out


def _ra_ults(sid, a, ults, agent, team, me) -> dict:
    rows = [r for r in rt._rows(ra.STORE / "events" / "ult_cast" / f"{sid}.jsonl")
            if r.get("kind") in ("cast", "refusal")]
    side = {s: ("ally" if team.get(s) == team[me] else "enemy") for s in team}
    tru = [(u["on_ms"] + a, f"{agent.get(u['subject'])}|{'own' if u['subject'] == me else side.get(u['subject'])}")
           for u in ults]

    def lab(r):
        v = r.get("side") or r.get("variant")
        v = "own" if v in ("own", "self") or r.get("player_cast") else v
        return f"{r.get('agent') or r.get('template_agent')}|{v}"

    casts = [r for r in rows if r["kind"] == "cast"]
    det = [(float(r["t_ms"]), lab(r)) for r in casts]
    # any agent and side: does a replay ult sit under each stored cast at all?
    p_any = _ra_pair([d[0] for d in det], [t[0] for t in tru], ra.ULT_GATE_MS)
    res = {"stored_casts": len(det), "replay_ults": len(tru),
           "replay_by_label": dict(Counter(t[1] for t in tru)),
           "stored_by_label": dict(Counter(d[1] for d in det)),
           "by_label": _ra_cast_score(det, tru, ra.ULT_GATE_MS),
           "paired_any_label": len(p_any),
           "any_label_stored_minus_replay_ms": ra._stats([x[2] for x in p_any], 1)}
    pl = _ra_pair([d[0] for d in det], [t[0] for t in tru], ra.ULT_GATE_MS)
    res["paired_label_agrees"] = sum(det[i][1] == tru[j][1] for i, j, _ in pl)
    pr = sum(v["paired"] for v in res["by_label"].values())
    res["paired_same_label"] = pr
    res["recall"] = round(pr / len(tru), 4) if tru else None
    res["precision"] = round(pr / len(det), 4) if det else None
    # refusals: was a replay ult of the template's agent near?
    rf = Counter()
    tru_t = np.array([t[0] for t in tru], float)
    tru_ag = np.array([t[1].split("|")[0] for t in tru] + [None], object)[:-1]
    for r in rows:
        if r["kind"] != "refusal":
            continue
        ag = r.get("template_agent")
        hit = bool(((np.abs(tru_t - float(r["t_ms"])) <= ra.ULT_GATE_MS) & (tru_ag == ag)).any())
        rf[(r.get("reason"), "replay_ult_of_agent" if hit else "no_replay_ult_of_agent")] += 1
    res["refusals"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(rf.items(), key=str)}
    return res


def _ra_planted(sid, rp, mf, a, lag, ex) -> dict:
    """Dropped-or-planted spike glyphs against the planted spike (`TimedBomb_C`)."""
    bombs = ex.instances(class_short="TimedBomb_C")
    gx, gy, gt = [], [], []
    for r in rt._rows(ra.STORE / "events" / "spike" / f"{sid}.jsonl", '"kind":"frame"'):
        if r.get("reason") is not None:
            continue
        for g in r.get("glyphs") or []:
            if g.get("reason") is None and g.get("state") == "dropped":
                gx.append(g["cx"]); gy.append(g["cy"]); gt.append(r["t_ms"])
    if not gt:
        return {"refused": "no_dropped_glyphs"}
    t_rep = rt._frames_to_replay(np.array(gt, float), a, lag)
    X, Y = _ra_bolt_truth(bombs, t_rep)
    PX, PY = rt.to_px(mf, X, Y)
    D = np.hypot(PX - np.array(gx)[:, None], PY - np.array(gy)[:, None])
    alive = np.isfinite(D).any(axis=1)
    dmin = np.where(alive, np.nanmin(np.where(np.isfinite(D), D, np.inf), axis=1), np.nan)
    # frames where the replay has a planted spike: how many carry a dropped glyph
    grid = sorted({r["t_ms"] for r in rt._rows(ra.STORE / "events" / "spike" / f"{sid}.jsonl", '"kind":"frame"')
                   if r.get("reason") is None})
    g_rep = rt._frames_to_replay(np.array(grid, float), a, lag)
    Xg, _ = _ra_bolt_truth(bombs, g_rep)
    planted_frames = np.isfinite(Xg).any(axis=1)
    have = set(np.round(gt, 1).tolist())
    with_glyph = np.array([round(t, 1) in have for t in grid])
    return {"plants": len(bombs), "dropped_glyphs": len(gt),
            "glyphs_while_planted": int(alive.sum()),
            "glyph_err_px_while_planted": ra._stats(dmin[alive]),
            "planted_frames": int(planted_frames.sum()),
            "planted_frames_with_glyph": int((planted_frames & with_glyph).sum())}


def record_replay_abilities(s: dict) -> list[str]:
    """`replay_abilities_score`'s values in the `replay_abilities` series,
    part `score`, as `replay_abilities score --record` wrote them."""
    from reticle import metrics
    v = {}
    for ab, x in s["tray_drop"]["casts"].items():
        k = re.sub(r"[^a-z]", "_", str(ab).lower())
        v[f"tray_{k}_paired"] = x["paired"]
        v[f"tray_{k}_replay"] = x["replay"]
        v[f"tray_{k}_false"] = x["false"]
        if x["stored_minus_replay_ms"]:
            v[f"tray_{k}_dt_ms_median"] = x["stored_minus_replay_ms"]["median"]
    for ab, x in s["ability_state"]["cast_verdicts"].items():
        k = re.sub(r"[^a-z]", "_", str(ab).lower())
        v[f"state_{k}_paired"] = x["paired"]
        v[f"state_{k}_replay"] = x["replay"]
    rb = s["ability_shape"].get("recon_bolt") or {}
    for k in ("rows", "found", "rows_with_bolt_alive", "found_with_bolt", "found_without_bolt",
              "not_found_with_bolt", "recall_rows", "replay_bolts_of_player", "casts_with_replay_bolt"):
        v[f"rb_{k}"] = rb.get(k)
    v["rb_err_px_median"] = (rb.get("found_centre_err_px") or {}).get("median")
    v["rb_err_px_p90"] = (rb.get("found_centre_err_px") or {}).get("p90")
    v["rb_bolt_life_s_median"] = (rb.get("bolt_life_s") or {}).get("median")
    hf = s["ability_shape"].get("hunters_fury") or {}
    v["hf_line_to_sova_px_median"] = (hf.get("line_to_sova_px") or {}).get("median")
    v["hf_angle_deg_median"] = (hf.get("line_vs_view_yaw_deg") or {}).get("median")
    u = s["ult_cast"]
    v.update({"ult_stored": u["stored_casts"], "ult_replay": u["replay_ults"],
              "ult_paired_same_label": u["paired_same_label"], "ult_paired_any": u["paired_any_label"],
              "ult_recall": u["recall"], "ult_precision": u["precision"],
              "ult_dt_ms_median": (u["any_label_stored_minus_replay_ms"] or {}).get("median")})
    lb = s["labels"]
    for name, short in (("glyph_eval_points", "glyph"), ("tray_object_marks", "marks")):
        for k, st in (lb[name]["err_px"] or {}).items():
            key = re.sub(r"[^a-z]", "_", k.lower())
            v[f"{short}_{key}_n"] = (st or {}).get("n")
            v[f"{short}_{key}_px_median"] = (st or {}).get("median")
    pl = s["spike"].get("planted") or {}
    v["planted_glyph_err_px_median"] = (pl.get("glyph_err_px_while_planted") or {}).get("median")
    v["planted_frames"] = pl.get("planted_frames")
    v["planted_frames_with_glyph"] = pl.get("planted_frames_with_glyph")
    metrics.record("replay_abilities", part="score", session=s["session"], values=v,
                   deps={"replay_abilities": ra.REPLAY_ABILITIES_VERSION, "vrfkit": rt.VRFKIT_VERSION,
                         "minimap_lag_ms": rt.MINIMAP_LAG_MS, "cast_gate_ms": ra.CAST_GATE_MS,
                         "ult_gate_ms": ra.ULT_GATE_MS})
    return [f"[metric:replay_abilities/score#{k}={x}]" for k, x in v.items()]


#: What each `replay_score` phantom claims: a teammate observation claims a
#: teammate (or the player), an enemy icon an enemy player.
REPLAY_CLAIMS = {"teammate": ("player_ally", "player_self"), "enemy": ("player_enemy",)}
#: Why the class-aware blocks leave a find out, printed beside the counts.
REPLAY_LEFT_OUT = {
    "off_grid": "the find's frame joins no live grid sample (outside live play or the capture's spans)",
    "spike_not_planted": "a dropped spike glyph while no planted spike lives: the spike item "
                         f"(BombEquippable_C) is not joined: {NOT_JOINED['BombEquippable_C']}",
    "spike_carried": "a carried spike glyph rides its carrier; the spike item is not joined",
    "shape_line": "a Hunter's Fury beam is a line, not a point; `hunters_fury` scores it",
}


def _norm(s) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _live_rounds(M) -> list:
    """The rounds holding a live grid sample (`enemy_lane_check.live_samples`)."""
    from . import sets as elc
    live, _ = elc.live_samples(M)
    return sorted({int(r) for r in np.asarray(M.G_round)[live]})


def _class_block(rows: list, rec: dict, rounds: list, census: dict, extra: dict) -> dict:
    rounds = sorted(set(rounds) | {r["round"] for r in rows})
    doc, per = _step_summary(rows, rec, rounds, census, extra)
    return {"rows": rows, "classes": doc, "_per": per}


def _grid_finds(M, to_cm, t_cap, px, py, claim, meta, keep=None) -> tuple[dict, np.ndarray, np.ndarray, int]:
    """Finds at stream frames `t_cap` on T1d's grid (`_frames_on_grid`):
    the finds, every frame's sample and replay time, and how many of the
    kept frames join no sample."""
    t_cap = np.asarray(t_cap, float)
    keep = np.ones(t_cap.size, bool) if keep is None else np.asarray(keep, bool)
    k, trep = _frames_on_grid(M, t_cap, np.ones(t_cap.size, bool))
    i = np.flatnonzero(keep & (k >= 0))
    F = _finds(k[i], t_cap[i], trep[i], np.asarray(px, float)[i], np.asarray(py, float)[i], to_cm,
               [claim[j] for j in i], [meta[j] for j in i])
    return F, k, trep, int((keep & (k < 0)).sum())


def replay_classes(sid: str, s: dict) -> dict:
    """Step 9: `replay_score`'s phantoms against every replay entity.

    `replay_score` calls an observation a phantom when no living player of
    its claimed side lies within 8 m (one to one, players only). Here each
    phantom (a `round_entity` teammate observation, a `minimap_object` enemy
    icon) joins every replay entity at its frame's grid sample
    (`_join_entities`) and takes its outcome (`claim_outcome`): a phantom on
    another real entity is that entity's, on nothing `nothing_there`, on an
    unmapped actor a named coverage gap."""
    ctx = _truth_ctx(sid)
    M = ctx["M"]
    to_cm = _to_cm(sid)
    rounds = _live_rounds(M)
    G_last, raw = None, {}
    for name, fams in REPLAY_CLAIMS.items():
        ph = s["_finds"][name]
        n = int(np.asarray(ph["t_cap"]).size)
        fam = ph.get("family")
        meta = [{"frame_idx": int(ph["frame_idx"][i]), **({"obs_family": str(fam[i])} if fam is not None else {})}
                for i in range(n)]
        F, _k, _t, off = _grid_finds(M, to_cm, ph["t_cap"], ph["px"], ph["py"], [None] * n, meta)
        rows, G_ = _score_finds(ctx, F, claimed=lambda d, fams=fams: d["family"] in fams,
                                near_side="enemy" if name == "enemy" else "ally")
        raw[name] = (rows, n, off)
        G_last = G_
    census = _session_census(ctx, G_last)
    out = {}
    for name, (rows, n, off) in raw.items():
        out[name] = _class_block(rows, {}, rounds, census, {"phantoms": n, "left_out": {"off_grid": off}})
    return out


def replay_ability_classes(sid: str) -> dict:
    """Step 9: the point finds of the streams `replay_abilities_score` reads,
    against every replay entity.

    * `shape`: each found `ability_shape` ring centre at its frame, claiming
      a child of the ability the shape names (`right_entity:name_right` on
      that ability's child, `name_wrong` on another ability's child); recall
      of the player's own children of those abilities over the samples of
      every shape row (the stream reads only after a cast);
    * `spike`: each dropped spike glyph of a read `spike` frame while a
      planted spike (`TimedBomb_C`) lives, claiming the spike; recall of the
      planted spike over the read frames. Dropped glyphs with no planted
      spike and carried glyphs are counted apart (`REPLAY_LEFT_OUT`)."""
    ctx = _truth_ctx(sid)
    M = ctx["M"]
    to_cm = _to_cm(sid)
    rounds = _live_rounds(M)
    ri = {r: i for i, r in enumerate(rounds)}
    C = M.tl0.children.cols
    G0 = _empty_join(ctx)
    out = {}

    # shapes
    sh = sorted((r for r in (_stream(sid, "ability_shape", '"shape"') or []) if r.get("kind") == "shape"),
                key=lambda r: r["t_ms"])
    pt = [r for r in sh if r.get("cx") is not None]
    t = np.array([r["t_ms"] for r in pt], float)
    found = np.array([bool(r.get("found")) for r in pt], bool)
    F, k_all, trep_all, off = _grid_finds(M, to_cm, t, [r["cx"] for r in pt], [r["cy"] for r in pt],
                                          [_norm(r["ability"]) for r in pt],
                                          [{"ability": r["ability"], "cast_t_ms": r.get("cast_t_ms")} for r in pt],
                                          keep=found)
    rows, G_ = _score_finds(ctx, F, claimed=lambda d: d["kind"] == "child" and str(d["family"]).startswith("ability_"),
                            name_of=lambda d: _norm(d["ability"]), near_side="ally")
    abil = {_norm(r["ability"]) for r in pt}
    sel = np.array([s_ is not None and s_ == M.me and _norm(a_) in abil
                    for s_, a_ in zip(C["subject"], C["ability"])], bool)
    on = k_all >= 0
    rec = _recall_children(M, G_, k_all[on], trep_all[on], sel, _assigned(rows, G_, "child"), ri, len(rounds),
                           key_of=lambda d: f"{d['key']} ({d['entity_class']})") if on.any() else {}
    out["shape"] = (rows, rec, {"shape_rows": len(sh), "point_rows": len(pt), "found": int(found.sum()),
                                "abilities": sorted({r["ability"] for r in pt}),
                                "left_out": {"off_grid": off, "shape_line": len(sh) - len(pt)},
                                "stamps": [_stream_stamp(sid, "ability_shape")]})

    # the planted spike
    planted = np.flatnonzero(G0["joinable"] & (C["cls"].astype(str) == "TimedBomb_C"))
    fr = sorted((r for r in (_stream(sid, "spike", '"kind":"frame"') or [])
                 if r.get("kind") == "frame" and r.get("reason") is None), key=lambda r: r["t_ms"])
    tf = np.array([r["t_ms"] for r in fr], float)
    gt, gx, gy, gm = [], [], [], []
    carried = 0
    for r in fr:
        for g in r.get("glyphs") or []:
            if g.get("reason") is not None:
                continue
            if g.get("state") == "dropped":
                gt.append(r["t_ms"])
                gx.append(g["cx"])
                gy.append(g["cy"])
                gm.append({"state": "dropped"})
            elif g.get("state") == "carried":
                carried += 1
    gt = np.array(gt, float)
    g_rep = np.asarray(M.to_rep(gt, rt.REMOTE_LAG_MS), float) if gt.size else np.zeros(0)
    in_plant = np.zeros(gt.size, bool)
    for c in planted:
        in_plant |= (g_rep >= G0["lo"][c] - WINDOW_MS) & (g_rep <= G0["hi"][c] + WINDOW_MS)
    F, _k, _t, off = _grid_finds(M, to_cm, gt, gx, gy, [None] * gt.size, gm, keep=in_plant)
    rows, G_ = _score_finds(ctx, F, claimed=lambda d: d["family"] == "spike", near_side="ally")
    k_f, trep_f = _frames_on_grid(M, tf, np.ones(tf.size, bool))
    on = k_f >= 0
    sel = np.isin(np.arange(C["cls"].size), planted)
    rec = _recall_children(M, G_, k_f[on], trep_f[on], sel, _assigned(rows, G_, "child"), ri, len(rounds),
                           key_of=lambda d: d["key"]) if on.any() and planted.size else {}
    out["spike"] = (rows, rec, {"dropped_glyphs": int(gt.size), "planted_spikes": int(planted.size),
                                "left_out": {"off_grid": off, "spike_not_planted": int((~in_plant).sum()),
                                             "spike_carried": carried},
                                "stamps": [_stream_stamp(sid, "spike")]})
    census = _session_census(ctx, G_)
    return {name: _class_block(rows, rec, rounds, census, extra) for name, (rows, rec, extra) in out.items()}


def _pool_blocks(res: list[dict], key: str = "blocks") -> dict:
    """Each block pooled over the sessions holding it (`_pool_classes`)."""
    names = sorted({n for r in res for n in (r.get(key) or {})})
    pooled = {}
    for name in names:
        have = [r for r in res if name in (r.get(key) or {})]
        if len(have) > 1:
            pooled[name] = _pool_classes([{"session": r["session"], "classes": r[key][name]["classes"]}
                                          for r in have], [{"classes": r[key][name]["_per"]} for r in have])
            pooled[name]["left_out"] = dict(sum((Counter(r[key][name]["classes"].get("left_out") or {})
                                                 for r in have), Counter()))
    return pooled


def _print_blocks(scope: str, blocks: dict) -> None:
    for name, b in blocks.items():
        c = b["classes"] if "classes" in b else b
        print(f"   {scope} {name}: left out {c.get('left_out')} "
              + " ".join(f"{k}={c[k]}" for k in ("phantoms", "found", "dropped_glyphs", "planted_spikes")
                         if k in c), flush=True)
        _print_classes(f"{scope} {name}", c, fa=False)


def _write_blocks(sub: str, sid: str, blocks: dict) -> None:
    d = OUT / "steps" / sub
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{sid}.jsonl", "w", encoding="utf-8") as f:
        for name, b in blocks.items():
            for row in b["rows"]:
                f.write(json.dumps({"block": name, **row}, default=str) + "\n")


def run_replay_score(sessions: list[str], geometry: Path | None, legacy_out: str | None, record: bool,
                     record_score: bool) -> int:
    """`replay-score`: `replay_score` per session, its phantoms against every
    replay entity on the development matches (`replay_classes`), pooled with
    round-bootstrap intervals. The report goes to `OUT/replay/SESSION.json`;
    `--legacy-out NAME` also writes the report alone where `replay_truth
    score` wrote it (`replay_truth.ANALYSIS`)."""
    for sid in sessions:
        if tr.never_read(sid):
            raise SystemExit(f"{sid}: the held-out match is never read by this harness")
    res = []
    for sid in sessions:
        t0 = time.perf_counter()
        s = replay_score(sid, geometry, finds=True)
        fi = s.pop("_finds", None)
        if legacy_out:
            rt.ANALYSIS.mkdir(parents=True, exist_ok=True)
            name = legacy_out if len(sessions) == 1 else f"{sid}_{legacy_out}"
            (rt.ANALYSIS / name).write_text(json.dumps(s, indent=1, default=rt._default), encoding="utf-8")
        why = ("refused: " + str(s["refused"]) if "refused" in s else
               "neither a development match nor a 2026-10-07 replay capture" if sid not in SCORED else
               "--geometry: the truth join reads the session's own geometry" if geometry else None)
        blocks = {} if why else replay_classes(sid, {"_finds": fi})
        _print_replay(sid, s)
        _print_blocks(sid, blocks)
        if why:
            print(f"   {sid} class-aware blocks: {why}", flush=True)
        _write_blocks("replay", sid, blocks)
        doc = {"session": sid, "version": VERSION, "report": s, "classes_refused": why,
               "classes": {n: b["classes"] for n, b in blocks.items()}, "secs": round(time.perf_counter() - t0, 1)}
        (OUT / "replay").mkdir(parents=True, exist_ok=True)
        (OUT / "replay" / f"{sid}.json").write_text(json.dumps(tr.label(doc, [sid]), indent=1, default=rt._default), encoding="utf-8")
        if record_score and "refused" not in s:
            print("\n".join(record_replay_score(s)), flush=True)
        res.append({"session": sid, "blocks": blocks})
    pooled = _pool_blocks(res)
    if pooled:
        _print_blocks("pooled", {n: {"classes": c} for n, c in pooled.items()})
    _finish_blocks("replay", sessions, res, pooled, record,
                   note="replay_score's phantoms (round_entity teammates, minimap_object enemies with no living "
                        "player of the claimed side within 8 m) against every replay entity")
    return 0


def _print_replay(sid: str, s: dict) -> None:
    """`replay_score`'s headline, as a line per block."""
    if "refused" in s:
        print(f"{sid} replay_score refused: {s['refused']}", flush=True)
        return
    T, E = s["teammates"], s["enemies"]
    print(f"{sid} replay_score ({rt.REPLAY_TRUTH_VERSION}): frames {s['frames']['scored']}; teammates recall "
          f"{T['pooled']['recall']} phantoms {T['pooled']['phantom']} ({T['pooled']['phantom_share']}); self recall "
          f"{s['self']['recall']}; enemy icons {E.get('icons')} phantoms {E.get('phantom')} "
          f"({E.get('phantom_share')}); names agreement {T['names']['agreement']}", flush=True)


def _finish_blocks(sub: str, sessions: list[str], res: list[dict], pooled: dict, record: bool, note: str) -> None:
    doc = {"step": sub, "version": VERSION, "boot": f"{tr.N_BOOT} round resamples, seed {tr.SEED}",
           "left_out_reasons": REPLAY_LEFT_OUT,
           "sessions": {r["session"]: {n: b["classes"] for n, b in (r.get("blocks") or {}).items()} for r in res},
           "pooled": pooled}
    name = f"step_{sub}" + _suffix(sessions)
    (OUT / f"{name}.json").write_text(json.dumps(tr.label(doc, sessions), indent=1, default=str), encoding="utf-8")
    if record:
        from .extras import record as rec
        scopes = [(sid, b) for sid, b in doc["sessions"].items() if b]
        if pooled:
            scopes.append((_pool_name(sessions), pooled))
        for scope, blocks in scopes:
            vals, ci = {}, {}
            for bn, c in blocks.items():
                vals[f"{bn}_finds"] = c["finds"]
                for o in CLASS_OUTCOMES:
                    vals[f"{bn}_{o}"] = c["outcomes"][o]
                    if c.get("outcomes_ci", {}).get(o) is not None:
                        ci[f"{bn}_{o}"] = c["outcomes_ci"][o]
                for lb, v in c["labels"].items():
                    if v >= 5 or lb.startswith("right_entity"):
                        nm = f"{bn}_{_metric_name(lb)}"
                        vals[nm] = v
                        if lb in c.get("labels_ci", {}):
                            ci[nm] = c["labels_ci"][lb]
                for k, v in c["recall"].items():
                    nm = f"{bn}_recall_{_metric_name(k)}"
                    vals[nm] = v["value"]
                    ci[nm] = v["ci"]
                    vals[nm + "_den"] = v["den"]
                for k, v in (c.get("left_out") or {}).items():
                    vals[f"{bn}_left_out_{k}"] = v
            rec("question_acceptance", part=sub, session=scope, values=vals, ci=ci,
                deps={"version": VERSION, "rule": "T1d", "window_ms": WINDOW_MS, "near_cm": NEAR_CM,
                      "ambig_cm": AMBIG_CM, "life_tail_ms": LIFE_TAIL_MS,
                      "replay_truth": rt.REPLAY_TRUTH_VERSION},
                context={"task": TASK9, "boot": doc["boot"], "sessions": sessions},
                note=note)


def run_replay_abilities(sessions: list[str], legacy_out: bool, record: bool, record_score: bool) -> int:
    """`replay-abilities`: `replay_abilities_score` per session and its point
    finds against every replay entity (`replay_ability_classes`) on the
    development matches. The report goes to `OUT/replay_abilities/SESSION.json`;
    `--legacy-out` also writes it where `replay_abilities score` wrote it
    (`replay_abilities.ANALYSIS`)."""
    for sid in sessions:
        if tr.never_read(sid):
            raise SystemExit(f"{sid}: the held-out match is never read by this harness")
    res = []
    for sid in sessions:
        t0 = time.perf_counter()
        s = replay_abilities_score(sid)
        if legacy_out:
            ra.ANALYSIS.mkdir(parents=True, exist_ok=True)
            (ra.ANALYSIS / f"{sid}.json").write_text(json.dumps(s, indent=1, default=rt._default), encoding="utf-8")
        why = ("refused: " + str(s["refused"]) if "refused" in s else
               "neither a development match nor a 2026-10-07 replay capture" if sid not in SCORED else None)
        blocks = {} if why else replay_ability_classes(sid)
        if "refused" in s:
            print(f"{sid} replay_abilities_score refused: {s['refused']}", flush=True)
        else:
            u = s["ult_cast"]
            print(f"{sid} replay_abilities_score ({ra.REPLAY_ABILITIES_VERSION}): tray casts "
                  f"{ {k: (v['paired'], v['replay']) for k, v in s['tray_drop']['casts'].items()} }; ult recall "
                  f"{u['recall']} precision {u['precision']}; spike planted {s['spike'].get('planted')}", flush=True)
        _print_blocks(sid, blocks)
        if why:
            print(f"   {sid} class-aware blocks: {why}", flush=True)
        _write_blocks("replay_abilities", sid, blocks)
        doc = {"session": sid, "version": VERSION, "report": s, "classes_refused": why,
               "classes": {n: b["classes"] for n, b in blocks.items()}, "secs": round(time.perf_counter() - t0, 1)}
        (OUT / "replay_abilities").mkdir(parents=True, exist_ok=True)
        (OUT / "replay_abilities" / f"{sid}.json").write_text(json.dumps(tr.label(doc, [sid]), indent=1, default=rt._default),
                                                             encoding="utf-8")
        if record_score and "refused" not in s:
            print("\n".join(record_replay_abilities(s)), flush=True)
        res.append({"session": sid, "blocks": blocks})
    pooled = _pool_blocks(res)
    if pooled:
        _print_blocks("pooled", {n: {"classes": c} for n, c in pooled.items()})
    _finish_blocks("replay_abilities", sessions, res, pooled, record,
                   note="ability_shape ring centres and dropped spike glyphs while planted against every replay entity")
    return 0


#: The budget's class-aware extras: an extra starts from the entity
#: `truth_under` puts under it. Only where that entity is an enemy player
#: (undrawn, or 3 to 8 m off) does the players-only split refine it.
BUDGET_REFINED = {"undrawn_truth": "vu_", "nothing_there:enemy_3_8m": "e38_"}


def budget_class(old_cls: str, label: str) -> str:
    """An extra's class-aware cause: its `truth_under` label, refined by the
    players-only class where the label names an enemy player
    (`BUDGET_REFINED`), with the old class kept beside it otherwise."""
    for lead, pre in BUDGET_REFINED.items():
        if label == lead:
            return f"{label}:{old_cls}" if old_cls.startswith(pre) else f"{label}:other:{old_cls}"
    if label.startswith("right_entity"):
        return f"{label}:{old_cls}"
    return label


def _budget_tables(C: dict, sessions: list[str], key: str, orders: dict, quiet: bool = False) -> dict:
    """The budget's Pareto tables per match and pooled, as
    `enemy_error_budget.budget` builds them: per class the count and share
    with 95% intervals from a bootstrap over rounds, stratified by match
    (`enemy_error_budget._boot`), rows by count, the cumulative share."""
    from . import budget as eb
    tables = {}
    scopes = [(sid, [sid]) for sid in sessions] + ([("pooled", sessions)] if len(sessions) > 1 else [])
    for scope, sids in scopes:
        tables[scope] = {}
        for st, order in orders.items():
            rounds = {s: sorted({f["round"] for f in C[s]}) for s in sids}
            ri = {s: {r: i for i, r in enumerate(rounds[s])} for s in sids}
            den = {s: np.zeros(len(rounds[s])) for s in sids}
            cnt = {c: {s: np.zeros(len(rounds[s])) for s in sids} for c in order}
            for s in sids:
                for f in C[s]:
                    if f["set"] == st:
                        den[s][ri[s][f["round"]]] += 1
                        cnt[f[key]][s][ri[s][f["round"]]] += 1
            N = int(sum(d.sum() for d in den.values()))
            rows = []
            for c in order:
                n = int(sum(v.sum() for v in cnt[c].values()))
                ci_n, ci_s = eb._boot(rounds, cnt[c], den)
                rows.append({"cls": c, "n": n, "share": round(n / N, 4) if N else None,
                             "n_ci": ci_n, "share_ci": ci_s})
            rows.sort(key=lambda r: -r["n"])
            cum = 0
            for r in rows:
                cum += r["n"]
                r["cum_share"] = round(cum / N, 4) if N else None
            tables[scope][st] = {"total": N, "rows": rows}
            if not quiet:
                print(f"\n{scope} {key} {st}: {N}", flush=True)
                for r in rows:
                    if r["n"]:
                        print(f"  {r['cls']:64s} {r['n']:5d} [{r['n_ci'][0]:4d},{r['n_ci'][1]:4d}] "
                              f"{r['share']:7.3f} [{r['share_ci'][0]:.3f},{r['share_ci'][1]:.3f}] "
                              f"{r['cum_share']:6.3f}", flush=True)
    return tables


def _lane_rows(tag: str, sid: str) -> dict:
    """The lane's class-aware rows (`lane`'s `classes_SESSION.jsonl`, this
    version's), by (sample, frame, icon px)."""
    docs = [OUT / f"lane_{tag}.json", OUT / f"lane_{tag}_{sid}.json"]
    ok = False
    for p in docs:
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("version") == VERSION and sid in (d.get("sessions") or {}):
                ok = True
    if not ok:
        raise SystemExit(f"{sid} {tag}: no {VERSION} lane run holds this session; run `lane --tag {tag}` first")
    out = {}
    with open(OUT / tag / f"classes_{sid}.jsonl", encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            key = (int(r["k"]), int(r["frame_idx"]), round(r["icon_px"][0], 1), round(r["icon_px"][1], 1))
            out.setdefault(key, []).append(r)
    return out


def run_budget(tag: str, sessions: list[str], record: bool, rewrite: bool = False) -> int:
    """`budget --tag TAG`: the enemy lane's error budget, class-aware.

    Misses keep the players-only classes (`enemy_error_budget.MISS_ORDER`:
    a T1d-drawn enemy is one entity already). Each extra starts from the
    entity `truth_under` puts under it (the lane run's class rows), then the
    players-only class refines only an enemy-player label (`budget_class`).
    The players-only budget is the control: recomputed from the stored
    features, it must equal the stored `enemy_error_budget` tables and
    classed rows; it is rewritten there only when they are absent, or with
    `--rewrite`."""
    from . import budget as eb
    C, ctl = {}, {}
    for sid in sessions:
        tr.refuse(sid)
        C[sid] = eb.classify(eb._load_feats(tag, sid))
        sc = json.loads((eb.SRC / tag / f"score_{sid}.json").read_text(encoding="utf-8"))
        got = Counter(f["set"] for f in C[sid])
        if got["miss"] != sc["misses"] or got["extra"] != sc["extras"]:
            raise SystemExit(f"{sid} {tag}: classed {got['miss']} misses and {got['extra']} extras against "
                             f"the scorer's {sc['misses']} and {sc['extras']}")
        stored = eb.OUT / tag / f"classed_{sid}.jsonl"
        if stored.is_file():
            old = [json.loads(ln) for ln in stored.open(encoding="utf-8")]
            ctl[sid] = {"rows": len(C[sid]), "stored_rows": len(old),
                        "rows_equal": old == C[sid]}
        else:
            ctl[sid] = {"rows": len(C[sid]), "stored_rows": None, "rows_equal": None}
        lab = _lane_rows(tag, sid)
        joined = Counter()
        for f in C[sid]:
            if f["set"] != "extra":
                f["cls_ca"] = f["cls"]
                continue
            key = (int(f["k"]), int(f["frame_idx"]), round(f["icon_px"][0], 1), round(f["icon_px"][1], 1))
            hits = lab.get(key) or []
            if not hits:
                raise SystemExit(f"{sid} {tag}: extra k={f['k']} at {f['icon_px']} joins no lane row")
            u = hits.pop(0)          # two icons at one place in one frame: one row each, in order
            joined[u["outcome"]] += 1
            f["truth_under"] = u["label"]
            f["truth_entity"] = {k: u[k] for k in ("entity_id", "entity_class", "family", "agent", "ability",
                                                   "dist_m", "derivation")}
            f["cls_ca"] = budget_class(f["cls"], u["label"])
        ctl[sid]["extras_by_truth_outcome"] = dict(joined)
    orders_old = {"miss": list(eb.MISS_ORDER), "extra": list(eb.EXTRA_ORDER)}
    old_t = _budget_tables(C, sessions, "cls", orders_old, quiet=True)
    stored_b = eb.OUT / tag / ("budget.json" if len(sessions) > 1 else f"budget_{sessions[0]}.json")
    if stored_b.is_file():
        sb = json.loads(stored_b.read_text(encoding="utf-8"))
        ctl["tables_equal"] = sb.get("tables") == old_t
    else:
        ctl["tables_equal"] = None
    print(f"players-only control (enemy_error_budget {eb.VERSION}): {json.dumps(ctl)}", flush=True)
    if (ctl["tables_equal"] is None or rewrite) and ctl["tables_equal"] is not True:
        eb.budget(tag, sessions, record=False)
    elif ctl["tables_equal"] is False:
        print(f"   the stored players-only budget differs and is kept ({stored_b}); --rewrite replaces it",
              flush=True)
    classes = sorted({f["cls_ca"] for s in sessions for f in C[s] if f["set"] == "extra"})
    new_t = _budget_tables(C, sessions, "cls_ca", {"extra": classes})
    for scope, tb in new_t.items():
        tb["miss"] = old_t[scope]["miss"]
    cross = {s: dict(Counter(f"{f['cls']}|{f['cls_ca']}" for f in C[s] if f["set"] == "extra").most_common())
             for s in sessions}
    res = {"version": VERSION, "budget_version": eb.VERSION, "tag": tag, "sessions": sessions,
           "rule": "extras start from truth_under (the lane's class rows); misses keep the players-only classes",
           "refined": BUDGET_REFINED, "boot": f"{eb.N_BOOT} round resamples within each match, seed {eb.SEED}",
           "control": ctl, "tables": new_t, "players_only_tables": old_t, "old_x_new": cross}
    d = OUT / tag / "budget"
    d.mkdir(parents=True, exist_ok=True)
    for sid in sessions:
        with open(d / f"classed_{sid}.jsonl", "w", encoding="utf-8") as fh:
            for f in C[sid]:
                if f["set"] != "hit":
                    fh.write(json.dumps(f) + "\n")
    name = "budget.json" if sorted(sessions) == sorted(FROZEN_DEV) else f"budget_{'_'.join(sessions)}.json"
    (d / name).write_text(json.dumps(tr.label(res, sessions), indent=1), encoding="utf-8")
    print(f"\n-> {d / name}", flush=True)
    if record:
        from .extras import record as rec
        for scope, tb in new_t.items():
            vals, ci = {"extra_total": tb["extra"]["total"], "miss_total": tb["miss"]["total"]}, {}
            for r in tb["extra"]["rows"]:
                if r["n"]:
                    nm = "extra_" + _metric_name(r["cls"])
                    vals[nm] = r["n"]
                    vals[nm + "_share"] = r["share"]
                    ci[nm] = r["n_ci"]
                    ci[nm + "_share"] = r["share_ci"]
            ctl_rows = []
            if scope != "pooled" and ctl[scope]["rows_equal"] is not None:
                ctl_rows.append({"name": "players-only classed rows equal the stored enemy_error_budget rows",
                                 "observed": int(ctl[scope]["rows_equal"]), "expected": 1, "tol": 0})
            if scope == "pooled" and ctl["tables_equal"] is not None:
                ctl_rows.append({"name": "players-only tables equal the stored enemy_error_budget tables",
                                 "observed": int(ctl["tables_equal"]), "expected": 1, "tol": 0})
            rec("question_acceptance", part=f"budget/{tag}", session=scope if scope != "pooled" else _pool_name(sessions),
                values=vals, ci=ci, controls=ctl_rows,
                deps={"version": VERSION, "budget_version": eb.VERSION, "rule": "T1d", "near_cm": NEAR_CM,
                      "window_ms": WINDOW_MS, "ambig_cm": AMBIG_CM, "refined": BUDGET_REFINED},
                context={"task": TASK9, "boot": res["boot"], "sessions": sessions},
                note="the enemy lane's extras by the entity truth_under puts under each, refined by the "
                     "players-only class only on an enemy player; misses keep the players-only classes")
    return 0


def run_budget_tool(a) -> int:
    """The budget's diagnostics, unchanged from `enemy_error_budget`: the
    features (`budget-feats`), the eye crops and their score, the levers,
    the label sample and exploratory crops. They read the players-only
    classes; `budget` holds the class-aware ones."""
    from . import budget as eb
    cmd = a.cmd.removeprefix("budget-")
    if cmd == "feats":
        for s in a.sessions:
            eb.feats(s, a.tag)
        return 0
    if cmd == "eye":
        return eb.eye_crops(a.tag, a.n, a.only.split(",") if a.only else None, a.out)
    if cmd == "sample":
        eb.label_sample(a.tag)
        return 0
    if cmd == "levers":
        eb.levers(a.tag, a.record)
        return 0
    if cmd == "eye-score":
        eb.eye_score(a.tag, a.record)
        return 0
    if cmd == "peek":
        rng = np.random.default_rng(eb.SEED)
        rows = []
        for sid in a.sessions.split(","):
            rows += [f for f in eb._load_feats(a.tag, sid) if f["set"] == a.set and eval(a.expr, {"f": f})]
        print(f"{len(rows)} rows match", flush=True)
        pick = [rows[i] for i in sorted(rng.permutation(len(rows))[:a.n])]
        eb.draw_crops(a.tag, pick, a.name)
        return 0
    return 1


# ----------------------------------------------------------------- slot regions (QUESTION_ACCEPTANCE B1)

#: The slot-region scorer's own stamp (task enemy-slots-20261009).
SLOTS_VERSION = "slot-regions-0.1.0"
TASK_SLOTS = "enemy-slots-20261009"


def _truth_slots(slots: list[dict], agents: list) -> tuple[np.ndarray, list]:
    """Each truth player's slot by the arbiter's names, then one-to-one
    elimination of what is left (evaluation pairing only); -1 unpaired."""
    from reticle.agent_names import agent_key
    by = {agent_key(s["agent"]): k for k, s in enumerate(slots) if s.get("agent")}
    out = np.array([by.get(agent_key(a), -1) if a else -1 for a in agents], np.int64)
    left_t = np.flatnonzero(out < 0)
    left_s = sorted(set(range(len(slots))) - set(out[out >= 0].tolist()))
    notes = []
    if left_t.size == 1 and len(left_s) == 1:
        out[left_t[0]] = left_s[0]
        notes.append({"truth": agents[left_t[0]], "slot": left_s[0], "how": "elimination",
                      "slot_agent": slots[left_s[0]].get("agent")})
    elif left_t.size:
        notes.append({"unpaired_truth": [agents[i] for i in left_t], "free_slots": left_s})
    return out, notes


def _slot_frames_on_grid(M, t_cap, drawn) -> np.ndarray:
    """`_frames_on_grid` without the crop cache's spans: the slot model
    holds a belief on every stored frame, and the `ally_icon` frames are the
    frames read. Live play only (`harness.sets.live_samples`)."""
    from . import sets as elc
    t_rep = np.asarray(M.to_rep(np.asarray(t_cap, float), rt.REMOTE_LAG_MS), float)
    live, _ = elc.live_samples(M)
    step = float(np.median(np.diff(M.G)))
    i = np.clip(np.searchsorted(M.G, t_rep), 0, M.G.size - 1)
    k = frame_samples(M.G, t_rep, np.asarray(drawn, bool) & live[i], FRAME_HALF_STEP * step)
    k[(k >= 0) & ~live[np.clip(k, 0, None)]] = -1
    return k


def slot_regions(sid: str) -> dict:
    """Every living player on every scored frame against its slot's region
    (`slot_state.build_slots`, causal binding), both sides, scored by
    `reticle.acceptance.slot_region_scores`.

    The frames are the `ally_icon` frames the widget drew, on T1d's grid in
    live play (`_slot_frames_on_grid`). A truth player pairs with the slot the
    arbiter's lineup verdict names (`_truth_slots`). `drawn` is T1d's rule
    for an enemy; an ally counts drawn while he lives."""
    from reticle import slot_state as ss
    t0 = time.perf_counter()
    ctx = _truth_ctx(sid)
    M, J = ctx["M"], ctx["J"]
    G = ss.build_slots(sid, binding="causal", store_root=STORE)
    if "refused" in G:
        raise SystemExit(f"{sid}: build_slots refused: {G['refused']}")
    S, B = G["S"], G["B"]
    k = _slot_frames_on_grid(M, S.fr_t, S.fr_drawn)
    f = np.flatnonzero(k >= 0)
    kk = k[f]
    rounds = sorted(set(M.G_round[kk].tolist()))
    rr_f = np.searchsorted(np.asarray(rounds), M.G_round[kk])
    upm = ss.units_per_m()
    alive = np.asarray(J["alive"], bool)
    PX = np.where(alive, M.X, np.nan)[:, kk] / upm            # (players, scored frames), metres
    PY = np.where(alive, M.Y, np.nan)[:, kk] / upm
    side_of = np.array([r.side for r in G["rows"]])
    kinds = dict(ss.KINDS)
    out = {"session": sid, "version": SLOTS_VERSION, "acceptance_version": acc.ACCEPTANCE_VERSION,
           "slot_state_version": ss.SLOT_STATE_VERSION, "stamp": G["stamp"],
           "frames_scored": int(f.size), "rounds": len(rounds), "sides": {}, "_arrays": {}}
    for side, subj, slots in (("enemy", M.ei, G["L"]["enemy_slots"]), ("ally", M.ci, G["L"]["slots"])):
        rows = np.flatnonzero(side_of == side)
        other = M.ci if side == "enemy" else M.ei
        tslot, notes = _truth_slots(slots, [M.agent.get(M.sid[j]) for j in subj])
        q = defaultdict(list)
        for i, j in enumerate(subj):
            if tslot[i] < 0:
                continue
            live = np.flatnonzero(alive[j, kk])
            if not live.size:
                continue
            fr = f[live]
            row = np.full(live.size, rows[tslot[i]])
            x, y = PX[j, live], PY[j, live]
            C = ss.contains(B, row, fr, x, y)
            kind = C["kind"].astype(np.int64)
            fit = kind == ss.FIT
            mates = np.delete(np.arange(len(subj)), i)
            fo = np.full(live.size, -1, np.int64)
            if fit.any():
                fo[fit] = acc.slot_fit_outcomes(
                    B["x"][row[fit], fr[fit]], B["y"][row[fit], fr[fit]], x[fit], y[fit],
                    PX[np.asarray(subj)[mates]][:, live[fit]].T, PY[np.asarray(subj)[mates]][:, live[fit]].T,
                    PX[np.asarray(other)][:, live[fit]].T, PY[np.asarray(other)][:, live[fit]].T)
            q["round"].append(rr_f[live])
            q["inside"].append(C["region"] & G["open"][row, fr])
            q["kind"].append(kind)
            q["area"].append(ss.region_area(B, row, fr))
            q["R"].append(np.asarray(C["R"], float))
            q["drawn"].append(np.asarray(J["drawn"], bool)[j, kk[live]] if side == "enemy"
                              else np.ones(live.size, bool))
            q["fit_out"].append(fo)
        Q = {key: np.concatenate(v) for key, v in q.items()} if q else \
            {key: np.zeros(0) for key in ("round", "inside", "kind", "area", "R", "drawn", "fit_out")}
        Q["n_rounds"] = len(rounds)
        kind_sf = B["kind"][rows][:, f]
        op = kind_sf != ss.CLOSED
        SF = {"round": np.broadcast_to(rr_f, kind_sf.shape)[op], "kind": kind_sf[op],
              "slot": np.broadcast_to(np.arange(rows.size)[:, None], kind_sf.shape)[op]}
        sc = acc.slot_region_scores(Q, SF, kinds, unbounded=("unanchored",))
        counts = (G["enemy"]["bind"]["counts"] if side == "enemy" else G["bind"]["counts"])
        out["sides"][side] = {**sc["doc"], "truth_pairing": notes,
                              "slot_agents": [s.get("agent") for s in slots],
                              "binding_counts": {kk_: v for kk_, v in counts.items()
                                                 if isinstance(v, (int, str))}}
        out["_arrays"][side] = sc["arrays"]
    out["secs"] = round(time.perf_counter() - t0, 1)
    return out


def _print_slots(scope: str, d: dict) -> None:
    def fmt(v):
        return "-" if not v or v.get("value") is None else f"{v['value']:.4f} {v.get('ci')}"
    for side in ("enemy", "ally"):
        s = d.get(side)
        if not s:
            continue
        print(f"   {scope} {side}: calibration {fmt(s.get('calibration'))}; anchored "
              f"{fmt(s.get('calibration_anchored'))}; T1d-drawn {fmt(s.get('calibration_drawn'))}; "
              f"unanchored {fmt(s.get('unanchored'))}; lane coverage {fmt(s.get('lane_coverage'))} "
              f"(drawn {fmt(s.get('lane_coverage_drawn'))}); fit right {fmt(s.get('fit_right_entity'))}",
              flush=True)


def run_slots(sessions: list[str], record: bool) -> int:
    """Score both sides' slot regions on each session, pool the development
    and the 2026-10-07 sessions and all of them, print, write the document
    under OUT/steps/slots and, with `record`, the metrics."""
    for sid in sessions:
        _refuse(sid)
    res = []
    sub = OUT / "steps" / "slots"
    sub.mkdir(parents=True, exist_ok=True)
    for sid in sessions:
        r = slot_regions(sid)
        (sub / f"{sid}.json").write_text(json.dumps(tr.label({k: v for k, v in r.items() if k != "_arrays"}, [sid]),
                                                    indent=1, default=str), encoding="utf-8")
        e = r["sides"]["enemy"]
        print(f"{sid} slots: {r['frames_scored']} frames, {r['rounds']} rounds, {r['secs']} s; enemy binding "
              f"{e['binding_counts']}; area (bounded) {e['area_m2_bounded']}; by kind "
              + "; ".join(f"{k}: {v['value']} n={v['den']} r={v['radius_m'].get('median')}"
                          for k, v in e["by_kind"].items()), flush=True)
        flat = {side: {**{n: v for n, v in r["sides"][side].items()
                          if isinstance(v, dict) and "value" in v},
                       **{f"fit_{o}": r["sides"][side]["fit_outcomes"][o] for o in acc.SLOT_FIT_OUTCOMES}}
                for side in r["sides"]}
        _print_slots(sid, flat)
        res.append(r)
    pools = {}
    # `all6` pools the frozen matches with `DEV` only when both are named; its rows carry `frozen`.
    scopes = [("new3", [r for r in res if r["session"] in DEV]),
              ("dev3", [r for r in res if r["session"] in FROZEN_DEV]), ("all6", res)]
    for name, rs in scopes:
        if len(rs) < 2 or (name == "all6" and len(rs) != len(DEV) + len(FROZEN_DEV)):
            continue
        pools[name] = {side: acc.pool_slot_regions([{"arrays": r["_arrays"][side]} for r in rs])
                       for side in ("enemy", "ally")}
        _print_slots(name, pools[name])
    doc = {"step": "slots", "version": SLOTS_VERSION, "acceptance_version": acc.ACCEPTANCE_VERSION,
           "boot": f"{acc.N_BOOT} round resamples, seed {acc.SEED}",
           "sessions": {r["session"]: {k: v for k, v in r.items() if k != "_arrays"} for r in res},
           "pooled": pools}
    (OUT / "step_slots.json").write_text(json.dumps(tr.label(doc, sessions), indent=1, default=str), encoding="utf-8")
    if record:
        _record_slots(res, pools, sessions)
    return 0


def _record_slots(res: list[dict], pools: dict, sessions: list[str]) -> None:
    """Each side's shares per session and pooled, with their intervals."""
    from .extras import record as rec
    scopes = [(r["session"], {side: {**{n: v for n, v in r["sides"][side].items()
                                        if isinstance(v, dict) and "value" in v},
                                     **{f"fit_{o}": r["sides"][side]["fit_outcomes"][o]
                                        for o in acc.SLOT_FIT_OUTCOMES},
                                     **{f"kind_{k}": v for k, v in r["sides"][side]["by_kind"].items()}}
                              for side in r["sides"]}, r) for r in res]
    scopes += [(name, p, None) for name, p in pools.items()]
    for scope, by_side, r in scopes:
        for side, d in by_side.items():
            vals = {n: v["value"] for n, v in d.items() if v.get("value") is not None}
            ci = {n: v["ci"] for n, v in d.items() if v.get("ci") is not None}
            vals.update({f"{n}_den": v["den"] for n, v in d.items() if v.get("den") is not None})
            if r is not None:
                s = r["sides"][side]
                for k, v in s["by_kind"].items():
                    if v["radius_m"].get("median") is not None:
                        vals[f"kind_{k}_radius_m_median"] = v["radius_m"]["median"]
                    if v["area_m2"].get("median") is not None:
                        vals[f"kind_{k}_area_m2_median"] = v["area_m2"]["median"]
                if s["area_m2_bounded"].get("median") is not None:
                    vals["area_m2_bounded_median"] = s["area_m2_bounded"]["median"]
            rec("question_acceptance", part=f"slots/{side}", session=scope, values=vals, ci=ci,
                deps={"version": SLOTS_VERSION, "acceptance_version": acc.ACCEPTANCE_VERSION,
                      "rule": "T1d", "near_m": acc.SLOT_NEAR_M,
                      "stamp": r["stamp"] if r is not None else None},
                context={"task": TASK_SLOTS, "boot": f"{acc.N_BOOT} round resamples, seed {acc.SEED}",
                         "sessions": sessions},
                note=f"{side} slot regions (slot_state causal) against replay truth on the drawn "
                     "ally_icon frames in live play; calibration = truth inside the region; "
                     "unanchored = share of open slot-frames whose region is the map; lane coverage = "
                     "share of living-player rows whose slot holds a fit")


# ----------------------------------------------------------------- the ability lane (docs/ABILITY_ENTITIES.md steps 2-3)

#: The default sessions: the development set. The frozen development matches
#: run only when named, and then carry `frozen`.
ABILITY_SETS = tuple(DEV)
#: `--side` choices: one slot side, or every side in one run (step 3).
ABILITY_SIDE_CHOICES = acc.ABILITY_SIDES + ("all",)


def _ability_truth(sid: str) -> dict:
    """The replay's truth for every slot's ability children, in capture ms
    (`replay_truth.session_context`'s clock). Per slot side (`self`, `team`,
    `enemy`, from the replay's teams and the decided player): every player's
    cast records (`replay_actors.Export.casts`) named by the slot map and the
    class census, each player's ult transitions as X casts, each player's
    world actors per ability and class, and each player's deaths; and the
    census's unmapped classes. `casts` and `others` keep step 2's shape: the
    player's own casts, and every other player's."""
    ctx = rt.session_context(sid)
    out = dict(ctx["out"])
    if "refused" in out:
        return {"refused": out["refused"]}
    rp, a, me, agent = ctx["rp"], ctx["a"], ctx["me"], ctx["agent"]
    allies = set(ctx.get("allies") or [])
    side_of = lambda s: "self" if s == me else "team" if s in allies else "enemy"
    ex = ra.Export(rp.match, rp=rp)
    cen = ra.actor_census(rp.match, ex)
    smap = ra.slot_map(cen)
    folder_name = {(r["code"], r["folder"]): r["ability"] for r in cen["classes"] if r.get("folder")}
    code_of, actors = {}, []
    for r in cen["classes"]:
        if not r.get("code") or not r["mapped"]:
            continue
        for i in ex.instances(class_short=r["class"]):
            s, _ = ex.owner_subject(i["guid"])
            if s is None:
                continue
            code_of.setdefault(s, r["code"])
            actors.append({"ability": r["ability"], "class": r["class"], "subject": s,
                           "agent": agent.get(s), "side": side_of(s),
                           "open_ms": float(i["open_ms"]) + a,
                           "close_ms": None if i["close_ms"] is None else float(i["close_ms"]) + a})
    casts = []
    for c in ex.casts()["casts"]:
        if c["t_ms"] is None:
            continue
        ag = agent.get(c["subject"])
        f = smap.get(f"{ag}|{c['slot']}")
        name = folder_name.get((code_of.get(c["subject"]), f)) if f else None
        casts.append({"t_ms": float(c["t_ms"]) + a, "ability": name, "slot": c["slot"], "agent": ag,
                      "subject": c["subject"], "side": side_of(c["subject"])})
    x_name = {}
    for s in rp.subjects:
        code = code_of.get(s)
        x = next((r["ability"] for r in cen["classes"] if r.get("code") == code
                  and r.get("folder") == "Ability_X"), None)
        if x is None and code:
            x = ra.ability_display(code, "Ability_X")["display"]
        x_name[s] = x
    # Step 2's others: every other player's raw cast records, kept as step 2 read them.
    others = [{k: c[k] for k in ("t_ms", "ability", "slot", "agent")} for c in casts if c["subject"] != me]
    casts = [c for c in casts if c["ability"] is None or c["ability"] != x_name.get(c["subject"])]
    casts += [{"t_ms": float(u["on_ms"]) + a, "ability": x_name.get(u["subject"]), "slot": "X",
               "agent": agent.get(u["subject"]), "subject": u["subject"], "side": side_of(u["subject"])}
              for u in ex.ult_intervals() if u["subject"] in agent]
    deaths = defaultdict(list)
    for e in rp.group("characterDeath"):
        if e.get("victim") is not None:
            deaths[e["victim"]].append(float(e["t"]) + a)
    mine = [c for c in casts if c["subject"] == me]
    return {"agent": agent.get(me), "me": me,
            "casts": [{k: c[k] for k in ("t_ms", "ability", "slot", "agent")} for c in mine],
            "others": others, "all_casts": casts,
            "actors": [x for x in actors if x["subject"] == me], "all_actors": actors,
            "deaths_ms": deaths.get(me, []), "deaths_by_subject": dict(deaths), "clock_ms": a,
            "unmapped_classes": sorted(r["class"] for r in cen["classes"] if not r["mapped"])}


def _ability_child_rows(sid: str) -> list[dict]:
    from reticle.store import Store
    st = Store(STORE)
    path = st.events_path("ability_child", sid)
    return [r for r in (st.read_events("ability_child", sid) if path.is_file() else [])
            if r.get("kind") == "child"]


def _ability_lane_rows(sid: str) -> tuple[list[dict], set, dict]:
    """The `ability` lane's consumer entities, plus each instance the lane
    withheld (stale inputs or an unresolved name) as the owner stored it in
    `ability_child`, shaped as an entity and marked held; and why the lane
    withheld them (`entity_events.rebuild_reason`, or its held inputs)."""
    from reticle import entity_events as ee
    from reticle.store import Store
    st = Store(STORE)
    ev = ee.EntityEvents(st, sid, lanes=("ability",), check=False)
    ents = [] if "ability" in ev.missing else list(ev.entities(lane="ability"))
    have = {e["entity_id"] for e in ents}
    children = [r for r in _ability_child_rows(sid)
                if r["child_id"] not in have and r.get("node", "instance") == "instance"]
    held = set()
    for c in children:
        ents.append({"entity_id": c["child_id"], "family": "ability_object",
                     "kind": c.get("subject") or "unknown", "round": c["round"],
                     "side": c.get("side", "ally"), "player": c.get("owner_slot", c.get("parent")),
                     "lifetime": {"began": dict(c["open"]), "ended": dict(c["end"])}})
        held.add(c["child_id"])
    why = {}
    if held:
        stale = ee.stale_inputs(st, sid)
        why = {"missing": ev.missing["ability"]} if "ability" in ev.missing else \
            {s: stale[s] for s in ee.LANE["ability"]["inputs"] if s in stale} or \
            {"withheld": "an unresolved name or an unbound owner (the lane's ledger)"}
    return ents, held, why


def _object_finds(sid: str) -> tuple[list[dict], set]:
    """The owner's spawned-object nodes (`ability_child` rows with node
    `object`, witnessed and possible), as `score_ability_objects` takes them,
    and the classes of the spawn tree for the session's agents."""
    from reticle import slot_state as ss
    rows = _ability_child_rows(sid)
    nodes = [{"key": r["child_id"], "cls": acc.object_class_key(r["object"]),
              "side": r.get("slot_side"), "agent": r.get("agent"), "exists": r.get("exists"),
              "open_lo": float(r["open"]["lo_ms"]), "open_hi": float(r["open"]["hi_ms"]),
              "end_hi": float(r["end"]["hi_ms"]), "end_basis": r["end"]["basis"]}
             for r in rows if r.get("node") == "object"]
    L = ss.lineup_slots(sid, STORE)
    agents = {ss.agent_key(s["agent"]) for s in (L.get("slots") or []) + (L.get("enemy_slots") or [])
              if s.get("agent")}
    tree = ss.ability_objects(STORE)["tree"]
    classes = {acc.object_class_key(o["part"]) for (ag, _slot), objs in tree.items() if ag in agents
               for o in objs}
    return nodes, classes


def run_ability_lane(sessions: list[str], tag: str, side: str, record: bool,
                     post_hoc: bool = False) -> int:
    """`ability-lane`: the `ability` lane's children scored per slot side and
    class against the replay (`reticle.acceptance.score_ability_lane`), and
    the owner's spawned-object nodes per side and class
    (`score_ability_objects`); one document per session and one pooled,
    written under `OUT/ability_lane/TAG/`. Rows the lane withheld count, and
    the document names why. `side` is one of `ABILITY_SIDE_CHOICES`; `all`
    scores every side in one run. A side's finds pair only with that side's
    truth casts; a find on another side's cast is `other_entity`. Finds no
    witness bound to a slot score apart, as `unbound`, against every
    non-player cast. Witnessed object nodes are the primary object measure;
    possible nodes score in their own block (`objects_possible`). `post_hoc`
    marks every recorded row a revision after the pre-registered run."""
    from reticle import entity_events as ee
    from reticle import slot_state as ss
    from reticle.store import Store
    sides = acc.ABILITY_SIDES if side == "all" else (side,)
    st = Store(STORE)
    out_dir = OUT / "ability_lane" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    docs, arrays, obj_arrays, poss_arrays = {}, defaultdict(list), [], []
    for sid in sessions:
        ents, held, stale = _ability_lane_rows(sid)
        if not ents:
            print(f"{sid}: no ability lane rows ({stale})", flush=True)
            continue
        truth = _ability_truth(sid)
        if "refused" in truth:
            print(f"{sid}: replay truth refused: {truth['refused']}", flush=True)
            continue
        L = ss.lineup_slots(sid, STORE)
        self_key = L["slots"][int(L["player_slot"])]["key"] if L.get("player_slot") is not None else None
        rounds = ee.round_rows(st, sid)
        starts = [float(r["t_start_ms"]) for r in rounds]
        bars = [float(r["t_close_ms"] if r.get("t_close_ms") is not None else r["t_end_ms"])
                for r in rounds]
        objects = frozenset(r["child_id"] for r in _ability_child_rows(sid) if r.get("node") == "object")
        finds = acc.ability_lane_finds(ents, frozenset(held), self_key, objects)
        doc = {"session": sid, "agent": truth["agent"], "version": VERSION,
               "lane": (ee.EntityEvents(st, sid, lanes=("ability",), check=False)
                        .stamp("ability") or {}).get("entity_ability_version"),
               "held_stale": stale, "unmapped_classes": truth["unmapped_classes"],
               "unmapped_note": "coverage gaps by class: the census maps no ability to them",
               "sides": {}}
        for sd in sides + ((acc.ABILITY_UNBOUND,) if side == "all" else ()):
            if sd == "self":
                tc, oth = truth["casts"], truth["others"]
                inst = acc.ability_truth_instances(tc, truth["actors"], truth["deaths_ms"], bars)
            else:
                want = ("team", "enemy") if sd == acc.ABILITY_UNBOUND else (sd,)
                inst = []
                for subj in sorted({c["subject"] for c in truth["all_casts"] if c["side"] in want}):
                    tc_s = [c for c in truth["all_casts"] if c["subject"] == subj]
                    inst += acc.ability_truth_instances(
                        tc_s, [x for x in truth["all_actors"] if x["subject"] == subj],
                        truth["deaths_by_subject"].get(subj, []), bars)
                oth = [{k: c[k] for k in ("t_ms", "ability", "slot", "agent")}
                       for c in truth["all_casts"] if c["side"] not in want]
            fs = [f for f in finds if f["side"] == sd]
            d, arr = acc.score_ability_lane(fs, inst, oth, starts)
            doc["sides"][sd] = d
            arrays[sd].append(arr)
            a = d["all"]
            print(f"{sid} [{sd}]: truth {a['truth']}, finds {a['finds']} ({a['held_stale_finds']} held), "
                  f"recall {a['recall']} {a['recall_ci']}, false opens {a['false_opens']} "
                  f"{a['false_open_ci']}, outcomes {a['outcomes']}, open err {a['open_error']}, "
                  f"end err {a['end_error']}, end cause {a['end_cause_agreement']} "
                  f"(n {a['end_cause_n']})", flush=True)
        if side == "all":
            nodes, classes = _object_finds(sid)
            acts = []
            for x in truth["all_actors"]:
                cls = acc.object_class_key(x["class"])
                if cls not in classes:
                    continue
                acts.append({"cls": cls, "side": x["side"], "agent": x["agent"], "open_ms": x["open_ms"],
                             "close_ms": x["close_ms"],
                             "end_cause": acc.truth_end_cause(x["close_ms"],
                                                              truth["deaths_by_subject"].get(x["subject"], []),
                                                              bars, x["open_ms"])})
            od, oarr = acc.score_ability_objects(nodes, acts, starts)
            doc["objects"] = od
            obj_arrays.append(oarr["witnessed"])
            poss_arrays.append(oarr["possible"])
            w, pb = od["all"], od["possible"]["all"]
            print(f"{sid} [objects]: truth {w['truth']}, witnessed nodes {w['finds']}, recall "
                  f"{w['recall']} {w['recall_ci']}, false opens {w['false_open_share']}, cause "
                  f"{w['end_cause_agreement']}; possible nodes {pb['finds']}, recall {pb['recall']}",
                  flush=True)
        docs[sid] = doc
        (out_dir / f"{sid}.json").write_text(json.dumps(tr.label(doc, [sid]), indent=1, default=str), encoding="utf-8")
    if not docs:
        return 1
    pooled = {sd: acc.pool_ability_lane(arr) for sd, arr in arrays.items() if arr}
    pooled_obj = acc.pool_ability_lane(obj_arrays) if obj_arrays else {}
    pooled_poss = acc.pool_ability_lane(poss_arrays) if poss_arrays else {}
    (out_dir / "pooled.json").write_text(json.dumps(tr.label({"sessions": sorted(docs), "sides": pooled,
                                                     "objects": pooled_obj,
                                                     "objects_possible": pooled_poss,
                                                     "post_hoc": post_hoc}, sorted(docs)),
                                                    indent=1, default=str), encoding="utf-8")
    print(f"\npooled over {len(docs)} sessions")
    head = (f"{'side':8s} {'class':34s} {'truth':>5s} {'finds':>5s} {'pair':>4s} {'recall':>7s} "
            f"{'recall CI':>16s} {'false':>6s} {'false CI':>16s} {'open med':>8s} {'end med':>8s} {'cause':>6s}")
    print(head)
    for sd, blocks in list(pooled.items()) + ([("objects", pooled_obj)] if pooled_obj else []) \
            + ([("possible", pooled_poss)] if pooled_poss else []):
        for cls, b in sorted(blocks.items(), key=lambda kv: (kv[0] == "_all", kv[0])):
            print(f"{sd:8s} {cls[:34]:34s} {b['truth']:5d} {b['finds']:5d} {b['paired']:4d} "
                  f"{str(b['recall']):>7s} {str(b['recall_ci']):>16s} {str(b['false_open_share']):>6s} "
                  f"{str(b['false_open_ci']):>16s} {str(b['open_error'].get('median_ms')):>8s} "
                  f"{str(b['end_error'].get('median_ms')):>8s} {str(b['end_cause_agreement']):>6s}")
    if record:
        from .extras import record as rec
        scopes = [(sid, {sd: {**d["classes"], "_all": d["all"]} for sd, d in doc["sides"].items()}
                   | ({"objects": {**doc["objects"]["classes"], "_all": doc["objects"]["all"]},
                        "objects_possible": {**doc["objects"]["possible"]["classes"],
                                             "_all": doc["objects"]["possible"]["all"]}}
                      if "objects" in doc else {}))
                  for sid, doc in docs.items()]
        scopes.append((_pool_name(sorted(docs)), {**pooled, **({"objects": pooled_obj,
                                                                 "objects_possible": pooled_poss}
                                                                if pooled_obj else {})}))
        for scope, by_side in scopes:
            vals, ci = {}, {}
            for sd, blocks in by_side.items():
                for cls, b in blocks.items():
                    nm = _metric_name(cls) if side != "all" and sd == "self" else \
                        f"{sd}_{_metric_name(cls)}"
                    for k in ("truth", "finds", "paired", "recall", "false_opens", "false_open_share",
                              "end_cause_agreement"):
                        vals[f"{nm}_{k}"] = b.get(k)
                    vals[f"{nm}_open_err_median_ms"] = b["open_error"].get("median_ms")
                    vals[f"{nm}_end_err_median_ms"] = b["end_error"].get("median_ms")
                    for k, v in ((f"{nm}_recall", b.get("recall_ci")),
                                 (f"{nm}_false_open_share", b.get("false_open_ci"))):
                        if v is not None:
                            ci[k] = v
            rec("question_acceptance", part=f"ability_lane/{tag}", session=scope, values=vals, ci=ci,
                deps={"version": VERSION, "acceptance": acc.ACCEPTANCE_VERSION,
                      "gate_ms": acc.ABILITY_OPEN_GATE_MS, "end_tol_ms": acc.ABILITY_END_TOL_MS,
                      "ability_child": ss.ABILITY_CHILD_VERSION},
                context={"task": "ability-tree-step3-20261009", "side": side,
                         "sessions": sorted(docs), "post_hoc": post_hoc},
                note="docs/ABILITY_ENTITIES.md step 3: the ability lane's children of every slot "
                     "side against the replay's casts and actors, per side and class; spawned-"
                     "object nodes per class against the replay's actors of that class")
    return 0


def main(argv=None) -> int:
    """The harness's subcommands (`commands.add_parsers`) for the old
    `prototypes/question_acceptance.py` command line."""
    from . import commands
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    commands.add_parsers(sub)
    a = ap.parse_args(argv)
    return commands.dispatch(a, a.cmd)
