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
kind exists, `player`: the five ally slots, keyed
`<session>:ally:slot:<k>` as the lineup keys them. The belief law
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
No ability kind is built here.

Ability children and effects (declared, not built)
--------------------------------------------------
docs/ABILITY_ENTITIES.md makes this module the owner of ability instances
(`ability` children) and what they do to players (`effect` entities). They
form a tree: slot, ability instance, spawned objects nested to any depth,
effects; each node has its own lifecycle and a revisable parent binding to
any entity key. The owner holds
[owns:ability-child], [owns:ability-effect] and [owns:ability-owner], each
`partial` until its migration step builds it (step 2 the player's children
and effects, step 3 the team's and the caster verdict). Step 1 ships only the
declaration: `CHANNELS`, every input the child owner may read and what each
may do (open a child, join one, end one, name its kind, claim its agent),
stamped `ABILITY_CHANNELS_VERSION`, and `ABILITY_LANES`, the two lanes
ability entities reach consumers through. The ABILITY ratchet
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
`unanchored` (no fix this round: the map). `v_max` is the top ground speed
from the game files [domain:game_data/character-movement-speeds] in metres
[domain:game_data/game-units-centimetres]. Negative evidence is off.
Reach is still a Euclidean disc: the walk reach the gate needs (BACKLOG item
3) waits for a walk graph baked with the geometry, since `reticle/` may not
read the prototypes' sightline tables.

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
SLOT_STATE_VERSION = "slot-state-0.1.0"
#: The binding law's own stamp (unchanged from the prototype).
ENTITY_BINDING_VERSION = "entity-binding-0.1.1"
#: The prototype versions this module reproduces.
PORTED_FROM = {"entity_state": "entity-state-0.3.0", "entity_binding": ENTITY_BINDING_VERSION}

#: Entity kinds. Only `player` is built.
KIND_PLAYER = "player"

#: Belief kinds, as stored (u1).
CLOSED, FIT, CROWD, REACH, UNANCHORED, FIT_UNNAMED = 0, 1, 2, 3, 4, 5
KINDS = {CLOSED: "closed", FIT: "fit", CROWD: "crowd", REACH: "reach", UNANCHORED: "unanchored",
         FIT_UNNAMED: "fit_unnamed"}
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

#: Entity kinds the child owner will hold beside `player` (section 2.2).
KIND_ABILITY = "ability"
KIND_EFFECT = "effect"
#: The ownership entries this module answers for ability entities.
ABILITY_ENTRIES = ("ability-child", "ability-effect", "ability-owner")

#: ability-channels-0.1.0 (2026-10-09): section 2.3's witness table, as code.
#: A change to any row restamps this table, never the player slots.
ABILITY_CHANNELS_VERSION = "ability-channels-0.1.0"

#: What an input may open: any child, a child of the player's team only, or
#: either only where no child of that ability is live.
OPENS = ("any", "team", "if_none_live", "team_if_none_live")

#: Every input the child owner may read, one row per witness (section 2.3),
#: and what it may do:
#:
#: - `opens`: one of `OPENS`, or None where it never opens a child;
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
     "wired": True,
     "owners": ("ability-cast", "ability-state"), "readers": ("tray-drop",),
     "streams": ("tray_drop", "ability_state"), "feeds": ("ability-child",),
     "opens": "any", "joins": False, "ends": None,
     "kind": "the tray slot of the player's kit",
     "agent_claim": "depends_on the self slot's verdict",
     "position": "the self slot's belief at the cast", "effect": None},
    {"witness": "spectated_kit_drop", "parent": "the spectated teammate's slot",
     "wired": True,
     "owners": ("tray-kit",), "readers": ("tray-icon", "tray-drop"),
     "streams": ("tray_kit", "tray_kit_identity", "tray_drop"), "feeds": ("ability-child",),
     "opens": "any", "joins": False, "ends": None,
     "kind": "the spectated kit's slot", "agent_claim": "channel tray_kit",
     "position": "the spectated slot's belief", "effect": None},
    {"witness": "ult_line", "parent": "the caster's slot, by the template's class and side",
     "wired": True,
     "owners": ("ult-cast",), "readers": ("ult-line",),
     "streams": ("ult_cast", "ult_cast_identity", "ult_line"), "feeds": ("ability-child",),
     "opens": "any", "joins": True, "ends": None,
     "kind": "the template's class", "agent_claim": "channel ult_line",
     "position": None, "effect": None},
    {"witness": "smoke_track", "parent": "the caster's slot, by the smoke rule",
     "wired": True,
     "owners": ("minimap-smoke", "smoke-owner"), "readers": ("minimap-dark",),
     "streams": ("smoke", "smoke_owner", "smoke_owner_identity", "minimap_dark"),
     "feeds": ("ability-child",),
     "opens": "team", "joins": True, "ends": "an observed end",
     "kind": "the smoke rule's agent and slot", "agent_claim": "channel smoke_owner",
     "position": "the disc", "effect": None},
    {"witness": "glyph_track", "parent": "unknown at the open; the caster's slot or a spawned object, bound later",
     "wired": True,
     "owners": ("ability-glyph-name", "ability-disc-track"),
     "readers": ("ability-icon", "ability-glyph"),
     "streams": ("ability_glyph_name", "ability_glyph_identity", "ability_disc_track",
                 "ability_icon", "ability_glyph"),
     "feeds": ("ability-child",),
     "opens": "any", "joins": True, "ends": "the verify's loss where the disc would show",
     "kind": "the verdict key", "agent_claim": "channel minimap_glyph",
     "position": "the track", "effect": None},
    {"witness": "shape_fit", "parent": "unknown at the open; bound later",
     "wired": True,
     "owners": ("ability-shape", "ability-gate"), "readers": ("ability-candidates",),
     "streams": ("ability_fit", "ability_wall", "ability_shape", "ability_gate"),
     "feeds": ("ability-child",),
     "opens": "any", "joins": True, "ends": "the fit's absence where it would show",
     "kind": "the descriptor", "agent_claim": None,
     "position": "the fit", "effect": None},
    {"witness": "dead_clove_circle", "parent": "the dead Clove's slot",
     "wired": True,
     "owners": ("clove-circle",), "readers": (),
     "streams": ("clove_circle",), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": None,
     "kind": None, "agent_claim": "channel dead_clove_circle (through smoke-owner)",
     "position": "the circle's centre bounds the disc", "effect": None},
    {"witness": "killfeed_ability_kill", "parent": "the killer's live node of that ability, else the killer's slot",
     "wired": True,
     "owners": ("killfeed-weapon",), "readers": ("killfeed-weapon-descriptor",),
     "streams": ("killfeed_weapon", "death"), "feeds": ("ability-child", "ability-effect"),
     "opens": "if_none_live", "joins": True, "ends": None,
     "kind": "the weapon verdict", "agent_claim": "depends_on the killer verdict",
     "position": None, "effect": "a kill, on the victim"},
    {"witness": "assist_icon", "parent": "the assister's live node of that ability, else the assister's slot",
     "wired": True,
     "owners": ("kill-assists",), "readers": ("killfeed-assist-panel",),
     "streams": ("assist", "killfeed_assist"), "feeds": ("ability-child", "ability-effect"),
     "opens": "team_if_none_live", "joins": True, "ends": None,
     "kind": "the icon's ability", "agent_claim": "depends_on the assister verdict",
     "position": None, "effect": "an assist, on the victim"},
    {"witness": "own_ability_audio", "parent": "the self slot",
     "wired": True,
     "owners": ("ability-audio",), "readers": (), "streams": (), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": None,
     "kind": "the scored slot", "agent_claim": None, "position": None, "effect": None},
    {"witness": "device_destroyed", "parent": "the destroyed node's own parent, unchanged",
     "wired": False,
     "owners": (), "readers": (), "streams": (), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": "destroyed by the enemy",
     "kind": None, "agent_claim": None, "position": None, "effect": None},
    {"witness": "others_ability_audio", "parent": "unknown; bound later",
     "wired": False,
     "owners": (), "readers": (), "streams": (), "feeds": ("ability-child",),
     "opens": None, "joins": True, "ends": None,
     "kind": "the class", "agent_claim": None, "position": None, "effect": None},
)

