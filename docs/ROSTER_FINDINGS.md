# Roster and event-timing findings — 2026-09-07

These are localized source inspections, not a corpus accuracy estimate.
Reproduce counts with `reticle audit`; source images are kept in the private
store/workspace rather than committed footage. No detector thresholds changed.

## Confirmed roster undercount: 587c15b07779, 1483.0 seconds

Four frames at 1482.0, 1483.0, 1483.5 and 1484.0 seconds show the same two
friendly portraits and one enemy portrait. The friendly reader answers 2, 1,
2, 2. There is no visible birth/revive behind the reported 1 -> 2 transition.
The local contact sheet is `fixtures/reconciliation/count_increase.png`.

The measured ally slot-detail vectors (left to right; occupied slots pack right):

| Time (s) | Slot 1 | Slot 2 | Slot 3 | Slot 4 | Slot 5 | Read | Visible |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1482.0 | 2.3254 | 6.5354 | 8.1501 | 23.5602 | 35.9212 | 2 | 2 |
| 1483.0 | 7.9196 | 9.6660 | 6.7256 | 22.7143 | 37.4154 | 1 | 2 |
| 1483.5 | 3.7520 | 3.2665 | 3.2025 | 24.2960 | 35.4007 | 2 | 2 |
| 1484.0 | 3.2609 | 4.6095 | 2.9847 | 23.5013 | 36.1178 | 2 | 2 |

Mechanism in `roster.alive_from_detail`: it maximizes an absolute detail gap.
At 1483.0 the incorrect one-player split scores 37.4154 - 22.7143 = 14.7011;
the correct two-player split scores 22.7143 - 9.6660 = 13.0483. Both portraits
are comfortably above DETAIL_FLOOR=9. Raising/lowering that floor does not
resolve the actual ambiguity. Background detail in the empty slots changes
which gap wins. The algorithm mistakes within-portrait contrast variation for
the occupied/empty boundary.

Next experiment: compare normalized contrast and portrait-specific structural
evidence on the existing independently inspected frames, including all-alive,
one-survivor, real zero and absent HUD. Do not simply count values above the
floor: an empty slot here already exceeds it. Do not impose monotonic counts:
real revives must remain possible. Hold this sequence out of subsequent tuning
if it is to serve as evaluation evidence.

## Confirmed delayed killfeed observation: c40d950031bb, 700.5–703.5 seconds

Stored roster changes from 5v2 to 4v2 at 700.5s. Stored `kf_entry_mask` remains
zero through 702.5s, although the source frame at 702s visibly contains the
player's death entry. At 703s it reports mask 2, then mask 3 at 703.5s; entry
tracks begin at 703.0 and 703.5s. The contact sheet is
`fixtures/reconciliation/roster_timing.png`.

The audit's adjacent windows [690.5,700.5] and [700.5,710.5] have residuals -1
and +1. Their union agrees. This supports delayed killfeed observation rather
than a roster-count correction. First detection is not event occurrence time.
Do not shift all events by a fixed offset: the delay is detector/window specific.

## Round-boundary guard rejected

Requiring two nearby identical score reads removes two final score transitions
and shifts four others later in this corpus (369 -> 367). Those final outcomes
have insufficient repeat observations, not demonstrated wrong scores. The
proposal stays in the audit; production round inference is unchanged. Next
reconcile score steps with clock/phase and scoreboard evidence, preserving final
rounds and explicit uncertainty.

## Remaining inspection queue

For 587c15b07779, the audit-v0.1 windows with count disagreements are:
207.5–217.5, 314.5–324.5, 773–783, 1009.5–1019.5, 1375–1385 and 1464–1474s.
They remain unresolved; no claim that all are roster errors. The 1474–1484s
count-increase window is localized above. Audit-v0.2 also refuses missing HUD
coverage, so rerun it before treating any interval as supported agreement.

---

# 2026-09-07, later: the evidence is stored, and two more defects

## The table now holds the DETAIL VECTORS, so this page's experiment is free

`l1/roster` stored only the adjudicated count, so "try a different split rule"
meant re-reading the video of a session already read. `roster-0.2.0` stores
`detail_ally` / `detail_enemy` -- the five floats per team the count is decided
from -- and `ROSTER_SPLIT_VERSION` stamps the rule separately, because a rule
change is now a re-derivation over stored data rather than a decode.
`Store.has_roster` deliberately does not consult it.

