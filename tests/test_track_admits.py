"""`track.admits_many` against the scalar `track.admits` it vectorises."""
from __future__ import annotations

import unittest

import numpy as np

from reticle.track import CLASSES, TELEPORT_PX, admits, admits_many


class AdmitsManyTests(unittest.TestCase):
    def test_agrees_with_the_scalar_rule_on_every_class(self):
        rng = np.random.default_rng(0)
        d = np.concatenate([rng.uniform(0, 2.5 * TELEPORT_PX, 400), [0.0, 1.5, 1.6, TELEPORT_PX]])
        t = np.concatenate([rng.uniform(-0.05, 2.0, 400), [0.0, 0.0, 0.1, 0.1]])
        for scale in (1.0, 0.71):
            for name, motion in CLASSES.items():
                want = [admits(motion, float(a), float(b), scale)[0] for a, b in zip(d, t)]
                got = admits_many(motion, d, t, scale)
                self.assertEqual(got.tolist(), want, f"{name} at scale {scale}")


if __name__ == "__main__":
    unittest.main()
