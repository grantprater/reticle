# Reticle backlog summary

`BACKLOG.md` contains work deliberately deferred rather than abandoned. Each
item records why it is deferred and what event would make it worth resuming.
Items marked closed, answered, or superseded are summarized for historical
context only.

## Highest-priority work

### Deaths as identity-bearing events

- The central product goal is an event stream containing death identity,
  location, and eventually movement/orientation. Current roster and minimap
  tables provide counts or unstable positional slots, not agent identity.
- Use the existing lineup composition matcher on occupied roster slots to
  recover the alive agent set at each sampled time. Difference that set at
  killfeed death times to identify victims, preserve disagreements, and combine
  the result with the X-mark location.
- The killfeed team mask and weapon/ability divider provide independent checks.
  Gunfire usually gives both enemy icon and death mark; utility kills and falls
  may provide location without identity.
- Step 1 (ordered roster assignment) is built, but incomplete lineups are the
  binding constraint. Next: compute margins against assignment-consistent
  alternatives, apply self/tray evidence to all slots, then revisit coverage.
  Only afterward should death identities be promoted into the event stream.

### Measure enemy vision trailing persistence

- Enemy icons can remain drawn briefly after leaving the team viewcone. Measure
  the duration, whether abilities behave like players, and the terminal marker
  state.
- Use stored lighting and enemy tracks, excluding deaths via the killfeed. If
  stored data is insufficient, review short frame windows manually.
- This measurement must precede the enemy vision gate; otherwise true trailing
  detections would be incorrectly refused. Trigger: now.

### Wire the enemy vision gate safely

- Enemy entities should be expected only where the drawn-light channel says the
  team can see, but lighting is a refusal signal, not confirmation or ground
  truth. Unknown pixels are not dark.
- The gate must retain refused detections and distinguish them from reveal
  events. Sova dart pulses are the explicit exception for enemy players; the
  dart reveals a line-of-sight set, not the drawn circle's projected area.
- Scope the rule to enemy-side entities. Own-team icons are always visible, and
  enemy-side spike/ability entities do not receive the player-reveal exception.
- Trigger: the measured persistence window and the G3 enemy-reader work in the
  appearance-matching plan.

### Correct the fact registry

- `domain/*.toml` has typed, cited, dependency-checked facts but no subject.
  Add a controlled-vocabulary `subject` so facts can be queried by agent,
  ability, phase, or icon.
- Add `given` for conditional claims so they can be evaluated against an
  identity-bearing event log.
- Add `subject` first because it is cheap and useful immediately; defer the
  graph-like conditional layer until deaths have identity.

## Minimap and self-reader backlog

### Reject unlit ally icons carefully

- An ally should produce nearby light; unlit detections are often barriers,
  death marks, or scenery. The rule removes many false allies but can reject
  everything in frames with little lit area.
- Implement it as a persistent tracker rule with a light-budget guard, not a
  one-frame hard gate. Use the roster to distinguish a permitted missing ally
  from an extra phantom.
- Trigger: any consumer relying on ally counts; first obtain fresh roster data.

### Recover missing emitters from residual light

- Leave-one-out residual light predicts the rough direction of a missing
  emitter, not an accurate bearing. It is useful to bridge a short detection gap
  but must not override a detected icon or be validated by explained area.
- Trigger: a track that persists through a detection gap. Validate against
  held-out detections.

### Keep L1 refusal and widget absence distinct

- Both currently become `self_x = NULL`, so downstream tracking cannot tell a
  refused read from an absent widget.
- Add a stored `widget_drawn` column, bump the minimap version, and rebuild the
  stale sessions. The ally-channel proxy is only a conservative interim rule.

### Rebuild stale minimap L1 datasets

- Most stored tables predate the Step 1 self reader and contain positions that
  the current reader would refuse. Do not use them as a current adjudication
  baseline.
- Re-decode the old sessions together with `widget_drawn`; this is the required
  prerequisite for model work using stored minimap positions.

### Respect coincident icons

- Icons may overlap [domain:minimap/coincident-icons]. Never use another icon's
  position to exclude a belief region or assume distinct centers can be
  recovered.
- Same-colour fragments may still be deduplicated inside the detector; that is
  different from claiming that two entities cannot overlap.

### Fix self-icon confusions

- The self fit can land on the carried/dropped spike, yellow site paint, or a
  teammate. Motion limits do not catch nearby wrong objects because the drift
  can be made of small legal steps.
