"""The dead Clove's range circle (`clove_circle`), its smoke-owner channel and
the player's Ruse casts while dead (`ability_timeline.dead_ruse_casts`)."""
import unittest
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from reticle import clove_circle as cc
from reticle.ability_timeline import DEAD_RUSE_VERSION, dead_ruse_casts, held_at_deaths
from reticle.adjudication import smoke_owner
from reticle.geometry import MapScale

W = 460


def static(seed=0):
    """A textured grey widget static, as a baked reference would be."""
    rng = np.random.default_rng(seed)
    g = cv2.GaussianBlur(rng.uniform(60, 140, (W, W)).astype(np.float32), (0, 0), 3)
    return np.clip(g, 0, 255)


def with_circle(sg, c, r, rim=60.0, tint=12.0):
    """The static with a pale disc tint and a bright one-pixel rim drawn at
    sub-pixel precision (supersampled, then shrunk with INTER_AREA)."""
    k = 4
    big = np.zeros((W * k, W * k), np.float32)
    yy, xx = np.mgrid[:W * k, :W * k]
    d = np.hypot((xx + 0.5) / k - c[0], (yy + 0.5) / k - c[1])
    big[d <= r] = tint
    big[np.abs(d - r) <= 0.75] = rim
    over = cv2.resize(big, (W, W), interpolation=cv2.INTER_AREA)
    g = np.clip(sg + over, 0, 255).astype(np.uint8)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def reader(sg, windows=(), self_track=None, r_base=152.08, r_from="sunset", map_name="sunset"):
    ms = MapScale("sunset__test", 1.0, 1.0, "test")
    return cc.CloveCircleReader(sg, np.ones((W, W), bool), (0, 0, W, W), list(windows), ms,
                                r_base, r_from, map_name=map_name, self_track=self_track)


class CircleFit(unittest.TestCase):
    def test_a_synthetic_ring_is_fitted_to_a_fraction_of_a_pixel(self):
        sg = static()
        img = with_circle(sg, (201.3, 225.7), 151.6)
        got = reader(sg).read(img, None)
        self.assertTrue(got["present"], got)
        # The fit takes the rim's steepest outward drop, its outer edge.
        self.assertAlmostEqual(got["cx"], 201.3, delta=0.75)
        self.assertAlmostEqual(got["cy"], 225.7, delta=0.75)
        self.assertAlmostEqual(got["r"], 151.6, delta=1.0)
        self.assertLess(got["rms"], cc.RIM_RMS_MAX)

    def test_a_ring_half_outside_the_widget_still_fits(self):
        sg = static(1)
        got = reader(sg).read(with_circle(sg, (99.0, 245.0), 151.6), None)
        self.assertTrue(got["present"], got)
        self.assertAlmostEqual(got["r"], 151.6, delta=1.0)

    def test_the_static_alone_reads_no_circle(self):
        sg = static(2)
        img = cv2.cvtColor(sg.astype(np.uint8), cv2.COLOR_GRAY2BGR)
        got = reader(sg).read(img, None)
        self.assertFalse(got["present"])

    def test_a_ring_of_another_radius_is_not_hers(self):
        sg = static(3)
        got = reader(sg).read(with_circle(sg, (230.0, 230.0), 120.0), None)
        self.assertFalse(got["present"])

    def test_the_radius_window_narrows_where_the_fact_measures_the_map(self):
        sg = static()
        self.assertEqual(reader(sg).radius_window, cc.RADIUS_WINDOW_MEASURED)
        self.assertEqual(reader(sg, r_base=140.87, r_from="lotus").radius_window,
                         cc.RADIUS_WINDOW)


class OpportunityGate(unittest.TestCase):
    ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100000.0},
              {"round_no": 2, "t_start_ms": 120000.0, "t_end_ms": 200000.0}]

    def test_a_window_runs_from_the_death_to_the_round_end(self):
        w = cc.opportunity_windows([{"t_ms": 40000.0, "death_id": "d1"}], self.ROUNDS)
        self.assertEqual([(x["t0_ms"], x["t1_ms"], x["end"]) for x in w],
                         [(40000.0, 100000.0, "round_end")])

    def test_a_revive_or_the_next_death_ends_it_first(self):
        w = cc.opportunity_windows([{"t_ms": 130000.0}, {"t_ms": 150000.0}], self.ROUNDS,
                                   revives_ms=[135000.0])
        self.assertEqual([(x["t1_ms"], x["end"]) for x in w],
                         [(135000.0, "revive"), (200000.0, "round_end")])

    def test_a_death_between_rounds_opens_nothing(self):
        self.assertEqual(cc.opportunity_windows([{"t_ms": 110000.0}], self.ROUNDS), [])

    @mock.patch("reticle.minimap.widget_drawn", return_value=True)
    def test_the_reader_reads_only_inside_its_windows(self, _drawn):
        sg = static()
        r = reader(sg, [{"t0_ms": 1000.0, "t1_ms": 2000.0}])
        frame = with_circle(sg, (201.3, 225.7), 151.6)
        r.feed(SimpleNamespace(t_ms=5000.0, frame_idx=0, frame=frame))
        self.assertEqual(r.rows[-1]["reason"], "outside_windows")
        self.assertEqual(r.spans, [(1000.0, 2000.0)])

    @mock.patch("reticle.minimap.widget_drawn", return_value=True)
    def test_a_circle_round_the_living_players_icon_is_the_audio_circle(self, _drawn):
        sg = static()
        frame = with_circle(sg, (201.3, 225.7), 151.6)
        track = (np.array([1400.0, 1600.0]), np.array([201.0, 201.0]), np.array([226.0, 226.0]))
        ally = reader(sg, [{"t0_ms": 1000.0, "t1_ms": 2000.0, "player_death": False}], track)
        ally.feed(SimpleNamespace(t_ms=1500.0, frame_idx=0, frame=frame))
        self.assertEqual(ally.rows[-1]["reason"], "concentric_with_self")
        mine = reader(sg, [{"t0_ms": 1000.0, "t1_ms": 2000.0, "player_death": True}], track)
        mine.feed(SimpleNamespace(t_ms=1500.0, frame_idx=0, frame=frame))
        self.assertTrue(mine.rows[-1]["present"])


