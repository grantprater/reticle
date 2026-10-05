"""Version stamps written into every stored row.

Per the design doc (SS7): every row carries the versions that produced it, so
rows can be attributed to a definition and selectively recomputed later.

Bump EXTRACTOR_VERSION when the meaning of any primitive column changes --
that invalidates cached L1 and forces a re-decode. Bump SEGMENTER_VERSION for
changes to span logic only; that recomputes from stored L1 without touching
video.
"""

SCHEMA_VERSION = 1
# 0.2.0 (2026-09-07) moved the round START to the clock RESET. It used to be
# the previous round's score increment, which is ~6 s before that round's
# clock expires -- measured at a median of exactly 6.0 s on 17 of 18 sessions
# over 281 rounds, with the roster putting the real start 7.0 s later at a
# buy-phase clock of 28 s. The END did not move, so rounds are no longer
# contiguous and the gap between them is the post-round period. Every stored
# round carries `start_source`, so one built by the old contiguous rule cannot
# read as current. See `rounds.round_bounds` and `docs/ROSTER_FINDINGS.md`.
# 0.3.0 (2026-09-24): an event first seen at a round's exact end belongs to that
# round (it is the decisive event); `a <= t < z` dropped 25 of the player's
# deaths and 12 kills over the 17 KNOWN_KD sessions.
# 0.4.0 (2026-09-24): events run to the next round's buy-phase snap
# (`t_close_ms`), since post-round kills count [domain:rounds/post-round-period].
# 0.5.0 (2026-09-24): a final round the scoreline never closed is inferred from
# the match-end rule (`end_source = match_end_rule`).
# 0.6.0 (2026-09-24): a player death carrying the second-life badge is a
# second life, not a death (`player_second_lives`), where badge reads exist.
# 0.7.0 (2026-09-24): a player kill or death entry split into two tracks is
# counted once (`checks.merge_split_tracks`).
# 0.8.0 (2026-10-02): a plant is the planted-spike graphic (`plant_graphic`)
# seen on two consecutive samples with the clock unread, not an unread-clock run
# of at least 7 s; one sample, or no graphic rows in the round, stores
# `spike_planted` null with `plant_reason`. Without a current `plant_graphic`
# stream the old run rule still marks a plant (`plant_source = clock_run`) and
# every other round is null, never False. Over the 21 Riot-scored matches:
# plants found by both 212 -> 251, Riot only 68 -> 27, store only 8 -> 0.
# 0.9.0 (2026-10-04): a round whose buy-phase reset went unread starts one
# median post-round gap after the previous end (`start_source = post_round_gap`,
# `rounds.place_unread_starts`), not at the score increment, so the previous
# round closes there and keeps its post-round events. Over the 21 Riot-scored
# matches the 7 post-round deaths stamped with the next round all move to their
# own round; no other death moves; 89 of 439 starts move 7-8 s later.
# 0.10.0 (2026-10-05): where the last clock reading before a round's end is
# stale (a stored plant_graphic sample between it and the next reading, or the
# two more than ROUND_START_JUMP_MS apart) and no upward jump is read, the next
# round starts at the first buy-phase reading after the end
# (`start_source = buy_clock_after_unread`). 76 of the 89 post_round_gap starts
# on the 21 Riot-scored matches become read starts; no clock_reset start moves.
ROUND_VERSION = "round-0.10.0"
# The planted-spike graphic in the scoreline's clock field, read from the hud
# crop cache (`plant_graphic`). 0.1.0 (2026-10-02): red coverage of the clock
# field less twice its white ink, cut at 0.2.
PLANT_GRAPHIC_VERSION = "plant-graphic-0.1.0"
# Coaching bundle. 0.2.0 (2026-09-24): rounds apply the second-life gate, and
# each event carries its round's combat report verdict (`round_verdict`).
# 0.3.0 (2026-09-30): kills and deaths are the death owner's `death_verdict`
# events, and each event's round is `rounds.round_containing`'s, not `t < t_end_ms`.
COACH_VERSION = "coach-0.3.0"
# Pure credit-ledger rules and interval semantics. This does not stamp a credit
# detector: no such observation channel exists yet.
# 0.2.0 (2026-10-04): an overtime reset assigns `overtime_credits` (5000), not
# the pistol bank (800); Riot's records open every overtime round at 5000.
ECONOMY_VERSION = "economy-0.2.0"
# Context-free Tab-scoreboard row observations: K/D/A, credits, highlight,
# geometry, portrait composition and raw agent-art scores. Identity is
# adjudicated downstream.
# 0.2.0: the portrait box is the square cell at the table's left edge (the old
# trough locator landed inside the slab); raw agent-art scores and gain added.
# 0.3.0: every agent's score per row, for a side assignment downstream.
# 0.4.0: the enemy block is searched for only below the ally block.
# 0.5.0: a board whose anchored enemy rows overlap the ally rows is not read.
# 0.6.0: portrait art scores in float64 on the GPU when cupy is present; the
# coverage row names the scorer. Against OpenCV's float32, 9 of 4640 rounded
# scores on 7010b3d62460 differ by at most 0.0007; best agent and gain agree
# on 160 of 160 rows, margin on 159. Over the whole session's stored rows,
# 1033 of 95294 rounded scores differ, 6 by more than 0.001 and at most by
# 0.0047, all on weak non-best scores near 0.14; best agent and gain agree
# on 3310 of 3310 rows, best score on 3244, margin on 3220. a06f04a0059f:
# 2163 of 182439 differ, at most 0.0036; best agent on 6330 of 6330 rows,
# second agent on 6328, gain on 6329. 043bafca271a: 480 of 205262, at most
# 0.0010; best agent on 7120 of 7120, gain on 7119.
# 0.7.0: one `sample` row per frame offered, open or closed, naming the test
# that closed it (`scoreboard.CLOSE_REASONS`); the coverage row counts them.
# No verdict changes.
# 0.8.0: where the round-history strip witness reads present, the blocks are
# the slab runs that meet its marker lines, not the tallest runs; a block the
# strip does not bound is refused (`green_not_at_strip`, `red_not_at_strip`,
# `red_short_at_strip`). Absent or unreadable strip: 0.7.0 exactly. Sample
# and row events carry `anchor`, `strip` and `edges`. One decode of
# [metric:scoreboard/anchored@a06f04a0059f#frames_decoded=300] frames of a06f04a0059f
# (docs/SCOREBOARD_PRESENCE.md, "Anchoring on the strip"): of 100 boards the
# strip saw and 0.7.0 closed, [metric:scoreboard/anchored@a06f04a0059f#closed_present_opened_five_each=70] open, all at the board.
# Of 100 it opened, [metric:scoreboard/anchored@a06f04a0059f#open_present_off_board_before=55] had enemy rows off the board:
# [metric:scoreboard/anchored@a06f04a0059f#open_present_off_board_moved_onto_board=35] now sit on it (portrait median
# [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_portrait_median_before=0.518] -> [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_portrait_median_after=0.91]) and
# [metric:scoreboard/anchored@a06f04a0059f#open_present_off_board_refused=20] are refused. Of [metric:scoreboard/anchored@a06f04a0059f#open_present_at_board_before=45] at the
# board, [metric:scoreboard/anchored@a06f04a0059f#open_present_at_board_changed=3] are refused where the enemy slab's top rows fail
# the red test and the rest are unchanged. Frames without the strip:
# [metric:scoreboard/anchored@a06f04a0059f#absent_equal_070=100] of 100 unchanged.
# 0.9.0: where no red run begins at the strip's lower line, the line still
# places the enemy rows, and a red run over half the ally height inside that
# span (`red_overlap`) or all five portraits scoring at least 0.81
# (`portraits`) confirm them; sample and row events carry `confirm`. On the
# same selection (docs/SCOREBOARD_PRESENCE.md, "The line places, the slab
# confirms"): of [metric:scoreboard/line-confirm@a06f04a0059f#closed_present_refused_at_strip_before=26] + [metric:scoreboard/line-confirm@a06f04a0059f#open_present_refused_at_strip_before=23] boards 0.8.0 refused at
# the strip, [metric:scoreboard/line-confirm@a06f04a0059f#recovered=45] open, all at the board; the other [metric:scoreboard/line-confirm@a06f04a0059f#still_refused=4] have a wrong
# table left edge. Every board 0.8.0 opened is unchanged ([metric:scoreboard/line-confirm@a06f04a0059f#closed_present_before_open_unchanged=70] +
# [metric:scoreboard/line-confirm@a06f04a0059f#open_present_before_open_unchanged=77]), and no strip-absent frame changes ([metric:scoreboard/line-confirm@a06f04a0059f#absent_changed=0]).
# 0.10.0: where the strip's rectangle is known, the table's left and right
# edges are its frame, the two colour steps TABLE_W apart near the place the
# strip's centre predicts (`scoreboard._frame_edges`), not the green test's
# dense columns; a board without that frame closes as `no_table_frame`. On
# the fixture of decoded boards (docs/SCOREBOARD_PRESENCE.md, "The table's
# frame"), held-out sessions: both edges right on
# [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_edges_right_after=68] of [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_n=71] boards the dense columns misplaced,
# the other [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_closed_no_frame=3] closed and showing no board; the gate accepts
# [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_accepted_after=49] of them, against [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_accepted_before=2]. No correct board changes a row or a
# verdict ([metric:scoreboard/table-frame@fixture#holdout_ok_rows_changed=0] of [metric:scoreboard/table-frame@fixture#holdout_ok_n=50]); its edges move at most [metric:scoreboard/table-frame@fixture#holdout_ok_edge_shift_max_px=2] px.
# 0.11.0: where the strip's rectangle is known, the row test counts slab
# pixels only in the table's columns (`scoreboard.table_columns`, frame x
# 572-1347), not across the whole frame, so green or red world beside the
# board no longer moves the rows; every pixel read lies in
# `scoreboard.reader_roi` (frame x 535-1382). On the decoded boards
# (docs/SCOREBOARD_PRESENCE.md, "The table's rows"): each reads the same
# pasted into black inside that region
# ([metric:scoreboard/table-rows@fixture#roi_equal=456] of [metric:scoreboard/table-rows@fixture#boards=456]); against 0.10.0 the rows move onto
# the table on [metric:scoreboard/table-rows@fixture#better_on_table=47] boards and [metric:scoreboard/table-rows@fixture#better_no_board_closed=4] opens with no board close,
# while [metric:scoreboard/table-rows@fixture#worse_closed=5] boards read at the table close over a dull world.
# 0.12.0: the GPU scores portraits in float32, on the window shifted by its
# integer per-channel mean, not in float64; the coverage row names
# `cupy-float32`. On the decoded boards (docs/SCOREBOARD_PRESENCE.md,
# "Portrait scoring time") no board changes a verdict, an edge, a row or a
# named agent ([metric:scoreboard/speed-float32@fixture#bar_changed_boards=0] of [metric:scoreboard/speed-float32@fixture#boards=456]);
# [metric:scoreboard/speed-float32@fixture#rounded_scores_differ=19] of [metric:scoreboard/speed-float32@fixture#rounded_scores=115420] rounded scores move, by
# at most [metric:scoreboard/speed-float32@fixture#max_score_diff=0.0001].
# 0.13.0: one CUDA kernel scores every portrait of a frame, with exact
# integer masked sums and a float64 finish, so a window's scores no longer
# depend on the batch; the coverage row names `cupy-exact`. Every decoded
# board reads as 0.11.0 read it, portrait scores included
# ([metric:scoreboard/speed-batch@fixture#boards_identical_float64=456] of [metric:scoreboard/speed-batch@fixture#boards=456]); against 0.12.0 no board
# changes a verdict, an edge, a row or a named agent
# ([metric:scoreboard/speed-batch@fixture#bar_changed_boards=0]), and the [metric:scoreboard/speed-batch@fixture#rounded_scores_differ=19] rounded scores
# 0.12.0 moved move back.
SCOREBOARD_VERSION = "scoreboard-0.13.0"
# Stored versions whose accepted openings the current reader does not
# contradict. A consumer of VERDICTS (the lineup constraining its top bar by
# the board) accepts these; `reticle plan` still names the rescan. 0.7.0 adds
# rows and a reason and changes no verdict, so without this the bump refused
# the board on every stored session and named 122 of 190 lineup slots.
# 0.8.0 rewrites the enemy rows of most boards 0.7.0 opened off the board,
# and the openings gate refuses those boards: every accepted stored opening
# on the 19 lineup sessions ([metric:scoreboard/stored-openings@all-sessions#accepted_at_board=6018]) has its enemy rows at
# the board, [metric:scoreboard/stored-openings@all-sessions#accepted_off_board=0] off it. At the accepted ones in the sample,
# 0.8.0 writes the same rows on [metric:scoreboard/anchored@a06f04a0059f#stored_accepted_same=41], the same reads 6 px higher on
# [metric:scoreboard/anchored@a06f04a0059f#stored_accepted_moved_same_reads=1], and refuses [metric:scoreboard/anchored@a06f04a0059f#stored_accepted_refused_now=3]; it names no other agent in any. So
# 0.6.0 and 0.7.0 stay applied, and the openings 0.8.0 adds wait for the
# rescan. 0.9.0 opens only boards 0.8.0 refused and changes none it opened,
# so 0.8.0 is compatible too; it reads the three accepted openings 0.8.0
# refused again ([metric:scoreboard/line-confirm@a06f04a0059f#stored_accepted_recovered=3]), with 0.7.0's rows or the same reads 2 px lower.
# 0.10.0 moves the edges of boards 0.9.0 read with the right edges by at most
# 2 px and refuses no opening 0.9.0 accepted ([metric:scoreboard/table-frame@fixture#fit_accepted_lost=0] + [metric:scoreboard/table-frame@fixture#holdout_accepted_lost=0] lost on the
# fixture), so 0.9.0 stays applied. 0.11.0 names the same agent in every
# row of every board both versions accept ([metric:scoreboard/table-rows@fixture#accepted_both_same_agents=335] of
# [metric:scoreboard/table-rows@fixture#accepted_both=335]), and the [metric:scoreboard/table-rows@fixture#accepted_lost=5] accepted openings it refuses sit at the
# board, so 0.10.0 stays applied. 0.12.0 changes only the fourth decimal of
# a few scores and no verdict or agent ([metric:scoreboard/speed-float32@fixture#bar_changed_boards=0] boards
# change), so 0.11.0 stays applied. 0.13.0 moves the same fourth decimals
# back and changes no verdict, so 0.12.0 stays applied.
SCOREBOARD_VERDICT_COMPATIBLE = ("scoreboard-0.6.0", "scoreboard-0.7.0", "scoreboard-0.8.0",
                                 "scoreboard-0.9.0", "scoreboard-0.10.0", "scoreboard-0.11.0",
                                 "scoreboard-0.12.0", SCOREBOARD_VERSION)
