r"""Rescore minimap ally identity against the player's labels, and test contrast.

    .\.venv\Scripts\python.exe prototypes\minimap_identity_clean.py collect
    .\.venv\Scripts\python.exe prototypes\minimap_identity_clean.py rescore
    .\.venv\Scripts\python.exe prototypes\minimap_identity_clean.py binding
    .\.venv\Scripts\python.exe prototypes\minimap_identity_clean.py montage

Purpose. Every minimap identity model built so far was fitted and scored on
killfeed death bindings, which the player found right 107 of 149 times
(`prototypes/label_death_icons.py`, task `death-icon-labels`). His 140
portrait answers are the first clean ground truth. This rescores those
models on them, tests whether identification is contrastive among the
match's four teammates (the player names a smudge because "it couldn't be
any of the others"), sums evidence over the labelled 2 s, and tests a
stricter binding.

Labels. `<store>/labels/death_icon/*.jsonl`, last row per key; class
`agent` with an `answer` is a test icon (its `observation_key`). Candidates
are the reader's four teammates (`mic` session `candidates`).

Leave one session out. Each labelled session is a fold: references, LLR
tables, Fisher masks, covariances and temperatures come only from the other
sessions. Two reference sources: `noisy`, the death bindings as they are;
`fixed`, the same bindings with the player's answers applied (a relabelled
binding takes his agent; not a portrait, another agent or unsure drops it).
`exemplar` alone reads the test session: its automatic bindings, never the
player's labels, never the scored segment.

Models (step 1). `art_best` the reader's stored `best_guess`; `art_raw` the
raw art argmax (`art_pooled` is monotone in it, so per icon they agree);
`mined`, `mined+exemplar` (`minimap_mined_references.MinedModel`);
`comp_fisher` nearest mean reference of the composition over high-Fisher
pixels (`ally_icon_separability`, Fisher map refitted per fold). Each also
with the per-frame joint assignment (`reticle.track.assign`) over the frame's
icons, posteriors a softmax at a temperature fitted on the other folds.

Contrast (step 2), on aligned Lab patches (`lab`) and compositions (`comp`,
`cfish`): `diag` a diagonal Gaussian with the within-agent variance pooled
across training sessions (non-contrastive); `cweight` the same with each
feature weighted by the share of its variance that lies between THIS
match's four references; `cmask` the diagonal Gaussian on the quarter of
features whose four-reference spread over within spread is highest;
`maha` a full shrunk covariance over the four; `mlda` the four whitened
means' 3-d span with the within covariance refitted in it; `pair` the top
two of `comp_fisher` decided on their discriminant with per-agent spreads.

Segments (step 3): log posteriors summed over the labelled segment's last
2 s against the single icon. Binding (step 4): a death binding survives when
no other ally icon comes within `R` px of the bound segment in its last 1 s,
or when the segment ends before the killfeed death rather than after it.

Caches go to `mic.WORK / "clean"`; nothing is written to the store. No
decode: crops come from the lossless minimap cache. Predictions and outcome:
`minimap-identity-clean-labels` in the store's `notes/predictions.jsonl`.
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
from reticle.appearance import hsv_composition  # noqa: E402
from reticle.track import assign  # noqa: E402

import ally_icon_separability as asep  # noqa: E402
import label_death_icons as ldi  # noqa: E402
import minimap_identity_calibration as mic  # noqa: E402
import minimap_mined_references as mmr  # noqa: E402

WORK = mic.WORK / "clean"
TEMPS = np.exp(np.linspace(np.log(1e-3), np.log(100.0), 90))
SHRINK_COV = 0.2
LAST_BIND_MS = 1000.0


# ---------------------------------------------------------------- data

def clean_data():
    """Sessions, death-bound units per session, and the player's labels keyed
    by unit key (answered and certain)."""
    sids = sorted(p.stem for p in mic.WORK.glob("*.pkl"))
    sessions = mic.load_sessions(sids, mic.WORK)
    units = {s: mic.label_units(sessions[s], Counter()) for s in sids}
    labs = {k: r for k, r in ldi._labels().items() if not r.get("uncertain")}
    return sids, sessions, units, labs


def unit_key(sid: str, u: dict) -> str:
    return f"{sid}:{u['segment']}:{u['death_id']}"


def fixed_units(units: dict, labs: dict) -> dict:
    """The bindings with the player's answers applied."""
    out = {}
    for sid, us in units.items():
        out[sid] = []
        for u in us:
            r = labs.get(unit_key(sid, u))
            if r is None:
                out[sid].append(u)
            elif r["class"] == "agent":
                out[sid].append({**u, "victim": r["answer"]})
        # not_portrait / other_agent: the binding is dropped
    return out


