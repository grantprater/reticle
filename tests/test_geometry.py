"""The (map, profile) geometry key, and what it refuses.

These are cheap and they exist because the failure they guard is not: under the
per-session layout a session could silently read geometry belonging to a
different widget size, and the only symptom was confident answers about the
wrong pixels. Everything here runs against a temporary store, never the real one.
"""
import json
import tempfile
import unittest
from pathlib import Path

from reticle import geometry as G


def _store(sessions):
    root = Path(tempfile.mkdtemp())
    (root / "manifests").mkdir(parents=True)
    for sid, (profile, tags, frames) in sessions.items():
        (root / "manifests" / f"{sid}.json").write_text(json.dumps({
            "session_id": sid, "source_profile": profile, "tags": tags,
            "source": {"frame_count": frames}}), encoding="utf-8")
    return root


CORPUS = {
    "long_ascent_big": ("valorant-16x9-bigmap", ["map:ascent"], 139288),
    "demo_ascent_big": ("valorant-16x9-bigmap", ["map:ascent", "ability-demo"], 2266),
    "long_ascent_small": ("valorant-16x9", ["map:ascent"], 143309),
    "untagged": ("valorant-16x9", ["ability-demo"], 3096),
}


class GeometryKey(unittest.TestCase):
    def setUp(self):
        self.root = _store(CORPUS)

    def test_key_round_trips(self):
        k = G.key("ascent", "valorant-16x9-bigmap")
        self.assertEqual(G.parse(k), ("ascent", "valorant-16x9-bigmap"))

    def test_parse_refuses_a_non_key(self):
        with self.assertRaises(ValueError):
            G.parse("ascent")

    def test_profile_is_part_of_the_key(self):
        """The same map at two widget sizes is two geometries, not one.

        Every constant in `minimap.py` is in widget pixels, so sharing one npz
        across profiles would be the exact defect the old `DONOR` check hunted.
        """
        big = G.key_of("long_ascent_big", self.root)
        small = G.key_of("long_ascent_small", self.root)
        self.assertNotEqual(big, small)
        self.assertNotEqual(G.path(big, self.root), G.path(small, self.root))

    def test_sessions_on_one_key_share_one_path(self):
        self.assertEqual(G.path_of("long_ascent_big", self.root),
                         G.path_of("demo_ascent_big", self.root))

    def test_an_untagged_session_reaches_no_geometry(self):
        self.assertIsNone(G.key_of("untagged", self.root))
        self.assertIsNone(G.path_of("untagged", self.root))
        self.assertIn("untagged", G.untagged(self.root))

    def test_require_says_which_failure_it_is(self):
        with self.assertRaises(SystemExit) as no_tag:
            G.require("untagged", self.root)
        self.assertIn("map:", str(no_tag.exception))
        with self.assertRaises(SystemExit) as not_built:
            G.require("long_ascent_big", self.root)
        self.assertIn("minimap_geometry", str(not_built.exception))

    def test_the_reference_session_is_the_longest_recording(self):
        """A 37s demo clip must never be the source of a shared static map.

        The static is a per-pixel median, so a clip built around one deliberate
        cast bakes the cast in -- measured at 347 px of false "plantable" on a
        real Cypher clip.
        """
        k = G.key("ascent", "valorant-16x9-bigmap")
        self.assertEqual(G.sessions_for(k, self.root),
                         ["long_ascent_big", "demo_ascent_big"])
        self.assertEqual(G.reference_session(k, self.root), "long_ascent_big")

    def test_keys_in_store_skips_what_it_cannot_name(self):
        self.assertEqual(G.keys_in_store(self.root),
                         [G.key("ascent", "valorant-16x9"),
                          G.key("ascent", "valorant-16x9-bigmap")])

    def test_fit_shares_the_geometry_key(self):
        """The art fit depends on map and widget, so it is cached the same way."""
        self.assertEqual(G.fit_path_of("long_ascent_big", self.root).stem,
                         G.path_of("long_ascent_big", self.root).stem)

    def test_a_missing_manifest_is_not_an_exception(self):
        self.assertIsNone(G.key_of("nope", self.root))
        self.assertIsNone(G.manifest("nope", self.root))


if __name__ == "__main__":
    unittest.main()
