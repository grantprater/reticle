"""The time split and merge of `process_shards`, and the live-round clip of a
decoded ally pass (`roi_cache.clip_live_rounds`, ally-icon-0.13.0)."""
from __future__ import annotations

import unittest

import numpy as np

from reticle.process_shards import SeedMismatch, check_seeds, split_at_gaps
from reticle.roi_cache import clip_live_rounds
from reticle.teardrop import PRIOR_GAP_MS, IconPoseReader, SelfConeReader


def _round(t0: float, n: int, step: float = 66.7) -> list[float]:
    return [t0 + i * step for i in range(n)]


class SplitTests(unittest.TestCase):
    def test_cuts_fall_only_at_gaps(self):
        times = _round(0, 100) + _round(60_000, 100) + _round(120_000, 100)
        runs = split_at_gaps(times, 3, PRIOR_GAP_MS)
        self.assertEqual([len(r) for r in runs], [100, 100, 100])
        self.assertEqual(sum(runs, []), sorted(times))
        for a, b in zip(runs, runs[1:]):
            self.assertGreater(b[0] - a[-1], PRIOR_GAP_MS)

    def test_balances_by_count_among_the_gaps(self):
        # Six rounds of unequal length: three runs near a third each.
        lens = [50, 50, 50, 200, 50, 100]
        times = sum((_round(k * 100_000.0, n) for k, n in enumerate(lens)), [])
        runs = split_at_gaps(times, 3, PRIOR_GAP_MS)
        self.assertEqual(len(runs), 3)
        self.assertEqual(sum(runs, []), sorted(times))
        self.assertEqual([len(r) for r in runs], [150, 200, 150])

    def test_fewer_gaps_give_fewer_runs(self):
        times = _round(0, 40) + _round(10_000, 40)
        self.assertEqual([len(r) for r in split_at_gaps(times, 3, PRIOR_GAP_MS)], [40, 40])
        self.assertEqual(split_at_gaps(_round(0, 30), 3, PRIOR_GAP_MS), [_round(0, 30)])
        self.assertEqual(split_at_gaps([], 3, PRIOR_GAP_MS), [])

    def test_a_short_pause_is_no_cut(self):
        # 150 ms apart: a prior survives it, so the runs may not part there.
        times = _round(0, 20) + _round(19 * 66.7 + 150.0, 20)
        self.assertEqual(len(split_at_gaps(times, 2, PRIOR_GAP_MS)), 1)


def _cand(channel: str, t: float, surprise: str | None) -> dict:
    return {"channel": channel, "t_ms": t,
            "pose": {"origin": "teardrop", "search": "full", "surprise": surprise}}


class SeedTests(unittest.TestCase):
    def test_a_seed_after_reads_is_the_serial_state(self):
        runs = [{"candidates": [_cand("ally", 0, "no_prior"), _cand("self", 0, "no_prior")]},
                {"candidates": [_cand("ally", 9e4, "gap"), _cand("self", 9e4, "gap")]}]
        check_seeds(runs)

    def test_a_seed_with_no_earlier_read_is_refused(self):
        runs = [{"candidates": [_cand("self", 0, "no_prior")]},
                {"candidates": [_cand("ally", 9e4, "gap")]}]
        with self.assertRaises(SeedMismatch):
            check_seeds(runs)

    def test_a_channel_the_run_never_reads_is_no_mismatch(self):
        # A row of a channel no pose read touched (no `search`) carries no seed.
        runs = [{"candidates": [_cand("ally", 0, "no_prior")]},
                {"candidates": [{"channel": "self", "t_ms": 9e4, "pose": {"origin": "ring_fit"}},
                                _cand("ally", 9e4, "gap")]}]
        check_seeds(runs)


class AfterGapTests(unittest.TestCase):
    def test_a_seeded_reader_sees_a_gap_not_no_prior(self):
        fresh, seeded = IconPoseReader("ally", 1.0), IconPoseReader("ally", 1.0)
        seeded.after_gap(1000.0)
        self.assertEqual(fresh._prior(10.0, 10.0, 1000.0 + 2 * PRIOR_GAP_MS), (None, "no_prior"))
        self.assertEqual(seeded._prior(10.0, 10.0, 1000.0 + 2 * PRIOR_GAP_MS), (None, "gap"))

    def test_the_self_reader_seeds_its_prior(self):
        r = SelfConeReader(1.0)
        r.after_gap(500.0)
        self.assertEqual(r._fits._prior(1.0, 1.0, 500.0 + 2 * PRIOR_GAP_MS), (None, "gap"))


class _Reader:
    def __init__(self, name, spans, live=True):
        self.name, self.spans = name, spans
        if live:
            self.live_rounds_only = True


class LiveClipTests(unittest.TestCase):
    ROUNDS = [(10_000.0, 100_000.0), (130_000.0, 220_000.0)]

    def test_a_decode_reads_the_live_rounds_only(self):
        r, other = _Reader("ally_icon", [(0.0, 250_000.0)]), _Reader("minimap",
                                                                     [(0.0, 250_000.0)], False)
        notes = clip_live_rounds([r, other], lambda: (self.ROUNDS, None))
        self.assertEqual(r.spans, self.ROUNDS)
        self.assertEqual(other.spans, [(0.0, 250_000.0)])
        clip = r.spans_clip
        self.assertEqual((clip["frames_from"], clip["cache_set"], clip["reason"]),
                         ("video", None, "outside_live_rounds"))
        self.assertEqual(clip["spans_skipped"], [[0.0, 10_000.0], [100_000.0, 130_000.0],
                                                 [220_000.0, 250_000.0]])
        self.assertIn("clipped to the 2 live rounds", notes[0])

    def test_without_rounds_the_spans_stay_and_say_why(self):
        r = _Reader("ally_icon", [(0.0, 250_000.0)])
        notes = clip_live_rounds([r], lambda: (None, "no stored rounds"))
        self.assertEqual(r.spans, [(0.0, 250_000.0)])
        self.assertFalse(hasattr(r, "spans_clip"))
        self.assertIn("no stored rounds", notes[0])

    def test_a_cache_clip_is_kept(self):
        r = _Reader("ally_icon", [(10_000.0, 50_000.0)])
        r.spans_clip = {"reason": "outside_cache_rounds"}
        self.assertEqual(clip_live_rounds([r], lambda: (self.ROUNDS, None)), [])
        self.assertEqual(r.spans_clip, {"reason": "outside_cache_rounds"})

    def test_the_ally_reader_declares_it(self):
        from reticle.minimap import AllyIconReader
        self.assertTrue(AllyIconReader.live_rounds_only)


class UnreadCauseTests(unittest.TestCase):
    def test_a_live_round_clip_names_its_own_cause(self):
        import pyarrow as pa
        from reticle.team_vision import StoredAllyPoses, _ally_icon_schema
        frames = pa.Table.from_pylist([{"kind": "frame", "frame_idx": 100, "t_ms": 50_000.0,
                                        "widget_drawn": True}], schema=_ally_icon_schema())
        clip = {"reason": "outside_live_rounds", "spans_asked": [[0.0, 250_000.0]],
                "spans_read": [[10_000.0, 100_000.0]],
                "spans_skipped": [[0.0, 10_000.0], [100_000.0, 250_000.0]]}
        poses = StoredAllyPoses(frames, {"spans_clip": clip})
        self.assertEqual(poses.cause(7, 5_000.0), "outside_live_rounds")
        self.assertEqual(poses.cause(7, 50_000.0), "no_frame_in_read_span")


if __name__ == "__main__":
    unittest.main()
