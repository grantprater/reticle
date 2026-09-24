# Killers through the identity arbiter — 2026-09-23

**Outcome: passed.** Round 4 of `a06f04a0059f` names 5 of 7 killers, all
matching source, with zero wrong names. Before this change every verdict had
`killer: null` on the stored-portrait path, and the killer that other paths
set was decided outside `adjudication.identity`.

## Mechanism

- `attach_stored_killfeed_portraits` builds a `killer_claim` from the entry's
  stored killer portraits, as it builds the victim claim: the killer's plate
  is the side opposite the victim's, the candidates are that side's
  board-constrained lineup, and the channel names an agent only when at
  least two views agree.
- `adjudicate_death` names the killer as a second entity,
  `<death_id>:killer`, through `adjudicate_agent_identity`. Its witnesses are
  the player HUD on a player kill and the killer portraits. The verdict stores
  it under `metadata["killer_identity"]`, and `death_verdict_to_events` emits
  its identity event.

## Results

Truth was read from source killfeed crops before measuring.

| Death | Victim | Truth | Named | Witness |
| --- | --- | --- | --- | --- |
| 281500 | Deadlock | Killjoy | Killjoy | portraits |
| 283500 | Reyna | Omen | Omen | portraits |
| 284500 | Jett | Breach | refused | one of four views clears the 0.07 margin |
| 295000 | Miks | Killjoy | refused | one view (correct) before the next entry |
| 295500 | Skye | Phoenix | Phoenix | player HUD; portraits 3 of 4 views |
| 301000 | Phoenix | Omen | Omen | portraits; "KILLED BY OMEN" banner in source |
| 332500 | Iso | Breach | Breach | portraits |

## Open

- An entry's portrait window ends at the next entry, so near-simultaneous
  kills get one view each. This limits victims and killers alike.
- The player's own kills label killer portraits for free. Harvesting those
  crops per session could widen the gallery, provided each crop records the
  player-HUD witness that labelled it.
