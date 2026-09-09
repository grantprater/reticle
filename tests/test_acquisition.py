import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
import json
import tempfile
from pathlib import Path

import numpy as np

from reticle.acquisition import (DEFAULT_TIERS, EvidenceRequest, ReaderCapability,
                                 SamplingTier, execute_plan, plan_requests,
                                 plan_spec, write_plan)
from reticle.cli import main


CAPABILITIES = {"events": ReaderCapability(
    reader="events", properties=("brief_event", "stable_state"), tiers=DEFAULT_TIERS)}


def request(name, prop, spans, gap, tiers=("sparse", "standard", "motion", "native"),
            selection="conflict"):
    return EvidenceRequest(name, "events", prop, ("present", "absent"), tuple(spans),
                           gap, tuple(tiers), "test distinction", selection=selection)


class Cap:
    def __init__(self, frames=100): self.frames, self.i, self.released = frames, -1, False
    def isOpened(self): return True
    def grab(self): self.i += 1; return self.i < self.frames
    def get(self, prop): return self.i * 100.0
    def retrieve(self): return True, np.zeros((1, 1, 3), dtype=np.uint8)
    def release(self): self.released = True


class Reader:
    def __init__(self): self.times, self.finished = [], 0
    def feed(self, sample): self.times.append(sample.t_ms)
    def finish(self): self.finished += 1


class Context:
    media = "mock"
    fps = 10.0


class PlanningTests(unittest.TestCase):
    def test_least_tier_meeting_tolerance_is_selected(self):
        plan = plan_requests([
            request("stable", "stable_state", [(0, 10000)], 500),
            request("brief", "brief_event", [(4000, 5000)], 100),
        ], CAPABILITIES, 60.0)
        by_request = {rid: route for route in plan["routes"]
                      for rid in route["request_ids"]}
        self.assertEqual(by_request["stable"]["hz"], 2.0)
        self.assertEqual(by_request["brief"]["hz"], 10.0)
        self.assertLess(plan["estimated_frames_conservative"], 10 * 60)

    def test_unsupported_empty_and_budget_are_distinct_refusals(self):
        empty = request("empty", "stable_state", [], 500)
        impossible = request("fast", "brief_event", [(0, 1000)], 1)
        plan = plan_requests([empty, impossible], CAPABILITIES, 60.0)
        self.assertEqual({row["request_id"]: row["reason"] for row in plan["refused"]},
                         {"empty": "empty_coverage_request",
                          "fast": "unsupported_temporal_tolerance"})
        over = plan_requests([request("large", "stable_state", [(0, 10000)], 500)],
                             CAPABILITIES, 60.0, max_frames=10)
        self.assertEqual(over["routes"], [])
        self.assertEqual(over["refused"][0]["reason"], "frame_budget_exhausted")

    def test_unimplemented_spatial_tier_cannot_be_claimed(self):
        capabilities = {"events": ReaderCapability(
            reader="events", properties=("stable_state",),
            tiers=(SamplingTier("half", 2.0, spatial_scale=0.5),))}
        with self.assertRaisesRegex(ValueError, "not executable"):
            plan_requests([request("stable", "stable_state", [(0, 1000)], 500,
                                   tiers=("half",))], capabilities, 60.0)

    def test_request_must_disclose_selection_lane_and_alternatives(self):
        bad_lane = request("bad", "stable_state", [(0, 1000)], 500,
                           selection="outcome")
        with self.assertRaisesRegex(ValueError, "opportunity or conflict"):
            plan_requests([bad_lane], CAPABILITIES, 60.0)
        no_alternatives = EvidenceRequest(
            "none", "events", "stable_state", (), ((0, 1000),), 500,
            ("sparse",), "test distinction")
        with self.assertRaisesRegex(ValueError, "alternatives"):
            plan_requests([no_alternatives], CAPABILITIES, 60.0)

    def test_json_contract_plans_without_media_and_can_be_persisted(self):
        spec = {
            "nominal_fps": 60.0,
            "max_frames": 100,
            "capabilities": [{
                "reader": "events", "properties": ["stable_state"],
                "tiers": [{"name": "sparse", "hz": 2.0}],
            }],
            "requests": [{
                "request_id": "stable", "reader": "events",
                "property": "stable_state", "alternatives": ["same", "changed"],
                "spans_ms": [[0, 1000]], "max_sample_gap_ms": 500,
                "allowed_tiers": ["sparse"], "reason": "audit stable state",
                "selection": "opportunity",
            }],
        }
        self.assertEqual(plan_spec(spec)["routes"][0]["hz"], 2.0)
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "spec.json", Path(tmp) / "plan.json"
            source.write_text(json.dumps(spec), encoding="utf-8")
            plan = write_plan(source, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), plan)
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(["acquisition-plan", str(source)]), 0)
            self.assertEqual(json.loads(stdout.getvalue()), plan)

    def test_execution_shares_retrievals_and_reports_actual_coverage(self):
        plan = plan_requests([
            request("stable", "stable_state", [(0, 9900)], 500,
                    selection="opportunity"),
            request("brief", "brief_event", [(4000, 5000)], 100),
        ], CAPABILITIES, 10.0)
        reader, cap = Reader(), Cap()
        with patch("reticle.decode.cv2.VideoCapture", return_value=cap):
            result = execute_plan(Context(), plan, {"events": reader})
        self.assertLess(result["retrieved_frames"], 100)
        self.assertEqual(result["reader_frames"], len(reader.times))
        self.assertEqual(reader.finished, 1)
        self.assertTrue(all(row["status"] == "observed" for row in result["coverage"]))
        # The dense interval includes the synthetic 4.5-second event instant.
        self.assertIn(4500.0, reader.times)
        self.assertTrue(cap.released)


if __name__ == "__main__":
    unittest.main()
