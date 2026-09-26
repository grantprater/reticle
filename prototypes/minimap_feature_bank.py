r"""A bank of hand-defined minimap icon features, selected by what names agents.

    .\.venv\Scripts\python.exe prototypes\minimap_feature_bank.py bank
    .\.venv\Scripts\python.exe prototypes\minimap_feature_bank.py select
    .\.venv\Scripts\python.exe prototypes\minimap_feature_bank.py score
    .\.venv\Scripts\python.exe prototypes\minimap_feature_bank.py montage

Purpose. The player names a minimap ally portrait "morphologically": by the
ratios between its features and by its colour gradients and palette. This
computes many such features per aligned icon, keeps each family separately
addressable, and lets held-out accuracy on automatic labels choose which
families name agents. It then renders references for every agent from the
game's 64 px minimap portrait art, so an agent no other session has shown can
still be named.

Labels. Automatic: a death binding (`minimap_identity_calibration.label_units`)
whose segment ends more than `AUTO_MS` before the killfeed death; its last 2 s
of icons carry the victim, each unit weighing one. The player's 140 answers
(`prototypes/label_death_icons.py`) are the test set only; nothing is fitted
or selected on them.

Features (`bank`), on the aligned crop (`ally_icon_separability.aligned`,
2x upsampled; `x2`) and its 2x-downsampled copy (`x1`, about one native
pixel), with the reader's teal/self key pixels excluded. Regions: `disc`
(0.75 r), `upper` (hair), `lower` (face), `centre` (0.4 r), `left`, `right`.
Families: Lab and HSV statistics per region; a k-means Lab palette of the
disc and of each half; region ratios and differences; mean colour
derivatives per channel; vertical and horizontal Lab profiles; HOG and
rotation-invariant uniform LBP at both scales; Hu moments of the Otsu bright
and dark structure; 3x3 and 4x4 Lab grids and a 3x3 HSV grid; the 90-bin
composition over the disc; the stored reader composition; the disc's Lab
pixels at `x1`.

Scoring. Per family, a diagonal Gaussian per agent with the within-agent
variance pooled over the training sessions; a family's score is its mean
per-feature log likelihood, so families weigh equally; a set's score is the
sum. Candidates are the session's four teammates. `elim` scores a candidate
without a reference under the mean of the references with the between-agent
variance added (`minimap_identity_clean.Contrast`).

Selection (`select`). Leave one session out over the automatic labels:
Fisher ratios per feature (all agents, and per confused pair), single-family
held-out accuracy, and greedy forward selection of families by held-out
nearest-reference accuracy.

Rendered references (`score`). The minimap portrait art is shrunk to native
size, blurred and upsampled as the real crops are; scale, blur and vertical
offset are fitted per fold to the mean real icon of each agent with a
reference, and an affine Lab map carries art colour to game colour. A
rendered reference's variance adds the art-to-game residual measured on the
covered agents. Test icons are scored with mined references, rendered ones,
both, and elimination.

Caches go to `mic.WORK / "feature_bank"`; nothing is written to the store.
No decode. Predictions and outcome: `minimap-feature-bank` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.appearance import hsv_composition  # noqa: E402

import ally_icon_separability as asep  # noqa: E402
import minimap_identity_calibration as mic  # noqa: E402
import minimap_identity_clean as mcl  # noqa: E402

WORK = mic.WORK / "feature_bank"
AUTO_MS = 200.0
ART = mic.STORE.root / "reference" / "assets" / "agents"
SIDE1 = asep.SIDE // 2 + 1
PAIRS = (("Deadlock", "Miks"), ("Deadlock", "Reyna"), ("Miks", "Reyna"), ("Clove", "Reyna"))


# ---------------------------------------------------------------- regions and families

def regions(side: int, R: float) -> dict:
    rad = asep.radius_grid(side)
    yy, xx = np.mgrid[:side, :side]
    c = (side - 1) / 2
    disc = rad <= 0.75 * R
    return {"disc": disc, "upper": disc & (yy < c - 0.5), "lower": disc & (yy > c + 0.5),
            "centre": rad <= 0.4 * R, "left": disc & (xx < c - 0.5),
            "right": disc & (xx > c + 0.5), "c": c, "R": R}


def _m(mask, keyed):
    m = mask & ~keyed
    return m if m.sum() >= 4 else mask


def lab_stats(L, m):
    v = L[m]
    return np.r_[v.mean(0), v.std(0), np.percentile(v[:, 0], [10, 90])]


def hsv_stats(H, m):
    h = H[m]
    ang = h[:, 0] * np.pi / 90.0
    s, v = h[:, 1] / 255.0, h[:, 2] / 255.0
    w = s + 1e-3
    return np.r_[(w * np.cos(ang)).sum() / w.sum(), (w * np.sin(ang)).sum() / w.sum(),
                 s.mean(), s.std(), v.mean(), v.std()]


def palette(L, m, k):
    px = L[m].astype(np.float32)
    if len(px) < k:
        px = np.repeat(px, k, axis=0)
    cv2.setRNGSeed(0)
    _, lab_, cen = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                                            20, 0.5), 2, cv2.KMEANS_PP_CENTERS)
    w = np.bincount(lab_.ravel(), minlength=k) / len(px)
    o = np.argsort(cen[:, 0])
    return np.r_[cen[o].ravel(), w[o]]


def grads(L, m):
    out = []
    for ch in range(3):
        gx = cv2.Sobel(L[..., ch], cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(L[..., ch], cv2.CV_32F, 0, 1)
        out += [gx[m].mean(), gy[m].mean(), np.abs(gx[m]).mean(), np.abs(gy[m]).mean()]
    return np.array(out)


def profile(L, rg, m, axis, n=6):
    c, R = rg["c"], rg["R"]
    yy, xx = np.mgrid[:L.shape[0], :L.shape[1]]
    t = (yy if axis == 0 else xx) - (c - 0.75 * R)
    band = np.clip((t / (1.5 * R) * n).astype(int), 0, n - 1)
    base = L[m].mean(0)
    return np.concatenate([L[m & (band == b)].mean(0) if (m & (band == b)).any() else base
                           for b in range(n)])


def grid(F, rg, m, n):
    c, R = rg["c"], rg["R"]
    yy, xx = np.mgrid[:F.shape[0], :F.shape[1]]
    by = np.clip(((yy - (c - 0.75 * R)) / (1.5 * R) * n).astype(int), 0, n - 1)
    bx = np.clip(((xx - (c - 0.75 * R)) / (1.5 * R) * n).astype(int), 0, n - 1)
    base = F[m].mean(0)
    return np.concatenate([F[m & (by == i) & (bx == j)].mean(0)
                           if (m & (by == i) & (bx == j)).any() else base
                           for i in range(n) for j in range(n)])


def hog(L, rg, m, bins=8):
    g = L[..., 0]
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag, ang = np.hypot(gx, gy), np.arctan2(gy, gx)
    b = ((ang + np.pi) / (2 * np.pi) * bins).astype(int) % bins
    c = rg["c"]
    yy, xx = np.mgrid[:g.shape[0], :g.shape[1]]
    out = []
    for qy in (yy < c, yy >= c):
        for qx in (xx < c, xx >= c):
            mm = m & qy & qx
            out.append(np.bincount(b[mm], weights=mag[mm], minlength=bins))
    v = np.concatenate(out)
    return v / max(np.linalg.norm(v), 1e-6)


_RIU = None


def _riu_table():
    global _RIU
    if _RIU is None:
        t = np.zeros(256, int)
        for code in range(256):
            bits = [(code >> i) & 1 for i in range(8)]
            u = sum(bits[i] != bits[(i + 1) % 8] for i in range(8))
            t[code] = sum(bits) if u <= 2 else 9
        _RIU = t
    return _RIU


def lbp(L, m, rad):
    g = cv2.GaussianBlur(L[..., 0], (0, 0), 0.5 * rad)
    p = np.pad(g, rad, mode="edge")
    h, w = g.shape
    code = np.zeros((h, w), int)
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
    for i, (dy, dx) in enumerate(offs):
        nb = p[rad + dy * rad:rad + dy * rad + h, rad + dx * rad:rad + dx * rad + w]
        code |= (nb >= g + 1.0).astype(int) << i
    v = np.bincount(_riu_table()[code[m]], minlength=10).astype(float)
    return v / max(v.sum(), 1.0)


def hu(L, m):
    v = L[..., 0][m].astype(np.uint8)
    thr, _ = cv2.threshold(v.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out = []
    for mm in (m & (L[..., 0] > thr), m & (L[..., 0] <= thr)):
        h7 = cv2.HuMoments(cv2.moments(mm.astype(np.uint8), binaryImage=True)).ravel()
        out.append(-np.sign(h7) * np.log10(np.abs(h7) + 1e-12))
    return np.r_[np.concatenate(out), (m & (L[..., 0] > thr)).sum() / m.sum(), thr]


def describe(img: np.ndarray, keyed: np.ndarray, R: float) -> dict:
    """Every family for one aligned icon (BGR uint8, `asep.SIDE` square)."""
    rg = regions(img.shape[0], R)
    L = cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float32)
    H = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    ms = {n: _m(rg[n], keyed) for n in ("disc", "upper", "lower", "centre", "left", "right")}
    f = {}
    for n in ("disc", "upper", "lower", "centre"):
        f[f"lab_{n}"] = lab_stats(L, ms[n])
        f[f"hsv_{n}"] = hsv_stats(H, ms[n])
    f["pal_disc"] = palette(L, ms["disc"], 3)
    f["pal_halves"] = np.r_[palette(L, ms["upper"], 2), palette(L, ms["lower"], 2)]
    mean = {n: L[ms[n]].mean(0) for n in ms}
    hs = {n: hsv_stats(H, ms[n]) for n in ("upper", "lower")}
    rim = _m(rg["disc"] & ~rg["centre"], keyed)
    f["ratios"] = np.r_[mean["upper"] - mean["lower"], hs["upper"] - hs["lower"],
                        mean["centre"] - L[rim].mean(0), mean["left"] - mean["right"],
                        (mean["upper"][0] + 1) / (mean["lower"][0] + 1)]
    f["grad_x2"] = grads(L, ms["disc"])
    f["prof_v"] = profile(L, rg, ms["disc"], 0)
    f["prof_h"] = profile(L, rg, ms["disc"], 1)
    f["hog_x2"] = hog(L, rg, ms["disc"])
    f["lbp_x2"] = lbp(L, ms["disc"], 2)
    f["hu"] = hu(L, ms["disc"])
    f["grid3_lab"] = grid(L, rg, ms["disc"], 3)
    f["grid4_lab"] = grid(L, rg, ms["disc"], 4)
    Hc = np.dstack([np.cos(H[..., 0] * np.pi / 90) * H[..., 1] / 255,
                    np.sin(H[..., 0] * np.pi / 90) * H[..., 1] / 255,
                    H[..., 1] / 255, H[..., 2] / 255])
    f["grid3_hsv"] = grid(Hc, rg, ms["disc"], 3)
    f["comp"] = hsv_composition(img, ms["disc"])
    # native scale
    s1 = cv2.resize(img, (SIDE1, SIDE1), interpolation=cv2.INTER_AREA)
    k1 = cv2.resize(keyed.astype(np.uint8) * 255, (SIDE1, SIDE1),
                    interpolation=cv2.INTER_AREA) > 64
    rg1 = regions(SIDE1, R * SIDE1 / img.shape[0])
    L1 = cv2.cvtColor(s1, cv2.COLOR_BGR2Lab).astype(np.float32)
    d1 = _m(rg1["disc"], k1)
    f["grad_x1"] = grads(L1, d1)
    f["hog_x1"] = hog(L1, rg1, d1)
    f["lbp_x1"] = lbp(L1, d1, 1)
    f["pixels"] = np.where(rg1["disc"][..., None], L1, 0.0)[rg1["disc"]].ravel()
    return {k: np.asarray(v, np.float32) for k, v in f.items()}


# ---------------------------------------------------------------- data

def auto_units(sids, sessions, units) -> dict:
    """Bindings whose segment ends more than `AUTO_MS` before the death."""
    out = {}
    for s in sids:
        d = sessions[s]
        td = {x["death_id"]: x["t"] for x in d["deaths"]}
        out[s] = [u for u in units[s]
                  if d["obs"][u["segment"]][-1][0] - td[u["death_id"]] < -AUTO_MS]
    return out


def run_bank() -> None:
    sids, sessions, units, labs = mcl.clean_data()
    feats = mcl.IconFeatures(sids, sessions)
    keys = sorted(feats.img)
    R = asep.median_r([(s, k) for s, k in keys], feats.crops)
    rows = [describe(feats.img[sk], feats.keyed[sk], R) for sk in keys]
    fams = {n: np.stack([r[n] for r in rows]) for n in rows[0]}
    fams["comp_stored"] = np.stack([
        feats.comp[sk] if feats.comp[sk] is not None else np.full(90, np.nan, np.float32)
        for sk in keys]).astype(np.float32)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "bank.pkl").write_bytes(pickle.dumps({
        "keys": keys, "R": R, "fams": fams,
        "img": {sk: feats.img[sk] for sk in keys}}))
    print("icons", len(keys), "R", round(R, 2), {n: v.shape[1] for n, v in fams.items()})


class Bank:
    """The cached bank, automatic rows, tests and per-family fold scores."""

    def __init__(self):
        b = pickle.loads((WORK / "bank.pkl").read_bytes())
        self.keys, self.R, self.fams, self.img = b["keys"], b["R"], b["fams"], b["img"]
        self.idx = {sk: i for i, sk in enumerate(self.keys)}
        self.sids, self.sessions, units, labs = mcl.clean_data()
        self.units = units
        self.auto = auto_units(self.sids, self.sessions, units)
        self.agents = sorted({u["victim"] for us in units.values() for u in us}
                             | {p.stem[:-len("_minimap_portrait")]
                                for p in ART.glob("*_minimap_portrait.png")})
        self.aix = {a: i for i, a in enumerate(self.agents)}
        rows = []                          # (row index, sid, agent idx, unit id, weight)
        for s in self.sids:
            for j, u in enumerate(self.auto[s]):
                ks = [k for k in u["keys_last"] if (s, k) in self.idx]
                rows += [(self.idx[(s, k)], s, self.aix[u["victim"]], (s, j), 1.0 / len(ks))
                         for k in ks]
        self.rows = rows
        unit_by_key = {mcl.unit_key(s, u): u for s in self.sids for u in units[s]}
        self.tests = [r for r in labs.values() if r["class"] == "agent"
                      and r["key"] in unit_by_key
                      and (r["session_id"], r["observation_key"]) in self.idx]
        bound = {s: {u["victim"] for u in us} for s, us in units.items()}
        self.covered_all = {r["key"]: any(r["answer"] in bound[s] for s in bound
                                          if s != r["session_id"]) for r in self.tests}
        self.n_labels = sum(1 for r in labs.values() if r["class"] == "agent")

    def fit(self, fam: str, train_sids) -> tuple:
        """Agent means (NaN rows where absent), pooled within variance, and
        the between-agent variance of the means."""
        X = self.fams[fam]
        tr = [r for r in self.rows if r[1] in train_sids]
        idx = np.array([r[0] for r in tr])
        y = np.array([r[2] for r in tr])
        w = np.array([r[4] for r in tr])
        Xt = X[idx].astype(np.float64)
        ok = np.isfinite(Xt).all(1)
        Xt, y, w = Xt[ok], y[ok], w[ok]
        M = np.full((len(self.agents), X.shape[1]), np.nan)
        res = np.zeros_like(Xt)
        for a in np.unique(y):
            s = y == a
            M[a] = (Xt[s] * w[s, None]).sum(0) / w[s].sum()
            res[s] = Xt[s] - M[a]
        var = (res ** 2 * w[:, None]).sum(0) / w.sum()
        var = var + 0.01 * Xt.var(0) + 1e-6
        have = np.isfinite(M[:, 0])
        return M, var, M[have].var(0), have

    def fold_scores(self, fam: str, test_sid: str, rendered=None) -> dict:
        """Mean per-feature log likelihood of every icon of `test_sid` under
        each agent's reference from the other sessions: `mined` (NaN where
        absent), `elim` (one column), and `art` when `rendered` holds the
        fold's rendered family vectors and art variance."""
        M, var, bvar, have = self.fit(fam, [s for s in self.sids if s != test_sid])
        ii = np.array([i for i, (s, _) in enumerate(self.keys) if s == test_sid])
        X = self.fams[fam][ii].astype(np.float64)
        X = np.where(np.isfinite(X), X, np.nanmean(M, 0))

        def ll(Mx, v):
            return -0.5 * ((((X[:, None, :] - Mx[None]) ** 2) / v) + np.log(v)).mean(2)

        out = {"rows": ii, "mined": ll(M, var),
               "elim": ll(np.nanmean(M[have], 0)[None], var + bvar)[:, 0]}
        if rendered is not None:
            Ra, gap = rendered[fam]
            out["art"] = ll(Ra, var + gap)
        return out


