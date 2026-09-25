"""Lossless crops of fixed HUD regions, stored so a reader can rerun without
decoding the capture.

A reader whose every pixel read falls inside a declared set of profile ROIs
(the killfeed reader inside `killfeed`; the HUD reader inside the score line,
bottom HUD and killfeed) can be fed from these crops: `RoiCache.sample`
pastes each stored crop into a black frame of the capture's size, so the
reader runs unchanged and sees the same pixels inside its ROIs. What it reads
outside them is black, which is why the check is equality of the reader's
output against a decoded run, not the assumption that it stays inside.

The player's decision (2026-09-25): a crop of a known reader ROI is not a copy
of the raw media; the rule against copying is about duplicating the capture.

A cache is keyed by session, set name (`CACHE_SETS`) and `ROI_CACHE_VERSION`,
and records the source content key, profile and rectangles; `RoiCache.load`
refuses a cache whose record disagrees with the session now, and serves a set
from any cache whose rectangles include it. Crops are PNG, so the pixels are
the decoder's, bit for bit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .decode import Sample

ROI_CACHE_VERSION = "roi-cache-0.1.0"

#: Named sets of profile ROIs, each the regions one pass's readers read.
CACHE_SETS = {
    "killfeed": ("killfeed",),
    # The HUD pass (`hud_reader.HudReader`), the roster that rides it, and the
    # screen centre. The spike graphic replaces the clock inside `scoreline`.
    "hud": ("scoreline", "hud_hp", "hud_ammo", "killfeed", "hud_roster", "hud_roster_enemy",
            "center"),
}


def roi_rects(name: str, profile, wh: tuple[int, int]) -> list[list[int]]:
    """The pixel rectangles (x0, y0, x1, y1) of a cache set, in set order."""
    if name not in CACHE_SETS:
        raise ValueError(f"no cacheable ROI set named {name!r}; have {sorted(CACHE_SETS)}")
    by = {r.name: r for r in profile.rois}
    missing = [r for r in CACHE_SETS[name] if r not in by]
    if missing:
        raise ValueError(f"profile {profile.name} lacks ROIs {missing} for set {name!r}")
    return [[int(v) for v in by[r].pixels(*wh)] for r in CACHE_SETS[name]]


def cache_dir(store_root: Path, name: str) -> Path:
    return Path(store_root) / "roi_cache" / name / ROI_CACHE_VERSION


def _cache_record(manifest: dict, profile, name: str, rects, hz: float) -> dict:
    return {"version": ROI_CACHE_VERSION, "roi": name, "rects": [list(r) for r in rects],
            "hz": hz, "session_id": manifest["session_id"], "profile": profile.name,
            "content_key": manifest["source"].get("content_key"),
            "wh": [int(manifest["source"]["width"]), int(manifest["source"]["height"])]}


class RoiCacheWriter:
    """A reader that joins a decode pass and stores a set's crops."""

    def __init__(self, store_root: Path, manifest: dict, profile, name: str = "killfeed",
                 hz: float = 2.0, spans=None):
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        self.rects = roi_rects(name, profile, wh)
        self.record = _cache_record(manifest, profile, name, self.rects, hz)
        self.name = f"roi_cache:{name}"
        self.hz, self.spans = hz, spans
        d = cache_dir(store_root, name)
        d.mkdir(parents=True, exist_ok=True)
        sid = manifest["session_id"]
        self.paths = (d / f"{sid}.bin", d / f"{sid}.idx.npy", d / f"{sid}.json")
        self._part = self.paths[0].with_suffix(".bin.part")
        self._fh = open(self._part, "wb")
        # One row per frame per rectangle: t_ms, frame_idx, rect, offset, length.
        self._index: list[tuple[float, int, int, int, int]] = []
        self._offset = 0

    def feed(self, smp) -> None:
        for k, (x0, y0, x1, y1) in enumerate(self.rects):
            ok, png = cv2.imencode(".png", smp.frame[y0:y1, x0:x1])
            if not ok:
                raise ValueError(f"could not encode the crop at {smp.t_ms} ms")
            b = png.tobytes()
            self._fh.write(b)
            self._index.append((float(smp.t_ms), int(smp.frame_idx), k, self._offset, len(b)))
            self._offset += len(b)

    def finish(self) -> None:
        self._fh.close()
        self._part.replace(self.paths[0])
        np.save(self.paths[1], np.array(self._index, dtype=np.float64).reshape(-1, 5))
        frames = len({t for t, *_ in self._index})
        self.paths[2].write_text(json.dumps({**self.record, "frames": frames,
                                             "bytes": self._offset}, indent=1),
                                 encoding="utf-8")


