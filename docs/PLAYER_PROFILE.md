# Player profile

Status: live, 2026-10-04. `prototypes/player_profile.py` describes the
player's competitive history against the other players in the same matches.
It is descriptive: each difference it reports is a hypothesis for the
decision-value models, never a verdict. It feeds no reader, no reader's
threshold and nothing shown during play.

## Privacy

The player's statistics are private. The run writes `profile-v2.json` and
`report-v2.md` only to `<store>/analysis/player-profile-20261004/`, beside
the first run's `profile.json` and `report.md`, and refuses to overwrite an
existing file. This file
and the code carry no player numbers. Account ids, Riot IDs, match ids and
pseudonyms stay in the store, and peers appear only pooled, never one by
one.

## Sources

- The player's HenrikDev v4 history (`external/ladder/henrikdev/v4/raw`,
  [LADDER_SAMPLE.md](LADDER_SAMPLE.md)), read through
  `ladder_fetch.stored_matches`.
- The captured competitive matches' Riot records (`external/riot/`), carried
  into the v4 shape by `ladder_fetch.riot_to_v4`; unrated records are
  skipped.
- Both pass through `ladder_fetch.parse_matches` with the store's salt. The
  parser drops damage events and ability casts, so `extras_v4` reads those
  two fields from the same records, and `riot_extras_v4` renames Riot's.
- The player's accounts (labels A, B, C) come from
  `ladder_fetch.owner_accounts`, which includes
  `riot_ground_truth.identify_player`.
- Excluded: matches with a kept replay and no capture
  ([REPLAY_KEEPING.md](REPLAY_KEEPING.md)); the report counts them.

## Comparison

Every metric is a ratio of summed counts: the player's numerator over their
denominator, against the same ratio pooled over every other player in the
same matches. Matches are the resampling unit: the interval is the 2.5th and
97.5th percentiles over match resamples, and the player's and the peers'
ratios share each draw, so the difference keeps their correlation. A metric
whose player denominator holds fewer than 30 events is flagged `LOW n`.

The report ranks the three strongest signals: rankable pooled metrics with
enough events and an interval for the difference that excludes zero, by
the difference over the interval's half-width, one per family. With some
forty metrics, about two intervals exclude zero by chance alone.

## Metrics

| Family | Metric | Numerator / denominator |
| --- | --- | --- |
| fragging | `kills_per_round`, `deaths_per_round`, `kd` | kills, deaths, rounds |
| fragging | `adr` | damage to enemies / rounds |
| fragging | `hs_share` | headshots / all hits |
| fragging | `kast` | rounds with a kill, assist, survival or traded death / rounds |
| multikill | `mk2_rate`, `mk3_rate` | rounds with 2+ or 3+ kills / rounds |
| opening | `opening_involvement` | first kills plus first deaths / rounds |
| opening | `opening_win` | first kills / (first kills + first deaths) |
| opening | `first_kill_rate`, `first_death_rate` | per round |
| trade | `traded_share` | deaths to enemies traded / deaths to enemies |
| trade | `traded_share_3s`, `traded_share_7s` | the same at 3 s and 7 s |
| trade | `untraded_deaths_per_round`, `trades_per_round` | per round |
| spacing | `near_mate_m`, `near_mate_m_untraded` | nearest listed teammate at death (m) / deaths with one listed |
| spacing | `isolated_death_share` | deaths with every listed teammate beyond `ISOLATED_CM` / deaths with at least one listed teammate |
| clutch | `clutch_rate` | rounds in a 1vX / rounds |
| clutch | `clutch_win`, `clutch_win_1v1`, `clutch_win_1v2plus` | won / attempted |
| postplant | `plants_per_attack_round`, `defuses_per_defense_plant` | per round on that side |
| postplant | `pp_death_attack`, `pp_death_defense`, `pp_kills_*` | per round alive at the plant, by side |
| economy | `buy_vs_mates` | own loadout minus teammates' mean (non-pistol) |
| economy | `offsync_buy`, `offsync_save` | full buy while teammates save, and the reverse |
| economy | `eco_win`, `force_win`, `full_win`, `pistol_win` | rounds won in that buy band |
| economy | `death_rate_high_loadout` | rounds died in / rounds with own loadout in the full band |
| utility | `casts_<slot>_per_round`, `casts_per_round` | ability casts (match totals) / rounds |
| utility | `assists_per_cast`, `kills_assists_per_cast` | ratio of totals |
| outcome | `round_win` | rounds won / rounds |

Pooled utility compares agents unlike the player's, so it is not ranked; by
agent, the peers are those who played the same agent.

Groups: side (round level), map, agent, account, season, month, lobby rank
band (the parser's `stratum`) and source, for the headline metrics. Casts are
match totals, so the side group, which splits a match, carries no cast
metric: the first run booked each match's casts on whichever side row sorted
first.

## Definitions and choices

- Rounds: every round in the record except surrendered ones.
- Opening duel: the round's first kill between teams.
- Trade: a death is traded when its killer dies to the victim's team within
  `TRADE_WINDOW_MS`, 5 s. No domain fact records a window; the choice is
  the module's.
- Distance at death: the victim's location against the teammates a kill
  lists. A kill lists only some players, so an unlisted teammate may be
  alive; deaths with no listed teammate stay out of the distance metrics.
- Clutch: the first kill state before the round's decision where the
  player is their team's only living player and an enemy lives, from
  `winprob_reference.simulate` (living sets with revives).
- Sides: the sides swap at halftime [domain:rounds/halftime-side-swap],
  whose owner is `reticle/rounds.py`. The module asks that owner's rule by
  round number (`rounds.side_in_round`, [domain:rounds/side-by-round]) with
  Red starting on attack: Red attacks rounds 0 to 11 and the even overtime
  rounds. Round 12 is the first after halftime
  [domain:rounds/pistol-round-bank]. The report checks the rule against
  Riot's `winningTeamRole` and against every planter's team.
- Buy bands by the team's mean loadout: eco below 2000, force from 2000,
  full from 3900, a choice. Pistol rounds are rounds 0 and 12, the first
  round and the first after halftime [domain:rounds/pistol-round-bank].

## Command

    .\.venv\Scripts\python.exe prototypes\player_profile.py run [--boot N]

`tests/test_player_profile.py` checks each count on synthetic matches.
