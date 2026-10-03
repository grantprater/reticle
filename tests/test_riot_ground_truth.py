"""The Riot scorer's alignment and coordinate transform, on synthetic data."""
import math
import random
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_ground_truth as rg  # noqa: E402


class AlignmentTest(unittest.TestCase):
    def _synthetic(self, offset_ms, slope=1.0, n=150, drop=0.05, extra=4, seed=7):
        rnd = random.Random(seed)
        game = sorted(rnd.uniform(60_000, 2_300_000) for _ in range(n))
        store = []
        for g in game:
            if rnd.random() < drop:
                continue
            # the feed's 2 Hz grid: the first sample at or after the entry
            t = offset_ms + slope * g + rnd.uniform(0, 300)
            store.append(math.ceil(t / 500.0) * 500.0)
        store += [rnd.uniform(0, 2_400_000) for _ in range(extra)]
        return game, store

    def test_recovers_offset(self):
        game, store = self._synthetic(103_618.0)
        fit = rg.fit_alignment(game, store)
        # the offset absorbs the grid's mean lag, under 500 ms
        self.assertGreater(fit["a_ms"], 103_618.0)
        self.assertLess(fit["a_ms"], 103_618.0 + 500.0)
        self.assertAlmostEqual(fit["slope"], 1.0, delta=1e-4)
        self.assertGreaterEqual(fit["matched"], int(0.93 * len(game)))
        self.assertLess(fit["residual_mad_ms"], 250.0)

    def test_reports_drift(self):
        game, store = self._synthetic(50_000.0, slope=1.0005)
        fit = rg.fit_alignment(game, store, tol_ms=2500.0)
        self.assertAlmostEqual(fit["slope"], 1.0005, delta=1e-4)
        self.assertGreater(abs(fit["drift_ms_over_match"]), 800.0)

    def test_negative_offset(self):
        game, store = self._synthetic(-20_000.0)
        fit = rg.fit_alignment(game, [t for t in store if t > 0])
        self.assertAlmostEqual(fit["a_ms"], -20_000.0 + 250.0, delta=300.0)

    def test_match_is_one_to_one(self):
        pairs = rg.match_times([1000.0, 1100.0], [1050.0], 0.0, 1.0, 500.0)
        self.assertEqual(len(pairs), 1)
        self.assertEqual({j for _i, j, _d in pairs}, {0})


class TransformTest(unittest.TestCase):
    MAP = {"xMultiplier": 7e-05, "yMultiplier": -7e-05,
           "xScalarToAdd": 0.813895, "yScalarToAdd": 0.573242}

    def test_axis_swap(self):
        u, v = rg.game_to_uv(1000.0, 0.0, self.MAP)
        self.assertAlmostEqual(u, 0.813895)
        self.assertAlmostEqual(v, 0.573242 - 0.07)
        u2, v2 = rg.game_to_uv(1000.0, 0.0, self.MAP, swap=False)
        self.assertAlmostEqual(u2, 0.813895 + 0.07)
        self.assertAlmostEqual(v2, 0.573242)

    def test_affine_matches_the_warp(self):
        """`art_affine` lands a dot where `cv2.warpAffine` and `_place` put it."""
        import cv2

        h0, w0 = 300, 260
        fit = (270.0, 0.37, -11, 7)
        art = np.zeros((h0, w0), np.float32)
        ax, ay = 190, 60
        art[ay - 2:ay + 3, ax - 2:ax + 3] = 1.0
        rot, scale, dx, dy = fit
        M = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, scale)
        side = int(max(h0, w0) * scale * 1.6)
        M[0, 2] += side / 2 - w0 / 2
        M[1, 2] += side / 2 - h0 / 2
        r = cv2.warpAffine(art, M, (side, side), flags=cv2.INTER_LINEAR)
        canvas = np.zeros((200, 200), np.float32)
        y0, x0 = max(0, dy), max(0, dx)
        canvas[y0:y0 + side - (y0 - dy), x0:x0 + side - (x0 - dx)] = \
            r[y0 - dy:, x0 - dx:][:200 - y0, :200 - x0]
        ys, xs = np.nonzero(canvas > 0.01)
        wts = canvas[ys, xs]
        cx, cy = float((xs * wts).sum() / wts.sum()), float((ys * wts).sum() / wts.sum())
        px, py = rg.apply(rg.art_affine((h0, w0), fit), ax, ay)
        self.assertAlmostEqual(px, cx, delta=0.3)
        self.assertAlmostEqual(py, cy, delta=0.3)

    def test_map_frame_crop_and_scale(self):
        """A crop shifts the art origin; px per unit follows the fit's scale."""
        mf = rg.MapFrame(self.MAP, (2048, 2048), (0.0, 0.25, 0, 0), crop=(100, 50, 1800, 1900))
        self.assertAlmostEqual(mf.px_per_unit, 7e-05 * 2048 * 0.25, places=6)
        x, y = mf.to_px(0.0, 0.0)
        side = int(1900 * 0.25 * 1.6)
        ex = 0.25 * (0.813895 * 2048 - 0.5 - 100 - 950) + side / 2
        ey = 0.25 * (0.573242 * 2048 - 0.5 - 50 - 900) + side / 2
        self.assertAlmostEqual(x, ex, places=4)
        self.assertAlmostEqual(y, ey, places=4)

    def test_facing_follows_the_transform(self):
        mf = rg.MapFrame(self.MAP, (2048, 2048), (0.0, 0.25, 0, 0))
        # +x in game is -v on the art (yMultiplier < 0): image up, 270 degrees
        self.assertAlmostEqual(mf.facing_deg(0.0, 0.0, 0.0), 270.0, delta=1e-6)
        # +y in game is +u: image right, 0 degrees
        self.assertAlmostEqual(mf.facing_deg(0.0, 0.0, math.pi / 2), 0.0, delta=1e-6)

    def test_angle_err_wraps(self):
        self.assertAlmostEqual(rg.angle_err(359.0, 2.0), 3.0)
        self.assertAlmostEqual(rg.angle_err(90.0, 270.0), 180.0)


