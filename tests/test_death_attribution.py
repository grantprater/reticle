"""Tests for death adjudication and victim attribution."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from reticle.adjudication.death import (
    DEATH_ADJUDICATION_VERSION,
    DeathVerdict,
    TeamRoster,
    RoundRosterSnapshot,
    LivingRosterTracker,
    build_round_roster_timeline,
    build_match_roster_timeline,
    adjudicate_death,
    adjudicate_round_deaths,
    attach_stored_killfeed_portraits,
    death_verdict_to_events,
    extract_minimap_death_marks,
    extract_killer_location,
    shrink_events,
    expand_events,
    detect_second_life_badge,
    classify_revive_icon,
    fit_arc,
)
from reticle.events import validate_event_rows


class DeathAttributionTests(unittest.TestCase):
    def test_stored_portraits_keep_refused_rivals_and_entry_boundaries(self):
        lineup = {"sides": {"ally": [
            {"agent": "Phoenix"}, {"agent": "Reyna"},
            {"agent": None, "best_guess": "Deadlock"},
            {"agent": "Raze"}, {"agent": "Miks"}]}}
        gallery = {"Phoenix": [np.array([1., 0., 0.])],
                   "Reyna": [np.array([0., 1., 0.])],
                   "Deadlock": [np.array([0., 0., 1.])],
                   "Raze": [np.array([0.5, 0.5, 0.])],
                   "Miks": [np.array([0.5, 0., 0.5])]}
        entries = [{"t_ms": 1000., "slot": 0, "side": "ally"},
                   {"t_ms": 2000., "slot": 1, "side": "ally"}]
        def observation(t, slot, comp):
            return {"kind": "portrait_observation", "t_ms": float(t),
                    "frame_idx": t, "observation_key": f"o:{t}",
                    "slot": slot, "role": "victim", "ally": True,
                    "composition": comp, "reason": ""}
        rows = [observation(1000, 0, [0., 0., 1.]),
                observation(1500, 0, [0., 0., 1.]),
                observation(2000, 1, [0., 1., 0.]),
                observation(2500, 1, [0., 1., 0.]),
                observation(2500, 0, [0., 0., 1.])]
        got = attach_stored_killfeed_portraits(
            entries, rows, lineup, gallery, source_version="portrait-test")
        self.assertIsNone(got[0]["claim"]["agent"])
        self.assertEqual(got[0]["claim"]["evidence"]["refused_rivals"], ["Deadlock"])
        self.assertEqual(len(got[0]["claim"]["evidence"]["observations"]), 2)
        self.assertEqual(got[1]["claim"]["agent"], "Reyna")
        self.assertEqual(len(got[1]["claim"]["evidence"]["observations"]), 2)

    def test_single_portrait_view_cannot_promote_a_name(self):
        lineup = {"sides": {"ally": [{"agent": a} for a in
                             ("Phoenix", "Reyna", "Raze", "Miks", "Clove")]}}
        gallery = {"Reyna": [np.array([0., 1.])],
                   "Phoenix": [np.array([1., 0.])]}
        rows = [{"kind": "portrait_observation", "t_ms": 1000.,
                 "slot": 0, "role": "victim", "ally": True,
                 "composition": [0., 1.], "reason": ""}]
        got = attach_stored_killfeed_portraits(
            [{"t_ms": 1000., "slot": 0, "side": "ally"}], rows,
            lineup, gallery, source_version="portrait-test")
        self.assertIsNone(got[0]["claim"]["agent"])
        self.assertEqual(got[0]["claim"]["reason"], "portrait_single_view")

    def test_agreement_resolves_victim_with_independent_channels(self):
        """When killfeed portrait and roster differencing agree, status is resolved with 2 channels."""
        kf_claim = {
            "channel": "killfeed_portrait",
            "agent": "Skye",
            "evidence": {"margin": 0.15},
        }
        roster_shrink = {
            "t_ms": 295000.0,
            "gone": ["Skye"],
            "named": True,
            "margin": 0.20,
        }
        verdict = adjudicate_death(
            death_id="death:session:295000:enemy:0",
            t_ms=295000.0,
            side="enemy",
            killfeed_claim=kf_claim,
            roster_shrink=roster_shrink,
            player_agent="Phoenix",
            is_player_kill=True,
        )
        self.assertEqual(verdict.status, "resolved")
        self.assertEqual(verdict.victim, "Skye")
        self.assertEqual(verdict.killer, "Phoenix")
        self.assertEqual(verdict.independent_channels, 2)
        self.assertIn("killfeed_portrait", verdict.channels)
        self.assertIn("roster_diff", verdict.channels)

    def test_disagreement_is_preserved_never_masked(self):
        """When killfeed portrait and roster differencing conflict, verdict is disagreement."""
        kf_claim = {
            "channel": "killfeed_portrait",
            "agent": "Iso",
            "evidence": {"margin": 0.12},
        }
        roster_shrink = {
            "t_ms": 295000.0,
            "gone": ["Skye"],
            "named": True,
        }
        verdict = adjudicate_death(
            death_id="death:session:295000:enemy:1",
            t_ms=295000.0,
            side="enemy",
            killfeed_claim=kf_claim,
            roster_shrink=roster_shrink,
        )
        self.assertEqual(verdict.status, "disagreement")
        self.assertIsNone(verdict.victim)
        self.assertIn("witnesses disagree", verdict.reason)

    def test_single_channel_resolves_when_companion_refuses(self):
        """When killfeed portrait refused on thin margin, confident roster diff still resolves."""
        kf_claim = {
            "channel": "killfeed_portrait",
            "agent": None,
            "reason": "portrait_margin 0.03 below 0.07",
        }
        roster_shrink = {
            "t_ms": 295000.0,
            "gone": ["Skye"],
            "named": True,
        }
        verdict = adjudicate_death(
            death_id="death:session:295000:enemy:2",
            t_ms=295000.0,
            side="enemy",
            killfeed_claim=kf_claim,
            roster_shrink=roster_shrink,
        )
        self.assertEqual(verdict.status, "resolved")
        self.assertEqual(verdict.victim, "Skye")
        self.assertEqual(verdict.independent_channels, 1)

    def test_local_player_death_flags_player_agent_as_victim(self):
        """Player death HUD flag provides ground-truth local victim witness."""
        verdict = adjudicate_death(
            death_id="death:session:1000:ally:0",
            t_ms=1000.0,
            side="ally",
            player_agent="Phoenix",
            is_player_death=True,
        )
        self.assertEqual(verdict.status, "resolved")
        self.assertEqual(verdict.victim, "Phoenix")
        self.assertIn("player_hud", verdict.channels)

    def test_death_location_attribution_from_xmark_and_track(self):
        """Location attributes from co-located death mark or terminating track."""
        track = {
            "entity_id": "track_skye",
            "side": "enemy",
            "last_seen_ms": 295166.0,
            "location": (275.0, 241.0),
            "agent": "Skye",
        }
        xmark = (274.5, 241.2)

        verdict = adjudicate_death(
            death_id="death:session:295000:enemy:3",
            t_ms=295000.0,
            side="enemy",
            track_termination=track,
            xmark_location=xmark,
        )
        self.assertEqual(verdict.location, (274.5, 241.2))
        self.assertEqual(verdict.victim, "Skye")

    def test_killer_location_attribution_and_event_metadata(self):
        """Killer location attributes and serializes into DeathVerdict and ENTITY_DELETED event."""
        verdict = adjudicate_death(
            death_id="death:session:281500:ally:0",
            t_ms=281500.0,
            side="ally",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Deadlock", "killer": "Killjoy"},
            roster_shrink={"t_ms": 281500.0, "gone": ["Deadlock"], "named": True},
            xmark_location=(137.8, 201.1),
            killer_location=(112.0, 229.4),
        )
        self.assertEqual(verdict.status, "resolved")
        self.assertEqual(verdict.victim, "Deadlock")
        self.assertEqual(verdict.killer, "Killjoy")
        self.assertEqual(verdict.location, (137.8, 201.1))
        self.assertEqual(verdict.killer_location, (112.0, 229.4))
        self.assertIn("killer_location", verdict.channels)
        self.assertIn("xmark", verdict.channels)

        d = verdict.to_dict()
        self.assertEqual(d["location"], [137.8, 201.1])
        self.assertEqual(d["killer_location"], [112.0, 229.4])

        events = death_verdict_to_events(verdict, "session_test")
        self.assertEqual(len(events), 2)
        del_event = events[0]
        self.assertEqual(del_event["metadata"]["location"], [137.8, 201.1])
        self.assertEqual(del_event["metadata"]["killer_location"], [112.0, 229.4])
        self.assertEqual(len(validate_event_rows(events)), 0)

    def test_extract_killer_location_helpers(self):
        """extract_killer_location attributes player position for self and nearest ally/enemy."""
        # 1. Local player is killer
        loc_self = extract_killer_location(
            killer_side="ally",
            killer_agent="Phoenix",
            player_agent="Phoenix",
            player_position=(280.1, 334.7),
        )
        self.assertEqual(loc_self, (280.1, 334.7))

        # 2. Teammate ally killer picks closest ally position to victim
        loc_ally = extract_killer_location(
            killer_side="ally",
            killer_agent="Raze",
            victim_location=(137.5, 201.1),
            ally_positions=[(116.4, 191.0), (320.0, 180.0)],
        )
        self.assertEqual(loc_ally, (116.4, 191.0))

        # 3. Enemy killer picks closest sighting to victim
        loc_enemy = extract_killer_location(
            killer_side="enemy",
            killer_agent="Killjoy",
            victim_location=(137.8, 201.1),
            enemy_sightings=[(112.0, 229.4), (320.0, 160.0)],
        )
        self.assertEqual(loc_enemy, (112.0, 229.4))

    def test_round_death_events_emission_and_contract_validation(self):
        """Emitted death events must satisfy unified event schema contract."""
        session_id = "a06f04a0059f"
        killfeed_entries = [
            {
                "t_ms": 295500.0,
                "victim_ally": False,
                "kf_player_kill": True,
                "claim": {"channel": "killfeed_portrait", "agent": "Skye"},
            }
        ]
        roster_series = [
            {"t_ms": 294000.0, "enemy": {"agents": ["Skye", "Killjoy"], "margin": 0.2, "reason": None}},
            {"t_ms": 296000.0, "enemy": {"agents": ["Killjoy"], "margin": 0.2, "reason": None}},
        ]
        tracks = [
            {"side": "enemy", "last_seen_ms": 295166.0, "location": (275.0, 241.0), "agent": "Skye"}
        ]

        verdicts = adjudicate_round_deaths(
            session_id,
            killfeed_entries,
            roster_series,
            tracks=tracks,
            player_agent="Phoenix",
        )
        self.assertEqual(len(verdicts), 1)
        v = verdicts[0]
        self.assertEqual(v.status, "resolved")
        self.assertEqual(v.victim, "Skye")
        self.assertEqual(v.killer, "Phoenix")
        self.assertEqual(v.location, (275.0, 241.0))

        events = death_verdict_to_events(v, session_id)
        self.assertEqual(len(events), 2)  # ENTITY_DELETED + IDENTITY_DISTRIBUTION

        errors = validate_event_rows(events)
        self.assertEqual(len(errors), 0)

        del_event = events[0]
        self.assertEqual(del_event["event_kind"], "entity_deleted")
        self.assertEqual(del_event["deletion_reason"], "eliminated")
        self.assertEqual(del_event["metadata"]["victim"], "Skye")
        self.assertEqual(del_event["metadata"]["killer"], "Phoenix")
        self.assertEqual(del_event["metadata"]["location"], [275.0, 241.0])

        id_event = events[1]
        self.assertEqual(id_event["event_kind"], "identity_distribution")
        self.assertEqual(id_event["identity_distribution"]["distribution"], {"Skye": 1.0})

    def test_living_roster_sequence_preservation_and_elimination(self):
        """Living roster eliminates dead agents while strictly preserving canonical team order."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        tracker = LivingRosterTracker(lineup, starting_role="defenders")
        snap0 = tracker.start_round(4)
        self.assertEqual(snap0.ally_alive, 5)
        self.assertEqual(snap0.ally_agents, ["Phoenix", "Raze", "Deadlock", "Reyna", "Clove"])
        self.assertEqual(snap0.enemy_alive, 5)
        self.assertEqual(snap0.enemy_agents, ["Skye", "Iso", "Killjoy", "Omen", "Jett"])

        # Deadlock dies (middle slot 2)
        snap1 = tracker.apply_death(281500.0, "ally", "Deadlock")
        self.assertEqual(snap1.ally_alive, 4)
        # Sequence must be ordered subsequence with Deadlock omitted
        self.assertEqual(snap1.ally_agents, ["Phoenix", "Raze", "Reyna", "Clove"])

        # Reyna dies (slot 3)
        snap2 = tracker.apply_death(283500.0, "ally", "Reyna")
        self.assertEqual(snap2.ally_alive, 3)
        self.assertEqual(snap2.ally_agents, ["Phoenix", "Raze", "Clove"])

        # Jett dies on enemy side (slot 4)
        snap3 = tracker.apply_death(284500.0, "enemy", "Jett")
        self.assertEqual(snap3.enemy_alive, 4)
        self.assertEqual(snap3.enemy_agents, ["Skye", "Iso", "Killjoy", "Omen"])

    def test_living_roster_revive_restores_canonical_slot(self):
        """When an agent is revived, they are restored into their exact canonical slot order."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        tracker = LivingRosterTracker(lineup)
        tracker.start_round(4)

        tracker.apply_death(281500.0, "ally", "Deadlock")
        tracker.apply_death(283500.0, "ally", "Reyna")
        self.assertEqual(tracker.living_sequence("ally"), ["Phoenix", "Raze", "Clove"])

        # Sage revives Deadlock: Deadlock must slot back between Raze and Clove!
        snap_revive = tracker.apply_revive(290000.0, "ally", "Deadlock")
        self.assertEqual(snap_revive.ally_alive, 4)
        self.assertEqual(snap_revive.ally_agents, ["Phoenix", "Raze", "Deadlock", "Clove"])

    def test_living_roster_halftime_role_flip(self):
        """Sides flip role (attackers <-> defenders) at round 13 (halftime)."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}],
                "enemy": [{"agent": "Skye"}],
            }
        }
        tracker = LivingRosterTracker(lineup, starting_role="defenders")

        # First half (rounds 1-12): ally is defenders, enemy is attackers
        snap4 = tracker.start_round(4)
        self.assertEqual(snap4.ally_role, "defenders")
        self.assertEqual(snap4.enemy_role, "attackers")

        snap12 = tracker.start_round(12)
        self.assertEqual(snap12.ally_role, "defenders")
        self.assertEqual(snap12.enemy_role, "attackers")

        # Second half (round 13+): roles flip
        snap13 = tracker.start_round(13)
        self.assertEqual(snap13.ally_role, "attackers")
        self.assertEqual(snap13.enemy_role, "defenders")

    def test_ally_death_location_always_observable_for_ability_or_environmental(self):
        """Ally deaths are always observable via minimap blue X marks [domain:minimap/ally-death-mark]."""
        # 1. Ally killed by ability (e.g. Raze Showstopper / Paint Shells)
        v_ability = adjudicate_death(
            death_id="death:session:1000:ally:0",
            t_ms=1000.0,
            side="ally",
            death_cause="ability",
            weapon="Paint Shells",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Clove", "killer": "Raze"},
            roster_shrink={"t_ms": 1000.0, "gone": ["Clove"], "named": True},
            xmark_location=(244.9, 153.9),
        )
        self.assertEqual(v_ability.status, "resolved")
        self.assertEqual(v_ability.victim, "Clove")
        self.assertEqual(v_ability.death_cause, "ability")
        self.assertEqual(v_ability.weapon, "Paint Shells")
        self.assertEqual(v_ability.location, (244.9, 153.9))

        # 2. Ally dying environmentally (e.g. falling off Abyss)
        v_env = adjudicate_death(
            death_id="death:session:2000:ally:1",
            t_ms=2000.0,
            side="ally",
            death_cause="environmental",
            weapon="Fall",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Reyna"},
            roster_shrink={"t_ms": 2000.0, "gone": ["Reyna"], "named": True},
            xmark_location=(150.0, 300.0),
        )
        self.assertEqual(v_env.status, "resolved")
        self.assertEqual(v_env.victim, "Reyna")
        self.assertEqual(v_env.death_cause, "environmental")
        self.assertIsNone(v_env.killer)
        self.assertIsNone(v_env.killer_location)
        self.assertEqual(v_env.location, (150.0, 300.0))

    def test_enemy_ability_and_environmental_unobserved_abstains_location(self):
        """Enemy dying to ability or environment unobserved abstains location [domain:minimap/environmental-death]."""
        # 1. Enemy dies to unobserved ally utility (e.g. cross-map Sova shock dart into smoke)
        v_enemy_ability = adjudicate_death(
            death_id="death:session:3000:enemy:0",
            t_ms=3000.0,
            side="enemy",
            death_cause="ability",
            weapon="Shock Bolt",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Iso", "killer": "Sova"},
            roster_shrink={"t_ms": 3000.0, "gone": ["Iso"], "named": True},
            # No xmark and no terminating track because nobody saw Iso die
            xmark_location=None,
            track_termination=None,
        )
        self.assertEqual(v_enemy_ability.status, "resolved")  # Identity resolved
        self.assertEqual(v_enemy_ability.victim, "Iso")
        self.assertEqual(v_enemy_ability.killer, "Sova")
        self.assertEqual(v_enemy_ability.death_cause, "ability")
        self.assertIsNone(v_enemy_ability.location)  # Location explicitly abstained
        self.assertIn("unobserved enemy ability death location", v_enemy_ability.reason)

        # 2. Enemy falls off map on Abyss unobserved
        v_enemy_fall = adjudicate_death(
            death_id="death:session:4000:enemy:1",
            t_ms=4000.0,
            side="enemy",
            death_cause="environmental",
            weapon="Fall",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Jett"},
            roster_shrink={"t_ms": 4000.0, "gone": ["Jett"], "named": True},
            xmark_location=None,
            track_termination=None,
        )
        self.assertEqual(v_enemy_fall.status, "resolved")
        self.assertEqual(v_enemy_fall.victim, "Jett")
        self.assertEqual(v_enemy_fall.death_cause, "environmental")
        self.assertIsNone(v_enemy_fall.killer)
        self.assertIsNone(v_enemy_fall.killer_location)
        self.assertIsNone(v_enemy_fall.location)  # Location explicitly abstained
        self.assertIn("unobserved enemy environmental death location", v_enemy_fall.reason)

        # Emit events and verify metadata captures death_cause and null location
        events = death_verdict_to_events(v_enemy_fall, "session_test")
        self.assertEqual(len(events), 2)
        del_event = events[0]
        self.assertEqual(del_event["metadata"]["death_cause"], "environmental")
        self.assertIsNone(del_event["metadata"]["location"])
        self.assertIsNone(del_event["metadata"]["killer_location"])
        self.assertEqual(len(validate_event_rows(events)), 0)

    def test_living_roster_slot_mapping_flipped_packing(self):
        """HUD slot mapping respects flipped packing: allies pack right, enemies pack left."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        tracker = LivingRosterTracker(lineup)
        snap0 = tracker.start_round(1)

        # 5 alive: both teams occupy slots 0..4
        self.assertEqual(snap0.ally_slots, {"Phoenix": 0, "Raze": 1, "Deadlock": 2, "Reyna": 3, "Clove": 4})
        self.assertEqual(snap0.enemy_slots, {"Skye": 0, "Iso": 1, "Killjoy": 2, "Omen": 3, "Jett": 4})

        # Deadlock (slot 2) dies on ally side -> 4 alive
        # Allies pack RIGHT towards scoreline: slots are [1, 2, 3, 4], slot 0 is empty!
        snap1 = tracker.apply_death(1000.0, "ally", "Deadlock")
        self.assertEqual(snap1.ally_slots, {"Phoenix": 1, "Raze": 2, "Reyna": 3, "Clove": 4})

        # Skye (slot 0) dies on enemy side -> 4 alive
        # Enemies pack LEFT towards scoreline: slots are [0, 1, 2, 3], slot 4 is empty!
        snap2 = tracker.apply_death(2000.0, "enemy", "Skye")
        self.assertEqual(snap2.enemy_slots, {"Iso": 0, "Killjoy": 1, "Omen": 2, "Jett": 3})

        # Eliminate all allies except Clove (1 alive)
        tracker.apply_death(3000.0, "ally", "Phoenix")
        tracker.apply_death(4000.0, "ally", "Raze")
        snap_last = tracker.apply_death(5000.0, "ally", "Reyna")
        # 1 survivor packs to rightmost slot (slot 4, closest to scoreline)
        self.assertEqual(snap_last.ally_slots, {"Clove": 4})

    def test_living_roster_second_life_run_it_back(self):
        """Phoenix Run It Back death (second life) records the event without removing agent from roster."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        tracker = LivingRosterTracker(lineup)
        tracker.start_round(4)

        # Phoenix "dies" during Run It Back (is_second_life=True)
        snap_rib = tracker.apply_death(280000.0, "ally", "Phoenix", is_second_life=True)
        self.assertEqual(snap_rib.ally_alive, 5)
        self.assertEqual(snap_rib.ally_agents, ["Phoenix", "Raze", "Deadlock", "Reyna", "Clove"])
        self.assertEqual(snap_rib.event, "second_life:Phoenix")

    def test_adjudicate_round_deaths_with_revives_and_second_death(self):
        """Round death adjudication supports revives restoring agents for subsequent deaths."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        kf_entries = [
            # 1. Deadlock dies at 281500ms
            {
                "t_ms": 281500.0, "side": "ally",
                "claim": {"agent": "Deadlock", "killer": "Killjoy"},
                "location": (137.8, 201.1), "killer_location": (112.0, 229.4),
            },
            # 2. Deadlock dies AGAIN at 295000ms after being revived at 290000ms
            {
                "t_ms": 295000.0, "side": "ally",
                "claim": {"agent": "Deadlock", "killer": "Omen"},
                "location": (140.0, 205.0), "killer_location": (115.0, 230.0),
            },
        ]
        revives = [
            {"t_ms": 290000.0, "side": "ally", "agent": "Deadlock"},
        ]

        verdicts = adjudicate_round_deaths(
            session_id="test_revive_session",
            killfeed_entries=kf_entries,
            roster_series=[],
            revives=revives,
            lineup=lineup,
        )
        self.assertEqual(len(verdicts), 2)
        self.assertEqual(verdicts[0].victim, "Deadlock")
        self.assertEqual(verdicts[1].victim, "Deadlock")

        # Build timeline and verify transitions
        timeline = build_round_roster_timeline(
            lineup=lineup,
            death_verdicts=verdicts,
            round_no=4,
            t_start_ms=232000.0,
            revives=revives,
        )
        # Snapshots: round_start (5) -> death1 (4) -> revive (5) -> death2 (4)
        self.assertEqual(len(timeline), 4)
        self.assertEqual(timeline[0].ally_alive, 5)
        self.assertEqual(timeline[1].ally_alive, 4)
        self.assertEqual(timeline[1].event, "death:Deadlock")
        self.assertEqual(timeline[2].ally_alive, 5)
        self.assertEqual(timeline[2].event, "revive:Deadlock")
        self.assertEqual(timeline[3].ally_alive, 4)
        self.assertEqual(timeline[3].event, "death:Deadlock")

    def test_living_roster_to_events_validation(self):
        """LivingRosterTracker emits formal events that pass validate_event_rows."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        tracker = LivingRosterTracker(lineup)
        snap0 = tracker.start_round(4, t_start_ms=232000.0)
        snap1 = tracker.apply_death(281500.0, "ally", "Deadlock")
        snap2 = tracker.apply_revive(290000.0, "ally", "Deadlock")

        events = tracker.to_events("test_session", [snap0, snap1, snap2])
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["event_kind"], "session_boundary")
        self.assertEqual(events[1]["event_kind"], "entity_deleted")
        self.assertEqual(events[2]["event_kind"], "entity_state")
        self.assertEqual(events[2]["state"], "revived")

        errors = validate_event_rows(events)
        self.assertEqual(errors, [])

    def test_detect_second_life_badge_positive_and_negative(self):
        """detect_second_life_badge cleanly separates Phoenix Run It Back arc from crosshairs/negatives."""
        import cv2
        from pathlib import Path
        import numpy as np

        fixture_badge = Path("fixtures/reconciliation/phoenix_second_life_badge.png")
        if fixture_badge.is_file():
            crop = cv2.imread(str(fixture_badge))
            has_badge, info = detect_second_life_badge(crop)
            self.assertTrue(has_badge)
            self.assertGreaterEqual(info["run"], 0.29)
            self.assertGreaterEqual(info["coverage"], 0.50)

        # Negative: plain black crop
        blank_crop = np.zeros((34, 68, 3), dtype=np.uint8)
        has_badge_blank, info_blank = detect_second_life_badge(blank_crop)
        self.assertFalse(has_badge_blank)
        self.assertEqual(info_blank["run"], 0.0)

        # Negative: simulated crosshair (four separate tick marks, no circular arc >= 0.29)
        crosshair_crop = np.zeros((34, 34, 3), dtype=np.uint8)
        cx, cy = 17, 16
        for r in range(7, 12):
            crosshair_crop[cy - r, cx] = 255
            crosshair_crop[cy + r, cx] = 255
            crosshair_crop[cy, cx - r] = 255
            crosshair_crop[cy, cx + r] = 255
        has_badge_crosshair, info_crosshair = detect_second_life_badge(crosshair_crop)
        self.assertFalse(has_badge_crosshair)
        self.assertLess(info_crosshair["run"], 0.29)

    def test_classify_revive_icon_sage_and_clove(self):
        """classify_revive_icon matches Sage Resurrection and rejects non-revive crops."""
        import cv2
        from pathlib import Path
        import numpy as np

        fixture_sage = Path("fixtures/reconciliation/sage_revive_icon.png")
        if fixture_sage.is_file():
            crop = cv2.imread(str(fixture_sage))
            matched_agent, score, meta = classify_revive_icon(crop)
            self.assertEqual(matched_agent, "Sage")
            self.assertGreaterEqual(score, 0.65)
            self.assertGreaterEqual(meta["margin"], 0.15)
            self.assertEqual(meta["top_agent"], "Sage")

        # Negative: blank or noise crop
        blank = np.zeros((24, 30, 3), dtype=np.uint8)
        matched_blank, score_blank, _ = classify_revive_icon(blank)
        self.assertIsNone(matched_blank)
        self.assertEqual(score_blank, 0.0)

    def test_expand_events_and_roster_revive_detection(self):
        """expand_events captures named and unnamed living roster count increases."""
        # 1. Named expansion (Deadlock restored to living set)
        series_named = [
            {"t_ms": 285000.0, "ally": {"agents": ["Phoenix", "Raze", "Clove"], "alive": 3, "margin": 0.2}},
            {"t_ms": 290000.0, "ally": {"agents": ["Phoenix", "Raze", "Deadlock", "Clove"], "alive": 4, "margin": 0.2}},
        ]
        exp_named = expand_events(series_named, "ally")
        self.assertEqual(len(exp_named), 1)
        self.assertEqual(exp_named[0]["t_ms"], 290000.0)
        self.assertEqual(exp_named[0]["side"], "ally")
        self.assertEqual(exp_named[0]["added"], ["Deadlock"])
        self.assertTrue(exp_named[0]["named"])

        # 2. Unnamed expansion (alive count jump 3 -> 4 without agent names)
        series_unnamed = [
            {"t_ms": 960500.0, "alive_ally": 3, "alive_enemy": 2},
            {"t_ms": 961000.0, "alive_ally": 4, "alive_enemy": 2},
        ]
        exp_unnamed = expand_events(series_unnamed, "ally")
        self.assertEqual(len(exp_unnamed), 1)
        self.assertEqual(exp_unnamed[0]["t_ms"], 961000.0)
        self.assertEqual(exp_unnamed[0]["side"], "ally")
        self.assertIsNone(exp_unnamed[0]["added"])
        self.assertFalse(exp_unnamed[0]["named"])

    def test_adjudicate_round_deaths_auto_second_life_from_badge(self):
        """adjudicate_round_deaths automatically detects second life when badge is present in band crop."""
        import cv2
        from pathlib import Path

        fixture_badge = Path("fixtures/reconciliation/phoenix_second_life_badge.png")
        if fixture_badge.is_file():
            crop = cv2.imread(str(fixture_badge))
        else:
            crop = np.zeros((34, 68, 3), dtype=np.uint8)
            cv2.circle(crop, (34, 16), 11, (255, 255, 255), 2)
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Jett"}],
                "enemy": [{"agent": "Omen"}, {"agent": "Skye"}],
            }
        }
        # Killfeed entry has crop with Phoenix badge
        kf_entries = [
            {
                "t_ms": 801000.0,
                "victim_ally": True,
                "claim": {"agent": "Phoenix", "killer": "Omen"},
                "band_crop": crop,
            }
        ]
        verdicts = adjudicate_round_deaths(
            session_id="test_badge_session",
            killfeed_entries=kf_entries,
            roster_series=[],
            lineup=lineup,
        )
        self.assertEqual(len(verdicts), 1)
        self.assertTrue(verdicts[0].is_second_life)
        self.assertEqual(verdicts[0].victim, "Phoenix")

    def test_multi_round_living_roster_tracker_full_match(self):
        """LivingRosterTracker maintains state across multiple rounds, resets on start, and flips role at halftime."""
        lineup = {
            "sides": {
                "ally": [{"agent": "Phoenix"}, {"agent": "Raze"}, {"agent": "Deadlock"}, {"agent": "Reyna"}, {"agent": "Clove"}],
                "enemy": [{"agent": "Skye"}, {"agent": "Iso"}, {"agent": "Killjoy"}, {"agent": "Omen"}, {"agent": "Jett"}],
            }
        }
        rounds_input = [
            # Round 1: ally defenders
            {
                "round_no": 1,
                "t_start_ms": 10000.0,
                "death_verdicts": [
                    DeathVerdict(death_id="d:1", t_ms=15000.0, side="enemy", victim="Skye", status="resolved"),
                    DeathVerdict(death_id="d:2", t_ms=20000.0, side="ally", victim="Deadlock", status="resolved"),
                ],
            },
            # Round 12: final round of first half (ally defenders)
            {
                "round_no": 12,
                "t_start_ms": 720000.0,
                "death_verdicts": [
                    DeathVerdict(death_id="d:12_1", t_ms=730000.0, side="ally", victim="Reyna", status="resolved"),
                ],
            },
            # Round 13: first round of second half (HALFTIME ROLE FLIP: ally attackers)
            {
                "round_no": 13,
                "t_start_ms": 780000.0,
                "death_verdicts": [
                    DeathVerdict(death_id="d:13_1", t_ms=790000.0, side="enemy", victim="Iso", status="resolved"),
                ],
                "revives": [
                    {"t_ms": 795000.0, "side": "enemy", "agent": "Iso"},
                ],
            },
            # Round 14: second half continue (ally attackers)
            {
                "round_no": 14,
                "t_start_ms": 840000.0,
                "death_verdicts": [
                    DeathVerdict(death_id="d:14_1", t_ms=850000.0, side="ally", victim="Phoenix", status="resolved", is_second_life=True),
                ],
            },
        ]

        timeline = build_match_roster_timeline(lineup, rounds_input, starting_role="defenders")
        self.assertGreater(len(timeline), 4)

        # Round 1 start: 5v5, defenders vs attackers
        r1_start = next(s for s in timeline if s.round_no == 1 and s.event == "round_start")
        self.assertEqual(r1_start.ally_alive, 5)
        self.assertEqual(r1_start.enemy_alive, 5)
        self.assertEqual(r1_start.ally_role, "defenders")
        self.assertEqual(r1_start.enemy_role, "attackers")

        # Round 12 start: reset to 5v5, defenders
        r12_start = next(s for s in timeline if s.round_no == 12 and s.event == "round_start")
        self.assertEqual(r12_start.ally_alive, 5)
        self.assertEqual(r12_start.ally_role, "defenders")

        # Round 13 start: reset to 5v5, ROLE FLIPPED to attackers!
        r13_start = next(s for s in timeline if s.round_no == 13 and s.event == "round_start")
        self.assertEqual(r13_start.ally_alive, 5)
        self.assertEqual(r13_start.ally_role, "attackers")
        self.assertEqual(r13_start.enemy_role, "defenders")

        # Round 13 Iso revive
        r13_revive = next(s for s in timeline if s.round_no == 13 and s.event == "revive:Iso")
        self.assertEqual(r13_revive.enemy_alive, 5)
        self.assertIn("Iso", r13_revive.enemy_agents)

        # Round 14 second life Phoenix death doesn't decrement alive count
        r14_rib = next(s for s in timeline if s.round_no == 14 and s.event == "second_life:Phoenix")
        self.assertEqual(r14_rib.ally_alive, 5)
        self.assertEqual(r14_rib.ally_role, "attackers")

        # Formal Reticle event conversion across the match timeline
        tracker = LivingRosterTracker(lineup, starting_role="defenders")
        events = tracker.to_events("session_match_test", timeline)
        self.assertGreater(len(events), 0)
        errors = validate_event_rows(events)
        self.assertEqual(errors, [])

    def test_adjudicate_round_deaths_icon_crop_populates_weapon_and_cause(self):
        """adjudicate_round_deaths uses icon_crop to adjudicate weapon, cause, and second life."""
        from reticle.adjudication.weapon import load_ability_gallery, load_weapon_gallery

        # 1. Gun icon crop: Spectre
        gallery = load_weapon_gallery()
        spectre_crop = np.zeros((34, 66, 3), dtype=np.uint8)
        if "Spectre" in gallery:
            s = gallery["Spectre"]
            spectre_crop[7:27, 2:64][s[:, :, 3] > 128] = 255

        raw_kf = [
            {
                "t_ms": 100000.0,
                "side": "enemy",
                "claim": {"channel": "killfeed_portrait", "agent": "Jett"},
                "killer": "Phoenix",
                "icon_crop": spectre_crop,
            },
        ]
        verdicts = adjudicate_round_deaths("test_session", raw_kf, [])
        self.assertEqual(len(verdicts), 1)
        v = verdicts[0]
        self.assertEqual(v.victim, "Jett")
        self.assertEqual(v.weapon, "Spectre")
        self.assertEqual(v.death_cause, "gun")
        self.assertFalse(v.is_second_life)

        # 2. Revive / Second life ability icon crop: Phoenix Run It Back
        ab_gallery = load_ability_gallery()
        phoenix_crop = np.zeros((34, 34, 3), dtype=np.uint8)
        if "Phoenix_Ultimate" in ab_gallery:
            pu = ab_gallery["Phoenix_Ultimate"]
            w_target = int(round(pu.shape[1] * (20 / pu.shape[0])))
            pu_resized = cv2.resize(pu, (w_target, 20))
            phoenix_crop[7:27, 5:5+w_target][pu_resized[:, :, 3] > 128] = 255

        raw_kf_2 = [
            {
                "t_ms": 105000.0,
                "side": "ally",
                "claim": {"channel": "killfeed_portrait", "agent": "Phoenix"},
                "killer": "Jett",
                "icon_crop": phoenix_crop,
            },
        ]
        verdicts_2 = adjudicate_round_deaths("test_session", raw_kf_2, [], player_agent="Phoenix")
        self.assertEqual(len(verdicts_2), 1)
        v2 = verdicts_2[0]
        self.assertEqual(v2.victim, "Phoenix")
        self.assertEqual(v2.weapon, "Run It Back")
        self.assertEqual(v2.death_cause, "ability")
        self.assertTrue(v2.is_second_life)


