"""The enemy teardrop's soft ring gate and the reader's owner gate, on synthetic keys."""
from __future__ import annotations

import math
import unittest

import numpy as np

from reticle import minimap_objects as mo
from reticle import teardrop


def _ring_key(level: float, size: int = 60, cx: float = 30.0, cy: float = 30.0,
              r_in: float = 7.5, r_out: float = 10.5) -> np.ndarray:
    """A key holding a ring of uniform `level` between `r_in` and `r_out`."""
    yy, xx = np.mgrid[0:size, 0:size]
    rho = np.hypot(xx - cx, yy - cy)
    return np.where((rho >= r_in) & (rho <= r_out), level, 0.0).astype(np.float32)


class SoftRingTests(unittest.TestCase):
    def test_a_pale_ring_scores_in_proportion_and_the_hard_cut_drops_it(self):
        key = _ring_key(0.3)
        hard = teardrop.ring_cover(key, 30.0, 30.0, 0.0, 7.5, 10.5)
        soft = teardrop.ring_cover(key, 30.0, 30.0, 0.0, 7.5, 10.5, soft=True)
        self.assertEqual(hard, 0.0)
        self.assertAlmostEqual(soft, 0.3 / 0.5, places=5)

    def test_a_full_ring_scores_one_either_way(self):
        key = _ring_key(1.0)
        self.assertEqual(teardrop.ring_cover(key, 30.0, 30.0, 0.0, 7.5, 10.5), 1.0)
        self.assertEqual(teardrop.ring_cover(key, 30.0, 30.0, 0.0, 7.5, 10.5, soft=True), 1.0)

    def test_a_bar_across_the_ring_stays_under_the_gate(self):
        # A straight red bar crosses the annulus twice: soft or hard, most
        # bins away from the lobe hold nothing.
        key = np.zeros((60, 60), np.float32)
        key[:, 28:33] = 1.0
        soft = teardrop.ring_cover(key, 30.0, 30.0, 0.0, 7.5, 10.5, soft=True)
        self.assertLess(soft, teardrop.ICON_CLASSES["enemy"].min_ring)

    def test_only_the_enemy_class_scores_softly(self):
        self.assertTrue(teardrop.ICON_CLASSES["enemy"].soft_ring)
        self.assertFalse(teardrop.ICON_CLASSES["ally"].soft_ring)

    def test_soft_is_never_below_hard(self):
        rng = np.random.default_rng(0)
        for _ in range(20):
            key = rng.random((60, 60)).astype(np.float32) * rng.random()
            hard = teardrop.ring_cover(key, 30.0, 30.0, 45.0, 7.5, 10.5)
            soft = teardrop.ring_cover(key, 30.0, 30.0, 45.0, 7.5, 10.5, soft=True)
            self.assertGreaterEqual(soft + 1e-9, hard)


class OwnerGateTests(unittest.TestCase):
    marks = {"red": [{"x": 50.0, "y": 50.0}], "blue": [], "red_other": []}
    pings = np.array([[1000.0, 8000.0, 100.0, 100.0]])

    def test_a_read_at_a_red_x_is_the_x_classifiers(self):
        got = mo._owned(mo.ENABLED, self.marks, None, 2000.0, 52.0, 51.0, 1.0)
        self.assertEqual(got[0], "x_mark")
        self.assertTrue(got[1].startswith("owned_by_x_classifier"))

    def test_a_read_at_a_drawn_ping_is_the_pings_only_while_drawn(self):
        none = {"red": [], "blue": [], "red_other": []}
        self.assertEqual(mo._owned(mo.ENABLED, none, self.pings, 2000.0, 104.0, 103.0, 1.0)[0], "ping")
        self.assertIsNone(mo._owned(mo.ENABLED, none, self.pings, 9000.0, 104.0, 103.0, 1.0))
        self.assertIsNone(mo._owned(mo.ENABLED, none, self.pings, 2000.0, 130.0, 100.0, 1.0))

    def test_the_gate_scales_with_the_widget(self):
        none = {"red": [], "blue": [], "red_other": []}
        d = mo.PING_OWN_PX * 0.71 + 0.5      # past the scaled radius, inside the base one
        self.assertIsNone(mo._owned(mo.ENABLED, none, self.pings, 2000.0, 100.0 + d, 100.0, 0.71))
        self.assertEqual(mo._owned(mo.ENABLED, none, self.pings, 2000.0, 100.0 + d, 100.0, 1.0)[0], "ping")

    def test_off_or_without_a_ping_stream_the_gate_abstains(self):
        off = dict(mo.ENABLED, owner_gate=False)
        self.assertIsNone(mo._owned(off, self.marks, self.pings, 2000.0, 50.0, 50.0, 1.0))
        none = {"red": [], "blue": [], "red_other": []}
        self.assertIsNone(mo._owned(mo.ENABLED, none, None, 2000.0, 100.0, 100.0, 1.0))

    def test_stored_pings_pairs_each_appearance_with_its_expiry(self):
        class _S:
            def read_events(self, kind, sid):
                return [{"event_kind": "entity_state", "entity_id": "ping:danger:0", "t_ms": 100,
                         "position": [5.0, 6.0], "producer_version": "ping-0.1.0"},
                        {"event_kind": "entity_deleted", "entity_id": "ping:danger:0", "t_ms": 10100,
                         "producer_version": "ping-0.1.0"}]
        arr, ids, stamp = mo.stored_pings(_S(), "x")
        self.assertEqual(stamp, "ping-0.1.0")
        self.assertEqual(arr.tolist(), [[100.0, 10100.0, 5.0, 6.0]])
        self.assertEqual(ids, ["ping:danger:0"])

        class _E:
            def read_events(self, kind, sid):
                return []
        from reticle.input_stamps import NO_ROWS
        self.assertEqual(mo.stored_pings(_E(), "x"), (None, None, NO_ROWS))

    def test_the_ping_gate_reaches_the_glyph_not_the_icon_and_links_its_ping(self):
        none = {"red": [], "blue": [], "red_other": []}
        ids = ["ping:danger:7"]
        got = mo._owned(mo.ENABLED, none, self.pings, 2000.0, 105.0, 100.0, 1.0, ids)
        self.assertEqual(got[0], "ping")
        self.assertEqual(got[2], [{"stream": "ping", "entity_id": "ping:danger:7", "d_px": 5.0}])
        self.assertLess(mo.PING_OWN_PX, mo.ICON_PX)
        d = 0.5 * (mo.PING_OWN_PX + mo.ICON_PX)   # inside an icon's radius, off the glyph
        self.assertIsNone(mo._owned(mo.ENABLED, none, self.pings, 2000.0, 100.0 + d, 100.0, 1.0, ids))
        x_got = mo._owned(mo.ENABLED, self.marks, None, 2000.0, 52.0, 51.0, 1.0)
        self.assertIsNone(x_got[2])


