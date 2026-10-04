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

The player's slot comes from the stored lineup (`lineups/<sid>.json`, team
order left to right) and the player's agent (`SELF_AGENT`). Survivors pack
toward the scoreline keeping team order, so the player's drawn position is
the lineup slot only while all five allies live, unless the lineup slot is
the outermost (drawn position 5 - allies alive, the roster owner's count,
`roster.resolve`) or the innermost (always 4); other frames are left out.
The local player does NOT always stand first: on 59c70f1ef720 the player's
Sova is lineup slot 2, and an outermost-slot rule (0.1.0 of this script)
read the wrong pill there.

How the fill is read
--------------------
Geometry is fitted per session from full-health, full-shield frames: the
pill band's rows and each slot's pill ends, sub-pixel, where the median
whiteness crosses half its height. Per frame the band's centre rows are
averaged into a colour profile across the pill. A two-level step fit
(vectorised over frames and split points through cumulative sums) gives the
fill colour and the background colour; each column's coverage is its
projection between the two, clipped to [0, 1], and the fill end is the sum
of coverages: soft, sub-pixel, never binarised. A one-level profile (the BIC
prefers no step) is a full pill: the player is alive, so the fill is never
empty.

The fill end is regressed on hp/100 and on (hp+shield)/150; the residual
RMS of each, on all rows and on rows where the two predictors differ by at
least 0.1, decides. Rows where `shield` is null are kept apart: the HUD
reader returns null both for no shield and for an unread one.

Run:  python -m prototypes.topbar_pill  (writes <store>/analysis/topbar-pill-0.3.0/)
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import cv2
import numpy as np

from reticle import metrics
from reticle import roster as roster_mod
from reticle.profiles import get_profile
from reticle.roi_cache import RoiCache
from reticle.store import Store

VERSION = "topbar-pill-0.3.0"
STORE = Path("C:/Users/grant/reticle-store")
SESSIONS = (("4f207c0c4e39", "2026-09-28"), ("59c70f1ef720", "2026-08-24"),
            ("a06f04a0059f", "2026-08-26"))
#: Samples this close before the player's death are left out: the killfeed
#: entry trails the death, and the bottom HUD may already show a teammate.
DEATH_GUARD_MS = 1500.0
#: Predictors that differ by at least this much discriminate the hypotheses.
DISCRIMINATE = 0.10
N_SLOTS = 5
#: Columns of the pill's rounded left cap left out of the step fit and
#: counted as fill (0.2.0 split a full pill between its cap and its body
#: and read 3.3 px on 845 samples). A fill ending inside the cap reads 0.
CAP_PX = 3
#: Mean brightest channel of a one-level profile above which it is full.
FULL_MAX_CHANNEL = 240.0
#: The player's agent per session and where it was read. 4f207c0c4e39 and
#: a06f04a0059f: the majority of the stored `tray_kit_identity` claims (Iso
#: 36, Phoenix 40). 59c70f1ef720 has no tray-kit or self identity stored and
#: its self-icon witness misreads (Gekko); its Sova was read by eye from the
#: cached roster at 1283.0 s: all five alive, hp 4 on the bottom HUD, and one
#: near-empty red pill, under Sova.
SELF_AGENT = {"4f207c0c4e39": "Iso", "59c70f1ef720": "Sova", "a06f04a0059f": "Phoenix"}


def _below_normal() -> None:
    if sys.platform == "win32":
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)


def alive_spans(store: Store, sid: str, date: str) -> list[tuple[float, float]]:
    """(start, stop) per round: start to the player's first death or the close."""
    r = store.read_rounds(sid, date).to_pydict()
    deaths = sorted(e["t_ms"] for e in store.read_events("death", sid)
                    if e.get("kind") == "death_verdict" and not e.get("is_revive")
                    and (e.get("metadata") or {}).get("is_player_death"))
    out = []
    for a, close in zip(r["t_start_ms"], r["t_close_ms"]):
        d = [t for t in deaths if a <= t < close]
        out.append((a, (d[0] - DEATH_GUARD_MS) if d else close))
    return out


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
    ends = []
    for i in range(0, len(edges) - 1, 2):
        l, r = edges[i], edges[i + 1]
        # sub-pixel crossings by linear interpolation of the smooth profile
        xl = l + (half - prof[l]) / (prof[l + 1] - prof[l])
        xr = r + (half - prof[r]) / (prof[r + 1] - prof[r])
        ends.append((float(xl) + 0.5, float(xr) + 0.5))
    return rs, ends


