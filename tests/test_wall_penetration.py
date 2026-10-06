"""What a bullet path crosses: placements, solid runs, impenetrable surfaces."""
import numpy as np
import pytest

pytest.importorskip("embreex")
trimesh = pytest.importorskip("trimesh")

from reticle.line_of_sight import Occluders  # noqa: E402
from reticle.wall_penetration import Penetration, intervals  # noqa: E402


def box(c, e):
    return np.asarray(trimesh.creation.box(extents=e).triangles) + np.asarray(c, float)


def scene(surfaces):
    """Two closed walls on the line y = 0, each one placement."""
    parts = [box((0, 0, 150), (10, 400, 300)), box((300, 0, 150), (20, 400, 300))]
    tris = np.concatenate(parts).astype(np.float32)
    src = np.concatenate([np.full(len(p), i) for i, p in enumerate(parts)])
    surf = np.concatenate([np.full(len(p), s) for p, s in zip(parts, surfaces)])
    occ = Occluders("toy", tris=tris)
    return Penetration(occ, src=src, surface_of_tri=surf)


def test_two_walls_two_placements_two_solids():
    pen = scene([0, 0])
    a, b = np.array([[-500.0, 0, 160]]), np.array([[800.0, 0, 160]])
    g = pen.lines(a, b)[0]
    assert g["crossings"] == 4 and g["placements"] == 2 and g["solids"] == 2
    assert g["solid_cm"] == pytest.approx(30.0, abs=0.5)
    assert g["impenetrable"] is False and g["unread"] is False and g["classes"] == ["High"]


def test_impenetrable_surface_is_reported():
    pen = scene([0, 1])
    g = pen.lines(np.array([[-500.0, 0, 160]]), np.array([[800.0, 0, 160]]))[0]
    assert g["impenetrable"] is True and "Impenetrable" in g["classes"]


def test_a_clear_line_crosses_nothing():
    pen = scene([0, 0])
    g = pen.lines(np.array([[-500.0, 900, 160]]), np.array([[800.0, 900, 160]]))[0]
    assert g["crossings"] == 0 and g["placements"] == 0 and g["solids"] == 0


def test_one_solid_from_two_shells():
    # an outer shell entered at 10 and an inner shell left at 40 bound one wall
    ln, op, run = intervals(np.zeros(4, int), np.array([10.0, 40.0, 60.0, 65.0]), np.zeros(4, int),
                            np.array([-1, 1, -1, 1]), np.array([100.0]), runs=True)
    assert ln.tolist() == [30.0, 0.0, 5.0, 0.0] and run.tolist() == [True, False, True, False]
