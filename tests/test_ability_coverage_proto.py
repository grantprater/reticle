"""Synthetic checks of prototypes/ability_coverage.py: counting, union, ranking.

No store is read; every input is built here.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import ability_coverage as ac  # noqa: E402

CAT = ac.Catalogue({"agents": {
    "Sova": {"abilities": [
        {"name": "Owl Drone", "slot": "Grenade", "key": "C", "functions": "Controlled Deployable"},
        {"name": "Shock Bolt", "slot": "Ability1", "key": "Q", "functions": "Deterrent"},
        {"name": "Recon Bolt", "slot": "Ability2", "key": "E", "functions": "Intel"},
        {"name": "Hunter's Fury", "slot": "Ultimate", "key": "X", "functions": "Weapon Equip"},
        {"name": "Uncanny Marksman", "slot": "Passive", "key": None}]},
    "KAY/O": {"abilities": [
        {"name": "FRAG/ment", "slot": "Grenade", "key": "C", "functions": "Deterrent"},
        {"name": "FLASH/drive", "slot": "Ability1", "key": "Q", "functions": "Flash"},
        {"name": "ZERO/point", "slot": "Ability2", "key": "E", "functions": "Intel Limiter"},
        {"name": "NULL/cmd", "slot": "Ultimate", "key": "X", "functions": None}]},
}})


def _casts(g=0, a1=0, a2=0, u=0):
    return {"Grenade": g, "Ability1": a1, "Ability2": a2, "Ultimate": u}


PLAYERS = [
    {"subject": "me", "agent": "Sova", "side": "self", "casts": _casts(2, 1, 3, 1)},
    {"subject": "mate", "agent": "KAY/O", "side": "ally", "casts": _casts(1, 4, 0, 1)},
    {"subject": "foe", "agent": "Sova", "side": "enemy", "casts": _casts(0, 0, 2, 0)},
]


def w(channel, side, agent, slot, t):
    return ac._w(channel, side, agent, slot, t, (channel, t))


def round_of(t):
    return 1 if t < 100_000 else 2


class CatalogueTest(unittest.TestCase):
    def test_slots_by_key_and_name(self):
        self.assertEqual(CAT.by_key[(ac.canon("Sova"), "E")], "Ability2")
        self.assertEqual(CAT.slot_of_name("KAY_O", "flash/drive"), "Ability1")
        self.assertIsNone(CAT.slot_of_name("Sova", "Uncanny Marksman"))

    def test_tags_and_unknown(self):
        self.assertEqual(CAT.tags("Sova", "Ability2"), ["reveal"])
        self.assertEqual(CAT.tags("KAY/O", "Ability1"), ["impair"])
        self.assertFalse(CAT.has_functions("KAY/O", "Ultimate"))


class ResolveTest(unittest.TestCase):
    def test_sides(self):
        self.assertEqual(ac.resolve_subject(w("tray", "self", "Sova", "Ability2", 1), PLAYERS), "me")
        # an ally witness of the player's own agent is the player
        self.assertEqual(ac.resolve_subject(w("ult_cast", "ally", "Sova", "Ultimate", 1), PLAYERS), "me")
        self.assertEqual(ac.resolve_subject(w("ult_cast", "enemy", "Sova", "Ultimate", 1), PLAYERS), "foe")
        self.assertEqual(ac.resolve_subject(w("ult_cast", "ally", "KAY_O", "Ultimate", 1), PLAYERS), "mate")
        self.assertIsNone(ac.resolve_subject(w("ult_cast", "enemy", "KAY/O", "Ultimate", 1), PLAYERS))
        self.assertIsNone(ac.resolve_subject(w("killfeed", None, "Sova", "Ultimate", 1), PLAYERS))


class TallyTest(unittest.TestCase):
    def setUp(self):
        ws = [
            # self Recon Bolt: tray sees 2 in round 1 and 1 in round 2, audio 2 in round 1
            w("tray", "self", "Sova", "Ability2", 10_000), w("tray", "self", "Sova", "Ability2", 20_000),
            w("tray", "self", "Sova", "Ability2", 120_000),
            w("audio", "self", "Sova", "Ability2", 10_100), w("audio", "self", "Sova", "Ability2", 20_100),
            # minimap sees one in round 2 the tray also saw: union stays 3
            w("minimap_shape", "self", "Sova", "Ability2", 120_200),
            # ally KAY/O flash: assist icon round 1, killfeed nothing; ult twice (Riot 1): excess
            w("assist_icon", "ally", "KAY/O", "Ability1", 30_000),
            w("ult_cast", "ally", "KAY/O", "Ultimate", 40_000),
            w("ult_cast", "ally", "KAY/O", "Ultimate", 140_000),
            # no player of this side and agent
            w("ult_cast", "enemy", "KAY/O", "Ultimate", 50_000),
            # an ability the catalogue does not list
            w("killfeed", "enemy", "Sova", None, 60_000),
        ]
        kill = w("killfeed", "ally", "KAY/O", "Grenade", 70_000)
        kill["kill"] = True
        revive = w("killfeed", "ally", "KAY/O", "Ultimate", 41_000)
        revive["kill"] = False
        ws += [kill, revive]
        self.t = ac.tally(ws, PLAYERS, round_of)
        self.sessions = [{"players": PLAYERS, "tally": self.t,
                          "kills": {("me", "Ultimate"): 2}}]

    def test_union_is_per_round_max(self):
        cell = self.t["cells"][("me", "Ability2")]
        self.assertEqual(cell["channels"], {"tray": 3, "audio": 2, "minimap_shape": 1})
        self.assertEqual(cell["any"], 3)
        self.assertEqual(self.t["cells"][("mate", "Ultimate")]["any"], 2)

    def test_unresolved_reasons(self):
        self.assertEqual(self.t["unresolved"][("ult_cast", "no_player_of_side_and_agent")], 1)
        self.assertEqual(self.t["unresolved"][("killfeed", "ability_not_in_catalogue")], 1)

    def test_aggregate_missed_excess_and_rank(self):
        rows = ac.aggregate(self.sessions, CAT)
        by = {(a["side"], a["agent"], a["slot"]): a for a in rows}
        rb = by[("self", "Sova", "Ability2")]
        self.assertEqual((rb["riot"], rb["any"], rb["missed"], rb["excess"]), (3, 3, 0, 0))
        self.assertEqual(rb["covered_by_channel"], {"tray": 3, "audio": 2, "minimap_shape": 1})
        ku = by[("ally", "KAY/O", "Ultimate")]
        self.assertEqual((ku["riot"], ku["any"], ku["missed"], ku["excess"]), (1, 1, 0, 1))
        self.assertEqual(ku["tier"], "unknown")   # a revive entry is no kill
        fr = by[("ally", "KAY/O", "Grenade")]
        self.assertEqual((fr["tier"], fr["kill_basis"], fr["any"]), ("kill", "killfeed", 1))
        fl = by[("ally", "KAY/O", "Ability1")]
        self.assertEqual((fl["missed"], fl["tier"]), (3, "block/reveal/impair"))
        hf = by[("self", "Sova", "Ultimate")]
        self.assertEqual((hf["tier"], hf["kill_basis"]), ("kill", "riot"))
        self.assertEqual(by[("enemy", "Sova", "Ability2")]["missed"], 2)
        # kill tier first, then missed within a tier
        self.assertEqual(rows[0]["tier"], "kill")
        tiers = [ac.TIER_ORDER.index(a["tier"]) for a in rows]
        self.assertEqual(tiers, sorted(tiers))
        bri = [a["missed"] for a in rows if a["tier"] == "block/reveal/impair"]
        self.assertEqual(bri, sorted(bri, reverse=True))
        s = ac.side_totals(rows)
        self.assertEqual(s["self"]["riot"], 7)
        self.assertEqual(s["enemy"]["missed"], 2)


class KillfeedWitnessTest(unittest.TestCase):
    def test_sides_and_dedupe(self):
        def death(t, rnd, killer, weapon, side, **kw):
            return {"kind": "death_verdict", "t_ms": t, "round_no": rnd, "killer": killer,
                    "weapon": weapon, "side": side, "weapon_evidence": {"category": "ability"}, **kw}
        rows = [death(1000, 1, "Sova", "Shock Bolt", "enemy"),        # victim enemy: killer ally
                death(2000, 1, "Sova", "Shock Bolt", "enemy"),        # same round, same cast witness
                death(3000, 1, "Sova", "Shock Bolt", "ally"),         # victim ally: killer enemy
                death(4000, 2, "Sova", "Hunter's Fury", "enemy", kf_player_kill=True),
                death(5000, 2, "KAY/O", "NULL/cmd", "ally", same_side=True, is_revive=True),
                {"kind": "death_verdict", "weapon": "Vandal", "weapon_evidence": {"category": "gun"}}]
        ws = ac.witnesses_killfeed(rows, CAT)
        got = [(x["side"], x["agent"], x["slot"], x["kill"]) for x in ws]
        self.assertEqual(got, [("ally", "Sova", "Ability1", True), ("enemy", "Sova", "Ability1", True),
                               ("self", "Sova", "Ultimate", True), ("ally", "KAY/O", "Ultimate", False)])


class EpisodeAndTimingTest(unittest.TestCase):
    def test_fit_episodes(self):
        hits = [(0.0, "Recon Bolt", "ally"), (500.0, "Recon Bolt", "ally"), (1000.0, "Recon Bolt", "ally"),
                (5000.0, "Recon Bolt", "ally"), (500.0, "Lockdown", "enemy")]
        eps = ac.fit_episodes(hits, gap_ms=2500.0)
        self.assertEqual([(e["t_ms"], e["ability"]) for e in eps],
                         [(0.0, "Recon Bolt"), (500.0, "Lockdown"), (5000.0, "Recon Bolt")])

    def test_pair_times_one_to_one(self):
        p = ac.pair_times([100.0, 150.0, 5000.0], [120.0, 4000.0], 2000.0)
        self.assertEqual(sorted((i, j) for i, j, _ in p), [(0, 0), (2, 1)])
        self.assertEqual(dict(((i, j), dt) for i, j, dt in p)[(2, 1)], 1000.0)

    def test_lag_after(self):
        self.assertEqual(ac.lag_after([10_000.0, 500.0], [2_000.0, 9_000.0], 60_000.0), [1000.0])


if __name__ == "__main__":
    unittest.main()
