# Reticle working handoff

## Picking up

**Task `death-scoreboard-binding` passed on 2026-09-23.** The real round emits seven deaths with four correct machine names (Deadlock, Reyna, Miks, Phoenix), three enemy identity refusals, and seven location refusals. Read the [resolution](docs/DEATH_SCOREBOARD_BINDING.md#resolution--scoreboard-agent-and-dimming-witness). The first failure was the stored portrait box, which sat inside the slab. `scoreboard-0.2.0` scores the table-edge cell against official agent art; `adjudication/scoreboard.py` gates whole openings and reads dimmed portraits as dead [domain:rounds/scoreboard-dead-dimmed]. Only `a06f04a0059f` was rescanned under 0.2.0; other sessions still hold 0.1.0 rows, and the gates rest on one round.

Next candidate, with no contract yet: `scoreboard-lineup` in the [backlog](BACKLOG.md). The board names enemy Killjoy where the lineup accepts Clove. The enemy pair at 284500/295500 ms stays unordered {Jett, Skye}.

Full suite 596 tests pass; `doctor` 11 findings, zero errors. Development time and token use were not measured.

The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. Historical handoffs and measurements are in [the dated archive](docs/archive/NOTES-through-2026-09-12.md). The [backlog](BACKLOG.md) orders current work; the [working map](docs/WORKING_MAP.md) routes required subsystem reading.
