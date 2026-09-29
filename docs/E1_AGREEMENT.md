# E1: agreeing totals concealed binding errors — landed 2026-09-28

**Outcome: the prediction held, and it still holds on master.** Where the
killfeed, the combat report and the scoreboard agreed on a round's totals, the
owners had left death panels unbound, bound two report rows to one killer, and
merged an enemy's death into the player's killfeed track. Totals cannot see a
binding, so agreement is no acceptance test: score events one to one. The
branch's findings, with the numbers of its replay, are
[archived](archive/E1_AGREEMENT-2026-09-28.md). E1 belongs to
[the experiment program](EXPERIMENT_PROGRAM.md). Only the owner fixes are
promoted; the player has reviewed the seeded rounds against source (below).

## Landing on master

Branch `e1-land-20260928` merges `e1-agreement-20260927` over master
`64fff80`. Master's death rules keep their stamps: the board interval closes
on its opening (0.15.0), an elimination collision refuses the board's names
(0.16.0), and a collision contests its deaths (0.17.0). E1's track split, which
ends a killfeed entry track where its victim plate changes side, lands above
them as `death-adjudication-0.18.0`. `combat-report-round-0.10.0` lands
unchanged: master never moved past 0.8.0.

The two rules overlap: the split changes which entries exist, and master's
collision and interval rules read those entries. Before the store rerun, the
replay's control (0.18.0 code on the stored 0.17.0 verdicts) changed
[metric:e1_agreement/landing@store-20#before_deaths_control_changed=12]
verdicts, [metric:e1_agreement/landing@store-20#before_deaths_control_player_changed=4]
of them the player's, all in
[metric:e1_agreement/landing@store-20#before_control_sessions=6] sessions
where the split adds a track. The merge keeps both rules, since each changes
different evidence: the split separates two entries, and the collision rule
refuses a repeated name.

## The store rerun

`reticle deaths`, then `reticle combat-report`, ran from storage on the
[metric:e1_agreement/landing@store-20#sessions=20] sessions with a death
stream (backup: the store's `notes/backup/e1-land-before-deaths-0.18.0-20260928/`).
They read the stored `scoreboard-0.9.0`; master's code is `scoreboard-0.10.0`,
a rescan the player deferred, so `reticle plan` still lists deaths as stale on
the scoreboard input.

- The player's counted kills and deaths moved on
  [metric:e1_agreement/landing@store-20#player_kd_sessions_moved=0] sessions.
  The split added [metric:e1_agreement/landing@store-20#entries_new_only=36]
  entry keys and retired [metric:e1_agreement/landing@store-20#entries_old_only=8].
- `59c70f1ef720`'s player death moves to `death:59c70f1ef720:1625000:0`
  (killer Chamber), and the report's KILLED YOU row at 1625 s now binds it.
  Two player-kill rows follow the split to their new entries (`3694746e4e54`
  1355.5 s, `bfad2778a372` 1443.0 s):
  [metric:e1_agreement/landing@store-20#report_rows_rebound=3] rows rebound.
- Victim disagreements fell from
  [metric:e1_agreement/landing@store-20#victim_disagreement_before=7] to
  [metric:e1_agreement/landing@store-20#victim_disagreement_after=6], killer
  disagreements from [metric:e1_agreement/landing@store-20#killer_disagreement_before=3]
  to [metric:e1_agreement/landing@store-20#killer_disagreement_after=1];
  contested deaths stay at [metric:e1_agreement/landing@store-20#contested_after=18].
- The combat-report verdict equals `checks.KNOWN_KD` on every known session
  ([metric:e1_agreement/landing@store-20#report_sessions_off_known=0] off).

## The replay

`prototypes/e1_agreement.py --replay` read the 18 sessions ledger entry
`e1-agreement-land-2026-09-28` pins, with no decode; `0f08b3dc3777` stores no
HUD data and is refused. Of [metric:e1_agreement/replay@pinned-18#rounds=353]
rounds, [metric:e1_agreement/replay@pinned-18#three_way=79] agreed three ways,
[metric:e1_agreement/replay@pinned-18#disagree=11] disagreed and
[metric:e1_agreement/replay@pinned-18#unwitnessed=18] had fewer than two
channels. More rounds agree because `scoreboard-0.9.0` reads more boundaries:
[metric:e1_agreement/replay@pinned-18#boundaries_read=149] of
[metric:e1_agreement/replay@pinned-18#boundaries=370]. The seeded rounds hold
[metric:e1_agreement/replay@pinned-18#seeded_deaths=52] player deaths; the
report bound [metric:e1_agreement/replay@pinned-18#deaths_report_bound=51] and
flagged [metric:e1_agreement/replay@pinned-18#flagged=0] rounds. The unbound
death is `a06f04a0059f` round 16 at 1576.0 s, a second life in a round with
one panel. The verdict K/D is off `checks.KNOWN_KD` on
[metric:e1_agreement/replay@pinned-18#verdict_sessions_off_known=0] sessions.

### Disagreements by stored reason

- The killfeed misses a death the report saw: `5822b6646448` rounds 16 (a
  second life [domain:rounds/run-it-back-in-report]) and 19, `e37fdeca944f`
  rounds 1 and 5, and `c62c2b06bcfb` round 12 (the known Killjoy death; no
  scoreboard stream).
- `bfad2778a372` round 23: the killfeed credits a kill that the report and the
  known K/D do not.
- The scoreboard misreads the player row: `b7d24102a6f6` rounds 11 and 12 and
  `bdfdcf009dba` round 17, as before; and, new at `scoreboard-0.9.0`,
  `bdfdcf009dba` rounds 3 and 4, where the board books round 3's death one
  boundary late.

### Withholding

Without the killfeed portraits and death bindings, the report loses
[metric:e1_agreement/replay@pinned-18#rows_no_killfeed_lost=22] of
[metric:e1_agreement/replay@pinned-18#rows_no_killfeed_entities=68] row names;
without the scoreboard it changes
[metric:e1_agreement/replay@pinned-18#rows_no_scoreboard_changed=4] and renames
none. Without the scoreboard,
[metric:e1_agreement/replay@pinned-18#deaths_no_scoreboard_changed=105] death
verdicts change, [metric:e1_agreement/replay@pinned-18#deaths_no_scoreboard_player_changed=8]
of them the player's; the control changes
[metric:e1_agreement/replay@pinned-18#deaths_control_changed=0]. No withheld
channel renames a death
([metric:e1_agreement/landing@store-20#no_scoreboard_renamed=0]), so
withholding exposed no wrong binding. It shows two things. The scoreboard is
the only witness for
[metric:e1_agreement/landing@store-20#no_scoreboard_resolved_to_abstained=75]
victim names. And it makes conflicts visible: without it,
[metric:e1_agreement/landing@store-20#no_scoreboard_contested_to_resolved=16]
contested deaths and
[metric:e1_agreement/landing@store-20#no_scoreboard_disagreement_to_resolved=5]
disagreements read as resolved. Removing a channel hides errors; it does not
expose them.

## The landing's predictions

Ledger `e1-agreement-land-2026-09-28` stated six before the rerun. L1 (no
player K/D moves; the 59c7 key), L2 (the control changes only where the split
adds tracks, then none), L3 (verdict equals `KNOWN_KD`) and L5 (no flagged
round) held. L4 failed: three-way rounds rose by 20, not at most 6, because
the rescanned scoreboard reads more boundaries. L6 held in part: the player's
verdicts still change without the scoreboard, but more verdicts change, not
fewer, because master's collision rule turns the board's conflicting names
into contests rather than removing them.

## The player's review

The store's `analysis/e1-agreement/review-20260928.md` listed the 79 seeded
rounds and eleven extra checks: the cluster-bound rows, the folded panels, the
`59c70f1ef720` death at 1625 s, the rebound rows, and two panels that opened
2 to 2.5 s before their killfeed entry. The player answered them against
source (`labels/e1_review_20260928.jsonl`; the last answer per key counts):
[metric:e1_review/answers@review-20260928#yes=114] of
[metric:e1_review/answers@review-20260928#answers=121] held. Of
[metric:e1_review/answers@review-20260928#events=110] deaths and kills,
[metric:e1_review/answers@review-20260928#events_yes=105] held, and every
binding he checked held. The failures are names and times:

- `223d636bf8d2` (`C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`): four
  names that rest on the killfeed portrait alone. 335.5 s victim Fade, read
  Iso; 721.0 s killer Fade, read Iso; 1028.5 s victim Iso, abstained; 2067.0 s
  victim Clove, read Reyna. The portraits confuse Fade's player
  (`sacrificeursoul`) with Iso, and the name clusters left three of the four
  roles out because both followed views read no name text.
- `c40d950031bb` (`C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`): the
  player's death was booked at 703.5 s, 2.5 s after it happened; at 703.5 s he
  saw Chamber kill Phoenix.
- Extra checks: [metric:e1_review/answers@review-20260928#check_no=2] of
  [metric:e1_review/answers@review-20260928#checks=11] n. At `223d636bf8d2`
  719 s the panel opens after the entry, not before. At `5822b6646448`
  (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`) 1093 s his note says he
  toggled the panel with N [domain:combat_report/appears-on-death], which the
  fold assumes; the n and the note disagree, so the item stays open. He added
  that the report lists its rows newest first
  [domain:combat_report/rows-newest-first] and that the panel toggles, possibly
  into the next buy phase [domain:combat_report/toggle-into-next-buy-phase].

**A y on an extra check confirms the order of events, not their times.** The
player did not time the earlier kills outside each clip (2026-09-28), so no y
answer is timing evidence; the onsets below rest on the crop cache.

### Entry onsets

Measured against the HUD crop cache (2 Hz, its full rate) on
[metric:killfeed_onset/crop-sample@sample-178#items=178] stored onsets (every
review event, every player event near an extra check, three other entries per
session): [metric:killfeed_onset/crop-sample@sample-178#on_time_before=166]
were on time, [metric:killfeed_onset/crop-sample@sample-178#late_0_5_before=9]
one sample late (the fade-in: the victim plate reads at half its colour), and
[metric:killfeed_onset/crop-sample@sample-178#late_2_plus_before=2] seconds
late. No smoothing or confirmation delays an onset: `track_entries` keys a
track at its first detection, so a late onset is frames the reader missed.
The two multi-second cases have two causes:

- At `c40d950031bb` 701.0 s the entry's white text split its plate run in two
  over a dark wall; both halves fell under `MIN_BAND_H`, and the entry was
  absent until 703.5 s. `killfeed._join_split_runs` (`hud-0.16.0`) rejoins
  them. The player's death is now `death:c40d950031bb:701000:0`, killer
  Chamber, and Chamber's kill of Phoenix is its own entry at 704.5 s.
- At `223d636bf8d2` 719.0 s the player's death entry sat in the bottom slot
  behind the Shooting Error box, which hides its weapon icon and victim name;
  it reads only at 721.0 s, when the stack rises. No reader change recovers it.

The HUD was rescanned from the crop cache, then rounds, deaths and the combat
report reran from storage on [metric:e1_review/rerun@store-20#sessions=20]
sessions (backup: the store's
`notes/backup/killfeed-onset-before-hud-0.16.0-20260928/`). At-death panels
whose entry opens 1 s or more after them fell from
[metric:killfeed_onset/panel-lead@store-20#entry_late_1s_before=6] to
[metric:killfeed_onset/panel-lead@store-20#entry_late_1s_after=3] of
[metric:killfeed_onset/panel-lead@store-20#panels=288]; the three left are the
overlay case (`223d636bf8d2` 719 and 1208 s, `b3b9defb6fd7` 1635 s).
[metric:e1_review/rerun@store-20#player_deaths_moved=4] player deaths moved
earlier; the player's counted kills and deaths moved on
[metric:e1_review/rerun@store-20#player_kd_sessions_moved=0] sessions.

### Names

`death-adjudication-0.19.0` lets a name-cluster role whose two followed views
read no name try its other views (`killfeed-name-cluster-0.2.0`).
`223d636bf8d2`'s 335.5 s victim then joins Fade's cluster and is named Fade.
The rerun changed [metric:e1_review/rerun@store-20#victims_changed=10] victims
and [metric:e1_review/rerun@store-20#killers_changed=7] killers and renamed
[metric:e1_review/rerun@store-20#reviewed_yes_renamed=0] items the player
answered y; six of the killers are `587c15b07779` entries that print "Vyse",
now named Vyse, not Fade. Three `223d636bf8d2` names stay wrong: the 721.0 s
killer reads no name text at any view, and the 1028.5 s and 2067.0 s victims'
name crops miss their players' clusters (a one-role and a six-role fragment).

## Open

1. The overlay case: a player death behind the Shooting Error box keeps a late
   onset; the combat report panel's open time is the other witness.
2. `223d636bf8d2`'s three wrong names: name crops that miss their cluster, and
   a killer name read at no view.
3. The scoreboard rescan to `scoreboard-0.10.0` (a decode), then `reticle
   deaths` and `reticle combat-report` again under a new pin.
4. From the branch, unchecked since: `3694746e4e54` and `a06f04a0059f` each
   carry one player death owned by an enemy-victim entry.
5. `cli._combat_report_identity` builds its killfeed tracks with
   `track_entries` and no `sides`, so the report's row naming does not see the
   split; ask the death owner whether it should read `session_entries`.
6. A two-read scoreboard player-row rule, predicted first; `bdfdcf009dba`
   rounds 3 and 4 are its new case.
