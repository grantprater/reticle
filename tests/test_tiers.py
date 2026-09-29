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
        self.assertEqual({c.session for c in tiers.FAST}, {tiers.OMEN_DEMO, tiers.MATCH})
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


if __name__ == "__main__":
    unittest.main()
