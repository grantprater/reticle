"""The killfeed portrait's art ZNCC: the descriptor, the reader's search, and the claim."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import appearance, killfeed
from reticle.adjudication.identity import (PORTRAIT_LIKELIHOOD, PORTRAIT_NONE,
                                           claim_from_killfeed_portrait)
from reticle.killfeed import UNIT_SCALE, art_view
from reticle.store import DEFAULT_STORE

TH = killfeed.ART_TILE_H
TW = int(round(killfeed.PORTRAIT_ASPECT * TH))
STORE_ART = DEFAULT_STORE / "reference" / "assets" / "agents"


def _texture(seed: int, h: int = 128, w: int = 256) -> np.ndarray:
    """Smooth random colour at the art's size, an alpha that hides the corners."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (h // 8, w // 8, 3)).astype(np.uint8)
    col = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    alpha = np.full((h, w), 255, np.uint8)
    alpha[:12, :20] = 0
    alpha[-12:, -20:] = 0
    return np.dstack([col, alpha])


def _art_dir(names, tmp: Path) -> Path:
    for i, name in enumerate(names):
        cv2.imwrite(str(tmp / f"{name}_killfeed_portrait.png"), _texture(i + 1))
    return tmp


def _tile(art_dir: Path, name: str, mirrored=False) -> np.ndarray:
    """The art as the killfeed draws it: shrunk to one band (INTER_AREA), over
    a dark plate where transparent."""
    im = cv2.imread(str(art_dir / f"{name}_killfeed_portrait.png"), cv2.IMREAD_UNCHANGED)
    im = cv2.resize(im, (TW, TH), interpolation=cv2.INTER_AREA).astype(np.float32)
    a = im[:, :, 3:4] / 255.0
    out = (im[:, :, :3] * a + 40 * (1 - a)).astype(np.uint8)
    return out[:, ::-1].copy() if mirrored else out


def _brute(region_lab, lab, weight):
    """The weighted ZNCC written out window by window."""
    h, w = weight.shape
    out = np.zeros((region_lab.shape[0] - h + 1, region_lab.shape[1] - w + 1))
    wn = weight / weight.sum()
    for y in range(out.shape[0]):
        for x in range(out.shape[1]):
            X = region_lab[y:y + h, x:x + w]
            xc = X - (wn[:, :, None] * X).sum((0, 1))
            rc = lab - (wn[:, :, None] * lab).sum((0, 1))
            num = (wn[:, :, None] * xc * rc).sum()
            out[y, x] = num / np.sqrt((wn[:, :, None] * xc * xc).sum()
                                      * (wn[:, :, None] * rc * rc).sum())
    return out


class ArtZnccTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = _art_dir(["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"],
                            Path(self.tmp.name))
        appearance._ART_CACHE.clear()
        self.art = appearance.killfeed_art(self.dir, TH, TW)

    def tearDown(self):
        self.tmp.cleanup()
        appearance._ART_CACHE.clear()

    def test_the_vectorised_correlation_is_the_weighted_zncc(self):
        rng = np.random.default_rng(7)
        region = appearance.to_lab(rng.integers(0, 256, (TH + 2, TW + 4, 3)).astype(np.uint8))
        z = appearance.art_zncc(region, self.art, ["Bravo"])
        i = self.art.index["Bravo"]
        lab = np.ascontiguousarray(self._lab(i))
        weight = self._weight(i)
        np.testing.assert_allclose(z[:, :, 0], _brute(region, lab, weight), atol=2e-4)

    def _lab(self, i):
        t = self.art.terms[False]
        # rebuild the art's Lab from the cache's own inputs
        im = cv2.imread(str(self.dir / f"{self.art.agents[i]}_killfeed_portrait.png"),
                        cv2.IMREAD_UNCHANGED).astype(np.float32) / 255.0
        a = im[:, :, 3:4]
        pm = cv2.resize(im[:, :, :3] * a, (TW, TH), interpolation=cv2.INTER_AREA)
        al = cv2.resize(a[:, :, 0], (TW, TH), interpolation=cv2.INTER_AREA)
        col = np.clip(pm / np.maximum(al, 1e-3)[:, :, None], 0, 1).astype(np.float32)
        self.assertEqual(t["wn"].shape[0], TH * TW)
        return cv2.cvtColor(col, cv2.COLOR_BGR2Lab)

    def _weight(self, i):
        im = cv2.imread(str(self.dir / f"{self.art.agents[i]}_killfeed_portrait.png"),
                        cv2.IMREAD_UNCHANGED).astype(np.float32) / 255.0
        w = cv2.resize(im[:, :, 3], (TW, TH), interpolation=cv2.INTER_AREA)
        m = appearance.ART_INNER_MARGIN
        w[:m] = 0
        w[TH - m:] = 0
        w[:, :m] = 0
        w[:, TW - m:] = 0
        return w

    def test_the_inner_weights_ignore_a_frame_over_the_border(self):
        # The player's own portrait carries a yellow frame over the art's outer
        # rows [domain:killfeed/self-yellow-frame].
        tile = _tile(self.dir, "Charlie")
        framed = tile.copy()
        cv2.rectangle(framed, (0, 0), (TW - 1, TH - 1), (0, 220, 255), 2)
        inner = appearance.art_zncc(appearance.to_lab(framed), self.art, ["Charlie"])[0, 0, 0]
        full = appearance.ArtTiles(self.art.agents, *self._stack(), margin=0)
        whole = appearance.art_zncc(appearance.to_lab(framed), full, ["Charlie"])[0, 0, 0]
        self.assertGreater(inner, 0.95)
        self.assertGreater(inner, whole + 0.05)

    def _stack(self):
        labs = np.stack([self._lab(i) for i in range(len(self.art.agents))])
        alphas = []
        for name in self.art.agents:
            im = cv2.imread(str(self.dir / f"{name}_killfeed_portrait.png"),
                            cv2.IMREAD_UNCHANGED).astype(np.float32) / 255.0
            alphas.append(cv2.resize(im[:, :, 3], (TW, TH), interpolation=cv2.INTER_AREA))
        return labs, np.stack(alphas)

    def _crop(self, killer=None, killer_x0=60, victim=None, victim_mirrored=True, h=50, w=420,
              y0=8):
        crop = np.full((h, w, 3), 40, np.uint8)
        if killer:
            crop[y0:y0 + TH, killer_x0:killer_x0 + TW] = _tile(self.dir, killer)
        if victim:
            x1 = w - killfeed.ART_VICTIM_OUTER + 1
            crop[y0:y0 + TH, x1 - TW:x1] = _tile(self.dir, victim, mirrored=victim_mirrored)
        return crop

    def test_a_victim_is_the_mirrored_art_at_the_right_aligned_anchor(self):
        crop = self._crop(victim="Delta")
        got = art_view(crop, "victim", None, 8, False, UNIT_SCALE, self.dir)
        top = max(got["art_zncc"], key=got["art_zncc"].get)
        self.assertEqual(top, "Delta")
        self.assertEqual(got["art_shift"], [0, 0])
        self.assertEqual((got["art_anchor"], got["art_mirrored"], got["art_search"]),
                         ("right_edge", True, "prior"))
        self.assertGreater(got["art_zncc"]["Delta"], 0.95)
        # drawn unmirrored, the same art no longer matches its mirror image
        flat = art_view(self._crop(victim="Delta", victim_mirrored=False), "victim", None, 8,
                        False, UNIT_SCALE, self.dir)
        self.assertLess(flat["art_zncc"].get("Delta", 0.0), 0.8)

    def test_a_killer_continues_its_box_and_widens_on_surprise(self):
        crop = self._crop(killer="Echo", killer_x0=60)
        prior = art_view(crop, "killer", 60, 8, True, UNIT_SCALE, self.dir)
        self.assertEqual((prior["art_search"], prior["art_shift"]), ("prior", [0, 0]))
        self.assertEqual(max(prior["art_zncc"], key=prior["art_zncc"].get), "Echo")
        # the box says 72; the portrait starts at 60: the prior misses, the strip finds it
        moved = art_view(crop, "killer", 72, 8, True, UNIT_SCALE, self.dir)
        self.assertEqual(moved["art_search"], "widened")
        self.assertEqual(moved["art_shift"], [-12, 0])
        self.assertEqual(max(moved["art_zncc"], key=moved["art_zncc"].get), "Echo")

    def test_a_sliding_victim_widens_its_rows_not_its_anchor(self):
        # the entry still slides into its slot: the band reads 5 rows above the art
        crop = self._crop(victim="Delta", y0=13, h=60)
        got = art_view(crop, "victim", None, 8, False, UNIT_SCALE, self.dir)
        self.assertEqual((got["art_search"], got["art_shift"]), ("widened", [0, 5]))
        self.assertEqual(max(got["art_zncc"], key=got["art_zncc"].get), "Delta")

    def test_candidates_come_from_the_side_and_widen_to_all_on_surprise(self):
        crop = self._crop(killer="Foxtrot", killer_x0=60)
        side = {"ally": ["Alpha", "Bravo"], "enemy": ["Foxtrot", "Charlie"]}
        got = art_view(crop, "killer", 60, 8, False, UNIT_SCALE, self.dir, side)
        self.assertEqual(sorted(got["art_zncc"]), ["Charlie", "Foxtrot"])
        self.assertEqual((got["art_candidates"], got["art_candidates_widened"]), ("side", None))
        # the plate says ally, whose candidates do not hold Foxtrot: every agent is scored
        wrong = art_view(crop, "killer", 60, 8, True, UNIT_SCALE, self.dir, side)
        self.assertTrue(wrong["art_candidates_widened"])
        self.assertEqual(len(wrong["art_zncc"]), len(self.art.agents))
        self.assertEqual(max(wrong["art_zncc"], key=wrong["art_zncc"].get), "Foxtrot")
        # no lineup: every agent, and the reason says so
        none = art_view(crop, "killer", 60, 8, None, UNIT_SCALE, self.dir, None)
        self.assertEqual(none["art_candidates"], "all: no lineup given")

    def test_a_killer_cut_by_the_roi_edge_scores_the_columns_inside(self):
        # a long name pushes the portrait 20 px past the ROI's left edge
        cut = 20
        crop = np.full((50, 420, 3), 40, np.uint8)
        crop[8:8 + TH, 0:TW - cut] = _tile(self.dir, "Bravo")[:, cut:]
        got = art_view(crop, "killer", -cut, 8, True, UNIT_SCALE, self.dir)
        self.assertEqual(got["art_search"], "prior")
        self.assertEqual(max(got["art_zncc"], key=got["art_zncc"].get), "Bravo")
        self.assertGreater(got["art_zncc"]["Bravo"], 0.95)
        self.assertEqual((got["art_x0"], got["art_shift"]), (-cut, [0, 0]))
        self.assertLess(got["art_cover"], 1.0)
        # the cut window matches the brute-force correlation over the columns inside
        region = appearance.to_lab(crop[8:8 + TH, 0:TW - cut])
        z = appearance.art_zncc(region, self.art, ["Bravo"], cut=cut)
        i = self.art.index["Bravo"]
        np.testing.assert_allclose(
            z[:, :, 0], _brute(region, np.ascontiguousarray(self._lab(i)[:, cut:]),
                               self._weight(i)[:, cut:]), atol=2e-4)
        # under ART_MIN_COVER of the art inside, the window is no evidence
        far = appearance.art_zncc(region[:, :8], self.art, ["Bravo"], cut=TW - 8)
        self.assertEqual(float(far.max()), 0.0)

    def test_the_plate_left_end_is_found_to_a_subpixel_past_the_assist_panel(self):
        # a teal plate from x = 50.5 (its first column half covered), over grey
        # scene, with an assist panel's teal cell over the top 18 rows left of it
        h, w = 34, 200
        crop = np.full((h, w, 3), (90, 90, 90), np.float32)
        teal = np.array((160, 190, 60), np.float32)        # BGR, hue inside GREEN_H
        crop[:, 51:] = teal
        crop[:, 50] = 0.5 * teal + 0.5 * crop[:, 49]
        crop[:18, 10:44] = teal
        crop = crop.astype(np.uint8)
        got = killfeed.plate_left_edge(crop, 150, UNIT_SCALE)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got[0], 50.5, delta=0.3)

    def test_a_killer_starts_at_its_plate_and_falls_back_to_its_box(self):
        crop = self._crop(killer="Echo", killer_x0=60)
        got = art_view(crop, "killer", 72, 8, True, UNIT_SCALE, self.dir, plate_x0=60.2)
        self.assertEqual((got["art_search"], got["art_anchor"], got["art_shift"]),
                         ("prior", "plate_left", [0, 0]))
        # a misplaced edge surprises; the name-start box holds
        box = art_view(crop, "killer", 60, 8, True, UNIT_SCALE, self.dir, plate_x0=120)
        self.assertEqual((box["art_search"], box["art_anchor"]), ("prior", "killer_box"))
        # no box: the plate alone places it
        alone = art_view(crop, "killer", None, 8, True, UNIT_SCALE, self.dir, plate_x0=60)
        self.assertEqual(max(alone["art_zncc"], key=alone["art_zncc"].get), "Echo")

    def test_a_killer_without_a_box_refuses_with_its_reason(self):
        got = art_view(self._crop(), "killer", None, 8, True, UNIT_SCALE, self.dir)
        self.assertIsNone(got["art_zncc"])
        self.assertEqual(got["art_reason"], "no_killer_box")