class PairsTest(unittest.TestCase):
    def test_greedy_pairs_nearest_first(self):
        pr = rg.greedy_pairs([(0, 0), (10, 0)], [(9, 0), (1, 0), (50, 50)], 5.0)
        self.assertEqual(sorted((i, j) for i, j, _ in pr), [(0, 1), (1, 0)])


class _Ref:
    """A valorant-api stand-in: one weapon, no agent weapons."""
    weapons = {"vandal-uuid": "Vandal"}


GUN = {"damageType": "Weapon", "damageItem": "VANDAL-UUID"}
AGENTS = {"a1": "Jett", "a2": "Sova", "b1": "Raze", "b2": "Omen"}
WHO = {"a1": {"teamId": "Blue"}, "a2": {"teamId": "Blue"},
       "b1": {"teamId": "Red"}, "b2": {"teamId": "Red"}}


def _kill(g, victim, killer, rnd=0, fd=GUN):
    return {"gameTime": g, "round": rnd, "victim": victim, "killer": killer,
            "finishingDamage": fd}


def _death(t, victim, killer, side=None, **kw):
    return dict({"t_ms": t, "victim": victim, "killer": killer, "side": side,
                 "weapon": "Vandal", "death_id": f"d{t}"}, **kw)


def _score(kills, deaths, legacy=()):
    pairs = rg.match_times([k["gameTime"] for k in kills], [d["t_ms"] for d in deaths],
                           0.0, 1.0, rg.MATCH_TOL_MS)
    out, _rows = rg.score_deaths(kills, deaths, pairs, WHO, AGENTS, "Blue", _Ref(), 0.0,
                                 legacy=legacy)
    return out


