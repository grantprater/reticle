"""Validate reviewable domain proposals over stored evidence [owns:domain-hypothesis].

This module never writes accepted facts. `domain` remains their owner. Evidence
dependencies include selection and decision rules, so a rule cannot validate
itself through a transitive verdict.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import artifacts, domain, revisions

SCHEMA_VERSION = 1
PRODUCER_VERSION = "domain-learning-0.1.0"
ROLES = {"supporting", "contradicting", "unresolved"}
STATUSES = {"proposed", "under_review", "accepted", "rejected", "superseded", "withdrawn"}
TRANSITIONS = {
    "proposed": {"under_review", "rejected"},
    "under_review": {"accepted", "rejected"},
    "accepted": {"superseded", "withdrawn"},
    "rejected": set(), "superseded": set(), "withdrawn": set(),
}


def _required(record: dict, fields: tuple[str, ...], label: str, errors: list[str]) -> None:
    for field in fields:
        if record.get(field) is None or record.get(field) == "":
            errors.append(f"{label}: missing {field}")


def validate(document: dict) -> dict:
    """Return a complete report; invalid references never silently disappear."""
    errors: list[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    proposal = document.get("hypothesis", {})
    if not isinstance(proposal, dict):
        proposal = {}
    _required(proposal, ("hypothesis_id", "revision", "claim", "kind", "subject",
                         "scope", "proposed_by", "proposed_at", "rule_id", "prediction", "falsifier",
                         "evaluation_plan", "status"), "hypothesis", errors)
    if proposal.get("kind") not in domain.KINDS:
        errors.append("hypothesis: invalid domain kind")
    if proposal.get("status") not in STATUSES:
        errors.append("hypothesis: invalid status")
    if not isinstance(proposal.get("scope"), dict):
        errors.append("hypothesis: scope must be an explicit object")
    nodes = document.get("evidence", [])
    if not isinstance(nodes, list):
        nodes = []
        errors.append("evidence must be a list")
    index: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("evidence entry must be an object")
            continue
        label = f"evidence {node.get('id', '?')}"
        _required(node, ("id", "revision", "current_revision", "kind", "observed_at",
                         "analyzed_at", "source", "dependencies", "rules_used"), label, errors)
        if node.get("id") in index:
            errors.append(f"{label}: duplicate id")
        elif isinstance(node.get("id"), str):
            index[node["id"]] = node
        if node.get("revision") != node.get("current_revision"):
            errors.append(f"{label}: stale revision")
        source = node.get("source")
        if not isinstance(source, dict) or not source.get("session") or not source.get("window_ms"):
            errors.append(f"{label}: source session and window_ms required")
        if node.get("kind") not in {"observation", "verdict", "selection", "review"}:
            errors.append(f"{label}: invalid kind")
        if not isinstance(node.get("dependencies"), list) or not isinstance(node.get("rules_used"), list):
            errors.append(f"{label}: dependencies and rules_used must be lists")
    visiting: set[str] = set()
    visited: set[str] = set()
    def walk(key: str) -> set[str]:
        if key in visiting:
            errors.append(f"evidence {key}: dependency cycle")
            return set()
        if key in visited:
            return transitive[key]
        visiting.add(key)
        node = index[key]
        rules = set(node.get("rules_used", []))
        for dep in node.get("dependencies", []):
            if not isinstance(dep, dict) or dep.get("id") not in index:
                errors.append(f"evidence {key}: missing dependency {dep}")
                continue
            target = index[dep["id"]]
            if dep.get("revision") != target.get("revision"):
                errors.append(f"evidence {key}: stale dependency {dep['id']}")
            rules.update(walk(dep["id"]))
            rules.update(target.get("rules_used", []))
        visiting.remove(key)
        visited.add(key)
        transitive[key] = rules
        return rules
    transitive: dict[str, set[str]] = {}
    for key in index:
        walk(key)
    classified = {role: [] for role in ROLES}
    dependent = []
    for ref in proposal.get("evidence", []):
        if not isinstance(ref, dict) or ref.get("role") not in ROLES:
            errors.append(f"hypothesis: invalid evidence reference {ref}")
            continue
        key = ref.get("id")
        if key not in index:
            errors.append(f"hypothesis: missing evidence {key}")
            continue
        if ref.get("revision") != index[key].get("revision"):
            errors.append(f"hypothesis: stale evidence {key}")
        classified[ref["role"]].append(key)
        if proposal.get("rule_id") in transitive.get(key, set()):
            dependent.append(key)
    independent = [key for key in classified["supporting"] if key not in dependent]
    status = proposal.get("status")
    transition = document.get("transition")
    if transition is not None:
        prior = transition.get("from")
        if status not in TRANSITIONS.get(prior, set()):
            errors.append(f"invalid transition {prior} -> {status}")
        if not transition.get("reviewer") or not transition.get("decided_at") or not transition.get("reason"):
            errors.append("transition requires reviewer, decided_at and reason")
    elif status not in {"proposed"}:
        errors.append("non-proposed status requires a review transition")
    if status == "accepted" and not independent:
        errors.append("acceptance requires independent support")
    if status == "accepted" and (transition or {}).get("reviewer") == "automatic":
        errors.append("automatic acceptance requires a separately validated policy")
    if status == "accepted" and errors:
        errors.append("acceptance refused while validation errors remain")
    units = {}
    for level in ("instance", "round", "session"):
        units[level] = len({index[key].get(level) for key in independent if index[key].get(level)})
    fact = {
        "claim": proposal.get("claim"), "kind": proposal.get("kind"),
        "known": "inferred", "since": (transition or {}).get("decided_at") or proposal.get("proposed_at"),
        "subject": proposal.get("subject"),
        "depends_on": sorted(independent),
    }
    impacted = []
    root = proposal.get("rule_id")
    consumers = document.get("consumers", [])
    by_id = {item["id"]: item for item in consumers if isinstance(item, dict) and "id" in item}
    affected = {root}
    changed = True
    while changed:
        changed = False
        for key, item in by_id.items():
            if key not in affected and affected.intersection(item.get("depends_on", [])):
                affected.add(key)
                changed = True
    for key in sorted(affected - {root}):
        item = by_id[key]
        impacted.append({"id": key, "revision": item.get("revision"),
                         "action": "recompute_stored" if item.get("stored_inputs", False) else "inspect_source_need"})
    return {"valid": not errors, "errors": sorted(set(errors)), "hypothesis": proposal,
            "evidence_details": {key: index[key] for key in sorted(set(sum(classified.values(), [])))},
            "supporting": classified["supporting"], "independent_support": independent,
            "dependent_support": sorted(set(dependent)),
            "contradicting": classified["contradicting"], "unresolved": classified["unresolved"],
            "support_units": units, "promotion_proposal": fact,
            "withdrawal_impact": impacted}


def render(report: dict) -> str:
    proposal = report["hypothesis"]
    lines = [f"# Domain hypothesis: {proposal.get('hypothesis_id')}", "",
             f"Status: {proposal.get('status')}; valid: {report['valid']}", "",
             f"Claim: {proposal.get('claim')}", f"Scope: {json.dumps(proposal.get('scope'), sort_keys=True)}", ""]
    for label in ("independent_support", "dependent_support", "contradicting", "unresolved"):
        lines.append(f"{label}: {', '.join(report[label]) or 'none'}")
    lines += ["", f"Support units: {json.dumps(report['support_units'], sort_keys=True)}",
              "", "Validation refusals:"]
    lines += [f"- {error}" for error in report["errors"]] or ["- none"]
    lines += ["", "Promotion proposal (review only):", "```json",
              json.dumps(report["promotion_proposal"], indent=2, sort_keys=True), "```",
              "", "Withdrawal/correction dry run:"]
    lines += [f"- {item['id']}@{item['revision']}: {item['action']}" for item in report["withdrawal_impact"]] or ["- no declared consumers"]
    lines += ["", "Evidence source windows:"]
    for key, node in report["evidence_details"].items():
        lines.append(f"- {key}@{node['revision']}: {json.dumps(node['source'], sort_keys=True)}; observed {node['observed_at']}; analyzed {node['analyzed_at']}; refusal {node.get('refusal_reason') or 'none'}")
    return "\n".join(lines) + "\n"


def publish(document: dict, output: Path) -> tuple[Path, dict]:
    report = validate(document)
    output = Path(output)
    proposal = document.get("hypothesis", {})
    for prior in (output / "runs").glob("*/proposal.json"):
        old = json.loads(prior.read_text(encoding="utf-8"))
        previous = old.get("hypothesis", {})
        if (previous.get("hypothesis_id"), previous.get("revision")) == (proposal.get("hypothesis_id"), proposal.get("revision")) and old != document:
            raise ValueError("immutable hypothesis revision already has different content")
    files = {"proposal.json": json.dumps(document, indent=2, sort_keys=True),
             "report.json": json.dumps(report, indent=2, sort_keys=True),
             "review.md": render(report)}
    path = revisions.publish_revision(output, artifact="domain_hypothesis",
                                      producer_version=PRODUCER_VERSION, files=files,
                                      manifest={"schema_version": SCHEMA_VERSION,
                                                "hypothesis_id": document.get("hypothesis", {}).get("hypothesis_id"),
                                                "producer_fingerprint": artifacts.producer_fingerprint("domain_hypothesis")},
                                      compatibility=False)
    return path, report
