import unittest

import numpy as np

from reticle import barriers


def wall(x, y, w, h):
    return {"x": x + w / 2, "y": y + h / 2, "box": [x, y, w, h]}


class MergeTests(unittest.TestCase):
    def test_anchors_within_tolerance_are_one_bar_and_keep_their_provenance(self):
        a = barriers.merge([[wall(10, 10, 20, 4)], [wall(12, 11, 20, 4)]])
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["seen_in"], [0, 1])

    def test_a_bar_only_one_round_saw_is_not_averaged_away(self):
        a = barriers.merge([[wall(10, 10, 20, 4)], [wall(300, 300, 20, 4)]])
        self.assertEqual([x["seen_in"] for x in a], [[0], [1]])


class CutLawTests(unittest.TestCase):
    """A barrier set is judged as a SET: does it separate the map."""

    def corridor(self):
        # Two rooms joined by one corridor, which is the only chokepoint.
        f = np.zeros((60, 60), bool)
        f[5:25, 5:55] = True                      # north room
        f[35:55, 5:55] = True                     # south room
        f[25:35, 28:32] = True                    # the corridor
        return f

    def test_a_bar_over_the_only_chokepoint_separates_the_map(self):
        f = self.corridor()
        self.assertFalse(barriers.separates([], f, grow=0))
        cut = [wall(27, 29, 6, 2)]
        self.assertTrue(barriers.separates(cut, f, grow=0))
        areas, total = barriers.partition(cut, f, grow=0)
        self.assertEqual(len(areas), 2)
        self.assertEqual(areas, [1016, 1016])          # the two rooms, evenly
        # Only the part of the bar that lay on passable floor is removed: the
        # corridor is 4 px wide and the bar is 6, and painting a bar must not
        # subtract the two ends that were never floor.
        self.assertEqual(sum(areas), total - 8)

    def test_a_bar_that_misses_the_chokepoint_does_not(self):
        f = self.corridor()
        self.assertFalse(barriers.separates([wall(8, 8, 6, 2)], f, grow=0))

    def test_pockets_behind_bars_are_not_territories(self):
        # Eight bars that each fence off a sliver leave the map connected, and
        # the law must not read eight pockets as a partition.
        f = self.corridor()
        bars = [wall(6 + 6 * i, 6, 4, 1) for i in range(8)]
        self.assertFalse(barriers.separates(bars, f, grow=0))

    def test_the_report_shows_every_growth_so_one_lucky_value_is_visible(self):
        rows = barriers.cut_report([wall(27, 29, 6, 2)], self.corridor(),
                                   grows=(0, 4))
        self.assertEqual([r["grow_px"] for r in rows], [0, 4])
        self.assertTrue(all("regions" in r and "fractions" in r for r in rows))


if __name__ == "__main__":
    unittest.main()
