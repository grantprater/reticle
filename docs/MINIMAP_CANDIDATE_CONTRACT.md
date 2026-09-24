# Minimap candidate preservation

The minimap reader stores fitted hypotheses and their measurements under a
content-addressed revision. A separate decision artifact names each candidate,
its disposition, reason, rule version, and any preferred candidate. Production
`ally_icon` rows and the legacy wide position table are views of those decisions.

The boundary is a fitted hypothesis. Colour components too small to fit, or
outside the baked opaque slab, remain bounded candidate-generation limits.
Source review still measures recall. A fitted hypothesis survives shape,
facing, interior-map, duplicate, temporal-self and top-four decisions. An unread
facing is `null` with `facing_reason`; no reader silently turns it into absence.

Candidate revisions include source frame and time, detector version, and all
available ring measurements. Decisions must refer to an existing candidate in
the pinned revision. The store refuses missing, duplicate, or undecided keys.
The runner writes candidates, reloads that revision, derives and stores
decisions, then reloads decisions to build accepted views. Changed candidate
revisions invalidate derived views even when accepted positions coincide.

Each ally candidate carries two kinds of appearance evidence:

- **Baseline appearance** (`baseline_descriptor`, `baseline_map_diff`,
  `baseline_reason`) is measured for every fitted candidate, accepted or not,
  with no occluder mask. It depends on no other candidate's decision, so any
  rule can replay against it.
- **Accepted-view descriptor** (`descriptor`, `map_diff`, `descriptor_pixels`,
  `descriptor_reason`) is the composition the previous accepted output used.
  Only fits that view selected have one; the rest say `not_selected`.

Portrait compositions depend on a selected self occluder and selected ally
neighbors. Their records name those dependencies. A changed selection can
replay the shape decision from stored measurements, but computing a new portrait
composition for a different mask needs source pixels. No stored output claims
that counterfactual crop was observed.

Old `ally_icon` and `l1/minimap` records lack candidate lineage. Stored-data
tasks may use their accepted observations with their old stamps, but must mark
lineage unavailable and cannot recover rejected fits or alternative occluders.
This change does not initiate a corpus rescan.

The reader never imports the adjudicator. The runner asks
`adjudication.minimap_candidates` for decisions and the accepted rows, then
hands those rows to `AllyIconReader.events`. At scan time the reader compares
the replayed accepted view with its live gated output, frame by frame, position
and refusal reason, and refuses to publish if they differ.