# TESTING-PHASE WAIVER, TO REVISIT: stored stamps that `reticle plan` (and
# every rerun input check inside it) accepts as the current stamp, as
# {(current, stored): why}. The player decided on 2026-09-29, to iterate
# quickly, that the scoreboard streams his rescan wrote at 0.12.0 count as
# current under 0.13.0, with no rescan; later sessions of that rescan run at
# 0.13.0. Against 0.12.0, 0.13.0 changes no verdict, edge, row or named agent
# on any of the [metric:scoreboard/speed-batch@fixture#boards=456] decoded boards
# ([metric:scoreboard/speed-batch@fixture#bar_changed_boards=0] change), and only
# [metric:scoreboard/speed-batch@fixture#rounded_scores_differ=19] of
# [metric:scoreboard/speed-float32@fixture#rounded_scores=115420] rounded portrait scores
# differ, by at most [metric:scoreboard/speed-float32@fixture#max_score_diff=0.0001].
# The key names the literal current stamp, so the waiver lapses at the next
# bump; a waived stamp must already be verdict-compatible. `plan` names each
# stream it accepts here as accepted by waiver, never as current. Stored
# stamps stay as written: they record the code that wrote them.
#
# A waiver whose equivalence holds only on some sessions is a dict: `why`, and
# `when`, the name of a per-session condition `plan.WAIVER_CONDITIONS`
# evaluates over the stored data. It accepts only where the condition holds;
# where it fails or cannot be evaluated (no session given, an unknown
# placement) the stamp stays stale, and `plan` names the waiver it declined.
#
# The player approved on 2026-10-04 ("stamp waiver") that stored
# ally-icon-0.11.0 rows count as ally-icon-0.12.0 on sessions whose minimap
# placement is upright, so the cached ally-icon rerun then writing 0.11.0
# rows need not run again. 0.12.0 differs from 0.11.0 only where
# `widget_frame.turned_at` says the stored placement is turned, so it holds
# only where `widget_frame.upright_throughout` is True; side-based sessions
# with a turned half (4f207c0c4e39, b3b9defb6fd7) and side-based sessions with
# no stored placement (0f08b3dc3777, declared per_side) stay stale. Read in
# memory from the crop cache over one two-minute window each, 0.12.0 and
# 0.11.0 wrote the same rows, stamps and the stamp-bearing candidate revision
# aside: [metric:ally_icon_waiver/equivalence@043bafca271a#differing_rows=0] of
# [metric:ally_icon_waiver/equivalence@043bafca271a#rows=4202] rows on 043bafca271a,
# [metric:ally_icon_waiver/equivalence@223d636bf8d2#differing_rows=0] of
# [metric:ally_icon_waiver/equivalence@223d636bf8d2#rows=4472] on 223d636bf8d2 and
# [metric:ally_icon_waiver/equivalence@587c15b07779#differing_rows=0] of
# [metric:ally_icon_waiver/equivalence@587c15b07779#rows=3755] on 587c15b07779,
# stacked members among them
# ([metric:ally_icon_waiver/equivalence@043bafca271a#stack_rows=429],
# [metric:ally_icon_waiver/equivalence@223d636bf8d2#stack_rows=323] and
# [metric:ally_icon_waiver/equivalence@587c15b07779#stack_rows=291] rows).
STAMP_WAIVERS = {
    ("scoreboard-0.13.0", "scoreboard-0.12.0"):
        "player 2026-09-29: testing-phase waiver, no rescan; 0.13.0 changes no verdict",
    ("ally-icon-0.12.0", "ally-icon-0.11.0"): {
        "why": "player 2026-10-04 (\"stamp waiver\"): 0.12.0 turns portraits back only "
               "where the stored placement is turned, so an upright session reads the "
               "same rows",
        "when": "upright_placement",
    },
}
assert all(stored in SCOREBOARD_VERDICT_COMPATIBLE
           for current, stored in STAMP_WAIVERS if current.startswith("scoreboard-"))
