import json
import tempfile
import unittest
from pathlib import Path

from reticle.round_lifetimes import (RoundLifetimes, ally_capacity, readable_kind,
                                     replay_scale)


def detection(x=10,family="ally",view="minimap"):
    return dict(x=x,y=10,box=[x-5,5,10,10],family=family,view=view,label=family)


class RoundLifetimeTests(unittest.TestCase):
    def test_appearance_cannot_link_after_motion_covers_widget(self):
        for scale in (1.0, 0.7118):
            life = RoundLifetimes('R1', 0, scale)
            first = life.step(0, [dict(detection(10, 'enemy'), appearance=[1.0])])[0]
            after = life.step(77000, [dict(detection(400, 'enemy'), appearance=[1.0])])[0]
            self.assertNotEqual(first['entity_id'], after['entity_id'])

    def test_appearance_reacquires_while_motion_is_informative(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [dict(detection(), appearance=[1.0])])[0]
        again = life.step(2000, [dict(detection(40), appearance=[1.0])])[0]
        self.assertEqual(first['entity_id'], again['entity_id'])

    def test_static_jitter_does_not_license_cumulative_drift(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [detection(10, 'barrier')])[0]
        jitter = life.step(100, [detection(15, 'barrier')])[0]
        drift = life.step(200, [detection(20, 'barrier')])[0]
        self.assertEqual(first['entity_id'], jitter['entity_id'])
        self.assertNotEqual(first['entity_id'], drift['entity_id'])
        self.assertEqual(drift['x'], 20)  # Never snap observations to the anchor.

    def test_known_kind_survives_unknown_but_refuses_conflicting_kind(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [dict(detection(family='object'), kind='ping:danger')])[0]
        unknown = life.step(100, [dict(detection(family='object'), kind='?')])[0]
        other = life.step(200, [dict(detection(family='object'), kind='ping:standard')])[0]
        self.assertEqual(first['entity_id'], unknown['entity_id'])
        self.assertNotEqual(first['entity_id'], other['entity_id'])

    def test_one_to_one_with_alternatives(self):
        life=RoundLifetimes("R1",0)
        first=life.step(0,[detection(10),detection(20)])
        rows=life.step(100,[detection(14),detection(16)])
        self.assertEqual(len({r['entity_id'] for r in rows}),2)
        self.assertEqual({r['entity_id'] for r in rows},{r['entity_id'] for r in first})
        self.assertTrue(all(r['state']=='ambiguous_continuation' for r in rows))
        self.assertTrue(all(r['identity_status']=='ambiguous' for r in rows))

    def test_later_evidence_resolves_both_sides_of_an_overlap_history(self):
        life = RoundLifetimes("R1", 0)
        first = life.step(0, [detection(10), detection(20)])
        overlap = life.step(100, [detection(14), detection(16)])
        component = life.association_components[overlap[0]["association_component_id"]]
        self.assertEqual(len(component["hypotheses"]), 2)
        # A later independently attributed portrait identifies the first
        # ambiguous observation. One-to-one conservation resolves the other.
        life.step(200, [], association_evidence=[{
            "observation_id": overlap[0]["observation_id"],
            "entity_id": first[0]["entity_id"],
            "evidence_ref": "portrait:later",
        }])
        self.assertEqual(
            life.association_for(overlap[0]["observation_id"])["entity_id"],
            first[0]["entity_id"])
        self.assertEqual(
            life.association_for(overlap[1]["observation_id"])["entity_id"],
            first[1]["entity_id"])
        report = life.association_report()
        self.assertEqual(report["summary"]["resolved"], 1)
        self.assertEqual(report["summary"]["retained_histories"], 1)
        self.assertEqual(report["revisions"][0]["evidence_ref"], "portrait:later")

    def test_successive_ambiguous_steps_share_one_history_component(self):
        life = RoundLifetimes("R1", 0)
        life.step(0, [detection(10), detection(20)])
        first = life.step(100, [detection(14), detection(16)])
        second = life.step(200, [detection(14), detection(16)])
        self.assertEqual(first[0]["association_component_id"],
                         second[0]["association_component_id"])
        self.assertEqual(life.association_report()["summary"]["components"], 1)

    def test_one_blob_preserves_both_entering_lives_as_a_composite_alternative(self):
        life = RoundLifetimes("R1", 0)
        first = life.step(0, [detection(10), detection(20)])
        blob = life.step(100, [detection(15)])[0]
        projection = life.association_for(blob["observation_id"])
        entering = sorted(r["entity_id"] for r in first)
        self.assertIn(entering, projection["membership_alternatives"])
        # The renderer lost multiplicity; the state model did not end a life.
        split = life.step(200, [detection(12), detection(18)])
        self.assertEqual(len(life.entities), 2)
        self.assertEqual(set(entering), {r["entity_id"] for r in split})

    def test_ambiguous_observation_does_not_contaminate_identity_appearance(self):
        life = RoundLifetimes("R1", 0)
        life.step(0, [dict(detection(10), appearance=[1., 0.]),
                      dict(detection(20), appearance=[0., 1.])])
        before = {eid: list(row["appearance"]) for eid, row in life.entities.items()}
        life.step(100, [dict(detection(14), appearance=[.5, .5]),
                        dict(detection(16), appearance=[.5, .5])])
        self.assertEqual({eid: row["appearance"] for eid, row in life.entities.items()}, before)

    def test_stall_cannot_refresh_any_view(self):
        life=RoundLifetimes("R1",0)
        life.step(0,[detection(),detection(view="world")])
        self.assertEqual(life.step(100,[detection()],source_state="stale"),[])
        self.assertTrue(all(e['observations']==1 for e in life.entities.values()))

    def test_gap_does_not_imply_death(self):
        life=RoundLifetimes("R1",0)
        a=life.step(0,[detection(family="self")])[0]
        life.step(100,[])
        b=life.step(3000,[detection(200,family="self")])[0]
        self.assertEqual(a['entity_id'],b['entity_id'])
        self.assertIsNone(life.finish(4000)[0]['end_ms'])
        self.assertIsNone(b['origin_ms'])

    def test_coordinate_systems_do_not_merge(self):
        life=RoundLifetimes("R1",0)
        a=life.step(0,[detection()])[0]
        b=life.step(100,[detection(view="world")])[0]
        self.assertNotEqual(a['entity_id'],b['entity_id'])

    def test_roster_capacity_is_not_identity(self):
        life=RoundLifetimes("R1",0)
        rows=life.step(0,[detection(family="self"),detection(40),detection(80)],roster={'alive_ally':2})
        self.assertEqual(rows[1]['acquisition'],'roster_slot_available_not_identity')
        self.assertEqual(rows[2]['acquisition'],'roster_count_conflict')
        self.assertIsNone(rows[1]['origin_ms'])

    def test_round_ids_and_observation_time(self):
        a=RoundLifetimes('R1',0).step(0,[detection()])[0]
        b=RoundLifetimes('R2',0).step(0,[detection()])[0]
        self.assertNotEqual(a['entity_id'],b['entity_id'])
        with self.assertRaises(ValueError):
            RoundLifetimes('R3',0).step(100,[dict(detection(),observed_t_ms=0)])


