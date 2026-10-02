"""The ally teardrop's prior: association, surprises, the audit cadence and `rests_on`."""
import math
import unittest
from unittest.mock import patch

import numpy as np

from reticle import teardrop


def _teal(cx, cy, deg, size=90):
    """A teal ally teardrop drawn by the ally class's own model."""
    c = teardrop.ICON_CLASSES["ally"]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    m = teardrop.render(xx - cx, yy - cy, np.float32(math.radians(deg)),
                        c.r_in, c.r_out, c.L, teardrop.EDGE)
    crop = np.zeros((size, size, 3), np.uint8)
    crop[..., 0] = crop[..., 1] = (80 * m).astype(np.uint8)
    return crop


def _ang(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


class PriorTests(unittest.TestCase):
    def test_the_first_image_searches_in_full_with_no_prior(self):
        o = teardrop.IconPoseReader("ally").read(_teal(45, 45, 30), 46.0, 44.0,
                                                 frame_idx=1, t_ms=0.0, ref="1:ally:0")
        self.assertEqual((o["search"], o["surprise"], o["rests_on"]), ("full", "no_prior", None))
        self.assertEqual(o["origin"], "teardrop")

    def test_a_near_icon_continues_its_prior_and_names_it(self):
        r = teardrop.IconPoseReader("ally")
        r.read(_teal(45, 45, 30), 46.0, 44.0, frame_idx=1, t_ms=0.0, ref="1:ally:0")
        crop = _teal(46.2, 44.5, 38)
        o = r.read(crop, 47.0, 44.0, frame_idx=5, t_ms=66.7, ref="5:ally:0")
        self.assertEqual((o["search"], o["surprise"], o["rests_on"]), ("prior", None, "1:ally:0"))
        full = teardrop.fit_icon(crop, "ally", 47.0, 44.0)
        self.assertLess(math.hypot(o["x"] - full["x"], o["y"] - full["y"]), 0.2)
        self.assertLess(_ang(o["deg"], full["deg"]), 1.0)
        # The margin is measured at the fitted centre under either search.
        self.assertAlmostEqual(o["margin"], full["margin"], delta=0.01)

    def test_the_prior_binds_by_ring_centre_within_prior_px(self):
        r = teardrop.IconPoseReader("ally")
        r.read(_teal(30, 45, 0), 30.0, 45.0, frame_idx=1, t_ms=0.0, ref="a")
        far = r.read(_teal(30 + 8, 45, 0), 38.0, 45.0, frame_idx=5, t_ms=66.7, ref="b")
        self.assertEqual((far["search"], far["surprise"]), ("full", "no_prior"))

    def test_an_old_prior_is_a_gap(self):
        r = teardrop.IconPoseReader("ally")
        r.read(_teal(45, 45, 30), 46.0, 44.0, frame_idx=1, t_ms=0.0, ref="a")
        o = r.read(_teal(45.5, 45, 30), 46.0, 44.0, frame_idx=40, t_ms=650.0, ref="b")
        self.assertEqual((o["search"], o["surprise"]), ("full", "gap"))

    def test_a_turn_past_the_local_window_is_an_edge_surprise(self):
        r = teardrop.IconPoseReader("ally")
        r.read(_teal(45, 45, 0), 46.0, 44.0, frame_idx=1, t_ms=0.0, ref="a")
        crop = _teal(45, 45, 90)
        o = r.read(crop, 46.0, 44.0, frame_idx=5, t_ms=66.7, ref="b")
        self.assertEqual((o["search"], o["surprise"], o["rests_on"]), ("full", "edge", None))
        self.assertLess(_ang(o["deg"], 90.0), 2.0)

    def test_a_repeated_image_keeps_the_prior_s_age_from_its_last_sight(self):
        r = teardrop.IconPoseReader("ally")
        first = _teal(45, 45, 30)
        for i, t in enumerate((0.0, 66.7, 133.3, 200.0)):
            r.read(first, 46.0, 44.0, frame_idx=1 + 4 * i, t_ms=t, ref="a")
        o = r.read(_teal(45.5, 45, 32), 46.0, 44.0, frame_idx=17, t_ms=266.7, ref="b")
        self.assertEqual((o["search"], o["rests_on"]), ("prior", "a"))

    def test_without_a_frame_index_the_read_is_the_full_search_and_adds_nothing(self):
        crop = _teal(45, 45, 30)
        o = teardrop.IconPoseReader("ally").read(crop, 46.0, 44.0)
        self.assertFalse({"search", "surprise", "rests_on", "audit"} & set(o))
        full = teardrop.fit_icon(crop, "ally", 46.0, 44.0)
        self.assertEqual((o["x"], o["y"], o["deg"]), (full["x"], full["y"], full["deg"]))


class SurpriseTests(unittest.TestCase):
    prior = {"ncc": 0.8}

    def test_each_trigger_names_itself(self):
        base = {"x": 1.0, "read": True, "ncc": 0.78, "on_edge": False}
        self.assertIsNone(teardrop._surprise(base, self.prior))
        self.assertEqual(teardrop._surprise({**base, "on_edge": True}, self.prior), "edge")
        self.assertEqual(teardrop._surprise({**base, "ncc": 0.69}, self.prior), "ncc_drop")
        self.assertEqual(teardrop._surprise({**base, "outside_ncc": 0.79}, self.prior),
                         "facing_elsewhere")
        self.assertIsNone(teardrop._surprise({**base, "outside_ncc": 0.77}, self.prior))
        for why in ("low_ncc", "no_ring", "ambiguous_facing"):
            self.assertEqual(teardrop._surprise({**base, "read": False, "reason": why},
                                                self.prior), why)
        self.assertEqual(teardrop._surprise({"read": False, "reason": "no_key"}, self.prior),
                         "no_key")

    def test_a_gate_refusing_the_local_fit_runs_the_full_search(self):
        r = teardrop.IconPoseReader("ally")
        r.read(_teal(45, 45, 30), 46.0, 44.0, frame_idx=1, t_ms=0.0, ref="a")
        real = teardrop.fit_icon

        def refuse_local(*a, **kw):
            f = real(*a, **kw)
            if kw.get("prior") is not None:
                f.update(read=False, reason="ambiguous_facing")
            return f

        with patch("reticle.teardrop.fit_icon", side_effect=refuse_local):
            o = r.read(_teal(45.5, 45, 32), 46.0, 44.0, frame_idx=5, t_ms=66.7, ref="b")
        self.assertEqual((o["search"], o["surprise"], o["origin"]),
                         ("full", "ambiguous_facing", "teardrop"))


class AuditTests(unittest.TestCase):
    def _walk(self, poses):
        """Read one icon along `poses` at 15 Hz (frames 4 apart); the reads."""
        r = teardrop.IconPoseReader("ally")
        out = []
        for i, (x, deg) in enumerate(poses):
            f = 2 + 4 * i
            out.append(r.read(_teal(x, 45, deg), x + 1.0, 44.0, frame_idx=f,
                              t_ms=f * 1000 / 60, ref=f"{f}:ally:0"))
        return out

    def test_the_audit_falls_on_the_first_new_image_of_each_block_whatever_the_fit(self):
        still = self._walk([(45.0 + 0.01 * i, 30.0) for i in range(22)])
        turning = self._walk([(45.0 + 0.4 * i, 30.0 + 50.0 * (i % 2)) for i in range(22)])
        frames = [2 + 4 * i for i in range(22)]
        due = {f for f in frames if f // teardrop.AUDIT_FRAMES != (f - 4) // teardrop.AUDIT_FRAMES}
        due.discard(2)  # the first image has no prior to audit
        for reads in (still, turning):
            got = {f for f, o in zip(frames, reads) if "audit" in o}
            self.assertEqual(got, due)
        # The still icon continues its prior; the turning one surprises at the
        # edge, and its audit reuses that full search.
        a = next(o for f, o in zip(frames, still) if "audit" in o)
        self.assertEqual(a["search"], "prior")
        self.assertLess(_ang(a["audit"]["prior"]["deg"], a["audit"]["full"]["deg"]), 1.0)
        b = next(o for f, o in zip(frames, turning) if "audit" in o)
        self.assertEqual((b["search"], b["surprise"]), ("full", "edge"))
        self.assertEqual(b["audit"]["full"]["deg"], b["deg"])

    def test_posed_carries_the_search_and_its_prior(self):
        d = {"cx": 46.0, "cy": 44.0, "facing": 10.0}
        pose = {"origin": "teardrop", "x": 45.0, "y": 45.0, "deg": 30.0, "ncc": 0.8,
                "search": "prior", "surprise": None, "rests_on": "1:ally:0"}
        out = teardrop.posed(d, pose)
        self.assertEqual((out["pose"]["search"], out["pose"]["rests_on"]), ("prior", "1:ally:0"))
        bare = teardrop.posed(d, {k: v for k, v in pose.items()
                                  if k not in ("search", "surprise", "rests_on")})
        self.assertEqual(set(bare["pose"]), {"origin", "ncc", "reason", "facing_reason"})


if __name__ == "__main__":
    unittest.main()
