"""The round-history strip witness on synthetic centre crops: two marker lines
in register read present, a band too dark for a dark dot reads unreadable,
and a band without a lattice reads absent, each with its reason."""
from __future__ import annotations

import unittest

import numpy as np

from reticle import scoreboard_strip as strip
from reticle.version import SCOREBOARD_STRIP_VERSION

#: The centre crop's frame rectangle at 1920x1080 (x, y, w, h).
RECT = (883, 486, 154, 108)
PITCH = 22


def _crop(grey: int = 90) -> np.ndarray:
    return np.full((RECT[3], RECT[2], 3), grey, np.uint8)


def _dots(crop: np.ndarray, lines=(0, 1), first: int = 12, n: int = 6,
          value: int = 30) -> np.ndarray:
    """2x2 dark dots, one per column, on the named marker lines."""
    for line in lines:
        y = strip.ROW_Y[line] - RECT[1]
        for k in range(n):
            x = first + PITCH * k
            crop[y:y + 2, x:x + 2] = value
    return crop


class ReadStripTests(unittest.TestCase):
    def test_two_marker_lines_in_register_read_present(self):
        got = strip.read_strip(_dots(_crop()), RECT)
        self.assertEqual(got["verdict"], "present")
        self.assertIsNone(got["reason"])
        self.assertEqual(got["cells"], 12)
        self.assertEqual(got["per_line"], [6, 6])
        self.assertEqual(got["paired"], 6)
        self.assertAlmostEqual(got["pitch"], PITCH, delta=0.2)

    def test_a_dark_band_reads_unreadable(self):
        got = strip.read_strip(_crop(grey=10), RECT)
        self.assertEqual(got["verdict"], "unreadable")
        self.assertEqual(got["reason"], "band_too_dark_for_dark_dots")
        self.assertLess(got["background"], strip.MIN_BACKGROUND)

    def test_a_plain_band_has_no_lattice_and_reads_absent(self):
        got = strip.read_strip(_crop(), RECT)
        self.assertEqual(got["verdict"], "absent")
        self.assertEqual(got["reason"], "too_few_cells")
        self.assertEqual(got["cells"], 0)

    def test_marks_on_one_line_only_read_absent(self):
        got = strip.read_strip(_dots(_crop(), lines=(0,)), RECT)
        self.assertEqual(got["verdict"], "absent")
        self.assertEqual(got["reason"], "one_line_empty")

    def test_too_few_columns_read_absent(self):
        got = strip.read_strip(_dots(_crop(), n=2), RECT)
        self.assertEqual(got["verdict"], "absent")
        self.assertEqual(got["reason"], "too_few_cells")

    def test_a_missing_crop_reads_unreadable(self):
        self.assertEqual(strip.read_strip(None, RECT),
                         {"verdict": "unreadable", "reason": "no_crop"})

    def test_a_crop_that_misses_the_marker_lines_reads_unreadable(self):
        got = strip.read_strip(_crop()[:40], RECT)
        self.assertEqual(got["reason"], "marker_lines_outside_crop")


class StripEventsTests(unittest.TestCase):
    def test_coverage_then_one_stamped_sample_row_per_frame(self):
        reads = [(0, 0.0, strip.read_strip(_dots(_crop()), RECT)),
                 (30, 500.0, strip.read_strip(_crop(), RECT)),
                 (60, 1000.0, strip.read_strip(_crop(grey=10), RECT))]
        rows = strip.strip_events("s", reads, RECT, "roi-cache-x")
        cov = rows[0]
        self.assertEqual(cov["kind"], "coverage")
        self.assertEqual(cov["frames"], 3)
        self.assertEqual(cov["verdicts"], {"present": 1, "absent": 1, "unreadable": 1})
        self.assertEqual(cov["reasons"], {"band_too_dark_for_dark_dots": 1, "too_few_cells": 1})
        self.assertEqual([r["frame_idx"] for r in rows[1:]], [0, 30, 60])
        for r in rows:
            self.assertEqual(r["scoreboard_strip_version"], SCOREBOARD_STRIP_VERSION)
            self.assertEqual(r["roi_cache_version"], "roi-cache-x")


if __name__ == "__main__":
    unittest.main()
