r"""Enemy icons, death X marks and red "?" marks, read from stored minimap crops.

    .\.venv\Scripts\python.exe -m reticle minimap-objects <session>

Owns [owns:enemy-icon] and [owns:last-known-mark]. The X marks come from the
death owner's detector (`adjudication.death.minimap_x_marks`); this module
reads them in the same pass and stores them beside the enemies.

Each cached minimap frame becomes one `minimap_object` row: the enemy icons
it holds, each with its position and, where the icon-pose owner reads it, its
facing; the X marks of both colours; the red "?" marks; and every refused
candidate with its reason. A frame the widget does not draw is a row with a
reason, not a missing row, so coverage stays unbiased. Decodes no video.

**The enemy.** The red key's ring fit proposes each icon (`minimap.icons`
with the enemy ring's gates, the detector stage 2 scored), and the icon-pose
owner's enemy class fits the teardrop from it (`teardrop.fit_icon`), whose
lobe is translucent [domain:minimap/enemy-lobe-translucent]. A read fit gives
the centre and facing (image degrees, y down). Facing never reaches the
entity lane yet: the contract names no orientation convention.

**The proposal.** To 0.5.0 the ring search fitted one circle per red blob,
seeded at its centroid, and gated it afterwards. An icon whose key touches
another red shape (its own lobe, a red X, a utility glyph, another icon)
shares a blob with it, and that one circle slides onto the neighbour or
straddles the lobe: it lands off the icon, or its interior holds the lobe
and the inner gate drops it, while the icon's own ring passes the gates at
its centre (`prototypes/enemy_proposal_funnel.py`). The search that gates
first and proposes every peak (`minimap.icons(seed="peaks")`) finds those
icons, and also rings the lobeless red-rimmed utility discs the off-centre
circle had refused by luck. 0.6.0 required a lobe (`RING_LOBE`) and proposed
the peaks only beside the last frame's icons (`RING_SEED` "centroid+prior",
an unaudited prior); both stay switchable and are off from 0.7.0.

From 0.7.0 the search proposes every gated peak (`RING_SEED` "peaks") and
scores each ring's coverage softly (`RING_COVER` "soft": the mean of
`teardrop.redness` over the circle, cut once at `COV_MIN`), and the
`portrait_gate` decides which finds are enemy icons. Cross-reference, not a
tuned shape: a red-rimmed utility disc, a red triangle and a faint X ring
as well as an icon, but only an icon holds an agent's portrait. The gate
asks the identity owner how well the find's `portrait_features` fit the
CLOSEST of the match's enemy five, from the stored lineup
(`lineup.portrait_candidates`, the side's named slots and refused slots'
guesses), under the rendered-art references baked from the game's minimap
portrait textures (`identity.rendered_art_fit`, `ally_portrait.render`
shrinks the art with `INTER_AREA`). A find whose fit exceeds `FIT_MAX`
is refused `not_a_portrait`; every kept find stores `portrait_fit` and the
second-closest agent's lead over it, `portrait_margin`. The gate stores no
name: naming stays `agent-identity`'s. With no lineup, a short enemy side,
or no references, the gate cannot refuse anything, so the search falls back
to the centroid seed and the head records why (`portrait_gate`).

Against T1d on 9acf02f98283 (pings reread) the 0.6.0 prior seed scored
[metric:teardrop_refusals/lane/ep1@9acf02f98283#hits=2905] hits and
[metric:teardrop_refusals/lane/ep1@9acf02f98283#false_accepts=118] true false
accepts against 0.5.0's
[metric:teardrop_refusals/lane/b1@9acf02f98283#hits=2836] and
[metric:teardrop_refusals/lane/b1@9acf02f98283#false_accepts=145]; the peaks
everywhere with the lobe and no gate,
[metric:teardrop_refusals/lane/pk2@9acf02f98283#hits=2960] and
[metric:teardrop_refusals/lane/pk2@9acf02f98283#false_accepts=175]. 0.7.0
scores [metric:teardrop_refusals/lane/pg1@9acf02f98283#hits=3237] and
[metric:teardrop_refusals/lane/pg1@9acf02f98283#false_accepts=47] there; at
465 px, [metric:teardrop_refusals/lane/pg1@c817691bcd15#hits=3825] and
[metric:teardrop_refusals/lane/pg1@c817691bcd15#false_accepts=187] on
c817691bcd15 (0.5.0:
[metric:teardrop_refusals/lane/b1@c817691bcd15#hits=3629],
[metric:teardrop_refusals/lane/b1@c817691bcd15#false_accepts=210]) and
[metric:teardrop_refusals/lane/pg1@d3dcfb182ab1#hits=2580] and
[metric:teardrop_refusals/lane/pg1@d3dcfb182ab1#false_accepts=61] on
d3dcfb182ab1 (0.5.0:
[metric:teardrop_refusals/lane/b1@d3dcfb182ab1#hits=2453],
[metric:teardrop_refusals/lane/b1@d3dcfb182ab1#false_accepts=93]). Pooled,
a paired round bootstrap puts the change at
[metric:enemy_portrait_gate/paired/pg1-vs-b1@dev3#d_hits=724] hits
([metric:enemy_portrait_gate/paired/pg1-vs-b1@dev3#d_hits_lo=566] to
[metric:enemy_portrait_gate/paired/pg1-vs-b1@dev3#d_hits_hi=897]) and
[metric:enemy_portrait_gate/paired/pg1-vs-b1@dev3#d_fa=-153] true false
accepts ([metric:enemy_portrait_gate/paired/pg1-vs-b1@dev3#d_fa_lo=-287] to
[metric:enemy_portrait_gate/paired/pg1-vs-b1@dev3#d_fa_hi=-39]).

Each part's share (`prototypes/enemy_portrait_gate.py paired`): the peaks
with the gate on the binary key score
[metric:teardrop_refusals/lane/pgb@9acf02f98283#hits=2943] hits and
[metric:teardrop_refusals/lane/pgb@9acf02f98283#false_accepts=30] true false
accepts on 9acf02f98283, where the peaks without the gate scored
[metric:teardrop_refusals/lane/pk1@9acf02f98283#false_accepts=227]: the gate
removes the discs. Soft coverage then adds
[metric:enemy_portrait_gate/paired/pg1-vs-pgb@9acf02f98283#d_hits=294] hits
for [metric:enemy_portrait_gate/paired/pg1-vs-pgb@9acf02f98283#d_fa=17]
false accepts at 331 px, but at 465 px only
[metric:enemy_portrait_gate/paired/pg1-vs-pgb@c817691bcd15#d_hits=22] and
[metric:enemy_portrait_gate/paired/pg1-vs-pgb@d3dcfb182ab1#d_hits=20] hits
for [metric:enemy_portrait_gate/paired/pg1-vs-pgb@c817691bcd15#d_fa=81] and
[metric:enemy_portrait_gate/paired/pg1-vs-pgb@d3dcfb182ab1#d_fa=30] false
accepts, both intervals above zero. There the rim already keys, and the soft
score proposes red shapes the gate passes: Cypher's camera glyph, a black
disc with a white device, fits Cypher's black-and-white portrait when Cypher
is in the five, and an icon half under a teammate's fits a portrait too. The
gate's other cost is Omen's violet portrait, whose rendered-art fit is poor:
on c817691bcd15 a `not_a_portrait` refusal lies beside 120 misses.
The read costs more: the teardrop fits every gated peak, not one circle
per blob, and a reread of c817691bcd15 took about 3.7 times 0.5.0's on
either key.

**The "?".** A red blob the X shape test rejects and no enemy icon covers,
whose red run, walked back frame by frame, begins where an enemy icon ended:
the icon's last frame lies at most `Q_SWAP_MS` before the run's first frame,
and that first frame at most `Q_GONE_MS` before now
[domain:minimap/last-known-mark] [domain:minimap/last-known-mark-timing].
The walk reads this stream's own earlier frames, so the "?" is pure over
what the pass stored.

**The icon scale.** Icons follow the map zoom
[domain:minimap/icons-follow-map-zoom], so every icon length here is a base
value times `icon_scale`, the one transform (`geometry.MapScale`: widget
scale x map zoom); the head records it and its source. The X owner is still
given the widget's scale, so the death stream's inputs do not move. Read at
the widget's scale alone (0.71 on the 331 px widget, against 0.64 with the
zoom), the enemy teardrop was 12% too large, and it refused visible enemy
icons as `no_ring` and `low_ncc`; the enemy class now also scores its ring
softly and refuses a lobeless ring as `no_lobe` (`teardrop.ICON_CLASSES`,
ENEMY_TEARDROP_VERSION). Against T1d on 9acf02f98283 the lane's hit rate rose
from [metric:teardrop_refusals/lane/stored@9acf02f98283#hit_rate=0.442] to
[metric:teardrop_refusals/lane/final@9acf02f98283#hit_rate=0.6313], and the
misses beside a `no_ring` refusal fell from
[metric:teardrop_refusals/lane/stored@9acf02f98283#no_ring=767] to
[metric:teardrop_refusals/lane/final@9acf02f98283#no_ring=27]
(`prototypes/teardrop_refusals.py`).

**Three fixes, each switchable and stamped.** `FIXES` names them and
`ENABLED` turns each on; the stamp is the base version plus the fixes on, so
turning one off changes the stamp and `reticle plan` names the stream stale.

- `teardrop_box`: an enemy is boxed at the teardrop's fitted centre with
  radius the fitted tip distance plus `TIP_PAD` * scale, which holds the tip
  at either facing; a fit refused only as `ambiguous_facing` is kept as
  position only, its facing null with that reason. Off, only a read
  teardrop is kept, boxed by the fixed ring `RING` * scale (stage 2's
  teardrop mode). On a held-out sample the box held the whole icon on
  [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK4_n=14]
  of [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK4_of=14].
  Either way a fit the teardrop refuses for another reason (`low_ncc`,
  `no_ring`) is no enemy: it is stored refused at the ring's centre with no
  extent, and where a shape-confirmed red X lies within `X_OWN_PX` * scale
  it is the X classifier's (`owned_by_x_classifier`), not a missed enemy.
- `slab_gate`: a red candidate (enemy, red X, or the red blob a "?" is read
  from) is kept only when at least `RED_SHARE` of the redness within
  `ICON_PX` * scale lies on the baked slab. Void just off the map makes
  false red candidates [domain:minimap/transparency]; the slab comes from
  baked geometry only [domain:capture/session-pixels-are-not-the-map]. A
  disc with no red abstains and keeps. On the held-out sample the gate
  dropped [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK1_n=0]
  of [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK1_of=16]
  marks the player called an enemy, X or "?".

- `owner_gate`: a teardrop read is the X classifier's where a
  shape-confirmed red X lies within `X_OWN_PX` * scale, and the ping
  reader's where a confirmed ping of the stored `ping` stream is drawn
  within `PING_OWN_PX` * scale at that time, on the ping's own glyph
  (`stored_pings`; no ping stream, the gate abstains and the head records
  `no_rows`). The refusal links the ping's `entity_id` and its distance.
  From ping-0.2.0 the ping owner confirms the danger pings whose flash
  [domain:minimap/danger-ping-flash] split their runs. With pings reread
  from the crop cache by that code (`teardrop_refusals.py pings`, tag
  `p020`), not the stored ping-0.1.0 stream, true false accepts on
  9acf02f98283 fell from
  [metric:teardrop_refusals/lane/final@9acf02f98283#false_accepts=194] to
  [metric:teardrop_refusals/lane/c1@9acf02f98283#false_accepts=129] with the
  hit rate at [metric:teardrop_refusals/lane/c1@9acf02f98283#hit_rate=0.6313];
  at `PING_OWN_PX` and with the annulus lobe test they stand at
  [metric:teardrop_refusals/lane/r1@9acf02f98283#false_accepts=138], the hit
  rate at [metric:teardrop_refusals/lane/r1@9acf02f98283#hit_rate=0.631].
  The cache reread confirms fewer pings than the stored video-read stream
  (44 against 57 on 9acf02f98283); the gate over a production ping-0.2.0
  stream, refreshed from video, is unmeasured.

The first two fixes were measured in `prototypes/enemy_lane_bounds.py`
(enemy-lane-bounds-0.1.0) before they were wired; the third and the icon
scale in `prototypes/teardrop_refusals.py`.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .version import ALLY_PORTRAIT_FEATURES_VERSION, ENEMY_TEARDROP_VERSION, TEARDROP_VERSION

#: 0.2.0 (2026-10-07): icons are read at base x widget scale x map zoom
#: (`icon_scale`), the enemy teardrop scores its ring softly
#: (ENEMY_TEARDROP_VERSION 0.2.0), and the `owner_gate` fix.
#: 0.3.0 (2026-10-07): the ping gate reaches `PING_OWN_PX`, not `ICON_PX`,
#: and links its ping; the lobe test's ring is an annulus (enemy-teardrop-0.3.0).
#: 0.4.0 (2026-10-07): the ring search that finds each red icon
#: (`minimap.icons`: radii, area, kernel, separation) reads at `icon_scale`
#: too, where it read the widget scale alone.
#: 0.5.0 (2026-10-07): that ring search keeps only the integer radii inside
#: the scaled base band (`minimap.icons(radii="inside")`): 6 to 8 px at the
#: 331 px key's map scale (0.637), where 0.4.0 searched from 5 px. A 465 px
#: key reads the rows 0.4.0 read.
#: 0.6.0 (2026-10-07): the ring finds keep only those with a lobe past the
#: ring (`RING_LOBE`), and beside an icon the last frame accepted the search
#: also proposes the gated ring peaks (`RING_SEED` "centroid+prior").
#: 0.7.0 (2026-10-07): every gated peak is proposed (`RING_SEED` "peaks"),
#: its coverage scored on soft redness (`RING_COVER`), no lobe required;
#: the `portrait_gate` fix keeps only finds that fit an enemy portrait.
MINIMAP_OBJECT_BASE = "minimap-object-0.7.0"

#: The switchable fixes, in stamp order.
FIXES = ("teardrop_box", "slab_gate", "owner_gate", "portrait_gate")
#: Which fixes are on. A caller may pass its own map; the stamp records it.
ENABLED = {"teardrop_box": True, "slab_gate": True, "owner_gate": True,
           "portrait_gate": True}


def minimap_object_version(fixes: dict | None = None) -> str:
    """The stream's stamp: the base version plus each fix that is on."""
    fixes = ENABLED if fixes is None else fixes
    on = [f for f in FIXES if fixes.get(f)]
    return f"{MINIMAP_OBJECT_BASE}+{'+'.join(on) if on else 'nofix'}"


