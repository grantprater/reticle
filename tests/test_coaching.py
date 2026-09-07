"""Behavioral checks for leakage, abstention and event/round persistence."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from reticle.coaching import (observed_states, player_observations, evaluate_states,
                              attach_event_estimates, _coach_weights, run_coaching)
from reticle.store import Store
from reticle.cli import _resolve_session
from reticle.version import ROUND_VERSION, HUD_VERSION


def fixture_states(sessions=4, rounds=40):
    return [dict(session_id=str(sid), round_no=r, t_ms=r*100000 + k*1000,
                 alive_ally=4 if r % 2 else 2, alive_enemy=3,
                 clock_ms=90000-k*10000, won=bool(r % 2))
            for sid in range(sessions) for r in range(rounds) for k in range(3)]


class CoachingTests(unittest.TestCase):
    def test_holdout_is_independent_of_its_labels(self):
        states = fixture_states()
        report, models, predictions = evaluate_states(states)
        flipped = [dict(s, won=not s['won']) if s['session_id'] == '0' else s for s in states]
        _, changed, _ = evaluate_states(flipped)
        np.testing.assert_array_equal(models['0'], changed['0'])
        self.assertLess(report['brier'], report['baseline_brier'])
        for fold in report['folds']:
            self.assertNotIn(fold['held_out'], fold['training_sessions'])
        self.assertEqual(len(predictions), len(states))

    def test_repeated_states_do_not_inflate_evaluation(self):
        states = fixture_states()
        a, _, _ = evaluate_states(states)
        b, _, _ = evaluate_states(states + states)
        self.assertEqual(a, b)
        w = _coach_weights(states)
        self.assertAlmostEqual(w.sum(), 160)

    def test_one_session_abstains(self):
        report, models, predictions = evaluate_states(fixture_states(1))
        self.assertEqual(report['status'], 'insufficient_data')
        self.assertFalse(models)
        self.assertFalse(predictions)

    def test_no_future_roster_or_null_interpolation(self):
        rounds = [dict(t_start_ms=0, t_end_ms=1000, round_no=1, won=False),
                  dict(t_start_ms=1000, t_end_ms=30000, round_no=2, won=True)]
        h = pa.table(dict(t_ms=[1000, 2000, 3000, 4000, 5000, 6000],
                          clock_ms=[94000, 93000, 92000, None, 90000, 89000]))
        v = pa.table(dict(t_ms=[1000, 2000, 3000, 4000, 5000, 6000, 7000],
                          alive_ally=[5, 5, 0, 0, 4, 4, 5],
                          alive_enemy=[5, 5, 0, 0, 4, 4, 5]))
        states, reasons = observed_states(h, v, rounds, 's')
        self.assertEqual([s['t_ms'] for s in states], [2000, 6000])
        self.assertEqual(states[-1]['alive_ally'], 4)
        self.assertIn('roster_unknown_or_terminal', reasons)
        missing, _ = observed_states(h, None, rounds, 's')
        self.assertEqual(missing, [])

    def test_frozen_or_buy_clock_and_unsorted_time(self):
        rounds = [dict(t_start_ms=0, t_end_ms=1000, round_no=1, won=False),
                  dict(t_start_ms=1000, t_end_ms=30000, round_no=2, won=True)]
        v = pa.table(dict(t_ms=[1000, 2000, 3000], alive_ally=[5]*3, alive_enemy=[5]*3))
        for clock in ([30000, 29000, 28000], [90000]*3):
            h = pa.table(dict(t_ms=[1000, 2000, 3000], clock_ms=clock))
            states, _ = observed_states(h, v, rounds, 's')
            self.assertEqual(states, [])
        h = pa.table(dict(t_ms=[2000, 1000], clock_ms=[93000, 94000]))
        with self.assertRaises(ValueError):
            observed_states(h, v, rounds, 's')

    def test_tracks_clip_bounds_and_unresolved_round(self):
        h = pa.table(dict(t_ms=[1000., 1500., 2000., 2500.],
                          kf_kill_mask=[1, 1, 0, 0], kf_death_mask=[0, 0, 1, 0]))
        manifest = dict(session_id='s', source=dict(path='video.mp4', duration_ms=5000))
        events = player_observations(h, [], manifest)
        self.assertEqual(len(events), 1)  # one-frame death is not an event
        self.assertEqual(events[0]['clip_start_ms'], 0)
        self.assertEqual(events[0]['clip_end_ms'], 5000)
        self.assertIsNone(events[0]['round_no'])
        self.assertEqual(events, player_observations(h, [], manifest))

    def test_event_delta_requires_close_states_from_same_round(self):
        event = dict(session_id='s', round_no=2, t_ms=5000, quality_flags=[])
        states = [dict(session_id='s', round_no=1, t_ms=4000,
                       alive_ally=4, alive_enemy=3, clock_ms=90000, won=True),
                  dict(session_id='s', round_no=2, t_ms=6000,
                       alive_ally=4, alive_enemy=2, clock_ms=88000, won=True)]
        attach_event_estimates([event], states, {'s': np.zeros(4)})
        self.assertIsNone(event['state_delta'])
        states[0]['round_no'] = 2
        attach_event_estimates([event], states, {'s': np.zeros(4)})
        self.assertEqual(event['state_delta'], 0)
        states[0]['t_ms'] = 1000
        attach_event_estimates([event], states, {'s': np.zeros(4)})
        self.assertIsNone(event['state_delta'])

    def test_round_fields_survive_storage(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            row = dict(round_no=1, plant_t_ms=1234., post_plant_ms=4567.,
                       side_inferred='left', side_separation=0.25,
                       side_agrees=True, map='ascent')
            store.write_rounds([row], 's', '2026-09-07')
            table = store.read_rounds('s', '2026-09-07')
            actual = table.to_pylist()[0]
            for k, v in row.items():
                self.assertEqual(actual[k], v)
            self.assertEqual(table.schema.metadata[b'round_version'].decode(), ROUND_VERSION)

    def test_ambiguous_session_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            path = Path(d) / 'manifests'
            path.mkdir()
            for sid in ('abc', 'abd'):
                (path / f'{sid}.json').write_text(json.dumps(dict(session_id=sid)))
            with self.assertRaisesRegex(SystemExit, 'ambiguous'):
                _resolve_session(store, 'ab')
            self.assertEqual(_resolve_session(store, 'abc')['session_id'], 'abc')

    def test_bundle_staleness_identity_and_determinism(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            man = dict(session_id='s', ingested_at='2026-09-07',
                       source=dict(path='video.mp4', content_key='key', duration_ms=10000))
            mp = store.manifest_path('s')
            mp.parent.mkdir()
            mp.write_text(json.dumps(man))
            hp = store.hud_path('s', '2026-09-07')
            hp.parent.mkdir(parents=True)
            hud = pa.table(dict(t_ms=[1000., 1500.], clock_ms=[90000, 89000],
                                score_left=[0, 0], score_right=[0, 0],
                                kf_kill_mask=[1, 1], kf_death_mask=[0, 0],
                                kf_entry_mask=[1, 1]))
            out = Path(d) / 'analysis'
            def write_hud_version(version, sid='s'):
                pq.write_table(hud.replace_schema_metadata(dict(hud_version=version,
                               session_id=sid, content_key='key')), hp)
            write_hud_version('old')
            report = run_coaching(store, [man], out)
            self.assertEqual(report['skipped'][0]['reason'], 'stale_hud')
            self.assertEqual((out / 'events.jsonl').read_text(), '')
            write_hud_version(HUD_VERSION, 'wrong')
            report = run_coaching(store, [man], out)
            self.assertEqual(report['skipped'][0]['reason'], 'hud_identity_mismatch')
            write_hud_version(HUD_VERSION)
            report = run_coaching(store, [man], out)
            self.assertEqual(report['n_events'], 1)
            before = {p.name: p.read_bytes() for p in out.iterdir()}
            run_coaching(store, [man], out)
            self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})
            self.assertEqual(report['status'], 'insufficient_data')

    def test_round_source_version_is_actual_not_current(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            hp = store.hud_path('s', '2026-09-07')
            hp.parent.mkdir(parents=True)
            pq.write_table(pa.table(dict(t_ms=[0])).replace_schema_metadata(
                dict(hud_version='hud-old', content_key='real-key')), hp)
            store.write_rounds([dict(round_no=1)], 's', '2026-09-07')
            row = store.read_rounds('s', '2026-09-07').to_pylist()[0]
            self.assertEqual(row['hud_version'], 'hud-old')
            self.assertEqual(row['content_key'], 'real-key')


if __name__ == '__main__':
    unittest.main()
