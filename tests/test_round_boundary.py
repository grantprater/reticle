"""Which round an event near a round boundary belongs to."""
from __future__ import annotations

import unittest

from reticle.rounds import (_clock_reset_after, _reset_after, final_round, in_round_window,
                            match_over, match_round, place_unread_starts, round_bounds,
                            round_closes, round_containing, side_in_round, starting_side)


class SideByRound(unittest.TestCase):
    """[domain:rounds/side-by-round]: halves of 12, overtime cycles open on
    the starting side; an unread start or round is null with a reason."""

    def test_halves_and_overtime(self):
        got = {n: side_in_round(n, "attack")[0] for n in (1, 12, 13, 24, 25, 26, 27, 28)}
        self.assertEqual(got, {1: "attack", 12: "attack", 13: "defence", 24: "defence",
                               25: "attack", 26: "defence", 27: "attack", 28: "defence"})
        self.assertEqual(side_in_round(13, "defence"), ("attack", None))

    def test_unread_is_null_with_a_reason(self):
        self.assertEqual(side_in_round(5, None), (None, "starting_side_unread"))
        self.assertEqual(side_in_round(None, "attack"), (None, "match_round_unread"))

    def test_match_round_is_the_score_before_plus_one(self):
        self.assertEqual(match_round({"round_no": 1, "score_us": 7, "score_them": 5}), 13)
        self.assertEqual(match_round({"left_before": 12, "right_before": 12}), 25)
        self.assertIsNone(match_round({"round_no": 3, "score_us": None, "score_them": 2}))



def _frame(t, slot=0, carried=True):
    """A stored `spike` frame: our marker in `slot` (None: no marker) and a
    carried glyph on our minimap or none."""
    glyphs = [{"reason": None, "state": "carried", "cx": 10.0, "cy": 10.0}] if carried else []
    return {"kind": "frame", "t_ms": float(t), "reason": None, "rotation": 0, "icons": [],
            "glyphs": glyphs, "marker": {"slot": slot, "reason": None if slot is not None else "no_marker"}}


def _round(n, a, z, before):
    return {"round_no": n, "t_start_ms": float(a), "t_end_ms": float(z),
            "score_us": before, "score_them": 0}


class StartingSide(unittest.TestCase):
    """`starting_side` reads only what the attackers produce: an agreed
    carrier frame or a planter slot, through the side rule; it refuses on a
    conflict or no evidence, never defaulting."""

    HEAD = {"kind": "coverage", "widget_scale": 1.0}

    def test_attack_in_the_second_half_means_a_defence_start(self):
        rounds = [_round(1, 0, 100, 0), _round(2, 110, 200, 12)]   # match rounds 1 and 13
        spike = [self.HEAD, _frame(150)]
        carrier = [{"kind": "round", "round_no": 2, "spike_planted": True, "planter_slot": {"slot": 0}}]
        got = starting_side(rounds, spike, carrier)
        self.assertEqual((got["starting_side"], got["reason"]), ("defence", None))
        self.assertEqual({v["channel"] for v in got["votes"]}, {"carrier", "planter"})

    def test_one_channel_alone_votes_nothing(self):
        rounds = [_round(1, 0, 100, 0)]
        spike = [self.HEAD, _frame(50, slot=None), _frame(60, carried=False)]
        got = starting_side(rounds, spike, [{"kind": "round", "round_no": 1, "planter_slot": None}])
        self.assertEqual((got["starting_side"], got["reason"]), (None, "no_attack_evidence"))

    def test_conflict_refuses_and_stores_the_rounds(self):
        rounds = [_round(1, 0, 100, 0), _round(2, 110, 200, 12)]
        spike = [self.HEAD, _frame(50), _frame(150)]
        got = starting_side(rounds, spike, [{"kind": "round", "round_no": 1, "planter_slot": None}])
        self.assertEqual((got["starting_side"], got["reason"]), (None, "starting_side_conflict"))
        self.assertEqual(got["disagreements"][-1]["rounds"], {"attack": [1], "defence": [2]})

    def test_cross_channel_disagreements_are_stored(self):
        rounds = [_round(1, 0, 100, 0), _round(2, 110, 200, 1)]
        spike = [self.HEAD, _frame(50)]
        carrier = [{"kind": "round", "round_no": 1, "spike_planted": True, "planter_slot": None},
                   {"kind": "round", "round_no": 2, "spike_planted": True, "planter_slot": {"slot": 1}}]
        got = starting_side(rounds, spike, carrier)
        self.assertEqual(got["starting_side"], "attack")
        self.assertEqual([d["check"] for d in got["disagreements"]],
                         ["carrier_without_planter", "planter_without_agreed_carrier"])

    def test_missing_streams_refuse(self):
        self.assertEqual(starting_side([_round(1, 0, 100, 0)], None, [])["reason"], "spike_unread")


