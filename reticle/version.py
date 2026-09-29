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
ROUND_VERSION = "round-0.7.0"
# Coaching bundle. 0.2.0 (2026-09-24): rounds apply the second-life gate, and
# each event carries its round's combat report verdict (`round_verdict`).
COACH_VERSION = "coach-0.2.0"
# Pure credit-ledger rules and interval semantics. This does not stamp a credit
# detector: no such observation channel exists yet.
ECONOMY_VERSION = "economy-0.1.0"
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
SCOREBOARD_VERSION = "scoreboard-0.9.0"
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
SCOREBOARD_VERDICT_COMPATIBLE = ("scoreboard-0.6.0", "scoreboard-0.7.0", "scoreboard-0.8.0",
                                 SCOREBOARD_VERSION)
# The round-history strip as a second presence witness of the Tab board, read
# by `scoreboard_strip` from the hud crop cache's `center` crop and written as
# `scoreboard_strip` rows by `reticle strip`. 0.1.0 ports the rule and
# constants of `prototypes/scoreboard_strip.py` at its 0.2.0.
SCOREBOARD_STRIP_VERSION = "scoreboard-strip-0.1.0"
EXTRACTOR_VERSION = "l1-0.1.0"
SEGMENTER_VERSION = "seg-0.2.0"
# Stage 02 deterministic HUD extraction. Bump when glyph segmentation, the
# template set, or field parsing changes -- that invalidates stored HUD reads
# and forces a re-decode, since this stage needs pixels.
# 0.13.0 (2026-09-25): the killfeed divider prefers line art, so the
# weapon-slot box, and with it `kf_*_wx`, moves off pale plates and portraits.
# 0.14.0 (2026-09-25): `kf_ally_mask` / `kf_enemy_mask` read the killer's
# plate colour behind the weapon icon, not the last run past it.
# 0.15.0 (2026-09-26): `kf_same_side_mask` stores the slots whose killer
# plate reads the victim's side, the one-colour banner a revive draws.
HUD_VERSION = "hud-0.15.0"
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
ALLY_ICON_VERSION = "ally-icon-0.4.0"
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
# One observation of an ability's drawn minimap shape (a ring or a beam), fitted
# by `ability_shapes` on the stored minimap crops at a cast. Bump when a model,
# a prior, an acceptance or the stored fields change.
ABILITY_SHAPE_VERSION = "ability-shape-0.1.0"
# The ability tray's charge drops, written as `tray_drop` rows by `reticle
# tray` from the stored crops. Bump when a tray constant or the drop rule
# changes; the gate that decides which drops are the player's has its own
# stamp, PLAYER_CAST_VERSION.
TRAY_VERSION = "tray-0.1.0"
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
PLAYER_CAST_VERSION = "player-cast-0.7.0"
# Whose kit the ability tray shows, per sample of the stored `hud_abilities`
# crops: the slot icons scored against the catalogue's (`tray_icons`) and read
# against the candidate sets the lineup allows (`adjudication.tray_kit`),
# written as `tray_kit` rows by `reticle tray-kit`, with the arbiter's identity
# events as `tray_kit_identity`. Bump when the icon geometry, a threshold, the
# candidate-set rule, the span rule or the stored fields change.
TRAY_KIT_VERSION = "tray-kit-0.1.0"
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
ABILITY_STATE_VERSION = "ability-state-0.3.0"
# Peaks of the official ultimate voice lines correlated against a capture's
# audio, written as `ult_line` rows by `reticle ult-lines` (`ult_lines`). It
# stores no class and no name. Bump when a template, the front end, the
# correlation, the floor or the stored fields change -- those re-decode audio.
ULT_LINE_VERSION = "ult-line-0.1.0"
# Ultimate casts selected, classed and named from stored `ult_line` peaks, the
# lineup and the rounds table by `reticle ult-cast` (`adjudication.ult_cast`),
# with own lines bound to the player's X casts from `tray_drop`. Bump when the
# threshold, the classing, the cast window or the stored fields change.
# 0.2.0: `tray_witness` on own casts and `missed_line` rows.
ULT_CAST_VERSION = "ult-cast-0.2.0"
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
SMOKE_OWNER_VERSION = "smoke-owner-0.1.0"
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
COMBAT_REPORT_ROUND_VERSION = "combat-report-round-0.8.0"
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
ROSTER_VERSION = "roster-0.2.0"
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
ROSTER_SPLIT_VERSION = "roster-split-0.3.1"
