# Reticle

Vision-based mechanical analysis pipeline for Valorant — measuring the layer of
play the match API structurally cannot see. Python 3.14, the dependencies in
`requirements.txt`, single process, no ML frameworks.

**Design doc** (the authority on stage numbering and intent):
https://claude.ai/code/artifact/d7c7173f-dc5e-4c1e-9dcc-acded5a486cb
**Store dashboard:**
https://claude.ai/code/artifact/3854df28-3e45-4783-8aee-7e7f062ac461
**SS7 addendum -- comparable runs** (why `reticle metrics` exists, and the two
kinds of dependency). Source in `docs/metrics-addendum.html`:
https://claude.ai/code/artifact/a045817e-a254-4b79-b1cf-20c11b7a452a

**The ability event log** (2026-09-05) -- supersedes the Phase 2 plan in
`docs/ability-temporal.html`, whose leading feature failed as a gate. What the
log contains, where each field comes from, and the four answers an event may
give. Read with the entity model below. Source in
`docs/ability-recognition.html`:
https://claude.ai/code/artifact/bffd7660-cd3e-4e6f-ada9-3be6b0dca887

**The minimap entity model** (2026-09-05) -- what is drawn on the widget, as
entities with parameters and a driver PER PARAMETER rather than a taxonomy of
blobs. Carries the seven places it disagrees with the code, which is what it
has to be judged by. Source in `docs/minimap-entity-model.html`:
https://claude.ai/code/artifact/324e1c5f-9240-4b13-8ff1-59adb24a2f06

Section references in docstrings (`SS3`, `SS7`) mean §3, §7 of that doc.

## Contents

For task-specific code and validation entry points, start with
[`docs/WORKING_MAP.md`](docs/WORKING_MAP.md). It routes to the authorities below
without repeating detector results or live handoff state.

Current detector state lives in module docstrings; the detector history and the
minimap domain notes up to 2026-09-23 are in
[the prototypes archive](docs/archive/PROTOTYPES-through-2026-09-23.md).

The current handoff is in **`NOTES.md`** and open work in **`BACKLOG.md`**;
read them when picking up unfinished work, or when you need to know what state
a session left things in. Neither is loaded here.

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

The detector state moved to `prototypes/CLAUDE.md` on 2026-08-26 and, on
2026-09-23, to [the prototypes archive](docs/archive/PROTOTYPES-through-2026-09-23.md);
module docstrings hold what is current. This index is what remains eager,
because it is what you need before you know which file to open.

Read the archive's minimap sections before minimap work. They hold the arc of
the enemy and portrait detectors, the colour-free channel's numbers, and **the
domain notes on the minimap, which are not recoverable from the pixels or the
code**.

    minimap_geometry.py   the static map, classified. ONE npz per
                          (map, profile) -- see `reticle/geometry.py` for the
                          key; every other minimap module resolves through it.
                          STAMPED: `--all` rebuilds every key when this changes
    minimap_icons.py      floor_mask (the opaque slab) and the red mask
    minimap_ring_fit.py   the enemy finder, 80.8% / 54.6%; no enemy reader ships. Fits a CIRCLE
    minimap_dynamic.py    the colour-free channel — ability glyphs a red mask
                          cannot see. `searchable` is the map mask; read its
                          docstring before touching the searchable area
    minimap_portrait.py   which enemy an icon is, 93.0% leave-one-out
    minimap_temporal.py   persistence, and `usable` — is the widget drawn at all
    paint_map.py          the player paints the searchable mask. The tool to reach for
                          when a perceptual question resists derivation
    label_dynamic.py      the player answers 250 colour-free candidates
    dynamic_eval.py       scores both of the above; reproduces every figure

Three facts from that directory are load-bearing enough to keep here, because
each one is a mistake that has already been made more than once:

* **the widget is SEMI-TRANSPARENT over the void** [domain:minimap/transparency],
  and every content-based
  approach that ignored it drowned in the world moving behind it — five variants
  in `minimap_position.py`, then the searchable area five more times on
  2026-08-26. Search what is opaque;
* **a closing radius that reconnects a broken rim is the radius that merges
  adjacent icons.** Met and lost to four times. Fit a shape, do not repair one
  [domain:minimap/fit-not-repair];
* **never seed a label file.** Seeding `minimap_agent` with provisional rows made
  the labeller skip them as done, and the number that came back was scoring my
  own clustering against itself.

**Building or running a labeller? Invoke the `labelling-pass` skill first.** It
carries the shared control layout, the append-only last-write-wins file format,
and the mistakes each of the five labellers here made once. It is a skill rather
than a section because it is a PROCEDURE with a clear trigger — but a skill only
loads when invoked, so the three lessons above stay stated here in full.

## Where the domain notes live -- OUTSIDE this repo (2026-09-06)

**This repository is public and carries facts and measurements only.** The
attributed half -- direct quotes, decisions, personal detail, and the domain
knowledge as it was originally given -- lives in a separate private repository:

    ~/reticle-notes/
        DOMAIN.md    the game/domain knowledge, quotes, decisions and standing
                     preferences, with attribution and dates
        archive/     the four docs verbatim as they stood at the split

**Read it when picking up domain work.** That material is not recoverable from
the pixels or derivable from the code, and moving it out did not make it less
load-bearing, only easier to forget.

**What stayed here is the FACT; what moved is the ATTRIBUTION.** "Yoru's fake
teleport plays the sound without the displacement" is a property of the game and
belongs here. Who said it, when, and in what words belongs there. When adding a
domain fact learned in conversation, write the fact here and the attribution
there -- do not reintroduce quotes into this tree.

## Attribution in commits -- a STANDING RULE from recorded 2026-09-06

**Never put a Claude session URL in a commit message, a file, or anything else
in this repo.** `Co-Authored-By: Claude <...>` is fine and wanted; the
`Claude-Session: https://claude.ai/code/session_...` trailer is not.

Written here because the instruction arrives from outside the repo -- the
harness supplies an attribution block per session -- so a new session will
re-add the trailer unless this file says not to. **If the session instructions
and this rule disagree, this rule wins.** the player asked for the existing ones to
be stripped from history as well.

