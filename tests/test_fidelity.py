import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

from reticle.acquisition import plan_spec
from reticle.capabilities import builtin_capabilities, unvalidated
from reticle.decode import sample_windows
from reticle.fidelity import (FROZEN_WINDOWS, Tier, load_windows, score_agreement,
                              score_killfeed, score_minimap_coverage)


def frozen():
    return load_windows(FROZEN_WINDOWS)


class Cap:
    """A decoder with a known timeline, so a transport can be tested without media."""

    def __init__(self, frames=1200, fps=60.0):
        self.frames, self.fps, self.i = frames, fps, -1
        self.released = False
        self.seeks = []

    def isOpened(self): return True

    def set(self, prop, value):
        self.seeks.append(value)
        self.i = int(value / 1000.0 * self.fps) - 1
        return True

    def grab(self):
        self.i += 1
        return self.i < self.frames

    def get(self, prop):
        # POS_MSEC and POS_FRAMES both derive from the same cursor.
        return self.i * (1000.0 / self.fps) if prop == 0 else self.i + 1

    def retrieve(self): return True, np.zeros((1, 1, 3), dtype=np.uint8)

    def release(self): self.released = True


class FrozenContractTests(unittest.TestCase):
    def test_shipped_contract_loads_and_pins_its_review(self):
        f = frozen()
        self.assertEqual(f["session_id"], "c40d950031bb")
        roles = {w["role"] for w in f["windows"]}
        self.assertEqual(roles, {"trigger", "audit", "confuser"})
        for window in f["windows"]:
            # Every reviewed instant must be one somebody looked at, and the
            # presence/absence lists may not overlap: an instant cannot be both.
            seen = set(window["reviewed"]["entries_seen_at_ms"])
            empty = set(window["reviewed"]["no_entries_at_ms"])
            self.assertFalse(seen & empty, window["window_id"])
            self.assertTrue((seen | empty) <= set(window["reviewed_instants_ms"]),
                            window["window_id"])

    def test_a_window_without_a_review_is_refused(self):
        f = frozen()
        f["windows"][0].pop("reviewed")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.json"
            p.write_text(json.dumps(f), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_windows(p)

    def test_a_reviewed_instant_outside_its_window_is_refused(self):
        f = frozen()
        f["windows"][0]["reviewed_instants_ms"].append(f["windows"][0]["t1_ms"] + 1)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.json"
            p.write_text(json.dumps(f), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_windows(p)


TOL = {"onset_ms": 250, "min_presence_recall": 0.9,
       "max_confuser_false_positive_frames": 0}


def synthetic(role="trigger", seen=(1000.0,), empty=(5000.0,)):
    """A contract with WELL-SEPARATED instants, so counts are exact.

    The shipped windows were reviewed at 200 ms and the tolerance is 250 ms, so
    one observation there legitimately covers two neighbouring instants. That is
    the intended rule and a poor place to assert an exact number.
    """
    return {"windows": [{"window_id": "w", "role": role, "t0_ms": 0.0,
                         "t1_ms": 10000.0,
                         "reviewed_instants_ms": list(seen) + list(empty),
                         "reviewed": {"entries_seen_at_ms": list(seen),
                                      "no_entries_at_ms": list(empty)}}]}


class ScoringTests(unittest.TestCase):
    def test_presence_is_recalled_within_tolerance_and_missed_outside_it(self):
        f = synthetic()
        near = score_killfeed(f, [{"t_ms": 1100.0, "entries": 1}], TOL)
        far = score_killfeed(f, [{"t_ms": 1400.0, "entries": 1}], TOL)
        self.assertEqual(near["per_window"][0]["recalled"], 1)
        self.assertEqual(near["pooled_presence_recall"], 1.0)
        self.assertEqual(far["per_window"][0]["recalled"], 0)
        self.assertEqual(far["pooled_presence_recall"], 0.0)

    def test_one_observation_recalls_every_instant_it_covers(self):
        """Recall is per reviewed instant, not per sample: a 2 Hz reader has no
        sample at every 200 ms instant and must not be scored as if it did."""
        f = synthetic(seen=(1000.0, 1200.0))
        got = score_killfeed(f, [{"t_ms": 1100.0, "entries": 1}], TOL)
        self.assertEqual(got["per_window"][0]["recalled"], 2)

    def test_a_claim_at_a_reviewed_empty_instant_is_a_false_positive(self):
        f = synthetic(role="confuser")
        loud = score_killfeed(f, [{"t_ms": 5000.0, "entries": 3}], TOL)
        self.assertEqual(loud["confuser_false_positive_instants"], 1)
        quiet = score_killfeed(f, [{"t_ms": 5000.0, "entries": 0}], TOL)
        self.assertEqual(quiet["confuser_false_positive_instants"], 0)

    def test_false_positives_do_not_fall_as_the_sample_rate_rises(self):
        """The rule counts any nearby claim, not every nearby claim.

        Requiring all of them made a denser tier score better for being denser,
        which is the defect this rule was corrected for after the first run
        reported 0 false positives at native rate and 1 at 15 Hz.
        """
        f = synthetic(role="confuser")
        sparse = [{"t_ms": 5000.0, "entries": 2}]
        dense = sparse + [{"t_ms": 5060.0, "entries": 0},
                          {"t_ms": 4940.0, "entries": 0}]
        self.assertEqual(score_killfeed(f, sparse, TOL)["confuser_false_positive_instants"],
                         score_killfeed(f, dense, TOL)["confuser_false_positive_instants"])

    def test_a_window_nobody_sampled_recalls_nothing_rather_than_everything(self):
        f = synthetic()
        got = score_killfeed(f, [], TOL)
        self.assertEqual(got["per_window"][0]["n_samples"], 0)
        self.assertEqual(got["pooled_presence_recall"], 0.0)
        self.assertEqual(got["false_positive_instants"], 0)

    def test_agreement_is_scored_only_on_shared_frames(self):
        tol = {"agreement_px": 3.0}
        reference = [{"frame_idx": i, "self_x": 10.0, "self_y": 10.0} for i in range(4)]
        candidate = [{"frame_idx": 0, "self_x": 11.0, "self_y": 10.0},
                     {"frame_idx": 2, "self_x": 40.0, "self_y": 10.0},
                     {"frame_idx": 99, "self_x": 10.0, "self_y": 10.0}]
        got = score_agreement(reference, candidate, tol, ("self_x", "self_y"))
        self.assertEqual(got["n_shared_frames"], 2)
        self.assertEqual((got["agree"], got["differ"]), (1, 1))
        self.assertAlmostEqual(got["worst_disagreement_px"], 30.0)

    def test_a_null_on_both_sides_agrees_and_a_one_sided_null_differs(self):
        tol = {"agreement_px": 3.0}
        reference = [{"frame_idx": 0, "self_x": None, "self_y": None},
                     {"frame_idx": 1, "self_x": 5.0, "self_y": 5.0}]
        candidate = [{"frame_idx": 0, "self_x": None, "self_y": None},
                     {"frame_idx": 1, "self_x": None, "self_y": None}]
        got = score_agreement(reference, candidate, tol, ("self_x", "self_y"))
        self.assertEqual((got["agree"], got["differ"]), (1, 1))
        self.assertEqual(got["candidate_null_where_reference_read"], 1)


class NativeTierTests(unittest.TestCase):
    def test_native_oversamples_so_the_reference_drops_no_frame(self):
        """Asking for exactly the nominal rate silently sampled at 48 Hz."""
        self.assertGreater(Tier("native", None).request_hz(60.0), 60.0)
        self.assertEqual(Tier("native", None).effective_hz(60.0), 60.0)
        self.assertEqual(Tier("2hz", 2.0).request_hz(60.0), 2.0)


class MinimapCoverageTests(unittest.TestCase):
    def test_widget_absence_is_not_a_detector_refusal(self):
        rows = [
            {"self_x": 1.0, "self_y": 2.0},
            {"self_x": None, "self_y": None},  # fitted icon refused
            {"self_x": None, "self_y": None},  # widget absent
        ]
        got = score_minimap_coverage(rows, widget_absent=1)
        self.assertEqual((got["eligible"], got["reads"], got["refused"]),
                         (2, 1, 1))
        self.assertEqual(got["eligible_coverage_fraction"], 0.5)


class SeekTransportTests(unittest.TestCase):
    def test_it_seeks_to_each_window_instead_of_grabbing_from_the_start(self):
        cap = Cap(frames=60 * 60)
        with mock.patch("cv2.VideoCapture", return_value=cap):
            got = [s.t_ms for _, s in sample_windows(
                "mock", 60.0, {"r": (10.0, [(50000.0, 50500.0)])})]
        self.assertTrue(got and 50000.0 <= got[0] < 50200.0)
        self.assertEqual(cap.seeks, [50000.0])
        self.assertTrue(cap.released)

    def test_unrestricted_coverage_is_refused_rather_than_scanned(self):
        with self.assertRaises(ValueError):
            list(sample_windows("mock", 60.0, {"r": (10.0, None)}))

    def test_no_requested_coverage_does_no_work(self):
        cap = Cap()
        with mock.patch("cv2.VideoCapture", return_value=cap):
            self.assertEqual(list(sample_windows("mock", 60.0, {"r": (10.0, [])})), [])
        self.assertEqual(cap.seeks, [])


class TransportChoiceTests(unittest.TestCase):
    def test_a_late_narrow_window_plans_the_seeking_transport(self):
        spec = {
            "nominal_fps": 60.0, "capabilities": "builtin",
            "requests": [{
                "request_id": "kf", "reader": "hud",
                "property": "killfeed_entry_presence",
                "alternatives": ["entry", "no_entry"],
                "spans_ms": [[850000, 860000]], "max_sample_gap_ms": 200,
                "allowed_tiers": ["sparse", "standard", "motion", "native"],
                "reason": "a kill is claimed here",
            }],
        }
        plan = plan_spec(spec)
        self.assertEqual(plan["transport"], "seek_windows")
        self.assertEqual(plan["covered_span_seconds"], 10.0)
        self.assertEqual(plan["reach_seconds"], 860.0)

    def test_near_contiguous_coverage_keeps_the_sequential_transport(self):
        spec = {
            "nominal_fps": 60.0, "capabilities": "builtin",
            "requests": [{
                "request_id": "kf", "reader": "hud",
                "property": "killfeed_entry_presence",
                "alternatives": ["entry", "no_entry"],
                "spans_ms": [[0, 900000]], "max_sample_gap_ms": 200,
                "allowed_tiers": ["sparse", "standard", "motion", "native"],
                "reason": "the whole capture",
            }],
        }
        self.assertEqual(plan_spec(spec)["transport"], "sequential_grab")


class BuiltinCapabilityTests(unittest.TestCase):
    def test_the_registry_declares_only_what_the_frozen_run_promoted(self):
        declared = builtin_capabilities()
        self.assertEqual(set(declared), {"hud"})
        self.assertEqual(declared["hud"].properties, ("killfeed_entry_presence",))
        self.assertNotIn("transition", declared["hud"].regimes)
        self.assertNotIn("minimap.self_position", declared)

    def test_no_declared_tier_runs_below_the_validated_five_hertz(self):
        rates = [t.hz for t in builtin_capabilities()["hud"].tiers if t.hz is not None]
        self.assertEqual(min(rates), 5.0)

    def test_every_withheld_entry_says_why(self):
        for key, why in unvalidated().items():
            self.assertTrue(why.strip(), key)

    def test_the_registry_is_a_copy_so_a_caller_cannot_widen_it(self):
        builtin_capabilities().pop("hud")
        self.assertIn("hud", builtin_capabilities())

    def test_an_unvalidated_regime_is_refused_rather_than_answered(self):
        spec = {
            "nominal_fps": 60.0, "capabilities": "builtin",
            "requests": [{
                "request_id": "wipe", "reader": "hud",
                "property": "killfeed_entry_presence",
                "alternatives": ["entry", "no_entry"],
                "spans_ms": [[504000, 505000]], "max_sample_gap_ms": 200,
                "allowed_tiers": ["motion"], "reason": "a wipe crosses the ROI",
                "regime": "transition",
            }],
        }
        plan = plan_spec(spec)
        self.assertEqual(plan["routes"], [])
        self.assertEqual([r["reason"] for r in plan["refused"]], ["unsupported_regime"])

    def test_a_property_the_run_never_scored_is_refused(self):
        spec = {
            "nominal_fps": 60.0, "capabilities": "builtin",
            "requests": [{
                "request_id": "pos", "reader": "minimap",
                "property": "self_position",
                "alternatives": ["a", "b"],
                "spans_ms": [[100000, 101000]], "max_sample_gap_ms": 200,
                "allowed_tiers": ["motion"], "reason": "where was the player",
            }],
        }
        plan = plan_spec(spec)
        self.assertEqual([r["reason"] for r in plan["refused"]], ["unsupported_property"])


if __name__ == "__main__":
    unittest.main()
