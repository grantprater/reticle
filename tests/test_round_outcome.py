"""The round-history strip's outcome icons: cell reading, pooling, and the
deaths a capture stall swallowed at an elimination round end."""
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import round_outcome as ro
from reticle.adjudication import round_outcome as pool
from reticle.adjudication.death import DeathVerdict, infer_stall_deaths
from reticle.scoreboard_strip import ROW_Y
from reticle.store import DEFAULT_STORE

SIDE = 19
TEAL = np.array([200, 200, 40], np.float32)      # BGR, G - R = 160
RED = np.array([40, 40, 220], np.float32)        # G - R = -180
PLATE = 70.0


def _icons() -> dict:
    """Four distinct alpha shapes standing in for the build's textures."""
    out = {}
    disc = np.zeros((SIDE, SIDE), np.float32)
    cv2.circle(disc, (9, 9), 8, 1.0, -1)
    out["elimination"] = disc
    ring = np.zeros_like(disc)
    cv2.rectangle(ring, (2, 2), (16, 16), 1.0, 3)
    out["defuse"] = ring
    cross = np.zeros_like(disc)
    cv2.line(cross, (2, 2), (16, 16), 1.0, 3)
    cv2.line(cross, (16, 2), (2, 16), 1.0, 3)
    out["detonation"] = cross
    tri = np.zeros_like(disc)
    cv2.fillPoly(tri, [np.array([[9, 1], [17, 17], [1, 17]], np.int32)], 1.0)
    out["time"] = tri
    return out


def _band(columns, cells, icons):
    """A band of grey plate with, per column, an icon on one line and a grey
    dot on the other, or dots on both. `cells` maps column index to
    (reason, line, colour) or None."""
    pad = ro.BAND_PAD
    h = ROW_Y[1] - ROW_Y[0] + 2 * pad + 1
    band = np.full((h, int(max(columns)) + 40, 3), PLATE, np.float32)
    lines = (pad, pad + ROW_Y[1] - ROW_Y[0])
    for j, x in enumerate(columns):
        spec = cells.get(j)
        for li, y in enumerate(lines):
            if spec is not None and li == ("ally", "enemy").index(spec[1]):
                a = icons[spec[0]][..., None]
                ys, xs = slice(y - SIDE // 2, y + SIDE // 2 + 1), slice(x - SIDE // 2, x + SIDE // 2 + 1)
                band[ys, xs] = band[ys, xs] * (1 - a) + spec[2] * a
            else:
                cv2.circle(band, (x, y), 2, (150, 150, 150), -1)
    return np.clip(band, 0, 255).astype(np.uint8)


class CellTest(unittest.TestCase):
    def setUp(self):
        self.icons = _icons()
        self.cols = [30, 60, 90, 120, 150, 180]

    def test_each_reason_line_and_tint(self):
        cells = {0: ("elimination", "ally", TEAL), 1: ("defuse", "enemy", RED),
                 2: ("detonation", "ally", TEAL), 3: ("time", "enemy", RED)}
        got = ro.read_cells(_band(self.cols, cells, self.icons), 0, self.cols, self.icons)
        self.assertEqual([c["round"] for c in got], [1, 2, 3, 4, 5, 6])
        for j, (reason, line, _) in cells.items():
            c = got[j]
            self.assertEqual(c["verdict"], "icon", c)
            self.assertEqual((c["reason"], c["line"]), (reason, line))
            self.assertEqual(c["tint"], "teal" if line == "ally" else "red")
            self.assertGreaterEqual(c["ink"], ro.INK_MIN)
        # Unplayed columns: dots on both lines read empty, never an icon.
        self.assertEqual([c["verdict"] for c in got[4:]], ["empty", "empty"])

    def test_colourless_icon_is_not_an_icon(self):
        # A grey icon shape scores on texture but carries no ink.
        cells = {0: ("elimination", "ally", np.array([120, 120, 120], np.float32))}
        got = ro.read_cells(_band(self.cols, cells, self.icons), 0, self.cols, self.icons)
        self.assertNotEqual(got[0]["verdict"], "icon")

    def test_column_outside_band_is_unread(self):
        band = _band(self.cols, {}, self.icons)
        got = ro.read_cells(band, 0, [5], self.icons)
        self.assertEqual((got[0]["verdict"], got[0]["refusal"]), ("unread", "column_outside_crop"))

    def test_layout_constants_match_game_files(self):
        build = Path(DEFAULT_STORE) / "reference" / "game-files" / ro.GAME_BUILD
        if not (build / ro.LAYOUT_DIR / "ScoreboardRound.json").is_file():
            self.skipTest("no exported widget JSON in the store")
        got = ro.layout_from_game_files(build)
        self.assertEqual(got, {"icon_units": ro.ICON_UNITS,
                               "history_inset_units": ro.HISTORY_INSET_UNITS})


def _frame(t, cells, idx=None):
    return {"kind": "frame", "t_ms": float(t), "frame_idx": idx if idx is not None else int(t // 100),
            "round_outcome_version": "round-outcome-test", "cells": cells}


def _icon(n, reason, line="ally", tint="teal"):
    return {"round": n, "verdict": "icon", "reason": reason, "line": line, "tint": tint}


ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100_000.0, "score_us": 0,
           "score_them": 0, "won": True},
          {"round_no": 2, "t_start_ms": 110_000.0, "t_end_ms": 200_000.0, "score_us": 1,
           "score_them": 0, "won": False}]


