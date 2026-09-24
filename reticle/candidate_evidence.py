"""Validate immutable reader candidates and replayable decisions.

The contract is shared by readers. It checks the fitted-hypothesis boundary,
not pixel recall. A producer must record every hypothesis it hands to this API.
"""

from __future__ import annotations

import hashlib
import json

CANDIDATE_CONTRACT_VERSION = "candidate-contract-0.1.0"
REQUIRED_MEASUREMENTS = {
    "ally_icon": ("cx", "cy", "r", "cov", "inner", "inner_v", "lobe",
                  "area", "widget_scale", "facing", "facing_reason",
                  "map_diff", "map_diff_reason", "descriptor",
                  "descriptor_reason", "descriptor_pixels", "self_occluder",
                  "baseline_descriptor", "baseline_map_diff", "baseline_reason",
                  "self_occluder_candidate_key", "neighbor_candidate_keys"),
}
VERDICT_FIELDS = {"disposition", "family", "barrier", "agent", "name",
                  "identity_status", "preferred_candidate_key"}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def revision(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_candidates(rows: list[dict], producer: str | None = None) -> None:
    keys = set()
    for row in rows:
        if row.get("kind") != "candidate":
            raise ValueError("raw batch accepts candidate rows only")
        key = row.get("candidate_key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError(f"missing or duplicate candidate key: {key!r}")
        if row.get("frame_idx") is None or row.get("t_ms") is None:
            raise ValueError(f"candidate has no source instant: {key}")
        if not row.get("reader_version"):
            raise ValueError(f"candidate has no reader version: {key}")
        forbidden = VERDICT_FIELDS.intersection(row)
        if forbidden:
            raise ValueError(f"raw candidate contains verdict fields: {sorted(forbidden)}")
        missing = set(REQUIRED_MEASUREMENTS.get(producer, ())) - row.keys()
        if missing:
            raise ValueError(f"candidate lacks measurements: {sorted(missing)}")
        for field, reason in (("facing", "facing_reason"),
                              ("map_diff", "map_diff_reason"),
                              ("descriptor", "descriptor_reason")):
            if field in row and row[field] is None and not row.get(reason):
                raise ValueError(f"candidate has null {field} without reason: {key}")
        keys.add(key)


def validate_decisions(candidates: list[dict], decisions: list[dict],
                       producer: str | None = None) -> None:
    validate_candidates(candidates, producer)
    by_key = {row["candidate_key"]: row for row in candidates}
    keys = set(by_key)
    seen = set()
    for row in decisions:
        key = row.get("candidate_key")
        if row.get("kind") != "decision" or key not in keys or key in seen:
            raise ValueError(f"missing, foreign, or duplicate decision: {key!r}")
        if row.get("disposition") not in {"accepted", "rejected", "suppressed", "unresolved"}:
            raise ValueError(f"invalid disposition: {key}")
        if not row.get("rule_version") or not row.get("reason"):
            raise ValueError(f"decision lacks rule version or reason: {key}")
        preferred = row.get("preferred_candidate_key")
        if preferred is not None and (preferred not in keys or preferred == key or
                                      by_key[preferred]["frame_idx"] != by_key[key]["frame_idx"] or
                                      by_key[preferred].get("channel") != by_key[key].get("channel")):
            raise ValueError(f"invalid preferred candidate: {key}")
        seen.add(key)
    if seen != keys:
        raise ValueError(f"undecided candidates: {sorted(keys - seen)[:5]}")
    verdicts = {r["candidate_key"]: r for r in decisions}
    for row in decisions:
        preferred = row.get("preferred_candidate_key")
        if preferred and (row["disposition"] != "suppressed" or
                          verdicts[preferred]["disposition"] != "accepted"):
            raise ValueError("suppression must reference an accepted survivor")
    for row in candidates:
        if row.get("channel") != "ally":
            continue
        key = row["candidate_key"]
        occluder = row.get("self_occluder_candidate_key")
        if occluder is not None and (
                occluder not in by_key or by_key[occluder]["channel"] != "self" or
                by_key[occluder]["frame_idx"] != row["frame_idx"] or
                verdicts[occluder]["disposition"] != "accepted"):
            raise ValueError(f"invalid self occluder dependency: {key}")
        for neighbor in row.get("neighbor_candidate_keys", []):
            if (neighbor not in by_key or neighbor == key or
                    by_key[neighbor]["channel"] != "ally" or
                    by_key[neighbor]["frame_idx"] != row["frame_idx"] or
                    verdicts[neighbor]["disposition"] != "accepted"):
                raise ValueError(f"invalid neighbor dependency: {key}")
