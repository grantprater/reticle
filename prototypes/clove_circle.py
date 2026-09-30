r"""Measure the dead Clove's smoke-range circle on the minimap in one capture.

    .\.venv\Scripts\python.exe prototypes\clove_circle.py [--record]

Why this exists
---------------
The player, 2026-09-29: the smoke-range circle is drawn only for Clove and
only after her death, centred on the death location, while the dead Clove's
smoke menu is open, and it seemed to linger a split second after the smoke
was placed. This file measures that circle on the capture the player named,
`C:\Users\grant\Videos\2026-09-28 14-18-06.mp4` (Clove on Lotus, not
ingested, so no session hash and no crop cache). Predictions and outcomes are
in the store's `notes/predictions.jsonl` under `clove-circle-20260929`.

What it reads
-------------
Short ffmpeg accurate-seek decodes only: 45-75 s at 20 fps (the death at
about 47.9 s and the dead-Clove Ruse cast at 57-60.5 s), three 60 fps windows
around the transitions, and 156.7-158.4 s at 10 fps as the control (Clove
alive, targeting view open). Nothing is written but small PNGs and the sheet.

The widget placement comes from `widget_frame.fit_crop` against the baked
`lotus__valorant-16x9` static (the capture draws it 1.176x and rotated 180
degrees); every minimap coordinate here is in that baked frame, and the
capture decides nothing but the placement
[domain:capture/session-pixels-are-not-the-map]. The circle is fitted as a
shape: 360 rays from a centre, the steepest outward brightness drop on each
(its white rim over the static-subtracted crop), then a least-squares circle
with residual rejection, iterated. Presence is the ring contrast at the
fitted circle; the control also runs a free search over every centre in the
widget at radii 84-94 px. The self icon is fitted the same way on
saturation (its pale yellow rim against the grey floor).

Map units are not reported: the store holds no world-to-minimap transform.
Frames the placement owner calls undrawn (NCC under `MIN_NCC`: ghost hands
over the widget, bright spectator views, one camera-cut frame) are left out
of the fits and the absence test.

Results (2026-09-29)
--------------------
The circle's radius is
[metric:clove_circle/measure@2026-09-28_14-18-06#r_baked=89.73] baked px,
[metric:clove_circle/measure@2026-09-28_14-18-06#r_capture=105.5] capture
px, [metric:clove_circle/measure@2026-09-28_14-18-06#r_over_self_r=11.68]
self-icon rim radii; frame-to-frame sd
[metric:clove_circle/measure@2026-09-28_14-18-06#r_sd=0.013] px, median fit
rms [metric:clove_circle/measure@2026-09-28_14-18-06#fit_rms=0.36] px. Its
centre lies [metric:clove_circle/measure@2026-09-28_14-18-06#offset_self_last=0.51]
px from the self icon's last live position and
[metric:clove_circle/measure@2026-09-28_14-18-06#offset_x_settled=7.27] px
from the death X after the X drifted with the body. It appears at
[metric:clove_circle/measure@2026-09-28_14-18-06#t_appear=57.083] s,
[metric:clove_circle/measure@2026-09-28_14-18-06#lead_over_view_s=0.67] s
before the targeting view's map; the view closes and the Ruse disc is born at
[metric:clove_circle/measure@2026-09-28_14-18-06#t_placed=59.85] s; the
circle is gone at [metric:clove_circle/measure@2026-09-28_14-18-06#t_gone=60.5]
s, a linger of [metric:clove_circle/measure@2026-09-28_14-18-06#linger_s=0.65]
s that spans a spectator camera cut. With Clove alive and the view open, the
best in-widget ring score is
[metric:clove_circle/measure@2026-09-28_14-18-06#control_free_max=3.9]
against [metric:clove_circle/measure@2026-09-28_14-18-06#positive_free_min=22.6]
on drawn frames. Contact sheet:
`<store>/analysis/clove-circle-20260929/contact_sheet.png`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import geometry, metrics, widget_frame  # noqa: E402

cv2.setNumThreads(1)
VID = "C:/Users/grant/Videos/2026-09-28 14-18-06.mp4"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "clove-circle-20260929"
GEOM = geometry.path(geometry.key("lotus", "valorant-16x9"))
MM = (0, 0, 440, 440)             # capture crop holding the widget
MENU = (280, 300, 720, 720)       # capture crop holding the targeting view
IDLE = 0x40                       # IDLE_PRIORITY_CLASS for ffmpeg on Windows
VERSION = "clove-circle-0.1.0"
ANG = np.deg2rad(np.arange(0, 360, 1.0))


def decode(t0, dur, fps, crop, scale=None):
    x, y, w, h = crop
    vf = f"fps={fps},crop={w}:{h}:{x}:{y}"
    W, H = w, h
    if scale:
        vf += f",scale={scale[0]}:{scale[1]}"
        W, H = scale
    cmd = ["ffmpeg", "-v", "error", "-threads", "1", "-ss", f"{t0:.4f}", "-i", VID,
           "-t", f"{dur:.4f}", "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         creationflags=IDLE if os.name == "nt" else 0)
    raw = p.stdout.read()
    p.wait()
    a = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    return t0 + np.arange(len(a)) / fps, a


class Frame:
    """The baked frame: placement, static and the warp into it."""

    def __init__(self):
        z = np.load(GEOM)
        self.static = z["static"]
        self.h, self.w = self.static.shape[:2]
        self.sgray = cv2.cvtColor(self.static, cv2.COLOR_BGR2GRAY).astype(np.float32)
        self.fit = None

    def place(self, crop):
        self.fit = widget_frame.fit_crop(self.static, crop, (MM[0], MM[1]))
        self.A = np.array(self.fit["affine"], float)
        self.Ai = cv2.invertAffineTransform(self.A)
        return self.fit

    def baked(self, img):
        return cv2.warpAffine(img, self.Ai, (self.w, self.h), flags=cv2.INTER_LINEAR)

    def diff(self, img):
        g = cv2.cvtColor(self.baked(img), cv2.COLOR_BGR2GRAY).astype(np.float32)
        return cv2.GaussianBlur(g - self.sgray, (0, 0), 0.7)

    def widget_drawn(self, img):
        """The placement owner's own test: below MIN_NCC no widget is drawn."""
        return widget_frame.placement_ncc(self.static, img, (MM[0], MM[1]), self.A) >= widget_frame.MIN_NCC

    def to_capture(self, x, y):
        return (self.A @ np.array([x, y, 1.0])).tolist()


