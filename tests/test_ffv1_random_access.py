"""`RoiCache.samples` reads an FFV1 cache at any times, bit for bit.

A cache written before `FFV1_WRITER_VERSION` 0.2.0 has a key frame every 12
frames and no `encoding` in its record (`roi_cache`, "An FFV1 frame is not a
seek point"); `_Ffv1Video` seeks to the cued key frame and decodes forward.
A cache written now has a key frame on every frame (`FFV1_GOP` 1), and a
sparse read seeks straight to its frame. Every read must equal the pixels
fed to the writer and OpenCV's sequential decode of the same file, the
reader `samples` used before. `_Ffv1Rect` chooses OpenCV or PyAV per read by
the gap; both must yield the same bytes.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from reticle.roi_cache import (FFV1_WRITER_VERSION, RoiCache, _Ffv1Rect, _Ffv1Video,
                                ffmpeg_path, roi_rects)

sys.path.insert(0, str(Path(__file__).parent))
from test_tray_grid_cache import _ffmpeg_or_skip, _manifest, _times, _write  # noqa: E402

N = 60


def _drop_encoding(root: Path) -> None:
    """Strip `encoding` from the cache record, as a cache written before
    `FFV1_WRITER_VERSION` 0.2.0 stores it."""
    meta = next((root / "roi_cache" / "minimap").rglob("*.json"))
    rec = json.loads(meta.read_text(encoding="utf-8"))
    rec.pop("encoding")
    meta.write_text(json.dumps(rec), encoding="utf-8")


def _key_flags(path: Path) -> list[str]:
    """ffprobe's key-frame flag of every frame of a video."""
    probe = str(Path(ffmpeg_path()).with_name(Path(ffmpeg_path()).name.replace("ffmpeg", "ffprobe")))
    out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "frame=key_frame", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


