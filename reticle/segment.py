"""Stage 01: gate and segment (design doc SS3).

Reads L1 primitives and emits spans. Never touches video -- which is the whole
point of the L0/L1 split: threshold changes recompute in under a second instead
of forcing a re-decode.

WHAT THIS IS NOT: the design doc specifies a small *trained* classifier for
buy / in-round / post-round / menu / spectate. This is the rule-based baseline
that stands in until there is labelled data to train one on, and it makes a
deliberately coarser claim:

    in_match   HUD and minimap both present and live
    active     in_match, with meaningful scene motion
    idle       in_match, but static (menus mid-match, death cam holds, AFK)
    off        no HUD -- loading, agent select, alt-tabbed, desktop

The thresholds below are starting guesses. Calibrate them against your own
footage with `reticle segment --show-signals` before trusting the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass
class SegmentConfig:
    """Tunables for the baseline classifier. All comparisons are on L1 columns."""

    # A live minimap is redrawn constantly. Sustained perceptual change in that
    # ROI is the single most reliable "we are in a round" signal that does not
    # depend on reading any text.
    minimap_dchange_min: float = 2.0
    # HUD chrome is high-contrast line art; empty backgrounds are not.
    hud_edge_min: float = 0.020
    # Whole-frame motion separating an active scene from a held camera.
    active_motion_min: float = 0.012
    # Rolling median width in samples. Kills single-frame flicker.
    smooth_window: int = 9
    # Spans shorter than this are absorbed into their neighbours.
    min_span_ms: float = 3000.0

    def as_dict(self) -> dict:
        return asdict(self)


STATES = ("off", "idle", "active")

# ROIs that carry HUD chrome. Whichever of these the profile defines and the
# stored table actually has are maxed together for the "HUD is on screen" test.
# A capture that crops one HUD corner away can then still be gated on whatever
# chrome survived -- see VALORANT_16_9_CROP75 in profiles.py.
HUD_CHROME_ROIS = ("hud_hp", "hud_ammo", "hud_roster")


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or values.size == 0:
        return values
    if window % 2 == 0:
        window += 1
    half = window // 2
    padded = np.pad(values, (half, half), mode="edge")
    strided = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(strided, axis=1)


def classify(table: dict[str, np.ndarray], cfg: SegmentConfig) -> np.ndarray:
    """Per-sample state labels as an integer array indexing STATES."""
    n = len(table["t_ms"])
    if n == 0:
        return np.empty(0, dtype=np.int8)

    minimap_change = _rolling_median(
        table.get("minimap_dchange", np.zeros(n)).astype(np.float64), cfg.smooth_window
    )
    chrome = [
        table[f"{roi}_edge"].astype(np.float64)
        for roi in HUD_CHROME_ROIS
        if f"{roi}_edge" in table
    ]
    hud_edge = _rolling_median(
        np.maximum.reduce(chrome) if chrome else np.zeros(n), cfg.smooth_window
    )
    motion = _rolling_median(table["motion"].astype(np.float64), cfg.smooth_window)

    in_match = (minimap_change >= cfg.minimap_dchange_min) & (hud_edge >= cfg.hud_edge_min)
    active = in_match & (motion >= cfg.active_motion_min)

    labels = np.zeros(n, dtype=np.int8)  # off
    labels[in_match] = 1  # idle
    labels[active] = 2  # active
    return labels


def _merge_into(target: dict, other: dict) -> None:
    """Fold `other` into `target`, keeping every derived field consistent.

    mean_motion is re-weighted by sample count rather than left alone -- an
    absorbed span changes n_samples, so an un-updated mean would describe a
    different set of samples than the one the span now claims to cover.
    """
    total = target["n_samples"] + other["n_samples"]
    if total:
        target["mean_motion"] = (
            target["mean_motion"] * target["n_samples"]
            + other["mean_motion"] * other["n_samples"]
        ) / total
    target["i0"] = min(target["i0"], other["i0"])
    target["i1"] = max(target["i1"], other["i1"])
    target["t_start_ms"] = min(target["t_start_ms"], other["t_start_ms"])
    target["t_end_ms"] = max(target["t_end_ms"], other["t_end_ms"])
    target["n_samples"] = total


def _coalesce(spans: list[dict]) -> bool:
    """Merge neighbouring spans that share a state. True if anything merged.

    Absorbing a short span deletes the separator between its two neighbours,
    and those neighbours usually share a state -- a sub-threshold span is
    typically a brief flicker inside a longer run of the opposite label.
    Without this pass they survive as two adjacent spans carrying the same
    state, which inflates span counts and understates the longest run.
    """
    merged = False
    i = 1
    while i < len(spans):
        if spans[i]["state"] == spans[i - 1]["state"]:
            _merge_into(spans[i - 1], spans.pop(i))
            merged = True
        else:
            i += 1
    return merged


def to_spans(
    t_ms: np.ndarray, labels: np.ndarray, motion: np.ndarray, cfg: SegmentConfig
) -> list[dict]:
    """Collapse per-sample labels into contiguous spans, then merge short ones."""
    if labels.size == 0:
        return []

    spans: list[dict] = []
    start = 0
    for i in range(1, labels.size + 1):
        if i == labels.size or labels[i] != labels[start]:
            spans.append(
                {
                    "state": STATES[int(labels[start])],
                    "i0": start,
                    "i1": i - 1,
                    "t_start_ms": float(t_ms[start]),
                    "t_end_ms": float(t_ms[i - 1]),
                    "n_samples": int(i - start),
                    "mean_motion": float(motion[start:i].mean()),
                }
            )
            start = i

    # Absorb sub-threshold spans into whichever neighbour is longer, then
    # rejoin neighbours that now share a state. Repeats until stable, since
    # either step can create new work for the other.
    changed = True
    while changed and len(spans) > 1:
        changed = _coalesce(spans)
        for idx, span in enumerate(spans):
            if span["t_end_ms"] - span["t_start_ms"] >= cfg.min_span_ms:
                continue
            prev_span = spans[idx - 1] if idx > 0 else None
            next_span = spans[idx + 1] if idx + 1 < len(spans) else None
            if prev_span is None and next_span is None:
                continue
            if prev_span is None:
                target = next_span
            elif next_span is None:
                target = prev_span
            else:
                prev_len = prev_span["t_end_ms"] - prev_span["t_start_ms"]
                next_len = next_span["t_end_ms"] - next_span["t_start_ms"]
                target = prev_span if prev_len >= next_len else next_span
            _merge_into(target, span)
            spans.pop(idx)
            changed = True
            break

    for i, span in enumerate(spans):
        span["span_idx"] = i
        span["duration_ms"] = span["t_end_ms"] - span["t_start_ms"]
        span.pop("i0", None)
        span.pop("i1", None)
    return spans


def segment(table: dict[str, np.ndarray], cfg: SegmentConfig) -> list[dict]:
    labels = classify(table, cfg)
    return to_spans(table["t_ms"], labels, table["motion"], cfg)
