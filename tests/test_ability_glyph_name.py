"""Stage 3 of the glyph channel: `adjudication.ability.disc_tracks` and
`adjudication.ability_glyph` over synthetic stored rows."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle.adjudication import ability_glyph as ag
from reticle.adjudication.ability import JUMP_REACH_BASE, disc_tracks
from reticle.adjudication.identity import adjudicate_agent_identity, claims_from_lineup

SID = "s"
KEYS = ["Astra:C", "Astra:X", "Omen:E", "Omen:Q", "Sova:C", "Sova:Q", "Viper:Q"]
STAR = "answer:labels/x.jsonl#L367:minimap/TX_Astra_Minimap_PassiveBlack.png"


def tables(tie=0.1, drawing=None):
    states = {("astra", "X", "TX_Astra_Minimap_PassiveBlack"): [
        {"state": "SetSelected", "phase": "targeting",
         "views": {"self": True, "teammate": False, "enemy": False, "spectator": False}}]}
    sources = {k: ["icon"] for k in KEYS}
    sources["Astra:X"] = ["icon", STAR]
    return ag.VerdictTables(KEYS, {k: 0.5 for k in KEYS}, {k: 0.6 for k in KEYS},
                            {"full": 0.7, "audit": 0.8}, tie, sources, states,
                            {"glyph": {"null": {"version": "null-test"}},
                             "states": {"version": "states-test"}}, drawing=drawing,
                            names={"Sova:C": "Owl Drone"})


NOT_DRAWN = {"Sova:Q": {"answer": "nothing", "other": None, "answer_key": "visibility:Sova:Q:ally",
                        "row": "labels/q/answers.jsonl#L9", "domain_subject": "sova:shock bolt",
                        "domain_facts": []},
             "Astra:X": {"answer": "shape", "other": None, "answer_key": "visibility:Astra:X:ally",
                         "row": "labels/q/answers.jsonl#L4", "domain_subject": None, "domain_facts": []}}
STAR_STATE = {("Astra:X", "TX_Astra_Minimap_PassiveBlack"): {"state": "placed-inactive star",
                                                              "row": "labels/q/answers.jsonl#L7"}}


def lineup(ally=("Astra", "Omen", "Sova", "Reyna", "Sage"),
           enemy=("Jett", "Raze", "Fade", "Breach", "Killjoy")):
    sides = {"ally": [{"slot": i, "agent": a, "best_guess": a} for i, a in enumerate(ally)],
             "enemy": [{"slot": i, "agent": a, "best_guess": a} for i, a in enumerate(enemy)]}
    claims = claims_from_lineup(sides, {"tray": {"votes": {ally[2]: 9}}}, observation_id=SID)
    return {"sides": sides, "identity_claims": claims, "agent_identity": adjudicate_agent_identity(claims)}


def cands(ally=("Astra", "Omen", "Sova", "Reyna", "Sage"), rivals=(), blind=0):
    agents = {a: "named" for a in ally}
    agents.update({a: "rival" for a in rivals})
    return {"ally": {"agents": agents, "blind": blind},
            "enemy": {"agents": {a: "named" for a in ("Jett", "Raze", "Fade", "Breach", "Killjoy")},
                      "blind": 0}}


def disc_id(t, i):
    return f"ability_icon:{SID}:{round(float(t), 3)}:{i}"


def rows_of(spec, keys=KEYS):
    """spec: [(t, i, pred_t or None, reason, {key: (score, source)}, (cx, cy))]."""
    n = len(spec)
    S = np.full((n, len(keys)), np.nan)
    SI = np.full((n, len(keys)), -1, np.int64)
    for r, (_, _, _, _, sc, _) in enumerate(spec):
        for k, (v, s) in sc.items():
            S[r, keys.index(k)] = v
            SI[r, keys.index(k)] = s
    return {"n": n, "t_ms": np.array([x[0] for x in spec], float),
            "frame_idx": np.arange(n), "disc": np.array([disc_id(x[0], x[1]) for x in spec], object),
            "pred": np.array(["" if x[2] is None else disc_id(x[2], x[1]) for x in spec], object),
            "i": np.array([x[1] for x in spec], np.int64),
            "cx": np.array([x[5][0] for x in spec], float), "cy": np.array([x[5][1] for x in spec], float),
            "scale": np.ones(n), "map_shown": np.full(n, 0.3),
            "portrait": np.array([""] * n, object),
            "reason": np.array([x[3] for x in spec], object), "S": S, "SI": SI}


def glyph(spec, frames=None, audit=(), surprise=(), candidates=None):
    ts = sorted({x[0] for x in spec}) if frames is None else [f[0] for f in frames]
    fr = [""] * len(ts) if frames is None else [f[1] for f in frames]
    return {"head": {"candidates": candidates or cands(), "candidates_from": "lineup test@x",
                     "ability_glyph_version": "ability-glyph-0.5.0", "glyph_bank": "bank"},
            "frames": {"t_ms": np.array(ts, float), "reason": np.array(fr, object)},
            "context": rows_of(spec), "audit": rows_of(list(audit)), "surprise": rows_of(list(surprise))}


def placed(t0, n, scores, i=0, xy=(50.0, 50.0), reason=""):
    """A placed disc seen at n 2 Hz samples, each scoring `scores`."""
    return [(t0 + 500 * k, i, None if k == 0 else t0 + 500 * (k - 1), reason, scores, xy)
            for k in range(n)]


def verdicts(res):
    return {r["track"]: r for r in res["rows"][1:]}


class DiscTracks(unittest.TestCase):
    def test_tracks_join_verify_links_and_store_motion(self):
        spec = placed(0, 3, {}, xy=(10.0, 10.0))
        spec[1] = (500, 0, 0, "", {}, (10.0, 13.0))
        spec[2] = (1000, 0, 500, "", {}, (10.0, 13.0 + JUMP_REACH_BASE + 1))
        spec += [(1000, 1, None, "", {}, (80.0, 80.0))]
        frames = [(0, ""), (500, ""), (1000, ""), (1500, "not_live")]
        g = glyph(spec, frames)
        out = disc_tracks(SID, g["context"], g["frames"], None)
        tr = out["tracks"]
        self.assertEqual(len(tr), 2)
        a, b = tr
        self.assertEqual(a["track"], f"{SID}:adisc:0.0:0")
        self.assertEqual(a["fixes"], 3)
        self.assertAlmostEqual(a["path_px"], 3 + JUMP_REACH_BASE + 1)
        self.assertEqual(a["lifetime_ms"], 1000.0)
        self.assertAlmostEqual(a["first_second"]["speed_base_per_s"], 3 + JUMP_REACH_BASE + 1)
        self.assertEqual(a["surprises"], ["jump_past_reach"])
        self.assertEqual(a["end"], "frame_unread:not_live")
        self.assertEqual(a["onset"], "stream_start")
        self.assertEqual(b["fixes"], 1)
        self.assertEqual(b["onset"], "observed")
        self.assertEqual(list(out["track"]), [0, 0, 0, 1])

    def test_end_reason_reads_the_stored_verify(self):
        spec = placed(0, 2, {}) + [(500, 1, None, "", {}, (90.0, 90.0))]
        frames = [(0, ""), (500, ""), (1000, "")]
        g = glyph(spec, frames)
        verify = {"t_ms": np.array([1000.0, 1000.0]), "of": np.array([0, 1]),
                  "lost": np.array([True, False])}
        tr = disc_tracks(SID, g["context"], g["frames"], verify)["tracks"]
        self.assertEqual([t["end"] for t in tr], ["verify_lost", "verify_held_unbound"])

    def test_a_loss_under_a_stored_icon_or_ping_is_no_loss(self):
        # Three discs lost at 1000 ms: one under a teammate's icon, one under
        # a ping, one in the clear.
        spec = (placed(0, 2, {}, i=0, xy=(50.0, 50.0)) + placed(0, 2, {}, i=1, xy=(150.0, 50.0))
                + placed(0, 2, {}, i=2, xy=(250.0, 50.0)))
        frames = [(0, ""), (500, ""), (1000, "")]
        g = glyph(spec, frames)
        verify = {"t_ms": np.full(3, 1000.0), "of": np.array([0, 1, 2]), "lost": np.ones(3, bool)}
        covers = {"t_ms": np.array([700.0, 700.0]), "x": np.array([55.0, 250.0 + 40.0]),
                  "y": np.array([52.0, 50.0]), "kind": np.array(["ally", "enemy"]),
                  "p_t0": np.array([600.0]), "p_t1": np.array([np.inf]),
                  "p_x": np.array([160.0]), "p_y": np.array([50.0])}
        tr = disc_tracks(SID, g["context"], g["frames"], verify, covers)["tracks"]
        self.assertEqual([t["end"] for t in tr], ["covered_by_ally", "covered_by_ping", "verify_lost"])
        # no covers given: every loss stands
        tr = disc_tracks(SID, g["context"], g["frames"], verify)["tracks"]
        self.assertEqual([t["end"] for t in tr], ["verify_lost"] * 3)

    def test_a_gated_sample_never_splits_a_track(self):
        spec = placed(0, 4, {})
        spec[2] = (1000, 0, 500, "map_shown", {}, (50.0, 50.0))
        g = glyph(spec)
        tr = disc_tracks(SID, g["context"], g["frames"], None)["tracks"]
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0]["fixes"], 4)
        self.assertEqual(tr[0]["scored_fixes"], 3)


class Verdict(unittest.TestCase):
    def run_(self, g, player="Sova", kit=None, lu=None):
        return ag.adjudicate(SID, g, None, tables(), lu or lineup(), kit, player)

    def test_a_clear_key_names_the_track_and_claims_its_caster(self):
        res = self.run_(glyph(placed(0, 3, {"Sova:C": (0.8, 0), "Sova:Q": (0.4, 0), "Omen:E": (0.3, 0)})))
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["ability"]["key"], "Sova:C")
        self.assertIsNone(v["reason"])
        self.assertEqual(v["agent"], "Sova")
        self.assertEqual(v["identity_status"], "resolved")
        claim = res["claims"][0]
        self.assertEqual(claim["channel"], ag.CHANNEL)
        # The lineup chose the candidates: the claim depends on the ally slots.
        self.assertEqual(claim["depends_on"], [f"{SID}:ally:slot:{i}" for i in range(5)])
        self.assertEqual(len(res["events"]), 1)

    def test_below_null_and_a_tie_inside_one_kit(self):
        res = self.run_(glyph(placed(0, 2, {"Sova:C": (0.45, 0), "Omen:E": (0.3, 0)})
                              + placed(5000, 2, {"Sova:C": (0.8, 0), "Sova:Q": (0.75, 0), "Omen:E": (0.3, 0)},
                                       i=1)))
        v = verdicts(res)
        low, tie = v[f"{SID}:adisc:0.0:0"], v[f"{SID}:adisc:5000.0:1"]
        self.assertEqual(low["reason"], "below_null")
        self.assertIsNone(low["agent"])
        # The slot ties inside Sova's kit; the kit is clear, so the claim names Sova.
        self.assertEqual(tie["reason"], "pairwise_tie")
        self.assertIsNone(tie["ability"])
        self.assertTrue(tie["kit_clear"])
        self.assertEqual(tie["agent"], "Sova")

    def test_gated_tracks_refuse_with_their_reason(self):
        res = self.run_(glyph(placed(0, 2, {}, reason="ally_portrait")
                              + placed(0, 2, {}, i=1, xy=(5.0, 5.0), reason="map_shown")))
        v = verdicts(res)
        self.assertEqual(v[f"{SID}:adisc:0.0:0"]["reason"], "occluded")
        self.assertEqual(v[f"{SID}:adisc:0.0:1"]["reason"], "no_clean_frame")
        self.assertEqual(res["claims"], [])

    def test_astra_star_is_pending_and_view_excludes_it_when_spectating(self):
        star = {"Astra:X": (0.8, 1), "Astra:C": (0.4, 0), "Sova:C": (0.3, 0)}
        res = self.run_(glyph(placed(0, 3, star)), kit=[(0.0, 5000.0, "Sova")])
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["reason"], "pending")
        self.assertEqual(v["pending"], "Astra:star")
        self.assertEqual(v["state"]["texture"], "TX_Astra_Minimap_PassiveBlack")
        self.assertEqual(v["agent"], "Astra")
        # The tray shows a teammate's kit: the spectator view; the states
        # table marks the star texture false there, so the key leaves.
        res = self.run_(glyph(placed(0, 3, star)), kit=[(0.0, 5000.0, "Omen")])
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertNotEqual(v["best"], "Astra:X")
        self.assertEqual(v["samples"]["view_spectator"], 3)
        res = self.run_(glyph(placed(0, 3, {"Astra:X": (0.8, 1)})), kit=[(0.0, 5000.0, "Omen")])
        self.assertEqual(verdicts(res)[f"{SID}:adisc:0.0:0"]["reason"], "view_excluded")

    def test_an_unknown_view_stays_in_as_a_surprise(self):
        res = self.run_(glyph(placed(0, 2, {"Sova:C": (0.8, 0), "Omen:E": (0.3, 0)})), kit=None)
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["ability"]["key"], "Sova:C")
        self.assertIn("view_unknown", v["surprises"])

    def test_the_omen_rule_refuses_without_a_recorded_scale(self):
        res = self.run_(glyph(placed(0, 2, {"Omen:Q": (0.8, 0), "Omen:E": (0.75, 0), "Sova:C": (0.2, 0)})))
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["reason"], "pairwise_tie")
        self.assertFalse(v["omen_rule"]["applied"])
        self.assertTrue(v["omen_rule"]["reason"].startswith("scale_unrecorded"))
        self.assertEqual(v["omen_rule"]["pooled"], {"Omen:Q": 0.8, "Omen:E": 0.75})
        self.assertEqual(v["agent"], "Omen")

    def test_outside_candidate_set_from_the_surprise_path(self):
        spec = placed(0, 2, {"Sova:C": (0.4, 0), "Omen:E": (0.3, 0)})
        full = {k: (0.2, 0) for k in KEYS}
        full["Viper:Q"] = (0.9, 0)
        res = self.run_(glyph(spec, surprise=[(t, i, p, "", full, xy) for t, i, p, _, _, xy in spec]))
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["reason"], "outside_candidate_set")
        self.assertEqual(v["outside"]["best"], "Viper:Q")
        self.assertEqual(v["outside"]["path"], "surprise")
        self.assertEqual(res["claims"][0]["reason"], "outside_candidate_set")

    def test_a_rival_kit_and_a_blind_slot_never_take_the_name(self):
        g = glyph(placed(0, 2, {"Viper:Q": (0.9, 0), "Sova:C": (0.2, 0)}),
                  candidates=cands(ally=("Astra", "Omen", "Sova", "Reyna"), rivals=("Viper",)))
        v = verdicts(self.run_(g))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["ability"]["key"], "Viper:Q")
        self.assertIsNone(v["agent"])
        self.assertEqual(v["claim_reason"], "rival_kit")
        g = glyph(placed(0, 2, {"Sova:C": (0.9, 0), "Omen:E": (0.2, 0)}), candidates=cands(blind=1))
        v = verdicts(self.run_(g))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["claim_reason"], "blind_slot")
        self.assertIsNone(v["agent"])

    def test_audit_claims_stay_out_of_the_aggregator(self):
        spec = placed(0, 2, {"Sova:C": (0.9, 0), "Omen:E": (0.2, 0)})
        full = {k: (0.2, 0) for k in KEYS}
        full["Sova:C"] = (0.95, 0)
        res = self.run_(glyph(spec, audit=[(t, i, p, "", full, xy) for t, i, p, _, _, xy in spec]))
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertTrue(v["audit"]["named"])
        self.assertEqual(v["audit_claim"]["channel"], ag.AUDIT_CHANNEL)
        self.assertEqual(res["audit_claims"], [v["audit_claim"]])
        self.assertTrue(all(c["channel"] == ag.CHANNEL for c in res["claims"]))
        cov = res["rows"][0]
        self.assertEqual(cov["audit"]["agree_with_context"], 1)
        self.assertFalse(cov["audit"]["in_aggregator"])

    def test_a_key_the_player_says_draws_nothing_never_names(self):
        g = glyph(placed(0, 2, {"Sova:Q": (0.9, 0), "Sova:C": (0.3, 0), "Omen:E": (0.2, 0)}))
        res = ag.adjudicate(SID, g, None, tables(drawing={"not_drawn": NOT_DRAWN}), lineup(), None, "Sova")
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["reason"], "not_drawn_per_answer")
        self.assertIsNone(v["ability"])
        self.assertFalse(v["kit_clear"])
        self.assertIsNone(v["agent"])
        self.assertEqual(v["claim_reason"], "not_drawn_per_answer")
        self.assertIn("fact_contradicts:Sova:Q", v["surprises"])
        self.assertEqual(v["not_drawn"]["row"], "labels/q/answers.jsonl#L9")
        self.assertIn("labels/q/answers.jsonl#L9", v["rests_on"])
        self.assertEqual(res["rows"][0]["not_drawn"]["refused"], 1)
        # The runner-up is not promoted, and a drawn key still names.
        g = glyph(placed(0, 2, {"Sova:C": (0.9, 0), "Sova:Q": (0.3, 0), "Omen:E": (0.2, 0)}))
        v = verdicts(ag.adjudicate(SID, g, None, tables(drawing={"not_drawn": NOT_DRAWN}), lineup(), None,
                                   "Sova"))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["ability"], {"agent": "Sova", "slot": "C", "key": "Sova:C", "name": "Owl Drone"})
        self.assertIsNone(v["not_drawn"])

    def test_a_texture_state_answer_outranks_its_keys_visibility_answer(self):
        star = {"Astra:X": (0.8, 1), "Astra:C": (0.4, 0), "Sova:C": (0.3, 0)}
        t = tables(drawing={"not_drawn": NOT_DRAWN, "drawn_textures": STAR_STATE})
        v = verdicts(ag.adjudicate(SID, glyph(placed(0, 3, star)), None, t, lineup(), None,
                                   "Sova"))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["pending"], "Astra:star")
        self.assertEqual(v["agent"], "Astra")
        # The same key on its display icon has no state answer: not drawn.
        icon = {"Astra:X": (0.8, 0), "Astra:C": (0.4, 0), "Sova:C": (0.3, 0)}
        v = verdicts(ag.adjudicate(SID, glyph(placed(0, 3, icon)), None, t, lineup(), None,
                                   "Sova"))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["reason"], "not_drawn_per_answer")
        self.assertIsNone(v["agent"])

    def test_the_audit_path_refuses_a_key_not_drawn(self):
        spec = placed(0, 2, {"Sova:C": (0.9, 0), "Omen:E": (0.2, 0)})
        full = {k: (0.2, 0) for k in KEYS}
        full["Sova:Q"] = (0.95, 0)
        g = glyph(spec, audit=[(t, i, p, "", full, xy) for t, i, p, _, _, xy in spec])
        res = ag.adjudicate(SID, g, None, tables(drawing={"not_drawn": NOT_DRAWN}), lineup(), None, "Sova")
        v = verdicts(res)[f"{SID}:adisc:0.0:0"]
        self.assertFalse(v["audit"]["named"])
        self.assertEqual(v["audit"]["reason"], "not_drawn_per_answer")
        self.assertIsNone(v["audit_claim"])

    def test_a_missing_cut_refuses_no_cut_for_key(self):
        t = tables()
        t.cut[t.index["Sova:C"]] = np.nan
        g = glyph(placed(0, 2, {"Sova:C": (0.9, 0), "Omen:E": (0.2, 0)}))
        v = verdicts(ag.adjudicate(SID, g, None, t, lineup(), None, "Sova"))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["reason"], "no_cut_for_key")

    def test_a_blind_slot_on_another_side_leaves_the_claim(self):
        c = cands()
        c["enemy"]["blind"] = 1
        g = glyph(placed(0, 2, {"Sova:C": (0.9, 0), "Omen:E": (0.2, 0)}), candidates=c)
        v = verdicts(self.run_(g))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["agent"], "Sova")
        # No side admits Viper: a blind slot anywhere may hold it.
        g = glyph(placed(0, 2, {"Viper:Q": (0.9, 0), "Sova:C": (0.2, 0)}), candidates=c)
        v = verdicts(self.run_(g))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(v["claim_reason"], "blind_slot")

    def test_the_cut_comes_from_the_tables(self):
        g = glyph(placed(0, 2, {"Sova:C": (0.6, 0), "Omen:E": (0.2, 0)}))
        t = tables()
        t.cut[t.index["Sova:C"]] = 0.65
        res = ag.adjudicate(SID, g, None, t, lineup(), None, "Sova")
        self.assertEqual(verdicts(res)[f"{SID}:adisc:0.0:0"]["reason"], "below_null")


class Loader(unittest.TestCase):
    def test_load_glyph_rows_reads_scores_sources_and_links(self):
        rows = [{"kind": "coverage", "ability_glyph_version": "ability-glyph-0.5.0",
                 "window": {"ms": 3000.0}, "candidates": cands()},
                {"kind": "frame", "t_ms": 0.0, "frame_idx": 0, "reason": None, "discs": 1},
                {"kind": "disc", "set": "context", "t_ms": 0.0, "frame_idx": 0, "disc": disc_id(0, 0), "i": 0,
                 "cx": 5, "cy": 6, "r": 4.0, "scale": 0.63, "map_shown": 0.2, "portrait": None,
                 "reason": None, "rests_on": ["lineup x"],
                 "scores": {"Sova:C": [0.7, 1, 12.0, 0, 1, -1], "Omen:E": [0.3, 0, 10.0, 15, 0, 0]}},
                {"kind": "frame", "t_ms": 500.0, "frame_idx": 1, "reason": None, "discs": 1},
                {"kind": "disc", "set": "context", "t_ms": 500.0, "frame_idx": 1, "disc": disc_id(500, 0),
                 "i": 0, "cx": 5, "cy": 6, "r": 4.0, "scale": 0.63, "map_shown": None,
                 "portrait": "ally_portrait", "reason": "ally_portrait",
                 "rests_on": [disc_id(0, 0)], "scores": None}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.jsonl"
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            got = ag.load_glyph_rows(p, KEYS)
        c = got["context"]
        self.assertEqual(c["n"], 2)
        self.assertEqual(list(c["pred"]), ["", disc_id(0, 0)])
        self.assertEqual(list(c["reason"]), ["", "ally_portrait"])
        self.assertAlmostEqual(c["S"][0, KEYS.index("Sova:C")], 0.7)
        self.assertEqual(c["SI"][0, KEYS.index("Sova:C")], 1)
        self.assertTrue(np.isnan(c["S"][1]).all())
        self.assertEqual(got["audit"]["n"], 0)
        self.assertEqual(list(got["frames"]["t_ms"]), [0.0, 500.0])

    def test_load_drawing_answers_reads_the_last_sure_answer(self):
        rows = [{"key": "visibility:Sova:Q:ally", "kind": "visibility", "answer": "icon", "unsure": False},
                {"key": "visibility:Sova:Q:ally", "kind": "visibility", "answer": "nothing", "unsure": False},
                {"key": "visibility:Sova:C:ally", "kind": "visibility", "answer": "shape", "unsure": True},
                {"key": "visibility:Omen:E:ally", "kind": "visibility", "answer": "shape", "unsure": False},
                {"key": "visibility:Omen:E:drawing", "kind": "visibility", "answer": "icon", "unsure": False},
                {"key": "visibility:Astra:X:ally", "kind": "visibility", "answer": "shape", "unsure": False},
                {"key": "texture:TX_Astra_Minimap_PassiveBlack", "kind": "texture", "answer": "Astra:X",
                 "unsure": False, "state": "placed-inactive star"}]
        cat = {"agents": {"Sova": {"abilities": [{"key": "Q", "name": "Shock Bolt"}]}}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ag.DRAWING_ANSWERS
            p.parent.mkdir(parents=True)
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            (Path(d) / "reference").mkdir()
            (Path(d) / "reference" / "abilities.json").write_text(json.dumps(cat), encoding="utf-8")
            got = ag.load_drawing_answers(d, KEYS)
        self.assertEqual(sorted(got["not_drawn"]), ["Astra:X", "Sova:Q"])
        self.assertEqual(got["not_drawn"]["Sova:Q"]["row"], f"{ag.DRAWING_ANSWERS}#L2")
        self.assertEqual(got["not_drawn"]["Sova:Q"]["domain_subject"], "sova:shock bolt")
        self.assertEqual(list(got["drawn_textures"]), [("Astra:X", "TX_Astra_Minimap_PassiveBlack")])
        self.assertEqual(got["provenance"]["rows"], 7)

    def test_a_stale_bank_refuses(self):
        self.assertIsNotNone(ag.stale_reason({"ability_glyph_version": "ability-glyph-0.5.0",
                                              "glyph_bank": "old"}))


if __name__ == "__main__":
    unittest.main()


def _vis(key, answer, unsure=False):
    return {"key": key, "kind": "visibility", "answer": answer, "unsure": unsure}


class OwnCasterDrawing(unittest.TestCase):
    """A key whose agent is the recording player's own reads the player's
    `self` drawing answer first; any other caster's key reads `drawing`, else
    `ally`, and never the `self` answer."""

    ROWS = [_vis("visibility:Sova:Q:self", "nothing"), _vis("visibility:Sova:Q:ally", "icon"),
            _vis("visibility:Viper:Q:self", "shape"),
            _vis("visibility:Omen:E:ally", "nothing"), _vis("visibility:Omen:E:self", "icon")]

    def test_player_drawing_reads_self_first_only_for_the_own_caster(self):
        other, own = ag.player_drawing(self.ROWS), ag.player_drawing(self.ROWS, own=True)
        self.assertEqual(other[("Sova", "Q")][2], "visibility:Sova:Q:ally")
        self.assertEqual(own[("Sova", "Q")][2], "visibility:Sova:Q:self")
        self.assertNotIn(("Viper", "Q"), other)
        self.assertEqual(own[("Viper", "Q")][0], "shape")
        self.assertEqual(own[("Omen", "E")][0], "icon")

    def test_load_drawing_answers_keeps_both_view_orders(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ag.DRAWING_ANSWERS
            p.parent.mkdir(parents=True)
            p.write_text("".join(json.dumps(r) + "\n" for r in self.ROWS), encoding="utf-8")
            got = ag.load_drawing_answers(d, KEYS, names={})
            self.assertEqual(got["provenance"]["stamp"], ag.drawing_answers_stamp(d))
        self.assertEqual(sorted(got["not_drawn"]), ["Omen:E"])
        self.assertEqual(sorted(got["not_drawn_own"]), ["Sova:Q", "Viper:Q"])
        self.assertEqual(got["not_drawn_own"]["Sova:Q"]["row"], f"{ag.DRAWING_ANSWERS}#L1")

    def test_the_self_answer_refuses_only_the_players_own_key(self):
        nd = {"Sova:Q": dict(NOT_DRAWN["Sova:Q"], answer_key="visibility:Sova:Q:self")}
        t = tables(drawing={"not_drawn": {}, "not_drawn_own": nd})
        g = glyph(placed(0, 2, {"Sova:Q": (0.9, 0), "Sova:C": (0.3, 0), "Omen:E": (0.2, 0)}))
        mine = verdicts(ag.adjudicate(SID, g, None, t, lineup(), None, "Sova"))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(mine["reason"], "not_drawn_per_answer")
        self.assertEqual(mine["not_drawn"]["answer_key"], "visibility:Sova:Q:self")
        # A teammate plays Sova while the player records Omen: the self answer
        # does not describe that caster's drawing.
        theirs = verdicts(ag.adjudicate(SID, g, None, t, lineup(), None, "Omen"))[f"{SID}:adisc:0.0:0"]
        self.assertEqual(theirs["ability"]["key"], "Sova:Q")
        self.assertIsNone(theirs["not_drawn"])

    def test_the_stamp_moves_with_a_read_answer_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ag.DRAWING_ANSWERS
            p.parent.mkdir(parents=True)
            self.assertEqual(ag.drawing_answers_stamp(d), "no_rows")
            p.write_text("".join(json.dumps(r) + "\n" for r in self.ROWS), encoding="utf-8")
            first = ag.drawing_answers_stamp(d)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(_vis("visibility:Raze:C:enemy", "nothing")) + "\n")
                fh.write(json.dumps(_vis("visibility:Sova:C:ally", "icon")) + "\n")
            self.assertEqual(ag.drawing_answers_stamp(d), first)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(_vis("visibility:Omen:E:ally", "icon")) + "\n")
            self.assertNotEqual(ag.drawing_answers_stamp(d), first)


class _MemStore:
    """Stored heads in memory, as `plan` and `input_stamps.head_row` read them."""

    def __init__(self, root):
        self.root = Path(root)
        self.rows: dict[str, list[dict]] = {}

    def read_manifest(self, sid):
        return {"session_id": sid, "ingested_at": "2026-10-07T00:00:00"}

    def read_events(self, stream, sid):
        return self.rows.get(stream, [])

    def events_version(self, stream, sid):
        return None


def _verdict_store(root) -> _MemStore:
    """A store whose stored disc tracks and verdicts are current over their inputs."""
    from reticle.minimap_glyph import GLYPH_BANK_STAMP
    from reticle.plan import record_inputs
    store = _MemStore(root)
    store.rows["ability_glyph"] = [{"ability_glyph_version": ag.ABILITY_GLYPH_VERSION,
                                    "glyph_bank": GLYPH_BANK_STAMP, "hz": 2.0}]
    store.rows["tray_kit"] = [{"tray_kit_version": "tk-1"}]
    man = store.read_manifest(SID)
    store.rows["ability_disc_track"] = [
        record_inputs(store, man, "ability_disc_track",
                      {"kind": "coverage", "ability_disc_track_version": ag.ABILITY_DISC_TRACK_VERSION}),
        {"kind": "track", "track": "s1:adisc:1", "scale": 1.0,
         "fix": {"t_ms": [0.0], "cx": [10.0], "cy": [10.0]}}]
    store.rows["ability_glyph_name"] = [
        record_inputs(store, man, "ability_glyph_name",
                      {"kind": "coverage", "ability_glyph_name_version": ag.ABILITY_GLYPH_NAME_VERSION}),
        {"kind": "verdict", "track": "s1:adisc:1", "ability": {"key": "Tejo:C"}, "reason": None}]
    return store


class StoredVerdictStaleness(unittest.TestCase):
    """`disc_verdicts` hands out stored verdicts only where `plan`'s recorded
    input check and the glyph rows' `stale_reason` find them current."""

    def test_current_verdicts_are_read_with_their_content_stamp(self):
        from reticle.input_stamps import content_stamp
        with tempfile.TemporaryDirectory() as d:
            store = _verdict_store(d)
            got = ag.disc_verdicts(store, SID)
            self.assertNotIn("skipped", got)
            self.assertEqual(list(got["verdicts"]), ["s1:adisc:1"])
            self.assertEqual(got["stamp"], content_stamp(store.rows["ability_glyph_name"][0],
                                                         "ability_glyph_name_version"))

    def test_an_input_moved_since_the_verdicts_refuses_them(self):
        with tempfile.TemporaryDirectory() as d:
            store = _verdict_store(d)
            stamp = ag.disc_verdicts(store, SID)["stamp"]
            store.rows["tray_kit"] = [{"tray_kit_version": "tk-2"}]
            got = ag.disc_verdicts(store, SID)
            self.assertIn("tray_kit", got["skipped"])
            self.assertEqual(got["stamp"], stamp)

    def test_an_older_verdict_code_or_lineup_refuses_them(self):
        with tempfile.TemporaryDirectory() as d:
            store = _verdict_store(d)
            store.rows["ability_glyph_name"][0]["ability_glyph_name_version"] = "ability-glyph-name-0.0.1"
            self.assertIn("ability-glyph-name-0.0.1", ag.disc_verdicts(store, SID)["skipped"])
            store = _verdict_store(d)
            # a lineup file written after the verdicts read none
            (Path(d) / "lineups").mkdir()
            (Path(d) / "lineups" / f"{SID}.json").write_text(json.dumps({"version": "lineup-0.5.0"}),
                                                            encoding="utf-8")
            self.assertIn("lineup", ag.disc_verdicts(store, SID)["skipped"])

    def test_missing_or_stale_glyph_rows_refuse_without_raising(self):
        with tempfile.TemporaryDirectory() as d:
            store = _verdict_store(d)
            del store.rows["ability_glyph"]
            got = ag.disc_verdicts(store, SID)
            self.assertIn("no ability_glyph rows", got["skipped"])
            store = _verdict_store(d)
            store.rows["ability_glyph"][0]["glyph_bank"] = "glyph-bank-old"
            self.assertIn("glyph-bank-old", ag.disc_verdicts(store, SID)["skipped"])
            store = _verdict_store(d)
            del store.rows["ability_glyph_name"]
            got = ag.disc_verdicts(store, SID)
            self.assertEqual((got["stamp"], "no stored ability_glyph_name" in got["skipped"]),
                             ("no_rows", True))