def _ev(t):
    return {"t_first": float(t)}


def _times(seq):
    return [e["t_first"] for e in seq]


class RoundBoundary(unittest.TestCase):
    def test_an_event_at_the_end_belongs_to_the_round_it_ends(self):
        got = in_round_window([_ev(100), _ev(527.5)], 100.0, 527.5, 535.0, ends={527.5})
        self.assertEqual(_times(got), [100.0, 527.5])

    def test_touching_rounds_count_the_shared_instant_once(self):
        ends = {447.5, 527.5}
        seq = [_ev(447.5)]
        first = in_round_window(seq, 335.0, 447.5, 447.5, ends)
        second = in_round_window(seq, 447.5, 527.5, 535.0, ends)
        self.assertEqual((len(first), len(second)), (1, 0))

    def test_a_post_round_kill_belongs_to_the_round_just_decided(self):
        ends = {927.5, 1008.0}
        seq = [_ev(929.0)]
        self.assertEqual(_times(in_round_window(seq, 864.5, 927.5, 935.5, ends)), [929.0])
        self.assertEqual(in_round_window(seq, 935.5, 1008.0, 1015.5, ends), [])

    def test_the_last_round_closes_one_median_gap_after_its_end(self):
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 100.0},
                  {"t_start_ms": 107.0, "t_end_ms": 200.0},
                  {"t_start_ms": 209.0, "t_end_ms": 300.0}]
        self.assertEqual(round_closes(rounds), [107.0, 209.0, 308.0])


class UnreadStart(unittest.TestCase):
    """A round whose buy-phase reset went unread starts one median post-round
    gap after the previous end, so the previous round keeps its post-round
    events (`place_unread_starts`, round-0.9.0)."""

    def _rounds(self):
        return [{"t_start_ms": 0.0, "t_end_ms": 100.0, "start_source": "capture_start"},
                {"t_start_ms": 107.0, "t_end_ms": 200.0, "start_source": "clock_reset"},
                {"t_start_ms": 200.0, "t_end_ms": 300.0, "start_source": "score_increment"},
                {"t_start_ms": 309.0, "t_end_ms": 400.0, "start_source": "clock_reset"}]

    def test_the_unread_start_moves_one_median_gap_and_says_so(self):
        rounds = place_unread_starts(self._rounds())
        self.assertEqual([r["t_start_ms"] for r in rounds], [0.0, 107.0, 208.0, 309.0])
        self.assertEqual(rounds[2]["start_source"], "post_round_gap")
        self.assertEqual(rounds[0]["start_source"], "capture_start")

    def test_a_post_round_event_stays_in_the_round_just_decided(self):
        rounds = place_unread_starts(self._rounds())
        for r, c in zip(rounds, round_closes(rounds)):
            r["t_close_ms"] = c
        self.assertEqual(round_containing(203.0, rounds)["t_end_ms"], 200.0)
        self.assertEqual(round_containing(200.0, rounds)["t_end_ms"], 200.0)   # the decisive event
        self.assertEqual(round_containing(208.0, rounds)["t_end_ms"], 300.0)
        self.assertEqual(round_containing(150.0, rounds)["t_end_ms"], 200.0)   # unchanged

    def test_without_a_read_reset_the_score_increment_start_stays(self):
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 100.0, "start_source": "capture_start"},
                  {"t_start_ms": 100.0, "t_end_ms": 200.0, "start_source": "score_increment"}]
        place_unread_starts(rounds)
        self.assertEqual((rounds[1]["t_start_ms"], rounds[1]["start_source"]),
                         (100.0, "score_increment"))

    def test_the_start_never_passes_the_rounds_own_end(self):
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 100.0, "start_source": "capture_start"},
                  {"t_start_ms": 130.0, "t_end_ms": 200.0, "start_source": "clock_reset"},
                  {"t_start_ms": 200.0, "t_end_ms": 210.0, "start_source": "score_increment"}]
        place_unread_starts(rounds)
        self.assertEqual(rounds[2]["t_start_ms"], 210.0)


