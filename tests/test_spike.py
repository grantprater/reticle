"""The spike reader (`reticle.spike`) and its carrier cross-check
(`adjudication.spike_carrier`), on synthetic crops and rows."""
import unittest

import cv2
import numpy as np

from reticle import spike
from reticle.adjudication.spike_carrier import check, frame_state

YELLOW = (40, 225, 205)          # BGR: G above R, as the glyph measures


def _crop(w=465, h=465):
    return np.full((h, w, 3), 128, np.uint8)


def _draw_glyph(crop, cx, cy, side, base_down):
    """Paint the rendered template into `crop` as yellow on grey."""
    t = spike.glyph_template(side, base_down)
    p = t.shape[0] // 2
    win = crop[cy - p:cy + p + 1, cx - p:cx + p + 1].astype(np.float32)
    a = t[..., None]
    win = win * (1 - a) + np.array(YELLOW, np.float32) * a
    crop[cy - p:cy + p + 1, cx - p:cx + p + 1] = win.astype(np.uint8)


class GlyphTest(unittest.TestCase):
    def test_reads_ground_and_carried(self):
        crop = _crop()
        _draw_glyph(crop, 100, 120, 21.0, True)
        _draw_glyph(crop, 300, 300, 17.5, False)
        got = spike.accepted(spike.glyph_fits(crop))
        by = {g["state"]: g for g in got}
        self.assertEqual(sorted(by), ["carried", "dropped"])
        self.assertLessEqual(abs(by["dropped"]["cx"] - 100) + abs(by["dropped"]["cy"] - 120), 2)
        self.assertLessEqual(abs(by["carried"]["cx"] - 300) + abs(by["carried"]["cy"] - 300), 2)
        self.assertGreater(by["carried"]["ncc"], by["carried"]["ncc_flip"])

    def test_a_widget_drawn_turned_over(self):
        # The screen draws the glyphs upright; a widget placed at rotation 180
        # reaches the reader turned back, glyphs upside down. The state names
        # the glyph as drawn on the screen.
        screen = _crop()
        _draw_glyph(screen, 100, 120, 21.0, True)            # dropped
        _draw_glyph(screen, 300, 300, 17.5, False)           # carried
        baked = cv2.rotate(screen, cv2.ROTATE_180)
        h, w = baked.shape[:2]
        turned = {g["state"]: g for g in spike.accepted(spike.glyph_fits(baked, rotation=180))}
        self.assertEqual(sorted(turned), ["carried", "dropped"])
        d, c = turned["dropped"], turned["carried"]
        self.assertLessEqual(abs(d["cx"] - (w - 1 - 100)) + abs(d["cy"] - (h - 1 - 120)), 2)
        self.assertLessEqual(abs(c["cx"] - (w - 1 - 300)) + abs(c["cy"] - (h - 1 - 300)), 2)
        # Read as if unturned, as spike-0.1.0 did, the states swap.
        plain = {(g["cx"], g["cy"]): g["state"]
                 for g in spike.accepted(spike.glyph_fits(baked))}
        self.assertEqual(plain.get((d["cx"], d["cy"])), "carried")

    def test_empty_floor_reads_nothing(self):
        self.assertEqual(spike.glyph_fits(_crop()), [])

    def test_orange_is_a_candidate(self):
        crop = _crop()
        t = spike.glyph_template(21.0, True)
        p = t.shape[0] // 2
        win = crop[100 - p:101 + p, 100 - p:101 + p].astype(np.float32)
        a = t[..., None]
        crop[100 - p:101 + p, 100 - p:101 + p] = (win * (1 - a) + np.array((20, 140, 230)) * a).astype(np.uint8)
        fits = spike.glyph_fits(crop)
        self.assertTrue(fits)
        self.assertEqual(spike.accepted(fits), [])
        self.assertEqual(fits[0]["reason"], "orange")


class OnGlyphTest(unittest.TestCase):
    carried = {"cx": 100, "cy": 100, "state": "carried", "reason": None}
    dropped = {"cx": 100, "cy": 100, "state": "dropped", "reason": None}

    ally_carrier = {"cx": 107.0, "cy": 92.5}          # at (CARRIER_DX, CARRIER_DY)

    def test_fit_on_the_glyph_is_refused(self):
        self.assertIsNotNone(spike.on_glyph(101, 102, [self.carried], 1.0))
        self.assertIsNotNone(spike.on_glyph(103, 102, [self.dropped], 1.0))
        # Near a carried glyph whose carrier is another icon: the glyph.
        self.assertIsNotNone(spike.on_glyph(97.2, 104.2, [self.carried], 1.0, [self.ally_carrier]))
        self.assertIsNotNone(spike.on_glyph(102, 97, [self.carried], 1.0, [self.ally_carrier]))

    def test_the_carrier_is_kept(self):
        # The carrier's own fit, at the carrier's place or pulled toward its
        # glyph, is an icon carrying the spike at its lower left.
        self.assertIsNone(spike.on_glyph(105.6, 95.8, [self.carried], 1.0))
        self.assertIsNone(spike.on_glyph(107, 92.5, [self.carried], 1.0, [self.ally_carrier]))
        self.assertIsNone(spike.on_glyph(103, 96, [self.carried], 1.0, [{"cx": 105, "cy": 95}]))
        # No carrier seen: a fit off the glyph's core may be the carrier.
        self.assertIsNone(spike.on_glyph(102.8, 95.8, [self.carried], 1.0))
        self.assertIsNone(spike.on_glyph(101, 104, [self.carried], 1.0))

    def test_far_or_rejected_glyphs_refuse_nothing(self):
        self.assertIsNone(spike.on_glyph(110, 110, [self.dropped], 1.0))
        self.assertIsNone(spike.on_glyph(100, 100, [{**self.dropped, "reason": "orange"}], 1.0))

    def test_carrier_offset(self):
        icons = [{"channel": "ally", "cx": 107.0, "cy": 92.0}, {"channel": "self", "cx": 80, "cy": 80}]
        got = spike.carrier_offset(self.carried, icons, 1.0)
        self.assertEqual(got["channel"], "ally")
        self.assertIsNone(spike.carrier_offset(self.carried, icons[1:], 1.0))

    def test_carrier_offset_turned_over(self):
        # On the screen the carrier sits up and right of its glyph; in a baked
        # frame turned back from 180, down and left.
        below = [{"channel": "ally", "cx": 93.0, "cy": 108.0}]
        above = [{"channel": "ally", "cx": 107.0, "cy": 92.0}]
        self.assertEqual(spike.carrier_offset(self.carried, below, 1.0, rotation=180)["channel"],
                         "ally")
        self.assertIsNone(spike.carrier_offset(self.carried, above, 1.0, rotation=180))
        self.assertIsNone(spike.carrier_offset(self.carried, below, 1.0))
        # on_glyph keeps the turned carrier and refuses a fit beside it.
        carrier = [{"cx": 93.0, "cy": 107.5}]
        self.assertIsNone(spike.on_glyph(95.5, 104.5, [self.carried], 1.0, carrier, rotation=180))
        self.assertIsNotNone(spike.on_glyph(102, 104, [self.carried], 1.0, carrier, rotation=180))
        self.assertIsNone(spike.on_glyph(102, 104, [self.carried], 1.0, carrier))


