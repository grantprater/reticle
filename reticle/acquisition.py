"""Accuracy-constrained variable-fidelity observation planning.

The planner decides what evidence a question needs; ``decode`` remains
transport. Temporal tiers are executable now. Spatial tiers deliberately remain
native-pixel declarations until a reader is validated at lower fidelity. Plans
refuse unsupported tolerances and budgets instead of degrading silently.

**The tier is not where the saving is.** Measured 2026-09-09 on c40d950031bb
over one 10 s window at 850 s, ``decode.sample_multi`` cost 49.74 s at 60 Hz and
48.80 s at 2 Hz -- 28.6x fewer frames for 1.9% less time -- because it grabs the
file from the start to the last timestamp anyone asked for. Seeking to the window
instead costs 2.51 s and 1.10 s for the same frames. So a plan reports
``covered_span_seconds`` and ``reach_seconds`` beside its frame estimate, and
``execute_plan`` picks the transport whose cost law matches the coverage it was
handed. A frame count alone described neither.

Owns [owns:evidence-plan].
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .decode import sample_multi, sample_windows
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


# Below this share of its own reach, coverage is sparse enough that a seek per
# window beats grabbing everything between the windows. At 1.0 the requests are
# one contiguous block and the sequential pass has nothing to skip.
SEEK_COVERAGE_FRACTION = 0.5


def _choose_transport(span_seconds: float, reach_seconds: float) -> str:
    """Name the transport whose cost law fits this coverage, and why.

    Neither transport is faster in general: `sample_multi` pays for the whole
    prefix once, `sample_windows` pays a seek per window. The crossover is how
    much of the prefix the request actually wants.
    """
    if reach_seconds <= 0:
        return "none"
    if span_seconds / reach_seconds < SEEK_COVERAGE_FRACTION:
        return "seek_windows"
    return "sequential_grab"


def plan_requests(requests: list[EvidenceRequest],
                  capabilities: dict[str, ReaderCapability], nominal_fps: float,
                  max_frames: int | None = None) -> dict:
    """Choose the cheapest tier satisfying each request, then merge routes."""
    if (isinstance(nominal_fps, bool) or not isinstance(nominal_fps, (int, float))
            or not math.isfinite(nominal_fps) or nominal_fps <= 0):
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
    covered = merge_windows([span for route in routes for span in route["spans_ms"]])
    span_seconds = sum(end - start for start, end in covered) / 1000.0
    reach_seconds = (covered[-1][1] / 1000.0) if covered else 0.0
    transport = _choose_transport(span_seconds, reach_seconds)
    return {
        "producer_version": ACQUISITION_VERSION,
        "nominal_fps": float(nominal_fps),
        "max_frames": max_frames,
        "estimated_frames_conservative": estimated,
        "covered_span_seconds": span_seconds,
        "reach_seconds": reach_seconds,
        "transport": transport,
        "routes": routes,
        "refused": refused,
        "requests": [asdict(request) for request in requests],
        "limits": [
            "Estimated frames sum routes conservatively and may double-count overlaps.",
            "Frames are NOT the cost. Measured 2026-09-09 on c40d950031bb, one 10 s "
            "window at 850 s: under the sequential transport 60 Hz and 2 Hz cost "
            "49.74 s and 48.80 s for 601 and 21 frames -- a 28.6x frame cut buying "
            "1.9%. Cost tracks covered_span_seconds under the seeking transport and "
            "reach_seconds under the sequential one.",
            "All current spatial tiers use native source/ROI pixels.",
            "Meeting a sample-gap tolerance does not establish detector recall.",
        ],
    }


def _parse_requests(raw_requests: list) -> list[EvidenceRequest]:
    """One parser for the public request shape, whichever registry serves it."""
    return [EvidenceRequest(
        request_id=raw["request_id"], reader=raw["reader"],
        property=raw["property"], alternatives=tuple(raw["alternatives"]),
        spans_ms=tuple(tuple(span) for span in raw["spans_ms"]),
        max_sample_gap_ms=raw["max_sample_gap_ms"],
        allowed_tiers=tuple(raw["allowed_tiers"]), reason=raw["reason"],
        regime=raw.get("regime", "standard"),
        selection=raw.get("selection", "conflict"),
    ) for raw in raw_requests]


def plan_spec(spec: dict) -> dict:
    """Parse the public JSON planning contract and return an executable plan."""
    if not isinstance(spec, dict):
        raise ValueError("acquisition spec must be a JSON object")
    raw_capabilities = spec.get("capabilities")
    raw_requests = spec.get("requests")
    if not isinstance(raw_requests, list):
        raise ValueError("requests must be a JSON array")
    # `"capabilities": "builtin"` plans against what the shipped readers were
    # VALIDATED to do, so a spec cannot promote a tier by asserting it.
    if raw_capabilities == "builtin":
        from .capabilities import builtin_capabilities

        try:
            plan = plan_requests(_parse_requests(raw_requests),
                                 builtin_capabilities(), spec["nominal_fps"],
                                 spec.get("max_frames"))
            return json.loads(json.dumps(plan, allow_nan=False))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid acquisition spec: {exc}") from exc
    if not isinstance(raw_capabilities, list):
        raise ValueError('capabilities must be a JSON array or the string "builtin"')
    capabilities = {}
    try:
        for raw in raw_capabilities:
            tiers = tuple(SamplingTier(**tier) for tier in raw["tiers"])
            capability = ReaderCapability(
                reader=raw["reader"], properties=tuple(raw["properties"]),
                tiers=tiers, regimes=tuple(raw.get("regimes", ("standard",))),
                negative_evidence=raw.get(
                    "negative_evidence", "requires recorded readable coverage"),
            )
            if capability.reader in capabilities:
                raise ValueError(f"duplicate capability: {capability.reader}")
            capabilities[capability.reader] = capability
        plan = plan_requests(_parse_requests(raw_requests), capabilities,
                             spec["nominal_fps"], spec.get("max_frames"))
        # The public contract is JSON, so do not leak Python tuple semantics to
        # callers or produce an in-memory plan that differs from its persisted form.
        return json.loads(json.dumps(plan, allow_nan=False))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid acquisition spec: {exc}") from exc


def write_plan(spec_path: str | Path, out: str | Path | None = None) -> dict:
    """Read a JSON contract, plan without media access, and optionally persist it."""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    plan = plan_spec(spec)
    if out is not None:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(plan, sort_keys=True, indent=2,
                                     allow_nan=False), encoding="utf-8")
    return plan


def execute_plan(ctx, plan: dict, readers: dict[str, object], progress=None) -> dict:
    """Drive planned routes through one decode and report actual PTS coverage."""
    routes = plan.get("routes", [])
    missing = sorted({route["reader"] for route in routes} - readers.keys())
    if missing:
        raise ValueError(f"missing planned readers: {', '.join(missing)}")
    requests = {route["route_id"]: (route["hz"], route["spans_ms"])
                for route in routes}
    # The plan named the transport from the coverage it planned; honour it here
    # rather than deciding a second time from the same numbers.
    transport = plan.get("transport") or "sequential_grab"
    sampler = sample_windows if transport == "seek_windows" else sample_multi
    coverage = {route["route_id"]: {"route_id": route["route_id"],
                                    "reader": route["reader"],
                                    "request_ids": route["request_ids"],
                                    "n_frames": 0, "first_t_ms": None,
                                    "last_t_ms": None, "status": "unobserved"}
                for route in routes}
    fed = set()
    retrieved = 0
    for who, sample in sampler(str(ctx.media), ctx.fps, requests):
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
            "transport": transport,
            "retrieved_frames": retrieved,
            "reader_frames": len(fed),
            "coverage": list(coverage.values()),
            "refused": list(plan.get("refused", []))}
