r"""Check a freshly recorded ability-demo clip BEFORE it is ingested.

    .\.venv\Scripts\python.exe prototypes\clip_preflight.py <video>... [--donor a06f04a0059f]
    .\.venv\Scripts\python.exe prototypes\clip_preflight.py --write-donor [--donor a06f04a0059f]

Why this exists, 2026-09-03
-----------------------------
the player records a sitting of one-agent demo clips back to back, and CLAUDE.md's
"Before ingesting any new capture" checklist is a list of settings that break
things SILENTLY -- extraction still returns answers, they are merely wrong. The
first clip of this sitting proved it: minimap orientation was left on
side-based, so the whole widget was rotated 180 degrees and nothing downstream
would have said so. A per-clip check costs seconds; finding it later costs the
sitting.

What it checks, and how each one is decided rather than eyeballed:

    widget size    the map's white line-work, measured inside the minimap ROI,
                   must span the same rows as a KNOWN bigmap session. The small
                   widget stops ~150 px higher. Restricted to the ROI because
                   anything bright elsewhere on screen is not this test's
                   business -- see ROI's comment.
    orientation    normalised cross-correlation of the clip's median map
                   against the donor's, and against the donor rotated 180.
                   Whichever wins IS the orientation -- a bounding box cannot
                   answer this, because a roughly centred map has nearly the
                   same box either way.
    top-left ROI   anything drawn over the minimap (the shooting-error readout
                   landed there on this account) shows as line-work reaching
                   further left than the donor's.

WARNING: this is the sole non-builder capture median allowlisted by `doctor`.
It may be used only for widget dimensions, placement and orientation. It must
never become a floor mask, lighting reference, detector background, or cached
base map; those come only from baked ``(map, profile)`` geometry.

The donor snapshot, 2026-10-05
------------------------------
The player deletes the video of every capture without a replay file, the
default donor's among them. `--write-donor` stores the donor's median corner,
with its provenance, at `<store>/reference/preflight_donor/<donor>.npz`;
preflight reads that snapshot and decodes the donor's video only when no
snapshot exists. With neither, or with a snapshot sampled at another `--n`
and no video, it refuses by name. Only this file may read the snapshot
(`doctor` SESSION_STATIC enforces this), and only for the three checks above.

The median over sampled frames is what makes all three checks readable at all: the
widget is SEMI-TRANSPARENT over live scenery, so a single frame carries the
world moving behind it. Same trick `minimap_geometry` uses.

Reports, never fixes. A failure here is a capture setting, not a code change.

`--key <map>__<profile>` also fits the widget's PLACEMENT per sampled frame
against that key's baked static (`reticle.widget_frame.fit_crop`): scale,
rotation and corner, grouped into segments (a side-based capture flips at the
half). The player, 2026-09-28: a variant widget is read through this
transform rather than abstained on. The fit uses single frames, never the
median, and the numbers it prints are what `reticle widget-fit --write` stores
on the manifest after ingest.

One limit, stated because the output can mislead: the correlation is not
alignment-invariant. It rotates the donor about the CROP centre rather than the
widget centre, and it cannot absorb a translation, so a clip whose widget sits
somewhere else scores low BOTH ways and reports "cannot tell" rather than
naming the rotation. That is the honest answer -- such a clip has already
failed the size and ROI checks -- but do not read "cannot tell" as "upright".
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

STORE = Path.home() / "reticle-store"
# The minimap ROI of valorant-16x9-bigmap, in pixels at 1080p, plus a small
# margin. Measuring INSIDE it is not a convenience: the Neon clip drew a bright
# vertical band down the frame's left edge, outside the widget entirely, and a
# whole-corner bounding box read that as the map growing 73 rows taller. A
# check that fires on content it was never asked about costs a re-record.
ROI = (15, 14, 480, 500)
W = H = 560
N = 41
ROT_MARGIN = 0.02      # ncc difference below this is "cannot tell"
# 0.1.0 (2026-10-05): the donor's `median_corner`, stored losslessly with its
# sample, so preflight survives the donor video's retirement.
PREFLIGHT_DONOR_VERSION = "preflight-donor-0.1.0"
SNAPSHOT_DIR = STORE / "reference" / "preflight_donor"


class Refusal(Exception):
    """Preflight cannot obtain a donor median; the message names why."""


def corner_frames(path: str, n: int = N, meta: dict | None = None):
    """`(t_ms, top-left corner)` of `n` frames spread over the capture.

    `meta`, when given, receives the frame count, fps and decoded indices."""
    cap = cv2.VideoCapture(str(path))
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    out, idx = [], []
    for i in np.linspace(tot * 0.05, tot * 0.95, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            out.append((i * 1000.0 / fps, fr[:H, :W].copy()))
            idx.append(int(i))
    cap.release()
    if not out:
        raise SystemExit(f"{path}: decoded no frames")
    if meta is not None:
        meta.update(frame_count=tot, fps=fps, frame_indices=idx,
                    t_ms=[float(t) for t, _ in out])
    return out


def median_corner(path: str, n: int = N, frames=None):
    """Capture median for widget geometry checks only; never map extraction."""
    buf = [f for _, f in (frames or corner_frames(path, n))]
    return np.median(np.stack(buf), 0).astype(np.uint8)


def snapshot_path(donor: str) -> Path:
    return SNAPSHOT_DIR / f"{donor}.npz"


def _sha(arr) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _manifest(donor: str) -> dict:
    p = STORE / "manifests" / f"{donor}.json"
    if not p.is_file():
        raise Refusal(f"donor {donor}: no manifest at {p}")
    return json.loads(p.read_text())


def _decodable(donor: str, man: dict) -> str:
    """The donor video's path; a Refusal names why it cannot be decoded."""
    if man.get("video_retired"):
        raise Refusal(f"donor {donor}: video retired at {man['video_retired'].get('at')}")
    path = man["source"]["path"]
    if not Path(path).is_file():
        raise Refusal(f"donor {donor}: video {path} is not on disk")
    return path


