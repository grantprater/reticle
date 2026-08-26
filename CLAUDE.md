# Reticle

Vision-based mechanical analysis pipeline for Valorant — measuring the layer of
play the match API structurally cannot see. Python 3.14, four deps, single
process, no ML frameworks.

**Design doc** (the authority on stage numbering and intent):
https://claude.ai/code/artifact/d7c7173f-dc5e-4c1e-9dcc-acded5a486cb
**Store dashboard:**
https://claude.ai/code/artifact/3854df28-3e45-4783-8aee-7e7f062ac461

Section references in docstrings (`SS3`, `SS7`) mean §3, §7 of that doc.

## Picking up

**2026-08-25, enemy detector.** Two label corpora now exist:
`9acf02f98283` (Ascent, 149 frames / 46 enemies) and `bdfdcf009dba` (Lotus, 303
frames / 65 enemies). Everything below is measured; the tree is clean and nothing
is half-applied.

    detect() single frame     ascent 91.3% recall / 41.2% precision
    + track_filter()          ascent 91.3% / 48.8%
    detect() single frame     lotus  76.2% / 42.5%   (cut points UNCHANGED)

**CLOSED 2026-08-26: lowering `AREA` with persistence as the safety net does
not work, and neither does track-level back-fill.** This was the standing "start
here" and it is now measured, three ways, on both corpora. Everything below is
scored inside a +/-250 ms window at 50 ms around each label -- a track cannot
exist at an isolated frame -- with only the centre frame scored, so the numbers
are directly comparable to the shipped ones. `prototypes/enemy_teacher.py`
(decode + dump) and `enemy_teacher_sweep.py` (rules, from the dump, no video).

**The floor sweep is the decisive one.** A track is accepted if it contains one
shipped-quality member (the safety net) and its centre member clears `floor`:

    floor    ascent               lotus
      8      93.5% / 21.6%        82.5% / 29.5%
    120      91.3% / 27.8%        76.2% / 37.5%      <- the SHIPPED floor
    160      91.3% / 31.3%        73.0% / 39.3%

At the shipped floor the track rule reaches **exactly shipped recall** (91.3%,
76.2%) with far worse precision than shipped `detect()`'s 41.2% / 42.1%. So
back-filling from a confident sibling recovers **zero** enemies there and only
admits blobs the shape gates were right to reject. Taking the floor from 120 to
8 then buys 2 enemies on Ascent and 4 on Lotus for 43% and 55% more false
positives. Persistence at len>=3 is applied throughout all of those numbers: it
is not a sufficient net, and the pairing the README proposed is now tested.

**The shape gates, not the size floor, are doing the work.** That is the
inversion worth keeping: `AREA` looked like the binding constraint because the
adjudicated misses die there, but relaxing what `frag_top1`, aspect and
hollowness reject costs precision immediately and buys almost nothing.

Two weaker variants were tried and both are below shipped at matched recall: a
hand-tuned track rule (best: two gated members, `3/2/0`, 93.5% / 31.6% on
Ascent) and a **fitted** track-level score over seven track features, cross-map
validated (89.1% / 28.7% on Ascent, 74.6% / 37.3% on Lotus). The eval's own
`track_filter()` at TOP1-off/len>=3 already reaches 93.5% / 42.2% on Ascent and
beats every one of them on both axes.

**One thing did come out of it: a blob-level calibrated score reaches a
high-precision operating point the AND-chain has no equivalent for.** Fitted by
IRLS over the 16 blob features plus four log-size terms, trained on one map and
scored on the other:

    fit lotus -> ascent    50.0% recall / 85.2% precision    (p93)
                           67.4%         / 67.4%             (p88)
    fit ascent -> lotus    28.6%         / 75.0%             (p93)
                           60.3%         / 59.4%             (p82)

It does **not** beat shipped+persistence in the useful region (Ascent
91.3% / 48.8%) -- at 84.8% recall it gives 40.2%. The gain is only at the far
precision end, which is exactly the end a *pseudo-labelling* teacher needs and
the end the conjunction cannot reach at all, because a veto has no confidence.

**What this says about the teacher idea overall.** The premise was that offline
evidence -- the whole video, 20x the compute -- could reach near-perfect
precision and recall and then be distilled. Recall has a real ceiling and it is
close: the permissive proposer finds 97.8% of Ascent labels and 92.1% of Lotus,
so the enemies are nearly all *proposed*. Precision is the wall. Nothing tested
gets past ~85% precision on one map and ~75% on the other, and pseudo-labelling
needs better than that or it poisons the student. **Screen-space evidence alone
will not produce a near-perfect teacher**, which is a direct argument for the
independent modality already identified -- the minimap as a frame-level gate --
rather than for more work on the rim.

Caveat that cuts the other way, from the eval docstring: measured precision
**understates** the detector by roughly 10%, because enemy limbs are scored as
false positives by the head-click matcher and there is at least one unmarked
enemy in the reviewed sample.

Two more recall classes, both newly isolated and neither addressed:

* **clustered enemies are not separated** -- three enemies standing together
  yield fewer than three detections, because the vertical closing kernel that
  merges one enemy's broken rim cannot tell those fragments from a neighbour's;
* **6:26 on Lotus is bug-shaped** -- 332 and 779 pixels pass every colour gate
  and the enemy is still lost, so shape, aspect or the closing is discarding a
  well-found enemy. Unexplained.

**Grant's domain notes on the minimap, 2026-08-26. None of this is recoverable
from the pixels and two of them correct claims this file previously made.**

* **A Cypher cam ROTATES**, and it is the **only other moving icon** on the
  widget. It is a perfect circle, it never translates, and its rotation shows as
  the camera glyph turning INSIDE the ring -- **with no lobe**. This corrects
  "a placed ability never turns", which was written into `motion()` and was
  load-bearing for the motion filter. The consequence is that the filter's two
  branches are not interchangeable: **translation** holds against everything
  including the cam, while **rotation does not reject a cam at all** -- rotation
  here is measured from the lobe, and a cam has none, so any rotation a cam
  yields is ring roughness. `minimap_ring_fit.LOBE_MIN_FRAC` now floors that, or
  a perfect circle would report a confident bearing from noise and the rotation
  branch would pass the one object it most needs to reject. Absence of a lobe is
  itself a positive discriminator.

  **Measured effect of the floor, and its limit.** Adding `LOBE_MIN_FRAC`
  dropped the median rotation of non-enemy tracks from **8.9 deg to 2.0 deg**
  while leaving enemy tracks at 103.0 deg -- so the separation on the rotation
  axis widened from 12x to 50x. **The scored operating points did not move at
  all**, because blobs yielding 8.9 deg were already under the `rot >= 15` gate;
  the floor cleans up sub-threshold noise and widens the margin rather than
  changing today's numbers. Its p75 still reaches 121 deg, so lobeless blobs can
  occasionally still produce a large spurious bearing.

  **The cam case itself is still UNTESTED.** Nothing in the label set identifies
  which `other_red` marks are Cypher cams, so the guard is principled and
  unmeasured. Testing it needs cams labelled as such, or frames known to contain
  one.
