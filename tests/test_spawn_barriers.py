"""`reticle/spawn_barriers.py` and `map_regions.pre_round_areas`: the barrier
transforms, the stored table's provenance, the area's flood and cover, and
that neither reads a capture. Synthetic cases are no evidence."""
from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

import numpy as np

from reticle import map_regions as mr
from reticle import spawn_barriers as sb

STORE = Path.home() / "reticle-store"
HAS_TABLES = (STORE / "spawn_barriers").is_dir() and (STORE / "sightlines" / "choice.json").is_file()


def _comp(actor, name, typ, props):
    return {"Type": typ, "Name": name, "Outer": {"ObjectName": f"SpawnBarrier_C'L:PersistentLevel.{actor}'"},
            "Properties": props}


class TransformTest(unittest.TestCase):
    def test_roll_minus_90_stands_the_box_up(self):
        # the default GameObjectMesh: roll -90 turns local Y up and local Z across
        R = sb.rotator(0.0, 0.0, -90.0)
        np.testing.assert_allclose(R, [[1, 0, 0], [0, 0, 1], [0, -1, 0]], atol=1e-12)

    def test_yaw_90_turns_x_to_y(self):
        np.testing.assert_allclose(sb.rotator(0.0, 90.0, 0.0)[0], [0, 1, 0], atol=1e-12)

    def test_level_barrier_box_side_and_reason(self):
        defaults = {"SpawnBarrier_C": {
            "GameObjectMesh": {"RelativeLocation": {"X": 0, "Y": 0, "Z": 0.5},
                               "RelativeRotation": {"Pitch": 0, "Yaw": 0, "Roll": -90},
                               "RelativeScale3D": {"X": 1, "Y": 1, "Z": 0.1},
                               "StaticMesh": {"ObjectName": "StaticMesh'SuperGrid_BoxCentered'"}},
            "TheScene": {}}}
        level = [
            {"Type": "SpawnBarrier_C", "Name": "B1"},
            _comp("B1", "TheScene", "SceneComponent",
                  {"RelativeLocation": {"X": 1000, "Y": 2000, "Z": 0},
                   "RelativeRotation": {"Pitch": 0, "Yaw": 90, "Roll": 0}}),
            _comp("B1", "GameObjectMesh", "StaticMeshComponent",
                  {"RelativeLocation": {"X": 0, "Y": 0, "Z": 500}, "RelativeScale3D": {"X": 4, "Y": 10, "Z": 0.1}}),
            _comp("B1", "TeamRole", "TeamRoleComponent", {"TeamRole": "EAresTeamRole::Attacker"}),
            {"Type": "SpawnBarrier_C", "Name": "B2"},
            _comp("B2", "TheScene", "SceneComponent", {}),
        ]
        rows = sb.level_barriers(level, defaults, np.array([-50, -50, 0.0]), np.array([50, 50, 100.0]))
        b1, b2 = rows
        self.assertEqual((b1["side"], b2["side"], b2["side_reason"]), ("attack", None, "no_team_role"))
        c = np.asarray(b1["corners"])
        # 400 cm wide along world Y (yawed 90), 1000 cm tall, 10 cm thick along world X
        np.testing.assert_allclose(np.ptp(c, 0), [10, 400, 1000], atol=1e-6)
        np.testing.assert_allclose([c[:, 2].min(), c[:, 2].max()], [0, 1000], atol=1e-6)
        np.testing.assert_allclose(c[:, 1].mean(), 2000, atol=1e-6)


def _cells(nx=12, ny=3, step=100.0):
    """A corridor of cells along x on one floor, 8-connected."""
    ix, iy = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    ix, iy = ix.ravel(), iy.ravel()
    xy = np.column_stack([ix * step + step / 2, iy * step + step / 2])
    r, c = [], []
    for i in range(len(ix)):
        for j in range(len(ix)):
            if i < j and max(abs(ix[i] - ix[j]), abs(iy[i] - iy[j])) == 1:
                r.append(i)
                c.append(j)
    return {"xy": xy, "z": np.zeros(len(xy)), "r": np.array(r), "c": np.array(c), "grid_cm": step,
            "body_cm": 98.0, "jump_cm": 115.0, "table": "synthetic", "bridges": 0}


def _barrier(x0, x1, side):
    lo, hi = np.array([x0, -100.0, 0.0]), np.array([x1, 400.0, 1000.0])
    corners = sb.box_corners(lo, hi)[:, :3]
    return {"side": side, "corners": corners.tolist(),
            "plan": [[x0, -100], [x1, -100], [x1, 400], [x0, 400]]}


