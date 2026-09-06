# prototypes/ — detector state and the minimap in detail

Loaded when a session touches this directory, which is exactly when it is
wanted. The root `CLAUDE.md` carries what you need BEFORE you know which file to
open — the handoff, the conventions, the capture settings, the open defects.
This carries where each detector stands and why it is the way it is.

Module docstrings are the third tier and the most specific: they load when the
file is read, and they hold the reasoning for one file's decisions. Prefer
putting a fact in the docstring; put it here when it spans several modules, and
in the root when not knowing it would cause a repeated mistake.

**The section below that is hardest to replace is "the domain notes on the
minimap".** It is not recoverable from the pixels and not derivable from the
code — a Cypher cam rotates but never translates, the triangle is the important
part of the teardrop, the site letters are dark grey on the yellow. If any of it
is ever contradicted by measurement, correct it in place and say so; do not
delete it.

### The vision cone: origin, facing, raycast -- started 2026-09-02

`prototypes/minimap_cone.py`. the spec, from watching cones deliberately
on a fresh clip: the cone originates at the icon's own teardrop point, spans a
fixed angle centred on the direction that teardrop points, and each ray stops
at the first wall -- no reflection. Full detail, including two real mistakes
made building it (a facing calculation that was ~180 degrees off from icon
fragmentation, and a brightness-diff width measurement contaminated first by
a UI ping-range ring and then by the plantable-zone tint), is in that module's
docstring, not repeated here.

Working state: facing extraction is solid, verified by eye against real
frames (the fitted arrow lands on the visible triangle bulge, not assumed).
The raycast mask is verified too, in a way that wasn't planned -- rendered on
a doorway frame, it splits into thin fingers through the gap and re-expands
beyond it, unprompted, exactly the behaviour the player described from playing.
`CONE_HALF_ANGLE_DEG = 56` (112 total) is a working estimate from 23 samples
on ONE clip, ONE map -- confirm on a second map before trusting it further.
Box pass-through is coded per the stated fact, not yet independently
measured (the one test case tried didn't actually cross a boxedge pixel).

**Not yet done, and the reason to come back to this**: the
follow-up -- across many cone instances, a boxedge segment light passes both
sides of in the same frame is a real low obstacle, one that's never lit past
is a full wall mislabelled as a box. That is a label-free fix for
`minimap_geometry`'s box/wall classification, already known to be poor, but
needs far more cone observations than one clip supplies.

**Practical yield is much lower than the demo clip suggested -- measured
2026-09-02 trying to use this for something else.** Applying `icon_facing` to
50 real ability-candidate positions on `eb10db50b1fb` (not the curated demo
clip this module was built and tuned against) returned a usable cone for only
4 of them -- `LOBE_MIN_FRAC`'s refuse-over-guess gate is doing its job, but it
means the cone is not yet a tool you can point at an arbitrary frame and
expect an answer from. Anything built on top of it needs to budget for that.

**CORRECTED 2026-09-03: the yield is ~90%, and the 4-of-50 was a SEEDING
problem, not the gate refusing.** Seeding `self_cone` from the largest ring
returned by `reticle.minimap.self_rings` (`prototypes/ability_cone.py`,
`--cone`), measured over every labelled ability frame:

    2ba870ccbd50   22/22 frames   100%
    79a706a7ce4c   54/55           98%
    a06f04a0059f   40/42           95%
    eb10db50b1fb   18/32           56%   <- the session 4-of-50 came from
                                          89% pooled

Even on the original session the yield is 56%, not 8%. So `LOBE_MIN_FRAC` is
not the binding constraint and the paragraph above should not be used to price
cone work. **The two parked hypotheses below -- cone-termination proximity and
local sliver/thinness -- are affordable again**; they were shelved on the
strength of the 4-of-50 figure.

Separately, and it is a different question from yield: using the cone as the
LIGHTING REFERENCE for ability detection was tried and does **not** beat the
plain two-state interval residual (93.8% recall at 34.1% precision against
38.5% at the same recall). See `ability_cone.py` -- the diagnosis behind it
holds, 27% of labelled positives are invisible to the interval test at their
own pixel, but a more permissive reference lifts the noise as much as the
signal.

**Two open hypotheses from the player, 2026-09-02, neither tested successfully
yet -- recorded so they aren't re-guessed blind next time:**

* **Cone TERMINATION proximity.** Several false-positive ability candidates
  on `eb10db50b1fb` turned out to be fragments of the player icon
  (confirmed by eye: 1 and 3 were the icon's arrow, 2/4/5 were its middle),
  and the read was that they "all have relatively close terminations of
  the viewcone" -- i.e. the icon sitting near where a ray stops might be *why*
  the icon's own diff signature fragments into separate candidate pieces
  rather than being caught as one blob. Tried two ways, neither worked: (1)
  seeding the cone fit from the CANDIDATE's own position rather than the
  icon's true position, which is invalid whenever the two are far apart (the
  real trapwire instances sit 8-32px from the self icon, past `fit_ring`'s
  +/-5px search); (2) seeding properly from `reticle.minimap.self_rings`'s
  fitted centre instead, which is correct but starved by the yield problem
  above -- only 4 of 50 rows produced a cone to measure distance-to-boundary
  from at all. **Not disproven, just unmeasured.**
* **Sliver / local thinness -- a DIFFERENT property, the distinction.**
  Not "does a ray stop here" but "is the lit region narrow here" (a ray
  passing through a doorway gap, per this module's own doorway-finger
  behaviour). A quick substitute -- distance to the nearest wall on the
  STATIC floor mask, needing no facing fit at all -- was tried as a
  same-day cousin of this idea and came back flat (real trapwire 38-65px
  from a wall, `not_ability` 14-78px, total overlap, zero separating power).
  That result says wall-proximity alone isn't it, not that thinness isn't --
  thinness needs the actual cone's local width, which inherits the yield
  problem above.

Both need either a way to raise the facing-fit's yield (a looser gate for
diagnostic use, trading confidence for coverage -- a real design decision,
not a quick fix) or a controlled clip built specifically to produce many
cone instances near walls/dooprways on purpose, the same way the original
half-angle measurement clip was built on purpose.

**Wrong session used for this whole thread, caught by the player 2026-09-02.**
`eb10db50b1fb` and `d95cfad5693a` are both `valorant-16x9` (the small
widget). A third Cypher session, `79a706a7ce4c`, was recorded the same
evening an hour later on `valorant-16x9-bigmap` (the enlarged widget) --
geometry is built but nothing has scanned it yet. Every finding in this
section (`self_icon_dist`, `device_glyph_score`, `host_span`'s failure, the
two hypotheses above) was measured on the SMALL widget only and has not been
checked against the bigger one, where icon radius and cone geometry both
scale differently.

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
against the 164 hand labels on `a06f04a0059f`, pre-kill pool:

    seal test (hole in the blob)          0.0% recall
    ring fit, per frame                80.8% / 54.6%    uniform P 19.4%
    + persistence len>=3               76.7% / 70.0%    uniform P 19.2%
    + motion (disp>=3 or rot>=15)      72.6% / 74.6%    uniform P 29.4%

The seal test died because **the ring is a teardrop, not an annulus** (the player):
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

**The premise HOLDS**, in the strong ring-and-triangle form: the player labelled with
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
* it is a poor template source, and the reason is the (below): the enemy
  side of the roster draws its art MIRRORED. Even flipped back it tops out at
  74.6% with the crop fitted to the answers. But the player also says the minimap
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

the observation is not what failed: the icon IS a circle at a consistent
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
the question -- is there a technique for fuzzy matching across downscaled or
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
   `label_icon_agent.py` candidates straight from the ring finder so the player names
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
  the observation. The angle between the largest surviving fragment and
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
rule, and getting to it took five corrections from the player in one session, every
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
    the painting (ceiling)      IoU  100%   227

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
line for its neighbour's noise. the player painted over 71% of the box edges and 47%
of the borders, which is what a person does when a line is just map. Dropping it
takes reachable centres from 211 to 241 of 254 with the stream unchanged.

Net over the same 120 frames: stream **925 -> 278**, reachable hand-marked
centres **212 -> 241 of 254**, bomb sites 7% -> 100% searchable, and the rule is
one line instead of five.

**The rule TRANSFERS, and the straight-line idea is dead.** the player painted Lotus
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

**the player then withdrew the straight-line observation, and he was right to.**
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
at the hand-marked icons reach 2.0, p95 1.71, against a quarter of the
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

### The static map does TWO jobs, and only one of them wants a derived image

the player, 2026-09-05: *the valorant wiki had minimap images, probably better than
our derived ones.* Right, and separating WHY exposes a conflation this
directory has been carrying since `static_map` was written.

The per-pixel median is used for two unrelated purposes:

**1. GEOMETRY -- what is floor, wall, hole, bomb site.** Derived, and the
record here says derived badly. `minimap_geometry`'s box/wall split is
described in this file as "already known to be poor"; the bomb sites came out
**93% VOID** until the classifier was rewritten round them; widening the plant
test grew a third "bomb site" out of 10921 px of brown void on Split; and the
searchable area was derived and re-derived FIVE times before the player painted it
by hand, twice. It is also per-session by construction, so a parked vision cone
bakes into it as map structure -- measured on `c0b63335e635`, a 2271 px blob at
(215,183) classified `box edge` where the full match says `floor`.

**A canonical map image fixes every one of those**, and it is the thing the
root checklist already asks for: *geometry should be shared between sessions on
the same map rather than re-derived per session*. The map is already known --
manifests carry a `map:<name>` tag.

**2. PHOTOMETRY -- what a pixel LOOKS LIKE in this capture with nothing on it.**
Used by the two-state interval residual, by `widget_drawn`'s correlation, and
by every ability diff. **This cannot come from a wiki image at any quality.**
The widget is semi-transparent over live world, brightness moves with the
capture and the encode, and the whole point is to difference against the actual
values in these pixels. A clean external render is the wrong reference by
construction, not merely a mismatched one.

So the design is: **wiki art for geometry and labels, capture median for
photometry**, and they stop being one array.

**What to check before building it, because it can fail cheaply.** The wiki's
art may be a stylised top-down render rather than the same projection the game
draws in the widget. The test is one NCC alignment of a wiki image against a
session's median under a similarity transform (scale + translation only -- the
minimap is fixed/always_same/uncentered, so there is no rotation to fit).
`clip_preflight.py` already does exactly this kind of correlation against a
donor, so the machinery exists. **If it aligns at high NCC, the geometry
problem is solved for every session on that map at once. If it does not, stop
-- do not start fitting warps**, which is the shape of the failure that killed
the scoreboard-crop idea (`minimap_portrait_transform`, 24.7% against a 20%
chance rate, closed).

### The minimap's own palette and geometry, measured 2026-08-26

the player named these off footage and had never noticed the elevated shade before,
so none of it appears in any earlier measurement. What the pixels say:

* **the map has real HOLES** -- unwalkable interior bounded by the white
  lines the player says dictate them. **17.5% of the footprint on Split, 14.5% on
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

### Ability icons: what the player sees, and what it implies

Corrections he made to two guesses of mine, both worth keeping because both
were plausible and both were wrong:

* the `other_red` clusters I presented as candidate classes are **scenes, not
  marks**. A 36 px tile holds a Cypher cam AND two overlapping X marks AND a
  dropped spike AND ally portraits. The descriptor only reads a ~5 px disc so it
  was not confused, but every class I read off that sheet was an artefact of the
  tile size;
* ability icons are **not** uniformly a black-and-white glyph inside a
  team-coloured surround. Some are pure black and white with no team indication
  at all; Skye's bird and dog were the only ones the player saw with a green outline
  (plus a small directional arrow). **A pure B/W glyph is invisible to the
  current finder**, which masks on red -- those are not confounders being
  misclassified, they are undetected.

Named so far: the yellow triangle with a ringed glyph is the **dropped spike**.
The rest of the pool is dominated by X death marks.

