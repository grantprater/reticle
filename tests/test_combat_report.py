"""The combat report reader's pixel rules and the panel/round adjudication."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from reticle import combat_report as cr
from reticle.adjudication import combat_report as adj
from reticle.version import COMBAT_REPORT_VERSION


def _row(out, inc, oh="000", ih="000", killed=0.0, killed_you=0.0, assist=0.0):
    return {"out": {"text": out}, "in": {"text": inc},
            "out_hits": {"text": oh}, "in_hits": {"text": ih},
            "out_word": {"KILLED": killed, "KILLED YOU": 0.1, "ASSIST": assist},
            "in_word": {"KILLED": 0.1, "KILLED YOU": killed_you, "ASSIST": 0.1}}


def _frame(t, rows, header=0.99):
    return {"kind": "frame", "t_ms": float(t), "header": header, "hx": 1633, "hy": 465,
            "rows": rows, "combat_report_version": COMBAT_REPORT_VERSION}


def _run(t0, t1, rows, step=1000):
    return [_frame(t, rows) for t in range(t0, t1 + 1, step)]


ROUNDS = [
    {"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100000.0, "player_kills": 1, "player_deaths": 1},
    {"round_no": 2, "t_start_ms": 100000.0, "t_end_ms": 200000.0, "player_kills": 0, "player_deaths": 1},
    {"round_no": 3, "t_start_ms": 208000.0, "t_end_ms": 300000.0, "player_kills": 2, "player_deaths": 0},
]


class ReaderPixels(unittest.TestCase):
    def test_grey_counts_read_as_zero_without_a_template(self):
        patch = np.full((52, 16), 40, np.uint8)
        for y in (6, 22, 38):
            patch[y:y + 9, 5:11] = 150           # drawn grey: a zero count
        self.assertEqual(cr.read_hits(patch, tpl=None)["text"], "000")

    def test_wrong_blob_count_is_refused_with_a_reason(self):
        patch = np.full((52, 16), 40, np.uint8)
        patch[6:15, 5:11] = 150
        got = cr.read_hits(patch, tpl=None)
        self.assertIsNone(got["text"])
        self.assertEqual(got["reason"], "1-blobs")

    def test_header_is_found_where_it_is_drawn(self):
        header, _words = cr.load_templates()
        gray = np.random.default_rng(0).integers(20, 60, (1080, 1920)).astype(np.uint8)
        gray[400:400 + header.shape[0], 1600:1600 + header.shape[1]] = header
        score, hx, hy = cr.locate(gray, header)
        self.assertGreater(score, 0.99)
        self.assertEqual((hx, hy), (1600, 400))

    def test_other_frame_sizes_are_refused_not_scaled(self):
        reader = cr.CombatReportReader(digits=None)
        reader.feed(SimpleNamespace(frame_idx=0, t_ms=0.0, frame=np.zeros((720, 1280, 3), np.uint8)))
        self.assertIsNone(reader.rows[0]["header"])
        self.assertEqual(reader.rows[0]["reason"], "frame_size_1280x720")


class Panels(unittest.TestCase):
    def test_reopen_merges_but_an_identical_death_panel_is_new(self):
        same = [_row("0", "160", ih="100", killed_you=0.99)]
        frames = _run(50000, 60000, same) + _run(90000, 92000, same) + _run(150000, 160000, same)
        ps = adj.panels(frames, death_times=[50000.0, 150000.0])
        self.assertEqual([p["start_ms"] for p in ps], [50000.0, 150000.0])
        self.assertEqual(ps[0]["reopens"], [90000.0])

    def test_flags_are_a_majority_vote_over_the_panel(self):
        rows_hit = [_row("160", "0", oh="100", killed=0.95)]
        rows_miss = [_row("160", "0", oh="100", killed=0.3)]
        frames = _run(10000, 14000, rows_hit) + [_frame(15000, rows_miss)]
        (p,) = adj.panels(frames, death_times=[10000.0])
        self.assertTrue(p["rows"][0]["killed"])

    def test_hit_count_noise_does_not_change_the_modal_read(self):
        good = [_row("65", "0", oh="010")]
        noisy = [_row("65", "0", oh="018")]
        frames = _run(10000, 18000, good) + [_frame(19000, noisy)]
        (p,) = adj.panels(frames, death_times=[10000.0])
        self.assertEqual(p["rows"][0]["out_hits"], "010")
        self.assertEqual(p["agreement"]["out_hits"], [9, 1, 0])


class Rounds(unittest.TestCase):
    def test_summary_early_in_a_round_belongs_to_the_previous_one(self):
        # Round 2 ends exactly where round 3 would begin had there been no
        # gap; the boundary itself must still step back (a strict < did not).
        rounds = [dict(r) for r in ROUNDS]
        rounds[2]["t_start_ms"] = 200000.0
        frames = _run(210000, 214000, [_row("160", "0", oh="100", killed=0.95)])
        ps = adj.panels(frames, death_times=[])
        adj.assign_rounds(ps, rounds)
        self.assertEqual((ps[0]["kind"], ps[0]["round_no"]), ("summary", 2))

    def test_counts_sit_beside_the_stored_rounds_and_keep_disagreements(self):
        frames = (_run(60000, 70000, [_row("160", "65", oh="100", ih="010", killed=0.95,
                                           killed_you=0.99)])
                  + _run(150000, 160000, [_row("0", "160", ih="100", killed_you=0.99)])
                  + _run(210000, 214000, [_row("160", "0", oh="100", killed=0.95)]))
        ev = adj.events("s", frames, ROUNDS, death_times=[60000.0, 150000.0])
        rounds = {e["round_no"]: e for e in ev if e["kind"] == "round"}
        self.assertEqual((rounds[1]["kills"], rounds[1]["deaths"]), (1, 1))
        self.assertTrue(rounds[1]["kills_agree"] and rounds[1]["deaths_agree"])
        # The summary opened early in round 3 is round 2's: 1 kill against 0 stored.
        self.assertEqual(rounds[2]["kills"], 1)
        self.assertFalse(rounds[2]["kills_agree"])
        self.assertIsNone(rounds[3]["kills"])
        self.assertEqual(rounds[3]["reason"], "no panel shown for this round")
        self.assertEqual(ev[0]["kills_disagree"], 1)

    def test_rows_from_another_version_are_refused(self):
        frames = _run(60000, 62000, [_row("0", "160")])
        frames[0]["combat_report_version"] = "combat-report-0.0.0"
        with self.assertRaises(ValueError):
            adj.events("s", frames, ROUNDS, death_times=[60000.0])



class Verdict(unittest.TestCase):
    def test_report_decides_where_shown_and_killfeed_elsewhere(self):
        frames = _run(60000, 70000, [_row("160", "65", oh="100", ih="010", killed=0.95,
                                          killed_you=0.99)])
        rounds = [dict(r) for r in ROUNDS]
        rounds[0]["player_deaths"] = 2          # killfeed flicker: one death seen twice
        ev = adj.events("s", frames, rounds, death_times=[60000.0])
        by = {e["round_no"]: e for e in ev if e["kind"] == "round"}
        self.assertEqual((by[1]["deaths_verdict"], by[1]["verdict_source"]), (1, "combat_report"))
        self.assertFalse(by[1]["deaths_agree"])
        self.assertEqual((by[3]["kills_verdict"], by[3]["verdict_source"]), (2, "killfeed"))
        self.assertEqual(ev[0]["verdict_from_killfeed"], 2)



class Naming(unittest.TestCase):
    """`name_rows`: killfeed witnesses kept inside the scoreboard bound, per cluster."""

    def _thumb(self, seed):
        import base64
        arr = np.random.default_rng(seed).integers(0, 255, (27, 20, 3)).astype(np.uint8)
        return base64.b64encode(arr.tobytes()).decode("ascii")

    def test_a_killfeed_name_outside_the_bound_abstains_and_the_cluster_carries_the_rest(self):
        jett, skye = self._thumb(1), self._thumb(2)
        ps = [
            {"start_ms": 60000.0, "kind": "death", "round_no": 1,
             "rows": [{"killed_you": True, "killed": False, "portrait": jett}]},
            {"start_ms": 150000.0, "kind": "death", "round_no": 2,
             "rows": [{"killed_you": True, "killed": False, "portrait": jett},
                      {"killed_you": False, "killed": False, "portrait": skye}]},
        ]
        rounds = [dict(r) for r in ROUNDS[:2]]
        deaths = [{"t_first": 59000.0, "t_last": 63000.0, "slot": 0},
                  {"t_first": 149000.0, "t_last": 153000.0, "slot": 0}]
        # The killfeed reads the killer as Jett in round 1 and Iso in round 2;
        # the scoreboard says only Jett's kills rose in round 2.
        board = [{"t": 1000.0, "agent": "Jett", "kills": 0, "deaths": 0},
                 {"t": 1000.0, "agent": "Iso", "kills": 0, "deaths": 0},
                 {"t": 101000.0, "agent": "Jett", "kills": 1, "deaths": 0},
                 {"t": 101000.0, "agent": "Iso", "kills": 0, "deaths": 0},
                 {"t": 152000.0, "agent": "Jett", "kills": 2, "deaths": 0},
                 {"t": 152000.0, "agent": "Iso", "kills": 0, "deaths": 0}]
        enemy = [{"agent": "Jett"}, {"agent": "Iso"}, {"agent": "Skye"},
                 {"agent": "Omen"}, {"agent": "Killjoy"}]
        reads = {59000.0: "Jett", 149000.0: "Iso"}
        original = adj._killfeed_name
        adj._killfeed_name = lambda tr, *_a: reads[tr["t_first"]]
        try:
            claims, verdicts = adj.name_rows("s", ps, rounds, [], deaths, [], board, enemy, {})
        finally:
            adj._killfeed_name = original
        by = {v["entity_id"]: v for v in verdicts}
        jett_entity = ps[0]["rows"][0]["entity_id"]
        self.assertEqual(ps[1]["rows"][0]["entity_id"], jett_entity)
        self.assertEqual((by[jett_entity]["status"], by[jett_entity]["agent"]), ("resolved", "Jett"))
        refused = [c for c in claims if c["channel"] == "killfeed_portrait" and c["agent"] is None]
        self.assertEqual(len(refused), 1)
        self.assertIn("outside scoreboard bound", refused[0]["reason"])
        self.assertNotIn(ps[1]["rows"][1]["entity_id"], by)   # no witness: no verdict

    def test_an_ally_row_takes_no_enemy_witness_and_never_joins_an_enemy_cluster(self):
        jett = self._thumb(1)
        ps = [{"start_ms": 60000.0, "kind": "death", "round_no": 1,
               "rows": [{"killed_you": True, "killed": False, "portrait": jett},
                        {"killed_you": True, "killed": False, "portrait": jett, "ally": True}]}]
        rounds = [dict(r) for r in ROUNDS[:1]]
        deaths = [{"t_first": 59000.0, "t_last": 63000.0, "slot": 0}]
        enemy = [{"agent": a} for a in ("Jett", "Iso", "Skye", "Omen", "Killjoy")]
        ally = [{"agent": a} for a in ("Phoenix", "Jett", "Breach", "Reyna", "Miks")]
        original = adj._killfeed_name
        adj._killfeed_name = lambda *_a: "Jett"
        try:
            claims, _ = adj.name_rows("s", ps, rounds, [], deaths, [], [], enemy, {},
                                      ally_rows=ally, player="Phoenix")
        finally:
            adj._killfeed_name = original
        enemy_row, ally_row = ps[0]["rows"]
        self.assertNotEqual(enemy_row["entity_id"], ally_row["entity_id"])
        mine = [c for c in claims if c["entity_id"] == ally_row["entity_id"]]
        self.assertEqual([(c["channel"], c["agent"]) for c in mine], [("ally_lineup", None)])
        self.assertIn("ally bound of 4", mine[0]["reason"])
        self.assertEqual(adj.ally_bound(ally[:2], "Phoenix"), ["Jett"])


class RoundVerdicts(unittest.TestCase):
    def _stream(self, **over):
        from reticle.version import COMBAT_REPORT_ROUND_VERSION
        rnd = {"kind": "round", "round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100.0,
               "stored_kills": 2, "stored_deaths": 1, "kills_verdict": 1, "deaths_verdict": 1,
               "assists": 0, "verdict_source": "combat_report",
               "kills_agree": False, "deaths_agree": True, **over}
        return [{"kind": "summary", "combat_report_round_version": COMBAT_REPORT_ROUND_VERSION}, rnd]

    def test_current_rounds_read_and_changed_ones_refuse(self):
        rounds = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100.0,
                   "player_kills": 2, "player_deaths": 1}]
        v = adj.round_verdicts(self._stream(), rounds)
        self.assertEqual(v["status"], "ok")
        self.assertEqual((v["rounds"][1]["kills"], v["rounds"][1]["killfeed_kills"],
                          v["rounds"][1]["agree"]), (1, 2, False))
        moved = [{**rounds[0], "player_deaths": 2}]
        self.assertTrue(adj.round_verdicts(self._stream(), moved)["reason"].startswith("rounds_changed"))
        stale = self._stream()
        stale[0]["combat_report_round_version"] = "old"
        self.assertTrue(adj.round_verdicts(stale, rounds)["reason"].startswith("stale_verdict"))
        self.assertEqual(adj.round_verdicts([], rounds)["reason"], "no_report")

    def test_coach_flags_a_disagreeing_round(self):
        from reticle.coaching import attach_round_verdicts
        rounds = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100.0,
                   "player_kills": 2, "player_deaths": 1}]
        ev = [{"round_no": 1, "quality_flags": []}, {"round_no": None, "quality_flags": []}]
        attach_round_verdicts(ev, adj.round_verdicts(self._stream(), rounds))
        self.assertIn("report_disagrees_with_killfeed", ev[0]["quality_flags"])
        self.assertIsNone(ev[1]["round_verdict"])


if __name__ == "__main__":
    unittest.main()