# ---------------------------------------------------------------- selection

FAMS_REAL_ONLY = {"comp_stored"}


def cands_of(bank, sid):
    return [bank.aix[a] for a in bank.sessions[sid]["candidates"] if a in bank.aix]


def heldout(bank, S: dict, fams, key="mined", only=None) -> tuple:
    """Unit-weighted held-out accuracy of the summed family scores over the
    automatic rows (of sessions `only`) whose victim has a reference."""
    ok = tot = 0.0
    for s in (bank.sids if only is None else only):
        sc = sum(S[f][s][key] for f in fams)
        pos = {r: i for i, r in enumerate(S[fams[0]][s]["rows"])}
        cs = np.array(cands_of(bank, s))
        for r, rs, a, _, w in (x for x in bank.rows if x[1] == s):
            v = sc[pos[r]]
            if not np.isfinite(v[a]):
                continue
            cv = cs[np.isfinite(v[cs])]
            ok += w * (cv[np.argmax(v[cv])] == a)
            tot += w
    return ok / max(tot, 1e-9), tot


def pair_acc(bank, S, fams, A, B):
    a, b = bank.aix[A], bank.aix[B]
    ok = tot = 0.0
    for s in bank.sids:
        sc = sum(S[f][s]["mined"] for f in fams)
        pos = {r: i for i, r in enumerate(S[fams[0]][s]["rows"])}
        for r, _, y, _, w in (x for x in bank.rows if x[1] == s):
            if y not in (a, b) or not (np.isfinite(sc[pos[r], a]) and np.isfinite(sc[pos[r], b])):
                continue
            pick = a if sc[pos[r], a] >= sc[pos[r], b] else b
            ok += w * (pick == y)
            tot += w
    return round(ok / max(tot, 1e-9), 3), round(tot, 1)


