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
