"""PROTOTYPE: screen-space enemy detection, scored against hand labels.

    python prototypes/enemy_detect_eval.py <session> [thr k area hmin ck]

Best measured, on 149 hand-labelled frames / 46 labelled enemies of
9acf02f98283:

    detect() alone, single frame        91.3% recall, 41.2% precision
    + track_filter() over a sequence    91.3% recall, 48.8% precision

Scored on LABELS, not on tracks -- a label hit by two detections survives losing
one, so these do not match the per-detection tables further down.

The knobs are not independent and the whole curve is worth seeing before picking
a point:

    TOP1  MINTRACK   recall  precision
    off      1        93.5%     35.0%     <- no filtering
    off      3        93.5%     42.2%     <- persistence is FREE
    0.90     3        91.3%     48.8%     <- shipped
    0.60     3        84.8%     57.4%
    0.60     5        78.3%     65.5%     <- best F1, but a third of enemies gone

**Persistence at len>=3 costs no recall at all.** If only one filter is wanted,
it is that one; TOP1 trades 2.2 points of recall for 6.6 of precision.

99% precision is not reachable this way, and it is worth being concrete about
why: it means removing 79 of 80 false positives, where these filters remove 26
at no recall cost. The best precision available at >=90% recall is 48.8%. The
route to substantially better is not a sharper threshold on a blob -- it is a
signal that rejects whole FRAMES, and the minimap is the candidate (see below).

One session, one enemy-outline colour setting; nothing here has been tested
across sessions yet, and every cut point is fitted to this one.

The outline is red THROUGH MAGENTA, not red
-------------------------------------------
This was worth more than every threshold in the file put together, and it was
found by asking why specific misses failed rather than by sweeping.

Measured at the 47 labels: the rim sits at OpenCV hue 171-179 and 0-1, with 88%
of rim pixels inside `(h < 10 | h > 170)`. Every miss that failed on colour sat
at hue **132-160** with *zero* pixels in that band -- while still carrying `a*`
173-207 and saturation 243-255. They were never faint. They were the wrong hue.

The cause is tinting. **Anything that colours the model shifts the rim toward
magenta while leaving `a*` high**: smoke the enemy is standing in, and Reyna's
ult, which renders the model purple. Widening the band's lower edge from 170 to
130 took recall from 69.6% to 91.3% for under two points of precision.

Direction matters as much as width. Orange scenery -- a confirmed false positive
on a building -- lives just *above* hue 10, so the band grows downward into
magenta and stays tight on the orange side (6, not 10, which was worth 4 false
positives at no recall cost). Widening symmetrically, the reflex, buys the false
positives and not the misses.

Outline colour is a **player-toggleable setting** (yellow exists, and at least
one more), so this band is right for these captures, not universal.

An ablation is only valid for the configuration it ran in
---------------------------------------------------------
Dropping each gate in turn showed the saturation and `a*` floors to be inert:
removing either changed one false positive in a hundred. The obvious conclusion,
that they were dead weight, was wrong. They were inert only because the *hue*
gate upstream already rejected everything they would have caught. Widening the
band made both live again, worth 20 false positives between them.

Two full parameter sweeps were spent on those two constants before the ablation
showed they could not have mattered. Ablate first; it is far cheaper than
sweeping something inert, and it says which knob is even connected.

Gate-by-gate, at the pre-widening configuration (dTP / dFP when removed):

    sat          +0   +1     inert (see above -- became live after widening)
    a-star       +0   +1     inert (ditto)
    ownmask      +0   +0     inert, deleted
    fill         +2   +8     bad trade, deleted
    aspect       +0  +26     kept
    hollow       +0  +15     kept
    area         +1  +30     kept
    hmin         +1 +110     kept, the single biggest filter
    weapmask     +0  +14     kept

The rim light, and how it got there
-----------------------------------
The outline is a **rim light**: red *relative to what it borders*. Against a
dark wall it is vivid; against Ascent's terracotta it is barely there. A
morphological **top-hat on Lab's a-star channel** keeps structures thinner than
its kernel and removes anything larger, whatever the background level -- exactly
the difference between a 1-4 px rim and a brick wall.

    absolute red, S>150             53% recall,  3% precision
    + hollow-rim shape filter       30%         10%
    top-hat on Lab a*               85%          6%
    + shape filters                 57%         32%
    + shape tests only on big blobs 75%         11%
    + vertical closing              77%         14%
    + absolute floor                69.6%       24.2%
    + magenta band, drop fill       91.3%       22.3%
    + tighter orange/sat/a*, ar1.15 93.5%       25.3%
    + combat-report box detection   93.5%       33.6%
    + bottom-left corner            93.5%       35.0%

Three misreadings, each fixed by looking at pixels rather than a summary:

1. **The outline is a rim, not a fill.**
2. **A shape prior needs the shape to exist.** Demanding hollowness of a sliver
   of an enemy -- a shoulder past a corner, which is where peeking happens --
   asks a question with no answer, and the filter answers no. Shape tests apply
   only to blobs big enough to be a body.
3. **A broken contour is not a small object.** The rim is interrupted by the
   body and by limbs, so connected components shattered one enemy into fragments
   that each failed the size tests. A vertically biased closing kernel bridges
   them, because a person is taller than wide.

UI is found by its own structure, not by masking screen area
------------------------------------------------------------
Half the false positives in a reviewed sample of 30 were UI, and the combat
report was most of it -- its crimson row stripes, red damage numbers and red
name banner are *genuinely red*, so no colour test will ever separate them.

Masking the region outright reached 40.2% precision at no measured recall cost,
with zero labels inside. It was still refused: the region is x 0.78-1.0 at
mid-screen height, which is exactly where an enemy peeking your right side
appears, and 46 labelled players is far too thin to conclude enemies never
appear in a quarter of the screen. That "0 labels inside" would have read fine
in a commit message and cost real detections later.

So the box is located per frame from its own structure. **A box is several
horizontal rules of the same width at the same x.** Rows carrying a long
horizontal edge run are its rules, so grouping them by shared x-span -- not by
y-proximity -- gives the bounding box directly, and only that rectangle is
excluded. Third-longest run rather than longest, because one long scenery edge
is common and three stacked ones is furniture. Cost is a 1/4-scale grey resize
and one Sobel.

Measured: panel in 62/149 frames, 5/5 by-eye panel frames found, 0/8 clean
frames, precision 25.3% -> 33.6% at **zero** recall cost.

`minrun` is the whole ballgame and the coverage table hides it:

    minrun 440   covers  1/15 UI false positives   (panel is ~408 px wide!)
    minrun 380   covers  8/15   -> precision 33.6%, recall 93.5%
    minrun 300   covers  9/15   -> precision 31.6%, recall 80.4%

At 300 it buys 5 false positives by swallowing 8 labelled enemies. The gap
between 380 and 300 is the difference between masking furniture and masking the
game, and it is invisible in the coverage numbers alone.

An earlier version of this grouped rule rows by y-proximity and took the median
x-span. It fired in 116/149 frames and removed almost nothing, because the
longest run in one row and the longest in the next are frequently different
structures, so the median described no real rectangle. It also searched the full
frame while the separation had been measured on a band, so every "clean" box it
found was the top HUD. Measure and build on the same region.

What did not work
-----------------
**Persistence could not find the player's own weapon.** It was roughly half the
false positives, so the killfeed's overlay-mask trick looked obvious. The
derived mask covered 0.7% of the frame and changed nothing, because the
first-person model bobs, sways and changes when the weapon does, so no pixel
responds often enough. **Persistence finds things that do not move, not things
that are always there.** A measured region works instead. The persistence mask
was later shown inert by ablation and deleted.

**A "player is dead" gate does not remove the combat report.** The panel's
timestamps cluster in time, which suggested it was a death artifact, and the
killfeed already knows when the player died. Measured: only 4 of 13 combat
report false positives occur while dead. The player holds Tab mid-round. The
hypothesis was clean, cheap to test, and wrong.

**Skipping Tab-scoreboard frames is not worth doing** as a frame gate: one frame
in 150 has the full scoreboard open. (The combat report is a different, far more
common panel -- see above.)

**A width profile does not work, and the redo settled it.** The original test
scored 1.8:1 and was compromised -- measured on the *closed* mask, whose vertical
kernel smooths away the detail a profile depends on. Recomputed on the raw
top-hat mask and scored leave-one-out, it separates 28.5%, which is *worse* than
the compromised number it was meant to rescue. The signature is real in the mean
-- enemies show a narrow head (0.15-0.24 of max width in the top two bins) where
false positives start wide (0.27-0.44) -- but individual profiles overlap far too
much. It was the most promising item on this list and it is now closed.

Second map: what actually costs recall (adjudicated)
----------------------------------------------------
Lotus (bdfdcf009dba, 303 frames / 65 enemies) run with Ascent's cut points
untouched: **76.2% recall, 42.5% precision, 0.2 FP/frame** against Ascent's
91.3% / 41.2% / 0.4.

Precision transferred and the adversarial test passed -- Lotus is pink-magenta
temple stone sitting INSIDE the widened band, the prediction was that it would
flood, and instead false positives per frame halved. Hue 130 is a property of
the outline, not a fit to Ascent's terracotta.

All 17 misses were adjudicated by eye. **None were corpses**, which refutes the
hypothesis that produced them. The statistic behind that hypothesis was real and
reproducible -- misses sat at a median 2.7s after a killfeed death against 5.2s
for detections, twice as likely to fall within 4s -- but the mechanism was wrong.
Deaths correlate with SHOOTING, and shooting produces muzzle flashes, tracers and
particle effects: six of the seventeen are obscured by exactly that. A
correlation with the right shape and the wrong cause, believed because two
earlier observations about corpses made it feel confirmed.

    combat effects over the enemy   6   muzzle flash, tracer, particles, scope
    tiny slivers                    4   gun+hand, bare gun barrel, a head
    agent colour / scene tint       4   Waylay x3, Clove under a green tint
    cluster not separated           2   one of three enemies in a group
    MISLABELLED muzzle flashes      2   corrected in the label file

Measuring the colour gates at each miss splits them by what actually fails:

* **zero top-hat response** (both gun barrels): there is no rim at all. No colour
  or size tuning reaches these. Grant identified them only from the minimap,
  which is the strongest argument yet that bearing confirmation is not a
  precision filter but the ONLY route to a class of enemy the screen does not
  carry.
* **size floor after gating** (Waylay x3, bare head, head over dune, scoping):
  6 to 76 pixels survive every colour gate and then fail AREA >= 120. This is
  the largest fixable class.
* **downstream rejection** (tejo at 6:26, twice): 332 and 779 pixels pass every
  colour gate and the detection is still lost, so shape, aspect or the closing
  merging the enemy with the muzzle flash is throwing away a well-found enemy.
  Bug-shaped, not threshold-shaped, and unexplained.
* **hue** (green-tinted Clove): 434 top-hat pixels, median hue 11, rejected
  because the orange edge is 6. A green tint pushes the rim UP toward orange
  exactly as smoke pushes it DOWN toward magenta -- the band was only ever
  widened in one direction, because that is where Ascent's misses happened to be.

**The orange edge stays at 6 anyway, measured on both maps.** Widening to 10
recovers that single enemy and costs 10-14 false positives on Lotus (precision
42.5% -> 38.3%); Ascent is flat on recall throughout. One compelling crop is not
worth a fifth of the precision, and the green-tint case is a singleton rather
than a class.

**Clustered enemies are not separated.** Three enemies standing together yield
fewer than three detections. The vertical closing kernel exists to merge one
enemy's broken rim and cannot tell those fragments from a neighbour's, so it
merges people. Untested and unfixed.

**Corpse outline persistence remains unexplained.** Some corpses carry a red
outline and some do not; 8 of 36 fire the detector. The obvious hypothesis, that
the outline fades with age, is unsupported (fired corpses median 4.0s since a
death against 3.0s for silent ones) but the test is underpowered rather than
conclusive: with 157 killfeed events ~95% of corpses sit within 12s of some
death, and the killfeed timestamps deaths without locating them, so it cannot age
an individual body.

Known error classes still open
------------------------------
From a hand-reviewed sample of 30 false positives:

* **UI that is not a box** -- "recon bolt destroyed" and spike-planted alerts are
  text banners, and box detection structurally cannot reach them. The top-centre
  region they occupy (x 0.42-0.53, y 0.17-0.28) is dead centre above the
  horizon, where a distant enemy on high ground appears, so it must NOT be
  masked positionally. It wants the same structural treatment.
* **An ally read as an enemy (Clove).** This is a direct consequence of the
  magenta widening, not a stray: Clove's colour identity is purple, and the band
  was widened precisely to admit purple-tinted enemies. The same knob pulls both
  ways, so it cannot be tuned out on the hue axis -- the discriminator has to be
  structural (a rim is a closed contour around a silhouette; costume colour is
  interior fill) or external (the roster and minimap already know who is an
  ally). Expect this to worsen on teams running Clove rather than stay flat.
* **Particle effects** -- weapon muzzle/impact particles and Killjoy molly
  particles, ~17% of the sample.
* **Enemy limbs scored as false positives.** A Reyna leg and a Killjoy leg are
  *correct* detections the head-click matcher cannot credit. With a probable
  unmarked enemy in the sample too, measured precision understates the detector
  by roughly 10%.
* **Clove smoke against map geometry** forming a tall thin human-like shape.

The four remaining misses are all at the size floor: 21, 42 and 45 px blobs
(a gun barrel through smoke is 9x6), plus one aspect rejection at 1.18 against a
1.15 threshold. A single frame does not carry enough evidence at that size, and
lowering `area` to reach them floods the false positives. This is the end of
per-frame tuning, not a threshold left untuned.

What the label set does NOT cover
---------------------------------
"93.5% recall" means recall *on the cases sampled*, and one case is missing
entirely: an enemy visible only as a **head above a box or an elevated edge**.
Grant reports no such frame came up while labelling. It is a standard strong
position, so its absence is a gap in the evidence rather than in the game.

It is also the hardest case here. A head alone is small, wider than tall, and
has no silhouette to match -- so the aspect and hollowness tests would reject it
if they applied. They do not, because those tests are size-conditional and a head
falls under the threshold, which means the design happens to treat it correctly.
"Happens to" is not "is shown to", and nothing has tested it.

The label set is also **centre-biased and must not be fitted to**: 97.9% of
labels fall in the middle third of the screen, because half the frames were
sampled just before a kill, when the player is by definition looking at the
enemy. A centre prior would score well here and be wrong -- exposure analysis
needs peripheral enemies most of all. For the same reason the **50% UI share of
false positives is inflated**: event-pool sampling lands on kills and deaths,
which is exactly when the combat report is up. In continuous play it will be far
lower, and that number must not be quoted as a production figure.

One label is known bad and excluded: at 29:54 the enemy had already been killed.

Fragmentation is the strongest shape signal found
------------------------------------------------
Measured over a battery of twelve raw-mask features, ranked by best achievable
(enemies kept - false positives kept):

    fragments        50.2%   TP med 13 pieces, FP med 5
    frag_top1        49.2%   share of mass in the largest piece: TP 0.38, FP 0.62
    aspect           37.8%
    shoulder_at      29.7%
    profile corr     28.5%   (leave-one-out; see above)
    solidity         12.5%   near useless
    compactness      11.3%   near useless

**An enemy's rim shatters into many pieces with no dominant one; a false
positive is a few pieces with the mass concentrated in one.** The fragmentation
that finding 3 above treats purely as a problem -- the thing the vertical closing
kernel exists to paper over -- is itself the signal.

It is not a size proxy, which was the obvious way for it to be a false discovery.
Within matched raw-area bands the separation *increases* with size (21.8%, 50.0%,
75.5%), and size alone scores only 42.5%. The mechanism is in the correlations:
`corr(fragments, area)` is **+0.75 for enemies and +0.05 for false positives**.
A long thin contour breaks up in proportion to its length; a compact blob's
piece-count does not depend on how big it is. Structurally different objects.

**Use frag_top1, not the raw count.** It is scale-free and separates in every
band (41.5 / 54.8 / 72.1%), where the raw count collapses to 21.8% in the
smallest -- and the smallest band is exactly where the four remaining misses live.

A second, weaker shape signal: whether the rim **seals into a silhouette** when
gaps are bridged at a small radius. Closing at 21 px seals 54% of enemies against
21% of false positives (2.6:1); a convex hull seals 98% against 89% and is
useless, because convexifying swallows the concavities that carry the shape.

Temporal: persistence works, relative motion does not
-----------------------------------------------------
**Persistence separates.** Over +/-250 ms at 50 ms steps, len>=3 keeps 98% of
enemy detections and removes 27% of false positives; len>=5 removes half of them
for 16%. That is safe to apply because the detector is stable: measured against
the labels it fires on a real enemy in a median of 9 of 11 samples, and 46/46
labelled enemies appear in at least two.

That last measurement mattered more than the filter. A first tracker reported a
median enemy track of 6 with eleven single-sample tracks -- a plausible-looking
modest signal that was entirely two bugs:

* **no gap tolerance** -- tracks were extended only from the immediately previous
  sample, so one missed detection ended a track and started a new one, shredding
  a 9-of-11 detector into short pieces;
* **an inverted camera-compensation sign** -- the prediction subtracted the phase
  correlation shift instead of adding it, which doubles the error during fast
  pans and blows the match gate exactly when the camera moves fastest. With the
  wrong sign there was NO separation at all: 86% of enemies against 84.9% of
  false positives, a diagonal.

The contradiction that exposed both -- "the detector sees it in 9 of 11 frames but
the tracker says 6" -- was findable in a way that "this number looks a bit low"
never is. Prefer measurements with a known-correct answer to check against.

**Relative motion is not recoverable, across five attempts.** Enemies do move
relative to the background and the game renders them that way, but what the
detector hands over is a fragmentary contour, not an object:

    global camera compensation, centroid   measured mask instability -- a broken
                                           rim's centroid wanders while the
                                           object sits still. FP median 227 px/s
                                           where static scenery must be ~0.
    local flow, bounding box               measured background against background:
                                           a rim's box is mostly the scenery it
                                           encloses. TP 24.8, FP 24.8 px/s.
    local flow, rim pixels, 2x baseline    TP 15.0, FP 15.2. Aperture problem: two
                                           dimensions of motion are not
                                           recoverable from a 1-D edge.
    interior by hole-filling               empty -- the rim seals in only 5 of 50
                                           enemies and 0 of 73 false positives.
    interior by convex hull                seals 98%/89% but TP 13.7 vs FP 14.9:
                                           the hull pulls background inside.

Diagnostic that the camera estimate was never the problem: changing its region
between a wide patch and a tight one around the crosshair barely moved the
numbers, which cannot happen if camera error dominates.

This also removes the most expensive operation measured -- Farneback flow at half
resolution costs 63.5 ms/frame, **2.7x the entire detector** -- so dropping it is
a cost win as well as a complexity win. A speed-range filter is blocked by the
same defect, since it needs the same unmeasurable quantity.

What it costs, measured
-----------------------
Per 1920x1080 frame on the development machine:

    decode (sequential)          2.4 ms
    detect() end to end         23.6 ms      (close 8.9, HSV 4.7, top-hat 4.0,
                                              find_boxes 3.3)
    Farneback flow, half res    63.5 ms      -- dropped, see above

At 10 Hz that is ~10 minutes per 40-minute session, so the fifteen-session
library is under three hours, offline and embarrassingly parallel. On hardware
that barely clears Valorant's (deliberately low) minimum spec, scale by ~3-4x:
still an overnight job. Nothing here runs alongside the game.

On pose estimation
------------------
Human pose estimation is genuinely a solved problem, and `cv2.dnn` is available,
so an ONNX model would add **no new Python dependency** -- only a weights file.
(`cv2.HOGDescriptor` and its built-in pedestrian detector are NOT available;
OpenCV 5.0 dropped them.) Three things to weigh before taking that step:

* it breaks **no model in stage 02**, the property that makes every extractor
  auditable against something the game itself reported;
* it is likely to fail where it is needed. Pose models are trained on photographs
  of real, largely unoccluded humans. The remaining misses are 21-45 px fragments
  and slivers past a corner -- stylised, tiny, heavily occluded. Expect it to
  confirm the enemies already detected and miss the ones that are missed;
* cost only works in a **two-stage** design: full-frame inference is roughly 2-4x
  the current detector on CPU and hours per session on weak hardware, while
  verifying only the 1-3 crops the detector proposes is comparable to current
  cost and fits the existing "expensive layer sees <1% of frames" rule.

Where to go next
----------------
Combine frag_top1 with persistence and re-score end to end. Both are measured,
neither is applied in `detect()` yet, and they are independent signals -- one
shape, one temporal -- so they should not be redundant.

Everything above is measured on **one session, 149 frames, 50 enemy detections
against 73 false positives**, and a best-cut-over-a-continuum statistic is
optimistic on samples that small. Some of the top of that feature table is noise
fitted to this sample. The honest confirmation is a second session's labels, not
a tighter threshold on this one.

The tracker itself is still unvalidated as a tracker: every label here is an
isolated frame, so these numbers say persistence *separates*, not that a tracker
run continuously over a match works. The killfeed anchor tests that for free --
"was an enemy tracked in the two seconds before a kill" -- across all fifteen
sessions, biased toward enemies about to die but testing the sequence rather than
the frame.

The head-peek gap wants the detector used to find its own test set: run at scale,
pull frames where it fires on short wide blobs, check by eye. Sound as long as
the result is treated as a floor on recall rather than a measurement of it.
"""
import json, sys
from pathlib import Path
import numpy as np, cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import metrics                                       # noqa: E402