def fisher(bank, fam):
    X = bank.fams[fam][[r[0] for r in bank.rows]].astype(np.float64)
    y = np.array([r[2] for r in bank.rows])
    ok = np.isfinite(X).all(1)
    X, y = X[ok], y[ok]
    units = Counter(r[3] for r in bank.rows)
    n_units = Counter()
    for r in bank.rows:
        n_units[r[2]] += 1.0 / units[r[3]]
    keep = [a for a in np.unique(y) if n_units[a] >= 3]
    M = {a: X[y == a].mean(0) for a in keep}
    V = {a: X[y == a].var(0) for a in keep}
    within = np.mean([V[a] for a in keep], 0) + 1e-9
    F = np.array(list(M.values())).var(0) / within
    pf = {}
    for A, B in PAIRS:
        a, b = bank.aix[A], bank.aix[B]
        if a in M and b in M:
            pf[f"{A}/{B}"] = float(np.max((M[a] - M[b]) ** 2 / (V[a] + V[b] + 1e-9)))
    return {"mean": round(float(F.mean()), 3), "max": round(float(F.max()), 3),
            "pair_max": {k: round(v, 2) for k, v in pf.items()}}


def all_scores(bank, fams, rendered_by_fold=None) -> dict:
    return {f: {s: bank.fold_scores(f, s, None if rendered_by_fold is None
                                    else rendered_by_fold[s]) for s in bank.sids}
            for f in fams}


