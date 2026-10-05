"""The minimap glyph reader (`minimap_glyph`, `ability_glyph` rows)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from reticle import minimap_glyph as M
from reticle.version import ABILITY_GLYPH_VERSION

STORE = Path(os.environ.get("RETICLE_STORE", Path.home() / "reticle-store"))


def _glyph(kind: str) -> np.ndarray:
    """A 128 px white-on-black test glyph."""
    g = np.zeros((128, 128), np.float32)
    if kind == "arrow":                                   # asymmetric: its rotation is recoverable
        cv2.fillPoly(g, [np.array([[64, 10], [110, 70], [76, 70], [76, 118], [52, 118], [52, 70],
                                   [18, 70]], np.int32)], 1.0)
    elif kind == "ring":
        cv2.circle(g, (64, 64), 44, 1.0, 14)
    elif kind == "bar":
        cv2.rectangle(g, (20, 54), (108, 74), 1.0, -1)
    elif kind == "dots":
        for x, y in ((34, 34), (94, 34), (64, 94)):
            cv2.circle(g, (x, y), 14, 1.0, -1)
    return g


def _data(cuts=None) -> M.GlyphData:
    sources = {"Alpha:E": [("icon", _glyph("arrow"))], "Alpha:Q": [("icon", _glyph("ring"))],
               "Bravo:C": [("icon", _glyph("bar"))], "Charlie:X": [("icon", _glyph("dots"))]}
    keys = sorted(sources)
    cuts = cuts or {k: 0.6 for k in keys}
    return M.GlyphData(keys, sources, {"Alpha:E"}, cuts, {"stamp": "test-bank"})


def _crop(glyph=None, rot=0, at=(200, 220), canvas=16, n=465, noise_seed=3):
    """A grey crop with a dark disc at `at`, a glyph drawn into it at `rot`."""
    rng = np.random.default_rng(noise_seed)
    img = np.full((n, n, 3), 140, np.float32) + rng.normal(0, 2, (n, n, 1))
    cv2.circle(img, at, 13, (35, 35, 35), -1)
    if glyph is not None:
        t = M._template(glyph, canvas, rot)
        h = t.shape[0] // 2
        x0, y0 = at[0] - h, at[1] - h
        img[y0:y0 + t.shape[0], x0:x0 + t.shape[1]] += 200 * t[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


class _Icons:
    """The proposer's row for a sample: a stub of `LiveIcons`, with the
    verify of the previous read sample's discs where they still hold
    (`lost` names the previous indices whose verify fails)."""
    version, source = "icon-proposer-test", "stub"

    def __init__(self, discs, reason=None):
        self.discs, self.reason = discs, reason
        self.lost: set = set()
        self._prev = None

    def at(self, smp):
        if self.reason:
            self._prev = None
            return {"t_ms": smp.t_ms, "reason": self.reason, "candidates": None, "verify": None}
        cands = [{"cx": x, "cy": y, "r": 10.0} for x, y in self.discs]
        ver = None
        if self._prev is not None:
            t0, prev = self._prev
            ver = {"of_t_ms": t0, "rows": [{"of": k, "cx": c["cx"], "cy": c["cy"], "r": c["r"],
                                            "score": None if k in self.lost else 0.5}
                                           for k, c in enumerate(prev)]}
        self._prev = (float(smp.t_ms), cands)
        return {"t_ms": smp.t_ms, "reason": None, "candidates": cands, "verify": ver}


def _reader(data, icons, cands=None, **kw):
    cands = {"ally": {"agents": {"Alpha": "named"}, "blind": 0},
             "enemy": {"agents": {"Charlie": "rival"}, "blind": 0}} if cands is None else cands
    kw.setdefault("hz", 2.0)
    return M.AbilityGlyphReader(data, (0, 0, 465, 465), "s0", cands, "lineup test", icons, **kw)


def _smp(img, t, i=0):
    return SimpleNamespace(frame=img, t_ms=float(t), frame_idx=i)


class MatcherTest(unittest.TestCase):
    def setUp(self):
        os.environ["RETICLE_GLYPH"] = "cpu"

    def test_a_placed_glyph_at_a_known_rotation_scores_its_key_first(self):
        data = _data()
        img = _crop(_glyph("arrow"), rot=60)
        r = _reader(data, _Icons([(200, 220)]))
        r.feed(_smp(img, 1000.0))
        rows = [x for x in r.rows if x["kind"] == "disc" and x["set"] == "context"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["best"], "Alpha:E")
        score, si, canvas, rot, dx, dy = rows[0]["scores"]["Alpha:E"]
        self.assertGreater(score, 0.9)
        self.assertEqual(rot, 60)
        self.assertEqual((dx, dy), (0, 0))
        self.assertTrue(rows[0]["above_cut"])

    def test_an_upright_key_is_searched_at_zero_only(self):
        tm = M.Templates(_data(), ["Alpha:Q", "Alpha:E"], 1.0, "policy")
        rots = {tm.keys[o]: set() for o in set(tm.owner)}
        for (si, c, rot), o in zip(tm.meta, tm.owner):
            rots[tm.keys[o]].add(rot)
        self.assertEqual(rots["Alpha:Q"], {0})
        self.assertEqual(rots["Alpha:E"], set(M.ROTATIONS))

    def test_a_disc_with_no_glyph_scores_under_the_null_cut(self):
        data = _data()
        r = _reader(data, _Icons([(200, 220)]))
        r.feed(_smp(_crop(None), 1000.0))
        row = next(x for x in r.rows if x["kind"] == "disc" and x["set"] == "context")
        self.assertLess(row["scores"][row["best"]][0], data.cuts[row["best"]])
        self.assertFalse(row["above_cut"])

    def test_the_context_set_excludes_kits_outside_the_lineup(self):
        data = _data()
        r = _reader(data, _Icons([(200, 220)]))
        self.assertEqual(r.context_keys, ["Alpha:E", "Alpha:Q", "Charlie:X"])
        r.feed(_smp(_crop(_glyph("bar")), 1000.0))
        row = next(x for x in r.rows if x["kind"] == "disc" and x["set"] == "context")
        self.assertNotIn("Bravo:C", row["scores"])
        self.assertNotEqual(row["best"], "Bravo:C")
        # The audit path scores every kit: the first birth is an audit sample.
        audit = next(x for x in r.rows if x["kind"] == "disc" and x["set"] == "audit")
        self.assertEqual(audit["best"], "Bravo:C")
        self.assertEqual(set(audit["scores"]), set(data.keys))

    def test_agent_names_match_across_stores(self):
        self.assertEqual(M._agent_key("KAY_O"), M._agent_key("KAY/O"))


class ReaderTest(unittest.TestCase):
    def setUp(self):
        os.environ["RETICLE_GLYPH"] = "cpu"

    def test_reasons_windows_audit_and_surprise(self):
        data = _data()
        icons = _Icons([(200, 220)])
        r = _reader(data, icons, audit_every=2)
        blank = _crop(None)
        r.feed(_smp(blank, 0.0, 0))                      # birth 1: audit, below null
        r.feed(_smp(blank, 500.0, 1))                    # the verify continues the window
        icons.reason = "not_live"
        r.feed(_smp(blank, 1000.0, 2))                   # unread: the window ends -> surprise
        icons.reason = None
        r.feed(_smp(_crop(_glyph("ring")), 1500.0, 3))   # birth 2: not audited, clears its cut
        rows = r.events("s0", "key")
        head, body = rows[0], rows[1:]
        frames = [x for x in body if x["kind"] == "frame"]
        self.assertEqual([f["reason"] for f in frames], [None, None, "not_live", None])
        ctx = [x for x in body if x["kind"] == "disc" and x["set"] == "context"]
        self.assertEqual([x["birth"] for x in ctx], [True, False, True])
        self.assertEqual(ctx[1]["rests_on"], [ctx[0]["disc"], "lineup test"])
        self.assertEqual(ctx[1]["window"], ctx[0]["window"])
        self.assertEqual(ctx[0]["disc"], "ability_icon:s0:0.0:0")
        self.assertEqual(sum(x.get("set") == "audit" for x in body), 2)
        sur = [x for x in body if x.get("set") == "surprise"]
        self.assertEqual([x["t_ms"] for x in sur], [0.0, 500.0])
        self.assertTrue(all(x["surprise_reason"].startswith("below_null_through_window") for x in sur))
        self.assertEqual(ctx[2]["best"], "Alpha:Q")
        self.assertEqual(head["births"], 2)
        self.assertEqual(head["windows"], {"audit": 1, "surprise": 1})

    def test_a_lost_verify_ends_the_window_and_the_disc_is_born_again(self):
        icons = _Icons([(200, 220)])
        r = _reader(_data(), icons)
        blank = _crop(None)
        r.feed(_smp(blank, 0.0, 0))
        icons.lost = {0}                                  # the proposer's verify loses the disc
        r.feed(_smp(blank, 500.0, 1))
        ctx = [x for x in r.rows if x["kind"] == "disc" and x["set"] == "context"]
        self.assertEqual([x["birth"] for x in ctx], [True, True])
        self.assertNotEqual(ctx[0]["window"], ctx[1]["window"])
        self.assertEqual(r.continued, {"verified": 0, "lost": 1})

    def test_a_window_past_its_schedule_still_absorbs_its_disc(self):
        """After WINDOW_MS the window's audit and surprise stop, and the disc
        the verify keeps is never born again."""
        icons = _Icons([(200, 220)])
        r = _reader(_data(), icons, audit_every=1)
        blank = _crop(None)
        for k in range(10):                               # 0 .. 4.5 s at 2 Hz
            r.feed(_smp(blank, 500.0 * k, k))
        ctx = [x for x in r.rows if x["kind"] == "disc" and x["set"] == "context"]
        self.assertEqual(sum(x["birth"] for x in ctx), 1)
        self.assertEqual(len({x["window"] for x in ctx}), 1)
        audits = [x for x in r.rows if x.get("set") == "audit"]
        self.assertEqual([x["t_ms"] for x in audits], [500.0 * k for k in range(7)])
        r.finish()
        sur = [x for x in r.rows if x.get("set") == "surprise"]
        self.assertEqual(len(sur), 7)                     # the scheduled frames only
        self.assertTrue(all(x["surprise_reason"].endswith("window_end") for x in sur))

    def test_audit_rows_store_no_cut(self):
        r = _reader(_data(), _Icons([(200, 220)]))
        r.feed(_smp(_crop(_glyph("bar")), 0.0))
        audit = next(x for x in r.rows if x.get("set") == "audit")
        self.assertIsNone(audit["best_cut"])
        self.assertIsNone(audit["above_cut"])
        self.assertEqual(audit["cut_reason"], "no_null_at_full_rotation")
        self.assertEqual(audit["rests_on"], [])           # the full set rests on no lineup

    def test_context_and_frame_rows_rest_on_the_lineup(self):
        r = _reader(_data(), _Icons([(200, 220)]))
        r.feed(_smp(_crop(_glyph("arrow")), 0.0))
        ctx = next(x for x in r.rows if x.get("set") == "context")
        frame = next(x for x in r.rows if x["kind"] == "frame")
        self.assertIn("lineup test", ctx["rests_on"])
        self.assertEqual(frame["rests_on"], ["lineup test"])

    def test_a_disc_the_baked_static_draws_is_gated(self):
        """Stage 1's map_like: a disc whose luma correlates with the baked
        static's is the map's; it is not scored and opens no window."""
        img = _crop(_glyph("bar"))                        # a wall notch the map draws, as a test
        r = _reader(_data(), _Icons([(200, 220)]), static=img.copy())
        r.feed(_smp(img, 0.0))
        row = next(x for x in r.rows if x["kind"] == "disc")
        self.assertEqual(row["reason"], "static_like")
        self.assertGreaterEqual(row["static_corr"], M.MAP_CORR)
        self.assertIsNone(row["scores"])
        self.assertIsNone(row["window"])
        self.assertEqual(r.births, 0)
        self.assertFalse(any(x.get("set") in ("audit", "surprise") for x in r.rows))
        # A glyph disc on a map that draws a flat floor there is scored.
        r2 = _reader(_data(), _Icons([(200, 220)]), static=_crop(None, at=(60, 60)))
        r2.feed(_smp(_crop(_glyph("arrow")), 0.0))
        row2 = next(x for x in r2.rows if x["kind"] == "disc")
        self.assertIsNone(row2["reason"])
        self.assertLess(row2["static_corr"], M.MAP_CORR)

    def test_a_disc_inside_a_stored_portrait_is_gated(self):
        allies = M.StoredAllyIcons.from_rows([
            {"kind": "coverage", "ally_icon_version": "ally-icon-test"},
            {"kind": "frame", "frame_idx": 0, "self": [100.0, 100.0, 7.0]},
            {"kind": "icon", "frame_idx": 0, "cx": 203.0, "cy": 221.0, "r": 6.0, "family": "ally"},
            {"kind": "icon", "frame_idx": 1, "cx": 330.0, "cy": 330.0, "r": 6.0, "family": "ally"}])
        r = _reader(_data(), _Icons([(200, 220), (100, 104), (330, 330)]), allies=allies)
        r.feed(_smp(_crop(_glyph("arrow")), 0.0, 0))
        rows = sorted((x for x in r.rows if x["kind"] == "disc" and x["set"] == "context"),
                      key=lambda x: x["i"])
        self.assertEqual([x["reason"] for x in rows], ["on_ally_icon", "on_ally_icon", None])
        self.assertEqual(rows[1]["icon"]["family"], "self")
        self.assertAlmostEqual(rows[0]["icon"]["d"], float(np.hypot(3, 1)), places=3)
        head = r.events("s0", "k")[0]
        self.assertEqual(head["gates"]["ally_icon"]["ally_icon_version"], "ally-icon-test")
        frame = next(x for x in r.rows if x["kind"] == "frame")
        self.assertEqual(frame["gated"], {"on_ally_icon": 2})

    def test_missing_gate_inputs_are_named_not_guessed(self):
        r = _reader(_data(), _Icons([(200, 220)]))
        r.feed(_smp(_crop(_glyph("arrow")), 0.0))
        row = next(x for x in r.rows if x["kind"] == "disc")
        self.assertIsNone(row["static_corr"])
        self.assertIsNone(row["icon"])
        head = r.events("s0", "k")[0]
        self.assertTrue(head["gates"]["static"]["unknown"])
        self.assertTrue(head["gates"]["ally_icon"]["unknown"])

    def test_provenance_fields_present(self):
        r = _reader(_data(), _Icons([(200, 220)]))
        r.feed(_smp(_crop(_glyph("arrow")), 0.0))
        head = r.events("s0", "geo-key")[0]
        self.assertEqual(head["kind"], "coverage")
        self.assertEqual(head["ability_glyph_version"], ABILITY_GLYPH_VERSION)
        self.assertEqual(head["ability_icon_version"], "icon-proposer-test")
        self.assertEqual(head["glyph_bank"], M.GLYPH_BANK_STAMP)
        for k in ("glyph_data", "matcher", "candidates", "candidates_from", "context", "audit",
                  "surprise", "window", "textures", "by_reason"):
            self.assertIn(k, head)
        self.assertEqual(head["candidates_from"], "lineup test")
        self.assertIn("why", head["context"])
        self.assertEqual(head["audit"]["every"], M.AUDIT_EVERY)
        self.assertIn("INTER_AREA", head["matcher"]["resample"])

    def test_refusals_keep_their_reason(self):
        r = _reader(_data(), _Icons([(200, 220)]), cands=None)
        r.candidates = None
        r.feed(_smp(_crop(None), 0.0))
        self.assertEqual(r.rows[-1]["reason"], "no_lineup")
        r2 = _reader(_data(), SimpleNamespace(at=lambda smp: None, version=None, source="stub"))
        r2.feed(_smp(_crop(None), 0.0))
        self.assertEqual(r2.rows[-1]["reason"], "no_ability_icon_row")
        r3 = _reader(_data(), _Icons([(3, 3)]))
        r3.feed(_smp(_crop(None), 0.0))
        self.assertEqual(r3.rows[0]["reason"], "off_crop")

    def test_live_icons_reads_only_the_same_sample(self):
        ip = SimpleNamespace(rows=[{"t_ms": 500.0, "reason": None, "candidates": []}])
        live = M.LiveIcons(ip)
        self.assertIsNotNone(live.at(_smp(None, 500.0)))
        self.assertIsNone(live.at(_smp(None, 1000.0)))

    def test_stored_icons_reads_the_stored_rows_and_their_stamp(self):
        rows = [{"kind": "coverage", "ability_icon_version": "icon-proposer-0.3.0"},
                {"kind": "frame", "t_ms": 500.0, "reason": None, "candidates": [], "verify": None},
                {"kind": "frame", "t_ms": 1000.0, "reason": "not_live", "candidates": None}]
        st = M.StoredIcons(rows)
        self.assertEqual(st.version, "icon-proposer-0.3.0")
        self.assertEqual(st.source, "stored")
        self.assertEqual(st.at(_smp(None, 500.0))["candidates"], [])
        self.assertEqual(st.at(_smp(None, 1000.0))["reason"], "not_live")
        self.assertIsNone(st.at(_smp(None, 1500.0)))

    def test_the_stored_path_reads_as_the_live_path(self):
        """A reader over the stored proposer rows writes the rows a reader fed
        live writes."""
        img = _crop(_glyph("arrow"))
        live = _Icons([(200, 220)])
        stored = [{"kind": "coverage", "ability_icon_version": "icon-proposer-test"}]
        held = {}
        a = _reader(_data(), SimpleNamespace(at=lambda s: held[s.t_ms], version="icon-proposer-test",
                                             source="stub"))
        for k in range(3):
            smp = _smp(img, 500.0 * k, k)
            held[smp.t_ms] = live.at(smp)
            stored.append({"kind": "frame", **held[smp.t_ms]})
            a.feed(smp)
        b = _reader(_data(), M.StoredIcons(stored))
        for k in range(3):
            b.feed(_smp(img, 500.0 * k, k))

        def strip(rows):
            return [{k: v for k, v in x.items() if k != "ability_icon_source"} for x in rows]

        self.assertEqual(strip(a.events("s0", "k")[1:]), strip(b.events("s0", "k")[1:]))
        self.assertEqual(b.events("s0", "k")[0]["ability_icon_source"], "stored")

    def test_a_staged_pass_with_the_live_icon_reader_refuses(self):
        with self.assertRaises(SystemExit):
            M.check_pass(True, "staged", None)
        with self.assertRaises(SystemExit):
            M.check_pass(True, "staged", 2)
        M.check_pass(True, "staged", 0)
        M.check_pass(True, "serial", None)
        M.check_pass(False, "staged", 2)                  # stored proposer rows: nothing to race


class ContinuationTest(unittest.TestCase):
    """`ability_icons.verified_continuations`, the proposer's answer."""

    def test_a_held_verify_binds_the_overlapping_candidate(self):
        from reticle.ability_icons import verified_continuations
        ver = {"of_t_ms": 0.0, "rows": [{"of": 0, "cx": 50, "cy": 50, "r": 8.0, "score": 0.6},
                                        {"of": 1, "cx": 90, "cy": 90, "r": 8.0, "score": None},
                                        {"of": 2, "cx": 140, "cy": 20, "r": 8.0, "score": 0.5}]}
        cands = [{"cx": 141, "cy": 21, "r": 8.0}, {"cx": 90, "cy": 90, "r": 8.0},
                 {"cx": 52, "cy": 49, "r": 8.0}, {"cx": 300, "cy": 300, "r": 8.0}]
        self.assertEqual(verified_continuations(ver, cands), {0: 2, 2: 0})
        self.assertEqual(verified_continuations(None, cands), {})
        self.assertEqual(verified_continuations(ver, []), {})