STORE = Path.home()/"reticle-store"
SID  = sys.argv[1]
THR  = int(sys.argv[2]) if len(sys.argv) > 2 else 25       # top-hat strength
K    = int(sys.argv[3]) if len(sys.argv) > 3 else 11       # kernel, > rim width
AREA = int(sys.argv[4]) if len(sys.argv) > 4 else 120
HMIN = int(sys.argv[5]) if len(sys.argv) > 5 else 22
CK   = int(sys.argv[6]) if len(sys.argv) > 6 else 13
AR   = (1.15, 5.0)        # 1.20 rejects a real enemy at 1.18; below 1.15 buys nothing
HUE_MAGENTA, HUE_ORANGE = 130, 6
SAT, AST = 130, 155
WEAP = (0.50, 0.66)
# Left-handed weapon is a toggleable setting, and it mirrors the view model
# across the vertical axis. Getting this wrong fails in BOTH directions at once
# and silently: the mask covers empty screen on one side, costing recall on
# enemies peeking there, while the actual weapon sits unmasked on the other,
# costing precision. Nothing in the output would look wrong.
HANDED = "right"
# UI box finder
SCALE, GRAD, TOL, PAD = 4, 10, 12, 6
MINRUN, MINROWS, MINSPAN = 380, 3, 15
# Fragmentation: an enemy's rim shatters into many pieces with no dominant one,
# a false positive concentrates its mass in one. Reject a blob whose largest
# piece holds more than this share of the raw rim. 0.90 is deliberately mild --
# it costs 2.2 points of recall for 6.6 of precision; 0.60 is much sharper
# (recall 84.8%, precision 57.4%) but the cut is fitted to one session.
TOP1 = 0.90
# Persistence, applied by track_filter() over a sequence -- NOT by detect(),
# which sees one frame. len>=3 costs no recall at all.
MINTRACK, TRACK_GAP, TRACK_GATE = 3, 2, 90.0
# Known-bad ground truth, per session -- at 9acf02f98283 29:54 the enemy had
# already been killed. Keyed by session: an unqualified set would silently drop
# a legitimate frame at the same timestamp in any other capture.
BAD_BY_SESSION = {"9acf02f98283": {29*60 + 54}}
BAD_LABELS = BAD_BY_SESSION.get(SID, set())