**How team gets attributed, which is the design's load-bearing idea.** the player:
an ability's team is inferred from WHOSE ability it is -- most abilities belong
to exactly one agent -- or from the teammate it originated with. He is not sure
whether a small team indicator exists. That does not matter, because the
scoreboard already gives the full ten-agent lineup: **ability -> agent is nearly
1:1 and agent -> team is known**, so classifying the glyph attributes the team
for free. It also collapses the search space from every ability in the game to
the thirty-odd the two teams in THIS match can actually produce, and prunes by
who is alive. That is the same scoreboard read the identification work already
depends on, doing a second job.

### The ability class list has a SHAPE, and the player named it (2026-09-03)

Asked where to go after generic shape features kept failing, the player gave the
taxonomy the template bank should be built on. His words:

> There are essentially two categories of abilities: icons and regions, each
> with sub-categories depending on duration/lifetime and whether they have
> multiple modes for ally/enemy/self or controlled (and also whether they have
> portions that extend past the icon). So it is sort of a modal template
> matching but the modal part might not even be necessary if you can find the
> invariant part.

**Take this seriously: it retro-explains four separate failures already
measured in this repo, none of which was connected to the others at the time.**

* **icons vs REGIONS** explains why the shipped finder keeps missing things. It
  fits a CIRCLE, so it is an icon detector by construction -- and it cannot see
  a Sage/Viper wall (aspect 9.50), Deadlock's Barrier Mesh (multi-segment,
  variable segment count, "they can get destroyed or be up against a wall and
  very small"), or a deployed smoke. Those are regions. The standing rule *do
  NOT pre-filter the pool on shape* is the same fact discovered from the other
  end;
* **portions that extend past the icon** is the Cypher trapwire exactly: the
  icon is a small black-and-white circle and the WIRE is a separate coloured bar
  across the chokepoint. Recorded as "two independent, differently-shaped
  signals for the same object" before there was a category for it;
* **modes** is the cam turning teal while the player views through it (measured,
  H=76-77) and the unconfirmed hedge that an enemy cam turns red;
* **duration/lifetime** is what `ability_eval.py` found by accident --
  `n_observations` was being written to every candidate row and never read, and
  gating on it roughly doubled precision at no recall cost.

**Design consequence, and it is the point of writing this down: the template
bank is not flat.** It is two families, and a detector that assumes one shape
family will keep failing on the other -- which is what every generic feature
tried so far has done. Build the icon matcher first (fixed art, fixed size, one
orientation except the rotating cam) and treat regions as a separate problem
with its own primitive, rather than hoping one gate covers both.

**"Find the invariant part" is the right instinct and there is precedent.**
Where a mode changes colour, match on shape and let colour be a separate field;
where a glyph rotates, the ring is invariant and the glyph inside is not. This
is the same lesson `minimap_portrait` already paid for: pixel-wise correlation
failed across surfaces and **composition** matching transferred at 83.5%
held-out, because it threw away the layout that was not invariant. Look for the
part that survives the mode before building a bank of modes.

### The audio ring: an information boundary drawn on the widget (the player, 2026-09-03)

> There's another sort of "region", the audio range around the player, which is
> represented by sort of a white circular shadow in a fixed radius around the
> player. Again it represents the audio range for events, and also the spike
> detonation radius.

Not previously recorded anywhere here, and it is worth more than the confounder
it looks like. Three separate uses, in increasing order of value:

* **a confounder.** A large soft-edged white circle centred on the player is
  exactly the kind of thing a region detector will propose and an icon detector
  will clip corners off. It is one more reason a frame's ground truth has to
  include non-ability objects -- `paint_icons.WORLD` carries it as
  `world:audio_ring`;
* **free once measured.** It is player-anchored and FIXED radius, and the self
  track is already shipped (`reticle/minimap.py`), so after one measurement it
  is *derivable* rather than detectable -- draw it, do not look for it. Same
  class of thing as dA/ds being a property of the map rather than of the round;
* **the one that matters: it is a rendering of WHAT THE PLAYER COULD HEAR.**
  CLAUDE.md's peek section argues the minimap shows *what your team knows*
  rather than ground truth, and that this is the right basis for decision
  analysis -- you cannot be faulted for an enemy nobody had seen. The audio ring
  is the same argument for sound, drawn on screen at a known radius: an event
  inside it was audible, one outside it was not. That is an information boundary
  the pipeline can compute per frame, and it bears directly on whether a peek or
  a rotate was justified.

**2026-09-05, the player: THE AUDIO RADIUS IS ONLY DRAWN WHILE YOU ARE MAKING
STEPS.** *The audio radius seems to only be visible while you're making steps.*

That reverses the ring's status twice over and neither reading is obvious from
a crop:

* **as a confounder it is cheaper than assumed.** It is not a permanent
  annotation to be subtracted, it is intermittent -- so a candidate at the
  player's own radius is only contaminated on the frames where he was moving
  audibly, and the ring's ABSENCE across a still window is not a detection
  failure to be chased;
* **as a signal it is worth far more than assumed, because it is a
  MEASUREMENT OF THE PLAYER'S OWN NOISE.** Walking, running and crouching
  differ in how loud they are, and this ring is the game stating, per frame,
  whether the player was audible at all. Nothing else in the capture says that.
  Silent movement is the whole content of "was that peek telegraphed", and it
  needs no new ROI -- the ring is already in the widget.

**ANSWERED the same day, by the player, with the clip (`2026-09-05 18-44-09.mp4`):
ONLY RUNNING MAKES NOISE AND ACTIVATES THE VISIBLE AUDIO RADIUS.** Walking and
crouching draw nothing.

So it is BINARY, not a variable radius -- and that is the better outcome of the
two, because it makes the ring a direct readout rather than a measurement to
calibrate:

    ring drawn        the player is RUNNING, and is audible at that radius
    ring absent       walking, crouching, or standing still -- inaudible

**Combined with the shipped self track it separates the two absences, and that
is the signal worth having.** Speed comes free from `reticle/minimap.py`, so:

    moving + ring       running: the peek was TELEGRAPHED
    moving + no ring    walking or crouching: DELIBERATE silence
    still + no ring     holding

The middle row is the one nothing else in the capture can see. CLAUDE.md's peek
section argues the whole point is whether an approach gave information away;
this is the game stating it per frame. It needs no new ROI and no classifier --
the ring is already in the widget and the track is already stored.

**MEASURED off that clip, same day: the ring radius is 94-95 px, about 19 m**
at the widget's ~0.2 m/px. It separates cleanly rather than by a fitted edge --
running frames score an angular-median brightness lift of 3-12 at r = 91-103,
and every non-running frame scores exactly 0.00:

    7.5 - 8.0 s     r 95      lift 3-10
    10.0 - 13.5 s   r 93-103  lift 6-12
    everything else  --       lift 0.00

Two things about HOW it was measured, both of which the first attempt got wrong
and both of which recur:

* **the peak is the player's own icon unless you exclude it.** A radial profile
  from r=8 reports r=8 on every frame at a lift of ~60, ring or not. Start past
  the icon and its facing triangle;
* **use the angular MEDIAN, not the mean.** The vision cone is a wedge over
  roughly a third of the angles and drags a mean at every radius; the ring is
  the only thing that lifts ALL directions at one radius. Requiring the band to
  span at least half the angular bins is the same test from the other side.
  This is the module's own recurring shape -- measure the property that
  separates the two things, not a threshold on what they share.

At ~19 m this is also plausible against the game: Valorant's run-footstep
audibility is usually put at around 20 m. That is corroboration, not a source.

Note the asymmetry before building on it: ring-present is a POSITIVE claim
about audibility, ring-absent is the union of three states and only becomes
"deliberately silent" once the self track says the player was moving. Do not
read absence alone as quiet play.

**And it doubles as the spike's detonation radius**, which is immediately usable:
post-plant, whether the player stood inside the lethal circle is a fact about a
round that `rounds.py` already knows the phase of.

Unmeasured so far: the radius itself, in minimap pixels and in metres. The
region pass is the cheapest way to get it -- paint the circle once or twice and
read it off, rather than deriving it.

**2026-09-04, mid-labelling, the player: ABILITIES DRAW RADIUS RINGS TOO, and they
look like the audio ring.** Killjoy candidates 8-10 of `dae6f33f3f48` are the
*active radius* of her devices, and his verdict on how to label them:

> visually [they] are very similar to the audio radius around the player. But it
> wouldn't be entirely accurate to call that an ability

This upgrades the audio ring from confounder to one member of a CLASS of
concentric ring annotations, and it changes two things.

**It is a third label class, not a positive and not a negative.** Marking a
radius ring `not_ability` poisons the negative class with something an ability
genuinely caused; giving it an ability name trains the detector to fire on
annotations rather than objects. It gets its own category -- `agent=""`,
`ability="radius_ring"`, following the cross-agent convention that made all
deployed smokes one category -- and because `category_id` is on every row,
scoring includes or excludes it per metric. Same pattern as revive and wallbang
kills in the root `CLAUDE.md`.

**The two kinds are separable by ANCHOR even when they are identical in a crop.**
The audio ring is player-anchored at fixed radius; a device's active radius is
anchored to the device and does not move when the player does. So `self_d` in
the Phase 1 series decides it -- a player-centred ring holds a constant distance
from the self icon across its whole window, a device-centred one does not. That
is worth knowing before anyone tries to separate them by appearance, which is
the expensive way to fail: **a distinction the player cannot make by eye may still be
recoverable from the track.**

It also means the "derive it, do not detect it" argument above now has a
counterexample beside it. The audio ring is derivable once its radius is known.
An ability's active radius is not -- it depends on which device is placed and
where -- so the two must not be handled by one rule despite looking the same.

**the player confirms the anchor, and narrows the class to TWO AGENTS.** The device
radius does stay constant, and *"Killjoy and Chamber are the only agents I can
think of with that mechanic."* That is a strong prior and it is worth stating as
a filter: on the one-agent-per-clip demo corpus only `dae6f33f3f48` (Killjoy)
and `ccff4a11ff5a` (Chamber) can produce a device radius at all, so a ring in any
other clip is the audio ring, a smoke edge, or a false positive.

**Checked against the reference, and it is NOT derivable -- keep it as the.**
`ability_reference` has no structured field for a leash. The descriptions only
hint: Killjoy's Alarmbot and Turret mention "in range" and "recall", Chamber's
Rendezvous mentions "in range of the anchor". Worse, a keyword sweep for range
language also catches Chamber's Trademark (*"when a visible enemy comes in
range"*), which is a DETECTION radius and a different mechanic -- so the obvious
automatic extraction of this fact produces a wrong third class.

### EVERY ABILITY HAS AN EQUIP SOUND AND A CAST SOUND, AND EQUIP IS SELF-ONLY

**the player, 2026-09-06:** *there is a separate equip and cast sound for each
ability. Not positive there is one for literally every ability but I would
guess there is. The equip sound is only for the self agent.*

**Self-only is the load-bearing half**, and it changes what the audio channel
is for. Every other audio target discussed here -- ultimate voicelines, cast
SFX -- is spatialised and can come from anybody, which is why
`BACKLOG.md`'s analysis-by-synthesis entry has to caveat that a fixed
dictionary only fits the local player's near-field casts. **An equip sound is
near-field BY DEFINITION**: it exists only for the agent holding the mouse. So
it is the one audio event with no spatialisation to model, no HRTF filter to
undo, and no ambiguity about whose it is.

Four consequences:

* **it is the cleanest possible first dictionary entry.** The backlog names the
  local player's own casts as the clean case to start from; this is a strictly
  cleaner case inside it;
* **it PRECEDES the cast**, so the pair is a two-event signature rather than
  one sound -- far stronger for a matched filter than either alone, and the
  interval between them is the hold/aim time, which is a real quantity nothing
  in this pipeline currently measures;
* **it pairs with the SUBMENU below, and the two are mutual controls.** The
  submenu is drawn when an ability is pulled out; the equip sound plays at the
  same moment. One is visual and one is acoustic, they fail for unrelated
  reasons, and either one confirms the other -- which is the strongest
  validation structure this repo has (the same shape as the killfeed anchor and
  the camera-pan facing check);
* **it bounds the tray.** `ability_hud` reads the charge AFTER the cast; equip
  brackets it from the other side, so a cast is a sound, a submenu, and a drop
  in a known order rather than one threshold crossing.

