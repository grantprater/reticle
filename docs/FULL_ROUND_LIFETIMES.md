# Full-round entity lifetimes

Design saved 2026-09-08, before implementation. Extends the minimap entity
model and contiguous diagnostics; does not replace their observation semantics.

## Deliverable

Inspect both September 7/8 recordings (Lotus `7010b3d62460`, Sunset
`a1a995e6b19b`), rank complete rounds by overlap with source-stall spans, and
render at least one complete buy/live/post-round interval. Preserve real-time
playback, source timestamps and audio. Draw boxes and labels over observed
minimap entities and supported first-person detections. Save raw observations,
adjudications, lifetime summaries and render provenance beside the video.

## Entity coverage

Agents (self, ally, enemy), ability glyphs and regions, pings, spawn barriers,
spike (carried/dropped/planted when supported), death marks, last-known marks,
and viewcones. A generic dynamic object is an explicit unresolved class, not
automatically an ability. World-view outline candidates are not automatically
live enemies: corpses, reveal outlines, deployables and scenery are alternatives.
Ability tray icons are HUD observations and cannot establish a world location.

## Pipeline

1. Ingest original paths, using the inspected enlarged fixed minimap profile.
   Derive shared capture stalls from primitives. Inspect source boundary frames
   and score/clock transitions; choose a round without detected stalls if possible.
2. Reuse the current geometry and detector implementations. Capture all channels
   on shared decoded frames. Separate detector sampling rate from video rate;
   every rendered frame retains its actual timestamp and observation age.
3. Keep detector track IDs separate from round-scoped entity IDs. Short missing
   reads suspend position, not existence. Reacquisition must be unique under
   the motion law or an independent identity witness. Ambiguous assignments
   retain alternatives; round end censors unresolved lifetimes. No long-gap
   position extrapolation and no cones from carried positions.
4. Roster counts permit delayed acquisition but do not identify the candidate.
   Barriers require buy-phase/static map evidence; stationary players stay
   possible. Cross-reference barrier/ability evidence before admitting an ally.
   Missing/stale roster reads do not supply a count. Unknown origin remains
   null, distinct from first observation. Observed death and disappearance are
   different endings.
5. Combine existing enemy-ring, dynamic-object, ping and screen-outline readers
   with explicit competing class hypotheses. Never promote overlapping colour
   detections by majority vote. Use HUD spike evidence to distinguish planted
   state from a generic minimap glyph; do not invent the dropped-spike location.
6. Join first-person and minimap observations by time and compatible visibility
   evidence. This supports/refutes hypotheses, but does not establish one-to-one
   agent identity without a unique witness. Preserve contradictions and unlinked
   detections. Source stalls invalidate every channel.
7. Render labels above boxes with stable short IDs, class/state and uncertainty.
   Use a separate enlarged minimap panel when native-size labels become crowded.
   Fresh boxes and last-seen markers must be visually distinct. Never cover the
   source minimap with the diagnostic header. Include a machine-readable coverage
   report stating unsupported classes and unresolved intervals.

## Validation and stopping criteria

Before edits, run the existing lifecycle/diagnostic tests and a known two-second
Ascent control. Log falsifiable predictions in the external store: the control
retains one self and one ally; roster acquisition never allocates the same slot
twice; unobserved positions never become fresh evidence; every ID is round-scoped;
stalled samples cannot support any channel. Exercise absence, crowding, death,
round reset, competing class claims and source-stall cases with focused tests.

Re-run the real control, then render the selected full round and inspect source
and output at buy phase, barrier drop, combat, death and spike transitions where
present. Check output duration/frame count/audio and sidecar alignment. Report
fragmentation, unknowns and coverage separately from accuracy. If the first
perceptual approach fails, expose its source evidence for player review rather
than tuning blindly. A full-duration render is not proof of exhaustive recognition.

Implementation results and exact reproduction commands will be appended here.

---

## Implementation results, 2026-09-08