Both roster sessions were re-scanned. The counts are unchanged: 3730 rows and
8 zero-reads on `587c15b07779`, 1945 rows and 187 on `c40d950031bb`, and
`prototypes/roster_split_eval.py` reproduces every stored count from the stored
detail exactly (`cells moved 0` for the shipped rule on both).

## The ratio split rule: PRINCIPLED, and NOT ESTABLISHED by this corpus

The shipped rule maximises `min(occupied) - max(empty)`. The compositing
mechanism `roster.py` documents says the boundary should be a RATIO: the bar is
a tinted semi-transparent panel, so scenery behind it arrives dimmed and blurred
by roughly constant transmittance while the portrait is crisp art on top, and
both populations scale with how detailed the scene behind the bar is.

Measured over 11,306 team-cell reads on two sessions, the two rules differ on
**six**:

| | absolute | ratio |
|---|---|---|
| `587c15b07779` cells moved | -- | 1 (the held-out 1483.0s frame) |
| `c40d950031bb` cells moved | -- | 5 (enemy, 962-965s) |
| audit agree / disagree / unreadable, 587 | 115 / 6 / 9 | 116 / 6 / 9 |
| audit, c40d | 58 / 2 / 0 | 58 / 2 / 0 |
| refusal rate, excursions, over-5 | -- | identical |

**The only audit movement is the held-out window itself**, so it is not
independent confirmation. The mechanism argues for the ratio; the corpus cannot
distinguish the two rules. Shipping it is a judgement about mechanism, not a
result — and it is cheap and safe either way, since it moves six cells.

Two variants were tried and are wrong, recorded so they are not retried:

* **scoring `n = 0` on the ratio scale** (`DETAIL_FLOOR / max(detail)`) makes the
  rule never refuse. Coverage went to 100% by converting 519 honest refusals
  into confident zeros -- the known undrawn defect made louder, wearing the
  costume of better coverage;
* **a 0.0 sentinel** admits splits scoring 0.42, i.e. the dimmest OCCUPIED slot
  dimmer than the brightest EMPTY one. Eleven rows on `587c15b07779` read
  `[7.34 31.09 7.32 37.00 13.04]` -- bright slots that are not a contiguous run
  anchored at the inner edge, so the packing premise fails and refusing is
  right. The ratio analogue of "positive gap" is **1.0**.

`opens-at-5` was tried as a discriminator and is unusable here: `round_bounds`
starts a round at a score increment, which lands in the buy phase where the bar
is dim, so it measures round-boundary error rather than the split rule.

## CONFIRMED by rendering: a WIPED team reads as `None`, not `0`

`587c15b07779`, 154-176s, enemy bar, rendered at 5x:

| Time | enemy detail | read | visible |
|---:|---|---:|---|
| 154.0 | `21.45 2.40 3.32 2.81 2.29` | 1 | one portrait, scenery through four empty slots |
| 158.0 | ` 2.20 2.03 2.04 2.17 2.58` | **None** | **no portraits; bar drawn, scenery visible** |
| 162.0 | ` 2.15 2.15 2.15 2.15 2.15` | None | flat panel, nothing drawn |
| 176.0 | `30.03 32.22 31.32 29.46 20.31` | 5 | five portraits, new round |

At 158.0s all five enemies are dead and the bar is drawn. The correct answer is
**0** and the read refuses. `DETAIL_FLOOR`'s stated purpose is to resolve the
all-dead case and it does not: a drawn-but-empty bar sits at 2-8, which vetoes
every occupied split, and `n = 0` then loses to the `-1.0` sentinel unless the
bar is near-black (`max < 1.0`). Only a bar with nothing behind it reaches 0.

**This is the documented `(0,0)` defect from the opposite side, and it costs the
audit its most informative windows** -- a wipe is a round outcome, and the
roster refuses exactly there. It is pinned by
`test_undrawn_and_wiped_rosters_are_not_distinguished`.

**Not patched: it is a decision, not a task.** `roster.py` already records that
returning `None` at the floor contradicts why the floor exists. The two states
are `drawn and empty` (answer 0) and `not drawn` (refuse), and the reader must
separate them before either answer is safe.

