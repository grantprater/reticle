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
    claims = claims_from_lineup(sides, {"tray": {"votes": {ally[player_slot]: 9}}},
                                observation_id=sid, source_version="lineup-test")
    return {"version": "lineup-test", "sides": sides, "identity_claims": claims,
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


def _cast(t_ms, reason=None, **tray):
    """One X drop as `player_x_drops` returns it: the player's cast unless the
    owner gave a reason to refuse it."""
    return {"t_ms": t_ms, "slot": "X", "from": 1.0, "to": 0.0, "suspect": False,
            "forced": False, "cooccur": False, "across_gap": False,
            "player_cast": reason is None, "reason": reason, **tray}


class TrayBindingTests(unittest.TestCase):
    """Own lines bound to the player's X casts, and X casts with no own line."""

    def setUp(self):
        self.lu = _lineup("s", ALLY, ENEMY)            # the player is Sova
        self.peaks = _stored(_peak(50.0, "Sova", "ally", 0.20),     # witnessed own line
                             _peak(150.0, "Sova", "ally", 0.10),    # own line, no drop
                             _peak(69.6, "Sova", "ally", 0.025),    # under the witness floor
                             _peak(90.3, "Jett", "ally", 0.03))     # another template
        self.casts = [_cast(50400.0), _cast(70000.0), _cast(90000.0, **{"from": 0.97}),
                      _cast(150500.0, "after_player_death")]
        self.res = uc.adjudicate("s", self.peaks, self.lu, ROUNDS, "round-test",
                                 tray_drops=self.casts, tray_inputs={"tray_drop": "tray-test"})
        self.own = {r["t_s"]: r for r in self.res["rows"]
                    if r["kind"] == "cast" and r["class"] == "own"}
        self.missed = {r["cast_t_ms"]: r for r in self.res["rows"] if r["kind"] == "missed_line"}

    def test_an_own_line_beside_a_drop_is_witnessed_by_the_nearest_cast(self):
        self.assertEqual(self.own[50.0]["tray_witness"], {"dt_s": -0.4, "cast_t_ms": 50400.0})
        self.assertIsNone(self.own[50.0]["tray_witness_reason"])

    def test_an_own_line_without_a_drop_has_no_witness_and_says_why(self):
        self.assertIsNone(self.own[150.0]["tray_witness"])
        self.assertEqual(self.own[150.0]["tray_witness_reason"], "no_x_cast_in_window")

    def test_an_unwitnessed_own_line_keeps_the_drop_the_owner_refused(self):
        self.assertEqual(self.own[150.0]["tray_refused"],
                         {"dt_s": -0.5, "drop_t_ms": 150500.0, "reason": "after_player_death"})
        self.assertNotIn("tray_refused", self.own[50.0])
        self.assertNotIn(150500.0, self.missed)      # a refused drop is no cast to miss
        self.assertEqual(self.res["rows"][0]["own_beside_refused_drop"],
                         {"after_player_death": 1})

    def test_a_drop_without_a_line_keeps_the_best_peak_under_the_threshold(self):
        r = self.missed[70000.0]
        self.assertEqual((r["round"], r["player_agent"], r["template"]), (1, "Sova", "Sova_ult_ally"))
        self.assertEqual(r["best_peak"]["score"], 0.025)
        self.assertEqual(r["best_peak"]["dt_s"], -0.4)
        self.assertIsNone(r["best_peak_reason"])
        self.assertLess(r["best_peak"]["score"], uc.THRESHOLD)

    def test_a_drop_without_any_own_peak_is_null_with_its_reason(self):
        r = self.missed[90000.0]
        self.assertIsNone(r["best_peak"])            # Jett's peak is not the own template
        self.assertEqual(r["best_peak_reason"], "no_peak_above_floor")
        self.assertEqual(r["tray"]["from"], 0.97)    # the drop's reading, kept as evidence

    def test_the_coverage_row_counts_the_binding(self):
        cov = self.res["rows"][0]
        self.assertEqual((cov["own_witnessed"], cov["own_unwitnessed"]), (1, 1))
        self.assertEqual((cov["missed_lines"], cov["missed_with_peak"]), (2, 1))
        self.assertEqual((cov["tray"]["x_drops"], cov["tray"]["player_x_casts"]), (4, 3))
        self.assertEqual(cov["inputs"]["tray_drop"], "tray-test")
        self.assertEqual(cov["by_class"]["own"], 2)  # missed lines are no selection

    def test_phoenix_binds_a_line_from_twenty_seconds_before_the_drop(self):
        lu = _lineup("s", ["Phoenix", "Jett", "Sage", "Omen", "Raze"], ENEMY)
        res = uc.adjudicate("s", _stored(_peak(50.0, "Phoenix", "ally", 0.2)), lu, ROUNDS,
                            "round-test", tray_drops=[_cast(62600.0)])
        own = next(r for r in res["rows"] if r.get("class") == "own")
        self.assertEqual(own["tray_witness"], {"dt_s": -12.6, "cast_t_ms": 62600.0})
        self.assertEqual(res["rows"][0]["missed_lines"], 0)
        # Any other agent's window is 1.5 s either side.
        res = uc.adjudicate("s", _stored(_peak(50.0, "Sova", "ally", 0.2)), self.lu, ROUNDS,
                            "round-test", tray_drops=[_cast(62600.0)])
        self.assertEqual(res["rows"][0]["missed_lines"], 1)
        self.assertEqual(uc.cast_window("Phoenix"), (-20.0, 1.5))
        self.assertEqual(uc.cast_window("Sova"), (-1.5, 1.5))

    def test_a_cast_outside_every_round_is_counted_not_missed(self):
        res = uc.adjudicate("s", self.peaks, self.lu, ROUNDS, "round-test",
                            tray_drops=[_cast(5000.0)])
        self.assertEqual(res["rows"][0]["missed_lines"], 0)
        self.assertEqual(res["rows"][0]["tray"]["casts_outside_round"], 1)

    def test_without_tray_drops_nothing_binds_and_the_reason_is_stored(self):
        res = uc.adjudicate("s", self.peaks, self.lu, ROUNDS, "round-test",
                            tray_reason="tray_drops_stale")
        own = [r for r in res["rows"] if r.get("class") == "own"]
        self.assertTrue(all(r["tray_witness"] is None for r in own))
        self.assertEqual({r["tray_witness_reason"] for r in own}, {"tray_drops_stale"})
        self.assertFalse(any(r["kind"] == "missed_line" for r in res["rows"]))
        self.assertEqual(res["rows"][0]["tray"]["reason"], "tray_drops_stale")

    def test_without_the_players_agent_no_cast_is_missed(self):
        res = uc.adjudicate("s", self.peaks, None, ROUNDS, "round-test", tray_drops=self.casts)
        self.assertEqual(res["rows"][0]["tray"], {"bound": False, "reason": "no_player_agent",
                                                  "x_drops": 4, "player_x_casts": 3,
                                                  "casts_outside_round": 0,
                                                  "window_s": [-1.5, 1.5]})
        self.assertEqual(res["rows"][0]["missed_lines"], 0)

    def test_the_tray_owner_decides_which_drops_are_the_players_casts(self):
        stored = [{"kind": "coverage"},
                  {"kind": "drop", "t_ms": 50000.0, "slot": "X", "from": 1.0, "to": 0.0,
                   "suspect": False, "forced": False, "cooccur": False, "across_gap": False,
                   "player_cast": False, "reason": "stale"},
                  {"kind": "drop", "t_ms": 65000.0, "slot": "X", "from": 1.0, "to": 0.0,
                   "suspect": False, "forced": False, "cooccur": False, "across_gap": False,
                   "player_cast": True, "reason": None},
                  {"kind": "drop", "t_ms": 40000.0, "slot": "E", "from": 1.0, "to": 0.0,
                   "suspect": False, "forced": False, "cooccur": False, "across_gap": False,
                   "player_cast": True, "reason": None}]
        got = uc.player_x_drops(stored, lambda t: "round_live", ROUNDS, [60000.0])
        # The owner, not the stored flag: 50 s is a cast, 65 s falls after the death,
        # and the E drop is not the ultimate.
        self.assertEqual([(r["t_ms"], r["player_cast"], r["reason"]) for r in got],
                         [(50000.0, True, None), (65000.0, False, "after_player_death")])


class BurstTests(unittest.TestCase):
    """Three or more selections within BURST_S are one sound."""

    def setUp(self):
        self.lu = _lineup("s", ALLY, ENEMY)

    def test_a_weak_burst_is_refused_whole_and_kept_as_evidence(self):
        res = uc.adjudicate("s", _stored(_peak(50.0, "Jett", "ally", 0.06),
                                         _peak(50.8, "Reyna", "enemy", 0.05),
                                         _peak(51.9, "Killjoy", "ally", 0.07)),
                            self.lu, ROUNDS, "round-test")
        rows = {r["template"]: r for r in res["rows"][1:]}
        self.assertEqual({r["kind"] for r in rows.values()}, {"refusal"})
        self.assertEqual(rows["Jett_ult_ally"]["reason"], "burst")
        self.assertEqual(rows["Jett_ult_ally"]["class"], "possible")
        self.assertEqual(rows["Jett_ult_ally"]["burst"], {"n": 3, "best_score": 0.07, "t0_s": 50.0})
        # The impossible row keeps the lineup's reason; the burst is beside it.
        self.assertEqual(rows["Killjoy_ult_ally"]["reason"], "agent_not_on_ally_side")
        self.assertTrue(all(c["agent"] is None for c in res["claims"]))
        cov = res["rows"][0]
        self.assertEqual(cov["burst"]["refused"], 2)
        self.assertEqual(cov["refusal_reasons"], {"burst": 2, "impossible": 1})
        self.assertEqual(validate_event_rows(res["events"]), [])

    def test_a_strong_line_stands_and_its_crosstalk_is_refused(self):
        res = uc.adjudicate("s", _stored(_peak(50.0, "Jett", "ally", 0.30),
                                         _peak(50.5, "Reyna", "enemy", 0.05),
                                         _peak(51.0, "Viper", "enemy", 0.06)),
                            self.lu, ROUNDS, "round-test")
        kinds = {r["template"]: (r["kind"], r.get("reason")) for r in res["rows"][1:]}
        self.assertEqual(kinds, {"Jett_ult_ally": ("cast", None),
                                 "Reyna_ult_enemy": ("refusal", "burst"),
                                 "Viper_ult_enemy": ("refusal", "burst")})

    def test_a_pair_is_no_burst(self):
        res = uc.adjudicate("s", _stored(_peak(50.0, "Jett", "ally", 0.05),
                                         _peak(51.0, "Reyna", "enemy", 0.05),
                                         _peak(53.5, "Viper", "enemy", 0.05)),
                            self.lu, ROUNDS, "round-test")
        self.assertEqual({r["kind"] for r in res["rows"][1:]}, {"cast"})
        self.assertTrue(all(r["burst"] is None for r in res["rows"][1:]))

    def test_bursts_chain_within_the_span(self):
        got = uc.burst_of([1.0, 2.0, 3.0, 4.5, 6.0, 20.0], [0.1, 0.2, 0.3, 0.4, 0.5, 0.9])
        self.assertEqual([None if b is None else b["n"] for b in got], [4, 4, 4, 4, None, None])
        self.assertEqual(got[0]["best_score"], 0.4)  # 6.0 s has one neighbour: no burst


def _death(t_ms, weapon, killer, side, same_side=False, status="resolved"):
    """One stored `death_verdict`: `side` is the victim's."""
    return {"kind": "death_verdict", "death_id": f"death:s:{int(t_ms)}:0", "t_ms": t_ms,
            "weapon": weapon, "killer": killer, "side": side, "same_side": same_side,
            "weapon_evidence": {"status": status},
            "death_adjudication_version": "death-test"}


class WitnessTests(unittest.TestCase):
    """Peaks under the threshold stand only with an independent witness."""

    def setUp(self):
        self.lu = _lineup("s", ALLY, ENEMY)            # the player is Sova

    def _rows(self, res):
        return {r["template"]: r for r in res["rows"][1:] if r["kind"] == "cast"}

    def test_an_ult_kill_witnesses_the_best_earlier_peak_of_its_round(self):
        res = uc.adjudicate("s", _stored(_peak(40.0, "Jett", "ally", 0.035),
                                         _peak(45.0, "Jett", "ally", 0.032),
                                         _peak(62.0, "Jett", "ally", 0.04),     # after the kill
                                         _peak(120.0, "Jett", "ally", 0.04)),   # round 2
                            self.lu, ROUNDS, "round-test",
                            deaths=[_death(60000.0, "Blade Storm", "Jett", "enemy")])
        casts = [r for r in res["rows"][1:] if r["kind"] == "cast"]
        self.assertEqual([r["t_s"] for r in casts], [40.0])
        r = casts[0]
        self.assertEqual((r["selected_by"], r["agent"], r["side"]), ("witness", "Jett", "ally"))
        self.assertEqual(r["witness"]["kind"], "ult_kill")
        self.assertEqual(r["witness"]["lead_s"], 20.0)
        self.assertEqual(r["rests_on"], [{"stream": "death", "owner": "adjudication.death",
                                          "death_id": "death:s:60000:0", "version": "death-test"}])
        claim = next(c for c in res["claims"] if c["entity_id"] == r["entity_id"])
        self.assertIn("death:s:60000:0:killer", claim["depends_on"])
        self.assertEqual(claim["evidence"]["selected_by"], "witness")
        self.assertEqual(res["rows"][0]["witness"]["ult_kill_accepted"], 1)
        self.assertEqual(validate_event_rows(res["events"]), [])

    def test_a_revive_witnesses_its_own_side(self):
        res = uc.adjudicate("s", _stored(_peak(59.8, "Sage", "ally", 0.035)), self.lu, ROUNDS,
                            "round-test",
                            deaths=[_death(60000.0, "Resurrection", "Sage", "ally", same_side=True)])
        self.assertEqual(self._rows(res)["Sage_ult_ally"]["witness"]["lead_s"], 0.2)

    def test_no_witness_below_the_floor_or_beside_a_standing_cast(self):
        deaths = [_death(60000.0, "Blade Storm", "Jett", "enemy")]
        res = uc.adjudicate("s", _stored(_peak(40.0, "Jett", "ally", uc.WITNESS_FLOOR - 0.001)),
                            self.lu, ROUNDS, "round-test", deaths=deaths)
        self.assertEqual(self._rows(res), {})
        self.assertEqual(res["rows"][0]["witness"]["ult_kill_below_floor"], 1)
        res = uc.adjudicate("s", _stored(_peak(30.0, "Jett", "ally", 0.2),
                                         _peak(40.0, "Jett", "ally", 0.04)),
                            self.lu, ROUNDS, "round-test", deaths=deaths)
        self.assertEqual([r["t_s"] for r in res["rows"][1:] if r["kind"] == "cast"], [30.0])
        self.assertEqual(res["rows"][0]["witness"]["ult_kill_explained"], 1)

    def test_a_witness_names_no_agent_the_lineup_rules_out(self):
        res = uc.adjudicate("s", _stored(_peak(40.0, "Raze", "enemy", 0.04)), self.lu, ROUNDS,
                            "round-test", deaths=[_death(60000.0, "Showstopper", "Raze", "ally")])
        self.assertEqual(self._rows(res), {})
        self.assertEqual(res["rows"][0]["witness"]["ult_kill_impossible"], 1)

    def test_an_icon_another_agent_is_named_for_witnesses_nothing(self):
        kills, skipped = uc.ult_kill_witnesses(
            [_death(60000.0, "Blade Storm", "Reyna", "enemy"),
             _death(61000.0, "NULL/cmd", "KAY/O", "ally", same_side=True),
             _death(62000.0, "Vandal", "Jett", "enemy"),
             _death(63000.0, "Blade Storm", None, "enemy", status="refused")], ROUNDS)
        self.assertEqual(kills, [])
        self.assertEqual(skipped, {"actor_named_another_agent": 1, "icon_names_the_revived": 1,
                                   "icon_unresolved": 1})

    def test_a_witness_reinstates_a_peak_a_burst_refused(self):
        res = uc.adjudicate("s", _stored(_peak(50.0, "Jett", "ally", 0.06),
                                         _peak(50.8, "Reyna", "enemy", 0.05),
                                         _peak(51.0, "Viper", "enemy", 0.05)),
                            self.lu, ROUNDS, "round-test",
                            deaths=[_death(60000.0, "Blade Storm", "Jett", "enemy")])
        r = self._rows(res)["Jett_ult_ally"]
        self.assertTrue(r["burst_refusal_overridden"])
        self.assertEqual(r["selected_by"], "witness")
        self.assertEqual(len(res["rows"]) - 1, 3)    # one row per entity

    def test_the_players_x_cast_witnesses_its_own_line(self):
        res = uc.adjudicate("s", _stored(_peak(69.6, "Sova", "ally", 0.035)), self.lu, ROUNDS,
                            "round-test", tray_drops=[_cast(70000.0)])
        r = self._rows(res)["Sova_ult_ally"]
        self.assertEqual(r["witness"], {"kind": "tray_x_cast", "cast_t_ms": 70000.0, "dt_s": -0.4})
        self.assertEqual(r["tray_witness"], {"dt_s": -0.4, "cast_t_ms": 70000.0})
        self.assertEqual(r["rests_on"][0]["stream"], "tray_drop")
        self.assertEqual(res["rows"][0]["missed_lines"], 0)
        self.assertEqual(res["rows"][0]["witness"]["tray_accepted"], 1)


if __name__ == "__main__":
    unittest.main()
