# Reticle

Vision-based mechanical analysis pipeline for Valorant. The complete project
guide is [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md). This file is every agent's
single root guidance; `CLAUDE.md` imports it.

## Start here

Use [`docs/WORKING_MAP.md`](docs/WORKING_MAP.md) for task routing. Before
changing a subsystem, read `NOTES.md` (the current handoff), the
`BACKLOG.md` task, the owning module docstring and the relevant
`PROJECT_GUIDE.md` section. Minimap and prototype work
also requires `prototypes/CLAUDE.md`; domain attribution and private quotes
remain in `~/reticle-notes/`, outside this public repo.

## Acceptance north star

The entity channel produces identity-bearing events and a visually checkable
annotated match: players, abilities, viewcones, pings and other icons as they
evolve through a VOD. Identity makes movement, continuity, and origin rules
checkable. Prediction, logging and coaching are downstream of observations.
When a perceptual question cannot be derived, ask the player and record the
first failure, not a guessed answer.

## How to write

Strunk governs replies, docstrings, commit messages and `NOTES.md`:

- Omit needless words.
- Use the active voice.
- Put statements in positive form.
- Use concrete language.

The active voice is the load-bearing one: "the geometry rebuilt under me" hid
what "I rebuilt the geometry while my experiment read it" states.

## Global constraints

- Stage 02 is deterministic; no model. Threshold, geometry, normalization,
  and mined templates are the baseline.
- Unknown, refusal, missing widget, stale input, and terminal state stay
  distinguishable; an unread value is `null` with a reason, never a guess.
- Keep raw observations separate from adjudication and later lifecycle events.
  Readers own pixel evidence and report it with scores and reasons;
  adjudication and the lanes own continuity, uniqueness, reach and
  cross-channel priors, and decide whether a find is real. A reader's prior is
  its owner's stored belief, never a copy the reader keeps.
  Stored timestamps are observation times; source evidence must precede an
  inference's promotion.
- Every independent detector/table has its own version stamp and provenance.
  Recomputable rules use stored data and never decode video. Before a
  measurement, rebuild what it reads through: stale cached geometry, and on
  the development matches every stale stream between the change and the
  scored event (`reticle plan` names them).
- Never copy raw media; lossless `roi_cache` crops of fixed reader ROIs and
  retired captures' stream-copied audio are not copies (player, 2026-09-25,
  2026-10-05). New readers join shared decode passes; gate
  dense sampling on opportunity, not outcome. Never silently overwrite evidence.
- A shared decode pass is an execution optimization, not a shared definition: a
  change to one detector never restamps another stream or a rule recomputed from
  stored data. Adjudication stays pure over stored observations, with explicit
  alternatives and evidence links; a late detector answer never becomes an
  event's inferred origin; a review window points into source media with its
  provenance, never as a clip or conclusion.
- Events are the interface, to consumers and to acceptance. Consumers
  (`reticle view`) read only emitted events and stored rounds, never a reader,
  tracker or adjudicator; a missing field goes into the owning event. A change
  is accepted on the events its owning layer emits (enemy tracks, slot
  beliefs), scored per question against replay truth; a reader's own score is
  a diagnostic. A new scorer extends the one harness (QUESTION_ACCEPTANCE B7),
  never adds a prototype.
- **Replay truth covers every entity** (player, 2026-10-05, 2026-10-07). Score
  each find against every entity the replay layer holds there and then:
  players, every ability child of every mapped class, the spike and ult
  orbs. A find on another real entity is that entity's, never `other` or a
  false accept; one on nothing is `nothing_there`; one on an unmapped
  actor is a coverage gap named by class. A scorer that reads only players
  names each class it omits, and why.
- **Fidelity follows the question** (player, 2026-10-04, 2026-10-06): process
  only the detail the use case's questions need, as an engine culls
  detail. Hold coarse beliefs by default; read at full
  fidelity where an opportunity opens, never on the outcome; measure each need
  by degrading truth ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md)).
- Run the least work testing the change: `reticle trial` on the windows
  where it should move output plus the declared sample
  (`reticle dev-sample`), with error bars; adjudications rerun from storage.
  Corpus reruns wait for replay training.
