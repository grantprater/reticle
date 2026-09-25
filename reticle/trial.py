"""Rerun one reader on part of a session and diff it against the stored streams.

A reader change is checked where it can matter, not over the whole capture:

* the frames are the stored HUD timeline's own timestamps, so every row the
  trial writes has a stored counterpart to compare with;
* `windows="occupied"` keeps only frames within `pad_ms` of a frame whose
  stored killfeed mask holds an entry; `"all"` keeps the whole timeline;
* `source="video"` seeks to each run of frames (`decode.seek_at`) instead of
  decoding from the file start; `source="cache"` reads the ROI crops
  (`roi_cache`) and decodes nothing.

A trial writes nothing to the store. It is a test tier, not a scan: the
occupied windows come from the stored reader's own output, so a change that
finds entries where the old reader saw none can only show up in a full scan,
which stays the acceptance run. Returns the rows and their diff.
"""
from __future__ import annotations

import json
import time

import numpy as np

TRIAL_READERS = {
    # reader name -> (the ROI its reads stay inside, the streams it writes)
    "killfeed": ("killfeed", ("killfeed_portrait", "killfeed_weapon")),
}


def _killfeed_reader(ctx):
    from .killfeed import KillfeedPortraitReader
    return KillfeedPortraitReader(ctx.profile, ctx.wh, mask=ctx.kf_mask(), hz=2.0, spans=None)


def _killfeed_rows(reader, sid: str) -> dict[str, list[dict]]:
    return {"killfeed_portrait": reader.events(sid), "killfeed_weapon": reader.weapon_events(sid)}


def targets(hud: dict, windows: str = "occupied", pad_ms: float = 2000.0) -> list[float]:
    """Timestamps of the stored HUD timeline the trial reads."""
    t = np.asarray(hud["t_ms"], dtype=float)
    if windows == "all":
        return t.tolist()
    if windows != "occupied":
        raise ValueError(f"unknown windows {windows!r}")
    occ = t[np.asarray([bool(m) for m in hud["kf_entry_mask"]])]
    if not len(occ):
        return []
    j = np.searchsorted(occ, t)
    near = np.minimum(np.abs(t - occ[np.clip(j, 0, len(occ) - 1)]),
                      np.abs(t - occ[np.clip(j - 1, 0, len(occ) - 1)]))
    return t[near <= pad_ms].tolist()


def _key(row: dict) -> str:
    return json.dumps(row, sort_keys=True)


def diff(new: list[dict], stored: list[dict], at: set[float]) -> dict:
    """Observation rows (coverage rows aside) compared at the trial's frames."""
    obs = lambda rows: [r for r in rows if r.get("kind") not in ("coverage", "summary")
                        and "t_ms" in r]
    a = [_key(r) for r in obs(new)]
    b = [_key(r) for r in obs(stored) if float(r["t_ms"]) in at]
    sa, sb = set(a), set(b)
    outside = sum(float(r["t_ms"]) not in at for r in obs(stored))
    return {"trial_rows": len(a), "stored_rows": len(b), "same": len(sa & sb),
            "only_trial": len(sa - sb), "only_stored": len(sb - sa),
            "stored_outside_frames": outside,
            "example_only_trial": sorted(sa - sb)[:2], "example_only_stored": sorted(sb - sa)[:2]}


def run(store, manifest: dict, reader: str = "killfeed", source: str = "video",
        windows: str = "occupied", pad_ms: float = 2000.0) -> dict:
    from .decode import seek_at
    from .passes import SessionContext
    from .profiles import get_profile
    from .roi_cache import RoiCache

    if reader not in TRIAL_READERS:
        raise ValueError(f"no trial for reader {reader!r}; have {sorted(TRIAL_READERS)}")
    roi_name, streams = TRIAL_READERS[reader]
    sid = manifest["session_id"]
    profile = get_profile(manifest["source_profile"])
    ctx = SessionContext(store=store, manifest=manifest, profile=profile)
    hud = store.read_hud(sid, manifest["ingested_at"][:10]).to_pydict()
    want = targets(hud, windows, pad_ms)
    stored_idx = dict(zip(hud["t_ms"], hud["frame_idx"]))
    r = _killfeed_reader(ctx)
    t0 = time.perf_counter()
    if source == "video":
        frames = seek_at(str(ctx.media), want, ctx.fps)
    elif source == "cache":
        cache, why = RoiCache.load(store.root, manifest, profile, roi_name)
        if cache is None:
            raise SystemExit(f"{sid}: no usable {roi_name} ROI cache ({why}) -- "
                             f"run `reticle roicache {sid}`")
        frames = cache.samples(want)
    else:
        raise ValueError(f"unknown source {source!r}")
    n = 0
    for smp in frames:
        smp.frame_idx = int(stored_idx.get(smp.t_ms, smp.frame_idx))
        r.feed(smp)
        n += 1
    seconds = time.perf_counter() - t0
    # The store writes plain JSON; compare what it would have written.
    rows = {s: [json.loads(json.dumps(x, separators=(",", ":"), allow_nan=False))
                for x in rs] for s, rs in _killfeed_rows(r, sid).items()}
    at = set(float(t) for t in want)
    diffs = {s: diff(rows[s], store.read_events(s, sid), at) for s in streams}
    return {"session_id": sid, "reader": reader, "source": source, "windows": windows,
            "pad_ms": pad_ms, "timeline": len(hud["t_ms"]), "frames": n,
            "seconds": round(seconds, 1), "diff": diffs, "rows": rows}