class PoolTest(unittest.TestCase):
    def test_game_round_from_scores(self):
        self.assertEqual(pool.game_round({"score_us": 7, "score_them": 5}), 13)
        self.assertIsNone(pool.game_round({"score_us": None, "score_them": 5}))

    def test_frames_before_round_end_do_not_vote(self):
        frames = [_frame(50_000, [_icon(1, "defuse")]),          # before round 1 ended
                  _frame(105_000, [_icon(1, "elimination")]),
                  _frame(150_000, [_icon(1, "elimination"), _icon(2, "time", "enemy", "red")]),
                  _frame(210_000, [_icon(1, "elimination"), _icon(2, "time", "enemy", "red")]),
                  _frame(220_000, [_icon(1, "elimination"), _icon(2, "time", "enemy", "red")])]
        c1, c2 = pool.pool_outcomes("s", frames, ROUNDS)
        self.assertEqual((c1["end_reason"], c1["winner"], c1["frames"]), ("elimination", "ally", 4))
        self.assertEqual(c1["claim_id"], "s:round_outcome:1")
        self.assertFalse(c1["won_disagrees"])
        self.assertEqual((c2["end_reason"], c2["winner"], c2["frames"]), ("time", "enemy", 2))
        self.assertIsNone(c2["refusal"])

    def test_disagreement_refuses_and_keeps_votes(self):
        frames = [_frame(101_000 + k, [_icon(1, r)])
                  for k, r in enumerate(["elimination", "defuse", "elimination", "defuse"])]
        c1 = pool.pool_outcomes("s", frames, ROUNDS)[0]
        self.assertEqual(c1["refusal"], "frames_disagree")
        self.assertIsNone(c1["end_reason"])
        self.assertEqual(c1["reason_votes"], {"elimination": 2, "defuse": 2})

    def test_few_and_no_frames(self):
        c1, c2 = pool.pool_outcomes("s", [_frame(101_000, [_icon(1, "time")])], ROUNDS)
        self.assertEqual(c1["refusal"], "few_frames")
        self.assertEqual(c2["refusal"], "no_frames")

    def test_winner_disagreeing_with_stored_won_is_recorded(self):
        frames = [_frame(101_000 + k, [_icon(1, "elimination", "enemy", "red")]) for k in range(3)]
        c1 = pool.pool_outcomes("s", frames, ROUNDS)[0]
        self.assertEqual(c1["winner"], "enemy")
        self.assertTrue(c1["won_disagrees"])
        self.assertTrue(c1["won_stored"])

    def test_tint_against_line_is_counted(self):
        frames = [_frame(101_000 + k, [_icon(1, "elimination", "ally", "red" if k == 0 else "teal")])
                  for k in range(3)]
        self.assertEqual(pool.pool_outcomes("s", frames, ROUNDS)[0]["tint_disagrees"], 1)


LINEUP = {"sides": {"ally": [{"agent": a} for a in ("Jett", "Sova", "Omen", "Sage", "Fade")],
                    "enemy": [{"agent": a} for a in ("Reyna", "Vyse", "Miks", "Breach", "Clove")]}}
STALL = [{"t_start_ms": 90_000.0, "t_end_ms": 99_800.0}]
ROUND = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100_000.0}]


def _death(i, t, side, victim, revive=False):
    return DeathVerdict(death_id=f"d{i}", t_ms=float(t), side=side, victim=victim,
                        status="resolved", is_revive=revive)


def _claim(reason="elimination", winner="ally", refusal=None):
    return [{"round_no": 1, "claim_id": "s:round_outcome:1", "end_reason": reason,
             "winner": winner, "refusal": refusal}]


def _results(verdicts):
    return [{"round_no": 1, "entries": [{} for _ in verdicts], "verdicts": verdicts}]


