import unittest

from reticle.adjudication import self_entry as se

PLAYER = {"agent": "KAY_O", "status": "resolved", "reason": None, "slot": 4,
          "player_agent_version": "player-agent-0.3.0"}


def _claim(channel, agent=None, reason=None, per_entry=None):
    ev = {"per_entry_agent": per_entry} if per_entry else {}
    return {"channel": channel, "agent": agent, "reason": reason, "evidence": ev}


def verdict(victim, killer, side="enemy", same=False, me_kill=False, me_death=False,
            etype="kill", second=False, round_no=1, t=1000.0, killer_cluster=None):
    """A stored death verdict with the per-entry portrait claims given:
    `victim` / `killer` an agent, None (refused) or ("cluster", agent) for a
    claim a name cluster replaced."""
    def claims(a, cluster=None):
        out = []
        if isinstance(a, tuple):
            out.append(_claim("killfeed_portrait", None, "replaced_by_name_cluster", a[1]))
        elif a is None:
            out.append(_claim("killfeed_portrait", None, "portrait_views_refused_or_disagree"))
        else:
            out.append(_claim("killfeed_portrait", a))
        if cluster is not None:
            out.append(_claim("killfeed_name_cluster", cluster))
        return out
    return {"kind": "death_verdict", "death_id": f"death:x:{int(t)}:0", "round_no": round_no,
            "t_ms": t, "slot": 0, "side": side, "same_side": same,
            "kf_player_kill": me_kill, "kf_player_death": me_death,
            "entry_type": {"type": etype}, "is_second_life": second, "is_revive": etype == "revive",
            "metadata": {"identity": {"claims": claims(victim)},
                         "killer_identity": {"claims": claims(killer, killer_cluster)}}}


def _run(rows, player=PLAYER):
    out = se.adjudicate(rows, player, "x")
    return out[0], [r for r in out if r["kind"] == "entry"], [r for r in out if r["kind"] == "round"]


class SideAndPortraitTests(unittest.TestCase):
    def test_the_bound_agent_on_the_ally_side_is_the_player(self):
        head, entries, _ = _run([verdict("Jett", "KAY_O", side="enemy", me_kill=True)])
        killer = entries[0]["roles"]["killer"]
        self.assertEqual(killer["side"], "ally")
        self.assertIs(killer["is_player"], True)
        self.assertEqual(killer["basis"], "side_portrait")
        self.assertEqual(killer["disagreements"], [])
        self.assertEqual((head["kills"], head["deaths"]), (1, 0))

    def test_the_side_separates_a_mirror(self):
        """The enemy's KAY/O kills an ally: no role is the player's."""
        head, entries, _ = _run([verdict("Sage", "KAY_O", side="ally", me_kill=True),
                                 verdict("Jett", "Sova", side="enemy", t=2000.0)])
        killer = entries[0]["roles"]["killer"]
        self.assertEqual(killer["side"], "enemy")
        self.assertIs(killer["is_player"], False)
        self.assertEqual(killer["disagreements"], ["me"])
        self.assertEqual(head["kills"], 0)

    def test_a_replaced_portrait_claim_keeps_the_per_entry_answer(self):
        _, entries, _ = _run([verdict(("cluster", "KAY_O"), "Jett", side="ally", me_death=True)])
        self.assertIs(entries[0]["roles"]["victim"]["is_player"], True)
        self.assertEqual(entries[0]["roles"]["victim"]["basis"], "side_portrait")


class FallbackTests(unittest.TestCase):
    def test_a_refused_portrait_falls_back_to_me(self):
        head, entries, _ = _run([verdict("Jett", None, side="enemy", me_kill=True)])
        killer = entries[0]["roles"]["killer"]
        self.assertEqual(killer["basis"], "me")
        self.assertIs(killer["is_player"], True)
        self.assertEqual(killer["witnesses"]["side_portrait"]["reason"],
                         "portrait_views_refused_or_disagree")
        self.assertEqual(head["kills"], 1)

    def test_a_capture_without_me_gives_absence_no_weight(self):
        """No role reads "Me": a refused portrait is unread, not "not the player"."""
        head, entries, _ = _run([verdict("Jett", None, side="enemy"),
                                 verdict("KAY_O", "Reyna", side="ally", t=2000.0)])
        self.assertFalse(head["me_printed"])
        killer = entries[0]["roles"]["killer"]
        self.assertIsNone(killer["is_player"])
        self.assertIn("me:capture_prints_no_me", killer["reason"])
        self.assertEqual((head["kills"], head["unread_kills"], head["deaths"]), (0, 1, 1))

    def test_the_name_cluster_answers_last(self):
        head, entries, _ = _run([verdict("Jett", None, side="enemy", killer_cluster="KAY_O")])
        killer = entries[0]["roles"]["killer"]
        self.assertEqual(killer["basis"], "name_cluster")
        self.assertEqual(killer["witnesses"]["name_cluster"]["rests_on"], "killfeed_portrait")
        self.assertEqual(head["kills"], 1)

    def test_an_unbound_player_leaves_only_the_text(self):
        unbound = {"agent": None, "status": "disagreement", "player_agent_version": "p"}
        _, entries, _ = _run([verdict("Jett", "KAY_O", side="enemy", me_kill=True)], unbound)
        killer = entries[0]["roles"]["killer"]
        self.assertEqual(killer["basis"], "me")
        self.assertEqual(killer["witnesses"]["side_portrait"]["reason"],
                         "player_unbound:disagreement")


class CountTests(unittest.TestCase):
    def test_second_lives_and_revives_count_nothing(self):
        head, _, _ = _run([verdict("KAY_O", "Jett", side="ally", etype="second_life_death",
                                   second=True, me_death=True),
                           verdict("KAY_O", "Sage", side="ally", same=True, etype="revive",
                                   t=2000.0)])
        self.assertEqual((head["kills"], head["deaths"]), (0, 0))

    def test_a_team_kill_is_no_kill(self):
        head, _, _ = _run([verdict("Sage", "KAY_O", side="ally", same=True, me_kill=True)])
        self.assertEqual(head["kills"], 0)

    def test_rounds_sum_to_the_head(self):
        head, _, rounds = _run([verdict("Jett", "KAY_O", me_kill=True, round_no=1),
                                verdict("KAY_O", "Jett", side="ally", me_death=True,
                                        round_no=2, t=2000.0)])
        self.assertEqual([(r["round_no"], r["kills"], r["deaths"]) for r in rounds],
                         [(1, 1, 0), (2, 0, 1)])
        self.assertEqual(head["portrait_vs_me"], {"agree": 4})


if __name__ == "__main__":
    unittest.main()
