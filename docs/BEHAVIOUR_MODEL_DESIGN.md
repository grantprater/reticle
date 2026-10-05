# Behaviour dynamics: hierarchical predict-update model

Date: 2026-09-25. Status: long-term design goal. Two pieces ship: name
continuity (`reticle/adjudication/killfeed_names.py`) and a reliability table
(`reticle/adjudication/reliability.py`); the rest is unbuilt. The
player's intent, recorded at their request. Extends
[ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md) and sits downstream of the
acceptance north star in `AGENTS.md`: behaviour is inferred from
identity-bearing events, never in place of them.

## Intent

A long-term goal of the project is to extract behaviour dynamics, patterns and
archetypes from VODs: group tactics such as a five-player rush, individual
roles such as a lurker or an entry, and individual tendencies such as baiting.
These should come out of the same inference that names agents and tracks
entities, not from a separate heuristic layer.

## Framing: predict-update-smooth at three timescales

Almost everything the pipeline observes is state that persists and changes by
events. The general method is predict-update filtering: carry the state
forward, predict the next observation, and correct by the prediction error
(the innovation). Cost follows surprise: a prediction that holds is cheap to
confirm, and only a large innovation widens the search (`AGENTS.md`, "Continue
the prior; widen the search only on surprise").

Behaviour is the same machinery one level up. Each level is the prior for the
level below and is updated by it:

| Timescale | Latent state | Evidence |
|---|---|---|
| frame | position, alive state, entry identity | minimap, roster, killfeed |
| round | team plan (rush, split, default); each player's role this round | positions, contact timing, death order |
| match and career | each player's tendencies (lurks, baits, entries, anchors) | the roles inferred over many rounds |

The standard names for the pieces:

- **Switching state-space models:** a hidden discrete mode (executing a rush,
  holding, rotating) selects which dynamics the positions follow; the filter
  infers the mode from the motion.
- **Hierarchical HMMs and hierarchical Bayesian models:** a per-player trait is
  a parameter shared across that player's rounds; each round updates it a
  little and it shapes the prior for the next.
- **Smoothing, not only filtering:** the pipeline is offline and holds the
  whole VOD, so beliefs use later evidence too (forward-backward for discrete
  state, Rauch-Tung-Striebel for continuous).
- **Multiple-hypothesis tracking:** keep competing associations alive until
  evidence prunes them, rather than guessing.
- **Factor graphs and message passing:** couple per-entity models only where
  entities interact; pass each channel's information once, so no evidence is
  counted twice (the repository's `depends_on` rule).

## One model: minimap entities, events and behaviour

The frame level is multi-target tracking, and it covers minimap mining and
event recognition as well as identity. Parts of the pipeline already work this
way without the name:

- **Baked geometry is the prior for the background.** It predicts an empty
  minimap, and `SESSION PIXELS DO NOT DEFINE THE MAP` keeps that prior out of
  the observation it explains.
- **Residual mining is innovation.** `prototypes/entity_mining_residual.py`
  seeds areas from `lighting.raw_dark` births after tray casts: observation
  minus prediction, read as a birth.
- **Tracks with censored lifetimes:** `round_lifetimes` for ally icons,
  `reticle smokes` for smokes.

What the full model adds:

1. **Each entity carries a predicted future.** An icon predicts its next
   position from its motion; a smoke predicts its expiry from its duration. A
   frame is mostly confirmation; the surprises are the events.
2. **Channels predict each other, and events are transitions.** A tray charge
   drop predicts an ability entity near the caster; an ally icon vanishing
   predicts a killfeed entry and a roster drop; a killfeed death places a death
   on the map. Recognising an event is testing which transition explains the
   innovation, and whether the other channels' predictions came true; when they
   did not, the surprise is stored.
3. **Birth and death of an unknown number of entities:** multi-target tracking
   with birth-death processes (PHD or multi-Bernoulli filters). Detections are
   gated against predicted tracks; what falls outside every gate is a birth
   hypothesis; a track no longer observed decays toward death, or toward
   unobserved where it could be hidden.
4. **Sampling follows expected information:** dense reads around casts,
   contacts and predicted expiries, sparse ones where every prediction holds.

The minimap is harder than the killfeed: it is translucent, icons overlap and
cones are partial, so its likelihoods need calibrating; censoring is everywhere
(enemies only when spotted, smokes hide what is inside); and each entity type
(icons, abilities, cones, pings) needs its own dynamics and appearance model,
coupled only where entities interact.

## Requirements the model imposes

- **Calibrated likelihoods.** Readers emit scores; the update step needs
  P(observation | state). The player's labels calibrate them.
- **Censoring.** Enemies appear on the minimap only when spotted. An unseen
  enemy is unobserved, not absent, and the model carries that.
- **Honest process noise and re-acquisition.** A filter that trusts its prior
  too far locks in a wrong state; a sustained large innovation re-opens the
  wide search, and the surprise is stored.
- **Defined before discovered.** Archetypes are first defined by the player as
  domain facts in `domain/*.toml` (a trade window, what counts as separate from
  the team), computed with their uncertainty and checked against the VOD.
  Unsupervised discovery (clustering, fitted switching models) comes second,
  reviewed by the player, since structure found in measurement artifacts looks
  like structure found in play.

## Inference architecture

Agreed with the player on 2026-09-25; the route from today's agreement
counting to the model above.

**Three roles.**

1. **Readers** emit calibrated likelihoods over a declared candidate set:
   P(observation | hypothesis) for each hypothesis they scored. They never
   decide, and never apply a prior to their own output.
2. **Beliefs** live in named, owned variables: `name_agent[match, name]`,
   `entry_victim[death]`, `alive[side, agent, t]`. Each has one owner in
   `ownership.toml`, as questions do now.
3. **Inference** combines factors -- evidence and constraints -- into
   posteriors. A variable's value is published when its posterior is
   confident; a refusal carries the posterior, so a consumer sees what the
   evidence favoured and by how much.

**Gating, not scoring.** A prior narrows WHICH hypotheses a reader scores (the
side's five, the match's ten, the slot's predicted agent); it never changes a
score. When even the best gated candidate fits poorly, the reader widens to
the full set and records why: that is the surprise path of "Continue the
prior". A gated likelihood table declares its scope, so inference knows the
set it covers. [Prior-driven readers](PRIOR_DRIVEN_READERS.md) audits every
reader against this rule and ranks where a prior would pay.

**`identity_claim` becomes a factor.** It already carries a channel, an entity
key, evidence and `depends_on`. It gains a likelihood table over its candidates
and the scope that produced them. The arbiter keeps its interface -- claims
in, verdicts out -- and changes its internals from agreement counting to a
posterior per entity, then per match. Every name still passes through
`adjudication.identity`.

**Double counting becomes structural.** A factor attaches to the graph once;
two claims from one observation are one factor, and repeated views of one
entry are one channel's evidence, not a dozen witnesses. `depends_on` stays as
provenance: a claim whose name rested on another verdict attaches no new
factor for that verdict's information. The prior that gated a reader is not
counted again in its output.

**Name continuity.** A killfeed name should belong to one player, hence one
agent, for a whole match. If stage 2 confirms it, match identity is an
assignment of five names to five agents per side: at most 5! = 120 hypotheses,
small enough to enumerate exactly. Every entry then informs its name's
assignment, and the side's five-distinct-agents rule
[domain:rounds/agent-uniqueness] couples the names.

**Stages.**

1. Per-source likelihood-ratio calibration of portrait scores (official art;
   in-session exemplars), fitted on independently witnessed entries only.
2. Measure name continuity from the killfeed crop cache.
3. Factor form of `identity_claim`: a likelihood table and a declared scope.
4. A per-match identity graph in the arbiter over names and agents.
5. `agent-alive` as a time chain (deaths and revives as transitions).
6. Readers query the belief store for their candidate sets.

## Candidate signatures

Hypotheses for the player to define or reject, not domain facts:

| Archetype | Observable signature |
|---|---|
| five-player rush | low team spread, synchronised movement, early first contact, deaths clustered in time and place |
| lurker | far from the team centroid, often on the other side of the map, contact late or apart from the team's |
| baiting | enters contact after a teammate dies there, repeatedly |
| entry | first contact or first death of the round, most often |
| anchor | holds one site across rounds, rotates late |

The player chose rotations and lurks as the first coaching question
(2026-10-04); [COACHING_ROTATIONS_LURKS.md](COACHING_ROTATIONS_LURKS.md)
plans them as events.

## Order

1. **Foundation (in progress):** identity-bearing killfeed events, then
   `agent-alive`, the first end-to-end predict-update-smooth model (per side
   and round; transitions are deaths and revives, emissions the roster count
   and the packed survivor portraits).
2. **First behavioural target: trades and baiting for the player's own team**
   (player, 2026-09-25). It needs only named deaths, their order and timing,
   and ally positions, and the player can judge the result directly.
3. Round-level team plans and roles for the player's team, where positions are
   fully observed.
4. Tendencies across the player's sessions: most data, fully observed, and the
   target a coaching layer can act on.
5. Enemy behaviour, through the killfeed and spotted moments, with censoring.
