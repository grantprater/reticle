"""`adjudication.smoke_owner` over synthetic smoke tracks and lineups."""
import unittest

from reticle.adjudication import smoke_owner

SID = "s"


def lineup(ally, player_slot=0, unresolved=()):
    """A lineup whose arbiter resolved every ally slot but `unresolved`."""
    sides = {"ally": [{"slot": i, "agent": a} for i, a in enumerate(ally)],
             "enemy": [{"slot": i, "agent": a} for i, a in
                       enumerate(["Reyna", "Sova", "Sage", "Raze", "Fade"])]}
    ident = []
    for side in ("ally", "enemy"):
        for r in sides[side]:
            ok = not (side == "ally" and r["slot"] in unresolved)
            ident.append({"entity_id": f"{SID}:{side}:slot:{r['slot']}",
                          "status": "resolved" if ok else "abstained",
                          "agent": r["agent"] if ok else None})
    return {"sides": sides, "player": {"slot": player_slot}, "agent_identity": ident}


def track(i, first_s, life_s, onset="observed", end="observed"):
    return {"kind": "track", "track": i, "first_ms": first_s * 1000.0,
            "last_ms": (first_s + life_s) * 1000.0, "life_s": life_s,
            "onset_status": onset, "end_status": end, "cx": 10.0, "cy": 10.0}


def rows(*tracks):
    return [{"kind": "coverage", "smoke_version": "smoke-0.2.0"}, *tracks]


def owners(res):
    return {r["track"]: r for r in res["rows"][1:]}


