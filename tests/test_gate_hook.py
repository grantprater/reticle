"""The per-frame gate hook in `passes` (BACKLOG item 1) and the ally gate.

A refused frame is a recorded non-read with a reason, is never retrieved or
fetched, and is never fed; audit frames are read whatever the gate says and
stored apart; the gate is asked only after every earlier read was fed back.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from reticle import passes
from reticle.ally_gate import AllyGate, teammate_fits
from reticle.decode import sample_multi
from reticle.minimap import AllyIconReader
from reticle.passes import GateDecision, GateLog, gate_decide, run, run_cached
from reticle.ratchets import Audit, Gate
from reticle.slot_state import GateBelief

AUDIT = Audit(every_ms=10_000.0, window_ms=1_000.0, phase_ms=4_000.0)


class Cap:
    """A capture of `frames` frames at `step` ms that counts retrieves."""

    def __init__(self, frames=40, step=500.0):
        self.frames, self.step, self.i = frames, step, -1
        self.retrieved: list[float] = []

    def isOpened(self): return True

    def grab(self):
        self.i += 1
        return self.i < self.frames

    def get(self, prop): return self.i * self.step

    def retrieve(self):
        self.retrieved.append(self.i * self.step)
        return True, np.zeros((1, 1, 3), dtype=np.uint8)

    def release(self): pass


def _opened(cap):
    """Open `cap` for `sample_multi` with no backend record."""
    from contextlib import ExitStack
    st = ExitStack()
    st.enter_context(patch("reticle.decode.open_capture", return_value=cap))
    st.enter_context(patch("reticle.decode.capture_backend", return_value={}))
    return st


class Gated:
    """A frame-gated reader: its gate opens on whole seconds only, and logs
    every call in order with the feeds and feedbacks."""

    opportunity_gate = Gate("o", "s", "frame", "test-gate-0", AUDIT)

    def __init__(self, name="gated", hz=2.0, spans=None, opens=None):
        self.name, self.hz, self.spans = name, hz, spans
        self.frame_gate = object()
        self.opens = opens or (lambda t: t % 1000.0 == 0.0)
        self.calls: list[tuple[str, float]] = []
        self.fed: list[float] = []

    def wants(self, t_ms):
        self.calls.append(("wants", t_ms))
        return (self.opens(t_ms), "open" if self.opens(t_ms) else "half_second")

    def observed(self, t_ms):
        self.calls.append(("observed", t_ms))

    def feed(self, smp):
        self.calls.append(("feed", smp.t_ms))
        self.fed.append(smp.t_ms)


class Plain:
    def __init__(self, name="plain", hz=2.0, spans=None):
        self.name, self.hz, self.spans = name, hz, spans
        self.fed: list[float] = []

    def feed(self, smp):
        self.fed.append(smp.t_ms)


class DecodeHookTests(unittest.TestCase):
    def test_a_refused_instant_is_never_retrieved(self):
        cap = Cap()
        asked = []
        with patch("reticle.decode.cv2.VideoCapture", return_value=cap):
            rows = list(sample_multi("x", 2.0, {"g": (2.0, None)},
                                     gates={"g": lambda t: asked.append(t) or t % 1000.0 == 0.0}))
        self.assertEqual(len(asked), 40)
        self.assertEqual([s.t_ms for _w, s in rows], [t for t in asked if t % 1000.0 == 0.0])
        self.assertEqual(cap.retrieved, [s.t_ms for _w, s in rows])

    def test_another_reader_still_gets_the_frame(self):
        cap = Cap(frames=6)
        with patch("reticle.decode.cv2.VideoCapture", return_value=cap):
            rows = list(sample_multi("x", 2.0, {"g": (2.0, None), "p": (2.0, None)},
                                     gates={"g": lambda t: False}))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(w == frozenset({"p"}) for w, _s in rows))


class RunHookTests(unittest.TestCase):
    def _run(self, frames=40):
        g, p = Gated(), Plain()
        cap = Cap(frames=frames)
        with _opened(cap):
            run(SimpleNamespace(media="x", fps=2.0), [g, p])
        return g, p, cap

    def test_refusals_are_recorded_never_fed(self):
        g, p, cap = self._run()
        offered = [i * 500.0 for i in range(40)]
        self.assertEqual(p.fed, offered)
        audit = [t for t in offered if AUDIT.covers(t, 0.0)]
        expect = sorted({t for t in offered if t % 1000.0 == 0.0} | set(audit))
        self.assertEqual(g.fed, expect)
        log = g.gate_log
        refused = [t for t in offered if t % 1000.0 != 0.0]
        self.assertEqual(log.summary()["refused"], len(refused))
        self.assertEqual(log.summary()["refused_reasons"], {"half_second": len(refused)})
        rows = log.unread_rows()
        self.assertEqual(sum(r["frames"] for r in rows), len(refused))
        self.assertTrue(all(r["kind"] == "unread" and r["reason"] == "half_second"
                            and r["gate_version"] == "test-gate-0" for r in rows))
        self.assertEqual(log.audit_t, audit)

    def test_the_gate_is_asked_after_the_last_read_fed_back(self):
        g, _p, _cap = self._run(frames=8)
        seq = [c for c in g.calls]
        # every wants at t follows the feed (and feedback) of each earlier read
        for i, (what, t) in enumerate(seq):
            if what == "wants":
                earlier = [x for w, x in seq[:i] if w == "feed"]
                self.assertTrue(all(x < t for x in earlier))
        fed = [t for w, t in seq if w == "feed"]
        back = [t for w, t in seq if w == "observed"]
        # an audit-only read is fed but never fed back to the gate's belief
        self.assertEqual(back, [t for t in fed if t % 1000.0 == 0.0])

    def test_an_unbound_gate_reads_the_grid(self):
        g = Gated()
        g.frame_gate = None
        cap = Cap(frames=6)
        with _opened(cap):
            run(SimpleNamespace(media="x", fps=2.0), [g])
        self.assertEqual(len(g.fed), 6)
        self.assertIsNone(getattr(g, "gate_log", None))


class FakeCache:
    """A crop cache that records which times it fetched, lazily."""

    def __init__(self, times):
        self.t_ms = np.asarray(times, float)
        self.record = {"version": "cache-test", "hz": None}
        self.fetched: list[float] = []

    def samples(self, targets, rois=None):
        for t in targets:
            self.fetched.append(float(t))
            yield SimpleNamespace(t_ms=float(t), frame_idx=int(t // 500), frame=None)


class CachedHookTests(unittest.TestCase):
    def test_a_refused_time_costs_no_crop_fetch(self):
        times = [i * 500.0 for i in range(30)]
        g = Gated()
        g.cache_rois = ("minimap",)
        cache = FakeCache(times)
        run_cached(SimpleNamespace(), [g], cache)
        self.assertEqual(cache.fetched, g.fed)
        log = g.gate_log
        self.assertEqual(len(log.reads) + log.summary()["refused"], 30)
        self.assertEqual(log.summary()["offered"], 30)
        self.assertEqual(g.gate_log.summary()["refused"], sum(r["frames"] for r in
                                                                g.gate_log.unread_rows()))

    def test_log_merge_keeps_run_order(self):
        a, b = GateLog(Gated.opportunity_gate), GateLog(Gated.opportunity_gate)
        a.record(0.0, GateDecision(False, "x"))
        a.record(500.0, GateDecision(False, "x"))
        b.record(9000.0, GateDecision(True, "open"))
        b.record(9500.0, GateDecision(False, "x"))
        a.extend(b)
        self.assertEqual(a.runs, [[0.0, 500.0, "x", 2, ()], [9500.0, 9500.0, "x", 1, ()]])
        self.assertEqual(a.read_t, [9000.0])


def _belief(n_open=4, starts=(0.0,)):
    t = np.arange(0.0, 600_000.0, 1000.0 / 15)
    return GateBelief(t, np.full(t.size, n_open), np.asarray(starts), r_fit_m=1.5,
                      v_max=7.5, m_per_px=0.1, stamp={"test": True})


class AllyGateRuleTests(unittest.TestCase):
    def _gate(self, **kw):
        return AllyGate(_belief(kw.pop("n_open", 4), kw.pop("starts", (0.0,))), **kw)

    def test_reach_opens_at_the_tolerance(self):
        g = self._gate()
        grid = np.arange(1000.0, 8000.0, 1000.0 / 15)
        reads = []
        for t in grid:
            ok, why = g.wants(t)[:2]
            if ok:
                reads.append((round(t), why))
                g.observed(t, [(10.0 * k, 0.0) for k in range(4)])
        self.assertEqual(reads[0][1], "unanchored")
        self.assertTrue(all(w == "reach_exceeds_tolerance" for _t, w in reads[1:]))
        gap = np.diff([t for t, _w in reads])
        self.assertTrue((gap >= g.retry_ms - 70).all() and (gap <= g.retry_ms + 70).all())

    def test_an_unfound_teammate_retries_at_the_reach_period(self):
        g = self._gate()
        g.wants(1000.0)
        g.observed(1000.0, [(0.0, 0.0)])             # 1 of 4 found
        self.assertEqual(g.wants(1000.0 + 1000.0 / 15)[:2], (False, "retry_wait"))
        self.assertEqual(g.belief.at(2000.0)["kind"], "unanchored")

    def test_a_death_opens_a_cue_at_5_hz(self):
        g = self._gate(deaths_t=[3000.0])
        g.wants(2900.0)
        g.observed(2900.0, [(0.0, 0.0)] * 4)
        t = 2900.0
        opened = []
        while t < 4500.0:
            t += 1000.0 / 15
            ok, why = g.wants(t)[:2]
            if ok:
                opened.append((t, why))
                g.observed(t, [(0.0, 0.0)] * 4)
        cues = [x for x, w in opened if w == "cue:death"]
        self.assertGreaterEqual(len(cues), 4)
        self.assertTrue(all(3000.0 <= x <= 4000.0 for x in cues))
        self.assertTrue((np.diff(cues) >= 199.0).all())

    def test_an_enemy_near_a_teammate_is_a_cue(self):
        enemy = (np.array([2000.0]), np.array([105.0]), np.array([0.0]))
        g = self._gate(enemy=enemy)
        g.wants(1900.0)
        g.observed(1900.0, [(0.0, 0.0), (100.0, 0.0), (300.0, 0.0), (400.0, 0.0)])
        self.assertEqual(g.wants(2100.0)[:2], (True, "cue:enemy_near"))
        far = AllyGate(_belief(), enemy=(np.array([2000.0]), np.array([900.0]), np.array([0.0])))
        far.wants(1900.0)
        far.observed(1900.0, [(0.0, 0.0)] * 4)
        self.assertEqual(far.wants(2100.0)[:2], (False, "within_tolerance"))

    def test_no_open_teammate_refuses(self):
        self.assertEqual(self._gate(n_open=0).wants(1000.0), (False, "no_open_teammate", ("belief",)))

    def test_a_gap_or_a_round_barrier_restarts_the_belief(self):
        g = self._gate(starts=(0.0, 50_000.0))
        g.wants(1000.0)
        g.observed(1000.0, [(0.0, 0.0)] * 4)
        self.assertEqual(g.wants(1000.0 + 1000.0 / 15)[1], "within_tolerance")
        self.assertEqual(g.wants(1500.0)[:2], (True, "unanchored"))      # a 433 ms gap
        g.observed(1500.0, [(0.0, 0.0)] * 4)
        t = 1500.0
        while t < 50_100.0:
            t += 1000.0 / 15
            ok, _why = g.wants(t)[:2]
            if ok:
                g.observed(t, [(0.0, 0.0)] * 4)
            if t >= 50_000.0:
                self.assertEqual((ok, _why), (True, "unanchored"))
                break

    def test_the_gate_reads_no_replay(self):
        import inspect

        from reticle import ally_gate, slot_state
        code = [inspect.getsource(ally_gate).split('"""', 2)[2]]
        for fn in (slot_state.gate_belief, slot_state.ally_gate_for, slot_state.stored_enemy_icons):
            code.append(inspect.getsource(fn).split('"""', 2)[2])
        for src in code:
            for name in ("replay_", "vrf", "external"):
                self.assertNotIn(name, src)

    def test_teammate_fits_skip_barriers_and_stack_members(self):
        icons = [{"cx": 1, "cy": 2, "reason": None}, {"cx": 3, "cy": 4, "reason": "interior_is_map"},
                 {"cx": 5, "cy": 6, "reason": None, "origin": "stack_fit"}]
        self.assertEqual(teammate_fits(icons), [(1.0, 2.0)])


