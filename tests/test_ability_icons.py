"""The dark-icon proposer, its verify, and the `ability_icon` reader's rows."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from reticle import ability_icons as I
from reticle.version import ABILITY_ICON_VERSION


def _slab_img(n=465):
    rng = np.random.default_rng(1)
    img = np.full((n, n, 3), 150, np.uint8)
    noise = rng.integers(0, 40, (n, n, 1), dtype=np.uint8)
    img = cv2.add(img, np.repeat(noise, 3, axis=2))
    slab = np.zeros((n, n), np.uint8)
    slab[60:n - 60, 60:n - 60] = 1
    return img, slab


class ProposerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The tests copy `base` before drawing and only read the terms.
        cls.base, cls.slab = _slab_img()
        cls.terms = I.IconTerms(cls.slab, I.SET_AT)

    def test_finds_a_dark_disc_and_nothing_on_a_blank_slab(self):
        self.assertEqual(I.propose_icons(self.base, self.terms), [])
        img = self.base.copy()
        cv2.circle(img, (200, 240), 9, (20, 20, 20), -1)
        c = I.propose_icons(img, self.terms)
        self.assertEqual(len(c), 1)
        self.assertLessEqual(np.hypot(c[0]["cx"] - 200, c[0]["cy"] - 240), 1)
        self.assertLessEqual(abs(c[0]["r"] - 9), 1.5)

    def test_off_slab_darkness_is_not_a_candidate(self):
        img = self.base.copy()
        cv2.circle(img, (25, 25), 9, (20, 20, 20), -1)
        self.assertEqual(I.propose_icons(img, self.terms), [])

    def test_verify_follows_a_moved_icon_and_loses_a_gone_one(self):
        img = self.base.copy()
        cv2.circle(img, (200, 240), 9, (20, 20, 20), -1)
        c = I.propose_icons(img, self.terms)
        moved = self.base.copy()
        cv2.circle(moved, (201, 241), 9, (20, 20, 20), -1)
        v = I.verify_icons(moved, self.terms, c)
        self.assertIsNotNone(v[0]["score"])
        self.assertEqual((v[0]["cx"], v[0]["cy"]), (201, 241))
        self.assertIsNone(I.verify_icons(self.base, self.terms, c)[0]["score"])


class ReaderTest(unittest.TestCase):
    def test_rows_reasons_verify_and_stamp(self):
        base, slab = _slab_img()
        floor = slab.astype(bool)
        sgray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        phase = {0.0: "round_live", 500.0: "round_live", 1000.0: "buy"}
        rd = I.AbilityIconReader(slab=slab, floor=floor, sgray=sgray, box=(0, 0, 465, 465),
                                 phase_at=phase.get)
        img = base.copy()
        cv2.circle(img, (200, 240), 9, (20, 20, 20), -1)
        for t, i in ((0.0, img), (500.0, img), (1000.0, img)):
            rd.feed(SimpleNamespace(frame=i, t_ms=t, frame_idx=int(t / 1000 * 60)))
        ev = rd.events("s", "k")
        head, rows = ev[0], ev[1:]
        self.assertEqual(head["ability_icon_version"], ABILITY_ICON_VERSION)
        self.assertEqual(head["by_reason"], {"read": 2, "not_live": 1})
        self.assertIsNone(rows[0]["verify"])
        self.assertEqual(rows[1]["verify"]["of_t_ms"], 0.0)
        self.assertIsNotNone(rows[1]["verify"]["rows"][0]["score"])
        self.assertEqual(rows[2]["reason"], "not_live")
        self.assertEqual(head["verify_lost"], 0)


# --- the disabled drawing: game-file renders (icon-proposer-0.4.0)

from pathlib import Path  # noqa: E402

from reticle.store import DEFAULT_STORE  # noqa: E402

GAME_FILES = Path(DEFAULT_STORE) / "reference/game-files/release-13.06-shipping-18-5590001"
SENSOR_TEX = GAME_FILES / ("minimap/ShooterGame/Content/UI/Shared/Icons/Abilities/Minimap/"
                           "TX_UI_Minimap_Deadlock_Q_InActive.png")
SENSOR_GD = GAME_FILES / "game-data/ShooterGame/Content/Abilities/GameObject_StealthingTrap_Base.json"


def _sensor(diameter: int):
    """Deadlock's Sonic Sensor minimap texture, premultiplied and shrunk
    with INTER_AREA to `diameter` px, and its alpha."""
    tex = cv2.imread(str(SENSOR_TEX), cv2.IMREAD_UNCHANGED).astype(np.float32) / 255.0
    pm = cv2.resize(tex[..., :3] * tex[..., 3:], (diameter, diameter), interpolation=cv2.INTER_AREA)
    a = cv2.resize(tex[..., 3], (diameter, diameter), interpolation=cv2.INTER_AREA)[..., None]
    return pm, a


def _render(base, pm, a, opacity, cx, cy, rng, off=8.0, sd=3.0):
    """The texture composited over `base` at `opacity`, plus a lighting offset
    and noise (grey levels), as the widget would draw it."""
    img = base.astype(np.float32) / 255.0
    d = pm.shape[0]
    y0, x0 = cy - d // 2, cx - d // 2
    if opacity > 0:
        roi = img[y0:y0 + d, x0:x0 + d]
        img[y0:y0 + d, x0:x0 + d] = opacity * pm + (1 - opacity * a) * roi
    out = img * 255.0 + off + rng.normal(0, sd, img.shape)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


@unittest.skipUnless(SENSOR_TEX.is_file() and SENSOR_GD.is_file(), "game files not extracted")
class DisabledDrawingTest(unittest.TestCase):
    """The game files' disabled opacity, read from the file, over the test
    slab: the live verify loses the dim drawing, the disabled path holds it,
    and the glyph's own pixels stay correlated."""

    @classmethod
    def setUpClass(cls):
        import json
        gd = json.loads(SENSOR_GD.read_text(encoding="utf-8"))
        cls.opacity = next(float(o["Properties"]["DisabledMinimapIconOpacity"]) for o in gd
                           if "DisabledMinimapIconOpacity" in (o.get("Properties") or {}))
        cls.base, cls.slab = _slab_img()
        cls.terms = I.IconTerms(cls.slab, I.SET_AT)
        cls.sgray = cv2.cvtColor(cls.base, cv2.COLOR_BGR2GRAY).astype(np.float64)
        cls.pm, cls.a = _sensor(19)

    def test_the_reader_opacity_is_the_game_files(self):
        self.assertEqual(I.DISABLED_OPACITY, self.opacity)
        self.assertEqual(I.DIM_HYPOTHESES, (1.0, self.opacity, 0.0))

    def test_the_disabled_variant_matches_a_game_file_render(self):
        rng = np.random.default_rng(3)
        for cx, cy in ((200, 240), (300, 150), (150, 330)):
            live = _render(self.base, self.pm, self.a, 1.0, cx, cy, rng)
            (c,) = [x for x in I.propose_icons(live, self.terms) if np.hypot(x["cx"] - cx, x["cy"] - cy) < 4]
            ref = I.live_ref(cv2.cvtColor(live, cv2.COLOR_BGR2GRAY).astype(np.float32), self.sgray,
                             c["cx"], c["cy"], c["r"], self.terms)
            got = {}
            for o in (1.0, self.opacity, 0.0):
                im = _render(self.base, self.pm, self.a, o, cx, cy, rng)
                v = I.verify_icons(im, self.terms, [c])[0]
                g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
                d = I.verify_disabled(g, self.sgray, ref, c["cx"], c["cy"], self.terms.verify_half)
                got[o] = (v["score"], d)
            # live: the verify holds it and the disabled path says no
            self.assertIsNotNone(got[1.0][0])
            self.assertLess(got[1.0][1]["disabled_dim"], I.DISABLED_DIM_MIN)
            # disabled: the live verify loses it, the disabled path holds it
            self.assertIsNone(got[self.opacity][0])
            self.assertGreater(got[self.opacity][1]["disabled_dim"], I.DISABLED_DIM_MIN)
            self.assertAlmostEqual(got[self.opacity][1]["opacity"], self.opacity, delta=0.05)
            # gone: the bare map holds nothing
            self.assertIsNone(got[0.0][0])
            self.assertLess(got[0.0][1]["disabled_dim"], I.DISABLED_DIM_MIN)

    def test_the_reader_holds_a_drawing_through_its_disabled_state(self):
        rng = np.random.default_rng(4)
        floor = self.slab.astype(bool)
        rd = I.AbilityIconReader(slab=self.slab, floor=floor, sgray=self.sgray, box=(0, 0, 465, 465))
        frames = [_render(self.base, self.pm, self.a, o, 200, 240, rng)
                  for o in (1.0, 1.0, self.opacity, self.opacity, 0.0)]
        for k, f in enumerate(frames):
            rd.feed(SimpleNamespace(frame=f, t_ms=500.0 * k, frame_idx=k))
        ev = rd.events("s", "k")
        head, rows = ev[0], ev[1:]
        self.assertEqual(head["ability_icon_version"], "icon-proposer-0.4.0")
        self.assertEqual(head["disabled"]["opacity"], self.opacity)
        # the two dim samples: verified through the disabled drawing, and
        # the held disc joins the sample's candidates, disabled
        for r in rows[2:4]:
            (v,) = [v for v in r["verify"]["rows"] if v.get("disabled_dim") is not None]
            self.assertTrue(I.held_disabled(v))
            dim = [c for c in r["candidates"] if c.get("state") == "disabled"]
            self.assertEqual(len(dim), 1)
            self.assertEqual(I.verified_continuations(r["verify"], r["candidates"]),
                             {r["candidates"].index(dim[0]): v["of"]})
        # the map alone: the disc is gone
        (v,) = rows[4]["verify"]["rows"]
        self.assertFalse(I.held(v))
        self.assertEqual(head["verify_held_disabled"], 2)
        self.assertEqual(head["verify_lost"], 1)

    def test_the_glyph_matcher_reads_the_dim_glyph_as_the_live_one(self):
        from reticle import minimap_glyph as mg
        data = mg.GlyphData.load(DEFAULT_STORE)
        tm = mg.Templates(data, [k for k in data.keys if k.startswith("Deadlock:")], 1.0, "policy")
        rng = np.random.default_rng(5)
        score = {}
        for o in (1.0, self.opacity):
            im = _render(self.base, self.pm, self.a, o, 200, 240, rng)
            y = cv2.cvtColor(im, cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)
            w, _ = mg.disc_windows(y, np.array([[200.0, 240.0]]), tm.w, tm.sh)
            best, _, _ = mg.score_windows(w, tm)
            score[o] = dict(zip(tm.keys, best[0].tolist()))
        for o in score:
            self.assertEqual(max(score[o], key=score[o].get), "Deadlock:Q")
        self.assertLess(abs(score[1.0]["Deadlock:Q"] - score[self.opacity]["Deadlock:Q"]), 0.1)


if __name__ == "__main__":
    unittest.main()
