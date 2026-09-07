# Reticle — working notes

Where the work stands **today**: the handoff into the next session, and the
defects that are live rather than standing. `CLAUDE.md` carries what stays
true across sessions — the conventions, the domain rules, the mistakes worth
not repeating. This file carries what is true this week, and it is read on
demand rather than loaded into every session.

Read it when picking up unfinished work. Update it in place; let it go stale
rather than let it grow.

Split out of `CLAUDE.md` on 2026-08-27.

## PICKING UP -- 2026-09-07, the plan is reconciled with the backlog

`docs/IMPLEMENTATION_PLAN.md` is the broad review and the execution record.
`BACKLOG.md` is the deferred queue. They were written independently and now
agree; what follows is what the reconciliation actually changed, then what is
live.

**Verified before reconciling, not taken on the plan's word:** 14 tests pass,
`doctor` reports the 5 findings and 1 error the plan claims, and
`analysis/reconciliation.json` holds the window counts it quotes (587c15b07779:
115 agree / 9 unreadable / 6 disagree / 1 increase over 131 windows;
c40d950031bb: 58 / 0 / 2 / 0 plus 1 timing-ambiguous and one adjacent
cancellation).

**Four backlog entries moved.** The 587c15b07779 scan CLOSED -- its trigger
fired, `scan --only roster` did it without the minimap rebuild it used to
depend on, and that decoupling is the reconciliation's one structural win.
"Two unwired modules" is now one: `roster.py` wired itself as predicted, and
`doctor` agrees. The minimap re-validation entry gained the two constraints the
plan carried and it did not -- the rebuild destroys shade unless `map_shade
build --all` rides it, and `2ba870ccbd50`'s profile must be settled before it
is rebuilt on a possibly-wrong crop. The prototypes-deletion entry has a
trigger that CANNOT FIRE: `doctor` now finds five orphans and not one of them
is in the enemy-teacher cluster the entry names.

**The plan's four remaining milestones are now backlog entries with triggers**
("The coaching milestones this file had no entry for"). Prose in a plan is not
a queue. Stated there too: the plan is silent on the audio channel, the
viewcone, the wiki map and analysis-by-synthesis, and silence is not
deprecation.

### The live queue, in order

**1. The roster reader -- WORKED, and it ends on a decision for the player.**
The roster is the AUDITOR of the killfeed (`roster.py` is explicit that the
direction must not reverse), so a roster defect corrupts the only label-free
validity signal the project has.

*Shipped:* `l1/roster` now stores the DETAIL VECTORS the count is adjudicated
from (`roster-0.2.0`), with the split rule on its own stamp
(`ROSTER_SPLIT_VERSION`). A split-rule experiment is now a re-derivation over
stored data instead of a 127 s re-read; `prototypes/roster_split_eval.py` is
that experiment and it reproduces every stored count exactly. Both sessions
re-scanned, counts unchanged.

*Measured:* the ratio split rule is right on the frame that motivated it and
moves **six cells in 11,306**. The only audit movement is the held-out window
itself, so the corpus does not establish it. Not shipped.

*Found, by rendering:* a WIPED team reads `None` rather than `0` -- the
documented `(0,0)` defect from the other side, and it costs the audit its most
informative windows, because a wipe is a round outcome. Also a non-uniform fade
reading as a confident partial count, which is confined to outside rounds
(0.0-0.1% of in-round rows). Everything is in `docs/ROSTER_FINDINGS.md` with the
frames; the wipe case is pinned by a test so a fix has to change it on purpose.

*Decided by the player and SHIPPED, `roster-split-0.2.0`:* the split is a ratio,
and an empty bar is resolved by the SCORELINE rather than by how dark it is --
score read means the HUD is drawn, so a dim bar is a WIPE and answers 0; no
score answers nothing. `roster.resolve()` does the as-of join at adjudication
time, because `scan --only roster` runs no HUD reader; `audit` and `coach` both
call it. Both sessions re-scanned.

Measured: `587c15b07779` audit agree 115 -> **116**, unreadable 9 -> **7**,
ambiguous `(0,0)` rows 8 -> **0** (187 -> 5 on `c40d950031bb`). `coach` is
unchanged at 26 rounds and still abstains -- terminal states were never
eligible, so this buys AUDIT coverage, not model coverage.

**The one remaining count increase MOVED, and that is the handoff.** It was the
confirmed 1483.0s split defect; it is now 167.5-177.5s, where the enemy bar
correctly reads 0 from 158s and 5 at 176s. That is not a roster error -- it is
`round_bounds` putting the boundary at the score increment instead of at the
round's real end. The audit has stopped flagging the roster and started flagging
round timing, which is item 3 below.

**2. DONE 2026-09-07 -- every unresolved window is diagnosed, and NOT ONE is a
roster error.** All seven on 587c15b07779 and all three on c40d950031bb were
inspected by rendering the killfeed. Three are the documented **Run It Back**
divergence (the local player is Phoenix on that session), three are killfeed
tracker defects, and two are an onset landing across a window boundary. Full
table in `docs/ROSTER_FINDINGS.md`.

**The consequence is a re-ranking: the work is in the KILLFEED, not the
roster.** The revive-mark reader -- CLAUDE.md's candidate next step #2 -- is now
the highest-value addition on evidence rather than argument: it resolves 3 of
the 7 windows outright, on top of the K/D divergences it was already wanted for.

**STARTED 2026-09-07, geometry located, detector NOT built.** The badge is a
white CIRCULAR ARC and it **straddles the victim-plate boundary** -- extracting
the weapon-icon-to-victim-name gap gets only a sliver of it, so a crop keyed to
`EntryView.wx1 .. victim_run[0]` is the wrong window and that was the assumption
this started from. The headshot crosshair is the common occupant of that gap and
appears on marked entries too, so the question is *is there an arc*, not *which
mark is this*. Measured on three confirmed positives and four negatives; full
crops and the next step in `docs/ROSTER_FINDINGS.md`.

**It stops at three positives deliberately.** `ff636d173b07` is the session to
add before fitting anything: CLAUDE.md records four hand-verified Phoenix ult
marks there and its K/D is +4 deaths against `KNOWN_KD` for exactly that reason,
which makes seven positives with an independent count to score against. Then fit
a circle rather than threshold one -- `minimap.fit_ring` is the precedent.

`reticle audit` is `audit-0.3.0` and now reports killfeed health from stored L1:
counted tracks that never formed a divider (61 corpus-wide) and tracks lasting
far past the ~4.5s entry lifetime (83, only 6 of them explained by a frozen
frame). **CLAUDE.md's "there are now none anywhere" about long tracks is false
-- there are 154 over 12 samples.**

**3. Round and POV gates.** 111 of 543 coaching events sit near an uncertain
round boundary; that is 20% and the largest quality number the first milestone
produced. Do not require two score reads: it drops two final-round outcomes.