def greedy(bank, S, fams, key="mined", max_steps=10, min_gain=0.002, only=None,
           quiet=False) -> list:
    chosen, best, path = [], 0.0, []
    while len(chosen) < max_steps:
        trial = {f: heldout(bank, S, chosen + [f], key, only)[0] for f in fams if f not in chosen}
        f = max(trial, key=trial.get)
        if trial[f] - best < min_gain:
            break
        chosen.append(f)
        best = trial[f]
        path.append((f, round(best, 4)))
        if not quiet:
            print("  greedy", key, f, round(best, 4), flush=True)
    return path


def run_select() -> dict:
    bank = Bank()
    fams = sorted(bank.fams)
    S = all_scores(bank, fams)
    res = {"auto_units": sum(len(v) for v in bank.auto.values()),
           "all_units": sum(len(v) for v in bank.units.values()),
           "auto_icons": len(bank.rows), "sessions": len(bank.sids),
           "single": {}, "fisher": {}, "pairs": {}}
    for f in fams:
        res["single"][f] = round(heldout(bank, S, [f])[0], 4)
        res["fisher"][f] = fisher(bank, f)
    res["single"] = dict(sorted(res["single"].items(), key=lambda x: -x[1]))
    res["greedy"] = greedy(bank, S, [f for f in fams if f not in FAMS_REAL_ONLY])
    res["greedy_with_stored"] = greedy(bank, S, fams)
    sel = [f for f, _ in res["greedy"]]
    for A, B in PAIRS:
        per = {f: pair_acc(bank, S, [f], A, B) for f in fams}
        top = sorted(per.items(), key=lambda x: -x[1][0])[:5]
        res["pairs"][f"{A}/{B}"] = {"n_units": per["comp"][1], "top": top,
                                    "comp": per["comp"][0], "selected": pair_acc(bank, S, sel, A, B)[0]}
    (WORK / "select.json").write_text(json.dumps(res, indent=1))
    (WORK / "scores_mined.pkl").write_bytes(pickle.dumps(S))
    return res


