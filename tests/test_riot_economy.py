"""EconomyTracker replayed over Riot's stored match records.

Riot's records are an external witness to the credit rules: every team-round's
wallet total must be the owner's prediction, AFK rounds excepted.

The store gains a record with every replayed match, so the tests assert rates
over whatever records exist, never corpus totals; the floors catch a record
lost from the store.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_economy as rx  # noqa: E402

RECORDS = rx.STORE / "external" / "riot"

# Team-round counts of the 23 records stored on 2026-10-05: the 22 captured
# in August and September and c817691bcd15's. The store only grows.
FLOOR = {"match_start_n": 46, "halftime_n": 42, "overtime_n": 24, "regular_n": 860}


@unittest.skipUnless(any(RECORDS.glob("*.json")), "no Riot records in the store")
class RiotEconomyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = rx.load_records()
        cls.rows = [row for sid, m in cls.records for row in rx.replay(sid, m)]
        cls.summary = rx.summarise(cls.rows)

    def test_store_keeps_its_records(self):
        for key, floor in FLOOR.items():
            self.assertGreaterEqual(self.summary[key], floor, key)

    def test_resets(self):
        s = self.summary
        for period in ("match_start", "halftime", "overtime"):
            self.assertEqual(s[f"{period}_ok"], s[f"{period}_n"], period)

    def test_regular_rounds(self):
        # Every regular team-round is predicted except those an AFK player
        # settles [domain:rounds/afk-round-reward].
        s = self.summary
        afk_misses = sum(1 for r in self.rows
                         if r["period"] == "regular" and not r["ok"] and r["afk_settled"])
        self.assertEqual(s["regular_ok"], s["regular_n"] - afk_misses)

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
        # A 200-credit plant reward mispredicts about a third of regular
        # team-rounds on the 26 records of 2026-10-07.
        rules = rx.alternative_rules("plant_200")
        rows = [row for sid, m in self.records for row in rx.replay(sid, m, rules)]
        s = rx.summarise(rows)
        self.assertLess(s["regular_ok"], 0.75 * s["regular_n"])


if __name__ == "__main__":
    unittest.main()