class Ffv1RandomAccessTest(unittest.TestCase):
    """A cache written at ffmpeg's default group of 12, its record silent on
    the encoding: today's behaviour, unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        try:
            from reticle.roi_cache import ffmpeg_path
            ffmpeg_path()
        except SystemExit:
            cls.profile = None
            return
        with patch("reticle.roi_cache.FFV1_GOP", 12):
            cls.profile, cls.frames = _write(cls.tmp.name, n=N, spans=((0.0, 4000.0),))
        _drop_encoding(Path(cls.tmp.name))
        cls.cache, why = RoiCache.load(Path(cls.tmp.name), _manifest(), cls.profile, "minimap")
        assert why is None, why
        cls.video = Path(cls.tmp.name) / "roi_cache" / "minimap"
        cls.t = _times(N)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        _ffmpeg_or_skip(self)

    def _r0(self) -> Path:
        return next(self.video.rglob("*.r0.mkv"))

    def _opencv_frames(self) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(self._r0()))
        out = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            out.append(f)
        cap.release()
        return out

    def test_the_video_cues_a_key_frame_every_twelve_frames(self):
        v = _Ffv1Video(self._r0())
        try:
            self.assertEqual(v.keys.tolist(), list(range(0, N, 12)))
        finally:
            v.close()

    def test_an_old_record_states_no_group_and_reads_unkeyed(self):
        self.assertNotIn("encoding", self.cache.record)
        v = _Ffv1Rect(self._r0())
        try:
            v.read(40)                      # opens PyAV; the cues list every 12th frame
            self.assertFalse(v.keyed)
        finally:
            v.close()

    def test_any_order_of_reads_equals_the_fed_pixels_and_opencv(self):
        ref = self._opencv_frames()
        self.assertEqual(len(ref), N)
        x0, y0, x1, y1 = roi_rects("minimap", self.profile, (1920, 1080))[0]
        rng = np.random.default_rng(7)
        orders = {
            "grid": list(range(N)),
            "gated": [0, 2, 3, 14, 16, 30, 33, 35, 47, 48, 50, 59],
            "random": rng.integers(0, N, 80).tolist(),        # backward jumps too
        }
        for name, idx in orders.items():
            times = [self.t[i] for i in idx]
            got = list(self.cache.samples(times, rois=["minimap"]))
            self.assertEqual(len(got), len(idx), name)
            for i, smp in zip(idx, got):
                crop = smp.frame[y0:y1, x0:x1]
                self.assertTrue(np.array_equal(crop, self.frames[i][y0:y1, x0:x1]), (name, i))
                self.assertTrue(np.array_equal(crop, ref[i]), (name, i))

    def test_the_gap_chooses_the_decoder_and_both_yield_the_same_bytes(self):
        ref = self._opencv_frames()
        orders = {
            "dense": (list(range(N)), {"cv": N, "av": 0}),
            "seek then dense": ([30] + list(range(31, 40)), {"cv": 7, "av": 3}),
            "dense, seek, dense": ([0, 3, 6, 40, 42, 44, 5, 7], {"cv": 3, "av": 5}),
            # a run PyAV began hands over to OpenCV after DENSE_HANDOVER (3) dense reads
            "handover": ([20, 21, 22, 23, 24, 25, 50, 10], {"cv": 3, "av": 5}),
        }
        with patch("reticle.roi_cache.DENSE_HANDOVER", 3):
            for name, (idx, served) in orders.items():
                v = _Ffv1Rect(self._r0())
                try:
                    for i in idx:
                        self.assertTrue(np.array_equal(v.read(i), ref[i]), (name, i))
                    self.assertEqual(v.served, served, name)
                finally:
                    v.close()

    def test_a_read_decodes_from_the_nearer_of_its_position_and_the_key(self):
        v = _Ffv1Video(self._r0())
        try:
            v.read(2)                       # from the start: no seek
            self.assertEqual((v.seeks, v.decoded), (0, 3))
            v.read(30)                      # key 24 lies past position 3: seek
            self.assertEqual((v.seeks, v.decoded), (1, 3 + 7))
            v.read(33)                      # position 31 is past key 24: forward
            self.assertEqual((v.seeks, v.decoded), (1, 3 + 7 + 3))
            v.read(5)                       # backward: seek to key 0
            self.assertEqual((v.seeks, v.decoded), (2, 3 + 7 + 3 + 6))
        finally:
            v.close()

    def test_a_frame_past_the_end_raises(self):
        v = _Ffv1Video(self._r0())
        try:
            with self.assertRaises(ValueError):
                v.read(N + 5)
        finally:
            v.close()


class Ffv1KeyedTest(unittest.TestCase):
    """A cache written now: every frame a key frame, stated in its record."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        try:
            ffmpeg_path()
        except SystemExit:
            return
        cls.profile, cls.frames = _write(cls.tmp.name, n=N, spans=((0.0, 4000.0),), grid=False)
        cls.cache, why = RoiCache.load(Path(cls.tmp.name), _manifest(), cls.profile, "minimap")
        assert why is None, why
        cls.r0 = next((Path(cls.tmp.name) / "roi_cache" / "minimap").rglob("*.r0.mkv"))
        cls.t = _times(N)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        _ffmpeg_or_skip(self)

    def test_the_record_states_the_writer_and_a_group_of_one(self):
        self.assertEqual(self.cache.record["encoding"],
                         [{"version": FFV1_WRITER_VERSION, "gop": 1}] * 2)
        self.assertEqual(self.cache.record["version"], "roi-cache-0.1.0")

    def test_ffprobe_and_the_cues_list_every_frame_as_a_key_frame(self):
        self.assertEqual(_key_flags(self.r0), ["1"] * N)
        v = _Ffv1Video(self.r0)
        try:
            self.assertEqual(v.keys.tolist(), list(range(N)))
        finally:
            v.close()

    def test_any_order_of_reads_equals_the_fed_pixels(self):
        x0, y0, x1, y1 = roi_rects("minimap", self.profile, (1920, 1080))[0]
        rng = np.random.default_rng(11)
        orders = {"grid": list(range(N)), "gated": [0, 2, 3, 14, 16, 30, 33, 35, 47, 48, 50, 59],
                  "random": rng.integers(0, N, 80).tolist()}
        for name, idx in orders.items():
            got = list(self.cache.samples([self.t[i] for i in idx], rois=["minimap"]))
            self.assertEqual(len(got), len(idx), name)
            for i, smp in zip(idx, got):
                self.assertTrue(np.array_equal(smp.frame[y0:y1, x0:x1],
                                               self.frames[i][y0:y1, x0:x1]), (name, i))

    def test_a_sparse_read_seeks_straight_to_its_frame(self):
        v = _Ffv1Rect(self.r0, gop=1)
        try:
            self.assertTrue(v.keyed)
            for i in [0, 2, 3, 14, 16, 30, 33]:
                v.read(i)
            av = v._av
            # 0 and 3 are the next frame on the decoder that stands there
            # (OpenCV, then PyAV); each skip seeks and decodes its frame alone.
            self.assertEqual(v.served, {"cv": 1, "av": 6})
            self.assertEqual((av.seeks, av.decoded), (5, 6))
        finally:
            v.close()

    def test_dense_reads_keep_the_opencv_path(self):
        v = _Ffv1Rect(self.r0, gop=1)
        try:
            for i in range(N):
                v.read(i)
            self.assertEqual(v.served, {"cv": N, "av": 0})
        finally:
            v.close()

    def test_a_record_silent_on_the_group_reads_it_from_the_cues(self):
        v = _Ffv1Rect(self.r0)
        try:
            self.assertFalse(v.keyed)
            v.read(30)                      # a long gap opens PyAV, whose cues list every frame
            self.assertTrue(v.keyed)
        finally:
            v.close()


if __name__ == "__main__":
    unittest.main()