def write_donor(donor: str, n: int = N) -> Path:
    """Decode the donor's median corner once and store it with provenance.

    Refuses rather than overwrite an existing snapshot."""
    out = snapshot_path(donor)
    if out.exists():
        raise Refusal(f"donor {donor}: snapshot {out} exists; it is never overwritten")
    man = _manifest(donor)
    path = _decodable(donor, man)
    meta: dict = {}
    med = median_corner(path, n, corner_frames(path, n, meta))
    prov = {
        "version": PREFLIGHT_DONOR_VERSION, "donor": donor,
        "source_profile": man["source_profile"], "source_path": path,
        "content_key": man["source"].get("content_key"), "n": n,
        "n_decoded": len(meta["frame_indices"]), "frame_count": meta["frame_count"],
        "fps": meta["fps"], "frame_indices": meta["frame_indices"], "t_ms": meta["t_ms"],
        "crop": [0, 0, W, H], "shape": list(med.shape), "dtype": str(med.dtype),
        "sha256": _sha(med),
        "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.npz")
    np.savez_compressed(tmp, median=med, provenance=np.array(json.dumps(prov)))
    os.replace(tmp, out)
    return out


def donor_median(donor: str, n: int = N):
    """`(median corner, source profile, origin)` for `donor`.

    Reads the stored snapshot; decodes the donor's video only without one."""
    p = snapshot_path(donor)
    note = ""
    if p.is_file():
        with np.load(p, allow_pickle=False) as z:
            med, prov = z["median"], json.loads(str(z["provenance"]))
        if _sha(med) != prov["sha256"]:
            raise Refusal(f"donor {donor}: snapshot {p} fails its sha256")
        if prov["n"] == n:
            return med, prov["source_profile"], f"snapshot {p} [{prov['version']}]"
        note = f"; its snapshot sampled n={prov['n']}, not {n}"
    man = _manifest(donor)
    try:
        path = _decodable(donor, man)
    except Refusal as e:
        raise Refusal(f"{e}, and no usable snapshot at {p}{note}") from None
    return median_corner(path, n), man["source_profile"], f"decoded {path}{note}"