class DeathPairingTest(unittest.TestCase):
    """Fix 3: time first, then names, each pass counted apart."""

    def test_time_pass_scores_names_right(self):
        out = _score([_kill(10_000, "b1", "a1")], [_death(10_300, "Raze", "Jett", "enemy")])
        self.assertEqual(out["pairs_time_kept"], 1)
        self.assertEqual(out["victim_right"], 1)
        self.assertEqual(out["killer_right"], 1)
        self.assertEqual(out.get("victim_paired_by_name", 0), 0)

    def test_late_entry_pairs_by_name_never_right(self):
        # first seen 3.2 s late: past the time tolerance, same victim
        kills = [_kill(10_000, "b1", "a1")]
        deaths = [_death(13_200, "Raze", "Jett", "enemy")]
        legacy = _score(kills, deaths, legacy=("pairing",))
        self.assertEqual((legacy["matched"], legacy["missed"], legacy["false_deaths"]), (0, 1, 1))
        out = _score(kills, deaths)
        self.assertEqual((out["matched"], out["missed"], out["false_deaths"]), (1, 0, 0))
        self.assertEqual(out["pairs_name_pass"], 1)
        self.assertEqual(out["victim_paired_by_name"], 1)
        self.assertEqual(out["killer_paired_by_name"], 1)
        self.assertEqual(out.get("side_paired_by_name"), 1)
        for k in ("victim_right", "killer_right", "side_right"):
            self.assertEqual(out.get(k, 0), 0, k)

    def test_name_pass_needs_agreeing_killer(self):
        out = _score([_kill(10_000, "b1", "a1")], [_death(13_200, "Raze", "Sova")])
        self.assertEqual(out["matched"], 0)
        # an unnamed killer does not block it, and scores refused
        out = _score([_kill(10_000, "b1", "a1")], [_death(13_200, "Raze", None)])
        self.assertEqual(out["pairs_name_pass"], 1)
        self.assertEqual(out["killer_refused"], 1)

    def test_name_pass_window(self):
        out = _score([_kill(10_000, "b1", "a1")], [_death(15_500, "Raze", "Jett")])
        self.assertEqual(out["matched"], 0)

    def test_simultaneous_swap_is_reassigned_by_name(self):
        # one sample, slots unread: the order is unknown, names choose
        kills = [_kill(10_000, "b1", "a1"), _kill(10_100, "b2", "a2")]
        deaths = [_death(10_500, "Omen", "Sova"), _death(10_500, "Raze", "Jett")]
        legacy_free = _score(kills, deaths, legacy=("pairing",))
        out = _score(kills, deaths)
        self.assertEqual(out["ambiguous_pairs"], 2)
        self.assertEqual(out["ambiguous_death_order_unknown"], 2)
        self.assertEqual(out["pairs_name_reassigned"], 2)
        self.assertEqual(out["victim_paired_by_name"], 2)
        self.assertEqual(out.get("victim_right", 0), 0)
        self.assertEqual(out.get("victim_wrong", 0), 0)
        # 0.1.0 counted the name-chosen permutation as right
        self.assertEqual(legacy_free["victim_right"], 2)

    def test_name_pairing_keeps_a_wrong_name_wrong(self):
        kills = [_kill(10_000, "b1", "a1"), _kill(10_100, "b2", "a2")]
        # order unknown; the second entry's killer is misread
        deaths = [_death(10_500, "Omen", "Sova"), _death(10_500, "Raze", "Sova")]
        out = _score(kills, deaths)
        self.assertEqual(out["pairs_name_reassigned"], 2)
        self.assertEqual(out["killer_wrong"], 1)
        self.assertEqual(out["killer_paired_by_name"], 1)

    def test_time_only_swap_kept_by_legacy_order(self):
        # 0.2.0: entries 100 ms apart, time ties, names reassign
        kills = [_kill(10_000, "b1", "a1"), _kill(10_100, "b2", "a2")]
        deaths = [_death(10_000, "Omen", "Sova"), _death(10_100, "Raze", "Jett")]
        old = _score(kills, deaths, legacy=("order",))
        self.assertEqual(old["pairs_name_reassigned"], 2)
        # 0.3.0: the stored order is known; the names it gives score wrong
        out = _score(kills, deaths)
        self.assertEqual(out["pairs_name_reassigned"], 0)
        self.assertEqual(out["ambiguous_pairs"], 0)
        self.assertEqual(out["victim_wrong"], 2)

    def test_time_pass_pairs_as_many_as_greedy(self):
        kills = [_kill(g, "b1", "a1") for g in (1000, 5000, 9000)]
        deaths = [_death(t, None, None) for t in (1400, 5100, 9900)]
        _p, stats = rg.pair_deaths(kills, deaths, AGENTS, 0.0)
        self.assertEqual(stats["pairs_time"], stats["pairs_time_greedy"])
        self.assertEqual(stats["pairs_time"], 3)


