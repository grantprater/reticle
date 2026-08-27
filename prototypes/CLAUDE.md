# prototypes/ — detector state and the minimap in detail

Loaded when a session touches this directory, which is exactly when it is
wanted. The root `CLAUDE.md` carries what you need BEFORE you know which file to
open — the handoff, the conventions, the capture settings, the open defects.
This carries where each detector stands and why it is the way it is.

Module docstrings are the third tier and the most specific: they load when the
file is read, and they hold the reasoning for one file's decisions. Prefer
putting a fact in the docstring; put it here when it spans several modules, and
in the root when not knowing it would cause a repeated mistake.

**The section below that is hardest to replace is "Grant's domain notes on the
minimap".** It is not recoverable from the pixels and not derivable from the
code — a Cypher cam rotates but never translates, the triangle is the important
part of the teardrop, the site letters are dark grey on the yellow. If any of it
is ever contradicted by measurement, correct it in place and say so; do not
delete it.

### State, 2026-08-26

**Screen enemy detector: unchanged and still the shipped numbers.** 91.3% /
41.2% on Ascent, 76.2% / 42.5% on Lotus (`prototypes/enemy_detect_eval.py`,
which stays the reference oracle). `enemy_features.py` splits it into
`propose()` + `gate()`, proven bit-identical frame by frame.

**CLOSED: lowering `AREA` with persistence as the net does not work**, and
neither does track-level back-fill. At the shipped floor the track rule reaches
*exactly* shipped recall with much worse precision, so back-fill recovers zero
enemies there; 120 -> 8 buys 2 enemies on Ascent and 4 on Lotus for 43-55% more
false positives. **The shape gates, not the size floor, are doing the work.**
A blob-level fitted score gives a high-precision point the AND-chain has no
equivalent for (50.0% / 85.2% cross-map) but does not beat shipped+persistence
in the useful region. Detail in `enemy_teacher.py`, `enemy_teacher_sweep.py`.

