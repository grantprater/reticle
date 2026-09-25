# Bootstrap integration handoff

Branch `experiment/bootstrap-integration` starts at production commit
`3df93ccce95e0e684b86d6e07bb86911c72ba247`. `result.json` points to the
branch ref for the final commit. The [manifest](manifest.json) pins the frozen learner, lane
reports, current production streams and immutable local replay outputs. The
production streams match Lane A's old hashes; current combat report acceptance
postdates both lane code bases. No production store input or frozen candidate
was changed.

The [production-entry replay](../../../.experiment-store/bootstrap-integration/production-replay-001/report.json)
finds no learner change on the development slice. Production's `session_entries`
constructs the query death in slot 1, and the current death owner already names
Phoenix as killer there. The [legacy replay](../../../.experiment-store/bootstrap-integration/dev-replay-005/report.json)
reproduces Lane B's new name in slot 0, but that entity is absent from the
accepted death stream. The old adapter used a per-round entry extractor and
created a different correspondence. Withdrawing its direct anchor leaves
another teaching death; withdrawing both restores its abstention. This is a
historical adapter result, not an incremental production binding. The
[provisional production-entry transfer](../../../.experiment-store/bootstrap-integration/production-transfer-001/report.json)
also has no change. Source accuracy remains unmeasured.

The frozen exemplar revision was left intact. The bounded adapter translates
its placeholder `death:S` dependencies to teaching-session keys in memory.
Its source observation keys and independent witness claims resolve, while
transitive selection and association dependencies remain absent. The replay
records that gap for every anchor. The production-entry replay's event keys
match the current stored death stream across the selected rounds.

`tools/bootstrap_compare.py` accepts `--reference`, `--candidate`, `--spec`
and `--output`. It uses exact maximum-cardinality event matching within the
bounded scope, reports ambiguous equal-cost associations, and separates wrong,
unresolved, unobservable and unscored properties. A source-accuracy run requires
an independent review revision. The executable [comparison](../../../.experiment-store/bootstrap-integration/production-replay-001/comparison_report.json)
against the current baseline is explicitly `stored_agreement` and records no
candidate change. Lane A's historical
ablation figure is baseline agreement and must not be reused as accuracy.

The [source review question](review.md) is ready. The repository's
`labelling-pass` skill was found and read. No new labels were made. The saved
query frame still needs a player answer that binds the visible rows to the
production slot and establishes whether they are distinct deaths. Production
acceptance has already used Lane A's sealed session;
it remains learner held out but cannot serve as a fresh system-development
holdout. A later generalization test needs fresh source.

Stored combat report identity disagreements carry `conflicting_claims`. Most
pit `scoreboard_kd` against a killfeed-derived name. `death_verdict` often
inherits that same name, so counting it as another witness would inflate
support. The smallest follow-up is one source panel and its Tab opening for
`combat_report:223d636bf8d2:portrait:2`, testing the row association before
any rule change. No detector, gallery or domain fact was promoted.

Verification used the repository venv from this worktree. Focused comparator,
Lane B adapter and production death attribution tests passed. Development and
provisional transfer replay commands completed; `bootstrap_compare.py`
completed against generated reference/candidate/spec files. `reticle doctor`
returned zero errors. Its warning about a missing historical death-refusals
read comes from this fresh worktree; the other findings were already present
at pickup. Commands:

```powershell
C:/Users/grant/reticle/.venv/Scripts/python.exe -m unittest discover -s tests -p test_bootstrap_compare.py -q
C:/Users/grant/reticle/.venv/Scripts/python.exe -m unittest discover -s tests -p test_bootstrap_b_run.py -q
C:/Users/grant/reticle/.venv/Scripts/python.exe -m unittest discover -s tests -p test_death_attribution.py -q
C:/Users/grant/reticle/.venv/Scripts/python.exe tools/bootstrap_b_replay.py --store C:/Users/grant/reticle-store --candidate C:/Users/grant/reticle-worktrees/bootstrap-b/.experiment-store/bootstrap-b/frozen-candidate/candidate.json --session a06f04a0059f --rounds 3 4 5 --output .experiment-store/bootstrap-integration/production-replay-001
C:/Users/grant/reticle/.venv/Scripts/python.exe tools/bootstrap_compare.py --reference .experiment-store/bootstrap-integration/production-replay-001/comparison_reference.json --candidate .experiment-store/bootstrap-integration/production-replay-001/comparison_candidate.json --spec .experiment-store/bootstrap-integration/production-replay-001/comparison_spec.json --output .experiment-store/bootstrap-integration/production-replay-001/comparison_report.json
C:/Users/grant/reticle/.venv/Scripts/python.exe -m reticle doctor
```