_HELD = {  # stored death first-seen times after a round's end -> the round Riot puts them in
    "c62c2b06bcfb": {109000.0: 1, 326000.0: 3, 328500.0: 3},
    "59c70f1ef720": {984500.0: 10},
}


def _stored_hud(sid):
    from reticle.store import DEFAULT_STORE, Store
    store = Store(DEFAULT_STORE)
    try:
        man = store.read_manifest(sid)
    except Exception:
        return None
    path = store.hud_path(sid, man["ingested_at"][:10])
    if not path.exists():
        return None
    import pyarrow.parquet as pq
    return pq.read_table(path)


class StartAfterPlant(unittest.TestCase):
    """The buy-phase start after a planted round: the graphic hides the clock,
    so the last reading before the end is the pre-plant round clock, and no
    buy reading jumps above it."""

    def _planted(self, post_round=None):
        """A round clock to 70 s, the graphic for 30 s across the end at 40 s,
        an optional post-round countdown, then a buy clock from 28 s down."""
        t, clock, graphic = [], [], {}
        for k in range(20):                        # live clock 80 -> 70.5 s
            t.append(k * 500.0); clock.append(80000.0 - k * 500)
        for k in range(20, 80):                    # the graphic, clock unread
            t.append(k * 500.0); clock.append(None)
            graphic[k * 500.0] = {"score": 1.0}
        for v in (post_round or []):
            t.append(t[-1] + 500.0); clock.append(v)
        for k in range(10):                        # buy clock 28 s down
            t.append(t[-1] + 500.0); clock.append(28000.0 - k * 500)
        return t, clock, graphic

    def test_the_first_buy_reading_starts_the_round(self):
        t, clock, graphic = self._planted()
        first_buy = t[clock.index(28000.0)]
        self.assertEqual(_reset_after(t, clock, 30000.0, graphic),
                         (first_buy, "buy_clock_after_unread"))
        self.assertEqual(_clock_reset_after(t, clock, 30000.0, graphic), first_buy)

    def test_an_unread_stretch_alone_marks_the_reading_stale(self):
        t, clock, _ = self._planted()
        self.assertEqual(_reset_after(t, clock, 30000.0)[1], "buy_clock_after_unread")

    def test_a_read_jump_still_wins(self):
        t, clock, graphic = self._planted(post_round=[3000.0, 2500.0])
        self.assertEqual(_reset_after(t, clock, 30000.0, graphic),
                         (t[clock.index(28000.0)], "clock_reset"))

    def test_a_fresh_reading_without_a_jump_stays_unread(self):
        """The buy clock already showing when the increment is read: no
        stretch, no graphic, so the start stays unread."""
        t = [k * 500.0 for k in range(20)]
        clock = [28000.0 - k * 500 for k in range(20)]
        self.assertIsNone(_reset_after(t, clock, 2000.0, {}))

    def test_round_bounds_labels_the_start(self):
        t, clock, graphic = self._planted()
        left = [0 if x <= 30000.0 else 1 for x in t]
        left[-1] = 2                               # the next round ends
        rounds = round_bounds(t, left, [0] * len(t), clock, graphic)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(rounds[0]["t_end_ms"], t[left.index(1)])
        self.assertEqual((rounds[1]["t_start_ms"], rounds[1]["start_source"]),
                         (t[clock.index(28000.0)], "buy_clock_after_unread"))


