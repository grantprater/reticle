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
