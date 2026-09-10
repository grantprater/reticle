"""Deterministic appearance evidence for tiny minimap icons.

The portrait and the facing surround are separate representations. This module
samples only the upright interior; rotation remains the geometry matcher's job.
It exposes raw-luma and background-normalized correlations independently so a
development evaluation can select a rule without hiding which evidence won.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


APPEARANCE_VERSION = "minimap-appearance-0.1.0"
GRID = 11
INTERIOR_FRAC = 0.55
MIN_CELLS = 25
# Selected on c40d950031bb 210-340s before the frozen-window evaluation.
# These gate only the recent trusted-template recovery path.
MIN_CONTRAST = 10.0
RECENT_RESIDUAL_SCORE_MIN = 0.7325
#: The joint path's gate stays UNSELECTED. Its development precision was good
#: enough to choose one -- every gate at or above 0.1254 was exact -- but its
#: coverage failed the predeclared budget, so promoting a number here would be
#: choosing a threshold for a rule already measured as not worth shipping.
#: `proposed` refuses instead. See docs/MINIMAP_APPEARANCE_MATCHING.md Step 2.
JOINT_RESIDUAL_SCORE_MIN = None

_yy, _xx = np.mgrid[0:GRID, 0:GRID]
_unit_x = (_xx - (GRID - 1) / 2) / ((GRID - 1) / 2)
_unit_y = (_yy - (GRID - 1) / 2) / ((GRID - 1) / 2)
_DISC = (_unit_x * _unit_x + _unit_y * _unit_y) <= 1.0


@dataclass(frozen=True)
class Descriptor:
    """One upright icon interior, independent of its source coordinates."""

    luma: np.ndarray
    residual: np.ndarray
    mask: np.ndarray
    contrast: float


@dataclass(frozen=True)
class Match:
    """Best spatial explanation and the strongest separated alternative."""

    x: float
    y: float
    score: float
    runner_up: float
    margin: float
    contrast: float
    mode: str


@dataclass(frozen=True)
class _Anchor:
    descriptor: Descriptor | None
    x: float
    y: float
    radius: float
    t_ms: float
    trusted: bool


class RecentAppearanceRecovery:
    """Recover a ring refusal from a recent, forced-correspondence template.

    Two consecutive sampled observations must both have physically compatible
    ring fits before the newer fit becomes a trusted anchor. Refusals never
    become anchors, and a refusal breaks the consecutive-fit pair needed to
    certify the next fit. This makes the temporal template causal without
    turning the matcher's own answer into future evidence.
    """

    def __init__(self, background_lo: np.ndarray, background_hi: np.ndarray,
                 support: np.ndarray, *, scale: float = 1.0,
                 max_gap_ms: float = 1000.0, run_px: float = 45.0,
                 fit_error_px: float = 2.0):
        shape = support.shape
        if background_lo.shape != shape or background_hi.shape != shape:
            raise ValueError("background references and support must have one shape")
        self.background_lo = background_lo
        self.background_hi = background_hi
        self.support = support
        self.scale = float(scale)
        self.max_gap_ms = float(max_gap_ms)
        self.run_px = float(run_px)
        self.fit_error_px = float(fit_error_px)
        self._anchor: _Anchor | None = None
        self._previous_sample_was_fit = False

    def unavailable(self) -> None:
        """Break template trust when the widget itself was not observable."""
        self._anchor = None
        self._previous_sample_was_fit = False

    def refusal(self) -> None:
        """A sampled frame with no ring fit breaks the consecutive-fit pair.

        Callers that only inspect the appearance evidence must still declare
        the refusal, or an anchor gets certified across a gap it never saw.
        """
        self._previous_sample_was_fit = False

    def fitted(self, crop: np.ndarray, colour_mask: np.ndarray, fit: dict,
               t_ms: float) -> None:
        """Observe a ring fit and certify it only from the preceding fit."""
        x, y, radius = float(fit["cx"]), float(fit["cy"]), float(fit["r"])
        descriptor = describe(crop, colour_mask, x, y, radius,
                              self.background_lo, self.background_hi)
        trusted = False
        if self._previous_sample_was_fit and self._anchor is not None:
            dt_ms = float(t_ms) - self._anchor.t_ms
            limit = max(2.0 * self.fit_error_px * self.scale,
                        self.run_px * self.scale * (dt_ms / 1000.0) * 2.0)
            trusted = (0.0 < dt_ms <= self.max_gap_ms
                       and math.hypot(x - self._anchor.x,
                                      y - self._anchor.y) <= limit
                       and descriptor is not None)
        self._anchor = _Anchor(descriptor, x, y, radius, float(t_ms), trusted)
        self._previous_sample_was_fit = True

    def reach_px(self, t_ms: float) -> float | None:
        """How far the icon could have physically moved since the anchor."""
        anchor = self._anchor
        if anchor is None or not anchor.trusted or anchor.descriptor is None:
            return None
        dt_ms = float(t_ms) - anchor.t_ms
        if not (0.0 < dt_ms <= self.max_gap_ms):
            return None
        return max(2.0 * self.fit_error_px * self.scale,
                   self.run_px * self.scale * (dt_ms / 1000.0) * 2.0)

    def admissible(self, proposals: list[dict],
                   t_ms: float) -> list[tuple[float, float]]:
        """Proposals the anchor's motion limit allows, in proposal order."""
        reach = self.reach_px(t_ms)
        if reach is None:
            return []
        anchor = self._anchor
        return [(float(p["cx"]), float(p["cy"])) for p in proposals
                if math.hypot(float(p["cx"]) - anchor.x,
                              float(p["cy"]) - anchor.y) <= reach]

    def query_at(self, crop: np.ndarray, colour_mask: np.ndarray,
                 proposals: list[dict], t_ms: float) -> Match | None:
        """Score the anchor's template at admissible proposals, UNGATED.

        The anchor's radius sizes the interior rather than each proposal's own,
        because a proposal comes from the fit the shape gate refused and its
        radius is the least trustworthy number it carries.
        """
        candidates = self.admissible(proposals, t_ms)
        if not candidates:
            return None
        return match_at(crop, colour_mask, self.background_lo,
                        self.background_hi, [self._anchor.descriptor],
                        candidates, self._anchor.radius, mode="residual",
                        support=self.support,
                        runner_separation_px=3.0 * self.scale)

    def proposed(self, crop: np.ndarray, colour_mask: np.ndarray,
                 proposals: list[dict], t_ms: float) -> Match | None:
        """The joint rule: current-frame proposals, then the selected gate."""
        self.refusal()
        if JOINT_RESIDUAL_SCORE_MIN is None:
            raise RuntimeError("the joint gate is unselected; run the "
                               "development evaluation first")
        got = self.query_at(crop, colour_mask, proposals, t_ms)
        if (got is None or got.score < JOINT_RESIDUAL_SCORE_MIN
                or got.contrast < MIN_CONTRAST):
            return None
        return got

    def refused(self, crop: np.ndarray, colour_mask: np.ndarray,
                t_ms: float) -> Match | None:
        """Try the locked residual rule, returning ``None`` on weak evidence."""
        self.refusal()
        anchor = self._anchor
        if (anchor is None or not anchor.trusted or anchor.descriptor is None):
            return None
        dt_ms = float(t_ms) - anchor.t_ms
        if not (0.0 < dt_ms <= self.max_gap_ms):
            return None
        search = max(2.0 * self.fit_error_px * self.scale,
                     self.run_px * self.scale * (dt_ms / 1000.0) * 2.0)
        got = match_near(crop, colour_mask, self.background_lo,
                         self.background_hi, [anchor.descriptor],
                         (anchor.x, anchor.y), anchor.radius, search,
                         mode="residual", support=self.support,
                         runner_separation_px=3.0 * self.scale)
        if (got is None or got.score < RECENT_RESIDUAL_SCORE_MIN
                or got.contrast < MIN_CONTRAST):
            return None
        return got


