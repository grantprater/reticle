import unittest
from reticle.round_lifetimes import RoundLifetimes


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


if __name__ == '__main__':
    unittest.main()