class SmokeOwner(unittest.TestCase):
    def test_a_lone_team_smoke_agent_names_every_track(self):
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0), track(1, 50, 4.0, onset="censored:unobserved")),
                                     lineup(["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"]))
        got = owners(res)
        self.assertEqual({r["agent"] for r in got.values()}, {"Miks"})
        self.assertEqual(got[0]["rules"], ["smoke_lifetime", "team_smoke_agent"])
        self.assertEqual(got[1]["rules"], ["team_smoke_agent"])
        # Every claim rests on the lineup, so none is an independent witness.
        self.assertTrue(all(c["depends_on"] for c in res["claims"]))

    def test_two_agents_are_told_apart_by_lifetime(self):
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0), track(1, 40, 15.0), track(2, 70, 3.0)),
                                     lineup(["Jett", "Miks", "Sova", "Reyna", "Sage"]))
        got = owners(res)
        self.assertEqual(got[0]["agent"], "Miks")
        self.assertIsNone(got[1]["agent"])
        self.assertEqual(got[1]["reason"], "lifetime_fits_no_candidate")
        self.assertEqual(got[2]["agent"], "Jett")

    def test_a_censored_track_names_only_by_excluding_the_shorter(self):
        res = smoke_owner.adjudicate(
            SID, rows(track(0, 10, 16.5, end="censored:unobserved"),
                      track(1, 40, 12.0, end="censored:unobserved")),
            lineup(["Omen", "Miks", "Sova", "Reyna", "Sage"], player_slot=2))
        got = owners(res)
        self.assertEqual(got[0]["agent"], "Miks")
        self.assertIsNone(got[1]["agent"])
        self.assertTrue(got[1]["reason"].startswith("censored_lifetime"))

    def test_an_unmeasured_candidate_blocks_the_lifetime_rule(self):
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0)),
                                     lineup(["Brimstone", "Miks", "Sova", "Reyna", "Sage"]))
        r = owners(res)[0]
        self.assertIsNone(r["agent"])
        self.assertEqual(r["reason"], "no_lifetime_for Brimstone")

    def test_lifetimes_within_error_refuse(self):
        saved = dict(smoke_owner.LIFETIME_S)
        smoke_owner.LIFETIME_S["Clove"] = (17.5, 17.75, "test")
        try:
            res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0)),
                                         lineup(["Clove", "Miks", "Sova", "Reyna", "Sage"]))
        finally:
            smoke_owner.LIFETIME_S.clear()
            smoke_owner.LIFETIME_S.update(saved)
        self.assertTrue(owners(res)[0]["reason"].startswith("lifetimes_within_error"))

    def test_a_bulk_cast_is_never_omens_and_shares_one_caster(self):
        res = smoke_owner.adjudicate(
            SID, rows(track(0, 10, 18.0), track(1, 10, 9.0, end="censored:unobserved")),
            lineup(["Omen", "Brimstone", "Sova", "Reyna", "Sage"], player_slot=2))
        got = owners(res)
        # Omen is excluded by the pair; Brimstone is left alone.
        self.assertEqual(got[0]["candidates"], ["Brimstone"])
        self.assertEqual(got[0]["agent"], "Brimstone")
        self.assertEqual(got[1]["agent"], "Brimstone")

    def test_bulk_cast_carries_a_name_to_a_censored_mate(self):
        res = smoke_owner.adjudicate(
            SID, rows(track(0, 10, 18.0), track(1, 10, 2.0, end="censored:unobserved")),
            lineup(["Jett", "Miks", "Sova", "Reyna", "Sage"], player_slot=2))
        got = owners(res)
        self.assertEqual(got[0]["agent"], "Miks")
        self.assertEqual(got[1]["agent"], "Miks")
        self.assertEqual(got[1]["rules"], ["bulk_cast"])
        claim = next(c for c in res["claims"] if c["channel"] == "bulk_cast"
                     and c["entity_id"] == got[1]["entity_id"])
        self.assertEqual(claim["depends_on"], [got[0]["entity_id"]])

    def test_the_players_tray_names_and_conflicts(self):
        lu = lineup(["Omen", "Miks", "Sova", "Reyna", "Sage"], player_slot=0)
        casts = [{"slot": "E", "t_ms": 9000.0, "player_cast": True, "reason": None}]
        res = smoke_owner.adjudicate(
            SID, rows(track(0, 10, 15.0), track(1, 40, 17.0, end="censored:unobserved"),
                      track(2, 70, 18.0)), lu, tray_casts=casts, tray_reason=None)
        got = owners(res)
        self.assertEqual(got[0]["agent"], "Omen")
        self.assertIn("player_tray", got[0]["rules"])
        # No drop before the birth: the other smoke agent.
        self.assertEqual(got[1]["agent"], "Miks")
        # A tray cast against a lifetime that says otherwise is refused.
        casts.append({"slot": "E", "t_ms": 69000.0, "player_cast": True, "reason": None})
        res = smoke_owner.adjudicate(SID, rows(track(2, 70, 18.0)), lu,
                                     tray_casts=casts, tray_reason=None)
        r = owners(res)[2]
        self.assertIsNone(r["agent"])
        self.assertEqual(r["reason"], "tray_cast_conflict")

    def test_a_refused_drop_in_the_window_leaves_the_cast_open(self):
        lu = lineup(["Omen", "Brimstone", "Sova", "Reyna", "Sage"], player_slot=0)
        casts = [{"slot": "E", "t_ms": 9000.0, "player_cast": False, "reason": "forced"}]
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 15.0)), lu,
                                     tray_casts=casts, tray_reason=None)
        r = owners(res)[0]
        self.assertIsNone(r["agent"])
        self.assertIn("no_lifetime_for Brimstone", r["reason"])
        self.assertEqual(r["by_channel"]["player_tray"]["reason"], "tray_drop_refused forced")

    def test_no_lineup_and_an_incomplete_side_refuse(self):
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0)), None)
        self.assertEqual(owners(res)[0]["reason"], "no_lineup")
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0)),
                                     lineup(["Phoenix", "Miks", "Sova", "Reyna", "Sage"],
                                            unresolved=(3,)))
        self.assertTrue(owners(res)[0]["reason"].startswith("ally_side_incomplete"))

    def test_identity_events_come_from_the_arbiter(self):
        res = smoke_owner.adjudicate(SID, rows(track(0, 10, 18.0)),
                                     lineup(["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"]))
        self.assertEqual(len(res["events"]), 1)
        self.assertEqual(res["rows"][0]["by_agent"], {"Miks": 1})


if __name__ == "__main__":
    unittest.main()
