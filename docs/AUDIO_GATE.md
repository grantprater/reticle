# The audio gate

A detector that says, for every moment of a capture, whether anything other
than footsteps, gunfire and ambience sounded, so that the expensive passes
(dense minimap sampling, the ring and line sweeps, the timer-bar read, a
census montage) run only where something happened. The direction is the
player's ([audio bank](AUDIO_ABILITY_BANK.md#audio-as-the-gate-for-the-expensive-passes-2026-09-26)).
The prototype is `prototypes/audio_gate.py`; it emits no events, writes
nothing under `events/` or `labels/`, and `reticle/` does not import it.

## What the earlier prototypes settled

`audio_probe` found that loudness onsets alone do not find casts: marks were
indistinguishable from random-time controls. `audio_events` found that when a
cast does sound, its RMS event sits within one 50 ms bin of the tray drop.
Together they say the gate is a classifier of sound type at a known time
resolution, not an onset detector. `audio_channel` built the front end the
bank uses (64 mel bands, 60 Hz to 16 kHz, 10 ms hop, per-band median
removed) and its stored `ammo_*.npz` is an equip witness, the white fraction
of the ammo glyph [domain:abilities/ammo-hidden-while-non-gun-held], not
gunfire. Gunfire has no witness yet.

## Mined labels, from stored data only

Every label comes from a stored table with its version, never from the video.

- **Own cast.** A tray drop (`events/tray_drop`, `player_cast` true, not
  `suspect`), window 0.3 s before to 1.5 s after. The player's verified subset
  is `labels/tray_object`, 120 casts over 19 sessions.
- **Own gunfire.** The 2 Hz HUD table's magazine count falls between two
  samples while the reserve does not change. A reload or a weapon swap moves
  the reserve too. This is the prototype's rule, checked by prediction P0
  below, not a domain fact until it holds.
- **Known other.** Deaths (`events/death`, victim or killer the player), plants
  and round transitions (`rounds`, `gametime.get_phase`). Neither positive
  nor background; detections there are explained.
- **Buy phase.** Frames `gametime.get_phase` calls `buy_phase`.
- **Background.** Frames in a live round at least 3 s from an own cast, 1 s
  from own gunfire and 2 s from a known other. It contains footsteps,
  ambience, enemy gunfire and, unlabelled, teammates' and enemies'
  abilities. That contamination is the design's main risk and is measured,
  not assumed away: a detection in background is "unexplained", not "false".
- **Movement.** The self track's speed from `l1/minimap` at 15 Hz, an
  analysis column for footsteps, not a training class.

Stalled spans (`reticle.stalls`) are excluded from every count. The player
reports (2026-09-26, correcting an earlier answer) that some match
sessions, none of the ability demos and not most matches, carry podcast
audio: continuous speech for minutes at a time, pulled in from another
application. Agent voice lines are speech too, but last one to three
seconds inside own-cast windows, so speech is not subtracted from the
gate. F4's per-session speech fraction identifies the podcast sessions,
every score is reported with and without them, and F2 is also fitted with
them removed from the training folds (F2c).

## Formulations, scored identically

- **F0, loudness.** Spectral flux and RMS peaks. The control the others must
  beat.
- **F1, the bank as a detector.** The maximum over the bank's references of
  the `corr` score at each frame, the identification score used for
  detection. Runs on the GPU with cupy at a 100 ms step.
- **F2, mined-class classifier.** Per 100 ms frame, the log-mel context
  (mean, max and delta spread per band over 0.5 s, session median removed)
  into a multinomial logistic regression over own cast, gunfire, background
  and buy, balanced, fitted in cupy; the gate score is the cast posterior.
- **F3, background only.** A Gaussian density fitted to gunfire, background
  and buy frames alone; the gate is low density. No cast label is used to
  fit it, so if F3 matches F2 the gate needs no cast labels and finds
  others' abilities too.
- **F4, pretrained tagger.** An AudioSet audio tagger (the player agreed to
  torch in the venv, 2026-09-26) whose classes already include gunshot,
  footsteps and speech; the gate is one minus the background posteriors, and
  its embeddings feed the F2 classifier. Added once the install is verified.

All are fitted leave-one-session-out over the match sessions and scored on
the held-out session.

## Scores

- Recall on the 120 verified casts and on all tray casts: a detection within
  0.5 s before to 1.0 s after the drop.
- Detections per live minute, and unexplained detections per live minute
  after removing those within 1.5 s of an own cast, own gunfire or a known
  other. The curve of recall against unexplained per minute as the threshold
  moves; recall is read at 1, 3 and 10 unexplained per minute.
- Timing: detection onset minus tray drop.
- Tray-blind casts: Run it Back on `6afc32cb46b4` at 43.2 s
  [domain:abilities/phoenix-run-it-back-expiry-flash] and the Regrowth casts
  [domain:abilities/skye-regrowth-no-tray-drop].
- Cross-reference: smoke onsets from `events/smoke` on `a06f04a0059f`, any
  team, against detections; agreement is consistency, not accuracy.
- Transfer: fitted on matches, scored on the re-recorded demos.

Unexplained detections are listed for the player with the capture path,
the timestamp, a spectrogram and a command that plays 3 s from the source;
no audio is copied out of the capture.

## Predictions

Recorded in the store's `notes/predictions.jsonl` under task `audio-gate`
before any run. Outcomes are appended here when the runs finish.

| Id | Prediction | Confidence |
|---|---|---|
| P0 | Own-gunfire frames carry more energy in the 1 to 4 kHz bands than background frames on at least 17 of 19 sessions; the ammo rule finds gunfire. | 0.8 |
| P1 | F0 reaches 80% recall on the verified casts only above 20 unexplained per minute: loudness is no gate. | 0.8 |
| P2 | F2 reaches 70% recall on the verified casts at 3 unexplained per live minute, leave-one-session-out. Falsified below 50%. | 0.5 |
| P3 | F3 reaches 50% recall at 5 unexplained per minute with no cast label in its fit. | 0.4 |
| P4 | The best gate fires at the Run it Back cast and at one of the two Regrowth demo casts. | 0.6 |
| P5 | Median detection onset is within 0.3 s of the tray drop. | 0.6 |
| P6 | On `a06f04a0059f`, half the smoke onsets have a detection within 1.5 s. | 0.4 |
| P7 | The sessions the player says carry background audio are the ones with the highest unexplained rate at fixed recall. | 0.5 |

## Results

Generated by `python prototypes/audio_gate.py report` from the runs recorded in the store's `notes/metrics.jsonl` (`audio-gate-0.1.0`); every figure cites its run. Outputs sit under `<store>/analysis/audio-gate/0.1.0/`.

### What ran

