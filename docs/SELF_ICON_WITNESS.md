# The self icon as the player's second witness

`reticle self-icon <sid> | --all` (`reticle/self_icon.py`, `self-icon-0.2.0`)
reads the player's minimap icon from the stored minimap crops, decodes no
video, and writes `self_icon` rows. `lineup.load_lineup` reads their witness
as the lineup's `self_icon` witness; no lineup file is rewritten.
`identity._self_icon_claim` ranks the ally five and the arbiter decides
(`player-agent-0.2.0`).

## Why it was empty

`Lineup.add_self` existed and nothing called it, so every stored lineup held no
self-icon frame and the tray was the only witness to the player's agent. The
tray's votes also pool spectated kits
[domain:hud/tray-after-player-death].

## The gate

A frame is read only where the stored roster reads five allies alive at both
roster samples around it: five living allies include the player, so the view
is the player's. The gate rests on neither the tray nor the killfeed, so the
two claims stay independent. Every grid frame is stored, scored or refused
with its reason (`not_all_alive`, `widget_not_drawn`, `no_self_fit`,
`ally_overlap`, `interior_too_thin`).

## Two descriptors

The first run (`self-icon-0.1.0`) scored the icon's interior by composition
against the official art, as `Lineup.add_self` does. Over the 21 lineup
sessions it agreed with the tray on
[metric:self_icon/agreement-composition@lineup-21#agree=15], disagreed on
[metric:self_icon/agreement-composition@lineup-21#disagree=2] and abstained on
[metric:self_icon/agreement-composition@lineup-21#abstain=4]. Both
disagreements, `bfad2778a372` and `e37fdeca944f`, named Chamber where the tray
named Skye. The crops show Skye: auburn hair under a green band, no glasses.
The composition ranked Chamber first of 29 on all
[metric:self_icon/agreement-composition@lineup-21#skye_chamber_first=6] Skye
sessions, and named him wherever Chamber sat on the ally side. The self icon
was wrong, not the tray.

`self-icon-0.2.0` also stores each frame's minimap portrait features
(`ally_portrait.portrait_features`) and their rendered-art log likelihoods
(`identity.rendered_art_scores`), the scorer the teammate channel prefers.
The witness reads the mean of those, gated at the reference table's
`margin_min`, wherever every scored frame has them; the composition's mean
stays beside it. The two are never mixed.

## Result

Over the 21 lineup sessions the `self_icon` claim agrees with the tray on
[metric:self_icon/agreement@lineup-21#agree=12], disagrees on
[metric:self_icon/agreement@lineup-21#disagree=0] and abstains on
[metric:self_icon/agreement@lineup-21#abstain=9]:
[metric:self_icon/agreement@lineup-21#abstain_margin=8] below the margin and
[metric:self_icon/agreement@lineup-21#abstain_unread=1] unread. The player
verdict moves on [metric:self_icon/agreement@lineup-21#player_changed=0]
sessions: the tray named all 21 before, and each name now has a second witness
or an abstention beside it.

Seven of the eight margin abstentions are Sova sessions, where another
agent's art scores near Sova's. A crop sheet of `9acf02f98283` shows Sova's portrait in the
ring, and shows fits that are not the ring: Sova's yellow ability arcs and the
carried spike draw in the self key, and `self_icons` fits them. Those frames
dilute the mean.

**The Iso capture abstains.** On `4f207c0c4e39` the minimap is drawn larger
than the baked Split geometry, so `widget_drawn` refuses all
[metric:self_icon/iso@4f207c0c4e39#widget_not_drawn=461] frames the gate
passes, and the stored minimap rows hold no self position either. The icon is
visible in the crops; reading it needs geometry for that widget size.

## Open

- Gate the fit on the stored self track, or on the self key's ring shape, so
  ability arcs and the spike stop reaching the score.
- A mean over frames is gated at a per-icon margin; a rule fitted for a
  session's pooled evidence would name more of the Sova sessions.
- The Iso capture needs geometry for its widget size before any minimap
  reader can see it.