#: The lanes ability entities reach consumers through (section 2.9): the
#: child owner's, and the kit owner's. Any other ability lane is ABILITY debt.
ABILITY_LANES = {"ability": "children and effects (`ability-child`, `ability-effect`); "
                            "built in step 2",
                 "ability_tray": "the kit (`ability-state`)"}


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
    in_reach = np.isin(k, (REACH, CROWD, FIT_UNNAMED)) & (d_an <= R + tol)
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
                    np.where(np.isin(k, (FIT, REACH)), np.pi * R ** 2, np.nan)))


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
    pl = L.get("player") or {}
    return {"slots": slots, "player_slot": pl.get("slot"), "player_agent": pl.get("agent"),
            "lineup_version": L.get("version")}


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


def player_lifecycle(S: StoredRows, slots: list[dict]) -> dict:
    """(5, F) open mask of the player slots from rounds and the death owner's
    verdicts, plus the events that set it."""
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
    for d in sorted((d for d in S.deaths if d.get("side") == "ally"), key=lambda d: d["t_ms"]):
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
    E = stack_entities([{"rows": player_rows(L["slots"]), "open": life["open"],
                         "X": bind["X"], "Y": bind["Y"], "has": bind["has"], "wit": wit,
                         "obs": bind["obs"]}])
    B = beliefs(S.fr_t, E["X"], E["Y"], E["has"], E["open"], life["seg_start"],
                r_fit=r_fit, r_icon=r_icon, v_max=v_max, wit=E["wit"])
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
                 "spectate_witness": extra["spect"].get("version")} if binding == "causal" else {})}
    return {"session": sid, "rows": E["rows"], "S": S, "L": L, "mf": mf, "to_m": to_m,
            "m_per_px": m_per_px, "t_ms": S.fr_t, "life": life,
            "windows": round_windows(S.fr_t, life["starts"]), "bind": bind, "B": B, "rec": rec,
            "binding": binding, **extra, "params": params, "stamp": stamp,
            "cost": {"frames": int(F), "load_cpu_s": round(load_s, 2),
                     "lifecycle_us_per_frame": round((t1 - t0) / F * 1e6, 2),
                     "bind_us_per_frame": round((t2 - t1) / F * 1e6, 2),
                     "beliefs_us_per_frame": round((t3 - t2) / F * 1e6, 2),
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
    and an anchored `fit_unnamed`). A missing disc is NaN; `unanchored` is
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
    reach = np.isin(k, (REACH, CROWD, FIT_UNNAMED)) & np.isfinite(R)
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
    deaths = [d for d in _jsonl(root / "events" / "death" / f"{sid}.jsonl")
              if d.get("kind") == "death_verdict"]
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
    rests_on = (f"slot_state.GateBelief {st['gate_belief_version']} ({st['slot_state_version']}) "
                f"over death {st['inputs']['death']}, lineup {st['inputs']['lineup']}, "
                f"rounds {st['inputs']['rounds']}",
                f"death verdicts {st['inputs']['death']} (cue)",
                f"minimap_object enemy icons {ver} (cue)" if enemy is not None
                else "minimap_object: not stored (no enemy cue)")
    return AllyGate(got["belief"], got["deaths_t"], enemy, rests_on)


# ----------------------------------------------------------------- storage

def l2_path(sid: str, store_root: Path = DEFAULT_STORE) -> Path:
    return Path(store_root) / "l2" / "slot_state" / f"{sid}.npz"


def write_record(G: dict, store_root: Path = DEFAULT_STORE) -> Path:
    """Store the per-frame record at `<store>/l2/slot_state/<session>.npz`
    with its stamp, written beside and moved into place whole."""
    p = l2_path(G["session"], store_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = frame_record(G["B"], G["bind"]["obs"], G["t_ms"])
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, rec=rec, t_ms=G["t_ms"].astype("f8"),
                        frame_idx=G["S"].fr_f.astype("i4"), open=G["life"]["open"],
                        keys=np.asarray([f"{r.kind}|{r.id}" for r in G["rows"]]),
                        stamp=np.asarray(json.dumps(G["stamp"], default=str)))
    tmp.replace(p)
    return p


def slot_summary(G: dict) -> dict:
    """Counts a command prints: belief kinds over open entity-frames, the
    lifecycle and binding counts, and the cost."""
    k = G["B"]["kind"]
    op = k != CLOSED
    return {"session": G["session"], "version": SLOT_STATE_VERSION, "binding": G["binding"],
            "frames": int(k.shape[1]), "entities": len(G["rows"]),
            "open_share": round(float(op.mean()), 4),
            "kinds": {KINDS[int(v)]: int((k[op] == v).sum()) for v in np.unique(k[op])},
            "lifecycle": G["life"]["counts"], "binding_counts": G["bind"]["counts"],
            "cost": G["cost"]}


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