class OrderPairingTest(unittest.TestCase):
    """0.3.0: the killfeed's order pairs what time alone cannot."""

    def test_same_sample_ordered_by_slot(self):
        # two kills 200 ms apart, first seen in one sample; slot 0 is older
        kills = [_kill(10_000, "b1", "a1"), _kill(10_200, "b2", "a2")]
        deaths = [_death(10_500, "Omen", "Sova", slot=1), _death(10_500, "Raze", "Jett", slot=0)]
        out = _score(kills, deaths)
        self.assertEqual((out["matched"], out["pairs_time_kept"]), (2, 2))
        self.assertEqual(out["ambiguous_pairs"], 0)
        self.assertEqual((out["victim_right"], out["killer_right"]), (2, 2))
        pairs, _st, amb = rg.pair_deaths_in_order(kills, deaths, AGENTS, 0.0)
        self.assertEqual(sorted((i, j) for i, j, *_ in pairs), [(0, 1), (1, 0)])
        self.assertEqual(amb, {})

    def test_crossing_forbidden(self):
        # nearest time would pair 0->1 and 1->0, which crosses the order
        x = [1000.0, 1400.0]
        y = [1500.0, 1600.0]
        self.assertEqual(rg.align_in_order(x, y, 1500.0), [(0, 0), (1, 1)])
        # a crossing that would add a pair never beats the order: the
        # entry placed first in the feed cannot pair the later kill and the
        # entry placed second the earlier one
        self.assertEqual(rg.align_in_order([1000.0, 5000.0], [5100.0, 1150.0], 500.0),
                         [(1, 0)])

    def test_gap_on_either_side(self):
        # a missed kill: the middle kill has no entry
        self.assertEqual(rg.align_in_order([1000.0, 5000.0, 9000.0], [1300.0, 9200.0], 1500.0),
                         [(0, 0), (2, 1)])
        # a false death: the middle entry has no kill
        self.assertEqual(rg.align_in_order([1000.0, 9000.0], [1300.0, 5000.0, 9200.0], 1500.0),
                         [(0, 0), (1, 2)])
        out = _score([_kill(1000, "b1", "a1"), _kill(9000, "b2", "a2")],
                     [_death(1300, "Raze", "Jett", slot=0), _death(5000, None, None, slot=0),
                      _death(9200, "Omen", "Sova", slot=0)])
        self.assertEqual((out["matched"], out["missed"], out["false_deaths"]), (2, 0, 1))

    def test_most_pairs_before_least_dt(self):
        # skipping the near death pairs both kills; order keeps them apart
        self.assertEqual(rg.align_in_order([1000.0, 2000.0], [1900.0, 3000.0], 1500.0),
                         [(0, 0), (1, 1)])

    def test_same_sample_rival_is_ambiguous(self):
        # one kill, two entries of one sample: time and order tie, names choose
        kills = [_kill(10_000, "b1", "a1")]
        deaths = [_death(10_500, "Omen", "Sova", slot=0), _death(10_500, "Raze", "Jett", slot=1)]
        out = _score(kills, deaths)
        self.assertEqual((out["matched"], out["false_deaths"]), (1, 1))
        self.assertEqual(out["ambiguous_same_sample_unpaired"], 1)
        self.assertEqual(out["victim_paired_by_name"], 1)
        self.assertEqual(out.get("victim_wrong", 0), 0)

    def test_late_first_read_contradicts_the_order(self):
        # the second entry is first read at 11 000 in slot 0, above the entry
        # seen at 10 500 and still on screen: the stack calls it the older
        kills = [_kill(10_000, "b2", "a2"), _kill(10_200, "b1", "a1")]
        deaths = [_death(10_500, "Raze", "Jett", slot=1, t_last_ms=14_000),
                  _death(11_000, "Omen", "Sova", slot=0, t_last_ms=14_500)]
        self.assertEqual(rg.order_contradictions(deaths), {frozenset((0, 1))})
        out = _score(kills, deaths)
        self.assertEqual(out["ambiguous_death_order_contradicted"], 2)
        self.assertEqual(out["victim_paired_by_name"], 2)
        self.assertEqual(out.get("victim_wrong", 0), 0)

    def test_kill_tie_is_ambiguous(self):
        kills = [_kill(10_000, "b1", "a1"), _kill(10_000, "b2", "a2")]
        deaths = [_death(10_500, "Omen", "Sova", slot=0), _death(10_500, "Raze", "Jett", slot=1)]
        out = _score(kills, deaths)
        self.assertEqual(out["ambiguous_kill_order_tie"], 2)
        self.assertEqual(out["victim_paired_by_name"] + out.get("victim_right", 0), 2)


