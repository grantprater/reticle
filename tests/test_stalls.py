import unittest

from reticle.stalls import StallConfig, spans, stalled_at, total_ms


def series(pairs):
    """(t_ms, motion) pairs -> the two arrays `spans` takes."""
    return [p[0] for p in pairs], [p[1] for p in pairs]


class StallSpanTests(unittest.TestCase):
    def test_a_zero_motion_run_is_a_stall(self):
        t, m = series([(i * 200.0, 0.0 if 1000 <= i * 200 <= 3000 else 0.08)
                       for i in range(30)])
        got = spans(t, m)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["t_start_ms"], got[0]["t_end_ms"]), (1000.0, 3000.0))

    def test_a_keyframe_refresh_does_not_split_one_stall(self):
        # Zero-motion runs arrive in ~3.6 s pieces separated by ONE non-zero
        # sample -- the encoder refreshing a frozen picture. That is one stall.
        rows = []
        for i in range(60):
            t = i * 200.0
            live = (t % 3600 == 0)          # a single refreshed sample
            rows.append((t, 0.05 if live else 0.0))
        got = spans(*series(rows))
        self.assertEqual(len(got), 1)
        self.assertGreater(got[0]["t_end_ms"] - got[0]["t_start_ms"], 10000)

    def test_an_isolated_zero_sample_is_not_a_stall(self):
        t, m = series([(i * 200.0, 0.0 if i == 7 else 0.08) for i in range(30)])
        self.assertEqual(spans(t, m), [])

    def test_a_gap_longer_than_the_merge_window_is_two_stalls(self):
        rows = [(i * 200.0, 0.0) for i in range(10)]                  # 0-1800
        rows += [(2000.0 + i * 200.0, 0.09) for i in range(10)]       # live 2s
        rows += [(4000.0 + i * 200.0, 0.0) for i in range(10)]        # 4000-5800
        self.assertEqual(len(spans(*series(rows))), 2)

    def test_lookup_is_closed_on_both_ends_and_unknown_is_not_stalled(self):
        got = [{"t_start_ms": 100.0, "t_end_ms": 400.0, "samples": 4}]
        self.assertTrue(stalled_at(got, 100.0))
        self.assertTrue(stalled_at(got, 400.0))
        self.assertFalse(stalled_at(got, 99.0))
        self.assertFalse(stalled_at(got, 401.0))
        # None is UNKNOWN, and a caller must not read it as "no stalls".
        self.assertFalse(stalled_at(None, 200.0))
        self.assertEqual(total_ms(None), 0.0)

    def test_config_is_honoured_and_empty_input_is_empty(self):
        t, m = series([(i * 200.0, 0.0) for i in range(4)])           # 600 ms
        self.assertEqual(spans(t, m), [])                              # under 1 s
        self.assertEqual(len(spans(t, m, StallConfig(min_stall_ms=500.0))), 1)
        self.assertEqual(spans([], []), [])


if __name__ == "__main__":
    unittest.main()
