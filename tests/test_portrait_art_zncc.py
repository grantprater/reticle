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
        self.assertAlmostEqual(got["art_visible"], (TW - cut) / TW, places=3)

    def test_a_cut_killer_keeps_its_column_and_refuses_under_the_visible_minimum(self):
        vmin = killfeed.ART_MIN_VISIBLE
        crop = np.full((60, 420, 3), 40, np.uint8)
        # the art 4 rows below the band, cut to vmin + 2 columns
        cut = TW - (vmin + 2)
        crop[12:12 + TH, 0:TW - cut] = _tile(self.dir, "Bravo")[:, cut:]
        got = art_view(crop, "killer", -cut, 8, True, UNIT_SCALE, self.dir)
        self.assertEqual(max(got["art_zncc"], key=got["art_zncc"].get), "Bravo")
        self.assertEqual((got["art_search"], got["art_x0"], got["art_shift"]),
                         ("widened", -cut, [0, 4]))
        # a surprise at a cut placement widens rows only, never the column: a
        # placement 6 px off finds nothing it could have found by moving
        off = art_view(crop, "killer", -cut + 6, 8, True, UNIT_SCALE, self.dir)
        self.assertLessEqual(abs(off["art_shift"][0]), killfeed.ART_PRIOR_X)
        # under the minimum the view refuses and stores the placement
        tiny = TW - (vmin - 1)
        refused = art_view(crop, "killer", -tiny, 8, True, UNIT_SCALE, self.dir)
        self.assertIsNone(refused["art_zncc"])
        self.assertEqual((refused["art_reason"], refused["art_x0"]), ("art_cut_by_roi", -tiny))
        self.assertAlmostEqual(refused["art_visible"], (vmin - 1) / TW, places=3)
        # a visible prior beside a cut one is still searched
        both = art_view(self._crop(killer="Echo", killer_x0=60), "killer", -tiny, 8, True,
                        UNIT_SCALE, self.dir, plate_x0=60)
        self.assertEqual((both["art_anchor"], both["art_search"]), ("plate_left", "prior"))

    def test_every_candidate_is_scored_on_the_same_cut_columns(self):
        # no per-candidate cover gate: a narrow cut scores every agent
        region = appearance.to_lab(np.full((TH, 10, 3), 90, np.uint8)
                                   + np.arange(10, dtype=np.uint8)[None, :, None] * 9)
        z = appearance.art_zncc(region, self.art, list(self.art.agents), cut=TW - 10)
        self.assertEqual(z.shape, (1, 1, len(self.art.agents)))
        self.assertTrue(np.all(z != 0.0))

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

    def test_an_entry_anchor_holds_and_a_surprise_there_widens_rows_only(self):
        crop = self._crop(killer="Echo", killer_x0=60, y0=12, h=60)
        # the anchor holds the column; the band reads 4 rows above the art
        got = art_view(crop, "killer", 80, 8, True, UNIT_SCALE, self.dir, entry_x0=60.3)
        self.assertEqual((got["art_search"], got["art_anchor"], got["art_shift"]),
                         ("widened", "entry_anchor", [0, 4]))
        self.assertEqual(max(got["art_zncc"], key=got["art_zncc"].get), "Echo")
        # without it the name-start box at 80 widens the strip instead
        strip = art_view(crop, "killer", 80, 8, True, UNIT_SCALE, self.dir)
        self.assertEqual((strip["art_anchor"], strip["art_shift"]), ("killer_box", [-20, 4]))
        # a misplaced anchor falls through to the view's own plate edge
        own = art_view(self._crop(killer="Echo", killer_x0=60), "killer", 90, 8, True,
                       UNIT_SCALE, self.dir, plate_x0=60, entry_x0=120)
        self.assertEqual((own["art_search"], own["art_anchor"]), ("prior", "plate_left"))

    def test_a_killer_without_a_box_refuses_with_its_reason(self):
        got = art_view(self._crop(), "killer", None, 8, True, UNIT_SCALE, self.dir)
        self.assertIsNone(got["art_zncc"])
        self.assertEqual(got["art_reason"], "no_killer_box")


