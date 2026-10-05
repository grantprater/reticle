"""The one-pass ingest: the primitives on `ingest`'s frame stride inside a
shared decode, and the gated crop sets decided in the pass from their
witness, written exactly as the stored-gate writer writes them."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from reticle import decode
from reticle.decode import Sample
from reticle.profiles import get_profile
from reticle.roi_cache import (LIVE_GATE_MAX_PENDING, KillfeedPanelLiveGate, RoiCacheWriter,
                               ScoreboardLiveGate, killfeed_panel_gate, refusal_path,
                               scoreboard_gate)


def _manifest(sid="s1", key="k1"):
    return {"session_id": sid, "source_profile": "valorant-16x9",
            "source": {"width": 1920, "height": 1080, "content_key": key}}


def _needs_ffmpeg(test):
    from reticle.roi_cache import ffmpeg_path
    try:
        ffmpeg_path()
    except SystemExit:
        test.skipTest("ffmpeg not installed")


class _FakeCapture:
    """A variable-rate capture: frame i at a jittered time, its pixels its index."""

    def __init__(self, times_ms):
        self.t, self.i = list(times_ms), -1

    def isOpened(self):
        return True

    def grab(self):
        self.i += 1
        return self.i < len(self.t)

    def retrieve(self):
        return True, np.full((4, 4, 3), self.i % 256, np.uint8)

    def get(self, prop):
        return self.t[self.i]

    def release(self):
        pass


def _vfr_times(n=600, fps=60.0, seed=1):
    rng = np.random.default_rng(seed)
    step = 1000.0 / fps
    return np.cumsum(np.r_[step, step + rng.uniform(-6.0, 6.0, n - 1)]).tolist()


class FrameStrideTest(unittest.TestCase):
    """A stride reader in `sample_multi` takes the frames `sample_frames`
    takes, and leaves every other reader's frames as they were alone."""

    def test_stride_reader_matches_sample_frames_and_moves_no_other_reader(self):
        times = _vfr_times()
        with mock.patch.object(decode, "open_capture", lambda p: _FakeCapture(times)):
            alone = [(s.frame_idx, s.t_ms) for s in decode.sample_frames("x", 5.0, 60.0)]
            hud_alone = [(s.frame_idx, s.t_ms) for _w, s in
                         decode.sample_multi("x", 60.0, {"hud": (2.0, None)})]
            got = {"primitives": [], "hud": []}
            for who, s in decode.sample_multi("x", 60.0, {"primitives": (5.0, None),
                                                          "hud": (2.0, None)},
                                              strides={"primitives": decode.frame_stride(60.0, 5.0)}):
                for name in who:
                    got[name].append((s.frame_idx, s.t_ms))
        self.assertEqual(got["primitives"], alone)
        self.assertEqual(got["hud"], hud_alone)
        self.assertEqual([f for f, _ in alone], list(range(0, 600, 12)))
        # On this jittered timeline a timestamp stride picks other frames, the
        # reason the stride is by decode index.
        with mock.patch.object(decode, "open_capture", lambda p: _FakeCapture(times)):
            by_time = [s.frame_idx for _w, s in
                       decode.sample_multi("x", 60.0, {"primitives": (5.0, None)})]
        self.assertNotEqual(by_time, [f for f, _ in alone])

    def test_a_stride_reader_reads_the_whole_capture(self):
        with self.assertRaises(ValueError):
            list(decode.sample_multi("x", 60.0, {"p": (5.0, [(0.0, 10.0)])}, strides={"p": 12}))


class _FakeKillfeed:
    """The killfeed reader's surface the live gate reads: rows appended
    while a sample is fed, and the stored stream built from them."""

    def __init__(self, killers_at):
        self.rows, self.killers_at = [], set(killers_at)

    def feed(self, smp):
        if smp.t_ms in self.killers_at:
            self.rows.append({"frame_idx": smp.frame_idx, "t_ms": float(smp.t_ms), "slot": 0,
                              "role": "killer"})
        self.rows.append({"frame_idx": smp.frame_idx, "t_ms": float(smp.t_ms), "slot": 1,
                          "role": "victim"})

    def events(self, sid):
        common = {"session_id": sid, "source": "killfeed",
                  "killfeed_portrait_version": "killfeed-portrait-test"}
        return [{**common, "kind": "coverage"}] + [
            {**common, "kind": "portrait_observation", **r} for r in self.rows]


