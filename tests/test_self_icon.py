import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle import lineup, self_icon
from reticle.version import SELF_ICON_VERSION


def _frame(scores=None, reason=None, art=None):
    return {"kind": "frame", "t_ms": 0.0, "reason": reason,
            **({"composition_scores": scores} if scores else {}),
            **({"art_scores": art} if art else {})}


class AliveGateTests(unittest.TestCase):
    """A frame is the player's own only where five allies live on both sides of it."""

    def test_five_on_both_sides_passes(self):
        self.assertTrue(self_icon.all_alive([0, 500, 1000], [5, 5, 5], 700))

    def test_a_death_on_either_side_refuses(self):
        self.assertFalse(self_icon.all_alive([0, 500, 1000], [5, 5, 4], 700))
        self.assertFalse(self_icon.all_alive([0, 500, 1000], [5, 4, 5], 700))

    def test_a_roster_sample_too_far_away_refuses(self):
        self.assertFalse(self_icon.all_alive([0, 5000], [5, 5], 2500))

    def test_no_roster_refuses(self):
        self.assertFalse(self_icon.all_alive([], [], 100))


class TeardropCentreTests(unittest.TestCase):
    """The ring fit finds the icon; the portrait is cut at the teardrop's centre."""

    def _read(self, crop, det):
        from unittest.mock import patch

        import numpy as np

        seen = {}

        def pixels(crop, fit, others=()):
            seen["fit"] = dict(fit)
            return (slice(0, 1), slice(0, 1)), np.zeros((1, 1), bool)
        ctx = {"floor": np.ones(crop.shape[:2], bool), "slab": None, "static": None, "sgray": None}
        with patch("reticle.minimap.widget_drawn", return_value=True), \
                patch("reticle.minimap.self_icons", return_value=[dict(det)]), \
                patch("reticle.minimap.ally_icons", return_value=[]), \
                patch("reticle.spike.glyph_fits", return_value=[]), \
                patch("reticle.minimap.self_portrait_pixels", side_effect=pixels):
            return self_icon.read_frame(crop, ctx, {}), seen

    def test_the_portrait_is_cut_at_the_teardrop_centre(self):
        from tests.test_teardrop import _crop
        # 465 px wide: widget scale 1.0. The ring fit sits 3 px toward the lobe.
        crop = np.zeros((80, 465, 3), np.uint8)
        crop[:, :80] = _crop(40.0, 40.0, 0.0)
        row, seen = self._read(crop, {"cx": 43.0, "cy": 40.0, "r": 9, "cov": 0.9})
        self.assertEqual((row["reason"], row["origin"], row["cx"]), ("interior_too_thin", "teardrop", 43.0))
        self.assertLess(abs(row["x"] - 40.0) + abs(row["y"] - 40.0), 0.3)
        self.assertLess(abs(seen["fit"]["cx"] - 40.0), 0.2)

    def test_an_unread_teardrop_keeps_the_ring_fit_centre_and_says_why(self):
        row, seen = self._read(np.zeros((80, 465, 3), np.uint8),
                               {"cx": 43.0, "cy": 40.0, "r": 9, "cov": 0.9})
        self.assertEqual((row["x"], row["y"], row["origin"], row["origin_reason"]),
                         (43.0, 40.0, "ring_fit", "no_yellow"))
        self.assertEqual(seen["fit"]["cx"], 43.0)


class WitnessTests(unittest.TestCase):
    def test_the_witness_is_the_mean_score_over_scored_frames(self):
        got = self_icon.icon_witness([_frame({"A": 1.0, "B": 0.0}), _frame({"A": 0.5, "B": 1.0}),
                                 _frame(reason="ally_overlap")])
        self.assertEqual(got["frames"], 2)
        self.assertEqual(got["scores"], {"A": 0.75, "B": 0.5})
        self.assertEqual(got["reference_source"], "official_art")
        self.assertNotIn("margin_min", got)

    def test_the_rendered_art_is_read_where_every_frame_has_it(self):
        refs = {"margin_min": 0.6, "version": "refs-test"}
        both = [_frame({"A": 1.0, "B": 0.0}, art={"A": -1.0, "B": 1.0}),
                _frame({"A": 1.0, "B": 0.0}, art={"A": 0.0, "B": 2.0})]
        got = self_icon.icon_witness(both, refs)
        self.assertEqual(got["reference_source"], "rendered_art")
        self.assertEqual(got["scores"], {"A": -0.5, "B": 1.5})
        self.assertEqual(got["margin_min"], 0.6)
        self.assertEqual(got["composition_scores"], {"A": 1.0, "B": 0.0})

    def test_the_two_descriptors_are_never_mixed(self):
        got = self_icon.icon_witness([_frame({"A": 1.0, "B": 0.0}, art={"A": 0.0, "B": 2.0}),
                                 _frame({"A": 0.5, "B": 0.0})], {"margin_min": 0.6})
        self.assertEqual(got["reference_source"], "official_art")
        self.assertEqual(got["scores"], {"A": 0.75, "B": 0.0})

    def test_no_scored_frame_names_the_refusal_past_the_gate(self):
        got = self_icon.icon_witness([_frame(reason="not_all_alive")] * 5
                                + [_frame(reason="widget_not_drawn")] * 2)
        self.assertEqual(got["frames"], 0)
        self.assertEqual(got["reason"], "widget_not_drawn")

    def test_a_stale_stored_row_is_no_witness(self):
        self.assertIsNone(self_icon.stored_witness([{"self_icon_version": "self-icon-0.0.0",
                                                      "witness": {"frames": 3}}]))
        self.assertEqual(self_icon.stored_witness([{"self_icon_version": SELF_ICON_VERSION,
                                                     "witness": {"frames": 3}}]),
                         {"frames": 3})