def seg_of_keys(data: dict) -> dict:
    return {k: seg for seg, obs in data["obs"].items() for _, k in obs}


def cut_crops(sid: str, keys: set, ev: dict) -> dict:
    """Raw crops as `ally_icon_separability.collect_crops` cuts them."""
    cache = asep._cache(sid)
    x0, y0, x1, y1 = cache.rect_of("minimap")
    t_of = {}
    for f, t in zip(cache.frame_idx, cache.t_ms):
        t_of.setdefault(int(f), float(t))
    by_t = defaultdict(list)
    for k in keys:
        t = t_of.get(int(ev[k]["frame_idx"])) if k in ev else None
        if t is not None:
            by_t[t].append(k)
    rows, h = {}, asep.RAW // 2
    for smp in cache.samples(sorted(by_t), rois=["minimap"]):
        crop = smp.frame[y0:y1, x0:x1]
        pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT, value=0)
        for k in by_t[smp.t_ms]:
            e = ev[k]
            cx, cy = int(round(e["cx"])), int(round(e["cy"]))
            rows[k] = {"raw": pad[cy:cy + asep.RAW, cx:cx + asep.RAW].copy(),
                       "dx": float(e["cx"]) - cx, "dy": float(e["cy"]) - cy,
                       "r": float(e["r"]), "facing": e.get("facing"),
                       "frame": int(e["frame_idx"]), "w": int(crop.shape[1])}
    return rows


def run_collect() -> None:
    """Crops of every labelled icon's frame-mates that the separability cache
    lacks, and every ally icon's position (for the binding test)."""
    sids, sessions, units, labs = clean_data()
    WORK.mkdir(parents=True, exist_ok=True)
    by_sid = defaultdict(list)
    for r in labs.values():
        by_sid[r["session_id"]].append(r)
    for sid in sids:
        data = sessions[sid]
        have = pickle.loads((asep.OUT / f"{sid}.pkl").read_bytes())
        ev = {e["observation_key"]: e for e in mic.STORE.read_events("ally_icon", sid)
              if e.get("kind") == "icon"}
        frames = {data["icons"][r["observation_key"]]["frame"] for r in by_sid[sid]
                  if r["observation_key"] in data["icons"]}
        want = {k for k, i in data["icons"].items() if i["frame"] in frames} - set(have)
        extra = cut_crops(sid, want, ev) if want else {}
        pos = {k: (float(e["t_ms"]), float(e["cx"]), float(e["cy"]), int(e["frame_idx"]))
               for k, e in ev.items()}
        (WORK / f"{sid}.pkl").write_bytes(pickle.dumps({"extra": extra, "pos": pos}))
        print(sid, "labels", len(by_sid[sid]), "extra crops", len(extra), "of", len(want),
              flush=True)


# ---------------------------------------------------------------- features

