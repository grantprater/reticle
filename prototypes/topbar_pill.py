r"""Does the top bar's white pill show health alone, or health plus shield?

The player (2026-10-04) says the pill under each top-bar portrait shows
health and probably not shield. The game's widget export names the binding:
`PlayerParticipantWidget_v2.UpdateWidgets` holds `GetHealth`,
`GetMaxHealth`, `Divide` and `SetPercent` locals beside the `Health`
ProgressBar, and no shield or armor getter appears anywhere in the export.
This prototype measures the pill against the bottom HUD's stored `hp` and
`shield` [domain:hud/topbar-health-pill].

What it reads, and from where
-----------------------------
Only the `hud` crop cache (`roi_cache`, 2 Hz): the `hud_roster` crop. No
decode. The player's own pill only, while the player lives: each round runs
from its start to its close or the player's first death in it (stored
`death` verdicts with `is_player_death`), less `DEATH_GUARD_MS` before the
death. After a death the bottom HUD shows the spectated teammate, so those
spans are left out.

Who the player is, and where the player's pill is drawn
-------------------------------------------------------
The identity arbiter names the player's agent and its lineup slot
(`adjudication.identity.player_identity`, the `player-agent` owner's
answer, read from `lineup.load_lineup`); this script decides neither. The
lineup reader reads the top bar only while a side is fully alive, so its
slot is the drawn position only on frames where the roster owner counts all
five allies (`roster.resolve`, given the stored menu witness its docstring
requires, `menu.stored_menu`). Every other frame is left out: where
survivors are drawn after a death is the roster owner's question, and no
domain fact records whether they keep team order.

How the fill is read
--------------------
Geometry is fitted per session from full-health, full-shield frames: the
pill band's rows and each slot's pill ends, sub-pixel, by linear
interpolation where the median whiteness crosses half its height. Each
frame's band rows are averaged into one colour per column: a box filter
over whole rows, the only resample; no frame is enlarged.

The empty part of the pill is a translucent white track over the scene, so
its colour is predicted per column from the scene just above and below the
pill: `E = a * 255 + (1 - a) * scene`. The translucency `a` is fitted per
session on the pill's last interior columns of frames with hp <= 60, where
both hypotheses agree the pill is empty (hp/100 <= 0.6, (hp+shield)/150 <=
0.74). The fill is opaque; its colour `F` is the frame's own colour over the
first interior columns past the rounded left cap (white, red or teal). Each
column scores softly as its projection between `E` and `F`, clipped to [0,
1]; the fill length is the cap plus the sum of those scores: sub-pixel,
never binarised, cut once at the hypothesis test. A frame refuses, with its
reason, where `F` lies too close to `E` at the fill columns (`fill_unseen`:
the fill ends inside the cap, or the scene lights the track to the fill's
colour) or where more than `MAX_FLAT_COLS` columns have no contrast
(`low_contrast`). 0.3.0's per-frame two-level step fit split full pills at
small shading steps (4f207c0c4e39: 424.5 s read 0.900, 254.0 s read 0.7465);
fixed per-column levels do not.

The fill is regressed on hp/100 and on (hp+shield)/150, both as logged in
advance (least squares in px per session; the slope band) and robustly
(one scale per hypothesis, pooled). Rows where `shield` is null are kept
apart: the HUD reader returns null both for no shield and for an unread
one.

Run:  python -m prototypes.topbar_pill  (writes <store>/analysis/topbar-pill-0.4.0/)
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import numpy as np

from reticle import metrics
from reticle import roster as roster_mod
from reticle.adjudication.identity import player_identity
from reticle.lineup import load_lineup
from reticle.menu import stored_menu
from reticle.profiles import get_profile
from reticle.roi_cache import RoiCache
from reticle.store import Store

VERSION = "topbar-pill-0.4.0"
STORE = Path("C:/Users/grant/reticle-store")
SESSIONS = (("4f207c0c4e39", "2026-09-28"), ("59c70f1ef720", "2026-08-24"),
            ("a06f04a0059f", "2026-08-26"))
#: Samples this close before the player's death are left out: the killfeed
#: entry trails the death, and the bottom HUD may already show a teammate.
DEATH_GUARD_MS = 1500.0
#: Predictors that differ by at least this much discriminate the hypotheses.
DISCRIMINATE = 0.10
N_SLOTS = 5
#: Columns of the pill's rounded left cap, counted as fill when the fill is
#: seen past them.
CAP_PX = 3
#: Interior columns past the cap whose mean colour is the frame's fill.
FILL_COLS = 3
#: Scene rows above and below the band (crop rows relative to the band's
#: first and last rows), past the pill's dark outline.
SCENE_ABOVE = (-6, -3)
SCENE_BELOW = (4, 7)
#: Last interior columns that fit the track's translucency, and the hp at or
#: under which both hypotheses call them empty.
TRACK_COLS = 3
TRACK_HP_MAX = 60.0
#: RGB distance between fill and track under which a column carries no
#: contrast, and how many such columns a frame may hold.
MIN_CONTRAST = 30.0
MAX_FLAT_COLS = 2
#: The slope band logged in advance (px per unit fraction).
SLOPE_BAND = (36.0, 48.0)
RMS_MAX_PX = 2.0
#: Full pills 0.3.0 misread, (t_ms, drawn slot): 424.5 s slot 1 read 0.900
#: and 254.0 s slot 2 read 0.7465. Fewer than five allies live there, so
#: they are no self sample; the same reader reads them as a check.
PROBES = {"4f207c0c4e39": ((424500.0, 1), (254000.0, 2))}


def _below_normal() -> None:
    if sys.platform == "win32":
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)


def alive_spans(store: Store, sid: str, date: str) -> list[tuple[float, float]]:
    """(start, stop) per round: start to the player's first death or the close."""
    r = store.read_rounds(sid, date).to_pydict()
    deaths = np.array(sorted(e["t_ms"] for e in store.read_events("death", sid)
                             if e.get("kind") == "death_verdict" and not e.get("is_revive")
                             and (e.get("metadata") or {}).get("is_player_death")), float)
    a = np.asarray(r["t_start_ms"], float)
    z = np.asarray(r["t_close_ms"], float)
    deaths = np.r_[deaths, np.inf]
    d = deaths[np.searchsorted(deaths, a)]               # first death at or after the start
    stop = np.where(d < z, d - DEATH_GUARD_MS, z)
    return list(zip(a.tolist(), stop.tolist()))