@unittest.skipUnless(all(_stored_hud(s) is not None for s in _HELD), "no stored HUD for the held sessions")
class StoredPostRoundDeaths(unittest.TestCase):
    """Regression on stored rows: the post-round deaths that carried the NEXT
    round's number on the two held-out sessions fall in their own round."""

    def test_post_round_deaths_carry_their_own_round(self):
        from reticle.rounds import build_rounds
        for sid, want in _HELD.items():
            rounds = build_rounds(_stored_hud(sid))
            got = {t: round_containing(t, rounds)["round_no"] for t in want}
            self.assertEqual(got, want, sid)



class MatchEnd(unittest.TestCase):
    def test_the_match_end_rule(self):
        self.assertTrue(match_over(13, 11))
        self.assertFalse(match_over(13, 12))      # overtime: not two ahead
        self.assertFalse(match_over(12, 12))
        self.assertTrue(match_over(15, 13))
        self.assertFalse(match_over(10, 2))       # a capture cut short, or a surrender

    def _session(self, final_scores):
        # Last decided round ends at 100 s at 12-6; the buy-phase clock resets
        # at 107 s and the scoreline is read until 190 s.
        t = [float(x) for x in range(95, 200)]
        clock = [5000 if x < 107 else 30000 - (x - 107) * 100 for x in range(95, 200)]
        left = [12 if x >= 100 else 11 for x in range(95, 200)]
        right = [6] * len(t)
        if final_scores is None:
            left = [v if x < 191 else None for v, x in zip(left, range(95, 200))]
            right = [v if x < 191 else None for v, x in zip(right, range(95, 200))]
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 100.0, "left_before": 11,
                   "right_before": 6, "won_left": True}]
        return t, left, right, clock, rounds

    def test_an_unread_final_round_is_inferred_with_its_winner(self):
        t, left, right, clock, rounds = self._session(None)
        got = final_round(t, left, right, clock, rounds)
        self.assertEqual((got["t_start_ms"], got["t_end_ms"], got["won_left"]), (107.0, 190.0, True))
        self.assertEqual(got["end_source"], "match_end_rule")

    def test_no_final_round_when_no_single_result_ends_the_match(self):
        t, left, right, clock, rounds = self._session(None)
        rounds[0].update(left_before=9, right_before=2)      # 10-2 after it
        self.assertIsNone(final_round(t, left, right, clock, rounds))



class SecondLife(unittest.TestCase):
    def _obs(self, t, badge):
        return {"kind": "second_life_observation", "t_ms": float(t), "has_badge": badge,
                "player_death": True}

    def test_a_badged_entry_is_a_second_life_and_an_unread_one_is_unknown(self):
        from reticle.adjudication.death import second_life_death
        obs = [self._obs(1577000, True), self._obs(1577500, True), self._obs(1578000, False),
               self._obs(1594000, False)]
        self.assertTrue(second_life_death(1576500, 1579500, obs))
        self.assertFalse(second_life_death(1593500, 1598000, obs))
        self.assertIsNone(second_life_death(1000, 2000, obs))

    def test_split_keeps_unread_deaths_and_a_stale_stream_splits_nothing(self):
        from reticle.adjudication.death import split_second_lives, stored_second_life
        obs = [self._obs(1577000, True), self._obs(1594000, False)]
        tracks = [{"t_first": 1576500.0, "t_last": 1579500.0},
                  {"t_first": 1593500.0, "t_last": 1598000.0},
                  {"t_first": 1000.0, "t_last": 2000.0}]
        deaths, lives = split_second_lives(tracks, obs)
        self.assertEqual([d["t_first"] for d in deaths], [1593500.0, 1000.0])
        self.assertEqual([d["t_first"] for d in lives], [1576500.0])
        self.assertEqual(split_second_lives(tracks, None), (tracks, []))
        rows = [{"killfeed_portrait_version": "v1", "kind": "portrait_observation"},
                {"kind": "second_life_observation", "t_ms": 1.0, "has_badge": True}]
        self.assertEqual(len(stored_second_life(rows, "v1")), 1)
        self.assertIsNone(stored_second_life(rows, "v2"))
        self.assertIsNone(stored_second_life([], "v1"))



