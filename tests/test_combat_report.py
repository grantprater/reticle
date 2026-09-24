"""The combat report reader's pixel rules and the panel/round adjudication."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from reticle import combat_report as cr
from reticle.adjudication import combat_report as adj
from reticle.version import COMBAT_REPORT_VERSION


def _row(out, inc, oh="000", ih="000", killed=0.0, killed_you=0.0, assist=0.0):
    return {"out": {"text": out}, "in": {"text": inc},
            "out_hits": {"text": oh}, "in_hits": {"text": ih},
            "out_word": {"KILLED": killed, "KILLED YOU": 0.1, "ASSIST": assist},
            "in_word": {"KILLED": 0.1, "KILLED YOU": killed_you, "ASSIST": 0.1}}


def _frame(t, rows, header=0.99):
    return {"kind": "frame", "t_ms": float(t), "header": header, "hx": 1633, "hy": 465,
            "rows": rows, "combat_report_version": COMBAT_REPORT_VERSION}


def _run(t0, t1, rows, step=1000):
    return [_frame(t, rows) for t in range(t0, t1 + 1, step)]


ROUNDS = [
    {"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100000.0, "player_kills": 1, "player_deaths": 1},
    {"round_no": 2, "t_start_ms": 100000.0, "t_end_ms": 200000.0, "player_kills": 0, "player_deaths": 1},
    {"round_no": 3, "t_start_ms": 208000.0, "t_end_ms": 300000.0, "player_kills": 2, "player_deaths": 0},
]


class ReaderPixels(unittest.TestCase):
    def test_grey_counts_read_as_zero_without_a_template(self):
        patch = np.full((52, 16), 40, np.uint8)
        for y in (6, 22, 38):
            patch[y:y + 9, 5:11] = 150           # drawn grey: a zero count
        self.assertEqual(cr.read_hits(patch, tpl=None)["text"], "000")

    def test_wrong_blob_count_is_refused_with_a_reason(self):
        patch = np.full((52, 16), 40, np.uint8)
        patch[6:15, 5:11] = 150
        got = cr.read_hits(patch, tpl=None)
        self.assertIsNone(got["text"])
        self.assertEqual(got["reason"], "1-blobs")

    def test_header_is_found_where_it_is_drawn(self):
        header, _words = cr.load_templates()
        gray = np.random.default_rng(0).integers(20, 60, (1080, 1920)).astype(np.uint8)
        gray[400:400 + header.shape[0], 1600:1600 + header.shape[1]] = header
        score, hx, hy = cr.locate(gray, header)
        self.assertGreater(score, 0.99)
        self.assertEqual((hx, hy), (1600, 400))

    def test_other_frame_sizes_are_refused_not_scaled(self):
        reader = cr.CombatReportReader(digits=None)
        reader.feed(SimpleNamespace(frame_idx=0, t_ms=0.0, frame=np.zeros((720, 1280, 3), np.uint8)))
        self.assertIsNone(reader.rows[0]["header"])
        self.assertEqual(reader.rows[0]["reason"], "frame_size_1280x720")


class Panels(unittest.TestCase):
    def test_reopen_merges_but_an_identical_death_panel_is_new(self):
        same = [_row("0", "160", ih="100", killed_you=0.99)]
        frames = _run(50000, 60000, same) + _run(90000, 92000, same) + _run(150000, 160000, same)
        ps = adj.panels(frames, death_times=[50000.0, 150000.0])
        self.assertEqual([p["start_ms"] for p in ps], [50000.0, 150000.0])
        self.assertEqual(ps[0]["reopens"], [90000.0])

    def test_flags_are_a_majority_vote_over_the_panel(self):
        rows_hit = [_row("160", "0", oh="100", killed=0.95)]
        rows_miss = [_row("160", "0", oh="100", killed=0.3)]
        frames = _run(10000, 14000, rows_hit) + [_frame(15000, rows_miss)]
        (p,) = adj.panels(frames, death_times=[10000.0])
        self.assertTrue(p["rows"][0]["killed"])

    def test_hit_count_noise_does_not_change_the_modal_read(self):
        good = [_row("65", "0", oh="010")]
        noisy = [_row("65", "0", oh="018")]
        frames = _run(10000, 18000, good) + [_frame(19000, noisy)]
        (p,) = adj.panels(frames, death_times=[10000.0])
        self.assertEqual(p["rows"][0]["out_hits"], "010")
        self.assertEqual(p["agreement"]["out_hits"], [9, 1, 0])


class Rounds(unittest.TestCase):
    def test_summary_early_in_a_round_belongs_to_the_previous_one(self):
        # Round 2 ends exactly where round 3 would begin had there been no
        # gap; the boundary itself must still step back (a strict < did not).
        rounds = [dict(r) for r in ROUNDS]
        rounds[2]["t_start_ms"] = 200000.0
        frames = _run(210000, 214000, [_row("160", "0", oh="100", killed=0.95)])
        ps = adj.panels(frames, death_times=[])
        adj.assign_rounds(ps, rounds)
        self.assertEqual((ps[0]["kind"], ps[0]["round_no"]), ("summary", 2))

    def test_counts_sit_beside_the_stored_rounds_and_keep_disagreements(self):
        frames = (_run(60000, 70000, [_row("160", "65", oh="100", ih="010", killed=0.95,
                                           killed_you=0.99)])
                  + _run(150000, 160000, [_row("0", "160", ih="100", killed_you=0.99)])
                  + _run(210000, 214000, [_row("160", "0", oh="100", killed=0.95)]))
        ev = adj.events("s", frames, ROUNDS, death_times=[60000.0, 150000.0])
        rounds = {e["round_no"]: e for e in ev if e["kind"] == "round"}
        self.assertEqual((rounds[1]["kills"], rounds[1]["deaths"]), (1, 1))
        self.assertTrue(rounds[1]["kills_agree"] and rounds[1]["deaths_agree"])
        # The summary opened early in round 3 is round 2's: 1 kill against 0 stored.
        self.assertEqual(rounds[2]["kills"], 1)
        self.assertFalse(rounds[2]["kills_agree"])
        self.assertIsNone(rounds[3]["kills"])
        self.assertEqual(rounds[3]["reason"], "no panel shown for this round")
        self.assertEqual(ev[0]["kills_disagree"], 1)

    def test_rows_from_another_version_are_refused(self):
        frames = _run(60000, 62000, [_row("0", "160")])
        frames[0]["combat_report_version"] = "combat-report-0.0.0"
        with self.assertRaises(ValueError):
            adj.events("s", frames, ROUNDS, death_times=[60000.0])


if __name__ == "__main__":
    unittest.main()