# ---------------------------------------------------------------- rendered art

def load_art() -> dict:
    out = {}
    for p in sorted(ART.glob("*_minimap_portrait.png")):
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        out[p.stem[:-len("_minimap_portrait")]] = im.astype(np.float32)
    return out


def render(art: np.ndarray, q: float, sigma: float, dy: float, bg: np.ndarray) -> np.ndarray:
    """Art shrunk to native size (`q` aligned px per art px, halved), laid
    over `bg`, blurred by `sigma` native px, upsampled 2x as crops are."""
    n = max(4, int(round(64 * q / 2)))
    a = cv2.resize(art[..., 3] / 255.0, (n, n), interpolation=cv2.INTER_AREA)
    rgb = cv2.resize(art[..., :3] * (art[..., 3:] / 255.0), (n, n), interpolation=cv2.INTER_AREA)
    canvas = np.tile(bg.astype(np.float32), (SIDE1, SIDE1, 1))
    o = (SIDE1 - n) // 2
    lo, hi = max(0, -o), min(n, SIDE1 - o)
    sl = slice(o + lo, o + hi)
    canvas[sl, sl] = rgb[lo:hi, lo:hi] + canvas[sl, sl] * (1 - a[lo:hi, lo:hi, None])
    if sigma > 0:
        canvas = cv2.GaussianBlur(canvas, (0, 0), sigma)
    c1, c2 = (SIDE1 - 1) / 2, (asep.SIDE - 1) / 2
    shift = (o + n / 2 - 0.5) - c1
    m = np.float32([[2, 0, c2 - 2 * (c1 + shift)], [0, 2, c2 - 2 * (c1 + shift) + dy]])
    out = cv2.warpAffine(canvas, m, (asep.SIDE, asep.SIDE), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    return np.clip(out, 0, 255).astype(np.uint8)


def mean_images(bank, train_sids) -> dict:
    acc = defaultdict(lambda: [0.0, 0.0])
    for r, s, a, _, w in bank.rows:
        if s in train_sids:
            acc[a][0] = acc[a][0] + w * bank.img[bank.keys[r]].astype(np.float64)
            acc[a][1] += w
    return {bank.agents[a]: v[0] / v[1] for a, v in acc.items() if v[1] >= 3}


def fit_renderer(bank, art, train_sids, sigmas=(0.0, 0.4, 0.7, 1.0, 1.3, 1.6)) -> dict:
    """Scale, blur and offset minimising disc Lab error to the mean real
    icons after an affine Lab colour map, over agents with 3+ units."""
    means = {a: m for a, m in mean_images(bank, train_sids).items() if a in art}
    disc = regions(asep.SIDE, bank.R)["disc"]
    bg = np.mean([m[disc].mean(0) for m in means.values()], 0)
    tgt = {a: cv2.cvtColor(np.clip(m, 0, 255).astype(np.uint8), cv2.COLOR_BGR2Lab)
           .astype(np.float64)[disc] for a, m in means.items()}
    best = None
    for q in np.arange(0.26, 0.52, 0.02):
        for sigma in sigmas:
            for dy in (-2.0, -1.0, 0.0, 1.0, 2.0):
                src = {a: cv2.cvtColor(render(art[a], q, sigma, dy, bg), cv2.COLOR_BGR2Lab)
                       .astype(np.float64)[disc] for a in means}
                A = np.concatenate([np.c_[src[a], np.ones(len(src[a]))] for a in means])
                Y = np.concatenate([tgt[a] for a in means])
                W, *_ = np.linalg.lstsq(A, Y, rcond=None)
                err = float(((A @ W - Y) ** 2).mean())
                if best is None or err < best["err"]:
                    best = {"err": err, "q": float(q), "sigma": sigma, "dy": dy, "W": W, "bg": bg}
    return best


def rendered_image(art_a, p) -> np.ndarray:
    img = render(art_a, p["q"], p["sigma"], p["dy"], p["bg"])
    L = cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)
    L = np.c_[L, np.ones(len(L))] @ p["W"]
    L = np.clip(L, 0, 255).astype(np.uint8).reshape(asep.SIDE, asep.SIDE, 3)
    return cv2.cvtColor(L, cv2.COLOR_Lab2BGR)