The frozen-frame instrument was built (`reconciliation.frozen_runs`, no
threshold: every HUD column equal sample to sample) and **MEASURED NOT TO WORK
for this**: only 8% of derived round starts fall inside a run of >= 5s, and the
median run sits 25s from the nearest one. It stays because it separates a merged
killfeed track from an entry held on a paused screen, and because 2.8% of
derived in-round time is a frame that never changed -- a coaching-state
eligibility question. Do not retry it as a boundary detector.

Also measured and negative: **the killfeed is not systematically late.** Over
182 in-round roster drops matched to their nearest onset the lag is median
+0.00s, p90 +0.50s, and 98% fall inside the audit's existing +/-1.0s. The 2.5s
case on c40d950031bb is a 2% tail. Do not widen `ENTRY_ALIGNMENT_MS`.

**MEASURED 2026-09-07, and the defect is now quantified corpus-wide.** Two
independent channels agree that `round_bounds` starts a round ~6s before the
PREVIOUS round's clock expires, and that the real round begins ~7s after that:

    clock at the derived round start   median 6.0s over 281 rounds, all 18
                                       sessions; median is 6.0s on 17 of them
                                       and 5.0s on the 18th. 95% under 15s,
                                       i.e. the previous round's last seconds
    roster, 26 rounds on the two sessions that have one:
      wipe onset - derived round END        median +0.0s
      both teams back to 5 - derived END    median +7.0s (p10 +4.5, p90 +7.5)
      clock when both teams are back to 5   median 28.0s -- the buy phase

The round END is well placed; the START is wrong, and contiguity makes those the
same instant. The score updates when the round is DECIDED, not when the clock
runs out. This is the single explanation for the `opens-at-5` collapse, the
167.5-177.5s count increase, and a large share of the 111 boundary-flagged
coaching events.

**DONE 2026-09-07 -- the player took it, and `round-0.2.0` ships it.** The start
is the first upward clock JUMP after the score increment; the END did not move,
so rounds are no longer contiguous and the gap between them is the post-round
period. Stored rounds carry `start_source`, so one built the old way cannot read
as current. All rounds rebuilt, `coach` and `audit` re-run.

It lands where the roster predicted, on six times the rounds: **clock median
28.0s at the new start (p10 25.0, p90 29.0) over 275 rounds on 18 sessions**,
92% inside a buy phase, gap median 7.5s. 22% of rounds fall back to the old
start because their buy-phase clock was unreadable, and they are labelled.

`STATUS.md` is byte-identical -- every K/D against `KNOWN_KD`, 369 rounds,
183/369 plants -- which is the check that mattered: a start-side change must not
touch numbers derived from session-level tracks. Coaching eligibility is also
unchanged (329/107 states, 26 rounds, still abstaining); the rejection
bookkeeping moved honestly, `clock_or_phase_unknown` falling by exactly the
amount `round_boundary_or_unresolved` rose. **`round_boundary_uncertain` events
fell 111 -> 79**, with `round_unresolved` rising 7 -> 39: the same 118 events,
39 of them now definite rather than uncertain.

The audit moved as predicted -- disagreements 6 -> 4 and 2 -> **0**, both
boundary-straddling windows resolved, the three Run It Back windows and two
tracker defects correctly untouched. **The 167.5-177.5s count increase
resolved.** The one that remains is a different window, 690.5-700.5s, previously
hidden inside an unreadable one: rendered, it is a genuine **Sage/Clove revive**
(one portrait, then two, then one) that the reader tracks correctly at every
step. A real event exposed, not a regression. Full numbers in
`docs/ROSTER_FINDINGS.md`.

Everything after that is in `BACKLOG.md`. The minimap channel is a separate
thread and its handoff is below, unchanged: `doctor` still reports 35/36 stale
geometry caches, and no minimap number should be quoted until they are rebuilt.

### What `reticle coach` and `reticle audit` are

`coach` builds a reproducible event/review bundle from stored L1 only: 543
player kill/death observations across 18 HUD sessions, source and code hashes on
every run. Default output `~/reticle-store/analysis/coaching/`; start with
`report.json` and `review.md`. Probability evaluation ABSTAINS -- 26 eligible
rounds from two sessions -- and that is a reportable result, not a gap to paper
over. `audit` localizes cross-channel disagreements without labels; v0.2 refuses
windows where HUD coverage is missing, so a gap can no longer read as agreement.
`scan --only roster` fills roster coverage in ~127s per session without
touching minimap or geometry.

Nobody has read `review.md` yet. It is one window per round chosen
chronologically -- source pointers for inspection, not a sample of anything.

## Minimap handoff -- 2026-09-07, the BASE layer is built

### DONE 2026-09-07: the art's terrain LEVELS are in the geometry npz.

`prototypes/map_shade.py`, additive, **35 of 36 npz**. Six classes rather than a
level table -- FLOOR (a per-map ladder), RAMP, SHADOW, LINE, SITE, VOID -- plus
`shade_step`, `shade_purity` and the fit used. Full argument and every figure in
that module's docstring and in `prototypes/CLAUDE.md` under "THE BASE LAYER IS
BUILT". The three that matter here:

* **51.9% of every always-lit pixel is off the base shade**, and the artefact
  rate climbs monotonically with the rung (8.1% at base, 35.8% at +5) while the
  real cones fall away with it (7.7% sometimes-lit at base, 0.1% at +5);
* **SITE against the derived `PLANT` labels is 87.4-87.9% IoU** on four
  independent statics across three maps -- an alignment check the alpha fit
  cannot give;
* **two stored fits were stale and worse than the code's own answer**
  (`a06f04a0059f` 79.9% -> 94.6% IoU). Recomputed. `cone_terrain`'s numbers were
  measured through the worse one and **survived unchanged**.

**Licensing: SETTLED, and not as a risk being managed. Corrected 2026-09-07.**
This used to read *"the recorder is content to take level geometry from the wiki
art"*, which turned a POSITION into a tolerated risk. The position is that where
a level's floors, walls, elevations and sites are is DATA about the level rather
than anything expressive, so there is nothing in it for a copyright interest to
attach to. The art is an instrument for measuring that data.

What the code does follows from it and is worth stating plainly, because it is
checkable: the PNGs are fetched into the store, which is outside the repo, and
no PNG has ever been committed here. What this repo produces and ships is
`reference/shade/<map>.npz` -- class indices per pixel -- which is the
measurement, not the render.

### Next within the minimap channel (after cache revalidation)

**The ANNOTS layer: subtract the audio ring and the icons, then fit bearings to
the residual.** BASE now exists, so this is the next layer down the list in
`prototypes/CLAUDE.md`'s "THE WIDGET IS LAYERS", and it is unblocked rather than
merely next.

    per frame:  fit an affine art-grey -> observed on pixels explained by
                nothing else, using `shade` as the art level
                subtract the KNOWN-geometry annotations -- the audio ring
                (an annulus at 94-95 px round the self icon, drawn only while
                running), the icons, the X marks
                what remains is LIGHT: the union of the team's cones

