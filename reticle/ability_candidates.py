r"""Which abilities, with which parameters, could be drawn on a minimap crop.

Owns [owns:ability-candidates].

Why. The finders in `ability_shapes` are parameterised functions: each takes
one descriptor (shape, drawn sizes in px, colour model, prior) and knows
nothing else. This module is the rest of the pipeline that feeds them. It
names the set a crop's context allows -- the abilities of the match's ten
agents, on the side each fields, whose caster could still draw at that time
-- and why each other candidate was left out. Code that scores against a
candidate set names it; the full set is the surprise path (AGENTS.md,
"Continue the prior"), which `ability_scan` runs where no candidate fits.

The table. `TABLE` holds one entry per ability whose minimap drawing has a
measured appearance fact. Every number a finder reads comes from that fact's
`values` in `domain/abilities.toml`, as base pixels at
`geometry.SCALE_REF_KEY`; `ability_descriptor` turns them into px with the key's
`geometry.map_scale`. Pipeline tolerances (radius window, width band,
acceptance) stay beside the finders, per shape. A field with no fact makes
that ability's descriptor refuse with the reason; it never borrows another
ability's value [domain:abilities/ability-rules-are-unique]:

| Ability | Shape | Prior | Sizes | Fact |
|---|---|---|---|---|
| Regrowth | ring round Skye | caster | radius per map | [domain:abilities/skye-regrowth-minimap-ring-size] |
| Recon Bolt | ring at the landing | free | radius per map | [domain:abilities/sova-recon-bolt-minimap-ring-size] |
| Hunter's Fury | line from Sova | caster | width | [domain:abilities/sova-hunters-fury-minimap-beam-size] |
| Barrier Orb | four segments on a line | free | length, pieces, width | [domain:abilities/sage-barrier-orb-minimap-size] |
| Blaze | smooth curve | free | width, length range | [domain:abilities/phoenix-blaze-minimap-size] |
| Lockdown | ring round the device | free | radius per map, enemy colour only | [domain:abilities/killjoy-lockdown-enemy-minimap-ring] |

Colour follows the side [domain:minimap/ability-drawing-colour-by-side], and
each side's model is measured per ability: every fact above measures the ally
colour only but Lockdown's, which measures the enemy colour only, so the
ally Lockdown refuses `no_ally_colour` and every other enemy descriptor
`no_enemy_colour`. The Barrier
Orb's enemy wall is red-themed [domain:abilities/sage-barrier-orb-global-minimap]
and unmeasured. A radius measured on no map of this key refuses
`no_radius_on_map`: the radii differ by 7-8% between maps after the transform,
and that spread is not a window to widen.

`ICONS` holds the icon descriptors the facts give -- glyph, whether the look
changes with the side, facing style -- with a reason on every field no fact
states. They are data for a classifier the icon proposer (`ability_icons`)
does not have; the proposer names no ability.

The inputs, each asked of its owner:

- the lineup: `lineup.load_lineup` (the arbiter's side verdicts, the board's
  constraint) and `adjudication.identity.side_candidates` per side. A named
  slot's agent is a candidate. An unread slot -- refused, with or without a
  best guess -- is open: the witness that guessed refused the guess, so the
  guess does not bound the slot (c62c2b06bcfb's raw enemy slot 4 guessed
  Astra; the board names Killjoy). A team fields each agent once
  [domain:rounds/agent-uniqueness], so an open slot allows every agent the
  side has not named: that set is the surprise set, justified by the unread
  slot, and each candidate it adds says so (`open_slot`) with the slots'
  stored reasons.
- who is alive: `adjudication.death.build_match_roster_timeline` over the stored
  `death` verdicts and the stored rounds. No ability is cast while its owner
  is dead, except Clove's [domain:abilities/no-cast-while-dead]; a drawing
  made before the death persists or not per ability. Regrowth is channelled
  [domain:abilities/skye-regrowth-channelled] and so ends with Skye; every
  other entry's persistence is unasked, so a dead caster's candidate stays
  and says so (`caster_alive: false`).
- the self seed: the stored self position (`ability_shapes.seed_from_track`)
  seeds a caster-prior candidate whose agent is the player's
  (`lineup.load_lineup`'s `player`, the arbiter's answer).
- the transform: `geometry.map_scale_of`.

Every candidate carries `rests_on` these inputs, so a fit scored against it
is never counted again as an independent witness of the lineup or the
deaths. The descriptor names an ability and its caster's agent; the name of
the caster of any drawing stays the arbiter's (`adjudication.identity`,
`ability-owner`).

Not for. Fitting (`ability_shapes`); the gate (`ability_scan`); tracks,
lifecycles and owners (`adjudication.ability`, the arbiter); the self tray's
cast times as a window (not supplied yet).
"""
from __future__ import annotations