# The round-history strip as a second presence witness of the Tab board, read
# by `scoreboard_strip` from the hud crop cache's `center` crop and written as
# `scoreboard_strip` rows by `reticle strip`. 0.1.0 ports the rule and
# constants of `prototypes/scoreboard_strip.py` at its 0.2.0.
SCOREBOARD_STRIP_VERSION = "scoreboard-strip-0.1.0"
# The round-end icon in each cell of the Tab board's round-history strip, read
# by `round_outcome` from the scoreboard crop cache on frames the strip witness
# reads present, and written as `round_outcome` rows by `reticle round-outcome`.
# 0.1.0 (2026-10-03): the build's four MatchOutcomes alphas at the widget's
# 19-unit slot, INTER_AREA, against soft colourfulness; columns fitted from the
# strip witness's marks and checked against the widget JSON's inset.
ROUND_OUTCOME_VERSION = "round-outcome-0.1.0"
# How each round ended, pooled from the `round_outcome` cells by
# `adjudication.round_outcome` and written as `round_outcome_claim` rows.
# 0.1.0 (2026-10-03): column N is the stored round with score_us + score_them
# = N - 1; only frames after the stored round end vote; at least 2 votes and
# 80% agreement on reason and line, else a refusal with the votes kept.
ROUND_OUTCOME_CLAIM_VERSION = "round-outcome-claim-0.1.0"
EXTRACTOR_VERSION = "l1-0.1.0"
SEGMENTER_VERSION = "seg-0.3.0"
# 0.3.0 (2026-10-04): `in_match` is HUD chrome alone; the minimap-change term
# gated on an outcome and labelled HUD-present stretches `off`. Minimap readers
# read `segment.READ_STATES` (idle and active), and record the spans' stamp.
# Stage 02 deterministic HUD extraction. Bump when glyph segmentation, the
# template set, or field parsing changes -- that invalidates stored HUD reads
# and forces a re-decode, since this stage needs pixels.
# 0.13.0 (2026-09-25): the killfeed divider prefers line art, so the
# weapon-slot box, and with it `kf_*_wx`, moves off pale plates and portraits.
# 0.14.0 (2026-09-25): `kf_ally_mask` / `kf_enemy_mask` read the killer's
# plate colour behind the weapon icon, not the last run past it.
# 0.15.0 (2026-09-26): `kf_same_side_mask` stores the slots whose killer
# plate reads the victim's side, the one-colour banner a revive draws.
# 0.16.0 (2026-09-28): `killfeed._join_split_runs` rejoins an entry whose plate
# run broke in two at its text rows. The entry stack gains the samples it was
# missing, so track onsets move earlier (c40d950031bb's player death, 703.5 s
# to 701.0 s) and `kf_*` columns change where a split entry stood.
# 0.17.0 (2026-10-02): `_band_text` admits ability icons it refused as `no_icon`: knife-sized
# pieces of any tint and joined thin strokes (`_stroke_groups`), gated on the plate seam.
# Ability-kill entries enter `kf_entry_mask`.
# 0.18.0 (2026-10-02): a killfeed divider piece inside a fitted ring grows to
# the ring's pieces (`_grow_strokes`, `ring_fit`), so a ringed icon's `kf_*_wx`
# holds one column, not whichever piece won, and its emblem is no name.
# 0.19.0 (2026-10-03): one-colour bands (spike, self and team kills, Not Dead Yet
# expiries) are entries when an icon at an entry's spacing divides two names
# on plate (`_one_colour_bands`, `_plate_flanks`); a thin-stroked icon (Paint
# Shells) divides by the plate-relative cut (`_soft_stroke_groups`).
# `kf_dropped_bands` and `kf_dropped_band_reason` store each refused band's
# reason, which only the census held.
# 0.20.0 (2026-10-03): `killfeed.PITCH` is 39, the game's row (34) plus
# spacer (5) [domain:killfeed/entry-list-layout], not 40: a tall plate run
# splits into bands on the game's grid and `absolute_slot` names slots by it.
# (0.19.0 belongs to one-colour-band-20261003.)
# 0.21.0 (2026-10-04): the clock, both scores, health, shield and magazine
# read digit templates rendered from the game's DIN Next font files at each
# widget's size (`ocr.game_font_templates`) [domain:hud/digit-fonts], not the
# 44 mined ones; the reserve keeps the mined set (`ocr.RESERVE_FONT`). Those
# fields match every glyph against every template at once
# (`Templates.match_many`), with margins from exact pixel sums, so a margin
# of 12/240 passes the 0.05 cut. A number with a leading zero refuses, and so
# does a field whose digits' tops and bottoms both spread over 2 px. The
# guards bind the mined reserve too: on 043bafca271a they refuse 15 stored
# reserve reads of 0, each a '00' misread of 100
# [metric:game_font_digits/compare_production@043bafca271a#ammo_reserve_lost=15].
# On the tuning sessions they refuse seven stored health reads of 0 where the
# HUD shows 20 or 100 [metric:game_font_digits/tuning_guards#hp_stored_zero_refused=7].
# Held out, no stored value changes to another value
# [metric:game_font_digits/compare_production@3694746e4e54#hp_changed=0]
# [metric:game_font_digits/compare_production@c40d950031bb#hp_changed=0];
# the margins of about 600 templates drop lone 0s in the clock and scores
# [metric:game_font_digits/compare_production@c40d950031bb#score_right_lost=5]
# [metric:game_font_digits/compare_production@4f207c0c4e39#clock_ms_lost=4]
# (prototypes/game_font_digits.py compare --production).
# 0.22.0 (2026-10-05): the two score fields read white ink against their own
# plate (`ocr.score_field`): coverage (luma - plate) / (255 - plate) over a
# grey opening, cut hard at SCORE_INK_CUT into components (a cut that still
# decides which dim digits exist; BACKLOG.md carries its removal); each
# component's whiteness is scored (`ocr.ink_score`, the coverage-weighted
# mean coverage) and cut at SCORE_INK_MIN, where it becomes a glyph, a
# blocker or a faint neighbour; no raw-luma gate. Bright scenery behind the
# plate no longer fuses with the digits into masses refused as `occluded`;
# a plate too near white to show a digit refuses `low_contrast`, and a
# sub-ink component spanning a read digit's rows beside it refuses
# `faint_digit`. The clock keeps the 190 cut. `n_glyphs` counts the glyphs
# inside the three fields. Oversize score ink of any area blocks. All
# figures are in-sample: the rules were tuned on the 21 Riot-recorded
# matches. There score reads rise from 2ad32ef's 122257 to 162507
# [metric:scoreline_soft/riot-21-soft#reads=162507], with 79479 full reads
# [metric:scoreline_soft/riot-21-soft#full_reads=79479], none off Riot's
# score sequence [metric:scoreline_soft/riot-21-soft#full_off_riot=0]. On
# the fixed handful one old read changes, a correction
# [metric:scoreline_soft/handful-soft#changed=1], and 20 of 16016 become
# refusals [metric:scoreline_soft/handful-soft#lost=20]. A scoreline read
# costs 0.93 ms per frame on a06f04a0059f
# [metric:scoreline_soft/cost-soft#ms_a06f04a0059f=0.927] against 0.57 ms
# before [metric:scoreline_soft/cost-soft#ms_2ad32ef_a06f04a0059f=0.574]. Of the occluded score samples before the small-jump unread round
# starts, 141 of 163 read both scores
# [metric:scoreline_soft/unread-reset-windows-soft#both_read=141].
HUD_VERSION = "hud-0.22.0"
# 0.12.0: `kf_entries` no longer counts a plate-coloured band that holds no
# name text. Every killfeed entry carries two names, so a band we can see and
# that has no glyph-sized ink in it is not an entry -- and `_entry_bands` splits
# a tall plate run into round(h/PITCH) bands, which is how a respawn wipe
# painting both plate colours across the ROI manufactures three to six of them
# at once. The evidence was already computed and discarded; `kf_empty_bands`
# and `kf_empty_band_reason` now store it, so a wiped frame reads as unreadable rather
# than as empty or as six kills. Attribution is untouched by construction: a
# an empty band could only ever have been `unparsed`, never `kill` or `death`,
# so kf_player_kill/kf_player_death and every _wx and _ys column are unchanged
# and the K/D table in killfeed.py still stands. What moves is `kf_entries` and
# the entry stack derived from it.
#
# 0.11.0: every null field now carries WHY. `clock_reason`,
# `score_*_reason`, `kf_unparsed` and `kf_unparsed_reason` are new columns.
# A null with no reason beside it is a number nobody can act on, and the
# 33-60% clock read rate this stage has reported since it was built was
# exactly that -- six different guards reading identically. Landed BEFORE the
# corpus re-scan on purpose, so one decode picks up the schema and the
# hud-0.10.0 killfeed fixes together.
# Stage 02 minimap position tracking. Bump when self/ally detection, the
# floor mask, or the filtering constants (RUN_PX, GAP_MS) change -- raw
# positions are stored unfiltered, so a filter-only change does NOT need a
# version bump or a re-decode (see minimap.filter_track).
#
# 0.2.0: adopted `minimap.widget_drawn`. Frames where the widget is not
# rendered at all -- the death screen, and the M key -- are now stored with
# NULL positions instead of whatever `self_rings` found in the world behind it.
# This MOVES every stored minimap number and every figure derived from one; the
# validations that backed the track (xmark_eval, chokepoint_eval) were measured
# with those frames in and are re-run against it.
# 0.3.0: `floor_mask` was reconciled (`18b0912`). It had been defined twice with
# different behaviour since 2026-08-27 and the shipped reader ran the older
# branch; the gate is now `sat < 20` plus a largest-component rule, UNIONED with
# the tinted bomb sites, which are floor. Measured against the two paintings
# it goes 57.8% -> 78.8% IoU on Ascent at 100% recall.
#
# This bump is what the stamp is FOR and it was nearly missed: the note above
# says to bump when the floor mask changes, and the change landed a commit
# earlier without one. The stored track is built on the old gate, whose extra
# 13.7% of the widget on Ascent is 100.0% outside the painted map -- 878 stored
# self positions and ~8,400 ally candidates of pure phantom. Re-reading it is
# TABLED in BACKLOG.md, so this stamp is the thing that keeps the staleness
# visible in `reticle status` rather than resting on someone reading a note.
# 0.5.0: the shipped self reader now supplies fitted `self_icons` to
# `pick_self`, ranked by arc coverage, and never falls back to connected-
# component centroids. Broken arcs previously voted as separate icons with
# centres biased by roughly the ring radius. Position fits do not require a
# readable bearing, and candidates must touch the opaque slab. Every stored
# self position can move or become null, so this requires a re-decode.
#
# 0.4.0: `pick_self`'s nearest-to-previous gate is floored at the icon fit's
# own pair budget, `2 * FIT_ERR_PX`, and measures the elapsed time since the
# previous position was READ rather than the rate the reader was configured
# with. The gate was `RUN_PX * scale * step * 2` alone, which is 1.50 px at
# 60 Hz -- below the fit error it has to clear -- so the reader abandoned the
# track on 9.4% of consecutive steps at 60 Hz against 1.9% at 2 Hz. A higher
# rate scored WORSE, and the P3 tier comparison cannot rest on a reader that
# is non-monotonic in its own rate. The FLOOR binds only above ~22 Hz, where
# it crosses the run allowance at 44 ms; the elapsed-time half binds at any
# rate, but only on the frames that follow a widget-absent stretch. Measured
# over the frozen windows: 6.6% of native reads move, 0.9% at 15 Hz -- exactly
# its ten widget-absent frames -- and none at all at 10, 5 or 2 Hz.
#
# 0.6.0 adds `widget_drawn`. The reader has always KNOWN whether the widget was
# on screen -- it refuses the frame on exactly that test -- and it threw the
# answer away, writing the same NULL position for "nobody was looking" as for
# "the fit refused". Those are different facts: only the second is a detection
# failure, and only the first forbids a belief outright. `belief.resolve` had
# to conflate them, and the interim workaround recovered 2016 of 2676 by
# cross-referencing the ally channel. No detector changed, so positions are
# byte-identical to 0.5.0; this bump exists because the TABLE gained a column,
# and rows without it must read as unknown rather than as false.
MINIMAP_VERSION = "minimap-0.7.0"
# Minimap pings, emitted as EVENTS rather than per-frame rows. Bump when the
# hue bands, the size gates or the lifetime gate change. Events are rewritten
# whole per session, so this is a stamp for attribution rather than a cache
# key -- nothing skips a ping read on a version match, because pings ride a
# pass that was going to happen anyway and cost no decode of their own.
PING_VERSION = "ping-0.1.0"
# Ally icon descriptors, emitted as `ally_icon` EVENTS by
# `minimap.AllyIconReader` at 2 Hz. Its own stamp rather than a
# MINIMAP_VERSION bump: positions do not change, and a descriptor is an
# independent detector. Bump when the icon gate, the interior mask, the
# occluder rule or `ALLY_MAP_DIFF_MIN` changes.
# 0.2.0: the fit is seeded on `minimap.coverage_surface` rather than the
# blob centroid, so a fit no longer lands on the teardrop lobe; the barrier
# gate moved into `ally_icons` itself, and the interior is computed in a
# window around each fit.
# 0.3.0: every fitted hypothesis is stored under a candidate revision with a
# baseline appearance (no occluders); the accepted view's descriptor names the
# self and neighbor candidates it masked. Accepted rows are unchanged; the
# stamp moves because events now carry `candidate_key`, `family` and lineage.
# 0.4.0: selected icons carry `portrait_features` (`ally_portrait.portrait_features`:
# 3x3 Lab grid, native-scale edge-orientation histograms, horizontal profile)
# with `portrait_features_version`; accepted rows are otherwise unchanged.
# 0.5.0: each candidate stores the accepted spike glyphs within
# `spike.ON_GLYPH_PX` of it (`spike_glyphs`), and a fit that lands on one
# (`spike.on_glyph`) is neither the self occluder nor a described teammate;
# `ally_decisions` rejects it as `on_spike_glyph`.
# 0.6.0: every fit past the shape gate is posed by its teardrop (`teardrop.posed`:
# SelfConeReader for the self channel, IconPoseReader for allies, at the widget's
# scale): where it reads, its centre and facing replace the ring fit's in the glyph
# check, the separation, the portrait's pixels and alignment, and the published
# row; each fit keeps the ring fit's under `ring` and names its `pose` and
# `facing_source`. `ally_decisions` rejects `facing_unread` only where neither
# reader saw a lobe.
# 0.7.0 (2026-10-01): a teammate's teardrop continues its fit on the previous
# image (`teardrop.IconPoseReader`'s prior, ICON_POSE_PRIOR_VERSION) and searches
# in full only on surprise; each ally fit's `pose` records `search`, `surprise`,
# `rests_on` (the prior's candidate key) and, on the audit cadence, `audit`. The
# self channel still searches in full.
# 0.9.0 (2026-10-02): on a widget size whose self portrait takes the ring fit's
# centre (`teardrop.labelled_scale` False: 331 px) the self channel's teardrop is
# not fitted, since `self_portrait_pose` discarded its centre and facing there;
# its pose is `ring_fit` with `reason` `unlabelled_scale` and `ncc` None, where
# 0.7.0 kept the unused NCC and a refused fit's reason. Centres, facings and
# accepted rows are unchanged. Numbered above ally-ring-subpixel-20261001's 0.8.0.
# 0.9.1: where the self teardrop is fitted (465 px), it continues its fit on the
# previous image under the prior rule (`teardrop.SelfConeReader` given a frame
# index, ICON_POSE_PRIOR_VERSION 0.2.0); each self fit's `pose` records `search`,
# `surprise`, `rests_on` and, on the audit cadence, `audit`, as an ally fit's does.
# 0.9.2: a refused fit is a prior too (ICON_POSE_PRIOR_VERSION 0.3.0): the next
# image's fit near it searches locally, and a refusal there is stored with
# `search` `prior`, its `rests_on` and its reason.
# 0.9.3: a prior-searched fit whose local grid keeps the prior's pose refines
# from a finer compass step (ICON_POSE_PRIOR_VERSION 0.4.0).
# 0.11.0 (2026-10-04), merging two branches that each bumped 0.9.3 (stack-fit's
# 0.10.0 and game-spike's 0.9.4, neither stored): where the self icon is seen,
# the stored roster's capacity (`round_lifetimes.ally_capacity`) exceeds the
# frame's ring-fit teammates, and a window of teal holds more than one teammate
# draws, the stacked-icon search (`stack_fit`, STACK_FIT_VERSION) fits that
# window; each member is a candidate of channel `stack`, and `ally_decisions`
# (minimap-icon-decision-0.3.0) accepts a member the ring fits do not already
# hold, up to the capacity, as an ally icon with `origin` `stack_fit`. Frame rows
# carry `stack_reason`; ring-fit rows and their observation keys are unchanged.
# The spike glyph step (`spike.glyph_fits`, SPIKE_VERSION 0.3.0) draws the
# game's Minimap_BombIcon texture, so on-glyph flags may move.
# 0.12.0 (2026-10-04): where the session's stored widget placement is turned
# 180 degrees (`widget_frame.turned_at`), each aligned teammate portrait (ring
# fits and stacked members) is turned back before its features are taken, as
# `self_icon` and `minimap_objects` already do
# [domain:minimap/upright-icons-on-turned-map]. A turned frame row carries
# `turned`, and the coverage row `widget_turned_frames`; a session with no
# turned placement reads the same rows as 0.11.0.
ALLY_ICON_VERSION = "ally-icon-0.12.0"
# The stacked teammate icon search (`stack_fit`), ported from
# `prototypes/stack_fit.py` 0.2.0. 0.3.0: numpy in place of torch, the icons
# drawn at `ICON_ALPHA` instead of opaque, windows scored on each pose's
# covered pixels.
STACK_FIT_VERSION = "stack-fit-0.3.0"
# The minimap portrait feature families (`ally_portrait.portrait_features`). Bump when
# the alignment, the disc, `DISC_R` or any family changes: stored features and
# the calibration fitted on them go stale together.
ALLY_PORTRAIT_FEATURES_VERSION = "ally-portrait-features-1.0.0"
# The baked table of references rendered from minimap portrait art
# (`ally_portrait.build_references`) under its stored calibration. Bump when
# the renderer or the table layout changes.
ALLY_PORTRAIT_REFS_VERSION = "ally-portrait-refs-1.0.0"
# Light evidence at each ability candidate's instant, written as `ability_light`
# EVENTS by `reticle ability-light`: `lighting.raw_lit` and `lighting.raw_dark`
# packed per frame. It stores no decision; `adjudication.ability` reads it.
# 0.2.0: stores raw_dark alongside raw_lit to distinguish opaque objects from viewcones.
ABILITY_LIGHT_VERSION = "ability-light-0.2.0"
# The team's adjudicated vision per frame, written as `team_vision` rows by
# `reticle vision` from the minimap crop cache: every tracked icon's resolved
# bearing and lifecycle eligibility, and the packed union of the eligible cones
# (`observable`) beside the union of all tracked bearings (`observable_all`).
# The chain is `team_vision.TeamVision`, the one `overlay` draws.
# 0.2.0: the self cone starts at the teardrop's centre (`teardrop`, TEARDROP_VERSION)
# where the shape reads, else at the ring fit's centre; each self icon records which.
# 0.3.0: the self cone faces the teardrop's facing where the shape reads, else the
# track's resolved lobe; the stored self icon's `self_cone` names both sources.
# 0.4.0: rays stop at the geometry's occluder table (`occ`: the static's white-line
# walls and its closed boxes, reticle/occluders.py) where the npz carries it;
# the coverage row names the table's stamp as `occluders` (None: art box edges only).
# Each icon also records `boxes_crossed`, the boxes its cone would pass with boxes open.
# 0.5.0: every icon's centre and facing come from its teardrop (`teardrop`,
# ICON_TEARDROP_VERSION for teammates) where it reads, before the tracker sees
# them; the light resolves only a fallback ring-fit lobe; each stored icon's
# `pose` names its origin and facing source, replacing the self icon's `self_cone`.
# 0.6.0 (2026-09-29): on a 331 px widget the self cone casts from self teardrop
# reads at NCC 0.55 and above, not 0.6 (TEARDROP_VERSION 0.4.0, the player's
# 331 px self facing labels, E13); a read under 0.55 casts nothing. Numbered
# above self-spike-tracker-20260929's 0.5.0.
# 0.7.0 (2026-10-04): the teammates are the stored `ally_icon` stream's family
# `ally` rows, posed by `teardrop.posed` with this chain's `RING_FALLBACK`,
# not a second ring fit and teardrop read; a drawn frame the stream did not
# read is refused (`widget` `ally_unread`, with its reason). The coverage row
# records `inputs.ally_icon` and no longer `icon_teardrop_version`.
# 0.7.1 (2026-10-04): on an `ally_unread` frame the self icon is still read,
# tracked and cast (`observable_self`), and the lifecycle suspends only the
# `ally` role (LIFECYCLE_VERSION 0.3.0); each refused frame names its own
# cause (`ally_unread_cause`) from the stream's frame rows and `spans_clip`,
# not the head's clip reason; the coverage row counts the causes.
TEAM_VISION_VERSION = "team-vision-0.7.1"
# The self icon read as a teardrop (`teardrop.fit_teardrop`): its centre is the self cone's
# origin. Promoted from prototypes/teardrop_tip.py (teardrop-tip-0.1.0) unchanged.
# 0.2.0: `SelfConeReader` returns the teardrop's facing as a product, with its centre.
# 0.3.0: on a widget size the facing labels do not cover (`LABELLED_SCALES`), a self
# read under `SELF_FACING_MIN_NCC` gives the centre and no facing (`facing_reason`
# `low_ncc_unlabelled_scale`); `posed` poses a ring-fit detection by a read.
# 0.4.0 (2026-09-29): the 331 px widget is labelled (`self_facing_331_20260929`,
# E13) and its self facing gate is NCC 0.55 (`SELF_FACING_GATES`,
# `self_facing_gate`; `facing_reason` `low_ncc_labelled_gate`); other unlabelled
# sizes keep 0.6, and 465 px keeps no gate. The fit is unchanged.
TEARDROP_VERSION = "teardrop-0.4.0"
# A teammate's or an enemy's icon read as a teardrop (`teardrop.fit_icon`): its centre
# and facing. Promoted from prototypes/icon_teardrop.py (icon-teardrop-0.1.0), whose
# model, keys and gates are unchanged; 0.2.0 scales its radii by `minimap.widget_scale`,
# as the self teardrop's are, so a 331 px widget's centre lands on the portrait.
ICON_TEARDROP_VERSION = "icon-teardrop-0.2.0"
# The prior rule over `fit_icon` (`teardrop.IconPoseReader` given a frame index):
# which earlier fit an icon continues (`PRIOR_PX`, `PRIOR_GAP_MS`), the local grid
# (`LOCAL_PX`, `LOCAL_DEG`), the surprises that run the full grid, and the audit
# cadence (`AUDIT_FRAMES`). `fit_icon` itself is ICON_TEARDROP_VERSION's; a
# reader called without a frame index (`team_vision`) does not use this rule.
# 0.2.0 (2026-10-02): the rule also serves the self teardrop (`SelfConeReader`
# given a frame index, over `teardrop.fit_self`), whose local fit now carries
# `outside_ncc` so `facing_elsewhere` means for it what it means for a teammate,
# and whose prior under `SELF_PRIOR_MIN_NCC` (0.65) runs the full grid
# (`weak_prior`). The ally rule is unchanged.
# 0.3.0: a refused fit continues as a read one does, after the nearest read fit
# is preferred; a local read ends it (`refusal_ended`), a refusal for another
# reason is a surprise, and `REFUSAL_CHAIN` (10) prior-searched refusals in a
# row run the full grid (`refusal_chain`). The audit samples these reads.
# 0.4.0: where the local grid's best is the prior's own centre and facing, the
# compass starts at `PRIOR_REFINE_STEP` (0.125 px, 0.75 degrees) instead of
# 0.5 px and 3 degrees; the full grid's refinement is unchanged.
ICON_POSE_PRIOR_VERSION = "icon-pose-prior-0.4.0"
# One observation of an ability's drawn minimap shape (a ring or a beam), fitted
# by `ability_shapes` on the stored minimap crops at a cast. Bump when a model,
# a prior, an acceptance or the stored fields change.
# 0.2.0 (2026-09-30): the same ring and beam scores, searched fast. A coarse
# FFT ring surface proposes five centres and the exact score is maximised
# round each; the beam is swept over every angle at once; a ring's centre
# must lie on the map's footprint. Promoted from prototypes/ability_shape_fast.py
# (docs/ABILITY_DETECTION.md, stage 1).
# 0.3.0 (2026-09-30): every pixel length is a base value times one transform,
# widget scale x map zoom from baked geometry (`geometry.map_scale`). The
# widened ring range now reaches the 465 px keys' rings; rows carry `map_scale`.
# 0.4.0 (2026-09-30): the finders take a candidate's descriptor (shape, drawn
# sizes, colour model, prior) from `ability_candidates`; the shared teal and
# the whole radius range are the surprise path's. New finders: four segments
# on a line (`fit_segments`) and a smooth curve (`fit_curve`).
ABILITY_SHAPE_VERSION = "ability-shape-0.4.0"
# The candidate set of `ability_candidates`: the appearance table, the lineup
# and death inputs it reads, the exclusion rules. Bump when the table, an
# input or a rule changes; a remeasured fact changes `values_digest` instead.
# 0.2.0 (2026-10-01): Lockdown joins the table (the enemy ring only); an
# unread lineup slot, refused or blind, opens every agent its side has not
# named (`open_slot`), where 0.1.0 took a refused slot's best guess alone.
ABILITY_CANDIDATES_VERSION = "ability-candidates-0.2.0"
# The candidate fits of the ability pass: `ability_fit` (rings, beams) and
# `ability_wall` (segments, curves) rows, one per candidate per gated sample,
# and the `ability_shape_audit` cadence. Bump when the pass's use of the
# candidates, the surprise rule or the audit cadence changes.
# 0.2.0 (2026-10-01): a ring or beam candidate whose hue band misses the
# teal gate's opens its own gate (its colour forms a component as wide as
# the teal gate asks), so a yellow ring is fit where the teal gate stays
# shut; only teal-gated candidates spare a sample the surprise path.
ABILITY_FIT_VERSION = "ability-fit-0.2.0"
ABILITY_WALL_VERSION = "ability-wall-0.1.0"
# The teal-component opportunity gate of the ability pass (`ability_scan`,
# `ability_gate` rows): which 2 Hz live samples the shape fits read. Bump when
# its thresholds, its grid or its stored fields change.
# 0.2.0 (2026-09-30): the component extent is a base value under the transform.
ABILITY_GATE_VERSION = "ability-gate-0.2.0"
# The dark-icon proposer and its pointwise verify (`ability_icons`,
# `ability_icon` rows), ported from `prototypes/ability_shape_fast.py` with the
# baked slab, radii at 1 px. Bump when a threshold, the radius step, the slab
# or a stored field changes.
# 0.3.0 (2026-09-30): radii, rim, reach and verify window are base values under
# the transform (`geometry.map_scale`), no longer shares of the crop's width.
ABILITY_ICON_VERSION = "icon-proposer-0.3.0"
# The ability tray's charge drops, written as `tray_drop` rows by `reticle
# tray` from the stored crops. Bump when a tray constant or the drop rule
# changes; the gate that decides which drops are the player's has its own
# stamp, PLAYER_CAST_VERSION.
# 0.2.0 (2026-10-05): a teal or gold half going empty is a drop (`by`
# halves), with both samples' half classes as evidence; the tray is drawn
# where every C, Q and E half reads as a bar class under read slot icons
# (`tray.drawn_mask`), so a drop onto an all-spent tray is not `forced`.
# 0.3.0 (2026-10-05): a gold-only drop fires only on a second channel's
# witness (`tray.gold_witness`): the restock countdown restarting or
# appearing over the slot, or its icon lit on the gold sample and dimming
# after; the refused ones are stored as `unwitnessed_drop` rows. Teal drops
# are unchanged.
# 0.4.0 (2026-10-05): a third witness, `persisted`: the spent half read gold
# on `tray.GOLD_PERSIST_MIN` readable samples in a row ending at its gold
# sample; any one witness fires the drop. Candidates and witnesses carry
# `gold_run`.
TRAY_VERSION = "tray-0.4.0"
# The tray's teal fill per slot (`tray.slot_counts`, `fills`) and the
# fill-only drawn test, which `tray-kit` and `ability-state` record as
# `tray_fill`. It was stamped TRAY_VERSION until tray-0.2.0 changed the drops
# only; bump when a teal constant, the guard rows or the fill normalisation
# change.
TRAY_FILL_VERSION = "tray-0.1.0"
# The tray bar's half classes (`tray.segment_scores`, `segment_classes`): each
# half of each bar scored softly against teal, gold and the empty grey, and
# cut once (`SEG_MIN`). `reticle tray` writes them beside the drops as
# run-length `segments` rows of the `tray_drop` stream, and ability_state
# reads them. A stamp of its own, so the fill and drop rule (TRAY_VERSION),
# and the streams that read only the fill, keep theirs. Bump when a class
# centre, spread, the core geometry, the cut or a stored field changes.
# 0.1.0 (2026-10-04): first reader; the client draws a returned charge gold.
TRAY_SEGMENT_VERSION = "tray-segment-0.1.0"
# Whether the game's menu covers the HUD, per sample of the stored crops, written
# as `menu_open` rows by `reticle menu`: the tab strip in the `hud` cache and
# the CLOSE SETTINGS button in the tray crop (`menu`). Bump when a fit, a
# constant or the stored fields change.
MENU_VERSION = "menu-0.1.0"
# Which stored tray drops are the local player's casts, decided by
# `ability_timeline.player_tray_casts` from stored data alone. `reticle tray`
# stamps it beside its drops; `ult-cast` and `ability-shapes` record it among
# their inputs. Bump when the gate's rule or its inputs change.
# 0.1.0 was stamped as tray-0.1.0 and ended the kit at the player's first
# killfeed death in the round.
# 0.2.0: a Phoenix Run It Back death, and a Clove death her Not Dead Yet
# revive follows, do not end the kit.
# 0.3.0: an X drop from a slot that was not full (a `from` fill below
# `ability_timeline.FULL_MIN`) is refused as `partial_charge`.
# 0.4.0: an X drop that does not empty the slot (a `to` fill above
# `ability_timeline.EMPTY_MAX`) is refused as `pips_lit`, and a drop that
# leaves any other slot at its full level (a `to` fill at or above
# `ability_timeline.FULL_AFTER_MIN`) as `equip_release`.
# 0.5.0: a release, a drop `equip_release` refuses from above
# `ability_timeline.FULL_LEVEL`, taints no drop beside it; an X drop the
# charge tests refuse still does.
# 0.6.0: the first change from the player's kit to another agent's in a round,
# stored by `reticle tray-kit`, ends the kit too, until the tray returns to the
# player's kit; a drop between the two is refused as `after_kit_change`. A
# session without current `tray_kit` rows is decided as under 0.5.0.
# 0.7.0: a drop at an instant the stored menu witness (`menu_open`, `reticle
# menu`) finds the menu open is refused first, as `menu_open`, and taints no
# drop beside it; on a capture with no rounds table it outranks `no_rounds`.
# A session without current `menu_open` rows is decided as under 0.6.0.
# 0.8.0: the gate reads the kit at each drop from the stored `tray_kit` spans
# (`tray_kit.kit_agents_at`): a drop under another agent's kit is
# `kit_not_player`, and under a named kit where the arbiter names no player
# agent `kit_owner_unresolved`. Own and other are judged against the
# consumer's player agent, not the agent the rows were written against, so
# rows written with no player agent still give kit changes.
# 0.9.0: a stored revive of the player from any reviver
# (`adjudication.death.player_revive_times`), a teammate Sage's Resurrection
# included, undoes the death before it for every agent, not only Clove's own
# Not Dead Yet.
# 0.10.0: the player's own ult line (`ult_cast` rows of the player's own class
# that rest on no tray cast) passes an X drop refused as `forced` or
# `after_player_death` in the agent's cast window of it, before the kit's end;
# one line, one drop (`ability_timeline._admit_lined_x`).
PLAYER_CAST_VERSION = "player-cast-0.10.0"
# Whose kit the ability tray shows, per sample of the stored `hud_abilities`
# crops: the slot icons scored against the catalogue's (`tray_icons`) and read
# against the candidate sets the lineup allows (`adjudication.tray_kit`),
# written as `tray_kit` rows by `reticle tray-kit`, with the arbiter's identity
# events as `tray_kit_identity`. Bump when the icon geometry, a threshold, the
# candidate-set rule, the span rule or the stored fields change.
TRAY_KIT_VERSION = "tray-kit-0.1.0"
# The restock countdown numeral above a C, Q or E tray slot (`tray_countdown`),
# written as `tray_countdown` rows by `reticle tray` in the tray's shared pass
# over the stored crops. Bump when the font, its size, the placement, the
# candidate set, a threshold or a stored field changes.
# 0.1.0 (2026-10-05): first reader, DIN Next Regular at 16 px.
TRAY_COUNTDOWN_VERSION = "tray-countdown-0.1.0"
# The player's minimap self icon, its portrait scored against every agent's
# art on stored minimap crops where the roster reads all five allies alive
# (`self_icon`), written as `self_icon` rows by `reticle self-icon`; the
# lineup reads them as its `self_icon` witness. Bump when the gate, the pixel
# mask, the gallery scoring or the stored fields change.
# 0.1.0 (2026-09-28, never committed): the composition against the official
# art alone; it named Chamber for Skye on two sessions.
# 0.2.0: each frame also stores the portrait feature families and their
# rendered-art scores, and the witness reads those at the table's margin.
# 0.3.0: a self fit that lands on a spike glyph (`spike.on_glyph`) is
# skipped for the next; a frame whose every fit lands on one is refused as
# `on_spike_glyph`.
# 0.4.0: `spike.on_glyph` keeps a fit that may be the carrier: near a carried
# glyph it refuses only a fit on the glyph's core or one whose carrier another
# fit of the frame holds (0.3.0 rows, written on two sessions, refused by
# distance alone).
# 0.5.0: the portrait is cut, aligned and tested for overlap at the self
# teardrop's centre (`teardrop.SelfConeReader`, TEARDROP_VERSION) where it reads
# on the labelled 465 px widget; each row keeps the ring fit's `cx`, `cy` and adds
# `x`, `y`, `origin` and `origin_reason`.
# 0.6.0 (2026-10-04): where the session's stored widget placement is rotated
# 180 degrees, the aligned portrait is turned back before its features are
# taken (`self_icon.turned_widget`): the resampled widget had delivered it
# upside down, and the turned half of 4f207c0c4e39 named Phoenix for Iso.
# A frame read so carries `turned`; the coverage row, `widget_frame`.
SELF_ICON_VERSION = "self-icon-0.6.0"
# The kit of the local player as a state per slot (charges, equipped,
# castable, owner alive), written as `ability_state` rows by `reticle
# ability-state` (`adjudication.ability_state`) from stored `tray_drop` rows,
# the verdicts of the gate, the deaths and the tray fills of the crop cache.
# Bump when a level threshold, a transition, a charge rule or the stored
# fields change.
# 0.2.0: the wiki harvest gives the charge count where no domain fact does
# (`charge_priors`); state rows name their `charges_source`, and the coverage
# row lists the conflicts, the slots without a count and the half readings
# against each count.
# 0.3.0: the kit witness (`adjudication.tray_kit`). A sample inside a span of
# another agent's kit is unreadable as `kit:spectating:<agent>`, and after the
# round's first kit change as `owner_dead:kit_witness`, where the tray's own
# kit rather than a killfeed entry says the owner is dead.
# 0.4.0: the gate's `player-cast-0.8.0` verdicts, and the spans of another
# agent's kit judged against the arbiter's player agent even where the stored
# `tray_kit` rows named none.
# 0.5.0: the audio witness (`adjudication.ability_audio`, through
# `ability_timeline.audio_cast_witness`). Each drop verdict carries an `audio`
# claim: the kit ability the audio around the drop sounds like, its score,
# margin and refusal, and whether it agrees with the drop's slot; the
# coverage row counts them. It changes no state.
# 0.6.0: the audio claim carries the witness's calibrated `p_right` beside
# its margin (`best_ref`, `margin_ref`, `p_right_reason`,
# `calibration_basis`); `score_labels` reads the player's corrections
# (`tray_object_labels`) and says whether each label agrees with its drop.
# 0.7.0: the audio claim carries the witness's `phase` (a phase group's
# release and landing evidence, `ability-audio-0.4.0`); its verdict may be
# refused `bolt_unknown` or `landing_tie`.
# 0.8.0: the tray's half classes (TRAY_SEGMENT_VERSION). A C, Q or E level
# counts gold halves, the charge the client draws when it comes back; a level
# whose teal halves disagree with the fill is unread and held
# (`segments_disagree_with_fill`); a live-phase rise that adds a gold half
# with no player kill near it is a `live_return`; state rows carry `gold` and
# the run's `halves`.
# 0.9.0: the drops read halves (tray-0.2.0), so spending a gold charge is a
# drop; a sample is drawn by the half classes under read slot icons; a gold
# rise is a `live_return` only on an ability with a restock fact
# (`restock_facts`), elsewhere a `recharge` with the surprise
# `gold_rise_without_a_restock_fact`; slot parameters carry `restock_fact`.
ABILITY_STATE_VERSION = "ability-state-0.9.0"
# Which ability of the player's kit the audio around a tray cast sounds like:
# a whitened matched filter over the stored audio-gate log-mel against the
# game's own ability sounds (`adjudication.ability_audio`), read by
# `ability_timeline.audio_cast_witness`. Bump when the frames, the whitening,
# the template rule, the track, the window, the refusals or the stored fields
# change.
# 0.2.0: a cast's window is cut at the midpoint to the neighbouring own cast
# the gate passes on each side (`ability_audio.clip_bounds`), so a cast's
# score never reaches the next cast's sound.
# 0.3.0: each row carries `p_right`, the set's stored margin calibration
# applied to the best referenced class's margin, beside the margin.
# 0.4.0: phase groups (`ability_audio.cast_verdicts`): abilities sharing a
# sound score as one kit class, and where it wins a later phase names the
# slot -- Sova's bolts share their release, and the landing files after it
# name the bolt; neither landing heard refuses `bolt_unknown`, a landing
# margin under TIE_MARGIN `landing_tie`; each row carries `phase`.
# 0.5.0: a phase group may declare a late phase per member (Sova's Recon
# Bolt's scan pulse): where no landing is heard and exactly one member's late
# track reaches its level, that member is the verdict with no margin and no
# `p_right` (`late_phase_only`); `phase` carries the late scores.
# 0.6.0: a pulse-only verdict carries a `p_right` from its group's
# `late_calibration` (`late_p_right`: the late level's false-fire rate over
# the cast's late window against the dev hit rate and prior), basis
# `late_phase`; without one it stays None (`late_phase_only`).
ABILITY_AUDIO_VERSION = "ability-audio-0.6.0"
# The fitted parameter set the audio witness reads, under
# `reference/ability-audio/<version>/` in the store: per agent the background
# whitener (shrink 0.1), the AR(2) coefficients, the whitened templates and
# their classes, and the class thresholds at one false fire per live minute,
# fitted on the dev sessions its provenance names. A new fit is a new
# version; a set is never overwritten.
# 0.1.1: the same fit; Skye's Trailblazer evidence map adds the player's
# confirmation (`player_20261003`) to its basis.
# 0.2.0: `reticle ability-audio-fit`: the declared split
# (`ability_audio.split_sessions`), one whitener pooled over every agent's
# dev sessions, thresholds over every dev session, shared reference files
# left out (`ability_audio.shared_reference_mask`); Sova, Skye, Phoenix,
# Clove, Iso, and Omen and Deadlock zero-shot.
# 0.2.1: the player's answers of 2026-10-04 (`ability_audio_fit.PLAYER_MAPS`):
# Skye's Guide_AbilE_ScoutExpire_3P is Guiding Light. Sova's
# Hunter_AbilQ_Cast_* as Shock Bolt is recorded, not applied: dev refuted it.
# 0.2.2: 0.2.1's arrays byte for byte, and per agent the margin calibration
# fitted on its dev casts (`ability_audio.calibrate`, `reticle
# ability-audio-fit --calibrate`).
# 0.2.3: Skye's Guide_AbilE_ScoutExpire_3P is Trailblazer's end-phase sound
# (player and game data, 2026-10-04), left out of the cast-window references
# (`ability_audio_fit.END_PHASE_LEFT_OUT`); the Guiding Light map is gone.
# 0.2.4: 0.2.3's arrays byte for byte with the margin calibration fitted on
# its dev casts.
# 0.2.5: Sova's Hunter_AbilQ_Cast_* are the bolts' shared release, the phase
# group Q+E (`ability_audio_fit.PHASE_GROUPS`), with the Shock and Recon
# landing files and their levels; thresholds per kit-level class.
# 0.2.6: 0.2.5's arrays byte for byte with the margin calibration fitted on
# its dev casts (a bolt's margin is its landing margin).
# 0.2.7: 0.2.6's arrays, thresholds and calibration, with the Recon Bolt's
# scan pulse (Play_Hunter_Abil_SonarBolt_SonarPing_upd, audio-sfx-gaps-0.1.0)
# as the phase group Q+E's late phase for E, 0.05 to 6.0 s after the release,
# its level at one false fire per live minute on dev (`reticle
# ability-audio-fit --late-phase`).
# 0.2.8: 0.2.7's arrays, with the phase group Q+E's late phase for E
# calibrated on dev (`reticle ability-audio-fit --late-calibrate`): the
# counts `ability_audio.late_p_right` reads.
ABILITY_AUDIO_PARAMS_VERSION = "ability-audio-params-0.2.8"
# Peaks of the official ultimate voice lines correlated against a capture's
# audio, written as `ult_line` rows by `reticle ult-lines` (`ult_lines`). It
# stores no class and no name. Bump when a template, the front end, the
# correlation, the floor or the stored fields change -- those re-decode audio.
# 0.2.0: the templates are the game's own English lines (vo-ref-0.1.0, each
# agent's ultimate announcement event), not the wiki MP3s.
ULT_LINE_VERSION = "ult-line-0.2.0"
# Ultimate casts selected, classed and named from stored `ult_line` peaks, the
# lineup and the rounds table by `reticle ult-cast` (`adjudication.ult_cast`),
# with own lines bound to the player's X casts from `tray_drop`. Bump when the
# threshold, the classing, the cast window or the stored fields change.
# 0.2.0: `tray_witness` on own casts and `missed_line` rows.
# 0.3.0: bursts under BURST_BOUND refused; peaks under THRESHOLD accepted only
# with a tray or ult-kill witness (`rests_on`).
# 0.4.0: a burst counts every stored peak at or above BURST_FLOOR, not only the
# selected ones; the coverage row states `vo_heard`.
# 0.5.0: every cast and refusal row carries its round's barrier drop (`gametime`),
# onset minus drop and a phase (buy, at_drop, live); selection is unchanged.
ULT_CAST_VERSION = "ult-cast-0.5.0"
# Grey dark minimap floor and icon-occluded pixels, packed per sampled frame,
# written as `minimap_dark` rows by `reticle scan`. It stores no decision;
# `adjudication.smokes` reads it. Bump when `SMOKE_SAT_MAX`, the occluders or
# the stored fields change -- those need pixels, so they re-decode.
MINIMAP_DARK_VERSION = "minimap-dark-0.1.0"
# Smoke tracks recomputed from stored `minimap_dark` rows by `reticle smokes`.
# Bump when a birth, presence or end rule in `adjudication.smokes` changes.
# 0.2.0: sampling gaps are unobserved; onsets carry their own censoring.
# 0.3.0: a frame the stored menu witness (`menu_open`) finds covered is
# unobserved.
# 0.4.0: a component whose disc overlaps a live track's is no birth, so a smoke
# born half covered is not born again once uncovered.
SMOKE_VERSION = "smoke-0.4.0"
# Which ally agent cast each smoke track, from stored `smoke` tracks, the
# lineup's verdicts and the player's tray casts (`adjudication.smoke_owner`).
# Bump when a rule, a lifetime, a cast window or the stored fields change.
# 0.2.0 (2026-10-04): each row links the player's smoke-slot tray cast its
# track was cast from (`cast`, `cast_ms`, `rests_on`), so the entity starts at
# the drop and a Dark Cover's target-icon phase lies inside it.
SMOKE_OWNER_VERSION = "smoke-owner-0.2.0"
# Combat report reads (header score, per-row damage, hit splits, flag-word
# correlations), written as `combat_report` rows by `reticle scan`. It stores no
# decision. Bump when an offset, a threshold, the templates or the stored fields
# change -- those need pixels, so they re-decode.
# 0.2.0: each row also stores its portrait thumbnail (`portrait`).
# 0.3.0: each row also stores its name-field band median BGR (`band`).
# 0.4.0: each row also stores the ALLY word correlation in the weapon slot (`slot_word`).
COMBAT_REPORT_VERSION = "combat-report-0.4.0"
# Panels, their rounds and per-round kill/death/assist counts, recomputed from
# stored `combat_report` rows by `reticle combat-report`. Bump when a grouping,
# voting or round rule in `adjudication.combat_report` changes.
# 0.2.0: per-round verdict (report where shown, else killfeed) with its source.
# 0.3.0: rows named through adjudication.identity by portrait cluster.
# 0.4.0: killfeed witnesses take enemy portraits only.
# 0.5.0: round_verdicts accessor; KILLED YOU and lone KILLED rows bind to
#        stored death entities (`bind_deaths`) and carry death_verdict claims.
# 0.6.0: ALLY rows (the ALLY word) take no enemy witness, cluster apart from
#        enemy rows, and are bounded by the ally lineup less the player.
# 0.7.0: a panel opening up to 4 s before the killfeed reads the death is a
#        death panel (the death flash can wash the killfeed).
# 0.8.0: KILLED on an ALLY row (a team kill) is not a kill; an early panel
#        that does not read the previous round's death panel stays in its own
#        round as a death the killfeed missed.
# 0.9.0: binding a KILLED YOU row to a death and picking the killer's killfeed
#        track use the at-death window (5 s before to 4 s after the panel
#        opens, `near_death`) instead of 6 s before to 1 s after; a KILLED
#        YOU row binds only when it is the panel's one KILLED YOU row.
# 0.10.0: the killer's killfeed portrait names a KILLED YOU row only as the
#        panel's one KILLED YOU row; in a panel with more, a row binds by the
#        portrait cluster an earlier death panel of the round bound, and the
#        one row left to the one death left in the window; a death opens at
#        most one death panel, so a repeated read with no later death reopens.
# 0.11.0: a panel's round is the rounds owner's (`rounds.round_containing`,
#        the post-round period up to the next buy phase) instead of a fixed
#        8 s past the round's end; a summary within SUMMARY_WINDOW_MS after
#        the last stored round's close reports that round.
COMBAT_REPORT_ROUND_VERSION = "combat-report-round-0.11.0"
# Stage 02 roster reads, off the two HUD roster bars. **What this stamps is the
# per-slot DETAIL VECTORS, not the alive count.** Bump when `ART_FRAC` or the
# ROI geometry changes -- those need pixels, so they re-decode.
#
# 0.2.0 (2026-09-07) added `detail_ally` / `detail_enemy`: the ten floats the
# count is adjudicated from. Before it, the table held only the count, so
# changing the split rule meant re-reading the video of a session already read
# -- which is why `docs/ROSTER_FINDINGS.md`'s experiment could not be run from
# storage. Now it can.
#
# **Its own table and its own stamp, rather than two more columns on
# `l1/hud`.** They are read from the same frames in the same pass, so fusing
# them would cost nothing to write -- but it would put the roster behind
# `HUD_VERSION`, and then a `DETAIL_FLOOR` tweak would restamp all 34 HUD
# columns as a new definition and a HUD bump would restamp every roster read as
# new when nothing about the roster moved. That is exactly the comparability
# fault `metrics.py` splits deps from context to avoid: a version that moves
# for reasons unrelated to the number it stamps is not a version, it is noise.
#
# 0.3.0 (2026-09-28) starts the crispness band below the tinted panel's top
# edge (`roster.PANEL_TOP_FRAC`). The rows above the panel show the scene
# undimmed, and that strip let an empty slot reach 10-13 and count as a
# portrait (docs/BOARD_ALIVE_SETS.md). Every stored vector changes; `scan
# --only roster --from cache` rereads them without a decode.
ROSTER_VERSION = "roster-0.3.0"
# The split rule that turns those detail vectors into a count. It is a SEPARATE
# stamp because it is a pure function of stored data: changing it re-derives,
# it does not re-decode, and `Store.has_roster` deliberately does not consult
# it. Same argument as splitting the roster off `l1/hud` -- a version that
# moves for reasons unrelated to the number it stamps is noise -- applied one
# level down, to the observation/adjudication boundary rather than the
# channel boundary. Bump when `DETAIL_FLOOR` or `roster.alive_from_detail`
# changes.
#
# 0.2.0 (2026-09-07) is two changes with one cause -- both replace an ABSOLUTE
# test on a composited HUD, which is the mistake CLAUDE.md records as never once
# having been the right answer here. The split is now a RATIO between the
# dimmest occupied and brightest empty slot; and "nothing is crisp" is resolved
# by whether the SCORELINE reads on that frame rather than by how dark the bar
# is, so a wiped team answers 0 and an absent HUD refuses. `roster.resolve()`
# does the second, over stored data, because `scan --only roster` runs no HUD.
#
# 0.3.1 (2026-09-28) adds `CRISP_FLOOR`: a bar whose crispest slot is below 13
# holds no portrait, so a wiped bar over detailed scenery reads 0 (HUD drawn)
# or None rather than 1 (docs/BOARD_ALIVE_SETS.md). 0.3.0 names a rule the
# store's metrics log measured the same day and never shipped: `DETAIL_FLOOR`
# raised to 13 per split, which also counted 0 on bars holding a red portrait
# beside crisp teammates.
#
# 0.4.0 (2026-09-28): a bar with a crisp slot but no winning split refuses
# (`no_split`) rather than reading 0 under a drawn HUD, and every refusal
# carries its reason (`roster.read_split`, `roster.resolve_reasons`).
# `DETAIL_FLOOR` falls from 9 to 8 for roster-0.3.0's panel band, where no
# board-empty slot reaches 8 and a red portrait reads 6-11.
ROSTER_SPLIT_VERSION = "roster-split-0.4.0"
# The spike's glyph on the minimap (fitted as a rounded triangle, base down on
# the ground and base up when carried) and its marker on the ally roster, read
# from the minimap and hud crop caches (`spike`), written as `spike` rows by
# `reticle spike`. Bump when a template, a side, a gate or the stored fields
# change.
#
# 0.2.0 (2026-09-29): a widget drawn turned over (`widget_frame`, rotation
# 180) arrives in the baked frame with its upright glyph upside down; the
# glyph's state and the carrier's offset turn with the placement's rotation,
# which each frame row stores. Unturned sessions read the same fits.
# 0.3.0 (2026-10-03): the glyph is drawn from the game's texture
# Minimap_BombIcon (build release-13.06-shipping-18-5590001, sha256 checked
# against the store manifest) in place of the hand-drawn triangle: 24 units
# dropped and 18 carried, times the measured box fractions, times the capture's
# map scale (`geometry.MapScale`); centres refine sub-pixel, and the session
# head stores `map_scale` and `game_textures`. The roster marker keeps its
# mined template (`spike.TEMPLATE_FILE` says why).
SPIKE_VERSION = "spike-0.3.0"
# The spike's carrier and state cross-checked from stored `spike` rows, the
# rounds table and the roster (`adjudication.spike_carrier`): the roster
# marker against the minimap carried glyph, the carrier against the plant, a
# vanished marker against the roster's alive count. Bump when a rule, a
# tolerance or the stored fields change.
#
# 0.2.0 (2026-09-29): the carrier's icon is sought at the offset the frame
# row's widget `rotation` turns (`spike.carrier_offset`).
SPIKE_CARRIER_VERSION = "spike-carrier-0.2.0"
