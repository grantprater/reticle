"""`icon_prior`: the spike glyph's prior, the dropped-glyph mask, the carrier
flag, the per-side icon track and the audit cadence, on synthetic crops."""
import unittest

import cv2
import numpy as np

from reticle import icon_prior, spike
from reticle.minimap import self_icons

YELLOW = (40, 225, 205)          # BGR: the glyph's greenish yellow
SELF = (120, 240, 220)           # BGR: passes `minimap.self_mask`


def _crop(w=465, h=465):
    return np.full((h, w, 3), 128, np.uint8)


def _draw_glyph(crop, cx, cy, side=21.0, base_down=True):
    t = spike.glyph_template(side, base_down)
    p = t.shape[0] // 2
    win = crop[cy - p:cy + p + 1, cx - p:cx + p + 1].astype(np.float32)
    a = t[..., None]
    crop[cy - p:cy + p + 1, cx - p:cx + p + 1] = (
        win * (1 - a) + np.array(YELLOW, np.float32) * a).astype(np.uint8)


def _draw_icon(crop, cx, cy, r=10):
    cv2.circle(crop, (cx, cy), r, SELF, 2)


FLOOR = np.ones((465, 465), bool)


class GlyphTrackTest(unittest.TestCase):
    def test_dropped_glyph_is_checked_at_its_place(self):
        crop = _crop()
        _draw_glyph(crop, 200, 200)
        g = icon_prior.GlyphTrack()
        first = g.step(crop, None, 0.0)
        self.assertEqual((first["state"], first["rests_on"]), ("dropped", "full_search"))
        second = g.step(crop, None, 66.7)
        self.assertEqual((second["state"], second["rests_on"]), ("dropped", "prior"))
        self.assertEqual((second["cx"], second["cy"]), (first["cx"], first["cy"]))

    def _confirmed(self, crop):
        g = icon_prior.GlyphTrack()
        for i in range(1 + icon_prior.CONFIRM_CHECKS):
            g.step(crop, None, i * 66.7)
        return g

    def test_a_missing_glyph_is_held_then_lost(self):
        crop, empty = _crop(), _crop()
        _draw_glyph(crop, 200, 200)
        g = self._confirmed(crop)
        held = g.step(empty, None, 1000.0)
        self.assertEqual((held["state"], held["rests_on"]), ("dropped", "prior_held"))
        for t in (4000.0, 7000.0, 10000.0):
            self.assertEqual(g.step(empty, None, t)["rests_on"], "prior_held")
        lost = g.step(empty, None, 200.0 + icon_prior.HOLD_UNVERIFIED_MS)
        self.assertIsNone(lost["state"])
        self.assertEqual([s["kind"] for s in lost["surprises"]], ["glyph_lost"])

    def test_an_unconfirmed_glyph_sets_no_prior(self):
        crop, empty = _crop(), _crop()
        _draw_glyph(crop, 200, 200)
        g = icon_prior.GlyphTrack()
        g.step(crop, None, 0.0)
        got = g.step(empty, None, 66.7)
        self.assertIsNone(got["state"])
        self.assertEqual([s["kind"] for s in got["surprises"]], ["glyph_unconfirmed"])

    def test_a_glyph_moving_without_a_carrier_is_a_surprise(self):
        a, b = _crop(), _crop()
        _draw_glyph(a, 200, 200)
        _draw_glyph(b, 300, 120)
        g = self._confirmed(a)
        got = g.step(b, None, 1000.0)
        self.assertEqual(got["state"], "dropped")
        self.assertEqual([s["kind"] for s in got["surprises"]], ["glyph_moved_without_carrier"])

    def test_a_pickup_follows_the_carried_glyph(self):
        a, b = _crop(), _crop()
        _draw_glyph(a, 200, 200)
        _draw_glyph(b, 205, 195, 17.5, False)
        g = icon_prior.GlyphTrack()
        g.step(a, None, 0.0)
        got = g.step(b, None, 66.7)
        self.assertEqual((got["state"], got["rests_on"]), ("carried", "full_search"))
        self.assertEqual(got["surprises"], [])

    def test_a_gap_expires_the_prior(self):
        crop = _crop()
        _draw_glyph(crop, 200, 200)
        g = icon_prior.GlyphTrack()
        g.step(crop, None, 0.0)
        got = g.step(crop, None, icon_prior.RESET_GAP_MS + 1.0)
        self.assertEqual(got["rests_on"], "full_search")


class MaskTest(unittest.TestCase):
    def test_the_glyph_alone_yields_no_self_fit_once_masked(self):
        crop = _crop()
        _draw_glyph(crop, 200, 200)
        g = spike.accepted(spike.glyph_fits(crop))[0]
        self.assertTrue(self_icons(crop, FLOOR, require_facing=False))
        veto = icon_prior.veto_for(crop.shape, g, 1.0)
        self.assertEqual(self_icons(crop, FLOOR, require_facing=False, veto=veto), [])

    def test_an_icon_on_the_glyph_is_fitted_from_its_ring(self):
        crop = _crop()
        _draw_icon(crop, 206, 196)
        _draw_glyph(crop, 200, 200)
        g = spike.accepted(spike.glyph_fits(crop))[0]
        veto = icon_prior.veto_for(crop.shape, g, 1.0)
        fits = self_icons(crop, FLOOR, require_facing=False, veto=veto)
        self.assertTrue(fits)
        best = max(fits, key=lambda f: f["cov"])
        self.assertLessEqual(np.hypot(best["cx"] - 206, best["cy"] - 196), 3.0)

    def test_a_carried_glyph_is_not_masked(self):
        self.assertIsNone(icon_prior.veto_for((465, 465, 3), {"state": "carried", "cx": 1,
                                                              "cy": 1, "side": 17.5}, 1.0))