from . import ability_shapes as shapes
from .domain import load as load_facts
from .geometry import MapScale
from .version import ABILITY_CANDIDATES_VERSION

#: One entry per ability with a measured drawing: its caster, shape, prior,
#: the appearance fact holding its values, the facts that say it is drawn, and
#: whether a drawing outlives its caster (value, fact; None is unasked).
TABLE = {
    "Regrowth": {"agent": "Skye", "shape": "ring", "prior": "caster",
                 "size": "abilities/skye-regrowth-minimap-ring-size",
                 "draws": ("abilities/skye-regrowth-minimap-ring",),
                 "persists_after_death": (False, "abilities/skye-regrowth-channelled")},
    "Recon Bolt": {"agent": "Sova", "shape": "ring", "prior": "free",
                   "size": "abilities/sova-recon-bolt-minimap-ring-size",
                   "draws": ("abilities/sova-recon-bolt-minimap-ring",),
                   "persists_after_death": (None, "unasked")},
    "Hunter's Fury": {"agent": "Sova", "shape": "beam", "prior": "caster",
                      "size": "abilities/sova-hunters-fury-minimap-beam-size",
                      "draws": ("abilities/sova-hunters-fury-minimap-beam",),
                      "persists_after_death": (None, "unasked")},
    "Barrier Orb": {"agent": "Sage", "shape": "segments", "prior": "free",
                    "size": "abilities/sage-barrier-orb-minimap-size",
                    "draws": ("abilities/sage-barrier-orb-segments",
                              "abilities/sage-barrier-orb-whole-before-break"),
                    "persists_after_death": (None, "unasked")},
    "Blaze": {"agent": "Phoenix", "shape": "curve", "prior": "free",
              "size": "abilities/phoenix-blaze-minimap-size",
              "draws": ("abilities/phoenix-blaze",),
              "persists_after_death": (None, "unasked")},
    "Lockdown": {"agent": "Killjoy", "shape": "ring", "prior": "free",
                 "size": "abilities/killjoy-lockdown-enemy-minimap-ring",
                 "draws": ("abilities/killjoy-lockdown-global-minimap",),
                 "persists_after_death": (None, "unasked")},
}

