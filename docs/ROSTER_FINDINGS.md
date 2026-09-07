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

