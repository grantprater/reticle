"""Does a cheaper tier read the same thing? The P3 acceptance measurement.

The planner in `acquisition` chooses a temporal tier per request. Nothing until
now checked whether the tier it chose reads what native rate reads, or what it
costs. This module runs the SHIPPED readers over frozen, source-reviewed windows
at reference fidelity and at each candidate tier, and reports two things the gate
asks for separately: agreement, and measured cost.

**Three baselines, and they are not the same thing.**

    reviewed truth      what a person saw in the frames, frozen before the run
    reference fidelity  every native frame, same detector
    candidate tier      the rate the planner would pick

Agreement with reference fidelity is consistency, not accuracy -- it is the same
detector at a higher rate, and a detector that fires on a camera wipe fires on it
at every rate. So presence and false positives are scored against the REVIEWED
field, and only frame-for-frame agreement is scored against the reference. The
two confuser windows exist to make that distinction bite: the stored 2 Hz read
recorded three and four killfeed entries across two respawn wipes that hold no
killfeed row at any reviewed instant.

**Windows are frozen before tuning, and the tolerances with them.** The onset
tolerance is 250 ms because the review that established the onsets was done at
200 ms; a tighter tolerance would be measuring the reviewer, not the reader.
Presence is scored only at instants somebody actually looked at.

**Killfeed presence is scored on the adjudicated account, not per frame.** The
first run of this gate scored `kf_entries`, and refused every tier on the
killfeed at every rate: a camera wipe paints both plate colours across the tray,
so one frame of it looks like three entries, and one frame is not where that can
be told from an entry. `checks.entry_presence` walks the frames instead and
keeps the tracks that persisted. Nothing about the reader changed and nothing in
the frozen contract changed; what changed is which account the verdict is taken
on. `killfeed_per_frame` still reports the reader's own claim, as diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
import time
from pathlib import Path

from .checks import entry_presence, track_entries
from .decode import sample_multi, sample_windows
from .refine import merge_windows


FIDELITY_VERSION = "fidelity-0.1.0"

FROZEN_CONTRACT = "p3-reference-fidelity-1"
# Inside the package, not `fixtures/`: that directory is gitignored media,
# and a frozen evaluation nobody can check out is not frozen.
FROZEN_WINDOWS = Path(__file__).resolve().parent / "frozen" / "p3_reference_windows.json"

TRANSPORTS = {"seek_windows": sample_windows, "sequential_grab": sample_multi}


# Asking for exactly `nominal_fps` does NOT retrieve every frame. The samplers
# gate on a next-timestamp, so a step of 1000/60 ms skips whenever a frame lands
# a hair early -- measured here at 3832 frames over 79.4 s, an effective 48.3 Hz
# claiming to be 60. A reference that quietly drops a fifth of its frames is not
# reference fidelity, and worse, it shrinks the SHARED frame set every candidate
# tier is scored on. Oversampling the request makes the gate unreachable.
NATIVE_OVERSAMPLE = 4.0


@dataclass(frozen=True)
class Tier:
    """A rate to compare. `hz=None` means every native frame in the window."""

    name: str
    hz: float | None

    def effective_hz(self, nominal_fps: float) -> float:
        return float(nominal_fps if self.hz is None else self.hz)

    def request_hz(self, nominal_fps: float) -> float:
        """What to ask the sampler for, which is not what the tier reports."""
        if self.hz is None:
            return float(nominal_fps) * NATIVE_OVERSAMPLE
        return float(self.hz)


def load_windows(path: str | Path = FROZEN_WINDOWS) -> dict:
    """Read the frozen window contract and refuse anything it does not pin.

    A frozen evaluation that silently accepts a window with no reviewed field
    is not frozen; it is a place to put a result after seeing it.
    """
    frozen = json.loads(Path(path).read_text(encoding="utf-8"))
    if frozen.get("contract") != FROZEN_CONTRACT:
        raise ValueError(f"expected contract {FROZEN_CONTRACT}, got {frozen.get('contract')!r}")
    if not frozen.get("session_id") or not frozen.get("frozen_on"):
        raise ValueError("frozen windows must name their session and freeze date")
    windows = frozen.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("frozen windows must list at least one window")
    seen = set()
    for window in windows:
        wid = window.get("window_id")
        if not wid or wid in seen:
            raise ValueError(f"window IDs must be present and unique: {wid!r}")
        seen.add(wid)
        if window.get("role") not in {"trigger", "audit", "confuser"}:
            raise ValueError(f"{wid}: role must be trigger, audit or confuser")
        t0, t1 = window.get("t0_ms"), window.get("t1_ms")
        if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)) or t1 <= t0:
            raise ValueError(f"{wid}: window bounds must be increasing")
        reviewed = window.get("reviewed")
        instants = window.get("reviewed_instants_ms")
        if not isinstance(reviewed, dict) or not isinstance(instants, list) or not instants:
            raise ValueError(f"{wid}: every window needs a reviewed field and the "
                             "instants that review looked at")
        for t in instants:
            if not (t0 <= t <= t1):
                raise ValueError(f"{wid}: reviewed instant {t} lies outside the window")
    tolerances = frozen.get("tolerances")
    if not isinstance(tolerances, dict) or "killfeed_entry" not in tolerances:
        raise ValueError("frozen windows must pin their tolerances")
    return frozen


def _spans(frozen: dict) -> list[tuple[float, float]]:
    return merge_windows([(w["t0_ms"], w["t1_ms"]) for w in frozen["windows"]])


def _window_of(frozen: dict, t_ms: float) -> dict | None:
    for window in frozen["windows"]:
        if window["t0_ms"] <= t_ms <= window["t1_ms"]:
            return window
    return None


def score_killfeed(frozen: dict, observations: list[dict], tolerance: dict) -> dict:
    """Score killfeed entry presence against the REVIEWED field, per window.

    `observations` are `{t_ms, entries}` rows from one tier's run. A reviewed
    instant counts as recalled when the tier saw an entry within the onset
    tolerance of it, which is the only fair test of a rate: a 2 Hz reader has no
    sample at 183 400 ms and being asked for one would score the phase, not the
    reader.

    Called twice per tier, on two different accounts of the same run: what each
    frame held, and what `checks.entry_presence` adjudicated across frames. The
    verdict is taken on the adjudicated one, because a frame is not where a
    camera wipe can be told from an entry -- see `run_tier`.
    """
    onset_ms = float(tolerance["onset_ms"])
    rows = sorted(observations, key=lambda r: r["t_ms"])
    per_window = []
    for window in frozen["windows"]:
        reviewed = window["reviewed"]
        inside = [r for r in rows if window["t0_ms"] <= r["t_ms"] <= window["t1_ms"]]
        seen_at = set(reviewed.get("entries_seen_at_ms", []))
        empty_at = set(reviewed.get("no_entries_at_ms", []))
        hits = misses = 0
        for t in sorted(seen_at):
            near = [r for r in inside if abs(r["t_ms"] - t) <= onset_ms]
            if any(r["entries"] > 0 for r in near):
                hits += 1
            else:
                misses += 1
        # A false positive is the reader claiming an entry within tolerance of
        # an instant the review recorded as EMPTY. `any`, not `all`: requiring
        # every nearby sample to fire makes the count fall as the rate rises,
        # purely because a denser tier has more chances to include one quiet
        # sample -- which would score the sampler, not the detector. Corrected
        # after the first run reported 0 false positives at native rate and 1 at
        # 15 Hz on the same window.
        false_positives = 0
        for t in sorted(empty_at):
            near = [r for r in inside if abs(r["t_ms"] - t) <= onset_ms]
            if any(r["entries"] > 0 for r in near):
                false_positives += 1
        recall = (hits / (hits + misses)) if (hits + misses) else None
        per_window.append({
            "window_id": window["window_id"], "role": window["role"],
            "n_samples": len(inside),
            "reviewed_present": len(seen_at), "reviewed_empty": len(empty_at),
            "recalled": hits, "missed": misses,
            "presence_recall": recall,
            "false_positive_instants": false_positives,
            "max_entries_observed": max([r["entries"] for r in inside], default=0),
        })
    present = [w for w in per_window if w["reviewed_present"]]
    pooled_hits = sum(w["recalled"] for w in present)
    pooled_total = sum(w["recalled"] + w["missed"] for w in present)
    confusers = [w for w in per_window if w["role"] == "confuser"]
    return {
        "per_window": per_window,
        "pooled_presence_recall": (pooled_hits / pooled_total) if pooled_total else None,
        "confuser_false_positive_instants": sum(w["false_positive_instants"] for w in confusers),
        "false_positive_instants": sum(w["false_positive_instants"] for w in per_window),
    }


def score_agreement(reference: list[dict], candidate: list[dict], tolerance: dict,
                    fields: tuple[str, str]) -> dict:
    """Frame-for-frame agreement on a two-component position, at SHARED frames.

    A candidate tier's frames are a subset of the reference's, so comparing at
    shared `frame_idx` isolates the reader's own state from which frames it was
    handed. Anything that differs here differs because the reader carries
    something across frames.
    """
    limit = float(tolerance["agreement_px"])
    fx, fy = fields
    ref = {r["frame_idx"]: r for r in reference}
    shared = [c for c in candidate if c["frame_idx"] in ref]
    agree = differ = ref_null = cand_null = 0
    worst = 0.0
    for c in shared:
        r = ref[c["frame_idx"]]
        rv, cv = (r[fx], r[fy]), (c[fx], c[fy])
        if rv[0] is None or rv[1] is None:
            ref_null += 1
            if cv[0] is None or cv[1] is None:
                agree += 1
            else:
                differ += 1
            continue
        if cv[0] is None or cv[1] is None:
            cand_null += 1
            differ += 1
            continue
        d = math.hypot(cv[0] - rv[0], cv[1] - rv[1])
        worst = max(worst, d)
        if d <= limit:
            agree += 1
        else:
            differ += 1
    fraction = (agree / len(shared)) if shared else None
    return {
        "n_candidate_samples": len(candidate),
        "n_shared_frames": len(shared),
        "agree": agree, "differ": differ,
        "agreement_fraction": fraction,
        "worst_disagreement_px": worst,
        "reference_null_frames": ref_null,
        "candidate_null_where_reference_read": cand_null,
    }


def _hud_args(nominal_fps: float, hz: float) -> argparse.Namespace:
    """The shipped HUD reader's constructor takes CLI args. Give it the same
    gates `scan` does, so this measures the shipped detector and not a variant."""
    return argparse.Namespace(hz=hz, minimap_hz=hz, min_confidence=0.82,
                              min_margin=0.05)


def run_tier(ctx, frozen: dict, tier: Tier, transport: str) -> dict:
    """Run the shipped HUD and minimap readers over the frozen windows at one
    tier, and measure what it cost.

    Wall time is measured around the decode loop, so it includes the seeks and
    the readers. It is a real number on one machine and one file, not a
    benchmark: the ratio between tiers is the part that carries.
    """
    from .cli import _MinimapPass
    from .hud_reader import HudReader

    if transport not in TRANSPORTS:
        raise ValueError(f"unknown transport: {transport}")
    spans = _spans(frozen)
    hz = tier.effective_hz(ctx.fps)
    # The minimap's own step gate is derived from the tier it BELIEVES it runs
    # at, so the reader must be built with the reported rate even when the
    # sampler is asked to oversample.
    args = _hud_args(ctx.fps, hz)
    hud = HudReader(ctx.store, ctx.manifest, ctx.profile, args)
    minimap = _MinimapPass(ctx.store, ctx.manifest, ctx.profile, spans, args)
    request_hz = tier.request_hz(ctx.fps)
    requests = {"hud": (request_hz, spans), "minimap": (request_hz, spans)}

    retrieved = 0
    start = time.perf_counter()
    for who, sample in TRANSPORTS[transport](str(ctx.media), ctx.fps, requests):
        retrieved += 1
        if "hud" in who:
            hud.feed(sample)
        if "minimap" in who:
            minimap.feed(sample)
    wall = time.perf_counter() - start

    # The count of record is the adjudicated one. `read_killfeed` reports what
    # one frame held and cannot do better -- a camera wipe paints both plate
    # colours across the tray and looks like three entries in that frame -- so
    # the walk across frames is where a band that never persisted is refused.
    rows = sorted(hud.rows, key=lambda r: r["t_ms"])
    times = [r["t_ms"] for r in rows]
    masks = [r["kf_entry_mask"] for r in rows]
    wx = [r["kf_entry_wx"] for r in rows]
    tracks = track_entries(times, masks, wx)
    adjudicated = entry_presence(times, masks, wx)
    for row, obs in zip(rows, adjudicated):
        obs["frame_idx"] = row["frame_idx"]

    return {
        "tier": tier.name, "hz": hz, "requested_hz": request_hz,
        "transport": transport,
        "retrieved_frames": retrieved,
        "wall_seconds": round(wall, 3),
        "covered_span_seconds": sum(b - a for a, b in spans) / 1000.0,
        "reach_seconds": (spans[-1][1] / 1000.0) if spans else 0.0,
        "killfeed": [{"frame_idx": r["frame_idx"], "t_ms": r["t_ms"],
                      "entries": r["kf_entries"]} for r in hud.rows],
        "killfeed_adjudicated": adjudicated,
        "killfeed_tracks": {
            "counted": sum(1 for a in tracks if a["counted"]),
            "refused": {reason: sum(1 for a in tracks if a["refused"] == reason)
                        for reason in ("single_frame", "no_persistence")},
            "counted_span_ms": sorted(round(a["span_ms"])
                                      for a in tracks if a["counted"]),
            "refused_span_ms": sorted(round(a["span_ms"])
                                      for a in tracks if not a["counted"]),
        },
        "minimap": [{"frame_idx": r["frame_idx"], "t_ms": r["t_ms"],
                     "self_x": r["self_x"], "self_y": r["self_y"]}
                    for r in minimap.rows],
        "minimap_widget_absent": minimap.n_absent,
    }


def compare(ctx, frozen: dict, tiers: list[Tier], transport: str = "seek_windows") -> dict:
    """Reference fidelity against every candidate tier, on the same windows.

    The first tier is the reference. Every later one is scored twice: against
    the reviewed truth for presence and false positives, and against the
    reference for frame-for-frame agreement.
    """
    if len(tiers) < 2:
        raise ValueError("a comparison needs a reference tier and at least one candidate")
    runs = [run_tier(ctx, frozen, tier, transport) for tier in tiers]
    reference, candidates = runs[0], runs[1:]
    kf_tol = frozen["tolerances"]["killfeed_entry"]
    mm_tol = frozen["tolerances"]["minimap_self_position"]

    results = []
    for run in [reference] + candidates:
        killfeed = score_killfeed(frozen, run["killfeed_adjudicated"], kf_tol)
        row = {
            "tier": run["tier"], "hz": run["hz"],
            "is_reference": run is reference,
            "retrieved_frames": run["retrieved_frames"],
            "wall_seconds": run["wall_seconds"],
            "cost_ratio_vs_reference": (round(run["wall_seconds"]
                                              / reference["wall_seconds"], 3)
                                        if reference["wall_seconds"] else None),
            "frame_ratio_vs_reference": (round(run["retrieved_frames"]
                                               / reference["retrieved_frames"], 4)
                                         if reference["retrieved_frames"] else None),
            "killfeed": killfeed,
            "killfeed_per_frame": score_killfeed(frozen, run["killfeed"], kf_tol),
            "killfeed_tracks": run["killfeed_tracks"],
            "minimap_widget_absent": run["minimap_widget_absent"],
        }
        if run is not reference:
            row["minimap_agreement"] = score_agreement(
                reference["minimap"], run["minimap"], mm_tol,
                ("self_x", "self_y"))
            row["verdict"] = _verdict(row, kf_tol, mm_tol)
        results.append(row)

    return {
        "producer_version": FIDELITY_VERSION,
        "contract": frozen["contract"],
        "frozen_on": frozen["frozen_on"],
        "session_id": frozen["session_id"],
        "transport": transport,
        "reference_tier": reference["tier"],
        "covered_span_seconds": reference["covered_span_seconds"],
        "reach_seconds": reference["reach_seconds"],
        "tiers": results,
        "limits": list(frozen.get("limits", [])) + [
            "Wall seconds are one machine and one file. The ratio between tiers "
            "is the comparable part.",
            "Agreement with reference fidelity is the same detector at a higher "
            "rate. Presence and false positives are scored against the reviewed "
            "field instead, which is why the confuser windows are here.",
            "Killfeed presence is scored on the ADJUDICATED account -- entries "
            "that persisted -- and `killfeed_per_frame` reports what the reader "
            "claimed frame by frame, which is diagnostics and not the verdict.",
        ],
    }


def _verdict(row: dict, kf_tol: dict, mm_tol: dict) -> dict:
    """Pass or fail each declared tolerance, and say which one failed.

    A tier that meets every tolerance is a tier a capability may declare. One
    that does not is refused there, which is the whole point of measuring: the
    planner must not be able to choose a rate nobody validated.
    """
    checks = {}
    recall = row["killfeed"]["pooled_presence_recall"]
    checks["killfeed_presence_recall"] = {
        "value": recall, "min": kf_tol["min_presence_recall"],
        "pass": recall is not None and recall >= kf_tol["min_presence_recall"],
    }
    confuser = row["killfeed"]["confuser_false_positive_instants"]
    checks["killfeed_confuser_false_positives"] = {
        "value": confuser, "max": kf_tol["max_confuser_false_positive_frames"],
        "pass": confuser <= kf_tol["max_confuser_false_positive_frames"],
    }
    agreement = row["minimap_agreement"]["agreement_fraction"]
    checks["minimap_self_agreement"] = {
        "value": agreement, "min": mm_tol["min_agreement_fraction"],
        "pass": agreement is not None and agreement >= mm_tol["min_agreement_fraction"],
    }
    return {"checks": checks,
            "failed": sorted(k for k, v in checks.items() if not v["pass"]),
            "pass": all(v["pass"] for v in checks.values())}
