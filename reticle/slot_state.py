r"""Player slots and a position belief for every open slot, every frame.

Owns [owns:slot-state] and [owns:position-belief]: the one owner of where a
slot is believed to be, the player's own included. The self slot's
per-instant law (`resolve`, `Fix`, `absent_instants`, belief-0.3.0) moved
here from `reticle/belief.py` unchanged; the section at the end holds it.
Throughout, evidence arrives as arguments or from stored rows named in the
stamp, a `Fix` or a region is never evidence, and observed and believed
coverage are reported apart.

    .\.venv\Scripts\python.exe -m reticle slot-state SESSION [--binding causal|post_round] [--write] [--at MS]

ENTITY_STATE step 1 (docs/ENTITY_STATE.md; QUESTION_ACCEPTANCE B1),
promoted from `prototypes/entity_state.py` (entity-state-0.3.0) and
`prototypes/entity_binding.py` (entity-binding-0.1.1), whose scorers stay
in the prototype and call this module. It reads STORED rows only: the
`ally_icon` frame and icon rows, the `round_entity` observations and
entities, the death owner's verdicts, the lineup, the round table, and for
the causal binding the `ping`, `spike` and `tray_kit` rows and the baked
geometry's labels. It decodes nothing and reads no crop.

Entities
--------
State is held per entity row, keyed `(kind, id)` (`EntityRow`). Today one
kind exists, `player`, on both sides: the five ally slots, keyed
`<session>:ally:slot:<k>`, then the five enemy slots, keyed
`<session>:enemy:slot:<k>`, as the lineup keys them. The belief law
(`beliefs`, `contains`, `region_area`), the round reset (`seg_start`) and
the storage record work over any (entity, frame) arrays and assume no kind.
A second kind joins by three extension points, never by a second module:

* `EntityRow`: its `kind`, `id`, `side`, `owner` (the owner entity's id,
  e.g. an ability instance's caster slot) and `spawn`/`end` reasons;
* a lifecycle builder returning its (rows, F) open mask, as
  `player_lifecycle` does for players (an ability instance would open at its
  cast and close at its expiry, never past its round);
* a binder returning its (rows, F) X, Y, has and witness arrays, as
  `causal_bind` and `bind_entities` do for players.

`stack_entities` joins the blocks; `beliefs` then runs once over all rows.
Ability nodes keep their own rows (`build_abilities`), not the frame axis.

Ability children and effects
----------------------------
docs/ABILITY_ENTITIES.md makes this module the owner of ability instances
(`ability` children) and what they do to players (`effect` entities). They
form a tree: slot, ability instance, spawned objects nested to any depth,
effects; each node has its own lifecycle and a revisable parent binding to
any entity key. The owner holds
[owns:ability-child], [owns:ability-effect] and [owns:ability-owner].
`build_abilities` walks every slot of both teams in one pass (step 3): a
side is a property of the slot, a witness's reach a property of its channel.
`CHANNELS` names every input the child owner may read and what each may do
(open a child, join one, end one, name its kind, claim its agent), with the
sides it observes and opens on, stamped `ABILITY_CHANNELS_VERSION`;
`ABILITY_LANES` names the two lanes ability entities reach consumers through. The ABILITY ratchet
(`ratchets.ability_findings`, run by `doctor`) errors on any ability stream,
lane or ownership entry these two tables and this owner do not account for,
and the event validator (`entity_contract.check_ability_row`) rejects an
ability or effect row outside lane `ability`, from another producer, or
named by another key's verdict without `depends_on`. No agent name is
decided here: a child's agent will be the `agent-identity` arbiter's verdict
on the child key.

Names
-----
This module decides no agent name. Each player slot's agent is the
`agent-identity` arbiter's lineup verdict (`lineup.load_lineup`'s
`agent_identity`); a fit's portrait log ratio is the arbiter's
`identity.rendered_art_scores`; spellings compare through `agent_names`.
Results declare what they rest on (`rests_on`).

Slots (lifecycle)
-----------------
A slot opens `alive` at each round's start (the round table's clock reset)
and stays open through the post-round period
[domain:rounds/post-round-period] until the next round starts. A named ally
victim of the death owner's verdict closes its slot at the verdict's time,
only inside the verdict's own round; a second-life death leaves it open
[domain:rounds/resurrection-mechanics]; a revive reopens it
[domain:killfeed/revive-entries]; an unnamed victim closes nothing.

No state outlives a round: the last fix, the chain evidence and the motion
prior all reset where `seg_start` changes, and every comparison (nearest
other slot, continuity, assignment) runs within one frame or one round.

Binding fits to slots
---------------------
`causal` (the default, entity-binding-0.1.1): at each frame every ally fit
goes to an open teammate slot or to its own non-player column by one
`track.assign` over a motion cost from what was bound before and the fit's
own portrait log ratio; the self fit binds to the player's slot while it is
open, then to the spectated teammate's (`tray_kit`'s witness, no
lookahead) [domain:minimap/self-icon-shows-spectated]. Non-player reasons
(`off_map`, `ability_glyph`, `not_a_teammate`, `ping`, `spike`) come from
stored owners. Chains of portrait evidence move between slots when they
gain `SWAP_MIN` nats. `post_round` (entity-state-0.2.0's binding) binds the
stored `round_entity` entities through their pooled verdicts and
continuity. The prototype docstrings hold the full rules and their scores.

Beliefs
-------
Every open slot holds one belief per frame: `fit` (a disc of
`r_fit = r_icon + v_max dt_frame` round a witnessed fit), `fit_unnamed` (an
unwitnessed fit: its disc together with the reach from the last witnessed
fix), `crowd` (no fit; the last fix lay within one icon diameter of another
slot that still has a fit [domain:minimap/coincident-icons]), `reach` (the
disc of `v_max (t - t_fix) + r_fit` round the round's last witnessed fix),
`unanchored` (no fix this round: the map). `spawn_anchor` can replace
`unanchored` with `spawn` (the disc round the side's pre-round area from
the callout-region owner, which the game files' spawn barriers bound, grown
by reach from `gametime`'s barrier drop, the side from the rounds owner)
until that disc covers the map, on the sides `SPAWN_ANCHOR_SIDES` names.
`v_max` is the top ground speed
from the game files [domain:game_data/character-movement-speeds] in metres
[domain:game_data/game-units-centimetres]. Negative evidence is off.
Reach is still a Euclidean disc: the walk reach the gate needs (BACKLOG item
3) waits for a walk graph baked with the geometry, since `reticle/` may not
read the prototypes' sightline tables.

Enemy slots
-----------
Five per round on the enemy side (`enemy_rows`), each named by the
`agent-identity` arbiter's lineup verdict on its key, never here. The enemy
lane keeps its readers and its adjudication: `minimap_objects` stores the
enemy finds, `round_lifetimes` joins them into tracks and decides which are
real (`detection_reality`), and `adjudication.identity` names each track.
`bind_enemy_tracks` reads the stored `enemy_track` rows and binds a track's
observations to the slot whose verdict names the same agent as the track's
verdict (`agent_names.agent_key`); an unnamed track, a refused track and a
name outside the enemy five bind nothing and are counted by reason. Every
bound fit is witnessed: the arbiter named its track. The track's verdict is
pooled over the whole track, so it is a post-round witness, as the
`post_round` binding's named entities are. The lifecycle is
`player_lifecycle` over the death owner's enemy verdicts; the law is
`beliefs`, run per side so a crowd's host is an icon of the same side. A slot
never fixed this round is `unanchored`; one seen, then unseen, holds `reach`
from its last fix; a dead one is `closed` at the death owner's verdict.
Reach stays the Euclidean disc, as for allies.
`prototypes/coaching_belief.py`'s reachable set cannot replace it without a
bake: it floods the walk graph of the prototypes' 3D sightline table
(`sightlines_3d`), which `reticle/` may not read, so the port waits for the
walk-graph bake.

Scored on the six replay sessions (`reticle acceptance slots`), a living
enemy lies inside his slot's region on
[metric:question_acceptance/slots/enemy@all6#calibration=0.9881] of drawn
frames in live play, and inside a fit's disc on
[metric:question_acceptance/slots/enemy@all6#kind_fit=0.9434] of the frames
his slot holds a fit; that is
[metric:question_acceptance/slots/enemy@all6#lane_coverage=0.0412] of them.
The slot is `unanchored` on
[metric:question_acceptance/slots/enemy@all6#unanchored=0.6018] of its open
frames, so the high calibration is mostly the map: a calibrated belief, not
a sharp one.

World metres come from valorant-api's map constants and the geometry's
`shade_fit` (`replay_source.map_frame_for_geometry`; no replay is read).

Storage and the gate's query
----------------------------
`frame_record` lays the beliefs out frames by entities, with QUESTION_ACCEPTANCE
section 4's `read`, `t_obs` and `rate` (all `full` and `fine` at the stored
15 Hz grid); `write_record` stores it at `<store>/l2/slot_state/<session>.npz`
with a stamp naming this version and every input's. `RegionCursor.at`
answers, for each instant in turn, each entity's point disc and reach disc in
metres and widget pixels: the belief a per-frame gate asks before it reads.
The cursor moves forward only, steps frame to frame within a round and resets
at the round barrier, so no query searches past its round; `region_at` is
the one-off form. The gate lives below this layer (`passes`), so it should
take a cursor's `at` as a callable rather than import this module.

Promotion check (2026-10-09)
----------------------------
On 9acf02f98283, c817691bcd15 and d3dcfb182ab1, both bindings, every belief,
binding and lifecycle array and every count equals the prototype's
(entity-state-0.3.0). Scored against the replay on every drawn frame, the
causal binding holds a living teammate on
[metric:entity_state/replay@9acf02f98283_causal~2026-10-09T10:24:30#calibration=0.9718]
and [metric:entity_state/replay@c817691bcd15_causal#calibration=0.9655] of
teammate-frames; d3dcfb182ab1 has no Riot record, so the prototype's replay
scorer cannot pair its players (QUESTION_ACCEPTANCE B8).
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .agent_names import agent_key, reference_agent, same_agent
from .minimap import FIT_ERR_PX, GAP_MS, RUN_PX, admit_steps, crosses
from .store import DEFAULT_STORE, Store

#: slot-state-0.1.0 (2026-10-09): entity-state-0.3.0 and entity-binding-0.1.1
#: promoted; agent spellings compare through `agent_names.agent_key`.
#: 0.2.0 (2026-10-09): the five enemy slots join the entity axis after the
#: ally five, fed by the stored `enemy_track` rows; ally rows are unchanged.
#: The spawn anchor (`spawn_anchor`, 2026-10-09) ships off and changes no
#: belief, so it bumps nothing; turning it on bumps this.
#: 0.3.0 (2026-10-09): the module builds the player's ability children and
#: effects (`build_abilities`, stamped `ABILITY_CHILD_VERSION` and
#: `ABILITY_EFFECT_VERSION`); the slot rows are unchanged.
#: 0.4.0 (2026-10-09): the spawn anchor (spawn-anchor-0.2.0) is on for both
#: sides: an unwitnessed slot holds the disc round its side's pre-round area.
SLOT_STATE_VERSION = "slot-state-0.4.0"
#: The enemy binding's own stamp.
ENEMY_BINDING_VERSION = "enemy-binding-0.1.0"
#: The binding law's own stamp (unchanged from the prototype).
ENTITY_BINDING_VERSION = "entity-binding-0.1.1"
#: The prototype versions this module reproduces.
PORTED_FROM = {"entity_state": "entity-state-0.3.0", "entity_binding": ENTITY_BINDING_VERSION}

#: Entity kinds. Only `player` is built.
KIND_PLAYER = "player"

#: Belief kinds, as stored (u1).
CLOSED, FIT, CROWD, REACH, UNANCHORED, FIT_UNNAMED, SPAWN = 0, 1, 2, 3, 4, 5, 6
KINDS = {CLOSED: "closed", FIT: "fit", CROWD: "crowd", REACH: "reach", UNANCHORED: "unanchored",
         FIT_UNNAMED: "fit_unnamed", SPAWN: "spawn"}
#: Post-round binding routes (u1): only the first two are witnessed.
HOW_SELF, HOW_NAMED_RING, HOW_NAMED_STACK, HOW_CONTINUITY = 1, 2, 3, 4
WITNESSED = (HOW_SELF, HOW_NAMED_RING)
#: A named entity whose slot another holds over more than this share of its
#: frames binds by continuity instead.
CONFLICT_SHARE = 0.2

# --- the causal binding (entity-binding-0.1.1), unchanged
W_ID = 1.0
LLR_CLIP = 4.0
DECAY = 0.955
SWAP_MIN = 6.0
CHAIN_MIN = 3.0
K_RELOC = 3.0
K_NP = 3.0
NP_BONUS = {"off_map": 50.0, "ability_glyph": 50.0, "not_a_teammate": 4.0, "ping": 6.0,
            "spike": 6.0}
NP_REASONS = ("off_map", "ability_glyph", "not_a_teammate", "ping", "spike")
NP_BUCKETS = NP_REASONS + ("duplicate", "unexplained")
HOW_SPECTATE, HOW_ASSIGNED, HOW_ASSIGNED_SPECTATED = 6, 7, 8
WITNESS_SELF, WITNESS_SPECTATE, WITNESS_PORTRAIT, WITNESS_EXCLUSIVE = 1, 2, 3, 4
WITNESS_PORTRAIT_UNCONFIRMED = 5
ANCHORING = (WITNESS_SELF, WITNESS_SPECTATE, WITNESS_PORTRAIT)

#: QUESTION_ACCEPTANCE section 4's per-entity-frame read and rate codes (u1).
READS = ("full", "local", "cheap_check", "skipped", "audit")
RATES = ("coarse", "fine")

SPECTATE_RESTS_ON = ("tray_kit spectating witness (kit_agents_at lookahead 0 ms; each span's agent "
                     "pooled over the whole span: a post-round tray_kit verdict)")


# --- ability children and effects: the declaration (docs/ABILITY_ENTITIES.md step 1)

#: Entity kinds the child owner holds beside `player` (section 2.2).
KIND_ABILITY = "ability"
KIND_EFFECT = "effect"
#: A slot's side relative to the player: the player's own slot, a teammate's,
#: an enemy's. A side is a property of the slot; which witnesses reach it is a
#: property of each channel (`CHANNELS` `sides`).
SIDE_SELF, SIDE_TEAM, SIDE_ENEMY = "self", "team", "enemy"
SIDES = (SIDE_SELF, SIDE_TEAM, SIDE_ENEMY)
#: The sides whose ability children and effects `build_abilities` builds:
#: every slot, in one pass (docs/ABILITY_ENTITIES.md step 3, which took in
#: step 4 on 2026-10-09).
ABILITY_SIDES_BUILT = ("self", "team", "enemy")
#: The ownership entries this module answers for ability entities.
ABILITY_ENTRIES = ("ability-child", "ability-effect", "ability-owner")

#: ability-channels-0.1.0 (2026-10-09): section 2.3's witness table, as code.
#: 0.2.0 (2026-10-09): every row names the `sides` it can observe and the
#: `opens_sides` it opens a child on; the assist icon opens on every side.
#: A change to any row restamps this table, never the player slots.
#: 0.3.0 (2026-10-09): a glyph track ends its node only where the team's
#: stored vision covers its place (`team_vision`), on every side.
ABILITY_CHANNELS_VERSION = "ability-channels-0.3.0"

#: What an input may open: any child, a child of the player's team only, or
#: either only where no child of that ability is live.
OPENS = ("any", "team", "if_none_live", "team_if_none_live")

#: Every input the child owner may read, one row per witness (section 2.3),
#: and what it may do:
#:
#: - `opens`: one of `OPENS`, or None where it never opens a child;
#: - `sides`: the slot sides (`SIDES`) the witness can observe, from the
#:   cited evidence, never by analogy; None where unknown, with
#:   `sides_reason`;
#: - `opens_sides`: the sides on which it opens a child; on the others it
#:   joins only;
#: - `joins`: may join a live child of the same instance;
#: - `ends`: the end it may witness, or None;
#: - `kind`: what names the child's kind, or None;
#: - `agent_claim`: how the row bears on the child's agent (a channel's claim
#:   re-keyed to the child, or `depends_on` another key's verdict), or None;
#: - `position`: what places the child, or None;
#: - `effect`: the effect it witnesses (section 2.5), or None.
#: - `parent`: the entity key the row binds the new node to, a revisable
#:   binding: a player slot, an ability instance or a spawned object.
#:
#: `owners` are the ownership entries whose verdicts the row reads; each
#: declares `feeds` with the row's `feeds`. `readers` are the entries beneath
#: them. `streams` are the stored streams the row rests on. A row with
#: `wired` False names a witness no code reads yet: no owner, no stream.
#: Ability entities form a tree (player, 2026-10-09): slot -> ability
#: instance -> spawned objects, nested to any depth -> effects. Each node is
#: its own entity with its own lifecycle (Cypher's tracking dart is a child
#: of his Spycam and ends at his death while the camera persists), and its
#: parent may be any entity key, rebound when the evidence moves.
#: Each ability's own facts decide what a witness means for it; no row
#: extends one ability's mechanics to another
#: [domain:abilities/ability-rules-are-unique].
CHANNELS: tuple[dict, ...] = (
    {"witness": "player_tray_cast", "parent": "the self slot",
     "wired": True, "sides": ("self",), "opens_sides": ("self",),
     "sides_reason": "the tray draws the player's own kit while the player lives "
                     "[domain:hud/tray-after-player-death]",
     "owners": ("ability-cast", "ability-state"), "readers": ("tray-drop",),
     "streams": ("tray_drop", "ability_state"), "feeds": ("ability-child",),
     "opens": "any", "joins": False, "ends": None,
     "kind": "the tray slot of the player's kit",
     "agent_claim": "depends_on the self slot's verdict",
     "position": "the self slot's belief at the cast", "effect": None},
    {"witness": "spectated_kit_drop", "parent": "the spectated teammate's slot",
     "wired": True, "sides": ("team",), "opens_sides": ("team",),
     "sides_reason": "after the player's death the tray draws the spectated teammate's kit "
                     "[domain:hud/tray-after-player-death]",
     "owners": ("tray-kit",), "readers": ("tray-icon", "tray-drop"),
     "streams": ("tray_kit", "tray_kit_identity", "tray_drop"), "feeds": ("ability-child",),
     "opens": "any", "joins": False, "ends": None,
     "kind": "the spectated kit's slot", "agent_claim": "channel tray_kit",
     "position": "the spectated slot's belief", "effect": None},
    {"witness": "ult_line", "parent": "the caster's slot, by the template's class and side",
     "wired": True, "sides": ("self", "team", "enemy"), "opens_sides": ("self", "team", "enemy"),
     "sides_reason": "every player hears every ult line, the variant naming the side "
                     "[domain:abilities/ult-lines-heard-by-both-teams]",
     "owners": ("ult-cast",), "readers": ("ult-line",),
     "streams": ("ult_cast", "ult_cast_identity", "ult_line"), "feeds": ("ability-child",),
     "opens": "any", "joins": True, "ends": None,
     "kind": "the template's class", "agent_claim": "channel ult_line",
     "position": None, "effect": None},
    {"witness": "smoke_track", "parent": "the caster's slot, by the smoke rule",
     "wired": True, "sides": ("self", "team"), "opens_sides": ("team",),
     "sides_reason": "only the player's team's smokes are drawn "
                     "[domain:abilities/enemy-smokes-not-on-minimap]; on the self side the "
                     "kit's cast transition opens the child and the smoke joins it",
     "owners": ("minimap-smoke", "smoke-owner"), "readers": ("minimap-dark",),
     "streams": ("smoke", "smoke_owner", "smoke_owner_identity", "minimap_dark"),
     "feeds": ("ability-child",),
     "opens": "team", "joins": True, "ends": "an observed end",
     "kind": "the smoke rule's agent and slot", "agent_claim": "channel smoke_owner",
     "position": "the disc", "effect": None},
    {"witness": "glyph_track", "parent": "unknown at the open; the caster's slot or a spawned object, bound later",
     "wired": True, "sides": ("self", "team", "enemy"), "opens_sides": ("team", "enemy"),
     "sides_reason": "every drawing ability draws for both sides, an enemy's inside the "
                     "team's vision [domain:minimap/ability-drawings-both-sides]; on the self "
                     "side the kit's cast transition opens the child and the glyph joins it",
     "owners": ("ability-glyph-name", "ability-disc-track"),
     "readers": ("ability-icon", "ability-glyph"),
     "streams": ("ability_glyph_name", "ability_glyph_identity", "ability_disc_track",
                 "ability_icon", "ability_glyph", "team_vision"),
     "feeds": ("ability-child",),
     "opens": "any", "joins": True,
     "ends": "the verify's loss where the disc would show, while the team's vision "
             "(`team_vision`) covers its place [domain:abilities/drawing-loss-in-view-ends-object]",
     "kind": "the verdict key", "agent_claim": "channel minimap_glyph",
     "position": "the track", "effect": None},
    {"witness": "shape_fit", "parent": "unknown at the open; bound later",
     "wired": True, "sides": ("self",), "opens_sides": (),
     "sides_reason": "`ability_shape` fits only after the player's own casts; the 2 Hz "
                     "`ability_fit` rows no owner reads yet",
     "owners": ("ability-shape", "ability-gate"), "readers": ("ability-candidates",),
     "streams": ("ability_fit", "ability_wall", "ability_shape", "ability_gate"),
     "feeds": ("ability-child",),
     "opens": "any", "joins": True, "ends": "the fit's absence where it would show",
     "kind": "the descriptor", "agent_claim": None,
     "position": "the fit", "effect": None},
    {"witness": "dead_clove_circle", "parent": "the dead Clove's slot",
     "wired": True, "sides": ("self", "team"), "opens_sides": (),
     "sides_reason": "it names a smoke, and only the team's smokes are drawn "
                     "[domain:abilities/enemy-smokes-not-on-minimap]",
     "owners": ("clove-circle",), "readers": (),
     "streams": ("clove_circle",), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": None,
     "kind": None, "agent_claim": "channel dead_clove_circle (through smoke-owner)",
     "position": "the circle's centre bounds the disc", "effect": None},
    {"witness": "killfeed_ability_kill", "parent": "the killer's live node of that ability, else the killer's slot",
     "wired": True, "sides": ("self", "team", "enemy"), "opens_sides": ("self", "team", "enemy"),
     "sides_reason": "an ability kill draws the ability's icon in the entry's weapon slot "
                     "[domain:killfeed/ability-kill-icon], and the death owner's stored "
                     "verdicts hold both sides' kills",
     "owners": ("killfeed-weapon",), "readers": ("killfeed-weapon-descriptor",),
     "streams": ("killfeed_weapon", "death"), "feeds": ("ability-child", "ability-effect"),
     "opens": "if_none_live", "joins": True, "ends": None,
     "kind": "the weapon verdict", "agent_claim": "depends_on the killer verdict",
     "position": None, "effect": "a kill, on the victim"},
    {"witness": "assist_icon", "parent": "the assister's live node of that ability, else the assister's slot",
     "wired": True, "sides": ("self", "team", "enemy"), "opens_sides": ("self", "team", "enemy"),
     "sides_reason": "an assisted kill draws the assist panel, the assister's ability icon "
                     "beside the portrait [domain:killfeed/assist-panel], whichever side kills",
     "owners": ("kill-assists",), "readers": ("killfeed-assist-panel",),
     "streams": ("assist", "killfeed_assist"), "feeds": ("ability-child", "ability-effect"),
     "opens": "if_none_live", "joins": True, "ends": None,
     "kind": "the icon's ability", "agent_claim": "depends_on the assister verdict",
     "position": None, "effect": "an assist, on the victim"},
    {"witness": "own_ability_audio", "parent": "the self slot",
     "wired": True, "sides": ("self",), "opens_sides": (),
     "sides_reason": "the audio owner scores the player's own tray drops only",
     "owners": ("ability-audio",), "readers": (), "streams": (), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": None,
     "kind": "the scored slot", "agent_claim": None, "position": None, "effect": None},
    {"witness": "device_destroyed", "parent": "the destroyed node's own parent, unchanged",
     "wired": False, "sides": None, "opens_sides": (),
     "sides_reason": "unknown: which sides hear a destruction sound or announcement "
                     "[domain:abilities/device-destroyed-sounds] is unmeasured",
     "owners": (), "readers": (), "streams": (), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": "destroyed by the enemy",
     "kind": None, "agent_claim": None, "position": None, "effect": None},
    {"witness": "others_ability_audio", "parent": "unknown; bound later",
     "wired": False, "sides": None, "opens_sides": (),
     "sides_reason": "unknown: `prototypes/audio_others.py` does not tell the caster's side",
     "owners": (), "readers": (), "streams": (), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": None,
     "kind": "the class", "agent_claim": None, "position": None, "effect": None},
)


def channel(witness: str) -> dict:
    """The `CHANNELS` row of one witness."""
    return next(r for r in CHANNELS if r["witness"] == witness)


def opens_on(witness: str, side: str | None) -> bool:
    """Whether `witness` opens a child on a slot of `side` (`CHANNELS`)."""
    return side in (channel(witness).get("opens_sides") or ())


#: The lanes ability entities reach consumers through (section 2.9): the
#: child owner's, and the kit owner's. Any other ability lane is ABILITY debt.
ABILITY_LANES = {"ability": "children and effects (`ability-child`, `ability-effect`) of "
                            "every slot, one builder (step 3)",
                 "ability_tray": "the kit (`ability-state`)"}


# --- ability children and effects: every slot, one builder (docs/ABILITY_ENTITIES.md step 3)

#: ability-child-0.1.0 (2026-10-09): the player's own instances.
#: 0.2.0 (2026-10-09): every slot of both teams in one pass (step 3 with step
#: 4); spawned objects are nodes of their own under their instance or parent
#: object (the mechanics sheet's spawn tree); glyph tracks re-acquired at the
#: same place join one child; a team-owned glyph's verify loss ends its child.
#: A change to a child rule restamps this stamp alone, never the player slots.
#: 0.2.1 (2026-10-09, post hoc, withdrawn): a drawing's loss ended a node only
#: where its own facts gave no lifetime, a rule over every ability drawn from
#: two.
#: 0.3.0 (2026-10-09): a drawing's loss ends a node only where its own sheet
#: row answers `drawing_loss` yes (`_drawing_lost`); an unanswered cell ends
#: nothing and stores `no-fact`. Claims come from `CHANNELS`, and a
#: `possible` node publishes none.
#: 0.4.0 (2026-10-09): the player's rule replaces the per-object
#: `drawing_loss` question [domain:abilities/drawing-loss-in-view-ends-object]:
#: a lost drawing of any side ends its node where the team's vision covered
#: its place through the loss (`team_vision.StoredVision`), leaves it open
#: with `drawing_lost_out_of_view` where it did not, and stores the unknown
#: view's reason otherwise (`_drawing_lost`).
#: 0.4.1 (2026-10-09): a moving drawing's place is carried along its last
#: velocity through the loss (`MOVING_PX`, `team_vision.point_at`).
ABILITY_CHILD_VERSION = "ability-child-0.4.1"
#: ability-effect-0.1.0 (2026-10-09): the player's ability kills and assists,
#: and any effect an ability's own `effects` fact names.
#: 0.2.0 (2026-10-09): every slot's; a spawned object's own effects hang
#: under the object.
ABILITY_EFFECT_VERSION = "ability-effect-0.2.0"
#: The streams this owner writes (`reticle ability-children SESSION --write`).
ABILITY_STREAMS = ("ability_child", "ability_effect", "ability_child_identity")
#: A child's end basis. An observed end outranks a predicted one; among the
#: predicted, the earliest fires.
END_BASES = ("observed_end", "owner_death", "lifetime_expiry", "round_barrier")
#: The kit owner's transitions this owner reads (`adjudication.ability_state`).
KIT_CAST, KIT_DEATH, KIT_REVIVE = "cast", "owner_death", "revive"
#: The kit's owner_death transition and the death owner's verdict are two
#: readings of one death, paired nearest first within this many ms. The bound
#: is the one `replay_abilities` pairs owner_death verdicts with replay deaths
#: by; it is not a measured lag.
DEATH_PAIR_MS = 3000.0
X_SLOT = "X"
#: A glyph track born after an earlier track of the same owner and ability
#: was last fixed, within this many widget px of that last fix, is the same
#: object found again (the disc verify loses a drawing under a passing icon).
#: Four times the icon fit error (`minimap.FIT_ERR_PX`); chosen, not fitted.
GLYPH_SAME_PLACE_PX = 4.0 * FIT_ERR_PX
#: The glyph reader's step: a track's object appeared at most one step before
#: its birth (`ability_glyph`, 2 Hz).
GLYPH_STEP_MS = 500.0
#: A disc track end that is the drawing's loss where the disc would show
#: (`adjudication.ability.disc_tracks`); any other end is an unread frame.
GLYPH_LOST = "verify_lost"
#: The team relative to the player each slot side belongs to.
TEAM_OF = {SIDE_SELF: "ally", SIDE_TEAM: "ally", SIDE_ENEMY: "enemy"}
#: The other team.
OTHER_TEAM = {"ally": "enemy", "enemy": "ally"}
#: The node types of the tree: an ability instance (the cast) and a spawned
#: object under it.
NODE_INSTANCE, NODE_OBJECT = "instance", "object"
#: The sheet columns an object node's lifecycle reads (`ability_objects`).
OBJECT_COLUMNS = ("parent", "lifecycle_class", "lifetime_s", "owner_death", "ends_on", "effects",
                  "destructible")
#: The rule a lost drawing reads, the player's (2026-10-09).
DRAWING_LOSS_RULE = "abilities/drawing-loss-in-view-ends-object"
#: Why a lost drawing out of view leaves its node open.
DRAWING_LOST_OUT_OF_VIEW = "drawing_lost_out_of_view"
#: The disc round a drawing's last fix the vision is read over: the fit
#: error (`minimap.FIT_ERR_PX`).
VIEW_DISC_PX = FIT_ERR_PX
#: A drawing moves where its last two fixes, at most one second apart, lie
#: farther apart than twice the fit error; a still one's fixes jitter less.
MOVING_PX = 2.0 * FIT_ERR_PX


def _subject_key(subject: str) -> tuple[str, str]:
    who, _, what = str(subject).partition(":")
    return agent_key(who), agent_key(what)


def _structured(found: dict, name: str, tag: str):
    """(value, fact key, reason) of one lifecycle field over the facts of one
    subject (`found`: fact key -> value). Two facts that disagree refuse."""
    vals = {k: v for k, v in found.items() if v}
    if not vals:
        return None, None, f"no-fact:{tag}:{name}"
    if len({json.dumps(v, sort_keys=True, default=list) for v in vals.values()}) > 1:
        return None, None, f"conflicting-facts:{','.join(sorted(vals))}:{name}"
    k = sorted(vals)[0]
    return vals[k], k, None


def _fact_seconds(facts: dict, ref: str) -> float | None:
    """The number `<domain>/<id>#<group>.<field>` names, in seconds."""
    key, _, path = ref.partition("#")
    f = facts.get(key)
    v = (f.values or {}) if f is not None else {}
    for part in path.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def ability_lifecycle(agent: str, ability: str | None, slot: str, facts: dict | None = None) -> dict:
    """One ability's lifecycle from its own facts, never by analogy
    [domain:abilities/ability-rules-are-unique]; every field it cannot read
    carries a `no-fact:<agent>:<slot>:<field>` reason and no default.

    - `lifecycle_class`, `owner_death`, `effects`, `ends_on`: the structured
      fields of the lifecycle facts whose subject is `<agent>:<ability>`
      (`domain.LIFECYCLE_KEYS`, written by the mechanics sheet). A deployed
      ability with no owner-death field is disabled at its owner's death
      [domain:abilities/deployed-ability-ends]. A `*-persists-after-death`
      fact with no structured field says so in prose only, and stays a
      reason (`unstructured-fact`), never a parsed value.
    - lifetime: game files first [domain:abilities/game-files-outrank-player-quantities]:
      a lifecycle fact's `lifetime` reference, else the one `life` value of
      the ability's game-data fact (two or more refuse as ambiguous), else the
      kit owner's `-duration` fact (`ability_state.duration_facts`).
    - `ends_on`: the facts' set, else `round_end` plus the causes a read
      lifetime or owner-death fact implies; round end is always a member
      [domain:rounds/no-ability-crosses-round-barrier].
    - `states`: `entity_contract.ability_states`, the facts' phases.
    """
    from . import domain as dm
    from .adjudication.ability_state import duration_facts
    from .entity_contract import ability_states
    facts = dm.load() if facts is None else facts
    if agent is None:
        return _unknown_lifecycle("unbound: no caster")
    a, ab = agent_key(agent), agent_key(ability)
    tag = f"{a}:{slot}"
    life = {k: f for k, f in facts.items() if f.kind == "lifecycle" and ":" in f.subject
            and _subject_key(f.subject) == (a, ab)} if ab else {}
    out: dict = {"subject": f"{str(agent).lower()}:{str(ability).lower()}" if ability else None,
                 "facts": sorted(life)}
    for name in ("lifecycle_class", "owner_death"):
        v, k, why = _structured({key: getattr(f, name) for key, f in life.items()}, name, tag)
        out.update({name: v, f"{name}_fact": k, f"{name}_reason": why})
    if out["owner_death"] is None and out["lifecycle_class"] == "deployed":
        out.update(owner_death="disabled", owner_death_fact="abilities/deployed-ability-ends",
                   owner_death_reason=None)
    if out["owner_death"] is None and out["owner_death_reason"].startswith("no-fact"):
        prose = sorted(k for k in life if k.endswith("-persists-after-death"))
        if prose:
            out["owner_death_reason"] = f"unstructured-fact:{prose[0]}:owner_death"
    eff, eff_k, eff_why = _structured({k: tuple(f.effects) for k, f in life.items()}, "effects", tag)
    out.update(effects=list(eff or ()), effects_fact=eff_k, effects_reason=eff_why)

    # Lifetime, game files first.
    lt, lt_fact, lt_why, alts = None, None, None, {}
    refs = {k: f.lifetime for k, f in life.items() if f.lifetime}
    if len(set(refs.values())) > 1:
        lt_why = f"conflicting-facts:{','.join(sorted(refs))}:lifetime"
    elif refs:
        k, ref = sorted(refs.items())[0]
        if ref == "none":
            lt_why = f"fact-names-no-lifetime:{k}"
        elif ref == "player":
            lt_why = f"player-lifetime-unread:{k}"
        else:
            s = _fact_seconds(facts, ref)
            lt, lt_fact = (s * 1000.0, ref) if s is not None else (None, None)
            lt_why = None if s is not None else f"unresolved-lifetime:{ref}"
    if lt is None and lt_why is None and ab:
        gd = sorted(k for k, f in facts.items() if f.domain == "game_data"
                    and f.id.endswith("-game-data") and ":" in f.subject
                    and _subject_key(f.subject) == (a, ab))
        for k in gd:
            vals = {f"{k}#life.{n}": v for n, v in ((facts[k].values or {}).get("life") or {}).items()
                    if n.endswith("_s") and isinstance(v, (int, float))}
            if len(vals) == 1:
                lt_fact, s = next(iter(vals.items()))
                lt = float(s) * 1000.0
                break
            if len(vals) > 1:
                alts = {r: float(v) for r, v in vals.items()}
                lt_why = f"ambiguous-fact:{k}:life"
                break
    if lt is None and lt_why is None and ab:
        d = duration_facts(facts).get((a, ab))
        if d:
            lt, lt_fact = d["duration_ms"], d["fact"]
    if lt is None and lt_why is None:
        lt_why = f"no-fact:{tag}:duration"
    out.update(lifetime_ms=lt, lifetime_fact=lt_fact, lifetime_reason=lt_why,
               lifetime_alternatives_s=alts or None)

    ends, ends_k, ends_why = _structured({k: tuple(f.ends_on) for k, f in life.items()},
                                         "ends_on", tag)
    if ends is not None:
        out.update(ends_on=sorted(set(ends) | {"round_end"}), ends_on_fact=ends_k,
                   ends_on_reason=None)
    else:
        implied = {"round_end"} | ({"lifetime"} if lt is not None else set()) | (
            {"owner_death"} if out["owner_death"] == "destroyed" else set())
        out.update(ends_on=sorted(implied), ends_on_fact=None, ends_on_reason=ends_why)
    phases, phase_why = ability_states(str(agent), str(ability), slot)
    out.update(states=sorted(phases), phase_reason=phase_why)
    return out


def _unknown_lifecycle(why: str) -> dict:
    """The lifecycle of a node whose ability is unknown: every field a reason."""
    return {"subject": None, "facts": [], "lifecycle_class": None, "lifecycle_class_fact": None,
            "lifecycle_class_reason": why, "owner_death": None, "owner_death_fact": None,
            "owner_death_reason": why, "effects": [], "effects_fact": None, "effects_reason": why,
            "lifetime_ms": None, "lifetime_fact": None, "lifetime_reason": why,
            "lifetime_alternatives_s": None, "ends_on": ["round_end"], "ends_on_fact": None,
            "ends_on_reason": why, "states": [], "phase_reason": why}


# --- the spawn tree: each ability's spawned objects, from the mechanics sheet

def _sheet_value(row: dict, column: str, answers: dict, key_of) -> tuple:
    """(value, source, reason) of one sheet cell: the player's answer where one
    is sure, else a pre-filled cell its sources confirm, else a `no-fact`
    reason. Game files outrank the player on quantities, so a lifetime answer
    is one of the game data's values or `none` (the sheet's own rule)."""
    a = answers.get(key_of(row, column))
    if a is not None and not a.get("unsure") and a.get("answer") is not None:
        return a["answer"], f"player answer {a['key']}", None
    cell = (row.get("cells") or {}).get(column) or {}
    if cell.get("status") == "confirm" and cell.get("value") is not None:
        src = (cell.get("sources") or [cell.get("basis") or "pre-fill"])[0]
        return cell["value"], f"sheet pre-fill: {src}", None
    tag = f"{agent_key(row['agent'])}:{row['slot']}:{row.get('part')}"
    if cell.get("status") == "conflict":
        return None, None, f"conflicting-sources:{tag}:{column}"
    return None, None, f"no-fact:{tag}:{column}"


def ability_objects(store_root: Path = DEFAULT_STORE) -> dict:
    """The spawn tree of every ability that spawns more than one world object
    (the mechanics sheet's object rows, `mechanics_sheet.build_rows`): per
    (agent key, slot), each object's stem, subject, the sheet's cells for
    `OBJECT_COLUMNS` (a sure player answer outranks the pre-fill; an open
    cell is `no-fact`), and the minimap textures the game data says it draws.
    An engine helper the player cannot see (`n/a`) is no node. Returns
    {"tree": ..., "stamp": ...}, or an empty tree with the reason the sheet
    is unread."""
    from . import mechanics_sheet as ms
    root = Path(store_root)
    try:
        rows = ms.load_prefill_rows(root)
    except SystemExit as e:
        return {"tree": {}, "stamp": {"version": None, "reason": f"sheet_unread: {e}"}}
    answers = ms.load_sheet_answers(root)
    tree: dict = defaultdict(list)
    for r in rows:
        if ms.is_agent_row(r) or not r.get("part"):
            continue
        if all((r["cells"].get(c) or {}).get("status") in ms.NOT_ASKED for c in OBJECT_COLUMNS):
            continue
        cells = {c: _sheet_value(r, c, answers, ms.cell_key) for c in OBJECT_COLUMNS}
        tex = ((r["cells"].get("minimap_drawing") or {}).get("evidence") or {}).get("textures") or {}
        tree[(agent_key(r["agent"]), r["slot"])].append({
            "part": r["part"], "subject": r["subject"], "agent": r["agent"], "slot": r["slot"],
            "ability": r["ability"], "cells": cells,
            "textures": sorted(t for t, v in tex.items() if (v or {}).get("owner") == r["part"])})
    p = root / ms.ANSWERS
    return {"tree": dict(tree), "stamp": {
        "version": ms.VERSION, "answers_sha": (ms._file_sha(p) if p.is_file() else "no_rows"),
        "reason": None}}


def object_lifecycle(obj: dict, facts: dict) -> dict:
    """A spawned object's lifecycle from its own facts and its own sheet row,
    never its parent's or a sibling's [domain:abilities/ability-rules-are-unique]:
    a lifecycle fact whose subject is the object's (`<agent>:<ability>/<object>`)
    first, then the sheet's cell (`ability_objects`); every field neither gives
    is a `no-fact` reason."""
    subj = obj["subject"].lower()
    life = {k: f for k, f in facts.items() if f.kind == "lifecycle"
            and str(f.subject).lower() == subj}
    tag = f"{agent_key(obj['agent'])}:{obj['slot']}:{obj['part']}"
    out: dict = {"subject": subj, "facts": sorted(life)}

    def pick(name, fact_attr, cell):
        v, k, why = _structured({key: getattr(f, fact_attr) for key, f in life.items()}, name, tag)
        if v is not None:
            return v, k, None
        cv, src, cwhy = obj["cells"][cell]
        return cv, src, cwhy

    for name in ("lifecycle_class", "owner_death"):
        v, k, why = pick(name, name, name)
        out.update({name: v, f"{name}_fact": k, f"{name}_reason": why})
    eff, eff_k, eff_why = pick("effects", "effects", "effects")
    kinds = [e.get("effect") if isinstance(e, dict) else str(e) for e in (eff or ())]
    out.update(effects=[k for k in kinds if k], effects_fact=eff_k, effects_reason=eff_why)
    refs = {k: f.lifetime for k, f in life.items() if f.lifetime}
    lt, lt_fact, lt_why = None, None, None
    if refs:
        k, ref = sorted(refs.items())[0]
        s = _fact_seconds(facts, ref) if ref not in ("none", "player") else None
        lt, lt_fact = (s * 1000.0, ref) if s is not None else (None, None)
        lt_why = None if s is not None else f"fact-names-no-lifetime:{k}"
    else:
        v, src, why = obj["cells"]["lifetime_s"]
        if isinstance(v, dict) and v.get("s") is not None:
            lt, lt_fact = float(v["s"]) * 1000.0, v.get("ref") or src
        elif isinstance(v, dict) and v.get("player_s") is not None:
            lt, lt_fact = float(v["player_s"]) * 1000.0, src
        elif v == "none":
            lt_why = f"sheet-names-no-lifetime:{src}"
        else:
            lt_why = why or f"no-fact:{tag}:lifetime_s"
    out.update(lifetime_ms=lt, lifetime_fact=lt_fact, lifetime_reason=lt_why,
               lifetime_alternatives_s=None)
    ends, ends_k, ends_why = pick("ends_on", "ends_on", "ends_on")
    if ends and ends_why is None:
        out.update(ends_on=sorted(set(ends) | {"round_end"}), ends_on_fact=ends_k, ends_on_reason=None)
    else:
        out.update(ends_on=["round_end"], ends_on_fact=None,
                   ends_on_reason=ends_why or f"no-fact:{tag}:ends_on")
    out.update(states=[], phase_reason=f"no-fact:{tag}:states")
    return out


def _evidence(stream: str, eid: str, version, t_ms, **extra) -> dict:
    return {"stream": stream, "id": eid, "version": version,
            "t_ms": None if t_ms is None else float(t_ms), **extra}


def _child_round(t_ms: float, rounds: list[dict]) -> dict | None:
    from .rounds import round_containing
    return round_containing(float(t_ms), rounds)


def _barrier(r: dict) -> float:
    """The round's barrier: its close, the next buy phase
    [domain:rounds/post-round-period]."""
    return float(r["t_close_ms"] if r.get("t_close_ms") is not None else r["t_end_ms"])


def _live(c: dict, t: float) -> bool:
    """Whether a child may be live at `t`: inside its open-to-predicted-end span."""
    return c["open"]["lo_ms"] <= t <= c["predicted_end"]["hi_ms"]


def _nearest_child(cands: list[dict], t: float) -> dict | None:
    return min(cands, key=lambda c: (abs(t - c["open"]["hi_ms"]), c["open"]["hi_ms"])) if cands else None


def _stored_vision(root: Path, sid: str):
    """The team's stored vision, asked through its owner (ownership entry
    `team-vision`, `team_vision.StoredVision`)."""
    from .team_vision import StoredVision
    return StoredVision.from_store(root, sid)


def _drawing_lost(c: dict, g: dict, xy: tuple | None, vision, gver, v: tuple | None = None) -> None:
    """A drawing's verify loss (`GLYPH_LOST`) under the player's rule
    [domain:abilities/drawing-loss-in-view-ends-object]: the loss falls after
    the track's last fix and by the next glyph step, so the team's vision
    owner (`team_vision.StoredVision.in_view`) is asked whether the last
    fix's place, carried along `v` where the drawing moves, lay in view
    through that window. In view, the loss is the
    node's observed end; out of view, the node stays open with
    `DRAWING_LOST_OUT_OF_VIEW`; unknown stores the view's reason and ends
    nothing. Replay truth never reaches this rule."""
    from .team_vision import IN_VIEW, OUT_OF_VIEW
    e = g["last_ms"]
    ev = _evidence("ability_glyph_name", g["entity_id"], gver, e)
    x, y = xy if xy is not None else (None, None)
    view = vision.in_view(x, y, e, e + GLYPH_STEP_MS, VIEW_DISC_PX, v)
    st = view["status"]
    c["drawing_loss"] = {
        "t_ms": e, "rule": DRAWING_LOSS_RULE, "view": view,
        "ends": st == IN_VIEW,
        "reason": (None if st == IN_VIEW else DRAWING_LOST_OUT_OF_VIEW if st == OUT_OF_VIEW
                   else f"view_unknown: {view['reason']}"),
        "evidence": [ev, {"stream": "team_vision", "id": None,
                          "version": view["team_vision_version"], "t_ms": e}]}
    if st == IN_VIEW:
        c["observed_end"] = {"lo_ms": e, "hi_ms": e + GLYPH_STEP_MS, "basis": "observed_end",
                             "evidence": ev}


def _okey(owner: dict | None):
    return owner["key"] if owner else None


class _Children:
    """The session's children while they are built: opened per round, joined
    only among the same round's children of the same owner slot and ability
    slot (ROUNDSCOPE: nothing crosses a round). `owner` is the slot record
    (`_slot_table`), or None where no witness binds a caster."""

    def __init__(self, sid: str, rounds: list[dict], facts: dict):
        self.sid, self.rounds, self.facts = sid, rounds, facts
        self.items: list[dict] = []
        self.candidates: list[dict] = []
        self._life: dict = {}
        #: (round, owner key, slot) -> that round's children, in open order.
        self._by: dict = defaultdict(list)

    def of(self, rno, owner, slot: str | None) -> list[dict]:
        """The children of (`owner`, `slot`) opened in round `rno`."""
        return self._by.get((rno, _okey(owner), slot), [])

    def in_round(self, rno) -> list[dict]:
        """Every child opened in round `rno`."""
        return [c for (r, _o, _s), cs in self._by.items() if r == rno for c in cs]

    def lifecycle(self, c: dict) -> dict:
        key = (c["agent"], c["ability"], c["slot"])
        if key not in self._life:
            self._life[key] = (ability_lifecycle(c["agent"], c["ability"], c["slot"], self.facts)
                               if c["agent"] and c["slot"] else
                               _unknown_lifecycle(c.get("owner_reason") or "unbound"))
        return self._life[key]

    def open(self, owner: dict | None, slot: str | None, lo: float, hi: float, basis: str, by: str,
             ev: dict, owner_reason: str | None = None, side: str | None = None) -> dict | None:
        r = _child_round(hi, self.rounds)
        if r is None:
            self.candidates.append({"witness": by, "slot": slot, "owner": _okey(owner), "t_ms": hi,
                                    "reason": "outside_every_round", "evidence": [ev]})
            return None
        rno, bar = int(r["round_no"]), _barrier(r)
        lo = max(float(lo), float(r["t_start_ms"]))
        c = {"round": rno, "barrier_ms": bar, "slot": slot, "owner": owner,
             "owner_reason": owner_reason, "side": owner["side"] if owner else side,
             "agent": owner["agent"] if owner else None,
             "ability": (owner["kit"].get(slot) if owner and slot else None),
             "node": NODE_INSTANCE, "open": {"lo_ms": lo, "hi_ms": float(hi), "basis": basis},
             "opened_by": by, "witnesses": [{"witness": by, **ev}], "observed_end": None,
             "owner_death": None, "position": None, "over_bound": False, "surprises": [],
             "glyphs": [], "depends": []}
        self.predict(c)
        self.items.append(c)
        self._by[(rno, _okey(owner), slot)].append(c)
        return c

    def predict(self, c: dict) -> None:
        """The child's predicted end from its open and its lifetime fact, never
        past its round's barrier."""
        life, bar = (c["life"] if "life" in c else self.lifecycle(c)), c["barrier_ms"]
        lo, hi = c["open"]["lo_ms"], c["open"]["hi_ms"]
        if life["lifetime_ms"] is not None:
            c["predicted_end"] = {"lo_ms": min(lo + life["lifetime_ms"], bar),
                                  "hi_ms": min(hi + life["lifetime_ms"], bar),
                                  "basis": ("lifetime_expiry" if hi + life["lifetime_ms"] < bar
                                            else "round_barrier")}
        else:
            c["predicted_end"] = {"lo_ms": bar, "hi_ms": bar, "basis": "round_barrier"}

    def candidate(self, by, owner, slot, t, ev, reason) -> None:
        r = _child_round(t, self.rounds)
        self.candidates.append({"witness": by, "slot": slot, "owner": _okey(owner), "t_ms": float(t),
                                "round": None if r is None else int(r["round_no"]),
                                "reason": reason if r is not None else "outside_every_round",
                                "evidence": [ev]})

    def join(self, owner, slot: str | None, t: float, gate, by: str, ev: dict, used: set,
             candidate_reason: str = "no_live_child", keep: bool = True) -> dict | None:
        """Join a witness at `t` to the nearest live child of (`owner`, `slot`)
        in its round that `gate` admits and no witness of this kind joined;
        else keep it as a candidate (`keep`), never a new child."""
        r = _child_round(t, self.rounds)
        rno = None if r is None else int(r["round_no"])
        pool = self.of(rno, owner, slot)
        got = _nearest_child([c for c in pool if id(c) not in used and gate(c, t)], t)
        if got is None:
            if not keep:
                return None
            # A drawing after its child's predicted end is a stored surprise
            # on that child, never a new child.
            before = [c for c in pool if c["open"]["hi_ms"] <= t]
            prior = max(before, key=lambda c: c["open"]["hi_ms"]) if before else None
            if prior is not None and r is not None and _live(prior, t):
                candidate_reason = "its_child_already_joined_by_this_witness"
            elif prior is not None and r is not None:
                prior["surprises"].append(f"{by} at {t:.0f} ms, after the predicted end "
                                          f"({prior['predicted_end']['basis']})")
                candidate_reason = "after_the_predicted_end_of_its_child"
            self.candidates.append({"witness": by, "slot": slot, "owner": _okey(owner),
                                    "t_ms": float(t), "round": rno,
                                    "reason": candidate_reason if r is not None else
                                    "outside_every_round", "evidence": [ev]})
            return None
        used.add(id(got))
        got["witnesses"].append({"witness": by, **ev})
        return got