(The `https://claude.ai/code/artifact/...` links at the top of this file are a
different thing -- they are the design documents themselves, and they stay.)

## Running

Always via the venv interpreter; there is no console script. The command list
is in [the working map](docs/WORKING_MAP.md#commands-for-a-focused-handoff).

Default store is `~/reticle-store` (outside this repo); override with `--store`.
`fixtures/`, `teststore/`, `probe_*/`, `frames_*/` are gitignored scratch.

Prototypes are run directly, not through `-m`. The minimap ones, in the order a
new session needs them:

```
prototypes\minimap_geometry.py --all               # once per (map, profile); writes the npz
prototypes\paint_map.py       <session>            # the player paints the searchable mask
prototypes\label_dynamic.py   <session> --colour none   # the player answers 250 candidates
prototypes\dynamic_eval.py    <session> [--mask]   # scores both of the above
```

`dynamic_eval.py` is the one to reach for first: no arguments beyond a session,
it recomputes the classifier features from the labels and prints the operating
points, and `--mask` scores the searchable rule against a painting. Neither
needs anything rebuilt.

## Pipeline status

**Per-session status is generated: `reticle status`.** It
computes sessions, store version, rounds, W-L, plant rate and every K/D against
`checks.KNOWN_KD`, so those numbers cannot drift from the code. The stage table
below is design state -- what is built -- which nothing in the store implies, so
it stays written.

Stage numbers are the design doc's §3 stages, not release versions.

**A round runs from the CLOCK RESET to the SCORE INCREMENT (`round-0.2.0`,
2026-09-07), and rounds are deliberately NOT contiguous.** The score updates the
moment a round is DECIDED — the wipe — so using it as the next round's start put
that start ~6 s before the previous round's clock even expired;
[ROSTER_FINDINGS.md](docs/ROSTER_FINDINGS.md) measures it on the clock and the
roster (*the round start MOVED to the clock reset*). The gap between one round's
end and the next one's start is the post-round period. Kills there are legal and count
[domain:rounds/post-round-period], so since `round-0.4.0` an event landing in it
belongs to the round just decided; the last round closes one median gap after
its end. At match end the scoreline gives way to the end screen, so the deciding
increment is often never read; since `round-0.5.0` the match-end rule
[domain:rounds/match-end] infers that final round and its winner
(`end_source = match_end_rule`). Every stored round carries
`start_source`, so a round built the old way cannot read as current.

| Stage | What | Status |
|---|---|---|
| 00 Ingest | fingerprint → profile, manifest, no media copied | **done** (`probe`, `ingest`) |
| 01 Gate/segment | frame state → bounded play spans | **rule-based baseline** — `off`/`idle`/`active`, not the doc's trained buy/in-round/post-round/menu/spectate classifier. No labelled data yet. |
| 02 Deterministic extractors | HUD, killfeed, minimap, main-view | **partial** — see below |
| 03 Event proposal | fuse stage-02 into typed candidates | partial: `coach` persists player kill/death observations and review windows; broader engagement fusion remains open |
| 04 VLM adjudication | ambiguous band only | not started |
| 05 Reconcile | source priority + label-free invariants | `reconciliation.py` preserves detector evidence and disagreements. Scoreboard credit candidates are promoted only by repeated agreement or a strict read; identity claims remain channel-attributed and unresolved on disagreement. Broader entity reconciliation remains partial. |
| 06 Metrics | pure versioned functions | exploratory `coach` state baseline with session holdouts; real-data probability evaluation currently lacks roster coverage |
| 07 Narrate/query | footage review | `coach` writes a linked review index; no automated coaching narrative |
| 08 Correction loop | not started |

### Stage 02 detail

Built and populating in the store: round clock, both team scores, HP, shield,
ammo (mag + reserve), killfeed **entry count**, and killfeed **player
attribution** (kill/death, with the stack positions needed to count entries).

Built and stored as context-free events: the **Tab scoreboard** (`scoreboard.py`)
— all ten display rows' K/D/A, local-row highlight, credit OCR evidence, source
geometry, and portrait composition descriptors. `scan` writes these observations
to `events/scoreboard`; it does not assign a player or agent. `audit` adjudicates
repeated credit reads and accepts separately supplied, channel-attributed identity
claims. Display-row indices are local to an opening and are never treated as stable
identity because the top roster compacts when an agent dies.

Not built: **main-view detection**. The **combat report** reader
(`reticle/combat_report.py`) stores what each sampled frame of the post-death
panel shows, and `adjudication.combat_report` recomputes panels, rounds and
kills from those rows. Cross-channel identity
claim production from roster portraits, minimap icons, and killfeed portraits is
still incomplete in the production pipeline.

**Minimap position tracking (self) is built and wired in as of 2026-09-02**:
`reticle minimap <session>` writes `l1/minimap` at 15 Hz over active spans —
self is a filtered track, validated against two independent ground truths
(the X mark a death leaves, and the map's physical chokepoints; see
[the prototypes archive](docs/archive/PROTOTYPES-through-2026-09-23.md)). Ally
icons now carry identity: `round_entities.session_lifetimes` joins them into
per-round lifetimes and `adjudication.identity.assign_ally_pieces` names each
piece from its portrait art ([ROUND_ENTITIES.md](docs/ROUND_ENTITIES.md)). The
visibility (dA/ds) computation this was gating is still unbuilt.

§2 calls the homography trivial, and `MinimapMode.has_static_homography`
records per session whether a single constant transform exists — true for
every capture from 2026-08-23 evening on.

The **combat report** [domain:combat_report/panel-layout], shown at each of the
player's deaths [domain:combat_report/appears-on-death], gives engagement-level
data the killfeed cannot. Its reader places every field relative to the panel
header, because the panel moves with its row count. The banner name changes
between deaths
(`Chef`, then `Harbinger` on one session), which may mean it follows the
spectated player rather than the local one.

## Checking against the game's own numbers

Two commands exist for this, and they are the only checks that compare against
something outside the pipeline rather than a domain invariant.

```
reticle kd    <session>          running K/D per round, from the killfeed
reticle board <session>          read every Tab scoreboard and score us against it
```

`board` reads all ten rows of the scoreboard, including credits, and detects the
local player's row from the yellow outline (no name reading — see
`scoreboard.py`). Per opening it prints the board's K/D beside ours, so the first
divergent row names a window of a minute or two rather than a whole match. On
`96aa1ae9b96f` it agreed exactly across 21 consecutive openings before the first
miss. The stored path keeps detector output context-free; identity fusion belongs
to `audit`/`reconciliation.py`.

