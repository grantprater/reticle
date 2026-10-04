"""The three killfeed track faults the Riot scorer found (2026-10-03).

* A frozen capture hides the motion the stall reader keys on; the frozen game
  clock extends the stall (`stalls.spans`).
* An entry drawn once at a stall's end is an entry (`checks.track_entries`).
* One entry read as two tracks is one death (`death.same_entry`,
  `merge_split_entries`); a band nothing else attests is no death
  (`death.unwitnessed_entry`).
* The scorer counts a kill inside a stall as unobservable and pairs names
  across a stall (`riot_ground_truth` 0.3.2).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from reticle.adjudication.death import (merge_split_entries, refuse_unwitnessed,
                                        same_entry, unwitnessed_entry)
from reticle.checks import stack_apart, track_entries
from reticle.stalls import frozen_clock_runs, spans

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_ground_truth as rg  # noqa: E402


def verdict(t, victim=None, killer=None, revive=False, second_life=False, channels=(),
            claims=(), death_id=None):
    return SimpleNamespace(t_ms=t, victim=victim, killer=killer, is_revive=revive,
                           is_second_life=second_life, channels=list(channels),
                           metadata={"identity": {"claims": list(claims)}},
                           death_id=death_id or f"death:x:{int(t)}")


def entry(t0, t1, slot, side="enemy", reads=None, **kw):
    return {"t_first": t0, "t_last": t1, "slot": slot, "side": side,
            "reads": reads or [(t0, slot), (t1, slot)], **kw}


class FrozenClockTests(unittest.TestCase):
    def test_the_frozen_clock_extends_a_zero_motion_stall(self):
        t = [i * 200.0 for i in range(100)]                       # 0-19.8 s
        motion = [0.0 if 8000 <= x <= 10000 else 0.05 for x in t]
        # the clock ticks every second, then holds 40 s from 5 s to 15 s;
        # the value read first at 5 s was live for up to one tick
        clock = [40000.0 if 5000 <= x <= 15000 else 60000.0 - x for x in t]
        got = spans(t, motion, clock=(t, clock))
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["t_start_ms"], got[0]["t_end_ms"]), (6000.0, 15000.0))
        self.assertIn("clock", got[0])

    def test_a_held_clock_without_a_zero_motion_seed_is_no_stall(self):
        t = [i * 200.0 for i in range(100)]
        clock = [40000.0] * 100                                    # buy phase, say
        self.assertEqual(spans(t, [0.05] * 100, clock=(t, clock)), [])
        self.assertEqual(len(frozen_clock_runs(t, clock)), 1)

    def test_an_unread_clock_breaks_no_run_into_a_freeze(self):
        t = [i * 500.0 for i in range(10)]
        self.assertEqual(frozen_clock_runs(t, [None] * 10), [])


class ReleasedEntryTests(unittest.TestCase):
    def test_a_single_frame_at_a_stall_end_is_an_entry(self):
        t = [i * 500.0 for i in range(40)]
        masks = [1 if x == 10000.0 else 0 for x in t]
        stall = [{"t_start_ms": 4000.0, "t_end_ms": 10000.0}]
        self.assertEqual([a["refused"] for a in track_entries(t, masks)], ["single_frame"])
        got = track_entries(t, masks, stalls=stall)
        self.assertEqual([a["refused"] for a in got], [None])
        self.assertEqual(got[0]["released"], {"t_start_ms": 4000.0, "t_end_ms": 10000.0})

    def test_a_single_frame_away_from_a_stall_stays_refused(self):
        t = [i * 500.0 for i in range(40)]
        masks = [1 if x == 15000.0 else 0 for x in t]
        stall = [{"t_start_ms": 4000.0, "t_end_ms": 10000.0}]
        self.assertEqual([a["refused"] for a in track_entries(t, masks, stalls=stall)],
                         ["single_frame"])


class SameEntryTests(unittest.TestCase):
    def test_one_victim_within_one_life_rising_in_the_queue_merges(self):
        e = entry(1000.0, 2500.0, 2, reads=[(1000.0, 2), (2500.0, 2)])
        l_ = entry(3000.0, 5000.0, 1)
        m = same_entry((e, verdict(1000, "Jett", "Sova")), (l_, verdict(3000, "Jett", None)))
        self.assertEqual(m["rule"], "queue")

    def test_different_victims_never_merge(self):
        e, l_ = entry(1000.0, 2500.0, 1), entry(3000.0, 5000.0, 1)
        self.assertIsNone(same_entry((e, verdict(1000, "Jett")), (l_, verdict(3000, "Sova"))))

    def test_a_revive_between_breaks_the_merge(self):
        e, l_ = entry(1000.0, 2500.0, 1), entry(3000.0, 5000.0, 1)
        args = ((e, verdict(1000, "Jett")), (l_, verdict(3000, "Jett")))
        self.assertIsNotNone(same_entry(*args))
        self.assertIsNone(same_entry(*args, revives=[{"t_ms": 2000.0, "side": "enemy"}]))

    def test_a_later_track_below_the_earlier_is_another_entry(self):
        e = entry(1000.0, 2500.0, 0, reads=[(1000.0, 0), (2500.0, 0)])
        l_ = entry(3000.0, 5000.0, 2)
        self.assertIsNone(same_entry((e, verdict(1000, "Jett")), (l_, verdict(3000, "Jett"))))

    def test_stall_time_does_not_count_toward_the_life(self):
        stall = [{"t_start_ms": 5000.0, "t_end_ms": 19000.0}]
        e, l_ = entry(1000.0, 5000.0, 1), entry(19000.0, 20000.0, 1)
        args = ((e, verdict(1000, "Jett")), (l_, verdict(19000, "Jett")))
        self.assertIsNone(same_entry(*args))
        self.assertEqual(same_entry(*args, stalls=stall)["rule"], "queue")

    def test_a_stall_release_merges_past_one_life(self):
        # the earlier lived 8 s before the stall: past one life even
        # unstalled, yet the release at the stall's end redrew it
        stall = [{"t_start_ms": 9000.0, "t_end_ms": 19000.0}]
        e, l_ = entry(1000.0, 9000.0, 1), entry(19000.0, 20000.0, 1)
        args = ((e, verdict(1000, "Jett")), (l_, verdict(19000, "Jett")))
        self.assertIsNone(same_entry(*args))
        self.assertEqual(same_entry(*args, stalls=stall)["rule"], "stall_release")

    def test_killers_alone_merge_only_the_next_sample_in_the_same_slot(self):
        e = entry(1000.0, 1000.0, 1, reads=[(1000.0, 1)])
        nxt = entry(1500.0, 5500.0, 1)
        later = entry(3000.0, 5500.0, 1)
        self.assertEqual(same_entry((e, verdict(1000, None, "Clove")),
                                    (nxt, verdict(1500, "Jett", "Clove")))["rule"],
                         "continuation")
        self.assertIsNone(same_entry((e, verdict(1000, None, "Clove")),
                                     (later, verdict(3000, "Jett", "Clove"))))

    def test_merge_keeps_both_deaths_and_the_evidence(self):
        e, l_ = entry(1000.0, 2500.0, 1), entry(3000.0, 5000.0, 1)
        r = {"entries": [e, l_], "verdicts": [verdict(1000, "Jett"), verdict(3000, "Jett")]}
        merges = merge_split_entries([r])
        self.assertEqual(len(merges), 1)
        self.assertEqual(len(r["entries"]), 1)
        self.assertEqual(r["entries"][0]["t_last"], 5000.0)
        self.assertEqual(r["merged"][0][2]["rule"], "queue")
        self.assertEqual(r["entries"][0]["merged"][0]["absorbed"], "death:x:3000")


class UnwitnessedTests(unittest.TestCase):
    def test_a_band_nothing_names_or_observes_is_refused(self):
        r = {"entries": [entry(1000.0, 3000.0, 5)],
             "verdicts": [verdict(1000, channels=("killfeed_portrait",),
                                  claims=[{"channel": "killfeed_portrait", "agent": None,
                                           "reason": "no_match"}])]}
        got = refuse_unwitnessed([r])
        self.assertEqual([g["reason"] for g in got], ["no_role_named_no_observer"])
        self.assertEqual(r["entries"], [])
        self.assertEqual(len(r["refused"]), 1)

    def test_a_roster_drop_or_a_read_weapon_attests_an_unnamed_death(self):
        self.assertIsNone(unwitnessed_entry(entry(1000.0, 3000.0, 1),
                                            verdict(1000, channels=("roster_diff",))))
        self.assertIsNone(unwitnessed_entry(
            entry(1000.0, 3000.0, 1, weapon_evidence={"status": "resolved"}), verdict(1000)))
        self.assertIsNone(unwitnessed_entry(entry(1000.0, 3000.0, 1),
                                            verdict(1000, claims=[{"agent": "Jett"}])))

    def test_a_revive_is_never_refused(self):
        self.assertIsNone(unwitnessed_entry(entry(1000.0, 3000.0, 1), verdict(1000, revive=True)))


class ScorerStallTests(unittest.TestCase):
    def test_stall_time_does_not_count_toward_the_name_pass(self):
        stall = [{"t_start_ms": 2000.0, "t_end_ms": 12000.0}]
        self.assertEqual(rg.stalled_ms(1000.0, 13000.0, stall), 10000.0)
        self.assertEqual(rg.stalled_ms(13000.0, 1000.0, stall), 10000.0)
        self.assertEqual(rg.stalled_ms(0.0, 1000.0, stall), 0.0)
        self.assertIs(rg.in_stall(5000.0, stall), stall[0])
        self.assertIsNone(rg.in_stall(13000.0, stall))
        self.assertIsNone(rg.in_stall(5000.0, None))


class StackApartTests(unittest.TestCase):
    """A band apart from the stack is no entry (`checks.stack_apart`)."""

    # b7d24102a6f6 1580.5-1585.0 s in miniature: the death recap's panel reads
    # in slot 5 under empty slots; a new entry arrives in slot 0, a second in 1.
    MASKS = [32, 32, 33, 35, 35, 35, 3, 35, 3, 1]

    def test_the_recap_panel_is_apart_and_the_stack_is_not(self):
        apart = stack_apart(self.MASKS)
        self.assertEqual([int(a) for a in apart], [32, 32, 32, 32, 32, 32, 0, 32, 0, 0])

    def test_an_entry_below_a_stack_entry_is_not_apart(self):
        self.assertEqual([int(a) for a in stack_apart([1, 3, 3, 2, 1])], [0, 0, 0, 0, 0])

    def test_one_empty_slot_above_is_not_apart(self):
        # A new entry read in slot 1 while the expiring one above has faded.
        self.assertEqual([int(a) for a in stack_apart([1, 2, 1, 1])], [0, 0, 0, 0])
        self.assertEqual([int(a) for a in stack_apart([3, 4, 6])], [0, 0, 0])

    def test_a_band_under_an_apart_band_is_apart(self):
        self.assertEqual([int(a) for a in stack_apart([48, 48, 0])], [48, 48, 0])

    def test_apart_reads_join_no_entry_and_stay_visible(self):
        t = [500.0 * i for i in range(len(self.MASKS))]
        tracks = track_entries(t, self.MASKS, stack=self.MASKS)
        counted = [(a["t_first"], a["slot_first"]) for a in tracks if a["counted"]]
        self.assertEqual(counted, [(1000.0, 0), (1500.0, 1)])
        self.assertTrue(all(a["refused"] == "stack_apart" for a in tracks if a["slot_first"] == 5))
        # Without the stack, the panel's run is an entry.
        self.assertIn((0.0, 5), [(a["t_first"], a["slot_first"])
                                 for a in track_entries(t, self.MASKS) if a["counted"]])


if __name__ == "__main__":
    unittest.main()
