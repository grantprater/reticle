"""The player profile on synthetic matches; no store, no player data.

Every match, PUUID and number below is made up. Two v4 matches pass through
`ladder_fetch.parse_matches` (the parsed-schema owner) and the profile's
feature tables, and the tests check counts worked out by hand.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import player_profile as pp  # noqa: E402

SALT = bytes(16)
RED = [0, 1, 2, 3, 4]
BLUE = [5, 6, 7, 8, 9]
TEAM = {p: ("Red" if p in RED else "Blue") for p in RED + BLUE}


def puuid(i):
    return f"00000000-0000-0000-0000-{i:012d}"


def mid(i):
    return f"22222222-0000-0000-0000-{i:012d}"


def who(p):
    return {"puuid": puuid(p), "name": None, "tag": None, "team": TEAM[p]}


def loc(p, x, y):
    return {"player": who(p), "view_radians": 0.0,
            "location": {"x": x, "y": y}}


def kill(r, t, killer, victim, listed=(), assist=()):
    return {"round": r, "time_in_round_in_ms": t,
            "time_in_match_in_ms": 100000 * r + t,
            "killer": who(killer), "victim": who(victim),
            "assistants": [who(a) for a in assist],
            "weapon": {"id": "w", "name": "Vandal", "type": "Weapon"},
            "secondary_fire_mode": False, "location": {"x": 0, "y": 0},
            "player_locations": list(listed)}


def rnd(r, winner, loadout, damage=None, plant=None):
    damage = damage or {}
    return {
        "id": r, "result": "Elimination", "ceremony": "CeremonyDefault",
        "winning_team": winner, "plant": plant, "defuse": None,
        "stats": [{"player": who(p),
                   "economy": {"loadout_value": loadout.get(p, 1000),
                               "remaining": 0,
                               "weapon": {"id": "w", "name": "Vandal"},
                               "armor": None},
                   "stats": {"score": 0, "kills": 0},
                   "damage_events": damage.get(p, []),
                   "was_afk": False, "received_penalty": False,
                   "stayed_in_spawn": False} for p in RED + BLUE]}


def match_one():
    """Round 0: p0 dies first and is traded; p4 wins a 1v4.
    Round 1: p0 opens, kills twice, dies untraded; p0 buys alone."""
    k0 = [kill(0, 1000, 5, 0, listed=[loc(1, 300, 400), loc(2, 3000, 4000),
                                      loc(5, 10, 10)]),
          kill(0, 3000, 1, 5),
          kill(0, 4000, 6, 1),
          kill(0, 20000, 7, 2),
          kill(0, 21000, 7, 3),
          kill(0, 30000, 4, 6), kill(0, 31000, 4, 7),
          kill(0, 32000, 4, 8), kill(0, 33000, 4, 9)]
    k1 = [kill(1, 1000, 0, 5, assist=[1]),
          kill(1, 2000, 0, 6),
          kill(1, 9000, 7, 0, listed=[loc(1, 6000, 8000)]),
          kill(1, 15000, 1, 7),
          kill(1, 16000, 1, 8), kill(1, 17000, 2, 9)]
    dmg = {0: [{"player": who(5), "damage": 150, "headshots": 1,
                "bodyshots": 1, "legshots": 0},
               {"player": who(1), "damage": 50, "headshots": 1,
                "bodyshots": 0, "legshots": 0}]}   # friendly: not counted
    rounds = [rnd(0, "Red", {}),
              rnd(1, "Red", {0: 4500}, damage=dmg)]
    return v4(1, rounds, k0 + k1, casts={0: (2, 1, 3, 0)})


def match_two():
    """One round, Blue wins; nobody on Red is in a clutch alone."""
    ks = [kill(0, 1000, 0, 5), kill(0, 2000, 6, 0), kill(0, 2500, 6, 1),
          kill(0, 3000, 6, 2), kill(0, 3100, 6, 3), kill(0, 3200, 6, 4)]
    return v4(2, [rnd(0, "Blue", {})], ks)


def v4(m, rounds, kills, casts=None):
    casts = casts or {}
    return {
        "metadata": {"match_id": mid(m), "map": {"id": "m", "name": "Ascent"},
                     "game_version": "v", "game_length_in_ms": 1,
                     "started_at": f"2026-09-2{m}T12:00:00Z",
                     "is_completed": True, "queue": {"id": "competitive"},
                     "season": {"short": "e11a5"}, "region": "na",
                     "cluster": "x"},
        "players": [{"puuid": puuid(p), "team_id": TEAM[p],
                     "party_id": f"party{p}", "agent": {"name": "Sova"},
                     "tier": {"id": 13, "name": "Gold 2"},
                     "account_level": 1,
                     "stats": {"score": 0, "kills": 0, "deaths": 0,
                               "assists": 0},
                     "ability_casts": dict(zip(
                         ("grenade", "ability1", "ability2", "ultimate"),
                         casts.get(p, (1, 1, 1, 0)))),
                     "behavior": {"afk_rounds": 0, "rounds_in_spawn": 0}}
                    for p in RED + BLUE],
        "teams": [{"team_id": "Red", "won": True,
                   "rounds": {"won": 1, "lost": 0}},
                  {"team_id": "Blue", "won": False,
                   "rounds": {"won": 0, "lost": 1}}],
        "rounds": rounds, "kills": kills}


def built(ms=None):
    ms = ms or [match_one(), match_two()]
    T = pp.build_tables(ms, [], [], SALT, {puuid(0)})
    c = pp.connect(T)
    pp.features(c)
    pid, _ = pp.lf._pseudo(SALT, {puuid(0)})
    labels = {pid(pa.array([puuid(0)])).to_pylist()[0]: "A"}
    pp.player_match(c, labels)
    return c, pid


def owner_rows(c, pid, match):
    p0 = pid(pa.array([puuid(0)])).to_pylist()[0]
    cols = [d[0] for d in c.execute("select * from pr limit 0").description]
    rows = c.execute("select * from pr where player = ? and match_id = ? "
                     "order by round", [p0, mid(match)]).fetchall()
    return [dict(zip(cols, r)) for r in rows]


class Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, pid = built()
        cls.pid = staticmethod(pid)
        cls.r = owner_rows(cls.c, cls.pid, 1)
        cls.ps = {p: cls.pid(pa.array([puuid(p)])).to_pylist()[0]
                  for p in RED + BLUE}

    def test_opening(self):
        self.assertEqual([x["fd"] for x in self.r], [1, 0])
        self.assertEqual([x["fk"] for x in self.r], [0, 1])

    def test_trade_window(self):
        # round 0: p5 killed p0 and died to p1 2 s later: traded
        # round 1: p7 killed p0 and died 6 s later: not traded at 5 s
        self.assertEqual([x["traded"] for x in self.r], [1, 0])
        self.assertEqual([x["traded_lo"] for x in self.r], [1, 0])
        self.assertEqual([x["traded_hi"] for x in self.r], [1, 1])
        p1 = self.ps[1]
        n = self.c.execute("select sum(trades) from pr where player = ?",
                           [p1]).fetchone()[0]
        self.assertEqual(n, 1)

    def test_distance_at_death(self):
        # nearest listed teammate: p1 at (300, 400) cm from (0, 0) = 500 cm
        self.assertAlmostEqual(self.r[0]["dist_sum"], 500.0)
        self.assertEqual(self.r[0]["isolated"], 0)
        # round 1: the only listed teammate is 100 m away
        self.assertAlmostEqual(self.r[1]["dist_u_sum"], 10000.0)
        self.assertEqual(self.r[1]["isolated"], 1)

    def test_kast_and_multikill(self):
        self.assertEqual([x["kast"] for x in self.r], [1, 1])
        self.assertEqual([x["mk2"] for x in self.r], [0, 1])
        p4 = self.ps[4]
        mk3 = self.c.execute("select mk3 from pr where player = ? and "
                             "match_id = ? and round = 0",
                             [p4, mid(1)]).fetchone()[0]
        self.assertEqual(mk3, 1)

    def test_clutch(self):
        p4 = self.ps[4]
        got = self.c.execute("select clutch, clutch_x, clutch_won from pr "
                             "where player = ? and match_id = ? and round = 0",
                             [p4, mid(1)]).fetchone()
        self.assertEqual(got, (1, 4, 1))
        # match two: p4 is last alive on Red at 3100 against four Blues
        got = self.c.execute("select clutch, clutch_x, clutch_won from pr "
                             "where player = ? and match_id = ?",
                             [p4, mid(2)]).fetchone()
        self.assertEqual(got, (1, 4, 0))
        self.assertEqual([x["clutch"] for x in self.r], [0, 0])

    def test_damage_enemy_only(self):
        self.assertEqual(self.r[1]["dmg"], 150)
        self.assertEqual((self.r[1]["hs"], self.r[1]["bs"]), (1, 1))

    def test_economy(self):
        self.assertEqual(self.r[0]["buy"], "pistol")
        self.assertEqual(self.r[1]["buy"], "eco")      # mean 1700
        self.assertAlmostEqual(self.r[1]["mates_mean_lv"], 1000.0)

    def test_side(self):
        self.assertEqual({x["side"] for x in self.r}, {"attack"})
        got = self.c.execute(
            f"select {pp.side_sql('r')} from (select unnest([0, 11, 12, 23, "
            "24, 25, 26]) r)").fetchall()
        self.assertEqual([g[0] for g in got],
                         ["Red", "Red", "Blue", "Blue", "Red", "Blue", "Red"])


class Metrics(unittest.TestCase):
    def test_pooled_owner_values(self):
        c, _ = built()
        S = pp.sums(c)
        P = pp.profile(S, boot=50)["pooled"]
        self.assertAlmostEqual(P["kd"]["owner"], 3 / 3)
        # first kills: match two's round and match one's round 1
        self.assertAlmostEqual(P["opening_win"]["owner"], 2 / 3)
        self.assertAlmostEqual(P["opening_involvement"]["owner"], 3 / 3)
        self.assertAlmostEqual(P["traded_share"]["owner"], 1 / 3)
        self.assertAlmostEqual(P["adr"]["owner"], 150 / 3)
        # 6 casts over 2 rounds, then 3 over 1
        self.assertAlmostEqual(P["casts_per_round"]["owner"], 9 / 3)
        self.assertAlmostEqual(P["offsync_buy"]["owner"], 1 / 1)
        self.assertTrue(P["kd"]["low_n"])

    def test_side_group_has_no_cast_metric(self):
        c, _ = built()
        G = pp.profile(pp.sums(c), boot=20)["grouped"]
        self.assertIn("casts_per_round", pp.MATCH_TOTALS)
        for v in G["side"].values():
            self.assertFalse(set(v) & set(pp.MATCH_TOTALS))
            self.assertIn("kd", v)
        for v in G["agent"].values():
            self.assertIn("casts_per_round", v)

    def test_out_paths_keep_earlier_runs(self):
        pj, rm = pp.out_paths(Path("x"))
        self.assertNotEqual(pj.name, "profile.json")
        self.assertNotEqual(rm.name, "report.md")

    def test_casts_counted_once_per_match(self):
        c, _ = built([match_one()])
        S = pp.sums(c)
        own = S["is_owner"].astype(bool)
        self.assertEqual(S["n_casts_per_round"][own].sum(), 6)

    def test_compare_identical_groups(self):
        n = 40
        S = {"match_id": np.repeat(np.arange(n).astype(str), 2),
             "is_owner": np.tile([1, 0], n),
             "n_x": np.tile([3.0, 3.0], n), "d_x": np.tile([10.0, 10.0], n)}
        r = pp.compare(S, "x", np.ones(2 * n, bool), boot=200)
        self.assertAlmostEqual(r["owner"], 0.3)
        self.assertAlmostEqual(r["diff"], 0.0)
        self.assertLessEqual(r["ci_diff"][0], 0.0)
        self.assertGreaterEqual(r["ci_diff"][1], 0.0)
        self.assertEqual(r["owner_n"], 10.0 * n)

    def test_compare_detects_a_gap(self):
        n = 60
        rng = np.random.default_rng(0)
        S = {"match_id": np.repeat(np.arange(n).astype(str), 2),
             "is_owner": np.tile([1, 0], n),
             "n_x": np.column_stack([rng.binomial(20, 0.7, n),
                                     rng.binomial(20, 0.4, n)]).ravel()
             .astype(float),
             "d_x": np.full(2 * n, 20.0)}
        r = pp.compare(S, "x", np.ones(2 * n, bool), boot=500)
        self.assertGreater(r["ci_diff"][0], 0.0)

    def test_strongest_one_per_family(self):
        base = {"rankable": True, "low_n": False}

        def m(fam, d, ci, dm=None, cim=None, **kw):
            dm, cim = (d, ci) if dm is None else (dm, cim)
            return base | {"family": fam, "diff": d, "ci_diff": ci,
                           "diff_matched": dm, "ci_diff_matched": cim} | kw
        P = {"a": m("f", 0.5, [0.4, 0.6]),
             "b": m("f", 0.4, [0.3, 0.5]),
             "c": m("g", -0.2, [-0.3, -0.1]),
             "d": m("h", 0.1, [-0.1, 0.3]),
             "e": m("i", 0.9, [0.1, 1.7], low_n=True),
             # holds against every peer, reverses against same-agent peers
             "x": m("j", 0.5, [0.4, 0.6], -0.5, [-0.6, -0.4]),
             # utility ranks on the agent-matched comparison alone
             "u": m("utility", None, None, 0.3, [0.2, 0.4])}
        got = [s["metric"] for s in pp.strongest(P)]
        self.assertEqual(got, ["a", "u", "c"])

    def test_agent_matched_removes_the_mix(self):
        # the player plays X (ratio 0.5); peers on X score 0.5, on Y 0.1
        n = 30
        S = {"match_id": np.repeat(np.arange(n).astype(str), 3),
             "is_owner": np.tile([1, 0, 0], n),
             "agent": np.tile(["X", "X", "Y"], n),
             "n_x": np.tile([5.0, 5.0, 1.0], n),
             "d_x": np.full(3 * n, 10.0)}
        raw = pp.compare(S, "x", np.ones(3 * n, bool), boot=200)
        self.assertAlmostEqual(raw["diff"], 0.5 - 0.3)
        r = pp.compare_agent_matched(S, "x", np.ones(3 * n, bool), boot=200)
        self.assertAlmostEqual(r["peers_matched"], 0.5)
        self.assertAlmostEqual(r["diff_matched"], 0.0)


class Sources(unittest.TestCase):
    def test_kept_replays_without_capture(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "external" / "replays"
            p.mkdir(parents=True)
            (p / "manifest.json").write_text(json.dumps({"files": [
                {"file": f"{mid(1)}.vrf", "capture_session": None},
                {"file": f"{mid(2)}.vrf", "capture_session": "abc"}]}))
            self.assertEqual(pp.kept_replay_matches(Path(d)), {mid(1)})

    def test_riot_extras_reshape(self):
        rec = {"match": {
            "matchInfo": {"matchId": mid(3)},
            "players": [{"subject": puuid(0), "teamId": "Red",
                         "stats": {"abilityCasts": {
                             "grenadeCasts": 2, "ability1Casts": 0,
                             "ability2Casts": 5, "ultimateCasts": 1}}},
                        {"subject": puuid(5), "teamId": "Blue", "stats": {}}],
            "roundResults": [{"roundNum": 0, "playerStats": [
                {"subject": puuid(0), "damage": [
                    {"receiver": puuid(5), "damage": 140, "headshots": 1,
                     "bodyshots": 1, "legshots": 0}]}]}]}}
        pid, _ = pp.lf._pseudo(SALT, set())
        ex = pp.extras_v4([pp.riot_extras_v4(rec)], pid)
        self.assertEqual(ex["casts"].column("ability2").to_pylist()[0], 5.0)
        d = ex["damage"].to_pylist()[0]
        self.assertEqual((d["damage"], d["team"], d["receiver_team"]),
                         (140.0, "Red", "Blue"))


if __name__ == "__main__":
    unittest.main()
