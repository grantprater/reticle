# Reticle

Vision-based mechanical analysis pipeline for Valorant. The complete project
guide, including design rationale, measured findings, open defects, and
historical conventions, is [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md). This file is
the single root guidance for every agent; `CLAUDE.md` imports it.

## Start here

Use [`docs/WORKING_MAP.md`](docs/WORKING_MAP.md) for task routing. Read
`NOTES.md` for the single current handoff, then the selected `BACKLOG.md` task
and its contract in `docs/tasks.json`. Read the relevant section of
`PROJECT_GUIDE.md` before changing a subsystem. Minimap and prototype work
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

The active voice is the load-bearing one. "The geometry rebuilt under me" hid
an error that "I rebuilt the geometry while my own experiment was reading it"
states plainly, and the player had to ask what the sentence meant.

## Global constraints

- Stage 02 is deterministic; no model. Threshold, geometry, normalization,
  and mined templates are the baseline.
- Unknown, refusal, missing widget, stale input, and terminal state stay
  distinguishable; an unread value is `null` with a reason, never a guess.
- Keep raw observations separate from adjudication and later lifecycle events.
  Stored timestamps are observation times, and source evidence must precede
  promotion of an inference.
- Every independent detector/table has its own version stamp and provenance.
  Recomputable rules use stored data and must not decode video; stale cached
  geometry must be rebuilt before trusting derived measurements.
- Raw media is never copied. New readers join shared decode passes; gate dense
  sampling on opportunity rather than outcome. Never silently overwrite evidence.
- The HUD and minimap are semi-transparent over the void. Search inside the
  opaque structure; fit a shape rather than repairing it with a closing radius;
  never seed label files. Invoke the `labelling-pass` skill before labelling.
- **SESSION PIXELS DO NOT DEFINE THE MAP.** A capture may determine only the
  minimap widget's dimensions and placement. Base-map pixels, floor masks,
  lighting references, detector backgrounds, and all other static map values
  come exclusively from baked geometry keyed by `(map, profile)`. Never add a
  per-session static-map cache or capture median to a reader/prototype; `doctor`
  enforces this. The only exceptions are the geometry builder itself and
  `clip_preflight`, whose capture median is restricted to size/placement/orientation.
- Never use stored-data bounds or a model's own output as independent evidence.
  Keep unresolved and no-contact opportunities so coverage is not biased.
- **READ THE REFUSAL REASON BEFORE CALLING ANYTHING A BLOCKER.** A count of
  refusals is a symptom; the cause is usually stored beside it. Counting
  `lineup`'s refused slots gave *3 of 5 named*, which read as a coverage fact;
  each slot's `reason` said PAIRWISE TIE, and twelve of 79 refusals were ties a
  constraint had already broken. Provenance can be perfect while attribution is
  wrong, and no citation check catches it.
- **CROSS-REFERENCE BEFORE TUNING.** When a detection is wrong, first ask what
  other channel already observes the same event, and gate one on the other.
  Tuning a threshold, mask or morphology on the channel that produced the error
  is the second resort. The precedent is `ally_icons` scored against the
  roster: +0.99 phantom teammates per frame became -0.15 with no change to the
  detector. Agreement is consistency, not accuracy -- store the disagreements.
- Measure a known baseline before structural edits, then rerun the real command
  and confirm a known result. A parse check alone is not verification.
- Treat what you know about the system as beliefs held with uncertainty, and
  update them on evidence. Before acting on an assumption about an owner, a
  detector or a mechanic, check it or state it with a falsifier. Spend effort
  where uncertainty is largest and a cheap experiment can resolve it, as the
  pipeline refines where uncertainty exceeds a question's tolerance. Observations
  are uncertain too, and so are the tools that produce them: a result that
  surprises may be a tool error, so check the instrument before revising the
  system belief. A failed prediction revises the belief; record it and carry
  it into the handoff.
- Before a perceptual experiment, state falsifiable predictions and log them in
  the store's `notes/predictions.jsonl`; inspect source images before measuring.
  On the first failed perceptual approach, build the tool that asks the player.
- Commit whenever a result is verified. `NOTES.md` and `BACKLOG.md` are
  bounded working documents, not logs: `NOTES.md` holds only the current
  handoff, and `BACKLOG.md` holds open work plus the five latest completed
  tasks. Rewrite them in place and move what they retire to a dated file under
  `docs/archive/`. `doctor` HANDOFF checks the limits.
- Never put Claude session URLs in repository files or commit messages. Public
  files contain facts; attribution, quotes, and private domain notes stay out.

## Repository declarations

`doctor` checks each of these. The arguments for them are in
`PROJECT_GUIDE.md`, "Repository declarations and why they exist".

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
- **Every agent name is decided by `adjudication.identity`**, per entity and
  per side. Readers publish `identity_claim`s. Owners that bind a death, track,
  row or ability to a witness supply the entity key and ask the arbiter. A
  claim that rests on another entity's verdict declares `depends_on`. An
  ownership entry whose output carries a name declares `names_agents = true`
  and defers to `agent-identity`. OWNERSHIP makes an undeclared name producer,
  or an identity event built outside the arbiter, an ERROR, and the event
  validator rejects the event.

Only the dated files under `docs/archive/` are exempt from DOMAIN and QUOTED.
`NOTES.md` and `BACKLOG.md` are checked like any other document.

## Running

Always use the repository venv:

```powershell
.\.venv\Scripts\python.exe -m reticle <command>
```

At pickup, run `doctor` and inspect `status`; use the focused commands and
tests in [`docs/WORKING_MAP.md`](docs/WORKING_MAP.md). Read task-specific
detail from [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md), then the owning module's
docstring and any applicable prototype guide.

## Guide routes

`PROJECT_GUIDE.md` retains the former full guidance verbatim. Its major routes
are: detector/domain detail, running and pipeline status, north star and
measurement rationale, open defects, pre-ingest checklist, reliability model,
load-bearing conventions, and repository declarations. This file is
intentionally only the eager index and global constraints; do not duplicate
historical measurements here.
