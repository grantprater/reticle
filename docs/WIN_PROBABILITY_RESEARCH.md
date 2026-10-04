# Win probability and coaching: research and roadmap

Date: 2026-10-04. Status: research findings and a proposed roadmap; nothing
here is implemented. Rules stay in [AGENTS.md](../AGENTS.md); commands stay in
[WORKING_MAP.md](WORKING_MAP.md). The economy and forecast design this builds
on is [ECONOMY_AND_PREDICTION_DESIGN.md](ECONOMY_AND_PREDICTION_DESIGN.md).

Eight research lenses, a completeness critic, four follow-up studies and an
adversarial verifier produced this document. Each external claim carries its
URL and retrieval date. **Verified** means the verifier or a lens read the
primary text or reran the number; **unverified** means it rests on a search
summary, a secondary source or one scratch run. Internal numbers cite their
run with a `metric:` token where the store records one. The
`winprob_reference` tokens name fields with dots (`M1_alive.nats`), which the
QUOTED pattern cannot parse, so doctor does not check them; they are
provenance pointers into `notes/metrics.jsonl`, recorded 2026-10-04T14:43:49
by `prototypes/winprob_reference.py` on branch `winprob-reference-20261004`
(commit 45a8699, pushed, not merged).

## Conclusions first

1. **Riot's rules decide what "real time" means.** For the player's own
   matches no conclusion may reach him before the match ends. The binding
   deadline is a report soon after match end, not a 66.7 ms frame. A
   per-frame deadline exists only for analysing matches he watches.
2. **Alive counts carry most of round win probability; team loadout is the
   only other input with a resolved gain.** Positions, clock, side and map add
   nothing resolvable at 454 rounds. Reticle's observed state costs about
   0.003 nats against Riot's exact state.
3. **Economy is the largest gap**, and its rules are known: Riot's ledgers
   reproduce `economy.EconomyRules` in 815 of 816 team-rounds. Two stored facts
   are wrong: the plant reward is 300, not 200, and overtime starts at 5,000,
   not 800.
4. **One reader holds most of the over-investment.** `ally_icon` reads every
   ally at 15 Hz and costs about 1x real time on one core; `team_vision` fits
   the same poses a second time. Neither serves the win-probability question
   at that rate.
5. **The smallest end-to-end experiment is ready**: a round-state filter over
   stored events, scored against Riot's winners, needs no decode and no new
   reader.

## 1. The goal, stated precisely

The end goal is a calibrated estimate, at each moment of a round, of
P(this side wins the round | everything observable so far), and coaching that
uses the changes in that estimate to pick moments worth review. Reticle is the
observation layer; the estimator consumes emitted events only.

Three products share the estimator and differ in deadline and in what is
observable:

| Product | Whose matches | Deadline | Observable | Policy |
|---|---|---|---|---|
| **Post-game** | the player's own | report within minutes of match end | the player's POV: own team, enemies only when seen, own HUD; whole-match lookahead allowed | endorsed ("analyze and reflect later") |
| **Spectator / VOD** | others' matches, pro VODs, the player's Replays | none for VODs; a 15 Hz frame stream for live spectating | observer HUD: all ten minimap icons, side-coloured; Replays show every enemy with no fog | no in-match rule applies to a non-participant; stream sniping is barred |
| **Live in-match** | the player's own, shown during play | per frame | the player's POV only, causal | barred (section 2) |

Two estimators follow. The **POV estimator** conditions only on what the
capture showed up to time t and marginalises hidden state (enemy loadout,
unseen positions). The **omniscient estimator** conditions on Riot's full
match record and serves post-match review and training. Section 2 of the
economy design already separates them; keep them separate, and never let the
omniscient posterior re-enter adjudication.

## 2. What Riot's policy allows live, and what follows

### What the texts say (all verified from raw HTML, 2026-10-04)

- VALORANT developer policy, https://developer.riotgames.com/docs/valorant
  (undated; its mirror is dated 2025-03-07). Unapproved: "In-game apps and
  overlays that include any real-time data that would improve a player's
  performance immediately by altering player behavior (i.e. 'go here now'),
  vs altering it upon reflection, learning and coaching the player game over
  game." Also unapproved: static overlays that block the map, scouting, and
  "Apps that are not public and are designed for personal use only".
  Approved: "Training tools that allow players to view their own match
  histories and aggregate stats." "Personal Key Applications are currently
  not supported." "Products cannot identify or analyze players who are
  deliberately hidden by the game." MMR or ELO calculators are barred.
- Third Party Applications article,
  https://support.riotgames.com/en-us/valorant/account/third-party-applications
  (updated 2025-02-10). "No software should compromise game integrity or
  negatively impact the in-game player experience, from the moment you press
  'Play' until you log off." Barred as a measurable advantage: "Drawing
  conclusions for you during gameplay (ie we want to see you play the game
  first, then analyze and reflect later!)" and "Altering your field of
  intelligence (zoomhacks or global ult alerts)". Penalty: "continuing to use
  it may still result in the loss of your account."
- General policy, https://developer.riotgames.com/policies/general (updated
  2025-05-29): "Products should use supported services from Riot Games for
  data ingestion"; "Products cannot create an unfair advantage for players".
