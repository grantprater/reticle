"""Line of sight between world points, through a map's static collision.

[owns:line-of-sight]

A map's 3D sightline table (`<store>/sightlines/<map>__<version>.npz`, the
version `<store>/sightlines/choice.json` names for the map) stores every
triangle the probe kept and a mask of those that block the Weapon trace
channel (docs/SIGHTLINES_3D_PROBE.md). This module loads that mask's
triangles into an embree scene and answers whether a segment between two
world points (cm, Unreal axes) crosses one. It reads the stored table only;
the builder stays `prototypes/sightlines_3d.py`, and nothing here imports it.

Doors, breakables, smokes and ability walls are absent from the table. A
wall a gun shoots through blocks here; `wall_penetration` says what lies on
the line.

Facts: [domain:game_data/character-eye-height] (the eye stands 77 cm above
the capsule centre, which is the actor location a replay records).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .store import DEFAULT_STORE

LINE_OF_SIGHT_VERSION = "line-of-sight-0.1.0"
#: BaseEyeHeight: the standing eye above the capsule centre, in cm
#: [domain:game_data/character-eye-height].
EYE_ABOVE_CENTRE_CM = 77.0
#: A segment stops this short of its end, so a target standing against a
#: wall is not hidden by the wall behind it.
END_SLACK_CM = 1.0


def sightlines_dir(root=DEFAULT_STORE) -> Path:
    return Path(root) / "sightlines"


def map_key(map_name: str) -> str:
    """The table's key for a map display name or a `/Game/Maps/<Code>/<Code>`
    path, through valorant-api's map list in the store."""
    s = str(map_name)
    if s.startswith("/Game/"):
        return _codename_keys().get(s, s.rsplit("/", 1)[-1].lower())
    return s.strip().lower()


@lru_cache(maxsize=1)
def _codename_keys(root=DEFAULT_STORE) -> dict:
    p = Path(root) / "external" / "valorant-api" / "maps.json"
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))["data"]
    return {m["mapUrl"]: m["displayName"].strip().lower() for m in data if m.get("mapUrl")}


def sightline_table(map_name: str, root=DEFAULT_STORE) -> Path | None:
    """The table that stands for the map, by `choice.json`; None without one."""
    key = map_key(map_name)
    d = sightlines_dir(root)
    cp = d / "choice.json"
    if not cp.is_file():
        return None
    entry = (json.loads(cp.read_text(encoding="utf-8")).get("maps") or {}).get(key)
    if not entry or not entry.get("has_3d"):
        return None
    p = d / f"{key}__{entry['table_version']}.npz"
    return p if p.is_file() else None


class Occluders:
    """The Weapon-blocking triangles of one map, ready to cast segments."""

    def __init__(self, map_name: str, root=DEFAULT_STORE, tris: np.ndarray | None = None):
        from embreex import mesh_construction, rtcore_scene

        self.map = map_key(map_name)
        if tris is None:
            path = sightline_table(map_name, root)
            if path is None:
                raise FileNotFoundError(f"no 3D sightline table for map {map_name!r}")
            with np.load(path, allow_pickle=False) as z:
                tris = z["tris"][z["weapon"]]
                prov = json.loads(str(z["provenance"]))
            self.table = path.name
            self.table_version = prov.get("version")
        else:
            self.table, self.table_version = "synthetic", None
        self.tris = np.ascontiguousarray(tris, np.float32)
        self.scene = rtcore_scene.EmbreeScene()
        mesh_construction.TriangleMesh(self.scene, self.tris)

    def provenance(self) -> dict:
        return {"owner": "line-of-sight", "version": LINE_OF_SIGHT_VERSION,
                "map": self.map, "table": self.table, "table_version": self.table_version,
                "n_tris": int(len(self.tris))}

    def first_hit(self, o: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(triangle index, distance) of the first crossing along each ray
        (origins `o`, unit directions `d`); index -1 where none."""
        r = self.scene.run(np.ascontiguousarray(o, np.float32), np.ascontiguousarray(d, np.float32), output=1)
        return r["primID"].astype(np.int64), r["tfar"].astype(np.float64)

    def blocked(self, a: np.ndarray, b: np.ndarray, chunk: int = 1_000_000) -> np.ndarray:
        """True where the segment a -> b (rows of xyz, cm) crosses a triangle.
        A non-finite endpoint gives False; ask `finite` first."""
        a = np.asarray(a, np.float64).reshape(-1, 3)
        b = np.asarray(b, np.float64).reshape(-1, 3)
        out = np.zeros(len(a), bool)
        ok = np.isfinite(a).all(1) & np.isfinite(b).all(1)
        idx = np.flatnonzero(ok)
        for s in range(0, len(idx), chunk):
            k = idx[s:s + chunk]
            d = b[k] - a[k]
            L = np.linalg.norm(d, axis=1)
            u = d / np.maximum(L, 1e-9)[:, None]
            r = self.scene.run(a[k].astype(np.float32), u.astype(np.float32),
                               dists=np.maximum(L - END_SLACK_CM, 0.0).astype(np.float32),
                               query="OCCLUDED")
            out[k] = np.asarray(r) != -1
        return out


def eye(centre: np.ndarray) -> np.ndarray:
    """The standing eye above actor locations (rows of xyz, cm)."""
    c = np.array(centre, np.float64, copy=True)
    c[..., 2] += EYE_ABOVE_CENTRE_CM
    return c
