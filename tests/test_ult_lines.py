"""The ultimate voice-line reader on synthetic arrays: no capture, no store, no GPU."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle import ult_lines as ul


def _plant(seed=3, n=48000 * 3, at=50000, m=4000):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.3, n).astype(np.float32)
    y = rng.normal(0, 0.3, m).astype(np.float32)
    x[at:at + m] += y
    return x, y


class CorrelationTests(unittest.TestCase):

    def test_a_planted_line_is_found_at_its_hop(self):
        x, y = _plant()
        s = ul.phat_tracks(x, [y], chunk=1 << 15, xp=np)[0]
        self.assertEqual(int(np.argmax(s)), 50000 // ul.HOP_N)
        self.assertGreater(s.max(), 0.2)
        self.assertLess(np.median(s[s > -1]), 0.05)

    def test_a_line_straddling_two_chunks_is_still_found(self):
        rng = np.random.default_rng(4)
        x = rng.normal(0, 0.3, 48000 * 2).astype(np.float32)
        y = rng.normal(0, 0.3, 3000).astype(np.float32)
        chunk = 1 << 14
        step = (chunk - int(np.ceil(3000 / ul.HOP_N)) * ul.HOP_N) // ul.HOP_N * ul.HOP_N
        at = step - 1000                 # starts in chunk 0, ends past its step
        x[at:at + 3000] += y
        s = ul.phat_tracks(x, [y], chunk=chunk, xp=np)[0]
        self.assertEqual(int(np.argmax(s)), at // ul.HOP_N)

    def test_a_chunk_shorter_than_the_line_refuses(self):
        with self.assertRaises(ValueError):
            ul.phat_tracks(np.zeros(4096, np.float32), [np.ones(5000, np.float32)],
                           chunk=4096, xp=np)

    def test_the_read_reproduces_itself(self):
        x, y = _plant(seed=5)
        a = ul.phat_tracks(x, [y, y[::-1].copy()], chunk=1 << 15, xp=np)
        b = ul.phat_tracks(x, [y, y[::-1].copy()], chunk=1 << 15, xp=np)
        np.testing.assert_array_equal(a, b)


class PeakTests(unittest.TestCase):

    def test_nms_keeps_the_higher_peak_within_one_template_length(self):
        s = np.zeros(60, np.float32)
        s[10], s[14], s[30], s[45] = 0.9, 0.8, 0.7, 0.2
        self.assertEqual(ul.nms_peaks(s, m=5, floor=0.5).tolist(), [10, 30])
        self.assertEqual(ul.nms_peaks(s, m=4, floor=0.5).tolist(), [10, 14, 30])

    def test_each_template_keeps_peaks_above_its_own_floor(self):
        rng = np.random.default_rng(6)
        tracks = rng.uniform(0, 0.01, (2, 1000)).astype(np.float32)
        tracks[0, 100], tracks[1, 700] = 0.5, 0.3
        tracks[1, 990:] = -1.0           # unscored frames past the end
        pk = ul.track_peaks(tracks, [20, 20], q=0.99)
        self.assertIn((0, 100), list(zip(pk["tpl"].tolist(), pk["frame"].tolist())))
        self.assertIn((1, 700), list(zip(pk["tpl"].tolist(), pk["frame"].tolist())))
        self.assertTrue(np.all(pk["score"] >= pk["floor"][pk["tpl"]]))
        self.assertAlmostEqual(float(pk["floor"][1]),
                               float(np.quantile(tracks[1][tracks[1] > -1], 0.99)), places=6)


class TemplateTests(unittest.TestCase):

    def test_trim_keeps_the_active_span_and_floors_silence(self):
        L = np.full((50, 4), -100.0, np.float32)
        L[10:30] = 40.0
        L[20, 2] = -100.0                # a digital hole inside the line
        ok = np.ones(50, bool)
        ok[:3] = False
        T, k0, k1 = ul.trim_floor(L, ok, active_db=40.0, floor_db=50.0)
        self.assertEqual((k0, k1), (10, 30))
        self.assertEqual(T.min(), -10.0)

    def test_log_mel_places_a_tone_in_its_band_and_refuses_the_edges(self):
        t = np.arange(48000, dtype=np.float32) / 48000
        x = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        L, ok, _rms = ul.log_mel(x, np.ones(len(x), bool), 48000, xp=np)
        self.assertEqual(L.shape, (100, ul.BANDS))
        self.assertFalse(ok[0])
        self.assertTrue(ok[50])
        centres = ul.mel_filterbank(48000, ul.NFFT).argmax(axis=1) * 48000 / ul.NFFT
        self.assertLess(abs(centres[int(L[50].argmax())] - 1000), 150)

    def test_the_ult_pair_comes_from_the_ally_and_enemy_cast_sections(self):
        rows = [
            {"agent": "Gekko", "ability": "Thrash", "section": "Ally Cast", "file": "G__t__ally-cast__2.mp3"},
            {"agent": "Gekko", "ability": "Thrash", "section": "Ally Cast", "file": "G__t__ally-cast__1.mp3"},
            {"agent": "Gekko", "ability": "Thrash", "section": "Enemy Cast", "file": "G__t__enemy-cast__1.mp3"},
            {"agent": "Gekko", "ability": "Thrash", "section": "Ally Recast", "file": "G__t__ally-recast__1.mp3"},
            {"agent": "KAY/O", "ability": "NULL/cmd", "section": "Ally Cast", "file": "K__n__ally-cast__1.mp3"},
            {"agent": "Sova", "ability": "Hunter's Fury", "section": "Ally Cast", "file": "S__h__ally-cast__1.mp3"}]
        got = ul.harvested_ults(rows, have={"Sova"})
        self.assertEqual(got, {"Gekko_ult_ally": "G__t__ally-cast__1.mp3",
                               "Gekko_ult_enemy": "G__t__enemy-cast__1.mp3",
                               "KAY_O_ult_ally": "K__n__ally-cast__1.mp3"})

    def test_two_abilities_with_cast_lines_stop_the_harvest(self):
        rows = [{"agent": "X", "ability": "One", "section": "Ally Cast", "file": "a.mp3"},
                {"agent": "X", "ability": "Two", "section": "Enemy Cast", "file": "b.mp3"}]
        with self.assertRaises(ValueError):
            ul.harvested_ults(rows, have=set())

    @staticmethod
    def _vo(agent, event, media, heard_by, slot="X"):
        return {"agent": agent, "event": event, "media": media, "heard_by": heard_by, "slot": slot,
                "language": "en-US", "flac": f"{agent.replace('/', '_')}/{slot}/{event}__{media}.flac",
                "ref_version": "vo-ref-0.1.0"}

    def test_the_ult_pair_is_the_x_event_with_one_ally_and_one_enemy_line(self):
        v = self._vo
        rows = [v("Gekko", "Play_VO_Aggrobot_AbilityXCast", "A.XCastAllies01", "ally"),
                v("Gekko", "Play_VO_Aggrobot_AbilityXCast", "A.XCastEnemies01", "enemy"),
                v("Gekko", "Play_VO_Aggrobot_AbilityXCast_2nd", "A.XRecastAllies01", "ally"),
                v("Gekko", "Play_VO_Aggrobot_AbilityXCast_2nd", "A.XRecastAllies02", "ally"),
                v("Gekko", "Play_VO_Aggrobot_AbilityXCast_2nd", "A.XRecastEnemies01", "enemy"),
                v("Gekko", "Play_VO_Aggrobot_AbilityXCast_2nd", "A.XRecastEnemies02", "enemy"),
                v("Raze", "Play_VO_Clay_AbilityXCast", "Clay.AbilityXCast01", None),
                v("Raze", "Play_VO_Clay_AbilityXEquip", "Clay.AbilityXEquipAllies03", "ally"),
                v("Raze", "Play_VO_Clay_AbilityXEquip", "Clay.AbilityXEquipEnemies01", "enemy"),
                {**v("Reyna", "Play_VO_Vampire_ULT_AbilityXCast", "Vampire.ULT.AbilityXCastAllies01", "ally"),
                 "ult_form": True},
                {**v("Reyna", "Play_VO_Vampire_ULT_AbilityXCast", "Vampire.ULT.AbilityXCastAllies02", "ally"),
                 "ult_form": True},
                v("Reyna", "Play_VO_Vampire_AbilityXCast", "V.XCastAllies01", "ally"),
                v("Reyna", "Play_VO_Vampire_AbilityXCast", "V.XCastEnemies01", "enemy"),
                v("KAY/O", "Play_VO_Grenadier_AbilityXCast", "G.XCastAllies01", "ally"),
                v("KAY/O", "Play_VO_Grenadier_AbilityXCast", "G.XCastEnemies01", "enemy"),
                v("KAY/O", "Play_VO_Grenadier_AbilityQCast", "G.QCast01", None, slot="Q")]
        got = {n: r["media"] for n, r in ul.ult_event_rows(rows).items()}
        self.assertEqual(got, {"Gekko_ult_ally": "A.XCastAllies01", "Gekko_ult_enemy": "A.XCastEnemies01",
                               "KAY_O_ult_ally": "G.XCastAllies01", "KAY_O_ult_enemy": "G.XCastEnemies01",
                               "Raze_ult_ally": "Clay.AbilityXEquipAllies03",
                               "Raze_ult_enemy": "Clay.AbilityXEquipEnemies01",
                               "Reyna_ult_ally": "Vampire.ULT.AbilityXCastAllies01",
                               "Reyna_ult_enemy": "Vampire.ULT.AbilityXCastAllies02"})
        self.assertEqual(ul.ult_event_rows(rows)["Reyna_ult_enemy"]["heard_by"], "enemy")

    def test_an_agent_without_one_split_x_event_refuses_the_set(self):
        v = self._vo
        with self.assertRaises(ValueError):
            ul.ult_event_rows([v("Raze", "Play_VO_Clay_AbilityXCast", "Clay.AbilityXCast01", None)])
        two = [v("X", f"Play_VO_X_{e}", f"X.{e}{s}", h) for e in ("AbilityXCast", "AbilityXEquip")
               for s, h in (("Allies01", "ally"), ("Enemies01", "enemy"))]
        with self.assertRaises(ValueError):
            ul.ult_event_rows(two)

    def test_the_manifest_lists_the_game_lines_with_their_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d)
            rows = [self._vo("Sova", "Play_VO_Hunter_AbilityXCast", "Hunter.AbilityXCastAllies", "ally"),
                    self._vo("Sova", "Play_VO_Hunter_AbilityXCast", "Hunter.AbilityXCastEnemies01", "enemy")]
            for r in rows:
                (v / r["flac"]).parent.mkdir(parents=True, exist_ok=True)
                (v / r["flac"]).write_bytes(r["media"].encode())
            (v / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            got = ul.manifest_from_assets(v)
            self.assertEqual([(e["name"], e["agent"], e["variant"], e["file"]) for e in got],
                             [("Sova_ult_ally", "Sova", "ally", rows[0]["flac"]),
                              ("Sova_ult_enemy", "Sova", "enemy", rows[1]["flac"])])
            self.assertEqual(got[0]["sha256"], ul.template_digest(v / rows[0]["flac"]))
            self.assertEqual(got[1]["event"], "Play_VO_Hunter_AbilityXCast")
            self.assertEqual(ul.manifest_dir({"dir": "reference/game-files/vo"}),
                             Path("reference/game-files/vo"))
            self.assertEqual(ul.manifest_dir({}), ul.VOICE_DIR)

    def test_a_file_that_differs_from_the_manifest_refuses_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d)
            (v / "Sova_ult_ally.mp3").write_bytes(b"not the line")
            entry = {"name": "Sova_ult_ally", "agent": "Sova", "variant": "ally",
                     "file": "Sova_ult_ally.mp3", "sha256": "0" * 16}
            with self.assertRaises(ValueError):
                ul.build_templates(v, [entry], xp=np)
            with self.assertRaises(ValueError):
                ul.build_templates(v, [{**entry, "file": "missing.mp3"}], xp=np)

    def test_the_declared_manifest_holds_both_lines_of_every_agent(self):
        m = ul.load_manifest()
        names = [e["name"] for e in m["templates"]]
        self.assertEqual(len(names), len(set(names)))
        by_agent = {}
        for e in m["templates"]:
            by_agent.setdefault(e["agent"], set()).add(e["variant"])
            self.assertEqual(e["name"], f"{e['agent']}_ult_{e['variant']}")
        self.assertTrue(all(v == {"ally", "enemy"} for v in by_agent.values()))
        self.assertIn("KAY_O", by_agent)
        self.assertIn("Gekko", by_agent)
        self.assertEqual(m["key"], ul.templates_key(m["templates"]))
        self.assertEqual(ul.manifest_dir(m), ul.VO_DIR)
        self.assertTrue(all(e["ref_version"] == m["ref_version"] for e in m["templates"]))


class ObservationTests(unittest.TestCase):

    def test_rows_are_a_coverage_row_then_peaks_in_time_order(self):
        x, y = _plant(seed=7, at=96000)
        templates = [{"name": "Sova_ult_ally", "agent": "Sova", "variant": "ally", "frames": 9},
                     {"name": "Sova_ult_enemy", "agent": "Sova", "variant": "enemy", "frames": 9}]
        tracks = ul.phat_tracks(x, [y, y[::-1].copy()], chunk=1 << 15, xp=np)
        peaks = ul.track_peaks(tracks, [t["frames"] for t in templates])
        info = {"decode_s": 0.0, "rate": 48000, "filled_fraction": 1.0, "backend": "numpy",
                "n_frames": int(tracks.shape[1]), "score_s": 0.0}
        rows = ul.observations("s", "ck", "ult-line-test", templates, "key", info, peaks)
        cov, rest = rows[0], rows[1:]
        self.assertEqual(cov["kind"], "coverage")
        self.assertEqual(cov["peaks"], len(rest))
        self.assertEqual(set(cov["per_template"]), {"Sova_ult_ally", "Sova_ult_enemy"})
        self.assertTrue(all(r["kind"] == "peak" and r["ult_line_version"] == "ult-line-test"
                            and r["content_key"] == "ck" and r["session_id"] == "s" for r in rest))
        order = [(r["frame"], r["template"]) for r in rest]
        self.assertEqual(order, sorted(order))
        best = max(rest, key=lambda r: r["score"])
        self.assertEqual((best["template"], best["t_s"]), ("Sova_ult_ally", 2.0))
        self.assertNotIn("class", best)
        self.assertTrue(all(r["score"] >= r["floor"] for r in rest))


if __name__ == "__main__":
    unittest.main()