**Screen detector regression on the new capture, unfixed.** On
`2026-08-26 09-56-37.mp4` the aggregate rate is normal (0.42 det/frame against
Ascent's 0.40) but the STRONG detections are dominated by purple Ascent foliage
and a **magenta weapon skin** at a fixed screen position (36 of 125 in
x 1360-1840, y 320-480). Both follow from widening the hue band to 130. Two
things to act on: a **weapon skin is a per-session property like the outline
colour**, and the weapon mask's `y > 0.66h` bound is too low for a raised gun
model. The summary statistic hid this completely; a contact sheet took one
glance.

**Minimap: the line is reopened and the finder works.** Full arc today, all
against Grant's 164 hand labels on `a06f04a0059f`, pre-kill pool:

    seal test (hole in the blob)          0.0% recall
    ring fit, per frame                80.8% / 54.6%    uniform P 19.4%
    + persistence len>=3               76.7% / 70.0%    uniform P 19.2%
    + motion (disp>=3 or rot>=15)      72.6% / 74.6%    uniform P 29.4%

The seal test died because **the ring is a teardrop, not an annulus** (Grant):
7.3 px thick at the triangle and **1.1-2.0 px over most of the rest**. Closure
is topological, needs every pixel of that thin arc, and one break loses it --
which is exactly what half-resolution chroma does. Fitting the circle that best
covers the arc needs no closing kernel (the thing that merged adjacent icons in
every earlier attempt) and degrades gracefully. `inner_red` is required
alongside coverage, or solid red things win; the radius must NOT float, or the
fit collapses to the smallest circle through a surviving fragment.

Persistence and motion attack **different** classes -- flicker and static
decoys -- which is why both earn their place. Every cut point is fitted to ONE
session; the project's history says a new map is where these break.

**The premise HOLDS**, in the strong ring-and-triangle form: Grant labelled with
the screen beside the minimap and reports no frame with an enemy present and no
icon. A "58%, so not a proof gate" figure I published was **wrong** -- the pool
sampled 300-1400 ms before the killfeed entry, which lags the kill, so most of
that window held no enemy yet. I treated "a kill happened 1.4 s later" as "an
enemy is present now" without checking it.

**Portrait identification works, and the interior is a far stronger signal than
the ring.** `prototypes/minimap_portrait.py`, `prototypes/label_icon_agent.py`.
Leave-one-out over 71 hand-marked enemy icons on `a06f04a0059f`, five agents:

    nearest exemplar (1-NN)              93.0%
    3-NN                                 84.5%
    one median template per agent        70.4%
    roster art as the template, flipped  74.6%   (crop fitted on the test set)
    roster art as the template, as-is    63.4%   (crop fitted on the test set)

and it abstains usefully -- answering 94.4% of icons at 97.0% correct, 69.0% at
98.0%, 52.1% at 100%, on the margin between the best-matching agent and the
runner-up AGENT (not the runner-up exemplar; two views of the same player
first and second is the confident case).

Four things worth carrying forward:

* **nearest exemplar, not a per-agent template.** A single template scores
  70.4% because the same agent's icons do not correlate well with *each other*:
  the facing triangle sweeps across the interior, the map floor bleeds in at the
  rim, and the local player's icon draws over the top at close range. Averaging
  over that is a blur that matches nobody. Free clustering of the 71 icons gave
  **19 groups, every one visually pure**, merging by eye into exactly the five
  agents the roster shows plus a sixth clean group for the question marks --
  those extra groups are the appearance modes, and holding them is the job;
* **it survives 4:2:0 where the ring nearly does not.** The ring is a 1-2 px
  *colour* feature and colour is what subsampling halves; the portrait is an
  ~11 px *luma* structure. Same file, same frames, opposite outcome;
* **the descriptor is scale-free** -- a disc of 0.55x the fitted ring radius on
  an 11x11 grid, red masked out, per-channel NCC. Every grid size from 11 to 17
  scored within 1.5 points, which says the information is in the pixels the icon
  actually has;
* **the failures are background, not confusion.** All five misses are icons
  sitting over warm scenery or heavily covered by the triangle, and no agent
  pair is systematically confused (five distinct one-off confusions). Masking
  the interior better is the next lever, ahead of any change to the matcher.

**The roster names the gallery; it is not the template source.** Mining the
five enemy portraits is automatic (`minimap_portrait.py mine` finds a frame
where all five are alive by requiring the *weakest* of the five slots to be
detailed, and cuts them at the measured grid). Two jobs it does well and one it
does not:

* it turns five clusters of *players* into five *agents*, needing one frame;
* it says who is ALIVE per frame, which is an external check on identification
  with no hand labels behind it -- 70 of 71 provisional labels name an agent the
  roster shows alive at that instant, against a 77% chance rate. Over all 120
  namings of the five clusters the labelling ranks first at 98.6%, but the
  runner-up is 97.2%, one observation behind: **corroboration, not proof**;
* it is a poor template source, and the reason is Grant's (below): the enemy
  side of the roster draws its art MIRRORED. Even flipped back it tops out at
  74.6% with the crop fitted to the answers. But Grant also says the minimap
  icon is a **circular crop of the same art at a consistent size and scale**,
  which means a fixed transform exists and I swept the wrong family. Fitting it
  against an unmirrored surface -- the Tab scoreboard, which `scoreboard.py`
  already locates -- would mean **a gallery mined once per agent transfers to
  every session**, and a new capture needs no labelling at all. That is worth
  more than the 18 points.

**CLOSED: the minimap icon is not a crop of the scoreboard bust.**
`prototypes/minimap_portrait_transform.py`. Held-out accuracy 24.7% against a
20% chance rate, and the diagnostic that settles it is the per-agent best case
-- a crop fitted to ONE agent's own icons, with no generalisation asked for:
Omen 0.215, Jett 0.236, Killjoy 0.160 resemblance, against 0.513 / 0.624 /
0.904 for two real icons of the same agent. Skye and Iso reach 0.63-0.65 and
still fall short. The per-agent optimal crops also disagree with each other.
Three agents at 0.16-0.24 in the best case is a different ASSET, not a
mis-placed crop, and the three it fails on are the ones with strong silhouette
furniture -- Omen's hood, Jett's hair, Killjoy's beanie.

Grant's observation is not what failed: the icon IS a circle at a consistent
scale, and as-is beats mirrored (24.7% against 17.3%), so the orientation claim
holds. What failed is my inference that the circle is cut from the scoreboard's
surface.

**The killfeed portrait fails the same way, and testing it exposed a flaw in
how the scoreboard result was read.** Killfeed portraits are a much tighter
face crop, so they looked promising; clustered and swept against each agent's
icons, every cluster scores the SAME against a given agent (Skye 0.43-0.61
across eight unrelated clusters, Iso 0.32-0.63), with the best beating the
runner-up by 0.002-0.02. So the 0.63 that Skye and Iso reached from the
scoreboard was never partial success -- it is a per-agent FLOOR, set by that
agent's icons correlating with any face-shaped patch. **Resemblance numbers
without a null control are uninterpretable, and mine did not have one.** The
correct statistic is resemblance-to-own-agent minus resemblance-to-others, and
by that measure the pixel-wise signal is zero on both surfaces.

**SOLVED, by throwing the layout away: composition matching transfers.**
Grant's question -- is there a technique for fuzzy matching across downscaled or
partial copies -- has an answer, and it is the one method that never needed the
framings to agree. Compare COLOUR COMPOSITION, not pixels. Scoreboard art
against the 79 labelled icons, five agents, chance 20%:

    whole portrait, NO parameters at all           77.2%
    central disc, held out by agent                83.5%   icon-weighted
    central disc, fitted on all five               92.4%   in-sample only
    in-domain control: icon histograms             91.1%   leave-one-out

against **88.6%** for the hand-labelled in-domain NCC gallery. Composition gets
within five points of a fully labelled gallery **using no minimap labels at
all**. The held-out fit is also stable -- three of five folds pick the same
(cx 0.42, frac 0.28) where the pixel-wise fit picked a different crop every
fold and scored below chance. `minimap_portrait.composition()`.

Why it works where correlation did not: at 11 px there is barely any layout to
match, and the identity that survives lives in the palette. Which is the
original argument for this being tractable -- the minimap's own palette is
narrow, so an agent's colours stand out against it.

**The cold bootstrap is wired and does not work yet, and the blocker is not
identification.** `minimap_portrait.py bootstrap` runs the whole chain with no
labels: scoreboard opening -> ten portraits -> five enemy compositions -> ring
fit -> named, with the roster giving a label-free alive check. Two things stop
it being trustworthy, and only the first is fixed.

**Fixed: scoreboard portrait extraction was wrong on two sessions of three, in
three compounding ways.** Each masked the next and none of them looked like
what it was -- the symptom was always "the lineup will not map to the roster".

* `read_scoreboard`'s table geometry moves a long way between openings, because
  **the board ANIMATES OPEN and a half-expanded board still parses**. One
  a06f04a0059f opening reports x 240..1699 with 42 px rows, another 572..1347
  with 34 px. Anything taken as a fixed offset from `sb.x0` inherits that;
* locating the portrait by DENSEST window put the crop on the player names.
  Measured across ten rows, name text peaks at 151 and portrait art at 130 --
  text is denser. The reliable feature is the GAP between them (detail 14
  against 130), searched from inside the table, since everything left of the
  table edge is flat background and a deeper minimum still;
* selecting an opening by detail alone picks half-expanded boards, and
  selecting by tallest picks MISDETECTIONS -- 55 and 60 px rows on Lotus and
  Split against 42, with blank portraits (weakest-row detail 0.5 against 78).
  Both conditions are needed: gate on portrait readability
  (`SB_MIN_ROW_DETAIL`, a floor of 30 in a gap between 2.5 and 64), then prefer
  the tallest of what survives.

All three sessions now cut ten clean portraits, and the roster-to-agent mapping
is a clean bijection on all three at 0.49-0.79.

**That mapping is also done by COMPOSITION, and the first version was a
mistake worth recording.** I used pixel correlation, reasoning that the roster
and scoreboard carry the same bust asset so correlation was fine here even
though it had just failed against the minimap. It scored 0.23-0.48 on
a06f04a0059f and produced the right answer, which I read as it working; on the
two new sessions it scored 0.02-0.49 and produced no bijection at all. The
first result was luck and the low scores were saying so. Composition also
happens to make the roster's mirroring irrelevant, being layout-free.

**NOT fixed, and now the binding constraint: the icon population.** Over a whole
match the ring finder's output is dominated by things that are not agents --
X marks, abilities, question marks -- and there are far more of them than
enemies. Reject classes help (`confounders.npz`, mined once from a06f's labels
and reusable because a `?` glyph and an X mark are the same art in every
capture) but each one becomes a sink that absorbs most detections. Persistence
plus translation is the right filter -- **a question mark marks a last-known
position, so it cannot move, and neither can an X mark or a turret** -- but at
len>=3 and displacement>=3 it cuts yield to roughly 10% of tracks, which is too
few to measure anything on.

So identification is proven as a METHOD and unproven as a PIPELINE, and the gap
is detection, not matching. Two ways forward:

1. **confirm transfer with a small label pass on Lotus.** Feed
   `label_icon_agent.py` candidates straight from the ring finder so Grant names
   icons that are already found rather than clicking to find them -- perhaps 60
   keypresses. That turns 83.5% from "held out by agent on one session" into
   "measured on a lineup never seen";
2. **go at the detector**, which is now what limits everything downstream.

The label-free alive check cannot settle this on its own: with four of five
enemies typically alive its chance rate is 67-81%, so it catches a collapse and
cannot separate 85% from 95%.

Roster geometry, measured at 1920x1080: enemy slot k at
x = 1175 + 65.75k, y 30..70, 40 px square, slot 0 nearest the scoreline.
Survivors PACK toward the scoreline keeping team order, so slot index is not
identity -- the sequence is.

**The cold bootstrap works on unseen sessions.** All three, no minimap labels
anywhere, enemies named from scoreboard art by composition:

    session          map      ids   alive-consistent   chance
    a06f04a0059f     Ascent    15        86.7%          69%
    5822b6646448     Lotus     14        85.7%          53%
    c62c2b06bcfb     Split     22       100.0%          69%

Two lineups never seen on two maps never seen at this widget size, and the
distribution spreads across all five enemies on both rather than collapsing.
What it does NOT show: n is 14-22 because the motion filter is strict, and at
these chance rates the alive check separates "not collapsing" from "collapsing"
and cannot separate 85% from 95%.

### Colour-free detection: measured, and blocked on labels

`prototypes/minimap_dynamic.py`, `prototypes/label_dynamic.py`.

**As a replacement for the red finder it loses decisively**: 55.6% / 29.6% at
its best of eighteen configurations, against `minimap_ring_fit`'s shipped
80.8% / 54.6%. Structural, not a threshold -- tracing every hand-marked enemy
icon through the filters gives 32 fragmented below the area floor, 29 kept, 11
merged above the ceiling, 5 with no blob at all. The raw signal is fine (peak
difference at a mark has a median of 147); the icon's 1-2 px rim simply falls
apart under differencing, into fragments of median area 57 and p10 SIX. Closing
to repair it takes recall to 21.8%, because the radius that reconnects a rim is
the radius that merges neighbours -- the same trap for the third time.

Three reasonable guesses died here, all recorded in the module:

* guarding box edges as well as borders leaves 25.2% of the widget searchable
  and cuts recall to 38.9%; box edges run through the interior, so guarding them
  deletes the floor icons stand on. **Borders only**;
* the viewcone merging icons into itself is real but small -- 11 marks against
  fragmentation's 32. Top-hatting the difference bought 2 points;
* **the triangle does not survive where the rim dies.** It is 7.3 px against
  1-2, so a triangle-first detector looked like the natural rescue and it is
  Grant's own observation. The angle between the largest surviving fragment and
  the triangle's measured bearing has a median of 77 degrees, 30% inside 45
  against 25% for random. The icon fragments evenly.

**So this is not the enemy detector and expecting it to be was the error.** The
circle fit is better at finding red rings and keeps that job. What this channel
uniquely does is see what has NO colour -- the pure black-and-white ability
glyphs a red mask cannot reach at any threshold.

**BLOCKED: that cannot be scored.** Nothing in the store says where an ability
icon is. The channel reports 1300-3900 uncoloured blobs per sweep against
200-300 red, and there is no telling glyphs from noise without labels.
`label_dynamic.py` is the pass that unblocks it -- uniform over active play (an
ability has no pre-kill anchor, and a pre-kill pool would over-represent X
marks), asking only "what is the ringed thing" from six classes, with the blob's
measured features stored beside the answer so a classifier can be fitted later
without re-detecting. It does not ask WHICH ability: detection first, identity
second, the order that let every earlier stage be measured on its own.

**What this channel may look at: the opaque slab, plus the bomb sites.**
`prototypes/paint_map.py`, `searchable(labels, static=...)`. That is the whole
rule, and getting to it took five corrections from Grant in one session, every
one of them found by eye off a labeller screen after I had already convinced
myself with numbers:

1. the dilation fringe at the map's rim -- *the outer bounds are a row of white
   pixels and then outside that a row of grey.* It is `floor_mask`'s deliberate
   9 px dilation, added so a red ring OVERHANGING the slab edge is still
   scored; `LINE_GUARD` missed it by exactly one pixel;
2. **cutting the whole fringe was wrong** and he called it before the numbers
   did: *those are on a map border, but not outside it.* Ten of the eleven
   hand-marked centres it lost were 1-3 px from an interior BOX EDGE;
3. **the bomb sites were 93% VOID.** `floor_mask` is `sat < 20` and the paint is
   tinted, so it fails; the PLANT class was fitted to the saturated core at
   `sat > 60` and caught 3% of the zone. A site is opaque (SD 17.9 v the slab's
   16.6) and 19 of 254 hand-marked icons stand in one. Widened to the hue
   alone, closed, size-floored, filled so the LETTER comes with it -- *the
   letters are a very dark grey, almost black, always against the yellow* --
   and required to TOUCH THE FLOOR, because widening also caught the agent HUD
   in the top-right corner as a third "site", 102 of 116 blobs at SD 42.5;
4. enclosed void pockets, which no flood from the frame edge can reach: *a void
   right next to the site ... it goes straight from white to the muddy brown of
   the background*;
5. the borders have a **drop shadow** -- white, then light grey, then darker
   grey on the bottom edge, plain white on the top -- so no symmetric guard
   fits them anyway.

**Then he painted the mask** and it replaced all of it. Scored against his
painting, on a mask he made without ever pressing `m` to see mine:

    slab + sites, no guard              IoU 91.3%   241 of 254 marks reachable
    slab + sites, border guard 1px      IoU 89.4%   227
    slab + sites, border guard 3px      IoU 83.9%   211
    + the floor mask's dilation ring    IoU 76.4%   220
    Grant's own painting (ceiling)      IoU  100%   227

He kept 0.0% of the holes, 0.0% of the exterior and 7.3% of the overhang ring.
**The question was never which transparency is tolerable**, which is what four
of my five patches had been about. Everything they added -- an exterior flood
fill, a fringe scoped to it, a hole rule, a pocket rule, a per-region threshold
-- is deleted.

**`LINE_GUARD` goes too, and that is the surprise.** This module opens by saying
the white lines are where the false positives live, 107 blobs against the red
mask's 7, and the guard has been in since. Measured on the slab, a white line is
the QUIETEST thing on the widget -- temporal SD **7.4** against plain slab's
17.1, so a noise-matched threshold there would be 12, not 28. The flicker was
never the line; it was the void beside the line, and the guard was charging the
line for its neighbour's noise. Grant painted over 71% of the box edges and 47%
of the borders, which is what a person does when a line is just map. Dropping it
takes reachable centres from 211 to 241 of 254 with the stream unchanged.

Net over the same 120 frames: stream **925 -> 278**, reachable hand-marked
centres **212 -> 241 of 254**, bomb sites 7% -> 100% searchable, and the rule is
one line instead of five.

**The rule TRANSFERS, and the straight-line idea is dead.** Grant painted Lotus
too, again without pressing `m`, and the derived rule scores **IoU 92.8%** on it
against 91.3% on Ascent -- a different map, a different site count, a mask made
independently:

                     Ascent   Lotus
    IoU               91.3%   92.8%
    lit slab          94.2%   92.9%   painted
    bomb sites        99.0%   93.3%
    HOLE               0.0%    0.0%
    exterior void      0.9%    0.0%
    BORDER line       46.6%   47.7%
    BOXEDGE line      71.3%   58.0%

Two maps, two independent paintings, near-identical profile. The plant fix
transferred unseeded as well: three zones found on Lotus, A B and C, 100%
searchable, on the first map with a site count different from the one it was
built against.

**Grant then withdrew the straight-line observation, and he was right to.**
*I think my assertion was wrong, there is at least one line that looks like it's
supposed to be curved.* Fitting `approxPolyDP` to the searchable boundary:

    Ascent  eps=2px   96.0% orthogonal   0.3% at 45deg    3.6% neither
    Lotus   eps=2px   81.7% orthogonal   3.3% at 45deg   15.0% neither

Ascent IS 96% axis-aligned, which is why the claim felt true -- it was true of
the map he was looking at. Lotus is not, and its 15% does not shrink when the
tolerance doubles (14.6% -> 15.0%), which is the signature of a genuine curve: a
curve is merely re-approximated by a looser epsilon where a straight edge
collapses into fewer segments. So **do not snap the mask boundary to straight
segments.** It would be correct on Ascent and would cut corners off Lotus, and
the failure would be invisible at the IoU level -- 15% of a 1568 px perimeter is
a few hundred pixels against a mask of 70,000.

**Do NOT pre-filter the pool on shape.** Aspect looks decisive -- 0 of 55 blobs
at Grant's hand-marked icons reach 2.0, p95 1.71, against a quarter of the
stream at 2.5+ -- but those 55 are ENEMY icons, and a Sage or Viper wall is
drawn on the minimap as a long thin shape. Filtering on it before the labels
exist would delete exactly the abilities the pass is for. It is stored per row
as `aspect` and asked of the labels afterwards instead.

The labels settled it three times over: a **ping** is an expanding ripple whose
fragments are thin arcs, an **area** ability is a wall, and the corrected
**barrier** at t=1041958 has an aspect of **9.50**. Every one would have been
deleted by a filter that looked decisive at 0 of 55 enemy icons over 2.0.

Note on the primitive, since I described it loosely once: **the shipped detector
fits a CIRCLE**, scored by how much of its circumference is red, plus a non-red
interior test. The teardrop is why we got there -- it killed the closure test --
and the thick triangle is read separately by rays as `facing` and `lobe`. No
teardrop is ever fitted.

### The minimap's own palette and geometry, measured 2026-08-26

Grant named these off footage and had never noticed the elevated shade before,
so none of it appears in any earlier measurement. What the pixels say:

* **the map has real HOLES** -- unwalkable interior bounded by the white
  lines Grant says dictate them. **17.5% of the footprint on Split, 14.5% on
  Ascent** (`prototypes/minimap_geometry.py`). An earlier figure of 33.9% and
  33.3% here was WRONG: it took the floor's convex hull as the footprint, and a
  floor plan is deeply concave, so the gaps between the map's arms counted as
  interior holes. I read the two maps agreeing to within half a point as
  confirmation when it was really two maps being equally convex-ish -- a
  spurious agreement is not a check. The footprint is now what the floor
  encloses, found by flooding the exterior inward;
* **a dark low-saturation band is the VOID, not elevated ground.** Split's
  static map is 73% low-saturation against Ascent's 29%, with 55% of it in
  V 60-90 where Ascent sits at V115. I took that for elevated walkable area
  being wrongly excluded and it is not: overlaying the mask shows the band is
  the semi-transparent region OUTSIDE the map, and Split's void is simply
  darker because of what renders behind it. `floor_mask` is right;
* **the viewcone shows up as a per-frame brightness LIFT over the static map** --
  p90 +51 on Split, +8 on Ascent, against a p50 of 0. That is worth flagging
  well beyond ability work: a lighter-grey cone is *what your team can currently
  see*, which is exactly the basis SS4 needs for peek exposure and which the
  design doc's version was declared out of reach for. Not pursued yet.

### Ability icons: what Grant sees, and what it implies

Corrections he made to two guesses of mine, both worth keeping because both
were plausible and both were wrong:

* the `other_red` clusters I presented as candidate classes are **scenes, not
  marks**. A 36 px tile holds a Cypher cam AND two overlapping X marks AND a
  dropped spike AND ally portraits. The descriptor only reads a ~5 px disc so it
  was not confused, but every class I read off that sheet was an artefact of the
  tile size;
* ability icons are **not** uniformly a black-and-white glyph inside a
  team-coloured surround. Some are pure black and white with no team indication
  at all; Skye's bird and dog were the only ones Grant saw with a green outline
  (plus a small directional arrow). **A pure B/W glyph is invisible to the
  current finder**, which masks on red -- those are not confounders being
  misclassified, they are undetected.

Named so far: the yellow triangle with a ringed glyph is the **dropped spike**.
The rest of the pool is dominated by X death marks.

**How team gets attributed, which is the design's load-bearing idea.** Grant:
an ability's team is inferred from WHOSE ability it is -- most abilities belong
to exactly one agent -- or from the teammate it originated with. He is not sure
whether a small team indicator exists. That does not matter, because the
scoreboard already gives the full ten-agent lineup: **ability -> agent is nearly
1:1 and agent -> team is known**, so classifying the glyph attributes the team
for free. It also collapses the search space from every ability in the game to
the thirty-odd the two teams in THIS match can actually produce, and prunes by
who is alive. That is the same scoreboard read the identification work already
depends on, doing a second job.

### Grant's domain notes on the minimap -- not recoverable from the pixels

* **A Cypher cam ROTATES**, and it is the **only other moving icon** on the
  widget. Perfect circle, never translates, rotation shown by the camera glyph
  turning INSIDE the ring -- **no lobe**. This corrected "a placed ability never
  turns", which was load-bearing in `motion()`. Consequence: **translation**
  holds against everything including the cam; **rotation does not reject a cam
  at all**, since rotation is read from the lobe and a cam has none.
  `minimap_ring_fit.LOBE_MIN_FRAC` floors that so a perfect circle cannot report
  a confident bearing from noise. **Still UNTESTED against a real cam** -- no
  label says which `other_red` marks are cams.
* **The triangle is the most important part of the teardrop** -- 7.3 px against
  1-2 px for the rest of the ring, so it is both the most robust part and the
  part carrying identity. A cam has a ring and no triangle.
* **The interior portrait is the same art as the KILLFEED portrait and the top
  roster portrait.** Route to identification, and it works -- see "Portrait
  identification works" above. Two corrections Grant made once it was measured:
  **the ENEMY SIDE of the roster draws the art mirrored**, so the two teams face
  each other, while **the Tab scoreboard and the minimap hold every agent in one
  orientation, always**; and **the minimap icon is a circular CROP of that art,
  not the whole bust, at a consistent size and scale**. The first explains why
  flipping the roster art gained 11 points of matching accuracy; the second says
  a fixed crop-and-scale transform exists to be fitted, which is what a
  cross-session gallery needs.
* **Omen's ultimate turns the minimap a fuzzy black for a few seconds** and is
  the ONLY ability in the game that does so; Omen also teleports globally, so
  position continuity breaks across it. Detected and abstained on rather than
  tuned through -- `minimap_temporal.USABLE_MIN = 70`, sitting in an empty gap
  (floor brightness 121 median / 131 p95 normally, 0-30 affected, p01 39).
  Round-transition fades trip it too. A frame that is unreadable must produce
  NO answer, not a confident empty one.
* **The local player's icon draws ON TOP of an enemy's** when they overlap.
  Deprioritised on Grant's call: only at extreme short range, where the screen
  detector has a large unambiguous blob anyway. It IS in the agent-label set --
  Grant flagged one Jett icon mostly covered by his own in a close-range duel --
  so identification sees the case even though detection was allowed to skip it.
* **An ally Breach ultimate draws a big RED BAR across the minimap**, and it
  occludes icons: Grant hit one covering the top of a question-mark icon while
  labelling. This is the sharpest counterexample yet to the assumption the whole
  minimap line rests on -- **red does not mean enemy**. Every red confounder
  catalogued so far (X marks, Reyna blinds, Cypher cams, pings) is small and
  roughly icon-sized, which is why area and ring-fit gates have been enough; a
  bar is large, is drawn by YOUR OWN TEAM, and lands on top of real icons rather
  than beside them. Consequences to check, none of them measured yet: it may
  survive `floor_mask`, it is the wrong shape for `fit_ring` but could still
  supply a stray arc, and for the portrait descriptor it is occlusion the red
  mask happens to remove for free. Not in any label set as its own class.

**Profile: `valorant-16x9-bigmap`.** The enlarged widget spans px 15..480 x
15..500 against the old 15..346 x 22..351, so the shipped `minimap` ROI missed
most of it. Overrides that one ROI and nothing else; borrows
`valorant-16x9`'s mined templates via `Profile.template_profile`. Its bounding
box clips the ally roster (starts x=434), so the corner x 434..480, y 15..90
holds roster HUD as well as minimap -- accepted, but anything reading this ROI
as a change signal should know it also changes when a teammate dies.

**Capture side: 4:2:0 costs a fifth of the screen detector and most of the
minimap.** Measured on a lossless round against its own subsampled twin, so only
chroma resolution moves: 65.6% of rim pixels survive, top-hat at the rim falls
43.8 -> 27.6 against a threshold of 25, detections fall 103 -> 80. On the
minimap the enemy ring seals in lossless (hole_frac 0.69) and not at 4:2:0
(0.00-0.09). Grant's call: stay on 4:2:0 and prove it there, which the ring fit
now does. `prototypes/chroma_test.py`, and item 12 of the pre-ingest checklist.


**Also unresolved and worth an eye:** some corpses carry a red outline and some
do not, and no explanation survived testing. The obvious one -- the outline fades
with age -- is unsupported but the test is underpowered, because the killfeed
timestamps deaths without locating them and so cannot age an individual body.

Last worked 2026-08-26. **Seventeen sessions ingested, seventeen with
scoreboard K/D in `checks.KNOWN_KD`, and every one carries its map.** Sixteen
are scorable (`0f08b3dc3777` is the cropped capture and has no killfeed ROI).
The store is at **`hud-0.8.1`** throughout. **Nine of thirteen are exact and the gap is 8 events across 372.** Five of the
eight are Run It Back (see "Scoreboard divergence is a finding" below), one is
the ability-kill read error, and two are new and uninvestigated — see below.
Long tracks are 0. Nothing is half-applied and the tree is clean.

**`5822b6646448` (Lotus, 13/21) is EXACT with no invariant violations**, and it
is fully out-of-sample: recorded 2026-08-26 after the widget change, ingested
and scored the same day, nothing tuned against it. It is the second capture on
the enlarged minimap and the first on a map that widget has not seen, which is
the test the icon work most needs. `c62c2b06bcfb` (Split, 13/15) is **kills exact, deaths -1**,
with 5 invariant violations and both open. The violations look like one cause,
not five: the scoreline reads a two-digit score as one digit twice
(0:06:51 12 -> 2, 0:31:43 12 -> 1) and recovers within 3.5s each time, so the
two decreases and the two illegal sum steps are the same event counted from
both sides. The 4.5s clock jump at 0:00:03 is pre-match. Neither the -1 death
nor the dropped digit has been investigated; a Split lineup has not been seen
at this widget size before. Both were confirmed `valorant-16x9-bigmap` before ingest by
measuring the floor slab — it reaches x 452 / 458 against the old widget's 346.

**Ground truth is now corroborated.** Grant read his whole match history on
2026-08-25 and every K/D already transcribed off the end screens agreed, so
`KNOWN_KD` has two independent sources behind it. Two sessions gained ground
truth for the first time and both were fully out-of-sample — never scored, never
used to tune anything: `96aa1ae9b96f` (Haven) came out **exact**, and the brand
new `043bafca271a` (Haven) came out **exact** as well.

**One match has no capture.** The history lists a thirteenth match on 2026-08-24
(Split, 3/13) with no corresponding file. Nothing is wrong with the pipeline;
the recording is simply absent.

**Open: `e37fdeca944f` (Sunset) is −2 deaths.** A brand new capture on a map
never seen before, kills exact. Not yet investigated and not yet known whether
it is a read error or another divergence. It is the first thing to look at.

`hud-0.7.0` — **three band-detection fixes**, all found from five misses Grant
spotted by eye on `9acf02f98283` (4:27, 20:32, 24:35, 31:22, 32:22). Four of the
five were caught in exactly *one* sampled frame, one short of `KF_MIN_OBS`; the
fifth formed no band at all.

* plate density was measured across the whole ROI, so **narrow entries** ("Me
  (Bandit) exile") fell under `PLATE_ROW_FRAC` where the glyphs are tallest and
  the run shattered below `MIN_BAND_H`. Now measured inside the row's own entry;
* **warm scenery** reads as the enemy plate's red and merged into the entry
  above until the run passed `MAX_BAND_H` and was discarded whole. Rows now have
  to show both plate colours — the band's own test, one step earlier. Because
  new entries arrive at the top of the stack, this always cost the newest event;
* the divider test asked for **ink** either side, not glyphs, so bright sky in
  the band won it on size and flipped a kill to a death. Now glyphs.

`hud-0.8.1` — **a divider is only recorded when it can be trusted.** While an
entry slides into the stack its band is half-formed for a frame or two and the
split can land far left with no killer name beyond it; at `ff636d173b07` 10:18
that read 151 and 150 before settling at 253, and the tracker took the move as a
different entry and counted one death twice. The divider is now recorded only
when there is a name on both sides of it — the same test that chose it — and an
unrecorded one (stored as 0) falls back to slot and time. This was the divider
mechanism's own first defect, found while trying to verify the Phoenix deaths.

`hud-0.8.0` — **the tracker now sees each entry's divider column**. An entry's
weapon-icon divider sits at a fixed column for its whole life (the feed is
right-aligned, so the victim's name width sets it) and moves by at most 3 px,
while two different entries in one slot are tens of pixels apart. Storing it
(`kf_entry_wx` / `kf_kill_wx` / `kf_death_wx`, packed nine bits per slot) and
refusing to extend a track whose divider moved more than `KF_SIG_TOL` removed
every long track in the set. `223d636bf8d2` went exact; `ff636d173b07`'s kills
went from −3 to exact. **This supersedes the `kf_entry_mask` stack-shift plan** —
the divider does the same job more directly, and `kf_entry_mask` is still unused.

**Settled: every remaining divergence is Run It Back.** All six events between
the killfeed and `checks.KNOWN_KD` are now accounted for — one read error and
five entries that are read correctly and simply not counted:

* `ff636d173b07` +4 deaths. All 24 tracked deaths read correctly, and exactly
  four carry the **Phoenix ult mark** — 13:21, 20:00, 29:13, 38:20. 24 − 4 = 20,
  the recorded figure. Grant's own deaths inside his ult.
* `bfad2778a372` +1 kill, the same rule from the other side: a kill on an
  *enemy* Phoenix inside Run It Back. 19/15 confirmed off the end screen.

Both causes are **visible in the killfeed itself**, which is what makes reading
the mark worth doing: one detector reconciles both sessions exactly.

**Grant's call (2026-08-25): keep these events, do not drop them to match the
board.** A duel lost inside Run It Back is still a duel that was lost, and §4's
metrics are about duels. So the mark becomes a *category* on the entry — an
event that happened and that the scoreboard does not count — rather than a
filter. Stage 05 subtracts them when reconciling totals; stage 06 decides per
metric whether to include them. Same treatment as wallbangs.

**In flight: minimap position tracking** (`prototypes/minimap_position.py`,
not wired into the pipeline). Measured on `9acf02f98283`: 86% of frames yield a
position, 92% coverage after filtering, 1.5% of steps physically implausible.
Ally rings detect too. The static map falls out as a per-pixel median and is
also the occlusion grid the geometry work needs. Read the rejected-approaches
list at the foot of that file before trying anything clever — five variants
failed there and the failures share one cause: **the widget is semi-transparent
over the void, so anything content-based drowns in the world moving behind it.**
Masking to the opaque floor slab is what fixed it.

Next steps, in order: promote it to `reticle/minimap.py` with L1 columns; settle
the sample rate (everything downstream is a *speed* measurement, so 2 Hz cannot
work — 15-20 Hz for the minimap, likely a separate pass from the 2 Hz HUD read);
then the visibility computation.

**Peek exposure as the design doc defines it is out of reach**, and that is a
design-doc correction rather than a missing feature. It needs enemy positions,
and the minimap shows an enemy only while somebody on your team can see them --
a teammate holding an angle, or a recon reveal -- plus red X marks for last-known
positions. That is *what your team knows*, not ground truth, and for decision
analysis it is the right basis: you cannot be faulted for an enemy nobody had
seen, but you can be for peeking into one a teammate was looking at. It does
mean full exposure-to-any-enemy is out of reach from a self-capture. If the
product must run on a player's own OBS capture (Grant is sceptical that building
commercially on the replay system is viable), no amount of extractor work
recovers it. See "How peeking actually works" below for what replaces it.

The four candidates for what comes next, with the case for each:

1. **Reconcile the scoreboard against the killfeed** (§3 stage 05). The board
   outranks killfeed inference and is already readable, so for any session where
   it is open the totals could simply be taken from it, with the killfeed
   supplying timing within the round. This makes the remaining attribution gap
   stop mattering for totals without fixing it.
2. **Record whether an entry carries a revive mark.** This is now the best-
   evidenced next step: it is the only divergence in the set with a *visible
   cause in the killfeed itself*, and reading it would reconcile `bfad2778a372`
   exactly. The marks all sit in one place — right of the weapon icon, where a
   headshot crosshair goes — and are all circular badges, so *detecting* one
   needs no icon list; telling the four apart does, but four is a bounded set
   that changes only when Riot ships a new revive ult. Worth capturing as a
   field on the entry either way: a kill undone is its own coachable category,
   the same argument as wallbangs.
3. **Minimap position tracking** — the last big stage-02 extractor, and the
   gating dependency for the doc's peek-exposure metric.
4. **Keep grinding killfeed recall.** Diminishing: four causes found, two fixed,
   the rest cost a re-ingest or need a new primitive.

If a new capture reads badly, count thin tracks first (see below) — it is the
fastest signal for whether the problem is detection or counting.

