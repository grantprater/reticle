# Reticle notes summary

This document summarizes the points in `NOTES.md`. Later entries supersede
earlier ones where noted; historical measurements are retained here for
context, not as current baselines.

## Current handoff — 2026-09-11

### Ownership is declared and checked

- `ownership.toml` names the owner of every question a module may decide, with
  the `not_for` boundary that stops a module being selected by name. `doctor`'s
  OWNERSHIP check verifies it: 47 entries, 26 infrastructure modules, all 64
  modules placed once. An owner claims its entry in its own docstring.
- The registry replaced a proposed hand-written index. A restatement of 63
  module boundaries drifts, an unchecked declaration is satisfied by declaring
  everything, and the index pass missed what a check found at once.
- What it found: `reticle/adjudication/` sat in no layer, because the layer
  check globbed `*.py` and could not see a directory, hiding an eager upward
  import from `adjudication.ability` into `ability_timeline`. The blind spot is
  fixed and the edge removed by moving `ability_timeline` and `ability_coverage`
  into the adjudication layer, where their own definition puts them.
- Five questions are declared unowned and print every run: `agent-identity`,
  `death-victim`, `ability-owner`, `ability-detection`, `fact-subject`.

## Earlier handoff — 2026-09-10

### Lineup and identity are the immediate blocker

- `prototypes/roster_identity.py` can infer the living agents on each side by
  treating the packed roster as an ordered subsequence of the five known
  agents. This reduces the assignment problem to at most ten candidates and
  provides the hook for naming deaths by differencing alive sets.
- The player identity result was previously attributed to the wrong witness.
  The ability tray, top bar, and self icon are the intended independent
  witnesses; the tray decided the a06 session. Assignment already works at
  83.5% on held-out data, so perception is not the present blocker.
- Of 79 refused slots, 12 were ties already resolved by assignment, 11 need
  cross-side elimination (which is forbidden), and 56 have no named candidate
  from any witness. The margin must therefore be measured against the best
  assignment-consistent alternative, and self/tray evidence must be applied to
  all ten slots rather than only the player slot.
- Cross-match assignment must remain per side because both teams may contain
  the same agent. A single ten-slot assignment would create false identities.
- Coverage remains incomplete: ally sides name 3–5 of 5 agents, enemy sides
  name 0–3, and 33 sessions have no lineup. Incomplete sides must refuse rather
  than silently assign unnamed slots.
- The first run exposed three logic bugs: a one-candidate case looked maximally
  confident, unnamed slots unfairly lost assignments, and a duplicate
  `read_session` function triggered `doctor`. These are corrected or refused.
- Next order: fix assignment-relative margins; extend self/tray witnesses to
  every slot; then revisit full-side accumulation and the provisional margin
  threshold. After that, difference alive sets at killfeed times to produce
  identity-bearing deaths and compare them with known deaths.

### Deaths with identity are the north star

- No current channel stores agent identity: roster stores counts, HUD stores
  team masks, and minimap ally slots are not stable identities. Death times and
  ally death locations are available, but the victim name is not.
- The existing lineup matcher is the missing anchor. Occupied roster slots can
  be mapped to named agents per instant; removing an agent from that set at a
  killfeed time identifies the victim. Disagreements between the two sides are
  valuable output, not something to hide.
- The target artifact is an event stream with identity and location. Identity
  is required to test movement, continuity, teleport, existence, and origin
  rules. The annotated match is validation for that stream.
- Enemy death locations are stronger than previously recorded: gunfire usually
  shows both the victim icon and the X mark, because the victim was visible to
  the shooter. Ability kills and falls may lack the mark. A simple gun-versus-
  ability classification of the killfeed weapon slot can separate these cases.
- The fact registry is missing a subject and cannot properly represent
  conditional facts. A future minimal fix is `subject` plus `given`; a graph is
  intentionally deferred until event identity exists.

### Minimap acquisition and the a06 explanation

- Repainting a06 with larger matching radii did not change recall or precision,
  proving radius was not the cause of its missed icons. The correct icon radius
  is 12 px (24 px across), not the earlier 20–25 px claim.
- The remaining miss is a dim device. Acquired icons have median contrast 240
  and filled fraction 0.46; the missed icon has contrast 173 and fraction 0.11,
  matching the recorded dim state. The `base` area-gated channel survives this
  better than the `core` channel.
- Labels now explicitly define radius as the icon disc only; connected
  multi-segment objects are one icon per node plus a separate span region.
- The next acquisition work is broader sampling across maps and agents. Keep a
  low-contrast channel for ranking rather than gating, and do not fit the
  system to one missed icon.

### Area-band correction and geometry discipline

- Independent labels showed that the previous area cap was fitted to player
  icons. Median extents are roughly 13 px for players, 24 px for ability icons,
  and 27 px for regions. The cap was widened from `(10, 400)` to `(10, 500)`.
- This recovered d95 recall from 77.1% to 93.8% with only a small precision
  increase and left a06 unchanged as predicted. Most recovered misses were
  icons welded to nearby structures.