#: Icon descriptors from facts: glyph per side, whether the look changes with
#: the side, and the facing style. None carries its reason beside it.
ICONS = {
    "Leer": {"agent": "Reyna",
             "glyph": {"ally": "white minus on a dark icon", "enemy": "white iris with a red "
                       "vertical pupil inside a red circle"},
             "side_look": "changes",
             "facing": None, "facing_reason": "no fact states a facing",
             "facts": ("abilities/reyna-leer-minimap-icon",
                       "abilities/reyna-leer-enemy-minimap-glyph")},
    "Prowler": {"agent": "Fade",
                "glyph": {"ally": "white arrow on a dark teal-rimmed icon", "enemy": None},
                "glyph_reason": {"enemy": "no fact gives the enemy icon"},
                "side_look": None, "side_look_reason": "the enemy icon is unrecorded",
                "facing": "the white arrow glyph points the way it moves",
                "facts": ("abilities/fade-prowler-minimap-icon",)},
    "Guiding Light": {"agent": "Skye",
                      "glyph": {"ally": "white bird on a dark teal-rimmed icon", "enemy": None},
                      "glyph_reason": {"enemy": "no fact gives the enemy icon"},
                      "side_look": None, "side_look_reason": "the enemy icon is unrecorded",
                      "facing": None, "facing_reason": "no fact states a facing",
                      "facts": ("abilities/skye-guiding-light-minimap-icon",)},
    "FLASH/drive": {"agent": "KAY/O",
                    "glyph": {"ally": "white spiky glyph on a dark icon", "enemy": None},
                    "glyph_reason": {"enemy": "no fact gives the enemy icon"},
                    "side_look": None, "side_look_reason": "the enemy icon is unrecorded",
                    "facing": None, "facing_reason": "no fact states a facing",
                    "facts": ("abilities/kayo-flashdrive-minimap-icon",)},
    "Trailblazer": {"agent": "Skye",
                    "glyph": {"ally": None, "enemy": "white dog on a near-black disc inside a "
                              "red ring with a red lobe"},
                    "glyph_reason": {"ally": "no fact gives the ally icon"},
                    "side_look": None, "side_look_reason": "the ally icon is unrecorded",
                    "facing": None, "facing_reason": "the lobe is the enemy icon's; no fact "
                                                     "says it faces",
                    "facts": ("abilities/skye-trailblazer-enemy-minimap-glyph",)},
}

#: The agents whose drawings never end with their death: a dead Clove still
#: casts [domain:abilities/no-cast-while-dead].
CASTS_WHILE_DEAD = ("Clove",)

_FACTS: dict | None = None


def facts() -> dict:
    global _FACTS
    if _FACTS is None:
        _FACTS = load_facts()
    return _FACTS


def map_of(ms: MapScale | None) -> str | None:
    """The map a baked key draws (`<map>__<profile>`)."""
    return None if ms is None or not ms.key else ms.key.split("__")[0]


def ability_descriptor(ability: str, side: str, ms: MapScale, map_name: str | None = None,
               fact_table: dict | None = None) -> dict:
    """`ability`'s descriptor on `side` in this key's px, or one that refuses.

    `map_name` defaults to the key's map. The values are the fact's; the
    tolerances are the finder's (`ability_shapes`)."""
    fact_table = fact_table or facts()
    t = TABLE.get(ability)
    d = {"id": f"{ability}:{side}", "ability": ability, "side": side,
         "agent": None if t is None else t["agent"],
         "shape": None if t is None else t["shape"],
         "prior": None if t is None else t["prior"]}
    if t is None:
        return {**d, "refused": "no_appearance_fact"}
    f = fact_table.get(t["size"])
    d["facts"] = [t["size"], *t["draws"]]
    if f is None or not f.values:
        return {**d, "refused": f"no_appearance_fact: {t['size']}"}
    v = f.values
    hue = v.get(f"{side}_hue") or v.get(f"{side}_rim_hue")
    sat = v.get(f"{side}_sat_p10") or v.get(f"{side}_rim_sat_p10")
    if hue is None or sat is None:
        return {**d, "refused": f"no_{side}_colour: {t['size']} measures no {side} colour"}
    d["colour"] = shapes.colour_model(hue, sat)
    map_name = map_name or map_of(ms)
    if t["shape"] == "ring":
        r = (v.get("base_radius") or {}).get(map_name)
        if r is None:
            return {**d, "refused": f"no_radius_on_map: {t['size']} measures none on {map_name}"}
        d["radius_px"] = ms.px(r)
    elif t["shape"] == "beam":
        d["width_px"] = ms.px(v["base_width"])
        d["geo"] = shapes.beam_geometry(d["width_px"], ms)
    elif t["shape"] == "segments":
        d["length_px"] = ms.px(v["base_length"])
        d["pieces_px"] = [ms.px(p) for p in v["base_pieces"]]
        d["width_px"] = ms.px(v["base_width"])
    elif t["shape"] == "curve":
        d["width_px"] = ms.px(v["base_width"])
        d["length_px"] = [ms.px(p) for p in v["base_length"]]
    return d


# ------------------------------------------------------------------ supply

