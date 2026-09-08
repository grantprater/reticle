import json
import tempfile
import unittest
from pathlib import Path

from reticle.round_lifetimes import RoundLifetimes, readable_kind, replay_scale


def detection(x=10,family="ally",view="minimap"):
    return dict(x=x,y=10,box=[x-5,5,10,10],family=family,view=view,label=family)


class RoundLifetimeTests(unittest.TestCase):
    def test_one_to_one_with_alternatives(self):
        life=RoundLifetimes("R1",0)
        first=life.step(0,[detection(10),detection(20)])
        rows=life.step(100,[detection(14),detection(16)])
        self.assertEqual(len({r['entity_id'] for r in rows}),2)
        self.assertEqual({r['entity_id'] for r in rows},{r['entity_id'] for r in first})
        self.assertTrue(all(r['state']=='ambiguous_continuation' for r in rows))

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


class ReplayScaleTests(unittest.TestCase):
    """An export replayed at the wrong widget scale is a silent wrong answer."""

    def test_scale_changes_which_observations_are_one_entity(self):
        # 8 widget px in 100 ms: inside the walker ceiling on a 465 px widget,
        # outside it on a 331 px one. Replaying either at the other's scale is
        # not a rounding difference, it is a different set of entities.
        ids = []
        for scale in (1.0, 0.7118):
            life = RoundLifetimes('R1', 0, scale)
            first = life.step(0, [detection(10)])[0]
            ids.append(first['entity_id'] == life.step(100, [detection(18)])[0]['entity_id'])
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


if __name__ == '__main__':
    unittest.main()
