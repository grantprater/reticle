# Backlog entries retired on 2026-09-28

`e1-agreement` completed, and the open item `BACKLOG.md` held for it is below as it stood. `revive-plate-witness` left the completed list to keep its five latest; its full text is in the [09-27 archive](BACKLOG-through-2026-09-27.md).

- **`e1-agreement` (2026-09-28):** `prototypes/e1_agreement.py --replay` read 18 pinned sessions from storage (one refused): of 353 rounds, 59 agreed three ways, 9 disagreed, each by a stored reason, and 19 had fewer than two channels. Two agreeing rounds left the player's death panel unbound because the combat report's owner called it at-death by one window and bound by another; one window, `near_death` (`combat-report-round-0.9.0`), binds both and exposed four panels whose two KILLED YOU rows both bound to the later death's killer; those rows now bind neither. The player's source review of the seeded rounds and the corpus replay at scoreboard-0.9.0 remain ([findings](../E1_AGREEMENT.md)).

The retired open item:

**E1: can agreement conceal a wrong event history? (next, 2026-09-27).** First experiment of [the experiment program](../EXPERIMENT_PROGRAM.md): the combat report, killfeed and scoreboard are all in production and its falsifier is concrete. From storage only, list every round where the three channels disagree, by the stored reason; then seed rounds whose totals agree, bind each death to its source witness, identity and life episode, and withhold each channel in turn. Belief, falsifier and acceptance: ledger entry `e1-agreement-2026-09-27`.
Acceptance: `.\.venv\Scripts\python.exe prototypes\e1_agreement.py --replay` writes both lists from storage with no decode and records `e1_agreement/replay` through `reticle.metrics`.
Evidence: the player reviews the seeded agreeing rounds against source before anything is promoted; any source error there refutes agreement as an acceptance test. Stop at the first upstream identity failure; promote no oracle candidate or all-null output.
