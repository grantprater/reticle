"""Which sessions the acceptance harness admits (`reticle.harness.extras.refuse`).

No store is read: `refuse` checks only the session id.
"""
import unittest

from reticle.harness import extras as tr
from reticle.harness import run as qa


class RefuseScopeTests(unittest.TestCase):
    def test_the_development_matches_and_the_new_captures_are_admitted(self):
        for sid in ("9acf02f98283", "c817691bcd15", "d3dcfb182ab1",
                    "cadaadeb2d8b", "066741deafe5", "9912c382130b"):
            self.assertIsNone(tr.refuse(sid))

    def test_the_held_out_match_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "held-out"):
            tr.refuse("cea8ecbc94ab")

    def test_an_archived_session_is_refused(self):
        # b7d24102a6f6 is retired (the store's retirement/retirements.jsonl).
        with self.assertRaisesRegex(SystemExit, "neither a development match"):
            tr.refuse("b7d24102a6f6")

    def test_the_harness_takes_its_set_from_teardrop_refusals(self):
        self.assertIs(qa.SCORED, tr.SCORED)
        self.assertIs(qa.NEW, tr.NEW)
        self.assertNotIn(tr.HELD_OUT, tr.SCORED)

    def test_the_lane_check_refuses_outside_the_scored_set(self):
        from reticle.harness import sets as elc
        with self.assertRaisesRegex(SystemExit, "held-out"):
            elc.build_sets("cea8ecbc94ab")
        with self.assertRaisesRegex(SystemExit, "neither a development match"):
            elc.build_sets("b7d24102a6f6")


if __name__ == "__main__":
    unittest.main()
