# Omen Dark Cover misses in the smoke channel

The held-out shape score
(`prototypes/shape_heldout_score.py`) found the smoke channel
(`minimap_dark` -> `adjudication.smokes`) missing most Omen:E headline marks.
Those missed marks are now dev for the smoke channel. The counts, per-mark
stages and graded predictions live in the store's `notes/predictions.jsonl`
(task `omen-dark-cover-miss-diagnosis-20261004`); the raw reads and crop
strips live in `analysis/omen-dark-cover-misses-20261004/`.

## What drops each mark

Three causes, none of them a rejected smoke.

1. **The span gate hides a stationary caster.** In `b9558488a607`
   (`C:/Users/grant/Videos/2026-09-06 17-00-35.mp4`) `segment.py` labels
   28.6-41.6 s and 46.8-74.6 s `off`, which its docstring defines as no HUD.
   The HUD chrome is present there; `in_match` fails on `minimap_dchange`
   alone, because the player stands still on an empty custom-game map and
   the minimap does not change. `scan` reads minimap readers only on active
   spans, so no reader sees either Dark Cover. Read over the whole capture
   from the crop cache, the frozen channel tracks both discs and covers the
   later sightings.
2. **The mark precedes the disc.** A Dark Cover first draws a black target
   icon, then a grey disc [domain:abilities/omen-dark-cover-minimap-phases].
   Marks labelled during the icon phase (`e78e75b2d191` at 20.8 s and
   26.65 s, `C:/Users/grant/Videos/2026-09-03 19-16-07.mp4`; `b9558488a607`
   at 47.8 s and 55.9 s) lie before the track's birth at the same place. The
   icon's ring yields grey-dark components below `AREA_MIN_REF`, which
   `smokes.tracks` drops without a stored reason. The glyph matcher's follow
   verdict names Omen:E at every one of these marks.
3. **No smoke exists.** At `b9558488a607` 39.8 s a white hollow ring is
   centred on the mark and no disc follows; the tray records a Paranoia drop
   before it and no Dark Cover drop. Resolved from stored audio below: Dark
   Cover was equipped there and not cast.

## Cross-reference before tuning

- `tray_drop` reads the whole capture and records an E drop for every Dark
  Cover in both demos, including the two the span gate hid.
- The demo audio census finds the SmokeDome cast sounds on every Omen E cast
  at a stable offset near the drop (`analysis/demo-audio-census-20261004/`,
  a prototype, not a production stream).
- The kill feed does not observe a smoke.

## Proposals (2026-10-04, first pass)

- Open a minimap read window on opportunity: an E tray drop or a Dark Cover
  cast sound in an idle or off span with HUD chrome present.
- Link a smoke track to the E tray drop shortly before its birth at its
  place, so the Dark Cover entity's onset is the drop and its icon phase is
  the glyph sighting.

## What changed (branch `omen-smoke-gaps-20261004`)

**The span rule, in its owner.** The span gate hides HUD-present time on
matches too: on the 21 Riot-record matches `seg-0.2.0` labelled
[metric:omen_smoke_gaps/span_rule#live_off_old=4464] of
[metric:omen_smoke_gaps/span_rule#live_n=67447] live-round samples off while
the HUD stream read the round clock, every one failing on `minimap_dchange`
alone. `seg-0.3.0` gates `in_match` on HUD chrome alone, and the minimap
readers read idle and active spans (`segment.READ_STATES`); that leaves
[metric:omen_smoke_gaps/span_rule#live_unread_new=5] such samples unread. The
cost outside rounds:
[metric:omen_smoke_gaps/span_rule#outside_newly_in_match=2379] of
[metric:omen_smoke_gaps/span_rule#samples=219465] samples with no clock read
outside rounds become in-match; a cache scan clips to rounds and reads none of
them. `plan` names the spans stale (`reticle segment <sid>`) and every reader
that read the old spans (`minimap`, `ping`, `ally_icon`, `minimap_dark`, the
ability pass); each records the spans' stamp from now on.

**No tray read window.** Under `seg-0.3.0`
[metric:omen_smoke_gaps/player_casts#outside_new_read=0] of
[metric:omen_smoke_gaps/player_casts#player_casts=518] player tray casts on
the matches lie outside the read spans (`seg-0.2.0` missed
[metric:omen_smoke_gaps/player_casts#outside_old_active=4]); what remains
unread has no HUD, so no tray drop, and a window would add no sample.

**The cast link, in `smoke_owner`** (`smoke-owner-0.2.0`). Each row names the
player's smoke-slot cast its track was cast from (`cast`, `cast_ms`,
`rests_on` the drop) where the player-cast gate passed one drop inside the
agent's cast window and no other track claims it; else `cast_reason`.

**Trial** from the crop cache (store
`analysis/omen-smoke-gaps-20261004/trial-0.1.0`), no production stream
written. Of the [metric:omen_smoke_gaps/demo_marks#headline_omen_e=13]
headline Omen:E marks on the two demos, now dev for the smoke channel, the
smoke channel covers [metric:omen_smoke_gaps/demo_marks#covered_old=4] under
`seg-0.2.0` and [metric:omen_smoke_gaps/demo_marks#covered_new=8] under
`seg-0.3.0`. The gate refuses every demo drop (`no_rounds`), so no demo track
links its cast; taking the demo drops as the player's casts, the linked
entities cover [metric:omen_smoke_gaps/demo_marks#covered_new_linked=12], all
but 39.8 s. On matches with an ally Omen, against Riot's `ability2Casts`:
`587c15b07779` names Omen on
[metric:omen_smoke_gaps/riot_omen@587c15b07779#omen_named_old=22] tracks under
`seg-0.2.0` and [metric:omen_smoke_gaps/riot_omen@587c15b07779#omen_named_new=23]
under `seg-0.3.0`, Riot
[metric:omen_smoke_gaps/riot_omen@587c15b07779#riot_ability2_casts=25];
`c62c2b06bcfb` [metric:omen_smoke_gaps/riot_omen@c62c2b06bcfb#omen_named_new=30]
either way, Riot [metric:omen_smoke_gaps/riot_omen@c62c2b06bcfb#riot_ability2_casts=32].
The player is never Omen in the matches, so no match track links a cast.

## The 39.8 s mark: an equipped Dark Cover, not a cast

The demo audio census row `b9558488a607:37017:Q`
(`analysis/demo-audio-census-20261004/casts.jsonl`, offsets from the Q drop at
37.02 s) fires the Dark Cover equip sounds `Ability2/..._SmokeDome_Equip_1P_01`
and `4/..._SmokeDome_ReEquip_01` at +2.07 s (39.09 s) and the targeting loop
`..._SmokeDome_UI_Forwards_Loop` at +4.98 s (42.0 s); its first
`..._SmokeDome_Cast_v01` is at +9.79 s (46.8 s), which the E row
`b9558488a607:47050:E` places 0.25 s before the 47.05 s tray drop. So Omen held
Dark Cover equipped from 39.1 s and cast it at 46.8 s; the ring at (258,71)
from 39.3 to 41.5 s lies inside the equip, and no smoke was cast there. The
label marks an equipped Dark Cover, not a smoke. What draws the ring while
Dark Cover is equipped is one observation; it is no domain fact until the
player confirms it or a targeted demo repeats it.
