from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np

from reticle import dev_sample as ds
from reticle.metrics import rule_of_three, wilson


def _rounds(n, t_round=100_000.0):
    rows = []
    for i in range(1, n + 1):
        rows.append({"round_no": i, "t_start_ms": (i - 1) * t_round,
                     "t_end_ms": i * t_round - 8000.0, "t_close_ms": i * t_round,
                     "start_source": "capture_start" if i == 1 else "clock_reset",
                     "map": "split", "player_kills": i % 3, "won": bool(i % 2)})
    return rows


class SampleTest(unittest.TestCase):

    def test_frozen_sample_is_versioned_and_stratified(self):
        self.assertEqual(ds.DEV_SAMPLE_VERSION, "dev-sample-0.1.0")
        per = Counter(w.session for w in ds.SAMPLE)
        self.assertEqual(set(per), set(ds.MATCHES))
        self.assertEqual(set(per.values()), {ds.PER_MATCH})
        self.assertIn("4f207c0c4e39", per)      # the 1.15x variant widget
        for w in ds.SAMPLE:
            self.assertTrue(w.reason.startswith(ds.DEV_SAMPLE_VERSION), w)
            self.assertLess(w.t0, w.t1)
            for sid, a, b, _ in ds.HELD_OUT_WINDOWS:
                self.assertFalse(w.session == sid and w.t0 <= b and a <= w.t1, w)

    def test_build_is_deterministic_and_seeded(self):
        rounds = {"s1": _rounds(24), "s2": _rounds(10)}
        a, b = ds.build(rounds), ds.build(rounds)
        self.assertEqual(a, b)
        self.assertNotEqual(ds.build(rounds, seed="another"), a)

    def test_build_one_round_per_half_and_never_the_lobby(self):
        out = ds.build({"s1": _rounds(24), "s2": _rounds(10)})
        s1 = [w for w in out if w.session == "s1"]
        self.assertEqual(sorted(w.reason.split()[3] for w in s1), ["first_half", "second_half"])
        s2 = [w for w in out if w.session == "s2"]
        self.assertEqual([w.reason.split()[3] for w in s2], ["first_half", "first_half"])
        self.assertTrue(all(w.t0 > 0 for w in out))    # round 1 starts at the capture

    def test_build_ignores_outcomes(self):
        rounds = _rounds(24)
        flipped = [dict(r, player_kills=9 - r["player_kills"], won=not r["won"]) for r in rounds]
        self.assertEqual(ds.build({"s": rounds}), ds.build({"s": flipped}))

    def test_build_drops_held_out_windows(self):
        rounds = _rounds(24)
        held = (("s", 150.0, 160.0, "test"),)
        kept = ds.opportunity_rounds([dict(r, session_id="s") for r in rounds], held)
        self.assertNotIn(2, [r["round_no"] for r in kept])
        self.assertIn(3, [r["round_no"] for r in kept])

    def test_drift_names_moved_windows(self):
        w = ds.Window("s", 10.0, 20.0, "r")
        self.assertEqual(ds.drift([w], [w]), [])
        self.assertEqual(len(ds.drift([w], [w._replace(t1=25.0)])), 1)
        self.assertEqual(len(ds.drift([w], [])), 1)