Ask the player to open the scoreboard once a round when recording; it costs the player
nothing and it is worth more than any invariant.

## Wallbangs are a finding, not just a parsing problem

The wallbang arrow is currently something to see past when reading a name, but
§4 already excludes wallbang duels from the aim metrics ("no visual contact") —
and an exclusion rate is itself diagnostic. A kill or death through a surface is
its own coachable category: prediction, recon and map knowledge rather than aim.
The icon is detectable, so capture it as a field on the entry when the icon list
lands, rather than only stepping over it.

## What this is for (decided 2026-08-25)

### The endstate, as originally framed (2026-08-26)

Asked directly, at the end of the minimap labelling session:

> For this basically event-tracking phase, my ideal endstate would be real-time
> labelling of a VOD of enemies and allies on screen and on minimap, as well as
> labelling of abilities and pings on the minimap, and position estimation of
> enemies and allies, leading into logging and statistical analysis of duels and
> rounds as events, using the win probability model discussed, and including
> shooting error and ability to surface clips denoting notable patterns.

### The NORTH STAR for the entity channel (recorded 2026-09-06)

Asked for a visually checkable proof of work for this portion of the pipeline:

> a system that can annotate the vods, highlight the abilities, players,
> viewcones, pings, and any other icons as they evolve throughout a match

**This is an acceptance test, and it outranks any per-detector metric.** A
number on a held-out set says a detector is right on the frames someone chose;
an annotated match says the whole channel is right on the frames nobody chose,
including the ones between the samples. Every failure this repo has paid for
twice -- a confident wrong fit, a detector validated on one clip, a threshold
that worked on the session it was swept on -- is a failure a rendered match
would have shown in seconds.

Three things follow, and they re-rank work:

* **`reticle/overlay.py` is the vehicle and it already exists**, with the right
  discipline built in: *this module draws; it decides nothing*, every value
  comes from calling the real extractor. It covers the killfeed, scoreline and
  bottom HUD, and since 2026-09-06 the minimap channel too (`--no-minimap` turns
  it off). Extending it across that channel is the concrete form of this north star;
* **"as they evolve" means the overlay must render TRACKS, not per-frame
  detections.** An entity that flickers, swaps identity, or teleports between
  frames is visible instantly in a video and nearly invisible in an aggregate.
  That is the same argument `track.py` was built on, and this is how it gets
  checked;
* **it wants every channel drawn at once**, which is what makes it a test of
  the ENTITY MODEL rather than of five detectors. Abilities, players, view
  cones and pings sharing one frame is exactly where mutual exclusion and the
  count constraints either hold or visibly do not.

It is also the cheapest possible instrument for the perceptual questions this
repo keeps asking me to answer: a rendered match is a thing the player and I can
both look at, which no confusion matrix is.

### The endstate this serves

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
* **shooting error comes from the in-game UI, not from us.** asked
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
  finds is only useful if it comes back as footage, and *the clips likely
  need a higher fidelity pass to get the exact bounds.* So the event log's
  timestamp locates a clip; it does not define it. Detection can stay cheap and
  sampled, with an expensive pass run only over the handful of moments that are
  actually going to be cut. That is a two-stage design, and it means precision
  of event TIMING is not a constraint on the main extractors -- a useful thing
  to know before anyone raises a sample rate to chase it;
* **whether any of this can be a pure streaming algorithm is open.** *if
  we want to try to do this with a pure streaming algorithm for efficiency I
  actually don't even know if it's possible.* Nor do I, and the honest answer
  has parts. Per-frame reads (killfeed, HUD, minimap detection) stream fine. Two
  things historically did not: the static map was a per-session median and
  `active` spans came from segmenting the whole file. The first is now removed:
  readers load baked `(map, profile)` geometry before streaming and session
  pixels may only size and place the widget
  [domain:capture/session-pixels-are-not-the-map]. `active` span derivation remains the
  future-context obstacle, and the round-phase detector is the first candidate.

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

* a round passes through multiple states, which provides temporal context, but
  these observations share an outcome and are not independent samples. Weight
  rounds equally and keep whole sessions out of training during evaluation;
* WPA is continuous but inherits model error. It does not guarantee greater
  statistical power or measure the causal effect of a player's decision;
* conditioning is automatic. "Win% on first blood" stops being its own question
  and becomes the average WPA of the first kill, already conditioned on state.
  A 5v1 peek and a 5v5 peek are never averaged together, which is exactly
  the objection to counting exposed angles;
* it handles the post-plant rule change natively, because phase is in the state.

**Co-equal goal: film retrieval.** The largest |WPA| events *are* the list of
  moments worth reviewing under the model, rather than proof of what decided
  a session -- and it is the
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
the policy the player already plays and can never say what a different policy would
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

the domain knowledge, 2026-08-25. None of this is recoverable from the code
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

**Counting exposed angles is the other half, and it is conditional.**
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
Run It Back never reaches the scoreboard, and a Kayo ult down may not either
[domain:rounds/resurrection-mechanics] —
but both are duels that were lost, and §4's metrics are about duels, not about
the end-of-match tally. the position (2026-08-25): **perfectly matching the
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
asking the player to open Tab once a round. 79 openings pinned a miss to a single
round on `223d636bf8d2`.

This raises the value of recording a revive mark rather than lowering it: the
point is not to drop those events to match the board, it is to tag them so
stage 06 can include or exclude them per metric. A kill undone by a Sage revive
is also its own coachable category, the same argument as wallbangs above.

## Open design question: engagements without a kill

