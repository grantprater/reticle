"""The killstreak numeral [domain:killfeed/killstreak-indicator]: templates
rendered from the game font, the empty
template, refusals, pooling and the per-round kill-index witness."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from reticle import killfeed_numeral as kn
from reticle.adjudication import killstreak as ks

FONT = kn.store_font("C:/Users/grant/reticle-store")


def _scene(numeral: str | None, art_x0: int = 120, art_y0: int = 40, phase=(0, 0),
           noise: float = 4.0, seed: int = 0) -> np.ndarray:
    """A killfeed ROI crop: a dark green backer left of a killer art window
    (art_x0, art_y0, 34 rows), with `numeral` drawn white at the slot."""
    rng = np.random.default_rng(seed)
    crop = np.full((120, 240, 3), (60, 110, 40), np.float32)
    crop[art_y0:art_y0 + 34, art_x0:art_x0 + 68] = (150, 120, 200)   # the art
    if numeral:
        ink = kn._ink(numeral, FONT, kn.FONT_PX, *phase)
        ys, xs = np.nonzero(ink > 0.02)
        ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        cx = art_x0 + kn.SLOT_CX
        cy = art_y0 + 34 + kn.SLOT_CY
        x0, y0 = int(round(cx - ink.shape[1] / 2)), int(round(cy - ink.shape[0] / 2))
        region = crop[y0:y0 + ink.shape[0], x0:x0 + ink.shape[1]]
        region += ink[..., None] * (np.array([235, 240, 238], np.float32) - region)
    crop += rng.normal(0, noise, crop.shape)
    return np.clip(crop, 0, 255).astype(np.uint8)


def _killer(art_x0=120, art_y0=40, **kw):
    return {"role": "killer", "slot": 0, "art_x0": art_x0, "art_y0": art_y0, "ally": True, **kw}


@unittest.skipUnless(FONT, "no game font in the store")
class TestTemplates(unittest.TestCase):
    def test_rendered_from_the_font_at_every_phase(self):
        temps = kn.templates(FONT, 1.0)
        self.assertEqual(tuple(temps), kn.NUMERALS)
        for text, t in temps.items():
            self.assertEqual(t.shape[0], kn.PHASES ** 2)
            # INTER_AREA keeps soft edges: full-coverage pixels and partial ones
            self.assertGreater(t.max(), 0.9)
            self.assertTrue(((t > 0.05) & (t < 0.95)).any(), text)
        # wider strings draw wider
        self.assertLess(temps["II"].shape[2], temps["III"].shape[2])
        self.assertLess(temps["III"].shape[2], temps["VIII"].shape[2])
        # a quarter-pixel phase moves the ink's centroid a quarter pixel
        t = temps["III"]
        cols = np.arange(t.shape[2])
        c0 = (t[0].sum(0) * cols).sum() / t[0].sum()
        c1 = (t[1].sum(0) * cols).sum() / t[1].sum()
        self.assertAlmostEqual(c1 - c0, 1.0 / kn.PHASES, delta=0.05)

    def test_templates_scale_with_the_capture(self):
        small, big = kn.templates(FONT, 1.0), kn.templates(FONT, 1.5)
        self.assertGreater(big["IV"].shape[2], 1.3 * small["IV"].shape[2] - 2)


@unittest.skipUnless(FONT, "no game font in the store")
class TestReader(unittest.TestCase):
    def test_reads_each_numeral_at_its_slot(self):
        for text in ("III", "IV", "V", "VI", "VIII"):
            for phase in ((0, 0), (0.5, 0.25)):
                row, = kn.numeral_observations(_scene(text, phase=phase), [_killer()], FONT)
                self.assertEqual(row["numeral"], text, (text, phase, row["scores"]))
                self.assertGreater(row["margin"], kn.READ_MIN_MARGIN)
                self.assertEqual(row["rests_on"][0]["prior"], "art_window")

    def test_the_entry_anchor_places_the_slot_first(self):
        row, = kn.numeral_observations(_scene("IV", art_x0=120),
                                       [_killer(art_x0=150, entry_anchor=120.0, entry=7)], FONT)
        self.assertEqual(row["numeral"], "IV")
        self.assertEqual(row["rests_on"][0], {"prior": "entry_anchor", "x": 120.0,
                                              "art_bottom": 74.0, "entry": 7})

    def test_the_empty_template_reads_absence(self):
        row, = kn.numeral_observations(_scene(None), [_killer()], FONT)
        self.assertEqual(row["numeral"], kn.EMPTY)
        self.assertEqual(row["best"], kn.EMPTY)
        self.assertIsNone(row["reason"])
        self.assertEqual(row["scores"][kn.EMPTY], 0.0)
        self.assertTrue(all(v <= 0 for k, v in row["scores"].items() if k))

    def test_faint_structure_is_not_a_numeral(self):
        # a soft edge in the slot, no text at the text's contrast
        crop = _scene(None, noise=1.0)
        crop[60:70, 100:110] = (80, 125, 60)
        row, = kn.numeral_observations(crop, [_killer()], FONT)
        self.assertIn(row["numeral"], (kn.EMPTY, None))
        self.assertNotIn(row["numeral"], kn.NUMERALS)

    def test_refusals_carry_their_reason(self):
        crop = _scene("III")
        cut, = kn.numeral_observations(crop, [_killer(art_x0=10)], FONT)
        self.assertEqual((cut["numeral"], cut["reason"]), (None, kn.REFUSE_CUT))
        none, = kn.numeral_observations(crop, [_killer(art_x0=None)], FONT)
        self.assertEqual((none["numeral"], none["reason"]), (None, kn.REFUSE_NO_ANCHOR))
        nofont, = kn.numeral_observations(crop, [_killer()], None)
        self.assertEqual((nofont["numeral"], nofont["reason"]), (None, kn.REFUSE_NO_FONT))
        # victim rows are not read
        self.assertEqual(kn.numeral_observations(crop, [{"role": "victim", "slot": 0}], FONT), [])

    def test_fit_scores_match_opencv_zncc(self):
        rng = np.random.default_rng(3)
        win = rng.random((20, 30)).astype(np.float32)
        temps = kn.templates(FONT, 1.0)["IV"][:2]
        sc, _ = kn.fit_scores(win, temps)
        r = cv2.matchTemplate(win, temps[1], cv2.TM_CCOEFF_NORMED)
        hi = r >= 0.5
        self.assertTrue(np.allclose(sc[1][hi], (r * r)[hi], atol=1e-4) or not hi.any())


def _row(t, slot, numeral, entry=0, reason=None, frame=None):
    return {"kind": "numeral_observation", "t_ms": float(t), "slot": slot,
            "frame_idx": frame if frame is not None else int(t // 500), "entry": entry,
            "numeral": numeral, "reason": reason}


def _verdict(t, killer, side="enemy", rn=1, slot=0, t_last=None, **kw):
    return {"death_id": f"death:s:{int(t)}:{slot}", "t_ms": float(t), "t_last_ms":
            float(t_last if t_last is not None else t + 1000), "slot": slot, "round_no": rn,
            "side": side, "killer": killer, "same_side": False, "is_revive": False,
            "is_second_life": False, "death_adjudication_version": "test", **kw}


class TestPooling(unittest.TestCase):
    def test_one_numeral_across_views(self):
        p = ks.pool_entry([_row(0, 0, "IV"), _row(500, 0, "IV"), _row(1000, 0, "")])
        self.assertEqual((p["numeral"], p["reason"]), ("IV", None))

    def test_refuses_on_disagreement(self):
        p = ks.pool_entry([_row(0, 0, "IV"), _row(500, 0, "IV"), _row(1000, 0, "V")])
        self.assertEqual((p["numeral"], p["reason"]), (None, "views_disagree"))
        p = ks.pool_entry([_row(0, 0, "IV"), _row(500, 0, "IV")] +
                          [_row(1000 + 500 * i, 0, "") for i in range(3)])
        self.assertEqual((p["numeral"], p["reason"]), (None, "numeral_and_empty"))
        p = ks.pool_entry([_row(0, 0, "IV")])
        self.assertEqual((p["numeral"], p["reason"]), (None, "too_few_views"))

    def test_absence_pools(self):
        p = ks.pool_entry([_row(0, 0, ""), _row(500, 0, ""), _row(1000, 0, None, reason="weak_fit")])
        self.assertEqual(p["numeral"], "")


class TestWitness(unittest.TestCase):
    def test_kill_index_skips_revives_and_second_lives(self):
        vs = [_verdict(1000, "Jett"), _verdict(2000, "Jett", is_revive=True),
              _verdict(3000, "Jett", is_second_life=True), _verdict(4000, "Jett"),
              _verdict(5000, "Jett", rn=2)]
        idx = ks.kill_indices(vs)
        self.assertEqual([idx[v["death_id"]]["index"] for v in vs], [1, None, None, 2, 1])
        self.assertEqual(idx[vs[1]["death_id"]]["why"], "revive")
        # the killer's side is the victim's other side
        self.assertEqual(idx[vs[0]["death_id"]]["killer_side"], "ally")

    def test_unnamed_killer_makes_later_indices_uncertain(self):
        vs = [_verdict(1000, None), _verdict(2000, "Jett")]
        idx = ks.kill_indices(vs)
        self.assertEqual(idx[vs[1]["death_id"]]["why"], "after_unnamed_killer")

    def test_agreement_and_surprise(self):
        vs = [_verdict(1000 * i, "Jett", slot=0) for i in (1, 3, 5, 7)]
        rows = []
        for i, (v, n) in enumerate(zip(vs, ("", "", "III", "V"))):
            rows += [_row(v["t_ms"], 0, n, entry=i), _row(v["t_ms"] + 500, 0, n, entry=i)]
        out = ks.witness(vs, rows)
        self.assertEqual([r["binding"] for r in out], ["reader_entry"] * 4)
        self.assertEqual([r["status"] for r in out], ["agree", "agree", "agree", "disagree"])
        s = out[3]["surprise"]
        self.assertEqual((s["kind"], s["reader"], s["death_stream"], s["delta"]),
                         ("numeral_above_index", "V", "IV", 1))
        summ = ks.summary(out)
        self.assertEqual(summ["false_reads"], 0)
        self.assertEqual(summ["status"], {"agree": 3, "disagree": 1})

    def test_false_read_and_killer_claim_binding(self):
        v = _verdict(1000, "Jett", slot=1, metadata={"killer_identity": {"claims": [
            {"channel": "killfeed_portrait", "evidence": {"observations": [
                {"frame_idx": 2, "evidence": {"slot": 1}},
                {"frame_idx": 3, "evidence": {"slot": 0}}]}}]}})
        rows = [_row(1000, 1, "III", frame=2), _row(1500, 0, "III", frame=3),
                _row(1500, 1, "", frame=3)]
        out, = ks.witness([v], rows)
        self.assertEqual(out["binding"], "killer_claim")
        self.assertEqual((out["numeral"], out["expected"], out["status"]), ("III", "", "disagree"))
        self.assertEqual(ks.summary([out])["false_reads"], 1)

    def test_killer_views_running_onto_the_next_entry_keep_the_first(self):
        claims = {"killer_identity": {"claims": [{"channel": "killfeed_portrait", "evidence": {
            "observations": [{"frame_idx": f, "evidence": {"slot": 1}} for f in (2, 3, 4, 5)]}}]}}
        v = _verdict(1000, "Jett", slot=1, metadata=claims)
        rows = [_row(1000, 1, "", entry=7, frame=2), _row(1500, 1, "", entry=7, frame=3),
                _row(2000, 1, "III", entry=8, frame=4), _row(2500, 1, "III", entry=8, frame=5)]
        out, = ks.witness([v], rows)
        self.assertEqual(out["binding"], "killer_claim_first_entry")
        self.assertEqual((out["numeral"], out["status"]), ("", "agree"))

    def test_an_entry_bound_by_two_verdicts_witnesses_neither(self):
        claims = {"killer_identity": {"claims": [{"channel": "killfeed_portrait", "evidence": {
            "observations": [{"frame_idx": f, "evidence": {"slot": 1}} for f in (2, 3)]}}]}}
        a = _verdict(1000, "Jett", slot=1, metadata=claims)
        b = _verdict(1000, "Omen", side="ally", slot=2, metadata=claims)
        rows = [_row(1000, 1, "III", entry=7, frame=2), _row(1500, 1, "III", entry=7, frame=3)]
        out = ks.witness([a, b], rows)
        self.assertEqual([r["pool"]["reason"] for r in out], ["entry_shared"] * 2)
        self.assertEqual([r["status"] for r in out], ["unread"] * 2)
        self.assertEqual(out[0]["pool"]["shared_with"], [b["death_id"]])

    def test_unread_entries_are_not_scored(self):
        out, = ks.witness([_verdict(1000, "Jett")], [])
        self.assertEqual((out["status"], out["pool"]["reason"]), ("unread", "no_views"))


if __name__ == "__main__":
    unittest.main()