class OneRowPerInstantTests(unittest.TestCase):
    def test_every_offered_instant_has_exactly_one_gated_row(self):
        g = Gated()
        cap = Cap(frames=60)
        with _opened(cap):
            run(SimpleNamespace(media="x", fps=2.0), [g])
        offered = [i * 500.0 for i in range(60)]
        frames = [{"kind": "frame", "frame_idx": i, "t_ms": t, "widget_drawn": True}
                  for i, t in enumerate(g.fed)]
        gated, audit = AllyIconReader.gated_streams([{"kind": "coverage"}] + frames, g.gate_log)
        covered = [r["t_ms"] for r in gated if r["kind"] == "frame"]
        for r in gated:
            if r["kind"] == "unread":
                covered += [t for t in offered if r["t_ms"] <= t <= r["t_last_ms"]]
        self.assertEqual(sorted(covered), offered)
        self.assertEqual(gated[0]["gate"]["offered"], 60)
        # the audit read some refused instants: each still has its unread row
        self.assertTrue(set(g.gate_log.audit_t) - set(g.gate_log.reads))
        self.assertEqual(sorted(r["t_ms"] for r in audit if r["kind"] == "frame"),
                         sorted(g.gate_log.audit_t))


class AllyStreamTests(unittest.TestCase):
    def test_the_audit_is_stored_apart(self):
        head = {"kind": "coverage", "session_id": "s", "frames": 4}
        frames = [{"kind": "frame", "frame_idx": i, "t_ms": t, "widget_drawn": True,
                   "stack_reason": "self_unseen"} for i, t in enumerate((0.0, 500.0, 1000.0, 1500.0))]
        icons = [{"kind": "icon", "frame_idx": i, "t_ms": f["t_ms"], "reason": None}
                 for i, f in enumerate(frames)]
        log = GateLog(AllyIconReader.opportunity_gate)
        log.record(0.0, GateDecision(True, "unanchored", rests_on=("belief",)))
        log.record(500.0, GateDecision(False, "within_tolerance", rests_on=("belief",)))
        log.record(1000.0, GateDecision(False, "within_tolerance", audit=True,
                                        rests_on=("belief",)))
        log.record(1500.0, GateDecision(True, "reach_exceeds_tolerance", audit=True,
                                        rests_on=("belief", "death")))
        gated, audit = AllyIconReader.gated_streams([head] + frames + icons, log)
        self.assertEqual(gated[0]["read"], "gate")
        self.assertEqual([r["t_ms"] for r in gated if r["kind"] == "frame"], [0.0, 1500.0])
        self.assertEqual([r for r in gated if r["kind"] == "unread"],
                         [{"kind": "unread", "t_ms": 500.0, "t_last_ms": 1000.0,
                           "reason": "within_tolerance", "frames": 2, "rests_on": ["belief"],
                           "gate_version": AllyIconReader.opportunity_gate.version}])
        read = [r for r in gated if r["kind"] == "frame"]
        self.assertEqual([(r["gate_reason"], r["gate_rests_on"]) for r in read],
                         [("unanchored", ["belief"]), ("reach_exceeds_tolerance", ["belief", "death"])])
        self.assertEqual(audit[0]["read"], "audit")
        self.assertEqual([r["t_ms"] for r in audit if r["kind"] == "frame"], [1000.0, 1500.0])
        self.assertEqual(audit[0]["frames"], 2)
        self.assertEqual(gated[0]["gate"]["audit_only"], 1)
        self.assertEqual(gated[0]["gate"]["offered"], 4)
        self.assertEqual(gated[0]["gate"]["version"], "ally-gate-0.1.0")

    def test_the_reader_declares_a_frame_gate(self):
        g = AllyIconReader.opportunity_gate
        self.assertEqual((g.kind, g.version), ("frame", "ally-gate-0.1.0"))
        self.assertIsNotNone(g.audit)
        r = AllyIconReader.__new__(AllyIconReader)
        self.assertFalse(passes.frame_gated(r))
        gate = AllyGate(_belief(), sources={"belief": "belief stamp"})
        r.bind_gate(gate)
        self.assertTrue(passes.frame_gated(r))
        self.assertEqual(r.opportunity_gate.rests_on, ("belief: belief stamp",))
        r.frames, r.icons = [], []
        r.spans = None
        d = gate_decide(r, 1000.0)
        self.assertEqual((d.read, d.reason), (True, "unanchored"))


if __name__ == "__main__":
    unittest.main()
