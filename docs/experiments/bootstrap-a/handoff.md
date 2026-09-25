# Bootstrap Lane A: Independent Evaluation Handoff

## Summary

Lane A executed the independent evaluation protocol defined in `docs/BOOTSTRAP_PARALLEL_RUN.md`. We isolated execution in worktree `C:/Users/grant/reticle-worktrees/bootstrap-a` on branch `experiment/bootstrap-a`, using lane-local experiment store `C:/Users/grant/reticle-worktrees/store-bootstrap-a`. All production store inputs remained read-only. We implemented 1-to-1 event alignment with temporal tolerances, validated duplicate-plus-miss cancellation detection, completed a cross-channel death audit and ablation on `a06f04a0059f` Rounds 3-6 (34 death opportunities), and delivered a versioned evaluation specification (`reticle-eval-0.1.0`) with sealed transfer partition `a1a995e6b19b`.

## Owned Files

- `tools/bootstrap_a_eval.py`: Evaluation engine, 1-to-1 event alignment, ablation runner, and audit generator.
- `tests/test_bootstrap_a_eval.py`: Unit test suite (7 tests, all passing in 0.001s).
- `docs/experiments/bootstrap-a/manifest.json`: Pinned baseline manifest with SHA-256 hashes of code and stored data.
- `docs/experiments/bootstrap-a/task_contract.json`: Executable local task contract.
- `docs/experiments/bootstrap-a/eval_spec.json`: Versioned evaluation specification for Lane B candidate.
- `docs/experiments/bootstrap-a/audit_report.md`: Markdown audit report detailing event correspondence and ablations.
- `docs/experiments/bootstrap-a/cost.json`: Measured runtime costs and compute profile.
- `docs/experiments/bootstrap-a/result.json`: Prescribed machine-readable result payload.
- `docs/experiments/bootstrap-a/handoff.md`: This handoff document.

## Key Findings

1. **Count Agreement Conceals Event Discrepancies**:
   Synthetic cancellation tests confirm that identical round totals can hide concurrent missing and spurious events. The 1-to-1 evaluator detects this condition as non-zero error, correctly reporting precision and recall degradation.

2. **Cross-Channel Death Audit (`a06f04a0059f` Rounds 3-6, 34 Deaths)**:
   - **Fully Agreed**: 10 deaths (29.4%) have matching victim identity across Killfeed and Scoreboard.
   - **Single-Channel Rescues**: 19 deaths (55.9%) depend entirely on one channel because the other refused:
     - Killfeed rescues Scoreboard in 16 deaths.
     - Scoreboard rescues Killfeed in 3 deaths: Jett at 284.5s (Round 4), Miks at 295.0s (Round 4), and Breach at 443.0s (Round 5).
   - **Explicit Abstentions**: 5 deaths (14.7%) where both channels refused, preserved as `abstained` with concrete reasons rather than guessed.

3. **Ablation Results**:
   - **Withholding Scoreboard**: Resolved victim accuracy drops to 89.7%; 3 verified deaths are lost.
   - **Withholding Killfeed**: Resolved victim accuracy drops to 44.8%; 16 verified deaths are lost.

4. **Combat Report Corroboration**:
   Combat report player death panels match killfeed player death events on all 4 rounds (Round 3: 1, Round 4: 1, Round 5: 0, Round 6: 1). Run It Back deaths in later rounds (Rounds 16, 20, 23) correctly separate into second-life events without distorting permanent death counts.

5. **First Failure**:
   Event `death:a06f04a0059f:176500:0` in Round 3 at 176.5s. Killfeed refused due to `portrait_views_refused_or_disagree`; Scoreboard refused due to `newly_dim_2_disagrees_with_killfeed_deaths_3`.

6. **Review Bundle**:
   Generated 5 player questions covering the unobserved enemy deaths in Rounds 3 and 6, presenting alternatives and a `cannot_tell` choice.

## Evaluation Specification and Partition Policy

`docs/experiments/bootstrap-a/eval_spec.json` defines evaluation rules for Lane B's candidate:
- 1-to-1 event alignment with temporal tolerance $\Delta t \le 2500$ ms.
- Property denominators explicitly penalizing candidate abstentions and misattributions.
- Partition `a1a995e6b19b` (Sunset, 24 rounds, 191 deaths) remains sealed from learning.

## Verification Commands

```powershell
# Run evaluator tests
.\.venv\Scripts\python.exe -m unittest tests/test_bootstrap_a_eval.py -v

# Run dev slice audit and verify markdown output
.\.venv\Scripts\python.exe tools/bootstrap_a_eval.py --audit --slice a06f04a0059f:3-6

# Validate evaluation specification
.\.venv\Scripts\python.exe tools/bootstrap_a_eval.py --validate-spec docs/experiments/bootstrap-a/eval_spec.json

# Check repository health
.\.venv\Scripts\python.exe -m reticle doctor
```

## Smallest Next Action

Relay `docs/experiments/bootstrap-a/handoff.md`, `result.json`, commit hash, and artifact paths to the coordinating session. When Lane B freezes its candidate revision, evaluate that candidate using `tools/bootstrap_a_eval.py` against `eval_spec.json` on the sealed partition `a1a995e6b19b`.