**Unverified and stated as such: "not positive there is one for literally every
ability".** Treat coverage as unknown per ability until measured, and remember
the demo corpus can only establish it for abilities the player could cast solo --
the kill-gated and ally-gated kits are UNTESTED here, same as for the icons.

### THE ABILITY SUBMENU AND ITS ON-HOVER PROMPTS (the player, 2026-09-06)

> When pulling out the ability there is basically a submenu above it with
> icons. For yoru e as an example there is a left click icon and a track
> indicating to move it forward and a right click icon with an arrow pointing
> at the ground icon to indicate placing it on the ground. Then when you mouse
> over the teleport location, whether through a wall or not, an F key icon with
> fake shows up, onhover basically. There are a variety of these on-hover icons
> and ability submenus that maybe could have the domain knowledge inferred
> from.

**This is a surface nothing in the repo has ever read, and for the fake/real
problem it may beat audio outright.** The whole reason audio was named as
necessary is that Yoru's fake plays the teleport sound without the
displacement, so sound cannot separate them. **A prompt that says `F fake` is
the game naming the choice on screen**, in text, before it is taken.

Four reasons it is worth more than another SFX:

* **it is a small closed set of fixed art at a fixed screen position**, which
  is the shape every reader in this repo that works has had -- digit templates,
  agent-name bitmaps, the 25 killfeed name glyphs. The submenu is drawn above
  the tray, so the ROI is adjacent to `ability_hud`'s and the reader can join
  that pass rather than opening its own decode;
* **it states the MODE BEFORE the cast**, where the tray states the charge
  AFTER it. That is a precondition rather than a consequence, and it is the
  first thing in this pipeline that would be;
* **it is self-documenting.** the point -- the domain knowledge could
  be inferred FROM it. A submenu enumerating left-click, right-click and F for
  one ability is the game listing that ability's modes, which is exactly the
  `modes` axis of his taxonomy that this file has been filling in by asking
  him. Reading it turns a per-agent interview into a per-clip measurement;
* **it is LOCAL-PLAYER ONLY**, like the drone HUD overlay -- a limit, not a
  defect, and the same half of the event log.

Two cautions before building it. **On-hover means it is conditional on where he
is pointing**, so its absence is no evidence -- the same one-sided rule as the
enemy X mark and the missing tray drop. And an *available* prompt is not a
*taken* action: `F fake` appearing says the fake was OFFERED, and only the
keypress or its consequence says it happened. Pair it with the position track
rather than reading it alone.

**RENDERED AND CONFIRMED the same day, on `5a63cc4fecfc` at the Yoru E casts,
region x 731-1186 y 900-1062 (the band above `ability_hud`'s bar at y 1032):**

* at **18.00 s** the submenu appears above slot E as **two mouse-button glyphs
  side by side**, white line art on dark -- left-click and right-click, exactly
  as described;
* at **18.40 s** the on-hover prompt reads **`F ⟋ FAKE`** in literal, legible
  capitals beside an F-key glyph, with the rift orb lit in the world;
* an **`E` key glyph with a yellow underline** marks the ability as equipped,
  and it is present at 18.40 s and again at 26.50 s;
* the **ultimate's pips are visible** as a row of evenly spaced teal marks
  under slot X at **y = 1037, pitch 8.0 px**, directly above the charge bar.

**`FAKE` is rendered as a WORD.** That is a far easier target than anything
else in this repo -- larger than a killfeed name glyph, at a fixed position, in
a closed set -- and it means the fake/real distinction may be readable from the
HUD without audio at all. The caution above still applies unchanged: the prompt
says the fake was OFFERED, not taken.

### Abilities have PLACEMENT MODES, and only for your own agent (the player, 2026-09-04)

> quite a few abilities have different colors/modes while being placed, so that's
> sort of a modal thing. It would only apply to the player's current agent

Three consequences, and the first is the one that has already cost this project
a technique once.

* **it is an APPEARANCE-MODES problem, the exact shape that killed single-template
  matching.** One template per agent scored 41.8% against a gallery's 88.6%
  precisely because a class with several appearances cannot be one exemplar. If
  placement preview and deployed device are both labelled `turret`, that category
  is bimodal by construction, and any centroid, median template or single
  threshold fitted to it sits between two modes and matches neither;
* **a preview is PROOF the object is the local player's.** Enemies never render
  their placement previews on your minimap, so in a real match -- where the demo
  corpus's solo assumption breaks -- preview mode is a free ally/self attribution
  signal, not just a nuisance;
* **the mode does not need to be labelled, because it is RECOVERABLE.** The tray
  says whether an ability is currently equipped, and every label row carries
  `(t_ms, x, y)`, so mode can be recomputed for rows already answered -- the same
  property that let host span and top-hat peak be applied to 154 existing rows
  for free. `ability_hud.py` has the tray geometry already, though it currently
  reads charge FILL rather than equipped state, so this is an addition to a
  working reader rather than a new surface. **Do not ask the player to label a mode he
  can only guess at when the HUD states it outright.**

**The first one found is a CONE, and that breaks an assumption.** the player, naming
the category while labelling: *"I'm naming one for the turret `place_color`. It's
a green vision cone of the turret."*

That is the **third** cone known to be drawn on this widget -- the player's own,
Tejo's (recorded above, 2026-09-03), and now Killjoy's turret during placement --
and it collides head-on with a class this project has treated as pure noise.
*"Fragments of viewcone"* is one of the two false-positive classes the player named
from the gallery, and every cone feature is built on `minimap_cone.self_cone()`,
which fits THE cone, singular, anchored at the player. A turret placement cone is
cone-shaped, fragments the same way, and is **positive evidence of an ability**.

So "cone-shaped therefore not an ability" is false, and two things follow:

* it is a candidate explanation for why `cone_cond` failed as a gate (0.40
  pooled, 2 of 4 sessions) while still carrying orthogonal signal among gate
  survivors. A feature keyed to the player's cone is being asked about frames
  where a *different* cone is the thing on screen;
* `self_cone()` fitting one cone anchored at the player is now a known
  incompleteness, not just a simplification. Nothing yet reads a cone that is
  anchored somewhere else.

On the name: the category registry is GLOBAL across agents and sessions, and
rows store `category_id`, so a name reused later for a different agent's
placement mode cannot be split apart afterwards. `place_color` will read as
generic once a second agent has one. Not worth interrupting a pass to change --
but if a Chamber or Vyse placement mode turns up, give it its own name rather
than reusing this one.

This also gives a candidate mechanism for a measured result nobody had explained:
`n_runs` is INVERTED in `ability_features.py` -- real abilities produce FEWER
contiguous detection runs than false positives. A preview that resolves into a
deployment is one object appearing twice with a gap, which would push a real
ability's run count UP, not down. So either previews are rare in the labelled
set, or they are being detected as separate candidates rather than one track.
Worth checking against the new labels before trusting either reading.

### The one-agent-per-clip demo corpus, recorded 2026-09-03

the player recorded a sitting of controlled clips on **Ascent**, one agent each, on
an alt account with every agent unlocked, custom game, infinite abilities ON.
Ingested `valorant-16x9-bigmap`, tagged `ability-demo,<agent>`. This is the
template-bank ground truth the candidate-anchored label store structurally
cannot give: the player knows what he cast, so the labels are free and exact.

**Check every clip with `prototypes/clip_preflight.py` BEFORE ingesting.** The
first take of the sitting was recorded with minimap orientation left on
side-based, so the entire widget was rotated 180 degrees -- checklist item 8,
the setting that breaks silently, arriving for real. Nothing downstream would
have said so; the map simply would not have matched Ascent's geometry. Caught
in one render, and the same check then cleared fifteen more clips in seconds.

Two limits on what a solo custom game can record, both from the player, neither
recoverable from the footage:

* **some abilities cannot be demonstrated alone.** Clove's clip is 20s because
  two of her abilities require KILLS. Any agent whose kit is conditioned on
  kills, deaths or teammates is under-covered by this corpus by construction,
  and a class missing from it is not evidence the class draws nothing;
* **infinite abilities makes the ability TRAY unreadable** (already recorded
  below): a demo clip is the worst place to read cast times and the best place
  to read artwork. Do not try to get both from one clip.

**THE NEGATIVE CLASS IS LARGE, and the player named its shape (2026-09-03):**

> There are actually quite a few abilities with no icons. Grenades, flashes,
> molotovs are the most common.

Take that as a structural claim about the class list, not a footnote. It says
the icon/region taxonomy covers PLACED and PERSISTENT things, and that a whole
family -- thrown, instantaneous, or short-lived damage and blind utility -- is
simply absent from the widget. Consequences, in order of how much they change
what to build:

* **the class list is far smaller than the ~110 agent-ability pairs**, so
  enumerating it is tractable and a template bank is a realistic object;
* **a missing detection is often correct.** Any recall figure computed over
  "abilities cast" rather than "abilities that DRAW something" is wrong by
  however large this family is, and it would look like a detector defect;
* **audio is the only channel for these.** This is the strongest argument yet
  for the matched-filter work in NOTES: the events with no minimap footprint
  are exactly the ones that must come from sound, and they are common ones
  (a flash before a peek bears directly on a duel);
* **it can only be established by controlled clips.** Mining footage can never
  distinguish "this ability draws nothing" from "no one cast it, or we missed
  it".

The first instance measured: **Neon's E (High Gear -- speed and slide) has NO
minimap icon.** the player said so unprompted after a bright vertical band down the
left edge of the frame tripped the pre-flight's bounding box -- that band is
the ability's own screen effect, and the widget shows nothing. Same class of
fact as *ult orbs have no minimap icon*.

**The recording protocol closes that gap, and the player stated it (2026-09-03):
every ability is cast in every clip, and after the first couple of clips, cast
IN ORDER.** Both halves are load-bearing and neither is recoverable from the
pixels:

* **every ability cast** makes absence informative. An agent's kit is a known
  closed set, so "cast four, found two icons" is direct evidence that the other
  two draw nothing -- the negative class becomes free rather than needing its
  own labelling pass. **But it is every ability he CAN cast, and that is the
  whole caveat.** the player, correcting the sentence above: Clove needs a KILL for
  two abilities and a DEATH for her ultimate; Reyna's need kills as well. So a
  missing icon has TWO possible causes -- the ability draws nothing, or it was
  never castable solo -- and they are not separable from the footage. Treat
  kill/death-gated abilities as UNTESTED, never as negatives. Getting this
  wrong would put a real icon class into the negative list permanently, which
  is the population trap this repo has already paid for twice;
* **cast in order** makes identity largely derivable. The icons that appear
  form a SUBSEQUENCE of the agent's ability order, so the k-th icon is not
  necessarily the k-th ability, but the relative order is fixed. That is a
  strong prior over a small closed set, and it costs the player nothing.

Two cautions before leaning on the ordering. It does NOT give cast times --
infinite abilities makes the tray unreadable, so the only anchor is the icon's
own first appearance, which lags the cast by however long the projectile takes.
And "after the first couple" means SOME early clip may be UNORDERED; applying
the prior to it would silently mislabel.

**Which ones is OPEN, and recollection is the wrong instrument for it.** Asked,
the player first said Tejo (`c0b63335e635`) and Viper (`6bb88dba5d2c`), then revised
to Viper probably being in order and Tejo possibly too. That is not a
contradiction to resolve by asking a third time -- it is a memory of a detail
that was never deliberate at the time, and the answer is in the footage.

**Verify it instead, and the check is nearly free.** Every agent's kit is a
known closed set and the icons that appear are a subsequence of the cast order,
so once a clip's icons are detected and identified, the observed sequence
either is or is not consistent with the slot order. Run that test on all of
them rather than trusting any clip's ordering: it costs one comparison per
clip, it covers the ones nobody is unsure about, and it would also catch a
mis-tagged agent. Until it has run, treat the ordering prior as UNVERIFIED
everywhere rather than as verified for seventeen clips and doubtful for two.

**Per-agent gating known so far** -- extend this as it is found, because an
absent icon means nothing without it:

    clove    two abilities need a KILL; the ultimate needs a DEATH
    reyna    abilities need KILLS (soul orbs)
    sage     E needs an ALLY WHO HAS TAKEN DAMAGE; the ultimate needs a DEAD ALLY

Sage is the sharpest case so far and worth stating in full, because it shows
the gating is not a minor asterisk: only her two ORB abilities are castable
solo, and both are REGIONS -- the wall is the multi-segment object already
recorded at aspect 9.50. So her clip is evidence about regions and says
NOTHING about her other two, in either direction.

Note also that the gate is not always "needs a kill": Sage's is an ally state,
and an ally who has taken damage is unobtainable in a solo custom game for a
different reason than a kill is. Do not encode this as one flag.

**And there are TWO kinds of gate, which must not be collapsed.** the player, with
the Skye clip: her ultimate *requires enemies to be alive to track*. That is
not "cannot cast" -- the ult goes off and the seekers exist. It is **cast but
UNREPRESENTATIVE**: with nothing to track, a seeker will not travel the way it
does in a real round.

    NOT CASTABLE     no observation at all. Absence is uninformative.
                     clove, reyna, sage
    CASTABLE BUT     the ARTWORK is valid -- an icon's appearance does not
    UNREPRESENTATIVE depend on there being a target. Its MOTION, LIFETIME and
                     final position do not transfer.
                     skye's ultimate

The distinction is load-bearing because the two families of evidence this
corpus produces are affected differently. A template bank built on artwork can
use an unrepresentative cast; anything using `n_observations`, `duration_ms` or
the translation invariant cannot. `ability_eval`'s lifetime gate is exactly the
second kind, and it is the feature that doubled precision -- so feeding it a
solo-cast seeker would poison the number that currently works best.

**Corrected immediately, and the correction is the useful part.** The first
version of this note extended the caution to "any moving icon cast with no
target". the player, on the Sova clip: *Sova drone is controlled by the player, I
flew it around* -- and then, unprompted, *same with fade dogs* and *and skye
dog and birds*. So PILOTED utility is the norm and autonomous seeking is the
exception:

    piloted by the player, motion IS representative
        sova    drone
        fade    prowler ("dogs")
        skye    trailblazer ("dog"), and the birds
    autonomous, needs a target to behave normally
        skye    ultimate (seekers)

That inverts the practical consequence. The corpus DOES contain valid moving-
icon data -- several clips of it, deliberately flown -- which is the first of
its kind here and directly relevant to the translation invariant, since
`motion()` currently rests on "a placed ability never translates" with the Omen
smoke as its only known counterexample. A piloted drone is a second, and one
that translates for its whole lifetime rather than briefly.

The generalisation was mine and it was wrong in the direction that would have
discarded good data. Ask which specific abilities are autonomous rather than
inferring it from "it moves".

Both clips are short for exactly this reason (`28f53bfddbbe` 0:20,
`af09094c0729` 0:24), so clip LENGTH is itself a hint that a kit was only
partly exercised.

**Contamination is REAL in these clips and it is the player, not the ability.**
`c0b63335e635` (Tejo, 38s) disagrees with the full Ascent match's geometry on
2.07% of the ROI, and the largest blob is 2271 px at (215,183), 45x107,
classified `box edge` in the clip where the match says `floor`. That is the
own icon and vision cone, stationary long enough to survive the median and be
baked in as map structure. Smaller blobs are the callout text along the top
edge. The capture-side fix is to KEEP MOVING while placing; the post-hoc fix is
to borrow the full match's geometry, for which see the next note.

**Borrowing measured, not assumed.** `--geometry-from a06f04a0059f` against
the clip's own `--two-state-from` build, `ability_disc.find_discs` over 40
frames of `c0b63335e635`:

    geometry-from     1.00 candidates/frame   mean area 93.9
    two-state-from    0.78 candidates/frame   mean area 94.4

The `2ba870ccbd50` symptom was LARGE, LONG-LIVED false positives, so identical
mean area is the reassuring number and the rate difference is small. Read the
direction carefully rather than as a cost: the contaminated build proposes
FEWER because the parked cone is baked into it as map structure, so
`searchable()` masks out exactly the region he was placing abilities in. Fewer
candidates there is a recall loss disguised as a precision win.

**A donor's lighting reference IS transferable between recordings, measured.**
NOTES has `--geometry-from` down as unresolved -- it fixed contamination on
`2ba870ccbd50` but introduced large false positives from a pixel-value mismatch
between recordings that was never root caused. Tested directly here, medianing
the raw widget from each recording and comparing gray on the 73061 pixels the
donor calls floor:

    clip                     mean|d|   p95|d|    bias
    c0b63335e635 (Tejo)         3.72     18.0   +3.57
    6bb88dba5d2c (Viper)        2.31     15.0   +2.15

Small, and a consistent slight positive bias. So a different account, a
different day and a different encode still put the same map pixel at nearly the
same value, and the `2ba870ccbd50` failure was NOT a general property of
borrowing across recordings. **Do not read this as a clearance for that
session** -- it says the mechanism blamed there is absent HERE, on Ascent, on
these clips; `2ba870ccbd50` is a different map and profile and remains
unexplained.

Caution on how this was measured, because it nearly went the other way: the
same comparison run on the two sessions' STORED `lo_gray`/`hi_gray` gives mean
12.1 / p95 45.0, three times worse, and would have said the opposite. Those
arrays are cluster centres computed from different frame counts by different
runs, so they differ for reasons that have nothing to do with the recordings.
Compare the RAW medians when the question is about the recordings.

### Tejo's kit, and a SECOND vision cone on the widget (the player, 2026-09-03)

Asked what the pale wedge in `c0b63335e635` at t=28350 ms is:

    C   a CONTROLLABLE DRONE. The wedge is the drone's own HUD on the widget
    Q   a stunning and damaging GRENADE
    E   a charged, STAGED MOLOTOV -- damages an area in PULSES, deployed
        through an "iPad"-like map interface, as many smoke agents do
    X   like E but in a LINE: pulses of damage from origin to end, one-shots
        anyone standing in it

Four consequences, and the first is the important one:

* **IT IS AN OVERLAY THAT OVERLAPS THE MINIMAP, AND MUST NOT BE READ AS
  MINIMAP CONTENT.** the player, correcting a first reading of it as the ability's
  "minimap presence": *well it's an overlay, it just overlaps the minimap* ...
  *but it shouldn't be interpreted as being on the minimap.* Confirmed by
  rendering the whole frame with the ROI outlined -- the wedge sits inside the
  minimap ROI, drawn near the self icon, while the drone's other UI (a large
  golden circular map) sits centre-screen and clear of it.

  **That combination is the dangerous one**: it occupies minimap pixels without
  being minimap content, so every candidate it produces gets a confident world
  position through the homography that means nothing at all. It is the same
  class of hazard as the shooting-error box over the killfeed -- an occluder --
  except that here the occluder is itself icon-coloured and moves, so it looks
  exactly like a find. The seven fragments at t=28350 are a real detection of a
  real ability and a WRONG position, simultaneously.

  **But do not stop at masking it, because the player inverted this immediately:**
  *there would only be a hud like that if a player ability is currently active,
  and the cause can be known, there are only a few.*

  So the overlay is an EVENT, not just a nuisance. Three things follow and they
  are the most useful consequence of the whole Tejo thread:

  * **its presence means the local player has an ability ACTIVE**, with a start
    and an end read directly off the pixels -- that is a cast time and a
    duration, which is exactly what `ability_hud.py`'s tray was built to give
    and cannot in these clips, because infinite abilities pins the tray full;
  * **the cause is identifiable from a SMALL CLOSED SET.** Only a few abilities
    draw a HUD of this kind, so this is a bounded classification, not an open
    one -- the same shape as the digit templates and the twenty-five agent-name
    bitmaps, both of which worked;
  * **it is the LOCAL player only.** An ally's or enemy's active ability draws
    nothing on the HUD, so this channel is about his own actions. That is a
    limit, not a defect: his own casts are the half of the event log that feeds
    the self track and the duel context around it.

  Treat it as: recognise the overlay, emit "<ability> active from t0 to t1",
  and mask the widget region for its duration. The mask is a side effect of the
  identification, not the goal.

  And a caution for
  `prototypes/minimap_cone.py`, which fits one cone seeded from the largest
  `self_rings` ring: a drone wedge drawn over the widget is a second wedge the
  fit can lock onto. `CONE_HALF_ANGLE_DEG=56` was measured on 23 samples from
  one clip that may or may not have contained a drone -- worth re-checking
  before that constant is trusted further;
