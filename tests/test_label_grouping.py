import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import label_grouping as G  # noqa: E402


class StubClips:
    """Frames without a decoder, so the coordinate convention is testable."""

    def __init__(self, root, frame):
        self.root, self.frame = Path(root), frame

    def frames(self, sid, times):
        return [self.frame.copy() for _ in times]

    def release(self):
        pass


class CoordinateConventionTests(unittest.TestCase):
    """A label's x/y index the minimap CROP, not the full frame.

    `ability_series` reads them as `crop[y, x]` on a crop taken at the profile's
    minimap ROI. Reading them as absolute frame coordinates puts every ring
    about fifteen pixels off its object, which looks plausible and answers the
    wrong question -- it is what the first render of this tool actually did.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "manifests").mkdir(parents=True, exist_ok=True)
        (self.root / "manifests/s1.json").write_text(json.dumps({
            "session_id": "s1", "source_profile": "valorant-16x9",
            "source": {"path": "missing", "width": 1920, "height": 1080,
                       "fps": 60.0, "duration_ms": 60000.0}}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_roi_comes_from_the_profile(self):
        x0, y0, w, h = G.roi_for(self.root, "s1")
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        # Whatever the profile says, it must not be the full frame.
        self.assertLess(w, 1920)
        self.assertLess(h, 1080)

    def test_the_ring_lands_on_the_roi_relative_pixel(self):
        x0, y0, w, h = G.roi_for(self.root, "s1")
        frame = np.zeros((1080, 1920, 3), np.uint8)
        # A bright marker at ROI-relative (40, 50).
        frame[y0 + 50, x0 + 40] = (255, 255, 255)
        component = {"component_id": "c1", "session_id": "s1", "x": 40, "y": 50,
                     "observed_t_ms": 1000.0, "observed_end_ms": 1200.0,
                     "raw": {}}
        window = {"review_id": "r1", "session_id": "s1", "component_ids": ["c1"],
                  "clip_start_ms": 0.0, "clip_end_ms": 2000.0, "ability_id": None}
        image, panel_h, (left, scale) = G.compose(
            window, "c1", {"c1": component}, StubClips(self.root, frame))
        self.assertIsNotNone(image)
        # The marker must be inside the ring drawn for the component.
        cx, cy = left + int(40 * scale), int(50 * scale)
        patch = image[max(0, cy - 3):cy + 4, max(0, cx - 3):cx + 4]
        self.assertGreater(int(patch.max()), 200,
                           "the ringed pixel is not where the marker was drawn")

    def test_a_window_with_no_component_still_composes(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        window = {"review_id": "r0", "session_id": "s1", "component_ids": [],
                  "clip_start_ms": 0.0, "clip_end_ms": 4000.0, "ability_id": None}
        image, panel_h, _ = G.compose(window, None, {}, StubClips(self.root, frame))
        self.assertIsNotNone(image)
        self.assertGreater(panel_h, 0)

    def test_the_composite_fits_a_1080p_screen(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        window = {"review_id": "r0", "session_id": "s1", "component_ids": [],
                  "clip_start_ms": 0.0, "clip_end_ms": 4000.0, "ability_id": None}
        image, _, _ = G.compose(window, None, {}, StubClips(self.root, frame))
        self.assertLessEqual(image.shape[0], 960, "leaves no room for the status bars")
        self.assertLessEqual(image.shape[1], 1920)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "analysis/ability-entities").mkdir(parents=True, exist_ok=True)
        rows = [
            {"review_id": "a", "session_id": "s2", "ability_id": "sova:owl drone",
             "component_ids": ["c1", "c2"], "clip_start_ms": 0, "clip_end_ms": 1},
            {"review_id": "b", "session_id": "s1", "ability_id": "deadlock:sonic sensor",
             "component_ids": ["c3"], "clip_start_ms": 0, "clip_end_ms": 1},
        ]
        (self.root / "analysis/ability-entities/review.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_deadlock_is_ranked_first(self):
        got = G.ranked_windows(self.root, None)
        self.assertEqual(got[0]["review_id"], "b")

    def test_answered_components_are_skipped_so_a_pass_resumes(self):
        components = {c: {"component_id": c} for c in ("c1", "c2", "c3")}
        queue, done, out_dir = G.build_queue(self.root, None, False, 0, components)
        self.assertEqual(len(queue), 3)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "s1.jsonl").write_text(
            json.dumps({"review_id": "b", "component_id": "c3"}) + "\n", encoding="utf-8")
        queue, done, _ = G.build_queue(self.root, None, False, 0, components)
        self.assertEqual(len(queue), 2)
        self.assertIn(("b", "c3"), done)


if __name__ == "__main__":
    unittest.main()