* **The triangle is the most important part of the teardrop.** The ring is
  1-2 px over most of its circumference and 7.3 px at the triangle, so the
  triangle is both the most robust part of the icon and the part that carries
  identity -- a cam has a ring and no triangle.
* **The interior portrait is the same art as the killfeed portrait and the top
  roster portrait** (not the Tab scoreboard). That is a route to *identification*
  rather than detection, and it fits the mining convention already used for digit
  glyphs: the templates would be taken from Grant's own footage on two surfaces
  the pipeline already locates, rather than authored. It should be unusually
  tractable because **the minimap's own palette is narrow** -- grey, yellow,
  black and red -- so an agent portrait's colours are distinctive against it.
  Nothing has been built or measured here.
* **Omen's ultimate turns the minimap a fuzzy black for a few seconds** and is
  the only ability in the game that renders the widget unusable; Omen also
  teleports globally, so position continuity breaks across it. Detected and
  abstained on rather than tuned through -- see `minimap_temporal.USABLE_MIN`.
* **The local player's icon draws ON TOP of an enemy's** when they overlap.
  Deprioritised on Grant's call: it only happens at extreme short range, where
  the screen detector has a large unambiguous blob and does not need the minimap.

**SETTLED 2026-08-26, against 96 of Grant's hand labels on `a06f04a0059f`.
Two results, and the first one bounds the whole idea.**

**1. The premise HOLDS. Grant labelled 96 frames with the screen visible beside
the minimap and reports there was never a frame with an enemy present and no
icon.** That is the strong ring-and-triangle form of the claim, checked by eye
against the screen, and it is the best evidence the premise has ever had.

**A number I published as "58% -- not a proof gate" was wrong, and the error is
worth keeping.** The pre-kill pool samples 300-1400 ms before the killfeed entry
APPEARS, and the entry lags the kill -- so most of that window sits before the
enemy ever came into view. Grant: *the enemy is often only in view 400 ms or
less before the kill.* So the 42% of pre-kill frames with no icon are frames
with no enemy yet, not counterexamples.

    prekill  34/59 carry an enemy icon   57.6%
    uniform   4/37                       10.8%

Those numbers are real but they measure **"is an enemy icon on screen in this
frame"**, which is a fact about the sampling window, not about the premise. The
5x gap says the pool is doing its job; neither number tests the gate. I treated
"a kill happened 1.4 s later" as "an enemy is present now" without checking it,
and the whole conclusion followed from that one unverified denominator.

**Consequence: the sampling window is too early and has been tightened** to
0-600 ms before the entry, which straddles the kill given the lag rather than
preceding it. Frames labelled under the old window are still valid -- the marks
record what was actually there -- but the pool is biased toward the approach
rather than the duel.

**2. The seal test is dead at 4:2:0 and ring-fitting replaces it.** Scored
against the same labels:

    seal (hole test)                       0.0% recall
    ring fit, cov>=0.60                   37.2% recall / 76.2% precision
    ring fit, cov>=0.35                   79.1% recall / 61.8% precision

From zero to 79%. The fix came straight from Grant's observation that the ring
is a **teardrop, not an annulus** -- measured thickness by angle from the facing
triangle: 7.3 px at the triangle, 4.1/1.9 at +/-30 deg, and **1.1-2.0 px over
most of the rest**. Closure is topological, so it needs every pixel of that thin
arc to survive and one break loses it entirely; half-resolution chroma is
precisely what a 1-2 px colour feature does not survive. Fitting the circle that
best covers the arc, then testing the disc it encloses, needs no closing kernel
(the thing that merged adjacent icons in every earlier attempt) and degrades
gracefully instead of failing outright.

Both halves of the criterion are load-bearing and measured on one lossless frame:

    enemy icon   cov 0.85  r 10  inner_red 0.00     ring around a portrait
    red X mark   cov 0.33  r  6  inner_red 0.67     solid throughout

Ranking on coverage alone picks solid red things, since a disc's circumference
is fully red. And the radius must NOT float: with the search open to r=6 a small
surviving fragment always fits something, and the fit collapsed to r=6 with a
meaningless coverage on nearly every miss. The widget size is fixed, so the icon
radius is nearly constant -- letting it float gave away the strongest prior
available. Re-measure if the size slider moves.

**Z-order: the local player's icon draws ON TOP of an enemy's.** Grant found it;
at 13:00 only an 18 px, 7x4 sliver of the enemy ring survives underneath. This
happens at exactly the range a duel happens, so it hits the pre-kill pool
hardest, and no colour or shape work reaches it -- the pixels are not rendered.
The player's own icon is findable, so this is at least a *detectable* condition
rather than a silent miss.

COV_MIN 0.35 is fitted to 96 labels on ONE session and is provisional.

**Superseded detail: the enlarged minimap fixes the seal, and 4:2:0 undoes it.**

Rendering the minimap 800 ms before each of the 21 tracked kills gives a
contact sheet where an enemy icon is visible **by eye in most of them** — so the
premise holds in the strong form, not just the "there is red somewhere" form.
The finder fired on **1 of 21**. The finder is what is broken, not the premise.

Why, measured at four of those kills. Blobs of exactly icon size ARE found —
126-238 px at 14x19 to 30x21 — and then die on the seal:

    lossless, enlarged widget    hole_frac 0.69     seals cleanly
    4:2:0,    enlarged widget    hole_frac 0.00-0.09

Lowering the saturation cut to 85 and then 70 does not rescue it, with or
without the floor mask. **The ring's ~2 px band does not survive half-resolution
chroma**, so the portrait interior is never enclosed and the one feature that
separates an enemy icon from a red X mark is gone. This is exactly the
prediction made from the lossless round, now confirmed on a full match with a
killfeed anchor rather than on a single round with no denominator.

**The fallback if 4:2:0 has to stay: the triangle survives where the seal does
not.** `lobe` fires at 1.46-3.78 on these same blobs even at 4:2:0. A finder
built on red + icon size + lobe, with no seal requirement, is therefore possible
— but it has not been tested against the confounder that matters, and an X mark
has four arms, so its own angular profile is not flat. Measure it against
labelled X marks before believing it.

**INGESTED as `a06f04a0059f`** (profile `valorant-16x9-bigmap`, tags
`map:ascent, outline:red, minimap:large, chroma:420`) — 11608 L1 rows, 58 spans.
Grant's scoreboard K/D is **19/19**, now in `checks.KNOWN_KD`. Fully
out-of-sample -- nothing has been tuned against it, and it is the first session
recorded after the minimap change, so it also tests that the change cost the
killfeed nothing.

**It did not, but this is the widest gap in the set: 21/22 against 19/19,
delta +2 kills / +3 deaths, 5 events across 43.** Not yet investigated. The
Run It Back rule would explain deaths running HIGH against the board, which is
the direction seen here, but no agent has been checked. `verify` also flags one
score violation at 30:01 (`11 -> 1`), which is the known spurious-leading-1 OCR
defect already recorded for `9acf02f98283`, not a new fault.

Read rates are in line with the set: clock 47.7%, scores 48.8%, hp 85.1%,
ammo 46.5%. Final 13-11 over 24 rounds.

