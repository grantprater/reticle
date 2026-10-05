"""cs_data's pure parts on small fixtures: no network, no store."""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import cs_data as cd  # noqa: E402

SALT = 1234567890123

HEADER = ("," + ",".join(["file", "map", "date", "round", "tick", "seconds", "att_team", "vic_team",
                          "att_side", "vic_side", "hp_dmg", "arm_dmg", "is_bomb_planted",
                          "bomb_site", "hitbox", "wp", "wp_type", "award", "winner_team",
                          "winner_side", "att_id", "att_rank", "vic_id", "vic_rank", "att_pos_x",
                          "att_pos_y", "vic_pos_x", "vic_pos_y", "round_type", "ct_eq_val",
                          "t_eq_val", "avg_match_rank"]))
CT, T = "CounterTerrorist", "Terrorist"
SID_A, SID_B, SID_C = 76561197960000001, 76561197960000002, 76561197960000003


def _row(i, f, rnd, tick, att_side, vic_side, hp, planted, winner, att, vic, rank=10.0):
    return ",".join(str(x) for x in [
        i, f, "de_dust2", "09/28/2017 8:44:22 PM", rnd, tick, tick / 64, "Team 1", "Team 2",
        att_side, vic_side, hp, 0, planted, "", "Head", "AK47", "Rifle", 300, "Team 1", winner,
        att, 16, vic, 15, 1.5, 2.5, 3.5, 4.5, "NORMAL", 20000, 21000, rank])


def _mm_csv() -> str:
    rows = [
        # round 1, CT wins: victim B (T) takes 60 then 50 -> dies at the second hit
        _row(0, "m1.dem", 1, 100, CT, T, 60, False, CT, SID_A, SID_B),
        _row(1, "m1.dem", 1, 110, CT, T, 50, False, CT, SID_A, SID_B),
        # victim A (CT) takes only 30 -> survives
        _row(2, "m1.dem", 1, 120, T, CT, 30, False, CT, SID_C, SID_A),
        # a second T dies to one 100 hit after a plant
        _row(3, "m1.dem", 1, 130, CT, T, 100, True, CT, SID_A, SID_C),
        # round 2, T wins, one CT death; att_id 0 is world damage
        _row(4, "m1.dem", 2, 300, T, CT, 100, False, T, 0, SID_A, rank=17.4),
    ]
    return HEADER + "\n" + "\n".join(rows) + "\n"


class EnvAndPseudonymTests(unittest.TestCase):

    def test_env_value_unquotes_and_skips_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# KAGGLE_API_TOKEN=nope\nOTHER=1\nexport KAGGLE_API_TOKEN=\"abc=def\"\n",
                         encoding="utf-8")
            assert cd.env_value(p, "KAGGLE_API_TOKEN") == "abc=def"
            assert cd.env_value(p, "MISSING") is None
            assert cd.env_value(Path(d) / "absent", "X") is None

    def test_pseudonym_is_keyed_stable_and_drops_no_player(self):
        ids = np.array([SID_A, SID_B, SID_A, 0], np.int64)
        p = cd.pseudonym(ids, SALT)
        assert p[0] == p[2] and p[0] != p[1]
        assert p[3] == -1 and (p[:3] >= 0).all()
        assert not np.isin(ids[:3], p).any()
        assert cd.pseudonym(ids, SALT + 1)[0] != p[0]

    def test_salt_is_created_once(self):
        with tempfile.TemporaryDirectory() as d:
            s1 = cd.load_salt(Path(d) / ".salt")
            assert cd.load_salt(Path(d) / ".salt") == s1


