# Branches retired on 2026-10-09

The convergence cleanup of 2026-10-09 deleted these local branches. Each one's
last commit stays reachable at its `archive/` tag; `git checkout <tag>`
restores it. Remote copies on `origin` were left alone. The audit behind the
cleanup compared each branch with master `9bacd17`.

One line per branch: name; tag; what it tried; what it found; where its
salvage landed.

## Approved by the player

- `binding-rules-20261002`; `archive/binding-rules-20261002`; cut a round piece where a sighting gap spans a teammate's death (round-entity-0.15.0); 78 cuts made 35 new bindings, 31 matching the victim, but moved 9 correct bindings to an unnamed piece, and the slot model replaces piece naming; no salvage.
- `luma-render-20261002`; `archive/luma-render-20261002`; keyed the ally rim on luma (E1) and fitted fuller renders (E2); unverified, four E2 slices never ran, and `prototypes/scene_stack.py` is the render path now; the write-up landed in [LUMA_RENDER-2026-10-02.md](LUMA_RENDER-2026-10-02.md).
- `wip-vision-lifecycle-wiring`; `archive/wip-vision-lifecycle-wiring`; second witnesses and stored verdicts for minimap-lifecycle-0.3.0, marked "do not merge" and waiting on self-spike-tracker; detection_reality, the arbiter design and the slot model replace it; no salvage.
- `whitened-weapon-null-20261004`; `archive/whitened-weapon-null-20261004`; an open-set null for the whitened killfeed-weapon filter; negative: the NULL gate gave Riot 537/0/9 against 531/0/15, but held-out leave-one-icon-out misnamed 535 against the IoU gate's 63, and no gate won on both; no salvage. Its detached twin worktree `wf_07b3fd55-9e3-10` (same `d9bb522`) was removed.
- `w1-ally-prior-score-20261006`; `archive/w1-ally-prior-score-20261006`; a per-frame scorer of the ally prior against replay truth; negative: carried positions scored 0.13-0.16 below the stored stream on all three dev matches (c817 at ally-prior-0.4.0: 0.7422 against 0.8932); the harness owns frame scoring now; no salvage.
- `w2-self-tracker-score-20261006`; `archive/w2-self-tracker-score-20261006`; the self and spike tracker (minimap-0.8.0, `adjudication.spectate`, `icon_prior`) with a W2 scorer; negative: guard 6 removed live fits through a false spectate interval (9acf02f98283 round 23) and intervals past the respawn, and it added a second player-dead owner beside `round_entities.player_dead_spans`; two facts landed in `domain/minimap.toml`, [domain:minimap/death-camera-period] and [domain:minimap/spike-last-known-mark].

## Content already on master, or a strict ancestor of a kept or retired branch

- `enemy-error-budget-20261007`; `archive/enemy-error-budget-20261007`; the enemy lane's error budget; master holds it as the rebased merge `78a1f5b` (`git cherry` all `-`); none needed.
- `enemy-labels-20261007`; `archive/enemy-labels-20261007`; the budget plus a disagreement labeller; same rebased merge, both commits `-`; none needed.
- `kff-old-20261005`; `archive/kff-old-20261005`; killfeed follow-ups before a renumber (hud-0.24/0.25, killfeed-weapon-0.18); two commits `-`, and master `4169060` equals `e9952a5` plus fixup `92b20dc`; none needed.
- `worktree-agent-a18926290da85c09f`; `archive/worktree-agent-a18926290da85c09f`; the protocol-demo cast census; all six commits `-`, `docs/DEMO_CAST_CENSUS.md` is on master; none needed.
- `wip-primary-20260926`; `archive/wip-primary-20260926`; a save of the primary checkout's uncommitted work of 2026-09-25/26; every file it touched exists on master, developed further; none needed.
- `stacked-icons-20261002`; `archive/stacked-icons-20261002`; a joint k-icon fit for stacked ally icons; negative: its teal key erased the pale ring and lost 42 of 197 labelled icons; superseded by `reticle/stack_fit.py`.
- `ally-ring-subpixel-20261001`; `archive/ally-ring-subpixel-20261001`; fractional ring radii (ally-icon-0.8.0); negative by the player's verdict: ally-count error fell at 331 px, but phantom fits rose and labelled icons were lost; none.
- `killfeed-prior-design-20261002`; `archive/killfeed-prior-design-20261002`; the killfeed queue-prior plan; an ancestor of the kept `killfeed-prior-step1-20261002`; held there.
- `worktree-agent-a9868f361c77a713f`; `archive/worktree-agent-a9868f361c77a713f`; the same plan; an ancestor of `killfeed-prior-step1-20261002`; held there.
- `whitened-weapon-20261003`; `archive/whitened-weapon-20261003`; a whitened matched filter for killfeed weapons (weapon-adjudication-1.4.0); an ancestor of `whitened-weapon-null-20261004`, retired above; none.
- `self-spike-tracker-20260929`; `archive/self-spike-tracker-20260929`; the first self and spike tracker; an ancestor of `w2-self-tracker-score-20261006`, retired above; the facts landed as for w2.

## The bootstrap experiment

- `experiment/bootstrap-a`; `archive/experiment/bootstrap-a`; lane A: independent evaluation and a death correspondence audit; the learner changed no name, so the player's answer scored production; recorded in [BOOTSTRAP_PARALLEL_RUN-2026-09-24.md](BOOTSTRAP_PARALLEL_RUN-2026-09-24.md).
- `experiment/bootstrap-integration`; `archive/experiment/bootstrap-integration`; reconciled the lanes and closed with the player's answer; its `handoff.md`, `result.json` and `tools/bootstrap_compare.py` survive only at the tag, and the one harness owns comparison now.

## Kept, with salvage or a tag

- `enemy-fix-check-20260930` stays until its 61 player labels are scored; its domain fact landed in `domain/minimap.toml` as [domain:minimap/door-leaves-and-ledges-are-tall-boxes].
- `worktree-agent-a3c32f26e36c27c4f`, the glyph classifier's refusal below 0.5, stays: this cleanup did not list it. Its write-up landed in [ABILITY_DEMO_MINING-2026-09-23.md](ABILITY_DEMO_MINING-2026-09-23.md).

- `experiment/bootstrap-b` (`archive/experiment/bootstrap-b`), lane B's bounded portrait learning: its worktree holds an untracked `.experiment-store/`, so the branch stays.
- `crowd-prior-v4-20261004` (`archive/crowd-prior-v4-20261004`), a merge of two master commits: its worktree `wf_076f19ca-1ad-1` holds an uncommitted line, so the branch stays.
- `ult-buyphase-v2-20261004` (`archive/ult-buyphase-v2-20261004`): merged into master, but its worktree `wf_e83a3e3b-cc9-1` holds an untracked draft, so it stays.