class LobeTests(unittest.TestCase):
    """A teardrop's lobe adds what a ring cannot explain; a lobeless disc's does not."""

    def _key(self, L_):
        c = teardrop.ICON_CLASSES["enemy"]
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float32)
        if L_ is None:                       # a lobeless ring
            return teardrop.render_ring(xx - 30.0, yy - 29.0, c.r_in, c.r_out,
                                        teardrop.EDGE).astype(np.float32)
        return teardrop.render(xx - 30.0, yy - 29.0, np.float32(math.radians(40.0)),
                               c.r_in, c.r_out, L_, teardrop.EDGE).astype(np.float32)

    def test_the_ring_model_holds_no_mass_outside_the_annulus(self):
        """`lobe_gain`'s ring-only model: rendering the teardrop with its apex
        at `r_out` drew a tangent stripe outside the ring."""
        c = teardrop.ICON_CLASSES["enemy"]
        yy, xx = np.mgrid[-30:31, -30:31].astype(np.float64)
        e = teardrop.EDGE
        ring = teardrop.render_ring(xx, yy, c.r_in, c.r_out, e)
        rho = np.hypot(xx, yy)
        outside = (rho > c.r_out + e / 2) | (rho < c.r_in - e / 2)
        self.assertEqual(float(ring[outside].sum()), 0.0)
        self.assertGreater(float(ring[~outside].sum()), 0.0)
        old = teardrop.render(xx, yy, np.float64(0.7), c.r_in, c.r_out, c.r_out, e)
        self.assertGreater(float(old[outside].sum()), 0.0)   # the stripe the fix removes

    def test_a_teardrop_reads_with_a_positive_lobe_gain(self):
        f = teardrop.fit_icon(None, "enemy", 31.0, 30.0, key=self._key(18.0))
        self.assertTrue(f["read"], f.get("reason"))
        self.assertGreater(f["lobe_gain"], 0.1)

    def test_a_ring_with_no_lobe_is_refused_as_no_lobe(self):
        f = teardrop.fit_icon(None, "enemy", 31.0, 30.0, key=self._key(None))
        self.assertFalse(f["read"])
        self.assertEqual(f["reason"], "no_lobe")
        self.assertLessEqual(f["lobe_gain"], 0.0)

    def test_the_ally_class_has_no_lobe_test(self):
        self.assertIsNone(teardrop.ICON_CLASSES["ally"].min_lobe_gain)
        yy, xx = np.mgrid[0:60, 0:60].astype(np.float32)
        a = teardrop.ICON_CLASSES["ally"]
        key = teardrop.render(xx - 30.0, yy - 30.0, np.float32(0.4), a.r_in, a.r_out, a.L,
                              teardrop.EDGE).astype(np.float32)
        self.assertNotIn("lobe_gain", teardrop.fit_icon(None, "ally", 30.0, 30.0, key=key))


class IconScaleTests(unittest.TestCase):
    def test_the_teardrop_reads_at_the_icon_scale_and_the_x_owner_at_the_widgets(self):
        from unittest.mock import patch

        seen = {}

        def marks(crop, floor, scale):
            seen["x"] = scale
            return {"blue": [], "red": [], "red_other": []}

        def fit(crop, cls, cx, cy, *, scale, key):
            seen["fit"] = scale
            return {"read": False, "reason": "low_ncc", "ncc": 0.3}

        crop = np.zeros((40, 40, 3), np.uint8)
        ctx = {"floor": np.ones((40, 40), bool), "slab": np.ones((40, 40), bool), "scale": 0.7118}
        with patch("reticle.adjudication.death.minimap_x_marks", marks), \
                patch("reticle.minimap.icons", lambda *a, **k: [{"cx": 20.0, "cy": 20.0, "r": 6}]), \
                patch("reticle.teardrop.fit_icon", fit):
            mo.read_frame(crop, ctx, scale=0.6372)
        self.assertEqual(seen, {"x": 0.7118, "fit": 0.6372})


if __name__ == "__main__":
    unittest.main()