def rendered_refs(bank, art, train_sids, fams, **kw) -> tuple:
    """Per family: the rendered vector of every agent (rows of `agents`,
    NaN without art) and the art-to-game residual variance on the covered."""
    p = fit_renderer(bank, art, train_sids, **kw)
    vecs = {}
    for a in bank.agents:
        if a in art:
            img = rendered_image(art[a], p)
            vecs[a] = describe(img, asep.key_mask(img), bank.R)
    out = {}
    for f in fams:
        M, *_ = bank.fit(f, train_sids)
        Ra = np.full_like(M, np.nan)
        for a, v in vecs.items():
            Ra[bank.aix[a]] = v[f]
        both = np.isfinite(M[:, 0]) & np.isfinite(Ra[:, 0])
        gap = ((Ra[both] - M[both]) ** 2).mean(0) + 1e-6
        out[f] = (Ra, gap)
    return out, p


def pick(v, cs):
    cv = [c for c in cs if np.isfinite(v[c])]
    return cv[int(np.argmax([v[c] for c in cv]))] if cv else None


def art_scores(bank, art, fams, **kw) -> tuple:
    """Fold scores with rendered references fitted on the other sessions."""
    rend, params = {}, {}
    for s in bank.sids:
        rend[s], p = rendered_refs(bank, art, [x for x in bank.sids if x != s], fams, **kw)
        params[s] = {k: p[k] for k in ("q", "sigma", "dy", "err")}
    S = {f: {s: bank.fold_scores(f, s, rend[s]) for s in bank.sids} for f in fams}
    return S, params