Reproduction, in order. `prototypes/full_round_entities.py` is the renderer,
`reticle/round_lifetimes.py` the association law, `tools/round_entity_review.py`
the offline player page.

    python prototypes/full_round_entities.py --select 7010b3d62460 a1a995e6b19b \
        --out ~/reticle-store/notes/full-round-selection-20260908.json
    python prototypes/full_round_entities.py 7010b3d62460 --round 15 \
        --out ~/reticle-store/notes/lotus-round15-20260908
    python tools/round_entity_review.py ~/reticle-store/notes/lotus-round15-20260908
    node tests/review_harness.cjs ~/reticle-store/notes/lotus-round15-20260908/review.html
    python -m reticle.round_lifetimes ~/reticle-store/notes/lotus-round15-20260908 \
        --out /tmp/replay.json          # reproduces lifetimes.json, no decode

**Selection.** 22 complete rounds across the two recordings, 21 of them with no
stalled capture at all, so the deliverable's "choose a round without detected
stalls if possible" was not a constraint. Ranked by stall, then player kills,
then plant: Lotus round 15 (3 kills, a plant) and Sunset round 6 (3 kills, no
plant) are the top two, and both are rendered.

### Lotus round 15 -- 100.5 s, 6030/6030 frames, 0 ms stalled

Detection at 10 Hz over 60 Hz video with source audio; every rendered frame
keeps its source timestamp and the age of the observation drawn on it. 1005
samples, the widget drawn in 994. 20,689 adjudicated observations:

    continuation             18,530   89.6%
    ambiguous_continuation      940    4.5%
    first_observed            1,219    5.9%

**Three classes hold across the whole round, and they are the ones with an
independent witness.**

    self       1 entity, all 100.5 s, 793 observations, one id start to end
    spike      1 entity; 239 of its 240 observations post-plant, 1 at the
               boundary -- the HUD plant flag and the minimap glyph agree
    barrier   12 entities, 1,950 observations, ALL of them in buy phase:
               0 in live, 0 post-plant. The phase rule separates completely.

**The rest is fragmentation, and it is concentrated in the unresolved classes.**
1,228 entity hypotheses for one round:

    object     660   median 3 observations, 0.4 s      222 seen exactly once
    ally_outline 239 median 1                          133 seen exactly once
    outline    183   median 1                          137 seen exactly once
    ally        81   median 4; the longest lives 63.1 s over 627 observations
    enemy       43   median 2; the longest 2.4 s -- but an enemy is only DRAWN
                     while revealed, so short lives here are expected
    hud_ability  8   median 82
    barrier     12 · self 1 · spike 1

Four allies over 100 s arriving as 81 hypotheses is the number to attack, and
1,082 of the 1,228 are `object?`/`outline?` -- explicitly unresolved classes,
not wrong answers. 492 of those are single observations.

**The limiter on the roster gate is the SELF icon, not the roster.** Capacity is
`alive_ally - 1` because the roster counts the player, so it needs an observed
self. Over 2,933 ally observations:

    roster_slot_available_not_identity   2,333   79.5%
    roster_unknown                         527   18.0%
    roster_count_conflict                   73    2.5%

The 527 are the samples with no self icon: 212 of 1005 samples, over 59 runs,
the widget drawn in all but 7 of them. 129 of those samples are in buy phase,
and the longest run (1446.1-1449.3 s, 3.2 s) is the SOURCE, not the detector --
the widget at round start draws no agent icons at all, which the pixels show
directly. So the refusal is correct and the cross-reference is still available:
the roster already says whether the player is alive, which separates "the
widget is not drawing me" from "I am spectating", and that is what the
`has_self` test currently cannot tell apart. Not built.

**The replay is exact.** `python -m reticle.round_lifetimes` over the stored
`observations.jsonl` reproduces all 1,228 entities byte for byte in 50 s
without decoding a frame -- so the adjudication can be re-run against a changed
law at no video cost. It reads the widget scale from provenance
(`full-round-0.2.0`) or derives it from the session manifest, and never assumes
it: the association law is in widget pixels, and an 8 px step in 100 ms is one
entity at scale 1.0 and two at 0.7118.

**The review page is built and is too long to ask for.** 2,457 candidates
(first/middle/last of every entity), and it passes `tests/review_harness.cjs`.
A player pass needs a sampled population -- the 660 `object?` entities would
dominate it -- so the page is not worth a player's time in this form.
