"""The killfeed entry type from every revive witness at once
(`adjudication.death.decide_entry_type`): agreement, each kind of
disagreement, a missing witness, the context gate and a KAY/O revive with no
prior down."""
import unittest

from reticle.adjudication.death import (decide_entry_type, entry_witnesses, icon_witness,
                                        plate_revive, revive_context, revive_entry,
                                        ring_witness, type_round_entries)

SIDES = {"ally": [{"agent": a} for a in ("Sage", "Raze", "Sova", "Reyna", "Killjoy")],
         "enemy": [{"agent": a} for a in ("Jett", "KAY_O", "Clove", "Omen", "Skye")]}


def w(icon=None, ring=None, plates=None):
    """Three witness claims with the given values; None carries a reason."""
    def c(name, v):
        return {"witness": name, "value": v, "reason": None if v is not None else "unread",
                "evidence": {}}
    return {"icon": c("icon", icon), "ring": c("ring", ring), "plates": c("plates", plates)}


OPEN = {"witness": "context", "value": True, "reason": None}
CLOSED = {"witness": "context", "value": False, "reason": "Sage:prior_death"}
UNCHECKED = {"witness": "context", "value": None, "reason": "context_unchecked"}


def obs(t, slot, ringed, wx0=200, wx1=240, reason=None):
    return {"kind": "weapon_icon_observation", "t_ms": t, "slot": slot, "wx0": wx0, "wx1": wx1,
            "grid": "00", "aspect": 1.0, "ringed": ringed,
            "ring_reason": reason if ringed is None else None, "ring": {"cover": 1.0 if ringed else 0.5}}


class AgreementTests(unittest.TestCase):

    def test_every_witness_agrees_on_a_revive(self):
        d = decide_entry_type(w(True, True, True), OPEN)
        self.assertEqual((d["status"], d["type"], d["rule"]), ("resolved", "revive", 1))
        self.assertIsNone(d["disagreement"])
        self.assertEqual(d["alternatives"][0], {"type": "revive", "for": ["icon", "plates", "ring"],
                                                "against": []})

    def test_every_witness_agrees_on_a_kill(self):
        d = decide_entry_type(w(False, False, False), OPEN)
        self.assertEqual((d["type"], d["disagreement"]), ("kill", None))
        d = decide_entry_type(w(False, False, False), OPEN, is_second_life=True)
        self.assertEqual(d["type"], "second_life_death")

    def test_one_colour_plates_beside_a_named_gun_are_no_disagreement(self):
        """A team kill and an environmental death are one colour too."""
        d = decide_entry_type(w(False, False, True), OPEN)
        self.assertEqual((d["type"], d["disagreement"]), ("kill", None))


class DisagreementTests(unittest.TestCase):

    def test_icon_against_ring_refuses(self):
        for icon, ring in ((True, False), (False, True)):
            d = decide_entry_type(w(icon, ring, True), OPEN)
            self.assertEqual((d["status"], d["type"], d["reason"]),
                             ("refused", None, "slot_witnesses_disagree"))
            self.assertIn("icon", d["disagreement"]["revive" if icon else "not_revive"])
            self.assertIn("ring", d["disagreement"]["not_revive" if icon else "revive"])
            # Both alternatives stay, with their witnesses.
            self.assertEqual({a["type"] for a in d["alternatives"]}, {"revive", "kill"})

    def test_two_coloured_plates_against_a_slot_revive_refuse(self):
        for icon, ring in ((True, True), (True, None), (None, True)):
            d = decide_entry_type(w(icon, ring, False), OPEN)
            self.assertEqual(d["reason"], "plates_two_colours_against_slot")
            self.assertEqual(d["disagreement"]["not_revive"], ["plates"])

    def test_no_single_witness_decides_against_another(self):
        """The ring alone against the icon and the plates alone against the
        ring refuse; neither is outvoted."""
        self.assertEqual(decide_entry_type(w(False, True, None), OPEN)["status"], "refused")
        self.assertEqual(decide_entry_type(w(None, True, False), OPEN)["status"], "refused")

    def test_refused_entry_is_not_a_revive_for_the_roster(self):
        e = {"t_ms": 0.0, "entry_type": decide_entry_type(w(True, False, True), OPEN)}
        self.assertFalse(revive_entry(e))


