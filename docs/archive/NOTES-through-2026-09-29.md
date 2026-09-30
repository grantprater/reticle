# Reticle working handoff

## Picking up

**2026-09-28.** Every branch of the day is merged into master (`2410764`). The identity arbiter now names the player's agent, contests a death whose name a collision repeats, and has E1's review behind it. The minimap gained a menu guard, a spike channel, a variant widget and a teardrop that reads the self facing. `reticle verify --tier fast` checks known answers without a decode. No code task is active: the [backlog](BACKLOG.md) waits on the player's labels and answers, on decodes he must approve, and on his calls about identity. On 2026-09-29 `reticle self-icon --all` reran from storage to `self-icon-0.4.0`. `reticle plan` now names two decodes, `ally_icon` and `scoreboard`, and four storage reruns that wait on the scoreboard: `deaths`, `openings`, `ult-cast` and `ability-state`.

### A lesson: rendering is not measuring

A reader verified by rendering it on a few frames is unmeasured until it is scored on labels. The self facing came from the ring fit from the day the self tracker was promoted (2026-09-02, `reticle/minimap.py`); overlays looked right and nothing scored it. The player's blind labels on Lotus (`5822b6646448`, `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`) show the ring fit flipped on [metric:self_facing_eval/labels@5822b6646448+controls#ring_all_lotus_flip=0.5] of the labelled frames, where the teardrop errs a median [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_all_lotus_median_abs_deg=2.233] degrees ([E4](docs/STATISTICAL_ADJUDICATOR.md#e4-calibrate-the-origin-and-the-angle)). The sliver search's Formulation D (`prototypes/adjudicator_statistical.py`) hid the flip: it cast both lobes, shifted the origin and turned the ray through relaxed walls, so a backwards facing still "explained" the light. Score a reader before loosening the test that reads it. The fast tier's `lotus/self-facing` check now holds the facing to the labels.

### Identity and deaths

- **Contested deaths.** A death carrying a name that an elimination collision repeats stays contested until the player HUD or a minimap track confirms it (`death-adjudication-0.17.0`); [metric:e1_agreement/landing@store-20#contested_after=18] deaths wait on such a witness. [Victim disagreements](docs/VICTIM_DISAGREEMENTS.md) records the earlier disagreements by cause: the board's elimination inherits killfeed errors and uncounted second lives.
- **Killfeed onset.** `hud-0.16.0` rejoins an entry whose white text split its plate over a dark wall. The player's death at `c40d950031bb` (`C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`) moves from 703.5 s to 701.0 s. The Shooting Error box still hides an entry until the stack rises (`223d636bf8d2`, `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`, 719 s).
- **Exemplar.** `agent-identity-0.9.0` records the exemplar at the shift that set a portrait's score; no name moves. `plan` stales a deaths table when the scoreboard or identity rules move.
- **Lineup owner.** The round 4 oracle follows the crops (Jett in enemy slot 2, Killjoy in 4) and tests the lineup owner, not the raw top bar.
- **The player's agent.** The arbiter decides it from tray and self-icon claims (`player-agent-0.2.0`, `lineup-0.5.0`). The self icon scores rendered art ([results](docs/SELF_ICON_WITNESS.md)): it agreed with the tray on [metric:self_icon/agreement@lineup-21#agree=12] lineup sessions, disagreed on [metric:self_icon/agreement@lineup-21#disagree=0] and abstained on the rest, mostly Sova. `self-icon-0.4.0` keeps a fit that may be the spike's carrier and refuses one on the glyph itself.
- **E1.** Agreeing totals concealed binding errors ([E1](docs/E1_AGREEMENT.md)). E1 landed as `death-adjudication-0.18.0`; 0.19.0 lets a name cluster try every followed view. The player reviewed the list: [metric:e1_review/answers@review-20260928#yes=114] of [metric:e1_review/answers@review-20260928#answers=121] answers held (`labels/e1_review_20260928.jsonl`). Three `223d636bf8d2` names stay wrong.

### The minimap

- **Menu witness.** `reticle menu` (`menu-0.1.0`) finds the open menu from the crop caches on [metric:menu/witness@all-sessions#sessions_with_open=36] of [metric:menu/witness@all-sessions#sessions=58] sessions; the tray, roster and minimap readers refuse what it covers ([results](docs/MENU_WITNESS.md)).
- **Roster.** `roster-0.3.0` reads crispness inside the tinted panel, and `roster-split-0.4.0` refuses a crisp bar with no split. Board agreements rose to [metric:roster_split/panel-band#agree=34402] with [metric:roster_split/panel-band#agree_lost=0] lost; `KNOWN_KD` stays [metric:roster_split/panel-band-known-kd#exact=13] of 17 exact ([results](docs/BOARD_ALIVE_SETS.md)).
- **Spike.** `reticle spike` (`spike-0.1.0`) reads the glyph on the minimap and the carrier marker on the roster. `adjudication.spike_carrier` checks them against the plant and the alive count, stores every disagreement and names nobody.
- **Team vision.** `team-vision-0.3.0` casts the self cone from the teardrop's centre along its facing (`teardrop-0.2.0`). F1 against the joined light rose from [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_before_f1=0.6104] to [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_f1=0.6968] on `e78e75b2d191` (`C:\Users\grant\Videos\2026-09-03 19-16-07.mp4`), and `light_refusals` now refuses the 43.35 s sliver. `reticle vision` runs a match several times faster with its output unchanged. The store holds 0.3.0 for `e78e75b2d191` and `a06f04a0059f` (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`) only. Ally and enemy teardrops wait on the player's labels ([E6](docs/STATISTICAL_ADJUDICATOR.md#e6-ally-and-enemy-teardrops)).
- **Variant widget.** `reticle widget-fit <sid> --write` fits a widget drawn at another scale, rotation or placement and resamples it into the baked frame. The Iso capture `4f207c0c4e39` (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`) now reads.
- **Smokes.** `adjudication.smoke_owner` names each team smoke's caster through the arbiter from the player's rules [domain:abilities/smoke-attribution]; `smoke-0.4.0` births no smoke over a live one.

### Infrastructure

- `reticle verify --tier fast` runs seven known-answer checks from storage and the crop cache. A stamp the code has passed reads STALE, never PASS.
- QUOTED pins a citation to one run with `~<run>`; unpinned citations meet the latest run.
- `reticle/clipserve.py` serves capture windows by HTTP range; `prototypes/e1_review.py` plays the review through it without copying media.
- The dark reader rides the minimap crop cache (`--from cache`) and reads FFV1 forward instead of seeking.

**Older threads**: archived ([09-26](docs/archive/NOTES-through-2026-09-26.md), [09-27](docs/archive/NOTES-ability-id-through-2026-09-27.md), [pub/sub](docs/archive/NOTES-pubsub-through-2026-09-27.md), [09-28](docs/archive/NOTES-through-2026-09-28.md), [09-28 evening](docs/archive/NOTES-through-2026-09-28b.md)). The untracked `prototypes/mechanics_eval.py` belongs to the user and must remain untouched. The [working map](docs/WORKING_MAP.md) routes reading.
