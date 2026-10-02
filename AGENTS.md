# Reticle

Vision-based mechanical analysis pipeline for Valorant. The complete project
guide is [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md). This file is the single root
guidance for every agent; `CLAUDE.md` imports it.

## Start here

Use [`docs/WORKING_MAP.md`](docs/WORKING_MAP.md) for task routing. Read
`NOTES.md` (the current handoff), then the `BACKLOG.md` task, then the
owning module docstring and the relevant section of `PROJECT_GUIDE.md` before
changing a subsystem. Minimap and prototype work
also requires `prototypes/CLAUDE.md`; domain attribution and private quotes
remain in `~/reticle-notes/`, outside this public repo.

## Acceptance north star

The entity channel produces identity-bearing events and a visually checkable
annotated match: players, abilities, viewcones, pings and other icons as they
evolve through a VOD. Identity lets movement, continuity, and origin rules be
checked. Prediction, logging and coaching are downstream of observations.
When a perceptual question cannot be derived, ask the player and record the
first failure, not a guessed answer.

## How to write

Strunk governs replies, docstrings, commit messages and `NOTES.md` alike:

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
  Stored timestamps are observation times, and source evidence must precede
  promotion of an inference.
- Every independent detector/table has its own version stamp and provenance.
  Recomputable rules use stored data and must not decode video; rebuild stale
  cached geometry before trusting derived measurements.
- Raw media is never copied; lossless crops of a fixed reader ROI
  (`roi_cache`) are not a copy (player, 2026-09-25). New readers join shared
  decode passes; gate dense sampling on opportunity rather than outcome. Never
  silently overwrite evidence.
- A shared decode pass is an execution optimization, not a shared definition:
  a change to one detector must not restamp another stream or a rule
  recomputed from stored data. Adjudication stays pure over stored
  observations, with explicit alternatives and evidence links; a late detector
  answer never becomes an event's inferred origin; and a review window points
  into source media with its provenance rather than standing as a clip or a
  conclusion.
- Events are the interface. Consumers (`reticle view`) read only emitted
  events and stored rounds, never a reader, tracker or adjudicator; a missing
  field goes into the owning event, never into a recomputing consumer.
- Run the least work that tests the change. `reticle plan` names the stale
  streams; adjudications rerun from storage; a reader change is checked first
  with `reticle trial` (stored windows, crop cache, no decode); a full scan is
  the acceptance run.
- The HUD and minimap are semi-transparent over the void
  [domain:minimap/transparency]. Search inside the opaque structure; fit a shape
  rather than repairing it with a closing radius [domain:minimap/fit-not-repair];
  never seed label files. Invoke the `labelling-pass` skill before labelling.
- **SESSION PIXELS DO NOT DEFINE THE MAP**
  [domain:capture/session-pixels-are-not-the-map]. A capture may determine only
  the minimap widget's dimensions and placement. Base-map pixels, floor masks,
  lighting references, detector backgrounds, and all other static map values
  come exclusively from baked geometry keyed by `(map, profile)`. Never add a
  per-session static-map cache or capture median to a reader/prototype; `doctor`
  enforces this. The only exceptions are the geometry builder and
  `clip_preflight`, whose capture median sets only size, placement and orientation.
- **Read pixels as samples of a smooth image** (player, 2026-10-01). A
  minimap icon spans about 13 px at 1080p, so a reader keeps every partial
  pixel. Shrink with `INTER_AREA`; enlarge, warp or shift with linear or
  cubic interpolation; name the flag on every resample, since `cv2.resize`
  defaults to linear, which skips pixels when it shrinks. Score colour and
  coverage softly and cut a soft score once, at the decision, as `teardrop`
  does; never binarise a template or an observation before resampling or
  matching it. Fit position to sub-pixel precision where position decides.
  Never enlarge a frame to read it: enlargement adds no information.
  Nearest-neighbour belongs to display code alone.
- Never use stored-data bounds or a model's own output as independent evidence.
  Keep unresolved and no-contact opportunities so coverage is not biased.
- **READ THE REFUSAL REASON BEFORE CALLING ANYTHING A BLOCKER.** A count of
  refusals is a symptom; the cause is usually stored beside it. `lineup`'s
  refused slots read as *3 of 5 named*, a coverage fact; each slot's `reason`
  said PAIRWISE TIE, and twelve of 79 refusals were ties a constraint had
  already broken. Provenance can be perfect while attribution is
  wrong, and no citation check catches it.
- **CROSS-REFERENCE BEFORE TUNING.** When a detection is wrong, first ask which
  other channel already observes the event, and gate one on the other.
  Tuning a threshold, mask or morphology on the channel that produced the error
  is the second resort. The precedent is `ally_icons` scored against the
  roster: +0.99 phantom teammates per frame became -0.15 with no change to the
  detector. Agreement is consistency, not accuracy -- store the disagreements.
- Measure a known baseline before structural edits, then rerun the real command
  and confirm a known result. A parse check alone is not verification.
- Hold what you know about the system as uncertain beliefs, and update them
  on evidence. Before acting on an assumption about an owner, a
  detector or a mechanic, check it or state it with a falsifier. Spend effort
  where uncertainty is largest and a cheap experiment can resolve it,
  refining only where uncertainty exceeds the question's tolerance.
  Observations and the tools that produce them are uncertain too: a result
  that surprises may be a tool error, so check the instrument before revising
  the system belief. A failed prediction revises the belief; record it and carry
  it into the handoff.