class MissingWitnessTests(unittest.TestCase):

    def test_a_silent_witness_leaves_the_others_to_decide(self):
        self.assertEqual(decide_entry_type(w(None, True, True), OPEN)["type"], "revive")
        self.assertEqual(decide_entry_type(w(True, None, None), OPEN)["type"], "revive")
        self.assertEqual(decide_entry_type(w(None, False, None), OPEN)["type"], "kill")

    def test_plates_decide_only_with_the_slot_silent(self):
        """bdfdcf009dba 1310.0 s: the Resurrection icon went unnamed."""
        d = decide_entry_type(w(None, None, True), OPEN)
        self.assertEqual((d["type"], d["rule"]), ("revive", 3))
        self.assertEqual(decide_entry_type(w(None, None, False), OPEN)["type"], "kill")

    def test_nothing_witnessed_refuses(self):
        d = decide_entry_type(w(None, None, None), OPEN)
        self.assertEqual((d["status"], d["reason"]), ("refused", "no_revive_witness"))

    def test_witness_claims_carry_their_reasons(self):
        self.assertEqual(icon_witness({})["reason"], "no_weapon_stream")
        self.assertEqual(icon_witness({"weapon_evidence": {"status": "refused", "name": None,
                                                           "reason": "new"}})["reason"],
                         "icon_new")
        self.assertIs(icon_witness({"weapon_evidence": {"status": "resolved",
                                                        "name": "Resurrection"}})["value"], True)
        self.assertIs(icon_witness({"weapon_evidence": {"status": "resolved",
                                                        "name": "Vandal"}})["value"], False)
        entry = {"t_first": 1000.0, "t_last": 3000.0, "slot": 0, "sig": 200}
        self.assertEqual(ring_witness(entry, None)["reason"], "no_weapon_stream")
        self.assertEqual(ring_witness(entry, [])["reason"], "no_bound_frame")
        old = [{k: v for k, v in obs(1000.0, 0, True).items() if not k.startswith("ring")}]
        self.assertEqual(ring_witness(entry, old)["reason"], "no_ring_field")
        self.assertEqual(ring_witness(entry, [obs(1000.0, 0, None, reason="uncertain_fit")]
                                      )["reason"], "ring_uncertain_fit")
        self.assertIs(ring_witness(entry, [obs(1000.0, 0, True)])["value"], True)
        split = [obs(1000.0, 0, True), obs(1500.0, 0, False)]
        self.assertEqual(ring_witness(entry, split)["reason"], "ring_frames_disagree")
        self.assertEqual(plate_revive({"same_side": None})["reason"], "plates_unread")
        self.assertIs(plate_revive({"same_side": False})["value"], False)
        self.assertIs(plate_revive({"same_side": True}, (False, None))["value"], True)
        self.assertEqual(plate_revive({"same_side": True}, (True, None))["reason"], "self_entry")
        self.assertEqual(plate_revive({"same_side": True})["reason"], "no_name_check")

    def test_entry_witnesses_are_three_separate_claims(self):
        entry = {"t_first": 1000.0, "t_last": 3000.0, "slot": 0, "sig": 200, "same_side": True,
                 "weapon_evidence": {"status": "resolved", "name": "Resurrection"}}
        ws = entry_witnesses(entry, [obs(1000.0, 0, True), obs(1500.0, 0, True)], (False, None))
        self.assertEqual({k: v["value"] for k, v in ws.items()},
                         {"icon": True, "ring": True, "plates": True})
        self.assertEqual(ws["ring"]["evidence"]["frames"][0][:3], [1000.0, 0, True])