class PreRoundAreaTest(unittest.TestCase):
    def setUp(self):
        inv = np.tile(np.eye(4), (2, 1, 1))
        # attack spawn over x 0..300, defence spawn over x 900..1200
        self.reg = mr.Regions(inv, [[0, 0, -100], [900, 0, -100]], [[300, 300, 500], [1200, 300, 500]],
                              [{"region": "Spawn", "super": "Attacker Side"},
                               {"region": "Spawn", "super": "Defender Side"}])

    def test_barrier_stops_the_flood_and_the_area_covers_the_spawn(self):
        bars = {"barriers": [_barrier(500, 510, "attack"), _barrier(700, 710, "defence")]}
        A = mr.pre_round_areas(self.reg, bars, _cells())
        self.assertEqual(A["attack"]["basis"], "walk_flood")
        x = _cells()["xy"][A["attack"]["reached"]][:, 0]
        self.assertLess(x.max(), 500)
        self.assertGreater(x.max(), 300)          # past the volume, up to the barrier
        fp = mr.spawn_footprints(self.reg)
        for side in ("attack", "defence"):
            self.assertTrue(mr.in_polygon(A[side]["polygon"], fp[side]).all(), side)

    def test_a_gap_leaks_and_falls_back_to_the_hull(self):
        bars = {"barriers": [_barrier(500, 510, "attack")]}
        bars["barriers"][0]["corners"] = (np.asarray(bars["barriers"][0]["corners"])
                                          + [0, 1000, 0]).tolist()   # moved off the corridor
        bars["barriers"].append(_barrier(700, 710, "defence"))
        bars["barriers"][1]["corners"] = (np.asarray(bars["barriers"][1]["corners"])
                                          + [0, 1000, 0]).tolist()
        A = mr.pre_round_areas(self.reg, bars, _cells())
        self.assertEqual(A["attack"]["basis"], "hull")
        self.assertEqual(A["attack"]["fallback"], "leak:other_spawn")

    def test_no_walk_graph_falls_back_to_the_hull(self):
        bars = {"barriers": [_barrier(500, 510, "attack"), _barrier(700, 710, "defence")]}
        A = mr.pre_round_areas(self.reg, bars, None)
        self.assertEqual({a["basis"] for a in A.values()}, {"hull"})
        self.assertEqual(A["attack"]["fallback"], "no_walk_graph")

    def test_crossing_test(self):
        frames = mr.barrier_frames({"barriers": [_barrier(500, 510, "attack")]})
        a = np.array([[450.0, 50, 98], [450.0, 50, 98], [450.0, 50, 2000]])
        b = np.array([[550.0, 50, 98], [490.0, 50, 98], [550.0, 50, 2000]])
        np.testing.assert_array_equal(mr.crosses_boxes(a, b, frames), [True, False, False])


class NoCaptureTest(unittest.TestCase):
    BANNED = {"barriers", "roi_cache", "decode", "VideoCapture", "imread", "clip_preflight",
              "path_of", "crop", "read_frame", "Store", "read_hud"}

    def test_no_capture_pixels_are_read(self):
        fns = [sb.bake, sb.build, sb.load, sb.level_barriers, sb.class_defaults, sb.mesh_bounds,
               sb.side_footprints, mr.pre_round_areas, mr.walk_cells, mr.barrier_frames]
        for fn in fns:
            tree = ast.parse(inspect.getsource(fn))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
            self.assertFalse(names & self.BANNED, (fn.__name__, names & self.BANNED))

    def test_module_imports_no_capture_source(self):
        tree = ast.parse(Path(sb.__file__).read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse(mods & {"decode", "barriers", "roi_cache", "clip_preflight", "geometry"}, mods)


@unittest.skipUnless(HAS_TABLES, "no stored spawn-barrier tables")
class StoredTableTest(unittest.TestCase):
    def test_provenance_names_the_build_and_each_file(self):
        manifest = {}
        for f in sb.export_dir(STORE).glob("manifest*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    manifest[r["game_path"]] = r["sha256"]
        for key, level in sb.LEVELS.items():
            t = sb.load(key, STORE)
            p = t["provenance"]
            self.assertEqual((t["version"], p["build"], p["source"]),
                             (sb.SPAWN_BARRIERS_VERSION, sb.GAME_BUILD, "game files"))
            self.assertTrue(p["tool_commit"] and p["cue4parse"])
            paths = {f["game_path"]: f["sha256"] for f in p["files"]}
            self.assertIn(level, paths)
            for gp, sha in paths.items():
                self.assertEqual(sha, manifest[gp], gp)
            self.assertEqual(t["counts"]["refused"], 0, key)
            self.assertGreater(t["counts"]["attack"] + t["counts"]["defence"], 0, key)

    def test_the_table_rebakes_identically(self):
        t = json.loads(sb.barrier_table_path("lotus", STORE).read_text(encoding="utf-8"))
        self.assertEqual(json.dumps(sb.bake("lotus", STORE), sort_keys=True), json.dumps(t, sort_keys=True))

    def test_the_area_covers_the_spawn_volumes(self):
        for key in ("ascent", "lotus", "sunset"):
            reg = mr.Regions.load(key, STORE)
            A = mr.pre_round_areas(reg, sb.load(key, STORE), mr.walk_cells(key, STORE))
            fp = mr.spawn_footprints(reg)
            for side in ("attack", "defence"):
                self.assertEqual(A[side]["basis"], "walk_flood", (key, side))
                self.assertTrue(mr.in_polygon(A[side]["polygon"], fp[side]).all(), (key, side))


if __name__ == "__main__":
    unittest.main()
