"""Tests for the killfeed weapon scorer's registration and whitened matched filter."""
from __future__ import annotations

import unittest

import numpy as np

from reticle.adjudication import weapon
from reticle.adjudication.weapon import (REFUSE_AMBIGUOUS, REFUSE_NEW, REFUSE_REGISTRATION,
                                         REFUSE_TIE, TIE_Z, WHITEN_CANVAS, WHITEN_LEFT,
                                         _name_white, _thin_reason, _white_index,
                                         candidate_tiers, name_frame, register_canvas,
                                         soft_canvas, whiten_scale)
from reticle.killfeed import ICON_GRID, soft_patch

H, W = int(WHITEN_CANVAS[0]), int(WHITEN_CANVAS[1])


def _glyph(x0: int, x1: int, y0: int = 12, y1: int = 22) -> np.ndarray:
    c = np.zeros((H, W), np.float32)
    c[y0:y1, x0:x1] = 1.0
    return c


def _index(refs: dict[str, np.ndarray], limits=None) -> dict:
    """An identity-covariance parameter set: W = mu, c = mu.mu / 2."""
    names = list(refs)
    R = np.array([refs[n].ravel() for n in names], np.float32)
    return _white_index({"names": np.array(names), "refs": R, "W": R.copy(),
                         "c": 0.5 * np.einsum("kd,kd->k", R, R),
                         "provenance": {"limits": limits or {"excess": 0.15, "deficit": 0.2}}})


def _row(w: np.ndarray, scale: float = 1.0) -> dict:
    ok = np.ones(w.shape[1], bool)
    return {"soft": soft_patch(w, ok, 0, w.shape[1]),
            "slot_geom": {"scale": {"scale": scale}}}


class RegistrationTests(unittest.TestCase):
    def test_left_edge_is_sub_pixel_and_lands_on_the_canvas_left(self):
        """The edge is where the column maximum crosses the cut, interpolated
        between columns; the warp puts it at WHITEN_LEFT and the centroid row
        on the middle row."""
        w = np.zeros((20, 60), np.float32)
        w[3:7, 5] = 0.25
        w[3:7, 6:30] = 1.0
        canvas, info = register_canvas(w)
        self.assertAlmostEqual(info["x_edge"], 6 - 0.5 / 0.75, places=3)
        self.assertAlmostEqual(info["y_centroid"], 4.5, places=3)
        self.assertEqual(canvas.shape, (H, W))
        self.assertAlmostEqual(float(canvas[:, int(WHITEN_LEFT)].max()), 0.5, places=2)
        rows = canvas.sum(axis=1)
        self.assertAlmostEqual(float((rows * np.arange(H)).sum() / rows.sum()), (H - 1) / 2, places=2)

    def test_no_column_crossing_the_cut_refuses(self):
        canvas, info = register_canvas(np.full((20, 60), 0.4, np.float32))
        self.assertIsNone(canvas)
        self.assertEqual(info, {"reason": "no_edge"})

    def test_ink_on_the_patch_border_is_an_unobserved_edge(self):
        w = np.zeros((20, 60), np.float32)
        w[3:7, 0:30] = 0.8
        self.assertEqual(register_canvas(w), (None, {"reason": "edge_at_border"}))

    def test_an_unknown_plate_inside_the_box_leaves_the_glyph_unread(self):
        """59c70f1ef720 2198.0 s slot 0: the plate is unknown over the
        Vandal's first nine columns, stored as whiteness 0; read as dark, the
        glyph registered 8 px late and scored Spectre."""
        w = np.zeros((34, 83), np.float32)
        w[10:24, 3:80] = 1.0
        ok = np.ones(83, bool)
        ok[:12] = False
        row = {"soft": soft_patch(w, ok, 0, 83), "ix0": 3, "ix1": 80}
        self.assertEqual(soft_canvas(row, 1.0), (None, {"reason": "plate_unknown"}))
        ok[:12] = True
        ok[:3] = False                          # outside the box: still read
        row = {"soft": soft_patch(w, ok, 0, 83), "ix0": 3, "ix1": 80}
        self.assertIsNotNone(soft_canvas(row, 1.0)[0])

    def test_a_larger_capture_is_shrunk_never_a_smaller_one_enlarged(self):
        w = np.zeros((34, 90), np.float32)
        w[10:24, 10:70] = 1.0
        canvas, _ = soft_canvas(_row(w, 1.5), 1.0)
        self.assertEqual(canvas.shape, (H, W))
        self.assertEqual(soft_canvas(_row(w, 0.667), 1.0), (None, {"reason": "row_below_scale"}))
        self.assertEqual(soft_canvas({}, 1.0), (None, {"reason": "no_soft"}))
        self.assertEqual((whiten_scale(1.5), whiten_scale(0.6667)), (1.0, 0.667))