class AllyCapacityTests(unittest.TestCase):
    def test_the_roster_caps_allies_only_where_self_is_seen(self):
        self.assertEqual(ally_capacity(4, True), 3)
        self.assertIsNone(ally_capacity(4, False))
        self.assertIsNone(ally_capacity(None, True))
        self.assertEqual(ally_capacity(0, True), 0)

    def test_a_window_of_reads_takes_the_largest(self):
        self.assertEqual(ally_capacity([3, None, 4, 2], True), 3)
        self.assertIsNone(ally_capacity([None], True))

    def test_a_spectated_self_counted_among_the_allies_leaves_all_of_them(self):
        self.assertEqual(ally_capacity(3, True, spectated=True), 3)
        self.assertIsNone(ally_capacity(3, False, spectated=True))


class NameTests(unittest.TestCase):
    """The name is the fragmentation test, so it must be legible and fixed."""

    def test_families_get_english_names_and_the_self_gets_no_number(self):
        life = RoundLifetimes('R1', 0)
        rows = life.step(0, [detection(10, 'self'), detection(40), detection(80),
                             detection(200, 'enemy')])
        self.assertEqual([r['name'] for r in rows],
                         ['you', 'ally 1', 'ally 2', 'enemy 1'])

    def test_a_rebirth_is_visible_in_the_name(self):
        # The point of the whole scheme: a fifth ally in a 5v5 is wrong on the
        # face of the frame, where `E0119` is just another serial number.
        life = RoundLifetimes('R1', 0)
        life.step(0, [detection(10), detection(40)])
        born = life.step(5000, [detection(400)])[0]
        self.assertEqual(born['name'], 'ally 3')
        self.assertEqual(born['state'], 'first_observed')

    def test_a_reader_may_name_the_kind_and_the_name_survives_a_class_change(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [dict(detection(10, 'object'), kind='ping:danger')])[0]
        self.assertEqual(first['name'], 'ping:danger 1')
        again = life.step(100, [dict(detection(11, 'object'), kind='?',
                                     label='object?')])[0]
        self.assertEqual(again['entity_id'], first['entity_id'])
        self.assertEqual(again['name'], 'ping:danger 1')      # fixed at birth
        self.assertEqual(life.entities[again['entity_id']]['class_history'],
                         ['object', 'object?'])               # the class moved

    def test_an_unnamed_observation_still_gets_a_readable_kind(self):
        self.assertEqual(readable_kind({'family': 'ally_outline'}), 'ally shape?')
        self.assertEqual(readable_kind({'family': 'object'}), '?')
        self.assertEqual(readable_kind({'family': 'object', 'kind': 'ability?'}),
                         'ability?')


