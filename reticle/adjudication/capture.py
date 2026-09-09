"""Targeted capture queue: review first, and record only what review cannot settle.

Milestone E of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  Its gate is that
every requested second addresses a named missing discriminator, so a card that
cannot state its surviving alternatives, the property they disagree on, why the
existing sources fail and the action expected to separate them is not issued.

The design's own request order puts source review before any recording, because
reviewing footage already on disk may resolve the largest gaps for zero new
capture.  So a gap with a demo session becomes a review item costing no recorded
seconds; only a gap with no source at all, or one whose prerequisite a solo
recording cannot establish, becomes a capture card.

A detector scoring poorly is explicitly not a reason to ask for footage, and
neither is a bookkeeping fault: a session missing its `ability-demo` tag is a
manifest to fix, not a clip to record.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


ABILITY_CAPTURE_VERSION = "ability-capture-0.1.0"

# One row of the design's capture matrix per property group, with the
# participants that group's prerequisite actually needs.  ``recorded_s`` is the
# design's planning allowance per usable take, not a promised completion time.
CARDS = {
    "identity": {
        "card": "clean local cue or cast-to-object identity",
        "action": "solo; quiet baseline, equip and hold, one commit, let the cue finish",
        "success": "independent visible commit and an isolated sound or object onset",
        "recorded_s": (8, 15), "participants": ("caster",)},
    "geometry": {
        "card": "origin/bearing/extent driver",
        "action": "solo; one prescribed straight movement and one turn, or rotate a stationary device control",
        "success": "which parameter changes is visible under a known input",
        "recorded_s": (10, 20), "participants": ("caster",)},
    "motion": {
        "card": "fixed versus owner-attached region",
        "action": "solo; cast, then move the owner away along a short known path",
        "success": "object origin and owner motion separate on a readable map",
        "recorded_s": (8, 15), "participants": ("caster",)},
    "state": {
        "card": "preview versus deployed mode",
        "action": "solo; hold, adjust aim once, commit; a separate cancel trial only if unresolved",
        "success": "preview follows input, the commit is observed, deployed behaviour is distinguished",
        "recorded_s": (10, 20), "participants": ("caster",)},
    "time": {
        "card": "expiry versus destruction",
        "action": "solo; one clean natural ending, uninterrupted, with no early round end",
        "success": "termination cause independently visible",
        "recorded_s": (20, 45), "participants": ("caster",)},
    "durability": {
        "card": "expiry versus destruction",
        "action": "solo where destructible; one deliberate destruction with the whole footprint visible",
        "success": "termination cause independently visible",
        "recorded_s": (15, 30), "participants": ("caster",)},
    "resources": {
        "card": "recall/redeploy versus resume activation",
        "action": "solo; deploy, activate or recall, then a prescribed re-use",
        "success": "resource/UI transition and object continuity are both visible",
        "recorded_s": (15, 30), "participants": ("caster",)},
    "function": {
        "card": "reactive target behavior",
        "action": "caster plus a cooperating opponent; target starts outside range, crosses once, then exits",
        "success": "baseline, entry, response and target position all visible",
        "recorded_s": (12, 20), "participants": ("caster", "opponent")},
    "causality": {
        "card": "damage/heal/hit-confirm gate",
        "action": "establish the required target or owner state; capture pre-state, one effect, post-state",
        "success": "HUD or target-view state change corroborates the effect",
        "recorded_s": (8, 15), "participants": ("caster", "target")},
    "observation": {
        "card": "enemy/team rendering or hearing",
        "action": "two POVs recorded simultaneously; one known use with controlled line of sight and distance",
        "success": "the same use appears in both synchronized recordings",
        "recorded_s": (10, 20), "participants": ("caster", "receiver")},
}

# Cards that answer a disagreement the corpus can already point at, rather than
# a blank row in the catalogue.
TRANSFER_CARD = {
    "card": "ordinary scale/clutter transfer",
    "action": ("one representative use in a second session under the ordinary capture "
               "profile, with a controlled distractor; change one factor at a time"),
    "success": "the known use stays source-verifiable under the changed rendering",
    "recorded_s": (10, 20), "participants": ("caster",)}

GROUPING_CARD = {
    "card": "multi-object versus segmented/pulsing object",
    "action": ("isolated use where castable, all scheduled activations, whole footprint "
               "kept visible"),
    "success": ("parent use, sibling or segment geometry, and at least two disputed "
                "pulses or activations all visible"),
    "recorded_s": (14, 26), "participants": ("caster",)}

# A solo take cannot establish these prerequisites, so review of solo demo
# footage can never close them and they route straight to a card.
NEEDS_OTHER_PARTICIPANTS = {"function", "causality", "observation"}

SETUP_S = {1: 60.0, 2: 240.0, 3: 420.0}
REVIEW_S_PER_TAKE = 120.0
REDO_FRACTION = {1: 0.25, 2: 0.6, 3: 0.9}
REVIEW_ITEM_S = 180.0


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def observed_evidence(root: Path) -> dict[str, dict]:
    """What the corpus has actually seen of each ability.

    This decides both ranking and eligibility.  Downstream importance is taken
    from observation rather than taste: an ability a human has labelled 71 times
    in real matches matters more to the annotated-VOD endstate than one no
    source has ever shown.  These are planning weights, not probabilities.

    Eligibility matters more.  An ability the corpus has never observed has no
    surviving alternatives to separate -- nothing disagrees about it yet -- so a
    card for it would be an enumeration of the catalogue rather than a
    demonstrated gap, and the design forbids exactly that.
    """
    evidence: dict[str, dict] = defaultdict(
        lambda: {"named_components": 0, "unresolved_windows": 0, "use_claims": 0})
    root = Path(root)
    for row in _rows(root / "analysis" / "ability-entities" / "review.jsonl"):
        if row.get("ability_id"):
            evidence[row["ability_id"]]["unresolved_windows"] += 1
    for row in _rows(root / "analysis" / "ability-gallery" / "coverage.jsonl"):
        evidence[row["ability_id"]]["named_components"] += int(row.get("named", 0))
    claims = defaultdict(set)
    for row in _rows(root / "analysis" / "ability-gallery" / "parameters.jsonl"):
        if row.get("conditioned_on"):
            claims[row["conditioned_on"]].add(row["use_claim_id"])
    for ability_id, ids in claims.items():
        evidence[ability_id]["use_claims"] = len(ids)
    return {k: dict(v, total=sum(v.values())) for k, v in evidence.items()}


def _cost(participants: int, takes: int, recorded_s: float) -> dict:
    setup = SETUP_S[participants]
    review = REVIEW_S_PER_TAKE * takes
    redo = (setup + recorded_s + review) * REDO_FRACTION[participants]
    return {"setup_s": setup, "recorded_s": round(recorded_s, 1),
            "review_s": review, "expected_redo_s": round(redo, 1),
            "total_effort_s": round(setup + recorded_s + review + redo, 1)}


MIN_EVIDENCE_FOR_PARTICIPANTS = 5
MIN_NAMED_FOR_TRANSFER = 3


def _card(request_id, ability_id, agent, ability, spec, group, alternatives,
          why, discriminator, evidence, distinctions):
    participants = len(spec["participants"])
    recorded_s = float(sum(spec["recorded_s"])) / 2.0
    cost = _cost(participants, 1, recorded_s)
    importance = 1 + evidence.get(ability_id, {}).get("total", 0)
    return {
        "capture_request_id": request_id, "ability_id": ability_id, "agent": agent,
        "ability": ability, "property_group": group, "card": spec["card"],
        "named_missing_discriminator": discriminator,
        "surviving_alternatives": alternatives,
        "property_in_dispute": group,
        "why_existing_sources_fail": why,
        "separating_action": spec["action"], "success_condition": spec["success"],
        "participants": list(spec["participants"]),
        "corpus_evidence": evidence.get(ability_id, {}),
        "distinctions_resolved": distinctions, "downstream_importance": importance,
        "cost": cost,
        "value": round(distinctions * importance / cost["total_effort_s"], 6),
        "status": "proposed",
    }


def build_queue(root: str | Path) -> dict:
    """Review items from the coverage matrix; cards only from live disagreements."""
    root = Path(root).resolve()
    coverage = _rows(root / "analysis" / "ability-coverage" / "coverage.jsonl")
    if not coverage:
        raise FileNotFoundError(
            "run `reticle ability-coverage` first: the queue is derived from its rows")
    evidence = observed_evidence(root)
    gallery = _rows(root / "analysis" / "ability-gallery" / "coverage.jsonl")
    entity_review = _rows(root / "analysis" / "ability-entities" / "review.jsonl")
    naming = {r["ability_id"]: (r["agent"], r["ability"]) for r in coverage}

    review_items, not_requested = [], []
    for row in coverage:
        if row["status"] != "not_exercised":
            continue
        group, demos = row["property_group"], row.get("demo_session_ids") or []
        if not demos:
            not_requested.append({
                "ability_id": row["ability_id"], "property_group": group,
                "reason": "no source and nothing in the corpus disagrees about it yet",
            })
            continue
        seen = evidence.get(row["ability_id"], {}).get("total", 0)
        review_items.append({
            "review_id": f"ability-source-review:{row['ability_id']}:{group}",
            "ability_id": row["ability_id"], "agent": row["agent"],
            "property_group": group, "sessions": demos,
            "recorded_s": 0.0, "effort_s": REVIEW_ITEM_S,
            "corpus_observations": seen,
            "question": (f"Does the existing {row['agent']} demo already show "
                         f"{row['ability']}'s {group}?"),
            "why_before_capture": ("the design orders source review ahead of every request; "
                                   "footage on disk may already answer this at no capture cost"),
            "status": "unreviewed",
        })
    review_items.sort(key=lambda r: (-r["corpus_observations"], r["review_id"]))
    for rank, item in enumerate(review_items, 1):
        item["rank"] = rank

    cards, deferred = [], []

    # 1. Milestone D could not tell a session artefact from a real appearance.  Two
    # different things cause that and they need different takes, so the card names
    # which one applies rather than defaulting to "record it again".
    co_occurring = defaultdict(set)
    for row in gallery:
        for sid in row.get("sessions") or []:
            co_occurring[sid].add(row["ability_id"])
    for row in gallery:
        if row.get("held_out_evaluable") or row.get("named", 0) < MIN_NAMED_FOR_TRANSFER:
            continue
        ability_id = row["ability_id"]
        agent, ability = naming.get(ability_id, (ability_id.split(":")[0], ability_id))
        sessions = row.get("sessions") or []
        partners = {other for sid in sessions for other in co_occurring[sid]
                    if other != ability_id and other.split(":")[0] == ability_id.split(":")[0]}
        if len(sessions) < 2:
            spec = dict(TRANSFER_CARD, action=(
                "one representative use in a SECOND session under the ordinary capture "
                "profile, alongside another ability of the same agent; change one factor "
                "at a time"))
            discriminator = "only one session holds this ability, so no session can be held out"
            why = (f"every labelled use sits in {sessions}; holding that session out leaves "
                   f"no training example at all")
        elif not partners:
            spec = dict(TRANSFER_CARD, action=(
                "one take containing this ability AND another ability of the same agent, "
                "in a session that already holds labelled uses of both"))
            discriminator = ("this ability never shares a session with a second labelled class, "
                             "so no within-session contrast exists to test")
            why = (f"it appears in {len(sessions)} sessions {sessions} but never beside another "
                   f"labelled {agent} ability, and a contrast needs both classes in the test "
                   f"session so the map cannot supply the margin")
        else:
            spec = dict(TRANSFER_CARD, action=(
                f"one take pairing this ability with {sorted(partners)[0]} in a session other "
                f"than the one that already holds both"))
            discriminator = ("the partner class it shares a session with occurs in no other "
                             "session, so there is nothing to train on")
            why = (f"it co-occurs with {sorted(partners)} in only one session, leaving the "
                   f"pair untrainable when that session is held out")
        cards.append(_card(
            f"capture:transfer:{ability_id}", ability_id, agent, ability,
            spec, "observation",
            ["appearance is a property of this ability",
             "appearance is a property of this session, map or capture profile"],
            why, discriminator, evidence, 1))

    # 2. Milestone C left competing groupings standing -- but on footage already on
    # disk.  The design orders review first, so these escalate to a card only once a
    # reviewer records that the existing source cannot settle them.
    unresolved = Counter(r["ability_id"] for r in entity_review
                         if r.get("ability_id") and len(r.get("component_ids") or []) > 1)
    for ability_id, count in sorted(unresolved.items()):
        agent, ability = naming.get(ability_id, (ability_id.split(":")[0], ability_id))
        deferred.append({
            "would_be_request_id": f"capture:grouping:{ability_id}",
            "ability_id": ability_id, "agent": agent, "ability": ability,
            "card": GROUPING_CARD["card"], "property_group": "geometry",
            "unresolved_windows": count,
            "surviving_alternatives": ["one object drawn as several components",
                                       "several independent objects from one use",
                                       "one object pulsing, redrawn per activation"],
            "deferred_because": ("the dispute is live on footage already recorded; "
                                 "`reticle ability-entities` queues these windows for review "
                                 "at no capture cost"),
            "escalates_when": ("a reviewed window is marked as unresolvable from its own "
                               "source -- clipped use, footprint out of frame, or occluded"),
            "status": "deferred_to_review",
        })

    # 3. Prerequisites a solo demo cannot establish.  Nothing in the corpus disputes
    # these yet: they are unobserved, and absence of evidence is not a surviving
    # alternative.  They are named so the omission is visible, and not requested.
    for group in sorted(NEEDS_OTHER_PARTICIPANTS):
        eligible = sorted({r["ability_id"] for r in coverage
                           if r["property_group"] == group
                           and r["status"] == "not_exercised"
                           and evidence.get(r["ability_id"], {}).get("total", 0)
                           >= MIN_EVIDENCE_FOR_PARTICIPANTS})
        if eligible:
            deferred.append({
                "would_be_request_id": f"capture:{group}:*",
                "property_group": group, "card": CARDS[group]["card"],
                "participants": list(CARDS[group]["participants"]),
                "abilities": eligible, "ability_count": len(eligible),
                "deferred_because": ("no observation in the corpus disagrees about this "
                                     "property for these abilities; they are unobserved, and "
                                     "the design's request order puts source review first"),
                "escalates_when": ("source review leaves a specific property in dispute for a "
                                   "named ability, which then gets its own card"),
                "status": "deferred_no_demonstrated_dispute",
            })

    cards.sort(key=lambda c: (-c["value"], c["capture_request_id"]))
    for rank, card in enumerate(cards, 1):
        card["rank"] = rank

    batches = []
    grouped = defaultdict(list)
    for card in cards:
        grouped[(card["agent"], tuple(card["participants"]))].append(card)
    for (agent, participants), members in sorted(grouped.items()):
        recorded = sum(c["cost"]["recorded_s"] for c in members)
        cost = _cost(len(participants), len(members), recorded)
        separate = sum(c["cost"]["total_effort_s"] for c in members)
        batch_id = f"take:{agent.casefold()}:{'+'.join(participants)}"
        for card in members:
            card["batch_id"] = batch_id
        batches.append({
            "batch_id": batch_id, "agent": agent, "participants": list(participants),
            "capture_request_ids": [c["capture_request_id"] for c in members],
            "cards": len(members), "recorded_s": round(recorded, 1), "cost": cost,
            "effort_saved_by_batching_s": round(separate - cost["total_effort_s"], 1),
            "value": round(sum(c["distinctions_resolved"] * c["downstream_importance"]
                               for c in members) / cost["total_effort_s"], 6),
            "note": "one setup, unrelated casts kept from overlapping within the take",
            "status": "proposed",
        })
    batches.sort(key=lambda b: (-b["value"], b["batch_id"]))

    verdicts = verify_takes(root, cards, gallery)
    settled = {v["capture_request_id"] for v in verdicts if v["verdict"] == "verified"}
    for card in cards:
        if card["capture_request_id"] in settled:
            card["status"] = "satisfied"

    summary = {
        "coverage_rows": len(coverage),
        "review_items": len(review_items), "review_recorded_s": 0.0,
        "review_effort_s": round(sum(r["effort_s"] for r in review_items), 1),
        "capture_cards": len(cards), "capture_batches": len(batches),
        "not_requested_rows": len(not_requested),
        "deferred_requests": len(deferred),
        "requested_recorded_s": round(sum(c["cost"]["recorded_s"] for c in cards), 1),
        "requested_total_effort_s": round(sum(b["cost"]["total_effort_s"] for b in batches), 1),
        "cards_by_source": dict(sorted(Counter(
            c["capture_request_id"].split(":")[1] for c in cards).items())),
        "cards_by_participants": dict(sorted(Counter(
            len(c["participants"]) for c in cards).items())),
        "takes_recorded": len({v["take_id"] for v in verdicts}),
        "take_verdicts": dict(sorted(Counter(v["verdict"] for v in verdicts).items())),
        "cards_satisfied": sum(c["status"] == "satisfied" for c in cards),
        "open_recorded_s": round(sum(c["cost"]["recorded_s"] for c in cards
                                     if c["status"] != "satisfied"), 1),
    }
    return {
        "manifest": {
            "schema_version": 1, "producer_version": ABILITY_CAPTURE_VERSION,
            "store_root": str(root), "summary": summary,
            "value_formula": ("distinctions_resolved * downstream_importance / "
                              "(setup + recorded + review + expected redo)"),
            "limits": [
                "Review items come first and request no recorded seconds at all.",
                "A card is issued only where the corpus already holds a disagreement: a "
                "class that cannot be held out, a grouping that stayed unresolved, or a "
                "prerequisite no solo recording can establish.",
                "An ability the corpus has never observed gets no card. Absence of "
                "evidence is not a surviving alternative.",
                "A poor detector score is not a gap, and a missing manifest tag is a "
                "bookkeeping fault rather than a capture request.",
                "A dispute that lives on footage already recorded is review work, not a "
                "capture request; it escalates only when review cannot settle it.",
                "Recording allowances are planning figures per usable take, not promised times.",
                "Downstream importance counts observed uses in this corpus; it is a "
                "planning weight, not a measured probability.",
                "A take never certifies itself: a claimed success is checked against evidence "
                "the take could not assert into being, and an unbacked claim stays unverified.",
                "A take that failed part of its batch is retained with the failure recorded, "
                "so only the failed step needs re-recording.",
            ],
        },
        "review": review_items, "cards": cards, "batches": batches,
        "deferred": deferred, "not_requested": not_requested, "takes": verdicts,
    }


def write_queue(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("review", "cards", "batches", "deferred", "not_requested", "takes"):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in bundle[name]),
            encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    return out


# --- Milestone F: executing accepted cards -------------------------------------
#
# A take is appended, never rewritten, and a take's own claim never decides its
# own outcome.  The design is explicit that success must not be labelled from the
# intended script alone, so `verify_takes` ignores what the operator says happened
# and asks the store whether the independent evidence actually arrived.

TAKES_PATH = ("notes", "capture-takes.jsonl")


def takes_path(root: str | Path) -> Path:
    return Path(root).joinpath(*TAKES_PATH)


def record_take(root: str | Path, take_id: str, session_id: str | None,
                outcomes: list[dict], operator_note: str = "") -> dict:
    """Append one take.  ``outcomes`` are the operator's claims, kept as claims.

    A take that failed some of its cards still records the ones it got, because
    a partial failure is evidence about the protocol and re-recording a whole
    batch to recover one card wastes the rest.
    """
    for outcome in outcomes:
        if not outcome.get("capture_request_id"):
            raise ValueError("each outcome needs a capture_request_id")
        if outcome.get("claimed_status") not in {"success", "failed", "not_attempted"}:
            raise ValueError("claimed_status must be success, failed or not_attempted")
    row = {
        "take_id": take_id, "session_id": session_id,
        "operator_note": operator_note,
        "claims": [{"capture_request_id": o["capture_request_id"],
                    "claimed_status": o["claimed_status"],
                    "actual_action": o.get("actual_action"),
                    "failure_reason": o.get("failure_reason")} for o in outcomes],
    }
    path = takes_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def verify_takes(root: str | Path, cards: list[dict], gallery: list[dict]) -> list[dict]:
    """Check each claimed success against evidence the take did not produce itself.

    For a transfer card the independent evidence is specific: the ability has to
    have become held-out evaluable, which needs labelled uses in the new session
    and cannot be satisfied by asserting the take went well.
    """
    root = Path(root)
    by_id = {c["capture_request_id"]: c for c in cards}
    evaluable = {row["ability_id"]: row for row in gallery}
    manifests = {p.stem for p in (root / "manifests").glob("*.json")}
    verdicts = []
    for take in _rows(takes_path(root)):
        for claim in take["claims"]:
            request_id = claim["capture_request_id"]
            card = by_id.get(request_id)
            ability_id = card["ability_id"] if card else None
            row = {"take_id": take["take_id"], "capture_request_id": request_id,
                   "ability_id": ability_id, "session_id": take.get("session_id"),
                   "claimed_status": claim["claimed_status"],
                   "actual_action": claim.get("actual_action"),
                   "failure_reason": claim.get("failure_reason")}
            if claim["claimed_status"] != "success":
                verdicts.append({**row, "verdict": "retained_failure",
                                 "independent_evidence": None,
                                 "reason": "operator recorded no success to check; "
                                           "the take is kept so the protocol failure is not lost"})
                continue
            if card is None:
                verdicts.append({**row, "verdict": "unverifiable",
                                 "independent_evidence": None,
                                 "reason": "no open card matches this request id"})
                continue
            if not take.get("session_id") or take["session_id"] not in manifests:
                verdicts.append({**row, "verdict": "unverified",
                                 "independent_evidence": None,
                                 "reason": "claimed success but the take's session is not ingested, "
                                           "so nothing independent can be read"})
                continue
            entry = evaluable.get(ability_id) or {}
            sessions = entry.get("sessions") or []
            evidence = {"named_components": entry.get("named", 0),
                        "sessions_with_labels": sessions,
                        "held_out_evaluable": bool(entry.get("held_out_evaluable"))}
            if take["session_id"] not in sessions:
                verdicts.append({**row, "verdict": "unverified",
                                 "independent_evidence": evidence,
                                 "reason": "the ingested session carries no labelled use of this "
                                           "ability, so the claimed cast left no evidence"})
            elif not entry.get("held_out_evaluable"):
                verdicts.append({**row, "verdict": "partial",
                                 "independent_evidence": evidence,
                                 "reason": "the use was captured and labelled, but the contrast "
                                           "is still not held-out evaluable"})
            else:
                verdicts.append({**row, "verdict": "verified",
                                 "independent_evidence": evidence,
                                 "reason": "the ability is now held-out evaluable, which the take "
                                           "could not assert into being"})
    return verdicts