def _death_verdicts(rows: list[dict]) -> dict[int, list]:
    """The stored death verdicts per round, as the death owner's own objects.

    A verdict whose side is neither ally nor enemy changes neither side's
    living five, and the death owner's tracker has no roster for it, so it is
    left out here and counted by `for_session` (`death_unknown_side`)."""
    from .adjudication.death import DeathVerdict
    out: dict[int, list] = {}
    for r in rows:
        if r.get("kind") != "death_verdict" or r.get("side") not in ("ally", "enemy"):
            continue
        out.setdefault(int(r["round_no"]), []).append(DeathVerdict(
            death_id=r["death_id"], t_ms=float(r["t_ms"]), side=r["side"],
            victim=r.get("victim"), status=r.get("status", "abstained"),
            is_second_life=bool(r.get("is_second_life")), is_revive=bool(r.get("is_revive"))))
    return out


class CandidateSupply:
    """The candidate set of one session at any sample time.

    Built by `for_session` from stored data only. `at(t_ms)` returns the
    candidate descriptors, the exclusions with their reasons, and the seed
    each caster-prior candidate of the player takes."""

    def __init__(self, session_id: str, ms: MapScale, sides: dict, player: str | None,
                 snapshots: list, round_starts: list, seed_at=None, rests_on: dict | None = None,
                 fact_table: dict | None = None):
        self.session_id, self.ms, self.sides, self.player = session_id, ms, sides, player
        self.snapshots = snapshots
        self.round_starts = round_starts
        self.seed_at = seed_at
        self.rests_on = dict(rests_on or {})
        self.fact_table = fact_table or facts()
        self._desc: dict = {}

    @property
    def stamp(self) -> dict:
        """What a stream built from this supply records of it."""
        return {"ability_candidates_version": ABILITY_CANDIDATES_VERSION, **self.rests_on}

    def _alive(self, t_ms: float) -> dict[str, set[str] | None]:
        """The living agents per side at `t_ms` (None where no timeline holds)."""
        snap = None
        for s in self.snapshots:
            if s.t_ms <= t_ms:
                snap = s
            else:
                break
        if snap is None:
            return {"ally": None, "enemy": None}
        return {"ally": set(snap.ally_agents), "enemy": set(snap.enemy_agents)}

    def descriptor(self, ability: str, side: str) -> dict:
        k = (ability, side)
        if k not in self._desc:
            self._desc[k] = ability_descriptor(ability, side, self.ms, fact_table=self.fact_table)
        return self._desc[k]

    def at(self, t_ms: float) -> dict:
        alive = self._alive(t_ms)
        cands, excluded = [], []
        for side in ("ally", "enemy"):
            sc = self.sides.get(side) or {}
            named, rivals, blind = sc.get("named", []), sc.get("rivals", []), sc.get("blind", [])
            n_open = len(rivals) + len(blind)
            for ability, t in TABLE.items():
                agent = t["agent"]
                if agent not in named and not n_open:
                    excluded.append({"ability": ability, "side": side, "agent": agent,
                                     "reason": "not_in_lineup"})
                    continue
                why = "named" if agent in named else _open_why(sc, n_open, agent in rivals)
                living = alive[side]
                caster_alive = None if living is None or agent not in set(named) else agent in living
                persists, pfact = t["persists_after_death"]
                if caster_alive is False and persists is False and agent not in CASTS_WHILE_DEAD:
                    excluded.append({"ability": ability, "side": side, "agent": agent,
                                     "reason": f"caster_dead: {pfact} ends it with the caster"})
                    continue
                d = dict(self.descriptor(ability, side))
                d["selected"] = why
                d["caster_alive"] = caster_alive
                if caster_alive is False:
                    d["persistence"] = pfact
                if d.get("refused"):
                    excluded.append({"ability": ability, "side": side, "agent": agent,
                                     "reason": d["refused"]})
                    continue
                d["seed"] = None
                if (t["prior"] == "caster" and side == "ally" and agent == self.player
                        and self.seed_at is not None):
                    d["seed"] = self.seed_at(t_ms)
                d["rests_on"] = sorted(self.rests_on)
                cands.append(d)
        return {"candidates": cands, "excluded": excluded}


