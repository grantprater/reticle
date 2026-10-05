"""prototypes/game_data_facts.py: inheritance checks, citation units, and
regeneration of domain/game_data.toml.

The synthetic tests build their own exports; the regeneration test reads the
store's game-file exports and skips when they are absent.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import game_data_facts as gd  # noqa: E402


def _export(pkg, super_pkg, default_props, comps=None):
    name = pkg.rsplit('/', 1)[1]
    out = [{'Type': 'BlueprintGeneratedClass', 'Name': name + '_C',
            'Super': {'ObjectPath': (super_pkg + '.1') if super_pkg else '/Script/Engine.Actor'}},
           {'Type': name + '_C', 'Name': f'Default__{name}_C', 'Properties': default_props}]
    for cname, props in (comps or {}).items():
        out.append({'Type': 'SphereComponent', 'Name': cname, 'Properties': props})
    return out


class Synthetic(unittest.TestCase):
    PARENT = '/Game/Test/Parent'
    MID = '/Game/Test/Mid'
    CHILD = '/Game/Test/Child'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        files = {
            self.PARENT: _export(self.PARENT, None, {'Duration': 4.0, 'Speed': 900.0,
                                                     'Curve': {'ObjectPath': '/Game/Test/Curve_A.0'}},
                                 {'Sphere_GEN_VARIABLE': {'SphereRadius': 1.0}}),
            self.MID: _export(self.MID, self.PARENT, {'Speed': 1200.0}),
            self.CHILD: _export(self.CHILD, self.MID, {},
                                {'Sphere_GEN_VARIABLE': {'RelativeScale3D': {'X': 410.0}}}),
        }
        for pkg, data in files.items():
            p = root / 'ability-states' / 'ShooterGame' / 'Content' / (pkg.replace('/Game/', '') + '.json')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data), encoding='utf-8')
        self._build, gd.BUILD = gd.BUILD, str(root)
        gd._cache.clear()

    def tearDown(self):
        gd.BUILD = self._build
        gd._cache.clear()
        self.tmp.cleanup()

    def test_chain_follows_super(self):
        self.assertEqual(gd.class_chain(self.CHILD), [self.CHILD, self.MID, self.PARENT])

    def test_inherited_value_reads_through_the_chain(self):
        self.assertEqual(gd.read(self.PARENT, 'Default__Parent_C', 'Duration', owner=self.CHILD), 4.0)

    def test_an_override_between_owner_and_source_refuses(self):
        with self.assertRaises(ValueError):
            gd.read(self.PARENT, 'Default__Parent_C', 'Speed', owner=self.CHILD)

    def test_reference_field_names_its_object(self):
        self.assertEqual(gd.read_ref(self.PARENT, 'Default__Parent_C', 'Curve', owner=self.CHILD),
                         '/Game/Test/Curve_A')

    def test_scale_factor_is_cited_without_a_length_unit(self):
        spec = [dict(agent='Test', slot='C', ability='Probe', missing=[], note='', refs=[], see=[], extra=None,
                     values=[gd.SPH('size', 'Sphere radius', self.CHILD, 'Sphere_GEN_VARIABLE',
                                    radius_pkg=self.PARENT, owner=self.CHILD)])]
        out, errors = gd.evaluate(spec)
        self.assertEqual(errors, [])
        row = out[0]['rows'][0]
        self.assertEqual(row['value'], 4.1)
        cite = gd.raw_cite(row)
        self.assertIn('SphereRadius = 1.0 cm x', cite)
        self.assertIn('RelativeScale3D.X = 410.0 (unitless scale)', cite)
        self.assertNotIn('410.0 cm', cite)

    def test_angle_is_its_own_group(self):
        rows = [dict(role='angle', tkey='max_angle_deg', value=45.0), dict(role='size', tkey='radius_m', value=3.0)]
        _, groups = gd.values_table(rows)
        self.assertEqual(groups, {'angle': {'max_angle_deg': 45.0}, 'size': {'radius_m': 3.0}})


class Regeneration(unittest.TestCase):
    def test_regenerated_text_equals_the_committed_file(self):
        if not Path(gd.BUILD).is_dir():
            self.skipTest(f'game-file exports absent: {gd.BUILD}')
        gd._cache.clear()
        text, cov = gd.render()
        self.assertEqual(text, gd.FACTS.read_text(encoding='utf-8'))
        self.assertEqual(len(cov), 116)


if __name__ == '__main__':
    unittest.main()