class IconFeatures:
    """Aligned image, key mask and fixed descriptors per (sid, key)."""

    def __init__(self, sids, sessions):
        self.crops = {}
        for sid in sids:
            c = pickle.loads((asep.OUT / f"{sid}.pkl").read_bytes())
            c.update(pickle.loads((WORK / f"{sid}.pkl").read_bytes())["extra"])
            self.crops[sid] = c
        rows = [(s, k) for s in sids for k in self.crops[s]]
        r_px = asep.median_r(rows, self.crops)
        desc = asep.Describer(r_px, np.zeros((asep.SIDE, asep.SIDE)))
        self.img, self.keyed, self.lab, self.comp, self.labvec = {}, {}, {}, {}, {}
        for s, k in rows:
            row = self.crops[s][k]
            img = asep.aligned(row)
            self.img[(s, k)] = img
            self.keyed[(s, k)] = asep.key_mask(img)
            self.labvec[(s, k)] = asep.lab(img).reshape(-1)
            self.lab[(s, k)] = desc(row)["lab_patch"].astype(np.float32)
            d = sessions[s]
            self.comp[(s, k)] = d["comp"][d["icons"][k]["row"]] if k in d["icons"] else None

    def has(self, s, k) -> bool:
        return (s, k) in self.img


def train_rows(units: dict, sids, feats: IconFeatures) -> list:
    """(sid, key, agent, unit id, weight) over labelled last-2-s icons with a
    crop; a unit weighs one in total."""
    out = []
    for sid in sids:
        for j, u in enumerate(units[sid]):
            ks = [k for k in u["keys_last"] if feats.has(sid, k)]
            out += [(sid, k, u["victim"], (sid, j), 1.0 / len(ks)) for k in ks]
    return out


def weighted_stats(X, y, w):
    """Per-agent weighted means (units equal) and the pooled within-agent
    residuals with their weights."""
    ya = np.array(y)
    means, R, RW = {}, [], []
    for a in sorted(set(y)):
        m = ya == a
        ww = w[m] / w[m].sum()
        mu = (X[m] * ww[:, None]).sum(0)
        means[a] = mu
        R.append(X[m] - mu)
        RW.append(ww / len(set(y)))
    return means, np.concatenate(R), np.concatenate(RW)


class Contrast:
    """Gaussian scorers over one feature, fitted on training rows."""

    def __init__(self, X, y, w):
        self.means, R, rw = weighted_stats(X, y, w)
        self.var = (R ** 2 * rw[:, None]).sum(0) / rw.sum() + 1e-6
        M = np.array(list(self.means.values()))
        self.gmean, self.bvar = M.mean(0), M.var(0)
        d = X.shape[1]
        S = (R * rw[:, None]).T @ R / rw.sum()
        S = (1 - SHRINK_COV) * S + SHRINK_COV * np.trace(S) / d * np.eye(d)
        ev, V = np.linalg.eigh(S)
        self.Wh = V / np.sqrt(np.maximum(ev, 1e-9))
        self.Rw = R @ self.Wh
        self.rw = rw
        self.wmeans = {a: m @ self.Wh for a, m in self.means.items()}
        self.X, self.y, self.w = X, np.array(y), w

    def scores(self, x, cands, kind) -> dict:
        if kind == "elim":
            # Diagonal Gaussian log likelihoods; a candidate with no reference
            # scores under "some agent unlike the referenced ones": the mean of
            # all references, spread widened by their between-agent variance.
            out = {}
            for a in cands:
                m, v = ((self.means[a], self.var) if a in self.means
                        else (self.gmean, self.var + self.bvar))
                out[a] = float(-0.5 * (((x - m) ** 2) / v + np.log(v)).sum())
            return out
        cs = [a for a in cands if a in self.means]
        if not cs:
            return {}
        M = np.array([self.means[a] for a in cs])
        if kind == "diag":
            return dict(zip(cs, -(((x - M) ** 2) / self.var).sum(1)))
        if kind in ("cweight", "cmask"):
            b = M.var(0)
            ratio = b / self.var
            if kind == "cweight":
                g = b / (b + self.var)
            else:
                g = (ratio >= np.quantile(ratio, 0.75)).astype(float)
            return dict(zip(cs, -((g * (x - M) ** 2) / self.var).sum(1)))
        z = x @ self.Wh
        Mz = np.array([self.wmeans[a] for a in cs])
        if kind == "maha":
            return dict(zip(cs, -0.5 * ((z - Mz) ** 2).sum(1)))
        if kind == "mlda":
            M0 = Mz - Mz.mean(0)
            _, _, Vt = np.linalg.svd(M0, full_matrices=False)
            P = Vt[:max(1, len(cs) - 1)].T
            Rp = self.Rw @ P
            C = (Rp * self.rw[:, None]).T @ Rp / self.rw.sum() + 1e-6 * np.eye(P.shape[1])
            Ci = np.linalg.inv(C)
            D = z @ P - Mz @ P
            return dict(zip(cs, -0.5 * np.einsum("ij,jk,ik->i", D, Ci, D)))
        raise ValueError(kind)

    def pair(self, x, a, b) -> dict:
        """Decide `a` against `b` on their shrunk discriminant, each agent's
        own spread along it (shrunk toward the pooled spread by 5 units)."""
        if a not in self.means or b not in self.means:
            return {}
        dvec = (self.wmeans[a] - self.wmeans[b]) @ self.Wh.T
        proj = self.X @ dvec
        pooled = float(((self.Rw @ (self.wmeans[a] - self.wmeans[b])) ** 2 * self.rw).sum()
                       / self.rw.sum())
        out = {}
        for c in (a, b):
            m = self.y == c
            ww = self.w[m]
            mu = float((proj[m] * ww).sum() / ww.sum())
            v = float((((proj[m] - mu) ** 2) * ww).sum() / ww.sum())
            v = (v * ww.sum() + pooled * 5.0) / (ww.sum() + 5.0)
            xp = float(x @ dvec)
            out[c] = -0.5 * (xp - mu) ** 2 / v - 0.5 * math.log(v)
        return out


