"""The ability pass's shape reader: the live and drawn gates, the teal gate,
and the two streams it writes under their own stamps."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from reticle import ability_scan as A
from reticle.version import ABILITY_GATE_VERSION, ABILITY_SHAPE_VERSION

TEAL = (180, 170, 30)


def _base() -> np.ndarray:
    rng = np.random.default_rng(0)
    img = np.full((331, 331, 3), 40, np.uint8)
    cv2.rectangle(img, (60, 60), (270, 270), (128, 128, 128), -1)
    noise = rng.integers(0, 60, (331, 331, 1), dtype=np.uint8)
    return cv2.add(img, np.repeat(noise, 3, axis=2))


class ShapeReaderTest(unittest.TestCase):
    def setUp(self):
        self.base = _base()
        floor = np.zeros(self.base.shape[:2], bool)
        floor[60:271, 60:271] = True
        sgray = cv2.cvtColor(self.base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        phase = {0.0: "round_live", 500.0: "round_live", 1000.0: "buy", 1500.0: "post_plant"}
        self.reader = A.AbilityShapeReader(floor=floor, sgray=sgray, support=floor,
                                           box=(0, 0, 331, 331), phase_at=phase.get)

    def feed(self, img, t, idx):
        self.reader.feed(SimpleNamespace(frame=img, t_ms=t, frame_idx=idx))

    def test_gate_closed_open_and_not_live(self):
        ring = self.base.copy()
        cv2.circle(ring, (150, 160), 45, TEAL, 2)
        self.feed(self.base, 0.0, 0)
        self.feed(ring, 500.0, 30)
        self.feed(ring, 1000.0, 60)
        self.feed(ring, 1500.0, 90)
        g = self.reader.gate_rows
        self.assertEqual([r["gate"] for r in g], [False, True, None, True])
        self.assertEqual(g[2]["reason"], "not_live")
        s = self.reader.shape_rows
        self.assertEqual([r["t_ms"] for r in s], [500.0, 1500.0])
        best = s[0]["rings"][0]
        self.assertTrue(best["accepted"])
        self.assertLessEqual(np.hypot(best["cx"] - 150, best["cy"] - 160), 2)

    def test_each_stream_carries_its_own_stamp(self):
        self.feed(self.base, 0.0, 0)
        gate = self.reader.gate_events("s", "k")
        shape = self.reader.shape_events("s", "k")
        self.assertEqual(gate[0]["kind"], "coverage")
        self.assertEqual(gate[0]["ability_gate_version"], ABILITY_GATE_VERSION)
        self.assertNotIn("ability_shape_version", gate[0])
        self.assertEqual(shape[0]["ability_shape_scan_version"], ABILITY_SHAPE_VERSION)
        self.assertEqual(shape[0]["ability_gate_version"], ABILITY_GATE_VERSION)
        self.assertEqual(gate[0]["by_reason"], {"closed": 1})


if __name__ == "__main__":
    unittest.main()