def _stored(st: Store, stream: str, sid: str) -> list[dict]:
    return st.read_events(stream, sid) if st.events_path(stream, sid).is_file() else []


def _identity_status(st: Store, sid: str, stream: str = "death_identity") -> dict:
    """identity ref -> (status, agent) from a stored identity stream's
    `identity_distribution` events (the arbiter's verdicts), with the sides of
    the slots each verdict depends on."""
    out = {}
    for r in _stored(st, stream, sid):
        if r.get("event_kind") != "identity_distribution":
            continue
        dist = (r.get("identity_distribution") or {}).get("distribution") or {}
        top = max(sorted(dist), key=lambda a: dist[a]) if dist else None
        out[r["entity_id"]] = ((r.get("metadata") or {}).get("status"), top)
    return out


def _identity_sides(st: Store, sid: str, stream: str) -> dict:
    """identity ref -> the teams of the lineup slots the verdict depends on."""
    out = {}
    for r in _stored(st, stream, sid):
        if r.get("event_kind") == "identity_distribution":
            deps = (r.get("metadata") or {}).get("depends_on") or []
            out[r["entity_id"]] = sorted({d.split(":")[1] for d in deps if d.count(":") >= 3})
    return out


def _kit_of(agent: str | None, store_root: Path) -> dict:
    """{slot: ability name} of an agent (`lineup.abilities_for`), {} where the
    reference is unread."""
    if not agent:
        return {}
    from .lineup import abilities_for
    try:
        return dict(abilities_for(agent, store_root))
    except (OSError, ValueError, KeyError):
        return {}


