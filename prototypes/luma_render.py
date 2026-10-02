r"""Ally icons keyed by luma shape and chroma-block colour (E1), and fitted by a fuller render (E2).

    .\.venv\Scripts\python.exe prototypes\luma_render.py e1-run SESSION [--between T0 T1] [--cond 1.0|luma|luma2]
    .\.venv\Scripts\python.exe prototypes\luma_render.py e1-score SESSION [--between T0 T1] [--record]
    .\.venv\Scripts\python.exe prototypes\luma_render.py e1-diff SESSION [--between T0 T1] [--cond luma2]
    .\.venv\Scripts\python.exe prototypes\luma_render.py e1-sheet SESSION --between T0 T1 [--cond luma2]
    .\.venv\Scripts\python.exe prototypes\luma_render.py e1-keys SESSION --at T_MS

Stage 1 of `capture_psf.py` measured the capture's blur: luma is nearly
pixel-sharp (Gaussian sigma about 0.25 native px) and chroma is 4:2:0 in 2x2
blocks aligned to even frame coordinates [domain:capture/chroma-420]. The
ally reader keys the teal rim on HSV hue, saturation and value
(`minimap.ally_mask`), that is on upsampled chroma, so a rim one or two pixels
wide loses its saturation to the floor it shares a chroma block with. Task
`luma-render-20261002` in the store's `notes/predictions.jsonl`.

**E1, the luma-shaped key** (`luma_key`). Each pixel's luma says whether ring
material covers it; each 2x2 chroma block says whether that material is teal.

* Luma. `dY = Y - Y_static` against the baked static
  [domain:capture/session-pixels-are-not-the-map], less a lighting term
  `ell`: the grey opening of `dY` with a disc wider than an icon
  (`LIGHT_K_BASE` base px x map scale), so lit floor larger than an icon
  is background and the icon itself is not. Coverage `l = clip((dY - ell -
  L0) / L1, 0, 1)`. With a 0.25 px PSF a pixel's luma is the box average of
  what covers it (2% leaks to each neighbour), so `l` is per pixel and needs
  no deconvolution; a source with a wider PSF would need one, and the source
  carries its sigma for that reason (`Source`).
* Chroma. On the source's chroma grid (`Source.chroma_block`: 2 for H.264
  4:2:0, 1 for a 4:4:4 source such as a live RGB frame), the block's mean
  `dCr`, `dCb` against the static, unmixed by the block's luma coverage
  `alpha`: the ring's own chroma is `dC_block / max(alpha, A_MIN)`. Teal is
  `Cr` well below the static's with `Cb` near it (the blue death X has high
  `Cb`; green scenery low `Cb`); the soft score `t` ramps over `T_CR`.
* Where the floor is lit to the ring's own luma (light Haven floor), luma
  cannot locate the rim; a weight `w` falls from 1 to 0 as `Y_static + ell`
  nears `Y_RING`, and the shape score there falls back to the teal score:
  `shape = w l + (1 - w) t`.
* Key: one cut, `shape * t >= CUT`. The key replaces the HSV key in the ring
  fit, its coverage gate and the descriptor's exclusion, through a hook
  (`luma_hook`) as `upscale_trial._scaled` hooks the reader;
  `minimap.portrait_key`, which keys an aligned resampled image with no
  static under it, stays on HSV. Nothing else moves.

**E1b, the grown HSV key** (`luma_key_grow`, condition `luma2`), logged as
an amendment after `luma` failed on 223d636bf8d2: unmixing amplified small
`dCr` on lit floor into phantoms. The HSV key stays the seed; only pixels
within `GROW_PX` of it whose luma rises (`l >= 0.5`) and whose raw block
`dCr` falls below `-RAW_CR` join it, so no component starts outside the HSV
key.

The constants were set by eye on calibration slices (223d636bf8d2
1090-1250 s, a06f04a0059f 440-600 s) before any test slice was scored.

**Scoring.** `e1-run` writes the file `upscale_trial.score` reads, under
this task's folder; condition `1.0` is the stored reader rerun there (and
checked against the stored stream), `luma` the hooked one. `e1-score` is
`upscale_trial.score` pointed at this folder. `e1-diff` counts icons one
condition accepts and the other does not, split by the roster (an icon
added on a frame the baseline under-counted is a candidate recovery; on a
frame at or over capacity, a candidate phantom). `e1-sheet` draws 12 of
each way.

Unwired (`"wire": "no"`): a measurement, not a reader.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "2"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import upscale_trial as ut  # noqa: E402
from reticle import geometry, minimap, teardrop  # noqa: E402
from reticle.decode import Sample  # noqa: E402
from reticle.minimap import ally_icon_reader  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from reticle.version import ALLY_ICON_VERSION  # noqa: E402

VERSION = "luma-render-0.1.0"
TASK = "luma-render-20261002"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
CONDITIONS = ("1.0", "luma", "luma2")


# ------------------------------------------------------------------ the source
@dataclass(frozen=True)
class Source:
    """How a frame source blurs: the luma PSF (Gaussian sigma, native px, or
    None when unmeasured) and the chroma grid (block side, aligned to even
    frame coordinates). A per-source parameter, never a constant of the key
    or the render: a recording and a live frame differ here."""

    name: str
    chroma_block: int
    luma_sigma: float | None
    chroma_filter: str          # how the decoder rebuilds full-resolution chroma


#: Stage 1 of `capture_psf.py` on three H.264 sessions.
H264_420 = Source("h264-420", 2, 0.25, "pair-v,121-left-h")
#: A full-RGB frame with no codec (the live pipeline); its PSF is unmeasured.
RGB_444 = Source("rgb-444", 1, None, "none")
SOURCES = {s.name: s for s in (H264_420, RGB_444)}


def source_of(man: dict) -> Source:
    """Every ingested session is an H.264 4:2:0 recording (stage 1)."""
    return H264_420


# ------------------------------------------------------------------ E1 key
LIGHT_K_BASE = 24.0     # lighting opening's disc diameter, base px (2 r_out + 3)
L0, L1 = 12.0, 24.0     # luma coverage ramp over dY - ell, grey levels
Y_RING = 190.0          # the teal ring's luma (calibration: lobe 207, ring 166-185)
W_C = (15.0, 30.0)      # luma informs where Y_RING - background exceeds W_C[0], fully past the sum
A_MIN = 0.25            # least luma coverage a block's chroma is unmixed by
T_CR = (5.0, 10.0)      # teal: unmixed dCr below -T_CR[0], ramped over T_CR[1]
CB_HI, CB_LO, CB_RAMP = 18.0, -25.0, 8.0   # unmixed dCb band (blue X above, green below)
CUT = 0.25              # the one cut: luma evidence x teal (a geometric mean of 0.5)


def ycc(img: np.ndarray) -> np.ndarray:
    """(H, W, 3) float32 Y, Cb, Cr (BT.601 full range), as `capture_psf.ycc`."""
    y = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    return y[..., [0, 2, 1]]


def _block_mean(a: np.ndarray, ox: int, oy: int, b: int) -> np.ndarray:
    """Mean of `a` over the source's chroma blocks, broadcast back per pixel.
    `ox, oy`: frame coordinates of `a[0, 0]`; blocks align to multiples of `b`."""
    if b == 1:
        return a
    h, w = a.shape
    px, py = ox % b, oy % b
    pad = np.pad(a, ((py, (-(h + py)) % b), (px, (-(w + px)) % b)), mode="edge")
    H, W = pad.shape
    m = pad.reshape(H // b, b, W // b, b).mean((1, 3))
    up = np.repeat(np.repeat(m, b, 0), b, 1)
    return up[py:py + h, px:px + w]


def luma_key(crop: np.ndarray, static_ycc: np.ndarray, ox: int, oy: int, ms: float,
             source: Source = H264_420, parts: bool = False):
    """The E1 ally key over `crop` (module docstring). `static_ycc` is the
    baked static in `ycc`, crop-shaped; `ms` the map scale."""
    yc = ycc(crop)
    d = yc - static_ycc
    k = int(round(LIGHT_K_BASE * ms)) | 1
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    ell = cv2.morphologyEx(d[..., 0], cv2.MORPH_OPEN, disc, borderType=cv2.BORDER_REPLICATE)
    lum = np.clip((d[..., 0] - ell - L0) / L1, 0.0, 1.0)
    # Where the background is as bright as the ring, luma cannot see it:
    # w falls to 0 and the chroma block alone decides.
    w = np.clip((Y_RING - (static_ycc[..., 0] + ell) - W_C[0]) / W_C[1], 0.0, 1.0)
    b = source.chroma_block
    alpha = _block_mean(w * lum + (1.0 - w), ox, oy, b)
    a = np.maximum(alpha, A_MIN)
    cr = _block_mean(d[..., 2], ox, oy, b) / a
    cb = _block_mean(d[..., 1], ox, oy, b) / a
    teal = (np.clip((-cr - T_CR[0]) / T_CR[1], 0.0, 1.0)
            * np.clip((CB_HI - cb) / CB_RAMP, 0.0, 1.0)
            * np.clip((cb - CB_LO) / CB_RAMP, 0.0, 1.0))
    shape = w * lum + (1.0 - w) * teal
    key = shape * teal >= CUT
    if parts:
        return key, {"lum": shape, "teal": teal, "ell": ell, "dY": d[..., 0], "dCr": d[..., 2],
                     "w": w}
    return key


#: E1b (amendment, logged after `luma` failed on 223d636bf8d2): hysteresis.
GROW_PX = 2             # the luma rim grows the HSV key by at most this many px
RAW_CR = 6.0            # raw block dCr below -RAW_CR: teal past the floor's chroma noise


def luma_key_grow(crop: np.ndarray, static_ycc: np.ndarray, ox: int, oy: int, ms: float,
                  source: Source = H264_420, parts: bool = False):
    """E1b: the HSV key, grown into luma-located rim pixels. A pixel joins
    when luma says ring material covers it (`lum` >= 0.5, as `luma_key`),
    its chroma block's raw `dCr` lies past the floor's noise (no unmixing,
    so no amplification), and it lies within `GROW_PX` of an HSV-keyed pixel
    in one connected piece with it. Teal confirms the class (the strict
    key); luma places the edge it missed."""
    hsv = _HSV_ALLY(crop)
    yc = ycc(crop)
    d = yc - static_ycc
    k = int(round(LIGHT_K_BASE * ms)) | 1
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    ell = cv2.morphologyEx(d[..., 0], cv2.MORPH_OPEN, disc, borderType=cv2.BORDER_REPLICATE)
    lum = np.clip((d[..., 0] - ell - L0) / L1, 0.0, 1.0)
    cr = _block_mean(d[..., 2], ox, oy, source.chroma_block)
    cb = _block_mean(d[..., 1], ox, oy, source.chroma_block)
    cand = (lum >= 0.5) & (cr <= -RAW_CR) & (cb < CB_HI) & (cb > CB_LO)
    g = 2 * GROW_PX + 1
    near = cv2.dilate(hsv.astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (g, g))) > 0
    both = (hsv | (cand & near)).astype(np.uint8)
    n, lab = cv2.connectedComponents(both, connectivity=8)
    seeded = np.zeros(n, bool)
    seeded[np.unique(lab[hsv])] = True
    seeded[0] = False
    key = seeded[lab]
    if parts:
        return key, {"lum": lum, "teal": (cr <= -RAW_CR).astype(np.float32), "ell": ell,
                     "dY": d[..., 0], "dCr": d[..., 2]}
    return key


_HSV_ALLY = minimap.ally_mask


@contextlib.contextmanager
def luma_hook(static: np.ndarray, ox: int, oy: int, ms: float, source: Source = H264_420,
              keyfn=None):
    """`minimap.ally_mask` is the E1 key for the duration, on crops of the
    reader's box; `minimap.portrait_key` keeps the HSV key it had."""
    hsv_ally, self_mask = minimap.ally_mask, minimap.self_mask
    st = ycc(static)
    memo = {}

    def key(crop):
        if crop.shape[:2] != st.shape[:2]:
            raise ValueError(f"luma key asked on a {crop.shape} crop; the static is {st.shape}")
        # The reader asks twice per frame (fit, then descriptor); compare pixels,
        # not addresses, since a frame buffer may be reused.
        if memo.get("crop") is None or not np.array_equal(memo["crop"], crop):
            memo.update(crop=crop.copy(),
                        key=(keyfn or luma_key)(crop, st, ox, oy, ms, source))
        return memo["key"]

    saved = (minimap.ally_mask, minimap.portrait_key)
    minimap.ally_mask = key
    minimap.portrait_key = lambda img: hsv_ally(img) | self_mask(img)
    try:
        yield {"ally_mask": (keyfn or luma_key).__name__, "portrait_key": "hsv", "source": source.name,
               "map_scale": ms}
    finally:
        minimap.ally_mask, minimap.portrait_key = saved


