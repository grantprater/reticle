# Named alive sets from the scoreboard — 2026-09-23

**Outcome: the board and the roster agree; one prediction clause failed as
worded.** Each accepted scoreboard opening names who is lit and who is dimmed
on each side [domain:rounds/scoreboard-dim-is-dead]. The top-bar roster counts
the living independently, and both readers ride the same sampled pass, so an
opening and its roster row share a timestamp.

## Mechanism

- `reconciliation.audit_board_alive` joins each accepted opening to the latest
  roster row at or before it (within 1 s) and compares the lit count per side.
  An unread or missing roster refuses with its reason. Each disagreement keeps
  its distance to the nearest killfeed entry and score boundary, and the time
  since the roster count last rose.
- `reconciliation.contradicted_openings` lists the (opening, side) pairs the
  roster contradicts. The scoreboard death witness
  (`adjudication.death.scoreboard_death_claims`) skips them and counts the
  skips in its evidence.

## Results

Across the 19 scoreboard sessions, the lit count equals the roster count on
11926 of 11958 side-openings (99.7%). Another 78 have an unread roster.

The 32 disagreements, classified by time since the roster count rose:

| Class | Count | Which channel is wrong | Source check |
| --- | --- | --- | --- |
| First sample of a new round: the top bar has reset, the board has not relit | 22 | neither; a transition [domain:rounds/scoreboard-relights-after-top-bar] | `587c15b07779` 97500 ms: all ten top-bar portraits, seven board rows dimmed |
| Roster reads 1 on a wiped side | 6 | roster | `96aa1ae9b96f` 1082000 ms: empty ally top bar, all five rows dimmed |
| 0.5–5 s after a rise, or 500 ms from a death | 4 | not checked | none |

The prediction said at least 80% of disagreements would lie within 2 s of a
killfeed entry or score boundary; 22 of 32 (69%) did. The window was measured
from the score change, which precedes the next round by about 7 s, so it
missed the round-start transition that causes most of them.

In round 4 of `a06f04a0059f`, all 34 side-openings agree with the roster, and
each of the seven named victims is lit in every accepted opening before its
death and dimmed in every one after it. Deadlock, Jett and Miks were named by
the dimming witness, so only Reyna, Phoenix and Skye test the dimmed side
independently. Iso dies after the last opening. The round still names all
seven (`teststore/death-round4-board-alive/`).

## Open

- The roster's wiped-side reading of 1 is a roster defect; `roster.resolve`
  owns it.
- A stale board can only hide deaths from the witness's newly dimmed set,
  never add one, so before the guard it caused refusals, not wrong names.
  The guard changes the refusal reason to the true one.