# ---------------------------------------------------------------- rescore

def softmax_log(sc: dict, temp: float) -> dict:
    m = max(sc.values())
    z = sum(math.exp((v - m) / temp) for v in sc.values())
    return {a: (v - m) / temp - math.log(z) for a, v in sc.items()}


def fold_scores(test_sid, sids, sessions, units_src, units_noisy, feats, need):
    """Per model, {key: score dict} for the test session's `need` keys, with
    every fitted quantity from the other sessions."""
    others = [s for s in sids if s != test_sid]
    data = sessions[test_sid]
    cands = data["candidates"]
    segs = seg_of_keys(data)
    train_units = [u for s in others for u in units_src[s]]
    out = defaultdict(dict)
    for k in need:
        icon = data["icons"].get(k)
        if icon is None:
            continue
        out["art_raw"][k] = {a: icon["scores"][a] for a in cands if a in icon["scores"]}
    for name, fams in (("mined", ("mined",)), ("mined+exemplar", ("mined", "exemplar"))):
        model = mmr.MinedModel(sessions, units_noisy, train_units, train_units, fams)
        for k in need:
            if k in data["icons"]:
                out[name][k] = model.llr(test_sid, k, segs.get(k))
    rows = train_rows(units_src, others, feats)
    y = [r[2] for r in rows]
    w = np.array([r[4] for r in rows])
    Fs = asep.fisher(np.array([feats.labvec[(s, k)] for s, k, *_ in rows]), y, w)
    Fs = Fs.reshape(asep.SIDE, asep.SIDE, 3).sum(2)
    fmask = Fs >= np.quantile(Fs, 0.75)

    def cfish(s, k):
        return hsv_composition(feats.img[(s, k)], fmask & ~feats.keyed[(s, k)])

    Xf = np.array([cfish(s, k) for s, k, *_ in rows])
    refs = asep.unit_refs({(s, k): x for (s, k, *_), x in zip(rows, Xf)}, rows)
    test_f = {k: cfish(test_sid, k) for k in need if feats.has(test_sid, k)}
    for k, x in test_f.items():
        out["comp_fisher"][k] = {a: float(np.minimum(x, refs[a]).sum()) for a in cands if a in refs}
    stored = [r for r in rows if feats.comp[(r[0], r[1])] is not None]
    fams = {"lab": (np.array([feats.lab[(s, k)] for s, k, *_ in rows]), rows,
                    {k: feats.lab[(test_sid, k)] for k in test_f}),
            "comp": (np.array([feats.comp[(s, k)] for s, k, *_ in stored]), stored,
                     {k: feats.comp[(test_sid, k)] for k in test_f
                      if feats.comp[(test_sid, k)] is not None}),
            "cfish": (Xf, rows, test_f)}
    for fam, (X, rr, tx) in fams.items():
        con = Contrast(X, [r[2] for r in rr], np.array([r[4] for r in rr]))
        for kind in ("diag", "cweight", "cmask", "maha", "mlda", "elim"):
            for k, x in tx.items():
                out[f"{fam}_{kind}"][k] = con.scores(x, cands, kind)
        for k in tx:
            # two unreferenced candidates tie under `elim`: the art score splits them
            art = out["art_raw"].get(k, {})
            out[f"{fam}_elim"][k] = {a: v + (1e-3 * art.get(a, 0.0) if a not in con.means else 0.0)
                                     for a, v in out[f"{fam}_elim"][k].items()}
        for k, x in tx.items():
            base = out["comp_fisher"].get(k) or {}
            top = sorted(base, key=base.get, reverse=True)[:2]
            if len(top) == 2:
                pr = con.pair(x, *top)
                if pr:
                    rest = {a: -1e9 for a in cands if a not in pr}
                    out[f"{fam}_pair"][k] = {**pr, **rest}
    return out


