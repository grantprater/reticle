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

## The wiped side reads 0 — 2026-09-28

Across 20 scoreboard sessions, `roster.resolve` read 1 on
[metric:roster_split/bar-floor#wiped_read_1_before=32] side-openings whose
five board rows were all dimmed. The source crops
(`notes/pictures/roster_wiped_reads_1.png` in the store) show two causes:

- **An empty bar over scenery.** The panel dims the scene behind it rather
  than hiding it, so the innermost empty slot reached 10-12 against 3-8
  elsewhere, cleared `DETAIL_FLOOR` (9), and the ratio among five scenery
  slots cleared 1.0. Six wipes, 27 side-openings.
- **A drawn portrait the board has dimmed.** KAY/O on `4f207c0c4e39`, and a
  red portrait and Clove on `ff636d173b07`, sit crisp on the top bar. The
  reader reads what is drawn; which channel is right is the board's question.

Before tuning anything I checked the other witnesses. Past each side's fifth
killfeed death, [metric:roster_split/bar-floor-killfeed#rows_ge1_bar_max_below_13_before=52]
rows read 1 or more on a bar with no slot at 13; the rest show a crisp
survivor (`notes/pictures/roster_wiped_killfeed_contradicted.png`), so they
audit the killfeed, not the roster. The roster audits the killfeed, so the
killfeed cannot also gate it (`roster.py`, "the direction that must not be
reversed"), and the board opens too rarely to gate every row. The defect
lives in the reader's own rule, so the rule changed.

**The fix (roster-split-0.3.1).** A bar whose crispest slot is below
`CRISP_FLOOR` (13) holds no portrait: it reads 0 when the scoreline reads and
None otherwise. A bar with any crisp slot keeps the 0.2.0 ratio rule.

| Check | 0.2.0 | 0.3.1 |
| --- | --- | --- |
| Board-wiped side-openings read 1 | [metric:roster_split/bar-floor#wiped_read_1_before=32] | [metric:roster_split/bar-floor#wiped_read_1=5] |
| Board agreements | [metric:roster_split/bar-floor#agree_before=34383] | [metric:roster_split/bar-floor#agree=34399] |
| Agreements lost | — | [metric:roster_split/bar-floor#agree_lost=0] |
| Rows reading ≥1 after a fifth killfeed death | [metric:roster_split/bar-floor-killfeed#rows_ge1_before=708] | [metric:roster_split/bar-floor-killfeed#rows_ge1=656] |
| In-round rows read 0 beside a slot at 13+ | — | [metric:roster_split/bar-floor-rows#in_round_0_with_slot_ge_13=0] |
| `checks.KNOWN_KD` exact, of [metric:roster_split/bar-floor-known-kd#sessions=17] | unchanged | [metric:roster_split/bar-floor-known-kd#exact=13] |

The five that still read 1 are the drawn-portrait wipes. Over every stored
row, [metric:roster_split/bar-floor-rows#changed=731] resolved counts move;
[metric:roster_split/bar-floor-rows#in_round_to_0=2] in-round rows fall to 0,
both wipes, and the rest become None. Most are the game's menu screen,
whose navigation icons 0.2.0 read as three allies (four crops checked). On the board, no side the two agree on shows a lit
portrait on a bar below 13
[metric:roster_split/bar-floor#lit_bar_max_below_13_agree=0].

**The rule it replaces.** An earlier draft raised `DETAIL_FLOOR` to 13 for
every split. It fixed the same board cases and lost no agreement, but over
all stored rows it read 0 on
[metric:roster_split/bar-floor-rows#per_split_13_in_round_0_with_slot_ge_13=26]
in-round rows beside a slot at 13 or more. The crops
(`notes/pictures/roster_floor13_inround_changes.png`) show red portraits
[domain:minimap/red-portrait-states] at 9-12 beside crisp teammates:
`a1a995e6b19b` 1640 s allies, three alive, read 0. The board check alone
could not catch it: it lost no agreement.

The stored table follows the rule: `scan --only roster --from cache` reread all
[metric:roster_split/bar-floor-cache#sessions=21] roster sessions without a
decode. All [metric:roster_split/bar-floor-cache#detail_identical=175578]
detail cells match the table before, and the
[metric:roster_split/bar-floor-cache#alive_changed=731] changed ungated
counts all became None, none on a bar with a crisp slot
[metric:roster_split/bar-floor-cache#alive_changed_crisp=0].

## Open

- A wiped side over scenery that reaches 13 still reads 1 or more
  ([metric:roster_split/bar-floor#wiped_bar_max_ge_13=13] of
  [metric:roster_split/bar-floor#wiped_sides=2197] board-wiped sides), and
  scenery behind the first empty slot of a partly filled bar can count as one
  more portrait (`4f207c0c4e39` 2170.5 s reads 4 of 3). Detail cannot separate
  that scenery from a red portrait; the pill or the hue might.
- A bar with a crisp slot but no winning split reads 0 under a drawn HUD
  (`[7.34 31.09 7.32 37.00 13.04]`); it should refuse. Not changed here.
- Round entities and the death adjudicator read the stored ungated columns
  rather than `resolve`; they pick up 0.3.1 only when rerun.
- A stale board can only hide deaths from the witness's newly dimmed set,
  never add one, so before the guard it caused refusals, not wrong names.
  The guard changes the refusal reason to the true one.