class ArtClaimTests(unittest.TestCase):
    def _claim(self, scores, candidates=("A", "B", "C", "D", "E"), rivals=()):
        obs = {"role": "killer", "slot": 0, "ally": False, "reason": "", "t_ms": 1.0,
               "art_zncc": scores, "composition": [0.0] * 90}
        return claim_from_killfeed_portrait(obs, entity_id="e", candidates=list(candidates),
                                            rivals=list(rivals), gallery={})

    def test_a_clear_match_names_from_the_art(self):
        c = self._claim({"A": 0.88, "B": 0.15, "C": 0.12, "D": 0.2, "E": 0.1})
        self.assertEqual(c["agent"], "A")
        self.assertEqual(c["evidence"]["likelihood_source"], "art_zncc")

    def test_none_of_them_takes_a_view_that_matches_no_candidate(self):
        c = self._claim({"A": 0.3, "B": 0.15, "C": 0.12, "D": 0.2, "E": 0.1})
        self.assertIsNone(c["agent"])
        self.assertTrue(c["reason"].startswith("portrait_none_of_them"), c["reason"])
        self.assertIn(PORTRAIT_NONE, c["evidence"]["posterior"])

    def test_two_close_candidates_refuse_on_the_posterior(self):
        c = self._claim({"A": 0.85, "B": 0.84, "C": 0.12, "D": 0.2, "E": 0.1})
        self.assertIsNone(c["agent"])
        self.assertTrue(c["reason"].startswith("portrait_posterior"), c["reason"])

    def test_an_unscored_candidate_refuses_rather_than_scoring_zero(self):
        c = self._claim({"A": 0.88, "B": 0.15})
        self.assertIsNone(c["agent"])
        self.assertTrue(c["reason"].startswith("portrait_candidate_unscored"), c["reason"])

    def test_a_refused_slot_stays_barred(self):
        c = self._claim({"A": 0.15, "B": 0.1, "R": 0.9}, candidates=("A", "B"), rivals=("R",))
        self.assertIsNone(c["agent"])
        self.assertTrue(c["reason"].startswith("portrait_best_is_refused_slot"))

    def test_a_refused_art_search_is_quoted(self):
        c = self._claim(None)
        self.assertIsNone(c["agent"])
        self.assertTrue(c["reason"].startswith("portrait_art_refused"))

    def test_the_table_is_ordered(self):
        t = PORTRAIT_LIKELIHOOD["art_zncc"]
        self.assertGreater(t["same"], t["diff"])


