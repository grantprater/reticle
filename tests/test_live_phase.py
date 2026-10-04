"""The ability pass's live-phase lookup on a session without a HUD stream.

A demo scanned with `--only ability --from cache` has no stored HUD reads;
the lookup reports the live phase unknown with a reason instead of
aborting the pass, and the readers store that reason in their heads.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from reticle import ability_icons as I
from reticle import ability_scan as A
from reticle import cli


class FakeStore:
    """A store holding no HUD rows; `read_hud` aborts as `Store.read_hud` does."""

    def __init__(self, root: Path, hud: bool = False, rounds: bool = False):
        self.root = root
        self.rounds = rounds
        if hud:
            p = self.hud_path("s", "d")
            p.parent.mkdir(parents=True)
            p.write_bytes(b"")

    def hud_path(self, sid, date):
        return self.root / "l1" / "hud" / sid / "hud.parquet"

    def read_hud(self, sid, date):
        if not self.hud_path(sid, date).is_file():
            raise SystemExit(f"no HUD reads for session {sid}")
        return "hud-table"

    def read_rounds(self, sid, date):
        return SimpleNamespace(to_pylist=lambda: []) if self.rounds else None


class LivePhaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_hud_stream_is_null_with_a_reason(self):
        phase_at, why = cli._live_phase_at(FakeStore(self.root), "s", "d")
        self.assertIsNone(phase_at)
        self.assertEqual(why, "no HUD stream")

    def test_no_hud_and_no_rounds_names_the_hud(self):
        phase_at, why = cli._live_phase_at(FakeStore(self.root, rounds=True), "s", "d")
        self.assertIsNone(phase_at)
        self.assertEqual(why, "no HUD stream")

    def test_hud_without_rounds_names_the_rounds(self):
        phase_at, why = cli._live_phase_at(FakeStore(self.root, hud=True), "s", "d")
        self.assertIsNone(phase_at)
        self.assertEqual(why, "no rounds stream")

    def test_hud_and_rounds_give_the_gametime_phase(self):
        gt = SimpleNamespace(game_time_at=lambda t: SimpleNamespace(
            phase="round_live" if t < 1000 else "buy"))
        store = FakeStore(self.root, hud=True, rounds=True)
        with mock.patch("reticle.gametime.build_session_gametime", return_value=gt) as b, \
                mock.patch("reticle.stalls.for_session", return_value=None):
            phase_at, why = cli._live_phase_at(store, "s", "d")
        self.assertIsNone(why)
        self.assertEqual(b.call_args.args[1], "hud-table")
        self.assertEqual(phase_at(0.0), "round_live")
        self.assertEqual(phase_at(2000.0), "buy")


class PhaseReasonHeadTest(unittest.TestCase):
    def _shape(self, phase_at, reason):
        floor = np.zeros((40, 40), bool)
        floor[5:35, 5:35] = True
        sgray = np.full((40, 40), 90.0)
        r = A.AbilityShapeReader(floor=floor, sgray=sgray, support=floor, box=(0, 0, 40, 40),
                                 phase_at=phase_at, phase_reason=reason)
        r.feed(SimpleNamespace(frame=np.full((40, 40, 3), 90, np.uint8), t_ms=0.0, frame_idx=0))
        return r

    def test_shape_heads_carry_the_reason_and_rows_a_null_phase(self):
        r = self._shape(None, "no HUD stream")
        gate = r.gate_events("s", "k")
        self.assertEqual(gate[0]["phase_reason"], "no HUD stream")
        self.assertIsNone(gate[1]["phase"])
        self.assertNotEqual(gate[1]["reason"], "not_live")
        self.assertEqual(r.shape_events("s", "k")[0]["phase_reason"], "no HUD stream")

    def test_shape_heads_omit_the_reason_where_the_phase_is_read(self):
        r = self._shape({0.0: "round_live"}.get, "ignored")
        gate = r.gate_events("s", "k")
        self.assertNotIn("phase_reason", gate[0])
        self.assertEqual(gate[1]["phase"], "round_live")

    def test_icon_head_carries_the_reason(self):
        z = np.zeros((40, 40), bool)
        rd = I.AbilityIconReader(slab=z, floor=z, sgray=np.zeros((40, 40)), box=(0, 0, 40, 40),
                                 phase_reason="no HUD stream")
        self.assertEqual(rd.events("s", "k")[0]["phase_reason"], "no HUD stream")
        rd = I.AbilityIconReader(slab=z, floor=z, sgray=np.zeros((40, 40)), box=(0, 0, 40, 40),
                                 phase_at=lambda t: "round_live", phase_reason="ignored")
        self.assertNotIn("phase_reason", rd.events("s", "k")[0])


if __name__ == "__main__":
    unittest.main()
