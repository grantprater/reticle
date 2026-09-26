import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reticle import decode


class OpenCaptureTests(unittest.TestCase):
    def test_cpu_mode_never_tries_nvdec(self):
        with patch.dict(os.environ, {"RETICLE_DECODE": "cpu"}), \
                patch("reticle.decode._NvdecCapture", side_effect=AssertionError), \
                patch("reticle.decode.cv2.VideoCapture", return_value="cv2") as video:
            self.assertEqual(decode.open_capture("x.mp4"), "cv2")
        video.assert_called_once_with("x.mp4")

    def test_auto_mode_falls_back_to_opencv(self):
        with patch.dict(os.environ, {"RETICLE_DECODE": "auto"}), \
                patch("reticle.decode._NvdecCapture", side_effect=RuntimeError("no device")), \
                patch("reticle.decode.cv2.VideoCapture", return_value="cv2"):
            self.assertEqual(decode.open_capture("x.mp4"), "cv2")

    def test_nvdec_mode_refuses_to_fall_back(self):
        with patch.dict(os.environ, {"RETICLE_DECODE": "nvdec"}), \
                patch("reticle.decode._NvdecCapture", side_effect=RuntimeError("no device")), \
                patch("reticle.decode.cv2.VideoCapture") as video:
            with self.assertRaises(RuntimeError):
                decode.open_capture("x.mp4")
        video.assert_not_called()

    def test_unknown_mode_refuses(self):
        with patch.dict(os.environ, {"RETICLE_DECODE": "gpu"}):
            with self.assertRaises(ValueError):
                decode.open_capture("x.mp4")


def _clip(directory: str) -> str | None:
    """A short H.264 yuv420p limited-range clip, or None without ffmpeg."""
    try:
        from reticle.roi_cache import ffmpeg_path
        ffmpeg = ffmpeg_path()
    except SystemExit:
        return None
    out = str(Path(directory) / "clip.mp4")
    done = subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=320x240:rate=60:duration=2", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709", "-bf", "2", out],
        capture_output=True)
    return out if done.returncode == 0 else None


class NvdecExactnessTests(unittest.TestCase):
    """Frames, indices and timestamps match OpenCV's, where NVDEC exists."""

    def test_sample_multi_is_byte_identical_to_opencv(self):
        with tempfile.TemporaryDirectory() as d:
            clip = _clip(d)
            if clip is None:
                self.skipTest("ffmpeg with libx264 unavailable")
            try:
                decode._NvdecCapture(clip).release()
            except Exception as exc:  # no CUDA device or PyAV without CUDA
                self.skipTest(f"NVDEC unavailable: {exc}")
            req = {"a": (7.0, None), "b": (30.0, [(300.0, 900.0)])}
            runs = {}
            for mode in ("cpu", "nvdec"):
                with patch.dict(os.environ, {"RETICLE_DECODE": mode}):
                    runs[mode] = [(who, s.frame_idx, s.t_ms, s.frame.tobytes())
                                  for who, s in decode.sample_multi(clip, 60.0, req)]
            self.assertGreater(len(runs["cpu"]), 20)
            self.assertEqual(runs["cpu"], runs["nvdec"])

    def test_release_mid_stream_stops_the_decoder(self):
        with tempfile.TemporaryDirectory() as d:
            clip = _clip(d)
            if clip is None:
                self.skipTest("ffmpeg with libx264 unavailable")
            try:
                cap = decode._NvdecCapture(clip)
            except Exception as exc:
                self.skipTest(f"NVDEC unavailable: {exc}")
            self.assertTrue(cap.grab())
            ok, frame = cap.retrieve()
            self.assertTrue(ok)
            self.assertEqual(frame.shape, (240, 320, 3))
            self.assertTrue(frame.flags.writeable)
            cap.release()
            self.assertIsNone(cap._thread)


if __name__ == "__main__":
    unittest.main()