class SecondLifeTest(unittest.TestCase):
    """Fix 2: a Run It Back death is counted apart."""

    def test_split(self):
        rows = [_death(1, "Phoenix", "Raze", is_second_life=True), _death(2, "Raze", "Jett"),
                _death(3, "Sage", None, is_revive=True)]
        kill_like, apart = rg.split_deaths(rows)
        self.assertEqual([r["t_ms"] for r in kill_like], [2])
        self.assertEqual([r["t_ms"] for r in apart], [1])
        kill_like, apart = rg.split_deaths(rows, legacy=("second-life",))
        self.assertEqual([r["t_ms"] for r in kill_like], [1, 2])
        self.assertEqual(apart, [])


class SelfKillTest(unittest.TestCase):
    """Fix 4: Riot's killer is the victim: no killer to read."""
    SPIKE = {"damageType": "Bomb", "damageItem": ""}

    def test_unnamed_killer_not_applicable(self):
        kills = [_kill(10_000, "b1", "b1", fd=self.SPIKE)]
        deaths = [_death(10_200, "Raze", None)]
        out = _score(kills, deaths)
        self.assertEqual(out["killer_not_applicable"], 1)
        self.assertEqual(out.get("killer_refused", 0), 0)
        old = _score(kills, deaths, legacy=("self-kill",))
        self.assertEqual(old["killer_refused"], 1)

    def test_named_killer_still_scored(self):
        out = _score([_kill(10_000, "b1", "b1", fd=self.SPIKE)], [_death(10_200, "Raze", "Omen")])
        self.assertEqual(out["killer_wrong"], 1)


class UnmappableItemTest(unittest.TestCase):
    """Fix 5: an item the cached table lacks is listed by its full id."""

    def test_full_id(self):
        fd = {"damageType": "Weapon", "damageItem": "856D9A7E-4B06-DC37-15DC-9D809C37CB90"}
        name, kind = rg.weapon_name(fd, "Chamber", _Ref())
        self.assertEqual(kind, "unmapped")
        self.assertEqual(name, "unmapped:Chamber:856D9A7E-4B06-DC37-15DC-9D809C37CB90")
        out = _score([_kill(10_000, "b1", "a1", fd=fd)], [_death(10_100, "Raze", "Jett")])
        self.assertEqual(out["unmappable_items"], {name.replace("Chamber", "Jett"): 1})
        self.assertEqual(out["weapon_unmapped_riot"], 1)


class MinimapTruthTest(unittest.TestCase):
    """Fix 1: the victims dying at the frame's instant are drawn."""

    @staticmethod
    def _k(g, victim, rnd=0, alive=("a1", "a2", "b1", "b2")):
        return {"gameTime": g, "round": rnd, "victim": victim,
                "victimLocation": {"x": g, "y": 1.0},
                "playerLocations": [{"subject": s, "location": {"x": 0.0, "y": 0.0},
                                     "viewRadians": 0.0} for s in alive if s != victim]}

    def test_victim_and_simultaneous_victims_join(self):
        early = self._k(4000, "a2", alive=("a1", "a2", "b1", "b2"))
        k = self._k(5000, "b1", alive=("a1", "b1", "b2"))
        twin = self._k(5000, "b2", alive=("a1", "b1", "b2"))
        later = self._k(5000, "a1", rnd=1)          # another round, same game time
        dying = {}
        for x in (early, k, twin, later):
            dying.setdefault((x["round"], x["gameTime"]), []).append(x)
        locs = rg.truth_locations(k, dying)
        self.assertEqual(set(locs), {"a1", "b1", "b2"})
        self.assertTrue(locs["b1"]["victim_added"])
        self.assertEqual(locs["b1"]["location"], {"x": 5000, "y": 1.0})
        self.assertIsNone(locs["b1"]["viewRadians"])
        # the earlier kill's victim stays dead
        self.assertNotIn("a2", locs)
        # 0.1.0 left the victim out
        self.assertNotIn("b1", rg.truth_locations(k, dying, legacy_victim=True))


if __name__ == "__main__":
    unittest.main()