def _slot_table(L: dict, self_kit: dict, store_root: Path) -> list[dict]:
    """Every player slot of both teams with its side (`SIDES`), its agent as
    the lineup arbiter's verdict on its key (or None with the verdict's
    status), its identity ref and its kit: the player's from the kit owner,
    every other slot's from the official reference by its agent."""
    pk = int(L["player_slot"])
    out = []
    for k, s in enumerate(L["slots"]):
        side = SIDE_SELF if k == pk else SIDE_TEAM
        ok = s.get("status") == "resolved" and s.get("agent")
        out.append({"key": s["key"], "side": side, "team": "ally",
                    "agent": s["agent"] if ok else None, "status": s.get("status"),
                    "ref": f"identity:{s['key']}",
                    "kit": self_kit if side == SIDE_SELF else (_kit_of(s["agent"], store_root) if ok else {})})
    for s in L.get("enemy_slots") or []:
        ok = s.get("status") == "resolved" and s.get("agent")
        out.append({"key": s["key"], "side": SIDE_ENEMY, "team": "enemy",
                    "agent": s["agent"] if ok else None, "status": s.get("status"),
                    "ref": f"identity:{s['key']}",
                    "kit": _kit_of(s["agent"], store_root) if ok else {}})
    return out


def _find_slot(slots: list[dict], team: str | None, agent: str | None) -> dict | None:
    """The slot of `team` the arbiter names `agent`; a team fields each agent
    once [domain:rounds/agent-uniqueness]."""
    if not agent or team is None:
        return None
    return next((s for s in slots if s["team"] == team and s["agent"]
                 and agent_key(s["agent"]) == agent_key(agent)), None)


def _teams_fielding(slots: list[dict], agent: str | None) -> list[str]:
    return sorted({s["team"] for s in slots if s["agent"] and agent
                   and agent_key(s["agent"]) == agent_key(agent)})


def _slot_by_name(s: dict) -> dict:
    return {agent_key(v): k for k, v in (s.get("kit") or {}).items() if v}


