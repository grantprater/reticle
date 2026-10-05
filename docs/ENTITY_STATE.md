# Entity state: player slots, position beliefs and ability children

A plan, proposed 2026-10-04. The player asked why the ally reader loses
teammates, what our position representation is, and whether a game-like
representation would serve both representation and querying better; he
called losing an icon in a crowd unacceptable. He then added that abilities
are child entities of their casters, shorter-lived, following the same
principle, with a position that is harder to define. This plan answers both.
Rules live in [AGENTS.md](../AGENTS.md); this plan cites them and restates
none. It extends [SCENE_MODEL.md](SCENE_MODEL.md) section 1 (the state) and
fills the ally estimate that [ENTITY_EVENTS.md](ENTITY_EVENTS.md) leaves
owed (`entity_contract.NO_ESTIMATE_OWNER`).

## 0. What "lost" is today, and why

A teammate exists in the store only where a reader fitted it.

- `minimap.AllyIconReader` writes one `frame` row per described frame and
  one `icon` row per fitted ring: widget-pixel `cx, cy, r`, facing and the
  portrait's features. A teammate it did not fit has no row.
- `round_entities.session_lifetimes` links rows into entities after the
  fact. An entity starts at its first observation
  (`acquisition: roster_slot_available_not_identity`) and ends at a bound
  death or is right-censored where observations stop. Nothing is stored
  between observations, and positions are widget pixels.
- `belief.Fix` holds a between-observation estimate for the player alone,
  as a pixel disc.

