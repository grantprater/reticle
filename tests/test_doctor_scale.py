"""doctor SCALE: a map-drawn size read at the widget's scale alone."""
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import doctor


def _check(src: str, allow: dict | None = None) -> list[tuple[str, str]]:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "reticle").mkdir()
        (base / "reticle" / "reader.py").write_text(textwrap.dedent(src), encoding="utf-8")
        return doctor.check_scale(base, {} if allow is None else allow)


class ScaleCheckTests(unittest.TestCase):
    def test_a_planted_widget_scale_read_is_an_error(self):
        got = _check("""
            from .minimap import widget_scale
            def read(crop):
                return 9.5 * widget_scale(crop.shape[1])
            """)
        self.assertEqual([s for s, _ in got], [doctor.ERROR])
        self.assertIn("reticle/reader.py:4 read: widget_scale()", got[0][1])

    def test_a_stored_widget_scale_and_the_reference_width_are_errors(self):
        got = _check("""
            def read(row, w):
                return row["widget_scale"] * 2 + row.get("widget_scale") + 2.0 * w / 465.0
            """)
        self.assertEqual(sorted(m.split(" -- ")[0].split(": ", 1)[1] for _, m in got),
                         ['.get("widget_scale")', '/ reference width', '["widget_scale"]'])

    def test_a_scale_taker_without_scale_is_an_error_and_with_one_is_not(self):
        got = _check("""
            from .minimap import self_icons
            def read(crop, floor, sc):
                a = self_icons(crop, floor, require_facing=False)
                b = self_icons(crop, floor, scale=sc)
                c = self_icons(crop, floor, **{"scale": sc})
                return a, b, c
            """)
        self.assertEqual(len(got), 1)
        self.assertIn("self_icons() without scale", got[0][1])

    def test_a_local_function_of_the_same_name_is_not_a_scale_taker(self):
        self.assertEqual(_check("""
            def compare(rows):
                def icons(r):
                    return r["icons"]
                return [icons(r) for r in rows]
            """), [])

    def test_a_listed_use_passes_a_deferred_one_warns_and_a_stale_entry_warns(self):
        src = """
            from .minimap import widget_scale
            def chrome(w):
                return widget_scale(w)
            def bake(w):
                return widget_scale(w)
            """
        got = _check(src, {("reticle/reader.py", "chrome"): "the widget's own frame",
                           ("reticle/reader.py", "bake"): "deferred: a bake",
                           ("reticle/reader.py", "gone"): "nothing reads here now"})
        self.assertEqual(sorted(s for s, _ in got), [doctor.WARN, doctor.WARN])
        self.assertTrue(any("deferred: a bake" in m for _, m in got))
        self.assertTrue(any("matches no widget-scale read" in m for _, m in got))

    def test_the_repository_has_no_unlisted_use(self):
        self.assertEqual([m for s, m in doctor.check_scale() if s == doctor.ERROR], [])


if __name__ == "__main__":
    unittest.main()
