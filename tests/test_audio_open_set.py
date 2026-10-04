import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import audio_open_set as A  # noqa: E402


def row(flac, abilities, phases, persp=None, states=()):
    return {"flac": flac, "abilities": abilities, "phases": phases,
            "media_name_perspective": persp, "states": [list(s) for s in states]}


class CandidateFileTests(unittest.TestCase):
    def test_keeps_only_single_ability_files_of_the_agent(self):
        rows = [row("a", ["Sova:Q:Shock Bolt"], ["cast"]),
                row("b", ["Sova:Q:Shock Bolt", "Sova:E:Recon Bolt"], ["equip"]),
                row("c", [], []),
                row("d", ["Skye:Q:Trailblazer"], ["cast"]),
                row("e", ["Sova:Q:Shock Bolt"], ["refused"])]
        self.assertEqual([f["flac"] for f in A.kit_files(rows, "Sova")], ["a"])

    def test_perspective_prefers_the_media_name(self):
        self.assertEqual(A.perspective(row("x", [], [], "3P", [("Q", "o", "s", "cast", "e", "1P")])), "3P")
        self.assertEqual(A.perspective(row("x", [], [], None, [("Q", "o", "s", "cast", "e", "1P?")])), "1P")
        self.assertEqual(A.perspective(row("x", [], [], None, [("Q", "o", "s", "cast", "e", "3P-ally")])), "3P")
        self.assertEqual(A.perspective(row("x", [], [], None, [("Q", "o", "s", "c", "e", "1P"),
                                                               ("Q", "o", "s", "c", "e", "3P")])), "any")

    def test_a_file_takes_its_earliest_phase(self):
        self.assertEqual(A.file_phase(["impact", "cast"]), ("cast", 2, True))
        self.assertEqual(A.file_phase(["loop"]), ("loop", 6, False))
        self.assertEqual(A.file_phase(["none"]), ("none", None, False))


class SplitTests(unittest.TestCase):
    def test_even_positions_dev(self):
        self.assertEqual(A.split_demos(["c", "a", "b"]), {"dev": ["a", "c"], "held": ["b"]})


class QuantileTests(unittest.TestCase):
    def test_histogram_quantiles_match_numpy(self):
        rng = np.random.default_rng(0)
        r = np.clip(rng.normal(0.1, 0.1, 200000), -1, 1)
        h = np.bincount(A.hist_index(r), minlength=A.HIST_BINS)[None]
        q = A.hist_quantiles(h)[0]
        self.assertAlmostEqual(q[0], np.quantile(r, 0.5), delta=2.0 / A.HIST_BINS)
        self.assertAlmostEqual(q[1], np.quantile(r, 0.999), delta=2.0 / A.HIST_BINS)

    def test_empty_row_is_nan(self):
        self.assertTrue(np.isnan(A.hist_quantiles(np.zeros((1, A.HIST_BINS)))).all())


class PeakTests(unittest.TestCase):
    def test_local_maxima_at_or_above_level_one_per_gap(self):
        V = np.zeros((1, 400), np.float32)
        V[0, 100], V[0, 120], V[0, 300] = 2.0, 1.5, 1.0
        f, k = A.peaks(V, np.ones_like(V, bool), 0.9, gap=50)
        self.assertEqual(list(k), [100, 300])

    def test_invalid_frames_never_peak(self):
        V = np.zeros((1, 200), np.float32)
        V[0, 50] = 3.0
        valid = np.ones_like(V, bool)
        valid[0, 50] = False
        self.assertEqual(len(A.peaks(V, valid, 0.9)[1]), 0)

    def test_a_plateau_keeps_its_first_frame(self):
        V = np.zeros((1, 200), np.float32)
        V[0, 60:63] = 2.0
        self.assertEqual(list(A.peaks(V, np.ones_like(V, bool), 0.9)[1]), [60])


FILES = [{"slot": "Q", "phase": "equip", "rank": 0, "opens": True, "perspective": "1P"},
         {"slot": "Q", "phase": "cast", "rank": 2, "opens": True, "perspective": "1P"},
         {"slot": "Q", "phase": "impact", "rank": 4, "opens": False, "perspective": "3P"},
         {"slot": "E", "phase": "loop", "rank": 6, "opens": False, "perspective": "any"}]


class EventTests(unittest.TestCase):
    def test_phases_in_order_group_into_one_event(self):
        ev = A.group_events([(0, 100, 1.0), (1, 150, 2.0), (2, 900, 1.5)], FILES, "max")
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["frame"], ev[0]["state"]), (150, "cast"))
        self.assertEqual(ev[0]["best_phase"], "cast")
        old = A.group_events([(0, 100, 1.0), (1, 150, 2.0)], FILES, "max", rule="audio-open-set-0.1.0")
        self.assertEqual(old[0]["frame"], 100)

    def test_equip_alone_is_an_equip_state_event(self):
        ev = A.group_events([(0, 100, 3.0)], FILES, "max")
        self.assertEqual((ev[0]["state"], ev[0]["frame"]), ("equip", 100))

    def test_a_cast_long_after_equip_takes_the_cast_time(self):
        ev = A.group_events([(0, 100, 3.0), (1, 700, 2.0)], FILES, "max")
        self.assertEqual([(e["state"], e["frame"]) for e in ev], [("cast", 700)])

    def test_a_repeated_cast_phase_opens_a_new_event(self):
        ev = A.group_events([(1, 100, 2.0), (1, 600, 2.0)], FILES, "max")
        self.assertEqual([e["frame"] for e in ev], [100, 600])

    def test_a_late_phase_past_life_opens_a_new_event(self):
        ev = A.group_events([(1, 100, 2.0), (2, 100 + int(A.LIFE_S * 100) + 300, 2.0)], FILES, "max")
        self.assertEqual(len(ev), 2)

    def test_cast_family_never_opens_on_a_later_phase(self):
        self.assertEqual(A.group_events([(3, 100, 5.0)], FILES, "cast"), [])
        self.assertEqual(len(A.group_events([(3, 100, 5.0)], FILES, "max")), 1)

    def test_agree_family_needs_two_phases(self):
        self.assertEqual(A.group_events([(1, 100, 5.0)], FILES, "agree"), [])
        self.assertEqual(len(A.group_events([(1, 100, 5.0), (2, 300, 1.0)], FILES, "agree")), 1)

    def test_abilities_group_apart(self):
        ev = A.group_events([(1, 100, 2.0), (3, 120, 2.0)], FILES, "max")
        self.assertEqual(sorted(e["slot"] for e in ev), ["E", "Q"])


class MatchTests(unittest.TestCase):
    def test_nearest_same_slot_inside_window_each_once(self):
        ev = [{"slot": "Q", "frame": 1000}, {"slot": "Q", "frame": 1050}, {"slot": "E", "frame": 1000}]
        casts = [{"slot": "Q", "frame": 1040}, {"slot": "E", "frame": 2000}]
        m = A.match(ev, casts)
        self.assertEqual([(i, j) for i, j, _dt in m], [(1, 0)])

    def test_castfree_excludes_the_span_around_each_time(self):
        m = A.castfree_mask(3000, np.ones(3000, bool), [10.0])
        self.assertTrue(m[600] and not m[800] and not m[1900] and m[2100])


if __name__ == "__main__":
    unittest.main()
