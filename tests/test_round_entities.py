"""Session round lifetimes from stored ally icon events."""
import unittest

from reticle.round_entities import ROUND_ENTITY_VERSION, session_lifetimes


def _frame(i, t, drawn=True, me=(100.0, 100.0, 10)):
    return {"kind": "frame", "session_id": "s", "frame_idx": i, "t_ms": t,
            "widget_drawn": drawn, "icons": 0, "self": list(me) if me else None}


def _icon(i, t, x, y=50.0, reason=None, comp=(1.0,)):
    return {"kind": "icon", "session_id": "s", "frame_idx": i, "t_ms": t, "index": 0,
            "observation_key": f"s:{i}:{x}", "cx": x, "cy": y, "r": 8,
            "reason": reason, "composition": list(comp) if comp else None}


ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 1000.0},
          {"round_no": 2, "t_start_ms": 1000.0, "t_end_ms": 2000.0}]


class SessionLifetimeTests(unittest.TestCase):
    def run_rows(self, events, roster=None):
        return session_lifetimes("s", events, ROUNDS, 1.0, roster)

    def test_one_walking_ally_is_one_entity_per_round(self):
        events = []
        for k, t in enumerate(range(0, 2000, 67)):
            events += [_frame(k, float(t)), _icon(k, float(t), 50.0 + k * 0.5)]
        rows = self.run_rows(events)
        allies = [r for r in rows if r["kind"] == "entity" and r["family"] == "ally"]
        self.assertEqual(sorted(r["round_no"] for r in allies), [1, 2])
        self.assertTrue(all(r["round_entity_version"] == ROUND_ENTITY_VERSION for r in rows))

    def test_an_interior_that_is_the_map_is_a_barrier_not_an_ally(self):
        events = [_frame(0, 0.0), _icon(0, 0.0, 50.0, reason="interior_is_map")]
        rows = self.run_rows(events)
        (obs,) = [r for r in rows if r["kind"] == "observation" and r["family"] != "self"]
        self.assertEqual(obs["family"], "barrier")

    def test_an_absent_widget_suspends_rather_than_ends(self):
        events = [_frame(0, 0.0), _icon(0, 0.0, 50.0),
                  _frame(1, 67.0, drawn=False, me=None),
                  _frame(2, 134.0), _icon(2, 134.0, 51.0)]
        rows = self.run_rows(events)
        allies = {r["entity_id"] for r in rows
                  if r["kind"] == "observation" and r["family"] == "ally"}
        self.assertEqual(len(allies), 1)
        self.assertEqual(rows[0]["absent_frames"], 1)

    def test_the_roster_count_marks_an_extra_ally(self):
        events = [_frame(0, 0.0), _icon(0, 0.0, 50.0), _icon(0, 0.0, 200.0)]
        events[2]["observation_key"] = "s:0:b"
        rows = self.run_rows(events, roster={"t_ms": [0.0], "alive_ally": [2]})
        marks = sorted(r["acquisition"] for r in rows
                       if r["kind"] == "observation" and r["family"] == "ally")
        self.assertEqual(marks, ["roster_count_conflict",
                                 "roster_slot_available_not_identity"])

    def test_track_segments_receive_adjudicated_agent_names(self):
        import numpy as np

        def _one_hot(i, w=0.9):
            v = np.full(4, (1.0 - w) / 3.0, dtype=np.float32)
            v[i] = w
            return v.tolist()

        gallery = {name: [np.eye(4, dtype=np.float32)[i]]
                   for i, name in enumerate(["Breach", "Deadlock", "Miks", "Reyna"])}
        lineup = {
            "sides": {
                "ally": [{"slot": i, "agent": a, "best_guess": a}
                         for i, a in enumerate(["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"])]
            },
            "player": {"agent": "Phoenix"},
        }
        events = [
            _frame(0, 0.0, me=(100.0, 100.0, 10)),
            _icon(0, 0.0, 50.0, comp=_one_hot(0)),
            _icon(0, 0.0, 200.0, reason="interior_is_map"),
            _frame(1, 67.0, me=(100.0, 100.0, 10)),
            _icon(1, 67.0, 50.5, comp=_one_hot(0)),
        ]
        events[2]["observation_key"] = "s:0:barrier"
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, lineup=lineup, gallery=gallery)
        ents = {r["family"]: r for r in rows if r["kind"] == "entity"}

        self.assertIn("ally", ents)
        self.assertEqual(ents["ally"]["agent"], "Breach")
        self.assertEqual(ents["ally"]["teammate_key"], "s:teammate:Breach")
        self.assertEqual(ents["ally"]["identity_status"], "resolved")
        self.assertEqual(ents["ally"]["identity_votes"], {"Breach": 2})

        self.assertIn("self", ents)
        self.assertEqual(ents["self"]["agent"], "Phoenix")
        self.assertEqual(ents["self"]["teammate_key"], "s:teammate:Phoenix")
        self.assertEqual(ents["self"]["identity_status"], "resolved")

        self.assertIn("barrier", ents)
        self.assertIsNone(ents["barrier"]["agent"])
        self.assertIsNone(ents["barrier"]["teammate_key"])
        self.assertEqual(ents["barrier"]["identity_status"], "abstained")
        self.assertEqual(ents["barrier"]["identity_reason"], "barrier")

    def test_a_death_binds_to_a_track_end_and_never_names_it(self):
        import numpy as np

        gallery = {name: [np.eye(4, dtype=np.float32)[i]]
                   for i, name in enumerate(["Breach", "Deadlock", "Miks", "Reyna"])}
        lineup = {
            "sides": {
                "ally": [{"slot": i, "agent": a, "best_guess": a}
                         for i, a in enumerate(["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"])]
            },
            "player": {"agent": "Phoenix"},
        }
        # Track has no confident composition (e.g. comp is uniform noise, below margin)
        uniform_comp = [0.25, 0.25, 0.25, 0.25]
        events = [
            _frame(0, 0.0),
            _icon(0, 0.0, 50.0, comp=uniform_comp),
            _frame(1, 67.0),
            _icon(1, 67.0, 50.5, comp=uniform_comp),
        ]
        deaths = [{
            "kind": "death_verdict", "round_no": 1, "t_ms": 70.0, "side": "ally",
            "victim": "Reyna", "death_id": "death:s:70:0", "killer": "Jett", "weapon": "Vandal"
        }]
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, deaths=deaths, lineup=lineup, gallery=gallery)
        ents = {r["family"]: r for r in rows if r["kind"] == "entity"}

        self.assertIn("ally", ents)
        # The killfeed stays the independent check of portrait names.
        self.assertIsNone(ents["ally"]["agent"])
        self.assertIsNone(ents["ally"]["teammate_key"])
        self.assertEqual(ents["ally"]["identity_status"], "abstained")
        self.assertEqual(ents["ally"]["death_id"], "death:s:70:0")
        self.assertEqual(ents["ally"]["end_reason"], "death")


    def test_a_segment_that_fits_no_teammate_is_refused(self):
        from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION
        names = ["Breach", "Deadlock", "Miks", "Reyna"]
        refs = {"version": "t", "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
                "margin_min": 0.5, "variance": {"g": [1.0]},
                "agents": {n: {"g": [float(i)]} for i, n in enumerate(names)},
                "teammate_fit": {"version": "t", "fit_max": 2.0}}
        lineup = {"sides": {"ally": [{"slot": i, "agent": a, "best_guess": a} for i, a in
                                     enumerate(["Phoenix"] + names)]},
                  "player": {"agent": "Phoenix"}}
        events = []
        for k in range(3):
            icon = _icon(k, 67.0 * k, 50.0 + k * 0.5)
            icon.update(portrait_features={"g": [9.0]},
                        portrait_features_version=ALLY_PORTRAIT_FEATURES_VERSION)
            events += [_frame(k, 67.0 * k), icon]
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, lineup=lineup,
                                 gallery={n: [] for n in names}, references=refs)
        (ally,) = [r for r in rows if r["kind"] == "entity" and r["family"] == "ally"]
        self.assertIsNone(ally["agent"])
        self.assertTrue(ally["identity_reason"].startswith("not_a_teammate"))
        self.assertEqual(ally["identity_evidence"]["fit"], 36.0)

    def test_a_segment_whose_best_teammate_changes_is_split_and_named_by_piece(self):
        from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION
        names = ["Breach", "Deadlock", "Miks", "Reyna"]
        refs = {"version": "t", "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
                "margin_min": 0.5, "variance": {"g": [1.0]},
                "agents": {n: {"g": [float(i)]} for i, n in enumerate(names)}}
        lineup = {"sides": {"ally": [{"slot": i, "agent": a, "best_guess": a} for i, a in
                                     enumerate(["Phoenix"] + names)]},
                  "player": {"agent": "Phoenix"}}
        events = []
        for k in range(12):
            icon = _icon(k, 67.0 * k, 50.0 + k * 0.5)
            icon.update(portrait_features={"g": [0.0 if k < 6 else 3.0]},
                        portrait_features_version=ALLY_PORTRAIT_FEATURES_VERSION)
            events += [_frame(k, 67.0 * k), icon]
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, lineup=lineup,
                                 gallery={n: [] for n in names}, references=refs)
        allies = sorted((r for r in rows if r["kind"] == "entity" and r["family"] == "ally"),
                        key=lambda r: r["piece_index"])
        self.assertEqual([r["agent"] for r in allies], ["Breach", "Reyna"])
        self.assertEqual(allies[0]["segment_id"], allies[1]["segment_id"])
        self.assertEqual(allies[0]["end_reason"], "split: best teammate changed")
        obs = [r for r in rows if r["kind"] == "observation" and r["family"] == "ally"]
        self.assertEqual({o["entity_id"] for o in obs}, {r["id"] for r in allies})