class EntryAnchorTests(unittest.TestCase):
    """The follow and the anchor of `killfeed.EntryAnchors`."""

    def _view(self, slot, y0, wx0=200, v0=300):
        return killfeed.EntryView(slot=slot, y0=y0, y1=y0 + 34, wx0=wx0, wx1=wx0 + 30,
                                  killer_run=(120, 190), victim_run=(v0, 400))

    @staticmethod
    def _fields(x0, z=0.9, anchor="plate_left", search="prior"):
        return {"art_zncc": {"A": z}, "art_anchor": anchor, "art_search": search,
                "art_x0": x0, "art_candidates_widened": None}

    def test_an_entry_is_followed_as_it_rises_and_a_new_layout_is_a_new_entry(self):
        a = killfeed.EntryAnchors()
        a.frame(0.0)
        first = a.entry(self._view(1, 54), UNIT_SCALE)
        a.frame(500.0)
        risen = a.entry(self._view(0, 15, wx0=201), UNIT_SCALE)
        other = a.entry(self._view(1, 54, v0=330), UNIT_SCALE)
        self.assertIs(first, risen)
        self.assertIsNot(other, first)
        # an entry never falls: the same layout lower down is another entry
        a.frame(1000.0)
        self.assertIsNot(a.entry(self._view(2, 93), UNIT_SCALE), first)
        # unseen past ENTRY_FOLLOW_GAP_MS, it is gone
        a.frame(1000.0 + killfeed.ENTRY_FOLLOW_GAP_MS + 1)
        self.assertIsNot(a.entry(self._view(0, 15), UNIT_SCALE), first)

    def test_the_anchor_is_the_median_of_the_most_confident_confirmed_edges(self):
        a = killfeed.EntryAnchors()
        a.frame(0.0)
        e = a.entry(self._view(0, 15), UNIT_SCALE)
        self.assertIsNone(killfeed.EntryAnchors.anchor(e))
        # an edge the art did not confirm is not taken
        killfeed.EntryAnchors.confirm(e, self._fields(57, z=0.3), (57.4, 30.0))
        self.assertIsNone(killfeed.EntryAnchors.anchor(e))
        for edge, score in ((56.2, 9.0), (56.4, 12.0), (68.0, 4.5), (56.3, 10.0)):
            killfeed.EntryAnchors.confirm(e, self._fields(int(edge)), (edge, score))
        got = killfeed.EntryAnchors.anchor(e)
        self.assertEqual((got["source"], got["views"]), ("plate_left", killfeed.ANCHOR_VIEWS))
        self.assertAlmostEqual(got["x"], 56.3)

    def test_an_art_only_placement_needs_a_second_view(self):
        a = killfeed.EntryAnchors()
        a.frame(0.0)
        e = a.entry(self._view(0, 15), UNIT_SCALE)
        killfeed.EntryAnchors.confirm(e, self._fields(56, anchor="killer_box", search="widened"),
                                      None)
        self.assertIsNone(killfeed.EntryAnchors.anchor(e))
        killfeed.EntryAnchors.confirm(e, self._fields(57, anchor="killer_box", search="widened"),
                                      None)
        got = killfeed.EntryAnchors.anchor(e)
        self.assertEqual(got["source"], "art")
        self.assertAlmostEqual(got["x"], 56.5)
        # an all-agent result is the art alone even on the prior window: one
        # view places nothing, two that agree do
        f = a.entry(self._view(1, 54, v0=340), UNIT_SCALE)
        widened = dict(self._fields(56, anchor="killer_box"), art_candidates_widened="top 0.4")
        killfeed.EntryAnchors.confirm(f, widened, (56.2, 20.0))
        self.assertIsNone(killfeed.EntryAnchors.anchor(f))
        killfeed.EntryAnchors.confirm(f, widened, None)
        self.assertEqual(killfeed.EntryAnchors.anchor(f)["source"], "art")


    def test_a_cut_entry_is_seeded_from_its_name_start_until_a_confirmed_anchor(self):
        a = killfeed.EntryAnchors()
        a.frame(0.0)
        e = a.entry(self._view(0, 15), UNIT_SCALE)
        # a whole placement seeds nothing: the strip may still find the art
        killfeed.EntryAnchors.seed(e, 12.0, UNIT_SCALE)
        self.assertIsNone(killfeed.EntryAnchors.anchor(e))
        killfeed.EntryAnchors.seed(e, -20.4, UNIT_SCALE)
        killfeed.EntryAnchors.seed(e, -25.0, UNIT_SCALE)      # the first seed holds
        got = killfeed.EntryAnchors.anchor(e)
        self.assertEqual((got["source"], got["views"]), ("name_start", 1))
        self.assertAlmostEqual(got["x"], -20.4)
        # two art views that agree take over from the seed
        for x in (-21, -21):
            killfeed.EntryAnchors.confirm(e, self._fields(x, anchor="entry_anchor"), None)
        self.assertEqual(killfeed.EntryAnchors.anchor(e)["source"], "art")


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
