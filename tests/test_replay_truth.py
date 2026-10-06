"""The replay scorer's Riot wrap step, miss classifier, track metrics and self
identification, on synthetic data."""
import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import replay_truth as rt  # noqa: E402

MATCH = "00000000-1111-2222-3333-444444444444"


def _record(match=MATCH, start_local="2026-10-05 13:09:01", length_ms=2_400_000):
    start = dt.datetime.strptime(start_local, "%Y-%m-%d %H:%M:%S").timestamp() * 1000.0
    return {"matchInfo": {"matchId": match, "gameStartMillis": int(start),
                          "gameLengthMillis": length_ms},
            "players": [{"subject": "p1", "teamId": "Blue"}], "kills": [], "roundResults": []}


def _raw(rec):
    return json.dumps(rec).encode("utf-8")


def _prov(raw):
    return {"body_sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": "2026-10-05T17:34:52-06:00"}


CAPTURE = r"C:\Videos\2026-10-05 13-10-55.mp4"


class WrapRecordTest(unittest.TestCase):
    def test_wraps_a_matching_record(self):
        raw = _raw(_record())
        res = rt.wrap_record(raw, _prov(raw), MATCH, "sess", CAPTURE, "sess", {})
        self.assertNotIn("refused", res)
        rec = res["record"]
        self.assertEqual(rec["probe"]["session_id"], "sess")
        self.assertEqual(rec["probe"]["capture"], CAPTURE)
        self.assertEqual(rec["probe"]["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(rec["match"], json.loads(raw))
        self.assertAlmostEqual(rec["probe"]["capture_minus_game_start_s"], 114.0, places=1)

    def test_refuses_a_body_that_differs_from_its_sidecar(self):
        raw = _raw(_record())
        prov = _prov(raw + b" ")
        res = rt.wrap_record(raw, prov, MATCH, "sess", CAPTURE, None, {})
        self.assertEqual(res["refused"], "raw_sha256_differs_from_provenance")

    def test_refuses_another_match(self):
        raw = _raw(_record(match="other"))
        res = rt.wrap_record(raw, _prov(raw), MATCH, "sess", CAPTURE, None, {})
        self.assertTrue(res["refused"].startswith("record_is_match"))

    def test_refuses_a_session_already_wrapped(self):
        raw = _raw(_record())
        res = rt.wrap_record(raw, _prov(raw), MATCH, "sess", CAPTURE, None, {"sess": "older"})
        self.assertEqual(res["refused"], "session_already_wrapped:older")

    def test_refuses_when_the_replay_names_another_session(self):
        raw = _raw(_record())
        res = rt.wrap_record(raw, _prov(raw), MATCH, "sess", CAPTURE, "other", {})
        self.assertEqual(res["refused"], "replay_names_session:other")

    def test_refuses_a_capture_outside_the_game(self):
        raw = _raw(_record(start_local="2026-10-05 09:00:00", length_ms=1_800_000))
        res = rt.wrap_record(raw, _prov(raw), MATCH, "sess", CAPTURE, None, {})
        self.assertTrue(res["refused"].startswith("capture_outside_game"))

    def test_a_capture_name_without_a_stamp_skips_the_time_check(self):
        raw = _raw(_record(start_local="2026-10-05 09:00:00"))
        res = rt.wrap_record(raw, _prov(raw), MATCH, "sess", r"C:\x\clip.mp4", None, {})
        self.assertIsNone(res["record"]["probe"]["capture_minus_game_start_s"])


class WrapRiotTest(unittest.TestCase):
    """The command over a throwaway store: it writes once and never overwrites."""

    def _store(self, root: Path):
        raw = _raw(_record())
        pd = root / "external" / "riot-pd-v1"
        (pd / "raw").mkdir(parents=True)
        (pd / "provenance").mkdir()
        (pd / "raw" / f"{MATCH}.json").write_bytes(raw)
        (pd / "provenance" / f"{MATCH}.json").write_text(json.dumps(_prov(raw)))
        (root / "external" / "riot").mkdir()
        (root / "external" / "replays").mkdir()
        (root / "external" / "replays" / "manifest.json").write_text(json.dumps(
            {"files": [{"file": f"{MATCH}.vrf", "capture_session": "sess"}]}))
        (root / "manifests").mkdir()
        (root / "manifests" / "sess.json").write_text(json.dumps(
            {"session_id": "sess", "source": {"path": CAPTURE}}))

    def test_writes_once_then_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._store(root)
            dry = rt.wrap_riot(MATCH, "sess", write=False, store=root)
            self.assertFalse(dry["written"])
            self.assertFalse((root / "external" / "riot" / f"{MATCH}.json").exists())
            res = rt.wrap_riot(MATCH, "sess", write=True, store=root)
            self.assertTrue(res["written"])
            p = root / "external" / "riot" / f"{MATCH}.json"
            body = p.read_bytes()
            self.assertEqual(json.loads(body)["probe"]["session_id"], "sess")
            again = rt.wrap_riot(MATCH, "sess", write=True, store=root)
            self.assertEqual(again["refused"], "already_wrapped")
            self.assertEqual(p.read_bytes(), body)

    def test_refuses_without_a_fetched_record(self):
        with tempfile.TemporaryDirectory() as d:
            res = rt.wrap_riot(MATCH, "sess", store=Path(d))
            self.assertEqual(res["refused"], "no_fetched_record")


class MissClassTest(unittest.TestCase):
    def test_first_class_in_order_wins(self):
        f = {"widget_absent": [1, 0, 0, 0, 0, 0],
             "stacked": [1, 1, 0, 0, 0, 1],
             "under_stored_occluder": [1, 1, 1, 0, 0, 0],
             "edge": [1, 1, 1, 1, 0, 1]}
        got = rt.classify_misses({k: np.array(v, bool) for k, v in f.items()}).tolist()
        self.assertEqual(got, ["widget_absent", "stacked", "under_stored_occluder", "edge",
                               "isolated", "stacked"])

    def test_the_order_is_fixed(self):
        self.assertEqual(rt.MISS_CLASSES, ("widget_absent", "stacked", "under_stored_occluder",
                                           "edge", "isolated"))

    def test_absent_flags_never_hold(self):
        got = rt.classify_misses({"edge": np.array([True, False])}).tolist()
        self.assertEqual(got, ["edge", "isolated"])


class TrackMetricsTest(unittest.TestCase):
    def test_switches_fragments_and_idf1(self):
        # one life, ten frames: entity 1 x3, miss, entity 1 x2, entity 2 x3, miss
        ent = [1, 1, 1, -1, 1, 1, 2, 2, 2, -1]
        t = np.arange(10) * 66.7
        m = rt.track_metrics([5] * 10, t, ent, n_obs=8)
        self.assertEqual(m["switches"], 1)
        self.assertEqual(m["fragments"], 3)        # a miss and a switch each end one
        self.assertEqual(m["entity_runs"], 2)      # only the switch ends one
        self.assertEqual(m["idtp"], 5)             # life 5 <-> entity 1
        self.assertAlmostEqual(m["idf1"], 2 * 5 / (10 + 8), places=4)

    def test_lives_do_not_switch_into_each_other(self):
        m = rt.track_metrics([1, 1, 2, 2], [0, 1, 0, 1], [7, 7, 8, 8], n_obs=4)
        self.assertEqual(m["switches"], 0)
        self.assertEqual(m["idf1"], 1.0)

    def test_flagged_switches(self):
        m = rt.track_metrics([1, 1, 1], [0, 1, 2], [3, 4, 3], n_obs=3,
                             flag=[False, True, False])
        self.assertEqual(m["switches"], 2)
        self.assertEqual(m["switches_flagged"], 1)


class NearPointsTest(unittest.TestCase):
    def test_time_window_and_radius(self):
        pts = np.array([[1000.0, 50.0, 50.0, 2.0], [5000.0, 10.0, 10.0, 0.0]])
        t = np.array([1100.0, 1100.0, 3000.0])
        x = np.array([58.0, 70.0, 50.0])
        y = np.array([50.0, 50.0, 50.0])
        got = rt._near_points(t, x, y, pts, tol_ms=250.0, reach=6.5).tolist()
        self.assertEqual(got, [True, False, False])


class ChooseSelfSubjectTest(unittest.TestCase):
    """`choose_self_subject` on synthetic self tracks: four subjects, 1000 frames."""

    SUBS = ["me", "mate", "foe", "far"]

    def _dist(self, n=1000, seed=0):
        g = np.random.default_rng(seed)
        D = np.column_stack([g.uniform(0.0, 1.0, n),       # follows the icon
                             g.uniform(3.0, 30.0, n),      # a teammate nearby
                             g.uniform(10.0, 60.0, n),
                             np.full(n, 80.0)])
        return D

    def test_names_the_subject_the_track_follows(self):
        r = rt.choose_self_subject(self._dist(), self.SUBS, margin=0.25)
        self.assertEqual(r["subject"], "me")
        self.assertIsNone(r["reason"])
        self.assertEqual(r["best"]["share_within"], 1.0)
        self.assertEqual(r["runner_up"]["subject"], "mate")
        self.assertAlmostEqual(r["margin"], 1.0 - r["runner_up"]["share_within"], places=4)

    def test_a_dead_subject_counts_as_a_miss(self):
        D = self._dist()
        D[:600, 0] = np.nan            # the player dies; the icon follows the mate
        D[:600, 1] = 0.5
        r = rt.choose_self_subject(D, self.SUBS, margin=0.25)
        self.assertIsNone(r["subject"])
        self.assertEqual(r["best"]["subject"], "mate")
        self.assertTrue(r["reason"].startswith("margin_too_small"))
        self.assertEqual(r["candidates"][1]["frames_alive"], 400)

    def test_refuses_a_short_track(self):
        r = rt.choose_self_subject(self._dist(n=899), self.SUBS, margin=0.25)
        self.assertIsNone(r["subject"])
        self.assertTrue(r["reason"].startswith("track_too_short"))

    def test_refuses_a_poor_fit(self):
        D = self._dist()
        D[:, 0] = 5.0
        D[:250, 0] = 0.5               # within 2 m on a quarter of frames only
        r = rt.choose_self_subject(D, self.SUBS, margin=0.1)
        self.assertIsNone(r["subject"])
        self.assertTrue(r["reason"].startswith("no_fit"))

    def test_refuses_a_small_margin(self):
        D = self._dist()
        D[:500, 1] = 0.5               # a teammate stacked on half the track
        r = rt.choose_self_subject(D, self.SUBS, margin=0.6)
        self.assertIsNone(r["subject"])
        self.assertTrue(r["reason"].startswith("margin_too_small"))
        self.assertEqual(rt.choose_self_subject(D, self.SUBS, margin=0.5)["subject"], "me")

    def test_the_module_cut_is_set(self):
        self.assertEqual(rt.SELF_ID_MARGIN, 0.25)
        self.assertEqual(rt.choose_self_subject(self._dist(), self.SUBS)["margin_cut"], 0.25)

    def test_same_side_compares_partitions_not_labels(self):
        subs = ["a", "b", "c", "d"]
        riot = {"a": "Blue", "b": "Blue", "c": "Red", "d": "Red"}
        spawn = {"a": "B", "b": "B", "c": "A", "d": "A"}
        self.assertTrue(rt._same_side(spawn, "a", riot, "a", subs))
        spawn["b"] = "A"
        self.assertFalse(rt._same_side(spawn, "a", riot, "a", subs))
        self.assertIsNone(rt._same_side({}, "a", riot, "a", subs))


if __name__ == "__main__":
    unittest.main()
