# Omen Dark Cover misses in the smoke channel

Diagnosis only; no detector changed. The held-out shape score
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
   before it and no Dark Cover drop. The player is asked what draws it.

## Cross-reference before tuning

- `tray_drop` reads the whole capture and records an E drop for every Dark
  Cover in both demos, including the two the span gate hid.
- The demo audio census finds the SmokeDome cast sounds on every Omen E cast
  at a stable offset near the drop (`analysis/demo-audio-census-20261004/`,
  a prototype, not a production stream).
- The kill feed does not observe a smoke.

## Proposals (not made)

- Open a minimap read window on opportunity: an E tray drop or a Dark Cover
  cast sound in an idle or off span with HUD chrome present. This recovers the
  span-gated discs without retuning `minimap_dchange_min`.
- Link a smoke track to the E tray drop shortly before its birth at its
  place, so the Dark Cover entity's onset is the drop and its icon phase is
  the glyph sighting. Score the smoke channel from the disc onwards.
- Neither recovers the 39.8 s mark; it waits for the player's answer.