if __name__ == "__main__":
    unittest.main()


class DeadIntervalTests(unittest.TestCase):
    def _death(self, t, victim, **kw):
        return {"kind": "death_verdict", "side": "ally", "round_no": 1, "t_ms": t,
                "victim": victim, **kw}

    def test_a_death_bars_until_the_revive_entry_that_names_the_victim(self):
        from reticle.round_entities import ally_dead_intervals
        deaths = [self._death(1000.0, "Sage"), self._death(9000.0, "Sage", is_revive=True),
                  self._death(2000.0, "Jett"), self._death(3000.0, "Phoenix", is_second_life=True)]
        out = ally_dead_intervals(deaths, {1: 20000.0}, [], [])
        self.assertEqual([s[:2] for s in out[1]["Sage"]], [(1700.0, 8300.0)])
        self.assertEqual([s[:2] for s in out[1]["Jett"]], [(2700.0, 20000.0)])
        self.assertNotIn("Phoenix", out[1])

    def test_an_unexplained_roster_rise_ends_the_interval(self):
        from reticle.round_entities import ally_dead_intervals
        out = ally_dead_intervals([self._death(1000.0, "Clove")], {1: 20000.0},
                             [0.0, 1500.0, 6000.0], [5, 4, 5])
        self.assertEqual(out[1]["Clove"][0][:2], (1700.0, 5300.0))
        self.assertIn("roster rise", out[1]["Clove"][0][2])


