# Bootstrap lane B handoff

Status: **review pending**. The [frozen run](../../../.experiment-store/bootstrap-b/frozen-candidate/report.json)
finds a new killer binding in the development slice. The result is a stored-data
retrieval outcome, not an independently validated accuracy claim. The
[source review bundle](../../../.experiment-store/bootstrap-b/review.md) is the
first bounded checkpoint. No production fact or gallery changed.

## Frozen contract

- Branch: `experiment/bootstrap-b`; commit: branch HEAD (the commit hash is
  reported at delivery).
- Committed code baseline: `70d888fdd37327a5041ab419be6c165b96011da2`.
- Development: `a06f04a0059f`, contiguous rounds 3-5. Round 3 alone teaches;
  rounds 4-5 are queries. Provisional transfer: `3694746e4e54`, round 4.
  The independent sealed session named by lane A was not accessed.
- Inputs: each observation, lineup, manifest, geometry, HUD/roster table and
  official gallery file has a SHA256 in the run report. The source content
  keys are pinned there. Input hashes were rechecked before publication.
- Candidate: [candidate.json](../../../.experiment-store/bootstrap-b/frozen-candidate/candidate.json),
  revision `8164052e9fddde22a8b71540ba7fc389a33bec18c293dcc3a804dd9432fd7a9c`.
  This is an array of existing `portrait_exemplars` records. The learner did
  not inspect evaluation truth or harvest from the target session.
- Selection: all entries in the chosen contiguous rounds, with unresolved
  rows retained; a seeded random event and a no-proposal window appear in
  the source bundle. The report records each refusal reason.

## Observed checkpoint

The official gallery baseline abstains on the round-5 killer at 412000 ms.
The adapted pass names Phoenix through the identity arbiter and cites a
round-3 player-HUD anchor. Withdrawing that one anchor leaves the same name,
but its dependency changes to another round-3 player-HUD anchor. Withdrawing
both contributors restores the baseline abstention. The provisional transfer
round does not change. The [lane metrics log](../../../.experiment-store/bootstrap-b/notes/metrics.jsonl)
records counts, costs and the missing accuracy control.

The strict first failure is incomplete transitive lineage. The adapter checks
each harvested portrait against the actual stored observation and owner
verdict, but the existing producer does not record all selection and
association rules that bound a witness to a death. It therefore marks every
anchor's full independence unknown. `tools/identity_loop.py` also passes the
literal session key `S` to the death owner. Its dependent `death:S` IDs are
ambiguous across sessions. A source image shows the player killfeed at the
query, but the required `labelling-pass` skill is absent, so this lane made no
formal label. The review bundle asks the smallest instance question.

The counterexample search kept unresolved query events, conflicts and a
no-proposal window; the report separates them. A synthetic wrong-anchor test
confirms that the arbiter records a learned claim as dependent and retains a
conflicting independent claim. No domain hypothesis was defensible, so no
consumer or withdrawal impact was promoted.

## Commands and next action

Run from this worktree with `C:/Users/grant/reticle/.venv/Scripts/python.exe`:

```powershell
& C:/Users/grant/reticle/.venv/Scripts/python.exe tools/bootstrap_b_run.py --store C:/Users/grant/reticle-store --output .experiment-store/bootstrap-b/UNIQUE-RUN
& C:/Users/grant/reticle/.venv/Scripts/python.exe tools/bootstrap_b_replay.py --store C:/Users/grant/reticle-store --candidate .experiment-store/bootstrap-b/frozen-candidate/candidate.json --session SESSION --rounds ROUND --output .experiment-store/bootstrap-b/UNIQUE-REPLAY
& C:/Users/grant/reticle/.venv/Scripts/python.exe -m unittest discover -s tests -p test_bootstrap_b_run.py -q
& C:/Users/grant/reticle/.venv/Scripts/python.exe -m unittest discover -s tests -p test_domain_learning.py -q
```

Both focused test files pass; the real replay command reproduced the provisional
transfer output. `doctor` returned zero errors; its warnings include an absent
old task read in this fresh worktree. The executable adapter writes only a
lane-local output root and refuses to overwrite one.

Next, add immutable source keys and complete selection/association dependencies
to the existing owner output, then perform controlled source review of the
query. The coordinator can replay this frozen candidate on the sealed session
after checking evidence availability; output agreement alone cannot establish
truth. Stop here before further mining or promotion.

## Recovery note

The first lane worktree under the primary checkout disappeared during this
run. Its uncommitted artifacts were lost. I restored the pinned branch in
`C:/Users/grant/reticle-worktrees/bootstrap-b` and reproduced the finding,
the single-anchor survival and the two-anchor retraction there. Only the
restored artifacts are cited above.
