import unittest

import numpy as np

from prototypes.proposal_audit import _maximum_matching, diagnose


class ProposalMatchingTests(unittest.TestCase):
    def test_assignment_does_not_credit_one_proposal_to_two_icons(self):
        icons = [{"x": 10, "y": 10, "r": 3},
                 {"x": 14, "y": 10, "r": 3}]
        proposals = [{"cx": 12.0, "cy": 10.0, "area": 8, "id": 1}]
        self.assertEqual(len(_maximum_matching(icons, proposals, slack=0)), 1)

    def test_assignment_recovers_maximum_cardinality(self):
        icons = [{"x": 10, "y": 10, "r": 3},
                 {"x": 15, "y": 10, "r": 3}]
        proposals = [{"cx": 12.0, "cy": 10.0, "area": 8, "id": 1},
                     {"cx": 8.0, "cy": 10.0, "area": 8, "id": 2}]
        self.assertEqual(len(_maximum_matching(icons, proposals, slack=0)), 2)


class ProposalDiagnosisTests(unittest.TestCase):
    def test_distinguishes_no_support_small_large_and_miscentered(self):
        labels = np.zeros((40, 50), np.int32)
        labels[8:10, 18:20] = 1       # too small at icon 1
        labels[6:15, 27:36] = 2       # too large at icon 2
        labels[20:23, 35:38] = 3      # accepted support, centroid far away
        components = [
            {"id": 1, "cx": 18.5, "cy": 8.5, "area": 4},
            {"id": 2, "cx": 31.0, "cy": 10.0, "area": 81},
            {"id": 3, "cx": 45.0, "cy": 30.0, "area": 9},
        ]
        icons = [{"x": 5, "y": 5, "r": 2},
                 {"x": 19, "y": 9, "r": 2},
                 {"x": 31, "y": 10, "r": 2},
                 {"x": 36, "y": 21, "r": 2}]
        got = diagnose(icons, components, labels, lo_area=6, hi_area=50, slack=0)
        self.assertEqual(got["failures"], {
            "no_residual_support": 1,
            "components_too_small": 1,
            "component_too_large": 1,
            "accepted_component_miscentered_or_claimed": 1,
        })

    def test_reports_fragmented_target_separately(self):
        labels = np.zeros((20, 20), np.int32)
        labels[8:10, 8:10] = 1
        labels[11:13, 11:13] = 2
        components = [{"id": 1, "cx": 8.5, "cy": 8.5, "area": 4},
                      {"id": 2, "cx": 11.5, "cy": 11.5, "area": 4}]
        got = diagnose([{"x": 10, "y": 10, "r": 5}], components, labels,
                       lo_area=6, hi_area=50, slack=0)
        self.assertEqual(got["fragmented_targets"], 1)
        self.assertEqual(got["failures"]["components_too_small"], 1)


if __name__ == "__main__":
    unittest.main()
