"""Synthetic checks of prototypes/tray_gold_eval.py: per-slot scoring and the
persistence rule's switch. No store is read; every input is built here."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import tray_gold_eval as tge  # noqa: E402
from reticle import tray  # noqa: E402


class ScoreSlots(unittest.TestCase):
    def test_covered_is_the_lesser_and_beyond_the_excess(self):
        got = tge.score_slots({"C": 3, "Q": 1, "E": 5}, {"C": 2, "Q": 4, "E": 5, "X": 1})
        self.assertEqual(got["C"], {"riot": 2, "covered": 2, "beyond": 1})
        self.assertEqual(got["Q"], {"riot": 4, "covered": 1, "beyond": 0})
        self.assertEqual(got["E"], {"riot": 5, "covered": 5, "beyond": 0})
        self.assertEqual(got["X"], {"riot": 1, "covered": 0, "beyond": 0})

    def test_a_slot_riot_lacks_is_not_scored(self):
        self.assertEqual(tge.score_slots({"C": 2}, {}), {})

    def test_total_sums_sessions_and_slots(self):
        a = tge.score_slots({"C": 3}, {"C": 2, "X": 1})
        b = tge.score_slots({"E": 1}, {"E": 2})
        self.assertEqual(tge.total([a, b]), {"riot": 5, "covered": 3, "beyond": 1})


class PersistMin(unittest.TestCase):
    CAND = {"t_ms": 2000.0, "slot": "E", "t_before_ms": 1500.0, "t_gold_ms": 1500.0,
            "gold_run": 2}

    def test_the_rule_sets_and_restores_the_owner_constant(self):
        before = tray.GOLD_PERSIST_MIN
        with tge.persist_min(None):
            w = tray.gold_witness(self.CAND, [], {})
            self.assertFalse(w["witnessed"])
        with tge.persist_min(2):
            self.assertEqual(tray.gold_witness(self.CAND, [], {})["by"], ["persisted"])
        with tge.persist_min(3):
            self.assertFalse(tray.gold_witness(self.CAND, [], {})["witnessed"])
        self.assertEqual(tray.GOLD_PERSIST_MIN, before)

    def test_the_constant_is_restored_after_an_exception(self):
        before = tray.GOLD_PERSIST_MIN
        with self.assertRaises(RuntimeError):
            with tge.persist_min(None):
                raise RuntimeError("inside the rule")
        self.assertEqual(tray.GOLD_PERSIST_MIN, before)

    def test_eye_key_rounds_to_a_tenth_second(self):
        self.assertEqual(tge.eye_key("s", {"slot": "E", "t_ms": 429066.67}), ("s", "E", 429.1))


if __name__ == "__main__":
    unittest.main()