# ------------------------------------------------------------------ E1 run
def _ms(sid: str) -> float:
    m = geometry.map_scale(geometry.key_of(sid))
    if m is None:
        raise SystemExit(f"{sid}: no map scale; refusing")
    return float(m.scale)


def e1_run(sid: str, cond: str, between=None) -> Path:
    """Condition `1.0` reruns the stored reader (as `upscale_trial run`);
    `luma` reads the same frames under `luma_hook`. Writes the file
    `upscale_trial.score` reads, here."""
    ut.OUT = OUT
    if cond == "1.0":
        return ut.run_condition(sid, "1.0", between)
    from reticle.trial import _ally_rows
    store, man, profile, ctx = ut._session(sid)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no usable minimap crop cache ({why}); not decoding")
    want, stored_idx, src = ut._timeline(store, sid, cache, between, False)
    r = ally_icon_reader(ctx)
    x0, y0, x1, y1 = r.box
    ms = _ms(sid)
    source = source_of(man)
    t0 = time.perf_counter()
    n = 0
    with luma_hook(r.static, x0, y0, ms, source,
                   keyfn=luma_key_grow if cond == "luma2" else luma_key) as hooks:
        for smp in cache.samples(want, rois=("minimap",)):
            idx = int(stored_idx.get(smp.t_ms, smp.frame_idx))
            r.feed(Sample(frame_idx=idx, t_ms=float(smp.t_ms), frame=smp.frame))
            n += 1
        rows = json.loads(json.dumps(_ally_rows(r, sid)["ally_icon"], allow_nan=False))
    frames = [{"t_ms": f["t_ms"], "frame_idx": f["frame_idx"], "widget_drawn": f["widget_drawn"],
               "self": f.get("self")} for f in rows if f["kind"] == "frame"]
    icons = []
    for e in rows:
        if e["kind"] != "icon":
            continue
        pose = e.get("pose") or {}
        icons.append({"t_ms": e["t_ms"], "frame_idx": e["frame_idx"], "cx": e["cx"], "cy": e["cy"],
                      "r": e["r"], "facing": e["facing"], "reason": e["reason"],
                      "family": e.get("family"), "cov": e.get("cov"), "inner": e.get("inner"),
                      "ring": e.get("ring"), "pose_origin": pose.get("origin"),
                      "search": pose.get("search")})
    out = {"version": VERSION, "task": TASK, "session_id": sid, "condition": cond,
           "coords": "pixel_centre", "factor": 1.0, "ally_icon_version": ALLY_ICON_VERSION,
           "hooks": hooks, "constants": {"GROW_PX": GROW_PX, "RAW_CR": RAW_CR,"LIGHT_K_BASE": LIGHT_K_BASE, "L0": L0, "L1": L1,
                                         "Y_RING": Y_RING, "W_C": W_C, "CUT": CUT,
                                         "A_MIN": A_MIN, "T_CR": T_CR, "CB": [CB_LO, CB_HI, CB_RAMP]},
           "timeline": src, "between": between, "labels": False, "asked": len(want),
           "frames": n, "seconds": round(time.perf_counter() - t0, 1),
           "widget_px": [x1 - x0, x1 - x0], "frames_rows": frames, "icons": icons}
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"{int(between[0])}-{int(between[1])}" if between else "all"
    path = OUT / f"{sid}_{tag}_{cond}.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("session_id", "condition", "timeline", "asked", "frames",
                                          "seconds", "hooks")}))
    print(f"wrote {path}")
    return path


