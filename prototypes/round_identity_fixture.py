r"""Build the store fixture that `tests/test_round_identity_e2e.py` reads.

    C:/Users/grant/reticle/.venv/Scripts/python.exe prototypes/round_identity_fixture.py a06f04a0059f --round 4
    ... --decode-minimap      # also cut the minimap icon crops (decodes video)

The fixture lives in the store, `<store>/fixtures/round_identity/`, so every
worktree finds it; the repository's `fixtures/` is gitignored and reached only
the primary checkout. It holds lossless crops of fixed reader ROIs, never the
capture (the player, 2026-09-25; `reticle/roi_cache.py`).

`<sid>_r<round>_killfeed.npz` holds killfeed ROI crops read from the `hud` ROI
crop cache, so building it decodes nothing. Which frames: every (time, slot)
view that `death.follow_entry_portraits` binds to each entry that
`death.session_entries` finds in the round, the views `reticle deaths` reads.
The entry's first view is kept: on a06f04a0059f round 4 every victim portrait
is fully drawn at its first 2 Hz sample (notes/pictures/
round_identity_r4_killfeed_a06f04a0059f.png), and those crops equal a fresh
seek-and-decode of the same frames bit for bit. The stored 0.76 clip at
284.5 s is the reader's box landing past Jett's white hair, which it reads as
name text, not a portrait still sliding in; no later view is cleaner
(notes/pictures/round_identity_r4_portrait_boxes_a06f04a0059f.png).

`<sid>_r<round>_minimap.npz` holds the icon crop around each labelled minimap
sighting, cut exactly as `round_identity_eval.extract_crops_for_sightings`
cuts it from video: one seek per distinct label time. Label times fall on the
60 fps capture, not the minimap cache's 15 Hz, so this half decodes, and only
with `--decode-minimap`.

Each file carries `provenance_json`: the inputs' version stamps, the source
content key and the rule above.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle.adjudication.death import (follow_entry_portraits, icon_widths,  # noqa: E402
                                        session_entries)
from reticle.killfeed import KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import ROI_CACHE_VERSION, RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

FIXTURE_SUBDIR = ("fixtures", "round_identity")


def fixture_path(store: Store, session_id: str, round_no: int, kind: str) -> Path:
    """`<store>/fixtures/round_identity/<sid>_r<round>_<kind>.npz`, kind
    `killfeed` or `minimap`."""
    return store.root.joinpath(*FIXTURE_SUBDIR) / f"{session_id}_r{round_no}_{kind}.npz"


def _manifest(store: Store, session_id: str) -> dict:
    return json.loads(store.manifest_path(session_id).read_text(encoding="utf-8"))


def build_killfeed(store: Store, session_id: str, date: str, round_no: int) -> Path:
    """Killfeed ROI crops at every view each round entry occupies; no decode."""
    from prototypes.round_identity_eval import load_round_bounds
    man = _manifest(store, session_id)
    profile = get_profile(man["source_profile"])
    cache, why = RoiCache.load(store.root, man, profile, "killfeed")
    if cache is None:
        raise SystemExit(f"{session_id}: no killfeed ROI cache ({why}); "
                         f"run `reticle scan {session_id} --only roi_cache --cache-roi hud`")
    if store.events_version("killfeed_portrait", session_id) != KILLFEED_PORTRAIT_VERSION:
        raise SystemExit(f"{session_id}: killfeed portraits are not at {KILLFEED_PORTRAIT_VERSION}")
    t0, t1, _ = load_round_bounds(store, session_id, date, round_no)
    hud = store.read_hud(session_id, date).to_pydict()
    portraits = [r for r in store.read_events("killfeed_portrait", session_id)
                 if r.get("kind") == "portrait_observation"]
    weapons = (store.read_events("killfeed_weapon", session_id)
               if store.events_version("killfeed_weapon", session_id) == KILLFEED_WEAPON_VERSION
               else None)
    widths = icon_widths(weapons)
    entries = []
    for e in session_entries(hud):
        if not (t0 <= e["t_first"] <= t1):
            continue
        views = sorted(follow_entry_portraits(e, portraits, widths))
        entries.append({"t_first": e["t_first"], "t_last": e["t_last"], "slot": e["slot"],
                        "side": e["side"], "views": [[float(t), int(s)] for t, s in views]})
    times = sorted({t for e in entries for t, _ in e["views"]})
    x0, y0, x1, y1 = cache.rect_of("killfeed")
    crops, frame_idx, got = [], [], []
    for smp in cache.samples(times, rois=["killfeed"]):
        crops.append(np.ascontiguousarray(smp.frame[y0:y1, x0:x1]))
        frame_idx.append(smp.frame_idx)
        got.append(smp.t_ms)
    missing = sorted(set(times) - set(got))
    if missing:
        raise SystemExit(f"the killfeed cache lacks views at {missing}")
    prov = {
        "builder": "prototypes/round_identity_fixture.py", "kind": "killfeed",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": session_id, "date": date, "round_no": round_no,
        "round_ms": [t0, t1], "content_key": man["source"].get("content_key"),
        "source": f"roi_cache {cache.record['roi']} {ROI_CACHE_VERSION}",
        "killfeed_rect": [x0, y0, x1, y1], "wh": cache.record["wh"],
        "profile": profile.name,
        "views_from": f"death.follow_entry_portraits over killfeed_portrait "
                      f"{KILLFEED_PORTRAIT_VERSION} and killfeed_weapon "
                      f"{KILLFEED_WEAPON_VERSION if weapons is not None else None}",
        "rule": "every view the entry occupies, its first included: each victim portrait "
                "is fully drawn at the entry's first 2 Hz sample",
    }
    out = fixture_path(store, session_id, round_no, "killfeed")
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, provenance_json=json.dumps(prov), entries_json=json.dumps(entries),
                        frame_t=np.array(got, dtype=np.float64),
                        frame_idx=np.array(frame_idx, dtype=np.int64),
                        crops=np.stack(crops))
    print(f"{out}: {len(entries)} entries, {len(got)} frames from the {cache.record['roi']} cache")
    for e in entries:
        print(f"  {e['t_first'] / 1000:7.1f} s slot {e['slot']} {e['side']:5s} "
              f"{len(e['views'])} views")
    return out


def build_minimap(store: Store, session_id: str, date: str, round_no: int) -> Path:
    """Icon crops around each labelled sighting; decodes one frame per label time."""
    from prototypes.round_identity_eval import load_minimap_labels, load_round_bounds
    man = _manifest(store, session_id)
    src = man["source"]
    if not Path(src["path"]).is_file():
        raise SystemExit(f"{session_id}: capture not found at {src['path']}")
    profile = get_profile(man["source_profile"])
    mx0, my0, mx1, my1 = next(r for r in profile.rois
                              if r.name == "minimap").pixels(int(src["width"]), int(src["height"]))
    t0, t1, _ = load_round_bounds(store, session_id, date, round_no)
    sightings = load_minimap_labels(store, session_id, t0, t1)
    cap = cv2.VideoCapture(src["path"])
    frames = {}
    try:
        for t in sorted({s["t_ms"] for s in sightings}):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t))
            ok, frame = cap.read()
            if not ok:
                raise SystemExit(f"no frame at {t} ms")
            frames[t] = frame[my0:my1, mx0:mx1]
    finally:
        cap.release()
    meta, arrays = [], {}
    for i, s in enumerate(sightings):
        x, y, r = int(s["x"]), int(s["y"]), int(s["r"])
        crop = np.ascontiguousarray(frames[s["t_ms"]][max(0, y - r):y + r, max(0, x - r):x + r])
        arrays[f"crop_{i}"] = crop
        meta.append({**{k: s[k] for k in ("t_ms", "x", "y", "r", "agent", "marked_kind")},
                     "idx": i, "crop_shape": list(crop.shape)})
    prov = {
        "builder": "prototypes/round_identity_fixture.py", "kind": "minimap",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": session_id, "date": date, "round_no": round_no,
        "round_ms": [t0, t1], "content_key": src.get("content_key"),
        "source": "video: one CAP_PROP_POS_MSEC seek per distinct label time",
        "frames_decoded": len(frames), "minimap_rect": [mx0, my0, mx1, my1],
        "labels": f"labels/minimap_agent/{session_id}.jsonl",
    }
    out = fixture_path(store, session_id, round_no, "minimap")
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, provenance_json=json.dumps(prov), meta_json=json.dumps(meta), **arrays)
    print(f"{out}: {len(meta)} sightings from {len(frames)} decoded frames")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?", default="a06f04a0059f")
    ap.add_argument("--round", type=int, default=4)
    ap.add_argument("--date", default="2026-08-26")
    ap.add_argument("--decode-minimap", action="store_true",
                    help="also cut the minimap icon crops, decoding one frame per label time")
    args = ap.parse_args()
    store = Store()
    build_killfeed(store, args.session, args.date, args.round)
    if args.decode_minimap:
        build_minimap(store, args.session, args.date, args.round)
    return 0


if __name__ == "__main__":
    sys.exit(main())
