"""prototypes/scoreboard_reads.py on synthetic rows: openings from the strip
alone, the frame-selection rules, thinning, and the threshold fit."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import scoreboard_reads as sr  # noqa: E402


def strip_sample(f, verdict):
    return {"kind": "sample", "frame_idx": f, "t_ms": f * 500.0 / 30,
            "verdict": verdict, "scoreboard_strip_version": "x"}


def slab_sample(f, open_):
    return {"kind": "sample", "frame_idx": f, "t_ms": f * 500.0 / 30, "open": open_,
            "reason": None if open_ else "green_no_rows", "anchor": None}


class TestScoreboardReads(unittest.TestCase):
    def setUp(self):
        # 2 Hz samples at 30 fps: frame 15k. Strip: open 1-4 with a hole at 3,
        # absent, then a lone unreadable sample at 7. The slab test opens at 9
        # alone, which the strip-only openings must ignore.
        verdicts = ["absent", "present", "present", "absent", "present", "absent",
                    "absent", "unreadable", "absent", "absent"]
        self.strip = [strip_sample(15 * i, v) for i, v in enumerate(verdicts)]
        self.board = [slab_sample(15 * i, i == 9) for i in range(len(verdicts))]

    def test_strip_runs_join_one_hole_and_ignore_the_slab(self):
        runs = sr.strip_runs(self.board, self.strip)
        self.assertEqual([r["frames"] for r in runs], [[15, 30, 60], [105]])

    def test_rules(self):
        f = [10, 20, 30, 40, 50]
        self.assertEqual(sr.select(f, "a0"), [10])
        self.assertEqual(sr.select(f, "a"), [20])
        self.assertEqual(sr.select([10], "a"), [10])
        self.assertEqual(sr.select(f, "b"), [30])
        self.assertEqual(sr.select(f, "c"), [50])
        self.assertEqual(sr.select(f, "d"), [20, 50])
        self.assertEqual(sr.select([10, 20], "d"), [20])
        diffs = {20: 9.0, 30: 1.0, 40: 6.0, 50: 0.5}
        self.assertEqual(sr.select(f, "e", diffs, theta=5.0), [20, 40])
        self.assertEqual(sr.select(f, "all"), f)
        with self.assertRaises(ValueError):
            sr.select(f, "e")

    def test_thin_rows_keeps_coverage(self):
        rows = [{"kind": "coverage"}, {"kind": "row_observation", "frame_idx": 15},
                {"kind": "sample", "frame_idx": 30}]
        self.assertEqual(sr.thin_rows(rows, {15}), rows[:2])

    def test_youden_theta_separates(self):
        d = np.array([1.0, 1.5, 2.0, 8.0, 9.0, 10.0])
        y = np.array([False, False, False, True, True, True])
        theta, j = sr.youden_theta(d, y)
        self.assertTrue(2.0 <= theta < 8.0)
        self.assertAlmostEqual(j, 1.0)

    def test_split_is_fixed(self):
        self.assertEqual(sr.split("a06f04a0059f"), "dev")
        self.assertEqual(sr.split("043bafca271a"), "held")

    def test_field_changes(self):
        runs = [{"run": 0, "frames": [1, 2, 3]}, {"run": 1, "frames": [4]}]
        row = lambda k, d: {"kills": k, "deaths": 0, "assists": 0, "credits": 800,  # noqa: E731
                            "dim": d, "is_player": False, "display_row": 0}
        states = {1: None, 2: {("ally", "Jett"): row(0, False)},
                  3: {("ally", "Jett"): row(1, True)}, 4: {("ally", "Jett"): row(0, False)}}
        got = sr.field_changes(states, runs)
        self.assertEqual(got["openings_with_two_accepted"], 1)
        self.assertEqual((got["kills"], got["dim"], got["credits"], got["any"]), (1, 1, 0, 1))
        labels = sr.pair_labels(states, runs)
        self.assertEqual(labels, {2: True, 3: True})

    def test_variants_select_like_e(self):
        diffs = {20: 9.0, 30: 1.0, 40: 6.0, 50: 0.5}
        for v in sr.VARIANTS:
            self.assertEqual(sr.select([10, 20, 30, 40, 50], v, diffs, theta=5.0), [20, 40])

    def test_credit_bins_cover_the_credits_cell(self):
        from reticle import scoreboard as sb
        bins = sr.credit_bins()
        self.assertTrue(bins and bins == list(range(bins[0], bins[-1] + 1)))
        lo, hi = sr.credit_span()
        self.assertLessEqual(bins[0] / sr.NBINS, lo)
        self.assertGreaterEqual((bins[-1] + 1) / sr.NBINS, hi)

    def test_credit_match_by_overlap(self):
        c = {"t_start_ms": 100.0, "t_end_ms": 500.0}
        a = {"t_start_ms": 0.0, "t_end_ms": 150.0}
        b = {"t_start_ms": 200.0, "t_end_ms": 600.0}
        far = {"t_start_ms": 900.0, "t_end_ms": 950.0}
        self.assertIs(sr.credit_match(c, [a, b, far]), b)
        self.assertIsNone(sr.credit_match(c, [far]))

    def test_n_differ_counts_gains_apart(self):
        cmp_ = {"lineup": {"same": 2}, "credits": {"same": 5, "lost": 2, "gained": 3},
                "local_row": {"changed": 1}, "deaths": {"same": 4, "refusal_reason_changed": 1},
                "kd_bound": {"same": 3, "changed": 1}}
        got = sr.n_differ(cmp_)
        self.assertEqual((got["total"], got["lost"]), (2 + 3 + 1 + 1 + 1, 2 + 1 + 1))


class _FakeCap:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self):
        return (True, self.frames.pop(0)) if self.frames else (False, None)

    def release(self):
        pass


class TestWriteFramesRect(unittest.TestCase):
    def test_nonzero_rect_top_writes_board_rows(self):
        # Each crop row encodes its absolute frame row; a cache rect starting
        # at frame row 150 must still yield board_y()'s frame rows.
        y0, y1 = sr.board_y()
        top, h = 150, 1080 - 150
        rows = (np.arange(h) + top).astype(np.uint16)
        crop = np.zeros((h, 400, 3), np.uint8)
        crop[:, :, 0] = (rows & 255)[:, None]
        crop[:, :, 1] = (rows >> 8)[:, None]
        cache, cap = sr.CACHE, sr._cap
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "s.json").write_text(json.dumps({"rects": [[535, top, 400, h]]}))
            np.save(d / "s.idx.npy", np.array([[0.0, 7, 0, 0, 0], [500.0, 8, 0, 1, 0]]))
            out = d / "out"
            out.mkdir()
            try:
                sr.CACHE, sr._cap = d, (lambda p: _FakeCap([crop, crop]))
                names = sr._write_frames("s", {8}, "c", out)
            finally:
                sr.CACHE, sr._cap = cache, cap
            self.assertEqual(names, ["c_f8.png"])
            im = cv2.imread(str(out / names[0]))
        got = im[:, 0, 0].astype(int) + 256 * im[:, 0, 1].astype(int)
        self.assertEqual(im.shape[0], y1 - y0)
        self.assertEqual(int(got[0]), y0)
        self.assertEqual(int(got[-1]), y1 - 1)


class TestMigrateChecks(unittest.TestCase):
    """The migration's checks on a synthetic cache: a correct thinned copy
    passes `load_checks`, one whose record lost its old gate fails, and a
    swap restores the stored files exactly."""

    VERDICTS = ["absent", "absent", "present", "absent", "absent", "absent", "unreadable",
                "absent", "absent"]

    def setUp(self):
        from reticle.roi_cache import ffmpeg_path
        try:
            ffmpeg_path()
        except SystemExit:
            self.skipTest("ffmpeg not installed")

    def _cache(self, root: Path):
        from reticle.decode import Sample
        from reticle.profiles import get_profile
        from reticle.roi_cache import RoiCacheWriter, cache_dir, scoreboard_gate
        from reticle.version import SCOREBOARD_STRIP_VERSION
        strip = [{"scoreboard_strip_version": SCOREBOARD_STRIP_VERSION, "kind": "sample",
                  "frame_idx": 30 * i, "t_ms": 500.0 * i, "verdict": v}
                 for i, v in enumerate(self.VERDICTS)]
        man = {"session_id": "s1", "source_profile": "valorant-16x9",
               "source": {"width": 1920, "height": 1080, "content_key": "k1"}}
        old, _ = scoreboard_gate(strip, margin=1)
        rng = np.random.default_rng(3)
        w = RoiCacheWriter(root, man, get_profile("valorant-16x9"), "scoreboard", hz=2.0,
                           gate=old)
        for i in range(len(self.VERDICTS)):
            w.feed(Sample(frame_idx=30 * i, t_ms=500.0 * i,
                          frame=rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)))
        w.finish()
        return cache_dir(root, "scoreboard"), man, strip

    def test_load_checks_pass_a_true_copy_and_fail_a_lost_gate(self):
        from reticle.roi_cache import scoreboard_gate, thin_cache
        with tempfile.TemporaryDirectory() as tmp:
            src, man, strip = self._cache(Path(tmp))
            dst = Path(tmp) / "thinning"
            thin_cache(src, "s1", scoreboard_gate(strip)[0], dst, "test")
            got = sr.load_checks("s1", src, dst, man, strip)
            self.assertTrue(got["ok"], got)
            self.assertEqual((got["held"], got["dropped"]), (2, 4))
            self.assertEqual(got["refusal_dropped"], {"thinned_out": 4})
            self.assertEqual(got["refusal_outside_old_gate"], {"outside_gate": 3})
            rec = json.loads((dst / "s1.json").read_text(encoding="utf-8"))
            del rec["thinned"]["gate_before"]
            (dst / "s1.json").write_text(json.dumps(rec), encoding="utf-8")
            bad = sr.load_checks("s1", src, dst, man, strip)
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["refusal_dropped"], {"outside_gate": 4})

    def test_gate_core_ignores_only_the_rule_name(self):
        a = {"witness": "scoreboard_strip", "spans": [[0.0, 1.0]], "rule": "on+1"}
        self.assertEqual(sr._gate_core(a), sr._gate_core({k: v for k, v in a.items()
                                                          if k != "rule"}))
        self.assertNotEqual(sr._gate_core(a), sr._gate_core({**a, "spans": [[0.0, 2.0]]}))

    def test_swap_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src", Path(tmp) / "dst"
            src.mkdir()
            dst.mkdir()
            for n in ("s.json", "s.idx.npy", "s.r0.mkv"):
                (src / n).write_text("old " + n)
                (dst / n).write_text("new " + n)
            aside = sr._swap_in("s", src, dst)
            self.assertEqual((src / "s.json").read_text(), "new s.json")
            self.assertEqual((src / "s.json.pre-thin").read_text(), "old s.json")
            self.assertFalse(any(dst.iterdir()))
            for n in ("s.json", "s.idx.npy", "s.r0.mkv"):
                (src / n).unlink()
            sr._restore(aside)
            self.assertEqual(sorted(p.name for p in src.iterdir()),
                             ["s.idx.npy", "s.json", "s.r0.mkv"])
            self.assertEqual((src / "s.r0.mkv").read_text(), "old s.r0.mkv")


if __name__ == "__main__":
    unittest.main()
