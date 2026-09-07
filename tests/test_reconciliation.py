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
                readers[0].rows = [dict(frame_idx=0,t_ms=0,alive_ally=5,alive_enemy=5)]
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


if __name__ == '__main__':
    unittest.main()
