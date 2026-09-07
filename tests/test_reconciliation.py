import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa

from reticle.reconciliation import audit_scoreline, audit_roster_deltas
from reticle.cli import build_parser, cmd_scan
from reticle.roster import alive_from_detail, resolve
from reticle.store import Store


class ReconciliationTests(unittest.TestCase):
    def test_score_confirmation_is_diagnostic_and_reports_first_confirmation(self):
        h = pa.table(dict(t_ms=[0,500,1000,1500,2000,2500,3000,3500,4000],
                          score_left=[0,0,1,0,0,1,1,1,2], score_right=[0]*9))
        r = audit_scoreline(h)
        self.assertEqual(r['raw_boundaries'], 3)
        self.assertEqual(r['confirmed_boundaries'], 1)
        self.assertEqual(r['proposed'][0]['t_ms'], 2500)
        self.assertEqual(r['proposed'][0]['confirmed_ms'], 3000)
        self.assertEqual(len(r['unsupported_raw_boundaries']), 2)

    def test_roster_delta_uses_actual_non_five_baseline(self):
        t = list(range(0,60500,500))
        h = pa.table(dict(t_ms=t,score_left=[0 if x<1000 else 1 if x<60000 else 2 for x in t],
                          score_right=[0]*len(t),
                          kf_entry_mask=[1 if 16000<=x<=16500 else 0 for x in t]))
        v = pa.table(dict(t_ms=t,alive_ally=[4]*len(t),
                          alive_enemy=[4 if x<16000 else 3 for x in t]))
        r = audit_roster_deltas(h,v)
        self.assertEqual(r['counts']['agree'], 4)
        self.assertEqual(r['windows'][0]['roster_drop'], 1)
        self.assertEqual(r['windows'][0]['observed_start'], (4,4))
        # Missing killfeed coverage must not be interpreted as no deaths.
        sparse = h.filter(pa.array([not 14000 <= x <= 18000 for x in t]))
        self.assertEqual(audit_roster_deltas(sparse,v)['windows'][0]['status'],
                         'hud_gap_or_unreadable')
        data = v.to_pydict()
        data['alive_ally'][40] = None
        self.assertEqual(audit_roster_deltas(h,pa.table(data))['windows'][0]['status'],
                         'unreadable_roster')
        data['alive_ally'][40] = 5
        self.assertEqual(audit_roster_deltas(h,pa.table(data))['windows'][0]['status'],
                         'count_increase_requires_explanation')

    def test_roster_only_scan_uses_shared_pass_without_geometry_or_hud(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            media = Path(d)/'source.mp4'
            media.touch()  # decode is mocked, but the source-presence contract is real
            man = dict(session_id='s',ingested_at='2026-09-07',source_profile='valorant-16x9',
                       source=dict(path=str(media),filename=media.name,content_key='k',
                                   width=1920,height=1080,fps=60,duration_ms=1000))
            mp = store.manifest_path('s')
            mp.parent.mkdir()
            mp.write_text(json.dumps(man))
            def shared_pass(ctx,readers,progress):
                self.assertEqual([r.name for r in readers],['roster'])
                readers[0].rows = [dict(frame_idx=0,t_ms=0,alive_ally=5,alive_enemy=5,
                                        detail_ally=[30.0]*5,detail_enemy=[30.0]*5)]
                return 1
            args = build_parser().parse_args(['--store',d,'scan','s','--only','roster'])
            with patch('reticle.cli.passes_run',side_effect=shared_pass) as run, \
                    patch('reticle.cli._active_spans',side_effect=AssertionError('unnecessary spans')), \
                    patch('reticle.cli._HudPass',side_effect=AssertionError('unnecessary HUD')), \
                    patch('reticle.cli._MinimapPass',side_effect=AssertionError('unnecessary geometry')), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_scan(args),0)
                self.assertEqual(cmd_scan(args),0)  # current roster is a cache hit
                self.assertEqual(run.call_count,1)
            self.assertTrue(store.has_roster('s','2026-09-07'))
            self.assertFalse(store.hud_path('s','2026-09-07').exists())
            # The EVIDENCE is stored beside the count, and the count is
            # re-derivable from it -- that is the whole point of roster-0.2.0,
            # so it is asserted rather than left to a docstring.
            v = store.read_roster('s','2026-09-07').to_pydict()
            self.assertEqual(list(v['detail_ally'][0]),[30.0]*5)
            self.assertEqual(alive_from_detail(list(v['detail_ally'][0]),True),
                             v['alive_ally'][0])

    def test_empty_bar_is_resolved_by_the_hud_and_never_guessed(self):
        """Which of `wiped` and `no HUD` an empty bar is comes from the SCORELINE.

        Per-slot detail cannot separate them -- these two vectors are both dim
        and the darker one is the DRAWN case on real footage. The frames are
        587c15b07779 at 158s (wiped, scoreline reads) and c40d950031bb at 967s
        (capture ending, scoreline null); see docs/ROSTER_FINDINGS.md.
        """
        wiped = [2.20,2.03,2.04,2.17,2.58]
        black = [0.69,0.91,0.91,0.44,0.40]
        for d in (wiped, black):
            self.assertEqual(alive_from_detail(d,False,True), 0)   # HUD drawn
            self.assertIsNone(alive_from_detail(d,False,False))    # HUD absent
            self.assertIsNone(alive_from_detail(d,False))          # unknown

    def test_split_is_scale_free_and_refuses_an_unpacked_bar(self):
        """The ratio rule, and the sentinel that keeps it from over-answering."""
        # 587c15b07779 1483.0s: two portraits, the widest ABSOLUTE gap says one.
        self.assertEqual(alive_from_detail([7.92,9.67,6.73,22.71,37.42],True), 2)
        # Doubling the whole vector cannot change how many are drawn.
        self.assertEqual(alive_from_detail([15.84,19.34,13.46,45.42,74.84],True), 2)
        # Bright slots that are not a contiguous run from the inner edge: the
        # packing premise fails, so refuse rather than pick the least-bad split.
        self.assertIsNone(alive_from_detail([7.34,31.09,7.32,37.00,13.04],True))
        self.assertEqual(alive_from_detail([30.0]*5,True), 5)

    def test_resolve_never_borrows_a_future_hud_row(self):
        """The gate is an as-of join, and out-of-range leaves it unknown."""
        roster = pa.table(dict(t_ms=[0.0,5000.0,10000.0],
                               alive_ally=[None]*3, alive_enemy=[None]*3,
                               detail_ally=[[2.0]*5]*3, detail_enemy=[[2.0]*5]*3))
        hud = pa.table(dict(t_ms=[4800.0], score_left=[1], score_right=[0]))
        ally, enemy = resolve(hud, roster)
        # t=0 precedes the only HUD row, t=10000 is 5.2s past it: both unknown.
        self.assertEqual(ally, [None, 0, None])
        self.assertEqual(enemy, [None, 0, None])
        blank = pa.table(dict(t_ms=[4800.0], score_left=[None], score_right=[None]))
        self.assertEqual(resolve(blank, roster)[0], [None, None, None])


if __name__ == '__main__':
    unittest.main()
