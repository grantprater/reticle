"""`adjudication.spectate`: the player's death intervals and the spectate switch."""
import unittest

from reticle.adjudication import spectate


def _death(t, **kw):
    row = {"kind": "death_verdict", "t_ms": t, "kf_player_death": True,
           "is_second_life": False, "is_revive": False, "victim": "Phoenix",
           "death_id": f"death:s:{int(t)}:0"}
    row.update(kw)
    return row


ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 90_000.0},
          {"round_no": 2, "t_start_ms": 100_000.0, "t_end_ms": 190_000.0}]


def _track(points):
    """Self points every 66.7 ms from (t0, x, y) runs."""
    out = []
    for t0, t1, x, y in points:
        t = t0
        while t < t1:
            out.append((t, x, y))
            t += 1000.0 / 15
    return out


class TestIntervals(unittest.TestCase):
    def test_killfeed_death_to_next_round(self):
        ivs = spectate.player_dead_intervals([_death(40_000.0)], ROUNDS)
        self.assertEqual(len(ivs), 1)
        iv = ivs[0]
        self.assertEqual((iv.t0_ms, iv.t1_ms, iv.rests_on, iv.t1_why),
                         (40_000.0, 100_000.0, "killfeed_death", "next_round_start"))
        self.assertTrue(iv.holds(95_000.0))
        self.assertFalse(iv.holds(100_000.0))

    def test_second_life_and_other_deaths_are_not_his(self):
        rows = [_death(40_000.0, is_second_life=True), _death(50_000.0, kf_player_death=False),
                _death(60_000.0, is_revive=True)]
        self.assertEqual(spectate.player_dead_intervals(rows, ROUNDS), [])

    def test_revive_naming_him_ends_the_interval(self):
        rows = [_death(40_000.0), _death(52_000.0, kf_player_death=False, is_revive=True)]
        iv = spectate.player_dead_intervals(rows, ROUNDS)[0]
        self.assertEqual((iv.t1_ms, iv.t1_why), (52_000.0, "revive_verdict"))

    def test_switch_found_after_death(self):
        selves = _track([(30_000.0, 40_000.0, 100.0, 100.0),
                         (42_400.0, 46_000.0, 200.0, 150.0)])
        mates = spectate.Teammates([(t, 201.0, 151.0) for t, _x, _y in
                                    _track([(41_000.0, 46_000.0, 0, 0)])])
        iv = spectate.player_dead_intervals([_death(40_000.0)], ROUNDS, selves, mates)[0]
        self.assertAlmostEqual(iv.switch_ms, 42_400.0, delta=70)
        self.assertTrue(iv.spectated(43_000.0))
        self.assertFalse(iv.spectated(41_000.0))

    def test_a_jump_back_is_no_switch(self):
        # One frame on a teammate, then back at the player's place.
        selves = _track([(30_000.0, 40_000.0, 100.0, 100.0),
                         (42_400.0, 42_470.0, 200.0, 150.0),
                         (42_470.0, 46_000.0, 101.0, 100.0)])
        mates = spectate.Teammates([(42_400.0, 200.0, 150.0)])
        self.assertIsNone(spectate.switch_after(40_000.0, 100_000.0, selves, mates))

    def test_fallback_needs_a_roster_drop(self):
        # No death stored: the yellow icon leaves him for a teammate between
        # two frames. A jump after a gap longer than ANCHOR_GAP_MS anchors
        # nothing, so the fallback sees only a switch without a hole.
        selves = _track([(30_000.0, 42_400.0, 100.0, 100.0),
                         (42_400.0, 46_000.0, 200.0, 150.0)])
        mates = spectate.Teammates([(42_000.0, 200.0, 150.0)])
        none = spectate.player_dead_intervals([], ROUNDS, selves, mates,
                                              roster=([0.0, 39_000.0], [5, 5]))
        self.assertEqual(none, [])
        got = spectate.player_dead_intervals([], ROUNDS, selves, mates,
                                             roster=([0.0, 39_000.0], [5, 4]))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].rests_on, "spectate_switch")
        self.assertAlmostEqual(got[0].t0_ms, 42_400.0, delta=70)
        self.assertEqual(got[0].t1_ms, 100_000.0)

    def test_index(self):
        ivs = spectate.player_dead_intervals([_death(40_000.0), _death(150_000.0)], ROUNDS)
        ix = spectate.DeadIndex(ivs)
        self.assertIsNone(ix.at(39_000.0))
        self.assertEqual(ix.at(41_000.0).t0_ms, 40_000.0)
        self.assertIsNone(ix.at(120_000.0))
        self.assertEqual(ix.at(160_000.0).t1_why, "capture_end")


if __name__ == "__main__":
    unittest.main()
