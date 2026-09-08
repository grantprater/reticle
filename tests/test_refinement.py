import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reticle.refinement import plan_refinement, save_refinement
from reticle.artifacts import producer_fingerprint
from reticle.review import REVIEW_VERSION
from reticle.version import COACH_VERSION


class FakeStore:
    def __init__(self, root, sid, date):
        self.root = Path(root)
        self.sid, self.date = sid, date

    def _path(self, name):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def manifest_path(self, sid):
        return self._path(f"manifests/{sid}.json")

    def hud_path(self, sid, date):
        return self._path(f"l1/{sid}-{date}-hud.parquet")

    def roster_path(self, sid, date):
        return self._path(f"l1/{sid}-{date}-roster.parquet")


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RefinementTests(unittest.TestCase):
    def _bundle(self, td, sid="s1"):
        root = Path(td)
        store = FakeStore(root / "store", sid, "2026-09-07")
        manifest = {"session_id": sid, "ingested_at": "2026-09-07T00:00:00", "source": {"path": "clip.mp4", "duration_ms": 20000}}
        for p, value in ((store.manifest_path(sid), manifest), (store.hud_path(sid, "2026-09-07"), b"hud"), (store.roster_path(sid, "2026-09-07"), b"roster")):
            if isinstance(value, dict): p.write_text(json.dumps(value), encoding="utf-8")
            else: p.write_bytes(value)
        bundle = root / "bundle"; bundle.mkdir(exist_ok=True)
        code = producer_fingerprint("coaching")
        report = {"review_version": REVIEW_VERSION, "coach_version": COACH_VERSION,
                  "code_sha256": code, "inputs": [{"session_id": sid,
                  "manifest_sha256": _digest(store.manifest_path(sid)), "hud_sha256": _digest(store.hud_path(sid, "2026-09-07")),
                  "roster_sha256": _digest(store.roster_path(sid, "2026-09-07"))}]}
        (bundle / "report.json").write_text(json.dumps(report), encoding="utf-8")
        rows = [dict(review_id="a", review_version=REVIEW_VERSION, session_id=sid, source_path="clip.mp4", t_ms=2000, clip_start_ms=0, clip_end_ms=5000),
                dict(review_id="b", review_version=REVIEW_VERSION, session_id=sid, source_path="clip.mp4", t_ms=6000, clip_start_ms=4000, clip_end_ms=9000)]
        (bundle / "review.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return store, manifest, bundle

    def test_plan_rejects_stale_code_and_unknown_or_cross_session_ids(self):
        with tempfile.TemporaryDirectory() as td:
            store, manifest, bundle = self._bundle(td)
            report = json.loads((bundle / "report.json").read_text())
            report["code_sha256"]["review.py"] = "stale"
            (bundle / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "stale review producer"):
                plan_refinement(store, manifest, bundle, ["a"])
            store, manifest, bundle = self._bundle(td, "s2")
            with self.assertRaisesRegex(ValueError, "unknown"):
                plan_refinement(store, manifest, bundle, ["missing"])
            rows = (bundle / "review.jsonl").read_text().replace('"session_id": "s2"', '"session_id": "other"')
            (bundle / "review.jsonl").write_text(rows)
            with self.assertRaisesRegex(ValueError, "another session"):
                plan_refinement(store, manifest, bundle, ["a"])

    def test_plan_merges_overlap_and_enforces_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store, manifest, bundle = self._bundle(td)
            plan = plan_refinement(store, manifest, bundle, ["a", "b"], max_seconds=9)
            self.assertEqual(plan["spans_ms"], [(0.0, 9000.0)])
            with self.assertRaisesRegex(ValueError, "exceeding"):
                plan_refinement(store, manifest, bundle, ["a", "b"], max_seconds=8)

    def test_preview_path_does_not_open_video(self):
        with tempfile.TemporaryDirectory() as td:
            store, manifest, bundle = self._bundle(td)
            from reticle.cli import main
            with patch("reticle.refine.iter_windows", side_effect=AssertionError("decode")), \
                    patch("reticle.cli._HudPass", side_effect=AssertionError("video")), \
                    patch("reticle.cli.Store", return_value=store), \
                    patch("reticle.cli._resolve_session", return_value=manifest):
                self.assertEqual(main(['refine', 's1', '--bundle', str(bundle), '--review-id', 'a']), 0)

    def test_modified_hud_and_removed_roster_refuse(self):
        with tempfile.TemporaryDirectory() as td:
            store, manifest, bundle = self._bundle(td)
            hp = store.hud_path('s1', '2026-09-07')
            hp.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hud_sha256'):
                plan_refinement(store, manifest, bundle, ['a'])
            hp.write_bytes(b'hud')
            store.roster_path('s1', '2026-09-07').unlink()
            with self.assertRaisesRegex(ValueError, 'stale review roster'):
                plan_refinement(store, manifest, bundle, ['a'])

    def test_save_invalid_nan_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "result.json"; target.write_text("original", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_refinement(target, {"session_id": "s"}, [{"value": float("nan")}])
            self.assertEqual(target.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
