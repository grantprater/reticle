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
  of the next coarse transition (a trade, the next kill, a retake beating the
  fuse); V prices the transition. This is the multiresolution structure of Cervone et al.
  (https://arxiv.org/abs/1408.0777) and the fourth-down recipe of Brill et al.
  (https://arxiv.org/abs/2311.03490).
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
seen and triggered whether or not the player acted:

| Decision | Trigger t_d | Context c (the choice) | Alternatives |
|---|---|---|---|
| Trade spacing | the player's death or first contact, minus 1 s | nearest living teammate's distance, then path distance and line of sight | close to trade range |
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
- `PROJECT_GUIDE.md` L417 lists positioning under mechanics. This design files
  position relative to teammates and cues under decisions and leaves aim and
  peeks under mechanics; the guide line needs that change.

## 2. Estimator

**Value.** V(z), z = (attackers alive, defenders alive, loadout-difference
class, plant flag), from `prototypes/winprob_reference.py` 0.2.0. Loadout is
its one resolved gain
([metric:winprob_reference/riot_G#step:M1_alive->M2_alive_load.nats=0.01719]),
with plant
([metric:winprob_reference/riot_G#step:M3_alive_load_side->B1_plant_flag.nats=0.00264]).
The point-of-view (POV) version marginalises the round filter's posterior over z.

**Transitions.** Bayesian logistic hazards P(o | z, c; θ) for o in: traded
within 5 s, next kill ours, retake before the defuse landmark, next round's
loadout class after a save. Coefficients pool hierarchically:

```
θ_shape  (CS, wide τ_s, declares rests_on)
  -> θ_val   (VALORANT ladder, every match containing the player excluded)
    -> θ_band  (rank band; map and patch as partially pooled effects)
      -> θ_me    (the player's fit-split matches)
```

The between-player spread τ_p, estimated from the ladder sample, sets how far
the player's 300-odd deaths can move him from his band. Fitting is MAP with a
Laplace posterior through statsmodels or scipy, vectorised.

**Decomposition**, for episode e in state z with context c_e:

```
D_e = Σ_o [P(o|z,c_e; θ_band) − P(o|z,c_ref; θ_band)] · ΔV(o,z)   decision
M_e = Σ_o [P(o|z,c_e; θ_me)   − P(o|z,c_e;  θ_band)] · ΔV(o,z)   mechanics
ε_e = ΔV_realised − Σ_o P(o|z,c_e; θ_me) · ΔV(o,z)               luck
```

θ_band leaves the player out (https://arxiv.org/abs/2401.09940), so his skill
cannot leak into the baseline. c_ref is a named alternative or the band's
propensity-weighted typical context in z. Where the best choice depends on aim
(taking a 1v1), D is also shown at θ_me as a sensitivity line. M absorbs
teammates' and opponents' skill too, so it reads "duel results against
expectation", never "aim".

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

**Rule.** Public datasets, the player's Riot match records and replays may fit
the win-probability and coaching models' baselines and priors. They never
feed a reader, a reader's threshold or anything shown during play. Every
match that evaluates a fitted model is held out from its fit, and an estimate
that rests on these sources declares `rests_on`.

**The plan is decided**:
1. the player's three accounts' records, through the fetch kit
   (`docs/MATCH_FETCH_KIT.md`);
2. a limited, rate-respecting HenrikDev sample of ranked ladder matches,
   snowballed from the player's lobbies and stratified by rank, which also
   measures how play changes up the ladder;
3. a space-bounded CS sample to test transference.

A separate task builds the fetcher. The models need from it what follows.

| Source | Holds (verified 2026-10-04) | Size | Rank / patch fit | Terms | Use |
|---|---|---|---|---|---|
| Own accounts, Riot PD records | kills with every living player's location and view, assistants, per-round economy, plant and defuse site, time, location and players' locations, `competitiveTier` | 22 stored; about 76 to fetch | exact | ToS §7.1 exposure on the player's account (`docs/MATCH_FETCH_KIT.md`) | fit the player level; evaluate |
| HenrikDev ladder sample (https://docs.henrikdev.xyz) | v4 match details mirror Riot's schema; its docs list kills with player locations, plant and defuse events, economy and tier per player; field names unconfirmed | capped at 1,000 matches | any band; current patches | a key is required; Basic key 30 requests/min; "big analytic projects" disallowed; "make sure that the user has given his consent" (https://github.com/Henrik-3/unofficial-valorant-api) | fit θ_val and θ_band |
| ESTA (https://github.com/pnxenopoulos/esta) | 1,558 pro CS:GO demos, 2 Hz frames, kills, damage, grenades, plants | 3.9 GB compressed (LAN 1.7 GB) | pro, 2021-22 | CC BY-SA 4.0 | θ_shape; methods |
| CS2 FACEIT demos via the Data API `demo_url` (https://docs.faceit.com/docs/data-api/data/), parsed by awpy (MIT, https://github.com/pnxenopoulos/awpy) | tick positions, kills, damage, grenades, bomb events | bounded below | FACEIT levels 1-10: a CS skill ladder | rate limits undisclosed; demo terms unchecked | θ_shape; CS ladder gradient |
| VLR.gg | round winner, win type, buy class, first kills; no kill timeline or positions | — | pro | forbids scraping and compiling without written permission (https://www.vlr.gg/terms) | not used |
| Kaggle `ryanluong1/valorant-champion-tour-2021-2023-data` | VCT 2021-26 matches, `eco_rounds.csv`, round events; scraped from VLR | 84 MB | pro | MIT as uploaded; VLR's terms still bind its source | player decision; at most a sanity check on the loadout term |
| Own replays (15 `.vrf`) | all ten players at 128 Hz between kills | 15 | exact | — | rotation timing: see decisions |

Riot's VAL-MATCH-V1 refuses personal apps
(https://developer.riotgames.com/docs/valorant); other Kaggle sets are
aggregates.

**What transfers.** Ladder records transfer everything at the right rank. CS
transfers shape only: trade-odds decay with spacing, the WP curve over alive
counts, and how both change with skill. Never map, kit, utility, economy or
time-to-kill values. Pro data transfers the coarse economy shape only.

**What the fetcher must deliver.**
- Fields: per match, `matchId`, map, `gameVersion`, start time, queue, ranked
  flag; per player, account id, team, agent, `competitiveTier`, party; per
  round, winner, result code, plant time, site, location, planter and
  `plantPlayerLocations`, defuse time, location and players, per-player
  `loadoutValue`, spent and remaining; per kill, `gameTime`, `roundTime`,
  killer, victim, assistants, `victimLocation`, `playerLocations` with
  `viewRadians`, finishing damage.
- Normalisation: a versioned normaliser maps HenrikDev records to Riot's keys,
  accepted by a field-by-field diff against the PD record of the same match on
  at least three of the player's own matches.
- Rank bands: Iron–Bronze, Silver–Gold, Platinum–Diamond, Ascendant–Radiant;
  each at least 40 players with 5 ranked matches each, 200 matches per band (a
  planning figure for estimating τ_p, unmeasured). Snowball at most three hops
  from the player's lobbies; a band that does not fill is reported short, never
  widened. Cap: 1,000 matches.
- Patch window: the patches the player's own records span plus the current
  one; patch enters as an effect, never a pool boundary; a patch that changes
  the economy rules is checked against [domain:rounds/credit-ledger-rules].
- Pace: one request every 4 s (half the Basic limit), single-threaded,
  resumable, stopping on any 429. HenrikDev counts each call plus each
  uncached background Riot request, so 1,000 matches is an estimated 2,200
  counted requests, about 2.5 hours.
- Privacy: other players' ids stay in the store only; names are dropped,
  outputs hash ids, and nothing about another player is published.
- CS budget: at most 10 GB on disk; raw demos are deleted once parsed; the
  FACEIT sample is stratified by skill level.

**Splits.** (a) The 21 captured matches with records never enter a production
fit; they evaluate the POV estimator and the card. (b) The player's uncaptured
matches fit θ_me up to a play-order cutoff; the last 20% evaluate it. (c) The
ladder sample splits by player; no match containing the player enters θ_val or
θ_band. (d) CS never evaluates a VALORANT model. Each fitted table stamps its
split manifest's digest, its source digests and its version.

### Player decisions needed

1. **HenrikDev's consent clause.** Its README asks that users consent and bans
   unconsented analytics. Confirm the use with the operator when requesting
   the key, or narrow the sample to consenting players.
2. **Bands, cap and pace.** Confirm the bands, 200 matches per band, the
   1,000-match cap and one request every 4 s.
3. **Replays.** The rule allows fitting on them. Choose whether the 14
   uncaptured replays fit rotation timing or stay evaluation truth, the only
   between-kill truth.
4. **The Kaggle VCT set.** Use it or skip it, given that VLR forbids
   compilation.
5. **CS.** Confirm the 10 GB budget and a FACEIT API key.
6. **PROJECT_GUIDE L417.** Move relative positioning from mechanics to
   decisions.
7. **Lurk and rotation definitions.** The open questions in
   COACHING_ROTATIONS_LURKS.md need answers.
8. **Labels.** Choose whether the player's labels may tune ranking weights, or
   only accept.

## 4. Observations and fidelity

Episodes need state at decision instants only, at 2 Hz. A 0.5 s lag costs
[metric:winprob_reference/alive_lag#B3_phase_clock.lag_0.5s.bits=0.00715]
bits. A lurker sitting behind a wall costs nothing between instants.

| Need | Stream | Accuracy |
|---|---|---|
| Deaths and trades | `death` | [metric:riot_truth/deaths#recall=0.9955] |
| Alive state | round filter | [metric:round_filter/riot_G/clock#cost_nats=0.01536] nats against Riot |
| Plant | rounds | [metric:riot_truth/rounds#plant_both=251] read by both; **no site stored** |
| Teammates at t_d | `round_entity` | [metric:riot_truth/minimap/all#matched=8366] of [metric:riot_truth/minimap/all#riot_allies=10445] at kills; [metric:replay_truth/score#ally_coverage=0.3825] of living ticks |
| Ults, all ten players | `ult_cast` | [metric:riot_truth/ult#recall=0.9028] |
| Loadout | economy ledger | [metric:riot_economy/team_rounds#regular_ok=815] of [metric:riot_economy/team_rounds#regular_n=816]; not wired to events |
| Regions | none | callout cells failed ([metric:coaching_callouts/ascent@a06f04a0059f#boundary_share_7p6px=0.2185] near a boundary); drawn polygons needed |

**Gaps.** Enemy sightings exist on three sessions; assists live on an unmerged
branch; engagements without a kill need self-HP drops.

**Interface.** A future owner emits `decision_episode` events (t_d, z, c,
reference, D, M, ε, intervals, agreement, `rests_on`, the fitted table's
version); `reticle view` reads only those. Episodes may compute during play
within the frame budget; the card renders after the round, never mid-match.

## 5. What the player sees

The numbers below are illustrative, not measured.

- **Trade spacing, round 14, Ascent defence.** "Died at Market 1 s after
  contact; nearest teammate 24 m, no line of sight. Your band trades this
  state 38% of the time; at your spacing, 11%. Decision −0.03 WP [−0.05,
  −0.01], 0.88 agreement. Duel: lost one expected at 47%; within expectation,
  not coached."
- **Rotation, round 9, Haven defence.** "Left C 6.5 s after the killfeed showed
  two allies dead at A. At plant you stood 31 m from A Site. Leaving 3 s
  earlier raises the band's retake estimate by 0.04 [0.00, 0.08], 0.71
  agreement: uncertain."
- **Lurk, round 12, Bind attack.** "Took a 1v2 at A Short 6 s before the B
  execute, 40 m from the nearest teammate. Untraded. Decision −0.04 [−0.09,
  +0.01]: uncertain. Compared with holding until the execute (band propensity
  0.34)."
- **Match card.** The three confident episodes with the largest |D|, each
  beside a same-z control chosen blind to outcome, for the player to label.
  Season lines are shrunk ("lurk spacing −0.4 rounds per match against your
  band [−0.9, +0.1]; your data's weight 0.3"); mechanics get their own line
  ("opening duels expected 49%, realised 51%").

**Guards against the outcome fallacy and selection.** D reads no outcome, so a
won round can carry negative D. Triggers ignore outcomes and keep no-contact
opportunities; controls are stored beside surfaced episodes; comparisons stay
within z and buy class. Team-strength proxies (score, rank gap, party) adjust
but never earn credit. An unsighted enemy is "unknown", never "absent".
Kill-anchored episodes flatter fights that ended in a kill until engagement
episodes exist, and the card says so. Fits update only from completed matches.

## 6. Staged plan

Commands name a planned prototype, `prototypes/decision_value.py`, under the
repository venv.

| Stage | Work | Acceptance command | Evidence standard |
|---|---|---|---|
| S0 | Trade-spacing pilot on the 22 stored records (§7); record the player-level counts | `prototypes\decision_value.py pilot` | Predictions logged before the run; ledger rows `decision_value/pilot`; leave one match out; 101 bootstrap refits by match |
| S1 | Fetch (separate task) | the fetcher's manifest report | Band counts meet §3 or are reported short; patch window; request log at most 15/min; HenrikDev-to-PD diff clean on 3 own matches; ids in the store only |
| S2 | Hierarchical transition and propensity models | `decision_value.py fit` | Held-out log loss on held-out ladder players and on the player's held-out 20% beats the band-free model, with a bootstrap interval; τ with intervals; split digest in deps |
| S3 | CS transference | `decision_value.py transfer` | Learning curve on band data: CS prior against a flat prior at 1-50 matches, with the crossing point reported whichever way it falls; FACEIT-level gradient against band gradient |
| S4 | POV substitution on the 21 captured matches | `decision_value.py pov` | Reticle-feature model within 0.005 nats of the record-feature model; coverage reported |
| S5 | Rotation and lurk episodes | after COACHING_ROTATIONS_LURKS R1-R5 and a plant-site field | Retake model from `plantPlayerLocations` resolves defenders' distance (interval excludes 0) |
| S6 | `decision_episode` owner and card | `reticle view <sid>` | The player labels surfaced episodes against controls; a bar the player sets beforehand |
| S7 | Skill-ladder report | `decision_value.py ladder` | Per-band coefficients with intervals; a monotone trend is claimed only where intervals separate |

## 7. First experiment: trade spacing on the stored records

The 22 stored Riot records, single-threaded, seconds of compute. Leave one
match out, so every evaluated match is held out from the fit that scores it;
production refits on S1 data and keeps the captured matches for evaluation.
For each death, take the nearest living teammate's distance from
`playerLocations` (victim's team only) and whether the death was traded within
5 s (revived victims removed). Fit P(traded | distance, z) with a player
offset, price D and M with ΔV from `winprob_reference`, then substitute
reticle's teammate positions on the 21 captured matches.

**Planned predictions**, to log in `notes/predictions.jsonl` before the run:

- **P1.** The distance slope is negative and its 95% interval excludes 0. The
  nearest quartile's trade rate is at least twice the farthest's, and
  P1 fails below 1.5 times.
- **P2.** Distance improves held-out log loss over z alone by at least 0.01
  nats per death, with a bootstrap interval that excludes 0.
- **P3.** The player's offset interval spans 0. His deaths are about 330, a
  scratch count to be recorded in S0.
- **P4.** Reticle's teammate positions place at least one ally at 70% or more
  of the player's deaths. The model on them sits within 0.005 nats of the
  record-position model.
- **P5.** Per match, mean D and mean M correlate with |r| < 0.3. A stronger
  correlation means the split does not separate decision from mechanics.

If P1 fails while P2 holds, test path distance next. If P4 fails, reader
coverage, not sample size, blocks this behaviour.

## 8. What it cannot do

- Value a policy no one in the band plays (positivity).
- Price information or distraction that leaves no transition, such as a lurker
  holding three defenders' attention.
- Value utility beyond its effect on transitions, or comms at all.
- Give confident verdicts on most single moments.
- Coach teammates' decisions, or predict how opponents adapt to a changed
  policy (https://arxiv.org/abs/1812.05170).
- Claim causes beyond "no unmeasured confounding given (z, c)".
- Judge plant-site choice before reticle stores the site.
- Validate itself on round outcomes; the player's labels are the acceptance
  standard.
