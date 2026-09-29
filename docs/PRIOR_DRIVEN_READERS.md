# Prior-driven readers

A plan, proposed 2026-09-29. The player asked that readers work as
adjudication should: start from what context predicts, check the prediction
cheaply, and widen the search only on surprise. `AGENTS.md` ("Continue the
prior; widen the search only on surprise") states the principle and its
guards; this document audits how each reader uses context today, states the
pattern for this repository, ranks where a prior would pay, and names the
code that already follows it and the code that assumes a prior it never
checks. It builds nothing.

Every figure below comes from stored rows (no decode, no GPU), recorded as
the run `prior-audit-20260929` under the series `prior_readers_audit/*`. The
store was mid-rescan (the player's scoreboard rescan) while it was read, so
each citation pins that run.

## 1. Inventory

"Searches" is what one sample costs; "Context" is what the reader or its
owner already consults; "Declares" says whether a result that context shaped
names what it rests on. Class: **full** searches the whole region and gallery
every sample; **tracked** starts each sample from the last one; **mixed**
tracks or gates part of the work.

| Reader (module) | Searches per sample | Context it uses | Declares | Class |
|---|---|---|---|---|
| HUD scoreline, clock, bottom HUD (`hud_reader`, `ocr`) | Every digit ROI, full template set | A per-session killfeed calibration; nothing temporal (`gametime` fits the clock downstream) | -- | full |
| Killfeed entries and attribution (`killfeed`) | Row profile over the whole ROI, every band parsed | A persistence mask for toggled overlays, derived from the footage; follow and persistence live downstream (`checks.track_entries`, `death.follow_entry_portraits`) | -- | mixed |
| Killfeed portraits, names, weapons (`killfeed`, `adjudication.death`, `identity`) | Crops beside every parsed entry | The lineup's side candidates, refused slots as rivals (`identity.side_candidates`) | `depends_on`, `binding_from` | mixed |
| Roster alive (`roster`) | Ten slot details, one boundary per side | Survivors pack as a contiguous run (a structural prior inside the frame); deliberately no killfeed prior | -- | full |
| Scoreboard rows (`scoreboard`) | Slab profile; every portrait against all 29 agents | The strip places the blocks and predicts the frame edges | `anchor`, `both_anchored`, `enemy_rows_from` | mixed |
| Scoreboard strip (`scoreboard_strip`) | Lattice fit in the fixed centre crop | None | -- | full |
| Top bar lineup (`lineup`) | Ten compositions against all 29 agents, accumulated over the match | The board's side set re-assigns slots (`identity.lineup_with_board`) | `top_bar_sides`, `board_disagreements`, `constrained_by` | full (justified: it bootstraps) |
| Self position (`minimap.pick_self`, `filter_track`) | Ring fits over the slab | Nearest to the previous point within a run gate; the motion law | Nothing: the pick does not say which path chose it | tracked |
| Ally icons (`minimap.AllyIconReader`) | Ring fits over the slab, descriptors at 2 Hz | Baked static for barriers; no state across frames by design | -- | full |
| Teardrop (`teardrop`) | Grid over centre and facing in a window | The ring fit's centre in the same frame | `team_vision` stores `origin` and `facing` source | mixed |
| Team vision (`team_vision`) | Cones for tracked icons | `Tracker` and lifecycle across frames; the teardrop's facing never enters the track history | Origin, facing source, eligibility | tracked |
| Spike glyph and roster marker (`spike`) | Glyph template at three sides over the slab, 1 Hz | Marker read only at the five slot columns (structural); nothing temporal | -- | full |
| Minimap dark (`minimap_dark`) and smokes (`adjudication.smokes`, `smoke_owner`) | Dark grey floor over the whole widget | Tracks judged by their own disc after birth; owner restricted to the ally side's smoke agents | `depends_on` the ally slots | mixed |
| Pings (`ping`) | Hue candidates over the floor | Contiguity by construction (`Grouper`), class lifetime | -- | mixed |
| Menu (`menu`) | Two opaque structures, searched | None; other readers consult it | -- | full |
| Combat report (`combat_report`) | Header template, then fields relative to it | None | -- | full |
| Self icon portrait (`self_icon`) | 29 agents per frame | Frames gated on the roster reading five allies alive; the claim ranks among the ally five | `depends_on`, `global_best`, `rank_of_pick` | full scoring, prior at the claim |
| Tray fills (`tray`) | Four bars at fixed geometry | Session p90 normalisation | -- | full |
| Tray kit (`tray_icons`, `adjudication.tray_kit`) | Only the agents the current set asks for (lazy scorer in `cli`) | Player, then allies, then all | `depends_on`, `widened` with reason | mixed (prior-driven) |
| Ult lines (`ult_lines`) | All templates over the audio | None; "consults no lineup" | -- | full |

Twenty rows: eleven full, two tracked, seven mixed. Eight declare the prior a
result rests on (killfeed portraits, scoreboard, top bar, teardrop through team
vision, team vision, smoke owner, self icon claim, tray kit). One tracked
reader declares nothing: the self position.

## 2. The pattern, stated for this repository

**Predict, verify, widen.** A reader takes a prediction from context -- a
candidate set, a search window, or a value -- and scores the prediction
first. It accepts the prediction when the reader's own gate passes on the
predicted hypotheses. It widens to the full search when the gate fails, and
records the widening as a surprise row with the prediction, the
observation and the reason. `adjudication.tray_kit` is the model: the
player's kit, then the ally side's, then the catalogue, each widening named.

`docs/BEHAVIOUR_MODEL_DESIGN.md` ("Gating, not scoring") already fixes the
first guard: a prior narrows which hypotheses a reader scores and never
changes a score. The rest follow.

1. **Declare the scope.** A prior-shaped result names the prediction it
   tested and its source: `depends_on` entity ids for identity claims, the
   stream and version for a stored prior, the instants for a temporal one
   (`belief.Fix.rests_on` already does this). One field, `scope`, should hold
   `{set or window, source, widened}` on every gated row.
2. **Count the prior once.** A result gated on the lineup cannot testify for
   the lineup. `adjudication.reliability` already excludes `depends_on`
   claims from its reference counts; every consumer that counts witnesses
   must do the same.
3. **Store the surprise.** A failed prediction is a row, never an average and
   never a silent fall-through.
4. **Audit on a fixed cadence.** Run the full search on a schedule fixed in
   advance over the opportunity-gated grid -- every k-th sample, plus the first
   sample of each span -- and store it apart as an audit row. The agreement
   between audit and gated rows is the check of the prior; without it, "a
   prior that is never checked is a hidden assumption". A surprise-triggered
   full search is not an audit sample: its selection depends on the outcome.
5. **Keep a prior-free channel where adjudication needs independence.** The
   roster audits the killfeed; the combat report is the second witness for a
   death the killfeed hides; the top bar and the board's audit openings
   bootstrap identity; ult lines consult no lineup. None of these gates on
   another channel.
6. **Expire the prior at a hole.** A prior stops at a widget-absent frame, a
   round boundary, the player's death (the view spectates), and an open menu,
   the same boundaries `filter_track` and `belief` already respect.
7. **Mind the stamp.** A decoding reader whose output rests on another
   stream becomes stale when that stream moves, and a stale decoding reader
   costs a decode. So priors in decoding readers should come from the
   reader's own earlier samples, or from baked geometry; priors from other
   streams belong in owners that recompute from storage, where a change costs
   a rerun.

**The belief rule, amended.** `docs/ADJUDICATION_DESIGN.md` said a belief
"cannot seed a template, feed a detector's prior, or count toward observed
coverage", which forbade this plan. The rule's purpose is that a belief never
becomes an observation, and this plan keeps it: the gated reader stores a raw
score over a declared scope, the audit keeps the unbiased channel, and gated
rows never count as independent coverage of the prior. The player approved
the amendment on 2026-09-29: a belief may set a reader's prior under the
guards `AGENTS.md` states ("Continue the prior; widen the search only on
surprise"), which are guards 1 to 4 above.

**What the pattern trades.**

- *Lock-in.* A tracker that latches onto a confuser follows it. `pick_self`
  keeps the fit nearest the last point, so a self fit that jumps to the spike
  glyph stays there while the glyph stays within the gate (section 3, item 2).
- *Drift.* A prior updated from its own gated outputs corrupts slowly. Set
  a prior only from audit rows or full searches.
- *Missed unexpected events.* A gated reader cannot see what its set
  excludes: a Phoenix returning from Run It Back, a spectated kit, a
  teammate's icon under the player's. The widening gate catches only what
  fails the gate; the audit catches the rest at its cadence.
- *Coverage bias.* Gated samples verify what was expected. Audit rows alone
  estimate a reader's recall.

## 3. Ranked opportunities

Ranked by expected accuracy gain against risk; speed counts second, because
a batched scoreboard scorer already cut an open frame's median from
[metric:scoreboard/speed-batch@a06f04a0059f~2026-09-29T12:28:06#ms_open_median_ref=246.3]
to [metric:scoreboard/speed-batch@a06f04a0059f~2026-09-29T12:28:06#ms_open_median_cur=52.3]
ms (scoreboard-0.13.0, on a peer branch). Each experiment reads the crop
cache and stored rows and decodes nothing.

### 1. Ally icons: the roster's count and each teammate's track

*Prior.* The roster says how many teammates live; each teammate's track says
where its icon was a frame ago. Search a window round each predicted
position with the relaxed coverage the sweep in `minimap.py` measured (0.20),
and accept a fit there only as `scope: track`.

*Evidence.* At `ally-icon-0.4.0`, against the roster's alive allies less one,
over in-round frames with the widget and a self fit:
`a06f04a0059f` read exact on
[metric:prior_readers_audit/ally-icon-vs-roster@a06f04a0059f~prior-audit-20260929#exact=12940]
of [metric:prior_readers_audit/ally-icon-vs-roster@a06f04a0059f~prior-audit-20260929#frames=17749],
over on [metric:prior_readers_audit/ally-icon-vs-roster@a06f04a0059f~prior-audit-20260929#over=286]
and under on [metric:prior_readers_audit/ally-icon-vs-roster@a06f04a0059f~prior-audit-20260929#under=4523];
`5822b6646448` exact on
[metric:prior_readers_audit/ally-icon-vs-roster@5822b6646448~prior-audit-20260929#exact=10511]
of [metric:prior_readers_audit/ally-icon-vs-roster@5822b6646448~prior-audit-20260929#frames=15771],
over on [metric:prior_readers_audit/ally-icon-vs-roster@5822b6646448~prior-audit-20260929#over=473]
and under on [metric:prior_readers_audit/ally-icon-vs-roster@5822b6646448~prior-audit-20260929#under=4787].
The phantom teammate is solved; a missing one in about a quarter of frames
is not. Identity, vision and round entities all read this channel.

*Risk.* Stacked icons are genuinely hidden, and a relaxed fit near a
prediction can take a barrier or a ping. Keep the barrier gate, store a
missing teammate as `missing` with its reason, and never let a track-gated
fit enter the roster-agreement audit.

*Experiment.* From stored rows, split the under frames by whether the
previous frame held two fits within twice the radius (a stack explains the
miss) or none (a detection explains it). Then re-fit 300 of the isolated
misses from the minimap crop cache at coverage 0.20 inside a window round the
lost track's last position, and have the player label the fits blind
(`labelling-pass`). Prediction to log first: most misses are stacks.

### 2. Self position: declare the pick, then guard the lock-in

*Prior.* `pick_self` already takes the fit nearest the previous point. Make
it declare which path chose (`near_previous` or `widened`) and store the
runner-up; then refuse a near-previous pick that sits on an accepted spike
glyph, asking `spike.on_glyph`.

*Evidence.* `docs/ADJUDICATION_DESIGN.md` measured the self reader's accepted
answers as the player 87.49% of the time, with the spike the largest
confuser. At the spike reader's 1 Hz samples holding an accepted dropped
glyph, the stored self fit sits within 4 px of it on
[metric:prior_readers_audit/self-on-spike@a06f04a0059f~prior-audit-20260929#self_on_glyph=47]
of [metric:prior_readers_audit/self-on-spike@a06f04a0059f~prior-audit-20260929#samples_with_dropped_glyph=159]
(`a06f04a0059f`),
[metric:prior_readers_audit/self-on-spike@5822b6646448~prior-audit-20260929#self_on_glyph=7]
of [metric:prior_readers_audit/self-on-spike@5822b6646448~prior-audit-20260929#samples_with_dropped_glyph=94]
(`5822b6646448`) and
[metric:prior_readers_audit/self-on-spike@223d636bf8d2~prior-audit-20260929#self_on_glyph=54]
of [metric:prior_readers_audit/self-on-spike@223d636bf8d2~prior-audit-20260929#samples_with_dropped_glyph=220]
(`223d636bf8d2`), in runs up to
[metric:prior_readers_audit/self-on-spike@a06f04a0059f~prior-audit-20260929#longest_run_s=9]
s. A plant or a defuse puts the player on the spike for that long too, so
these counts are the signature, not the error rate. The stored self fits
predate `spike-0.2.0`.

*Risk.* Low: declaring changes no output; the glyph refusal already exists
for the self icon portrait (`self-icon-0.4.0`).

*Experiment.* View the six runs of five seconds or more from the minimap crop
cache beside the tray and the plant clock, and class each as plant, defuse or
lock-in.

*Result (2026-09-29, run `prior-self-20260929`, `prototypes/prior_self.py`,
not wired).* The audit read `ally_icon`'s best-coverage self, which no prior
chooses; its count reproduces
([metric:prior_self/audit-reproduced@a06f04a0059f~prior-self-20260929#self_on_glyph=47]
of [metric:prior_self/audit-reproduced@a06f04a0059f~prior-self-20260929#samples_with_dropped_glyph=159]
on `a06f04a0059f`). `pick_self`'s stored track (`l1/minimap`) sits on the
glyph more often and longer:
[metric:prior_self/on-glyph-l1-owner@a06f04a0059f~prior-self-20260929#on_samples=71]
samples in runs up to
[metric:prior_self/on-glyph-l1-owner@a06f04a0059f~prior-self-20260929#longest_s=27]
s there, and
[metric:prior_self/on-glyph-l1-owner@223d636bf8d2~prior-self-20260929#on_samples=69]
up to [metric:prior_self/on-glyph-l1-owner@223d636bf8d2~prior-self-20260929#longest_s=18]
s on `223d636bf8d2`. The prior locks in.

No run of five seconds or more is a plant or a defuse. By eye on the crop
strips
([metric:prior_self/run-classing@a06f04a0059f+223d636bf8d2~prior-self-20260929#runs_ge_5s=6]
runs), the player was dead in
[metric:prior_self/run-classing@a06f04a0059f+223d636bf8d2~prior-self-20260929#player_dead=4]:
the fit rings the spike where the carrier fell while the view spectates a
teammate, whose yellow icon, with another agent's portrait, moves elsewhere.
In [metric:prior_self/run-classing@a06f04a0059f+223d636bf8d2~prior-self-20260929#locked_player_elsewhere=1]
the player walks toward the spike 50 px away; in
[metric:prior_self/run-classing@a06f04a0059f+223d636bf8d2~prior-self-20260929#player_icon_not_found=1]
(`223d636bf8d2`, 1276-1280 s) no icon of his shows. On `a06f04a0059f` every
audit sample on the glyph falls after the player's death. A second defect
follows: after the player dies, the self track follows the spectated
teammate, so guard 6 (expire the prior at the player's death) applies to the
self position too.

The lock-in depends on frame phase. The replay refits `self_icons` on the
15 Hz crop cache and agrees with `l1/minimap` within 0.5 px on
[metric:prior_self/replay-vs-l1@a06f04a0059f~prior-self-20260929#within_0.5px=10278]
of [metric:prior_self/replay-vs-l1@a06f04a0059f~prior-self-20260929#both=10279]
shared instants, but the cache and the decode sample different frames half
the time: at 664.5 s on `a06f04a0059f` one missed frame sent `l1` onto the
glyph for 4 s, and the replay kept the player.

The guarded pick (`minimap.pick_self_declared`, then `spike.on_glyph` on
`spike-0.2.0` rows, then the teardrop) cuts the replay's samples on a glyph
from [metric:prior_self/on-glyph-stored@223d636bf8d2~prior-self-20260929#on_samples=71]
to [metric:prior_self/on-glyph-guarded@223d636bf8d2~prior-self-20260929#on_samples=2]
on `223d636bf8d2` and from
[metric:prior_self/on-glyph-stored@a06f04a0059f~prior-self-20260929#on_samples=78]
to [metric:prior_self/on-glyph-guarded@a06f04a0059f~prior-self-20260929#on_samples=4]
on `a06f04a0059f`, and loses
[metric:prior_self/points@223d636bf8d2~prior-self-20260929#lost_elsewhere=0]
points away from a glyph. The teardrop reads on
[metric:prior_self/teardrop@a06f04a0059f~prior-self-20260929#on_glyph_read=70]
of [metric:prior_self/teardrop@a06f04a0059f~prior-self-20260929#on_glyph_n=1425]
fits on a glyph against
[metric:prior_self/teardrop@a06f04a0059f~prior-self-20260929#off_glyph_read=1954]
of [metric:prior_self/teardrop@a06f04a0059f~prior-self-20260929#off_glyph_n=2251]
off one. The cost is open: of
[metric:prior_self/lost-while-alive@223d636bf8d2~prior-self-20260929#lost_while_alive=301]
frames refused while the player lived on `223d636bf8d2`,
[metric:prior_self/lost-while-alive@223d636bf8d2~prior-self-20260929#track_at_glyph=96]
sit where the track stands at the glyph, where he may stand on the spike.
`prototypes/label_prior_self.py` asks the player about 34 such frames,
blind. The 1 Hz full-search audit disagrees with the guarded pick on
[metric:prior_self/audit-cadence@a06f04a0059f~prior-self-20260929#disagree_guarded=34]
of [metric:prior_self/audit-cadence@a06f04a0059f~prior-self-20260929#compared=1283]
samples.

### 3. Pings: the ally track says a teammate stands there

*Prior.* A standard-hue candidate that coincides with a tracked ally icon for
its life is the teammate: `ping.py` found by eye that 13 of the 31 pings it
confirmed on a Lotus match were ally icons. Refuse it as `on_ally_track` and store the
disagreement.

*Evidence.* Of
[metric:prior_readers_audit/ping-on-ally-icon@a06f04a0059f+5822b6646448~prior-audit-20260929#standard_with_frames=47]
stored standard pings on two sessions,
[metric:prior_readers_audit/ping-on-ally-icon@a06f04a0059f+5822b6646448~prior-audit-20260929#on_ally_icon_half_life=13]
sit within 6 px of an ally fit for at least half their life.

*Risk.* A player may ping where a teammate stands. The refusal must keep the
row, so a labelled check can reverse it.

*Experiment.* View the 13 from the minimap crop cache and label each ping or
teammate; log the prediction (most are teammates) first.

### 4. Spike: a dropped glyph does not move

*Prior.* Once a dropped or planted glyph is accepted, the next sample
correlates one template at that place and state; a miss, a changed state or
the audit cadence widens to the slab. A carried glyph is predicted at its
carrier's lower left [domain:minimap/spike-carrier-overlay].

*Evidence.* Of
[metric:prior_readers_audit/spike-dropped-still@four-sessions~prior-audit-20260929#bracketed=489]
samples bracketed by one accepted dropped glyph at one place, the reader held
it on [metric:prior_readers_audit/spike-dropped-still@four-sessions~prior-audit-20260929#held=478].
The gain is a few holes and a cheaper sample, not a new channel.

*Risk.* A teammate standing on a dropped spike picks it up; the verify must
test the state (base orientation), not presence alone.

*Experiment.* At the eleven holes, correlate the bracketing glyph's template
at its place from the minimap crop cache, and view each: a portrait over the
glyph, or the spike picked up.

### 5. Scoreboard portraits: the gallery question

*Prior.* Score each row against its side's set, not all 29 agents.

*Evidence against the tempting prior.* The top bar's side five (named slots
plus refused slots' best guesses) misses the board's full-gallery best on
[metric:prior_readers_audit/scoreboard-topbar-five@lineup-sessions~prior-audit-20260929#best_outside_topbar_five=35938]
of [metric:prior_readers_audit/scoreboard-topbar-five@lineup-sessions~prior-audit-20260929#accepted_rows=183260]
accepted rows over 20 sessions. Named slots alone, dropping refused ones,
miss on [metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#named_only_best_differs=18299]
of [metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#named_only_rows=45665]
rows of five sessions -- the lesson `side_candidates` records. The gate
catches the gap: of
[metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#outside_five=14189]
rows whose best lies outside the five,
[metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#outside_five_passing_gate_within_five=0]
would pass the shipped gate within the five, and
[metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#inside_five_failing_gate_within_five=0]
rows inside it would fail. So the widening gate works, and would fire on a
fifth of rows.

*Evidence for the board's own prior.* A set taken from each session's first
three accepted full-gallery openings disagrees with the full-gallery best on
[metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#later_rows_first3_set_best_differs=0]
of [metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#later_rows_first3_set=48030]
later accepted rows. Acceptance itself used the full gallery, so this shows
the prior loses nothing on openings the reader accepts today; it cannot show
what a gated reader would newly accept.

*No accuracy gain.* Of
[metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#row_refused_openings=912]
openings refused for a row, measuring the margin within the board's set
would pass [metric:prior_readers_audit/scoreboard-gated@sample5~prior-audit-20260929#row_refused_pass_within_board_set=1].
Rows fail on score, not on a rival outside the match. The gain is speed, and
batching has taken most of it.

*The circularity and its resolution.* The lineup takes each side's SET from
the board (`identity.board_side_sets`) and each SLOT from the top bar
(`identity.lineup_with_board`). A board gated on the lineup would feed the
lineup its own answer. So:

- The board never gates on the top bar or the lineup. Its prior is its own
  first three accepted full-gallery openings per session, then a full-gallery
  audit opening every tenth accepted opening and after every surprise.
- `board_side_sets` counts only full-gallery openings toward
  `BOARD_MIN_OPENINGS`; a gated opening declares `scope: board_first_openings`
  and may witness rows, dimming and deaths, never the set.
- The witness order for the set stays: board audit openings first, the top
  bar where the board refuses. The top bar keeps the full gallery, because it
  bootstraps and its guesses are weak: refused slots' guesses fall in the
  board's set on
  [metric:prior_readers_audit/lineup-topbar@lineup-sessions~prior-audit-20260929#guess_in_board=35]
  of [metric:prior_readers_audit/lineup-topbar@lineup-sessions~prior-audit-20260929#guess_with_board=67],
  named slots on
  [metric:prior_readers_audit/lineup-topbar@lineup-sessions~prior-audit-20260929#named_in_board=117]
  of [metric:prior_readers_audit/lineup-topbar@lineup-sessions~prior-audit-20260929#named_with_board=123].
- The gate for a gated row reads the score (`AGENT_SCORE_MIN`), since a margin
  within five is not the margin the cuts were fitted on; refit the margin on
  audit rows before using it.

*Experiment.* Time the scorer on the cached minute of `a06f04a0059f` through
`reticle trial --reader scoreboard` with the gallery cut to each side's five,
against the full 29, when the GPU is free. Build only if the saving matters
after batching.

### Further, lower

6. **Killfeed follow in the reader.** Parse a band fully only when it is new;
   a band the last frame predicts (same divider column, same slot or one
   higher) verifies by comparing crops; the stack's direction is now a fact
   [domain:killfeed/stack-order]. Wipe bands already die on persistence in
   `checks.track_entries`, so the gain is cost and consistency.
7. **The round clock counts down.** Consecutive reads within 1.5 s break the
   countdown on
   [metric:prior_readers_audit/clock-countdown@a06f04a0059f~prior-audit-20260929#surprises=11]
   of [metric:prior_readers_audit/clock-countdown@a06f04a0059f~prior-audit-20260929#pairs=1784]
   pairs on `a06f04a0059f`, and
   [metric:prior_readers_audit/clock-countdown@a06f04a0059f~prior-audit-20260929#unread_bracketed=154]
   unread samples sit between two reads that agree with a countdown. A
   verify of the predicted digits could read them; `gametime` already
   bridges such gaps from storage, so the gain is small.
8. **A roster drop predicts a killfeed entry.** A targeted native-rate reread
   of the killfeed crop cache round an unexplained drop can recover the
   entries the Shooting Error box hides. A recovered entry rests on the
   roster and must leave the killfeed-roster audit, or the auditor audits
   itself.

Readers to leave prior-free: roster, combat report, menu, ult lines, the top
bar, and the board's audit openings (guard 5).

## 4. Where the repo already does this, and where it assumes a prior

**Already prior-driven, and declared.**

- `adjudication.tray_kit` with the lazy scorer in `cli` (`score` inside the
  tray-kit command): player, allies, all; `widened` with its reason;
  `depends_on` per set. The one reader that saves work by its prior.
- `identity._self_icon_claim`: ranks among the ally five, declares
  `depends_on`, and stores `global_best` and `rank_of_pick`, so the surprise
  survives. The global best fell outside the ally five on
  [metric:prior_readers_audit/lineup-topbar@lineup-sessions~prior-audit-20260929#global_best_outside_ally_five=6]
  of [metric:prior_readers_audit/lineup-topbar@lineup-sessions~prior-audit-20260929#self_icon_claims=21]
  lineups.
- `identity.side_candidates`: a refused slot enters as a rival and a slot
  with no guess blinds the side.
- `death.follow_entry_portraits`: an entry followed by its own key.
- `smoke_owner`: the ally side's smoke agents, `depends_on` the slots.
- `scoreboard`: strip-anchored blocks declare `anchor`, and
  `adjudication.scoreboard` separates `both` from `both_anchored`.
- `team_vision`: the teardrop's facing stays out of the track history, and
  the vision at t reads only entities accepted before t, so nothing iterates
  to a fixed point.
- `self_icon`: frames gated on the roster's five alive allies, an opportunity
  gate independent of the tray.
- `round_entities` 0.8.0 states that killfeed deaths now bar dead teammates
  and are "no longer an independent check of the names".

**A prior assumed, or used and never checked.**

- `minimap.pick_self` chooses by the previous point and falls through to the
  highest coverage without saying which path chose; no surprise row exists
  (section 3, item 2).
- `minimap.filter_track` returns interpolated points as plain tuples beside
  measured ones, while `docs/ADJUDICATION_DESIGN.md` requires that
  interpolation render distinctly. The raw reads stay stored; the returned
  track does not mark what it invented. (2026-09-29: `filter_track(...,
  mark=True)` now marks each point; the default is unchanged, and nothing
  stores the output. `pick_self_declared` names the pick's rule.)
- **The killfeed stack's direction was two beliefs; the player settled it**
  on 2026-09-29 [domain:killfeed/stack-order]. `death.follow_entry_portraits`
  and `checks.track_entries` matched the fact and now cite it; `killfeed.py`'s
  docstrings said the reverse, and no code read them. Stored rows agree: a
  divider-matched entry fell a slot on
  [metric:killfeed_stack_order/pairs@stored-hud~stack-order-20260929#falls=7]
  of [metric:killfeed_stack_order/pairs@stored-hud~stack-order-20260929#matched_pairs=28356]
  consecutive pairs, and a new entry arrived below every entry already on
  screen on
  [metric:killfeed_stack_order/pairs@stored-hud~stack-order-20260929#arrivals_below_all=1518]
  of [metric:killfeed_stack_order/pairs@stored-hud~stack-order-20260929#arrivals_with_entry_on_screen=1625]
  arrivals; most of the rest sit where the previous sample held an unparsed
  band. The walk's nearest-slot rule still gives a risen entry to the expired
  track above it when dividers and victim sides agree:
  [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#welded_entries=45]
  of [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#entries=3310]
  entries, of which
  [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#welded_player_deaths=3]
  are the player's deaths. The follow then binds
  [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#welded_views_bound=213]
  of their
  [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#welded_views_if_unwelded=358]
  views: the old symptom, by a new path.
- `follow_entry_portraits` skips a frame where two slots fit the key and
  stores nothing, so the ambiguity rate cannot be counted.
- `tray_kit` accepts the player's kit as a lone candidate with no audit
  cadence: while the fit passes, the catalogue never checks it.
- `ally_icons` consulted the roster once, to sweep `ALLY_COV_MIN`; the prior
  exists and no frame asks it.
- `AGENTS.md` says a smoke "is sought from the agents in the match, near where
  their abilities land". The owner uses the agents; `minimap_dark` searches
  the whole floor, and nothing searches near where abilities land.

## Order of work, if the player accepts

1. Declare before changing: `scope` on gated rows, the pick path in
   `pick_self`, an interpolation flag in `filter_track`, a stored ambiguity row
   in the follow. No output changes, so `reticle verify --tier fast` must pass
   unchanged.
2. Run the four stored-row experiments above (items 1-4); log predictions in
   `notes/predictions.jsonl` first. The killfeed stack check is done
   (section 4).
3. Build the ally window search if item 1's isolated misses are real, scored
   against the player's blind labels before it is wired.
4. The belief-rule amendment is decided (section 2); build the scoreboard's
   own prior if the timing still matters.