def placements(frames, key: str):
    """The widget's placement segments against `key`'s baked static, fitted
    per frame (`reticle.widget_frame`), in full-frame pixels."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from reticle import widget_frame as wf
    from reticle.geometry import reference_for_key
    static = reference_for_key(key)
    fits = [(t, wf.fit_crop(static, f, (0, 0))) for t, f in frames]
    return wf.placement_segments(fits), static.shape[:2]


def linework_bbox(med):
    """Bounding box of the map's white line-work, measured INSIDE the ROI.

    Returned in full-frame coordinates so it stays comparable to the donor's.
    """
    x0, y0, x1, y1 = ROI
    g = cv2.cvtColor(med[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    m = (g > np.percentile(g, 99.0)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return (int(xs.min()) + x0, int(ys.min()) + y0,
            int(xs.max()) + x0, int(ys.max()) + y0)


def ncc(a, b):
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    a, b = a - a.mean(), b - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float((a * b).sum() / d) if d else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--donor", default="a06f04a0059f",
                    help="ingested session on the SAME map to compare against")
    ap.add_argument("--n", type=int, default=N)
    ap.add_argument("--key", default=None,
                    help="also fit the widget placement against this <map>__<profile> baked static")
    ap.add_argument("--write-donor", action="store_true",
                    help="store the donor's median corner under reference/preflight_donor/ and exit")
    a = ap.parse_args()

    try:
        if a.write_donor:
            print(f"wrote {write_donor(a.donor, a.n)}")
            return 0
        if not a.videos:
            ap.error("name at least one video, or pass --write-donor")
        donor, profile, origin = donor_median(a.donor, a.n)
    except Refusal as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"donor median from {origin}", file=sys.stderr)
    dbb = linework_bbox(donor)
    print(f"donor {a.donor} [{profile}]  linework bbox {dbb}\n")

    bad = 0
    for v in a.videos:
        frames = corner_frames(v, a.n)
        med = median_corner(v, a.n, frames)
        bb = linework_bbox(med)
        up, down = ncc(med, donor), ncc(med, cv2.rotate(donor, cv2.ROTATE_180))
        rows_ok = abs(bb[1] - dbb[1]) <= 6 and abs(bb[3] - dbb[3]) <= 6
        left_ok = bb[0] >= dbb[0] - 6
        if abs(up - down) < ROT_MARGIN:
            orient = f"CANNOT TELL  (ncc {up:+.3f} vs rot180 {down:+.3f})"
            ok_o = False
        elif up > down:
            orient, ok_o = f"upright      (ncc {up:+.3f} vs rot180 {down:+.3f})", True
        else:
            orient, ok_o = f"ROTATED 180  (ncc {up:+.3f} vs rot180 {down:+.3f})", False

        print(f"{Path(v).name}")
        print(f"   linework bbox {bb}")
        print(f"   [{'ok' if rows_ok else 'FAIL'}] widget size   rows {bb[1]}..{bb[3]} "
              f"vs donor {dbb[1]}..{dbb[3]}"
              f"{'' if rows_ok else '   <- small widget, or a different minimap size'}")
        print(f"   [{'ok' if ok_o else 'FAIL'}] orientation   {orient}")
        print(f"   [{'ok' if left_ok else 'FAIL'}] top-left ROI  left edge {bb[0]} "
              f"vs donor {dbb[0]}"
              f"{'' if left_ok else '   <- something is drawn over the minimap'}")
        if a.key:
            segs, shape = placements(frames, a.key)
            for sg in segs:
                m = np.asarray(sg["affine"])
                print(f"   placement     from {sg['t0_ms']} ms: rotation {sg['rotation']}, "
                      f"scale {sg['scale']:.3f}, corner ({m[0, 2]:.1f}, {m[1, 2]:.1f}), "
                      f"{sg['n']} frames")
        if not (rows_ok and ok_o and left_ok):
            bad += 1
        print()
    print(f"{len(a.videos) - bad}/{len(a.videos)} clips pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
