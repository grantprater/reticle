"""The ultimate-cast adjudicator on hand-built peaks, lineups and rounds."""
import unittest

from reticle.adjudication import ult_cast as uc
from reticle.adjudication.identity import adjudicate_agent_identity, claims_from_lineup
from reticle.events import validate_event_rows


def _lineup(sid, ally, enemy, player_slot=0, enemy_refused=()):
    """A lineup whose arbiter verdicts name `ally` and `enemy` slot by slot;
    an enemy slot in `enemy_refused` is refused with a best guess and rival."""
    sides = {"ally": [{"slot": i, "agent": a, "best_guess": a, "rival": None}
                      for i, a in enumerate(ally)],
             "enemy": [{"slot": i, "agent": None if i in enemy_refused else a,
                        "best_guess": a, "rival": "Omen", "reason": "margin"}
                       for i, a in enumerate(enemy)]}
    claims = claims_from_lineup(sides, None, observation_id=sid, source_version="lineup-test")
    return {"version": "lineup-test", "sides": sides, "player": {"slot": player_slot},
            "agent_identity": adjudicate_agent_identity(claims),
            "board_state": {"applied": False, "reason": "no_scoreboard"}}


ALLY = ["Sova", "Jett", "Sage", "Omen", "Raze"]
ENEMY = ["Reyna", "Viper", "Neon", "Cypher", "Fade"]
ROUNDS = [{"round_no": 1, "t_start_ms": 10000.0, "t_end_ms": 100000.0, "t_close_ms": 107000.0},
          {"round_no": 2, "t_start_ms": 107000.0, "t_end_ms": 200000.0, "t_close_ms": 207000.0}]


def _peak(t_s, agent, variant, score, frame=None):
    return {"kind": "peak", "t_s": t_s, "frame": frame if frame is not None else int(round(t_s * 100)),
            "template": f"{agent}_ult_{variant}", "agent": agent, "variant": variant,
            "score": score, "floor": 0.02, "ult_line_version": "ult-line-test"}


def _stored(*peaks):
    return [{"kind": "coverage", "ult_line_version": "ult-line-test", "templates_key": "k"},
            *peaks]


class ClassTests(unittest.TestCase):

    def test_classes_follow_the_lineup(self):
        s = uc.lineup_sides(_lineup("s", ALLY, ENEMY), "s")
        c = lambda a, v: uc.template_class(a, v, s, "Sova")[0]
        self.assertEqual(c("Sova", "ally"), "own")
        self.assertEqual(c("Sova", "enemy"), "impossible")
        self.assertEqual(c("Jett", "ally"), "possible")
        self.assertEqual(c("Killjoy", "ally"), "impossible")
        self.assertEqual(c("Reyna", "enemy"), "possible")
        self.assertEqual(c("Killjoy", "enemy"), "impossible")

    def test_an_unresolved_slot_leaves_its_guesses_and_the_side_unknown(self):
        lu = _lineup("s", ALLY, ENEMY, enemy_refused=(4,))
        s = uc.lineup_sides(lu, "s")
        self.assertEqual(s["enemy"]["refused"], 1)
        self.assertFalse(s["enemy"]["complete"])
        self.assertEqual(uc.template_class("Killjoy", "enemy", s, "Sova"),
                         ("unknown", "enemy_side_has_1_unresolved_slots"))
        self.assertEqual(uc.template_class("Reyna", "enemy", s, "Sova")[0], "possible")

    def test_no_lineup_leaves_every_peak_unknown(self):
        self.assertIsNone(uc.lineup_sides(None, "s"))
        self.assertIsNone(uc.player_agent(None, "s"))
        self.assertEqual(uc.template_class("Jett", "ally", None, None), ("unknown", "no_lineup"))

    def test_the_player_is_the_arbiters_verdict_on_the_players_slot(self):
        self.assertEqual(uc.player_agent(_lineup("s", ALLY, ENEMY, player_slot=1), "s"), "Jett")


