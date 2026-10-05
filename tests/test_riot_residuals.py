"""Fixes for the Riot scorer's residual failures (2026-10-04).

* A name read whole and cut at its word gap is one name; a crop read once
  never bridges two names (`killfeed_names.join_fragments`).
* A revive drawn below a split track's later piece separates nothing
  (`death.same_entry`).
* An entry whose victim side went unread takes only a roster drop no sided
  entry took (`death._match_shrinks`).
* The scorer pairs a death drawn at a stall's release with a kill inside the
  stall (`riot_ground_truth._release_pass`).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from reticle.adjudication.death import _match_shrinks, entry_victim_side, same_entry
from reticle.adjudication.killfeed_names import (NCC_MIN, fragment_ncc, join_fragments, ncc,
                                                 name_clusters)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_ground_truth as rg  # noqa: E402


def _word(seed: int, w: int) -> np.ndarray:
    """A 24-row band with white glyph-like strokes on a grey plate."""
    rng = np.random.default_rng(seed)
    g = np.full((24, w), 90, np.uint8)
    for x in range(1, w - 3, 5):
        g[8:8 + int(rng.integers(4, 10)), x:x + 2] = 240
    return g


def _scatter(seed: int, w: int) -> np.ndarray:
    """A 24-row band with white strokes at random columns and rows."""
    rng = np.random.default_rng(seed)
    g = np.full((24, w), 90, np.uint8)
    for x in rng.choice(np.arange(1, w - 2), size=w // 4, replace=False):
        y = int(rng.integers(4, 14))
        g[y:y + int(rng.integers(3, 8)), x:x + 2] = 240
    return g


def _name(*words) -> np.ndarray:
    gap = np.full((24, 6), 90, np.uint8)
    parts = []
    for w in words:
        parts += [w, gap]
    return np.hstack(parts[:-1])


def _crops(**grays):
    return {eid: {"team": "ally", "me": False, "gray": g, "reason": None}
            for eid, g in grays.items()}


class FragmentJoinTests(unittest.TestCase):
    def test_a_word_of_a_name_reads_as_its_fragment(self):
        first, last = _word(1, 40), _word(3, 30)
        whole = _name(first, last)
        self.assertGreaterEqual(fragment_ncc(first, whole), NCC_MIN)
        self.assertGreaterEqual(fragment_ncc(last, whole), NCC_MIN)
        self.assertLess(fragment_ncc(_word(5, 40), whole), NCC_MIN)
        # widths within the tolerance are one reading, not a fragment
        self.assertEqual(fragment_ncc(whole[:, :-2], whole), 0.0)

    def test_clusters_of_one_name_cut_at_its_gap_join(self):
        first, last = _word(1, 40), _word(3, 30)
        whole = _name(first, last)
        crops = _crops(k1=whole, v1=first, k2=whole.copy(), v2=first.copy(), k3=last,
                       o1=_word(5, 40), o2=_word(5, 40))
        out = name_clusters(crops)
        self.assertEqual(out["sides"]["ally"], [["k1", "v1", "k2", "v2", "k3"], ["o1", "o2"]])

    def test_a_whole_name_whose_two_words_recur_joins_neither(self):
        # killfeed-name-cluster-0.5.0: the whole is a recurring cluster that
        # would join two groups that do not read one name, the shape a junk
        # crop holding two names takes, so it joins nothing.
        first, last = _word(1, 40), _word(3, 30)
        whole = _name(first, last)
        crops = _crops(k1=whole, v1=first, k2=whole.copy(), v2=first.copy(), k3=last,
                       k4=last.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"],
                         [["k1", "k2"], ["v1", "v2"], ["k3", "k4"]])

    def test_a_recurring_junk_crop_cannot_bridge_two_names(self):
        a, b = _word(1, 40), _word(7, 40)
        junk = _name(a, _word(9, 20), b)
        crops = _crops(a1=a, a2=a.copy(), b1=b, b2=b.copy(), j1=junk, j2=junk.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"],
                         [["a1", "a2"], ["b1", "b2"], ["j1", "j2"]])

    def test_two_recurring_junk_clusters_cannot_vouch_for_each_other(self):
        # killfeed-name-cluster-0.5.1: each junk cluster holds A's word and
        # B's word around a different middle; tested with the other still in
        # place, each saw A and B as one group through the other.
        a, b = _scatter(21, 44), _scatter(23, 44)
        j, k = _name(a, _scatter(25, 20), b), _name(a, _scatter(27, 20), b)
        self.assertLess(ncc(j, k), NCC_MIN)
        crops = _crops(a1=a, a2=a.copy(), b1=b, b2=b.copy(), j1=j, j2=j.copy(), k1=k, k2=k.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"],
                         [["a1", "a2"], ["b1", "b2"], ["j1", "j2"], ["k1", "k2"]])

    def test_a_word_two_names_share_at_opposite_ends_bridges_neither(self):
        # "TAG X" and "Y TAG": TAG is the left word of one and the right word
        # of the other, with a whole word beside it in each.
        tag = _scatter(31, 30)
        one, two = _name(tag, _scatter(33, 60)), _name(_scatter(35, 62), tag)
        crops = _crops(p1=one, p2=one.copy(), q1=two, q2=two.copy(), t1=tag, t2=tag.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"],
                         [["p1", "p2"], ["q1", "q2"], ["t1", "t2"]])

    def test_a_recurring_shared_word_bridges_neither(self):
        tag = _scatter(1, 30)
        one, two = _name(tag, _scatter(3, 60)), _name(tag, _scatter(5, 62))
        crops = _crops(a1=one, a2=one.copy(), b1=two, b2=two.copy(), t1=tag, t2=tag.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"],
                         [["a1", "a2"], ["b1", "b2"], ["t1", "t2"]])

    def test_a_name_with_an_icon_on_opposite_sides_joins(self):
        # 7010b3d62460: the victim crops of one name carry the neighbouring
        # icon's edge on the right, the killer crops on the left; the clean
        # crops are the left word of one and the right word of the other.
        name, icon = _scatter(1, 40), _scatter(11, 12)
        victim, killer = _name(name, icon), _name(icon, name)
        crops = _crops(n1=name, v1=victim, k1=killer, n2=name.copy(), v2=victim.copy(),
                       k2=killer.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"],
                         [["n1", "v1", "k1", "n2", "v2", "k2"]])

    def test_a_crop_read_once_joins_the_one_name_it_links_to(self):
        first, last = _word(1, 40), _word(3, 30)
        whole = _name(first, last)
        crops = _crops(v1=first, v2=first.copy(), k1=whole)
        self.assertEqual(name_clusters(crops)["sides"]["ally"], [["v1", "v2", "k1"]])
        crops = _crops(v1=first, k1=whole, k2=whole.copy())
        self.assertEqual(name_clusters(crops)["sides"]["ally"], [["v1", "k1", "k2"]])

    def test_a_word_two_names_share_bridges_neither(self):
        tag = _scatter(1, 30)
        one, two = _name(tag, _scatter(3, 60)), _name(tag, _scatter(5, 62))
        crops = _crops(a1=one, a2=one.copy(), b1=two, b2=two.copy(), t1=tag)
        self.assertEqual(name_clusters(crops)["sides"]["ally"], [["a1", "a2"], ["b1", "b2"], ["t1"]])

    def test_a_crop_read_once_joins_two_groups_that_read_one_name(self):
        # bfad2778a372: greedy clustering split one 113 px name into 28 and 8
        # crops; a 102 px crop is a word of both. The test hands the split
        # clusters to the join directly.
        first, last = _scatter(1, 60), _scatter(3, 30)
        whole = _name(first, last)
        crops = _crops(a1=whole, a2=whole.copy(), b1=whole[:, :-1].copy(), b2=whole[:, :-1].copy(),
                       w=first)
        greedy = [["a1", "a2"], ["b1", "b2"], ["w"]]
        self.assertEqual(join_fragments(greedy, crops), [["a1", "a2", "b1", "b2", "w"]])

    def test_a_singleton_junk_crop_cannot_bridge_two_names(self):
        # One junk crop holds one name at its left edge and another at its
        # right; each name recurs, the junk crop does not.
        a, b = _word(1, 40), _word(7, 40)
        crops = _crops(a1=a, a2=a.copy(), b1=b, b2=b.copy(), junk=_name(a, _word(9, 20), b))
        self.assertEqual(name_clusters(crops)["sides"]["ally"], [["a1", "a2"], ["b1", "b2"], ["junk"]])

    def test_unrelated_clusters_stay_apart(self):
        crops = _crops(a=_word(1, 40), b=_word(2, 60), c=_word(4, 30))
        self.assertEqual(join_fragments([["a"], ["b"], ["c"]], crops), [["a"], ["b"], ["c"]])


def verdict(t, victim=None, killer=None):
    return SimpleNamespace(t_ms=t, victim=victim, killer=killer, is_revive=False,
                           is_second_life=False)


def entry(t0, t1, slot, side="enemy", reads=None):
    return {"t_first": t0, "t_last": t1, "slot": slot, "side": side,
            "reads": reads or [(t0, slot), (t1, slot)]}


class ReviveBelowTests(unittest.TestCase):
    def test_a_revive_below_the_later_piece_does_not_block_the_merge(self):
        # 9acf02f98283: Killjoy -> Clove in slot 1 split at 968.5 s; the Not
        # Dead Yet revive drew in slot 2 at 967.0 s
        e, l_ = entry(966000.0, 968000.0, 1, "ally"), entry(968500.0, 970500.0, 1, "ally")
        revive = entry(967000.0, 971500.0, 2, "ally")
        args = ((e, verdict(966000, "Clove", "Killjoy")), (l_, verdict(968500, "Clove", "Killjoy")))
        below = [{"t_ms": 967000.0, "side": "ally", "entry": revive}]
        self.assertEqual(same_entry(*args, revives=below)["rule"], "queue")

    def test_a_revive_at_or_above_the_later_piece_still_blocks(self):
        e, l_ = entry(1000.0, 2500.0, 1), entry(3000.0, 5000.0, 1)
        args = ((e, verdict(1000, "Jett")), (l_, verdict(3000, "Jett")))
        level = [{"t_ms": 2000.0, "side": "enemy", "entry": entry(2000.0, 6000.0, 1)}]
        self.assertIsNone(same_entry(*args, revives=level))
        self.assertIsNone(same_entry(*args, revives=[{"t_ms": 2000.0, "side": "enemy"}]))


class UnreadSideShrinkTests(unittest.TestCase):
    def test_the_victim_side_reads_side_then_flag_then_victim_side(self):
        self.assertEqual(entry_victim_side({"side": "ally", "victim_ally": False}), "ally")
        self.assertEqual(entry_victim_side({"victim_ally": True}), "ally")
        self.assertEqual(entry_victim_side({"victim_ally": False, "victim_side": "ally"}), "enemy")
        self.assertEqual(entry_victim_side({"victim_side": "ally"}), "ally")
        self.assertEqual(entry_victim_side({}), "enemy")
        self.assertIsNone(entry_victim_side({"victim_side": None}))

    def test_an_unread_side_takes_no_drop_a_sided_entry_took(self):
        drop = {"t_ms": 1500.0}
        got = _match_shrinks([{"t_ms": 1000.0, "side": "enemy"}, {"t_ms": 1500.0, "side": "unknown"}],
                             [], [drop], 2500.0)
        self.assertEqual(got, [drop, None])

    def test_an_unread_side_takes_the_nearest_free_drop_of_either_side(self):
        d1, d2, a1 = {"t_ms": 742000.0}, {"t_ms": 744000.0}, {"t_ms": 760000.0}
        got = _match_shrinks([{"t_ms": 742000.0, "side": "unknown"},
                              {"t_ms": 744000.0, "side": "enemy"}], [a1], [d1, d2], 2500.0)
        self.assertEqual(got, [d2, d1])


class ReleasePassTests(unittest.TestCase):
    def test_a_released_death_pairs_with_a_kill_inside_its_stall(self):
        span = {"t_start_ms": 1331400.0, "t_end_ms": 1339600.0}
        kills = [{"victim": "p1", "killer": "p2"}]
        agent_of = {"p1": "Waylay", "p2": "Jett"}
        deaths = [{"t_ms": 1339500.0, "victim": None, "killer": "Jett", "released": span}]
        got = rg._release_pass(kills, deaths, agent_of, [1332747.0], [1339500.0], [])
        self.assertEqual(got, [(0, 0, 1339500.0 - 1332747.0, "stall_release")])

    def test_a_disagreeing_killer_or_a_kill_outside_the_stall_does_not_pair(self):
        span = {"t_start_ms": 1331400.0, "t_end_ms": 1339600.0}
        kills = [{"victim": "p1", "killer": "p2"}]
        agent_of = {"p1": "Waylay", "p2": "Jett"}
        sova = [{"t_ms": 1339500.0, "victim": None, "killer": "Sova", "released": span}]
        self.assertEqual(rg._release_pass(kills, sova, agent_of, [1332747.0], [1339500.0], []), [])
        jett = [{"t_ms": 1339500.0, "victim": None, "killer": "Jett", "released": span}]
        self.assertEqual(rg._release_pass(kills, jett, agent_of, [1320000.0], [1339500.0], []), [])


if __name__ == "__main__":
    unittest.main()