class StallDeathTest(unittest.TestCase):
    def test_living_losers_die_in_the_gap(self):
        before = [_death(1, 10_000, "enemy", "Reyna"), _death(2, 20_000, "enemy", "Vyse"),
                  _death(3, 30_000, "ally", "Jett")]
        got = infer_stall_deaths("s", _results(before), ROUND, STALL, _claim(), LINEUP)
        self.assertEqual(got["refused"], [])
        rows = got["inferred"]
        self.assertEqual(sorted(r["victim"] for r in rows), ["Breach", "Clove", "Miks"])
        r = rows[0]
        self.assertTrue(r["inferred"])
        self.assertIsNone(r["t_ms"])
        self.assertEqual(r["t_window_ms"], [90_000.0, 99_800.0])
        self.assertIsNone(r["killer"])
        self.assertEqual(r["killer_reason"], "unobserved interval")
        self.assertEqual(r["rests_on"], {"deaths": ["d1", "d2", "d3"],
                                         "outcome_claim": "s:round_outcome:1"})
        self.assertEqual(r["identity"]["status"], "resolved")
        self.assertEqual(r["identity"]["agent"], r["victim"])
        self.assertEqual(r["identity"]["independent_channels"], 0)

    def test_allies_follow_the_same_rule_and_revives_return(self):
        before = [_death(1, 10_000, "ally", "Jett"), _death(2, 20_000, "ally", "Sova"),
                  _death(3, 30_000, "ally", "Jett", revive=True)]
        got = infer_stall_deaths("s", _results(before), ROUND, STALL, _claim(winner="enemy"), LINEUP)
        self.assertEqual(sorted(r["victim"] for r in got["inferred"]),
                         ["Fade", "Jett", "Omen", "Sage"])

    def test_late_killfeed_entry_binds_without_redating(self):
        verdicts = [_death(1, 10_000, "enemy", "Reyna"), _death(9, 102_000, "enemy", "Miks"),
                    _death(8, 99_500, "enemy", "Breach"), _death(7, 120_000, "enemy", "Clove")]
        rows = infer_stall_deaths("s", _results(verdicts), ROUND, STALL, _claim(), LINEUP)["inferred"]
        miks = next(r for r in rows if r["victim"] == "Miks")
        self.assertEqual(miks["late_witness"], {"death_id": "d9", "t_ms": 102_000.0})
        self.assertIsNone(miks["t_ms"])
        self.assertIsNone(next(r for r in rows if r["victim"] == "Vyse")["late_witness"])
        # an entry sampled at the gap's edge witnesses too; one long after does not
        self.assertEqual(next(r for r in rows if r["victim"] == "Breach")["late_witness"]["death_id"], "d8")
        self.assertIsNone(next(r for r in rows if r["victim"] == "Clove")["late_witness"])

    def test_refusals(self):
        res = _results([_death(1, 10_000, "enemy", "Reyna")])
        cases = [(None, "outcome_unread"), (_claim(refusal="frames_disagree"), "outcome_unread"),
                 (_claim(reason="defuse"), "ended_by_defuse")]
        for claims, why in cases:
            got = infer_stall_deaths("s", res, ROUND, STALL, claims, LINEUP)
            self.assertEqual(got["inferred"], [])
            self.assertEqual(got["refused"][0]["refusal"], why)
        roster = {"t_ms": np.array([50_000.0]), "alive_ally": np.array([5]),
                  "alive_enemy": np.array([2])}            # the prior holds 4 enemies alive
        got = infer_stall_deaths("s", res, ROUND, STALL, _claim(), LINEUP, roster)
        self.assertEqual(got["refused"][0]["refusal"], "prior_count_disagrees")
        dead = _results([_death(i, 1000 * i, "enemy", a) for i, a in
                         enumerate(("Reyna", "Vyse", "Miks", "Breach", "Clove"))])
        got = infer_stall_deaths("s", dead, ROUND, STALL, _claim(), LINEUP)
        self.assertEqual(got["refused"][0]["refusal"], "none_alive")

    def test_end_read_after_release_counts_only_with_score_unread(self):
        res = _results([_death(1, 10_000, "enemy", "Reyna")])
        late_end = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 104_000.0, "won_left": True}]
        hud = {"t_ms": np.array([99_000.0, 101_000.0, 102_000.0, 104_000.0]),
               "score_left": [3, None, None, 4], "score_right": [2, 2, 2, 2]}
        got = infer_stall_deaths("s", res, late_end, STALL, _claim(), LINEUP, None, hud)
        self.assertEqual(len(got["inferred"]), 4)
        self.assertEqual(got["inferred"][0]["end_in_gap"], "score_unread_after_release")
        hud["score_left"] = [3, None, 3, 4]               # the old score read after release
        got = infer_stall_deaths("s", res, late_end, STALL, _claim(), LINEUP, None, hud)
        self.assertEqual(got, {"inferred": [], "refused": []})
        self.assertEqual(infer_stall_deaths("s", res, late_end, STALL, _claim(), LINEUP),
                         {"inferred": [], "refused": []})

    def test_round_end_outside_any_stall_infers_nothing(self):
        late = [{"t_start_ms": 50_000.0, "t_end_ms": 60_000.0}]
        got = infer_stall_deaths("s", _results([]), ROUND, late, _claim(), LINEUP)
        self.assertEqual(got, {"inferred": [], "refused": []})
        self.assertEqual(infer_stall_deaths("s", _results([]), ROUND, None, _claim(), LINEUP),
                         {"inferred": [], "refused": []})


if __name__ == "__main__":
    unittest.main()