From 164.0s to 174.0s the ALLY detail vector is byte-identical across eleven
samples. A frozen frame is a static post-round screen, and repeated identical
vectors detect it with no threshold at all -- worth knowing before anyone builds
a phase gate.

## FAILED: cross-slot spread does not separate undrawn from wiped

The obvious mechanism -- live scenery behind a transparent bar varies slot to
slot, a panel with nothing behind it does not -- is visually true on the four
frames above and does **not** survive the corpus. Relative spread
`(max-min)/mean` over all dim rows runs smoothly from 0.00 to 1.7 (587) and 4.0
(c40d) with no gap anywhere, against a bright-row median of 0.26-0.52. It also
breaks by construction on near-black bars, where the normalizer collapses and
the ratio inflates. **A different separator is needed; do not retry this one.**

## CONFIRMED but BOUNDED: a fading bar reads as a confident partial count

`c40d950031bb`, 960-967s (the capture ends at 972s). All five enemy portraits
are visible and dimmed by a wipe transition, brighter on the left:

| Time | enemy detail | absolute | ratio | visible |
|---:|---|---:|---:|---|
| 962.0 | `12.61 9.17 5.85 5.39 5.99` | 1 | 2 | **5** |
| 965.0 | `12.39 9.01 5.56 5.93 6.12` | 1 | 2 | **5** |

Both rules are wrong, and a non-uniform fade is not answerable by any split over
per-slot detail -- the reader must refuse. **Bounded, and this is the reassuring
half:** rows whose brightest slot falls between `DETAIL_FLOOR` and `2x` it are
0.0-0.1% of in-round rows on both sessions, so the confidently-wrong population
is essentially all outside rounds. The refusal band (nothing clears the floor)
is 2.7-9.6% of in-round rows and is dominated by the wipe case above.

---

# 2026-09-07, shipped: the ratio split and the HUD gate

Both decided by the player after the measurements above. `roster-split-0.2.0`.

**The split is a ratio** (`reticle.roster.alive_from_detail`), shipped on the
mechanism rather than on the corpus, which could not separate the two rules.
Cheap and reversible: its own version stamp, and the stored detail re-derives
either answer. `prototypes/roster_split_eval.py` now compares the shipped rule
against the one it replaced.

**An empty bar is resolved by the SCORELINE, not by how dark it is.** If
`l1/hud` read a score at that instant the HUD is drawn, so a dim roster bar
means the team is WIPED and the answer is 0; with no score the answer is
nothing. `roster.resolve()` does the as-of join and never borrows a future row.
It lives at adjudication time rather than in `RosterReader` because
`scan --only roster` runs no HUD reader, so the stored columns are the ungated
answer by construction and `audit` / `coach` both call `resolve()`.

## What it moved, measured

| `587c15b07779` audit | before | after |
|---|---:|---:|
| agree | 115 | **116** |
| unreadable roster | 9 | **7** |
| disagreement | 6 | 6 |
| count increase | 1 | 1 |
| ambiguous `(0,0)` rows | 8 | **0** |

`c40d950031bb` is unchanged at 58 / 2 / 1, with its `(0,0)` rows falling 187 to
5. `coach` is unchanged at 26 eligible rounds and still abstains -- terminal
states are excluded from eligibility either way, so this buys audit coverage
rather than model coverage, exactly as expected.

**The remaining count increase MOVED, and that is the result worth reading.** It
was 1474-1484s -- the confirmed split defect, now fixed. It is now
**167.5-177.5s**: the enemy bar reads 0 from 158s (wiped, score 1->2) and 5 at
176s, a real 0->5 step that only looks like an increase because `round_bounds`
puts the boundary at the score increment rather than at the round's actual end.
The audit has stopped flagging a roster error and started flagging a
round-boundary error, which is the instrument doing its job.

## Two metrics in the eval are CONFOUNDED and must not be read as rule quality

