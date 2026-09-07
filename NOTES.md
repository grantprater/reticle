# Reticle — working notes

Where the work stands **today**: the handoff into the next session, and the
defects that are live rather than standing. `CLAUDE.md` carries what stays
true across sessions — the conventions, the domain rules, the mistakes worth
not repeating. This file carries what is true this week, and it is read on
demand rather than loaded into every session.

Read it when picking up unfinished work. Update it in place; let it go stale
rather than let it grow.

Split out of `CLAUDE.md` on 2026-08-27.

## The north star for this channel (recorded 2026-09-06)

> a system that can annotate the vods, highlight the abilities, players,
> viewcones, pings, and any other icons as they evolve throughout a match

A visually checkable proof of work, and it outranks any per-detector metric --
recorded in full under "The NORTH STAR for the entity channel" in `CLAUDE.md`.
`reticle/overlay.py` is the vehicle: it exists, it already refuses to hold its
own copy of the logic, and it draws **no minimap entity at all** yet. Extending
it to the minimap channel -- tracks, not per-frame detections, every channel in
one frame -- is the concrete form of this.

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
  All five misses on `c40d950031bb` have ONE cause: an undrawn roster reads as
  `0`, not as unreadable. 9.6% of stored rows are `(0,0)` and every one is
  outside a round (0:08-1:53 pre-match, 16:06-16:09 after). Round 0's window
  starts in that prologue, so its first three probes are the three `-10`s and
  its two teams are the two `starts at 5` failures. **Not patched on one
  session** -- `DETAIL_FLOOR` exists to resolve the all-dead case, so refusing
  there contradicts its purpose. Fix is a drawn/undrawn test (as
  `minimap.widget_drawn` does) or bounding the reader to rounds. Full note in
  `roster.py`. Direction still holds and must not silently reverse: this
  calibrates the roster; afterwards the killfeed is the audited channel;
* **587c15b07779's 13 disagreements remain unopened** -- it needs a scan, and
  every session now also wants a minimap re-read, which is TABLED in
  `BACKLOG.md`;
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
