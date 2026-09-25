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
SCOREBOARD_VERSION = "scoreboard-0.5.0"
EXTRACTOR_VERSION = "l1-0.1.0"
SEGMENTER_VERSION = "seg-0.2.0"
# Stage 02 deterministic HUD extraction. Bump when glyph segmentation, the
# template set, or field parsing changes -- that invalidates stored HUD reads
# and forces a re-decode, since this stage needs pixels.
HUD_VERSION = "hud-0.12.0"
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
ALLY_ICON_VERSION = "ally-icon-0.3.0"
# Light evidence at each ability candidate's instant, written as `ability_light`
# EVENTS by `reticle ability-light`: `lighting.raw_lit` and `lighting.raw_dark`
# packed per frame. It stores no decision; `adjudication.ability` reads it.
# 0.2.0: stores raw_dark alongside raw_lit to distinguish opaque objects from viewcones.
ABILITY_LIGHT_VERSION = "ability-light-0.2.0"
# Grey dark minimap floor and icon-occluded pixels, packed per sampled frame,
# written as `minimap_dark` rows by `reticle scan`. It stores no decision;
# `adjudication.smokes` reads it. Bump when `SMOKE_SAT_MAX`, the occluders or
# the stored fields change -- those need pixels, so they re-decode.
MINIMAP_DARK_VERSION = "minimap-dark-0.1.0"
# Smoke tracks recomputed from stored `minimap_dark` rows by `reticle smokes`.
# Bump when a birth, presence or end rule in `adjudication.smokes` changes.
# 0.2.0: sampling gaps are unobserved; onsets carry their own censoring.
SMOKE_VERSION = "smoke-0.2.0"
# Combat report reads (header score, per-row damage, hit splits, flag-word
# correlations), written as `combat_report` rows by `reticle scan`. It stores no
# decision. Bump when an offset, a threshold, the templates or the stored fields
# change -- those need pixels, so they re-decode.
# 0.2.0: each row also stores its portrait thumbnail (`portrait`).
# 0.3.0: each row also stores its name-field band median BGR (`band`).
COMBAT_REPORT_VERSION = "combat-report-0.3.0"
# Panels, their rounds and per-round kill/death/assist counts, recomputed from
# stored `combat_report` rows by `reticle combat-report`. Bump when a grouping,
# voting or round rule in `adjudication.combat_report` changes.
# 0.2.0: per-round verdict (report where shown, else killfeed) with its source.
# 0.3.0: rows named through adjudication.identity by portrait cluster.
# 0.4.0: killfeed witnesses take enemy portraits only.
COMBAT_REPORT_ROUND_VERSION = "combat-report-round-0.4.0"
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
ROSTER_SPLIT_VERSION = "roster-split-0.2.0"