- The HUD and minimap are semi-transparent over the void
  [domain:minimap/transparency]. Search inside the opaque structure; fit a shape
  rather than repairing it with a closing radius [domain:minimap/fit-not-repair];
  never seed label files. Invoke the `labelling-pass` skill before labelling.
- **SESSION PIXELS DO NOT DEFINE THE MAP**
  [domain:capture/session-pixels-are-not-the-map]. A capture may determine only
  the minimap widget's dimensions and placement. All static map values
  (base-map pixels, floor masks, lighting references, detector backgrounds)
  come only from `(map, profile)` geometry drawn from the game's textures
  (`reticle/map_asset.py`). Never add a per-session static-map cache or
  capture median to a reader or prototype except `clip_preflight`, whose
  median sets only size, placement and orientation; `doctor` enforces this.
- **Read pixels as samples of a smooth image** (player, 2026-10-01)
  [domain:capture/capture-resolution]. Name the filter on every resample:
  `INTER_AREA` to shrink, linear or cubic to enlarge or warp, nearest only
  in display code. Score colour and coverage softly and cut once, at the
  decision, as `teardrop` does; never binarise before resampling or
  matching. Fit sub-pixel where position decides. Never enlarge a frame to
  read it.
- **No pure Python on the critical path** (player, 2026-10-02). Per-frame,
  per-sample and per-row work runs vectorised in numpy, OpenCV or scipy;
  never hand-write an algorithm a maintained library provides.
- Never use stored-data bounds or a model's own output as independent evidence.
  Keep unresolved and no-contact opportunities so coverage stays unbiased.
- **READ THE REFUSAL REASON BEFORE CALLING ANYTHING A BLOCKER.** A count of
  refusals is a symptom; the cause is usually stored beside it. Provenance
  can be perfect and attribution wrong; no citation check catches it.
- **CROSS-REFERENCE BEFORE TUNING.** When a detection is wrong, first ask which
  other channel observes the event, and gate one on the other in the layer
  that owns the decision. Tuning a
  threshold, mask or morphology on the erring channel is the second resort.
  Agreement is consistency, not accuracy; store the disagreements.
- Measure a baseline before structural edits, then rerun the real command
  and confirm a known result; a parse check is not verification.
- Hold beliefs about the system as uncertain.
  Before acting on an assumption about an owner, detector or mechanic, check
  it or state its falsifier. Spend effort where uncertainty is largest and cheap
  to resolve, refining only where it exceeds the question's tolerance. A
  surprise may be a tool error; check the instrument before revising the
  system belief. A failed
  prediction revises the belief; record it in the handoff.
- **Continue the prior; widen the search only on surprise.** Context predicts
  most of what comes next: the last frame's stored belief, the match's lineup, the
  adjudicated belief the last run left. Start every reading and experiment
  from that prediction; check it cheaply. Follow a killfeed entry where it
  was; seek a smoke where the match's agents' abilities land; revise the
  belief an experiment tested, never start over. Store the surprise, never
  average it away. A surprise may reopen the verdict it
  contradicts, which reruns once with the new evidence; store the original, the
  revision and the surprise. An unchecked prior is a hidden assumption. Audit a
  prior by a full search on opportunity-gated samples at a cadence fixed in
  advance, stored apart, until its efficacy is statistically significant
  (player, 2026-09-30). A
  surprise-triggered search is no audit sample. Code scoring against a gallery
  or candidate set names the set its context allows (the match's agents, the
  side's five, the slot's predicted agent) and why; the full set is the surprise
  path, justified as the lineup reader's 29 agents are before any
  lineup exists. A prior is evidence, weighed once: a result it shaped declares
  `rests_on`, so the prior never counts again as an independent witness.
- **Ability mechanics are unique per ability** (player, 2026-09-26)
  [domain:abilities/ability-rules-are-unique]: the lifecycle, inputs, minimap
  drawing and screen overlay of one ability predict nothing about another.
  Record each in `domain/abilities.toml`, never by analogy: quantities from
  game files first, qualitative mechanics from the player or observation
  (player, 2026-10-04) [domain:abilities/game-files-outrank-player-quantities];
  [`docs/ABILITY_MECHANICS_SHEET.md`](docs/ABILITY_MECHANICS_SHEET.md) holds the
  questions; a targeted-demo census verifies answers, never discovers them.
