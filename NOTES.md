# Reticle working handoff

## Picking up

**2026-10-03.** Master stands at `4ad072a`. A corpus rerun from the crop cache and storage finished on every match, so `plan` names no stale line on a match. The [backlog](BACKLOG.md) holds three active items: close the remaining failures against Riot's match records, cut runtime (first, why `ally_icon` costs twice as much per call on six sessions), and stacked ally icons by render-and-compare. The killfeed crop faults and missing killfeed readers became threads of the first. The previous handoff is [archived](docs/archive/NOTES-2026-10-02-to-10-03.md).

A crash at 00:52 on 2026-10-03 zeroed `.git/refs/heads/master` mid-merge; the player restored it to `48ae5df` from the reflog, and `git fsck` reports no fault.

### What `status`, `plan` and the Riot scorer say

After the rerun, `verify --tier fast` passes every check with none stale (before it, three were stale); `status` reads one more known K/D exact than before; doctor reports no error. `plan` still names `vision` (`team-vision-0.3.0` -> `0.6.0`) and `ult-cast` on the demos, which the matches-only rule skips.

`prototypes/riot_ground_truth.py --all --offline --record` scored the stored streams against Riot's match records on 21 matches:

- **Deaths:** recall [metric:riot_truth/deaths#recall=0.978], precision [metric:riot_truth/deaths#precision=0.9765]; of named fields, victim [metric:riot_truth/deaths#victim_right_of_named=0.9946], killer [metric:riot_truth/deaths#killer_right_of_named=0.991], weapon [metric:riot_truth/deaths#weapon_right_of_named=0.9981].
- **Rounds:** winners right on [metric:riot_truth/rounds#winner_right=439] of [metric:riot_truth/rounds#riot_rounds=439]; plants on both sides [metric:riot_truth/rounds#plant_both=251], Riot only [metric:riot_truth/rounds#plant_riot_only=27], two unread.
- **K/D:** known players agree on [metric:riot_truth/kd#known_agree=18] of [metric:riot_truth/kd#known_scored=18]; tracked exact on [metric:riot_truth/kd#tracked_exact=15] of [metric:riot_truth/kd#tracked_scored=21].
- **Minimap allies at kill instants:** [metric:riot_truth/minimap/all#matched=7272] of [metric:riot_truth/minimap/all#riot_allies=8935] matched, [metric:riot_truth/minimap/all#phantom=1453] phantoms, [metric:riot_truth/minimap/all#missed_stacked=792] misses in stacks; reader centre error median [metric:riot_truth/minimap/all#reader_pos_err_px_median=1.3] px.

### Landed since the 2026-10-02 handoff

Each commit body carries its measurements (`git log --no-merges d52a54b..master`).

- **Ground truth.** `prototypes/riot_ground_truth.py` (`riot-truth-0.1.0`, `wire: no`) scores stored streams against Riot's records; `killfeed_trial_deaths.py` adjudicates a killfeed trial in memory for it.
- **Rounds.** `plant_graphic` (`plant-graphic-0.1.0`) reads the planted-spike graphic in the cached scoreline crop; `round-0.8.0` marks plants from it [domain:hud/planted-spike-replaces-clock]. `stored_reads` keeps only sample rows.
- **Killfeed.** `hud-0.17.0` reads ability kills that `_band_text` had refused as `no_icon`; `hud-0.18.0` reads Clove's ringed divider as one ring. `death-adjudication-0.26.0` keeps entries in their order across a misread divider [domain:killfeed/stack-order]. `prototypes/killfeed_queue_stats.py` measured the stack as a queue; the player's answers on entry lifetime, capacity and round end are facts in `domain/killfeed.toml`.
- **Speed.** `ally_icon` runs faster with byte-identical output; `track.assign` calls scipy. `ally-icon-0.9.3` and `icon-pose-prior-0.4.0` continue the self teardrop's fit at 465 px, search the self icon in full on a weak prior, continue a refused fit as a prior, and start the compass finer.
- **Usage.** Stored-data commands record their runs (`command-usage-1`) and mark named steps. `reticle usage` still lists only scan passes, so an estimate cannot use those records.
- **Plan.** `plan` prints rerun lines in dependency order (`build_order` over `order_graph`): a driver running lines top to bottom had rebuilt `ult-cast` before the `tray` and `combat-report` it reads.

### Corpus rerun, 2026-10-03

On the 21 matches, crop cache and storage, no decode: `scan --only hud --from cache`, then `scan --only ally_icon --from cache`, then `vision`, then the storage commands `plan` named, and a short second pass. `hud` and `ally_icon` read different crop-cache sets, so one `--only hud ally_icon --from cache` pass refuses; run them separately.

### Unmerged records

- **`binding-rules-20261002`** (`round-entity-0.15.0`): cuts a piece where a sighting gap spans its teammate's death; gains victim-matching bindings but demotes correct ones. A cut piece is inner, so `RoundLifetimes.finish` never offers it its death, and the dead teammate's portrait usually still scores after the gap. Rework after the stacked icons: offer each cut piece its death through `death_rank`, and cut only where the later sightings do not read as the dead teammate. The revive at 96aa1ae9b96f (`C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`) 849.5 s names no victim.
- **`ally-ring-subpixel-20261001`** (`ally-icon-0.8.0`): a negative result by the player's verdict; it stays shelved and unmerged. Fractional ring radii lowered ally-count error at 331 px but added phantom fits and lost labelled icons.
- **`stacked-icons-20261002`** (`prototypes/stack_fit.py`, `wire: no`): the joint k-icon search made no fit between two icons but lost labelled icons, because its teal key erases the pale-cyan ring. The first active item carries the next step.
- **`luma-render-20261002`** (WIP, tabled): luma-keyed rims and fuller render fits, unverified; the likely vehicle for the stacked-icon render.
- **`killfeed-prior-design-20261002`** (2 commits): `docs/KILLFEED_QUEUE_PRIOR.md`, a proposed plan for a prior-driven killfeed reader that follows the queue. `killfeed-prior-step1-20261002` adds `prototypes/killfeed_follow.py`, step 1 of that plan, not wired.
- `self-spike-tracker-20260929`: the player-dead owner and guard 6 can merge with bumped versions; the tracker waits on labels. `wip-vision-lifecycle-wiring`: WIP, do not merge. `enemy-fix-check-20260930`: a held-out check of the teardrop box and the baked-slab gate. Local only: `worktree-agent-a18926290da85c09f` (protocol-demo census), `worktree-agent-a3c32f26e36c27c4f` (demo glyph mining), `experiment/bootstrap-*`. Delete `decodes-20260929` when convenient.

Riot's match-details records for all 22 match captures sit in the store under `external/riot/`, each naming its session in `probe.session_id` ([EXTERNAL_GROUND_TRUTH.md](docs/EXTERNAL_GROUND_TRUTH.md)); pull new ones promptly.

Capture paths: 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
