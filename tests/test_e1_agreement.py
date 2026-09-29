"""The E1 evaluator on synthetic rounds (`prototypes/e1_agreement.py`).

These rounds test the evaluator, never the pipeline: none is evidence, and
none is counted in the `e1_agreement/replay` series.
"""
from __future__ import annotations

import unittest

from prototypes.e1_agreement import (DISAGREE, NO_READ, SPLIT_READ, THREE_WAY, TWO_WAY,
                                     UNWITNESSED, boundaries, classify, life_episodes,
                                     scoreboard_rounds, scoreboard_spans, seed_round)

NONE = {"k": None, "d": None}


def kd(k, d):
    return {"k": k, "d": d}


# Three rounds; the buy phase is 25 s, so boundary windows run
# b0 (-inf, 25 s], b1 [105 s, 135 s], b2 [205 s, 235 s], b3 [305 s, inf).
ROUNDS = [
    {"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100000.0, "t_close_ms": 105000.0},
    {"round_no": 2, "t_start_ms": 110000.0, "t_end_ms": 200000.0, "t_close_ms": 205000.0},
    {"round_no": 3, "t_start_ms": 210000.0, "t_end_ms": 300000.0, "t_close_ms": 305000.0},
]


def read(t, k, d):
    return {"t_ms": t, "kills": k, "deaths": d, "is_player": True}


class ClassifyTests(unittest.TestCase):
    def test_three_way(self):
        c = classify(kd(1, 1), kd(1, 1), kd(1, 1))
        self.assertEqual(c["kind"], THREE_WAY)
        self.assertEqual(c["available"], ["killfeed", "report", "scoreboard"])

    def test_two_way(self):
        self.assertEqual(classify(kd(2, 0), kd(2, 0), NONE)["kind"], TWO_WAY)

    def test_disagree(self):
        c = classify(kd(1, 0), kd(1, 1), NONE)
        self.assertEqual(c["kind"], DISAGREE)
        self.assertEqual(c["differ"], [{"pair": ["killfeed", "report"], "field": "d",
                                        "killfeed": 0, "report": 1}])

    def test_disagree_beats_a_third_agreeing_channel(self):
        self.assertEqual(classify(kd(1, 1), kd(1, 1), kd(2, 1))["kind"], DISAGREE)

    def test_unwitnessed(self):
        self.assertEqual(classify(kd(1, 1), NONE, NONE)["kind"], UNWITNESSED)

    def test_half_read_channel_is_not_available(self):
        self.assertEqual(classify(kd(1, 1), {"k": 1, "d": None}, NONE)["kind"], UNWITNESSED)


class ScoreboardTests(unittest.TestCase):
    """b0 read 0/0, b1 unread, b2 read 2/1, b3 split between 3/1 and 4/1."""

    reads = [read(10000.0, 0, 0),
             read(60000.0, 1, 0),                      # mid-round: serves no boundary
             read(120000.0, None, 1),                  # in b1, but no K
             read(210000.0, 2, 1), read(212000.0, 2, 1), read(213000.0, 9, 1),
             read(310000.0, 3, 1), read(311000.0, 4, 1)]
    kf = {1: kd(1, 1), 2: kd(1, 0), 3: kd(1, 0)}
    rep = {1: kd(1, 1), 2: kd(1, 0), 3: kd(1, 0)}

    def setUp(self):
        self.bounds = boundaries(self.reads, ROUNDS)

    def test_boundaries(self):
        b = self.bounds
        self.assertEqual(len(b), 4)
        self.assertEqual((b[0]["k"], b[0]["d"], b[0]["reads"], b[0]["reason"]), (0, 0, 1, None))
        self.assertEqual((b[1]["k"], b[1]["reads"], b[1]["reason"]), (None, 1, NO_READ))
        self.assertEqual((b[2]["k"], b[2]["d"], b[2]["reads"]), (2, 1, 3))
        self.assertEqual((b[3]["k"], b[3]["d"], b[3]["reason"]), (None, None, SPLIT_READ))

    def test_no_stream(self):
        b = boundaries(None, ROUNDS)
        self.assertTrue(all(x["k"] is None and x["reason"] == "no scoreboard stream stored"
                            for x in b))

    def test_rounds(self):
        sb = scoreboard_rounds(self.bounds, ROUNDS)
        self.assertEqual(sb[1]["reason"], f"after: {NO_READ}")
        self.assertEqual(sb[2]["reason"], f"before: {NO_READ}")
        self.assertEqual(sb[3]["reason"], f"after: {SPLIT_READ}")
        self.assertTrue(all(sb[n]["k"] is None for n in (1, 2, 3)))

    def test_two_round_span(self):
        spans = scoreboard_spans(self.bounds, ROUNDS, self.kf, self.rep)
        self.assertEqual(len(spans), 1)
        s = spans[0]
        self.assertEqual(s["rounds"], [1, 2])
        self.assertEqual((s["scoreboard"], s["killfeed"], s["report"]),
                         (kd(2, 1), kd(2, 1), kd(2, 1)))
        self.assertTrue(s["agree_killfeed"])
        self.assertTrue(s["agree_report"])

    def test_span_without_a_report_panel(self):
        rep = {**self.rep, 2: NONE}
        kf = {**self.kf, 2: kd(0, 0)}
        s = scoreboard_spans(self.bounds, ROUNDS, kf, rep)[0]
        self.assertIsNone(s["report"]["k"])
        self.assertIsNone(s["agree_report"])
        self.assertFalse(s["agree_killfeed"])


def death(death_id, t, **kw):
    return {"kind": "death_verdict", "death_id": death_id, "round_no": 1, "t_ms": t,
            "kf_player_kill": False, "kf_player_death": False, "is_second_life": False,
            "is_revive": False, "status": "resolved", "metadata": {}, **kw}


def death_panel(start_ms, *, entity_id, death_entity=None):
    row = {"out": 0, "in": 150, "out_hits": 0, "in_hits": 1, "killed": False, "assist": False,
           "killed_you": True, "ally": False, "portrait": None, "entity_id": entity_id}
    if death_entity is not None:
        row["death_entity"] = death_entity
    return {"start_ms": start_ms, "end_ms": start_ms + 3000.0, "at_death": True, "kind": "death",
            "round_no": 1, "round_reason": None, "reopens": [], "rows": [row]}


class LifeEpisodeTests(unittest.TestCase):
    def test_second_life_does_not_end_a_life(self):
        ev = [death("d1", 10000.0, kf_player_death=True, is_second_life=True),
              death("k1", 20000.0, kf_player_kill=True),
              death("d2", 30000.0, kf_player_death=True),
              death("k2", 40000.0, kf_player_kill=True)]
        self.assertEqual(life_episodes(ev), {"d1": 1, "k1": 1, "d2": 1, "k2": 2})


class SeedRoundTests(unittest.TestCase):
    def test_duplicate_beside_a_miss_is_flagged(self):
        # The killfeed holds the real death at 10 s and a phantom at 50 s; the
        # report opened at 10 s and at 30 s, a death the killfeed missed. Both
        # channels total two deaths, and the scoreboard agrees.
        rows = [death("d10", 10000.0, kf_player_death=True),
                death("d50", 50000.0, kf_player_death=True)]
        panels = [death_panel(10500.0, entity_id="e1", death_entity="d10:killer"),
                  death_panel(30500.0, entity_id="e2")]
        self.assertEqual(classify(kd(0, 2), kd(0, 2), kd(0, 2))["kind"], THREE_WAY)
        s = seed_round(1, rows, panels, {})
        self.assertTrue(s["flag"])
        self.assertEqual(s["unbound_panels"], [30500.0])
        self.assertEqual(s["unpanelled_deaths"], ["d50"])
        self.assertEqual([d["report_bound"] for d in s["deaths"]], [True, False])
        self.assertEqual([d["life"] for d in s["deaths"]], [1, 2])

    def test_matched_round_is_not_flagged(self):
        rows = [death("d10", 10000.0, kf_player_death=True)]
        panels = [death_panel(10500.0, entity_id="e1", death_entity="d10:killer")]
        s = seed_round(1, rows, panels, {})
        self.assertFalse(s["flag"])
        self.assertEqual((s["unbound_panels"], s["unpanelled_deaths"]), ([], []))
        self.assertTrue(s["deaths"][0]["report_bound"])


if __name__ == "__main__":
    unittest.main()
