from pathlib import Path
import tempfile
import unittest

from reticle import doctor


class SessionStaticDoctorTest(unittest.TestCase):
    def test_rejects_retired_api_and_capture_median(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "reticle").mkdir()
            (root / "prototypes").mkdir()
            (root / "reticle" / "reader.py").write_text(
                "def f(store, sid):\n    return store.read_static_map(sid)\n",
                encoding="utf-8")
            (root / "prototypes" / "probe.py").write_text(
                "def f(np, frames):\n    return np.median(np.stack(frames), 0)\n",
                encoding="utf-8")

            found = doctor.check_session_static(root / "store", root)
            messages = "\n".join(message for _severity, message in found)
            self.assertIn("read_static_map", messages)
            self.assertIn("capture median", messages)
            self.assertTrue(all(severity == doctor.ERROR for severity, _ in found))

    def test_allows_only_builder_and_dimension_preflight_medians(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "reticle").mkdir()
            (root / "prototypes").mkdir()
            body = "def f(np, frames):\n    return np.median(np.stack(frames), 0)\n"
            for name in ("minimap_geometry.py", "clip_preflight.py"):
                (root / "prototypes" / name).write_text(body, encoding="utf-8")

            self.assertEqual(doctor.check_session_static(root / "store", root), [])

    def test_reports_but_does_not_remove_legacy_cache_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "reticle").mkdir()
            masks = root / "store" / "masks"
            masks.mkdir(parents=True)
            legacy = masks / "abc.static.npy"
            legacy.write_bytes(b"legacy")

            found = doctor.check_session_static(root / "store", root)
            self.assertEqual(found[0][0], doctor.WARN)
            self.assertIn("ignored by code", found[0][1])
            self.assertTrue(legacy.is_file())


if __name__ == "__main__":
    unittest.main()