def profile(d, c, rs, ang=ANG):
    xs = (c[0] + np.outer(np.cos(ang), rs)).astype(np.float32)
    ys = (c[1] + np.outer(np.sin(ang), rs)).astype(np.float32)
    return cv2.remap(d.astype(np.float32), xs, ys, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=float("nan"))


def ringscore(d, c, r):
    """Median over rays of (just inside the rim) - (just outside it)."""
    v = profile(d, c, np.array([r - 3, r - 1, r + 2, r + 4]))
    with np.errstate(all="ignore"):
        s = np.nanmean(v[:, :2], 1) - np.nanmean(v[:, 2:], 1)
        return float(np.nanmedian(s))


def circfit(x, y):
    a = np.c_[2 * x, 2 * y, np.ones_like(x)]
    s = np.linalg.lstsq(a, x * x + y * y, rcond=None)[0]
    return s[0], s[1], float(np.sqrt(s[2] + s[0] ** 2 + s[1] ** 2))


def fit_circle(d, c0, r0, win=12.0, iters=4):
    """Edge points on rays (steepest outward drop), least-squares circle."""
    c, r = np.array(c0, float), float(r0)
    for _ in range(iters):
        rs = np.arange(r - win, r + win, 0.25)
        v = profile(d, c, rs)
        g = -(v[:, 4:] - v[:, :-4])
        ok = np.isfinite(g).all(1)
        k = np.argmax(np.where(np.isfinite(g), g, -1e9), 1)
        re, amp = rs[k + 2], g[np.arange(len(k)), k]
        x, y = c[0] + re * np.cos(ANG), c[1] + re * np.sin(ANG)
        m = ok & (amp > np.nanpercentile(amp[ok], 30))
        for _ in range(3):
            cx, cy, rr = circfit(x[m], y[m])
            res = np.hypot(x - cx, y - cy) - rr
            m = ok & (np.abs(res) < max(1.5, 2.5 * np.std(res[m]))) & (amp > 0)
        c, r, win = np.array([cx, cy]), rr, max(3.5, win / 2)
    res = np.hypot(x - c[0], y - c[1]) - r
    return {"cx": float(c[0]), "cy": float(c[1]), "r": float(r),
            "rms": float(np.sqrt(np.mean(res[m] ** 2))), "inliers": float(m.mean())}


