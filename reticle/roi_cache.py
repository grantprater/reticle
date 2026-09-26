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

**A 15 Hz set is stored as video, not PNG.** PNG compresses each frame alone,
so 15 Hz minimap crops over the corpus's live rounds measured about as large
as the corpus itself. FFV1 in `bgr0` through `ffmpeg` (`CODECS`) is lossless
-- 147 of 147 frames read back bit for bit through OpenCV, seeks included --
at a third of PNG's size; lossless x264 was larger, since the minimap changes
too much between frames for prediction to pay. Every FFV1 frame is a key
frame, so a seek lands on the frame asked for.
"""
from __future__ import annotations

import json
import shutil
import subprocess
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
    # The minimap and the ability tray at the minimap rate, written over each
    # round from just before its barrier drop (`spans`): what was placed in the
    # buy phase is still drawn then [domain:rounds/buy-phase-barriers].
    "minimap": ("minimap", "hud_abilities"),
}

#: How each set's crops are stored: "png" per crop, or "ffv1" video per rect.
CODECS = {"minimap": "ffv1"}


def ffmpeg_path() -> str:
    """The ffmpeg executable: on PATH, or where winget installs it."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import os
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    for p in sorted(base.glob("**/ffmpeg.exe")):
        return str(p)
    raise SystemExit("ffmpeg not found: install it (winget install Gyan.FFmpeg)")


def roi_rects(name: str, profile, wh: tuple[int, int]) -> list[list[int]]:
    """The pixel rectangles (x0, y0, x1, y1) of a cache set, in set order."""
    if name not in CACHE_SETS:
        raise ValueError(f"no cacheable ROI set named {name!r}; have {sorted(CACHE_SETS)}")
    by = {r.name: r for r in profile.rois}
    missing = [r for r in CACHE_SETS[name] if r not in by]
    if missing:
        raise ValueError(f"profile {profile.name} lacks ROIs {missing} for set {name!r}")
    return [[int(v) for v in by[r].pixels(*wh)] for r in CACHE_SETS[name]]


def covers(held, wanted) -> bool:
    """Whether cached `held` spans contain every `wanted` span; `wanted` None
    is the whole capture, which only an unbounded cache holds."""
    if wanted is None:
        return False
    return all(any(a <= s and e <= b for a, b in held) for s, e in wanted)


def clip_spans(wanted, held) -> list[tuple[float, float]]:
    """`wanted` spans cut to what `held` spans contain; `wanted` None is the
    whole capture, so the result is `held` itself."""
    if wanted is None:
        return [(float(a), float(b)) for a, b in held]
    out = []
    for s, e in wanted:
        for a, b in held:
            lo, hi = max(s, a), min(e, b)
            if lo < hi:
                out.append((float(lo), float(hi)))
    return sorted(out)


def cache_dir(store_root: Path, name: str) -> Path:
    return Path(store_root) / "roi_cache" / name / ROI_CACHE_VERSION


def _cache_record(manifest: dict, profile, name: str, rects, hz: float, spans=None) -> dict:
    return {"version": ROI_CACHE_VERSION, "roi": name, "rects": [list(r) for r in rects],
            "hz": hz, "spans": None if spans is None else [[float(a), float(b)] for a, b in spans],
            "codec": CODECS.get(name, "png"), "session_id": manifest["session_id"], "profile": profile.name,
            "content_key": manifest["source"].get("content_key"),
            "wh": [int(manifest["source"]["width"]), int(manifest["source"]["height"])]}


def cache_for(store_root: Path, manifest: dict, profile, readers) -> tuple["RoiCache | None", str]:
    """The cache that can feed this whole pass, or None and why it cannot.

    A pass is fed from the cache only when EVERY reader declares a
    `cache_set` (its reads stay inside those ROIs), wants frames the cache
    holds at the rate it was written, and one stored cache holds the union of
    their ROIs. A cache written over `spans` feeds a reader only inside them:
    one wanting the whole capture, or time outside, needs a decode. One reader
    outside that makes it a decode: a pass is fed from one source.
    """
    need: set[str] = set()
    for r in readers:
        s = getattr(r, "cache_set", None)
        if s is None:
            return None, f"{r.name} reads outside any cached ROI set"
        need |= set(CACHE_SETS[s])
    names = [n for n, rs in CACHE_SETS.items() if need <= set(rs)]
    if not names:
        return None, f"no cached set holds {sorted(need)}"
    why = "no_cache"
    for name in sorted(names, key=lambda n: len(CACHE_SETS[n])):
        cache, reason = RoiCache.load(store_root, manifest, profile, name)
        if cache is None:
            why = reason or why
            continue
        bad = [r.name for r in readers if float(r.hz) != float(cache.record["hz"])]
        if bad:
            return None, f"{', '.join(bad)} at another rate than the cache's {cache.record['hz']} Hz"
        held = cache.record.get("spans")
        if held is None:
            # A whole-capture cache samples on one stride from the start; a
            # decode over spans restarts it at each span, on other frames.
            out = [r.name for r in readers if getattr(r, "spans", None) is not None]
            if out:
                return None, f"{', '.join(out)} reads spans, and the cache holds the whole capture"
        else:
            out = [r.name for r in readers if not covers(held, getattr(r, "spans", None))]
            if out:
                return None, f"{', '.join(out)} reads outside the cache's spans"
        return cache, f"{cache.record['roi']} cache ({cache.record['version']})"
    return None, why