man = json.loads((STORE/"manifests"/f"{SID}.json").read_text())
src = man["source"]; fps = float(src["fps"])
rows = {}
for line in (STORE/"labels"/"enemies"/f"{SID}.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line); rows[r["t_ms"]] = r
rows = [r for r in rows.values()
        if not r.get("uncertain") and r["t_ms"]//1000 not in BAD_LABELS]

KER  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (K, K))
CKER = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CK, CK*2))


def hud_mask(h, w):
    m = np.ones((h, w), bool)
    m[:120, :] = False; m[h-190:, :] = False       # top and bottom HUD bands
    m[:360, :360] = False                          # minimap
    m[60:360, w-520:] = False                      # killfeed
    # The player's own weapon: red-rimmed like everything else and in frame
    # constantly. Persistence cannot find it (the model bobs and sways), so this
    # is a measured region -- 21% of false positives, 0 of 47 labels. Measured
    # right-handed; a left-handed view model is the same region mirrored.
    if HANDED == "right":
        m[int(h*WEAP[1]):, int(w*WEAP[0]):] = False
    else:
        m[int(h*WEAP[1]):, :int(w*(1.0 - WEAP[0]))] = False
    # Bottom-left corner HUD. Corner, not mid-screen, which is what makes a
    # positional mask defensible here where it was not for the combat report.
    m[int(0.75*h):, :int(0.09*w)] = False
    return m


