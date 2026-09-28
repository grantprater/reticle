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

### Sunset round 6 -- 79.0 s, 4740/4740 frames, 0 ms stalled

    python prototypes/full_round_entities.py a1a995e6b19b --round 6 \
        --out ~/reticle-store/notes/sunset-round6-20260908

790 samples, the widget drawn in 774, no plant in this round. The three
witnessed classes behave the same way on a second map: **the self icon is one
entity for the whole 76.8 s it is drawn, and all 2,625 barrier observations
fall in buy phase with none in live.** The self is observed in 79.4% of samples
against Lotus's 78.9% -- close enough that this looks like a property of the
widget rather than of a round.

One spike observation, in a round with no plant: a single-frame `SPIKE planted
(HUD)` read out of 790 samples. One false positive, not a class failure, but it
is the HUD flag the spike gating leans on.

**Rendering the second round is what found the defect, and Lotus alone would
not have.** The association law admits a long-gap re-acquisition on APPEARANCE
similarity when the motion law does not refuse it -- but the walker class is
45 px/s, so over a 658 px widget diagonal it stops being able to refuse
anything at

    dt = 658 px / 45 px per s = 14.6 s

Past that, `admits` returns True for every position on the map and a colour
histogram at 0.85 is the entire gate. Measured over the two rounds, counting
accepted continuations that cross a gap of more than a second:

    lotus R15     7 links,  0 past 14.6 s   longest gap  9.7 s
    sunset R6    64 links, 31 past 14.6 s   longest gap 76.9 s

61 of Sunset's 64 are enemies, which is where it hurts most: an enemy icon is
drawn only while revealed, so its observations are naturally sparse and the
appearance branch is reached constantly. `E0026` is three observations spanning
77.0 s with one 76.9 s gap -- an icon at the start of the round and an icon at
the end, declared the same enemy. That is the thing this document's own rule
forbids: *reacquisition must be unique under the motion law or an independent
identity witness*, and at 77 s neither holds.

**The bound is derivable rather than tuned**, which is the reason to state it
before choosing a fix: past `diagonal / max_px_s` the motion law is not a
constraint, so the branch should either refuse, or say out loud that appearance
is carrying the link alone. Not changed here -- it is the association law, and
it wants measuring against both rounds as controls, which the replay entry
point now makes cheap.

**Cost, separately.** The candidate-parent set never expires for ally/enemy
entities that have an appearance vector, so it grows all round -- 0 to 166 on
Lotus while the set seen within the last second stays at 30-50. 61% of the
1.86 M candidate pairs evaluated are against entities not seen for over a
second, and the render decelerates 4x from first block to last.

**Sunset fragments harder than Lotus** -- 1,691 entities in 79 s against 1,228
in 100.5 s -- and the growth is in the unresolved classes and in enemies:
835 `object?`, 248 `outline?`, 219 `ally_outline?`, 231 `enemy` (99 seen once),
86 `ally`, 57 `barrier`. Its review page is 3,055 candidates, which is again
too many to ask a player for.

### Sunset round 6 again, 2026-09-08 evening -- 1,671 -> 1,551 entities

    python prototypes/full_round_entities.py a1a995e6b19b --round 6 \
        --out ~/reticle-store/notes/sunset-round6-final-20260908

Same round, same 4740/4740 frames and 0 ms stalled, under `lighting-0.3.0`,
`round-lifetimes-0.4.0` and `full-round-0.10.0`. Four separate renders isolate
the four fixes, and the table is what each one costs and buys:

    render         entities   enemy ent   enemy obs   self obs   banner ent
    reconciled       1,671         166         531        627           57
    + stability      1,628         152         482        562            0
    + barrier gate   1,551          73         159        562            0

**Three of the four are the same shape: a channel that already knew.** The map's
own stability said the location-name banner is not structure; the barrier
channel said no enemy can be drawn yet; the tracker's own motion law said which
self candidate is reachable. None of them is a threshold on the channel that
produced the error, which is the rule in `CLAUDE.md`, and each is measured in
the module that owns it -- `minimap.floor_mask`, `full_round_entities.read`,
`track.Tracker.principal`.

**Refusals are now reported.** `coverage.json` carries a `refusals` block
counted from the stored samples, so the gates can be scored rather than
believed: `enemy_barrier_phase` 474, `enemy_no_slab_support` 128,
`ping_no_slab_support` 763.

**The self icon is now REFUSED rather than guessed.** Coverage falls from 81.0%
to 72.6% of drawn samples, and the worst step between consecutive reported
positions falls from 312.2 px to 13.9 px with nothing over 20 px. 38 of the 77
gaps are a single sample, which the renderer covers by holding the last box.
Six positions the player could not have walked to are gone.

**What the numbers say is left.** 1,551 entities for a round with ten agents:
503 `?`, 355 `ability?`, 248 `outline?`, 219 `ally shape?`, 85 `ally`, 73
`enemy`. The unresolved classes are 76% of it and they are explicitly
unresolved rather than wrong. **The 85 allies are the wrong number**, and the
roster is not what is holding them back -- 68 of the 85 births happen while a
roster slot is free. The obvious cross-reference has been measured and does not
work: over the 103 samples carrying a roster conflict the flagged ally's
`lit_share` ran a median 0.707 against 0.761 for the accepted ones.