def _frames(n, seed=5):
    rng = np.random.default_rng(seed)
    times = np.round(np.cumsum(np.r_[0.0, 500.0 + rng.uniform(-17, 17, n - 1)]), 3)
    return [Sample(frame_idx=30 * i, t_ms=float(t),
                   frame=rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8))
            for i, t in enumerate(times)]


def _cache_files(root, name, sid="s1"):
    """Each stored file's bytes; an FFV1 video as its decoded frames, since
    Matroska stamps every file with a random segment id."""
    import cv2
    d = Path(root) / "roi_cache" / name / "roi-cache-0.1.0"
    out = {}
    for p in sorted(d.glob(f"{sid}*")):
        if p.suffix == ".mkv":
            cap, frames = cv2.VideoCapture(str(p)), []
            while True:
                ok, f = cap.read()
                if not ok:
                    break
                frames.append(f.tobytes())
            cap.release()
            out[p.name] = frames
        elif p.is_file():
            out[p.name] = p.read_bytes()
    return out


class LiveGateEqualsStoredGateTest(unittest.TestCase):
    """The gated writer fed in the pass stores the files the stored-gate
    writer stores after it: index, record and video, byte for byte."""

    def _stored_then_live(self, name, frames, witness_feed, stored_gate, live_gate):
        profile, man = get_profile("valorant-16x9"), _manifest()
        out = []
        for gate, live in ((stored_gate, None), (None, live_gate)):
            with tempfile.TemporaryDirectory() as root:
                w = RoiCacheWriter(Path(root), man, profile, name, hz=2.0, gate=gate,
                                   live_gate=live)
                for s in frames:
                    if live is not None:
                        witness_feed(s)
                    w.feed(s)
                w.finish()
                self.assertIsNone(w.refused)
                out.append(_cache_files(root, name))
        return out

    def test_killfeed_panel(self):
        _needs_ffmpeg(self)
        frames = _frames(24)
        killers = {frames[i].t_ms for i in (3, 4, 11, 23)}
        stored = _FakeKillfeed(killers)
        for s in frames:
            stored.feed(s)
        gate, why = killfeed_panel_gate(stored.events("s1"), 2.0)
        self.assertIsNone(why)
        live_kp = _FakeKillfeed(killers)
        a, b = self._stored_then_live("killfeed_panel", frames, live_kp.feed, gate,
                                      KillfeedPanelLiveGate(live_kp, 2.0, "s1"))
        self.assertEqual(sorted(a), sorted(b))
        self.assertEqual(a, b)
        rec = json.loads(b["s1.json"])
        # Samples 2-5, 10-12 and 22-23: one sample either side of each entry.
        self.assertEqual((rec["frames"], rec["frames_offered"]), (9, 24))

    def test_scoreboard(self):
        _needs_ffmpeg(self)
        frames = _frames(16, seed=7)
        on = {frames[i].t_ms for i in (2, 3, 9, 15)}
        verdict = lambda crop, rect, t: {"verdict": "present" if t in on else "absent",
                                         "reason": None}
        rect = [883, 486, 1037, 594]
        reads = [(s.frame_idx, s.t_ms, verdict(None, None, s.t_ms)) for s in frames]
        from reticle.scoreboard_strip import strip_events
        gate, why = scoreboard_gate(strip_events("s1", reads, rect, "roi-cache-0.1.0"))
        self.assertIsNone(why)
        live = ScoreboardLiveGate(rect, "s1")
        # The strip verdict stands in for `read_strip`, keyed on the sample
        # the gate is observing.
        current = {}
        observe = live.observe

        def observing(s):
            current["t"] = s.t_ms
            observe(s)
        live.observe = observing
        with mock.patch("reticle.scoreboard_strip.read_strip",
                        lambda crop, r: verdict(crop, r, current["t"])):
            a, b = self._stored_then_live("scoreboard", frames, lambda s: None, gate, live)
        self.assertEqual(a, b)
        self.assertEqual(json.loads(b["s1.json"])["frames"], 4)


