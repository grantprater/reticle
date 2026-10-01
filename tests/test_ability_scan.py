"""The ability pass's shape reader: the live and drawn gates, the teal gate,
and the two streams it writes under their own stamps."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from reticle import ability_scan as A
from reticle.version import ABILITY_GATE_VERSION, ABILITY_SHAPE_VERSION

TEAL = (180, 170, 30)


def _base() -> np.ndarray:
    rng = np.random.default_rng(0)
    img = np.full((331, 331, 3), 40, np.uint8)
    cv2.rectangle(img, (60, 60), (270, 270), (128, 128, 128), -1)
    noise = rng.integers(0, 60, (331, 331, 1), dtype=np.uint8)
    return cv2.add(img, np.repeat(noise, 3, axis=2))


class ShapeReaderTest(unittest.TestCase):
    def setUp(self):
        self.base = _base()
        floor = np.zeros(self.base.shape[:2], bool)
        floor[60:271, 60:271] = True
        sgray = cv2.cvtColor(self.base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        phase = {0.0: "round_live", 500.0: "round_live", 1000.0: "buy", 1500.0: "post_plant"}
        self.reader = A.AbilityShapeReader(floor=floor, sgray=sgray, support=floor,
                                           box=(0, 0, 331, 331), phase_at=phase.get)

    def feed(self, img, t, idx):
        self.reader.feed(SimpleNamespace(frame=img, t_ms=t, frame_idx=idx))

    def test_gate_closed_open_and_not_live(self):
        ring = self.base.copy()
        cv2.circle(ring, (150, 160), 45, TEAL, 2)
        self.feed(self.base, 0.0, 0)
        self.feed(ring, 500.0, 30)
        self.feed(ring, 1000.0, 60)
        self.feed(ring, 1500.0, 90)
        g = self.reader.gate_rows
        self.assertEqual([r["gate"] for r in g], [False, True, None, True])
        self.assertEqual(g[2]["reason"], "not_live")
        s = self.reader.shape_rows
        self.assertEqual([r["t_ms"] for r in s], [500.0, 1500.0])
        best = s[0]["rings"][0]
        self.assertTrue(best["accepted"])
        self.assertLessEqual(np.hypot(best["cx"] - 150, best["cy"] - 160), 2)

    def test_each_stream_carries_its_own_stamp(self):
        self.feed(self.base, 0.0, 0)
        gate = self.reader.gate_events("s", "k")
        shape = self.reader.shape_events("s", "k")
        self.assertEqual(gate[0]["kind"], "coverage")
        self.assertEqual(gate[0]["ability_gate_version"], ABILITY_GATE_VERSION)
        self.assertNotIn("ability_shape_version", gate[0])
        self.assertEqual(shape[0]["ability_shape_scan_version"], ABILITY_SHAPE_VERSION)
        self.assertEqual(shape[0]["ability_gate_version"], ABILITY_GATE_VERSION)
        self.assertEqual(gate[0]["by_reason"], {"closed": 1})

    def test_without_a_supply_every_gated_sample_is_a_surprise(self):
        ring = self.base.copy()
        cv2.circle(ring, (150, 160), 45, TEAL, 2)
        self.feed(ring, 500.0, 30)
        s = self.reader.shape_events("s", "k")
        self.assertEqual(s[0]["by_reason"], {"no_supply": 1})
        self.assertEqual(s[0]["surprise_rate"], 1.0)
        self.assertEqual(self.reader.fit_events("s", "k")[0]["supply_reason"], "no_supply")


def _desc(shape, ability, prior="free", **sizes) -> dict:
    """A synthetic candidate in the surprise teal, as `CandidateSupply.at` gives it."""
    d = {"id": f"{ability}:ally", "ability": ability, "agent": "X", "side": "ally",
         "shape": shape, "prior": prior, "colour": A.shapes.SURPRISE_COLOUR,
         "selected": "named", "caster_alive": True, "seed": None,
         "rests_on": ["death", "lineup"], **sizes}
    if shape == "beam":
        d["geo"] = A.shapes.beam_geometry(d["width_px"], A.shapes.SET_AT)
    return d


class FakeSupply:
    """Ring and wall candidates, and one exclusion, at every time."""

    stamp = {"ability_candidates_version": "test-0", "lineup": "l", "death": "d"}

    def __init__(self, cands):
        self.cands = cands

    def at(self, t_ms):
        return {"candidates": [dict(c) for c in self.cands],
                "excluded": [{"ability": "Blaze", "side": "enemy", "agent": "Phoenix",
                              "reason": "no_enemy_colour: unmeasured"},
                             {"ability": "Recon Bolt", "side": "ally", "agent": "Sova",
                              "reason": "not_in_lineup"}]}


class CandidateTest(unittest.TestCase):
    RING = _desc("ring", "Ring", radius_px=45.0)
    WALL = _desc("segments", "Wall", length_px=25.3, pieces_px=[7.8, 13.5, 19.2], width_px=3.1)

    def setUp(self):
        self.base = _base()
        floor = np.zeros(self.base.shape[:2], bool)
        floor[60:271, 60:271] = True
        sgray = cv2.cvtColor(self.base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        self.reader = A.AbilityShapeReader(
            floor=floor, sgray=sgray, support=floor, box=(0, 0, 331, 331),
            supply=FakeSupply([self.RING, self.WALL]), audit_every=3, values="v1")

    def feed(self, img, t, idx):
        self.reader.feed(SimpleNamespace(frame=img, t_ms=t, frame_idx=idx))

    def test_a_candidate_fit_spares_the_surprise_path_but_not_the_audit(self):
        ring = self.base.copy()
        cv2.circle(ring, (150, 160), 45, TEAL, 2)
        for i in range(4):
            self.feed(ring, 500.0 * i, 30 * i)
        fits = self.reader.fit_rows
        self.assertEqual(len(fits), 4)
        f = fits[0]["fits"][0]
        self.assertTrue(f["found"])
        self.assertEqual(f["descriptor"], "Ring:ally")
        self.assertEqual(f["rests_on"], ["death", "lineup"])
        self.assertLessEqual(np.hypot(f["cx"] - 150, f["cy"] - 160), 2)
        # The constant exclusion stays in the head; the rest go per sample.
        self.assertEqual(fits[0]["excluded"],
                         [{"ability": "Blaze", "side": "enemy",
                           "reason": "no_enemy_colour: unmeasured"}])
        self.assertEqual(self.reader.shape_rows, [])
        self.assertEqual([r["audit_n"] for r in self.reader.audit_rows], [1, 4])
        self.assertTrue(all(r["candidate_accepted"] for r in self.reader.audit_rows))
        head = self.reader.fit_events("s", "k")[0]
        self.assertEqual(head["surprise_rate"], 0.0)
        self.assertEqual(head["by_descriptor"], {"Ring:ally": {"fits": 4, "found": 4}})
        self.assertEqual(head["excluded"]["Recon Bolt:ally:not_in_lineup"], 4)
        self.assertEqual(head["ability_candidates_version"], "test-0")
        self.assertEqual(head["appearance_values"], "v1")
        self.assertEqual(head["ability_fit_version"], A.ABILITY_FIT_VERSION)

    def test_a_ring_no_candidate_explains_is_a_surprise(self):
        ring = self.base.copy()
        cv2.circle(ring, (150, 160), 70, TEAL, 2)
        self.feed(ring, 0.0, 0)
        self.assertFalse(self.reader.fit_rows[0]["fits"][0]["found"])
        self.assertEqual(self.reader.shape_rows[0]["surprise_reason"], "none_accepted")
        self.assertEqual(self.reader.shape_events("s", "k")[0]["surprise_rate"], 1.0)

    def test_a_wall_is_read_where_the_teal_gate_stays_shut(self):
        img = self.base.copy()
        cv2.rectangle(img, (140, 149), (165, 151), TEAL, -1)
        self.feed(img, 0.0, 0)
        self.assertEqual([r["gate"] for r in self.reader.gate_rows], [False])
        w = self.reader.wall_rows[0]["walls"][0]
        self.assertTrue(w["found"])
        self.assertEqual(w["descriptor"], "Wall:ally")
        head = self.reader.wall_events("s", "k")[0]
        self.assertEqual(head["ability_wall_version"], A.ABILITY_WALL_VERSION)
        self.assertEqual(head["by_descriptor"], {"Wall:ally": {"rows": 1, "found": 1, "piece": 0}})
        self.assertEqual(list(head["descriptors"]), ["Wall:ally"])

    def test_a_sample_without_a_wall_component_stores_no_wall_row(self):
        self.feed(self.base, 0.0, 0)
        self.assertEqual(self.reader.wall_rows, [])


YELLOW_BGR = (40, 220, 230)


class OwnGateTest(unittest.TestCase):
    """A candidate whose colour the teal gate cannot see opens its own gate."""

    def setUp(self):
        self.base = _base()
        floor = np.zeros(self.base.shape[:2], bool)
        floor[60:271, 60:271] = True
        sgray = cv2.cvtColor(self.base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        self.yellow = {**_desc("ring", "Yellow", radius_px=45.0),
                       "colour": {"hue": (20.0, 41.0), "s_min": 80.0}}
        self.reader = A.AbilityShapeReader(
            floor=floor, sgray=sgray, support=floor, box=(0, 0, 331, 331),
            supply=FakeSupply([CandidateTest.RING, self.yellow]), audit_every=100)

    def feed(self, img, t, idx):
        self.reader.feed(SimpleNamespace(frame=img, t_ms=t, frame_idx=idx))

    def test_own_gate_follows_the_hue_band(self):
        self.assertTrue(A.own_gate(self.yellow))
        self.assertFalse(A.own_gate(CandidateTest.RING))

    def test_a_yellow_ring_is_fit_where_the_teal_gate_stays_shut(self):
        img = self.base.copy()
        cv2.circle(img, (150, 160), 45, YELLOW_BGR, 2)
        self.feed(img, 0.0, 0)
        self.feed(self.base, 500.0, 1)
        self.assertEqual([r["gate"] for r in self.reader.gate_rows], [False, False])
        self.assertEqual(len(self.reader.fit_rows), 1)
        row = self.reader.fit_rows[0]
        self.assertIs(row["teal_gate"], False)
        f = row["fits"][0]
        self.assertEqual((f["descriptor"], f["gate"]), ("Yellow:ally", "own_colour"))
        self.assertTrue(f["found"])
        self.assertLessEqual(np.hypot(f["cx"] - 150, f["cy"] - 160), 2)
        self.assertEqual(self.reader.n_gated, 0)
        self.assertEqual(self.reader.shape_rows, [])
        self.assertEqual(self.reader.fit_events("s", "k")[0]["own_colour_rows"], 1)

    def test_an_own_gate_find_never_spares_a_teal_surprise(self):
        img = self.base.copy()
        cv2.circle(img, (150, 160), 45, YELLOW_BGR, 2)
        cv2.circle(img, (160, 150), 70, TEAL, 2)
        self.feed(img, 0.0, 0)
        row = self.reader.fit_rows[0]
        self.assertIs(row["teal_gate"], True)
        found = {f["descriptor"]: f["found"] for f in row["fits"]}
        self.assertEqual(found, {"Ring:ally": False, "Yellow:ally": True})
        self.assertEqual(self.reader.shape_rows[0]["surprise_reason"], "none_accepted")


if __name__ == "__main__":
    unittest.main()