**Two things the shade work says about how to do it.** The affine should be
fitted on `shade_kind == FLOOR & shade_step == 0` only -- the base shade is 72%
of the usable area and carries 90% of the real cone pixels, so it is both the
biggest and the cleanest population. And `shade_kind == LINE` should be excluded
from every lit test outright: it is 21.4% always-lit and it is not terrain.

**One tag would finish the coverage:** `79a706a7ce4c` has its own static and no
`map:` tag, so it is the only geometry npz with no shade. It is the third Cypher
demo clip; if it is Ascent, tagging it costs nothing and
`map_shade.py build 79a706a7ce4c --map ascent` does the rest.

**And re-run `map_shade.py build --all` after any geometry rebuild** --
`minimap_geometry.py` writes the npz from scratch and will drop these arrays.
`doctor` says 35 of 36 are stale, so that rebuild is coming.


**The observable area is built, drawn and measured, and the session ended on a
DESIGN CORRECTION that supersedes how it is computed. Read this section's last
part before extending anything.**

**What shipped and is solid:**

* `reticle/cone.py` -- the raycast, promoted out of `minimap_cone`, vectorised
  (2.74 ms/cone against 37.40, exact agreement with the loop on a real map).
  `passable` and `visible` split, fixing a real under-claim bug;
* `fit_ring` promoted to `reticle/minimap.py`, byte-identical
  (`minimap_icon_eval --finder ring`: 86.3% / 48.1% either side), and its
  circle search vectorised 8.7x, again exactly equivalent;
* `minimap.ally_icons` -- a blob becomes an icon by ring coverage, a non-key
  interior AND a facing lobe. Scored against the ROSTER, which is a label-free
  ground truth (`n_icons == alive_ally - 1`): raw ally blobs carry a **+0.99**
  residual, one phantom teammate per frame; promoted icons carry **-0.15**,
  **20 of 24 rounds agreeing, 95% CI [64%, 93%]**;
* `track.Tracker` -- Hungarian identity, motion law as an inadmissible cost,
  plus `resolved_facing`: a windowed circular mean with a RESULTANT gate;
* `overlay.py` draws the minimap channel -- icons, bearings, per-icon cones,
  the aggregate. AMBER is a refused bearing.

**THE THREE FINDINGS, in the order they matter:**

1. **THE WIDGET MUST BE SOLVED AS LAYERS** (`prototypes/cone_terrain.py`, and
   the section of that name in `prototypes/CLAUDE.md`). Terrain shade reads as
   illumination at 3x, the audio ring is baked into the static reference, and
   the derived floor mask agrees with the wiki art's exact alpha at only 75.6%
   IoU. Per-pixel tests for one layer ask a question the pixel cannot answer
   alone. **This is where the next session starts;**
2. **the reconstruction OVER-claims about 3x** against the area the game draws
   (`cone_lit.py`). Recall is high, precision is low. That dwarfs the 13% of
   area the ambiguity gate gives back, which was the wrong thing to optimise;
3. **the raw per-frame bearing FLIPS 180 degrees on 16% of frames**
   (`cone_flip.py`), from a thick annulus whose "reach past r" is uniform, so
   the argmax follows centre jitter. Gated, not solved -- and ally bearings
   turn out BETTER than self (7.2% against 16.1%).

**NEXT, in order:**

1. **the BASE + ANNOTATIONS layer.** Warp the art (the transform is already
   fitted and stored in `reference/fits/`), fit an affine art-grey -> observed
   per frame, and SUBTRACT the known-geometry annotations -- audio ring, icons,
   X marks -- rather than detecting them. The residual is the light. This kills
   the terrain artefact and gives a clean region to fit bearings to;
2. **ally IDENTITY, which is coupled to it** -- icons are one of the subtracted
   layers. 862 tracks over 4266 frames, 27% lasting a single observation, 12
   live tracks for 6 icons in the overlay. This is now the binding constraint,
   not the bearing;
3. re-measure `ally_icons` against the roster afterwards -- the -0.15 residual
   is a COUNT and says nothing about bearings;
4. then the interior-appearance invariant, which is what the area is for.

**OPEN QUESTION FOR THE RECORDER, cheap for them and expensive to derive:** the
drawn cone FADES with distance (lit share 51% at 0-20 px falling smoothly to
13% at 100 px, no cliff, over 407 cones). Does the cone have a visible edge at
some range, or does it just dim out? If it ends, an unbounded raycast is wrong;
if it fades, the lit mask is a conservative floor rather than an outline.
Picking wrong makes the area wrong in opposite directions.

**`CONE_HALF_ANGLE_DEG` is now 51.5 (103 full)**, from a reported fixed FOV of
103 that sits inside this repo's own measured 50-65 band. Provenance is a web
search and the docstring says so; an attempt to confirm it from camera pan
failed on a weapon-model lock in `minimap_self_check._world_grey`.

**Standing asks of the recorder:** unchanged -- more teleport-agent clips for
`TELEPORT_PX`, and the equip-hold-cast protocol.

## The north star for this channel (recorded 2026-09-06)

> a system that can annotate the vods, highlight the abilities, players,
> viewcones, pings, and any other icons as they evolve throughout a match

A visually checkable proof of work, and it outranks any per-detector metric --
recorded in full under "The NORTH STAR for the entity channel" in `CLAUDE.md`.
`reticle/overlay.py` is the vehicle: it exists, it already refuses to hold its
own copy of the logic, and it draws **no minimap entity at all** yet. Extending
it to the minimap channel -- tracks, not per-frame detections, every channel in
one frame -- is the concrete form of this.

## THE ORIGIN-EVENT MODEL is now §10 of the entity doc (2026-09-06)

**An entity's existence interval begins at an ORIGIN EVENT from a closed set:**
round start, ability equip, ability cast, ping, player death, or -- for an
enemy-owned entity -- the moment it left the COLLECTIVE TEAM VIEWCONE.

It is the largest omission the design doc had: §4 said existence is a set of
intervals and never said where one STARTS. The shift is from birth OBSERVED
(first detection, a property of the detector) to birth EXPLAINED (a property of
the world), and it makes a bad frame a missing OBSERVATION rather than a missing
ENTITY -- which is the structural fix for momentary blips, needing no detector
improvement at all.

**Five of the six origins already have readers. The sixth does not, and it is
now the highest-leverage missing piece in the minimap directory:** only the
local player's viewcone is fitted, ally cones are unread, and the enemy half of
the model cannot be built without the collective cone. An enemy entity's origin
is an OBSERVATION event -- a question mark is born when knowledge is lost.

Full argument in `docs/minimap-entity-model.html` §10 and `prototypes/CLAUDE.md`.

## RUNNING IS NEVER SILENT: 0 of 176 windows (2026-09-06)

The corroboration claim -- a player icon moving at running speed should be
making footstep sounds -- measured over all 28 ability-demo clips. Motion class
from the MEDIAN speed over a 1 s window, ability spans excluded:

    class    windows  clips   silent          95% CI
    still        601     28    35.4%   [31.7%, 39.3%]
    walk         995     28     6.3%   [ 5.0%,  8.0%]
    run          176     22     0.0%   [ 0.0%,  2.1%]

