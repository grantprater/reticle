"""The 3D sightline probe on a synthetic room: profiles, floors, occlusion, packing."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import sightlines_3d as s3  # noqa: E402

try:
    import embreex  # noqa: F401
    import trimesh  # noqa: F401
    HAVE_CASTER = True
except ImportError:
    HAVE_CASTER = False

INI = ("[/Script/Engine.CollisionProfile]\n"
       '+Profiles=(Name="BlockAll",CollisionEnabled=QueryAndPhysics,CustomResponses=)\n'
       '+Profiles=(Name="IgnoreOnlyPawn",CollisionEnabled=QueryAndPhysics,CustomResponses=((Channel="Pawn",Response=ECR_Ignore)))\n'
       '+EditProfiles=(Name="BlockAll",CustomResponses=((Channel="Level")))\n'
       "[/Script/Other]\n"
       '+Profiles=(Name="Elsewhere",CollisionEnabled=NoCollision,CustomResponses=)\n')


class ProfileTest(unittest.TestCase):
    def test_profiles_and_bodies(self):
        p = s3.parse_profiles(INI)
        self.assertNotIn("Elsewhere", p)
        self.assertTrue(s3.effective({"CollisionProfileName": "IgnoreOnlyPawn"}, p, "Weapon"))
        self.assertFalse(s3.effective({"CollisionProfileName": "IgnoreOnlyPawn"}, p, "Pawn"))
        off = {"CollisionProfileName": "BlockAll", "CollisionEnabled": "ECollisionEnabled::NoCollision"}
        self.assertFalse(s3.effective(off, p, "Weapon"))
        row = {"actor_class": "StaticMeshActor", "use_default_collision": False,
               "body": {"CollisionProfileName": "IgnoreOnlyPawn"}}
        self.assertEqual(s3.body_of(row, {"CollisionProfileName": "BlockAll"})["CollisionProfileName"], "IgnoreOnlyPawn")

    def test_pair_index_is_row_major_upper_triangle(self):
        n = 5
        i, j = np.triu_indices(n, 1)
        self.assertEqual(s3.pair_index(i, j, n).tolist(), list(range(n * (n - 1) // 2)))
        self.assertEqual(s3.pair_index(j, i, n).tolist(), list(range(n * (n - 1) // 2)))

    def test_bomb_mode_level_follows_the_dump(self):
        pers = [{"Type": "LevelStreamingAlwaysLoaded",
                 "Properties": {"WorldAsset": {"AssetPathName": "/Game/Maps/Infinity/Infinity_Art_Mid.Infinity_Art_Mid"}}}]
        lv = s3.streamed_levels(pers, "Infinity", {"Infinity_Modes_BombMode", "Infinity_Modes_FFA", "Infinity_Art_Mid"})
        self.assertEqual(lv, ["Infinity_Art_Mid", "Infinity_Modes_BombMode"])
        self.assertIn("Canyon_BombGameMode_Only", s3.streamed_levels([], "Canyon", {"Canyon_BombGameMode_Only"}))
        self.assertEqual(s3.streamed_levels([], "Ascent"), ["Ascent_Mode_BombMode"])

    def test_state_changing_classes(self):
        out = ["TimedDoorEvac_C", "Drawbridge_C", "DroppableDoorCover_C", "Switch_HiddenTemple_C",
               "WindowShield_C", "RespawningWallPlate_C", "BP_Destructible_BASE_C", "BP_Breakable_Simple_Rockman_C"]
        keep = ["StaticMeshActor", "Actor", "Tree_3_ConiferLarge_BP_C", "BP_WeaponBlockingVolume_C",
                "RadianiteSaltCrystal_C", "DescentBox_v5_C"]
        self.assertTrue(all(s3.STATE_CHANGING_CLASS.search(c) for c in out))
        self.assertFalse(any(s3.STATE_CHANGING_CLASS.search(c) for c in keep))

    def test_cell_callouts_take_the_smallest_volume(self):
        big, small = np.eye(4), np.eye(4)
        big[0, 0] = big[1, 1] = big[2, 2] = 10.0
        small[3, :3] = [100.0, 100.0, 0.0]
        reg = {"inv": np.linalg.inv(np.array([big, small])), "lo": np.zeros((2, 3)),
               "hi": np.array([[100.0, 100.0, 100.0], [50.0, 50.0, 100.0]])}
        got = s3.cell_callouts(np.array([[120.0, 120.0], [500.0, 500.0], [5000.0, 0.0]]), np.zeros(3), reg)
        self.assertEqual(got.tolist(), [1, 0, -1])

    def test_rotator_yaw_turns_x_to_y(self):
        v = np.array([1.0, 0.0, 0.0]) @ s3.rotator_matrix(0, 90, 0)
        np.testing.assert_allclose(v, [0, 1, 0], atol=1e-12)


@unittest.skipUnless(HAVE_CASTER, "embreex and trimesh are not installed")
class RoomTest(unittest.TestCase):
    def test_self_test_room(self):
        self.assertEqual(s3._self_test(), 0)

    def test_region_limits_floors(self):
        import trimesh
        ground = np.asarray(trimesh.creation.box(extents=(2000, 2000, 100)).triangles) + [0, 0, -50]
        c = s3.Caster(ground.astype(np.float32))
        m = np.eye(4)
        m[0, 0] = m[1, 1] = m[2, 2] = 5.0  # a 500 cm cube from the origin
        c.region = {"inv": np.linalg.inv(m)[None], "lo": np.zeros((1, 3)), "hi": np.full((1, 3), 100.0),
                    "names": ["r"]}
        z, _ = s3.floors(c, np.array([[250.0, 250.0], [-250.0, 250.0]]))
        self.assertAlmostEqual(float(z[0, 0]), 0.0, places=2)
        self.assertTrue(np.isnan(z[1]).all())


if __name__ == "__main__":
    unittest.main()
