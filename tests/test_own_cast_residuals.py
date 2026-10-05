"""Synthetic checks of prototypes/own_cast_residuals.py: one cause per missing
or extra cast on a built slot. No store is read; every input is built here."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import own_cast_residuals as ocr  # noqa: E402


def row(t_s, slot="E", reason=None, frm=1.0, to=0.0, kit="Sova", **kw):
    return {"t_ms": 1000.0 * t_s, "slot": slot, "reason": reason, "player_cast": reason is None,
            "from": frm, "to": to, "kit_read": kit, "forced": False, **kw}


def slot(rows, riot, slot_key="E", agent="Sova", others=(), **kw):
    mine = [r for r in rows if r["slot"] == slot_key]
    return {"session": "s", "agent": agent, "slot": slot_key, "riot": riot,
            "ours": sum(r["player_cast"] for r in mine), "rows": mine,
            "all_rows": list(rows) + list(others), "unwitnessed": [], "lines": [],
            "state_falls": [], "held_at_death": [], "excess_casts": [], "tray_state": None, **kw}


class Missing(unittest.TestCase):
    def test_a_witnessed_refused_drop_is_a_gate_refusal(self):
        rows = [row(10), row(50, reason="cooccur_among_casts", spend_witness=["countdown"])]
        items = ocr.attribute_slot(slot(rows, riot=2))
        self.assertEqual([(i["class"], i["cause"], i["how"]) for i in items],
                         [(3, "cooccur_among_casts", "own_kit_drop")])
        self.assertEqual(items[0]["t_ms"], 50000.0)

    def test_phase_death_screen_and_unwitnessed_full_landing_are_no_candidates(self):
        rows = [row(10),
                row(60, reason="phase:buy_phase", spend_witness=["icon"]),
                row(80, reason="after_player_death", kit_end_ms=79500.0),
                row(90, reason="equip_release", frm=1.4, to=0.98)]
        items = ocr.attribute_slot(slot(rows, riot=2))
        self.assertEqual([(i["class"], i["cause"]) for i in items], [(7, "no_drop_no_witness")])

    def test_a_drop_with_every_other_slot_falling_is_the_tray_not_a_cast(self):
        rows = [row(10), row(70, reason="cooccur_among_casts", spend_witness=["countdown"])]
        others = [row(70, slot="C", reason="cooccur_among_casts"),
                  row(70.5, slot="Q", reason="cooccur_among_casts")]
        items = ocr.attribute_slot(slot(rows, riot=2, others=others))
        self.assertEqual(items[0]["class"], 7)

    def test_an_own_ult_line_places_the_refused_x_drop(self):
        rows = [row(100, slot="X"),
                row(212, slot="X", reason="after_player_death", to=0.0, kit_end_ms=210000.0),
                row(203, slot="X", reason="pips_lit", frm=1.2, to=0.9)]
        s = slot(rows, riot=2, slot_key="X", agent="Phoenix", lines=[99000.0, 202000.0])
        items = ocr.attribute_slot(s)
        self.assertEqual([(i["class"], i["cause"], i["how"]) for i in items],
                         [(3, "after_player_death", "ult_line")])
        self.assertEqual(items[0]["t_ms"], 212000.0)

    def test_a_charge_held_at_a_death_is_a_spectated_kit(self):
        held = [{"t_ms": 40000.0, "charges": 1, "fact": "abilities/clove-smokes-after-death"}]
        items = ocr.attribute_slot(slot([row(10, kit="Clove")], riot=2, agent="Clove",
                                        held_at_death=held))
        self.assertEqual([(i["class"], i["cause"]) for i in items],
                         [(1, "spectated_kit_after_death")])

    def test_a_fall_right_after_a_cast_of_its_slot_is_that_cast(self):
        s = slot([row(10)], riot=3, state_falls=[(12000.0, 14000.0), (60000.0, 64000.0)],
                 tray_state=lambda t, t0=None: {"why": "guard_rows_flooded"})
        items = ocr.attribute_slot(s)
        self.assertEqual([(i["class"], i["cause"], i["t_ms"]) for i in items],
                         [(1, "guard_rows_flooded", 64000.0), (7, "no_drop_no_witness", None)])

    def test_a_death_refusal_the_rerun_gate_passes_is_a_candidate_with_its_root(self):
        # The stored gate ended the kit at 80 s; a teammate's revive the gate
        # does not read returned the player, and the rerun passes the drop.
        rows = [row(10),
                row(90, slot="Q", reason="after_player_death", kit_end_ms=80000.0,
                    root="teammate_revive", rejudged_reason=None, rejudged_kit_end_ms=None,
                    kit="Skye")]
        items = ocr.attribute_slot(slot(rows, riot=1, slot_key="Q", agent="Skye",
                                        others=[row(10)]) | {"ours": 0})
        self.assertEqual([(i["class"], i["cause"], i["evidence"]["root"]) for i in items],
                         [(3, "after_player_death", "teammate_revive")])

    def test_a_death_refusal_past_the_stored_kit_end_without_a_root_stays_out(self):
        rows = [row(10),
                row(90, slot="Q", reason="after_player_death", kit_end_ms=80000.0,
                    spend_witness=["countdown"], kit="Skye")]
        items = ocr.attribute_slot(slot(rows, riot=1, slot_key="Q", agent="Skye") | {"ours": 0})
        self.assertEqual([i["class"] for i in items], [7])

    def test_a_rejudged_drop_meets_the_rerun_gates_other_refusal(self):
        # The rerun refuses it as co-occurring: two other slots falling on
        # the same sample make it the tray, not a cast.
        r = row(90, slot="C", reason="after_player_death", kit_end_ms=80000.0,
                root="second_life_unread", rejudged_reason="cooccur_among_casts",
                rejudged_kit_end_ms=None, kit="Phoenix")
        others = [row(90, slot="Q", reason="after_player_death", kit="Phoenix"),
                  row(90.2, slot="E", reason="after_player_death", kit="Phoenix")]
        items = ocr.attribute_slot(slot([r], riot=1, slot_key="C", agent="Phoenix",
                                        others=others))
        self.assertEqual([i["class"] for i in items], [7])

    def test_a_drop_beside_another_slots_excess_cast_is_a_wrong_slot(self):
        rows = [row(10), row(50, reason="cooccur_among_casts", spend_witness=["icon"])]
        items = ocr.attribute_slot(slot(rows, riot=2, excess_casts=[("Q", 50500.0)]))
        self.assertEqual([(i["class"], i["cause"]) for i in items], [(4, "cast_in_Q")])


class Extra(unittest.TestCase):
    def test_an_x_cast_without_an_own_line_goes_first(self):
        rows = [row(100, slot="X"), row(300, slot="X", across_gap=True)]
        s = slot(rows, riot=1, slot_key="X", lines=[100500.0])
        items = ocr.attribute_slot(s)
        self.assertEqual([(i["class"], i["cause"], i["t_ms"]) for i in items],
                         [(6, "x_cast_without_own_line", 300000.0)])

    def test_a_countdown_witnessed_gold_cast_is_trusted(self):
        rows = [row(10, witness={"by": ["countdown", "persisted"]}),
                row(30, witness={"by": ["persisted"]})]
        items = ocr.attribute_slot(slot(rows, riot=1))
        self.assertEqual([(i["cause"], i["t_ms"]) for i in items],
                         [("gold_persisted_only", 30000.0)])

    def test_an_excess_pick_the_eye_calls_a_spend_is_unplaced(self):
        rows = [row(1000.0, slot="C"), row(1774.0, slot="C")]
        s = slot(rows, riot=1, slot_key="C") | {"session": "043bafca271a"}
        items = ocr.attribute_slot(s)
        self.assertEqual([(i["t_ms"], i["evidence"]["eye"], i["unplaced"]) for i in items],
                         [(1774000.0, "real_spend", True)])


class Summary(unittest.TestCase):
    def test_counts_per_class_ability_and_gate_reason(self):
        items = [{"kind": "missing", "class": 3, "cause": "forced", "agent": "Clove", "slot": "X"},
                 {"kind": "missing", "class": 3, "cause": "forced", "agent": "Clove", "slot": "X"},
                 {"kind": "missing", "class": 1, "cause": "stall", "agent": "Sova", "slot": "E"},
                 {"kind": "extra", "class": 6, "cause": "across_gap", "agent": "Sova", "slot": "C"}]
        got = ocr.summarise(items)
        self.assertEqual((got["missing"], got["extra"]), (3, 1))
        self.assertEqual(got["by_class"], {1: 1, 3: 2, 6: 1})
        self.assertEqual(got["gate_reasons"], {"forced": 2})
        self.assertEqual(got["by_class_ability"][3], {"Clove:X": 2})

    def test_class3_roots_and_the_rerun_reason(self):
        ev = {"root": "teammate_revive", "rejudged_reason": None}
        items = [{"kind": "missing", "class": 3, "cause": "after_player_death", "agent": "Skye",
                  "slot": "Q", "evidence": ev},
                 {"kind": "missing", "class": 3, "cause": "forced", "agent": "Iso", "slot": "X"},
                 {"kind": "extra", "class": 6, "cause": "no_flag", "agent": "Sova", "slot": "C",
                  "evidence": {"eye": "real_spend"}, "unplaced": True}]
        got = ocr.summarise(items)
        self.assertEqual(got["class3_roots"], {"teammate_revive": 1, "none": 1})
        self.assertEqual(got["class3_root_ability"]["teammate_revive"], {"Skye:Q": 1})
        self.assertEqual(got["class3_rejudged"], {"teammate_revive->None": 1})
        self.assertEqual((got["class6_eye"], got["extra_unplaced"]), ({"real_spend": 1}, 1))


if __name__ == "__main__":
    unittest.main()