**The intervals do not overlap**, so the separation is established rather than
suggestive, and the ordering is monotonic. Running produced sound in every one
of 176 windows across 22 clips.

Two statistics that found NOTHING on a full match, recorded so they are not
retried: broadband RMS (run/still 1.04x) and step-rate cadence at 1.5-4.5 Hz
(0.92x, slightly the wrong way). A match is saturated; the demo clips are where
this question is answerable.

**The earlier PARTIAL result was an aggregate artefact, not a real conflict.**
Classifying on PER-STEP speed let tracker jitter -- which spikes to 80-724 px/s
against `RUN_PX` 45 -- read as running. See the aggregate convention in
`CLAUDE.md`; this was its third instance in one session.

## The audio channel opened, and the tray CONFIRMS it (2026-09-06)

the player recorded `b9558488a607` (Omen, 83 s, Ascent) to a deliberate protocol --
equip, hold the target while stationary, cast, pause, repeat -- and it settled
the question the corpus could not.

**The tray and the audio agree to within one 50 ms bin on 6 casts of 6**
(`prototypes/audio_events.py --align`). Two independent readers, a teal pixel
count in the HUD and an RMS envelope of the audio, sharing no code, no pixels
and no failure mode. That validates the tray reader as much as the audio.

**The second teleport cast has FIVE SECONDS OF DIGITAL SILENCE in front of it**
-- every bin at the 0.0002 noise floor against a cast peak of 21.1. A reference
cut with nothing to be confused with, which is what no amount of filtering
recovers from a clip where the player was running.

**The equip sound is visible**, and it is the claim arriving independently:
two events at 3.65-4.80 s and 13.90-15.05 s, **duration 1.15 s to the bin and
peak 9.2 / 9.4**, one before each of the two teleport casts -- and the player equipped
exactly twice. Other slots are weaker and not claimed; the first E cast has
nothing before it at all, so coverage stays unverified exactly as the player hedged it.

**NEXT on this thread:** cut the references (the ult voicelines already exist,
56 of them, all decoding), then a matched filter, then NMF with a fixed
dictionary for the overlapping case. `prototypes/passes.py`, not another decode.

## Picking up

**2026-09-06, late. A long architecture session. Six plan items, and the
running theme is that two of them were WRONG and the measurements said so.**

Read `BACKLOG.md` first -- it is new, and it holds everything tabled with the
reason and the trigger that would un-defer it.

**What shipped:**

* **`floor_mask` was forked for ten days** and is reconciled (`18b0912`).
  78.8% / 77.9% IoU at 100% recall against the paintings, up from
  57.8% / 74.0%. **A SITE IS FLOOR** -- the correction, mid-fix, and it caught a
  real defect: 9.6% of stored self positions sit inside one;
* **`reticle doctor`** -- the repo's half of `status`. Six structural checks,
  and it found a manifest contradiction nobody was looking for
  (`2ba870ccbd50` tagged small-widget, ingested bigmap);
* **`l1/roster`** -- alive counts are stored, riding the HUD pass for free.
  The audit that validates it now runs off L1 with no decode and reproduces the
  seek path exactly;
* **`metrics` intervals** -- `wilson`/`bootstrap_ci`, on CHANGED only. The plan
  said to soften BROKEN with them, which was backwards;
* **`reticle/track.py`** -- motion as a property of IDENTITY, 18 self-tests,
  Hungarian assignment;
* **the entity model doc gained §6**, republished: the drivers ARE the tracking
  constraints, with the fourteen-row invariant inventory.

**Three measurements that changed the plan rather than confirming it:**

* **overlap is TRANSIENT** (the claim, tested): median 4.75x extent
  variation over a window, 9 of 10 events, 12% of frames a clean look. So
  identity precedes grouping, and the labelling pass must show a WINDOW. The
  grouping pass is therefore NOT next;
* **there is no dash mode** in 102,239 steps -- a smooth decay from the walk
  ceiling, so `track.DASH_PX_S` cannot be validated and the census refuses to
  quote a defect rate resting on it;
* **`filter_track` cannot tell a teleport from a phantom**: 54.7% of the 11,599
  observations it drops sit at teleport distance. Backlogged.

**Item 1 is DONE**: `filter_track(..., motion=None)` takes a `track.CLASSES`
key, the default path is byte-identical on all five sessions (93,553 points),
a teleport is kept and never interpolated across, and seven self-tests cover
it. `jump_census.py --motion` measures what opting in would do:

    observations kept    default   walker   walker_dash   walker_teleport
    pooled 102,765        88.7%    81.9%       95.0%          89.5%
                                  -6,987      +6,508          +835

**That is not what the entry predicted, and it re-aims item 2.** `admits` makes
two changes at once -- it adds the teleport branch and removes the 1.6x slack
the fixed gate always had. Against a strict walker the teleport branch is worth
+7,822; the lost slack costs -6,987 of it. Three of five sessions come out
NEGATIVE. So the old gate's slack was doing a motion class's job badly, for
every agent at once.

**Item 2 is BUILT and MEASURED** (`prototypes/cast_motion.py`), and it found
why the chain underperforms. `filter_track` also takes span-conditional motion
now -- `[(t0_ms, t1_ms, class), ...]` -- which is the mechanism item 2 wanted.
The class map is derived from `ability_reference`'s `functions` field rather
than hand-listed (and `Displacement` had to come out of it: it licensed jumps
for four ultimates that move ENEMIES, not the caster).

**What a teleport actually looks like, measured for the first time** -- largest
step in the 3 s after each teleport cast, agent from the ingest tag:

    yoru GATECRASH 4.6 / 6.3 px    omen Shrouded Step 38.5 / 40.1 px
    veto Crosscut 65.0 / 6.8 px    chamber Rendezvous 323.8 px

**`track.TELEPORT_PX` (200 px) is far too high, and `walker_teleport` refuses
three of the four real teleports it exists to admit** -- "too far to walk, too
near to be a teleport". The default gate refuses them too. Every SHORT teleport
lives in that dead zone, which is also why item 1's session-wide class was only
+835: the teleport branch almost never fires on a real teleport.

**NEXT: `TELEPORT_PX` wants re-measuring, and n=8 on 4 solo clips is not enough
to refit it on** -- fitting a constant to the observations that must pass is
the degenerate-crop mistake. More teleport-agent demo clips are the cheap way
to get n, and cost the player a few minutes each. Also open from the same run: a
two-part teleport (Yoru, Chamber, Waylay) drops on PLACEMENT and jumps on
traversal, so no fixed window catches it in general.

*Superseded framing, kept for the argument:* **item 2, cast events select the class** -- and the numbers above are the
argument for it rather than a per-session agent. *a teleport activated
on the hotbar (or in audio) should be triggering an expected agent teleport.* A
session-wide class gives up the slack everywhere to buy jumps in a few places;
a cast selects the class **on a window**, spending the permissiveness only
where there is evidence for it. `ability_hud.py`, `ability_reference` and
`l1/minimap` all exist; nothing new needs detecting.