The killfeed fires on deaths and revives [domain:killfeed/revive-entries] and
never on a duel nobody died in, so keying stage 03 on it alone would
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

`reticle/glance.py` is one fixed encoding for every perceptual question this
repo asks: a sheet of ringed items, each answered from a closed set, with
planted controls that void the sheet when missed. Its module docstring gives
the reasons, the grammar, the invariants and the control rule;
`prototypes/glance_cams.py` is the first thing built on it. A VOID sheet means
the question cannot be read at that magnification, and the next move is a
labeller, not a threshold. The cam sheets drew their controls from the 79
`enemy` and 31 `question` marks, placed long before the question existed.

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
quiet run prints one line and a moved number is loud. Its module docstring
gives the two kinds of dependency (invalidating `deps`, explanatory
`context`), the four verdicts, the pass-only baseline and the commands;
`fingerprint`, `wilson` and `bootstrap_ci` give their own reasons, including
why every interval must be deterministic.

**A moved number carries whether the move CLEARS ITS OWN NOISE**
(2026-09-06). `metrics.wilson(k, n)` covers anything k-of-n and `bootstrap_ci`
anything else, passed to `record(ci={...})`; a `CHANGED` verdict then prints
both intervals and says `SEPARATED` or `within noise`. **It applies to CHANGED
only.** On `BROKEN` the deps AND context are identical, so the number had no
licence to move at all, and an interval there would excuse exactly the small
unversioned edit the check exists to catch. Reproducibility and significance
are different questions and only one of them is about sampling. `--self-test`
asserts a CI never softens `BROKEN`.

**n is the number of INDEPENDENT units, not of observations.** `roster_alive`
reports 43/48 probes agreeing and that is not 48 samples -- six probes inside
one round share a roster state, so it records the ROUND rate instead: 6/8,
95% CI **[41%, 93%]**. And this is why pixel counts must never be fed to
`wilson`: `floor_mask_eval` compares masks over ~225k spatially correlated
pixels, where an interval would come out microscopic and be badly wrong.

**First retroactive read, and it corrects a claim already written down.**
`NOTES.md` records the ability channel's current best as *worse than the 0.49 @
0.85 that was on record, on three times the data*. Recall 0.85 rested on 27
positives -- 95% CI **[0.675, 0.941]** -- against 0.68 on 85, CI
**[0.577, 0.772]**. Those overlap, so **the decline is not established**; the
old number was simply too weak to be worse than. The detector clearing the
0.252 class baseline IS established (no overlap). Note the test is conservative
in one direction: non-overlap implies a real difference, overlap does not
disprove one, so read it as *not shown* rather than *not there*.

Wired in so far: `enemy_detect_eval.py`, and `dynamic_eval.py` for the held-out
fit, the pool composition, and the painted mask. A new eval should record too;
one `metrics.record()` at the end is the whole cost.

## Open defects

- **A single-frame detection is discarded** (`KF_MIN_OBS = 2`), which is right —
  but it means any detection fault that thins a track to one frame costs a whole
  event rather than degrading it. Four of the five misses the player found by hand on
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
  weapon slot itself (abilities) [domain:killfeed/ability-kill-icon]. Rather than enumerate them — which would never
  finish, since each patch can add more — `killfeed.py` keys on what a *name*
  is: several glyphs rather than one solid shape, with names on both sides of
  the divider. That handles unseen icons for free.
- **Two sessions are not clean comparisons, and both for the same reason: the
  killfeed and the scoreboard genuinely disagree.** `ff636d173b07` is a Phoenix
  game, `bfad2778a372` has an enemy Phoenix, and both are now fully explained by
  the same rule, stated below. Do not tune the extractor against either.

  The rule [domain:rounds/resurrection-mechanics]: **Sage and Clove revive after a real death and that
  death counts; Phoenix and Kayo grant the second life before the fact — Run It
  Back ends in a self-kill or a real kill and then returns the player, Kayo can be
  downed and either finished or picked back up — and those never counted.** It
  applies to the kill side as well as the death side.
- **Thin tracks are the leading indicator.** An entry seen in <=4 of a possible
  ~12 sampled frames is either barely caught or about to be split in two. If a
  new capture reads badly, count these first — 7 of 290 across the set now.

  Long tracks exist too, and long does not mean merged: 154 of 2859 counted
  tracks exceed 12 samples. [ROSTER_FINDINGS.md](docs/ROSTER_FINDINGS.md)
  (*Two tracker defects* and *`over_long` is not a merge detector*) gives the
  counts, the one merge confirmed by rendering and the single entry on a frozen
  frame; `reticle audit` reports both populations and marks frozen-frame tracks.
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
- **The M key removes the minimap, and it is the SAME error class as the death
  screen.** the player found it and recorded it deliberately (`2026-09-05
  17-55-32.mp4`): opening the full-size map takes the corner widget away
  entirely, so the minimap ROI holds nothing but live world. Measured on that
  clip, against a static map built from a second clip of the same session:

        widget drawn    corr +0.80 .. +0.89
        M key held      corr -0.03 .. +0.09
        usable()        TRUE on every widget-absent frame

  So `minimap_temporal.drawn()` separates it with the same margin it was built
  for, and `usable()` does not see it at all -- exactly as `drawn()`'s docstring
  says, one regime later. Two independent causes now produce widget-absent
  frames, and this one is **player-initiated and can happen at any moment in a
  round**, which the death screen cannot.

  **The shipped minimap position reader had no widget guard of any kind** until
  `minimap-0.2.0` adopted `minimap.widget_drawn`; before it, `cmd_minimap` read
  every frame inside an active span. Measured over all 27757 frames of
  `a06f04a0059f` at 15 Hz:

        usable()  refuses    614  (2.2%)
        drawn()   refuses   1394  (5.0%)
        the gap             780  (2.8%) -- kept by usable(), refused by drawn()
        harvested from those frames:  3605 self candidates, 4178 ally

  So **5% of the shipped position track was built on frames with no widget in
  them**, and adopting `usable()` alone would recover under half of that. The
  detections are not few: widget-absent frames yield 2.6 self candidates each,
  because `self_rings` is looking at open scenery.

  Closing it moves stored numbers, which is why it was measured first rather
  than patched -- but 5% is far past the level at which the position track's
  validation (the X-mark and chokepoint ground truths) can be assumed to still
  hold, so both were re-run against the guard (`reticle/version.py`,
  `minimap-0.2.0`).
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

   **A widget drawn at another size, place or orientation is transformed, not
   abstained on** (the player, 2026-09-28, quoted in `reticle/widget_frame.py`).
   `reticle widget-fit <sid> --write` stores the placement and tags the session
   `minimap:variant`, so its numbers pool apart.
