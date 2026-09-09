# Economy and prediction layer

Date: 2026-09-09. Status: economy accounting core and explicit-fact CLI
implemented; automatic observation, store derivation and prediction integration
remain proposed.

Extends [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), the existing
`reticle/coaching.py` baseline, and the observation -> adjudication -> entity
lifecycle -> compound episode -> review architecture. Does not replace the
entity ontology or initiate detector work, rescans, or a labeling campaign.

## Product objective

Find valuable inflection points conditioned on the history available at the
time. Explain separately how a moment changed the expected round result, how
unexpected it was, and how it changed the likely continuation. Preserve source
pointers, uncertainty, ordinary controls, and correction links.

Economy is a deterministic accounting layer over evidence. Purchases and hidden
inventory are inference. Prediction consumes both without promoting an estimate
to an observation. Stage 02 remains deterministic and model-free.

## Existing integration points

- `coaching.py` already constructs as-of states from stored HUD/roster data,
  fits a regularized probability baseline with session holdouts, attaches
  before/after state deltas, and supplies review windows. Extend that path.
- The current baseline deliberately excludes economy, inferred plant, side,
  POV and causal credit. This design specifies future inputs; it does not
  claim they are already available or validated.
- The implementation plan already separates observation times from inferred
  occurrence intervals and defines compound episodes linked to entity IDs.
  Forecast targets should reference those definitions, not create a parallel
  set of player/ability identities.
- Round intervals end at score increment and do not cover the entire inter-round
  period. Economy needs an explicit settlement/carryover association for that
  period, without changing round intervals to make joins convenient.
- Historical corpus counts in the existing plans are historical measurements,
  not evidence that a richer model can currently be trained.
- `reticle/economy.py` now implements the pure ruleset, interval balances,
  spending, resets, settlement, survival eligibility and balance reconciliation.
  It deliberately has no video reader or automatic stored-match derivation yet:
  Reticle has no stable ten-player credit observation channel to supply either
  without guessing. The `reticle economy FACTS.json` command applies ordered,
  explicit facts and emits a reviewable ledger. `tests/test_economy.py` is the
  executable contract for this slice.

## 1. Economy ledger

Maintain per-team loss streak and per-player credit/inventory state. Use stable
match player identity across rounds, linked to round-scoped entity IDs. Unknown
identity prevents player-specific attribution; a roster count cannot supply it.

The initial standard-round assumptions are 800 starting credits, 3000 for a
win, 1900/2400/2900 for the first/second/third-or-later consecutive loss,
200 per credited kill and 300 for each attacking player when the spike is
planted. A win resets that team's loss streak. A reduced payout does not stop
the team's streak advancing.

For loss streak L including the round just lost, ordinary loss income is
`1900 + 500 * min(L - 1, 2)`. A qualifying survival penalty replaces this
round-result component with 1000; kill and plant components remain separate.