The third item, **`fit_ring` on the self key, is DONE**, and so is the
descriptor swap it pointed at. Crossed:

                        --geom bbox        --geom pin
        --desc hist       10/26  38%         9/26  35%
        --desc ncc         0/26   0%         8/26  31%

**Nothing beat 38%, and the interaction is the finding.** Geometry is worth -1
under a histogram and **+8 under NCC** -- the fitted ring was measured with an
instrument (an alignment-blind histogram) that could not detect it, so the
falsification is narrower than it first read. The wash hypothesis is confirmed
on its own terms: `chamber -> sova` at a 98% margin becomes `chamber ->
chamber` under NCC. And the two descriptors are **complementary** -- they agree
on 4 of 26 and their union is **13/26 (50%)**.

Two facts about the self glyph came out of it, neither known before: the key
survives only over the lower half of the rim (22-23% present at the top
bearings, a dropout fixed in SCREEN space), and there is no hole to find (0 in
347 frames), so the portrait cannot be had as a hole in the key.

**So stop choosing a descriptor.** Both discard most of the glyph and they fail
on disjoint agents. `BACKLOG.md`'s analysis-by-synthesis entry now names
`self_agent` as its FIRST INSTANCE -- one entity, 29 hypotheses, no assignment
problem, and a ground-truth label already in the ingest tags. Draw the glyph
agent X would produce, subtract, score the residual against `sd_lo/sd_hi`; the
wash becomes part of the prediction instead of a nuisance to remove, and the
tail becomes evidence instead of a mask. It is the only place the loop can be
proved without also solving the pruning, which is why it is worth taking before
the audio half.

**Note for item 1.** Its `BACKLOG.md` trigger is *an agent is known for a
session*, which was item 3's job, and item 3 did not deliver it. So the motion
class has to come from somewhere else -- the ingest tag on the demo corpus, or
a `--agent` argument -- or item 1 ships the parameter with today's `walker`
default and nothing opts in yet, which is what its own text proposes.

**the direction for the channel, in the words:** *identity-based
identification of entities with their temporal evolution, subject to the
invariants of their specific identity.* That is design doc §6 now.

**2026-09-06. The ability-channel handoff further down is
unchanged and still the plan for that thread.**

**NEXT: the causal, temporal, aggregated entity model.** the goal for the
next session, and every piece it needs now exists in some form. The shape,
from the framing:

* **aggregated** -- one segmentation of the widget per frame, fragments grouped
  into OBJECTS (`prototypes/widget_objects.py`), instead of five detectors
  independently thresholding the same pixels and nothing arbitrating;
* **causal** -- what is on screen is CAUSED by events the pipeline already
  tracks. Two enemies dying in one place leave overlapping X marks the killfeed
  can predict the count of; an ability implies a caster who was alive; charges
  bound how many casts are possible;
* **temporal** -- decide on a WINDOW, not on the sampled frame
  (`reticle/refine.py`), and align channels in time.

**What is ready, and what is not:**

* **DONE: alive counts are STORED.** `l1/roster` at `roster-0.1.0`, written by
  `reticle scan`; the reader rides the HUD's own frames, so it costs no decode.
  `status` reports its staleness. First session `c40d950031bb`: 1945 rows,
  90.2% answered, 0 over-five. `roster_alive.py --stored` now runs the whole
  audit off L1 with no decode and reproduces the seek path EXACTLY (43/48,
  14/16, identical histogram) -- the end-to-end check on the wiring;
* **The cross-channel audit found its first defect, and it is in the ROSTER.**
  Three cross-channel misses and the two failed start-at-five checks on
  `c40d950031bb` have one cause: an undrawn roster reads as `0`, not as unreadable.
  The earlier wording incorrectly called these all five cross-channel misses;
  two `+1` cross-channel discrepancies also exist. 9.6% of stored rows are `(0,0)` and every one is
  outside a round (0:08-1:53 pre-match, 16:06-16:09 after). Round 0's window
  starts in that prologue, so its first three probes are the three `-10`s and
  its two teams are the two `starts at 5` failures. **Not patched on one
  session** -- `DETAIL_FLOOR` exists to resolve the all-dead case, so refusing
  there contradicts its purpose. Fix is a drawn/undrawn test (as
  `minimap.widget_drawn` does) or bounding the reader to rounds. Full note in
  `roster.py`. Direction still holds and must not silently reverse: this
  calibrates the roster; afterwards the killfeed is the audited channel;
* **587c15b07779 now has a roster scan** -- 3730 rows, obtained with
  `scan --only roster` without minimap recomputation. The old 100/113 probe
  result reproduces exactly from storage. The interval-delta audit localizes
  six disagreement windows and one count increase; see the picking-up section;
* **READY: window refinement.** `reticle/refine.py`. On the ping detector it
  takes precision 26% -> 42% at NO recall cost, killing every world, xmark and
  bar false positive (`prototypes/ping_edge_eval.py`);
* **NOT ready: assignment.** Objects are described, not labelled. Mutual
  exclusion and the count constraints need the roster table to exist first;
* **FALSIFIED, do not retry as stated:** grouping does not separate ally from
  ping on any shape feature at any gap. Pings are placed ON teammates, so the
  collision is in SPACE as well as in feature space. And `ally_rings` cannot
  veto a ping -- it fires harder on pings (median 0.9 px) than on allies
  (4.0 px).

**Also landed today, all committed with numbers:**

* `587c15b07779` ingested -- Lotus, 31:04, `valorant-16x9-bigmap`. Killfeed
  19/14; `board` reads 19/13, first divergence 0:15:50. **Not in `KNOWN_KD`
  and must not be added until the player confirms it off the match history** --
  `board` is a third extractor over the same pixels, not an external source;
* **the plant is detected positively off the spike graphic**
  (`prototypes/plant_spike.py`), 210/369 rounds (57%) against the null-clock
  rule's 183 (50%), disagreeing on 11%. `rounds._plant` is UNCHANGED pending
  the labels. The absolute version of that test was wrong (6 of 16
  disagreements misread) and the relative one is 16/16 -- and the two rates
  were nearly identical, so a rate is not evidence a rule is right;
* seven review findings fixed, including `verify` being unable to fail on
  `KNOWN_KD`, and the widget-size scale is now DERIVED (exactly 1.0 on
  everything read so far, so nothing moved).

**The map art is wired into `searchable` and is the biggest available accuracy
win still unclaimed.** `searchable(labels, art=art_mask(sid))` scores 92.3% /
94.0% against the paintings where the label rule scores 65.0% / 67.6%.
Nothing downstream calls it yet -- `dynamic_eval`, `scan_ability_clip` and the
ability corpus all still pass `static=`. Switching them over is the change
that acts on the *misreads of non-minimap content as icons*, because the
art's boundary is exact and undilated where `floor_mask` grows 9 px and closes
every crack narrower than that.