class RefitTests(unittest.TestCase):
    def test_a_fit_that_jumps_within_one_icon_is_the_same_entity(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [detection(10)])[0]
        again = life.step(67, [detection(22)])[0]
        self.assertEqual(again['entity_id'], first['entity_id'])
        self.assertEqual(again['state'], 'refit')

    def test_a_refit_never_takes_an_entity_observed_this_frame(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [detection(10)])[0]
        rows = life.step(67, [detection(11), detection(22)])
        self.assertEqual(rows[0]['entity_id'], first['entity_id'])
        self.assertNotEqual(rows[1]['entity_id'], first['entity_id'])


class ReplayScaleTests(unittest.TestCase):
    """An export replayed at the wrong widget scale is a silent wrong answer."""

    def test_scale_changes_which_observations_are_one_entity(self):
        # 20 widget px in 100 ms: past the walker ceiling at both scales, but a
        # REFIT on a 465 px widget (the lobe-jump limit is 24 px there) and a
        # new entity on a 331 px one (17.1 px). Replaying either at the other's
        # scale is not a rounding difference, it is a different set of entities.
        ids = []
        for scale in (1.0, 0.7118):
            life = RoundLifetimes('R1', 0, scale)
            first = life.step(0, [detection(10)])[0]
            ids.append(first['entity_id'] == life.step(100, [detection(30)])[0]['entity_id'])
        self.assertEqual(ids, [True, False])

    def test_stated_scale_is_read_not_derived(self):
        self.assertEqual(replay_scale({'widget_scale': 0.7118, 'session': 'nope'}),
                         (0.7118, 'provenance'))

    def test_missing_scale_is_derived_from_the_manifest_not_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manifests').mkdir()
            (root / 'manifests' / 'abc.json').write_text(json.dumps(
                {'source_profile': 'valorant-16x9',
                 'source': {'width': 1920, 'height': 1080}}), encoding='utf-8')
            scale, source = replay_scale({'session': 'abc'}, store_root=root)
        self.assertEqual(source, 'derived from manifest')
        self.assertAlmostEqual(scale, 0.7118, places=4)


