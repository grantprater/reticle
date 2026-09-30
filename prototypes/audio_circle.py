r"""Measure the minimap's self audio circle and score it as a witness of the player's own sounds.

    .\.venv\Scripts\python.exe prototypes\audio_circle.py scan SESSION [--t0 S --t1 S]
    .\.venv\Scripts\python.exe prototypes\audio_circle.py score [--round N] [--figure N] [--sheet] [--record]
    .\.venv\Scripts\python.exe prototypes\audio_circle.py radius SESSION TAG [--record]
    .\.venv\Scripts\python.exe prototypes\audio_circle.py score --per-frame [--record]
    .\.venv\Scripts\python.exe prototypes\audio_circle.py frames SESSION T0 T1 [--fit]

Why this exists
---------------
The player, 2026-09-29, named a pale circle round the self icon, drawn for
the player's own icon only [domain:minimap/self-audio-circle], and first
believed it drawn on every own sound at one radius. On 2026-09-30 the player
named the larger of its two sizes the spike radius and explained both: the
circle marks own footsteps and reloads, not shots or movement; a reload
draws the smaller circle while no step sounds, and a step's circle
supersedes it; a player can move at full speed without a step sounding
[domain:abilities/silent-stepping]. Whether the minimap draws the spike's
explosion is a separate belief
[domain:minimap/spike-explosion-drawn-belief]. This file measures the
circle's radius and time course and scores it against `sound_match.py`'s bank
detections, the HUD and the self track's speed on the Iso capture
(4f207c0c4e39, `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`). Predictions
and outcomes are in the store's `notes/predictions.jsonl` under
`audio-circle-20260929` and `audio-circle-running-20260930`.

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

Results (2026-09-30, `score --per-frame`)
-----------------------------------------
Every own-view drawn frame is fitted, not one frame per onset; presence is
gated on a 66-78 px band, since the any-radius argmax also finds map edges
and the widget's fixed border circle.

Two sizes. The footstep circle measures [metric:audio_circle/per-frame@4f207c0c4e39#large_r_median=74.86] px, sd
[metric:audio_circle/per-frame@4f207c0c4e39#large_r_sd=0.16], over [metric:audio_circle/per-frame@4f207c0c4e39#large_fits=1793] frames. The reload circle
measures [metric:audio_circle/per-frame@4f207c0c4e39#small_r_median=69.14] px, sd [metric:audio_circle/per-frame@4f207c0c4e39#small_r_sd=0.43], over
[metric:audio_circle/per-frame@4f207c0c4e39#small_fits=41] frames in [metric:audio_circle/per-frame@4f207c0c4e39#small_runs=9] runs; polar unwraps
confirm a ring at 69-70 px in four of them outside 903-905 s. The earlier sd
0.169 sampled one fit per clean onset seeded at 75 px, and those onsets
missed the small runs. Within a run the radius holds (median change
[metric:audio_circle/per-frame@4f207c0c4e39#run_abs_last_minus_second_median=0.09] px); at 903.8-905.3 s, where the
player was reloading or changing guns, the sizes alternate between frames as
steps supersede the reload. Every small fit lies within 2.5 s of a HUD
magazine refill ([metric:audio_circle/per-frame@4f207c0c4e39#small_fits_within_2_5s_of_refill=41]): refills with
it [metric:audio_circle/per-frame@4f207c0c4e39#refills_with_small=6] of [metric:audio_circle/per-frame@4f207c0c4e39#refills=17], refill-free control
windows [metric:audio_circle/per-frame@4f207c0c4e39#refill_control_with_small=0] of
[metric:audio_circle/per-frame@4f207c0c4e39#refill_control_windows=218]; that association was found after looking,
before the player's answer. Split by the bank's own footstep detections in
the same window, refills show the reload circle
[metric:audio_circle/per-frame@4f207c0c4e39#refills_no_footstep_small=4] of [metric:audio_circle/per-frame@4f207c0c4e39#refills_no_footstep=8] with no
detected step and [metric:audio_circle/per-frame@4f207c0c4e39#refills_footstep_small=2] of
[metric:audio_circle/per-frame@4f207c0c4e39#refills_footstep=9] with one: the direction the player's rule
predicts, on few refills and a bank that misnames many match sounds.

Movement. Own-view frames are drawn [metric:audio_circle/per-frame@4f207c0c4e39#frames_still_share=0.114] of
[metric:audio_circle/per-frame@4f207c0c4e39#frames_still_n=889] still (under 2 stored px/s),
[metric:audio_circle/per-frame@4f207c0c4e39#frames_slow_share=0.243] of [metric:audio_circle/per-frame@4f207c0c4e39#frames_slow_n=2188] at 2-8 px/s and
[metric:audio_circle/per-frame@4f207c0c4e39#frames_moving_share=0.635] of [metric:audio_circle/per-frame@4f207c0c4e39#frames_moving_n=1517] at 8-40
px/s. Own footsteps fall with it [metric:audio_circle/per-frame@4f207c0c4e39#bank_footstep_moving_drawn=61] of
[metric:audio_circle/per-frame@4f207c0c4e39#bank_footstep_moving_n=66] moving and
[metric:audio_circle/per-frame@4f207c0c4e39#bank_footstep_still_drawn=4] of [metric:audio_circle/per-frame@4f207c0c4e39#bank_footstep_still_n=19] still.
Speed predicts the circle only because moving usually steps. The
disagreements with "only while running" are in
`analysis/audio-circle-running-20260930/disagreements.jsonl`, and the
player's answers explain them: [metric:audio_circle/per-frame@4f207c0c4e39#dis_moving_window_without_circle=29]
moving one-second windows with no circle fit silent stepping, and at
1934.9-1935.4 s the player stepped throughout the firing while the circle
lags the sound. None is checked frame by frame.

Results (2026-09-29)
--------------------
Radius (superseded above: the circle has two sizes). On the Iso capture's Split widget (331 baked px) the fitted radius is
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
on the minimap in a spectated view, so it neither shows nor refutes a drawn
explosion [domain:minimap/spike-explosion-drawn-belief].
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


# ---------------------------------------------------------------- per frame (2026-09-30)

PF_VERSION = "audio-circle-perframe-0.1.0"
PF_OUT = STORE.root / "analysis" / "audio-circle-running-20260930"
#: Sheet tiles: baked px either side of the self icon, and the upscale (the Iso
#: widget is 1.15x the baked one, so x2 never shows fewer pixels than the capture).
SHEET_HALF, SHEET_Z = 160, 2
#: The radii the presence tests gate on, baked px: both fitted sizes (about 69 and
#: 75 on the Iso match, `score --per-frame`) with the ring kernel's slack. Set from
#: this run's fits; a third size outside it would read as absent.
SIZE_BAND = (66.0, 78.0)
#: Between the two fitted sizes, baked px.
SIZE_CUT = 72.0


def frames_sheet(sid: str, t0: float, t1: float, fit: bool = False, cols: int = 2) -> Path:
    """Every cached frame between t0 and t1 s round the self icon: the raw
    baked-frame crop and its static-subtracted grey side by side, upscaled
    SHEET_Z, each captioned with its time, view and stored self speed. With
    `fit`, ticks mark the per-frame fit just outside the circle on the
    subtracted tile only; the raw tile is never drawn on."""
    import sound_match as sm
    S = Session(sid)
    held = [t for t in S.cache.holds() if t0 * 1000 <= t <= t1 * 1000]
    spans = sm.pov_spans() if sid == ISO else []
    track = sm.self_track() if sid == ISO else None
    H, Z = SHEET_HALF, SHEET_Z
    font = cv2.FONT_HERSHEY_SIMPLEX
    pairs, last = [], None
    for tm, crop in S.crops(held):
        me, _ = S.self_at(tm)
        where = "self stored" if me else ("self held" if last else "no self: widget centre")
        me = me or last or (crop.shape[1] / 2, crop.shape[0] / 2)
        last = me
        x0, y0 = int(round(me[0])), int(round(me[1]))
        d = S.diff(crop)
        raw = cv2.copyMakeBorder(crop, H, H, H, H, cv2.BORDER_CONSTANT)[y0:y0 + 2 * H, x0:x0 + 2 * H]
        g = np.clip(128 + 2 * d, 0, 255).astype(np.uint8)
        g = cv2.copyMakeBorder(g, H, H, H, H, cv2.BORDER_CONSTANT)[y0:y0 + 2 * H, x0:x0 + 2 * H]
        raw = cv2.resize(raw, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
        g = cv2.cvtColor(cv2.resize(g, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        note = ""
        if fit:
            f = frame_fit(S, crop, me)
            if f is not None:
                cx, cy = (f["cx"] - x0 + H) * Z, (f["cy"] - y0 + H) * Z
                col = (0, 0, 255) if f["best"] >= T_HI else (160, 160, 160)
                for ang in np.deg2rad(np.arange(0, 360, 30.0)):
                    p0 = (int(cx + (f["r"] + 4) * Z * np.cos(ang)), int(cy + (f["r"] + 4) * Z * np.sin(ang)))
                    p1 = (int(cx + (f["r"] + 8) * Z * np.cos(ang)), int(cy + (f["r"] + 8) * Z * np.sin(ang)))
                    cv2.line(g, p0, p1, col, 2, cv2.LINE_AA)
                note = f"  ring {f['best']:.1f} argmax r {f['r_arg']:.0f} fit r {f['r']:.1f}"
        pov = sm.pov_at(spans, tm / 1000) if spans else None
        v = sm.speed_at(track, tm / 1000) if track is not None else None
        cap = (f"{tm / 1000:.3f} s  {pov or 'no'} view  speed "
               + ("?" if v is None else f"{v:.1f}") + f"  {where}" + note)
        pair = np.hstack([raw, np.full((raw.shape[0], 6, 3), 255, np.uint8), g])
        band = np.zeros((34, pair.shape[1], 3), np.uint8)
        cv2.putText(band, cap, (6, 24), font, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
        pairs.append(np.vstack([band, pair]))
    if not pairs:
        raise SystemExit(f"{sid}: no cached frame in {t0}-{t1} s")
    blank = np.zeros_like(pairs[0])
    rows = []
    for i in range(0, len(pairs), cols):
        row = pairs[i:i + cols] + [blank] * (cols - len(pairs[i:i + cols]))
        rows.append(np.hstack([np.pad(p, ((0, 8), (0, 8), (0, 0))) for p in row]))
    top = np.zeros((44, rows[0].shape[1], 3), np.uint8)
    cv2.putText(top, (f"{sid} {t0:g}-{t1:g} s, every cached frame. Left: raw baked-frame crop. Right: grey minus "
                      f"baked static (x2, 128 = 0). {2 * H} baked px square round the stored self icon, x{Z}."),
                (8, 30), font, 0.75, (255, 255, 255), 1, cv2.LINE_AA)
    PF_OUT.mkdir(parents=True, exist_ok=True)
    p = PF_OUT / f"{sid}-frames-{t0:g}-{t1:g}{'-fit' if fit else ''}.png"
    cv2.imwrite(str(p), np.vstack([top] + rows))
    print(f"sheet {len(pairs)} frames -> {p}")
    return p


def frame_fit(S: Session, crop, me, radii=None) -> dict | None:
    """One frame's circle, searched over every radius: the ring-score argmax
    over `radii` (default the scanned range) and the centre grid, then
    `clove_circle.fit_circle` seeded there."""
    radii = S.radii if radii is None else radii
    d = S.diff(crop)
    cur = ring_curve(d, me, radii)
    if not np.isfinite(cur).any():
        return None
    flat = np.nan_to_num(cur, nan=-1e9)
    k_off, k_r = np.unravel_index(int(np.argmax(flat)), flat.shape)
    c0 = (me[0] + OFFS[k_off][0], me[1] + OFFS[k_off][1])
    f = cc.fit_circle(d, c0, float(radii[k_r]), win=6.0)
    return {**f, "best": float(flat[k_off, k_r]), "r_arg": float(radii[k_r]),
            "ring": cc.ringscore(d, (f["cx"], f["cy"]), f["r"])}


#: Movement classes on `sound_match.speed_at` (stored px/s over +-0.5 s): still < 2,
#: slow 2-8, moving 8-40; 40 and over is the track's misfit bin (sound_match.SPEED_BINS).
MOVES = ("still", "slow", "moving", "misfit", "unknown")


def move_class(v: float | None) -> str:
    if v is None:
        return "unknown"
    return "still" if v < 2 else "slow" if v < 8 else "moving" if v < 40 else "misfit"


def local_peaks(h: np.ndarray, min_frac: float = 0.1, sep: int = 8) -> list[int]:
    """Bins that are the maximum within +-sep bins and hold at least min_frac of the top bin."""
    out = []
    for i in range(len(h)):
        a, b = max(0, i - sep), min(len(h), i + sep + 1)
        if h[i] > 0 and h[i] == h[a:b].max() and h[i] >= min_frac * h.max():
            if not out or i - out[-1] > sep:
                out.append(i)
    return out


def per_frame(record: bool) -> dict:
    """The circle's radius per frame, never from a median curve, and its presence
    against the self track's movement, the HUD's shots and the bank's
    footstep, jump and land detections, on the Iso match. Stored data only."""
    import sound_match as sm
    z, info = load_curves(ISO)
    t = z["t_ms"] / 1000.0
    radii = z["radii"]
    C = z["curve"].astype(float)
    spans = sm.pov_spans()
    pov = np.array([sm.pov_at(spans, x) or "none" for x in t])
    own = pov == "own"
    fin = np.isfinite(C).any(1)
    with np.errstate(all="ignore"):
        best = np.where(fin, np.nanmax(np.where(np.isfinite(C), C, -1e9), 1), np.nan)
    k_arg = np.where(fin, np.argmax(np.where(np.isfinite(C), C, -1e9), 1), -1)
    r_arg = np.where(fin, radii[np.clip(k_arg, 0, None)], np.nan)
    R0, k0 = circle_radius(C, radii, own & np.isfinite(C).all(1))
    old_score = np.nanmax(C[:, max(0, k0 - 2):k0 + 3], 1)
    st_old = states(old_score)
    st = states(best)                               # hysteresis on the best radius, not on R0
    res = {"version": PF_VERSION, "session": ISO, "R0_median_curve": R0, "T_HI": T_HI, "T_LO": T_LO,
           "radii_searched": [float(radii[0]), float(radii[-1])], "hz": info["hz"]}
    res["hist_best_own"] = np.histogram(best[own & fin], bins=np.arange(-4, 40, 1.0))[0].tolist()
    res["hist_best_other"] = np.histogram(best[(pov == "other") & fin], bins=np.arange(-4, 40, 1.0))[0].tolist()
    dr_own = own & (st == 1)
    res["own_frames"] = int((own & (st >= 0)).sum())
    res["own_drawn_frames"] = int(dr_own.sum())
    res["own_drawn_frac"] = round(float(dr_own.sum() / max(1, (own & (st >= 0)).sum())), 3)
    res["own_drawn_frac_old"] = round(float((own & (st_old == 1)).sum() / max(1, (own & (st_old >= 0)).sum())), 3)
    oth = (pov == "other") & (st >= 0)
    res["other_drawn_frac"] = round(float((st[oth] == 1).mean()), 3) if oth.any() else None
    ra = r_arg[dr_own]
    res["r_arg_own_drawn_hist"] = {int(r): int(n) for r, n in zip(*np.unique(ra, return_counts=True))}
    res["r_arg_share_outside_72_78"] = round(float(((ra < 72) | (ra > 78)).mean()), 3) if len(ra) else None
    h = np.histogram(ra, bins=np.arange(radii[0], radii[-1] + 2, 1.0))[0]
    res["r_arg_modes"] = [{"r": float(radii[0] + i), "n": int(h[i])} for i in local_peaks(h)]
    res["drawn_new_not_old"] = int((dr_own & (st_old != 1)).sum())
    res["drawn_old_not_new"] = int((own & (st_old == 1) & (st != 1)).sum())

    # exact fits on every own-view drawn frame, seeded at that frame's argmax
    S = Session(ISO)
    idx = np.nonzero(dr_own)[0]
    by_t = {float(z["t_ms"][i]): i for i in idx}
    fits = {}
    for tm, crop in S.crops(sorted(by_t)):
        me, _ = S.self_at(tm)
        if me is None:
            continue
        f = frame_fit(S, crop, me)
        if f is not None:
            fits[by_t[tm]] = f
    good = {i: f for i, f in fits.items() if f["inliers"] >= 0.5 and f["rms"] < 1.5}
    R = np.array([f["r"] for f in good.values()])
    res["fits"], res["fits_good"] = len(fits), len(good)
    if len(R):
        res["r_fit_median"] = round(float(np.median(R)), 2)
        res["r_fit_sd"] = round(float(R.std()), 2)
        res["r_fit_p5_p25_p75_p95"] = [round(float(np.percentile(R, q)), 2) for q in (5, 25, 75, 95)]
        res["r_fit_min_max"] = [round(float(R.min()), 2), round(float(R.max()), 2)]
        hf = np.histogram(R, bins=np.arange(radii[0], radii[-1] + 2, 1.0))[0]
        res["r_fit_hist_1px"] = {int(radii[0] + i): int(n) for i, n in enumerate(hf) if n}
        res["r_fit_modes"] = [{"r": float(radii[0] + i), "n": int(hf[i])} for i in local_peaks(hf)]
        res["r_fit_share_outside_72_78"] = round(float(((R < 72) | (R > 78)).mean()), 3)
    # the earlier instrument: fits seeded at R0 two frames after an R0-gated onset
    res["old_gate_share_of_new_drawn"] = round(float((st_old[idx] == 1).mean()), 3) if len(idx) else None
    rr = np.array([good[i]["r"] for i in good if st_old[i] == 1])
    res["r_fit_on_old_drawn_sd"] = round(float(rr.std()), 2) if len(rr) else None
    res["r_fit_on_old_drawn_n"] = int(len(rr))

    # 902-906 s, frame by frame
    w = np.nonzero((t >= 902.0) & (t <= 906.0))[0]
    res["span_902_906"] = [{"t": round(float(t[i]), 3), "pov": str(pov[i]), "state": int(st[i]),
                            "best": None if not np.isfinite(best[i]) else round(float(best[i]), 1),
                            "r_arg": None if not np.isfinite(r_arg[i]) else float(r_arg[i]),
                            "old_score": None if not np.isfinite(old_score[i]) else round(float(old_score[i]), 1),
                            "r_fit": round(good[i]["r"], 2) if i in good else None,
                            "rms": round(good[i]["rms"], 2) if i in good else None} for i in w]
    sr = np.array([good[i]["r"] for i in w if i in good])
    if len(sr):
        res["span_902_906_r_fit_min_max"] = [round(float(sr.min()), 2), round(float(sr.max()), 2)]
        res["span_902_906_fits"] = int(len(sr))

    # within a run: does the radius change as the circle fades?
    runs = [r for r in drawn_runs(t, st, best) if pov[r["i_on"]] == "own" and r["clean_on"] and r["clean_off"]]
    wr = []
    for r in runs:
        ii = [i for i in range(r["i_on"], r["i_off"] + 1) if i in good]
        if len(ii) < 3:
            continue
        rs_ = np.array([good[i]["r"] for i in ii])
        sc_ = np.array([good[i]["ring"] for i in ii])
        wr.append({"t_on": r["t_on"], "t_off": r["t_off"], "n": len(ii), "r_first": round(float(rs_[0]), 2),
                   "r_second": round(float(rs_[1]), 2), "r_last": round(float(rs_[-1]), 2),
                   "r_range": round(float(rs_.max() - rs_.min()), 2),
                   "slope_px_per_s": round(float(np.polyfit(t[ii], rs_, 1)[0]), 2),
                   "rho_r_ring": round(spearman(rs_, sc_), 2) if len(ii) >= 4 else None})
    res["runs_clean"] = len(runs)
    res["runs_fitted"] = len(wr)
    if wr:
        res["run_last_minus_second_median"] = round(float(np.median([x["r_last"] - x["r_second"] for x in wr])), 2)
        res["run_abs_last_minus_second_median"] = round(float(np.median([abs(x["r_last"] - x["r_second"]) for x in wr])), 2)
        res["run_r_range_median"] = round(float(np.median([x["r_range"] for x in wr])), 2)
        res["run_slope_median"] = round(float(np.median([x["slope_px_per_s"] for x in wr])), 2)
        rho = [x["rho_r_ring"] for x in wr if x["rho_r_ring"] is not None and np.isfinite(x["rho_r_ring"])]
        res["run_rho_r_ring_median"] = round(float(np.median(rho)), 2) if rho else None
        # between runs: the run's median radius
        res["run_median_r_hist_2px"] = np.histogram([np.median([good[i]["r"] for i in range(x_["i_on"], x_["i_off"] + 1)
                                                               if i in good]) for x_ in runs
                                                     if any(i in good for i in range(x_["i_on"], x_["i_off"] + 1))],
                                                    bins=np.arange(40, 140, 2.0))[0].tolist()
    res["run_rows"] = wr

    # -- The presence tests gate on the two sizes the fits found (SIZE_BAND), not on
    # the best ring at any radius, which map edges and circles round other centres
    # also win (its spectating drawn share is the false-positive witness).
    kb = (radii >= SIZE_BAND[0]) & (radii <= SIZE_BAND[1])
    band = np.nanmax(C[:, kb], 1)
    st_any, best_any = st, best
    st, best = states(band), band
    res["size_band"] = list(SIZE_BAND)
    res["band_own_drawn_frac"] = round(float((st[own & (st >= 0)] == 1).mean()), 3)
    res["band_other_drawn_frac"] = round(float((st[oth] == 1).mean()), 3) if oth.any() else None

    # -- movement: every own-view frame with a state, by the stored self speed
    track = sm.self_track()
    v = np.array([np.nan if (x := sm.speed_at(track, float(tt))) is None else x for tt in t])
    mv = np.array([move_class(None if np.isnan(x) else x) for x in v])
    sched = sm.phases()
    phase = np.array([sm.phase_at(sched, float(x)) for x in t])
    ok = own & (st >= 0)
    hv = ok & np.isfinite(v)
    e_ = np.arange(0, 21, 1.0)
    n_ = np.histogram(v[hv], bins=e_)[0]
    d_ = np.histogram(v[hv & (st == 1)], bins=e_)[0]
    res["speed_1px_frames"] = n_.tolist()
    res["speed_1px_drawn_share"] = np.round(d_ / np.maximum(n_, 1), 3).tolist()
    tab = {}
    for m in MOVES:
        s_ = ok & (mv == m)
        tab[m] = {"frames": int(s_.sum()), "drawn": int((st[s_] == 1).sum()),
                  "share": round(float((st[s_] == 1).mean()), 3) if s_.any() else None}
    res["movement_frames"] = tab
    # onsets: the movement state at each clean own-view onset
    ons = [r for r in drawn_runs(t, st, best) if pov[r["i_on"]] == "own" and r["clean_on"]]
    res["onsets_by_movement"] = {m: sum(1 for r in ons if mv[r["i_on"]] == m) for m in MOVES}
    # 1 s windows, non-overlapping, own view throughout: drawn anywhere inside vs the window's speed
    win = defaultdict(lambda: [0, 0])
    wrows = []
    for a in np.arange(np.floor(t[0]), t[-1], 1.0):
        m_ = (t >= a) & (t < a + 1) & ok
        if m_.sum() < 10 or not (own[(t >= a) & (t < a + 1)]).all():
            continue
        vv = sm.speed_at(track, a + 0.5)
        k = move_class(vv)
        ph = sm.phase_at(sched, a + 0.5)
        d_ = bool((st[m_] == 1).any())
        for key in (k, f"{k}|{ph}"):
            win[key][0] += 1
            win[key][1] += int(d_)
        wrows.append({"t0": float(a), "speed": vv, "move": k, "phase": ph, "drawn": d_})
    res["movement_windows_1s"] = {k: {"n": n, "drawn": d, "share": round(d / n, 3)} for k, (n, d) in sorted(win.items())}

    # -- the HUD: firing brackets by movement, drawn only as a new onset after an absence
    hs = sm.hud_samples()
    hud = defaultdict(list)
    for p_, q_ in zip(hs, hs[1:]):
        if p_["state"] != "gun" or q_["state"] != "gun" or p_["seg"] != q_["seg"]:
            continue
        if None in (p_["mag"], q_["mag"], p_["res"], q_["res"]):
            continue
        if sm.pov_at(spans, p_["t"]) != "own" or sm.pov_at(spans, q_["t"]) != "own":
            continue
        if p_["res"] == q_["res"] and q_["mag"] < p_["mag"]:
            kind = "firing"
        elif p_["res"] == q_["res"] and q_["mag"] == p_["mag"]:
            kind = "quiet"
        else:
            continue
        vv = sm.speed_at(track, (p_["t"] + q_["t"]) / 2)
        kind += "_" + move_class(vv)
        w_ = (t >= p_["t"]) & (t <= q_["t"] + WIN[1]) & (st >= 0)
        pre = (t >= p_["t"] - 0.5) & (t < p_["t"]) & (st >= 0)
        if w_.sum() < 3 or not pre.any():
            continue
        absent = bool((st[pre] == 0).all())
        hud[kind].append({"t_prev": p_["t"], "t_new": q_["t"], "speed": vv, "absent_before": absent,
                          "drawn": bool((st[w_] == 1).any()), "mag": [p_["mag"], q_["mag"]]})
    res["hud"] = {k: {"n": len(x), "n_absent_before": sum(r["absent_before"] for r in x),
                      "drawn_after_absent": sum(r["drawn"] for r in x if r["absent_before"])}
                  for k, x in sorted(hud.items())}

    # -- the bank: own-view own-sound detections by class and movement; circle = an onset within the window
    dets = [d for d in sm.load_dets() if sm.pov_at(spans, d["t"]) == "own" and abs(d["ild_db"]) < OWN_ILD_DB]
    on_t = np.array([r["t_on"] for r in ons])
    bank = defaultdict(lambda: [0, 0, 0])            # n, drawn in window, new onset in window
    brows = []
    for d in dets:
        w_ = (t >= d["t"] + WIN[0]) & (t <= d["t"] - WIN[0]) & (st >= 0)
        if w_.sum() < 3:
            continue
        vv = sm.speed_at(track, d["t"])
        m = move_class(vv)
        drawn = bool((st[w_] == 1).any())
        onset = bool(((on_t - d["t"] >= WIN[0]) & (on_t - d["t"] <= WIN[1])).any())
        key = f"{d['cls']}|{m}"
        bank[key][0] += 1
        bank[key][1] += int(drawn)
        bank[key][2] += int(onset)
        brows.append({"t": d["t"], "cls": d["cls"], "move": m, "speed": vv, "drawn": drawn, "onset": onset})
    res["bank"] = {k: {"n": a, "drawn": b, "onset": c} for k, (a, b, c) in sorted(bank.items())}

    # -- the two sizes: fits under SIZE_CUT are the small circle. Speed and whether the
    # HUD shows no gun counter (knife or ability held) at each fitted frame.
    ht = np.array([h["t"] for h in hs])
    hid = lambda x: hs[max(0, int(np.searchsorted(ht, x)) - 1)]["state"] == "hidden"   # noqa: E731
    for name, sel in (("small", lambda r: r < SIZE_CUT), ("large", lambda r: r >= SIZE_CUT)):
        ii = [i for i, f in good.items() if sel(f["r"])]
        if not ii:
            continue
        rr_ = np.array([good[i]["r"] for i in ii])
        vv_ = v[ii][np.isfinite(v[ii])]
        res[f"{name}_fits"] = len(ii)
        res[f"{name}_r_median"] = round(float(np.median(rr_)), 2)
        res[f"{name}_r_sd"] = round(float(rr_.std()), 2)
        res[f"{name}_speed_median"] = round(float(np.median(vv_)), 2) if len(vv_) else None
        res[f"{name}_hidden_hud"] = sum(hid(t[i]) for i in ii)
        if name == "small":
            ts_ = sorted(t[ii])
            res["small_runs"] = 1 + sum(1 for a_, b_ in zip(ts_, ts_[1:]) if b_ - a_ > 0.2)
            res["small_frames_t"] = [round(float(x), 3) for x in ts_]

    # -- magazine refills (found after the small circle's times were seen, so not a
    # pre-registered test): a read magazine that rises between consecutive samples
    # within 3 s. A refill "has" a size when a fit of that size falls in [prev - 2 s, new].
    # Control: 2.5 s own-view windows clear of every refill window by 0.5 s.
    small_t = np.array([t[i] for i, f in good.items() if f["r"] < SIZE_CUT])
    large_t = np.array([t[i] for i, f in good.items() if f["r"] >= SIZE_CUT])
    own_t = t[pov == "own"]
    refills, last = [], None
    for h in hs:
        if h["mag"] is None:
            continue
        if last is not None and h["mag"] > last["mag"] and h["t"] - last["t"] <= 3.0:
            a_, b_ = last["t"] - 2.0, h["t"]
            if ((own_t >= a_) & (own_t <= b_)).any():
                refills.append({"t_prev": last["t"], "t_new": h["t"], "mag": [last["mag"], h["mag"]],
                                "res": [last["res"], h["res"]],
                                "small": int(((small_t >= a_) & (small_t <= b_)).sum()),
                                "large": int(((large_t >= a_) & (large_t <= b_)).sum())})
        last = h
    ctrl = []
    for a_ in np.arange(t.min(), t.max() - 2.5, 2.5):
        if any(a_ - 0.5 <= r["t_new"] and a_ + 3.0 >= r["t_prev"] - 2.0 for r in refills):
            continue
        if ((own_t >= a_) & (own_t < a_ + 2.5)).sum() < 20:
            continue
        ctrl.append(bool(((small_t >= a_) & (small_t < a_ + 2.5)).any()))
    near = [bool(len(small_t) and np.min(np.abs(np.array([r["t_new"] for r in refills] + [r["t_prev"] for r in refills]) - x)) <= 2.5)
            for x in small_t] if refills else []
    res["refills"] = len(refills)
    res["refills_with_small"] = sum(r["small"] > 0 for r in refills)
    res["refills_with_large_only"] = sum(r["small"] == 0 and r["large"] > 0 for r in refills)
    res["refills_without_circle"] = sum(r["small"] == 0 and r["large"] == 0 for r in refills)
    res["refill_control_windows"] = len(ctrl)
    res["refill_control_with_small"] = sum(ctrl)
    res["small_fits_within_2_5s_of_refill"] = sum(near)
    # the player (2026-09-30): a reload draws the small circle while no footstep sounds,
    # and a footstep's circle supersedes it. Split refills by an own footstep detection
    # (the bank's, own view, level-split) in the same window; the bank is unreliable in
    # match audio, so this is a weak tally.
    fs_t = np.array([d_["t"] for d_ in dets if d_["cls"] == "footstep"])
    for r in refills:
        r["own_footsteps"] = int(((fs_t >= r["t_prev"] - 2.0) & (fs_t <= r["t_new"])).sum())
    for fk, fsel in (("footstep", lambda r: r["own_footsteps"] > 0), ("no_footstep", lambda r: r["own_footsteps"] == 0)):
        rr = [r for r in refills if fsel(r)]
        res[f"refills_{fk}"] = len(rr)
        res[f"refills_{fk}_small"] = sum(r["small"] > 0 for r in rr)
        res[f"refills_{fk}_large_only"] = sum(r["small"] == 0 and r["large"] > 0 for r in rr)
        res[f"refills_{fk}_none"] = sum(r["small"] == 0 and r["large"] == 0 for r in rr)
    res["refill_rows"] = refills

    # disagreements with "only from running", stored apart
    dis = ([{"kind": "onset_while_still", "t_on": r["t_on"], "t_off": r["t_off"], "speed": float(v[r["i_on"]]),
             "r_fit": good[r["i_on"] + 1]["r"] if r["i_on"] + 1 in good else None}
            for r in ons if mv[r["i_on"]] == "still"]
           + [{"kind": "moving_window_without_circle", **x} for x in wrows if x["move"] == "moving" and not x["drawn"]]
           + [{"kind": "still_shot_with_new_circle", **x} for x in hud.get("firing_still", [])
              if x["absent_before"] and x["drawn"]])
    res["disagreements"] = {k: sum(1 for x in dis if x["kind"] == k) for k in
                            ("onset_while_still", "moving_window_without_circle", "still_shot_with_new_circle")}
    PF_OUT.mkdir(parents=True, exist_ok=True)
    (PF_OUT / "disagreements.jsonl").write_text("".join(json.dumps(x, default=float) + "\n" for x in dis),
                                                encoding="utf-8")
    (PF_OUT / "bank_rows.jsonl").write_text("".join(json.dumps(x, default=float) + "\n" for x in brows),
                                            encoding="utf-8")
    np.savez_compressed(PF_OUT / "per_frame.npz", t=t, best=best_any, band=best, r_arg=r_arg, state=st, state_any=st_any, state_old=st_old,
                        speed=v, pov=pov,
                        r_fit=np.array([good[i]["r"] if i in good else np.nan for i in range(len(t))]))
    (PF_OUT / "per_frame.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    if record:
        record_per_frame(res)
    return res


def record_per_frame(res: dict) -> None:
    from reticle import metrics
    v = {k: res[k] for k in (
        "R0_median_curve", "own_frames", "own_drawn_frames", "own_drawn_frac", "own_drawn_frac_old",
        "other_drawn_frac", "band_own_drawn_frac", "band_other_drawn_frac", "r_arg_share_outside_72_78", "drawn_new_not_old", "drawn_old_not_new", "fits",
        "fits_good", "r_fit_median", "r_fit_sd", "r_fit_share_outside_72_78", "old_gate_share_of_new_drawn",
        "r_fit_on_old_drawn_sd", "r_fit_on_old_drawn_n", "span_902_906_fits", "runs_clean", "runs_fitted",
        "run_last_minus_second_median", "run_abs_last_minus_second_median", "run_r_range_median",
        "run_slope_median", "run_rho_r_ring_median") if res.get(k) is not None}
    for name, key in (("r_fit_p5", 0), ("r_fit_p25", 1), ("r_fit_p75", 2), ("r_fit_p95", 3)):
        if "r_fit_p5_p25_p75_p95" in res:
            v[name] = res["r_fit_p5_p25_p75_p95"][key]
    if "r_fit_min_max" in res:
        v["r_fit_min"], v["r_fit_max"] = res["r_fit_min_max"]
    if "span_902_906_r_fit_min_max" in res:
        v["span_902_906_r_min"], v["span_902_906_r_max"] = res["span_902_906_r_fit_min_max"]
    for j, m in enumerate(res.get("r_fit_modes", [])):
        v[f"r_fit_mode{j}_r"], v[f"r_fit_mode{j}_n"] = m["r"], m["n"]
    for k, w in res["movement_frames"].items():
        v[f"frames_{k}_n"], v[f"frames_{k}_drawn"] = w["frames"], w["drawn"]
        if w["share"] is not None:
            v[f"frames_{k}_share"] = w["share"]
    for k, w in res["movement_windows_1s"].items():
        k = k.replace("|", "_")
        v[f"win1s_{k}_n"], v[f"win1s_{k}_drawn"], v[f"win1s_{k}_share"] = w["n"], w["drawn"], w["share"]
    for k, n in res["onsets_by_movement"].items():
        v[f"onsets_{k}"] = n
    for k, w in res["hud"].items():
        v[f"hud_{k}_n"], v[f"hud_{k}_absent_before"], v[f"hud_{k}_drawn_after_absent"] = (
            w["n"], w["n_absent_before"], w["drawn_after_absent"])
    for k, w in res["bank"].items():
        c, m = k.split("|")
        v[f"bank_{c}_{m}_n"], v[f"bank_{c}_{m}_drawn"], v[f"bank_{c}_{m}_onset"] = w["n"], w["drawn"], w["onset"]
    for k, n in res["disagreements"].items():
        v[f"dis_{k}"] = n
    for i, (n, s) in enumerate(zip(res["speed_1px_frames"], res["speed_1px_drawn_share"])):
        v[f"speed_{i:02d}_frames"], v[f"speed_{i:02d}_drawn_share"] = n, s
    for k in (("small_fits", "large_fits", "small_runs", "small_hidden_hud", "large_hidden_hud",
              "small_speed_median", "large_speed_median", "small_r_median", "large_r_median",
              "small_r_sd", "large_r_sd", "refills", "refills_with_small", "refills_with_large_only",
              "refills_without_circle", "refill_control_windows", "refill_control_with_small",
              "small_fits_within_2_5s_of_refill")
              + tuple(f"refills_{a}{b}" for a in ("footstep", "no_footstep")
                      for b in ("", "_small", "_large_only", "_none"))):
        if res.get(k) is not None:
            v[k] = res[k]
    metrics.record("audio_circle", part="per-frame", session=ISO, values=v,
                   deps={"version": PF_VERSION, "curves": VERSION, "t_hi": T_HI, "t_lo": T_LO, "clean": CLEAN,
                         "own_ild_db": OWN_ILD_DB, "window": list(WIN), "self_win_ms": SELF_WIN_MS,
                         "still_lt": 2.0, "moving_ge": 8.0, "fit_good": "inliers >= 0.5 and rms < 1.5",
                         "detections": "analysis/sound-match/detections (sound-match-0.1.0)"},
                   context={"cache": "roi-cache-0.1.0 minimap 15 Hz", "minimap": "minimap-0.7.0",
                            "tray_kit": "tray-kit-0.1.0", "hud": "hud-0.16.0 2 Hz",
                            "geometry": "split__valorant-16x9"},
                   note="self audio circle per frame and against movement on the Iso capture; not wired")
    print(f"recorded {len(v)} values under audio_circle/per-frame@{ISO}")


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
    b.add_argument("--per-frame", action="store_true",
                   help="radius per frame over every searched radius, and presence against movement")
    f = sub.add_parser("frames")
    f.add_argument("session")
    f.add_argument("t0", type=float)
    f.add_argument("t1", type=float)
    f.add_argument("--fit", action="store_true")
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
    elif args.cmd == "frames":
        frames_sheet(args.session, args.t0, args.t1, fit=args.fit)
    elif args.cmd == "score" and args.per_frame:
        res = per_frame(args.record)
        print(json.dumps({k: v for k, v in res.items() if k not in ("span_902_906", "run_rows")}, indent=1))
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