class MatchmakingTests(unittest.TestCase):

    def _convert(self, zipped: bool):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        csv = _mm_csv()
        if zipped:
            src = root / "mm.zip"
            with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("mm_master_demos.csv", csv)
        else:
            src = root / "mm.csv"
            src.write_text(csv, encoding="utf-8", newline="\n")
        out = cd.mm_convert(src, root / "out", SALT)
        return out, pq.read_table(root / "out" / "damage.parquet")

    def test_convert_counts_rows_and_hides_ids(self):
        for zipped in (False, True):
            out, dmg = self._convert(zipped)
            assert out == {"parquet_rows": 5, "csv_rows": 5}
            assert "att_id" not in dmg.column_names and "att_pid" in dmg.column_names
            flat = set(dmg["att_pid"].to_pylist()) | set(dmg["vic_pid"].to_pylist())
            assert not flat & {SID_A, SID_B, SID_C}
            assert dmg["match"].to_pylist()[0] == "m1.dem"

    def test_deaths_rebuild_from_cumulative_damage(self):
        _, dmg = self._convert(False)
        rounds, kills = cd.mm_tables(dmg)
        assert rounds.num_rows == 2
        assert rounds["winner_conflict"].to_pylist() == [False, False]
        assert kills["tick"].to_pylist() == [110, 130, 300]
        st = cd.mm_states(rounds, kills)
        k = st.filter(np.array(st["event"].to_pylist()) == "kill")
        rows = list(zip(k["round"].to_pylist(), k["atk_alive"].to_pylist(),
                        k["def_alive"].to_pylist(), k["planted"].to_pylist()))
        assert rows == [(1, 4, 5, False), (1, 3, 5, True), (2, 5, 4, False)]
        assert k["skill"].to_pylist() == [10, 10, 17]
        assert k["t_s"].null_count == 3
        assert k["atk_win"].to_pylist() == [False, False, True]
        s = st.filter(np.array(st["event"].to_pylist()) == "start")
        assert s["atk_alive"].to_pylist() == [5, 5] and s["atk_load"].to_pylist() == [21000, 21000]


def _frame(tick, sec, ct, t, planted=False):
    return {"tick": tick, "seconds": sec, "clockTime": "01:40", "bombPlanted": planted,
            "bombsite": "A" if planted else "", "ct": {"alivePlayers": ct, "teamEqVal": 4000},
            "t": {"alivePlayers": t, "teamEqVal": 3900}}


def _kill(tick, sec, vic_side, att=SID_A, vic=SID_B, trade=False):
    return {"tick": tick, "seconds": sec, "attackerSteamID": att, "victimSteamID": vic,
            "assisterSteamID": None, "playerTradedSteamID": None,
            "attackerSide": "CT" if vic_side == "T" else "T", "victimSide": vic_side,
            "attackerName": "x", "victimName": "y", "attackerX": 1.0, "attackerY": 2.0,
            "victimX": 3.0, "victimY": 4.0, "weapon": "AK-47", "weaponClass": "Rifle",
            "isTrade": trade, "isFirstKill": False, "isHeadshot": True, "isTeamkill": False,
            "isSuicide": False, "distance": 100.0}


def _esta_demo():
    r1 = {"roundNum": 1, "isWarmup": False, "startTick": 0, "freezeTimeEndTick": 1000,
          "endTick": 1256, "bombPlantTick": 1128, "winningSide": "T",
          "roundEndReason": "TargetBombed", "ctFreezeTimeEndEqVal": 4400, "tFreezeTimeEndEqVal": 4250,
          "ctBuyType": "Full Eco", "tBuyType": "Full Eco", "ctScore": 0, "tScore": 0,
          "endCTScore": 0, "endTScore": 1,
          # awpy's seconds restart at the plant: the second kill reads 0.5, not 1.5
          "kills": [_kill(1064, 0.5, "CT"), _kill(1192, 0.5, "T", vic=SID_C, trade=True)],
          "frames": [_frame(1000, 0.0, 5, 5), _frame(1064, 0.5, 4, 5), _frame(1128, 1.0, 4, 5, True),
                     _frame(1192, 1.5, 4, 4, True), _frame(1256, 2.0, 4, 4, True),
                     _frame(1320, 2.5, 4, 4, True)]}
    r2 = dict(r1, roundNum=2, startTick=2000, freezeTimeEndTick=2000, endTick=2128,
              bombPlantTick=None, winningSide="CT", roundEndReason="CTWin", ctScore=0, tScore=1,
              endCTScore=1, endTScore=1, kills=[_kill(2064, 0.5, "T")],
              frames=[_frame(2000, 0.0, 5, 4), _frame(2064, 0.5, 5, 3), _frame(2128, 1.0, 5, 3)])
    warm = dict(r2, roundNum=0, isWarmup=True)
    return {"demoId": "demo-1", "mapName": "de_nuke", "tickRate": 128, "gameRounds": [warm, r1, r2]}


