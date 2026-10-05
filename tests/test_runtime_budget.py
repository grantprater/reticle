"""The real-time budget prototype (`prototypes/runtime_budget.py`) on synthetic
usage rows; none is evidence."""
from __future__ import annotations

import unittest

from prototypes import runtime_budget as rb

UPPER = [100_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000,
         50_000_000, 100_000_000]


def feed(count, total_ms, buckets, max_ms, hz, fed=None):
    return {"hz": hz, "spans": None, "fed": count if fed is None else fed,
            "feed": {"count": count, "total_ns": int(total_ms * 1e6),
                     "max_ns": int(max_ms * 1e6), "buckets": buckets},
            "thread_cpu_ns": None, "steps": {}}


def scan(sid, at, readers, until=None, status="completed"):
    return {"kind": "vod_scan", "version": "scan-usage-4", "session_id": sid,
            "recorded_at": at, "status": status, "until_s": until,
            "bucket_upper_ns": UPPER, "pass_ns": 10**9, "cv_threads": {"pass": 1},
            "contention": {"logical_cpus": 12, "other_cpu_ns": 0},
            "source": "cache:x", "readers": readers}


class Quantile(unittest.TestCase):
    def test_closed_bucket_interpolates(self):
        b = [0, 0, 0, 100, 0, 0, 0, 0, 0]          # all calls in [1, 2) ms
        self.assertAlmostEqual(rb.bucket_quantile_ms(b, UPPER, 9_000_000, 0.5), 1.5, places=6)
        # The recorded max closes the bucket early: [1, 1.9) ms.
        self.assertAlmostEqual(rb.bucket_quantile_ms(b, UPPER, 1_900_000, 0.5), 1.45, places=6)

    def test_open_bucket_lower_edge_without_total(self):
        b = [0] * 8 + [10]
        self.assertEqual(rb.bucket_quantile_ms(b, UPPER, 900_000_000, 0.95), 100.0)

    def test_open_bucket_exponential_excess_capped_at_max(self):
        b = [0] * 8 + [10]                         # ten calls averaging 150 ms
        got = rb.bucket_quantile_ms(b, UPPER, 900_000_000, 0.95, total_ns=1.5e9)
        # 100 ms + 50 ms * ln(20)
        self.assertAlmostEqual(got, 100 + 50 * 2.995732, places=3)
        capped = rb.bucket_quantile_ms(b, UPPER, 120_000_000, 0.95, total_ns=1.5e9)
        self.assertLessEqual(capped, 120.0)

    def test_no_calls(self):
        self.assertIsNone(rb.bucket_quantile_ms([0] * 9, UPPER, 0, 0.95))
        self.assertIsNone(rb.open_bucket_share([0] * 9))


