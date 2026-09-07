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
from reticle.roster import alive_from_detail
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

    def test_undrawn_and_wiped_rosters_are_not_distinguished(self):
        """A KNOWN DEFECT, asserted so a fix has to change this test on purpose.

        `DETAIL_FLOOR` exists to resolve the all-dead case and does not: a bar
        that is DRAWN but empty sits at 2-8 detail, which vetoes every occupied
        split and leaves `n = 0` losing to the -1.0 sentinel, so the read
        REFUSES. Only a near-black bar reaches 0. Confirmed by rendering on
        587c15b07779 at 158-174s -- see docs/ROSTER_FINDINGS.md.
        """
        wiped = [2.20,2.03,2.04,2.17,2.58]      # drawn, empty: should be 0
        black = [0.69,0.91,0.91,0.44,0.40]      # nothing drawn: should refuse
        self.assertIsNone(alive_from_detail(wiped,False))
        self.assertEqual(alive_from_detail(black,False),0)


if __name__ == '__main__':
    unittest.main()
