"""The board's presence from two stored witnesses, the slab test's rows and
the round-history strip's, and the openings built from it."""
from __future__ import annotations

import unittest

from reticle.adjudication.scoreboard import (SCOREBOARD_AGENT_VERSION, board_presence,
                                             presence_runs, scoreboard_openings)

ALLY = ["Breach", "Deadlock", "Phoenix", "Reyna", "Miks"]
ENEMY = ["Jett", "Killjoy", "Skye", "Iso", "Omen"]


def _t(f: int) -> float:
    return f / 60 * 1000.0


def board_rows(frame: int) -> list[dict]:
    """Ten readable rows of one open board, as the slab test stores them."""
    return [{"kind": "row_observation", "t_ms": _t(frame), "frame_idx": frame,
             "display_row": i, "team": "ally" if i < 5 else "enemy",
             "observation_key": f"s:{frame}:{i}", "portrait_agent_reason": None,
             "portrait_agent_best": name, "portrait_agent_score": 0.9,
             "portrait_agent_margin": 0.4, "portrait_gain": 0.9,
             "row_y0": 340 + 34 * i if i < 5 else 570 + 34 * (i - 5),
             "scoreboard_version": "scoreboard-0.7.0"}
            for i, name in enumerate(ALLY + ENEMY)]


def slab_sample(frame: int, open_: bool, reason=None) -> dict:
    return {"kind": "sample", "frame_idx": frame, "t_ms": _t(frame), "open": open_,
            "reason": None if open_ else reason}


def strip_sample(frame: int, verdict: str) -> dict:
    return {"kind": "sample", "frame_idx": frame, "t_ms": _t(frame), "verdict": verdict,
            "reason": {"present": None, "absent": "too_few_cells",
                       "unreadable": "band_too_dark_for_dark_dots"}[verdict],
            "scoreboard_strip_version": "scoreboard-strip-0.1.0"}


class BoardPresenceTests(unittest.TestCase):
    def test_each_sample_keeps_what_each_witness_said(self):
        slab = [slab_sample(0, True), slab_sample(30, True), slab_sample(60, False, "red_tall"),
                slab_sample(90, False, "green_no_rows"), slab_sample(120, False, "red_tall")]
        strip = [strip_sample(0, "present"), strip_sample(30, "absent"),
                 strip_sample(60, "present"), strip_sample(90, "absent"),
                 strip_sample(120, "unreadable")]
        got = board_presence(slab, strip)
        self.assertEqual(got["slab_closed_from"], "sample_rows")
        s = got["samples"]
        self.assertEqual([x["witness"] for x in s],
                         ["both", "slab_only", "strip_only", "neither", "unreadable"])
        self.assertEqual([x["present"] for x in s], [True, True, True, False, False])
        self.assertEqual(s[2]["slab_reason"], "red_tall")
        self.assertEqual(s[4]["strip_reason"], "band_too_dark_for_dark_dots")

    def test_closed_samples_come_from_the_offered_frames_when_no_sample_rows(self):
        rows = board_rows(30) + [{"kind": "coverage", "frames_offered": 3}]
        strip = [strip_sample(f, "absent") for f in (0, 30, 60)]
        got = board_presence(rows, strip)
        self.assertEqual(got["slab_closed_from"], "offered_frames")
        self.assertEqual([x["slab"] for x in got["samples"]], ["closed", "open", "closed"])
        self.assertEqual([x["witness"] for x in got["samples"]],
                         ["neither", "slab_only", "neither"])

    def test_closed_samples_stay_unknown_when_the_offered_count_disagrees(self):
        rows = board_rows(30) + [{"kind": "coverage", "frames_offered": 4}]
        strip = [strip_sample(f, "present") for f in (0, 30, 60)]
        got = board_presence(rows, strip)
        self.assertIsNone(got["slab_closed_from"])
        self.assertEqual([x["witness"] for x in got["samples"]], ["no_slab", "both", "no_slab"])
        self.assertTrue(all(x["present"] for x in got["samples"]))

    def test_a_frame_without_strip_row_is_no_strip(self):
        got = board_presence([slab_sample(0, True)], [])
        self.assertEqual(got["samples"][0]["witness"], "no_strip")
        self.assertTrue(got["samples"][0]["present"])


def _samples(flags, dt=500.0):
    return [{"frame_idx": 30 * i, "t_ms": dt * i, "present": bool(v)}
            for i, v in enumerate(flags)]


class PresenceRunsTests(unittest.TestCase):
    def test_one_sample_holes_join_and_singles_count(self):
        runs = presence_runs(_samples([1, 1, 0, 1, 0, 0, 1, 0]))
        self.assertEqual([(r["a"], r["z"]) for r in runs], [(0, 3), (6, 6)])
        self.assertEqual(runs[0]["holes"], [60])
        self.assertEqual(runs[0]["samples_on"], 3)
        self.assertEqual([r["single"] for r in runs], [False, True])

    def test_two_closed_samples_break_a_hold(self):
        runs = presence_runs(_samples([1, 0, 0, 1]))
        self.assertEqual([(r["a"], r["z"]) for r in runs], [(0, 0), (3, 3)])

    def test_a_gap_in_the_sampling_breaks_a_hold(self):
        s = _samples([1, 1, 1])
        s[2]["t_ms"] = 3000.0
        runs = presence_runs(s)
        self.assertEqual([(r["a"], r["z"]) for r in runs], [(0, 1), (2, 2)])

    def test_another_reading_of_presence(self):
        s = _samples([1, 1, 0])
        s[1]["slab"] = "open"
        runs = presence_runs(s, on=lambda x: x.get("slab") == "open")
        self.assertEqual([(r["a"], r["z"]) for r in runs], [(1, 1)])


class CombinedOpeningsTests(unittest.TestCase):
    def setUp(self):
        self.board = (board_rows(0) + board_rows(60)
                      + [slab_sample(0, True), slab_sample(30, False, "red_tall"),
                         slab_sample(60, True), slab_sample(90, False, "green_no_rows")])
        self.strip = [strip_sample(0, "present"), strip_sample(30, "present"),
                      strip_sample(60, "absent"), strip_sample(90, "absent")]

    def test_without_the_strip_the_openings_are_unchanged(self):
        got = scoreboard_openings(self.board)
        self.assertEqual([o["accepted"] for o in got], [True, True])
        self.assertNotIn("presence", got[0])

    def test_the_strip_adds_a_refused_opening_and_one_hold(self):
        alone = scoreboard_openings(self.board)
        got = scoreboard_openings(self.board, strip_rows=self.strip)
        self.assertEqual([o["frame_idx"] for o in got], [0, 30, 60])
        self.assertEqual([o["accepted"] for o in got], [True, False, True])
        self.assertEqual(got[1]["reason"], "strip_only_no_rows")
        self.assertEqual(got[1]["rows"], [])
        self.assertEqual(got[1]["version"], SCOREBOARD_AGENT_VERSION)
        self.assertEqual([o["presence"]["witness"] for o in got],
                         ["both", "strip_only", "slab_only"])
        self.assertEqual({o["hold"] for o in got}, {0})
        # the portrait gate is the same with or without the strip
        kept = [o for o in got if o["reason"] != "strip_only_no_rows"]
        self.assertEqual([(o["accepted"], o["reason"]) for o in kept],
                         [(o["accepted"], o["reason"]) for o in alone])


if __name__ == "__main__":
    unittest.main()
