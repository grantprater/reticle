r"""Does DRAWN CONTENT sit where the self ring refuses.

    .\.venv\Scripts\python.exe prototypes\minimap_occlusion.py c40d950031bb \
        --from-s 210 --to-s 340

The overlap story for self-ring refusals was inspected on a contact sheet, then
tested against the ALLY channel and cut to a 1.2x-1.6x lift. That test could
only see one occluder. The widget also draws enemies, ability entities, pings,
the spike, last-known markers and buy-phase barriers -- and the shipped reader
reads none of them, so no stored channel can answer the question.

This names no occluder. It measures FOREIGN CONTENT: pixels near the self
position whose grey leaves the geometry's measured [lo_gray, hi_gray] lighting
band, excluding self-keyed pixels. Anything drawn over the map counts, read or
not. It compares instants the reader answered against bracketed refusals, whose
centre is fixed by the fits either side.

Diagnostic only. It labels nothing and changes no reader.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle import geometry  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.minimap import (R_MAX, floor_mask, minimap_roi_px, self_icons,  # noqa: E402
                             self_mask, slab_mask, widget_drawn, widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402


def foreign_fraction(crop: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                     keyed: np.ndarray, cx: float, cy: float, radius: float,
                     margin: float) -> float | None:
    """Share of nearby pixels that neither the map nor the self icon explains.

    The widget is semi-transparent over live world, so `lo_gray`/`hi_gray` are
    the two measured lighting states rather than one clean background. A pixel
    outside that band by `margin` carries something drawn on top -- an icon, a
    region, a ping, a barrier -- without needing to say which.
    """
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = grey.shape
    r = int(np.ceil(radius))
    x0, x1 = max(0, int(cx) - r), min(w, int(cx) + r + 1)
    y0, y1 = max(0, int(cy) - r), min(h, int(cy) + r + 1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius * radius
    disc &= ~keyed[y0:y1, x0:x1]
    if int(disc.sum()) < 12:
        return None
    g = grey[y0:y1, x0:x1]
    band_lo = lo[y0:y1, x0:x1] - margin
    band_hi = hi[y0:y1, x0:x1] + margin
    foreign = ((g < band_lo) | (g > band_hi)) & disc
    return float(foreign.sum() / disc.sum())


def bracketed(rows: list[dict], max_gap_ms: float = 55.0) -> dict[int, tuple]:
    """Refusals bounded by close fitted centres on each side."""
    fitted = [i for i, r in enumerate(rows) if r["fit"] is not None]
    out = {}
    for i, row in enumerate(rows):
        if row["fit"] is not None or not row["drawn"]:
            continue
        before = next((j for j in reversed(fitted) if j < i), None)
        after = next((j for j in fitted if j > i), None)
        if before is None or after is None:
            continue
        a, b = rows[before], rows[after]
        if (row["t_ms"] - a["t_ms"] > max_gap_ms
                or b["t_ms"] - row["t_ms"] > max_gap_ms):
            continue
        af, bf = a["fit"], b["fit"]
        if np.hypot(af["cx"] - bf["cx"], af["cy"] - bf["cy"]) > 6.0:
            continue
        q = (row["t_ms"] - a["t_ms"]) / (b["t_ms"] - a["t_ms"])
        out[i] = (af["cx"] + q * (bf["cx"] - af["cx"]),
                  af["cy"] + q * (bf["cy"] - af["cy"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--from-s", type=float, required=True)
    ap.add_argument("--to-s", type=float, required=True)
    ap.add_argument("--out", default=None, help="write the report JSON here")
    args = ap.parse_args(argv)

    store = Store(args.store)
    manifest = json.loads((Path(args.store) / "manifests" /
                           f"{args.session}.json").read_text(encoding="utf-8"))
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    box = minimap_roi_px(profile, int(src["width"]), int(src["height"]))
    med = geometry.reference_static(args.session, store.root)
    sd = geometry.stability(args.session, store.root, med.shape[:2])
    floor, slab = floor_mask(med, sd=sd), slab_mask(med, sd=sd)
    sgray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)
    with np.load(geometry.require(args.session, store.root)) as z:
        lo, hi = z["lo_gray"].astype(np.float32), z["hi_gray"].astype(np.float32)

    x0, y0, x1, y1 = box
    spans = [(args.from_s * 1000.0, args.to_s * 1000.0)]
    rows = []
    for _who, smp in sample_windows(src["path"], float(src["fps"]),
                                    {"native": (float(src["fps"]) * 4.0, spans)}):
        crop = smp.frame[y0:y1, x0:x1]
        drawn = widget_drawn(crop, sgray, floor)
        fits = (self_icons(crop, floor, require_facing=False, support=slab)
                if drawn else [])
        rows.append({"t_ms": smp.t_ms, "crop": crop.copy(), "drawn": drawn,
                     "fit": max(fits, key=lambda d: d["cov"]) if fits else None})

    scale = widget_scale(rows[0]["crop"].shape[1])
    radius = 1.5 * R_MAX * scale
    marks = bracketed(rows)
    print(f"{len(rows)} instants; {sum(r['fit'] is not None for r in rows)} read; "
          f"{len(marks)} bracketed refusals; radius {radius:.1f} px")

    report = {"session_id": args.session, "spans_ms": spans,
              "radius_px": radius, "margins": {}}
    for margin in (8.0, 12.0, 20.0):
        read, refused = [], []
        for i, row in enumerate(rows):
            if not row["drawn"]:
                continue
            keyed = self_mask(row["crop"])
            if row["fit"] is not None:
                v = foreign_fraction(row["crop"], lo, hi, keyed,
                                     row["fit"]["cx"], row["fit"]["cy"],
                                     radius, margin)
                if v is not None:
                    read.append(v)
            elif i in marks:
                cx, cy = marks[i]
                v = foreign_fraction(row["crop"], lo, hi, keyed, cx, cy,
                                     radius, margin)
                if v is not None:
                    refused.append(v)
        read, refused = np.array(read), np.array(refused)
        if not read.size or not refused.size:
            continue
        lift = float(np.mean(refused) / np.mean(read)) if np.mean(read) else None
        report["margins"][str(margin)] = {
            "read_n": int(read.size), "refused_n": int(refused.size),
            "read_mean": float(np.mean(read)),
            "refused_mean": float(np.mean(refused)),
            "read_median": float(np.median(read)),
            "refused_median": float(np.median(refused)),
            "lift": lift,
        }
        print(f"  margin {margin:4.0f}: read n={read.size} mean="
              f"{np.mean(read):.3f} median={np.median(read):.3f} | "
              f"refused n={refused.size} mean={np.mean(refused):.3f} "
              f"median={np.median(refused):.3f} | lift {lift:.2f}x")
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True),
                          encoding="utf-8")
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