**The minimap line's next step is labels, and the tools are ready.**
`prototypes/label_minimap.py` samples 70% in the 300-1400 ms before each
killfeed kill (Grant's call, and correct: at a kill an enemy provably existed)
and 30% uniform over active play as the control — a pre-kill-only set cannot be
falsified, since a detector that always says yes would score 100%.
`minimap_icon_eval.py` then answers two questions, and **the first needs no
detector at all**: of the pre-kill frames, how many actually carry an enemy
icon. That is the premise, in the form that matters, and it has never been
tested — what was verified earlier is that no enemy frame had zero red PIXELS,
which includes X marks, Reyna blinds, Cypher cams and pings. If the pre-kill
rate is far below 100%, the proof gate is dead however good the finder gets.

**The ring+triangle finder now works** (`minimap_icon_scan.py`). Grant's shape —
a red-circled icon with a red triangle for facing — is measured as an angular
profile: a bare ring has the same outer radius at every angle, a ring with a
triangle has one sector reaching further, so the signal is the ratio of the
largest sector radius to the typical one. Dimensionless, so it survives the
widget being resized again. Verified on the one hand-checked frame:

    enemy icon  area 119  hole 261  hole_frac 0.69  lobe 1.54  facing -169
    red X mark  area  74  hole   0  hole_frac 0.00  lobe 0.00  facing none

-169 degrees is left, which is where the wedge is by eye. Two bugs got there
first and both are geometric: thresholding at `1.35 x max hole radius` counted
nothing, because an irregular hole already reaches the ring's inner edge; and
measuring from the BLOB centroid reported the facing 180 degrees out, because
the solid triangle drags the centroid into itself. The hole's centroid is the
ring's centre and is what the geometry actually says.

**2026-08-26, full game with the enlarged minimap (`2026-08-26 09-56-37.mp4`,
38.7 min, Ascent, standard 4:2:0). Two findings, and the second is the bigger
one.**

**The minimap finder gets almost nothing on it.** Scanning 599 frames yields 7
candidates; a contact sheet of all 7 shows **four are map geometry** (site boxes
and warm floor panels reading as red), one is an ability icon, one an ally, and
**one plausibly a real enemy icon**. The triangle-lobe feature returned 0.00 on
every candidate including the real one, so it is not working -- the lobe radius
is taken from the hole's *max* extent, which already reaches past the ring band,
so nothing is ever counted as outside it.

**The screen detector cannot anchor that number, and finding out why matters
more.** The plan was to use the verified premise -- an enemy on screen implies an
icon on the minimap -- to get a denominator without labels. It gave 0/44, which
looked catastrophic and is meaningless, because the anchor is contaminated. A
contact sheet of the 35 strongest detections (>= 500 px) on this capture shows
they are dominated by:

* **purple/violet foliage** -- Ascent's flowers, sitting squarely in the widened
  magenta band;
* **a magenta weapon skin**, firing repeatedly at a FIXED screen position
  (x 1360-1840, y 320-480, 36 of 125 detections in that band). The weapon mask
  is `y > 0.66h = 713`; the gun model reaches well above it, so the mask does
  not cover the skin.

Neither is in the recorded false-positive classes, and both are direct
consequences of widening the hue band to 130 -- the same knob that bought 22
points of recall. **The aggregate rate is unchanged at 0.42 detections/frame
(Ascent measured 0.40), so nothing looks wrong until you look at what the strong
detections ARE.** A summary statistic hid it completely; the contact sheet took
one glance.

Two consequences worth acting on: a **weapon skin is a per-session property like
the outline colour**, and a magenta one defeats a magenta-widened detector; and
the weapon mask's vertical bound is wrong for a raised gun model.

**Not established either way: the premise itself.** Note that the recorded
verification is that no enemy frame had *zero red on the minimap* -- red PIXELS,
not an enemy ICON. "There is red somewhere" and "there is a ring-plus-triangle
icon" are different claims, and only the first was ever measured. The second is
what a bearing or a proof gate needs. My 24 missed minimaps mostly carry no red
icon, but since the anchor was contaminated those frames probably carried no
enemy either, so they are not evidence against it. **This needs a real anchor:
ingest the capture and use killfeed kills**, where an enemy provably existed.

**2026-08-26, enlarged minimap: the ring DOES seal, and 4:2:0 takes it away
again.** `prototypes/minimap_icons.py`, run on the lossless round (which carries
the enlarged widget). The blocking finding at the old size was "the ring does
not seal, and the closing radius that would seal it merges adjacent icons".
Measured side by side on one frame, with no closing applied at all:

    enemy icon   27x21, area 119, SEALED, hole 261 px, hole_frac 0.69
    red X mark   13x13, area  74, open,   hole   0 px, hole_frac 0.00

That is a **complete** separation where the old size gave a soft 0.76-against-
0.92 overlap, and it is the discrimination the whole minimap line was blocked
on. Only 3 blobs in that frame; the flood is gone.

**Two corrections were needed before it was visible, and both were mine.**

* `SAT_MIN` 120 -> **100**. At 120 the ring does not seal *at all* (hole 0); at
  100 the same icon encloses 261 px. The ring's outer half is anti-aliased
  against the map and its saturation falls between the two, so a cut 20 points
  too tight opens the ring and destroys the only feature that identifies it.
  This is "never test an absolute level against this HUD" biting on the minimap.
* The **floor mask had to be re-derived**: `sat < 20`, not `sat < 60`, and the
  largest connected component only. At `sat < 60` it took **83%** of the ROI --
  admitting the hazed background wholesale. Value cannot do this job here
  because the background is BRIGHTER than the floor (map slab S=0 V=118;
  scenery through the transparent part S 36-58, V 97-140), so the old
  `val > 110` passes it. Skipping the floor mask entirely, which I did first,
  reproduced the original failure exactly: median "icon" area 956 px, diameter
  59 -- scenery, not icons.

**What is NOT established: the rate.** Only 3 of 120 sampled frames yield an
icon-shaped seal in lossless. That number is **uninterpretable** without knowing
how many of those frames contain a minimap-visible enemy at all, and this
capture has no labels and is a single remade round. Do not quote it as recall
in either direction.

**What IS interpretable, and it is the actionable part: 4:2:0 collapses it.**
Same frames, subsampled:

    sealed blobs        31.8% -> 15.4%
    icon-shaped seals    3/120 -> 0/120

So the enlarged widget and the lossless codec are two changes at once, and the
chroma half of it is doing real work. **A full-length capture at standard 4:2:0
settings will be materially worse for the minimap line than this round
suggests.** Same mechanism as the screen rim (see the chroma section above): the
ring is ~2 px of colour, and half-resolution chroma averages it into the map.

Next step is the rate, and it needs an anchor rather than more tuning: an enemy
icon must disappear when that enemy dies, and per-team alive counts come from
the killfeed, so an ingested session gives ground truth without hand labels.
The profile's `minimap` ROI is still the OLD size and must be re-measured with
`probe` before any enlarged capture is ingested.

**The minimap line is parked, and Grant is unblocking it on the capture side.**
He is recording a session tomorrow (2026-08-26) with a LARGER MINIMAP. That is
the right fix: five algorithmic approaches all failed on the same thing -- the
icon ring does not seal, and the closing radius that would seal it merges
adjacent icons -- and the ceiling was 77-79% of enemy frames where a proof gate
needs ~100%. Resolution is the binding constraint, not cleverness.

**What is already established there, so it does not need redoing:** the premise
survived adversarial review. An enemy on screen ALWAYS has an icon on the
minimap; all ten apparent counterexamples confirmed it (a dead enemy, a
question-mark icon for a revealed-but-not-visible enemy, and detection failures
with the icon plainly present). Hollowness is a real discriminator (red fraction
0.76 for enemy-frame blobs against 0.92 for empty) -- an icon rings a bright
portrait, an X mark is solid red. Icons are area 50-200; the slabs swamping empty
frames are 700-1150 and separable on size alone. When the bigger capture lands,
re-run those three against it before building anything new.

**Measured 2026-08-26: 4:2:0 chroma subsampling costs a fifth of the detector.**
Grant recorded one lossless round (`2026-08-26 09-16-10.avi`, Ut Video RGB,
5.7 GB for 60 s), which makes a controlled test possible for the first time:
degrade those exact frames and compare each with its own subsampled twin, so
scene, lighting and colour range are held fixed and only chroma resolution
moves. `prototypes/chroma_test.py`, 240 sampled frames:

    rim pixels surviving 4:2:0        65.6%
    top-hat at the reference rim      43.8 -> 27.6   (-37%, threshold is 25)
    SHIPPED detections                 103 ->   80   (-22%)

The rim is 1-4 px and its whole signal is chroma -- that is what the Lab `a*`
top-hat reads -- so storing chroma at half resolution averages it with the
background it borders *before the file is written*. Mean rim response lands at
27.6 against a threshold of 25: the surviving rim is one step from not being
there, which is exactly what the two adjudicated Lotus misses with **zero
top-hat response** look like. **This is a lower bound** -- it isolates
subsampling and excludes quantisation, because no ffmpeg is on PATH to do a real
encode.

Suggestive but not conclusive, because the scenes differ: the conditional shape
of rim strength in the H.264 library straddles the simulation, with Ascent
*below* pure subsampling, consistent with quantisation adding to it.

    lossless RGB          median 48   p75 65   share in 25-35  22.7%
      same frames 4:2:0   median 39   p75 48                   34.6%
    H.264 ascent          median 35   p75 45                   46.7%
    H.264 lotus           median 42   p75 52                   27.5%

**Do not read that ordering as explaining the map gap.** Ascent has the weaker
rims and the *better* recall (91.3% against Lotus's 76.2%), so rim strength is
not what separates the two sessions.

Lossless is not the fix -- 5.7 GB/round is ~226 GB for a 40-minute match.
**4:4:4 H.264/HEVC is**, and it keeps full chroma resolution at a fraction of
that. See item 12 under "Before ingesting any new capture".

**Also unresolved and worth an eye:** some corpses carry a red outline and some
do not, and no explanation survived testing. The obvious one -- the outline fades
with age -- is unsupported but the test is underpowered, because the killfeed
timestamps deaths without locating them and so cannot age an individual body.

Last worked 2026-08-25. **Fourteen sessions ingested, fourteen with scoreboard
K/D in `checks.KNOWN_KD`, and every one carries its map.** Thirteen are
scorable (`0f08b3dc3777` is the cropped capture and has no killfeed ROI). The
store is at **`hud-0.8.1`** throughout. **Nine of thirteen are exact and the gap is 8 events across 372.** Five of the
eight are Run It Back (see "Scoreboard divergence is a finding" below), one is
the ability-kill read error, and two are new and uninvestigated — see below.
Long tracks are 0. Nothing is half-applied and the tree is clean.

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

## Running

Always via the venv interpreter — there is no console script:

```
.\.venv\Scripts\python.exe -m reticle <command>
```

Default store is `~/reticle-store` (outside this repo); override with `--store`.
`fixtures/`, `teststore/`, `probe_*/`, `frames_*/` are gitignored scratch.

## Pipeline status

Stage numbers are the design doc's §3 stages, not release versions.

| Stage | What | Status |
|---|---|---|
| 00 Ingest | fingerprint → profile, manifest, no media copied | **done** (`probe`, `ingest`) |
| 01 Gate/segment | frame state → bounded play spans | **rule-based baseline** — `off`/`idle`/`active`, not the doc's trained buy/in-round/post-round/menu/spectate classifier. No labelled data yet. |
| 02 Deterministic extractors | HUD, killfeed, minimap, main-view | **partial** — see below |
| 03 Event proposal | fuse stage-02 into typed candidates | not started |
| 04 VLM adjudication | ambiguous band only | not started |
| 05 Reconcile | source priority + label-free invariants | invariants only (`checks.py`, `verify`). The scoreboard is now readable and outranks killfeed inference, but nothing reconciles the two yet. |
| 06 Metrics | pure versioned functions | not started |
| 07 Narrate/query | not started |
| 08 Correction loop | not started |

### Stage 02 detail

Built and populating in the store: round clock, both team scores, HP, shield,
ammo (mag + reserve), killfeed **entry count**, and killfeed **player
attribution** (kill/death, with the stack positions needed to count entries).

Built but not stored: the **Tab scoreboard** (`scoreboard.py`) — all ten rows'
K/D/A and which row is the local player's. `reticle board` reads it live off the
video; nothing writes it to L1 yet, which is the obvious next step if it starts
getting used for more than checking.

Not built: **credits**, **minimap position tracking**, **main-view detection**,
**combat report**.

Minimap position tracking is the gating dependency for the doc's peek-exposure
metric and for movement state generally; §2 calls the homography trivial, and
`MinimapMode.has_static_homography` records per session whether a single
constant transform exists — true for every capture from 2026-08-23 evening on.

The **combat report** (the post-death panel, right of centre) is the richest
unread surface in the game: per enemy it shows outgoing damage, incoming damage,
the hit breakdown, and kill / killed-you flags. That is engagement-level data
the killfeed cannot give. Two things to settle before building it: the panel's
height and vertical position vary with the number of enemy rows, so it needs
detection rather than a fixed ROI; and the banner name changes between deaths
(`Chef`, then `Harbinger` on one session), which may mean it follows the
spectated player rather than the local one.

## Checking against the game's own numbers

Two commands exist for this, and they are the only checks that compare against
something outside the pipeline rather than a domain invariant.

```
reticle kd    <session>          running K/D per round, from the killfeed
reticle board <session>          read every Tab scoreboard and score us against it
```

`board` is the stronger of the two: it reads all ten rows of the scoreboard and
identifies the local player's row by the yellow outline the game draws round it
(no name reading — see `scoreboard.py`). Per opening it prints the board's K/D
beside ours, so the first divergent row names a window of a minute or two rather
than a whole match. On `96aa1ae9b96f` it agreed exactly across 21 consecutive
openings before the first miss.

Ask Grant to open the scoreboard once a round when recording; it costs him
nothing and it is worth more than any invariant.

## Wallbangs are a finding, not just a parsing problem

The wallbang arrow is currently something to see past when reading a name, but
§4 already excludes wallbang duels from the aim metrics ("no visual contact") —
and an exclusion rate is itself diagnostic. A kill or death through a surface is
its own coachable category: prediction, recon and map knowledge rather than aim.
The icon is detectable, so capture it as a field on the entry when the icon list
lands, rather than only stepping over it.

## What this is for (decided 2026-08-25)

**Main goal: statistical relationships, via win probability.** Not "does X
correlate with winning" over named facts -- that design is arithmetically
doomed. A round yields *one bit* of outcome, so 262 rounds is 262 bits, and
conditioning splits it to nothing; at 242 scored rounds nothing separates from
baseline except the tautological survive/die pair, and adding facts makes it
worse rather than better because each one is another chance to find noise.

Instead: estimate P(win | round state) and value every event by how much it
moved that probability. State is small -- `(alive_us, alive_them, phase,
coarse_time, side, score_diff)`. The reasons this wins:

* a round passes through eight to ten states, so 262 rounds give ~2000
  state-transition observations rather than 242 outcomes;
* WPA is continuous, so effects resolve with far less data than a win/loss bit;
* conditioning is automatic. "Win% on first blood" stops being its own question
  and becomes the average WPA of the first kill, already conditioned on state.
  A 5v1 peek and a 5v5 peek are never averaged together, which is exactly
  Grant's objection to counting exposed angles;
* it handles the post-plant rule change natively, because phase is in the state.

**Co-equal goal: film retrieval.** The largest |WPA| events *are* the list of
moments that decided a session, so this falls out for free -- and it is the
delivery mechanism for everything else. Nobody changes behaviour from a
coefficient table; people change behaviour after watching themselves throw a
4v2. Highest value per unit of effort in the whole project.

**Standing constraint: metrics must stay versioned and stable**, so the
longitudinal question ("am I improving, on what axis, over months") stays open.
The version stamps already in the store are what protect this and are easy to
break casually.

**Deferred, not dropped: mechanical coaching.** Aim, peeks, positioning --
prescriptive rather than diagnostic, and it needs a different architecture: high
sample rate, engagement-level detail, minimap geometry. It continues on its own
track. It is *not* subsumed by the statistical goal, because statistics describe
the policy Grant already plays and can never say what a different policy would
have produced. That counterfactual gap is the ceiling of the main goal.

**Blocked, for now: opponent and meta priors.** Needs enemy positions, which no
capture of one's own screen contains.

**A goal in its own right: data quality.** With no labelled data and one
customer, a number that cannot be trusted is worse than no number, and this
session produced several corrections to confident claims. Cross-checks are a
feature, not scaffolding.

Fact tables follow from this: the **engagement** is the fact and the **round**
is a dimension, because there are five to ten times more engagements and each
carries richer covariates.

## How peeking actually works, and what to measure instead

Grant's domain knowledge, 2026-08-25. None of this is recoverable from the code
and the metric below makes no sense without it.

**Peek style is dictated by angle advantage, which is geometry.** If you are
*further* from the corner than the enemy, you see them first, so the correct play
is slow — slice the pie, take the angle in increments. If you are tight against
the corner you have angle *dis*advantage, you will be seen first, and the correct
play is a wide swing: cross the exposed band fast and get full information at
once. Jump peeks and the rest are situational variants.

The computable form of that is a derivative. Let A(p) be the set of positions
with line of sight to p — the visibility footprint, a raster visibility
computation on the floorplan the median map already gives us. Then

    dA/ds  =  how much new territory can see you, per unit of your own movement

is exactly angle advantage. Far from the corner it is small: each step exposes a
sliver, so slicing works. Tight to the corner it is large: no increment is small
enough to be safe, so committing is right. **It needs no enemy positions and no
conditioning** — it is a property of where you are standing.

That gives two failure modes, and the second is the one worth telling a player:

  * dA/ds small, moving fast   — threw away an advantage the position gave you
  * dA/ds large, moving slow   — slow-rolling into an angle you were always
                                 going to lose

**Counting exposed angles is the other half, and it is conditional.** Grant:
wide-swinging when you reasonably expect one enemy is not a bad play, so a raw
count is not a verdict. Worse, peeking is driven by *priors* — where enemies
commonly are, which shifts with rank and a lot with map geometry. The
naive-but-honest treatment is statistical: record features per peek, learn the
empirical rate, report tendencies rather than judgements ("you wide-swing into
4+ angles with 3 enemies alive 18% of the time and win 22% of those").

Most conditioning variables are already in L1 or one step away: **enemies alive**
decrements from the killfeed, **teammates** from the killfeed plus the minimap's
ally rings, **time in round** from the clock, **region** from the callout label
above the minimap. The outcome — did a duel follow, was it won — is the killfeed
again. This is where the "engagements without a kill" question below stops being
academic: duels that produced no killfeed entry are disproportionately the ones
that went badly, so omitting them flatters every number.

Order of attack: build dA/ds first because it is unconditional, and leave the
angle count as a statistical layer on top.

Standing limits, none cheap to fix: **no elevation** (the floorplan is a
silhouette, so a bridge and the floor under it are one region), **no cover
objects**, **jump peeks are invisible** (vertical motion is not on the minimap,
so a jump peek reads as a fast peek), and dA/ds aggregates every occluding edge
in play rather than naming the one you mishandled.

## Sampling densely where it matters, without poisoning the sample

Open, 2026-08-25. Peek work needs 15-20 Hz and the whole capture does not
deserve it, so some form of proportional sampling is wanted. Two passes is the
shape the design doc already implies -- §3's cost rule ("if the expensive layer
ever sees more than ~1% of frames, stage 01 is wrong") is about the VLM band,
but the principle is the same: a cheap pass decides where the expensive pass
looks.

**The trap is gating on outcome.** Sampling densely where shots were fired, or
where a killfeed entry landed, seems obvious and is wrong for the same reason
already recorded under "engagements without a kill": a peek that exposed five
angles and met nobody is not a non-event, it is the control group. Gate on
contact and the model only ever sees peeks that drew a duel, which flatters
every number and cannot be corrected after the fact.

**Gate on opportunity instead.** dA/ds is a property of the *map*, not of the
round -- so it can be precomputed once per map as a scalar field over the
floorplan, and "is the player near a cell where exposure changes fast" is then a
lookup rather than an inference. That gates on geometry the player was moving
through, entirely independent of whether anything happened, which is exactly the
independence the statistical layer needs.

That also settles the hard-code-versus-infer question for this case: the field
is *derived* from the floorplan rather than hand-authored, but it is *static*,
so it costs nothing at query time. Nothing about round phase needs hard-coding
-- "start of round is high value" is a proxy for "everyone is alive and moving
into position", and the geometry gate captures the part that matters without
assuming it.

Practical note: seeking is expensive in H.264 and contiguous decoding is cheap,
so the second pass should decode *ranges*, not scattered frames. Windows, not
samples.

## The top HUD says more than it looks like

Measured 2026-08-25 off `9acf02f98283`, and it collapses three open problems.

**Alive counts are directly readable.** The roster bars draw a portrait only for
a player who is *alive* -- it disappears on death -- so counting portraits gives
both teams' alive counts as a per-frame state. No integration of killfeed
events, no error accumulation. `hud_roster` already covered the friendly side;
`hud_roster_enemy` now covers the other, measured at px ~1167..1467.

**That is also a continuous audit of the killfeed.** The roster is state and the
killfeed is events, so a running killfeed total should always agree with the
roster count. Where they diverge, an entry was missed -- and unlike the
scoreboard, which gives ~50 checks a match at best and 5 at worst, this checks
every sampled frame. It is the densest validity signal available and it costs
one new ROI.

**Allies are on the left, enemies on the right.** The roster bars are green-left
and red-right, which independently confirms what `rounds.infer_player_side`
derived statistically from eleven sessions. Two unrelated methods, same answer.

**The spike icon sits in the scoreline ROI.** When the spike is planted the
round timer is replaced by a red spike graphic, centre-screen, for the whole 45
seconds -- inside a region already being cropped. That is the persistent
indicator `rounds.py` wants instead of the one-sample clock discontinuity it
currently uses, and it needs no new ROI at all.

It probably also explains a standing oddity. Clock read rates sit at 33-60% and
`9acf02f98283` is 39.7%; planted rounds have no clock to read, because the spike
graphic is where the digits would be. Some unknown share of "unreadable" frames
are not misreads at all -- they are frames with nothing to read.

## Scoreboard divergence is a finding, not an error

The killfeed and the scoreboard answer different questions, and where they
disagree the killfeed is often the one worth keeping. A death inside Phoenix's
Run It Back never reaches the scoreboard, and a Kayo ult down may not either —
but both are duels that were lost, and §4's metrics are about duels, not about
the end-of-match tally. Grant's position (2026-08-25): **perfectly matching the
scoreboard is not the goal.**

So `checks.KNOWN_KD` measures two different things at once and they must not be
conflated:

- a **read error** — the extractor got the pixels wrong. A missed entry, or an
  entry attributed to the wrong side. This is the number that should go to zero.
- a **definitional divergence** — the extractor read the entry correctly and the
  game simply does not count it. This should be *labelled*, not eliminated.

At `hud-0.8.1` the 6-event gap is one read error (`c40d950031bb` 13:14, the
ability kill) and five Run It Back events, all verified. Quote the read-error
count as the quality number.

Verifying them is what found the `hud-0.8.1` defect along the way: the one
divergence `board` could see on `ff636d173b07` was a real double-count, not a
Phoenix death. That session has only 5 openings in 45 minutes, all before 12:03,
so `board` could say nothing about the rest — the sharpest argument yet for
asking Grant to open Tab once a round. 79 openings pinned a miss to a single
round on `223d636bf8d2`.

This raises the value of recording a revive mark rather than lowering it: the
point is not to drop those events to match the board, it is to tag them so
stage 06 can include or exclude them per metric. A kill undone by a Sage revive
is also its own coachable category, the same argument as wallbangs above.

## Open design question: engagements without a kill

The killfeed only fires when someone dies, so keying stage 03 on it alone would
measure a biased subset. Counted from the store, shots fired outnumber killfeed
events **2.6 to 1** (400 shot bursts against 153 attributed entries across the
six sessions, and that is a floor — 2 Hz sampling collapses any burst shorter
than half a second into one sample). Damage taken outnumbers them 3.7 to 1.

The bias has a direction: a duel where the player fired and nobody died is
disproportionately a duel they *lost* or flubbed. Measuring only duels that
ended in a kill would flatter every one of the doc's three metrics — that is a
validity problem, not just missing coverage.

The signals are already in L1 and need no new extractor:

- **`ammo_mag` falling between samples is a shot fired** (already noted in
  `store.py`). Bursts of it bound an engagement.
- **`hp` + `shield` falling is damage taken**, which catches engagements the
  player never shot in.
- The killfeed stays what §2 calls the bootstrap: it is the *labelled* subset,
  the anchor that says a duel definitely happened and who won it.

So the answer is almost certainly no, do not ignore them — but nothing depends
on this until stage 03 defines what an engagement is, and the sample rate
probably has to rise for shot-level timing to mean anything.

## Debugging what the extractors see

`reticle overlay` renders the detections onto the capture as a video. It reads
no stored HUD and writes no L1 — every annotation comes from calling the real
extractor on that frame, so it cannot disagree with what `hud` would record.
Keep it that way: a debug view with its own copy of the logic is worse than none.

```
reticle overlay <session> --from 7:35 --seconds 25            # a window
reticle overlay <session> --from 2:40 --to 4:40 --entries-only  # only frames with a killfeed entry
```

Per killfeed entry it draws the band, the weapon-icon divider, the two name runs
with their pixel widths, and both match scores against the threshold. Colour is
the language: green kill, red death, grey not-the-player, **amber** an overlay
covers the name so attribution was refused, **magenta** unparsed. Amber and
magenta are the ones to chase; so is grey on an entry that visibly reads `Me`.
The calibrated overlay mask is drawn too, so you can see what it ate.

Text is rasterised before `--scale` is applied, so use `--scale 1.0` when
reading values and a smaller scale only for skimming.

**To audit a whole session's entries at once, build a contact sheet**: crop the
band for every tracked event into one tall image, one row per entry, labelled
with its timestamp. Twenty-four rows fit in a single glance, which is how the
four Phoenix marks on `ff636d173b07` were found and counted. Far cheaper than
scrubbing an overlay video, and it is the right tool whenever the question is
"which of these entries carries X" rather than "what happened at time T".

## Open defects

- **One known read error, plus two unexplained**, across 372 events at
  `hud-0.8.1`. The raw gap against `checks.KNOWN_KD` is 8 events, from 24 at
  `hud-0.6.0`: five are verified Run It Back, one is the ability kill below, and
  two are `e37fdeca944f`'s missing deaths, which nobody has looked at yet. See
  "Scoreboard divergence is a finding" above before quoting the 8.
  `killfeed.py` has the per-session table.
- **The one real miss left is an ability kill.** `c40d950031bb` 13:14,
  `HungryHamster5 ⊗ Me`, killed by Raze. There is no weapon icon, and the
  ability mark fragments under the white-text cut into pieces too small to be a
  divider candidate, so the band goes *unparsed* and the death is lost. Reading
  it needs a divider that does not depend on the icon — the boundary between the
  two plate colours is the candidate, and it needs no list of icons. A prototype
  landed the split correctly on 6 of 8 test bands; the estimator needs to be
  edge detection on the plate chevron rather than a brute-force search.
- **A single-frame detection is discarded** (`KF_MIN_OBS = 2`), which is right —
  but it means any detection fault that thins a track to one frame costs a whole
  event rather than degrading it. Four of the five misses Grant found by hand on
  `9acf02f98283` were exactly that; the fifth formed no band at all. When hunting
  a miss, read `kf_entries` either side of it before looking at attribution: a
  lone frame is the tell.
- **Absolute brightness is the known soft spot.** `TEXT_V_MIN` (200) and
  `PLATE_V_MIN` (140) are absolute levels, tuned across captures that all share
  one set of video settings, and nothing has tested whether they survive a
  different one. No fix since `hud-0.6.0` has added another — the warm-scenery
  fault had a working fix that just raised `PLATE_V_MIN` to 160 and it was
  dropped for a structural test instead. The ability icon above fragments
  precisely because of `TEXT_V_MIN`.
- **No list of killfeed icons is needed, and none was used.** Valorant draws
  marks between the weapon and the victim name (headshot, wallbang) and in the
  weapon slot itself (abilities). Rather than enumerate them — which would never
  finish, since each patch can add more — `killfeed.py` keys on what a *name*
  is: several glyphs rather than one solid shape, with names on both sides of
  the divider. That handles unseen icons for free.
- **Two sessions are not clean comparisons, and both for the same reason: the
  killfeed and the scoreboard genuinely disagree.** `ff636d173b07` is a Phoenix
  game, `bfad2778a372` has an enemy Phoenix, and both are now fully explained by
  the same rule — see "Settled" above. Do not tune the extractor against either.

  The rule, from Grant: **Sage and Clove revive after a real death and that
  death counts; Phoenix and Kayo grant the second life before the fact — Run It
  Back ends in a self-kill or a real kill and then returns him, Kayo can be
  downed and either finished or picked back up — and those never counted.** It
  applies to the kill side as well as the death side.
- **Thin tracks are the leading indicator.** An entry seen in <=4 of a possible
  ~12 sampled frames is either barely caught or about to be split in two. If a
  new capture reads badly, count these first — 7 of 290 across the set now. A
  count *above* ~12 used to mean the opposite, two entries merged into one; the
  divider ended that and there are now none anywhere, so one appearing again is
  a signal that something upstream broke.
- **Fixed at `hud-0.8.0`: the entry tracker could not tell a merge from a
  split.** Matching by nearest slot merged consecutive entries reusing a vacated
  slot; matching by most-recently-seen shattered genuine doubles and scored
  worse. Slot plus time never contained the answer. Each entry's divider column
  does — see `killfeed.divider_of_ys`. It rules a match *out* only: two entries
  with the same killer, victim and weapon render at the same column, so equal
  dividers prove nothing.
- **An overlay can delete a killfeed entry outright.** The occlusion mask blanks
  pixels, so a row behind the shooting-error box may not reach `PLATE_ROW_FRAC`
  and the band never forms — the entry is not reported occluded, it is simply
  absent. The row profile is now measured over *visible* pixels only, which
  recovers the partly-covered bands (`223d636bf8d2` went from 14 to 30 frames
  correctly reported as unattributed), but a row almost entirely behind the box
  is unrecoverable. That is a capture fix, not a code one.
- **Scoreline OCR drops a transient extra digit.** On `9acf02f98283` the score
  reads `1 → 11 → 1` and `9 → 19 → 9` within half a second, i.e. a spurious
  leading `1`, and `verify` flags 8 violations there. Single-sample, reverts
  immediately, and unrelated to the killfeed. Clock read rate on that session is
  also low (39.7%). Worth a look when next in `ocr.py`.
- **`README.md` is stale.** It says HP, ammo and the killfeed are unbuilt; they
  are built, and it still describes stage 02 as scoreline-only. Fix it when next
  touching that area.
- **A dead player spectates, so the main view is not theirs.** Found while
  checking ally rendering: `9acf02f98283` 24:50 shows the combat report, "SWITCH
  PLAYER", and a teammate's first-person model. Nothing currently detects this
  -- `spans` knows off/idle/active and not spectating -- and every main-view
  metric is wrong on those frames, because the camera, the crosshair and the
  hands all belong to somebody else. Aim, crosshair placement and enemy
  detection all have to exclude them. The combat report panel is a usable
  marker, and so is the killfeed: the player is dead from their death entry
  until the round ends.
- **Health is not a death signal.** `hp` going unreadable was used as an
  independent death estimate and it is not one — it also goes unreadable in buy
  phase, while scoped, and while spectating. On `b3b9defb6fd7` it produced 20
  "deaths" of which most were a *teammate* dying. Don't reach for it again.

## Before ingesting any new capture

1. **Check the crosshair position.** It must sit at frame centre — (960, 540) at
   1080p. (1280, 720) means OBS is compositing a larger render onto a smaller
   canvas at 1:1 and part of the HUD is *not in the file*. Fix it in OBS.
   `valorant-16x9-crop75` exists only to salvage already-recorded captures
   (`0f08b3dc3777` is one).
2. **Set Valorant's performance stats to text-only**, not graph or both. The
   graph column covers the lower half of the killfeed ROI and cuts usable entry
   slots from six to three — losing exactly the multikills worth measuring.
3. **Turn the shooting-error readout off**, or move it out of the top-right. It
   lands at killfeed-ROI x 337-461, y 136-198, covering 59% of the victim name
   box in stack slot 3 and 26% in slot 4 — precisely where a death is read.
   Entries under it are counted as `kf_unattributed` rather than guessed, so it
   costs lost deaths, not wrong ones.
4. **Run `probe` and look at the frames.** ROI fractions are guesses until you
   have. Everything downstream is wrong until they are right.
5. **Record the minimap settings.** Only fixed + always_same + uncentered gives
   a constant minimap→world transform. Pass
   `ingest --minimap-mode "fixed/always_same/uncentered"`; it lands in the
   manifest.
6. **Label the map.** Grant is labelling maps for future captures. Geometry
   should be shared between sessions on the same map rather than re-derived per
   session, and nothing currently knows which map a capture is.
7. **Keep the enemy highlight on, and record its colour** as an `outline:<c>`
   tag at ingest. Valorant outlines enemy models in a colour the player picks --
   red on every capture so far, but yellow and at least one other exist -- so it
   is a per-session property like the minimap mode, and nothing should hardcode
   it. Turning it off entirely would put enemy detection back into
   model-recognition territory.

   **Allies are rendered through walls in buy phase**, as a solid teal
   silhouette -- clearly visible at `9acf02f98283` 9:09. Sampling forty live
   frames found no ally silhouettes, and every green blob there had a mundane
   cause: foliage, and the spectated player's own teal gloves. So the rule is
   not "any outline is an enemy" but **"any outline in the session's enemy
   colour is an enemy"**, which is why that colour is tagged. It also means the
   enemy outline should never be set to green, or the two stop being separable.

   The outline is what makes this tractable. A saturated-red mask over the main
   view returns a few hundred pixels in a 2-megapixel frame -- enormously
   specific -- and the blobs come out human-shaped: 16x44 at aspect 2.75 on a
   standing enemy at 9acf02f98283 4:23.

   Four things carry it, and only the first is a target: a **visible enemy**, a
   **revealed** one outlined through geometry by Sova or Fade (not shootable, so
   it must stay out of aim statistics, but it is a direct measurement of what the
   player knew), a **deployable**, and a **corpse** -- bodies stay outlined, and
   a corpse is the dangerous one because it sits exactly where a real enemy just
   was, so counting it as target acquisition would look reasonable and inflate
   every aim number.
8. **Confirm the minimap is fixed, not rotating, and not side-swapping.**
   Grant sets it that way deliberately -- Valorant's defaults both rotate the map
   with the player and mirror it between attack and defence. It is the setting
   that makes map geometry shareable between sessions and bearings comparable
   across rounds, and a capture recorded with defaults breaks that **silently**:
   position extraction still returns answers, they are just rotated or mirrored.
   Same class of per-session setting as the enemy outline colour above.
9. **Record whether the weapon is left- or right-handed.** Toggleable, and it
   mirrors the view model across the vertical axis. The enemy detector masks the
   player's own weapon by region -- the one place persistence provably fails --
   so the wrong handedness breaks it in both directions at once and silently:
   the mask covers empty screen on one side, costing recall on enemies peeking
   there, while the weapon sits unmasked on the other, costing precision.
10. **Record the minimap size.** Grant is enlarging it from 2026-08-26. Icon
    extraction is resolution-bound, not algorithm-bound: at the original size an
    icon is a ~12 px ring around a portrait, the ring does not survive
    thresholding intact, and every approach tried topped out at 77-79% of frames
    that provably contain a visible enemy. A larger widget should move all of it.
    Record the size per session -- geometry and icon thresholds both scale with it.
12. **Record in 4:4:4 if the encoder allows it, and record which was used.**
    Measured 2026-08-26 (see "4:2:0 chroma subsampling costs a fifth of the
    detector" above): 4:2:0 alone destroys 34% of enemy-rim pixels and 22% of
    detections, on identical frames. The enemy rim is 1-4 px of pure chroma, so
    half-resolution chroma averages it away before the file exists — and no
    algorithm recovers what was never written. This is the same class of
    capture-side constraint as the minimap size, and the same lesson: the
    binding limit is what reached the file.

    Lossless is *not* the recommendation — 5.7 GB per round is ~226 GB for a
    match. NVENC HEVC (and AV1 on newer cards) supports 4:4:4 at ordinary
    bitrates; that is the setting worth changing. Keep the lossless round as a
    reference capture, because a controlled A/B needs an undegraded source and
    it is the only one that exists.

13. **Check whether the minimap has an opacity setting.** Unresolved. The widget
   being semi-transparent over the void is the single largest difficulty in
   minimap extraction; if it can be made opaque most of that goes away for
   future recordings. Same class of fix as the shooting-error readout above.

## Conventions that are load-bearing

- **Never test an absolute level against this HUD.** It is composited over
  live scenery, so any absolute threshold eventually measures the world instead
  of the widget. This is not a series of unrelated bugs, it is one property of
  the game, and it has now produced: the killfeed row profile merging warm walls
  into a band; the minimap's void defeating background differencing, a
  persistence mask and every colour statistic; the roster bar's white health
  pips vanishing against a white wall; washed-out killfeed entries; and the
  victim's plate reading as enemy everywhere because scenery past the entry's
  right edge is warm. Every fix has had the same shape — **measure inside the
  structure, require coverage, compare relatively.** Density within the row's
  own entry, not across the ROI. Slot texture against neighbouring slots, not a
  threshold. A plate column that spans the band's height, not one that is merely
  the right colour. Reach for that shape first; it has never once been wrong.

  **But relative does not mean instead of absolute.** Structure answers "is this
  a thin rim against its surroundings"; level answers "is this the colour we are
  looking for". They are different questions and neither substitutes for the
  other -- the plate test above needs coverage *and* colour, and it is right to.
  Reading this convention as "replace absolute with relative" produced an enemy
  detector that fired confidently on a grey line beside a cyan panel, because a
  top-hat is a local peak finder and every image has local peaks. Adding a
  permissive absolute floor back underneath it nearly doubled precision. The
  floor's job is only to reject things that are not the colour at all; it must
  never be the test that decides what counts as red *enough*, which is the
  mistake that started the whole sequence.

- **The enemy outline is red *through magenta*, not red.** Measured at 47 hand
  labels on 9acf02f98283: the rim sits at OpenCV hue 171-179 and 0-1, 88% of rim
  pixels inside `(h < 10 | h > 170)`. But every miss that failed on colour sat at
  hue **132-160** with *zero* pixels in that band -- while still carrying `a*`
  173-207 and saturation 243-255. They are not faint, they are the wrong hue.
  The cause is tinting: **anything that colours the model shifts the rim toward
  magenta while leaving `a*` high** -- smoke the enemy is standing in, and Reyna's
  ult, which renders the model purple. Widening the band's lower edge from 170 to
  130 took recall from 69.6% to 91.3% for under two points of precision.

  The direction matters as much as the width. Orange scenery -- a confirmed false
  positive on a building at 38:03 -- lives just *above* hue 10, so the band must
  grow downward into magenta and stay tight on the orange side. Widening
  symmetrically, which is the reflex, buys the false positives and not the misses.
  Outline colour is also a **player-toggleable setting** (yellow exists, and at
  least one more), so this band is right for these captures, not universal; it is
  a per-profile value the moment a capture uses a different setting.
- **An ablation is only valid for the configuration it ran in.** Dropping each
  gate in turn showed the saturation and `a*` floors to be completely inert --
  removing either changed one false positive out of a hundred. The obvious
  conclusion, that they were dead weight, was wrong. They were inert only because
  the *hue* gate upstream was already rejecting everything they would have caught.
  Widening that band made both live again, worth 20 false positives between them.
  Deleting them on the ablation's evidence would have given back a fifth of the
  precision the widening was for. Re-measure a gate after changing anything
  upstream of it; "contributes nothing" is a statement about a configuration, not
  about a gate.
- **Never guess a value.** A field the extractor cannot read stays `null`.
  Everything is range-checked before return — a clock of 7:41 is a misread, not
  a fact. This is what makes `checks.py` meaningful.
- **No model in stage 02.** The HUD is structured data rendered as pixels:
  threshold → connected components → geometry filter → normalise → nearest
  template. Digit templates are *mined from Grant's own footage* (`glyphs`),
  not from a font file, and committed as `.npz` keyed by profile.
- **Version stamps drive recompute.** Bump `EXTRACTOR_VERSION` → re-decode;
  `SEGMENTER_VERSION` → spans recompute from stored L1 in milliseconds;
  `HUD_VERSION` → re-read (needs pixels, so it re-decodes).
- **`segment` must never open the video.** Recomputing spans from stored L1 is
  the whole point of the L0/L1 split, and it is what makes threshold sweeps
  free. `hud` is the one stage that legitimately re-decodes.
- **Raw media is never copied.** Manifests point at where the file lives.
- **Deaths per round is not a usable invariant** — Sage resurrect and Clove
  self-revive both let a player die twice in a round.
- Cost rule from §3: if the expensive layer ever sees more than ~1% of frames,
  stage 01 is wrong. Fix gating before buying compute.
- **Commit whenever a result is verified. Standing authorisation -- no need to
  ask.** The bar is "a measurement reproduces" or "a section is written", not
  "the task is finished". A session that reached 93.5%/35.0% then carried 500
  insertions of verified work in the working tree while running destructive
  edits against it; a patch that split the file on a section marker discarded
  every function in it, and the work survived only because it could be
  reconstructed from earlier in the same conversation. Small commits also make
  `git show HEAD:path` a real recovery tool -- it has already restored notes
  deleted by a careless rewrite once.
- **A parse check is not a verification.** `ast.parse` reported "parses clean"
  on the gutted file above, because a module containing only a docstring is
  valid Python. Syntax checks cannot see missing behaviour. After any structural
  edit, re-run the thing and confirm a **known number** comes back -- for the
  detector that is TP 43 / FN 3 / FP 80. That check is only meaningful because
  the number was measured before the edit, so measure first, then edit.
