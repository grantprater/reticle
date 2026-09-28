"""End-to-end integration tests for Round 4 agent identity adjudication.

Validates the full identity pipeline on Round 4 of session `a06f04a0059f` against
ground-truth labels, testing:
1. Round boundary ingestion from L2 rounds table;
2. Label ingestion and spatial clustering;
3. Refusal safety with stored top-bar lineup (preventing false identifications);
4. Matcher precision and 100% accuracy on resolved with true candidates;
5. Multi-channel corroboration (minimap + killfeed) in AgentIdentityArbiter;
6. Formal IDENTITY_DISTRIBUTION event generation and contract validation.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from reticle.adjudication.death import (
    adjudicate_round_deaths,
    death_verdict_to_events,
)
from reticle.adjudication.identity import (
    AGENT_IDENTITY_VERSION,
    MINIMAP_SURFACES,
    AgentIdentityArbiter,
    claims_from_minimap_icons,
    identity_claim,
    load_identity_gallery,
)
from reticle.events import validate_event_rows
from reticle.store import Store
from prototypes.round_identity_eval import (
    assign_spatial_tracks,
    extract_crops_for_sightings,
    extract_round_killfeed_entries,
    load_minimap_labels,
    load_round_bounds,
)
from prototypes.round_identity_fixture import fixture_path

#: Killfeed ROI crops of every view each round 4 entry occupies, in the store so
#: every worktree reads them; `prototypes/round_identity_fixture.py` builds
#: them from the hud ROI cache. Without them `extract_round_killfeed_entries`
#: reads one video frame per entry, and one view cannot carry a name through
#: `_channel_verdict`, so the death tests skip.
#:
#: The ally oracle is the source's. Seacow is Breach (the player,
#: [domain:killfeed/ability-kill-icon]) and kills Jett at 284.5 s and Iso at
#: 332.5 s; the 295.0 s victim is Miks, as the player answered in the
#: death-refusals review and the stored lineup names in ally slot 4. The ally
#: slot order is the stored lineup's. Enemy slots 0 and 4 are refused there,
#: and it names slot 2 Clove where the killfeed shows Killjoy.
KF_FIXTURE = fixture_path(Store(), "a06f04a0059f", 4, "killfeed")
NEEDS_KF_FIXTURE = unittest.skipUnless(
    KF_FIXTURE.is_file(), f"needs {KF_FIXTURE}: run prototypes/round_identity_fixture.py")


class RoundIdentityE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store()
        cls.session_id = "a06f04a0059f"
        cls.date = "2026-08-26"
        cls.round_no = 4

        cls.t_start_ms, cls.t_end_ms, _ = load_round_bounds(
            cls.store, cls.session_id, cls.date, cls.round_no
        )
        cls.sightings = load_minimap_labels(
            cls.store, cls.session_id, cls.t_start_ms, cls.t_end_ms
        )
        cls.sightings_with_crops = extract_crops_for_sightings(
            cls.store, cls.session_id, cls.sightings
        )
        assign_spatial_tracks(cls.sightings_with_crops)
        cls.gallery = load_identity_gallery(cls.store.root, surfaces=MINIMAP_SURFACES)

    def test_round4_bounds_and_sightings_ingestion(self):
        """Verify round boundaries and ground-truth label ingestion."""
        self.assertEqual(self.t_start_ms, 232000.0)
        self.assertEqual(self.t_end_ms, 351000.0)
        self.assertEqual(len(self.sightings), 25)

        agents = [s["agent"] for s in self.sightings]
        self.assertEqual(agents.count("killjoy"), 14)
        self.assertEqual(agents.count("skye"), 11)

    def test_round4_stored_lineup_prevents_false_identifications(self):
        """Stored top-bar lineup has refused rival slots: arbiter must refuse, not misname."""
        stored_lineup_path = self.store.root / "lineups" / f"{self.session_id}.json"
        with open(stored_lineup_path, "r", encoding="utf-8") as f:
            stored_lineup = json.load(f)

        claims = claims_from_minimap_icons(
            self.sightings_with_crops, stored_lineup, gallery=self.gallery
        )
        self.assertEqual(len(claims), 25)

        # In stored mode, all 25 sightings must refuse rather than making false claims
        resolved = [c for c in claims if c.get("agent") is not None]
        self.assertEqual(len(resolved), 0)

        # Verify reasons cite rival slots or thin margins
        reasons = [c.get("reason", "") for c in claims]
        self.assertTrue(any("icon_best_is_refused_slot" in r for r in reasons))

    def test_round4_true_candidates_resolution_and_accuracy(self):
        """With true candidate roster, resolved claims must be 100% accurate."""
        oracle_lineup = {
            "sides": {
                "enemy": [
                    {"slot": 0, "agent": "Skye", "best_guess": "Skye", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Iso", "best_guess": "Iso", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Killjoy", "best_guess": "Killjoy", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Omen", "best_guess": "Omen", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Jett", "best_guess": "Jett", "margin": 0.2, "reason": None},
                ]
            }
        }

        claims = claims_from_minimap_icons(
            self.sightings_with_crops, oracle_lineup, gallery=self.gallery
        )
        resolved = [c for c in claims if c.get("agent") is not None]
        self.assertGreater(len(resolved), 0)

        # Every resolved claim must match human ground truth
        for c, s in zip(claims, self.sightings_with_crops):
            if c.get("agent") is not None:
                self.assertEqual(c["agent"].lower(), s["agent"].lower())
                self.assertGreater(c["evidence"]["margin"], 0.07)

        # Skye sightings should all be resolved with decisive margins (> 0.15)
        skye_claims = [c for c, s in zip(claims, self.sightings_with_crops) if s["agent"] == "skye"]
        self.assertEqual(len(skye_claims), 11)
        for sc in skye_claims:
            self.assertEqual(sc["agent"], "Skye")
            self.assertGreater(sc["evidence"]["margin"], 0.15)

    def test_round4_arbiter_and_cross_channel_corroboration(self):
        """Arbiter aggregates minimap claims and corroborates with killfeed witness."""
        oracle_lineup = {
            "sides": {
                "enemy": [
                    {"slot": 0, "agent": "Skye", "best_guess": "Skye", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Iso", "best_guess": "Iso", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Killjoy", "best_guess": "Killjoy", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Omen", "best_guess": "Omen", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Jett", "best_guess": "Jett", "margin": 0.2, "reason": None},
                ]
            }
        }
        claims = claims_from_minimap_icons(
            self.sightings_with_crops, oracle_lineup, gallery=self.gallery
        )

        arbiter = AgentIdentityArbiter()
        arbiter.extend(claims)

        # Concurrent killfeed portrait claim at elimination time
        kf_claim = identity_claim(
            "minimap:enemy:track:track_a",
            "Skye",
            channel="killfeed_portrait",
            observed_at_ms=295000.0,
            source_version="killfeed-portrait-0.1.0",
        )
        arbiter.add(kf_claim)

        verdicts = arbiter.verdict()
        self.assertEqual(len(verdicts), 2)

        verdict_a = next(v for v in verdicts if v["entity_id"] == "minimap:enemy:track:track_a")
        self.assertEqual(verdict_a["status"], "resolved")
        self.assertEqual(verdict_a["agent"], "Skye")
        self.assertEqual(verdict_a["independent_channels"], 2)
        self.assertEqual(set(verdict_a["channels"]), {"minimap_portrait", "killfeed_portrait"})

        verdict_b = next(v for v in verdicts if v["entity_id"] == "minimap:enemy:track:track_b")
        self.assertEqual(verdict_b["status"], "resolved")
        self.assertEqual(verdict_b["agent"], "Killjoy")
        self.assertEqual(verdict_b["independent_channels"], 1)

    def test_round4_identity_distribution_events_validation(self):
        """Arbiter emitted IDENTITY_DISTRIBUTION events must satisfy unified event schema."""
        oracle_lineup = {
            "sides": {
                "enemy": [
                    {"slot": 0, "agent": "Skye", "best_guess": "Skye", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Iso", "best_guess": "Iso", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Killjoy", "best_guess": "Killjoy", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Omen", "best_guess": "Omen", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Jett", "best_guess": "Jett", "margin": 0.2, "reason": None},
                ]
            }
        }
        claims = claims_from_minimap_icons(
            self.sightings_with_crops, oracle_lineup, gallery=self.gallery
        )

        arbiter = AgentIdentityArbiter()
        arbiter.extend(claims)
        events = arbiter.events(self.session_id, t_ms=self.t_end_ms)

        self.assertEqual(len(events), 2)
        errors = validate_event_rows(events)
        self.assertEqual(len(errors), 0)

        for event in events:
            self.assertEqual(event["event_kind"], "identity_distribution")
            self.assertEqual(event["session_id"], self.session_id)
            self.assertEqual(event["producer_version"], AGENT_IDENTITY_VERSION)
            self.assertIn("distribution", event["identity_distribution"])
            self.assertEqual(event["metadata"]["status"], "resolved")

    def _round4_deaths(self):
        """Death verdicts from the killfeed fixture, the roster and the
        minimap tracks, against the source's lineup."""
        oracle_lineup = {
            "sides": {
                "ally": [
                    {"slot": 0, "agent": "Phoenix", "best_guess": "Phoenix", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Breach", "best_guess": "Breach", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Deadlock", "best_guess": "Deadlock", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Reyna", "best_guess": "Reyna", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Miks", "best_guess": "Miks", "margin": 0.2, "reason": None},
                ],
                "enemy": [
                    {"slot": 0, "agent": "Skye", "best_guess": "Skye", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Iso", "best_guess": "Iso", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Killjoy", "best_guess": "Killjoy", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Omen", "best_guess": "Omen", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Jett", "best_guess": "Jett", "margin": 0.2, "reason": None},
                ],
            }
        }
        claims = claims_from_minimap_icons(
            self.sightings_with_crops, oracle_lineup, gallery=self.gallery
        )
        arbiter = AgentIdentityArbiter()
        arbiter.extend(claims)
        verdicts = arbiter.verdict()

        # Build terminating tracks from arbiter verdicts
        terminating_tracks = []
        for v in verdicts:
            tr_id = v["entity_id"].split(":")[-1]
            tr_sightings = [s for s in self.sightings_with_crops if s.get("track_id") == tr_id]
            if tr_sightings and v.get("status") == "resolved":
                last_s = tr_sightings[-1]
                terminating_tracks.append({
                    "entity_id": v["entity_id"],
                    "side": "enemy",
                    "agent": v.get("agent"),
                    "last_seen_ms": float(last_s["t_ms"]),
                    "location": (float(last_s["x"]), float(last_s["y"])),
                })

        # Ingest HUD reads and Roster series with live killfeed portrait classification
        hud = self.store.read_hud(self.session_id, self.date).to_pydict()
        roster = self.store.read_roster(self.session_id, self.date).to_pylist()
        kf_entries = extract_round_killfeed_entries(
            hud, self.t_start_ms, self.t_end_ms,
            store=self.store, session_id=self.session_id,
            active_lineup=oracle_lineup, gallery=self.gallery,
        )
        r4_roster = [r for r in roster if self.t_start_ms <= r["t_ms"] <= self.t_end_ms]

        death_verdicts = adjudicate_round_deaths(
            session_id=self.session_id,
            killfeed_entries=kf_entries,
            roster_series=r4_roster,
            tracks=terminating_tracks,
            player_agent="Phoenix",
            lineup=oracle_lineup,
            gallery=self.gallery,
        )
        return death_verdicts, terminating_tracks

    @NEEDS_KF_FIXTURE
    def test_round4_death_attribution_and_events(self):
        """Cross-channel death adjudication names each victim and killer as the source shows them."""
        death_verdicts, tracks = self._round4_deaths()

        self.assertEqual(len(death_verdicts), 7)
        resolved_deaths = [d for d in death_verdicts if d.status == "resolved"]
        self.assertEqual(len(resolved_deaths), 7)

        # Victim and killer as the killfeed draws them (source review, 2026-09-28).
        # Jett's victim vote is thin: the reader reads her white hair as name
        # text and cuts the box past her portrait (clipped 0.76), so 3 of 10
        # views name her and 7 refuse.
        expected = [
            (281500.0, "ally", "Deadlock", "Killjoy"),
            (283500.0, "ally", "Reyna", "Omen"),
            (284500.0, "enemy", "Jett", "Breach"),
            (295000.0, "ally", "Miks", "Killjoy"),
            (295500.0, "enemy", "Skye", "Phoenix"),
            (301000.0, "ally", "Phoenix", "Omen"),
            (332500.0, "enemy", "Iso", "Breach"),
        ]
        for t_ms, side, victim, killer in expected:
            d = next(d for d in death_verdicts if abs(d.t_ms - t_ms) < 1.0)
            with self.subTest(t_ms=t_ms):
                self.assertEqual(d.side, side)
                self.assertEqual(d.status, "resolved")
                self.assertEqual(d.victim, victim)
                self.assertEqual(d.killer, killer)
                self.assertIn("killfeed_portrait", d.channels)
                self.assertIn("roster_diff", d.channels)

        # Skye's minimap track ends where she was last labelled; no other death
        # has a location witness here.
        skye_death = next(d for d in death_verdicts if abs(d.t_ms - 295500.0) < 1.0)
        skye_track = next(tr for tr in tracks if tr["agent"] == "Skye")
        self.assertEqual(skye_death.location, skye_track["location"])
        self.assertGreaterEqual(skye_death.independent_channels, 2)
        self.assertIn("minimap_track", skye_death.channels)

        player_death = next(d for d in death_verdicts if abs(d.t_ms - 301000.0) < 1.0)
        self.assertIn("player_hud", player_death.channels)

        # Emit and validate formal events schema
        death_events = []
        for dv in death_verdicts:
            death_events.extend(death_verdict_to_events(dv, self.session_id))

        # 7 ENTITY_DELETED, 7 victim and 7 killer IDENTITY_DISTRIBUTION events.
        self.assertEqual(len(death_events), 21)
        errors = validate_event_rows(death_events)
        self.assertEqual(len(errors), 0)
        del_events = [e for e in death_events if e["event_kind"] == "entity_deleted"]
        self.assertEqual(len(del_events), 7)

        # Check Skye's deletion and identity events
        skye_del_event = next(
            e for e in death_events
            if e.get("metadata", {}).get("victim") == "Skye" and e["event_kind"] == "entity_deleted"
        )
        self.assertEqual(skye_del_event["deletion_reason"], "eliminated")
        self.assertEqual(skye_del_event["metadata"]["killer"], "Phoenix")
        self.assertEqual(tuple(skye_del_event["metadata"]["location"]), skye_track["location"])

        # The identity event comes from the arbiter, keyed by the death.
        skye_id_event = next(
            e for e in death_events
            if e["event_kind"] == "identity_distribution"
            and e["identity_distribution"]["subject_entity_id"] == skye_del_event["entity_id"]
        )
        self.assertEqual(skye_id_event["identity_distribution"]["distribution"], {"Skye": 1.0})
        self.assertEqual(skye_id_event["source_channel"], "adjudication.identity")

    @NEEDS_KF_FIXTURE
    @unittest.expectedFailure
    def test_round4_gun_kill_locations(self):
        """Every gun kill should carry a death and a killer location.

        Expected to fail: no channel this harness feeds observes where anyone
        died or stood, and `reticle deaths` stores no location either. The
        coordinates this test once asserted came from the 2026-09-12 fixture,
        which recorded no source for them (Jett's matched Deadlock's X mark to
        0.3 px), and the death-round4 contract refused fixture locations.
        """
        death_verdicts, _ = self._round4_deaths()
        for dv in death_verdicts:
            self.assertIsNotNone(dv.location, f"{dv.death_id} has no death location")
            self.assertIsNotNone(dv.killer_location, f"{dv.death_id} has no killer location")


    @NEEDS_KF_FIXTURE
    def test_round4_living_roster_timeline_and_slot_tracking(self):
        """Verify the complete Round 4 living roster timeline, survivor inward packing, and slot mapping."""
        from reticle.adjudication.death import build_round_roster_timeline, LivingRosterTracker

        oracle_lineup = {
            "sides": {
                "ally": [
                    {"slot": 0, "agent": "Phoenix"},
                    {"slot": 1, "agent": "Breach"},
                    {"slot": 2, "agent": "Deadlock"},
                    {"slot": 3, "agent": "Reyna"},
                    {"slot": 4, "agent": "Miks"},
                ],
                "enemy": [
                    {"slot": 0, "agent": "Skye"},
                    {"slot": 1, "agent": "Iso"},
                    {"slot": 2, "agent": "Killjoy"},
                    {"slot": 3, "agent": "Omen"},
                    {"slot": 4, "agent": "Jett"},
                ],
            }
        }

        hud = self.store.read_hud(self.session_id, self.date).to_pydict()
        roster = self.store.read_roster(self.session_id, self.date).to_pylist()
        kf_entries = extract_round_killfeed_entries(
            hud, self.t_start_ms, self.t_end_ms,
            store=self.store, session_id=self.session_id,
            active_lineup=oracle_lineup, gallery=self.gallery,
        )
        r4_roster = [r for r in roster if self.t_start_ms <= r["t_ms"] <= self.t_end_ms]

        death_verdicts = adjudicate_round_deaths(
            session_id=self.session_id,
            killfeed_entries=kf_entries,
            roster_series=r4_roster,
            player_agent="Phoenix",
            lineup=oracle_lineup,
            gallery=self.gallery,
        )

        timeline = build_round_roster_timeline(
            lineup=oracle_lineup,
            death_verdicts=death_verdicts,
            round_no=4,
            t_start_ms=self.t_start_ms,
            starting_role="defenders",
        )

        # 1 start snapshot + 7 death snapshots = 8 snapshots
        self.assertEqual(len(timeline), 8)

        # Snapshot 0: Round start (5v5)
        # Allies in slots 0..4, Enemies in slots 0..4
        snap0 = timeline[0]
        self.assertEqual(snap0.ally_alive, 5)
        self.assertEqual(snap0.ally_agents, ["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"])
        self.assertEqual(snap0.ally_slots, {"Phoenix": 0, "Breach": 1, "Deadlock": 2, "Reyna": 3, "Miks": 4})
        self.assertEqual(snap0.enemy_alive, 5)
        self.assertEqual(snap0.enemy_agents, ["Skye", "Iso", "Killjoy", "Omen", "Jett"])
        self.assertEqual(snap0.enemy_slots, {"Skye": 0, "Iso": 1, "Killjoy": 2, "Omen": 3, "Jett": 4})

        # Snapshot 1: Deadlock dies (ally, slot 2) at 281.5s -> 4v5
        # Allies pack right: slots 1..4 (slot 0 empty!)
        snap1 = timeline[1]
        self.assertEqual(snap1.event, "death:Deadlock")
        self.assertEqual(snap1.ally_alive, 4)
        self.assertEqual(snap1.ally_agents, ["Phoenix", "Breach", "Reyna", "Miks"])
        self.assertEqual(snap1.ally_slots, {"Phoenix": 1, "Breach": 2, "Reyna": 3, "Miks": 4})

        # Snapshot 2: Reyna dies (ally, slot 3) at 283.5s -> 3v5
        # Allies pack right: slots 2..4 (slots 0, 1 empty!)
        snap2 = timeline[2]
        self.assertEqual(snap2.event, "death:Reyna")
        self.assertEqual(snap2.ally_alive, 3)
        self.assertEqual(snap2.ally_agents, ["Phoenix", "Breach", "Miks"])
        self.assertEqual(snap2.ally_slots, {"Phoenix": 2, "Breach": 3, "Miks": 4})

        # Snapshot 3: Jett dies (enemy, slot 4) at 284.5s -> 3v4
        # Enemies pack left: slots 0..3 (slot 4 empty!)
        snap3 = timeline[3]
        self.assertEqual(snap3.event, "death:Jett")
        self.assertEqual(snap3.enemy_alive, 4)
        self.assertEqual(snap3.enemy_agents, ["Skye", "Iso", "Killjoy", "Omen"])
        self.assertEqual(snap3.enemy_slots, {"Skye": 0, "Iso": 1, "Killjoy": 2, "Omen": 3})

        # Snapshot 4: Miks dies (ally) at 295.0s -> 2v4
        # Allies pack right: slots 3..4
        snap4 = timeline[4]
        self.assertEqual(snap4.event, "death:Miks")
        self.assertEqual(snap4.ally_alive, 2)
        self.assertEqual(snap4.ally_agents, ["Phoenix", "Breach"])
        self.assertEqual(snap4.ally_slots, {"Phoenix": 3, "Breach": 4})

        # Snapshot 5: Skye dies (enemy, slot 0) at 295.5s -> 2v3
        # Enemies pack left: slots 0..2 (slots 3, 4 empty!)
        snap5 = timeline[5]
        self.assertEqual(snap5.event, "death:Skye")
        self.assertEqual(snap5.enemy_alive, 3)
        self.assertEqual(snap5.enemy_agents, ["Iso", "Killjoy", "Omen"])
        self.assertEqual(snap5.enemy_slots, {"Iso": 0, "Killjoy": 1, "Omen": 2})

        # Snapshot 6: Phoenix dies (ally, slot 0) at 301.0s -> 1v3
        # 1 ally survivor (Breach) packs right to innermost slot 4!
        snap6 = timeline[6]
        self.assertEqual(snap6.event, "death:Phoenix")
        self.assertEqual(snap6.ally_alive, 1)
        self.assertEqual(snap6.ally_agents, ["Breach"])
        self.assertEqual(snap6.ally_slots, {"Breach": 4})

        # Snapshot 7: Iso dies (enemy, slot 1) at 332.5s -> 1v2
        # Enemies pack left: slots 0..1
        snap7 = timeline[7]
        self.assertEqual(snap7.event, "death:Iso")
        self.assertEqual(snap7.enemy_alive, 2)
        self.assertEqual(snap7.enemy_agents, ["Killjoy", "Omen"])
        self.assertEqual(snap7.enemy_slots, {"Killjoy": 0, "Omen": 1})

        # Verify event emission from tracker
        tracker = LivingRosterTracker(oracle_lineup, starting_role="defenders")
        events = tracker.to_events(self.session_id, timeline)
        self.assertEqual(len(events), 8)  # 1 session_boundary + 7 entity_deleted
        errors = validate_event_rows(events)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
