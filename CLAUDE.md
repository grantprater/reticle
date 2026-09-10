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

**The artifact is an EVENT STREAM CARRYING IDENTITY, and every observable event
in the game belongs in it.** Stated by the player, 2026-09-10:

    at time x    our ally BREACH was at (u, v)
    at x+1       our ally BREACH was at (u+du, v+dv)
    at x+2       our ally BREACH used their C at (n, m), orientation (r, t)

**Identity is the primary means by which rules of movement and existence can be
verified**, which is why it outranks everything else queued. Without a named
entity there is nothing for a speed limit, a continuity rule, a teleport, or
the origin-event invariants to be checked against -- a position with no identity
cannot contradict anything. Only with the stream in this shape does analysis on
it become possible, and analysis is downstream of it, never a substitute.

The visually checkable annotated match -- players, abilities, viewcones, pings
and other icons as they evolve through a VOD -- is the CHECK on that stream, not
a separate goal. Prediction, logging and coaching are downstream of observations.
When a perceptual question cannot be derived, ask the player and record the first
failure, not a guessed answer.

## How to write

Strunk, and it governs replies, docstrings, commit messages and `NOTES.md`
alike:

- Omit needless words.
- Use the active voice.
- Put statements in positive form.
- Use concrete language.

The active voice is the load-bearing one here. "The geometry rebuilt under me"
hid an error that "I rebuilt the geometry while my own experiment was reading
it" states plainly, and the player had to ask what the sentence meant.

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
  file that still restates one. `NOTES.md` and `BACKLOG.md` are exempt: they are
  append-only records of what was known on a date. Read one with
  `reticle domain [DOMAIN] [--id ID]`. Pipeline accuracy is NOT a domain fact --
  outcomes belong in `notes/predictions.jsonl`. Facts carry a dependency graph
  too: a GIVEN fact (`player`, `observed`) rests on nothing and may not declare
  `depends_on`, an `inferred` one must name what it rests on, a `measured` one
  must name a `source`, and the graph must be acyclic. That is what stops a
  guess being laundered into a given.
- **A NUMBER QUOTED IN PROSE CITES THE RUN THAT PRODUCED IT.** The form is a
  bracketed `metric:` token carrying the series, the session and the VALUE, and
  `doctor`'s QUOTED check compares it to the latest `pass` row. A citation to a
  series with no recorded run is an ERROR; a quoted value that no longer matches
  is a finding naming the file and both numbers, because the honest fix is
  sometimes the prose and sometimes the number. This existed because `metrics`
  stored 132 runs and nothing linked a single line of prose to any of them, so a
  figure could be quoted, the code could move, and the prose would stay. Read
  with `reticle/quoted.py`; `NOTES.md` and `BACKLOG.md` are exempt as
  append-only history.
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
