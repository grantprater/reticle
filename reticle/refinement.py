"""Bounded dense HUD evidence linked to an existing coaching review bundle.

Planning reads stored data only. Execution reuses the shipped HUD reader and
requires its cached overlay mask so setup cannot quietly scan the whole capture.
Dense rows remain a separate artifact: they do not rewrite L1 or adjudicate an
event's true onset. Overlapping review windows share one native-rate decode.

Source check (2026-09-07): review ea445110508b26f12d4e on 043bafca271a,
[244000, 258000) ms, returned 840 rows from 244000 to 257983.333 ms. A
max_frames=1 rerun refused without replacing the prior artifact. Reproduce via
`reticle refine 043bafca271a --review-id ea445110508b26f12d4e --execute`.
This validates the window transport, not detector accuracy or refined onset.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .refine import merge_windows
from .review import REVIEW_VERSION
from .version import COACH_VERSION

REFINEMENT_VERSION = "refinement-0.1.0"


def _refinement_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_refinement(store, manifest, bundle, review_ids, max_seconds=30.0):
    """Validate evidence provenance before offering any source-media work."""
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    bundle = Path(bundle)
    report = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
    if (report.get("review_version") != REVIEW_VERSION
            or report.get("coach_version") != COACH_VERSION):
        raise ValueError("stale review definition; rerun coach")
    expected_code = ("coaching.py", "review.py", "rounds.py", "roster.py", "checks.py", "version.py")
    for name in expected_code:
        if report.get("code_sha256", {}).get(name) != _refinement_digest(Path(__file__).with_name(name)):
            raise ValueError(f"stale review producer {name}; rerun coach")
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    inputs = [r for r in report.get("inputs", []) if r.get("session_id") == sid]
    if len(inputs) != 1:
        raise ValueError("review bundle does not uniquely identify this session")
    source = inputs[0]
    for field, path in (("manifest_sha256", store.manifest_path(sid)),
                        ("hud_sha256", store.hud_path(sid, date))):
        if not path.is_file() or source.get(field) != _refinement_digest(path):
            raise ValueError(f"stale review input {field}; rerun coach")
    roster = store.roster_path(sid, date)
    actual_roster = _refinement_digest(roster) if roster.is_file() else None
    if source.get("roster_sha256") != actual_roster:
        raise ValueError("stale review roster; rerun coach")
    rows = [json.loads(line) for line in (bundle / "review.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    requested = set(review_ids)
    if not requested:
        raise ValueError("select at least one review ID")
    selected = [r for r in rows if r.get("review_id") in requested]
    if len(selected) != len(requested) or {r["review_id"] for r in selected} != requested:
        raise ValueError("unknown or duplicate review IDs in bundle")
    duration = manifest["source"].get("duration_ms")
    for row in selected:
        if row.get("session_id") != sid or row.get("review_version") != REVIEW_VERSION:
            raise ValueError("review ID belongs to another session or definition")
        if row.get("source_path") != manifest["source"].get("path"):
            raise ValueError("review source path disagrees with manifest")
        a, z, t = row["clip_start_ms"], row["clip_end_ms"], row["t_ms"]
        if not all(math.isfinite(x) for x in (a, z, t)) or not 0 <= a <= t < z:
            raise ValueError("invalid review interval")
        if duration is not None and z > duration:
            raise ValueError("review interval extends beyond source")
    spans = merge_windows([(r["clip_start_ms"], r["clip_end_ms"]) for r in selected])
    seconds = sum(z-a for a, z in spans) / 1000
    if seconds > max_seconds:
        raise ValueError(f"merged windows need {seconds:.3f}s, exceeding --max-seconds {max_seconds:g}")
    return dict(refinement_version=REFINEMENT_VERSION, session_id=sid,
                review_ids=sorted(requested), spans_ms=spans, seconds=seconds,
                source_path=manifest["source"]["path"], provenance=source,
                review_sha256=_refinement_digest(bundle / "review.jsonl"),
                producer_sha256={name: _refinement_digest(Path(__file__).with_name(name))
                                 for name in ("refinement.py", "refine.py", "cli.py", "ocr.py", "killfeed.py", "profiles.py", "version.py")},
                windows=sorted(selected, key=lambda r: (r["t_ms"], r["review_id"])))


def save_refinement(target, plan, rows):
    """Publish only a completed decode; failures never replace a prior result."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    coverage = []
    for window in plan.get("windows", []):
        times = [r["t_ms"] for r in rows if window["clip_start_ms"] <= r["t_ms"] < window["clip_end_ms"]]
        coverage.append(dict(review_id=window["review_id"], n_frames=len(times),
                             first_t_ms=min(times) if times else None,
                             last_t_ms=max(times) if times else None))
    data = dict(plan, n_frames=len(rows), observations=rows, coverage=coverage,
                limits=["Dense detector observations, not adjudicated event onset.",
                        "Decode exhaustion may shorten coverage; inspect actual timestamps."])
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(target)
