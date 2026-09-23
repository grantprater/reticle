# Reticle working handoff

## Picking up

**`scoreboard-lineup` passed on 2026-09-23.** Read the [results](docs/SCOREBOARD_LINEUP.md). The scoreboard names each side's five agents and `adjudication.identity` restricts the top-bar assignment to them; `lineup.load_lineup` applies it when a session's scoreboard rows are current (`scoreboard-0.3.0`). Only `a06f04a0059f` and `7010b3d62460` are rescanned. Both name all ten slots correctly, and round 4 names all seven deaths (`teststore/death-round4-lineup/`).

Every agent name passes through `adjudication.identity`; `AGENTS.md` states the rule and `doctor` OWNERSHIP plus the event validator enforce it. `scoreboard-0.5.0` fixes the reader placing the enemy block on the ally block; both rescanned sessions have zero such openings and unchanged results. Next is step 3 in the [backlog](BACKLOG.md): rescan the other 15 scoreboard sessions.

Full suite 609 tests pass; `doctor` 11 findings, zero errors. Development time and token use were not measured.

The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. Historical handoffs and measurements are in [the dated archive](docs/archive/NOTES-through-2026-09-12.md). The [backlog](BACKLOG.md) orders current work; the [working map](docs/WORKING_MAP.md) routes required subsystem reading.
