---
name: labelling-pass
description: Build or run a tool that asks Grant for ground truth — a frame labeller, a candidate classifier, a mask painter. Use when a perceptual question resists derivation, or before any measurement that needs labels to be scored at all. Carries the control layout every labeller in this repo shares, the file format, and the lessons each one learned by getting it wrong.
---

# Asking Grant, instead of deriving it

## When to reach for this

**On the FIRST failure of a perceptual question, not the fifth.** On 2026-08-26
the minimap's searchable area was derived and re-derived five times — each
attempt measured, plausible and wrong — and Grant named the defect by eye in
seconds every time. `paint_map.py` settled it in one pass, and the rule it
produced transferred to a second map at 92.8% IoU. Every stage of this project
that works was preceded by a labelling pass.

The signal that you want this: you are about to write a third variant of a
threshold, or you have a measurement that is *true* but keeps disagreeing with
what a person sees.

The other trigger is a channel that **cannot be scored at all**. The colour-free
minimap detector produced 1300-3900 blobs a sweep with nothing in the store
saying which were real — no amount of cleverness fixes that, only labels.

## Before writing any code: ask for the class list

Grant knows what is drawn on the screen; the detector only knows what it found.
`label_dynamic.py` was launched six times in one session because ping, area
ability and spawn barrier each surfaced mid-run and needed a new key. Ask first:
*what things can actually appear here?* One question would have saved five
restarts, each costing him a detection wait.

Then decide the population you sample from, and check it is the one you mean.
That same pass drew uniformly over `active` spans — and `segment` calls the buy
phase active, so 38% of the questions were about an empty minimap.

## The control orthodoxy

Every labeller here shares these, and a new one must not invent its own:

    U            unsure — recorded, and kept OUT of scoring
    A            back one
    Q / ESC      save and quit
    right click  undo the last mark on this frame   (click-based tools)
    SPACE / D    save and advance                   (click-based tools)
    N            nothing here, and advance          (click-based tools)

Classes are **digit keys** when the question is "which of these is it"
(`label_icon_agent`, `label_dynamic`), and **modifier+click** when the question
is "mark every one of these you can see" (`label_minimap`, `label_enemies`).

Always include an **escape hatch class** — `7 = other` in `label_dynamic`.
`0 = nothing` is a *claim* that the thing is an artefact, and forcing a real
object into it poisons the negative class. The escape hatch is what caught spawn
barriers.

Fit the window on a 1080p screen. Ring the candidate in **every** panel.

## The file format

Append-only JSONL at `<store>/labels/<kind>/<session>.jsonl`, and **the last row
for a key wins** — the convention `minimap_portrait.load_agent_labels` reads. It
is what makes `A`-then-reanswer work, and what let two mislabelled barriers be
corrected after the fact by appending rather than editing.

Store **the answer, and enough to find the pixel again** — nothing else.
Features are recomputed, not stored. Host span and top-hat peak were invented
after 154 rows were already answered and applied to all of them for free,
because every row carried `(t_ms, x, y)`.

Also record `by` (who answered) and, for anything with a derived counterpart,
whether they were shown it (`compared_against_derived` in `paint_map`). An
independent mask is worth more than a corrected one, and the file has to say
which it is.

Make it **resumable**: load what is already answered, skip those candidates, and
make quitting partway safe.

## Never seed the file

Seeding `minimap_agent` with provisional rows made the labeller skip every
seeded icon as already done, and the number that came back was scoring my own
clustering against itself. `paint_map.py` starts blank for the same reason and
offers `m` to *flash* the derived mask on demand — comparison, not a starting
point, and the metadata records whether it was pressed.

## The tile is not the object

A 36 px crop of the minimap routinely holds a Cypher cam AND two overlapping X
marks AND a dropped spike AND ally portraits. Grant, reading a contact sheet
presented as one-object-per-tile. So ring the candidate in every panel and ask
about **the ringed thing**, never "what is in this tile".

## Tk mechanics that have already cost time

* `root.bind("bracketleft", ...)` binds a *sequence of eleven keypresses*. A
  named keysym needs angle brackets: `"<bracketleft>"`. A single character
  (`"q"`) is fine bare. This silently broke brush sizing and Grant painted a
  whole mask at one size.
* Re-encoding a full-resolution PNG on every mouse-motion event is too slow.
  Draw cheap immediate feedback on the canvas during the drag and recomposite
  once on `ButtonRelease`.
* A context panel that resizes 1080p to a tile's height is unreadable — Grant
  could pick out nothing but the scoreboard. Crop to what matters instead of
  fitting the whole frame.
* `PhotoImage` needs a reference kept, or the image is garbage-collected blank.

## While the pass is running

Do not restart the tool for an improvement that does not change the data being
produced. A missing class key is worth a restart; a blurry context panel is not,
mid-run.

Read the file as it fills — it is flushed per row. An interim analysis at 154 of
250 rows is what surfaced the host-span feature, and that changed what the rest
of the pass was worth.

## After the pass

Write the scoring as a **prototype, not a scratch script** — if a figure is
worth putting in a commit message it will be re-run. `dynamic_eval.py` is the
pattern: takes a session, recomputes features from the labels, prints the
operating points.

Then check the obvious trap: **does the ground truth come from the same
population as the thing being filtered?** *0 of 55 hand-marked icons have aspect
>= 2.0* was a true measurement that would have deleted Sage walls, ping ripples
and spawn barriers — because those 55 were enemy icons and the target was
ability glyphs.