The survival predicate must include outcome and side. Riot's documented rule
specifies attackers surviving a loss without planting and defenders surviving
after detonation. It is not a blanket rule for every survived loss; in particular,
do not automatically penalize an attacker surviving a defuse loss.
Source: [Riot patch 1.11 economy rules](https://playvalorant.com/en-gb/news/game-updates/valorant-patch-notes-1-11/).
This is a documented rule origin, not an exhaustive verification of every patch
or mode. Pin the applicable ruleset before implementation acceptance.

Represent income, spending, refund, reset and reconciliation as separate ledger
entries. Record payer and recipient independently for teammate purchases.
Process transactions in game order with a ruleset-defined cap and award timing;
do not blindly sum an entire round and cap once. Deduplicate credited kills and
plants by reconciled event identity, not by the number of observing channels.

Ruleset parameters also include halftime and overtime resets, credit cap,
prices, refund eligibility, inventory persistence, free/recharging utility,
ultimate charges and special life mechanics. Do not assume an observed death
counter increment uniquely establishes a paid kill, final death, or inventory
loss. A partial capture must not initialize its first visible round to 800.

### Settlement and carryover

Keep three distinct times: round decision, economic award, and next buy opening.
Events after the decision can change surviving equipment and possibly payable
rewards. Link them to the relevant economic interval even when their gameplay
`round_id` is unresolved or outside existing round bounds. Record attribution
explicitly rather than assigning them to the next round by timestamp alone.

The rule for survival must use the game's relevant settlement/life state;
being alive at score increment alone is insufficient evidence of carryover.
Round-win probability is terminal after the decision, but economic impact may
continue until the next round. Unknown settlement timing remains unresolved.

### Observations, exact derivations, and feasible alternatives

An observed balance anchors accounting at its observation time. Known income
plus unknown spending does not establish an exact later balance. Preserve
separate fields for observed credits, derived exact credits when possible,
credit bounds, unexplained residual and evidence references.

Likewise, current weapon possession is not proof of purchase. Carryover,
teammate purchase, pickup and swap can explain it. An ability use constrains
earlier availability but does not necessarily establish a paid purchase.
An equip event is not a cast, and a free/recharged charge is not expenditure.

Maintain jointly feasible credit/inventory scenarios, starting with coarse
weapon classes and bounded ability counts where exact items are unavailable.
Scenarios must satisfy prices, known balance observations and item transfers.
No independent player estimates that spend the same team funds twice. Start
with bounds/alternatives; add scenario weights only with a stated, evaluated
prior. If pruning scenarios, preserve omitted/unknown mass rather than claiming
the retained set is exhaustive.

When evidence conflicts, retain the ledger and the observation with a residual
and explanation request. Do not invent a purchase to force reconciliation.

Outputs for prediction: current resources by player and team, distribution of
credits across players, known/possible retained items, and replacement-cost or
next-buy scenarios. Expected next-round purchasing power is a forecast, not a
deterministic credit observation. Ultimates remain a separate resource channel.

## 2. Information state and history

Let H_t contain only evidence available through t. Keep observed time, inferred
occurrence interval and evidence availability separate. A delayed killfeed read
can explain an earlier action retrospectively but cannot enter an earlier
forecast. Corrections produce a new retrospective version, never silently
rewrite a stored pre-event forecast.

Default perspective: information available to Reticle from the captured POV up
to that time. This is not omniscient state or a claim about what a player noticed.
Player-decision evaluation would need a separately defined information view.

Context includes map, side, score, phase, clock, spike, known alive/life states,
health, position age, visibility, equipment/resources and recent event history.
History summaries can encode trades, rotations, utility use and previous-round
buy/approach tendencies. Unsupported context stays null with reason; unknown,
stale, missing widget, terminal and refusal remain distinct.

The deterministic state layer never fabricates hidden positions. A prediction
layer may marginalize over explicitly labeled latent states. Its posterior is
not new independent evidence for detection, identity, or lifecycle adjudication.

For uncertain state Z, the conceptual win predictor is
`p_t = sum_z P(win | z, H_t) * P(z | H_t)`.
If only a feasible set is justified, report sensitivity across alternatives
rather than calling an arbitrary uniform average a calibrated probability.
Distinguish input ambiguity from uncertainty in the fitted model.

## 3. Three event measurements

Use the same model version and fixed team perspective before and after.

| Measurement | Definition | Interpretation |
|---|---|---|
| Outcome swing | `delta_p = p_after - p_before` | Signed percentage-point movement in round-win expectation |
| Outcome divergence | `JS(Bern(p_before), Bern(p_after))` | Optional symmetric, bounded distribution change |
| Surprise | `-log2 P(observed event or bundle | H_before)` | Realized surprisal; entropy is its expectation over outcomes |
| Continuation change | `JS(Q_before, Q_after)` | Revision of the distribution of a shared future target |

Use percentage-point swing as the primary readable outcome measure; retain
divergence for analysis. JS with base-2 logs is bounded by one bit. Signed
direction must remain available because divergence alone cannot identify who
benefited. Surprise must come from the actual pre-event forecast, not a model
conditioned on the event after it happened.

Define event probability over an explicit class, interval and spatial tolerance.
Exact continuous time/location tuples have no useful point probability. Model
support failure is not an infinitely surprising highlight: use held-out smoothing
and an explicit unsupported status. Missing observation coverage is not no-event.

Before/after deltas describe an observed interval, not individual causal credit.
When multiple changes occur within uncertain timing bounds, attribute to the
episode and expose those bounds. Do not isolate a single action by assertion.
Ordinary clock progression and information reveals can move predictions too.

## 4. Predicting event bundles

Start with a modest ontology of observable lifecycle events and coarse locations,
then model short dependent sequences. Initial horizon proposal: 5 seconds;
compare 10 seconds on training/validation data before freezing the definition.
An event such as a kill may have a coarse team-level forecast even when exact
participant identity cannot be predicted reliably.

Include no significant event, round termination, and censored/unobservable
intervals. Censoring is an eligibility state, not a gameplay outcome. Arbitrary
multi-label probabilities do not constitute a joint bundle distribution.

For sequence `(e1, ..., ek)`, factor the joint distribution through conditional
event/time probabilities with an explicit stop/survival component. This captures
entry -> trade -> plant dependencies without multiplying independent marginals.
Group sequences into readable bundles with a versioned mapping. If alternatives
overlap, do not present their probabilities as a mutually exclusive total.

### Comparable continuation distributions

Choose a pre-event anchor a, post-event anchor b, and common endpoint T. Q_before
predicts the target on `(b, T]` using H_a, marginalizing over the unobserved bridge
`(a, b]`. Q_after predicts that identical target on `(b, T]` using H_b. Both use
the same event vocabulary, spatial bins, endpoint and terminal convention.

Simply comparing 'next event' before a kill with 'next event' after it measures
a shifted target. Excluding the consumed event and aligning the future interval
is necessary for meaningful continuation change. For an initial simpler model,
use a shared coarse state-at-T target and record the transition to sequence
targets as a different metric version.

## 5. Selecting review moments

Score events and aggregate related events using existing compound-episode
semantics. An episode retains member IDs, net swing, peak internal swing,
surprise, continuation change, source interval and uncertainty. Do not sum
absolute event swings and call that net impact.

Initially rank largest absolute round swings, with separate unexpected-moment
and changed-continuation views. Do not multiply all three scores: an expected
decisive event would disappear. A learned combined ranking can follow player
review, with weights chosen on review/training data and frozen for evaluation.

Deduplicate overlapping moments and retain ordinary controls independently of
outcome. Uncertainty-heavy moments remain reviewable as unresolved; they should
not receive artificially large confident importance scores.

After the round is decided, report economic consequences separately from round
impact. A saved or destroyed rifle may affect the next buy while current-round
win probability is fixed. Add match-win prediction only after a model connects
round transitions, side changes, score and economy; a credit difference alone
does not establish a match-win probability change.

Example review card (illustrative, not measured): an entry/trade episode changes
round-win probability from 35% to 62% (+27 points), has pre-event bundle
probability 12% (3.06 bits of surprise), and shifts the continuation toward a
plant. Show alternative loadout sensitivity, evidence pointers and intervening
events. No claim that the entry player personally caused all 27 points.

## 6. Proposed artifact contracts

These are logical records, not a committed storage migration or filenames.

| Record | Required content |
|---|---|
| Economy transaction | Match/player/team, component, amount or bounds, payer/recipient, occurrence interval, availability time, source IDs, ruleset and adjudication versions |
| Resource snapshot | As-of time, exact/bounded credits, inventory alternatives, unresolved reasons, preceding transactions and observations |
| Forecast | As-of time, perspective, target/horizon, distribution or abstention, source snapshot, model/training-cutoff and feature versions |
| Moment estimate | Event/episode IDs, anchor times, before/after forecast IDs, separate scores, timing ambiguity, confidence/sensitivity, review pointers |

Keep independently versioned evidence, economy rules, inventory inference,
features, model, event taxonomy, metric definitions and review selection. Pure
derivations reuse stored evidence and do not decode video. New raw readers, if
later authorized, join shared passes rather than create a second decode path.

## 7. Design acceptance and implementation order

1. Specify settlement/reset rules and source coverage; build ledger and resource
   snapshots independently of statistical modeling. Worked acceptance examples:
   loss streak, survived defuse versus survival penalty, plant plus kill income,
   teammate-paid rifle, cap ordering, partial capture, halftime reset, post-round
   death/pickup, missing purchase and contradictory balance. No work is executed
   merely by listing these examples here.
2. Extend the existing structured win baseline with justified economy features
   and limited history summaries. Preserve the simpler model as a comparator.
3. Add episode-level swing review and uncertainty sensitivity. A model changing
   its mind when a hidden gun is revealed is an information event, not proof
   that the gun was purchased at the reveal time.
4. Evaluate coarse short-horizon forecasts before a large sequence model. Add
   bundle surprise and aligned continuation divergence only once their target
   distributions have usable held-out performance.
5. Add next-round resource forecasts and eventually match-win impact.

Evaluation uses complete matches grouped across duplicate captures, held out in
actual play chronology. Fit feature choices, smoothing, priors, calibration and
ranking weights inside training folds. Repeated states share outcomes; weight
rounds and cluster uncertainty by match. Assess Brier/log loss, calibration,
coverage/abstention, continuation likelihood and human review usefulness. Compare
with base rate, current clock/alive baseline and simple next-event frequencies.

Prediction may proceed with a reduced supported feature set; unsupported richer
features do not require a detector bug-finding session before design can advance.
The open architecture choice is evidence granularity and coverage, not whether
the full latent game state can be made exact. No calibrated deployment claim or
model capacity choice follows from existing historical corpus counts.
