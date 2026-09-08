# Minimap detection: contiguous evidence and correction

2026-09-08. Implemented: temporal association corrections and a reproducible
sequence diagnostic/review loop. Full entity recognition remains incomplete.

## Findings that determine the plan

The existing stack already fits icons, resolves bearing lobes against lighting,
raycasts cones, and assigns tracks. Temporal interpolation and residual ensemble
fitting are experiments to extend this stack, not replacement pipelines.

The first native-rate rendering exposed two implementation defects:

* Widget-absent frames returned before updating trackers; elapsed time alone
  did not expire a track. Tracks now expire after a configurable observation
  gap (500 ms default), and absent-widget samples advance both trackers.
* At 60 Hz the walking allowance is less than one pixel. Integer ring centers
  can therefore violate it through quantization alone. The overlay now supplies
  sqrt(0.5) native pixels of endpoint uncertainty to association. Motion-class
  laws and observed coordinates are unchanged. This is a quantization bound,
  not an estimate of the larger ring-fitting error.

Replaying the same two-second raw reads (298–300 s, 120 frames each) changes
track births as follows. These are fragmentation diagnostics, NOT accuracy:

| Map | Self, exact centers | Self, quantization bound | Allies, exact | Allies, bound |
|---|---:|---:|---:|---:|
| Ascent | 25 | 13 | 62 | 43 |
| Lotus | 21 | 10 | 18 | 11 |

The remaining churn is substantial. Ascent's sequence also visibly exposes
phantom allies through the translucent widget. Increasing motion tolerance
until IDs stop changing would conceal that defect and can merge real players.

## Implemented inspection loop

`reticle overlay SESSION --from 4:58 --seconds 2 --hz 60 --no-mask
--minimap-diagnostics --out UNIQUE.mp4` renders consecutive source frames for
these 60 Hz captures. One initial seek is followed by forward decode. The
existing shared frame serves HUD, icons, light, tracking, and rendering.
Use the source rate for contiguous frames; a lower rate is sampled review.

The JSONL sidecar records source identity, producer hashes, geometry/static
hashes, actual observation timestamps, raw icon fits, association IDs, carried
position ages, adjacent readable/lit pixel counts, and overlap by distance from
the nearest fresh emitter. Unknown light is never counted as unlit. Carried
positions never contribute a fresh cone. Output paths refuse overwrites.

`tools/minimap_sequence_summary.py UNIQUE.minimap.jsonl` recomputes association
churn and distance-bin counts without decoding media. `tools/minimap_sequence_review.py
UNIQUE.mp4` creates an offline review page beside the video. It supports frame
stepping, context playback, explicit classes including other/unsure, append-only
answer downloads and resumption by importing answers. No answer is seeded;
the player supplies attribution. Reviews record that derived annotations were
visible and must not be described as blinded ground truth.
Preview frames are embedded from the derived overlay so the page works offline
without depending on browser support for OpenCV's video codec. Generated page
scripts passed syntax checks; interactive UI QA was unavailable because no
browser was connected. Final Ascent/Lotus source-overlay frames were inspected.

## Next corrections, in dependency order

1. **Refresh comparable baselines.** Archive existing derived evidence before
   re-reading the five stored minimap sessions; doctor currently reports four
   version-stale tables. Re-run xmark evaluation on the current geometry.
   Chokepoint ground truth depends on the changed floor mask, so quote it only
   as a consistency check. Add roster reads to the same decode pass where absent.
2. **Adjudicate ally candidates across time.** Join adjacent light, raw ring
   fit, portrait interior, roster alive count, and motion support. Require
   readable local floor and a healthy global light budget before calling lack
   of local light a contradiction. Preserve stationary allies; immobility is
   not proof of a barrier. Require persistent contradiction before excluding
   a candidate from an inferred count or cone. Store raw and adjudicated rows
   separately, with reasons and dependency versions.
3. **Resolve cone geometry disagreement.** Use the new 0–20, 20–40, 40–60,
   60–100 and 100+ pixel bins, distributions per frame and pooled counts.
   Review predicted-only and lit-only regions on both maps. Unknown lighting,
   occluders, translucent void, near-icon masking, range falloff and mechanical
   doors are distinct hypotheses. Do not choose a range cap using overall
   overlap alone. Lighting used to resolve bearings cannot independently
   establish bearing accuracy.
4. **Fit entity lifecycles jointly.** Start candidate intervals from observed
   round, cast/equip, ping, death and loss-of-visibility evidence. First detection
   remains an observation time, not an inferred origin. Bind agent-specific
   motion/lifetime only when identity has independent support. Allow alternate
   associations at crossings; temporary missing observations keep uncertainty,
   not a fabricated position or bearing.
5. **Use residual ensemble fitting for gaps.** Fit missing emitters to residual
   light after supported cones are removed. Score position/bearing alternatives
   with wall/box geometry and held-out observations. Existing leave-one-out
   results support coarse direction, not precise bearings. Label inferred
   cones separately and exclude them from hard enemy-visibility rejection.