def free_search(d, radii=np.arange(84, 96, 2.0), step=4.0):
    """The best ring score at any in-widget centre, radii 84-94 px."""
    xs, ys = np.arange(0, d.shape[1] + 1, step), np.arange(0, d.shape[0] + 1, step)
    best = (-1e9, None)
    for r in radii:
        acc = []
        for a in np.deg2rad(np.arange(0, 360, 4)):
            vals = []
            for rr in (r - 3, r - 1, r + 2, r + 4):
                mx = (xs[None, :] + rr * np.cos(a)).astype(np.float32).repeat(len(ys), 0)
                my = (ys[:, None] + rr * np.sin(a)).astype(np.float32).repeat(len(xs), 1)
                vals.append(cv2.remap(d, mx, my, cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_CONSTANT, borderValue=float("nan")))
            acc.append((vals[0] + vals[1]) / 2 - (vals[2] + vals[3]) / 2)
        acc = np.array(acc)
        with np.errstate(all="ignore"):
            s = np.nanmedian(acc, 0)
        s[np.isfinite(acc).mean(0) < 0.8] = np.nan
        k = int(np.nanargmax(s))
        if s.flat[k] > best[0]:
            best = (float(s.flat[k]), (float(xs[k % len(xs)]), float(ys[k // len(xs)]), float(r)))
    return best


def purple(menu_img):
    hsv = cv2.cvtColor(menu_img, cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 0] > 125) & (hsv[..., 0] < 160)
                  & (hsv[..., 1] > 70) & (hsv[..., 2] > 80)).mean())


def blue_x(b, win=(100, 183, 132, 212)):
    """Centroid of the blue death-X key inside a window of the baked crop."""
    x0, y0, x1, y1 = win
    w = b[y0:y1, x0:x1].astype(int)
    m = (w[..., 0] > 170) & (w[..., 0] - w[..., 2] > 90) & (w[..., 0] - w[..., 1] > 40)
    ys, xs = np.nonzero(m)
    return (float(xs.mean() + x0), float(ys.mean() + y0), int(m.sum())) if m.sum() >= 8 else None


def first_true(ts, flags):
    idx = np.nonzero(flags)[0]
    return float(ts[idx[0]]) if len(idx) else None


def edge(frame, t0, t1, test, fps=60):
    """Last frame where `test` is False and first where it is True, at 60 fps."""
    ts, a = decode(t0, t1 - t0, fps, MM)
    flags = np.array([test(im) for im in a])
    i = int(np.argmax(flags)) if flags.any() else None
    if i is None or i == 0:
        return {"before": None, "after": float(ts[i]) if i == 0 else None}
    return {"before": float(ts[i - 1]), "after": float(ts[i])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    try:
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    fr = Frame()
    _, a = decode(55.0, 0.05, 20, MM)
    place = fr.place(a[0])
    print("placement", place)
    scale = place["scale"]

    ts, mm = decode(45.0, 30.0, 20, MM)
    _, menu = decode(45.0, 30.0, 20, MENU, scale=(180, 180))
    diffs = [fr.diff(im) for im in mm]
    blank = np.array([not fr.widget_drawn(im) for im in mm])   # camera-cut frames

    # Fit on the first frame of the menu's full view, then everywhere drawn.
    i58 = int(round((58.0 - 45.0) * 20))
    ref = fit_circle(diffs[i58], (122.0, 195.0), 90.0)
    c0, r0 = (ref["cx"], ref["cy"]), ref["r"]
    score = np.array([ringscore(d, c0, r0) for d in diffs])
    drawn = (score > 10) & ~blank
    fits = [dict(fit_circle(diffs[i], c0, r0), t=float(ts[i])) for i in np.nonzero(drawn)[0]]
    R = np.array([f["r"] for f in fits])
    CX = np.array([f["cx"] for f in fits])
    CY = np.array([f["cy"] for f in fits])
    RMS = np.array([f["rms"] for f in fits])
    INL = np.array([f["inliers"] for f in fits])
    cx, cy, r = float(np.median(CX)), float(np.median(CY)), float(np.median(R))

    # The self icon's rim, alive, up to the death; then the X that replaces it.
    sfits, last_alive, x_first = [], None, None
    for i in range(len(ts)):
        if ts[i] > 49.0:
            break
        b = fr.baked(mm[i])
        bx = blue_x(b)
        if bx is not None:
            x_first = x_first or dict(t=float(ts[i]), x=bx[0], y=bx[1], n=bx[2])
            continue
        if ts[i] < 46.5 or x_first:
            continue
        sat = cv2.GaussianBlur(cv2.cvtColor(b, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32), (0, 0), 0.6)
        s0 = (sfits[-1]["cx"], sfits[-1]["cy"]) if sfits else (122.5, 195.0)
        f = dict(fit_circle(sat, s0, 6.0, win=3.5), t=float(ts[i]))
        sfits.append(f)
        last_alive = f
    self_r = float(np.median([f["r"] for f in sfits]))
    xs_settled = [blue_x(fr.baked(mm[i])) for i in range(len(ts)) if 52.0 <= ts[i] <= 56.0]
    xs_settled = [x for x in xs_settled if x]
    x_settled = (float(np.median([x[0] for x in xs_settled])), float(np.median([x[1] for x in xs_settled])))

    # Coarse timeline at 20 fps.
    pur = np.array([purple(m) for m in menu])
    t_on, t_off_last = first_true(ts, drawn), float(ts[np.nonzero(drawn)[0][-1]])
    view = pur > 0.1
    t_view_on = first_true(ts, view & (ts > 55))
    t_view_last = float(ts[np.nonzero(view & (ts < 62))[0][-1]])
    # The Ruse cloud's dark disc on the minimap: mean grey in a 4 px disc.
    disc_c = (138.0, 268.0)
    yy, xx = np.mgrid[:fr.h, :fr.w]
    dmask = np.hypot(xx - disc_c[0], yy - disc_c[1]) < 4

    def disc_dark(im):
        return float(cv2.cvtColor(fr.baked(im), cv2.COLOR_BGR2GRAY)[dmask].mean())

    # 60 fps refinement of the three transitions.
    e_on = edge(fr, t_on - 0.1, t_on + 0.05, lambda im: ringscore(fr.diff(im), c0, r0) > 10)
    e_off = edge(fr, t_off_last - 0.05, t_off_last + 0.1,
                 lambda im: fr.widget_drawn(im) and ringscore(fr.diff(im), c0, r0) < 5)
    base = disc_dark(mm[int(round((59.5 - 45) * 20))])
    e_disc = edge(fr, t_view_last - 0.05, t_view_last + 0.15, lambda im: disc_dark(im) < base - 25)
    tv, mv = decode(t_view_last - 0.05, 0.2, 60, MENU, scale=(180, 180))
    pv = np.array([purple(m) for m in mv]) > 0.1
    k = int(np.argmin(pv)) if (~pv).any() else None
    e_view = {"before": float(tv[k - 1]) if k else None, "after": float(tv[k]) if k is not None else None}

    # Control: Clove alive with the targeting view open.
    cts, ctl = decode(156.7, 1.75, 10, MM)
    _, cmenu = decode(156.7, 1.75, 10, MENU, scale=(180, 180))
    ctl_rows = []
    for t, im, m in zip(cts, ctl, cmenu):
        d = fr.diff(im)
        best = free_search(d)
        ctl_rows.append({"t": float(t), "purple": purple(m), "ref": ringscore(d, c0, r0),
                         "free": best[0], "at": best[1]})
    pos_free = [free_search(diffs[int(round((t - 45) * 20))])[0] for t in (57.1, 58.0, 60.45)]

    placement_t = e_view["after"]
    res = {
        "version": VERSION, "placement": place, "scale": scale,
        "r_baked": r, "r_capture": r * scale, "r_sd": float(R.std()),
        "r_min": float(R.min()), "r_max": float(R.max()),
        "centre_baked": [cx, cy], "centre_sd": [float(CX.std()), float(CY.std())],
        "fit_rms_median": float(np.median(RMS)), "fit_rms_max": float(RMS.max()),
        "fit_inliers_median": float(np.median(INL)), "fit_inliers_min": float(INL.min()),
        "n_drawn": int(drawn.sum()),
        "self_r_baked": self_r, "r_over_self_r": r / self_r,
        "self_last": last_alive, "x_first": x_first, "x_settled": x_settled,
        "offset_self_last": float(np.hypot(cx - last_alive["cx"], cy - last_alive["cy"])),
        "offset_x_first": float(np.hypot(cx - x_first["x"], cy - x_first["y"])),
        "offset_x_settled": float(np.hypot(cx - x_settled[0], cy - x_settled[1])),
        "t_death_x": x_first["t"], "t_on_20": t_on, "t_last_20": t_off_last,
        "t_view_on_20": t_view_on, "t_view_last_20": t_view_last,
        "edge_on": e_on, "edge_off": e_off, "edge_view_close": e_view, "edge_disc": e_disc,
        "undrawn_frames": [float(t) for t in ts[blank]],
        "linger_s": e_off["after"] - placement_t,
        "lead_over_view_s": t_view_on - e_on["after"],
        "control": ctl_rows, "control_free_max": max(c["free"] for c in ctl_rows),
        "control_ref_max": max(abs(c["ref"]) for c in ctl_rows),
        "positive_free_min": min(pos_free),
        "absent_ref_max": float(np.abs(score[~drawn & ~blank]).max()),
    }
    (OUT / "results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "control"}, indent=1))
    make_sheet(fr, res, c0, r0)
    if args.record:
        record_run(res)
    return 0


def make_sheet(fr, res, c0, r0):
    """Frames bracketing each event, in the capture's own orientation."""
    cx, cy = res["centre_baked"]
    r_cap = res["r_capture"]
    pc = fr.to_capture(cx, cy)
    sl = res["self_last"]
    ps = fr.to_capture(sl["cx"], sl["cy"])
    pxs = fr.to_capture(*res["x_settled"])
    eo, ef, ev = res["edge_on"], res["edge_off"], res["edge_view_close"]
    picks = [(sl["t"], "last alive: self icon rim fit"), (res["t_death_x"], "death X first drawn"),
             (eo["before"], "no circle"), (eo["after"], "circle appears"),
             (res["t_view_on_20"], "targeting view opens"), (ev["before"], "view open, last"),
             (ev["after"], "view closed, Ruse disc born"), (ef["before"], "circle last drawn"),
             (ef["after"], "circle gone"), (157.8, "CONTROL alive, view open")]
    tiles = []
    for t, label in picks:
        _, a = decode(t, 1 / 60, 60, MM)
        _, m = decode(t, 1 / 60, 60, MENU, scale=(300, 300))
        im = a[0].copy()
        drawn = ringscore(fr.diff(a[0]), c0, r0) > 10
        big = cv2.resize(im, (660, 660), interpolation=cv2.INTER_CUBIC)
        k = 660 / 440
        col = (0, 0, 255) if drawn else (160, 160, 160)
        # Ticks just outside the fitted rim, so the drawn rim itself stays visible.
        for a in np.deg2rad(np.arange(0, 360, 22.5)):
            p0 = (pc[0] + (r_cap + 4) * np.cos(a), pc[1] + (r_cap + 4) * np.sin(a))
            p1 = (pc[0] + (r_cap + 11) * np.cos(a), pc[1] + (r_cap + 11) * np.sin(a))
            cv2.line(big, (int(p0[0] * k), int(p0[1] * k)), (int(p1[0] * k), int(p1[1] * k)), col, 2, cv2.LINE_AA)
        cv2.drawMarker(big, (int(pc[0] * k), int(pc[1] * k)), (0, 0, 255), cv2.MARKER_CROSS, 8, 1)
        cv2.circle(big, (int(ps[0] * k), int(ps[1] * k)), 3, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.drawMarker(big, (int(pxs[0] * k), int(pxs[1] * k)), (255, 128, 0), cv2.MARKER_DIAMOND, 8, 1)
        if t == sl["t"]:
            cv2.circle(big, (int(ps[0] * k), int(ps[1] * k)), int(round(sl["r"] * res["scale"] * k)),
                       (0, 255, 255), 1, cv2.LINE_AA)
        tile = np.zeros((690, 960, 3), np.uint8)
        tile[30:, :660] = big
        tile[30:330, 660:960] = m[0]
        txt = f"{t:.3f} s  {label}  ({'circle drawn' if drawn else 'no circle'})"
        cv2.putText(tile, txt, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        leg = ["red ticks: fitted circle, just outside", "  its rim (grey: same place, absent)",
               "red +: fitted centre", "yellow o: self icon at last alive frame",
               "orange diamond: death X after drift",
               "right: targeting-view crop"]
        for j, s in enumerate(leg):
            cv2.putText(tile, s, (666, 360 + 24 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
        tiles.append(tile)
    rows = [np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
    head = np.zeros((40, rows[0].shape[1], 3), np.uint8)
    cv2.putText(head, (f"Dead-Clove smoke-range circle, 2026-09-28 14-18-06.mp4 (Lotus). r = {res['r_baked']:.2f} baked px "
                       f"= {res['r_capture']:.1f} capture px = {res['r_over_self_r']:.1f} x self-icon rim; "
                       f"fit rms {res['fit_rms_median']:.2f} px"),
                (8, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "contact_sheet.png"), np.vstack([head] + rows))


def record_run(res):
    v = {"r_baked": round(res["r_baked"], 2), "r_capture": round(res["r_capture"], 1),
         "r_sd": round(res["r_sd"], 3), "fit_rms": round(res["fit_rms_median"], 2),
         "fit_inliers": round(res["fit_inliers_median"], 2), "n_drawn": res["n_drawn"],
         "self_r_baked": round(res["self_r_baked"], 2), "r_over_self_r": round(res["r_over_self_r"], 2),
         "offset_self_last": round(res["offset_self_last"], 2),
         "offset_x_first": round(res["offset_x_first"], 2),
         "offset_x_settled": round(res["offset_x_settled"], 2),
         "t_death": round(res["t_death_x"], 2),
         "t_appear": round(res["edge_on"]["after"], 3),
         "t_view_open": round(res["t_view_on_20"], 2),
         "t_placed": round(res["edge_view_close"]["after"], 3),
         "t_disc_born": round(res["edge_disc"]["after"], 3) if res["edge_disc"]["after"] else None,
         "t_gone": round(res["edge_off"]["after"], 3),
         "linger_s": round(res["linger_s"], 3), "lead_over_view_s": round(res["lead_over_view_s"], 2),
         "control_free_max": round(res["control_free_max"], 1),
         "positive_free_min": round(res["positive_free_min"], 1)}
    metrics.record("clove_circle", part="measure", session="2026-09-28_14-18-06",
                   values=v,
                   deps={"version": VERSION, "geometry": "lotus__valorant-16x9",
                         "widget_frame": widget_frame.WIDGET_FRAME_VERSION},
                   context={"capture": VID, "span": "45-75 s at 20 fps, edges at 60 fps",
                            "control": "156.7-158.4 s at 10 fps"},
                   note="dead-Clove smoke-range circle; capture not ingested, session is the file stem")


if __name__ == "__main__":
    sys.exit(main())
