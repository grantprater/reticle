r"""The capture chain's blur on the minimap, measured on the baked map's walls.

    .\.venv\Scripts\python.exe prototypes\capture_psf.py measure SESSION [--frames N]
    .\.venv\Scripts\python.exe prototypes\capture_psf.py compare SESSION [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\capture_psf.py plot SESSION [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\capture_psf.py icons SESSION --between T0 T1
    .\.venv\Scripts\python.exe prototypes\capture_psf.py icon-score --calib S:T0-T1 ... --test S:T0-T1 ...
    .\.venv\Scripts\python.exe prototypes\capture_psf.py icon-sheet SESSION --between T0 T1 [--n N]
    .\.venv\Scripts\python.exe prototypes\capture_psf.py record SESSION [SESSION ...]

The player's hypothesis: every minimap element passes through one nearly
fixed blur -- the game's anti-aliased draw, OBS's downscale, 4:2:0 chroma
subsampling [domain:capture/chroma-420] and H.264 -- and a render-and-compare
fit through that blur recovers an icon at sub-pixel precision. This script
measures the blur (stage 1). Task `capture-psf-20261001` in the store's
`notes/predictions.jsonl`, which states the selection rule and predictions
before any measurement.

**Where the edges come from.** The key's baked static only
[domain:capture/session-pixels-are-not-the-map]: axis-aligned bright wall
lines (`find_chunks`), cut into 8 px chunks, with opaque map on both sides
(baked `labels` not VOID) and flat plateaus in the static. The capture
supplies only the blurred profile across each chunk.

**Which frames.** Cached minimap frames (crop cache, no decode) at a fixed
stride over the whole cache. A (chunk, frame) pair counts only if its plateau
pixels, 3 px or more from the ridge, match the baked static (mean |dY| <= 4,
max <= 12); the transition pixels are never gated, so a different blur
cannot be selected away.

**The model** (`fit_profiles`). Each profile is three flat levels (side,
line, side) with edges e1 < e2, seen through a Gaussian PSF of total sigma in
native px (the pixel aperture included). The levels are linear and solved in
closed form; e1, e2 and sigma are searched on a grid, then refined to 0.01 px,
as `reticle/teardrop.py` refines its soft-edged render. Luma is BT.601 Y
(OpenCV's YCrCb; the decoder's conversion is BT.601, since Cb stays constant
across a luma step inside a chroma block).

**Chroma.** Fitted the same way where the plateaus differ in Cb or Cr by 6
or more, and against explicit 4:2:0 models (`chroma_block_rss`): the luma
PSF, then a chroma sample per 2-pixel pair aligned to even FRAME coordinates
(a box mean, or a left-sited [1 2 1]/4 filter), then nearest duplication; an
odd-aligned pair is the control. `block_test` counts 2x2 blocks whose four
chroma values agree.

**Stage 2: ally icons through the PSF** (`IconBatch`, `fit_batch`). The
ally teardrop of `teardrop.ICON_CLASSES['ally']` times `geometry.map_scale`
(the one scale transform) times a free scale s, at each stored ally_icon
detection (`ally-icon-0.7.0`). Five layers per channel: ring and lobe,
portrait disc, a one-pixel rim outside the teardrop (added after the first
sheet; see the amendment record), background (the baked static times a gain)
and a constant. Luma coverage passes through the stage-1 PSF as a 1.13 px
ramp; chroma through the same plus 4:2:0. Colours are solved linearly; centre,
s and facing by grid, then compass refine. `icon-score` scores the fit as a
verifier of the stored stream (`upscale_trial`'s roster score) and its centre
jitter on stationary icons; `record` writes the metrics rows the doc cites.

No reader stamp moves; every command writes under
`analysis/capture-psf-20261001/`.
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "2")

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, teardrop  # noqa: E402
from reticle.minimap import VOID, minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

VERSION = "capture-psf-0.1.0"
TASK = "capture-psf-20261001"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK

R = 5                     # profile half-width, px
CHUNK = 8                 # chunk length along the line, px
RIDGE_MIN = 30.0          # line above both plateaus (at +-4 px) by this much luma
SECOND_RIDGE = 20.0       # no second ridge this strong within 2..R px
FLAT_MAX = 4.0            # |Y(+-5) - Y(+-3)| in the static
OPAQUE_PX = 6             # baked labels not VOID within this many px of the ridge
GATE_MEAN, GATE_MAX = 4.0, 12.0   # plateau pixels against the static
PLATEAU_PX = 3            # plateau = samples this far or farther from the ridge
CHROMA_STEP = 6.0         # chroma plateaus differ by this much to fit chroma
FRAMES = 500
PER_FRAME_EVERY = 10      # every Nth used frame keeps per-frame profiles


def _idle() -> None:
    cv2.setNumThreads(2)
    try:
        import torch
        torch.set_num_threads(2)
    except Exception:
        pass
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    except Exception:
        pass


def ycc(img: np.ndarray) -> np.ndarray:
    """(H, W, 3) float32: Y, Cb, Cr (BT.601 full range, OpenCV's YCrCb reordered)."""
    y = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    return y[..., [0, 2, 1]]


# ------------------------------------------------------------------ edges
def find_chunks(static: np.ndarray, labels: np.ndarray) -> list[dict]:
    """Axis-aligned bright-line chunks in the baked static (module docstring).

    'v' chunks are vertical lines at column c over rows a0..a1-1, profiled
    along x; 'h' chunks are horizontal lines at row c, profiled along y."""
    Y = ycc(static)[..., 0]
    out = []
    for orient in ("v", "h"):
        A = Y if orient == "v" else Y.T
        L = labels if orient == "v" else labels.T
        n_run, n_c = A.shape            # rows along the line, columns across
        ridge = np.zeros_like(A, dtype=bool)
        core = A[:, R:n_c - R]
        left4, right4 = A[:, R - 4:n_c - R - 4], A[:, R + 4:n_c - R + 4]
        lm1, rp1 = A[:, R - 1:n_c - R - 1], A[:, R + 1:n_c - R + 1]
        ok = (core >= lm1) & (core > rp1) & (core - np.maximum(left4, right4) >= RIDGE_MIN)
        ridge[:, R:n_c - R] = ok
        weak = np.zeros_like(ridge)
        weak[:, R:n_c - R] = ((core >= lm1) & (core > rp1)
                              & (core - np.maximum(left4, right4) >= SECOND_RIDGE))
        for c in range(R + 1, n_c - R - 1):
            col = ridge[:, c]
            r = 0
            while r < n_run:
                if not col[r]:
                    r += 1
                    continue
                s = r
                while r < n_run and col[r]:
                    r += 1
                e = r                       # run s..e-1
                if e - s < 10:
                    continue
                a = s + 1
                while a + CHUNK <= e - 1:
                    rows = slice(a, a + CHUNK)
                    win = A[rows, c - R:c + R + 1]
                    lab = L[rows, c - OPAQUE_PX:c + OPAQUE_PX + 1]
                    others = weak[rows, c - R:c + R + 1].copy()
                    others[:, R - 1:R + 2] = False
                    flat_l = abs(float(win[:, 0].mean() - win[:, 2].mean()))
                    flat_r = abs(float(win[:, -1].mean() - win[:, -3].mean()))
                    if (lab != VOID).all() and not others.any() and flat_l <= FLAT_MAX \
                            and flat_r <= FLAT_MAX:
                        out.append({"orient": orient, "c": int(c), "a0": int(a), "a1": int(a + CHUNK)})
                    a += CHUNK
    return out


def window(img: np.ndarray, ch: dict) -> np.ndarray:
    """(CHUNK, 2R+1, C) samples of a chunk: along the line by across it."""
    c, a0, a1 = ch["c"], ch["a0"], ch["a1"]
    if ch["orient"] == "v":
        return img[a0:a1, c - R:c + R + 1]
    return np.swapaxes(img[c - R:c + R + 1, a0:a1], 0, 1)


# ------------------------------------------------------------------ fit
I_POS = np.arange(-R, R + 1, dtype=np.float64)


def _phi(x):
    import torch
    return 0.5 * (1.0 + torch.erf(x / math.sqrt(2.0)))


def _esf(d, sg, form: str):
    """The PSF's edge-spread function at signed distance d (px) for width sg.

    `gauss`: a Gaussian of total sigma sg. `boxgauss`: a one-pixel box (the
    pixel's own aperture, as area sampling makes it) convolved with a
    Gaussian of sigma sg; at sg -> 0 it is a linear ramp over one pixel."""
    import torch
    if form == "gauss":
        return _phi(d / sg)

    def g(u):
        z = u / sg
        return u * _phi(z) + sg * torch.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return g(d + 0.5) - g(d - 0.5)


def fit_profiles(P: np.ndarray, device=None, form: str = "gauss") -> dict:
    """Fit three levels through a Gaussian PSF to each row of P (N, 2R+1).

    Returns arrays e1, e2, sigma, levels (N, 3), rss, rmse. The grid covers
    e1 in [-2.5, 1.5], width e2 - e1 in [0.1, 3.5] and sigma in [0.05, 1.6]
    at 0.1 / 0.1 / 0.05 px, then a 0.01 px grid +-0.1 round the best."""
    import torch
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    Pt = torch.as_tensor(P, dtype=torch.float64, device=dev)
    N = Pt.shape[0]
    xs = torch.as_tensor(I_POS, device=dev)

    def rss_for(e1, w, sg, Psub):
        # e1, w, sg: (K,) or (N, K); returns rss (N, K) and levels.
        e2 = e1 + w
        p1 = _esf(xs - e1[..., None], sg[..., None], form)
        p2 = _esf(xs - e2[..., None], sg[..., None], form)
        X = torch.stack([1 - p1, p1 - p2, p2], dim=-1)          # (..., 11, 3)
        XtX = X.transpose(-1, -2) @ X + 1e-9 * torch.eye(3, device=dev, dtype=X.dtype)
        H = X @ torch.linalg.solve(XtX, X.transpose(-1, -2))   # (..., 11, 11)
        if H.dim() == 3:                                         # shared grid
            fit = torch.einsum("kij,nj->nki", H, Psub)
            res = Psub[:, None, :] - fit
        else:
            fit = torch.einsum("nkij,nj->nki", H, Psub)
            res = Psub[:, None, :] - fit
        return (res * res).sum(-1)

    g1 = torch.arange(-2.5, 1.5001, 0.1, device=dev, dtype=torch.float64)
    gw = torch.arange(0.1, 3.5001, 0.1, device=dev, dtype=torch.float64)
    gs = torch.arange(0.05, 1.6001, 0.05, device=dev, dtype=torch.float64)
    if form == "boxgauss":
        gs = torch.cat([torch.tensor([0.02], device=dev, dtype=torch.float64), gs])
    E1, W, S = torch.meshgrid(g1, gw, gs, indexing="ij")
    E1, W, S = E1.flatten(), W.flatten(), S.flatten()
    best = torch.full((N,), float("inf"), device=dev, dtype=torch.float64)
    arg = torch.zeros((N,), dtype=torch.long, device=dev)
    KB = 4096
    for nb in range(0, N, 256):
        Ps = Pt[nb:nb + 256]
        for kb in range(0, E1.numel(), KB):
            r = rss_for(E1[kb:kb + KB], W[kb:kb + KB], S[kb:kb + KB], Ps)
            v, j = r.min(1)
            upd = v < best[nb:nb + 256]
            best[nb:nb + 256] = torch.where(upd, v, best[nb:nb + 256])
            arg[nb:nb + 256] = torch.where(upd, j + kb, arg[nb:nb + 256])
    e1, w, sg = E1[arg], W[arg], S[arg]
    # Fine: 0.01 px +-0.1 in each dimension, per profile.
    d = torch.arange(-0.1, 0.1001, 0.01, device=dev, dtype=torch.float64)
    D1, DW, DS = torch.meshgrid(d, d, d, indexing="ij")
    D1, DW, DS = D1.flatten(), DW.flatten(), DS.flatten()
    out_e1, out_w, out_s, out_rss = [], [], [], []
    for nb in range(0, N, 64):
        Ps = Pt[nb:nb + 64]
        fe1 = e1[nb:nb + 64, None] + D1[None]
        fw = (w[nb:nb + 64, None] + DW[None]).clamp(min=0.02)
        fs = (sg[nb:nb + 64, None] + DS[None]).clamp(min=0.02)
        r = rss_for(fe1, fw, fs, Ps)
        v, j = r.min(1)
        ar = torch.arange(Ps.shape[0], device=dev)
        out_e1.append(fe1[ar, j]); out_w.append(fw[ar, j]); out_s.append(fs[ar, j]); out_rss.append(v)
    e1 = torch.cat(out_e1); w = torch.cat(out_w); sg = torch.cat(out_s); rss = torch.cat(out_rss)
    # Levels at the optimum.
    e2 = e1 + w
    p1 = _esf(xs - e1[:, None], sg[:, None], form)
    p2 = _esf(xs - e2[:, None], sg[:, None], form)
    X = torch.stack([1 - p1, p1 - p2, p2], dim=-1)
    lev = torch.linalg.lstsq(X, Pt[..., None]).solution[..., 0]
    model = (X @ lev[..., None])[..., 0]
    return {"e1": e1.cpu().numpy(), "e2": e2.cpu().numpy(), "sigma": sg.cpu().numpy(),
            "levels": lev.cpu().numpy(), "rss": rss.cpu().numpy(),
            "rmse": np.sqrt(rss.cpu().numpy() / P.shape[1]), "model": model.cpu().numpy()}


def fit_step(P: np.ndarray, device=None) -> dict:
    """One step (two levels) through a Gaussian to each row of P (N, 2R+1):
    the chroma's effective width, averaged over the pair phases. The three-
    level model can spend its middle level on a half-way chroma pair and so
    reads a 4:2:0 staircase as two sharp steps; this one cannot."""
    import torch
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    Pt = torch.as_tensor(P, dtype=torch.float64, device=dev)
    xs = torch.as_tensor(I_POS, device=dev)
    ge = torch.arange(-3.0, 3.0001, 0.02, device=dev, dtype=torch.float64)
    gs = torch.arange(0.05, 2.5001, 0.02, device=dev, dtype=torch.float64)
    E, S = torch.meshgrid(ge, gs, indexing="ij")
    E, S = E.flatten(), S.flatten()
    p = _phi((xs - E[:, None]) / S[:, None])
    X = torch.stack([1 - p, p], -1)                                       # (K, 11, 2)
    XtX = X.transpose(-1, -2) @ X + 1e-9 * torch.eye(2, device=dev, dtype=X.dtype)
    H = X @ torch.linalg.solve(XtX, X.transpose(-1, -2))
    res = Pt[:, None, :] - torch.einsum("kij,nj->nki", H, Pt)
    rss = (res * res).sum(-1)
    v, j = rss.min(1)
    return {"e": E[j].cpu().numpy(), "sigma": S[j].cpu().numpy(),
            "rmse": np.sqrt(v.cpu().numpy() / P.shape[1])}


def _blurred_basis(e1, e2, sigma, xs):
    """Unit-level basis (len(xs), 3) of the three-level profile through the PSF."""
    from math import erf, sqrt
    ph = np.vectorize(lambda t: 0.5 * (1 + erf(t / sqrt(2))))
    p1, p2 = ph((xs - e1) / sigma), ph((xs - e2) / sigma)
    return np.stack([1 - p1, p1 - p2, p2], axis=-1)


def chroma_block_rss(prof: np.ndarray, e1: float, e2: float, sigma: float, x0_frame: int) -> dict:
    """RSS of a chroma profile (2R+1,) under explicit 4:2:0 models.

    The full-resolution chroma is the luma PSF's three-level profile with
    free levels; each model then makes one chroma sample per pixel pair and
    duplicates it. `x0_frame` is the frame coordinate of sample i = 0 along
    the profile. Models: `box_even` (mean of the pair aligned to even frame
    coordinates), `sited_even` ([1 2 1]/4 centred on the even pixel),
    `box_odd` (pairs aligned to odd coordinates, the control), and `none`
    (no subsampling: the luma PSF alone)."""
    xs_ext = np.arange(-R - 2, R + 3, dtype=np.float64)
    B = _blurred_basis(e1, e2, sigma, xs_ext)                   # (2R+5, 3)
    idx = {int(x): k for k, x in enumerate(xs_ext)}
    res = {}
    for name in ("box_even", "sited_even", "box_odd", "none"):
        rows = []
        for i in range(-R, R + 1):
            xf = x0_frame + i
            if name == "none":
                rows.append(B[idx[i]])
                continue
            par = 0 if name.endswith("even") else 1
            lead = i - ((xf - par) % 2)                          # first pixel of its pair
            if name.startswith("box"):
                rows.append(0.5 * (B[idx[lead]] + B[idx[lead + 1]]))
            else:
                rows.append(0.25 * B[idx[lead - 1]] + 0.5 * B[idx[lead]] + 0.25 * B[idx[lead + 1]])
        X = np.array(rows)
        lev, *_ = np.linalg.lstsq(X, prof, rcond=None)
        r = prof - X @ lev
        res[name] = float((r * r).sum())
    return res


# ------------------------------------------------------------------ measure
def _session(sid: str):
    store = Store(STORE)
    man = json.loads((store.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    profile = get_profile(man["source_profile"])
    return store, man, profile


def block_test(yc: np.ndarray, opaque: np.ndarray, ox: int, oy: int) -> dict:
    """Share of 2x2 chroma blocks with Cb and Cr range <= 2, among blocks
    whose 4x4 neighbourhood has a chroma range >= 6 (`ox`, `oy`: frame
    coordinates of the crop's origin). Alignments are frame parities."""
    out = {}
    H, W = yc.shape[:2]
    for name, (px, py) in {"aligned": (0, 0), "off_x": (1, 0), "off_y": (0, 1), "off_xy": (1, 1)}.items():
        sx = (px - ox) % 2
        sy = (py - oy) % 2
        hh, ww = (H - sy - 2) // 2, (W - sx - 2) // 2
        C = yc[sy:sy + 2 * hh, sx:sx + 2 * ww, 1:3]
        blk = C.reshape(hh, 2, ww, 2, 2)
        rng = (blk.max(axis=(1, 3)) - blk.min(axis=(1, 3))).max(-1)        # (hh, ww)
        # 4x4 neighbourhood: the block and a 1 px ring (offsets -1..+2).
        k4 = np.ones((4, 4), np.uint8)
        nrng = np.zeros((H, W), np.float32)
        for ci in (1, 2):
            ch = np.ascontiguousarray(yc[..., ci])
            hi = cv2.dilate(ch, k4, anchor=(1, 1), borderType=cv2.BORDER_REPLICATE)
            lo = cv2.erode(ch, k4, anchor=(1, 1), borderType=cv2.BORDER_REPLICATE)
            nrng = np.maximum(nrng, hi - lo)
        act = nrng[sy:sy + 2 * hh:2, sx:sx + 2 * ww:2] >= 6
        op = opaque[sy:sy + 2 * hh, sx:sx + 2 * ww].reshape(hh, 2, ww, 2).all(axis=(1, 3))
        m = act & op
        n_act = int(m.sum())
        n_const = int((rng[m] <= 2).sum())
        out[name] = {"active_blocks": n_act, "constant": n_const,
                     "share": round(n_const / max(1, n_act), 4)}
    return out


def measure(sid: str, frames: int = FRAMES, key: str | None = None) -> Path:
    import torch
    store, man, profile = _session(sid)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no usable minimap crop cache ({why}); not decoding")
    key = key or geometry.key_of(sid)
    with np.load(geometry.path(key), allow_pickle=False) as z:
        static, labels = z["static"].copy(), z["labels"].copy()
        built_from = str(z["built_from"])
    wh = (int(man["source"]["width"]), int(man["source"]["height"]))
    if getattr(cache, "widget", None) is not None:
        raise SystemExit(f"{sid}: a variant widget is resampled into its baked frame; "
                         f"its pixels carry that resample, so it does not measure the capture's blur")
    x0, y0, x1, y1 = minimap_roi_px(profile, *wh)
    if (y1 - y0, x1 - x0) != static.shape[:2]:
        raise SystemExit(f"{sid}: crop {(y1 - y0, x1 - x0)} != static {static.shape[:2]}")
    chunks = find_chunks(static, labels)
    st_ycc = ycc(static)
    st_win = np.stack([window(st_ycc, ch) for ch in chunks])                 # (K, 8, 11, 3)
    plate = np.abs(I_POS) >= PLATEAU_PX
    held = cache.holds()
    stride = max(1, len(held) // frames)
    want = held[::stride][:frames]
    K = len(chunks)
    acc = np.zeros((K, 2 * R + 1, 3)); cnt = np.zeros(K, int)
    per_frame = []                                    # (chunk index, frame t, profile (11, 3))
    blocks = []
    opaque = labels != VOID
    t0 = time.perf_counter()
    used = 0
    for smp in cache.samples(want, rois=("minimap",)):
        crop = smp.frame[y0:y1, x0:x1]
        yc = ycc(crop)
        win = np.stack([window(yc, ch) for ch in chunks])                    # (K, 8, 11, 3)
        d = np.abs(win[..., 0] - st_win[..., 0])[:, :, plate]                # (K, 8, n_plate)
        ok = (d.reshape(K, -1).mean(1) <= GATE_MEAN) & (d.reshape(K, -1).max(1) <= GATE_MAX)
        prof = win.mean(1)                                                   # (K, 11, 3)
        acc[ok] += prof[ok]
        cnt[ok] += 1
        if used % PER_FRAME_EVERY == 0:
            for k in np.where(ok)[0]:
                per_frame.append((int(k), float(smp.t_ms), prof[k]))
        if used % 50 == 0 and len(blocks) < 10:
            blocks.append(block_test(yc, opaque, x0, y0))
        used += 1
    keep = cnt >= 5
    mean = acc[keep] / cnt[keep, None, None]
    kidx = np.where(keep)[0]
    lum = fit_profiles(mean[..., 0])
    box = fit_profiles(mean[..., 0], form="boxgauss")
    stat = fit_profiles(st_win[kidx].mean(1)[..., 0])
    rows = []
    for j, k in enumerate(kidx):
        ch = chunks[k]
        lv = lum["levels"][j]
        row = {**ch, "n_frames": int(cnt[k]), "sigma": float(lum["sigma"][j]),
               "e1": float(lum["e1"][j]), "e2": float(lum["e2"][j]),
               "levels": [float(v) for v in lv], "rmse": float(lum["rmse"][j]),
               "contrast": float(lv[1] - 0.5 * (lv[0] + lv[2])),
               "box_sigma": float(box["sigma"][j]), "box_rmse": float(box["rmse"][j]),
               "static_sigma": float(stat["sigma"][j]), "static_e1": float(stat["e1"][j]),
               "static_e2": float(stat["e2"][j]),
               "profile_y": [round(float(v), 3) for v in mean[j, :, 0]],
               "model_y": [round(float(v), 3) for v in lum["model"][j]]}
        x0f = (x0 + ch["c"]) if ch["orient"] == "v" else (y0 + ch["c"])
        row["x0_frame"] = int(x0f)
        chroma = {}
        for ci, cname in ((1, "cb"), (2, "cr")):
            pr = mean[j, :, ci]
            step = abs(float(pr[:2].mean() - pr[-2:].mean()))
            if step < CHROMA_STEP:
                continue
            chroma[cname] = {"step": step, "profile": [round(float(v), 3) for v in pr]}
        row["chroma"] = chroma
        rows.append(row)
    # Chroma fits.
    cps, cref = [], []
    for j, row in enumerate(rows):
        for cname, c in row["chroma"].items():
            cps.append(np.array(c["profile"])); cref.append((j, cname))
    if cps:
        cf = fit_profiles(np.stack(cps))
        for m, (j, cname) in enumerate(cref):
            row = rows[j]
            c = row["chroma"][cname]
            c.update({"sigma": float(cf["sigma"][m]), "e1": float(cf["e1"][m]), "e2": float(cf["e2"][m]),
                      "rmse_free": float(cf["rmse"][m]), "model": [round(float(v), 3) for v in cf["model"][m]]})
            br = chroma_block_rss(np.array(c["profile"]), row["e1"], row["e2"], row["sigma"], row["x0_frame"])
            c["rmse_models"] = {k2: math.sqrt(v / (2 * R + 1)) for k2, v in br.items()}
    # Per-frame fits (luma), a subsample.
    pf = {}
    if per_frame:
        P = np.stack([p[2][:, 0] for p in per_frame])
        f = fit_profiles(P)
        pos = {int(k): j for j, k in enumerate(kidx)}
        pf_rows = []
        for m, (k, t, _) in enumerate(per_frame):
            if k not in pos:
                continue
            pf_rows.append({"chunk": int(pos[k]), "t_ms": t, "sigma": float(f["sigma"][m]),
                            "e1": float(f["e1"][m]), "e2": float(f["e2"][m]), "rmse": float(f["rmse"][m])})
        pf = {"n": len(pf_rows), "rows": pf_rows}
    out = {"version": VERSION, "task": TASK, "session_id": sid, "key": key, "static_built_from": built_from,
           "widget_px": [int(x1 - x0), int(y1 - y0)], "widget_scale": float(widget_scale(x1 - x0)),
           "crop_origin": [int(x0), int(y0)], "cached_frames": len(held), "asked": len(want),
           "used_frames": used, "chunks_found": K, "chunks_fitted": len(rows),
           "seconds": round(time.perf_counter() - t0, 1), "rows": rows, "per_frame": pf,
           "block_test": blocks}
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{sid}_stage1.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    print(json.dumps(summary(out), indent=1))
    print(f"wrote {p}")
    return p


# ------------------------------------------------------------------ summarise
def _q(v):
    v = np.asarray(v, float)
    if v.size == 0:
        return None
    q1, md, q3 = np.percentile(v, [25, 50, 75])
    return {"n": int(v.size), "median": round(float(md), 4), "q1": round(float(q1), 4),
            "q3": round(float(q3), 4), "half_iqr": round(float(q3 - q1) / 2, 4)}


def ringing(rows: list[dict]) -> dict:
    """Pooled luma residual (data - model) / contrast by distance outside the
    line's nearer edge, in 0.5 px bins from 0.5 to 3 px."""
    bins = {f"{a:.1f}-{a + 0.5:.1f}": [] for a in np.arange(0.5, 3.0, 0.5)}
    for r in rows:
        if r["contrast"] < 30:
            continue
        res = (np.array(r["profile_y"]) - np.array(r["model_y"])) / r["contrast"]
        for i, x in enumerate(I_POS):
            dist = max(r["e1"] - x, x - r["e2"])
            if dist < 0.5 or dist >= 3.0:
                continue
            a = math.floor(dist * 2) / 2
            bins[f"{a:.1f}-{a + 0.5:.1f}"].append(float(res[i]))
    return {k: {"n": len(v), "mean": round(float(np.mean(v)), 4) if v else None,
                "se": round(float(np.std(v) / math.sqrt(len(v))), 4) if v else None} for k, v in bins.items()}


def summary(out: dict) -> dict:
    rows = out["rows"]
    s = {"session": out["session_id"], "widget_px": out["widget_px"], "widget_scale": round(out["widget_scale"], 4),
         "used_frames": out["used_frames"], "chunks_found": out["chunks_found"], "chunks_fitted": out["chunks_fitted"]}
    for o in ("v", "h"):
        rr = [r for r in rows if r["orient"] == o]
        s[f"luma_sigma_{o}"] = _q([r["sigma"] for r in rr])
        s[f"static_sigma_{o}"] = _q([r["static_sigma"] for r in rr])
        s[f"width_{o}"] = _q([r["e2"] - r["e1"] for r in rr])
        s[f"rmse_{o}"] = _q([r["rmse"] for r in rr])
        if rr and "box_sigma" in rr[0]:
            s[f"boxgauss_sigma_{o}"] = _q([r["box_sigma"] for r in rr])
            s[f"boxgauss_rmse_ratio_{o}"] = _q([r["box_rmse"] / max(r["rmse"], 1e-6) for r in rr])
        s[f"offset_mid_{o}"] = _q([0.5 * (r["e1"] + r["e2"] - r["static_e1"] - r["static_e2"]) for r in rr])
        cs = [c for r in rr for c in r["chroma"].values() if "sigma" in c]
        s[f"chroma_sigma_{o}"] = _q([c["sigma"] for c in cs])
        if cs:
            st = fit_step(np.stack([np.array(c["profile"]) for c in cs]))
            s[f"chroma_step_sigma_{o}"] = _q(st["sigma"])
            s[f"chroma_rmse_abs_{o}"] = {"free": _q([c["rmse_free"] for c in cs]),
                                         **{m: _q([c["rmse_models"][m] for c in cs])
                                            for m in ("box_even", "sited_even", "box_odd", "none")}}
        if cs:
            s[f"chroma_rmse_ratio_{o}"] = {m: _q([c["rmse_models"][m] / max(c["rmse_free"], 1e-6) for c in cs])
                                           for m in ("box_even", "sited_even", "box_odd", "none")}
    s["luma_sigma_all"] = _q([r["sigma"] for r in rows])
    pf = out.get("per_frame") or {}
    if pf.get("rows"):
        s["per_frame_sigma"] = _q([r["sigma"] for r in pf["rows"]])
        # Per-frame against the same chunk's mean-profile sigma.
        diffs = [r["sigma"] - rows[r["chunk"]]["sigma"] for r in pf["rows"]]
        s["per_frame_minus_mean"] = _q(diffs)
    s["ringing"] = ringing(rows)
    bt = out.get("block_test") or []
    if bt:
        s["block_test"] = {k: round(float(np.mean([b[k]["share"] for b in bt])), 4) for k in bt[0]}
        s["block_test_active"] = int(np.mean([b["aligned"]["active_blocks"] for b in bt]))
    return s


def compare(sids: list[str]) -> dict:
    outs = [json.loads((OUT / f"{s}_stage1.json").read_text(encoding="utf-8")) for s in sids]
    res = {"sessions": sids, "summaries": [summary(o) for o in outs]}
    print(json.dumps(res, indent=1))
    return res


# ------------------------------------------------------------------ plot
def _canvas(w, h):
    return np.full((h, w, 3), 255, np.uint8)


def plot(sids: list[str]) -> Path:
    """Edge-profile sheet: per session, the supersampled outer flank of every
    luma chunk (normalised, against distance from its fitted edge) with the
    Gaussian of the session's median sigma; the chroma flanks likewise; and
    the ringing bins. Drawn with OpenCV; one column per session."""
    from math import erf, sqrt
    outs = [json.loads((OUT / f"{s}_stage1.json").read_text(encoding="utf-8")) for s in sids]
    PW, PH, M = 420, 300, 40
    img = _canvas(M + len(outs) * (PW + M), 3 * (PH + M) + M)
    font = cv2.FONT_HERSHEY_SIMPLEX
    for col, o in enumerate(outs):
        ox = M + col * (PW + M)
        rows = o["rows"]
        sig = float(np.median([r["sigma"] for r in rows]))
        for panel, what in enumerate(("luma", "chroma", "ring")):
            oy = M + panel * (PH + M)
            cv2.rectangle(img, (ox, oy), (ox + PW, oy + PH), (0, 0, 0), 1)
            X = lambda d: int(ox + (d + 3.0) / 6.0 * PW)  # noqa: E731
            Yv = lambda v: int(oy + PH - (v + 0.2) / 1.4 * PH)  # noqa: E731
            if what in ("luma", "chroma"):
                for v in (0.0, 0.5, 1.0):
                    cv2.line(img, (ox, Yv(v)), (ox + PW, Yv(v)), (220, 220, 220), 1)
                cv2.line(img, (X(0), oy), (X(0), oy + PH), (220, 220, 220), 1)
                pts = []
                for r in rows:
                    if what == "luma":
                        if r["contrast"] < 30:
                            continue
                        P = np.array(r["profile_y"]); A, L, B = r["levels"]
                        sets = [(P, A, L, r["e1"], +1), (P, B, L, r["e2"], -1)]
                        mid = 0.5 * (r["e1"] + r["e2"])
                        for (pp, base, top, e, sgn) in sets:
                            if abs(top - base) < 30:
                                continue
                            for i, x in enumerate(I_POS):
                                if (sgn > 0 and x > mid) or (sgn < 0 and x < mid):
                                    continue
                                pts.append((sgn * (x - e), (pp[i] - base) / (top - base)))
                    else:
                        for c in r["chroma"].values():
                            if "sigma" not in c:
                                continue
                            pp = np.array(c["profile"])
                            lo, hi = pp[:2].mean(), pp[-2:].mean()
                            if abs(hi - lo) < CHROMA_STEP:
                                continue
                            mid = 0.5 * (c["e1"] + c["e2"])
                            for i, x in enumerate(I_POS):
                                pts.append((x - mid, (pp[i] - lo) / (hi - lo)))
                for d, v in pts:
                    if -3 <= d <= 3 and -0.2 <= v <= 1.2:
                        cv2.circle(img, (X(d), Yv(v)), 1, (180, 120, 40), -1)
                if what == "luma":
                    prev = None
                    for d in np.linspace(-3, 3, 200):
                        v = 0.5 * (1 + erf(d / sig / sqrt(2)))
                        p = (X(d), Yv(v))
                        if prev:
                            cv2.line(img, prev, p, (0, 0, 220), 2)
                        prev = p
                    cv2.putText(img, f"{o['session_id']} luma flanks; red: Gaussian sigma {sig:.2f}",
                                (ox, oy - 8), font, 0.4, (0, 0, 0), 1)
                    cv2.putText(img, "distance from edge (px), outward <0", (ox + 5, oy + PH - 5),
                                font, 0.35, (80, 80, 80), 1)
                else:
                    cv2.putText(img, "chroma (Cb/Cr) steps, normalised, vs line centre (px)",
                                (ox, oy - 8), font, 0.4, (0, 0, 0), 1)
            else:
                rg = ringing(rows)
                cv2.putText(img, "luma residual / contrast, outside the line (px)", (ox, oy - 8), font, 0.4,
                            (0, 0, 0), 1)
                Yr = lambda v: int(oy + PH / 2 - v / 0.1 * PH / 2)  # noqa: E731
                cv2.line(img, (ox, Yr(0)), (ox + PW, Yr(0)), (0, 0, 0), 1)
                for v in (-0.03, 0.03):
                    cv2.line(img, (ox, Yr(v)), (ox + PW, Yr(v)), (200, 200, 255), 1)
                for b, (k, st) in enumerate(rg.items()):
                    if st["mean"] is None:
                        continue
                    xx = ox + int((b + 0.5) / len(rg) * PW)
                    cv2.circle(img, (xx, Yr(st["mean"])), 4, (0, 0, 200), -1)
                    cv2.line(img, (xx, Yr(st["mean"] - 2 * st["se"])), (xx, Yr(st["mean"] + 2 * st["se"])),
                             (0, 0, 200), 1)
                    cv2.putText(img, k, (xx - 18, oy + PH - 5), font, 0.33, (0, 0, 0), 1)
                cv2.putText(img, "+-3% lines; axis +-10%", (ox + 5, oy + 14), font, 0.35, (80, 80, 80), 1)
    p = OUT / f"edge_profiles_{'_'.join(sids)}.png"
    cv2.imwrite(str(p), img)
    print(f"wrote {p}")
    return p


# ------------------------------------------------------------------ stage 2: icons through the PSF
#: Stage 1's luma PSF (a one-pixel box and a 0.15 px Gaussian) as the linear
#: ramp of equal variance: sqrt(1 + 12 x 0.15^2) px.
LUMA_RAMP = 1.13
NOISE = 4.0               # grey; z = (SSE_bg - SSE_icon) / NOISE^2
ALLY = teardrop.ICON_CLASSES["ally"]
DEEP_PX = 2.0             # pixels deeper than r_in - this inside the initial disc carry no weight
C_GRID = np.arange(-1.5, 1.501, 0.5)
S_GRID = (0.9, 1.0, 1.1)
TH_NEAR = (-20.0, 0.0, 20.0, 180.0)   # degrees about the stored facing (180: the ring fit's flip)
TH_ALL = tuple(range(0, 360, 30))      # when the stored icon has no facing
STEP0 = (0.25, 0.03, 8.0)              # compass: centre px, scale, degrees
STEP_MIN = 0.03
TEAL_MIN = 0.5
STAT_DISC = 0.55          # stationary test: luma inside this fraction of r_in
STAT_MEAN, STAT_MAX, CHANGED_MIN = 1.0, 6.0, 0.3
PAIR_MS, PAIR_PX = 100.0, 2.0


def _tdev():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _layers(dx, dy, th, s, sc):
    """Ring-and-lobe, disc, rim and background coverage at pixel centres through
    the luma PSF: `teardrop.render`'s model with the edge set by stage 1."""
    import torch
    r_in, r_out, L_ = ALLY.r_in * sc * s, ALLY.r_out * sc * s, ALLY.L * sc * s
    c, sn = torch.cos(th), torch.sin(th)
    u = dx * c + dy * sn
    v = -dx * sn + dy * c
    rho = torch.sqrt(dx * dx + dy * dy)
    ca = r_out / L_
    sa = torch.sqrt(torch.clamp(1.0 - ca * ca, min=0.0))
    d_wedge = u * ca + v.abs() * sa - r_out
    d_tri = torch.maximum(d_wedge, torch.maximum(r_out * ca - u, u - L_))
    d_tear = torch.minimum(rho - r_out, d_tri)
    T = torch.clamp(0.5 - torch.maximum(d_tear, r_in - rho) / LUMA_RAMP, 0.0, 1.0)
    D = torch.clamp(0.5 - (rho - r_in) / LUMA_RAMP, 0.0, 1.0)
    # A one-pixel band outside the teardrop: the dark rim some captures draw
    # round the ring; its colour is free, so where no rim is drawn it takes
    # the background's.
    O = torch.clamp(0.5 - (d_tear - 1.0) / LUMA_RAMP, 0.0, 1.0) - torch.clamp(0.5 - d_tear / LUMA_RAMP, 0.0, 1.0)
    O = torch.clamp(O, 0.0, 1.0)
    Bg = torch.clamp(1.0 - T - D - O, 0.0, 1.0)
    return T, D, O, Bg


def _q420(M, fx0, fy0):
    """4:2:0 as stage 1 measured it: a pair mean vertically and a left-sited
    [1 2 1]/4 horizontally, both on pairs aligned to even frame coordinates,
    then duplicated. M (B, P, H, W); fx0, fy0 (B,) frame coordinates of M's
    pixel (0, 0)."""
    import torch
    B, P, H, W = M.shape
    dev = M.device
    rows = torch.arange(H, device=dev)
    lr = (rows[None] - ((fy0[:, None] + rows[None]) % 2)).clamp(0, H - 2)        # (B, H)
    i0 = lr[:, None, :, None].expand(B, P, H, W)
    Mv = 0.5 * (torch.gather(M, 2, i0) + torch.gather(M, 2, i0 + 1))
    cols = torch.arange(W, device=dev)
    lc = (cols[None] - ((fx0[:, None] + cols[None]) % 2)).clamp(1, W - 2)        # (B, W)
    j0 = lc[:, None, None, :].expand(B, P, H, W)
    return (0.25 * torch.gather(Mv, 3, j0 - 1) + 0.5 * torch.gather(Mv, 3, j0)
            + 0.25 * torch.gather(Mv, 3, j0 + 1))


def _solve(X, y, w):
    """Weighted least squares per (B, P): X (B, P, K, N), y (B, N), w (B, N).
    Returns SSE (B, P) and coefficients (B, P, K)."""
    import torch
    Xw = X * w[:, None, None, :]
    A = (Xw @ X.transpose(-1, -2)).double()
    K = X.shape[2]
    tr = A.diagonal(dim1=-2, dim2=-1).sum(-1)[..., None, None] / K
    # A ridge relative to the matrix's scale keeps an empty layer (an icon at
    # the widget's edge, a band off the window) from making it singular.
    A = A + (1e-7 * tr + 1e-6) * torch.eye(K, device=X.device, dtype=A.dtype)
    b = (Xw * y[:, None, None, :]).sum(-1).double()
    coef = torch.linalg.solve(A, b[..., None])[..., 0]
    yy = (w * y * y).sum(-1)[:, None].double()
    sse = (yy - (coef * b).sum(-1)).float()
    return sse, coef.float()


class IconBatch:
    """Windows of B icons: observed Y/Cb/Cr (inner window), the baked static
    on the padded window, weights, frame origins and initial poses."""

    def __init__(self, obs, stat, w, fx0, fy0, init, sc, half):
        import torch
        dev = _tdev()
        self.obs = torch.as_tensor(obs, device=dev, dtype=torch.float32)      # (B, 3, N)
        self.stat = torch.as_tensor(stat, device=dev, dtype=torch.float32)    # (B, 3, Hp, Wp)
        self.w = torch.as_tensor(w, device=dev, dtype=torch.float32)          # (B, N)
        self.fx0 = torch.as_tensor(fx0, device=dev, dtype=torch.long)         # padded origin
        self.fy0 = torch.as_tensor(fy0, device=dev, dtype=torch.long)
        self.init = torch.as_tensor(init, device=dev, dtype=torch.float32)    # (B, 3): cx, cy in window px, facing deg
        self.sc, self.half = float(sc), int(half)
        Hp = 2 * half + 1 + 4
        g = torch.arange(Hp, device=dev, dtype=torch.float32) - 2.0           # inner px coords
        self.Y, self.X = torch.meshgrid(g, g, indexing="ij")
        self.Hp = Hp

    def _inner(self, M):
        n = 2 * self.half + 1
        return M[..., 2:2 + n, 2:2 + n].reshape(*M.shape[:2], n * n)

    def loss(self, cx, cy, s, th, want_coef=False):
        """SSE summed over Y, Cb, Cr for parameters (B, P) each."""
        import torch
        dx = self.X[None, None] - cx[..., None, None]
        dy = self.Y[None, None] - cy[..., None, None]
        T, D, O, Bg = _layers(dx, dy, th[..., None, None], s[..., None, None], self.sc)
        sY, sB, sR = (self.stat[:, k][:, None] for k in range(3))
        XY = torch.stack([self._inner(T), self._inner(D), self._inner(O), self._inner(sY * Bg),
                          self._inner(Bg)], 2)
        QT, QD, QO, QB = (_q420(M, self.fx0, self.fy0) for M in (T, D, O, Bg))
        XB = torch.stack([self._inner(QT), self._inner(QD), self._inner(QO),
                          self._inner(_q420(sB * Bg, self.fx0, self.fy0)), self._inner(QB)], 2)
        XR = torch.stack([self._inner(QT), self._inner(QD), self._inner(QO),
                          self._inner(_q420(sR * Bg, self.fx0, self.fy0)), self._inner(QB)], 2)
        tot, coefs = 0.0, []
        for k, Xc in enumerate((XY, XB, XR)):
            sse, coef = _solve(Xc, self.obs[:, k], self.w)
            tot = tot + sse
            coefs.append(coef)
        return (tot, torch.stack(coefs, -1)) if want_coef else tot

    def loss_bg(self):
        """SSE of the background alone (static gain and offset per channel)."""
        import torch
        ones = torch.ones((self.obs.shape[0], 1, self.Hp, self.Hp), device=self.obs.device)
        tot = 0.0
        for k in range(3):
            sk = self.stat[:, k][:, None]
            m = sk if k == 0 else _q420(sk, self.fx0, self.fy0)
            X = torch.stack([self._inner(m), self._inner(ones)], 2)
            sse, _ = _solve(X, self.obs[:, k], self.w)
            tot = tot + sse[:, 0]
        return tot


def fit_batch(bt: IconBatch) -> dict:
    """Grid round each icon's stored pose, then a compass refine."""
    import torch
    B = bt.obs.shape[0]
    dev = bt.obs.device
    cx0, cy0, f0 = bt.init[:, 0], bt.init[:, 1], bt.init[:, 2]
    has_f = ~torch.isnan(f0)
    grid = []
    for dxx in C_GRID:
        for dyy in C_GRID:
            for ss in S_GRID:
                grid.append((dxx, dyy, ss))
    G = torch.tensor(grid, device=dev, dtype=torch.float32)                   # (g, 3)
    ths_near = torch.tensor(TH_NEAR, device=dev, dtype=torch.float32)
    ths_all = torch.tensor(TH_ALL, device=dev, dtype=torch.float32)
    best = torch.full((B,), float("inf"), device=dev)
    bp = torch.zeros((B, 4), device=dev)
    # Icons with a stored facing try its four near values; the rest every 30
    # degrees. A batch mixing both runs twelve, the near list repeating.
    nt = len(TH_NEAR) if bool(has_f.all()) else len(TH_ALL)
    for ti in range(nt):
        th_deg = torch.where(has_f, torch.nan_to_num(f0) + ths_near[ti % len(TH_NEAR)],
                             ths_all[ti % len(TH_ALL)].expand(B))
        for g0 in range(0, G.shape[0], 49):
            Gc = G[g0:g0 + 49]
            cx = cx0[:, None] + Gc[None, :, 0]
            cy = cy0[:, None] + Gc[None, :, 1]
            s = Gc[None, :, 2].expand(B, -1)
            th = torch.deg2rad(th_deg)[:, None].expand(B, Gc.shape[0])
            L = bt.loss(cx, cy, s, th)
            v, j = L.min(1)
            upd = v < best
            best = torch.where(upd, v, best)
            cand = torch.stack([cx[torch.arange(B), j], cy[torch.arange(B), j], s[torch.arange(B), j],
                                th_deg], 1)
            bp = torch.where(upd[:, None], cand, bp)
    # Compass refine.
    step = torch.tensor(STEP0, device=dev).repeat(B, 1)                        # (B, 3)
    dirs = torch.tensor([[0, 0, 0, 0], [1, 0, 0, 0], [-1, 0, 0, 0], [0, 1, 0, 0], [0, -1, 0, 0],
                         [0, 0, 1, 0], [0, 0, -1, 0], [0, 0, 0, 1], [0, 0, 0, -1]], device=dev, dtype=torch.float32)
    for _ in range(80):
        sc4 = torch.stack([step[:, 0], step[:, 0], step[:, 1], step[:, 2]], 1)   # (B, 4)
        cand = bp[:, None, :] + dirs[None] * sc4[:, None, :]                   # (B, 9, 4)
        cand[..., 2] = cand[..., 2].clamp(0.6, 1.6)
        L = bt.loss(cand[..., 0], cand[..., 1], cand[..., 2], torch.deg2rad(cand[..., 3]))
        v, j = L.min(1)
        moved = j != 0
        bp = cand[torch.arange(B), j]
        best = v
        step = torch.where(moved[:, None], step, step / 2)
        if bool((step[:, 0] < STEP_MIN).all()):
            break
    L, coef = bt.loss(bp[:, None, 0], bp[:, None, 1], bp[:, None, 2], torch.deg2rad(bp[:, None, 3]),
                      want_coef=True)
    bg = bt.loss_bg()
    return {"cx": bp[:, 0].cpu().numpy(), "cy": bp[:, 1].cpu().numpy(), "s": bp[:, 2].cpu().numpy(),
            "facing": (bp[:, 3].cpu().numpy() % 360.0), "sse": L[:, 0].cpu().numpy(), "sse_bg": bg.cpu().numpy(),
            "coef": coef[:, 0].cpu().numpy(), "n_w": bt.w.sum(1).cpu().numpy()}


def _ycc_to_bgr(yc):
    """(3,) Y, Cb, Cr -> BGR float (OpenCV's BT.601 full range)."""
    a = np.array([[[yc[0], yc[2], yc[1]]]], np.float32)
    return cv2.cvtColor(np.clip(a, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR)[0, 0].astype(np.float32)


def _stored_icons(store, sid, between):
    t0, t1 = between[0] * 1000.0, between[1] * 1000.0
    rows = [r for r in store.read_events("ally_icon", sid)
            if r.get("kind") == "icon" and t0 <= float(r["t_ms"]) <= t1]
    return rows


def fit_icons(sid: str, between, limit: int | None = None, batch: int = 32) -> Path:
    """Fit every stored ally icon (both families) in the slice through the PSF."""
    import torch
    store, man, profile = _session(sid)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no usable minimap crop cache ({why}); not decoding")
    key = geometry.key_of(sid)
    ms = geometry.map_scale(key)
    if ms is None:
        raise SystemExit(f"{sid}: {key} has no map scale; refusing")
    sc = ms.scale
    with np.load(geometry.path(key), allow_pickle=False) as z:
        static = z["static"].copy()
    wh = (int(man["source"]["width"]), int(man["source"]["height"]))
    x0, y0, x1, y1 = minimap_roi_px(profile, *wh)
    st = ycc(static)
    H, W = st.shape[:2]
    half = int(math.ceil(ALLY.L * sc * 1.15 + 3))
    n = 2 * half + 1
    pad = half + 2
    stp = np.pad(st, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    inside = np.pad(np.ones((H, W), np.float32), ((pad, pad), (pad, pad)))
    icons = _stored_icons(store, sid, between)
    if limit:
        icons = icons[:limit]
    by_t: dict[float, list[int]] = {}
    for i, r in enumerate(icons):
        by_t.setdefault(float(r["t_ms"]), []).append(i)
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
    r_deep = ALLY.r_in * sc - DEEP_PX
    results = [None] * len(icons)
    pend = []

    def flush():
        if not pend:
            return
        obs = np.stack([p[1] for p in pend]); stat = np.stack([p[2] for p in pend])
        w = np.stack([p[3] for p in pend]); fx0 = np.array([p[4] for p in pend]); fy0 = np.array([p[5] for p in pend])
        init = np.stack([p[6] for p in pend])
        bt = IconBatch(obs, stat, w, fx0, fy0, init, sc, half)
        with torch.no_grad():
            f = fit_batch(bt)
        for j, p in enumerate(pend):
            i, ox, oy = p[0], p[7], p[8]
            coef = f["coef"][j]                                   # (5 basis, 3 channels)
            ring = coef[0]
            teal = float(teardrop.tealness(_ycc_to_bgr(ring)[None, None])[0, 0])
            results[i] = {"cx": float(f["cx"][j] + ox), "cy": float(f["cy"][j] + oy), "s": float(f["s"][j]),
                          "r_out": float(ALLY.r_out * sc * f["s"][j]), "facing": float(f["facing"][j]),
                          "sse": float(f["sse"][j]), "sse_bg": float(f["sse_bg"][j]),
                          "z": float((f["sse_bg"][j] - f["sse"][j]) / NOISE ** 2), "n_w": float(f["n_w"][j]),
                          "rmse": float(math.sqrt(max(f["sse"][j], 0.0) / max(3 * f["n_w"][j], 1.0))),
                          "ring_ycc": [float(v) for v in ring], "disc_ycc": [float(v) for v in coef[1]],
                          "teal": teal}
        pend.clear()

    t_start = time.perf_counter()
    times = sorted(by_t)
    for smp in cache.samples(times, rois=("minimap",)):
        crop = smp.frame[y0:y1, x0:x1]
        yc = np.pad(ycc(crop), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        for i in by_t.get(float(smp.t_ms), []):
            r = icons[i]
            ix, iy = int(round(r["cx"])), int(round(r["cy"]))
            ox, oy = ix - half, iy - half                          # inner window origin, crop px
            sy, sx = oy + pad, ox + pad
            ob = yc[sy:sy + n, sx:sx + n]
            sp = stp[sy - 2:sy + n + 2, sx - 2:sx + n + 2]
            wv = inside[sy:sy + n, sx:sx + n].copy()
            # distance from the stored centre, in inner window coordinates
            rho0 = np.hypot(xx + half - (r["cx"] - ox), yy + half - (r["cy"] - oy))
            wv[rho0 < r_deep] = 0.0
            f0 = r.get("facing")
            init = np.array([r["cx"] - ox, r["cy"] - oy, np.nan if f0 is None else float(f0)], np.float32)
            # frame coordinates of the padded window's pixel (0, 0)
            fx0, fy0 = x0 + ox - 2, y0 + oy - 2
            pend.append((i, np.moveaxis(ob, 2, 0).reshape(3, -1), np.moveaxis(sp, 2, 0), wv.reshape(-1),
                         fx0, fy0, init, ox, oy))
            if len(pend) >= batch:
                flush()
    flush()
    out_rows = []
    for r, f in zip(icons, results):
        if f is None:
            continue
        out_rows.append({"t_ms": float(r["t_ms"]), "frame_idx": int(r["frame_idx"]), "family": r["family"],
                         "reason": r.get("reason"), "pose_origin": (r.get("pose") or {}).get("origin"),
                         "stored": {"cx": r["cx"], "cy": r["cy"], "r": r["r"], "facing": r.get("facing")},
                         "ring": {"cx": (r.get("ring") or {}).get("cx"), "cy": (r.get("ring") or {}).get("cy")},
                         "psf": f})
    out = {"version": VERSION, "task": TASK, "session_id": sid, "key": key, "between": list(between),
           "map_scale": ms.provenance(), "half": half, "luma_ramp": LUMA_RAMP, "noise": NOISE,
           "icons": out_rows, "seconds": round(time.perf_counter() - t_start, 1)}
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{sid}_{int(between[0])}-{int(between[1])}_icons.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    ss = np.array([r["psf"]["s"] for r in out_rows if r["family"] == "ally"])
    print(json.dumps({"session": sid, "icons": len(out_rows), "seconds": out["seconds"],
                      "s_median": round(float(np.median(ss)), 4) if ss.size else None,
                      "r_out_median": round(float(np.median([r["psf"]["r_out"] for r in out_rows])), 3)}))
    print(f"wrote {p}")
    return p


# ------------------------------------------------------------------ stage 2: scoring
def _load_icons(sid, between):
    return json.loads((OUT / f"{sid}_{int(between[0])}-{int(between[1])}_icons.json").read_text(encoding="utf-8"))


def _accept(f: dict, zstar: float) -> bool:
    return f["z"] >= zstar and f["teal"] >= TEAL_MIN


def _roster(sid, between, zstar=None):
    """Roster residuals {t: n - capacity} for the stored icons and, given
    z*, for the PSF verifier; frames as `upscale_trial.score` counts them."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import upscale_trial as ut
    store = Store(STORE)
    d = _load_icons(sid, between)
    frames = [r for r in store.read_events_kind("ally_icon", sid, "frame") if r.get("kind") == "frame"
              and between[0] * 1000.0 <= float(r["t_ms"]) <= between[1] * 1000.0 and r.get("widget_drawn")]
    pop = ut._population(store, sid, sorted(float(r["t_ms"]) for r in frames))
    from collections import Counter
    base = Counter(r["t_ms"] for r in d["icons"] if r["family"] != "barrier")
    res_a = {t: base.get(t, 0) - c for t, c in pop.items()}
    if zstar is None:
        return res_a, None, pop, d
    ver = Counter(r["t_ms"] for r in d["icons"] if r["family"] != "barrier" and _accept(r["psf"], zstar))
    res_v = {t: ver.get(t, 0) - c for t, c in pop.items()}
    return res_a, res_v, pop, d


def _pairs(store, sid, d):
    """Stationary pairs (the stationary rule in the predictions record)."""
    man = json.loads((store.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    profile = get_profile(man["source_profile"])
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    x0, y0, x1, y1 = minimap_roi_px(profile, int(man["source"]["width"]), int(man["source"]["height"]))
    sc = d["map_scale"]["scale"]
    rd = STAT_DISC * ALLY.r_in * sc
    half = d["half"]
    by_t: dict[float, list[dict]] = {}
    for r in d["icons"]:
        if r["family"] == "ally":
            by_t.setdefault(r["t_ms"], []).append(r)
    times = sorted(by_t)
    lum = {}
    for smp in cache.samples(times, rois=("minimap",)):
        lum[float(smp.t_ms)] = ycc(smp.frame[y0:y1, x0:x1])[..., 0]
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
    disc = np.hypot(xx, yy) <= rd
    pairs = []
    for ta, tb in zip(times[:-1], times[1:]):
        if tb - ta > PAIR_MS or ta not in lum or tb not in lum:
            continue
        for a in by_t[ta]:
            cands = [b for b in by_t[tb] if math.hypot(b["stored"]["cx"] - a["stored"]["cx"],
                                                       b["stored"]["cy"] - a["stored"]["cy"]) <= PAIR_PX]
            if len(cands) != 1:
                continue
            b = cands[0]
            ix, iy = int(round(a["stored"]["cx"])), int(round(a["stored"]["cy"]))
            if iy - half < 0 or ix - half < 0 or iy + half + 1 > lum[ta].shape[0] or ix + half + 1 > lum[ta].shape[1]:
                continue
            wa = lum[ta][iy - half:iy + half + 1, ix - half:ix + half + 1]
            wb = lum[tb][iy - half:iy + half + 1, ix - half:ix + half + 1]
            dd = np.abs(wa - wb)
            if dd[disc].mean() > STAT_MEAN or dd[disc].max() > STAT_MAX:
                continue
            pairs.append({"ta": ta, "tb": tb, "a": a, "b": b, "changed": bool(dd.mean() >= CHANGED_MIN)})
    return pairs


def _disp(p, which):
    a, b = p["a"], p["b"]
    if which == "psf":
        return math.hypot(b["psf"]["cx"] - a["psf"]["cx"], b["psf"]["cy"] - a["psf"]["cy"])
    if which == "ring":
        if a["ring"]["cx"] is None or b["ring"]["cx"] is None:
            return None
        return math.hypot(b["ring"]["cx"] - a["ring"]["cx"], b["ring"]["cy"] - a["ring"]["cy"])
    return math.hypot(b["stored"]["cx"] - a["stored"]["cx"], b["stored"]["cy"] - a["stored"]["cy"])


def _stationary_spans(pairs):
    """Chains of consecutive stationary pairs of one icon, >= 3 frames."""
    nxt = {(p["ta"], id(p["a"])): p for p in pairs}
    starts = set(nxt) - {(p["tb"], id(p["b"])) for p in pairs}
    spans = []
    for st in starts:
        chain = [nxt[st]["a"]]
        k = st
        while k in nxt:
            p = nxt[k]
            chain.append(p["b"])
            k = (p["tb"], id(p["b"]))
        if len(chain) >= 3:
            spans.append(chain)
    return spans


def _rms(chain, which):
    if which == "psf":
        P = np.array([[c["psf"]["cx"], c["psf"]["cy"]] for c in chain])
    elif which == "ring":
        if any(c["ring"]["cx"] is None for c in chain):
            return None
        P = np.array([[c["ring"]["cx"], c["ring"]["cy"]] for c in chain], float)
    else:
        P = np.array([[c["stored"]["cx"], c["stored"]["cy"]] for c in chain])
    return float(np.sqrt(((P - P.mean(0)) ** 2).sum(1).mean()))


def icon_score(calib: list[str], test: list[str]) -> dict:
    """z* from the calibration slices, then jitter, size and roster on the test slices.

    Slices are `SID:T0-T1` (seconds)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import upscale_trial as ut

    def parse(x):
        sid, span = x.split(":")
        a, b = span.split("-")
        return sid, (float(a), float(b))

    store = Store(STORE)
    cal = [parse(x) for x in calib]
    zall = np.concatenate([[r["psf"]["z"] for r in _load_icons(sid, bw)["icons"]] for sid, bw in cal])
    zs = np.unique(np.concatenate([[0.0], np.percentile(zall, np.linspace(0, 60, 121))]))
    tot = {}
    for z in zs:
        errs = []
        for sid, bw in cal:
            _, rv, _, _ = _roster(sid, bw, float(z))
            errs.extend(abs(v) for v in rv.values())
        tot[float(z)] = float(np.mean(errs))
    zstar = min(tot, key=lambda k: (tot[k], k))
    out = {"zstar": zstar, "calib": calib, "calib_mae_at_zstar": round(tot[zstar], 4),
           "calib_mae_at_0": round(tot[0.0], 4), "test": {}}
    mae = lambda v: float(np.abs(v).mean())  # noqa: E731
    for x in test:
        sid, bw = parse(x)
        ra, rv, pop, d = _roster(sid, bw, zstar)
        dm = ut._boot(ra, rv, mae)
        ally = [r for r in d["icons"] if r["family"] == "ally"]
        sc = d["map_scale"]
        pairs = _pairs(store, sid, d)
        ch = [p for p in pairs if p["changed"]]
        sp = _stationary_spans(pairs)
        jit = {}
        for which in ("psf", "stored", "ring"):
            dv = [v for v in (_disp(p, which) for p in pairs) if v is not None]
            dc = [v for v in (_disp(p, which) for p in ch) if v is not None]
            rr = [v for v in (_rms(c, which) for c in sp) if v is not None]
            jit[which] = {"pairs_median": round(float(np.median(dv)), 4) if dv else None,
                          "pairs_mean": round(float(np.mean(dv)), 4) if dv else None,
                          "changed_median": round(float(np.median(dc)), 4) if dc else None,
                          "changed_mean": round(float(np.mean(dc)), 4) if dc else None,
                          "changed_p90": round(float(np.percentile(dc, 90)), 4) if dc else None,
                          "span_rms_median": round(float(np.median(rr)), 4) if rr else None,
                          "span_rms_mean": round(float(np.mean(rr)), 4) if rr else None}
        r_out = np.array([r["psf"]["r_out"] for r in ally])
        out["test"][x] = {
            "icons": len(d["icons"]), "ally_icons": len(ally),
            "roster": {"n": len(pop), "stored": ut._metrics(ra), "psf_verifier": ut._metrics(rv),
                       "d_mae": dm, "dropped": sum(1 for r in d["icons"] if r["family"] != "barrier"
                                                   and not _accept(r["psf"], zstar))},
            "size": {"r_out": _q(r_out), "s": _q([r["psf"]["s"] for r in ally]),
                     "map_scale_r_out": round(ALLY.r_out * sc["scale"], 3),
                     "widget_scale_r_out": round(ALLY.r_out * sc["widget_scale"], 3)},
            "fit": {"rmse": _q([r["psf"]["rmse"] for r in ally]), "z": _q([r["psf"]["z"] for r in ally]),
                    "teal": _q([r["psf"]["teal"] for r in ally])},
            "jitter": {"stationary_pairs": len(pairs), "changed_pairs": len(ch), "spans": len(sp), **jit}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon_score.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return out


def icon_sheet(sid: str, between, n: int = 8) -> Path:
    """Observed / rendered / residual for n ally icons spread over the slice,
    at 10x (nearest, display only), with the PSF centre (red), the stored
    pose (green) and the ring fit (magenta)."""
    import torch
    store, man, profile = _session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    d = _load_icons(sid, between)
    key = d["key"]
    sc = d["map_scale"]["scale"]
    half = d["half"]
    with np.load(geometry.path(key), allow_pickle=False) as z:
        static = z["static"].copy()
    x0, y0, x1, y1 = minimap_roi_px(profile, int(man["source"]["width"]), int(man["source"]["height"]))
    st = ycc(static)
    ally = [r for r in d["icons"] if r["family"] == "ally"]
    pick = [ally[int(i)] for i in np.linspace(0, len(ally) - 1, n)]
    Z, nwin = 10, 2 * half + 1
    pad = half + 2
    stp = np.pad(st, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    rows = []
    for r in pick:
        smp = next(cache.samples([r["t_ms"]], rois=("minimap",)))
        crop = smp.frame[y0:y1, x0:x1]
        yc = np.pad(ycc(crop), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        ix, iy = int(round(r["stored"]["cx"])), int(round(r["stored"]["cy"]))
        ox, oy = ix - half, iy - half
        sy, sx = oy + pad, ox + pad
        ob = yc[sy:sy + nwin, sx:sx + nwin]
        sp = stp[sy - 2:sy + nwin + 2, sx - 2:sx + nwin + 2]
        w = np.ones(nwin * nwin, np.float32)
        bt = IconBatch(np.moveaxis(ob, 2, 0).reshape(1, 3, -1), np.moveaxis(sp, 2, 0)[None], w[None],
                       np.array([x0 + ox - 2]), np.array([y0 + oy - 2]),
                       np.array([[0, 0, 0]], np.float32), sc, half)
        f = r["psf"]
        dev = bt.obs.device
        t = lambda v: torch.tensor([[v]], device=dev, dtype=torch.float32)  # noqa: E731
        with torch.no_grad():
            dx = bt.X[None, None] - t(f["cx"] - ox)[..., None, None]
            dy = bt.Y[None, None] - t(f["cy"] - oy)[..., None, None]
            T, D, O, Bg = _layers(dx, dy, t(math.radians(f["facing"]))[..., None, None], t(f["s"])[..., None, None], sc)
            _, coef = bt.loss(t(f["cx"] - ox), t(f["cy"] - oy), t(f["s"]), t(math.radians(f["facing"])), want_coef=True)
            coef = coef[0, 0].cpu().numpy()                                    # (5, 3)
            model = np.zeros((3, nwin, nwin), np.float32)
            for k in range(3):
                maps = [T, D, O, bt.stat[:, k][:, None] * Bg, Bg]
                if k > 0:
                    maps = [_q420(m, bt.fx0, bt.fy0) for m in maps]
                acc = sum(coef[j, k] * maps[j] for j in range(5))
                model[k] = acc[0, 0, 2:2 + nwin, 2:2 + nwin].cpu().numpy()
        mo = np.moveaxis(model, 0, 2)
        to_bgr = lambda a: cv2.cvtColor(np.clip(a[..., [0, 2, 1]], 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR)  # noqa: E731
        o_img, m_img = to_bgr(ob), to_bgr(mo)
        res = np.abs(ob - mo).sum(2)
        r_img = cv2.applyColorMap(np.clip(res * 4, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        tiles = []
        for im in (o_img, m_img, r_img):
            big = cv2.resize(im, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
            P = lambda x, y: (int((x - ox + 0.5) * Z), int((y - oy + 0.5) * Z))  # noqa: E731
            cv2.circle(big, P(f["cx"], f["cy"]), 4, (0, 0, 255), -1)
            cv2.circle(big, P(r["stored"]["cx"], r["stored"]["cy"]), 4, (0, 200, 0), -1)
            if r["ring"]["cx"] is not None:
                cv2.circle(big, P(r["ring"]["cx"], r["ring"]["cy"]), 4, (255, 0, 255), -1)
            tiles.append(big)
        row = np.hstack(tiles)
        cv2.putText(row, f"t {r['t_ms'] / 1000:.2f}s z {f['z']:.0f} rmse {f['rmse']:.1f} r_out {f['r_out']:.2f} "
                    f"teal {f['teal']:.2f}", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        rows.append(row)
    sheet = np.vstack(rows)
    p = OUT / f"icon_sheet_{sid}_{int(between[0])}-{int(between[1])}.png"
    cv2.imwrite(str(p), sheet)
    print(f"wrote {p}")
    return p

# ------------------------------------------------------------------ record
def record_metrics(sids: list[str]) -> None:
    """One metrics row per stage-1 session (`capture_psf/stage1`) and per
    stage-2 test slice (`capture_psf/icons`), for the doc's citations."""
    from reticle import metrics
    for sid in sids:
        o = json.loads((OUT / f"{sid}_stage1.json").read_text(encoding="utf-8"))
        s = summary(o)
        vals = {"widget_px": o["widget_px"][0], "frames": s["used_frames"], "chunks": s["chunks_fitted"],
                "luma_sigma": s["luma_sigma_all"]["median"], "luma_sigma_v": s["luma_sigma_v"]["median"],
                "luma_sigma_h": s["luma_sigma_h"]["median"],
                "luma_sigma_half_iqr": s["luma_sigma_all"]["half_iqr"],
                "boxgauss_sigma_v": s["boxgauss_sigma_v"]["median"],
                "boxgauss_sigma_h": s["boxgauss_sigma_h"]["median"],
                "chroma_step_sigma_v": s["chroma_step_sigma_v"]["median"],
                "chroma_step_sigma_h": s["chroma_step_sigma_h"]["median"],
                "chroma_chunks": s["chroma_sigma_v"]["n"] + s["chroma_sigma_h"]["n"],
                "block_aligned": s["block_test"]["aligned"], "block_off_x": s["block_test"]["off_x"],
                "block_off_y": s["block_test"]["off_y"],
                "ringing_max_abs": max(abs(v["mean"]) for v in s["ringing"].values() if v["mean"] is not None),
                "offset_mid_v": s["offset_mid_v"]["median"], "offset_mid_h": s["offset_mid_h"]["median"]}
        metrics.record("capture_psf", part="stage1", session=sid, values=vals,
                       deps={"version": VERSION, "key": o["key"], "static_built_from": o["static_built_from"]},
                       context={"task": TASK})
    p = OUT / "icon_score.json"
    if p.is_file():
        d = json.loads(p.read_text(encoding="utf-8"))
        for x, v in d["test"].items():
            sid = x.split(":")[0]
            j = v["jitter"]
            vals = {"zstar": d["zstar"], "stationary_pairs": j["stationary_pairs"], "changed_pairs": j["changed_pairs"],
                    "spans": j["spans"], "r_out": v["size"]["r_out"]["median"], "s": v["size"]["s"]["median"],
                    "map_scale_r_out": v["size"]["map_scale_r_out"],
                    "widget_scale_r_out": v["size"]["widget_scale_r_out"],
                    "mae_stored": v["roster"]["stored"]["mae"], "mae_verifier": v["roster"]["psf_verifier"]["mae"],
                    "d_mae": v["roster"]["d_mae"][0], "dropped": v["roster"]["dropped"],
                    "rmse": v["fit"]["rmse"]["median"]}
            for which in ("psf", "stored", "ring"):
                for k in ("changed_median", "changed_mean", "changed_p90", "span_rms_median", "span_rms_mean"):
                    vals[f"{which}_{k}"] = j[which][k]
            metrics.record("capture_psf", part="icons", session=sid, values=vals,
                           deps={"version": VERSION, "slice": x, "calib": " ".join(d["calib"]),
                                 "ally_icon_version": "ally-icon-0.7.0"},
                           context={"task": TASK})
    print("recorded")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure"); m.add_argument("session"); m.add_argument("--frames", type=int, default=FRAMES)
    c = sub.add_parser("compare"); c.add_argument("sessions", nargs="+")
    p = sub.add_parser("plot"); p.add_argument("sessions", nargs="+")
    f = sub.add_parser("icons"); f.add_argument("session")
    f.add_argument("--between", type=float, nargs=2, required=True)
    f.add_argument("--limit", type=int, default=None)
    sc = sub.add_parser("icon-score"); sc.add_argument("--calib", nargs="+", required=True)
    sc.add_argument("--test", nargs="+", required=True)
    sh = sub.add_parser("icon-sheet"); sh.add_argument("session"); sh.add_argument("--between", type=float, nargs=2, required=True)
    sh.add_argument("--n", type=int, default=8)
    rc = sub.add_parser("record"); rc.add_argument("sessions", nargs="+")
    a = ap.parse_args(argv)
    _idle()
    if a.cmd == "measure":
        measure(a.session, a.frames)
    elif a.cmd == "compare":
        compare(a.sessions)
    elif a.cmd == "plot":
        plot(a.sessions)
    elif a.cmd == "icons":
        fit_icons(a.session, tuple(a.between), a.limit)
    elif a.cmd == "icon-score":
        icon_score(a.calib, a.test)
    elif a.cmd == "icon-sheet":
        icon_sheet(a.session, tuple(a.between), a.n)
    elif a.cmd == "record":
        record_metrics(a.sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
