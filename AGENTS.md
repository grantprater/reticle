# Reticle

Vision-based mechanical analysis pipeline for Valorant. The complete project
guide, including design rationale, measured findings, open defects, and
historical conventions, is [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md).

## Start here

Use [`docs/WORKING_MAP.md`](docs/WORKING_MAP.md) for task routing. Read
`NOTES.md` for the live handoff, the relevant `BACKLOG.md` heading, and the
relevant section of `PROJECT_GUIDE.md` before changing a subsystem. Minimap
and prototype work also requires `prototypes/CLAUDE.md`; domain attribution
and private quotes remain in `~/reticle-notes/`, outside this public repo.

## Acceptance north star

The entity channel must produce a visually checkable annotated match: players,
abilities, viewcones, pings, and other icons as they evolve through a VOD.
Prediction/logging and coaching are downstream of observations. When a
perceptual question cannot be derived, ask the player and record the first
failure, not a guessed answer.

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
- Never use stored-data bounds or a model's own output as independent evidence.
  Keep unresolved and no-contact opportunities so coverage is not biased.
- **CROSS-REFERENCE BEFORE TUNING.** When a detection is wrong, first ask what
  other channel already observes the same event, and gate one on the other.
  Tuning a threshold, mask or morphology on the channel that produced the error
  is the second resort, not the first. An ally icon with no lit pixels beside
  it is not an ally; a bearing that disagrees with the light beside the icon is
  the flipped one. The precedent is `ally_icons` scored against the roster:
  +0.99 phantom teammates per frame became -0.15 with no change to the
  detector. Agreement is consistency, not accuracy -- store the disagreements.
- Measure a known baseline before structural edits, then rerun the real command
  and confirm a known result. A parse check alone is not verification.
- Before a perceptual experiment, state falsifiable predictions and log them in
  the store's `notes/predictions.jsonl`; inspect source images before measuring.
  On the first failed perceptual approach, build the tool that asks the player.
- Commit whenever a result is verified, and keep the `Picking up` section of
  `NOTES.md` short and current.
- Never put Claude session URLs in repository files or commit messages. Public
  files contain facts; attribution, quotes, and private domain notes stay out.

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
and load-bearing conventions. The root file is intentionally only the eager
index and global constraints; do not duplicate historical measurements here.