- **Continue the prior; widen the search only on surprise.** Context predicts
  most of what comes next: the last frame's state, the match's lineup, the
  banner's type, the adjudicated belief the last run left. Start every reading
  and experiment from that prediction, check it cheaply, and widen only
  where the observation surprises it. A killfeed entry is followed where it
  was; a smoke is sought where the match's agents' abilities land; a
  portrait tile is placed from its banner type's anchor; an experiment
  revises the belief it tested rather than starting over. Store the
  surprise, never average it away. A surprise may also reopen the earlier
  verdict it contradicts, which reruns once with the new evidence; store the
  original, the revision and the surprise. A prior never checked is a hidden
  assumption: the portrait channel assumed an entry keeps its first slot, and
  lost every view taken after the stack rose. Audit a prior by a
  full search on opportunity-gated samples at a cadence fixed in advance,
  stored apart, until its efficacy is statistically significant; after that,
  widening on surprise suffices (player, 2026-09-30). A surprise-triggered
  search is no audit sample. Code that
  scores against a gallery or candidate set names the set its
  context allows (the match's agents, the side's five, the slot's predicted
  agent) and why; the full set is the surprise path and must be justified, as
  the lineup reader's 29 agents are before any lineup exists. A prior is
  evidence, weighed once: a result it shaped declares `rests_on`, so the
  prior is never counted again as an independent witness.
- **Ability mechanics are unique per ability** (player, 2026-09-26)
  [domain:abilities/ability-rules-are-unique]: the lifecycle, inputs, minimap
  drawing and screen overlay of one ability predict nothing about another.
  Record each from the player or an observation in `domain/abilities.toml`,
  never by analogy; the questions live in
  [`docs/ABILITY_MECHANICS_SHEET.md`](docs/ABILITY_MECHANICS_SHEET.md), and a
  census verifies an answer with a targeted demo, never discovers it.
- Before a perceptual experiment, state falsifiable predictions and log them in
  the store's `notes/predictions.jsonl`; inspect source images before measuring.
  On the first failed perceptual approach, build the tool that asks the player.
- Commit whenever a result is verified. `NOTES.md` and `BACKLOG.md` are
  bounded working documents, not logs: `NOTES.md` holds only the current
  handoff; `BACKLOG.md`, open work plus the five latest completed tasks.
  Rewrite them in place and move what they retire to a dated file under
  `docs/archive/`. `doctor` HANDOFF checks the limits. An open `BACKLOG.md`
  item carries an `Acceptance:` command and an `Evidence:` standard inside its
  paragraph, and HANDOFF reports items without them.
- Never put Claude session URLs in repository files or commit messages. Public
  files contain facts; attribution, quotes, and private domain notes stay out.

## Repository declarations

`doctor` checks each of these; `PROJECT_GUIDE.md`, "Repository declarations
and why they exist", argues for them.

- **Wire or decline.** A prototype named in `notes/predictions.jsonl` is either
  used by `reticle/` or carries `"wire": "no"` with a `"wire_reason"` (PROMOTE).
- **Domain facts** about VALORANT and its capture live in `domain/*.toml`, one
  table per fact with `claim`, `kind`, `known` and `since`; prose cites them
  with a bracketed `domain:` token instead of restating them. Read one with
  `reticle domain`. Pipeline accuracy is not a domain fact (DOMAIN).
- **Quoted numbers cite their run** with a bracketed `metric:` token naming
  series, session and value (QUOTED). The check compares only numbers that
  carry a token, so a bare measured number in a document passes silently:
  record the run and cite it.
- **Layers are declared** in `architecture.toml`. Place every new module; an
  upward import needs a blessed edge. `reticle/` never imports `prototypes/`,
  including by `sys.path` insert (LAYER).
- **Ownership is declared** in `ownership.toml`: one entry per question, naming
  the owner, what it produces and what it is `not_for`. The owner's docstring
  carries its `[owns:<id>]` token. Route with `reticle ownership <question>`
  (OWNERSHIP).
- **Ask the owner; never restate its rule.** Before writing code that decides
  anything, run `reticle ownership` for the question. If an owner exists, call
  it, even when its rule looks like three lines to copy. A restated rule
  compiles, passes its tests and drifts silently.
- **Every agent name is decided by `adjudication.identity`**, the
  aggregator over one arbiter per channel, per entity and side. Each
  channel pools its own readings and publishes `identity_claim`s through its
  arbiter; from another channel it takes only a candidate set, a window or a
  gate, never that channel's verdict on the same entity. Owners that bind a
  death, track, row or ability to a witness supply the entity key and ask the
  arbiter. A claim that rests on another entity's verdict declares
  `depends_on`; an observation a prior placed declares `rests_on`. An
  ownership entry whose output carries a name declares `names_agents = true`
  and defers to `agent-identity`. OWNERSHIP makes an undeclared name
  producer or an identity event built outside the arbiter an ERROR, and the
  event validator rejects such an event.
- **Documents are declared** in `documents.toml`. Register each document, with
  its kind, status and date, in the commit that creates it. A plan becomes
  `implemented`, naming `implemented_by`, or `superseded`, naming
  `superseded_by`, and then moves to `docs/archive/` with a date. Rules have
  one home, `AGENTS.md`, and command lists one, `docs/WORKING_MAP.md`; other
  files point to them (DOCS).

QUOTED skips `docs/archive/`; DOMAIN checks only citations there.

## Running

Always use the repository venv:

```powershell
.\.venv\Scripts\python.exe -m reticle <command>
```

At pickup, run `doctor` and inspect `status`.

## Guide routes

`PROJECT_GUIDE.md` keeps the former guidance verbatim. This file holds only
the eager index and global constraints; keep historical measurements out.
