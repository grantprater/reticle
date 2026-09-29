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

## Scenery above the panel — 2026-09-28, later

`4f207c0c4e39` 2170.5 s (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`)
read four allies where the board lit three. The crop
(`notes/pictures/roster_panel_band_board_changes.png`, first row) shows the
cause: the crispness band began at the crop's top row, and the tinted panel
begins on row 8 of 78. Above it the scene arrives undimmed. Over the board's
empty slots, the top row reaches
[metric:roster_split/panel-band#empty_top_rows_p99=28.2] at the 99th
percentile; inside the panel no row passes
[metric:roster_split/panel-band#empty_panel_rows_p99_max=4.5]. The empty
slot's 10.4 was a window frame above the panel. Neither the pill nor the hue
was needed: once the band starts inside the panel, detail separates scenery
from a red portrait [domain:minimap/red-portrait-states].

**The fix.** `roster-0.3.0` reads crispness from `PANEL_TOP_FRAC` (row 10)
to `ART_FRAC`. `roster-split-0.4.0` refuses a bar with a crisp slot and no
winning split (`no_split`) instead of reading 0, names every refusal's reason
(`roster.read_split`, `roster.resolve_reasons`, and `roster_reason` on the
board audit's unread records), and lowers `DETAIL_FLOOR` from 9 to 8. In the
panel band no slot the board leaves empty reaches
[metric:roster_split/panel-band#empty_max=7.53] and no lit one falls below
[metric:roster_split/panel-band#occupied_min=19.07]; a red portrait reads 6
to 11. The first reread kept the floor at 9, and the crops of every in-round
change showed a red KAY/O between crisp teammates at 8.9 (`bfad2778a372`
1011.5 s allies) reading 1 of 4; the floor of 8 restores 4.

| Check | 0.3.1 on roster-0.2.0 | 0.4.0 on roster-0.3.0 |
| --- | --- | --- |
| Board agreements, of [metric:roster_split/panel-band#side_openings=35250] | [metric:roster_split/panel-band#agree_before=34399] | [metric:roster_split/panel-band#agree=34402] |
| Agreements lost | — | [metric:roster_split/panel-band#agree_lost=0] |
| Board-wiped sides with a slot at 13+ | [metric:roster_split/panel-band#wiped_bar_max_ge_13_before=13] | [metric:roster_split/panel-band#wiped_bar_max_ge_13=11] |
| of those, scenery (crops) | — | [metric:roster_split/panel-band#wiped_scenery_ge_13=0] |
| `checks.KNOWN_KD` exact, of [metric:roster_split/panel-band-known-kd#sessions=17] | [metric:roster_split/bar-floor-known-kd#exact=13] | [metric:roster_split/panel-band-known-kd#exact=13] |

The three agreements gained: `4f207c0c4e39` 2170.5 s (4 to 3),
`5822b6646448` 1946.5 s (a pale fifth portrait, 4 to 5) and `e37fdeca944f`
1650.5 s (a wiped bar over scenery, 2 to 0). `c40d950031bb` 961.5-964 s, five
portraits under a fading screen, now refuses instead of reading 1. The
eleven wiped side-openings that still read a count all show drawn
portraits: seven at a round reset the board has not relit, one KAY/O the
board dims (`4f207c0c4e39` 911.5 s), and three openings of a red portrait
with no health pill (`ff636d173b07` 523.5-524.5 s).

Over every stored row, [metric:roster_split/panel-band-rows#changed=593] of
[metric:roster_split/panel-band-rows#cells=175578] resolved counts change;
[metric:roster_split/panel-band-rows#to_none_hud_not_drawn=550] become None
on a bar with nothing crisp and no scoreline, most of them the menu before
the first round, and [metric:roster_split/panel-band-rows#no_split=11]
refuse `no_split`. I checked all
[metric:roster_split/panel-band-rows#in_round_changes_checked=37] in-round
changes that are not HUD refusals by crop
(`notes/pictures/roster_panel_band_inround_changes.png`). A red captive now
counts (`a1a995e6b19b` 942.5 s and `a06f04a0059f` 537.5 s enemies, 0 to 4),
and the `no_split` refusals replace a 0 beside a crisp portrait. Nine answers
became wrong
[metric:roster_split/panel-band-rows#in_round_newly_wrong=9]: eight rows at
session starts with no HUD drawn, where scenery or menu text is crisp
(`bdfdcf009dba` 0-2.5 s, `96aa1ae9b96f` 47.5 s, `bfad2778a372` 29.5 s), and
`a06f04a0059f` 1099.0 s enemies, whose red fifth portrait the enemy box clips
(below), 5 to 4.

`scan --only roster --from cache --force` reread all
[metric:roster_split/panel-band-cache#sessions=21] roster sessions without a
decode. [metric:roster_split/panel-band-cache#ungated_changed=977] stored
ungated counts changed,
[metric:roster_split/panel-band-cache#ungated_changed_in_round=539] of them
in a round. The old tables are in
`notes/backup/roster-before-0.3.0-20260928/`.

## The enemy box clips the fifth portrait

`hud_roster_enemy` spans x 1167-1467, 300 px; `hud_roster` spans 434-751,
317 px, and mirrored about the scoreline's centre it would end at 1486. In
the `hud` cache the enemy tiles start about 66 px apart, and the fifth starts
at x [metric:roster/enemy-box#enemy_tile4_start_px=267.5] of the crop, so
about [metric:roster/enemy-box#enemy_tile4_px_outside=8] of its 40 px fall
outside it. The equal fifths the roster and lineup readers cut also drift
against the tiles: enemy slot 4's window holds about 28 px of panel and the
clipped tile.

That the clip causes the lineup's enemy refusals is only partly supported.
Over the stored lineups, the enemy side refuses
[metric:roster/enemy-box#lineup_refused_enemy=54] slots and the ally side
[metric:roster/enemy-box#lineup_refused_ally=20]; slot 4 refuses
[metric:roster/enemy-box#enemy_refused_slot4=14] times, but slots 0 and 2,
whose tiles lie whole inside their windows, refuse
[metric:roster/enemy-box#enemy_refused_slot0=11] and
[metric:roster/enemy-box#enemy_refused_slot2=12]. Every refusal's reason is
a margin below 0.07. The clip can explain at most slot 4's excess; the
side-wide gap has another cause. The cache holds no pixels beyond x 1467
above y 81, so a wider box needs a decode, which this work did not run.

## Open

- A drawn portrait the board dims still counts (KAY/O downed, a red
  portrait with no health pill). Which channel is right is the board's
  question.
- With no HUD drawn, a crisp bar still reads a count; the scoreline cannot
  gate it, because it is unread on many in-round rows.
- Widen `hud_roster_enemy` to 1167-1486 and cut slots at the tile pitch;
  that needs a decode of the roster sessions (or of the `hud` cache set)
  and a lineup rerun.
- Round entities and the death adjudicator read the stored ungated columns
  rather than `resolve`; they pick up roster-0.3.0 only when rerun from
  storage.
- A stale board can only hide deaths from the witness's newly dimmed set,
  never add one, so before the guard it caused refusals, not wrong names.
  The guard changes the refusal reason to the true one.
