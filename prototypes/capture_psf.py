r"""The capture chain's blur on the minimap, measured on the baked map's walls.

    .\.venv\Scripts\python.exe prototypes\capture_psf.py measure SESSION [--frames N]
    .\.venv\Scripts\python.exe prototypes\capture_psf.py compare SESSION [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\capture_psf.py plot SESSION [SESSION ...]

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

No reader stamp moves; each `measure` writes one JSON under
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

from reticle import geometry  # noqa: E402
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure"); m.add_argument("session"); m.add_argument("--frames", type=int, default=FRAMES)
    c = sub.add_parser("compare"); c.add_argument("sessions", nargs="+")
    p = sub.add_parser("plot"); p.add_argument("sessions", nargs="+")
    a = ap.parse_args(argv)
    _idle()
    if a.cmd == "measure":
        measure(a.session, a.frames)
    elif a.cmd == "compare":
        compare(a.sessions)
    elif a.cmd == "plot":
        plot(a.sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
