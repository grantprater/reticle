"""The frame-time kit's pure rules on synthetic data: the PresentMon reader
and decision table (`prototypes/frametime_results.py`) and the live-load
harness's schedule (`prototypes/live_load.py`)."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import frametime_results as fr  # noqa: E402
import live_load as ll  # noqa: E402


def _csv(path: Path, ms: list[float], col: str = "MsBetweenPresents",
         extra_app: bool = True, extra_chain: bool = False) -> None:
    rows = [f"Application,ProcessID,SwapChainAddress,{col}"]
    rows += [f"{fr.GAME},1,0xA,{m}" for m in ms]
    if extra_app:
        rows += ["obs64.exe,2,0xB,1.0"] * 50
    if extra_chain:
        rows += [f"{fr.GAME},1,0xC,99.0"] * 3
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class ReaderTest(unittest.TestCase):
    def test_keeps_the_games_main_swapchain_and_reads_either_column(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "01_base.csv"
            _csv(p, [5.0] * 100, extra_chain=True)
            ft, col, note = fr.frame_times(p)
            self.assertEqual((len(ft), col), (100, "MsBetweenPresents"))
            self.assertEqual((note["other_apps"], note["other_swapchains"]), (50, 3))
            _csv(p, [4.0] * 10, col="FrameTime")
            ft, col, _ = fr.frame_times(p)
            self.assertEqual((len(ft), col), (10, "FrameTime"))

    def test_summary_fixes_the_definitions(self):
        ft = np.r_[np.full(990, 5.0), np.full(10, 20.0)]
        s = fr.summary(ft)
        self.assertEqual(s["fps_median"], 200.0)
        self.assertEqual(s["p99_ms"], 5.0 + 0.01 * 15.0 * 1)      # numpy's linear p99
        self.assertAlmostEqual(s["fps_low1"], 1000.0 / s["p99_ms"], places=1)


class DecideTest(unittest.TestCase):
    def _arms(self, d: Path, fps: dict, pace=None):
        k = 1
        for arm, values in fps.items():
            for v in values:
                p = d / f"{k:02d}_{arm}.csv"
                _csv(p, list(np.full(500, 1000.0 / v)))
                if arm in fr.LEVELS:
                    log = {"pace": (pace or {}).get(arm, 1.0), "lag_s": {"p95": 0.05}}
                    p.with_name(p.stem + ".load.json").write_text(json.dumps(log))
                k += 1
        return fr.collect_arms(d)

    def test_highest_level_within_budget_is_chosen(self):
        with tempfile.TemporaryDirectory() as d:
            arms = self._arms(Path(d), {"base": [200, 198], "obs": [180, 180],
                                        "light": [175, 175], "medium": [165, 165],
                                        "full": [150, 150]})
            dec = fr.decide(arms)
            self.assertTrue(dec["rows"]["light"]["passes"])
            self.assertTrue(dec["rows"]["medium"]["passes"])        # 1 - 165/199 = 17%
            self.assertFalse(dec["rows"]["full"]["passes"])         # 25%
            self.assertEqual(dec["chosen"], "medium")
            self.assertIn("medium", dec["verdict"])

    def test_a_harness_that_fell_behind_fails_and_drift_undecides(self):
        with tempfile.TemporaryDirectory() as d:
            arms = self._arms(Path(d), {"base": [200, 200], "light": [190, 190]},
                              pace={"light": 0.5})
            dec = fr.decide(arms)
            self.assertFalse(dec["rows"]["light"]["passes"])
            self.assertIn("fell behind", dec["rows"]["light"]["why"])
        with tempfile.TemporaryDirectory() as d:
            arms = self._arms(Path(d), {"base": [200, 180], "light": [190, 190]})
            self.assertTrue(fr.decide(arms)["verdict"].startswith("undecided"))


class ProtocolFolderTest(unittest.TestCase):
    """The folder docs/FRAMETIME_PROTOCOL.md has the player leave, file for file."""

    ORDER = ("base", "obs", "light", "medium", "full",
             "full", "medium", "light", "obs", "base")
    FPS = {"base": 200, "obs": 180, "light": 175, "medium": 165, "full": 150}

    def _session(self, d: Path, skip_load: str | None = None,
                 load: dict | None = None) -> None:
        _csv(d / "00_check.csv", [5.0] * 20)                       # step 3's 10 s check
        for k, arm in enumerate(self.ORDER, start=1):
            stem = f"{k:02d}_{arm}"
            _csv(d / f"{stem}.csv", list(np.full(500, 1000.0 / self.FPS[arm])))
            (d / f"{stem}.gpu.csv").write_text("timestamp,utilization.gpu\n", encoding="utf-8")
            if arm in fr.LEVELS and arm != skip_load:
                log = {"pace": 1.0, "lag_s": {"p95": 0.05}, **(load or {}).get(arm, {})}
                (d / f"{stem}.load.json").write_text(json.dumps(log), encoding="utf-8")
                (d / f"{stem}.load.txt").write_text("{}", encoding="utf-8")
        (d / "notes.txt").write_text("Ascent, attacker spawn\n", encoding="utf-8")
        (d / "decision.json").write_text("{}", encoding="utf-8")

    def test_the_protocols_folder_reads_and_decides(self):
        with tempfile.TemporaryDirectory() as d:
            self._session(Path(d))
            arms = fr.collect_arms(Path(d))
            self.assertNotIn("check", arms)
            self.assertEqual({k: len(a["files"]) for k, a in arms.items()},
                             {"base": 2, "obs": 2, "light": 2, "medium": 2, "full": 2})
            dec = fr.decide(arms)
            self.assertEqual(dec["chosen"], "medium")
            self.assertEqual(dec["chosen_vs_obs"], "full")         # 1 - 150/180 = 17%
            self.assertEqual(fr.main([d]), 0)

    def test_a_level_without_its_load_log_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self._session(Path(d), skip_load="medium")
            dec = fr.decide(fr.collect_arms(Path(d)))
            self.assertFalse(dec["rows"]["medium"]["passes"])
            self.assertIn("no load log", dec["rows"]["medium"]["why"])
            self.assertEqual(dec["chosen"], "light")

    def test_late_calls_fail_a_level_whose_pace_ratio_held(self):
        with tempfile.TemporaryDirectory() as d:
            self._session(Path(d), load={"medium": {"pace": 1.0, "lag_s": {"p95": 1.58}}})
            dec = fr.decide(fr.collect_arms(Path(d)))
            self.assertFalse(dec["rows"]["medium"]["passes"])
            self.assertIn("late", dec["rows"]["medium"]["why"])

    def test_a_late_start_fails_the_level_and_names_its_row(self):
        with tempfile.TemporaryDirectory() as d:
            self._session(Path(d), load={"light": {"ready_s": 31.0}})
            dec = fr.decide(fr.collect_arms(Path(d)))
            self.assertFalse(dec["rows"]["light"]["passes"])
            self.assertIn("started late in 03_light.csv", dec["rows"]["light"]["why"])
            self.assertEqual(dec["chosen"], "medium")

    def test_check_reads_the_ten_second_file(self):
        with tempfile.TemporaryDirectory() as d:
            self._session(Path(d))
            self.assertEqual(fr.main(["--check", str(Path(d) / "00_check.csv")]), 0)
            empty = Path(d) / "empty.csv"
            _csv(empty, [], extra_app=True)
            self.assertEqual(fr.check(empty), 1)

    def test_the_protocols_arm_line_matches_the_rules(self):
        doc = (Path(__file__).resolve().parents[1] / "docs" / "FRAMETIME_PROTOCOL.md").read_text(
            encoding="utf-8")
        line = next(x for x in doc.splitlines() if "live_load.py 043bafca271a" in x)
        seconds = float(re.search(r"--seconds (\d+)", line).group(1))
        max_wall = float(re.search(r"--max-wall (\d+)", line).group(1))
        delay, timed = (float(x) for x in re.search(r"--delay (\d+) --timed (\d+)", doc).groups())
        self.assertGreater(max_wall, seconds)          # a harness at pace is never cut short
        self.assertGreaterEqual(seconds, delay + timed)  # the load spans the recording
        self.assertLess(fr.READY_MAX, delay)
        self.assertIn("-RedirectStandardError", line)

    def test_an_undecided_session_names_no_level(self):
        with tempfile.TemporaryDirectory() as d:
            self._session(Path(d))
            _csv(Path(d) / "10_base.csv", list(np.full(500, 1000.0 / 180)))
            dec = fr.decide(fr.collect_arms(Path(d)))
            self.assertTrue(dec["verdict"].startswith("undecided"))
            self.assertIsNone(dec["chosen"])
            self.assertIsNone(dec["chosen_vs_obs"])
            self.assertEqual(dec["best_within_budget"], "medium")


class ScheduleTest(unittest.TestCase):
    def test_each_reader_reads_its_own_grid_inside_the_window(self):
        t15 = np.arange(0.0, 10000.0, 1000.0 / 15)
        t2 = np.arange(0.0, 10000.0, 500.0)
        caches = {"hud": SimpleNamespace(t_ms=t2, record={}),
                  "minimap": SimpleNamespace(t_ms=t15, record={"spans": [[0.0, 4000.0]]})}
        readers = {"hud": SimpleNamespace(hz=2.0), "ally_icon": SimpleNamespace(hz=5.0)}
        ev = ll.schedule(caches, readers, 1000.0, 6000.0, {}, with_audio=True)
        hud = [t for t, s, w in ev if s == "hud"]
        ally = [t for t, s, w in ev if s == "minimap"]
        self.assertEqual(len(hud), 11)                      # 1.0 .. 6.0 s at 2 Hz
        self.assertTrue(all(1000.0 <= t <= 4000.0 for t in ally))   # the cached span only
        # 3 s at 5 Hz from 1.0 s; the last cached time falls just short of 4.0 s.
        self.assertEqual(len(ally), 15)
        self.assertEqual([w for t, s, w in ev if s == "audio"], [["0.0:4000.0"]])
        self.assertEqual([t for t, *_ in ev], sorted(t for t, *_ in ev))


if __name__ == "__main__":
    unittest.main()
