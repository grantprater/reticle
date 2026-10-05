"""The combat report crop cache: the reader's region, one frame per round
named by the owner of the panels' rounds, and read back by the reader with a
refusal at each frame the set dropped."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle import combat_report as cr
from reticle.adjudication import combat_report as adj
from reticle.decode import Sample
from reticle.profiles import get_profile
from reticle.roi_cache import (RoiCache, RoiCacheWriter, cache_for, combat_report_gate,
                               roi_rects, unheld_frames)
from reticle.version import COMBAT_REPORT_FRAMES_VERSION


def _manifest(sid="s1", key="k1"):
    return {"session_id": sid, "source_profile": "valorant-16x9",
            "source": {"width": 1920, "height": 1080, "content_key": key}}


def _needs_ffmpeg(test):
    from reticle.roi_cache import ffmpeg_path
    try:
        ffmpeg_path()
    except SystemExit:
        test.skipTest("ffmpeg not installed")


def _rows(headers, hz=1.0, version="combat-report-test"):
    """A stored combat_report stream: a coverage row, then a frame per
    header score at `hz` from 0 ms."""
    common = {"session_id": "s1", "source": "combat_report", "combat_report_version": version}
    step = 1000.0 / hz
    return [{**common, "kind": "coverage", "hz": hz}] + [
        {**common, "kind": "frame", "frame_idx": i * 60, "t_ms": i * step, "header": h,
         "reason": None} for i, h in enumerate(headers)]


def _row(out, inc, killed=False, killed_you=False, hits="010"):
    """One panel row as the reader stores it."""
    return {"out": {"text": out}, "in": {"text": inc}, "out_hits": {"text": hits},
            "in_hits": {"text": "100"},
            "out_word": {"KILLED": 0.9 if killed else 0.1, "KILLED YOU": 0.0, "ASSIST": 0.0},
            "in_word": {"KILLED": 0.0, "KILLED YOU": 0.9 if killed_you else 0.1, "ASSIST": 0.0},
            "slot_word": {"ALLY": 0.0}, "portrait": None, "band": None}


def _frame_row(t, rows=None, hy=400):
    """A stored frame: the panel shown with `rows`, or no panel."""
    r = {"session_id": "s1", "source": "combat_report", "combat_report_version": "t",
         "kind": "frame", "frame_idx": int(t // 1000 * 60), "t_ms": float(t), "hx": 1600,
         "hy": hy, "reason": None}
    if rows is None:
        return {**r, "header": 0.2}
    return {**r, "header": 0.95, "rows": rows}


#: Three rounds with the bounds the rounds owner stores.
ROUNDS = [
    {"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 56000.0, "t_close_ms": 69500.0,
     "player_kills": 0, "player_deaths": 1},
    {"round_no": 2, "t_start_ms": 69500.0, "t_end_ms": 123500.0, "t_close_ms": 128000.0,
     "player_kills": 1, "player_deaths": 0},
    {"round_no": 3, "t_start_ms": 128000.0, "t_end_ms": 232000.0, "t_close_ms": 239000.0,
     "player_kills": 0, "player_deaths": 0},
]
DEATHS = [20000.0]


def _session_rows():
    """Round 1: the player dies at 20 s; the panel shows from then through
    the round's end (56 s) into round 2's buy phase, one frame at 30 s
    misreading a hit count. Round 2, survived: its summary shows for two
    frames in round 3's buy phase. Round 3: no panel."""
    died = [_row("150", "140", killed_you=True)]
    out = []
    for t in range(0, 240000, 1000):
        if 20000 <= t <= 80000:
            rows = ([_row("150", "140", killed_you=True, hits="020")] if t == 30000 else died)
            out.append(_frame_row(t, rows, hy=400 if t < 56000 else 300))
        elif t in (130000, 131000):
            out.append(_frame_row(t, [_row("200", "0", killed=True), _row("45", "0")], hy=380))
        else:
            out.append(_frame_row(t))
    return out