**the architectural note, now a convention in CLAUDE.md: a new reader
joins the PASS.** `ping_scan` was written as a standalone video-path script the
same afternoon `passes.py` was built to prevent exactly that. Fixed, both paths
verified to return 14 pings -- but the lesson is the one to carry: a registry
the newest code does not use is not a registry.

**Four things landed earlier in the session:**

* **the last known read error in stage 02 is CLOSED.** `c40d950031bb` reads
  2/7 against `KNOWN_KD`'s 2/7. Two killfeed defects, found by the exclusion
  census rather than by looking for them: the icon test was a FALLBACK rather
  than a tier, so a portrait suppressed the area test small weapon icons need
  and **pistol kills went unparsed**; and `plate_seam` is a divider that needs
  no icon at all, which is what reads an ability kill. Nothing regressed.
  `e37fdeca944f` is still -2 deaths and is NOT a divider problem;
* **`reticle/census.py` + `prototypes/reader_census.py` exist**, and the audit
  they were built for is the thing to keep running. Decode is 93% of a stage's
  cost, so a census pass over a session is cheap relative to what it finds.
  **`ocr.py` has ~12 unexamined guards of the same shape** and the scoreline's
  transient extra digit on `9acf02f98283` is probably one of them;
* **decode once, feed many.** `decode.sample_multi` + `reticle scan` run both
  stage-02 halves in one pass, 45% saved, frame-for-frame identical. `hud`,
  `minimap` and `scan` all drive the same `_HudPass`/`_MinimapPass`. The
  killfeed overlay mask is cached per session at `<store>/masks/`;
* **the shipped minimap reader now has a widget guard** (`minimap-0.2.0`), and
  the re-validation of the position track is the live piece of work -- see
  below.

**PINGS ARE DONE AS A DETECTOR, and the clip falsified why it was asked for.**
`prototypes/ping_scan.py`. Five glyphs, and **the LIFETIME is the feature**:
7.0 s for standard / need help / watching here / on my way, **10.0 s for
danger**, exact to 0.1 s at a 10 Hz sample. Hue alone gives 15 true and 24
false; the lifetime gate leaves 14 true and 0 false, with a truncated run
reported UNCONFIRMED rather than guessed at. A ping does NOT expand -- full
size in under one frame -- so the entity model needs no fourth extent value.
Details and the two ways a persistence gate can be fooled are in that module.

**What is worth doing next on pings**, in order, none of it started:

1. **ingest the two clips** so the events have a real session id. `ping_scan
   --emit` writes `<store>/events/ping/<session>.jsonl` and nothing has been
   emitted yet, because inventing a session id would put rows in the store
   under a key no manifest backs;
2. **a ping over the VOID is invisible to this** -- off the opaque slab the
   world shows through and hue means nothing. How often that happens is
   UNMEASURED and it is the first thing to check on match footage;
3. **`on_my_way` (hue 32) sits closer to `need_help` (17-22) than any other
   pair**, and both were measured on one map. Those two are what breaks first
   on a different map;
4. `watching_here` has n=1 and `on_my_way` only appears in its own short clip,
   so their lifetimes are ASSUMED from the other three rather than observed.

**THE LIVE PIECE: re-validate the minimap position track at `minimap-0.2.0`.**
the call, 2026-09-05: add the guard, then re-validate; checking the rate on
a second ordinary session first is TABLED.

`cmd_minimap` had no widget guard of any kind. Measured over all 27757 frames
of `a06f04a0059f` at 15 Hz: `drawn()` refuses 5.0% where `usable()` refuses
2.2%, and those frames yield 3605 self and 4178 ally candidates -- 2.6 per
frame, harvested from open scenery. `minimap.widget_drawn` is now called per
frame and a refused frame is stored as a row with NULL positions rather than
dropped, so the hole stays visible to `filter_track`.

`drawn`/`usable` were PROMOTED from `prototypes/minimap_temporal` into
`reticle/minimap.py`; the prototype re-exports them, so there is still exactly
one implementation.

**That moves every stored minimap number**, so `xmark_eval.py` and
`chokepoint_eval.py` both take `--no-guard` to reproduce the figure on record
and are being run both ways on `a06f04a0059f`. **Until those two numbers are
in, the position track's validation status is UNKNOWN, not good** -- the
figures in `prototypes/CLAUDE.md` were measured with the phantom frames in.

**2026-09-05. The ability channel was re-founded on a different question, and
the full argument is a document rather than a handoff:**

**The ability event log** -- `docs/ability-recognition.html`,
https://claude.ai/code/artifact/bffd7660-cd3e-4e6f-ada9-3be6b0dca887
**The minimap entity model** -- `docs/minimap-entity-model.html`,
https://claude.ai/code/artifact/324e1c5f-9240-4b13-8ff1-59adb24a2f06
The first is what the log contains; the second is what an entity IS, with a
driver PER PARAMETER. Read both before picking this up; below is only state.

**What today settled, in one place.**

* **the labelling pass is DONE** -- 5 sessions, 161 records, 58 new positives,
  giving 85 pos / 252 neg over 9 sessions, up from 27 over 4;
* **it falsified the claim it was run to support.** `patch_range` pooled AUC
  **0.86 -> 0.57**, consistent 4 of 9. The break is perfectly confounded with
  capture regime (4 ordinary captures vs 5 `infinite-abilities` demos), so the
  corpus cannot say whether the feature never generalised or the demos are a
  different world. **One ordinary-capture session labelled the new way is the
  one footage ask**, and it is worth more than any number of demo clips;
* **the weighted combiner does not earn its parameters.** Equal-weight z-sum
  matches or beats it in every configuration (0.74 vs 0.69 AUC), and sign
  agreement is 100% across all 8 folds -- so this is not fold noise, the
  features are near-redundant. Label volume was never the blocker;
* **per-session z-scoring is worth more than any weighting** (0.74 vs 0.64).
  The dominant recoverable variance is per-session, not per-object;
* **current honest best**: equal-weight z-sum, per-session z, leave-one-session-
  out -- precision 0.36, recall 0.68, AUC 0.74, against a 0.21 baseline.
  **CORRECTED 2026-09-06: it is NOT established as worse than the 0.49 @ 0.85
  that was on record.** That recall rested on 27 positives, 95% CI
  [0.675, 0.941], against 0.68 on 85 at [0.577, 0.772] -- they overlap, so the
  old figure was too weak to be worse than rather than better. Clearing the
  0.252 class baseline IS established. This sentence asserted a decline for a
  fortnight and the arithmetic never supported it; `metrics.wilson` exists now
  so the next one says so on its own;
* **the cast-anchored detector is built and emitting.**
  `prototypes/ability_cast.py`, joining `ability_hud.py`'s tray drops to the
  reference kit: **24 casts, 27 of 43 agent-named positives explained (63%)**,
  and `--emit` writes events to `<store>/events/ability/`;