class AdjudicationTests(unittest.TestCase):

    def setUp(self):
        self.lu = _lineup("s", ALLY, ENEMY)
        self.peaks = _stored(_peak(50.0, "Sova", "ally", 0.20),       # own
                             _peak(60.0, "Reyna", "enemy", 0.05),     # possible, enemy side
                             _peak(70.0, "Killjoy", "ally", 0.09),    # impossible
                             _peak(80.0, "Jett", "ally", 0.03),       # below the threshold
                             _peak(104.0, "Omen", "ally", 0.06))      # post-round: round 1
        self.res = uc.adjudicate("s", self.peaks, self.lu, ROUNDS, "round-test")

    def test_only_peaks_at_the_threshold_are_selected(self):
        cov = self.res["rows"][0]
        self.assertEqual((cov["peaks"], cov["selected"]), (5, 4))
        self.assertEqual(cov["by_class"], {"own": 1, "possible": 2, "impossible": 1, "unknown": 0})
        self.assertNotIn(80.0, [r["t_s"] for r in self.res["rows"][1:]])
        self.assertEqual(cov["inputs"]["round"], "round-test")
        self.assertEqual(cov["inputs"]["lineup"], "lineup-test")

    def test_each_selected_peak_is_one_claim_resting_on_its_sides_verdicts(self):
        claims = {c["evidence"]["template"]: c for c in self.res["claims"]}
        self.assertEqual(len(claims), 4)
        self.assertTrue(all(c["channel"] == "ult_line" for c in claims.values()))
        self.assertEqual(claims["Reyna_ult_enemy"]["agent"], "Reyna")
        self.assertEqual(claims["Reyna_ult_enemy"]["depends_on"],
                         [f"s:enemy:slot:{i}" for i in range(5)])
        self.assertEqual(claims["Sova_ult_ally"]["depends_on"],
                         [f"s:ally:slot:{i}" for i in range(5)])
        self.assertEqual(claims["Sova_ult_ally"]["evidence"]["score"], 0.20)
        # The arbiter counts a dependent claim as no independent witness.
        v = {v["entity_id"]: v for v in self.res["verdicts"]}[claims["Reyna_ult_enemy"]["entity_id"]]
        self.assertEqual((v["status"], v["agent"], v["independent_channels"]),
                         ("resolved", "Reyna", 0))

    def test_casts_take_their_side_from_the_variant_and_their_name_from_the_arbiter(self):
        casts = {r["template"]: r for r in self.res["rows"] if r["kind"] == "cast"}
        self.assertEqual(casts["Sova_ult_ally"]["side"], "ally")
        self.assertTrue(casts["Sova_ult_ally"]["player_cast"])
        self.assertEqual(casts["Reyna_ult_enemy"]["side"], "enemy")
        self.assertFalse(casts["Reyna_ult_enemy"]["player_cast"])
        self.assertTrue(all(r["agent"] is not None and r["identity_status"] == "resolved"
                            for r in casts.values()))

    def test_an_impossible_peak_is_a_refusal_with_its_reason(self):
        refusals = [r for r in self.res["rows"] if r["kind"] == "refusal"]
        self.assertEqual(len(refusals), 1)
        r = refusals[0]
        self.assertEqual((r["template"], r["reason"], r["template_agent"]),
                         ("Killjoy_ult_ally", "agent_not_on_ally_side", "Killjoy"))
        self.assertNotIn("agent", r)
        claim = next(c for c in self.res["claims"] if c["entity_id"] == r["entity_id"])
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "agent_not_on_ally_side")
        v = next(v for v in self.res["verdicts"] if v["entity_id"] == r["entity_id"])
        self.assertEqual(v["status"], "abstained")

    def test_the_round_is_the_rounds_window_with_its_post_round_period(self):
        by_t = {r["t_s"]: r["round"] for r in self.res["rows"][1:]}
        self.assertEqual(by_t[50.0], 1)
        self.assertEqual(by_t[104.0], 1)
        res = uc.adjudicate("s", _stored(_peak(5.0, "Jett", "ally", 0.1),
                                         _peak(150.0, "Jett", "ally", 0.1)),
                            self.lu, ROUNDS, "round-test")
        self.assertEqual([r["round"] for r in res["rows"][1:]], [None, 2])

    def test_identity_events_come_from_the_arbiter_and_pass_the_validator(self):
        events = self.res["events"]
        self.assertEqual(len(events), 4)
        self.assertEqual(validate_event_rows(events), [])
        self.assertTrue(all(e["source_channel"] == "adjudication.identity" for e in events))

    def test_a_session_without_a_lineup_classes_every_peak_unknown(self):
        res = uc.adjudicate("s", self.peaks, None, ROUNDS, "round-test")
        cov = res["rows"][0]
        self.assertEqual(cov["by_class"], {"own": 0, "possible": 0, "impossible": 0, "unknown": 4})
        self.assertIsNone(cov["player_agent"])
        self.assertTrue(all(c["depends_on"] == [] for c in res["claims"]))

    def test_two_templates_at_one_onset_are_two_entities(self):
        res = uc.adjudicate("s", _stored(_peak(50.0, "Jett", "ally", 0.1),
                                         _peak(50.0, "Sage", "ally", 0.08)),
                            self.lu, ROUNDS, "round-test")
        ids = [r["entity_id"] for r in res["rows"][1:]]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual({r["agent"] for r in res["rows"][1:]}, {"Jett", "Sage"})


if __name__ == "__main__":
    unittest.main()