# The enemy ring fit: the HSV key and gates stage 2 used
# (prototypes/minimap_icons.enemy_red_mask, prototypes/minimap_ring_fit).
HUE_LO, HUE_HI, SAT_MIN, VAL_MIN = 8, 168, 100, 90
COV_MIN, INNER_RED_MAX = 0.30, 0.25
RING = 11.0          # the fixed box radius with teardrop_box off, * scale
TIP_PAD = 1.5        # the teardrop box's pad past the fitted tip, * scale
RED_SHARE = 0.25     # the slab gate's floor
ICON_PX = 10.0       # an icon's radius for the gate disc and for "under an icon", * scale
X_OWN_PX = 6.0       # a ring find this near a shape-confirmed red X is the X's, * scale
#: A teardrop read this near a drawn ping sits on the ping's own glyph and is
#: the ping reader's, * scale. On the development matches the false reads on
#: a ping sat at a median of 5.2 base px from it, and most real enemies the
#: `ICON_PX` gate refused at about 8. Against the ping gate off
#: (`teardrop_refusals.py gate --off gx`), the gate at 7 refuses
#: [metric:teardrop_refusals/gate/r1@dev3#refused_real=18] real enemies and
#: removes [metric:teardrop_refusals/gate/r1@dev3#removed_false=62] true false
#: accepts; at `ICON_PX`,
#: [metric:teardrop_refusals/gate/g10@dev3#refused_real=46] and
#: [metric:teardrop_refusals/gate/g10@dev3#removed_false=76].
PING_OWN_PX = 7.0
# The "?" witness (prototypes/minimap_objects_s2.question_at).
Q_GONE_MS = 3300.0   # the measured gone time's maximum (3.28 s), rounded up
Q_SWAP_MS = 200.0    # the icon's last frame lies this near the run's first
PLACE_PX = 6.0       # a red blob at the "?"'s place, * scale
GAP_FRAMES = 2       # frames the red run may miss