class WindowsFileTest(unittest.TestCase):

    def test_round_trip_keeps_a_reason_with_commas(self):
        wins = [ds.Window("abc", 1.5, 9.25, "thread 5, art_y0"), ds.Window("def", 0.0, 2.0, "")]
        self.assertEqual(ds.parse_windows(ds.format_windows(wins)), wins)
        with tempfile.TemporaryDirectory() as d:
            p = ds.write_windows(Path(d) / "w.csv", wins)
            self.assertEqual(ds.read_windows(p), wins)
            self.assertEqual(ds.load([p], sample=True), wins + list(ds.SAMPLE))

    def test_comments_and_blank_lines_skipped(self):
        text = "# targeted\nsession,t0,t1,reason\n\nabc,1,2,x\n# end\n"
        self.assertEqual(ds.parse_windows(text), [ds.Window("abc", 1.0, 2.0, "x")])

    def test_bad_files_refused(self):
        for text in ("sid,a,b\nabc,1,2\n", "session,t0,t1,reason\nabc,1\n",
                     "session,t0,t1,reason\nabc,x,2\n", "session,t0,t1,reason\nabc,3,2\n",
                     "session,t0,t1,reason\n,1,2\n", "session,t0,t1,reason\nabc,nan,2\n"):
            with self.assertRaises(ValueError, msg=text):
                ds.parse_windows(text)

    def test_spans_merge_and_inclusive_mask(self):
        wins = [ds.Window("a", 1.0, 2.0, ""), ds.Window("a", 2.0, 3.0, ""),
                ds.Window("a", 10.0, 11.0, ""), ds.Window("b", 0.0, 1.0, "")]
        sp = ds.spans_ms(wins)
        self.assertEqual(sp["a"], [(1000.0, 3000.0), (10000.0, 11000.0)])
        m = ds.in_spans([999.0, 1000.0, 3000.0, 3000.5, 10500.0, 12000.0], sp["a"])
        self.assertEqual(m.tolist(), [False, True, True, False, True, False])
        self.assertEqual(ds.in_spans(np.array([1.0]), []).tolist(), [False])


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def read_events(self, stream, sid):
        return self.rows.get((stream, sid), [])


class TargetsTest(unittest.TestCase):

    def test_residual_windows_join_overlaps(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            p.write_text("session,t,reason\na,100,missed\na,110,killer_wrong\nb,5,false_death\n",
                         encoding="utf-8")
            res = ds.read_residuals(p)
        out = ds.targets_from_residuals(res, pad_s=15.0)
        self.assertEqual(out, [ds.Window("a", 85.0, 125.0, "missed; killer_wrong"),
                               ds.Window("b", 0.0, 20.0, "false_death")])

    def test_residual_header_required(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            p.write_text("sid,time\na,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                ds.read_residuals(p)

    def test_stream_targets_where_the_code_path_fires(self):
        rows = {("killfeed_portrait", "s"): [
            {"t_ms": 10_000, "kind": "entry", "evidence": {"band": "overlaid"}},
            {"t_ms": 50_000, "kind": "entry", "evidence": {"band": "clean"}},
            {"t_ms": 90_000, "kind": "entry", "refused": True},
            {"kind": "summary"}]}
        st = _Store(rows)
        out = ds.targets_from_stream(st, ["s"], "killfeed_portrait",
                                     ds.parse_where(["evidence.band=overlaid"]), pad_s=5.0)
        self.assertEqual([(w.t0, w.t1) for w in out], [(5.0, 15.0)])
        out = ds.targets_from_stream(st, ["s"], "killfeed_portrait", ds.parse_where(["refused"]),
                                     pad_s=5.0)
        self.assertEqual([(w.t0, w.t1) for w in out], [(85.0, 95.0)])
        self.assertEqual(ds.parse_where(["a=1", "b=x", "c"]), {"a": 1, "b": "x", "c": True})


class IntervalTest(unittest.TestCase):

    def test_rule_of_three(self):
        self.assertIsNone(rule_of_three(0))
        self.assertAlmostEqual(rule_of_three(300), 0.01)
        self.assertEqual(rule_of_three(2), 1.0)
        for n in (5, 30, 300, 3000):    # never tighter than the exact bound
            self.assertGreaterEqual(rule_of_three(n), 1 - 0.05 ** (1 / n))

    def test_wilson_known_value(self):
        lo, hi = wilson(0, 100)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.0370, places=4)
        lo, hi = wilson(50, 100)
        self.assertAlmostEqual(lo, 0.4038, places=4)
        self.assertAlmostEqual(hi, 0.5962, places=4)


if __name__ == "__main__":
    unittest.main()
