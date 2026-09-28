# Tray kit witness

`reticle tray-kit` reads the C, Q, E and X icons of each cached tray crop and
says whose kit the tray shows (`reticle.tray_icons`, `adjudication.tray_kit`,
`tray-kit-0.1.0`). After the player dies the tray shows a spectated
teammate's kit [domain:hud/tray-after-player-death]; each slot draws its
ability's catalogue icon, dimmed while the ability is unavailable
[domain:hud/tray-slot-icons]. A change from the player's kit to another is a
second witness of the player's death, independent of the killfeed.

## How it reads

Each slot patch is scored against the catalogue icon's alpha channel by
normalised cross-correlation, which ignores gain and offset, so a lit and a
dimmed icon read alike. The candidates are staged by context: the player's
agent first (fit at least `PLAYER_FIT_MIN`, 0.6), then the ally side's agents
as the arbiter names them, with an unresolved slot's guess as a rival (fit at
least `KIT_FIT_MIN`, 0.5, and margin at least `MARGIN_MIN`, 0.1), then all
agents. A reading is refused, with its reason, when no lineup exists, the tray
is not drawn, the icons are too dim, a rival wins, the margin is short or the
fit is low. Runs of one kit form spans; `adjudication.identity` names each
span's agent. A `kit_change` is the first span of another kit, at least two
claims long, after the player's own; a `kit_return` is the player's kit after
a change. The witness's death lasts from a round's first change to the first
return after it.

