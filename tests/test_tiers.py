"""The fast verification tier's wiring: the parser, the exit code, and the
rules each check applies. The checks' own runs read the store and belong to
`reticle verify --tier fast`, not here."""
from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from reticle import cli, tiers


class ParserTests(unittest.TestCase):
    def test_verify_takes_a_tier(self):
        args = cli.build_parser().parse_args(["verify", "--tier", "fast"])
        self.assertEqual(args.tier, "fast")
        self.assertIsNone(args.only)
        self.assertIs(args.func, cli.cmd_verify)

    def test_verify_without_a_tier_keeps_the_session_form(self):
        args = cli.build_parser().parse_args(["verify", "a06f04a0059f"])
        self.assertIsNone(args.tier)
        self.assertEqual(args.session, "a06f04a0059f")

    def test_unknown_tier_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["verify", "--tier", "corpus"])


class DeclarationTests(unittest.TestCase):
    def test_fast_tier_is_declared_with_sources(self):
        ids = [c.id for c in tiers.FAST]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({c.session for c in tiers.FAST},
                         {tiers.OMEN_DEMO, tiers.MATCH, tiers.LOTUS})
        for c in tiers.FAST:
            self.assertIn(c.kind, ("accuracy", "consistency"))
            self.assertTrue(c.source)
        # A baseline check says so: consistency is never presented as accuracy.
        for c in tiers.FAST:
            if c.kind == "consistency":
                self.assertIn("not a known answer", c.source)


def _fake(statuses):
    return [{"id": f"c{i}", "session": "s", "kind": "accuracy", "source": "src",
             "seconds": 0.0, "status": s, "measured": 1, "known": 1, "detail": ""}
            for i, s in enumerate(statuses)]


class ExitCodeTests(unittest.TestCase):
    def _run(self, statuses):
        args = cli.build_parser().parse_args(["verify", "--tier", "fast"])
        out = io.StringIO()
        with mock.patch.object(tiers, "run", return_value=_fake(statuses)), \
                mock.patch.object(cli, "Store") as store, contextlib.redirect_stdout(out):
            store.return_value.read_manifest.return_value = {"source": {"path": "x.mp4"}}
            code = cli.cmd_verify(args)
        return code, out.getvalue()

    def test_all_pass_exits_zero(self):
        code, out = self._run(["PASS", "PASS"])
        self.assertEqual(code, 0)
        self.assertIn("2 pass, 0 fail, 0 stale of 2", out)

    def test_a_failure_exits_one(self):
        self.assertEqual(self._run(["PASS", "FAIL"])[0], 1)

    def test_stale_is_not_a_pass(self):
        code, out = self._run(["PASS", "STALE"])
        self.assertEqual(code, 1)
        self.assertIn("1 stale", out)


class RuleTests(unittest.TestCase):
    def test_drops_match_labelled_casts_by_slot_and_time(self):
        casts = [{"slot": "E", "t_ms": 20000.0}, {"slot": "C", "t_ms": 7500.0}]
        drops = [{"slot": "E", "t_ms": 20500.0}, {"slot": "C", "t_ms": 7500.0},
                 {"slot": "Q", "t_ms": 9000.0}]
        m = tiers.match_drops(drops, casts)
        self.assertEqual((m["found"], m["missed"], m["extra"]), (2, [], ["Q@9.0s"]))

    def test_a_drop_in_another_slot_or_too_late_misses(self):
        m = tiers.match_drops([{"slot": "Q", "t_ms": 20000.0}, {"slot": "E", "t_ms": 21500.0}],
                              [{"slot": "E", "t_ms": 20000.0}])
        self.assertEqual(m["found"], 0)
        self.assertEqual(m["missed"], ["E@20.0s"])

    def test_one_drop_matches_one_cast(self):
        m = tiers.match_drops([{"slot": "C", "t_ms": 7000.0}],
                              [{"slot": "C", "t_ms": 7000.0}, {"slot": "C", "t_ms": 7400.0}])
        self.assertEqual(m["found"], 1)

    def test_a_stale_stored_stream_reports_stale(self):
        stamps = {"hud": ("hud-0.1.0", "hud-9.9.9"), "killfeed_portrait": ("a", "a"),
                  "combat_report": ("b", "b")}
        store = mock.Mock()
        store.read_manifest.return_value = {"ingested_at": "2026-08-26T00:00:00"}
        with mock.patch.object(tiers, "_stored_stamps", return_value=stamps):
            r = tiers.check_match_kd(store)
        self.assertEqual(r["status"], tiers.STALE)
        self.assertIn("hud-0.1.0", r["detail"])



def _facing(errors_lotus, errors_control, unread=()):
    return {tiers.LOTUS: {"errors": [(float(i), e) for i, e in enumerate(errors_lotus)],
                          "unread": list(unread)},
            tiers.OMEN_DEMO: {"errors": [(float(i), e) for i, e in enumerate(errors_control)],
                              "unread": []}}


class SelfFacingTests(unittest.TestCase):
    LOTUS_OK = [2.0] * 26 + [170.0, -150.0]
    CONTROL_OK = [1.5] * 8

    def _check(self, groups):
        with mock.patch.object(tiers, "self_facing_errors", return_value=(groups, "")):
            return tiers.check_self_facing(mock.Mock())

    def test_the_error_wraps_round_the_circle(self):
        self.assertAlmostEqual(tiers.facing_error_deg(179.0, -179.0), -2.0)
        self.assertAlmostEqual(tiers.facing_error_deg(-170.0, 170.0), 20.0)

    def test_the_labelled_answer_passes(self):
        self.assertEqual(self._check(_facing(self.LOTUS_OK, self.CONTROL_OK))["status"],
                         tiers.PASS)

    def test_one_more_flip_fails(self):
        lotus = self.LOTUS_OK[:-3] + [2.0, 170.0, -150.0, 95.0]
        self.assertEqual(self._check(_facing(lotus, self.CONTROL_OK))["status"], tiers.FAIL)

    def test_a_flipped_control_fails(self):
        self.assertEqual(self._check(_facing(self.LOTUS_OK, [1.5] * 7 + [180.0]))["status"],
                         tiers.FAIL)

    def test_reading_fewer_items_fails(self):
        self.assertEqual(self._check(_facing(self.LOTUS_OK[1:], self.CONTROL_OK))["status"],
                         tiers.FAIL)

    def test_a_wider_median_fails(self):
        self.assertEqual(self._check(_facing([3.5] * 26 + [170.0, -150.0],
                                             self.CONTROL_OK))["status"], tiers.FAIL)

    def test_missing_labels_fail(self):
        with mock.patch.object(tiers, "self_facing_errors", return_value=(None, "no labels")):
            r = tiers.check_self_facing(mock.Mock())
        self.assertEqual((r["status"], r["detail"]), (tiers.FAIL, "no labels"))


if __name__ == "__main__":
    unittest.main()
