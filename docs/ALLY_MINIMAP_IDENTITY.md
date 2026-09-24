# Ally minimap identity (backlog step 6, first slice)

## What was built

- `minimap.ally_icon_descriptors` describes each teammate icon that passes the
  ally channel's gates by `appearance.hsv_composition` over its interior disc
  (0.75 r). It masks the ally and self keys, the player's own icon, and pixels
  nearer another detected icon. It also stores `map_diff`, the interior's mean
  grey difference from the baked map. An interior below `ALLY_MAP_DIFF_MIN` is
  the map itself, a teal spawn barrier, and is refused as `interior_is_map`.
- `minimap.AllyIconReader` joins `reticle scan` as the `ally_icon` channel at
  2 Hz over active spans and writes `ally_icon` events at `ally-icon-0.1.0`:
  a coverage row, one row per described frame, and one row per icon. Minimap
  positions and `minimap-0.7.0` are unchanged.
- `identity.claims_from_ally_icons` names each frame's icons together with
  `assign_side` over the board's ally set minus the player. The entity is the
  observation; nothing joins icons across frames yet.
- `tools/ally_identity_review.py` adjudicates from stored events and renders a
  seeded random sample of named icons from source.

## Results on `a06f04a0059f`

The reader described
[metric:ally_identity_review/official-art@a06f04a0059f#described=7833] of
[metric:ally_identity_review/official-art@a06f04a0059f#icons=9925] icons, and the
arbiter named
[metric:ally_identity_review/official-art@a06f04a0059f#named=4932] of them, a
share of [metric:ally_identity_review/official-art@a06f04a0059f#named_of_described=0.6296]
of the described. The remaining described icons refused on the assignment margin.

A source check of a seeded random 40 named icons found
[metric:ally_identity_review/source-check@a06f04a0059f#correct=38] correct and
[metric:ally_identity_review/source-check@a06f04a0059f#wrong=2] wrong. The
prediction allowed one wrong, so it failed.

## Open

Both wrong names are overlapping ally icons. In one, the ring fitted Reyna's
icon while Deadlock's, drawn below and overlapping, filled part of its
interior. In the other, the fit's centre falls between stacked Reyna and Breach
icons. The neighbour mask removes only pixels nearer another DETECTED icon, and
neither overlapped neighbour was detected separately. The candidate fixes are
refusing a fit whose keyed component is larger than one icon, or one whose disc
holds a second portrait. Measure either against a player-labelled sample, not
against the 40 above, which chose the failure.

Two parts of the agreed slice remain: session exemplars (an ally whose death is
named at t is the icon that vanishes at t, with `depends_on`), and a track key
so claims accumulate per teammate rather than per frame.
