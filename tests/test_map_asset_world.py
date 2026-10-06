"""map_asset's world: UIData constants, the per-map world offset, the site letters."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

from reticle import map_asset as A
from reticle.store import DEFAULT_STORE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototypes"))

HAVE_SITES = (A.site_set(DEFAULT_STORE) / "manifest.jsonl").is_file()


class WorldOffset(unittest.TestCase):
    def test_unfitted_map_is_zero(self):
        self.assertEqual(A.world_offset("no-such-map").tolist(), [0.0, 0.0])

    def test_frozen_offsets_name_their_fit(self):
        got = json.loads(A.WORLD_FILE.read_text(encoding="utf-8"))
        fitted = {m for m, _p, _n in got["fit_on"].values()}
        self.assertEqual(set(got["offsets"]), fitted)
        for off in got["offsets"].values():
            self.assertLess(np.hypot(*off), 4.0)

    def test_fit_world_leaves_a_match_out(self):
        import minimap_geometry as MG
        res = {"a": {"map": "m", "tex": np.array([[1.0, 0.0], [3.0, 0.0]])},
               "b": {"map": "m", "tex": np.array([[0.0, 2.0]])}}
        self.assertEqual(MG.fit_world(res)["m"], [round(4 / 3, 4), round(2 / 3, 4)])
        self.assertEqual(MG.fit_world(res, exclude={"a"})["m"], [0.0, 2.0])
        self.assertNotIn("m", MG.fit_world(res, exclude={"a", "b"}))


@unittest.skipUnless(HAVE_SITES, "the store's exported minimap-sites set is absent")
class Sites(unittest.TestCase):
    def test_lotus_has_three_sites_from_its_level(self):
        s = A.sites("lotus")
        self.assertEqual(sorted(s), ["A", "B", "C"])
        self.assertTrue(all("/Maps/Jam/" in v[2] for v in s.values()))

    def test_uidata_matches_valorant_api_scale(self):
        c = A.uidata_constants("lotus")
        self.assertAlmostEqual(abs(c["x_mult"]), 7.2e-05, places=9)

    def test_letters_darken_at_most_half(self):
        P = A.transform("valorant-16x9-bigmap")
        M = A.map_affine(A.rotation("lotus"), P["scale"], P["centre"])
        cov = A.letter_cover("lotus", M, P["shape"])
        self.assertLessEqual(float(cov.max()), A.LETTER_OPACITY + 1e-6)
        self.assertGreater(float(cov.max()), 0.4)
        x, y, _ = A.sites("lotus")["A"]
        cx, cy = M @ np.array([*map(float, A.world_to_texture("lotus", x, y)), 1.0])
        ys, xs = np.nonzero(cov > 0.1)
        near = np.hypot(xs - cx, ys - cy) < 15
        self.assertGreater(int(near.sum()), 20)


if __name__ == "__main__":
    unittest.main()