def fill_end(P: np.ndarray) -> np.ndarray:
    """Fill length in px of each profile `P` (n, W, 3), by soft coverage."""
    n, W, _ = P.shape
    c1 = np.concatenate([np.zeros((n, 1, 3)), np.cumsum(P, 1)], 1)
    c2 = np.concatenate([np.zeros((n, 1)), np.cumsum((P ** 2).sum(2), 1)], 1)
    k = np.arange(1, W)                                   # split: k fill columns
    sl, sr = c1[:, k], c1[:, -1:] - c1[:, k]
    ql, qr = c2[:, k], c2[:, -1:] - c2[:, k]
    sse = (ql - (sl ** 2).sum(2) / k) + (qr - (sr ** 2).sum(2) / (W - k))
    j = sse.argmin(1)
    kb = k[j]
    L = sl[np.arange(n), j] / kb[:, None]
    R = sr[np.arange(n), j] / (W - kb)[:, None]
    sse2 = sse[np.arange(n), j]
    sse1 = c2[:, -1] - (c1[:, -1] ** 2).sum(1) / W
    m = W * 3
    bic1 = m * np.log(np.maximum(sse1, 0) / m + 1e-6) + 3 * np.log(m)
    bic2 = m * np.log(np.maximum(sse2, 0) / m + 1e-6) + 7 * np.log(m)
    d = L - R
    alpha = np.clip(((P - R[:, None]) * d[:, None]).sum(2)
                    / np.maximum((d ** 2).sum(1), 1e-6)[:, None], 0, 1)
    end = alpha.sum(1)
    # One level: a full pill is opaque fill (white, red or teal: a channel
    # near 255); an empty one is half-white over the scene.
    full = P.max(axis=2).mean(axis=1) >= FULL_MAX_CHANNEL
    return np.where(bic2 < bic1, end, np.where(full, float(W), 0.0)), bic2 < bic1


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
    hud = store.read_hud(sid, date)
    ros = store.read_roster(sid, date)
    tm = hud.column("t_ms").to_numpy().astype(float)
    hp = np.array(hud.column("hp").to_pylist(), dtype=float)
    sh = np.array(hud.column("shield").to_pylist(), dtype=float)
    ally, _ = roster_mod.resolve(hud, ros)
    ally = dict(zip(ros.column("t_ms").to_pylist(), ally))
    spans = alive_spans(store, sid, date)
    sa = np.array([a for a, _ in spans]); sz = np.array([z for _, z in spans])
    inside = ((tm[:, None] >= sa) & (tm[:, None] < sz)).any(1)
    n_ally = np.array([ally.get(t) if ally.get(t) is not None else -1 for t in tm])
    keep = inside & (hp >= 1) & (hp <= 100) & (n_ally >= 1)
    idx = np.flatnonzero(keep)

    x0, y0, x1, y1 = rc.stored_rect("hud_roster")
    crops = {}
    for smp in rc.samples(tm[idx].tolist(), rois=["hud_roster"]):
        crops[smp.t_ms] = smp.frame[y0:y1, x0:x1]
    idx = np.array([i for i in idx if tm[i] in crops])
    stack = np.stack([crops[tm[i]] for i in idx]).astype(np.float32)

    full = (hp[idx] == 100) & (sh[idx] == 50) & (n_ally[idx] == N_SLOTS)
    rs, ends = geometry(stack[full].min(axis=3))
    if len(ends) != N_SLOTS:
        return {"session": sid, "refused": f"found {len(ends)} pill ends, not 5", "ends": ends}
    band = stack[:, rs].mean(axis=1)                        # (n, w, 3)
    # Each slot's interior, whole pixels inside its fitted ends.
    out = {"session": sid, "date": date, "capture": man["source"].get("path"),
           "band_rows": [rs.start + y0, rs.stop - 1 + y0],
           "pill_ends_px": [[round(a, 2), round(b, 2)] for a, b in ends], "slots": {}}
    lineup = json.loads((STORE / "lineups" / f"{sid}.json").read_text(encoding="utf-8"))
    slot = next(r["slot"] for r in lineup["sides"]["ally"]
                if (r["agent"] or r["best_guess"]) == SELF_AGENT[sid])
    n = n_ally[idx]
    if slot == 0:
        self_slot = N_SLOTS - n
    elif slot == N_SLOTS - 1:
        self_slot = np.full_like(n, N_SLOTS - 1)
    else:
        self_slot = np.where(n == N_SLOTS, slot, -1)
    out["self_agent"], out["self_lineup_slot"] = SELF_AGENT[sid], slot
    for s, (a, b) in enumerate(ends):
        lo, hi = int(np.ceil(a)), int(np.floor(b))
        P = band[:, lo + CAP_PX:hi]
        end, stepped = fill_end(P)
        frac_len = np.where(end > 0, (lo - a) + CAP_PX + end, 0.0)   # from the fitted left end
        width = b - a
        occ = s >= N_SLOTS - n                              # occupied slots
        sel = occ & (sh[idx] == sh[idx])
        h1 = hp[idx] / 100.0
        h2 = (hp[idx] + np.nan_to_num(sh[idx])) / 150.0
        disc = sel & (np.abs(h1 - h2) >= DISCRIMINATE)
        row = {"width_px": round(width, 2),
               "self": {}, "occupied_any": {}}
        for name, m in (("self", sel & (self_slot == s)), ("occupied_any", sel)):
            for sub, mm in (("all", m), ("discriminating", m & disc)):
                if mm.sum() < 5:
                    continue
                row[name][sub] = {"health_only": fit(h1[mm], frac_len[mm]),
                                  "health_plus_shield": fit(h2[mm], frac_len[mm])}
        noshield = occ & (self_slot == s) & ~(sh[idx] == sh[idx])
        if noshield.sum() >= 5:
            row["self"]["shield_null"] = {"health_only": fit(h1[noshield], frac_len[noshield])}
        out["slots"][s] = row
        if s == 0:
            out["samples_self"] = []
        sm = (self_slot == s) & occ
        out.setdefault("samples_self", []).extend(
            {"t_ms": float(tm[i]), "slot": s, "hp": float(hp[i]),
             "shield": None if sh[i] != sh[i] else float(sh[i]),
             "fill_px": round(float(f), 2), "fill_frac": round(float(f / width), 4),
             "stepped": bool(st)}
            for i, f, st in zip(idx[sm], frac_len[sm], stepped[sm]))
    return out