6. **Label the map.** the player is labelling maps for future captures. Geometry
   is shared between sessions on the same map: `geometry.map_of` reads the
   `map:` tag, and `doctor`'s COVERAGE check reports a session without one.
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
   the player sets it that way deliberately -- Valorant's defaults both rotate the map
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
10. **Record the minimap size.** the player is enlarging it from 2026-08-26. Icon
    extraction is resolution-bound, not algorithm-bound: at the original size an
    icon is a ~12 px ring around a portrait, the ring does not survive
    thresholding intact, and every approach tried topped out at 77-79% of frames
    that provably contain a visible enemy. A larger widget should move all of it.
    Record the size per session -- geometry and icon thresholds both scale with it.
11. **Record in 4:4:4 if the encoder allows it, and record which was used.**
    Measured 2026-08-26 [domain:capture/chroma-420]: 4:2:0 alone destroys 34% of enemy-rim pixels and 22% of
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

12. **The minimap has NO opacity setting. ANSWERED by the player, and do not ask
   again.** Valorant does not expose one, so the widget being semi-transparent
   over the void [domain:minimap/transparency] is a permanent property of the problem, not a capture setting
   that could be fixed. Every approach must be built to survive it.

   **Recorded here because it has now been asked twice.** the player answered it once
   before and this checklist still said "Unresolved", so a second session spent
   it again — and worse, offered it as the highest-payoff next step. That is the
   documented failure mode of this file: a question written down as open stays
   open forever, because nothing marks it answered. **When the player answers a
   standing question, write the ANSWER here in the same turn**, not a note that
   it was discussed.

## A model of where my judgement is reliable

`reticle/judgement.py`, built 2026-08-27 from a question of the: novelty
seems to carry the most information, the way human memory over-weights novel or
emotionally volatile events -- is there a core idea there?

There is, and the naive version was tried and failed the same day: onset
sampling, novelty in INPUT space, selected 68% artefacts against the existing
labels and would have gutted the ability class (8 rows against 45). The module
docstring and its `stake` block give what survives -- surprise weighted by
consequence, measured as calibration gap, runs and a Bonferroni-corrected
change point, with stake set by a claim's level and the cost of being wrong.

Measured in `--self-test` over 2000 coin-flip sequences of n=30: **corrected
fires 0.8%, uncorrected would fire 19.9%.** A real change (15 right then 15
wrong) is caught at exactly #15.

First read, 39 predictions: no regime change anywhere, and every domain except
`minimap` and `rounds` is underpowered for one. `geometry` is overconfident by
0.85 -- that is the old retrospective batch. The directional hint in both
powered domains is the same and does not yet reach significance: accuracy falls
in the second half of each, and both second halves are dominated by **guesses at
constants** rather than predictions about what running existing code will do.

**Stake: what it costs to be wrong, which is not what accuracy measures.**
predicting a file's word count has a different salience to predicting
whether your ontology was correct. With cost recorded, over 33 backfilled rows:

    level         n    acc     gap   mean cost
    ontology      8   0.38   -0.46         2.1
    mechanism     7   0.43   -0.38         1.1
    value        13   0.62   -0.05         0.2

Cost orders as predicted, an order of magnitude apart. **The gap column is the
finding nobody was looking for**: the claims that cost the most are the ones I
am most overconfident about. Stake is reported as a percentile within this
log, never as an absolute, because every decision it feeds is a ranking.
`stake()` is a prior, to be replaced by a fit of `level x rests_on -> cost`
once enough rows carry an observed cost.

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
    ask the player before deriving               5  prose only -- judgement call, but
                                               "on the FIRST failure" is countable
    look at the image before measuring      3  PARTIALLY ENFORCED (2026-09-02):
                                               label_ability.py's `candidates`
                                               source now REFUSES to launch until
                                               `review_candidates.py` has rendered
                                               and content-hash-stamped that exact
                                               candidates file (see it and
                                               `filter_ability_candidates.py`).
                                               It can force the render to happen;
                                               it cannot force the looking, which
                                               is the gap the 3rd recurrence lived
                                               in -- twice a labelling GUI was
                                               launched against a candidate file
                                               nobody had rendered at all.
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
   go look). Log irreducible ones `verdict: aleatoric` and route them to the player.
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

**Ask the player before deriving, when the player can just look.** The searchable mask was
derived and re-derived five times on 2026-08-26, each attempt measured and
plausible and wrong, and the player named the defect by eye every time in seconds.
`paint_map.py` settled it in one pass and the result transferred to a second map
at 92.8% IoU. The project's own history says the same thing more quietly: every
stage that works was preceded by a labelling pass. **On the FIRST failure of a
perceptual question, build the tool that asks the player** -- not the fifth.

**In vision work, look at the image before measuring it.** Rendering the
offending candidate took one tool call and settled what three analysis scripts
had not. Several dead ends that day -- two flood-fill variants, a distance-to-
void analysis -- would have died in seconds against a picture.

**Third recurrence, 2026-09-02, and this is the one that got a real gate.**
the player recorded two controlled Cypher clips; `scan_ability_clip.py` was run and
a labelling GUI launched straight off its output TWICE without anyone
rendering a single candidate first. Both times the candidates were mostly
garbage from detector bugs (self-derived geometry baking a persistent device
into its own "empty floor" reference; a shared static map's pixel-value
mismatch against the clip's own footage fragmenting the viewcone into fake
icon-sized blobs), and the player spent real time clicking through it before either was
caught. The question, verbatim: *this has already happened multiple times,
how can you note this so you don't keep repeating it.* Prose had already
answered that question twice and been ignored both times under time pressure,
which is why `review_candidates.py` exists now — see the table above.

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
the two maps in use were fine. **Run `minimap_geometry.py --all` whenever that
file changes.** Keying geometry per (map, profile) is what made that
affordable: it is one build per (map, profile) rather than one per session, and
about 5 minutes end to end, so the stamp stops being a thing people defer.

