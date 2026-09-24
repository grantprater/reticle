# Scoreboard-constrained lineup — 2026-09-23

**Outcome: passed.** The Tab scoreboard now names each side's five agents, and
`adjudication.identity` restricts the top-bar slot assignment to them. Round 4
of `a06f04a0059f` has all seven deaths named, each matching the player's
source answer, where it previously had four.

## Mechanism

- `scoreboard-0.3.0` stores every agent's score per row, not just the best two.
- `identity.board_side_sets` assigns each accepted opening's five rows with
  `assign_side` over those scores. It believes a side's set only when at least
  two openings name all five and every one names the same five.
- `identity.lineup_with_board` re-assigns the stored top-bar matrix over that
  set. The board says who is on the side; the top bar says which slot. The
  unconstrained verdict stays under `top_bar_sides`, and each changed name goes
  into `board_disagreements`.
- `lineup.load_lineup` applies both when the session's scoreboard rows are
  current, so every consumer gets the constrained lineup.

## Results

| Session | Board sets | Top bar alone | With board | Source check |
| --- | --- | --- | --- | --- |
| `a06f04a0059f` (Ascent) | 156 openings, one set per side | ally 3/5, enemy 3/5 named; enemy slot 2 accepted *Clove* | 10/10 named | all ten match the top bar |
| `7010b3d62460` (Lotus) | 205 openings, one set per side | ally 3/5, enemy 0/5 | 10/10 named | ally matches the recorded truth; enemy matches by eye, slot 1 Clove least certain |

The top bar's *Clove* in `a06f04a0059f` held Jett's slot. The earlier binding
write-up attributed it to Killjoy, which was wrong.

With the corrected candidates, the killfeed portrait names Skye (295500 ms)
and Iso (332500 ms). Jett (284500 ms) is **not** named by the portrait: its
four views split between Jett and Omen, and the channel abstains. The
scoreboard witness names Jett by elimination against the independently named
Skye, and the verdict records zero independent channels and that dependency.

## Corpus at scoreboard-0.5.0

The other 17 sessions with scoreboard rows were rescanned (`reticle scan
<id> --only scoreboard --force`). In every one, each side's accepted
openings, 73 to 891 per session, agree on a single five-agent set, so the
board names both sides in all 17. The constrained lineup names 170 of 170
slots; the top bar alone named 113.

The board changed six top-bar names, one each in six sessions. A source crop
of the top bar and an accepted opening shows the board right every time:

| Session | Slot | Top bar | With board | Source |
| --- | --- | --- | --- | --- |
| `3694746e4e54` | enemy 2 | Breach | Brimstone | beret; all ten slots match |
| `5822b6646448` | enemy 3 | Clove | Jett | white hair |
| `96aa1ae9b96f` | enemy 3 | Raze | Cypher | hat; all five enemy slots match |
| `b7d24102a6f6` | enemy 3 | Breach | Brimstone | beret |
| `bdfdcf009dba` | enemy 2 | Breach | Tejo | goggles |
| `bfad2778a372` | ally 2 | Sova | Chamber | glasses and suit |

The eleven sessions with no changed name were not source-checked; their
filled slots rest on the board alone. The prediction and outcome are in the
store's `notes/predictions.jsonl` under `scoreboard-corpus`.

## Reader defect found

Some openings place the enemy block on top of the ally block and read the ally
portraits twice. At 1999000 ms of `a06f04a0059f` that produced a second enemy
set equal to the ally set, and `board_side_sets` refused on the disagreement.
`scoreboard_openings` refuses any opening whose enemy rows are not below its
ally rows: 13 of 378 openings in `a06f04a0059f` and 108 of 450 in
`7010b3d62460` at `scoreboard-0.3.0`.

The reader now fixes it at the source, in two steps. Two predictions were
logged, and the first was partly falsified:

- **0.4.0** searches for the enemy block only below the ally block. At
  1999000 ms the ally slab over a purple backdrop also passed the red test,
  so the tallest red run lay inside the ally block. That removed the case but
  left 30 and 118 overlapping openings from two other mechanisms: a short red
  run at the ally bottom (`a06f04a0059f` 305500 ms), and an ally block that
  swallowed the history strip (`7010b3d62460` 102000 ms). In both, anchoring
  the enemy rows at a team height lifts them into the ally block.
- **0.5.0** does not read a board whose anchored enemy rows start above the
  ally block's bottom, because nothing in the reader knows which block is
  right. Both sessions then have zero overlapping openings. Board sets,
  constrained lineups and all seven round-4 names are unchanged
  (`teststore/death-round4-reader-block-2/`). The adjudication gate stays as
  a second guard.

## Gates on the second session

Of 2692 gated rows in `7010b3d62460`, 3 (0.1%) have a gain inside the
0.60–0.75 band that separates live from dimmed portraits. The agent gates are
unchanged from `a06f04a0059f`. Both remain fitted on two sessions.
