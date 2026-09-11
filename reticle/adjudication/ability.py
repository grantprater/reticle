"""Ability component, entity-grouping, and property hypotheses.

This is milestone C of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  It creates
alternatives for the match-wide adjudicator; it is not a final classifier.
Human component identity can support a parent edge.  It cannot prove that
several components form one physical entity.

Owns [owns:ability-hypothesis].
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ..ability_timeline import build_timeline


ABILITY_ENTITY_VERSION = "ability-entities-0.1.0"
ONSET_GROUP_VERSION = "ability-onset-group-0.1.0"
PERSISTENCE_GROUP_VERSION = "ability-persistence-group-0.1.0"
BEARING_GROUP_VERSION = "ability-bearing-group-0.1.0"
PARENT_PRE_MS = 2000.0
PARENT_POST_MS = 6000.0
ONSET_MS = 300.0
DIST_PX = 60.0
BEARING_TOL_DEG = 15.0
ORPHAN_GAP_MS = 3000.0
ORPHAN_DIST_PX = 120.0
#: "The same place" for an object that does not translate. Tight on purpose: a
#: second device deployed nearby is a different entity, and only a placed
#: ability qualifies at all.
PERSIST_DIST_PX = 12.0

# Versioned domain hypotheses already recorded by the entity model.  These are
# candidate factors until the recording patch and source evidence validate them.
PARAMETER_RULES = {
    "killjoy:alarmbot": {"origin_driver": "enemy-reactive", "bearing_driver": "absent", "extent": "none"},
    "killjoy:turret": {"origin_driver": "fixed", "bearing_driver": "enemy-reactive", "extent": "none"},
    "sova:owl drone": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "tejo:stealth drone": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "fade:prowler": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "skye:trailblazer": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "skye:guiding light": {"origin_driver": "piloted", "bearing_driver": "piloted", "extent": "none"},
    "cypher:spycam": {"origin_driver": "fixed", "bearing_driver": "aimed", "extent": "none"},
    "cypher:trapwire": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "extending"},
    "phoenix:blaze": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "freeform"},
    "viper:toxic screen": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "extending"},
    "sova:hunter's fury": {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "extending"},
    "viper:poison cloud": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "viper:viper's pit": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "jett:cloudburst": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "brimstone:sky smoke": {"origin_driver": "fixed", "bearing_driver": "absent", "extent": "radius"},
    "omen:dark cover": {"origin_driver": "global", "bearing_driver": "absent", "extent": "radius"},
}


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _key(row: dict) -> tuple:
    return (row.get("session_id"), row.get("t_ms"), row.get("x"), row.get("y"))


def _labels(root: Path) -> dict[tuple, dict]:
    """Last append-only answer wins for each preserved source coordinate."""
    out = {}
    folder = root / "labels" / "ability"
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        if ".bak" in path.name:
            continue
        for line_no, row in enumerate(_jsonl(path), 1):
            row = dict(row, _source_path=path.relative_to(root).as_posix(),
                       _source_line=line_no)
            out[_key(row)] = row
    return out


def _label_state(label: dict | None) -> str:
    if not label:
        return "unreviewed"
    if label.get("not_ability"):
        return "clutter"
    if label.get("uncertain"):
        return "uncertain"
    if label.get("agent") and label.get("ability"):
        return "named"
    return "generic" if label.get("category_id") else "unreviewed"


def _ability_id(label: dict | None) -> str | None:
    if label and label.get("agent") and label.get("ability"):
        return f"{label['agent'].casefold()}:{label['ability'].casefold()}"
    return None


def _components(root: Path, labels: dict[tuple, dict]) -> list[dict]:
    """Detector candidates and human labels are both components.

    A label whose coordinates no detector candidate reproduces is still a
    human observation of a thing on the minimap.  Joining on the exact key
    only, and emitting the remainder as ``human_label`` components, keeps the
    corroborated and uncorroborated cases distinguishable without inventing
    an agreement a fuzzy join would manufacture.
    """
    out, consumed = [], set()
    folder = root / "labels" / "ability_candidates"
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        if ".bak" in path.name or ".prefilter" in path.name:
            continue
        sid = path.stem
        for line_no, raw in enumerate(_jsonl(path), 1):
            key = (sid, raw.get("t_ms"), raw.get("x"), raw.get("y"))
            label = labels.get(key)
            if label:
                consumed.add(key)
            out.append({
                "component_id": f"component:{sid}:{raw.get('t_ms')}:{raw.get('x')}:{raw.get('y')}",
                "session_id": sid, "origin": "detector_candidate",
                "observed_t_ms": float(raw.get("t_ms", 0)),
                "observed_end_ms": float(raw.get("t_ms", 0)) + float(raw.get("duration_ms") or 0),
                "x": raw.get("x"), "y": raw.get("y"), "box": raw.get("box"),
                "n_observations": raw.get("n_observations"),
                "source_evidence": [{"path": path.relative_to(root).as_posix(),
                                     "record": line_no}],
                "label_evidence": ({"path": label["_source_path"],
                                    "record": label["_source_line"]} if label else None),
                "label_state": _label_state(label),
                "label_ability_id": _ability_id(label),
                "category_id": label.get("category_id") if label else None,
                "raw": raw,
            })
    for key, label in labels.items():
        if key in consumed:
            continue
        sid, t_ms, x, y = key
        out.append({
            "component_id": f"component:{sid}:{t_ms}:{x}:{y}",
            "session_id": sid, "origin": "human_label",
            "observed_t_ms": float(t_ms or 0),
            "observed_end_ms": float(t_ms or 0) + float(label.get("duration_ms") or 0),
            "x": x, "y": y, "box": label.get("box"),
            "n_observations": label.get("n_observations"),
            "source_evidence": [{"path": label["_source_path"],
                                 "record": label["_source_line"]}],
            "label_evidence": {"path": label["_source_path"],
                               "record": label["_source_line"]},
            "label_state": _label_state(label),
            "label_ability_id": _ability_id(label),
            "category_id": label.get("category_id"),
            "raw": {k: v for k, v in label.items() if not k.startswith("_")},
        })
    return sorted(out, key=lambda r: (r["session_id"], r["observed_t_ms"], r["component_id"]))


def _distance(a: dict, b: dict) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def onset_groups(rows: list[dict]) -> list[list[dict]]:
    groups = []
    for row in sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"])):
        for group in groups:
            if (abs(group[0]["observed_t_ms"] - row["observed_t_ms"]) <= ONSET_MS
                    and any(_distance(row, member) <= DIST_PX for member in group)):
                group.append(row)
                break
        else:
            groups.append([row])
    return groups


def persistence_groups(rows: list[dict]) -> list[list[dict]]:
    """Observations at one position are one entity, however far apart in time.

    A placed ability does not translate, so re-observing a thing where a thing
    already was is the same thing in a later phase -- not a second deployment
    and not a rebirth. Onset grouping cannot say this: it needs a shared onset
    within 300 ms, which a transformation twenty seconds later does not have.

    Transitively linked, so a slow drift across several observations stays one
    group rather than breaking at whichever pair first exceeds the radius.
    """
    groups: list[list[dict]] = []
    for row in sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"])):
        for group in groups:
            if any(_distance(row, member) <= PERSIST_DIST_PX for member in group):
                group.append(row)
                break
        else:
            groups.append([row])
    return groups


def bearing_groups(rows: list[dict]) -> list[list[dict]]:
    """Order-independent circular grouping around the earliest component."""
    rows = sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"]))
    if len(rows) < 2:
        return [rows] if rows else []
    origin = rows[0]
    angles = sorted(((math.degrees(math.atan2(r["y"] - origin["y"],
                                              r["x"] - origin["x"])) % 360.0, r)
                     for r in rows[1:]), key=lambda pair: (pair[0], pair[1]["component_id"]))
    if not angles:
        return [[origin]]
    gaps = [(angles[i + 1][0] - angles[i][0], i) for i in range(len(angles) - 1)]
    gaps.append((360.0 - angles[-1][0] + angles[0][0], len(angles) - 1))
    cuts = {i for gap, i in gaps if gap > BEARING_TOL_DEG}
    if not cuts:
        return [[origin] + [row for _, row in angles]]
    start = (max(cuts) + 1) % len(angles)
    groups, current = [], []
    for offset in range(len(angles)):
        idx = (start + offset) % len(angles)
        current.append(angles[idx][1])
        if idx in cuts:
            groups.append([origin] + current)
            current = []
    if current:
        groups.append([origin] + current)
    return groups


def _mean_bearing(group: list[dict]) -> float | None:
    if len(group) < 2:
        return None
    origin = group[0]
    angles = [math.atan2(r["y"] - origin["y"], r["x"] - origin["x"])
              for r in group[1:]]
    return round(math.degrees(math.atan2(sum(math.sin(a) for a in angles),
                                         sum(math.cos(a) for a in angles))), 1)


def _time_clusters(rows: list[dict], gap_ms: float = ORPHAN_GAP_MS) -> list[list[dict]]:
    """Components that could plausibly be one object share a clip.

    Time alone is not enough. Two components a human has given DIFFERENT ability
    names cannot be one entity -- the label already settles it -- and two objects
    on opposite sides of the map are not one either. Grouping them anyway
    produces a question with no true answer, which is what the first real pass
    hit on its first screen.
    """
    clusters = []
    for row in sorted(rows, key=lambda r: (r["observed_t_ms"], r["component_id"])):
        for cluster in clusters:
            last = cluster[-1]
            named = {c["label_ability_id"] for c in cluster if c["label_ability_id"]}
            mine = row["label_ability_id"]
            if named and mine and mine not in named:
                continue
            if (row["observed_t_ms"] - last["observed_t_ms"] <= gap_ms
                    and _distance(row, last) <= ORPHAN_DIST_PX):
                cluster.append(row)
                break
        else:
            clusters.append([row])
    return clusters


def _orphan_reason(parents: list, contradictions: list, session_uses: list,
                   same_ability: list, named: str | None, label_state: str) -> str | None:
    """Why a component has no parent.  A silent use channel and a use just
    outside the window are different findings, and neither is a group.
    A component a human called clutter is answered, not orphaned."""
    if parents or label_state == "clutter":
        return None
    if contradictions:
        return "only_contradicted_parents"
    if not session_uses:
        return "no_use_claims_in_session"
    if named and not same_ability:
        return "no_use_claim_of_named_ability"
    return "outside_parent_window"


def build_entities(root: str | Path) -> dict:
    root = Path(root).resolve()
    timeline = build_timeline(root)
    labels = _labels(root)
    components = _components(root, labels)
    uses = timeline["use_claims"]
    uses_by_session = defaultdict(list)
    for use in uses:
        uses_by_session[use["session_id"]].append(use)

    component_claims = []
    compatible_by_use = defaultdict(list)
    for component in components:
        parents = []
        contradictions = []
        for use in uses_by_session.get(component["session_id"], []):
            dt = component["observed_t_ms"] - use["observed_t_ms"]
            if not -PARENT_PRE_MS <= dt <= PARENT_POST_MS:
                continue
            named = component.get("label_ability_id")
            if named and named != use.get("ability_id"):
                contradictions.append({"use_claim_id": use["use_claim_id"],
                                       "reason": "human_named_other_ability"})
                continue
            if component["label_state"] == "clutter":
                contradictions.append({"use_claim_id": use["use_claim_id"],
                                       "reason": "human_marked_clutter"})
                continue
            status = "supported" if named == use.get("ability_id") else "candidate"
            parents.append({"use_claim_id": use["use_claim_id"], "status": status,
                            "use_claim_status": use.get("status"),
                            "reason": ("matching_human_component_identity" if status == "supported"
                                       else "temporal_compatibility")})
            compatible_by_use[use["use_claim_id"]].append(component)
        session_uses = uses_by_session.get(component["session_id"], [])
        named = component.get("label_ability_id")
        same = [u for u in session_uses if u.get("ability_id") == named] if named else session_uses
        nearest = (min(same, key=lambda u: (abs(component["observed_t_ms"] - u["observed_t_ms"]),
                                            u["use_claim_id"])) if same else None)
        component_claims.append({
            "component_id": component["component_id"],
            "session_id": component["session_id"],
            "origin": component["origin"],
            "label_state": component["label_state"],
            "possible_parents": sorted(parents, key=lambda r: r["use_claim_id"]),
            "contradicted_parents": sorted(contradictions, key=lambda r: r["use_claim_id"]),
            "orphan_reason": _orphan_reason(parents, contradictions, session_uses, same,
                                            named, component["label_state"]),
            "nearest_use_claim_id": nearest["use_claim_id"] if nearest else None,
            "nearest_use_dt_ms": (round(component["observed_t_ms"] - nearest["observed_t_ms"], 1)
                                  if nearest else None),
            "clutter_alternative": component["label_state"] != "named",
            "unobserved_prior_use_alternative": component["label_state"] != "named",
            "source_evidence": component["source_evidence"],
            "label_evidence": component["label_evidence"],
        })

    hypotheses, properties, review = [], [], []
    for use in uses:
        candidates = compatible_by_use.get(use["use_claim_id"], [])
        supported = [c for c in candidates if c.get("label_ability_id") == use.get("ability_id")]
        null_status = "contradicted" if supported else "candidate"
        hypotheses.append({
            "hypothesis_id": f"entity:null:{use['use_claim_id']}",
            "use_claim_id": use["use_claim_id"], "relation": "spawned_by",
            "grouping_method": "no_observed_spatial_child",
            "component_ids": [], "status": null_status,
            "status_reason": ("matching_human_component_exists" if supported
                              else "ability_may_have_no_minimap_child_or_reader_missed_it"),
        })
        methods = [("onset_proximity", ONSET_GROUP_VERSION, onset_groups(candidates))]
        rule = PARAMETER_RULES.get(use.get("ability_id"))
        if rule and rule["extent"] == "extending":
            methods.append(("bearing", BEARING_GROUP_VERSION, bearing_groups(candidates)))
        # A piloted object translates for its whole life, so position
        # persistence would collapse a flight path into a point. Every other
        # deployed thing holds still, which is what makes the alternative sound.
        if not (rule and rule["origin_driver"] == "piloted"):
            methods.append(("position_persistence", PERSISTENCE_GROUP_VERSION,
                            persistence_groups(candidates)))
        seen_groups = set()
        for method, version, groups in methods:
            for group in groups:
                members = tuple(sorted(c["component_id"] for c in group))
                signature = (method, members)
                if not members or signature in seen_groups:
                    continue
                seen_groups.add(signature)
                human_supported = [c for c in group if c in supported]
                hid = hashlib.sha256((use["use_claim_id"] + method + "|".join(members)).encode()).hexdigest()[:16]
                hypotheses.append({
                    "hypothesis_id": f"entity:{hid}",
                    "use_claim_id": use["use_claim_id"], "relation": "spawned_by",
                    "grouping_method": method, "grouping_version": version,
                    "component_ids": list(members),
                    "status": "supported_components" if human_supported else "proposal",
                    "status_reason": ("contains_matching_human_named_components" if human_supported
                                      else "components_only_temporally_compatible"),
                    "grouping_resolved": len(group) == 1,
                    "grouping_limit": (None if len(group) == 1 else
                                       "component identity does not prove common physical entity"),
                    "treats_appearance_change_as": (
                        "a later PHASE of one entity" if method == "position_persistence"
                        else "a separate observation, which splits a transforming entity"),
                })
                properties.extend(_properties(use, group, f"entity:{hid}", method, rule))
        if len(candidates) != 1 or not supported:
            review.append({
                "review_id": f"ability-group:{use['use_claim_id']}",
                "session_id": use["session_id"], "use_claim_id": use["use_claim_id"],
                "ability_id": use.get("ability_id"),
                "clip_start_ms": max(0.0, use["observed_t_ms"] - PARENT_PRE_MS),
                "clip_end_ms": use["observed_t_ms"] + PARENT_POST_MS,
                "component_ids": sorted(c["component_id"] for c in candidates),
                "question": "Which ringed components are parts of the same entity, separate entities, clutter, or missing?",
                "classes": ["same_entity", "separate_entities", "clutter", "missing_component", "other", "unsure"],
                "status": "unreviewed",
            })

    parented = {r["component_id"] for r in component_claims if r["possible_parents"]}
    orphans = [c for c in components
               if c["component_id"] not in parented and c["label_state"] != "clutter"]
    reason_by_id = {r["component_id"]: r["orphan_reason"] for r in component_claims}
    by_session = defaultdict(list)
    for component in orphans:
        by_session[component["session_id"]].append(component)
    for sid, rows in sorted(by_session.items()):
        for cluster in _time_clusters(rows):
            abilities = sorted({c["label_ability_id"] for c in cluster if c["label_ability_id"]})
            review.append({
                "review_id": f"ability-orphan:{sid}:{int(cluster[0]['observed_t_ms'])}",
                "session_id": sid, "use_claim_id": None,
                "ability_id": abilities[0] if len(abilities) == 1 else None,
                "named_abilities": abilities,
                "clip_start_ms": max(0.0, cluster[0]["observed_t_ms"] - PARENT_PRE_MS),
                "clip_end_ms": max(c["observed_end_ms"] for c in cluster) + PARENT_POST_MS,
                "component_ids": sorted(c["component_id"] for c in cluster),
                "orphan_reasons": sorted({reason_by_id[c["component_id"]] for c in cluster
                                          if reason_by_id.get(c["component_id"])}),
                "question": "No ability use was claimed for these components. Did a use occur here that the use channel missed, are they a still-living entity from an earlier use, or clutter?",
                "classes": ["missed_use", "earlier_use_persisting", "clutter", "other", "unsure"],
                "status": "unreviewed",
            })

    orphan_claims = [r for r in component_claims if r["orphan_reason"]]
    summary = {
        "use_claims": len(uses), "components": len(components),
        "components_by_origin": dict(sorted(Counter(c["origin"] for c in components).items())),
        "orphan_components": len(orphan_claims),
        "orphan_reasons": dict(sorted(Counter(r["orphan_reason"] for r in orphan_claims).items())),
        "human_named_without_supported_parent": sum(
            1 for r in component_claims
            if r["label_state"] == "named"
            and not any(p["status"] == "supported" for p in r["possible_parents"])),
        "human_named_components": sum(c["label_state"] == "named" for c in components),
        "human_clutter_components": sum(c["label_state"] == "clutter" for c in components),
        "component_parent_edges": sum(len(r["possible_parents"]) for r in component_claims),
        # A human name matching a claim the reader itself flagged is not the same
        # evidence as one matching a clean claim, and the gate number must not
        # quietly pool them.
        "supported_parent_edges": sum(
            sum(p["status"] == "supported" and p.get("use_claim_status") != "suspect"
                for p in r["possible_parents"]) for r in component_claims),
        "supported_parent_edges_on_suspect_claims": sum(
            sum(p["status"] == "supported" and p.get("use_claim_status") == "suspect"
                for p in r["possible_parents"]) for r in component_claims),
        "entity_hypotheses": len(hypotheses), "property_claims": len(properties),
        "review_windows": len(review),
        "grouping_methods": dict(sorted(Counter(h["grouping_method"] for h in hypotheses).items())),
    }
    return {
        "manifest": {
            "schema_version": 1, "producer_version": ABILITY_ENTITY_VERSION,
            "timeline_version": timeline["manifest"]["producer_version"],
            "store_root": str(root), "summary": summary,
            "limits": [
                "Group hypotheses are alternatives, not final adjudications.",
                "Human component identity does not prove multi-component grouping.",
                "Parent windows are candidate-generation bounds, not ability lifetime laws.",
                "Parameter rules require patch and source validation before becoming hard constraints.",
                "Onset grouping splits an entity that transforms; position persistence keeps "
                "it whole. Both are offered, and they disagree exactly where it matters.",
            ],
        },
        "component_claims": component_claims,
        "entity_hypotheses": sorted(hypotheses, key=lambda r: (r["use_claim_id"], r["hypothesis_id"])),
        "properties": sorted(properties, key=lambda r: (r["hypothesis_id"], r["property"])),
        "review": sorted(review, key=lambda r: (r["session_id"], r["clip_start_ms"])),
    }


def _properties(use: dict, group: list[dict], hypothesis_id: str,
                method: str, rule: dict | None) -> list[dict]:
    source = "human_observed" if any(c["label_state"] == "named" for c in group) else "detector_observed"
    times = [c["observed_t_ms"] for c in group]
    ends = [c["observed_end_ms"] for c in group]
    rows = [
        {"hypothesis_id": hypothesis_id, "property": "existence_interval_ms",
         "value": [min(times), max(ends)], "units": "source_ms", "source_kind": source,
         "status": "observed_components"},
        {"hypothesis_id": hypothesis_id, "property": "component_count",
         "value": len(group), "units": "components", "source_kind": source,
         "status": "observed_components"},
        {"hypothesis_id": hypothesis_id, "property": "origin",
         "value": [group[0]["x"], group[0]["y"]] if method == "bearing" else None,
         "units": "minimap_roi_px", "source_kind": "inferred" if method == "bearing" else "unknown",
         "status": "proposal" if method == "bearing" else "unresolved"},
        {"hypothesis_id": hypothesis_id, "property": "bearing",
         "value": _mean_bearing(group) if method == "bearing" else None,
         "units": "degrees_image_xy", "source_kind": "inferred" if method == "bearing" else "unknown",
         "status": "proposal" if method == "bearing" else "unresolved"},
    ]
    if rule:
        for prop in ("origin_driver", "bearing_driver", "extent"):
            rows.append({
                "hypothesis_id": hypothesis_id, "property": prop,
                "value": rule[prop], "units": None, "source_kind": "reference_derived",
                "status": "domain_hypothesis_needs_patch_validation",
                "rule_scope": use.get("ability_id"),
            })
    return rows


def write_entities(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("component_claims", "entity_hypotheses", "properties", "review"):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in bundle[name]),
            encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(bundle["manifest"], indent=2, sort_keys=True),
                                       encoding="utf-8")
    return out
