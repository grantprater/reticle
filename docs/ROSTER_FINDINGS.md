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