- Before a perceptual experiment, log falsifiable predictions in the store's
  `notes/predictions.jsonl`; inspect source images before measuring. On the
  first failed perceptual approach, build the tool that asks the player.
- Commit whenever a result is verified. `NOTES.md` and `BACKLOG.md` are bounded
  working documents, not logs: `NOTES.md` holds only the current handoff;
  `BACKLOG.md`, open work plus the five latest completed tasks. Rewrite them in
  place and move what they retire to a dated file under `docs/archive/`.
  `doctor` HANDOFF checks the limits and that each open item names an
  `Acceptance:` command and an `Evidence:` standard.
- Never put Claude session URLs in repository files or commit messages. Public
  files contain facts; attribution, quotes, and private domain notes stay out.

## Repository declarations

`doctor` checks each of these; `PROJECT_GUIDE.md`, "Repository declarations
and why they exist", argues for them.

- **Wire or decline.** A prototype named in `notes/predictions.jsonl` is used by
  `reticle/` or carries `"wire": "no"` with a `"wire_reason"` (PROMOTE).
- **Domain facts** about VALORANT and its capture live in `domain/*.toml`, one
  table per fact with `claim`, `kind`, `known` and `since`; prose cites them
  by bracketed `domain:` token, never restating them. Read one with
  `reticle domain`. Pipeline accuracy is not a domain fact (DOMAIN).
- **Quoted numbers cite their run** with a bracketed `metric:` token naming
  series, session and value (QUOTED). The check compares only tokened numbers; a
  bare measured number passes silently: record the run and cite it.
- **Layers are declared** in `architecture.toml`. Place every new module; an
  upward import needs a blessed edge. `reticle/` never imports `prototypes/`,
  including by `sys.path` insert (LAYER).
- **Ownership is declared** in `ownership.toml`: one entry per question, naming
  the owner, what it produces and what it is `not_for`. The owner's docstring
  carries its `[owns:<id>]` token. Route with `reticle ownership <question>`
  (OWNERSHIP).
- **Ask the owner; never restate its rule.** Before a fix or any code that
  decides, name the layer that holds the evidence it needs (`reticle
  ownership`, `architecture.toml`); if that owner has the mechanism, call or
  extend it, even when its rule looks like three lines to copy. A restated
  rule compiles, passes its tests and drifts silently.
- **Every agent name is decided by `adjudication.identity`**, the aggregator
  over one arbiter per channel, per entity and side. Each channel pools its
  readings and publishes `identity_claim`s through its arbiter; from another
  channel it takes only a candidate set, a window or a gate, never that
  channel's verdict on the same entity. Owners that bind a death, track, row or
  ability to a witness supply the entity key and ask the arbiter. A claim that
  rests on another entity's verdict declares `depends_on`; an observation a
  prior placed declares `rests_on`. An ownership entry whose output carries a
  name declares `names_agents = true` and defers to `agent-identity`. OWNERSHIP
  errors on an undeclared name producer or an identity event built outside the
  arbiter, and the event validator rejects such events.
- **Documents are declared** in `documents.toml`. Register each document, with
  its kind, status and date, in the commit that creates it. A plan becomes
  `implemented`, naming `implemented_by`, or `superseded`, naming
  `superseded_by`, then moves to `docs/archive/` with a date. Rules have one
  home, `AGENTS.md`, and command lists one, `docs/WORKING_MAP.md`; other files
  point to them (DOCS).

QUOTED skips `docs/archive/`; DOMAIN checks only citations there.

## Running

Use the repository venv:

```powershell
.\.venv\Scripts\python.exe -m reticle <command>
```

At pickup, run `doctor` and `status`.

## Guide routes

`PROJECT_GUIDE.md` keeps the former guidance verbatim. This file holds only
the eager index and global constraints; keep historical measurements out.