class ReaderRoiTest(unittest.TestCase):

    def test_the_set_is_the_readers_own_region(self):
        profile = get_profile("valorant-16x9")
        self.assertEqual(roi_rects("combat_report", profile, (1920, 1080)),
                         [cr.reader_roi((1920, 1080))])
        self.assertEqual(cr.reader_roi((1920, 1080)), [1176, 120, 1920, 1080])
        with self.assertRaises(ValueError):
            cr.reader_roi((2560, 1440))

    def test_every_read_stays_inside_it(self):
        """The reader reads the same rows from a frame blacked outside the
        region as from the whole frame, with the header at the corners of
        its search."""
        from reticle.ocr import Templates
        digits = Templates.load("valorant-16x9")
        x0, y0, x1, y1 = cr.reader_roi((1920, 1080))
        th, tw = cr.load_templates()[0].shape
        rng = np.random.default_rng(3)
        for hx, hy in ((cr.SEARCH[0], cr.SEARCH[1]), (cr.SEARCH[2] - tw, cr.SEARCH[3] - th),
                       (cr.SEARCH[0], cr.SEARCH[3] - th), (1500, 400)):
            frame = _panel_frame(rng, hx, hy)
            black = np.zeros_like(frame)
            black[y0:y1, x0:x1] = frame[y0:y1, x0:x1]
            a, b = cr.CombatReportReader(digits), cr.CombatReportReader(digits)
            a.feed(Sample(frame_idx=0, t_ms=0.0, frame=frame))
            b.feed(Sample(frame_idx=0, t_ms=0.0, frame=black))
            self.assertGreaterEqual(a.rows[0]["header"], cr.READ_MIN)
            self.assertEqual(a.rows, b.rows)


class RoundFramesTest(unittest.TestCase):
    """One frame per round: the most complete panel, from inside a run of
    frames that read the same, checked to give every round its verdict."""

    def test_one_frame_per_round_the_summary_inside_a_stable_run(self):
        got = adj.round_frames(_session_rows(), ROUNDS, DEATHS)
        self.assertEqual([g["round_no"] for g in got], [1, 2, 3])
        one, two, three = got
        # Round 1: the summary, the first frame at the round's end whose
        # neighbours both read the same.
        self.assertEqual((one["t_ms"], one["stability"], one["shown"], one["rows"]),
                         (56000.0, "interior", "summary", 1))
        # Round 2: two frames only, so the earlier of the pair.
        self.assertEqual((two["t_ms"], two["stability"], two["shown"], two["rows"]),
                         (130000.0, "pair", "summary", 2))
        self.assertTrue(one["reproduces"] and two["reproduces"])
        self.assertEqual((three["t_ms"], three["reason"]), (None, "no panel shown for this round"))

    def test_the_kept_frames_alone_give_every_round_its_verdict(self):
        rows = _session_rows()
        got = adj.round_frames(rows, ROUNDS, DEATHS)
        kept = [r for r in rows if r["t_ms"] in {g["t_ms"] for g in got}]
        self.assertEqual(len(kept), 2)
        verdict = lambda frames: adj.round_verdicts(adj.events("s1", [
            {**r, "combat_report_version": adj.COMBAT_REPORT_VERSION} for r in frames],
            ROUNDS, DEATHS), ROUNDS)
        self.assertEqual(verdict(kept), verdict(rows))
        self.assertEqual(verdict(kept)["rounds"][1]["deaths"], 1)

    def test_a_frame_that_misreads_is_never_kept(self):
        rows = _session_rows()
        # Every frame from the round's end on misreads but the one at 60 s;
        # the frozen death panel keeps a frame before the misreads.
        bad = [_row("150", "140", killed_you=True, hits="020")]
        rows = [{**r, "rows": bad} if 56000 <= r["t_ms"] <= 80000 and r["t_ms"] != 60000 else r
                for r in rows]
        one = adj.round_frames(rows, ROUNDS, DEATHS)[0]
        self.assertEqual((one["t_ms"], one["stability"], one["shown"]),
                         (21000.0, "interior", "in_round"))
        self.assertTrue(one["reproduces"])

    def test_no_panel_keeps_nothing(self):
        got = adj.round_frames([_frame_row(t) for t in range(0, 240000, 1000)], ROUNDS, DEATHS)
        self.assertEqual([g["t_ms"] for g in got], [None, None, None])
        self.assertTrue(all(g["reason"] for g in got))


    def test_a_round_whose_report_changed_keeps_a_frame_per_read(self):
        """Two deaths in round 1 (a revive): a one-row death panel at 20 s,
        then a two-row one at 40 s through the round's end. One frame of the
        second would lose the first panel's row."""
        first = [_row("150", "140", killed_you=True)]
        second = [_row("150", "140", killed_you=True), _row("90", "120", killed_you=True)]
        rows = []
        for t in range(0, 240000, 1000):
            if 20000 <= t <= 26000:
                rows.append(_frame_row(t, first))
            elif 40000 <= t <= 80000:
                rows.append(_frame_row(t, second, hy=400 if t < 56000 else 300))
            else:
                rows.append(_frame_row(t))
        got = [g for g in adj.round_frames(rows, ROUNDS, [20000.0, 40000.0]) if g["round_no"] == 1]
        self.assertEqual([(g["t_ms"], g["rows"], g["reads"]) for g in got],
                         [(21000.0, 1, 2), (56000.0, 2, 2)])
        self.assertTrue(all(g["reproduces"] for g in got))

    def test_a_round_whose_panels_read_alike_keeps_one(self):
        got = [g for g in adj.round_frames(_session_rows(), ROUNDS, DEATHS) if g["round_no"] == 1]
        self.assertEqual([(g["t_ms"], g["reads"]) for g in got], [(56000.0, 1)])


