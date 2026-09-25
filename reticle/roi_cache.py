"""Lossless crops of one fixed HUD region, stored so a reader can rerun without
decoding the capture.

A reader whose every pixel read falls inside a declared ROI (the killfeed
reader inside `killfeed_roi`) can be fed from these crops: `RoiCache.sample`
pastes the stored crop into a black frame of the capture's size, so the reader
runs unchanged and sees the same pixels inside its ROI. What it reads outside
the ROI is black, which is why the check is equality of the reader's output
against a decoded run, not the assumption that it stays inside.

The player's decision (2026-09-25): a crop of a known reader ROI is not a copy
of the raw media; the rule against copying is about duplicating the capture.

The cache is keyed by session, ROI name and `ROI_CACHE_VERSION`, and records
the source content key, profile and ROI rectangle; `RoiCache.load` refuses a
cache whose record disagrees with the session now. Crops are PNG, so the
pixels are the decoder's, bit for bit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .decode import Sample

ROI_CACHE_VERSION = "roi-cache-0.1.0"


def roi_rect(name: str, profile, wh: tuple[int, int]) -> tuple[int, int, int, int]:
    """The pixel rectangle (x0, y0, x1, y1) of a cacheable ROI."""
    if name == "killfeed":
        from .killfeed import killfeed_roi
        roi = killfeed_roi(profile)
        if roi is None:
            raise ValueError(f"profile {profile.name} has no killfeed ROI")
        return tuple(int(v) for v in roi.pixels(*wh))
    raise ValueError(f"no cacheable ROI named {name!r}")


def cache_dir(store_root: Path, name: str) -> Path:
    return Path(store_root) / "roi_cache" / name / ROI_CACHE_VERSION


def _cache_record(manifest: dict, profile, name: str, rect, hz: float) -> dict:
    return {"version": ROI_CACHE_VERSION, "roi": name, "rect": list(rect), "hz": hz,
            "session_id": manifest["session_id"], "profile": profile.name,
            "content_key": manifest["source"].get("content_key"),
            "wh": [int(manifest["source"]["width"]), int(manifest["source"]["height"])]}


class RoiCacheWriter:
    """A reader that joins a decode pass and stores its ROI's crops."""

    def __init__(self, store_root: Path, manifest: dict, profile, name: str = "killfeed",
                 hz: float = 2.0, spans=None):
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        self.rect = roi_rect(name, profile, wh)
        self.record = _cache_record(manifest, profile, name, self.rect, hz)
        self.name = f"roi_cache:{name}"
        self.hz, self.spans = hz, spans
        d = cache_dir(store_root, name)
        d.mkdir(parents=True, exist_ok=True)
        sid = manifest["session_id"]
        self.paths = (d / f"{sid}.bin", d / f"{sid}.idx.npy", d / f"{sid}.json")
        self._part = self.paths[0].with_suffix(".bin.part")
        self._fh = open(self._part, "wb")
        self._index: list[tuple[float, int, int, int]] = []
        self._offset = 0

    def feed(self, smp) -> None:
        x0, y0, x1, y1 = self.rect
        ok, png = cv2.imencode(".png", smp.frame[y0:y1, x0:x1])
        if not ok:
            raise ValueError(f"could not encode the crop at {smp.t_ms} ms")
        b = png.tobytes()
        self._fh.write(b)
        self._index.append((float(smp.t_ms), int(smp.frame_idx), self._offset, len(b)))
        self._offset += len(b)

    def finish(self) -> None:
        self._fh.close()
        self._part.replace(self.paths[0])
        np.save(self.paths[1], np.array(self._index, dtype=np.float64).reshape(-1, 4))
        self.paths[2].write_text(json.dumps({**self.record, "frames": len(self._index),
                                             "bytes": self._offset}, indent=1),
                                 encoding="utf-8")


@dataclass
class RoiCache:
    """A stored cache, checked against the session it claims to hold."""

    record: dict
    t_ms: np.ndarray
    frame_idx: np.ndarray
    offset: np.ndarray
    length: np.ndarray
    blob: Path

    @classmethod
    def load(cls, store_root: Path, manifest: dict, profile,
             name: str = "killfeed") -> tuple["RoiCache | None", str | None]:
        """The cache, or None with the reason it cannot be used."""
        d = cache_dir(store_root, name)
        sid = manifest["session_id"]
        meta = d / f"{sid}.json"
        if not meta.is_file():
            return None, "no_cache"
        rec = json.loads(meta.read_text(encoding="utf-8"))
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        want = _cache_record(manifest, profile, name, roi_rect(name, profile, wh), rec["hz"])
        for key in ("version", "rect", "profile", "content_key", "wh"):
            if rec.get(key) != want[key]:
                return None, f"stale_{key}"
        idx = np.load(d / f"{sid}.idx.npy")
        return cls(rec, idx[:, 0], idx[:, 1].astype(int), idx[:, 2].astype(np.int64),
                   idx[:, 3].astype(np.int64), d / f"{sid}.bin"), None

    def samples(self, targets_ms: list[float]):
        """A Sample per target the cache holds, in target order: the crop
        pasted into a black frame of the capture's size."""
        pos = {float(t): i for i, t in enumerate(self.t_ms)}
        w, h = self.record["wh"]
        x0, y0, x1, y1 = self.record["rect"]
        with open(self.blob, "rb") as fh:
            for t in targets_ms:
                i = pos.get(float(t))
                if i is None:
                    continue
                fh.seek(int(self.offset[i]))
                crop = cv2.imdecode(np.frombuffer(fh.read(int(self.length[i])), np.uint8),
                                    cv2.IMREAD_COLOR)
                frame = np.zeros((h, w, 3), np.uint8)
                frame[y0:y1, x0:x1] = crop
                yield Sample(frame_idx=int(self.frame_idx[i]), t_ms=float(t), frame=frame)