def circle_rows(t0_s, t1_s, c=(200.0, 225.0), r=151.6):
    return [{"kind": "coverage"}] + [
        {"kind": "frame", "t_ms": t * 1000.0, "present": True, "cx": c[0], "cy": c[1], "r": r}
        for t in np.arange(t0_s, t1_s + 1e-6, 0.25)]


class CircleChannel(unittest.TestCase):
    def runs(self, *spans):
        rows = [x for a, b in spans for x in circle_rows(a, b)[1:]]
        return smoke_owner.circle_runs(smoke_owner.circle_samples(rows))

    def test_a_disc_born_as_a_run_ends_inside_it_is_cloves(self):
        t = {"first_ms": 411320.0, "cx": 180.0, "cy": 235.0}
        agent, why, ev = smoke_owner.circle_verdict(t, self.runs((409.25, 411.75)), None, "s")
        self.assertEqual((agent, why), ("Clove", None))
        self.assertTrue(ev["rests_on"])

    def test_a_disc_born_mid_run_is_not_witnessed(self):
        t = {"first_ms": 947000.0, "cx": 302.0, "cy": 410.0}
        agent, why, _ = smoke_owner.circle_verdict(t, self.runs((946.25, 950.75)), None, "s")
        self.assertEqual((agent, why), (None, "no_circle_near_birth"))

    def test_a_disc_beyond_the_reach_is_not_witnessed(self):
        t = {"first_ms": 411320.0, "cx": 200.0 + 151.6 * 1.2, "cy": 225.0}
        agent, why, _ = smoke_owner.circle_verdict(t, self.runs((409.25, 411.5)), None, "s",
                                                   reach=1.09)
        self.assertEqual((agent, why), (None, "disc_outside_circle"))

    def test_no_stream_abstains_with_its_reason(self):
        self.assertEqual(smoke_owner.circle_verdict({"first_ms": 0.0}, None, "no_team_clove",
                                                    "s")[:2], (None, "no_team_clove"))


def owner(t_s, eid, group=None, agent="Clove"):
    return {"kind": "smoke_owner", "entity_id": eid, "first_ms": t_s * 1000.0, "agent": agent,
            "cast_group": group or [eid]}


class DeadRuse(unittest.TestCase):
    ROUNDS = [{"round_no": 5, "t_start_ms": 375000.0, "t_end_ms": 487000.0}]
    PARAMS = {"max_charges": 2, "restock_min_s": 30.0}

    def test_each_birth_sample_after_the_death_is_one_cast(self):
        rows = [owner(390.0, "a"), owner(411.3, "b"), owner(455.6, "c", ["c", "d"]),
                owner(455.6, "d", ["c", "d"]), owner(470.0, "e", agent=None)]
        got = dead_ruse_casts("Clove", [405500.0], [], self.ROUNDS, rows, {405500.0: 2},
                              self.PARAMS)
        self.assertEqual([(r["t_ms"], r["clouds"]) for r in got["rows"]],
                         [(411300.0, 1), (455600.0, 2)])
        self.assertTrue(all(r["player_cast"] and r["dead_ruse_version"] == DEAD_RUSE_VERSION
                            for r in got["rows"]))

    def test_the_charges_held_bound_the_clouds(self):
        rows = [owner(406.0, "a"), owner(407.0, "b"), owner(408.0, "c")]
        got = dead_ruse_casts("Clove", [405500.0], [], self.ROUNDS, rows, {405500.0: 1},
                              self.PARAMS)
        # One held, one restock running: two clouds at most before 30 s pass.
        self.assertEqual([r["player_cast"] for r in got["rows"]], [True, True, False])
        self.assertEqual(got["rows"][2]["reason"], "beyond_charge_bound")
        self.assertEqual([r["needs_restock"] for r in got["rows"]], [False, True, True])

    def test_a_revive_ends_the_dead_window(self):
        rows = [owner(420.0, "a")]
        got = dead_ruse_casts("Clove", [405500.0], [410000.0], self.ROUNDS, rows, None,
                              self.PARAMS)
        self.assertEqual(got["rows"], [])

    def test_only_a_clove_player_casts_while_dead(self):
        got = dead_ruse_casts("Sova", [405500.0], [], self.ROUNDS, [owner(411.3, "a")])
        self.assertEqual((got["rows"], got["reason"]), ([], "not_clove"))

    def test_the_state_models_owner_death_rows_give_the_charges(self):
        state = [{"kind": "verdict", "transition": "owner_death", "slot": "E", "t_ms": 405500.0,
                  "before": {"charges": 1}},
                 {"kind": "verdict", "transition": "owner_death", "slot": "Q", "t_ms": 405500.0,
                  "before": {"charges": 0}}]
        self.assertEqual(held_at_deaths(state), {405500.0: 1})


if __name__ == "__main__":
    unittest.main()
