r"""Measure the minimap's self audio circle and score it as a witness of the player's own sounds.

    .\.venv\Scripts\python.exe prototypes\audio_circle.py scan SESSION [--t0 S --t1 S]
    .\.venv\Scripts\python.exe prototypes\audio_circle.py score [--round N] [--figure N] [--sheet] [--record]
    .\.venv\Scripts\python.exe prototypes\audio_circle.py radius SESSION TAG [--record]

Why this exists
---------------
The player, 2026-09-29, named a pale circle round the self icon, drawn on
every sound the player makes, lingering after it, at one radius whatever the
sound, for the player's own icon only [domain:minimap/self-audio-circle].
This file measures its radius and time course and scores its onsets against
`sound_match.py`'s bank detections on the Iso capture (4f207c0c4e39,
`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`). Predictions and outcomes
are in the store's `notes/predictions.jsonl` under `audio-circle-20260929`.

What it reads
-------------
The minimap crop cache (`roi_cache`, 15 Hz inside each round) normalised into
the baked widget frame by the session's stored placement; the baked
`(map, profile)` static as the only background
[domain:capture/session-pixels-are-not-the-map]; the stored self track
(`l1/minimap`), tray-kit spans (whose view is shown) and the cached audio
detections. No video decode.

The circle is fitted as a shape, never repaired. `scan` samples the
static-subtracted crop on rays round the stored self position (and centres
within +-4 px of it, since the stored position is noisy) and keeps, per
frame, the ring score at every radius: the median over rays of the grey just
inside minus just outside (`clove_circle.ringscore`'s definition, evaluated
on a grid). `score` finds the radius from the median curve, marks the circle
drawn by hysteresis on that score, and fits exact circles on drawn frames
with `clove_circle.fit_circle`.

Results (2026-09-29)
--------------------
Radius. On the Iso capture's Split widget (331 baked px) the fitted radius is
[metric:audio_circle/score@4f207c0c4e39#r_baked_median=74.86] px, sd
[metric:audio_circle/score@4f207c0c4e39#r_baked_sd=0.169], over
[metric:audio_circle/score@4f207c0c4e39#radius_fits_good=86] onsets;
footstep, jump, land, equip and no-detection onsets agree within half a
pixel. The self rim fits at
[metric:audio_circle/score@4f207c0c4e39#self_r_baked=7.21] px, so the circle
spans [metric:audio_circle/score@4f207c0c4e39#r_over_self_r=10.38] rims. On
Lotus 5822b6646448 (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`, bigmap
widget 465 px) the 38-56 s circle measures
[metric:audio_circle/radius-38-56@5822b6646448#r_baked=108.45] px, sd
[metric:audio_circle/radius-38-56@5822b6646448#r_sd=0.169], or
[metric:audio_circle/radius-38-56@5822b6646448#r_over_self_r=11.83] rims. Its
centre follows the moving self icon within a median
[metric:audio_circle/radius-38-56@5822b6646448#centre_offset_from_self_median=2.59]
px, so it is this circle, not a dead Clove's. Icons keep their size while map
scales differ, so the rim multiple differs by map.

Time course, at 15 Hz. The circle appears within one frame (0.07, 0.90, 1.00
of plateau) and fades through one intermediate frame. The modal clean run
lasts 0.5-0.6 s, median
[metric:audio_circle/score@4f207c0c4e39#run_mode_median_s=0.517] s: one
sound's circle. A run holding several own-sound detections ends a median
[metric:audio_circle/score@4f207c0c4e39#multi_after_last_median=0.333] s after
the last, so a new sound extends it.

Witness agreement. Only
[metric:audio_circle/score@4f207c0c4e39#onset_share_with_own_sound=0.347] of
[metric:audio_circle/score@4f207c0c4e39#onsets_own=98] own-view onsets hold an
own-sound detection within +-0.30 s. The lag median is
[metric:audio_circle/score@4f207c0c4e39#lag_median=-0.005] s over a flat
histogram: chance. Own-sound detections fall with the circle
[metric:audio_circle/score@4f207c0c4e39#own_sound_det_share_with_circle=0.464]
of the time, others'
[metric:audio_circle/score@4f207c0c4e39#others_det_share_with_circle=0.459]:
the bank's level split carries no information about the circle. Buy-phase
equip and buy-menu sounds draw none, and HUD firing brackets at 901.0-902.5 s
and 1120.9-1122.9 s show the magazine falling with no circle. The
disagreements are in `analysis/audio-circle-20260929/disagreements-all.jsonl`.

Loudness. Radius does not follow level (rho
[metric:audio_circle/score@4f207c0c4e39#rho_level_radius=-0.09]). Ring
contrast follows it across onsets (rho
[metric:audio_circle/score@4f207c0c4e39#rho_level_ring=0.514]) but not within
a run, where the background under the rim holds still (rho
[metric:audio_circle/score@4f207c0c4e39#rho_level_ring_within_run=0.045]):
the background, not the sound, sets the contrast.

Spectating. Onsets come at
[metric:audio_circle/score@4f207c0c4e39#view_own_per_s=0.2678] per second in
the player's own view and
[metric:audio_circle/score@4f207c0c4e39#view_other_per_s=0.0199] while
spectating.

Spike. The one cached detonation (round 16, about 1581.4 s) draws no circle
on the minimap, so the explosion radius cannot be compared here.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
from reticle import geometry  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

import clove_circle as cc  # noqa: E402

cv2.setNumThreads(1)
VERSION = "audio-circle-0.1.0"
STORE = Store()
OUT = STORE.root / "analysis" / "audio-circle-20260929"
RAYS = np.deg2rad(np.arange(0, 360, 3.0))
OFFS = np.array([(dx, dy) for dy in (-4, -2, 0, 2, 4) for dx in (-4, -2, 0, 2, 4)], float)
R_LO, R_HI = 0.12, 0.42           # searched radii, fractions of the widget width
SELF_WIN_MS = 200.0               # the self position is the stored track's median over +-this


def idle() -> None:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)     # IDLE_PRIORITY_CLASS


class Session:
    """A session's cache, baked static and self track."""

    def __init__(self, sid: str):
        self.sid = sid
        self.man = STORE.read_manifest(sid)
        self.cache, why = RoiCache.load(STORE.root, self.man, get_profile(self.man["source_profile"]), "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap cache ({why})")
        self.rect = self.cache.rect_of("minimap")
        self.key = geometry.key_of(sid)
        self.static = geometry.reference_static(sid)
        self.sgray = cv2.cvtColor(self.static, cv2.COLOR_BGR2GRAY).astype(np.float32)
        self.W = self.static.shape[1]
        import pyarrow.parquet as pq
        p = next((STORE.root / "l1" / "minimap").glob(f"date=*/session={sid}/minimap.parquet"))
        t = pq.read_table(p).to_pydict()
        self.mt = np.asarray(t["t_ms"], float)
        self.sx = np.array([np.nan if v is None else v for v in t["self_x"]], float)
        self.sy = np.array([np.nan if v is None else v for v in t["self_y"]], float)
        self.drawn = np.array([bool(v) for v in t["widget_drawn"]])
        o = np.argsort(self.mt, kind="stable")
        self.mt, self.sx, self.sy, self.drawn = self.mt[o], self.sx[o], self.sy[o], self.drawn[o]
        self.radii = np.arange(int(R_LO * self.W), int(R_HI * self.W) + 1, 1.0)

    def self_at(self, t_ms: float):
        """(the median stored self position within +-SELF_WIN_MS, or None when fewer
        than two are stored there; the stored widget_drawn at t_ms, or None).

        The median, since the stored track jumps by 10 px or more on single
        frames (4f207c0c4e39 at 42.70 s), which the +-4 px centre grid misses."""
        i = int(np.argmin(np.abs(self.mt - t_ms)))
        drawn = bool(self.drawn[i]) if abs(self.mt[i] - t_ms) <= 1.0 else None
        a, b = np.searchsorted(self.mt, t_ms - SELF_WIN_MS), np.searchsorted(self.mt, t_ms + SELF_WIN_MS, "right")
        ok = np.isfinite(self.sx[a:b])
        if ok.sum() < 2:
            return None, drawn
        return (float(np.median(self.sx[a:b][ok])), float(np.median(self.sy[a:b][ok]))), drawn

    def crops(self, t_list):
        x0, y0, x1, y1 = self.rect
        for s in self.cache.samples(list(t_list), rois=["minimap"]):
            yield s.t_ms, s.frame[y0:y1, x0:x1]

    def diff(self, crop):
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return cv2.GaussianBlur(g - self.sgray, (0, 0), 0.7)


