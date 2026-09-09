"""Build ability-use claims from independent stored evidence.

Milestone B of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  Tray drops are
bounded observations of a state transition, not unconditional casts.  This
module preserves the possible transition meanings and never requires a minimap
candidate.  Optional materialization drives the existing prototype reader over
demo sources, then consumes its version-stamped caches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .ability_coverage import build_inventory
from .store import DEFAULT_STORE


ABILITY_TIMELINE_VERSION = "ability-timeline-0.1.0"
_STEP = re.compile(r"\.step(\d+(?:\.\d+)?)\.")
TRANSITION_ALTERNATIVES = ("commit", "activation", "mode_transition", "end")


def _step_ms(source_path: str) -> float | None:
    match = _STEP.search(Path(source_path).name)
    if not match:
        return None
    try:
        step = float(match.group(1)) * 1000.0
    except ValueError:
        return None
    return step if step > 0 else None


def _audio_references(root: Path) -> list[dict]:
    out = []
    folder = root / "reference" / "assets" / "ability_sfx"
    # The established filename contract ends in __SESSION_TIMEs.ext.  Earlier
    # name portions are descriptive only and cannot override reference identity.
    pattern = re.compile(r"__(?P<session>[0-9a-f]+)_(?P<time>[0-9.]+)s\.[^.]+$")
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        if not path.is_file():
            continue
        match = pattern.search(path.name)
        if not match:
            continue
        out.append({
            "path": path.relative_to(root).as_posix(),
            "session_id": match.group("session"),
            "t_ms": float(match.group("time")) * 1000.0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return out


def build_timeline(root: str | Path) -> dict:
    """Return deterministic use claims from the current evidence inventory."""
    root = Path(root).resolve()
    inventory = build_inventory(root)
    source_hashes = {r["path"]: r["sha256"]
                     for r in inventory["manifest"]["source_files"]}
    audio = _audio_references(root)
    spectated = {row["session_id"] for row in inventory["sessions"]
                 if "spectator" in (row.get("tags") or [])}
    labels_by_ability = defaultdict(list)
    for row in inventory["source_windows"]:
        if row["source_kind"] == "human_ability_label" and row.get("ability_id"):
            labels_by_ability[(row["session_id"], row["ability_id"])].append(row)

    claims = []
    for row in inventory["source_windows"]:
        if row["source_kind"] != "tray_cast_candidate":
            continue
        t_ms = float(row["t_observed_ms"])
        step_ms = _step_ms(row["source_path"])
        occurrence_start = max(0.0, t_ms - step_ms) if step_ms else None
        label_candidates = [
            r["window_id"] for r in labels_by_ability.get(
                (row["session_id"], row.get("ability_id")), [])
            if t_ms - 2000.0 <= r["t_observed_ms"] <= t_ms + 15000.0
        ] if row.get("ability_id") else []
        audio_candidates = [
            a for a in audio if a["session_id"] == row["session_id"]
            and abs(a["t_ms"] - t_ms) <= max(step_ms or 0.0, 100.0)
        ]
        source_ref = {
            "path": row["source_path"],
            "record": row["source_record"],
            "sha256": source_hashes.get(row["source_path"]),
        }
        claims.append({
            "use_claim_id": f"use:{row['session_id']}:{Path(row['source_path']).name}:"
                            f"{row['source_record']}",
            "session_id": row["session_id"],
            "agent": row.get("agent"),
            "ability_id": row.get("ability_id"),
            "ability": row.get("ability"),
            "slot": row.get("key"),
            # A spectator clip reads the OBSERVED player's tray, so the caster is
            # whoever the camera is on, not whoever is holding the mouse.
            "owner": (None if not row.get("agent")
                      else "observed_player" if row["session_id"] in spectated
                      else "local_player"),
            "observed_t_ms": t_ms,
            "available_t_ms": t_ms,
            "occurrence_interval_ms": [occurrence_start, t_ms],
            "sampling_step_ms": step_ms,
            "transition": None,
            "transition_alternatives": list(TRANSITION_ALTERNATIVES),
            "status": "suspect" if row.get("suspect") else "candidate",
            "status_reason": ("reader_flagged_drop" if row.get("suspect")
                              else "single_slot_drop"),
            "identity_status": ("setup_agent_and_reference_slot" if row.get("ability_id")
                                else "unresolved"),
            "source_evidence": [source_ref],
            "audio_reference_candidates": audio_candidates,
            "human_label_candidates": sorted(label_candidates),
            "minimap_required": False,
            "raw": row.get("raw"),
        })

    # A reader change creates a new cache beside the old one.  Equivalent rows
    # are two provenance roots for one observation, not two game events.
    equivalent = defaultdict(list)
    for claim in claims:
        key = (claim["session_id"], claim["observed_t_ms"], claim["slot"],
               json.dumps(claim.get("raw"), sort_keys=True))
        equivalent[key].append(claim)
    merged_claims = []
    for key, same in equivalent.items():
        claim = dict(same[0])
        claim["source_evidence"] = sorted(
            (e for row in same for e in row["source_evidence"]),
            key=lambda e: (e["path"], e["record"]),
        )
        raw_key = hashlib.sha256(key[3].encode()).hexdigest()[:8]
        claim["use_claim_id"] = (f"use:{key[0]}:{key[1]:g}:{key[2]}:{raw_key}")
        merged_claims.append(claim)
    claims = merged_claims

    conflicts = list(inventory["conflicts"])
    grouped = defaultdict(list)
    for claim in claims:
        grouped[(claim["session_id"], claim["observed_t_ms"], claim["slot"])].append(claim)
    for key, alternatives in grouped.items():
        raw_values = {json.dumps(c.get("raw"), sort_keys=True) for c in alternatives}
        if len(raw_values) > 1:
            conflicts.append({
                "reason": "multiple_cast_cache_interpretations",
                "session_id": key[0], "observed_t_ms": key[1], "slot": key[2],
                "use_claim_ids": sorted(c["use_claim_id"] for c in alternatives),
            })

    claims.sort(key=lambda r: (r["session_id"], r["observed_t_ms"], r["use_claim_id"]))
    summary = {
        "use_claims": len(claims),
        "equivalent_cache_rows_collapsed": sum(len(v) - 1 for v in equivalent.values()),
        "sessions_with_claims": len({r["session_id"] for r in claims}),
        "clean_candidates": sum(r["status"] == "candidate" for r in claims),
        "suspect_candidates": sum(r["status"] == "suspect" for r in claims),
        "identified_candidates": sum(r["ability_id"] is not None for r in claims),
        "audio_reference_candidates": sum(bool(r["audio_reference_candidates"]) for r in claims),
        "label_candidate_links": sum(len(r["human_label_candidates"]) for r in claims),
        "by_slot": dict(sorted(Counter(r["slot"] for r in claims).items())),
        "conflicts": len(conflicts),
    }
    return {
        "manifest": {
            "schema_version": 1,
            "producer_version": ABILITY_TIMELINE_VERSION,
            "store_root": str(root),
            "coverage_producer_version": inventory["manifest"]["producer_version"],
            "source_files": inventory["manifest"]["source_files"],
            "audio_reference_files": audio,
            "summary": summary,
            "limits": [
                "Tray drops are use candidates, not resolved cast semantics.",
                "Source-linked audio cuts are references, not independent detections.",
                "Human label links are temporal candidates, not parent-child adjudications.",
            ],
        },
        "use_claims": claims,
        "conflicts": sorted(conflicts, key=lambda r: json.dumps(r, sort_keys=True)),
    }


def write_timeline(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("use_claims", "conflicts"):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in bundle[name]),
            encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    return out


def materialize_demo_casts(root: str | Path, step_s: float = 0.5) -> dict:
    """Drive the existing tray reader over every tagged demo source.

    This is the only media-reading part of milestone B.  It writes new,
    reader-hash-keyed cache files and never replaces labels or old caches.
    """
    if step_s <= 0:
        raise ValueError("step must be positive")
    root = Path(root).resolve()
    # The reader still owns prototype-specific calibration.  Bind its existing
    # path parameters explicitly so a non-default test store cannot leak into
    # the user's store.
    from prototypes import ability_cast as cast
    from prototypes import ability_hud as hud

    cast.STORE = hud.STORE = root
    cast.LAB = root / "labels" / "ability"
    cast.CACHE = root / "casts"
    cast.CAND = root / "labels" / "ability_candidates"
    cast.EVENTS = root / "events" / "ability"
    manifests = []
    for path in sorted((root / "manifests").glob("*.json")):
        man = json.loads(path.read_text(encoding="utf-8"))
        if "ability-demo" in man.get("tags", []):
            manifests.append(man)
    result = []
    for man in manifests:
        sid = man["session_id"]
        before = set((root / "casts").glob(f"{sid}.step{step_s}.*.json"))
        rows, agent = cast.tray_casts(sid, step_s=step_s, use_cache=True)
        after = set((root / "casts").glob(f"{sid}.step{step_s}.*.json"))
        result.append({
            "session_id": sid, "agent": agent, "n_candidates": len(rows),
            "cache_paths": sorted(p.relative_to(root).as_posix() for p in after),
            "created": sorted(p.relative_to(root).as_posix() for p in after - before),
        })
    return {"sessions": result, "candidates": sum(r["n_candidates"] for r in result)}


def run(root: str | Path = DEFAULT_STORE, out: str | Path | None = None,
        *, materialize: bool = False, step_s: float = 0.5) -> tuple[dict, dict | None]:
    materialized = materialize_demo_casts(root, step_s) if materialize else None
    bundle = build_timeline(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-timeline"
    write_timeline(bundle, target)
    return bundle, materialized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--step", type=float, default=0.5)
    args = parser.parse_args(argv)
    bundle, materialized = run(args.store, args.out, materialize=args.materialize,
                               step_s=args.step)
    if materialized:
        print(f"materialized {materialized['candidates']} candidates across "
              f"{len(materialized['sessions'])} demos")
    summary = bundle["manifest"]["summary"]
    print(f"{summary['use_claims']} use claims across {summary['sessions_with_claims']} sessions; "
          f"{summary['suspect_candidates']} suspect; {summary['conflicts']} conflicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