def _reread(rows, keep):
    """The stream `scan --only combat_report --from cache` stores from a set
    holding `keep`: those frames as read, a `thinned_out` refusal at every
    other, and the set named in the head (`CombatReportReader.events`)."""
    head = {"kind": "coverage", "hz": 1.0, "cache_set": "combat_report",
            "cache_gate": {"rule": "one_per_round"}, "frames_refused": len(rows) - len(keep)}
    return [head] + [r if r["t_ms"] in keep else
                     {**{k: r[k] for k in ("kind", "frame_idx", "t_ms")},
                      "header": None, "reason": "thinned_out"} for r in rows]


class ThinnedStreamTest(unittest.TestCase):
    """The kept frames give each round its counts, not the death panel's
    timing: its consumers refuse a reread stream rather than read it."""

    def setUp(self):
        self.rows = _session_rows()
        keep = {g["t_ms"] for g in adj.round_frames(self.rows, ROUNDS, DEATHS)}
        self.thin = _reread(self.rows, keep)

    def test_the_full_stream_is_not_thinned(self):
        self.assertIsNone(adj.thinned(self.rows))
        self.assertGreater(len(adj.death_panel_tops(self.rows)[0]), 30)

    def test_death_panel_tops_and_panel_aside_refuse(self):
        from reticle.adjudication.death import panel_aside
        why = adj.thinned(self.thin)
        self.assertIn("thinned", why)
        # Without the head, the refusals alone mark it.
        self.assertIsNotNone(adj.thinned(self.thin[1:]))
        with self.assertRaises(ValueError):
            adj.death_panel_tops(self.thin)
        times = [float(t) for t in range(0, 240000, 500)]
        self.assertIsNone(panel_aside(times, self.thin, 200.0))
        self.assertIsNotNone(panel_aside(times, [{"kind": "coverage", "hz": 1.0}] + self.rows,
                                         200.0))

    def test_row_naming_reads_and_writes_nothing(self):
        from reticle import cli

        class NoStore:
            def __getattr__(self, name):
                raise AssertionError(f"identity touched the store: {name}")
        cli._combat_report_identity(NoStore(), "s1", "2026-10-05", self.thin, ROUNDS, DEATHS)

    def test_the_round_counts_still_reproduce(self):
        verdict = lambda frames: adj.round_verdicts(adj.events("s1", [
            {**r, "combat_report_version": adj.COMBAT_REPORT_VERSION} for r in frames],
            ROUNDS, DEATHS), ROUNDS)
        self.assertEqual(verdict(self.thin[1:]), verdict(self.rows))