`opens-at-5` falls from 21/38 to 4/38 and `increases` rises from 20 to 39. Both
are `round_bounds` showing through: a derived round starts at the score
increment, which is the instant the PREVIOUS round ended, usually with a wipe --
so the correct count there is 0, and the gate now ANSWERS those rows where the
old rule refused and was silently skipped. Verified by hand on `587c15b07779` at
255.0s (allies all dim ~3.0, four enemies crisp at 21-30, score stepping 2-0 to
2-1) and at 1315.5s (same shape, 10-4 to 10-5). Both are genuine wipes.

**The corollary is a free instrument for the round-boundary work:** the roster's
transition from a wiped team to a full one is an independent read on where a
round really starts, and it needs no decode.

## Regression check: the numbers on record come back

`prototypes/roster_alive.py --stored`, the label-free cross-channel check, run
against the re-scanned tables:

| | on record | now |
|---|---|---|
| `587c15b07779` probes agreeing | 100/113 (88%) | **100/113 (88%)** |
| `587c15b07779` slot-reads answered | 233/240 | **233/240** |
| `c40d950031bb` probes agreeing | 43/48 | **43/45** |
| starts-at-5, both sessions | -- | 40/40 and 14/14 |
| increases / over-five, both | -- | 0 / 0 |

**The one number that moved is the c40d DENOMINATOR, and it moved the right
way**: same 43 agreements, three fewer probes, because the reader now refuses
where it previously guessed. `roster.py` already recorded that this session's
five misses were all the undrawn defect, and this is that population leaving the
sample rather than being answered wrongly. Nothing became less accurate.

---

# 2026-09-07, later still: every unresolved window, diagnosed by rendering

All seven unresolved windows on `587c15b07779` and all three on
`c40d950031bb` were inspected by rendering the killfeed ROI at 1.3-1.6x
INTER_NEAREST. **NOT ONE IS A ROSTER ERROR.** That is the headline: it
vindicates the reader shipped earlier today and moves the work to the killfeed.

| window | res | what the pixels show |
|---|---:|---|
| 207.5-217.5 | -1 | `Vyse [sniper] (+) Phoenix` at 209.5s -- **Run It Back mark** |
| 314.5-324.5 | +1 | six deaths, six entries; the sixth (`Fade -> Omen`) appears only at ~325.0s, after the window closed |
| 773.0-783.0 | +1 | `Phoenix (x) Fade` visible at 781.0s, **swallowed by the track that began at 775.5s** (19 samples) |
| 949.5-959.5 | -1 | `Omen [sniper] (+) Me` at 950.0s -- **Run It Back mark**, on the local player |
| 1009.5-1019.5 | -1 | **two** entries on screen at 1018.0s, three tracks reported; the extra has the minimum 2 samples |
| 1375.0-1385.0 | -1 | `Fade [rifle] (+) Phoenix` at 1377.5s -- **Run It Back mark** |
| 1464.0-1474.0 | -1 | no killfeed at all from 1472.0s: warm wall and teal scenery. Two isolated detections 1.5s apart, no divider on either, linked into one counted track |
| c40d 690.5/700.5 | +1/-1 | the known adjacent pair; onset lag, cancels over the union |
| c40d 494.0-504.0 | -1 | an onset landing exactly on the window boundary |

**Three of the seven are the documented Run It Back divergence.** CLAUDE.md
already records that Phoenix and Kayo grant the second life BEFORE the fact, so
the death is a real killfeed entry that produces no roster change by design.
The local player is Phoenix on this session (`Omen (+) Me` at 951.0s), which is
why three appear in one match. The audit does not model it, so it reports them
as detector disagreements.

**This makes the revive-mark reader the highest-value killfeed addition, and it
is now evidenced rather than argued.** CLAUDE.md lists it as candidate next step
#2 for the K/D divergences; it additionally resolves 3 of the 7 unresolved audit
windows on the only session with a full roster. The marks all sit in one place
-- right of the weapon icon -- and detecting *a* badge needs no icon list.

## Two tracker defects, each confirmed once, now reported by `reticle audit`

`audit-0.3.0` adds a `killfeed` section from stored L1 and no decode:

    no_divider   a COUNTED track no observation of which ever showed a name
                 either side of the weapon icon.  61 of 2859 corpus-wide.
    over_long    a counted track lasting far beyond the entry lifetime.
                 83 corpus-wide, 6 of them explained by a frozen frame.

