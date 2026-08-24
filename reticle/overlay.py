"""Render what the extractors see onto the capture, as a video (debug aid).

This module draws; it decides nothing. Every value it shows comes from calling
the real extractor -- `analyse_killfeed`, `read_scoreline`, `read_bottom_hud` --
so what you watch is what the pipeline actually did on that frame. A debug view
with its own copy of the logic can disagree with the code it is meant to explain,
which is worse than having no view at all.

Colour is the whole language here, so it is fixed in one place:

    green    the local player killed someone
    red      the local player died
    grey     an entry the player is not in
    amber    an entry an overlay covers -- attribution refused, not negative
    magenta  a band that could not be parsed at all

Amber and magenta are the ones to look for. Grey on an entry that visibly says
"Me" is the other bug worth hunting, and the per-side match scores are drawn so
you can see how far off the threshold it was.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import cv2

from .killfeed import ME_MATCH_MIN, analyse_killfeed, killfeed_roi
from .ocr import crop_gray, read_bottom_hud, read_scoreline, scoreline_roi
from .profiles import Profile

# BGR, because OpenCV.
INK = (236, 233, 230)
DIM = (120, 116, 112)
GREEN = (120, 220, 130)
RED = (90, 95, 235)
GREY = (150, 150, 150)
AMBER = (60, 180, 245)
MAGENTA = (200, 90, 200)
PANEL = (28, 24, 22)

VERDICT_COLOUR = {
    "kill": GREEN,
    "death": RED,
    "other": GREY,
    "occluded": AMBER,
    "tie": MAGENTA,
    "unparsed": MAGENTA,
}

FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class OverlayContext:
    """Everything the renderer needs that does not change frame to frame."""

    profile: Profile
    templates: object
    width: int
    height: int
    kf_mask: np.ndarray | None = None
    min_confidence: float = 0.82
    min_margin: float = 0.05
    spans: list | None = None          # (t_start_ms, t_end_ms, state)


def _text(img, s, org, colour=INK, scale=0.44, weight=1):
    """Text with a dark outline, so it survives any background."""
    cv2.putText(img, s, org, FONT, scale, (0, 0, 0), weight + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, FONT, scale, colour, weight, cv2.LINE_AA)


def _panel(img, x, y, w, h, alpha=0.62):
    sub = img[max(0, y):y + h, max(0, x):x + w]
    if sub.size:
        sub[:] = cv2.addWeighted(sub, 1 - alpha, np.full_like(sub, PANEL), alpha, 0)


def _state_at(spans, t_ms: float) -> str:
    if not spans:
        return "?"
    for t0, t1, state in spans:
        if t0 <= t_ms <= t1:
            return state
    return "-"


def draw(frame: np.ndarray, t_ms: float, frame_idx: int, ctx: OverlayContext) -> np.ndarray:
    """Annotate one frame. Returns a new image; `frame` is untouched."""
    img = frame.copy()
    W, H = ctx.width, ctx.height
    prof = ctx.profile

    # ---- every ROI, faintly, so a misplaced box is obvious --------------
    for roi in prof.rois:
        x0, y0, x1, y1 = roi.pixels(W, H)
        cv2.rectangle(img, (x0, y0), (x1, y1), DIM, 1)
        _text(img, roi.name, (x0 + 3, max(11, y0 - 4)), DIM, 0.38)

    # ---- stage 02: scoreline and bottom HUD -----------------------------
    sroi = scoreline_roi(prof)
    sr = read_scoreline(crop_gray(frame, sroi, W, H), ctx.templates,
                        ctx.min_confidence, ctx.min_margin)
    br = read_bottom_hud(frame, prof, ctx.templates, W, H,
                         ctx.min_confidence, ctx.min_margin)

    def fmt(v, unit=""):
        return "--" if v is None else f"{v}{unit}"

    clock = "--" if sr.clock_ms is None else f"{sr.clock_ms // 60000}:{sr.clock_ms // 1000 % 60:02d}"
    lines = [
        f"t {_hms(t_ms)}   frame {frame_idx}   state {_state_at(ctx.spans, t_ms)}",
        f"clock {clock}   score {fmt(sr.score_left)} - {fmt(sr.score_right)}"
        f"   conf {sr.confidence:.2f}",
        f"hp {fmt(br.hp)}   shield {fmt(br.shield)}"
        f"   ammo {fmt(br.ammo_mag)}/{fmt(br.ammo_reserve)}",
    ]
    occl = tuple(sr.occluded) + tuple(br.occluded)
    if occl:
        lines.append("occluded: " + ", ".join(occl))
    _panel(img, 8, 8, 430, 20 + 18 * len(lines))
    for i, line in enumerate(lines):
        _text(img, line, (18, 30 + 18 * i), INK, 0.46)

    # ---- stage 02: killfeed, entry by entry -----------------------------
    kroi = killfeed_roi(prof)
    if kroi is not None:
        kx0, ky0, kx1, ky1 = kroi.pixels(W, H)
        views = analyse_killfeed(frame, kroi, W, H, ctx.kf_mask, prof.name)
        # the calibrated overlay mask, so you can see what it ate
        if ctx.kf_mask is not None and not ctx.kf_mask.all():
            ys, xs = np.where(~ctx.kf_mask)
            if xs.size:
                cv2.rectangle(img, (kx0 + int(xs.min()), ky0 + int(ys.min())),
                              (kx0 + int(xs.max()), ky0 + int(ys.max())), AMBER, 1)
                _text(img, "overlay mask", (kx0 + int(xs.min()) + 3,
                                            ky0 + int(ys.min()) - 4), AMBER, 0.36)
        for v in views:
            colour = VERDICT_COLOUR.get(v.verdict, GREY)
            a, z = ky0 + v.y0, ky0 + v.y1
            cv2.rectangle(img, (kx0, a), (kx1, z), colour, 2)
            # weapon icon: the divider between the two names
            if v.wx1 > v.wx0:
                for x in (kx0 + v.wx0, kx0 + v.wx1):
                    cv2.line(img, (x, a), (x, z), colour, 1)
            # the name runs actually matched against, with their widths
            for run, side in ((v.killer_run, "K"), (v.victim_run, "V")):
                if run is None:
                    continue
                rx0, rx1 = kx0 + run[0], kx0 + run[1]
                cv2.rectangle(img, (rx0, a + 2), (rx1, z - 2), colour, 1)
                _text(img, f"{side}{rx1 - rx0 + 1}", (rx0, z + 12), colour, 0.36)
            label = f"s{v.slot} {v.verdict}   k {v.kill_score:.2f}   d {v.death_score:.2f}"
            lw = 8 * len(label)
            _panel(img, kx0 - lw - 12, a, lw + 10, 22, alpha=0.72)
            _text(img, label, (kx0 - lw - 6, a + 15), colour, 0.44)

        n_kill = sum(1 for v in views if v.verdict == "kill")
        n_death = sum(1 for v in views if v.verdict == "death")
        head = (f"killfeed  {len(views)} entries   kill {n_kill}  death {n_death}"
                f"   threshold {ME_MATCH_MIN:.2f}")
        _panel(img, kx0 - 2, ky0 - 26, kx1 - kx0 + 4, 22)
        _text(img, head, (kx0 + 4, ky0 - 10), INK, 0.44)

    # ---- legend ---------------------------------------------------------
    key = [("kill", GREEN), ("death", RED), ("not player", GREY),
           ("occluded", AMBER), ("unparsed", MAGENTA)]
    _panel(img, 8, H - 34, 26 + 96 * len(key), 26)
    for i, (name, colour) in enumerate(key):
        x = 18 + 96 * i
        cv2.rectangle(img, (x, H - 26), (x + 14, H - 16), colour, -1)
        _text(img, name, (x + 20, H - 17), INK, 0.42)
    return img


def _hms(ms: float) -> str:
    s = int(ms // 1000)
    return f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}"
