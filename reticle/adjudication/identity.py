"""Cross-channel agent identity adjudication over stored claims.

Readers do not name entities.  They publish claims, and this module is the
single owner that turns claims about one entity into a canonical answer.  A
claim may abstain; an abstention is not a disagreement.  Conflicting names
remain unresolved with both witnesses attached.

This is deliberately narrower than a general reconciliation engine.  It does
not read frames, track icons, or infer a persistent entity key.  Callers must
provide that key, so a packed roster slot cannot silently become a player.

Owns [owns:agent-identity].
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import glob
from pathlib import Path

import cv2
import numpy as np

from .. import appearance
from ..roster import N_SLOTS


AGENT_IDENTITY_VERSION = "agent-identity-0.1.0"
PORTRAIT_MARGIN_MIN = 0.07
_IDENTITY_SURFACES = ("agent_icon", "killfeed_portrait", "minimap_portrait")


def identity_claim(entity_id, agent=None, *, channel, observed_at_ms=None,
                   reason=None, source_version=None, evidence=None) -> dict:
    """Return one normalized, provenance-carrying identity claim.

    ``agent=None`` is an explicit abstention.  The arbiter never turns a
    missing name into an unknown agent or drops the reason for refusing.
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
        "reason": reason if agent is None else None,
        "source_version": source_version,
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
    if player and player.get("agent") is not None and player.get("slot") is not None:
        entity_id = f"{observation_id}:ally:slot:{player['slot']}"
        decided_by = player.get("decided_by")
        channel = ("ability_tray" if decided_by == "ability_tray"
                   else "self_icon" if decided_by == "self_icon_among_top_bar_candidates"
                   else "player_identity")
        out.append(identity_claim(
            entity_id, player["agent"], channel=channel,
            source_version=version,
            evidence={"slot": player["slot"],
                      "decided_by": decided_by,
                      "agree": player.get("agree"),
                      "witnesses": player.get("witnesses", {})},
        ))
    return out


def load_identity_gallery(store) -> dict[str, list[np.ndarray]]:
    """Load official portrait descriptors in the killfeed feature space."""
    art = Path(store) / "reference" / "assets" / "agents"
    gallery: dict[str, list[np.ndarray]] = {}
    for surface in _IDENTITY_SURFACES:
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
        references = gallery.get(agent, ())
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
    `lineup.adjudicate` learned this from the other end: a margin measured
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
    )


def adjudicate_agent_identity(claims) -> list[dict]:
    """Adjudicate independent claims, grouped by their supplied entity key.

    The result is intentionally conservative:

    * one distinct named agent produces ``resolved``;
    * two or more named agents produce ``disagreement`` and no answer;
    * claims containing only abstentions produce ``abstained``;
    * no claims produce no row, since there was no observation opportunity.

    A single named witness is not presented as corroborated.  Consumers can
    require ``independent_channels >= 2`` when their question needs it, while
    direct witnesses such as the ability tray remain usable for the local
    player's identity.  No confidence is invented from channel agreement.
    """
    grouped = defaultdict(list)
    for raw in claims:
        claim = _normalise(raw)
        grouped[claim["entity_id"]].append(claim)

    out = []
    for entity_id, group in grouped.items():
        named = [c for c in group if c["agent"] is not None]
        agents = sorted({c["agent"] for c in named})
        by_agent = defaultdict(list)
        for claim in named:
            by_agent[claim["agent"]].append(claim["channel"])
        channels = sorted({c["channel"] for c in named})
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
            "channels": channels,
            "independent_channels": len(channels),
            "agents_seen": agents,
            "channels_by_agent": {
                name: sorted(set(values)) for name, values in sorted(by_agent.items())
            },
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