def fit_temp(pairs) -> float:
    def nll(t):
        return -sum(softmax_log(sc, t).get(v, -30.0) for sc, v in pairs)
    return float(min(TEMPS, key=nll))


def argmax(sc: dict):
    return max(sc, key=sc.get) if sc else None


def run_rescore() -> dict:
    sids, sessions, units, labs = clean_data()
    feats = IconFeatures(sids, sessions)
    unit_by_key = {unit_key(s, u): u for s in sids for u in units[s]}
    tests = [r for r in labs.values() if r["class"] == "agent" and r["key"] in unit_by_key]
    by_sid = defaultdict(list)
    for r in tests:
        by_sid[r["session_id"]].append(r)
    sources = {"noisy": units, "fixed": fixed_units(units, labs)}
    scores = {}          # (source, model) -> {(sid, key): score dict}
    for src, usrc in sources.items():
        for sid in sorted(by_sid):
            data = sessions[sid]
            need = set()
            for r in by_sid[sid]:
                f = data["icons"][r["observation_key"]]["frame"]
                need |= {k for k, i in data["icons"].items() if i["frame"] == f}
                need |= set(unit_by_key[r["key"]]["keys_last"])
            got = fold_scores(sid, sids, sessions, usrc, units, feats, need)
            for m, d in got.items():
                for k, sc in d.items():
                    scores.setdefault((src, m), {})[(sid, k)] = sc
            print(src, sid, "labels", len(by_sid[sid]), flush=True)
    (WORK / "scores.pkl").write_bytes(pickle.dumps({"scores": scores, "tests": tests}))
    return summarise(sessions, units, unit_by_key, tests, scores)