def geometry(whiteness: np.ndarray) -> tuple[slice, list[tuple[float, float]]]:
    """Centre rows of the pill band and each slot's (left, right) ends, from
    the median min-channel image of full-pill frames."""
    med = np.median(whiteness, axis=0)
    rows = med.mean(axis=1)
    base = np.median(rows)
    peak = rows.max()
    band = np.where(rows > base + 0.75 * (peak - base))[0]
    rs = slice(int(band.min()), int(band.max()) + 1)
    prof = med[rs].mean(axis=0)
    lo, hi = np.percentile(prof, 10), np.percentile(prof, 99)
    half = (lo + hi) / 2
    above = prof > half
    edges = np.flatnonzero(np.diff(above.astype(np.int8)))
    l, r = edges[0::2][: len(edges) // 2], edges[1::2][: len(edges) // 2]
    # sub-pixel crossings by linear interpolation of the smooth profile
    xl = l + (half - prof[l]) / (prof[l + 1] - prof[l]) + 0.5
    xr = r + (half - prof[r]) / (prof[r + 1] - prof[r]) + 0.5
    return rs, [(float(a), float(b)) for a, b in zip(xl, xr)]


def track_colour(scene: np.ndarray, a: float) -> np.ndarray:
    """The empty track's predicted colour over `scene` (any shape, RGB last)."""
    return a * 255.0 + (1.0 - a) * scene


def fit_translucency(P: np.ndarray, scene: np.ndarray) -> float:
    """`a` in `band = a * 255 + (1 - a) * scene` on empty columns, as the
    median of per-value ratios (robust to a mis-slotted frame)."""
    u = (255.0 - scene).ravel()
    v = (P - scene).ravel()
    ok = u > 40.0
    return float(np.median(v[ok] / u[ok]))


def fill_end(P: np.ndarray, E: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Soft fill length in px past the cap of each profile `P` (n, W, 3)
    against its predicted track colour `E` (n, W, 3), and the refusal reason
    per frame ('' where read)."""
    F = P[:, :FILL_COLS].mean(1, keepdims=True)                  # (n, 1, 3)
    d = F - E                                                    # (n, W, 3)
    dd = (d ** 2).sum(2)
    alpha = np.clip(((P - E) * d).sum(2) / np.maximum(dd, 1e-6), 0.0, 1.0)
    flat = dd < MIN_CONTRAST ** 2
    unseen = flat[:, :FILL_COLS].any(1)
    low = flat.sum(1) > MAX_FLAT_COLS
    why = np.where(unseen, "fill_unseen", np.where(low, "low_contrast", ""))
    return alpha.sum(1), why


def profiles(stack: np.ndarray, rs: slice, a: float, b: float) -> tuple[np.ndarray, np.ndarray]:
    """Per frame of `stack` (n, h, w, 3), the band's colour per interior
    column past the cap of the pill at (a, b), and the scene's above and
    below it (box means over whole rows)."""
    lo, hi = int(np.ceil(a)), int(np.floor(b))
    cols = slice(lo + CAP_PX, hi)
    band = stack[:, rs, cols].mean(axis=1)
    above = stack[:, rs.start + SCENE_ABOVE[0]:rs.start + SCENE_ABOVE[1], cols].mean(1)
    below = stack[:, rs.stop - 1 + SCENE_BELOW[0]:rs.stop - 1 + SCENE_BELOW[1], cols].mean(1)
    return band, 0.5 * (above + below)


def read_pill(band: np.ndarray, scene: np.ndarray, alpha_track: float,
              a: float) -> tuple[np.ndarray, np.ndarray]:
    """Fill length in px from the pill's fitted left end, and the refusal."""
    soft, refused = fill_end(band, track_colour(scene, alpha_track))
    return (int(np.ceil(a)) - a) + CAP_PX + soft, refused


def fit(x: np.ndarray, y: np.ndarray) -> dict:
    A = np.c_[x, np.ones_like(x)]
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ coef
    return {"slope_px": round(float(coef[0]), 2), "intercept_px": round(float(coef[1]), 2),
            "rms_px": round(float(np.sqrt(np.mean(res ** 2))), 3),
            "median_abs_px": round(float(np.median(np.abs(res))), 3), "n": int(len(y))}


def session(store: Store, sid: str, date: str) -> dict:
    man = store.read_manifest(sid)
    rc, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "hud")
    if rc is None:
        return {"session": sid, "refused": f"no hud crop cache: {why}"}
    who = player_identity(load_lineup(sid, STORE), sid)
    if who["agent"] is None or who["slot"] is None:
        return {"session": sid, "refused": f"player identity {who['status']}: {who['reason']}"}
    slot = int(who["slot"])
    hud = store.read_hud(sid, date)
    ros = store.read_roster(sid, date)
    menu, menu_stamp = stored_menu(store, sid)
    ally, _ = roster_mod.resolve(hud, ros, menu=menu.at if menu is not None else None)
    ally_nomenu, _ = roster_mod.resolve(hud, ros)
    rt = np.asarray(ros.column("t_ms").to_pylist(), float)
    na = np.array([-1 if v is None else v for v in ally])
    na0 = np.array([-1 if v is None else v for v in ally_nomenu])
    tm = hud.column("t_ms").to_numpy().astype(float)
    hp = np.array(hud.column("hp").to_pylist(), dtype=float)
    sh = np.array(hud.column("shield").to_pylist(), dtype=float)
    # each HUD sample takes the roster row at its own time (both run at 2 Hz)
    k = np.searchsorted(rt, tm)
    hit = (k < len(rt)) & (rt[np.minimum(k, len(rt) - 1)] == tm)
    n_ally = np.where(hit, na[np.minimum(k, len(rt) - 1)], -1)
    n_ally0 = np.where(hit, na0[np.minimum(k, len(rt) - 1)], -1)
    spans = np.array(alive_spans(store, sid, date))
    inside = ((tm[:, None] >= spans[:, 0]) & (tm[:, None] < spans[:, 1])).any(1)
    base = inside & (hp >= 1) & (hp <= 100)
    menu_changed = int((base & (n_ally0 == N_SLOTS) & (n_ally != N_SLOTS)).sum())
    keep = base & (n_ally == N_SLOTS)
    idx = np.flatnonzero(keep)

    x0, y0, x1, y1 = rc.stored_rect("hud_roster")
    crops = {smp.t_ms: smp.frame[y0:y1, x0:x1] for smp in
             rc.samples(tm[idx].tolist(), rois=["hud_roster"])}
    idx = idx[np.isin(tm[idx], np.fromiter(crops, float))]
    stack = np.stack([crops[t] for t in tm[idx]]).astype(np.float32)

    full = (hp[idx] == 100) & (sh[idx] == 50)
    rs, ends = geometry(stack[full].min(axis=3))
    if len(ends) != N_SLOTS:
        return {"session": sid, "refused": f"found {len(ends)} pill ends, not 5", "ends": ends}
    a, b = ends[slot]
    band, scene = profiles(stack, rs, a, b)
    empty = hp[idx] <= TRACK_HP_MAX
    alpha_track = fit_translucency(band[empty, -TRACK_COLS:], scene[empty, -TRACK_COLS:])
    fill_px, refused = read_pill(band, scene, alpha_track, a)
    width = b - a
    frac = fill_px / width
    probes = {}
    for t, s in PROBES.get(sid, ()):
        got = [smp.frame[y0:y1, x0:x1] for smp in rc.samples([t], rois=["hud_roster"])]
        if not got:
            probes[f"{t:.1f}@{s}"] = {"refused": "not_in_crop_cache"}
            continue
        pa, pb = ends[s]
        pband, pscene = profiles(got[0][None].astype(np.float32), rs, pa, pb)
        pf, pr = read_pill(pband, pscene, alpha_track, pa)
        probes[f"{t:.1f}@{s}"] = {"fill_frac": round(float(pf[0] / (pb - pa)), 4),
                                  "refused": pr[0] or None}
    read = refused == ""
    out = {"session": sid, "date": date, "capture": man["source"].get("path"),
           "self_agent": who["agent"], "self_lineup_slot": slot,
           "identity": {k: who.get(k) for k in ("status", "channels", "independent_channels",
                                                "player_agent_version")},
           "menu_witness": menu_stamp, "menu_changed_five_ally_rows": menu_changed,
           "band_rows": [rs.start + y0, rs.stop - 1 + y0],
           "pill_ends_px": [[round(p, 2), round(q, 2)] for p, q in ends],
           "track_translucency": round(alpha_track, 4), "width_px": round(width, 2),
           "n_five_allies_alive": int(len(idx)), "probe_full_pills": probes,
           "refusals": {r: int((refused == r).sum()) for r in ("fill_unseen", "low_contrast")}}
    s = sh[idx]
    hasS = (s == s) & read
    h1 = hp[idx] / 100.0
    h2 = (hp[idx] + np.nan_to_num(s)) / 150.0
    disc = hasS & (np.abs(h1 - h2) >= DISCRIMINATE)
    logged = {}
    for sub, m in (("all", hasS), ("discriminating", disc)):
        if m.sum() >= 5:
            logged[sub] = {"health_only": fit(h1[m], fill_px[m]),
                           "health_plus_shield": fit(h2[m], fill_px[m])}
    out["logged_fits"] = logged
    out["samples_self"] = [
        {"t_ms": float(t), "slot": slot, "hp": float(p),
         "shield": None if q != q else float(q),
         "fill_px": None if r else round(float(f), 2),
         "fill_frac": None if r else round(float(g), 4), "refused": r or None}
        for t, p, q, f, g, r in zip(tm[idx], hp[idx], s, fill_px, frac, refused)]
    return out


def pooled(results: list[dict]) -> dict:
    """Self-slot samples of every session, fill as a fraction of the pill."""
    rows = [r for res in results for r in res.get("samples_self", [])
            if r["shield"] is not None and r["fill_frac"] is not None]
    f = np.array([r["fill_frac"] for r in rows])
    hp = np.array([r["hp"] for r in rows])
    sh = np.array([r["shield"] for r in rows])
    h1 = hp / 100
    h2 = (hp + sh) / 150
    disc = np.abs(h1 - h2) >= DISCRIMINATE
    out = {"n_with_shield_read": len(rows)}
    # Robust: each hypothesis gets one scale, the median of fill/pred. The
    # raw share within 0.05 (scale 1) stands beside the scaled one.
    for sub, m in (("all", np.ones_like(f, bool)), ("discriminating", disc),
                   ("damaged_discriminating", disc & (hp < 100))):
        row = {"n": int(m.sum())}
        for name, pred in (("health_only", h1), ("health_plus_shield", h2)):
            ok = m & (pred > 0.2)
            scale = float(np.median(f[ok] / pred[ok]))
            res = np.abs(f[m] - scale * pred[m])
            raw = np.abs(f[m] - pred[m])
            row[name] = {"scale": round(scale, 4),
                         "median_abs_err_frac": round(float(np.median(res)), 4),
                         "within_0.05": round(float(np.mean(res <= 0.05)), 4),
                         "within_0.05_unscaled": round(float(np.mean(raw <= 0.05)), 4)}
        out[sub] = row
    s1 = out["all"]["health_only"]["scale"]
    out["outliers_health_only_gt_0.1"] = round(float(np.mean(np.abs(f - s1 * h1) > 0.1)), 4)
    # The cleanest contrast: full health, shield 0 (null), 25 or 50. Health
    # alone predicts one fill; health plus shield predicts 100/150, 125/150
    # and 150/150 of it.
    out["full_health_by_shield"] = {}
    for s in (None, 25.0, 50.0):
        v = np.array([r["fill_frac"] for res in results for r in res.get("samples_self", [])
                      if r["hp"] == 100 and r["shield"] == s and r["fill_frac"] is not None])
        if len(v):
            out["full_health_by_shield"]["null" if s is None else str(int(s))] = {
                "n": int(len(v)), "median_fill_frac": round(float(np.median(v)), 4),
                "p10": round(float(np.percentile(v, 10)), 4),
                "p90": round(float(np.percentile(v, 90)), 4)}
    return out


def logged_tests(results: list[dict]) -> dict:
    """The tests as logged before 0.3.0 measured: per session, H1 holds if
    hp/100's least-squares RMS is <= 2 px and (hp+shield)/150's is not 25%
    lower; H2 falls if hp/100 fits better on discriminating rows; P3 holds
    if the better fit's slope lies in 36-48 px."""
    out = {}
    for r in results:
        lf = r.get("logged_fits") or {}
        if "all" not in lf:
            continue
        a1, a2 = lf["all"]["health_only"], lf["all"]["health_plus_shield"]
        d = lf.get("discriminating")
        best = a1 if a1["rms_px"] <= a2["rms_px"] else a2
        out[r["session"]] = {
            "H1_holds": a1["rms_px"] <= RMS_MAX_PX and not a2["rms_px"] <= 0.75 * a1["rms_px"],
            "H2_falls": bool(d) and d["health_only"]["rms_px"] < d["health_plus_shield"]["rms_px"],
            "P3_slope_in_band": SLOPE_BAND[0] <= best["slope_px"] <= SLOPE_BAND[1],
            "rms_px": [a1["rms_px"], a2["rms_px"]],
            "disc_rms_px": [d["health_only"]["rms_px"], d["health_plus_shield"]["rms_px"]] if d else None,
            "slope_px": best["slope_px"]}
    return out


def main() -> None:
    _below_normal()
    store = Store(STORE)
    results = [session(store, sid, d) for sid, d in SESSIONS]
    summary = {"version": VERSION, "pooled_self": pooled(results),
               "logged_tests": logged_tests(results),
               "probe_full_pills": {r["session"]: r.get("probe_full_pills") for r in results},
               "sessions": [{k: v for k, v in r.items() if k != "samples_self"} for r in results]}
    dest = STORE / "analysis" / VERSION
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    with open(dest / "samples_self.jsonl", "w", encoding="utf-8") as fh:
        for r in results:
            for row in r.get("samples_self", []):
                fh.write(json.dumps({"session": r["session"], **row}) + "\n")
    p = summary["pooled_self"]
    fb, dd = p["full_health_by_shield"], p["damaged_discriminating"]
    metrics.record(
        "topbar_pill", part="self_alive", session="",
        values={"n": p["all"]["n"],
                "full_hp_shield_null_fill": fb["null"]["median_fill_frac"],
                "full_hp_shield_25_fill": fb["25"]["median_fill_frac"],
                "full_hp_shield_50_fill": fb["50"]["median_fill_frac"],
                "all_health_only_scale": p["all"]["health_only"]["scale"],
                "all_health_only_within_005": p["all"]["health_only"]["within_0.05"],
                "all_health_plus_shield_within_005": p["all"]["health_plus_shield"]["within_0.05"],
                "all_health_only_within_005_unscaled": p["all"]["health_only"]["within_0.05_unscaled"],
                "all_health_plus_shield_within_005_unscaled":
                    p["all"]["health_plus_shield"]["within_0.05_unscaled"],
                "outliers_health_only_gt_01": p["outliers_health_only_gt_0.1"],
                "damaged_disc_n": dd["n"],
                "damaged_health_only_scale": dd["health_only"]["scale"],
                "damaged_health_only_within_005": dd["health_only"]["within_0.05"],
                "damaged_health_plus_shield_scale": dd["health_plus_shield"]["scale"]},
        deps={"version": VERSION, "sessions": [s for s, _ in SESSIONS],
              "roi_cache": "roi-cache-0.1.0"},
        context={"store_dir": f"analysis/{VERSION}"},
        note="top-bar pill fill vs bottom-HUD hp and shield, player's own slot, five allies alive")
    print(json.dumps({k: v for k, v in summary.items() if k != "sessions"}, indent=1))
    print(json.dumps([{k: v for k, v in r.items() if k not in ("logged_fits",)}
                      for r in summary["sessions"]], indent=1))


if __name__ == "__main__":
    main()