class TerminationTests(unittest.TestCase):
    """Lifetime endings distinguish round survival, verified death, and unobserved loss."""

    def test_entity_active_near_round_end_resolves_to_round_end(self):
        life = RoundLifetimes('R1', 0)
        life.step(29000, [detection(10)])
        res = life.finish(30000, deaths=[])
        self.assertEqual(res[0]['end_reason'], 'round_end')
        self.assertIsNone(res[0]['end_ms'])
        self.assertEqual(res[0]['right_censored_at_ms'], 30000)

    def test_entity_midround_disappearance_near_death_resolves_to_death(self):
        life = RoundLifetimes('R1', 0)
        life.step(20000, [detection(10)])
        deaths = [{'kind': 'death_verdict', 'death_id': 'death:R1:1', 't_ms': 20500, 'side': 'ally'}]
        res = life.finish(50000, deaths=deaths)
        self.assertEqual(res[0]['end_reason'], 'death')
        self.assertEqual(res[0]['end_ms'], 20500)
        self.assertEqual(res[0]['death_id'], 'death:R1:1')
        self.assertIsNone(res[0]['right_censored_at_ms'])

    def test_entity_midround_disappearance_near_roster_drop_resolves_to_death(self):
        life = RoundLifetimes('R1', 0)
        life.step(20000, [detection(10)])
        res = life.finish(50000, roster_drops=[20500.0])
        self.assertEqual(res[0]['end_reason'], 'death')
        self.assertEqual(res[0]['end_ms'], 20500.0)
        self.assertEqual(res[0]['death_evidence'], 'roster:alive_ally_drop:20500.0')

    def test_unexplained_midround_disappearance_remains_right_censored(self):
        life = RoundLifetimes('R1', 0)
        life.step(10000, [detection(10)])
        res = life.finish(50000, deaths=[])
        self.assertEqual(res[0]['end_reason'], 'last observation does not establish destruction/death')
        self.assertIsNone(res[0]['end_ms'])
        self.assertEqual(res[0]['right_censored_at_ms'], 10000)

    def _two_lives_two_deaths(self):
        life = RoundLifetimes('R1', 0)
        for t in range(0, 20001, 500):
            life.step(t, [detection(10), detection(200)] if t <= 19000 else [detection(10)])
        deaths = [{'kind': 'death_verdict', 'death_id': 'dA', 't_ms': 20100, 'side': 'ally'},
                  {'kind': 'death_verdict', 'death_id': 'dB', 't_ms': 20900, 'side': 'ally'}]
        return life, deaths

    def test_the_default_admit_leaves_every_ending_unchanged(self):
        life, deaths = self._two_lives_two_deaths()
        base = life.finish(50000, deaths=deaths)
        self.assertEqual(life.finish(50000, deaths=deaths, admit=None), base)
        self.assertEqual(life.finish(50000, deaths=deaths, admit=lambda e, d: True), base)
        self.assertEqual(sorted(r['death_id'] for r in base), ['dA', 'dB'])

    def test_a_refused_death_stays_free_for_the_next_entity(self):
        life, deaths = self._two_lives_two_deaths()
        big = max(life.entities.values(), key=lambda e: e['observations'])['id']
        greedy = {r['id']: r['death_id'] for r in life.finish(50000, deaths=deaths)}
        self.assertEqual(greedy[big], 'dA')
        refuse = lambda e, d: not (e['id'] == big and d['death_id'] == 'dA')
        got = {r['id']: r['death_id'] for r in life.finish(50000, deaths=deaths, admit=refuse)}
        self.assertEqual(got[big], 'dB')
        self.assertEqual(sorted(v for v in got.values() if v), ['dA', 'dB'])

    def _big_late_and_small_early(self):
        """A large entity last seen at 22.0 s and a small one at 20.0 s."""
        life = RoundLifetimes('R1', 0)
        for t in range(0, 22001, 500):
            dets = [detection(10)]
            if 19000 <= t <= 20000:
                dets.append(detection(200))
            life.step(t, dets)
        big = max(life.entities.values(), key=lambda e: e['observations'])['id']
        small = next(i for i in life.entities if i != big)
        return life, big, small

    def test_the_nearest_last_sighting_takes_the_death_not_the_largest_entity(self):
        """bfad2778a372 R21: a Chamber track last seen 267 ms before
        Chamber's death lost it to one last seen 1.8 s before."""
        life, big, small = self._big_late_and_small_early()
        deaths = [{'death_id': 'd', 't_ms': 20100, 'side': 'ally'}]
        got = {r['id']: r['death_id'] for r in life.finish(50000, deaths=deaths)}
        self.assertEqual((got[small], got[big]), ('d', None))

    def test_the_entity_named_as_the_victim_takes_the_death(self):
        """5822b6646448 R5: an unnamed piece took Omen's death from the Omen
        piece. Here the named entity is the farther one in time."""
        from reticle.round_lifetimes import death_rank
        life, big, small = self._big_late_and_small_early()
        deaths = [{'death_id': 'd', 't_ms': 20300, 'side': 'ally', 'victim': 'Omen'}]
        names = {big: 'Omen'}
        rank = lambda e, d: death_rank(d, agent=names.get(e['id']),
                                       last_seen_ms=e['last_seen_ms'])
        got = {r['id']: r['death_id'] for r in life.finish(50000, deaths=deaths, rank=rank)}
        self.assertEqual((got[big], got[small]), ('d', None))

    def test_the_x_breaks_a_tie_in_time(self):
        from reticle.round_lifetimes import death_rank
        d = {'t_ms': 1000.0, 'location': (50.0, 50.0)}
        near = death_rank(d, last_seen_ms=900.0, last_xy=(52.0, 50.0))
        far = death_rank(d, last_seen_ms=1100.0, last_xy=(70.0, 50.0))
        unplaced = death_rank(d, last_seen_ms=1100.0)
        self.assertLess(near, far)
        self.assertLess(far, unplaced)