def summarise(sessions, units, unit_by_key, tests, scores) -> dict:
    bound = {s: {u["victim"] for u in us} for s, us in units.items()}
    covered = {r["key"]: any(r["answer"] in bound[s] for s in bound if s != r["session_id"])
               for r in tests}
    res = {"n": len(tests), "covered": sum(covered.values()),
           "art_best": sum(sessions[r["session_id"]]["icons"][r["observation_key"]]["best"]
                           == r["answer"] for r in tests)}
    per_agent = defaultdict(lambda: defaultdict(Counter))
    per_agent_n = Counter(r["answer"] for r in tests)
    for r in tests:
        best = sessions[r["session_id"]]["icons"][r["observation_key"]]["best"]
        per_agent["art_best"][r["answer"]]["ok"] += best == r["answer"]
    calls = {}
    for (src, m), sc in scores.items():
        if m == "art_raw" and src == "fixed":
            continue
        name = m if m == "art_raw" else f"{src}:{m}"
        temps = {}
        for sid in {r["session_id"] for r in tests}:
            pairs = [(sc[(r["session_id"], r["observation_key"])], r["answer"]) for r in tests
                     if r["session_id"] != sid and sc.get((r["session_id"], r["observation_key"]))]
            temps[sid] = fit_temp(pairs)
        c = Counter()
        for r in tests:
            sid, k = r["session_id"], r["observation_key"]
            data = sessions[sid]
            s = sc.get((sid, k)) or {}
            ok = argmax(s) == r["answer"]
            c["icon"] += ok
            c["icon_covered" if covered[r["key"]] else "icon_uncovered"] += ok
            c["uncovered"] += r["answer"] not in s
            per_agent[name][r["answer"]]["ok"] += ok
            calls[(name, sid, k)] = argmax(s)
            # joint: the frame's icons take distinct teammates
            f = data["icons"][k]["frame"]
            keys = [kk for kk, i in data["icons"].items() if i["frame"] == f and sc.get((sid, kk))]
            cands = data["candidates"]
            if k in keys:
                cost = [[-softmax_log(sc[(sid, kk)], temps[sid]).get(a, -30.0) for a in cands]
                        for kk in keys]
                col = assign(cost)[keys.index(k)]
                jok = col >= 0 and cands[col] == r["answer"]
            else:
                jok = ok
            c["joint"] += jok
            c["frames_multi"] += len(keys) > 1
            per_agent[name][r["answer"]]["joint"] += jok
            # segment: log posteriors over the labelled last 2 s
            u = unit_by_key[r["key"]]
            tot = Counter()
            for kk in u["keys_last"]:
                if sc.get((sid, kk)):
                    tot.update(softmax_log(sc[(sid, kk)], temps[sid]))
            c["segment"] += argmax(dict(tot)) == r["answer"]
            per_agent[name][r["answer"]]["seg"] += argmax(dict(tot)) == r["answer"]
        res[name] = {**dict(c), "temp_median": round(float(np.median(list(temps.values()))), 4)}
    res["by_agent_n>=3"] = {
        a: {m: f"{per_agent[m][a]['ok']}" + (f"/j{per_agent[m][a]['joint']}" if m != "art_best" else "")
            for m in ("art_best", "art_raw", "noisy:mined", "noisy:mined+exemplar",
                      "noisy:comp_fisher", "noisy:cfish_diag", "noisy:cfish_cweight",
                      "noisy:cfish_elim", "fixed:cfish_elim")}
        | {"n": n} for a, n in sorted(per_agent_n.items()) if n >= 3}
    (WORK / "calls.pkl").write_bytes(pickle.dumps(calls))
    return res


# ---------------------------------------------------------------- binding

