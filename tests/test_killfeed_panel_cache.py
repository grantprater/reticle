"""The killfeed panel crop cache: the strip left of the killfeed ROI, gated on
stored killfeed entries, read with the `hud` set as one wider killfeed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from reticle.decode import Sample
from reticle.profiles import get_profile
from reticle.roi_cache import (RoiCache, RoiCacheWriter, in_spans, killfeed_panel_gate,
                               roi_rects)


def _manifest(sid="s1", key="k1"):
    return {"session_id": sid, "source_profile": "valorant-16x9",
            "source": {"width": 1920, "height": 1080, "content_key": key}}


def _needs_ffmpeg(test):
    from reticle.roi_cache import ffmpeg_path
    try:
        ffmpeg_path()
    except SystemExit:
        test.skipTest("ffmpeg not installed")


def _portrait_rows(entries, version="killfeed-portrait-test"):
    """A stored killfeed_portrait stream: a coverage row, then one row per
    (t_ms, role, reason) entry view."""
    common = {"session_id": "s1", "source": "killfeed", "killfeed_portrait_version": version}
    return [{**common, "kind": "coverage"}] + [
        {**common, "kind": "portrait_observation", "frame_idx": int(t // 500 * 30),
         "t_ms": float(t), "slot": 0, "role": role, **({"reason": why} if why else {})}
        for t, role, why in entries]


class KillfeedPanelRectTest(unittest.TestCase):

    def test_the_strip_lies_left_of_the_killfeed_roi_over_its_rows(self):
        profile = get_profile("valorant-16x9")
        self.assertEqual(roi_rects("killfeed_panel", profile, (1920, 1080)),
                         [[1278, 81, 1421, 346]])
        kf = roi_rects("killfeed", profile, (1920, 1080))[0]
        self.assertEqual(roi_rects("killfeed_panel", profile, (1920, 1080))[0][2], kf[0])

    def test_one_scale_transform_places_it_at_another_size(self):
        from reticle.killfeed import killfeed_roi
        profile = get_profile("valorant-16x9")
        x0, y0, _x1, y1 = (int(v) for v in killfeed_roi(profile).pixels(2560, 1440))
        # 143 px at 1080p is round(143 * 1440 / 1080) = 191 px at 1440p.
        self.assertEqual(roi_rects("killfeed_panel", profile, (2560, 1440)),
                         [[x0 - 191, y0, x0, y1]])


class KillfeedPanelGateTest(unittest.TestCase):
    """The gate is an entry on screen, one HUD sample either side; the panel,
    the outcome, never gates."""

    def test_killer_rows_open_one_sample_either_side(self):
        gate, why = killfeed_panel_gate(_portrait_rows(
            [(1000, "killer", None), (1000, "victim", None), (1500, "killer", None),
             (5000, "victim", None), (9000, "killer", "no gap past the name")]), 2.0)
        self.assertIsNone(why)
        self.assertEqual(gate["spans"], [[250.0, 2250.0], [8250.0, 9750.0]])
        kept = [t for t in range(0, 10500, 500) if in_spans(t, gate["spans"])]
        self.assertEqual(kept, [500, 1000, 1500, 2000, 8500, 9000, 9500])
        # A jittered timestamp a sample away is still held; two samples away is not.
        self.assertTrue(in_spans(2008.0, gate["spans"]))
        self.assertFalse(in_spans(2492.0, gate["spans"]))
        self.assertEqual((gate["witness"], gate["witness_version"], gate["witness_open"],
                          gate["margin_samples"], gate["roles"]),
                         ("killfeed_portrait", "killfeed-portrait-test", 3, 1, ["killer"]))

    def test_no_rows_is_no_gate_and_no_entries_keep_nothing(self):
        self.assertIn("no stored", killfeed_panel_gate([], 2.0)[1])
        gate, why = killfeed_panel_gate(_portrait_rows([(500, "victim", None)]), 2.0)
        self.assertIsNone(why)
        self.assertEqual((gate["spans"], gate["witness_open"]), ([], 0))

    def test_scan_refuses_a_panel_cache_it_cannot_write(self):
        from reticle.cli import _killfeed_panel_cache_gate
        from reticle.store import Store
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            args = lambda **kw: SimpleNamespace(**{"cache_live": False, "cache_hz": None,
                                                   "hz": 2.0, **kw})
            with self.assertRaises(SystemExit) as none:
                _killfeed_panel_cache_gate(store, "s1", args())
            self.assertIn("--only hud", str(none.exception))
            store.write_events("killfeed_portrait", "s1", _portrait_rows([(500, "killer", None)]))
            self.assertEqual(_killfeed_panel_cache_gate(store, "s1", args())["spans"],
                             [[0.0, 1250.0]])
            for bad in (args(cache_live=True), args(cache_hz=4.0)):
                with self.assertRaises(SystemExit):
                    _killfeed_panel_cache_gate(store, "s1", bad)


class KillfeedPanelUnionTest(unittest.TestCase):
    """The `hud` set and the gated strip read as one cache: the wider
    killfeed pasted from both, and the gate's refusal outside it."""

    def _write(self, root, frames, gate):
        profile = get_profile("valorant-16x9")
        man = _manifest()
        hud = RoiCacheWriter(Path(root), man, profile, "hud", hz=2.0)
        panel = RoiCacheWriter(Path(root), man, profile, "killfeed_panel", hz=2.0, gate=gate)
        for i, f in enumerate(frames):
            s = Sample(frame_idx=30 * i, t_ms=500.0 * i, frame=f)
            hud.feed(s)
            panel.feed(s)
        hud.finish()
        panel.finish()
        return profile, man

    def test_the_union_pastes_both_sets_and_refuses_outside_the_gate(self):
        _needs_ffmpeg(self)
        rng = np.random.default_rng(3)
        frames = [rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8) for _ in range(8)]
        gate, _ = killfeed_panel_gate(_portrait_rows([(1500, "killer", None)]), 2.0)
        with tempfile.TemporaryDirectory() as root:
            profile, man = self._write(root, frames, gate)
            union, why = RoiCache.load_union(Path(root), man, profile, "killfeed_wide")
            self.assertIsNone(why)
            self.assertEqual(union.rect_of("killfeed_wide"), [1278, 81, 1910, 346])
            self.assertEqual(union.holds("killfeed_wide"), [1000.0, 1500.0, 2000.0])
            x0, y0, x1, y1 = union.rect_of("killfeed_wide")
            got = list(union.samples([0.0, 1000.0, 1500.0, 2000.0, 3000.0], rois="killfeed_wide"))
            self.assertEqual([s.t_ms for s in got], [1000.0, 1500.0, 2000.0])
            for s in got:
                # Bit for bit: the strip (FFV1) and the killfeed (PNG) of one frame.
                self.assertTrue(np.array_equal(s.frame[y0:y1, x0:x1],
                                               frames[s.frame_idx // 30][y0:y1, x0:x1]))
                self.assertEqual(int(s.frame[:, :x0].max()), 0)
            # Outside the gate: the strip's refusal, never a black strip read as seen.
            self.assertEqual(union.refusal(0.0, "killfeed_wide"), "outside_gate")
            self.assertEqual(union.refusal(3000.0, "killfeed_wide"), "outside_gate")
            self.assertIsNone(union.refusal(3000.0, ["killfeed"]))
            self.assertEqual(len(list(union.samples([3000.0], rois=["killfeed"]))), 1)
            # The panel cache alone keeps the gated samples, and never feeds a scan.
            panel, _ = RoiCache.load(Path(root), man, profile, "killfeed_panel")
            self.assertEqual((panel.record["codec"], panel.record["frames_offered"],
                              panel.record["gate"]), ("ffv1", 8, gate))

    def test_parts_at_different_rates_do_not_unite(self):
        _needs_ffmpeg(self)
        profile = get_profile("valorant-16x9")
        gate, _ = killfeed_panel_gate(_portrait_rows([(0, "killer", None)]), 2.0)
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with tempfile.TemporaryDirectory() as root:
            man = _manifest()
            for name, hz, g in (("hud", 4.0, None), ("killfeed_panel", 2.0, gate)):
                w = RoiCacheWriter(Path(root), man, profile, name, hz=hz, gate=g)
                w.feed(Sample(frame_idx=0, t_ms=0.0, frame=frame))
                w.finish()
            union, why = RoiCache.load_union(Path(root), man, profile, ("hud", "killfeed_panel"))
            self.assertIsNone(union)
            self.assertIn("different rates", why)
            union, why = RoiCache.load_union(Path(root), _manifest(key="k2"), profile,
                                             "killfeed_wide")
            self.assertIsNone(union)
            self.assertIn("stale_content_key", why)


class PlanNamesTheMissingSetTest(unittest.TestCase):

    def test_plan_names_a_missing_panel_cache_where_the_hud_set_and_witness_exist(self):
        from reticle.plan import cache_work
        from reticle.store import Store
        _needs_ffmpeg(self)
        profile = get_profile("valorant-16x9")
        man = _manifest()
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            self.assertEqual(cache_work(store, man), [])          # no hud set, nothing owed
            w = RoiCacheWriter(Path(root), man, profile, "hud", hz=2.0)
            w.feed(Sample(frame_idx=0, t_ms=0.0, frame=frame))
            w.finish()
            self.assertEqual(cache_work(store, man), [])          # no witness rows yet
            rows = _portrait_rows([(0, "killer", None)])
            store.write_events("killfeed_portrait", "s1", rows)
            got = cache_work(store, man)
            self.assertEqual([(c["set"], c["reason"]) for c in got], [("killfeed_panel", "missing")])
            self.assertIn("--only roi_cache --cache-roi killfeed_panel", got[0]["command"])
            gate, _ = killfeed_panel_gate(rows, 2.0)
            w = RoiCacheWriter(Path(root), man, profile, "killfeed_panel", hz=2.0, gate=gate)
            w.feed(Sample(frame_idx=0, t_ms=0.0, frame=frame))
            w.finish()
            self.assertEqual(cache_work(store, man), [])
            # A cache written from other media is named with the load's refusal.
            self.assertEqual([c["reason"] for c in cache_work(store, _manifest(key="k2"))],
                             ["stale_content_key"])
