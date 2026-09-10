# Reticle — backlog

Work that is **deferred, not dropped**. This file exists because the other
three had nowhere to put it:

    CLAUDE.md    what stays true across sessions -- conventions, domain facts,
                 mistakes worth not repeating
    NOTES.md     what is true THIS WEEK -- the handoff and live defects, kept
                 short on purpose and allowed to go stale
    STATUS.md    generated facts, which cannot disagree with the code
    BACKLOG.md   decided-to-defer, with the REASON and what would un-defer it

The reason matters more than the item. A backlog without one rots into a list
nobody can triage, and this repo already has the failure mode written down: *a
question written down as open stays open forever, because nothing marks it
answered.* So every entry carries **what would change to make this worth
doing** — and an entry whose trigger has fired should move to `NOTES.md` or be
deleted, not sit here looking busy.

Ordered by consequence, not by age.

---

## Separate a killfeed entry from a camera wipe by BLUR -- superseded by ORDER

**Twice demoted on 2026-09-09, and the second time it was replaced.**
Persistence settled the gate first: `checks.entry_presence` refuses a band that
never persisted and takes the confuser false positives to zero at every tier,
so nothing downstream needs a blur signal to get the right answer. What stayed
wrong was `kf_entries` itself, the per-frame column, which reaches six on one
wiped frame.

Then the player named a better rule for that, and it carries no threshold at
all where blur needs one fitted on development windows nobody has cut. **A
killfeed entry renders in a fixed ORDER** -- plate, then furniture, then glyphs
-- and unrenders in reverse. A band that appears with full contents in a single
frame violates the ordering and is a wash; a band that loses contents while
keeping its plate AND its divider is one entry blinking. Both terms are already
computed in `analyse_killfeed`. It is item 2 of the next session's list in
`NOTES.md`.

Kept here for the MEASUREMENT below, which stands whatever reads it: the two
classes are separable on sharpness, and that is worth knowing if the ordering
rule turns out to need corroboration. Do not fit its threshold on the frozen
windows.

`_entry_bands` decides an entry from plate colour alone and splits a tall run
into `round(h / PITCH)` bands, so a respawn or camera wipe painting the ROI in
both plate colours manufactures three to six entries out of one wash. Refusing
the bands that carry none of an entry's furniture (`EMPTY_BAND_REFUSALS`) took
out roughly half; the survivors return `no_divider`, which is a class real
entries also reach, so no refusal class finishes the job.

**The player's suggestion measures well.** A wipe is blurred and its sub-bands
share horizontal bounds, because they are slices of one rectangle rather than
separate entries. Over 1,298 bands on `c40d950031bb`, mean horizontal Sobel
magnitude inside the band's own plate extent:

                             bands   median   p05    p95/max
    real activity (w1)        1166     58.4   45.6      70.6
    wipe w5                     61     16.8    2.8      28.2
    wipe w6                     71     11.0    8.9      13.1

The real p05 is 45.6 and no wipe band exceeds 28.2, so the classes are
separated in these windows. Slide-in frames -- a plate drawn before its content
-- keep the sharp edge (42-70), which is why this signal costs nothing that
`no_icon` costs. Width identity corroborates more weakly: among frames holding
several bands, the widths agree within 4 px in 20% of real frames, 55% of w5
and 100% of w6. Real entries differ in width by more than two to one, which
`_row_profile` already says.

**Do not fit the threshold on these numbers.** They were measured on the frozen
P3 evaluation windows, and choosing a cut from them turns the test set into the
training set. Cut new development windows -- other wipes, other sessions -- pick
the threshold there, and let `reticle fidelity-check` stay an untouched check.

Persistence was the stronger rule and it landed on 2026-09-09 in
`checks.track_entries`. Over the frozen windows at native rate, eleven real
entries span 4733-8017 ms and eleven wipe tracks span 0-667 ms -- classes that
do not come close, needing no threshold fitted anywhere.

## `reticle/` has NO ability detector, and the five prototypes are triaged

**2026-09-10, prompted by `doctor`'s new PROMOTE check.** `ability_entities.py`
is an adapter over `adjudication.ability`, which builds entity hypotheses from
stored observations -- and nothing in the shipped tree produces a minimap
ability observation from pixels. Every detector is in `prototypes/`. The five
the check listed, each now decided in `notes/predictions.jsonl`:

* **`ability_eval`** -- declined. A SCORER, not a reader; promoting an
  evaluation harness would make *in `reticle/`* stop meaning *in the pipeline*.
* **`ability_cone`** -- declined. Its hypothesis needed an absolute level and
  failed for the reason `CLAUDE.md` gives about every absolute level here. Its
  incidental finding, that seeding the cone from a fitted self ring lifts
  availability from 4/50 to 89% pooled, is **already shipped in a better
  form**: `overlay.py` seeds from `self_icons` and settles the lobe against the
  drawn light. Nothing left to promote.
* **`ability_signed`** -- declined FOR NOW. `dark >= 10` genuinely beats the
  sign comparison on both axes (95.5%/43.8% against 81.8%/39.1%), but it is a
  threshold fitted on 22 objects where the thing it replaces is not a threshold
  at all. **Revisit when the labels grow**; `d95cfad5693a`'s 47
  reviewed-but-unanswered candidates are the cheapest source.
* **`ability_scale`** -- measured, and folded into the entry below.
* **`ability_disc`** -- declined too, and for a better reason than the two
  blockers first recorded here. It is a detector for ONE visual family, and the
  mining pass in `docs/MINIMAP_APPEARANCE_MATCHING.md` exists so that a
  detector per family is not needed. A class-specific detector is a candidate
  CHANNEL of the general proposer -- the black-hat is scale-selective where the
  foreign mask is not -- never the reader. See *A class-specific detector is
  not a step toward this*.

**The peak-finder detour, kept because both halves are worth having.** The
prediction was pre-registered and HELD: local maxima are monotonic in the
response floor at all four kernels where thresholded blobs ridge at three of
them, confirming that merging past `AREA_MAX` is what makes recall
non-monotonic. It bought nothing. Scored against the painted frames, where
precision is real:

    detector, abilities only        d95cfad5693a        a06f04a0059f
    blobs, calibrated             100.0% / 100.0%     90.9% /  32.3%
    peaks raw, floor 60           100.0% /   4.0%    100.0% /   1.7%
    peaks smooth, floor 60         94.4% /  13.4%     72.7% /   4.4%

recall / precision. **The candidate-anchored sweep could not have shown this**:
there, only recall and stream size are honest, and peaks read as a modest trade
at 95.2% recall against the blob finder's 90.5%. The painted frames turn that
stream into 872 and 636 false positives. Do not choose an operating point on
labels that cannot score precision.

**THE SELF ICON IS A VALID PER-SESSION RULER; WIDGET WIDTH IS NOT.** The
minimap has a zoom slider, so rendered size is a per-session setting. Measured
over two sessions whose icons differ in size by 1.667x:

    session         widget    n   icon r   self r   icon/self
    a06f04a0059f      465    11    10.00     5.47      1.828
    d95cfad5693a      331    31     6.00     3.29      1.824
    between-session ratio                              1.002

The widget WIDTH ratio over the same pair is 1.405, so a constant scaled by
`minimap.widget_scale` mis-sizes an ability icon by about 19% between them:
predicted radius 7.12 against a measured 6.00, where the self-radius ruler
predicts 6.01. **Radii here are black-hat half-max and are NOT `fit_ring`'s
`r`** -- the ruler and the thing measured must share one definition, or the
per-session constant this removes comes straight back.

What `ability_disc` needs before it ships as the ability observation reader:

1. **per-session sizing.** `BH_K = 27` and `AREA_MIN/MAX = 40/900` are eyeballed
   on one session. Express them as multiples of the self radius above;
2. **stop thresholding.** The operating point is a RIDGE, not a plateau: recall
   is non-monotonic in `BH_MIN` because lowering the floor merges neighbouring
   responses past `AREA_MAX` and the icon is discarded whole. `BH_MIN = 130` is
   the level at which blobs happen not to merge on four sessions, and it will
   not transfer on that basis. Take local maxima of the response at the disc
   scale, or a watershed, instead of a global cut plus an area filter.

Its measured recall is 85.7% (18/21) at 2.4 candidates per frame against
`minimap_dynamic.detect`'s 6.8, and the black-hat response separates 3-4x at the
labelled positions across every kernel from 15 to 81 -- so the primitive is
sound independently of where the gates land. Precision is NOT measurable from
that run and must not be quoted: the labels are candidate-anchored. The
exhaustively painted frames are what make it measurable.

**Fixed on the way in:** `prototypes/minimap_dynamic.py` imported
`reticle.geometry as _G` INSIDE one function while three others referenced it,
so `load_geometry` raised `NameError` and the whole ability line was dead. It
had been dead long enough that nothing noticed.

## A killfeed ability icon says that ability was used, and by whom

The divider on an ability kill is the ABILITY's icon, not a weapon's -- see
`c40d950031bb` 13:14, `HungryHamster5 [ability] Me`. So every ability kill in
the feed is a labelled ability use with a timestamp and a named owner, standing
about ten seconds. That is a channel the ability line does not currently read,
and it is exactly the kind of evidence it is short of: the gallery's held-out
problem is that **one** contrast exists in the whole corpus, because every
ability but Deadlock's pair appears in a single session.

What it would give, and what it would not:

* an ability use with an OWNER, which onset proximity and `position_persistence`
  currently have to guess at, and which `ability-entities` wants for per-agent
  death;
* a time bound tight enough to anchor a phase -- the entry stands for seconds
  after the kill, so the icon dates the use to a window, not an instant;
* only abilities that KILLED. Smokes, walls, recon and every non-damaging
  ability never appear, so the sample is biased towards damage and says nothing
  about the classes the gallery is actually failing on.

Cost, and the player flagged it: extracting WHICH ability the icon names needs a
mined template per ability per agent, the same work the weapon icons took, and
there is no list to start from. Read it as a corroborating channel for uses the
entity channel already hypothesises before trying to identify icons cold.

## The vision gate on enemy-team entities is a RULE, and nothing consumes it

**Domain, 2026-09-10.** An enemy-team entity is drawn on our minimap only where
our team can see it. That covers enemy player icons and the enemy-side spike
lying on the ground alike. The entry below applies the weak form of this to
ALLIES, where light is only a correlate; for enemy-team entities it is a
NECESSARY CONDITION, which is a far stronger gate, and no reader uses it.

**Use `lighting.py`, not `cone.py`.** The drawn light classifies each floor
pixel against the map's own `lo_gray`/`hi_gray` resting states, so it reads what
the game shaded. The raycast reconstruction over-claims its area by roughly 3x
-- a gate that wide refuses almost nothing, which is a fair reason to have left
the gate out while that was the only instrument. It is no longer the only one.
The collective-viewcone entry says the same thing from the other side: *the
interior-appearance invariant is not wired to anything. The area exists;
nothing consumes it yet.*

Three constraints on how it may be used:

* **it refuses, it never confirms.** An enemy-team detection on unlit floor is
  a false positive; one on lit floor is merely permitted;
* **absence outside the light says nothing**, so the gate cannot raise recall
  and must never be read as though it could, or coverage becomes biased by
  where the team happened to be looking;
* **the exception class is already an entry here.** A reveal ability shows an
  enemy with no sight of them -- *A RECON DART PULSE is a legal origin for an
  enemy appearance*. An unlit enemy icon is therefore a refusal OR a reveal,
  separated by the ability channel and not by the light. Store the
  disagreement; never delete the detection.

`lighting.py` is not ground truth and says so: any map object whose resting
state is the bright one reads permanently lit, and the mechanical doors on
Ascent and Lotus still do. Unknown light is never counted as unlit, which is
what stops the gate refusing on pixels that could not be classified.

