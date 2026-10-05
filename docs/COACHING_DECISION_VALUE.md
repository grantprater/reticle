# Decision value: coaching play apart from mechanics

Status: design, proposed 2026-10-04. It builds on
[WIN_PROBABILITY_RESEARCH.md](WIN_PROBABILITY_RESEARCH.md) (the coarse
win-probability model, its calibration and the live-play rules),
[COACHING_ROTATIONS_LURKS.md](COACHING_ROTATIONS_LURKS.md) (rotation and lurk
events, regions, acceptance by labels) and
[BEHAVIOUR_MODEL_DESIGN.md](BEHAVIOUR_MODEL_DESIGN.md) (behaviour signatures).

## Conclusion

- Coarse state prices the round. Alive counts, loadout difference and the
  plant flag carry round win probability (WP); positions add nothing to it
  ([metric:winprob_reference/positions_K_riot#M3_alive_load_side.step.nats=-0.0004]
  with Riot positions,
  [metric:winprob_reference/positions_G_ally/window#step.nats=-0.00095] with
  reticle's allies). This design keeps that model, V(z), unchanged.
- Decisions act through transitions. Where a player stands relative to
  teammates, and when he moves relative to his information, changes the odds
  of the next coarse transition (his death, a trade, a retake beating the
  fuse); V prices the transition. This is the multiresolution structure of
  Cervone et al. (https://arxiv.org/abs/1408.0777) and the fourth-down recipe
  of Brill et al. (https://arxiv.org/abs/2311.03490).
- Each episode splits three ways: **decision** (the chosen context against a
  reference, priced at the rank band's conversion), **mechanics** (the
  player's conversion edge in that context) and **luck** (the rest). The round's
  result never enters the decision term.
- One player's sample cannot fit the slopes. The rank band, fitted on a limited
  ladder sample, carries them; the player's records move a few shrunk offsets;
  a CS sample tests how much structure transfers between games.
- Most single moments will read "uncertain", and the card says so.

## 1. Where decisions end and mechanics begin

An **episode** opens at a decision instant t_d, fixed before its outcome can be
seen and triggered whether or not the player acted. Riot records hold
`playerLocations` only at kill, plant and defuse instants, so every episode
fitted on Riot records opens at one of those instants; any player's kill
serves as the clock. Rotation lag (cue to leaving) and first contact need
movement between those instants, so they wait for reticle's POV streams or
replays (S5).

| Decision | Trigger t_d | Context c (the choice) | Alternatives |
|---|---|---|---|
| Trade spacing | every kill instant with the player and at least one teammate alive | nearest living teammate's distance, then path distance and line of sight | close to trade range |
| Rotation | a cue: ally death, ally ping or sighting, plant | lag from cue to leaving; distance to site at plant | leave 5 s earlier; hold |
| Lurk | each kill instant on attack | distance from the nearest teammate and from the team's contact | regroup |
| Retake or save | plant with the round near lost | alive, loadout, clock landmark | retake; save |
| First contact | the round's first engagement | teammates within trade range, clock | wait for a teammate |

- **Decision**: what the player chose and could know at t_d. That covers his
  own and teammates' positions (allies are always on the minimap), the
  killfeed, spike state, clock, carried utility and buy. Enemy features enter
  only as reticle observed them (sightings, pings). Records that hold all ten
  players' positions never put enemy positions into c, so no context is
  omniscient.
- **Mechanics**: conversion once contact starts (duels, spray, peek
  technique), reported as realised minus expected and never coached as a
  decision.
- **Abilities** split the same way: sending a dog into a group is a decision;
  whether it led to a kill is an ability effect, read from the assist panel
  [domain:killfeed/assist-panel] once that stream merges.
- **Ruling.** Position relative to teammates and cues is a decision; how an
  angle is cleared or swung is mechanics, probably beyond minimap fidelity and
  left to a future screen-analysis channel. For coaching, this ruling
  supersedes `PROJECT_GUIDE.md` L417, which lists positioning under
  mechanics; that file keeps former guidance verbatim and stays unedited.

## 2. Estimator

**Value.** V(z), z = (attackers alive, defenders alive, loadout-difference
class, plant flag), from `prototypes/winprob_reference.py` 0.2.0. Loadout is
its one resolved gain
([metric:winprob_reference/riot_G#step:M1_alive->M2_alive_load.nats=0.01719]),
with plant
([metric:winprob_reference/riot_G#step:M3_alive_load_side->B1_plant_flag.nats=0.00264]).
The point-of-view (POV) version marginalises the round filter's posterior over z.

**Transitions.** Bayesian hazards P(o | z, c; θ) with competing outcomes.
A trade-spacing episode ends within N s (N = 10, fixed in §7) in one of
three: the player dies untraded, dies and is traded within 5 s, or survives; a multinomial logistic
fits them jointly, so spacing is priced through the chance of dying as well
as the chance of being traded. Other episodes use: next kill ours, retake
before the defuse landmark, next round's loadout class after a save.
Coefficients pool hierarchically:

```
θ_shape  (CS, wide τ_s, declares rests_on)
  -> θ_val   (VALORANT ladder, every match containing the player excluded)
    -> θ_band  (rank band; map and patch as partially pooled effects)
      -> θ_me    (the player's uncaptured matches)
```

The between-player spread τ_p, estimated from the ladder sample, sets how far
the player's own episodes can move him from his band. θ_me fits on the
uncaptured matches of the player's three accounts, which branch
`ladder-fetch-20261004` is fetching; their counts are unknown until fetched,
and any count is recorded as a ledger row before it is quoted. Production fits
exclude the captured matches. Fitting is MAP with a Laplace posterior through
statsmodels or scipy, vectorised.

**Decomposition**, for episode e in state z with context c_e:

```
D_e = Σ_o [P(o|z,c_e; θ_band) − P(o|z,c_ref; θ_band)] · ΔV(o,z)   decision
M_e = Σ_o [P(o|z,c_e; θ_me)   − P(o|z,c_e;  θ_band)] · ΔV(o,z)   mechanics
ε_e = ΔV_realised − Σ_o P(o|z,c_e; θ_me) · ΔV(o,z)               luck
```

A baseline fitted with the player inside absorbs his skill
(https://arxiv.org/abs/2401.09940 corrects this by multicalibration); this
design leaves the player out of θ_band. c_ref is a named alternative or the
band's propensity-weighted typical context in z. Where the best choice depends on aim (taking a 1v1), D
is also shown at θ_me as a sensitivity line. M absorbs teammates' and
opponents' skill too, so it reads "duel results against expectation", never
"aim".

**Off-policy guards.** A propensity model P(c | z) on the same hierarchy
gates every comparison: an alternative is valued only where its propensity is
at least 0.1 and at least 30 band episodes in comparable z chose it; otherwise
D is null with reason `no_comparable_play`. A doubly robust estimate replaces
regression adjustment once the ladder sample exists.

**Uncertainty.** A cluster bootstrap by match (101 refits) gives each D an
interval and a sign-agreement share; a moment reads "confident" at 0.83
agreement or more (Brill et al.'s threshold) and "uncertain" otherwise. Season
lines give the player's shrunk offset, its interval and its data weight.

## 3. Data

**Rule.** The use policy lives in
[EXTERNAL_GROUND_TRUTH.md](EXTERNAL_GROUND_TRUTH.md): these sources may fit
win-probability and coaching baselines and priors; they never feed a reader,
a reader's threshold or anything shown during play; matches that evaluate a
fitted model are held out from its fit. An estimate that rests on them
declares `rests_on`.

**Sources.** Two docs on unmerged branches own the samples, their terms and
budgets; this design names only what the models need from them.

- `docs/LADDER_SAMPLE.md` (branch `ladder-fetch-20261004`): a polite
  HenrikDev fetcher, the player's own accounts first, then the ladder sample
  (ruling 1 below).
- `docs/CS_TRANSFER_SAMPLE.md` (branch `cs-scout-20261004`): the ESEA tables
  already in the store's `external/cs/kaggle_mm_mirror` and the samples of
  ruling 5.

| Source | Holds (verified 2026-10-04) | Size | Use |
|---|---|---|---|
| Own accounts, Riot PD records | kills with every living player's location and view, assistants, per-round economy, plant and defuse site, time, location and players' locations, `competitiveTier` | 22 stored; up to about 76 to fetch | uncaptured: fit θ_me; captured: evaluate |
| HenrikDev ladder sample | Riot's schema relayed; field names unconfirmed | per `LADDER_SAMPLE.md` | fit θ_val and θ_band |
| CS samples | per `CS_TRANSFER_SAMPLE.md` | 2 GB bound | θ_shape; CS skill gradient |
| VLR.gg and the VLR-scraped Kaggle VCT set | round winner, buy class, first kills; no kill timeline or positions | — | not used: VLR forbids compiling its data (https://www.vlr.gg/terms) |
| Own replays (15 `.vrf`) | all ten players at 128 Hz between kills | 15 | the 14 uncaptured: held out to test models |

Riot's VAL-MATCH-V1 refuses personal apps
(https://developer.riotgames.com/docs/valorant).

**What transfers.** Ladder records transfer everything at the right rank. CS
transfers shape only: trade-odds decay with spacing, the WP curve over alive
counts, and how both change with skill. Never map, kit, utility, economy or
time-to-kill values. Pro data transfers the coarse economy shape only.

**What the models need from the fetcher.**
- Fields: per match, `matchId`, map, `gameVersion`, start time, queue, ranked
  flag; per player, account id, team, agent, `competitiveTier`, party; per
  round, winner, result code, plant time, site, location, planter and
  `plantPlayerLocations`, defuse time, location and players, per-player
  `loadoutValue`, spent and remaining; per kill, `gameTime`, `roundTime`,
  killer, victim, assistants, `victimLocation`, `playerLocations` with
  `viewRadians`, finishing damage.
- Normalisation: HenrikDev records mapped to Riot's keys, accepted by a
  field-by-field diff against the PD record of the same match on at least
  three of the player's own matches.
- Rank bands: Iron–Bronze, Silver–Gold, Platinum–Diamond, Ascendant–Radiant;
  each at least 40 players with 5 ranked matches each (a planning figure for
  estimating τ_p, unmeasured). A band that does not fill is reported short,
  never widened.
- Patch window: the patches the player's own records span plus the current
  one; patch enters as an effect, never a pool boundary; a patch that changes
  the economy rules is checked against [domain:rounds/credit-ledger-rules].

**Splits.** (a) The 22 captured matches never enter a production fit; they
evaluate the POV estimator and the card. The pilot alone fits on them,
leaving one match out. (b) The player's uncaptured matches fit θ_me up
to a play-order cutoff; the last 20% evaluate it. (c) The ladder sample splits
by player; no match containing the player enters θ_val or θ_band. (d) CS never
evaluates a VALORANT model. Each fitted table stamps its split manifest's
digest, its source digests and its version.

### Player decisions

Ruled:

1. **HenrikDev ladder sample.** Under 2000 matches, pseudonymised, never
   published, for comparison with the player's own games
   (`docs/LADDER_SAMPLE.md` on branch `ladder-fetch-20261004`).
2. **Replays.** The 14 uncaptured replays stay held out to test models.
3. **The VLR-scraped Kaggle VCT set.** Not used.
4. **Positioning.** Position relative to teammates and cues is a decision;
   angle technique is mechanics (§1).
5. **CS data.** The Kaggle ranked-matchmaking set and 100 ESTA pro demos,
   under the 2 GB bound (`docs/CS_TRANSFER_SAMPLE.md`); FACEIT deferred.

Open:

6. **Lurk and rotation definitions.** The open questions in
   COACHING_ROTATIONS_LURKS.md.
7. **Labels.** Whether the player's labels tune ranking weights or only
   accept.

## 4. Observations and fidelity

Episodes need state at decision instants only, at 2 Hz. A 0.5 s lag costs
[metric:winprob_reference/alive_lag#B3_phase_clock.lag_0.5s.bits=0.00715]
bits.

| Need | Stream | Accuracy |
|---|---|---|
| Deaths and trades | `death` | [metric:riot_truth/deaths#recall=0.9955] |
| Alive state | round filter | [metric:round_filter/riot_G/clock#cost_nats=0.01536] nats against Riot |
| Plant | rounds | [metric:riot_truth/rounds#plant_both=251] read by both; **no site stored** |
| Teammates at t_d | `round_entity` | [metric:riot_truth/minimap/all#matched=8366] of [metric:riot_truth/minimap/all#riot_allies=10445] at kills; on one replay, [metric:replay_truth/score@9acf02f98283#ally_coverage=0.3825] of living ticks |
| Ults, all ten players | `ult_cast` | [metric:riot_truth/ult#recall=0.9028] |
| Loadout | economy ledger | [metric:riot_economy/team_rounds#regular_ok=815] of [metric:riot_economy/team_rounds#regular_n=816]; not wired to events |
| Regions | none | callout cells failed ([metric:coaching_callouts/ascent@a06f04a0059f#boundary_share_7p6px=0.2185] near a boundary); drawn polygons needed |

**Gaps.** Enemy sightings exist on three sessions; assists live on an unmerged
branch; engagements without a kill need self-HP drops.

**Interface.** A future owner emits `decision_episode` events (t_d, z, c,
reference, D, M, ε, intervals, agreement, `rests_on`, the fitted table's
version); `reticle view` reads only those. Episodes compute after each round;
the card renders after the match, never after a round, as
COACHING_ROTATIONS_LURKS.md rules.

## 5. What the player sees

The numbers below are illustrative, not measured.

- **Trade spacing, round 14, Ascent defence.** "Died at Market 1 s after
  contact; nearest teammate 24 m, no line of sight. At the kill before, your
  band dies untraded from this state 30% of the time; at your spacing, 52%.
  Decision −0.03 WP [−0.05, −0.01], 0.88 agreement. Duel: lost one expected at
  47%; within expectation, not coached."
- **Match card.** The three confident episodes with the largest |D|, each
  beside a same-z control chosen blind to outcome, for the player to label.
  Season lines are shrunk ("lurk spacing −0.4 rounds per match against your
  band [−0.9, +0.1]; your data's weight 0.3"); mechanics get their own line
  ("opening duels expected 49%, realised 51%").

**Guards against the outcome fallacy and selection.** D reads no outcome, so a
won round can carry negative D. Triggers ignore outcomes and keep no-contact
opportunities: a trade-spacing episode opens at every kill instant the player
survives, not at his death. Controls are stored beside surfaced episodes;
comparisons stay within z and buy class. Team-strength proxies (score, rank
gap, party) adjust but never earn credit. An unsighted enemy is "unknown",
never "absent". Kill-anchored episodes flatter fights that ended in a kill
until engagement episodes exist, and the card says so. Fits update only from
completed matches.

## 6. Staged plan

Commands name a planned prototype, `prototypes/decision_value.py`, under the
repository venv.

| Stage | Work | Acceptance command | Evidence standard |
|---|---|---|---|
| S0 | Trade-spacing pilot on the 22 stored records (§7) | `prototypes\decision_value.py pilot` | Predictions logged before the run; ledger rows `decision_value/pilot`; leave one match out; 101 bootstrap refits by match |
| S1 | Fetch (`ladder-fetch-20261004`, `cs-scout-20261004`) | the fetchers' manifest reports | Band counts meet §3 or are reported short; HenrikDev-to-PD diff clean on 3 own matches; ids in the store only |
| S2 | Hierarchical transition and propensity models | `decision_value.py fit` | Held-out log loss on held-out ladder players and on the player's held-out 20% beats the band-free model, with a bootstrap interval; τ with intervals; separation: on held-out ladder players, the per-player correlation of mean D and mean M has a 95% interval inside ±0.3, set before the run; split digest in deps |
| S3 | CS transference | `decision_value.py transfer` | Learning curve on band data: CS prior against a flat prior at 1-50 matches, with the crossing point reported whichever way it falls; CS skill gradient against band gradient |
| S4 | POV substitution on the 22 captured matches, at the same kill instants as S0 | `decision_value.py pov` | Reticle-feature model within 0.005 nats of the record-feature model; coverage reported |
| S5 | Rotation, lurk and first-contact episodes | after COACHING_ROTATIONS_LURKS R1-R5 and a plant-site field | Retake model from `plantPlayerLocations` resolves defenders' distance (interval excludes 0) |
| S6 | `decision_episode` owner and card | `reticle view <sid>` | The player labels surfaced episodes against controls; a bar the player sets beforehand |
| S7 | Skill-ladder report | `decision_value.py ladder` | Per-band coefficients with intervals; a monotone trend is claimed only where intervals separate |

## 7. First experiment: trade spacing on the stored records

The 22 stored Riot records, single-threaded, seconds of compute. Leave one
match out, so every evaluated match is held out from the fit that scores it;
production fits exclude these captured matches. The player is found by
`riot_ground_truth.identify_player`, then `resolve_lineup_player`, which names
him in [metric:decision_value/pilot_power#matches_by_lineup_agent=1] record
(4f207c0c4e39) by the lineup's agent; episodes there declare
`rests_on: lineup.player`. Episodes open at every kill instant with the player
and at least one teammate alive
([metric:decision_value/pilot_power#kill_instants_player_alive_with_teammate=1907]
on all [metric:decision_value/pilot_power#matches_identified=22] records).
Context is the nearest living teammate's distance from that instant's
`playerLocations` (the player's team only). Outcomes within N = 10 s, fixed
now, compete: dies untraded, dies traded within 5 s (revived victims
removed), survives; a death after 10 s counts as survival. Episodes from kills
less than 10 s apart overlap and share outcomes; the bootstrap resamples whole
matches, so it absorbs that correlation. Fit the outcomes jointly given
distance and z with a player offset, price D and M with ΔV from
`winprob_reference`, then substitute reticle's teammate positions at the same
instants on the captured matches (S4).

**Power.** The player has
[metric:decision_value/pilot_power#player_deaths=329] deaths in the records,
[metric:decision_value/pilot_power#deaths_with_living_teammate=286] with a
living teammate, of which
[metric:decision_value/pilot_power#traded_5s_of_those=45] were traded within
5 s. On those deaths the trade offset's standard error is about
[metric:decision_value/pilot_power#offset_se_logit=0.162] logit, so an offset
under about ±[metric:decision_value/pilot_power#significance_offset_logit=0.318]
logit cannot reach significance, and 80% power needs about
±[metric:decision_value/pilot_power#power80_offset_logit=0.455] logit. A
per-match correlation over 22 matches has a 95% half-width of about
[metric:decision_value/pilot_power#match_r_halfwidth_95_n22=0.422], and mean
D and mean M share the player offset by construction, so the pilot does not
test whether D and M separate; S2 does.

**Planned predictions**, to log in `notes/predictions.jsonl` before the run,
all with N = 10 s:

- **P1.** The distance slope on dying untraded is positive and its 95%
  interval excludes 0. Among deaths with a living teammate, the nearest
  quartile's trade rate is at least twice the farthest's; P1 fails below 1.5
  times.
- **P2.** Distance improves held-out log loss over z alone by at least 0.01
  nats per episode, with a bootstrap interval that excludes 0.
- **P3.** The player's offsets' intervals span 0.
- **P4.** At the episode instants (kill instants with the player and at
  least one teammate alive in the record), reticle's teammate positions place
  at least one living ally at 70% or more of them. The same share at the
  player's deaths with a living teammate is reported as a second line. The
  model on reticle's positions sits within 0.005 nats of the record-position
  model.

If P1 fails while P2 holds, test path distance next. If P4 fails, reader
coverage, not sample size, blocks this behaviour.

## 8. What it cannot do

- Value a policy no one in the band plays (positivity).
- Price information or distraction that leaves no transition, such as a lurker
  holding three defenders' attention.
- Value utility beyond its effect on transitions, or comms at all.
- Coach teammates' decisions, or predict how opponents adapt to a changed
  policy (https://arxiv.org/abs/1812.05170).
- Claim causes beyond "no unmeasured confounding given (z, c)".
- Judge plant-site choice before reticle stores the site.
- Validate itself on round outcomes; the player's labels are the acceptance
  standard.