def run_binding() -> dict:
    """A death binding survives when no other ally icon comes within `R` px of
    the bound segment in its last `LAST_BIND_MS`."""
    sids, sessions, units, labs = clean_data()
    res = {}
    rows = []
    for sid in sids:
        data = sessions[sid]
        pos = pickle.loads((WORK / f"{sid}.pkl").read_bytes())["pos"]
        t_death = {d["death_id"]: d["t"] for d in data["deaths"]}
        by_frame = defaultdict(list)
        for k, (t, x, yy, f) in pos.items():
            by_frame[f].append(k)
        for u in units[sid]:
            obs = data["obs"][u["segment"]]
            own = {k for _, k in obs}
            end = obs[-1][0]
            dmin = math.inf
            for t, k in obs:
                if t < end - LAST_BIND_MS or k not in pos:
                    continue
                _, x, yy, f = pos[k]
                for kk in by_frame[f]:
                    if kk not in own:
                        dmin = min(dmin, math.hypot(pos[kk][1] - x, pos[kk][2] - yy))
            r = labs.get(unit_key(sid, u))
            rows.append({"d": dmin, "dt": end - t_death[u["death_id"]], "label": None if r is None else
                         (r["answer"] if r["class"] == "agent" else r["class"]),
                         "victim": u["victim"]})
    lab_rows = [r for r in rows if r["label"] is not None]
    res["bindings"] = len(rows)
    res["labelled"] = len(lab_rows)
    res["labelled_right"] = sum(r["label"] == r["victim"] for r in lab_rows)
    for R in (10, 20, 30, 45, 60):
        keep = [r for r in lab_rows if r["d"] > R]
        res[f"R{R}"] = {"all_kept": sum(r["d"] > R for r in rows),
                        "labelled_kept": len(keep),
                        "kept_right": sum(r["label"] == r["victim"] for r in keep),
                        "dropped_right": sum(r["label"] == r["victim"] for r in lab_rows
                                             if r["d"] <= R)}
    # timing: the victim's icon goes before the killfeed shows the death
    for hi in (0.0, -100.0, -200.0):
        keep = [r for r in lab_rows if r["dt"] < hi]
        res[f"end_before_{int(-hi)}ms"] = {
            "all_kept": sum(r["dt"] < hi for r in rows), "labelled_kept": len(keep),
            "kept_right": sum(r["label"] == r["victim"] for r in keep)}
    after = [r for r in lab_rows if r["dt"] >= 0]
    res["end_at_or_after_death"] = {"labelled": len(after),
                                    "right": sum(r["label"] == r["victim"] for r in after)}
    return res


# ---------------------------------------------------------------- montage

def run_montage(a: str = "fixed:comp_fisher", b: str = "fixed:cfish_cweight") -> dict:
    """Icons where contrast (`b`) fixes or breaks the call of `a`: aligned
    crop at 4x, captioned answer / a / b."""
    sids, sessions, units, labs = clean_data()
    calls = pickle.loads((WORK / "calls.pkl").read_bytes())
    tests = pickle.loads((WORK / "scores.pkl").read_bytes())["tests"]
    feats_crops = {s: pickle.loads((asep.OUT / f"{s}.pkl").read_bytes()) for s in sids}
    tiles = []
    for r in tests:
        sid, k = r["session_id"], r["observation_key"]
        ca, cb = calls.get((a, sid, k)), calls.get((b, sid, k))
        if (ca == r["answer"]) != (cb == r["answer"]):
            img = cv2.resize(asep.aligned(feats_crops[sid][k]), None, fx=4, fy=4,
                             interpolation=cv2.INTER_NEAREST)
            pad = cv2.copyMakeBorder(img, 0, 42, 0, 0, cv2.BORDER_CONSTANT, value=0)
            col = (80, 220, 80) if cb == r["answer"] else (60, 60, 230)
            for i, txt in enumerate((r["answer"], f"a {ca}", f"c {cb}")):
                cv2.putText(pad, txt, (2, img.shape[0] + 12 + 14 * i),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1)
            tiles.append(pad)
    if not tiles:
        return {"changed": 0}
    ncol = 8
    while len(tiles) % ncol:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + ncol]) for i in range(0, len(tiles), ncol)])
    path = WORK / "contrast_montage.png"
    cv2.imwrite(str(path), grid)
    return {"changed": len(tiles), "path": str(path)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("collect", "rescore", "binding", "montage"))
    ap.add_argument("--a", default="fixed:comp_fisher")
    ap.add_argument("--b", default="fixed:cfish_cweight")
    o = ap.parse_args()
    if o.step == "collect":
        run_collect()
        sys.exit(0)
    out = {"rescore": run_rescore, "binding": run_binding,
           "montage": lambda: run_montage(o.a, o.b)}[o.step]()
    (WORK / f"{o.step}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, default=str)[:3000])
