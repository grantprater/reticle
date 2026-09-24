"""Shared candidate accounting and minimap replay boundary."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from reticle.adjudication.minimap_candidates import (
    MINIMAP_ICON_DECISION_VERSION, accepted, ally_decisions)
from reticle.minimap import AllyIconReader
from reticle.store import Store


class CandidateEvidenceTests(unittest.TestCase):
    def test_fitted_icon_replays_from_persisted_evidence(self):
        w = 465
        static = np.full((w, w, 3), 128, np.uint8)
        crop = static.copy()
        cv2.circle(crop, (60, 60), 10, (200, 220, 40), 3)
        cv2.fillPoly(crop, [np.array([[60, 44], [55, 51], [65, 51]], np.int32)],
                     (200, 220, 40))
        cv2.circle(crop, (60, 60), 7, (30, 60, 200), -1)
        reader = AllyIconReader(np.ones((w, w), bool), None, static,
                                (0, 0, w, w))
        with patch("reticle.minimap.widget_drawn", return_value=True):
            reader.feed(SimpleNamespace(frame=crop, frame_idx=7, t_ms=3500.0))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            rev = store.write_candidates("ally_icon", "s", reader.candidate_rows("s"),
                                         reader.frames)
            batch = store.read_candidate_batch("ally_icon", "s", rev)
            decisions = ally_decisions(batch["rows"])
            store.write_decisions("ally_icon", "s", rev,
                                  MINIMAP_ICON_DECISION_VERSION, decisions)
            loaded = store.read_decisions("ally_icon", "s", rev,
                                          MINIMAP_ICON_DECISION_VERSION)
            kept = accepted(batch["rows"], loaded)
            expected = reader.events("s", kept, rev)
            actual = AllyIconReader.replay_events("s", batch["frames"], kept,
                                                  reader.hz, rev)
            self.assertEqual(actual, expected)
            self.assertEqual(actual[0]["candidate_lineage"], "complete")
            self.assertEqual(len([r for r in actual if r["kind"] == "icon"]), 1)
            self.assertTrue(all(r["baseline_descriptor"] is not None
                                for r in batch["rows"] if r["channel"] == "ally"))
            bad = [dict(r) for r in loaded]
            bad.pop()
            with self.assertRaisesRegex(ValueError, "undecided"):
                store.write_decisions("ally_icon", "s", rev,
                                      MINIMAP_ICON_DECISION_VERSION, bad)

    def test_rejected_fit_keeps_baseline_for_replay(self):
        w = 465
        static = np.full((w, w, 3), 128, np.uint8)
        crop = static.copy()
        cv2.circle(crop, (60, 60), 10, (200, 220, 40), 3)
        cv2.fillPoly(crop, [np.array([[60, 44], [55, 51], [65, 51]], np.int32)],
                     (200, 220, 40))
        cv2.circle(crop, (60, 60), 7, (30, 60, 200), -1)
        # A 30-degree arc fits a ring whose coverage fails the shape gate.
        cv2.ellipse(crop, (200, 200), (10, 10), 0, 0, 30, (200, 220, 40), 3)
        reader = AllyIconReader(np.ones((w, w), bool), None, static,
                                (0, 0, w, w))
        with patch("reticle.minimap.widget_drawn", return_value=True):
            reader.feed(SimpleNamespace(frame=crop, frame_idx=7, t_ms=3500.0))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            rev = store.write_candidates("ally_icon", "s", reader.candidate_rows("s"),
                                         reader.frames)
            batch = store.read_candidate_batch("ally_icon", "s", rev)
            store.write_decisions("ally_icon", "s", rev,
                                  MINIMAP_ICON_DECISION_VERSION,
                                  ally_decisions(batch["rows"]))
            loaded = store.read_decisions("ally_icon", "s", rev,
                                          MINIMAP_ICON_DECISION_VERSION)
            # Decisions replay from the stored revision alone.
            reread = store.read_candidate_batch("ally_icon", "s", rev)
            self.assertEqual(ally_decisions(reread["rows"]), loaded)
            rejected = [d for d in loaded if d["disposition"] == "rejected"]
            self.assertEqual([d["reason"] for d in rejected], ["shape_gate"])
            row = next(r for r in batch["rows"]
                       if r["candidate_key"] == rejected[0]["candidate_key"])
            # The accepted view measured no descriptor; the baseline did.
            self.assertIsNone(row["descriptor"])
            self.assertEqual(row["descriptor_reason"], "not_selected")
            self.assertIsNotNone(row["baseline_descriptor"])
            # The legacy accepted output is unchanged by preserving the fit.
            kept = accepted(batch["rows"], loaded)
            events = AllyIconReader.replay_events("s", batch["frames"], kept,
                                                  reader.hz, rev)
            self.assertEqual(reader.events("s", kept, rev), events)
            icons = [r for r in events if r["kind"] == "icon"]
            self.assertEqual([(r["cx"], r["cy"]) for r in icons],
                             [(round(r["cx"], 2), round(r["cy"], 2))
                              for r in reader.icons])
            self.assertNotIn(row["candidate_key"],
                             {r["candidate_key"] for r in icons})

    def test_identical_fits_select_one_copy(self):
        # Two blobs can fit the same circle. Only the kept copy may carry the
        # accepted view's descriptor or be named as a neighbor dependency.
        import reticle.minimap as minimap
        w = 465
        static = np.full((w, w, 3), 128, np.uint8)
        crop = static.copy()
        for x in (60, 200):
            cv2.circle(crop, (x, 60), 10, (200, 220, 40), 3)
            cv2.fillPoly(crop, [np.array([[x, 44], [x - 5, 51], [x + 5, 51]],
                                         np.int32)], (200, 220, 40))
            cv2.circle(crop, (x, 60), 7, (30, 60, 200), -1)
        real = minimap.icons

        def doubled(*args, **kwargs):
            found = real(*args, **kwargs)
            if kwargs.get("gates", True):
                return found
            return sorted([dict(f) for f in found for _ in (0, 1)],
                          key=lambda d: -d["cov"])

        reader = AllyIconReader(np.ones((w, w), bool), None, static,
                                (0, 0, w, w))
        with patch("reticle.minimap.widget_drawn", return_value=True),                 patch("reticle.minimap.icons", side_effect=doubled):
            reader.feed(SimpleNamespace(frame=crop, frame_idx=7, t_ms=3500.0))
        rows = [r for r in reader.candidate_rows("s") if r["channel"] == "ally"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(sum(r["descriptor_reason"] != "not_selected"
                             for r in rows), 2)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            rev = store.write_candidates("ally_icon", "s", reader.candidate_rows("s"),
                                         reader.frames)
            batch = store.read_candidate_batch("ally_icon", "s", rev)
            store.write_decisions("ally_icon", "s", rev,
                                  MINIMAP_ICON_DECISION_VERSION,
                                  ally_decisions(batch["rows"]))
            loaded = store.read_decisions("ally_icon", "s", rev,
                                          MINIMAP_ICON_DECISION_VERSION)
            kept = accepted(batch["rows"], loaded)
            events = reader.events("s", kept, rev)
            self.assertEqual(len([r for r in events if r["kind"] == "icon"]), 2)


if __name__ == "__main__":
    unittest.main()