class WhitenedNamingTests(unittest.TestCase):
    def test_a_clear_glyph_names_its_reference(self):
        idx = _index({"Long": _glyph(4, 80), "Short": _glyph(4, 30)})
        v = _name_white(_glyph(4, 80), idx, {"Long", "Short"})
        self.assertEqual((v["name"], v["pair"]), ("Long", ["Long", "Short"]))
        self.assertGreater(v["z"], TIE_Z)

    def test_two_references_too_close_to_part_are_a_pairwise_tie(self):
        """With identity covariance z = |mu_a - mu_b| / 2: one column apart is
        sqrt(10)/2, under TIE_Z."""
        idx = _index({"A": _glyph(4, 60), "B": _glyph(4, 61)})
        v = _name_white(_glyph(4, 60), idx, {"A", "B"})
        self.assertEqual((v["name"], v["reason"], v["best"]), (None, REFUSE_TIE, "A"))
        self.assertLess(v["z"], TIE_Z)

    def test_ink_beyond_the_winner_is_a_registration_failure(self):
        g = _glyph(4, 60)
        g[0:4, 70:99] = 1.0                     # a straddled neighbour's ink
        v = _name_white(g, _index({"A": _glyph(4, 60), "B": _glyph(4, 20)}), {"A", "B"})
        self.assertEqual((v["name"], v["reason"]), (None, REFUSE_REGISTRATION))
        self.assertGreater(v["coverage"][0], 0.15)

    def test_a_winner_the_iou_floor_did_not_clear_is_ambiguous(self):
        v = _name_white(_glyph(4, 80), _index({"Long": _glyph(4, 80), "Short": _glyph(4, 30)}),
                        {"Short"})
        self.assertEqual((v["name"], v["reason"], v["best"]), (None, REFUSE_AMBIGUOUS, "Long"))

    def test_an_empty_candidate_set_is_new(self):
        empty = _white_index({"names": np.array([], str), "refs": np.zeros((0, H * W), np.float32),
                              "W": np.zeros((0, H * W), np.float32), "c": np.zeros(0, np.float32)})
        self.assertEqual(_name_white(_glyph(4, 80), empty, set())["reason"], REFUSE_NEW)

    def test_thin_reason_reports_the_new_refusals(self):
        self.assertEqual(_thin_reason({REFUSE_TIE: 3}, 4), REFUSE_TIE)
        self.assertEqual(_thin_reason({REFUSE_REGISTRATION: 3, REFUSE_NEW: 1}, 4),
                         REFUSE_REGISTRATION)
        self.assertEqual(_thin_reason({REFUSE_TIE: 1, REFUSE_NEW: 1}, 4), "too_few_named")


class NameFrameTests(unittest.TestCase):
    @staticmethod
    def _grid(cols, rows=16):
        g = np.zeros(ICON_GRID, dtype=np.uint8)
        g[:rows, :cols] = 1
        return g

    def _tiers(self):
        gallery = {"names": np.array(["Long", "Short"]),
                   "masks": np.array([self._grid(60), self._grid(20)]),
                   "aspects": np.array([3.0, 3.0])}
        refs = _index({"Long": _glyph(4, 80), "Short": _glyph(4, 30)})
        whiten = {k: v for k, v in zip(("names", "refs", "W", "c"),
                                       (np.array(refs["names"]), refs["refs"], refs["W"], refs["c"]))}
        whiten["aspects"] = np.array([3.0, 3.0])
        whiten["provenance"] = {"limits": refs["limits"]}
        return candidate_tiers(gallery, whiten=whiten)

    def test_the_whitened_filter_decides_within_the_iou_cleared_names(self):
        v = name_frame(self._grid(60), 3.0, self._tiers(), (_glyph(4, 80), {}))
        self.assertEqual((v["name"], v["scorer"], v["tier"]), ("Long", "whitened", "full"))
        self.assertEqual(v["iou"]["best"], "Long")

    def test_an_unregistered_glyph_refuses_where_iou_would_name_it(self):
        tiers = self._tiers()
        self.assertEqual(name_frame(self._grid(60), 3.0, tiers)["name"], "Long")
        v = name_frame(self._grid(60), 3.0, tiers, (None, {"reason": "no_edge"}))
        self.assertEqual((v["name"], v["reason"]), (None, REFUSE_REGISTRATION))

    def test_an_icon_iou_calls_new_stays_new(self):
        v = name_frame(self._grid(5, 3), 3.0, self._tiers(), (_glyph(4, 80), {}))
        self.assertEqual((v["name"], v["reason"], v["scorer"]), (None, REFUSE_NEW, "iou"))


class StoreParameterTests(unittest.TestCase):
    def test_the_gallery_at_0667_leaves_out_unreadable_placements(self):
        """Hot Hands drawn at 0.667 x 24 px falls under the reader's own gate;
        the gallery lists it unreadable instead of refusing whole."""
        gal, why = weapon.load_gallery(None, 0.667)
        if gal is None and why in ("no_gallery", "no_game_icons"):
            self.skipTest(why)
        self.assertIsNone(why)
        un = gal["provenance"]["game"]["unreadable"]
        self.assertTrue(any(u.startswith("Hot Hands@") for u in un))
        full, _ = weapon.load_gallery(None, 1.0)
        self.assertEqual(full["provenance"]["game"]["unreadable"], [])

    def test_entry_weapon_records_whitening_it_could_not_load(self):
        from unittest import mock
        grid = np.zeros(ICON_GRID, np.uint8)
        grid[:16, :20] = 1
        hexgrid = np.packbits(grid.astype(bool)).tobytes().hex()
        rows = [{"kind": "weapon_icon_observation", "t_ms": t, "slot": 0, "wx0": 200, "wx1": 220,
                 "aspect": 1.0, "grid": hexgrid} for t in (0, 500, 1000)]
        gal = {"names": np.array(["Aftershock"]), "masks": np.array([grid]),
               "aspects": np.array([1.0])}
        with mock.patch.object(weapon, "load_whitening", return_value=(None, "no_whitening:1.000")):
            ev = weapon.entry_weapon({"t_first": 0, "t_last": 1000, "slot": 0, "sig": 200}, rows, gal)
        self.assertEqual(ev["name"], "Aftershock")
        self.assertEqual((ev["whiten"]["status"], ev["whiten"]["reason"]),
                         ("unavailable", "no_whitening:1.000"))


if __name__ == "__main__":
    unittest.main()