#: The ring search's seed (`minimap.icons`): "centroid", one circle per red
#: blob (to 0.5.0); "peaks", every gated peak of the ring score (0.7.0);
#: "centroid+prior", the centroid's finds plus the peaks within `PRIOR_PX`
#: of an icon the last read frame, at most `PRIOR_MS` before, accepted
#: (0.6.0). "peaks" needs the portrait gate: where the gate is on and cannot
#: read, the search falls back to "centroid".
RING_SEED = "peaks"
#: Keep only ring finds with a lobe past the ring (`minimap.LOBE_MIN_FRAC`,
#: `icons(require_facing=True)`); on in 0.6.0 only.
RING_LOBE = False
#: What the "peaks" ring coverage scores: "soft", the mean `teardrop.redness`
#: over the circle (0.7.0); "binary", the HSV key's share (to 0.6.0).
#: On a seeded sample of 9acf02f98283's T1d icon places the key held a median
#: [metric:enemy_portrait_gate/softcal@9acf02f98283#bin_median_ring_unproposed=0.275]
#: of the ring at icons the search missed, the soft score
#: [metric:enemy_portrait_gate/softcal@9acf02f98283#soft_median_ring_unproposed=0.483];
#: at places with no icon drawn both stay near zero.
RING_COVER = "soft"
#: The portrait gate's cut on `identity.rendered_art_fit` (mean squared
#: z-score to the closest enemy reference): the 99th percentile over the T1d
#: hits of 9acf02f98283's 0.5.0 reread
#: [metric:enemy_portrait_gate/separation/b1@9acf02f98283#hit_fit_p99=1.509],
#: the rule the owner's teammate fit uses (P99 of bound icons), taken at the
#: 331 px widget and held unchanged at 465 px.
FIT_MAX = 1.5
PRIOR_PX = 10.0      # a peak this near a last-frame icon continues it, * scale
PRIOR_MS = 250.0     # the last read frame is the prior this long

