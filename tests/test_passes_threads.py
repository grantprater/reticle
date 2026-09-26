import unittest

import cv2

from reticle.passes import _feed


class Reader:
    def __init__(self, cv_threads=None):
        if cv_threads is not None:
            self.cv_threads = cv_threads
        self.seen = []

    def feed(self, smp):
        self.seen.append((smp, cv2.getNumThreads()))


class Failing(Reader):
    def feed(self, smp):
        raise RuntimeError("reader failed")


class ReaderThreadTests(unittest.TestCase):
    def setUp(self):
        self.before = cv2.getNumThreads()
        cv2.setNumThreads(4)

    def tearDown(self):
        cv2.setNumThreads(self.before)

    def test_declared_count_holds_during_feed_and_is_restored(self):
        r = Reader(cv_threads=1)
        _feed(r, "s", None)
        self.assertEqual(r.seen, [("s", 1)])
        self.assertEqual(cv2.getNumThreads(), 4)

    def test_undeclared_reader_keeps_the_process_count(self):
        r = Reader()
        _feed(r, "s", None)
        self.assertEqual(r.seen, [("s", 4)])

    def test_count_is_restored_when_the_reader_raises(self):
        with self.assertRaises(RuntimeError):
            _feed(Failing(cv_threads=1), "s", None)
        self.assertEqual(cv2.getNumThreads(), 4)

    def test_usage_feed_runs_under_the_declared_count(self):
        class Usage:
            def feed(self, reader, smp):
                reader.feed(smp)
        r = Reader(cv_threads=1)
        _feed(r, "s", Usage())
        self.assertEqual(r.seen, [("s", 1)])


if __name__ == "__main__":
    unittest.main()