if __name__ == "__main__":
    unittest.main()


class ScoreboardDimWitnessTest(unittest.TestCase):
    """The scoreboard's newly dimmed rows as a gated victim witness."""

    ALLY = ["Breach", "Deadlock", "Phoenix", "Reyna", "Miks"]
    ENEMY = ["Jett", "Killjoy", "Skye", "Iso", "Omen"]

    def board(self, t_ms, dim=(), bad=None):
        rows = []
        for i, name in enumerate(self.ALLY + self.ENEMY):
            rows.append({
                "kind": "row_observation", "t_ms": t_ms, "frame_idx": int(t_ms / 33),
                "display_row": i, "team": "ally" if i < 5 else "enemy",
                "observation_key": f"s:{t_ms}:{i}", "portrait_agent_reason": None,
                "portrait_agent_best": name, "portrait_agent_score": 0.9,
                "portrait_agent_margin": 0.4,
                "portrait_gain": 0.35 if name in dim else 0.9,
                "scoreboard_version": "scoreboard-0.2.0"})
        if bad is not None:
            rows[bad]["portrait_agent_score"] = 0.5
        return rows

    def test_one_refused_row_refuses_the_whole_opening(self):
        from reticle.adjudication.scoreboard import scoreboard_openings
        got = scoreboard_openings(self.board(1000.0, bad=7) + self.board(2000.0))
        self.assertEqual([o["accepted"] for o in got], [False, True])
        self.assertEqual(got[0]["reason"], "row_refused")

    def test_enemy_rows_on_top_of_ally_rows_refuse_the_opening(self):
        from reticle.adjudication.scoreboard import scoreboard_openings
        rows = self.board(1000.0)
        for i, r in enumerate(rows):
            r["row_y0"] = 340 + 34 * (i % 5)     # both blocks at the ally rows
        got = scoreboard_openings(rows)[0]
        self.assertFalse(got["accepted"])
        self.assertEqual(got["reason"], "enemy_rows_not_below_ally_rows")

    def test_a_gain_between_bands_names_nothing(self):
        from reticle.adjudication.scoreboard import scoreboard_openings
        rows = self.board(1000.0)
        rows[2]["portrait_gain"] = 0.68
        got = scoreboard_openings(rows)[0]
        self.assertFalse(got["accepted"])
        self.assertTrue(got["rows"][2]["reason"].startswith("gain_between_bands"))

    def test_one_death_and_one_newly_dim_agent_binds(self):
        from reticle.adjudication.death import scoreboard_death_claims
        from reticle.adjudication.scoreboard import scoreboard_openings
        openings = scoreboard_openings(self.board(1000.0) + self.board(3000.0, dim={"Deadlock"}))
        claims = scoreboard_death_claims([{"t_ms": 2000.0, "side": "ally"}], openings, {})
        self.assertEqual(claims[0]["agent"], "Deadlock")
        self.assertEqual(claims[0]["evidence"]["newly_dim"], ["Deadlock"])

    def test_several_deaths_name_only_by_elimination(self):
        from reticle.adjudication.death import scoreboard_death_claims
        from reticle.adjudication.scoreboard import scoreboard_openings
        openings = scoreboard_openings(
            self.board(1000.0) + self.board(9000.0, dim={"Reyna", "Miks", "Jett", "Skye"}))
        entries = [{"t_ms": 2000.0, "side": "ally"}, {"t_ms": 3000.0, "side": "enemy"},
                   {"t_ms": 4000.0, "side": "ally"}, {"t_ms": 5000.0, "side": "enemy"}]
        claims = scoreboard_death_claims(entries, openings, {0: "Reyna"})
        self.assertEqual(claims[2]["agent"], "Miks")
        self.assertIsNone(claims[0]["agent"])      # its only other death is unnamed
        self.assertTrue(claims[1]["reason"].startswith("interval_unordered"))
        self.assertTrue(claims[3]["reason"].startswith("interval_unordered"))

    def test_an_independent_name_outside_the_dim_set_refuses(self):
        from reticle.adjudication.death import scoreboard_death_claims
        from reticle.adjudication.scoreboard import scoreboard_openings
        openings = scoreboard_openings(self.board(1000.0) + self.board(9000.0, dim={"Reyna", "Miks"}))
        entries = [{"t_ms": 2000.0, "side": "ally"}, {"t_ms": 4000.0, "side": "ally"}]
        claims = scoreboard_death_claims(entries, openings, {0: "Phoenix"})
        self.assertIsNone(claims[1]["agent"])
        self.assertTrue(claims[1]["reason"].startswith("other_names_not_in_newly_dim"))

    def test_count_disagreement_with_killfeed_refuses(self):
        from reticle.adjudication.death import scoreboard_death_claims
        from reticle.adjudication.scoreboard import scoreboard_openings
        openings = scoreboard_openings(self.board(1000.0) + self.board(3000.0, dim={"Reyna", "Miks"}))
        claims = scoreboard_death_claims([{"t_ms": 2000.0, "side": "ally"}], openings, {})
        self.assertIsNone(claims[0]["agent"])
        self.assertEqual(claims[0]["reason"], "newly_dim_2_disagrees_with_killfeed_deaths_1")

    def test_a_sage_revive_lights_a_row_again_without_refusing(self):
        from reticle.adjudication.death import scoreboard_death_claims
        from reticle.adjudication.scoreboard import scoreboard_openings
        openings = scoreboard_openings(self.board(1000.0, dim={"Reyna"})
                                       + self.board(3000.0, dim={"Miks"}))
        claims = scoreboard_death_claims([{"t_ms": 2000.0, "side": "ally"}], openings, {})
        self.assertEqual(claims[0]["agent"], "Miks")
        self.assertEqual(claims[0]["evidence"]["revived"], ["Reyna"])

    def test_a_run_it_back_death_is_not_counted_against_the_dimmed_set(self):
        from reticle.adjudication.death import scoreboard_death_claims
        from reticle.adjudication.scoreboard import scoreboard_openings
        openings = scoreboard_openings(self.board(1000.0) + self.board(3000.0, dim={"Miks"}))
        entries = [{"t_ms": 1500.0, "side": "ally"}, {"t_ms": 2000.0, "side": "ally"}]
        claims = scoreboard_death_claims(entries, openings, {}, second_life={0})
        self.assertEqual(claims[0]["reason"], "second_life_death_does_not_dim")
        self.assertEqual(claims[1]["agent"], "Miks")

    def test_scoreboard_name_resolves_and_disagreement_is_kept(self):
        claim = {"channel": "scoreboard_dim", "agent": "Deadlock"}
        alone = adjudicate_death(death_id="d", t_ms=1.0, side="ally", scoreboard_claim=claim)
        self.assertEqual((alone.status, alone.victim), ("resolved", "Deadlock"))
        clash = adjudicate_death(death_id="d", t_ms=1.0, side="ally", scoreboard_claim=claim,
                                 killfeed_claim={"channel": "killfeed_portrait", "agent": "Reyna"})
        self.assertEqual((clash.status, clash.victim), ("disagreement", None))