**The rule is not new; it has simply never reached a reader.** The entity model
already made it an origin-time event -- an enemy-owned entity's interval ends
when it leaves the collective team viewcone -- and §11 there says the collective
viewcone *is not one more detector, it is the term four of these invariants are
written in*. **Note the error direction reverses.** That document argues for
UNDER-claiming the area, because its invariants are about disappearance and an
over-large area discards legitimate vanishings. This gate refuses DETECTIONS
instead, so over-claiming merely wastes it while under-claiming deletes real
enemies. One instrument, two opposite failure directions: keep the gate as a
stored disagreement rather than a silent filter, and report what it refused
beside what it kept.

**Trigger: G3, the enemy reader**, in `docs/MINIMAP_APPEARANCE_MATCHING.md`.
The hard part of reading a red ring off a translucent widget is the false
positives, and a necessary condition removes them without touching the
detector.

**Own-team icons are always visible**, so the gate is scoped to the enemy half
and must never touch ours: a missing own-team icon stays a detection failure
rather than information. One consequence worth having: on the attacking half
the spike's state is fully observable at every instant -- base-up beside a
player is carried, base-down is on the ground, the planted glyph with the HUD
graphic is planted.

**A reveal shows PLAYERS ONLY** -- not the spike, not abilities (domain,
2026-09-10). So the reveal exception applies to enemy player icons alone, and
for the enemy-side ground spike and enemy ability entities the gate is
EXCEPTIONLESS. That makes them the better instrument of the two: an unlit
enemy-side spike is a false positive with no second reading, so it can validate
the drawn light in a way an enemy player icon never can.

## Reject ally icons that have no light beside them

**Measured 2026-09-07, rendered and inspected, deliberately NOT wired.** An ally
lights the ground around itself, so an icon with no lit pixels within 26 px is
a spawn barrier or a death X -- the two false-positive classes `minimap.py`
already names, and the reason `l1/minimap` records `n_allies = 4` at a moment
when all four teammates are dead. It rejects 24.5% of detected icons on Ascent
and 15.8% on Lotus, and the rejections do land on featureless floor marks while
portrait-bearing icons are kept.

**Two reasons it is not a gate yet.** In a frame with almost no lit area every
icon rejects -- visible on a Lotus ability-screen frame where the only surviving
icon scored 0.11 -- so it needs a light-budget guard. And the test should be
persistent rather than per-frame: a barrier does not move and an ally does, so
"unlit beside it for N consecutive frames while the team has light elsewhere" is
the honest form, which needs the tracker rather than a single frame.

**Trigger: any work that consumes `n_allies` or the ally channel as a count**,
because that is where the phantoms cost something. Scoring it wants the ROSTER,
which is the label-free precedent that took the ally residual from +0.99 to
-0.15 -- and neither painted session has an `l1/roster` table today, so a
`scan --only roster` on `a06f04a0059f` is the cheap unblock.

## Guess the emitters the aggregate lost, as an ensemble fit

**Measured 2026-09-07 leave-one-out: a good DIRECTION estimator, a poor bearing
one.** Hide an icon that was actually detected, and recover its bearing from
residual light alone -- the light no other cone explains:

    median error   within 30deg   within 60deg   opposed >150deg
    ascent  39.2deg     42.2%          65.9%           3.0%
    lotus   48.8deg     39.7%          54.5%           5.3%
    random  90   deg     16.7%          33.3%          16.7%

Two and a half times better than chance at 30 degrees, and it almost never
points backwards. But a 40-49 degree median error is large against a 103 degree
cone, so it can place a coarse cone for a track with NO detection and must not
refine one that has a detection. That is the same shape as `cone.resolve_lobe`:
the binary choice is reliable, the continuous estimate is not.

**Trigger: tracks that persist through a detection gap.** The value is a
teammate the ally channel dropped for a few frames, not a better bearing for one
it can see. Validate leave-one-out, never by explained lit area, which is
circular. See `reticle/cone.py` and the memory note on ensemble guessing.

## ~~Recover a refused self position from the icon's APPEARANCE~~ CLOSED 2026-09-09

**Measured twice and closed both times.** The design is Step 2 of
`docs/MINIMAP_APPEARANCE_MATCHING.md`; the numbers and every predeclared
prediction are in the store's `notes/predictions.jsonl`.

A recent-template descriptor searched over a disk around a causal prior looked
excellent at native rate -- 110/111 frozen answers within 3 px -- and collapsed
at the reader's real tiers, to 80.0%/68.4%/12.5% precision at 15/10/5 Hz. Wrong
offsets sat confidently above the score gate, so no threshold could repair it.

The joint fit replaced the disk with permissive current-frame ring proposals, so
that a wrong offset must also explain self-coloured pixels. **That fixed the
confident errors** -- 97.92% of ungated answers within 3 px, exact above any
modest gate -- and it did not matter, because of the denominator:

    drawn refusals in the development interval            1594
    ...that a recent template can answer at all            164   10.29%
    ...with a forced bracket, i.e. MEASURABLE at all       137    8.60%

**Refusals arrive in long runs**, and a recent template needs a recent fit.
(The original entry said the runs were portrait overlap. Inspected, not
measured -- and a 2026-09-09 cross-reference against the ally channel cut it
to a 1.2x-1.6x lift, with most refusals carrying no ally within 15 px.) 85 of 137 opportunities
had no trusted anchor; where one existed the path was nearly exhaustive, and the
motion gate excluded none of the 51 correct proposals it saw. Ceiling misses are
displaced fragments and never another icon -- 25 at 3-6 px, 26 at 6-12 px, none
beyond 12 px.

Do not re-open this by tuning a score. **The thing to model is the overlap**,
which is Step 3's directional geometry. It inherits `match_at` and the permissive
proposal call `icons(..., separation_px=0)`, whose default reproduces the shipped
deduplication -- worth 11 points of ceiling, because deduplication keeps the best
ARC rather than the fragment nearest the true centre.

## L1 cannot tell a REFUSED self read from an ABSENT widget

Both are written as `self_x = NULL` with no flag, so the standing constraint
that refusal and missing widget stay distinguishable is violated in the table
every downstream position rule reads. `cmd_minimap` writes the NULL on the
`widget_drawn` branch and again when `pick_self` refuses.

**What it costs.** `filter_track`'s docstring says NULL rows are how it tells
"a widget-absent hole from a detection miss" -- it cannot, so it treats every
refusal as a hole and refuses to interpolate across any of them. On
`c40d950031bb`, 2016 of 2676 unread instants plainly had the widget drawn,
because the ALLY channel read icons inside it at that instant.

**The interim rule is a cross-reference**, `minimap.absent_instants`: an ally
icon read at an instant proves the widget was drawn there. Sufficient, not
necessary, so it over-reports absence and the belief layer stays conservative.

**The fix is a stored column.** `widget_drawn` in L1 minimap, which is a
`MINIMAP_VERSION` bump and a re-decode of every session. Worth doing with the
18 sessions still on `minimap-0.4.0` (see the stale-L1 entry), not before.

## 18 of 20 stored minimap L1 datasets predate the Step 1 reader

Only `c40d950031bb` and `ff636d173b07` carry `minimap-0.5.0`; the rest are
`minimap-0.4.0` and one is `minimap-0.1.0`. 0.4.0 is the permissive reader with
the connected-component fallback that Step 1 removed, so its ~94% self coverage
counts positions the current reader refuses to claim.

**Any model work reading those tables is reading the old detector.** Rebuild
before using stored positions as an adjudication baseline, and fold in the
`widget_drawn` column above so one re-decode buys both.

## Two icons may be EXACTLY COINCIDENT, so no rule may assume they separate

Measured 2026-09-09 while testing whether ally centres could exclude regions.
At instants where the self reader answered, 73 self-ally pairs on
`c40d950031bb` and 104 on `ff636d173b07` sit closer than 5.7 px -- about a
third of an icon diameter -- and the closest pair is 0.7 px apart.

**This is the widget's resolving power, not a defect.** Two players who touch
are not separable at this scale, and one standing above another on a different
level is drawn at the same point. So coincidence is expected, and any rule
asserting a minimum distance between distinct icons is invalid.
`MIN_ICON_SEPARATION_PX` is not such a rule: it collapses fragments inside ONE
colour key, where the alternative reading is one icon rather than two players.

What this forbids: excluding regions from a position belief because another
icon is there; treating coincidence as a detector disagreement; assuming an
overlap resolves into distinct centres given a better fit.

## The self fit flips between the PORTRAIT and the CARRIED-SPIKE BADGE

**The player named it and the step distribution confirms it, with no labels.**
Reported at candidate 17 of the first labelling pass: the spike glyph seen at
the self icon is the badge shown while CARRYING the spike, sitting to the
bottom left of the portrait -- not a separate dropped spike.

Adjacent admitted reads, steps of 3-20 px, binned by direction (0 = +x,
90 = DOWN the image):

    bin        c40d950031bb   ff636d173b07
    90-120        43            118          down and LEFT
    270-300       75  peak      167  peak    up and RIGHT
    uniform       24             42
    peak vs uniform  3.15x        4.02x

Two peaks 180 degrees apart at a tight magnitude -- median 3.2 px, p90 4.0 --
is a fit flipping between two fixed points and back. The direction is the one
the player named.

**This is a different defect from a wrong object, and a worse one for the
labelling pass.** A fit on the badge is still the player, so the pass records
`local_player` and reads as CORRECT while the position is wrong by a fixed
offset. Class questions cannot see it. What can: the bimodal step signature
above, and a centre estimate that takes the portrait rather than the whole
keyed blob.

3.2 px at scale 0.712 is about 4.5 reference px, against an icon radius of
8-13, so the badge sits within half a radius of the portrait -- which is why
`MIN_ICON_SEPARATION_PX`, the step law and every distance gate are blind to it.

## The self key may be catching the YELLOW SITE PAINT

Reported at candidate 29 of the first labelling pass: the fit bounced between a
portion of the yellow plantable zone and the yellow self icon. The self icon and
the site paint are the same colour family.

    accepted fits landing on site paint     c40d950031bb   ff636d173b07
    site paint as a share of the slab           7.3%           4.8%
    SELF fits on site paint                    19.85%          8.40%
    ALLY fits on site paint                    10.26%          3.75%

**Self lands on site paint at twice the ally rate on both sessions**, from a
different colour key on the same widget. Not proof: the local player may
genuinely spend more time on sites than a median teammate, and this is
agreement reasoning rather than accuracy. But the disparity is consistent
across two sessions and the mechanism is named by eye.

**Unlike the spike, this one already has a channel.** `minimap.site_mask`
derives the zones from the static median map, so it needs no decode, and a site
cannot move. That makes it a usable cross-reference: a self fit supported only
by site paint is suspect. Measure before gating -- the paint is walkable floor
and players stand on it constantly.

## The self reader ACCEPTS THE SPIKE ICON as the player

The two domain facts this defect turns on are
[domain:minimap/spike-glyph] and [domain:minimap/no-spike-channel].

**Reviewed 2026-09-10 on annotated clips** (`prototypes/refusal_clip.py`, five
refusal runs on `c40d950031bb`, one per length band). Three of the five show it:

* the self fit lands on the spike icon while the player stands beside it;
* on a longer run the fit drifts from the player, through the spike, and onto a
  DIFFERENT PLAYER, with the positions before the drift nowhere near the ones
  after;
* in buy phase, with the team clumped around the spike, the fit moves to the
  spike, the buy menu opens -- the widget goes absent -- and when it closes the
  fit has settled on another player.

**The step law cannot catch this.** It rejects implausible SPEED, and a spike
lying at the player's feet is a fraction of a pixel away; so is a teammate in a
clump. The drift is a sequence of small legal steps onto the wrong object.

**No existing channel witnesses it.** `full_round_entities.py` gets the spike
from the HUD plant graphic, which covers the PLANTED spike only -- its own
limitations list says "dropped spike, death marks and last-known marks may
remain generic objects". Every clip above is a dropped or carried spike.