- The spike is inside the self colour key and visually resembles a ring. Shape,
  silhouette, interior value, dot pattern, and the 180-degree pickup rotation
  are the useful discriminators; ring quality and arc coverage are not.
- `inner_v`/interior evidence is already computed but not retained. A raised
  coverage gate improves accuracy but costs coverage and is directionally
  biased by bearing, so measure it only with the belief layer end to end.
- Photometric vicinity can temporarily gate accepted reads, but the durable
  solution is a segmented glyph reader. The spike reader needs state-labelled
  pickup windows and must not rely on broken `self_mask` components.
- Self appearance recovery was tested and closed: it worked at native rate but
  collapsed at real sampling tiers because refusals arrive in long runs without
  trusted anchors. Model overlap and directional geometry instead of retuning a
  score.

### Do not wire inertial holding yet

- Constant-velocity prediction does not consistently beat a stationary hold,
  but false spike accepts make stationary holding look better than it may be.
- Re-evaluate after self false accepts are removed; do not promote inertia from
  the contaminated comparison.

### Revalidate minimap data after floor-mask changes

- Old minimap tracks include known off-paint phantoms from the superseded mask.
  Re-read L1 minimap data before quoting any minimap metric.
- Re-run `xmark_eval`; treat old chokepoint comparisons as incomparable because
  their reference ridges changed with the mask. Trigger: before any further
  minimap measurement.

### Fix the Lotus small-widget plant mask

- `lotus__valorant-16x9` identifies only about 41% of expected plant zones, far
  below the other geometry keys. This is not explained by normal widget-scale
  degradation.
- Trigger: the first minimap read on that key or any change to the plant tint
  test. Score all geometry keys when touching the shared test.

## Ability detection and event evidence

### Build a general ability detector, not one detector per family

- No ability detector is currently shipped in `reticle/`; the five prototypes
  were triaged. Evaluation-only code stays a scorer, cone seeding is already
  covered elsewhere, signed thresholds wait for more labels, and the
  family-specific disc detector is only a possible candidate channel.
- The peak-finder experiment failed on painted frames: response maxima created
  many false positives and recall was non-monotonic because merged blobs exceed
  the area cap.
- If the disc primitive is revisited, scale it from the self radius per session
  and replace global thresholding with local maxima or watershed. Require
  independent precision labels before selecting an operating point.
- Acquisition remains limited by dim devices and narrow validation diversity.
  Broaden painted data across maps and agents; keep a low-contrast ranking path.

### Use ability-kill icons as corroborating evidence

- A killfeed ability icon gives a timestamped ability use and named owner, which
  could anchor gallery phases and owner/death relationships.
- It is biased toward damaging abilities and cannot represent smokes, walls,
  recon, or other non-damaging uses. Identify the ability icon only after using
  it as corroboration; a full per-ability template bank is expensive.

### Model recon dart pulses as origins

- A Sova dart creates two discrete reveal pulses. Each pulse reveals only what
  it can see from the dart's actual, possibly elevated position.
- Treat the revealed enemy set as the observation; the minimap circle is only a
  bound and must not be raycast as ground coverage. Trigger: when the enemy
  channel needs a reveal origin.

### Record the player's agent

- The stored minimap sessions lack the player's agent, blocking identity-
  conditional teleport analysis. Capture a one-word agent tag at ingest, and/or
  derive it from ally roster portraits using the existing composition matcher.
- Trigger: next capture for tagging; next ally-roster read for derivation.

### Measure dash behavior

- Existing refused-motion data shows a smooth speed tail rather than a distinct
  dash mode, so `walker_dash` should not be retained as a class on current data.
- Trigger: one tagged session with Jett, Neon, or Waylay. If no mode appears,
  delete the class.

### Improve audio corroboration

- Running does not yet have a robust audio classifier: broadband RMS is nearly
  unchanged, while cadence features are more promising but only partly tested.
- Audio is likely more valuable as a cheap video index and as an independent
  event witness. Ultimate references already exist; basic ability sounds need a
  controlled recording pass.
- Record while standing still, pause about three seconds between casts, and
  cast abilities in order. Reuse `prototypes/passes.py` and preserve clean
  pre-cast baselines. Yoru's fake teleport makes audio disambiguation important.

### Use analysis-by-synthesis cautiously

- Hypothesize an event, render its expected pixels/audio, and fit the residual
  to turn the unexplained tail into evidence. This could handle washes, glyph
  visibility, and facing better than isolated detectors.
- The hypothesis space is combinatorial, audio is spatialized, and a bad
  forward model produces confident wrong fits. Require independent witnesses
  and bounded hypotheses before investing.

