# Reticle working handoff

## Picking up

**2026-10-06.** Master stands at `832b1ff`. Two branches wait for the player's merge, both pushed and test-merged together on `notes-20261006` (this handoff): `agent-spelling-owner-20261006` (`460059b`) and `agent-replay-self-id-20261006` (`9d7909a`). The [backlog](BACKLOG.md) order stands: replay training, the ally-icon cost, the spelling owner's remainder. The previous handoff is [archived](docs/archive/NOTES-2026-10-05-to-10-06.md).

### New captures, ingested 2026-10-05

- **d3dcfb182ab1** (18-13-01, development, replay 16a475cb): 20 rounds, 7-13, K/D 13/21. The ingest hook found the replay by the recording time in its header, linked it, and built the layer and episodes. The ingest took about 2,840 s for 28.6 minutes of capture, about 99 s per capture-minute against c817691bcd15's 170. No Riot record is fetched.
- **cea8ecbc94ab** (19-18-53, held-out, replay bd7efa02): starts in round 5; the reader numbered 16 rounds 5 to 20 from the 4-0 score on screen, 13-7 final. Replay linked and built, truth untouched. Two capture differences, both put to the player: the killfeed shows the account name instead of "Me", so the player's K/D reads 0/0; and the shooting-error readout is on, covering killfeed slots 3 and 4.

### On the branches

- **Spelling owner** (`460059b`): `reticle/agent_names.py` owns agent-name spelling (`[owns:agent-spelling]`, foundation layer); every comparison in `reticle/` asks it, and eight duplicate tables and helpers are gone. player-agent 0.3.0 and round-entity 0.18.0. Reruns from storage bound the player to KAY_O on c817691bcd15 (slot 2) and d3dcfb182ab1 (slot 4), each on two channels; own ult casts 4 and 4; tray-drop player casts 53 and 24. 4f207c0c4e39 stays Iso, slot 0. Because the stored c817691bcd15 and d3dcfb182ab1 streams came from the branch, master's code disagrees with them until the merge. The player-agent bump leaves every other session's lineup consumers stale in `plan` until the corpus run. Prototypes keep their own spelling rules (listed in the commit).
- **Replay self identification** (`9d7909a`, replay-truth-0.3.0): `score` names the player as the replay player whose living path holds the stored `ally_icon` self centre within 2 m on the most frames, refusing below 900 frames, a 0.30 share or a 0.25 lead. The cut was registered (task `replay-self-id-20261006`) before d3dcfb182ab1 ran. On c817691bcd15 and 9acf02f98283 the pick and the team equal Riot's, with leads of 0.57 and 0.57. d3dcfb182ab1 scored without a Riot record: KAY/O, the same account as the other two, lead 0.52. Riot's record, when present, is a stored cross-check. `replay_layer` still needs Riot to set the player, so d3dcfb182ab1's layer has no capture clock or self.

### Still open from c817691bcd15

- The phantom enemy Clove lives only in the unconstrained top-bar file (slot 2, margin 0.0806 over Jett against a 0.07 gate); the scoreboard constraint makes the view five of five right.
- K/D 10/28 against 10/24: `rounds.player_deaths` counts every `kf_death_mask` track, with `player_second_lives` None. Round 7 adds two (a revive and a second life), round 20 one ally-side entry flagged `kf_player_death`. Not fixed.
- `replay_abilities.py census` ran clean without `--record`; the TypeError is not reproduced. Suspect `metrics.record`.
- `plan c817691bcd15` still names `reread ally_icon`, `reread hud` (hud-0.26) and `decode minimap_dark` (needs video), and so `deaths` refuses.
- No ability-candidate model covers KAY/O, so ability-shapes finds no casts and the 279 gated samples find no caster: no ring or beam caster played.
- The ingest is unjudged.

### Side findings

- `plan` on a new capture does not name stored-data steps that never ran; the ingest ran them by hand.
- The thread caps leak: several ingest commands used two to five times their wall time in CPU with the BLAS and OMP caps set. OpenCV probably runs its own pool (`cv2.setNumThreads`).
- Combat-report surprise: b7d24102a6f6 round 18 and 7010b3d62460 round 2 show two distinct reads within a round; show the player those frames.

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`; d3dcfb182ab1 `C:\Users\grant\Videos\2026-10-05 18-13-01.mp4`; cea8ecbc94ab `C:\Users\grant\Videos\2026-10-05 19-18-53.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