This is upstream of everything built on self position. `belief.resolve` treats
an admitted read as evidence and cannot be right while the reads are wrong, and
the leave-one-out motion test below is scored against these same reads.

**THE SPIKE IS INSIDE THE SELF COLOUR KEY, measured 2026-09-10 with no decode.**
`prototypes/key_collision.py` samples the label sheets, which are
`INTER_NEAREST` x5 crops with no colour transform, so every fifth pixel is a
source pixel and the player has already said what each position is. The share
of a 5 px disc that `self_mask` keys, by answer:

    answer            n     self key mean / med    ally key mean / med
    local_player    179       0.074   0.062          0.007   0.000
    spike            10       0.112   0.117          0.006   0.000
    teammate          3       0.070   0.099          0.004   0.000
    coincident        7       0.053   0.012          0.000   0.000

The spike fills the key harder than the player, and this is a LOWER BOUND: the
disc is centred on the accepted fit, the player's key is an annulus at r 6-9 px
and the spike's is filled, so the test's geometry favours the player. With the
site paint below, `self_mask` is a yellow key holding five things -- the ring,
the dropped spike, the planted spike, the carried badge and the site paint. So
no colour rule separates them and the reader must be a shape reader.

**`inner` already separates the spike and nothing reads it.** `icons` returns
the inner-disc fill fraction and `self_fit_eval.py --features` caches it, but
nothing prints or uses it. From `notes/self-fit-features-c40d950031bb.json`,
median [p10-p90]: the player 0.000 [0.000-0.112], the spike 0.156
[0.018-0.244]. The shipped `inner_max` of 0.25 admits 100% of both, so it
refuses nothing today. As a refusal it is redundant -- every labelled spike
also sits below `cov` 0.35 -- but `inner` and `cov` are uncorrelated on the
player at r = 0.025, so a joint rule may refuse the same spikes at a lower
coverage gate and keep more real positions. **No cut may be chosen here**;
these are the frozen labels.

**THE SPIKE REALLY IS A RING, WHICH IS WHY THE READER ACCEPTS IT.** Domain,
2026-09-10: the glyph is a rounded equilateral triangle with a very thin black
outline, a black dot at its centre inside a BLACK CIRCLE, and three more dots
set toward the corners. At this scale that presents a keyed annulus around a
dark interior -- exactly what `fit_ring` exists to find, and exactly what the
local player's icon is. `inner_red` is the keyed fraction of the fitted
interior, and both classes pass because both interiors are un-keyed: the player
0.000, the spike 0.156, the gate 0.25. **So the confuser is not a weak fit or a
threshold, and every proposal of the form *fit the ring better* is dead,
including arc coverage.** What separates them is what the ring fit discards: the
SILHOUETTE (rounded triangle against circle, read on the outer boundary), the
INTERIOR VALUE (portrait against black), and the dot pattern. Note that
`fit_ring` already computes `inner_v`, the interior grey mean, and `icons`
drops it -- a computed feature aimed at precisely this distinction, absent from
its output dict and from the self-fit feature cache alike.

**THE GLYPH INVERTS ON PICKUP, and that is the discriminator for STATE.** The
spike is yellow in every state, including carried by a teammate, so the ally key
holds no spike and the entire object lives in the self key. On the ground the
BASE sits at the bottom with a corner up; carried, the whole glyph is rotated
180 degrees and is slightly smaller. The transition takes ONE FRAME. A round may hold unboundedly many pickups and drops, so this is
one entity alternating between two states rather than a new entity per drop --
a lifetime model that opens a track per appearance will miscount it, and at 2 Hz
the transitions are unobservable, so state is read per frame and never from a
transition. The enemy team has no carried state on our minimap: an enemy holding
the spike draws nothing, and the icon exists only while it lies on the ground,
where it obeys the vision gate. A carrier's death drops it, and the announcer
says *spike down <location>* -- the only witness the dropped spike has.

**PRE-REGISTERED AND FAILED ON THE INSTRUMENT, 2026-09-10.** Three predictions
went into `notes/predictions.jsonl` -- the flip is readable at this scale, the
ground glyph is larger, a carried glyph is adjacent to a player icon. All ten
labelled instants were sought at native rate and read as raw pixels with no
annotation on them. None could be scored, because `self_mask` does not deliver
the glyph as an object:

    keyed components within 8 px of the labelled spike    1 to 5
    positions where it is a single component              2 of 10
    largest component                                     8-36 px
    nearest component to the fit is a 1-4 px speck        4 of 10

The glyph is plainly visible in the raw pixels at 0.712 scale, so this is a KEY
problem and not a resolution one -- `self_mask` catches a broken rim and drops
the body. **So the spike reader is not built on `self_mask` components**; it
needs the glyph's own colour band or a masked appearance fit over luma. The
keyed mass sits ABOVE the fitted centre on 6 of 10, so the ring fit is not
centred on the glyph it accepted.

A second attempt with the corrected triangle geometry failed on contamination.
A rounded triangle's widest row is its base, so the row profile of the keyed
mass should read base-down on the ground and base-up when carried; it returned
base-up on 8 of 10, with exactly 8 keyed pixels in the top row of five separate
cases. That is a sampling window clipping site paint or a neighbouring icon,
not a base. **Segment the glyph before measuring its shape.**

Scoring needs two things nothing has yet: per-case STATE truth, since the ten
labels say `spike` and not which state, and a window spanning a PICKUP, which is
the only place two states are known to be the same physical spike.

The reader is planned as G1 in *Icon-class order of work*,
`docs/MINIMAP_APPEARANCE_MATCHING.md`.

**MEASURED 2026-09-10, 200 labelled accepted fits, reweighted by stratum:**

    stratum      n   share    player    wrong    ambiguous
    crowded    100   62.6%     83.0%    10.0%      7.0%
    clear      100   37.4%     95.0%     5.0%      0.0%
    reweighted                 87.49%    8.13%     4.38%

Wrong ones: 9 spike, 3 nothing, 3 teammate. Every ambiguous case was crowded.
The wrong-object 95% interval is roughly 4.3-11.9% on n=200.

**About one accepted self position in eight is not the player.** On the same
session `fidelity-check` reports 0.9917 cross-rate agreement. That is
consistency and this is accuracy, and the gap between them is the standing rule
made concrete. It is the first accuracy figure this channel has had.

`belief.resolve` stamps an OBSERVED fix with radius `FIT_ERR_PX` = 2 px, which
is a false claim for those, and no work above the reader can repair it.

**The class stamp never reached the writer** -- it was added to the docstring
only -- so no row records which class list it was answered under. `spike`
cannot be split into the carried badge and a dropped one, and site paint had no
class for most of the run, so some site cases are inside `nothing` or `spike`.
Fixed for the next pass; the first pass's provenance is simply lost.

**ARC COVERAGE separates them, and nothing else does.** Recomputed on the
labelled fits (`self_fit_eval.py --features`): the player sits at cov 0.38
[0.28-0.56], and every wrong class sits at 0.28-0.30 with p90 at or below 0.38.
Lobe (0.52 both) and facing (97-100% both) do not separate at all. The wrong
accepts are all low-coverage fits sitting just above the shipped gate of 0.25.

    cov >=   players kept   wrong kept   wrong share of kept
      0.25        100.0%       100.0%          8.50%   <- shipped
      0.28         79.7%        40.0%          4.45%
      0.32         69.9%        24.6%          3.17%
      0.35         64.1%         7.7%          1.10%
      0.40         47.1%         7.7%          1.49%

**The gate alone is not the answer: it buys accuracy with coverage.** Cutting
the wrong-object rate to 1.1% costs 36% of the reader's correct positions, and
observed coverage is already only 75% of instants. Note also that there are 15
wrong examples in total, so the middle column moves in steps of about 7 points.

**What makes it affordable is the belief layer.** A refused low-coverage fit is
not a lost position: single-frame refusals interpolate at 96.4% and short runs
at 94.2%, from the reads either side, which the gate has just made cleaner. So
the pairing to measure is a raised gate PLUS `belief.resolve`, end to end --
observed accuracy up, observed coverage down, believed coverage roughly held.
Measure it before shipping either half; neither is worth much alone.

**Gate only where a confuser could be -- but VICINITY cannot be defined from
the channels.** Applying the gate only in the crowded stratum keeps more real
positions and lets far more wrong ones through:

    rule                          players kept  wrong kept  wrong share
    shipped, 0.25 everywhere            100.0%      100.0%       8.50%
    0.35 everywhere                      64.1%        7.7%       1.10%
    0.35 only when crowded               77.8%       30.7%       3.54%

Because 3 of the 9 spike cases and 2 of the 3 `nothing` cases are in the CLEAR
stratum. `crowded` asks whether a read ALLY is within 25 px, and the spike is
read by no channel, so a dropped spike beside the player is a `clear` instant
with a confuser in it. Ability icons, enemies and marks are invisible to the
test for the same reason.

**So the vicinity test has to be photometric UNTIL THE CHANNELS EXIST.** It is
properly a channel question -- is the spike there, is an ability there -- and
the answer is unavailable only because those readers are not built. Photometry
is the stand-in: is there any other drawn structure near the fit, whatever it
is and whoever would name it.
`prototypes/minimap_occlusion.py` already measures exactly that -- foreign
content against the geometry's lighting band -- and it was built to refute the
overlap story for REFUSALS. Here it would gate ACCEPTS, which is the use it is
actually suited to.

**Untested risk in raising the gate: arc coverage depends on BEARING.** The
self key survives only over the lower half of the rim, at 61-67% of bearings
150-240 deg against 22-23% at 330-30. Raising `cov_min` therefore refuses more
often at particular facings, which is a directional bias in coverage rather
than a random loss, and it is not measured. The facing angle was not kept in
the feature cache; keep it next time.

Strafing is not at risk from this rule: arc coverage is a per-frame shape and
has no motion term. That is a reason to prefer it over an anti-oscillation
rule, which would have to reason about a sequence and could mistake real
movement for a flip.

This also removes the need for an anti-oscillation rule. The portrait/badge
flip is a low-coverage fit beside a high-coverage one, so a shape gate refuses
it a frame at a time and never has to reason about the sequence.

**Class list, from the player 2026-09-10.** What can be mistaken for the self
icon: the spike, ability icons, and other players. Death marks and last-known
markers are covered by players when both are present, so they are not the
common confusion -- but they remain visible where nobody stands, so the
labeller keeps a class for them.

**The DRAW ORDER is unknown, and the player does not know it either.** Whether
the widget has a defined priority between players, the spike, abilities and
marks is unrecorded and is NOT derivable from stored data -- nothing stores
what was underneath. Recorded here as an open question rather than guessed. It
matters: if players always draw over the spike, a fit on a spike means the
player is elsewhere, which is a usable constraint; if not, it means nothing.

**The player and the spike are CO-LOCATED when this happens.** Seen at
candidate 9 of the first pass: the fit is on the player at the asked instant,
and half a second later the same map spot holds the spike, the player having
walked off it. So the reader is not jumping to a distant object -- it is
choosing between two things at one place, which is why a speed gate cannot see
it and why a better centre estimate cannot either. `8 = coincident` was added
to the labeller for exactly this, kept separate from `U` because the labeller
can see perfectly well; there is simply no single answer.

`prototypes/label_self_fit.py` runs the pass. It samples the reader's own
ACCEPTED fits in two recorded strata -- `crowded`, another read icon within
25 px, and `clear` -- so a rate over all accepted fits can be reweighted rather
than measured on the interesting case alone. 200 candidates are prepared for
`c40d950031bb`; three panels at -0.5 s, 0 and +0.5 s ring the same place, since
a dropped spike does not move and a player does.

## A constant-velocity hold does not beat a stationary one