**A new reader joins the PASS. Recorded 2026-09-05, and it is an architectural
rule rather than an optimisation:**

> it not being a reader raises an architectural question. The reason we're
> structuring it as a pipeline is for efficiency. If we're just leaving easy
> efficiency gains on the table and being sloppy and adding bloat, even on a
> first draft and exploratory phase that's not a good sign.

The occasion: `reticle/passes.py` was built that afternoon so a reader could
ride an existing decode -- decode is 93% of a stage's cost -- and `ping_scan.py`
was written the same day taking a VIDEO PATH, so it could only ever be another
full decode. the player asked why the corpus re-scan did not include pings, and
that was the answer.

**The cost of the miss is not the wasted decode, it is that the architecture
becomes decorative.** A registry that the newest code does not use is not a
registry, it is a file; and a first draft is exactly what later work is copied
from, so exploratory phase is an argument for the rule and not an exemption
from it.

The shape that satisfies it: detection is a function over frames
(`reticle/ping.py` `sightings`, grouped by `Grouper` and `resolve`), a standalone
scan decodes for itself and calls it, and `PingReader` accumulates frames from
somebody else's pass and calls the same function. Verified both ways return 14 pings and the same four classes.

One constraint is now an invariant: **a reader never builds a median**. It reads
the baked `(map, profile)` reference and streams in one phase. Session pixels
may measure only the widget's dimensions and placement
[domain:capture/session-pixels-are-not-the-map]; `doctor` rejects cache APIs and
capture medians outside the two exceptions AGENTS.md names.

**ALIGN THE WINDOW TO THE QUESTION BEFORE READING ANYTHING OUT OF IT. This is
now the most repeated mistake in this codebase -- FOUR times on 2026-09-06
alone, in four different files, by someone who had already written the note
about the third one.**

Every instance is the same shape: a CORRECT reader, measured over the wrong
span, producing a confident number about a question nobody asked.

    probing "starts at 5" from 6% into a round      5/22  -> 40/40
      -- the roster is not drawn for the new round yet; `round-0.2.0` moved
         the round start to the clock reset (see *Pipeline status*)
    a refinement window butted against a run's end  0.32-0.43 -> 0.00-0.06
      -- `t1` is the MEASURED end, up to a sample period early, so the window
         read the object's own tail as evidence against it
    a round's killfeed deaths vs a roster read at 92% of it   19/20 disagreed
      -- rounds end in wipes; every death after the last probe was charged to
         a roster that had not seen it
    previous-round killfeed entries counted into this round   58% -> 88%
      -- an entry stays on screen for seconds, so `t_first` lands inside the
         next round's window

And the one already recorded before today, now in
[the prototypes archive](docs/archive/PROTOTYPES-through-2026-09-23.md): an
ability series read against the whole decoded axis rather than its own query
window reported `detect` firing on 75.5% of frames at the median query and
75.7% at the max, across 53 queries -- uniformity that reads as a finding and
is arithmetic.

**Why it keeps happening: the wrong span never errors.** It returns a number of
the right type in the right range, and it is usually a PLAUSIBLE number -- 58%
agreement looks like a detector that mostly works, not like a window that
starts too early. Nothing in the type system, the invariants or the code review
catches it; only asking "what span is this average over, and is it the span the
question is about" does.

Three things that make it findable:

* **a systematic sign is the tell.** All four had a residue skewed one way --
  killfeed always ahead, never behind. Random error is symmetric; a one-sided
  residue is almost always an alignment fault, not noise;
* **state the span in the output.** A figure printed without the window it was
  computed over cannot be checked by the person reading it, including you an
  hour later;
* **`win_lo`/`win_hi` already exist for exactly this** (`ability_series`), and
  the convention there -- a feature wanting a local window derives it from
  `t_ms` and still respects the decoded bounds -- is the general answer.

**THE AGGREGATE IS THE MEASUREMENT. Choosing max where median belongs has now
inverted three separate results, twice in one session (2026-09-06).** This is
the sibling of *align the window to the question* above -- that one is about
WHICH SAMPLES go into a number, this one is about HOW THEY ARE REDUCED to one --
and it fails the same silent way: a plausible number of the right type.

    self_icon_dist      min over a track vs MEDIAN      3 of 5 real trapwires
                        kept vs 5 of 5. Min stopped meaning "is the player
                        here" and started meaning "was the player EVER here"
    "cast made while     max over a window vs MEDIAN     8/119 (7%) vs 28/41
    standing still"      (68%). A sevenfold swing, and the 7% was quoted to
                         the player before it was checked
    motion class from    per-STEP speed vs a windowed    inverted the result
    the self track       MEDIAN                          outright: tracker
                         jitter spikes to 80-724 px/s against RUN_PX 45, so
                         every jittery step was classified as RUNNING

**The tell is that an extreme-value aggregate answers a different question than
the one asked.** "Was the player still" is about the typical value in a window; a max
answers "did anything in this window look like motion", which one bad frame
satisfies. Ask which question the aggregate actually answers before quoting it.

**The cheap enforcement, since prose here has a poor record: report TWO
aggregates whenever a per-sample quantity is reduced over a window, and say
which one the claim rests on.** All three failures above were visible the
instant both were printed side by side, and in each case that cost one extra
column. A single-aggregate figure derived from a noisy per-sample series should
be treated as unverified until its sibling has been looked at.

**A promoted function is DELETED from its prototype and re-exported, never
copied.** Promotion has happened twice and took two different shapes, and only
one of them is safe. `ping_scan` was done right: detection moved to
`reticle/ping.py` and the prototype now imports `Grouper`, `resolve` and
`sightings` from it. `minimap_position` was done wrong: `reticle/minimap.py`
was created by COPY and the prototype kept byte-identical `floor_mask` and
`static_map` definitions of its own.