class OcclusionAndStackingTests(unittest.TestCase):
    """Occluded and stacked tracks remain eligible across extended temporal gaps."""

    def test_self_occlusion_extends_association_budget(self):
        life = RoundLifetimes('R1', 0)
        # Step 0: Ally near self (separation 10 px <= OCCLUSION_RADIUS_PX)
        first = life.step(0, [
            dict(detection(100), y=100),
            dict(detection(110, family='self'), y=100),
        ])
        ally_id = first[0]['entity_id']

        # Step 1500: Ally emerges from under self after 1.5s (> 0.75s standard budget)
        again = life.step(1500, [
            dict(detection(115), y=100),
            dict(detection(110, family='self'), y=100),
        ])
        self.assertEqual(again[0]['entity_id'], ally_id)
        self.assertEqual(again[0]['state'], 'continuation')

    def test_ally_stack_preserves_merged_track_continuity(self):
        life = RoundLifetimes('R1', 0)
        # Step 0: Two allies walking together (separation 15 px <= STACK_RADIUS_PX)
        first = life.step(0, [
            dict(detection(100), y=100),
            dict(detection(115), y=100),
        ])
        e1, e2 = first[0]['entity_id'], first[1]['entity_id']

        # Step 1000: Merged stack: only one icon detected
        life.step(1000, [dict(detection(105), y=100)])

        # Step 2000: Un-stacking after 2.0s (> 0.75s standard budget)
        split = life.step(2000, [
            dict(detection(100), y=100),
            dict(detection(115), y=100),
        ])
        self.assertEqual(len(life.entities), 2)
        self.assertEqual({r['entity_id'] for r in split}, {e1, e2})

    def test_stationary_dropout_bridges_flicker(self):
        life = RoundLifetimes('R1', 0)
        first = life.step(0, [dict(detection(200), y=200)])
        # Reappears 1.8s later at almost identical position (d=1 px <= STATIONARY_RADIUS_PX)
        again = life.step(1800, [dict(detection(201), y=200)])
        self.assertEqual(again[0]['entity_id'], first[0]['entity_id'])
        self.assertEqual(again[0]['state'], 'continuation')