Measured 2026-09-10 by leave-one-out over admitted reads: hide a read, predict
it from the reads before it, score against it. Velocity is taken over a 500 ms
baseline, because fit centres are integers and one sample of displacement is
mostly quantisation.

    gap     c40d950031bb hold / inertia      ff636d173b07 hold / inertia
    0.5 s   3.16 / 3.16  (39.8% better)      3.61 / 2.81  (52.8% better)
    1.0 s   5.39 / 6.14  (35.9%)             6.40 / 5.10  (48.7%)
    2.0 s   8.94 / 13.04 (27.6%)             12.04 / 11.55 (40.6%)
    3.0 s   11.18 / 19.70 (23.0%)            16.28 / 18.40 (34.7%)

Medians in px. Inertia helps only on one session at short gaps and loses badly
by 3 s, which is what a straight line does to a player who turns a corner.

**But the comparison is confounded by the entry above.** A falsely accepted
spike icon does not move, so every such read flatters the stationary hold. The
test cannot settle the question until the false accepts are gone. Do not wire
an inertial hold on this evidence, and do not conclude that inertia is wrong.

## Minimap re-validation after the `floor_mask` reconciliation

**Tabled 2026-09-06 by the player.** The commit is `18b0912`; the numbers and the
argument are in `reticle/minimap.py`'s docstring and
`prototypes/floor_mask_eval.py`.

**Job 1 is DONE 2026-09-07, and it changed shape while being done.** The
rebuild was framed as 34-36 decodes; the store's own numbers said it was 5,
because 36 session npz held 5 distinct geometries. Geometry is now keyed
`<map>__<profile>` (`reticle/geometry.py`), 11 keys covering 50 sessions,
rebuilt in 5m40s by `minimap_geometry.py --all`, which re-attaches shade in the
same write. The two constraints this entry carried are both gone rather than
satisfied: shade cannot be dropped silently any more, and `2ba870ccbd50`'s
tag/profile contradiction is settled (its own frames are Ascent at scale 1.00 --
the tag was wrong, the ingest right). `doctor` is 2 findings / 0 errors.

Two jobs remain, and the second depends on the first:

1. **re-read `l1/minimap`.** The stored track was built on the old gate, which
   admitted 13.7% of the widget on Ascent that is **100.0% outside the
   painting** — a region holding 878 stored self positions and ~8,400 ally
   candidates, all phantoms. **This is now the whole of the re-validation and
   nothing blocks it;**
2. **re-run `xmark_eval`, and treat `chokepoint_eval` as incomparable.** Its
   chokepoints are the distance-transform ridge OF `floor_mask`, so its ground
   truth moved with the thing under test — 31 chokepoints before, 14 after.
   Separation ratio is identical at 2.8x, which is all it can say.

**Trigger: before any minimap number is quoted, or any minimap work resumes.**
Until then the stored track is *known* to be built on a superseded mask, which
is a different and safer state than not knowing.

Preview measured on the OLD stored track, so not the re-validation:

    xmark_eval  a06f04a0059f      before      after
      scored                       61/67      57/67
      closest-to-X median         24.3 px    22.4 px
      closest-to-X p95           144.1 px   136.7 px
      closest-to-X max           306.7 px   235.5 px
      ally-to-ally spread        141.9 px    72.6 px

Better median, p95 and max on four fewer scored deaths: the signature of
removing phantoms rather than of a better detector.

## `lotus__valorant-16x9` finds 41% of the plant zones it should

**Found 2026-09-07 by coverage that did not exist the day before.** Keying
geometry per (map, profile) built five keys no session had ever had geometry
for, and scoring each against the wiki art put one far off the line:

    SITE vs derived PLANT      lotus bigmap  87.4%   split bigmap  87.9%
                               ascent bigmap 87.5%   split 16x9    85.0%
                               ascent 16x9   84.4%   sunset 16x9   76.4%
                               haven 16x9    74.8%   abyss 16x9    72.4%
                               lotus 16x9    35.4%   <- 732 px derived, 1793 art

Small-widget keys score lower across the board, which is expected -- the plant
tint test in `classify()` was tuned on the large widget, and `floor_mask`'s
lengths scale with the widget while the colour tests do not. **`lotus` at
`valorant-16x9` is not on that gradient**, so it is a different failure, and a
plant zone that is not labelled is a bomb site the occlusion grid calls
ordinary floor.

Not chased here, deliberately: one session reads that key
(`bdfdcf009dba`), no minimap work is queued on Lotus 16x9, and the number was
produced by an alignment check rather than by anything downstream noticing.

**Trigger: the first minimap read on a `valorant-16x9` Lotus session, or any
change to the plant tint test.** The second is the sharper one -- whoever
touches that test should score all nine keys, not the one they are looking at,
because that is how this was found. `map_shade.py check --all` is the command.

## ~~Scan `587c15b07779` and open its 13 cross-channel disagreements~~ DONE 2026-09-07

**The trigger fired and the entry closes.** `scan --only roster` removed the
dependency on an unrelated minimap rebuild -- that is the reconciliation's one
structural win, because it decouples roster coverage from the expensive minimap
re-read the entry above still owes. 3730 stored rows reproduce the original
100/113 probe check exactly. `reticle audit` compares actual count changes over
aligned intervals: **115 agree, 9 unreadable, 6 disagree, 1 count increase**
over 131 windows. The 88%/13 figure and this one are different sampling
definitions and are not directly comparable, so the "13" never resolves as 13.

**One of the seven is diagnosed and it is a reader defect, not a killfeed
miss** -- `docs/ROSTER_FINDINGS.md`, 1483.0s. The remaining six windows are
live work, not deferred work, and live in `NOTES.md`. Nothing here is left to
un-defer.

**Historical -- tabled 2026-09-06 by the player.** `NOTES.md` has called these *the audit signal
and nobody has looked at them* since they were measured -- 100/113 probes agree
(88%), leaving 13.

Two things make it more than a scan:

* it is 31:04, and since `MINIMAP_VERSION` went to `0.3.0` every session also
  wants a minimap re-read, so this pulls in work that is itself tabled above;
* **some of the 13 may already be explained.** The 88% was measured by seeking,
  before `roster.py`'s undrawn-reads-as-zero defect was known, and on
  `c40d950031bb` that one cause accounted for ALL five misses. If it accounts
  for most of the 13 as well, the killfeed is cleaner than the figure suggests
  -- and if it does not, the residue is the real signal and worth far more.
  Either outcome is informative, which is what makes this worth doing rather
  than a chore.

Run it as `reticle scan 587c15b07779`, then `prototypes/roster_alive.py
587c15b07779 --stored`, which costs nothing once the table exists.

**Trigger: the roster's undrawn defect being fixed** -- open these against a
reader that refuses instead of guessing, or the 13 will be re-diagnosed twice.
Alternatively any session that is scanning that capture for another reason.

## The coaching milestones this file had no entry for

**Added 2026-09-07 by reconciliation.** `docs/IMPLEMENTATION_PLAN.md` executed
its first milestone and left four more in prose, with acceptance gates and no
triggers. Prose in a plan is not a backlog: the plan cannot say *what would make
this worth doing next*, because it was written before the first milestone's
results existed. These are those four, with the trigger each is actually
waiting on. The plan stays the argument; this is the queue.

The gate they all sit behind is in `NOTES.md` and is live, not deferred: the
roster split rule and the round/POV gate. Everything here is downstream of it.

* **Round-boundary reconciliation against clock, phase and scoreboard.**
  `rounds._plant` infers planting from FUTURE missing-clock runs, which cannot
  be a prediction-time feature, and score increments locate round ends late.
  111 of 543 coaching events are flagged near an uncertain boundary -- that is
  20% of the corpus, and it is the largest single quality number the first
  milestone produced. The two-score-read guard is already rejected and stays
  diagnostic: it drops two final-round outcomes.
  **Trigger: it has fired.** This is the next thing after the roster gate.

* **No-kill and no-contact episodes** -- the plan's *multiple-direction
  contact* and *multiple-route exposure*. Both need entity IDs, direction
  separation and the minimap's occluder geometry, so both are downstream of the
  minimap re-validation at the top of this file AND of ally identity.
  **Trigger: the killfeed adapter linking events to entity IDs.** Until then
  the retained no-contact denominator is the only part that can be built, and
  it can be built without them.
  **Review progress 2026-09-07:** `reticle/review.py` now retains one ordinary
  eligible-state control per round, selected independently of observed events
  and outcomes. This is a review comparison sample, not a verified no-contact
  denominator: roster/clock gating still limits coverage and controls may contain
  contact. Entity and geometry dependencies remain open.

* **Statistical progression under frozen definitions** -- economy, phase, side,
  map, agent with shrinkage; chronological rather than ingest-order evaluation;
  leave-session-out demoted to a diagnostic.
  **Trigger: enough eligible rounds that abstention stops being the result.**
  26 today from two sessions. `scan --only roster` is the cheap way to add
  them, at ~127s per session with no minimap work -- but the plan's standing
  instruction is *do not launch a broad re-scan merely to satisfy the model's
  minimum sample count*, so the gate must be validated first or the extra
  rounds inherit the defect.

* **Correction history, and rebuilding only dependent artifacts.** Every event
  needs a correction key; corrections must not silently overwrite the
  observation that was corrected.
  **Trigger: the first time a human disagrees with a stored event.** Nobody has
  reviewed `review.md` yet, so this has no evidence to store and building it now
  would be building for an imagined workflow.

**What the plan does NOT supersede, stated because a fresh plan reads as
total:** the audio channel, the corroborating-channels argument,
analysis-by-synthesis, the collective viewcone and the wiki-map promotion all
sit below in this file and are untouched by it. The plan is about one thread --
events, review and the state model. It is silent on the others, and silence is
not deprecation.

## `map_shade.stamp()` hashes RAW BYTES, so a line ending flips it

**Found 2026-09-10, after it had already lied.** `doctor` opened this session
reporting *12 geometry npz carry a STALE shade*, and every one of them was
current. `prototypes/wiki_map.py` sat in the working tree with LF endings --
23070 bytes committed against 22591 normalised -- and `stamp()` hashes
`map_shade.py` and `wiki_map.py` raw bytes, so the stamp read `bda1e17d...`
while every baked artifact carried `d22d3190...`. Reverting the stray
modification restored the match and the finding went away on its own.

So on Windows with `core.autocrlf`, merely touching either source file
invalidates twelve baked artifacts and invites a rebuild that changes nothing.
That is the opposite of what a staleness check is for.

**The fix is one line** -- hash normalised text rather than bytes:
`p.read_text(encoding="utf-8").replace("
", "
").encode()`. It is NOT
applied here because it changes the stamp value, which marks all 12 shades
stale for real and forces `prototypes/map_shade.py build --all` to rewrite
baked geometry. That rewrite is the player's call, not a side effect of a
cleanup.

**Trigger: the next deliberate shade rebuild.** Change `stamp()` in the same
pass, so one rebuild pays for both. Until then, check `git status` before
believing a SHADE finding.

## `ICON_AREA_REF` is wrong for the BIGMAP profile, and a06's paint cannot score acquisition

**Found 2026-09-10 while measuring the new acquisition channels.** Two separate
defects in the same session, and both cap what `proposal_audit.py` can say.

`ICON_AREA_REF = (10, 400)` in `prototypes/mine_icons.py` is declared in
REFERENCE px, so on `valorant-16x9-bigmap` -- the reference widget, scale 1.0 --
it caps an icon at radius 11. That widget's real icons are 20-25 px in radius:
`a06f04a0059f`'s missed residual components run 1189-1417 px. The band was
measured on something, but not on the profile it is stated in.

`a06f04a0059f`'s `ability_paint` rows mark r=7 discs on those same icons, so the
matching radius is SMALLER than the icon and a hand-clicked point need not sit
near the icon's thickest place. That is why the `core` channel scores 100.0%
recall on d95 and 45.5% on a06 -- the a06 figure may be measuring the labels.

