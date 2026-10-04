"""The held-out scorer's split and tallies: the headline keeps after_cast and control frames outside the dev
sessions and the tuned-label windows; unsure, smoke, other-agent and typed marks are never named right or
wrong; a truth outside the kit counts wrong and is reported."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import minimap_glyph_eval as ev  # noqa: E402


def row(kind="after_cast", dev=False, near=False):
    return {"kind": kind, "dev_session": dev, "near_tuned_label": near}


class Subsets(unittest.TestCase):
    def test_headline(self):
        self.assertEqual(ev.heldout_subsets(row()), ["headline"])
        self.assertEqual(ev.heldout_subsets(row("control")), ["headline"])

    def test_apart(self):
        self.assertEqual(ev.heldout_subsets(row(dev=True)), ["dev_session"])
        self.assertEqual(ev.heldout_subsets(row(near=True)), ["near_tuned_label"])
        self.assertEqual(ev.heldout_subsets(row(dev=True, near=True)), ["dev_session", "near_tuned_label"])
        self.assertEqual(ev.heldout_subsets(row("audit_excluded")), ["audit_only"])
        self.assertEqual(ev.heldout_subsets(row("audit_excluded", near=True)), ["audit_only", "near_tuned_label"])


class Marks(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(ev.mark_class({"ability": "Sova:C"}), "named")
        self.assertEqual(ev.mark_class({"ability": None, "unsure": True}), "unsure")
        for a in ("smoke", "other_agent", "other"):
            self.assertEqual(ev.mark_class({"ability": a}), a)

    def test_tally(self):
        def m(truth, pred, cls="named", in_kit=True):
            return {"class": cls, "subsets": ["headline"], "truth": truth, "truth_name": "x", "agent": truth.split(":")[0],
                    "truth_in_kit": in_kit, "follow_pred": pred, "base_pred": pred}
        M = [m("Sova:C", "Sova:C"), m("Sova:E", "Sova:C"), m("Miks:C", "Miks:Q", in_kit=False), m("Sova:Q", None),
             {"class": "unsure", "subsets": ["headline"]}, {"class": "other", "subsets": ["headline"]}]
        s = ev.naming_summary(M, "headline")
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["follow"], {"right": 1, "wrong": 2, "refused": 1, "accuracy": 0.25})
        self.assertEqual(s["truth_outside_kit"], 1)
        self.assertEqual(s["confusions"]["Sova:E -> Sova:C"], 1)
        self.assertEqual(ev.naming_summary(M, "dev_session")["n"], 0)


if __name__ == "__main__":
    unittest.main()
