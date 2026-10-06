"""Which callout region and super-region holds a world point.

[owns:callout-region]

A map's callout volumes are the game's own named playable regions, oriented
boxes exported with each 3D sightline table (`region_inv`, `region_lo`,
`region_hi`, `region_names`; docs/SIGHTLINES_3D_PROBE.md, "Floors"). A point
lies in the smallest volume that holds it, probed `PROBE_CM` above the given
height as the table's builder probes its cells.

Volume names are no label: five maps name them only by number
(`BP_CalloutRegion12`). The boxes of one actor form one region and take the
label of valorant-api's callout points (`regionName`, `superRegionName`: A,
B, C, Mid, Attacker Side, Defender Side) that lie inside any of them, the
majority winning; an actor holding none takes the points over or under its
boxes in plan, and failing those the point nearest its centre in plan. Each
label carries that basis (`inside`, `plan` or `nearest`), so a consumer can
see which labels rest on the weaker rules.
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from .line_of_sight import map_key, sightline_table
from .store import DEFAULT_STORE

MAP_REGIONS_VERSION = "map-regions-0.1.0"
#: Points are tested this far above the given z: a replay's z is the capsule
#: centre, a callout point's z sits at the floor.
PROBE_CM = 50.0
SITES = ("A", "B", "C")


class Regions:
    """One map's callout volumes and their labels."""

    def __init__(self, inv, lo, hi, labels: list[dict], table: str = "synthetic"):
        self.inv = np.asarray(inv, float).reshape(-1, 4, 4)
        self.lo = np.asarray(lo, float).reshape(-1, 3)
        self.hi = np.asarray(hi, float).reshape(-1, 3)
        self.labels = labels
        self.table = table
        fwd = np.linalg.inv(self.inv)[:, :3, :3] if len(self.inv) else np.zeros((0, 3, 3))
        scale = np.linalg.norm(fwd, axis=2)
        self.volume = np.prod(np.abs(self.hi - self.lo) * scale, axis=1)
        self._codes()

    def _codes(self) -> None:
        self.super = np.array([lab.get("super") for lab in self.labels], dtype=object)
        #: The super-region names, and each volume's index into them (-1 none).
        self.super_labels = sorted({x for x in self.super.tolist() if x is not None})
        code = {x: i for i, x in enumerate(self.super_labels)}
        self.super_code = np.array([code.get(x, -1) for x in self.super.tolist()], np.int16)

    @classmethod
    def load(cls, map_name: str, root=DEFAULT_STORE) -> "Regions":
        path = sightline_table(map_name, root)
        if path is None:
            raise FileNotFoundError(f"no sightline table with callout volumes for {map_name!r}")
        with np.load(path, allow_pickle=False) as z:
            inv, lo, hi = z["region_inv"], z["region_lo"], z["region_hi"]
            names = json.loads(str(z["region_names"]))
        reg = cls(inv, lo, hi, [{"volume": n} for n in names], table=path.name)
        reg.labels = label_volumes(reg, api_callouts(map_name, root), names)
        reg._codes()
        return reg

    def volume_of(self, pts: np.ndarray) -> np.ndarray:
        """Index of the smallest volume holding each point (xyz, cm), -1 for
        none or a non-finite point."""
        p = np.asarray(pts, float).reshape(-1, 3)
        out = np.full(len(p), -1, np.int32)
        if len(self.inv) == 0 or len(p) == 0:
            return out
        ok = np.isfinite(p).all(1)
        h = np.column_stack([p[:, 0], p[:, 1], p[:, 2] + PROBE_CM, np.ones(len(p))])
        h[~ok] = 0.0
        loc = np.einsum("nj,kji->kni", h, self.inv)[..., :3]
        inside = ((loc >= self.lo[:, None, :]) & (loc <= self.hi[:, None, :])).all(-1)
        inside &= ok[None, :]
        vol = np.where(inside, self.volume[:, None], np.inf)
        k = np.argmin(vol, axis=0)
        has = np.isfinite(vol[k, np.arange(len(p))])
        out[has] = k[has]
        return out

    def super_of(self, pts: np.ndarray) -> np.ndarray:
        """The super-region label of each point, None outside every volume."""
        k = self.volume_of(pts)
        out = np.full(len(k), None, dtype=object)
        out[k >= 0] = self.super[k[k >= 0]]
        return out

    def super_code_of(self, pts: np.ndarray) -> np.ndarray:
        """Each point's index into `super_labels`, -1 outside every volume."""
        k = self.volume_of(pts)
        out = np.full(len(k), -1, np.int16)
        out[k >= 0] = self.super_code[k[k >= 0]]
        return out

    def provenance(self) -> dict:
        basis = Counter(lab.get("basis") for lab in self.labels)
        return {"owner": "callout-region", "version": MAP_REGIONS_VERSION,
                "table": self.table, "volumes": len(self.labels), "label_basis": dict(basis)}


