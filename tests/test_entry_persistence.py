"""The two bars that turn per-frame killfeed bands into adjudicated entries.

Both are stated in SAMPLES as well as milliseconds, and both tests below exist
because the millisecond form alone gave the wrong answer at native rate: a
2500 ms track gap is five samples at 2 Hz and 150 frames at 60, and a
two-observation minimum is one second at 2 Hz and 33 ms at 60.

The shapes here are the ones measured on `c40d950031bb`, scaled down.
"""
import unittest

from reticle.checks import (KF_ENTRY_MIN_LIFE_MS, entry_presence,
                            sample_step_ms, track_entries)


def steps(t0, n, step):
    return [t0 + i * step for i in range(n)]


def feed(times, occupied):
    """One mask column: `occupied` maps a time to the slots holding an entry."""
    return [sum(1 << s for s in occupied.get(t, ())) for t in times]


class SampleStepTests(unittest.TestCase):
    def test_the_step_is_measured_rather_than_declared(self):
        self.assertAlmostEqual(sample_step_ms(steps(0, 20, 500.0)), 500.0)
        self.assertAlmostEqual(sample_step_ms(steps(0, 20, 1000 / 60)), 1000 / 60)

    def test_a_stall_does_not_move_the_step(self):
        t = steps(0, 20, 500.0) + [200_000.0, 200_500.0]
        self.assertAlmostEqual(sample_step_ms(t), 500.0)

    def test_too_few_reads_fall_back_rather_than_divide_by_nothing(self):
        self.assertEqual(sample_step_ms([]), 500.0)
        self.assertEqual(sample_step_ms([0.0, 500.0]), 500.0)


class PersistenceTests(unittest.TestCase):
    """A band that never persists is not an entry, at any rate."""

    def native(self, occupied, seconds=20.0):
        t = steps(0.0, int(seconds * 60), 1000 / 60)
        return t, track_entries(t, feed(t, occupied))

    def test_a_two_frame_band_at_native_rate_is_refused(self):
        # 33 ms of plate colour cleared KF_MIN_OBS on its own, which is how a
        # camera wipe reached the entry count at 60 Hz and not at 2 Hz.
        t = steps(0.0, 600, 1000 / 60)
        occupied = {t[100]: (0,), t[101]: (0,)}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual([a["refused"] for a in tracks], ["no_persistence"])
        self.assertEqual([a["counted"] for a in tracks], [False])

    def test_a_five_second_entry_at_native_rate_is_counted(self):
        t = steps(0.0, 600, 1000 / 60)
        occupied = {ts: (0,) for ts in t if 2000.0 <= ts <= 7000.0}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual([a["counted"] for a in tracks], [True])
        self.assertGreater(tracks[0]["span_ms"], KF_ENTRY_MIN_LIFE_MS)

    def test_the_same_entry_is_counted_at_2_hz_from_two_samples(self):
        # The bar is a LIFE, not a span: `span + 2*step` is the longest life a
        # track is consistent with, so a 2 Hz sampler that caught an entry
        # twice is not refused for resolution it never had.
        t = steps(0.0, 40, 500.0)
        occupied = {2000.0: (0,), 2500.0: (0,)}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual([a["counted"] for a in tracks], [True])

    def test_a_single_frame_is_refused_at_every_rate(self):
        for step in (1000 / 60, 500.0):
            t = steps(0.0, 40, step)
            tracks = track_entries(t, feed(t, {t[10]: (0,)}))
            self.assertEqual([a["refused"] for a in tracks], ["single_frame"])


class TrackGapTests(unittest.TestCase):
    """The gap that ends a track is bounded by samples as well as by time."""

    def test_scattered_wipe_bands_do_not_chain_into_the_entry_that_follows(self):
        # Measured shape: seven singles across a respawn wipe in four different
        # slots, 1.8 s of nothing, then the real entry. With a 2500 ms gap and
        # nothing else, all of it was ONE track running 8.0 s -- long enough to
        # pass any persistence bar, and claiming the entry started during the
        # wipe.
        t = steps(0.0, 600, 1000 / 60)
        wipe = {t[i]: (s,) for i, s in ((10, 4), (17, 3), (40, 5), (75, 1))}
        entry = {ts: (0,) for ts in t if 3000.0 <= ts <= 8000.0}
        tracks = track_entries(t, feed(t, {**wipe, **entry}))
        counted = [a for a in tracks if a["counted"]]
        self.assertEqual(len(counted), 1)
        self.assertGreaterEqual(counted[0]["t_first"], 3000.0)

    def test_2_hz_keeps_the_millisecond_gap_it_was_validated_on(self):
        # Every stored session was read at 2 Hz and scored against the
        # scoreboard K/D there. At that rate the sample bound is 20 s and the
        # 2500 ms cap binds, so the walk is the one those numbers validated.
        t = steps(0.0, 60, 500.0)
        occupied = {ts: (0,) for ts in t if ts <= 2000.0 or 4000.0 <= ts <= 6000.0}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["t_last"], 6000.0)

    def test_a_dropout_inside_one_entry_does_not_split_it(self):
        # A real entry's plate drops out mid-life -- 583 ms of it on
        # c40d950031bb, returning with the same divider column. Splitting there
        # would double-count the kill.
        t = steps(0.0, 900, 1000 / 60)
        occupied = {ts: (0,) for ts in t
                    if 2000.0 <= ts <= 7000.0 and not 4000.0 < ts < 4500.0}
        tracks = track_entries(t, feed(t, occupied))
        self.assertEqual(len(tracks), 1)


class EntryPresenceTests(unittest.TestCase):
    """The count of record: what persisted, not what one frame held."""

    def test_a_wipe_contributes_nothing_and_an_entry_covers_its_whole_life(self):
        t = steps(0.0, 600, 1000 / 60)
        wipe = {t[300]: (0, 1, 2), t[301]: (0, 1, 2)}
        entry = {ts: (0,) for ts in t if 1000.0 <= ts <= 6000.0}
        rows = entry_presence(t, feed(t, {**wipe, **entry}))
        at = {r["t_ms"]: r["entries"] for r in rows}
        self.assertEqual(at[t[300]], 1)      # the entry, and not three more
        self.assertEqual(at[t[10]], 0)
        self.assertEqual(at[3000.0], 1)

    def test_a_frame_the_entry_dropped_out_of_still_carries_it(self):
        t = steps(0.0, 900, 1000 / 60)
        occupied = {ts: (0,) for ts in t
                    if 2000.0 <= ts <= 7000.0 and not 4000.0 < ts < 4500.0}
        rows = entry_presence(t, feed(t, occupied))
        at = {r["t_ms"]: r["entries"] for r in rows}
        self.assertEqual(at[t[0]], 0)
        self.assertTrue(all(v == 1 for ts, v in at.items() if 4000.0 < ts < 4500.0))


if __name__ == "__main__":
    unittest.main()