class AnnotateTest(unittest.TestCase):
    def test_the_carrier_is_flagged_and_the_glyph_ring_refused(self):
        glyph = {"cx": 100.0, "cy": 100.0, "state": "carried", "side": 17.5}
        carrier = {"cx": 107.0, "cy": 92.5}
        ring = {"cx": 101.0, "cy": 100.0}
        fits = icon_prior.glyph_say([carrier, ring], icon_prior.SIDES["self"], glyph, 1.0,
                                   icons=[carrier, ring])
        self.assertTrue(carrier["carries_spike"])
        self.assertIsNone(carrier["refused"])
        self.assertEqual(ring["refused"], "on_carried_glyph")
        self.assertEqual(len(fits), 2)

    def test_an_enemy_never_carries(self):
        glyph = {"cx": 100.0, "cy": 100.0, "state": "carried", "side": 17.5}
        fit = {"cx": 107.0, "cy": 92.5}
        icon_prior.glyph_say([fit], icon_prior.SIDES["enemy"], glyph, 1.0, icons=[fit])
        self.assertFalse(fit["carries_spike"])

    def test_a_fit_near_a_dropped_glyph_is_marked_not_refused(self):
        glyph = {"cx": 100.0, "cy": 100.0, "state": "dropped", "side": 21.0}
        fit = {"cx": 104.0, "cy": 97.0}
        icon_prior.glyph_say([fit], icon_prior.SIDES["ally"], glyph, 1.0, icons=[fit])
        self.assertTrue(fit["glyph_masked"])
        self.assertIsNone(fit["refused"])


class IconTrackTest(unittest.TestCase):
    def test_a_jump_is_a_surprise(self):
        tr = icon_prior.IconTrack(icon_prior.SIDES["self"], 1.0, 66.7)
        tr.step(0.0, [{"cx": 100.0, "cy": 100.0, "cov": 0.9}])
        got = tr.step(66.7, [{"cx": 300.0, "cy": 300.0, "cov": 0.9}])
        self.assertEqual(got["rests_on"], "sole_candidate")
        self.assertEqual([s["kind"] for s in got["surprises"]], ["self_jump"])

    def test_an_enemy_track_holds_its_last_known_place(self):
        tr = icon_prior.IconTrack(icon_prior.SIDES["enemy"], 1.0, 66.7)
        tr.step(0.0, [{"cx": 100.0, "cy": 100.0, "cov": 0.9}])
        held = tr.step(1000.0, [])
        self.assertEqual(held["rests_on"], "last_known")
        self.assertEqual(held["held_xy"], (100.0, 100.0))
        gone = tr.step(1000.0 + icon_prior.LAST_KNOWN_MS, [])
        self.assertEqual(gone["rests_on"], "no_candidate")

    def test_a_self_track_does_not(self):
        tr = icon_prior.IconTrack(icon_prior.SIDES["self"], 1.0, 66.7)
        tr.step(0.0, [{"cx": 100.0, "cy": 100.0, "cov": 0.9}])
        self.assertEqual(tr.step(1000.0, [])["rests_on"], "no_candidate")


class AllyDecisionTest(unittest.TestCase):
    """`ally_decisions` 0.3.0: a masked fit is not refused for a dropped glyph."""

    def _row(self, key, masked=None, state="dropped"):
        row = {"candidate_key": key, "frame_idx": 1, "channel": "ally", "cov": 0.9,
               "inner": 0.0, "cx": 100.0, "cy": 100.0, "widget_scale": 1.0,
               "facing": 0.0, "map_diff": 40.0,
               "spike_glyphs": [{"cx": 101.0, "cy": 100.0, "state": state, "side": 21.0,
                                 "ncc": 0.85, "amp": 120.0, "reason": None}]}
        if masked is not None:
            row["glyph_masked"] = masked
        return row

    def test_masked_fit_on_a_dropped_glyph_is_kept(self):
        from reticle.adjudication.minimap_candidates import ally_decisions
        (old,) = ally_decisions([self._row("a")])
        (new,) = ally_decisions([self._row("b", masked=True)])
        self.assertEqual(old["reason"], "on_spike_glyph")
        self.assertEqual(new["disposition"], "accepted")

    def test_a_carried_glyph_still_refuses_its_ring(self):
        from reticle.adjudication.minimap_candidates import ally_decisions
        (d,) = ally_decisions([self._row("c", masked=False, state="carried")])
        self.assertEqual(d["reason"], "on_spike_glyph")


class AuditClockTest(unittest.TestCase):
    def test_cadence_and_first_frame_after_a_gap(self):
        c = icon_prior.AuditClock(every=3)
        got = [c.tick(t * 66.7) for t in range(7)]
        self.assertEqual(got, [True, False, False, True, False, False, True])
        self.assertTrue(c.tick(7 * 66.7 + icon_prior.RESET_GAP_MS + 1))


class SelfTrackerTest(unittest.TestCase):
    def test_self_on_the_dropped_spike_is_kept(self):
        crop = _crop()
        _draw_icon(crop, 300, 300)
        _draw_icon(crop, 206, 196)
        _draw_glyph(crop, 200, 200)
        tr = icon_prior.SelfTracker(FLOOR, None, 1.0, 66.7)
        first = tr.step(crop, 0.0)
        self.assertEqual(first["spike_state"], "dropped")
        self.assertIsNotNone(first["self_x"])
        self.assertEqual(len(tr.audits), 1)

    def test_widget_absent_row_is_a_reason(self):
        tr = icon_prior.SelfTracker(FLOOR, None, 1.0, 66.7)
        got = tr.step(_crop(), 0.0)
        self.assertEqual((got["self_x"], got["self_reason"]), (None, "no_candidate"))


if __name__ == "__main__":
    unittest.main()