def test_calls(bank, S, fs, key, r) -> tuple:
    s = r["session_id"]
    i = bank.idx[(s, r["observation_key"])]
    pos = int(np.nonzero(S[fs[0]][s]["rows"] == i)[0][0])
    return pick(sum(S[f][s][key][pos] for f in fs), cands_of(bank, s)) == bank.aix[r["answer"]]


def run_check() -> dict:
    """Instrument checks: families chosen without the test session's own
    automatic rows (nested), and the rendered blur fixed at each value."""
    bank = Bank()
    art = load_art()
    fams = [f for f in bank.fams if f not in FAMS_REAL_ONLY]
    res = {"sigma": {}}
    for sg in (0.0, 0.7, 1.0, 1.6):
        S, params = art_scores(bank, art, fams, sigmas=(sg,))
        path = greedy(bank, S, fams, key="art", quiet=True)
        fs = [f for f, _ in path]
        c = Counter()
        for r in bank.tests:
            c["cov" if bank.covered_all[r["key"]] else "unc"] += test_calls(bank, S, fs, "art", r)
        res["sigma"][sg] = {"fams": path, "art_cov": c["cov"], "art_unc": c["unc"]}
        print("sigma", sg, res["sigma"][sg], flush=True)
    S, _ = art_scores(bank, art, fams)
    for key in ("mined", "art"):
        c, chosen = Counter(), Counter()
        for s in sorted({r["session_id"] for r in bank.tests}):
            fs = [f for f, _ in greedy(bank, S, fams, key=key, quiet=True,
                                       only=[x for x in bank.sids if x != s])]
            chosen[tuple(fs)] += 1
            for r in bank.tests:
                if r["session_id"] == s:
                    ok = test_calls(bank, S, fs, key, r)
                    c["cov" if bank.covered_all[r["key"]] else "unc"] += ok
        res[f"nested_{key}"] = {"cov": c["cov"], "unc": c["unc"],
                                "sets": {"+".join(k): v for k, v in chosen.items()}}
        print("nested", key, res[f"nested_{key}"], flush=True)
    (WORK / "check.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def run_score() -> dict:
    bank = Bank()
    art = load_art()
    sel = json.loads((WORK / "select.json").read_text())
    fams = [f for f in bank.fams if f not in FAMS_REAL_ONLY]
    S, params = art_scores(bank, art, fams)
    art_path = greedy(bank, S, fams, key="art")
    sets = {"selected": [f for f, _ in sel["greedy"]], "art_selected": [f for f, _ in art_path],
            "comp": ["comp"], "all": fams}
    res = {"n": len(bank.tests), "labels": bank.n_labels,
           "covered_all": sum(bank.covered_all.values()),
           "render_params": params, "art_greedy": art_path, "sets": sets}
    for name, fs in sets.items():
        c = Counter()
        wrong = Counter()
        for r in bank.tests:
            s = r["session_id"]
            i = bank.idx[(s, r["observation_key"])]
            pos = int(np.nonzero(S[fs[0]][s]["rows"] == i)[0][0])
            mined = sum(S[f][s]["mined"][pos] for f in fs)
            elim = sum(S[f][s]["elim"][pos] for f in fs)
            artv = sum(S[f][s]["art"][pos] for f in fs)
            cs = cands_of(bank, s)
            y = bank.aix[r["answer"]]
            cov = np.isfinite(mined[y])
            tag = "cov" if bank.covered_all[r["key"]] else "unc"
            calls = {
                "mined": pick(mined, cs),
                "mined_elim": pick(np.where(np.isfinite(mined), mined,
                                            elim + 1e-3 * np.nan_to_num(artv, nan=-1e9)), cs),
                "art": pick(artv, cs),
                "mined+art": pick(np.where(np.isfinite(mined), mined, artv), cs),
                "mined+art_elim": pick(np.where(np.isfinite(mined), mined,
                                                np.maximum(elim, artv)), cs)}
            for m, p in calls.items():
                ok = p == y
                c[f"{m}"] += ok
                c[f"{m}:{tag}"] += ok
                c[f"{m}:auto_{'cov' if cov else 'unc'}"] += ok
                if m == "mined+art" and not ok and tag == "unc":
                    wrong[f"{r['answer']}->{bank.agents[p] if p is not None else None}"] += 1
            c[f"n:{tag}"] += 1
            c[f"n:auto_{'cov' if cov else 'unc'}"] += 1
        res[name] = dict(sorted(c.items()))
        res[name]["uncovered_errors_mined+art"] = dict(wrong.most_common(12))
    per_agent = defaultdict(Counter)
    fs = sets["selected"]
    for r in bank.tests:
        if bank.covered_all[r["key"]]:
            continue
        s = r["session_id"]
        i = bank.idx[(s, r["observation_key"])]
        pos = int(np.nonzero(S[fs[0]][s]["rows"] == i)[0][0])
        artv = sum(S[f][s]["art"][pos] for f in fs)
        per_agent[r["answer"]]["n"] += 1
        per_agent[r["answer"]]["art"] += pick(artv, cands_of(bank, s)) == bank.aix[r["answer"]]
    res["uncovered_by_agent_selected_art"] = {a: dict(v) for a, v in sorted(per_agent.items())}
    (WORK / "score.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def run_montage(agents=("Jett", "Reyna", "Brimstone", "Cypher")) -> str:
    """Per agent: rendered art, mean real icon, and six real icons, x4."""
    bank = Bank()
    art = load_art()
    p = fit_renderer(bank, art, bank.sids)
    means = mean_images(bank, bank.sids)
    test_imgs = defaultdict(list)
    for r in bank.tests:
        test_imgs[r["answer"]].append(bank.img[(r["session_id"], r["observation_key"])])
    rows = []
    for a in agents:
        real = [bank.img[bank.keys[r]] for r, _, y, _, _ in bank.rows if y == bank.aix[a]]
        real = real[::max(1, len(real) // 6)][:6] if real else test_imgs[a][:6]
        tiles = [rendered_image(art[a], p),
                 np.clip(means[a], 0, 255).astype(np.uint8) if a in means
                 else np.zeros((asep.SIDE, asep.SIDE, 3), np.uint8)] + list(real)
        tiles += [np.zeros_like(tiles[0])] * (8 - len(tiles))
        rows.append(np.hstack([cv2.resize(t, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
                               for t in tiles[:8]]))
    out = WORK / "montage.png"
    cv2.imwrite(str(out), np.vstack(rows))
    print({k: p[k] for k in ("q", "sigma", "dy", "err")})
    return str(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("bank", "select", "score", "check", "montage"))
    a = ap.parse_args()
    if a.step == "bank":
        run_bank()
    elif a.step == "select":
        print(json.dumps(run_select(), indent=1)[:6000])
    elif a.step == "score":
        print(json.dumps(run_score(), indent=1, default=float)[:8000])
    elif a.step == "check":
        print(json.dumps(run_check(), indent=1, default=float)[:4000])
    else:
        print(run_montage())


if __name__ == "__main__":
    main()
