r"""An icon's facing from where its rim is brightest: the teardrop's tip drawn lighter.

    .\.venv\Scripts\python.exe prototypes\tip_highlight.py [--record] [--sheet]

The player, labelling 331 px teammate icons (2026-09-29), saw the tip of the
teardrop drawn lighter than the rest of the rim, like a highlight
[domain:minimap/icon-tip-highlight]. This reads a facing from that highlight
alone, as a witness beside the teardrop's template fit (`reticle.teardrop`),
which scores the lobe's SHAPE and ignores its brightness.

**The rule** (`read`, `tip-highlight-0.1.0`). Round the class detector's
centre (the ring fit, not the teardrop, so no teardrop output enters), take
the pixels at radii `[r_in - 1, L + 1.5]` (the class's `reticle.teardrop`
radii, scaled by `minimap.widget_scale`) whose class hue (`HUE`: ally
min(G, B) - R, enemy R - max(G, B), self min(G, R) - B) reaches `HUE_MIN`.
Grey floor, white walls and the portrait carry no hue and drop out. Of those,
keep the brightest `TOP_FRAC` by `max(B, G, R)` (the saturated tip reaches
255 in its dominant channel) and return the circular mean of their angles
about the centre. It refuses with `no_hue` under `MIN_PX` hued pixels and
`diffuse` where the kept pixels' mean resultant length is under `MIN_R`.
Nothing here is fitted to labels; the constants were set after one
inspection sheet and a printout of pixel values along seven labelled rays.

`hue_mass` is the geometry-only control: the unweighted circular mean of ALL
hued pixels in the band, which the lobe's extra area pulls toward the tip
with no brightness at all. The highlight earns its place only where it beats
that control.

**Scoring** runs on labels only, with the scorers' own conventions
(`icon_facing_eval`, `self_facing_eval`): median absolute error, flip rate
(error above 90 degrees), clicks on another icon or another class's colour
out, `cant_tell` out. Sets: E6's ally and enemy labels (465 px, recomputed
from the crop cache), the Lotus self labels, and the 331 px ally set against
its frozen manifest. On the 331 px manifest it also reports agreement with
the teardrop and the ring, which is consistency, not accuracy. `--record`
writes one `metrics` row per set (series `tip_highlight_eval`); `--sheet`
writes contact sheets to the store's `analysis/tip-highlight-20260929/`.
Crop cache only; no decode.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402
import icon_facing_eval as ife  # noqa: E402
import label_icon_facing as lif  # noqa: E402
import label_self_facing as lsf  # noqa: E402
import self_facing_eval as sfe  # noqa: E402
from reticle import teardrop as td  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "tip-highlight-0.1.0"
EVAL_VERSION = "tip-highlight-eval-0.1.1"   # 0.1.1: manifest agreement keys `consistency_*`, apart from the agree stratum
HUE_MIN = 15.0        # class hue, 0-255 units; grey floor and white walls sit near 0
TOP_FRAC = 0.2        # the brightest fifth of the hued band
MIN_PX = 8            # hued pixels at scale 1.0 (scaled by area)
MIN_R = 0.25          # mean resultant length of the kept pixels
AGREE_DEG = 30.0
OUT = sem.STORE / "analysis" / "tip-highlight-20260929"


def hue(crop: np.ndarray, cls: str) -> np.ndarray:
    """The class's hue per pixel, signed, in 0-255 units (`HUE_MIN` gates it)."""
    c = crop.astype(np.float32)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    if cls == "ally":
        return np.minimum(g, b) - r
    if cls == "enemy":
        return r - np.maximum(g, b)
    if cls == "self":
        return np.minimum(g, r) - b
    raise ValueError(cls)


def radii(cls: str) -> tuple[float, float]:
    """`(r_in, L)` at widget scale 1.0, from the owner's class table."""
    if cls == "self":
        return td.R_IN, td.L
    c = td.ICON_CLASSES[cls]
    return c.r_in, c.L