Nothing disagreed, which is exactly why it survived a year of review -- two
copies of the same code agree until one of them changes. The moment the
shipped `floor_mask` moves (its 9 px dilation is a live candidate, being a
length that should scale with the widget), every eval importing the prototype
keeps silently measuring the old behaviour while the pipeline measures the new.
That is the `built_by` stamp lesson with the stamp missing: the ARTEFACT was
versioned, the CODE PATH was not.

**CORRECTED 2026-09-06: they had ALREADY diverged when the paragraph above was
written, and it said they had not.** The `floor_mask` docstring in
`reticle/minimap.py` records the fork, the reconciled gate and its IoU against
the two paintings. The slab-only gate looked correct and was not -- the player,
shown the two blobs it lost: *why would floor mask exclude bomb sites? Those are
part of the floor.* The tint is paint ON the floor.

**Rebuilt 2026-09-07, and the store is now keyed per (map, profile)**; the 36
per-session npz held only 5 distinct geometries.

**It is checkable rather than remembered: `reticle doctor`, added 2026-09-06.**
It matches definitions by NAME in both trees, with a small allowlist for
genuinely local helpers that has to be edited to grow. Its docstring records
why the `git grep` meant to catch the fork passed clean for ten days, and why
doctor runs at pickup rather than as a git hook. `doctor` is the repo's half of
`status`: `status` says what is in the store, `doctor` says what shape the
codebase is in. Its checks are listed in `doctor.run`, each a fault that has
actually happened here; only an ERROR fails the command, since a checker that
fails on everything gets ignored. Its manifest check found `2ba870ccbd50`
tagged `small-widget` and ingested `valorant-16x9-bigmap` on its first run;
[the prototypes archive](docs/archive/PROTOTYPES-through-2026-09-23.md) records on 2026-09-07
that the tag was wrong.

Since 2026-09-26 it does run from Claude Code hooks (`.claude/settings.json`),
which differ from a git hook in that hurry cannot skip them:
`tools/hook_pickup.py` prints NOTES.md, the `reticle.status` header and
doctor's summary at session start, resume and compaction, and
`tools/hook_doctor.py` refuses to end a turn on a geometry-guard failure or a
doctor ERROR, once per turn, and reruns doctor only when the tree changed.
`tools/hook_no_session_url.py` blocks any call that carries a Claude session
URL. `tools/hook_session_score.py` writes one objective row per session to
`~/reticle-store/notes/sessions.jsonl` (turns, tool calls, edits, tests,
commits, compactions, effort, model); it counts no corrections, because a
phrase regex matched two of 201 recorded prompts, both wrongly, and a wrong
count is worse than a null.

*Added 2026-09-05, after a review found the duplicate. The first version of
this note claimed the rule was already here when it was not, which is the
failure mode the note itself is about.*

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
  template. Digit templates are *mined from the footage* (`glyphs`),
  not from a font file, and committed as `.npz` keyed by profile.
- **Version stamps drive recompute.** Bump `EXTRACTOR_VERSION` → re-decode;
  `SEGMENTER_VERSION` → spans recompute from stored L1 in milliseconds;
  `HUD_VERSION` → re-read from pixels: `scan --only hud` rereads the crop cache
  (`roi_cache`), and `--from video` decodes.
- **`segment` must never open the video.** Recomputing spans from stored L1 is
  the whole point of the L0/L1 split, and it is what makes threshold sweeps
  free. The `hud` command re-opens the source; `scan --only hud` reads the crop
  cache instead.
- **Raw media is never copied.** Manifests point at where the file lives.
  Lossless crops of a fixed reader ROI (`reticle/roi_cache.py`) are not a copy
  of the capture (player, 2026-09-25): they let `reticle trial` rerun a reader
  with no decode.
- **Deaths per round is not a usable invariant** — Sage resurrect and Clove
  self-revive both let a player die twice in a round
  [domain:rounds/resurrection-mechanics].
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
  instruction from recorded 2026-08-26: do this unprompted.** It is the first
  thing read when picking work back up and it decays fastest, so a stale one
  actively misleads. Detail does
  NOT belong there -- it belongs in the prototype docstring next to the code it
  describes, and in the commit message, both of which are searchable and neither
  of which goes stale silently. One session left it at 560 lines and it had to
  be cut by two thirds.

  **On the trigger, honestly: there is no context-usage readout available.**
  the player asked for "around 94% of the session limit"; that cannot be implemented
  literally, because nothing exposes a percentage to work from. Guessing at one
  would be worse than not having it. Use what IS observable instead:

  * **rewrite it when a result changes what the next session should do first.**
    This is the real trigger and it is not an end-of-session activity at all --
    a finding that closes a line or opens one should update "Picking up" as part
    of recording it, in the same commit;
  * refresh it when several verified results have landed without one;
  * refresh it when the player signals winding down, or asks for a handoff.

  The durable protection is the convention above it -- commit whenever a result
  is verified -- because that survives a session ending abruptly, which no
  end-of-session ritual can. Treat the handoff as a summary of commits already
  made, never as the only place a finding is written down.

## Repository declarations and why they exist

Moved verbatim from the root `CLAUDE.md` on 2026-09-23, when the root guidance was merged into `AGENTS.md` and compressed to one line per rule. These are the full arguments; `doctor` enforces the mechanical half of each.

- **BEFORE CALLING ANYTHING A BLOCKER, READ THE FIELD THAT SAYS WHY IT REFUSED.
  Not the count of refusals.** A count is a symptom and is trivially
  computable; naming it the cause is a claim, and the reason is usually already
  stored beside it. `lineup`'s refused slots each carry a `reason` -- *not
  separated from Raze* -- which says PAIRWISE TIE and therefore says a
  constraint might break it. Counting them instead gave *3 of 5 named*, which
  read as a coverage fact and was an artifact of the margin being computed
  before the assignment. Twelve of 79 refusals were ties already broken. The
  provenance was perfect and the attribution was wrong, so no citation check
  catches this: it is the aggregate hiding the mechanism, which this file
  already warns about from the other end.