- Domain facts now live in `domain/*.toml` and are checked for dangling
  citations. A proposed forked-constant check was rejected because it failed
  on a clean repository; stale art hashing still needs a deliberate rebuild.

### Proposal pool and mining conclusions

- Baked `(map, profile)` geometry replaced retired per-session static maps. The
  change barely moved proposal results, confirming the old comparison was
  dependency-invalid rather than substantively different.
- Missed icons are usually rings joined by thin necks to cones, lines, nearby
  icons, or map structure. Hole filling creates usable discs; a distance-
  transform `core` channel is precise but fails on dim a06 icons.
- The acquisition pool is therefore the union of `base`, `neck`, and `core`,
  not a replacement of one channel with another. Validation diversity is still
  too small for a general inventory claim.
- Mining review concluded that proposal recall and cluster purity must be
  measured before interpreting clusters. Position is useful for instance
  association, not family identity; appearance-only clustering fragments
  similar noise; contrast should rank candidates with a retained low-contrast
  audit path. Compare deterministic full-glyph/tracklet mining with a learned
  challenger at explicit labeling budgets, using held-out extraction accuracy,
  coverage, and human effort.
- The first mining run found static subtraction was inert, appearance-only
  clustering produced 254 fragmented clusters, and rotation matching had no
  null model. Recurrence spread and contrast accidentally revealed the useful
  distinction: fixed objects recur near one position, players spread widely,
  and low-contrast speckle recurs poorly. These historical interpretations are
  superseded by the review above.

## Recent completed threads

### Self reader, killfeed, and P3

- The self reader is accurate for accepted positions (87.49%), but its anchors
  are contaminated and observed fixes were overstated. Arc coverage was the
  only useful discriminator, but it is biased by facing direction and costs
  coverage; the player icon can be confused with the carried spike badge.
- Step 1 replaced fragmented self-colour blobs with a fitted self icon and no
  blob fallback. Agreement improved to about 0.985–0.994 across sampled rates,
  while roughly 28% of frames correctly refuse due to insufficient evidence.
- The next self step is exemplar matching over rotations, using forced
  correspondences and normalized two-state backgrounds. Nearest exemplars
  beat per-agent averages in the existing prototype.
- Killfeed persistence thresholds removed rate-dependent false positives, but a
  camera wipe remains in a supposedly clean frozen window. The stronger rule is
  render-order consistency: a fully formed band appearing in one frame is a
  wash, and a band losing contents while its plate and divider remain is one
  blinking entry. Put this rule in `analyse_killfeed`, re-review the window, and
  freeze a second-session comparison.
- Transport, not frame count, dominates runtime when sampling windows. Seeking
  directly to requested windows is the important performance result; adaptive
  accuracy is not yet accepted.

### Architecture and ability-line results

- P0–P3 architecture work added shared sampling, immutable gallery/phase
  revisions, bounded identity histories, acquisition planning, and execution
  over shared decode routes. This is a foundation, not validated adaptive
  performance; P0 and P2 review gates remain.
- Temporal shape failed to distinguish Deadlock Sonic Sensor from Barrier Mesh
  across held-out directions. The sensor is bimodal because devices dim on
  deactivation, so the gallery must be conditioned on phase before rerunning.
- The corpus cannot support broad leave-one-session-out learning: only one
  held-out contrast exists and most abilities occur in one session. Labeling
  must focus on Deadlock first, then owner-death linkage.
- Important ability facts: objects can last under two seconds, simultaneous tray
  drops are transition wipes, devices dim after deactivation, entities can
  transform, and position persistence disagrees with onset proximity in the
  transforming cases.
- Ability modeling should represent origin, optional deployment vector, extent
  kind, mode, and causal event. Cast detection gives the event more reliably
  than the final position. Deployables emit cones; deployed smokes form an
  agent-independent class; placement hold time is unbounded; and Skye healing
  drains only while healing.

### Geometry, barriers, and lighting

- Official art is now the authoritative source for minimap floor and terrain
  classes. Geometry is keyed by `(map, profile)`, stamped through the art path,
  and guarded on writes. Most maps use art; Summit remains derived because its
  art fit is below the minimum threshold.
- The barrier law is exactly three connected territories in a path: ally,
  neutral, enemy. Reachability excludes pre-existing isolated pockets. Sunset
  has nine barriers, including one diagonal barrier that axis-aligned width/
  height missed. One candidate still fails to span its doorway; measure it on
  its principal axis before baking, and do not tune a growth constant merely to
  obtain three regions.
- The enemy channel previously used fitted centers and the dilated floor,
  producing architecture and border phantoms. Slab support and barrier gating
  remove most of these. Doorway phantoms remain a photometric problem caused by
  buy-phase variation; fit reference states on live-phase frames.
- Lighting version 0.3.0 fixed a second crossing where pixels brighter than the
  lit reference were classified dark. This is a consistency correction, not a
  visual-accuracy proof. Full-round outputs made with the old lighting version
  must be regenerated before drawing conclusions.
