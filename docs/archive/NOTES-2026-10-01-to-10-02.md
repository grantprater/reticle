# Reticle working handoff

## Picking up

**2026-10-01.** Master stands at `b218bb3` and is pushed. On 2026-09-30 the entity-event layer landed: `reticle project` writes the death, spike, round-entity and enemy lanes, and `reticle view` draws a round from them alone ([ENTITY_EVENTS.md](docs/ENTITY_EVENTS.md)). The identity rule became one arbiter per channel under the `adjudication.identity` aggregator, and `plan` now compares every input stamp a stream recorded. On 2026-10-01 the killfeed weapon owner learned to refuse an icon it has never seen. The [backlog](BACKLOG.md) holds three active items: the corpus rerun, the killfeed crop faults and the missing killfeed readers. The previous handoff is [archived](docs/archive/NOTES-2026-09-29-to-10-01.md).

The player's answers stand as facts in `domain/*.toml`; their words stay in `~/reticle-notes/`.

### What `status` and `plan` say

`reticle status`: 60 sessions ingested, 439 rounds derived; 13 of 17 exact against `checks.KNOWN_KD`; plants on 220 of 439 rounds; one ping session stale.

`reticle plan` names one crop-cache reread (`ally_icon` on 18 sessions) and storage reruns across nearly every match: `deaths` (`death-adjudication-0.20.0` -> `0.24.0` on 16 sessions), `lifetimes` (`round-entity-0.8.0` -> `0.13.0`), `ability-shapes` (`ability-shape-0.1.0` -> `0.4.0`), `self-icon` (-> `0.5.0`), `vision` (`team-vision-0.3.0` -> `0.6.0`), then `ult-cast`, `ability-state`, `combat-report`, `tray`, `smokes`, `enemy-tracks` and `project`. bfad2778a372's entity lanes are held until its deaths refresh.

### Landed on 2026-10-01

- **Test crash.** `test_usage` stands in for `cv2.VideoCapture` instead of subclassing it; the subclass corrupted pymalloc under OpenCV 5.
- **Death binding.** A death binds first to the piece the arbiter named its victim, then the nearest sighting (`round-entity-0.11.0`). A piece seen past the dead-icon lag is not the victim (0.12.0), and a death left unbound may end a piece before its segment's last (0.13.0, `seen_after_death`). A player kill joins the entry whose divider agrees at the kill's onset (`death-adjudication-0.22.0`); `plan` stamps the reliability table by its death rule.
- **Ability candidates and walls.** `ability_candidates` supplies the abilities a lineup allows, each with a drawn size in base px times the map scale; the shape reader fits rings, beams, walls (Barrier Orb) and curves (Blaze). An enemy Killjoy's Lockdown is a yellow ring [domain:abilities/killjoy-lockdown-enemy-minimap-ring]; off Split it refuses as `no_radius_on_map`, since no radius is measured there.
- **Open-set killfeed icons.** `adjudication.weapon` scores an icon by nearest-exemplar IoU and refuses as `new` (unlike every exemplar) or `ambiguous` (two names too close). It narrows by the actor's kit, then the match's agents, then the full gallery as the surprise path, and audits one entry in ten with the full search. `death-adjudication` owns the entry type: kill, second-life death or revive, with reviver and revived roles [domain:killfeed/entry-types] [domain:killfeed/revive-entries]. The Warden is a new rifle [domain:killfeed/warden-icon]; `weapon-gallery-0.4.0` names twelve Warden entries on 4f207c0c4e39 and changes no other name. `prototypes/label_killfeed_groups.py` lets the player name each group of refused icons.
- **Ability names.** `ABILITY_CANONICAL_NAMES` had slots swapped for Phoenix, Brimstone, Deadlock and Harbor; it now follows `<store>/reference/abilities.json`, and `tests/test_ability_names.py` guards it. Phoenix's Ability1 is Hot Hands [domain:killfeed/phoenix-hot-hands-icon]. The fix moved one exemplar: `weapon-gallery-0.5.0`, `weapon-adjudication-1.2.0`.

### What the killfeed numbers say

Through the tiered search, known icons refused as `new` rose from [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.3.0#known_refused_new_after=0.0272] at gallery 0.3.0 to [metric:killfeed_openset/tiered_all_unselected@weapon-gallery-0.4.0#known_refused_new_after=0.0338] at 0.4.0, for no measured cause. The player named [metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#rows=16] groups of refused rows no icon; most are boxes the weapon reader cut badly, and a channel the reader ignores catches each ([metric:killfeed_openset/crop_faults@a06f04a0059f+5822b6646448+4f207c0c4e39#caught_any=16]). A box can also crop an icon too tightly.

### Open questions

- Orange rings on 043bafca271a (`C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`): whose ability?
- Regrowth's saturation floor waits on a definition of a rim pixel; the stored floor was measured on pixels already cut at saturation 50, and the Regrowth benchmark fell from 14 to 12.
- bfad2778a372 (`C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`) shows a Chamber death twice, at 1017.0 s and 1018.5 s.
- Hunter's Fury's angle is within 3 degrees on 17 of 19 casts, down from 19.
- The icon benchmark runs 1.8 times slower than before, for no measured cause.

### Held and unmerged

`git log master..<branch>` lists unmerged commits on:

- `self-spike-tracker-20260929` (4): the player-dead owner and guard 6 can merge with bumped versions; the minimap tracker waits on on-spike labels.
- `wip-vision-lifecycle-wiring` (1): WIP, do not merge.
- `enemy-fix-check-20260930` (1): a held-out check of the teardrop box and the baked-slab gate.
- `worktree-agent-a18926290da85c09f` (6, local only): the protocol-demo census.
- `worktree-agent-a3c32f26e36c27c4f` (5, local only): demo glyph mining and tray-drop checks.
- `experiment/bootstrap-a` (1), `experiment/bootstrap-b` (1), `experiment/bootstrap-integration` (2), local only.

`decodes-20260929` has no unmerged commit left; delete it when convenient.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched. The [working map](docs/WORKING_MAP.md) routes reading.