class EstaTests(unittest.TestCase):

    def test_parse_checks_rounds_and_drops_late_frames(self):
        p = cd.esta_parse(_esta_demo(), SALT)
        c = p["check"]
        assert c["rounds"] == 2 and c["scored"] == 2 and c["rounds_ok"]
        assert c["median_gap_s"] == 0.5
        assert p["frames"].num_rows == 5 + 3  # the frame after endTick is dropped
        assert p["rounds"]["plant_s"].to_pylist() == [1.0, None]
        assert p["kills"]["is_trade"].to_pylist() == [False, True, False]
        assert p["kills"]["t_s"].to_pylist() == [0.5, 1.5, 0.5]
        assert SID_A not in p["kills"]["att_pid"].to_pylist()
        assert "attackerName" not in p["kills"].column_names

    def test_states_follow_kills_plant_and_start_counts(self):
        p = cd.esta_parse(_esta_demo(), SALT)
        st = cd.esta_states(p["rounds"], p["kills"], p["frames"])
        ev = np.array(st["event"].to_pylist())
        k = st.filter(ev == "kill")
        rows = list(zip(k["round"].to_pylist(), k["atk_alive"].to_pylist(), k["def_alive"].to_pylist(),
                        k["planted"].to_pylist(), k["since_plant_s"].to_pylist()))
        assert rows == [(1, 5, 4, False, None), (1, 4, 4, True, 0.5), (2, 3, 5, False, None)]
        s = st.filter(ev == "start")
        assert s["atk_alive"].to_pylist() == [5, 4]  # round 2's first frame shows four T
        assert set(st["skill"].to_pylist()) == {cd.PRO_SKILL}
        t = st.filter(ev == "tick")
        assert t.num_rows == 8 and t["atk_win"].to_pylist()[:5] == [True] * 5
        assert t["since_plant_s"].to_pylist()[:5] == [None, None, 0.0, 0.5, 1.0]

    def test_frames_agree_with_the_kill_log(self):
        p = cd.esta_parse(_esta_demo(), SALT)
        assert cd.frame_kill_agreement(p["rounds"], p["kills"], p["frames"])["frame_kill_alive_agree"] == 1.0
        f = p["frames"]
        bad = f.set_column(f.schema.get_field_index("t_alive"), "t_alive",
                           pa.array(np.array([5, 5, 5, 4, 4, 1, 3, 3], np.int8)))
        assert cd.frame_kill_agreement(p["rounds"], p["kills"], bad)["frame_kill_alive_agree"] == 0.875


class TableTests(unittest.TestCase):

    def test_wp_table_and_first_kill(self):
        n = 4
        st = cd.state_table("x", ["a", "a", "b", "b"], [1, 1, 1, 1], "kill", None,
                            [4, 4, 5, 4], [5, 4, 4, 4], [False, False, False, True], None,
                            np.zeros(n), np.zeros(n), 19, [False, False, True, True])
        t = cd.wp_table(st)
        cells = {(a, d, p): (n_, w) for a, d, p, n_, w in zip(*(t[c].to_pylist() for c in
                 ("atk_alive", "def_alive", "planted", "n", "atk_win")))}
        assert cells[(4, 4, False)] == (1, 0.0) and cells[(4, 4, True)] == (1, 1.0)
        v = cd.wp_values(st)
        assert v["def_win_4v4_plant"] == 0.0 and v["n_4v4_noplant"] == 1
        assert v["def_win_3v3_noplant"] is None
        fk = cd.first_kill(st)
        assert fk == {"first_kill_rounds": 2, "first_kill_full_side_win": 1.0}

    def test_rank_spread_counts_rounds_and_matches(self):

        r = pa.table({"match": ["a", "a", "b"], "avg_match_rank": [3.4, 3.4, 17.6]})
        v = cd.rank_spread(r)
        assert v["rounds_rank_3"] == 2 and v["rounds_rank_18"] == 1
        assert v["matches_rank_3"] == 1 and v["matches"] == 2
        assert v["share_rank_17_up"] == round(1 / 3, 4)

    def test_budget_check_raises_over_budget(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "f").write_bytes(b"x" * 10)
            assert cd.check_budget(0, Path(d)) == 10
            with self.assertRaises(RuntimeError):
                cd.check_budget(cd.BUDGET_BYTES, Path(d))


if __name__ == "__main__":
    unittest.main()
