# Reticle handoff paragraphs retired from the ability-identification branch on 2026-09-27

Moved out of `NOTES.md` when it passed its word limit; the metric tokens and
facts were current when written.

**The audio gate (2026-09-27).** `prototypes/audio_gate.py` scores five formulations leave-one-session-out on 20 matches with labels mined from HUD reads ([results](docs/AUDIO_GATE.md)). Gunfire mined from the ammo counter is louder than background on [metric:audio_gate/p0@all-matches#sessions_louder=20] of 20 sessions by [metric:audio_gate/p0@all-matches#diff_db_median=17.97] dB. The best gate, a logistic regression, finds [metric:audio_gate/loso@all-matches#F2_recall_verified_at_3=0.483] of the 120 verified casts at 3 unexplained detections per live minute, duty cycle [metric:audio_gate/loso@all-matches#F2_duty_at_3=0.296], and [metric:audio_gate/loso@all-matches#F2_recall_verified_at_10=0.625] at 10, never 0.7; onset [metric:audio_gate/loso@all-matches#F2_onset_median_s=-0.05] s from the tray drop; it fires at both tray-blind demo casts. Loudness alone reaches [metric:audio_gate/loso@all-matches#F0_recall_verified_at_10=0.717] at 10; the AudioSet tagger is weaker. Own casts run [metric:audio_gate/labels@all-matches#casts_per_live_min=1.871] per live minute, so others' casts are the target: unexplained detections lean toward unnamed ally piece onsets ([metric:audio_gate/witness@all-matches#F2_unnamed_ally_piece_onsets_near=0.445] against [metric:audio_gate/witness@all-matches#F2_unnamed_ally_piece_onsets_chance=0.267] by chance), not pings or smokes. Six matches carry podcast speech: [metric:audio_gate/loso@all-matches#F2_unexplained_speech_fraction=0.29] of unexplained onsets. Verdicts in ledger `audio-gate`; declined for wiring. The player reviewed six unexplained rows, all allies' casts with their voice lines and reloads. Next: match the game's fixed voice-line and ability assets as templates [domain:abilities/voice-lines-announce-casts]; read the timer bar, cooldown counters and chat box [domain:hud/chat-broadcasts-callouts]; then a minimap change gate paired with this one for births of others' abilities.

## Moved from NOTES.md on 2026-09-27

**Ability shapes and the tray, wired (2026-09-26).** `reticle tray` stores the tray's drops from the crop cache (`tray-0.1.0`, from `prototypes/ability_hud.py`), and `ability_timeline.player_tray_casts` keeps the player's casts by phase, round (`rounds.in_round_window`) and first death. Sova's bow glows over the tray; the reader compares across a refusal of up to 3 s (`across_gap`). The player's Recon Bolt casts on Sova sessions rose from [metric:tray/port@tray-work-cache#sova_recon_casts_before=31] to [metric:tray/port@tray-work-cache#sova_recon_casts=65], and [metric:tray/port@tray-work-cache#labelled_casts_passing=119] of 120 labelled casts pass. `reticle ability-shapes` fits Regrowth's ring, Recon Bolt's ring and Hunter's Fury's line on each cached crop 0-6 s after those casts (`ability-shape-0.1.0`). On the player's marks it finds Fury [metric:ability_shapes/marks@tray-object-marks#fury_found=21] of 21, Regrowth [metric:ability_shapes/marks@tray-object-marks#regrowth_found=14] of 16, Recon Bolt [metric:ability_shapes/marks@tray-object-marks#recon_found=8] of 8, and [metric:ability_shapes/marks@tray-object-marks#pre_found=0] of 10 panels before a cast. Teal counts over the whole widget, since masking the void removed the bands that reject scenery. The Fury line shows on [metric:ability_shapes/production@all-sessions-player-cast-0.3.0#fury_found=223] of 247 crops after the drop and turns between them. The minimap refresh (`minimap-0.7.0`, 19 sessions) changed no found count, yet the self track stores single-frame gaps, so the nearest row left [metric:ability_shapes/production@all-sessions-seed100#seed_none=488] crops unseeded; the nearest position within 250 ms (`SEED_TOL_MS`) leaves [metric:ability_shapes/production@all-sessions-player-cast-0.3.0#seed_none=223], found unchanged; the Fury angle is within 3 deg on [metric:ability_shapes/marks@tray-object-marks#fury_angle_3deg=19] of 21 (14 before); a bridged Recon Bolt drop 0.5 s earlier refuses the labelled Shock Bolt at `75a55a296d3b` 274.1 s, and 10 unlabelled casts. Outcomes: `ability-shape-fit`, `tray-guard-gap`.

From the voice-lines paragraph, moved 2026-09-27: A per-agent cast window (Phoenix's line 20 s before its drop) lifts own recall to [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#own_recall_agent_window=0.844] (ledger `voice-lines`); cross-template suppression is declined, since at the same false-alarm rate it drops [metric:voice_lines/suppression-0.2.0-F-B@all-matches#removed_possible_alone=36] lone detections and [metric:voice_lines/suppression-0.2.0-F-B@all-matches#own_hits_lost=4] tray-witnessed own lines;

From the voice-lines paragraph, shortened on 2026-09-27 (later); the sentences as they stood:

- ; the threshold holds out: picked on one half and scored on the other, [metric:voice_lines/heldout-0.1.0@all-matches#heldout_impossible_per_min_a=0.0976] and [metric:voice_lines/heldout-0.1.0@all-matches#heldout_impossible_per_min_b=0.1101] impossible per live minute, so 0.0443 stays.

- and the gate (`player-cast-0.2.0`) keeps the kit through a Run it Back death the badge votes a second life and a Clove death her revive entry follows:

- [metric:ult_lines/ult-cast@all-sessions-player-cast-0.4.0#own_beside_refused_cooccur_among_casts=6] lie beside drops refused as co-occurring and [metric:ult_lines/ult-cast@all-sessions#own_beside_refused_after_player_death=4] beside a death the killfeed missed or no badge read undid.

- The X bar lights only when the ult is castable [domain:abilities/ult-slot-lights-when-castable] (player).

- The player's review ([doc](docs/VOICE_LINES.md)): every row below or beside the threshold is no ult line, as the scores predicted (an ult-ready line, speech, a drone).

From the voice-lines paragraph, shortened on 2026-09-27 (evening); the sentences as they stood:

- while her enemy cast template scores [metric:ult_ready_lines/heard@c40d950031bb#killjoy_cast_enemy_score=0.0574]

- The shape refits kept every found count (G3, G6).

- [metric:voice_line_harvest/ult-ready@wiki#agents_with_ult_asset_covered=28] of 28

- onset [metric:voice_lines/evaluate-F-B@all-matches#onset_median_s=-0.43] s from the drop with interquartile range [metric:voice_lines/evaluate-F-B@all-matches#onset_iqr_s=0.442]

- The player's review: every row below or beside the threshold is no ult line ([doc](docs/VOICE_LINES.md)).

- The restamp under 0.5.0 reproduces the recount and adds [metric:ability_shapes/production@all-sessions#casts_added=36] shape casts; Recon Bolt draws on [metric:ability_shapes/production@all-sessions#added_recon_found_frac=0.333] of their crops against [metric:ability_shapes/production@all-sessions#old_recon_found_frac=0.292] before (R1 failed only on its mixed baseline).

- the four were added teal over an unlit slot

- from [metric:ult_lines/ult-cast@all-sessions-player-cast-0.1.0#own_witnessed=37]

- (`ability-shape-0.1.0`); on the player's marks Fury [metric:ability_shapes/marks@tray-object-marks#fury_found=21] of 21, Regrowth [metric:ability_shapes/marks@tray-object-marks#regrowth_found=14] of 16, Recon Bolt [metric:ability_shapes/marks@tray-object-marks#recon_found=8] of 8.

- The [metric:ult_lines/x-fill@all-sessions#x_casts_with_line=46] X casts with a line fall from fills of [metric:ult_lines/x-fill@all-sessions#with_line_from_min=0.9] or more; the 4 from part-filled slots have none; X casts only from a full slot [domain:abilities/ult-charge-pips], so `player-cast-0.3.0` refuses an X drop from a fill under 0.80 (`partial_charge`): in-round X casts [metric:ult_lines/ult-cast@all-sessions-player-cast-0.3.0#x_casts=50] from 54, casts with a line [metric:ult_lines/ult-cast@all-sessions-player-cast-0.3.0#x_casts_with_line_fraction=0.92] (G4).

- `player-cast-0.4.0` refuses a drop that leaves its slot at 0.75 or more (`equip_release`, [metric:tray/equip-release@all-sessions#equip_release=75] of 493) and an X drop that leaves pips lit (`pips_lit`, 2): in-round X casts [metric:ult_lines/ult-cast@all-sessions-player-cast-0.4.0#x_casts=48], casts with a line [metric:ult_lines/ult-cast@all-sessions-player-cast-0.4.0#x_casts_with_line_fraction=0.938], witnessed 45 unchanged (T1 held).

- Cross-template suppression is declined ([results](docs/VOICE_LINES.md)).

- The probe `1a090b300cf1` has its score floor within the desktop sessions' range (p99 [metric:ult_lines/probe@1a090b300cf1#score_p99=0.0327] against 0.029 to 0.040).

- The combined presence leaves [metric:scoreboard/openings@all-sessions#holes=1381] one-sample gaps that no witness sees a board in.

- `ult-cast-0.2.0` binds own lines to the tray's X casts, and the gate (`player-cast-0.2.0`) keeps the kit through Run it Back and a Clove revive: [metric:ult_lines/ult-cast@all-sessions-player-cast-0.4.0#own_witnessed=45] of 58 have an X cast; [metric:ult_lines/ult-cast@all-sessions-player-cast-0.4.0#own_beside_refused_cooccur_among_casts=6] lie beside co-occurring refusals and [metric:ult_lines/ult-cast@all-sessions#own_beside_refused_after_player_death=4] beside a missed death.

- A two-charge slot draws two segments [domain:hud/ability-tray-charge-segments] and reads as halves ([metric:tray/segments@all-sessions#half_from_full=89] drops full to half, [metric:tray/segments@all-sessions#empty_from_half=43] half to empty, of 155 accepted); [metric:tray/segments@all-sessions#full_after=68] of 493 accepted drops leave the slot full, an equip released, and the Fury line shows on [metric:tray/full-after-shapes@all-sessions#fury_full_after_found=3] of 13 crops after one.

- Of the 120 labelled drops 94 pass: refused are 21 that drew nothing, two X drops from part-filled slots, the bridged Shock Bolt, and two objects (`b3b9defb6fd7` 1627.0 s, `e37fdeca944f` 364.6 s), stored as disagreements.

- Ult-ready lines, harvested and scored ([doc](docs/ULT_READY_LINES.md)): the wiki holds one per agent, a radio reply [domain:abilities/ult-ready-line-is-a-radio-reply]. Allies' templates fire [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_ally_to_absent=8.37] times the absent rate, but [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_collide=93] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ready=261] ready onsets also fire a cast template, and at the one labelled line (`c40d950031bb` 678.1 s, Killjoy by the player) her take ranks [metric:ult_ready_lines/heard@c40d950031bb#killjoy_rank=17] of 29: the scorer fails its one label. The line is voiced unprompted when the charge fills [domain:abilities/ult-ready-lines], so next store the tray's X fill and score own ready lines against it.
