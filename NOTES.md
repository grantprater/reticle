# Reticle working handoff

## Picking up

**`ability-detection` and `ability-appearance` wired and benchmarked (2026-09-23).** Reticle now identifies ability entities across both circular (smokes, deployables) and linear (walls) archetypes, including the dual-archetype Cypher Trapwire (anchor discs + connecting wire span):
- `detect_ability_discs`, `detect_ability_walls`, and `detect_trapwire_anchors` in `reticle/minimap.py` claim `[owns:ability-detection]` under `status = "partial"`.
- POV corroboration benchmarks (`tools/ability_pov_benchmark.py`, `tools/ability_wall_benchmark.py`) achieve 100.0% recall and 100.0% precision across tray-cast demo sessions.
- Cold temporal tracking (`tools/ability_cold_benchmark.py`) recovers persistent abilities on spectator feeds without HUD trays (92.9% recall on Cypher trapwires, 80-100% on spycam).
- Deterministic glyph & appearance classification in `reticle/adjudication/gallery.py` (`[owns:ability-appearance]`) achieves 21/21 (100.0%) classification accuracy across smokes, deployables, and walls using harvested exemplar reference assets.

Domain facts expanded to 43 in `domain/abilities.toml` with `subject` indexing. Full test suite passes (626 tests); `reticle doctor` has 9 findings (down from 11), 0 errors.

**Scoreboard lineups hold across the corpus (2026-09-23).** At `scoreboard-0.5.0` all 19 scoreboard sessions name both sides, and `lineup.load_lineup` constrains the top bar to the board's sets: 170 of 170 slots named in the other 17, with six top-bar names corrected and source-checked ([results](docs/SCOREBOARD_LINEUP.md#corpus-at-scoreboard-050)). Every agent name passes through `adjudication.identity`; `AGENTS.md` states the rule and `doctor` OWNERSHIP plus the event validator enforce it. Next is step 4 in the [backlog](BACKLOG.md): named alive sets.


The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. Historical handoffs and measurements are in [the dated archive](docs/archive/NOTES-through-2026-09-12.md). The [backlog](BACKLOG.md) orders current work; the [working map](docs/WORKING_MAP.md) routes required subsystem reading.