REFUSALS = ("widget_not_drawn", "widget_shape")


def enemy_red_mask(crop: np.ndarray) -> np.ndarray:
    """The enemy ring fit's key: saturated, bright red in HSV."""
    import cv2

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(np.int16) for i in range(3))
    return ((h < HUE_LO) | (h > HUE_HI)) & (s > SAT_MIN) & (v > VAL_MIN)


def slab_red_share(red: np.ndarray, slab: np.ndarray, x: float, y: float, scale: float) -> float | None:
    """The share of the redness within ICON_PX * scale of (x, y) that lies on
    the slab; None where the disc holds no red."""
    r = ICON_PX * scale
    h, w = red.shape
    x0, x1 = max(0, int(x - r)), min(w, int(x + r) + 2)
    y0, y1 = max(0, int(y - r)), min(h, int(y + r) + 2)
    if x0 >= x1 or y0 >= y1:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    disc = np.hypot(xx - x, yy - y) <= r
    sub = red[y0:y1, x0:x1]
    tot = float(sub[disc].sum())
    if tot <= 0:
        return None
    return float(sub[disc & slab[y0:y1, x0:x1]].sum()) / tot


def _gate(fixes, red, slab, x, y, scale) -> tuple[float | None, str | None]:
    """The slab gate's share and, where it drops the candidate, the reason."""
    if not fixes.get("slab_gate"):
        return None, None
    share = slab_red_share(red, slab, x, y, scale)
    if share is not None and share < RED_SHARE:
        return share, f"off_slab: red share {share:.2f} < {RED_SHARE}"
    return share, None


def _rnd(v, n=2):
    return None if v is None else round(float(v), n)


def _owned(fixes, marks, pings, t_ms, x, y, scale,
           ping_ids=None) -> tuple[str, str, list | None] | None:
    """The `owner_gate`: the channel that observes a teardrop read's place, as
    `(cls, reason, evidence)`, or None. A shape-confirmed red X within
    `X_OWN_PX` * scale is the X classifier's; a confirmed ping drawn at `t_ms`
    within `PING_OWN_PX` * scale is the ping reader's, and `evidence` links
    that ping's `entity_id` (from `ping_ids`) and its distance in widget px.
    Each owner is asked, not restated: the X is `minimap_x_marks`' answer,
    the ping a stored `ping` event."""
    if not fixes.get("owner_gate"):
        return None
    if any(math.hypot(q["x"] - x, q["y"] - y) <= X_OWN_PX * scale for q in marks["red"]):
        return "x_mark", "owned_by_x_classifier: teardrop read", None
    if pings is not None and pings.size and t_ms is not None:
        on = np.flatnonzero((pings[:, 0] <= t_ms) & (t_ms <= pings[:, 1]))
        if on.size:
            d = np.hypot(pings[on, 2] - x, pings[on, 3] - y)
            i = int(np.argmin(d))
            if d[i] <= PING_OWN_PX * scale:
                eid = None if ping_ids is None else ping_ids[on[i]]
                return "ping", "owned_by_ping: teardrop read", [
                    {"stream": "ping", "entity_id": eid, "d_px": _rnd(d[i])}]
    return None


