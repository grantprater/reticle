import unittest

from reticle.agent_names import (agent_in, agent_key, canonical_agent,
                                 reference_agent, same_agent)


class AgentNamesTests(unittest.TestCase):
    def test_every_spelling_of_kayo_is_one_agent(self):
        for a in ("KAY/O", "KAY_O", "kayo", " Kay/O "):
            for b in ("KAY/O", "KAY_O", "kayo"):
                self.assertIs(same_agent(a, b), True, (a, b))
        self.assertEqual({agent_key(n) for n in ("KAY/O", "KAY_O", "kayo")}, {"kayo"})

    def test_unknown_names_compare_as_unknown(self):
        self.assertIsNone(same_agent(None, "Iso"))
        self.assertIsNone(same_agent("", "Iso"))
        self.assertIs(same_agent("Iso", "Omen"), False)

    def test_the_stored_spelling_is_the_asset_stem(self):
        self.assertEqual(canonical_agent("KAY/O"), "KAY_O")
        self.assertEqual(canonical_agent("KAY_O"), "KAY_O")
        self.assertEqual(canonical_agent("Phoenix"), "Phoenix")
        self.assertIsNone(canonical_agent(None))

    def test_a_collection_is_searched_by_key(self):
        ref = {"KAY/O": 1, "Omen": 2}
        self.assertEqual(reference_agent("KAY_O", ref), "KAY/O")
        self.assertEqual(reference_agent("kayo", ref), "KAY/O")
        self.assertEqual(reference_agent("Omen", ref), "Omen")
        self.assertIsNone(reference_agent("Iso", ref))
        self.assertIsNone(reference_agent(None, ref))
        self.assertTrue(agent_in("KAY/O", ("Phoenix", "KAY_O")))
        self.assertFalse(agent_in(None, ("Phoenix", "KAY_O")))


if __name__ == "__main__":
    unittest.main()