def build_abilities(sid: str, store_root: Path = DEFAULT_STORE, facts: dict | None = None) -> dict:
    """Every slot's ability children, their spawned objects and their effects,
    from stored witnesses only, in one pass (docs/ABILITY_ENTITIES.md step 3).
    Decodes nothing.

    The slots: the ten lineup slots (`_slot_table`), each with its side
    (self, team, enemy), the arbiter's verdict on its key and its kit. Each
    witness channel reaches the sides `CHANNELS` names (`sides`) and opens a
    child on `opens_sides`; on any other side it only joins. Every binding to
    a slot rests on that slot's verdict: a child's `depends_on` lists the
    slot's identity ref, plus the channel verdict that named the caster.

    Openers: the kit owner's cast transitions (self), a spectated teammate's
    tray drops (team), ult lines (every side; an own line joins an X child
    inside the agent's cast window, `ult_cast.cast_window`), a dead Clove's
    smokes (self, `ability_timeline.dead_ruse_casts`), the team's named smokes
    (one smoke, one cast), glyph tracks (team and enemy), and ability kills
    and assists where no child of that ability is live (every side). Joiners:
    `ability_shape` fits by their cast, own audio, the player's smokes, glyph
    tracks of a live child (a later track joins only where it re-acquires
    the child's drawing, within `GLYPH_SAME_PLACE_PX` of its last fix), and
    Clove's circle. A smoke the arbiter does not name opens a child with no
    caster: its parent is null with the smoke owner's reason. A glyph whose
    agent both teams field and whose verdict names no team does the same.

    Spawned objects: under each instance of an ability that spawns several
    objects, one node per object of the spawn tree (`ability_objects`), its
    `parent` the instance or its parent object. A node a glyph track draws
    (the game data's texture of that object) is `witnessed`, opened at the
    track; any other is `possible`, opened somewhere inside its parent's
    life. Each node's lifecycle is its own (`object_lifecycle`).

    Ends: each node's lifetime and `ends_on` from its own facts; an observed
    end (a smoke's, or the verify loss of a team-owned glyph, which always
    shows [domain:minimap/ability-drawings-both-sides]) outranks a predicted
    end; an enemy glyph's loss may be the team's vision, so it ends nothing;
    the round barrier ends every node [domain:rounds/no-ability-crosses-round-barrier].
    Owner death: the player's from the kit's owner_death transition paired to
    the death verdict, every other slot's from the death owner's resolved
    verdict on its agent; each node then disables, ends or persists as its own
    facts say. The charge bound: opens per round and slot beyond the kit's
    `max_charges` are flagged `over_bound`, never dropped.

    No name is decided here: a child's agent is the arbiter's verdict on its
    owner slot, cited through `depends_on`.
    """
    from .adjudication.smoke_owner import CAST_WINDOW_S, SMOKE_ABILITY
    from .adjudication.ult_cast import OWN_WINDOW_S, cast_window, in_window
    from . import domain as dm
    root = Path(store_root)
    st = Store(root)
    facts = dm.load() if facts is None else facts
    man = st.read_manifest(sid)
    date = man["ingested_at"][:10]
    table = st.read_rounds(sid, date)
    rounds = sorted(table.to_pylist() if table is not None else [],
                    key=lambda r: float(r["t_start_ms"]))
    if not rounds:
        return {"refused": "no_rounds"}
    L = lineup_slots(sid, root)
    if "refused" in L:
        return {"refused": L["refused"]}
    if L["player_slot"] is None:
        return {"refused": "no_player_slot"}
    me = L["slots"][int(L["player_slot"])]
    if me["status"] != "resolved" or not me["agent"]:
        return {"refused": f"player_agent_unresolved: {me['reason'] or me['status']}"}
    agent, self_key = me["agent"], me["key"]
    state = _stored(st, "ability_state", sid)
    kit_head = next((r for r in state if r.get("kind") == "coverage"), None)
    if kit_head is None:
        return {"refused": "no_ability_state"}
    kit = dict(kit_head.get("kit") or {})
    params = kit_head.get("parameters") or {}
    kver = kit_head.get("ability_state_version")
    slots = _slot_table(L, kit, root)
    mine_slot = next(s for s in slots if s["key"] == self_key)
    verdicts = sorted((r for r in state if r.get("kind") == "verdict"),
                      key=lambda r: (float(r["t_ms"]), str(r.get("slot"))))
    B = _Children(sid, rounds, facts)
    stamps = {"ability_state": kver}
    refused: Counter = Counter()

    # Openers: the kit owner's cast transitions (self).
    by_cast: dict[tuple[str, float], dict] = {}
    for v in verdicts:
        if v.get("transition") != KIT_CAST:
            continue
        t = float(v["t_ms"])
        lo = float((v.get("before") or {}).get("t_ms", t))
        ev = _evidence("ability_state", f"{sid}:{v['slot']}:{int(round(t))}:cast", kver, t,
                       claims=list(v.get("claims") or []), agreed=list(v.get("agreed") or []))
        c = B.open(mine_slot, v["slot"], lo, t, "the kit's cast transition: between the tray "
                   "samples before and at the drop", "player_tray_cast", ev)
        if c is None:
            continue
        by_cast[(v["slot"], round(t, 1))] = c
        if "audio" in (v.get("agreed") or []):
            aud = [x for x in v.get("claims") or [] if str(x).endswith(":audio")]
            c["witnesses"].append({"witness": "own_ability_audio",
                                   **_evidence("ability_state", aud[0] if aud else f"{sid}:{v['slot']}:"
                                               f"{int(round(t))}:audio", kver, t)})

    # Openers: a spectated teammate's tray drops (team). The drop's kit is the
    # span's agent, and the sample before the drop lies in the same span.
    spans = [r for r in _stored(st, "tray_kit", sid) if r.get("kind") == "span" and not r.get("own")
             and r.get("identity_status") == "resolved" and r.get("agent")]
    stamps["tray_kit"] = next((r.get("tray_kit_version") for r in spans), None)
    drops = [r for r in _stored(st, "tray_drop", sid) if r.get("kind") == "drop"]
    stamps["tray_drop"] = next((r.get("tray_version") for r in drops), None)
    span_t = np.asarray([float(s["t_first_ms"]) for s in spans], float)
    order = np.argsort(span_t, kind="stable")
    spans = [spans[i] for i in order]
    span_t = span_t[order]
    for d in sorted(drops, key=lambda r: float(r["t_ms"])):
        if not spans or d.get("suspect") or d.get("forced") or d.get("across_gap") \
                or d.get("phase") != "round_live":
            continue
        t = float(d["t_ms"])
        k = int(np.searchsorted(span_t, t, side="right")) - 1
        if k < 0:
            continue
        sp = spans[k]
        step = float(d.get("step_s") or 0.5) * 1000.0
        if not (sp["t_first_ms"] <= t - step and t <= sp["t_last_ms"]):
            continue
        if not d.get("kit_agent") or agent_key(d["kit_agent"]) != agent_key(sp["agent"]):
            refused["spectated_drop_kit_disagrees"] += 1
            continue
        owner = _find_slot(slots, "ally", sp["agent"])
        # after the player's death the tray draws a spectated teammate's kit
        # [domain:hud/tray-after-player-death]: a drop binds to a team slot only
        if owner is None or owner["side"] != SIDE_TEAM:
            refused["spectated_drop_agent_not_a_teammate"] += 1
            continue
        ev = _evidence("tray_drop", f"{sid}:tray_drop:{int(round(t))}:{d['slot']}", stamps["tray_drop"], t,
                       span=sp["entity_id"])
        c = B.open(owner, d["slot"], t - step, t, "a spectated kit's drop: between the tray samples "
                   "before and at the drop", "spectated_kit_drop", ev)
        if c is not None:
            c["depends"].append(f"identity:{sp['entity_id']}")

    # Ult lines: the player's own join an X child inside the agent's cast
    # window, else open one; every other line opens or joins its caster's.
    ult = _stored(st, "ult_cast", sid)
    uver = ult[0].get("ult_cast_version") if ult else None
    stamps["ult_cast"] = uver
    uids = _identity_status(st, sid, "ult_cast_identity")
    used: set = set()
    for r in sorted((r for r in ult if r.get("kind") == "cast"), key=lambda r: float(r["t_ms"])):
        t = float(r["t_ms"])
        ev = _evidence("ult_cast", r["entity_id"], uver, t, template=r.get("template"))
        if r.get("player_cast"):
            owner, win = mine_slot, cast_window(agent)
        else:
            team = r.get("side") if r.get("side") in ("ally", "enemy") else None
            ust, utop = uids.get(f"identity:{r['entity_id']}", (r.get("identity_status"), r.get("agent")))
            if ust != "resolved" or not utop or team is None:
                refused["ult_line_caster_unresolved"] += 1
                continue
            owner = _find_slot(slots, team, utop)
            if owner is None:
                refused["ult_line_caster_not_in_lineup"] += 1
                continue
            if owner["side"] == SIDE_SELF:
                refused["ult_line_self_not_player_cast"] += 1
                continue
            win = cast_window(owner["agent"])
        r_ = _child_round(t, rounds)
        rno = None if r_ is None else int(r_["round_no"])
        near = [c for c in B.of(rno, owner, X_SLOT)
                if id(c) not in used and in_window(t, c["open"]["hi_ms"], win)]
        got = _nearest_child(near, t)
        if got is not None:
            used.add(id(got))
            got["witnesses"].append({"witness": "ult_line", **ev})
            if owner is not mine_slot:
                got["depends"].append(f"identity:{r['entity_id']}")
            if t < got["open"]["hi_ms"]:
                # The line came first: the cast lies before its onset, within
                # the window `ult_cast` binds an own line to its drop by.
                got["open"] = {"lo_ms": max(float(r_["t_start_ms"]), t - OWN_WINDOW_S * 1000.0),
                               "hi_ms": t, "basis": "an ult line heard before the X drop: "
                               "the cast lies within ult_cast.OWN_WINDOW_S before the onset"}
                B.predict(got)
            continue
        c = B.open(owner, X_SLOT, t - win[1] * 1000.0, t - win[0] * 1000.0,
                   f"an ult line's onset minus the agent's cast window {list(win)} s "
                   "(ult_cast.cast_window)", "ult_line", ev)
        if c is not None:
            used.add(id(c))
            if owner is not mine_slot:
                c["depends"].append(f"identity:{r['entity_id']}")

    # A dead Clove's smokes: the charge ledger of `dead_ruse_casts` (self).
    owners = _stored(st, "smoke_owner", sid)
    sover = owners[0].get("smoke_owner_version") if owners else None
    stamps["smoke_owner"] = sover
    dead_ruse = None
    from .ability_timeline import (DEAD_RUSE, dead_ruse_applies, dead_ruse_casts, held_at_deaths,
                                   ruse_parameters, stored_gate_inputs)
    if dead_ruse_applies(agent)[0] == "applies" and owners:
        gate, gstamps = stored_gate_inputs(st, sid, date, rounds, agent)
        dead_ruse = dead_ruse_casts(agent, gate["player_deaths_ms"], gate["revives_ms"], rounds,
                                    owners, held_at_deaths(state), ruse_parameters(facts))
        stamps["dead_ruse_gate"] = {k: v for k, v in gstamps.items()
                                    if k not in ("ult_cast", "ult_cast_reason")}
    dead_smokes: set = set()
    for d in (dead_ruse or {}).get("rows", []):
        sm = d["rests_on"][0]
        dead_smokes.add(sm)
        ev = _evidence("smoke_owner", sm, sover, d["t_ms"], basis=d["basis"],
                       death_ms=d["death_ms"])
        c = B.open(mine_slot, DEAD_RUSE[1], max(d["death_ms"], d.get("earliest_ms") or d["death_ms"]),
                   d["t_ms"], "a dead Clove's smoke birth: the cast lies between the death (or the "
                   "charge's earliest time) and the birth", "dead_clove_smoke", ev)
        if c is not None:
            c["dead_ruse"] = {"basis": d["basis"], "death_ms": d["death_ms"],
                              "window_end_ms": d["window_end_ms"]}
            c["observed_end_from"] = sm
            if not d["player_cast"]:
                c["over_bound"] = True
                c["surprises"].append(f"beyond_charge_bound: {d['basis']}")

    # Joiners: shape fits keyed to their cast (self).
    shapes = _stored(st, "ability_shape", sid)
    shver = shapes[0].get("ability_shape_version") if shapes else None
    stamps["ability_shape"] = shver
    for r in shapes:
        if r.get("kind") != "shape" or not r.get("found"):
            continue
        c = by_cast.get((r.get("slot"), round(float(r["cast_t_ms"]), 1)))
        ev = _evidence("ability_shape", f"{sid}:shape:{r['slot']}:{int(round(float(r['t_ms'])))}",
                       shver, r["t_ms"], shape=r.get("shape"))
        if c is None:
            B.candidates.append({"witness": "shape_fit", "slot": r.get("slot"), "owner": self_key,
                                 "t_ms": float(r["t_ms"]), "round": None,
                                 "reason": "its cast opened no child", "evidence": [ev]})
            continue
        c["witnesses"].append({"witness": "shape_fit", **ev})
        if c["position"] is None:
            if r.get("cx") is not None:
                x, y = float(r["cx"]), float(r["cy"])
            else:
                x, y = (float(r["x0"]) + float(r["x1"])) / 2.0, (float(r["y0"]) + float(r["y1"])) / 2.0
            c["position"] = {"x": round(x, 1), "y": round(y, 1), "t_ms": float(r["t_ms"]),
                             "source": "ability_shape"}

    # Smoke tracks (self and team): one cast, one smoke.
    smoke_rows = sorted((r for r in owners if r.get("kind") == "smoke_owner"
                         and r["entity_id"] not in dead_smokes), key=lambda r: float(r["first_ms"]))
    by_owner: dict = defaultdict(list)
    for r in smoke_rows:
        # The smoke owner's stored verdict names the caster (step 2's rule).
        owner = _find_slot(slots, "ally", r.get("agent"))
        by_owner[_okey(owner)].append((r, owner))
    for okey, items in by_owner.items():
        owner = items[0][1]
        if owner is None:
            # An unnamed smoke: a child of the team with no caster.
            for r, _o in items:
                t = float(r["first_ms"])
                ev = _evidence("smoke_owner", r["entity_id"], sover, t, last_ms=r.get("last_ms"),
                               end_status=r.get("end_status"), rules=r.get("rules"),
                               candidates=list(r.get("candidates") or []))
                c = B.open(None, None, t - GLYPH_STEP_MS, t, "a team smoke's birth: its cast lies "
                           "before the first drawn sample", "smoke_track", ev,
                           owner_reason=f"smoke_owner: {r.get('identity_status')} "
                           f"({r.get('reason')})", side=SIDE_TEAM)
                if c is not None:
                    c["observed_end_from"] = r["entity_id"]
                    c["alternatives"] = list(r.get("candidates") or [])
            continue
        s_agent = owner["agent"]
        smoke_slot = SMOKE_ABILITY.get(s_agent, (None,))[0]
        if smoke_slot is None:
            refused["smoke_agent_has_no_smoke_slot"] += len(items)
            continue
        swin = CAST_WINDOW_S.get(s_agent)
        in_swin = (lambda c, t, w=swin: w[0] <= (t - c["open"]["hi_ms"]) / 1000.0 <= w[1])
        rows_ = [r for r, _o in items]
        # With a cast window, one cast draws one smoke for that agent
        # [domain:abilities/smoke-bulk-confirm]: a child two tracks' windows
        # hold, or a track two children's, binds neither (the rule `cast_links` held).
        shared: set = set()
        if swin:
            holds = {r["entity_id"]: [id(c) for c in B.items if c["owner"] is owner
                                      and c["slot"] == smoke_slot and in_swin(c, float(r["first_ms"]))]
                     for r in rows_}
            per_child = Counter(x for v in holds.values() for x in v)
            shared = {e for e, v in holds.items() if len(v) > 1 or any(per_child[x] > 1 for x in v)}
        used = set()
        for r in rows_:
            t = float(r["first_ms"])
            ev = _evidence("smoke_owner", r["entity_id"], sover, t, last_ms=r.get("last_ms"),
                           end_status=r.get("end_status"), rules=r.get("rules"))
            if r["entity_id"] in shared:
                B.candidate("smoke_track", owner, smoke_slot, t, ev, "cast_shared_by_tracks")
                continue
            gate = in_swin if swin else (lambda c, t: _live(c, t))
            opens = opens_on("smoke_track", owner["side"])
            c = B.join(owner, smoke_slot, t, gate, "smoke_track", ev, used, keep=not opens)
            if c is None and opens:
                c = B.open(owner, smoke_slot, t - GLYPH_STEP_MS, t, "a team smoke's birth: its cast "
                           "lies before the first drawn sample", "smoke_track", ev)
                if c is not None:
                    used.add(id(c))
            if c is None:
                continue
            c["observed_end_from"] = r["entity_id"]
            if owner["side"] != SIDE_SELF:
                c["depends"].append(f"identity:{r['entity_id']}")
            if "dead_clove_circle" in (r.get("rules") or []):
                c["witnesses"].append({"witness": "dead_clove_circle",
                                       **_evidence("clove_circle", r["entity_id"], None, t,
                                                   rests_on=list(r.get("rests_on") or []))})
    for c in B.items:
        sm = c.get("observed_end_from")
        row = next((r for r in owners if r.get("entity_id") == sm), None) if sm else None
        if row is None:
            continue
        if c["position"] is None and row.get("cx") is not None:
            c["position"] = {"x": round(float(row["cx"]), 1), "y": round(float(row["cy"]), 1),
                             "t_ms": float(row["first_ms"]), "source": "smoke"}
        if row.get("end_status") == "observed" and row.get("last_ms") is not None:
            e = float(row["last_ms"])
            c["observed_end"] = {"lo_ms": e, "hi_ms": e, "basis": "observed_end",
                                 "evidence": _evidence("smoke_owner", sm, sover, e)}

    # Glyph tracks (every side): the verdict's agent and slot; its team from
    # the lineup, or from the slots the arbiter's verdict depends on where
    # both teams field the agent.
    glyphs = _stored(st, "ability_glyph_name", sid)
    gver = glyphs[0].get("ability_glyph_name_version") if glyphs else None
    stamps["ability_glyph_name"] = gver
    discs = {r["entity_id"]: r for r in _stored(st, "ability_disc_track", sid) if r.get("kind") == "track"}
    stamps["ability_disc_track"] = next((r.get("ability_disc_track_version") for r in discs.values()), None)
    gids = _identity_status(st, sid, "ability_glyph_identity")
    gsides = _identity_sides(st, sid, "ability_glyph_identity")

    def last_fix(eid):
        f = (discs.get(eid) or {}).get("fix") or {}
        xs, ys = f.get("cx") or [], f.get("cy") or []
        ok = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        return ok[-1] if ok else None

    def last_motion(eid):
        """The track's velocity (px per ms) over its last two fixes, or None
        where it holds still (`MOVING_PX`) or has fewer than two fixes."""
        f = (discs.get(eid) or {}).get("fix") or {}
        pts = [(t, x, y) for t, x, y in zip(f.get("t_ms") or [], f.get("cx") or [], f.get("cy") or [])
               if x is not None and y is not None]
        if len(pts) < 2:
            return None
        (t0, x0, y0), (t1, x1, y1) = pts[-2], pts[-1]
        if not 0 < t1 - t0 <= 1000.0 or math.hypot(x1 - x0, y1 - y0) <= MOVING_PX:
            return None
        return (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)

    def birth_xy(eid):
        b = (discs.get(eid) or {}).get("birth_xy")
        return tuple(b) if b else None

    def glyph_gate(c, t, eid):
        if not _live(c, t):
            return False
        if not c["glyphs"]:
            return True
        prev = c["glyphs"][-1]
        if t <= float(prev["last_ms"]):
            return False
        a, b = last_fix(prev["entity_id"]), birth_xy(eid)
        return a is not None and b is not None and math.hypot(a[0] - b[0], a[1] - b[1]) <= GLYPH_SAME_PLACE_PX

    for r in sorted((r for r in glyphs if r.get("kind") == "verdict" and r.get("reason") is None
                     and (r.get("ability") or {}).get("agent")), key=lambda r: float(r["birth_ms"])):
        t = float(r["birth_ms"])
        ab = r["ability"]
        ref = f"identity:{r['entity_id']}"
        gst, gtop = gids.get(ref, (None, None))
        teams = _teams_fielding(slots, ab["agent"])
        if gst == "resolved" and gtop and agent_key(gtop) != agent_key(ab["agent"]):
            refused["glyph_verdict_names_another_agent"] += 1
            continue
        # A verdict the arbiter abstains on joins a live child and opens none.
        named = gst == "resolved"
        if len(teams) > 1:
            dep = [s for s in gsides.get(ref, []) if s in ("ally", "enemy")]
            teams = dep if len(dep) == 1 else teams
        ev = _evidence("ability_glyph_name", r["entity_id"], gver, t, key=ab.get("key"),
                       texture=(r.get("state") or {}).get("texture"))
        glyph = {"entity_id": r["entity_id"], "birth_ms": t, "last_ms": float(r.get("last_ms") or t),
                 "end": (discs.get(r["entity_id"]) or {}).get("end"),
                 "texture": (r.get("state") or {}).get("texture")}
        if len(teams) != 1:
            if not teams:
                refused["glyph_agent_not_in_lineup"] += 1
                continue
            if not named:
                refused["glyph_unnamed_and_unbound"] += 1
                continue
            c = B.open(None, None, t - GLYPH_STEP_MS, t, "a glyph track's birth: its object "
                       "appeared within one glyph step before", "glyph_track", ev,
                       owner_reason=f"both teams field {ab['agent']} and the verdict names no team")
            if c is not None:
                c["glyphs"].append(glyph)
                c["alternatives"] = [ab.get("key")]
            continue
        owner = _find_slot(slots, teams[0], ab["agent"])
        opens = named and opens_on("glyph_track", owner["side"])
        c = B.join(owner, ab.get("slot"), t, lambda c, t, e=r["entity_id"]: glyph_gate(c, t, e),
                   "glyph_track", ev, set(), keep=not opens)
        if c is None and opens:
            c = B.open(owner, ab.get("slot"), t - GLYPH_STEP_MS, t, "a glyph track's birth: its "
                       "object appeared within one glyph step before", "glyph_track", ev)
        if c is None:
            # the self side's children open on the kit's cast transition and a
            # glyph only joins them; a team or enemy drawing opens its own
            # [domain:minimap/ability-drawings-both-sides] (`CHANNELS` glyph_track)
            if owner["side"] != SIDE_SELF and not opens:
                refused["glyph_unnamed_no_live_child"] += 1
            continue
        c["glyphs"].append(glyph)
        if owner["side"] != SIDE_SELF:
            c["depends"].append(ref)
        if c["position"] is None and birth_xy(r["entity_id"]):
            bx, by_ = birth_xy(r["entity_id"])
            c["position"] = {"x": round(float(bx), 1), "y": round(float(by_), 1), "t_ms": t,
                             "source": "ability_disc_track"}
    # A drawing's loss, every side: the team's vision at its last place
    # decides whether it ends the node
    # [domain:abilities/drawing-loss-in-view-ends-object]; a drawing outside
    # the team's vision says nothing [domain:minimap/vision-gate].
    tree_doc = ability_objects(root)
    vision = _stored_vision(root, sid)
    stamps["team_vision"] = vision.version
    for c in B.items:
        g = c["glyphs"][-1] if c["glyphs"] else None
        if g and c["observed_end"] is None and g["end"] == GLYPH_LOST:
            _drawing_lost(c, g, last_fix(g["entity_id"]), vision, gver, last_motion(g["entity_id"]))

    # Effects: ability kills and assists (every side).
    deaths = [r for r in _stored(st, "death", sid) if r.get("kind") == "death_verdict"]
    dver = deaths[0].get("death_adjudication_version") if deaths else None
    stamps["death"] = dver
    ids = _identity_status(st, sid)
    effects: list[dict] = []

    def source_for(owner, slot, t, by, ev):
        r_ = _child_round(t, rounds)
        rno = None if r_ is None else int(r_["round_no"])
        live = [c for c in B.of(rno, owner, slot) if c["open"]["hi_ms"] <= t and _live(c, t)]
        got = max(live, key=lambda c: c["open"]["hi_ms"]) if live else None
        if got is not None:
            got["witnesses"].append({"witness": by, **ev})
            return got, None
        if r_ is None:
            return None, "outside_every_round"
        if not opens_on(by, owner["side"]):
            return None, "channel_opens_no_child_on_this_side"
        c = B.open(owner, slot, float(r_["t_start_ms"]), t, f"no live child of the ability: the {by} "
                   "opens one (if_none_live); its cast lies between the round's start and the kill",
                   by, ev)
        return c, None

    for d in sorted(deaths, key=lambda r: float(r["t_ms"])):
        w = d.get("weapon_evidence") or {}
        if w.get("category") != "ability" or d.get("side") not in ("ally", "enemy"):
            continue
        if d.get("is_revive") or d.get("same_side"):
            refused["kill_same_side_or_revive"] += 1
            continue
        kref = f"identity:{d['death_id']}:killer"
        kst, ktop = ids.get(kref, (None, None))
        if not (kst == "resolved" and ktop and d.get("killer") and agent_key(ktop) == agent_key(d["killer"])):
            refused["kill_killer_not_resolved"] += 1
            continue
        owner = _find_slot(slots, OTHER_TEAM[d["side"]], d["killer"])
        if owner is None:
            refused["kill_killer_not_in_lineup"] += 1
            continue
        slot = _slot_by_name(owner).get(agent_key(w.get("name") or d.get("weapon")))
        if slot is None:
            refused["kill_weapon_not_in_kit"] += 1
            continue
        t = float(d["t_ms"])
        ev = _evidence("death", d["death_id"], dver, t, weapon=w.get("name"))
        src, why = source_for(owner, slot, t, "killfeed_ability_kill", ev)
        if src is None:
            refused[f"kill_{why}"] += 1
            continue
        effects.append({"effect": "kill", "source": src, "t_ms": t, "slot": slot,
                        "target": {"entity_id": d["death_id"], "agent": d.get("victim"),
                                   "ref": f"identity:{d['death_id']}"},
                        "depends_on": [kref], "evidence": [ev]})
    assists = _stored(st, "assist", sid)
    aver = next((r.get("assist_adjudication_version") for r in assists
                 if r.get("assist_adjudication_version")), None)
    stamps["assist"] = aver
    for a in sorted((r for r in assists if r.get("kind") == "assist_verdict"),
                    key=lambda r: float(r["t_ms"])):
        if a.get("killer_side") not in ("ally", "enemy"):
            continue
        for s in a.get("assisters") or []:
            ident = s.get("identity") or {}
            if ident.get("status") != "resolved" or not s.get("agent"):
                continue
            owner = _find_slot(slots, a["killer_side"], s["agent"])
            if owner is None:
                refused["assist_assister_not_in_lineup"] += 1
                continue
            if s.get("icon_status") != "read" or s.get("icon") in (None, "none") \
                    or s.get("icon_agent") != s["agent"]:
                refused["assist_no_ability_icon"] += 1
                continue
            slot = _slot_by_name(owner).get(agent_key(s["icon"]))
            if slot is None:
                refused["assist_icon_not_in_kit"] += 1
                continue
            t = float(a["t_ms"])
            ev = _evidence("assist", s["entity_id"], aver, t, icon=s["icon"])
            src, why = source_for(owner, slot, t, "assist_icon", ev)
            if src is None:
                refused[f"assist_{why}"] += 1
                continue
            effects.append({"effect": "assist", "source": src, "t_ms": t, "slot": slot,
                            "target": {"entity_id": a["death_id"], "agent": a.get("victim"),
                                       "ref": f"identity:{a['death_id']}"},
                            "depends_on": [f"identity:{s['entity_id']}"], "evidence": [ev]})

    # Owner deaths: the player's from the kit's owner_death transitions paired
    # to the death owner's verdict; every other slot's from that verdict.
    deaths_of: dict = defaultdict(list)
    own_deaths = sorted({float(v["t_ms"]) for v in verdicts if v.get("transition") == KIT_DEATH})
    mine_d = sorted((d for d in deaths if d.get("victim") == agent and d.get("side") == "ally"
                     and not d.get("is_revive")), key=lambda d: float(d["t_ms"]))
    mine_t = np.asarray([float(d["t_ms"]) for d in mine_d], float)
    for td in own_deaths:
        lo = int(np.searchsorted(mine_t, td - DEATH_PAIR_MS, side="left"))
        hi = int(np.searchsorted(mine_t, td + DEATH_PAIR_MS, side="right"))
        near = mine_d[lo:hi]
        dd = min(near, key=lambda d: abs(float(d["t_ms"]) - td)) if near else None
        deaths_of[self_key].append({
            "t_ms": td, "death_id": dd["death_id"] if dd else None,
            "death_reason": None if dd else f"no death verdict within {DEATH_PAIR_MS:.0f} ms",
            "evidence": _evidence("ability_state", f"{sid}:{int(round(td))}:owner_death", kver, td)})
    for d in sorted(deaths, key=lambda d: float(d["t_ms"])):
        if d.get("is_revive") or d.get("side") not in ("ally", "enemy") or not d.get("victim"):
            continue
        vst, vtop = ids.get(f"identity:{d['death_id']}", (None, None))
        if vst != "resolved" or not vtop or agent_key(vtop) != agent_key(d["victim"]):
            continue
        owner = _find_slot(slots, d["side"], d["victim"])
        if owner is None or owner["side"] == SIDE_SELF:
            continue
        deaths_of[owner["key"]].append({
            "t_ms": float(d["t_ms"]), "death_id": d["death_id"], "death_reason": None,
            "evidence": _evidence("death", d["death_id"], dver, float(d["t_ms"]))})

    def apply_deaths(nodes, life_of):
        for c in nodes:
            okey = _okey(c["owner"])
            for death in deaths_of.get(okey, []):
                td = death["t_ms"]
                r_ = _child_round(td, rounds)
                if r_ is None or int(r_["round_no"]) != c["round"] or c["owner_death"] is not None:
                    continue
                # A possible object may have opened any time in its window, so
                # a death after the window opens reaches it.
                start = c["open"]["lo_ms"] if c.get("exists") == "possible" else c["open"]["hi_ms"]
                if not (start <= td < c["predicted_end"]["hi_ms"]):
                    continue
                life = life_of(c)
                c["owner_death"] = {**death, "rule": life["owner_death"],
                                    "fact": life["owner_death_fact"], "reason": life["owner_death_reason"]}
                if c.get("exists") == "possible" and life["owner_death"] == "destroyed" \
                        and td < c["open"]["hi_ms"]:
                    # Its own facts destroy it at the owner's death: if it
                    # existed past the death, it opened before it.
                    c["open"] = {**c["open"], "hi_ms": td,
                                 "basis": c["open"]["basis"] + "; before the owner's death, which "
                                          "its own facts say destroys it"}
                    B.predict(c)

    instances = list(B.items)
    apply_deaths(instances, B.lifecycle)

    # Spawned objects: one node per object of the spawn tree under each
    # instance; a glyph whose texture the game data gives that object
    # witnesses it.
    tree = tree_doc["tree"]
    objects: list[dict] = []
    for inst in instances:
        if not inst["agent"] or not inst["slot"]:
            continue
        rows_ = tree.get((agent_key(inst["agent"]), inst["slot"])) or []
        by_part = {o["part"]: o for o in rows_}
        made: dict = {}

        def make(o, depth=0):
            if o["part"] in made:
                return made[o["part"]]
            pv, psrc, pwhy = o["cells"]["parent"]
            parent, parent_reason = inst, None
            if isinstance(pv, str) and pv != "ability":
                if pv in by_part and depth < len(by_part):
                    parent = make(by_part[pv], depth + 1)
                else:
                    parent, parent_reason = None, f"parent {pv} is no node of this instance"
            elif pv is None:
                parent, parent_reason = None, pwhy
            anc = parent or inst
            life = object_lifecycle(o, facts)
            tex = set(o["textures"])
            seen = [g for g in inst["glyphs"] if g["texture"] in tex]
            if seen:
                t0 = seen[0]["birth_ms"]
                open_ = {"lo_ms": max(t0 - GLYPH_STEP_MS, anc["open"]["lo_ms"]), "hi_ms": t0,
                         "basis": "a glyph track drawing this object's texture"}
            else:
                open_ = {"lo_ms": anc["open"]["lo_ms"], "hi_ms": anc["predicted_end"]["hi_ms"],
                         "basis": "possible: the spawn tree says its parent can spawn it; no witness "
                                  "reads whether or when this one did, so it lies inside the parent's life"}
            n = {"round": inst["round"], "barrier_ms": inst["barrier_ms"], "slot": inst["slot"],
                 "owner": inst["owner"], "owner_reason": inst["owner_reason"], "side": inst["side"],
                 "agent": inst["agent"], "ability": inst["ability"], "node": NODE_OBJECT,
                 "object": o["part"], "subject": o["subject"], "instance": inst,
                 "parent_node": parent, "parent_reason": parent_reason,
                 "parent_source": psrc, "exists": "witnessed" if seen else "possible",
                 "open": open_, "opened_by": "glyph_track" if seen else "spawn_tree",
                 "witnesses": [{"witness": "glyph_track", **_evidence(
                     "ability_glyph_name", g["entity_id"], gver, g["birth_ms"], texture=g["texture"])}
                     for g in seen],
                 "observed_end": None, "owner_death": None, "position": None, "over_bound": False,
                 "surprises": [], "glyphs": seen, "depends": [], "life": life}
            B.predict(n)
            # an object's drawing loss, read as the instance's above
            if seen and seen[-1]["end"] == GLYPH_LOST:
                _drawing_lost(n, seen[-1], last_fix(seen[-1]["entity_id"]), vision, gver,
                              last_motion(seen[-1]["entity_id"]))
            made[o["part"]] = n
            objects.append(n)
            return n

        for o in rows_:
            make(o)
    apply_deaths(objects, lambda n: n["life"])

    # Ends: observed first, else the earliest predicted cause, never past the barrier.
    def end_of(c, life):
        bar = c["barrier_ms"]
        cands = [c["predicted_end"]]
        od = c["owner_death"]
        if od and od["rule"] == "destroyed":
            cands.append({"lo_ms": od["t_ms"], "hi_ms": od["t_ms"], "basis": "owner_death"})
        end = c["observed_end"] or min(cands, key=lambda e: (e["hi_ms"], END_BASES.index(e["basis"])))
        end = {**end, "lo_ms": min(end["lo_ms"], bar), "hi_ms": min(end["hi_ms"], bar)}
        if end["hi_ms"] < c["open"]["hi_ms"]:
            c["surprises"].append(f"end before open: {end['basis']}")
            end = {**end, "lo_ms": c["open"]["hi_ms"], "hi_ms": c["open"]["hi_ms"]}
        c["end"] = end
        if c["observed_end"] and "lifetime" in life["ends_on"] \
                and c["observed_end"]["hi_ms"] < c["predicted_end"]["lo_ms"] - 1000.0:
            c["surprises"].append("observed end before the lifetime fact's expiry")

    for c in instances:
        end_of(c, B.lifecycle(c))
    for n in objects:
        end_of(n, n["life"])

    # The charge bound, against the kit owner's supply facts (the player's)
    # or the same supply rules over each other slot's kit.
    from .adjudication.ability_state import slot_parameters
    per = defaultdict(list)
    for c in instances:
        if c["owner"] is not None and c["slot"]:
            per[(c["round"], c["owner"]["key"], c["slot"])].append(c)
    pcache: dict = {}
    for (rno, okey, slot), cs in per.items():
        owner = cs[0]["owner"]
        if owner["side"] == SIDE_SELF:
            p = params.get(slot) or {}
        else:
            if okey not in pcache:
                try:
                    pcache[okey] = slot_parameters(owner["agent"], owner["kit"], facts)
                except (OSError, ValueError, KeyError):
                    pcache[okey] = {}
            p = pcache[okey].get(slot) or {}
        n = p.get("max_charges")
        if n is None or p.get("restock_fact") or slot == X_SLOT:
            continue
        for c in sorted(cs, key=lambda c: c["open"]["hi_ms"])[int(n):]:
            c["over_bound"] = True
            c["surprises"].append(f"over_bound: {len(cs)} opens of {slot} in round {rno}, "
                                  f"max_charges {n} ({p.get('max_charges_fact') or p.get('max_charges_source')})")

    # Ids: the round's number and each node's ordinal in the round.
    nodes = sorted(instances + objects, key=lambda c: (
        c["round"], c["open"]["hi_ms"], str(_okey(c["owner"])), str(c["slot"]),
        c["node"] != NODE_INSTANCE, str(c.get("object"))))
    seen = Counter()
    for c in nodes:
        seen[c["round"]] += 1
        c["id"] = f"{sid}:child:R{c['round']}:{seen[c['round']]}"
    common = {"session_id": sid, "ability_child_version": ABILITY_CHILD_VERSION}
    children = []
    for c in nodes:
        life = c["life"] if c["node"] == NODE_OBJECT else B.lifecycle(c)
        od = c["owner"]
        ref = od["ref"] if od else None
        if c["node"] == NODE_INSTANCE:
            parent = od["key"] if od else None
            parent_reason = None if od else f"unbound: {c['owner_reason']}"
        else:
            pn = c["parent_node"]
            parent = pn["id"] if pn is not None else None
            parent_reason = None if pn is not None else f"unbound: {c['parent_reason']}"
        deps = ([ref] if ref else []) + sorted(set(c["depends"]))
        odth = c["owner_death"]
        children.append({
            **common, "kind": "child", "entity_kind": KIND_ABILITY, "child_id": c["id"],
            "node": c["node"], "round": c["round"],
            "slot": c["slot"], "ability": c["ability"],
            "subject": c.get("subject") if c["node"] == NODE_OBJECT else life["subject"],
            "object": c.get("object"), "exists": c.get("exists", "witnessed"),
            "instance": c["instance"]["id"] if c["node"] == NODE_OBJECT else None,
            "agent": c["agent"], "agent_ref": ref, "depends_on": deps,
            "owner_slot": od["key"] if od else None,
            "owner_slot_reason": None if od else f"unbound: {c['owner_reason']}",
            "parent": parent, "parent_reason": parent_reason,
            "parent_source": c.get("parent_source"),
            "slot_side": c["side"], "side": TEAM_OF.get(c["side"]),
            "opened_by": c["opened_by"],
            "open": c["open"], "end": c["end"], "predicted_end": c["predicted_end"],
            "barrier_ms": c["barrier_ms"],
            "witnesses": c["witnesses"], "position": c["position"],
            "position_reason": None if c["position"] else
            "not_read: no fit, disc or glyph track joined; the owner slot's belief at the cast "
            "is not stored",
            "alternatives": c.get("alternatives") or [],
            "disabled": ({"t_ms": odth["t_ms"], "death_id": odth["death_id"], "evidence": odth["evidence"]}
                         if odth and odth["rule"] == "disabled" else None),
            "owner_death": odth,
            "owner_death_reason": ("the owner did not die while it lived" if odth is None
                                   else odth["reason"]),
            "lifecycle": life, "ends_on": life["ends_on"], "ends_on_reason": life["ends_on_reason"],
            "over_bound": c["over_bound"], "surprises": c["surprises"],
            "drawing_loss": c.get("drawing_loss"),
            "dead_ruse": c.get("dead_ruse")})
    candidates = [{**common, "kind": "candidate", **x} for x in B.candidates]
    by_id = {r["child_id"]: r for r in children}
    eff_rows = []
    seen = Counter()
    for e in sorted(effects, key=lambda e: (e["source"]["round"], e["t_ms"])):
        rno = e["source"]["round"]
        seen[rno] += 1
        src = by_id[e["source"]["id"]]
        eff_rows.append({"session_id": sid, "ability_effect_version": ABILITY_EFFECT_VERSION,
                         "kind": "effect", "entity_kind": KIND_EFFECT,
                         "effect_id": f"{sid}:effect:R{rno}:{seen[rno]}",
                         "round": rno, "effect": e["effect"], "source": e["source"]["id"],
                         "slot": e["slot"], "ability": e["source"]["ability"],
                         "subject": src["subject"], "slot_side": src["slot_side"], "side": src["side"],
                         "t_ms": e["t_ms"],
                         "lifetime": {"lo_ms": e["t_ms"], "hi_ms": e["t_ms"],
                                      "basis": f"instant: a {e['effect']} is an instant"},
                         "target": e["target"], "depends_on": e["depends_on"],
                         "evidence": e["evidence"]})
    # Effects a node's own `effects` fact names: predictions from the fact,
    # stored apart from witnessed effects, each under the node that produces it.
    for c in children:
        for spec in c["lifecycle"]["effects"]:
            name, _, targets = str(spec).partition(":")
            rno = c["round"]
            seen[rno] += 1
            tgt = {"entity_id": None, "agent": None, "ref": None,
                   "targets": targets.split("+") if targets else []}
            if not targets:
                tgt["targets_reason"] = f"no-fact:{c['subject']}:effect-targets"
            eff_rows.append({"session_id": sid, "ability_effect_version": ABILITY_EFFECT_VERSION,
                             "kind": "effect", "entity_kind": KIND_EFFECT,
                             "effect_id": f"{sid}:effect:R{rno}:{seen[rno]}",
                             "round": rno, "effect": name, "source": c["child_id"], "slot": c["slot"],
                             "ability": c["ability"], "subject": c["subject"],
                             "slot_side": c["slot_side"], "side": c["side"],
                             "t_ms": c["open"]["hi_ms"],
                             "lifetime": {"lo_ms": c["open"]["lo_ms"], "hi_ms": c["end"]["hi_ms"],
                                          "basis": f"the effects fact {c['lifecycle']['effects_fact']}"},
                             "target": tgt, "predicted": True,
                             "depends_on": [c["agent_ref"]] if c["agent_ref"] else [],
                             "evidence": [{"stream": "domain", "id": c["lifecycle"]["effects_fact"],
                                           "version": "domain", "t_ms": None}]})
    inst_rows = [c for c in children if c["node"] == NODE_INSTANCE]
    obj_rows = [c for c in children if c["node"] == NODE_OBJECT]
    head = {**common, "kind": "coverage", "ability_channels_version": ABILITY_CHANNELS_VERSION,
            "agent": agent, "player_slot": self_key, "agent_ref": f"identity:{self_key}",
            "sides": list(ABILITY_SIDES_BUILT), "kit": kit, "children": len(inst_rows),
            "objects": len(obj_rows), "candidates": len(candidates),
            "by_side": dict(Counter(str(c["slot_side"]) for c in inst_rows)),
            "objects_by_exists": dict(Counter(c["exists"] for c in obj_rows)),
            "by_opener": dict(Counter(c["opened_by"] for c in inst_rows)),
            "by_end": dict(Counter(c["end"]["basis"] for c in inst_rows)),
            "over_bound": sum(c["over_bound"] for c in inst_rows),
            "disabled": sum(c["disabled"] is not None for c in children),
            "unbound": sum(c["owner_slot"] is None for c in inst_rows),
            "refused": dict(refused),
            "candidate_reasons": dict(Counter(f"{x['witness']}:{x['reason']}" for x in candidates)),
            "dead_ruse_reason": None if dead_ruse is None else dead_ruse["reason"],
            "spawn_tree": tree_doc["stamp"],
            # Every lost drawing by the view its place had, and why a view
            # stayed unknown [domain:abilities/drawing-loss-in-view-ends-object].
            "drawing_loss": {
                "rule": DRAWING_LOSS_RULE,
                "by_view": dict(Counter(f"{c['node']}:{c['drawing_loss']['view']['status']}"
                                        for c in children if c.get("drawing_loss"))),
                "unknown_reasons": dict(Counter(
                    str(c["drawing_loss"]["view"]["reason"]).split(":")[0] for c in children
                    if c.get("drawing_loss") and c["drawing_loss"]["view"]["status"] == "unknown"))},
            # The stored inputs `plan` declares are recorded by the writer
            # (`plan.record_inputs`); a dead Clove's gate only where it was read.
            "inputs": {"team_vision": stamps["team_vision"],
                       **({"dead_ruse_gate": stamps["dead_ruse_gate"]}
                          if "dead_ruse_gate" in stamps else {})}}
    ehead = {"session_id": sid, "ability_effect_version": ABILITY_EFFECT_VERSION,
             "kind": "coverage", "agent": agent,
             "effects": len(eff_rows), "by_effect": dict(Counter(e["effect"] for e in eff_rows)),
             "by_side": dict(Counter(str(e["slot_side"]) for e in eff_rows)),
             "refused": {k: v for k, v in refused.items() if k.startswith(("kill_", "assist_"))},
             "inputs": {}}
    return {"session_id": sid, "agent": agent, "child_rows": [head] + children + candidates,
            "effect_rows": [ehead] + eff_rows, "identity_rows": child_identity(sid, children)}


def claim_channel(witness: str) -> str | None:
    """The channel a witness publishes its caster claim on, read from its
    `CHANNELS` row's `agent_claim`: `channel <name>` publishes on that
    channel; `depends_on ...` publishes on the witness's own name, the claim
    resting on the owner slot's verdict; no claim, or no row, publishes none."""
    row = next((r for r in CHANNELS if r["witness"] == witness), None)
    claim = (row or {}).get("agent_claim")
    if not claim:
        return None
    if claim.startswith("channel "):
        return claim.split()[1]
    if claim.startswith("depends_on"):
        return witness
    raise ValueError(f"CHANNELS[{witness}].agent_claim reads neither `channel` nor `depends_on`: {claim}")