Until both are fixed a06's acquisition numbers are a lower bound and an upper
bound on nothing, and the pool keeps `base` on that session's evidence alone.
**Trigger: the next time a single acquisition channel is to be selected.**
Re-measure the band against the bigmap widget's icons -- do not tune it against
these labels -- and repaint a06 with radii that match what is drawn. Then rerun
`proposal_audit.py --channels core` and see whether `base` still earns its
place.

## A small-widget painting, to score the length scaling

**Tabled 2026-09-06 by *I don't plan on having small widget sessions be
a concern for a while.*** Correct call — sixteen small-widget sessions are
ingested and none has been read.

The lengths in `floor_mask` now scale with the widget (`BRIDGE` 25 -> 19,
dilation 9 -> 7 at 331 px), which moves three small-widget sessions and no
large one. The direction is right and strictly conservative — it drops void and
adds nothing — but **no small-widget painting exists**, so it is unscored.

**Trigger: the first time a small-widget session is actually read.** One
`prototypes\paint_map.py 9acf02f98283` closes it, and `floor_mask_eval.py`
already scores whatever it finds with no changes.

**Related, added 2026-09-07:** the small-widget keys now exist and are scored
against the wiki art, which is a second, label-free way at the same question --
and one of them is badly wrong. See *`lotus__valorant-16x9` finds 41% of the
plant zones it should* above. A painting would say whether the rest of the
gradient (72-85% against the bigmap keys' 87%) is the mask or the art fit.

## Correct §1 of the published reconciliation plan

`docs/reconciliation-pass.html` —
https://claude.ai/code/artifact/cdb56ea7-f21d-4bdd-845c-17bc63197cdc

Its §1 concludes that the slab-only mask wins and that the two lost Ascent
blobs are a question for the player. Both were superseded within the hour: the blobs
are the bomb sites, a site is floor, and the shipped gate is the union. The
page is otherwise current.

**Trigger: any session that shares or builds on that document.** Low urgency,
zero risk — but a design doc that disagrees with the code is the exact failure
`CLAUDE.md` keeps recording, so it should not sit wrong indefinitely.

## Delete the superseded prototypes

19 of 70 files in `prototypes/` are named by no other file and no document.
The ~2,400-line 2026-08-26 enemy-teacher cluster (`enemy_teacher.py`,
`enemy_teacher_sweep.py`, `enemy_equiv_check.py`, `minimap_self_check.py`,
`minimap_anchor.py`, `minimap_portrait_official.py`) is the part that reads as
genuinely superseded rather than pending.

Nothing breaks by leaving them. The cost is that the next session reads them as
live and copies from them, which is the mechanism that produced the `floor_mask`
fork in the first place.

**Trigger: `reticle doctor`'s ORPHAN check listing them twice in a row**, i.e.
once it is clear which are pending and which are dead. `git` is the archive.

`doctor` now reports 7 rather than the 19 counted by hand -- it checks every
`.md` in the repo as well as every `.py`, which is the more honest test. Three
of the seven (`roster_alive`, `roster_scan`, `roster_names_scan`) are days old
and pending item 03, not dead.

**Re-measured 2026-09-07, and writing the answer here BROKE THE CHECK.** The
ORPHAN test skips any prototype named in any root `.md`, and this file is a root
`.md` -- so listing the dead modules in this entry took `doctor` from five
orphans to **zero**, in one commit, with no code touched. The entry's own stated
trigger is *`doctor`'s ORPHAN check listing them twice in a row*, so satisfying
the entry's format destroyed its trigger. `BACKLOG.md` is now excluded from that
check (`reticle/doctor.py`), on the argument that being on the DELETION backlog
is evidence a prototype is dead rather than alive.

**With that fixed `doctor` reports EIGHT**, not the seven on record and not the
five it briefly showed: `ability_combiner`, `glance_dynamic`, `label_enemies`,
`minimap_anchor`, `overlap_temporal`, `roster_names_scan`, `roster_scan`,
`weapon_icon_scan`. Three of those were being masked by this file all along, so
the seven was never right either.

**But note what the list still does NOT contain: five of the six enemy-teacher
modules this entry names as the genuinely-dead part.** They are named by
something else, so `doctor`'s ORPHAN check is not the trigger for deleting
*them* and never will be. `docs/IMPLEMENTATION_PLAN.md` independently concludes
"no broad rewrite or deletion of prototypes is necessary", which agrees.

**So the trigger is wrong for the item it is attached to.** Either re-aim the
entry at the eight `doctor` actually finds, or accept that the enemy-teacher
cluster needs a judgement call rather than a check. Do not let it sit as an
item whose trigger cannot fire.

## ~~One module in `reticle/` that no CLI command reaches~~ DONE 2026-09-07

`reticle refine` now reaches `refine.py` through the coaching review queue.
Selected overlapping windows share a bounded native-rate decode and the shipped
HUD reader; output remains separate evidence. `doctor` no longer reports UNWIRED.
This closes the module-placement decision, not ping-edge adjudication: the latter
still needs its detector-specific evidence before it can enter the ping reader.

**Half closed 2026-09-07.** `roster.py`'s `RosterReader` is now reached by
`cli.py` through the shared pass and `scan --only roster`; `doctor` confirms it
by no longer listing it. That was the predicted self-closing half.

`reticle/refine.py` remains imported only by `prototypes/ping_edge_eval.py`.
It was promoted before being wired, which makes "is it in `reticle/`?" stop
meaning "is it in the pipeline?".

**Trigger: none -- it needs a DECISION rather than a task.** Wire it into the
ping reader, or move it back to `prototypes/`. It has been `doctor`'s standing
UNWIRED finding for long enough that leaving it is now a choice.

## ~~`2ba870ccbd50` is tagged small-widget and was ingested as bigmap~~ ANSWERED 2026-09-07

**The tag was wrong; the ingest was right.** Found by `reticle doctor`'s
MANIFEST check on its first run, 2026-09-06, and nobody was looking for it. The
entry said it needed *one look at a frame*, and that is what settled it: against
the stored statics at every scale from 0.55 to 1.05, its own frames fit Ascent
at **scale 1.00** -- corr 0.686 and 0.691 against the two Ascent geometries,
0.071 against Split, 0.050 against Lotus. Retagged
`ability-demo brimstone map:ascent minimap:large`, asserting only what was
measured.

Two things follow. `prototypes/CLAUDE.md` reasoned about the unexplained
borrowing failure from *a different map and profile*; it is the same map and the
same profile, so a wrong crop is not a candidate explanation and that note is
corrected in place. And the npz that was quoted at it all along was a donated
copy of `a06f04a0059f`'s geometry, which said nothing about this session -- the
measurement had to come from the video. Nothing left to un-defer.

## Bake the BUY-PHASE BARRIERS into the map state, per map and side

**Named 2026-09-08 after a barrier spent 110 observations quarantined as an
unexplained ally.** The buy-phase spawn barriers are drawn in TEAM COLOUR, so
they key as ally on every map, in every round, for the whole buy phase -- and
they are static map furniture: the same doorways every round. Haven attack has
four, of varying widths: the doorway to C main, the doorway to mid/doors, the
doorway to "true mid", and the widest at the entrance to A site.

Measured anchors on `96aa1ae9b96f` (331 px widget), from components keyed in
>= 30% of 29 samples across 222-250 s:

    C main               ( 82, 230)     mid / doors     (138, 233)
    "true mid"           (177, 226)     A entrance    (185-209, 231)

**Those are anchors, not extents** -- the ally key catches part of each bar, so
the detector must measure the bar on its own colour. And the set is per map AND
per side: this is the ATTACK set.

Two things it buys, and the player has raised both. A keyed blob at a barrier
anchor during the buy phase stops being an unexplained appearance, which
removes a phantom class from every map rather than one window. And a barrier is
a PHASE LANDMARK -- a known position at a known phase -- so it is a free
per-round check that the stored geometry is still aligned.

**Note this class was never unknown.** `minimap.py` 734-739 has listed the buy
phase's teal spawn barriers as a confirmed false-positive class since it was
written, alongside the death X marks and scenery through the semi-transparent
widget. What is missing is the map state, not the identification.

**Trigger: the next map-state pass.** It belongs with the geometry npz, keyed
`<map>__<profile>` like everything else, not per session.

## A RECON DART PULSE is a legal origin for an enemy appearance

**Named 2026-09-08, from the circle that was producing phantom allies.** The
scan radius is drawn in team colour and the ally key catches its arc, which the
ring fit turns into a legal icon -- but the useful half is that
`LEGAL_ORIGINS["enemy"]` already lists `reveal`, and a dart pulse is exactly
one. An enemy icon appearing at a pulse is an EXPLAINED origin.

Three properties decide the model and none of them is the drawn circle:

* **two pulses per dart**, so it is two discrete reveal events, not a window;
* **it reveals only what the pulse can SEE from the dart** at that instant --
  a line-of-sight computation from the dart's position, which `cone.raycast`
  over the passable/box geometry already does. The circle is the bound;
* **the dart has variable verticality**, sticking to walls and ceilings, so the
  circle is a projection of a scan originating off the floor plane. **The drawn
  radius is not ground coverage** and must not be used as the revealed set.

**Trigger: the enemy channel needing an origin for a reveal.** Until then the
circle's arc is a known phantom source; do not try to reject it on shape --
elongation is 7.12 median against 2.18 for real icons but 31% of real icons
also clear 3.0, which is the aspect-ratio trap this repo already paid for.

## Record which agent the player played, per session

**The binding input for the identity-conditional tracker, and it is not in the
store.** None of the five sessions with an `l1/minimap` table records the agent
-- tags carry map, outline colour, widget size and chroma, and nothing else.

Without it the model cannot be applied to real data. `jump_census.py` can say
that 54.7% of the observations `filter_track` drops are at teleport distance,
and it cannot say whether a single one of them is a real teleport, because that
depends entirely on whether the player was playing one of Omen, Chamber, Veto,
Waylay or Yoru.

Two ways in, and they are complementary rather than alternatives:

* **a tag at ingest.** Costs the player one word per capture and is exact;
* **derive it.** `minimap_portrait.bootstrap` already names the ENEMY lineup
  from scoreboard art by composition matching (83.5% held-out, five agents).
  The same machinery pointed at the ally side names the, with no new
  labelling -- and the roster gives a per-frame alive check on it for free.

**Trigger: the next capture, for the tag; the next time the ally roster is
read, for the derivation.** Neither blocks the other.

## Measure a dash, or drop `walker_dash`

`track.DASH_PX_S` is a bound and `jump_census.py` showed it cannot become a
measurement from data in hand: above the walk ceiling the speed distribution is
a smooth decay -- 40.7% of refused steps in 45-60 px/s, 75.2% within 2x the
ceiling -- with no bump anywhere a dash could be. At 4x the class absorbed
90.5% of all refusals, which is a bound explaining everything.

**Trigger: one session where a dash agent (Jett, Neon, Waylay) was played and
tagged.** If the distribution still shows no mode there, `walker_dash` is not a
class this channel can carry and should be deleted rather than kept as a
plausible-looking bucket.

## ~~Make `filter_track` identity-conditional~~ DONE 2026-09-06

**Shipped: `filter_track(..., motion=None)`.** `None` keeps the fixed
`RUN_PX x 1.6` gate, and the default path is proven byte-identical against the
pre-change module on all five sessions with an `l1/minimap` table (93,553
points). Pass a `track.CLASSES` key and the gate becomes `track.admits`. A
teleport is kept **and never interpolated across** -- it is a legal
discontinuity, so drawing a path through it would invent the route, which is
the fault the widget-absent hole break already exists to prevent. Seven
self-tests in `reticle/track.py --self-test`.

**`jump_census.py --motion` says what opting in would do**, and it is not what
this entry predicted:

    observations kept        default    walker   walker_dash   walker_teleport
    pooled (102,765 obs)      88.7%      81.9%      95.0%           89.5%
                                        -6,987     +6,508           +835

The entry reasoned from "54.7% of the 11,599 dropped observations sit at
teleport distance" that a teleporting class would recover most of them. **Net,
it recovers 835**, and three of the five sessions LOSE points. The reason is
that `admits` is two changes at once: it adds the teleport branch and it
removes the 1.6x slack, which was never a law -- against a strict `walker` the
teleport branch is worth +7,822, and the lost slack costs -6,987 of that.

**So the fixed gate's slack was doing the work a motion class is supposed to
do**, badly and for every agent at once. Read the deltas as a cascade, not as
event counts: a refusal re-anchors the comparison to the last kept point.

Nothing opts in yet, and nothing should until a caller knows the agent --
which `self_agent.py` still cannot supply at 38%. The next caller is the entry
below: a cast is evidence for the class on a WINDOW, which is a better source
than a per-session guess.

## Superseded discussion of `filter_track`, kept for the argument

**The correction the tracking work identified, tabled 2026-09-06 by the player.**
`reticle/minimap.filter_track` rejects any step above `RUN_PX x 1.6` (72 px/s)
as physically impossible. That is a fixed threshold standing in for a law that
is actually per-identity, and it has three consequences, all measured in
`prototypes/jump_census.py` over 102,239 steps on five sessions:

* **it cannot tell a teleport from a phantom.** Of the 11,599 observations it
  drops, **54.7% (6,341) sit at teleport distance** from the last kept point.
  That is a ceiling rather than a count -- 5.7% of refused steps are at
  physically impossible speeds, so most are certainly misdetections -- but a
  fixed gate genuinely cannot separate them, and for Omen, Chamber, Veto,
  Waylay or Yoru the real ones are being destroyed silently;
* **the quality figure it feeds conflates three things.** `prototypes/CLAUDE.md`
  quotes jumps > 60 px/s at 5.0% / 3.3% / 3.8% as the residual error rate, and
  says elsewhere that it mixes tracking error, teleports and dashes. Only the
  first is a defect;
* **a refusal is a hard break**, so a destroyed teleport does not merely lose
  one point -- it ends the run and starts a new one, which is exactly the
  identity discontinuity ally tracking is meant to avoid.

The shape of the fix is already written: `reticle/track.admits` takes a motion
class and answers whether a step is legal for it, with the reason. `filter_track`
should take a class rather than assume `walker`, defaulting to today's
behaviour so nothing moves until a caller opts in.

**Trigger: an agent is known for a session** -- see the entry above, and the
`self_agent` work that derives it. Until then there is no class to pass, and
changing the gate would only swap one assumption for another.

**Do NOT** re-baseline the position track on the new gate before
`xmark_eval` has been re-run: this moves every stored minimap number and the
re-validation is itself tabled at the top of this file.

## ~~Fit a CIRCLE to the self ring, not a bounding box~~ DONE, FALSIFIED

**Run 2026-09-06 and it does not work.** The suspect was that the facing
triangle drags the crop off-centre in a rotating direction, and that
`fit_ring` -- which solved that teardrop for enemy icons -- would lift the
number. Three geometries on the same corpus:

    --geom bbox   the component bounding box (the 38% baseline)   10/26
    --geom ring   fit_ring, the enemy machinery unchanged          9/26
    --geom pin    fit_ring scored coverage MINUS interior          9/26

The full argument is in `self_agent.py`'s docstring. Two facts about the self
glyph came out of it that were not known before -- the old text was reasoning
from the enemy icon's shape rather than from this one:

* **the key survives only over the LOWER HALF of the rim** -- present on 61-67%
  of bearings 150-240 deg and **22-23% at 330-30**, over five sessions. A
  dropout fixed in SCREEN space, not one that rotates with facing;
* **there is no hole to find: 0 in 347 frames over six sessions.** A closed rim
  would hand over the portrait as the largest hole in the key, with no fitting
  at all. It is not closed. Do not re-try it.

**The descriptor was tried the same day (`--desc ncc`) and the crossing
re-reads this entry:**

                        --geom bbox        --geom pin
        --desc hist       10/26  38%         9/26  35%
        --desc ncc         0/26   0%         8/26  31%

Under the histogram the geometry is worth -1; under NCC it is worth **+8, from
below chance to 31%**. A histogram is alignment-blind, so it could not see a
better centre. **The fitted ring was measured with an instrument that could not
detect it**, and the falsification above is narrower than it reads: the crop is
not what caps the HISTOGRAM at ten. The wash hypothesis is confirmed on its own
terms -- `chamber -> sova` becomes `chamber -> chamber` under NCC.

**Neither descriptor is the answer and they are COMPLEMENTARY**: they agree on
4 of 26, and the union of what they get right is **13/26 (50%)** against 38%
for the better one alone. That is the reason not to keep picking descriptors --
see the analysis-by-synthesis entry, which now names this as its first
instance. **38% is still the number to beat.**

`fit_ring` gained a per-call radius range in the same commit, defaulting to the
measured `R_MIN/R_MAX`, because the icon radius is a widget-size constant: a
331 px widget wants 6-9 where the enlarged one wants 8-13.

## ~~Combine the detection channels: a CAST licenses a jump~~ BUILT + MEASURED 2026-09-06

**`prototypes/cast_motion.py`**, and it found the reason the whole chain has
been underperforming. `filter_track` now also takes SPAN-conditional motion --
`[(t0_ms, t1_ms, class), ...]`, the class inside each span and the default gate
outside -- which is the mechanism this entry asked for.

**The class map is DERIVED from `ability_reference`'s `functions` field**, not
hand-listed: `Teleport` -> `walker_teleport` (5 abilities), `Dash` ->
`walker_dash` (5). It disagrees with `track.py`'s prose note twice -- Waylay E
is `Invulnerability Mobility` (a fast travel, not a discontinuity) and Raze Q
is missing from the dash note. **`Displacement` was in the map for one run and
was a real defect**: it describes what an ability does to ANYONE, so it
licensed jumps for Astra, Breach, Deadlock and Miks, four ultimates that move
enemies and leave the caster still.

**THE MEASUREMENT, and it invalidates a constant.** `--steps` gives the largest
step in the 3 s after each teleport cast, agent from the ingest tag:

    yoru GATECRASH 4.6 / 6.3 px | omen Shrouded Step 38.5 / 40.1
    veto Crosscut 65.0 / 6.8    | chamber Rendezvous 323.8
    median 38.5 px, 1 of 8 reaching TELEPORT_PX

`track.TELEPORT_PX` is 200 px and its own comment admits what it is -- a bound
on the impossible, not a measurement. At 15 Hz `admits` allows a walker 3.0 px,
so **`walker_teleport` REFUSES three of the four real teleports it exists to
admit** ("too far to walk, too near to be a teleport"). The default gate
refuses them too. Every short teleport lives in that dead zone, and that is
also why item 1's session-wide `walker_teleport` was only +835: the teleport
branch almost never fires on a real teleport.

**RESOLVED 2026-09-08, and not by re-measuring the constant.** The entry above
said `TELEPORT_PX` wants re-measuring and that n=8 is not enough to refit it
on. That was right about the n and wrong about the target: **no value of a
distance threshold separates a teleport from a phantom**, because the real
teleports are 4.6-65 px and 54.7% of the steps `filter_track` refuses sit at
"teleport distance" too (`jump_census.py`). The two populations overlap, so the
axis is wrong rather than the number on it.

So distance is no longer asked. `track.Corroboration` and
`corroborates_teleport` license a discontinuity from OTHER CHANNELS -- the icon
and the viewcone both relocated, tied to a predecessor entity by audio or an
observed destination -- and `admits(..., evidence=)` then admits any distance
above the walk ceiling. `TELEPORT_PX` stays as the fallback for a caller with
no event channel and reports `TELEPORT_ASSUMED` for everything it admits, so
what rests on it is countable. `filter_track` takes the evidence per span:
`[(t0_ms, t1_ms, class, corroboration), ...]`.

The two limits the run established are unaffected and still stand: a two-part
teleport (Yoru, Chamber, Waylay) drops on PLACEMENT and jumps on traversal, so
no fixed window catches it in general; and slot X still draws pips, so
ultimates need the audio half.

**What this still needs is the event stream, not the rule.** One corroborated
event exists -- the player-reviewed Lotus Omen relocation -- and it was
assembled by hand. A cast on the tray plus a relocated cone is derivable
today; the audio half and the destination link are not. Until they are, the
corroborated path fires only where a human supplied the event.

## Superseded discussion of the cast/jump combination

**Recorded 2026-09-06, and the player notes the player has raised it before:** *a teleport
activated on the hotbar (or in audio once that's built) should be triggering an
expected agent teleport.* `NOTES.md` has carried "causal -- what is on screen
is CAUSED by events the pipeline already tracks" as a goal; this is the first
concrete, cheap instance of it, and it is the RIGHT fix for the
`filter_track` problem above rather than a parallel one.

**It inverts the dependency, which is what makes it better than the identity
prior alone.** Knowing the agent tells you a jump *may* be legal. Knowing a
cast happened at time t tells you a jump *is expected* at time t. So the two
channels become each other's control:

    cast at t AND jump at t     corroboration -- a real teleport, keep it
    jump at t, no cast          a phantom, and filter_track was right
    cast at t, no jump          the ability was not a teleport, or the track
                                lost the player through it -- itself a finding

**Every piece exists.** `ability_hud.py` reads the tray and its drops came out
clean on 7 of 7 demo clips with slot identity (C/Q/E) and in the recorded cast
order; `ability_reference` carries the agent-to-ability mapping, so slot plus
agent names the ability; `l1/minimap` carries the positions. Nothing new needs
detecting.

Two known limits, both already recorded elsewhere and neither fatal:

* **slot X never drops** -- the tray draws the ultimate as pips rather than a
  bar -- so Omen's ultimate and any other X-slot teleport is invisible to this
  channel. That is exactly the quarter the ultimate-voiceline matched filter
  was scoped to cover, which is why the player names audio in the same breath;
* **the tray is a level, not a charge count, for Viper**, and `infinite-
  abilities` pins it full on five demo clips. Neither affects teleports.

**Trigger: MET on 2026-09-06.** `track.admits` (done) -> `filter_track` takes a
class (done) -> cast events select it. **This is next**, and the measurement
above sharpens why it is better than a per-session agent: opting a whole
session in to `walker_teleport` is net +835 observations and NEGATIVE on three
of five sessions, because a class applied to the whole session also gives up
the slack everywhere. A cast selects the class **on a window**, which is the
only version of this that spends the permissiveness where the evidence is.

## Promote the WIKI MAP into `minimap_geometry`, which still bakes its own

**Recorded 2026-09-06, catching me reaching for the derived path on a fresh
clip:** *why are we still baking the map? I thought we were using the minimap
wiki reference which is higher accuracy anyway?*

**The player is right, and it is a promotion gap rather than an open question.**
`prototypes/wiki_map.py` is built and validated -- the official art's ALPHA
CHANNEL is an exact floor mask, fitted by a similarity transform whose rotation
lands on an exact multiple of 90:

    map      IoU vs the painting    derived rule scores
    Ascent           92.7%                     91.3%
    Lotus            93.7%                     92.8%

Six maps' art is fetched. **But `minimap_geometry.py` -- which writes the npz
that every other minimap module loads -- contains not one reference to it.**
The only consumer is `minimap_dynamic.searchable_from_art`, and its own
docstring calls itself *"an upgrade path, not a hard dependency"*. So the
artefact the pipeline actually runs on is still fully derived, and the better
source sits beside it unused. Only 2 sessions have a stored fit.

**What must NOT be collapsed while doing it**, and it is already written in
`prototypes/CLAUDE.md`: the static map does TWO jobs. **Geometry** -- floor,
walls, holes, bomb sites -- should come from the art. **Photometry** -- what a
pixel LOOKS LIKE in this capture, `static`/`lo_gray`/`hi_gray`/`sd_lo`/`sd_hi`
-- cannot come from a clean external render at any quality, because the widget
is semi-transparent over live world and the whole point is to difference
against the actual values in these pixels. So the npz keeps its capture median
and swaps only its labels.

**Trigger: the next time a session's geometry is built.** It also retires the
standing `doctor` ERROR that 35 of 36 npz are stale, since the labels would
stop depending on `classify()` at all.

**Interim, done 2026-09-07 and it is most of the way there.**
`prototypes/map_shade.py` warps the art into every session's widget pixels and
writes six terrain classes ADDITIVELY -- `shade`, `shade_kind`, `shade_step`,
`shade_purity`, `shade_fit`, `shade_map`, `shade_built_by` in **35 of 36 npz**.
So the art's geometry is now IN the artefact every minimap module loads; what
remains is for a consumer to prefer it over `labels`, which is the
re-validation job this entry describes.

**Two corrections to what this entry used to say.** *"Only 2 sessions have a
stored fit"* -- all 35 do now, and the fit is a per-(map, profile) constant to
within the refine search's own step, so it costs about 2 s per distinct static
and there are only SIX distinct statics in the store. And the interim note
recorded `b9558488a607` at **IoU 95.1%, rot 270, scale 0.2264**: no such file
was ever in `reference/fits/`, and that session recomputes at IoU 94.6%, scale
0.2246 -- identical to the other 28, because they all share one `static`. The
figure was never checkable; write the path next time, not just the number.

## THE COLLECTIVE TEAM VIEWCONE -- BUILT 2026-09-06

**DONE, and the entry is kept because its argument still ranks what comes
next.** `reticle/cone.py` (the raycast, vectorised), `minimap.ally_icons` (a
blob is an icon when it has coverage, a non-key interior AND a facing lobe),
`track.Tracker` (Hungarian identity, since all four allies share one teal), and
`overlay.py`'s minimap layer. Scored against the roster: raw ally blobs carry a
**+0.99** residual -- one phantom teammate per frame -- and the promoted icons
carry **-0.15**, 20 of 24 rounds agreeing, 95% CI [64%, 93%].

**SUPERSEDED IN PART, same day:** how the area is COMPUTED is now in
question. Terrain shade reads as illumination at 3x, the audio ring is baked
into the static reference, and the reconstruction over-claims ~3x against the
area the game itself draws. The widget has to be solved as LAYERS -- see
`prototypes/CLAUDE.md` "THE WIDGET IS LAYERS" and `cone_terrain.py`. The entry
below still ranks the work correctly; only the method changed.

What is NOT done, in the order this entry's own argument puts it:

* **the interior-appearance invariant is not wired to anything.** The area
  exists; nothing consumes it yet. That is the free precision gain below;
* **a bearing cannot be carried across a bad frame at 500 ms** (p90 163 degrees
  against a null of 160), so the area has holes where a lobe fit refused.
  Unmeasured at the 15 Hz the shipped reader runs at, and that is the first
  thing to run;
* **third cones are still unread** -- a turret placement preview is drawn by
  the local player and is cone-shaped.

The original entry follows unchanged.

## The argument, as written before it was built (2026-09-06)

**The observable area: the union of what the team can currently see.** Agreed as
the highest-value next piece, and the reason is structural rather than a ranking
of detectors: **four of the entity model's §11 invariants are written in terms
of it, and until it exists they are prose.**

The one that pays first, and it is cheap: **an enemy cannot originate in the
INTERIOR of the observable area.** An enemy appearing mid-cone in a single frame
is suspect, and the discard is CERTAIN in two of four cases:

    non-teleport agent                          DISCARD, certain
    teleport agent, in audio radius, no sound    DISCARD, certain
    teleport agent, in audio radius, sound       KEEP -- corroborated
    teleport agent, outside audio radius         UNDECIDED, retain flagged

A free precision gain over a channel whose precision has been the binding
constraint all along, and it needs no new label. **The audio channel closes the
teleport exception inside the audio radius**, so this is the first hard
cross-channel dependency in the model. Above the table sits a per-match
shortcut: the enemy lineup is readable from the scoreboard, so if no enemy is
one of the five teleport agents, every interior appearance is discardable with
no identity read at all.

**What exists, and what does not:**

    self cone      `minimap_cone.self_cone()` -- fitted, raycast, ~89-92% of
                   frames answer, magnitude validated against camera pan
    ally cones     NOTHING. Ally rings are per-frame candidates with no
                   identity, and no cone is fitted to any of them
    third cones    a turret's placement preview is a cone, is currently a
                   false-positive class, and is drawn by the local player

**It must be the RAYCAST cone, not the angular wedge.** An enemy stepping out
from behind an occluder is a legitimate interior appearance, and a wedge cannot
represent that -- so a wedge would make the invariant fire constantly and it
would rightly be abandoned. `minimap_cone` already raycasts and already splits
into fingers through a doorway, which is the behaviour this needs.

**Three legitimate violations of the interior invariant, all checkable:**

* **a teleport** -- legal for Omen, Chamber, Veto, Waylay, Yoru only, and the
  ENEMY LINEUP IS READABLE from the scoreboard, so the exception set is known
  per match rather than assumed;
* **a reveal** -- Sova, Fade and others paint an enemy the team cannot see;
* **an occluder** -- handled by the raycast, per above.

**Build it to UNDER-CLAIM.** An observable area that is too large turns
legitimate appearances into discarded reads, which is a silent recall loss of
the kind this project keeps paying for. The one ground truth available is the
local player's own cone.

**Trigger: next. It is also what `self_cone`'s parked hypotheses need** -- the
cone-termination and local-thinness ideas were shelved on a 4-of-50 yield figure
later corrected to ~89%, and both want more cone instances than one player
supplies.

## CORROBORATING CHANNELS: motion predicts sound, and sound indexes the video

**Recorded 2026-09-06: :** *player icons moving at running speed should be making
footstep sounds. The self player icon with the audio radius around same thing
(it takes a bit to leave after making no noise but roughly). Basically just
using corroborating signals as we have been to increase accuracy and
potentially also efficiency/search density.*

**Two distinct claims. The second is the more valuable and is untested; the
first was tested the same day and comes back PARTIAL.**

### Claim 1: running implies footsteps. Measured, 2 of 3 clips confirm.

Self-track speed against audio RMS, with every ability window excluded -- the
measured sound-event span aligned to a tray cast, not a fixed guard. A first
attempt used a 3 s guard and leaked the 4.4 s ult into the still class.

    session        class   n    median rms   silent
    e78e75b2d191   still  115      0.85      75.7%
      (omen)       walk   134      2.36      33.6%
                   run     67      2.95      16.4%
    ccff4a11ff5a   still  149     10.11      43.0%
      (chamber)    walk   348      9.84       4.9%
                   run    124     11.58       0.8%
    b9558488a607   still  662      1.86      52.4%     <- INVERTED
      (omen, new)  walk   168      0.69      76.8%
                   run     56      0.46      80.4%

On the two older clips the effect is strong and monotonic in the predicted
direction -- silence falls from 76% to 16% and from 43% to 1% as the track
speeds up. **On the new spaced clip it inverts**, and the likeliest reason is
already recorded in `prototypes/CLAUDE.md`: **only RUNNING makes noise; walking
and crouching draw nothing**. That clip's protocol had the player holding position
and repositioning gently, so its "run" class (n=56) is probably teleport steps
and tracker jitter rather than running. A hypothesis, not a finding.

**Two statistics that found NOTHING on a full match** (`c40d950031bb`, 16 min),
recorded so they are not retried as stated:

* **broadband RMS: run/still ratio 1.04x.** A real match is saturated with
  gunfire, abilities and teammates; the player's own footsteps are nowhere near
  the loudest thing in it;
* **step-rate cadence -- the share of envelope power at 1.5-4.5 Hz in a
  150-1200 Hz band: 0.92x**, slightly the WRONG way. Periodicity looked like the
  obvious rescue for energy failing, and it is not one at that band and window.

**THE ARBITER ALREADY EXISTS AND IS BETTER THAN EITHER: THE AUDIO RING.** The
game draws it only while running -- binary, measured at radius 94-95 px, with
every non-running frame scoring exactly 0.00 lift. So the right experiment is
not speed-vs-audio at all; it is **ring-vs-speed-vs-audio**, where the ring is
ground truth for "is the player audible" drawn on screen by the game itself. That also
settles the walk/run ambiguity that probably explains the inverted clip, and it
needs no labels. the parenthetical -- *it takes a bit to leave after making
no noise* -- is a lag to calibrate, not an obstacle.

### Claim 2: audio as a cheap INDEX over the video. Untested, and the bigger win.

**Decoding audio is orders of magnitude cheaper than decoding frames.** A whole
match's audio loads in seconds where `cmd_scan` at 15 Hz is minutes, and
`CLAUDE.md`'s cost rule already says a cheap pass should decide where the
expensive pass looks. Audio is the cheapest full-coverage pass available and
nothing uses it that way.

**The standing caution applies and must not be skipped:** *gate on OPPORTUNITY,
not on outcome.* `CLAUDE.md`'s sampling section records why -- gating dense
sampling on kills would make the model only ever see duels that drew a killfeed
entry.

**But the specific blind spot I named for it does not exist. the player,
2026-09-06:** *I don't believe there are silent abilities at all, only abilities
out of audio range.* I had written that "a silent ability is exactly the class
an audio gate would miss, and that class is known to be large" -- **conflating
two different classes**. What is known to be large is the set of abilities with
NO MINIMAP ICON (the note: *grenades, flashes, molotovs are the most
common*). That is a fact about the widget, not about sound, and I carried it
across without noticing.

**The consequence is large and it favours audio over the minimap.** If every
ability makes a sound, the audio channel has FULL coverage of the ability class
where the minimap structurally does not, and the failure mode is ATTENUATION --
a continuous, distance-dependent quantity -- rather than absence. Attenuation is
modellable and absence is not.

**And for the LOCAL PLAYER it is not a failure mode at all**: the casts are
never out of range. So an audio index over the player's own abilities has no
silent-class blind spot whatsoever, which is exactly the half of the event log
the tray and the submenu also cover. The out-of-range caveat applies only to
other players, where it becomes a RANGE ESTIMATE rather than a miss.

**Trigger: after the reference cuts exist.** An index needs something to index
ON, and a matched filter against the cut references is that. Until then a gate
would be an energy threshold, which is what `audio_probe` already killed.

## THE AUDIO CHANNEL: build it next, and it splits into two unequal halves

**Recorded 2026-09-06: :** *Teleports can be very short range or even faked though,
so this may simply require the audio channel. I think we build that next. Is
ability audio recoverable from the agent clips or do I need to do no sound but
the ability clips?*

Measured rather than guessed, 2026-09-06. **The answer is that the question
splits, and the two halves have opposite dependencies.**

### Half one: ULTIMATES. Reference audio already exists. Record nothing.

`reference/assets/voicelines` holds **56 mp3s -- 28 agents x ally AND enemy
variants** -- and all 56 decode: 52 at 48 kHz mono (the capture's own rate),
4 at 44.1 kHz stereo, 0.77-3.98 s, median 1.63 s. Long, loud, spectrally
distinctive, one per agent per side: the ideal matched-filter target, and a
closed set of the same shape as the digit templates and the agent-name bitmaps,
both of which worked.

**CORRECTED, by Recorded 2026-09-06: : the tray DOES read slot X.** This entry
first said *"slot X draws pips, not a bar, so `ability_hud` sees no drop for an
ultimate in 7 of 7 clips"* -- which is `prototypes/CLAUDE.md`'s note from
before the **2026-09-05 fix**, and `ability_hud.casts`'s own docstring already
records the correction: the pips DESATURATE from teal to grey along with the
bar, so the existing teal mask reads them with no new geometry. Measured then
on `02cf738b1c8f`: slot X goes 909 raw teal px -> 0 between 28.0 s and 28.5 s.
`cast_motion.py --steps` also read Omen's From the Shadows off slot X the same
day this entry was written, in the run printed above it. **Censused over all 27
demo clips: 22 of 27 carry at least one slot-X drop, 25 drops in total** --
C 31, Q 31, E 32, X 25. So slot X is read about as often as any other slot, and
the five clips without one are the "not observable in every clip" case the
docstring already describes, not a reader that cannot see pips. **A stale claim
repeated from an index that a docstring had already superseded** -- the exact
failure mode `CLAUDE.md` warns about for this file.

So audio is not the ONLY route to an ultimate. It is still worth building
first, for reasons that survive the correction: the voiceline references
already exist and cost nothing, the ultimate is the highest-stakes event in a
round, and the tray's ult read is explicitly *not observable in every clip*
(`6bb88dba5d2c` and `2ba870ccbd50` keep a full X bar through a labelled ult).
Two independent readings of the same event is the point.

**A REFINEMENT FROM THE DOMAIN NOTES, directly implementable from stored data:** the
ult fill *"might need to be divided by the number of pips in the ult, which is
a known quantity per-agent"*. It is -- `ability_reference` carries it as the
ultimate's `cost` field, **7, 8 or 9 points, present on 28 of 29 agents**
(Astra's row is malformed and needs a look). `fills()` normalises each slot by
the p90 of its own non-trivial samples, so a partial charge reads as a
fractional bar and `CAST_DROP` is being asked to separate "gained a point" from
"spent the whole ult" without knowing the quantum. Dividing by the pip count
makes one pip a known step: a drop of 1/N is a point being spent or the meter
ticking, a drop from full to zero is a CAST. That should raise precision on
slot X and make a partial-charge drop refusable rather than a threshold call.

**A false positive of exactly that kind is already in the census**: Sage
(cost 7) shows two slot-X drops, `0.98 -> 0.00` and **`1.03 -> 0.78`**. The
first is a cast; the second is a quarter-bar step that cleared `CAST_DROP` and
should not have. That is the case the divisor rejects.

**Reading the pip count off the PIXELS was probed and is INCONCLUSIVE -- do not
retry it as stated.** The pips are visible: a row of evenly spaced teal marks
at **y = 1037, pitch 8.0 px** on every agent tried. But the count per frame is
unstable (Yoru 0-8 across ten frames, Chamber 0-11) and its mode does not equal
`cost - 1` on any of eight agents, so the "N segments have N-1 dividers"
reading is not supported. **The pitch is the surprise**: it is 8.0-8.2 px
regardless of whether the agent costs 7, 8 or 9, so the segment width is fixed
and the BAR WIDTH must vary with the pip count -- which is a different and
probably easier measurement than counting marks, and it is untested. None of
this blocks the divisor, because `ability_reference.cost` already supplies the
number for 28 of 29 agents; the pixels would only be a cross-check.

**Astra's ultimate row is malformed in the reference** (`Astral Form / Cosmic
Divide`, cost None) and is the one agent the divisor cannot be applied to
without a fix.

### Half two: BASIC ABILITIES. No reference exists anywhere, so it must be cut.

Riot publishes icons and voicelines, not SFX: the store's ability assets are
**118 PNGs and zero audio files**. So a C/Q/E reference has to be cut from
footage at a known cast time -- which is what `audio_probe.py` concluded a
fortnight ago, and the tray it named as the cast-time source now exists.

**Re-run with the better anchor, and the anchor helps.** `audio_probe`'s null
used minimap-track first observations, which lag the cast and fragment. Tray
drops are the activation itself. Flux percentile rank at +/-0.05 s, marks
against 2000 random times from the same clip:

    omen     0.994 / 0.918      chamber  0.985 / 0.940
    yoru     0.984 / 0.924      veto     0.989 / 0.927

Marks sit above the null on all four clips, where the minimap-timed marks sat
ON it. **But the null is already 0.92-0.94**, so the clips remain saturated
with onsets and this is a direction, not a detector -- consistent with
`audio_probe`'s original verdict that onset cannot be the supervisor here.

**LOOKING settles what the flux number cannot.** A spectrogram sheet of the six
Omen casts against controls shows the casts at 19.9 s, 25.7 s and 29.2 s as an
unmistakable broadband state change at the mark -- quiet before, bright and
full-band after. **The sound is plainly there; it is SUSTAINED rather than
transient**, which is precisely why a flux/onset statistic misses it and a
matched filter or NMF activation would not.

### So: what the player should record, and it is NOT "no sound but the ability"

**That version is impossible and unnecessary.** Map ambience is always present,
and HRTF is on -- `audio_probe` already records that the reference should be
cut from footage recorded the way the player actually plays, so the clips are the
RIGHT source rather than a compromised one.

**The contaminant is the footsteps -- but HOW MUCH is NOT ESTABLISHED, and
the first attempt to measure it was my own aggregate error.** Over 27 demo
clips and 119 casts, asking whether the self track says the player was still in the
+/-0.5 s around each cast:

    still by MAX speed over the window       8/119   ( 7%)
    still by MEDIAN speed over the window   28/41    (68%)   (8-clip subset)

**A sevenfold swing from the choice of aggregate, which means the proxy does
not answer the question.** A max over fifteen frames is tripped by one jittery
ring fit, so it reads "moving" on a stationary player; a median passes a window
the player moved through briefly. This is `self_icon_dist`'s min-versus-median lesson
arriving again in a new file -- *once a whole window is sampled, the aggregate
IS the measurement* -- and the 7% figure should not be quoted.

What IS established: clip median speeds run 4.7-18.8 px/s, so these clips do
contain a lot of movement, and the Omen clip's ultimate at 29.2 s was cast
standing still on both statistics. **The direct test is the audio, not the
track** -- are footsteps audible in the cast window -- and that is a question
for the reference cut itself rather than a proxy.

So the ask is a light protocol change, not a new kind of clip:

* **stand still while casting** -- removes the dominant contaminant;
* **pause ~3 s between casts** -- gives a clean baseline immediately BEFORE
  each cast, which is what makes a residual calibrated rather than thresholded,
  and stops two abilities' sounds overlapping;
* **keep casting every ability, in order**, exactly as now -- that protocol is
  already what makes absence informative.

Everything else about the existing corpus is right, and the clips already
recorded stay usable as test data even where they are not usable as reference.

### Two things to carry into the build

* **`prototypes/passes.py`, not another decode.** CLAUDE.md's rule that a new
  reader joins the PASS was written for `ping_scan.py` taking a video path.
  Audio is a second stream of the same file and the same argument applies;
* **Yoru's fake teleport is the reason this is not optional** -- see
  `prototypes/CLAUDE.md`. Faking plays the sound without the displacement, so
  sound and position answer different halves of one question, and no amount of
  minimap work substitutes.

## Analysis-by-synthesis: hypothesise an event, render it, fit the residual

**Recorded 2026-09-06, closing the session:** *for audio, especially for
overlapping audio, a technique that I'm not sure exists could be -> guess an
event -> try to fit the sound that event would make into the audio. I think
this could also be used for icons, and is sort of a part of what I meant by
causal model.*

**It exists, it is old, and half of it is already written in this repo.** The
general name is ANALYSIS-BY-SYNTHESIS -- a generative forward model plus
residual scoring, dating to 1960s speech coding and the same idea as "vision as
inverse graphics". The entity model's §5 states it for icons already:

> Draw what should be there, subtract, and the residual is either an unmodelled
> entity or an error. Detection and validation from one mechanism, which is the
> same move that made the two-state background work.

the contribution is the generalisation: the SAME operation serves audio and
icons, and the entity model is the forward model both share. That is what turns
the model from a notation into something that does work.

**For overlapping audio the specific tool is NMF with a FIXED dictionary.**
Decompose the observed spectrogram as a non-negative combination of known
source templates, solving only for the activations. Overlap is what it is
built for, where a matched filter degrades exactly there --
`prototypes/audio_probe.py` already killed onset detection and concluded a
matched filter needs a reference cut at a known cast time.

**What is already in place, which is more than expected:**

    56 voiceline mp3s      reference/assets/voicelines, ALLY and ENEMY variants
    118 ability icons      reference/assets/abilities
    29 minimap portraits   reference/assets/agents
    sd_lo / sd_hi          per-pixel, PER-STATE noise, in every geometry npz
    tray cast times        ability_hud, clean on 7 of 7 demo clips with slot

`sd_lo`/`sd_hi` is the piece that makes this more than a threshold: a residual
needs a noise model to say what counts as small, and Phase 0b built exactly
that -- within-state SD sitting in a narrow 3.2-6.4 band across the searchable
area, against an overall SD 5-8x larger that would suppress the signal hardest
where the signal is.

**Three honest caveats, none fatal:**

* **Valorant audio is SPATIALISED** -- HRTF, distance attenuation, occlusion
  filtering -- so one event does not produce one waveform, and a fixed
  dictionary is wrong for anything distant. **The local player's OWN casts are
  the clean case**: near-field, consistent, and exactly the events the tray
  timestamps. Start there and treat other players' audio as a later problem;
* **the hypothesis space is combinatorial.** Guess-and-fit needs the guesses
  pruned, which is precisely what the causal constraints are for -- the roster's
  alive counts bound how many entities can exist, the killfeed predicts X-mark
  counts, an ability implies a living caster, charges bound casts. This is why
  it belongs AFTER those, not instead of them;
* **a bad forward model produces confident wrong fits**, which is this repo's
  signature failure in a new costume. The discipline that answers it is the one
  already in use: score against something the model did not fit, and refuse
  rather than guess.

**THE FIRST INSTANCE IS `self_agent`, and it is smaller than the trigger below.**
Added 2026-09-06 after the descriptor crossing, which is what named it. Two
descriptors that fail on DISJOINT agents, each discarding most of the glyph --
the histogram throws away position, NCC throws away level, and both mask the
ring and the tail out as nuisance -- is the signature of the wrong question.
The forward model asks the right one:

    hypothesise agent X -> DRAW the self glyph agent X would produce, at the
    observed facing: the official portrait, the ring's glow washing it, the
    solid tail -> subtract -> score the residual against sd_lo/sd_hi

Everything the loop needs is already measured or already stored:

* the 29 portraits are the hypothesis set, and the ground truth is in the
  ingest tags on 26 demo clips -- a label recorded for another purpose;
* the wash stops being a nuisance to REMOVE and becomes part of the
  PREDICTION, which is exactly what neither descriptor could do;
* the tail stops being masked out and becomes evidence, and its facing is
  independently readable (`minimap_ring_fit._facing`, magnitude validated
  against camera pan in `minimap_self_check`);
* the rim reading over its lower half only (22-23% present at the top) stops
  being a defect and becomes something the forward model must reproduce -- if
  the model does not predict the dropout, that is a falsifiable claim about it.

**Why here rather than on audio or on overlapping icons: ONE entity, 29
hypotheses, no assignment problem, and a free label.** The combinatorial
caveat below does not apply at all, which makes this the only place the loop
can be proved without also solving the pruning. If analysis-by-synthesis
cannot be made to work here, it will not work on a spatialised waveform.

**Trigger for the AUDIO half: after the cast-licenses-a-jump entry above.**
That is the smallest instance on the event side -- a hypothesised event
predicting an observable -- and it is worth proving the loop on one cheap
channel before building a dictionary. The `self_agent` instance has no such
dependency and can be taken whenever agent identity is next worked on.
