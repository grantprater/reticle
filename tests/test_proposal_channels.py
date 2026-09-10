"""The two channels added because area-gated centroids miss welded icons."""
import unittest

import cv2
import numpy as np

from prototypes.mine_icons import (core_proposals, fill_holes, neck_components)
from prototypes.proposal_audit import diagnose_union


def ring(shape, cx, cy, radius, thickness=1):
    """An icon as the residual mask actually sees it: an outline, not a disc."""
    mask = np.zeros(shape, np.uint8)
    cv2.circle(mask, (cx, cy), radius, 1, thickness)
    return mask.astype(bool)


class FillHolesTests(unittest.TestCase):
    def test_enclosed_interior_is_filled_and_the_outside_is_not(self):
        mask = ring((40, 40), 20, 20, 6)
        filled = fill_holes(mask)
        self.assertTrue(filled[20, 20])
        self.assertFalse(filled[2, 2])
        self.assertGreater(filled.sum(), mask.sum())

    def test_an_open_arc_keeps_its_background(self):
        mask = ring((40, 40), 20, 20, 6)
        mask[14:27, 20] = False          # cut the ring open
        self.assertFalse(fill_holes(mask)[20, 20])

    def test_a_border_touching_background_is_never_a_hole(self):
        mask = np.zeros((20, 20), bool)
        mask[:, 10] = True
        self.assertFalse(fill_holes(mask)[5, 5])


class NeckComponentTests(unittest.TestCase):
    def test_a_two_px_neck_is_cut_so_the_icon_is_its_own_component(self):
        mask = np.zeros((40, 80), np.uint8)
        cv2.circle(mask, (14, 20), 6, 1, -1)     # the icon
        mask[19:21, 20:52] = 1                   # the wire welding it to art
        mask[10:31, 52:76] = 1                   # extended ability art
        welded, _lbl = cv2.connectedComponents(mask, 8)[0:2]
        self.assertEqual(welded - 1, 1)          # one component before cutting

        components, opened, _labels = neck_components(mask.astype(bool))
        areas = sorted(c["area"] for c in components)
        self.assertGreaterEqual(len(components), 2)
        self.assertFalse(opened[20, 36])         # the neck is gone
        icon = min(components, key=lambda c: abs(c["cx"] - 14))
        self.assertLess(abs(icon["cx"] - 14), 2.0)
        self.assertLess(abs(icon["cy"] - 20), 2.0)
        self.assertLess(areas[0], areas[-1])

    def test_components_carry_the_same_fields_as_the_base_channel(self):
        components, _opened, _labels = neck_components(
            np.ones((20, 20), bool))
        self.assertEqual(set(components[0]),
                         {"id", "cx", "cy", "area", "bbox"})


class CoreProposalTests(unittest.TestCase):
    def test_a_ring_welded_to_a_wire_still_proposes_its_centre(self):
        mask = np.zeros((60, 60), np.uint8)
        cv2.circle(mask, (30, 30), 7, 1, 2)      # the icon, as an outline
        mask[29:31, 37:58] = 1                   # a wire out to the edge
        cores, filled = core_proposals(mask.astype(bool), scale=1.0)
        self.assertTrue(filled[30, 30])
        self.assertTrue(any(abs(c["cx"] - 30) <= 2 and abs(c["cy"] - 30) <= 2
                            for c in cores))

    def test_a_thin_wire_alone_proposes_nothing(self):
        mask = np.zeros((60, 60), bool)
        mask[29:31, 5:55] = True
        self.assertEqual(core_proposals(mask, scale=1.0)[0], [])

    def test_suppression_keeps_the_thicker_of_two_close_cores(self):
        mask = np.zeros((60, 60), np.uint8)
        cv2.circle(mask, (25, 30), 8, 1, -1)
        cv2.circle(mask, (28, 30), 4, 1, -1)
        cores, _filled = core_proposals(mask.astype(bool), scale=1.0,
                                        spacing=12)
        self.assertEqual(len(cores), 1)
        self.assertLess(abs(cores[0]["cx"] - 25), 2.0)


class UnionDiagnosisTests(unittest.TestCase):
    def _masks(self, shape):
        return {"base": np.zeros(shape, bool), "neck": np.zeros(shape, bool)}

    def test_credit_goes_to_the_channel_that_proposed_the_match(self):
        accepted = {"base": [], "neck": [{"cx": 10.0, "cy": 10.0, "area": 20}]}
        got = diagnose_union([{"x": 10, "y": 10, "r": 3}], accepted,
                             self._masks((20, 20)), ("base", "neck"), slack=0)
        self.assertEqual(dict(got["tp_by_channel"]), {"neck": 1})
        self.assertEqual(got["failures"], {})

    def test_no_channel_support_is_separable_from_a_rejected_gate(self):
        masks = self._masks((30, 30))
        masks["base"][9:12, 9:12] = True
        accepted = {"base": [], "neck": []}
        icons = [{"x": 10, "y": 10, "r": 2}, {"x": 25, "y": 25, "r": 2}]
        got = diagnose_union(icons, accepted, masks, ("base", "neck"), slack=0)
        self.assertEqual(got["failures"], {
            "rejected_with_support_in_base": 1,
            "no_channel_support": 1,
        })

    def test_two_channels_cannot_both_claim_one_icon(self):
        accepted = {"base": [{"cx": 10.0, "cy": 10.0, "area": 20}],
                    "neck": [{"cx": 10.5, "cy": 10.0, "area": 20}]}
        got = diagnose_union([{"x": 10, "y": 10, "r": 3}], accepted,
                            self._masks((20, 20)), ("base", "neck"), slack=0)
        self.assertEqual(len(got["matched"]), 1)
        self.assertEqual(sum(got["tp_by_channel"].values()), 1)


if __name__ == "__main__":
    unittest.main()
