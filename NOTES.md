# Reticle working handoff

## Picking up

**Task `death-refusals`: diagnose the five remaining identity refusals in `a06f04a0059f` round 4.** The fixed round is 232000–351000 ms. Keep the [two-name portrait review](teststore/death-round4-portraits/review-summary.md) as the baseline and inspect the first independent evidence gap before changing a portrait rule. The [contract](docs/tasks.json) requires source review of each refusal and an explicit bounded next fix or player question path.

The `death-portraits` contract passed. The shared `scan --only hud` pass persisted 3,392 versioned raw portrait observations. The fixed round has seven source-reviewed deaths, zero misses or extras in that set, two correct named victims (Reyna and Phoenix), five identity refusals, and zero verified locations. Reyna's two stored portrait views both name her; the source frame visibly agrees. Refused lineup rivals and all per-view scores remain in event witnesses. The [review summary](teststore/death-round4-portraits/review-summary.md) compares the prior one-name baseline. Focused and full tests pass (25 and 589); `doctor` remains at 11 findings, zero errors.

Task record: accepted; seven required reading routes were selected, with relevant sections inspected. The measured correction is one additional correct name and one fewer refusal; the real seven-event output and approved source frames were reviewed. Total development time and token use were not measured.

**First remaining gap:** Deadlock is the best portrait match at 281500 ms but her lineup slot is refused. The 284500 ms portrait offers only one named view among four, and the source shows a different victim; 295000 ms has only one view. Do not turn either into a name by lowering the portrait margin or counting lineup `best_guess` as accepted identity. Check other stored channels and source evidence for the five refusals; if identity still cannot be derived, ask the player and record the first failure.

The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. Historical handoffs and measurements are in [the dated archive](docs/archive/NOTES-through-2026-09-12.md). The [backlog](BACKLOG.md) orders current work; the [working map](docs/WORKING_MAP.md) routes required subsystem reading.
