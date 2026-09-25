r"""Find the killer portrait's right edge by texture, in any script.

    .\.venv\Scripts\python.exe prototypes\portrait_texture_edge.py score
    .\.venv\Scripts\python.exe prototypes\portrait_texture_edge.py show SESSION T_MS SLOT

The player's observation (2026-09-25): the portrait is visually messy and
face-like, while the rest of the banner is near-monochrome or smoothly
varying. `killfeed.killer_name_start` instead walks left over glyph-sized
white blobs, which assumes Latin letter shapes: the two bars of a Japanese
"ニ" are too short to be glyphs, flame art merges into "Ph", an earring reads
as a letter.

Here each entry's plate colour is estimated per row from the killer name's
own columns (the median of their non-white pixels), and every pixel is scored
by its distance from the segment between that plate colour and white -- the
colours a white glyph antialiased onto the plate can take. A column's score is
the share of its pixels farther than `FAR` from the segment. Walking left from
the killer's name run, the portrait's right edge is the first column that
starts `RUN` consecutive columns scoring above `EDGE`.

`score` measures the edge on the player's uniform killer labels
(`label_feed_portraits.py --uniform`) against a fit of the labelled agent's
reference portrait (`analysis/feed_portrait_uniform_fit.json`), beside the
current crop. It reads only the killfeed crops from the `hud` ROI cache.
Predictions are `portrait-texture-edge` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import killfeed as kf  # noqa: E402
from reticle.passes import SessionContext  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

FAR = 40.0     # BGR distance from the plate-white segment that is art, not text
EDGE = 0.25    # a column with this share of art pixels is portrait
RUN = 3        # consecutive portrait columns that make the edge


def art_share(band: np.ndarray, run: tuple[int, int]) -> np.ndarray:
    """Per column of `band`: the share of pixels off the plate-white segment,
    with the plate colour taken per row from the name run's columns."""
    b = band.astype(np.float32)
    name = b[:, run[0]:run[1] + 1]
    white = np.array([255.0, 255.0, 255.0], np.float32)
    lum = name.mean(axis=2)
    plate = np.empty((b.shape[0], 3), np.float32)
    for r in range(b.shape[0]):
        keep = lum[r] < 200
        plate[r] = np.median(name[r][keep], axis=0) if keep.any() else np.median(name[r], axis=0)
    d = white[None, :] - plate                      # per row: plate -> white
    rel = b - plate[:, None, :]
    t = np.clip((rel * d[:, None, :]).sum(2) / np.maximum((d * d).sum(1), 1e-6)[:, None], 0, 1)
    off = np.linalg.norm(rel - t[:, :, None] * d[:, None, :], axis=2)
    return (off > FAR).mean(axis=0)


def texture_edge(band: np.ndarray, run: tuple[int, int]) -> int | None:
    """The column just right of the portrait: the killer crop's right edge."""
    share = art_share(band, run)
    for x in range(run[0] - 1, RUN - 2, -1):
        if all(share[x - k] > EDGE for k in range(RUN)):
            return x + 1
    return None


def _items():
    store = Store()
    root = store.root
    meta = json.loads(str(np.load(root / "analysis" / "feed_portrait_uniform_labels.npz")["meta"]))
    fit = {r[0]: r for r in json.load(open(root / "analysis" / "feed_portrait_uniform_fit.json"))}
    return store, meta, fit


def _band(store, sid, t_ms, slot, cache_by={}):
    if sid not in cache_by:
        man = store.read_manifest(sid)
        prof = get_profile(man["source_profile"])
        ctx = SessionContext(store=store, manifest=man, profile=prof)
        reader = kf.KillfeedPortraitReader(prof, ctx.wh, mask=ctx.kf_mask(), hz=2.0, spans=None)
        cache, _ = RoiCache.load(store.root, man, prof, "killfeed")
        cache_by[sid] = (reader, cache, prof)
    reader, cache, prof = cache_by[sid]
    smp = next(iter(cache.samples([float(t_ms)], rois="killfeed")), None)
    if smp is None:
        return None
    views = kf.analyse_killfeed(smp.frame, reader.roi, reader.w, reader.h, reader.mask, prof.name)
    x0, y0, x1, y1 = reader.roi.pixels(reader.w, reader.h)
    crop = smp.frame[y0:y1, x0:x1]
    obs = kf.portrait_observations(smp.frame, reader.roi, reader.w, reader.h, views=views,
                                   mask=reader.mask, profile_name=prof.name)
    view = next((v for v in views if v.slot == slot and v.killer_run), None)
    now = next((o for o in obs if o["slot"] == slot and o["role"] == "killer" and "x1" in o), None)
    if view is None:
        return None
    return crop[view.y0:view.y1], view, now


def score() -> dict:
    store, meta, fit = _items()
    res, rows = Counter(), []
    for i, m in enumerate(meta):
        if i not in fit:
            continue
        slot = int(m["observation_key"].split(":")[2])
        got = _band(store, m["session_id"], m["t_ms"], slot)
        if got is None:
            res["no_view"] += 1
            continue
        band, view, now = got
        edge = texture_edge(band, view.killer_run)
        x0, _, x1, _ = m["ring"]
        _, _, _, match, fx, _fy, sc = fit[i]
        truth = (x0 + x1) / 2 + fx + 34 * sc          # the fitted face's right edge
        cur = now["x1"] if now else None
        rows.append((i, fit[i][1], round(truth), edge, cur, round(match, 2)))
        for name, x in (("texture", edge), ("current", cur)):
            if x is None:
                res[f"{name}_none"] += 1
            elif abs(x - truth) <= 3:
                res[f"{name}_within3"] += 1
            else:
                res[f"{name}_off"] += 1
    off = [r for r in rows if r[3] is None or abs(r[3] - r[2]) > 3 or r[4] is None or abs(r[4] - r[2]) > 3]
    return {"items": len(rows), **res, "off (item, agent, fit edge, texture, current, fit score)": off}


def show(sid: str, t_ms: float, slot: int) -> None:
    store = Store()
    band, view, now = _band(store, sid, t_ms, slot)
    share = art_share(band, view.killer_run)
    print("killer run", view.killer_run, "texture edge", texture_edge(band, view.killer_run),
          "current crop right", now and now["x1"])
    lo = max(0, (now["x1"] if now else view.killer_run[0]) - 30)
    print(" ".join(f"{x}:{share[x]:.2f}" for x in range(lo, view.killer_run[0] + 5)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["score", "show"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.cmd == "score":
        print(json.dumps(score(), indent=1))
    else:
        show(a.args[0], float(a.args[1]), int(a.args[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
