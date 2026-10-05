"""The ally-rate gate on synthetic crops: a still teammate is carried, never observed."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import ally_rate as ar  # noqa: E402

TEAL = (200, 190, 40)    # BGR: min(G, B) - R well above the key's ramp


def crop_with(points):
    c = np.zeros((120, 120, 3), np.uint8)
    for x, y in points:
        yy, xx = np.mgrid[0:120, 0:120]
        c[(xx - x) ** 2 + (yy - y) ** 2 <= 25] = TEAL
    return c


def rows_for(frames):
    """`frames`: list of [(x, y), ...] per frame, frame_idx = position."""
    f, x, y = [], [], []
    for i, pts in enumerate(frames):
        for px, py in pts:
            f.append(i)
            x.append(px)
            y.append(py)
    n = len(f)
    ic = {"f": np.array(f), "x": np.array(x, float), "y": np.array(y, float),
          "fac": np.zeros(n), "reason": np.array([None] * n, dtype=object),
          "barrier": np.zeros(n, bool), "key": np.array([f"s:{a}:{b}" for a, b in zip(f, range(n))],
                                                         dtype=object)}
    span = {}
    for i in range(n):
        a, _b = span.get(int(ic["f"][i]), (i, i))
        span[int(ic["f"][i])] = (a, i + 1)
    return {"icons": ic, "span": span}


class GateTest(unittest.TestCase):
    def run_gate(self, frames, tau=0.10):
        rows = rows_for(frames)
        v = {"name": "t", "base_hz": 1.0, "tau": tau, "death": False, "ping": False}
        g = ar.Gate(v, 1.0, ar.Windows(10))
        cues = {"death_open": False, "ping_xy": np.zeros((0, 2))}
        for i, pts in enumerate(frames):
            t = 1000.0 + i * 1000.0 / 15.0          # one base tick, at frame 0
            idx = np.arange(*rows["span"][i])
            g.step(i, t, i == 0, idx, crop_with(pts), rows, cues, False)
        return g

    def test_still_teammate_is_carried_as_predicted(self):
        g = self.run_gate([[(40, 40), (80, 80)]] * 5)
        later = [r for r in g.out if r[0] > 0]
        self.assertEqual({r[6] for r in later}, {"predicted"})
        # rests_on names the stored row of the last read, frame 0
        self.assertTrue(all(r[7] in (0, 1) and r[1] == -1 for r in later))
        self.assertEqual(g.decision[3], ("none", 2, 0))

    def test_moving_teammate_is_read_and_the_still_one_carried(self):
        frames = [[(40, 40), (80, 80)], [(44, 40), (80, 80)], [(48, 40), (80, 80)]]
        g = self.run_gate(frames)
        f1 = [r for r in g.out if r[0] == 1]
        moved = next(r for r in f1 if r[2] == 44.0)
        still = next(r for r in f1 if r[3] == 80.0)
        self.assertEqual(moved[6], "observed")
        self.assertEqual(still[6], "predicted")
        self.assertEqual(g.decision[1], ("partial", 2, 1))

    def test_a_vanished_teammate_widens_to_a_full_read(self):
        g = self.run_gate([[(40, 40), (80, 80)], [(80, 80)]])
        self.assertEqual(g.c["surprise_full"], 1)
        self.assertEqual(g.decision[1][0], "full")

    def test_no_cue_reads_only_at_the_base_rate(self):
        g = self.run_gate([[(40, 40)], [(60, 40)], [(80, 40)]], tau=math.inf)
        self.assertEqual([r[6] for r in g.out if r[0] == 2], ["predicted"])
        self.assertEqual(g.out[-1][2], 40.0)


if __name__ == "__main__":
    unittest.main()
