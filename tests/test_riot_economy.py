"""EconomyTracker replayed over Riot's stored match records.

Riot's records are an external witness to the credit rules: every team-round's
wallet total must be the owner's prediction, the one AFK round excepted.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_economy as rx  # noqa: E402

RECORDS = rx.STORE / "external" / "riot"


@unittest.skipUnless(any(RECORDS.glob("*.json")), "no Riot records in the store")
class RiotEconomyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = rx.load_records()
        cls.rows = [row for sid, m in cls.records for row in rx.replay(sid, m)]
        cls.summary = rx.summarise(cls.rows)

    def test_resets(self):
        s = self.summary
        self.assertEqual((s["match_start_ok"], s["match_start_n"]), (44, 44))
        self.assertEqual((s["halftime_ok"], s["halftime_n"]), (40, 40))
        self.assertEqual((s["overtime_ok"], s["overtime_n"]), (16, 16))

    def test_regular_rounds(self):
        s = self.summary
        self.assertEqual(s["regular_n"], 816)
        self.assertGreaterEqual(s["regular_ok"], 815)

    def test_every_miss_settles_an_afk_round(self):
        # Riot withholds an AFK player's round reward and pays teammates a
        # share; the ledger does not model it [domain:rounds/afk-round-reward].
        misses = [r for r in self.rows if not r["ok"]]
        self.assertTrue(all(r["afk_settled"] for r in misses), misses)

    def test_old_overtime_default_fails(self):
        rules = rx.alternative_rules("overtime_800")
        rows = [row for sid, m in self.records for row in rx.replay(sid, m, rules)]
        self.assertEqual(rx.summarise(rows)["overtime_ok"], 0)

    def test_plant_reward_200_fails(self):
        rules = rx.alternative_rules("plant_200")
        rows = [row for sid, m in self.records for row in rx.replay(sid, m, rules)]
        self.assertLess(rx.summarise(rows)["regular_ok"], 600)


if __name__ == "__main__":
    unittest.main()
