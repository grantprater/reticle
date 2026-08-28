# Reticle

Vision-based mechanical analysis pipeline for Valorant — measuring the layer of
play the match API structurally cannot see. Python 3.14, four deps, single
process, no ML frameworks.

**Design doc** (the authority on stage numbering and intent):
https://claude.ai/code/artifact/d7c7173f-dc5e-4c1e-9dcc-acded5a486cb
**Store dashboard:**
https://claude.ai/code/artifact/3854df28-3e45-4783-8aee-7e7f062ac461
**SS7 addendum -- comparable runs** (why `reticle metrics` exists, and the two
kinds of dependency). Source in `docs/metrics-addendum.html`:
https://claude.ai/code/artifact/a045817e-a254-4b79-b1cf-20c11b7a452a

Section references in docstrings (`SS3`, `SS7`) mean §3, §7 of that doc.

## Contents

Detector state and the minimap live in **`prototypes/CLAUDE.md`**, which
loads when a session touches that directory.

The current handoff and the live defect list are in **`NOTES.md`** — read it
when picking up unfinished work, or when you need to know what state a
session left things in. It is deliberately not loaded here.

- [Where the detector detail lives](#where-the-detector-detail-lives)
- [Running](#running)
- [Pipeline status](#pipeline-status)
- [Checking against the game's own numbers](#checking-against-the-games-own-numbers)
- [Wallbangs are a finding, not just a parsing problem](#wallbangs-are-a-finding-not-just-a-parsing-problem)
- [What this is for (decided 2026-08-25)](#what-this-is-for-decided-2026-08-25)
- [How peeking actually works, and what to measure instead](#how-peeking-actually-works-and-what-to-measure-instead)
- [Sampling densely where it matters, without poisoning the sample](#sampling-densely-where-it-matters-without-poisoning-the-sample)
- [The top HUD says more than it looks like](#the-top-hud-says-more-than-it-looks-like)
- [Scoreboard divergence is a finding, not an error](#scoreboard-divergence-is-a-finding-not-an-error)
- [Open design question: engagements without a kill](#open-design-question-engagements-without-a-kill)
- [Debugging what the extractors see](#debugging-what-the-extractors-see)
- [Asking myself a perceptual question](#asking-myself-a-perceptual-question)
- [Runs are compared, not just printed](#runs-are-compared-not-just-printed)
- [Open defects](#open-defects)
- [Before ingesting any new capture](#before-ingesting-any-new-capture)
- [A model of where my judgement is reliable](#a-model-of-where-my-judgement-is-reliable)
- [Conventions that are load-bearing](#conventions-that-are-load-bearing)

## Where the detector detail lives

Moved to **`prototypes/CLAUDE.md`** on 2026-08-26, which loads when a session
touches that directory — 671 lines of detector state, 63% of whose measured
figures already appeared in a module docstring. This index is what remains
eager, because it is what you need before you know which file to open.

Read `prototypes/CLAUDE.md` before any minimap work. It holds the arc of the
enemy and portrait detectors, the colour-free channel's numbers, and **Grant's
domain notes on the minimap, which are not recoverable from the pixels or the
code** — the single least replaceable thing in this repo.

    minimap_geometry.py   the static map, classified. Run once per session; every
                          other minimap module loads its npz. STAMPED: rebuild
                          every session's geometry when this file changes
    minimap_icons.py      floor_mask (the opaque slab) and the red mask
    minimap_ring_fit.py   the SHIPPED enemy finder, 80.8% / 54.6%. Fits a CIRCLE
    minimap_dynamic.py    the colour-free channel — ability glyphs a red mask
                          cannot see. `searchable` is the map mask; read its
                          docstring before touching the searchable area
    minimap_portrait.py   which enemy an icon is, 93.0% leave-one-out
    minimap_temporal.py   persistence, and `usable` — is the widget drawn at all
    paint_map.py          Grant paints the searchable mask. The tool to reach for
                          when a perceptual question resists derivation
    label_dynamic.py      Grant answers 250 colour-free candidates
    dynamic_eval.py       scores both of the above; reproduces every figure

Three facts from that directory are load-bearing enough to keep here, because
each one is a mistake that has already been made more than once:

* **the widget is SEMI-TRANSPARENT over the void**, and every content-based
  approach that ignored it drowned in the world moving behind it — five variants
  in `minimap_position.py`, then the searchable area five more times on
  2026-08-26. Search what is opaque;
* **a closing radius that reconnects a broken rim is the radius that merges
  adjacent icons.** Met and lost to four times. Fit a shape, do not repair one;
* **never seed a label file.** Seeding `minimap_agent` with provisional rows made
  the labeller skip them as done, and the number that came back was scoring my
  own clustering against itself.

**Building or running a labeller? Invoke the `labelling-pass` skill first.** It
carries the shared control layout, the append-only last-write-wins file format,
and the mistakes each of the five labellers here made once. It is a skill rather
than a section because it is a PROCEDURE with a clear trigger — but a skill only
loads when invoked, so the three lessons above stay stated here in full.

## Running

Always via the venv interpreter — there is no console script:

```
.\.venv\Scripts\python.exe -m reticle <command>
```

Default store is `~/reticle-store` (outside this repo); override with `--store`.
`fixtures/`, `teststore/`, `probe_*/`, `frames_*/` are gitignored scratch.

Prototypes are run directly, not through `-m`. The minimap ones, in the order a
new session needs them:

```
prototypes\minimap_geometry.py <session>            # once per session; writes the npz
prototypes\paint_map.py       <session>            # Grant paints the searchable mask
prototypes\label_dynamic.py   <session> --colour none   # Grant answers 250 candidates
prototypes\dynamic_eval.py    <session> [--mask]   # scores both of the above
```

`dynamic_eval.py` is the one to reach for first: no arguments beyond a session,
it recomputes the classifier features from the labels and prints the operating
points, and `--mask` scores the searchable rule against a painting. Neither
needs anything rebuilt.

## Pipeline status

**Per-session status is generated: `reticle status`, or read `STATUS.md`.** It
computes sessions, store version, rounds, W-L, plant rate and every K/D against
`checks.KNOWN_KD`, so those numbers cannot drift from the code. The stage table
below is design state -- what is built -- which nothing in the store implies, so
it stays written.

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

### The endstate, in Grant's words (2026-08-26)

Asked directly, at the end of the minimap labelling session:

> For this basically event-tracking phase, my ideal endstate would be real-time
> labelling of a VOD of enemies and allies on screen and on minimap, as well as
> labelling of abilities and pings on the minimap, and position estimation of
> enemies and allies, leading into logging and statistical analysis of duels and
> rounds as events, using the win probability model discussed, and including
> shooting error and ability to surface clips denoting notable patterns.

Read that as the ordering it implies, because it settles several questions this
document has been circling:

* **the minimap is not the goal, it is the cheapest source of events.** Every
  minimap sub-problem -- glyph detection, ability identity, position estimation
  -- is instrumental. When one of them stalls, the question is whether the event
  it feeds can be got another way, not how to rescue the technique;
* **detection and identity are both required, and so is TIME.** "Real-time
  labelling of a VOD" means the extractors have to run at a usable rate over a
  whole match, not just be accurate on sampled frames. Nothing has been measured
  for throughput yet. The 15-20 Hz minimap sample rate already noted under
  minimap position tracking is the first place this bites;
* **duels and rounds are the unit**, not frames or detections. That is what the
  L2 event log has to emit, and it is the join point for the win probability
  model;
* **shooting error comes from the in-game UI, not from us.** Grant, asked
  directly: *I was thinking we derive shooting error but it is probably better
  to use the in-game UI element. I think we have enough confirming signals that
  the reduced accuracy in killfeed reading is acceptable, but we can see.* That
  reverses capture note #3, which switched the readout OFF because it covers
  59% of the victim-name box in stack slot 3. **Turn it back on**, accept the
  killfeed cost, and lean on the other signals -- the scoreboard read, `board`
  per-round, and the minimap events this session unblocked -- to cover the
  attribution gap. Provisional: "but we can see" means measure the killfeed
  cost on the next capture rather than assume it is affordable. Moving the
  readout out of the top right is still strictly better than either choice if
  the game allows it;
* **surfacing clips needs a SECOND, higher-fidelity pass.** A pattern the model
  finds is only useful if it comes back as footage, and Grant: *the clips likely
  need a higher fidelity pass to get the exact bounds.* So the event log's
  timestamp locates a clip; it does not define it. Detection can stay cheap and
  sampled, with an expensive pass run only over the handful of moments that are
  actually going to be cut. That is a two-stage design, and it means precision
  of event TIMING is not a constraint on the main extractors -- a useful thing
  to know before anyone raises a sample rate to chase it;
* **whether any of this can be a pure streaming algorithm is open.** Grant: *if
  we want to try to do this with a pure streaming algorithm for efficiency I
  actually don't even know if it's possible.* Nor do I, and the honest answer
  has parts. Per-frame reads (killfeed, HUD, minimap detection) stream fine. Two
  things currently do not: the **static map** is a per-pixel median over ~180
  frames spread across the session, and **`active` spans** come from segmenting
  the whole file. Both look convertible -- a median over a warm-up window that
  updates incrementally, and an online segmenter -- but neither has been tried,
  and a warm-up means the first round of a VOD is read with a worse static map
  than the last. Anything needing FUTURE context is the real obstacle, and the
  round-phase detector is the first candidate.

Nothing here is scheduled. It is recorded so that the next person choosing
between four plausible next steps can ask which one is on this path.


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

## Asking myself a perceptual question

`reticle/glance.py` is one fixed encoding for every perceptual question in this
repo, and `prototypes/glance_cams.py` is the first thing built on it. Read its
module docstring before building a new debug view; the short version is why it
exists at all:

**`notes/predictions.jsonl` says claims about what a rendered image contains
were 5 of 5 WRONG at a mean stated confidence of 0.85.** Five-for-five wrong is
not a bandwidth failure -- bandwidth failures produce uncertainty, not confident
wrongness. Two things cause it, and only one of them is about pixels:

* **acuity against feature size.** The enemy rim is 1-4 px; a whole 1080p frame
  arrives downsampled to roughly a thousand tokens, so the thing this project
  measures is below the delivered sensory floor. The fix is magnification at a
  STATED factor, not a bigger image. A 200x200 crop at 4x costs about what the
  full frame costs and resolves the rim;
* **nothing pooled.** Every debug view here was bespoke -- the killfeed contact
  sheet in a scratch script, `label_dynamic`'s panel layout, `paint_map`'s -- so
  an error rate on killfeed bands said nothing about minimap glyphs and
  calibration restarted at n=1 in every module. A fixed encoding is what makes
  `reticle.glance calibration` a table that gets sharper across domains.

**A sheet is a backdrop plus ringed items, each answered from a closed set.**
That is the whole grammar; `present`, `which_of_k`, `boundary`, `count`,
`correspond` and `ordering` are layouts over it, not six renderers. Invariants
are enforced in code rather than remembered: INTER_NEAREST with the factor
printed, a 10-source-pixel scale bar on every panel, the candidate ringed in
every panel, off-source padding filled magenta so "no data" and "nothing here"
cannot be confused, and structural colour reserved for the QUESTION (amber
covered, magenta no-data, matching `overlay.py`) while domain colour stays for
the answer.

**The control is the mechanism.** Each sheet plants items whose answer is
already known, shuffled in; the footer says how many and never which. Miss one
and the sheet is scored VOID and its other answers are DISCARDED, not doubted --
the finding is then that this question cannot be read at this magnification, and
the next move is a labeller, not a threshold.

    .\.venv\Scripts\python.exe -m reticle.glance --self-test      # 8 sheets, all six kinds
    .\.venv\Scripts\python.exe -m reticle.glance calibration      # pooled, by domain and band

**Controls must be someone else's labels.** `truth_source` is required and
`answer()` refuses a `claude-*` provenance outright -- a control built from my
own prior claim is the `minimap_agent` seeding mistake in a new costume. The cam
sheets drew theirs from Grant's 79 `enemy` and 31 `question` marks, placed long
before the question existed. Be honest about what that buys: controls from a
DIFFERENT population establish a floor (can this be read at 6x at all), never a
ceiling (is the open class separable) -- the same trap as *0 of 55 hand-marked
icons have aspect >= 2.0*.

Two loads on 2026-08-27, and the pair is the argument. The **cam** sheets came
back VALID at 8 of 8 controls and closed a queued task in minutes by finding it
unrunnable. The **Lotus cross-session** sheet came back VOID on 2 of 6, and the
misses localised to one glyph -- which is the more valuable of the two results,
because those controls were strong: same detector, same channel, same question,
different map only. Eleven side predictions logged across both, 5 right, 3
wrong, 3 couldn't-tell, and the `minimap` rows of the calibration table now
exist at three confidence bands.

One defect the Lotus sheet exposed in the encoding itself, since it is the kind
that recurs: panels were laid flush left in a max-sized cell, so a sheet whose
boxes vary in size read as a ragged pile. Panels are centred in a uniform cell
now. **A contact sheet is worth exactly what a glance can take off it**, so
layout regressions in this module are correctness bugs, not cosmetics.

## Runs are compared, not just printed

`reticle/metrics.py` stores each run's summary and prints the **diff**, so a
run where nothing moved prints one line and a moved number is loud. The token
saving is the small half. The two real ones:

**The control is derived, not declared.** `version.py` already promises a
version is bumped when a column's MEANING changes. Read as a contract that is
checkable: if nothing a number depends on changed, the number must not change
either. Same deps and a different value is not a result -- it is an unversioned
edit or nondeterminism, and it is reported `BROKEN`. That is the standing
"confirm a known number comes back" check, enforced in code instead of carried
by hand, which is how it had drifted to the wrong row of a table for weeks.

**Comparability belongs to the dependency chain, not the field.** `recall`
keeps its name and its dtype across a class split and stops being the same
quantity -- the queued `ability` split is exactly that. So every record splits
what it was computed from into two kinds, and putting a field in the wrong one
is the only way to get this wrong quietly:

    deps      INVALIDATING -- code fingerprint, class list, sampling rule, the
              fit session, whether a painted mask was seeded. Different deps is
              not a comparison; no delta is shown at all.
    context   EXPLANATORY -- label counts, pool size. Different context is a
              comparison, and it is the interesting one. Labels arriving is the
              main legitimate reason a number here moves.

Collapse the two and it fails either way: everything invalidating and each code
touch resets the baseline, nothing invalidating and you get confident false
comparisons. Deps are **fingerprinted from function source** (`metrics.
fingerprint`) rather than listed, because a hand-kept list rots in the silent
direction -- add a knob, forget the list, and every later diff crosses a
boundary it should have refused.

**Only `pass` runs are ever a baseline, and that gate is structural** --
`baseline()` has no flag to include a `broken` or `cannot-answer` run. A broken
run allowed to become the new normal would re-baseline the fault and the check
would never fire again: the seeding mistake in a third costume, after
`minimap_agent` and `answer()`'s refusal of `claude-*` provenance.

```
reticle metrics                              # every series; quiet ones stay quiet
reticle metrics --tool enemy_detect --verbose
.\.venv\Scripts\python.exe -m reticle.metrics --self-test   # all four verdicts
```

Wired in so far: `enemy_detect_eval.py`, and `dynamic_eval.py` for the held-out
fit, the pool composition, and the painted mask. A new eval should record too;
one `metrics.record()` at the end is the whole cost.

## Open defects

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
  the same rule, stated below. Do not tune the extractor against either.

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

## A model of where my judgement is reliable

`reticle/judgement.py`, built 2026-08-27 from a question of Grant's: novelty
seems to carry the most information, the way human memory over-weights novel or
emotionally volatile events -- is there a core idea there?

There is, and the naive version was tried and failed the same day. **Novelty in
INPUT space is the wrong measure, because noise is maximally novel.** Onset
sampling was exactly that, and against Grant's existing labels it selected 68%
artefacts and would have gutted the ability class (8 rows against 45). The
useful reading of "emotionally volatile" is not *new* -- it is **surprise
weighted by consequence**, which is a real quantity: prioritised experience
replay ranks memories by prediction error, and information gain is only defined
relative to something you care about. This project's stake function is written
down as the endstate, which is why writing it down paid for itself.

What survives and is measurable is defined on the MODEL's behaviour, not the
input's strangeness:

    acc / gap    am I right, and am I right at the confidence I claim
    runs z       do outcomes CLUSTER (structure -- chase the run of wrongs)
                 or ALTERNATE (irreducible -- log aleatoric and stop tuning)
    change point has the error rate SHIFTED, i.e. have my assumptions lapsed

**The third is the one worth having.** Every expensive failure in this project
is a regime boundary where an assumption silently stopped applying: the death
screen where `usable()` lapsed, buy phase against live play, the halftime side
swap, 4:2:0 chroma. Each looked like ordinary noise until somebody looked.
**Sample where the error rate CHANGES, not where it is high** -- a stable 30%
teaches nothing new, a jump to 30% is a boundary.

**It refuses rather than guesses, and that is load-bearing.** A staleness
detector that hallucinates staleness is worse than none, so the change point is
Bonferroni-corrected for the number of splits searched and returns `None` below
5 scored outcomes a side. Measured in `--self-test` over 2000 coin-flip
sequences of n=30: **corrected fires 0.8%, uncorrected would fire 19.9%.** A
real change (15 right then 15 wrong) is caught at exactly #15.

First read, 39 predictions: no regime change anywhere, and every domain except
`minimap` and `rounds` is underpowered for one. `geometry` is overconfident by
0.85 -- that is the old retrospective batch. The directional hint in both
powered domains is the same and does not yet reach significance: accuracy falls
in the second half of each, and both second halves are dominated by **guesses at
constants** rather than predictions about what running existing code will do.

**Stake: what it costs to be wrong, which is not what accuracy measures.**
Grant: predicting a file's word count has a different salience to predicting
whether your ontology was correct. The first attempt to show that ran the wrong
test -- accuracy by level -- and found nothing, because cost was not in the log
at all. That absence was the gap. With cost recorded, over 33 backfilled rows:

    level         n    acc     gap   mean cost
    ontology      8   0.38   -0.46         2.1
    mechanism     7   0.43   -0.38         1.1
    value        13   0.62   -0.05         0.2

Cost orders as predicted, an order of magnitude apart. **The gap column is the
finding nobody was looking for**: the claims that cost the most are the ones I
am most overconfident about. Two wrong ontology claims cost a session each
(*the bomb sites are correctly classified*, *the class list is complete at six*)
against a wrong value claim costing a requote.

`level` is a priori and nearly SYNTACTIC -- readable off the claim's grammar --
so it cannot be quietly under-rated for a claim about to fail. `cost` is a
posteriori and ORDINAL, anchored to things that happened here rather than to
minutes, because an absolute scale would be false precision. **Stake is reported
as a percentile within this log, never as an absolute**: Grant's point that
comparison is inevitably relative, which is the right resolution rather than a
dodge, since every decision this feeds is a ranking. `stake()` is explicitly a
prior to be replaced -- once enough rows carry an observed cost, fit
`level x rests_on -> cost` from history, exactly as the calibration table
replaced asking how confident I felt.

Caveat, load-bearing: those rows are `level_by: claude-retro`, my own labelling
of my own claims after the outcomes were known. It is the hypothesis the
forward-recorded rows exist to test, not a result.

`reticle.glance calibration` is the BAND view of the same log (am I calibrated
at the confidence I claim); this is the TIME view. Different questions, kept
apart on purpose.

## Conventions that are load-bearing

**Conversion audit, 2026-08-27.** This section's job is to change behaviour,
and measured against that it has been the worst-performing part of the file:
**six recorded recurrences**, each a documented lesson that failed to prevent
its own repetition. Today's evidence is one-sided -- every convention that was
merely written down got violated again (*look at the image* twice, *verify the
patch applied* twice), while every one encoded as **code that refuses** held.
So each convention now carries its enforcement status, and prose that cannot
become a check is a candidate for deletion rather than for better wording.

    convention                          recur  status
    predict before you look                 -  OBSERVABLE: glance.answer records
                                               `predicted_first` from open rows
    ask Grant before deriving               5  prose only -- judgement call, but
                                               "on the FIRST failure" is countable
    look at the image before measuring      2  prose only -- ordering, not yet checkable
    ground truth from the same population    2  ENFORCED: glance.build warns and
                                               records `population_mismatch`
    stamp every cached artefact              0  ENFORCED since built (`built_by` hash)
                                               -- and it has never recurred
    quotable numbers go in prototypes/       1  partial -- a commit check could catch it
    a label row needs nothing more           -  **RETIRED, it was false.** See below

**`reticle.judgement compliance` reports whether the enforced ones are followed.**
That is the difference that matters: a convention nobody can tell whether you
obeyed cannot be evaluated, only repeated.

**Predict before you look. UNDER TEST from 2026-08-27 — log it, do not trust
it.** Before opening unfamiliar ground, or committing to a threshold or design:

1. **Ask what is predictable at all**, before spending effort on accuracy.
   Measure the noise floor; repeat an observation to see whether the OUTCOME
   varies (varies = irreducible, stop; stable and you were wrong = your model,
   go look). Log irreducible ones `verdict: aleatoric` and route them to Grant.
2. **State 3-5 claims specific enough to die cleanly** — a number, a class, a
   count. Finest resolution you can hold at 0.7 confidence, no finer: existence,
   direction, magnitude, value-with-a-band, mechanism. For a search, predict the
   result COUNT.
3. **Look, score each right / wrong / couldn't-tell, and go to the WRONG ones
   first**, before going where the task pointed. A broken prediction localises
   the part of your model that is actually wrong, which is worth more than the
   thing you came for.
4. **Log to `<store>/notes/predictions.jsonl`** — `{when, domain, claim,
   confidence, outcome, retrospective}`. Escalate resolution per DOMAIN and gate
   on CALIBRATION, not hit rate: right 80% of the time while claiming 0.9 means
   fix the confidence, not the resolution.

Two failure signatures worth naming. **Three predictions that agree and are all
wrong = a bad frame**, which feels like corroboration and is the dangerous case;
disagreement is ordinary ignorance. And a **rising `couldn't-tell` rate means
the technique is decaying into ritual**, since a vague claim survives evidence
that should have killed it.

Why bother: on 2026-08-26 the per-region temporal SD map (7.4 on white lines,
16.9 on the slab, 42.5 in the void) IS a map of what is predictable and answers
the searchable-area question outright — it was computed LAST, to explain a
conclusion, after five derived masks had failed. **That log is also the only
artefact here whose value grows across sessions**, since a calibration table
gets sharper with n and says which domains to trust. First read, retrospective:
structural claims about code fair; claims about what a rendered image contains,
5 of 5 wrong at a mean stated confidence of 0.85.

**Ask Grant before deriving, when he can just look.** The searchable mask was
derived and re-derived five times on 2026-08-26, each attempt measured and
plausible and wrong, and he named the defect by eye every time in seconds.
`paint_map.py` settled it in one pass and the result transferred to a second map
at 92.8% IoU. The project's own history says the same thing more quietly: every
stage that works was preceded by a labelling pass. **On the FIRST failure of a
perceptual question, build the tool that asks him** -- not the fifth.

**In vision work, look at the image before measuring it.** Rendering the
offending candidate took one tool call and settled what three analysis scripts
had not. Several dead ends that day -- two flood-fill variants, a distance-to-
void analysis -- would have died in seconds against a picture.

**Check that ground truth comes from the same population as the thing being
filtered. ENFORCED: pass `control_population` / `item_population` to
`glance.build`, which warns on the sheet's own face and records the mismatch.** Twice on 2026-08-26 a measurement was true and misleading: *0 of 55
hand-marked icons have aspect >= 2.0* (they were ENEMY icons; the target was
ability glyphs, and the filter would have deleted Sage walls, ping ripples and
spawn barriers) and *0 of 254 hand-marked icons sit on a HOLE* (nearly cut the
holes wholesale). A perfect measurement over the wrong population gives a wrong
conclusion with full confidence.

**Stamp every cached artefact with the code that built it.** `minimap_geometry`
writes `built_by`, a hash of itself, and `load_geometry` warns when it does not
match. Without it, widening the plant test grew a third "bomb site" on Split --
10921 px of brown void -- and nothing noticed, because that npz was stale and
the two maps in use were fine. **Rebuild every session's geometry whenever
`minimap_geometry.py` changes.**

**Analysis that produces a quotable number goes in `prototypes/`, not scratch.**
If a figure is worth putting in a commit message it will be re-run, and the next
session should not start by rebuilding feature extraction. `dynamic_eval.py` is
the pattern.

**A label row must carry enough to RECOMPUTE any feature later.** That is what
let host span and top-hat peak, invented after 154 rows were answered, be
applied to all of them for free -- every row had `(t_ms, x, y)`.

*Corrected 2026-08-27.* This used to read "nothing more -- features are
recomputed, not stored", and **that was false**: `label_dynamic` stores colour,
area, box and aspect on purpose, and says so in its own docstring. The
convention described a practice the repo had abandoned and nobody noticed,
which is the failure mode this whole file is exposed to -- prose that is never
checked drifts away from the code and then misleads. The principle that
survived is the KEY, not the absence of a cache.

**Where things live, so this file does not have to repeat them.** Module
docstrings carry why the code is as it is, and they load when the file is read;
this file carries what you need BEFORE you know which file to open. If a fact
would stop a mistake being repeated, it belongs here. If it explains an existing
decision, it belongs in the docstring.


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
  edit, re-run the thing and confirm a **known number** comes back. That check
  is only meaningful because the number was measured before the edit, so
  measure first, then edit.

  **The known number is no longer written here, and that is the point.**
  `reticle metrics` holds it, keyed to what produced it -- see "Runs are
  compared, not just printed" above. A number carried by hand rots exactly as
  a written status does: this bullet said *TP 43 / FN 3 / FP 80* until
  2026-08-27, which is the **unfiltered** configuration (93.5% / 35.0%), while
  the command it was attached to runs the shipped one and returns 42 / 4 / 60.
  Nothing had regressed. The control had simply been copied from the wrong row
  of the table and could not be checked without knowing which row.
- **Keep "Picking up" in `NOTES.md` current, and keep it SHORT. Standing
  instruction from Grant (2026-08-26): do this unprompted.** It is the first
  thing read when picking work back up and it decays fastest, so a stale one
  actively misleads. Detail does
  NOT belong there -- it belongs in the prototype docstring next to the code it
  describes, and in the commit message, both of which are searchable and neither
  of which goes stale silently. One session left it at 560 lines and it had to
  be cut by two thirds.

  **On the trigger, honestly: there is no context-usage readout available.**
  Grant asked for "around 94% of the session limit"; that cannot be implemented
  literally, because nothing exposes a percentage to work from. Guessing at one
  would be worse than not having it. Use what IS observable instead:

  * **rewrite it when a result changes what the next session should do first.**
    This is the real trigger and it is not an end-of-session activity at all --
    a finding that closes a line or opens one should update "Picking up" as part
    of recording it, in the same commit;
  * refresh it when several verified results have landed without one;
  * refresh it when Grant signals winding down, or asks for a handoff.

  The durable protection is the convention above it -- commit whenever a result
  is verified -- because that survives a session ending abruptly, which no
  end-of-session ritual can. Treat the handoff as a summary of commits already
  made, never as the only place a finding is written down.