def _circ(ang: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    s, c = float((w * np.sin(ang)).sum()), float((w * np.cos(ang)).sum())
    return math.degrees(math.atan2(s, c)), math.hypot(s, c) / max(float(w.sum()), 1e-9)


def read(crop: np.ndarray, cls: str, cx: float, cy: float, scale: float = 1.0) -> dict:
    """`{"deg", "r", "n_hued", "read", "reason"?, "hue_mass_deg", "pts"}` round `(cx, cy)`.

    `deg` is image degrees, y down. `pts` are the kept pixels, for the sheet.
    """
    r_in, L = radii(cls)
    lo, hi = (r_in - 1.0) * scale, (L + 1.5) * scale
    h, w = crop.shape[:2]
    R = int(math.ceil(hi)) + 1
    x0, x1, y0, y1 = max(0, int(cx) - R), min(w, int(cx) + R + 2), max(0, int(cy) - R), min(h, int(cy) + R + 2)
    sub = crop[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rho = np.hypot(xx - cx, yy - cy)
    band = (rho >= lo) & (rho <= hi)
    hued = band & (hue(sub, cls) >= HUE_MIN)
    n = int(hued.sum())
    out = {"n_hued": n, "read": False, "deg": None, "r": None, "hue_mass_deg": None, "pts": []}
    if n < max(3, int(round(MIN_PX * scale * scale))):
        out["reason"] = "no_hue"
        return out
    ang = np.arctan2(yy[hued] - cy, xx[hued] - cx)
    out["hue_mass_deg"] = _circ(ang, np.ones(n))[0]
    v = sub.max(axis=2).astype(np.float32)[hued]
    k = max(3, int(round(TOP_FRAC * n)))
    top = np.argsort(-v, kind="stable")[:k]
    deg, rr = _circ(ang[top], np.ones(k))
    out.update(deg=deg, r=rr, pts=list(zip(xx[hued][top].tolist(), yy[hued][top].tolist())))
    if rr < MIN_R:
        out.update(reason="diffuse")
        return out
    out["read"] = True
    return out


# ---------------------------------------------------------------- scoring

def _idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)   # IDLE_PRIORITY_CLASS
    except Exception:
        pass
    cv2.setNumThreads(1)


def _sess(sid: str):
    import team_vision_eval as tve
    return tve.Sess(sid)


def _crops(items: list[dict]) -> dict:
    by = defaultdict(set)
    for it in items:
        by[it["session"]].add(float(it["t_ms"]))
    out = {}
    for sid, ts in by.items():
        for t, c in _sess(sid).crops(sorted(ts)):
            out[(sid, float(t))] = c
    return out


def _add(rows: list[dict], centres: dict, crops: dict, cls_of) -> None:
    """Attach the highlight reading at each row's detector centre."""
    for r in rows:
        crop = crops[(r["session"], float(r["t_ms"]))]
        cx, cy = centres[r["key"]]
        hl = read(crop, cls_of(r), cx, cy, widget_scale(crop.shape[1]))
        r["highlight"] = hl["deg"] if hl["read"] else None
        r["highlight_reason"] = hl.get("reason")
        r["highlight_r"] = hl["r"]
        r["hue_mass"] = hl["hue_mass_deg"]
        r["det_cx"], r["det_cy"] = cx, cy
        r["_pts"] = hl["pts"]


def _err(r, name):
    if r.get(name) is None or r.get("label_deg") is None:
        return None
    return float(sem._signed_deg(r[name] - r["label_deg"]))


def summarise(rows: list[dict], readers) -> dict:
    out = {}
    for name in readers:
        errs = [e for e in (_err(r, name) for r in rows) if e is not None]
        d = ife.summary(errs)
        d["unread"] = sum(r.get(name) is None for r in rows)
        out[name] = d
    return out


def e6_rows(store: Path) -> list[dict]:
    """E6's ally and enemy labels, the teardrop and ring recomputed by `icon_facing_eval`."""
    index = json.loads((lif.items_dir(store) / "index.json").read_text(encoding="utf-8"))["items"]
    answers = lif.load_answers(lif.labels_path(store))
    rows = ife.readings(index, answers)
    by = {it["key"]: it for it in index}
    crops = _crops(rows)
    _add(rows, {k: (by[k]["det_x"], by[k]["det_y"]) for k in by}, crops, lambda r: r["cls"])
    for r in rows:
        r["_crop"] = crops[(r["session"], float(r["t_ms"]))]
    return rows


def e6_scored(rows):
    return [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= ife.ELSEWHERE_PX
            and r.get("label_colour", r["cls"]) == r["cls"]]


def self_rows(store: Path) -> list[dict]:
    index = json.loads((lsf.items_dir(store) / "index.json").read_text(encoding="utf-8"))["items"]
    answers = lsf.load_answers(lsf.labels_path(store))
    rows = sfe.readings(store, index, answers)
    by = {it["key"]: it for it in index}
    crops = _crops(rows)
    _add(rows, {k: (by[k]["ring_x"], by[k]["ring_y"]) for k in by}, crops, lambda r: "self")
    for r in rows:
        r["cls"] = "self"
        r["_crop"] = crops[(r["session"], float(r["t_ms"]))]
    return rows


def self_scored(rows):
    return [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= sfe.ELSEWHERE_PX]


def rows_331(store: Path) -> tuple[list[dict], list[dict]]:
    """The labelled rows and every manifest item, each with the highlight."""
    idir = lif.items_dir(store, lif.SET_331)
    manifest = json.loads((idir / "manifest.json").read_text(encoding="utf-8"))["items"]
    answers = lif.load_answers(lif.labels_path(store, lif.SET_331))
    crops = _crops(manifest)
    centres = {m["key"]: (m["det_x"], m["det_y"]) for m in manifest}
    allm = [dict(m, teardrop=m["teardrop_deg"], ring=m["ring_deg"], ring_lobe=m["ring_lobe_deg"], cls="ally")
            for m in manifest]
    _add(allm, centres, crops, lambda r: "ally")
    rows = ife.rows_331(manifest, answers)
    hl = {m["key"]: m for m in allm}
    for r in rows:
        for k in ("highlight", "highlight_reason", "highlight_r", "hue_mass", "det_cx", "det_cy", "_pts"):
            r[k] = hl[r["key"]][k]
        r["cls"] = "ally"
        r["_crop"] = crops[(r["session"], float(r["t_ms"]))]
    for m in allm:
        m["_crop"] = crops[(m["session"], float(m["t_ms"]))]
    return rows, allm


def scored_331(rows):
    return [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= ife.ELSEWHERE_331_PX]


def agreement(items: list[dict], a: str, others) -> dict:
    """How often `a` lies within `AGREE_DEG` of each other reader, where both read."""
    out = {}
    for b in others:
        d = [abs(float(sem._signed_deg(m[a] - m[b]))) for m in items if m.get(a) is not None and m.get(b) is not None]
        out[b] = {"n": len(d), "within30": float(np.mean(np.asarray(d) <= AGREE_DEG)) if d else None,
                  "over90": float(np.mean(np.asarray(d) > 90)) if d else None,
                  "median_abs_deg": float(np.median(d)) if d else None}
    return out


# ---------------------------------------------------------------- the sheet

def sheet(rows: list[dict], path: Path, readers=("highlight", "teardrop"), zoom: int = 7, half: int = 22,
          per_row: int = 8) -> Path:
    """Each item zoomed: the label (green), the highlight (magenta, its kept pixels dotted) and the teardrop (cyan)."""
    colours = {"label": (0, 255, 0), "highlight": (255, 0, 255), "teardrop": (255, 255, 0),
               "ring_lobe": (0, 128, 255), "ring": (0, 128, 255)}
    tiles = []
    for r in rows:
        crop = r["_crop"]
        cx, cy = r["det_cx"], r["det_cy"]
        ix, iy = int(round(cx)), int(round(cy))
        p = np.zeros((2 * half + 1, 2 * half + 1, 3), np.uint8)
        y0, x0 = iy - half, ix - half
        sub = crop[max(0, y0):iy + half + 1, max(0, x0):ix + half + 1]
        p[max(0, -y0):max(0, -y0) + sub.shape[0], max(0, -x0):max(0, -x0) + sub.shape[1]] = sub
        big = cv2.resize(p, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)

        def to(x, y):
            return (int((x - x0 + 0.5) * zoom), int((y - y0 + 0.5) * zoom))
        for (px, py) in r.get("_pts", []):
            cv2.circle(big, to(px, py), 2, colours["highlight"], -1)
        o = to(cx, cy)
        ln = half * zoom * 0.8
        for name in ("label",) + tuple(readers):
            deg = r.get("label_deg") if name == "label" else r.get(name)
            if deg is None:
                continue
            a = math.radians(deg)
            e = (int(o[0] + ln * math.cos(a)), int(o[1] + ln * math.sin(a)))
            cv2.arrowedLine(big, o, e, colours[name], 2 if name == "label" else 1, tipLength=0.12)
        eh = _err(r, "highlight")
        et = _err(r, "teardrop")
        txt = f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s {r['cls']}"
        cv2.putText(big, txt, (3, 13), 0, 0.42, (255, 255, 255), 1)
        txt2 = (f"hl {'-' if eh is None else f'{eh:+.0f}'} td {'-' if et is None else f'{et:+.0f}'}"
                if r.get("label_deg") is not None else
                f"hl {r.get('highlight_reason') or ''}")
        cv2.putText(big, txt2, (3, big.shape[0] - 5), 0, 0.42,
                    (0, 0, 255) if eh is None or abs(eh) > 90 else (255, 255, 255), 1)
        tiles.append(big)
    if not tiles:
        return path
    while len(tiles) % per_row:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)])
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), grid)
    return path