def ring_curve(d, c, radii):
    """Per centre offset, the ring score at every radius: median over rays of
    mean(r-3, r-1) - mean(r+2, r+4). Returns [len(OFFS), len(radii)]."""
    rs = np.arange(radii[0] - 3, radii[-1] + 5, 1.0)
    out = np.full((len(OFFS), len(radii)), np.nan, np.float32)
    for k, (dx, dy) in enumerate(OFFS):
        v = cc.profile(d, (c[0] + dx, c[1] + dy), rs, RAYS)
        j = np.arange(len(radii)) + 3                  # index of radius r in rs
        s = (v[:, j - 3] + v[:, j - 1]) / 2 - (v[:, j + 2] + v[:, j + 4]) / 2
        with np.errstate(all="ignore"):
            ok = np.isfinite(s).mean(0) >= 0.6
            m = np.nanmedian(s, 0)
        m[~ok] = np.nan
        out[k] = m
    return out


def scan(sid: str, t0: float | None, t1: float | None) -> Path:
    """Ring-score curves at every cached frame (optionally between t0 and t1 s)."""
    S = Session(sid)
    held = [t for t in S.cache.holds()
            if (t0 is None or t >= t0 * 1000) and (t1 is None or t <= t1 * 1000)]
    T, SX, SY, DR, CUR, OFF = [], [], [], [], [], []
    for n, (t, crop) in enumerate(S.crops(held)):
        me, drawn = S.self_at(t)
        T.append(t)
        DR.append(-1 if drawn is None else int(drawn))
        if me is None:
            SX.append(np.nan); SY.append(np.nan)
            CUR.append(np.full(len(S.radii), np.nan, np.float16)); OFF.append(-1)
            continue
        cur = ring_curve(S.diff(crop), me, S.radii)
        with np.errstate(all="ignore"):
            best = np.nanmax(cur, 0)
        SX.append(me[0]); SY.append(me[1])
        CUR.append(best.astype(np.float16))
        OFF.append(int(np.nanargmax(np.nan_to_num(cur, nan=-1e9).max(1))))
        if n % 2000 == 0:
            print(f"{sid} {t / 1000:8.2f} s  frame {n}/{len(held)}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "all" if t0 is None and t1 is None else f"{t0 or 0:g}-{t1 or 0:g}"
    path = OUT / f"{sid}-curves-{tag}.npz"
    np.savez_compressed(path, t_ms=np.array(T), self_x=np.array(SX), self_y=np.array(SY),
                        widget_drawn=np.array(DR), curve=np.array(CUR), off=np.array(OFF),
                        radii=S.radii, info=json.dumps({"version": VERSION, "session": sid, "key": S.key,
                                                        "hz": S.cache.record["hz"], "rect": S.rect}))
    print(f"{len(T)} frames -> {path}")
    return path


# ---------------------------------------------------------------- scoring

ISO = "4f207c0c4e39"
#: Hysteresis on the ring score at the circle's radius. A cut in the empty band
#: between the absent mode and the drawn plateau of the whole match's
#: own-view histogram (`score` prints it); set before the agreement was scored.
T_HI, T_LO = 8.0, 5.0
#: A clean onset or offset needs this many finite frames under T_LO on its far side.
CLEAN = 2
#: Own sound: a bank detection whose left-right level difference is under this.
OWN_ILD_DB = 1.0
#: Agreement window, audio time minus circle onset (first drawn frame), seconds.
WIN = (-0.30, 0.30)
#: An isolated own sound has no other own-sound detection within this many seconds.
ISOLATED_S = 2.0
#: The self icon's rim radius on the Lotus 331 px widget (clove_circle's fit), the seed
#: for the rim fit here, scaled by widget width.
SELF_R_SEED = 7.68 / 331.0
#: A rim fit counts when its rms is under this (px); the rim is a teardrop, not a circle.
RIM_RMS_MAX = 1.0


def load_curves(sid: str, tag: str = "all"):
    z = np.load(OUT / f"{sid}-curves-{tag}.npz")
    info = json.loads(str(z["info"]))
    return {k: z[k] for k in z.files if k != "info"}, info


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def circle_radius(C, radii, sel) -> tuple[float, int]:
    """The radius where the 90th percentile of the ring score over `sel` frames peaks."""
    with np.errstate(all="ignore"):
        p90 = np.nanpercentile(C[sel].astype(float), 90, 0)
    k = int(np.nanargmax(p90))
    return float(radii[k]), k


def states(score: np.ndarray) -> np.ndarray:
    """1 drawn, 0 absent, -1 unknown (no self position): hysteresis on T_HI/T_LO,
    carried across unknown frames."""
    st = np.full(len(score), -1, int)
    cur = 0
    for i, s in enumerate(score):
        if not np.isfinite(s):
            continue
        if cur == 0 and s >= T_HI:
            cur = 1
        elif cur == 1 and s < T_LO:
            cur = 0
        st[i] = cur
    return st


def drawn_runs(t, st, score) -> list[dict]:
    """Drawn runs with clean edges: CLEAN finite absent frames before and after."""
    out = []
    fin = np.nonzero(st >= 0)[0]
    fs = st[fin]
    i = 0
    while i < len(fin):
        if fs[i] != 1:
            i += 1
            continue
        j = i
        while j + 1 < len(fin) and fs[j + 1] == 1:
            j += 1
        a, b = fin[i], fin[j]
        pre = fin[max(0, i - CLEAN):i]
        post = fin[j + 1:j + 1 + CLEAN]
        clean_on = len(pre) == CLEAN and (fs[max(0, i - CLEAN):i] == 0).all() and t[a] - t[pre[0]] < 0.25
        clean_off = len(post) == CLEAN and (fs[j + 1:j + 1 + CLEAN] == 0).all() and t[post[-1]] - t[b] < 0.25
        out.append({"i_on": int(a), "i_off": int(b), "t_on": float(t[a]), "t_off": float(t[b]),
                    "t_before": float(t[pre[-1]]) if len(pre) else None,
                    "t_after": float(t[post[0]]) if len(post) else None,
                    "clean_on": bool(clean_on), "clean_off": bool(clean_off),
                    "peak": float(np.nanmax(score[a:b + 1]))})
        i = j + 1
    return out


def score_iso(only: int | None, record: bool, fig_round: int | None) -> dict:
    import sound_match as sm
    z, info = load_curves(ISO)
    t = z["t_ms"] / 1000.0
    radii = z["radii"]
    C = z["curve"].astype(float)
    spans = sm.pov_spans()
    pov = np.array([sm.pov_at(spans, x) or "none" for x in t])
    rr = sm.rounds()
    ch = sm.chunks()
    rno = np.array([next((r for r, a, b in ch if a <= x < b), -1) for x in t])
    sel_round = np.ones(len(t), bool) if only is None else rno == only
    own = (pov == "own") & sel_round
    R0, k0 = circle_radius(C, radii, own & np.isfinite(C).all(1))
    score = np.nanmax(C[:, max(0, k0 - 2):k0 + 3], 1)
    hist_own = np.histogram(score[own & np.isfinite(score)], bins=np.arange(-4, 30, 1.0))[0].tolist()
    st = states(score)
    rs = drawn_runs(t, st, score)
    for r in rs:
        r["pov"] = pov[r["i_on"]]
        r["round"] = int(rno[r["i_on"]])
    rs = [r for r in rs if sel_round[r["i_on"]]]
    dets = sm.load_dets(only)
    for d in dets:
        d["pov"] = sm.pov_at(spans, d["t"])
        d["own_sound"] = abs(d["ild_db"]) < OWN_ILD_DB
    own_snd = [d for d in dets if d["pov"] == "own" and d["own_sound"]]
    ot = np.array([d["t"] for d in own_snd])
    at = np.array([d["t"] for d in dets])
    res = {"version": VERSION, "session": ISO, "rounds": only, "R0_baked": R0, "radii_searched": [float(radii[0]), float(radii[-1])],
           "T_HI": T_HI, "T_LO": T_LO, "window": WIN, "own_ild_db": OWN_ILD_DB, "hz": info["hz"],
           "hist_own_score": hist_own}

    # -- Q3 agreement: circle onsets (own view, clean) vs own-sound detections.
    ons = [r for r in rs if r["pov"] == "own" and r["clean_on"]]
    rows = []
    for r in ons:
        lag = ot - r["t_on"]
        m = (lag >= WIN[0]) & (lag <= WIN[1])
        anyd = (at - r["t_on"] >= WIN[0]) & (at - r["t_on"] <= WIN[1])
        best = int(np.argmin(np.abs(np.where(m, lag, 99)))) if m.any() else None
        rows.append({**{k: r[k] for k in ("t_on", "t_before", "t_off", "clean_off", "peak", "round")},
                     "lag": float(lag[best]) if best is not None else None,
                     "det": own_snd[best] if best is not None else None,
                     "any_det": [dets[j]["cls"] + f"({dets[j]['ild_db']:+.1f})" for j in np.nonzero(anyd)[0]]})
    lags = np.array([x["lag"] for x in rows if x["lag"] is not None])
    res["onsets_own"] = len(rows)
    res["onsets_with_own_sound"] = int(len(lags))
    res["onset_share_with_own_sound"] = round(len(lags) / len(rows), 3) if rows else None
    res["onsets_without_any_det"] = sum(1 for x in rows if not x["any_det"])
    res["onset_share_without_any_det"] = round(res["onsets_without_any_det"] / len(rows), 3) if rows else None
    if len(lags):
        res["lag_median"] = round(float(np.median(lags)), 3)
        res["lag_p10"] = round(float(np.percentile(lags, 10)), 3)
        res["lag_p90"] = round(float(np.percentile(lags, 90)), 3)
        res["lag_hist_0.067"] = np.histogram(lags, bins=np.arange(-0.30, 0.3001, 1 / 15))[0].tolist()
    # own-view own-sound detections: circle drawn at any frame within the window around them
    drawn_t = t[st == 1]
    fin_t = t[st >= 0]
    det_rows = []
    for d in own_snd:
        w = (fin_t >= d["t"] - WIN[1]) & (fin_t <= d["t"] - WIN[0])
        if not w.any():
            det_rows.append({**d, "circle": None})
            continue
        hit = ((drawn_t >= d["t"] - WIN[1]) & (drawn_t <= d["t"] - WIN[0])).any()
        det_rows.append({**d, "circle": bool(hit)})
    seen = [x for x in det_rows if x["circle"] is not None]
    res["own_sound_dets"] = len(own_snd)
    res["own_sound_dets_observed"] = len(seen)
    res["own_sound_dets_with_circle"] = sum(x["circle"] for x in seen)
    res["own_sound_det_share_with_circle"] = round(res["own_sound_dets_with_circle"] / len(seen), 3) if seen else None
    by = defaultdict(lambda: [0, 0])
    for x in seen:
        by[x["cls"]][0] += 1
        by[x["cls"]][1] += int(x["circle"])
    res["own_sound_by_class"] = {c: {"n": v[0], "with_circle": v[1], "share": round(v[1] / v[0], 3)}
                                 for c, v in sorted(by.items())}
    # spatialised (others') detections in own view, the control
    oth = [d for d in dets if d["pov"] == "own" and abs(d["ild_db"]) >= 2.0]
    oc = []
    for d in oth:
        w = (fin_t >= d["t"] - WIN[1]) & (fin_t <= d["t"] - WIN[0])
        if w.any():
            oc.append(bool(((drawn_t >= d["t"] - WIN[1]) & (drawn_t <= d["t"] - WIN[0])).any()))
    res["others_dets_observed"] = len(oc)
    res["others_det_share_with_circle"] = round(float(np.mean(oc)), 3) if oc else None
    res["own_view_drawn_frac"] = round(float((st[own] == 1).mean()), 3)

    # -- The HUD as a second witness (2 Hz, stored): own-view brackets between two
    # counter reads of one gun. Firing: the magazine falls, the reserve holds. Reload:
    # the reserve falls and the magazine rises. Quiet: nothing changes. Each counts as
    # drawn when any frame in [t_prev, t_new + WIN[1]] is drawn; quiet brackets are
    # split by the self track's speed (still < 2 stored px/s), since running draws it.
    hs = sm.hud_samples()
    track = sm.self_track()
    lo_t = float(t[sel_round][0]) if sel_round.any() else 0.0
    hi_t = float(t[sel_round][-1]) if sel_round.any() else 0.0
    hud = defaultdict(list)
    for p_, q_ in zip(hs, hs[1:]):
        if not (lo_t <= q_["t"] <= hi_t) or p_["state"] != "gun" or q_["state"] != "gun" or p_["seg"] != q_["seg"]:
            continue
        if None in (p_["mag"], q_["mag"], p_["res"], q_["res"]):
            continue
        if sm.pov_at(spans, p_["t"]) != "own" or sm.pov_at(spans, q_["t"]) != "own":
            continue
        if p_["res"] == q_["res"] and q_["mag"] < p_["mag"]:
            kind = "firing"
        elif q_["res"] < p_["res"] and q_["mag"] > p_["mag"]:
            kind = "reload"
        elif p_["res"] == q_["res"] and q_["mag"] == p_["mag"]:
            kind = "quiet"
        else:
            continue
        v = sm.speed_at(track, (p_["t"] + q_["t"]) / 2)
        kind += "_still" if v is not None and v < 2.0 else ("_moving" if v is not None else "_unknown")
        w = (t >= p_["t"]) & (t <= q_["t"] + WIN[1]) & (st >= 0)
        if w.sum() < 3:
            continue
        pre = (t >= p_["t"] - 0.5) & (t < p_["t"]) & (st >= 0)
        hud[kind].append({"t_prev": p_["t"], "t_new": q_["t"], "drawn": bool((st[w] == 1).any()),
                          "absent_before": bool(pre.any() and (st[pre] == 0).all())})
    res["hud"] = {k: {"n": len(v), "drawn": sum(x["drawn"] for x in v),
                      "share": round(sum(x["drawn"] for x in v) / len(v), 3),
                      "n_absent_before": sum(x["absent_before"] for x in v),
                      "drawn_after_absent": sum(x["drawn"] for x in v if x["absent_before"])}
                  for k, v in sorted(hud.items())}
    res["hud_rows"] = {k: v for k, v in hud.items()}

    # -- Q2 time course.
    own_runs = [r for r in rs if r["pov"] == "own" and r["clean_on"] and r["clean_off"]]
    dur = np.array([r["t_off"] - r["t_on"] for r in own_runs])
    res["runs_clean"] = len(own_runs)
    res["run_s_p10_median_p90"] = [round(float(np.percentile(dur, q)), 3) for q in (10, 50, 90)] if len(dur) else None
    # A single sound's circle: the modal 0.1 s bin of clean run lengths (first to last
    # drawn frame), and the median inside it.
    if len(dur):
        h, e = np.histogram(dur, bins=np.arange(0, 3.01, 0.1))
        k = int(np.argmax(h))
        inb = dur[(dur >= e[k]) & (dur < e[k + 1])]
        res["run_mode_bin"] = [round(float(e[k]), 1), round(float(e[k + 1]), 1)]
        res["run_mode_n"] = int(h[k])
        res["run_mode_median_s"] = round(float(np.median(inb)), 3)
        res["run_hist_0.1s"] = h.tolist()
    # isolated own sounds that start a clean run: onset lag and how long the run lasts
    iso_rows = []
    for x in rows:
        d = x["det"]
        if d is None or not x["clean_off"]:
            continue
        others = np.abs(ot - d["t"])
        if ((others > 1e-6) & (others < ISOLATED_S)).any():
            continue
        iso_rows.append({"t": d["t"], "cls": d["cls"], "lag": x["lag"], "t_on": x["t_on"], "t_off": x["t_off"],
                         "drawn_s": round(x["t_off"] - x["t_on"], 3), "after_sound_s": round(x["t_off"] - d["t"], 3)})
    res["isolated"] = iso_rows
    if iso_rows:
        a = np.array([r["after_sound_s"] for r in iso_rows])
        res["isolated_n"] = len(iso_rows)
        res["isolated_after_sound_median"] = round(float(np.median(a)), 3)
        res["isolated_after_sound_p10"] = round(float(np.percentile(a, 10)), 3)
        res["isolated_after_sound_p90"] = round(float(np.percentile(a, 90)), 3)
        res["isolated_drawn_median"] = round(float(np.median([r["drawn_s"] for r in iso_rows])), 3)
    # restart: in runs holding several own sounds, the run ends a linger after the LAST one
    lasts = []
    for r in own_runs:
        inside = ot[(ot >= r["t_on"] + WIN[0]) & (ot <= r["t_off"])]
        if len(inside) >= 2:
            lasts.append({"t_on": r["t_on"], "t_off": r["t_off"], "n_sounds": int(len(inside)),
                          "after_last": round(r["t_off"] - float(inside.max()), 3),
                          "after_first": round(r["t_off"] - float(inside.min()), 3)})
    res["multi_sound_runs"] = len(lasts)
    if lasts:
        res["multi_after_last_median"] = round(float(np.median([x["after_last"] for x in lasts])), 3)
        res["multi_after_first_median"] = round(float(np.median([x["after_first"] for x in lasts])), 3)
    # rise and fade profiles, aligned at the first and last drawn frames, relative to the run's median
    rise, fade = [], []
    for r in own_runs:
        a, b = r["i_on"], r["i_off"]
        plat = float(np.nanmedian(score[a:b + 1]))
        if b - a < 4 or plat < T_HI:
            continue
        rise.append([score[a + k] / plat if 0 <= a + k < len(score) else np.nan for k in range(-2, 4)])
        fade.append([score[b + k] / plat if 0 <= b + k < len(score) else np.nan for k in range(-3, 3)])
    with np.errstate(all="ignore"):
        res["rise_profile_frames_-2..+3"] = np.round(np.nanmedian(np.array(rise), 0), 2).tolist() if rise else None
        res["fade_profile_frames_-3..+2"] = np.round(np.nanmedian(np.array(fade), 0), 2).tolist() if fade else None
    res["profile_runs"] = len(rise)

    # -- Q1 radius and Q4 loudness: exact fits two frames after each clean own onset.
    S = Session(ISO)
    pick = {}
    for x, r in zip(rows, ons):
        i = r["i_on"] + 2
        if i <= r["i_off"] and st[i] == 1:
            pick[float(z["t_ms"][i])] = x
    fits = fit_frames(S, sorted(pick), R0)
    for f in fits:
        x = pick[f["t_ms"]]
        f["t_on"] = x["t_on"]
        f["det"] = ({k: x["det"][k] for k in ("t", "cls", "ild_db", "level_db", "score")} if x["det"] else None)
        a = int(np.searchsorted(t, x["t_on"]))
        f["plateau"] = float(np.nanmedian(score[a:a + 5]))
    good = [f for f in fits if f["inliers"] >= 0.5 and f["rms"] < 1.5]
    res["radius_fits"] = len(fits)
    res["radius_fits_good"] = len(good)
    if good:
        R = np.array([f["r"] for f in good])
        SR = np.array([f["self_r"] for f in good if f["self_rms"] < RIM_RMS_MAX])
        res["r_baked_median"] = round(float(np.median(R)), 2)
        res["r_baked_sd"] = round(float(R.std()), 3)
        res["r_baked_p5_p95"] = [round(float(np.percentile(R, q)), 2) for q in (5, 95)]
        res["fit_rms_median"] = round(float(np.median([f["rms"] for f in good])), 3)
        res["centre_offset_from_self_median"] = round(float(np.median([f["offset"] for f in good])), 2)
        res["self_r_baked"] = round(float(np.median(SR)), 2) if len(SR) else None
        res["self_r_n"] = int(len(SR))
        res["r_over_self_r"] = round(float(np.median(R) / np.median(SR)), 2) if len(SR) else None
        byc = defaultdict(list)
        for f in good:
            byc[f["det"]["cls"] if f["det"] else "no_own_sound"].append(f["r"])
        res["r_by_class"] = {c: {"n": len(v), "median": round(float(np.median(v)), 2),
                                 "sd": round(float(np.std(v)), 3)} for c, v in sorted(byc.items())}
        lv = [f for f in good if f["det"]]
        res["loudness_n"] = len(lv)
        if len(lv) >= 5:
            L = np.array([f["det"]["level_db"] for f in lv])
            res["loudness_level_db_range"] = [float(L.min()), float(L.max())]
            res["rho_level_radius"] = round(spearman(L, np.array([f["r"] for f in lv])), 3)
            res["rho_level_ring"] = round(spearman(L, np.array([f["ring"] for f in lv])), 3)
            res["rho_level_plateau"] = round(spearman(L, np.array([f["plateau"] for f in lv])), 3)
    # Loudness at one place: inside runs holding two or more own sounds the background
    # under the rim barely changes, so the ring score one frame after each sound is
    # compared with its level after subtracting each run's means.
    dl, dr = [], []
    for r in rs:
        if r["pov"] != "own" or not (r["clean_on"] and r["clean_off"]):
            continue
        inside = [d for d in own_snd if r["t_on"] <= d["t"] <= r["t_off"]]
        pts = []
        for d in inside:
            i = int(np.searchsorted(t, d["t"])) + 1
            if i < len(t) and np.isfinite(score[i]) and st[i] == 1:
                pts.append((d["level_db"], float(score[i])))
        if len(pts) >= 2:
            a_ = np.array(pts)
            dl += list(a_[:, 0] - a_[:, 0].mean())
            dr += list(a_[:, 1] - a_[:, 1].mean())
    res["within_run_loudness_n"] = len(dl)
    if len(dl) >= 5:
        res["rho_level_ring_within_run"] = round(spearman(np.array(dl), np.array(dr)), 3)
    # The self icon's rim on a fixed sample: every 40th own-view frame with a self position.
    rim_t = [float(x) for x in z["t_ms"][np.nonzero(own & (st >= 0))[0][::40]]]
    rims = self_rims(S, rim_t)
    good_r = [x for x in rims if x["rms"] < RIM_RMS_MAX]
    res["self_rim_sampled"] = len(rims)
    res["self_rim_good"] = len(good_r)
    if good_r:
        res["self_r_baked"] = round(float(np.median([x["r"] for x in good_r])), 2)
        res["self_r_n"] = len(good_r)
        if good:
            res["r_over_self_r"] = round(float(np.median(R)) / res["self_r_baked"], 2)
    res["fits"] = fits

    # -- P6 spectating.
    def rate(k):
        m = (pov == k) & (st >= 0) & sel_round            # frames with a self position
        secs = int(m.sum()) / info["hz"]
        n = sum(1 for r in rs if r["pov"] == k and r["clean_on"])
        drawn = float((st[m] == 1).mean()) if m.any() else None
        return {"seconds": round(secs, 1), "onsets": n, "per_s": round(n / secs, 4) if secs else None,
                "drawn_frac": round(drawn, 3) if drawn is not None else None}
    res["view"] = {k: rate(k) for k in ("own", "other", "none")}

    res["onset_rows"] = [{**{k: v for k, v in x.items() if k != "det"},
                          "det": ({k: x["det"][k] for k in ("t", "cls", "ild_db", "level_db", "score")}
                                  if x["det"] else None)} for x in rows]
    res["own_sound_det_rows"] = [{k: x[k] for k in ("t", "cls", "ild_db", "level_db", "score", "round", "circle")}
                                 for x in det_rows]
    res["multi_rows"] = lasts
    tag = "all" if only is None else f"r{only:02d}"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"score-{tag}.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    # disagreements, stored apart (agreement is consistency, not accuracy)
    dis = ([{"kind": "onset_without_own_sound", **{k: v for k, v in x.items() if k != "det"}}
            for x in rows if x["lag"] is None]
           + [{"kind": "own_sound_without_circle", **{k: x[k] for k in ("t", "cls", "ild_db", "level_db", "score", "round")}}
              for x in det_rows if x["circle"] is False])
    (OUT / f"disagreements-{tag}.jsonl").write_text("".join(json.dumps(r, default=float) + "\n" for r in dis),
                                                   encoding="utf-8")
    if fig_round is not None:
        timeline(fig_round, t, score, st, pov, rs, dets, spans, R0)
    return res


def fit_frames(S: Session, t_list, R0: float) -> list[dict]:
    """Exact fits at the given frames: the circle (ray edges round the best
    grid centre, `clove_circle.fit_circle`) and the self icon's rim (the same
    fit on saturation), both in baked px."""
    out = []
    for t, crop in S.crops(t_list):
        me, _ = S.self_at(t)
        if me is None:
            continue
        d = S.diff(crop)
        cur = ring_curve(d, me, np.array([R0]))
        k = int(np.nanargmax(np.nan_to_num(cur[:, 0], nan=-1e9)))
        c0 = (me[0] + OFFS[k][0], me[1] + OFFS[k][1])
        f = cc.fit_circle(d, c0, R0, win=6.0)
        ring = cc.ringscore(d, (f["cx"], f["cy"]), f["r"])
        sat = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32), (0, 0), 0.6)
        s = cc.fit_circle(sat, me, SELF_R_SEED * S.W, win=3.5)
        out.append({"t_ms": float(t), "cx": f["cx"], "cy": f["cy"], "r": f["r"], "rms": f["rms"],
                    "inliers": f["inliers"], "ring": ring, "self_x": me[0], "self_y": me[1],
                    "self_cx": s["cx"], "self_cy": s["cy"], "self_r": s["r"], "self_rms": s["rms"],
                    "offset": float(np.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"]))})
    return out


def self_rims(S: Session, t_list) -> list[dict]:
    """The self icon's rim (saturation, `clove_circle.fit_circle`) at the given frames."""
    out = []
    for t, crop in S.crops(t_list):
        me, _ = S.self_at(t)
        if me is None:
            continue
        sat = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32), (0, 0), 0.6)
        f = cc.fit_circle(sat, me, SELF_R_SEED * S.W, win=3.5)
        out.append({"t_ms": float(t), "r": f["r"], "rms": f["rms"], "inliers": f["inliers"]})
    return out


def radius_span(sid: str, tag: str) -> dict:
    """The radius on a scanned span of another session: R0 from its curves,
    exact fits on every drawn frame, the self rim, in that session's baked px."""
    z, info = load_curves(sid, tag)
    C = z["curve"].astype(float)
    ok = np.isfinite(C).all(1)
    R0, k0 = circle_radius(C, z["radii"], ok)
    score = np.nanmax(C[:, max(0, k0 - 2):k0 + 3], 1)
    st = states(score)
    S = Session(sid)
    fits = fit_frames(S, [float(x) for x in z["t_ms"][st == 1]], R0)
    good = [f for f in fits if f["inliers"] >= 0.5 and f["rms"] < 1.5]
    R = np.array([f["r"] for f in good])
    SR = np.array([f["self_r"] for f in good if f["self_rms"] < RIM_RMS_MAX])
    res = {"session": sid, "key": info["key"], "span": tag, "widget_w": S.W, "R0": R0, "frames": int(len(score)),
           "drawn": int((st == 1).sum()), "fits_good": len(good),
           "r_baked": round(float(np.median(R)), 2) if len(R) else None,
           "r_sd": round(float(R.std()), 3) if len(R) else None,
           "r_331": round(float(np.median(R)) * 331.0 / S.W, 2) if len(R) else None,
           "self_r_baked": round(float(np.median(SR)), 2) if len(SR) else None, "self_r_n": int(len(SR)),
           "r_over_self_r": round(float(np.median(R) / np.median(SR)), 2) if len(SR) and len(R) else None,
           "centre_offset_from_self_median": round(float(np.median([f["offset"] for f in good])), 2) if good else None,
           "fits": fits}
    (OUT / f"{sid}-radius-{tag}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


#: Contact-sheet rule, fixed before rendering: per bank class among the isolated own
#: sounds that start a clean run, the one whose run is shortest (a single sound's
#: circle), at most 5 classes; plus the first clean own-view onset with no detection
#: of any class in the window. Each row: two frames before the onset to two after the offset,
#: at most 10 frames.
SHEET_RULE = "shortest isolated run per class (<=5) + first onset with no detection"


def sheet(res: dict, R0: float) -> Path:
    S = Session(ISO)
    z, _ = load_curves(ISO)
    t = z["t_ms"] / 1000.0
    ex = {}
    for r in sorted(res["isolated"], key=lambda r: r["drawn_s"]):
        ex.setdefault(r["cls"], r)
    picks = [(f"{c}: sound {r['t']:.3f} s, circle {r['t_on']:.3f}-{r['t_off']:.3f} s", r["t_on"], r["t_off"], r["t"])
             for c, r in list(ex.items())[:5]]
    nod = next((x for x in res["onset_rows"] if not x["any_det"] and x["clean_off"]), None)
    if nod:
        picks.append((f"no detection of any class: circle {nod['t_on']:.3f}-{nod['t_off']:.3f} s",
                      nod["t_on"], nod["t_off"], None))
    Z, HALF = 3, int(R0 * 1.3)
    rows = []
    for label, a, b, ts in picks:
        i0, i1 = int(np.searchsorted(t, a)), int(np.searchsorted(t, b))
        idx = list(range(max(0, i0 - 2), min(len(t), i1 + 3)))
        if len(idx) > 10:
            idx = idx[:6] + idx[-4:]
        tl = [float(z["t_ms"][i]) for i in idx]
        fits = {f["t_ms"]: f for f in fit_frames(S, tl, R0)}
        tiles = []
        for tm, crop in S.crops(tl):
            me, _ = S.self_at(tm)
            me = me or (crop.shape[1] / 2, crop.shape[0] / 2)
            f = fits.get(tm)
            drawn = f is not None and f["ring"] >= T_HI
            pad = cv2.copyMakeBorder(crop, HALF, HALF, HALF, HALF, cv2.BORDER_CONSTANT)
            x0, y0 = int(round(me[0])), int(round(me[1]))
            w = cv2.resize(pad[y0:y0 + 2 * HALF, x0:x0 + 2 * HALF], None, fx=Z, fy=Z, interpolation=cv2.INTER_CUBIC)
            if f is not None:
                cx, cy = (f["cx"] - x0 + HALF) * Z, (f["cy"] - y0 + HALF) * Z
                col = (0, 0, 255) if drawn else (160, 160, 160)
                for ang in np.deg2rad(np.arange(0, 360, 22.5)):
                    p0 = (int(cx + (f["r"] + 3) * Z * np.cos(ang)), int(cy + (f["r"] + 3) * Z * np.sin(ang)))
                    p1 = (int(cx + (f["r"] + 7) * Z * np.cos(ang)), int(cy + (f["r"] + 7) * Z * np.sin(ang)))
                    cv2.line(w, p0, p1, col, 2, cv2.LINE_AA)
            txt = f"{tm / 1000:.3f}" + (f" ring {f['ring']:.1f} r {f['r']:.1f}" if f else " no self")
            if ts is not None and abs(tm / 1000 - ts) < 1 / 30:
                txt += " <- SOUND"
            cv2.rectangle(w, (0, 0), (w.shape[1], 22), (0, 0, 0), -1)
            cv2.putText(w, txt, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(w)
        while len(tiles) < 10:
            tiles.append(np.zeros_like(tiles[0]))
        row = np.hstack(tiles)
        head = np.zeros((28, row.shape[1], 3), np.uint8)
        cv2.putText(head, label, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 1, cv2.LINE_AA)
        rows.append(np.vstack([head, row]))
    top = np.zeros((40, rows[0].shape[1], 3), np.uint8)
    cv2.putText(top, (f"Self audio circle, {ISO} (Split, Iso capture), baked frame round the self icon, x{Z}. "
                      f"Red ticks: fitted circle just outside its rim (grey: fit where not drawn). "
                      f"r = {res.get('r_baked_median')} baked px; drawn when ring >= {T_HI:g}"),
                (8, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
    p = OUT / "contact_sheet.png"
    cv2.imwrite(str(p), np.vstack([top] + rows))
    print(f"sheet -> {p}")
    return p


def timeline(r_no, t, score, st, pov, rs, dets, spans, R0) -> Path:
    """One round: own-sound detections by class against the circle's score and onsets."""
    import sound_match as sm
    a, b = next((c[1], c[2]) for c in sm.chunks() if c[0] == r_no)
    sel = (t >= a) & (t < b)
    fin = np.nonzero(sel & np.isfinite(score))[0]
    if len(fin):
        a, b = max(a, t[fin[0]] - 1), min(b, t[fin[-1]] + 1)
    classes = sorted({d["cls"] for d in dets if a <= d["t"] < b})
    W, L, R = 1900, 150, 20
    top, sc_h, gap, det_h, bot = 70, 180, 14, 20 * len(classes), 40
    H = top + sc_h + gap + det_h + bot
    im = np.full((H, W, 3), 255, np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    pw = W - L - R

    def X(x):
        return int(L + (x - a) / (b - a) * pw)
    for x0, x1, k in spans:
        if x1 > a and x0 < b:
            cv2.rectangle(im, (X(max(a, x0)), top), (X(min(b, x1)), H - bot),
                          (246, 233, 219) if k == "own" else (219, 227, 246), -1)
    ys = top + sc_h
    for lim in (T_LO, T_HI):
        yy = int(ys - lim / 25 * sc_h)
        cv2.line(im, (L, yy), (L + pw, yy), (190, 190, 190), 1)
        cv2.putText(im, f"{lim:g}", (L - 26, yy + 4), font, 0.38, (90, 90, 90), 1, cv2.LINE_AA)
    prev = None
    for i in np.nonzero(sel)[0]:
        if not np.isfinite(score[i]):
            prev = None
            continue
        p = (X(t[i]), int(ys - np.clip(score[i], 0, 25) / 25 * sc_h))
        if prev:
            cv2.line(im, prev, p, (60, 60, 60), 1, cv2.LINE_AA)
        prev = p
    for i in np.nonzero(sel & (st == 1))[0]:
        cv2.line(im, (X(t[i]), ys + 2), (X(t[i]), ys + 8), (40, 39, 214), 1)
    for r in rs:
        if a <= r["t_on"] < b and r["clean_on"]:
            cv2.line(im, (X(r["t_on"]), top), (X(r["t_on"]), H - bot), (40, 39, 214), 1)
    cv2.putText(im, "circle ring score", (8, top + 60), font, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, "red tick: drawn", (8, top + 80), font, 0.4, (40, 39, 214), 1, cv2.LINE_AA)
    yd = ys + gap
    for i, c in enumerate(classes):
        yy = yd + 10 + 20 * i
        cv2.line(im, (L, yy), (L + pw, yy), (225, 225, 225), 1)
        cv2.putText(im, c, (8, yy + 4), font, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    for d in dets:
        if a <= d["t"] < b:
            p = (X(d["t"]), yd + 10 + 20 * classes.index(d["cls"]))
            own_s = abs(d["ild_db"]) < OWN_ILD_DB
            cv2.circle(im, p, 5 if own_s else 3, (44, 160, 44) if own_s else (170, 170, 170), -1 if own_s else 1,
                       cv2.LINE_AA)
    for k in range(int(np.ceil(a / 5) * 5), int(b) + 1, 5):
        cv2.line(im, (X(k), H - bot), (X(k), H - bot + 5), (0, 0, 0), 1)
        cv2.putText(im, f"{k}", (X(k) - 12, H - bot + 20), font, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, f"{ISO} round {r_no}, capture s {a:.0f}-{b:.0f}: self audio circle (r = {R0:g} baked px) "
                f"vs bank detections", (L, 22), font, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, f"blue band: own view   pink: spectating   red vertical: clean circle onset   green dot: "
                f"own sound (|ILD| < {OWN_ILD_DB:g} dB)   grey ring: other detection",
                (L, 46), font, 0.45, (60, 60, 60), 1, cv2.LINE_AA)
    p = OUT / f"round-{r_no:02d}-timeline.png"
    cv2.imwrite(str(p), im)
    print(f"figure -> {p}")
    return p


def record_iso(res: dict) -> None:
    from reticle import metrics
    v = {k: res[k] for k in (
        "R0_baked", "r_baked_median", "r_baked_sd", "fit_rms_median", "centre_offset_from_self_median",
        "radius_fits_good", "self_r_baked", "self_r_n", "r_over_self_r", "onsets_own", "onsets_with_own_sound",
        "onset_share_with_own_sound", "onsets_without_any_det", "onset_share_without_any_det", "lag_median",
        "lag_p10", "lag_p90", "own_sound_dets_observed", "own_sound_dets_with_circle",
        "own_sound_det_share_with_circle", "others_dets_observed", "others_det_share_with_circle",
        "own_view_drawn_frac", "runs_clean", "run_mode_n", "run_mode_median_s", "multi_sound_runs",
        "multi_after_last_median", "multi_after_first_median", "profile_runs", "loudness_n",
        "rho_level_radius", "rho_level_ring", "rho_level_plateau", "within_run_loudness_n",
        "rho_level_ring_within_run") if res.get(k) is not None}
    v["r_baked_p5"], v["r_baked_p95"] = res["r_baked_p5_p95"]
    v["run_p10"], v["run_median"], v["run_p90"] = res["run_s_p10_median_p90"]
    rise, fade = res["rise_profile_frames_-2..+3"], res["fade_profile_frames_-3..+2"]
    v["rise_frame_before"], v["rise_frame0"], v["rise_frame1"] = rise[1], rise[2], rise[3]
    v["fade_frame_before_last"], v["fade_last"], v["fade_after"] = fade[2], fade[3], fade[4]
    for c, w in res["own_sound_by_class"].items():
        v[f"own_{c}_n"], v[f"own_{c}_with_circle"] = w["n"], w["with_circle"]
    for c, w in res["r_by_class"].items():
        v[f"r_{c}_n"], v[f"r_{c}_median"] = w["n"], w["median"]
    for k, w in res["hud"].items():
        for f in ("n", "drawn", "share", "n_absent_before", "drawn_after_absent"):
            v[f"hud_{k}_{f}"] = w[f]
    for k, w in res["view"].items():
        for f in ("seconds", "onsets", "per_s", "drawn_frac"):
            if w[f] is not None:
                v[f"view_{k}_{f}"] = w[f]
    metrics.record("audio_circle", part="score", session=ISO, values=v,
                   deps={"version": VERSION, "t_hi": T_HI, "t_lo": T_LO, "clean": CLEAN, "own_ild_db": OWN_ILD_DB,
                         "window": list(WIN), "self_win_ms": SELF_WIN_MS, "rim_rms_max": RIM_RMS_MAX,
                         "detections": "analysis/sound-match/detections (sound-match-0.1.0)"},
                   context={"cache": "roi-cache-0.1.0 minimap 15 Hz", "minimap": "minimap-0.7.0",
                            "tray_kit": "tray-kit-0.1.0", "hud": "hud-0.16.0 2 Hz",
                            "geometry": "split__valorant-16x9"},
                   note="self audio circle on the Iso capture; not wired")
    print(f"recorded {len(v)} values under audio_circle/score@{ISO}")


def record_radius(res: dict) -> None:
    from reticle import metrics
    v = {k: res[k] for k in ("R0", "frames", "drawn", "fits_good", "r_baked", "r_sd", "r_331", "self_r_baked",
                             "self_r_n", "r_over_self_r", "centre_offset_from_self_median", "widget_w")}
    metrics.record("audio_circle", part=f"radius-{res['span']}", session=res["session"], values=v,
                   deps={"version": VERSION, "t_hi": T_HI, "t_lo": T_LO, "rim_rms_max": RIM_RMS_MAX},
                   context={"geometry": res["key"], "cache": "roi-cache-0.1.0 minimap"},
                   note="self audio circle radius on a capture span; not wired")
    print(f"recorded under audio_circle/radius-{res['span']}@{res['session']}")


def main(argv=None) -> int:
    idle()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("scan")
    a.add_argument("session")
    a.add_argument("--t0", type=float)
    a.add_argument("--t1", type=float)
    b = sub.add_parser("score")
    b.add_argument("--round", type=int)
    b.add_argument("--figure", type=int)
    b.add_argument("--record", action="store_true")
    b.add_argument("--sheet", action="store_true")
    c = sub.add_parser("radius")
    c.add_argument("session")
    c.add_argument("tag")
    c.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "scan":
        scan(args.session, args.t0, args.t1)
    elif args.cmd == "radius":
        res = radius_span(args.session, args.tag)
        print(json.dumps({k: v for k, v in res.items() if k != "fits"}, indent=1))
        if args.record:
            record_radius(res)
    elif args.cmd == "score":
        res = score_iso(args.round, args.record, args.figure)
        if args.sheet:
            sheet(res, res["R0_baked"])
        if args.record and args.round is None:
            record_iso(res)
        print(json.dumps({k: v for k, v in res.items()
                          if k not in ("onset_rows", "own_sound_det_rows", "isolated", "multi_rows")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