**The entry lifetime is a hard constant and that is what makes `over_long`
readable at all**: median 10 samples and 4.5s on every one of 18 sessions,
pooled p95 13. Against it, 154 counted tracks exceed 12 samples and 83 exceed
16, to a maximum of 38.

**CLAUDE.md's claim that long tracks are gone is FALSE.** It reads *"the divider
ended that and there are now none anywhere, so one appearing again is a signal
that something upstream broke"*. There are 154.

## FAILED: `over_long` is not a merge detector

The hypothesis was that every over-long track is two entries merged. It was
formed on `587c15b07779` 775.5s, where it is CORRECT -- 19 samples over 10s,
swallowing a visible `Phoenix -> Fade` entry.

**The first independent test refuted it.** The corpus maximum -- `59c70f1ef720`,
2197.0-2215.5s, 38 samples -- is a SINGLE genuine entry (`Jett -> Ryzen PK` and
`Jett -> JustLifin`, unchanged across five rendered frames 18.5s apart) on a
FROZEN frame. Every stored HUD column there is identical from 2198.0 to 2214.0s,
`confidence` included. Generalising from the one confirmed case would have
turned 154 tracks into a fabricated defect rate.

So the two populations overlap and are separated by `frozen_runs`, which is why
`inside_frozen_frame` exists. 77 of the 83 over-long tracks are not explained by
a freeze; that is a CANDIDATE population, not a defect rate -- one is confirmed.

## FAILED: frozen runs do not localize round boundaries

A frozen frame is detectable from stored L1 with no threshold: every column
equal sample to sample, `confidence` being the load-bearing one since it is a
continuous float. 1240 runs and 4645s across the corpus at a 3-sample floor;
161 runs at a 5s floor.

They are **not** a round-boundary instrument, which was the reason for measuring
them. Only **8% (30/369)** of derived round starts fall inside a run of >= 5s,
and the median run sits **25s** from the nearest start (p25 8.5s, p75 71s).
What they do say is that **2.8% of derived in-round time is a frame that never
changed** -- an eligibility question for coaching states, not a timing one.

## FAILED: the killfeed is not systematically late

`ROSTER_FINDINGS` records one late onset (`c40d950031bb`, roster drop 700.5s,
entry 703.0s) and already warned against shifting all events by a fixed offset.
Measured properly over both roster sessions -- every in-round roster drop
matched to its nearest killfeed onset, one lag per death in a multi-death step:

    n = 182   median +0.00s   mean +0.05s   p90 +0.50s   p95 +0.50s   max +3.00s
    within the audit's +/-1.0s ENTRY_ALIGNMENT_MS:  178/182 (98%)

So the 2.5s case is a 2% tail, not an offset, and **`ENTRY_ALIGNMENT_MS` should
not be widened** -- doing so would buy the two boundary-straddling windows and
loosen every other comparison for nothing.

---

# 2026-09-07: the round-boundary defect, quantified on all 18 sessions

`round_bounds` locates a round start at the SCORE INCREMENT. Measured against
two independent channels, that instant is **~6 seconds before the previous
round's clock expires**, and the new round does not begin for another ~7s.

## Channel 1: the clock. 281 rounds, all 18 sessions, no roster needed

The clock read at each derived round start:

    pooled n=281   median 6.0s   p10 5.0   p25 6.0   p75 6.0   p90 6.0
    median is 6.0s on 17 of the 18 sessions, and 5.0s on the eighteenth

    under 15s -- the PREVIOUS round's dying seconds:  267/281  (95%)
    25-31s    -- an actual buy phase:                   7/281  ( 2%)

A distribution that tight across eighteen independently recorded sessions is a
structural offset, not noise. **A round does not begin with six seconds on the
clock.** The score updates the moment the round is DECIDED -- the wipe -- rather
than when the clock runs out, and `round_bounds` inherits that instant.

## Channel 2: the roster. 26 rounds on the two sessions that have one

    rounds whose end is marked by a wipe            26/26 (100%)
    wipe onset  -  derived round END      median  +0.0s  (p10 -7.0, p90 +5.0)
    both teams back to 5  -  derived END  median  +7.0s  (p10 +4.5, p90 +7.5)
    clock when both teams are back to 5   median  28.0s  (p90 29.0)

