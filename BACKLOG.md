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

## Minimap re-validation after the `floor_mask` reconciliation

**Tabled 2026-09-06 by the player.** The commit is `18b0912`; the numbers and the
argument are in `reticle/minimap.py`'s docstring and
`prototypes/floor_mask_eval.py`.

Three jobs, in order, and the second depends on the first:

1. **rebuild all 34 geometry npz.** `floor_mask` moved, so `classify()` moves
   and every `built_by` stamp is stale. This is the stamp convention working,
   not a surprise;
2. **re-read `l1/minimap`.** The stored track was built on the old gate, which
   admitted 13.7% of the widget on Ascent that is **100.0% outside the
   painting** — a region holding 878 stored self positions and ~8,400 ally
   candidates, all phantoms;
3. **re-run `xmark_eval`, and treat `chokepoint_eval` as incomparable.** Its
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

## Scan `587c15b07779` and open its 13 cross-channel disagreements

**Tabled 2026-09-06 by the player.** `NOTES.md` has called these *the audit signal
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

## A small-widget painting, to score the length scaling

**Tabled 2026-09-06 by the player: *I don't plan on having small widget sessions be
a concern for a while.*** Correct call — sixteen small-widget sessions are
ingested and none has been read.

The lengths in `floor_mask` now scale with the widget (`BRIDGE` 25 -> 19,
dilation 9 -> 7 at 331 px), which moves three small-widget sessions and no
large one. The direction is right and strictly conservative — it drops void and
adds nothing — but **no small-widget painting exists**, so it is unscored.

**Trigger: the first time a small-widget session is actually read.** One
`prototypes\paint_map.py 9acf02f98283` closes it, and `floor_mask_eval.py`
already scores whatever it finds with no changes.

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

## Two modules in `reticle/` that no CLI command reaches

`reticle/refine.py` is imported only by `prototypes/ping_edge_eval.py`;
`reticle/roster.py`'s `RosterReader` appears zero times in `cli.py`. Both were
promoted before being wired, which makes "is it in `reticle/`?" stop meaning
"is it in the pipeline?".

**Trigger: `roster.py` is item 03 and closes itself.** `refine.py` has no
scheduled caller, so it needs a decision rather than a task — wire it into the
ping reader, or move it back to `prototypes/`.

## `2ba870ccbd50` is tagged small-widget and was ingested as bigmap

Found by `reticle doctor`'s MANIFEST check on its first run, 2026-09-06, and
nobody was looking for it. The session is already on record twice -- a standing
*never re-scan* hazard in this file's ancestor and in `NOTES.md`, and a geometry
failure `prototypes/CLAUDE.md` describes as **unexplained**: "it fixed
contamination on `2ba870ccbd50` but introduced large false positives from a
pixel-value mismatch between recordings that was never root caused."

A wrong-profile ingest is a candidate explanation for exactly that. The profile
sets the minimap ROI and every constant in `minimap.py` is in widget pixels, so
the crop would be wrong and everything downstream would return confident answers
about the wrong pixels.

**Not diagnosed.** Which of the tag and the profile is wrong needs one look at a
frame, and `doctor` deliberately does not guess.

**Trigger: any attempt to use that session, or to close the unexplained
`--geometry-from` note.** Cheap to settle -- `reticle probe 2ba870ccbd50` and
look at the widget.

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
  The same machinery pointed at the ally side names his own, with no new
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

**NEXT, and do not skip the middle step:** `TELEPORT_PX` wants re-measuring,
and n=8 casts on 4 solo clips is not enough to refit it on -- a constant fitted
to the 8 observations that must pass is the degenerate-crop mistake again. The
cheap way to get n is more teleport-agent clips, which cost the player a few minutes
each. Two limits the run also established: a two-part teleport (Yoru, Chamber,
Waylay) drops on PLACEMENT and jumps on traversal, so no fixed window catches
it in general; and slot X still draws pips, so ultimates need the audio half.

## Superseded discussion of the cast/jump combination

**the player, 2026-09-06, and he notes he has raised it before:** *a teleport
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

**the player, 2026-09-06, catching me reaching for the derived path on a fresh
clip:** *why are we still baking the map? I thought we were using the minimap
wiki reference which is higher accuracy anyway?*

**He is right, and it is a promotion gap rather than an open question.**
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
standing `doctor` ERROR that 34 of 35 npz are stale, since the labels would
stop depending on `classify()` at all.

**Interim, done 2026-09-06:** `b9558488a607` has a stored fit at **IoU 95.1%,
rot 270, scale 0.2264** against its own derived mask, so the good geometry
exists for that clip even though nothing loads it yet.

## CORROBORATING CHANNELS: motion predicts sound, and sound indexes the video

**the player, 2026-09-06:** *player icons moving at running speed should be making
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
ground truth for "is he audible" drawn on screen by the game itself. That also
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
NO MINIMAP ICON (his own note: *grenades, flashes, molotovs are the most
common*). That is a fact about the widget, not about sound, and I carried it
across without noticing.

**The consequence is large and it favours audio over the minimap.** If every
ability makes a sound, the audio channel has FULL coverage of the ability class
where the minimap structurally does not, and the failure mode is ATTENUATION --
a continuous, distance-dependent quantity -- rather than absence. Attenuation is
modellable and absence is not.

**And for the LOCAL PLAYER it is not a failure mode at all**: his own casts are
never out of range. So an audio index over the player's own abilities has no
silent-class blind spot whatsoever, which is exactly the half of the event log
the tray and the submenu also cover. The out-of-range caveat applies only to
other players, where it becomes a RANGE ESTIMATE rather than a miss.

**Trigger: after the reference cuts exist.** An index needs something to index
ON, and a matched filter against the cut references is that. Until then a gate
would be an energy threshold, which is what `audio_probe` already killed.

## THE AUDIO CHANNEL: build it next, and it splits into two unequal halves

**the player, 2026-09-06:** *Teleports can be very short range or even faked though,
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

**CORRECTED, by the player, 2026-09-06: the tray DOES read slot X.** This entry
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

**THE REFINEMENT, and it is directly implementable from stored data:** the
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
cut from footage recorded the way he actually plays, so his own clips are the
RIGHT source rather than a compromised one.

**The contaminant is his own footsteps -- but HOW MUCH is NOT ESTABLISHED, and
the first attempt to measure it was my own aggregate error.** Over 27 demo
clips and 119 casts, asking whether the self track says he was still in the
+/-0.5 s around each cast:

    still by MAX speed over the window       8/119   ( 7%)
    still by MEDIAN speed over the window   28/41    (68%)   (8-clip subset)

**A sevenfold swing from the choice of aggregate, which means the proxy does
not answer the question.** A max over fifteen frames is tripped by one jittery
ring fit, so it reads "moving" on a stationary player; a median passes a window
he moved through briefly. This is `self_icon_dist`'s min-versus-median lesson
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

**the player, 2026-09-06, closing the session:** *for audio, especially for
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
