"""doctor RESTATE: reader-layer code that restates or pre-empts a downstream rule."""
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import doctor, ownership

#: A reader (`reader`, detect only), a module owning detect and assign
#: (`mixed`, so not reader-layer), a downstream owner (`track`) and a
#: lower-layer input (`geometry`, constrain).
DECLARATION = """
[[entry]]
id = "reading"
owner = "reader"
role = ["detect"]
produces = ["read"]

[[entry]]
id = "mixed-read"
owner = "mixed"
role = ["detect", "assign"]
produces = ["vote"]

[[entry]]
id = "track-continuation"
owner = "track"
role = ["track", "constrain"]
produces = ["admits", "refit_of"]

[[entry]]
id = "map-geometry"
owner = "geometry"
role = ["constrain"]
produces = ["key_of"]
"""


def _check(files: dict[str, str], allow: dict | None = None, arch: dict | None = None):
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "reticle").mkdir()
        (base / "ownership.toml").write_text(DECLARATION, encoding="utf-8")
        for name in ("track", "geometry", "lineup"):
            (base / "reticle" / f"{name}.py").write_text("def admits(): pass\n",
                                                          encoding="utf-8")
        for name, src in files.items():
            (base / "reticle" / f"{name}.py").write_text(textwrap.dedent(src),
                                                         encoding="utf-8")
        data = ownership.load(base / "ownership.toml")
        return doctor.check_restate(base, {} if allow is None else allow, data,
                                    {} if arch is None else arch)


class RestateCheckTests(unittest.TestCase):
    def test_a_call_to_a_downstream_rule_warns(self):
        got = _check({"reader": """
            from . import track
            from .track import refit_of as refit
            def read(a, b):
                return track.admits(a, b), refit(a)
            """})
        self.assertEqual([s for s, _ in got], [doctor.WARN, doctor.WARN])
        self.assertIn("reticle/reader.py:5 read: track.admits() is a downstream rule "
                      "(track-continuation)", got[0][1])
        self.assertIn("track.refit_of()", got[1][1])

    def test_a_local_function_of_the_same_name_is_not_the_owner(self):
        self.assertEqual(_check({"reader": """
            def admits(a):
                return a
            def read(a):
                return admits(a)
            """}), [])

    def test_a_module_that_owns_more_than_detect_is_not_reader_layer(self):
        self.assertEqual(_check({"mixed": """
            from .track import admits
            def vote(a):
                return admits(a)
            """}), [])

    def test_an_owner_below_the_readers_layer_is_an_input(self):
        src = {"reader": """
            from . import geometry
            def read(sid):
                return geometry.key_of(sid)
            """}
        self.assertEqual(len(_check(src)), 1)
        arch = {"_order": ["source", "readers"], "_index": {"geometry": 0, "reader": 1}}
        self.assertEqual(_check(src, arch=arch), [])

    def test_a_reader_kept_prior_warns(self):
        got = _check({"reader": """
            def fit(crop, prior=None):
                return prior
            def read(crops):
                last = None
                for c in crops:
                    last = fit(c, prior=last)
                return last
            def fresh(crops, p):
                for c in crops:
                    out = fit(c, prior=p)
                return out
            """})
        self.assertEqual(len(got), 1)
        self.assertIn("reader.py:7 read: fit(prior=last) carries its own earlier result",
                      got[0][1])

    def test_a_stored_stream_and_the_lineup_are_gates_on_a_verdict(self):
        got = _check({"reader": """
            from .lineup import load_lineup
            def window(store, sid):
                return store.read_events("death", sid), load_lineup(sid, store.root)
            """})
        self.assertEqual(len(got), 2)
        self.assertTrue(any('read_events("death")' in m for _, m in got))
        self.assertTrue(any("lineup.load_lineup() reads the stored lineup" in m for _, m in got))

    def test_a_gate_in_fixes_warns(self):
        got = _check({"reader": """
            FIXES = ("teardrop_box", "slab_gate")
            """})
        self.assertEqual(len(got), 1)
        self.assertIn("reader.py:2 slab_gate: FIXES holds 'slab_gate'", got[0][1])

    def test_the_allowlist_silences_defers_and_goes_stale(self):
        src = {"reader": """
            from . import track
            SEP_PX = 6
            FIXES = ("slab_gate",)
            def own(store, sid):
                return store.read_events("reader", sid)
            def read(a, b):
                return track.admits(a, b) and abs(a - b) > SEP_PX
            """}
        got = _check(src, {("reticle/reader.py", "own"): "reads back its own stream",
                           ("reticle/reader.py", "read"): "deferred: waits for its owner",
                           ("reticle/reader.py", "slab_gate"): "deferred: the slab gate",
                           ("reticle/reader.py", "name:SEP_PX"): "deferred: a separation",
                           ("reticle/reader.py", "gone"): "nothing here now",
                           ("reticle/reader.py", "name:GONE_PX"): "deferred: removed"})
        self.assertTrue(all(s == doctor.WARN for s, _ in got))
        text = "\n".join(m for _, m in got)
        self.assertNotIn("own stream", text)
        self.assertIn("read: track.admits() is a downstream rule (track-continuation) -- "
                      "deferred: waits for its owner", text)
        self.assertIn("slab_gate: FIXES holds 'slab_gate', a reader gate -- deferred:", text)
        self.assertIn("reader.py:3 SEP_PX: deferred: a separation", text)
        self.assertIn("RESTATED_GATES reticle/reader.py gone: matches nothing", text)
        self.assertIn("RESTATED_GATES reticle/reader.py name:GONE_PX: matches nothing", text)
        self.assertEqual(len(got), 5)

    def test_an_unlisted_match_takes_the_switchable_level(self):
        self.assertEqual(doctor.RESTATE_UNLISTED, doctor.WARN)

    def test_the_repository_has_no_stale_entry_and_no_error(self):
        got = doctor.check_restate()
        self.assertEqual([m for s, m in got if s == doctor.ERROR], [])
        self.assertEqual([m for _, m in got if "matches nothing" in m], [])


if __name__ == "__main__":
    unittest.main()
