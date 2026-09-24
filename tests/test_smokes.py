"""`adjudication.smokes` over synthetic `minimap_dark` rows."""
import unittest

import numpy as np

from reticle.adjudication import smokes
from reticle.lighting import pack_mask

H, W = 485, 465  # the bigmap widget, so AREA_MIN_REF applies unscaled
KNOWN = np.ones((H, W), bool)
YY, XX = np.ogrid[:H, :W]


def disc(cx, cy, r):
    return (XX - cx) ** 2 + (YY - cy) ** 2 <= r * r


def frame(t_ms, dark=None, occ=None, drawn=True):
    if not drawn:
        return {"kind": "frame", "t_ms": t_ms, "widget_drawn": False}
    z = np.zeros((H, W), bool)
    return {"kind": "frame", "t_ms": t_ms, "widget_drawn": True,
            "grey_dark": pack_mask(z if dark is None else dark),
            "occluded": pack_mask(z if occ is None else occ)}


def session(spec, hz=4.0):
    """`spec(t_s) -> frame row`, sampled at `hz` for 30 s."""
    rows = [{"kind": "coverage", "hz": hz}]
    rows += [spec(i / hz) for i in range(int(30 * hz))]
    return rows


class SmokeTracks(unittest.TestCase):
    def test_an_observed_smoke_has_one_track_and_its_lifetime(self):
        d = disc(200, 200, 12)
        rows = session(lambda t: frame(t * 1000, d if 5 <= t < 23 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["end_status"], "observed")
        self.assertAlmostEqual(got[0]["life_s"], 17.75, places=2)

    def test_an_undrawn_widget_neither_ages_nor_ends_a_track(self):
        d = disc(200, 200, 12)
        rows = session(lambda t: frame(t * 1000, drawn=False) if 10 <= t < 14
                       else frame(t * 1000, d if 5 <= t < 23 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["end_status"], "observed")

    def test_an_end_hidden_by_an_icon_is_censored(self):
        d = disc(200, 200, 12)
        cover = disc(200, 200, 16)
        rows = session(lambda t: frame(t * 1000, d if 5 <= t < 20 else None,
                                       cover if 19 <= t < 21 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["end_status"], "censored:unobserved")

    def test_a_smoke_alive_at_capture_end_is_censored(self):
        d = disc(200, 200, 12)
        rows = session(lambda t: frame(t * 1000, d if t >= 20 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(got[0]["end_status"], "censored:capture_end")
        self.assertIsNone(got[0]["end_bound_ms"])

    def test_a_textured_smoke_below_the_birth_area_stays_one_track(self):
        d = disc(200, 200, 12)
        hatch = d & ((XX + YY) % 3 != 0)          # a third of the disc not dark
        rows = session(lambda t: frame(t * 1000, (d if t < 6 else hatch) if 5 <= t < 23 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(len(got), 1)

    def test_small_components_and_widget_wide_darkening_make_no_track(self):
        small = disc(100, 100, 4)
        everything = np.ones((H, W), bool)
        rows = session(lambda t: frame(t * 1000, everything if 10 <= t < 12 else small))
        self.assertEqual(smokes.tracks(rows, KNOWN), [])

    def test_a_sampling_gap_censors_the_end_it_hides(self):
        d = disc(200, 200, 12)
        rows = [{"kind": "coverage", "hz": 4.0}]
        rows += [frame(i * 250.0, d if i >= 20 else None) for i in range(60)]          # 0-15 s
        rows += [frame(20000 + i * 250.0) for i in range(20)]                            # 20-25 s, gone
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(got[0]["end_status"], "censored:unobserved")

    def test_a_smoke_first_seen_as_an_icon_leaves_it_has_a_censored_onset(self):
        d = disc(200, 200, 12)
        cover = disc(200, 200, 16)
        rows = session(lambda t: frame(t * 1000, d if 5 <= t < 23 else None,
                                       cover if t < 8 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(got[0]["onset_status"], "censored:unobserved")
        clear = session(lambda t: frame(t * 1000, d if 5 <= t < 23 else None))
        self.assertEqual(smokes.tracks(clear, KNOWN)[0]["onset_status"], "observed")

    def test_a_partly_covered_smoke_born_as_an_icon_leaves_has_a_censored_onset(self):
        d = disc(200, 200, 12)
        part = disc(212, 200, 7)                  # the icon leaves most of the disc covered
        rows = session(lambda t: frame(t * 1000, d if 5 <= t < 23 else None,
                                       (d & ~part) if t < 8 else None))
        got = smokes.tracks(rows, KNOWN)
        self.assertEqual(got[0]["onset_status"], "censored:unobserved")


if __name__ == "__main__":
    unittest.main()