class LoadLineupSelfIconTests(unittest.TestCase):
    """`load_lineup` reads the stored self icon as the lineup's witness, with no rewrite."""

    SIDES = {"ally": [{"slot": i, "agent": a, "best_guess": a}
                      for i, a in enumerate(("Sova", "Sage", "Phoenix", "Raze", "Cypher"))],
             "enemy": []}

    def store_with(self, witness=None, version=SELF_ICON_VERSION, tray="Phoenix"):
        root = Path(tempfile.mkdtemp())
        (root / "lineups").mkdir()
        (root / "lineups" / "s1.json").write_text(json.dumps(
            {"version": "lineup-0.3.0", "sides": self.SIDES,
             "tray": {"agent": tray, "votes": 10, "total": 12, "frames_offered": 20}}),
            encoding="utf-8")
        if witness is not None:
            d = root / "events" / "self_icon"
            d.mkdir(parents=True)
            (d / "s1.jsonl").write_text(json.dumps(
                {"kind": "coverage", "self_icon_version": version, "witness": witness})
                + "\n" + json.dumps({"kind": "frame", "self_icon_version": version}) + "\n",
                encoding="utf-8")
        return root

    SCORES = {"Sova": 1.1, "Sage": 0.6, "Phoenix": 1.4, "Raze": 1.0, "Cypher": 0.5}

    def test_the_stored_self_icon_joins_the_tray(self):
        got = lineup.load_lineup("s1", self.store_with({"frames": 40, "scores": self.SCORES}))
        self.assertEqual(got["self_icon_state"]["source"], "self_icon_rows")
        claim = next(c for c in got["identity_claims"] if c["channel"] == "self_icon")
        self.assertEqual(claim["agent"], "Phoenix")
        self.assertEqual(got["player"]["agent"], "Phoenix")

    def test_a_disagreeing_self_icon_is_a_disagreement(self):
        got = lineup.load_lineup("s1", self.store_with({"frames": 40, "scores": self.SCORES},
                                                       tray="Sova"))
        self.assertIsNone(got["player"]["agent"])

    def test_a_stale_row_is_ignored_and_said_so(self):
        got = lineup.load_lineup("s1", self.store_with({"frames": 40, "scores": self.SCORES},
                                                       version="self-icon-0.0.0"))
        self.assertIsNone(got["self_icon_state"]["source"])
        self.assertTrue(got["self_icon_state"]["reason"].startswith("stale_version"))
        claim = next(c for c in got["identity_claims"] if c["channel"] == "self_icon")
        self.assertIsNone(claim["agent"])

    def test_the_witness_gate_is_its_own_margin(self):
        art = {"Sova": 1.0, "Sage": 0.0, "Phoenix": 1.5, "Raze": 0.2, "Cypher": 0.0}
        got = lineup.load_lineup("s1", self.store_with(
            {"frames": 40, "scores": art, "margin_min": 0.62,
             "reference_source": "rendered_art"}))
        claim = next(c for c in got["identity_claims"] if c["channel"] == "self_icon")
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "margin 0.500 below 0.62 among the ally candidates")
        self.assertEqual(claim["evidence"]["reference_source"], "rendered_art")

    def test_an_unread_icon_carries_its_refusal(self):
        got = lineup.load_lineup("s1", self.store_with(
            {"frames": 0, "scores": {}, "reason": "widget_not_drawn"}))
        claim = next(c for c in got["identity_claims"] if c["channel"] == "self_icon")
        self.assertEqual(claim["reason"], "no_self_icon_frames: widget_not_drawn")
        self.assertEqual(got["player"]["agent"], "Phoenix")


if __name__ == "__main__":
    unittest.main()
