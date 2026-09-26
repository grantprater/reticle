"""Minimap ally portrait features, and references rendered from the game's art.

A teammate's minimap icon is a portrait about 12 native pixels across. Its
agent shows in the portrait's colour layout and in the orientation of its
edges, so each icon is described by three hand-defined feature families on
one aligned crop:

* `grid3_lab` -- mean Lab colour of a 3x3 grid over the portrait disc (27);
* `hog_x1` -- edge-orientation histograms (8 bins, four quadrants) of the
  lightness at about one native pixel per pixel, unit-normalised (32);
* `prof_h` -- mean Lab colour of six vertical bands, left to right (18).

The aligned crop is the icon's 41 px window resampled so its fitted centre is
the middle pixel and a 331 px widget maps at 2x (`W_REF`, `UPS`): both widget
sizes land on one scale. The disc is 0.75 of `DISC_R` about the centre, less
the reader's teal and self key pixels, which the caller passes as `keyed`.
Portraits are drawn upright whatever the icon faces, so nothing rotates.

References come from `<store>/reference/assets/agents/<Agent>_minimap_portrait.png`:
the art is shrunk to icon size, laid over the mean disc colour, blurred,
upsampled as a crop is, colour-mapped to game colour by an affine Lab map,
and described by the same function (`render`, `render_reference`). The render
parameters, the colour map and the per-feature variances are a CALIBRATION
fitted on automatic death bindings across the corpus
(`prototypes/ally_portrait_calibration.py`), stored beside the table with
its provenance. `build_references` bakes the table; nothing here reads a
session's pixels, and no session defines a reference.

This DESCRIBES. `adjudication.identity` names.

Owns [owns:ally-portrait-features].
Measured by `minimap-feature-bank` and `ally-icon-rendered-art` in the
store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

RAW = 41                 # raw window side, centred on the rounded icon centre
SIDE = 37                # aligned crop side
SIDE1 = SIDE // 2 + 1    # the aligned crop at about one native pixel
W_REF, UPS = 331, 2.0    # a W_REF px widget maps at UPS x
#: The median fitted icon radius in aligned pixels over 10521 icons of 19
#: sessions (`minimap-feature-bank`); a fixed disc, not the icon's own `r`.
DISC_R = 12.0
FAMILIES = ("grid3_lab", "hog_x1", "prof_h")
REFERENCE_DIR = ("reference", "ally_portrait")
CALIBRATION_FILE = "calibration.json"
REFERENCES_FILE = "references.json"


def align_icon(crop: np.ndarray, cx: float, cy: float, width: int | None = None) -> np.ndarray:
    """The icon's window from the widget crop, resampled: fitted centre at the
    middle pixel, scale `UPS * W_REF / width`. Outside the crop is black."""
    width = crop.shape[1] if width is None else width
    h = RAW // 2
    ix, iy = int(round(cx)), int(round(cy))
    raw = np.zeros((RAW, RAW, 3), crop.dtype)
    y0, x0 = iy - h, ix - h
    sy0, sx0 = max(0, y0), max(0, x0)
    sy1, sx1 = min(crop.shape[0], y0 + RAW), min(crop.shape[1], x0 + RAW)
    if sy1 > sy0 and sx1 > sx0:
        raw[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = crop[sy0:sy1, sx0:sx1]
    c = RAW // 2
    dx, dy = cx - ix, cy - iy
    m = cv2.getRotationMatrix2D((c + dx, c + dy), 0.0, UPS * W_REF / width)
    m[0, 2] += (SIDE - 1) / 2 - (c + dx)
    m[1, 2] += (SIDE - 1) / 2 - (c + dy)
    return cv2.warpAffine(raw, m, (SIDE, SIDE), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT)


def _regions(side: int, R: float) -> dict:
    yy, xx = np.mgrid[:side, :side]
    c = (side - 1) / 2
    disc = np.hypot(xx - c, yy - c) <= 0.75 * R
    return {"disc": disc, "c": c, "R": R, "yy": yy, "xx": xx}


_REG = {}


def _region(side: int, R: float) -> dict:
    key = (side, R)
    if key not in _REG:
        _REG[key] = _regions(side, R)
    return _REG[key]


def _unkeyed(mask, keyed):
    m = mask & ~keyed
    return m if m.sum() >= 4 else mask


def _grid(F, rg, m, n):
    c, R = rg["c"], rg["R"]
    by = np.clip(((rg["yy"] - (c - 0.75 * R)) / (1.5 * R) * n).astype(int), 0, n - 1)
    bx = np.clip(((rg["xx"] - (c - 0.75 * R)) / (1.5 * R) * n).astype(int), 0, n - 1)
    base = F[m].mean(0)
    out = []
    for i in range(n):
        for j in range(n):
            cell = m & (by == i) & (bx == j)
            out.append(F[cell].mean(0) if cell.any() else base)
    return np.concatenate(out)


def _profile_h(L, rg, m, n=6):
    c, R = rg["c"], rg["R"]
    band = np.clip(((rg["xx"] - (c - 0.75 * R)) / (1.5 * R) * n).astype(int), 0, n - 1)
    base = L[m].mean(0)
    return np.concatenate([L[m & (band == b)].mean(0) if (m & (band == b)).any() else base
                           for b in range(n)])


def _hog(L, rg, m, bins=8):
    g = L[..., 0]
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag, ang = np.hypot(gx, gy), np.arctan2(gy, gx)
    b = ((ang + np.pi) / (2 * np.pi) * bins).astype(int) % bins
    c, yy, xx = rg["c"], rg["yy"], rg["xx"]
    out = []
    for qy in (yy < c, yy >= c):
        for qx in (xx < c, xx >= c):
            mm = m & qy & qx
            out.append(np.bincount(b[mm], weights=mag[mm], minlength=bins))
    v = np.concatenate(out)
    return v / max(np.linalg.norm(v), 1e-6)


def portrait_features(img: np.ndarray, keyed: np.ndarray) -> dict[str, np.ndarray]:
    """The three families of one aligned icon (BGR uint8, `SIDE` square);
    `keyed` marks the reader's teal and self key pixels on it."""
    rg = _region(img.shape[0], DISC_R)
    L = cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float32)
    disc = _unkeyed(rg["disc"], keyed)
    s1 = cv2.resize(img, (SIDE1, SIDE1), interpolation=cv2.INTER_AREA)
    k1 = cv2.resize(keyed.astype(np.uint8) * 255, (SIDE1, SIDE1),
                    interpolation=cv2.INTER_AREA) > 64
    rg1 = _region(SIDE1, DISC_R * SIDE1 / img.shape[0])
    L1 = cv2.cvtColor(s1, cv2.COLOR_BGR2Lab).astype(np.float32)
    f = {"grid3_lab": _grid(L, rg, disc, 3),
         "hog_x1": _hog(L1, rg1, _unkeyed(rg1["disc"], k1)),
         "prof_h": _profile_h(L, rg, disc)}
    return {k: np.asarray(v, np.float32) for k, v in f.items()}


