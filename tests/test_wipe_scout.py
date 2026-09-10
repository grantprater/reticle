"""The wipe scout's selector: a disagreement between two accounts of one frame.

It is not a threshold, so what these pin is the disagreement itself -- a frame
the reader claimed an entry on and the walk refused -- and the ranking, which
puts a wash carrying empty bands above a claim carrying none.
"""
import sys
import unittest
from pathlib import Path

import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.wipe_scout import candidates  # noqa: E402


def table(rows):
    """rows: (t_ms, kf_entries, kf_entry_mask, kf_empty_bands)."""
    cols = list(zip(*rows)) if rows else ([], [], [], [])
    return pa.table({
        "t_ms": pa.array(cols[0], type=pa.float64()),
        "kf_entries": pa.array(cols[1], type=pa.int16()),
        "kf_entry_mask": pa.array(cols[2], type=pa.int16()),
        "kf_empty_bands": pa.array(cols[3], type=pa.int16()),
    })


def steady(n, step=500.0):
    return [(i * step, 0, 0, 0) for i in range(n)]


class SelectorTests(unittest.TestCase):
    def test_a_persistent_entry_is_not_a_candidate(self):
        rows = steady(40)
        for i in range(10, 20):                      # five seconds in slot 0
            rows[i] = (rows[i][0], 1, 1, 0)
        self.assertEqual(candidates(table(rows)), [])

    def test_a_one_frame_claim_is_a_candidate(self):
        rows = steady(40)
        rows[20] = (rows[20][0], 3, 0b111, 2)
        found = candidates(table(rows))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["t0_ms"], 10_000.0)
        self.assertEqual(found[0]["max_claimed"], 3)
        self.assertEqual(found[0]["empty_bands"], 2)

    def test_a_wash_outranks_a_claim_carrying_no_empty_band(self):
        rows = steady(60)
        rows[10] = (rows[10][0], 1, 1, 0)            # no wipe signature
        rows[40] = (rows[40][0], 1, 2, 4)            # a wash
        found = candidates(table(rows))
        self.assertEqual([w["t0_ms"] for w in found], [20_000.0, 5_000.0])

    def test_neighbouring_instants_are_one_window(self):
        rows = steady(40)
        for i in (20, 21, 22):
            rows[i] = (rows[i][0], 1, 1 << (i - 20), 1)
        found = candidates(table(rows))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["n_instants"], 3)
        self.assertEqual((found[0]["t0_ms"], found[0]["t1_ms"]), (10_000.0, 11_000.0))

    def test_instants_further_apart_than_the_gap_are_separate_windows(self):
        rows = steady(60)
        rows[10] = (rows[10][0], 1, 1, 1)
        rows[40] = (rows[40][0], 1, 1, 1)
        self.assertEqual(len(candidates(table(rows), gap_ms=3000.0)), 2)
        self.assertEqual(len(candidates(table(rows), gap_ms=20_000.0)), 1)

    def test_a_session_with_nothing_refused_offers_no_window(self):
        self.assertEqual(candidates(table(steady(40))), [])


if __name__ == "__main__":
    unittest.main()
