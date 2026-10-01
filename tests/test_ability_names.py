"""`adjudication.weapon.ABILITY_CANONICAL_NAMES` against the reference's slots.

The table names each reference asset stem (`<Agent>_<slot>`). Phoenix's
Ability1 read Curveball here until 2026-10-01, so the killfeed labeller
captioned the Hot Hands art "Curveball" [domain:killfeed/phoenix-hot-hands-icon];
these tests compare every entry with `<store>/reference/abilities.json`.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import PureWindowsPath

from reticle.adjudication.weapon import ABILITY_CANONICAL_NAMES, ability_agent
from reticle.store import DEFAULT_STORE

REFERENCE = DEFAULT_STORE / "reference" / "abilities.json"
SLOTS = ("Ability1", "Ability2", "Grenade", "Ultimate")


def _norm(name: str) -> str:
    """Casing and spacing are ours; the words are the reference's."""
    return re.sub(r"\s+", " ", name).strip().casefold()


def reference_names() -> dict[str, str]:
    """Asset stem -> the reference's name for that slot."""
    agents = json.loads(REFERENCE.read_text(encoding="utf-8"))["agents"]
    out = {}
    for agent in agents.values():
        for ab in agent["abilities"]:
            f = (ab.get("icon") or {}).get("file")
            if f:
                out[PureWindowsPath(f).stem] = ab["name"]
    return out


@unittest.skipUnless(REFERENCE.is_file(), "no reference in the store")
class AgainstReferenceTests(unittest.TestCase):
    def test_every_entry_names_the_reference_slot(self):
        ref = reference_names()
        wrong = {stem: (name, ref.get(stem)) for stem, name in ABILITY_CANONICAL_NAMES.items()
                 if ref.get(stem) is None or _norm(ref[stem]) != _norm(name)}
        self.assertEqual(wrong, {})

    def test_every_reference_slot_is_named(self):
        ref = reference_names()
        missing = sorted(s for s in ref if s.rsplit("_", 1)[1] in SLOTS
                         and s not in ABILITY_CANONICAL_NAMES)
        self.assertEqual(missing, [])


class PhoenixTests(unittest.TestCase):
    def test_phoenix_slots(self):
        # [domain:abilities/phoenix-slots]: Q (Ability1) Hot Hands, E (Ability2) Curveball.
        self.assertEqual(ABILITY_CANONICAL_NAMES["Phoenix_Ability1"], "Hot Hands")
        self.assertEqual(ABILITY_CANONICAL_NAMES["Phoenix_Ability2"], "Curveball")
        self.assertEqual(ABILITY_CANONICAL_NAMES["Phoenix_Grenade"], "Blaze")
        self.assertEqual(ability_agent("Hot Hands"), "Phoenix")


if __name__ == "__main__":
    unittest.main()
