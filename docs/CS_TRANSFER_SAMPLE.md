# Counter-Strike transfer sample

Status: proposed, 2026-10-04. A scout of published Counter-Strike data for a
baseline that tests what transfers to VALORANT ladder play: coarse-state round
win probability (alive counts, bomb, time), trade timing, and how both shift
with skill. It complements `docs/WIN_PROBABILITY_RESEARCH.md`, whose
**Transfer** risk says CS:GO coefficients may misstate ranked play; this
sample measures that risk instead of assuming it.

Use: these records fit win-probability and coaching baselines and priors.
They never feed a reader, a reader's threshold, or anything shown during
play. A fit that uses them declares `rests_on` them; a model is scored only on
VALORANT matches held out of its fit.

## Sources

Sizes marked "measured" were read on 2026-10-04 from the host's file listing
or a downloaded file; "unverified" marks a claim taken from a description.
`prototypes/cs_scout_tables.py --record` recomputes every cited figure from
the stored files and writes the `cs_scout/*` rows of the store's
`notes/metrics.jsonl`; host listing sizes are quoted as listed, uncited. The
one ESTA demo was deleted after its row was recorded.

| Source | Holds | Format | Total size | Useful subset | Terms | Skill levels |
|---|---|---|---|---|---|---|
| ESTA (pnxenopoulos/esta on GitHub) | 1,558 parsed CS:GO demos, 41,782 rounds: rounds, kills (with `isTrade`), damages, bomb events, grenades, 2 Hz frames with every player's position, view, HP, inventory | one `.json.xz` per demo, awpy 1.3.1 schema | 3.9 GB (README; unverified); one demo measured 2,841,300 B compressed [metric:cs_scout/esta_demo#xz_bytes=2841300], 75,798,671 B decompressed [metric:cs_scout/esta_demo#json_bytes=75798671], 30 rounds [metric:cs_scout/esta_demo#rounds=30], 168 frames in round 1 [metric:cs_scout/esta_demo#frames_round1=168] | 100 online demos, about 284 MB compressed (100 times the measured demo), parsed to tables then discarded | CC BY-SA 4.0 | professional only (HLTV matches, online and LAN) |
| Kaggle "CS:GO Competitive Matchmaking Data" (skihikingkevin) | damage and grenade events, per-round metadata; ESEA part plus a matchmaking part | CSV | 3,624,699,821 B (measured, Kaggle API) | `mm_master_demos.csv` 283,128,379 B (measured listing) carries `att_rank`, `vic_rank`, `avg_match_rank` (Kaggle description; columns unverified) | CC BY-NC-SA 4.0 | matchmaking ranks (unverified spread); ESEA part has no rank |
| HF mirror HeadShottt/CS-GO | parquet re-upload of the Kaggle ESEA part: `kills` (with `ct_alive`, `t_alive`, `is_bomb_planted`, `seconds`), `meta` (winner, round type, equipment), `dmg`, `grenades` | parquet | 39 files, about 1.42 GB (measured listing) | `kills.parquet` 39,779,560 B [metric:cs_scout/esea#kills_parquet_bytes=39779560] + `meta.parquet` 6,295,282 B [metric:cs_scout/esea#meta_parquet_bytes=6295282], both downloaded | no licence stated; the Kaggle original's CC BY-NC-SA applies | none: every file is ESEA, `att_rank` and `vic_rank` are 0 [metric:cs_scout/esea_ranks#att_rank_max=0] in all 14,927 demos [metric:cs_scout/esea_ranks#demos=14927] |
| Kaggle "CS:GO Round Winner Classification" (christianlillelund) | 122,411 snapshots every 20 s from about 700 tournament demos: time left, alive, HP, money, weapons, bomb | CSV | 50,410,839 B (measured, Kaggle API) | whole file | CC0 | professional only |
| awpy (CS2 parser, MIT) | parses a CS2 `.dem` into rounds, kills, damages, bomb, grenades, smokes, infernos, shots, footsteps, ticks | Polars frames | n/a (a library, ships no data) | per parsed match, kept tables only (size unverified) | MIT | whatever demos it reads |
| FACEIT Data API + Downloads API | match details (`demo_url`), per-round match stats, player `skill_level` 1-10 and Elo, player history | JSON; CS2 `.dem` behind signed URLs | demo size unverified (tens to hundreds of MB each, per the brief) | 20 matches per level | Data API needs a key; demos need a Downloads API scope granted by application, about 30 days' response | FACEIT levels 1-10 |
| HLTV demos | professional match demos | `.rar` of `.dem` | unverified | none proposed; ESTA already covers pro play parsed | site terms; no API | professional only |

Not found: a published, pre-parsed CS2 table set spanning matchmaking ranks or
FACEIT levels. Hugging Face searches for "cs2" and "csgo" return detection,
video and world-model sets, none with round tables and skill levels.

## Measured on the ESEA tables

Predictions C1-C5 and their outcomes are logged in the store's
`notes/predictions.jsonl` under task `cs-scout-20261004`.

- Coverage: 377,629 rounds [metric:cs_scout/esea#rounds=377629] in 14,921 demos
  [metric:cs_scout/esea#demos=14921]; 2,742,646 kills [metric:cs_scout/esea#kill_rows=2742646], 98.4%
  [metric:cs_scout/esea#join_share=98.4%] of which join a round's winner. 430 kill rows
  [metric:cs_scout/esea#negative_alive_rows=430] carry negative alive counts; drop them.
- After a round's first kill, before a plant, the side left with five wins
  0.703 [metric:cs_scout/esea#first_kill_side5_win=0.703] of 376,535 rounds
  [metric:cs_scout/esea#first_kill_rounds=376535].
- Coarse win probability by alive counts after a kill, CT share of wins: 4v4
  0.47 [metric:cs_scout/esea#ct_win_4v4_noplant=0.47] without a plant, 0.23
  [metric:cs_scout/esea#ct_win_4v4_plant=0.23] with one; 2v2 0.49
  [metric:cs_scout/esea#ct_win_2v2_noplant=0.49] and 0.30
  [metric:cs_scout/esea#ct_win_2v2_plant=0.30]; 1v1 0.55
  [metric:cs_scout/esea#ct_win_1v1_noplant=0.55] and 0.33
  [metric:cs_scout/esea#ct_win_1v1_plant=0.33]. The 4v4 planted state rests on
  2,175 kill rows [metric:cs_scout/esea#n_4v4_plant=2175].
  A plant is worth about a quarter of a round in even states.
- Trade timing, without player ids: the next kill in a round kills the side
  that just scored in 52.3% [metric:cs_scout/esea#refrag_share=52.3%] of 2,358,756
  consecutive pairs [metric:cs_scout/esea#next_kill_pairs=2358756], within 5 s in 30.3%
  [metric:cs_scout/esea#refrag_5s_share=30.3%]; the median gap of those refrags is 3.86 s
  [metric:cs_scout/esea#refrag_gap_median_s=3.86]. ESTA's `isTrade` and the
  matchmaking set's `att_id` would give true trades.

These tables carry no skill level, so they cannot show a shift with rank.

## Proposed sample (hard budget 2 GB; this plan keeps under 1 GB)

| Stratum | Source | Kept on disk | Status |
|---|---|---|---|
| Amateur and semi-pro | ESEA `kills` + `meta` | 46 MB (downloaded) | done |
| Matchmaking ranks | Kaggle `mm_master_demos.csv`, converted to zstd parquet, raw CSV deleted | 283 MB transient; parquet estimate 60-100 MB (unverified) | needs the player's Kaggle API token and approval of a 283 MB download |
| Professional | ESTA, 100 online demos parsed to rounds, kills and 2 Hz alive/bomb/clock frames; `.xz` deleted after parsing | about 284 MB transient (100 times the measured demo); tables estimate under 50 MB (unverified) | needs approval for about 284 MB |
| CS2, FACEIT levels 1-10 | 20 matches per level, one demo at a time through awpy; keep rounds, kills, bomb and 2 Hz positions; delete each `.dem` | estimate 200-500 MB (unverified) | needs a Downloads API grant (about 30 days) and an awpy install; defer |

Download one source at a time, at Below Normal priority, single-threaded,
with parsing vectorised in pyarrow or numpy.

## What it lets us measure

1. Coarse-state round win probability, P(win | alive counts, bomb, time
   left), per stratum. Compare its shape with the same table fitted on the
   VALORANT match records; the transfer test fits on CS and scores log loss on
   held-out VALORANT matches against a VALORANT-only fit and the gambler's
   ruin baseline. Accept CS only as a weak prior if it helps at small
   VALORANT sample sizes.
2. First-kill conversion and the plant's value per stratum, against the same
   statistics in the player's three accounts and the ladder snowball.
3. Trade timing: refrag share and gap per stratum (true trades from ESTA and
   the matchmaking ids), against VALORANT's killfeed-derived trades.
4. Skill gradient: whether each statistic moves monotonically from Silver to
   professional; if CS shows a gradient and VALORANT's ladder sample shows the
   same direction, the gradient transfers; disagreements are stored.

## Not done

- No matchmaking-rank data downloaded: the mirror lacks it, and the Kaggle
  file needs an account token and exceeds this scout's 200 MB limit.
- No CS2 demo parsed and no awpy install; CS2 parsed sizes are estimates.
- No FACEIT key or Downloads API application.
- No VALORANT comparison run yet.
