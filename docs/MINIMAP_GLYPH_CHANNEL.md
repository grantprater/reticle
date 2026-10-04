# The minimap ability-glyph channel

This plan wires the game's minimap ability textures into production as a
channel that names the ability a minimap disc draws, and through the kit
that holds it, the agent who cast it. It answers BACKLOG item 2(a). The
evaluation it builds on is `prototypes/minimap_glyph_eval.py`
(`minimap-glyph-eval-0.2.0`, wire: no); the measurements it rests on are
`prototypes/glyph_channel_cost.py` (`glyph-channel-cost-0.1.0`, wire: no),
logged as `glyph-wiring-design-20261004` W1-W13 in the store's
`notes/predictions.jsonl`. The rules it obeys live in `AGENTS.md`; this
document cites them and never restates them.

## 1. What the measurements decide

Four results shape the design. Each failed a prediction logged before it
ran.

**The proposer costs; the glyphs do not.** On 100 cached minimap frames
of c40d950031bb (`C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`, 331 px
crop), `ability_icons.propose_icons` took
[metric:glyph_channel_cost/cost@c40d950031bb#propose_ms=44.8] ms per frame
(median), and scoring every proposed disc against the ally candidate set's
glyphs, every rotation searched, took
[metric:glyph_channel_cost/cost@c40d950031bb#bank_a_ms=3.4] ms. On
a06f04a0059f (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`, 465 px) the
proposer took [metric:glyph_channel_cost/cost@a06f04a0059f#propose_ms=148.2]
ms and the glyphs [metric:glyph_channel_cost/cost@a06f04a0059f#bank_a_ms=5.6]
ms. The same bank on the GPU took
[metric:glyph_channel_cost/cost@c40d950031bb#bank_a_gpu_ms=0.86] and
[metric:glyph_channel_cost/cost@a06f04a0059f#bank_a_gpu_ms=0.75] ms.
`ability_icons.verify_icons`, which rescores the previous frame's discs
locally, took [metric:glyph_channel_cost/cost@c40d950031bb#verify_ms=1.06]
and [metric:glyph_channel_cost/cost@a06f04a0059f#verify_ms=1.08] ms. The
prototype's `follow` reruns the proposer on every cached frame for 3 s
after each label; production must never do that.

**A random-access crop read costs more than the glyphs.** Reading one
cached minimap crop alone took
[metric:glyph_channel_cost/births@c40d950031bb#read_ms=62.2] ms (median).
The reader must ride a pass that already reads the crop cache in order,
never fetch frames one at a time.

**A shared threshold sits under the null.** All
[metric:glyph_channel_cost/births@c40d950031bb#new_at_or_above=50] of the
[metric:glyph_channel_cost/births@c40d950031bb#new=50] new discs at 2 Hz
on c40d950031bb scored at least 0.4 against the ally set (median
[metric:glyph_channel_cost/births@c40d950031bb#best_q50=0.626]), and so
did a share [metric:glyph_channel_cost/null#not_at_or_above_04=0.9917] of
the player's labelled non-ability discs (median
[metric:glyph_channel_cost/null#not_p50=0.543], 90th percentile
[metric:glyph_channel_cost/null#not_p90=0.664]); labelled icons score a
median [metric:glyph_channel_cost/null#pos_p50=0.875]. The follow's
`ICON_SCORE` gate therefore admits every disc. A maximum over thousands of
templates is high on noise; the reader needs a null measured per bank.

**Search size biases the verdict.** Rotating only the abilities whose game
minimap component sets `bRotates`
([metric:glyph_channel_cost/gamedata_minimap#brotates_abilities=22]
abilities) named
[metric:glyph_channel_cost/rotation#heldout_gamedata_policy=155] of
[metric:glyph_channel_cost/rotation#heldout_n=192] stored held-out windows,
below rotating every ability
([metric:glyph_channel_cost/rotation#heldout_rotate_all=164]) and below
rotating none ([metric:glyph_channel_cost/rotation#heldout_upright=157]).
Sixteen of its 18 losses are an upright truth beaten by a rotated rival,
14 of them Deadlock's Sonic Sensor by Annihilation: a key searched over 24
times more templates wins on noise. The `rotation` run reproduced the
prototype's rotate-all and upright counts exactly, so the instrument is
not the cause. Rotation is per ability [domain:abilities/ability-rules-are-unique],
and a mixed policy needs a per-key null; `bRotates` alone is no policy.

Two results hold. Widening the candidate set from the labelled caster's
kit to the ally candidate set (named slots plus each refused slot's best
guess and rival) cost 8 of
[metric:glyph_channel_cost/rotation#ally_rotate_all_items=178] items
([metric:glyph_channel_cost/rotation#ally_rotate_all_caster_kit_right=152]
to [metric:glyph_channel_cost/rotation#ally_rotate_all_ally_set_right=144]),
and the caster agent was right on
[metric:glyph_channel_cost/rotation#ally_rotate_all_ally_set_agent_right=155]:
naming the caster is easier than naming the slot. And the prior carries
most discs: at the cache's hold spacing
([metric:glyph_channel_cost/cost@c40d950031bb#hold_gap_ms=66.7] ms), a share
[metric:glyph_channel_cost/cost@c40d950031bb#prior_share=0.954] of discs lie
within 2 px x scale of a disc of the frame before; at the ability pass's
2 Hz the stored streams give
[metric:glyph_channel_cost/prior2hz@c62c2b06bcfb#prior_share=0.52] (c62c2b06bcfb,
`C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`) to
[metric:glyph_channel_cost/prior2hz@c40d950031bb#prior_share=0.78]
(c40d950031bb).

These windows (`analysis/minimap-glyphs-answers-20261004/answers-on`) are
contaminated: the matcher and the follow were chosen on them. They size the
design; they gate nothing.

## 2. The parts

The channel has four parts, each with its own owner, stamp and stream.
The proposer exists; the other three are proposed.

| Part | Owner | Stream | Reads | Decides |
|---|---|---|---|---|
| Proposer (exists) | `ability_icons` [owns:ability-icon] | `ability_icon` | crop cache | where dark discs are |
| Glyph reader | `minimap_glyph` (new) | `ability_glyph` | crop cache, `ability_icon` rows, lineup | each disc's score per candidate texture |
| Disc tracks | `adjudication.ability` (new function) | `ability_disc_track` | `ability_icon`, `ability_glyph` | which observations are one object |
| Glyph verdict | `adjudication.ability_glyph` (new) | `ability_glyph_name`, `ability_glyph_identity` | the tracks, `team_vision`, `tray_kit`, the lineup, the null table | each track's ability and the claim on its caster |

The aggregator, `adjudication.identity` [owns:agent-identity], decides the
caster's name, as for every name.

### The glyph reader

**Where it runs.** It joins the ability pass (`reticle scan <sid> --only
ability`), which rereads the minimap crop cache at 2 Hz on live spans, as a
`passes.Reader`. Sharing the pass is an execution optimisation: the reader
keeps its own stamp `ability-glyph-0.1.0`, and a change to the proposer
restamps it only through its declared input. It reads the proposer's
candidates for the same frame, never reruns the proposer, and never
decodes video.

**The follow.** A disc the frame before does not carry (a birth) opens a
follow window of up to 3 s. Inside it the reader takes the cache's held
frames, every one, and tracks the disc by `verify_icons` from its last fix,
searching wider each frame it misses, as the prototype's reach does. Each
fix declares `rests_on` the fix before it. The window ends after eight
scored frames or at 3 s. Dense sampling here is gated on opportunity (a
birth), not outcome. Whether the follow at the cache's cadence beats the
same follow over the 2 Hz frames alone is stage 2's question; the 2 Hz arm
costs no extra reads.

**The candidate set.** Per frame, the reader scores the textures the
match's context allows: the ally side's kits, each texture whose game-data
row (`ability-states-gamedata-0.2.0`) does not mark the frame's view
`false`, and the enemy side's kits, only textures an enemy sees. The
sides come from the lineup's verdicts, each refused slot admitting its best
guess and rival, as the arbiter admits rivals. Each frame row declares
`rests_on` the lineup file and version. The full set, every agent's kit,
runs on two paths, stored apart:

- the audit: every tenth birth, a cadence fixed here, scored against every
  kit through its window; these rows carry `audit: true` and measure what
  the lineup prior hides;
- the surprise: a disc whose best candidate stays under the bank's null
  through its window is rescored against every kit, `surprise: true`,
  never an audit sample.

The full set costs [metric:glyph_channel_cost/cost@c40d950031bb#bank_c_ms_per_disc=2.75]
ms per disc against [metric:glyph_channel_cost/cost@c40d950031bb#bank_a_ms_per_disc=1.29]
for the ally set on c40d950031bb.

**The textures.** Each ability's DisplayIcon and its exported minimap
textures, assigned by the player's texture answers
([domain:abilities/minimap-textures-deadlock] and its siblings, one fact
per agent) or by DisplayIcon correlation where no answer exists, with the
export build and inventory versions in the stamp. Game files, never mined
captures. Of the [metric:glyph_channel_cost/gamedata_minimap#minimap_abilities=71]
abilities with a minimap component in the game data,
[metric:glyph_channel_cost/gamedata_minimap#abilities_with_png=49] have an
exported texture.

**Pixels.** Luma inside an r = 8.5 px x scale disc, masked Pearson, never
binarised; templates shrink with `INTER_AREA` and turn with linear
interpolation [domain:capture/capture-resolution]. All discs of a frame
score in one matrix product, on the GPU when one is present; no per-disc
Python loop.

**Stored row (`ability_glyph`).** A coverage row: the stamp; inputs
(`ability_icon_version`, `roi_cache_version`, the lineup's file and
version, the glyph bank's digest: build, inventory, export, answers file
hash, states table, rotation policy); the matcher's parameters; the
candidate set per side with why each agent is in it; the audit cadence;
counts by reason. One row per scored frame and disc:
`{t_ms, frame_idx, disc: "ability_icon:<sid>:<t_ms>:<i>" or a follow fix
{cx, cy, r, rests_on}, set: "context"|"audit"|"surprise", scores:
{"<agent>:<slot>": [score, texture, canvas, rot, dx, dy]}, best, second,
margin}`. An unread frame keeps its reason: `not_live`,
`widget_not_drawn`, `no_ability_icon_row`, `off_crop`,
`geometry_size_mismatch`, `no_lineup`. The reader names nothing.

### Disc tracks

`ability-icon`'s entry routes tracks to `adjudication.ability`
(`not_for`: "tracks and lifecycles"), so the track joins there as
`disc_tracks`, pure over stored rows: a 2 Hz birth, its follow fixes, and
the later 2 Hz candidates its verify keeps. A track ends when the verify
loses it (`score` None, stored) or the round ends. Track ids are
`<sid>:adisc:<birth_t_ms>:<i>`. A track switching objects, which the
prototype saw twice, is a stored surprise when its fixes jump past the
reach.

### The glyph verdict

`adjudication.ability_glyph` reads the tracks and decides per track,
pure over stored rows:

1. **Gates, from other owners' stored answers.** A frame counts when the
   widget is drawn [owns:widget-drawn], no stored `team_vision` portrait
   covers the disc (the prototype's `portrait_cover`) and the disc is not
   the baked map's [domain:capture/session-pixels-are-not-the-map]. The
   frame's view is `self` while the tray shows the player's kit and
   `spectator` while it shows a teammate's [owns:tray-kit]
   [domain:hud/tray-after-player-death]; textures whose view is false for
   that view leave the set. A null view stays in with `view_unknown`, and
   a verdict resting on one is a stored surprise until the player answers
   [domain:minimap/spectator-view-matches-self].
2. **Pooling.** The mean score per key over the clean frames.
3. **The cut, once.** A key names the track when its pooled score clears
   the null for its bank size and its margin over the runner-up clears the
   tie margin; both come from the null table (section 5), never a shared
   constant. Otherwise the track refuses with one reason: `below_null`,
   `pairwise_tie`, `no_clean_frame`, `occluded`, `outside_candidate_set`
   (the audit or surprise path named a kit outside the set),
   `view_excluded`.
4. **State.** The winning texture's game-data state (inactive, active,
   ally, enemy and the rest) is an observation of that ability's drawing.
   A lifecycle phase comes only from the ability's lifecycle fact
   [domain:minimap/device-dim-on-deactivation]; the entity contract
   enforces it.

Output `ability_glyph_name`: per track, the ability (agent, game slot,
display name), the texture and its state, the pooled scores of every
candidate (the alternatives), margin, clean and skipped frames with
reasons, and `rests_on` the lineup, `team_vision` and `tray_kit` stamps.

**The claim.** Per named track, one `identity.identity_claim` on channel
`minimap_glyph`: the entity is the track, the agent is the kit's owner.
When the lineup chose the candidates, the claim `depends_on` the ally slot
entities, as `smoke_owner`'s claims do, so it never counts as an
independent witness of the roster. An audit-path claim, scored against
every kit, rests on no lineup and may witness which agents a side fields;
it enters the aggregator only after stage 4's null holds on the audit
rows. Until channel arbiters exist (`docs/ARBITER_ARCHITECTURE.md`,
section 1), the owner publishes its claims as `smoke_owner` does
(`ability_glyph_identity`); afterwards, through the minimap channel's
arbiter.

### The event and its consumers

A new lane `ability_icon` in `docs/ENTITY_EVENTS.md`: an `ability_object`
entity per track, its `identity` the aggregator's verdict cited by `ref`,
events `drawn` (first fix) and `gone` (the verify's loss) with observed
times and baked positions, and one event per texture state change. A
refused track goes to the ledger with its reason and `returns_to:
["ability-glyph-name"]`. Consumers read only this lane
[owns:entity-event]:

- `reticle view`, which draws named ability icons on the annotated match;
- `ability-owner`, unowned today and blocked on "an ability entity to
  attribute": the track is that entity, and the aggregator's verdict over
  the glyph claim, the birth at a bound ally fragment
  [domain:abilities/minimap-thrown-ability-icon] and the player's tray drop
  answers it;
- `adjudication.ability_state`'s later steps (allies' kits) and
  `adjudication.phases`, which read texture states as transitions;
- `adjudication.reliability` [owns:identity-channel-reliability], which
  scores the channel per agent.

## 3. Ownership entries

Proposed text; each lands in `ownership.toml` with the code that owns it.

- **`ability-glyph`**, owner `minimap_glyph`, role detect, "Which game
  minimap texture of the candidate kits does each proposed ability disc
  draw, and how well does each candidate score?" Produces the reader and
  its scoring. `not_for`: finding discs (`ability-icon`); joining discs
  across frames (`ability-disc-track`); naming the ability or its caster
  (`ability-glyph-name`, `agent-identity`); smokes (`minimap-dark`) and
  shapes (`ability-shape`); choosing the candidate set beyond the
  lineup's verdicts, which it takes as a candidate set only.
- **`ability-disc-track`**, owner `adjudication.ability`, role group,
  "Which stored ability-disc observations are one object, from birth to
  loss?" `not_for`: reading pixels (the follow's fixes are the reader's);
  naming; lifecycle phases (`ability-phase`).
- **`ability-glyph-name`**, owner `adjudication.ability_glyph`, roles
  adjudicate and attribute, `names_agents = true`, `defers_to =
  ["agent-identity", "player-agent", "tray-kit", "team-vision",
  "ability-disc-track"]`, "Which ability does a tracked minimap disc
  draw, in which texture state, and whose kit holds it?" `not_for`:
  deciding the caster's name, which the aggregator decides from the claim;
  binding the ability to a player track (`ability-owner`); a phase without
  a lifecycle fact; a threshold the null table does not give.
- **`ability-owner`** stays the aggregator's question; this plan supplies
  its entity and its first witness, and its `blocked_by` changes to the
  stage 5 lane.

## 4. Plan inputs

In `reticle/plan.py`, beside the ability pass's streams:

- `ability_glyph`: command `reticle scan {sid} --only ability`, how
  `cache`; fields `ability_glyph_version`, the glyph bank digest,
  `ability_icon_version`; upstream `ability_icon`; inputs the geometry and
  `_lineup_inputs()`.
- `ability_disc_track`: command `reticle ability-glyphs {sid}`, how
  `storage`; upstream `ability_icon`, `ability_glyph`, `rounds`.
- `ability_glyph_name`: same command, storage; fields the null table's
  version and the states table's version; upstream `ability_disc_track`,
  `team_vision`, `tray_kit`; inputs `_lineup_inputs()`.
- `ability_glyph_identity`: an identity stream, `producer_version` the
  aggregator's, parent `ability_glyph_name`.

The lineup appears twice on purpose: a lineup change restamps the reader,
whose candidate set it chose, and the verdict, whose claims depend on it.

## 5. Evaluation gates

Each gate states its command, its labels and its threshold before it runs.

1. **Instrument.** `prototypes\glyph_channel_cost.py rotation` reproduces
   the prototype's [metric:glyph_channel_cost/rotation#heldout_rotate_all=164]
   of [metric:glyph_channel_cost/rotation#heldout_n=192] and
   [metric:glyph_channel_cost/rotation#dev_rotate_all=51] of
   [metric:glyph_channel_cost/rotation#dev_n=59]. Done.
2. **The clean held-out pass.** `minimap-heldout-score-20261004` (H1-H8,
   logged before any matcher ran on `labels/minimap_glyph_heldout`) scores
   the prototype once on labels nobody tuned on. Its headline decides
   whether stage 2 starts: below 35% it stops this plan and the next step
   is the miss causes. After that run the labels are spent; no arm here
   is chosen on them.
3. **The null table.** Per bank (context set and full set, at each widget
   scale), the pooled-score and margin distributions of discs the player
   labelled as no ability, and of proposer discs no label names, from dev
   sessions only. The cut sits where the false naming rate on those discs
   is at most 5%. Stored as its own version; the verdict records it.
4. **Accuracy at the cut, on a fresh held-out set.** A new labelling pass
   (`prototypes/label_minimap_glyph_heldout.py`, a new queue version) on
   sessions no stage used. Named tracks must be right on the caster agent
   on at least 90% (Wilson lower bound at least 80%), naming at least
   half the sure kit-named marks. Refusals are kept with reasons.
5. **Riot.** Riot records each player's casts per slot per match (`stats.
   abilityCasts`; per-round effects are null). For each ally player and
   slot whose ability draws a disc, named births may not exceed Riot's
   count times that ability's births per cast; an ability with no births
   fact gets no bound and asks the player through the mechanics sheet.
   Excess lists the tracks with their reasons. Run with
   `prototypes\riot_ground_truth.py --all --offline --record` once a
   block reads the lane.
6. **Cross-reference.** The glyph claim against the birth's origin at an
   ally fragment and against the player's tray drop; disagreements are
   stored, never averaged, and the agreement rate joins the reliability
   table. Agreement is consistency, not accuracy.
7. **Cost.** `reticle usage <sid>` on the fast handful: the reader adds at
   most 10% to the ability pass's wall time, and the verdict runs under
   one minute per match from storage.

## 6. Staged order

1. **Done here:** cost, prior share, rotation and null measurements
   (W1-W13).
2. **Wait for the clean held-out score** (gate 2). Meanwhile ask the
   player the open rotation questions in `prototypes/ask_minimap_glyphs.py`
   and record the answers as one fact per ability.
3. **Null and rotation on dev**, gate 3: per-key nulls, then a rotation
   policy from the player's answers, compared on dev under the per-key
   null. Arms: 2 Hz follow against cache-cadence follow.
4. **The reader** in the ability pass, `ability-glyph-0.1.0`; `reticle
   trial --reader ability_glyph` on a06f04a0059f, 5822b6646448
   (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`) and 4f207c0c4e39
   (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`); gate 7.
5. **Tracks, verdict and claims** from storage; gates 4 and 6. The
   ability pass first runs on the 21 matches in one batched corpus rerun;
   today `ability_icon` exists on five sessions only.
6. **The lane and `reticle view`**; gate 5.
7. **The scene model.** The glyph textures become an ability sprite in
   `docs/SCENE_MODEL.md`'s renderer, composited over the baked static at
   the fitted pose; the per-key null becomes the sprite's residual
   threshold, and the reader's scores the render-and-compare residual.

## 7. Real time

Live, nothing decodes: the reader is a function of one minimap crop and
the previous frame's fixes. Its glyph scoring fits a live budget on the GPU
([metric:glyph_channel_cost/cost@a06f04a0059f#bank_a_gpu_ms=0.75] ms per
frame median). The proposer does not
([metric:glyph_channel_cost/cost@a06f04a0059f#propose_ms=148.2] ms at
465 px). A live proposer would continue the prior: verify the tracked
discs every frame, propose births only near the ally icons where an
ability's fact places its birth, and run the full search on surprise and
at a fixed audit cadence. That change belongs to `ability-icon` and needs
a birth-place fact per ability; it is out of this plan's scope.

## 8. Predictions for the next stages

Logged in the store when each stage starts, with these as the first
draft:

- P1 (stage 3): per-key nulls lift the game-data rotation policy to within
  2 of rotate-all on dev, removing most Deadlock Q to X losses.
- P2 (stage 3): the 2 Hz follow names within 3 points of the cache-cadence
  follow on dev.
- P3 (stage 4): the reader adds at most 10% to the ability pass's wall time.
- P4 (stage 5): at the cut, at most 20% of tracks refuse as `below_null`
  on matches; `pairwise_tie` concentrates on Skye (Seekers, Trailblazer,
  Guiding Light) and Sova's Owl Drone, as the prototype's misses did.
- P5 (stage 5): audit-path verdicts agree with context-path verdicts on at
  least 95% of audit births.

## 9. What this plan does not settle

- Whether a spectator sees what the spectated player sees
  [domain:minimap/spectator-view-matches-self]: the player is unsure, and
  the views gate rests on it.
- Births per cast per ability, for the Riot bound.
- Which abilities' minimap icons rotate: ten questions are open.
- The cost of reading the cache in order inside the pass; only the
  random-access read is measured.
- Shape-class drawings (recon bolt, smokes, walls): `ability-shape` and
  `minimap-dark` own them.

## Reproduce

From the repository root, single-threaded, Below Normal, no decode:

```powershell
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py           # cost.json: 100 frames each on c40d950031bb, a06f04a0059f
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py rotation  # rotation.json: stored windows, no cache
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py births    # births.json: c40d950031bb, stored 2 Hz rows
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py table     # game-data minimap counts
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py record    # the metric series cited above
```

Outputs land in the store's `analysis/glyph-wiring-20261004/`.
