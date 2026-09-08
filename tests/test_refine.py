import unittest
from unittest.mock import patch
import numpy as np

from reticle.refine import merge_windows, iter_windows, read_window


class Cap:
    def __init__(self, ts): self.ts, self.i, self.seeks, self.released = ts, 0, [], False
    def isOpened(self): return True
    def set(self, prop, value): self.seeks.append(value); self.i = max(0, next((i for i,t in enumerate(self.ts) if t >= value), len(self.ts))-1); return True
    def read(self):
        if self.i >= len(self.ts): return False, None
        self.i += 1; return True, np.zeros((1,1,3), dtype=np.uint8)
    def get(self, prop): return (self.ts[self.i-1] if self.i else 0) if prop != 1 else self.i
    def release(self): self.released = True


class RefineTests(unittest.TestCase):
    def test_merge_and_validation(self):
        self.assertEqual(merge_windows([(5, 8), (8, 10), (1, 3)]), [(1., 3.), (5., 10.)])
        for x in [[(-1, 2)], [(1, 1)], [(1, float('nan'))], [(1, float('inf'))]]:
            with self.assertRaises(ValueError): merge_windows(x)

    def test_native_filter_endpoint_and_release(self):
        cap = Cap([0, 5, 10, 15])
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            rows = list(iter_windows('x', [(3, 10)]))
        self.assertEqual([x.t_ms for x in rows], [5.])
        self.assertEqual([x.frame_idx for x in rows], [1])
        self.assertEqual(len(cap.seeks), 1); self.assertTrue(cap.released)

    def test_limit_and_bad_timestamps_release(self):
        cap = Cap([0, 1, 2])
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            with self.assertRaises(ValueError): list(iter_windows('x', [(0, 3)], 1))
        self.assertTrue(cap.released)

        cap = Cap([1, 2, 3, 4])
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            with self.assertRaises(ValueError): list(iter_windows('x', [(0, 2), (3, 5)], 2))
        self.assertTrue(cap.released)
        cap = Cap([1, 1])
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            with self.assertRaises(ValueError): list(iter_windows('x', [(0, 3)]))
        self.assertTrue(cap.released)

    def test_empty_does_not_open_and_read_compat_clamps(self):
        with patch('reticle.refine.cv2.VideoCapture') as vc:
            self.assertEqual(list(iter_windows('x', [])), [])
            vc.assert_not_called()
        cap = Cap([0, 5])
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            w = read_window('x', -4, 6, lambda f: True)
        self.assertEqual(w.t_ms, [0., 5.])

    def test_early_close_and_failed_open_release(self):
        cap = Cap([0, 1, 2])
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            it = iter_windows('x', [(0, 3)])
            next(it); it.close()
        self.assertTrue(cap.released)

    def test_failed_seek_and_probe_error_release(self):
        cap = Cap([0, 1]); cap.set = lambda prop, value: False
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            with self.assertRaisesRegex(ValueError, 'seek'):
                list(iter_windows('x', [(0, 2)]))
        self.assertTrue(cap.released)
        cap = Cap([0, 1])
        def bad_probe(frame):
            raise RuntimeError('probe failure')
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            with self.assertRaisesRegex(RuntimeError, 'probe failure'):
                read_window('x', 0, 2, bad_probe)
        self.assertTrue(cap.released)
        cap = Cap([]); cap.isOpened = lambda: False
        with patch('reticle.refine.cv2.VideoCapture', return_value=cap):
            with self.assertRaises(SystemExit): list(iter_windows('x', [(0, 1)]))
        self.assertTrue(cap.released)


if __name__ == '__main__': unittest.main()