def portrait_gate_inputs(store_root, sid: str) -> dict:
    """What the `portrait_gate` reads for one session: the enemy side's
    candidate set from the stored lineup and the rendered-art references, or
    None with the reason it cannot read.

    `{"names": [...] | None, "refs": table | None, "reason": str | None,
    "lineup_view": stamp, "lineup_file": version, "portrait_refs": version}`.
    The set is the match's enemy five, from the stored lineup
    (`lineup.portrait_candidates`): named slots and each refused slot's best
    guess. A side admitting fewer than `N_SLOTS` agents holds one the set
    cannot represent, and a portrait of that agent would fit none, so the
    gate refuses to read (`lineup_short`) rather than drop it. The full
    29-agent gallery is never the gate's set.
    """
    import json
    from pathlib import Path

    from . import lineup
    from .adjudication.identity import load_ally_portrait_references
    from .input_stamps import NO_ROWS
    from .roster import N_SLOTS

    root = Path(store_root)
    f = root / "lineups" / f"{sid}.json"
    out = {"names": None, "refs": None, "reason": None,
           "lineup_view": lineup.view_stamp(sid, root),
           "lineup_file": ((json.loads(f.read_text(encoding="utf-8")).get("version") or "unstamped")
                           if f.is_file() else NO_ROWS),
           "portrait_refs": NO_ROWS}
    refs = load_ally_portrait_references(root)
    if refs is not None:
        out["portrait_refs"] = refs.get("version") or NO_ROWS
    if refs is None:
        out["reason"] = "no_portrait_references"
    elif refs.get("features_version") != ALLY_PORTRAIT_FEATURES_VERSION:
        out["reason"] = (f"portrait_references_stale: {refs.get('features_version')} "
                         f"!= {ALLY_PORTRAIT_FEATURES_VERSION}")
    else:
        cands, _stamp = lineup.portrait_candidates(sid, root)
        five = None if cands is None else (cands.get("enemy") or [])
        if five is None:
            out["reason"] = "no_lineup"
        elif len(five) < N_SLOTS:
            out["reason"] = f"lineup_short: {len(five)} of {N_SLOTS} enemy agents admitted"
        else:
            out["names"], out["refs"] = list(five), refs
    return out


def portrait_gate(feats: dict, gate: dict | None) -> dict:
    """The `portrait_gate` verdict on one find's stored `portrait_features`:
    `{"fit", "margin", "reason"}`. `fit` is the identity owner's absolute fit
    to the closest of the candidate set (`identity.rendered_art_fit`, asked
    once per name), `margin` the second-closest's fit less it. `reason` is
    None where the find fits within `FIT_MAX`, `not_a_portrait: ...` where
    it does not, and the inputs' reason where the gate cannot read (then
    `fit` is None and nothing is refused). No name leaves this function."""
    from .adjudication.identity import rendered_art_fit

    if not gate or not gate.get("names"):
        return {"fit": None, "margin": None,
                "reason": (gate or {}).get("reason") or "no_candidates"}
    fits = sorted(r[0] for n in gate["names"]
                  if (r := rendered_art_fit(feats, [n], gate["refs"])) is not None)
    if not fits:
        return {"fit": None, "margin": None, "reason": "no_features"}
    fit = fits[0]
    margin = fits[1] - fit if len(fits) > 1 else None
    reason = (None if fit <= FIT_MAX else
              f"not_a_portrait: fit {fit:.2f} > {FIT_MAX} to the enemy five")
    return {"fit": fit, "margin": margin, "reason": reason}


