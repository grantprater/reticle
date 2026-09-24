# Reticle working handoff

## Picking up

**Scoreboard lineups hold across the corpus (2026-09-23).** At `scoreboard-0.5.0` all 19 scoreboard sessions name both sides, and `lineup.load_lineup` constrains the top bar to the board's sets: 170 of 170 slots named in the other 17, with six top-bar names corrected and source-checked ([results](docs/SCOREBOARD_LINEUP.md#corpus-at-scoreboard-050)). Every agent name passes through `adjudication.identity`; `AGENTS.md` states the rule and `doctor` OWNERSHIP plus the event validator enforce it. Next is step 4 in the [backlog](BACKLOG.md): named alive sets.

The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. Historical handoffs and measurements are in [the dated archive](docs/archive/NOTES-through-2026-09-12.md). The [backlog](BACKLOG.md) orders current work; the [working map](docs/WORKING_MAP.md) routes required subsystem reading.
