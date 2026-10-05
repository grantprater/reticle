"""Blind spans from stored primitives, and the killfeed tracker across them.

At a06f04a0059f Skye's blind hid the killfeed 1768.4-1771.2 s
[domain:abilities/skye-guiding-light-blind-screen]; an entry read once at
1768.0 s (slot 1, divider 186, ally victim) returned faded at 1771.0 s with
its plates one colour and its victim side enemy.
"""
import unittest

import numpy as np

from reticle.blinds import hidden_ms, inside, spans
from reticle.checks import track_entries
from reticle.killfeed import WX_BITS

ALLY, ENEMY = 1, 2


def prim(t, edge, mm, luma, motion=0.05):
    n = len(t)
    full = lambda v: list(v) if isinstance(v, (list, np.ndarray)) else [v] * n
    return {"t_ms": np.asarray(t, float), "killfeed_edge": np.asarray(full(edge), float),
            "minimap_std": np.asarray(full(mm), float), "luma_mean": np.asarray(full(luma), float),
            "motion": np.asarray(full(motion), float)}


class SpanTests(unittest.TestCase):
    def setUp(self):
        # 5 Hz, 0-6 s: a wash from 2.0 to 3.0 s, flaring to 0.70 then fading.
        self.t = [i * 200.0 for i in range(31)]
        core = lambda x: 2000 <= x <= 3000
        self.edge = [0.0 if core(x) else 0.03 for x in self.t]
        self.mm = [0.03 if core(x) else 0.15 for x in self.t]
        fade = {3200: 0.70, 3400: 0.55, 3600: 0.45, 3800: 0.38}
        self.luma = [0.42 if core(x) else fade.get(x, 0.35) for x in self.t]

    def test_a_washed_hud_is_a_blind_and_its_fade_extends_it(self):
        got = spans(prim(self.t, self.edge, self.mm, self.luma))
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["t_start_ms"], got[0]["core_end_ms"], got[0]["t_end_ms"]),
                         (2000.0, 3000.0, 3600.0))

    def test_an_edgeless_killfeed_over_a_live_minimap_is_no_blind(self):
        self.assertEqual(spans(prim(self.t, self.edge, 0.15, self.luma)), [])

    def test_a_dark_or_frozen_frame_is_no_blind(self):
        self.assertEqual(spans(prim(self.t, self.edge, self.mm, 0.14)), [])
        self.assertEqual(spans(prim(self.t, self.edge, self.mm, self.luma, motion=0.0)), [])

    def test_a_table_without_the_killfeed_edge_is_unknown(self):
        p = prim(self.t, self.edge, self.mm, self.luma)
        del p["killfeed_edge"]
        self.assertEqual(spans(p), [])

    def test_hidden_time_and_cover(self):
        s = [{"t_start_ms": 2000.0, "t_end_ms": 3000.0}]
        self.assertEqual(hidden_ms(s, 1500.0, 2500.0), 500.0)
        self.assertEqual(list(inside(s, [1999.0, 2000.0, 3000.0, 3001.0])),
                         [False, True, True, False])


class TrackerTests(unittest.TestCase):
    """The a06f04a0059f window, 1764.5-1773.5 s, at 2 Hz."""

    def setUp(self):
        self.t = [1764500.0 + 500.0 * i for i in range(19)]
        mask, wx, side = [], [], []
        for x in self.t:
            s = {}
            if x <= 1768000:
                s[0] = (268, ENEMY)
            if x == 1768000:
                s[1] = (186, ALLY)
            if x == 1771000:
                s[0] = (187, ENEMY)                     # faded, read wrong
            if 1771500 <= x <= 1772500:
                s[0] = (186, ALLY)
                s[1] = (286, ENEMY)
            if x == 1773000:
                s[1] = (286, ENEMY)
            mask.append(sum(1 << k for k in s))
            wx.append(s)
            a = sum(1 << k for k, (_, sd) in s.items() if sd == ALLY)
            e = sum(1 << k for k, (_, sd) in s.items() if sd == ENEMY)
            side.append((a, e, 1 if x == 1771000 else 0))
        self.mask, self.side = mask, side
        # One packed column per sample, laid out as `divider_of_ys` writes it.
        self.wx = [sum(w << (WX_BITS * k) for k, (w, _) in s.items()) or None for s in wx]
        self.blinds = [{"t_start_ms": 1768400.0, "t_end_ms": 1771200.0}]

    def tracks(self, blinds):
        return [a for a in track_entries(self.t, self.mask, self.wx, sides=self.side,
                                         blinds=blinds) if a["counted"]]

    def test_without_blinds_the_onset_is_lost_and_the_faded_read_begins_an_entry(self):
        got = self.tracks(None)
        self.assertNotIn(1768000.0, [a["t_first"] for a in got])
        self.assertIn(1771000.0, [a["t_first"] for a in got])

    def test_a_blind_keeps_the_entry_and_its_side(self):
        got = self.tracks(self.blinds)
        e = next(a for a in got if a["t_first"] == 1768000.0)
        self.assertEqual(e["slot_first"], 1)
        self.assertEqual(e["side"], "ally")
        self.assertEqual(e["t_last"], 1772500.0)
        self.assertTrue(e["blinded"])
        self.assertNotIn(1771000.0, [a["t_first"] for a in got])


if __name__ == "__main__":
    unittest.main()
