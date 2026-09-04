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

**And it doubles as the spike's detonation radius**, which is immediately usable:
post-plant, whether the player stood inside the lethal circle is a fact about a
round that `rounds.py` already knows the phase of.

Unmeasured so far: the radius itself, in minimap pixels and in metres. The
region pass is the cheapest way to get it -- paint the circle once or twice and
read it off, rather than deriving it.

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

* **A Cypher cam ROTATES**, and it is the **only other moving icon** on the
  widget. Perfect circle, never translates, rotation shown by the camera glyph
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
candidates with no cross-frame identity. Two independent ground-truth checks
now back it (see `xmark_eval.py`, `chokepoint_eval.py`, both 2026-09-02):
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

