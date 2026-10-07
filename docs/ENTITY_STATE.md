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
  death's X. When the region test admits no slot, the candidates fall back
  to every living slot of the victim's team the arbiter does not exclude,
  and the empty test is stored as a calibration surprise. One admitted slot
  closes, its close `depends_on` the other slots' verdicts. Several admitted slots stay `alive` with `maybe_dead`
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
| `fit` | a disc of radius `r_fit` round the fit | the fit's world position | that frame's fit (`observation_key`) |
| `held` | the last fit's disc | the last fit | the last fit, while the cheap check finds the icon's pixels unchanged (`ally_prior` design) |
| `crowd` | the host's disc of radius `2 r_icon + r_fit`, together with the slot's `reach` region grown since the merge | the host's fit | the slot's last fix, and the host slot's fits (`depends_on` the host's assignment) |
| `reach` | the Euclidean disc of radius `R(t)` round the anchor, over every standable cell (box tops included), less the forward-carried exclusions of the frame (below) | the anchor | the anchor fit, and the frames whose exclusions it carries |
| `spawn` | the team's spawn callout region (round start, before the first fit) | the callout's location | valorant-api's map callouts |
| `last_known` | enemies only: the "?" mark's place, then `reach` from it | the mark | `minimap_objects.last_known` |
| `unanchored` | the whole map | none | nothing: a slot with no fix since the round opened |

