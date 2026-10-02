# Reticle working handoff

## Picking up

**2026-10-02.** Master stands at `296dce7` and is pushed. The corpus rerun finished on the matches, so `plan` names no stale stream on any match. The [backlog](BACKLOG.md) holds three active items: stacked ally icons by render-and-compare, the killfeed crop faults and the missing killfeed readers. The previous handoff is [archived](docs/archive/NOTES-2026-10-01-to-10-02.md).

### What `status` and `plan` say

After the 2026-10-02 rerun: `verify --tier fast` passes 7 of 7; `status` reads 13 of 17 exact against `checks.KNOWN_KD` and plants on 220 of 439 rounds; doctor reports 0 errors. `plan` still names `vision` (`team-vision-0.3.0` -> `0.6.0`) on 37 sessions and `ult-cast` on 6, all demos under a minute, which the matches-only rule skips.

### Landed on 2026-10-01 and 10-02

- **Killfeed.** `KillfeedScale` scales every length by capture height; `killfeed-weapon-0.6.0` stores the slot's soft glyph and sub-pixel centroid [domain:killfeed/subpixel-placement]; 0.7.0 cuts the slot where the names place the entry; `weapon-gallery-0.6.0` rebinds the player's names. `death-adjudication-0.25.0` types each entry from every revive witness at once.
- **Pixels.** AGENTS.md now says to read pixels as samples of a smooth image [domain:capture/capture-resolution]. `prototypes/capture_psf.py` measures the capture's blur on baked wall lines; ally icons fitted through it do not beat the stored pose ([CAPTURE_PSF.md](docs/CAPTURE_PSF.md)). The portrait crop audit finds contamination a 331 px problem.
- **Minimap and binding.** `ally-icon-0.7.0` continues each teardrop's prior fit; `round-entity-0.14.0` offers an inner piece under a bound segment to the deaths left.
- **Staleness.** `plan` compares the candidate supply's recorded inputs; `usage` times named steps inside a reader.

### Corpus rerun, 2026-10-02

From storage, on matches only: `lifetimes` on 20 match sessions to `round-entity-0.14.0`, then `project` on 5822b6646448 (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`), a06f04a0059f (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`) and bfad2778a372 (`C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`), whose entity lanes no longer held.

### Unmerged records

- **`binding-rules-20261002`** (`b248d0c`, `round-entity-0.15.0`): cut a piece where a sighting gap spans its teammate's death. Against 0.14.0 it gains 21 victim-matching bindings and moves 6 unnamed pieces to a match, but demotes 9 correct bindings to unnamed pieces (matches 686 -> 704 over 78 cuts, measured on the branch). Two faults: a cut piece is inner, so `RoundLifetimes.finish` never offers it the death that cut it; and in 64 of 78 cuts the dead teammate's portrait still scores after the gap (top score in 50), so the cut's premise fails. To rework: fix the stacked-icon phantoms first, offer each cut piece its death through `death_rank`, and cut only when the post-gap sightings do not read as the dead teammate. 96aa1ae9b96f 849.5 s is a revive naming no victim, so Clove's dead interval stays open.
- **`ally-ring-subpixel-20261001`** (`24fbfb1`, `ally-icon-0.8.0`), shelved: fractional ring radii scaled by widget scale, a 9 base px centroid search, and a portrait floor scaled by area. Ally-count MAE falls on every 331 px slice (bfad2778a372 1259-1419 s 0.626 -> 0.530), but excess named icons beyond the roster rise on all three scorable slices, from thin-rim fits on the player's Sova Recon Bolt ring and Split's green world, and 3 labelled 331 px icons are lost (e37fdeca944f, `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`, 1342.5 s Waylay). The radii alone starve identity; the commits land together or not at all. The 9 px self search helps at 465 px (median centre error 3.18 -> 1.20 px on 5822b6646448). Proposed gate, unbuilt: of two close fits, keep the one the teardrop reads as an icon; refuse fits on the player's own ability rings.
- **`stacked-icons-20261002`** (`50ddd0b`, `prototypes/stack_fit.py`, `stack-fit-0.2.0`, `wire: no`): at master, `_gated` keeps a fit between two touching icons, which refuses both as `interior_too_thin`. In seeded samples master missed 18 of 50 real icons at 331 px and 6 of 22 at 465 px. The joint k-icon search made no between fits and cut 223d636bf8d2's whole-slice MAE from 0.627 to 0.407, but lost 42 of 197 labelled icons master finds, placed phantoms on bfad2778a372's green area fill and ran 3-5x slower, because its teal key erases the icons' pale-cyan ring. The first active backlog item carries the next step.
- **`luma-render-20261002`** (`19c2a0a`, WIP, tabled): luma-keyed rims (E1) and fuller render fits (E2), unverified, four E2 test slices unrun; the likely vehicle for the stacked-icon render.

Capture paths: 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`.

[EXTERNAL_GROUND_TRUTH.md](docs/EXTERNAL_GROUND_TRUTH.md) surveys outside records of a match. All 22 match captures have their match-details record (each kill with positions and view angles; 3,532 kills) saved in the store under `external/riot/`, each naming its session in `probe.session_id`. A 40-day-old match falsified the 30-day retention guess; pull new records promptly. The open questions wait in the backlog.

### Held and unmerged

`git log master..<branch>` lists unmerged commits on the four records above (1, 5, 1 and 2 commits, all pushed) and on:

- `self-spike-tracker-20260929` (4): the player-dead owner and guard 6 can merge with bumped versions; the tracker waits on labels.
- `wip-vision-lifecycle-wiring` (1): WIP, do not merge.
- `enemy-fix-check-20260930` (1): a held-out check of the teardrop box and the baked-slab gate.
- `worktree-agent-a18926290da85c09f` (6, local only): the protocol-demo census.
- `worktree-agent-a3c32f26e36c27c4f` (5, local only): demo glyph mining and tray-drop checks.
- `experiment/bootstrap-a` (1), `experiment/bootstrap-b` (1), `experiment/bootstrap-integration` (2), local only.

`decodes-20260929` has no unmerged commit left; delete it when convenient.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