def child_claims(children: list[dict]) -> list[dict]:
    """The identity claims this owner [owns:ability-owner] publishes on each
    witnessed node's key. Each witness publishes one claim per channel
    (`claim_channel`), naming the agent of the owner slot it bound the node
    to, with `binding_from` this owner and `depends_on` the owner slot, whose
    verdict the binding rests on. A node with no owner slot, or whose
    witnesses publish no claim, publishes one abstention with its reason. A
    `possible` node publishes nothing: no witness observed it."""
    from .adjudication.identity import identity_claim
    claims = []
    for c in children:
        if c.get("exists", "witnessed") != "witnessed":
            continue
        key = c["child_id"]
        if c["owner_slot"] is None or not c["agent"]:
            claims.append(identity_claim(key, None, channel="ability_child",
                                         reason=c.get("owner_slot_reason") or "unbound",
                                         source_version=ABILITY_CHILD_VERSION))
            continue
        seen = set()
        for w in c["witnesses"]:
            ch = claim_channel(w["witness"])
            if ch is None or ch in seen:
                continue
            seen.add(ch)
            claims.append(identity_claim(
                key, c["agent"], channel=ch, observed_at_ms=w.get("t_ms"),
                source_version=ABILITY_CHILD_VERSION, binding_from="ability_child",
                depends_on=[c["owner_slot"]],
                evidence={"stream": w.get("stream"), "id": w.get("id")}))
        if not seen:
            claims.append(identity_claim(
                key, None, channel="ability_child", source_version=ABILITY_CHILD_VERSION,
                reason="no witness of the node publishes a claim (`CHANNELS` agent_claim)"))
    return claims


def child_identity(sid: str, children: list[dict]) -> list[dict]:
    """`ability_child_identity`: the `agent-identity` arbiter's verdict on each
    witnessed node's key, over the claims `child_claims` publishes. The
    arbiter (`adjudication.identity.adjudicate_agent_identity`) decides; this
    module names no agent itself."""
    from .adjudication.identity import adjudicate_agent_identity, identity_events
    return identity_events(adjudicate_agent_identity(child_claims(children)), sid)


def ability_summary(B: dict) -> dict:
    """The coverage rows of a build, for the command's print."""
    if "refused" in B:
        return B
    h, e = B["child_rows"][0], B["effect_rows"][0]
    return {"session": B["session_id"], "agent": B["agent"],
            **{k: h[k] for k in ("children", "objects", "objects_by_exists", "by_side", "unbound",
                                 "candidates", "by_opener", "by_end", "over_bound",
                                 "disabled", "refused", "candidate_reasons")},
            "effects": e["effects"], "by_effect": e["by_effect"], "effects_by_side": e["by_side"],
            "effects_refused": e["refused"]}


@dataclass(frozen=True)
class EntityRow:
    """One row of the entity axis, keyed `(kind, id)`.

    `side` is `ally` or `enemy` (relative to the player); `owner` is the id
    of the entity this one belongs to (None for a player; an ability
    instance's caster slot); `slot` is a player's lineup slot."""
    kind: str
    id: str
    side: str
    owner: str | None = None
    slot: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.id)


def binding_params() -> dict:
    return {"version": ENTITY_BINDING_VERSION, "W_ID": W_ID, "LLR_CLIP": LLR_CLIP, "K_NP": K_NP,
            "NP_BONUS": dict(NP_BONUS), "DECAY": DECAY, "SWAP_MIN": SWAP_MIN,
            "CHAIN_MIN": CHAIN_MIN, "K_RELOC": K_RELOC}


def v_max_m_s() -> float:
    """The reach ceiling in m/s [domain:game_data/character-movement-speeds]:
    the base top speed times the largest state multiplier."""
    from . import domain
    sp = domain.load()["game_data/character-movement-speeds"].values
    return float(sp["speed"]["base_max_speed_m_s"]) * max(1.0, *sp["state_multiplier"].values())


def units_per_m() -> float:
    """Game units per metre [domain:game_data/game-units-centimetres]."""
    from . import domain
    return float(domain.load()["game_data/game-units-centimetres"].values["units_per_m"])


# ----------------------------------------------------------------- the belief law (kind-agnostic)

def last_fix(has: np.ndarray, seg_start: np.ndarray) -> np.ndarray:
    """(N, F) index of each row's last fit at or before each frame within the
    frame's round segment, -1 where none. `seg_start[f]` is the first frame
    of f's segment: the round barrier."""
    N, F = has.shape
    idx = np.where(has, np.arange(F)[None, :], -1)
    lf = np.maximum.accumulate(idx, axis=1)
    return np.where(lf >= seg_start[None, :], lf, -1)


def nearest_other(X: np.ndarray, Y: np.ndarray, has: np.ndarray, d_max: float) -> np.ndarray:
    """(N, F) the nearest OTHER row with a fit in the same frame within
    `d_max` metres of each row's fit, -1 where none."""
    N, F = has.shape
    D = np.hypot(X[:, None, :] - X[None, :, :], Y[:, None, :] - Y[None, :, :])
    ok = has[:, None, :] & has[None, :, :] & ~np.eye(N, dtype=bool)[:, :, None]
    D = np.where(ok, D, np.inf)
    j = np.argmin(D, axis=1)
    dmin = np.take_along_axis(D, j[:, None, :], axis=1)[:, 0, :]
    return np.where(dmin <= d_max, j, -1)


def beliefs(t_ms: np.ndarray, X: np.ndarray, Y: np.ndarray, has: np.ndarray,
            open_: np.ndarray, seg_start: np.ndarray, *, r_fit: float, r_icon: float,
            v_max: float, wit: np.ndarray | None = None) -> dict:
    """Every row's belief at every frame, as (N, F) arrays.

    `X, Y` are bound fits in metres (NaN where none); `has` marks them and
    only fits inside an open row count. `wit` marks fits a witness names
    (default: all); only those anchor a reach region. Returns the kind, the
    point, the reach anchor and radius, and the crowd core's centre."""
    N, F = has.shape
    has = has & open_
    wit = has if wit is None else (wit & has)
    lf = last_fix(wit, seg_start)
    valid = lf >= 0
    lfc = np.where(valid, lf, 0)
    rows = np.arange(N)[:, None]
    ax = np.where(valid, X[rows, lfc], np.nan)
    ay = np.where(valid, Y[rows, lfc], np.nan)
    dt_s = np.where(valid, (t_ms[None, :] - t_ms[lfc]) / 1000.0, np.nan)
    R = v_max * dt_s + r_fit
    host_now = nearest_other(X, Y, has, 2.0 * r_icon)
    host = np.where(valid, host_now[rows, lfc], -1)
    hc = np.where(host >= 0, host, 0)
    cols = np.arange(F)[None, :]
    host_has = (host >= 0) & has[hc, cols]
    kind = np.full((N, F), CLOSED, np.uint8)
    kind[open_ & ~has & ~valid] = UNANCHORED
    kind[open_ & ~has & valid] = REACH
    kind[open_ & ~has & valid & host_has] = CROWD
    kind[has & ~wit] = FIT_UNNAMED
    kind[wit] = FIT
    fitlike = (kind == FIT) | (kind == FIT_UNNAMED)
    hx = np.where(kind == CROWD, X[hc, cols], np.nan)
    hy = np.where(kind == CROWD, Y[hc, cols], np.nan)
    px = np.where(fitlike, X, np.where(kind == CROWD, hx, ax))
    py = np.where(fitlike, Y, np.where(kind == CROWD, hy, ay))
    return {"kind": kind, "x": px, "y": py, "ax": ax, "ay": ay,
            "R": np.where(kind == FIT, r_fit, R), "dt_s": np.where(kind == FIT, 0.0, dt_s),
            "hx": hx, "hy": hy, "rc": 2.0 * r_icon + r_fit, "host": np.where(kind == CROWD, host, -1),
            "lf": lf, "lf_any": last_fix(has, seg_start), "r_fit": r_fit}


def contains(B: dict, s: np.ndarray, f: np.ndarray, x: np.ndarray, y: np.ndarray,
             tol: float = 0.0) -> dict:
    """Whether each query point lies in its row's region at its frame.

    `region` is the reported region; `core` the crowd core alone (the fit
    disc alone for `fit_unnamed`). `tol` is a scorer's registration
    tolerance, never the belief's."""
    k = B["kind"][s, f]
    d_pt = np.hypot(x - B["x"][s, f], y - B["y"][s, f])
    d_an = np.hypot(x - B["ax"][s, f], y - B["ay"][s, f])
    d_h = np.hypot(x - B["hx"][s, f], y - B["hy"][s, f])
    R = B["R"][s, f]
    in_fit = np.isin(k, (FIT, FIT_UNNAMED)) & (d_pt <= B["r_fit"] + tol)
    in_reach = np.isin(k, (REACH, CROWD, FIT_UNNAMED, SPAWN)) & (d_an <= R + tol)
    in_core = (k == CROWD) & (d_h <= B["rc"] + tol)
    free = (k == UNANCHORED) | ((k == FIT_UNNAMED) & ~np.isfinite(R))
    region = in_fit | in_reach | in_core | free
    core = np.where(k == CROWD, in_core, np.where(k == FIT_UNNAMED, in_fit, region))
    return {"region": region, "core": core, "kind": k, "point_err": d_pt,
            "dt_s": B["dt_s"][s, f], "R": R}


def union_area(r1, r2, d) -> np.ndarray:
    """Area of the union of two discs of radii r1, r2 whose centres lie d apart."""
    r1, r2, d = (np.asarray(v, float) for v in (r1, r2, d))
    a = np.pi * r1 ** 2 + np.pi * r2 ** 2
    lo, hi = np.abs(r1 - r2), r1 + r2
    inner = d <= lo
    sep = d >= hi
    with np.errstate(invalid="ignore", divide="ignore"):
        c1 = np.clip((d ** 2 + r1 ** 2 - r2 ** 2) / (2 * d * r1), -1, 1)
        c2 = np.clip((d ** 2 + r2 ** 2 - r1 ** 2) / (2 * d * r2), -1, 1)
        lens = (r1 ** 2 * np.arccos(c1) + r2 ** 2 * np.arccos(c2)
                - 0.5 * np.sqrt(np.clip((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2)
                                        * (d + r1 + r2), 0, None)))
    lens = np.where(inner, np.pi * np.minimum(r1, r2) ** 2, np.where(sep, 0.0, lens))
    return a - lens


