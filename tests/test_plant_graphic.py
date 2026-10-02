"""The planted-spike graphic reader and the plant rule `rounds` builds on it."""
import unittest

import numpy as np

from reticle import plant_graphic as pg
from reticle.rounds import plant_state


def _crop(field_bgr=None, digits=False, h=59, w=308, bg=(90, 90, 90)):
    """A synthetic scoreline crop: grey band, optionally a red clock field and
    white digit ink in the digits' box."""
    im = np.zeros((h, w, 3), np.uint8)
    im[:] = bg
    if field_bgr is not None:
        im[:, int(0.40 * w):int(0.60 * w)] = field_bgr
    if digits:
        im[int(0.3 * h):int(0.7 * h), int(0.44 * w):int(0.56 * w):2] = (250, 250, 250)
    return im


class ReadField(unittest.TestCase):
    def test_graphic_scores_above_the_cut(self):
        got = pg.read_field(_crop(field_bgr=(20, 20, 220)))
        self.assertTrue(pg.shows_graphic(got), got)

    def test_red_plate_with_white_digits_is_not_the_graphic(self):
        # The last fifteen seconds' red plate [domain:hud/low-clock-red-plate].
        got = pg.read_field(_crop(field_bgr=(60, 60, 150), digits=True))
        self.assertGreater(got["red"], pg.GRAPHIC_CUT)
        self.assertFalse(pg.shows_graphic(got), got)

    def test_white_clock_is_not_the_graphic(self):
        self.assertFalse(pg.shows_graphic(pg.read_field(_crop(digits=True))))

    def test_missing_crop_refuses(self):
        got = pg.read_field(None)
        self.assertEqual(got["reason"], "no_crop")
        self.assertIsNone(pg.shows_graphic(got))
        self.assertIsNone(pg.shows_graphic(None))

    def test_score_is_resolution_free(self):
        a = pg.read_field(_crop(field_bgr=(20, 20, 220)))
        b = pg.read_field(_crop(field_bgr=(20, 20, 220), h=40, w=205))
        self.assertAlmostEqual(a["red"], b["red"], places=1)


def _round(clock, shown, step=500.0):
    """HUD samples at `step` from 0 with `clock` readings and graphic rows
    whose score is above the cut where `shown` is truthy (None: no row)."""
    t = [i * step for i in range(len(clock))]
    g = {}
    for ti, s in zip(t, shown):
        if s is not None:
            g[ti] = {"score": 0.4 if s else 0.0}
    return t, list(clock), g


class PlantState(unittest.TestCase):
    def test_two_graphic_samples_with_no_clock_are_a_plant(self):
        # A live clock, then the graphic for 1 s before the round ends: an
        # elimination soon after the plant, which the 7 s floor missed.
        t, clock, g = _round([90000, 89000, 88000, None, None], [0, 0, 0, 1, 1])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIs(got["spike_planted"], True)
        self.assertEqual(got["plant_t_ms"], t[3])
        self.assertEqual(got["post_plant_ms"], t[-1] - t[3])
        self.assertEqual(got["plant_source"], "plant_graphic")

    def test_one_sample_is_too_short(self):
        t, clock, g = _round([90000, 89000, 88000, 87000, None], [0, 0, 0, 0, 1])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIsNone(got["spike_planted"])
        self.assertEqual(got["plant_reason"], "graphic_single_sample")

    def test_a_read_clock_refutes_the_graphic(self):
        t, clock, g = _round([90000, 89000, 88000, 87000], [0, 1, 1, 1])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIs(got["spike_planted"], False)

    def test_no_graphic_is_false_not_null(self):
        t, clock, g = _round([90000, None, None, None], [0, 0, 0, 0])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIs(got["spike_planted"], False)
        self.assertIsNone(got["plant_reason"])

    def test_graphic_before_the_live_clock_is_not_a_plant(self):
        # A round opened at the capture's start: red menus before play.
        t, clock, g = _round([None, None, None, 90000, 89000], [1, 1, 1, 0, 0])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIs(got["spike_planted"], False)

    def test_no_live_clock_is_null(self):
        t, clock, g = _round([30000, 29000, None, None], [0, 0, 1, 1])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIsNone(got["spike_planted"])
        self.assertEqual(got["plant_reason"], "no_live_clock")

    def test_no_rows_in_the_round_is_null(self):
        t, clock, g = _round([90000, 89000, None], [None, None, None])
        got = plant_state(t, clock, 0.0, t[-1], g)
        self.assertIsNone(got["spike_planted"])
        self.assertEqual(got["plant_reason"], "no_plant_graphic_rows")

    def test_without_the_stream_only_the_clock_run_marks_a_plant(self):
        # 40 s of live clock, then 10 s unread to the end: the old run rule.
        n_live, n_run = 80, 20
        t = [i * 500.0 for i in range(n_live + n_run)]
        clock = [100000 - i * 500 for i in range(n_live)] + [None] * n_run
        got = plant_state(t, clock, 0.0, t[-1], None)
        self.assertIs(got["spike_planted"], True)
        self.assertEqual(got["plant_source"], "clock_run")
        # A short run is no evidence either way without the graphic.
        got = plant_state(t[:n_live + 2], clock[:n_live + 2], 0.0, t[n_live + 1], None)
        self.assertIsNone(got["spike_planted"])
        self.assertEqual(got["plant_reason"], "plant_graphic_absent")


class Events(unittest.TestCase):
    def test_coverage_row_then_samples(self):
        reads = [(0, 0.0, pg.read_field(_crop(field_bgr=(20, 20, 220)))),
                 (1, 500.0, pg.read_field(None))]
        rows = pg.graphic_events("s", reads, [1, 2, 3, 4], "roi-cache-0.1.0")
        self.assertEqual(rows[0]["kind"], "coverage")
        self.assertEqual((rows[0]["frames"], rows[0]["graphic"], rows[0]["no_crop"]), (2, 1, 1))
        self.assertTrue(all(r["plant_graphic_version"] == pg.PLANT_GRAPHIC_VERSION for r in rows))


if __name__ == "__main__":
    unittest.main()