def read_frame(crop: np.ndarray, ctx: dict, *, scale: float, fixes: dict | None = None,
               turn: bool = False, t_ms: float | None = None,
               prior: list | None = None) -> dict:
    """One drawn frame: enemies, X marks, red blobs, refusals.

    `ctx` holds the baked `floor` and `slab` (`minimap.floor_mask`,
    `slab_mask`). `scale` is the icon scale (`object_context`'s
    `icon_scale`); `ctx["scale"]`, the widget's, is what the X owner is
    given. `turn` rotates each enemy's aligned portrait 180 degrees,
    for a widget drawn turned over [domain:minimap/upright-icons-on-turned-map].
    The "?" marks need earlier frames and are added by `last_known`.
    """
    from . import ally_portrait, minimap, teardrop
    from .adjudication.death import minimap_x_marks

    fixes = ENABLED if fixes is None else fixes
    floor, slab = ctx["floor"], ctx["slab"]
    red = teardrop.redness(crop)
    enemies, refused = [], []
    # The X classifier owns every shape-confirmed X: a ring find the
    # teardrop does not read at an X is the X's, not a missed enemy.
    # The X owner is asked at the scale it has always been given (the
    # widget's), so the death stream's inputs do not move with this reader.
    marks = minimap_x_marks(crop, floor, ctx.get("scale", scale))
    # The enemy ring search keeps the radii inside the scaled band. At the
    # 331 px key's map scale a 5 px ring rings the true icons and red blobs
    # alike: on 9acf02f98283 it adds hits and true false accepts together,
    # the latter past the lane's bar (`prototypes/one_transform_check.py`
    # ablation `rmin6`). The self and ally fits keep the nearest radii.
    key = enemy_red_mask(crop)
    gate = ctx.get("portrait_gate")
    seed = ring_seed(fixes, gate)
    soft = seed == "peaks" and RING_COVER == "soft"
    finds = minimap.icons(key, crop, floor, cov_min=COV_MIN,
                          inner_max=INNER_RED_MAX, require_facing=RING_LOBE, support=slab,
                          seed=seed, scale=scale, radii="inside",
                          cov_map=red if soft else None)
    if RING_SEED == "centroid+prior" and prior:
        # Continue the prior: the gated ring peaks within PRIOR_PX of an
        # icon the last frame accepted, where no centroid find lies.
        sep = minimap.MIN_ICON_SEPARATION_PX * scale
        for d in minimap.icons(key, crop, floor, cov_min=COV_MIN, inner_max=INNER_RED_MAX,
                               require_facing=RING_LOBE, support=slab, seed="peaks",
                               scale=scale, radii="inside"):
            if (any(math.hypot(d["cx"] - px, d["cy"] - py) <= PRIOR_PX * scale for px, py in prior)
                    and not any(math.hypot(d["cx"] - g["cx"], d["cy"] - g["cy"]) < sep
                                for g in finds)):
                finds.append(dict(d, rests_on="prior"))
    for d in finds:
        ring = {"x": _rnd(d["cx"]), "y": _rnd(d["cy"]), "r": _rnd(d.get("r"))}
        f = teardrop.fit_icon(None, "enemy", d["cx"], d["cy"], scale=scale, key=red)
        reason = None if f.get("read") else f.get("reason")
        position_only = (reason == "ambiguous_facing" and fixes.get("teardrop_box")
                         and "x" in f)
        if reason is not None and not position_only:
            # A refused fit is never emitted with the fixed ring as its
            # extent, which cuts the icon [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK6_n=6];
            # it is stored at the ring's centre with no extent and its reason.
            at_x = any(math.hypot(q["x"] - d["cx"], q["y"] - d["cy"]) <= X_OWN_PX * scale
                       for q in marks["red"])
            refused.append({"cls": "x_mark" if at_x else "enemy", "x": ring["x"],
                            "y": ring["y"],
                            "reason": ("owned_by_x_classifier: teardrop " if at_x
                                       else "teardrop: ") + str(reason),
                            "ncc": _rnd(f.get("ncc"), 3)})
            continue
        x, y = float(f["x"]), float(f["y"])
        own = _owned(fixes, marks, ctx.get("pings"), t_ms, x, y, scale, ctx.get("ping_ids"))
        if own:
            refused.append({"cls": own[0], "x": _rnd(x), "y": _rnd(y), "reason": own[1],
                            "ncc": _rnd(f.get("ncc"), 3),
                            **({"evidence": own[2]} if own[2] else {})})
            continue
        tip_d = math.hypot(f["tip_x"] - x, f["tip_y"] - y)
        box = tip_d + TIP_PAD * scale if fixes.get("teardrop_box") else RING * scale
        share, drop = _gate(fixes, red, slab, x, y, scale)
        if drop:
            refused.append({"cls": "enemy", "x": _rnd(x), "y": _rnd(y), "reason": drop})
            continue
        img = ally_portrait.align_icon(crop, x, y)
        if turn:
            img = np.ascontiguousarray(img[::-1, ::-1])
        feats = ally_portrait.stored(ally_portrait.portrait_features(img, minimap.portrait_key(img)))
        pg = portrait_gate(feats, gate) if fixes.get("portrait_gate") else None
        if pg is not None and pg["fit"] is not None and pg["reason"]:
            refused.append({"cls": "enemy", "x": _rnd(x), "y": _rnd(y), "reason": pg["reason"],
                            "ncc": _rnd(f.get("ncc"), 3), "portrait_fit": _rnd(pg["fit"], 3),
                            "portrait_margin": _rnd(pg["margin"], 3)})
            continue
        enemies.append({
            "x": _rnd(x), "y": _rnd(y), "r": _rnd(box),
            "facing": None if position_only else _rnd(float(f["deg"]) % 360.0, 1),
            "facing_reason": "ambiguous_facing" if position_only else None,
            "tip": [_rnd(f["tip_x"]), _rnd(f["tip_y"])], "ncc": _rnd(f.get("ncc"), 3),
            "margin": _rnd(f.get("margin"), 3), "ring": ring, "slab_red_share": _rnd(share, 3),
            "portrait_features": feats,
            **({"portrait_fit": _rnd(pg["fit"], 3), "portrait_margin": _rnd(pg["margin"], 3)}
               if pg is not None and pg["fit"] is not None else {}),
            **({"rests_on": "prior"} if d.get("rests_on") else {})})
    xr = []
    for q in marks["red"]:
        share, drop = _gate(fixes, red, slab, q["x"], q["y"], scale)
        if drop:
            refused.append({"cls": "x_mark", "x": q["x"], "y": q["y"], "reason": drop})
        else:
            xr.append(q)
    blobs = []
    for a, bx, by in marks["red_other"]:
        if any(math.hypot(e["x"] - bx, e["y"] - by) <= ICON_PX * scale for e in enemies):
            continue
        share, drop = _gate(fixes, red, slab, bx, by, scale)
        if drop:
            refused.append({"cls": "red_blob", "x": bx, "y": by, "reason": drop})
            continue
        blobs.append([a, bx, by])
    return {"reason": None, "enemies": enemies,
            "x_marks": {"blue": marks["blue"], "red": xr}, "red_blobs": blobs,
            "refused": refused}