class AssignRoundsTest(unittest.TestCase):

    def test_a_summary_in_the_first_round_beside_an_unassigned_panel(self):
        """A summary that opens early in the first round has no previous
        round; a later panel not yet assigned has no kind. This raised
        KeyError before combat-report-frames-0.2.0."""
        row = {"out": "10", "in": "0", "killed_you": False}
        ps = [{"start_ms": 5000.0, "at_death": False, "rows": [row]},
              {"start_ms": 30000.0, "at_death": True, "rows": [row]}]
        adj.assign_rounds(ps, ROUNDS)
        self.assertEqual([(p["round_no"], p["kind"]) for p in ps], [(None, "summary"), (1, "death")])


class GateTest(unittest.TestCase):

    def test_the_gate_holds_the_named_frames_and_the_choice(self):
        choice = [{"round_no": 1, "t_ms": 2000.0}, {"round_no": 2, "t_ms": None, "reason": "x"},
                  {"round_no": 3, "t_ms": 6000.0}]
        gate, why = combat_report_gate(choice, _rows([0.1] * 9), 1.0)
        self.assertIsNone(why)
        self.assertEqual(gate["spans"], [[1750.0, 2250.0], [5750.0, 6250.0]])
        self.assertEqual((gate["rule"], gate["version"], gate["refuse_as"], gate["samples"],
                          gate["witness_samples"], gate["witness_version"]),
                         ("one_per_round", COMBAT_REPORT_FRAMES_VERSION, "thinned_out", 2, 9,
                          "combat-report-test"))
        self.assertEqual(gate["rounds"], choice)

    def test_no_rows_is_no_gate(self):
        self.assertIn("no stored", combat_report_gate([], [], 1.0)[1])


CHOICE = [{"round_no": 1, "t_ms": 2000.0}, {"round_no": 2, "t_ms": None, "reason": "x"},
          {"round_no": 3, "t_ms": 6000.0}]


class WriterRoundTripTest(unittest.TestCase):

    def _frames(self, n=10):
        rng = np.random.default_rng(7)
        return [Sample(frame_idx=i * 60, t_ms=i * 1000.0,
                       frame=rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8))
                for i in range(n)]

    def test_the_set_holds_one_frame_per_round_bit_for_bit(self):
        _needs_ffmpeg(self)
        profile, man = get_profile("valorant-16x9"), _manifest()
        frames = self._frames()
        gate, _ = combat_report_gate(CHOICE, _rows([0.1] * 10), 1.0)
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "combat_report", hz=1.0, gate=gate)
            w.recheck = lambda: {"same_frame": 2}
            for smp in frames:
                w.feed(smp)
            w.finish()
            cache, why = RoiCache.load(Path(root), man, profile, "combat_report")
            self.assertIsNone(why)
            self.assertEqual(cache.holds(), [2000.0, 6000.0])
            x0, y0, x1, y1 = cache.stored_rect("combat_report")
            by_t = {s.t_ms: s for s in frames}
            for smp in cache.samples(cache.holds()):
                want = by_t[smp.t_ms]
                self.assertEqual(smp.frame_idx, want.frame_idx)
                self.assertTrue(np.array_equal(smp.frame[y0:y1, x0:x1],
                                               want.frame[y0:y1, x0:x1]))
                self.assertFalse(smp.frame[:y0].any() or smp.frame[:, :x0].any())
            self.assertEqual(cache.refusal(3000.0), "thinned_out")
            self.assertIsNone(cache.refusal(2000.0))
            self.assertEqual(cache.offered()[:, 0].tolist(), [s.t_ms for s in frames])
            self.assertEqual([u[2] for u in unheld_frames(cache)], ["thinned_out"] * 8)
            self.assertEqual([u[0] for u in unheld_frames(cache)],
                             [0.0, 1000.0, 3000.0, 4000.0, 5000.0, 7000.0, 8000.0, 9000.0])
            self.assertEqual(cache.record["gate"]["rounds"], CHOICE)
            self.assertEqual(cache.record["gate_recheck"], {"same_frame": 2})
            self.assertEqual((cache.record["frames"], cache.record["frames_offered"]), (2, 10))

    def test_a_named_frame_the_pass_never_offered_fails(self):
        _needs_ffmpeg(self)
        profile, man = get_profile("valorant-16x9"), _manifest()
        gate, _ = combat_report_gate([{"round_no": 1, "t_ms": 2500.0}], _rows([0.1] * 4), 1.0)
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "combat_report", hz=1.0, gate=gate)
            for smp in self._frames(4):
                w.feed(smp)
            with self.assertRaises(RuntimeError):
                w.finish()
            # Nothing is stored: no record, no video.
            self.assertEqual(list(Path(root).glob("roi_cache/**/s1.*")), [])