* **"slot X never drops" was a defect in the READER.** The ult pips desaturate
  with the bar, so the existing teal mask reads them: slot X goes 909 -> 0 teal
  px between 28.0s and 28.5s against a Hunter's Fury label at 28.2s. Two bugs
  compounded -- `casts()` looped `range(3)`, and `drawn()` refused the frame
  because an all-spent tray reads as "not rendered". Both fixed;
* **a cast buys the EVENT cheaply and NOT the POSITION.** Widening the position
  window never raised the number of correct picks (3, at every width), so
  position is emitted only when the window holds exactly one candidate -- 2 of 2
  exact -- and is null otherwise, with the candidates carried along. Time and
  identity come free from HUD structure; location still needs the weak detector.
  **State this wherever the 63% is quoted.**

**the domain facts from today, none recoverable from pixels.** Detail is in
the module docstrings and the design doc; the heads only:

* **controllable deployables emit vision cones too** -- Owl Drone, Tejo's
  Stealth Drone, Skye's Trailblazer AND Guiding Light, Fade's Prowler, Killjoy's
  turret. Same half-angle is EXPECTED, not known. `self_cone()` cannot see them,
  and `cone_cond` -- now the best single feature, inverted, 7 of 9 consistent --
  is computed against the player's cone only. See `minimap_cone.py`;
* **`radius_ring` is what a DEPLOYED device draws, not placement** (Killjoy,
  Chamber, Veto). The ring is not the device: a candidate on the perimeter sits
  tens of px from its object;
* **held placeables want a `mode` field**, currently leaking into category names
  (`place_color`, `smoke` vs `smoke_deployed`). A preview sits at the player's
  feet, so it contaminates `self_d_med`;
* **deployed smokes are one agent-independent class on purpose** -- Jett's
  Cloudburst and Viper's Poison Cloud are both generic `smoke`, because the
  minimap carries no thrower identity;
* **placement hold time is unbounded** -- only the ~1-2s before the commit
  carries positional information; a long hold is its own signal;
* **`infinite-abilities` is a misleading tag on the five demo sessions** --
  toggled on to charge the ult, then off. `2ba870ccbd50` (Brimstone) genuinely
  had it on. **Viper's Pit is SUSTAINED**, so its bar releases when the pit ENDS
  (drop at 44.0s against labels at 36.9-42.6s);
* **Skye's Regrowth drains only while healing someone**, so `no cast` in a solo
  clip is correct, not a sampling defect.

**The cone tint is real and `blob_colour` structurally cannot see it.** Killjoy's
turret cone is green-tinted; `minimap_dynamic.blob_colour` gates on `s > 90`
before naming any colour and a translucent tint never clears it. Needs its own
low-saturation hue test -- do NOT loosen `COLOUR_SAT`, which is load-bearing.

**NEXT SESSION STARTS HERE: A LABELLING PASS ON OBJECT GROUPING.** the
call, 2026-09-05, closing the session -- *next session we can start on the
labelling pass.*

**Nothing in the label store says WHICH CANDIDATES ARE ONE OBJECT.** Grouping
has been in this pipeline since `ability_corpus` and has never been scored
against anything, so three separate things are currently unfalsifiable and one
pass settles all of them:

* the **extending signature** in `ability_cast.py` -- distance from an origin
  increasing over >=3 fragments. It resolved Viper's Toxic Screen correctly
  (+9.7 deg, 3 fragments) and returned three bolts for Sova's ult, but the rule
  was designed after looking at the Toxic Screen window, so that case is what
  it was fitted to rather than evidence for it;
* the **onset rule** it replaces for extending abilities (300 ms, 60 px);
* the **10 refused positions**, which are refused precisely because nothing can
  say whether several candidates are several objects or fragments of one.

Before building the labeller: **invoke the `labelling-pass` skill**, and render
and review the candidates first -- launching a GUI against unreviewed
candidates has three recorded recurrences and cost the player real clicking time
twice. `review_candidates.py` gates it.

**THE PING CLIP IS RECORDED AND IT FALSIFIED THE REASON FOR ASKING FOR IT.**
`2026-09-05 17-39-40.mp4` (65 s, four types) and `2026-09-05 17-57-24.mp4`
(on-my-mark). on watching it back: *they did not seem to radially
emanate*. Measured at 60 Hz and the player is right --

    7.133 s   nothing
    7.150 s   the diamond is ALREADY AT FULL SIZE

**There is no growth phase at all**, no ring, no arcs, and the glyph then sits
static for its whole life. So **a ping is not a third extent kind** and the
entity model does not need a fourth `extent` value: a ping is
`origin=fixed, bearing=absent, extent=none`, the same parameter shape as a
deployed device, and its identity is carried by GLYPH SHAPE AND COLOUR rather
than by motion. `git show d15418c` is the commit that claimed otherwise.

That also removes the reason to point the object-grouping labeller at pings
first. The pitch was *fragments of one expanding ring are the grouping problem
in its purest form*; a ping is one compact ~8x8 blob, which makes it the
EASIEST class in the store, not the hardest. It is still worth labelling -- as
a clean, cheap, four-class glyph problem with free labels -- just not as the
grouping case.

Where the older claim came from is worth knowing before it is written down
again: *a ping is an expanding ripple whose fragments are thin arcs* came off
the colour-free pass on the SMALL widget. Either the animation differs at that
size, or those arcs were something else. Do not re-assert it without a clip.

Glyphs seen so far, all ~8-10 px, hue is OpenCV:

    cyan diamond      hue ~82    the standard ping
    orange flag       hue ~17-20
    red triangle      hue ~173   danger (last in the order, so this is it)
    yellow stopwatch  hue ~32    on my mark (its own clip)

the order in the spam clip was **standard, need help, watching here,
danger**; three glyphs were isolated from it, so one of the middle two is
still unassigned. The warm Sunset scenery shows through the semi-transparent
widget at hue 10-22 and floods any saturation-based finder, which is why the
middle of that clip is noisy -- **a ping finder cannot be a colour threshold**,
it has to be shape against the opaque slab.

**QUEUED CAPTURE (SUPERSEDED, kept for the reasoning): a PING clip.** *I want to record a ping
minimap session where I just spam ping for a minute or so.* Same shape as the
one-agent-per-clip demo corpus and the same reason it works -- the player knows what the player
did, so the labels are free and exact.

It is worth more than a confounder clip. Pings are named in the endstate
alongside abilities (*labelling of abilities and pings on the minimap*), the
only evidence in the store today is a handful of rows from the colour-free pass
(*a ping is an expanding ripple whose fragments are thin arcs*, aspect ratios
that would have been deleted by a shape filter), and a minute of deliberate
spam gives more instances than the whole corpus has.

Two things it settles that nothing else can:

* **it is a THIRD extent kind.** The entity model has `extending` (outward
  along a bearing, a wall) and `radius` (fixed, a smoke). A ping expands
  RADIALLY -- a growing radius with no bearing at all -- so the model needs a
  fourth value and the ping clip is what measures its rate and lifetime;
* **fragments of one expanding ring are the grouping problem in its purest
  form.** Thin arcs at a shared centre, appearing over successive frames,
  which the onset rule and the bearing rule both handle badly. If the object
  grouping labeller is built first it can be pointed straight at this.