class RoiCacheWriter:
    """A reader that joins a decode pass and stores a set's crops."""

    def __init__(self, store_root: Path, manifest: dict, profile, name: str = "killfeed",
                 hz: float = 2.0, spans=None):
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        self.rects = roi_rects(name, profile, wh)
        self.record = _cache_record(manifest, profile, name, self.rects, hz, spans)
        self.name = f"roi_cache:{name}"
        self.hz, self.spans = hz, spans
        d = cache_dir(store_root, name)
        d.mkdir(parents=True, exist_ok=True)
        sid = manifest["session_id"]
        self.codec = self.record["codec"]
        self.paths = (d / f"{sid}.bin", d / f"{sid}.idx.npy", d / f"{sid}.json")
        # One row per frame per rectangle: t_ms, frame_idx, rect, offset, length;
        # for video, offset is the frame's number in its rect's file.
        self._index: list[tuple[float, int, int, int, int]] = []
        self._offset = 0
        if self.codec == "ffv1":
            ff = ffmpeg_path()
            self.videos = [d / f"{sid}.r{k}.mkv" for k in range(len(self.rects))]
            self._procs = []
            for (x0, y0, x1, y1), path in zip(self.rects, self.videos):
                part = path.with_suffix(".part.mkv")
                self._procs.append(subprocess.Popen(
                    [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                     "-s", f"{x1 - x0}x{y1 - y0}", "-r", str(hz), "-i", "-",
                     "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0", str(part)],
                    stdin=subprocess.PIPE))
            self._count = 0
        else:
            self._part = self.paths[0].with_suffix(".bin.part")
            self._fh = open(self._part, "wb")

    def feed(self, smp) -> None:
        if self.codec == "ffv1":
            for k, ((x0, y0, x1, y1), proc) in enumerate(zip(self.rects, self._procs)):
                proc.stdin.write(np.ascontiguousarray(smp.frame[y0:y1, x0:x1]).tobytes())
                self._index.append((float(smp.t_ms), int(smp.frame_idx), k, self._count, 0))
            self._count += 1
            return
        for k, (x0, y0, x1, y1) in enumerate(self.rects):
            ok, png = cv2.imencode(".png", smp.frame[y0:y1, x0:x1])
            if not ok:
                raise ValueError(f"could not encode the crop at {smp.t_ms} ms")
            b = png.tobytes()
            self._fh.write(b)
            self._index.append((float(smp.t_ms), int(smp.frame_idx), k, self._offset, len(b)))
            self._offset += len(b)

    def finish(self) -> None:
        if self.codec == "ffv1":
            for proc, path in zip(self._procs, self.videos):
                proc.stdin.close()
                if proc.wait() != 0:
                    raise RuntimeError(f"ffmpeg failed writing {path}")
                path.with_suffix(".part.mkv").replace(path)
            self._offset = sum(p.stat().st_size for p in self.videos)
        else:
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

    def samples(self, targets_ms: list[float], rois=None):
        """A Sample per target the cache holds, in target order: the stored
        crops pasted into a black frame of the capture's size. `rois` names
        the profile ROIs to decode (a cache set's, or a list); the rest stay
        black, so a killfeed reader on a `hud` cache decodes one crop, not all."""
        if isinstance(rois, str):
            rois = CACHE_SETS[rois]
        held = CACHE_SETS[self.record["roi"]]
        keep = (set(range(len(held))) if rois is None
                else {held.index(r) for r in rois if r in held})
        if not hasattr(self, "_by_t"):
            self._by_t: dict[float, list[int]] = {}
            for i, t in enumerate(self.t_ms):
                self._by_t.setdefault(float(t), []).append(i)
        w, h = self.record["wh"]
        if self.record.get("codec") == "ffv1":
            yield from self._video_samples(targets_ms, keep, w, h)
            return
        with open(self.blob, "rb") as fh:
            for t in targets_ms:
                got = [i for i in self._by_t.get(float(t), ()) if int(self.rect[i]) in keep]
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

    def _video_samples(self, targets_ms, keep, w, h):
        """`samples` for an FFV1 cache: one capture per rect, read in order,
        seeking only when a target skips frames."""
        caps, pos = {}, {}
        try:
            for t in targets_ms:
                got = [i for i in self._by_t.get(float(t), ()) if int(self.rect[i]) in keep]
                if not got:
                    continue
                frame = np.zeros((h, w, 3), np.uint8)
                for i in got:
                    k, n = int(self.rect[i]), int(self.offset[i])
                    if k not in caps:
                        caps[k] = cv2.VideoCapture(str(self.blob.with_name(
                            self.blob.name.replace(".bin", f".r{k}.mkv"))))
                        pos[k] = 0
                    if pos[k] != n:
                        caps[k].set(cv2.CAP_PROP_POS_FRAMES, n)
                    ok, crop = caps[k].read()
                    if not ok:
                        raise ValueError(f"cache video ended before frame {n} (rect {k})")
                    pos[k] = n + 1
                    x0, y0, x1, y1 = self.record["rects"][k]
                    frame[y0:y1, x0:x1] = crop
                yield Sample(frame_idx=int(self.frame_idx[got[0]]), t_ms=float(t), frame=frame)
        finally:
            for c in caps.values():
                c.release()
