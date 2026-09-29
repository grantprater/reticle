import unittest

from reticle.minimap_lifecycle import Lifecycle, Witnesses, matching_events


def obs(tid=1, x=10, role="ally", lit=10):
    return {"track_id": tid, "role": role, "x": x, "y": 10,
            "position_state": "observed", "light_support": {"known": 100, "lit": lit}}


def frame(t, observations, drawn=True):
    return {"t_ms": t, "widget": "drawn" if drawn else "not_drawn",
            "observations": observations, "light_budget": {"known": 1000, "lit": 200}}


def teleport(**extra):
    event = {"id": "teleport-1", "kind": "teleport", "role": "ally",
             "t_start_ms": 50, "t_end_ms": 150, "available_t_ms": 100,
             "x": 200, "y": 10, "radius_px": 3, "legal": True,
             "predecessor": "ally:1", "channels": ["icon", "viewcone", "audio"],
             "evidence_refs": ["icon:100", "cone:100", "audio:95"]}
    return dict(event, **extra)


class LifecycleTests(unittest.TestCase):
    def test_initial_window_is_censored_not_birth(self):
        row = Lifecycle().step(frame(0, [obs(lit=0)]))[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["state"], "left_censored")
        self.assertIsNone(row["origin_interval_ms"])

    def test_new_dark_nonping_quarantined_without_destroying_raw(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        raw = obs(2, 200, lit=0)
        result = lifecycle.step(frame(100, [raw]))[0]
        self.assertFalse(result["eligible"])
        self.assertEqual(result["state"], "unlit_unexplained_appearance")
        self.assertNotIn("eligible", raw)
        # Repeated detections do not independently establish an origin.
        self.assertFalse(lifecycle.step(frame(200, [raw]))[0]["eligible"])

    def test_existing_entity_can_persist_in_darkness(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        row = lifecycle.step(frame(100, [obs(x=12, lit=0)]))[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["state"], "continuation")
        self.assertIsNotNone(row["conflict"])

    def test_confirmed_ping_can_start_in_darkness(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, []))
        event = teleport(kind="ping", role="ping", predecessor=None, channels=["ping"])
        row = lifecycle.step(frame(100, [obs(2, 200, "ping", 0)]), [event])[0]
        self.assertTrue(row["eligible"])
        self.assertIsNone(row["conflict"])

    def test_teleport_relocates_existing_entity(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        row = lifecycle.step(frame(100, [obs(2, 200)]), [teleport()])[0]
        self.assertEqual(row["entity_id"], "ally:1")
        self.assertEqual(row["state"], "relocation")
        self.assertIsNone(row["origin_interval_ms"])

    def test_audio_alone_or_future_or_distant_cast_cannot_license_jump(self):
        for event in [teleport(channels=["audio"]), teleport(available_t_ms=101),
                      teleport(x=300), teleport(legal=None), teleport(predecessor="ally:99")]:
            lifecycle = Lifecycle()
            lifecycle.step(frame(0, [obs()]))
            self.assertFalse(lifecycle.step(frame(100, [obs(2, 200)]), [event])[0]["eligible"])

    def test_verified_origin_in_darkness_flags_lighting(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, []))
        cast = teleport(kind="cast", role="ability", predecessor=None)
        row = lifecycle.step(frame(100, [obs(2, 200, "ability", 0)]), [cast])[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["conflict"], "origin_vs_lighting")

    def test_a_missing_widget_suspends_identity_rather_than_ending_it(self):
        # The M key and the death screen take the widget away for 5% of a
        # session's frames. Wiping identity on each of them turned every
        # reappearance into a birth -- so the absence is a missing OBSERVATION,
        # and continuity stays testable across it while the gap budget lasts.
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        lifecycle.step(frame(100, [], False))
        row = lifecycle.step(frame(200, [obs(1, 12)]))[0]
        self.assertEqual(row["state"], "continuation")
        self.assertEqual(row["entity_id"], "ally:1")

    def test_an_absence_does_not_excuse_an_appearance_it_cannot_explain(self):
        # ...and the other half: within the budget the walk allowance still has
        # to reach. 200 px in 200 ms is not a walk, so this is quarantined
        # rather than excused as a censored boundary.
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        lifecycle.step(frame(100, [], False))
        row = lifecycle.step(frame(200, [obs(2, 200)]))[0]
        self.assertEqual(row["state"], "unexplained_appearance")
        self.assertFalse(row["eligible"])

    def test_an_absence_past_the_budget_is_a_censored_boundary(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        lifecycle.step(frame(600, [], False))
        row = lifecycle.step(frame(700, [obs(2, 200)]))[0]
        self.assertEqual(row["state"], "left_censored")
        self.assertTrue(row["eligible"])

    def test_the_fit_error_does_not_fragment_a_standing_entity(self):
        # The measured centre error of an icon fit is +/-2 px per observation
        # (`track.FIT_ERR_PX`); the ceiling this module used to apply was
        # sqrt(2) for the pair, so a standing player's own fit jitter read as
        # an unexplained appearance.
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        row = lifecycle.step(frame(17, [obs(1, 13)]))[0]
        self.assertEqual(row["state"], "continuation")

    def test_no_light_budget_is_unknown_not_unlit(self):
        f = frame(0, [obs(lit=0)])
        f["light_budget"]["lit"] = 0
        self.assertEqual(Lifecycle().step(f)[0]["light_state"], "unknown")

    def test_lifecycle_events_emits_valid_causal_origin_events(self):
        from reticle.events import validate_event_rows
        lifecycle = Lifecycle()
        # Step 0: left_censored at boundary
        lifecycle.step(frame(0, [obs(tid=1, x=10)]))
        # Step 1: continuation
        lifecycle.step(frame(17, [obs(tid=1, x=10)]))
        # Step 2: new entity appearance (unexplained)
        lifecycle.step(frame(34, [obs(tid=1, x=10), obs(tid=2, x=80)]))

        events = lifecycle.events("session-lifecycle-test", transitions_only=True)
        self.assertEqual(len(events), 2)
        errors = validate_event_rows(events)
        self.assertEqual(errors, [])

        e0, e1 = events[0], events[1]
        self.assertEqual(e0["event_kind"], "causal_origin")
        self.assertEqual(e0["origin_kind"], "left_censored")
        self.assertEqual(e0["entity_id"], "lifecycle:ally:ally:1")
        self.assertEqual(e0["t_ms"], 0.0)

        self.assertEqual(e1["origin_kind"], "unexplained_appearance")
        self.assertEqual(e1["entity_id"], "lifecycle:ally:ally:2")
        self.assertEqual(e1["t_ms"], 34.0)


class _Interval:
    """A stand-in for `adjudication.spectate.DeadInterval`."""

    def __init__(self, t0, t1, switch):
        self.t0, self.t1, self.switch = t0, t1, switch

    def holds(self, t):
        return self.t0 <= t < self.t1

    def spectated(self, t):
        return self.switch is not None and self.switch <= t < self.t1

    def row(self):
        return {"t0_ms": self.t0, "t1_ms": self.t1, "switch_ms": self.switch,
                "rests_on": "killfeed_death"}


class _Dead:
    def __init__(self, *intervals):
        self.intervals = intervals

    def at(self, t):
        return next((iv for iv in self.intervals if iv.holds(t)), None)


def me(tid=1, x=10, lit=10):
    return obs(tid, x, "self", lit)


class RefusalHealsTests(unittest.TestCase):
    """minimap-lifecycle-0.3.0: E8's structural faults and second witnesses."""

    def test_a_role_with_no_live_anchor_is_its_own_boundary(self):
        # The self anchor used to keep the boundary shut for a lost ally.
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [me(), obs(2, 100)]))
        lifecycle.step(frame(400, [me(1, 12)]))
        row = [r for r in lifecycle.step(frame(700, [me(1, 12), obs(3, 200)]))
               if r["role"] == "ally"][0]
        self.assertTrue(row["eligible"])
        self.assertEqual((row["state"], row["boundary"]), ("left_censored", "role"))

    def test_a_refusal_names_its_rule_and_persists_by_name(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs()]))
        first = lifecycle.step(frame(100, [obs(1, 11), obs(2, 200)]))[1]
        self.assertEqual(first["reason_code"], "beyond_reach")
        self.assertIn("beyond_reach", first["reason"])
        self.assertGreater(first["nearest_anchor"]["excess"], 0)
        later = lifecycle.step(frame(200, [obs(1, 12), obs(2, 201)]))[1]
        self.assertEqual(later["reason_code"], "persisting:beyond_reach")

    def test_a_refused_key_cannot_take_a_continuing_neighbours_identity(self):
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs(1, 10)]))
        lifecycle.step(frame(100, [obs(1, 10), obs(2, 200)]))
        # Key 2 walks beside ally 1's anchor while ally 1 is still observed.
        rows = lifecycle.step(frame(200, [obs(1, 10), obs(2, 14)]))
        self.assertEqual(rows[0]["entity_id"], "ally:1")
        self.assertNotEqual(rows[1]["entity_id"], "ally:1")
        self.assertFalse(rows[1]["eligible"])

    def test_the_roster_admits_an_ally_every_observed_ally_fits(self):
        w = Witnesses(roster=[(0, 5)])
        lifecycle = Lifecycle(witnesses=w)
        lifecycle.step(frame(0, [me(), obs(1, 10)]))
        row = lifecycle.step(frame(100, [me(1, 12), obs(1, 11), obs(2, 200)]))[2]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["state"], "corroborated_appearance")
        self.assertEqual(row["refused_as"], "unexplained_appearance")
        self.assertEqual(row["admitted_by"]["rule"], "roster_capacity")
        self.assertEqual(row["rests_on"], ["alive-count"])
        # Admitted, it anchors: the next frame continues it.
        nxt = lifecycle.step(frame(200, [me(1, 12), obs(1, 11), obs(2, 201)]))[2]
        self.assertEqual(nxt["state"], "continuation")

    def test_more_allies_than_the_roster_licenses_admits_none(self):
        w = Witnesses(roster=[(0, 2)])          # the player and one ally
        lifecycle = Lifecycle(witnesses=w)
        lifecycle.step(frame(0, [me(), obs(1, 10)]))
        row = lifecycle.step(frame(100, [me(1, 12), obs(1, 11), obs(2, 200)]))[2]
        self.assertFalse(row["eligible"])
        self.assertEqual(row["reason_code"], "over_capacity")

    def test_the_roster_vetoes_a_role_boundary_over_its_count(self):
        w = Witnesses(roster=[(0, 1)])          # the player alone
        lifecycle = Lifecycle(witnesses=w)
        lifecycle.step(frame(0, [me()]))
        row = lifecycle.step(frame(100, [me(1, 12), obs(5, 200)]))[1]
        self.assertFalse(row["eligible"])
        self.assertEqual(row["refused_as"], "left_censored")
        self.assertEqual(row["reason_code"], "over_capacity")

    def test_an_unread_roster_or_an_unseen_player_admits_nothing(self):
        for w, selves in ((Witnesses(), True), (Witnesses(roster=[(0, 5)]), False)):
            lifecycle = Lifecycle(witnesses=w)
            lifecycle.step(frame(0, [me(), obs(1, 10)]))
            f = [obs(1, 11), obs(2, 200)] + ([me(1, 12)] if selves else [])
            row = [r for r in lifecycle.step(frame(100, f)) if r["observation_key"] == "ally:2"][0]
            self.assertFalse(row["eligible"])

    def test_the_players_state_decides_the_yellow_icon(self):
        dead = _Dead(_Interval(1000, 5000, 3000))
        lifecycle = Lifecycle(witnesses=Witnesses(dead=dead))
        lifecycle.step(frame(0, [me(), obs(1, 100)]))
        # Alive: a refit jump of the self icon is admitted, not quarantined.
        row = lifecycle.step(frame(100, [me(2, 60), obs(1, 100)]))[0]
        self.assertEqual((row["state"], row["admitted_by"]["rule"]),
                         ("corroborated_appearance", "player_alive"))
        # The death camera: not a live position.
        row = lifecycle.step(frame(2000, [me(2, 60), obs(1, 100)]))[0]
        self.assertFalse(row["eligible"])
        self.assertEqual((row["state"], row["reason_code"]), ("death_camera_view", "death_camera"))
        # Spectating: a teammate's cone, anchored apart from the player.
        row = lifecycle.step(frame(3100, [me(3, 100), obs(1, 100)]))[0]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["state"], "spectated_teammate")
        self.assertEqual(row["rests_on"], ["player-dead"])
        self.assertTrue(row["entity_id"].startswith("spectated:"))

    def test_the_player_never_continues_a_spectated_teammate(self):
        dead = _Dead(_Interval(0, 1000, 0))
        lifecycle = Lifecycle(witnesses=Witnesses(dead=dead))
        lifecycle.step(frame(0, [me(3, 100), obs(1, 50)]))
        row = lifecycle.step(frame(1000, [me(3, 101), obs(1, 50)]))[0]
        self.assertNotEqual(row["entity_id"], "spectated:self:3")
        self.assertNotEqual(row["state"], "continuation")

    def test_a_round_start_explains_its_capacity_and_waits_for_the_reset(self):
        from reticle.minimap_lifecycle import round_start_events
        events = round_start_events([{"round_no": 2, "t_start_ms": 1000.0}], 300, 300)
        lifecycle = Lifecycle()
        lifecycle.step(frame(0, [obs(1, 10)]))
        # Before the reset is observed the event is not available.
        early = lifecycle.step(frame(400, [obs(1, 11), obs(2, 200)]), events)[1]
        self.assertFalse(early["eligible"])
        rows = lifecycle.step(frame(1000, [obs(1, 12)] + [obs(k, 40 * k) for k in range(2, 7)]),
                              events)
        explained = [r for r in rows if r["state"] == "explained_origin"]
        self.assertEqual(len(explained), 4)
        self.assertTrue(all(r["origin_event_id"] == "round_start:2:ally" for r in explained))

    def test_a_revive_explains_one_ally(self):
        from reticle.minimap_lifecycle import revive_events
        deaths = [{"kind": "death_verdict", "is_revive": True, "side": "ally",
                   "t_ms": 1000.0, "death_id": "death:s:1000:0"},
                  {"kind": "death_verdict", "is_revive": False, "side": "ally",
                   "t_ms": 900.0, "death_id": "death:s:900:0"}]
        events = revive_events(deaths, 300, 300)
        self.assertEqual(len(events), 1)
        lifecycle = Lifecycle()
        lifecycle.step(frame(900, [obs(1, 10)]))
        rows = lifecycle.step(frame(1100, [obs(1, 11), obs(2, 200), obs(3, 250)]), events)
        self.assertEqual([r["state"] for r in rows[1:]],
                         ["explained_origin", "unexplained_appearance"])

    def test_the_stored_record_carries_the_rule_and_its_evidence(self):
        from reticle.minimap_lifecycle import adjudication_record
        lifecycle = Lifecycle(witnesses=Witnesses(roster=[(0, 5)]))
        lifecycle.step(frame(0, [me(), obs(1, 10)]))
        row = lifecycle.step(frame(100, [me(1, 12), obs(1, 11), obs(2, 200)]))[2]
        rec = adjudication_record(row)
        self.assertEqual(rec["key"], "ally:2")
        for k in ("state", "eligible", "boundary", "reason_code", "reason", "nearest_anchor",
                  "refused_as", "admitted_by", "rests_on", "origin_event_id",
                  "alternatives", "light_state", "conflict", "entity_id"):
            self.assertIn(k, rec)
        self.assertEqual(rec["reason_code"], "beyond_reach")
        self.assertEqual(rec["admitted_by"]["roster_reads"], [[0.0, 5]])

    def test_new_states_are_valid_causal_origin_events(self):
        from reticle.events import validate_event_rows
        dead = _Dead(_Interval(50, 1000, 50))
        lifecycle = Lifecycle(witnesses=Witnesses(roster=[(0, 5)], dead=dead))
        lifecycle.step(frame(0, [me(), obs(1, 10)]))
        lifecycle.step(frame(40, [me(1, 11), obs(1, 11), obs(2, 200)]))
        lifecycle.step(frame(100, [me(1, 120), obs(1, 12), obs(2, 201)]))
        events = lifecycle.events("session-lifecycle-test", transitions_only=True)
        self.assertEqual(validate_event_rows(events), [])
        kinds = {e["origin_kind"] for e in events}
        self.assertIn("corroborated_appearance", kinds)
        self.assertIn("spectated_teammate", kinds)


if __name__ == "__main__":
    unittest.main()
