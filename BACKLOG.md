# Reticle task queue

This file orders work and says why a task is active; each open item carries an `Acceptance:` command and an `Evidence:` standard. Historical arguments and completed items are in the dated backlog archives; the queue as it stood at the end of 2026-09-29, with every item's full text, is [here](docs/archive/BACKLOG-through-2026-09-29.md).

## Agreed order (2026-09-29)

**Scene model: draw every light source.** Stage 1 and 2 of [SCENE_MODEL.md](docs/SCENE_MODEL.md) cannot be separated: the floor near an icon is lit by its own cone, by neighbours, by ability areas and by circles. Draw the measured sources in `prototypes/scene_stack.py`: the self audio circle [domain:minimap/self-audio-circle] and the dead Clove's circle [domain:abilities/clove-dead-smoke-range-circle] first, then the ability areas the player named, each from a stored observation or a player fact, never by analogy [domain:abilities/ability-rules-are-unique]. Give a cone evidence weight only for floor no other source explains, and measure the floor-colour error at 331 px on unlabelled frames. Rescore on the same label sets.
Acceptance: `.\.venv\Scripts\python.exe prototypes\scene_stack.py` scores the teardrop and the joint fit on identical items for every label set, with isolated items broken by the fit listed.
Evidence: a 331 px sheet with the drawn sources viewed before any claim; the unexplained-light share before and after through `reticle.metrics`; predictions logged first; nothing wired until the joint fit beats the teardrop on the player's labels at both widget sizes.

**Audio: the circle scores the bank.** The self audio circle marks the player's own sounds in their own view. Use its onsets as the witness for the bank's own-sound detections on `4f207c0c4e39` (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`), find why the bank fires implausible runs of knife equips in match audio, and add references for the missing guns (Ghost, Sheriff, Spectre) and abilities. Player inputs first: (1) were the magazine drops at 901.0-902.5 s and 1120.9-1122.9 s the player's own shots, and what stops the circle there; (2) is the "spike explosion radius" a size known from the game rather than a minimap drawing; (3) approve the proposed `self-audio-circle` fact updates (radius, half-second duration, extension by each new sound, not drawn while spectating). Picked-up skins confound gun classes [domain:capture/weapon-skins-picked-up].
Acceptance: `.\.venv\Scripts\python.exe prototypes\sound_match.py` reports per-class agreement with circle onsets and with the HUD witnesses on the Iso match.
Evidence: the player's answers recorded as facts before the witness changes; the listen list (`analysis/sound-match/listen-20260929.csv`) reviewed by the player; any further match decode approved by the player.

**Player inputs and reruns.** (1) The [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md)'s open cells: why Gekko's cone is missing at `5822b6646448` 49.50 s (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`), which piloted drones cast cones and whether they light the floor, the Seekers' despawn, the harvest values. (2) The `ally_icon` reread on 21 sessions from the crop cache (ask first; migrate the `unnamed_piece` label keys with `prototypes/label_unnamed_pieces.py` before it). (3) `self-icon` storage rerun to `self-icon-0.5.0`, and `reticle vision` for the four labelled 331 px sessions at `team-vision-0.6.0`. (4) Merge the death/spectate part of `self-spike-tracker-20260929` with bumped versions; hold its tracker for on-spike labels.
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan` names no stale stream, and `.\.venv\Scripts\python.exe -m reticle verify --tier fast` passes.
Evidence: each answer recorded as a fact citing the player; every migrated label key points at the same piece before and after, checked on crops; the player approves each decode.

## Waiting

In former order; each item's full text is in the [09-29 archive](docs/archive/BACKLOG-through-2026-09-29.md) or the [09-28 evening archive](docs/archive/BACKLOG-through-2026-09-28b.md).

- **Identity follow-ups** (2026-09-28): contested deaths waiting on an outside witness; three `223d636bf8d2` names; the Shooting Error box; the Iso spike carrier and self icon; `--from auto`; the `scoreboard_edges` fixture.
- **Minimap follow-ups** (2026-09-29): `plan` tracks `team_vision`; `plan` staleness for never-read inputs (`c62c2b06bcfb`); re-measure the facing carry on the teardrop; rays crossing a wall the icon stands against, and cones ending inside the footprint; why teardrop cones with a high match score score lower; the portrait gate for enemy detection at 331 px; stacked icons; an enemy tint reader; the enemy spike "?" in the held tracker.
- **Spectated self icon** (2026-09-30): `round_lifetimes` names the self family "you" after the player's death, when the icon is the spectated teammate; `scene_stack` 0.6.1 gates on `ability_state`'s context, `reticle/` does not.
- **Killfeed attribution** (player, 2026-09-24): exemplar source mismatch; `agent-alive`; the branching banner reader; assist panels; `scoreboard_dim` names; plate revives.
- **Ability identification on the demos** (2026-09-26): the Sova C refusals; census answers; the HUD the pipeline ignores (the ability timer bar dates casts for the audio references); the bank rebuild; the ult-ready scorer.
- **Minimap identity, ally slice first** ([results](docs/ALLY_MINIMAP_IDENTITY.md)).
- **The statistical adjudicator** ([plan](docs/STATISTICAL_ADJUDICATOR.md)): E1-E13 ran.
- **Geometry stamp reads line endings:** `minimap_geometry.source_stamp` hashes raw bytes.
- **Combat report follow-ups** and **Pub/sub**: see the archive.
- **Documents over budget:** `docs/WORKING_MAP.md` and `PROJECT_GUIDE.md` exceed their word budgets; `docs/SCOREBOARD_LINEUP.md` is reached by nothing.

## Completed

- **`scene-light` (2026-09-29):** `scene-stack-0.3.0` lights the floor from each team icon's pose; the light's causes measured, the Clove and self audio circles measured.
- **`sound-bank` (2026-09-29):** the range demo labelled, footsteps shown to draw from a shuffled pool per surface, the first bank scored on the range and on the Iso match.
- **`labels-331` (2026-09-29):** the player's 331 px self, ally and enemy facing labels; the 331 px self gate at 0.55 (E13).
- **`teardrop-everywhere` (2026-09-29):** every consumer reads centre and facing from the teardrop (E10); the ring's lobe was circular (E11).
- **`decodes` (2026-09-29):** the `scoreboard` rescan and the storage reruns at `death-adjudication-0.20.0`.

Full entries: [09-29 archive](docs/archive/BACKLOG-through-2026-09-29.md), [09-28 evening archive](docs/archive/BACKLOG-through-2026-09-28b.md).
