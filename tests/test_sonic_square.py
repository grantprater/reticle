"""The Sonic Sensor square fit recovers a synthetic square drawn by the domain fact's model."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import sonic_square as ss  # noqa: E402


def _scene(rng, a=0.17, cx=60.3, cy=58.6, w=26.0, h=27.0, lit=False):
    """A flat floor of grey 110 (lit 170 on the right half when `lit`), a dark icon disc on the
    square's bottom side, the square tinted `a` over it, and capture noise."""
    H_, W_ = 120, 120
    B = np.full((H_, W_), 110.0, np.float32)
    Hl = np.full((H_, W_), 170.0, np.float32)
    bg = B.copy()
    if lit:
        bg[:, 90:] = Hl[:, 90:]
    yy, xx = np.mgrid[0:H_, 0:W_].astype(np.float64)
    S = (ss.box_coverage(xx[0], cx - w / 2, cx + w / 2, 0.5)[None, :]
         * ss.box_coverage(yy[:, 0], cy - h / 2, cy + h / 2, 0.5)[:, None])
    g = bg + (255.0 - bg) * a * S
    icon = np.hypot(xx - cx, yy - (cy + h / 2)) <= 11.5
    g[icon] = 20.0
    g[icon & (np.hypot(xx - cx, yy - (cy + h / 2)) <= 3)] = 230.0
    g = g + rng.normal(0, 2.0, g.shape)
    return g.astype(np.float32), B, Hl, np.ones((H_, W_), bool)


def test_fit_recovers_square_and_links_icon():
    rng = np.random.default_rng(0)
    g, B, Hl, slab = _scene(rng)
    dets = ss.detect_frame(g, B, Hl, slab, 1.0, use_glyph=False)
    top = dets[0]
    assert abs(top["cx"] - 60.3) < 0.5 and abs(top["cy"] - 58.6) < 0.5
    # the icon hides most of the side it sits on, so the side across it is the looser one
    assert abs(top["w"] - 26.0) < 1.0 and abs(top["h"] - 27.0) < 1.5
    assert abs(top["alpha"] - 0.17) < 0.02
    assert top["icon"]["dir"] == "up" and abs(top["icon"]["y"] - 72.1) <= 3
    assert top["accepted"]


def test_lit_floor_beside_square_is_not_square():
    rng = np.random.default_rng(1)
    g, B, Hl, slab = _scene(rng, lit=True)
    dets = ss.detect_frame(g, B, Hl, slab, 1.0, use_glyph=False)
    acc = [d for d in dets if d["accepted"]]
    assert len(acc) == 1 and abs(acc[0]["cx"] - 60.3) < 0.5


def test_no_square_no_detection():
    rng = np.random.default_rng(2)
    g, B, Hl, slab = _scene(rng, a=0.0)
    assert not [d for d in ss.detect_frame(g, B, Hl, slab, 1.0, use_glyph=False) if d["accepted"]]