class LineupCandidatesTest(unittest.TestCase):
    """`lineup.glyph_candidates`: the set the reader takes from the lineup's owner."""

    def test_named_rivals_and_blind(self):
        from unittest import mock

        from reticle import lineup
        stored = {"sides": {
            "ally": [{"slot": 0, "agent": "Sova"}, {"slot": 1, "agent": "Cypher"},
                     {"slot": 2, "agent": None, "best_guess": "Jett"},
                     {"slot": 3, "agent": None, "best_guess": None}, {"slot": 4, "agent": "Omen"}],
            "enemy": [{"slot": k, "agent": a} for k, a in enumerate(
                ("Reyna", "Killjoy", "Skye", "Sage", "KAY/O"))]}}
        with mock.patch.object(lineup, "load_lineup", return_value=stored), \
                mock.patch.object(lineup, "view_stamp", return_value="v1"):
            got, frm = lineup.glyph_candidates("s0", "store")
        self.assertEqual(frm, "lineup v1")
        self.assertEqual(got["ally"]["agents"], {"Cypher": "named", "Jett": "rival", "Omen": "named",
                                                 "Sova": "named"})
        self.assertEqual(got["ally"]["blind"], 1)
        self.assertEqual(got["enemy"]["blind"], 0)
        self.assertEqual(set(got["enemy"]["agents"].values()), {"named"})

    def test_no_lineup(self):
        from unittest import mock

        from reticle import lineup
        with mock.patch.object(lineup, "load_lineup", return_value=None):
            self.assertEqual(lineup.glyph_candidates("s0", "store"), (None, None))