def region_area(B: dict, s: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Area in m^2 of each queried region (NaN where the region is the map
    or the row is closed)."""
    k = B["kind"][s, f]
    R = B["R"][s, f]
    d = np.hypot(B["hx"][s, f] - B["ax"][s, f], B["hy"][s, f] - B["ay"][s, f])
    crowd = union_area(R, np.full_like(R, B["rc"]), np.nan_to_num(d))
    du = np.hypot(B["x"][s, f] - B["ax"][s, f], B["y"][s, f] - B["ay"][s, f])
    unnamed = union_area(np.full_like(R, B["r_fit"]), R, np.nan_to_num(du))
    return np.where(k == CROWD, crowd, np.where(k == FIT_UNNAMED, unnamed,
                    np.where(np.isin(k, (FIT, REACH, SPAWN)), np.pi * R ** 2, np.nan)))


def storage_record(B: dict, obs: np.ndarray) -> np.ndarray:
    """The prototype's per-frame record: frames by rows (kept for its scorer)."""
    N, F = B["kind"].shape
    rec = np.zeros((F, N), dtype=[("kind", "u1"), ("host", "i1"), ("x", "f4"), ("y", "f4"),
                                  ("ax", "f4"), ("ay", "f4"), ("R", "f2"), ("obs", "i4")])
    rec["kind"] = B["kind"].T
    rec["host"] = B["host"].T
    rec["x"], rec["y"] = B["x"].T, B["y"].T
    rec["ax"], rec["ay"] = B["ax"].T, B["ay"].T
    rec["R"] = np.minimum(np.nan_to_num(B["R"], nan=0.0), 6.0e4).T
    rec["obs"] = obs.T
    return rec


def frame_record(B: dict, obs: np.ndarray, t_ms: np.ndarray) -> np.ndarray:
    """Frames by rows with QUESTION_ACCEPTANCE section 4's fields: `read`
    (every stored frame was read in `full`), `t_obs` (the time of the read
    the belief rests on: the frame's own for a fit, the anchor's for reach
    and crowd, NaN otherwise) and `rate` (`fine` at the 15 Hz grid)."""
    rec = storage_record(B, obs)
    N, F = B["kind"].shape
    out = np.zeros((F, N), dtype=rec.dtype.descr + [("read", "u1"), ("t_obs", "f8"), ("rate", "u1")])
    for name in rec.dtype.names:
        out[name] = rec[name]
    k = B["kind"]
    lf = B["lf"]
    t_fit = np.broadcast_to(t_ms[None, :], k.shape)
    t_anchor = np.where(lf >= 0, t_ms[np.clip(lf, 0, None)], np.nan)
    t_obs = np.where(np.isin(k, (FIT, FIT_UNNAMED)), t_fit,
                     np.where(np.isin(k, (REACH, CROWD)), t_anchor, np.nan))
    out["read"] = READS.index("full")
    out["t_obs"] = t_obs.T
    out["rate"] = RATES.index("fine")
    return out


# ----------------------------------------------------------------- the world frame

def world_frame(sid: str, store_root: Path = DEFAULT_STORE):
    """The geometry's map frame from valorant-api's constants (found by the
    map name the geometry stores) and its inverse: ((mf, to_m, m_per_px),
    None), or (None, reason). No replay or Riot record is read."""
    from . import geometry
    from .replay_source import Reference, canon_name, map_frame_for
    store_root = Path(store_root)
    ref = Reference(store_root / "external" / "valorant-api", fetch=False)
    mname = geometry.map_of(sid, store_root)
    mi = [m for m in ref.maps.values() if canon_name(m.get("displayName")) == canon_name(mname)]
    if len(mi) != 1:
        return None, f"no_map_record:{mname}"
    man = Store(store_root).read_manifest(sid)
    mf, why = map_frame_for(sid, man, ref, {"match": {"matchInfo": {"mapId": mi[0]["mapUrl"]}}},
                            store_root)
    if mf is None:
        return None, why
    p0 = np.asarray(mf.to_px(0.0, 0.0))
    M = np.column_stack([np.asarray(mf.to_px(1000.0, 0.0)) - p0,
                         np.asarray(mf.to_px(0.0, 1000.0)) - p0]) / 1000.0
    Mi = np.linalg.inv(M)
    upm = units_per_m()

    def to_m(px, py):
        q = np.stack([np.asarray(px, float) - p0[0], np.asarray(py, float) - p0[1]])
        u = np.tensordot(Mi, q, axes=1)
        return u[0] / upm, u[1] / upm

    def to_px(x_m, y_m):
        q = np.stack([np.asarray(x_m, float) * upm, np.asarray(y_m, float) * upm])
        p = np.tensordot(M, q, axes=1)
        return p[0] + p0[0], p[1] + p0[1]

    to_m.to_px = to_px
    m_per_px = 1.0 / (mf.px_per_unit * upm)
    return (mf, to_m, m_per_px), None


# ----------------------------------------------------------------- stored rows

def _jsonl(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _raw_fits() -> dict:
    return {"frame_idx": [], "cx": [], "cy": [], "reason": [], "key": [], "self": [],
            "feats": [], "feats_version": []}


def _add_fit(raw: dict, sid: str, r: dict) -> None:
    """Keep one `ally_icon` row's fit for the causal binding: every icon row,
    refused or not, and each frame row's self fit."""
    k = r.get("kind")
    if k == "frame" and r.get("self") is not None:
        cx, cy, reason, key, own = r["self"][0], r["self"][1], None, f"{sid}:{r['frame_idx']}:self", True
        feats = fv = None
    elif k == "icon":
        cx, cy, reason, key, own = r["cx"], r["cy"], r.get("reason"), r["observation_key"], False
        feats, fv = r.get("portrait_features"), r.get("portrait_features_version")
    else:
        return
    raw["frame_idx"].append(int(r["frame_idx"]))
    raw["cx"].append(float(cx))
    raw["cy"].append(float(cy))
    raw["reason"].append(reason)
    raw["key"].append(key)
    raw["self"].append(own)
    raw["feats"].append(feats)
    raw["feats_version"].append(fv)


def raw_fits_from_rows(sid: str, rows) -> dict:
    """The causal binding's fits from `ally_icon` rows, in row order."""
    raw = _raw_fits()
    for r in rows:
        _add_fit(raw, sid, r)
    return raw


class StoredRows:
    """One session's stored rows as arrays, read once (no decode, no crop).

    The `ally_icon` frames give the clock; the `round_entity` ally and self
    observations, the post-round binding's fits; the `ally_icon` icon rows
    join them by observation key only where `round_entity` was built from
    the same `ally_icon` version (`ally_icon_stale` otherwise). The icon
    rows and self fits are also kept in file order for the causal binding."""

    def __init__(self, sid: str, store_root: Path = DEFAULT_STORE):
        self.sid = sid
        self.root = Path(store_root)
        st = Store(self.root)
        ev = self.root / "events"
        self.manifest = st.read_manifest(sid)
        date = self.manifest["ingested_at"][:10]
        self.rounds = st.read_rounds(sid, date).to_pylist()
        self.ally_icon_version = None
        fr = {"f": [], "t": [], "drawn": []}
        icon = {}
        #: the causal binding's raw fits, in file order
        raw = _raw_fits()
        for r in _jsonl(ev / "ally_icon" / f"{sid}.jsonl"):
            k = r.get("kind")
            if k == "coverage":
                self.ally_icon_version = r.get("ally_icon_version")
            elif k == "frame":
                fr["f"].append(r["frame_idx"])
                fr["t"].append(r["t_ms"])
                fr["drawn"].append(bool(r.get("widget_drawn")))
            elif k == "icon":
                icon[r["observation_key"]] = (r.get("area"), r.get("origin") == "stack_fit",
                                              r.get("facing"), r.get("r"))
            _add_fit(raw, sid, r)
        self.raw_fits = raw
        o = np.argsort(fr["f"], kind="stable")
        self.fr_f = np.asarray(fr["f"], np.int64)[o]
        self.fr_t = np.asarray(fr["t"], float)[o]
        self.fr_drawn = np.asarray(fr["drawn"], bool)[o]
        ents, ob = {}, defaultdict(list)
        self.round_entity_inputs = {}
        self.ally_icon_stale = None
        self.unbound = 0
        for r in _jsonl(ev / "round_entity" / f"{sid}.jsonl"):
            k = r.get("kind")
            if k == "coverage":
                self.round_entity_inputs = r.get("inputs") or {}
                self.ally_icon_stale = (self.round_entity_inputs.get("ally_icon")
                                        != self.ally_icon_version)
                if self.ally_icon_stale:
                    icon = {}
            elif k == "entity" and r.get("family") in ("ally", "self"):
                ents[r["id"]] = r
            elif k == "observation" and r.get("family") in ("ally", "self"):
                if r.get("entity_id") is None:
                    self.unbound += 1
                    continue
                ik = icon.get(r["observation_key"])
                ob["f"].append(r["frame_idx"])
                ob["t"].append(r["t_ms"])
                ob["e"].append(r["entity_id"])
                ob["x"].append(r["x"])
                ob["y"].append(r["y"])
                ob["self"].append(r["family"] == "self")
                ob["stack"].append(bool(ik and ik[1]))
        self.ents = ents
        self.ent_ids = sorted({*ob["e"]})
        code = {e: i for i, e in enumerate(self.ent_ids)}
        o = np.lexsort((np.asarray(ob["t"]), np.asarray(ob["f"])))
        self.ob_f = np.asarray(ob["f"], np.int64)[o]
        self.ob_t = np.asarray(ob["t"], float)[o]
        self.ob_e = np.asarray([code[e] for e in ob["e"]], np.int64)[o]
        self.ob_x = np.asarray(ob["x"], float)[o]
        self.ob_y = np.asarray(ob["y"], float)[o]
        self.ob_self = np.asarray(ob["self"], bool)[o]
        self.ob_stack = np.asarray(ob["stack"], bool)[o]
        rs = [v[3] for v in icon.values() if v[3]]
        #: the icon radius the reader measured; 6 px on the 331 px widget,
        #: scaled with it, where no icon row is joined
        self.r = float(np.median(rs)) if rs else None
        if self.r is None:
            from . import geometry
            with np.load(geometry.path_of(sid, self.root)) as z:
                self.r = 6.0 * z["labels"].shape[1] / 331.0
        self.deaths = [d for d in _jsonl(ev / "death" / f"{sid}.jsonl")
                       if d.get("kind") == "death_verdict"]

    def input_stamps(self) -> dict:
        """Every input stream's stamp, for the provenance of what is built."""
        from . import lineup
        st = Store(self.root)
        out = {k: st.events_version(k, self.sid)
               for k in ("ally_icon", "round_entity", "death", "ping", "spike", "tray_kit")}
        out["lineup"] = lineup.view_stamp(self.sid, self.root)
        out["rounds"] = self.manifest.get("ingested_at")
        return out


# ----------------------------------------------------------------- player slots

def lineup_slots(sid: str, store_root: Path = DEFAULT_STORE) -> dict:
    """The five ally player slots: each lineup slot's agent as the arbiter's
    verdict, and the player's slot."""
    from . import lineup
    L = lineup.load_lineup(sid, store_root)
    if L is None:
        return {"refused": "no_lineup"}
    ver = {v.get("entity_id"): v for v in L.get("agent_identity") or []}
    slots = []
    for k in range(5):
        v = ver.get(f"{sid}:ally:slot:{k}") or {}
        slots.append({"key": f"{sid}:ally:slot:{k}", "agent": v.get("agent"),
                      "status": v.get("status"), "reason": v.get("reason")})
    enemy = []
    for k in range(5):
        v = ver.get(f"{sid}:enemy:slot:{k}") or {}
        enemy.append({"key": f"{sid}:enemy:slot:{k}", "agent": v.get("agent"),
                      "status": v.get("status"), "reason": v.get("reason")})
    pl = L.get("player") or {}
    return {"slots": slots, "player_slot": pl.get("slot"), "player_agent": pl.get("agent"),
            "lineup_version": L.get("version"), "enemy_slots": enemy}


def player_rows(slots: list[dict]) -> list[EntityRow]:
    """The entity rows of the ally player slots."""
    return [EntityRow(KIND_PLAYER, s["key"], "ally", None, k) for k, s in enumerate(slots)]


def _slot_of_agent(slots: list[dict]) -> dict:
    return {agent_key(s["agent"]): k for k, s in enumerate(slots) if s["agent"]}


def round_segments(t: np.ndarray, rounds: list[dict]) -> dict:
    """The round barriers on the frame axis: each frame's segment (-1 before
    the first round), its segment's first frame, and the round starts."""
    F = t.size
    rounds = sorted(rounds, key=lambda r: float(r["t_start_ms"]))
    starts = np.asarray([float(r["t_start_ms"]) for r in rounds], float)
    seg = np.searchsorted(starts, t, side="right") - 1
    seg_start_idx = np.searchsorted(t, starts)
    seg_start = np.where(seg >= 0, seg_start_idx[np.clip(seg, 0, None)], F)
    return {"rounds": rounds, "starts": starts, "seg": seg, "seg_start": seg_start,
            "seg_start_idx": seg_start_idx}


def player_lifecycle(S: StoredRows, slots: list[dict], side: str = "ally") -> dict:
    """(5, F) open mask of one side's player slots from rounds and the death
    owner's verdicts on that side's victims, plus the events that set it."""
    t = S.fr_t
    F = t.size
    R = round_segments(t, S.rounds)
    seg, seg_start, seg_start_idx, starts = R["seg"], R["seg_start"], R["seg_start_idx"], R["starts"]
    round_idx = {r.get("round_no"): i for i, r in enumerate(R["rounds"])
                 if r.get("round_no") is not None}
    open_ = np.repeat((seg >= 0)[None, :], len(slots), axis=0)
    by_agent = _slot_of_agent(slots)
    ev = Counter()
    events = []
    for d in sorted((d for d in S.deaths if d.get("side") == side), key=lambda d: d["t_ms"]):
        if d.get("is_second_life"):
            ev["second_life"] += 1
            continue
        if d.get("victim") is None:
            ev["maybe_dead_unnamed"] += 1
            continue
        k = by_agent.get(agent_key(d.get("victim")))
        if k is None:
            ev["victim_no_slot"] += 1
            events.append({"t_ms": d["t_ms"], "victim": d.get("victim"), "what": "victim_no_slot"})
            continue
        f0 = int(np.searchsorted(t, float(d["t_ms"])))
        if f0 >= F:
            continue
        # the death owner's round, not the time segment: a round whose start
        # fell back to the score increment would put a post-round death into
        # the next round
        r = round_idx.get(d.get("round_no"), seg[f0])
        f1 = int(seg_start_idx[r + 1]) if r + 1 < starts.size else F
        if f0 >= f1:
            ev["death_past_its_round"] += 1
            continue
        if d.get("is_revive"):
            open_[k, f0:f1] = True
            ev["revive"] += 1
            events.append({"t_ms": d["t_ms"], "slot": k, "what": "revive", "death_id": d.get("death_id")})
        else:
            if not open_[k, f0]:
                ev["death_of_closed_slot"] += 1
            open_[k, f0:f1] = False
            ev["close"] += 1
            events.append({"t_ms": d["t_ms"], "slot": k, "what": "close", "death_id": d.get("death_id")})
    return {"open": open_, "seg": seg, "seg_start": seg_start, "events": events, "counts": dict(ev),
            "starts": starts}


# ----------------------------------------------------------------- post-round binding

def bind_entities(S: StoredRows, slots: list[dict], player_slot, open_: np.ndarray,
                  seg_start: np.ndarray, to_m, v_max: float, r_fit: float) -> dict:
    """Bind the stored `round_entity` entities' fits to player slots through
    their pooled verdicts and continuity (entity-state-0.2.0's binding)."""
    F = S.fr_t.size
    n = len(slots)
    t = S.fr_t
    fpos = np.searchsorted(S.fr_f, S.ob_f)
    ok = (fpos < F) & (S.fr_f[np.clip(fpos, 0, F - 1)] == S.ob_f)
    mx, my = to_m(S.ob_x, S.ob_y)
    X = np.full((n, F), np.nan)
    Y = np.full((n, F), np.nan)
    obs = np.full((n, F), -1, np.int64)
    occ = np.zeros((n, F), bool)
    how = np.zeros((n, F), np.uint8)
    by_agent = _slot_of_agent(slots)
    c = Counter()
    order = np.argsort(S.ob_e, kind="stable")
    bounds = np.searchsorted(S.ob_e[order], np.arange(len(S.ent_ids) + 1))
    ents = []
    for code, eid in enumerate(S.ent_ids):
        idx = order[bounds[code]:bounds[code + 1]]
        idx = idx[ok[idx]]
        if not idx.size:
            continue
        fr, first = np.unique(fpos[idx], return_index=True)    # one fit per entity-frame
        idx = idx[first]
        row = S.ents.get(eid) or {}
        ents.append({"id": eid, "idx": idx, "fr": fr, "self": bool(S.ob_self[idx].any()),
                     "agent": row.get("agent")})
    stack = np.asarray(getattr(S, "ob_stack", np.zeros(S.ob_f.size, bool)), bool)

    def put(k, e, keep, route):
        fr, idx = e["fr"][keep], e["idx"][keep]
        X[k, fr], Y[k, fr] = mx[idx], my[idx]
        obs[k, fr] = idx
        occ[k, fr] = True
        how[k, fr] = (np.where(stack[idx], HOW_NAMED_STACK, HOW_NAMED_RING)
                      if route == HOW_NAMED_RING else route)
        return int(keep.sum())

    unnamed = [e for e in ents if not (e["self"] or e["agent"])]
    c["unnamed_entities"] = len(unnamed)
    named = sorted((e for e in ents if e["self"] or e["agent"]),
                   key=lambda e: (not e["self"], -e["fr"].size))
    for e in named:
        k = player_slot if e["self"] else by_agent.get(agent_key(e["agent"]))
        if k is None:
            c["named_no_slot"] += 1
            unnamed.append(e)
            continue
        live = open_[k, e["fr"]]
        if e["self"]:
            c["self_fits"] += put(k, e, live & ~occ[k, e["fr"]], HOW_SELF)
            c["self_fits_after_close"] += int((~live).sum())
            continue
        clash = occ[k, e["fr"]]
        if clash.mean() > CONFLICT_SHARE or live.mean() < 0.5:
            c["named_conflict" if clash.mean() > CONFLICT_SHARE else "named_slot_closed"] += 1
            unnamed.append(e)
            continue
        c["named_bound"] += 1
        c["named_fits"] += put(k, e, live & ~clash, HOW_NAMED_RING)
        c["named_fits_dropped"] += int((~(live & ~clash)).sum())
    unnamed.sort(key=lambda e: e["fr"][0])
    for e in unnamed:
        f0 = int(e["fr"][0])
        s0 = int(seg_start[f0])
        cand = np.flatnonzero(open_[:, f0] & (occ[:, e["fr"]].mean(axis=1) <= CONFLICT_SHARE))
        if not cand.size:
            c["non_player_no_free_slot"] += 1
            c["non_player_fits"] += int(e["fr"].size)
            continue
        # each free slot's last fix this round, and the excess past its reach
        w = occ[cand, s0:f0]
        has_prev = w.any(axis=1)
        fl = s0 + (w.shape[1] - 1 - np.argmax(w[:, ::-1], axis=1)) if w.shape[1] else np.zeros(cand.size, int)
        fl = np.where(has_prev, fl, 0)
        d = np.hypot(X[cand, fl] - mx[e["idx"][0]], Y[cand, fl] - my[e["idx"][0]])
        excess = np.maximum(0.0, d - (v_max * (t[f0] - t[fl]) / 1000.0 + r_fit))
        d = np.where(has_prev, d, np.inf)
        excess = np.where(has_prev, excess, 0.0)
        best = int(np.lexsort((d, excess))[0])
        k = int(cand[best])
        c["continuity_bound"] += 1
        c["continuity_relocation"] += int(excess[best] > 0)
        c["continuity_fits"] += put(k, e, open_[k, e["fr"]] & ~occ[k, e["fr"]], HOW_CONTINUITY)
    return {"X": X, "Y": Y, "obs": obs, "has": occ, "how": how, "counts": dict(c)}


# ----------------------------------------------------------------- causal binding

def off_map_mask(sid: str, r_px: float, store_root: Path = DEFAULT_STORE) -> tuple[np.ndarray, float]:
    """(H, W) True where a fit's centre lies more than `r_px` from every
    non-void cell of the baked labels, and the map's non-void area in px."""
    from scipy.ndimage import distance_transform_edt

    from . import geometry
    from .minimap import VOID
    with np.load(geometry.path_of(sid, store_root)) as z:
        lab = z["labels"]
    void = lab == VOID
    return distance_transform_edt(void) > r_px, float((~void).sum())


def load_fits(S: StoredRows, slots: list[dict], player_slot, to_m, r_px: float,
              raw: dict) -> dict:
    """Every stored ally fit of the session's frames, in frame order (the
    self fit last in its frame), with its portrait log ratios per slot from
    the `agent-identity` owner and its non-player reasons. `raw` holds the
    fits (`S.raw_fits`, or `raw_fits_from_rows` over rows a test cuts)."""
    from .adjudication.identity import (load_ally_portrait_references, rendered_art_fit,
                                        rendered_art_scores, teammate_fit_refusal)
    st = Store(S.root)
    sid = S.sid
    F = S.fr_t.size
    refs = load_ally_portrait_references(S.root)
    ref_agents = list((refs or {}).get("agents", {}))
    names, col = [], []
    for k, s in enumerate(slots):
        if k == player_slot:
            continue
        n = reference_agent(s.get("agent"), ref_agents) if s.get("agent") else None
        if n is not None:
            names.append(n)
            col.append(k)

    fi =np.asarray(raw["frame_idx"], np.int64)
    # the last frame row of each frame index, as the prototype's dict kept it
    pos = np.searchsorted(S.fr_f, fi, side="right") - 1
    known = (pos >= 0) & (S.fr_f[np.clip(pos, 0, None)] == fi) if F else np.zeros(fi.size, bool)
    keep = np.flatnonzero(known)
    is_self = np.asarray(raw["self"], bool)[keep]
    reason = np.asarray(raw["reason"], object)[keep]
    llr = np.zeros((keep.size, 5))
    not_mate = np.zeros(keep.size, bool)
    nofeat = Counter()
    tf = (refs or {}).get("teammate_fit")
    fv = (refs or {}).get("features_version")
    # one call per fit into the owner's scorer: the arbiter's rule, not ours
    for j, i in enumerate(keep):
        if raw["self"][i]:
            continue
        feats = raw["feats"][i]
        if raw["reason"][i] is None and feats and refs and len(names) >= 2 \
                and raw["feats_version"][i] == fv:
            sc = rendered_art_scores(feats, names, refs)
            if sc is not None:
                llr[j, col] = [sc[n] for n in names]
            fit = rendered_art_fit(feats, names, refs)
            if fit is not None:
                not_mate[j] = teammate_fit_refusal([fit[0]], tf)[0] is not None
        else:
            nofeat[raw["reason"][i] or "no_features"] += 1
    fpos = pos[keep]
    o = np.lexsort((is_self, fpos))
    cx = np.asarray(raw["cx"], float)[keep][o]
    cy = np.asarray(raw["cy"], float)[keep][o]
    fpos, is_self, reason, llr, not_mate = fpos[o], is_self[o], reason[o], llr[o], not_mate[o]
    key = np.asarray(raw["key"], object)[keep][o]
    mx, my = to_m(cx, cy)
    t = S.fr_t[fpos]
    off, map_px = off_map_mask(sid, r_px, S.root)
    H, W = off.shape
    xi = np.clip(np.round(cx).astype(int), 0, W - 1)
    yi = np.clip(np.round(cy).astype(int), 0, H - 1)
    flags = {"off_map": off[yi, xi],
             "ability_glyph": (reason == "interior_is_map") & ~is_self,
             "not_a_teammate": not_mate & ~is_self}
    near = 2.0 * r_px
    ping = np.zeros(cx.size, bool)
    open_ping, pings = {}, []
    for r in sorted(st.read_events("ping", sid), key=lambda r: float(r["t_ms"])):
        if r.get("event_kind") == "entity_state" and r.get("position"):
            open_ping[r["entity_id"]] = (float(r["t_ms"]), r["position"])
        elif r.get("event_kind") == "entity_deleted" and r["entity_id"] in open_ping:
            t0, p = open_ping.pop(r["entity_id"])
            pings.append((t0, float(r["t_ms"]), p[0], p[1]))
    pings += [(t0, np.inf, p[0], p[1]) for t0, p in open_ping.values()]
    for t0, t1, px, py in pings:                        # a few dozen pings, each over every fit
        ping |= (t >= t0) & (t <= t1) & (np.hypot(cx - px, cy - py) <= near)
    flags["ping"] = ping & ~is_self
    spk = [(float(r["t_ms"]), g["cx"], g["cy"]) for r in st.read_events("spike", sid)
           if r.get("kind") == "frame" for g in (r.get("glyphs") or [])
           if g.get("state") == "dropped" and g.get("reason") is None]
    spike = np.zeros(cx.size, bool)
    if spk:
        ts = np.asarray([s[0] for s in spk])
        o2 = np.argsort(ts, kind="stable")
        ts = ts[o2]
        sx = np.asarray([s[1] for s in spk], float)[o2]
        sy = np.asarray([s[2] for s in spk], float)[o2]
        j = np.searchsorted(ts, t, side="right") - 1
        jc = np.clip(j, 0, None)
        same_t = ts[jc]
        for d in range(0, 3):
            jj = np.clip(jc - d, 0, None)
            ok = (j - d >= 0) & (ts[jj] == same_t) & (t - same_t <= 1000.0)
            spike |= ok & (np.hypot(cx - sx[jj], cy - sy[jj]) <= near)
    flags["spike"] = spike & ~is_self
    start = np.searchsorted(fpos, np.arange(F + 1))
    return {"fpos": fpos, "start": start, "cx": cx, "cy": cy, "x": mx, "y": my, "t": t,
            "is_self": is_self, "reason": reason, "llr": llr, "key": key, "flags": flags,
            "map_px": map_px, "ref_names": names, "ref_cols": col,
            "margin_min": (refs or {}).get("margin_min"), "llr_unread": dict(nofeat),
            "references_version": (refs or {}).get("version")}


def spectated_slots(S: StoredRows, slots: list[dict], player_agent) -> dict:
    """(F,) slot of the teammate whose kit the tray shows at each frame, -1
    where it shows the player's or none (`tray_kit`'s witness, no lookahead)."""
    from .adjudication.tray_kit import kit_agents_at, stored_kit_witness
    F = S.fr_t.size
    out = np.full(F, -1, np.int64)
    w = stored_kit_witness(Store(S.root).read_events("tray_kit", S.sid), agent=player_agent)
    if w.get("reason") or not w["spans"]:
        return {"slot": out, "reason": w.get("reason") or "no_spans", "version": w.get("version"),
                "rests_on": SPECTATE_RESTS_ON}
    agents = kit_agents_at(S.fr_t, w["spans"], lookahead_ms=0.0)
    by = _slot_of_agent(slots)
    for i, a in enumerate(agents):                      # one lookup per frame's span agent
        if a is None or same_agent(a, player_agent):
            continue
        k = by.get(agent_key(a))
        if k is not None:
            out[i] = k
    return {"slot": out, "reason": None, "version": w.get("version"), "own_basis": w.get("own_basis"),
            "rests_on": SPECTATE_RESTS_ON}


def causal_bind(t_ms: np.ndarray, fits: dict, open_: np.ndarray, seg_start: np.ndarray,
                player_slot, spect: np.ndarray, *, r_fit: float, v_max: float,
                log_area: float, r_dup_m: float, margin_min: float | None) -> dict:
    """Bind every frame's fits to player slots from what was bound before.

    A filter: each frame's state depends on the last, so the frame loop is
    sequential; within a frame every step runs over arrays and one
    `track.assign`. The motion prior and chain evidence reset at each round
    barrier and when a slot closes."""
    from . import track

    N = open_.shape[0]
    F = t_ms.size
    X = np.full((N, F), np.nan)
    Y = np.full((N, F), np.nan)
    has = np.zeros((N, F), bool)
    how = np.zeros((N, F), np.uint8)
    wit = np.zeros((N, F), np.uint8)
    obs = np.full((N, F), -1, np.int64)
    n_fits = fits["x"].size
    np_code = np.full(n_fits, -1, np.int8)
    bound_to = np.full(n_fits, -1, np.int64)
    wit_fit = np.zeros(n_fits, np.uint8)
    fx, fy = fits["x"], fits["y"]
    llr_raw = fits["llr"]
    llr = np.clip(llr_raw, -LLR_CLIP, LLR_CLIP)
    llr_any = llr_raw.any(axis=1)
    fl = fits["flags"]
    flag_m = np.stack([fl[r] for r in NP_REASONS], axis=1)
    first_reason = np.where(flag_m.any(axis=1), np.argmax(flag_m, axis=1), -1)
    bonus = flag_m.astype(float) @ np.asarray([NP_BONUS[r] for r in NP_REASONS])
    np_cost = log_area + K_NP - bonus
    start = fits["start"]
    is_self = fits["is_self"]
    off_map = fl["off_map"]
    mates = np.arange(N) != (player_slot if player_slot is not None else -1)
    px = np.zeros(N)
    py = np.zeros(N)
    tb = np.full(N, np.nan)
    E = np.zeros((N, N))
    c = Counter()
    seg_prev = -1
    t0 = time.process_time()
    for k in range(F):
        if seg_start[k] != seg_prev:                      # a round barrier: no slot is anchored
            tb[:] = np.nan
            E[:] = 0.0
            seg_prev = seg_start[k]
        op = open_[:, k]
        tb[~op] = np.nan
        E *= DECAY
        E[~op] = 0.0
        a, b = int(start[k]), int(start[k + 1])
        if a == b:
            continue
        idx = np.arange(a, b)
        free = op & mates
        sidx = idx[is_self[idx]]
        if sidx.size:
            i = int(sidx[0])
            target = None
            if player_slot is not None and op[player_slot]:
                target, h, w = player_slot, HOW_SELF, WITNESS_SELF
            elif off_map[i]:
                c["self_off_map"] += 1
            elif spect[k] >= 0 and op[spect[k]] and free[spect[k]]:
                target, h, w = int(spect[k]), HOW_SPECTATE, WITNESS_SPECTATE
                c["self_spectate_bound"] += 1
            if target is not None:
                X[target, k], Y[target, k] = fx[i], fy[i]
                has[target, k] = True
                how[target, k], wit[target, k] = h, w
                obs[target, k] = i
                bound_to[i] = target
                px[target], py[target], tb[target] = fx[i], fy[i], t_ms[k]
                free[target] = False
                idx = idx[idx != i]
            else:
                c["self_offered_to_assignment"] += 1
        if not idx.size:
            continue
        cols = np.flatnonzero(free)
        m = cols.size
        n = idx.size
        cost = np.full((n, m + n), np.inf)
        anch = np.isfinite(tb[cols])
        R = v_max * np.where(anch, (t_ms[k] - tb[cols]) / 1000.0, 0.0) + r_fit
        sig = R / 2.0
        d = np.hypot(fx[idx][:, None] - px[cols][None, :], fy[idx][:, None] - py[cols][None, :])
        motion = np.where(anch[None, :], np.minimum(0.5 * (d / sig[None, :]) ** 2
                                                    + np.log(2 * np.pi * sig[None, :] ** 2),
                                                    log_area + K_RELOC), log_area)
        cost[:, :m] = motion - W_ID * llr[idx][:, cols]
        cost[np.arange(n), m + np.arange(n)] = np_cost[idx]
        got = np.asarray(track.assign(cost), np.int64)
        rr = np.flatnonzero((got >= 0) & (got < m))
        if rr.size:
            jj = got[rr]
            ii = idx[rr]
            ss = cols[jj]
            X[ss, k], Y[ss, k] = fx[ii], fy[ii]
            has[ss, k] = True
            obs[ss, k] = ii
            bound_to[ii] = ss
            how[ss, k] = np.where(is_self[ii], HOW_ASSIGNED_SPECTATED, HOW_ASSIGNED)
            # the portrait lead over every other free slot's agent, and
            # exclusivity: inside this slot's reach alone, every other anchored
            L = llr_raw[ii][:, cols]
            ar = np.arange(rr.size)
            own = L[ar, jj]
            if m > 1:
                L[ar, jj] = -np.inf
                lead = np.where(llr_any[ii], own - L.max(axis=1), 0.0)
            else:
                lead = np.zeros(rr.size)
            ins = anch[None, :] & (d[rr] <= R[None, :])
            here = ins[ar, jj]
            excl = here & (ins.sum(axis=1) == here) & ((~anch).sum() == ~anch[jj])
            if margin_min is not None:
                excl &= lead > -margin_min
                w = np.where(lead >= margin_min, WITNESS_PORTRAIT,
                             np.where(excl, WITNESS_EXCLUSIVE, 0)).astype(np.uint8)
            else:
                w = np.where(excl, WITNESS_EXCLUSIVE, 0).astype(np.uint8)
            wit[ss, k] = w
            wit_fit[ii] = w
        b_now = has[:, k]
        px[b_now], py[b_now], tb[b_now] = X[b_now, k], Y[b_now, k], t_ms[k]
        ob = obs[:, k]
        lit = b_now & mates & (ob >= 0)
        if lit.any():
            E[lit] += llr[ob[lit]]
        cand = np.flatnonzero(op & mates)
        pw = np.flatnonzero(wit[:, k] == WITNESS_PORTRAIT)
        if pw.size and cand.size >= 2:
            for s in pw:                                # at most five slots
                rest = cand[cand != s]
                if E[s, s] - E[s, rest].max() < CHAIN_MIN:
                    wit[s, k] = WITNESS_PORTRAIT_UNCONFIRMED
                    c["witness_3_unconfirmed"] += 1
        if cand.size >= 2:
            sub = E[np.ix_(cand, cand)]
            if (np.argmax(sub, axis=1) != np.arange(cand.size)).any():
                g = track.assign(-sub)
                gain = sub[np.arange(cand.size), g].sum() - np.trace(sub)
                if gain >= SWAP_MIN and sorted(g) == list(range(cand.size)):
                    dest = cand[np.asarray(g)]
                    px[dest], py[dest], tb[dest] = px[cand].copy(), py[cand].copy(), tb[cand].copy()
                    E[dest] = E[cand].copy()
                    c["chain_moves"] += int((dest != cand).sum())
                    c["chain_swaps"] += 1
    loop_s = time.process_time() - t0
    # each assigned fit's witness, as first published
    assigned = np.isin(how[has], (HOW_ASSIGNED, HOW_ASSIGNED_SPECTATED))
    w_pub = wit_fit[obs[has][assigned]]
    for v, n_ in enumerate(np.bincount(w_pub, minlength=1)):
        if n_:
            c[f"witness_{v}"] += int(n_)
    # every fit left to its non-player column: its first stored reason, else
    # `duplicate` within `r_dup_m` of a fit its frame bound, else `unexplained`
    iu = np.flatnonzero(bound_to < 0)
    fu = fits["fpos"][iu]
    dmin = np.where(has[:, fu].T, np.hypot(X[:, fu].T - fx[iu][:, None], Y[:, fu].T - fy[iu][:, None]),
                    np.inf).min(axis=1) if iu.size else np.zeros(0)
    fr_ = first_reason[iu]
    np_code[iu] = np.where(fr_ >= 0, fr_, np.where(dmin <= r_dup_m, len(NP_REASONS),
                                                   len(NP_REASONS) + 1))
    o = obs[obs >= 0]
    c["fit_bound_twice"] = int(o.size - np.unique(o).size)
    c["fits"] = int(n_fits)
    c["fits_bound"] = int((bound_to >= 0).sum())
    c["fits_offered"] = int(n_fits)
    np_bucket = np.full(n_fits, "", object)
    has_b = np_code >= 0
    np_bucket[has_b] = np.asarray(NP_BUCKETS, object)[np_code[has_b]]
    codes, counts = np.unique(np_code[has_b], return_counts=True)
    return {"X": X, "Y": Y, "has": has, "how": how, "wit": wit, "obs": obs,
            "np_bucket": np_bucket, "bound_to": bound_to, "counts": dict(c),
            "np_by_reason": {NP_BUCKETS[int(v)]: int(n_) for v, n_ in zip(codes, counts)},
            "flag_counts": {r: int(fl[r].sum()) for r in NP_REASONS},
            "loop_cpu_s": loop_s}


# ----------------------------------------------------------------- enemy slots

#: Why an `enemy_track` observation binds no enemy slot, in report order.
#: `bound` binds; the rest name the stored fact that stops it.
ENEMY_FIT_REASONS = ("bound", "no_track", "track_refused", "track_unnamed", "agent_not_in_lineup",
                     "off_frame_axis", "slot_closed", "duplicate")
ENEMY_RESTS_ON = ("enemy_track observations (minimap_object enemy finds the round_lifetimes "
                  "lane joined into tracks)",
                  "enemy_track entity verdicts: identity status and agent from "
                  "adjudication.identity, pooled over each track (post-round per track)",
                  "round_lifetimes.detection_reality on each track (a refused track binds nothing)",
                  "lineup agent_identity on the enemy slots", "enemy death_verdict rows")


def enemy_rows(slots: list[dict]) -> list[EntityRow]:
    """The entity rows of the enemy player slots."""
    return [EntityRow(KIND_PLAYER, s["key"], "enemy", None, k) for k, s in enumerate(slots)]


def stored_enemy_tracks(sid: str, store_root: Path = DEFAULT_STORE) -> dict | None:
    """The stored `enemy_track` rows as arrays: each track's arbiter verdict
    and reality status, and every observation's time, place (widget px)
    and track; None where the stream is not stored. Reads no pixel."""
    path = Path(store_root) / "events" / "enemy_track" / f"{sid}.jsonl"
    if not path.is_file():
        return None
    head, ents = {}, {}
    ob = {"t": [], "x": [], "y": [], "e": []}
    for r in _jsonl(path):
        k = r.get("kind")
        if k == "summary":
            head = r
        elif k == "entity":
            ents[r["id"]] = {"agent": r.get("agent"), "identity_status": r.get("identity_status"),
                             "reality_status": r.get("reality_status"),
                             "observations": int(r.get("observations") or 0)}
        elif k == "observation":
            ob["t"].append(float(r["t_ms"]))
            ob["x"].append(float(r["x"]))
            ob["y"].append(float(r["y"]))
            ob["e"].append(r.get("entity_id"))
    ids = sorted(ents)
    code = {e: i for i, e in enumerate(ids)}
    return {"ids": ids, "ents": [ents[e] for e in ids],
            "t": np.asarray(ob["t"], float), "x": np.asarray(ob["x"], float),
            "y": np.asarray(ob["y"], float),
            "e": np.asarray([code.get(e, -1) if e else -1 for e in ob["e"]], np.int64),
            "stamp": {k: head.get(k) for k in ("enemy_track_version", "minimap_object_version",
                                               "agent_identity_version", "lineup_version",
                                               "detection_reality_version")}}


def bind_enemy_tracks(fr_t: np.ndarray, T: dict, slots: list[dict], open_: np.ndarray,
                      to_m) -> dict:
    """Bind the stored enemy observations to the enemy slots.

    A track binds to the slot whose lineup verdict names the agent its own
    verdict names; both verdicts are the `agent-identity` arbiter's, so no
    name is chosen here. Only a `resolved` track binds; a track
    `detection_reality` refused binds nothing. An observation binds to the
    slot model's nearest frame within half a frame step (the `minimap_object`
    and `ally_icon` grids may sample other frames of one 15 Hz period) where
    the slot is open; two observations on one slot-frame keep the longer
    track's. Returns (5, F)
    `X`, `Y` (metres), `has`, `wit` (every bound fit: the arbiter named its
    track), `obs` (the observation's row) and the counts by
    `ENEMY_FIT_REASONS`."""
    n, F = len(slots), fr_t.size
    X = np.full((n, F), np.nan)
    Y = np.full((n, F), np.nan)
    has = np.zeros((n, F), bool)
    obs = np.full((n, F), -1, np.int64)
    by_agent = _slot_of_agent(slots)
    ents = T["ents"]
    # each track's slot, or the reason it has none (codes index ENEMY_FIT_REASONS)
    R = {r: i for i, r in enumerate(ENEMY_FIT_REASONS)}
    e_slot = np.full(len(ents), -1, np.int64)
    e_why = np.full(len(ents), R["bound"], np.int64)
    for i, e in enumerate(ents):                      # one entry per track, not per frame
        if e["reality_status"] == "refused":
            e_why[i] = R["track_refused"]
        elif e["identity_status"] != "resolved" or not e["agent"]:
            e_why[i] = R["track_unnamed"]
        elif agent_key(e["agent"]) not in by_agent:
            e_why[i] = R["agent_not_in_lineup"]
        else:
            e_slot[i] = by_agent[agent_key(e["agent"])]
    # a last sentinel track stands for observations no track holds
    e_slot = np.append(e_slot, -1)
    e_why = np.append(e_why, R["no_track"])
    e_n = np.asarray([e["observations"] for e in ents] + [0], np.int64)
    oe = np.where(T["e"] >= 0, T["e"], len(ents))
    why = e_why[oe]
    k = e_slot[oe]
    on = np.zeros(oe.size, bool)
    pc = np.zeros(oe.size, np.int64)
    if F:
        i = np.searchsorted(fr_t, T["t"])
        lo, hi = np.clip(i - 1, 0, F - 1), np.clip(i, 0, F - 1)
        pc = np.where(np.abs(fr_t[lo] - T["t"]) <= np.abs(fr_t[hi] - T["t"]), lo, hi)
        half = 0.5 * float(np.median(np.diff(fr_t))) if F > 1 else math.inf
        on = np.abs(fr_t[pc] - T["t"]) <= half
    why = np.where((why == R["bound"]) & ~on, R["off_frame_axis"], why)
    kc = np.clip(k, 0, None)
    live = open_[kc, pc] if F else np.zeros(oe.size, bool)
    why = np.where((why == R["bound"]) & ~live, R["slot_closed"], why)
    cand = np.flatnonzero(why == R["bound"])
    # one fit per slot-frame: the longest track's, then the first row
    o = cand[np.lexsort((cand, -e_n[oe[cand]], pc[cand], k[cand]))]
    first = np.ones(o.size, bool)
    first[1:] = (k[o][1:] != k[o][:-1]) | (pc[o][1:] != pc[o][:-1])
    why[o[~first]] = R["duplicate"]
    keep = o[first]
    if keep.size:
        mx, my = to_m(T["x"][keep], T["y"][keep])
        X[k[keep], pc[keep]] = mx
        Y[k[keep], pc[keep]] = my
        has[k[keep], pc[keep]] = True
        obs[k[keep], pc[keep]] = keep
    counts = {r: int((why == i).sum()) for r, i in R.items()}
    counts["observations"] = int(oe.size)
    counts["tracks"] = len(ents)
    counts["tracks_bound"] = int((e_slot[:-1] >= 0).sum())
    return {"X": X, "Y": Y, "has": has, "wit": has.copy(), "obs": obs, "why": why, "counts": counts}


def enemy_block(S: StoredRows, L: dict, to_m) -> dict:
    """The enemy slots' rows, lifecycle and bound fits, from stored rows.

    Without stored `enemy_track` rows every enemy slot holds no fit, so its
    belief is `unanchored` while open, and the reason says so."""
    slots = L["enemy_slots"]
    life = player_lifecycle(S, slots, side="enemy")
    T = stored_enemy_tracks(S.sid, S.root)
    F = S.fr_t.size
    if T is None:
        n = len(slots)
        bind = {"X": np.full((n, F), np.nan), "Y": np.full((n, F), np.nan),
                "has": np.zeros((n, F), bool), "wit": np.zeros((n, F), bool),
                "obs": np.full((n, F), -1, np.int64), "counts": {"reason": "no_enemy_track"}}
        stamp = {"enemy_track": None}
    else:
        bind = bind_enemy_tracks(S.fr_t, T, slots, life["open"], to_m)
        stamp = T["stamp"]
    return {"rows": enemy_rows(slots), "slots": slots, "life": life, "bind": bind,
            "stamp": {"enemy_binding_version": ENEMY_BINDING_VERSION, **stamp}}


def join_beliefs(Bs: list[dict]) -> dict:
    """Join per-side `beliefs` outputs on the entity axis; a crowd host's
    index moves with its block. The blocks share `r_fit` and the crowd core."""
    out = {"rc": Bs[0]["rc"], "r_fit": Bs[0]["r_fit"]}
    off = 0
    hosts = []
    for B in Bs:
        hosts.append(np.where(B["host"] >= 0, B["host"] + off, -1))
        off += B["kind"].shape[0]
    for k in ("kind", "x", "y", "ax", "ay", "R", "dt_s", "hx", "hy", "lf", "lf_any"):
        out[k] = np.concatenate([B[k] for B in Bs], axis=0)
    out["host"] = np.concatenate(hosts, axis=0)
    return out


# ----------------------------------------------------------------- the spawn anchor

#: spawn-anchor-0.1.0 (2026-10-09): the anchor law's own stamp.
#: spawn-anchor-0.2.0 (2026-10-09): the disc encloses the side's pre-round
#: area (`map_regions.pre_round_areas`, bounded by the game files'
#: `SpawnBarrier_C` placements), not its callout `Spawn` volumes alone.
SPAWN_ANCHOR_VERSION = "spawn-anchor-0.2.0"
#: The sides whose slots the spawn anchors. 0.1.0 shipped off: on the six
#: replay sessions the callout `Spawn` volumes missed most players at the
#: barrier drop, who walk up to the barriers in the buy phase (the store's
#: notes/predictions.jsonl, enemy-spawn-anchor-20261009-S1-outcome). 0.2.0
#: is on for both: on the same sessions the enemy calibration held within the
#: anchor-off interval while the enemy and ally unanchored shares fell
#: (spawn-barriers-20261009-S1-outcome).
SPAWN_ANCHOR_SIDES: tuple[str, ...] = ("ally", "enemy")
SPAWN_ANCHOR_OFF = "off by SPAWN_ANCHOR_SIDES"
#: Side codes for the anchor arrays, in the rounds owner's words
#: (`rounds.SIDES`); -1 is an unread side.
SIDE_CODES = ("attack", "defence")
SPAWN_RESTS_ON = ("callout-region: each side's pre-round area (map_regions.pre_round_areas: the 3D "
                  "table's walk cells flooded from the side's `Spawn` callout volumes, stopped by the "
                  "spawn barriers)",
                  "spawn-barriers: the game files' SpawnBarrier_C placements and TeamRole "
                  "(spawn_barriers, a table apart from the geometry)",
                  "round-bounds: rounds.starting_side over the stored spike and spike_carrier rows, "
                  "then rounds.side_in_round at each round's match_round",
                  "gametime: each round's barrier drop (t_live_ms) from the stored HUD clock")


def spawn_discs(map_name: str, store_root: Path = DEFAULT_STORE) -> dict:
    """Each side's spawn disc in metres, round its pre-round area.

    The callout-region owner draws each side's pre-round area
    (`map_regions.pre_round_areas`: where the side may walk before the drop,
    bounded by its spawn barriers from the game files, `spawn_barriers`);
    the disc is the smallest circle round that polygon
    (`cv2.minEnclosingCircle`), and `r_map` the distance from its centre to
    the farthest corner of any callout volume, so a disc of radius `r_map`
    covers every place the map names. Returns `discs` (side -> (cx, cy, r,
    r_map)), `provenance`, `areas` (each side's basis and size) and `map`, or
    `{"refused": why}`. Reads no capture."""
    import cv2

    from . import map_regions, spawn_barriers
    try:
        reg = map_regions.Regions.load(map_name, store_root)
    except FileNotFoundError:
        return {"refused": f"no_callout_volumes:{map_name}"}
    try:
        bars = spawn_barriers.load(map_name, store_root)
    except FileNotFoundError:
        return {"refused": f"no_spawn_barriers:{map_name}"}
    cells = map_regions.walk_cells(map_name, store_root)
    areas = map_regions.pre_round_areas(reg, bars, cells)
    upm = units_per_m()
    corners = map_regions.plan_corners(reg).reshape(-1, 2) / upm
    discs, info = {}, {}
    for side in SIDE_CODES:
        if side not in areas:
            continue
        poly = (areas[side]["polygon"] / upm).astype(np.float32)
        (cx, cy), r = cv2.minEnclosingCircle(poly)
        r_map = float(np.hypot(corners[:, 0] - cx, corners[:, 1] - cy).max())
        discs[side] = (float(cx), float(cy), float(r), r_map)
        info[side] = {"basis": areas[side]["basis"], "fallback": areas[side].get("fallback"),
                      "cells": areas[side].get("cells"), "area_m2": round(float(cv2.contourArea(poly)), 1)}
    if not discs:
        return {"refused": f"no_pre_round_area:{map_name}"}
    prov = dict(reg.provenance(), pre_round_area=map_regions.PRE_ROUND_AREA_VERSION,
                walk_table=(cells or {}).get("table"), bridges=(cells or {}).get("bridges"),
                spawn_barriers={"version": bars["version"], "table": bars["path"],
                                "sha16": bars["sha16"], "build": bars["provenance"]["build"]})
    return {"discs": discs, "map": map_name, "provenance": prov, "areas": info}


def team_sides(rounds: list[dict], starting: str | None) -> tuple[np.ndarray, Counter]:
    """Each round's side for the player's team as codes into `SIDE_CODES`
    (-1 unread), asked of the rounds owner (`rounds.side_in_round` at
    `rounds.match_round`), and the count of each unread reason."""
    from .rounds import match_round, side_in_round
    team = np.full(len(rounds), -1, np.int64)
    why = Counter()
    for i, r in enumerate(rounds):           # one entry per round, not per frame
        side, reason = side_in_round(match_round(r), starting)
        if side is None:
            why[reason] += 1
        else:
            team[i] = SIDE_CODES.index(side)
    return team, why


def round_sides(S: StoredRows, rounds: list[dict]) -> dict:
    """Each round's side for the player's team and its barrier drop, from
    their owners, in `rounds` order (`round_segments`' sorted rounds).

    The side is `rounds.side_in_round` at the round's `match_round`, given
    `rounds.starting_side` over the stored `spike` and `spike_carrier` rows;
    the halftime and overtime swaps are that owner's rule. The drop is
    `gametime`'s `t_live_ms` over the stored HUD clock (which falls back to
    the round's start where the clock went unread: the disc then grows from
    the start, a wider region, never a narrower one). Returns `team` (codes
    into `SIDE_CODES`, -1 unread), `t_live` (ms), `starting_side`, and the
    reasons."""
    from .rounds import starting_side
    ev = S.root / "events"
    spike = list(_jsonl(ev / "spike" / f"{S.sid}.jsonl"))
    carrier = list(_jsonl(ev / "spike_carrier" / f"{S.sid}.jsonl"))
    st = starting_side(S.rounds, spike or None, carrier or None)
    team, why = team_sides(rounds, st["starting_side"])
    t_start = np.asarray([float(r["t_start_ms"]) for r in rounds], float)
    t_live = t_start.copy()
    store = Store(S.root)
    date = S.manifest["ingested_at"][:10]
    if store.hud_path(S.sid, date).is_file() and rounds:
        from .gametime import build_session_gametime
        gt = build_session_gametime(S.sid, store.read_hud(S.sid, date), rounds, stall_list=[])
        live = {float(s.t_start_ms): float(s.t_live_ms) for s in gt.schedules}
        t_live = np.asarray([live.get(float(t), float(t)) for t in t_start], float)
    else:
        why["no_hud_stream"] += len(rounds)
    why["t_live_at_start"] += int((t_live <= t_start).sum())
    return {"team": team, "t_live": t_live, "starting_side": st["starting_side"],
            "starting_side_reason": st["reason"], "votes": len(st["votes"]),
            "reasons": dict(why)}


def spawn_anchor(B: dict, t_ms: np.ndarray, seg: np.ndarray, side: np.ndarray,
                 t_live: np.ndarray, discs: dict, *, r_fit: float, v_max: float) -> tuple[dict, dict]:
    """Anchor every open row that has no witnessed fix this round at its
    side's spawn; return the beliefs and the counts.

    `seg` is each frame's round (-1 before the first), `side` each round's
    side for these rows (codes into `SIDE_CODES`, -1 unread), `t_live` each
    round's barrier drop (ms) and `discs` side -> (cx, cy, r, r_map) in
    metres (`spawn_discs`). The region is a disc round the spawn disc's
    centre of radius `r + r_fit` until the drop, then grown by `v_max` per
    second since it: the reach law, from the spawn instead of a fix
    [domain:rounds/buy-phase-barriers]. An `unanchored` row becomes `spawn`;
    an unwitnessed fit with no witnessed fix (`fit_unnamed`, reach NaN) takes
    the spawn disc as its reach. Where the disc would reach `r_map` it covers
    the map and the row stays as `beliefs` left it, as it does where the
    side, the drop or the spawn is unread. The first witnessed fix ends the
    anchor: `beliefs` has then set a reach from that fix."""
    kind = B["kind"]
    nr = len(side)
    D = np.full((len(SIDE_CODES) + 1, 4), np.nan)
    for i, sd in enumerate(SIDE_CODES):
        if sd in discs:
            D[i] = discs[sd]
    on = seg >= 0
    sg = np.clip(seg, 0, max(nr - 1, 0))
    sc = np.where(on & (nr > 0), np.asarray(side, np.int64)[sg] if nr else -1, -1)
    sc = np.where(sc >= 0, sc, len(SIDE_CODES))
    cx, cy, r0, r_map = D[sc].T
    t0 = np.where(on & (nr > 0), np.asarray(t_live, float)[sg] if nr else np.nan, np.nan)
    dt = np.clip((t_ms - t0) / 1000.0, 0.0, None)
    Rs = r0 + r_fit + v_max * dt
    ok = np.isfinite(Rs) & (Rs < r_map)
    free = (kind == UNANCHORED) | ((kind == FIT_UNNAMED) & ~np.isfinite(B["R"]))
    a = free & ok[None, :]
    sp = a & (kind == UNANCHORED)
    out = dict(B)
    out["kind"] = np.where(sp, SPAWN, kind).astype(kind.dtype)
    out["ax"] = np.where(a, cx[None, :], B["ax"])
    out["ay"] = np.where(a, cy[None, :], B["ay"])
    out["R"] = np.where(a, Rs[None, :], B["R"])
    out["dt_s"] = np.where(a, dt[None, :], B["dt_s"])
    out["x"] = np.where(sp, cx[None, :], B["x"])
    out["y"] = np.where(sp, cy[None, :], B["y"])
    has_side = np.isfinite(r0)
    counts = {"spawn": int(sp.sum()), "fit_unnamed_anchored": int((a & ~sp).sum()),
              "past_map": int((free & (has_side & ~ok)[None, :]).sum()),
              "side_unread": int((free & (on & ~has_side)[None, :]).sum())}
    return out, counts


def spawn_context(S: StoredRows, seg_rounds: list[dict], store_root: Path = DEFAULT_STORE) -> dict:
    """The spawn anchor's inputs for one session: the discs (`spawn_discs`
    on the geometry's map name), each round's side and drop (`round_sides`)
    and the stamp; `{"refused": why}` where the map has no spawn volume."""
    from . import geometry
    mname = geometry.map_of(S.sid, store_root)
    D = spawn_discs(mname, store_root)
    if "refused" in D:
        return D
    RS = round_sides(S, seg_rounds)
    team = RS["team"]
    other = np.where(team >= 0, 1 - team, -1)
    stamp = {"spawn_anchor_version": SPAWN_ANCHOR_VERSION, "sides": list(SPAWN_ANCHOR_SIDES),
             "map": mname, "callout_regions": D["provenance"], "areas": D["areas"],
             "discs_m": {k: [round(v, 2) for v in d] for k, d in D["discs"].items()},
             "starting_side": RS["starting_side"], "starting_side_reason": RS["starting_side_reason"],
             "starting_side_votes": RS["votes"], "reasons": RS["reasons"],
             "rests_on": list(SPAWN_RESTS_ON)}
    return {"discs": D["discs"], "side": {"ally": team, "enemy": other}, "t_live": RS["t_live"],
            "stamp": stamp}


# ----------------------------------------------------------------- assembly

def stack_entities(blocks: list[dict]) -> dict:
    """Join per-kind blocks (`rows`, `open`, `X`, `Y`, `has`, `wit`, `obs`)
    on the entity axis, so `beliefs` runs once over every kind."""
    out = {"rows": [r for b in blocks for r in b["rows"]]}
    for k in ("open", "X", "Y", "has", "wit", "obs"):
        out[k] = np.concatenate([b[k] for b in blocks], axis=0)
    return out


def rests_on(binding: str, spect: dict | None = None) -> list[str]:
    """What a session's beliefs rest on, by binding mode."""
    common = ["lineup agent_identity", "death_verdict rows", "round table"]
    if binding == "causal":
        sp = (spect or {}).get("reason")
        return ["ally_icon fits (all, causal, per frame)", "identity.rendered_art_scores per fit",
                "identity.teammate_fit_refusal", "ping and spike events", "baked geometry labels",
                (spect or {}).get("rests_on", "tray_kit spectating witness")
                + (f" (unused: {sp})" if sp else "")] + common
    return ["round_entity entity verdicts (post-round, pooled)"] + common


def build_slots(sid: str, binding: str = "causal", store_root: Path = DEFAULT_STORE) -> dict:
    """Player slots and beliefs for one session from stored rows; timed.

    Returns a dict: `rows` (the `EntityRow`s), `S` (the stored rows), `L`
    (the lineup's slots), `life`, `bind`, `B` (the beliefs, (N, F) arrays),
    `rec` and `record` (frames by rows), `t_ms`, `windows` (the frame axis
    cut at the round barriers, `round_windows`), the world frame (`mf`,
    `to_m`, `m_per_px`), `params`, `cost`, `stamp`; or `{"refused": why}`."""
    if binding not in ("causal", "post_round"):
        raise ValueError(f"unknown binding {binding!r}")
    store_root = Path(store_root)
    t_load = time.process_time()
    S = StoredRows(sid, store_root)
    L = lineup_slots(sid, store_root)
    if "refused" in L:
        return {"session": sid, "refused": L["refused"]}
    wf, why = world_frame(sid, store_root)
    if wf is None:
        return {"session": sid, "refused": why}
    mf, to_m, m_per_px = wf
    v_max = v_max_m_s()
    dt_frame = float(np.median(np.diff(S.fr_t))) / 1000.0
    r_icon = float(S.r) * m_per_px
    r_fit = r_icon + v_max * dt_frame
    extra = {}
    if binding == "causal":
        fits = load_fits(S, L["slots"], L["player_slot"], to_m, float(S.r), raw=S.raw_fits)
        spect = spectated_slots(S, L["slots"], L["player_agent"])
        extra = {"fits": fits, "spect": spect}
    load_s = time.process_time() - t_load
    t0 = time.process_time()
    life = player_lifecycle(S, L["slots"])
    t1 = time.process_time()
    if binding == "causal":
        log_area = math.log(fits["map_px"] * m_per_px ** 2)
        bind = causal_bind(S.fr_t, fits, life["open"], life["seg_start"], L["player_slot"],
                           spect["slot"], r_fit=r_fit, v_max=v_max, log_area=log_area,
                           r_dup_m=2.0 * r_icon, margin_min=fits["margin_min"])
        wit = np.isin(bind["wit"], ANCHORING)
        bind["counts"]["spectate_witness"] = spect["reason"] or "read"
    else:
        bind = bind_entities(S, L["slots"], L["player_slot"], life["open"], life["seg_start"],
                             to_m, v_max, r_fit)
        wit = np.isin(bind["how"], WITNESSED)
    t2 = time.process_time()
    ally = {"rows": player_rows(L["slots"]), "open": life["open"], "X": bind["X"], "Y": bind["Y"],
            "has": bind["has"], "wit": wit, "obs": bind["obs"]}
    en = enemy_block(S, L, to_m)
    enemy = {"rows": en["rows"], "open": en["life"]["open"], **{k: en["bind"][k] for k in
                                                                  ("X", "Y", "has", "wit", "obs")}}
    t2e = time.process_time()
    E = stack_entities([ally, enemy])
    # the law runs once per side, so a crowd's host is an icon of the same side
    Bs = [beliefs(S.fr_t, b["X"], b["Y"], b["has"], b["open"], life["seg_start"],
                  r_fit=r_fit, r_icon=r_icon, v_max=v_max, wit=b["wit"]) for b in (ally, enemy)]
    # then each side's rows with no witnessed fix this round hold their spawn
    SP = (spawn_context(S, round_segments(S.fr_t, S.rounds)["rounds"], store_root)
          if SPAWN_ANCHOR_SIDES else {"refused": "off: " + SPAWN_ANCHOR_OFF})
    spawn_stamp = ({"version": SPAWN_ANCHOR_VERSION, "refused": SP["refused"]} if "refused" in SP
                   else dict(SP["stamp"], counts={}))
    if "refused" not in SP:
        for i, side in enumerate(("ally", "enemy")):
            if side in SPAWN_ANCHOR_SIDES:
                Bs[i], spawn_stamp["counts"][side] = spawn_anchor(
                    Bs[i], S.fr_t, life["seg"], SP["side"][side], SP["t_live"], SP["discs"],
                    r_fit=r_fit, v_max=v_max)
    B = join_beliefs(Bs)
    t3 = time.process_time()
    rec = storage_record(B, E["obs"])
    F = S.fr_t.size
    params = {"v_max_m_s": v_max, "dt_frame_s": dt_frame, "r_icon_m": r_icon,
              "r_fit_m": r_fit, "crowd_core_m": 2 * r_icon + r_fit,
              "conflict_share": CONFLICT_SHARE, "binding": binding,
              **({"binding_params": binding_params()} if binding == "causal" else {})}
    stamp = {"slot_state_version": SLOT_STATE_VERSION, "ported_from": PORTED_FROM,
             "binding": binding, "inputs": S.input_stamps(),
             "rests_on": rests_on(binding, extra.get("spect")), "params": params,
             **({"portrait_references": extra["fits"]["references_version"],
                 "spectate_witness": extra["spect"].get("version")} if binding == "causal" else {}),
             "enemy": {**en["stamp"], "rests_on": list(ENEMY_RESTS_ON)},
             "spawn_anchor": spawn_stamp}
    return {"session": sid, "rows": E["rows"], "S": S, "L": L, "mf": mf, "to_m": to_m,
            "m_per_px": m_per_px, "t_ms": S.fr_t, "life": life,
            "windows": round_windows(S.fr_t, life["starts"]), "bind": bind, "B": B, "rec": rec,
            "open": E["open"], "obs": E["obs"], "enemy": en,
            "binding": binding, **extra, "params": params, "stamp": stamp,
            "cost": {"frames": int(F), "load_cpu_s": round(load_s, 2),
                     "lifecycle_us_per_frame": round((t1 - t0) / F * 1e6, 2),
                     "bind_us_per_frame": round((t2 - t1) / F * 1e6, 2),
                     "enemy_us_per_frame": round((t2e - t2) / F * 1e6, 2),
                     "beliefs_us_per_frame": round((t3 - t2e) / F * 1e6, 2),
                     "total_us_per_frame": round((t3 - t0) / F * 1e6, 2),
                     "record_bytes_per_frame": int(rec.dtype.itemsize * rec.shape[1])}}


# ----------------------------------------------------------------- the gate's query

def round_windows(t: np.ndarray, starts: np.ndarray) -> dict:
    """The frame axis cut at the round barriers, once per session: window 0
    holds the frames before the first round start, window `w` the frames of
    round `w - 1`. `lo[w]` is window `w`'s first frame (`lo[-1]` is `F`),
    `t[w]` a view of its frame times, `starts` the sorted round starts."""
    starts = np.sort(np.asarray(starts, float))
    lo = np.concatenate([[0], np.searchsorted(t, starts), [t.size]]).astype(int)
    return {"starts": starts, "lo": lo, "t": [t[a:b] for a, b in zip(lo[:-1], lo[1:])]}


class RegionCursor:
    """The gate's per-frame query: a forward-only cursor over one session's
    frame axis, scoped to the round.

    `at(t_ms)` answers what `region_at` answers, for instants that never
    decrease. Within a round it steps to the next frame without a search;
    after a gap it searches only the rest of the current round's frames. At a
    round barrier it resets to the new round's window, so no query reaches
    past the round it falls in. The cursor carries a frame index and the last
    instant, no belief."""

    def __init__(self, G: dict):
        self.G = G
        W = G["windows"]
        self.starts, self.lo, self.views = W["starts"], W["lo"], W["t"]
        self.t = G["t_ms"]
        self.w = 0                  # the window holding the last instant
        self.f = -1                 # the latest frame at or before it
        self.t_last = -math.inf

    def at(self, t_ms: float) -> dict:
        t_ms = float(t_ms)
        if t_ms < self.t_last:
            raise ValueError(f"RegionCursor moves forward only: {t_ms} after {self.t_last}")
        self.t_last = t_ms
        if self.w < self.starts.size and t_ms >= self.starts[self.w]:
            # the round barrier: reset to the window of the round t_ms falls in
            while self.w < self.starts.size and t_ms >= self.starts[self.w]:
                self.w += 1
            self.f = int(self.lo[self.w]) - 1
        lo, hi = int(self.lo[self.w]), int(self.lo[self.w + 1])
        nxt = self.f + 1
        if nxt < hi and self.t[nxt] <= t_ms:
            if nxt + 1 < hi and self.t[nxt + 1] <= t_ms:
                # a gap: search the rest of this round's frames only
                self.f = nxt + int(np.searchsorted(self.views[self.w][nxt - lo:], t_ms,
                                                   side="right")) - 1
            else:
                self.f = nxt
        return region_of_frame(self.G, self.f, t_ms)


def region_at(G: dict, t_ms: float) -> dict:
    """Every entity's region at one instant `t_ms`, for a one-off query such
    as `reticle slot-state --at`: a fresh `RegionCursor` locates the round,
    then searches its frames only. A per-frame gate holds one cursor."""
    return RegionCursor(G).at(t_ms)


def region_of_frame(G: dict, f: int, t_ms: float) -> dict:
    """Every entity's region at instant `t_ms`, from stored frame `f`, the
    latest at or before it (causal), each radius grown by `v_max` over the
    gap.

    A region is the union of at most two discs: the point disc (`x_m`,
    `y_m`, `r_m`: the fit disc for `fit` and `fit_unnamed`, the crowd core
    round the host for `crowd`) and the reach disc (`ax_m`, `ay_m`,
    `reach_m`: round the round's last witnessed fix, for `reach`, `crowd`
    and an anchored `fit_unnamed`; round the spawn disc's centre for
    `spawn`). A missing disc is NaN; `unanchored` is
    the whole map (`reach_m` infinite); `closed` has neither. The same in
    baked widget pixels: `px`, `py`, `r_px`, `apx`, `apy`, `reach_px`.
    Returns `key` ((kind, id)) and `kind` per entity, `age_s` and `frame`.
    Frame -1, an instant before the first frame, returns every entity
    closed."""
    t = G["t_ms"]
    B = G["B"]
    N = B["kind"].shape[0]
    keys = [r.key for r in G["rows"]]
    if f < 0:
        nan = np.full(N, np.nan)
        return {"key": keys, "open": np.zeros(N, bool), "kind": ["closed"] * N,
                **{k: nan for k in ("x_m", "y_m", "r_m", "ax_m", "ay_m", "reach_m", "px", "py",
                                    "r_px", "apx", "apy", "reach_px")},
                "age_s": np.nan, "frame": -1}
    age = (float(t_ms) - float(t[f])) / 1000.0
    k = B["kind"][:, f]
    grow = G["params"]["v_max_m_s"] * age
    point = np.isin(k, (FIT, FIT_UNNAMED, CROWD))
    r_pt = np.where(k == CROWD, B["rc"], B["r_fit"]) + grow
    r_pt = np.where(point, r_pt, np.nan)
    x = np.where(point, B["x"][:, f], np.nan)
    y = np.where(point, B["y"][:, f], np.nan)
    R = B["R"][:, f]
    reach = np.isin(k, (REACH, CROWD, FIT_UNNAMED, SPAWN)) & np.isfinite(R)
    r_re = np.where(reach, R + grow, np.where(k == UNANCHORED, np.inf, np.nan))
    ax = np.where(reach, B["ax"][:, f], np.nan)
    ay = np.where(reach, B["ay"][:, f], np.nan)
    px, py = G["to_m"].to_px(x, y)
    apx, apy = G["to_m"].to_px(ax, ay)
    mpp = G["m_per_px"]
    return {"key": keys, "open": k != CLOSED, "kind": [KINDS[int(v)] for v in k],
            "x_m": x, "y_m": y, "r_m": r_pt, "ax_m": ax, "ay_m": ay, "reach_m": r_re,
            "px": px, "py": py, "r_px": r_pt / mpp, "apx": apx, "apy": apy,
            "reach_px": r_re / mpp, "age_s": age, "frame": f}


# ----------------------------------------------------------------- the gate's own belief

#: gate-belief-0.1.0 (2026-10-09): the belief a per-frame ally gate reads,
#: fed by the gated reader's own reads.
GATE_BELIEF_VERSION = "gate-belief-0.1.0"


class GateBelief:
    """The slot belief a per-frame ally gate asks before it reads
    (`ally_gate.AllyGate`, `passes`' hook), built from the gated reads alone.

    `RegionCursor` answers from a record built over every stored 15 Hz
    read; a gate that asked it would open where the full-rate reader had
    already read, which gates on the outcome. This belief holds instead what
    the gated reader itself saw: `observe` feeds back each read the gate
    opened, and `at` answers from those reads and from the priors of other
    channels only -- the round table's barriers and the death owner's
    verdicts, through `player_lifecycle`, for how many teammate slots are
    open.

    The law is this module's: a slot fixed at `t_fix` lies within
    `r_fit + v_max (t - t_fix)` metres (`beliefs`' reach). The binding is a
    count, not a slot assignment: a read that finds at least as many
    teammate icons as there are open teammate slots fixes every slot;
    otherwise the unfixed ones keep their last fix. No fix this round is
    `unanchored`. State resets at each round barrier (`reset`), so nothing
    outlives a round.

    Reach is the Euclidean disc. Walk reach waits for a walk graph baked
    into the geometry (BACKLOG item 3); until then the disc overstates how
    far a teammate can have gone, so the gate opens early, never late.
    """

    def __init__(self, t_grid: np.ndarray, n_open: np.ndarray, starts: np.ndarray,
                 r_fit_m: float, v_max: float, m_per_px: float, stamp: dict):
        self.t_grid = np.asarray(t_grid, float)
        self.n_open = np.asarray(n_open, np.int64)
        self.starts = np.sort(np.asarray(starts, float))
        self.r_fit_m, self.v_max, self.m_per_px = float(r_fit_m), float(v_max), float(m_per_px)
        self.stamp = stamp
        self.seg = None
        self.reset()

    def reset(self) -> None:
        """Forget every read: the next instant is unanchored."""
        self.t_fix = None
        self.t_read = None
        self.fix_px = np.zeros((0, 2))

    def radius_m(self, age_s: float) -> float:
        """The reach after `age_s` seconds unread (`beliefs`' law)."""
        return self.r_fit_m + self.v_max * max(0.0, float(age_s))

    def age_for(self, radius_m: float) -> float:
        """Seconds unread until the reach grows to `radius_m`."""
        return max(0.0, (float(radius_m) - self.r_fit_m) / self.v_max)

    def open_teammates(self, t_ms: float) -> int:
        """Open teammate slots (the player's own excluded) at `t_ms`."""
        i = int(np.searchsorted(self.t_grid, float(t_ms), side="right")) - 1
        return int(self.n_open[i]) if i >= 0 else 0

    def _barrier(self, t_ms: float) -> None:
        seg = int(np.searchsorted(self.starts, float(t_ms), side="right")) - 1
        if seg != self.seg:
            self.seg = seg
            self.reset()

    def at(self, t_ms: float) -> dict:
        """`n_open`, `kind` (`unanchored`, `fit` or `reach`), `radius_m`
        (infinite when unanchored), `t_read` (the last read this round,
        None before one), `fix_px` (the teammate icons of the last read, in
        widget pixels)."""
        self._barrier(t_ms)
        n = self.open_teammates(t_ms)
        if self.t_fix is None:
            kind, r = "unanchored", math.inf
        else:
            age = (float(t_ms) - self.t_fix) / 1000.0
            kind, r = ("fit" if age <= 0 else "reach"), self.radius_m(age)
        return {"n_open": n, "kind": kind, "radius_m": r, "t_read": self.t_read,
                "fix_px": self.fix_px}

    def observe(self, t_ms: float, fits_px) -> None:
        """A read at `t_ms` found the teammate icons at `fits_px` (n, 2)."""
        self._barrier(t_ms)
        fits = np.asarray(fits_px, float).reshape(-1, 2)
        self.t_read = float(t_ms)
        self.fix_px = fits
        if len(fits) >= self.open_teammates(t_ms):
            self.t_fix = float(t_ms)


def gate_belief(sid: str, store_root: Path = DEFAULT_STORE, hz: float = 15.0) -> dict:
    """The session's `GateBelief`, from stored rounds, death verdicts and
    the lineup alone -- no ally read; or `{"refused": why}`.

    The lifecycle (`player_lifecycle`) runs on a `hz` grid over the
    capture; a missing lineup leaves every teammate slot open in each round
    and says so in the stamp. `r_fit` takes the icon radius from the baked
    geometry (6 px on the 331 px widget, scaled) and one grid step's reach."""
    from types import SimpleNamespace

    from . import geometry, lineup
    root = Path(store_root)
    st = Store(root)
    manifest = st.read_manifest(sid)
    date = manifest["ingested_at"][:10]
    wf, why = world_frame(sid, root)
    if wf is None:
        return {"refused": why}
    _mf, _to_m, m_per_px = wf
    dur = float(manifest["source"].get("duration_ms") or 0.0)
    t = np.arange(0.0, dur + 1000.0 / hz, 1000.0 / hz)
    rows = list(_jsonl(root / "events" / "death" / f"{sid}.jsonl"))
    deaths = [d for d in rows if d.get("kind") == "death_verdict"]
    # The death owner places X-mark births through `death.stored_xmark_births`,
    # which reads the stored 15 Hz `ally_icon`: a prior that rests on it.
    death_inputs = next((d.get("inputs") or {} for d in rows if d.get("inputs")), {})
    S = SimpleNamespace(fr_t=t, rounds=st.read_rounds(sid, date).to_pylist(), deaths=deaths)
    L = lineup_slots(sid, root)
    if "refused" in L:
        slots, player = [{"key": f"{sid}:ally:slot:{k}", "agent": None} for k in range(5)], None
    else:
        slots, player = L["slots"], L["player_slot"]
    life = player_lifecycle(S, slots)
    mates = [k for k in range(len(slots)) if k != player]
    n_open = life["open"][mates].sum(axis=0)
    with np.load(geometry.path_of(sid, root)) as z:
        r_px = 6.0 * z["labels"].shape[1] / 331.0
    v_max = v_max_m_s()
    r_fit = r_px * m_per_px + v_max / hz
    stamp = {"gate_belief_version": GATE_BELIEF_VERSION, "slot_state_version": SLOT_STATE_VERSION,
             "inputs": {"death": deaths[0].get("death_adjudication_version") if deaths else None,
                        "death_ally_icon": death_inputs.get("ally_icon"),
                        "lineup": lineup.view_stamp(sid, root) if "refused" not in L
                        else f"refused: {L['refused']}",
                        "rounds": manifest.get("ingested_at")},
             "law": "reach = r_fit + v_max (t - t_fix); a read finding the open teammates' "
                    "count fixes every slot",
             "r_fit_m": round(r_fit, 4), "v_max_m_s": v_max, "m_per_px": round(m_per_px, 6),
             "lifecycle": life["counts"]}
    return {"belief": GateBelief(t, n_open, life["starts"], r_fit, v_max, m_per_px, stamp),
            "deaths_t": sorted(float(d["t_ms"]) for d in deaths if d.get("t_ms") is not None),
            "stamp": stamp}


def stored_enemy_icons(sid: str, store_root: Path = DEFAULT_STORE):
    """`(t_ms, x, y)` arrays of the stored `minimap_object` enemy icons in
    widget pixels, sorted by time, and the stream's stamp; `(None, None)`
    where none is stored. A gate's cue, never a verdict on the teammate."""
    path = Path(store_root) / "events" / "minimap_object" / f"{sid}.jsonl"
    if not path.is_file():
        return None, None
    t, x, y, ver = [], [], [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if ver is None and '"kind":"coverage"' in line:
                ver = json.loads(line).get("minimap_object_version")
                continue
            if '"enemies":[{' not in line:
                continue
            r = json.loads(line)
            if r.get("kind") != "frame":
                continue
            for e in r["enemies"]:
                t.append(float(r["t_ms"]))
                x.append(float(e["x"]))
                y.append(float(e["y"]))
    o = np.argsort(np.asarray(t, float), kind="stable")
    return tuple(np.asarray(a, float)[o] for a in (t, x, y)), ver


def ally_gate_for(sid: str, store_root: Path = DEFAULT_STORE):
    """The ally pass's runtime gate for one session (`ally_gate.AllyGate`):
    this module's `GateBelief`, the death verdicts' times and the stored
    enemy icons, each named with its stamp in `rests_on`; or
    `{"refused": why}`. Reads no replay and no ally row."""
    from .ally_gate import AllyGate
    got = gate_belief(sid, store_root)
    if "refused" in got:
        return got
    enemy, ver = stored_enemy_icons(sid, store_root)
    st = got["stamp"]
    deaths = (f"death verdicts {st['inputs']['death']}, whose X-mark births "
              f"(`death.stored_xmark_births`) read the stored 15 Hz ally_icon "
              f"{st['inputs']['death_ally_icon']}")
    sources = {"belief": f"slot_state.GateBelief {st['gate_belief_version']} "
                         f"({st['slot_state_version']}) over the lineup {st['inputs']['lineup']}, "
                         f"rounds {st['inputs']['rounds']} and the {deaths}",
               "death": f"{deaths} (cue)"}
    if enemy is not None:
        sources["enemy"] = f"minimap_object enemy icons {ver} (cue)"
    return AllyGate(got["belief"], got["deaths_t"], enemy, sources)


# ----------------------------------------------------------------- storage

def l2_path(sid: str, store_root: Path = DEFAULT_STORE) -> Path:
    return Path(store_root) / "l2" / "slot_state" / f"{sid}.npz"


def write_record(G: dict, store_root: Path = DEFAULT_STORE) -> Path:
    """Store the per-frame record at `<store>/l2/slot_state/<session>.npz`
    with its stamp, written beside and moved into place whole."""
    p = l2_path(G["session"], store_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = frame_record(G["B"], G["obs"], G["t_ms"])
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, rec=rec, t_ms=G["t_ms"].astype("f8"),
                        frame_idx=G["S"].fr_f.astype("i4"), open=G["open"],
                        keys=np.asarray([f"{r.kind}|{r.id}" for r in G["rows"]]),
                        sides=np.asarray([r.side for r in G["rows"]]),
                        stamp=np.asarray(json.dumps(G["stamp"], default=str)))
    tmp.replace(p)
    return p


def slot_summary(G: dict) -> dict:
    """Counts a command prints: belief kinds over open entity-frames, the
    lifecycle and binding counts, and the cost."""
    out = {"session": G["session"], "version": SLOT_STATE_VERSION, "binding": G["binding"],
           "frames": int(G["B"]["kind"].shape[1]), "entities": len(G["rows"])}
    side = np.asarray([r.side for r in G["rows"]])
    for s in ("ally", "enemy"):
        k = G["B"]["kind"][side == s]
        op = k != CLOSED
        out[s] = {"entities": int(k.shape[0]),
                  "open_share": round(float(op.mean()), 4) if k.size else None,
                  "kinds": {KINDS[int(v)]: int((k[op] == v).sum()) for v in np.unique(k[op])}}
    out["ally"].update(lifecycle=G["life"]["counts"], binding_counts=G["bind"]["counts"])
    out["enemy"].update(lifecycle=G["enemy"]["life"]["counts"],
                        binding_counts=G["enemy"]["bind"]["counts"])
    out["cost"] = G["cost"]
    return out


# ----------------------------------------------------------------- the self slot, per sampled instant

# Folded in from `reticle/belief.py` (belief-0.3.0, unchanged) on 2026-10-09,
# so one owner answers `position-belief` for every slot. Its invariants hold
# for the whole module: evidence arrives as arguments (this section fetches
# nothing), a `Fix` is never evidence (it seeds no template, feeds no
# detector's prior and counts toward no observed coverage), and observed and
# believed coverage are reported apart, never summed.
#
#: Bumped from 0.1.0, which lived in `minimap` and consulted the self reads and
#: the step law alone. Voids and reachability change the answer, so a stored
#: belief from the old rule cannot read as current. 0.3.0: an instant the
#: stored menu witness finds covered is absent (`absent_instants`).
BELIEF_VERSION = "belief-0.3.0"

OBSERVED = "observed"
INTERPOLATED = "interpolated"
HELD = "held"
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Fix:
    """Where the player is believed to be at one sampled instant.

    `source` separates a read from an inference, which is the distinction
    `docs/ADJUDICATION_DESIGN.md` requires and a bare `(t, x, y)` tuple loses:

        observed      the reader answered here and the step law admitted it
        interpolated  bracketed by two admitted reads close enough in time
        held          carried forward from the last read; nothing closes it yet
        unresolved    no belief -- `x`/`y` are None and `reason` says why

    `radius_px` is a physical bound, not a calibrated confidence: the fit error
    plus how far a running player could have travelled since the evidence,
    bounded by the nearer endpoint when the instant is bracketed. It is an
    UPPER bound and a generous one, because it is a disk: the reachable set is
    smaller wherever the map has walls, and expressing that is still owed.

    `rests_on` names the observation instants the belief was drawn from, so a
    later adjudication can link back to the raw reads rather than re-deriving
    which ones it used. An observed fix rests on itself; an unresolved one on
    nothing.
    """

    t_ms: float
    x: float | None
    y: float | None
    source: str
    radius_px: float | None
    reason: str | None = None
    rests_on: tuple[float, ...] = ()

    @property
    def observed(self) -> bool:
        return self.source == OBSERVED


def absent_instants(rows: list[dict], menu=None) -> list[float]:
    """The instants a stored L1 row cannot show the widget was drawn.

    **`minimap-0.6.0` answers this directly.** The reader refuses a frame on
    exactly the widget test and now records the answer, so a row carrying
    `widget_drawn` is authoritative: false means nobody was looking, true means
    the reader looked and refused. Only the first forbids a belief; the second
    is a detection failure and the layer may interpolate across it.

    **Older rows do not carry the column, and its absence is UNKNOWN rather
    than false.** For those this falls back to the ally cross-reference, which
    reads the same widget: an ally icon at that instant proves the widget was
    drawn, whatever the self reader did. That rule is sufficient and not
    necessary -- a drawn widget with no visible teammate still lands here -- so
    it OVER-reports absence and keeps the belief conservative where it cannot
    tell. On `c40d950031bb` it recovered 2016 of 2676 unread instants as
    plainly drawn. The two paths are kept apart deliberately: mixing a measured
    flag with a proxy would make a stale table look like a fresh one.

    **The menu covers the widget.** It dims the minimap, which still passes
    the widget test [domain:hud/menu-dims-tray]; `menu(t_ms)` is the stored
    menu witness (`menu.MenuWitness.at`), and an instant it finds covered is
    absent whatever the row says.
    """
    out: list[float] = []
    for r in rows:
        if menu is not None and menu(r["t_ms"]) is True:
            out.append(r["t_ms"])
            continue
        if r.get("self_x") is not None:
            continue
        drawn = r.get("widget_drawn")
        if drawn is None:                      # pre-0.6.0 row: use the proxy
            drawn = bool(r.get("n_allies"))
        if not drawn:
            out.append(r["t_ms"])
    return sorted(out)


def round_voids(rounds: list[dict]) -> list[float]:
    """Round starts and ends, as instants no belief may be carried across.

    A round start returns every player to spawn, so a position from the
    previous round says nothing about this one. Passed as `voids` rather than
    read here, because this module models no round semantics.
    """
    out: list[float] = []
    for r in rounds:
        out.extend((float(r["t_start_ms"]), float(r["t_end_ms"])))
    return sorted(out)


def _on(mask: np.ndarray | None, x: float, y: float) -> bool:
    """Is a believed centre somewhere the player could stand."""
    if mask is None:
        return True
    xi, yi = int(round(x)), int(round(y))
    if yi < 0 or xi < 0 or yi >= mask.shape[0] or xi >= mask.shape[1]:
        return False
    return bool(mask[yi, xi])


def resolve(found: list[tuple[float, float, float]], step_ms: float,
            scale: float = 1.0, motion=None, absent_t=None, voids=None,
            reachable: np.ndarray | None = None) -> list[Fix]:
    """One belief per sampled instant, carrying its source and its bound.

    Shares `minimap.admit_steps` with `filter_track`, so the two cannot
    disagree about which observations the motion law admitted. Unlike
    `filter_track` this answers at every instant the caller sampled, because a
    refused frame is a position the model still needs and `unresolved` states
    plainly where none exists.

    `absent_t` names the instants the widget was NOT drawn. Nothing is
    interpolated or held across one, because the player may have died or opened
    the full map there, and inventing a path through the only frames that state
    nobody was looking is the fault `filter_track` was fixed for. `None` means
    the caller cannot tell, and then EVERY unread instant is treated as
    unobservable -- the conservative reading, and why `absent_instants` exists.

    `voids` names instants that destroy the prior outright: round boundaries,
    and later deaths and camera wipes. Crossing one is not a long gap to be
    held through, it is a different situation about which the earlier read says
    nothing.

    `reachable` is a boolean mask in the same pixel frame as the positions. A
    believed centre off it is refused, because the map states outright that
    nobody stands there. Build it with the fit error admitted either side --
    `art_floor(kind, dilate=5)` holds 99.6% of the reader's own accepted
    centres on `c40d950031bb` against 98.6% undilated. Observed reads are never
    gated on it: they are evidence, and evidence is not discarded for
    disagreeing with a mask.
    """
    keep, jumps, _ = admit_steps(found, scale, motion)
    if absent_t is None:
        blind = sorted(p[0] for p in found if p[1] is None or p[2] is None)
    else:
        blind = sorted(float(t) for t in absent_t)
    dead = sorted(float(t) for t in (voids or ()))
    kept_t = [k[0] for k in keep]
    kept_at = {k[0]: k for k in keep}
    jump_after = {kept_t[i] for i in jumps if i < len(kept_t)}
    fit_err = FIT_ERR_PX * scale
    reach = RUN_PX * scale
    unobservable = set(blind)

    out: list[Fix] = []
    for t_ms, _x, _y in found:
        # The instant itself may be the one nobody was looking at, which is a
        # different answer from a gap BETWEEN two such instants.
        if t_ms in unobservable and t_ms not in kept_at:
            out.append(Fix(t_ms, None, None, UNRESOLVED, None, "widget_absent"))
            continue
        hit = kept_at.get(t_ms)
        if hit is not None:
            out.append(Fix(t_ms, hit[1], hit[2], OBSERVED, fit_err,
                           rests_on=(t_ms,)))
            continue
        # A read the step law rejected is not evidence, but the instant still
        # needs a belief; `reason` keeps the rejection visible.
        rejected = _x is not None and _y is not None
        i = int(np.searchsorted(kept_t, t_ms, side="left"))
        before = kept_at[kept_t[i - 1]] if i > 0 else None
        after = kept_at[kept_t[i]] if i < len(kept_t) else None
        reason = "rejected_step" if rejected else None
        voided = False
        if before is not None and crosses(dead, before[0], t_ms):
            before, voided = None, True
        if before is not None and crosses(blind, before[0], t_ms):
            before = None
            reason = "widget_absent"
        if after is not None and (crosses(dead, t_ms, after[0])
                                  or crosses(blind, t_ms, after[0])):
            after = None
        candidate = None
        if (before is not None and after is not None
                and before[0] not in jump_after
                and after[0] - before[0] <= GAP_MS):
            span = after[0] - before[0]
            f = (t_ms - before[0]) / span
            nearer = min(t_ms - before[0], after[0] - t_ms) / 1000.0
            candidate = Fix(t_ms,
                            before[1] + (after[1] - before[1]) * f,
                            before[2] + (after[2] - before[2]) * f,
                            INTERPOLATED, fit_err + reach * nearer, reason,
                            rests_on=(before[0], after[0]))
        elif (before is not None and before[0] not in jump_after
                and t_ms - before[0] <= GAP_MS):
            held = (t_ms - before[0]) / 1000.0
            candidate = Fix(t_ms, before[1], before[2], HELD,
                            fit_err + reach * held, reason,
                            rests_on=(before[0],))
        if candidate is not None:
            if _on(reachable, candidate.x, candidate.y):
                out.append(candidate)
                continue
            # Geometry contradicts the motion model. The straight line between
            # two reads is an assumption; the map's footprint is not.
            reason = "off_floor"
        if reason is None or reason == "rejected_step":
            if voided:
                reason = "void"
            elif before is not None and before[0] in jump_after:
                reason = "teleport"
            elif reason is None:
                reason = "stale"
        out.append(Fix(t_ms, None, None, UNRESOLVED, None, reason))
    return out