class DeathBindingTests(unittest.TestCase):
    """`death_binding_refusal`: which ally-side death may end which entity."""

    def _death(self, t, victim, **kw):
        return {"kind": "death_verdict", "side": "ally", "round_no": 1, "t_ms": t,
                "victim": victim, "death_id": f"death:s:{int(t)}:0", **kw}

    def _rows(self, icons, deaths, roster=None):
        events = []
        for k, t in enumerate((0.0, 67.0, 134.0)):
            events.append(_frame(k, t))
            for x, why in icons:
                icon = _icon(k, t, x, reason=why)
                icon["observation_key"] = f"s:{k}:{x}"
                events.append(icon)
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, roster, deaths=deaths)
        return {r["family"]: r for r in rows if r["kind"] == "entity"}, rows[0]

    def test_a_barrier_takes_no_death_and_no_roster_drop(self):
        ents, _ = self._rows([(50.0, "interior_is_map")], [self._death(140.0, "Jett")],
                             roster={"t_ms": [0.0, 150.0], "alive_ally": [5, 4]})
        self.assertIsNone(ents["barrier"]["death_id"])
        self.assertNotEqual(ents["barrier"]["end_reason"], "death")

    def test_the_players_death_ends_the_self_entity_not_an_ally(self):
        ents, cov = self._rows([(50.0, None)],
                               [self._death(140.0, None, kf_player_death=True)])
        self.assertEqual(ents["self"]["death_id"], "death:s:140:0")
        self.assertIsNone(ents["ally"]["death_id"])
        self.assertEqual(cov["death_unbound"], {})

    def test_a_teammates_death_never_ends_the_self_entity(self):
        ents, _ = self._rows([], [self._death(140.0, "Jett")])
        self.assertIsNone(ents["self"]["death_id"])

    def test_revives_and_second_lives_end_no_one(self):
        from reticle.round_entities import death_binding_refusal
        ally = {"family": "ally"}
        self.assertEqual(death_binding_refusal(ally, self._death(0, "Sage", is_revive=True),
                                               player_agent="Skye", agent=None), "revive")
        me = {"family": "self"}
        self.assertEqual(death_binding_refusal(
            me, self._death(0, "Phoenix", kf_player_death=True, is_second_life=True),
            player_agent="Phoenix", agent=None), "second_life")

    def test_the_x_and_the_name_must_agree(self):
        from reticle.round_entities import death_binding_refusal
        ally = {"family": "ally"}
        far = self._death(0, "Jett", location=[100.0, 100.0])
        self.assertEqual(death_binding_refusal(ally, far, player_agent="Skye", agent=None,
                                               last_xy=(10.0, 10.0)), "death_x_elsewhere")
        self.assertEqual(death_binding_refusal(ally, self._death(0, "Jett"), player_agent="Skye",
                                               agent="Fade"), "victim_is_another_agent")
        self.assertIsNone(death_binding_refusal(ally, far, player_agent="Skye", agent="Jett",
                                                last_xy=(95.0, 100.0)))

    def test_an_ally_piece_seen_past_the_dead_icon_lag_is_not_the_victim(self):
        """bfad2778a372 R18: a Fade piece last seen 1.25 s after an unnamed
        death took it from the Chamber seen 2.2 s before."""
        from reticle.round_entities import death_binding_refusal
        from reticle.round_lifetimes import DEAD_ICON_LAG_MS
        d = self._death(1881500.0, None)
        late = {"family": "ally", "last_seen_ms": 1882750.0}
        early = {"family": "ally", "last_seen_ms": 1879333.0}
        self.assertLess(DEAD_ICON_LAG_MS, 1250.0)
        self.assertEqual(death_binding_refusal(late, d, player_agent="Skye", agent="Fade"),
                         "seen_after_death")
        self.assertIsNone(death_binding_refusal(early, d, player_agent="Skye", agent="Chamber"))
        # The self entity shows the spectated teammate after the player dies.
        me = {"family": "self", "last_seen_ms": 1890000.0}
        self.assertIsNone(death_binding_refusal(
            me, self._death(1881500.0, "Skye", kf_player_death=True),
            player_agent="Skye", agent=None))

    def test_a_revival_or_a_downed_kayo_outlives_the_lag(self):
        from reticle.round_entities import death_binding_refusal
        late = {"family": "ally", "last_seen_ms": 5000.0}
        jett = self._death(1000.0, "Jett")
        revive = self._death(3000.0, "Jett", is_revive=True)
        self.assertEqual(death_binding_refusal(late, jett, player_agent="Skye", agent=None),
                         "seen_after_death")
        self.assertIsNone(death_binding_refusal(late, jett, player_agent="Skye", agent=None,
                                                deaths=[jett, revive]))
        # A revive after the sighting explains nothing.
        self.assertEqual(death_binding_refusal(
            late, jett, player_agent="Skye", agent=None,
            deaths=[jett, self._death(6000.0, "Jett", is_revive=True)]), "seen_after_death")
        self.assertIsNone(death_binding_refusal(late, self._death(1000.0, "KAY/O"),
                                                player_agent="Skye", agent=None))

    def test_the_late_piece_leaves_the_death_to_the_earlier_one(self):
        """The R18 shape end to end: a piece last seen 1.2 s after an unnamed
        death is nearer in time than one seen 1.3 s before it, and the earlier
        one takes the death."""
        events = []
        for k, t in enumerate(range(0, 3501, 100)):
            events.append(_frame(k, float(t)))
            xs = [50.0] + ([200.0] if t <= 1000 else [])
            for x in xs:
                icon = _icon(k, float(t), x)
                icon["observation_key"] = f"s:{k}:{x}"
                events.append(icon)
        d = self._death(2300.0, None)
        rounds = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 10000.0}]
        rows = session_lifetimes("s", events, rounds, 1.0, None, deaths=[d])
        bound = {r["last_seen_ms"]: r["death_id"] for r in rows
                 if r["kind"] == "entity" and r["family"] == "ally"}
        self.assertEqual(bound, {1000.0: d["death_id"], 3500.0: None})

    def test_a_death_can_end_a_piece_before_the_segments_last(self):
        """5822b6646448 R8: Omen's piece P6 takes Omen's death; the stray
        piece after it keeps the segment and records the dispute."""
        from reticle.round_entities import _piece_bodies
        v = {"agent": None, "status": "abstained", "reason": None, "votes": {},
             "evidence_sum": {}, "reference_source": None, "gap": None, "fit": None,
             "exact": False}
        pieces = {"S/P0": {"t": [1000.0, 1100.0]}, "S/P1": {"t": [3100.0]}}
        verdicts = {"S/P0": {**v, "agent": "Omen", "status": "resolved"}, "S/P1": v}
        body = {"id": "S", "end_ms": None, "death_id": None, "end_reason": "x",
                "right_censored_at_ms": 3100.0}
        d = {"death_id": "death:s:1400:0", "t_ms": 1400.0}
        rows = _piece_bodies(body, pieces, verdicts, ["S/P0", "S/P1"], "s", {"S/P0": d})
        self.assertEqual((rows[0]["death_id"], rows[0]["end_reason"], rows[0]["end_ms"]),
                         ("death:s:1400:0", "death", 1400.0))
        self.assertIsNone(rows[1]["death_id"])
        self.assertEqual(rows[1]["after_piece_death"], "death:s:1400:0")

    def test_a_drop_beside_the_players_death_ends_no_ally(self):
        from reticle.round_entities import drop_binding_refusal
        self.assertEqual(drop_binding_refusal({"family": "ally"}, 1000.0, [900.0]),
                         "drop_is_the_player")
        self.assertIsNone(drop_binding_refusal({"family": "self"}, 1000.0, [900.0]))
        self.assertEqual(drop_binding_refusal({"family": "self"}, 1000.0, []),
                         "drop_is_a_teammate")
        self.assertEqual(drop_binding_refusal({"family": "barrier"}, 1000.0, []),
                         "barrier_is_not_a_player")