def _runs(b):
    if not b.any(): return []
    idx = np.flatnonzero(np.diff(np.concatenate(([0], b.view(np.int8), [0]))))
    return list(zip(idx[::2], idx[1::2]))


def find_boxes(fr):
    """UI boxes, from the one thing a box has and scenery does not: several
    horizontal rules of the same width at the same x."""
    h, w = fr.shape[:2]
    g = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (w//SCALE, h//SCALE),
                   interpolation=cv2.INTER_AREA)
    hot = np.abs(cv2.Sobel(g, cv2.CV_16S, 0, 1, ksize=3)) > GRAD
    cand = [(y, a, b)
            for y in range(120//SCALE, min((h-190)//SCALE, hot.shape[0]))
            for a, b in _runs(hot[y]) if (b-a)*SCALE >= MINRUN]
    boxes, used = [], [False]*len(cand)
    for i, (y, a, b) in enumerate(cand):
        if used[i]: continue
        grp = [(y, a, b)]; used[i] = True
        for j in range(i+1, len(cand)):
            if not used[j] and abs(cand[j][1]-a) <= TOL and abs(cand[j][2]-b) <= TOL:
                grp.append(cand[j]); used[j] = True
        ys = sorted({z[0] for z in grp})
        if len(ys) >= MINROWS and (ys[-1]-ys[0]) >= MINSPAN:
            x0 = min(z[1] for z in grp)*SCALE; x1 = max(z[2] for z in grp)*SCALE
            boxes.append((max(0, x0-PAD), max(0, ys[0]*SCALE-PAD),
                          min(w, x1+PAD), min(h, ys[-1]*SCALE+PAD)))
    return boxes


def detect(fr):
    h, w = fr.shape[:2]
    lab = cv2.cvtColor(fr, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.int16)              # red-green opponent axis
    top = cv2.morphologyEx(lab[:, :, 1], cv2.MORPH_TOPHAT, KER)
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    hu, sa = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1].astype(np.int16)
    # Relative test (is this a thin rim) AND absolute (is it the colour at all).
    # Neither substitutes for the other: top-hat alone fires on a grey line
    # beside cyan, and an absolute floor alone fires on any terracotta wall.
    keep = ((top > THR)
            & ((hu < HUE_ORANGE) | (hu > HUE_MAGENTA))
            & (sa > SAT) & (a > AST)
            & hud_mask(h, w))
    for bx in find_boxes(fr):
        keep[bx[1]:bx[3], bx[0]:bx[2]] = False
    # Join the rim into ONE region before measuring it: it is broken by the body,
    # by limbs and by occlusion. A human is taller than wide, so the kernel is.
    m = cv2.morphologyEx(keep.astype(np.uint8), cv2.MORPH_CLOSE, CKER)
    n, lbl, st, _cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, ar = st[i]
        if ar < AREA or bh < HMIN: continue
        # Fragmentation, measured on the RAW rim inside this component -- the
        # closing above deliberately destroys the very structure this reads, so
        # it must come from `keep`, not from `m`.
        raw_i = (keep & (lbl == i))[y:y+bh, x:x+bw].astype(np.uint8)
        a_raw = int(raw_i.sum())
        if a_raw >= 10:
            fn_, _fl, fst, _fc = cv2.connectedComponentsWithStats(raw_i, 8)
            top1 = (fst[1:, 4].max()/a_raw) if fn_ > 1 else 1.0
            if top1 > TOP1: continue
        # Shape tests only where the shape exists. A sliver of an enemy has no
        # interior to be hollow, and demanding one filters out precisely the
        # detections that matter most.
        big = bw >= 14 and bh >= 30
        if big and not (AR[0] <= bh/max(bw, 1) <= AR[1]): continue
        ix0, iy0 = x + bw//4, y + bh//4
        ix1, iy1 = x + bw - bw//4, y + bh - bh//4
        if bw >= 14 and bh >= 24 and ix1 > ix0 and iy1 > iy0:
            inner = top[iy0:iy1, ix0:ix1]
            # the interior must be LESS red than the rim: a model sits inside an
            # outline, so the middle is the agent, not more outline
            if inner.size and float((inner > THR).mean()) > 0.45: continue
        out.append((x, y, bw, bh, ar))
    return out