* **the 7-fragment object at t=28350 detects a real ability at a meaningless
  place.** The scan found the C ability -- so it is not noise -- but as an
  overlay its position is screen-space, not map-space. "True positive" was the
  first reading here and it was too generous by half;
* **`E` and `X` PULSE.** A region that appears, vanishes and reappears in place
  breaks lifetime reasoning in a specific way: `n_observations` and
  `duration_ms` will see one pulsing ability as several short-lived objects at
  one position, and the onset-grouping proposed for fragments will split them
  by design, since each pulse is a fresh onset. Grouping needs a notion of
  "same place, repeating" as well as "same instant, adjacent";
* **the "iPad" deployment is a large map interface** used by Tejo, Brimstone,
  Astra and others. While it is open the player is not looking at the world, so
  main-view metrics are invalid for those frames -- the same class of exclusion
  as spectating, and nothing detects it either. **ANSWERED, not left open: it
  is an overlay and it draws centre-screen**, clear of the minimap ROI on
  `c0b63335e635` -- so it is a main-view problem, not a minimap one.

### First scan of the demo corpus: candidates are not events (2026-09-03)

26 clips rebuilt with `--geometry-from a06f04a0059f` (which removes the parked
vision cone the clips' own medians bake in) and scanned with
`scan_ability_clip.py`. First numbers, and the shape of the problem:

    c0b63335e635 tejo    45 candidates -> 28 events   4 fragmented into >=3
    c7674c699ad0 astra   43 candidates -> 33 events   1 fragmented into >=3
    a7ce88bf341c breach  50 candidates

**A candidate is not an object, and an object is not an event.** The clearest
case is Tejo at t=28350 ms: SEVEN candidates share that onset within 300 ms and
sit adjacent (x 227-270, y 230-319). Rendering the widget there shows why --
one large pale wedge appears and the blob detector proposes pieces of its edge.
That is the icon-vs-region split in the taxonomy, arriving as a measurement:
an icon detector run over a region returns the region's fragments.

**the player identified that wedge as his DRONE's HUD -- his C ability -- so those
seven fragments are a TRUE POSITIVE**, and the failure is representation
rather than detection. See the Tejo section above.

**Grouping on (shared onset, adjacency) is the cheap fix and it belongs before
the labeller.** Asking the player about seven fragments of one object spends his
time seven times for one answer, and it also breaks the arithmetic -- a
per-candidate precision figure counts one real object as seven.

**`self_icon_dist` explains a large share of what remains**, as it did when it
was first built:

    tejo    17 of 45 candidates within 20 px of the self icon (38%)
    astra   12 of 43 -- but 25 rows have self_icon_dist NULL

The null rate on Astra is its own defect: the feature is only computable where
`minimap.self_rings` finds the player, so on the clips where it does not, the
strongest available filter is simply absent rather than negative. Fixing that
is worth more than another shape feature.

**Read the first render honestly, because the first reading of it was wrong.**
The contact sheet shows many panels of pale yellow chevron texture and they
look exactly like static map hatching; the conclusion drawn from the sheet
alone was "mostly map texture, ~15% precision". The candidate TABLE then showed
those panels share one onset, and the rendered frames showed a live object
appearing at that instant. **A contact sheet of crops cannot distinguish a
static texture from a large object seen through small windows** -- it has no
time axis and no context. Look at the whole widget over time before judging a
scan's output, not only the crops it proposes.

### `self_icon_dist` is NULL for a SAMPLING reason, not a detection one

the player, on the ranked corpus: *I thought we had template matching for player
minimap icons working?* Worth answering precisely, because the answer is a bug.

**What exists.** `minimap_portrait` does composition matching (83.5% held-out,
88.6% leave-one-out over five agents) -- but that IDENTIFIES which agent an
icon is, given a location. Finding the location is `reticle.minimap.self_rings`
/ `ally_rings`, and `minimap_ring_fit` for enemies. `self_rings` is not template
matching at all: it is an absolute BGR threshold on the self colour,
intersected with `floor_mask`.

**Measured, so the obvious suspects can be dropped.** 60 frames per clip:

    session       agent     self_rings ok   without the floor gate
    c0b63335e635  tejo         100.0%              100.0%
    dae6f33f3f48  killjoy       96.7%               96.7%
    64d0fb783be2  vyse          95.0%               95.0%
    c7674c699ad0  astra         70.0%               71.7%

The floor gate costs 1.7% at worst and is NOT the problem, and the colour gate
finds the player in 70-100% of frames. Neither explains `self_icon_dist` being
NULL on 25 of Astra's 43 candidate rows (58%).

**The real cause: it is computed ONCE, at the track's BIRTH frame**
(`scan_ability_clip.py`, in the branch that opens a new track) and never
updated. One frame where `self_rings` misses sets the field NULL for that whole
track, however many later frames would have answered.

**And the two failures are CORRELATED, which is why 58% > 30%.** A candidate is
disproportionately born in a frame where something is covering the widget -- an
ability, an overlay, a flash -- and that is exactly when the self colour is
hidden too. So the sampling takes its one measurement at the moment it is least
likely to succeed. That is worse than random sampling, not equivalent to it.

**Fix: take the min over the track's frames, not the birth frame.** The feature
already earns its keep -- the reading of the gallery is that the bottom band
is cleanly player icons -- so this is coverage, and the cheapest real gain in
this channel. **Generalise it**: any per-track feature measured at one frame
inherits that frame's failures, and a track has many frames precisely so it
does not have to.

### The ranked corpus FAILED, and the player named the two survivors (2026-09-03)

713 events across 23 demo clips were grouped, scored and published as a gallery
ordered weakest-to-strongest (`prototypes/ability_corpus.py`). the verdict
on it:

> a lot of those examples are still essentially fragments of viewcone or tiny
> cracks in the minimap

**But he also said, of the other end of the same gallery:**

> all the weakest examples shown are either literally only player icons or very
> close to player icons

**Those two sentences together are a much sharper result than either alone, and
they SPLIT the four signals rather than condemning them.** The bottom band is
clean and homogeneous -- it is player icons, and nothing else. So
`self_icon_dist` WORKS, and it is the one signal here that demonstrably
transferred from the two Cypher clips to twenty-three agents. The failure is
narrower than "the score does not separate": it separates player icons from
everything else, and then fails to separate ABILITIES from CONE FRAGMENTS and
CRACKS, which is a different and harder cut that lifetime, onset and geometry
class carry no information about.

Two consequences for the next attempt:

* **keep `self_icon_dist` and fix its NULL case** -- it is null on 25 of
  Astra's 43 rows, wherever `minimap.self_rings` misses the player, and on
  those rows the one working filter is simply absent. That is the highest-value
  repair available and it is a coverage bug, not a modelling problem;
* **stop adding weight to lifetime, onset and geometry class for this cut.**
  Each was measured honestly on mostly Cypher trapwires over two clips, and a
  weighted sum of features that do not separate the classes you care about does
  not separate them either -- it only makes the failure harder to see. This is
  the "ground truth from the same population" rule again, and the ranking
  inherited it.

**The two surviving false-positive classes, in the words, and both are
things we can already MODEL:**

* **viewcone fragments** -- the cone clipping a corner, already the known
  nuisance that `host span` was invented for and that `minimap_cone.py` fits
  directly;
* **"tiny cracks in the minimap"** -- thin dark features of the static map
  itself. A NEW name for something this channel has produced all along, and a
  better one than "line-work artefacts", because it says where they come from.

**A hypothesis worth testing first, because it explains why the onset signal
did not remove the cracks.** A crack is static, so it should have no onset and
should have scored badly -- yet cracks are in the top band. The likely reason:
a crack is invisible on unlit ground and becomes visible when the cone sweeps
over it, so it acquires a FALSE onset, at a fixed position, correlated with
cone presence. If that is right, the discriminator is not a shape feature at
all: **does this candidate's appearance correlate with the cone covering it?**
Static position plus cone-correlated visibility is a crack; an ability is
neither.

Note what that is NOT. `prototypes/ability_cone.py` already tried using the
cone as a REFERENCE for expected pixel values and it did not beat the plain
interval residual ("a more permissive reference lifts the noise as much as the
signal"). This is a different question -- correlation of APPEARANCE with cone
COVERAGE over time, not a per-pixel reference level -- and it needs the cone
fit, which is now known to answer on 89% of frames rather than the 4-of-50
that shelved it.

**And it is the reframe already written in NOTES, arriving with evidence:**
stop classifying blobs, explain the frame. Both survivors are layers we can
model -- the static map and the cone -- so they should be SUBTRACTED, not
filtered after the fact by a feature that hopes to correlate with them.

### The untried temporal space, and why it is the right direction

the player, 2026-09-03: *what other temporal techniques do we have that we haven't
tried yet? I think that's the direction probably next, along with audio.*

**The inventory first, because it makes the gap obvious. Every temporal feature
in this repo is a SCALAR SUMMARY of a track:**

    drawn() / usable()          is the widget rendered at all
    n_observations, duration_ms how long a track lived
    motion(), keep_from()       how far it moved, whether it rotated
    link()                      which per-frame blobs are one track
    static_gray, two_state_gray per-pixel median / bimodal level over time
    per-pixel temporal SD       measured once, on 2026-08-26, to EXPLAIN the
                                searchable area -- never used as a feature

**Nothing anywhere looks at the SHAPE of a signal over time.** That is the
entire untried space, and both surviving false-positive classes live in it.

**1. Correlate a candidate against something else that varies over time.** The
strongest family, because both survivors are caused by things already
computable.

* **visibility vs CONE COVERAGE** -- a crack is invisible on unlit ground and
  appears when the cone sweeps it, so its appearances should correlate with
  cone coverage at its own pixel; an ability's should not. `minimap_cone.py`
  answers on 89% of frames. **Distinct from `ability_cone.py`**, which used the
  cone as a per-pixel reference LEVEL and did not beat the plain interval
  residual -- this is correlation of APPEARANCE with COVERAGE over time;
* **position vs the SELF TRACK** -- anything player-anchored moves with him:
  the drone HUD overlay, the audio ring, Vyse's ultimate. Correlating a
  candidate's position series against the shipped self track marks those
  DERIVABLE rather than detectable, and it kills the overlay class that all
  four of the corpus ranking's signals are blind to.

**2. Look at the candidate's own signal instead of summarising it.**

* **intra-patch temporal variance** turns the animation observation into a
  POSITIVE feature. A crack, once lit, is static -- near-zero variance within
  its own patch. An animating ultimate is high. That separates exactly the two
  classes lifetime cannot, using one measurement read in both directions;
* **repeat structure at a position** -- how many SEPARATE onsets occur at one
  pixel across a clip. A placed device: one. A crack: one per cone sweep. A
  pulsing ability (Tejo's E and X): a regular period. This also closes the
  pulse-grouping gap `ability_corpus.py` documents.

**3. Normalise by temporal noise rather than thresholding.** The per-pixel SD
map is already measured and NOTES already names it as the divisor for the 8x
contrast spread between Orbital Strike (median dark 13) and the sensors (95-105).
Still not done.

**4. Adaptive background.** A running-window median rather than one over the
whole clip, so a long-lived ability eventually becomes background while a crack
always is. Less obviously right than the others; worth measuring, not assuming.

**THE CAVEAT THAT RANKS ABOVE ALL OF THEM: 713 events, zero labels.** Every
technique here is unfalsifiable until some are labelled, and the lesson of the
ranked corpus was exactly that features validated on a narrow population do not
transfer. the two sentences about the gallery -- the top is cone fragments
and cracks, the bottom is cleanly player icons -- are currently the closest
thing to ground truth on this corpus.

So the cheapest real move is probably a LABELLING PASS on the grouped events
before any of the above, and it is now tractable in a way it was not this
morning: grouping cuts 713 candidates to a far smaller set of objects, and the
`self_icon_dist` sampling fix strips the player-icon band before the player ever
sees it. Invoke the `labelling-pass` skill first.

### Phase 0 and Phase 1 of the temporal build are DONE (2026-09-04)

Design doc, and the authority on what the phases are and why:
`docs/ability-temporal.html` --
https://claude.ai/code/artifact/9874912c-e084-497f-bd41-594944581e36

the player moved the labelling pass to AFTER Phase 1, agreeing the argument that
Phase 1 builds the pass's instrument: a rendered time-series strip per event is
far easier to judge than a static crop, which is the `labelling-pass` skill's
own *the tile is not the object* extended one axis.

**Two things measured before planning, both of which changed the plan.**

* **the ability TRAY reads cleanly on the demo corpus, and "infinite abilities
  makes the tray unreadable" -- written twice in this file -- is WRONG.** The
  bar refills, but the drop is still there to see. Seven clips, `ability_hud.py`
  at `--step 0.25`, every one clean with 0 SUSPECT:

        clip           agent     drops   slots, in order
        c0b63335e635   tejo        4     C 5.5 . E 16.5>17.0 . Q 22.5
        ff19748eea8c   jett        3     C 4.25>8.5 . E 16.25
        f1cf160b213d   neon        2     C 3.0 . E 18.0
        dae6f33f3f48   killjoy     4     C 5.25>8.5 . Q 26.75 . E 33.25
        64d0fb783be2   vyse        4     C 5.25>11.5 . Q 30.25 . E 39.0
        5a63cc4fecfc   yoru        4     C 5.25 . Q 15.25 . E 18.5>26.0
        2f4ef4e8da23   harbor      3     C 6.25 . Q 11.25 . E 22.75

  The drops come out in **C > Q > E order**, which is the stated recording
  protocol arriving independently from the pixels -- so it also VERIFIES the
  ordering prior this file records as unverified, on seven clips at least.

  This is a **supervisor, not a feature**: high precision, low recall, carrying
  slot identity, costing the player no labelling time. It is the first label-free
  score this channel has ever had. Recall is low by construction -- with
  infinite abilities a re-cast refills between samples -- so **a missing drop is
  no evidence, never "no cast"**.

  **Slot X never drops, in 7 of 7.** The tray draws the ultimate as pips rather
  than a bar. So the tray covers C/Q/E and the ultimate-voiceline matched filter
  covers X: audio is not a parallel thread, it is the missing quarter of this
  one.
* **the demo clips are SOLO** -- one roster portrait, one player icon. So the
  local player's cone is the ONLY lighting source on the whole corpus, which
  makes cone coverage a complete lighting model there and an incomplete one in a
  real match where four ally cones also light the map. **Any cone threshold
  tuned on this corpus will be optimistic**; that is the population-mismatch
  trap in a new costume and it should be stated on every figure.

**Phase 0a: `self_icon_dist` is sampled over the whole track, and the MEDIAN
beats the min.** NOTES proposed the min. Measured against the real
`eb10db50b1fb` labels at the already-set `SELF_ICON_DIST_MIN = 7` -- two
aggregates at one fixed gate, nothing re-fitted:

    aggregate   real trapwires kept   not_ability kept
    median             5 of 5             18 of 26
    min                3 of 5             16 of 26

Min drops two real trapwires for seven points more junk, which is the wrong
trade when recall is the scarce quantity. **The mechanism, and why min looked
right until it was measured**: min was proposed as part of a COVERAGE fix, and
the coverage fix is the per-frame sampling, not the aggregate. Once a whole
track is sampled, min stops meaning "is the player's icon here" and starts
meaning "was the player EVER here", which is a far more common event. Visible
directly in the Astra clip -- candidates at min 2.7 / median 54.6 over 275 ring
fits, and min 0.26 / median 20.4 over 211, are objects the player walked over, while
genuine player-icon fragments score small on BOTH (2.3/2.3, 0.34/2.43).

Null rate on Astra 58% -> 33%; the residue is short tracks that never coincided
with a ring fit at all, which is honest. `self_icon_dist_min` and `self_icon_n`
are stored beside it so the choice can be re-run as labels arrive.

**Still open, same bug one level up**: `ability_corpus.load_events` takes
`min(dists)` across an event's fragments, so a grouped event with one
near-player fragment inherits its distance. Same argument, same fix.

**Phase 0b: `two_state_gray` also returns WITHIN-STATE standard deviation**
(`sd_lo`, `sd_hi` in every geometry npz; `minimap_dynamic.load_noise`). This is
the divisor NOTES has named for a fortnight, and **it has to be per-state**.
Overall per-pixel SD at a two-state pixel measures the unlit-to-lit distance
rather than the noise, so it is largest exactly on the swept floor where every
interesting candidate sits -- dividing by it would suppress the signal hardest
where the signal is. Measured on `a06f04a0059f`, 400 frames, median per class:

    class      sd_lo   sd_hi   overall SD
    FLOOR       3.17    3.30        25.33
    BOXEDGE     5.97    3.92        33.60
    PLANT       6.00    4.99        27.45
    BORDER      9.37    5.14        38.68
    VOID       28.44    6.86            -

Overall SD is 5-8x the within-state figure in every class. Across the whole
searchable area the within-state noise sits in a narrow 3.2-6.4 band, so it
behaves as a divisor where it is used; the wild value is VOID, which
`searchable()` masks out anyway. A state made of ONE frame has SD 0 by
construction, on 6.5-8.8% of the widget, so `SD_FLOOR` is mandatory rather than
defensive.

**These are NOT the 2026-08-26 figures** (7.4 on white lines, 16.9 on the slab,
42.5 in the void) and must not be read against them. Those are an OVERALL SD on
a different session, they do not reproduce here, and the regions are not the
same ones: interior line-work classifies BOXEDGE, and BORDER has no pixel more
than 25 px from void, being the void boundary by construction. The colour-free
section's reasoning about `LINE_GUARD` stands as written.

**All 34 geometries were rebuilt** (the file changed, so the stamp did), each
keeping its own provenance -- donors from their own frames, borrowers
re-borrowed wholesale. The rebuild is bit-reproducible: `a06f04a0059f` comes
back with `labels` f94b85d0, `static` 96a251e0 and `lo_gray` ab7b0d1b
byte-for-byte, which is what proves the chunked rewrite of `two_state_gray`
changed nothing. It also caught **`2ba870ccbd50` carrying stale labels** from an
older `classify()` -- same static and lo_gray as its donor, different labels,
`built_by` bbded829 against everything else's f1390557. The stamp convention
doing its job.

**Phase 1: `prototypes/ability_series.py` -- the per-frame series.** Given query
positions it does ONE sequential pass per clip and returns, per position per
frame: patch grey (mean/max/min), the split `dark`/`bright` interval residual,
both normalised by the Phase 0b noise map, cone coverage at that pixel, whether
the cone fit at all, the self track's position and distance, and whether
`detect` fired within 10 px. Written to `<store>/series/` and
`<store>/series-labels/`.

Three decisions, each from a mistake already in this file:

* **queries are `(t_ms, x, y)` and everything is RECOMPUTED, never re-scanned.**
  `label_rows()`'s lesson applied to time, and the load-bearing one: a rescan
  orphans the label store's unstable key, and the four sessions that must never
  be rescanned are exactly the four carrying every ability label the player has
  given. A rescan-based design could be scored against NO labels at all;
* **sequential decode, not `cap.set()` per sample.** Speed, and correctness --
  OpenCV's frame-exact H.264 seeking is unreliable and the measurement here IS
  the frame-to-frame difference;
* **native rate, not the scan's 150 ms.** Animation and pulse features alias
  below their own rate into what looks like broadband noise, which would make
  the animation feature measure the opposite of what it is for.

Cost: 45 s and 0.5 MB per clip at 60 Hz with the cone (`c0b63335e635`, 45
queries x 2308 frames). Cone answered 92.0% of frames there, 48.0% on
`eb10db50b1fb` -- both consistent with the yields already recorded above.

**Two `floor` masks are used deliberately, and the divergence is a latent
defect worth knowing about.** This repo has THREE conventions for the `floor`
argument of `self_rings`: `reticle/cli.py` (the shipped self track) passes
`floor_mask(med)`, `ability_cone.py` passes `floor_mask(static, dilate=1)`, and
`scan_ability_clip.py` passes `labels != VOID`. `ability_series` matches each
use to the code its numbers must be comparable with -- the ring fit to
`scan_ability_clip`'s, so `self_d` reads against the stored `self_icon_dist`;
the cone to `ability_cone`'s, so coverage reads against the 89%-of-frames yield
everything downstream budgets from. Picking one would silently invalidate one of
those two comparisons, and it would not be obvious which.

**Two Phase 1 defects found by RUNNING it on a full match, both worth keeping
because the shape of each will recur.**

* **a full match is not a demo clip.** `--from-labels` on `a06f04a0059f`
  decoded all 139288 frames to serve 53 labels scattered over 39 minutes --
  about two hours of work for 10% of it. `--window-s` keeps only frames within
  N seconds of a query (9.9% of samples, 11m39s) and skips the rest with
  `cap.grab()`, which advances the decoder without producing an image, rather
  than by seeking. That keeps the no-seeking argument intact: the frames that
  ARE measured still arrive from an unbroken sequential decode, so consecutive
  samples inside a window are genuinely consecutive. Verified against a full
  pass of the Tejo clip -- the retained frame set is exactly the frames inside
  the window, and every value at them is bit-identical to the unwindowed run;
* **READ A SERIES AGAINST THE WRONG SPAN AND IT SAYS NOTHING, VERY
  CONFIDENTLY.** Windowing keeps the UNION of every query's window, so the axis
  spans 33 minutes while any one label is about its own few seconds. The first
  windowed run reported `detect` firing for 75.5% of frames at the median query
  and **75.7% at the max, across 53 queries** -- uniformity that reads as a
  finding and is arithmetic. Each query was being averaged over 13843 frames
  when 360 were its own.

  **It bites on a SHORT clip too**, which is the half worth internalising --
  the same Tejo series read whole-axis against per-query-window:

        statistic                          whole axis   own +/-3s
        detect fired, median query             14.9%       40.8%
        detect fired, max query                61.0%       94.5%
        nearest query to the self icon        35.3 px      3.9 px

  Same data, same pass. The whole-axis reading dilutes every candidate with the
  38 seconds in which its object does not exist. `win_lo`/`win_hi` now carry
  each query's own half-open slice and `summarise()` respects it; **every Phase
  2 feature must slice by it too.**

  The two spans are deliberately NOT collapsed. `win_lo`/`win_hi` say what was
  DECODED and is valid for that query, and on a demo clip that is the whole
  axis on purpose -- clipping there would destroy the repeat-structure feature,
  which is precisely about an object recurring later. A feature wanting a LOCAL
  window derives it from `t_ms` and still respects `win_lo`/`win_hi` as the
  outer bound of what exists.

**And an n worth knowing before quoting one: `a06f04a0059f`'s 53 ability label
rows sit at only 16 DISTINCT positions.** They are repeat observations of the
same devices, which is exactly what `ability_eval.collapse()` exists for
(*one row per position -- objects, not tracks*). Any figure quoted off the raw
row count on that session overstates its evidence by more than three times.

**`28f53bfddbbe` (Clove) had lost its media** -- the player had renamed
`2026-09-03 18-58-15.mp4` to `clove.mp4`. Manifest repointed, verified by
re-deriving the blake2b content key rather than trusting the name. It was 1 of
48; the rest all resolve. The failure is worth recording because of how it
presented: OpenCV reports `frame_count = -1` for a file it cannot open, so the
error surfaced as an `IndexError` on an empty array several functions away, and
it abandoned 26 good clips on the way. `MediaUnreadable` is now raised at the
cause and skipped per session with a tally at the end.

### Ability icons ANIMATE, and ultimates have fixed voicelines (the player, 2026-09-03)

> A fair number of the abilities, especially ultimates, essentially have minimap
> icon animations, so that's something we probably need to deal with temporally.
> There are also fixed agent voicelines for ultimates.

**Animation breaks template matching in a way none of the taxonomy's axes
covered.** Duration, mode and portions-extending-past-the-icon all describe a
STATIC appearance that changes state. An animating icon has no single
appearance to match, and the shipped approach for icon identity
(`minimap_portrait`'s composition matching) assumes one. Three consequences:

* **a template bank needs a temporal entry per animated class**, or an
  invariant that survives the animation -- the same "find the invariant part"
  move that made composition matching work when pixel correlation failed;
* **it partly explains the FRAGMENTATION already measured.** An icon whose
  appearance changes frame to frame will not track cleanly, so one object
  breaks into several short candidates -- which the lifetime feature then scores
  DOWN, exactly backwards, since animation is evidence of a real ability rather
  than of noise;
* **detection may be EASIER than identity here.** A patch of widget changing
  every frame in a structured way is conspicuous; deciding which ultimate it is
  is the hard half.

**The voicelines are the more valuable half, and they unblock a parked thread.**
`prototypes/audio_probe.py` established that every capture carries a stereo
48 kHz AAC track and that ONSET detection is dead -- marks sit where random
times sit at every tolerance tried. Its conclusion was that audio needs
IDENTITY, a matched filter on one sound, and that a matched filter needs a
reference cut at a known cast time, which infinite abilities made hard to get.

**A fixed per-agent ultimate voiceline is the ideal matched-filter target**, and
a better one than the SFX that thread was aiming at:

* it is long, loud and spectrally distinctive, where a device-placement click is
  short and quiet;
* it is a CLOSED SET, one or a few per agent -- the same shape as the digit
  templates and the twenty-five agent-name bitmaps, both of which worked;
* it announces an ULTIMATE, the highest-stakes event in a round and the one
  most worth having in the log;
* **it needs no minimap at all**, so it reaches ultimates that draw nothing --
  the negative class this corpus cannot otherwise touch;
* and the demo clips are a clean reference source: one agent per clip, ults cast
  deliberately, little else happening.

Enemy ultimate voicelines are audible to the enemy team in-game, so this may
also reach events on the other side. Unconfirmed -- ask the player rather than
assume.

### Uncertainty is ACCEPTABLE, and that ranks everything above (the player, 2026-09-03)

Said after a run of notes here each treating an open question as a blocker:

> It's acceptable to have some degree of uncertainty as well. You won't always
> know which abilities have been used or even what abilities they had to begin
> with. This is just recording the known event log as well as we can.

**Read this as a calibration on the whole ability line, because the notes above
were drifting the wrong way.** The deliverable is an event log, not a complete
ontology. "An ability icon appeared at (x, y) at t, class unknown" is a usable
event -- it has a time, a position and a team-ish prior from who is alive. It
does not become useful only once the class list is closed. And the class list
will never close: agents are added, an enemy's kit is only known from the
roster read, and abilities that draw nothing are unobservable by construction.

So the ordering that follows:

* **ship partial identification.** Detect > localise > classify, in that order
  of confidence, and emit what is known at each level rather than waiting;
* **do not gate the event log on the taxonomy.** The taxonomy improves the log;
  it is not a precondition for it;
* **an unresolved class is a cost, not a fault.** Several notes above imply a
  question must be settled before proceeding. Most need not be.

**One distinction this does NOT dissolve**, and it is why the Yoru decoy note
still stands as written: not knowing which ability an icon is costs precision
in a log that is honest about it. An object that silently CORRUPTS a signal
already trusted elsewhere -- a phantom player icon desynchronising the
roster-portrait alive count, which is also the killfeed's continuous audit --
is a different category, because nothing downstream would report lower
confidence. Uncertainty that is visible is affordable; uncertainty that
disguises itself as a confident number is the thing this repo keeps paying for.

### Yoru's DECOY may be a false player icon -- check this first (2026-09-03)

the description:

    C   a DECOY CLONE that looks like him and moves in a straight line; when
        shot it becomes a flash
    Q   a bounceable FLASH
    E   a TELEPORT marker, either stationary or travelling in a straight line;
        activating it teleports him to its location
    X   invulnerable and INVISIBLE for the duration; nearby enemies see blue at
        the screen edge and hear a noise. He can teleport during it

**The decoy is the most consequential thing in this sitting after the teleports,
and it is a HYPOTHESIS, not a finding.** If a decoy renders on the minimap as a
player icon, then the widget can show a player who does not exist, moving in a
straight line. That would break things this repo currently treats as solid:

* **the roster-portrait alive count**, which CLAUDE.md calls a per-frame state
  needing no event integration, and which is also the continuous audit of the
  killfeed. A phantom body would desynchronise them and look like a missed
  killfeed entry;
* **ally/enemy identity across frames**, the next step on the position thread.
  A decoy travelling in a straight line is exactly the trajectory a
  nearest-to-previous matcher will happily adopt;
* **`paint_icons.WORLD`'s self/ally/enemy classes**, which assume an icon
  corresponds to a person. A decoy needs its own class before anything is
  painted on a Yoru clip.

**What is NOT known and must not be assumed:** whether the decoy appears on the
minimap at all, and whether it appears to Yoru's own team the same way it
appears to enemies. This capture is the screen with Yoru on his own
side, so it can only answer the friendly case. The enemy case needs a different
capture and cannot be got from this corpus.

**THE PLAYER, 2026-09-06: YORU CAN FAKE THE TELEPORT OR TAKE IT, AND FAKING MAKES
THE NOISE.** He demonstrated both in `5a63cc4fecfc`. This is a domain fact
nothing in the capture states and it is the sharpest argument yet for the audio
channel, because it makes audio and the position track answer DIFFERENT halves
of one question:

    teleport sound + a jump      he TOOK it
    teleport sound + no jump     he FAKED it -- a deliberate deception, and an
                                 EVENT worth logging, not a detection failure
    no sound + a jump            not this ability; or the track is wrong

**That inverts the "cast, no jump" row of the cast-licenses-a-jump table.**
`cast_motion.py` records that row as *"not a teleport, or the track lost the
player -- itself a finding"*, which for Yoru is exactly backwards: it is the
ability working as intended, and it is the more interesting of the two
outcomes, since a fake is a read on the enemy rather than a rotation.

It also explains what was measured there without knowing this: Yoru's two
GATECRASH tray drops are followed by 4.6 px and 6.3 px of movement. **Do not
read those as two fakes** -- the tray drop is the rift being PLACED, and taking
or faking it is a later, separate action with no tray drop of its own. The tray
cannot tell the two apart in principle. Audio can.

**Consequence for the audio plan: Yoru's teleport SFX is a poor first target
and a valuable second one.** First target wants an ability whose sound implies
its effect; this one is specifically designed so that it does not.

`5a63cc4fecfc` is the clip. Check it BEFORE trusting any player-icon count on
a session with a Yoru, and record the answer here either way -- a confirmed
"the decoy does not draw" is as valuable as the alternative and closes the
question permanently.

**The ultimate raises the mirror question: does an INVISIBLE Yoru still draw on
his own team's minimap?** Almost certainly yes for allies, but "almost
certainly" is how the cam-is-red mistake happened twice. It is checkable in the
same clip.

### Waylay's kit, and a HUD element nothing has read (the player, 2026-09-03)

    C   a GRENADE causing movement and weapon slow on impact
    Q   a toggleable DASH or double dash; the first can go UPWARD
    E   a RECALL TELEPORT -- place an anchor, instantly return to it for the
        duration. Recharged on KILLS: two kills refills it, and there is an
        ICON ABOVE IT IN THE HUD indicating that
    X   a RECTANGULAR area that stuns like the grenade, slowing enemies and
        their fire rate

Three things to take from it beyond the teleport, which is filed above:

* **a REGION can be RECTANGULAR.** Every region in this document so far is a
  circle (smokes, Vyse's ult, the audio ring) or a wall (Sage, Viper,
  Deadlock's mesh). A rectangle is neither, and it kills any thought of
  identifying the region family by fitting one shape -- the same mistake the
  icon branch already made with `minimap_ring_fit` fitting a circle;
* **the ability TRAY carries a charge-state icon**, drawn above the ability.
  `ability_hud.py` reads the tray's fill levels and quantises them cleanly to
  0.00 / 0.50 / 1.00; nothing knows about a second indicator sitting above a
  slot. Worth checking it does not corrupt the fill read, and worth having --
  "this ability is kill-charged and currently ready" is round state;
* **a grenade again**, consistent with the rule that grenades, flashes and
  molotovs are the common no-icon family. Waylay's C and X are both damage/slow
  effects and the X is explicitly an AREA, so it is the more likely of the two
  to draw something.

### Ability DESCRIPTIONS are worth more than more clips (the player, 2026-09-03)

the player, sending the Vyse clip: *I should have given ability descriptions.* He
should have, and the first one he gave proves it -- a paragraph of his prose
constrains the class list harder than a minute of footage, because it says what
an object IS rather than what it looked like once.

**Vyse, in his words, and what each part implies:**

    C   a charged deployable VINES that, when activated, form a CIRCLE that
        damages enemies in it who move
    Q   a WALL that activates when an enemy crosses it, and cannot be destroyed
        while up, for a short duration
    E   a deployable FLASH FLOWER, placeable either side of the wall, flashes
        when activated, CAN BE PICKED BACK UP, reactivated and redeployed on
        cooldown
    X   a circular REGION CENTRED ON VYSE that goes off after a few seconds and
        stops enemies using their primary weapon

Four things fall out, and three of them are new to this document:

* **C is an ICON that BECOMES A REGION.** Deployed it is a placed device;
  activated it is a damaging circle. That is the `modes` axis of the
  taxonomy in its strongest form so far -- not a colour change like the Cypher
  cam turning teal, but a change of FAMILY. A detector that assigns an object
  to the icon branch or the region branch once, at first sight, is wrong for
  this class. It has to be allowed to change;
* **E CAN BE PICKED BACK UP.** So a placed device disappearing does NOT imply
  it was destroyed, and the same physical object can reappear elsewhere later.
  Anything reasoning about lifetime or identity by "device at position P
  persists until it stops being there" is wrong for this class -- and lifetime
  (`n_observations`, `duration_ms`) is currently the feature that doubled
  precision, so this is a caveat on the best number we have;
* **X is PLAYER-ANCHORED**, exactly like the audio ring. So the same argument
  applies: once its radius is measured it is DERIVABLE from the shipped self
  track rather than detectable -- draw it, do not look for it. Second instance
  of that pattern, which makes it a pattern rather than a special case;
* **Q is a triggered region**, so a region can have an activation state as well
  as a lifetime.

**Ask for these for every agent.** Free prose is the right form -- the player
describes, this file classifies; he should not be asked to fill in a taxonomy.
At 27 demo sessions against 4 labelled ability classes, the corpus is no longer
the bottleneck: knowing what the objects ARE is. A description also says what
to LOOK for in a clip, which turns a scan of it from open-ended into a check.

### TELEPORTS: player icons move discontinuously, and nothing here knows it

the player, 2026-09-03, with the Veto clip: *One of his abilities is a teleport. Two
of omen's abilities are teleports, and one of chamber's.*

    veto      one ability
    omen      two abilities
    chamber   one ability
    waylay    E, a RECALL teleport -- she places an anchor and returns to it
    yoru      E, a teleport marker that may be STATIONARY OR TRAVELLING

Waylay's is worth separating because it is a **two-part** teleport: placing the
anchor is itself a deployable (so probably an icon), and the recall is the
discontinuity. Chamber's Rendezvous is the same shape. So a teleport may
announce itself on the widget before it happens, which is a detectable
precondition rather than only a jump to explain after the fact.

**This is not an ability-icon note. It is a defect in the shipped position
track, and it was invisible because the player has not played these agents on any
recorded match.**

`reticle/minimap.py` filters the self track, and NOTES quotes **jumps > 60 px/s
at 5.0% / 3.3% / 3.8%** across the three geometry-validated sessions as a
quality figure -- implicitly, the residual error rate. That reading assumes
every large jump is a tracking fault. **A teleport is a real, correct jump**,
so on any session where the local player or a tracked ally is Veto, Omen or
Chamber, that metric conflates two different things and the filter will fight
the truth: nearest-to-previous is exactly the rule a teleport breaks, and it
will either reject the real new position or smear the transition across frames
that never happened.

Three consequences, in order of how soon they bite:

* **the current 5.0%/3.3%/3.8% figures are probably clean**, because the player
  played Phoenix on Ascent and neither of the other two lineups is known to
  have had him on a teleport agent -- but that is an assumption nobody checked,
  and it is checkable from the roster once the lineup read works;
* **ally identity across frames -- the next step on this thread -- must
  tolerate discontinuity.** The planned rule is nearest-to-previous per slot,
  the same trick `pick_self` uses. That rule is wrong for three agents on the
  roster, and it will fail SILENTLY by swapping two allies' identities when one
  teleports past the other;
* **dA/ds assumes motion is continuous.** Exposure per unit of movement is
  meaningless across a teleport -- the player did not cross the intervening
  ground and was never exposed on it. A teleport must break the path, not
  contribute a huge dA/ds spike.

**And the jump metric conflates a THIRD thing: dashes.** Waylay's Q is a
toggleable dash or double dash. A dash is continuous motion, unlike a teleport,
but at 15 Hz it can easily exceed 60 px/s between samples and be counted as a
fault. So `jumps > 60 px/s` is currently measuring tracking error, teleports
and dashes together, and only the first is a defect. Jett and Neon are the
obvious other dash cases; Neon's slide is already recorded here as drawing
nothing on the widget, which does not mean it does not MOVE her.

the player also notes the first part of her dash **can go upward** -- which the
minimap cannot show at all, the same standing limit as jump peeks being
invisible. Vertical displacement is simply absent from this channel.

**What to do about it is not yet decided, and should not be guessed.** The
honest options are to detect the discontinuity from the track itself (a jump
larger than any possible run speed over one sample interval), or to know the
agent from the roster and expect it. The first needs no roster and catches
unknown future agents; the second is exact where it applies. Neither has been
tried, and the demo clips are the place to measure what a teleport actually
looks like at 15 Hz before choosing.

### the domain notes on the minimap -- not recoverable from the pixels

* **A Cypher cam ROTATES.** *(It was recorded here as "the only other moving
  icon on the widget". **the player withdrew that on 2026-09-05** and it is corrected
  in place per this file's own rule. Killjoy's Alarmbot translates toward
  enemies and her turret snaps onto them; the piloted scouts -- Sova's drone,
  Tejo's drone, Fade's Prowler, Skye's dog and birds -- translate AND rotate
  under player control. Measured from the labels: the Owl Drone moves 18 px in
  0.9 s. What separates these is the DRIVER of the motion, not the fact of it;
  the taxonomy is in `prototypes/ability_cast.py`.)* Perfect circle, never translates, rotation shown by the camera glyph
  turning INSIDE the ring -- **no lobe**. This corrected "a placed ability never
  turns", which was load-bearing in `motion()`. Consequence: **translation**
  holds against the cam; **rotation does not reject a cam at all**, since
  rotation is read from the lobe and a cam has none.
  `minimap_ring_fit.LOBE_MIN_FRAC` floors that so a perfect circle cannot report
  a confident bearing from noise.

  **RESOLVED 2026-09-02, with real reference footage.** the player recorded two
  controlled clips placing his own Cypher kit (`eb10db50b1fb`, one cam plus
  the rest of his util; `d95cfad5693a`, several cams, deliberately "going
  inside" each to trigger the view). Confirmed against them, measured, not
  guessed:

  * **Cypher cams are NOT red**, correcting a mistake made twice in this repo
    (see below). At rest every placed Cypher device -- cam, trapwire, cage --
    is a **black/near-achromatic circle** (colour-free channel, not the red
    mask) with a small white line-art glyph inside identifying which device it
    is (a two-dot "lens" glyph read as the most likely cam candidate; a
    caution-tape X for the trapwire). Three distinct such glyphs appear
    together in `eb10db50b1fb`, matching three placed devices.
  * **A NEW mechanic, found while confirming the above: the icon changes
    colour while the player is actively viewing through it.** the player: *"I noticed
    the cam icon turned blue when I was in it."* Measured directly off
    `d95cfad5693a` (region-restricted HSV sample, not a whole-frame scan --
    the minimap's transparent-void scenery bleed makes an unrestricted colour
    search noisy): **H=76-77, S=166-168, V=144-148** (OpenCV 0-179 scale) at
    two independent viewing instances, against 4 stray background pixels in
    an unrestricted same-region resting-state control. That hue sits right at
    the edge of `minimap_position.ALLY_H = (75, 100)` -- the SAME teal already
    used for ally rings elsewhere on this widget, not a new colour family.
    "Blue" is the read of that teal by eye; the measurement says teal/cyan.
    The main view also shows a corroborating, unmistakable signal at the same
    moment -- a **"LIMITED ... MIN ... ZOOM" HUD overlay**, cheap to detect
    and useful as a second confirmation independent of the minimap.
  * **UNCONFIRMED, the hedge**: *"I believe when it's an enemy it
    turns red."* Not measured -- neither clip contains an enemy cam. Treat as
    a hypothesis, not a fact, until tested.
  * **The trapwire is TWO separate drawn things, and the player did not know the
    second one was on the minimap at all until seeing it in a labelling
    pass, 2026-09-02.** The trapwire's ICON is black-and-white like every
    other Cypher device (the caution-tape-X glyph above) -- but the WIRE
    ITSELF is ALSO rendered, as a straight coloured span across the
    chokepoint it's strung through, in the placing player's own team colour
    (light blue/teal on the). What `scan_ability_clip.py` actually
    found and the player named `Cypher:Trapwire` five times in `eb10db50b1fb` was
    this wire span, not the icon -- a short, roughly rectangular, hard-edged
    coloured bar sitting exactly in a doorway gap. Practically load-bearing:
    **the icon and the wire are two independent, differently-shaped signals
    for the same object**, and a detector built around one shape family
    (a ring-fit, tuned for the icon) will not recognise the other (a bar).
    Confirming the icon separately -- small, circular, black/white, at one
    end of the wire's span -- is still open.
  * **Next step to make this a real detector**: run `scan_ability_clip.py` on
    both sessions and let the player label the candidates it finds with
    `label_ability.py` -- now that the actual glyphs and their two colour
    states are known, this should take minutes rather than another blind
    mining pass.

  **The mistake this corrects, for the record**: `glance_cams.py` was run
  against Lotus's red-confounder pool this same session and guessed two wrong
  "cam" answers; the player caught it immediately. This was the SECOND time this
  exact error happened -- the first is recorded under "the cam question and
  the ability pass" above: *a cam glyph is black and white, so it lives in the
  COLOUR-FREE channel, not the red mask.* `label_minimap.py`'s ctrl+click
  example list and `glance_cams.py`'s docstring are both corrected/flagged.
  **Do not build a cam-finding tool against the red mask.**
* **ENEMY DEATHS LEAVE MARKS TOO, but they are NOT always visible the way ally
  marks are.** the player, 2026-09-05, asked directly because `xmark_eval` matches
  only teammate deaths to the blue X and this file also lists red X marks as a
  confounder class.

  **The asymmetry is the whole content of the fact, and it makes the constraint
  ONE-SIDED.** For a causal model over the widget that is the difference
  between a usable prediction and a wrong one:

      an OBSERVED enemy mark  =>  an enemy died there        (usable)
      an ABSENT enemy mark    =>  nothing                    (NOT "no death")

  So the killfeed's enemy side cannot be used to predict how many marks should
  be on screen, the way it can for teammates -- a missing enemy mark is not
  evidence of a missed killfeed entry, and treating it as one would generate
  phantom faults on exactly the sessions where visibility was poor. Teammate
  deaths keep the two-sided form, which is why `xmark_eval` is built on them
  and should stay that way.

  What decides visibility is unmeasured. The obvious candidate is the same rule
  the whole minimap obeys -- the widget shows what your TEAM knows -- so an
  enemy death nobody could see plausibly leaves nothing. Not confirmed; do not
  encode it.
* **An OMEN SMOKE TRANSLATES while it deploys**, and it is the only one. the player,
  2026-08-27, on candidate 61 of the Lotus pass: *it's the only smoke in the
  game that moves from omen to the placed location. Viper orb is throwable but I
  don't recall what the icon is and it's not "out" while in flight.* This is the
  **only known counterexample to the translation invariant**, which
  `motion()` had been treating as holding against everything. It narrows the
  claim rather than killing it: the movement is short and one-way and ends where
  the smoke lands, so **a track that translates and then stops forever is a
  smoke; one that keeps moving is a player.** Unmeasured -- until it is measured,
  translation is strong evidence, not a proof gate.

* **The triangle is the most important part of the teardrop** -- 7.3 px against
  1-2 px for the rest of the ring, so it is both the most robust part and the
  part carrying identity. A cam has a ring and no triangle.
* **The interior portrait is the same art as the KILLFEED portrait and the top
  roster portrait.** Route to identification, and it works -- see "Portrait
  identification works" above. Two corrections the player made once it was measured:
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
  Deprioritised on the call: only at extreme short range, where the screen
  detector has a large unambiguous blob anyway. It IS in the agent-label set --
  the player flagged one Jett icon mostly covered by his own in a close-range duel --
  so identification sees the case even though detection was allowed to skip it.
* **An ally Breach ultimate draws a big RED BAR across the minimap**, and it
  occludes icons: the player hit one covering the top of a question-mark icon while
  labelling. This is the sharpest counterexample yet to the assumption the whole
  minimap line rests on -- **red does not mean enemy**. Every red confounder
  catalogued so far (X marks, Reyna blinds, pings -- NOT Cypher cams, wrongly listed here until the player
  corrected it 2026-09-02; see the correction below) is small and
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
(0.00-0.09). the call: stay on 4:2:0 and prove it there, which the ring fit
now does. `prototypes/chroma_test.py`, and item 12 of the pre-ingest checklist.


**Also unresolved and worth an eye:** some corpses carry a red outline and some
do not, and no explanation survived testing. The obvious one -- the outline fades
with age -- is unsupported but the test is underpowered, because the killfeed
timestamps deaths without locating them and so cannot age an individual body.

**Per-session status is GENERATED, not written here.** Run
`reticle status` (or read `STATUS.md`) for sessions ingested, store version,
rounds, plant rates, and every K/D against `checks.KNOWN_KD`. This paragraph
used to carry those numbers by hand and on 2026-08-27 it was wrong three ways at
once -- *seventeen sessions* against 18, *the store is at hud-0.8.1 throughout*
against hud-0.9.0, *nine of thirteen are exact* against 9 of 17. Nothing had
changed except the world; the prose simply could not keep up, which is the
argument for computing it.

What is NOT derivable, and so stays here:

**`5822b6646448` (Lotus) was fully out-of-sample** -- recorded 2026-08-26 after
the widget change, ingested and scored the same day, nothing tuned against it.
It is the second capture on the enlarged minimap and the first on a map that
widget had not seen, which is the test the icon work most needed.
`c62c2b06bcfb` (Split) shows **5 invariant violations that look like one cause,
not five**: the scoreline reads a two-digit score as one digit twice
(0:06:51 12 -> 2, 0:31:43 12 -> 1) and recovers within 3.5 s each time, so the
two decreases and the two illegal sum steps are the same event counted from both
sides. The 4.5 s clock jump at 0:00:03 is pre-match. Both were confirmed
`valorant-16x9-bigmap` before ingest by measuring the floor slab -- it reaches
x 452 / 458 against the old widget's 346.

**Ground truth is now corroborated.** the player read his whole match history on
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

`hud-0.7.0` — **three band-detection fixes**, all found from five misses the player
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
  the recorded figure. the deaths inside his ult.
* `bfad2778a372` +1 kill, the same rule from the other side: a kill on an
  *enemy* Phoenix inside Run It Back. 19/15 confirmed off the end screen.

Both causes are **visible in the killfeed itself**, which is what makes reading
the mark worth doing: one detector reconciles both sessions exactly.

**the call (2026-08-25): keep these events, do not drop them to match the
board.** A duel lost inside Run It Back is still a duel that was lost, and §4's
metrics are about duels. So the mark becomes a *category* on the entry — an
event that happened and that the scoreboard does not count — rather than a
filter. Stage 05 subtracts them when reconciling totals; stage 06 decides per
metric whether to include them. Same treatment as wallbangs.

**DONE 2026-09-02: minimap position tracking is promoted.** `minimap_position.py`
-> `reticle/minimap.py` + `reticle minimap <session>` (L1, 15 Hz default, active
spans only). Self is a real filtered track; ally rings are still per-frame
candidates with no cross-frame identity.

**RE-VALIDATED at `minimap-0.2.0`, 2026-09-05, after the widget guard.** Both
checks were re-run with `--no-guard` (the figure on record) and without, on
`a06f04a0059f`. They say different things and the difference is the finding:

    xmark_eval            baseline    guarded
    scored                  64/67      61/67
    closest-to-X median     25.9 px    24.3 px
    closest-to-X p95       260.2 px   144.1 px      <-- the result
    ally-to-ally spread    138.7 px   141.9 px
    frames skipped            0.0%       9.2%

    chokepoint_eval       baseline    guarded
    scored                129/129    129/129
    transition median       3.8 px     3.9 px
    baseline-window median 10.2 px    10.9 px
    frames skipped            0.0%       5.8%

**The X-mark check improves sharply and the chokepoint check does not move.**
The p95 nearly halves for a 4.7% coverage cost, which is the signature of
removing phantoms rather than of a better detector: garbage does not shift a
median, it lives in the tail. Chokepoint's separation is preserved exactly
(2.7x the null before, 2.8x after) and its median moves by 0.1 px.

**Why they differ is the useful part, and it generalises.** The guard skipped
9.2% of the X-mark eval's frames against 5.8% of chokepoint's and 5.0% of the
session as a whole -- because `xmark_eval` samples around DEATHS, which is
exactly when the death screen is up, while `chokepoint_eval` samples at
location-banner transitions mid-round, when the player is alive and moving and
the widget is nearly always drawn. **Widget-absence is not uniform; it
concentrates where a measurement anchored on deaths looks.** Same shape as the
`self_icon_dist` sampling defect recorded above -- a per-track feature measured
at the birth frame inherits that frame's failures -- and the same lesson: ask
where a sample is drawn from before reading its rate.

Two independent ground-truth checks back the track (see `xmark_eval.py`,
`chokepoint_eval.py`, 2026-09-02, re-run 2026-09-05):
teammate deaths' pre-death ally-ring positions land within ~1-1.5m of the blue
X mark, and self-track positions near a location-banner text transition land
close to the map's own physical chokepoints (distance-transform ridge of the
floor mask) — both well inside the baseline-window null. This module's
rejected-approaches list (foot of the old prototype file, preserved in
`reticle/minimap.py`'s docstring) is still the reason to read before trying
anything content-based here again: five variants failed for one shared cause,
**the widget is semi-transparent over the void, so anything content-based
drowns in the world moving behind it.** Masking to the opaque floor slab is
what fixed it, and it is also the occlusion grid the visibility work needs.

Next steps, in order (see NOTES.md "Picking up" for the fuller version): ally
identity across frames; the visibility computation (dA/ds); vision cones and
enemy-icon states (solid / question-mark / X), still entirely unread.

**Peek exposure as the design doc defines it is out of reach**, and that is a
design-doc correction rather than a missing feature. It needs enemy positions,
and the minimap shows an enemy only while somebody on your team can see them --
a teammate holding an angle, or a recon reveal -- plus red X marks for last-known
positions. That is *what your team knows*, not ground truth, and for decision
analysis it is the right basis: you cannot be faulted for an enemy nobody had
seen, but you can be for peeking into one a teammate was looking at. It does
mean full exposure-to-any-enemy is out of reach from a self-capture. If the
product must run on a player's own OBS capture (the player is sceptical that building
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
3. ~~Minimap position tracking~~ **DONE 2026-09-02** — self is promoted and
   validated; ally identity and the visibility computation are what remain.
4. **Keep grinding killfeed recall.** Diminishing: four causes found, two fixed,
   the rest cost a re-ingest or need a new primitive.

If a new capture reads badly, count thin tracks first (see below) — it is the
fastest signal for whether the problem is detection or counting.