class BindingRuleTests(unittest.TestCase):
    """round-entity-0.14.0: inner pieces under a bound segment."""

    NAMES = ["Breach", "Deadlock", "Miks", "Reyna"]

    def _run(self, spans, deaths, t_end=5000.0):
        """`spans` lists `(t_ms, feature)` sightings of one icon at x=50; the
        feature 0.0 reads as Breach, 3.0 as Reyna. Frames between sightings
        draw the widget with no ally icon."""
        from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION
        refs = {"version": "t", "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
                "margin_min": 0.5, "variance": {"g": [1.0]},
                "agents": {n: {"g": [float(i)]} for i, n in enumerate(self.NAMES)}}
        lineup = {"sides": {"ally": [{"slot": i, "agent": a, "best_guess": a} for i, a in
                                     enumerate(["Phoenix"] + self.NAMES)]},
                  "player": {"agent": "Phoenix"}}
        seen = dict(spans)
        events = []
        for k, t in enumerate(sorted(set(seen) | set(range(0, int(t_end), 67)))):
            events.append(_frame(k, float(t)))
            if t in seen:
                icon = _icon(k, float(t), 50.0)
                icon.update(portrait_features={"g": [seen[t]]},
                            portrait_features_version=ALLY_PORTRAIT_FEATURES_VERSION)
                events.append(icon)
        rounds = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": t_end}]
        rows = session_lifetimes("s", events, rounds, 1.0, lineup=lineup,
                                 gallery={n: [] for n in self.NAMES}, references=refs,
                                 deaths=deaths)
        return sorted((r for r in rows if r["kind"] == "entity" and r["family"] == "ally"),
                      key=lambda r: r["first_seen_ms"])

    def _death(self, t, victim, **kw):
        return {"kind": "death_verdict", "side": "ally", "round_no": 1, "t_ms": t,
                "victim": victim, "death_id": f"death:s:{int(t)}:0", **kw}

    def test_an_inner_piece_takes_its_death_under_a_bound_segment(self):
        """c40d950031bb 872.0 s: Killjoy's inner piece, whose segment's end
        took Jett's later death, takes Killjoy's."""
        spans = [(67 * k, 0.0 if k < 6 else 3.0) for k in range(12)]
        breach, reyna = self._death(360.0, "Breach"), self._death(800.0, "Reyna")
        allies = self._run(spans, [breach, reyna], t_end=1000.0)
        self.assertEqual([(r["agent"], r["death_id"]) for r in allies],
                         [("Breach", breach["death_id"]), ("Reyna", reyna["death_id"])])

    def test_a_revive_stays_unbound(self):
        """bdfdcf009dba 1310.0 s and ff636d173b07 525.0 s: a revive entry ends
        no piece, inner or cut."""
        spans = [(67 * k, 0.0 if k < 6 else 3.0) for k in range(12)]
        revive = self._death(360.0, "Breach", is_revive=True)
        reyna = self._death(800.0, "Reyna")
        allies = self._run(spans, [revive, reyna], t_end=1000.0)
        self.assertNotIn(revive["death_id"], [r["death_id"] for r in allies])
        self.assertEqual(allies[-1]["death_id"], reyna["death_id"])
