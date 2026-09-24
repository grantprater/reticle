"""`doctor.check_uncalled`: owned producers no command reaches, and dead inputs."""
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import doctor


def _repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return root


OWNERSHIP = """
[[entry]]
id = "thing"
question = "What is the thing?"
owner = "m"
role = ["detect"]
status = "partial"
produces = ["wired", "cold", "drawn"]
not_for = "Anything else."
"""


class UncalledTests(unittest.TestCase):
    def setUp(self):
        self.root = _repo({
            "ownership.toml": OWNERSHIP,
            "reticle/cli.py": """
                from .m import wired
                from .overlay import render
                def cmd_run(args):
                    return wired(1, extra=2)
                def cmd_overlay(args):
                    return render()
            """,
            "reticle/overlay.py": """
                from .m import drawn
                def render():
                    return drawn()
            """,
            "reticle/m.py": """
                def wired(x, *, extra=None, never=None):
                    return x
                def cold():
                    return 0
                def drawn():
                    return 1
            """,
            "tools/t.py": "", "prototypes/p.py": "",
        })
        self.found = [m for _lv, m in doctor.check_uncalled(self.root)]

    def test_a_producer_no_command_reaches_is_flagged(self):
        self.assertTrue(any("cold" in m and "no CLI command" in m for m in self.found))

    def test_a_producer_reached_only_by_the_overlay_is_render_only(self):
        self.assertTrue(any("drawn" in m and "reached only through" in m
                            for m in self.found))

    def test_a_finding_outside_the_debt_list_is_an_error(self):
        levels = {m: lv for lv, m in doctor.check_uncalled(self.root)}
        self.assertTrue(all(lv == "ERROR" for lv in levels.values()))
        (self.root / "uncalled_debt.toml").write_text(
            'items = ["cold:thing:cold", "render:thing:drawn", "cold:thing:gone"]\n',
            encoding="utf-8")
        out = doctor.check_uncalled(self.root)
        cold = next(lv for lv, m in out if "produces cold" in m)
        drawn = next(lv for lv, m in out if "produces drawn" in m)
        self.assertEqual((cold, drawn), ("WARN", "WARN"))
        # A listed item no longer found must be deleted, so the list shrinks.
        self.assertTrue(any("cold:thing:gone" in m and "delete" in m for _lv, m in out))

    def test_a_wired_producer_is_not_flagged(self):
        self.assertFalse(any("produces wired" in m for m in self.found))

    def test_an_input_nobody_passes_is_flagged_and_a_passed_one_is_not(self):
        dead = [m for m in self.found if "never supplied" in m]
        self.assertEqual(len(dead), 1)
        self.assertIn("wired(never=)", dead[0])
        self.assertNotIn("extra", dead[0])


if __name__ == "__main__":
    unittest.main()