class DetectionRealityTests(unittest.TestCase):
    """`detection_reality` and the coincidence it pools, on synthetic rows."""

    def test_an_observation_lies_on_the_nearest_fix_within_half_a_period_and_reach(self):
        import numpy as np
        from reticle.round_lifetimes import glyph_coincidence
        # fixes at 0 ms (x 100) and 500 ms (x 104 and x 130); reach 10 px
        ft, fx, fy = [0.0, 500.0, 500.0], [100.0, 104.0, 130.0], [50.0, 50.0, 50.0]
        t = [100.0, 300.0, 400.0, 900.0, 260.0]
        x = [101.0, 103.0, 129.0, 104.0, 160.0]
        got = glyph_coincidence(t, x, [50.0] * 5, ft, fx, fy, [10.0] * 3, 250.0)
        # 100 ms: only the 0 ms fix is within 250 ms; 300 ms: the 500 ms fix
        # at x 104 is nearer than nothing else in time; 400 ms: x 130 is
        # nearest; 900 ms: no fix within 250 ms; 260 ms at x 160: none in reach
        self.assertEqual(got.tolist(), [0, 1, 2, -1, -1])
        self.assertEqual(glyph_coincidence([], [], [], ft, fx, fy, [10.0] * 3, 250.0).size, 0)
        self.assertTrue((glyph_coincidence(t, x, [50.0] * 5, [], [], [], [], 250.0) == -1).all())

    def test_the_reach_is_one_icon_radius_at_the_fix_scale(self):
        from reticle.minimap_objects import ICON_PX
        from reticle.round_lifetimes import glyph_reach
        self.assertEqual(glyph_reach([1.0, 0.5]).tolist(), [ICON_PX, ICON_PX * 0.5])

    def test_a_named_or_tied_glyph_is_placed_and_a_null_one_is_not(self):
        from reticle.round_lifetimes import glyph_placed
        self.assertTrue(glyph_placed({"ability": {"key": "Tejo:C"}, "reason": None}))
        self.assertTrue(glyph_placed({"ability": None, "reason": "pairwise_tie"}))
        for why in ("below_null", "occluded", "no_clean_frame"):
            self.assertFalse(glyph_placed({"ability": None, "reason": why}))
        self.assertFalse(glyph_placed(None))

    def test_a_track_mostly_on_a_placed_glyph_is_refused_with_both_hypotheses(self):
        from reticle.round_lifetimes import detection_reality
        verdicts = {"d1": {"ability": {"key": "Tejo:C"}, "reason": None, "best": "Tejo:C",
                           "second": "Cypher:E", "pooled": 0.9, "cut": 0.6},
                    "d2": {"ability": None, "reason": "below_null", "best": "Sova:C",
                           "second": None, "pooled": 0.3, "cut": 0.6}}
        got = detection_reality(10, {"d1": 6, "d2": 4}, verdicts)
        self.assertEqual((got["status"], got["reason"], got["glyph_support"]),
                         ("refused", "alternative_ability_glyph", 6))
        self.assertEqual(got["alternatives"][0], {"hypothesis": "drawn_player", "support": 4})
        self.assertEqual(got["alternatives"][1]["keys"], {"Tejo:C": 6})
        self.assertEqual([e["track"] for e in got["evidence"]], ["d1"])

    def test_half_or_less_on_a_glyph_is_accepted_and_no_verdicts_is_unassessed(self):
        from reticle.round_lifetimes import detection_reality
        v = {"d1": {"ability": None, "reason": "pairwise_tie", "best": "Tejo:C",
                    "second": "Cypher:E", "pooled": 0.7, "cut": 0.6}}
        got = detection_reality(10, {"d1": 5}, v)
        self.assertEqual((got["status"], got["reason"]), ("accepted", None))
        self.assertEqual(got["alternatives"][1]["keys"], {"Tejo:C": 5, "Cypher:E": 5})
        got = detection_reality(10, {}, None, unassessed="no glyph verdicts")
        self.assertEqual((got["status"], got["reason"], got["glyph_support"]),
                         ("unassessed", "no glyph verdicts", None))


if __name__ == '__main__':
    unittest.main()