So a teammate drawn under another icon, a ping, an ability, the spike glyph
or a bright floor has no row and is "lost". At Riot's kill instants over
[metric:riot_truth/minimap/all#sessions=21] matches, of
[metric:riot_truth/minimap/all#riot_allies=10445] living teammates the
stored pieces matched [metric:riot_truth/minimap/all#matched=8366] and missed
[metric:riot_truth/minimap/all#missed=2079], of which
[metric:riot_truth/minimap/all#missed_stacked=1002] stood in stacks. The
prior-first prototype (`prototypes/ally_prior.py`) carried a track one second
(`CARRY_MS`), then dropped it, and its capacity guard refused real fits to
keep beliefs; held out, it still lost
[metric:ally_prior/riot_pool@heldout6#lost_share=0.1322] of living
teammates.

The defect is representational. The store answers "which fits were there",
and a teammate is a fit. A game answers "where is each player", and a player
exists from spawn to death whether or not anyone draws it. This plan makes
the second answer the stored one.

## 1. Slots and their lifecycle

### The slot table

Each match holds ten **player slots**: five per team, keyed
`<session>:<team>:slot:<k>`, `team` in `ally`, `enemy` (the team, never the
attacking side [domain:rounds/halftime-side-swap]) and `k` the lineup's slot
index 0-4. The key is the one `ability_state` already uses for the player's
kit (`<session>:ally:slot:0`). The self is an ally slot. A slot's agent is
the identity arbiter's verdict on that lineup slot (`lineup.load_lineup`,
`identity.claims_from_lineup`); the slot carries the verdict's `ref`, never a
name of its own.

Readers update slots and never create or delete players. The lineup fixes
the slots; the lifecycle below opens and closes them; every observation is
assigned to a slot or explained as something else.

### States and the evidence for each transition

| State | Entered by | Owner asked |
|---|---|---|
| `pending` | match start; between rounds | `rounds.round_bounds` |
| `alive` | round start (spawn) | `rounds.round_bounds`; the roster's alive count checks it (`roster.alive_counts`) |
| `dead` | a death verdict naming the slot's agent | `adjudication.death` (victim through `adjudication.identity`) |
| `second_life` | a Run It Back death, a downed KAY/O | `adjudication.death.second_life_death`, `round_lifetimes.ICON_OUTLIVES_DEATH` [domain:rounds/resurrection-mechanics] |
| `alive` again | a revive entry naming the slot's agent | `adjudication.death` (`revive_entry`, `decide_entry_type`) [domain:killfeed/revive-entries] |
| `unaccounted` (a flag on `alive`) | the roster reads fewer living players than open slots with no death to explain it, or negative evidence empties the slot's region | `roster`, section 2 |
| closed `round_end` | the next buy phase | `rounds`; play continues through the post-round period [domain:rounds/post-round-period] |

- **Spawn.** Every lineup slot opens `alive` at the round's start. The
  round-start belief is the team's spawn region (section 2). A slot the
  round-start roster does not count stays open and `unaccounted`, with the
  roster's read as its reason; nothing infers a disconnect.
- **Death.** A death closes a slot only through the death owner. A named
  victim closes its slot at the verdict's time. An unnamed victim (the
  arbiter refused) binds through the owners that bind deaths today:
  `round_lifetimes.death_refusal`, `death_rank` and `seen_after_death`,
  over the living slots of the victim's team whose belief region holds the
  death's X. One admitted slot closes, its close `depends_on` the other
  slots' verdicts. Several admitted slots stay `alive` with `maybe_dead`
  set, the candidate set stored, until a sighting past
  `round_lifetimes.DEAD_ICON_LAG_MS` or a later verdict resolves it. The
  team's alive count stays the roster's, never the slot table's.
- **Second life and downs.** Phoenix's Run It Back death and a downed
  KAY/O leave the slot open in `second_life`, because their icons outlive
  the killfeed entry [domain:minimap/red-portrait-states]. The slot
  returns to `alive` or closes on the death owner's next verdict.
- **Revive.** Sage's Resurrection and Clove's Not Dead Yet reopen the slot
  [domain:rounds/resurrection-mechanics]. The reopened belief is a reach
  region anchored at the slot's death place; where a revived player stands
  is not recorded as a fact (section 12).
- **Teleport.** A fit outside a slot's region is still that slot's when the
  assignment binds it there (observations win, section 2). The slot then
  records a `relocation` and asks the teleport-licence owner
  (`track.corroborates_teleport` with a `track.Corroboration`): licensed by
  an icon, a cone, audio or an observed destination, or
  `teleport_assumed`. A relocation never opens a slot.
- **Disconnect.** No fact says whether a disconnected teammate stays drawn
  or stays in the roster. The slot stays open and becomes `unaccounted`
  only on the evidence above; the question goes to the player (section 12).
- **The player dead.** The self slot closes on the player's death verdict
  (`round_entities.player_dead_spans`). The self icon then draws the
  spectated teammate [domain:minimap/self-icon-shows-spectated], so each
  later self fit is an observation offered to the living ally slots, marked
  `via_spectated`, and the tray's spectated kit (`adjudication.tray_kit`,
  `kit:spectating:<agent>`) becomes a witness of that teammate's charges
  (section 9).

## 2. The belief

Every open slot holds one belief per frame: a point with an uncertainty
region. Its kind says what the region is.

| Kind | Region | Point | Rests on |
|---|---|---|---|
| `fit` | a disc of radius `k * sigma` round the fit | the fit's world position | that frame's fit (`observation_key`) |
| `held` | the last fit's disc | the last fit | the last fit, while the cheap check finds the icon's pixels unchanged (`ally_prior` design) |
| `crowd` | the crowd blob's cells, dilated by one icon radius | the blob centroid | the members' entry fits and the blob (`crowd_blob.FrameBlobs` design) |
| `reach` | the walkable cells within path distance `R(t)` of the anchor cell, less the cells negative evidence excluded | the anchor | the anchor fit, and the frames whose absence cut the region |
| `reach_disc` | `reach` on a map without a path table: a Euclidean disc on the walkable mask, refusal reason `no_path_table` | the anchor | as `reach` |
| `spawn` | the team's spawn callout region (round start, before the first fit) | the callout's location | valorant-api's map callouts |
| `last_known` | enemies only: the "?" mark's place, then `reach` from it | the mark | `minimap_objects.last_known` |

### Exact form

- **Point:** world `(x, y)` in metres (section 3) and `level`, the floor
  index, or null with a reason.
- **Fit sigma:** `sigma = FIT_ERR_PX * scale * m_per_px`, where
  `FIT_ERR_PX` is the minimap owner's per-fit error at the reference widget,
  `scale` the geometry key's `geometry.map_scale` (one scale transform, no
  per-size table) and `m_per_px` the world frame's metres per baked pixel. Stored ally fits lie a median
  [metric:replay_truth/score@9acf02f98283#ally_err_cm_median=76.0] cm from
  the replay, 90th percentile
  [metric:replay_truth/score@9acf02f98283#ally_err_cm_p90=159.0] cm;
  stage 1 fits `k` on the development set so the disc holds the truth at
  the nominal 0.95, and the held-out set checks it.
- **Reach:** `R(t) = v_max * (t_game - t_anchor) + k * sigma_anchor`, with
  `t_game` from the game-time owner (`gametime.SessionGameTime`), so a
  capture stall does not freeze the growth. The region is
  `dist_dm[anchor_cell] <= R(t)` on the map's all-pairs path table (1 m
  cells, `prototypes/sightlines.py`), less the exclusion mask. `v_max` is
  the top speed a fact gives (section 12). Until one exists the region uses
  the track owner's walker ceiling (`minimap.RUN_PX` through
  `track.association_tolerance`) converted to metres: a measured bound of
  the pipeline, generous by design, never a borrowed game value.
- **No velocity in the region.** A reach region is a bound, not a
  prediction; the reader's prior-first search may predict a place to look
  (the `ally_prior` design), and that prediction never narrows a region.

### Updates, per observation type

1. **A fit assigned to the slot** sets `fit`, whatever the prior said. When
   the fit lies outside the prior region, the slot stores a `relocation`
   and the teleport-licence verdict (section 1). Observations always win.
2. **A cheap check that holds** (unchanged pixels at the predicted icon)
   sets `held`.
3. **Crowd entry.** A slot whose prediction joins a tracked crowd blob sets
   `crowd`: no per-member pose, members set-valued (the player's rule:
   nobody cares whether one teammate stands 10 cm right of another). The
   crowd's split detector, not a timer, ends it.
4. **No observation** grows `reach` from the last `fit` or `held` frame.
5. **Death, revive, round end** follow section 1.
6. **Widget absent, menu open, capture stall:** time passes, the region
   grows, and nothing counts as negative evidence (`minimap.widget_drawn`,
   `menu.MenuWitness`, `stalls`).

### Negative evidence

Own-team icons are always drawn [domain:minimap/vision-gate], so a teammate
cannot stand where its icon would show and none does. A cell `c` **would
show** the slot's icon at frame `t` when all hold:

- the widget is drawn and placed (`minimap.widget_drawn`,
  `widget_frame.placement_status`), no menu covers it, no stall holds;
- `c` maps inside the widget's drawn disc and at least one icon radius in
  from its ring, since the ring cuts icons [domain:minimap/off-widget-self-marker];
- no other drawn thing could hide an icon there: no fitted icon of any
  family within one icon diameter (icons may coincide
  [domain:minimap/coincident-icons] and weld [domain:minimap/icon-welding]),
  no crowd blob, no pixel the hide owner marks (`minimap_dark.occluded`:
  smokes and grey cover), no ping, spike glyph or ability drawing the
  stored readers place there;
- the reader's detection probability `p_det(c)` for an unoccluded isolated
  icon, measured per reader version as a capability (`capabilities`), is
  known.

Each frame adds `log(1 - p_det(c))` to the slot's absence score at every
cell that would show and holds no fit within one icon radius. The region
excludes a cell once its score falls under `log(EPS)`: the score is soft and
the cut happens once, at the decision. A new `fit` resets the scores. A
region the cut empties is a surprise: the slot keeps the uncut region, sets
`region_exhausted`, and stores the frames that emptied it. The causes to
check are a missed death, a teleport, a reader miss and a wrong lineup.

### Identity enters through the arbiter

The fit-to-slot assignment names an observation, so `adjudication.identity`
owns it, as it owns `assign_ally_pieces` today. The slot state supplies the
prior; the arbiter decides.

Per frame, over the open slots of one team and the frame's fits of that
team's colour (ring fits, stack fits, and the self fit while the player is
dead), one `scipy.optimize.linear_sum_assignment` solves

    cost[f, s] = motion[f, s] - llr[f, agent(s)]

- `motion[f, s] = -log p(f | belief_s)`: a Gaussian on `fit`, `held` and
  `crowd` beliefs (variance `sigma_s^2 + sigma_f^2`), uniform over the cells
  of a `reach` region, and a fixed surprise cost outside the region. The
  prior is evidence weighed once: the claim records `rests_on` the belief's
  own `rests_on`, so the prior never counts again as a witness.
- `llr[f, a]`: the portrait's log ratio for agent `a`
  (`identity.rendered_art_scores` over the frame's `portrait_features`), the
  minimap channel's own reading.
- Each fit has one **non-player** column (barrier, ability, refit of an
  icon already assigned, `track.refit_of`), priced from the reader's own
  refusal reasons; each slot has one **unobserved** row priced at
  `-log(1 - p_det)` where its region would show, else zero.

Every fit is assigned or explained; none is dropped to keep a belief, and no
fit opens a slot. More team-coloured fits than living slots means some are
non-player or refits, each with its reason. An assignment publishes an
`identity_claim` on the fit's observation with channel `slot_assignment`,
`binding_from` the ally icon channel, and `depends_on` the slots it
eliminated. Inside a crowd, continuity abstains where a stored portrait
verdict exists: at emergence on 9acf02f98283 continuity alone named
[metric:ally_prior/replay_emergence@9acf02f98283#emergence_continuity_only_right=120]
right and
[metric:ally_prior/replay_emergence@9acf02f98283#emergence_continuity_only_wrong=132]
wrong, against the stored verdict's
[metric:ally_prior/replay_emergence@9acf02f98283#emergence_stored_verdict_only_right=260]
and
[metric:ally_prior/replay_emergence@9acf02f98283#emergence_stored_verdict_only_wrong=39].

Online, the assignment runs frame by frame. After the round a smoothing pass
(a Viterbi over each slot's assignment sequence, the successor of
`assign_ally_pieces`) may revise it; the revision is stored beside the
online answer and cites it.

## 3. The coordinate frame

**Canonical coordinates are world metres** in Riot's game frame: Riot units
over 100, the frame Riot's records and the replays use. Minimap pixels are a
view.

- **The chain.** A stored fit is a widget pixel of the session's
  `(map, profile)` geometry (`widget_frame` places each session there).
  The geometry key gains one baked field, `world_affine`: the 2x3 affine from
  world units to widget pixels, composed from valorant-api's map constants
  (`xMultiplier`, `xScalarToAdd`, `yMultiplier`, `yScalarToAdd`, crossed
  axes [domain:replay/vrf-minimap-axes-cross]) and the geometry's
  `shade_fit`. `prototypes/riot_ground_truth.MapFrame` computes it today;
  `reticle/` may not import a prototype, so `geometry` bakes it, owns it,
  and stamps it with the map constants' digest. The inverse takes pixels to
  metres. The map constants are game data, like the callouts the sightline
  build reads; neither a Riot record nor a replay feeds the transform.
- **Facing** is a world angle in the replay's yaw convention
  [domain:replay/vrf-yaw-is-view-radians], turned from image degrees
  through the same affine.
- **Turns and variants.** A side-based widget turns between rounds
  [domain:minimap/side-based-widget-turns-between-rounds] and a variant
  widget scales; `widget_frame` undoes both before the affine, so world
  coordinates never turn.
- **Floors.** The minimap is a plan; two players on different floors can
  share a point [domain:minimap/coincident-icons], and floor shade only
  hints at height [domain:minimap/floor-shade-is-elevation]. No reader
  reads a level. `level` is null with `no_level_reader` on 2D maps; on maps
  with a 3D table (`prototypes/sightlines_3d.py`: Ascent and Split) it holds
  the set of standable layers of the point's 1 m column, never one guessed.
- **Per-map validity.** The world frame exists where the geometry has a
  `shade_fit`, the map has a valorant-api record with nonzero constants, and
  the art fit clears `geometry.MIN_ART_FIT` (`summit__valorant-16x9-crop75`
  does not). Elsewhere the slot state stays in widget pixels with the reason
  `no_world_frame`, and every reach query refuses. The path tables exist on
  seven maps today (`<store>/sightlines/`: Abyss, Ascent, Haven, Lotus,
  Split, Summit, Sunset); other maps get `reach_disc`.

## 4. Storage, events and migration

### Per-frame arrays

One struct-of-arrays per session: frames by slots, written by the slot-state
owner at `<store>/l2/slot_state/<session>.npz`. The frame axis is the ally
reader's grid (15 Hz from the crop cache); the slot axis holds the ten
player slots, allies first.

| Field | dtype | Bytes | Meaning |
|---|---|---|---|
| `status` | u1 | 1 | `pending`, `alive`, `dead`, `second_life`, `closed` |
| `kind` | u1 | 1 | belief kind (section 2), or none |
| `flags` | u1 | 1 | `relocation`, `region_exhausted`, `maybe_dead`, `unaccounted`, `via_spectated`, `no_world_frame`, `surprise` |
| `level` | i1 | 1 | floor index, -1 unread |
| `x`, `y` | f4 x 2 | 8 | metres |
| `sigma` | f2 | 2 | metres (fit, held) |
| `facing` | f2 | 2 | radians, NaN unread |
| `cell` | i2 | 2 | spatial key: the point's walkable cell, -1 none |
| `anchor_cell` | i2 | 2 | reach anchor, -1 none |
| `radius_dm` | u2 | 2 | reach path radius |
| `t_anchor` | f4 | 4 | game ms of the anchor, relative to the round |
| `area` | u2 | 2 | region size in cells (m^2) |
| `crowd` | i1 | 1 | crowd index this frame, -1 none |
| `node` | i1 | 1 | callout region of the point, -1 none |
| `obs` | i4 | 4 | row of the bound observation, -1 none |
| `margin` | f2 | 2 | assignment cost margin to the runner-up |

A slot-frame takes 36 bytes and a frame 360, plus a 14-byte header
(`t_ms` f8, `frame_idx` i4, `drawn` u1, `menu` u1): 374 bytes. A 25-minute
match at 15 Hz holds 22,500 frames, about 8.4 MB before compression.

Region cell lists (`reach` and `crowd` kinds) are stored apart as a ragged
array (`frame_idx`, `slot`, offset into one int16 cell array) at 2 Hz and at
every kind change; no reach query needs a 15 Hz region (variable fidelity).
A region of 150 cells costs 300 bytes, so three unseen slots at 2 Hz over
1,500 s cost under 3 MB.

### Events consumers read

Consumers read the `entity_slot` lane through `entity_events.EntityEvents`,
never the npz. The lane holds:

- an `entity` row per slot per round: slot key, team, the arbiter's `ref`,
  opened and closed intervals with their reasons and evidence;
- `event` rows: `open`, `close` (citing the death verdict), `revive`,
  `relocation` (with the licence verdict), `crowd_enter`, `crowd_leave`,
  `unaccounted`, `region_exhausted`;
- `estimate` rows at 2 Hz for every slot no fit observes, which fills the
  owed ally estimate (`entity_contract.ESTIMATE_OWNERS` gains the slot-state
  owner for `("icon_track", "ally")`);
- a positions accessor: `EntityEvents.slots_at(t)` returns the
  struct-of-arrays rows for an instant, read from the lane's npz sidecar,
  whose sha256 the lane's stamp row records.

### Provenance and versions

- A `fit` belief `rests_on` its observation key; `held` and `reach` rest on
  the anchor fit and list the frames whose absence cut the region; `crowd`
  rests on the members' entry fits.
- An assignment claim `depends_on` the slots it eliminated; a death bound
  by elimination `depends_on` the slots it excluded.
- Stamps: `slot-state-0.1.0` (lifecycle, storage), `belief-0.4.0` (the
  belief law, extended from the player to every slot), the arbiter's
  `AGENT_IDENTITY_VERSION` (the new assignment), the world frame's stamp,
  `sightlines-0.1.0`, `TRACK_VERSION`, and every input stream's stamp and
  sha (`ally_icon`, `death`, `lineup`, `roster`, rounds, `menu_open`,
  stalls, game time). A change to one input restamps only what reads it.

### What `round_entity` becomes, and the migration

`round_entity` becomes a view over slots: one entity per slot and maximal
observed run, in today's row schema plus `slot_id`, so its consumers keep
working. The migration runs in order; each step is reversible and scored
before the next.

| Step | Change | Consumers |
|---|---|---|
| 1 | `slot_state` built from stored rows only (`ally_icon`, `death`, lineup, roster, rounds); `round_entity` untouched | none; the scorers read both |
| 2 | the assignment moves into `adjudication.identity`; deaths close slots | `entity_events` projects the ally lane from slots; `view` reads it |
| 3 | `round_entity` written as the view over slots (`round-entity-1.0.0`) | `reticle lifetimes`, the Riot scorer, `replay_truth` keep their reads |
| 4 | the ally reader runs prior-first from slot beliefs (the `ally_prior` design, wired) | readers |
| 5 | enemy slots replace `enemy_tracks`' association | `enemy_tracks` becomes the enemy view |

The Riot scorer and `replay_truth.py` gain a slot mode (section 8) beside
their located and lost counts, so step 1 is measured against today's
numbers on the same rows.

## 5. Queries

**Spatial keys.** Every point carries `cell`, its walkable 1 m cell in the
map's sightline table, and `node`, the cell's callout region; a region is a
cell list. Lookups are array indexing.

The coaching reach features (branch engagement-reach-20261004,
`decision_value.reach_features`) count who can **swing** (walk at most 2 m to
a cell that sees the opposing duelist), **trade** (at most 5 m) or stands in
an **adjacent node** (the same or an adjacent callout region). With beliefs
they become probabilities:

- per fight, once: `d_vis = dist_dm[:, vis].min(1)`, the walk from every
  cell to the nearest cell that sees the target's cell (`vis` from
  `los_bits`);
- per slot: `P(swing) = mean(d_vis[region] <= 20)` over the region's cells
  (uniform within a region; a fit's region is a handful of cells), and
  likewise trade at 50 dm;
- `P(node) = mean(adj_callout[node_target, region_callout[region]])`;
- a team's count is the sum of its slots' probabilities, stored with its
  certain floor (slots whose whole region qualifies) and its possible
  ceiling (slots with any qualifying cell).

On the 3D maps the `Map3D` adapter of `prototypes/engagement_reach.py`
serves the same interface. These are post-round queries; nothing is shown
during play.

## 6. Cost per frame and the real-time split

The readers set the cost, not the state.

- The stored ally reader spent
  [metric:scan_usage/ally_icon/cache/serial/cv12@9acf02f98283~e5c119ba#feed_s_ally_icon=1028.085] s
  over [metric:scan_usage/ally_icon/cache/serial/cv12@9acf02f98283~e5c119ba#frames=20620]
  frames on 9acf02f98283: about 50 ms a frame, three quarters of a core at
  15 Hz.
- The prior-first design read the same match at
  [metric:ally_prior/replay@9acf02f98283#prior_first_ms_per_frame=10.49] ms
  a frame.
- One ten-slot update (reach membership by one row compare per unseen slot,
  the negative cut, the assignment, the array write) took a median
  [metric:entity_state_probe/update_cost#median_us=73.2] us, 95th percentile
  [metric:entity_state_probe/update_cost#p95_us=102.6] us, single-threaded
  at Below Normal on Abyss's table (`prototypes/entity_state_probe.py
  cost`).
- A path table costs 52-72 MB in memory per map (uint16, cells squared);
  one map loads per match.

The 20% frame-rate budget is not yet measured (`docs/FRAMETIME_PROTOCOL.md`).
The split follows the cost:

- **During play:** the readers at opportunity-gated rates, the online slot
  update, and the cheap check; no smoothing, no identity revision, and
  nothing shown, since Riot's rules bar conclusions during a match.
- **After each round:** the assignment's Viterbi smoothing, death binding
  by elimination, ability child effects (section 9), and the round's
  coaching queries.
- **After the game:** the board's final lineup, a rerun of the round passes
  where the lineup changed, the evaluation, and the corpus fold.

## 7. Enemies under the same structure

Enemy slots follow the same lifecycle and belief, with weaker evidence.

- **Drawn only when spotted.** Enemy icons appear only inside team vision
  [domain:minimap/vision-gate] and stay drawn briefly after leaving it
  [domain:minimap/vision-trailing-persistence]. An enemy slot is `spawn`
  at round start (its team's spawn callout region, the round's role from
  `rounds.infer_player_side`), `fit` when `minimap_objects` reads its icon,
  `last_known` at its "?" mark [domain:minimap/last-known-mark], and `reach`
  otherwise.
- **Weak negative evidence.** Light can refuse an enemy and cannot confirm
  one (the `drawn-light` owner, `lighting.lit_mask`). A lit cell with no
  enemy icon within one icon radius adds to the absence score, with the
  same hiding rules as allies; an unlit cell adds nothing, since unknown is
  not dark. Enemy regions therefore stay wide. A sharp enemy belief comes
  only from a sighting.
- **Identity.** Enemy icons carry portrait features for the arbiter
  (`identity.claims_from_minimap_icons`); the same assignment binds them to
  enemy slots, over the enemy lineup from the arbiter and the board.
- **Other witnesses.** An enemy ultimate line (`adjudication.ult_cast`, with
  its side) shows a living enemy slot and places nobody; a killfeed death
  closes the slot as for allies.
- The replay holds no stored enemy coverage yet
  ([metric:replay_truth/score@9acf02f98283#enemy_coverage=0.0]); enemy
  calibration is first measured at Riot's kill instants.

## 8. Evaluation

Riot's records and the replay are evaluation truth only; neither feeds a
reader, a threshold, a prior or the transform.

### Truth instants

- **Riot:** every living player at each Riot kill instant, the victims of
  that instant included, aligned through stored deaths as
  `riot_ground_truth.py` aligns them, positions in world units over 100.
- **Replay:** every living player-tick of 9acf02f98283 on the 15 Hz grid
  (`replay_truth.py`), interpolated across gaps up to `MAX_GAP_MS`, never
  wider.

The truth slot of a truth player is the slot whose arbiter-named agent is
that player's agent on that team (Riot's character id, evaluation only). A
slot the arbiter left unnamed scores under `slot_unnamed`.

### Metrics, exactly

For each truth instant `i` of a living player with truth point `p_i` and
slot `s_i`:

- **Status agreement:** the slot is open and not `dead`. `lost` is the share
  of truth-alive instants whose slot is closed, `pending` or `dead`.
- **Containment:** `contained_i` is true when the cell holding `p_i`, or one
  of its eight neighbours (the 1 m registration tolerance the 2D sightline
  gate uses), lies in the reported region; for `fit` and `held`,
  `|p_i - x_i| <= k * sigma_i`. A strict variant drops the neighbours.
- **Calibration** per belief kind `b`: `C_b = sum(contained_i) / n_b` over
  instants of kind `b`, beside its nominal (0.95 for `fit` and `held`; 1.0
  for regions, which are bounds) and a Wilson interval
  (`metrics.wilson`).
- **Sharpness** per kind: the median and the mean of `log(area_i)`, area in
  square metres (cells).
- **Binding:** for `fit` instants, the share whose slot's agent is the
  agent of the truth player nearest the fit within `GATE_M`, counted on
  unambiguous pairs as the Riot scorer counts identity.
- **Comparison with today:** the share of truth-alive instants that are
  contained with area at most 20 m^2, against today's located share; and
  the stacked misses (`missed_stacked`) contained in their slot's region.

Sets: development is the fixed handful (`3694746e4e54`, `a06f04a0059f`,
`bdfdcf009dba`) and the replay; the held-out six of the `ally_prior` run
(`a1a995e6b19b`, `b7d24102a6f6`, `e37fdeca944f`, `bfad2778a372`,
`5822b6646448`, `ff636d173b07`) are scored once, with the parameters fixed.
The predictions sit in the store's `notes/predictions.jsonl` (task
entity-state-20261004, design predictions E1-E8), logged before any slot
state exists. On the held-out six, at Riot kill instants, allies only:

- E1: `lost` at most 0.01 (the prior-first prototype lost 0.13).
- E2: containment over all truth-alive ally instants at least 0.90.
- E3: `fit` and `held` containment at least 0.93, at the nominal 0.95.
- E4: at least 0.85 of the stacked teammates the ring fits miss lie in
  their slot's region.
- E5: median region area at most 10 m^2 over all ally instants, and at most
  150 m^2 over instants of the `crowd` and `reach` kinds.
- E6: binding right on at least 0.90 of unambiguous fit pairs.
- E7: the share contained with area at most 20 m^2 at least the stored
  pieces' matched share on the same instants.
- E8 (development, the replay): every-frame ally containment at least 0.90
  and median area at most 10 m^2.

## 9. Ability children

An ability instance is a child slot of its caster's player slot.

### The child slot

Key `<parent slot key>:<slot letter>:R<round>:<n>`: the parent, the tray
slot the ability sits in (C, Q, E, X; the signature is always E
[domain:abilities/signature-on-e]), the round and the instance's ordinal.
Fields: `status` (`live`, `live_assumed`, `ended`), `open` and `end`
intervals `{lo_ms, hi_ms, basis}`, the anchor belief, the shape, the effect
region, a motion class, and the effects bound to it.

### Lifecycle and evidence

| Evidence | Channel and owner | Who | Opens | Ends |
|---|---|---|---|---|
| tray drop the cast gate accepts | `tray`, `ability_timeline.player_tray_casts`, `adjudication.ability_state` | the player | yes | |
| ability audio around a cast | `adjudication.ability_audio` | the player | names the slot | |
| spectated kit's tray | `adjudication.tray_kit` (`kit:spectating`) | a spectated teammate | yes | |
| minimap drawing | `ability_shape`, `smoke` (owner `adjudication.smokes`), `ability_icon` | own team, and the few enemy drawings | yes | drawing gone where it would show |
| ultimate voice line | `adjudication.ult_cast` | either team | yes (X) | |
| killfeed weapon-slot ability | `adjudication.weapon` | the killer | yes, if none is live | |
| killfeed assist icon | `reticle/killfeed_assist.py` (branch assist-panel-20261004-wf4), `adjudication.assist` | the assister | yes, if none is live | |
| a duration fact | `domain/abilities.toml` | | | open + duration |
| the owner's death | death owner, with a per-ability fact that it ends | | | only where a fact says so |
| round end | `rounds` | | | `round_end_assumed` |

- **Opening** takes the first evidence. Its time is an interval, since a
  drawing appears after the cast (the replay shows Recon Bolt rings drawn
  about 0.3 s after the bolt opens, `prototypes/replay_abilities.py`).
  Later evidence of the same instance joins it.
- **The charge constraint.** Opening a child spends one charge of the
  parent's slot. For the player the charge state is `ability_state`'s. For
  every other parent the state is an interval: at most the slot's
  `max_charges` (a fact, else the catalogue's confirmed count
  [domain:abilities/catalogue-charge-counts-confirmed]) at round start, plus
  the restocks its recharge fact allows [domain:abilities/recharge-kinds].
  Children opened in a round never exceed that bound, as living slots never
  exceed the roster. Evidence past the bound joins an existing child first;
  failing that, it is a stored surprise (an unseen restock, a misattributed
  caster), never a silent extra charge. Astra's stars are one shared pool
  [domain:abilities/astra-stars-shared].
- **Ending.** Evidence ends a child: a drawing gone where it would show, a
  destruction cue, the duration fact. Without evidence the child persists:
  the player's rule is that a deployed ability is still there, and a
  few seconds late is acceptable. Such a child is `live_assumed`, `rests_on`
  its placement, and ends at round end. A dead owner ends a child only
  where a fact says so (Regrowth is channelled); thirteen
  persist-after-death facts cover placed abilities.

### Shape geometry is per-ability data

Each ability's shape comes from its own fact
[domain:abilities/ability-rules-are-unique], never by analogy. A geometry
fact in `domain/abilities.toml` carries:

- `shape`: `point`, `circle`, `segment`, `polyline`, `area`, `cone` or
  `trajectory`;
- world sizes: `radius_m`, `length_m`, `width_m`;
- `duration_s`, `persists_after_owner_death`, `ends_on`;
- for a moving child, `speed_m_s` and whether it is piloted;
- `effect`: what the region does (blocks sight, damages, reveals in line of
  sight within a radius, blinds, concusses, slows).

Sources, in order: a fact the player gave or a measurement recorded; the
extracted game files (`AbilityTuning_*` rows, `TimedStateComponent`
durations; extraction is allowed while the game is closed, and
[ABILITY_STATES_GAMEDATA.md](ABILITY_STATES_GAMEDATA.md) says where the
states live); a minimap drawing size measured per map
(`ability_candidates.TABLE`), turned into metres through the world frame. A
field with no source refuses with `no-fact:<agent>:<slot>:<field>`, as
`ability_state` refuses a missing charge count. The owner of this table is
`ability_candidates`, which already reads the drawing facts' values; it
gains the world fields.

Recorded today: a drawn size for Regrowth, Recon Bolt, Hunter's Fury,
Barrier Orb, Blaze, Lockdown (enemy colour), Trademark, Rendezvous, Sonic
Sensor, Chokehold, Miks' Waveform and Bassquake, and Nebula; a duration for
Cloudburst, Waveform, Blaze (8 s, start uncertain), Ruse (about 15 s drawn),
Run It Back (about 10 s) and the used Wingman (length unknown). Of the
mechanics sheet's 116 ability rows, 94 have no duration and 103 no recorded
geometry; 88 have neither. They are, by agent:

- Astra: X Astral Form / Cosmic Divide
- Breach: C Aftershock, Q Flashpoint, E Fault Line, X Rolling Thunder
- Brimstone: C Stim Beacon, Q Incendiary, E Sky Smoke, X Orbital Strike
- Chamber: Q Headhunter, X Tour De Force
- Clove: C Pick-me-up, Q Meddle, X Not Dead Yet
- Cypher: Q Cyber Cage, X Neural Theft
- Deadlock: C Barrier Mesh, E GravNet, X Annihilation
- Fade: C Prowler, Q Seize, E Haunt, X Nightfall
- Gekko: C Mosh Pit, E Dizzy, X Thrash
- Harbor: C Storm Surge, Q High Tide, E Cove, X Reckoning
- Iso: C Contingency, Q Undercut, E Double Tap, X Kill Contract
- Jett: Q Updraft, E Tailwind, X Blade Storm
- KAY/O: C FRAG/ment, Q FLASH/drive, E ZERO/point, X NULL/cmd
- Miks: C M-pulse, Q Harmonize
- Neon: C Fast Lane, Q Relay Bolt, E High Gear, X Overdrive
- Omen: C Shrouded Step, Q Paranoia, E Dark Cover, X From the Shadows
- Phoenix: Q Hot Hands, E Curveball
- Raze: C Boom Bot, Q Blast Pack, E Paint Shells, X Showstopper
- Reyna: C Leer, Q Devour, E Dismiss, X Empress
- Sage: Q Slow Orb, E Healing Orb, X Resurrection
- Skye: Q Trailblazer, E Guiding Light
- Sova: C Owl Drone, Q Shock Bolt
- Tejo: C Stealth Drone, Q Special Delivery, E Guided Salvo, X Armageddon
- Veto: C Crosscut, E Interceptor, X Evolution
- Viper: C Snake Bite, X Viper's Pit
- Vyse: Q Shear, E Arc Rose, X Steel Garden
- Waylay: C Saturate, Q Lightspeed, E Refract, X Convergent Paths
- Yoru: C FAKEOUT, Q BLINDSIDE, E GATECRASH, X DIMENSIONAL DRIFT

The list comes from the sheet's Duration and Minimap cells and the drawing
facts; the abilities with a drawn size still lack a world size and, but for
Waveform, a duration.

### Anchor belief and effect region

- **Anchor.** A drawn child takes a `fit` anchor from its drawing's fit
  (`ability_shapes`: ring centre, segment, curve). An undrawn child's anchor
  is the parent's belief at the open, dilated by the ability's placement
  range where a fact gives one; with no range fact the anchor stays the
  parent's region and says `anchor_unread: no_range_fact`.
- **Orientation** for segments and walls comes from the fitted drawing, else
  from the parent's facing at the cast, else stays unread.
- **Effect region** is the shape placed at the anchor, read through the
  sightline tables in world metres: a smoke's circle cuts sight lines that
  cross it; a reveal is the `los_bits` row of the anchor cell within the
  radius; an area is its cells. The effect region inherits the anchor's
  uncertainty: it is the union over the anchor region's cells, and stores
  its certain core (the intersection) beside it.

### Moving children

Drones, dogs, Seekers and Boom Bot carry a player-like belief: `fit` where
drawn (a piloted drone draws a cone [domain:abilities/piloted-drones-have-cones];
Skye's bird draws like an ally [domain:minimap/skye-bird-like-ally]), and
`reach` with the child's own `speed_m_s` when unseen. Without a speed fact the
child keeps its last fit and widens nothing (`no_speed_fact`). They occupy a
small child axis in the per-frame arrays (capacity: the most children moving
at once in the round), with the player-slot fields.

### Effects

An effect binds to the parent's live child of the named ability:

- **kill:** a killfeed death whose weapon slot the weapon owner names as the
  ability, killer the parent's agent;
- **assist:** an assist-panel entry whose assister is the parent's agent and
  whose icon `adjudication.assist` names as the ability;
- **no effect observed:** a child that ends with neither. This is not
  "missed": the store cannot see whom an ability failed to touch. A child
  whose effect region held a believed enemy slot (section 7) while live and
  that bound no effect records `exposed_no_effect`, with the enemy slots it
  rests on.

Where several children of one ability are live, the effect binds to the one
whose effect region holds the victim's death place, then to the latest
opened; the binding `rests_on` the death and weapon or assist verdicts and
`depends_on` the arbiter's killer or assister verdict. A child inside a
crowd keeps the crowd's resolution: a dog among teammates that bound no kill
is enough (the player's bar).

### Storage and events

Children are rows, not frames: one `child` entity row per child in the
`entity_ability` lane (a family `ability_object` already admits any ability
kind), `event` rows `open`, `end`, `effect`, `relocation`, and the moving
children's per-frame rows in the slot npz's child axis. Phases come only
from each ability's lifecycle facts (`entity_contract.STATE_VOCABULARY`).

### Effect-level evaluation against the replay

The replay holds each mapped ability actor's owner, spawn point, open and
close [domain:replay/vrf-ability-actors] and each cast's slot and time
[domain:replay/vrf-cast-records]; one replay has a capture so far
[domain:replay/vrf-ability-truth-per-replay].

- **Pairing:** a child pairs with a replay actor of the same owner (the
  parent slot's agent) and ability whose open lies within
  `CAST_GATE_MS` of the child's open interval, one to one, nearest first.
- **Open:** recall and precision per ability; open-time error.
- **Life:** end-time error and the interval overlap
  `|child ∩ truth| / |child ∪ truth|`, with `live_assumed` children counted
  apart.
- **Anchor:** the actor's spawn point inside the anchor region, and the
  region's area.
- **Effect:** each paired actor's truth effect is `kill` where a Riot kill
  by its owner with that ability's damage lies inside its life, `assist`
  where Riot credits its owner an assist on a kill inside its life (Riot
  names no assisting ability, so this truth is per owner and life window),
  else `none`. The score is the confusion matrix of the child's effect
  against the truth effect, and the share in agreement.

## 10. What this cannot do

- Place a player on a floor. The minimap is a plan; levels exist only on the
  two 3D maps, and the path table ignores drops, ropes and one-way routes.
- Make an enemy belief sharp without a sighting. Unlit is unknown.
- Resolve members inside a crowd. A crowd is one region, by design.
- See a teammate's cast that draws nothing and makes no sound the readers
  read. Such a child never opens, and the charge bound stays loose for
  every parent but the player and a spectated teammate.
- Name a disconnect, or place a revived player, without the facts in
  section 12.
- Give a world frame on a map without `shade_fit` or map constants, or a
  reach region on a map without a path table.
- Show anything during play.
- Score on much truth: Riot positions exist only at kill instants on 21
  matches, and one replay has a capture.

## 11. Owners

Each question gets one owner; the entries join `ownership.toml` with the
code that answers them, not before.

| Question | Owner | Defers to |
|---|---|---|
| Which player slots are open this round, and why did each open or close? | new `slot_state` (entities layer) | `rounds`, `lineup`, `roster`, `death-victim`, `killfeed-entry-type`, `round-entity` (death binding), `teleport-licence` |
| Where is a slot believed to be at a frame nothing observed? | `belief` ([owns:position-belief]), its question widened from the player to every slot | `track-continuation`, `widget-drawn`, the map's path table |
| Which slot is this fit? | `adjudication.identity` ([owns:agent-identity]), a new `assign_slot_fits` beside `assign_ally_pieces` | the slot beliefs as a prior, weighed once |
| Where is this map in world metres? | `geometry` ([owns:map-geometry]), a baked `world_affine` | valorant-api's map constants, `widget_frame` |
| Which ability instances exist, which charge each spent, and which effects bind to each? | new, beside `slot_state`; the `ability-owner` question it answers has no owner today | `ability-state`, `ult-cast`, `killfeed-weapon`, the assist owner, `ability-candidates`, `agent-identity` |
| What shape and duration does each ability have in the world? | `ability_candidates` ([owns:ability-candidates]), its table widened to world fields | `domain` |

## 12. Facts to ask the player for, or to read from the game files

1. The top running speed in metres per second (a game-file read of the
   character's walk speed would do), and whether weapons change it.
2. Whether a disconnected teammate stays drawn on the minimap, and whether
   the roster counts him.
3. Where a resurrected player stands: at the corpse, or elsewhere.
4. Each ability's duration and world shape (section 9's list), and each
   thrown ability's placement range.
5. Which abilities move their caster farther than running
   [domain:abilities/movement-abilities-are-dashes-and-teleports]; the
   mechanics sheet holds the candidates.

## 13. Stages and acceptance

1. **Slot state from stored rows.** The world frame baked into `geometry`;
   `slot_state` and the belief law over stored `ally_icon`, `death`, lineup,
   roster and rounds; the Riot and replay scorers' slot mode.
   Acceptance: `prototypes/riot_ground_truth.py --all --slots --record` and
   `prototypes/replay_truth.py score 9acf02f98283 --slots --record`.
   Evidence: predictions E1-E8 judged on the held-out six, scored once.
2. **The assignment in the arbiter; deaths close slots; the ally lane.**
   Acceptance: `reticle project SESSION` (the lane validated by
   `entity_contract`) and the full suite.
   Evidence: binding share at least the stored pieces' on unambiguous pairs.
3. **`round_entity` as a view.** Acceptance: the Riot scorer's 0.6.2 counts
   reproduce from the view within the pairing's ties. Evidence: matched
   and identity counts per session.
4. **Prior-first reading from the beliefs.** Acceptance: `reticle trial`
   on the handful against the full reader. Evidence: same-or-better
   containment at lower cost.
5. **Enemy slots.** Evidence: enemy containment at Riot kill instants.
6. **Ability children:** the player's kit, then teammates' drawn and voiced
   abilities, then enemies. Evidence: section 9's replay scores on
   9acf02f98283 and each later replay kept with a capture.

The sizing in sections 2 and 6 comes from `prototypes/entity_state_probe.py`
(predictions ES1-ES3, task entity-state-20261004). A reach region read along
the path table holds a median
[metric:entity_state_probe/reach_ratio#ratio_5m_min=0.9068] to
[metric:entity_state_probe/reach_ratio#ratio_5m_max=0.9178] of the walkable
cells a 5 m Euclidean disc holds, so walls cut little at that radius; against
the full pixel disc `belief.Fix` draws, the 5 m region covers
[metric:entity_state_probe/reach_ratio#split.disc_share_5m=0.6494] (Split) to
[metric:entity_state_probe/reach_ratio#lotus.disc_share_5m=0.7385] (Lotus),
and the 10 m region
[metric:entity_state_probe/reach_ratio#split.disc_share_10m=0.4679] to
[metric:entity_state_probe/reach_ratio#lotus.disc_share_10m=0.5252]. Most of
the sharpening an unseen teammate's region gains must therefore come from
negative evidence, not from walls.
