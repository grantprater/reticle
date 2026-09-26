r"""Where minimap ally icon identity lives, and which descriptor separates agents.

    .\.venv\Scripts\python.exe prototypes\ally_icon_separability.py crops
    .\.venv\Scripts\python.exe prototypes\ally_icon_separability.py look|fisher|descriptors|segments|mined
    .\.venv\Scripts\python.exe prototypes\ally_icon_separability.py inspect --agent Clove --nt 3 --zoom 2 --ncol 4

Purpose. Mined minimap references name some teammates well and others badly
(held out, per icon: Neon 0.97, Clove 0.44, Deadlock 0.16;
`minimap_mined_references.py`). The stored descriptor is `composition`, a
10x3x3 HSV histogram over the disc of 0.75 r less the teal key
(`minimap.ally_icon_descriptors`). This asks where in the icon the agent is
drawn, and which descriptor separates the agents best.

Labels and split. `minimap_identity_calibration.py`: a killfeed ally death
labels the last 2 s of the one segment that alone ends at it; its fixed split
(sorted ids, index mod 3 == 2 held out). References and fits use build
sessions only; accuracy is held-out, candidates the match's teammates.

Crops (`crops`). Per labelled icon, and per icon sharing a frame with a
held-out labelled icon (the joint assignment needs its rivals), a lossless
crop of the minimap from the `roi_cache` around the stored `cx, cy`. No
decode; the analysis cache goes to the calibration work directory.

Alignment. The stored `cx, cy, r` are integers and the widget comes in two
sizes, so each crop is resampled about the fitted centre at a scale set by
the widget width (`W_REF`, `UPS`), bilinear. Whether the portrait turns with
`facing` is measured, not assumed (`fisher`).

Steps. `look` writes a montage (per-agent mean aligned crop, three examples,
4x). `fisher` writes a per-pixel Fisher-ratio map (between-agent over
within-agent variance, per Lab channel) and the share of the stored
composition's mass that falls on low-separability pixels. `descriptors`
scores nearest-reference identity per icon for several descriptors.
`segments` names held-out segments at deaths with the best one, by vote over
the last 2 s and by the per-frame joint assignment. `mined` reruns
`minimap_mined_references.run_joint` with the composition swapped for another
descriptor. `inspect` draws every labelled segment of one agent, captioned
with the descriptor's nearest teammate, to audit the labels by eye.

Predictions and outcome: `ally-icon-separability` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.track import assign  # noqa: E402

import minimap_identity_calibration as mic  # noqa: E402
import minimap_mined_references as mmr  # noqa: E402

RAW = 41            # raw crop side, centred on the rounded icon centre
SIDE = 37           # aligned crop side
OUT = mic.WORK / "separability"


# ---------------------------------------------------------------- crops

def _cache(sid: str):
    man = json.loads((mic.STORE.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    cache, why = RoiCache.load(mic.STORE.root, man, get_profile(man["source_profile"]), "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no minimap cache ({why})")
    return cache


def collect_crops() -> None:
    cal, test, sessions, units = mmr.load_split()
    OUT.mkdir(parents=True, exist_ok=True)
    for sid in cal + test:
        data = sessions[sid]
        want = {k for u in units[sid] for k in u["keys_last"]}
        if sid in test:
            frames = {data["icons"][k]["frame"] for k in want}
            want |= {k for k, i in data["icons"].items() if i["frame"] in frames}
        ev = {e["observation_key"]: e for e in mic.STORE.read_events("ally_icon", sid)
              if e.get("kind") == "icon" and e.get("observation_key") in want}
        cache = _cache(sid)
        x0, y0, x1, y1 = cache.rect_of("minimap")
        t_of = {}
        for f, t in zip(cache.frame_idx, cache.t_ms):
            t_of.setdefault(int(f), float(t))
        by_t = defaultdict(list)
        miss = 0
        for k in want:
            e = ev.get(k)
            t = t_of.get(int(e["frame_idx"])) if e else None
            if t is None:
                miss += 1
                continue
            by_t[t].append(k)
        rows = {}
        h = RAW // 2
        for smp in cache.samples(sorted(by_t), rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT, value=0)
            for k in by_t[smp.t_ms]:
                e = ev[k]
                cx, cy = int(round(e["cx"])), int(round(e["cy"]))
                rows[k] = {"raw": pad[cy:cy + RAW, cx:cx + RAW].copy(),
                           "dx": float(e["cx"]) - cx, "dy": float(e["cy"]) - cy,
                           "r": float(e["r"]), "facing": e.get("facing"),
                           "frame": int(e["frame_idx"]), "w": int(crop.shape[1])}
        (OUT / f"{sid}.pkl").write_bytes(pickle.dumps(rows))
        print(sid, "icons", len(rows), "missing", miss, flush=True)


def load_all():
    cal, test, sessions, units = mmr.load_split()
    crops = {sid: pickle.loads((OUT / f"{sid}.pkl").read_bytes()) for sid in cal + test}
    return cal, test, sessions, units, crops


# ---------------------------------------------------------------- alignment

#: Aligned crops are upsampled so a widget `W_REF` pixels wide maps at `UPS`x.
#: The fitted radius and centre are integers, so the widget width, not `r`,
#: sets the scale.
W_REF, UPS = 331, 2.0


def aligned(row: dict, side: int = SIDE, rot: float = 0.0) -> np.ndarray:
    """The raw crop resampled: fitted centre at the middle pixel, scale
    `UPS * W_REF / w`, turned by `rot` degrees about the centre."""
    c = RAW // 2
    s = UPS * W_REF / row["w"]
    m = cv2.getRotationMatrix2D((c + row["dx"], c + row["dy"]), rot, s)
    m[0, 2] += (side - 1) / 2 - (c + row["dx"])
    m[1, 2] += (side - 1) / 2 - (c + row["dy"])
    return cv2.warpAffine(row["raw"], m, (side, side), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT)


def radius_grid(side: int = SIDE) -> np.ndarray:
    yy, xx = np.mgrid[:side, :side]
    c = (side - 1) / 2
    return np.hypot(xx - c, yy - c)


def labelled(sids, sessions, units, crops):
    """(sid, key, victim, unit id, weight) per labelled icon with a crop; a
    segment weighs one in total."""
    out = []
    for sid in sids:
        for j, u in enumerate(units[sid]):
            ks = [k for k in u["keys_last"] if k in crops[sid]]
            for k in ks:
                out.append((sid, k, u["victim"], (sid, j), 1.0 / len(ks)))
    return out


def lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float32)


def key_mask(img: np.ndarray) -> np.ndarray:
    """The reader's own teal and self keys (`minimap.ally_mask | self_mask`)."""
    from reticle.minimap import ally_mask, self_mask
    return ally_mask(img) | self_mask(img)