class Costs(unittest.TestCase):
    def test_feed_cost_scales_by_rate_and_gate(self):
        f = feed(150, 1500.0, [0, 0, 0, 0, 0, 150, 0, 0, 0], 12.0, hz=15.0)
        f["bucket_upper_ns"] = UPPER
        c = rb.feed_cost(f, duration_s=20.0, live_hz=5.0)
        self.assertAlmostEqual(c["mean_call_ms"], 10.0)
        self.assertAlmostEqual(c["open_share"], 0.5)        # 150 of 300 offered
        self.assertAlmostEqual(c["ms_per_s"], 10.0 * 5.0 * 0.5)

    def test_opening_cost_and_gate(self):
        o = rb.opening_cost(2.0, 0.25, ms_open=40.0, ms_closed=10.0, gate_ms=2.0)
        self.assertAlmostEqual(o["ms_per_s"], 2 * (0.25 * 40 + 0.75 * 10))
        self.assertAlmostEqual(o["gated_ms_per_s"], 2 * (0.25 * 40 + 0.75 * 2))
        self.assertAlmostEqual(o["open_ms_per_s"], 20.0)

    def test_change_only_saving(self):
        # 2 Hz, a quarter non-empty at 100 ms, empty 4 ms: mean call 28 ms.
        ms = 2 * (0.25 * 100 + 0.75 * 4)
        got = rb.change_only_saving(ms, 0.25, 4.0, 2.0, 0.5)
        self.assertAlmostEqual(got, 2 * 0.25 * 0.5 * 100)

    def test_budget_rules(self):
        b = rb.budget(970.0, 1200.0)
        self.assertTrue(b["pace_ok"])
        self.assertFalse(b["in_round_ok"])
        # pace = min(1, 1000 / X): 0.98 holds up to X = 1000 / 0.98, about 1020.
        self.assertTrue(rb.budget(1010.0, 900.0)["pace_ok"])
        self.assertAlmostEqual(rb.budget(1010.0, 900.0)["pace"], 1000 / 1010)
        self.assertFalse(rb.budget(1030.0, 900.0)["pace_ok"])
        self.assertAlmostEqual(b["pace_limit_ms_per_s"], 1000 / 0.98)

    def test_fastest_mean(self):
        b = [0, 0, 0, 0, 10, 10, 0, 0, 0]          # ten in [2, 5) ms, ten in [5, 10)
        self.assertAlmostEqual(rb.fastest_mean_ms(b, UPPER, 10**9, 10), 3.5)
        # The five fastest of [2, 5): spread evenly, mean 2 + 3 * 5 / 20.
        self.assertAlmostEqual(rb.fastest_mean_ms(b, UPPER, 10**9, 5), 2.75)
        self.assertAlmostEqual(rb.fastest_mean_ms(b, UPPER, 10**9, 20), (3.5 + 7.5) / 2)
        self.assertIsNone(rb.fastest_mean_ms(b, UPPER, 10**9, 21))
        self.assertIsNone(rb.fastest_mean_ms(b, UPPER, 10**9, 0))

    def test_killfeed_split_bounds(self):
        # 15 empty calls in [2, 5) ms, 5 non-empty at 100 ms each.
        f = feed(20, 15 * 3.5 + 5 * 100.0, [0, 0, 0, 0, 15, 0, 0, 5, 0], 100.0, hz=2.0)
        f["bucket_upper_ns"] = UPPER
        got = rb.killfeed_split(f, rows=40, empty_rows=30)
        self.assertAlmostEqual(got["empty_ms_lower"], 3.5)
        self.assertAlmostEqual(got["nonempty_ms_upper"], 100.0)
        self.assertAlmostEqual(got["nonempty_share"], 0.25)
        self.assertIsNone(rb.killfeed_split(f, rows=40, empty_rows=0))


class Selection(unittest.TestCase):
    def test_matches_need_length_and_rounds(self):
        got = rb.match_sessions({"a": 1000, "b": 1000, "c": 60}, {"a": 3, "c": 2})
        self.assertEqual(got, ["a"])

    def test_latest_whole_completed_scan_wins(self):
        rows = [scan("a", "2026-01-01", {"hud": feed(10, 10, [0] * 9, 1, 2.0)}),
                scan("a", "2026-01-03", {"hud": feed(10, 99, [0] * 9, 1, 2.0)}, until=30),
                scan("a", "2026-01-04", {"hud": feed(10, 77, [0] * 9, 1, 2.0)},
                     status="failed"),
                scan("a", "2026-01-02", {"hud": feed(10, 20, [0] * 9, 1, 2.0)})]
        got = rb.latest_feeds(rows, ["a"])
        self.assertEqual(got[("a", "hud")]["feed"]["total_ns"], int(20e6))


