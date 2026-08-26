"""Does 4:2:0 chroma subsampling destroy the enemy rim?

    .\\.venv\\Scripts\\python.exe prototypes\\chroma_test.py <lossless.avi> [--n 60]

The hypothesis. The enemy outline is a 1-4 px rim whose whole signal is
chroma -- that is literally what the Lab `a*` top-hat reads. H.264 in OBS
defaults to NV12 / 4:2:0, which stores chroma at HALF resolution in both axes,
so a 1-2 px rim's colour is averaged with the background it borders before the
file is ever written. Two adjudicated Lotus misses had **zero top-hat response**
-- no rim at all, at 6-76 px where the rim should have been -- and that is what
this failure would look like.

Why a lossless capture makes this answerable. Comparing a lossless capture
against an existing H.264 one would confound the codec with the scene, the map,
the lighting and possibly the colour range. Instead this degrades the lossless
frames ITSELF and compares each frame with its own subsampled twin: identical
content, identical colour range, identical everything except the chroma
resolution. That isolates the mechanism, which is the whole point of having the
capture.

It deliberately measures the RIM MASK, not the detections. Subsampling acts on
pixels; counting blobs afterwards would let the closing kernel and the size
floors hide how much of the rim actually survived.

What this test cannot say. It isolates chroma subsampling ONLY. A real H.264
encode also quantises and deblocks, and those act on luma too. `--h264` adds
that round trip where ffmpeg is available; without it, read the numbers here as
the subsampling term alone, which is a lower bound on the codec's total damage.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import enemy_features as ef                                    # noqa: E402


def to_420(fr):
    """Round-trip BGR through 4:2:0 chroma, as an encoder and decoder would.

    Box-average down (what an encoder does) and bilinear up (what a decoder
    does). Luma is untouched, which is the point: any difference this produces
    is chroma resolution and nothing else.
    """
    ycc = cv2.cvtColor(fr, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = ycc[:, :, 0], ycc[:, :, 1], ycc[:, :, 2]
    h, w = y.shape
    small = (w // 2, h // 2)
    cr2 = cv2.resize(cv2.resize(cr, small, interpolation=cv2.INTER_AREA),
                     (w, h), interpolation=cv2.INTER_LINEAR)
    cb2 = cv2.resize(cv2.resize(cb, small, interpolation=cv2.INTER_AREA),
                     (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.cvtColor(np.dstack([y, cr2, cb2]), cv2.COLOR_YCrCb2BGR)


def h264_roundtrip(frames, crf=23):
    """Encode frames as OBS would and read them back. Needs ffmpeg on PATH."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    h, w = frames[0].shape[:2]
    with tempfile.TemporaryDirectory() as td:
        out = str(Path(td) / "clip.mp4")
        p = subprocess.Popen(
            [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{w}x{h}", "-r", "60", "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
             "-pix_fmt", "yuv420p", out],
            stdin=subprocess.PIPE)
        for f in frames:
            p.stdin.write(f.tobytes())
        p.stdin.close()
        if p.wait() != 0:
            return None
        cap = cv2.VideoCapture(out)
        got = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            got.append(f)
        cap.release()
    return got if len(got) == len(frames) else None


def compare(ref, deg, cfg):
    """Rim survival between a reference frame and a degraded one."""
    k_ref, top_ref, *_ = ef.rim_mask(ref, cfg)
    k_deg, top_deg, *_ = ef.rim_mask(deg, cfg)
    n_ref = int(k_ref.sum())
    both = int((k_ref & k_deg).sum())
    return {
        "rim_ref": n_ref,
        "rim_deg": int(k_deg.sum()),
        "kept": both,
        # Top-hat strength AT THE REFERENCE RIM, in both. The mask is a
        # threshold on this, so it says how much headroom was lost -- a rim that
        # drops from 60 to 30 still passes thr=25 and is one step from not.
        "top_ref": float(top_ref[k_ref].mean()) if n_ref else 0.0,
        "top_deg": float(top_deg[k_ref].mean()) if n_ref else 0.0,
        "det_ref": len(ef.detect(ref, ef.SHIPPED)),
        "det_deg": len(ef.detect(deg, ef.SHIPPED)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--h264", action="store_true", help="also do a real encode")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"cannot open {args.video}")
        return 1
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idx = np.linspace(0, max(total - 1, 0), args.n).astype(int)
    frames = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            frames.append(fr)
    cap.release()
    if not frames:
        print("no frames read")
        return 1

    print(f"{Path(args.video).name}: {total} frames, sampled {len(frames)}")
    # Colour range is worth stating: a full-range capture and a limited-range one
    # differ on every ABSOLUTE threshold in the detector, which is exactly the
    # trap CLAUDE.md warns about. It does not affect the comparison below --
    # both sides come from the same file -- but it does affect comparing this
    # capture against the H.264 library.
    ys = np.concatenate([cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)[:, :, 0].ravel()[::97]
                         for f in frames[:10]])
    print(f"luma range in this capture: {ys.min()}..{ys.max()} "
          f"({'full' if ys.min() < 16 or ys.max() > 235 else 'limited or full, indistinguishable'})")

    rows = [compare(f, to_420(f), ef.SHIPPED) for f in frames]
    _report("4:2:0 chroma only", rows)

    if args.h264:
        enc = h264_roundtrip(frames)
        if enc is None:
            print("\nffmpeg unavailable or failed -- skipping the real encode")
        else:
            _report("full H.264 encode (crf 23)",
                    [compare(f, e, ef.SHIPPED) for f, e in zip(frames, enc)])
    return 0


def _report(title, rows):
    rim_ref = sum(r["rim_ref"] for r in rows)
    rim_deg = sum(r["rim_deg"] for r in rows)
    kept = sum(r["kept"] for r in rows)
    det_ref = sum(r["det_ref"] for r in rows)
    det_deg = sum(r["det_deg"] for r in rows)
    live = [r for r in rows if r["rim_ref"] > 0]
    print(f"\n--- {title} ---")
    print(f"  rim pixels        {rim_ref:8d} -> {rim_deg:8d}  "
          f"({rim_deg/max(rim_ref,1)*100:5.1f}% of reference)")
    print(f"  reference rim px surviving  {kept:8d}  "
          f"({kept/max(rim_ref,1)*100:5.1f}%)")
    if live:
        tr = sum(r["top_ref"] for r in live)/len(live)
        td = sum(r["top_deg"] for r in live)/len(live)
        print(f"  top-hat at reference rim    {tr:6.1f} -> {td:6.1f}  "
              f"({(td-tr)/max(tr,1e-9)*100:+5.1f}%, threshold is {ef.SHIPPED.thr})")
    print(f"  SHIPPED detections  {det_ref:5d} -> {det_deg:5d}   "
          f"over {len(rows)} frames, {len(live)} with any rim")


if __name__ == "__main__":
    raise SystemExit(main())