def stored(feats: dict[str, np.ndarray]) -> dict[str, list[float]]:
    """JSON form: each family rounded to four decimals."""
    return {k: [round(float(v), 4) for v in feats[k]] for k in FAMILIES}


# ---------------------------------------------------------------- references

def render(art: np.ndarray, q: float, sigma: float, dy: float, bg) -> np.ndarray:
    """Art (BGRA, 64 px) shrunk to native size (`q` aligned px per art px,
    halved), laid over `bg`, blurred by `sigma` native px, upsampled 2x as
    crops are, and shifted `dy` aligned px."""
    art = art.astype(np.float32)
    n = max(4, int(round(art.shape[0] * q / 2)))
    a = cv2.resize(art[..., 3] / 255.0, (n, n), interpolation=cv2.INTER_AREA)
    rgb = cv2.resize(art[..., :3] * (art[..., 3:] / 255.0), (n, n),
                     interpolation=cv2.INTER_AREA)
    canvas = np.tile(np.asarray(bg, np.float32), (SIDE1, SIDE1, 1))
    o = (SIDE1 - n) // 2
    lo, hi = max(0, -o), min(n, SIDE1 - o)
    sl = slice(o + lo, o + hi)
    canvas[sl, sl] = rgb[lo:hi, lo:hi] + canvas[sl, sl] * (1 - a[lo:hi, lo:hi, None])
    if sigma > 0:
        canvas = cv2.GaussianBlur(canvas, (0, 0), sigma)
    c1, c2 = (SIDE1 - 1) / 2, (SIDE - 1) / 2
    shift = (o + n / 2 - 0.5) - c1
    m = np.float32([[2, 0, c2 - 2 * (c1 + shift)], [0, 2, c2 - 2 * (c1 + shift) + dy]])
    out = cv2.warpAffine(canvas, m, (SIDE, SIDE), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    return np.clip(out, 0, 255).astype(np.uint8)


def render_reference(art: np.ndarray, cal: dict) -> np.ndarray:
    """`render` under the calibration, then its affine Lab colour map."""
    img = render(art, cal["q"], cal["sigma"], cal["dy"], cal["bg"])
    L = cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)
    L = np.c_[L, np.ones(len(L))] @ np.asarray(cal["W"], np.float64)
    L = np.clip(L, 0, 255).astype(np.uint8).reshape(SIDE, SIDE, 3)
    return cv2.cvtColor(L, cv2.COLOR_Lab2BGR)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_references(root, key_mask) -> dict:
    """Render every agent's minimap portrait art under the stored calibration
    and write the reference table. `key_mask(img)` is the reader's key
    (`minimap.portrait_key`), passed in so the same pixels are excluded."""
    from .version import ALLY_PORTRAIT_FEATURES_VERSION, ALLY_PORTRAIT_REFS_VERSION

    root = Path(root)
    out_dir = root.joinpath(*REFERENCE_DIR)
    cal_path = out_dir / CALIBRATION_FILE
    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    if cal.get("features_version") != ALLY_PORTRAIT_FEATURES_VERSION:
        raise ValueError(f"calibration was fitted on features "
                         f"{cal.get('features_version')}, not {ALLY_PORTRAIT_FEATURES_VERSION}")
    art_dir = root / "reference" / "assets" / "agents"
    agents, sources = {}, {}
    for p in sorted(art_dir.glob("*_minimap_portrait.png")):
        name = p.stem[:-len("_minimap_portrait")]
        art = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if art is None or art.ndim != 3 or art.shape[2] != 4:
            continue
        img = render_reference(art, cal)
        agents[name] = stored(portrait_features(img, key_mask(img)))
        sources[p.name] = _digest(p)
    table = {"version": ALLY_PORTRAIT_REFS_VERSION,
             "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
             "calibration": {"file": CALIBRATION_FILE, "sha": _digest(cal_path),
                             "version": cal.get("version"),
                             "provenance": cal.get("provenance")},
             "sources": sources,
             "margin_min": float(cal["margin_min"]),
             "variance": {f: [float(v) for v in np.asarray(cal["var"][f]) +
                              np.asarray(cal["gap"][f])] for f in FAMILIES},
             "agents": agents}
    (out_dir / REFERENCES_FILE).write_text(json.dumps(table, indent=1), encoding="utf-8")
    return table


def load_references(root) -> dict | None:
    """The baked table, or None when it was never built."""
    p = Path(root).joinpath(*REFERENCE_DIR, REFERENCES_FILE)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