def pooled(results: list[dict]) -> dict:
    """Self-slot samples of every session, fill as a fraction of the pill."""
    rows = [r for res in results for r in res.get("samples_self", [])
            if r["shield"] is not None]
    f = np.array([r["fill_frac"] for r in rows])
    h1 = np.array([r["hp"] / 100 for r in rows])
    h2 = np.array([(r["hp"] + r["shield"]) / 150 for r in rows])
    disc = np.abs(h1 - h2) >= DISCRIMINATE
    hp = h1 * 100
    sh = np.array([r["shield"] for r in rows])
    out = {"n_with_shield_read": len(rows)}
    # Robust throughout: about 5% of samples are slot or span errors (a wrong
    # roster count, a death the guard missed), which a least-squares fit
    # lets dominate. Each hypothesis gets one scale, the median of fill/pred
    # (the right cap's coverage reads a full pill short of its fitted ends).
    for sub, m in (("all", np.ones_like(f, bool)), ("discriminating", disc),
                   ("damaged_discriminating", disc & (hp < 100))):
        row = {"n": int(m.sum())}
        for name, pred in (("health_only", h1), ("health_plus_shield", h2)):
            ok = m & (pred > 0.2)
            scale = float(np.median(f[ok] / pred[ok]))
            res = np.abs(f[m] - scale * pred[m])
            row[name] = {"scale": round(scale, 4),
                         "median_abs_err_frac": round(float(np.median(res)), 4),
                         "within_0.05": round(float(np.mean(res <= 0.05)), 4)}
        out[sub] = row
    # The cleanest contrast: full health, shield 0 (null), 25 or 50. Health
    # alone predicts one fill; health plus shield predicts 100/150, 125/150
    # and 150/150 of it.
    out["full_health_by_shield"] = {}
    for s in (None, 25.0, 50.0):
        allrows = [r for res in results for r in res.get("samples_self", [])
                   if r["hp"] == 100 and r["shield"] == s]
        v = np.array([r["fill_frac"] for r in allrows])
        if len(v):
            out["full_health_by_shield"]["null" if s is None else str(int(s))] = {
                "n": int(len(v)), "median_fill_frac": round(float(np.median(v)), 4),
                "p10": round(float(np.percentile(v, 10)), 4),
                "p90": round(float(np.percentile(v, 90)), 4)}
    return out


def main() -> None:
    _below_normal()
    store = Store(STORE)
    results = [session(store, sid, d) for sid, d in SESSIONS]
    summary = {"version": VERSION, "pooled_self": pooled(results),
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
                "all_health_only_within_005": p["all"]["health_only"]["within_0.05"],
                "all_health_plus_shield_within_005": p["all"]["health_plus_shield"]["within_0.05"],
                "damaged_disc_n": dd["n"],
                "damaged_health_only_within_005": dd["health_only"]["within_0.05"],
                "damaged_health_plus_shield_scale": dd["health_plus_shield"]["scale"]},
        deps={"version": VERSION, "sessions": [s for s, _ in SESSIONS],
              "roi_cache": "roi-cache-0.1.0"},
        context={"store_dir": f"analysis/{VERSION}"},
        note="top-bar pill fill vs bottom-HUD hp and shield, player's own slot while alive")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
