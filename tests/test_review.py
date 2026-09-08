import copy
import unittest

from reticle.review import select_review_windows, render_review


def ctx():
    return {'s': {'source_path': r'C:\video\x.mp4', 'duration_ms': 10000,
                  'rounds': [{'round_no': 1, 't_start_ms': 1000, 't_end_ms': 9000}]}}


class ReviewTests(unittest.TestCase):
    def test_controls_and_event_bounds_overlap_and_render(self):
        events = [{'event_id': 'e', 'session_id': 's', 'round_no': 1, 't_ms': 8000,
                   'kind': 'player_kill', 'clip_start_ms': 0, 'clip_end_ms': 10000}]
        states = [dict(session_id='s', round_no=1, t_ms=t, won=x, state_delta=x)
                  for t, x in [(1000, True), (5000, False), (5000, True)]]
        rows = select_review_windows(events, states, ctx())
        control = next(r for r in rows if r['review_kind'] == 'ordinary_state_control')
        self.assertEqual(control['overlapping_event_ids'], [])
        self.assertGreaterEqual(control['clip_start_ms'], 1000)
        self.assertLessEqual(control['clip_end_ms'], 9000)
        self.assertIn('[Open video]', render_review(rows, 'ok'))
        self.assertIn('player_kill', render_review(rows, 'ok'))

    def test_overlap_and_selection_independent_of_labels(self):
        e = {'event_id': 'e', 'session_id': 's', 'round_no': 1, 't_ms': 8500,
             'kind': 'player_death', 'clip_start_ms': 8000, 'clip_end_ms': 9000}
        states = [dict(session_id='s', round_no=1, t_ms=t, won=False, probability=9, state_delta=4)
                  for t in (3000, 5000, 7000)]
        a = select_review_windows([e], states, ctx())
        changed = [dict(x, won=True, probability=-2, state_delta=-8) for x in states]
        b = select_review_windows([e], changed, ctx())
        self.assertEqual(a, b)
        self.assertIn('e', next(r for r in a if r['review_kind'].startswith('ordinary'))['overlapping_event_ids'])

    def test_overlap_uses_half_open_window_not_symmetric_radius(self):
        contexts = {'s': dict(source_path='x', duration_ms=40000,
                             rounds=[dict(round_no=1, t_start_ms=0, t_end_ms=30000)])}
        states = [dict(session_id='s', round_no=1, t_ms=10000)]
        events = [dict(event_id=str(t), session_id='s', round_no=1, t_ms=t)
                  for t in (1999, 2000, 15999, 16000, 17000)]
        control = next(r for r in select_review_windows(events, states, contexts)
                       if r['review_kind'] == 'ordinary_state_control')
        self.assertEqual(control['overlapping_event_ids'], ['15999', '2000'])

    def test_gap_and_round_end_anchors_refuse_and_source_end_clamps(self):
        contexts = ctx()
        for t in (999, 9000, 9500):
            event = dict(event_id='e', session_id='s', round_no=1, t_ms=t)
            state = dict(session_id='s', round_no=1, t_ms=t)
            self.assertEqual(select_review_windows([event], [state], contexts), [])
        contexts['s']['duration_ms'] = 6000
        state = dict(session_id='s', round_no=1, t_ms=5000)
        row = select_review_windows([], [state], contexts)[0]
        self.assertEqual((row['clip_start_ms'], row['clip_end_ms']), (1000, 6000))
        state['t_ms'] = 6000
        self.assertEqual(select_review_windows([], [state], contexts), [])

    def test_no_states_and_invalid_interval_refused(self):
        self.assertEqual(select_review_windows([], [], ctx()), [])
        bad = {'s': {'source_path': 'x', 'duration_ms': 500,
                      'rounds': [{'round_no': 1, 't_start_ms': 1000, 't_end_ms': 900}]}}
        e = {'event_id': 'e', 'session_id': 's', 'round_no': 1, 't_ms': 800,
             'clip_start_ms': 0, 'clip_end_ms': 1000}
        self.assertEqual(select_review_windows([e], [], bad), [])

    def test_input_rows_unchanged_and_order_independent(self):
        e = {'event_id': 'e', 'session_id': 's', 'round_no': 1, 't_ms': 4000,
             'kind': 'player_kill', 'clip_start_ms': 0, 'clip_end_ms': 9000}
        states = [dict(session_id='s', round_no=1, t_ms=t) for t in (7000, 3000, 5000)]
        original = copy.deepcopy((e, states))
        a = select_review_windows([e], states, ctx())
        b = select_review_windows([e], list(reversed(states)), ctx())
        self.assertEqual(a, b)
        self.assertEqual((e, states), original)


if __name__ == '__main__':
    unittest.main()
