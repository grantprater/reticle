"""The minimap glyph asking tool asks each view (self, teammate, enemy) on its own: no view's answer settles another
[domain:abilities/views-separate-per-ability], the sheet's caster-view cell settles `self` alone, and the game data
orders and annotates questions without answering them."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import ask_minimap_glyphs as ask  # noqa: E402

SHEET = {("Omen", "X"): ("From the Shadows", "?"),
         ("Yoru", "X"): ("Dimensional Drift", "icon [domain:abilities/views-separate-per-ability]"),
         ("Sova", "C"): ("Owl Drone", "nothing (census 1)")}
INV = {"rows": [{"proposed": "Sova:C", "name": "TX_UI_Minimap_Hunter_C"}]}
GD = {("Omen", "X"): {"views": {"self": {"drawn": 2, "not_drawn": 0, "unknown": 0},
                                "teammate": {"drawn": 2, "not_drawn": 0, "unknown": 0},
                                "enemy": {"drawn": 0, "not_drawn": 2, "unknown": 0}}, "cues": ["TX_Omen_X"]}}


class ViewsSeparate(unittest.TestCase):
    def setUp(self):
        self.saved = ask.sheet_minimap
        ask.sheet_minimap = lambda: SHEET

    def tearDown(self):
        ask.sheet_minimap = self.saved

    def test_each_view_is_its_own_question(self):
        pruned = []
        keys = [q["key"] for q in ask.visibility_questions(INV, pruned, GD)]
        for v in ("self", "ally", "enemy"):
            self.assertIn(f"visibility:Omen:X:{v}", keys)
        self.assertNotIn("visibility:Omen:X:drawing", keys)
        self.assertFalse(any(k.endswith(":spectator") for k in keys))

    def test_decided_sheet_cell_settles_self_alone(self):
        pruned = []
        keys = [q["key"] for q in ask.visibility_questions(INV, pruned, GD)]
        self.assertEqual(pruned, [("Yoru:X", "Dimensional Drift")])
        self.assertNotIn("visibility:Yoru:X:self", keys)
        self.assertIn("visibility:Yoru:X:ally", keys)
        self.assertIn("visibility:Yoru:X:enemy", keys)

    def test_order_proposed_then_game_data_then_rest_self_first(self):
        qs = ask.visibility_questions(INV, [], GD)
        self.assertEqual([q["key"] for q in qs[:3]],
                         ["visibility:Sova:C:self", "visibility:Sova:C:ally", "visibility:Sova:C:enemy"])
        self.assertEqual(qs[3]["key"], "visibility:Omen:X:self")
        self.assertEqual(qs[-1]["key"], "visibility:Yoru:X:enemy")

    def test_game_data_annotates_never_answers(self):
        qs = {q["key"]: q for q in ask.visibility_questions(INV, [], GD)}
        q = qs["visibility:Omen:X:enemy"]
        self.assertIn("enemy: 0 drawn / 2 not", q["shown"]["game_data"])
        self.assertNotIn("answer", q)
        self.assertIn("Omen X From the Shadows, AN ENEMY'S, INSIDE VISION VIEW", ask.prompt(q))


class AnswersStandForTheirOwnKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "answers.jsonl"
        rows = [{"key": "visibility:Yoru:X:ally", "kind": "visibility", "answer": "icon", "unsure": False},
                {"key": "visibility:Omen:X:enemy", "kind": "visibility", "answer": None, "unsure": True}]
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.saved = ask.ANSWERS
        ask.ANSWERS = self.path

    def tearDown(self):
        ask.ANSWERS = self.saved
        self.tmp.cleanup()

    def test_teammate_answer_settles_no_other_view(self):
        done = ask.answered()
        self.assertIn("visibility:Yoru:X:ally", done)
        for k in ("visibility:Yoru:X:enemy", "visibility:Yoru:X:self", "visibility:Yoru:X:drawing"):
            self.assertNotIn(k, done)

    def test_reask_unsure(self):
        done = ask.answered()
        self.assertIn("visibility:Omen:X:enemy", ask.settled(done))
        self.assertNotIn("visibility:Omen:X:enemy", ask.settled(done, reask_unsure=True))
        self.assertIn("visibility:Yoru:X:ally", ask.settled(done, reask_unsure=True))


class SheetColumnsByHeader(unittest.TestCase):
    def test_minimap_cell_found_by_header_name(self):
        text = ("## Omen\n\n| Slot | Extra | Ability | Minimap | Notes |\n|---|---|---|---|---|\n"
                "| X | new column | From the Shadows | icon [domain:abilities/views-separate-per-ability] | n |\n\n"
                "## Yoru\n\n| Slot | Ability | Minimap |\n|---|---|---|\n| C | Fakeout | ? |\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sheet.md"
            p.write_text(text, encoding="utf-8")
            saved, ask.SHEET = ask.SHEET, p
            try:
                got = ask.sheet_minimap()
            finally:
                ask.SHEET = saved
        self.assertEqual(got, {("Omen", "X"): ("From the Shadows", "icon [domain:abilities/views-separate-per-ability]"),
                               ("Yoru", "C"): ("Fakeout", "?")})


class _Fact:
    def __init__(self, claim, known="player", since="2026-10-04"):
        self.claim, self.known, self.since = claim, known, since


FACTS = {"abilities/killjoy-lockdown-global-minimap": _Fact("drawn on every player's minimap: device and ring"),
         "abilities/phoenix-blaze-no-minimap-icon": _Fact("Blaze draws no icon on the minimap; the wall")}
TABLE = {"abilities/killjoy-lockdown-global-minimap": [("Killjoy", "X", "Lockdown", ask.ALL_VIEWS,
                                                        {"icon": True, "shape": True})],
         "abilities/phoenix-blaze-no-minimap-icon": [("Phoenix", "C", "Blaze", None, {"icon": False, "shape": True})]}
SHEET2 = {("Killjoy", "X"): ("Lockdown", "compact icon (census 1)"),
          ("Phoenix", "C"): ("Blaze", "orange wall [domain:abilities/phoenix-blaze], no icon (disputed) "
                                      "[domain:abilities/phoenix-blaze-no-minimap-icon]")}


def _row(key, answer, line, unsure=False, shown=None):
    return {"key": key, "kind": "visibility", "answer": answer, "unsure": unsure, "by": "player",
            "ts": "2026-10-04T16:06:50", "_line": line, "shown": shown or {}}


class StatementsSettleAndReopen(unittest.TestCase):
    def setUp(self):
        self.saved = ask.sheet_minimap
        ask.sheet_minimap = lambda: SHEET2
        self.stmts = ask.fact_statements(FACTS, TABLE)

    def tearDown(self):
        ask.sheet_minimap = self.saved

    def qs(self, done, extra=None):
        st = dict(self.stmts)
        for k, v in (extra or {}).items():
            st[k] = st.get(k, []) + v
        qs = ask.visibility_questions({"rows": []}, [], {}, st)
        return qs, ask.annotate(qs, done)

    def test_player_fact_naming_the_view_settles_it(self):
        _, status = self.qs({})
        for v in ("self", "ally", "enemy"):
            self.assertEqual(status[f"visibility:Killjoy:X:{v}"],
                             (False, "settled by [domain:abilities/killjoy-lockdown-global-minimap]: icon_and_shape"))

    def test_fact_not_naming_a_view_settles_nothing(self):
        _, status = self.qs({})
        for v in ("ally", "enemy"):
            self.assertTrue(status[f"visibility:Phoenix:C:{v}"][0])

    def test_disputed_sheet_cell_is_open(self):
        self.assertEqual(ask.undecided(SHEET2[("Phoenix", "C")][1]), "a disputed statement")
        qs, status = self.qs({})
        self.assertIn("visibility:Phoenix:C:self", [q["key"] for q in qs])
        self.assertTrue(status["visibility:Phoenix:C:self"][0])

    def test_contradicted_answer_reopens_with_both_statements(self):
        done = {"visibility:Phoenix:C:ally": _row("visibility:Phoenix:C:ally", "icon_and_shape", 307),
                "visibility:Phoenix:C:enemy": _row("visibility:Phoenix:C:enemy", "icon_and_shape", 308)}
        belief = {("Phoenix", "C"): [{"source": "answers.jsonl#L366 question:blaze-icon:enemy", "by": "player",
                                      "since": "2026-10-04T19:04", "views": ["enemy"], "says": "Possibly",
                                      "states": {"icon": "possible"}}]}
        qs, status = self.qs(done, belief)
        is_open, why = status["visibility:Phoenix:C:enemy"]
        self.assertTrue(is_open)
        self.assertIn("'icon_and_shape' (answers.jsonl#L308", why)
        self.assertIn("[domain:abilities/phoenix-blaze-no-minimap-icon]", why)
        self.assertNotIn("L366", why)                       # a hedge contradicts nothing ...
        q = next(q for q in qs if q["key"] == "visibility:Phoenix:C:enemy")
        self.assertIn("L366", ask.prompt(q))                # ... but is shown
        self.assertIn("REOPENED", ask.prompt(q))
        self.assertEqual({q["key"] for q in qs[:2]}, {"visibility:Phoenix:C:ally", "visibility:Phoenix:C:enemy"})

    def test_answer_given_with_the_statement_shown_stands(self):
        qs, _ = self.qs({})
        shown = next(q for q in qs if q["key"] == "visibility:Phoenix:C:ally")["shown"]
        done = {"visibility:Phoenix:C:ally": _row("visibility:Phoenix:C:ally", "icon_and_shape", 400, shown=shown)}
        _, status = self.qs(done)
        self.assertEqual(status["visibility:Phoenix:C:ally"],
                         (False, "answered with the contradicting statements shown"))

    def test_agreeing_or_unsure_answer_stays_done(self):
        done = {"visibility:Phoenix:C:ally": _row("visibility:Phoenix:C:ally", "shape", 10),
                "visibility:Phoenix:C:enemy": _row("visibility:Phoenix:C:enemy", None, 11, unsure=True)}
        _, status = self.qs(done)
        self.assertFalse(status["visibility:Phoenix:C:ally"][0])
        self.assertFalse(status["visibility:Phoenix:C:enemy"][0])

    def test_contradicting_answer_blocks_a_fact_settlement(self):
        done = {"visibility:Killjoy:X:enemy": _row("visibility:Killjoy:X:enemy", "nothing", 5)}
        _, status = self.qs(done)
        self.assertTrue(status["visibility:Killjoy:X:enemy"][0])

    def test_repo_table_cites_player_facts_and_sheet_abilities(self):
        ask.sheet_minimap = self.saved
        ask.check_facts()            # raises SystemExit on a missing, non-player or misplaced fact row

    def test_row_statement_carries_its_line(self):
        done = {"question:blaze-icon:enemy": {"key": "question:blaze-icon:enemy", "answer": "possible", "by": "player",
                                              "ts": "t", "_line": 366, "answer_words": "2. Possibly"}}
        st = ask.row_statements(done)[("Phoenix", "C")][0]
        self.assertEqual((st["source"], st["views"], st["states"]),
                         ("answers.jsonl#L366 question:blaze-icon:enemy", ["enemy"], {"icon": "possible"}))

    def test_clash_and_category(self):
        self.assertEqual(ask.clash({"drawn": False}, {"shape": True}), ["shape", "drawn"])
        self.assertEqual(ask.clash({"icon": "possible"}, {"icon": False}), [])
        self.assertEqual(ask.category({"drawn": False}), "nothing")
        self.assertIsNone(ask.category({"shape": True}))


class ClaimWordsCheckCodedStates(unittest.TestCase):
    """`claim_mismatches` checks a row's coded states and views against its fact's claim text."""
    CLAIM = {"abilities/killjoy-lockdown-global-minimap": _Fact(
        "Killjoy's Lockdown is drawn on every player's minimap: the device's position and a large ring.")}
    WORDS = {"views": "drawn on every player's minimap", "icon": "the device's position", "shape": "a large ring"}

    def check(self, states, words, views=ask.ALL_VIEWS):
        return ask.claim_mismatches(self.CLAIM, {"abilities/killjoy-lockdown-global-minimap": [
            ("Killjoy", "X", "Lockdown", views, states, words)]})

    def test_quoted_row_passes(self):
        self.assertEqual(self.check({"icon": True, "shape": True}, self.WORDS), [])

    def test_flipped_state_fails(self):
        self.assertIn("icon=False quote lacks a negation",
                      self.check({"icon": False, "shape": True}, self.WORDS)[0])

    def test_unquoted_state_and_foreign_quote_fail(self):
        bad = self.check({"icon": True, "shape": True, "drawn": True}, dict(self.WORDS, shape="a small disc"))
        self.assertEqual(len(bad), 2)
        self.assertIn("shape quote not in the claim", bad[0])
        self.assertIn("drawn=True quotes no claim words", bad[1])

    def test_view_needs_its_word(self):
        self.assertIn("view self quoted without", self.check({"icon": True}, self.WORDS, ("self",))[0])

    def test_repo_rows_carry_quotes_the_claims_hold(self):
        from reticle import domain
        self.assertEqual(ask.claim_mismatches(domain.load()), [])

    def test_sova_ring_answer_is_an_enemy_view_statement(self):
        done = {"visibility:Sova:E:minimap-ring": {"key": "visibility:Sova:E:minimap-ring", "by": "player",
                                                   "ts": "t", "_line": 370, "player_words": "Yes",
                                                   "shown": {"question": "Enemy team too?"}}}
        st = ask.row_statements(done)[("Sova", "E")][0]
        self.assertEqual((st["views"], st["states"], st["says"]), (["enemy"], {"shape": True}, "Enemy team too? Yes"))


class ListPrintsOpenFirst(unittest.TestCase):
    def test_list_output_puts_open_keys_before_done(self):
        qs = [{"key": k, "kind": "rotation", "shown": {}} for k in ("a", "b", "c")]
        status = ask.annotate(qs, {"a": {"answer": "upright"}, "c": {"answer": "rotates"}})
        self.assertEqual(status, {"a": (False, "answered"), "b": (True, "no answer"), "c": (False, "answered")})
        self.assertEqual(ask.key_lines(qs, status), ["open b", "done a", "done c"])


if __name__ == "__main__":
    unittest.main()
