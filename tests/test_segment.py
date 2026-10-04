from __future__ import annotations

import unittest

import numpy as np

from reticle.segment import READ_STATES, SegmentConfig, classify, reader_spans, segment


def _table(n: int, hud: float, motion: float, dchange: float) -> dict[str, np.ndarray]:
    return {"t_ms": np.arange(n, dtype=float) * 200.0, "motion": np.full(n, motion),
            "minimap_dchange": np.full(n, dchange), "hud_hp_edge": np.full(n, hud)}


class SegmentTests(unittest.TestCase):
    def test_hud_chrome_alone_is_in_match(self):
        # A stationary caster on an empty map: HUD drawn, minimap unchanged
        # (b9558488a607 28.6-41.6 s, which seg-0.2.0 labelled off).
        cfg = SegmentConfig()
        still = classify(_table(50, hud=0.11, motion=0.03, dchange=0.0), cfg)
        self.assertTrue((still == 2).all())
        held = classify(_table(50, hud=0.11, motion=0.0, dchange=0.0), cfg)
        self.assertTrue((held == 1).all())
        dark = classify(_table(50, hud=0.0, motion=0.5, dchange=9.0), cfg)
        self.assertTrue((dark == 0).all())

    def test_readers_read_idle_and_active_as_one_stretch(self):
        self.assertEqual(READ_STATES, ("idle", "active"))
        spans = [{"state": "off", "t_start_ms": 0.0, "t_end_ms": 4000.0},
                 {"state": "active", "t_start_ms": 4200.0, "t_end_ms": 9000.0},
                 {"state": "idle", "t_start_ms": 9200.0, "t_end_ms": 15000.0},
                 {"state": "off", "t_start_ms": 15200.0, "t_end_ms": 20000.0},
                 {"state": "idle", "t_start_ms": 20200.0, "t_end_ms": 26000.0}]
        self.assertEqual(reader_spans(spans), [(4200.0, 15000.0), (20200.0, 26000.0)])

    def test_segment_spans_cover_a_hud_present_capture(self):
        cfg = SegmentConfig()
        t = _table(100, hud=0.11, motion=0.03, dchange=0.0)
        t["motion"][40:70] = 0.0
        spans = segment(t, cfg)
        self.assertEqual([s["state"] for s in spans], ["active", "idle", "active"])
        self.assertEqual(reader_spans(spans), [(0.0, 19800.0)])


if __name__ == "__main__":
    unittest.main()
