# Round entities over a whole session

## What runs

`reticle lifetimes SESSION` runs `round_lifetimes.RoundLifetimes` over every
round of a session from stored data only: the `ally_icon` events (ally fits,
their descriptors and the player's own fit), the HUD's round bounds and the
roster count. It writes `round_entity` events keyed by `round-entity-0.1.0`
and the association law's own stamp. An ally fit whose interior is the map
enters as a static `barrier`; a widget-absent frame suspends association.
`a06f04a0059f` was rescanned for this at 15 Hz (`scan --only ally_icon
--ally-hz 15`); the 2 Hz events stay beside their identity review.

## Fragmentation, and the first fix

Without any change to the association law, the session held
[metric:round_entities/baseline@a06f04a0059f#ally_entities=823] ally entities,
a median of [metric:round_entities/baseline@a06f04a0059f#median_per_round=35.0]
per round against at most four living teammates.
[metric:round_entities/baseline@a06f04a0059f#adjacent_births=460] of
[metric:round_entities/baseline@a06f04a0059f#mid_round_births=707] mid-round
births sat within 24 px of an ally seen the frame before.

Source frames show those births are not stacked icons separating. One icon's
ring fit jumps 10-20 px between frames, onto the teardrop lobe or the ring's
edge. `track.Tracker` already treated such a detection as a refit of the
unobserved track; `RoundLifetimes` lacked the rule. `track.refit_of` now owns
it and both call it. `RoundLifetimes` applies it only to entities seen on the
previous step, because an entity hidden longer is a reacquisition, not a
jumping fit. Ally entities fall to
[metric:round_entities/refit@a06f04a0059f#ally_entities=576].

Portraits either side of a refit disagree more often than crowded
continuations do
([metric:round_entities/refit@a06f04a0059f#refit_pairs_disagree_share=0.415]
against [metric:round_entities/refit@a06f04a0059f#crowded_control_disagree_share=0.078]).
All [metric:round_entities/refit@a06f04a0059f#refits_viewed=5] disagreeing
refits viewed in source were the same icon, with one side fitted on the lobe:
the fit describes floor, not the portrait. The check is confounded by the
lobe-centred fit, and that fit is the upstream defect.

## Open, in order

1. **Lobe-centred fits.** The ring fit centres on the teardrop often enough to
   dominate births, and it moves the stored position and spoils the
   descriptor. Fix it in the detector, not the association law.
2. **Missed icons.** Clearly drawn allies go undetected for seconds and are
   reborn; the facing gate is the likely cause, since `map_diff` now rejects
   barriers without it. Measure before removing it.
3. **Occlusion and stacks.** An ally under the self icon or inside a stack is
   refused, not ended: it needs a merged state that keeps it eligible.
4. **Start and end events.** Every lifetime ends right-censored. Ends come
   from killfeed deaths through the arbiter, domain lifetimes, and inferred
   causes; each carries its cause class and evidence.
5. **Names per track segment**, through `adjudication.identity`.
