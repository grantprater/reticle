"""Tests for in-game time transformation and capture discontinuity detection."""

from __future__ import annotations

import unittest
import pyarrow as pa
import numpy as np

from reticle.gametime import (
    GameTime,
    TimeDiscontinuity,
    SessionGameTime,
    RoundTimeSchedule,
    build_session_gametime,
)
from reticle.store import Store
from reticle.rounds import build_rounds


class GameTimeTests(unittest.TestCase):
    def test_phases_and_elapsed_time(self):
        """Schedule maps buy_phase, round_live, post_plant, and round_end correctly."""
        sched = RoundTimeSchedule(
            round_no=1,
            t_start_ms=10000.0,
            t_end_ms=90000.0,
            t_live_ms=30000.0,
            spike_planted=True,
            plant_t_ms=70000.0,
            post_plant_ms=20000.0,
        )
        sgt = SessionGameTime("s1", [sched], [], [])

        # 1. Buy phase (before barriers drop)
        gt_buy = sgt.game_time_at(15000.0, clock_read_ms=15000)
        self.assertEqual(gt_buy.round_no, 1)
        self.assertEqual(gt_buy.phase, "buy_phase")
        self.assertEqual(gt_buy.round_elapsed_ms, 0.0)
        self.assertFalse(gt_buy.is_stalled)

        # 2. Live pre-plant (active countdown)
        gt_live = sgt.game_time_at(50000.0, clock_read_ms=80000)
        self.assertEqual(gt_live.round_no, 1)
        self.assertEqual(gt_live.phase, "round_live")
        self.assertEqual(gt_live.round_elapsed_ms, 20000.0)
        self.assertEqual(gt_live.clock_ms, 80000)

        # 3. Post-plant: clock is None (spike graphic)
        gt_plant = sgt.game_time_at(75000.0)
        self.assertEqual(gt_plant.round_no, 1)
        self.assertEqual(gt_plant.phase, "post_plant")
        self.assertEqual(gt_plant.round_elapsed_ms, 45000.0)  # 40s live + 5s post-plant
        self.assertIsNone(gt_plant.clock_ms)

        # 4. Round end (post-decision)
        gt_end = sgt.game_time_at(95000.0)
        self.assertEqual(gt_end.round_no, 1)
        self.assertEqual(gt_end.phase, "round_end")

    def test_freeze_and_stall_identification(self):
        """Stalls mark is_stalled=True and record stall_freeze discontinuities."""
        sched = RoundTimeSchedule(
            round_no=1,
            t_start_ms=0.0,
            t_end_ms=60000.0,
            t_live_ms=10000.0,
        )
        stalls = [{"t_start_ms": 20000.0, "t_end_ms": 25000.0, "samples": 10}]
        disc = [TimeDiscontinuity(
            kind="stall_freeze",
            t_media_start=20000.0,
            t_media_end=25000.0,
            media_duration_ms=5000.0,
            game_duration_ms=5000.0,
            drift_ms=0.0,
            round_no=1,
            phase="round_live",
        )]
        sgt = SessionGameTime("s1", [sched], disc, stalls)

        self.assertFalse(sgt.is_stalled_at(15000.0))
        self.assertTrue(sgt.is_stalled_at(22000.0))
        self.assertFalse(sgt.is_stalled_at(26000.0))

        d = sgt.discontinuity_at(22000.0)
        self.assertIsNotNone(d)
        self.assertEqual(d.kind, "stall_freeze")
        self.assertEqual(d.media_duration_ms, 5000.0)

    def test_frame_drop_detection_from_hud(self):
        """Detect clock skipping forward faster than media time."""
        # Simulated HUD where media advances 1s, but clock drops 5s (4s dropped)
        t_ms = [10000.0, 11000.0, 12000.0]
        clock_ms = [90000, 89000, 84000]  # 11s->12s drops from 89s to 84s (5s in 1s)

        hud_table = pa.Table.from_arrays(
            [pa.array(t_ms, type=pa.float64()), pa.array(clock_ms, type=pa.int32())],
            names=["t_ms", "clock_ms"],
        )
        rounds = [{
            "round_no": 1,
            "t_start_ms": 5000.0,
            "t_end_ms": 30000.0,
            "spike_planted": False,
        }]

        sgt = build_session_gametime("test_sess", hud_table, rounds)
        drops = [d for d in sgt.discontinuities if d.kind == "frame_drop"]
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0].media_duration_ms, 1000.0)
        self.assertEqual(drops[0].game_duration_ms, 5000.0)
        self.assertEqual(drops[0].drift_ms, 4000.0)

    def test_session_a06f04a0059f_integration(self):
        """Verify on real session a06f04a0059f including Round 4 and 9.2s stall."""
        store = Store()
        sid = "a06f04a0059f"
        date = "2026-08-26"

        hud = store.read_hud(sid, date)
        rounds = build_rounds(hud)
        from reticle import stalls
        st_list = stalls.for_session(store, sid, date)

        sgt = build_session_gametime(sid, hud, rounds, stall_list=st_list)

        # 1. Round 4 check (t=232000 to 351000)
        # Buy phase: 240000
        gt_r4_buy = sgt.game_time_at(240000.0)
        self.assertEqual(gt_r4_buy.round_no, 4)
        self.assertEqual(gt_r4_buy.phase, "buy_phase")

        # Live pre-plant: 280000
        gt_r4_live = sgt.game_time_at(280000.0)
        self.assertEqual(gt_r4_live.round_no, 4)
        self.assertEqual(gt_r4_live.phase, "round_live")
        self.assertGreater(gt_r4_live.round_elapsed_ms, 0)
        self.assertIsNotNone(gt_r4_live.clock_ms)

        # Post-plant: 330000 (planted at 321000)
        gt_r4_plant = sgt.game_time_at(330000.0)
        self.assertEqual(gt_r4_plant.round_no, 4)
        self.assertEqual(gt_r4_plant.phase, "post_plant")
        self.assertIsNone(gt_r4_plant.clock_ms)

        # 2. Check 9.2s capture stall during Round 7 (t=692600 to 701800)
        gt_stall = sgt.game_time_at(695000.0)
        self.assertTrue(gt_stall.is_stalled)

        disc_stall = sgt.discontinuity_at(695000.0)
        self.assertIsNotNone(disc_stall)
        self.assertIn(disc_stall.kind, ("stall_freeze", "frame_drop"))
        self.assertAlmostEqual(disc_stall.media_duration_ms, 9200.0, delta=100.0)

    def test_round_and_phase_boundary_resets(self):
        """Clock resets at buy phase, active round, and post-plant do not create false discontinuities."""
        # Round 1:
        # t=10s: buy phase (c=2000)
        # t=12s: buy phase (c=0)
        # t=13s: barriers drop (c=99000) -> 99s reset
        # t=20s: spike planted (c=None)   -> post-plant clock disappearance
        # t=25s: post-plant (c=None)
        # t=30s: round 1 ends
        # Round 2:
        # t=35s: round 2 buy phase (c=30000) -> new round reset
        t_ms = [10000.0, 12000.0, 13000.0, 15000.0, 20000.0, 25000.0, 30000.0, 35000.0]
        clock_ms = [2000, 0, 99000, 97000, None, None, 6000, 30000]

        hud_table = pa.Table.from_arrays(
            [pa.array(t_ms, type=pa.float64()), pa.array(clock_ms, type=pa.int32())],
            names=["t_ms", "clock_ms"],
        )
        rounds = [
            {
                "round_no": 1,
                "t_start_ms": 10000.0,
                "t_end_ms": 30000.0,
                "spike_planted": True,
                "plant_t_ms": 20000.0,
                "post_plant_ms": 10000.0,
            },
            {
                "round_no": 2,
                "t_start_ms": 35000.0,
                "t_end_ms": 60000.0,
                "spike_planted": False,
            },
        ]

        sgt = build_session_gametime("test_boundaries", hud_table, rounds)

        # Confirm ZERO false frame drops or clock jumps were generated
        drops_and_jumps = [d for d in sgt.discontinuities if d.kind in ("frame_drop", "clock_jump")]
        self.assertEqual(len(drops_and_jumps), 0)

        # Confirm phase classification across boundaries
        self.assertEqual(sgt.game_time_at(11000.0).phase, "buy_phase")
        self.assertEqual(sgt.game_time_at(14000.0).phase, "round_live")
        self.assertEqual(sgt.game_time_at(22000.0).phase, "post_plant")
        self.assertIsNone(sgt.game_time_at(22000.0).clock_ms)
        self.assertEqual(sgt.game_time_at(32000.0).phase, "round_end")
        self.assertEqual(sgt.game_time_at(36000.0).phase, "buy_phase")
        self.assertEqual(sgt.game_time_at(36000.0).round_no, 2)


if __name__ == "__main__":
    unittest.main()