- [metric:audio_gate/labels@all-matches#sessions=20] match sessions, [metric:audio_gate/labels@all-matches#live_minutes=271.5] live minutes (the player alive in a live round), [metric:audio_gate/labels@all-matches#casts=508] own casts, [metric:audio_gate/labels@all-matches#casts_verified=120] of them labelled by the player, and [metric:audio_gate/labels@all-matches#gunfire_windows=2130] own-gunfire windows. The player casts [metric:audio_gate/labels@all-matches#casts_per_live_min=1.871] times per live minute.
- Wall time per formulation, one heavy process, GPU for the fits and the tagger: F0 [metric:audio_gate/fit-F0@all-matches#wall_s=5.2] s, F1 [metric:audio_gate/fit-F1@all-matches#wall_s=7.6] s, F2 [metric:audio_gate/fit-F2@all-matches#wall_s=329.7] s, F3 [metric:audio_gate/fit-F3@all-matches#wall_s=4.8] s, F4 [metric:audio_gate/fit-F4@all-matches#wall_s=875.3] s, F4b [metric:audio_gate/fit-F4b@all-matches#wall_s=1052.8] s, F2c [metric:audio_gate/fit-F2c@all-matches#wall_s=326.8] s; CPU threads [metric:audio_gate/fit-F2@all-matches#threads=4].
- F2's logistic regression per fold: log-loss median [metric:audio_gate/fit-F2@all-matches#loss_median=0.7198], max [metric:audio_gate/fit-F2@all-matches#loss_max=0.7293]; iterations median [metric:audio_gate/fit-F2@all-matches#iterations_median=8245], max [metric:audio_gate/fit-F2@all-matches#iterations_max=10000] of [metric:audio_gate/fit-F2@all-matches#max_iter=10000]. Adam at a fixed step climbs back out of its minimum, so each fold keeps its lowest-loss iterate, found at a median iteration of [metric:audio_gate/fit-F2@all-matches#best_at_median=2584]. A first run capped at 3000 iterations stopped short: on the fold that holds out `9acf02f98283` the loss fell from [metric:audio_gate/fit-check@9acf02f98283#loss_at_3000=0.75506] to [metric:audio_gate/fit-check@9acf02f98283#loss_converged=0.71674] by convergence, and the held-out cast posteriors of the two fits rank-correlate at [metric:audio_gate/fit-check@9acf02f98283#held_out_rank_corr=0.99196].

### Method as fixed

- Front end: `audio_channel`'s, 64 mel bands 60 Hz to 16 kHz, NFFT 2048 at the native 48 kHz, 10 ms hop, stereo averaged, per-band session median removed. PyAV demuxes the audio stream once and places it by pts. A frame is 100 ms: the mean and the max over ten 10 ms rows.
- Own gunfire: two consecutive 2 Hz HUD samples at most 0.75 s apart, both with `bottom_confidence` at or above 0.82 (the reader's threshold) and a read magazine; the magazine falls and the reserve holds, so the shots fall in (t_prev, t_cur]. A reload or a swap moves the reserve and is not fire.
- Live time is `round_live` and `post_plant` from gametime, ended 1 s before the player's first death in the round (`rounds.player_death_times`); stalls are excluded everywhere. Frames after the death stay unlabelled: the tray then shows a spectated teammate's kit [domain:hud/tray-after-player-death], so no drop there is the player's cast.
- Own cast: -0.3 s to +1.5 s around the drop, including the player's labels. Background keeps 3 s from casts and from every tray drop in live time, 1 s from own gunfire, 2 s from known others and 1 s from other deaths. Known others add the barrier drop (gametime `t_live`) and the tray drops the reader refused as forced or co-occurring.
- A detection is explained when its onset lies within 1.5 s of an own cast, else own gunfire, else a known other; only onsets in live time count toward rates.
- Scores are smoothed over 3 frames; frames at or above a threshold merge when closer than 0.3 s. The threshold sweeps 240 quantiles of the pooled live scores; recall and rates pool the held-out sessions. "At 3/min" is the threshold with the highest verified recall at or below 3 unexplained per live minute; "at recall r" is the one with the fewest unexplained at verified recall r or more. Recall falls again at low thresholds, where merged detections swallow casts, so a gate can peak below r (column "at best"). A cast counts when an onset lies -0.5 s to +1.0 s from its drop.
- Duty: the share of live time within 1.5 s of a detection window, the time a pass behind the gate would still run. "Inside a window" counts a cast whose recall window overlaps a detection window, however early it began.
- F0: the larger of the per-session ranks of frame RMS and spectral flux. F1: the bank's cast-phase templates (`audio_bank.refs_from`), 0.6 s patches z-scored against an 8 s local median, the maximum correlation at each 100 ms frame. F2: 192 features per frame (mean, max and first-difference spread per band over 5 centred frames), z-scored with the training fold, a multinomial logistic regression, class-balanced, L2 0.001, Adam on the GPU. F3: one Gaussian over the gunfire, background and buy frames, covariance shrunk 0.1 toward its diagonal, Mahalanobis distance ranked within the held-out session. F4: `MIT/ast-finetuned-audioset-10-10-0.4593` on 1 s windows at a 0.5 s step over a 16 kHz Kaldi filterbank; the gate is 1 minus the summed background posteriors (21 classes named in `AST_BACKGROUND`; Speech is not one). F4b: F2's classifier on F4's 768-d pooled embeddings. F2c: F2 with the podcast sessions left out of every training fold, scoring every session.

### Formulations, leave one session out

Over all [metric:audio_gate/loso@all-matches#sessions=20] sessions ([metric:audio_gate/loso@all-matches#F2_n_verified=120] verified casts, [metric:audio_gate/loso@all-matches#F2_n_all=508] in all, stalled casts excluded). A dash marks a point the gate never reaches. The best gate by verified recall at 3/min is F2.

Recall:

| Gate | Verified recall at 1/min | at 3/min | at 10/min | at best | All casts at 3/min | Verified casts inside a window at 3/min |
|---|---|---|---|---|---|---|
| F0 | [metric:audio_gate/loso@all-matches#F0_recall_verified_at_1=0.042] | [metric:audio_gate/loso@all-matches#F0_recall_verified_at_3=0.158] | [metric:audio_gate/loso@all-matches#F0_recall_verified_at_10=0.717] | [metric:audio_gate/loso@all-matches#F0_recall_verified_max=0.758] | [metric:audio_gate/loso@all-matches#F0_recall_all_at_3=0.185] | [metric:audio_gate/loso@all-matches#F0_covered_verified_at_3=0.192] |
| F1 | [metric:audio_gate/loso@all-matches#F1_recall_verified_at_1=0.042] | [metric:audio_gate/loso@all-matches#F1_recall_verified_at_3=0.117] | [metric:audio_gate/loso@all-matches#F1_recall_verified_at_10=0.317] | [metric:audio_gate/loso@all-matches#F1_recall_verified_max=0.742] | [metric:audio_gate/loso@all-matches#F1_recall_all_at_3=0.104] | [metric:audio_gate/loso@all-matches#F1_covered_verified_at_3=0.167] |
| F2 | [metric:audio_gate/loso@all-matches#F2_recall_verified_at_1=0.308] | [metric:audio_gate/loso@all-matches#F2_recall_verified_at_3=0.483] | [metric:audio_gate/loso@all-matches#F2_recall_verified_at_10=0.625] | [metric:audio_gate/loso@all-matches#F2_recall_verified_max=0.625] | [metric:audio_gate/loso@all-matches#F2_recall_all_at_3=0.581] | [metric:audio_gate/loso@all-matches#F2_covered_verified_at_3=0.592] |
| F3 | [metric:audio_gate/loso@all-matches#F3_recall_verified_at_1=0.017] | [metric:audio_gate/loso@all-matches#F3_recall_verified_at_3=0.05] | [metric:audio_gate/loso@all-matches#F3_recall_verified_at_10=0.317] | [metric:audio_gate/loso@all-matches#F3_recall_verified_max=0.658] | [metric:audio_gate/loso@all-matches#F3_recall_all_at_3=0.057] | [metric:audio_gate/loso@all-matches#F3_covered_verified_at_3=0.083] |
| F4 | [metric:audio_gate/loso@all-matches#F4_recall_verified_at_1=0.042] | [metric:audio_gate/loso@all-matches#F4_recall_verified_at_3=0.083] | [metric:audio_gate/loso@all-matches#F4_recall_verified_at_10=0.467] | [metric:audio_gate/loso@all-matches#F4_recall_verified_max=0.467] | [metric:audio_gate/loso@all-matches#F4_recall_all_at_3=0.108] | [metric:audio_gate/loso@all-matches#F4_covered_verified_at_3=0.133] |
| F4b | [metric:audio_gate/loso@all-matches#F4b_recall_verified_at_1=0.325] | [metric:audio_gate/loso@all-matches#F4b_recall_verified_at_3=0.417] | [metric:audio_gate/loso@all-matches#F4b_recall_verified_at_10=0.417] | [metric:audio_gate/loso@all-matches#F4b_recall_verified_max=0.417] | [metric:audio_gate/loso@all-matches#F4b_recall_all_at_3=0.488] | [metric:audio_gate/loso@all-matches#F4b_covered_verified_at_3=0.575] |
| F2c | [metric:audio_gate/loso@all-matches#F2c_recall_verified_at_1=0.25] | [metric:audio_gate/loso@all-matches#F2c_recall_verified_at_3=0.467] | [metric:audio_gate/loso@all-matches#F2c_recall_verified_at_10=0.633] | [metric:audio_gate/loso@all-matches#F2c_recall_verified_max=0.633] | [metric:audio_gate/loso@all-matches#F2c_recall_all_at_3=0.577] | [metric:audio_gate/loso@all-matches#F2c_covered_verified_at_3=0.558] |

Cost:

| Gate | Unexplained/min at recall 0.5 | at recall 0.7 | Duty at 1/min | at 3/min | at 10/min | at recall 0.7 | Onset minus drop at 3/min, median (s) |
|---|---|---|---|---|---|---|---|
| F0 | [metric:audio_gate/loso@all-matches#F0_unexplained_per_min_at_recall_0_5=7.12] | [metric:audio_gate/loso@all-matches#F0_unexplained_per_min_at_recall_0_7=9.42] | [metric:audio_gate/loso@all-matches#F0_duty_at_1=0.095] | [metric:audio_gate/loso@all-matches#F0_duty_at_3=0.275] | [metric:audio_gate/loso@all-matches#F0_duty_at_10=0.662] | [metric:audio_gate/loso@all-matches#F0_duty_at_recall_0_7=0.647] | [metric:audio_gate/loso@all-matches#F0_onset_median_s=0.1] |
| F1 | [metric:audio_gate/loso@all-matches#F1_unexplained_per_min_at_recall_0_5=17.94] | [metric:audio_gate/loso@all-matches#F1_unexplained_per_min_at_recall_0_7=20.48] | [metric:audio_gate/loso@all-matches#F1_duty_at_1=0.081] | [metric:audio_gate/loso@all-matches#F1_duty_at_3=0.259] | [metric:audio_gate/loso@all-matches#F1_duty_at_10=0.627] | [metric:audio_gate/loso@all-matches#F1_duty_at_recall_0_7=0.977] | [metric:audio_gate/loso@all-matches#F1_onset_median_s=-0.22] |
| F2 | [metric:audio_gate/loso@all-matches#F2_unexplained_per_min_at_recall_0_5=3.31] | - | [metric:audio_gate/loso@all-matches#F2_duty_at_1=0.127] | [metric:audio_gate/loso@all-matches#F2_duty_at_3=0.296] | [metric:audio_gate/loso@all-matches#F2_duty_at_10=0.513] | - | [metric:audio_gate/loso@all-matches#F2_onset_median_s=-0.05] |
| F3 | [metric:audio_gate/loso@all-matches#F3_unexplained_per_min_at_recall_0_5=12.92] | - | [metric:audio_gate/loso@all-matches#F3_duty_at_1=0.045] | [metric:audio_gate/loso@all-matches#F3_duty_at_3=0.186] | [metric:audio_gate/loso@all-matches#F3_duty_at_10=0.605] | - | [metric:audio_gate/loso@all-matches#F3_onset_median_s=0.3] |
| F4 | - | - | [metric:audio_gate/loso@all-matches#F4_duty_at_1=0.074] | [metric:audio_gate/loso@all-matches#F4_duty_at_3=0.229] | [metric:audio_gate/loso@all-matches#F4_duty_at_10=0.783] | - | [metric:audio_gate/loso@all-matches#F4_onset_median_s=0.3] |
| F4b | - | - | [metric:audio_gate/loso@all-matches#F4b_duty_at_1=0.148] | [metric:audio_gate/loso@all-matches#F4b_duty_at_3=0.245] | [metric:audio_gate/loso@all-matches#F4b_duty_at_10=0.245] | - | [metric:audio_gate/loso@all-matches#F4b_onset_median_s=-0.12] |
| F2c | [metric:audio_gate/loso@all-matches#F2c_unexplained_per_min_at_recall_0_5=3.51] | - | [metric:audio_gate/loso@all-matches#F2c_duty_at_1=0.123] | [metric:audio_gate/loso@all-matches#F2c_duty_at_3=0.294] | [metric:audio_gate/loso@all-matches#F2c_duty_at_10=0.515] | - | [metric:audio_gate/loso@all-matches#F2c_onset_median_s=-0.02] |

Over the sessions at or below speech fraction 0.18, without `5822b6646448`, `59c70f1ef720`, `9acf02f98283`, `a06f04a0059f`, `b7d24102a6f6`, `c40d950031bb`:

| Gate | Verified recall at 3/min | at best | All casts at 3/min | Unexplained/min at recall 0.5 | at recall 0.7 | Duty at 3/min |
|---|---|---|---|---|---|---|
| F0 | [metric:audio_gate/loso@all-matches#F0_recall_verified_at_3_clean=0.195] | [metric:audio_gate/loso@all-matches#F0_recall_verified_max_clean=0.747] | [metric:audio_gate/loso@all-matches#F0_recall_all_at_3_clean=0.211] | [metric:audio_gate/loso@all-matches#F0_unexplained_per_min_at_recall_0_5_clean=6.28] | [metric:audio_gate/loso@all-matches#F0_unexplained_per_min_at_recall_0_7_clean=9.19] | [metric:audio_gate/loso@all-matches#F0_duty_at_3_clean=0.297] |
| F1 | [metric:audio_gate/loso@all-matches#F1_recall_verified_at_3_clean=0.103] | [metric:audio_gate/loso@all-matches#F1_recall_verified_max_clean=0.713] | [metric:audio_gate/loso@all-matches#F1_recall_all_at_3_clean=0.115] | [metric:audio_gate/loso@all-matches#F1_unexplained_per_min_at_recall_0_5_clean=16.49] | [metric:audio_gate/loso@all-matches#F1_unexplained_per_min_at_recall_0_7_clean=20.2] | [metric:audio_gate/loso@all-matches#F1_duty_at_3_clean=0.274] |
| F2 | [metric:audio_gate/loso@all-matches#F2_recall_verified_at_3_clean=0.483] | [metric:audio_gate/loso@all-matches#F2_recall_verified_max_clean=0.621] | [metric:audio_gate/loso@all-matches#F2_recall_all_at_3_clean=0.571] | [metric:audio_gate/loso@all-matches#F2_unexplained_per_min_at_recall_0_5_clean=3.12] | - | [metric:audio_gate/loso@all-matches#F2_duty_at_3_clean=0.3] |
| F3 | [metric:audio_gate/loso@all-matches#F3_recall_verified_at_3_clean=0.046] | [metric:audio_gate/loso@all-matches#F3_recall_verified_max_clean=0.667] | [metric:audio_gate/loso@all-matches#F3_recall_all_at_3_clean=0.061] | [metric:audio_gate/loso@all-matches#F3_unexplained_per_min_at_recall_0_5_clean=12.82] | - | [metric:audio_gate/loso@all-matches#F3_duty_at_3_clean=0.182] |
| F4 | [metric:audio_gate/loso@all-matches#F4_recall_verified_at_3_clean=0.08] | [metric:audio_gate/loso@all-matches#F4_recall_verified_max_clean=0.437] | [metric:audio_gate/loso@all-matches#F4_recall_all_at_3_clean=0.093] | - | - | [metric:audio_gate/loso@all-matches#F4_duty_at_3_clean=0.214] |
| F4b | [metric:audio_gate/loso@all-matches#F4b_recall_verified_at_3_clean=0.391] | [metric:audio_gate/loso@all-matches#F4b_recall_verified_max_clean=0.402] | [metric:audio_gate/loso@all-matches#F4b_recall_all_at_3_clean=0.459] | - | - | [metric:audio_gate/loso@all-matches#F4b_duty_at_3_clean=0.297] |
| F2c | [metric:audio_gate/loso@all-matches#F2c_recall_verified_at_3_clean=0.471] | [metric:audio_gate/loso@all-matches#F2c_recall_verified_max_clean=0.632] | [metric:audio_gate/loso@all-matches#F2c_recall_all_at_3_clean=0.571] | [metric:audio_gate/loso@all-matches#F2c_unexplained_per_min_at_recall_0_5_clean=3.4] | - | [metric:audio_gate/loso@all-matches#F2c_duty_at_3_clean=0.296] |

Transfer, fitted on all matches and scored on the re-recorded demos' real casts at each gate's 3/min threshold: F0 [metric:audio_gate/demo-transfer@demos#F0_recall=0.733] of [metric:audio_gate/demo-transfer@demos#F0_n_casts=15], F1 [metric:audio_gate/demo-transfer@demos#F1_recall=0.4] of [metric:audio_gate/demo-transfer@demos#F1_n_casts=15], F2 [metric:audio_gate/demo-transfer@demos#F2_recall=0.733] of [metric:audio_gate/demo-transfer@demos#F2_n_casts=15], F3 [metric:audio_gate/demo-transfer@demos#F3_recall=0.133] of [metric:audio_gate/demo-transfer@demos#F3_n_casts=15], F4 [metric:audio_gate/demo-transfer@demos#F4_recall=0.333] of [metric:audio_gate/demo-transfer@demos#F4_n_casts=15], F4b [metric:audio_gate/demo-transfer@demos#F4b_recall=0.533] of [metric:audio_gate/demo-transfer@demos#F4b_n_casts=15], F2c [metric:audio_gate/demo-transfer@demos#F2c_recall=0.733] of [metric:audio_gate/demo-transfer@demos#F2c_n_casts=15]. F1 scores each demo without that demo's own templates.

### Curves

- `<store>/analysis/audio-gate/0.1.0/report/curves_verified.png`: verified recall against unexplained per live minute, all sessions
- `<store>/analysis/audio-gate/0.1.0/report/curves_all.png`: recall on all tray casts, all sessions
- `<store>/analysis/audio-gate/0.1.0/report/curves_verified_clean.png`: verified recall, the sessions at or below the speech cut
- `<store>/analysis/audio-gate/0.1.0/review/F2/index.html`: the top unexplained detections of F2, each with its capture path, time, spectrogram and an `ffplay` command.

### Per session

Sorted by speech fraction, the share of 1 s tagger windows with a Speech posterior above 0.5. Sustained speech is the share of 60 s stretches in which more than 60% of the windows carry a Speech posterior above 0.2. The fractions form a continuum with no gap; the stated cut, 0.18, puts above it exactly the sessions whose sustained speech is 0.05 or more, so both measures name the same sessions, marked (podcast). No session holds a Speech posterior above 0.5 for minutes at a time: the longest run, gaps up to 1.5 s bridged, lasts [metric:audio_gate/speech@9acf02f98283#speech_longest_run_s=33.5] s, on `9acf02f98283`. The sustained stretches hover around 0.5, which splits them into short runs. The demos, which carry no podcast, read [metric:audio_gate/speech@aab12e41dcfc#speech_fraction=0.023], [metric:audio_gate/speech@6afc32cb46b4#speech_fraction=0.009], [metric:audio_gate/speech@fc02a2c1ac01#speech_fraction=0.022], [metric:audio_gate/speech@0c6c52a65b9e#speech_fraction=0.076], [metric:audio_gate/speech@6ab7a9e99235#speech_fraction=0.0]. Rates are at each gate's pooled thresholds.

| Session | Speech fraction | Sustained speech | Speech posterior in buy phase, mean | Live min | Casts | F2 unexplained/min | F2 recall, all casts | F2 unexplained/min at recall 0.5 |
|---|---|---|---|---|---|---|---|---|
| `b7d24102a6f6` (podcast) | [metric:audio_gate/speech@b7d24102a6f6#speech_fraction=0.223] | [metric:audio_gate/speech@b7d24102a6f6#speech_sustained_fraction=0.072] | [metric:audio_gate/speech@b7d24102a6f6#speech_buy_mean=0.197] | [metric:audio_gate/loso@b7d24102a6f6#live_minutes=12.7] | [metric:audio_gate/loso@b7d24102a6f6#casts=24] | [metric:audio_gate/loso@b7d24102a6f6#F2_unexplained_per_min_at_3=3.77] | [metric:audio_gate/loso@b7d24102a6f6#F2_recall_all_at_3=0.708] | [metric:audio_gate/loso@b7d24102a6f6#F2_unexplained_per_min_at_recall_0_5=4.56] |
| `5822b6646448` (podcast) | [metric:audio_gate/speech@5822b6646448#speech_fraction=0.222] | [metric:audio_gate/speech@5822b6646448#speech_sustained_fraction=0.051] | [metric:audio_gate/speech@5822b6646448#speech_buy_mean=0.228] | [metric:audio_gate/loso@5822b6646448#live_minutes=12.4] | [metric:audio_gate/loso@5822b6646448#casts=17] | [metric:audio_gate/loso@5822b6646448#F2_unexplained_per_min_at_3=2.1] | [metric:audio_gate/loso@5822b6646448#F2_recall_all_at_3=0.412] | [metric:audio_gate/loso@5822b6646448#F2_unexplained_per_min_at_recall_0_5=2.26] |
| `a06f04a0059f` (podcast) | [metric:audio_gate/speech@a06f04a0059f#speech_fraction=0.219] | [metric:audio_gate/speech@a06f04a0059f#speech_sustained_fraction=0.295] | [metric:audio_gate/speech@a06f04a0059f#speech_buy_mean=0.228] | [metric:audio_gate/loso@a06f04a0059f#live_minutes=10.9] | [metric:audio_gate/loso@a06f04a0059f#casts=17] | [metric:audio_gate/loso@a06f04a0059f#F2_unexplained_per_min_at_3=2.47] | [metric:audio_gate/loso@a06f04a0059f#F2_recall_all_at_3=0.647] | [metric:audio_gate/loso@a06f04a0059f#F2_unexplained_per_min_at_recall_0_5=3.2] |
| `9acf02f98283` (podcast) | [metric:audio_gate/speech@9acf02f98283#speech_fraction=0.218] | [metric:audio_gate/speech@9acf02f98283#speech_sustained_fraction=0.052] | [metric:audio_gate/speech@9acf02f98283#speech_buy_mean=0.211] | [metric:audio_gate/loso@9acf02f98283#live_minutes=17.8] | [metric:audio_gate/loso@9acf02f98283#casts=31] | [metric:audio_gate/loso@9acf02f98283#F2_unexplained_per_min_at_3=3.1] | [metric:audio_gate/loso@9acf02f98283#F2_recall_all_at_3=0.742] | [metric:audio_gate/loso@9acf02f98283#F2_unexplained_per_min_at_recall_0_5=3.6] |
| `59c70f1ef720` (podcast) | [metric:audio_gate/speech@59c70f1ef720#speech_fraction=0.21] | [metric:audio_gate/speech@59c70f1ef720#speech_sustained_fraction=0.135] | [metric:audio_gate/speech@59c70f1ef720#speech_buy_mean=0.191] | [metric:audio_gate/loso@59c70f1ef720#live_minutes=19.3] | [metric:audio_gate/loso@59c70f1ef720#casts=33] | [metric:audio_gate/loso@59c70f1ef720#F2_unexplained_per_min_at_3=3.84] | [metric:audio_gate/loso@59c70f1ef720#F2_recall_all_at_3=0.606] | [metric:audio_gate/loso@59c70f1ef720#F2_unexplained_per_min_at_recall_0_5=4.36] |
| `c40d950031bb` (podcast) | [metric:audio_gate/speech@c40d950031bb#speech_fraction=0.185] | [metric:audio_gate/speech@c40d950031bb#speech_sustained_fraction=0.075] | [metric:audio_gate/speech@c40d950031bb#speech_buy_mean=0.171] | [metric:audio_gate/loso@c40d950031bb#live_minutes=5.4] | [metric:audio_gate/loso@c40d950031bb#casts=11] | [metric:audio_gate/loso@c40d950031bb#F2_unexplained_per_min_at_3=4.97] | [metric:audio_gate/loso@c40d950031bb#F2_recall_all_at_3=0.727] | [metric:audio_gate/loso@c40d950031bb#F2_unexplained_per_min_at_recall_0_5=5.34] |
| `223d636bf8d2` | [metric:audio_gate/speech@223d636bf8d2#speech_fraction=0.175] | [metric:audio_gate/speech@223d636bf8d2#speech_sustained_fraction=0.037] | [metric:audio_gate/speech@223d636bf8d2#speech_buy_mean=0.167] | [metric:audio_gate/loso@223d636bf8d2#live_minutes=18.5] | [metric:audio_gate/loso@223d636bf8d2#casts=29] | [metric:audio_gate/loso@223d636bf8d2#F2_unexplained_per_min_at_3=2.16] | [metric:audio_gate/loso@223d636bf8d2#F2_recall_all_at_3=0.69] | [metric:audio_gate/loso@223d636bf8d2#F2_unexplained_per_min_at_recall_0_5=2.16] |
| `ff636d173b07` | [metric:audio_gate/speech@ff636d173b07#speech_fraction=0.168] | [metric:audio_gate/speech@ff636d173b07#speech_sustained_fraction=0.016] | [metric:audio_gate/speech@ff636d173b07#speech_buy_mean=0.187] | [metric:audio_gate/loso@ff636d173b07#live_minutes=18.7] | [metric:audio_gate/loso@ff636d173b07#casts=28] | [metric:audio_gate/loso@ff636d173b07#F2_unexplained_per_min_at_3=2.78] | [metric:audio_gate/loso@ff636d173b07#F2_recall_all_at_3=0.179] | [metric:audio_gate/loso@ff636d173b07#F2_unexplained_per_min_at_recall_0_5=3.05] |
| `c62c2b06bcfb` | [metric:audio_gate/speech@c62c2b06bcfb#speech_fraction=0.163] | [metric:audio_gate/speech@c62c2b06bcfb#speech_sustained_fraction=0.016] | [metric:audio_gate/speech@c62c2b06bcfb#speech_buy_mean=0.168] | [metric:audio_gate/loso@c62c2b06bcfb#live_minutes=14.2] | [metric:audio_gate/loso@c62c2b06bcfb#casts=30] | [metric:audio_gate/loso@c62c2b06bcfb#F2_unexplained_per_min_at_3=2.18] | [metric:audio_gate/loso@c62c2b06bcfb#F2_recall_all_at_3=0.7] | [metric:audio_gate/loso@c62c2b06bcfb#F2_unexplained_per_min_at_recall_0_5=2.6] |
| `b3b9defb6fd7` | [metric:audio_gate/speech@b3b9defb6fd7#speech_fraction=0.157] | [metric:audio_gate/speech@b3b9defb6fd7#speech_sustained_fraction=0.002] | [metric:audio_gate/speech@b3b9defb6fd7#speech_buy_mean=0.191] | [metric:audio_gate/loso@b3b9defb6fd7#live_minutes=9.4] | [metric:audio_gate/loso@b3b9defb6fd7#casts=17] | [metric:audio_gate/loso@b3b9defb6fd7#F2_unexplained_per_min_at_3=3.07] | [metric:audio_gate/loso@b3b9defb6fd7#F2_recall_all_at_3=0.529] | [metric:audio_gate/loso@b3b9defb6fd7#F2_unexplained_per_min_at_recall_0_5=3.49] |
| `75a55a296d3b` | [metric:audio_gate/speech@75a55a296d3b#speech_fraction=0.15] | [metric:audio_gate/speech@75a55a296d3b#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@75a55a296d3b#speech_buy_mean=0.127] | [metric:audio_gate/loso@75a55a296d3b#live_minutes=7.1] | [metric:audio_gate/loso@75a55a296d3b#casts=13] | [metric:audio_gate/loso@75a55a296d3b#F2_unexplained_per_min_at_3=5.53] | [metric:audio_gate/loso@75a55a296d3b#F2_recall_all_at_3=0.769] | [metric:audio_gate/loso@75a55a296d3b#F2_unexplained_per_min_at_recall_0_5=5.38] |
| `bdfdcf009dba` | [metric:audio_gate/speech@bdfdcf009dba#speech_fraction=0.146] | [metric:audio_gate/speech@bdfdcf009dba#speech_sustained_fraction=0.023] | [metric:audio_gate/speech@bdfdcf009dba#speech_buy_mean=0.158] | [metric:audio_gate/loso@bdfdcf009dba#live_minutes=14.7] | [metric:audio_gate/loso@bdfdcf009dba#casts=28] | [metric:audio_gate/loso@bdfdcf009dba#F2_unexplained_per_min_at_3=3.61] | [metric:audio_gate/loso@bdfdcf009dba#F2_recall_all_at_3=0.393] | [metric:audio_gate/loso@bdfdcf009dba#F2_unexplained_per_min_at_recall_0_5=4.02] |
| `96aa1ae9b96f` | [metric:audio_gate/speech@96aa1ae9b96f#speech_fraction=0.135] | [metric:audio_gate/speech@96aa1ae9b96f#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@96aa1ae9b96f#speech_buy_mean=0.116] | [metric:audio_gate/loso@96aa1ae9b96f#live_minutes=10.2] | [metric:audio_gate/loso@96aa1ae9b96f#casts=16] | [metric:audio_gate/loso@96aa1ae9b96f#F2_unexplained_per_min_at_3=2.16] | [metric:audio_gate/loso@96aa1ae9b96f#F2_recall_all_at_3=0.812] | [metric:audio_gate/loso@96aa1ae9b96f#F2_unexplained_per_min_at_recall_0_5=2.45] |
| `bfad2778a372` | [metric:audio_gate/speech@bfad2778a372#speech_fraction=0.134] | [metric:audio_gate/speech@bfad2778a372#speech_sustained_fraction=0.001] | [metric:audio_gate/speech@bfad2778a372#speech_buy_mean=0.144] | [metric:audio_gate/loso@bfad2778a372#live_minutes=16.6] | [metric:audio_gate/loso@bfad2778a372#casts=32] | [metric:audio_gate/loso@bfad2778a372#F2_unexplained_per_min_at_3=3.02] | [metric:audio_gate/loso@bfad2778a372#F2_recall_all_at_3=0.844] | [metric:audio_gate/loso@bfad2778a372#F2_unexplained_per_min_at_recall_0_5=3.32] |
| `e37fdeca944f` | [metric:audio_gate/speech@e37fdeca944f#speech_fraction=0.127] | [metric:audio_gate/speech@e37fdeca944f#speech_sustained_fraction=0.032] | [metric:audio_gate/speech@e37fdeca944f#speech_buy_mean=0.155] | [metric:audio_gate/loso@e37fdeca944f#live_minutes=17.5] | [metric:audio_gate/loso@e37fdeca944f#casts=41] | [metric:audio_gate/loso@e37fdeca944f#F2_unexplained_per_min_at_3=3.31] | [metric:audio_gate/loso@e37fdeca944f#F2_recall_all_at_3=0.683] | [metric:audio_gate/loso@e37fdeca944f#F2_unexplained_per_min_at_recall_0_5=3.94] |
| `043bafca271a` | [metric:audio_gate/speech@043bafca271a#speech_fraction=0.124] | [metric:audio_gate/speech@043bafca271a#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@043bafca271a#speech_buy_mean=0.137] | [metric:audio_gate/loso@043bafca271a#live_minutes=13.6] | [metric:audio_gate/loso@043bafca271a#casts=25] | [metric:audio_gate/loso@043bafca271a#F2_unexplained_per_min_at_3=3.08] | [metric:audio_gate/loso@043bafca271a#F2_recall_all_at_3=0.68] | [metric:audio_gate/loso@043bafca271a#F2_unexplained_per_min_at_recall_0_5=3.23] |
| `3694746e4e54` | [metric:audio_gate/speech@3694746e4e54#speech_fraction=0.11] | [metric:audio_gate/speech@3694746e4e54#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@3694746e4e54#speech_buy_mean=0.118] | [metric:audio_gate/loso@3694746e4e54#live_minutes=12.6] | [metric:audio_gate/loso@3694746e4e54#casts=26] | [metric:audio_gate/loso@3694746e4e54#F2_unexplained_per_min_at_3=2.7] | [metric:audio_gate/loso@3694746e4e54#F2_recall_all_at_3=0.577] | [metric:audio_gate/loso@3694746e4e54#F2_unexplained_per_min_at_recall_0_5=2.94] |
| `7010b3d62460` | [metric:audio_gate/speech@7010b3d62460#speech_fraction=0.05] | [metric:audio_gate/speech@7010b3d62460#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@7010b3d62460#speech_buy_mean=0.126] | [metric:audio_gate/loso@7010b3d62460#live_minutes=14.1] | [metric:audio_gate/loso@7010b3d62460#casts=28] | [metric:audio_gate/loso@7010b3d62460#F2_unexplained_per_min_at_3=2.9] | [metric:audio_gate/loso@7010b3d62460#F2_recall_all_at_3=0.464] | [metric:audio_gate/loso@7010b3d62460#F2_unexplained_per_min_at_recall_0_5=3.25] |
| `587c15b07779` | [metric:audio_gate/speech@587c15b07779#speech_fraction=0.049] | [metric:audio_gate/speech@587c15b07779#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@587c15b07779#speech_buy_mean=0.151] | [metric:audio_gate/loso@587c15b07779#live_minutes=12.3] | [metric:audio_gate/loso@587c15b07779#casts=24] | [metric:audio_gate/loso@587c15b07779#F2_unexplained_per_min_at_3=2.85] | [metric:audio_gate/loso@587c15b07779#F2_recall_all_at_3=0.417] | [metric:audio_gate/loso@587c15b07779#F2_unexplained_per_min_at_recall_0_5=3.01] |
| `a1a995e6b19b` | [metric:audio_gate/speech@a1a995e6b19b#speech_fraction=0.047] | [metric:audio_gate/speech@a1a995e6b19b#speech_sustained_fraction=0.0] | [metric:audio_gate/speech@a1a995e6b19b#speech_buy_mean=0.141] | [metric:audio_gate/loso@a1a995e6b19b#live_minutes=13.4] | [metric:audio_gate/loso@a1a995e6b19b#casts=38] | [metric:audio_gate/loso@a1a995e6b19b#F2_unexplained_per_min_at_3=1.27] | [metric:audio_gate/loso@a1a995e6b19b#F2_recall_all_at_3=0.263] | [metric:audio_gate/loso@a1a995e6b19b#F2_unexplained_per_min_at_recall_0_5=1.87] |

### Witnesses

Stored minimap onsets against F2's detections at its 3/min threshold. Agreement is consistency, not accuracy: a detection beside a ping shows that two channels coincide, not that either is right. Each chance column is the share of live time within 1.5 s of the other side. `events/ability` holds only demos, and `events/minimap_dark` holds masks whose onsets are the smoke tracks, so neither adds a row.

| Witness | Sessions | Live onsets | Onsets with a detection | Chance | Unexplained detections with an onset | Chance |
|---|---|---|---|---|---|---|
| events/ping: every stored minimap ping of the player's team, its first frame | [metric:audio_gate/witness@all-matches#ping_sessions=19] | [metric:audio_gate/witness@all-matches#ping_onsets_live=316] | [metric:audio_gate/witness@all-matches#F2_ping_onsets_near=0.313] | [metric:audio_gate/witness@all-matches#F2_ping_onsets_chance=0.267] | [metric:audio_gate/witness@all-matches#F2_ping_unexplained_near=0.06] | [metric:audio_gate/witness@all-matches#ping_cover_live=0.058] |
| events/ability_shape: first found crop per own tray cast (Regrowth ring, Recon Bolt ring, Hunter's Fury line) | [metric:audio_gate/witness@all-matches#ability_shape_sessions=12] | [metric:audio_gate/witness@all-matches#ability_shape_onsets_live=98] | [metric:audio_gate/witness@all-matches#F2_ability_shape_onsets_near=0.888] | [metric:audio_gate/witness@all-matches#F2_ability_shape_onsets_chance=0.298] | [metric:audio_gate/witness@all-matches#F2_ability_shape_unexplained_near=0.009] | [metric:audio_gate/witness@all-matches#ability_shape_cover_live=0.028] |
| events/smoke over events/minimap_dark: observed smoke-track onsets | [metric:audio_gate/witness@all-matches#smoke_sessions=1] | [metric:audio_gate/witness@all-matches#smoke_onsets_live=22] | [metric:audio_gate/witness@all-matches#F2_smoke_onsets_near=0.273] | [metric:audio_gate/witness@all-matches#F2_smoke_onsets_chance=0.238] | [metric:audio_gate/witness@all-matches#F2_smoke_unexplained_near=0.148] | [metric:audio_gate/witness@all-matches#smoke_cover_live=0.08] |
| events/round_entity: first frame of each ally-family piece the identity arbiter abstained on (rings, devices, fragments) | [metric:audio_gate/witness@all-matches#unnamed_ally_piece_sessions=19] | [metric:audio_gate/witness@all-matches#unnamed_ally_piece_onsets_live=2202] | [metric:audio_gate/witness@all-matches#F2_unnamed_ally_piece_onsets_near=0.445] | [metric:audio_gate/witness@all-matches#F2_unnamed_ally_piece_onsets_chance=0.267] | [metric:audio_gate/witness@all-matches#F2_unnamed_ally_piece_unexplained_near=0.36] | [metric:audio_gate/witness@all-matches#unnamed_ally_piece_cover_live=0.268] |

The tagger's Speech posterior exceeds 0.5 at [metric:audio_gate/loso@all-matches#F2_unexplained_speech_fraction=0.29] of F2's unexplained onsets at 3/min, against [metric:audio_gate/loso@all-matches#live_speech_fraction=0.154] of live time; [metric:audio_gate/review-F2@all-matches#speech_tagged=17] of the [metric:audio_gate/review-F2@all-matches#rows=40] rows on the review sheet carry the speech tag. The tagger and the gate hear the same audio, so this too is consistency, not a second witness.

### Outcomes

Measured values beside each prediction; the player judges them.

- **P0.** Gunfire frames carry more 1 to 4 kHz energy than background on [metric:audio_gate/p0@all-matches#sessions_louder=20] of [metric:audio_gate/p0@all-matches#sessions_with_gunfire=20] sessions with gunfire; the median difference is [metric:audio_gate/p0@all-matches#diff_db_median=17.97] dB and the least [metric:audio_gate/p0@all-matches#diff_db_min=12.11] dB.
- **P1.** F0 never reaches verified recall 0.8; its verified recall at 20/min is [metric:audio_gate/loso@all-matches#F0_recall_verified_at_20=0.758], its maximum [metric:audio_gate/loso@all-matches#F0_recall_verified_max=0.758], and it needs [metric:audio_gate/loso@all-matches#F0_unexplained_per_min_at_recall_0_7=9.42] unexplained per minute for recall 0.7.
- **P2.** F2's verified recall at 3/min is [metric:audio_gate/loso@all-matches#F2_recall_verified_at_3=0.483]; without the podcast sessions [metric:audio_gate/loso@all-matches#F2_recall_verified_at_3_clean=0.483]; F2c's [metric:audio_gate/loso@all-matches#F2c_recall_verified_at_3=0.467].
- **P3.** F3's verified recall at 5/min is [metric:audio_gate/loso@all-matches#F3_recall_verified_at_5=0.117].
- **P4.** At F2's 3/min threshold, Run it Back fired [metric:audio_gate/tray-blind@demos#F2_run_it_back_fired=1] (1 is fired), with a highest in-session rank of [metric:audio_gate/tray-blind@demos#F2_run_it_back_rank=1.0] in its recall window; the Regrowth cast on `fc02a2c1ac01` fired [metric:audio_gate/tray-blind@demos#F2_regrowth_fc02a2c1ac01_fired=1], rank [metric:audio_gate/tray-blind@demos#F2_regrowth_fc02a2c1ac01_rank=0.991]. The demos hold one Regrowth cast, not the two P4 assumed: the player read the drop on `6ab7a9e99235` at 27.6 s as the in-game menu dimming the tray [domain:hud/menu-dims-tray].
- **P5.** F2's median onset minus drop is [metric:audio_gate/loso@all-matches#F2_onset_median_s=-0.05] s; the median absolute offset [metric:audio_gate/loso@all-matches#F2_onset_abs_median_s=0.25] s.
- **P6.** On `a06f04a0059f`, [metric:audio_gate/smokes@a06f04a0059f#onsets_live=22] of [metric:audio_gate/smokes@a06f04a0059f#onsets=27] observed smoke onsets fall in live time. F2 has a detection within 1.5 s of [metric:audio_gate/smokes@a06f04a0059f#F2_fraction_within_1_5=0.296] of all onsets and [metric:audio_gate/smokes@a06f04a0059f#F2_fraction_within_1_5_live=0.273] of the live ones; chance is [metric:audio_gate/smokes@a06f04a0059f#F2_chance_live=0.238].
- **P7.** The player named no sessions; the tagger's speech fraction stands in. Of the [metric:audio_gate/loso@all-matches#podcast_k=6] sessions above the cut, [metric:audio_gate/loso@all-matches#F2_podcast_in_top_k=3] are among the [metric:audio_gate/loso@all-matches#podcast_k=6] with the most F2 unexplained detections per minute at recall 0.5, where every session shares one pooled threshold; the rank correlation of speech fraction with that rate is [metric:audio_gate/loso@all-matches#F2_speech_spearman=0.265]. F0 reads [metric:audio_gate/loso@all-matches#F0_podcast_in_top_k=2] of [metric:audio_gate/loso@all-matches#podcast_k=6] and [metric:audio_gate/loso@all-matches#F0_speech_spearman=0.338].

### Verdicts (2026-09-27)

Judged by the orchestrator against the falsifiers written before the run;
the ledger rows are `audio-gate` outcomes of 2026-09-27.

- **P0 confirmed.** The ammo rule is a gunfire witness.
- **P1 confirmed as stated, weakly.** Loudness never reaches 0.8 but reaches
  0.717 at 10 per minute: a poor gate, not no gate.
- **P2 falsified.** 0.483 is below the 0.5 falsifier.
- **P3 falsified.** A background-only density does not find casts.
- **P4 confirmed**, on the one Regrowth demo cast that exists.
- **P5 confirmed.** The gate dates a cast to within 50 ms.
- **P6 falsified.** Smoke onsets are at chance.
- **P7 not supported.** Half the podcast sessions are among the noisiest.

Decision: the gate stays a prototype (`wire: no`). It is not a switch for
the expensive passes on its own. Its next use is as one of two witnesses
for births of others' abilities beside a minimap change gate, after the
timer bar and cooldown counters are read as cast witnesses; the unnamed
ally piece association is the lead. The review sheet awaits the player.

### The player's review (2026-09-27)

The player listened to six of the 40 unexplained rows in
`analysis/audio-gate/0.1.0/review/F2/index.html` and stopped, calling the
problem hard and the source rich. Every row held allies' casts with their
voice lines, and reloads; none was a false alarm. Paraphrased:

| Row | Session | Capture | Onset (s) | Heard |
|---|---|---|---|---|
| 2 | `b7d24102a6f6` | `2026-08-24 12-37-04.mp4` | 252.7 | Skye's bird, then Regrowth, then a reload |
| 3 | `7010b3d62460` | `2026-09-07 19-46-44.mp4` | 1587.1 | a Skye flash and a Chamber callout; muddled |
| 6 | `59c70f1ef720` | `2026-08-24 13-58-11.mp4` | 2343.5 | Clove's smoke line and the smoke's sound, an enemy-spotted callout, Sova's drone going out at the end |
| 9 | `c62c2b06bcfb` | `2026-08-26 13-18-48.mp4` | 1357.7 | Skye's dog, Sage's wall with its line, Skye's heal, Omen's reload line and the reload |
| 10 | `043bafca271a` | `2026-08-25 13-59-44.mp4` | 1870.1 | a death, a reload, Vyse's ult line and activation, then a flash |
| 15 | `e37fdeca944f` | `2026-08-25 13-17-45.mp4` | 289.9 | Skye's dog with its line, Sage's orb, Jett's smoke line, Raze's grenade, a Jett callout, destruction sounds, Skye's scout-destroyed line, Jett's reload line |

Two consequences. The gate's unexplained detections are ability events,
so the target is naming them, not suppressing them. And the game announces
casts in fixed voice lines [domain:abilities/voice-lines-announce-casts]
and ends devices with sounds and lines [domain:abilities/device-destroyed-sounds]:
these are fixed assets, so the next experiment matches them as templates
rather than classifying speech. The lines are allies' only, so a matched
line names an ally's cast and an enemy's cast leaves only the ability
sound; whether the player's own lines are heard, and whether a line sits
at a fixed offset from the cast, are open (the fact's exceptions). A
callout also prints in the chat box [domain:hud/chat-broadcasts-callouts],
which no reader parses. F1 was plain normalised correlation on log-mel, which
the magnitude envelope governs and occlusion and HRTF change; a whitened,
phase-transform correlation on the decoded waveform is untested. The player's evaluation criterion for all of this
work is the full-round event stream, everything identified and localised
and behaving by the game's invariants; the annotated match, not a recall
number, is the review.

### What was not done

- No events, labels or `reticle/` module: the gate stays a prototype until the player has judged the review sheet.
- The implementation gave no verdict on P0 to P7; the orchestrator's verdicts are above.
- No recall per agent or per ability, and no threshold per session or per map: one pooled threshold per gate.
- Teammates' and enemies' abilities stay unlabelled inside background; the witness table bounds their share of the unexplained detections only where a minimap table dates them.
- F4 was not fine-tuned, and its background classes are a fixed list, not fitted.
- No audio left a capture: no WAV and no clips; the review sheet plays the source with `ffplay`. No video was decoded and no `roi_cache` was read.
- The implementation appended nothing to the store's `notes/predictions.jsonl`;
  the orchestrator appended the verdicts and the wiring decision.
- The tests run under `unittest`; the venv has no pytest.
