"""Accuracy-constrained variable-fidelity observation planning.

The planner decides what evidence a question needs; ``decode.sample_multi``
remains transport. Temporal tiers are executable now. Spatial tiers deliberately
remain native-pixel declarations until a reader is validated at lower fidelity.
Plans refuse unsupported tolerances and budgets instead of degrading silently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path

from .decode import sample_multi
from .refine import merge_windows


ACQUISITION_VERSION = "acquisition-0.1.0"


@dataclass(frozen=True)
class SamplingTier:
    name: str
    hz: float | None  # None resolves to the source's nominal/native rate.
    spatial_scale: float = 1.0
    spatial_basis: str = "native_source_roi"


@dataclass(frozen=True)
class ReaderCapability:
    reader: str
    properties: tuple[str, ...]
    tiers: tuple[SamplingTier, ...]
    regimes: tuple[str, ...] = ("standard",)
    negative_evidence: str = "requires recorded readable coverage"


@dataclass(frozen=True)
class EvidenceRequest:
    request_id: str
    reader: str
    property: str
    alternatives: tuple[str, ...]
    spans_ms: tuple[tuple[float, float], ...]
    max_sample_gap_ms: float
    allowed_tiers: tuple[str, ...]
    reason: str
    regime: str = "standard"
    selection: str = "conflict"


DEFAULT_TIERS = (
    SamplingTier("sparse", 2.0),
    SamplingTier("standard", 10.0),
    SamplingTier("motion", 15.0),
    SamplingTier("native", None),
)

VALID_SELECTIONS = frozenset({"opportunity", "conflict"})


def _effective_hz(tier: SamplingTier, nominal_fps: float) -> float:
    hz = nominal_fps if tier.hz is None else tier.hz
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError("sampling tiers need a finite positive rate")
    return float(hz)


def _validate_request(request: EvidenceRequest) -> list[tuple[float, float]]:
    if not request.request_id or not request.reader or not request.property:
        raise ValueError("request ID, reader and property are required")
    if (not math.isfinite(request.max_sample_gap_ms)
            or request.max_sample_gap_ms <= 0):
        raise ValueError("max_sample_gap_ms must be finite and positive")
    if not request.allowed_tiers:
        raise ValueError("request must allow at least one tier")
    if not request.alternatives:
        raise ValueError("request must name the alternatives it needs to distinguish")
    if not request.reason:
        raise ValueError("request must record why the evidence is needed")
    if request.selection not in VALID_SELECTIONS:
        raise ValueError("selection must be opportunity or conflict")
    return merge_windows(request.spans_ms)


def _validate_capability(name: str, capability: ReaderCapability,
                         nominal_fps: float) -> None:
    if capability.reader != name:
        raise ValueError(f"capability key {name!r} disagrees with reader name")
    if not capability.properties or not capability.tiers or not capability.regimes:
        raise ValueError(f"capability {name!r} must declare properties, tiers and regimes")
    tier_names = [tier.name for tier in capability.tiers]
    if len(tier_names) != len(set(tier_names)):
        raise ValueError(f"capability {name!r} has duplicate tier names")
    for tier in capability.tiers:
        _effective_hz(tier, nominal_fps)
        if tier.spatial_scale != 1.0 or tier.spatial_basis != "native_source_roi":
            raise ValueError(
                "reduced spatial tiers are not executable until separately validated"
            )


def plan_requests(requests: list[EvidenceRequest],
                  capabilities: dict[str, ReaderCapability], nominal_fps: float,
                  max_frames: int | None = None) -> dict:
    """Choose the cheapest tier satisfying each request, then merge routes."""
    if not math.isfinite(nominal_fps) or nominal_fps <= 0:
        raise ValueError("nominal_fps must be finite and positive")
    if max_frames is not None and (isinstance(max_frames, bool)
                                   or not isinstance(max_frames, int)
                                   or max_frames <= 0):
        raise ValueError("max_frames must be a positive integer")
    for name, capability in capabilities.items():
        _validate_capability(name, capability, nominal_fps)
    accepted, refused = [], []
    seen = set()
    for request in requests:
        if request.request_id in seen:
            raise ValueError(f"duplicate request ID: {request.request_id}")
        seen.add(request.request_id)
        spans = _validate_request(request)
        if not spans:
            refused.append({"request_id": request.request_id,
                            "status": "skipped", "reason": "empty_coverage_request"})
            continue
        capability = capabilities.get(request.reader)
        if capability is None or request.property not in capability.properties:
            refused.append({"request_id": request.request_id,
                            "status": "refused", "reason": "unsupported_property"})
            continue
        if request.regime not in capability.regimes:
            refused.append({"request_id": request.request_id,
                            "status": "refused", "reason": "unsupported_regime"})
            continue
        tiers = [tier for tier in capability.tiers if tier.name in request.allowed_tiers]
        tiers.sort(key=lambda tier: _effective_hz(tier, nominal_fps))
        tier = next((tier for tier in tiers
                     if 1000.0 / _effective_hz(tier, nominal_fps)
                     <= request.max_sample_gap_ms), None)
        if tier is None:
            refused.append({"request_id": request.request_id,
                            "status": "refused",
                            "reason": "unsupported_temporal_tolerance"})
            continue
        hz = _effective_hz(tier, nominal_fps)
        seconds = sum(end - start for start, end in spans) / 1000.0
        accepted.append({
            "request": request,
            "spans_ms": spans,
            "tier": tier,
            "hz": hz,
            "estimated_frames": int(math.ceil(seconds * hz)),
        })

    estimated = sum(item["estimated_frames"] for item in accepted)
    if max_frames is not None and estimated > max_frames:
        refused.extend({"request_id": item["request"].request_id,
                        "status": "refused", "reason": "frame_budget_exhausted",
                        "estimated_frames": item["estimated_frames"]}
                       for item in accepted)
        accepted = []
        estimated = 0

    grouped = {}
    for item in accepted:
        tier = item["tier"]
        key = (item["request"].reader, item["hz"], tier.spatial_scale,
               tier.spatial_basis)
        group = grouped.setdefault(key, {"spans": [], "request_ids": [],
                                         "selections": set()})
        group["spans"].extend(item["spans_ms"])
        group["request_ids"].append(item["request"].request_id)
        group["selections"].add(item["request"].selection)
    routes = []
    for index, ((reader, hz, scale, basis), group) in enumerate(sorted(grouped.items()), 1):
        routes.append({
            "route_id": f"route-{index:04d}", "reader": reader, "hz": hz,
            "spans_ms": merge_windows(group["spans"]),
            "spatial_scale": scale, "spatial_basis": basis,
            "request_ids": sorted(group["request_ids"]),
            "selections": sorted(group["selections"]),
        })
    return {
        "producer_version": ACQUISITION_VERSION,
        "nominal_fps": float(nominal_fps),
        "max_frames": max_frames,
        "estimated_frames_conservative": estimated,
        "routes": routes,
        "refused": refused,
        "requests": [asdict(request) for request in requests],
        "limits": [
            "Estimated frames sum routes conservatively and may double-count overlaps.",
            "All current spatial tiers use native source/ROI pixels.",
            "Meeting a sample-gap tolerance does not establish detector recall.",
        ],
    }


def execute_plan(ctx, plan: dict, readers: dict[str, object], progress=None) -> dict:
    """Drive planned routes through one decode and report actual PTS coverage."""
    routes = plan.get("routes", [])
    missing = sorted({route["reader"] for route in routes} - readers.keys())
    if missing:
        raise ValueError(f"missing planned readers: {', '.join(missing)}")
    requests = {route["route_id"]: (route["hz"], route["spans_ms"])
                for route in routes}
    coverage = {route["route_id"]: {"route_id": route["route_id"],
                                    "reader": route["reader"],
                                    "request_ids": route["request_ids"],
                                    "n_frames": 0, "first_t_ms": None,
                                    "last_t_ms": None, "status": "unobserved"}
                for route in routes}
    fed = set()
    retrieved = 0
    for who, sample in sample_multi(str(ctx.media), ctx.fps, requests):
        retrieved += 1
        for route_id in who:
            row = coverage[route_id]
            row["n_frames"] += 1
            row["first_t_ms"] = (sample.t_ms if row["first_t_ms"] is None
                                 else min(row["first_t_ms"], sample.t_ms))
            row["last_t_ms"] = (sample.t_ms if row["last_t_ms"] is None
                                else max(row["last_t_ms"], sample.t_ms))
            row["status"] = "observed"
            reader_name = row["reader"]
            key = (reader_name, sample.frame_idx)
            if key not in fed:
                readers[reader_name].feed(sample)
                fed.add(key)
        if progress:
            progress(retrieved, sample)
    for reader_name in {route["reader"] for route in routes}:
        finish = getattr(readers[reader_name], "finish", None)
        if callable(finish):
            finish()
    return {"producer_version": ACQUISITION_VERSION,
            "retrieved_frames": retrieved,
            "reader_frames": len(fed),
            "coverage": list(coverage.values()),
            "refused": list(plan.get("refused", []))}
