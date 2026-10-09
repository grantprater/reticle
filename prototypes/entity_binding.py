r"""Causal per-frame binding of ally fits to the five ally slots.

    .\.venv\Scripts\python.exe prototypes\entity_state.py score SESSION ... --pool NAME --binding causal

Stage 2 of [docs/ENTITY_STATE.md](../docs/ENTITY_STATE.md) (section 2,
"Identity enters through the arbiter"), as a prototype beside
`prototypes/entity_state.py`, which calls it when `--binding causal` is
given; `--binding post_round` keeps the stage 1 path so both are scored.
Promoted (2026-10-09, QUESTION_ACCEPTANCE B1): the binding lives in
`reticle/slot_state.py` unchanged (`ENTITY_BINDING_VERSION` 0.1.1); this file
re-exports it under its old names for the prototypes and tests that call it;
`load_fits` and `spectated_slots` now take the module's `StoredRows`. It reads
STORED rows only: the `ally_icon` icon and frame rows, the `ping` and
`spike` events, the `tray_kit` rows, the lineup and the baked geometry's
labels. It decodes nothing and reads no crop.

The assignment
--------------
At each frame `t`, every ally fit of that frame (each `ally_icon` icon row,
refused or not, and the self fit when it is not bound directly) goes to one
of the open teammate slots or to its own non-player column, by one
`track.assign` (`scipy.optimize.linear_sum_assignment`, the
`track-continuation` owner's solver) over

    cost[f, s] = motion[f, s] - W_ID * clip(llr[f, agent(s)], LLR_CLIP)
    cost[f, np_f] = log(A_map) + K_NP - sum(bonus[reason] for f's reasons)

* `motion[f, s]`: the slot's belief at `t` from what was bound before `t`:
  a Gaussian per square metre round the slot's last bound fit,
  `0.5 (d / sigma)^2 + log(2 pi sigma^2)`, `sigma = R / 2` and
  `R = v_max (t - t_bound) + r_fit` (the reach radius, so the region's edge
  sits at two sigma); `log(A_map)` (uniform over the map) for a slot with no
  fit since its round opened.
* `llr[f, a]`: the fit's own portrait log ratio for agent `a` over the
  teammates the arbiter names (`identity.rendered_art_scores`, the
  `agent-identity` owner), read only for a fit the reader did not refuse.
  Only the fit's own frame enters: evidence available at `t`, never pooled
  forward. A slot's agent is the arbiter's lineup verdict; the prior is
  weighed once (results declare `rests_on`).
* Non-player reasons, each from a stored owner: `off_map` (the fit's centre
  lies more than one icon radius from every non-void cell of the baked
  `(map, profile)` labels, `minimap.VOID`), `ability_glyph` (the reader
  refused the ring as `interior_is_map`, which `round_entity` calls a
  barrier), `not_a_teammate` (`identity.teammate_fit_refusal`: the portrait
  fits none of the teammates' rendered art), `ping` (an active `ping`
  entity within two icon radii), `spike` (a dropped spike glyph the `spike`
  reader accepted within two icon radii, in the last second). A fit the
  assignment leaves to its non-player column with none of these is
  `duplicate` when it lies within two icon radii of a bound fit of the
  frame, else `unexplained`.

No fit opens a slot; a slot no fit binds keeps its belief and grows its
reach. One fit binds one slot at most (the solver's one-to-one), checked.

Self fits
---------
While the player's slot is open the self fit binds to it directly (the self
channel). After the player's death the self icon draws the spectated
teammate [domain:minimap/self-icon-shows-spectated]: the self fit binds to
the slot of the agent whose kit the tray shows then
(`adjudication.tray_kit.stored_kit_witness`, `kit_agents_at` with no
lookahead), `rests_on` that witness, whose span agents are pooled over each
whole span (a post-round `tray_kit` verdict, disclosed). A self fit off the
map binds no spectated slot; it enters the assignment with its `off_map`
reason. Where no current `tray_kit` row names a teammate's kit, the
self fit enters the assignment as an ordinary fit with no portrait term
(`via_spectated`), and the gap is counted.

Witnessed bindings
------------------
A binding anchors a reach region only when a witness names it: the self
channel, the spectating witness, or a portrait margin of at least the
rendered-art table's `margin_min` over every other open teammate slot's
agent. Every other binding is `fit_unnamed` (`entity_state.beliefs`).
Exclusivity (the fit lies in this slot's reach region and in no other open
slot's, every other open slot being anchored, and its portrait names no
other slot) is recorded as code 4 and anchors nothing: on the dev sessions
it carried wrong anchors forward.

Chains
------
Each slot carries its chain's portrait evidence: the decayed sum of the log
ratios of the fits bound to it (`DECAY` a frame). When the evidence of the
open teammate chains names a different chain-to-slot assignment, by at
least `SWAP_MIN` nats over the current one, the chains move: each slot
takes the motion state and evidence of the chain its evidence names. Frames
already bound stay as published; the move changes only what follows.

Outcome (2026-10-04, entity-binding-0.1.1)
------------------------------------------
Developed on the dev sessions only (`3694746e4e54`, `a06f04a0059f`,
`bdfdcf009dba`, `9acf02f98283`): chains, the relocation cap and the
chain-confirmed portrait witness came from the dev misses; the parameters
were fixed in an amendment row before the held-out score. Dev (0.1.0):
[metric:entity_state/riot_pool@dev4_causal#calibration=0.9657] against the
post-round [metric:entity_state/riot_pool@dev4_post_round#calibration=0.9521].
The held-out six, a second look, scored once, then rescored once after
the 0.1.1 correction of a causal leak a review found (the spectating witness
read `tray_kit` spans 100 ms ahead; off-map self fits could bind the
spectated slot), a correction and not a third look:
[metric:entity_state/riot_pool@heldout6es_causal#calibration=0.9689]
(post-round [metric:entity_state/riot_pool@heldout6es_post_round#calibration=0.9355]),
short of the 0.97 gate; the 8 kill instants the death owner's next-round
stamp closes are among the misses. By kind: fit
[metric:entity_state/riot_pool@heldout6es_causal#fit_calibration=0.9801],
fit_unnamed [metric:entity_state/riot_pool@heldout6es_causal#fit_unnamed_calibration=0.9711],
reach [metric:entity_state/riot_pool@heldout6es_causal#reach_calibration=0.9524]
(median radius [metric:entity_state/riot_pool@heldout6es_causal#reach_radius_m_median=9.81] m),
crowd [metric:entity_state/riot_pool@heldout6es_causal#crowd_calibration=0.973].
By session it runs from
[metric:entity_state/riot_pool@heldout6es_causal#59c70f1ef720.calibration=0.9471]
to [metric:entity_state/riot_pool@heldout6es_causal#043bafca271a.calibration=0.9889].
A bound fit lies within 8 m of the truth on
[metric:entity_state/riot_pool@heldout6es_causal#fit_bound_share=0.7615] of
living-teammate instants, against the ring fits'
[metric:entity_state/riot_pool@heldout6es_causal#ring_located_share=0.7121];
no frame binds one fit to two slots. The replay's every drawn frame (0.1.0, before the correction):
[metric:entity_state/replay@9acf02f98283_causal~2026-10-04T23:23:06#calibration=0.9722]
(post-round [metric:entity_state/replay@9acf02f98283_post_round#calibration=0.944]).

Non-player fits on the held-out six, by reason: `ability_glyph`
[metric:entity_state/riot_pool@heldout6es_causal#non_player_ability_glyph=18743],
`unexplained` [metric:entity_state/riot_pool@heldout6es_causal#non_player_unexplained=7290],
`off_map` [metric:entity_state/riot_pool@heldout6es_causal#non_player_off_map=1492],
`ping` [metric:entity_state/riot_pool@heldout6es_causal#non_player_ping=1376],
`duplicate` [metric:entity_state/riot_pool@heldout6es_causal#non_player_duplicate=596],
`not_a_teammate` [metric:entity_state/riot_pool@heldout6es_causal#non_player_not_a_teammate=71],
`spike` [metric:entity_state/riot_pool@heldout6es_causal#non_player_spike=51].
The binding costs a median
[metric:entity_state/riot_pool@heldout6es_causal#cost_us_per_frame_median=152.2] us
a frame and at most
[metric:entity_state/riot_pool@heldout6es_causal#cost_us_per_frame_max=174.88],
a Python loop over frames with one solver call each.

Six held-out misses viewed in the minimap crop cache: a ring fit on an
enemy icon of the same agent while the teammate stood stacked under
another; a real icon explained away as a ping drawn beside it; an icon the
reader never fitted while the slot took a fit on an ability line; a swap
the chain evidence had not yet moved; a spectating witness that named the
wrong teammate; a fit on bare floor beside an ability drawing. Most need a
second channel to refuse the fit (the enemy reader, the ability readers),
cross-referenced before any cost is tuned.

Follow-ups for the next confirmation set (the held-out six are spent; new
matches from 2026-10-05), none tuned here: the ping bonus (6 nats within two
icon radii) explains real teammates away as pings; portrait evidence counts
twice, in the per-frame cost and in the chain sum; a chain-confirmed
portrait witness can be confidently wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import slot_state as ss  # noqa: E402
from reticle.slot_state import (ANCHORING, CHAIN_MIN, DECAY, ENTITY_BINDING_VERSION,  # noqa: E402,F401
                                HOW_ASSIGNED, HOW_ASSIGNED_SPECTATED, HOW_SELF, HOW_SPECTATE,
                                K_NP, K_RELOC, LLR_CLIP, NP_BONUS, NP_BUCKETS, NP_REASONS,
                                SPECTATE_RESTS_ON, SWAP_MIN, W_ID, WITNESS_EXCLUSIVE,
                                WITNESS_PORTRAIT, WITNESS_PORTRAIT_UNCONFIRMED, WITNESS_SELF,
                                WITNESS_SPECTATE, causal_bind, load_fits, off_map_mask,
                                raw_fits_from_rows, spectated_slots)

STORE = Path.home() / "reticle-store"


def params() -> dict:
    return ss.binding_params()
