"""Mine ability evidence on the solo ability demos from stored data only.

    .\\.venv\\Scripts\\python.exe tools\\ability_demo_mining.py witness
    .\\.venv\\Scripts\\python.exe tools\\ability_demo_mining.py facts
    .\\.venv\\Scripts\\python.exe tools\\ability_demo_mining.py retrieve
    .\\.venv\\Scripts\\python.exe tools\\ability_demo_mining.py charges

A solo demo has one player, so the HUD tray is a witness for which ability a
minimap candidate could be. This tool asks the owners and restates none of
their rules: `adjudication.ability.build_entities` supplies each candidate's
parent edges to tray use claims, `domain_learning` validates and publishes each
web-fact proposal, and `metrics` records every count it prints.

`witness` scores the tray edge against the human labels on the reviewed demos.
`facts` turns `tools/data/ability_web_references.json` into domain-hypothesis
proposals and cross-checks each stated duration against the lifetimes of
human-named candidates; it never edits `domain/*.toml`. `retrieve` asks, for
every tray-bound candidate on an unlabelled demo, whether an independently
labelled exemplar of that ability exists in another session, and records the
refusal reason where none does. It decodes no video and writes no label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reticle import metrics  # noqa: E402
from reticle.ability_timeline import ABILITY_TIMELINE_VERSION  # noqa: E402
from reticle.adjudication.ability import (  # noqa: E402
    ABILITY_ENTITY_VERSION, _components, _labels, build_entities)
from reticle.adjudication.gallery import session_durations  # noqa: E402
from reticle.domain_learning import PRODUCER_VERSION as HYPOTHESIS_VERSION, publish  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

MINING_VERSION = "ability-demo-mining-0.1.0"
REFERENCES = ROOT / "tools" / "data" / "ability_web_references.json"
TODAY = "2026-09-23"
#: A candidate this close to the player's own icon is usually the icon itself.
SELF_MIN_PX = 12.0
#: An observed lifetime longer than the stated one by this much contradicts it;
#: 1.5 s covers the candidate sampler's step and the onset/offset fades.
LIFETIME_TOL_MS = 1500.0
#: Below this fraction of the stated life a track is more likely a fragment
#: than evidence for the value, so it stays unresolved.
FRAGMENT_FRACTION = 0.5
CENSOR_MS = 1000.0
MIN_EXEMPLARS = 3
DEMO_FLAGS = {"ability-demo", "custom-game", "infinite-abilities", "spectator",
              "spaced-casts", "stationary-at-casts"}


def demo_sessions(root: Path) -> dict[str, dict]:
    """Every manifest tagged `ability-demo`, with its tagged agent and map."""
    out = {}
    for path in sorted((root / "manifests").glob("*.json")):
        tags = json.loads(path.read_text(encoding="utf-8")).get("tags") or []
        if "ability-demo" not in tags:
            continue
        agents = [t for t in tags if ":" not in t and t not in DEMO_FLAGS]
        maps = [t.split(":", 1)[1] for t in tags if t.startswith("map:")]
        out[path.stem] = {"agent": agents[0] if len(agents) == 1 else None,
                          "map": maps[0] if maps else None}
    return out


def session_maps(root: Path) -> dict[str, str | None]:
    out = {}
    for path in sorted((root / "manifests").glob("*.json")):
        tags = json.loads(path.read_text(encoding="utf-8")).get("tags") or []
        maps = [t.split(":", 1)[1] for t in tags if t.startswith("map:")]
        out[path.stem] = maps[0] if maps else None
    return out


def _edges(bundle: dict) -> dict[str, dict]:
    return {row["component_id"]: row for row in bundle["component_claims"]}


def _uses(bundle_timeline: list[dict]) -> dict[str, dict]:
    return {u["use_claim_id"]: u for u in bundle_timeline}


def tray_edge(claim: dict, uses: dict[str, dict]) -> dict | None:
    """The single non-suspect tray use claim the owner linked, else None.

    Contradicted edges count: the owner moves an edge there only because a
    human answered, and scoring must see the edge the unlabelled case sees.
    """
    edges = [e for e in claim["possible_parents"] + claim["contradicted_parents"]
             if uses.get(e["use_claim_id"], {}).get("status") == "candidate"]
    ids = sorted({e["use_claim_id"] for e in edges})
    return uses[ids[0]] if len(ids) == 1 else None


def _load(root: Path):
    from reticle.ability_timeline import build_timeline
    timeline = build_timeline(root)
    bundle = build_entities(root)
    components = {c["component_id"]: c for c in _components(root, _labels(root))}
    return _uses(timeline["use_claims"]), _edges(bundle), components


def _deps() -> dict:
    return {"mining": MINING_VERSION, "timeline": ABILITY_TIMELINE_VERSION,
            "entities": ABILITY_ENTITY_VERSION, "self_min_px": SELF_MIN_PX}


def witness(root: Path) -> dict:
    uses, edges, components = _load(root)
    reviewed = {p.stem for p in (root / "labels" / "ability_candidates").glob("*.reviewed")}
    demos = demo_sessions(root)
    counts, by_ability = Counter(), defaultdict(Counter)
    for cid, comp in components.items():
        sid = comp["session_id"]
        if comp["origin"] != "detector_candidate" or sid not in reviewed or sid not in demos:
            continue
        if comp["label_state"] == "unreviewed":
            continue
        if float(comp["raw"].get("self_icon_dist") or 0.0) <= SELF_MIN_PX:
            counts["near_self"] += 1
            continue
        use = tray_edge(edges[cid], uses)
        if use is None:
            counts["no_unique_edge"] += 1
            continue
        state = comp["label_state"]
        if state == "named":
            state = "named_same" if comp["label_ability_id"] == use["ability_id"] else "named_other"
        counts[state] += 1
        by_ability[use["ability_id"]][state] += 1
    bound = sum(counts[k] for k in ("named_same", "named_other", "generic", "uncertain", "clutter"))
    values = {"bound": bound, **{k: counts[k] for k in
                                 ("named_same", "named_other", "generic", "uncertain", "clutter",
                                  "near_self", "no_unique_edge")},
              "precision": round(counts["named_same"] / bound, 3) if bound else None,
              "clutter_rate": round(counts["clutter"] / bound, 3) if bound else None}
    metrics.record("ability_demo_mining", part="tray-witness", values=values, deps=_deps(),
                   context={"reviewed_demo_sessions": len(reviewed & set(demos))},
                   note="tray edge = the one non-suspect use claim adjudication.ability links")
    return {"values": values, "by_ability": {k: dict(v) for k, v in sorted(by_ability.items())}}


def _pin(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _reference_node(ref: dict, scope: dict, retrieved: str) -> dict:
    patch = ref.get("patch") or "-".join([scope["patches"][0], scope["patches"][-1]])
    source = {"url": ref["url"], "retrieved_at": ref.get("retrieved_at") or retrieved,
              "patch": patch, "quote": ref["quote"], "value": ref.get("value")}
    if ref.get("note"):
        source["note"] = ref["note"]
    return {"id": f"ref:{ref['id']}", "revision": _pin(source), "current_revision": _pin(source),
            "kind": "reference", "observed_at": source["retrieved_at"], "analyzed_at": TODAY,
            "source": source, "dependencies": [], "rules_used": []}


def classify_lifetime(observed_ms: float, expected_ms: float, censored: bool) -> tuple[str, str]:
    """Role of one observed lifetime against a stated duration, with its reason."""
    if observed_ms > expected_ms + LIFETIME_TOL_MS:
        return "contradicting", "observed longer than stated duration plus tolerance"
    if censored:
        return "unresolved", "track runs to clip end; lifetime is a lower bound"
    if observed_ms < FRAGMENT_FRACTION * expected_ms:
        return "unresolved", "track shorter than half the stated life; likely a fragment"
    return "supporting", "observed lifetime within stated duration plus tolerance"


def lifetime_evidence(check: dict, uses, edges, components, durations, demos) -> list[tuple[dict, str]]:
    ability = check["ability_id"]
    expected = float(check["expected_ms"])
    out = []
    for cid, comp in sorted(components.items()):
        sid = comp["session_id"]
        raw_duration = comp["raw"].get("duration_ms")
        named = comp["label_state"] == "named" and comp["label_ability_id"] == ability
        tray = None
        if (comp["origin"] == "detector_candidate" and comp["label_state"] == "unreviewed"
                and sid in demos):
            use = tray_edge(edges[cid], uses)
            tray = use if use and use["ability_id"] == ability else None
        if not named and tray is None:
            continue
        window = [comp["observed_t_ms"], comp["observed_end_ms"]]
        node = {"id": f"obs:{cid}", "kind": "observation" if named else "verdict",
                "observed_at": f"{sid}@{int(comp['observed_t_ms'])}ms", "analyzed_at": TODAY,
                "source": {"session": sid, "window_ms": window,
                           "evidence": comp["source_evidence"]},
                "instance": cid, "session": sid,
                "session_class": "ability-demo" if sid in demos else "match",
                "dependencies": [], "rules_used": []}
        if raw_duration is None:
            role, reason = "unresolved", "component carries no observed duration"
        elif named:
            censored = comp["observed_end_ms"] >= durations.get(sid, float("inf")) - CENSOR_MS
            role, reason = classify_lifetime(float(raw_duration), expected, censored)
            node["witness"] = {"kind": "human_label", "evidence": comp["label_evidence"]}
            node["observed_ms"] = float(raw_duration)
            node["right_censored"] = censored
        else:
            role = "unresolved"
            reason = ("bound only by a tray window, whose precision on reviewed demos is low; "
                      "a player label must name it first")
            node["rules_used"] = ["ability-hypothesis:temporal_compatibility"]
            node["observed_ms"] = float(raw_duration)
            node["tray_use_claim"] = tray["use_claim_id"]
        node["refusal_reason"] = None if role == "supporting" else reason
        node["reason"] = reason
        node["revision"] = node["current_revision"] = _pin(comp["raw"])
        out.append((node, role))
    return out + instance_spans(ability, expected, out, edges, components, durations, demos)


def instance_spans(ability, expected, observed, edges, components, durations, demos):
    """One node per cast: the span of the named fragments the owner binds to it.

    `adjudication.ability` marks an edge `supported` when a human named the
    candidate as the tray's ability. Fragments sharing that use claim are one
    instance, so their union bounds its life where no single fragment does.
    """
    by_use = defaultdict(list)
    for node, _ in observed:
        if node["kind"] != "observation":
            continue
        cid = node["instance"]
        for edge in edges[cid]["possible_parents"]:
            if edge["status"] == "supported":
                by_use[edge["use_claim_id"]].append((node, components[cid]))
    out = []
    for use_id, members in sorted(by_use.items()):
        sid = members[0][1]["session_id"]
        start = min(c["observed_t_ms"] for _, c in members)
        end = max(c["observed_end_ms"] for _, c in members)
        censored = end >= durations.get(sid, float("inf")) - CENSOR_MS
        role, reason = classify_lifetime(end - start, expected, censored)
        deps = [{"id": n["id"], "revision": n["revision"]} for n, _ in members]
        pin = _pin({"use": use_id, "deps": deps})
        out.append(({"id": f"span:{use_id}", "revision": pin, "current_revision": pin,
                     "kind": "verdict", "observed_at": f"{sid}@{int(start)}ms",
                     "analyzed_at": TODAY,
                     "source": {"session": sid, "window_ms": [start, end]},
                     "instance": use_id, "session": sid,
                     "session_class": "ability-demo" if sid in demos else "match",
                     "unit": "instance", "fragments": len(members),
                     "observed_ms": end - start, "right_censored": censored,
                     "use_claim_status": next(e["use_claim_status"] for e in
                                              edges[members[0][0]["instance"]]["possible_parents"]
                                              if e["use_claim_id"] == use_id),
                     "dependencies": deps,
                     "rules_used": ["ability-hypothesis:matching_human_component_identity"],
                     "reason": reason, "refusal_reason": None if role == "supporting" else reason},
                    role))
    return out


def multi_drop_evidence(check: dict, uses: dict[str, dict], demos: dict) -> list[tuple[dict, str]]:
    """A demo cast whose tray drop spends more than one charge supports a batch launch.

    A one-charge drop is consistent with the claim too, so it stays unresolved;
    the tray alone cannot contradict a batch launch.
    """
    out = []
    one = 1.0 / check["uses"]
    for use_id, use in sorted(uses.items()):
        if (use.get("ability_id") != check["ability_id"] or use["session_id"] not in demos
                or use.get("status") != "candidate"):
            continue
        drop = float(use["raw"][2]) - float(use["raw"][3])
        role = "supporting" if drop > one + CHARGE_TOL else "unresolved"
        reason = (f"one drop of {drop:.2f} spends more than one charge ({one:.2f})"
                  if role == "supporting" else "a one-charge drop is consistent either way")
        pin = _pin(use["raw"])
        out.append(({"id": f"tray:{use_id}", "revision": pin, "current_revision": pin,
                     "kind": "observation", "observed_at": f"{use['session_id']}@{int(use['observed_t_ms'])}ms",
                     "analyzed_at": TODAY,
                     "source": {"session": use["session_id"],
                                "window_ms": list(use["occurrence_interval_ms"]),
                                "evidence": use["source_evidence"]},
                     "instance": use_id, "session": use["session_id"],
                     "session_class": "ability-demo", "drop": round(drop, 3),
                     "dependencies": [], "rules_used": [], "reason": reason,
                     "refusal_reason": None if role == "supporting" else reason,
                     "source_review": ("28f53bfddbbe 15.0 s: two dark discs appear together after "
                                       "the 14.5 s E drop; awaiting player confirmation"
                                       if use["session_id"] == "28f53bfddbbe" else None)},
                    role))
    return out


def facts(root: Path, output: Path) -> dict:
    data = json.loads(REFERENCES.read_text(encoding="utf-8"))
    scope = data["patch_scope"]
    uses, edges, components = _load(root)
    durations = session_durations(root)
    demos = demo_sessions(root)
    summary = []
    for proposal in data["proposals"]:
        nodes, refs = [], []
        for ref in proposal["references"]:
            node = _reference_node(ref, scope, data["retrieved_at"])
            if node["id"] not in {n["id"] for n in nodes}:
                nodes.append(node)
            refs.append({"id": node["id"], "revision": node["revision"], "role": ref["stance"]})
        check = proposal["check"]
        observed = []
        if check["kind"] == "tray_multi_drop":
            observed = multi_drop_evidence(check, uses, demos)
            for node, role in observed:
                nodes.append(node)
                refs.append({"id": node["id"], "revision": node["revision"], "role": role})
        if check["kind"] == "lifetime_upper":
            observed = lifetime_evidence(check, uses, edges, components, durations, demos)
            for node, role in observed:
                nodes.append(node)
                refs.append({"id": node["id"], "revision": node["revision"], "role": role})
        kind = "measurement" if proposal["property"] != "charges" else "rule"
        document = {
            "schema_version": 1,
            "hypothesis": {
                "hypothesis_id": proposal["hypothesis_id"],
                "revision": _pin({"proposal": proposal, "evidence": refs}),
                "claim": proposal["claim"], "kind": kind, "subject": proposal["subject"],
                "scope": {"patches": scope["patches"], "patch_reason": scope["reason"],
                          "map": None, "profile": None},
                "proposed_by": "web reference retrieval, tools/ability_demo_mining.py",
                "proposed_at": TODAY, "rule_id": proposal["hypothesis_id"],
                "prediction": ("No independently witnessed instance outlives the stated value by "
                               f"more than {LIFETIME_TOL_MS / 1000:.1f} s"
                               if check["kind"] == "lifetime_upper" else
                               "A later capture without infinite abilities shows the stated value"),
                "falsifier": ("A human-named instance observed longer than the stated value plus "
                              "tolerance" if check["kind"] == "lifetime_upper" else
                              "An observation of a different value in scope"),
                "evaluation_plan": check.get("reason") or
                "Compare human-named candidate lifetimes; keep tray-bound ones unresolved",
                "status": "proposed", "evidence": refs,
                "accepted_fact_conflict": proposal.get("accepted_fact_conflict"),
            },
            "evidence": nodes,
            "consumers": [],
        }
        path, report = publish(document, output / proposal["hypothesis_id"])
        fragments = [(n, r) for n, r in observed if n.get("unit") != "instance"]
        instances = [(n, r) for n, r in observed if n.get("unit") == "instance"]
        roles = Counter(role for _, role in fragments)
        demo_roles = Counter(role for node, role in fragments
                             if node["session_class"] == "ability-demo")
        summary.append({
            "hypothesis_id": proposal["hypothesis_id"], "valid": report["valid"],
            "errors": report["errors"], "review": str(path / "review.md"),
            "reference_support": len(report["reference_support"]),
            "reference_contradiction": len(report["reference_contradiction"]),
            "source_disagreement": report["source_disagreement"],
            "accepted_fact_conflict": bool(proposal.get("accepted_fact_conflict")),
            "observations": dict(roles), "demo_observations": dict(demo_roles),
            "instances": [{"use_claim": n["instance"], "span_ms": n["observed_ms"],
                           "fragments": n["fragments"], "role": r, "reason": n["reason"],
                           "use_claim_status": n["use_claim_status"],
                           "session_class": n["session_class"]} for n, r in instances],
            "contradicting_detail": [
                {"instance": node["instance"], "observed_ms": node.get("observed_ms"),
                 "session_class": node["session_class"]}
                for node, role in fragments if role == "contradicting"],
            "check": check["kind"],
        })
    values = {
        "proposals": len(summary),
        "valid": sum(s["valid"] for s in summary),
        "source_disagreements": sum(s["source_disagreement"] for s in summary),
        "accepted_fact_conflicts": sum(s["accepted_fact_conflict"] for s in summary),
        "checked": sum(1 for s in summary if s["check"] == "lifetime_upper"),
        "with_independent_observation": sum(
            1 for s in summary if s["observations"].get("supporting") or
            s["observations"].get("contradicting")),
        "contradicted": sum(1 for s in summary if s["observations"].get("contradicting")),
        "supporting_obs": sum(s["observations"].get("supporting", 0) for s in summary),
        "contradicting_obs": sum(s["observations"].get("contradicting", 0) for s in summary),
        "unresolved_obs": sum(s["observations"].get("unresolved", 0) for s in summary),
        **{f"instance_{role}": sum(1 for s in summary for i in s["instances"] if i["role"] == role)
           for role in ("supporting", "contradicting", "unresolved")},
    }
    metrics.record("ability_demo_mining", part="web-facts", values=values,
                   deps={**_deps(), "hypothesis": HYPOTHESIS_VERSION,
                         "tol_ms": LIFETIME_TOL_MS, "fragment": FRAGMENT_FRACTION,
                         "references": _pin(data)},
                   context={"retrieved_at": data["retrieved_at"]})
    (output / "summary.json").write_text(json.dumps({"values": values, "proposals": summary},
                                                    indent=2), encoding="utf-8")
    return {"values": values, "proposals": summary}


def retrieve(root: Path) -> dict:
    """Which tray-bound candidates on unlabelled demos have eligible exemplars."""
    uses, edges, components = _load(root)
    demos = demo_sessions(root)
    maps = session_maps(root)
    labelled = {p.stem for p in (root / "labels" / "ability").glob("*.jsonl") if ".bak" not in p.name}
    exemplars = defaultdict(list)
    for comp in components.values():
        if comp["label_state"] == "named":
            exemplars[comp["label_ability_id"]].append(comp)
    outcomes, reasons, rows = Counter(), Counter(), []
    for cid, comp in sorted(components.items()):
        sid = comp["session_id"]
        if sid not in demos or sid in labelled or comp["origin"] != "detector_candidate":
            continue
        if float(comp["raw"].get("self_icon_dist") or 0.0) <= SELF_MIN_PX:
            outcome, reason, ability = "refused", "at the player's own icon", None
        else:
            use = tray_edge(edges[cid], uses)
            ability = use["ability_id"] if use else None
            if use is None:
                outcome, reason = "unknown", "no unique tray edge; an unconstrained nearest name would be forced"
            else:
                pool = [e for e in exemplars.get(ability, []) if e["session_id"] != sid]
                same_map = [e for e in pool if maps.get(e["session_id"]) == demos[sid]["map"]]
                if not pool:
                    outcome, reason = "refused", "no independently labelled exemplar of this ability"
                elif len(same_map) < MIN_EXEMPLARS:
                    outcome = "refused"
                    reason = (f"{len(same_map)} same-map exemplars (<{MIN_EXEMPLARS}); "
                              "candidate size is not normalised across map scales")
                else:
                    outcome, reason = "eligible", "exemplars exist; not scored in this pass"
        outcomes[outcome] += 1
        reasons[reason] += 1
        rows.append({"component_id": cid, "session_id": sid, "tray_ability": ability,
                     "outcome": outcome, "reason": reason})
    values = {"candidates": len(rows), **{k: outcomes[k] for k in ("eligible", "refused", "unknown")},
              "added": 0, "conflicting": 0}
    metrics.record("ability_demo_mining", part="retrieval", values=values,
                   deps={**_deps(), "min_exemplars": MIN_EXEMPLARS},
                   context={"unlabelled_demos": len(set(demos) - labelled)})
    return {"values": values, "reasons": dict(reasons.most_common()),
            "by_session": {s: dict(Counter(r["outcome"] for r in rows if r["session_id"] == s))
                           for s in sorted({r["session_id"] for r in rows})}}


CHARGE_TOL = 0.15


def charges(root: Path) -> dict:
    """Compare each demo cast's tray drop with 1/Uses from the official pages.

    The tray fill is lit pips over total pips, so one cast removes 1/n. The
    tray reader and the page are independent: agreement is consistency between
    two channels, and each disagreement is kept.
    """
    import statistics
    from reticle.ability_timeline import build_timeline
    data = json.loads(REFERENCES.read_text(encoding="utf-8"))["official_uses"]
    uses_of, fuel = data["uses"], set(data["fuel"])
    demos = demo_sessions(root)
    drops = defaultdict(list)
    for use in build_timeline(root)["use_claims"]:
        ability = use.get("ability_id")
        if use["session_id"] not in demos or use.get("status") != "candidate" or ability not in uses_of:
            continue
        raw = use["raw"]
        drops[ability].append({"session": use["session_id"], "t_ms": use["observed_t_ms"],
                               "drop": round(float(raw[2]) - float(raw[3]), 3)})
    rows, matched, total = [], 0, 0
    for ability, casts in sorted(drops.items()):
        n = uses_of[ability]
        ok = [abs(c["drop"] - 1.0 / n) <= CHARGE_TOL for c in casts]
        median = statistics.median(c["drop"] for c in casts)
        nearest = min((1, 2, 3), key=lambda k: abs(median - 1.0 / k))
        if ability not in fuel:
            matched += sum(ok)
            total += len(casts)
        rows.append({"ability_id": ability, "official_uses": n, "casts": len(casts),
                     "matching": sum(ok), "median_drop": median, "nearest_uses": nearest,
                     "fuel": ability in fuel,
                     "role": ("supporting" if nearest == n and all(ok) else
                              "contradicting" if nearest != n else "unresolved"),
                     "drops": casts})
    values = {"abilities": len(rows), "casts": total, "matching": matched,
              "match_rate": round(matched / total, 3) if total else None,
              "abilities_nearest_other": sum(1 for r in rows if r["nearest_uses"] != r["official_uses"]
                                             and not r["fuel"])}
    metrics.record("ability_demo_mining", part="tray-charges", values=values,
                   deps={**_deps(), "tol": CHARGE_TOL, "uses": _pin(uses_of)},
                   context={"demo_sessions": len(demos)})
    return {"values": values, "abilities": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("witness", "facts", "retrieve", "charges"))
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--output", type=Path, default=None,
                        help="facts: directory for hypothesis revisions")
    args = parser.parse_args(argv)
    root = Path(args.store).resolve()
    if args.command == "witness":
        result = witness(root)
    elif args.command == "facts":
        result = facts(root, args.output or root / "analysis" / "domain-hypotheses")
    elif args.command == "charges":
        result = charges(root)
    else:
        result = retrieve(root)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