**The round END is well placed; it is the START that is wrong**, and because
`round_bounds` makes rounds contiguous these are the same instant. The roster
returns to 5 at clock ~28-30s, which is the top of Valorant's 30s buy phase.

So the first ~7 seconds of every derived round is post-round time, and the two
channels agree on it from different pixels: clock 6.0s at the derived start,
clock 28.0s and both rosters full 7.0s later.

## What this explains, that was previously separate

* **`opens-at-5` collapsing to 4/38** when the empty-bar gate shipped. At the
  derived round start the previous round's wipe is still on screen, so 0 is the
  correct count and the old rule was refusing it;
* **the count-increase flag at 167.5-177.5s** -- a real 0 -> 5 step across the
  true boundary, reported as an anomaly inside one derived round;
* **111 of 543 coaching events flagged near an uncertain boundary**, the largest
  quality number the first coaching milestone produced.

## The fix is available and it is NOT taken here

The round start should be located at the **clock RESET** -- the clock jumping up
to ~30s -- rather than at the score increment. That signal is in `l1/hud` on all
18 sessions and needs no roster and no decode, so unlike the roster instrument
it generalises to the whole corpus immediately.

**It is left for the player because it changes the round DEFINITION.** It moves
every stored round, needs a `ROUND_VERSION` bump, and shifts every coaching
event, eligible state and audit window derived from them. That is a call about
comparability, not a measurement, and this page is the evidence for making it.

---

# 2026-09-07: the round start MOVED to the clock reset (`round-0.2.0`)

Decided by the player. The start is now the first upward clock JUMP after the
score increment -- detected as a jump rather than a value band, because the band
is not reliably read (on `587c15b07779` the buy clock after 157.5 s is first
read at 16 s, the earlier part lost to a frozen frame). **The END did not move**,
so rounds are no longer contiguous and the gap between them is the post-round
period.

## It lands where the roster predicted, on six times the rounds

    clock at the NEW start   median 28.0s  p10 25.0  p90 29.0   n=275 rounds
    in a buy phase (20-35s)  254/275 (92%)
    gap, round END -> next START   median 7.5s  p10 0.0  p90 9.5   n=351

The roster predicted 28.0 s from 26 rounds on two sessions; the clock rule
delivers 28.0 s across 275 rounds on eighteen. Two channels, different pixels,
same number.

    start_source   clock_reset 275   score_increment 76   capture_start 18

**22% fall back**, and they are labelled rather than hidden: those are rounds
whose clock was unreadable through the whole buy phase, which is unsurprising at
the 33-60% clock read rates already on record. A fallback round keeps the old
contiguous start and says so.

## What moved, and what did not

**Did NOT move, and had better not have:** `STATUS.md` is byte-identical --
every K/D against `checks.KNOWN_KD` (12 of 17 exact), 369 rounds, 183/369
plants. Those come from session-level killfeed tracks rather than from round
assignment, so a start-side change must not touch them, and it did not.

**Coaching eligibility did not move either:** 329 and 107 states, 20 and 8
rounds, 543 events, 26 eligible rounds, still abstaining. What changed is the
BOOKKEEPING, and it changed honestly -- `clock_or_phase_unknown` fell by exactly
the amount `round_boundary_or_unresolved` rose (204 on one session, 81 on the
other). The same samples; they are now rejected as *outside a round* rather than
as *inside a round with an unknown clock*.

| event quality flag | before | after |
|---|---:|---:|
| `round_boundary_uncertain` | 111 | **79** |
| `round_unresolved` | 7 | **39** |

118 events carry a boundary concern either way, but 39 of them are now
DEFINITE rather than uncertain: they land in the post-round gap and belong to no
round. That is the flag getting sharper, not more numerous.

**The audit moved the way the diagnosis predicted:**

| | 587c15b07779 | c40d950031bb |
|---|---|---|
| agree | 116 -> 108 | 58 -> 54 |
| disagreement | 6 -> **4** | 2 -> **0** |
| timing_ambiguous | 1 -> 3 | 1 -> 1 |
| unreadable_roster | 7 -> 5 | 0 -> 1 |
| count_increase | 1 -> 1 | 0 -> 0 |

