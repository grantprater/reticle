# Minimap mining: the original proposal and its first run (2026-09-10)

Moved on 2026-09-27 from the section *Infer the inventory; do not be told it*
in [MINIMAP_APPEARANCE_MATCHING.md](../MINIMAP_APPEARANCE_MATCHING.md).
[MINIMAP_MINING_REVIEW.md](../MINIMAP_MINING_REVIEW.md) supersedes its
interpretation and next steps; the measurements below stand as recorded.

**Historical proposal and first-run interpretation:** read the
[subsequent critique](../MINIMAP_MINING_REVIEW.md) for the current design. In
particular, "clusters are classes", "junk never forms a cluster", semantic
assignment from event coincidence, and origin inference from position spread
are unsupported assumptions, not acceptance criteria. The replacement sequence
starts with an independent proposal-recall audit and preserves rare candidates.

**The prose descriptions above are a stopgap and must not become the method.**
Everything in them except the game rules is a property of pixels the capture
already holds, and this plan's own gallery contract already says to mine
exemplars from independently anchored windows. Asking for a paragraph per icon
does not scale past the fourteen rows above, it puts a person in the loop for
something a decode can answer, and it introduces an error class nothing can
catch: a description is unfalsifiable against the frame until someone re-reads
both.

**The precedent already worked, on the hardest case.**
`prototypes/minimap_portrait.py` mined 71 enemy icons on `a06f04a0059f` and
clustered them on their interiors alone. It produced 19 groups, every one
visually pure, merging into exactly the five agents the enemy roster shows plus
a sixth group for the question-mark icons -- with nothing tuned to make that
happen. Its own note records the residue precisely: the agent NAMES were first
written down wrong, the player corrected them, and **no measurement changed,
because the classes were right.** Structure is inferable. A name is not, and a
name is one word.

**The proposer already exists and was thrown away.**
`minimap_occlusion.foreign_fraction` asks, per pixel, whether the grey leaves
the map's measured `[lo_gray, hi_gray]` lighting band -- *something is drawn
here* -- naming no colour and no class. It then reduces that to a scalar and
discards the mask. **The mask is the object proposer**, and the whole shape of
the gap is in that one line: every prototype so far was built to answer one
detector's question, so none of them ever enumerated objects.

**Measured 2026-09-10 on four frames of `c40d950031bb`, inside the slab**, with
`prototypes/object_proposals.py`:

    frame                     foreign px   % of slab   components in the icon band
    dropped spike + player       1560        5.50%              37
    planted spike on B           1001        3.53%              11
    carried badge + ally clump   1040        3.66%              13
    spike, crowded               1156        4.07%              17

at a 10.0 grey margin, with the icon band 5-203 px at scale 0.712. Rendered,
the proposals cover the icon clumps and also pick up objects **no colour key
would find at all**. The tail is larger than the five or six real icons on a
frame, and much of it is map furniture -- which `doctor` already reports as a
standing finding, and which is removable precisely because it is STATIC.

**Why that tail is acceptable here, and would not be in a reader.** A detector
needs per-frame precision. A miner needs RECURRENCE: artwork repeats across
thousands of frames with a consistent appearance, and speckle does not, so the
junk never forms a cluster. This is the one place in the pipeline where a loose
proposer is the correct instrument, and it is why mining must not be built out
of the readers.

The protocol, which G1 uses and every later G-step inherits:

1. **Propose objects from the foreign mask, inside the opaque slab only.**
   Outside the slab the widget is see-through and the live world bleeds in,
   which is the documented cause of reading scenery as icons; inside it, the
   stored static map is a valid background. No colour key at any point.
2. **Subtract what is always there.** Accumulate a per-pixel foreign RATE over
   the session: a pixel foreign in most frames is furniture or a geometry
   error, not an entity. This calibrates itself off the corpus rather than off
   a hand-chosen threshold, and it is what removes the bulk of the tail above.
3. **Describe and cluster.** `minimap_appearance.describe` already produces an
   11x11 masked-luma descriptor with a contrast check, and
   `appearance_similarity` already scores two of them; `minimap_portrait.py`
   already clusters with them. The clusters are the classes. States separate
   here too, because a glyph that is smaller and rotated does not land in its
   neighbour's cluster.
4. **Relate the clusters automatically.** Test each pair for the
   transformations the widget actually uses -- a 180-degree rotation, a scale
   change, a colour swap. *It inverts* [domain:minimap/spike-inversion] is
   then a DISCOVERED relation
   between two clusters rather than a sentence someone supplies.
5. **Anchor clusters to independently timed events for their meaning.** The
   cluster that appears at a HUD-detected plant is the planted spike; the one
   that appears where a killfeed victim last stood is the dropped spike; the one
   that rides a player icon is carried. This is the forced-correspondence rule
   this plan already states, and it names classes without a person.
6. **Ask the player only what survives.** A one-word name for a cluster, or a
   yes/no on a rule the pipeline has hypothesised. Never a description.

**BUILT AND FIRST-RUN 2026-09-10: `prototypes/mine_icons.py`.** It runs end to
end and the proposer holds -- 2391 proposals over 101 frames of
`c40d950031bb` at 1 Hz, 23.7 per frame, every one describable. **Three of the
four steps above do not work as this document claims, and the claims are
corrected here rather than left standing:**

1. **The static subtraction is INERT.** At a 0.5 foreign rate it removed 14 px,
   0.0% of the slab, against the text above promising it removes the bulk of
   the tail. Furniture is not foreign in half of frames, so either the rate is
   the wrong statistic or the level is far off. Unsupported until re-measured.
2. **Clustering on appearance alone FRAGMENTS.** 254 clusters at join 0.60, 67
   recurring, and the large ones carry a POSITION SPREAD of 60-84 px. A class
   whose members are scattered over a third of the widget is a bag of visually
   similar noise, not an object.
3. **The rotation relation has no NULL and is therefore meaningless as run.**
   It fired on 93 pairs, several at rotated 0.75-0.82 against upright -0.97. An
   11x11 masked luma patch correlates with its own rotation by chance far too
   often for that to be a discovery. Measure rotated similarity between
   clusters known to be unrelated BEFORE any pair is called a relation.

**What the run did find, and it was printed by accident rather than designed:
POSITION SPREAD separates the clusters.** Cluster 11 is n=37 at 6.8 px spread
and contrast 150; cluster 14 is n=30 at 32 px and contrast 126; the noise
clusters sit at 60-84 px and contrast 45-70. That is the entity model's own
`origin` parameter falling out of the data: a fixed object recurs in ONE PLACE,
a player recurs everywhere, and speckle recurs nowhere in particular at low
contrast. **Cluster on appearance AND on that behaviour**, and gate proposals on
contrast before describing them.

Cost is bounded by sampling rather than by the pass: mining wants enough
exemplars per class, not every frame, so it takes the event-anchored windows
plus a spread of ordinary ones and rides the shared decode. Scoring it needs
the exhaustively painted frames, which are the only labels in the store that
make precision computable at all; 39 exist across two sessions today.

Three failure modes to design against, all of them already recorded elsewhere
in this repo: coincident objects, since two icons may sit 0.7 px apart and no
rule may assume they separate; class imbalance, since a spike appears in every
round and a rarely-used ability may have one instance in the corpus; and
mining's own circularity, since a cluster built from detector-selected frames
inherits that detector's blind spot -- which is why the proposer takes no
colour key.