- Overwolf, https://dev.overwolf.com/ow-native/guides/game-compliance/riot-games
  (undated): "Spike timers are not allowed to be shown during a live match";
  private apps are no longer accepted. That the rule originates with Riot is
  Overwolf's statement.
- Terms of Service, https://www.riotgames.com/en/terms-of-service (modified
  2024-12-01): §7.1 bars unauthorised programs that intercept, emulate or read
  memory, access to non-public areas, circumventing technological measures and
  stream sniping; §3 licenses "individual, non-commercial, entertainment
  purposes only" and bars reverse engineering and decompiling.
- Vanguard, https://www.riotgames.com/en/DevRel/vanguard-faq (2024-04-01):
  "There is absolutely no allow list for Vanguard." No Riot text addresses a
  third-party process that captures the screen or audio.

### What follows for the design

- **Nothing the player sees may come before match end** in his own games:
  win probability, ult or cooldown alerts (the ult-line witness is a "global
  ult alert" if shown live), spike countdowns, enemy-position estimates.
- **No per-frame deadline binds the post-game product.** Adjudicators may
  keep whole-match and fixed-lag smoothing. Causal, provisional-then-revised
  adjudication has a consumer only in live spectating.
- **Silent concurrent analysis is unnamed, not cleared.** The article's
  first sentence covers any software that harms the in-game experience from
  Play to log-off, so processing beside the game must first prove it costs no
  frame time (the PresentMon plan in section 4). Until then the default is:
  write ROI caches during the match, read them afterwards.
- **Coaching output must not resemble MMR**, must not profile opponents across
  matches for use before a match, and must not analyse players who hid their
  names. Reticle names agents, not accounts; keep it so.
- **Two current practices carry Terms of Service exposure** (fact verified;
  the legal reading is not made here): match records come from the client's
  undocumented PD endpoints with the game's build string in the
  client-version header, and `game-extract` opens the paks with AES keys and
  exports script bytecode. The player allowed extraction while the game is
  closed. A distributed product could rely on neither; the official route
  (VAL-MATCH-V1, same fields: player locations, `viewRadians`, economy) needs
  a public, registered, RSO opt-in product with a production key.

## 3. State inventory

"WP value" comes from the recorded reference fit (section 5) and the
literature. Live latency means time from the game event to a provisional
reading; no variable has a measured live latency today.

| Variable | Owner / source | Accuracy | Coverage | Live latency | WP value | Status | To close |
|---|---|---|---|---|---|---|---|
| Alive counts per side | `roster` (alive-count, 2 Hz); `adjudication.death` | deaths recall [metric:riot_truth/deaths#recall=0.9955], precision [metric:riot_truth/deaths#precision=0.9979]; side right [metric:riot_truth/deaths#side_right=3270] of 3277 | roster non-null 0.954 on a06f04a0059f; observed alive agrees with Riot on both sides at 93.3% of grid instants | 2 Hz sample plus entry read; per-round adjudication is batch | first-order | available | provisional count at first killfeed view, only for live spectating |
| Spike planted, plant time | `rounds` + `plant_graphic` | [metric:riot_truth/rounds#plant_both=251] both, [metric:riot_truth/rounds#plant_riot_only=27] Riot only, of which [metric:riot_truth/rounds#plant_riot_only_post_decision=18] after the decision; dt median [metric:riot_truth/rounds#plant_dt_ms_median=-103.0] ms | per frame | sample-limited | flag second-order; clock beyond the flag none resolved | available | post-round plants for the economy ledger only |
| Round winner, score, side, map | `rounds`, `round_outcome`, `rounds.infer_player_side`, manifest | winner [metric:riot_truth/rounds#winner_right=439] of [metric:riot_truth/rounds#riot_rounds=439] | all rounds | round end (next Tab strip for defuse and detonation) | labels; side and map add nothing resolved | available | none |
| Round clock | HUD OCR, `gametime` | within 1 s on 97.1% of read instants | 0.477 of a06f04a0059f HUD rows | 2 Hz | none resolved | available, over-read | derive game time from `gametime` and round bounds instead |
| Team loadout / credits | `economy.py` (pure ledger, `reticle economy FACTS.json` only); scoreboard credits at 2 Hz while Tab is open | rules reproduce Riot in 815 of 816 team-rounds; scoreboard ally credits equal Riot `remaining`, enemy credits equal round-start wallet in 85-90% of reads (two sessions, unrecorded) | allies when Tab opens; enemies hidden in play [domain:rounds/scoreboard-credit-snapshot] | buy phase | the only resolved gain beyond alive (grid +0.0172 nats) | missing as a stream | team-level ledger from stored events; enemy loadout as a bounded latent |
| Ult points / ults ready | `adjudication.ult_cast` (audio) for casts; tray for self pips | casts recall [metric:riot_truth/ult#recall=0.9028], precision [metric:riot_truth/ult#precision=0.9579]; held [metric:riot_truth/ult/held#recall=0.9526] | all ten players' casts; points of others unobserved | one voice line | unmeasured here; weak in VCT round-start models (unverified) | partial | ult-points ledger from deaths, plants, defuses and casts |
| Self HP / shield / ammo | `ocr.read_bottom_hud` (2 Hz) | unscored | hp non-null 0.851 on a06f04a0059f, but 18-36% of non-null hp rows (the fixed three sessions) fall after the player's death and read the spectated teammate | 2 Hz; misses most fights (14 of 46 died rounds show full HP at the last read) | second-order in CS; unmeasured here | partial, contaminated | death/spectate gate, then a per-round Riot damage scorer |
| Ally HP | none; top-bar pill measured only as alive/dead | — | — | — | second-order in CS | missing | calibrate the pill against own HP (one crop pair suggests it tracks) |
| Enemy HP | unobservable live | — | — | — | caps reachable accuracy | missing by design | none |
| Ally positions | `ally_icon`, `round_entity` (15 Hz) | matched [metric:riot_truth/minimap/all#matched=8366] of [metric:riot_truth/minimap/all#riot_allies=10445], phantoms [metric:riot_truth/minimap/all#phantom=362], missed in stacks [metric:riot_truth/minimap/all#missed_stacked=1002]; error median [metric:riot_truth/minimap/all#pos_err_px_median=1.3] px, p95 [metric:riot_truth/minimap/all#pos_err_px_p95=3.8] px; facing within 30° [metric:riot_truth/minimap/all#facing_within_30=0.878] | every living ally placed at 49-51% of grid instants | 15 Hz | none resolved at 1 Hz | available, over-read | zone and distance-to-site projection on baked geometry |
| Enemy positions | `enemy_track`, inside team vision only | 351 of 356 stored matched | only when seen | 15 Hz | none resolved | partial by design | a decaying regional belief, if a question needs it |
| Utility in play, vision | `adjudication.smokes`, `team_vision`, last-known marks | no external truth | allied smokes only [domain:abilities/enemy-smokes-not-on-minimap] | 15 Hz | not a WP input | partial | hold to a value-of-information test |
| Player skill | Riot `competitiveTier` (post-match) | — | lobbies mostly tiers 9-13 | none live | rank difference adds nothing at round start | missing live | none needed for round WP |
| Defuse progress | none | — | — | — | small (87 defuses in 467 rounds) | missing | observer HUD shows it; own POV rarely |

## 4. Real-time feasibility and blockers

### Cost today

Every per-frame cost below ran with 0.37-0.90 of the other logical CPUs busy,
so each is an upper bound; no uncontended run exists.

- `ally_icon` dominates. On a06f04a0059f (465 px widget) its feed took
  [metric:scan_usage/ally_icon/cache/serial/cv12@a06f04a0059f~e08ed4f7#feed_s_ally_icon=2241.754]
  s over 20,778 calls, about 108 ms per frame against 66.7 ms at 15 Hz;
  `stack_fit` is 51% of it and pose 27%. On 3694746e4e54 (331 px) it took
  [metric:scan_usage/ally_icon/cache/serial/cv12@3694746e4e54~7c69e7c3#feed_s_ally_icon=696.066]
  s, about 50 ms per frame. Over the 21 matches it is 62% of all reader feed
  time (one lens's sum, unrecorded). `stack_fit` searches only gated frames
  (3,820 of 20,778 on a06f04a0059f) but costs about 300 ms per searched
  frame.
- `team_vision` refits every ally and self pose with a full grid and no prior
  (`team_vision.py` passes no `frame_idx`), after `ally_icon` already stored
  those poses. Its pose and ring steps are about 972 s of a 1,743 s vision pass
  on a06f04a0059f. Verified in code; the seconds come from one contended run.
- HUD, killfeed, ability and audio readers together cost under 0.5 core-s per
  second of play. Audio scoring is 2.2 s per session on the GPU.
- Summed serially, every reader costs about 2.1x capture length on
  a06f04a0059f and 1.1x on 3694746e4e54 (one lens's sum, unrecorded).

### Three budgets

| Budget | When it binds | What binds | Verdict |
|---|---|---|---|
| A. Post-match, GPU idle | the player's own matches (the default) | turnaround and corpus-rerun hours | no fidelity cut is forced; remove duplicate work, port `stack_fit` to the GPU |
| B. Concurrent with the game | only if analysis runs during play | spare CPU and GPU beside VALORANT and OBS (NVENC H.264, 1080p60); unmeasured | run nothing heavy live; cache ROIs during play, read after |
| C. Live spectating | analysis of matches the player watches | 66.7 ms per 15 Hz frame with ten icons | needs per-icon variable rate and the GPU |

### GPU (microbenchmark, synthetic arrays, unrecorded)

On the RTX 3070 with cupy, `stack_fit`'s candidate loss math runs about 11x
faster per seed and 40-50x when seeds and windows are batched. A per-icon
port of the teardrop compass step runs *slower* than numpy (one cupy launch
costs about 29 µs). A GPU port pays only when it batches across seeds,
windows, icons and frames, in chunks of about 1M pixels. The venv's OpenCV has
no CUDA; cupy works, and `ult_lines.array_module` is the pattern. Desk
estimate, unverified: porting `stack_fit` halves `ally_icon`; porting the pose
as a batched full grid cuts it 3-4x, and Amdahl caps the gain near 4x.

### Blockers

1. The use case is undecided (section 8, question 1); it picks the budget.
2. Budget B is unmeasured. Plan, needing the player: five 300 s conditions in
   the Range (game alone; with OBS; plus one Below Normal reader replay; plus
   four; plus a looping cupy benchmark), logged with PresentMon 2.3.1,
   `Get-Counter` processor and GPU-engine counters, `nvidia-smi`, and the OBS
   log. Accept when p99 frame time and OBS drops stay within the player's
   tolerance. Whether PresentMon runs beside Vanguard is unverified.
3. No live frame source exists. Windows.Graphics.Capture yields BGRA 8-bit
   GPU surfaces with QPC timestamps (FP16 under HDR;
   https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture,
   retrieved 2026-10-04, verified); a live source should copy back only the
   reader ROIs, behind the `open_capture` seam.
4. No reader has seen 4:4:4 frames. The 60.6 s UTVideo `.avi` proxy is in no
   manifest (5.7 GB per minute rules it out as a routine format). NVENC HEVC
   4:4:4 on Ampere is the practical full-chroma recording (NVIDIA SDK notes,
   via search summary; unverified).
5. Adjudicators declare no evidence lag. Name clusters, `assign_side`, the
   lineup verdict, the ping Grouper and ally decisions run at match end; that
   suits budget A and blocks only budget C.

### A new source: in-client Replays

Since Patch 11.06 (https://playvalorant.com/en-us/news/dev/replays-everything-you-need-to-know,
2025-09-16, verified) the client keeps Replays of the player's own games on
the current patch, with all ten first-person views, speeds up to 8x, and a
minimap that cannot hide enemies. `docs/EXTERNAL_GROUND_TRUTH.md` says replays
"cannot be exported"; that line is stale, because 15 `.vrf` files sit in
`%LOCALAPPDATA%\VALORANT\Saved\Demos`. A replay capture would give fog-free
enemy positions for post-game coaching without inference. It needs the game
client open and expires at the next patch. OP.GG already sells replay-based
analysis (https://op.gg/valorant/replay, retrieved 2026-10-04; features as
advertised, untested).

## 5. Model design

### Structure

A **round-state filter** carries P(z | evidence up to t) with
z = (attackers alive, defenders alive, phase, t, enemy loadout class). Phase
is pre-plant or post-plant. Enemy loadout is latent, with a prior conditioned
on round type and round history and trained on Riot's `playerEconomies`. An
**outcome model** maps z to P(attackers win). The forecast marginalises:
p = Σ_z P(win | z) P(z | H), which the economy design already prescribes;
plugging in a point estimate of the enemy buy would make the forecast
overconfident.

The outcome model is a ridge logistic with few terms: alive counts (as
indicators or a monotone form), team loadout difference and a plant flag. The
recorded fit sets these choices (454 rounds; leave one match out; each round
weighted once; match-cluster bootstrap):

| Test | Result | Verdict |
|---|---|---|
| Alive counts alone | 0.4352 nats at kills [metric:winprob_reference/riot_K#M1_alive.nats=0.43523]; 0.5028 on a 1 s grid [metric:winprob_reference/riot_G#M1_alive.nats=0.50276] | carries most of the signal |
| + team loadout difference | grid +0.0172 nats [0.0019, 0.0337], better in 16 of 22 matches [metric:winprob_reference/riot_G#step:M1_alive->M2_alive_load.nats=0.01719]; kills +0.0084, unresolved | keep; the only resolved gain |
| + side; + map × side | side ±0.000; map × side −0.0032 at kills [metric:winprob_reference/riot_K#step:M3_alive_load_side->M4_alive_load_mapside.nats=-0.00315] | drop; overfits at this size |
| + plant flag | grid +0.0026 [0.0003, 0.0050] [metric:winprob_reference/riot_G#step:M3_alive_load_side->B1_plant_flag.nats=0.00264] | keep the flag |
| + phase-switching post-plant clock (45 s fuse, 7 s defuse) | −0.0032 [−0.0056, −0.0009] [metric:winprob_reference/riot_G#step:B1_plant_flag->B3_phase_clock.nats=-0.0032]; last 10 s of fuse +0.0078, unresolved (50 rounds) | drop the clock; revisit the endgame with more rounds |
| Gambler's ruin a/(a+d) | 0.094 nats worse at kills [metric:winprob_reference/riot_K#step:M1_alive->B0_gamblers_ruin.nats=-0.09351] | fit, do not assume |
| Riot positions at kills | −0.0004 [metric:winprob_reference/positions_K_riot#M3_alive_load_side.step.nats=-0.0004] | none resolved |
| Reticle ally positions, 1 s grid | −0.0010 window [metric:winprob_reference/positions_G_ally/window#step.nats=-0.00095] on [metric:winprob_reference/positions_G_ally/window#full_states=12937] states; +0.0016 frame (post hoc); isolated-ally ("lurker") subset +0.0058 [−0.0048, 0.0154] | none resolved; the lurker sign leans positive |
| Alive-count lag | 0.5 s costs 0.0071 bits per state [metric:winprob_reference/alive_lag#B3_phase_clock.lag_0.5s.bits=0.00715]; 2 s costs about 0.028 | 2 Hz suffices |
| Reticle's observed state against Riot's | +0.0027 nats [metric:winprob_reference/observed_cost#O_alive_side_flag_clock.cost.nats=0.00265] on [metric:winprob_reference/observed_cost#share_of_captured=0.7458] of captured instants | readers are good enough; the clock requirement costs the coverage |

The literature agrees in kind (all verified unless marked): Xenopoulos,
Doraiswamy and Silva, "Valuing Player Actions in CS:GO"
(https://arxiv.org/abs/2011.01324, 2020) rank equipment value first, with
distance to site minor; in "Graph Neural Networks to Predict Sports Outcomes"
(https://arxiv.org/abs/2207.14124, 2022) per-player positions cut log loss
only from 0.4351 to 0.4276; ESTA (https://arxiv.org/abs/2209.09861, 2022)
found set models over position and view did not beat team-level vectors.
HLTV Rating 3.0 (https://www.hltv.org/news/42485/introducing-rating-30,
2025-08-20) and Leetify
(https://leetify.com/blog/leetify-rating-explained, 2024-11-25) value kills
from alive counts, economy tiers and the bomb, with no positions. The one
VALORANT minimap-video paper (https://arxiv.org/html/2510.17199v1,
2025-10-20) reports accuracy only, validates on 100 rounds, and reaches 56% in
a round's first 24 s; it cannot serve as a target.

### Feeding the filter

- **Multiply likelihoods, not posteriors.** `ability_audio` stores `p_right`
  calibrated under its dev base rate; killfeed portraits carry posteriors
  under a uniform prior over admitted candidates. Divide out the calibration
  prior: LR = [q/(1−q)] / [π/(1−π)]. Each claim enters once, following its
  `depends_on` and `rests_on`.
- **Refusals stay distinguishable.** A refusal whose reason depends on the
  state (a pairwise tie, a stall) enters as a likelihood; any other refusal
  counts as missing at random, and the event keeps its reason.
- **Use availability time.** Stored times are observation times; a causal
  replay also needs the time the evidence could first be read. This matters
  only for live spectating.
- **Rounds start with the roster present, not five.** 043bafca271a round 14
  and e37fdeca944f round 8 start four against five; the roster reads 4 in
  both. Surrendered rounds are awarded, not played; drop them from labels.

### Calibration and validation

- Proper scores only: log loss in nats and bits, Brier; never accuracy.
- Leave one match out; bootstrap by match; report intervals. Correlated states
  shrink the effective sample (Brill, Yurko and Wyner,
  https://arxiv.org/html/2406.16171v5, 2025-08-20, verified).
- Five-bin reliability, with each bin's standard error stated (about 0.05 at
  90 rounds a bin). Recalibrate with a logistic (Platt) map, not isotonic
  regression, at this size.
- Score on outcome-independent clock landmarks as well as at kills, since kill
  instants over-sample fights.
- Round-start priors (loadout, previous round) enter with a weight that decays
  through the round, as nflfastR does for the pre-game spread
  (https://www.opensourcefootball.com/posts/2020-09-28-nflfastr-ep-wp-and-cp-models/,
  verified). A prior is evidence weighed once.

### Data

- **What exists.** The store holds 22 Riot match records: 467 rounds, 458
  played (9 surrendered), 3,459 kills, 7 maps, game versions 13.04-13.06, 20
  competitive and two unrated matches (0f08b3dc3777 and b3b9defb6fd7). The
  scorer's 21 matches and 439 rounds exclude 0f08b3dc3777.
  `EXTERNAL_GROUND_TRUTH.md`'s "3,532 kills" does not reproduce. Every round
  carries all ten players' economy; every kill carries every living player's
  position and view angle. The records lack HP, ult points, per-round ability
  casts and the spike carrier.
- **Capacity.** By Riley et al. (BMJ 2020) arithmetic, 458 rounds support an
  in-round model of about 15 parameters and a round-start model of about 3.
  Per-map, per-side or per-buy models and ±5 pp calibration need roughly
  2,000-4,000 rounds (one lens's calculation, unverified in detail).
- **More data.** The three probed accounts' histories listed 18, 47 and 33
  matches, so up to about 76 more records may be reachable, with unknown
  retention. They need no capture and would roughly quadruple the rounds
  behind every unresolved verdict. The only route is the PD endpoint
  (section 2), so the player decides.
- **Not usable.** The official API is closed to a personal tool; GRID's VCT
  data is commercial only; VLR has no kill timelines; HenrikDev's API is
  unofficial. Pro data may enter at most as a weak prior declared `rests_on`.

### Priors from the economy

Riot's ledgers fix the rules (one follow-up's scratch study, reproduced with
`EconomyTracker` unmodified; unrecorded):

| Rule | Riot | `EconomyRules` | Domain fact |
|---|---|---|---|
| Plant reward | 300 to each attacker, 0 to defenders; 262 of 262 plant team-rounds, 23 of them post-round | 300 | **200, wrong** [domain:rounds/plant-credits] |
| Overtime bank | 5,000 every overtime round; 16 of 16 team-rounds (patch 5.05) | **800 by default, wrong** | none |
| Pistol bank | 800; 84 of 84 team-rounds | 800 | none |
| Kill reward | 200 per enemy kill, post-decision kills paid; team and spike kills unpaid | 200 | none |
| Loss ladder | 1,900 / 2,400 / 2,900; resets on a win and at halftime | same | none |
| Survival rule | 1,000 for a surviving attacker after a timer loss with no plant, or a surviving defender after a detonation; a spike death is a death (patch 1.11) | same | none |
| Defuse reward | 0 | none | none |
| Cap | 9,000 | 9,000 | none |

The ledger must take `survived` from death events, never the scoreboard's D
column, which omits spike deaths, and must count post-round plants, which
`rounds.spike_planted` excludes by definition (23 of 262 plant rewards).
Enemy loadout is nearly deterministic in pistol and overtime rounds, so the
loadout prior conditions on round type. Per-player buy composition added
nothing over team loadout in one lens's test, so the WP prior needs team-level
purchasing power, not inventories.

## 6. Coaching

### What is actionable

- **Moments worth review.** The few largest win-probability swings of a
  match, each a source-linked review window with alternatives, never a
  verdict. Riot's own League WP is shown "after key plays or post-match"
  (https://lolesports.com/en-US/news/dev-diary-win-probability-powered-by-aws-at-worlds,
  2023-10-09, verified).
- **One priority fix per match**, chosen by threshold. Feedback research
  favours sparse, thresholded, goal-linked feedback (Lee and Carnahan 1990;
  Kleinman et al. 2021, https://pmc.ncbi.nlm.nih.gov/articles/PMC8675904/);
  the evidence is mixed and comes from motor learning and MOBAs.
- **The metrics every product shows**, computable now from stored events:
  trades and traded deaths (3 s and 5 s windows), KAST, opening duels,
  man-advantage conversion, clutches, unused utility at death (the tray at the
  player's death). No module computes any of them.
- **Buy decisions**, from the economy ledger, between matches.

### What reticle uniquely observes

API tools and replays see everything. Reticle sees what the player saw: the
minimap, cones, pings, the killfeed and the audio at each instant. It can judge
a decision against the information the player had: a late rotation after the
minimap showed three enemies at B, or a swing despite heard footsteps. That is
its niche. Aim metrics (crosshair placement, time to damage) need a main-view
enemy detector, which does not exist, and OP.GG already offers them from
replays.

### What coaching must not do

Show anything during the match; rate the player with an MMR-like number;
profile opponents for use before a match. The hand-set weapon-tier duel
logits in `coaching.estimate_duel_win_prob` are unfitted; data put most duels
near 50/50 (Sloan duel paper, Brier 0.228 against 0.25 for a coin flip). Fit
them from Riot records or remove them.

### Acceptance

No standard yet judges whether coaching works. Proposed: a small set of
moments the player labels worth reviewing, against which surfaced moments are
scored, plus his rating of each match report. That set also gives the
fidelity tests a downstream target besides WP.

## 6b. Variable fidelity

The player's principle (2026-10-04): observe only to the degree the question
needs. Each item below spends observation the question does not use.

### What we can stop worrying about, or read less often

- **OVER: `ally_icon` at a uniform 15 Hz.** About 108 ms per frame on
  a06f04a0059f (contended). `docs/ALLY_RATE.md` (2026-09-29) found 5 Hz names
  teammates as well (named share 0.631 against 0.633; labels 40 against 40 of
  57) and recommended 5 Hz; no decision was recorded, and the study predates
  `stack_fit`. Between consecutive frames 44-56% of linked icons move under
  0.5 px; 26% of icon samples move under 2 px in a second. The recorded fit
  finds no resolved WP value in positions. A still lurker behind a wall needs a
  change test, not a 15 Hz pose fit.
- **OVER: the duplicate pose in `team_vision`.** About 972 s of a 1,743 s
  pass re-derives poses `ally_icon` already stored, and two code paths can
  publish different poses for one icon. Waste under every budget.
- **OVER: `stack_fit` re-searching a persistent stack** from scratch on every
  gated frame (about 300 ms per searched frame on a06f04a0059f), with no
  continuation between frames. Stacked teammates holding a site do not move.
- **OVER: compass refinement to 0.05 px and 0.25°.** `pose/refine` costs
  about 11% of `ally_icon` on a06f04a0059f; facing against the player's labels
  errs a median 2.5°, and WP uses regions.
- **OVER: alive-count timing finer than 0.5 s.** It costs 0.0071 bits per
  state at 0.5 s. Do not raise killfeed or roster rates for WP.
- **OVER: reading the clock every frame for WP.** The clock adds nothing
  resolved, and requiring it drops 6,063 of 25,204 captured instants from the
  observed estimator. Use `gametime` and round bounds; read the HUD clock at
  most in the last seconds of a fuse.
- **OVER: the scoreboard at 2 Hz while open.** Enemy credits stay at the
  round-start wallet all round; ally credits change only at buys, plants and
  settlement. One agreeing pair of reads per row per round answers the
  economy question.
- **OVER (mild): killfeed entries read on about 8-10 frames each** (1,755
  entry-frames for 219 entries on a06f04a0059f; an earlier figure of 16
  counted both portraits). Several reads form the per-entry majority; test
  k-of-n on stored rows before cutting.
- **OVER: the bottom HUD at a uniform 2 Hz** through buy phase, death camera
  and spectating, while 14 of 46 died rounds show full HP at the last read
  before death. Read on change outside fights and densely inside them.
- **OVER: per-map side priors, per-player skill priors and exact enemy
  inventories for WP.** Map × side and rank difference hurt or add nothing;
  inventories serve buy coaching only.
- **OVER for WP, not for identity: the last death residuals** (missed
  [metric:riot_truth/deaths#missed=3], false [metric:riot_truth/deaths#false_deaths=7]).
  Killer and weapon refusals change no alive count. A single missed kill
  still corrupts the count for the rest of a round, so keep the death work;
  rank residuals by WP leverage.
- **OVER: post-decision plants for WP** (18 of the 27 Riot-only plants). They
  matter only to the ledger, which the next scoreboard snapshot witnesses.
- **OVER (framing): per-frame latency engineering for the player's own
  matches**, including causal adjudication and PUBSUB's 66.7 ms live target.
  Riot bars in-match conclusions; that work serves only live spectating.

**Not over-investment (checked):** the buy-phase exclusion already exists
(1.6-1.8% of tracked frames); deaths stay worth fixing because alive counts
dominate.

### The proposed fidelity policy

1. **Questions set rates, not readers.** Each consumer question declares the
   variable, precision and rate it needs: round WP needs alive counts at 2 Hz,
   the plant flag, team loadout per round and positions at zone level at most;
   trades need ordered death instants; peeks need 15 Hz in fight windows.
2. **Continue the prior along time.** For each icon, test the prior pose's
   render against the new crop (one correlation); keep the prior while the
   residual stays inside its noise band. Refit on change, surprise or the
   audit cadence.
3. **Raise on opportunity, never on outcome.** Raise the rate when icons
   converge (stack forming), an enemy icon, ping or last-known mark nears an
   ally, the spike phase reaches a site, the player is in a fight (HUD damage,
   combat audio), or a reader is surprised (`no_prior`, gap, low NCC). Lower
   it for still, separated icons, dead players and decided rounds. A kill must
   not trigger the dense reads that later count as coverage.
4. **Store why.** Each dense read records its trigger; a mixed-rate stream
   records its per-frame rate so coverage stays unbiased.
5. **Audit apart.** A fixed-cadence full search, stored apart, measures each
   prior's efficacy; only audit samples refit behaviour priors.
6. **Judge by decision flips.** A cheaper tier passes when WP, trade and
   death-binding verdicts do not flip against the dense run and the Riot
   minimap block stays same or better. `acquisition` and `fidelity` already
   score tiers against reference reads; extend their frozen windows to
   minimap questions.

## 7. Staged roadmap

Each stage names its acceptance command and evidence standard, as
`BACKLOG.md` items do. Compute rules apply throughout: one heavy process,
single-threaded, Below Normal, the fixed handful first, no decode without the
player's go-ahead.

**Stage 0. Decisions and facts.** Ask the section 8 questions. Revise
[domain:rounds/plant-credits] to 300, keeping the player's statement and the
surprise. Add `EconomyRules.overtime_credits = 5000`. Correct
`EXTERNAL_GROUND_TRUTH.md` (kills, two unrated matches, replays).
Acceptance: `reticle doctor` clean; a test drives `EconomyTracker` over the
Riot records. Evidence: 815 of 816 regular, 40 of 40 halftime and 16 of 16
overtime team-rounds balance.

**Stage 1. The smallest end-to-end experiment: a round-state filter on stored
events.** Merge `winprob-reference-20261004`. Build `prototypes/round_filter.py`:
for the 21 captured matches, read stored deaths, rounds, plant and roster
alive counts, run a forward filter over z with likelihoods from the Riot-scored
rates, apply the reference outcome model (alive, side, plant flag; no clock),
and emit p on a 1 s grid. Log predictions in `notes/predictions.jsonl` first:
observed-state log loss within 0.005 nats of the oracle; coverage above 95% of
captured instants once the clock is dropped. Acceptance: one recorded
`metrics.record` run; one number reruns identically. Evidence: log loss in
nats and bits, Brier and five-bin reliability against Riot winners,
match-bootstrap intervals, and coverage.

**Stage 2. Team economy ledger.** Wire `EconomyTracker` to stored deaths,
rounds, plants (post-round included) and `round_outcome`, emitting per-team
credit intervals; fit P(enemy loadout class | round type, history) on Riot
`playerEconomies`. Score scoreboard credits against Riot `remaining` (allies)
and `remaining + spent` (enemies). Acceptance: a scorer part in
`prototypes/riot_ground_truth.py`. Evidence: per-round team credits against
Riot, and the stage 1 filter's log loss with the loadout class marginalised.

**Stage 3. Remove duplicate work.** Make `team_vision` read `ally_icon`'s
stored poses (route through `reticle ownership` first; check the ring-fit
configurations match). Acceptance: `reticle trial`, then a vision rerun on
3694746e4e54, a06f04a0059f and bdfdcf009dba. Evidence: vision masks same or
better; `reticle usage` shows the pose steps gone.

**Stage 4. Variable-rate `ally_icon`.** Rerun the `ALLY_RATE` comparison at
current code with 15, 5 and 3 Hz and a gated arm (5 Hz base, 15 Hz near
stacks, contact or surprise), plus a per-icon change test. Acceptance: crop
cache trials on the fixed handful, then the Riot scorer. Evidence: matched,
phantom and missed-in-stack counts same or better; zero WP, trade and
death-binding flips; record the rate decision.

**Stage 5. Coaching metrics and delivery.** A stored-data owner for trades,
KAST, opening duels, clutches and unused utility at death, with the same
metrics computed from Riot records and disagreements stored; then a match
report of the top-K WP swings as review windows plus one priority fix.
Acceptance: `reticle ownership` entry and a command over the 21 matches.
Evidence: per-metric agreement with Riot; the player's ratings of surfaced
moments.

**Stage 6. POV gate for HUD inputs.** Mark bottom-HUD hp, shield and ammo
after the player's last death as the spectated teammate's (end at kit return
or the next buy phase, not at `t_close`); end `team_vision`'s self track at
death. Then score self HP per round against Riot damage. Acceptance: restamp
on the fixed handful. Evidence: zero player-attributed hp rows after death
(today 1,278 / 452 / 675); survived-round HP falls against Riot damage.

**Stage 7. GPU `stack_fit`.** Port the candidate search to cupy on the
`array_module` pattern, batched across seeds and windows. Acceptance: Riot
minimap block same or better on the fixed handful. Evidence: ms per searched
frame, uncontended.

**Stage 8 (conditional on the player's answers).** Budget-B footprint session;
a Replay probe (current patch, 1x and 4x, `clip_preflight`); an observer-HUD
profile for live spectating; an enemy regional belief; more Riot records.

## 8. Open questions for the player

1. Which "real time" do you mean: (a) your own matches, report ready shortly
   after the match ends; (b) live analysis of matches you watch; (c) both?
   Riot bars in-match conclusions in your own games.
2. Riot's records pay 300 credits to every attacker for a plant, post-round
   plants included (262 of 262 plant rounds); you said 200 on 2026-10-03. May
   we revise the domain fact to 300 and record your statement beside it?
3. May we fetch the uncaptured match records in your three accounts'
   histories (up to about 76) before they age out, given that the PD endpoint
   sits in Terms of Service territory? Whose are the second and third
   accounts, and do their owners agree?
4. Will Reticle stay a personal tool, or ever be shared or sold? That decides
   registration, RSO, asset licensing and whether the PD probe and AES
   extraction may stay.
5. May analysis run while you play, or only after? If during, will you sit
   for a 30-minute PresentMon session, and what frame-time cost is acceptable?
6. Which coaching questions come first: buys, trades and spacing, rotations
   and lurks, post-plant retakes, or peeks? Each sets a different position
   rate.
7. For a still teammate out of contact, is a check about twice a second at
   callout precision enough, with full rate near stacks, movement and fights?
   Does a still teammate holding an angle about to be peeked need more?
8. Will you capture a current-patch Replay so we can test its fog-free
   minimap against your live capture?
9. Does the white pill under each top-bar portrait show health, and does it
   include shield?
10. How should we judge the coaching: your rating of surfaced moments, your
    own review notes, or your stats across matches?
11. When a teammate is AFK, the other four split that player's round reward
    (two cases); do you know the rule?

## 9. Risks

- **Account risk.** Any in-match display (overlay, second screen, phone)
  falls under "loss of your account". Vanguard has no allow list, and a live
  screen reader shares a pixelbot's input stage; how Riot tells them apart is
  unpublished.
- **Policies tighten.** League added an explicit ban on enemy-cooldown
  tracking; Overwolf stopped accepting private apps; the game-specific policy
  index changed 2026-08-21.
- **Small data.** 458 played rounds in 22 matches; gains under about 0.01
  nats sit inside their intervals. Unresolved is not absent: the lurker
  subset and the fuse endgame both lean positive.
- **Biased evidence.** Riot positions exist only at kills, plants and
  defuses, so they over-sample fights. Kill-instant WP fits hide effects
  between kills; the 1 s grid fit addresses this only for allies.
- **Contended timings.** Every per-frame cost ran with 37-90% of other
  logical CPUs busy. Cutting fidelity on these numbers alone may cut the
  wrong thing; one idle rerun fixes it.
- **Stale facts.** The plant-credit fact and the overtime default are wrong;
  the non-ult Riot-truth series predate `riot-truth-0.5.1`; the coaching
  report on disk is `coach-0.1.0` against code at `coach-0.3.0`.
- **Unchecked citations.** The `winprob_reference` fields contain dots, so
  QUOTED cannot parse their tokens; those figures go unchecked until the
  series renames its fields or the pattern widens.
- **Transfer.** CS:GO coefficients and pro VALORANT data may misstate ranked
  play at tiers 9-13; use them at most as weak priors declared `rests_on`.
- **Feedback loops.** A WP or belief posterior that later shapes reader
  priors must declare `rests_on`, and only audit samples may refit it.
- **Contamination.** Up to a third of self-HP rows read a spectated teammate
  today; any HP feature built before the stage 6 gate inherits them.
- **Overconfidence.** An omniscient-trained model fed point estimates of
  hidden enemy loadout will be overconfident unless the filter marginalises.

## What this research did not do

It ran no decode, no uncontended timing and no footprint measurement. It
viewed no observer or Replay frame. It did not run a real GPU port, test
richer positional models, enemy positions on the grid or a time-ordered
holdout. It did not open the Leiden and Aalto theses, the techrxiv VALORANT
loadout paper (HTTP 403; its 60.61% accuracy is unverified) or Riot's page for
the 7 s defuse. The economy, motion, killfeed and HP figures marked unrecorded
come from scratch scripts in a session scratchpad and need a recorded run
before any decision rests on them alone.
