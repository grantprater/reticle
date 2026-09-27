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

Pending.