def ring_seed(fixes: dict, gate: dict | None) -> str:
    """The seed the ring search uses: `RING_SEED`, except that "peaks" with
    the `portrait_gate` on and unable to read (`gate` holds no names) falls
    back to "centroid", the proposal that needs no verifier."""
    if RING_SEED == "centroid+prior":
        return "centroid"
    if RING_SEED == "peaks" and fixes.get("portrait_gate") and not (gate or {}).get("names"):
        return "centroid"
    return RING_SEED


def last_known(frames: list[dict], scale: float) -> None:
    """Mark each read frame's red blobs as "?" marks or leave them, in place.

    For each red blob of frame t, walk back over the earlier read frames: an
    enemy icon within ICON_PX * scale ends the walk (`icon_last`); a red blob
    within PLACE_PX * scale extends the run (`onset`); more than GAP_FRAMES
    misses end it. A "?" is a blob whose run begins at most Q_SWAP_MS after
    the icon's last frame and at most Q_GONE_MS before t. `questions` holds
    each with the key of the icon it replaced; `red_other` holds the rest,
    each with why it is no "?".
    """
    read = [f for f in frames if f.get("reason") is None]
    T = [f["t_ms"] for f in read]
    for idx, f in enumerate(read):
        qs, other = [], []
        t = f["t_ms"]
        for a, bx, by in f["red_blobs"]:
            on, miss, k, icon_last, icon_key = t, 0, idx, None, None
            while k - 1 >= 0 and t - T[k - 1] <= Q_GONE_MS + Q_SWAP_MS + 200.0:
                k -= 1
                g = read[k]
                hit = next((i for i, e in enumerate(g["enemies"])
                            if math.hypot(e["x"] - bx, e["y"] - by) <= ICON_PX * scale), None)
                if hit is not None:
                    icon_last, icon_key = g["t_ms"], f"{g['t_ms']:.1f}:{hit}"
                    break
                if any(math.hypot(x - bx, y - by) <= PLACE_PX * scale
                       for _a, x, y in g["red_blobs"]):
                    on, miss = g["t_ms"], 0
                else:
                    miss += 1
                    if miss > GAP_FRAMES:
                        break
            why = ("no_icon_before" if icon_last is None
                   else "icon_ended_early" if on - icon_last > Q_SWAP_MS
                   else "older_than_gone" if t - on > Q_GONE_MS else None)
            if why is None:
                qs.append({"x": bx, "y": by, "onset_ms": on, "icon_last_ms": icon_last,
                           "icon_key": icon_key, "age_ms": round(t - on, 1)})
            else:
                other.append({"x": bx, "y": by, "area": a, "reason": why})
        f["questions"], f["red_other"] = qs, other
    for f in read:
        f.pop("red_blobs", None)


def object_context(store, sid: str) -> tuple[dict | None, str | None]:
    """The crop cache and the baked masks one session's read needs, or None
    with the reason."""
    import cv2

    from . import geometry
    from .minimap import floor_mask, slab_mask, widget_scale
    from .profiles import get_profile
    from .roi_cache import RoiCache

    man = store.read_manifest(sid)
    cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
    if cache is None:
        return None, f"no minimap crop cache ({why})"
    geo = geometry.path_of(sid, store.root)
    if geo is None or not geo.is_file():
        return None, "no baked geometry"
    med = geometry.reference_static(sid, store.root)
    sd = geometry.stability(sid, store.root, med.shape[:2])
    floor = floor_mask(med, sd=sd)
    pings, ping_ids, ping_version = stored_pings(store, sid)
    # Icons follow the map zoom [domain:minimap/icons-follow-map-zoom]: the
    # one transform is base x widget scale x map zoom (`geometry.MapScale`).
    icon_scale, icon_scale_source = geometry.drawn_scale(sid, store.root, floor.shape[1])
    return {"cache": cache, "floor": floor, "slab": slab_mask(med, sd=sd),
            "portrait_gate": portrait_gate_inputs(store.root, sid),
            "sgray": cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64),
            "rect": cache.rect_of("minimap"), "scale": widget_scale(floor.shape[1]),
            "geometry_key": geometry.key_of(sid, store.root),
            "pings": pings, "ping_ids": ping_ids, "ping_version": ping_version,
            "icon_scale": icon_scale, "icon_scale_source": icon_scale_source}, None


def stored_pings(store, sid: str) -> tuple[np.ndarray | None, list | None, str]:
    """The ping reader's confirmed pings, `(t0_ms, t1_ms, x, y)` rows in widget
    px, each row's `entity_id`, and the stream's stamp. Where no ping stream
    is stored: `(None, None, NO_ROWS)`, so the gate abstains rather than
    calling every place unpinged, and `plan` names the stream stale once
    pings are written (`input_stamps.moved`)."""
    from .input_stamps import NO_ROWS
    rows = store.read_events("ping", sid)
    if not rows:
        return None, None, NO_ROWS
    stamp = next((r.get("producer_version") or r.get("ping_version") for r in rows), None)
    on, out, ids = {}, [], []
    for r in rows:
        if r.get("event_kind") == "entity_state":
            on[r["entity_id"]] = (float(r["t_ms"]), r["position"])
        elif r.get("event_kind") == "entity_deleted" and r.get("entity_id") in on:
            t0, (x, y) = on.pop(r["entity_id"])
            out.append((t0, float(r["t_ms"]), float(x), float(y)))
            ids.append(r["entity_id"])
    return np.asarray(out, float).reshape(-1, 4), ids, stamp


