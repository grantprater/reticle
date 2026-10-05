"""prototypes/scoreboard_reads.py on synthetic rows: openings from the strip
alone, the frame-selection rules, thinning, and the threshold fit."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import scoreboard_reads as sr  # noqa: E402


def strip_sample(f, verdict):
    return {"kind": "sample", "frame_idx": f, "t_ms": f * 500.0 / 30,
            "verdict": verdict, "scoreboard_strip_version": "x"}


def slab_sample(f, open_):
    return {"kind": "sample", "frame_idx": f, "t_ms": f * 500.0 / 30, "open": open_,
            "reason": None if open_ else "green_no_rows", "anchor": None}


class TestScoreboardReads(unittest.TestCase):
    def setUp(self):
        # 2 Hz samples at 30 fps: frame 15k. Strip: open 1-4 with a hole at 3,
        # absent, then a lone unreadable sample at 7. The slab test opens at 9
        # alone, which the strip-only openings must ignore.
        verdicts = ["absent", "present", "present", "absent", "present", "absent",
                    "absent", "unreadable", "absent", "absent"]
        self.strip = [strip_sample(15 * i, v) for i, v in enumerate(verdicts)]
        self.board = [slab_sample(15 * i, i == 9) for i in range(len(verdicts))]

    def test_strip_runs_join_one_hole_and_ignore_the_slab(self):
        runs = sr.strip_runs(self.board, self.strip)
        self.assertEqual([r["frames"] for r in runs], [[15, 30, 60], [105]])

    def test_rules(self):
        f = [10, 20, 30, 40, 50]
        self.assertEqual(sr.select(f, "a0"), [10])
        self.assertEqual(sr.select(f, "a"), [20])
        self.assertEqual(sr.select([10], "a"), [10])
        self.assertEqual(sr.select(f, "b"), [30])
        self.assertEqual(sr.select(f, "c"), [50])
        self.assertEqual(sr.select(f, "d"), [20, 50])
        self.assertEqual(sr.select([10, 20], "d"), [20])
        diffs = {20: 9.0, 30: 1.0, 40: 6.0, 50: 0.5}
        self.assertEqual(sr.select(f, "e", diffs, theta=5.0), [20, 40])
        self.assertEqual(sr.select(f, "all"), f)
        with self.assertRaises(ValueError):
            sr.select(f, "e")

    def test_thin_rows_keeps_coverage(self):
        rows = [{"kind": "coverage"}, {"kind": "row_observation", "frame_idx": 15},
                {"kind": "sample", "frame_idx": 30}]
        self.assertEqual(sr.thin_rows(rows, {15}), rows[:2])

    def test_youden_theta_separates(self):
        d = np.array([1.0, 1.5, 2.0, 8.0, 9.0, 10.0])
        y = np.array([False, False, False, True, True, True])
        theta, j = sr.youden_theta(d, y)
        self.assertTrue(2.0 <= theta < 8.0)
        self.assertAlmostEqual(j, 1.0)

    def test_split_is_fixed(self):
        self.assertEqual(sr.split("a06f04a0059f"), "dev")
        self.assertEqual(sr.split("043bafca271a"), "held")

    def test_field_changes(self):
        runs = [{"run": 0, "frames": [1, 2, 3]}, {"run": 1, "frames": [4]}]
        row = lambda k, d: {"kills": k, "deaths": 0, "assists": 0, "credits": 800,  # noqa: E731
                            "dim": d, "is_player": False, "display_row": 0}
        states = {1: None, 2: {("ally", "Jett"): row(0, False)},
                  3: {("ally", "Jett"): row(1, True)}, 4: {("ally", "Jett"): row(0, False)}}
        got = sr.field_changes(states, runs)
        self.assertEqual(got["openings_with_two_accepted"], 1)
        self.assertEqual((got["kills"], got["dim"], got["credits"], got["any"]), (1, 1, 0, 1))
        labels = sr.pair_labels(states, runs)
        self.assertEqual(labels, {2: True, 3: True})

    def test_variants_select_like_e(self):
        diffs = {20: 9.0, 30: 1.0, 40: 6.0, 50: 0.5}
        for v in sr.VARIANTS:
            self.assertEqual(sr.select([10, 20, 30, 40, 50], v, diffs, theta=5.0), [20, 40])

    def test_credit_bins_cover_the_credits_cell(self):
        from reticle import scoreboard as sb
        bins = sr.credit_bins()
        self.assertTrue(bins and bins == list(range(bins[0], bins[-1] + 1)))
        self.assertLessEqual(bins[0] / sr.NBINS, sb.CREDITS_X - sb.CREDITS_HALF)
        self.assertGreaterEqual((bins[-1] + 1) / sr.NBINS, sb.CREDITS_X + sb.CREDITS_HALF)

    def test_credit_match_by_overlap(self):
        c = {"t_start_ms": 100.0, "t_end_ms": 500.0}
        a = {"t_start_ms": 0.0, "t_end_ms": 150.0}
        b = {"t_start_ms": 200.0, "t_end_ms": 600.0}
        far = {"t_start_ms": 900.0, "t_end_ms": 950.0}
        self.assertIs(sr.credit_match(c, [a, b, far]), b)
        self.assertIsNone(sr.credit_match(c, [far]))

    def test_n_differ_counts_gains_apart(self):
        cmp_ = {"lineup": {"same": 2}, "credits": {"same": 5, "lost": 2, "gained": 3},
                "local_row": {"changed": 1}, "deaths": {"same": 4, "refusal_reason_changed": 1},
                "kd_bound": {"same": 3, "changed": 1}}
        got = sr.n_differ(cmp_)
        self.assertEqual((got["total"], got["lost"]), (2 + 3 + 1 + 1 + 1, 2 + 1 + 1))


if __name__ == "__main__":
    unittest.main()
