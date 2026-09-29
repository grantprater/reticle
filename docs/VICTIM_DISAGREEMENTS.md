# Victim disagreements after scoreboard-0.9.0

Rerunning `reticle deaths` on the 20 sessions with scoreboard-0.9.0 inputs
raised the victim disagreements from 6 to 21
[metric:victim_disagreements/audit@corpus#disagreements=21]. Each of the 21
was judged by eye (2026-09-28) from the HUD crop cache: the killfeed entry's
victim portrait and name plate, and the top bar, which greys and then drops
each portrait as its agent dies. The top bar is a third channel that neither
witness uses. Contact sheets: `notes/pictures/victim-disagreements-20260928/`
in the store (`zoom_<session>_<ms>.png`). The predictions are in
`notes/predictions.jsonl` under `victim-disagreements`.

"Disagreements" counts death verdicts whose victim `identity.status` is
`disagreement`, as the `reticle deaths` summary prints them.

## Verdict

scoreboard-0.9.0 reads the board correctly. In every case checked, the newly
dimmed set matched the top bar: no row shift, no misread dim
[metric:victim_disagreements/audit@corpus#scoreboard_row_or_dim_errors=0].
Under scoreboard-0.6.0 the board witness refused the fifteen new cases'
intervals, and the killfeed alone resolved all fifteen: eleven right, four
wrong [metric:victim_disagreements/audit@corpus#new_wrong_before_rerun=4].
The new input exposes those four hidden errors, and opens eleven right names
where the board's elimination inherits a killfeed error or an uncounted
second life. The
killfeed witness is right on 14 of the 21
[metric:victim_disagreements/audit@corpus#killfeed_right=14]; the board
witness is right on 6 [metric:victim_disagreements/audit@corpus#board_right=6];
neither is right on one.

Agreement is consistency, not accuracy: the board's claim is wrong on most
of the 21 because `scoreboard_death_claims` names by ELIMINATION, and
elimination inherits whatever the other deaths in the interval were called.

## Causes

| Cause | n | Right witness |
|---|---|---|
| Killfeed portrait art misreads Clove or Sage as Reyna | 3 | board |
| Its interval partner, named by elimination from the misread | 2 | killfeed |
| Follow drift: same killer and weapon, the entry takes a neighbour's views | 3 | board (2), neither (1) |
| Its interval partner, named by elimination from the drifted name | 3 | killfeed |
| A second life or revive went uncounted, and an uncounted death made the count match | 7 | killfeed |
| Entry onset stored 1 s late, closing entry left out | 1 | killfeed |
| Name cluster alone wrong | 1 | board |
| `player_hud` calls the player's kill a player death | 1 | name cluster |

Counts: [metric:victim_disagreements/audit@corpus#portrait_art_misread=3],
[metric:victim_disagreements/audit@corpus#art_misread_partner=2],
[metric:victim_disagreements/audit@corpus#follow_drift=3],
[metric:victim_disagreements/audit@corpus#drift_partner=3],
[metric:victim_disagreements/audit@corpus#second_life_uncounted=7],
[metric:victim_disagreements/audit@corpus#onset_lag_boundary=1],
[metric:victim_disagreements/audit@corpus#name_cluster_alone=1],
[metric:victim_disagreements/audit@corpus#player_hud_flag=1].

**Duplicate names.** Fourteen of the fifteen new disagreements come in seven
pairs: two deaths in one board interval carry one name, and elimination
gives each the one dimmed agent no killfeed entry named. Either the killfeed
misread one entry, or the agent really died twice. The pair alone does not
say which. The crops split them: four pairs were misreads (two by the
portrait art, two by follow drift), and three were real second lives (KAY/O
downed in NULL/cmd, then killed; Clove after Not Dead Yet; Reyna after
Sage's Resurrection) whose revive or downed entry never reached the death
rows.

**Uncounted second lives.** A count that matches is not evidence. In
`a1a995e6b19b` KAY/O dies twice and Clove's death sits at the closing board's own time, which
the interval left out; four deaths against four dimmed agents matched by
coincidence. In `b3b9defb6fd7` Breach's death was stored with the ally side,
and Clove revived through Not Dead Yet and stayed lit. In `bdfdcf009dba` the
Not Dead Yet entry went unstored and Miks's death fell on an entry of unknown
side (not verified by eye).

**The closing opening.** Five of the 21 involve an entry whose onset equals
the time of the board opening that closes its interval
[metric:victim_disagreements/audit@corpus#closing_opening_entry=5]. A
killfeed entry appears at or after its death, so the board at that frame
already dims the victim, yet the interval `lo < t < hi` left it out.

**A silent error found beside them.** `bfad2778a372` 616.5 s is resolved as
Raze; its victim is Phoenix (BiGDonut101). The stack rose two slots at once
and the Raze entry's views were bound to the Phoenix entry
[metric:victim_disagreements/audit@corpus#silent_wrong_found=1].

## The 21

Times are the stored entry onset. New = not a disagreement in the backup
`notes/backup/deaths-before-scoreboard-0.9.0-rerun-20260928/`.

| Session, time | New | Portrait / cluster | Board | Other | True victim | Right | Cause |
|---|---|---|---|---|---|---|---|
| 223d636bf8d2 817.0 | yes | Reyna (portrait) | Clove | | Clove | board | art misread |
| 223d636bf8d2 820.5 | yes | Reyna | Clove (elim.) | | Reyna | killfeed | art partner |
| 223d636bf8d2 1293.0 | | Vyse | Iso (elim.) | | Vyse | killfeed | drift partner |
| 223d636bf8d2 1296.0 | | Vyse (views end Iso) | Iso | | Iso | board | follow drift |
| 3694746e4e54 319.5 | yes | Gekko | Brimstone (elim.) | | Gekko | killfeed | drift partner |
| 3694746e4e54 320.0 | yes | Gekko (first view Brimstone) | Brimstone (elim.) | | Brimstone | board | follow drift |
| 5822b6646448 1287.5 | | Reyna (portrait) | Sage | | Sage | board | art misread |
| 587c15b07779 776.0 | yes | Phoenix | Vyse | player_hud Phoenix | Phoenix | killfeed | onset lag, closing entry |
| 587c15b07779 1466.5 | | Fade (cluster; portrait Vyse) | Vyse (elim.) | | Vyse | board | name cluster |
| 59c70f1ef720 1619.5 | | Breach | refused | player_hud Sova | Breach | cluster | player_hud flag |
| 9acf02f98283 592.5 | yes | Reyna (portrait) | Clove (elim.) | | Clove | board | art misread |
| 9acf02f98283 595.0 | yes | Reyna | Clove (elim.) | | Reyna | killfeed | art partner |
| a1a995e6b19b 1639.5 | yes | KAY/O | Clove (elim.) | | KAY/O (downed) | killfeed | second life, closing entry |
| a1a995e6b19b 1650.5 | yes | KAY/O | Clove (elim.) | | KAY/O | killfeed | second life, closing entry |
| b3b9defb6fd7 1837.5 | | Clove | Breach (elim.) | | Clove (then Not Dead Yet) | killfeed | second life, side error |
| bdfdcf009dba 665.0 | yes | Clove (portrait) | Miks (elim.) | | Clove | killfeed | second life |
| bdfdcf009dba 669.0 | yes | Clove (portrait) | Miks (elim.) | | Clove (after Not Dead Yet) | killfeed | second life |
| bfad2778a372 615.5 | yes | Deadlock (first view Raze) | Phoenix (elim.) | | Raze | neither | follow drift |
| bfad2778a372 619.5 | yes | Deadlock | Phoenix (elim.) | | Deadlock | killfeed | drift partner |
| ff636d173b07 2228.5 | yes | Reyna | Sage (elim.) | | Reyna | killfeed | second life, closing entry |
| ff636d173b07 2240.5 | yes | Reyna | Sage (elim.) | | Reyna (after Sage's revive) | killfeed | second life, closing entry |

Captures (from the session manifests):

| Session | Capture |
|---|---|
| 223d636bf8d2 | `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4` |
| 3694746e4e54 | `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4` |
| 5822b6646448 | `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4` |
| 587c15b07779 | `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4` |
| 59c70f1ef720 | `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4` |
| 9acf02f98283 | `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4` |
| a1a995e6b19b | `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4` |
| b3b9defb6fd7 | `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4` |
| bdfdcf009dba | `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4` |
| bfad2778a372 | `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4` |
| ff636d173b07 | `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4` |

## What changed: the closing opening (death-adjudication-0.15.0)

`scoreboard_death_claims` now counts an entry whose onset equals an
opening's time toward the interval that opening closes: `(before, after]`.
`reticle deaths` reran on the 20 sessions from storage (no decode). Before is
the backup `notes/backup/deaths-0.14.0-scoreboard-0.9.0-before-boundary-20260928/`.

| | 0.14.0 | 0.15.0 |
|---|---|---|
| Victim disagreements | [metric:victim_disagreements/closing-opening@corpus#victim_disagreements_before=21] | [metric:victim_disagreements/closing-opening@corpus#victim_disagreements_after=16] |
| Killer disagreements | [metric:victim_disagreements/closing-opening@corpus#killer_disagreements_before=13] | [metric:victim_disagreements/closing-opening@corpus#killer_disagreements_after=13] |
| Board claims naming a victim | [metric:victim_disagreements/closing-opening@corpus#board_claims_before=1690] | [metric:victim_disagreements/closing-opening@corpus#board_claims_after=1787] |
| Killer labels right / wrong / unnamed | 138 / 1 / 7 | [metric:victim_disagreements/closing-opening@corpus#labels_right_after=138] / [metric:victim_disagreements/closing-opening@corpus#labels_wrong_after=1] / [metric:victim_disagreements/closing-opening@corpus#labels_unnamed_after=7] |

The five closing-opening disagreements resolved, all to the true victim
(`587c15b07779` 776.0 s Phoenix, `a1a995e6b19b` 1639.5 and 1650.5 s KAY/O,
`ff636d173b07` 2228.5 and 2240.5 s Reyna)
[metric:victim_disagreements/closing-opening@corpus#disagreement_to_resolved_right=5].
Three abstentions gained a name from the board alone, each right by eye
(`043bafca271a` 351.5 s Chamber, `bfad2778a372` 1850.0 s Jett,
`ff636d173b07` 217.5 s Clove;
`new_board_names.png`)
[metric:victim_disagreements/closing-opening@corpus#abstained_to_resolved_right=3].
No resolved name changed
[metric:victim_disagreements/closing-opening@corpus#resolved_names_changed=0].
The board withdrew 7 claims and added 104; every added claim that met
another witness agreed with it.

The five closing-opening cases resolve because the fixed count no longer
matches (for instance four dimmed agents against five deaths), so the board
refuses and the killfeed names alone. The second life stays uncounted; the
fix removes a coincidence, not the cause.

## What changed: the elimination collision (death-adjudication-0.16.0)

Elimination now refuses an interval whose independent names repeat an agent.
Every board claim in it reads `elimination_collision ['<agent>']`, and
`reticle deaths` stores one `collision` row per interval in the `death`
stream: the side, both openings, the newly dimmed agents, each death's key,
name and naming channels, and the board's own reason. A collision where the
count or a revive already refused is stored with that reason. The claims
already declared `depends_on` for the deaths elimination used.

Six stored intervals had repeated names
[metric:victim_disagreements/elimination-collision@corpus#colliding_elimination_intervals=6], holding 12 of the 16
disagreements [metric:victim_disagreements/elimination-collision@corpus#disagreements_in_colliding_intervals=12]. Rerun from
storage on the 20 sessions; before is the backup
`notes/backup/deaths-before-elimination-collision-20260928/`.

| | 0.15.0 | 0.16.0 |
|---|---|---|
| Victim disagreements | [metric:victim_disagreements/elimination-collision@corpus#victim_disagreements_before=16] | [metric:victim_disagreements/elimination-collision@corpus#victim_disagreements_after=4] |
| Killer disagreements | 13 | [metric:victim_disagreements/elimination-collision@corpus#killer_disagreements_after=13] |
| Killer labels right / wrong / unnamed | 138 / 1 / 7 | [metric:victim_disagreements/elimination-collision@corpus#labels_right_after=138] / [metric:victim_disagreements/elimination-collision@corpus#labels_wrong_after=1] / [metric:victim_disagreements/elimination-collision@corpus#labels_unnamed_after=7] |
| `checks.KNOWN_KD` exact of 17 | 13 | [metric:victim_disagreements/elimination-collision@corpus#known_kd_exact_after=13] |
| Collision rows | 0 | [metric:victim_disagreements/elimination-collision@corpus#collision_rows=30] |

The 30 rows: [metric:victim_disagreements/elimination-collision-rows@corpus#elimination_collision=6]
elimination collisions, [metric:victim_disagreements/elimination-collision-rows@corpus#count_mismatch=17]
where the count refused and [metric:victim_disagreements/elimination-collision-rows@corpus#revive_in_interval=7]
where a revive refused.

No resolved name changed [metric:victim_disagreements/elimination-collision@corpus#resolved_names_changed=0];
`bfad2778a372` 616.5 s stays Raze (truly Phoenix), since its claim already
refused. The 12 disagreements resolved to the killfeed's name
[metric:victim_disagreements/elimination-collision@corpus#disagreement_to_resolved=12]: seven right
[metric:victim_disagreements/elimination-collision@corpus#disagreement_to_resolved_right=7] and five wrong
[metric:victim_disagreements/elimination-collision@corpus#disagreement_to_resolved_wrong=5], by the table above (three
rechecked on the zoom crops):

| Session, time | Resolved | True victim |
|---|---|---|
| 223d636bf8d2 817.0 | Reyna | Clove |
| 223d636bf8d2 1296.0 | Vyse | Iso |
| 3694746e4e54 320.0 | Gekko | Brimstone |
| 9acf02f98283 592.5 | Reyna | Clove |
| bfad2778a372 615.5 | Deadlock | Raze |

The refusal traded twelve flagged deaths for seven right names and five
silent errors. A board refusal leaves the killfeed witness alone, and the
arbiter resolves one named witness. The collision row marks each of the five:
a consumer that reads it, or requires two independent channels, sees them.
The next step is to have the arbiter or the killfeed treat a stored collision
as contested, not to name either death from the board.

## Recommended next

1. **A stored collision should contest its deaths' names.** Elimination
   now refuses a colliding interval (0.16.0 above), and five of its deaths
   resolve silently wrong on the killfeed alone. The collision row names
   them; the arbiter or the killfeed should read it.
2. **Store the revive entries.** Clove's Not Dead Yet (`bdfdcf009dba` about
   666 s) and Sage's Resurrection (`ff636d173b07` about 2240 s) were on screen
   and absent from the death rows, so the board witness never saw
   `revive_in_interval`. KAY/O's downed entry carries the NULL/cmd emblem and
   should mark a second life.
3. **Follow drift.** Two consecutive entries by one killer with one gun share
   the follow key (`follow_entry_portraits`); three of the 21 and the silent
   `bfad2778a372` 616.5 s error come from it. The victim's name plate text
   would separate them.
4. **Clove and Sage read as Reyna** by the portrait art, as the exemplar
   experiment found for Sage on `5822b6646448`.
