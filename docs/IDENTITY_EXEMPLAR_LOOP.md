# Session exemplars for killfeed portraits — 2026-09-23

**Outcome: mostly confirmed; one clause failed.** Across all 24 rounds of
`a06f04a0059f`, scoring killfeed portraits against this session's own labelled
portraits names 32 more victims and killers, and a source check of 12 of them
finds all 12 correct. Neither refused round-4 killer is recovered.

## The loop

It follows the ability harvest's pattern (a second channel supplies the label)
with three rules that keep it from grading itself:

1. **Labels come only from witnesses that are not the portrait.**
   `death.portrait_exemplars` takes a death's portraits only when the arbiter
   resolved it with an independent claim from `EXEMPLAR_LABEL_CHANNELS`: a
   single scoreboard binding, or the player HUD. Names from elimination
   (`depends_on`) or from exemplars never label, so the loop converges after
   one harvest.
2. **An entry never matches its own portraits** (leave-one-entry-out).
3. **Exemplars are consulted only where the official art refuses**, and a name
   they decide carries `depends_on` on the death that labelled it. The arbiter
   does not count it as independent. The first version consulted them
   everywhere; 85 victims then rested on exemplars alone where 8 did before,
   because an exemplar out-scored art that had already named the portrait.

`tools/identity_loop.py` runs it: pass 0 is the existing adjudication over
every round (portraits, scoreboard dimming gated on the roster, player HUD);
pass 1 repeats it with the harvested exemplars.

## Results

The extraction emits 8 exact duplicate killfeed entries across 7 rounds; the
tool drops and counts them, leaving 162 deaths. Pass 0 harvested 202 labelled
portraits: 98 from the player HUD (Phoenix) and 104 from scoreboard bindings
across all ten agents.

| | Pass 0 | Pass 1 |
| --- | --- | --- |
| Victims named | 125 | 139 |
| Killers named | 94 | 112 |
| Disagreements | 0 | 0 |
| Victims named only by dependent claims | 8 | 22 |

Pass 1 added 32 names, changed none and removed none. A source check of 11
entries covering 12 added names, five of them Jett (the most frequent), finds
all 12 correct. Round 4 keeps all seven victims and the five named killers.

## Open

- **Breach at 284500 gets worse with exemplars**: two of four killer views
  lean Deadlock, and the margin gate keeps the name out. The source shows
  assist icons left of the killer portrait, so the crop is the likely cause,
  a `killfeed` reader defect.
- **Killjoy at 295000 has one view** before the next entry closes the window;
  no reference set fixes that.
- The 150 deaths outside round 4 have no source truth beyond the spot check.