def _square(a: np.ndarray, cx: float, cy: float, half: int) -> np.ndarray | None:
    """Integer-aligned source sampling; tiny rasters are resampled only once."""
    x, y = int(round(cx)), int(round(cy))
    x0, y0 = x - half, y - half
    x1, y1 = x + half, y + half
    if x0 < 0 or y0 < 0 or x1 > a.shape[1] or y1 > a.shape[0]:
        return None
    out = a[y0:y1, x0:x1]
    return out if out.shape[:2] == (2 * half, 2 * half) else None


def describe(crop: np.ndarray, colour_mask: np.ndarray, cx: float, cy: float,
             radius: float, background_lo: np.ndarray,
             background_hi: np.ndarray) -> Descriptor | None:
    """Sample an upright, colour-masked luma interior on a fixed grid.

    ``residual`` subtracts the midpoint of the two measured map-lighting states.
    It removes terrain shade while retaining the observed lit/unlit displacement.
    This is deliberately a bounded approximation, not an alpha recovery.
    """
    if crop.ndim != 3 or crop.shape[2] < 3:
        raise ValueError("crop must be a BGR image")
    shape = crop.shape[:2]
    if (colour_mask.shape != shape or background_lo.shape != shape
            or background_hi.shape != shape):
        raise ValueError("mask and background references must match the crop")
    half = max(3, int(round(float(radius) * INTERIOR_FRAC)))
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    values = _square(grey, cx, cy, half)
    lo = _square(np.asarray(background_lo, dtype=np.float32), cx, cy, half)
    hi = _square(np.asarray(background_hi, dtype=np.float32), cx, cy, half)
    keyed = _square(np.asarray(colour_mask, dtype=np.uint8), cx, cy, half)
    if values is None or lo is None or hi is None or keyed is None:
        return None
    luma = cv2.resize(values, (GRID, GRID), interpolation=cv2.INTER_AREA)
    midpoint = cv2.resize((lo + hi) * 0.5, (GRID, GRID),
                          interpolation=cv2.INTER_AREA)
    colour_free = cv2.resize(keyed * 255, (GRID, GRID),
                             interpolation=cv2.INTER_AREA) < 64
    mask = _DISC & colour_free
    if int(mask.sum()) < MIN_CELLS:
        return None
    visible = luma[mask]
    contrast = float(np.percentile(visible, 90) - np.percentile(visible, 10))
    return Descriptor(luma=luma, residual=luma - midpoint, mask=mask,
                      contrast=contrast)