The `crowd` kind (amended 2026-10-04, critique) covers the stacked
teammate: a slot that loses its fit while its last fix lies within one icon
diameter (`2 r_icon`) of a fit assigned to another slot, the self slot
included, **rides** that host [domain:minimap/coincident-icons]. Its point is
the host's fit; its region is the host disc together with its own reach
region, so a member who leaves the stack unseen is never cut out. It ends at
the slot's next fit, or when the host loses its fit (then `reach`). A tracked
blob (`crowd_blob.FrameBlobs`) may replace the host disc only after its
capacity check: when the blob explains fewer members (mass over one isolated
icon's mass) than it holds, every member's region becomes the blob together
with the reach grown from the last frame where the capacity agreed. The
host disc alone is the crowd's **core**; it is scored apart and never stands
as the reported region.

### Exact form

- **Point:** world `(x, y)` in metres (section 3) and `level`, the floor
  index, or null with a reason.
- **Fit radius:** `r_fit = r_icon + v_max * dt_frame`: one icon outer
  radius in metres (the reader's measured radius times the world frame's
  metres per baked pixel; one scale transform, no per-size table) plus the
  distance a player covers in one frame period, since a truth instant falls
  within a frame of the one drawn. It comes from geometry and a game fact,
  never from truth. Stored ally fits lie a median
  [metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#ally_err_cm_median=76.0] cm from
  the replay, 90th percentile
  [metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#ally_err_cm_p90=159.0] cm; the
  scorers measure the disc's calibration and never set it (amended: the
  first draft fitted `k` on development truth, a threshold taken from
  truth).
- **Reach:** `R(t) = v_max * (t_game - t_anchor) + r_fit`, with
  `t_game` from the game-time owner (`gametime.SessionGameTime`), so a
  capture stall does not freeze the growth. `v_max` is the character's top
  ground speed from the game files [domain:game_data/character-movement-speeds]:
  675 units/s with the largest state multiplier, 1.1 (Jumping), so 7.425 m/s
  [domain:game_data/game-units-centimetres]; every weapon multiplier
  valorant-api lists is below one. The bound is the **Euclidean** disc over
  every standable cell (floor, plant and box tops). The path table
  (`prototypes/sightlines.py`) models no drops, ropes, teleporters, doors,
  box tops or vaults (its own docstring), so path distance ranks and
  predicts but never bounds, until directed edges for drops, ropes and
  teleporters come from game files or recorded facts and the replay shows
  the path bound never excludes a truth position. The probe measured what
  the Euclidean disc gives up: about 9% of the walkable cells at 5 m.
  `minimap.RUN_PX` stays the tracker's association gate and never sizes a
  region: it is a bound measured on the pipeline's own tracks, in widget
  pixels.
- **Kits that move faster than running.** When the slot's kit holds a
  movement ability [domain:abilities/movement-abilities-are-dashes-and-teleports]
  whose charge state is not known spent, or a movement child of the slot is
  open, the reach region carries `kit_unbounded`: the disc bounds running
  only. The flag is scored apart.
- **No velocity in the region.** A reach region is a bound, not a
  prediction; the reader's prior-first search may predict a place to look
  (the `ally_prior` design), and that prediction never narrows a region.
- **Timing** (proposed 2026-10-06, [RENDER_DELAY.md](RENDER_DELAY.md)
  section 6): a fit keeps its render time; a remote slot's reach anchor is
  server time, render time less the match's remote-delay band's upper end
  [domain:capture/minimap-remote-player-lag].

### Updates, per observation type

1. **A fit assigned to the slot** sets `fit`, whatever the prior said. When
   the fit lies outside the prior region, the slot stores a `relocation`
   and the teleport-licence verdict (section 1). Observations always win.
2. **A cheap check that holds** (unchanged pixels at the predicted icon)
   sets `held`.
3. **Crowd entry.** A slot whose last fix lies within one icon diameter of
   another slot's fit sets `crowd`: no per-member pose, members set-valued
   (the player's rule: nobody cares whether one teammate stands 10 cm right
   of another). A fit of the slot, the host's lost fit, or the blob's
   capacity check ends it; the region always holds the member's own reach,
   so the split detector firing late costs sharpness, never containment.
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
- the reader **searched** `c` at frame `t`: it described the frame and
  `c` lies inside its search (the whole widget for a full read; the
  prior-first windows for a prior-first read). The reader stores what it
  searched; where it does not, `p_det(c, t) = 0`;
- the pixels at `c` **positively match the baked floor**: the soft residual
  of the frame against the geometry's base map and lighting reference
  (`(map, profile)` geometry [domain:capture/session-pixels-are-not-the-map])
  scores the cell as bare floor. A cell no reader marked as occluded is not
  thereby empty; an unread ping, an undrawn ability or an unfitted enemy
  icon fails this test and gives no absence;
- the reader's detection probability `p_det(b)` for an unoccluded isolated
  icon on background class `b` (floor shade and lighting class, not a
  per-cell rate) is measured on the replay's every-frame truth, stored with
  its provenance and version stamp, and taken at its lower Wilson bound.

**The region is a forward-reachable set, not an absence score** (amended
2026-10-04; the draft's per-cell score never moved with the player). Per
frame:

    region_t = dilate(region_{t-1}, v_max * dt) \ excluded_t
    excluded_t = cells where independent looks since the last fix give
                 absence evidence above the cut, counted in this frame only

An exclusion holds for the frame that observed it and is carried forward
only through the dilation, so a cell cleared while the teammate stood
elsewhere re-enters the region as soon as the teammate could have walked
there. The dilation is Euclidean over standable cells
(`scipy.ndimage.binary_dilation` with a disc element, or a distance
transform), never along the path graph, for the reason under **Reach**.

**Looks, not frames.** Frames 67 ms apart are not independent: a reader
that misses an icon on a bright patch misses it again next frame. One
**look** is counted per change of background, occluder or icon
configuration at the cell, or per decorrelation interval measured on the
replay (the lag at which the reader's miss autocorrelation falls under
0.1), whichever comes later. The absence evidence a cell can gain inside one
interval is capped at one look's.

**Negative evidence is off until measured.** Stage 1 runs with `p_det = 0`
everywhere, so a reach region is the plain Euclidean disc; the stored
reader records neither its search nor a floor residual today. Negative
evidence turns on per background class only when `p_det(b)`, the
decorrelation interval and the searched-cell record exist, and the replay
check passes: the every-frame truth never falls outside a reach region,
and the region at any instant is recomputable from stored rows. A
`region_exhausted` surprise (the cut empties the region) still stores the
frames that emptied it; the replay check is the guard for the truth cut out
of a region that is not empty. The causes to check are a missed death, a
teleport, a reader miss and a wrong lineup.

**Search cost.** Under prior-first reading, a reach slot is the surprise
path: its region widens the reader's search, and only searched cells give
absence. Section 6 budgets that search.

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

**Causal online, smoothed after the round** (amended 2026-10-04). The
figures above compare continuity with a stored entity verdict pooled over
the whole entity, future frames included, which a real-time update cannot
have. Online, the portrait term uses only causally pooled evidence (the
entity's frames up to `t`), and the emergence comparison is measured again
with causal pooling before continuity is told to abstain. The lane publishes
the online assignment; the post-round smoothing adds revision rows that
cite it. The smoothing runs jointly per frame over assignments (a Viterbi
whose states are the frame's permutations of fits to slots, vectorised in
numpy), so one fit never serves two slots; a per-slot Viterbi cannot
enforce that. `maybe_dead` resolves online only on evidence already seen;
its resolution by a later sighting is a revision row.

**Self fits.** While the player lives, the self marker binds to the self
slot directly (`belief.Fix`, the self channel). After the player's death a
self fit binds to the slot the spectating witness names (`adjudication.tray_kit`,
`kit:spectating:<agent>`), `rests_on` that witness; the assignment decides
only where no witness exists. Stored `tray_kit` rows exist on four of the
ten scored sessions (`a06f04a0059f`, `c62c2b06bcfb`, `c40d950031bb`,
`4f207c0c4e39`); on the other six every spectated self fit goes to the
assignment until `reticle tray-kit` writes their rows (not run here).

**One unit.** Every cost is a log-likelihood per square metre: the
Gaussian density for `fit`, `held` and the crowd core, `-log(area)` for a
uniform region. The non-player and unobserved prices are fitted on
development truth as rates (how often a fit is a non-player; how often a
living slot draws no fit), stamped with a version, and never set from
refusal reasons, which are not probabilities.

The stage 1 prototype (`prototypes/entity_state.py`) is the post-round
path only: it binds fits to slots through the stored entity verdicts and
continuity, `rests_on` those verdicts, and says so in every output. The
stage 2 prototype (`prototypes/entity_binding.py`, `--binding causal`)
is the online path: one assignment per frame over every stored fit, from
each slot's belief at `t` and each fit's own portrait, with a non-player
column per fit; each slot carries its chain's decayed portrait evidence,
and chains move between slots when that evidence names another
assignment. Both modes are scored side by side (section 13).

## 3. The coordinate frame

**Canonical coordinates are world metres** in Riot's game frame: game
units over 100 [domain:game_data/game-units-centimetres], the frame
Riot's records and the replays use. Minimap pixels are a view.

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
  [domain:replay/vrf-yaw-is-view-radians]. The affine swaps axes, a
  reflection, and the image's y runs down, so an angle offset would turn
  facing the wrong way: facing passes as a direction vector through the
  inverse affine's linear part and is renormalised. A test against the
  replay's yaw on 9acf02f98283 checks the sense of rotation, not only the
  offset.
- **Turns and variants.** A side-based widget turns between rounds
  [domain:minimap/side-based-widget-turns-between-rounds] and a variant
  widget scales; `widget_frame` undoes both before the affine, so world
  coordinates never turn.
- **Floors.** The minimap is a plan; two players on different floors can
  share a point [domain:minimap/coincident-icons], and floor shade only
  hints at height [domain:minimap/floor-shade-is-elevation]. No reader
  reads a level. `level` is a bitmask (u2): zero with `no_level_reader` on
  2D maps; on maps with a 3D table (`prototypes/sightlines_3d.py`: Ascent
  and Split) the set of standable layers of the point's 1 m column, never
  one guessed.
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
| `level` | u2 | 2 | standable layers, a bitmask; 0 unread |
| `x`, `y` | f4 x 2 | 8 | metres; NaN under `no_world_frame` |
| `px`, `py` | f4 x 2 | 8 | baked widget pixels, always |
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

A slot-frame takes 45 bytes and a frame 450, plus a 14-byte header
(`t_ms` f8, `frame_idx` i4, `drawn` u1, `menu` u1): 464 bytes. A 25-minute
match at 15 Hz holds 22,500 frames, about 10.4 MB before compression. The
stage 1 prototype stores less and measures its own bytes per frame.

**Every region is recomputable at any instant** from stored rows: the
filter is deterministic over the anchor, `R(t)`, the host and (once on) the
stored exclusions, so a scorer asks for the region at a Riot kill instant
instead of reading a stale 2 Hz copy. Region cell lists (`reach` and
`crowd` kinds) are also stored as a ragged array (`frame_idx`, `slot`,
offset into one int16 cell array) at 2 Hz and at every kind change, for
queries that want cells, not for scoring. Once negative evidence is on, the
per-frame exclusions it carried are stored with the frames, since the
region cannot be rebuilt without them.

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

`round_entity` becomes a view over slots: **one entity per slot life**
(open to close), in today's row schema plus `slot_id`, with the observed
runs as sub-intervals (amended 2026-10-04: one entity per observed run
split today's entities at every gap and changed their ids and counts).
Before step 3 a mapping from every old entity id to its slot id ships, and
every stored `identity_claim` and death binding is re-pointed through it and
checked. `live_assumed` and `over_bound` join
`entity_contract.STATE_VOCABULARY` with the code that emits them. The
migration runs in order; each step is reversible and scored before the
next.

**Layering.** Stage 1 is a prototype only (`prototypes/entity_state.py`,
not wired). Before stage 2 puts `slot_state` in `reticle/`, the sightline
builder moves into `reticle` as a baked part of the geometry, owned by
`map-geometry`, versioned and keyed by `(map, profile)`; `reticle/` never
imports a prototype. Each hiding-set input is listed with its stored
stream: ally fits (`ally_icon`), crowds (none stored; `crowd_blob` rows
exist only as analysis output), pings (`ping`), the hide owner
(`minimap_dark`), ability drawings (`ability_shape`, `smoke`). Where an
input is not stored for a frame, negative evidence is off for that frame.

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

**That probe timed a simpler algorithm than this plan specifies**
(amended 2026-10-04): one stateless row compare against a random
visibility mask on one map, with an unaugmented 5x5 assignment. It built no
hiding set, counted no looks, carried no exclusions, dilated nothing and
widened no search. "The readers set the cost, not the state" is therefore a
hypothesis. Two measurements decide it: the stage 1 prototype times the
belief law it implements (Euclidean reach, crowd riding, entity binding,
negative evidence off) per frame, single-threaded; and before negative
evidence turns on, the probe is rerun with the full per-frame pipeline
(hiding-set raster, per-look evidence, forward dilation, augmented
assignment) on the three development maps, with the reader's search
widened for reach slots, and its result is cited here.

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
  enemy icon within one icon radius is one look of absence evidence for
  that frame, under the same hiding rules as allies; it may exclude the
  cell from this frame's region only, and the exclusion moves forward
  through the dilation as section 2 states, never into a per-cell score.
  An unlit cell gives no look, since unknown is not dark. Enemy regions
  therefore stay wide. A sharp enemy belief comes only from a sighting.
- **Identity.** Enemy icons carry portrait features for the arbiter
  (`identity.claims_from_minimap_icons`); the same assignment binds them to
  enemy slots, over the enemy lineup from the arbiter and the board.
- **Enemy-owned children.** Enemy-owned ability children that draw like
  players (see the `domain/abilities.toml` facts) are alternatives to every
  enemy find; a find on one is that child's, never an enemy fit.
- **Other witnesses.** An enemy ultimate line (`adjudication.ult_cast`, with
  its side) shows a living enemy slot and places nobody; a killfeed death
  closes the slot as for allies.
- The replay holds no stored enemy coverage yet
  ([metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#enemy_coverage=0.0]); enemy
  calibration is first measured at Riot's kill instants.

## 8. Evaluation

Riot's records and the replay are evaluation truth only; neither feeds a
reader, a threshold, a prior or the transform.

### Truth instants

- **Riot:** every living player at each Riot kill instant, the victims of
  that instant included, aligned through stored deaths as
  `riot_ground_truth.py` aligns them, positions in world units over 100.
- **Replay:** every living player-tick and every open ability child of
  9acf02f98283 on the 15 Hz grid (`replay_truth.py`), interpolated across
  gaps up to `MAX_GAP_MS`, never wider. A find scores against the entity
  under it, of any class (AGENTS.md, "Replay truth covers every entity").

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
- **Strata.** Riot truth exists only at kill instants, which cluster in
  fights, so unseen stretches (lurkers), where reach regions are widest, are
  under-sampled there. Calibration and sharpness are reported by time since
  the slot's last fix (0, under 1 s, 1-5 s, 5-15 s, over 15 s), and the
  replay's every-frame truth weighs the long stretches properly.
- **Ability effects** are scored on all 21 Riot matches (Riot records each
  kill's ability) as well as on the replay's actors.

Sets: development is the fixed handful (`3694746e4e54`, `a06f04a0059f`,
`bdfdcf009dba`) and the replay. The held-out set is six Riot matches chosen
by the lowest `sha256('entity-state-heldout:' + session)` among those not in
development, not in the `ally_prior` held-out six and not named in any
crowd-prior-v4 prediction row: `75a55a296d3b`, `c62c2b06bcfb`,
`043bafca271a`, `59c70f1ef720`, `c40d950031bb`, `4f207c0c4e39`, scored
once with the parameters fixed (amended 2026-10-04: the first draft reused
the `ally_prior` held-out six, which that run had already scored; a
correction row in the store supersedes the set and keeps the original).
The predictions sit in the store's `notes/predictions.jsonl` (task
entity-state-20261004, design predictions E1-E8, and the prototype's
predictions P1-P8), logged before any slot state existed. At Riot kill
instants, allies only:

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
  exceed the roster. Evidence past the bound **always opens a child**,
  flagged `over_bound`: the parent's charge interval widens, the surprise
  is stored (an unseen restock, a pickup, a misattributed caster), and no
  evidence is dropped and no merge is made on capacity alone. Restocks the
  recharge fact lists are by timer and by kills [domain:abilities/recharge-kinds];
  pickups, recalls and reclaims (a Killjoy recall, a Cypher trapwire pickup,
  Gekko's reclaim) are not recorded and go to section 12. Astra's stars are
  one shared pool [domain:abilities/astra-stars-shared].
- **Joining.** Later evidence joins an existing child only inside that
  child's duration fact, or where the child's effect region holds the
  evidence; otherwise it opens a new child and spends a charge.
- **Ending.** Evidence ends a child: a drawing gone where it would show, a
  destruction cue, the duration fact. Without evidence, persistence follows
  the ability's **lifecycle class**, a per-ability fact (`deployed`,
  `instant`, `self_buff`, `equipped`, `movement`)
  [domain:abilities/ability-rules-are-unique]. Only a `deployed` child
  persists without evidence: the player's rule is that a deployed ability is
  still there, and a few seconds late is acceptable. Such a child is
  `live_assumed`, `rests_on` its placement, and ends at round end. A child
  whose ability has no lifecycle-class fact stores its end as refused with
  an interval (`no-fact:<agent>:<slot>:lifecycle_class`), never round end.
  A dead owner ends a child only where a fact says so (Regrowth is
  channelled); thirteen persist-after-death facts cover placed abilities.

### Shape geometry is per-ability data

Each ability's shape comes from its own fact
[domain:abilities/ability-rules-are-unique], never by analogy. A geometry
fact in `domain/abilities.toml` carries:

- `shape`: `point`, `circle`, `segment`, `polyline`, `area`, `cone` or
  `trajectory`;
- world sizes: `radius_m`, `length_m`, `width_m`;
- `duration_s`, `persists_after_owner_death`, `ends_on`;
- for a moving child, `speed_m_s` and whether it is piloted;
- `lifecycle_class`: `deployed`, `instant`, `self_buff`, `equipped` or
  `movement`;
- `effect`: what the region does (blocks sight, damages, reveals, blinds,
  concusses, slows), as a label only;
- `effect_query`: how the effect region is computed, per ability (for
  example `los_within_radius_from_anchor`, `cells_of_shape`,
  `sight_cut_by_circle`). Abilities that share an effect label do not share
  a query by that fact: alarm bots, sensors, cameras, Haunt and Recon Bolt
  each need their own;
- `drawing_to_scale`: whether the ability's minimap drawing is drawn to
  world scale.

Sources, in order: a fact the player gave or a measurement recorded; the
extracted game files (`AbilityTuning_*` rows, `TimedStateComponent`
durations; extraction is allowed while the game is closed, and
[ABILITY_STATES_GAMEDATA.md](ABILITY_STATES_GAMEDATA.md) says where the
states live); a minimap drawing size measured per map
(`ability_candidates.TABLE`), turned into metres through the world frame,
**only for an ability whose `drawing_to_scale` fact says so** or whose
world size a replay measured; a drawing is to scale for some abilities and
stylised for others. A field with no source refuses with
`no-fact:<agent>:<slot>:<field>`, as `ability_state` refuses a missing
charge count; a missing `effect_query` refuses the effect region. The owner of this table is
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
  range where a fact gives one. With no range fact the child stores **no
  anchor region** (`anchor_unread: no_range_fact`) and drops out of every
  region test; the parent's region never stands in for it.
- **Orientation** for segments and walls comes from the fitted drawing, else
  from the parent's facing at the cast, else stays unread.
- **Effect region** is the shape placed at the anchor and evaluated by the
  ability's own `effect_query`, read through the sightline tables in world
  metres; with no `effect_query` fact there is no effect region. The effect
  region inherits the anchor's
  uncertainty: it is the union over the anchor region's cells, and stores
  its certain core (the intersection) beside it.

### Moving children

Drones, dogs, Seekers and Boom Bot carry a player-like belief: `fit` where
drawn (a piloted drone draws a cone [domain:abilities/piloted-drones-have-cones];
Skye's bird draws like an ally [domain:minimap/skye-bird-like-ally]), and
`reach` with the child's own `speed_m_s` when unseen. Without a speed fact an
unseen child stores no region (`position_unbounded: no_speed_fact`) and
drops out of every region test; a frozen last fit never stands in for a
bound. Effects then bind by time window and the killfeed's ability alone.
They occupy a
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
  that bound no effect records `exposed_no_effect` as a probability: for
  each believed enemy slot (section 7), the share of its region inside the
  child's effect region while live, with the enemy slots it rests on. Any-cell
  overlap with a wide enemy region would mark nearly every child.

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

### Cross-channel cast witnesses (measured 2026-10-05)

`prototypes/ability_xchannel.py` (ledger `ability_xchannel/*`, not wired)
scored every stored channel that can witness another player's cast on the
21 Riot-recorded matches, against the replay's timed casts on 9acf02f98283
and Riot's per-player totals elsewhere. Predictions:
`ability-xchannel-20261005` in the store's `notes/predictions.jsonl`.

**Coverage.** Every match stores audio_others peaks, `ult_cast`, deaths and
assists; `smoke_owner` rows exist on 4 matches, `ability_fit` and
`ability_wall` on 5, `ability_icon` (unnamed discs, no witness) on 5,
`enemy_track` on 3. The replay match holds none of the minimap streams, so
it scores four channels: audio_others, `ult_cast`, the killfeed and the
assist panel [domain:killfeed/assist-panel].

**Per channel on the replay.** Audio_others pairs
[metric:ability_xchannel/replay@9acf02f98283#audio_others.paired=138] of
[metric:ability_xchannel/replay@9acf02f98283#audio_others.witnesses=434]
detections one to one across classes (precision
[metric:ability_xchannel/replay@9acf02f98283#audio_others.precision=0.318])
and hears [metric:ability_xchannel/replay@9acf02f98283#audio_others.other_hits=115]
of [metric:ability_xchannel/replay@9acf02f98283#audio_others.other_casts_in_vocab=372]
other players' casts. The ult line hears
[metric:ability_xchannel/replay@9acf02f98283#ult_cast.other_hits=22] of
[metric:ability_xchannel/replay@9acf02f98283#ult_cast.other_casts_in_vocab=22]
other players' ultimates at every distance
[domain:abilities/ult-lines-heard-by-both-teams]. Its
[metric:ability_xchannel/replay@9acf02f98283#ult_cast.unpaired.chamber.witnesses=3] unpaired rows are
Chamber's: the replay export's cast list holds
[metric:ability_xchannel/replay@9acf02f98283#ult_cast.unpaired.chamber.export_casts=0] Chamber ultimates, so
they have no cast to pair with. Riot's record of this match also counts
[metric:ability_xchannel/replay@9acf02f98283#ult_cast.unpaired.chamber.riot_casts=0]. Across matches, Riot
records 0 to 2 Chamber ultimate casts a match beside his Tour De Force
kills; that undercount is a separate observation.

The killfeed rows of the ability category on the replay are not all kills.
Of [metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.all.witnesses=15],
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.revive.witnesses=5] are Clove's Not Dead
Yet self-revives [domain:killfeed/revive-entries], cast witnesses that pair
with her ultimate
([metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.revive.paired_10s=5] within 10 s).
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.ability.kill.Headhunter.witnesses=7] are Chamber
Headhunter kills, which Riot does not count as ability kills. The remaining
three are a Blade Storm, a Turret and a Tour De Force kill. Riot records
[metric:ability_xchannel/replay@9acf02f98283#riot_other_kills=7] ability kills by other players on this
match, and [metric:ability_xchannel/replay@9acf02f98283#riot_other_kills_prior_cast=6] follow a cast of that
player and slot. The killfeed's kills pair with a prior cast
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.kill.paired_60s=9] of
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.kill.witnesses=10] times within 60 s,
against a chance floor of
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.kill.chance_60s=2.26] (a witness placed at
random in the match's rounds); within 10 s
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.kill.paired_10s=7], floor
[metric:ability_xchannel/replay@9acf02f98283#effect.killfeed.kind.kill.chance_10s=0.48]. The assist panel's
icons pair [metric:ability_xchannel/replay@9acf02f98283#effect.assist_icon.all.paired_60s=5] of
[metric:ability_xchannel/replay@9acf02f98283#effect.assist_icon.all.witnesses=5] within 60 s, but the floor
there is [metric:ability_xchannel/replay@9acf02f98283#effect.assist_icon.all.chance_60s=2.49], half of them;
within 10 s [metric:ability_xchannel/replay@9acf02f98283#effect.assist_icon.all.paired_10s=3] pair against a
floor of [metric:ability_xchannel/replay@9acf02f98283#effect.assist_icon.all.chance_10s=0.53]. The 60 s
window is loose for the panel; read it at 10 s.
Together the channels witness
[metric:ability_xchannel/replay@9acf02f98283#any_other.hit=128] of
[metric:ability_xchannel/replay@9acf02f98283#any_other.casts=372] other
players' casts.

**Independence.** One pair is testable on the replay, the assist panel and
audio_others. The panel draws only the player's team's assists (the corpus
holds no enemy assist icon), so its opportunities are allies' casts only:
over [metric:ability_xchannel/independence@9acf02f98283#replay.assist_icon-vs-audio_others.n=68] shared casts the
odds ratio is
[metric:ability_xchannel/independence@9acf02f98283#replay.assist_icon-vs-audio_others.odds_ratio=5.6471], Fisher p
[metric:ability_xchannel/independence@9acf02f98283#replay.assist_icon-vs-audio_others.fisher_p=0.18653]. The ult
line misses nothing and the killfeed has three shared kill casts.
X2 therefore fails on its pre-registered instrument
([metric:ability_xchannel/independence@9acf02f98283#X2_holds=0]). The
causes are measurable per channel instead: audio_others hears
[metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.dist.0-20m.hits=41]
of [metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.dist.0-20m.casts=83]
casts within 20 m,
[metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.dist.20-40m.hits=56]
of [metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.dist.20-40m.casts=128]
at 20 to 40 m,
[metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.dist.40mplus.hits=18]
of [metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.dist.40mplus.casts=122]
beyond, and none of
[metric:ability_xchannel/independence@9acf02f98283#cause.audio_others.live.False.casts=52]
casts while the player is dead; no other channel depends on distance. Over
match cells (added after the pre-registration) version 0.1.0 found the smoke
owner and the assist panel missing together; that came from counting enemy
cells against a team-only panel. Limited to allies' cells the pair has
[metric:ability_xchannel/independence@9acf02f98283#cells.assist_icon-vs-smoke.n=4] cells and no test, and no cell
pair is correlated. The one structural correlation left is the dead
listener, shared by the two audio channels, though the ult line still heard
one of one such ult.

**Combination.** The dev half chose one rule per (agent, slot). Version
0.1.0 corrected the dev half's audio share with the HELD absent-agent
false-alarm rate, a leak into the rule choice; version 0.2.0 uses the dev
half's own rate, cross-fitted leave one session out because the dev
threshold was fitted on the same sessions. On the held half
[metric:ability_xchannel/combined#X1_passing=4] of [metric:ability_xchannel/combined#X1_eligible=88] classes reach
count precision 0.8 with recall above their best single channel, all
ultimates (Clove, Jett, Raze, Sage): X1 fails, as P1 predicted.

Where no rule reaches 0.8 on dev, the choice falls back to the most precise
rule below the bar, and most classes fall back to audio_others alone
([metric:ability_xchannel/combined#held.all.classes.audio_others=50] classes). The combined gain
is therefore mostly audio_others alone. Over all classes, allies' held
coverage rises from [metric:ability_xchannel/combined#held.all.total.ally.today_covered=261] to
[metric:ability_xchannel/combined#held.all.total.ally.chosen_covered=697] of
[metric:ability_xchannel/combined#held.all.total.ally.riot=2237] Riot casts against
[metric:ability_xchannel/combined#held.all.total.ally.expected_false=314.1] expected false
alarms, a net gain of [metric:ability_xchannel/combined#held.all.total.ally.net_unclipped=121.9]
to [metric:ability_xchannel/combined#held.all.total.ally.net_prop=274.9]; enemies' from
[metric:ability_xchannel/combined#held.all.total.enemy.today_covered=161] to
[metric:ability_xchannel/combined#held.all.total.enemy.chosen_covered=1164] of
[metric:ability_xchannel/combined#held.all.total.enemy.riot=2957], net
[metric:ability_xchannel/combined#held.all.total.enemy.net_unclipped=355.0] to
[metric:ability_xchannel/combined#held.all.total.enemy.net_prop=524.4]. Of the gained casts,
audio_others alone gives [metric:ability_xchannel/combined#held.all.rule.audio_others.ally.gained=397]
of [metric:ability_xchannel/combined#held.all.total.ally.gained=436] (allies) and
[metric:ability_xchannel/combined#held.all.rule.audio_others.enemy.gained=943] of
[metric:ability_xchannel/combined#held.all.total.enemy.gained=1003] (enemies). Counting only the
classes whose dev rule passes the bar (the others keep today's count),
allies gain [metric:ability_xchannel/combined#held.passing.total.ally.gained=39] against
[metric:ability_xchannel/combined#held.passing.total.ally.expected_false=21.8] expected false
alarms and enemies [metric:ability_xchannel/combined#held.passing.total.enemy.gained=60] against
[metric:ability_xchannel/combined#held.passing.total.enemy.expected_false=20.1], nearly all from
the union rule. Every figure is an upper estimate: the null corrects only
absent-agent false alarms, and the replay's timed precision is lower. On the replay, requiring a second
channel admits
[metric:ability_xchannel/replay@9acf02f98283#agree.admitted=73] audio
detections at precision
[metric:ability_xchannel/replay@9acf02f98283#agree.precision_admitted=0.589].

**Effects.** Of [metric:ability_xchannel/effects#kill.kills=105] Riot
ability kills by other players, the killfeed names the ability on
[metric:ability_xchannel/effects#kill.killfeed=71]. Of the 34 it misses,
33 are weapon refusals on a death the killfeed read (`new` 19,
`no_observation` 12, `too_few_named` 2): Showstopper, Paint Shells,
Overdrive, Nanoswarm, Hunter's Fury, Mosh Pit, Tejo's Ability2 and three
others. Read the refusal before tuning the gallery. A cast witness lies within 10 s
before [metric:ability_xchannel/effects#kill.cast_witness_10s=67] kills,
of which [metric:ability_xchannel/effects#kill.audio_chance_10s=10.3] a
random placement of the audio detections would explain;
[metric:ability_xchannel/effects#kill.cast_witness_no_audio_10s=30] without
audio. The killfeed or a cast witness explains
[metric:ability_xchannel/effects#kill.either_10s=97]. P4 (under half) fails.
Of [metric:ability_xchannel/effects#assist.icons=138] assist-panel ability
icons, all the team's, [metric:ability_xchannel/effects#assist.cast_witness_10s=32]
have a cast witness within 10 s against a chance floor of
[metric:ability_xchannel/effects#assist.audio_chance_10s=13.0].

**Wiring sketch.**

- *Opens a child:* the tray drop (the player); the ult line (any player's
  X; its variant names the side); a minimap drawing or smoke owner row (the
  team); a killfeed ability kill (the killer's slot, if no child of it is
  live); an assist icon (the team's assister).
- *Joins only:* an audio_others detection. At replay precision 0.318 it
  would open two false children for each true one; it joins a child another
  channel opened, dating it within the class window, or stays a stored
  `candidate` the charge constraint can later promote. A second channel's
  agreement lifts it to 0.589, still under the bar, so agreement too only
  joins.
- *Effects first.* The killfeed's refused ability icons are the largest
  effect gap. Cross-reference before tuning: a refused weapon on a death
  whose killer's live child is a damaging ability is a candidate for that
  ability, offered to the weapon owner as a candidate set, never a verdict.
- *Identity:* an audio class names an agent of the lineup, which the
  arbiter's verdicts supply as the candidate set; the side comes from the
  lineup as a gate. An agent on both sides (three of five enemies on the
  replay) leaves two candidate parents; the child stores both and asks the
  arbiter, which may split them with the ult line's variant, the killfeed's
  colour or a minimap colour. The binding owner (`ability-owner`, unowned)
  publishes claims through the arbiter and declares `rests_on` the lineup.
- *For the player or the game files:* the hearing range of each ability's
  cast sound for an enemy (only Sova's Recon Bolt has a fact,
  [domain:abilities/sova-recon-bolt-landing-audible-range]); the game files
  may answer it before the player is asked.

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
- Give a world frame, or so a reach region, on a map without `shade_fit`
  or map constants.
- Bound a player who uses a movement ability; such a region carries
  `kit_unbounded`.
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

1. Answered from the game files (2026-10-04): the character's top ground
   speed is 675 units/s with state multipliers 0.6, 1.1 and 0.35
   [domain:game_data/character-movement-speeds]; the 1.1 multiplier is the
   Jumping state's. Still open: whether any agent's blueprint overrides
   the base tuning (no agent blueprint was read).
2. Whether a disconnected teammate stays drawn on the minimap, and whether
   the roster counts him.
3. Where a resurrected player stands: at the corpse, or elsewhere.
4. Each ability's duration and world shape (section 9's list), and each
   thrown ability's placement range.
5. Which abilities move their caster farther than running
   [domain:abilities/movement-abilities-are-dashes-and-teleports]; the
   mechanics sheet holds the candidates.
6. Each ability's lifecycle class (`deployed`, `instant`, `self_buff`,
   `equipped`, `movement`), its `effect_query`, and whether its minimap
   drawing is to scale.
7. Which abilities can be picked up, recalled or reclaimed for a charge
   (a Killjoy recall, a Cypher trapwire pickup, Gekko's reclaim), from the
   game files or the player.
8. The map's directed movement edges: drops, ropes, teleporters and the
   box tops players stand on, before path distance may bound a region.

## 13. Stages and acceptance

1. **Slot state from stored rows, as a prototype.** `prototypes/entity_state.py`
   builds ally slots and per-frame beliefs (fit, crowd, Euclidean reach;
   negative evidence off) from stored `round_entity`, `ally_icon`, `death`,
   lineup and rounds rows, in world metres, and scores them at Riot kill
   instants and on the replay. Acceptance:
   `prototypes/entity_state.py score SESSION ...` and
   `prototypes/entity_state.py replay 9acf02f98283`. Evidence: predictions
   P1-P8 judged on the held-out six, scored once. Then the world frame is
   baked into `geometry` and the Riot and replay scorers gain their slot
   mode.
   Outcome (2026-10-04, entity-state-0.2.0): held out, the region holds a
   living teammate on
   [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#calibration=0.9355] of kill
   instants, short of 0.98; reach regions hold
   [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#reach_calibration=0.9146], and
   [metric:entity_state/riot_pool@heldout6es~2026-10-04T22:29:59#has_slot_missing=8] instants
   found a living teammate's slot closed by a post-round death stamped
   with the next round. Those 8 kill instants sample a larger every-frame
   gap: on `c62c2b06bcfb` the judge counted 504 of 41617 alive
   teammate-frames with no open slot, 416 of them Sage's, closed by a
   post-round death stamped with the next round, and 22 all-slot closures
   at round starts; the stage 2 hunt, which skips 3 s after each buy
   start, counts
   [metric:entity_state/riot_pool@heldout6es_post_round#c62c2b06bcfb.hunt_no_slot=414]
   of [metric:entity_state/riot_pool@heldout6es_post_round#c62c2b06bcfb.hunt_alive_frames=41309],
   all Sage's. The misses trace to bindings, round starts and the fits
   themselves, not to the speed bound: the judge, viewing held-out reach
   misses in the crop cache, found the teammate's icon drawn at the truth
   and fitted but bound to no slot in every checkable case, and the other
   reach misses anchored on witnessed fits that sit on non-player drawings
   or off the map. The next step is a causal, witnessed binding that
   explains every fit, and a death owner that keeps post-round deaths in
   their round.
2. **The assignment, first as a causal prototype (2a), then in the
   arbiter (2b); deaths close slots; the ally lane.** Stage 2a:
   `prototypes/entity_binding.py`
   (`entity_state.py score ... --binding causal`) assigns every stored fit
   at each frame to a slot or to a non-player bucket with its reason
   (section 2, Identity), from stored rows only. Acceptance:
   `prototypes/entity_state.py score SESSION ... --binding causal` beside
   `--binding post_round`, and `replay 9acf02f98283` in both modes.
   Evidence: predictions B1-B4 (task entity-binding-20261004), the second
   look at the held-out six, scored once.
   Outcome (2026-10-04, entity-binding-0.1.1, the causal-leak correction
   of 0.1.0: no tray_kit lookahead, off-map self fits refused; a
   correction, not a third look): held out, the causal binding holds a living teammate on
   [metric:entity_state/riot_pool@heldout6es_causal#calibration=0.9689] of
   kill instants against the post-round binding's
   [metric:entity_state/riot_pool@heldout6es_post_round#calibration=0.9355];
   B1 (0.97) fails. A bound fit lies within 8 m of the truth on
   [metric:entity_state/riot_pool@heldout6es_causal#fit_bound_share=0.7615]
   (B2 holds against the ring fits'
   [metric:entity_state/riot_pool@heldout6es_causal#ring_located_share=0.7121]);
   no fit binds two slots (B3); reach regions have a median radius of
   [metric:entity_state/riot_pool@heldout6es_causal#reach_radius_m_median=9.81] m
   (B4). On the replay's every drawn frame the causal binding (0.1.0,
   before the correction) holds
   [metric:entity_state/replay@9acf02f98283_causal#calibration=0.9722]
   against [metric:entity_state/replay@9acf02f98283_post_round#calibration=0.944].
   The every-frame hunt over Riot's alive intervals finds
   [metric:entity_state/riot_pool@heldout6es_causal#hunt_no_slot=895] of
   [metric:entity_state/riot_pool@heldout6es_causal#hunt_alive_frames=222010]
   alive teammate-frames with no open slot, all from the lifecycle the two
   modes share, and
   [metric:entity_state/riot_pool@heldout6es_causal#hunt_no_position=2500]
   with no fit since the round opened (post-round
   [metric:entity_state/riot_pool@heldout6es_post_round#hunt_no_position=3939]).
   The causal binding costs at most
   [metric:entity_state/riot_pool@heldout6es_causal#cost_us_per_frame_max=174.88] us
   a frame, a Python loop over frames with one solver call each. The six
   held-out misses viewed in the crop cache: a fit on an enemy icon of the
   same agent; a real icon explained away as a ping; an icon the reader
   never fitted while the slot took a fit on an ability line; a swap the
   chain evidence had not yet moved; a spectating witness that named the
   wrong teammate; a fit on bare floor beside an ability drawing. Each of
   these fits needs another channel to refuse it (the enemy reader, the
   ability readers), not a sharper motion law.
   Stage 2b, the assignment in the arbiter and the ally lane. Acceptance:
   `reticle project SESSION` (the lane validated by
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
   9acf02f98283 and each later replay kept with a capture. Labelling finds
   by child class starts at stage 1; only the children's slot model waits
   for this step.

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

## 14. How the critique was resolved (2026-10-04)

A critique of the first draft found four blocking and eleven major
problems. Each is answered in the section named.

| # | Problem | Severity | Resolution | Where |
|---|---|---|---|---|
| B1 | Negative evidence piled up per cell and never moved with the player | blocking | The region is a forward-reachable set: last frame's region dilated by `v_max * dt`, less this frame's exclusions only; no permanent per-cell score. The replay's every-frame truth checks that no reach region ever excludes it | 2, Negative evidence |
| B2 | Frames 67 ms apart counted as independent looks; `p_det` had no truth source | blocking | Evidence counts per independent look (a change of background, occluder or icons, or a decorrelation interval measured on the replay), capped per interval; `p_det` per background class from the replay at its lower Wilson bound, stored with provenance | 2, Negative evidence |
| B3 | A cell no reader marked counted as empty, and unsearched cells gave absence | blocking | `p_det = 0` where the reader did not search; absence only where the pixels positively match the baked floor; reach slots widen the search, budgeted in section 6. Negative evidence stays off until all three exist | 2, 6 |
| B4 | The walk graph is not a superset of movement | blocking | The bound is the Euclidean disc over all standable cells; path distance only ranks until directed edges exist and the replay shows it never excludes truth; `kit_unbounded` for movement kits | 2, Reach; 12 |
| M1 | Children persisted to round end for every ability; late casts merged into stale children | major | Persistence only for the `deployed` lifecycle class, a per-ability fact; otherwise a refused end with an interval; joining only inside a duration or effect region | 9, Lifecycle |
| M2 | Missing range or speed facts produced false bounds | major | No region (`anchor_unread`, `position_unbounded`); the child drops out of every region test | 9, Anchor; Moving children |
| M3 | Drawn size and effect query by analogy | major | `drawing_to_scale` and `effect_query` facts per ability, refusing when absent | 9, Shape geometry |
| M4 | Recharge omitted pickups; over-bound evidence ambiguous | major | Over-bound evidence always opens an `over_bound` child; pickups and recalls go to the player or the game files | 9; 12 item 7 |
| M5 | Online path used a portrait verdict pooled over future frames | major | Causal pooling online, emergence remeasured; the lane publishes the online answer, smoothing adds revision rows; joint per-frame Viterbi | 2, Identity |
| M6 | A teammate exactly under another icon was not modelled | major | The `crowd` kind rides the host's fit, with the member's own reach kept in the region; its core is scored apart against `missed_stacked` | 2, table |
| M7 | A crowd ended only when the split detector fired | major | The capacity check, and the member's reach always in its region | 2, table; Updates 3 |
| M8 | The speed bound was `RUN_PX`, a stored-data bound in widget pixels | major | `v_max` from the game files, 7.425 m/s; `RUN_PX` stays the tracker's gate only | 2, Reach; 12 item 1 |
| M9 | `slot_state` in `reticle/` would import prototype tables; hiding inputs unlisted | major | Stage 1 is a prototype; the sightline builder moves into `geometry` before stage 2; inputs listed with their streams | 4, Layering |
| M10 | The `round_entity` view changed entity counts and ids | major | One entity per slot life, observed runs as sub-intervals, an old-to-new id mapping validated before stage 3 | 4, migration |
| M11 | The cost probe timed a simpler algorithm | major | The claim is now a hypothesis; the prototype times its own law, and the full probe reruns before negative evidence turns on | 6 |

The minor items: facing passes as a vector (3); units are a domain fact
(3); `level` is a bitmask and pixel columns are separate (3, 4); every
region is recomputable at any instant (4); an empty death-binding test
falls back to every unexcluded living slot (1); self fits bind to the self
slot and to the spectating witness (2); costs are log-likelihoods per
square metre (2); calibration is stratified by time since the last fix,
ability effects are scored on all 21 Riot matches, and `exposed_no_effect`
is a probability (8, 9).