@unittest.skipUnless(STORE_ART.is_dir(), "no agent art in the store")
class ConfusedPairsTests(unittest.TestCase):
    """The pairs the composition confused (Fade/Iso, Clove/Reyna,
    Brimstone/Breach), drawn from the store's own art over a plate with
    noise, as killer and as mirrored victim."""

    PAIRS = (("Fade", "Iso"), ("Clove", "Reyna"), ("Brimstone", "Breach"))

    def test_the_art_separates_each_confused_pair(self):
        rng = np.random.default_rng(3)
        for a, b in self.PAIRS:
            for name, other in ((a, b), (b, a)):
                for role in ("killer", "victim"):
                    crop = np.full((50, 420, 3), (60, 140, 40), np.uint8)
                    tile = _tile(STORE_ART, name, mirrored=role == "victim")
                    x0 = 60 if role == "killer" else 420 - killfeed.ART_VICTIM_OUTER + 1 - TW
                    crop[8:8 + TH, x0:x0 + TW] = tile
                    noisy = np.clip(crop.astype(np.int16) + rng.integers(-12, 13, crop.shape),
                                    0, 255).astype(np.uint8)
                    got = art_view(noisy, role, 60 if role == "killer" else None, 8, True,
                                   UNIT_SCALE, STORE_ART, {"ally": [a, b], "enemy": []})
                    z = got["art_zncc"]
                    self.assertGreater(z[name] - z[other], 0.3, (name, other, role, z))


if __name__ == "__main__":
    unittest.main()
