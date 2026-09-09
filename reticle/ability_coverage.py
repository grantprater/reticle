"""Inventory existing ability evidence without decoding or adjudicating it.

This is milestone A of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  It indexes
source windows and reports property-level coverage.  It never treats a missing
candidate, label, or tray drop as evidence that an ability was absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .store import DEFAULT_STORE


ABILITY_COVERAGE_VERSION = "ability-coverage-0.1.0"
PROPERTY_GROUPS = (
    "identity", "causality", "time", "geometry", "motion", "function",
    "state", "resources", "durability", "observation",
)
CAST_PROPERTIES = {"identity", "causality", "time", "resources"}
LABEL_PROPERTIES = {"identity", "observation"}
IGNORED_SUFFIXES = (".bak", ".reviewed", ".prefilter")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            row["_source_line"] = line_no
            rows.append(row)
    return rows


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _agent_tag(manifest: dict, known: dict[str, str]) -> str | None:
    tags = {str(tag).casefold() for tag in manifest.get("tags", [])}
    found = [canonical for folded, canonical in known.items() if folded in tags]
    return found[0] if len(found) == 1 else None


def _source_record(path: Path, root: Path, kind: str) -> dict:
    return {
        "kind": kind,
        "path": path.relative_to(root).as_posix(),
        "sha256": _digest(path),
    }


def _ability_id(agent: str, ability: str) -> str:
    return f"{agent.casefold()}:{ability.casefold()}"


def _definition_rows(reference: dict) -> list[dict]:
    rows = []
    for agent, record in sorted(reference.get("agents", {}).items()):
        for ability in record.get("abilities", []):
            name = ability.get("name")
            if not name:
                continue
            rows.append({
                "ability_id": _ability_id(agent, name),
                "agent": agent,
                "ability": name,
                "slot": ability.get("slot"),
                "key": ability.get("key"),
                "table_kind": ability.get("table_kind"),
                "cost": ability.get("cost"),
                "charges": ability.get("charges"),
                "functions": ability.get("functions"),
                "description": ability.get("description"),
                "mode": "unspecified",
                "reference_harvested": reference.get("harvested"),
            })
    return rows


def _usable_files(folder: Path, suffix: str) -> list[Path]:
    if not folder.is_dir():
        return []
    return [path for path in sorted(folder.glob(f"*{suffix}"))
            if not any(mark in path.name for mark in IGNORED_SUFFIXES)]


def _session_id(path: Path) -> str:
    return path.name.split(".", 1)[0]


def _cast_rows(root: Path, definitions: list[dict]) -> tuple[list[dict], list[dict]]:
    by_agent_key = {(r["agent"].casefold(), (r.get("key") or "").upper()): r
                    for r in definitions if r.get("key")}
    manifests = {}
    known = {r["agent"].casefold(): r["agent"] for r in definitions}
    for path in sorted((root / "manifests").glob("*.json")):
        manifests[path.stem] = _json(path)

    rows, conflicts = [], []
    for path in _usable_files(root / "casts", ".json"):
        sid = _session_id(path)
        manifest = manifests.get(sid)
        if manifest is None:
            conflicts.append({"source": path.relative_to(root).as_posix(),
                              "reason": "missing_manifest"})
            continue
        agent = _agent_tag(manifest, known)
        duration = float(manifest.get("source", {}).get("duration_ms") or 0.0)
        for line_no, raw in enumerate(_json(path), 1):
            if len(raw) < 2:
                conflicts.append({"source": path.relative_to(root).as_posix(),
                                  "record": line_no, "reason": "malformed_cast"})
                continue
            t_ms, key = float(raw[0]) * 1000.0, str(raw[1]).upper()
            definition = by_agent_key.get(((agent or "").casefold(), key))
            rows.append({
                "window_id": f"cast:{sid}:{path.name}:{line_no}",
                "session_id": sid,
                "source_kind": "tray_cast_candidate",
                "source_path": path.relative_to(root).as_posix(),
                "source_record": line_no,
                "t_start_ms": max(0.0, t_ms - 2000.0),
                "t_observed_ms": t_ms,
                "t_end_ms": min(duration, t_ms + 6000.0) if duration else t_ms + 6000.0,
                "agent": agent,
                "key": key,
                "ability_id": definition["ability_id"] if definition else None,
                "ability": definition["ability"] if definition else None,
                "suspect": bool(raw[4]) if len(raw) > 4 else None,
                "raw": raw,
            })
            if definition is None:
                conflicts.append({"source": path.relative_to(root).as_posix(),
                                  "record": line_no, "reason": "unresolved_agent_slot",
                                  "agent": agent, "key": key})
    return rows, conflicts


def _label_rows(root: Path, definitions: list[dict]) -> tuple[list[dict], list[dict]]:
    known = {r["ability_id"]: r for r in definitions}
    rows, conflicts = [], []
    for path in _usable_files(root / "labels" / "ability", ".jsonl"):
        sid = _session_id(path)
        for raw in _jsonl(path):
            if raw.get("not_ability") or raw.get("uncertain"):
                continue
            agent, ability = raw.get("agent"), raw.get("ability")
            aid = _ability_id(agent, ability) if agent and ability else None
            resolved = known.get(aid or "")
            rows.append({
                "window_id": f"label:{sid}:{raw['_source_line']}",
                "session_id": sid,
                "source_kind": "human_ability_label",
                "source_path": path.relative_to(root).as_posix(),
                "source_record": raw["_source_line"],
                "t_start_ms": max(0, float(raw.get("t_ms", 0)) - 1000.0),
                "t_observed_ms": float(raw.get("t_ms", 0)),
                "t_end_ms": float(raw.get("t_ms", 0)) + 1000.0,
                "agent": agent or None,
                "ability_id": resolved["ability_id"] if resolved else None,
                "ability": resolved["ability"] if resolved else (ability or None),
                "category_id": raw.get("category_id"),
                "x": raw.get("x"),
                "y": raw.get("y"),
                "legacy_key": [sid, raw.get("t_ms"), raw.get("x"), raw.get("y")],
            })
            if aid and resolved is None:
                conflicts.append({"source": path.relative_to(root).as_posix(),
                                  "record": raw["_source_line"],
                                  "reason": "label_not_in_reference",
                                  "agent": agent, "ability": ability})
    return rows, conflicts


def build_inventory(root: str | Path) -> dict:
    """Build a deterministic, stored-data-only evidence inventory."""
    root = Path(root).resolve()
    ref_path = root / "reference" / "abilities.json"
    if not ref_path.is_file():
        raise FileNotFoundError(f"missing ability reference: {ref_path}")
    reference = _json(ref_path)
    definitions = _definition_rows(reference)
    known_agents = {r["agent"].casefold(): r["agent"] for r in definitions}

    sessions = []
    manifests = {}
    manifest_paths = []
    for path in sorted((root / "manifests").glob("*.json")):
        manifest = _json(path)
        sid = manifest.get("session_id", path.stem)
        manifests[sid] = manifest
        manifest_paths.append(path)
        tags = manifest.get("tags", [])
        if "ability-demo" not in tags:
            continue
        agent = _agent_tag(manifest, known_agents)
        media_path = Path(manifest.get("source", {}).get("path", ""))
        sessions.append({
            "session_id": sid,
            "agent": agent,
            "duration_ms": manifest.get("source", {}).get("duration_ms"),
            "source_profile": manifest.get("source_profile"),
            "source_available": media_path.is_file(),
            "content_key": manifest.get("source", {}).get("content_key"),
            "tags": tags,
            "evidence": {},
        })

    evidence_files = {
        "candidate_labels": _usable_files(root / "labels" / "ability_candidates", ".jsonl"),
        "human_labels": _usable_files(root / "labels" / "ability", ".jsonl"),
        "native_series": _usable_files(root / "series", ".npz"),
        "cast_caches": _usable_files(root / "casts", ".json"),
        "ability_sfx": sorted((root / "reference" / "assets" / "ability_sfx").glob("*")),
        "voicelines": sorted((root / "reference" / "assets" / "voicelines").glob("*")),
    }
    evidence_by_session = defaultdict(lambda: defaultdict(list))
    sources = ([_source_record(ref_path, root, "ability_reference")] +
               [_source_record(path, root, "manifest") for path in manifest_paths])
    for kind, paths in evidence_files.items():
        for path in paths:
            if not path.is_file():
                continue
            sources.append(_source_record(path, root, kind))
            if kind not in {"ability_sfx", "voicelines"}:
                evidence_by_session[_session_id(path)][kind].append(
                    path.relative_to(root).as_posix())
    for session in sessions:
        session["evidence"] = dict(sorted(evidence_by_session[session["session_id"]].items()))

    casts, cast_conflicts = _cast_rows(root, definitions)
    labels, label_conflicts = _label_rows(root, definitions)
    windows = sorted(casts + labels,
                     key=lambda r: (r["session_id"], r["t_observed_ms"], r["window_id"]))
    by_ability = defaultdict(list)
    for window in windows:
        if window.get("ability_id"):
            by_ability[window["ability_id"]].append(window)
    demos_by_agent = defaultdict(list)
    for session in sessions:
        if session["agent"]:
            demos_by_agent[session["agent"]].append(session["session_id"])

    coverage = []
    for definition in definitions:
        relevant = by_ability.get(definition["ability_id"], [])
        cast_windows = [w for w in relevant if w["source_kind"] == "tray_cast_candidate"]
        clean_casts = [w for w in cast_windows if w.get("suspect") is False]
        label_windows = [w for w in relevant if w["source_kind"] == "human_ability_label"]
        for prop in PROPERTY_GROUPS:
            supporting = []
            status = "not_exercised"
            reason = "no_property_specific_evidence"
            if prop in LABEL_PROPERTIES and label_windows:
                status, reason = "supported", "human_named_source_observation"
                supporting.extend(w["window_id"] for w in label_windows)
            if prop in CAST_PROPERTIES and cast_windows and status != "supported":
                status = "weak"
                reason = ("clean_tray_cast_candidate" if clean_casts
                          else "suspect_tray_cast_candidate_only")
                supporting.extend(w["window_id"] for w in cast_windows)
            if not demos_by_agent.get(definition["agent"]) and not supporting:
                reason = "no_tagged_demo_or_property_specific_evidence"
            coverage.append({
                "ability_id": definition["ability_id"],
                "agent": definition["agent"],
                "ability": definition["ability"],
                "key": definition.get("key"),
                "mode": definition["mode"],
                "property_group": prop,
                "perspective": "local_player",
                "capture_regime": "ability_demo",
                "status": status,
                "status_reason": reason,
                "source_window_ids": sorted(set(supporting)),
                "demo_session_ids": sorted(demos_by_agent.get(definition["agent"], [])),
                "reference_available": True,
                "remaining_alternatives": ([] if status == "supported" else
                    ["property_not_observed", "source_not_yet_reviewed"]),
                "capture_request_id": None,
            })

    conflicts = sorted(cast_conflicts + label_conflicts,
                       key=lambda r: (r["source"], r.get("record", 0), r["reason"]))
    summary = {
        "definitions": len(definitions),
        "agents": len({r["agent"] for r in definitions}),
        "demo_sessions": len(sessions),
        "demo_duration_ms": sum(float(s.get("duration_ms") or 0) for s in sessions),
        "source_windows": len(windows),
        "cast_windows": len(casts),
        "human_label_windows": len(labels),
        "coverage_rows": len(coverage),
        "coverage_statuses": dict(sorted(Counter(r["status"] for r in coverage).items())),
        "conflicts": len(conflicts),
    }
    return {
        "manifest": {
            "schema_version": 1,
            "producer_version": ABILITY_COVERAGE_VERSION,
            "store_root": str(root),
            "source_files": sorted(sources, key=lambda r: (r["kind"], r["path"])),
            "summary": summary,
        },
        "definitions": definitions,
        "sessions": sorted(sessions, key=lambda r: r["session_id"]),
        "source_windows": windows,
        "coverage": coverage,
        "conflicts": conflicts,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8")


def write_inventory(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("definitions", "sessions", "source_windows", "coverage", "conflicts"):
        _write_jsonl(out / f"{name}.jsonl", bundle[name])
    (out / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    return out


def run(root: str | Path = DEFAULT_STORE, out: str | Path | None = None) -> dict:
    bundle = build_inventory(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-coverage"
    write_inventory(bundle, target)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    bundle = run(args.store, args.out)
    summary = bundle["manifest"]["summary"]
    print(f"{summary['definitions']} abilities; {summary['demo_sessions']} demo sessions; "
          f"{summary['source_windows']} source windows")
    print(f"coverage {summary['coverage_statuses']}; conflicts {summary['conflicts']}")
    print(Path(args.out) if args.out else Path(args.store) / "analysis" / "ability-coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
