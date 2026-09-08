import tempfile
import unittest
from pathlib import Path

from reticle.artifacts import (
    ARTIFACTS,
    affected_artifacts,
    changed_producers,
    producer_fingerprint,
)


class ArtifactTests(unittest.TestCase):
    def _root(self, names):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        return td, root

    def test_fingerprint_and_changed_producers_track_content_and_keys(self):
        names = ARTIFACTS["coaching"].code
        td, root = self._root(names)
        try:
            recorded = producer_fingerprint("coaching", root)
            (root / names[0]).write_bytes(b"changed")
            recorded.pop(names[1])
            recorded["extra.py"] = "gone"
            self.assertEqual(
                changed_producers("coaching", recorded, root),
                sorted((names[0], names[1], "extra.py")),
            )
        finally:
            td.cleanup()

    def test_missing_registered_source_refuses_to_fingerprint(self):
        names = ARTIFACTS["coaching"].code
        td, root = self._root(names[:-1])
        try:
            with self.assertRaises(FileNotFoundError):
                producer_fingerprint("coaching", root)
        finally:
            td.cleanup()

    def test_affected_artifacts_follow_registry_and_parent_graph(self):
        self.assertEqual(affected_artifacts(["docs/README.md"]), [])
        self.assertEqual(affected_artifacts(["reticle/hud_reader.py"]), ["refinement"])
        self.assertEqual(affected_artifacts(["reticle/roster.py"]), ["coaching", "refinement"])
        self.assertEqual(affected_artifacts(["reticle/artifacts.py"]), ["coaching", "refinement"])


if __name__ == "__main__":
    unittest.main()