# ---------------------------------------------------------------- main

def _print(title: str, res: dict) -> None:
    print(f"\n== {title}")
    print(f"  {'reader':10s} {'n':>3s} {'unread':>6s} {'med|e|':>7s} {'flip':>5s} {'<=10':>5s} {'<=20':>5s} {'bias':>6s}")
    for name, v in res.items():
        if not v.get("n"):
            print(f"  {name:10s} {0:3d} {v['unread']:6d}")
            continue
        print(f"  {name:10s} {v['n']:3d} {v['unread']:6d} {v['median_abs_deg']:7.1f} {v['flip']:5.2f} "
              f"{v['within10']:5.2f} {v['within20']:5.2f} {v['median_signed_deg']:6.1f}")


def _values(res: dict, prefix: str) -> dict:
    out = {}
    for name, v in res.items():
        out[f"{prefix}{name}_n"] = v.get("n", 0)
        out[f"{prefix}{name}_unread"] = v["unread"]
        for k in ("median_abs_deg", "flip", "within10", "within20", "median_signed_deg"):
            if k in v:
                out[f"{prefix}{name}_{k}"] = round(v[k], 3)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true", help="one metrics row per label set")
    ap.add_argument("--sheet", action="store_true", help="write contact sheets to " + str(OUT))
    ap.add_argument("--json", type=Path, help="write the per-item rows here")
    args = ap.parse_args(argv)
    _idle()
    store = sem.STORE
    from reticle import metrics
    deps = {"prototype": EVAL_VERSION, "reader": VERSION, "hue_min": HUE_MIN, "top_frac": TOP_FRAC,
            "min_px": MIN_PX, "min_r": MIN_R, "teardrop": td.ICON_TEARDROP_VERSION}
    dump = {}

    e6 = e6_rows(store)
    readers = ("highlight", "hue_mass", "teardrop", "ring")
    vals = {}
    for cls in ("ally", "enemy"):
        sc = [r for r in e6_scored(e6) if r["cls"] == cls]
        res = summarise(sc, readers + (("ring_lobe",) if cls == "ally" else ()))
        _print(f"E6 {cls} labels, 465 px ({len(sc)} scored)", res)
        vals.update(_values(res, f"{cls}_"))
        vals[f"{cls}_reasons"] = sum(r["highlight"] is None for r in sc)
    dump["e6"] = e6
    if args.record:
        metrics.record("tip_highlight_eval", part="labels-465", session="+".join(lif.SESSIONS), values=vals,
                       deps=dict(deps, labels=lif.labels_path(store).name))

    sr = self_rows(store)
    ss = self_scored(sr)
    vals = {}
    for name, sub in (("lotus", [r for r in ss if r["session"] == lsf.LOTUS]), ("all", ss)):
        res = summarise(sub, ("highlight", "hue_mass", "teardrop", "ring"))
        _print(f"self labels, {name} ({len(sub)} scored)", res)
        vals.update(_values(res, f"{name}_"))
    dump["self"] = sr
    if args.record:
        metrics.record("tip_highlight_eval", part="self", session=f"{lsf.LOTUS}+controls", values=vals,
                       deps=dict(deps, labels=lsf.labels_path(store).name))

    lab = lif.labels_path(store, lif.SET_331)
    n_lab = len(lif.load_answers(lab))
    print(f"\n{lab}: {n_lab} labelled rows")
    if n_lab:
        r331, all331 = rows_331(store)
        s331 = scored_331(r331)
        res = summarise(s331, ("highlight", "hue_mass", "teardrop", "ring", "ring_lobe"))
        _print(f"331 px ally labels ({len(s331)} scored of {n_lab} rows)", res)
        vals = _values(res, "")
        vals["label_rows"] = n_lab
        for st in ("flip", "agree"):
            sub = [r for r in s331 if r["stratum"] == st]
            rs = summarise(sub, ("highlight", "teardrop", "ring_lobe"))
            _print(f"  stratum {st}", rs)
            vals.update(_values(rs, f"{st}_"))
        ag = agreement(all331, "highlight", ("teardrop", "ring", "ring_lobe", "hue_mass"))
        print(f"\n  manifest ({len(all331)} items), highlight agreement (consistency, not accuracy):")
        for b, v in ag.items():
            print(f"    vs {b:9s} n {v['n']:3d} within30 {v['within30']:.2f} over90 {v['over90']:.2f} "
                  f"median {v['median_abs_deg']:.1f}")
            for k in ("n", "within30", "over90", "median_abs_deg"):
                vals[f"consistency_{b}_{k}"] = round(v[k], 3) if isinstance(v[k], float) else v[k]
        dump["331"] = r331
        if args.record:
            metrics.record("tip_highlight_eval", part="labels-331", session="+".join(lif.QUOTA_331), values=vals,
                           deps=dict(deps, labels=lab.name, manifest=lif.VERSION_331))
        if args.sheet:
            print("wrote", sheet(s331, OUT / "sheet_331_ally.png"))
            print("wrote", sheet([m for m in all331 if m["key"] not in {r["key"] for r in r331}],
                                 OUT / "sheet_331_unlabelled.png"))
    if args.sheet:
        sc = e6_scored(e6)
        print("wrote", sheet([r for r in sc if r["cls"] == "ally"], OUT / "sheet_465_ally.png"))
        print("wrote", sheet([r for r in sc if r["cls"] == "enemy"], OUT / "sheet_465_enemy.png"))
        print("wrote", sheet(ss, OUT / "sheet_self.png"))
    if args.json:
        args.json.write_text(json.dumps({k: [{kk: vv for kk, vv in r.items() if not kk.startswith("_")}
                                             for r in v] for k, v in dump.items()}, indent=1, default=str),
                             encoding="utf-8")
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