@dataclass
class RoiCache:
    """A stored cache, checked against the session it claims to hold."""

    record: dict
    t_ms: np.ndarray
    frame_idx: np.ndarray
    rect: np.ndarray
    offset: np.ndarray
    length: np.ndarray
    blob: Path

    @classmethod
    def _open(cls, d: Path, manifest: dict, profile):
        sid = manifest["session_id"]
        meta = d / f"{sid}.json"
        if not meta.is_file():
            return None, "no_cache"
        rec = json.loads(meta.read_text(encoding="utf-8"))
        if "rects" not in rec:                             # the one-rectangle layout
            rec["rects"] = [rec["rect"]]
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        want = {"version": ROI_CACHE_VERSION, "profile": profile.name,
                "content_key": manifest["source"].get("content_key"), "wh": list(wh)}
        for key, v in want.items():
            if rec.get(key) != v:
                return None, f"stale_{key}"
        if roi_rects(rec["roi"], profile, wh) != rec["rects"]:
            return None, "stale_rects"
        idx = np.load(d / f"{sid}.idx.npy")
        if idx.shape[1] == 4:                              # t, frame, offset, length
            idx = np.insert(idx, 2, 0, axis=1)
        return cls(rec, idx[:, 0], idx[:, 1].astype(int), idx[:, 2].astype(int),
                   idx[:, 3].astype(np.int64), idx[:, 4].astype(np.int64),
                   d / f"{sid}.bin"), None

    @classmethod
    def load(cls, store_root: Path, manifest: dict, profile,
             name: str = "killfeed") -> tuple["RoiCache | None", str | None]:
        """The cache for set `name`, or one whose rectangles include it; or
        None with the reason no cache can be used."""
        need = set(CACHE_SETS[name])
        why = "no_cache"
        for other in [name] + [n for n, rs in CACHE_SETS.items()
                               if n != name and need <= set(rs)]:
            got, reason = cls._open(cache_dir(store_root, other), manifest, profile)
            if got is not None:
                return got, None
            if reason != "no_cache":
                why = reason
        return None, why

    def rect_of(self, roi: str) -> list[int]:
        """The pixel rectangle of one profile ROI this cache holds."""
        return self.record["rects"][CACHE_SETS[self.record["roi"]].index(roi)]

    def samples(self, targets_ms: list[float]):
        """A Sample per target the cache holds, in target order: every stored
        crop pasted into a black frame of the capture's size."""
        rows: dict[float, list[int]] = {}
        for i, t in enumerate(self.t_ms):
            rows.setdefault(float(t), []).append(i)
        w, h = self.record["wh"]
        with open(self.blob, "rb") as fh:
            for t in targets_ms:
                got = rows.get(float(t))
                if not got:
                    continue
                frame = np.zeros((h, w, 3), np.uint8)
                for i in got:
                    fh.seek(int(self.offset[i]))
                    crop = cv2.imdecode(np.frombuffer(fh.read(int(self.length[i])), np.uint8),
                                        cv2.IMREAD_COLOR)
                    x0, y0, x1, y1 = self.record["rects"][int(self.rect[i])]
                    frame[y0:y1, x0:x1] = crop
                yield Sample(frame_idx=int(self.frame_idx[got[0]]), t_ms=float(t), frame=frame)
