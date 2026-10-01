# Reticle working handoff

## Picking up

**2026-09-29.** Every branch of the day that was meant to land is merged into master and pushed. The day moved the minimap's facing to the teardrop everywhere, started the scene model the player named as the end goal, and restarted the audio line from clean references. The player's answers of the day stand as facts in `domain/*.toml`, and their exact words are in `~/reticle-notes/DOMAIN.md` (no remote). Nothing is wired that was not scored on the player's labels. The [backlog](BACKLOG.md) holds three active items; the previous handoff is [archived](docs/archive/NOTES-through-2026-09-29.md).

`pytest` is now installed in the venv, and the suite passes on master (one expected failure).

### The minimap facing

- **Teardrop everywhere.** Every consumer reads icon centre and facing from the teardrop, never the ring fit ([E10](docs/STATISTICAL_ADJUDICATOR.md#e10-the-teardrop-in-every-consumer)). The ring's lobe had been chosen by the same light that later scored it ([E11](docs/STATISTICAL_ADJUDICATOR.md#e11-the-light-chose-the-rings-lobe-then-scored-it)).
- **331 px widget.** The player labelled self, ally and enemy facings blind at 331 px (`labels/*_facing_331_20260929.jsonl`). The self facing gate there is 0.55 (`teardrop-0.4.0`, `team-vision-0.6.0`); other scales keep 0.6 ([E13](docs/STATISTICAL_ADJUDICATOR.md#e13-the-331-px-self-and-enemy-labels)).
- **Fusion.** `prototypes/facing_fusion.py` takes the teardrop and tip highlight as the prior and the drawn light as evidence ([E12](docs/STATISTICAL_ADJUDICATOR.md#e12-the-icon-and-the-light-as-two-witnesses-of-one-facing)); not wired.
- **Icon facts.** The tip highlight is icon art; the enemy lobe is translucent and its rim faint at 331 px; the enemy's dropped spike shows only in team vision; an enemy carrier shows no spike overlay [domain:minimap/icon-tip-highlight] [domain:minimap/enemy-lobe-translucent].

### The scene model

[SCENE_MODEL.md](docs/SCENE_MODEL.md) plans one joint render-and-compare detector for every entity on the minimap, then a mesh with the killfeed, chat, roster, tray and audio. Stage 1 ran three times in `prototypes/scene_stack.py`:

- 0.1.0 compared class-colour scores and lost badly at 331 px.
- 0.2.0 rendered RGB over a two-state floor; it matched the teardrop at 465 px and still lost at 331 px.
- 0.3.0 lights the floor from each team icon's pose. Isolated 331 px self icons improve; stacks get worse, because a neighbour's light or a wall makes a reversed cone cheap ([results](docs/SCENE_MODEL.md#stages-1-and-2-together-030-the-light-from-the-pose)).

**Unexplained light.** Almost every labelled item shows lit floor no cone reaches. Lingering cones explain little of it and off-crop teammates none ([causes](docs/SCENE_MODEL.md#where-the-unexplained-light-comes-from)). The player named the sources: ability areas (Chamber's Trademark, Veto's Chokehold, Deadlock's Sonic Sensor), piloted drones' cones, the **self audio circle**, and a **dead Clove's smoke-range circle**. No teammate lights a circle round itself [domain:minimap/no-teammate-floor-circle].

- `prototypes/clove_circle.py` measured the Clove circle on one cast in `C:\Users\grant\Videos\2026-09-28 14-18-06.mp4` (not ingested): drawn only for a dead Clove, centred on the death point, from the cast to just after the smoke lands [domain:abilities/clove-dead-smoke-range-circle].
- `prototypes/audio_circle.py` measured the self audio circle on `4f207c0c4e39` (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`): a fixed radius, about half a second per sound, extended by the next, not drawn while spectating [domain:minimap/self-audio-circle]. Its proposed fact updates wait on the player.

### Audio

The agreed order: clean references, a common-sound bank, the audio-video offset, then fingerprinting.

- **Range demo.** The player recorded and labelled a range clip (`C:\Users\grant\Videos\2026-09-29 18-50-03.mp4`, `labels/sound_demo_20260929.jsonl`) with `prototypes/sound_demo.py`.
- **Footsteps** draw from a shuffled pool of samples per surface: every block of a pool's length holds each sample once [domain:abilities/footstep-surface-variants].
- **Bank.** `prototypes/sound_bank.py` names most labelled range events leave-one-out.
- **Match.** `prototypes/sound_match.py` ran it on the Iso match: knife equips transfer; gun equips and own shots do not. Stereo level difference separates own sounds from others'. The player may have picked up skinned guns [domain:capture/weapon-skins-picked-up].
- **Circle vs audio.** Audio-circle onsets agree with the bank's own-sound detections only at chance. The orchestrator reads that as the bank's error in match audio (implausible runs of knife equips), not the circle's: use the circle to score the bank. Unresolved: two firing brackets on the Iso match with no circle, at 901.0-902.5 s and 1120.9-1122.9 s.

### A lesson: read the caption at full size

The orchestrator misread a sheet caption as 1497.58 s when it said 49.50 s, and then proposed an 8.5 s time-base offset. A single-frame check showed the crop cache, labels and streams hold true capture time (frame index / 60 fps); the offset hypothesis failed (images in the store's `analysis/timebase-20260929/`). Crop captions before quoting a time, and check the instrument before revising the belief.

### Held and unmerged

- `self-spike-tracker-20260929`: the death/spectate part (guard 6) can merge with bumped versions; the minimap tracker waits on on-spike labels, and its defence-side spike handling should become an enemy-style "?".
- `wip-vision-lifecycle-wiring`: WIP, do not merge.
- `decodes-20260929` has one unmerged commit (`f54aa93`, the before-rescan summaries); check it before deleting the branch.

`reticle plan` names the `ally_icon` reread on 21 sessions (a crop-cache rescan; ask before starting) and a `self-icon` storage rerun to `self-icon-0.5.0`.

The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. The [working map](docs/WORKING_MAP.md) routes reading.
