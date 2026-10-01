# Reticle task queue

This file orders work and says why a task is active; each open item carries an `Acceptance:` command and an `Evidence:` standard. Historical arguments and completed items are in the dated backlog archives; the queue as it stood at the end of 2026-10-01, with every item's full text, is [here](docs/archive/BACKLOG-through-2026-10-01.md).

## Agreed order (2026-10-01)

**One corpus rerun of the stale streams.** `reticle plan` names storage reruns on nearly every match: `deaths` to `death-adjudication-0.24.0`, `lifetimes` to `round-entity-0.13.0`, `ability-shapes` to `ability-shape-0.4.0`, then `ult-cast`, `ability-state`, `combat-report`, `tray`, `smokes`, `enemy-tracks` and `project`; plus the crop-cache work: `ally_icon` on 18 sessions, `self-icon` to `self-icon-0.5.0`, `vision` to `team-vision-0.6.0` and `scan --only ability` on five. Run them as one batch on matches only, in the order `plan` prints, after the fixed handful passes. Migrate the `unnamed_piece` label keys with `prototypes/label_unnamed_pieces.py` before the `ally_icon` reread. Ask the player before starting; no step decodes video.
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan` names no stale stream, and `.\.venv\Scripts\python.exe -m reticle verify --tier fast` passes.
Evidence: the player's approval before the run; `reticle status` K/D exact count against `checks.KNOWN_KD` no lower than before; every migrated label key points at the same piece before and after, checked on crops; per-session death diffs listed, each change explained.

**Killfeed weapon box crop faults, and the rise in known icons refused as new.** Of the [metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#rows=16] groups of new-icon rows the player named no icon, most are bad boxes: on no entry, left of the killer portrait, across the killer's name, cutting an icon, on a band above the entry, or on an icon fading in (`prototypes/killfeed_openset.py faults`). A box can also crop an icon too tightly: the Hot Hands entry at b3b9defb6fd7 1731.5 s (`C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`) [domain:killfeed/phoenix-hot-hands-icon]. `killfeed._band_text` [owns:killfeed-weapon-descriptor] sets wx0/wx1 from its own blob alone. Gate it by cross-reference: a killer name read in the slot (`killfeed_name`), a counted entry track covering the frame, the box's top against the killer portrait's, its width against the entry's modal width; mark a track's first and last frames. A cut first frame also fixes the entry's width in `adjudication.weapon.bind_entry`: the Warden entry at 4f207c0c4e39 1783.0 s binds its 71 px first box and stays refused. Separately, known icons refused as `new` rose from [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#known_refused_new_after=0.0272] to [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.4.0#known_refused_new_after=0.0338] between gallery 0.3.0 and 0.4.0; read the refusal reasons of the added rows before changing anything.
Acceptance: `.\.venv\Scripts\python.exe -m reticle trial --reader killfeed SESSION` on a06f04a0059f, 5822b6646448 and 4f207c0c4e39, then `.\.venv\Scripts\python.exe prototypes\killfeed_openset.py faults <product> <labels>`.
Evidence: none of the 16 labelled rows stored as a weapon icon; every named entry of the three sessions keeps its name; the cause of the 0.0272 -> 0.0338 rise stated from the stored reasons, with crops viewed.

**The missing killfeed readers.** (1) KAY/O's down and revive each draw an X inside a downward triangle [domain:killfeed/kayo-downed-entry]. `killfeed.detect_second_life_badge` fits a ring on the player's own entries only, so a down is stored as a death; `revive_entry` keys on the revive icons. Cross-reference the pair: a revive must follow a KAY/O down in the round, under his ult (`ult_cast`). 4f207c0c4e39 has a down at 790.5 s and a revive at 799.0 s and no death stream. (2) The icon beside the victim's name: [KILLFEED_VICTIM_ICON.md](docs/KILLFEED_VICTIM_ICON.md) waits on the player's list of icons that can appear there. The crop cache serves [metric:killfeed_openset/victim_icon_cache_coverage@corpus#sessions_cached=21] sessions; the rest need `scan --only hud` (ask first). (3) The assist panel's disabling-ability icons [domain:killfeed/assist-panel].
Acceptance: `.\.venv\Scripts\python.exe -m reticle deaths SESSION` on a KAY/O capture stores each down as `is_second_life` and each revive as `is_revive`, with the pair linked.
Evidence: the player's labels of every KAY/O down and revive in that capture, against the stored rows; the player's answer on victim-side icons recorded as a fact before any reader code.

## Waiting

Each item's full text is in the [10-01 archive](docs/archive/BACKLOG-through-2026-10-01.md) or older archives.

- **Ability candidate follow-ups** (2026-10-01): orange rings on 043bafca271a (`C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`), owner unknown; Regrowth's saturation floor waits on the player's definition of a rim pixel; Hunter's Fury's angle benchmark fell from 19 to 17 casts within 3 degrees; the icon benchmark runs 1.8 times slower; Lockdown's radius is measured only on Split.
- **Duplicate Chamber death** (2026-10-01): bfad2778a372 (`C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`) stores Chamber's death at 1017.0 s and again at 1018.5 s.
- **Scene model: draw every light source** (2026-09-29): `scene-stack-0.6.1` casts light by raycast and still flips more facings than the teardrop; nothing wired until the joint fit beats the teardrop on the player's labels at both widget sizes ([SCENE_MODEL.md](docs/SCENE_MODEL.md)).
- **Audio: the circle scores the bank** (2026-09-29): `sound-bank-2.0.0` reaches knife equips in match audio; other classes do not transfer from the range; use the self audio circle's onsets to score the rest.
- **Player inputs**: the [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md)'s open cells (Gekko's missing cone at `5822b6646448` 49.50 s, piloted drones' cones, the Seekers' despawn, harvest values).
- **Identity follow-ups** (2026-09-28): contested deaths waiting on an outside witness; three `223d636bf8d2` names; the Shooting Error box; the Iso spike carrier and self icon; `--from auto`; the `scoreboard_edges` fixture.
- **Minimap follow-ups** (2026-09-29): `plan` staleness for never-read inputs (`c62c2b06bcfb`); the facing carry on the teardrop; rays crossing walls; the portrait gate for enemies at 331 px; stacked icons; an enemy tint reader; the enemy spike "?" in the held tracker.
- **Spectated self icon** (2026-09-30): `round_lifetimes` names the self family "you" after the player's death, when the icon is the spectated teammate.
- **Killfeed attribution** (2026-09-24): exemplar source mismatch; `agent-alive`; the branching banner reader; `scoreboard_dim` names; plate revives.
- **Ability identification on the demos** (2026-09-26): the Sova C refusals; census answers; the ability timer bar; the bank rebuild; the ult-ready scorer.
- **Minimap identity, ally slice first** ([results](docs/ALLY_MINIMAP_IDENTITY.md)); **the statistical adjudicator** ([plan](docs/STATISTICAL_ADJUDICATOR.md)), E1-E13 ran.
- **Geometry stamp reads line endings:** `minimap_geometry.source_stamp` hashes raw bytes.
- **Combat report follow-ups** and **Pub/sub**: see the archives.
- **Documents over budget:** `docs/WORKING_MAP.md` and `PROJECT_GUIDE.md` exceed their word budgets; `docs/SCOREBOARD_LINEUP.md` is reached by nothing.

## Completed

- **`killfeed-openset-20261001` (2026-10-01):** the weapon owner refuses an unseen icon as `new` or `ambiguous`, narrows by kit, lineup, then full gallery, audits one entry in ten; entry types and roles; the Warden named; `ABILITY_CANONICAL_NAMES` follows the reference (`weapon-gallery-0.5.0`, `weapon-adjudication-1.2.0`).
- **`ability-walls-20260930` (2026-10-01):** `ability_candidates` feeds the shape finders; walls and curves stored; enemy Lockdown as a candidate ring.
- **`death-followups-20261001` (2026-10-01):** a death binds to its named piece, then the nearest sighting (`round-entity-0.13.0`); `death-adjudication-0.22.0`.
- **`test-crash-20261001` (2026-10-01):** `test_usage` stands in for `cv2.VideoCapture` instead of subclassing it.
- **`staleness-20260930` (2026-10-01):** every stream records the stored stamp of each input it read, and `plan` compares them all; doctor INPUTS.

Full entries: [10-01 archive](docs/archive/BACKLOG-through-2026-10-01.md), [09-29 archive](docs/archive/BACKLOG-through-2026-09-29.md).
