# Reticle working handoff

## Picking up

**2026-10-06, night.** Master stands at `8f95262`, pushed. The [backlog](BACKLOG.md) order: build the slot model to answer the catalogued questions; the ally-icon cost by fidelity; the spelling owner's remainder. The earlier handoffs of the day are archived ([morning](docs/archive/NOTES-2026-10-06-morning.md), [evening](docs/archive/NOTES-2026-10-06-evening.md)).

### The frame

Fidelity follows the question (AGENTS.md). [COACHING_QUESTIONS.md](docs/COACHING_QUESTIONS.md) ranks the questions on 17 replays and 170 ladder matches: trades within 5 s, the opening duel, map control at 20 s, full buys, execute commitment and damage-only balance lead; most value comes from events. Coaching is about the player with teammates as context; an execute or rotation needs only that it happened and how many went. On truth, the schedule `Lp0.5-250w5` (0.5 Hz base reads, 5 Hz inside windows opened by a drawn enemy within reach, 250 ms buffered) reads 0.0484 of today's 15 Hz slot reads and keeps every sight question at 0.95 or better; it implies 0.36 to 0.81 ms per captured 60 Hz frame uncontended (0.69 to 1.56 contended), against today's 7.44 (14.2), before the gate's own cue and decode are priced. Last-seen sets pruned by team vision hold the truth 0.97 and collapse to unknown at a median 13 s; open flanks raise the death rate 1.55-fold. Peek/hold and corner distance showed no win edge; cross-round habits predicted little within a match. The acceptance plan [QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) records the player's answers and the cost bound.

### Timing

- replay-truth-0.4.0 reads truth on the killfeed least-squares clock (the capture clock runs about 1e-4 fast) with separate self and remote lags; teammate p90 error fell from about 3 px to 1-1.7 px [domain:capture/minimap-remote-player-lag].
- [RENDER_DELAY.md](docs/RENDER_DELAY.md): two clocks per belief, client render time for what the player could know and server time for order; a constant 50 ms prior in a 30-200 ms band, because no capture-only estimator recovered the delay. Sight order follows corner distance: the closer player sees later in 0.92 of non-tied duels, median 70 ms.
- `render-delay-ping-20261006` (merged): lobby ping does not set the delay (9acf02f98283: 168 ms delay, 59 ms lobby max; d3dcfb182ab1: 55 ms, 150 ms). The scoreboard's PING column is legible but unread; the self row may show a client-side figure. 9acf02f98283's delay stays unexplained (build 13.04, small minimap). The player set ping aside: it changes strategy little.

### Merged today

Spelling owner (`reticle/agent_names.py`); replay self identification, now owned by `reticle/replay_source.py` (`[owns:replay-self]`), so d3dcfb182ab1's layer has a clock and self; self-entry (side plus bound portrait; cea8ecbc94ab K/D 8/15) and the Shooting Error refusal (hud-0.27.0); `reticle/frame_join.py`; the stack-edge prototype; the fidelity rule; the plans above.

### Results in `notes/predictions.jsonl`

W1 (ally-prior) and W2 (self tracker, guard 6) failed their falsifiers; revision rows corrected c817691bcd15's frame join without changing a verdict; stack-edge discrimination names exits 0.89 at 40+ exposed px but needs slot beliefs for trigger, candidates and poses. Each task's prediction, revision and outcome rows carry the numbers.

### Side findings

- `replay_layer` keeps departed players alive in 7498df5e and 2c387cb6.
- The 3D sightline walk graph drops cells along barriers and doors and has no jump or drop edges; `prototypes/coaching_belief.py` adds its own.
- `cast` rows in replay layers come out in a different order per build, which blocks byte-identity checks.
- Combat-report surprise: b7d24102a6f6 round 18 and 7010b3d62460 round 2 show two distinct reads within a round.

### Unmerged branches

`w1-ally-prior-score-20261006`, `w2-self-tracker-score-20261006` (negative results). Carried: `one-pass-ingest-20261005`; held `whitened-weapon-20261003`, `whitened-weapon-null-20261004`; rework `binding-rules-20261002`; WIP `luma-render-20261002`, `wip-vision-lifecycle-wiring`; plans `killfeed-prior-design-20261002`, `killfeed-prior-step1-20261002`; `enemy-fix-check-20260930`; stale leftovers in the [10-05 archive](docs/archive/NOTES-2026-10-05-to-10-06.md).

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`; d3dcfb182ab1 `C:\Users\grant\Videos\2026-10-05 18-13-01.mp4`; cea8ecbc94ab `C:\Users\grant\Videos\2026-10-05 19-18-53.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