Window totals fall (131 -> 121, 61 -> 56) because rounds are ~7.5 s shorter.
**Both boundary-straddling windows resolved** -- `c40d950031bb`'s known
cancelling pair at 690.5/700.5 s is gone entirely, and `587c15b07779`'s
314.5-324.5 s softened from disagreement to timing_ambiguous. The three **Run It
Back** windows and the two tracker defects persist, exactly as they should:
moving a round boundary cannot fix a killfeed defect.

## The 167.5-177.5s count increase RESOLVED, and a real one took its place

It is gone, which is what the diagnosis predicted: it was a 0 -> 5 roster step
across the true boundary, reported as an anomaly inside one derived round.

The count that remains is a **different window, 690.5-700.5 s**, which was
previously buried inside an `unreadable_roster` window and is now visible.
Rendered at 5x: the enemy bar shows **one** portrait at 698.0 and 699.0 s,
**two** at 699.5, 700.5 and 702.0 s, and one again at 702.5 s. The reader is
right at every step. An enemy count rising 1 -> 2 is a **Sage or Clove revive**,
and the return to 1 is the revived player dying again -- there is a killfeed
track at 702.5 s. CLAUDE.md already records that those deaths count.

So this is not a defect and not a regression: it is a real game event the round
change exposed, and the audit flag did its job by demanding an explanation.

---

# 2026-09-07: the revive-mark reader, STARTED -- geometry located

The mark that explains three of the seven unresolved audit windows. Not built;
what follows is the measurement any detector has to be built on, and it already
corrects the assumption I started from.

## WHERE IT IS, and it is not where the layout suggests

The band reads `[killer portrait][killer name][weapon icon][marks][victim name]`,
so the obvious crop is `EntryView.wx1` (right edge of the weapon icon) to
`victim_run[0]` (left edge of the victim's name). Extracted at 6x INTER_NEAREST
for three confirmed Run It Back entries and four confirmed plain ones:

    marked   211.5s slot 1   Vyse (+) Phoenix     gap 66 px
             951.5s slot 1   Omen (+) Me          gap 32 px
            1378.5s slot 0   Fade (+) Phoenix     gap 74 px
    plain   1018.5s slot 1   Phoenix (x) Me       gap 58 px
             323.0s slot 0   Chamber (x) Jett     gap 54 px
             323.0s slot 2   Raze (x) Vyse        gap 54 px
             323.0s slot 3   Omen (arrow)(x) Raze gap 88 px

**The badge STRADDLES the victim-plate boundary and is only half inside that
crop.** In every marked case the circular arc appears at the extreme right edge,
drawn over the red victim plate, with `victim_run[0]` cutting through it. So a
reader keyed to the weapon->victim gap alone would see a sliver of arc and
nothing more. **The crop must extend past `victim_run[0]`.**

## WHAT SEPARATES THEM

    Run It Back   a large white CIRCULAR ARC enclosing a curved glyph, drawn
                  across the plate boundary. Unmistakable at 6x.
    headshot      four short bars arranged around a centre point -- no arc.
                  It is the COMMON occupant of this gap and appears on marked
                  and unmarked entries alike, so it is a confounder rather than
                  an alternative: 211.5s and 1378.5s carry BOTH.
    wallbang      a separate arrow-like glyph, seen at 323.0s slot 3 alongside
                  the crosshair.

So the discriminator is the ARC, and the marks are not mutually exclusive --
a detector must answer "is there an arc" rather than "which single mark is this".

## Why it stops here

Three confirmed positives is not a population. This directory's own lesson from
earlier today is that a mechanism confirmed once and generalised is how the
`over_long` merge hypothesis got refuted on its first independent test, and
`prototypes/CLAUDE.md` records `detail` failing the same way at n=3. The next
step is a labelled set spanning both sessions with a Phoenix or Kayo, then a
circle FIT rather than a threshold -- `minimap.fit_ring` is the precedent, and
the standing rule is *fit a shape, do not repair one*.

`ff636d173b07` is the session to add: CLAUDE.md records **four** Phoenix ult
marks there at 13:21, 20:00, 29:13 and 38:20, verified by hand, and its K/D is
+4 deaths against `checks.KNOWN_KD` for exactly that reason. That is seven
positives across two sessions with an independent count to score against.
