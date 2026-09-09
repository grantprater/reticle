import unittest

from reticle.economy import (CreditRange, EconomyTracker, RoundEconomyInput,
                             run_document, survival_penalty)
from reticle.version import ECONOMY_VERSION


TEAMS = {"ally": ("a1", "a2"), "enemy": ("e1", "e2")}


def round_input(number, winner="enemy", attacker="ally", planted=False,
                detonated=False, kills=None, survived=None):
    loser = "enemy" if winner == "ally" else "ally"
    return RoundEconomyInput(
        round_no=number, winner=winner, attacking_team=attacker,
        planted=planted, spike_detonated=detonated,
        kills=kills or {p: 0 for players in TEAMS.values() for p in players},
        survived=survived or {p: False for p in TEAMS[loser]},
        settlement_t_ms=number * 1000.0, source_ids=(f"round:{number}",))


class EconomyTests(unittest.TestCase):
    def tracker(self):
        tracker = EconomyTracker(TEAMS)
        tracker.reset_period(1, "match_start")
        return tracker

    def test_start_spend_kills_plant_and_first_loss(self):
        tracker = self.tracker()
        tracker.record_spending("a1", 800, round_no=1, reason="observed_buy")
        tracker.settle_round(round_input(
            1, planted=True,
            kills={"a1": 2, "a2": 0, "e1": 0, "e2": 0},
            survived={"a1": False, "a2": False}))
        self.assertEqual(tracker.balances["a1"], CreditRange.exact(2600))
        self.assertEqual(tracker.balances["a2"], CreditRange.exact(3000))
        self.assertEqual(tracker.balances["e1"], CreditRange.exact(3800))
        self.assertEqual(tracker.loss_streaks, {"ally": 1, "enemy": 0})

    def test_loss_streak_advances_and_win_resets_it(self):
        tracker = self.tracker()
        tracker.settle_round(round_input(1))
        tracker.settle_round(round_input(2))
        tracker.settle_round(round_input(3))
        tracker.settle_round(round_input(4, winner="ally", attacker="enemy",
                                         survived={"e1": False, "e2": False}))
        tracker.settle_round(round_input(5))
        rewards = [tx.amount.value for tx in tracker.transactions
                   if tx.player_id == "a1" and tx.kind == "round_loss_reward"]
        self.assertEqual(rewards, [1900, 2400, 2900, 1900])

    def test_surviving_attack_loss_without_plant_gets_1000(self):
        tracker = self.tracker()
        tracker.settle_round(round_input(1, survived={"a1": True, "a2": False}))
        self.assertEqual(tracker.balances["a1"], CreditRange.exact(1800))
        self.assertEqual(tracker.balances["a2"], CreditRange.exact(2700))

    def test_surviving_defuse_loss_does_not_get_penalty(self):
        tracker = self.tracker()
        tracker.settle_round(round_input(1, planted=True,
                                         survived={"a1": True, "a2": False}))
        self.assertEqual(tracker.balances["a1"], CreditRange.exact(3000))

    def test_surviving_defender_after_detonation_gets_penalty(self):
        tracker = self.tracker()
        tracker.settle_round(round_input(
            1, winner="ally", attacker="ally", planted=True, detonated=True,
            survived={"e1": True, "e2": False}))
        self.assertEqual(tracker.balances["e1"], CreditRange.exact(1800))
        self.assertEqual(tracker.balances["e2"], CreditRange.exact(2700))

    def test_unknown_plant_and_survival_produce_bounds(self):
        tracker = self.tracker()
        tracker.settle_round(round_input(
            1, planted=None, detonated=None,
            survived={"a1": None, "a2": False}))
        self.assertEqual(tracker.balances["a1"], CreditRange(1800, 3000))
        self.assertEqual(tracker.balances["a2"], CreditRange(2700, 3000))
        self.assertIsNone(tracker.snapshot()["players"]["a1"]["credits"])

    def test_balance_observation_anchors_and_preserves_conflict(self):
        tracker = self.tracker()
        result = tracker.observe_balance("a1", 500, round_no=1,
                                         source_ids=("hud:10",))
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.residual, (-300, -300))
        self.assertEqual(tracker.balances["a1"], CreditRange.exact(500))
        tx = tracker.transactions[result.transaction_sequence]
        self.assertEqual(tx.balance_before, CreditRange.exact(800))
        self.assertEqual(tx.source_ids, ("hud:10",))

    def test_partial_capture_refuses_without_all_player_anchors(self):
        tracker = EconomyTracker(TEAMS)
        for player in ("a1", "a2", "e1"):
            tracker.observe_balance(player, 2000, round_no=7)
        with self.assertRaisesRegex(ValueError, "e2"):
            tracker.settle_round(round_input(7))

    def test_uncertain_spending_is_conservative(self):
        tracker = self.tracker()
        tracker.record_spending("a1", (400, 800), round_no=1)
        self.assertEqual(tracker.balances["a1"], CreditRange(0, 400))

    def test_spending_that_exceeds_every_possible_balance_refuses(self):
        tracker = self.tracker()
        with self.assertRaisesRegex(ValueError, "maximum spend"):
            tracker.record_spending("a1", (400, 1000), round_no=1)

    def test_cap_applies_to_each_reward_component(self):
        tracker = self.tracker()
        tracker.observe_balance("a1", 8950, round_no=1)
        tracker.settle_round(round_input(
            1, kills={"a1": 1, "a2": 0, "e1": 0, "e2": 0}))
        self.assertEqual(tracker.balances["a1"], CreditRange.exact(9000))
        kill = next(tx for tx in tracker.transactions
                    if tx.player_id == "a1" and tx.kind == "kill_reward")
        self.assertEqual(kill.balance_after, CreditRange.exact(9000))

    def test_reset_clears_balances_and_loss_streaks(self):
        tracker = self.tracker()
        tracker.settle_round(round_input(1))
        tracker.reset_period(2, "halftime")
        self.assertTrue(all(v == CreditRange.exact(800)
                            for v in tracker.balances.values()))
        self.assertEqual(tracker.loss_streaks, {"ally": 0, "enemy": 0})
        self.assertEqual(tracker.last_settled_round, 1)

    def test_survival_rule_propagates_unknowns(self):
        self.assertTrue(survival_penalty("attack", True, False, False))
        self.assertFalse(survival_penalty("attack", True, True, False))
        self.assertTrue(survival_penalty("defence", True, True, True))
        self.assertIsNone(survival_penalty("defence", True, True, None))
        self.assertFalse(survival_penalty("defence", False, None, None))

    def test_transactions_carry_version_and_source(self):
        tracker = self.tracker()
        rows = tracker.settle_round(round_input(1))
        self.assertTrue(rows)
        self.assertTrue(all(row.economy_version == ECONOMY_VERSION for row in rows))
        self.assertTrue(all(row.source_ids == ("round:1",) for row in rows))

    def test_fact_document_is_a_json_serializable_adapter(self):
        document = {
            "teams": {team: list(players) for team, players in TEAMS.items()},
            "operations": [
                {"kind": "reset", "round_no": 1, "reason": "match_start"},
                {"kind": "spend", "round_no": 1, "player_id": "a1",
                 "amount": [400, 800], "source_ids": ["buy:1"]},
                {"kind": "round", "round_no": 1, "winner": "enemy",
                 "attacking_team": "ally", "planted": False,
                 "spike_detonated": False,
                 "kills": {p: 0 for players in TEAMS.values() for p in players},
                 "survived": {"a1": False, "a2": False},
                 "source_ids": ["round:1"]},
            ],
        }
        result = run_document(document)
        self.assertEqual(result["economy_version"], ECONOMY_VERSION)
        self.assertEqual(result["snapshot"]["players"]["a1"]["credits_min"], 1900)
        self.assertEqual(result["snapshot"]["players"]["a1"]["credits_max"], 2300)
        self.assertEqual(result["transactions"][4]["source_ids"], ("buy:1",))


if __name__ == "__main__":
    unittest.main()
