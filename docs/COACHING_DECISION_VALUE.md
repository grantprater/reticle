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
- Who can join a fight, read on sightlines, predicts it better than who
  stands near it, but by about a thousandth of a nat; it predicts trades
  well, as distance does (§9).

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

**Disclosure.** P1-P4 were reworded after the two `decision_value/pilot_power`
count runs had been read: commit feb1a0b followed the first run and d68ecc6
the second. The changes: P1's slope moved from "dying traded, negative" to
"dying untraded, positive" under the new competing outcomes, and its trade-rate
clause was limited to deaths with a living teammate; P2 counts per episode,
not per death; P3 names the player's offsets; P4 moved from his deaths to
the episode instants; P5 moved to S2. The count runs gave episode, death and
trade counts and the power figures above; no distance slope, log loss or
offset was fitted before the rewording. The prediction row (02:30:10Z) logs
the reworded text; a correction row in the ledger records this.

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

## 9. Results: engagement reach (2026-10-04)

`prototypes/engagement_reach.py` (engagement-reach-0.1.0) scored who can
join a fight once on the player's own competitive history. `decision_value.py
reach` had fixed its parameters on the 22 captured records: swing 2 m, trade
5 m, callout nodes, radius 5 m, plant 5 m. Predictions REACH1-REACH6 went
into the store's `notes/predictions.jsonl` (03:13:59Z) before any feature,
fit or score touched the history; the confirmation agent had read the
history's schema and counts at 02:59-03:00Z, before that row. Each number
below cites its ledger row; development figures are labelled. Weapons and
utility reach are left out.

**Placeholder body heights.** Every REACH figure below, the confirmation's
and its sensitivities, was computed on Ascent's and Split's
`sightlines-3d-0.1.0` tables, whose body heights were placeholders: eye
160 cm, chest 120 cm, crouch room 100 cm, jump 120 cm. The game's files give
eye 175 cm, body centre 98 cm, crouch room 56 cm, jump 115 cm
([SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md), "Body heights (0.3.0)").
The confirmation set is spent, so a rerun at the game's heights is post hoc
only, never a second confirmation; a correction row in the store's
`notes/predictions.jsonl` records the error. Post hoc at
`sightlines-3d-0.3.0`, with the same map choice and the same 123 matches:
REACH1 gains
[metric:engagement_reach/confirm/heights-0.3.0#REACH1.improvement_nats=0.00125]
[0.00046, 0.00201] (confirmed 0.00127 [0.00048, 0.00205]), null p95
[metric:engagement_reach/confirm/heights-0.3.0#REACH1.null_p95=0.00007];
REACH2's reach minus radius is
[metric:engagement_reach/confirm/heights-0.3.0#REACH2.reach_minus_radius_nats=0.00113]
[0.00042, 0.00186] (confirmed 0.00116 [0.00043, 0.00192]). Neither verdict
moves: REACH1 fails the bar, REACH2 holds.

**Sets.** Development: the captured records,
[metric:engagement_reach/dev#fights=3324] gun fights. Confirmation: of
[metric:engagement_reach/confirm#set.matches_listed=170] parsed matches, the
[metric:engagement_reach/confirm#set.held_out_excluded=2] held-out replay
matches and [metric:engagement_reach/confirm#set.no_table_excluded=45] on
maps without a sightline table (Bind, Pearl, Corrode, Fracture, Icebox,
Breeze) are excluded; no captured match is in the history. That leaves
[metric:engagement_reach/confirm#matches=123] matches,
[metric:engagement_reach/confirm#set.admitted_rounds=2454] admitted rounds
and [metric:engagement_reach/confirm#fights=17847] gun fights. The tables
carry no attacker role; Red attacks rounds 0-11 and even overtime rounds, and
[metric:engagement_reach/confirm#set.planter_on_attacking_team=1657]
planters stand on that team, against
[metric:engagement_reach/confirm#set.planter_on_other_team=0] on the other.

**Sightline map per map.** Ascent and Split use the 3D map from the game's
collision ([SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md)); the other five
maps use the 2D minimap map. The rule follows the probe's gate on the same
development kills: Ascent 3D
[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#los3d_share_on_2d_set=0.869] against 2D
[metric:sightlines_3d/gate/ascent#los2d_share=0.549], Split
[metric:sightlines_3d/gate/split~2026-10-04T22:11:22#los3d_share_on_2d_set=0.911] against
[metric:sightlines_3d/gate/split#los2d_share=0.707]. On the cell tables the
features read, Ascent's 3D cell line of sight holds for
[metric:engagement_reach/gate#ascent.los3d_strict=0.8695] of gun kills
against the 2D table's tolerant
[metric:engagement_reach/gate#ascent.los2d_tolerant=0.728]. Split ties:
[metric:engagement_reach/gate#split.los3d_strict=0.8578] against
[metric:engagement_reach/gate#split.los2d_tolerant=0.8594], but the 3D
control (the killer against the victim's other living teammates) is lower,
[metric:engagement_reach/gate#split.control3d_strict=0.0829] against
[metric:engagement_reach/gate#split.control2d_tolerant=0.1092]. A stricter
table rule, written first and set aside after this development gate ran,
would have kept Split on 2D; the rule the prediction row logs is the
replacement, and a correction row in the ledger says so. The 3D map's walk
graph, rebuilt from the stored cells, reproduces the stored components
exactly. One-way drops are not modelled.

**Holdout disclosure.** The ladder sample flags one match in five as
`holdout` ([LADDER_SAMPLE.md](LADDER_SAMPLE.md): a match that evaluates a
fitted model stays out of its fit). Of the 123 confirmation matches,
[metric:engagement_reach/confirm/no_holdout#set.holdout_excluded=22] carry
the flag, and the confirmation fitted on them. This analysis touched them; it
persisted no model, so no stored fit carries them forward. A post hoc
sensitivity reruns REACH1-REACH6 without them
([metric:engagement_reach/confirm/no_holdout#matches=101] matches,
[metric:engagement_reach/confirm/no_holdout#fights=14729] fights). Every
verdict stands: REACH1 gains
[metric:engagement_reach/confirm/no_holdout#REACH1.improvement_nats=0.0011]
[0.00028, 0.00199]; REACH2 holds at
[metric:engagement_reach/confirm/no_holdout#REACH2.reach_minus_radius_nats=0.00103]
[0.00024, 0.00187]; REACH3's share is
[metric:engagement_reach/confirm/no_holdout#REACH3.own_share=0.38] [-0.72,
0.93]; REACH4 holds for defenders,
[metric:engagement_reach/confirm/no_holdout#REACH4.coef_def_per_player=-0.139]
[-0.183, -0.083], not for attackers,
[metric:engagement_reach/confirm/no_holdout#REACH4.coef_att_per_player=0.0284]
[-0.008, 0.066]; REACH5 gains
[metric:engagement_reach/confirm/no_holdout#REACH5.improvement_nats=0.00683]
[0.0007, 0.0125], under the bar; REACH6's difference is
[metric:engagement_reach/confirm/no_holdout#REACH6.able_minus_distance_nats=0.00332]
[-0.0025, 0.0092]. One reading weakens: REACH5's defender direction,
[metric:engagement_reach/confirm/no_holdout#REACH5.coef_def_reach_per_player=-0.1448]
[-0.366, 0.027], no longer excludes 0.

**Shuffle null.** The confirmation's null used 20 position permutations
(p95 +0.00006); an independent check with 8 came out all negative (p95
-0.00007). Rerun with 200 permutations (same seed; every other figure
reproduced exactly): mean
[metric:engagement_reach/confirm/null200#REACH1.null_mean=-0.00016], p95
[metric:engagement_reach/confirm/null200#REACH1.null_p95=0.00002], and
[metric:engagement_reach/confirm/null200#REACH1.null_share_ge_observed=0.0]
of the 200 reach the observed
[metric:engagement_reach/confirm/null200#REACH1.improvement_nats=0.00127].
REACH1's gain clears its null by a wide margin whichever null is used; it
fails only the 0.01 bar.

**Predictions** (confirmation, development beside):

| | Prediction | Confirmation | Outcome |
|---|---|---|---|
| REACH1 | reach model gain >= 0.01 nats per fight, interval > 0, above the shuffle null | [metric:engagement_reach/confirm#REACH1.improvement_nats=0.00127] [0.00048, 0.00205]; null p95 [metric:engagement_reach/confirm#REACH1.null_p95=0.00006] (development [metric:engagement_reach/dev#REACH1.improvement_nats=0.0014]) | failed: real, an eighth of the bar |
| REACH2 | reach beats radius 5 m | [metric:engagement_reach/confirm#REACH2.reach_minus_radius_nats=0.00116] [0.00043, 0.00192]; radius alone [metric:engagement_reach/confirm#REACH2.radius_improvement_nats=0.00011] (development [metric:engagement_reach/dev#REACH2.reach_minus_radius_nats=0.0016]) | held |
| REACH3 | own-team features keep half the gain | share [metric:engagement_reach/confirm#REACH3.own_share=0.24] [-0.40, 0.58] | failed |
| REACH4 | each player able to join raises his side's odds | per player, attackers [metric:engagement_reach/confirm#REACH4.coef_att_per_player=0.032] [-0.001, 0.069]; defenders [metric:engagement_reach/confirm#REACH4.coef_def_per_player=-0.141] [-0.194, -0.091] (label: attacking duelist wins) | failed for attackers, held for defenders |
| REACH5 | plant reach gain >= 0.01 nats per plant; more defenders reaching a spike sightline help them | [metric:engagement_reach/confirm#REACH5.improvement_nats=0.00598] [0.00076, 0.01088] over [metric:engagement_reach/confirm#REACH5.planted_rounds=1495] plants; defenders per player [metric:engagement_reach/confirm#REACH5.coef_def_reach_per_player=-0.157] [-0.325, -0.003] (development sign opposite, [metric:engagement_reach/dev#REACH5.coef_def_reach_per_player=0.1585]) | failed the bar; direction held |
| REACH6 | teammates able to trade beat nearest distance on trades | [metric:engagement_reach/confirm#REACH6.able_minus_distance_nats=0.0057] [-0.0007, 0.0120] over [metric:engagement_reach/confirm#REACH6.deaths=15448] deaths (development [metric:engagement_reach/dev#REACH6.able_minus_distance_nats=0.0107]) | failed |

Reach read on sightlines beats distance on fights, but it moves fight
outcomes by about a thousandth of a nat. Reach matters most for trades: the
able-to-trade count gains
[metric:engagement_reach/confirm#REACH6.able_improvement_over_z_nats=0.04288]
nats over alive terms alone and distance
[metric:engagement_reach/confirm#REACH6.distance_improvement_over_z_nats=0.03718];
the two do not separate.

**Coaching readout** (confirmation; each fight read from both duelists'
sides; outnumbered means fewer able to join, walk <= 5 m, than the enemy;
intervals resample matches):

| Measure | Player | Lobby peers | Player minus peers |
|---|---|---|---|
| Reach balance (own swing + trade minus enemy's) | [metric:engagement_reach/confirm#coach.player.reach_balance=-0.073] | [metric:engagement_reach/confirm#coach.peers.reach_balance=0.008] | [metric:engagement_reach/confirm#coach.player_minus_peers.reach_balance=-0.081] [-0.166, 0.002] |
| Deaths taken outnumbered | [metric:engagement_reach/confirm#coach.player.share_deaths_outnumbered=0.295] | [metric:engagement_reach/confirm#coach.peers.share_deaths_outnumbered=0.277] | [metric:engagement_reach/confirm#coach.player_minus_peers.share_deaths_outnumbered=0.019] [-0.006, 0.043] |
| Deaths a teammate could trade, untraded | [metric:engagement_reach/confirm#coach.player.share_deaths_tradeable_untraded=0.220] | [metric:engagement_reach/confirm#coach.peers.share_deaths_tradeable_untraded=0.249] | [metric:engagement_reach/confirm#coach.player_minus_peers.share_deaths_tradeable_untraded=-0.029] [-0.050, -0.007] |
| WP cost per fight, outnumbered fights priced | [metric:engagement_reach/confirm#coach.player.wp_cost_per_fight=0.0035] | [metric:engagement_reach/confirm#coach.peers.wp_cost_per_fight=0.0031] | [metric:engagement_reach/confirm#coach.player_minus_peers.wp_cost_per_fight=0.0005] [0.0001, 0.0009] |

- An outnumbered fight's cost is the held-out reach model's change in the
  duelist's win chance, had his side matched the enemy's counts, times dV,
  the fight's swing in round win probability under winprob_reference's B1
  model. The player's outnumbered fights cost
  [metric:engagement_reach/confirm#coach.player.wp_cost_per_outnumbered_fight=0.013]
  each. The model sets this cost, so it inherits REACH1's small effect.
- The player's team: reach balance
  [metric:engagement_reach/confirm#coach.team.reach_balance=-0.022], deaths
  outnumbered [metric:engagement_reach/confirm#coach.team.share_deaths_outnumbered=0.281],
  cost per fight [metric:engagement_reach/confirm#coach.team.wp_cost_per_fight=0.0032];
  none separates from the opponents
  ([metric:engagement_reach/confirm#coach.team_minus_opponents.wp_cost_per_fight=0.0002]
  [-0.0001, 0.0005]).
- Side dominates. On defence the player's reach balance is
  [metric:engagement_reach/confirm#coach.player.defence.reach_balance=-0.546]
  and [metric:engagement_reach/confirm#coach.player.defence.share_deaths_outnumbered=0.369]
  of his deaths come outnumbered; on attack
  [metric:engagement_reach/confirm#coach.player.attack.reach_balance=0.398]
  and [metric:engagement_reach/confirm#coach.player.attack.share_deaths_outnumbered=0.220].
  Post hoc, against peers on the same side, the player's defence balance is
  lower by [metric:engagement_reach/confirm#coach.post_hoc.player_minus_peers.defence.reach_balance=-0.122]
  [-0.241, -0.011] and costs
  [metric:engagement_reach/confirm#coach.post_hoc.player_minus_peers.defence.wp_cost_per_fight=0.0009]
  [0.0002, 0.0016] more per fight; attack does not separate. Per-map lines
  (maps with at least 20 of the player's deaths) are in the store's results
  file, `analysis/engagement-reach-20261004/score_confirm.json`.

**Real-time fidelity.**

- Own team only: the player's team's counts keep a quarter of the gain
  (REACH3), [metric:engagement_reach/confirm#REACH3.own_improvement_nats=0.0003]
  nats with an interval spanning 0. Most of the small fight signal needs
  the enemy's other players, whom reticle sees only when spotted.
- Region precision (each own-team player at his callout region's
  representative cell): swing counts agree with exact positions at
  [metric:engagement_reach/confirm#region.own_swing_equal_share=0.772] of
  fights and trade counts at
  [metric:engagement_reach/confirm#region.own_trade_equal_share=0.786]; the
  own-team model loses
  [metric:engagement_reach/confirm#region.own_region_minus_own_exact_nats=-0.00028]
  nats [-0.00074, 0.00022], nothing measurable, though it has little to
  lose.
- Stored allies (development; stored `round_entity` ally and self icons at
  fight instants, frames within 250 ms): placed at
  [metric:engagement_reach/fidelity#coverage=0.9119] of fights. The own
  team's swing count matches Riot's at
  [metric:engagement_reach/fidelity#swing_equal_share=0.7341] (within one
  [metric:engagement_reach/fidelity#swing_within_one_share=0.9594], kappa
  [metric:engagement_reach/fidelity#swing_kappa=0.488]); trade at
  [metric:engagement_reach/fidelity#trade_equal_share=0.7041] (kappa
  [metric:engagement_reach/fidelity#trade_kappa=0.5]). Reticle counts fewer
  ([metric:engagement_reach/fidelity#trade_mean_diff=-0.2752] trade players
  a fight), and its icon count equals Riot's living teammates at only
  [metric:engagement_reach/fidelity#own_count_equal_share=0.5546] of
  instants.

**Not done.** Weapons and utility reach (per ability) stay out. This
confirmation read the 3D map on Ascent and Split only. 3D tables now exist
for all 13 maps of the history, and `sightlines.load` picks 3D on each
([SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md), "Every map in the
player's history"). The confirmation set is spent, so no hypothesis was
rerun on the six new maps; the matches the player records from now on are
the next confirmation set. Eye height, crouch height, walkable slope and
jump height are the probe's placeholders, and doors, wallbangs and one-way
drops are not modelled. No propensity guard gates the coaching cost; the
confirmation set is one player's lobbies, so the peers are his matchmaking
band, not a rank band.
