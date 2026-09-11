# The ownership index

Who is allowed to decide a question, declared in [`ownership.toml`](../ownership.toml)
and checked by [`reticle/ownership.py`](../reticle/ownership.py).

    .\.venv\Scripts\python.exe -m reticle ownership which agent died
    .\.venv\Scripts\python.exe -m reticle ownership --module track
    .\.venv\Scripts\python.exe -m reticle ownership --check

## The problem it solves

The word *identity* means seven things here: an agent in a roster slot, an icon
being the local player, an observation continuing a track, components belonging
to one physical ability, an ability having an owner, a killfeed entry naming a
victim, and a media file being one session. The modules are named after those
words, so selecting a dependency by name selects the wrong one. `roster` and
`lineup` both sound like identity; `minimap.pick_self` and `lineup`'s player
vote are both called *self*; `minimap_lifecycle` and `round_lifetimes` both
speak lifecycle; `track` sounds like the answer to all of it and owns none of
it.

Two faults have already been paid for. The HUD death signal dims a PACKED
living-slot index rather than a canonical player slot, and read as identity it
named the wrong victim in both rounds it was tested on. `minimap_lifecycle`
restated `track`'s continuation ceiling and the two drifted -- 2.2 px against
4.8 at 60 Hz -- so it quarantined appearances the tracker had already
associated.

## What an entry carries

`question` is the thing a developer arrives with; the module is the destination,
not the organizing idea. `owner`, `role` and `produces` say who answers it and
with which code. **`not_for` is the field to read second**: the negative
boundary is what stops a module being picked because its name matched, and every
one of them is a mistake this repo has made or nearly made.

`status` is `shipped`, `partial`, `transitional` -- wired but still reaching
`prototypes/`, and owing an `exit` -- or `unowned`. `defers_to` names an entry
whose rule this owner consumes rather than re-derives. `consumers` and
`stored_consumers` distinguish an import route from a stored-data one.

## Why a registry rather than a document

The first proposal was a hand-written `docs/IDENTITY_INDEX.md` restating each
module's boundary in prose, with the machine-readable registry as a second phase
and the checks as a third. Three things argued against that order:

1. **The restatement is the drift.** `domain/*.toml` exists because the minimap
   vision rule sat in five files and each copy was free to move. Sixty-three
   module boundaries restated in prose is the same tangle in a new file, and the
   owners' own docstrings already carry the argument better than a summary of it
   would. So prose CITES an entry with an `[owns:<id>]` token instead.
2. **An unchecked declaration is satisfied by declaring everything.**
   `architecture.toml` says so in its own header, and reports stale
   declarations for that reason. A phase-one index with no checker would have
   been correct on the day it was written and unfalsifiable afterwards.
3. **The pass missed what a check would have caught.** The module-by-module
   classification covered all 63 modules and did not notice that
   `reticle/adjudication/` sat in no layer at all: `architecture.py` globbed
   `reticle/*.py`, so four modules were unplaced and `adjudication.ability`
   imported `ability_timeline` -- an eager edge up into `entities` -- with
   nothing to report it. Reading finds what it looks for; a check finds what
   nobody looked at.

## What the checks are

`doctor`'s OWNERSHIP check, at the same bar as every other check in that file --
a fault that has actually happened, or a declaration that can go stale in
silence:

- an entry naming a module that is gone, or a `produces` name it no longer
  defines;
- an owner that does not claim its own entry with `[owns:<id>]`, or a module
  claiming one it does not own;
- a module owning no entry and not declared infrastructure -- so a new module
  cannot arrive unclassified;
- a `defers_to` whose import no longer exists, which is the drifted-law fault
  made mechanical;
- an owner reaching `prototypes/` without `transitional` status and an `exit`,
  and a `transitional` entry whose promotion has quietly happened;
- a consumer that no longer imports the owner it is declared against.

An import PROHIBITION is deliberately absent. `lineup` imports `roster`
legitimately and the fault was in the READING -- a slot index used as a name --
so a forbidden-edge list would catch nothing and look like it was working.

## The gaps are declared too

Five questions have `status = "unowned"`, and `doctor` prints them on every run:

    agent-identity      which named agent an icon, track or ability is
    death-victim        which agent died at a killfeed time, and where
    ability-owner       which agent cast an ability
    ability-detection   where an ability entity is in the frame
    fact-subject        what a domain fact is about

These are the product. `agent-identity` blocks the other three, and its own
blocker is lineup coverage rather than perception. Naming them here keeps them
in front of the next session instead of in a paragraph of `NOTES.md`.

## Open questions

- Should `subject` in `domain/*.toml` reuse the agent/ability vocabulary, or
  stay broader?
- When `agent-identity` gets an owner, does it become a new module or does
  `reconciliation` narrow into it? The entry forbids `reconciliation` growing
  into a universal adjudicator, but does not yet name the replacement.
- `ability_phases.ally_deaths` is a cross-channel read living in a command
  adapter. `BACKLOG.md` carries it.