class SessionEntries(unittest.TestCase):
    def test_simultaneous_entries_are_two_and_the_player_death_is_matched(self):
        from reticle.adjudication.death import death_key, session_entries
        t = [float(x) for x in range(0, 10001, 500)]
        on = [6000 <= x <= 9500 for x in t]
        hud = {"t_ms": t,
               "kf_entry_mask": [3 if o else 0 for o in on],
               "kf_ally_mask": [2 if o else 0 for o in on],
               "kf_enemy_mask": [1 if o else 0 for o in on],
               "kf_kill_mask": [1 if o else 0 for o in on],
               "kf_death_mask": [2 if o else 0 for o in on]}
        got = sorted(session_entries(hud), key=lambda e: e["slot"])
        self.assertEqual([(e["slot"], e["side"], e["kf_player_kill"], e["kf_player_death"])
                          for e in got],
                         [(0, "enemy", True, False), (1, "ally", False, True)])
        self.assertEqual(len({death_key("s", e["t_ms"], e["slot"]) for e in got}), 2)

    def test_a_kill_joins_the_entry_whose_divider_agrees_at_its_onset(self):
        """bdfdcf009dba 294.0 s: the player's kill entry (divider 233) expired,
        and a later entry in its slot (227, then 223) ran on in its track; the
        entry's last divider disagreed with the kill's and the kill went
        unmarked. The weld split now cuts that track at the empty samples
        [domain:killfeed/entry-lifetime], so the kill keeps its own entry and
        the later one stands apart."""
        from reticle.adjudication.death import session_entries
        t = [float(x) for x in range(0, 10001, 500)]
        div = [233 if x <= 4500 else 0 if x < 6000 else 227 if x == 6000 else 223 for x in t]
        on = [d > 0 for d in div]
        hud = {"t_ms": t, "kf_entry_mask": [int(o) for o in on], "kf_entry_wx": div,
               "kf_ally_mask": [0] * len(t), "kf_enemy_mask": [int(o) for o in on],
               "kf_kill_mask": [int(x <= 4500) for x in t],
               "kf_kill_wx": [233 if x <= 4500 else 0 for x in t],
               "kf_death_mask": [0] * len(t)}
        got = session_entries(hud)
        self.assertEqual([(e["t_first"], e["t_last"], e["kf_player_kill"]) for e in got],
                         [(0.0, 4500.0, True), (6000.0, 10000.0, False)])

    def test_an_entry_unread_at_its_onset_takes_its_tracks_first_read_side(self):
        """bdfdcf009dba 672.0 s: Evan -> TunaNoCrust appears in slot 3 under
        the Shooting Error overlay, victim plate unread, and reads an enemy
        victim from 674.5 s on. The entry's side is enemy, not unknown."""
        from reticle.adjudication.death import session_entries
        # (t, entry mask, packed dividers, ally mask, enemy mask), hud-0.17.0
        rows = [(671000.0, 3, 172749, 2, 1), (671500.0, 7, 58893005, 2, 5),
                (672000.0, 15, 58893005, 2, 5), (672500.0, 15, 59155149, 2, 5),
                (673000.0, 15, 58893005, 2, 5), (673500.0, 15, 58893005, 2, 5),
                (674000.0, 14, 59169280, 2, 4), (674500.0, 7, 48087889, 1, 6),
                (675000.0, 6, 48087552, 0, 6), (675500.0, 3, 93921, 0, 3),
                (676000.0, 3, 93921, 0, 3), (676500.0, 2, 93696, 0, 2),
                (677000.0, 0, 0, 0, 0)]
        t, mask, wx, ally, enemy = (list(c) for c in zip(*rows))
        hud = {"t_ms": t, "kf_entry_mask": mask, "kf_entry_wx": wx,
               "kf_ally_mask": ally, "kf_enemy_mask": enemy,
               "kf_kill_mask": [0] * len(t), "kf_death_mask": [0] * len(t)}
        got = {e["t_first"]: e for e in session_entries(hud)}
        self.assertEqual((got[672000.0]["slot"], got[672000.0]["side"],
                          got[672000.0]["victim_ally"]), (3, "enemy", False))

    def test_an_entry_carries_its_tracks_reads_as_it_rises(self):
        """The same entry's track follows it from slot 3 up the stack; its
        `(t_ms, slot)` reads seed the portrait follow (`entry_follow`)."""
        from reticle.adjudication.death import session_entries
        rows = [(671000.0, 3, 172749, 2, 1), (671500.0, 7, 58893005, 2, 5),
                (672000.0, 15, 58893005, 2, 5), (672500.0, 15, 59155149, 2, 5),
                (673000.0, 15, 58893005, 2, 5), (673500.0, 15, 58893005, 2, 5),
                (674000.0, 14, 59169280, 2, 4), (674500.0, 7, 48087889, 1, 6),
                (675000.0, 6, 48087552, 0, 6), (675500.0, 3, 93921, 0, 3),
                (676000.0, 3, 93921, 0, 3), (676500.0, 2, 93696, 0, 2),
                (677000.0, 0, 0, 0, 0)]
        t, mask, wx, ally, enemy = (list(c) for c in zip(*rows))
        hud = {"t_ms": t, "kf_entry_mask": mask, "kf_entry_wx": wx,
               "kf_ally_mask": ally, "kf_enemy_mask": enemy,
               "kf_kill_mask": [0] * len(t), "kf_death_mask": [0] * len(t)}
        reads = {e["t_first"]: e for e in session_entries(hud)}[672000.0]["reads"]
        self.assertEqual(reads[0], (672000.0, 3))
        self.assertLess(reads[-1][1], 3)
        self.assertEqual([s for _, s in reads], sorted((s for _, s in reads), reverse=True))


