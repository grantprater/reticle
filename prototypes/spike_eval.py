r"""Score the spike refusal (`reticle.spike.on_glyph`) on the player's labels.

    .\.venv\Scripts\python.exe prototypes\spike_eval.py

Three label sets, each a fit position the player judged, read from the
lossless minimap crop cache (no decode):

* `labels/self_fit/c40d950031bb.jsonl` -- self fits: local_player, spike,
  coincident, teammate, nothing;
* `labels/self_facing_lotus_20260928.jsonl` -- self fits on Lotus and
  controls: facing, not_self, cant_tell;
* `labels/unnamed_piece/*.jsonl` -- ally pieces the arbiter could not name,
  placed through the stored `ally_icon` event their observation key names.

For each item it fits the spike glyphs on that frame (`spike.glyph_fits`,
over the baked slab) and asks whether the labelled fit lands on one. It
prints refused/kept per answer. The last row for a key wins. Measured
2026-09-28 in the spike-reader handoff; the reader itself is `reticle/spike.py`.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import geometry, spike  # noqa: E402
from reticle.minimap import (ally_icons, floor_mask, self_icons, slab_mask,  # noqa: E402
                             widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
LABELS = STORE.root / "labels"
#: A labelled instant farther than this from every cached frame is skipped as
#: `no_crop`. The self-fit labels were cut from the capture, and the cache
#: holds only round spans: 45 of 200 c40d950031bb labels fall outside it, and
#: the nearest cached frame is then another moment (up to 37 s away).
MAX_GAP_MS = 70.0


def _last(path: Path, key: str = "key") -> list[dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r[key]] = r
    return list(rows.values())


class Frames:
    """Minimap crops and slabs, one session open at a time."""

    def __init__(self):
        self.sid = None

    def get(self, sid: str, t_ms: float):
        if sid != self.sid:
            man = STORE.read_manifest(sid)
            self.cache, _ = RoiCache.load(STORE.root, man, get_profile(man["source_profile"]),
                                          "minimap")
            med = geometry.reference_static(sid, STORE.root)
            sd = geometry.stability(sid, STORE.root, med.shape[:2])
            self.slab, self.floor, self.static = slab_mask(med, sd=sd), floor_mask(med, sd=sd), med
            self.t = np.unique(np.asarray(self.cache.t_ms, float))
            self.sid = sid
        t = float(self.t[np.argmin(np.abs(self.t - t_ms))])
        if abs(t - t_ms) > MAX_GAP_MS:
            return None
        smp = next(iter(self.cache.samples([t], rois=["minimap"])))
        x0, y0, x1, y1 = self.cache.rect_of("minimap")
        return smp.frame[y0:y1, x0:x1]


def items():
    for r in _last(LABELS / "self_fit" / "c40d950031bb.jsonl"):
        yield "self_fit", "c40d950031bb", r["t_ms"], r["x"], r["y"], r["answer"]
    for r in _last(LABELS / "self_facing_lotus_20260928.jsonl"):
        yield "self_facing", r["session"], r["t_ms"], r["ring_x"], r["ring_y"], r["answer"]
    for path in sorted((LABELS / "unnamed_piece").glob("*.jsonl")):
        sid = path.stem
        ev = {e["observation_key"]: e for e in STORE.read_events("ally_icon", sid)
              if e.get("kind") == "icon"}
        for r in _last(path):
            e = ev.get(r["observation_key"])
            if e is not None:
                yield "unnamed_piece", sid, float(e["t_ms"]), e["cx"], e["cy"], r["class"]


def refused(crop, frames, x, y):
    """The glyph the labelled fit lands on, or None. The frame's current self
    and ally fits stand in for the icons a carried glyph may belong to."""
    fl = frames.floor
    icons = (self_icons(crop, fl, require_facing=False, support=frames.slab)
             + ally_icons(crop, fl, support=frames.slab, static=frames.static))
    return spike.on_glyph(x, y, spike.glyph_fits(crop, frames.slab),
                          widget_scale(crop.shape[1]), icons)


def main() -> int:
    frames = Frames()
    out = collections.defaultdict(collections.Counter)
    for src, sid, t, x, y, answer in sorted(items(), key=lambda i: i[1]):
        crop = frames.get(sid, t)
        if crop is None or crop.shape[:2] != frames.slab.shape:
            out[(src, answer)]["no_crop"] += 1
            continue
        g = refused(crop, frames, x, y)
        out[(src, answer)]["refused" if g else "kept"] += 1
    for (src, answer), c in sorted(out.items()):
        print(f"{src:14s} {answer:16s} refused {c['refused']:3d}  kept {c['kept']:3d}"
              + (f"  no crop {c['no_crop']}" if c["no_crop"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