def _sfx(cond: str) -> str:
    return "" if cond == "luma" else f"_{cond}"


def _tag(between) -> str:
    return f"{int(between[0])}-{int(between[1])}" if between else "all"


def e1_score(sid: str, between=None) -> dict:
    ut.OUT, ut.CONDITIONS = OUT, CONDITIONS
    res = ut.score(sid, _tag(between))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"score_{sid}_{_tag(between)}.json").write_text(json.dumps(res, indent=1, default=str),
                                                           encoding="utf-8")
    return res


def _pop(sid, between):
    ut.OUT, ut.CONDITIONS = OUT, CONDITIONS
    got = ut._load(sid, _tag(between))
    store = Store(STORE)
    common = set.intersection(*[{f["t_ms"] for f in g["frames_rows"]} for g in got.values()])
    pop = ut._population(store, sid, sorted(common))
    if pop is None:
        drawn = set.intersection(*[{f["t_ms"] for f in g["frames_rows"] if f["widget_drawn"]}
                                   for g in got.values()])
        pop = {t: 0 for t in drawn}
    return got, pop


def e1_diff(sid: str, between=None, hit_px: float = 4.0, cond: str = "luma") -> dict:
    """Icons `luma` accepts and `1.0` does not (added) and the reverse
    (lost), on the score's population, split by the baseline's residual on
    the frame: under capacity (an added icon may be a recovered teammate) or
    at/over capacity (an added icon is a phantom by the roster)."""
    got, pop = _pop(sid, between)
    a, b = got["1.0"], got[cond]
    by = lambda g: {t: [i for i in g["icons"] if i["t_ms"] == t and i["family"] != "barrier"]
                    for t in pop}
    ia, ib = by(a), by(b)
    out = Counter()
    added, lost = [], []
    for t, cap in pop.items():
        ra = len(ia[t]) - cap
        for i in ib[t]:
            if not any(math.hypot(i["cx"] - j["cx"], i["cy"] - j["cy"]) <= hit_px for j in ia[t]):
                k = "added_under" if ra < 0 else "added_at_or_over"
                out[k] += 1
                added.append({**i, "frame_residual_A": ra, "capacity": cap})
        for j in ia[t]:
            if not any(math.hypot(i["cx"] - j["cx"], i["cy"] - j["cy"]) <= hit_px for i in ib[t]):
                k = "lost_over" if ra > 0 else "lost_at_or_under"
                out[k] += 1
                lost.append({**j, "frame_residual_A": ra, "capacity": cap})
    res = {"session_id": sid, "tag": _tag(between), "frames": len(pop), "counts": dict(out),
           "added": added, "lost": lost}
    (OUT / f"diff_{sid}_{_tag(between)}{_sfx(cond)}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({"session_id": sid, "frames": len(pop), "counts": dict(out)}))
    return res


# ------------------------------------------------------------------ E1 pictures
def _panel(crop, cx, cy, half, Z, keys, circles):
    """Window round (cx, cy): the pixels, then each key over grey, at Z x."""
    ix, iy = int(round(cx)), int(round(cy))
    h, w = crop.shape[:2]
    pad = np.zeros((2 * half + 1, 2 * half + 1, 3), np.uint8)
    ya, yb, xa, xb = max(0, iy - half), min(h, iy + half + 1), max(0, ix - half), min(w, ix + half + 1)
    sl = (slice(ya - (iy - half), yb - (iy - half)), slice(xa - (ix - half), xb - (ix - half)))
    pad[sl] = crop[ya:yb, xa:xb]
    tiles = [pad]
    for k in keys:
        g = cv2.cvtColor(cv2.cvtColor(pad, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) // 2
        kk = np.zeros(pad.shape[:2], bool)
        kk[sl] = k[ya:yb, xa:xb]
        g[kk] = (255, 255, 0)
        tiles.append(g)
    out = []
    for t in tiles:
        big = cv2.resize(t, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
        for (x, y, r, col) in circles:
            c = (int((x - ix + half + 0.5) * Z), int((y - iy + half + 0.5) * Z))
            cv2.circle(big, c, int(r * Z), col, 1)
            cv2.circle(big, c, 3, col, -1)
        out.append(big)
    return np.hstack([cv2.copyMakeBorder(o, 0, 0, 0, 3, cv2.BORDER_CONSTANT, value=(40, 40, 40))
                      for o in out])


def e1_sheet(sid: str, between=None, n: int = 12, seed: int = 7, cond: str = "luma") -> list[Path]:
    """Twelve added and twelve lost icons (fixed seed): pixels, HSV key, E1
    key, with the condition's posed centre and ring radius (added: yellow;
    lost: magenta)."""
    d = json.loads((OUT / f"diff_{sid}_{_tag(between)}{_sfx(cond)}.json").read_text(encoding="utf-8"))
    store, man, profile, ctx = ut._session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    rd = ally_icon_reader(ctx)
    x0, y0, x1, y1 = rd.box
    st = ycc(rd.static)
    ms = _ms(sid)
    half = int(math.ceil(teardrop.ICON_CLASSES["ally"].L * ms + 4))
    Z = max(6, int(round(8 / ms)))
    rng = np.random.default_rng(seed)
    paths = []
    for side in ("added", "lost"):
        rows = d[side]
        if not rows:
            continue
        pick = sorted((rows[int(i)] for i in rng.choice(len(rows), min(n, len(rows)), replace=False)),
                      key=lambda r: r["t_ms"])
        tiles = []
        for r in pick:
            smp = next(cache.samples([r["t_ms"]], rois=("minimap",)))
            crop = smp.frame[y0:y1, x0:x1]
            hsv = minimap.ally_mask(crop) & rd.floor
            lk = (luma_key_grow if cond == "luma2" else luma_key)(crop, st, x0, y0, ms) & rd.floor
            col = (0, 255, 255) if side == "added" else (255, 0, 255)
            row = _panel(crop, r["cx"], r["cy"], half, Z, [hsv, lk], [(r["cx"], r["cy"], r["r"], col)])
            cv2.putText(row, f"{r['t_ms'] / 1000:.2f}s res_A {r['frame_residual_A']:+d} cap "
                        f"{r['capacity']}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            tiles.append(row)
        w = max(t.shape[1] for t in tiles)
        sheet = np.vstack([cv2.copyMakeBorder(t, 0, 3, 0, w - t.shape[1], cv2.BORDER_CONSTANT)
                           for t in tiles])
        p = OUT / f"e1_sheet_{side}_{sid}_{_tag(between)}{_sfx(cond)}.png"
        cv2.imwrite(str(p), sheet)
        print(f"wrote {p}")
        paths.append(p)
    return paths


def e1_keys(sid: str, t_ms: float, near=None) -> Path:
    """One whole widget at `t_ms` (or a 60 px window round `near`, at 6x):
    pixels, HSV key, E1 key, luma coverage, teal score, lighting term
    (display only)."""
    store, man, profile, ctx = ut._session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    held = cache.holds()
    t = held[min(range(len(held)), key=lambda i: abs(held[i] - t_ms))]
    rd = ally_icon_reader(ctx)
    x0, y0, x1, y1 = rd.box
    smp = next(cache.samples([t], rois=("minimap",)))
    crop = smp.frame[y0:y1, x0:x1]
    key, p = luma_key(crop, ycc(rd.static), x0, y0, _ms(sid), parts=True)
    g = lambda m: cv2.cvtColor((np.clip(m, 0, 1) * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    hsv = minimap.ally_mask(crop) & rd.floor
    tiles = [crop, g(hsv), g(key & rd.floor), g(p["lum"]), g(p["teal"]),
             g((p["ell"] + 64) / 128)]
    z = 1.5
    if near is not None:
        x, y = int(near[0]), int(near[1])
        tiles = [t[max(0, y - 30):y + 30, max(0, x - 30):x + 30] for t in tiles]
        tiles = [cv2.copyMakeBorder(t, 0, 0, 0, 1, cv2.BORDER_CONSTANT, value=(0, 0, 255))
                 for t in tiles]
        z = 6
    top, bot = np.hstack(tiles[:3]), np.hstack(tiles[3:])
    img = cv2.resize(np.vstack([top, bot]), None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"e1_keys_{sid}_{int(t)}{'' if near is None else f'_{int(near[0])}_{int(near[1])}'}.png"
    cv2.imwrite(str(path), img)
    print(f"wrote {path}")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("e1-run", "e1-score", "e1-diff", "e1-sheet"):
        a = sub.add_parser(name)
        a.add_argument("session")
        a.add_argument("--between", nargs=2, type=float, help="seconds")
        if name in ("e1-run", "e1-diff", "e1-sheet"):
            a.add_argument("--cond", choices=CONDITIONS, default="luma")
        if name == "e1-score":
            a.add_argument("--record", action="store_true")
    k = sub.add_parser("e1-keys")
    k.add_argument("session")
    k.add_argument("--at", type=float, required=True)
    k.add_argument("--near", nargs=2, type=float)
    args = ap.parse_args(argv)
    ut._idle()
    if args.cmd == "e1-run":
        e1_run(args.session, args.cond, args.between)
    elif args.cmd == "e1-score":
        res = e1_score(args.session, args.between)
        print(json.dumps(res, indent=1, default=str))
        if args.record:
            _record_e1(res)
    elif args.cmd == "e1-diff":
        e1_diff(args.session, args.between, cond=args.cond)
    elif args.cmd == "e1-sheet":
        e1_sheet(args.session, args.between, cond=args.cond)
    elif args.cmd == "e1-keys":
        e1_keys(args.session, args.at, args.near)
    return 0


def _record_e1(res: dict) -> None:
    """One metrics row per E1 score: series `luma_render/e1`."""
    from reticle import metrics
    values = {}
    for cond, m in res["conditions"].items():
        c = cond.replace(".", "p")
        for key in ("n", "mae", "mean_residual", "exact", "under", "over"):
            if key in m:
                values[f"{key}_{c}"] = m[key]
    for cond, d in res.get("vs_A", {}).items():
        c = cond.replace(".", "p")
        values[f"d_mae_{c}"], values[f"d_mae_lo_{c}"], values[f"d_mae_hi_{c}"] = d["d_mae"]
        values[f"noise_bound_mae_{c}"] = d["noise_bound_mae"]
        values[f"frames_differ_{c}"] = d["frames_differ"]
    metrics.record("luma_render", part="e1", session=res["session_id"], values=values,
                   deps={"version": VERSION, "ally_icon_version": ALLY_ICON_VERSION},
                   context={"tag": res.get("tag"), "basis": res.get("basis")},
                   note=f"task {TASK}; files analysis/{TASK}/")


if __name__ == "__main__":
    raise SystemExit(main())