Pre-ingest, per the root checklist: crosshair centred, perf stats text-only,
shooting-error off, minimap fixed/always_same/uncentered, record the widget
size and the outline colour, and run `clip_preflight.py` BEFORE ingesting --
the first take of the last sitting was recorded with side-based orientation and
the whole widget was rotated 180 degrees.

**Then, in order.** (The event log doc's SS7 is the fuller version.)

1. **Label negatives on `a06f04a0059f` (53 positives) and `5822b6646448` (35).**
   Both were labelled POSITIVES-ONLY, so the scorer skips them for having no
   both-class labels, silently -- 88 positives stranded, more than the whole
   usable corpus. No new footage, no decode. Render and review the candidates
   first; that mistake has three recorded recurrences.
2. **One ordinary-capture session labelled the new way**, to break the regime
   confound. Until it exists, do not fit anything across both regimes.
3. **Audit the other readers for silent exclusions.** Every real gain today came
   from finding something discarded without a word -- the both-class check,
   `range(3)`, `drawn()`. `killfeed.py`, `scoreboard.py` and
   `minimap_temporal.usable()` all carry guards of the same shape.
4. **Audio**, now genuinely unblocked: `audio_probe.py` killed onset detection
   and said a matched filter needs a reference cut at a known cast time. The 56
   ultimate voicelines are the cuts and the tray now supplies the times. It is
   also the only channel for OTHER players' casts -- and the framing is why
   that generalises: **audio range is roughly the observable range, and roughly
   what is worth recording**.
5. **A low-saturation tint test, and a deployable cone seed.** New observations
   rather than recombinations of the exhausted bank. Killjoy's turret cone is
   **100 degrees** against the player's measured ~112 -- from the reference
   text, not a measurement, so do not reuse `CONE_HALF_ANGLE_DEG` for it.
6. **A per-ability distance-from-player prior**, to break the position ties this
   module currently refuses. only Omen's smoke and ultimate are truly
   global, so the shipped self track constrains every other ability. Measured
   medians span 21 px (Viper's Pit) to 180 px (Toxic Screen) and the ordering
   matches the families -- but n is 1-3 placements per ability, and the
   reference's `Deployment Type` is a different axis. See `ability_cast.py`.
7. **Represent an ability as ORIGIN + an OPTIONAL DEPLOYMENT VECTOR + a
   TRAJECTORY DRIVER.** the player proposed origin+vector, then withdrew it the same
   hour: objects change state after deployment, and the useful axis is what
   DRIVES the motion -- static, enemy-reactive (Killjoy's Alarmbot and turret),
   player-piloted (the scouts), player-aimed (Cypher's cam), or freeform-at-cast
   (Phoenix's wall). The vector is absent for rotation-invariant smokes: absent
   by construction, which is information, not a failed fit. `icon_facing()`
   already returns the pose half. It also re-justifies `cv2.minAreaRect` --
   deferred as a classifier feature, but the long axis of a grouped region IS
   the deployment vector, and measuring an object whose identity the cast
   already gave you is not classification.
8. **Enemy-reactive motion is an ENEMY DETECTION**, and CLAUDE.md lists opponent
   priors as blocked for want of enemy positions. An Alarmbot that moves is
   moving toward one; a turret that snaps is snapping onto one. Needs no new
   extractor -- the position track applied to an object the cast identified.
   Both are UNTESTABLE on the demo corpus (solo game, no enemies to react to),
   so this needs match footage.

**Do NOT**: add shape features (the bank is near-redundant and cannot be
usefully weighted -- measured); record more demo clips; chase `patch_range`.

**Standing hazards.** Never re-scan `2ba870ccbd50`, `eb10db50b1fb`,
`d95cfad5693a`, `79a706a7ce4c` -- the label store key is unstable. Never seed a
label file. **The tile is not the object**: at the candidate's own pixel 177 of
205 sit on FLOOR.

**`64d0fb783be2` (Vyse) is PULLED and TABLED at the call** -- 65 of 96
candidates in one 10s window, rendering as flat salmon tiles with no object.
Worth revisiting with the tint/illumination work: a coherent lit region produces
exactly that signature.

**Other live threads, not touched.** Detail in `git show HEAD~1:NOTES.md` and in
the module docstrings; heads only, because this section grows by stacking.

* **minimap position (self) is shipped; allies are not.** Next: ally identity
  across frames, then the visibility computation dA/ds, then enemy-icon states.
  Note ally CONES need no identity -- a cone is per-frame, and `ally_rings()`
  already returns the tuple `self_cone()` seeds from -- but the demo corpus is
  SOLO, so ally cones buy nothing there and everything on real-match footage;
* **vision cones:** confirm the half-angle on a second map, and find a case
  where a raycast actually crosses a boxedge pixel. Deployable cones are a
  second cone per clip on a path the player never walks, which is the cheap way
  out of "more footage than one clip supplies".

**Still true and still queued:** `ability_corpus.load_events` takes `min(dists)`
across an event's fragments, re-introducing the Phase 0a failure one level up;
three different `floor` conventions feed `self_rings`; a pulsing region still
gets one event per pulse; teleports break the shipped position track for Veto,
Omen, Chamber and Waylay.

## Live defects

Bugs with an owner and an end. The standing hazards — the ones that are properties
of the problem rather than tickets — stay in `CLAUDE.md` under "Open defects".

- **One known read error, plus two unexplained**, across 372 events at
  `hud-0.8.1`. The raw gap against `checks.KNOWN_KD` is 8 events, from 24 at
  `hud-0.6.0`: five are verified Run It Back, one is the ability kill below, and
  two are `e37fdeca944f`'s missing deaths, which nobody has looked at yet. See
  "Scoreboard divergence is a finding" in `CLAUDE.md` before quoting the 8.
  `killfeed.py` has the per-session table.
- **The one real miss left is an ability kill.** `c40d950031bb` 13:14,
  `HungryHamster5 ⊗ Me`, killed by Raze. There is no weapon icon, and the
  ability mark fragments under the white-text cut into pieces too small to be a
  divider candidate, so the band goes *unparsed* and the death is lost. Reading
  it needs a divider that does not depend on the icon — the boundary between the
  two plate colours is the candidate, and it needs no list of icons. A prototype
  landed the split correctly on 6 of 8 test bands; the estimator needs to be
  edge detection on the plate chevron rather than a brute-force search.
- **Scoreline OCR drops a transient extra digit.** On `9acf02f98283` the score
  reads `1 → 11 → 1` and `9 → 19 → 9` within half a second, i.e. a spurious
  leading `1`, and `verify` flags 8 violations there. Single-sample, reverts
  immediately, and unrelated to the killfeed. Clock read rate on that session is
  also low (39.7%). Worth a look when next in `ocr.py`.
- **`README.md` is stale.** It says HP, ammo and the killfeed are unbuilt; they
  are built, and it still describes stage 02 as scoreline-only. Fix it when next
  touching that area.