## Round, coaching, and review infrastructure

### Reconcile round boundaries

- Clock, phase, and scoreboard currently place about 20% of coaching events near
  uncertain boundaries. Plant inference using future clock gaps cannot be used
  as a prediction-time feature.
- This is the next coaching task after the roster gate. The two-score-read guard
  remains diagnostic rather than authoritative.

### Define no-kill/no-contact episodes

- These require entity IDs, direction separation, and minimap occluder geometry.
  A review control sample now exists, but it is not yet a verified no-contact
  denominator.
- Trigger: killfeed events linked to entity identities, plus minimap
  revalidation and ally identity.

### Establish frozen statistical progression

- Track economy, phase, side, map, and agent with shrinkage and chronological
  evaluation. Leave-session-out remains a diagnostic.
- Do not gather more rounds merely to satisfy a sample-size target until roster
  and eligibility gates are trusted.

### Add correction history

- Human corrections must preserve the original observation and use a correction
  key rather than silently overwriting data.
- Trigger: the first actual disagreement with a stored event; no review evidence
  exists yet, so implementation is intentionally deferred.

## Ownership boundaries

### Three boundaries the ownership index records without resolving

- `minimap_lifecycle` and `round_lifetimes` both own lifecycle vocabulary. The
  working split is detector-local quarantine against round-scoped physical
  entity, and nothing states it. Trigger: a consumer needing one identity across
  both, or a third module that speaks lifecycle.
- `reconciliation` has no ceiling and is where a cross-channel identity claim
  will be tempted next. `ownership.toml` forbids that in prose only. Trigger:
  `agent-identity` getting an owner; decide then between a new module and a
  narrowed `reconciliation`.
- `ability_phases.ally_deaths` is a cross-channel read inside a command adapter.
  Trigger: the next change to phase transition causes.

## Geometry, map state, and maintenance

### Bake buy-phase barriers into map state

- Spawn barriers are static, side-specific map furniture drawn in team colour.
  Store their anchor positions per `(map, profile, side)` and use them both to
  explain false ally detections and to validate phase/geometry alignment.
- Anchors are not full extents; detect the barrier on its own colour. Trigger:
  the next map-state pass.

### Remove genuinely superseded prototypes

- Some old enemy-teacher and minimap prototypes are likely dead, but the orphan
  check cannot reliably determine that because documentation and dependencies
  mask entries.
- Do not delete yet. Re-aim the backlog entry toward the actual eight `doctor`
  findings or make a judgment call about the old cluster; retain Git history.

### Handle constants and stale artifacts deliberately

- A forked constant caused a real measurement mismatch and has been unified.
  A broad constant checker was rejected because it failed on unrelated knobs.
- Revisit only after a second costly fork reveals a discriminating pattern. The
  shade-stamp line-ending bug is closed: hashing now normalizes line endings,
  includes the relevant floor/art inputs, and all artifacts were rebuilt.

### Correct documentation and stale plans

- The published reconciliation plan still contains a superseded slab-only
  conclusion. Correct it when the document is next used.
- `README.md` needs updating because it says several shipped readers are
  unbuilt and describes stage 02 incorrectly.

## Closed or answered items

- Blur-based killfeed wipe separation was superseded by persistence and then by
  render-order validation. Do not fit blur thresholds on frozen test windows.
- The 587c15 roster scan was completed; most windows agree, while the remaining
  disagreements moved to live notes.
- Geometry is now keyed by map and profile, official art is authoritative where
  it fits, and the mis-tagged `2ba870ccbd50` session was confirmed as Ascent
  large-widget data.
- `filter_track` identity conditioning, evidence-based teleport licensing,
  self-ring fitting, shared minimap/cone plumbing, and the previously unwired
  `refine` module were implemented or resolved.
- The small-widget geometry scaling direction was implemented but remains
  unpainted and unscored until a small-widget session is actually read.
- The main appearance-matching self-recovery proposal is closed after failing at
  operational sampling tiers; overlap and glyph-shape work supersede it.

## Practical ordering

1. Finish lineup verdict logic and obtain complete enough identity coverage.
2. Produce identity-bearing death events and preserve disagreements.
3. Measure enemy vision trailing persistence, then implement the stored
   disagreement/refusal gate.
4. Rebuild stale minimap L1 data with `widget_drawn` before quoting metrics.
5. Address self/spike confusion and broaden ability acquisition labels.
6. Only then advance coaching statistics, no-contact semantics, and the fact
   graph's conditional validation.