Icon scale. 48 px fits best on all three sessions scanned
([metric:tray_kit/scale@three-sessions#s_c40d950031bb_best_px=48],
[metric:tray_kit/scale@three-sessions#s_a06f04a0059f_best_px=48],
[metric:tray_kit/scale@three-sessions#s_4f207c0c4e39_best_px=48]), one of
them on the big-minimap profile
([metric:tray_kit/scale@three-sessions#s_a06f04a0059f_profile=valorant-16x9-bigmap]).
The median fit at 48 px is
[metric:tray_kit/scale@three-sessions#s_c40d950031bb_median_fit_48=0.876],
[metric:tray_kit/scale@three-sessions#s_a06f04a0059f_median_fit_48=0.908] and
[metric:tray_kit/scale@three-sessions#s_4f207c0c4e39_median_fit_48=0.949].

Thresholds, over the stored rows of four sessions. When another kit is named,
the player's own icons fit at most
[metric:tray_kit/thresholds@four-sessions#player_fit_on_other_kit_max=0.455]
(p99 [metric:tray_kit/thresholds@four-sessions#player_fit_on_other_kit_p99=0.402]),
below the 0.6 the player stage needs. The allies stage named the player's own
kit [metric:tray_kit/thresholds@four-sessions#own_kit_named_at_allies_stage=40]
times, with fits from
[metric:tray_kit/thresholds@four-sessions#own_kit_at_allies_fit_min=0.501].
Its smallest margin was
[metric:tray_kit/thresholds@four-sessions#allies_stage_margin_min=0.147]; the
median fit of a named kit is
[metric:tray_kit/thresholds@four-sessions#named_fit_median=0.931]; no reading
widened to all agents
([metric:tray_kit/thresholds@four-sessions#widened_to_all=0]).

## Iso, the game-only match 4f207c0c4e39

No killfeed death is stored for this match
([metric:tray_kit/witness@4f207c0c4e39#killfeed_deaths=0]), so the witness is
the only death evidence the tray gate has. At the player's instants it reads
Omen at 448 s ([metric:tray_kit/witness@4f207c0c4e39#at_448_0_s=Omen]),
Phoenix at 455 s ([metric:tray_kit/witness@4f207c0c4e39#at_455_0_s=Phoenix]),
refuses 463 s
([metric:tray_kit/witness@4f207c0c4e39#at_463_0_s=refused_tray_not_drawn]),
Sage at 550, 595 and 603 s
([metric:tray_kit/witness@4f207c0c4e39#at_550_0_s=Sage],
[metric:tray_kit/witness@4f207c0c4e39#at_595_0_s=Sage],
[metric:tray_kit/witness@4f207c0c4e39#at_603_0_s=Sage]) and Omen at 1960
and 2170 s ([metric:tray_kit/witness@4f207c0c4e39#at_1960_0_s=Omen],
[metric:tray_kit/witness@4f207c0c4e39#at_2170_0_s=Omen]). The player's label
at 448 s says Phoenix; the tray shows Omen until 449.07 s and Phoenix from
449.57 s, so the label or the tray lags the other by about 1.5 s. Ask the
player which. It names
[metric:tray_kit/witness@4f207c0c4e39#named=2354] of
[metric:tray_kit/witness@4f207c0c4e39#samples=3295] samples, with
[metric:tray_kit/witness@4f207c0c4e39#kit_changes=19] changes and
[metric:tray_kit/witness@4f207c0c4e39#kit_returns=14] returns.

The ability state read the spectated kit's bars as Iso's. Before the witness,
[metric:ability_state/step1@4f207c0c4e39-before-kit-witness#invariant_1_level_outside_the_segments=433]
samples showed a half level on a one-charge slot, the gate kept
[metric:ability_state/step1@4f207c0c4e39-before-kit-witness#transition_cast=52]
casts and the state raised
[metric:ability_state/step1@4f207c0c4e39-before-kit-witness#invariant_surprises=89]
surprises. With it the half levels fall to
[metric:ability_state/step1@4f207c0c4e39#invariant_1_level_outside_the_segments=0],
the casts to [metric:ability_state/step1@4f207c0c4e39#transition_cast=24]
(every one dropped falls after a kit change), and the surprises to
[metric:ability_state/step1@4f207c0c4e39#invariant_surprises=8]. The state
marks
[metric:ability_state/step1@4f207c0c4e39#unreadable_kit_spectating=5640]
slot-samples `kit:spectating:<agent>` and
[metric:ability_state/step1@4f207c0c4e39#unreadable_owner_dead_kit_witness=1152]
`owner_dead:kit_witness`, and the gate still reproduces every stored verdict
([metric:ability_state/step1@4f207c0c4e39#gate_stored_mismatch=0]).

## Against the killfeed

On a06f04a0059f (Phoenix, big-minimap profile)
[metric:tray_kit/witness@a06f04a0059f#kill_ends_with_other_kit=18] of
[metric:tray_kit/witness@a06f04a0059f#kill_ends=19] killfeed kit ends are
followed by another kit, after a median
[metric:tray_kit/witness@a06f04a0059f#delay_s_median=2.55] s (max
[metric:tray_kit/witness@a06f04a0059f#delay_s_max=4.02] s); the one missed
falls a second before its round ends. The kit changed
[metric:tray_kit/witness@a06f04a0059f#changes_while_alive=0] times while the
killfeed says the player lived, over
[metric:tray_kit/witness@a06f04a0059f#live_min=12.73] live minutes.

On c40d950031bb the tray at 595 s shows
[metric:tray_kit/witness@c40d950031bb#at_595_0_s=Phoenix]; the killfeed
death at 592.5 s precedes it.
[metric:tray_kit/witness@c40d950031bb#kill_ends_with_other_kit=5] of
[metric:tray_kit/witness@c40d950031bb#kill_ends=7] kit ends are followed by
another kit (median delay
[metric:tray_kit/witness@c40d950031bb#delay_s_median=2.5] s); the two missed
fall 11 and 7.5 s before their rounds end, while the tray stays undrawn.
Changes while alive:
[metric:tray_kit/witness@c40d950031bb#changes_while_alive=0] over
[metric:tray_kit/witness@c40d950031bb#live_min=5.7] minutes.

On c62c2b06bcfb (Skye)
[metric:tray_kit/witness@c62c2b06bcfb#kill_ends_with_other_kit=12] of
[metric:tray_kit/witness@c62c2b06bcfb#kill_ends=14] kit ends are followed by
another kit (median
[metric:tray_kit/witness@c62c2b06bcfb#delay_s_median=3.02] s, max
[metric:tray_kit/witness@c62c2b06bcfb#delay_s_max=15.07] s, one Raze sample in
a long undrawn stretch); the two missed fall 6.5 and 9.5 s before their rounds
end. The kit changed
[metric:tray_kit/witness@c62c2b06bcfb#changes_while_alive=1] time while the
killfeed says the player lived: to
[metric:tray_kit/crosscheck@c62c2b06bcfb#kit_change_agent=Phoenix] at
[metric:tray_kit/crosscheck@c62c2b06bcfb#kit_change_s=1147.05] s, for
[metric:tray_kit/crosscheck@c62c2b06bcfb#kit_change_span_claims=19] claims.
The combat report counts
[metric:tray_kit/crosscheck@c62c2b06bcfb#report_deaths=1] death in that
round, the killfeed stored
[metric:tray_kit/crosscheck@c62c2b06bcfb#killfeed_player_deaths=0], and
[metric:tray_kit/crosscheck@c62c2b06bcfb#death_abstained_in_gap=1] death
verdict abstained between the last own-kit sample and the change. The
killfeed missed a death the tray saw.

A kill end the tray does not follow falls a few seconds before the round ends,
when the tray is blank until the next round; the witness is silent there, not
wrong. A return to the player's kit falls after the round ends, except in
rounds whose end the rounds table sets at the close.

## Consumers

`ability_timeline.player_tray_casts` refuses a drop after the round's first
kit change and before the next return (`after_kit_change`), after the
killfeed's `after_player_death`. `adjudication.ability_state` marks a sample
whose tray shows another agent `kit:spectating:<agent>`, and a sample between
a change and the next return that shows no other kit
`owner_dead:kit_witness`; it adds a `tray_kit` claim beside each
killfeed kit end, and where no killfeed end exists it places the owner's
death at the change. `adjudication.death` does not use the witness; a planned
`agent-alive` owner belongs there.

## Not done

The witness ran on four sessions only. The other sessions keep their
`player-cast-0.5.0` tray rows, which carry no `tray_kit` stamp;
`reticle plan` does not yet name `tray_kit` as a stream.
