r"""Where the self viewcone's rays start, against the fitted teardrop, and how wide it is.

    .\.venv\Scripts\python.exe prototypes\cone_origin.py --sheet SID PATH
    .\.venv\Scripts\python.exe prototypes\cone_origin.py [--second 5822b6646448]

E4 of [the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md). The
player said on 2026-09-28 that the rays look to start at the icon's centre, and
asked that the exact point be calibrated [domain:minimap/cone-origin-near-centre].
E3b cast a cone from the teardrop's centre along the read facing and beat every
origin further out, but held the half-angle at 51.5 degrees, so origin and angle
were confounded. This fits them jointly.

**The model.** For a frame with a read teardrop (`teardrop_tip.fit`: centre
`(x, y)`, facing `th`) the origin is `(x, y) + a * u + c * n`, where `u` is the
unit facing and `n` is `u` turned +90 degrees in image coordinates (clockwise
on screen). The cone is `cone.raycast` from that origin with half-angle `h`,
through the baked passable mask. Each origin is cast once over the full circle;
a half-angle then keeps the pixels whose bearing from the origin lies within `h`
of the facing, which is the wedge `cone.raycast` itself marks, to a ray's
rounding. `--confirm` recasts the chosen cones with the owner's wedge.

**The witness.** The drawn light is `lighting.raw_lit` on the crop against the
baked lighting reference, on known floor, within `R_EVAL` px of the teardrop's
centre, outside the icon's own footprint (the teardrop grown by `PAD` px). The
score is the pooled F1 of cone against light: precision punishes a wide cone
and recall a narrow one, so `h` is identified, and the edges' positions over a
range of distances separate the origin from the angle.

`--witness all` (0.1.0) takes every lit pixel in the region. On 5822b6646448
teammates' cones dominate that mask, which left the half-angle unidentified and
pulled the light's bisector off the read facing. The default, `joined` (0.2.0),
keeps only lit components that touch a `JOIN_PX` band round the icon's
footprint: the drawn self cone starts under the icon, and a teammate's cone
starts under the teammate's. It uses no facing, so it favours no origin or
angle; a teammate's cone that overlaps ours still joins.

**Frames.** A frame enters when its teardrop reads and at least `MIN_LIT` lit
pixels lie in the region; consecutive identical fits (the minimap repeats
images) collapse to one. Frames split by `BLOCK_MS` time blocks into fit
(even) and held-out (odd) halves; the uncertainty is a block bootstrap of the
fit half's argmax. The demo's sliver neighbourhoods stay out, as in E1-E3.

It reads the minimap crop cache only, decodes no video, and writes one
`metrics` row. It changes no pipeline output.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import teardrop_tip as tt  # noqa: E402
from reticle import cone, lighting, metrics  # noqa: E402

VERSION = "cone-origin-0.3.0"
A_OFF = np.arange(-10.0, 12.01, 1.0)      # along the facing, px
C_OFF = np.arange(-4.0, 4.01, 1.0)       # across it, px (+ is clockwise on screen)
H_DEG = np.arange(38.0, 66.01, 1.0)      # half-angle
BASE = (0.0, 0.0, cone.CONE_HALF_ANGLE_DEG)
R_EVAL = 90.0
PAD = 3.0
MIN_LIT = 50
BLOCK_MS = 3000.0
N_RAYS_FULL = 1440
WINDOWS, WINDOW_S = 20, 6.0              # second session: contiguous windows spread over it
N_BOOT = 400
WITNESS = "joined"                       # or "all": every lit pixel in the region (0.1.0)
JOIN_PX = 3                              # a lit component joins the icon within this of its footprint


def joined(raw, region, tf):
    """The light joined to the self icon: lit components touching a band round its footprint.

    A teammate's cone is joined to that teammate's icon, not to ours, unless the
    two overlap; the drawn self cone starts under the icon. This uses no facing,
    so it favours no origin or angle.
    """
    import cv2
    lit = (raw & region).astype(np.uint8)
    fp = _footprint(raw.shape, tf).astype(np.uint8)
    band = cv2.dilate(fp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * JOIN_PX + 1,) * 2)) > 0
    n, lab = cv2.connectedComponents(lit, connectivity=8)
    keep = np.unique(lab[band & (lit > 0)])
    keep = keep[keep > 0]
    return np.isin(lab, keep) if len(keep) else np.zeros(raw.shape, bool)


def bisector(wit, tf):
    """Circular mean bearing of the witness beyond the apex, or None (E1's thresholds)."""
    ys, xs = np.nonzero(wit)
    d = np.hypot(xs - tf["x"], ys - tf["y"])
    k = d >= tt.L + 2.0
    if k.sum() < sem.LIGHT_MIN_PX:
        return None
    ang = np.arctan2(ys[k] - tf["y"], xs[k] - tf["x"])
    c, sn = np.cos(ang).mean(), np.sin(ang).mean()
    return math.degrees(math.atan2(sn, c)) if math.hypot(c, sn) >= sem.LIGHT_MIN_R else None


PLATEAU = 0.98                           # facings within 2% of the light's best F1


def light_facing(s, tf, wit, region, half=cone.CONE_HALF_ANGLE_DEG):
    """The facings whose cone from the teardrop centre best matches the joined light.

    Occlusion-aware, unlike the bisector: where a wall cuts one side of the cone,
    turning the cone into the wall changes nothing, so the plateau widens instead
    of the best facing moving. Returns (best facing, plateau as a 360-bool array).
    """
    vis = cone.raycast(s.passable, tf["x"], tf["y"], 0.0, half_angle_deg=180.0, visible=s.floor,
                       n_rays=N_RAYS_FULL, max_r=int(R_EVAL + 20))
    ys, xs = np.nonzero(region & vis)
    if not len(ys):
        return None, None
    b = np.floor(np.degrees(np.arctan2(ys - tf["y"], xs - tf["x"]))).astype(int) % 360
    n_all = np.bincount(b, minlength=360).astype(float)
    n_lit = np.bincount(b[wit[ys, xs]], minlength=360).astype(float)
    L = float(wit.sum())
    k = int(round(half))
    win = np.zeros(360)
    win[np.r_[0:k + 1, 360 - k:360]] = 1.0          # bins within `half` of facing 0
    conv = lambda v: np.real(np.fft.ifft(np.fft.fft(v) * np.conj(np.fft.fft(win))))
    hits, n = conv(n_lit), conv(n_all)
    f = 2.0 * hits / (n + L)
    best = int(np.argmax(f))
    return float(best), f >= PLATEAU * f[best]


def facing_vs_light(rows):
    """The read facing and the ring fit's raw facing against the light-fitted facing (E4c)."""
    out = {}
    for name, key in (("tip", "deg"), ("ring", "ring_deg")):
        e, inside, near = [], [], []
        for r in rows:
            lf, pl = r.get("lf"), r.get("plateau")
            d = r["tf"].get(key)
            if lf is None or d is None:
                continue
            e.append(float(sem._signed_deg(d - lf)))
            idx_ = np.arange(360)[np.unpackbits(pl, count=360).astype(bool)]
            gap = np.min(np.abs(sem._signed_deg(d - idx_))) if len(idx_) else 180.0
            inside.append(gap <= 0.5)
            near.append(gap <= 10.0)
        e = np.abs(np.array(e))
        out[f"lf_frames_{name}"] = len(e)
        out[f"lf_inside_{name}"] = float(np.mean(inside)) if inside else None
        out[f"lf_within10_{name}"] = float(np.mean(near)) if near else None
        out[f"lf_abs_median_{name}_deg"] = float(np.median(e)) if len(e) else None
        out[f"lf_flip_{name}"] = float(np.mean(e > 90)) if len(e) else None
    return out


def facing_vs_witness(rows):
    """The read facing and the ring fit's raw facing against the joined light's bisector."""
    out = {}
    for name, key in (("tip", "deg"), ("ring", "ring_deg")):
        e = np.array([float(sem._signed_deg(r["tf"][key] - r["phi"])) for r in rows
                      if r.get("phi") is not None and r["tf"].get(key) is not None])
        within = e[np.abs(e) <= 90.0]
        out[f"join_frames_{name}"] = int(len(e))
        out[f"join_flip_{name}"] = float((np.abs(e) > 90).mean()) if len(e) else None
        out[f"join_spread_{name}_deg"] = sem._robust_sd(within)
        out[f"join_bias_{name}_deg"] = float(np.median(within)) if len(within) else None
    return out


def _footprint(shape, tf):
    """The icon's own pixels: the teardrop grown by PAD, filled."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    m = tt.render(xx - tf["x"], yy - tf["y"], math.radians(tf["deg"]), r_in=0.0,
                  r_out=tt.R_OUT + PAD, L_=tt.L + PAD, edge=1.0)
    return m > 0


def region_of(s, tf):
    h, w = s.passable.shape
    yy, xx = np.mgrid[0:h, 0:w]
    return (np.hypot(xx - tf["x"], yy - tf["y"]) <= R_EVAL) & s.ref.known & ~_footprint((h, w), tf)


def origin(tf, a, c):
    th = math.radians(tf["deg"])
    return (tf["x"] + a * math.cos(th) - c * math.sin(th),
            tf["y"] + a * math.sin(th) + c * math.cos(th))


def grid_counts(s, tf, raw, region):
    """hits[a, c, h] and cone[a, c, h] pixel counts in the region; lit count."""
    L = raw & region
    ys, xs = np.nonzero(region)
    lit_here = L[ys, xs]
    hits = np.zeros((len(A_OFF), len(C_OFF), len(H_DEG)), np.int32)
    n = np.zeros_like(hits)
    for i, a in enumerate(A_OFF):
        for j, c in enumerate(C_OFF):
            ox, oy = origin(tf, a, c)
            vis = cone.raycast(s.passable, ox, oy, tf["deg"] % 360.0, half_angle_deg=180.0,
                               visible=s.floor, n_rays=N_RAYS_FULL, max_r=int(R_EVAL + 2 * abs(a) + 20))
            v = vis[ys, xs]
            ang = np.abs(sem._signed_deg(np.degrees(np.arctan2(ys[v] - oy, xs[v] - ox)) - tf["deg"]))
            srt = np.sort(ang)
            srt_lit = np.sort(ang[lit_here[v]])
            n[i, j] = np.searchsorted(srt, H_DEG, side="right")
            hits[i, j] = np.searchsorted(srt_lit, H_DEG, side="right")
    return hits, n, int(L.sum())


def f1(hits, n, lit):
    with np.errstate(invalid="ignore", divide="ignore"):
        return 2.0 * hits / (n + lit)


def best(H, N, Lsum):
    F = f1(H, N, Lsum)
    i = np.unravel_index(int(np.nanargmax(F)), F.shape)
    return (float(A_OFF[i[0]]), float(C_OFF[i[1]]), float(H_DEG[i[2]])), float(F[i])


def idx(p):
    return (int(np.argmin(np.abs(A_OFF - p[0]))), int(np.argmin(np.abs(C_OFF - p[1]))),
            int(np.argmin(np.abs(H_DEG - p[2]))))


def score_at(rows, p):
    i = idx(p)
    h = sum(r["hits"][i] for r in rows)
    n = sum(r["n"][i] for r in rows)
    L = sum(r["lit"] for r in rows)
    return {"f1": 2.0 * h / (n + L), "precision": h / n if n else None, "recall": h / L if L else None,
            "frames": len(rows)}


def fit(rows):
    H = sum(r["hits"] for r in rows).astype(float)
    N = sum(r["n"] for r in rows).astype(float)
    L = float(sum(r["lit"] for r in rows))
    return best(H, N, L)


def bootstrap(rows, seed=20260928):
    """Block bootstrap of the argmax: resample time blocks with replacement."""
    blocks = {}
    for r in rows:
        blocks.setdefault(r["block"], []).append(r)
    keys = list(blocks)
    Hb = {k: sum(r["hits"] for r in v).astype(float) for k, v in blocks.items()}
    Nb = {k: sum(r["n"] for r in v).astype(float) for k, v in blocks.items()}
    Lb = {k: float(sum(r["lit"] for r in v)) for k, v in blocks.items()}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(N_BOOT):
        pick = rng.choice(len(keys), len(keys), replace=True)
        H = sum(Hb[keys[k]] for k in pick)
        N = sum(Nb[keys[k]] for k in pick)
        L = sum(Lb[keys[k]] for k in pick)
        out.append(best(H, N, L)[0])
    out = np.array(out)
    return {name: (float(np.percentile(out[:, k], 2.5)), float(np.percentile(out[:, k], 97.5)),
                   float(np.std(out[:, k])))
            for k, name in enumerate(("along", "across", "half"))}, len(keys)


def read_frames(s, times, holdout=(), step=1):
    """Read the teardrop and the light on `times`; grid counts on every `step`-th distinct lit frame."""
    s.cache_t = np.asarray(sorted(times), float)
    tips = sem.read_tips(s)
    rows, prev, k = [], None, 0
    use = {t for t, f in tips.items() if f.get("read") and all(abs(t - h) > sem.HOLDOUT_MS for h in holdout)}
    for t, crop in s.crops(sorted(use)):
        tf = tips[t]
        key = (round(tf["x"], 3), round(tf["y"], 3), round(tf["deg"], 2))
        if key == prev:
            continue
        prev = key
        raw = lighting.raw_lit(crop, s.ref)
        reg = region_of(s, tf)
        wit = joined(raw, reg, tf) if WITNESS == "joined" else raw & reg
        if int(wit.sum()) < MIN_LIT:
            continue
        k += 1
        if (k - 1) % step:
            continue
        hits, n, lit = grid_counts(s, tf, wit, reg)
        lf, pl = light_facing(s, tf, wit, reg)
        rows.append({"t": t, "tf": tf, "hits": hits, "n": n, "lit": lit, "phi": bisector(wit, tf),
                     "lf": lf, "plateau": None if pl is None else np.packbits(pl),
                     "block": int(t // BLOCK_MS), "raw": np.packbits(raw), "wit": np.packbits(wit)})
    return tips, rows


def confirm(s, rows, params, far_only=False):
    """The owner's wedge: E3b's precision (whole cone, known floor) and recall (lit within 90 px)."""
    shape = s.passable.shape
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    k = s.ref.known
    out = {}
    for name, p in params.items():
        hit = tot = 0.0
        rec, f_h, f_n, f_l = [], 0.0, 0.0, 0.0
        for r in rows:
            tf = r["tf"]
            raw = np.unpackbits(r["raw"], count=shape[0] * shape[1]).reshape(shape).astype(bool)
            ox, oy = origin(tf, p[0], p[1])
            m = cone.raycast(s.passable, ox, oy, tf["deg"] % 360.0, half_angle_deg=p[2], visible=s.floor)
            tot += float((m & k).sum())
            hit += float((m & k & raw).sum())
            lit = raw & k & (np.hypot(xx - tf["x"], yy - tf["y"]) <= 90.0)
            if lit.sum() >= 50:
                rec.append(float((m & lit).sum() / lit.sum()))
            reg = region_of(s, tf)
            w = (np.unpackbits(r["wit"], count=shape[0] * shape[1]).reshape(shape).astype(bool)
                 if "wit" in r else raw & reg)
            f_h += float((m & w).sum())
            f_n += float((m & reg).sum())
            f_l += float(w.sum())
        out[name] = {"precision": hit / tot if tot else None, "recall": float(np.mean(rec)) if rec else None,
                     "f1_region": 2 * f_h / (f_n + f_l) if (f_n + f_l) else None, "frames": len(rows)}
    return out


def windows(s):
    T = np.unique(np.asarray(s.cache_t, float))
    span = T[-1] - T[0]
    starts = T[0] + (np.arange(WINDOWS) + 0.5) * span / WINDOWS
    out = []
    for w, t0 in enumerate(starts):
        sel = T[(T >= t0) & (T < t0 + WINDOW_S * 1000.0)]
        out.append((w, sel))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sheet", nargs=2, metavar=("SID", "PATH"))
    ap.add_argument("--second", default="5822b6646448")
    ap.add_argument("--step", type=int, default=1, help="grid every n-th distinct lit frame, second session")
    ap.add_argument("--out", type=Path, default=Path(sem.tempfile.gettempdir()) / "cone-origin")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--witness", choices=("joined", "all"), default="joined")
    args = ap.parse_args(argv)
    global WITNESS
    WITNESS = args.witness
    sem._below_normal()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.sheet:
        s = sem.Session(args.sheet[0])
        pick = [t for _, sel in windows(s) for t in sel[:: max(1, len(sel) // 2)][:2]]
        items = []
        for t, crop in s.crops(pick):
            det = tt.self_start(crop, s.floor)
            items.append((t, crop, det, tt.fit(crop, det["cx"], det["cy"]) if det else None))
        tt.sheet(Path(args.sheet[1]), items)
        print("wrote", args.sheet[1])
        return 0

    # Session A: the demo, every cached frame outside the sliver neighbourhoods.
    A = sem.Session(sem.DEMO)
    cal = sem.Calibration()
    A.run_chain(A.cache_t, calib=cal, holdout=sem.SLIVERS)     # E3b's frame set, for the instrument check
    tipsA, rowsA = read_frames(A, A.cache_t, holdout=sem.SLIVERS)
    print(f"A: {len(rowsA)} lit distinct frames", flush=True)
    # Instrument check: E3b's teardrop-centre arm on its own frames must reproduce 0.719.
    e3b_t = set(cal.frame_t)
    chk = [{"tf": tipsA[t], "raw": p} for (x, y, d, p, r), t in zip(cal.frames, cal.frame_t)
           if tipsA.get(t, {}).get("read")]
    inst = confirm(A, chk, {"e3b_tip_facing": BASE})["e3b_tip_facing"]
    print("instrument check (E3b precision_tip_facing 0.719):", inst, len(e3b_t), flush=True)

    fitA = [r for r in rowsA if r["block"] % 2 == 0]
    holdA = [r for r in rowsA if r["block"] % 2 == 1]
    pA, fA = fit(fitA)
    ciA, nbA = bootstrap(fitA)
    print("A fit:", pA, fA, ciA, flush=True)

    # Session B: contiguous windows, for the teardrop's precision and a second fit.
    B = sem.Session(args.second)
    wins = windows(B)
    wid = {float(t): w for w, sel in wins for t in sel}
    timesB = sorted(wid)
    tipsB, rowsB = read_frames(B, timesB, step=args.step)
    for r in rowsB:
        r["block"] = wid[float(r["t"])]
    print(f"B: {len(rowsB)} lit distinct frames (every {args.step})", flush=True)
    # tip_precision's jitter windows need consecutive frames, which the windows keep.
    PB = sem.tip_precision(tipsB, timesB)
    PA = sem.tip_precision(tipsA, [t for t in sorted(tipsA)
                                   if all(abs(t - h) > sem.HOLDOUT_MS for h in sem.SLIVERS)])
    print("B precision:", json.dumps(PB), flush=True)
    fitB = [r for r in rowsB if r["block"] % 2 == 0]
    holdB = [r for r in rowsB if r["block"] % 2 == 1]
    pB, fB = fit(fitB)
    ciB, nbB = bootstrap(fitB)
    pAll, _ = fit(rowsA + rowsB)
    print("B fit:", pB, fB, ciB, flush=True)

    arms = {"base": BASE, "fitA": pA, "fitB": pB, "pooled": pAll,
            "centre_fitted_half": (0.0, 0.0, pA[2])}
    grid = {}
    for set_name, rows in (("A_hold", holdA), ("A_fit", fitA), ("B_all", rowsB), ("B_hold", holdB)):
        grid[set_name] = {k: score_at(rows, p) for k, p in arms.items()}
    # Profile: best F1 over the other parameters at each along-offset, per session.
    prof = {}
    for nm, rows in (("A_hold", holdA), ("B_all", rowsB)):
        H = sum(r["hits"] for r in rows).astype(float)
        N = sum(r["n"] for r in rows).astype(float)
        L = float(sum(r["lit"] for r in rows))
        F = f1(H, N, L)
        prof[nm] = {"along": {float(a): float(np.nanmax(F[i])) for i, a in enumerate(A_OFF)},
                    "half": {float(h): float(np.nanmax(F[:, :, k])) for k, h in enumerate(H_DEG)}}
    conf = {"A_hold": confirm(A, holdA, {"base": BASE, "fitA": pA}),
            "B_all": confirm(B, rowsB, {"base": BASE, "fitA": pA, "fitB": pB})}
    res = {"version": VERSION, "tip_version": tt.VERSION, "instrument": inst,
           "fitA": {"params": pA, "f1": fA, "ci": ciA, "blocks": nbA, "frames": len(fitA)},
           "fitB": {"params": pB, "f1": fB, "ci": ciB, "blocks": nbB, "frames": len(fitB)},
           "pooled": pAll, "grid": grid, "profile": prof, "confirm": conf,
           "precision_A": PA, "precision_B": PB,
           "join_A": facing_vs_witness(rowsA), "join_B": facing_vs_witness(rowsB),
           "light_A": facing_vs_light(rowsA), "light_B": facing_vs_light(rowsB)}
    (args.out / f"results_e4_{WITNESS}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("profile",)}, indent=1))
    if args.no_record:
        return 0
    vals = {"instrument_precision": inst["precision"],
            "a_along": pA[0], "a_across": pA[1], "a_half": pA[2],
            "a_along_lo": ciA["along"][0], "a_along_hi": ciA["along"][1],
            "a_across_lo": ciA["across"][0], "a_across_hi": ciA["across"][1],
            "a_half_lo": ciA["half"][0], "a_half_hi": ciA["half"][1],
            "b_along": pB[0], "b_across": pB[1], "b_half": pB[2],
            "b_along_lo": ciB["along"][0], "b_along_hi": ciB["along"][1],
            "b_across_lo": ciB["across"][0], "b_across_hi": ciB["across"][1],
            "b_half_lo": ciB["half"][0], "b_half_hi": ciB["half"][1],
            "frames_a_fit": len(fitA), "frames_a_hold": len(holdA), "frames_b": len(rowsB),
            "blocks_a": nbA, "blocks_b": nbB}
    for set_name, d in grid.items():
        for arm, v in d.items():
            for m in ("f1", "precision", "recall"):
                vals[f"{set_name}_{arm}_{m}"] = v[m]
    for set_name, d in conf.items():
        for arm, v in d.items():
            for m in ("precision", "recall", "f1_region"):
                vals[f"confirm_{set_name}_{arm}_{m}"] = v[m]
    for k in ("read_rate", "frames_detected", "facing_jitter_rms20_deg", "tip_jitter_rms_px",
              "stationary_frames", "light_spread_tip_deg", "light_flip_tip", "light_frames_tip",
              "light_spread_ring_deg", "light_flip_ring", "light_spread_ring_e1_deg", "light_flip_ring_e1", "ring_offset_median_px",
              "ring_offset_cos_median", "ring_flip_vs_tip"):
        vals[f"b_{k}"] = PB.get(k)
    for sess, d in (("a", res["join_A"]), ("b", res["join_B"]), ("a", res["light_A"]), ("b", res["light_B"])):
        for k, v in d.items():
            vals[f"{sess}_{k}"] = v
    for nm, d in prof.items():
        for k in ("along", "half"):
            pk = max(d[k], key=d[k].get)
            vals[f"profile_{nm}_{k}_peak"] = pk
            vals[f"profile_{nm}_{k}_peak_f1"] = d[k][pk]
        vals[f"profile_{nm}_along_0_f1"] = d["along"][0.0]
    vals = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in vals.items()}
    metrics.record("cone_origin", part="e4" if WITNESS == "all" else "e4b-joined", session=f"{sem.DEMO}+{args.second}", values=vals,
                   deps={"prototype": VERSION, "reader": tt.VERSION, "lighting": lighting.LIGHTING_VERSION,
                         "grid": {"along": [A_OFF[0], A_OFF[-1]], "across": [C_OFF[0], C_OFF[-1]],
                                  "half": [H_DEG[0], H_DEG[-1]]},
                         "r_eval": R_EVAL, "witness": WITNESS, "join_px": JOIN_PX, "pad": PAD, "min_lit": MIN_LIT, "block_ms": BLOCK_MS,
                         "windows": [WINDOWS, WINDOW_S], "step_b": args.step,
                         "fact": "minimap/cone-origin-near-centre"},
                   context={"holdout_ms": sem.HOLDOUT_MS, "n_boot": N_BOOT})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