- The viewcone is a crosscheck, not ground truth. The raycast overclaims area,
  and its statistic conflicts with selected visual grids. Re-measure the
  distribution of precision, recall, and area ratio by distance from the
  emitter after rerendering with the corrected lighting.

### Identity, roster, and round lifetime history

- Roster bars pack survivors toward one edge, so fixed slot indices change
  identity after deaths. Accumulating lineup evidence only while a side is fully
  alive corrected Sunset from 2/5 to 5/5 named agents and prevented averaged
  identities. Lotus still has two deliberately refused portrait matches.
- The HUD death signal is real, but the dimmed index is a packed living-slot
  position rather than a canonical player slot. It named the wrong victim in
  both tested rounds and must not be used until death order/packing state is
  tracked.
- The player identity is supported by top-bar composition, self-icon ranking,
  and a tray glyph gate. Tray quality must be checked before its confidence is
  trusted; a bright Lotus background once produced a confident wrong answer.
  Abstention and disagreement are separate outcomes.
- Barriers, doors, cracks, pings, and spike states are different structural or
  phase witnesses. Barriers are buy-phase map furniture; doors are global
  in-use events with audio corroboration; cracks are static map art; and Sova's
  dart reveals a line-of-sight set from a variable-height origin, so its drawn
  circle is not ground coverage. KAY/O's knife is a radius reveal through walls.
- Round-lifetime names are now English and fixed at birth, which exposes
  fragmentation without pretending to know the agent. Appearance-only
  reacquisition becomes vacuous after the widget diagonal divided by walking
  speed (14.6 s); long gaps, especially enemy observations, must be refused or
  explicitly marked as appearance-only.
- The self track was reduced from many IDs to one by using measured fit error,
  elapsed-time gaps, suspension across absent widgets, and same-frame duplicate
  collapse. Teleports require corroboration from an icon, cone, audio, or
  observed destination; distance alone is only an explicitly marked fallback.
- The shared stall classification belongs in `l1/primitives`, since it is a
  source-frame property. Readers should join the stored spans rather than emit
  channel-specific stall events. HUD, roster, and ping are not yet wired to
  suppress or interpret stall rows.

## Earlier research and implementation history

### Base minimap and cone channel

- The base minimap layer, art warp, floor mask, vectorized cone raycast, icon
  fitting, tracking, and overlay rendering were promoted into `reticle/`.
- Early measurements showed the widget must be solved as layers: base art,
  annotations, icons, and lighting. The raw bearing flipped 180 degrees on a
  substantial fraction of frames, and cone area overclaim was large and
  spatially uneven. The current cone half-angle is 51.5 degrees, but it needs
  confirmation on another map.
- The next historical plan was to subtract audio rings and icons, recover ally
  identity, then test interior appearance. Subsequent roster and geometry work
  supersedes much of that sequence.

### Events, audio, pings, and data foundations

- The entity model defines existence intervals from origin events. Most origin
  classes have readers; the remaining ability detector was still missing.
- Audio and ability-tray evidence agree on six of six tested casts within one
  50 ms bin. An equip sound is an independent event witness; one teleport cast
  had several seconds of silence before it. The next work is to cut frozen
  audio references and connect them to event adjudication.
- Pings were detected, but the requested clip showed no growth phase: the
  marker appears and then stays. Two clips still need ingestion with real
  session IDs; void pings are invisible, `on_my_way` is close in hue to
  `need_help`, and `watching_here` has too little data for claims.
- Shared decode, census tooling, versioned metrics, `doctor`, stored roster
  counts, and the track/entity documentation were established. The system's
  target remains aggregated, causal, temporal entity inference rather than
  isolated frame labels.
- The ability labelling pass rejected pooled `patch_range` claims and found
  per-session z-scoring more useful than learned weighting. Equal-weight,
  per-session standardized scores are the current honest baseline, but are not
  a shipped reader.

## Live defects

- `hud-0.8.1` has one known read error and two unexplained event gaps among 372
  events. The raw gap is eight against known K/D; five are verified Run It Back
  cases, one is the ability kill below, and two deaths in `e37fdeca944f` remain
  unreviewed.
- One real killfeed miss is an ability kill at 13:14 in `c40d950031bb`. It has
  no weapon icon, and the ability mark fragments under the text cut. A divider
  based on the plate-colour boundary is the proposed fix; a prototype split 6
  of 8 test bands correctly.
- Scoreline OCR briefly adds a spurious leading `1` (`1→11→1` and `9→19→9`)
  in `9acf02f98283`, producing eight verification violations. It is transient
  and independent of killfeed parsing; clock coverage is also low there.
- `README.md` is stale: it says HP, ammo, and killfeed are unbuilt and still
  describes stage 02 as scoreline-only. Update it when that area is next
  touched.

## Repository state at the latest handoff

The latest reported checks were 450 tests passing, with `doctor` reporting
findings but zero errors. The immediate work is verdict logic for complete,
identity-bearing lineups and then death-event identity; perception expansion,
coverage tuning, and older cone/mining hypotheses should wait behind those
gates.