def _panel_frame(rng, hx, hy):
    """A noisy 1080p frame with the COMBAT REPORT header pasted at (hx, hy)
    and bright digit-like bars in the first row's damage fields."""
    frame = rng.integers(0, 60, (1080, 1920, 3), dtype=np.uint8)
    if hx is None:
        return frame
    header, _words = cr.load_templates()
    h, w = header.shape
    frame[hy:hy + h, hx:hx + w] = header[..., None]
    for box in (cr.OUT_NUM, cr.IN_NUM):
        x0, y0, _x1, _y1 = box
        ys, xs = hy + cr.ROW0 + y0 + 8, hx + x0 + 6
        for k in range(3):
            frame[ys:ys + 22, xs + 14 * k:xs + 14 * k + 8] = 230
    return frame


class ReaderFromCacheTest(unittest.TestCase):
    """`--from cache` feeds the reader the set's frames; it stores the rows
    the video gave on those frames and a refusal at every other one."""

    def test_rows_from_the_set_equal_rows_from_video(self):
        _needs_ffmpeg(self)
        from reticle.ocr import Templates
        from reticle.passes import run_cached
        digits = Templates.load("valorant-16x9")
        profile, man = get_profile("valorant-16x9"), _manifest()
        rng = np.random.default_rng(11)
        where = [None, None, (1400, 300), (1402, 300), None, None, None, (1500, 500), None]
        frames = [Sample(frame_idx=i * 60, t_ms=i * 1000.0,
                         frame=_panel_frame(rng, *(p or (None, None))))
                  for i, p in enumerate(where)]
        video = cr.CombatReportReader(digits)
        for smp in frames:
            video.feed(smp)
        stored = video.events("s1")
        choice = [{"round_no": 1, "t_ms": 3000.0}, {"round_no": 2, "t_ms": 7000.0}]
        gate, _ = combat_report_gate(choice, stored, 1.0)
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "combat_report", hz=1.0, gate=gate)
            for smp in frames:
                w.feed(smp)
            w.finish()
            again = cr.CombatReportReader(digits)
            # A gated set feeds only `--from cache`, and only a reader that refuses.
            cache, why = cache_for(Path(root), man, profile, [again])
            self.assertIsNone(cache)
            self.assertIn("gate kept", why)
            cache, why = cache_for(Path(root), man, profile, [again], gated_ok=True)
            self.assertIsNotNone(cache, why)
            again.refuse_unheld(cache.record, unheld_frames(cache))
            run_cached(None, [again], cache)
            rows = again.events("s1")
        self.assertEqual((rows[0]["frames"], rows[0]["frames_refused"], rows[0]["cache_set"]),
                         (len(frames), 7, "combat_report"))
        self.assertEqual(rows[0]["cache_gate"]["rounds"], choice)
        for a, b in zip(stored[1:], rows[1:]):
            self.assertEqual(a["t_ms"], b["t_ms"])
            if a["t_ms"] in (3000.0, 7000.0):
                self.assertEqual(a, b)
                self.assertGreaterEqual(b["header"], cr.READ_MIN)
            else:
                self.assertEqual((b["header"], b["reason"], b["frame_idx"]),
                                 (None, "thinned_out", a["frame_idx"]))


if __name__ == "__main__":
    unittest.main()
