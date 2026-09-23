"""Match identity: which named agent every entity is, decided in one place.

Readers do not name entities.  They publish claims, and this module is the
single owner that turns claims about one entity into a canonical answer.  A
claim may abstain; an abstention is not a disagreement.  Conflicting names
remain unresolved with both witnesses attached.

**Every name in the match passes through here.** That covers the icon,
track, killfeed portrait, scoreboard row, death victim and ability owner.
Downstream owners bind an entity -- `death` decides WHICH death a witness
speaks about -- and then ask this module for the name with their own entity
key. `death` once kept its own copy of the cross-channel rule, missing
`binding_from`, and the scoreboard named rows without publishing claims.
Nothing failed, so nothing caught it. Identity events now come only from
`identity_events`, which the event validator and `doctor`'s IDENTITY check
enforce.

Two stages, both here:

* **per entity** -- `adjudicate_agent_identity` over `identity_claim`s;
* **per side** -- `assign_side`, the five-distinct-agents assignment
  [domain:rounds/agent-uniqueness]. A side's lineup is identity of the match
  as a whole rather than of one entity, and its constraint breaks ties that
  no single entity's evidence can.

It does not read frames, track icons, or infer a persistent entity key.
Callers must provide that key, so a packed roster slot cannot silently become
a player.

Owns [owns:agent-identity].
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import glob
from pathlib import Path

import cv2
import numpy as np

from .. import appearance
from ..roster import N_SLOTS
from ..track import assign


AGENT_IDENTITY_VERSION = "agent-identity-0.2.0"

#: Borrowed from `lineup.MARGIN_MIN` and NOT refitted here. It keeps every
#: correct player portrait on the one population with a truth --
#: [metric:killfeed/portrait-gate#correct_at_gate=210] of
#: [metric:killfeed/portrait-gate#truth_portraits=210], whose thinnest correct
#: margin is [metric:killfeed/portrait-gate#min_margin_correct=0.078] -- and it
#: refuses [metric:killfeed/portrait-gate#refused_for_margin=173] of
#: [metric:killfeed/portrait-gate#portraits=392] portraits overall, where no
#: truth says whether that is right. Untested on the other nine players.
PORTRAIT_MARGIN_MIN = 0.07

#: The surface the killfeed actually draws, and the gallery both measured runs
#: used: `killfeed/portrait-identity` and `killfeed/portrait-stability` each
#: record `deps.gallery = "killfeed_portrait art, 29 agents"`. Scoring a
#: killfeed portrait against agent-icon and minimap art as well, and keeping
#: the best, changed the top match on 63 of 388 portraits -- a different rule
#: from the one the 93/93 rests on, and one whose winning surface varies per
#: agent, so the two scores a margin subtracts come from different drawings.
#: The side assignment's margin gate, fitted on one five-slot lineup and
#: provisional; `lineup`'s docstring carries the measurement.
SIDE_MARGIN_MIN = 0.07

MEASURED_SURFACES = ("killfeed_portrait",)
MINIMAP_SURFACES = ("minimap_portrait",)


def identity_claim(entity_id, agent=None, *, channel, observed_at_ms=None,
                   reason=None, source_version=None, evidence=None,
                   binding_from=None, depends_on=None) -> dict:
    """Return one normalized, provenance-carrying identity claim.

    ``agent=None`` is an explicit abstention.  The arbiter never turns a
    missing name into an unknown agent or drops the reason for refusing.

    ``binding_from`` names the channel this claim took its ENTITY from, when
    that is a different channel from the one that read the name.  It is the
    difference between two witnesses and one witness counted twice; see
    `adjudicate_agent_identity`.  ``reason`` is kept whatever the claim says,
    because a named claim can still carry how it was named.

    ``depends_on`` lists the entity ids whose OWN verdicts this claim used to
    reach its name -- naming one death by eliminating the others' names is the
    case. Such a claim can still disagree, so it is not ``binding_from``, but
    it is not independent evidence either and is not counted as such.
    """
    if not channel:
        raise ValueError("identity claims need a channel")
    if agent is not None and not str(agent):
        raise ValueError("an identity name must be non-empty or None")
    return {
        "entity_id": entity_id,
        "agent": agent,
        "channel": channel,
        "observed_at_ms": observed_at_ms,
        "reason": reason,
        "source_version": source_version,
        "binding_from": binding_from,
        "depends_on": sorted(depends_on) if depends_on else [],
        "evidence": deepcopy(evidence) if evidence is not None else {},
    }


def claims_from_lineup(sides, player=None, *, observation_id="lineup",
                       source_version=None) -> list[dict]:
    """Publish lineup, tray and self-icon witnesses as independent claims.

    The slot key is explicitly scoped to this lineup observation.  It is not a
    persistent player id: a later roster/track pass must supply that relation
    before these claims can be joined across time.
    """
    version = source_version or "lineup"
    out = []
    for side in ("ally", "enemy"):
        for row in sides.get(side, []):
            slot = row.get("slot")
            if slot is None:
                continue
            entity_id = f"{observation_id}:{side}:slot:{slot}"
            out.append(identity_claim(
                entity_id, row.get("agent"), channel="top_bar",
                reason=row.get("reason"), source_version=version,
                evidence={"side": side, "slot": slot,
                          "margin": row.get("margin"),
                          "best_guess": row.get("best_guess")},
            ))

    # The player result identifies the same ally slot through two witnesses
    # that answer a different question from the top bar.  Emit the witness
    # that actually decided, not a global self-icon argmax that may be an enemy
    # agent outside the ally roster.
    #
    # **The SLOT comes from the top bar either way**, and that is why the claim
    # says so.  `Lineup.player` finds the tray's agent by searching the top
    # bar's own rows for that name, and ranks the self icon among the five the
    # top bar proposed, so neither witness can contradict the top bar at the
    # slot it is attached to.  The name is independent evidence; the binding is
    # not, and counting it as a second channel would report corroboration that
    # the construction guarantees.
    if player and player.get("agent") is not None and player.get("slot") is not None:
        entity_id = f"{observation_id}:ally:slot:{player['slot']}"
        decided_by = player.get("decided_by")
        channel = ("ability_tray" if decided_by == "ability_tray"
                   else "self_icon" if decided_by == "self_icon_among_top_bar_candidates"
                   else "player_identity")
        out.append(identity_claim(
            entity_id, player["agent"], channel=channel,
            source_version=version, binding_from="top_bar",
            evidence={"slot": player["slot"],
                      "decided_by": decided_by,
                      "agree": player.get("agree"),
                      "witnesses": player.get("witnesses", {})},
        ))
    return out


def assign_side(scores, names: list[str], frames: int, side: str = "ally",
                margin_min: float = SIDE_MARGIN_MIN) -> list[dict]:
    """One row per slot of one side: the agent, its margin, and whether to believe it.

    Moved here from `lineup.adjudicate` on 2026-09-23: which five agents a side
    fields is match identity, decided by this module like every other name.
    `lineup` supplies the top bar's scores; any other surface that scores a
    whole side can supply its own.

    Pure over the per-frame (slot, agent) matrix, so a stored lineup can be
    re-adjudicated without opening the capture again.

    The five slots are five DIFFERENT agents, so this is an assignment and not
    five arg-maxes -- the same constraint the tracker uses on icons, for the
    same reason. A slot under the margin is `None` WITH its best guess kept
    beside it, because an unread value must say what it is.

    **Per SIDE, and never across the match**: [domain:rounds/agent-uniqueness].
    Both teams may field the same agent, so naming one on this side says
    nothing about the other -- a ten-slot assignment would have named 11
    refused slots wrongly across the stored lineups.

    **The margin is measured against the assignment, not against the raw
    ordering.** It is the optimal assignment's total score minus the best total
    attainable when this slot is FORBIDDEN its agent, so the alternative it is
    separated from is one the uniqueness constraint permits, and the
    displacement that alternative forces on the other four slots is paid for in
    the margin.

    The version this replaces compared `order[0]` with `order[1]` on the raw
    per-slot ordering, computed WITHOUT the assignment made two lines above it.
    Where the runner-up was near-tied but taken by another slot, the constraint
    had already resolved the tie and the slot was refused anyway -- 12 of 79
    refusals across 19 stored lineups. The count read as thin evidence and was
    a measurement taken in the wrong place.

    `best_guess` is the assignment's pick for the same reason. Reporting an
    argmax the constraint has already rejected is the original fault wearing a
    different field name.
    """
    s = np.asarray(scores, dtype=float)
    cost = [[-float(v) for v in row] for row in s]
    picked = assign(cost)
    best_total = sum(float(s[i, j]) for i, j in enumerate(picked) if j >= 0)
    out = []
    for i, j in enumerate(picked):
        margin, rival = 0.0, None
        if j >= 0:
            # Forbidding one cell and re-solving gives the best assignment in
            # which THIS slot differs -- the maximum over every alternative at
            # once, for one solve rather than one per candidate agent.
            blocked = [row[:] for row in cost]
            blocked[i][j] = float("inf")
            other = assign(blocked)
            margin = best_total - sum(float(s[k, c])
                                      for k, c in enumerate(other) if c >= 0)
            rival = names[other[i]] if other[i] >= 0 else None
        ok = j >= 0 and margin >= margin_min
        out.append({
            "slot": i, "side": side,
            "agent": names[j] if ok else None,
            "best_guess": names[j] if j >= 0 else names[int(np.argmax(s[i]))],
            "rival": rival,
            "score": round(float(s[i, j]) if j >= 0 else 0.0, 4),
            "margin": round(margin, 4),
            "frames": frames,
            "reason": None if ok else
                      f"margin {margin:.3f} below {margin_min} -- "
                      + (f"not separated from {rival}" if rival
                         else "no assignment"),
        })
    return out


#: A scoreboard row's best agent must lead its runner-up by this much, in
#: masked-correlation units. Measured on one round of `a06f04a0059f`: accepted
#: rows led by at least 0.30, misaligned rows by at most 0.23. Provisional.
BOARD_MARGIN_MIN = 0.25
#: Accepted openings that must agree before a side's set is believed.
BOARD_MIN_OPENINGS = 2


def board_side_sets(openings) -> dict[str, dict]:
    """Which five agents each side fields, from accepted scoreboard openings.

    Each accepted opening's five rows on a side are ASSIGNED with
    `assign_side` over every agent's stored score, not read as five argmaxes.
    A side's set is believed only when at least `BOARD_MIN_OPENINGS` openings
    name all five and every one of them names the same five; otherwise the
    side refuses with its reason and the per-opening sets stay on the row.
    Agents are fixed for the match, so openings from both halves count, and a
    disagreement between openings is a finding rather than a vote.
    """
    out = {}
    for side in ("ally", "enemy"):
        seen, missing = {}, 0
        for opening in openings:
            if not opening.get("accepted"):
                continue
            rows = [r for r in opening["rows"] if r["team"] == side]
            if len(rows) != N_SLOTS or any(not r.get("scores") for r in rows):
                missing += 1
                continue
            names = sorted(rows[0]["scores"])
            matrix = [[r["scores"].get(n, -1.0) for n in names] for r in rows]
            picked = assign_side(matrix, names, 1, side, margin_min=BOARD_MARGIN_MIN)
            if any(p["agent"] is None for p in picked):
                continue
            key = tuple(sorted(p["agent"] for p in picked))
            seen.setdefault(key, []).append(opening["t_ms"])
        row = {"agents": None, "openings": sorted(t for ts in seen.values() for t in ts),
               "sets": [{"agents": list(k), "openings": v} for k, v in sorted(seen.items())],
               "unscored_openings": missing, "reason": None}
        if len(seen) > 1:
            row["reason"] = "board_sets_disagree"
        elif not seen:
            row["reason"] = ("scores_not_stored" if missing else "no_accepted_opening")
        elif len(row["openings"]) < BOARD_MIN_OPENINGS:
            row["reason"] = f"only_{len(row['openings'])}_accepted_opening"
        else:
            row["agents"] = list(next(iter(seen)))
        out[side] = row
    return out


def lineup_with_board(lineup: dict, board: dict[str, dict]) -> dict:
    """The stored top-bar lineup with each side restricted to the board's set.

    Where the board names a side's five agents, the top bar's stored
    (slot, agent) matrix is re-assigned over those five only: the board says
    WHO is on the side, the top bar says WHICH SLOT. Every top-bar name the
    constraint changes or removes is stored in `board_disagreements`, and the
    unconstrained sides are kept under `top_bar_sides`. A side the board
    refuses keeps its top-bar verdict. Pure over stored data.
    """
    scores = lineup.get("scores") or {}
    names = scores.get("names")
    got = deepcopy(lineup)
    got["top_bar_sides"] = deepcopy(lineup.get("sides", {}))
    got["board"] = deepcopy(board)
    got["board_disagreements"] = []
    for side, row in board.items():
        if not row.get("agents") or not names or side not in scores:
            continue
        cols = [names.index(a) for a in row["agents"] if a in names]
        if len(cols) != N_SLOTS:
            continue
        matrix = np.asarray(scores[side], dtype=float)[:, cols]
        frames = int(lineup.get("frames") or 0)
        constrained = assign_side(matrix, [names[c] for c in cols], frames, side)
        for before, after in zip(got["top_bar_sides"].get(side, []), constrained):
            after["constrained_by"] = "scoreboard"
            if before.get("agent") and before["agent"] != after["agent"]:
                got["board_disagreements"].append({
                    "side": side, "slot": before.get("slot"),
                    "top_bar": before["agent"], "with_board": after["agent"],
                    "board_agents": row["agents"]})
        got.setdefault("sides", {})[side] = constrained
    claims = claims_from_lineup(got.get("sides", {}), got.get("player"),
                                observation_id=str(got.get("session", "lineup")),
                                source_version=got.get("version", "lineup"))
    got["identity_claims"] = claims
    got["agent_identity"] = adjudicate_agent_identity(claims)
    return got


def load_identity_gallery(store, surfaces=MEASURED_SURFACES) -> dict[str, list[np.ndarray]]:
    """Load official portrait descriptors in the killfeed feature space.

    The default is the surface that was measured; see `MEASURED_SURFACES`.
    Widening it is a different rule and needs its own before-and-after, which
    is why it is an argument and not a constant read from somewhere else.
    """
    art = Path(store) / "reference" / "assets" / "agents"
    gallery: dict[str, list[np.ndarray]] = {}
    for surface in surfaces:
        for path in sorted(glob.glob(str(art / f"*_{surface}.png"))):
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None or image.ndim != 3:
                continue
            stem = Path(path).stem
            suffix = f"_{surface}"
            name = stem[:-len(suffix)] if stem.endswith(suffix) else stem
            mask = (image[:, :, 3] > 128) if image.ndim == 3 and image.shape[2] == 4 else None
            descriptor = appearance.hsv_composition(image[:, :, :3], mask)
            if descriptor.size:
                gallery.setdefault(name, []).append(descriptor)
    return gallery


def _portrait_scores(composition, candidates, gallery):
    """Best official-art intersection for each agent admitted to the compare."""
    if composition is None:
        return {}
    observed = np.asarray(composition, dtype=np.float32).ravel()
    if not observed.size:
        return {}
    scores = {}
    for agent in sorted({c for c in candidates if c}):
        references = gallery.get(agent)
        if references is None:
            agent_lower = str(agent).lower()
            for g_name, g_refs in gallery.items():
                if str(g_name).lower() == agent_lower:
                    references = g_refs
                    break
            else:
                references = ()
        values = [float(np.minimum(observed, np.asarray(reference)).sum())
                  for reference in references
                  if np.asarray(reference).size == observed.size]
        if values:
            scores[agent] = max(values)
    return scores


def side_candidates(rows) -> dict:
    """Split one side's lineup rows into who may be named and who may not.

    **The alternative a portrait is separated from must be one the side can
    actually hold.** A refused lineup slot still holds an agent, and dropping
    it leaves that agent's portrait competing only against the four the lineup
    did name -- which names one of them, confidently, and wrongly.
    `assign_side` learned this from the other end: a margin measured
    against an inadmissible alternative is not a margin.

    So a refused slot enters the comparison as a RIVAL under its `best_guess`.
    It can take the match away and it can never take the name, because the
    witness that proposed it refused it. A refused slot with no guess at all is
    BLIND: nothing represents that agent, so no portrait on this side can be
    separated from it and every one of them must refuse.
    """
    named, rivals, blind = [], [], []
    for row in rows:
        agent = row.get("agent")
        if agent:
            named.append(agent)
            continue
        guess = row.get("best_guess")
        (rivals if guess else blind).append(guess or row.get("slot"))
    missing = max(0, N_SLOTS - len(rows))
    return {"named": named, "rivals": rivals,
            "blind": blind + [None] * missing,
            "slots": len(rows) + missing}


def claim_from_killfeed_portrait(observation, *, entity_id, candidates, gallery,
                                 rivals=(), source_version="killfeed-portrait",
                                 margin_min=PORTRAIT_MARGIN_MIN) -> dict:
    """Turn one stored killfeed portrait descriptor into an identity claim.

    ``candidates`` must come from the owning lineup observation. The open
    29-agent gallery is intentionally not used: the plate side is a constraint
    and the lineup is the independent witness that makes this portrait useful.
    ``rivals`` are admitted to the comparison and barred from the answer; see
    `side_candidates`. The descriptor stays in evidence when the match refuses.

    **A reader that already refused is quoted, never re-diagnosed.** The
    observation's own `reason` says what the pixels did -- no gap past the
    name, a band too short -- and computing a second reason here reports a thin
    margin for a portrait nothing ever described.
    """
    stored = str(observation.get("reason") or "").strip()
    evidence = {
        "role": observation.get("role"),
        "slot": observation.get("slot"),
        "ally": observation.get("ally"),
        "clipped": observation.get("clipped"),
        "detail": observation.get("detail"),
        "observation_reason": stored or None,
        "candidates": sorted({c for c in candidates if c}),
        "rivals": sorted({r for r in rivals if r}),
    }
    if stored or observation.get("composition") is None:
        return identity_claim(
            entity_id, None, channel="killfeed_portrait",
            reason=stored or "portrait_no_descriptor",
            source_version=source_version,
            observed_at_ms=observation.get("t_ms"), evidence=evidence)

    admitted = list(candidates) + list(rivals)
    scores = _portrait_scores(observation.get("composition"), admitted, gallery)
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    best = ordered[0] if ordered else (None, 0.0)
    runner = ordered[1] if len(ordered) > 1 else (None, 0.0)
    margin = best[1] - runner[1] if len(ordered) > 1 else 0.0
    evidence.update({
        "scores": {name: round(score, 6) for name, score in ordered},
        "best_guess": best[0],
        "margin": round(margin, 6),
    })

    barred = set(evidence["rivals"])
    if not ordered:
        reason = "portrait_no_comparable_candidate"
    elif best[0] in barred:
        # The portrait looks most like a slot the LINEUP could not name. This
        # is the honest refusal: the name exists and no witness stands behind
        # it.
        reason = f"portrait_best_is_refused_slot {best[0]}"
    elif len(ordered) == 1:
        # One admissible agent is a constraint result, not a separation. The
        # lineup already named it; the portrait adds nothing and says so.
        reason = "portrait_single_candidate"
    elif margin < margin_min:
        reason = f"portrait_margin {margin:.3f} below {margin_min}"
    else:
        reason = None
    return identity_claim(
        entity_id, best[0] if reason is None else None,
        channel="killfeed_portrait", reason=reason,
        source_version=source_version,
        observed_at_ms=observation.get("t_ms"), evidence=evidence)


def claims_from_killfeed_portraits(observations, lineup, *, entry_id, gallery,
                                   source_version="killfeed-portrait",
                                   margin_min=PORTRAIT_MARGIN_MIN) -> list[dict]:
    """Publish one constrained portrait claim per killfeed entry role.

    ``entry_id`` is supplied by the killfeed entry adjudicator and must remain
    stable across the consecutive frames of one entry. This function does not
    merge frames; `adjudicate_agent_identity` accumulates them when the claims
    share one ``entity_id``.
    """
    sides = lineup.get("sides", lineup)
    out = []
    for observation in observations:
        role = observation.get("role", "unknown")
        stored = str(observation.get("reason") or "").strip()
        side = ("ally" if observation.get("ally") is True else
                "enemy" if observation.get("ally") is False else None)
        if side is None:
            out.append(identity_claim(
                f"{entry_id}:{role}", channel="killfeed_portrait",
                reason=stored or "portrait_side_unknown",
                source_version=source_version,
                observed_at_ms=observation.get("t_ms"),
                evidence={"role": role, "slot": observation.get("slot"),
                          "observation_reason": stored or None,
                          "observation": observation},
            ))
            continue
        split = side_candidates(sides.get(side, []))
        if split["blind"] and not stored:
            out.append(identity_claim(
                f"{entry_id}:{role}", channel="killfeed_portrait",
                reason=(f"lineup_incomplete: {len(split['named'])} of "
                        f"{split['slots']} {side} slots named and "
                        f"{len(split['blind'])} propose no candidate"),
                source_version=source_version,
                observed_at_ms=observation.get("t_ms"),
                evidence={"role": role, "slot": observation.get("slot"),
                          "ally": observation.get("ally"),
                          "observation_reason": None,
                          "candidates": sorted(set(split["named"])),
                          "rivals": sorted({r for r in split["rivals"] if r})},
            ))
            continue
        out.append(claim_from_killfeed_portrait(
            observation, entity_id=f"{entry_id}:{role}",
            candidates=split["named"], rivals=split["rivals"], gallery=gallery,
            source_version=source_version, margin_min=margin_min))
    return out


def claim_from_minimap_icon(observation, *, entity_id, candidates, gallery,
                            rivals=(), source_version="minimap-portrait",
                            margin_min=PORTRAIT_MARGIN_MIN) -> dict:
    """Turn one stored minimap icon descriptor into an identity claim.

    ``candidates`` must come from the owning lineup observation. The candidate
    set is constrained to the lineup's side candidates (or rivals).
    If the icon is flagged as a question mark, or has an upstream refusal reason,
    an abstention claim is emitted quoting the reason.
    """
    stored = str(observation.get("reason") or "").strip()
    marked_kind = observation.get("marked_kind", observation.get("kind"))
    if not stored and (marked_kind == "question" or observation.get("is_question")
                       or str(observation.get("agent")).lower() == "question"):
        stored = "minimap_icon_question_mark"

    evidence = {
        "x": observation.get("x"),
        "y": observation.get("y"),
        "r": observation.get("r"),
        "track_id": observation.get("track_id"),
        "marked_kind": marked_kind,
        "observation_reason": stored or None,
        "candidates": sorted({c for c in candidates if c}),
        "rivals": sorted({r for r in rivals if r}),
    }

    comp = observation.get("composition")
    if comp is None:
        comp = observation.get("appearance")
    if comp is None and observation.get("crop") is not None:
        comp = appearance.hsv_composition(observation["crop"])
    elif comp is None and observation.get("patch") is not None:
        comp = appearance.hsv_composition(observation["patch"])

    has_comp = comp is not None and np.asarray(comp).size > 0
    has_scores = bool(observation.get("scores"))

    if stored or (not has_comp and not has_scores):
        return identity_claim(
            entity_id, None, channel="minimap_portrait",
            reason=stored or "icon_no_descriptor",
            source_version=source_version,
            observed_at_ms=observation.get("t_ms"), evidence=evidence)

    admitted = list(candidates) + list(rivals)
    if has_scores:
        raw_scores = observation["scores"]
        admitted_lower = {a.lower(): a for a in admitted}
        scores = {}
        for k, v in raw_scores.items():
            k_canon = admitted_lower.get(str(k).lower())
            if k_canon is not None:
                scores[k_canon] = float(v)
    else:
        scores = _portrait_scores(comp, admitted, gallery)

    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    best = ordered[0] if ordered else (None, 0.0)
    runner = ordered[1] if len(ordered) > 1 else (None, 0.0)
    margin = best[1] - runner[1] if len(ordered) > 1 else 0.0
    evidence.update({
        "scores": {name: round(score, 6) for name, score in ordered},
        "best_guess": best[0],
        "margin": round(margin, 6),
    })

    barred = set(evidence["rivals"])
    if not ordered:
        reason = "icon_no_comparable_candidate"
    elif best[0] in barred:
        reason = f"icon_best_is_refused_slot {best[0]}"
    elif len(ordered) == 1:
        reason = "icon_single_candidate"
    elif margin < margin_min:
        reason = f"icon_margin {margin:.3f} below {margin_min}"
    else:
        reason = None
    return identity_claim(
        entity_id, best[0] if reason is None else None,
        channel="minimap_portrait", reason=reason,
        source_version=source_version,
        observed_at_ms=observation.get("t_ms"), evidence=evidence)


def claims_from_minimap_icons(observations, lineup, *, gallery,
                              entity_key=None, side="enemy",
                              source_version="minimap-portrait",
                              margin_min=PORTRAIT_MARGIN_MIN) -> list[dict]:
    """Publish one constrained minimap icon claim per candidate sighting.

    ``entity_key`` determines the entity identity key attached to each claim:
    - If callable: called with ``observation`` to produce the key string.
    - If string: taken from ``observation.get(entity_key)``.
    - If None: inferred from ``observation["entity_id"]``,
      ``observation["track_id"]``, or falling back to
      ``f"minimap:{side}:{obs['t_ms']}:{obs['x']}:{obs['y']}"``.
    """
    sides = lineup.get("sides", lineup)
    split = side_candidates(sides.get(side, []))
    out = []
    for obs in observations:
        if callable(entity_key):
            entity_id = entity_key(obs)
        elif isinstance(entity_key, str) and obs.get(entity_key) is not None:
            entity_id = str(obs[entity_key])
        elif obs.get("entity_id") is not None:
            entity_id = str(obs["entity_id"])
        elif obs.get("track_id") is not None:
            entity_id = f"minimap:{side}:track:{obs['track_id']}"
        else:
            t = obs.get("t_ms", 0)
            x = obs.get("x", 0)
            y = obs.get("y", 0)
            entity_id = f"minimap:{side}:{t}:{x}:{y}"

        stored = str(obs.get("reason") or "").strip()
        marked_kind = obs.get("marked_kind", obs.get("kind"))
        if not stored and (marked_kind == "question" or obs.get("is_question")
                           or str(obs.get("agent")).lower() == "question"):
            stored = "minimap_icon_question_mark"

        if split["blind"] and not stored:
            out.append(identity_claim(
                entity_id, channel="minimap_portrait",
                reason=(f"lineup_incomplete: {len(split['named'])} of "
                        f"{split['slots']} {side} slots named and "
                        f"{len(split['blind'])} propose no candidate"),
                source_version=source_version,
                observed_at_ms=obs.get("t_ms"),
                evidence={"x": obs.get("x"), "y": obs.get("y"), "r": obs.get("r"),
                          "track_id": obs.get("track_id"), "marked_kind": marked_kind,
                          "observation_reason": None,
                          "candidates": sorted(set(split["named"])),
                          "rivals": sorted({r for r in split["rivals"] if r})},
            ))
            continue

        out.append(claim_from_minimap_icon(
            obs, entity_id=entity_id,
            candidates=split["named"], rivals=split["rivals"], gallery=gallery,
            source_version=source_version, margin_min=margin_min))
    return out


def _normalise(claim):
    """Validate a caller-supplied claim without mutating it."""
    required = ("entity_id", "channel")
    missing = [key for key in required if key not in claim]
    if missing:
        raise ValueError(f"identity claim missing {', '.join(missing)}")
    return identity_claim(
        claim["entity_id"], claim.get("agent"),
        channel=claim["channel"],
        observed_at_ms=claim.get("observed_at_ms"),
        reason=claim.get("reason"),
        source_version=claim.get("source_version"),
        evidence=claim.get("evidence"),
        binding_from=claim.get("binding_from"),
        depends_on=claim.get("depends_on"),
    )


def _channel_verdict(claims) -> dict:
    """Accumulate one channel's repeated views of one entity into one vote.

    **Repeated views of one channel are not independent witnesses**, so the
    rule that governs them is not the rule that governs two channels. A
    killfeed entry is drawn over a dozen frames and the top match changes at
    least once on a fifth of them, while
    [metric:killfeed/portrait-stability#frames_with_majority_side=545] of
    [metric:killfeed/portrait-stability#frames=589] frames agree with their own
    entry's majority.
    Reading those as a dozen witnesses turns a good channel into a permanent
    disagreement; accumulating them is what `lineup` already does over a
    session and `killfeed`'s own `not_for` demands.

    A tie inside a channel abstains. A majority of one over a rival is still a
    majority, and the dissent stays on the row rather than being averaged away.
    """
    named = [c for c in claims if c["agent"] is not None]
    votes = Counter(c["agent"] for c in named)
    ranked = votes.most_common()
    total = len(claims)
    row = {"votes": dict(sorted(votes.items())), "claims": total,
           "named": len(named), "constant": len(ranked) == 1,
           "binding_from": next((c.get("binding_from") for c in claims
                                 if c.get("binding_from")), None),
           "depends_on": sorted({d for c in claims for d in c.get("depends_on") or []})}
    if not ranked:
        # Abstentions carry the reader's reason, and the commonest one is the
        # channel's answer for why it said nothing.
        reasons = Counter(c["reason"] for c in claims if c["reason"])
        return {**row, "agent": None,
                "reason": reasons.most_common(1)[0][0] if reasons
                          else "all_claims_abstained"}
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        rivals = sorted(name for name, n in ranked if n == ranked[0][1])
        return {**row, "agent": None,
                "reason": "channel_tie " + " ".join(rivals)}
    return {**row, "agent": ranked[0][0], "reason": None}


def adjudicate_agent_identity(claims) -> list[dict]:
    """Adjudicate independent claims, grouped by their supplied entity key.

    Two rules, because two different things are being combined.

    *Within* a channel, repeated views accumulate into one vote; see
    `_channel_verdict`.  *Across* channels the result is intentionally
    conservative and nothing is decided by counting:

    * one distinct named agent produces ``resolved``;
    * two or more named agents produce ``disagreement`` and no answer;
    * channels that all abstain produce ``abstained``;
    * no claims produce no row, since there was no observation opportunity.

    A single named witness is not presented as corroborated.  Consumers can
    require ``independent_channels >= 2`` when their question needs it, while
    direct witnesses such as the ability tray remain usable for the local
    player's identity.

    **A channel that cannot disagree is not independent.**  A claim naming
    ``binding_from`` took its ENTITY from another channel -- the tray names the
    player's agent on its own, but the SLOT that claim is attached to came from
    searching the top bar for that name, so the two agree by construction.
    Such a channel is listed, and excluded from the independent count, because
    agreement is consistency and not accuracy. A channel whose claim
    ``depends_on`` other entities' verdicts is excluded from the count for the
    same reason, and its dependencies are listed on the row.
    """
    grouped = defaultdict(list)
    for raw in claims:
        claim = _normalise(raw)
        grouped[claim["entity_id"]].append(claim)

    out = []
    for entity_id, group in grouped.items():
        by_channel = {channel: _channel_verdict(
                          [c for c in group if c["channel"] == channel])
                      for channel in sorted({c["channel"] for c in group})}
        naming = {channel: row for channel, row in by_channel.items()
                  if row["agent"]}
        agents = sorted({row["agent"] for row in naming.values()})
        independent = [channel for channel, row in naming.items()
                       if row["binding_from"] not in naming
                       and not row["depends_on"]]
        if len(agents) > 1:
            status, agent, reason = "disagreement", None, "conflicting_claims"
        elif agents:
            status, agent, reason = "resolved", agents[0], None
        else:
            status, agent, reason = "abstained", None, "all_claims_abstained"
        out.append({
            "entity_id": entity_id,
            "agent": agent,
            "status": status,
            "reason": reason,
            "channels": sorted(naming),
            "independent_channels": len(independent),
            "depends_on": sorted({d for row in naming.values()
                                  for d in row["depends_on"]}),
            "agents_seen": agents,
            "by_channel": by_channel,
            "claims": group,
            "adjudication_version": AGENT_IDENTITY_VERSION,
        })
    return out


class AgentIdentityArbiter:
    """Small accumulator for claims arriving from a shared decode pass."""

    def __init__(self):
        self._claims = []

    def add(self, claim: dict) -> None:
        self._claims.append(_normalise(claim))

    def extend(self, claims) -> None:
        for claim in claims:
            self.add(claim)

    def verdict(self) -> list[dict]:
        """Return a recomputable verdict without discarding raw claims."""
        return adjudicate_agent_identity(self._claims)

    @property
    def claims(self) -> tuple[dict, ...]:
        """The immutable view callers can store beside the verdict."""
        return tuple(deepcopy(c) for c in self._claims)

    def events(self, session_id: str, t_ms: float = 0.0) -> list[dict]:
        """Convert adjudicated identity verdicts to formal IDENTITY_DISTRIBUTION events."""
        return identity_events(self.verdict(), session_id, t_ms)


def identity_events(verdicts, session_id: str, t_ms: float = 0.0) -> list[dict]:
    """IDENTITY_DISTRIBUTION events for arbiter verdicts: the only producer.

    The event validator rejects an identity event from any other source, so a
    module that decides a name without this arbiter cannot publish it.
    """
    from ..events import identity_distribution_event, IdentityDistribution, SourceChannel

    events = []
    for v in verdicts:
        dist = {}
        if v["status"] == "resolved" and v["agent"]:
            dist = {v["agent"]: 1.0}
        elif v["status"] == "disagreement" and v["agents_seen"]:
            p = round(1.0 / len(v["agents_seen"]), 3)
            dist = {a: p for a in v["agents_seen"]}
        event = identity_distribution_event(
            session_id=session_id,
            entity_id=f"identity:{v['entity_id']}",
            t_ms=t_ms,
            identity_distribution=IdentityDistribution(
                distribution=dist,
                subject_entity_id=v["entity_id"],
                contributing_channels=v["channels"],
            ),
            source_channel=SourceChannel.ADJUDICATION_IDENTITY,
            producer_version=AGENT_IDENTITY_VERSION,
            metadata={
                "status": v["status"],
                "reason": v["reason"],
                "independent_channels": v["independent_channels"],
                "depends_on": v.get("depends_on", []),
                "by_channel": {ch: r["agent"] for ch, r in v["by_channel"].items()},
            },
        )
        events.append(event.to_dict())
    return events