class EndToEnd(unittest.TestCase):
    def data(self):
        rounds = [{"round_no": i, "t_start_ms": i * 100_000.0,
                   "t_end_ms": i * 100_000.0 + 90_000.0} for i in range(10)]
        hud = feed(2000, 20_000.0, [0, 0, 0, 0, 0, 2000, 0, 0, 0], 12.0, hz=2.0)
        ally = feed(7500, 75_000.0, [0, 0, 0, 0, 0, 7500, 0, 0, 0], 12.0, hz=15.0)
        usage = [scan("m1", "2026-01-01", {"hud": hud, "ally_icon": ally}),
                 {"kind": "command", "command": "deaths", "session_id": "m1",
                  "recorded_at": "2026-01-02", "status": "completed",
                  "wall_ns": 20 * 10**9, "cpu_ns": 10 * 10**9},
                 {"kind": "command", "command": "vision", "session_id": "m1",
                  "recorded_at": "2026-01-02", "status": "completed",
                  "wall_ns": 200 * 10**9, "cpu_ns": 100 * 10**9}]
        live = {"full_bn": {"demand_cores": 1.0, "by_reader": {
            "hud": {"calls": 10, "cpu_ms_per_call": 20.0},
            "ally_icon": {"calls": 10, "cpu_ms_per_call": 5.0},
            "audio": {"calls": 1, "cpu_ms_per_call": 1000.0}}}}
        return {"durations": {"m1": 1000.0, "demo": 60.0},
                "rounds": {"m1": rounds}, "usage": usage, "metrics": [], "live_load": live}

    def test_analyse_charges_calibrated_cpu_and_splits_phases(self):
        old = rb.CALIBRATION_SESSION
        rb.CALIBRATION_SESSION = "m1"
        try:
            a = rb.measure_budget(self.data())
        finally:
            rb.CALIBRATION_SESSION = old
        self.assertEqual(a["matches"], ["m1"])
        hud = a["readers"]["hud"]
        # 10 ms wall per call, 20 ms CPU per call: charged the CPU.
        self.assertAlmostEqual(hud["cpu_over_wall"], 2.0)
        self.assertAlmostEqual(hud["charged_ms_per_s"], 10.0 * 2 * 1.0 * 2.0)
        ally = a["readers"]["ally_icon"]
        # 10 ms wall, CPU below wall: charged the wall; gate 7500 / 15000.
        self.assertAlmostEqual(ally["open_share"]["mean"], 0.5)
        self.assertAlmostEqual(ally["charged_ms_per_s"], 10.0 * 15 * 0.5)
        self.assertAlmostEqual(ally["charged_in_round_ms_per_s"], 10.0 * 15)
        self.assertAlmostEqual(a["live_ms_per_s"], 40.0 + 75.0)
        self.assertAlmostEqual(a["live_in_round_ms_per_s"], 40.0 + 150.0)
        self.assertEqual(a["post"]["deaths"]["phase"], "post_round")
        self.assertEqual(a["post"]["vision"]["phase"], "post_game")
        # deaths: 10 s over 10 rounds, plus the 1 s audio witness.
        self.assertAlmostEqual(a["post_round_cpu_s"], 2.0)
        self.assertAlmostEqual(a["post_game_cpu_s"], 100.0)
        self.assertAlmostEqual(a["round_gap_s"]["median"], 10.0)
        self.assertTrue(a["budget"]["pace_ok"])
        # Uncalibrated: hud at its usage wall, 20 ms/s.
        self.assertAlmostEqual(a["live_uncalibrated_ms_per_s"], 20.0 + 75.0)
        self.assertAlmostEqual(a["live_uncalibrated_in_round_ms_per_s"], 20.0 + 150.0)
        # The harness level timed hud and ally_icon only.
        h = a["harness"]
        self.assertEqual(h["readers"], ["ally_icon", "hud"])
        self.assertAlmostEqual(h["corpus_charged_ms_per_s"], 115.0)
        rows = rb.ledger_values(a, rb.top_changes(a, []))
        self.assertEqual(rows["live"]["matches"], 1)
        self.assertIn("ally_icon_ms_per_s", rows["readers"])


if __name__ == "__main__":
    unittest.main()
