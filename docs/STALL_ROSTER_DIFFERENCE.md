# Deaths inside an in-round capture stall: the roster difference

Status: proposed (2026-10-04). Owner when built: `adjudication.death`
(`infer_stall_deaths`), its identity through `adjudication.identity`.

## The gap this closes

While the capture stalls, the killfeed is not sampled, and an entry whose
five-second life [domain:killfeed/entry-lifetime] ends inside the stall is
never drawn. `infer_stall_deaths` (`death-adjudication-0.34.0`) already
infers the deaths of a round that ended by elimination inside the gap. It
says nothing about a gap the round outlives. On the 21 Riot-scored matches the
scorer counts 12 Riot kills as unobservable inside a stall (riot-truth-0.4.1,
stored deaths at `death-adjudication-0.34.0`):

| Session | Stall (s) | Round ends in gap | Riot kills in gap | Covered now by |
|---|---|---|---|---|
| 3694746e4e54 | 1149.0-1220.6 | yes (ally eliminated) | Jett, Miks, Reyna, Vyse (ally); Reyna, Gekko, Cypher (enemy) | inferred: the 4 allies; nothing for the 3 enemies |
| bfad2778a372 | 2329.0-2358.5 | yes | Fade (ally); Miks (ally) 0.3 s before the stall, counted missed | inferred: both |
| bfad2778a372 | 588.2-616.0 | no | Miks (ally) | nothing |
| 59c70f1ef720 | 2192.4-2215.8 | no | Breach (enemy) | nothing |
| bdfdcf009dba | 1758.0-1774.0 | no | Clove (ally) | nothing |
| b3b9defb6fd7 | 1331.4-1339.6 | no | Waylay (enemy) | the entry drawn at release (1339.5 s), which names no victim |

Capture paths: 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`;
bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; 59c70f1ef720
`C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; bdfdcf009dba
`C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; b3b9defb6fd7
`C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`.

The three enemies of 3694746e4e54 round 12 died in a gap that also ended the
round; after release the next round's full roster shows, so no living-set
difference can see them. Only a per-player death count read before and after
(the scoreboard's deaths column, the combat report) observes them. They stay
out of scope here.

## The rule

For each stall `[a, b]` inside a round whose stored end lies after
`b + STALL_ROUND_END_SLACK_MS`:

1. **Counts.** `n_before[side]`: the roster reader's last living count in
   `[t_start, a)` (`_roster_before`); `n_after[side]`: the median of its first
   three counts in `(b, b + 1.5 s]`. Refuse the gap as `roster_unread` when
   either is missing, and as `prior_count_disagrees` when `n_before` differs
   from the killfeed prior's living set (`build_round_roster_timeline`), as
   the round-end rule does.
2. **Explained drops.** Subtract every death verdict drawn at the release
   (`released` equal to this span, or first seen in `(a, b + one sample]`)
   on that side, and add back every revive drawn there. A side whose
   remainder is zero infers nothing; a negative remainder refuses the gap as
   `release_entries_exceed_drop`.
3. **Who.** The candidates are the prior living set less the victims the
   release entries named. When the remainder equals the candidates' count,
   every candidate died. Otherwise the deaths stay unnamed (`victim: null`,
   `victim_reason: "roster_count_only"`, `candidates` listed) unless a second
   channel names the survivors: for allies, the minimap ally icons present
   after release (`ally_icon`); for enemies, a scoreboard opening's dimmed
   rows. A name by elimination `depends_on` the prior's deaths, as now.
4. **Rows.** One `inferred_death` row per death: `t_ms: null`,
   `t_window_ms: [a, b]`, `rule: "roster_difference"`, `rests_on` the two
   roster samples, the release verdicts and the prior. Rows stay in
   `set_aside`; no `death_verdict` consumer reads them, as for the round-end
   rule.

The roster drop is the cross-reference; the killfeed prior and the release
entries are the explained part. Neither side's count is tuned.

## Predictions

Logged with the design in the store's `notes/predictions.jsonl`
(`riot-residuals-20261004`, subject `stall_roster_difference`).

- D1. bdfdcf009dba 1758.0-1774.0 s: ally 2 -> 1, no release entry: one ally
  death, named Clove only through the ally icons.
- D2. bfad2778a372 588.2-616.0 s: ally 4 -> 2 with one released ally entry
  (Chamber): one more ally death, Riot's Miks; enemy 5 -> 2 with three
  released enemy entries: none.
- D3. 59c70f1ef720 2192.4-2215.8 s: enemy 5 -> 1; the entries first seen
  inside the span (Chamber and Phoenix at 2197.0 s) and at its release
  (Killjoy, 2216.0 s) explain three, leaving one, Riot's Breach.
- D4. b3b9defb6fd7 1331.4-1339.6 s: enemy 4 -> 3, explained by the 1339.5 s
  release entry: nothing inferred.
- D5. Over the 21 matches the rule infers no death Riot lacks, and refuses
  rather than names wherever the counts disagree.

Falsifier for each: the counts or the explained remainder differ from those
stated, or an inferred death pairs with no Riot kill.
