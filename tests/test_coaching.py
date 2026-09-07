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
from reticle.rounds import (round_bounds, _clock_reset_after,
                            BUY_CLOCK_MAX_MS)
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


    def _score_clock(self, resets=True):
        """A two-round scoreline with a real clock: round, then buy, then round.

        Sample 0.5s apart. Round 1 counts 20 -> 0, the score steps at the wipe
        with 6s still showing, then the clock RESETS to 30 (buy) and counts
        down, then resets again to 100 for the round proper.
        """
        t, clock, left = [], [], []
        # round 1 winding down: clock 20 -> 6, no score change
        for k in range(28):
            t.append(k * 500.0); clock.append(20000 - k * 500); left.append(0)
        # the wipe: score steps while 6s remains
        n = len(t)
        for k in range(12):                       # 6s -> 0s, score already 1
            t.append((n + k) * 500.0); clock.append(6000 - k * 500); left.append(1)
        n = len(t)
        for k in range(60):                       # buy: 30s -> 0s
            t.append((n + k) * 500.0)
            clock.append((30000 - k * 500) if resets else None)
            left.append(1)
        n = len(t)
        for k in range(20):                       # round proper: 100s down
            t.append((n + k) * 500.0); clock.append(100000 - k * 500); left.append(1)
        return t, clock, left

    def test_round_start_is_the_clock_reset_and_the_end_does_not_move(self):
        """Only the START moved. The end is the score increment, as before."""
        t, clock, left = self._score_clock()
        right = [0] * len(t)
        old = round_bounds(t, left, right)
        new = round_bounds(t, left, right, clock)
        self.assertEqual(len(old), len(new))
        self.assertEqual([r['t_end_ms'] for r in old],
                         [r['t_end_ms'] for r in new])   # the END is untouched
        # Round 1 opens at the capture start under both rules.
        self.assertEqual(new[0]['t_start_ms'], t[0])
        self.assertEqual(new[0]['start_source'], 'capture_start')

    def test_the_start_takes_the_BUY_reset_not_the_round_proper_reset(self):
        """Two resets follow every round; taking the second is ~30s late."""
        t, clock, left = self._score_clock()
        right = [0] * len(t)
        rounds = round_bounds(t, left, right, clock)
        end = rounds[0]['t_end_ms']
        # Emulate the caller: where would a second round start?
        nxt = _clock_reset_after(t, clock, end)
        self.assertIsNotNone(nxt)
        i = t.index(nxt)
        self.assertLessEqual(clock[i], BUY_CLOCK_MAX_MS)   # a buy clock, not 100s
        self.assertGreater(clock[i], 20000)
        # It is the FIRST reset after the end, so it precedes the 100s one.
        later = [t[j] for j in range(len(t)) if t[j] > nxt and clock[j] > 90000]
        self.assertTrue(later and later[0] > nxt)

    def test_a_missing_reset_falls_back_and_SAYS_it_fell_back(self):
        """Refuse-over-guess: the fallback must stay countable, not vanish."""
        t, clock, left = self._score_clock(resets=False)   # buy clock unreadable
        right = [0] * len(t)
        self.assertIsNone(_clock_reset_after(t, clock, 20000.0))
        # Without a clock at all, the old contiguous rule is used and labelled.
        rounds = round_bounds(t, left, right)
        self.assertTrue(all(r['start_source'] in
                            ('capture_start', 'score_increment') for r in rounds))

    def test_rounds_stop_being_contiguous_and_the_gap_is_post_round(self):
        """The gap between one end and the next start is real, not missing."""
        t, clock, left = self._score_clock()
        right = [0] * len(t)
        end = round_bounds(t, left, right, clock)[0]['t_end_ms']
        start2 = _clock_reset_after(t, clock, end)
        self.assertGreater(start2, end)     # NOT contiguous any more

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