- **A measured result is WIRED or it is declined, in writing.** Leaving a
  prototype measured and unpromoted was the silent default, and writing it up
  made it look alive: `doctor`'s ORPHAN check exempts anything a document
  names. `doctor`'s PROMOTE check now reads `notes/predictions.jsonl` and
  reports every prototype named there that no module in `reticle/` uses.
  Declining is legitimate -- a refuted result belongs in `prototypes/` -- but
  it costs a `"wire": "no"` with a `"wire_reason"` on that row. Silence is no
  longer an option.
- **DOMAIN FACTS LIVE IN `domain/*.toml`, AND PROSE CITES THEM.** What is true
  of VALORANT and its capture goes in one TOML table per fact with a `claim`,
  a `kind`, a `known` provenance and a `since` date; everything else references
  it by a bracketed `domain:` token naming the file and the fact, instead of
  restating it. The tangle this replaces had
  the minimap vision rule in five files and *semi-transparent over the void* in
  twenty-four, each restatement free to drift, while facts the player supplied
  once got no consumer and were lost. `doctor`'s DOMAIN check makes a citation
  resolving to no fact an ERROR, and reports every fact nothing cites plus every
  file that restates a fact through one of its `phrases`; a fact with no
  `phrases` is not checked for restatement. In `docs/archive/`, dated history,
  DOMAIN checks citations and skips restatements; `NOTES.md` and `BACKLOG.md`,
  bounded working documents, are checked (amended 2026-09-23). Read one with
  `reticle domain [DOMAIN] [--id ID]`. Pipeline accuracy is NOT a domain fact --
  outcomes belong in `notes/predictions.jsonl`. Facts carry a dependency graph
  too: a GIVEN fact (`player`, `observed`) rests on nothing and may not declare
  `depends_on`, an `inferred` one must name what it rests on, a `measured` one
  must name a `source`, and the graph must be acyclic. That is what stops a
  guess being laundered into a given.
- **A NUMBER QUOTED IN PROSE CITES THE RUN THAT PRODUCED IT.** The form is a
  bracketed `metric:` token carrying the series, the session and the VALUE, and
  `doctor`'s QUOTED check compares it to the latest `pass` row, or to the one
  run a `~<run>` pin names. A citation to a
  series with no recorded run is an ERROR; a quoted value that no longer matches
  is a finding naming the file and both numbers, because the honest fix is
  sometimes the prose and sometimes the number. This existed because `metrics`
  stored 132 runs and nothing linked a single line of prose to any of them, so a
  figure could be quoted, the code could move, and the prose would stay. Read
  with `reticle/quoted.py`; only `docs/archive/` is exempt, as dated history
  (amended 2026-09-23).
- **THE LAYERING IS DECLARED IN `architecture.toml`, AND VERIFIED, NEVER
  DERIVED.** Eight layers over `reticle/`; a module may import its own layer or
  any below it, and every upward edge is blessed one at a time with a reason
  and whether it is eager or deferred. `doctor`'s LAYER check makes an
  unblessed eager upward import an ERROR, reports deferred ones -- a deferred
  import is how an inversion hides -- and reports a declaration that has gone
  stale, which is what stops the file rotting upward into permissiveness. It is
  declared because the DERIVED order is an accident: depth by longest path puts
  `doctor`, `domain` and `decode` beside `version`, since their real
  dependencies sit inside functions. `reticle/` must not import `prototypes/`,
  including by `sys.path` insert plus a bare import, which is the spelling that
  hid two real violations until this check existed.
- **WHO MAY DECIDE A QUESTION IS DECLARED IN `ownership.toml`, AND VERIFIED.**
  One entry per question, naming the owner, what it produces, what it defers to,
  and -- the field to read second -- what it is `not_for`. The word *identity*
  means seven things here -- an agent in a roster slot, an icon being the local
  player, an observation continuing a track, components belonging to one
  ability, an ability's owner, a killfeed entry's victim, and a media file
  being one session -- and modules are named after those words. The negative
  boundary is what stops a module being selected because its NAME matched: `roster` owns
  alive counts and not agent identity, `minimap` owns where the self icon is and
  not which agent the player is, and `track` owns what a proposed identity may
  DO over time and owns no identity at all. Two faults paid for it -- a packed
  living-slot index read as a player named the wrong victim in both rounds it
  was tested on, and `minimap_lifecycle` restated `track`'s continuation ceiling
  until the two disagreed by a factor of two. An owner claims its entry in its
  own docstring with an `[owns:<id>]` token, so a stale entry, a renamed
  output, an unplaced new module, a `defers_to` whose import went away, and a
  `shipped` owner still reaching `prototypes/` are all ERRORs in `doctor`'s
  OWNERSHIP check. A question nothing owns is declared too, with what blocks it,
  and `doctor` prints it on every run: today only `ability-owner`, since
  `adjudication.death` owns `death-victim`. Route with
  `reticle ownership <question>`; the argument stays in the owner's docstring
  and is cited, never restated.
- **WHICH DOCUMENTS ARE LIVE IS DECLARED IN `documents.toml`, AND CHECKED.**
  Undeclared documents rotted the ways the other declarations were built to
  stop. A committed `STATUS.md` fell behind the version stamps it reported.
  `docs/OWNERSHIP_INDEX.md` listed four unowned questions after
  `ownership.toml` had narrowed them to one. A design still called itself
  proposed after `reticle/belief.py` implemented part of it. HANDOFF kept
  counting `## Active:` headings after `BACKLOG.md` dropped them on 2026-09-23,
  so its task checks never fired. `doctor`'s DOCS check reports an unregistered
  document, an entry naming no file, a document no route reaches, a status its
  fields do not support, and an eager document past its word budget. The
  2026-09-23 streamlining plan kept a documentation registry out of its scope
  and put its guidance in existing files. This register asks four fields per
  document, never registers the archive, and blocks only on a broken entry;
  everything else is a finding.