6. **Attach abilities and enemy states.** Join local tray changes, equip/cast
   audio, independently supported caster position/identity, glyph appearance,
   motion and lifetime. Preserve multiple plausible owners. Audio absence is
   not a veto outside established coverage; a teleport sound can be a fake.
   Enemy appearances inside predicted visibility are disagreements to review,
   accounting for reveals, occlusion, teleports and detector misses.

## Acceptance gates

Use fixed contiguous windows spanning ordinary play, overlap/crossings,
death/blackout, buy-panel obstruction, casts and pings, plus unselected no-event
windows. Keep a held-out map/session. Report coverage and first failures along
with precision/recall from actual player answers; report unsure separately.
Measure ID switches and fragmentation against reviewed correspondences, not
just fewer IDs. A count forced below five is not evidence of correctness.

Promote an adjudication gate only when it improves reviewed errors without
silently losing true stationary allies or low-light frames. Every promotion
gets a separate version, source evidence, real-command replay and sequence
render. The current increment fixes temporal mechanics and exposes failures;
it does not claim solved ability attribution or reliable full-match identities.

## Follow-up: birth constraints and the reviewed Lotus teleport

`reticle/minimap_lifecycle.py` now implements causal origin/continuity
adjudication. `--minimap-lifecycle` enables the gate in the overlay; default
rendering retains the ungated comparison. Missing origin evidence quarantines
inferences, never deletes raw observations. Window starts/blackouts are censored
boundaries, not proven births. Established entities may persist in unlit space;
a genuine non-ping origin there is a lighting contradiction. A repeated
quarantined candidate cannot corroborate itself by persistence alone.

`--minimap-events FILE.jsonl` accepts spatially linked, corroborated legal events
with separate occurrence and evidence-availability times. Teleport support
requires icon and viewcone evidence plus audio or destination corroboration;
audio alone cannot license relocation. The demonstrated Lotus Omen relocation
is ~52px around 299.217-299.317s. A player-supported event preserves the original
entity ID despite fragmented destination fits. This is a real-source integration
check with supplied identity/audio evidence, not automatic Omen recognition.

The two-second Ascent replay quarantines 55 observations (37 with unlit reads).
These are candidate failures, not measured precision: completed player answer
exports were not yet available. Keep the gate opt-in until those are scored.
New diagnostic sidecars contain clean minimap crops from the shared decode;
new review pages show them by default and can reveal debug overlays explicitly.
The existing Lotus page and player answers were not changed. 92 Python tests
and in-memory old/new review export checks pass.

## Follow-up: entity lifetimes, and a teleport licensed by evidence

`track.Corroboration` / `corroborates_teleport` is the single rule for a legal
discontinuity, shared by the tracker and the lifecycle: the icon AND the
viewcone must have relocated, tied to a predecessor entity by audio or an
observed destination, with source references. `admits(..., evidence=)` then
admits any distance above the walk ceiling, and `TELEPORT_PX` is demoted to the
no-event fallback, reporting `TELEPORT_ASSUMED` for every step it admits. The
reviewed ~52 px Lotus relocation is refused on distance and admitted on
evidence. Distance was the wrong axis: measured teleports are 4.6-65 px and
refused phantoms sit at the same distances.

Association is now bounded by a MEASURED error rather than by integer
quantization. `track.FIT_ERR_PX` (2.0 px) comes from forced correspondences --
the self icon is detected exactly once in every frame of both windows, so
consecutive detections are the same entity with no labelling -- and
`association_tolerance` adds `|dr|` for the fit's own radius disagreement,
which is derived rather than fitted. Track expiry is elapsed time only; the
frames-missed count made the budget depend on the sample rate. A widget that is
not drawn suspends the lifecycle rather than wiping identity.

A separate limit closes the ally half, and it is about RESOLUTION rather than
motion: the widget draws an icon about `2*R_MIN` across, so two same-role fits
closer than that are two fits of one icon. `Tracker.resolve` collapses the
same-frame pair, keeping the higher `cov`, and the birth path defers to an
unobserved track inside the limit -- which is how the alternation arrives, one
fit at a time. Every same-frame ally pair in the Ascent window is either
8.1-9.1 px apart or at least 45 px, with nothing between 10 and 45, so the
limit sits in a measured gap. `light_support` now excludes `R_MAX` rather than
each fit's own radius, so two candidates are scored on the same annulus.

Re-running the real command on the same two windows: Ascent self track keys
13 -> 1 (the icon is detected in all 120 frames, so anything above 1 is a
defect), ally 43 -> 14, quarantines 55 -> 51; Lotus self 10 -> 1, ally 11 -> 2,
and the six repeated relocation rows for one event fall to two. 97 tests.

**Cone availability falls on Lotus allies, 92/92 to 76/92, and that is the
gate working**: a one-sample window has a resultant of 1.0 by construction, so
fragmented tracks were bypassing `resolved_facing`'s ambiguity refusal rather
than passing it. The 16 refusals concentrate in the post-teleport destination
fits.

Two limits to carry forward. The birth deferral means an entity appearing
within `2*R_MIN` of where a different one was seen, inside the gap budget,
inherits that identity; and the separation gap is measured on one window, so
two allies standing together would sit inside it. Both fail toward one
identity rather than a phantom, which is the safe direction, but an ally count
quoted from this channel should say so.