def api_callouts(map_name: str, root=DEFAULT_STORE) -> list[dict]:
    """valorant-api's callout points for the map (game units)."""
    return list(_api_callouts(map_key(map_name), str(root)))


@lru_cache(maxsize=32)
def _api_callouts(key: str, root: str) -> tuple:
    p = Path(root) / "external" / "valorant-api" / "maps.json"
    if not p.is_file():
        return ()
    for m in json.loads(p.read_text(encoding="utf-8"))["data"]:
        if (m.get("displayName") or "").strip().lower() == key:
            return tuple(c for c in (m.get("callouts") or []) if c.get("location"))
    return ()


def _centre_xy(reg: Regions, k: int) -> np.ndarray:
    c = np.append((reg.lo[k] + reg.hi[k]) / 2.0, 1.0) @ np.linalg.inv(reg.inv[k])
    return c[:2]


def label_volumes(reg: Regions, callouts: list[dict], names: list[str]) -> list[dict]:
    """Each volume's (region, super) label from the callout points inside it.

    The boxes of one actor (one name) are one callout region, so their
    points vote together; an actor holding no point takes the label of the
    point nearest its boxes' centre in plan. Grouping by actor uses the name
    as an identifier only, never as a label."""
    labels = [{"volume": n, "region": None, "super": None, "basis": "no_callouts"} for n in names]
    if not callouts or len(names) == 0:
        return labels
    pts = np.array([[c["location"]["x"], c["location"]["y"], c["location"]["z"]] for c in callouts])
    k = reg.volume_of(pts)
    votes: dict[str, Counter] = {}
    near: dict[tuple, float] = {}
    for kk, c, p in zip(k.tolist(), callouts, pts):
        if kk >= 0:
            lab = (c.get("regionName"), c.get("superRegionName"))
            votes.setdefault(names[kk], Counter())[lab] += 1
            near[(names[kk], lab)] = min(near.get((names[kk], lab), np.inf),
                                         float(np.hypot(*(p[:2] - _centre_xy(reg, kk)))))
    fwd = np.linalg.inv(reg.inv)
    centre_local = np.column_stack([(reg.lo + reg.hi) / 2.0, np.ones(len(reg.lo))])
    centre = np.einsum("kj,kji->ki", centre_local, fwd)[:, :3]
    # In plan: a point over or under an actor's boxes (the box's own x and y).
    h = np.column_stack([pts, np.ones(len(pts))])
    loc = np.einsum("nj,kji->kni", h, reg.inv)[..., :2]
    over = ((loc >= reg.lo[:, None, :2]) & (loc <= reg.hi[:, None, :2])).all(-1)   # (K, N)
    for name in dict.fromkeys(names):
        idx = [i for i, n in enumerate(names) if n == name]
        plan = Counter((callouts[j].get("regionName"), callouts[j].get("superRegionName"))
                       for j in np.flatnonzero(over[idx].any(0)))
        if name in votes:
            # The most points win; a tie goes to the label whose point lies
            # nearest the volume's centre in plan.
            top = max(votes[name].values())
            region, sup = min((lab for lab, n in votes[name].items() if n == top),
                              key=lambda lab: near[(name, lab)])
            lab = {"region": region, "super": sup, "basis": "inside",
                   "points": sum(votes[name].values())}
        elif plan:
            (region, sup), _n = plan.most_common(1)[0]
            lab = {"region": region, "super": sup, "basis": "plan", "points": sum(plan.values())}
        else:
            c = centre[idx].mean(0)
            j = int(np.argmin(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])))
            lab = {"region": callouts[j].get("regionName"),
                   "super": callouts[j].get("superRegionName"), "basis": "nearest"}
        for i in idx:
            labels[i].update(lab)
    return labels


def spawn_points(map_name: str, root=DEFAULT_STORE) -> dict[str, np.ndarray]:
    """valorant-api's `Spawn` callout point of each side, keyed `attack` and
    `defence`; a side without one is left out."""
    side = {"Attacker Side": "attack", "Defender Side": "defence"}
    out = {}
    for c in api_callouts(map_name, root):
        s = side.get(c.get("superRegionName"))
        if s and c.get("regionName") == "Spawn":
            loc = c["location"]
            out[s] = np.array([loc["x"], loc["y"]], float)
    return out