def _open_why(sc: dict, n_open: int, guessed: bool) -> str:
    """Why an agent the side has not named is a candidate: an open slot."""
    got = list(sc.get("open_reasons") or [])
    if len(got) < n_open:
        got.append(f"{n_open - len(got)} slot(s) with no stored row or reason")
    reasons = "; ".join(got)
    return (f"open_slot: {n_open} slot(s) unread ({reasons}); a team fields each agent "
            f"once, so any agent the side has not named may hold one"
            + ("; the refused best guess" if guessed else ""))


def open_reasons(rows) -> list[str]:
    """Each unread lineup slot's stored refusal, as `slot N: reason`."""
    return [f"slot {r.get('slot')}: {r.get('reason') or 'no reason stored'}"
            + (f" (best guess {r['best_guess']})" if r.get("best_guess") else "")
            for r in rows if not r.get("agent")]


def for_session(session_id: str, store, ms: MapScale | None = None, seed_at=None):
    """The session's `CandidateSupply`, or (None, reason) where an input is
    missing. Pure over stored data: the lineup, the death verdicts, the rounds
    and the baked geometry."""
    from . import geometry
    from .adjudication.death import build_match_roster_timeline
    from .adjudication.identity import side_candidates
    from .lineup import load_lineup
    ms = ms or geometry.map_scale_of(session_id, store.root)
    if ms is None:
        return None, "no_map_scale"
    lineup = load_lineup(session_id, store.root)
    if lineup is None:
        return None, "no_lineup"
    sides = {side: {**side_candidates(rows), "open_reasons": open_reasons(rows)}
             for side, rows in (lineup.get("sides") or {}).items()}
    player = (lineup.get("player") or {}).get("agent")
    rows = store.read_events("death", session_id)
    if not rows:
        return None, "no_death_verdicts"
    head = next((r for r in rows if r.get("kind") == "summary"), {})
    man = store.read_manifest(session_id)
    table = store.read_rounds(session_id, man["ingested_at"][:10])
    if table is None:
        return None, "no_rounds"
    rounds = table.to_pylist()
    by = _death_verdicts(rows)
    revives = {}
    for r in rows:
        if (r.get("kind") == "death_verdict" and r.get("is_revive") and r.get("victim")
                and r.get("side") in ("ally", "enemy")):
            revives.setdefault(int(r["round_no"]), []).append(
                {"t_ms": float(r["t_ms"]), "side": r["side"], "agent": r["victim"]})
    info = [{"round_no": int(r["round_no"]), "t_start_ms": float(r["t_start_ms"]),
             "death_verdicts": [v for v in by.get(int(r["round_no"]), []) if not v.is_revive],
             "revives": revives.get(int(r["round_no"]), [])} for r in rounds]
    snaps = build_match_roster_timeline(lineup, info)
    rests_on = {"lineup": lineup.get("version"), "death": head.get("death_adjudication_version"),
                "death_unknown_side": sum(r.get("kind") == "death_verdict"
                                          and r.get("side") not in ("ally", "enemy") for r in rows),
                "rounds": rounds[0].get("round_version") if rounds else None,
                "map_scale": ms.key, "seed": "stored self position" if seed_at else None}
    return CandidateSupply(session_id, ms, sides, player, snaps,
                           [float(r["t_start_ms"]) for r in rounds], seed_at, rests_on), None


def values_digest(fact_table: dict | None = None) -> str:
    """A short hash of every TABLE fact's values: a stream built from the
    descriptors records it, so a remeasured fact makes it stale."""
    import hashlib
    import json
    fact_table = fact_table or facts()
    got = {t["size"]: getattr(fact_table.get(t["size"]), "values", None) for t in TABLE.values()}
    return hashlib.sha1(json.dumps(got, sort_keys=True).encode()).hexdigest()[:12]


__all__ = ["TABLE", "ICONS", "ability_descriptor", "CandidateSupply", "for_session", "values_digest",
           "map_of"]
