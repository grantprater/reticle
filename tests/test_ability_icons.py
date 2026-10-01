"""The dark-icon proposer, its verify, and the `ability_icon` reader's rows."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from reticle import ability_icons as I
from reticle.version import ABILITY_ICON_VERSION


def _slab_img(n=465):
    rng = np.random.default_rng(1)
    img = np.full((n, n, 3), 150, np.uint8)
    noise = rng.integers(0, 40, (n, n, 1), dtype=np.uint8)
    img = cv2.add(img, np.repeat(noise, 3, axis=2))
    slab = np.zeros((n, n), np.uint8)
    slab[60:n - 60, 60:n - 60] = 1
    return img, slab


class ProposerTest(unittest.TestCase):
    def setUp(self):
        self.base, self.slab = _slab_img()
        self.terms = I.IconTerms(self.slab, I.SET_AT)

    def test_finds_a_dark_disc_and_nothing_on_a_blank_slab(self):
        self.assertEqual(I.propose_icons(self.base, self.terms), [])
        img = self.base.copy()
        cv2.circle(img, (200, 240), 9, (20, 20, 20), -1)
        c = I.propose_icons(img, self.terms)
        self.assertEqual(len(c), 1)
        self.assertLessEqual(np.hypot(c[0]["cx"] - 200, c[0]["cy"] - 240), 1)
        self.assertLessEqual(abs(c[0]["r"] - 9), 1.5)

    def test_off_slab_darkness_is_not_a_candidate(self):
        img = self.base.copy()
        cv2.circle(img, (25, 25), 9, (20, 20, 20), -1)
        self.assertEqual(I.propose_icons(img, self.terms), [])

    def test_verify_follows_a_moved_icon_and_loses_a_gone_one(self):
        img = self.base.copy()
        cv2.circle(img, (200, 240), 9, (20, 20, 20), -1)
        c = I.propose_icons(img, self.terms)
        moved = self.base.copy()
        cv2.circle(moved, (201, 241), 9, (20, 20, 20), -1)
        v = I.verify_icons(moved, self.terms, c)
        self.assertIsNotNone(v[0]["score"])
        self.assertEqual((v[0]["cx"], v[0]["cy"]), (201, 241))
        self.assertIsNone(I.verify_icons(self.base, self.terms, c)[0]["score"])


class ReaderTest(unittest.TestCase):
    def test_rows_reasons_verify_and_stamp(self):
        base, slab = _slab_img()
        floor = slab.astype(bool)
        sgray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        phase = {0.0: "round_live", 500.0: "round_live", 1000.0: "buy"}
        rd = I.AbilityIconReader(slab=slab, floor=floor, sgray=sgray, box=(0, 0, 465, 465),
                                 phase_at=phase.get)
        img = base.copy()
        cv2.circle(img, (200, 240), 9, (20, 20, 20), -1)
        for t, i in ((0.0, img), (500.0, img), (1000.0, img)):
            rd.feed(SimpleNamespace(frame=i, t_ms=t, frame_idx=int(t / 1000 * 60)))
        ev = rd.events("s", "k")
        head, rows = ev[0], ev[1:]
        self.assertEqual(head["ability_icon_version"], ABILITY_ICON_VERSION)
        self.assertEqual(head["by_reason"], {"read": 2, "not_live": 1})
        self.assertIsNone(rows[0]["verify"])
        self.assertEqual(rows[1]["verify"]["of_t_ms"], 0.0)
        self.assertIsNotNone(rows[1]["verify"]["rows"][0]["score"])
        self.assertEqual(rows[2]["reason"], "not_live")
        self.assertEqual(head["verify_lost"], 0)


if __name__ == "__main__":
    unittest.main()
