# Reticle working handoff

## Picking up

**2026-10-06, evening.** Master stands at `67a55ad`, pushed. The [backlog](BACKLOG.md) order is: define the coaching questions, then build the slot model to answer them; the ally-icon cost by fidelity; the spelling owner's remainder. The morning handoff is [archived](docs/archive/NOTES-2026-10-06-morning.md).

### The player's frame, set today

Fidelity follows the question (AGENTS.md). Readers hold coarse beliefs and read in full only where an opportunity opens, gated first on "an enemy is visible", never on outcomes; fidelity works like attention, one focus at a time with the player's own engagement first. Enemy information is a last-seen position whose reachable set grows with time, is pruned by the team's vision, and collapses to unknown once it covers the map; map control is the area the enemy cannot enter unseen, and its holes are coaching opportunities; cross-round habits are priors. Acceptance is question answers from a vision timeline against replay answers ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md)); damage-only fights are in scope through the combat report; enemy-side questions are beliefs outside acceptance. The player expects 95%+ savings over today's readers and real time with no noticeable cost, stretch goal under 1 ms per frame. Everything sits on the slot model (docs/ENTITY_STATE.md), whose step 1 is not built.

### Running at handoff

- **`coaching-questions-20261006`** (branch cut from `question-acceptance-20261006`): the question catalogue on the replays and Riot records; the truth-degradation sweep (enemy-visible gate, attention arm, last-seen sets pruned by team vision, map control and holes); the acceptance plan's revisions (QA5/QA6 revision rows, the cost target). Its report decides the next build.

### Merged today

- **Spelling owner** (`reticle/agent_names.py`): KAY/O bound on c817691bcd15 and d3dcfb182ab1; player-agent 0.3.0 leaves other sessions' lineup consumers stale until the corpus run.
- **replay-truth-0.3.0**: names the player from the replay (2 m path share, refusal below a 0.25 lead); agrees with Riot on c817691bcd15 and 9acf02f98283; d3dcfb182ab1 scored without Riot (ally names 0.989).
- **Self-entry** (`adjudication.self_entry`, self-entry-0.1.0): the player's killfeed roles by side plus the bound agent's portrait, "Me" second; agrees with "Me" on 677 of 677 roles; matches the scoreboard K/D on 15 of 17 captures; cea8ecbc94ab reads 8/15. 4f207c0c4e39 prints the account name and shows the Shooting Error readout [domain:hud/shooting-error-readout]; both fixes were designed on it. hud-0.27.0 refuses slots under the readout.
- **Frame join** (`reticle/frame_join.py`, `reticle frame-join SESSION`): c817691bcd15's `ally_icon` and minimap cache sit at different 15 Hz phases (0.567 exact); grid joins now refuse below 0.99.
- **Plans and prototypes:** `docs/QUESTION_ACCEPTANCE.md` (proposed; predictions QA0-QA7), `prototypes/stack_edge.py` (unwired), the AGENTS.md fidelity rule.

### Results recorded in `notes/predictions.jsonl`

- **W1, ally-prior** (branch `w1-ally-prior-score-20261006`, unmerged): carried positions 0.13-0.16 below the stored stream on all three development matches; falsifier fired. Names after a stack exit fall to about 0.70.
- **W2, self tracker and guard 6** (branch `w2-self-tracker-score-20261006`, unmerged): both predictions failed; guard 6 removes live fits through a false spectate interval (9acf02f98283 round 23) and intervals that run past the respawn; scored on the held-out match after failing, which a failed candidate should not do. Master's `player_dead_spans` removes no live fit but ends at round end. Two "player dead" owners exist only on that branch.
- **Stack-edge discrimination**: on exposed pixels it names the emerging teammate 0.89 at 40+ px (0.94 lag-corrected) against the stored stream's 0.77 where located; the pixel trigger, the stored candidate set and stored poses failed. Candidates should be the living roster plus a background null; poses and trigger from slot beliefs.
- Each frame-join correction carries a revision row; no verdict changed.

### Side findings

- Teammate fits trail replay truth by about 70 ms (BACKLOG waiting).
- FFV1 crop-cache decodes run on CPU at about 1.5-3x wall time despite thread caps.
- Combat-report surprise: b7d24102a6f6 round 18 and 7010b3d62460 round 2 show two distinct reads within a round; show the player those frames.

### Unmerged branches

`w1-ally-prior-score-20261006`, `w2-self-tracker-score-20261006` (negative results, kept for their scorers); `coaching-questions-20261006` (running). Carried from earlier handoffs: `one-pass-ingest-20261005`; held `whitened-weapon-20261003`, `whitened-weapon-null-20261004`; rework `binding-rules-20261002`; WIP `luma-render-20261002`, `wip-vision-lifecycle-wiring`; plans `killfeed-prior-design-20261002`, `killfeed-prior-step1-20261002`; `enemy-fix-check-20260930`; stale leftovers listed in the [10-05 archive](docs/archive/NOTES-2026-10-05-to-10-06.md).

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`; d3dcfb182ab1 `C:\Users\grant\Videos\2026-10-05 18-13-01.mp4`; cea8ecbc94ab `C:\Users\grant\Videos\2026-10-05 19-18-53.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
