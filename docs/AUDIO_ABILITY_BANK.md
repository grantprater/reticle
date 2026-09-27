# Naming the player's abilities from audio

Date: 2026-09-26. Status: experiment; declined for wiring. Prototype:
[`prototypes/audio_bank.py`](../prototypes/audio_bank.py) (`audio-bank-0.1.0`).
Ledger: the store's `notes/predictions.jsonl`, task `audio-ability-bank`.
Outputs: the store's `analysis/audio-bank/` (features, score caches, plots).

## What was asked

Can the local player's ability casts be named from audio alone, with
references cut from the solo demos and tested on real matches? The tray says
that a slot dropped and roughly when; it does not always say which sound went
with the drop, and a drop also comes from an ability equipped and not used.
Audio would be a second witness to the same event, independent of the tray.

`prototypes/audio_channel.py` had shown that a 0.6 s log-mel template names an
ability within one session and transfers only partly between two Omen
sessions. This run builds a bank from every solo demo, measures it by
leave-one-cast-out within the demos, then scores the player's casts in real
matches against it.

## Method

- **Bank.** A window from 1.5 s before to 1.0 s after each tray drop in the
  demo cast caches, plus five cast times the ledger names for two demos
  without a cache: [metric:audio_bank/build#demo_casts=132] casts from
  [metric:audio_bank/build#demo_sessions=29] demos in
  [metric:audio_bank/build#bank_classes=100] (agent, slot) classes, of which
  [metric:audio_bank/build#bank_classes_single=74] hold one reference. Drops of
  three or more slots within 1.5 s mark the tray changing owner and were left
  out ([metric:audio_bank/build#demo_switch_excluded=12]).
- **Front end.** `audio_channel`'s log-mel (64 bands, 60 Hz-16 kHz, 10 ms hop,
  mono), with the per-band median of an 8 s context around the drop removed,
  so a match and a demo go through the same arithmetic. Audio is decoded by
  seeking the audio stream; no video frame is decoded and no audio is stored.
- **Templates.** Each reference offers a `cast` template at the largest onset
  the tray allows and an `equip` template at an earlier onset
  [domain:abilities/ability-sound-phases]. A drop can mark the equip rather
  than the fire [domain:abilities/deadlock-ult-tray-drop-at-equip], so the
  names are positions, not verified phases.
- **Scores.** `corr` (z-scored patch correlation), `cover` (one-sided coverage,
  which tolerates voice lines [domain:abilities/ability-voice-line-mask]),
  `prod` = max(corr, 0) x cover, and `cover_abs`, `prod_abs` on absolute
  levels. The declared primary was `prod` on the cast template. A class scores
  its best reference over the lags its phase allows.
- **Candidate sets.** The kit 4-way scores only the four slots of the player's
  agent, which the lineup allows (the arbiter's resolved verdict for the
  player's slot). The open set scores all 100 classes and refuses below the
  95th percentile of the demo reject class (tray-quiet windows at least 8 s from
  any drop). The open set is the surprise path: it asks whether audio alone
  would name the agent.
- **Match queries.** Every `player_cast` drop in `events/tray_drop`
  ([metric:audio_bank/build#match_player_casts=483] in
  [metric:audio_bank/build#match_sessions=19] sessions), of which
  [metric:audio_bank/build#match_labelled=120] carry the player's answer in
  `labels/tray_object`. The null is
  [metric:audio_bank/build#match_null=190] windows from round-live spans before
  the player's first death, 8 s from any drop. Scoring goes by slot:
  [metric:audio_bank/build#label_ability_mismatch=18] Phoenix labels carry the
  older Q/E names [domain:abilities/phoenix-slots].

## Predictions and outcomes

Stated in the ledger before measuring. Kit 4-way chance is 0.25.

| ID | Prediction | Outcome |
|---|---|---|
| B1 | Demo leave-one-cast-out, primary, kit top-1 >= 75% of answerable casts | **Wrong.** [metric:audio_bank/retrieve#kit_hits=28] of [metric:audio_bank/retrieve#answerable=56] ([metric:audio_bank/retrieve#kit_top1=0.5]); the other casts of the [metric:audio_bank/retrieve#n=132] keep no reference of their class once their own is removed. `corr` [metric:audio_bank/retrieve_variants#corr_cast_kit_top1=0.679], `prod_abs` [metric:audio_bank/retrieve_variants#prod_abs_cast_kit_top1=0.732]. |
| B2 | Same set, top-1 over all bank abilities >= 60% | **Wrong.** [metric:audio_bank/retrieve#all_hits=13] ([metric:audio_bank/retrieve#all_top1=0.232]); `corr` [metric:audio_bank/retrieve_variants#corr_cast_all_top1=0.393]. |
| B3 | Demo reject p95 lies below the true-class median | **Wrong.** Reject p95 [metric:audio_bank/retrieve#reject_p95=0.746], reject median [metric:audio_bank/retrieve#reject_median=0.516], true median [metric:audio_bank/retrieve#true_median=0.296]. |
| B4 | Transfer, 120 verified, primary kit top-1 >= 0.50 | **Wrong.** [metric:audio_bank/transfer#verified_kit_hits=39] of [metric:audio_bank/transfer#verified_n=120] ([metric:audio_bank/transfer#verified_kit_top1=0.325]). After the fact: `corr` [metric:audio_bank/transfer_variants#corr_cast_verified_kit_top1=0.483], `prod_abs` [metric:audio_bank/transfer_variants#prod_abs_cast_verified_kit_top1=0.433]. |
| B5 | All tray casts score lower than the verified | **Confirmed, weakly.** [metric:audio_bank/transfer#tray_kit_hits=147] of [metric:audio_bank/transfer#tray_n=483] ([metric:audio_bank/transfer#tray_kit_top1=0.304]); drops not bridged across a gap [metric:audio_bank/transfer#tray_clean_kit_top1=0.318]. |
| B6 | Some referenced ability of the four match agents has kit recall <= 0.25 | **Confirmed.** Five abilities score zero under the primary; see the table. |
| B7 | The demo threshold admits > 5% of the match null | **Wrong.** It admits [metric:audio_bank/transfer#null_accept_all=3] of [metric:audio_bank/transfer#null_n=190] ([metric:audio_bank/transfer#null_accept_all_rate=0.016]), [metric:audio_bank/transfer#null_accept_kit=1] inside the kit. The demo reject class scores higher than the match null, so the threshold is conservative. |
| B8 | Open set accepts fewer than half of the 120 verified | **Confirmed.** [metric:audio_bank/transfer#verified_open_accepted=4] accepted, [metric:audio_bank/transfer#verified_open_correct=0] correct; on all tray casts [metric:audio_bank/transfer#tray_open_accepted=16] accepted, [metric:audio_bank/transfer#tray_open_correct=9] correct. |
| B9 | `prod_abs` beats `prod` on the verified | **Confirmed.** [metric:audio_bank/transfer_variants#prod_abs_cast_verified_kit_top1=0.433] against [metric:audio_bank/transfer_variants#prod_cast_verified_kit_top1=0.325]; on all tray casts [metric:audio_bank/transfer_variants#prod_abs_cast_tray_kit_top1=0.507]. |
| B10 | Median match-minus-demo gain within +/-3 dB | **Confirmed on the median, wrong per cast.** Median [metric:audio_bank/gain#median=-1.9] dB, IQR [metric:audio_bank/gain#q25=-5.2] to [metric:audio_bank/gain#q75=1.8]; [metric:audio_bank/gain#within_3db=41] of [metric:audio_bank/gain#n=114] within 3 dB. Per ability from [metric:audio_bank/transfer_ability_verified#Sova_Q_gain_median=-12.0] dB (Shock Bolt) to [metric:audio_bank/transfer_ability_verified#Skye_X_gain_median=23.1] dB (Seekers); a gain that large marks a reference cut on the wrong event. |
| B11 | Equip-only scores below cast-only | **Confirmed, not meaningful.** [metric:audio_bank/transfer_variants#prod_equip_verified_kit_top1=0.308] against [metric:audio_bank/transfer#verified_kit_top1=0.325]: two casts apart. |
| B12 | Primary beats the per-agent majority slot | **Confirmed, not meaningful.** [metric:audio_bank/transfer#verified_kit_hits=39] against [metric:audio_bank/transfer#majority_hits=35] ([metric:audio_bank/transfer#majority_rate=0.292]). |

After reading the Blaze failure, a second set tested a 1.0 s template, long
enough to hold what follows the onset:

| ID | Prediction | Outcome |
|---|---|---|
| R1 | `corr` verified rises from [metric:audio_bank/transfer_variants#corr_cast_verified_kit_top1=0.483] to >= 0.55 | **Wrong.** [metric:audio_bank/transfer_variants_t100#corr_cast_verified_kit_top1=0.492]. |
| R2 | Blaze under `corr` rises from [metric:audio_bank/confusion_verified#corr_cast_Phoenix_C_hits=1] of 9 to >= 3 of 9 | **Wrong.** [metric:audio_bank/confusion_verified_t100#corr_cast_Phoenix_C_hits=1] of 9. |
| R3 | Primary verified rises from [metric:audio_bank/transfer#verified_kit_top1=0.325] to >= 0.40 | **Wrong.** [metric:audio_bank/transfer_t100#verified_kit_top1=0.383]. The best score seen, `prod_abs` with 1.0 s templates, reached [metric:audio_bank/transfer_variants_t100#prod_abs_cast_verified_kit_top1=0.508] on the verified and [metric:audio_bank/transfer_variants_t100#prod_abs_cast_tray_kit_top1=0.542] on all tray casts; both were chosen after the fact. |

## Per-ability transfer

Kit 4-way hits on the player's casts. "Verified" are the casts the player
answered; "tray" are all `player_cast` drops by that slot, primary score.
Confusions are the `corr` 0.6 s verdicts on the verified casts that named
another slot.

| Ability | Verified n | `prod` 0.6 s | `corr` 0.6 s | `prod_abs` 1.0 s | Tray n | Tray hits | `corr` named instead |
|---|---|---|---|---|---|---|---|
| Sova C Owl Drone | [metric:audio_bank/transfer_ability_verified#Sova_C_n=8] | [metric:audio_bank/confusion_verified#prod_cast_Sova_C_hits=1] | [metric:audio_bank/confusion_verified#corr_cast_Sova_C_hits=8] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Sova_C_hits=7] | [metric:audio_bank/transfer_ability_tray#Sova_C_n=81] | [metric:audio_bank/transfer_ability_tray#Sova_C_kit_hits=17] | - |
| Sova Q Shock Bolt | [metric:audio_bank/transfer_ability_verified#Sova_Q_n=8] | [metric:audio_bank/confusion_verified#prod_cast_Sova_Q_hits=5] | [metric:audio_bank/confusion_verified#corr_cast_Sova_Q_hits=5] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Sova_Q_hits=5] | [metric:audio_bank/transfer_ability_tray#Sova_Q_n=19] | [metric:audio_bank/transfer_ability_tray#Sova_Q_kit_hits=8] | C 3 |
| Sova E Recon Bolt | [metric:audio_bank/transfer_ability_verified#Sova_E_n=8] | [metric:audio_bank/confusion_verified#prod_cast_Sova_E_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Sova_E_hits=0] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Sova_E_hits=0] | [metric:audio_bank/transfer_ability_tray#Sova_E_n=65] | [metric:audio_bank/transfer_ability_tray#Sova_E_kit_hits=12] | C 7, Q 1 |
| Sova X Hunter's Fury | [metric:audio_bank/transfer_ability_verified#Sova_X_n=8] | [metric:audio_bank/confusion_verified#prod_cast_Sova_X_hits=6] | [metric:audio_bank/confusion_verified#corr_cast_Sova_X_hits=6] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Sova_X_hits=6] | [metric:audio_bank/transfer_ability_tray#Sova_X_n=19] | [metric:audio_bank/transfer_ability_tray#Sova_X_kit_hits=14] | Q 2 |
| Phoenix C Blaze | [metric:audio_bank/transfer_ability_verified#Phoenix_C_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Phoenix_C_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Phoenix_C_hits=1] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Phoenix_C_hits=2] | [metric:audio_bank/transfer_ability_tray#Phoenix_C_n=28] | [metric:audio_bank/transfer_ability_tray#Phoenix_C_kit_hits=1] | Q 5, E 2, X 1 |
| Phoenix Q Hot Hands | [metric:audio_bank/transfer_ability_verified#Phoenix_Q_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Phoenix_Q_hits=6] | [metric:audio_bank/confusion_verified#corr_cast_Phoenix_Q_hits=6] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Phoenix_Q_hits=5] | [metric:audio_bank/transfer_ability_tray#Phoenix_Q_n=26] | [metric:audio_bank/transfer_ability_tray#Phoenix_Q_kit_hits=20] | E 1, X 1, C 1 |
| Phoenix E Curveball | [metric:audio_bank/transfer_ability_verified#Phoenix_E_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Phoenix_E_hits=4] | [metric:audio_bank/confusion_verified#corr_cast_Phoenix_E_hits=7] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Phoenix_E_hits=8] | [metric:audio_bank/transfer_ability_tray#Phoenix_E_n=54] | [metric:audio_bank/transfer_ability_tray#Phoenix_E_kit_hits=19] | Q 2 |
| Phoenix X Run it Back | [metric:audio_bank/transfer_ability_verified#Phoenix_X_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Phoenix_X_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Phoenix_X_hits=2] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Phoenix_X_hits=4] | [metric:audio_bank/transfer_ability_tray#Phoenix_X_n=11] | [metric:audio_bank/transfer_ability_tray#Phoenix_X_kit_hits=0] | Q 3, E 3, C 1 |
| Skye C Regrowth | [metric:audio_bank/transfer_ability_verified#Skye_C_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Skye_C_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Skye_C_hits=0] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Skye_C_hits=0] | [metric:audio_bank/transfer_ability_tray#Skye_C_n=25] | [metric:audio_bank/transfer_ability_tray#Skye_C_kit_hits=0] | Q 4, X 3, E 2 |
| Skye Q Trailblazer | [metric:audio_bank/transfer_ability_verified#Skye_Q_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Skye_Q_hits=6] | [metric:audio_bank/confusion_verified#corr_cast_Skye_Q_hits=8] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Skye_Q_hits=7] | [metric:audio_bank/transfer_ability_tray#Skye_Q_n=51] | [metric:audio_bank/transfer_ability_tray#Skye_Q_kit_hits=30] | X 1 |
| Skye E Guiding Light | [metric:audio_bank/transfer_ability_verified#Skye_E_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Skye_E_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Skye_E_hits=7] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Skye_E_hits=7] | [metric:audio_bank/transfer_ability_tray#Skye_E_n=51] | [metric:audio_bank/transfer_ability_tray#Skye_E_kit_hits=0] | X 1, Q 1 |
| Skye X Seekers | [metric:audio_bank/transfer_ability_verified#Skye_X_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Skye_X_hits=6] | [metric:audio_bank/confusion_verified#corr_cast_Skye_X_hits=0] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Skye_X_hits=0] | [metric:audio_bank/transfer_ability_tray#Skye_X_n=15] | [metric:audio_bank/transfer_ability_tray#Skye_X_kit_hits=11] | Q 7, E 2 |
| Clove C Pick-me-up | [metric:audio_bank/transfer_ability_verified#Clove_C_n=5] | [metric:audio_bank/confusion_verified#prod_cast_Clove_C_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Clove_C_hits=0] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Clove_C_hits=0] | [metric:audio_bank/transfer_ability_tray#Clove_C_n=5] | [metric:audio_bank/transfer_ability_tray#Clove_C_kit_hits=0] | Q 4, E 1 |
| Clove Q Meddle | [metric:audio_bank/transfer_ability_verified#Clove_Q_n=1] | [metric:audio_bank/confusion_verified#prod_cast_Clove_Q_hits=1] | [metric:audio_bank/confusion_verified#corr_cast_Clove_Q_hits=0] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Clove_Q_hits=1] | [metric:audio_bank/transfer_ability_tray#Clove_Q_n=2] | [metric:audio_bank/transfer_ability_tray#Clove_Q_kit_hits=2] | E 1 |
| Clove E Ruse | [metric:audio_bank/transfer_ability_verified#Clove_E_n=9] | [metric:audio_bank/confusion_verified#prod_cast_Clove_E_hits=4] | [metric:audio_bank/confusion_verified#corr_cast_Clove_E_hits=8] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Clove_E_hits=9] | [metric:audio_bank/transfer_ability_tray#Clove_E_n=30] | [metric:audio_bank/transfer_ability_tray#Clove_E_kit_hits=13] | Q 1 |
| Clove X Not Dead Yet | [metric:audio_bank/transfer_ability_verified#Clove_X_n=1] | [metric:audio_bank/confusion_verified#prod_cast_Clove_X_hits=0] | [metric:audio_bank/confusion_verified#corr_cast_Clove_X_hits=0] | [metric:audio_bank/confusion_verified_t100#prod_abs_cast_Clove_X_hits=0] | [metric:audio_bank/transfer_ability_tray#Clove_X_n=1] | [metric:audio_bank/transfer_ability_tray#Clove_X_kit_hits=0] | E 1 |

Clove's Pick-me-up and Not Dead Yet have no demo cast, so they cannot score.
Four abilities transfer under `corr`: Owl Drone, Trailblazer, Ruse and
Curveball. Hunter's Fury, Shock Bolt and Hot Hands transfer under every score
at a lower rate. Recon Bolt and Regrowth fail under every score; Blaze and Run
it Back stay below half under every score. Seekers transfers under `prod` and fails under `corr`,
Guiding Light the reverse: their demo references are one sound (below).

## Three failures read in the source

Each plot shows the match window, the true reference and the winning
reference, with the template and its best lag marked
(`analysis/audio-bank/plots/`).

1. **Skye Guiding Light, `bdfdcf009dba` 1184.05 s**
   (`explain-bdfdcf009dba_1184050_E.png`). The demo `6ab7a9e99235` drops E at
   22.0 s and X at 22.5 s; the two references hold one sound. The match cast
   carries a harmonic screech that appears nowhere in either reference.
   `corr` names E by the shared onset; coverage finds the screech missing and
   drives `prod` toward zero. The reference, not the score, is wrong: the demo
   may hold one cast where the tray shows two drops, and the Seekers gain of
   [metric:audio_bank/transfer_ability_verified#Skye_X_gain_median=23.1] dB and
   Regrowth gain of
   [metric:audio_bank/transfer_ability_verified#Skye_C_gain_median=21.4] dB say
   those references hold a much quieter event than the match casts.
2. **Phoenix Blaze, `587c15b07779` 1472.05 s**
   (`explain-587c15b07779_1472050_C.png`). The true reference looks the same
   by eye: an onset, a descending harmonic ladder, then broadband crackle. Hot
   Hands shares the onset, and the z-scored correlation rewards the contrast
   between silence and onset more than what follows. The 1.0 s template, meant
   to hold the crackle, did not change the verdict (R2).
3. **Sova Recon Bolt, `9acf02f98283` 732.05 s**
   (`explain-9acf02f98283_732050_E.png`). The match cast is a loud release with
   ringing pulses after it. The demo reference (`02cf738b1c8f` 14.5 s) was cast
   while moving, its drop 0.5 s before two Shock Bolt drops, and its cast
   template sits on footsteps. Owl Drone's clean onset wins. The Shock Bolt gain
   of [metric:audio_bank/transfer_ability_verified#Sova_Q_gain_median=-12.0] dB
   fits the same demo: its Shock Bolt references hold something louder than the
   match casts. I guess the Recon Bolt release; the player can say.

The sheets `sheet-demo_bank.png` and `sheet-match_windows.png` show every
window of a set at once.

## What was falsified

- The declared score (`prod`, 0.6 s, cast template) does not name the player's
  abilities in matches: it barely beats the majority slot (B4, B12).
- The demo reject class is not a null. Tray-quiet windows score above the true
  class (B3), likely because infinite abilities fire without a drop and those
  windows share the recording with the references. A refusal threshold drawn
  from it rejects almost everything, casts included (B8).
- The threshold does not admit match noise, as feared (B7); it is conservative.
- A longer template does not separate abilities that share an onset (R1-R3).

What survives: a clean reference transfers. Owl Drone, Trailblazer, Ruse and
Curveball each name most of their verified casts under `corr`, and the
failures trace to references cut from contaminated demo drops, not to the game
changing the sound between a demo and a match. Audio remains a candidate
second witness to the tray, not a reader.

## What could not be done

- Separate co-occurring demo drops. Which of two drops half a second apart was
  the cast needs the viewmodel, and this run decodes no video; the player can
  answer it faster.
- Use the demos without a cast cache: `2ba870ccbd50` (Brimstone) and
  `79a706a7ce4c` (Cypher) contribute nothing, and `29eff6920e8f` and
  `afa5bc60b935` only the five ledger-named casts. The spectator Cypher demos
  lost every drop to the tray-switch filter.
- Score Clove's Pick-me-up and Not Dead Yet, which no demo casts.
- Use the stereo difference, which `audio_channel` found marks self sounds.
- Find an independent equip witness for the templates. The ammo counter
  vanishes while an ability is held [domain:abilities/ammo-hidden-while-non-gun-held],
  which would place the equip without the tray; it needs a HUD read this run
  did not make.

## Questions only the player can answer

1. Skye demo `6ab7a9e99235`: which abilities did you cast at 22 s and at 28 s?
   The tray drops E and X together at 22.0/22.5 s, and C and X together at
   28.0 s.
2. Sova demo `02cf738b1c8f` 14.5-15.5 s: was that one Recon Bolt, then one or
   two Shock Bolts, while moving?
3. Would you record Sova, Phoenix, Skye and Clove to the Omen protocol
   (`b9558488a607`): standing still, casts spaced apart, equip-hold-cast, three
   casts of each ability including Pick-me-up and Not Dead Yet? Clean
   references are the one change the results point to.
4. Does your game volume or audio mix differ between the demos and the
   matches? The median gain says no, but the spread per cast is wide.
