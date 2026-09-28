# Backlog entries retired on 2026-09-26

Completed entries moved out of `BACKLOG.md` to keep its five latest.

- **`killer-portrait-anchor` (2026-09-25):** the killer's crop anchors at the name's first letter, descenders included; 6663 of 30244 crops moved, 13 names corrected, 228 killers gained.
- **`scan-from-cache` (2026-09-25):** `scan` feeds a pass of cache-bound readers from the ROI crop cache (`--from auto`); rows identical to a decode, 136 s against about 30 min.

## Open entry folded into the ability-identification task on 2026-09-26

**Minimap widget defects (2026-09-24):** the settings menu's dim overlay passes `minimap.widget_drawn` (`6bb88dba5d2c` at 44.0 s), and `radar_circular_mask` centres an ROI-inscribed circle while the drawn ring circumscribes the map [domain:minimap/widget-ring], clipping map pixels on 6 of 12 geometries.

## Open entry folded into the ability-identification task on 2026-09-26 (item 6)

**Ability shapes (next, 2026-09-26).** (1) The seeds read a stale self position (`minimap-0.1.0` to `0.5.0`): refresh it, asking before any decode. (2) A bridged tray drop 0.5 s early refuses a real cast as co-occurring (`75a55a296d3b` 274.1 s). (3) Ask the player which Fury lines are blasts. (4) Test `unnamed-piece-barrier-fury` from the stored labels and shape rows.

- **`revive-plate-witness` (2026-09-26):** a one-colour banner with an unnamed icon, a fielded reviver and two names is a revive (`death-adjudication-0.14.0`).
- **`ability-shape-wiring` (2026-09-26):** `reticle tray` and `reticle ability-shapes` store the player's casts and drawn shapes from the crop cache; on the player's marks Fury 21/21, Regrowth 14/16, Recon Bolt 8/8.

## Combat report error list (2026-09-24, moved 2026-09-27)

(2) the killfeed error list the report exposed: deaths never seen (`5822b6646448` 1415.5 s: the real death after a Run It Back, read in slot 2, never marked the player's death, an assist portrait on its left), an ability kill (molly), a kill of an enemy on a second life counted, a Me -> Me entry counted as a kill (likely Clove's revive expiring [domain:rounds/clove-revive-expiry-entry], or a self-kill), a split track `merge_split_tracks` did not join, and a post-round kill put in the next round where rounds touch (`a1a995e6b19b` 1064.5 s);