def read_times(ctx: dict, times, fixes: dict | None = None) -> list[dict]:
    """Frame rows at cache `times` (each held by the cache), "?" marks included."""
    from .minimap import widget_drawn

    cache = ctx["cache"]
    x0, y0, x1, y1 = ctx["rect"]
    frames = []
    last_t, last = None, None
    for smp in cache.samples(sorted(float(t) for t in times), rois=["minimap"]):
        crop = smp.frame[y0:y1, x0:x1]
        row = {"kind": "frame", "t_ms": float(smp.t_ms), "frame_idx": int(smp.frame_idx)}
        if crop.shape[:2] != ctx["floor"].shape:
            row["reason"] = "widget_shape"
        elif not widget_drawn(crop, ctx["sgray"], ctx["floor"]):
            row["reason"] = "widget_not_drawn"
        else:
            seg = cache.widget.at(smp.t_ms) if cache.widget is not None else None
            turn = bool(seg) and int(seg.get("rotation", 0)) == 180
            prior = (last if last_t is not None and float(smp.t_ms) - last_t <= PRIOR_MS
                     else None)
            row.update(read_frame(crop, ctx, scale=ctx["icon_scale"], fixes=fixes, turn=turn,
                                  t_ms=float(smp.t_ms), prior=prior))
            last_t, last = float(smp.t_ms), [(e["x"], e["y"]) for e in row["enemies"]]
        frames.append(row)
    frames.sort(key=lambda r: r["t_ms"])
    last_known(frames, ctx["icon_scale"])
    return frames


def read_session(store, sid: str, fixes: dict | None = None) -> dict:
    """Every frame of the session's minimap crop cache, read.

    Returns `{"rows": [...]}`, a coverage row first and a row per cached
    frame, or `{"skipped": why}`."""
    from .roi_cache import ROI_CACHE_VERSION

    fixes = dict(ENABLED if fixes is None else fixes)
    ctx, why = object_context(store, sid)
    if ctx is None:
        return {"skipped": why}
    gate = ctx.get("portrait_gate") or {}
    times = ctx["cache"].holds()
    frames = read_times(ctx, times, fixes)
    version = minimap_object_version(fixes)
    read = [f for f in frames if f.get("reason") is None]
    head = {"kind": "coverage", "session": sid, "minimap_object_version": version,
            "fixes": {f: bool(fixes.get(f)) for f in FIXES},
            "roi_cache_version": ROI_CACHE_VERSION, "teardrop_version": TEARDROP_VERSION,
            "enemy_teardrop_version": ENEMY_TEARDROP_VERSION,
            "inputs": {"ping": ctx.get("ping_version"),
                       **({k: gate.get(k) for k in ("lineup_view", "lineup_file", "portrait_refs")}
                          if fixes.get("portrait_gate") else {})},
            "portrait_gate": ({"candidates": gate.get("names"), "reason": gate.get("reason"),
                               "candidate_source": "lineup.portrait_candidates, enemy side",
                               "ring_seed_used": ring_seed(fixes, gate)}
                              if fixes.get("portrait_gate") else None),
            "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION,
            "geometry_key": ctx["geometry_key"], "scale": ctx["scale"],
            "icon_scale": ctx["icon_scale"], "icon_scale_source": ctx["icon_scale_source"],
            "parameters": {"RING_SEED": RING_SEED, "RING_LOBE": RING_LOBE,
                           "RING_COVER": RING_COVER, "FIT_MAX": FIT_MAX,
                           "COV_MIN": COV_MIN, "INNER_RED_MAX": INNER_RED_MAX, "RING": RING,
                           "X_OWN_PX": X_OWN_PX,
                           "TIP_PAD": TIP_PAD, "RED_SHARE": RED_SHARE, "ICON_PX": ICON_PX,
                           "PING_OWN_PX": PING_OWN_PX,
                           "Q_GONE_MS": Q_GONE_MS, "Q_SWAP_MS": Q_SWAP_MS,
                           "PLACE_PX": PLACE_PX, "GAP_FRAMES": GAP_FRAMES},
            "frames": len(frames), "read": len(read),
            "refused": {k: sum(f.get("reason") == k for f in frames) for k in REFUSALS},
            "enemies": sum(len(f["enemies"]) for f in read),
            "enemies_position_only": sum(e["facing"] is None for f in read for e in f["enemies"]),
            "x_blue": sum(len(f["x_marks"]["blue"]) for f in read),
            "x_red": sum(len(f["x_marks"]["red"]) for f in read),
            "questions": sum(len(f["questions"]) for f in read),
            "candidates_refused": dict(sorted(Counter(
                f"{x['cls']}:{x['reason'].split(':')[0]}" for f in read
                for x in f["refused"]).items()))}
    for f in frames:
        f["minimap_object_version"] = version
    return {"rows": [head] + frames}