def _ncc(a: np.ndarray, ma: np.ndarray, b: np.ndarray, mb: np.ndarray) -> float:
    mask = ma & mb
    if int(mask.sum()) < MIN_CELLS:
        return -1.0
    av, bv = a[mask].astype(np.float32), b[mask].astype(np.float32)
    av, bv = av - av.mean(), bv - bv.mean()
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    return float(av @ bv / denom) if denom > 1e-6 else -1.0


def appearance_similarity(a: Descriptor, b: Descriptor,
                          mode: str = "residual") -> float:
    """Masked normalized correlation for a declared evidence channel."""
    if mode == "luma":
        return _ncc(a.luma, a.mask, b.luma, b.mask)
    if mode == "residual":
        return _ncc(a.residual, a.mask, b.residual, b.mask)
    if mode == "mean":
        return 0.5 * (appearance_similarity(a, b, "luma")
                      + appearance_similarity(a, b, "residual"))
    raise ValueError(f"unknown appearance mode: {mode}")


def best_exemplar(query: Descriptor, gallery: list[Descriptor],
                  mode: str = "residual") -> float:
    """Nearest exemplar; an average template erases real appearance modes."""
    return max((appearance_similarity(query, item, mode)
                for item in gallery), default=-1.0)


def _score(crop: np.ndarray, colour_mask: np.ndarray,
           background_lo: np.ndarray, background_hi: np.ndarray,
           gallery: list[Descriptor], candidates, radius: float, mode: str,
           runner_separation_px: float) -> Match | None:
    """Best explanation over an explicit candidate list, keeping ambiguity.

    Only current-frame appearance supplies the returned observation; the caller
    decides which centres are admissible. The runner-up is spatially separated
    from the best so adjacent samples of one peak do not manufacture ambiguity.
    """
    if not gallery:
        return None
    scored = []
    for x, y in candidates:
        query = describe(crop, colour_mask, x, y, radius,
                         background_lo, background_hi)
        if query is None:
            continue
        scored.append((best_exemplar(query, gallery, mode), float(x), float(y),
                       query.contrast))
    if not scored:
        return None
    scored.sort(reverse=True)
    score, x, y, contrast = scored[0]
    runner = next((s for s, qx, qy, _ in scored[1:]
                   if math.hypot(qx - x, qy - y) >= runner_separation_px), -1.0)
    return Match(float(x), float(y), float(score), float(runner),
                 float(score - runner), float(contrast), mode)


def _supported(support: np.ndarray | None, x: int, y: int) -> bool:
    if support is None:
        return True
    if y < 0 or x < 0 or y >= support.shape[0] or x >= support.shape[1]:
        return False
    return bool(support[y, x])


def match_near(crop: np.ndarray, colour_mask: np.ndarray,
               background_lo: np.ndarray, background_hi: np.ndarray,
               gallery: list[Descriptor], prior: tuple[float, float],
               radius: float, search_px: float, *, mode: str = "residual",
               support: np.ndarray | None = None,
               runner_separation_px: float = 3.0) -> Match | None:
    """Search every integer centre around a causal prior. See `_score`.

    The prior bounds computation only. This enumerates positions the current
    frame never proposed, which is why a wrong offset can still score well;
    `match_at` is the constrained alternative.
    """
    px, py = prior
    reach = max(0, int(math.ceil(search_px)))
    candidates = [
        (x, y)
        for y in range(int(round(py)) - reach, int(round(py)) + reach + 1)
        for x in range(int(round(px)) - reach, int(round(px)) + reach + 1)
        if math.hypot(x - px, y - py) <= search_px and _supported(support, x, y)
    ]
    return _score(crop, colour_mask, background_lo, background_hi, gallery,
                  candidates, radius, mode, runner_separation_px)


def match_at(crop: np.ndarray, colour_mask: np.ndarray,
             background_lo: np.ndarray, background_hi: np.ndarray,
             gallery: list[Descriptor], candidates, radius: float, *,
             mode: str = "residual", support: np.ndarray | None = None,
             runner_separation_px: float = 3.0) -> Match | None:
    """Score appearance only where the CURRENT frame proposes an icon.

    A candidate here carries its own evidence -- a keyed ring fragment the
    shape gate refused -- so a well-scoring wrong offset must also explain
    self-coloured pixels, which an arbitrary disk position need not.
    """
    return _score(crop, colour_mask, background_lo, background_hi, gallery,
                  [(x, y) for x, y in candidates
                   if _supported(support, int(round(x)), int(round(y)))],
                  radius, mode, runner_separation_px)