@unittest.skipUnless((STORE / M.GLYPH_DATA["bank"][0]).is_dir(), "no stored glyph bank")
class GameTextureTest(unittest.TestCase):
    """The stored bank of game textures, under the stored policy."""

    def setUp(self):
        os.environ["RETICLE_GLYPH"] = "cpu"

    def test_a_game_texture_at_a_known_rotation_returns_its_key(self):
        data = M.GlyphData.load(STORE)
        key = "Cypher:E"                                  # turns [domain:abilities/cypher-spycam-minimap-glyph-turns]
        self.assertIn(key, data.rotating)
        glyph = data.sources[key][0][1]
        img = _crop(glyph / max(float(glyph.max()), 1e-6), rot=45, canvas=17)
        cands = {"ally": {"agents": {"Cypher": "named", "Sova": "named"}, "blind": 0},
                 "enemy": {"agents": {"Killjoy": "named", "Jett": "named"}, "blind": 0}}
        r = _reader(data, _Icons([(200, 220)]), cands=cands)
        r.feed(_smp(img, 0.0))
        row = next(x for x in r.rows if x["kind"] == "disc" and x["set"] == "context")
        self.assertEqual(row["best"], key)
        self.assertEqual(row["scores"][key][3], 45)
        self.assertTrue(row["above_cut"])
        self.assertTrue(all(k.split(":")[0] in ("Cypher", "Sova", "Killjoy", "Jett")
                            for k in row["scores"]))


if __name__ == "__main__":
    unittest.main()