# ---------------------------------------------------------------- look

LOOK = ("Deadlock", "Clove", "Reyna", "Miks", "Neon", "Breach", "Phoenix", "Sova",
        "Jett", "Sage")


def run_look(cal, test, sessions, units, crops, path: Path) -> dict:
    rows = labelled(cal + test, sessions, units, crops)
    by = defaultdict(list)
    for sid, k, v, _, _ in rows:
        by[v].append(aligned(crops[sid][k]).astype(np.float32))
    z, tiles, info = 4, [], {}
    for a in LOOK:
        if a not in by:
            info[a] = 0
            continue
        ims = by[a]
        info[a] = len(ims)
        pick = np.random.default_rng(0).choice(len(ims), size=min(3, len(ims)), replace=False)
        row = [np.mean(ims, axis=0)] + [ims[i] for i in pick]
        row = [cv2.resize(np.clip(t, 0, 255).astype(np.uint8), None, fx=z, fy=z,
                          interpolation=cv2.INTER_NEAREST) for t in row]
        while len(row) < 4:
            row.append(np.zeros_like(row[0]))
        strip = np.hstack([np.pad(t, ((2, 2), (2, 2), (0, 0))) for t in row])
        title = np.zeros((16, strip.shape[1], 3), np.uint8)
        cv2.putText(title, f"{a} n={len(ims)}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (255, 255, 255), 1)
        tiles.append(np.vstack([title, strip]))
    half = (len(tiles) + 1) // 2
    cols = [np.vstack(tiles[:half]), np.vstack(tiles[half:])]
    h = max(c.shape[0] for c in cols)
    cols = [np.pad(c, ((0, h - c.shape[0]), (0, 8), (0, 0))) for c in cols]
    cv2.imwrite(str(path), np.hstack(cols))
    return info


# ---------------------------------------------------------------- fisher

def fisher(X: np.ndarray, y: list, w: np.ndarray) -> np.ndarray:
    """Per feature: variance of the agent means (agents equal) over the mean
    within-agent variance (icons weighted `w`)."""
    ya = np.array(y)
    means, wv = [], []
    for a in sorted(set(y)):
        m = ya == a
        ww = w[m] / w[m].sum()
        mu = (X[m] * ww[:, None]).sum(0)
        means.append(mu)
        wv.append((((X[m] - mu) ** 2) * ww[:, None]).sum(0))
    return np.var(np.array(means), axis=0) / (np.mean(wv, axis=0) + 1e-6)


def lab_matrix(rows, crops, rot_by_facing=False):
    X, keep = [], []
    for i, (sid, k, *_r) in enumerate(rows):
        c = crops[sid][k]
        if rot_by_facing and c["facing"] is None:
            continue
        X.append(lab(aligned(c, rot=c["facing"] if rot_by_facing else 0.0)).reshape(-1))
        keep.append(i)
    return np.array(X), keep


def median_r(rows, crops) -> float:
    return float(np.median([crops[s][k]["r"] * UPS * W_REF / crops[s][k]["w"]
                            for s, k, *_ in rows]))


def run_fisher(cal, test, sessions, units, crops, path: Path) -> dict:
    rows = labelled(cal, sessions, units, crops)
    y = [r[2] for r in rows]
    w = np.array([r[4] for r in rows])
    X, _ = lab_matrix(rows, crops)
    F = fisher(X, y, w).reshape(SIDE, SIDE, 3)
    Xr, kr = lab_matrix(rows, crops, rot_by_facing=True)
    Fr = fisher(Xr, [y[i] for i in kr], w[kr]).reshape(SIDE, SIDE, 3)
    Fs = F.sum(2)
    rad = radius_grid()
    r_px = median_r(rows, crops)
    keyed = np.mean([key_mask(aligned(crops[s][k])) for s, k, *_ in rows[::5]], axis=0)
    disc = rad <= 0.75 * r_px
    comp_w = disc * (1 - keyed)
    zones = {"<0.5r": rad <= 0.5 * r_px, "0.5-0.75r": (rad > 0.5 * r_px) & disc,
             "0.75-1.25r": (rad > 0.75 * r_px) & (rad <= 1.25 * r_px),
             ">1.25r": rad > 1.25 * r_px}
    thr = np.quantile(Fs, 0.75)
    out = {"r_aligned_px": round(r_px, 2), "icons": len(rows), "rotated_icons": len(kr),
           "zone_mean_F": {z: round(float(Fs[m].mean()), 3) for z, m in zones.items()},
           "zone_mean_F_rotated": {z: round(float(Fr.sum(2)[m].mean()), 3)
                                   for z, m in zones.items()},
           "composition_mass_by_zone": {z: round(float(comp_w[m].sum() / comp_w.sum()), 3)
                                        for z, m in zones.items()},
           "key_share_in_disc": round(float(keyed[disc].mean()), 3),
           "F_interior_by_Lab_channel": [round(float(F[..., c][disc].mean()), 3)
                                         for c in range(3)],
           "composition_mass_on_F_below_q75": round(float(comp_w[Fs < thr].sum()
                                                          / comp_w.sum()), 3)}
    z, ims = 6, []
    for pnl in (F[..., 0], F[..., 1], F[..., 2], Fs, Fr.sum(2)):
        v = (pnl / (pnl.max() + 1e-9) * 255).astype(np.uint8)
        im = cv2.applyColorMap(cv2.resize(v, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST),
                               cv2.COLORMAP_INFERNO)
        c = int((SIDE * z) / 2)
        for rr in (0.75 * r_px, r_px):
            cv2.circle(im, (c, c), int(rr * z), (255, 255, 255), 1)
        ims.append(np.pad(im, ((0, 0), (0, 4), (0, 0))))
    cv2.imwrite(str(path), np.hstack(ims))
    np.save(OUT / "fisher_sum.npy", Fs)
    return out




# ---------------------------------------------------------------- descriptors

def hs_hist(img: np.ndarray, mask: np.ndarray, hb: int = 18, sb: int = 4) -> np.ndarray:
    """Hue x saturation histogram, each pixel weighted by its saturation, so
    grey pixels, whose hue is noise, carry little mass; value is ignored."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = (hsv[..., 0].astype(int) * hb // 180).clip(0, hb - 1)[mask]
    s = hsv[..., 1][mask].astype(np.float32)
    idx = h * sb + (s.astype(int) * sb // 256).clip(0, sb - 1)
    v = np.bincount(idx, weights=s / 255.0 + 1e-3, minlength=hb * sb).astype(np.float32)
    return v / max(v.sum(), 1e-6)


class Describer:
    """Descriptors of one aligned icon. Masks are fixed in aligned coordinates:
    `disc` is the geometric interior (0.75 r, the reader's), `fisher` the
    build-set pixels above the Fisher-ratio quantile `FISHER_Q`, `patch` the
    disc of radius `PATCH_FRAC * r` for aligned-pixel features."""

    FISHER_Q = 0.75
    PATCH_FRAC = 1.0

    def __init__(self, r_px: float, fisher_sum: np.ndarray):
        from reticle import appearance
        self.hsv_composition = appearance.hsv_composition
        rad = radius_grid()
        self.disc = rad <= 0.75 * r_px
        self.fmask = fisher_sum >= np.quantile(fisher_sum, self.FISHER_Q)
        self.patch = (rad <= self.PATCH_FRAC * r_px)[::2, ::2]

    def __call__(self, row: dict) -> dict:
        img = aligned(row)
        keyed = key_mask(img)
        small = cv2.resize(img, (SIDE // 2 + 1, SIDE // 2 + 1), interpolation=cv2.INTER_AREA)
        L = lab(small)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
        m = self.patch
        out = {"comp_geom": self.hsv_composition(img, self.disc & ~keyed),
               "comp_fisher": self.hsv_composition(img, self.fmask & ~keyed),
               "hs_sat": hs_hist(img, self.disc & ~keyed),
               "lab_patch": L[m].ravel(),
               "grad_patch": np.concatenate([gx[m], gy[m]]),
               "chroma_patch": L[m][:, 1:].ravel()}
        out["lab_grad"] = np.concatenate([out["lab_patch"], out["grad_patch"] / 4.0])
        return out


HIST = {"comp_stored", "comp_geom", "comp_fisher", "hs_sat"}


class LDA:
    """Fisher LDA with a shrunk pooled within-class covariance; scores are
    Gaussian log likelihoods in the discriminant space less a pooled
    background, so an agent without a reference scores 0 (as `mic.Features`
    leaves it out)."""

    def __init__(self, X, y, w, shrink=0.2, k=None):
        agents = sorted(set(y))
        ya = np.array(y)
        self.mu = X.mean(0)
        Xc = X - self.mu
        d = X.shape[1]
        means, Sw = {}, np.zeros((d, d))
        for a in agents:
            mm = ya == a
            ww = w[mm] / w[mm].sum()
            mu = (Xc[mm] * ww[:, None]).sum(0)
            means[a] = mu
            D = (Xc[mm] - mu) * np.sqrt(ww)[:, None]
            Sw += D.T @ D / len(agents)
        Sw = (1 - shrink) * Sw + shrink * np.trace(Sw) / d * np.eye(d)
        ev, V = np.linalg.eigh(Sw)
        Wh = V / np.sqrt(np.maximum(ev, 1e-9))
        M = np.array([means[a] for a in agents]) @ Wh
        M0 = M - M.mean(0)
        _, _, Vt = np.linalg.svd(M0, full_matrices=False)
        k = k or len(agents) - 1
        self.P = Wh @ Vt[:k].T
        self.means = {a: means[a] @ self.P for a in agents}
        C = np.cov(np.array(list(self.means.values())).T) + np.eye(k)
        self.bg_mu = np.mean(list(self.means.values()), axis=0)
        self.bg_inv = np.linalg.inv(C)
        self.bg_logdet = np.linalg.slogdet(C)[1]

    def project(self, X):
        return (np.atleast_2d(X) - self.mu) @ self.P

    def llr(self, z, cands) -> dict:
        dz = z - self.bg_mu
        bg = -0.5 * (dz @ self.bg_inv @ dz) - 0.5 * self.bg_logdet
        return {a: (-0.5 * float(((z - self.means[a]) ** 2).sum()) - bg) if a in self.means
                else 0.0 for a in cands}


def unit_refs(feats, rows) -> dict:
    """Per agent, the mean over segments of each segment's mean descriptor."""
    per_unit = defaultdict(list)
    agent_of = {}
    for sid, k, v, uid, _ in rows:
        per_unit[uid].append(feats[(sid, k)])
        agent_of[uid] = v
    acc = defaultdict(list)
    for uid, fs in per_unit.items():
        acc[agent_of[uid]].append(np.mean(fs, axis=0))
    return {a: np.mean(v, axis=0) for a, v in acc.items()}


def scorer(name, feats, rows, shrink=0.2):
    """A function (sid, key, cands) -> {agent: score}, fitted on `rows`."""
    if name.endswith("_lda"):
        base = name[:-4]
        X = np.array([feats[base][(s, k)] for s, k, *_ in rows])
        lda = LDA(X, [r[2] for r in rows], np.array([r[4] for r in rows]), shrink)
        return lambda s, k, c: lda.llr(lda.project(feats[base][(s, k)])[0], c)
    refs = unit_refs(feats[name], rows)
    if name in HIST:
        return lambda s, k, c: {a: float(np.minimum(feats[name][(s, k)], refs[a]).sum())
                                for a in c if a in refs}
    return lambda s, k, c: {a: -float(((feats[name][(s, k)] - refs[a]) ** 2).sum())
                            for a in c if a in refs}


def all_features(sessions, crops, r_px, Fs) -> dict:
    desc = Describer(r_px, Fs)
    feats = defaultdict(dict)
    for sid, rows in crops.items():
        data = sessions[sid]
        for k, row in rows.items():
            for n, v in desc(row).items():
                feats[n][(sid, k)] = np.asarray(v, np.float32)
            feats["comp_stored"][(sid, k)] = data["comp"][data["icons"][k]["row"]]
    return feats


def score_icons(fn, rows, sessions, refs_agents) -> dict:
    c, by = Counter(), defaultdict(Counter)
    for sid, k, v, _, _ in rows:
        if v not in refs_agents:
            c["uncovered"] += 1
            continue
        sc = fn(sid, k, sessions[sid]["candidates"])
        ok = bool(sc) and max(sc, key=sc.get) == v
        c["n"] += 1
        c["ok"] += ok
        by[v]["n"] += 1
        by[v]["ok"] += ok
    return {"icon": round(c["ok"] / max(1, c["n"]), 3), "n": c["n"],
            "uncovered": c["uncovered"],
            "by_agent": {a: f"{b['ok']}/{b['n']}" for a, b in sorted(by.items())}}


NAMES = ("comp_stored", "comp_geom", "comp_fisher", "hs_sat", "lab_patch", "chroma_patch",
         "comp_stored_lda", "lab_patch_lda", "chroma_patch_lda", "grad_patch_lda",
         "lab_grad_lda", "hs_sat_lda")


def prepare(cal, test, sessions, units, crops):
    build = labelled(cal, sessions, units, crops)
    held = labelled(test, sessions, units, crops)
    Fs = np.load(OUT / "fisher_sum.npy")
    feats = all_features(sessions, crops, median_r(build, crops), Fs)
    return build, held, feats


def run_descriptors(cal, test, sessions, units, crops) -> dict:
    build, held, feats = prepare(cal, test, sessions, units, crops)
    covered = {r[2] for r in build}
    # instrument: the recomputed geometric composition against the stored one
    agree = [float(np.minimum(feats["comp_geom"][(s, k)], feats["comp_stored"][(s, k)]).sum())
             for s, k, *_ in held if feats["comp_geom"][(s, k)].size]
    out = {"instrument_comp_geom_vs_stored_median_intersection": round(float(np.median(agree)), 3)}
    for n in NAMES:
        out[n] = score_icons(scorer(n, feats, build), held, sessions, covered)
        print(n, out[n]["icon"], {a: out[n]["by_agent"].get(a) for a in
                                  ("Deadlock", "Clove", "Reyna", "Miks", "Neon")}, flush=True)
    # LDA shrinkage by leave-one-build-session-out, for the best patch LDA
    loso = {}
    for lam in (0.05, 0.2, 0.5, 0.8):
        ok = n_ = 0
        for sid in cal:
            fit = [r for r in build if r[0] != sid]
            got = score_icons(scorer("lab_grad_lda", feats, fit, lam),
                              [r for r in build if r[0] == sid], sessions, {r[2] for r in fit})
            ok += got["icon"] * got["n"]
            n_ += got["n"]
        loso[lam] = round(ok / max(1, n_), 3)
    out["lab_grad_lda_loso_shrink"] = loso
    return out


STEPS = {"look": run_look, "fisher": run_fisher}


# ---------------------------------------------------------------- segments

def softmax(sc: dict, temp: float) -> dict:
    m = max(sc.values())
    e = {a: math.exp((v - m) / temp) for a, v in sc.items()}
    z = sum(e.values())
    return {a: v / z for a, v in e.items()}


def fit_temp(fn_for, cal, build, sessions) -> float:
    """One per-icon temperature by leave-one-build-session-out log loss."""
    pairs = []
    for sid in cal:
        fit = [r for r in build if r[0] != sid]
        fn = fn_for(fit)
        refs = {r[2] for r in fit}
        for s, k, v, *_ in (r for r in build if r[0] == sid):
            if v in refs:
                pairs.append((fn(s, k, sessions[s]["candidates"]), v))
    temps = np.exp(np.linspace(np.log(0.05), np.log(100), 60))
    loss = [-np.mean([math.log(max(softmax(sc, t)[v], 1e-12)) for sc, v in pairs])
            for t in temps]
    return float(temps[int(np.argmin(loss))])


def run_segments(cal, test, sessions, units, crops, name="comp_fisher") -> dict:
    build, held, feats = prepare(cal, test, sessions, units, crops)
    out = {}
    for nm in (name, "comp_stored"):
        fn_for = (lambda rows, nm=nm: scorer(nm, feats, rows))
        temp = fit_temp(fn_for, cal, build, sessions)
        fn = fn_for(build)
        post, raw = {}, {}
        frames = defaultdict(list)
        for sid in test:
            for k, row in crops[sid].items():
                c = sessions[sid]["candidates"]
                sc = fn(sid, k, c)
                sc = {a: sc.get(a, 0.0 if nm.endswith("_lda") else min(sc.values(), default=0.0))
                      for a in c}
                raw[(sid, k)] = sc
                post[(sid, k)] = softmax(sc, temp)
                frames[(sid, row["frame"])].append(k)
        name_of = {}
        for (sid, _f), keys in frames.items():
            c = sessions[sid]["candidates"]
            cost = [[-math.log(max(post[(sid, k)][a], 1e-12)) for a in c] for k in keys]
            for k, col in zip(keys, assign(cost)):
                name_of[(sid, k)] = c[col] if col >= 0 else None
        cnt, by = Counter(), defaultdict(Counter)
        for sid in test:
            for u in units[sid]:
                ks = [k for k in u["keys_last"] if (sid, k) in post]
                if not ks:
                    continue
                tot = Counter()
                for k in ks:
                    tot.update({a: math.log(max(p, 1e-12)) for a, p in post[(sid, k)].items()})
                votes = Counter(name_of[(sid, k)] for k in ks if name_of[(sid, k)])
                best = max(votes.values()) if votes else 0
                tied = [a for a, v in votes.items() if v == best]
                joint = max(tied, key=lambda a: tot[a]) if tied else None
                cnt["segments"] += 1
                cnt["vote_ok"] += max(tot, key=tot.get) == u["victim"]
                cnt["joint_ok"] += joint == u["victim"]
                cnt["icons"] += len(ks)
                cnt["joint_icon_ok"] += sum(name_of[(sid, k)] == u["victim"] for k in ks)
                by[u["victim"]]["n"] += 1
                by[u["victim"]]["joint"] += joint == u["victim"]
        out[nm] = {"temp": round(temp, 3),
                   "segment_sum_last2s": f"{cnt['vote_ok']}/{cnt['segments']}",
                   "segment_joint_last2s": f"{cnt['joint_ok']}/{cnt['segments']}",
                   "icon_joint": round(cnt["joint_icon_ok"] / max(1, cnt["icons"]), 3),
                   "joint_by_agent": {a: f"{b['joint']}/{b['n']}" for a, b in sorted(by.items())}}
        print(nm, {k: v for k, v in out[nm].items() if k != "joint_by_agent"}, flush=True)
    return out


STEPS.update({"descriptors": run_descriptors, "segments": run_segments})



# ---------------------------------------------------------------- inspect

def run_inspect(cal, test, sessions, units, crops, agent="Deadlock",
                name="comp_fisher", nt=6, zoom=3, ncol=2) -> dict:
    """One row per labelled segment of `agent` (build, then held out): the
    last `nt` of its last-2-s icons at `zoom`x in `ncol` columns, each captioned with `name`'s nearest
    teammate; written to `inspect_<agent>.png`."""
    build, held, feats = prepare(cal, test, sessions, units, crops)
    fn = scorer(name, feats, build)
    rows_out, info = [], []
    for part, sids in (("B", cal), ("H", test)):
        for sid in sids:
            for u in units[sid]:
                if u["victim"] != agent:
                    continue
                ks = [k for k in u["keys_last"] if k in crops[sid]][-nt:]
                tiles, got = [], []
                for k in ks:
                    sc = fn(sid, k, sessions[sid]["candidates"])
                    top = max(sc, key=sc.get) if sc else "-"
                    got.append(top)
                    t = cv2.resize(aligned(crops[sid][k]), None, fx=zoom, fy=zoom,
                                   interpolation=cv2.INTER_NEAREST)
                    cv2.putText(t, top[:5], (1, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                                (255, 255, 255), 1)
                    tiles.append(np.pad(t, ((1, 1), (1, 1), (0, 0))))
                while len(tiles) < nt:
                    tiles.append(np.zeros_like(tiles[0]))
                strip = np.hstack(tiles)
                cap = np.zeros((12, strip.shape[1], 3), np.uint8)
                cv2.putText(cap, f"{part} {sid[:6]} {u['segment'][-10:]} base={u['base']}",
                            (1, 9), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
                rows_out.append(np.vstack([cap, strip]))
                info.append((part, sid, u["segment"], u["base"], Counter(got).most_common(2)))
    per = -(-len(rows_out) // ncol)
    cols = [np.vstack(rows_out[i:i + per]) for i in range(0, len(rows_out), per)]
    h = max(c.shape[0] for c in cols)
    cols = [np.pad(c, ((0, h - c.shape[0]), (0, 6), (0, 0))) for c in cols]
    cv2.imwrite(str(OUT / f"inspect_{agent}.png"), np.hstack(cols))
    return {"segments": info}


STEPS["inspect"] = run_inspect


def run_mined(cal, test, sessions, units, crops, name="comp_fisher") -> dict:
    """`minimap_mined_references.run_joint` (mined + exemplar LLR tables,
    per-frame joint assignment) with each icon's composition replaced by
    `name`, over the icons that have crops: every labelled icon and every
    rival in a held-out labelled frame. `comp_stored` on the same icons is
    the instrument check against 106/134."""
    build, held, feats = prepare(cal, test, sessions, units, crops)
    out = {}
    for nm in ("comp_stored", name):
        s2 = {}
        for sid, data in sessions.items():
            keys = [k for k in data["icons"] if k in crops[sid]]
            icons = {k: dict(data["icons"][k], row=i) for i, k in enumerate(keys)}
            comp = np.stack([feats[nm][(sid, k)] if feats[nm][(sid, k)].size
                             else data["comp"][data["icons"][k]["row"]] for k in keys])
            s2[sid] = dict(data, icons=icons, comp=comp)
        res = mmr.run_joint(cal, test, s2, units, taus=(0.0,))
        out[nm] = res["0.0"]
    return out


STEPS["mined"] = run_mined


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("crops",) + tuple(STEPS))
    ap.add_argument("--agent", default="Deadlock")
    ap.add_argument("--nt", type=int, default=6)
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--ncol", type=int, default=2)
    a = ap.parse_args()
    if a.step == "crops":
        collect_crops()
    else:
        split = load_all()
        fn = STEPS[a.step]
        res = (fn(*split, OUT / f"{a.step}.png") if a.step in ("look", "fisher")
               else fn(*split, agent=a.agent, nt=a.nt, zoom=a.zoom, ncol=a.ncol)
               if a.step == "inspect" else fn(*split))
        (OUT / f"{a.step}.json").write_text(json.dumps(res, indent=1, default=str),
                                            encoding="utf-8")
        print(json.dumps(res, default=str)[:3000])