class SplitTracks(unittest.TestCase):
    def _tr(self, a, z, slot, sig):
        return {"t_first": float(a), "t_last": float(z), "slot": slot, "sig": sig, "n_obs": 2}

    def test_an_attribution_dropout_and_a_slot_rise_are_one_entry(self):
        from reticle.checks import merge_split_tracks
        got = merge_split_tracks([self._tr(106500, 107000, 0, 276), self._tr(110000, 111000, 0, 276),
                                  self._tr(409000, 409500, 1, 233), self._tr(413000, 413500, 0, 233)])
        self.assertEqual(len(got), 2)

    def test_overlapping_or_too_long_or_other_column_tracks_stay_apart(self):
        from reticle.checks import merge_split_tracks
        self.assertEqual(len(merge_split_tracks([self._tr(0, 4000, 0, 200), self._tr(3000, 7000, 1, 200)])), 2)
        self.assertEqual(len(merge_split_tracks([self._tr(0, 4000, 0, 200), self._tr(5000, 9000, 0, 200)])), 2)
        self.assertEqual(len(merge_split_tracks([self._tr(0, 1000, 0, 200), self._tr(3000, 4000, 0, 240)])), 2)
        self.assertEqual(len(merge_split_tracks([self._tr(0, 1000, 0, 200), self._tr(3000, 4000, 1, 200)])), 2)


if __name__ == "__main__":
    unittest.main()
