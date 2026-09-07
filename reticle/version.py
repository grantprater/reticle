"""Version stamps written into every stored row.

Per the design doc (SS7): every row carries the versions that produced it, so
rows can be attributed to a definition and selectively recomputed later.

Bump EXTRACTOR_VERSION when the meaning of any primitive column changes --
that invalidates cached L1 and forces a re-decode. Bump SEGMENTER_VERSION for
changes to span logic only; that recomputes from stored L1 without touching
video.
"""

SCHEMA_VERSION = 1
ROUND_VERSION = "round-0.1.0"
COACH_VERSION = "coach-0.1.0"
EXTRACTOR_VERSION = "l1-0.1.0"
SEGMENTER_VERSION = "seg-0.2.0"
# Stage 02 deterministic HUD extraction. Bump when glyph segmentation, the
# template set, or field parsing changes -- that invalidates stored HUD reads
# and forces a re-decode, since this stage needs pixels.
HUD_VERSION = "hud-0.11.0"
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
MINIMAP_VERSION = "minimap-0.3.0"
# Minimap pings, emitted as EVENTS rather than per-frame rows. Bump when the
# hue bands, the size gates or the lifetime gate change. Events are rewritten
# whole per session, so this is a stamp for attribution rather than a cache
# key -- nothing skips a ping read on a version match, because pings ride a
# pass that was going to happen anyway and cost no decode of their own.
PING_VERSION = "ping-0.1.0"
# Stage 02 roster alive counts, read off the two HUD roster bars. Bump when
# `ART_FRAC`, `DETAIL_FLOOR` or the split rule in `roster.alive_from_detail`
# changes -- that needs pixels, so it re-decodes.
#
# **Its own table and its own stamp, rather than two more columns on
# `l1/hud`.** They are read from the same frames in the same pass, so fusing
# them would cost nothing to write -- but it would put the roster behind
# `HUD_VERSION`, and then a `DETAIL_FLOOR` tweak would restamp all 34 HUD
# columns as a new definition and a HUD bump would restamp every roster read as
# new when nothing about the roster moved. That is exactly the comparability
# fault `metrics.py` splits deps from context to avoid: a version that moves
# for reasons unrelated to the number it stamps is not a version, it is noise.
ROSTER_VERSION = "roster-0.1.0"
