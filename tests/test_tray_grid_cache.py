"""The tray crops held only on their readers' 2 Hz grid (`roi_cache.GRID_ROIS`):
the grid is the readers' rule, a writer keeps exactly it, a thinned cache
refuses an off-grid tray read as `thinned_out`, and the checked migration
(`prototypes/tray_thin.py`) refuses a swap on any difference or a busy file."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from reticle.decode import Sample
from reticle.profiles import get_profile
from reticle.roi_cache import (CACHE_SETS, GRID_ROIS, GRID_THIN_VERSION, GridPicker, RoiCache,
                               RoiCacheWriter, ThinnedOut, cache_dir, compare_thinned, grid_keep,
                               grid_thin_rect, roi_rects)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import tray_thin as tt  # noqa: E402

STEP = GRID_ROIS["minimap"]["hud_abilities"]


def _manifest(sid="s1"):
    return {"session_id": sid, "source_profile": "valorant-16x9",
            "source": {"width": 1920, "height": 1080, "content_key": "k1"}}


def _times(n, t0=0.0, fps=60.0, every=4):
    """`n` frame times of a 60 fps capture at about 15 Hz, as a decode gives them."""
    return [t0 + (every * i) * 1000.0 / fps for i in range(n)]


class FakeCache:
    """A cache that records the times a reader asks and yields nothing."""

    def __init__(self, t, spans):
        self.t_ms = np.asarray(t, float)
        self.record = {"spans": spans, "version": "roi-cache-0.1.0"}
        self.asked: list[float] = []

    def samples(self, targets, rois=None):
        assert list(rois) == ["hud_abilities"]
        self.asked += [float(x) for x in targets]
        return iter(())


class GridRuleTest(unittest.TestCase):

    def test_grid_keep_is_what_the_tray_readers_ask(self):
        from reticle.cli import _tray_frames, _tray_samples
        t = _times(200) + _times(150, t0=40000.0)
        spans = [[0.0, 13000.0], [40000.0, 49000.0]]
        fake = FakeCache(t, spans)
        _tray_samples(fake, STEP)
        self.assertEqual(sorted(set(fake.asked)), grid_keep(t, spans, STEP).tolist())
        fake2 = FakeCache(t, spans)
        list(_tray_frames(fake2, STEP))
        self.assertEqual(sorted(set(fake2.asked)), grid_keep(t, spans, STEP).tolist())

    def test_the_picker_equals_grid_keep_on_jittered_spans(self):
        rng = np.random.default_rng(7)
        for _ in range(200):
            t0 = float(rng.uniform(0, 3e6))
            n = int(rng.integers(1, 120))
            t = np.cumsum(rng.uniform(40.0, 90.0, n)) + t0
            t = np.round(t * rng.choice([1, 3]), 3) / rng.choice([1, 3])
            spans = [[float(t[0] - rng.uniform(0, 50)), float(t[n // 2])],
                     [float(t[n // 2] + 1e-3), float(t[-1] + rng.uniform(0, 50))]]
            p = GridPicker(spans, STEP)
            got = []
            for x in np.unique(t):
                got += p.offer(float(x))
            got += p.close()
            self.assertEqual(got, grid_keep(t, spans, STEP).tolist())

    def test_a_grid_point_just_past_the_last_frame_keeps_it(self):
        # arange(0, 999.5 + 1, 500) holds 1000 > 999.5, which grid_times
        # clips to the last frame.
        t, spans = [0.0, 400.0, 999.5], [[0.0, 2000.0]]
        self.assertEqual(grid_keep(t, spans, STEP).tolist(), [0.0, 999.5])
        p = GridPicker(spans, STEP)
        got = [x for v in t for x in p.offer(v)] + p.close()
        self.assertEqual(got, [0.0, 999.5])


def _ffmpeg_or_skip(case):
    from reticle.roi_cache import ffmpeg_path
    try:
        ffmpeg_path()
    except SystemExit:
        case.skipTest("ffmpeg not installed")


def _write(root, n=24, spans=((0.0, 1100.0),), grid=True, seed=5):
    """A minimap cache of `n` random frames at about 15 Hz; `grid` False
    writes every tray frame, as the stored caches were written."""
    profile = get_profile("valorant-16x9")
    rng = np.random.default_rng(seed)
    frames = [rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8) for _ in range(n)]
    with mock.patch.dict("reticle.roi_cache.GRID_ROIS", {}, clear=not grid):
        w = RoiCacheWriter(Path(root), _manifest(), profile, "minimap", hz=15.0,
                           spans=[list(s) for s in spans])
        for i, (t, f) in enumerate(zip(_times(n), frames)):
            w.feed(Sample(frame_idx=4 * i, t_ms=t, frame=f))
        w.finish()
    return profile, frames


class WriterTest(unittest.TestCase):

    def setUp(self):
        _ffmpeg_or_skip(self)

    def test_the_writer_keeps_the_grid_and_refuses_off_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, frames = _write(tmp)
            cache, why = RoiCache.load(Path(tmp), _manifest(), profile, "minimap")
            self.assertIsNone(why)
            t = _times(len(frames))
            grid = grid_keep(t, [[0.0, 1100.0]], STEP).tolist()
            self.assertEqual(grid, [t[0], t[8], t[15]])
            tray = sorted(float(x) for x in cache.t_ms[cache.rect == 1])
            self.assertEqual(tray, grid)
            th = cache.thinned("hud_abilities")
            self.assertEqual((th["version"], th["step_s"], th["frames_kept"]),
                             (GRID_THIN_VERSION, STEP, 3))
            self.assertEqual(cache.holds(), t)
            # The grid reads back the fed pixels, bit for bit.
            x0, y0, x1, y1 = roi_rects("minimap", profile, (1920, 1080))[1]
            for smp in cache.samples(grid, rois=["hud_abilities"]):
                i = t.index(smp.t_ms)
                self.assertTrue(np.array_equal(smp.frame[y0:y1, x0:x1], frames[i][y0:y1, x0:x1]))
            # Off the grid: refused by name, never a neighbour's crop.
            self.assertEqual(cache.refusal(t[3], ["hud_abilities"]), "thinned_out")
            self.assertEqual(cache.refusal(t[3], "minimap"), "thinned_out")
            self.assertIsNone(cache.refusal(t[3], ["minimap"]))
            self.assertIsNone(cache.refusal(t[8], ["hud_abilities"]))
            with self.assertRaises(ThinnedOut) as e:
                list(cache.samples([t[0], t[3]], rois=["hud_abilities"]))
            self.assertEqual((e.exception.reason, e.exception.t_ms), ("thinned_out", t[3]))
            with self.assertRaises(ThinnedOut):
                list(cache.samples([t[3]]))
            # The minimap keeps every frame.
            mx0, my0, mx1, my1 = cache.rect_of("minimap")
            got = list(cache.samples(t, rois=["minimap"]))
            self.assertEqual(len(got), len(t))
            self.assertTrue(np.array_equal(got[5].frame[my0:my1, mx0:mx1],
                                           frames[5][my0:my1, mx0:mx1]))

    def test_a_whole_capture_cache_keeps_every_tray_frame(self):
        profile = get_profile("valorant-16x9")
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(1)
            w = RoiCacheWriter(Path(tmp), _manifest(), profile, "minimap", hz=15.0)
            for i, t in enumerate(_times(6)):
                w.feed(Sample(frame_idx=i, t_ms=t,
                              frame=rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)))
            w.finish()
            cache, _ = RoiCache.load(Path(tmp), _manifest(), profile, "minimap")
            self.assertIsNone(cache.thinned("hud_abilities"))
            self.assertEqual(int((cache.rect == 1).sum()), 6)

    def test_a_pass_reader_declared_on_the_set_asks_the_minimap_alone(self):
        from reticle.passes import _cache_rois
        from reticle.roi_cache import declare_set
        profile = get_profile("valorant-16x9")
        box = roi_rects("minimap", profile, (1920, 1080))[0]
        r = SimpleNamespace(box=box)
        declare_set(r, "minimap", profile, (1920, 1080))
        self.assertEqual(_cache_rois(r), ("minimap",))
        self.assertEqual(_cache_rois(SimpleNamespace(cache_set="hud")), CACHE_SETS["hud"])


class MigrateTest(unittest.TestCase):
    """`grid_thin_rect` on a cache written at every tray frame gives the
    writer's grid, read back bit for bit; the migration swaps only a copy
    whose readers agree, and refuses a busy cache."""

    def setUp(self):
        _ffmpeg_or_skip(self)

    def _stored(self, root):
        profile, frames = _write(root, grid=False)
        return profile, frames, cache_dir(Path(root), "minimap")

    def test_thin_rect_keeps_the_grid_bit_for_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, frames, src = self._stored(tmp)
            dst = Path(tmp) / "out" / "s1"
            got = grid_thin_rect(src, "s1", "hud_abilities", dst, "test")
            self.assertEqual((got["rect"], got["frames_before"], got["frames_kept"]), (1, 24, 3))
            bits = compare_thinned(src, dst, "s1", rect=1)
            self.assertEqual((bits["identical"], bits["different"], bits["extra_frames"],
                              bits["index_ok"]), (3, 0, False, True))
            full, _ = RoiCache.load(Path(tmp), _manifest(), profile, "minimap")
            rec = json.loads((dst / "s1.json").read_text(encoding="utf-8"))
            thin = full.with_index(np.load(dst / "s1.idx.npy"), rec, {1: dst / "s1.r1.mkv"})
            check = tt.load_checks(full, thin)
            self.assertTrue(check["ok"], check)
            self.assertEqual(check["refusal_dropped"], {"thinned_out": 21})
            with self.assertRaises(ValueError):
                grid_thin_rect(src, "s1", "minimap", Path(tmp) / "x", "test")

    def _migrate(self, tmp, readers, stored=True):
        root = Path(tmp)
        if stored:
            self._stored(tmp)
        with mock.patch("reticle.store.Store.read_manifest", lambda self, sid: _manifest(sid)):
            return tt.migrate_session("s1", root / "out", replace=True, store_root=root,
                                      readers=readers)

    def test_a_difference_in_any_stream_refuses_the_swap(self):
        def readers(sid, cache):
            thinned = cache.thinned("hud_abilities") is not None
            return {"rows": {"tray_drop": [{"kind": "drop", "t_ms": 1.0 + thinned}]},
                    "printed": ""}
        with tempfile.TemporaryDirectory() as tmp:
            before = (cache_dir(Path(tmp), "minimap"))
            r = self._migrate(tmp, readers)
            self.assertEqual((r["status"], r["failed"], r["replaced"]), ("failed", "readers", False))
            self.assertEqual(r["readers"]["tray_drop"]["differ"], 1)
            rec = json.loads((before / "s1.json").read_text(encoding="utf-8"))
            self.assertNotIn("thinned_rois", rec)
            self.assertEqual(int((np.load(before / "s1.idx.npy")[:, 2] == 1).sum()), 24)

    def test_identical_readers_swap_the_tray_file_alone(self):
        def readers(sid, cache):
            return {"rows": {"tray_drop": [{"kind": "coverage", "checks": {"wall_s": len(cache.t_ms)
                                                                           * np.random.rand()}}]},
                    "printed": ""}
        with tempfile.TemporaryDirectory() as tmp:
            self._stored(tmp)
            d = cache_dir(Path(tmp), "minimap")
            r0 = (d / "s1.r0.mkv").read_bytes()
            r = self._migrate(tmp, readers, stored=False)
            self.assertEqual(r["status"], "replaced", r)
            self.assertEqual((d / "s1.r0.mkv").read_bytes(), r0)
            self.assertEqual(sorted(p.name for p in d.iterdir()),
                             ["s1.idx.npy", "s1.json", "s1.r0.mkv", "s1.r1.mkv"])
            cache, _ = RoiCache.load(Path(tmp), _manifest(), get_profile("valorant-16x9"),
                                     "minimap")
            self.assertEqual(cache.thinned("hud_abilities")["frames_kept"], 3)

    def test_a_busy_cache_is_refused_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._stored(tmp)
            d = cache_dir(Path(tmp), "minimap")
            (d / "s1.r1.part.mkv").write_bytes(b"")
            r = self._migrate_only(tmp)
            self.assertEqual(r["status"], "busy")
            (d / "s1.r1.part.mkv").unlink()
            if os.name == "nt":
                with open(d / "s1.r1.mkv", "rb"):
                    r = self._migrate_only(tmp)
                self.assertEqual(r["status"], "busy")
                self.assertIn("open in another process", r["why"])

    @unittest.skipUnless(os.name == "nt", "an open file blocks a rename on Windows only")
    def test_a_swap_that_cannot_move_a_file_puts_everything_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src", Path(tmp) / "dst"
            src.mkdir()
            dst.mkdir()
            for n in ("s.json", "s.idx.npy", "s.r1.mkv"):
                (src / n).write_text("old " + n)
                (dst / n).write_text("new " + n)
            with open(src / "s.r1.mkv", "rb"):
                with self.assertRaises(OSError):
                    tt._swap_in("s", src, dst)
            self.assertEqual(sorted(p.name for p in src.iterdir()),
                             ["s.idx.npy", "s.json", "s.r1.mkv"])
            self.assertEqual((src / "s.json").read_text(), "old s.json")
            self.assertEqual(sorted(p.name for p in dst.iterdir()),
                             ["s.idx.npy", "s.json", "s.r1.mkv"])

    def _migrate_only(self, tmp):
        def readers(sid, cache):
            raise AssertionError("a busy cache is never read")
        with mock.patch("reticle.store.Store.read_manifest", lambda self, sid: _manifest(sid)):
            return tt.migrate_session("s1", Path(tmp) / "out", replace=True,
                                      store_root=Path(tmp), readers=readers)

    def test_the_capture_store_reads_back_its_catch_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = tt.CaptureStore(Path(tmp))
            self.assertEqual(st.read_events("tray_kit", "s1"), [])
            st.write_events("tray_kit", "s1", [{"kind": "coverage"}, {"kind": "sample", "x": 1},
                                                {"kind": "span"}])
            self.assertEqual(st.read_events_kind("tray_kit", "s1", "sample"),
                             [{"kind": "coverage"}, {"kind": "sample", "x": 1}])
            with self.assertRaises(RuntimeError):
                st.write_rounds([], "s1", "2026-10-05")
            self.assertFalse(any(Path(tmp).rglob("*.jsonl")))

    def test_compare_stream_rows_ignores_timing_only(self):
        a = [{"kind": "coverage", "checks": {"wall_s": 1.0, "cache_read_s": 2.0, "step_s": 0.5}}]
        b = [{"kind": "coverage", "checks": {"wall_s": 9.0, "cache_read_s": 3.0, "step_s": 0.5}}]
        self.assertEqual(tt.compare_stream_rows(a, b)["differ"], 0)
        c = [{"kind": "coverage", "checks": {"wall_s": 9.0, "step_s": 1.0}}]
        self.assertEqual(tt.compare_stream_rows(a, c)["differ"], 1)
        self.assertEqual(tt.compare_stream_rows(a, a + a)["differ"], 1)


if __name__ == "__main__":
    unittest.main()
