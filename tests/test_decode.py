import unittest
from unittest.mock import patch

import numpy as np

from reticle.decode import sample_frames, sample_multi, sample_spans
from reticle.passes import run


class Cap:
    def __init__(self, frames=4):
        self.frames, self.i, self.released = frames, -1, False

    def isOpened(self): return True
    def grab(self):
        self.i += 1
        return self.i < self.frames
    def get(self, prop): return self.i * 500.0
    def retrieve(self): return True, np.zeros((1, 1, 3), dtype=np.uint8)
    def release(self): self.released = True


class DecodeContractTests(unittest.TestCase):
    def test_empty_spans_mean_no_work_and_do_not_open_media(self):
        with patch("reticle.decode.cv2.VideoCapture") as video:
            self.assertEqual(list(sample_spans("x", [], 2.0, 60.0)), [])
            self.assertEqual(list(sample_multi("x", 60.0, {"empty": (2.0, [])})), [])
        video.assert_not_called()

    def test_empty_reader_does_not_receive_unrestricted_reader_frames(self):
        cap = Cap()
        with patch("reticle.decode.cv2.VideoCapture", return_value=cap):
            rows = list(sample_multi(
                "x", 2.0, {"empty": (2.0, []), "whole": (2.0, None)}))
        self.assertTrue(rows)
        self.assertTrue(all(who == frozenset({"whole"}) for who, _ in rows))

    def test_invalid_rates_and_spans_refuse_before_opening_media(self):
        invalid = [0, -1, float("nan"), float("inf"), True, "2"]
        with patch("reticle.decode.cv2.VideoCapture") as video:
            for rate in invalid:
                with self.subTest(rate=rate), self.assertRaises(ValueError):
                    list(sample_frames("x", rate, 60.0))
            for spans in [[(-1, 2)], [(2, 1)], [(0, float("nan"))], [(0,)]]:
                with self.subTest(spans=spans), self.assertRaises(ValueError):
                    list(sample_multi("x", 60.0, {"reader": (2.0, spans)}))
        video.assert_not_called()

    def test_duplicate_reader_names_refuse_instead_of_dropping_a_reader(self):
        class Reader:
            name, hz, spans = "same", 2.0, []
            def feed(self, sample): pass

        class Context: pass
        with self.assertRaisesRegex(ValueError, "unique"):
            run(Context(), [Reader(), Reader()])


if __name__ == "__main__":
    unittest.main()
