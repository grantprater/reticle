"""Cross-channel accounting must preserve unclassified light as unknown."""
import unittest

import numpy as np

from reticle.cone import compare_evidence, observable, resolve_lobe


class ConeEvidence(unittest.TestCase):
    def test_unknown_is_not_dark(self):
        mask = np.array([[True, True, True, False]])
        known = np.array([[True, True, False, True]])
        lit = np.array([[True, False, True, True]])
        self.assertEqual(compare_evidence(mask, lit, known), {
            "cone_px": 3, "comparable_px": 2, "unknown_px": 1,
            "lit_px": 1, "unlit_px": 1, "lit_share": .5})

    def test_empty_and_fully_unknown_abstain(self):
        empty = np.zeros((3, 3), bool)
        full = ~empty
        for mask in (empty, full):
            result = compare_evidence(mask, full, empty)
            self.assertIsNone(result["lit_share"])
            self.assertEqual(result["unlit_px"], 0)
            self.assertEqual(result["unknown_px"], int(mask.sum()))

    def test_lobe_without_comparable_pixels_cannot_win(self):
        p = np.ones((41, 41), bool)
        backward, _ = observable(p, [(20, 20, 180.)])
        yy, xx = np.indices(p.shape)
        known = backward & (xx < 19)
        # Light elsewhere prevents the early no-light refusal; the comparable
        # backward pixels are dark, but the forward lobe has no evidence at all.
        lit = np.zeros_like(p)
        lit[0, 40] = True
        d = {"cx": 20, "cy": 20, "facing": 0.}
        result = resolve_lobe(p, lit, [d], known=known)[0]
        self.assertEqual(result["facing"], 180.)
        self.assertEqual(result["lobe_score"], 0.)

    def test_two_unknown_lobes_leave_detection_unchanged(self):
        p = np.ones((41, 41), bool)
        d = {"cx": 20, "cy": 20, "facing": 0.}
        self.assertEqual(resolve_lobe(p, p, [d], known=~p), [d])
        self.assertNotIn("lobe_score", d)

    def test_unknown_forward_area_does_not_favor_backward_lobe(self):
        p = np.ones((41, 41), bool)
        _, xx = np.indices(p.shape)
        known = (xx < 19) | ((xx > 20) & (xx < 23))
        lit = (xx > 20) & (xx < 23)
        # Partial illumination behind beats the narrow forward known strip
        # under the old full-area denominator, but not on classified support.
        lit |= (xx < 10)
        d = {"cx": 20, "cy": 20, "facing": 0.}
        self.assertTrue(resolve_lobe(p, lit, [d])[0]["lobe_flipped"])
        corrected = resolve_lobe(p, lit, [d], known=known)[0]
        self.assertFalse(corrected["lobe_flipped"])
        self.assertEqual(corrected["lobe_score"], 1.)


if __name__ == "__main__":
    unittest.main()