class RosterMarkerTest(unittest.TestCase):
    def _roster(self, slot=None):
        crop = np.full((spike.ROSTER_H, 317, 3), 60, np.uint8)
        if slot is not None:
            t = spike.marker_template().astype(np.uint8)
            x = spike.MARK_X0 + slot * spike.MARK_PITCH
            crop[68:78, x:x + t.shape[1]] = t[..., None]
        return crop

    def test_reads_the_slot(self):
        for k in range(5):
            self.assertEqual(spike.roster_marker(self._roster(k))["slot"], k)

    def test_no_marker(self):
        got = spike.roster_marker(self._roster())
        self.assertIsNone(got["slot"])
        self.assertEqual(got["reason"], "no_marker")

    def test_other_size_is_refused(self):
        self.assertEqual(spike.roster_marker(np.zeros((60, 317, 3), np.uint8))["reason"],
                         "roster_size")


def _frame(t, glyph=None, slot=None, icons=()):
    glyphs = [] if glyph is None else [{"cx": 100, "cy": 100, "state": glyph, "reason": None}]
    return {"kind": "frame", "t_ms": t, "reason": None, "glyphs": glyphs, "icons": list(icons),
            "marker": {"slot": slot, "reason": None if slot is not None else "no_marker"}}


class CarrierCheckTest(unittest.TestCase):
    head = {"kind": "coverage", "session": "s", "spike_version": spike.SPIKE_VERSION,
            "widget_scale": 1.0}
    ally = [{"channel": "ally", "cx": 107.0, "cy": 92.5, "r": 9}]

    def test_frame_state(self):
        s = frame_state(_frame(0, "carried", 2, self.ally), 1.0)
        self.assertEqual((s["glyph"], s["slot"], s["carrier_channel"]), ("carried", 2, "ally"))

    def test_frame_state_turned_over(self):
        row = {**_frame(0, "carried", 2, [{"channel": "self", "cx": 93.0, "cy": 107.5, "r": 9}]),
               "rotation": 180}
        self.assertEqual(frame_state(row, 1.0)["carrier_channel"], "self")
        self.assertIsNone(frame_state({**row, "rotation": 0}, 1.0)["carrier_channel"])

    def test_agreement_and_disagreements(self):
        rows = [self.head, _frame(0, "carried", 1, self.ally), _frame(1000),
                _frame(2000, None, 1), _frame(3000, "carried", None, self.ally)]
        got = check(rows, [], [], [])
        cov = got[0]
        self.assertEqual(cov["agree"], {"carried": 1, "none": 1})
        self.assertEqual(cov["disagreements"],
                         {"marker_without_glyph": 1, "glyph_without_marker": 1})
        self.assertEqual(cov["slot_by_channel"], {"1:ally": 1})

    def test_plant_and_loss(self):
        rows = [self.head] + [_frame(t, "carried", 3, self.ally) for t in range(0, 9000, 1000)]
        rows += [_frame(9000), _frame(10000, "dropped"), _frame(11000)]
        rows += [_frame(20000, "carried", 3, self.ally), _frame(30000, None, 3)]
        rounds = [{"round_no": 1, "t_start_ms": 0, "t_end_ms": 40000, "spike_planted": True,
                   "plant_t_ms": 25000.0}]
        rt = [float(t) for t in range(0, 40000, 500)]
        ra = [5 if t < 8500 else 4 for t in rt]
        got = check(rows, rounds, rt, ra)
        cov = got[0]
        self.assertEqual(cov["disagreements"].get("carried_after_plant"), 1)
        rd = next(r for r in got if r["kind"] == "round")
        self.assertTrue(rd["carrier_seen"])
        self.assertEqual(rd["planter_slot"]["slot"], 3)
        self.assertEqual(rd["planter_slot"]["depends_on"], "agent-from-slot")
        loss = next(r for r in got if r["kind"] == "carrier_lost")
        self.assertTrue(loss["death"])
        self.assertTrue(loss["dropped_glyph_seen"])


if __name__ == "__main__":
    unittest.main()