class LiveGateRefusalTest(unittest.TestCase):

    def test_past_the_bound_the_set_is_refused_with_its_reason_stored(self):
        _needs_ffmpeg(self)

        class Never:
            witness = "never"

            def observe(self, smp):
                pass

            def decide(self, i, t, final=False):
                return None if not final else True

            def gate(self):
                return None, "unused"

        profile, man = get_profile("valorant-16x9"), _manifest()
        frames = _frames(LIVE_GATE_MAX_PENDING + 3)
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "killfeed_panel", hz=2.0,
                               live_gate=Never())
            for s in frames:
                w.feed(s)
            w.finish()
            self.assertTrue(w.refused.startswith("pending_bound"))
            files = _cache_files(root, "killfeed_panel")
            self.assertEqual(list(files), ["s1.refused.json"])
            rec = json.loads(files["s1.refused.json"])
            self.assertTrue(rec["refused"].startswith("pending_bound"))
            self.assertEqual(rec["frames_offered"], LIVE_GATE_MAX_PENDING + 1)
            self.assertEqual(refusal_path(Path(root), "s1", "killfeed_panel").name,
                             "s1.refused.json")

    def test_a_decision_the_final_gate_contradicts_refuses_the_set(self):
        _needs_ffmpeg(self)
        frames = _frames(6)
        kp = _FakeKillfeed({frames[2].t_ms})
        live = KillfeedPanelLiveGate(kp, 2.0, "s1")
        live.decide = lambda i, t, final=False: True          # keeps everything
        profile, man = get_profile("valorant-16x9"), _manifest()
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "killfeed_panel", hz=2.0,
                               live_gate=live)
            for s in frames:
                kp.feed(s)
                w.feed(s)
            w.finish()
            self.assertTrue(w.refused.startswith("gate_mismatch: 3 of 6"))
            self.assertEqual(list(_cache_files(root, "killfeed_panel")), ["s1.refused.json"])

    def test_a_live_gate_takes_no_spans_and_no_stored_gate(self):
        profile, man = get_profile("valorant-16x9"), _manifest()
        with tempfile.TemporaryDirectory() as root:
            for kw in ({"spans": [(0.0, 1.0)]}, {"gate": {"spans": []}}):
                with self.assertRaises(ValueError):
                    RoiCacheWriter(Path(root), man, profile, "killfeed_panel", hz=2.0,
                                   live_gate=object(), **kw)


class GateCheckTest(unittest.TestCase):

    def test_the_command_fails_where_the_stored_witness_gives_another_gate(self):
        from reticle.cli import _check_live_gates
        from reticle.store import Store
        _needs_ffmpeg(self)
        frames = _frames(6)
        kp = _FakeKillfeed({frames[2].t_ms})
        for s in frames:
            kp.feed(s)
        profile, man = get_profile("valorant-16x9"), _manifest()
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            gate, _ = killfeed_panel_gate(kp.events("s1"), 2.0)
            w = RoiCacheWriter(Path(root), man, profile, "killfeed_panel", hz=2.0, gate=gate)
            for s in frames:
                w.feed(s)
            w.finish()
            store.write_events("killfeed_portrait", "s1", kp.events("s1"))
            self.assertEqual(_check_live_gates(store, "s1", ["killfeed_panel"], 2.0), 0)
            other = _FakeKillfeed({frames[4].t_ms})
            for s in frames:
                other.feed(s)
            store.write_events("killfeed_portrait", "s1", other.events("s1"))
            self.assertEqual(_check_live_gates(store, "s1", ["killfeed_panel"], 2.0), 1)


if __name__ == "__main__":
    unittest.main()