class ContextGateTests(unittest.TestCase):

    def test_a_closed_gate_refuses_a_revive_and_never_makes_one(self):
        d = decide_entry_type(w(True, True, True), CLOSED)
        self.assertEqual((d["status"], d["reason"]), ("refused", "revive_against_context"))
        self.assertEqual(d["disagreement"]["context"], "Sage:prior_death")
        self.assertEqual(decide_entry_type(w(False, False, False), OPEN)["type"], "kill")

    def test_an_unchecked_gate_lets_a_revive_stand_and_says_so(self):
        d = decide_entry_type(w(True, True, True), UNCHECKED)
        self.assertEqual((d["type"], d["context_unchecked"]), ("revive", "context_unchecked"))

    def test_sage_needs_a_dead_teammate(self):
        e = {"t_ms": 5000.0, "side": "ally"}
        ctx = revive_context(e, [], SIDES, lineup_version="lineup-x", mechanism="Sage")
        self.assertIs(ctx["value"], False)
        self.assertEqual(ctx["rests_on"], [{"context": "lineup", "version": "lineup-x"}])
        dead = {"t_ms": 3000.0, "side": "ally", "entry_type": {"type": "kill"}}
        self.assertIs(revive_context(e, [dead], SIDES, mechanism="Sage")["value"], True)

    def test_sage_named_dead_cannot_revive(self):
        e = {"t_ms": 5000.0, "side": "ally"}
        dead = {"t_ms": 3000.0, "side": "ally", "entry_type": {"type": "kill"}}
        ctx = revive_context(e, [dead], SIDES, mechanism="Sage",
                             victims={3000.0: ("Sage", "death:s:3000:0")})
        self.assertIs(ctx["value"], False)
        self.assertEqual(ctx["depends_on"], ["death:s:3000:0"])

    def test_a_reviver_not_fielded_closes_the_gate(self):
        e = {"t_ms": 5000.0, "side": "enemy"}
        dead = {"t_ms": 3000.0, "side": "enemy", "entry_type": {"type": "kill"}}
        self.assertIs(revive_context(e, [dead], SIDES, mechanism="Sage")["value"], False)
        self.assertIs(revive_context(e, [dead], SIDES, mechanism="Clove")["value"], True)
        # An unnamed lineup slot leaves the check open, never closed.
        sides = {"enemy": [{"agent": None}, {"agent": "Jett"}]}
        self.assertIsNone(revive_context(e, [dead], sides, mechanism="Sage")["value"])


class KayoReviveTests(unittest.TestCase):
    """A KAY/O revive entry always follows his down entry in the same round
    [domain:killfeed/kayo-downed-entry]; one without it is a misread."""

    def test_a_kayo_revive_without_a_prior_down_refuses(self):
        e = {"t_ms": 799500.0, "t_first": 799500.0, "t_last": 800500.0, "slot": 1,
             "side": "enemy", "same_side": True, "plate_names": (False, None),
             "weapon_evidence": {"status": "resolved", "name": "NULL/cmd"}}
        (typed,) = type_round_entries([e], SIDES)
        d = typed["entry_type"]
        self.assertEqual((d["status"], d["reason"]), ("refused", "revive_against_context"))
        self.assertIn("KAY_O:", d["context"]["reason"])
        self.assertFalse(revive_entry(typed))

    def test_a_kayo_revive_after_his_named_down_is_a_revive(self):
        down = {"t_ms": 790000.0, "t_first": 790000.0, "t_last": 794500.0, "slot": 1,
                "side": "enemy", "same_side": False,
                "weapon_evidence": {"status": "resolved", "name": "Classic"}}
        rev = {"t_ms": 799500.0, "t_first": 799500.0, "t_last": 800500.0, "slot": 1,
               "side": "enemy", "same_side": True, "plate_names": (False, None),
               "weapon_evidence": {"status": "resolved", "name": "NULL/cmd"}}
        typed = type_round_entries([down, rev], SIDES,
                                   victims={790000.0: ("KAY_O", "death:s:790000:1")})
        self.assertEqual([t["entry_type"]["type"] for t in typed], ["kill", "revive"])
        self.assertEqual(typed[1]["entry_type"]["context"]["depends_on"], ["death:s:790000:1"])
        # Another named victim is no down of his: the revive refuses.
        typed = type_round_entries([down, rev], SIDES,
                                   victims={790000.0: ("Omen", "death:s:790000:1")})
        self.assertEqual(typed[1]["entry_type"]["reason"], "revive_against_context")
        # An unnamed earlier victim leaves the check open.
        typed = type_round_entries([down, rev], SIDES, victims={})
        self.assertEqual(typed[1]["entry_type"]["type"], "revive")
        self.assertIsNone(typed[1]["entry_type"]["context"]["value"])


if __name__ == "__main__":
    unittest.main()