def body_box(px, py):
    """The region a head click implies. A detection anywhere in it is a hit --
    a leg or a torso is a correct detection of that enemy, and requiring the box
    to contain the head scores real detections as false positives."""
    return (px-55, py-25, px+55, py+135)


def hits(px, py, x, y, bw, bh):
    bx0, by0, bx1, by1 = body_box(px, py)
    return not (x > bx1 or x+bw < bx0 or y > by1 or y+bh < by0)


def _world_grey(fr):
    """Grey patch for camera-motion estimation: world only.

    The HUD does not move with the camera, so including it drags the estimate
    toward zero. Which patch of world barely matters -- a wide one and a tight
    one around the crosshair gave the same answer -- so this takes the wide one.
    """
    h, w = fr.shape[:2]
    g = cv2.cvtColor(fr[int(0.20*h):int(0.75*h), int(0.15*w):int(0.85*w)],
                     cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (g.shape[1]//4, g.shape[0]//4), interpolation=cv2.INTER_AREA)
    return np.float32(g) * cv2.createHanningWindow((g.shape[1], g.shape[0]), cv2.CV_32F)


def track_filter(frames, dets_per_frame):
    """Keep only detections belonging to a track of at least MINTRACK samples.

    Persistence is the temporal signal that works; relative motion is not
    recoverable from a fragmentary rim and five attempts at it are recorded
    above. Two details are load-bearing and both were bugs first:

    * gap tolerance -- the detector fires on a real enemy in a median of 9 of 11
      samples but NOT contiguously, so extending tracks only from the previous
      sample shreds one enemy into several short tracks;
    * the camera shift is ADDED to the prediction. Subtracting it doubles the
      error during fast pans and flattens the signal to a diagonal -- 86% of
      enemies against 84.9% of false positives, i.e. nothing.

    Returns a list parallel to dets_per_frame, filtered.
    """
    greys = [_world_grey(f) for f in frames]
    shifts = [cv2.phaseCorrelate(greys[i], greys[i+1])[0] for i in range(len(greys)-1)]
    tracks = []
    for i, cur in enumerate(dets_per_frame):
        cents = [(d[0]+d[2]/2, d[1]+d[3]/2) for d in cur]
        taken = set()
        for t in tracks:
            last = t["pts"][-1][0]
            gap = i - last
            if gap <= 0 or gap > TRACK_GAP + 1: continue
            px, py = t["pts"][-1][1], t["pts"][-1][2]
            dx = sum(shifts[k][0] for k in range(last, i)) * 4
            dy = sum(shifts[k][1] for k in range(last, i)) * 4
            best, bd = None, TRACK_GATE * gap
            for j, (cx, cy) in enumerate(cents):
                if j in taken: continue
                d = np.hypot(cx - (px + dx), cy - (py + dy))
                if d < bd: best, bd = j, d
            if best is not None:
                taken.add(best)
                t["pts"].append((i, *cents[best])); t["idx"][i] = best
        for j, c in enumerate(cents):
            if j not in taken:
                tracks.append({"pts": [(i, *c)], "idx": {i: j}})
    keep = [set() for _ in dets_per_frame]
    for t in tracks:
        if len(t["pts"]) >= MINTRACK:
            for i, j in t["idx"].items():
                keep[i].add(j)
    return [[d for j, d in enumerate(ds) if j in keep[i]]
            for i, ds in enumerate(dets_per_frame)]


def main() -> int:
    cap = cv2.VideoCapture(str(src["path"]))
    st_ = {p: dict(tp=0, fn=0, fp=0, nt=0) for p in ("uniform", "event")}
    for r in rows:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"]/1000.0*fps)))
        ok, fr = cap.read()
        if not ok: continue
        dets = detect(fr); pool = st_[r["pool"]]
        players = [(m["x"], m["y"]) for m in r.get("marks", []) if m["kind"] == "player"]
        others = [(m["x"], m["y"]) for m in r.get("marks", [])
                  if m["kind"] in ("corpse", "deployable", "revealed")]
        used = set()
        for (px, py) in players:
            j = next((j for j, d in enumerate(dets)
                      if j not in used and hits(px, py, *d[:4])), None)
            if j is None: pool["fn"] += 1
            else: pool["tp"] += 1; used.add(j)
        for (px, py) in others:
            j = next((j for j, d in enumerate(dets)
                      if j not in used and hits(px, py, *d[:4])), None)
            if j is not None: used.add(j); pool["nt"] += 1
        pool["fp"] += len(dets) - len(used)
    cap.release()
    t = {k: sum(s[k] for s in st_.values()) for k in ("tp", "fn", "fp", "nt")}
    rec = t["tp"]/max(t["tp"]+t["fn"], 1)
    pre = t["tp"]/max(t["tp"]+t["fp"], 1)
    print(f"tophat>{THR} k={K} area>={AREA} h>={HMIN} ck={CK} "
          f"hue=(<{HUE_ORANGE}|>{HUE_MAGENTA}) sat>{SAT} a*>{AST} ar={AR}:")
    print(f"  TP {t['tp']:3d}  FN {t['fn']:3d}  FP {t['fp']:4d}  nontgt {t['nt']:2d}   "
          f"recall {rec*100:5.1f}%  precision {pre*100:5.1f}%  "
          f"FP/frame {t['fp']/max(len(rows), 1):4.1f}")

    # The numbers above are also the regression check, and were only ever that
    # by hand ("confirm TP 43 / FN 3 / FP 80 comes back"). Recording them with
    # what produced them makes the check automatic: same deps and a different
    # number is reported BROKEN rather than read as a result. There is no
    # external control here on purpose -- the previous run is not one, and
    # treating it as one is how a tool ends up scored against itself.
    metrics.record(
        "enemy_detect", part="labels", session=SID,
        values={"tp": t["tp"], "fn": t["fn"], "fp": t["fp"], "nontarget": t["nt"],
                "recall": round(rec, 4), "precision": round(pre, 4)},
        deps={"detect": metrics.fingerprint(
                  detect, hits, hud_mask, find_boxes,
                  THR=THR, K=K, AREA=AREA, HMIN=HMIN, CK=CK, AR=AR,
                  HUE_MAGENTA=HUE_MAGENTA, HUE_ORANGE=HUE_ORANGE,
                  SAT=SAT, AST=AST, WEAP=WEAP, HANDED=HANDED, TOP1=TOP1)},
        # Labels arriving is the main legitimate reason these move, so it is
        # context: the comparison stays valid and says what grew.
        context={"n_frames": len(rows), "n_enemies": t["tp"] + t["fn"],
                 "pools": ",".join(sorted({r["pool"] for r in rows}))},
    )
    print()
    print(metrics.report(tool="enemy_detect"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
