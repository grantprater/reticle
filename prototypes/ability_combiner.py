"""Weighted combiner for the ability candidate features, fitted honestly.

the player asked for this on 2026-09-05 after the gate re-ran on 85 positives and
`patch_range` fell from 0.86 to 0.57. The standing objection is recorded in
`NOTES.md` and is NOT resolved by this file: the corpus is two capture regimes
(four ordinary captures, five `infinite-abilities` custom games) and a combiner
fitted across both can fit the regime instead of the ability. This module is
built so that failure is VISIBLE rather than hidden -- it reports leave-one-
SESSION-out only, and it reports the per-regime split of every headline number.

Why logistic regression and not something larger
------------------------------------------------------------------------------
85 positives. A model with more capacity than this has nothing to learn from
and every opportunity to memorise the session it was fitted on. Weights are
L2-regularised and the strength is chosen by an INNER leave-one-session-out
loop over the training sessions only, so the held-out session is never involved
in choosing anything. Fitted with Newton-IRLS, which converges in ~8 iterations
at this size and needs no learning rate to tune.

Standardisation is PER SESSION, not global
------------------------------------------------------------------------------
Each session's features are z-scored using that session's own mean and SD,
including the held-out one. That is unsupervised -- it uses no labels -- so it
leaks nothing, and it is the one defence available against the regime confound:
it removes any per-session offset and scale, which is exactly the axis the
old/new split lives on. `--global-z` turns it off to show what it is worth.

The baselines that matter
------------------------------------------------------------------------------
A combiner is only interesting if it beats (a) the best single feature under
the same protocol, and (b) the equal-weight z-sum that `NOTES.md` records as
tying with it. Both are printed next to it every run. If it does not clear
them, it has not earned the parameters.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import ability_features as af                                         # noqa: E402

# Ordinary captures vs `infinite-abilities` custom-game demo clips. The split
# that `patch_range` breaks along; carried here so every number can be read
# per-regime without re-deriving it from the manifests.
NEW_REGIME = {"dae6f33f3f48", "02cf738b1c8f", "6bb88dba5d2c",
              "6ab7a9e99235", "ff19748eea8c"}

DEFAULT_FEATS = ["cone_cond", "autocorr1", "patch_range", "dark_p90",
                 "n_runs", "self_d_min"]


def zsess(X):
    """Z-score within one session. Zero-variance columns go to zero, not nan."""
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(np.isfinite(sd) & (sd > 1e-9), sd, 1.0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    return (X - mu) / sd


def fit_logit(X, y, lam, iters=25):
    """L2-penalised logistic regression by Newton-IRLS. Returns (w, b).

    The intercept is NOT penalised -- penalising it would drag the predicted
    base rate toward 0.5 and make precision depend on the class balance of
    whichever sessions happened to be in the training fold.
    """
    n, d = X.shape
    Xb = np.hstack([X, np.ones((n, 1))])
    w = np.zeros(d + 1)
    P = np.eye(d + 1) * lam
    P[-1, -1] = 0.0
    for _ in range(iters):
        z = Xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        W = np.clip(p * (1 - p), 1e-6, None)
        g = Xb.T @ (p - y) + P @ w
        H = (Xb * W[:, None]).T @ Xb + P
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        w_new = w - step
        if not np.all(np.isfinite(w_new)):
            break
        if np.max(np.abs(w_new - w)) < 1e-8:
            w = w_new
            break
        w = w_new
    return w[:-1], w[-1]


def prep(per, ys, sids, feats, per_session_z):
    """(X, y, session index) for a list of sessions, imputed and standardised."""
    Xs, yl, sl = [], [], []
    for s in sids:
        X = np.column_stack([per[s][k] for k in feats]).astype(float)
        if per_session_z:
            X = zsess(X)
        Xs.append(X)
        yl.append(ys[s])
        sl.append(np.full(len(ys[s]), s, object))
    X = np.vstack(Xs)
    y = np.concatenate(yl).astype(float)
    sess = np.concatenate(sl)
    return X, y, sess


def impute(Xtr, Xte):
    """Median of the TRAINING rows, applied to both. Never the test median."""
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    return (np.where(np.isfinite(Xtr), Xtr, med),
            np.where(np.isfinite(Xte), Xte, med))


def youden(score, y):
    """Threshold maximising tpr - fpr. No cost ratio to assume."""
    best, bj = 0.0, -2.0
    for c in np.unique(score):
        pred = score >= c
        j = pred[y == 1].mean() - pred[y == 0].mean()
        if j > bj:
            best, bj = float(c), j
    return best


def loso_scores(per, ys, sids, feats, per_session_z, lams):
    """Held-out score for every row, plus the weights each fold chose."""
    out_score = {}
    chosen = []
    for held in sids:
        tr = [s for s in sids if s != held]
        Xtr, ytr, str_ = prep(per, ys, tr, feats, per_session_z)
        Xte, yte, _ = prep(per, ys, [held], feats, per_session_z)
        Xtr, Xte = impute(Xtr, Xte)

        # INNER leave-one-session-out over the training sessions only, to pick
        # lambda. The held-out session takes no part in this.
        best_lam, best_auc = lams[0], -1.0
        for lam in lams:
            sc, yy = [], []
            for inner in tr:
                m = str_ != inner
                if not (ytr[m] == 1).any() or not (ytr[m] == 0).any():
                    continue
                w, b = fit_logit(Xtr[m], ytr[m], lam)
                sc.append(Xtr[~m] @ w + b)
                yy.append(ytr[~m])
            if not sc:
                continue
            sc, yy = np.concatenate(sc), np.concatenate(yy)
            a = af.auc(sc[yy == 1], sc[yy == 0])
            if np.isfinite(a) and a > best_auc:
                best_lam, best_auc = lam, a

        w, b = fit_logit(Xtr, ytr, best_lam)
        thr = youden(Xtr @ w + b, ytr)
        out_score[held] = (Xte @ w + b, yte, thr)
        chosen.append((held, best_lam, w.copy()))
    return out_score, chosen


def pr(out_score, subset=None):
    """Pooled precision/recall/AUC over held-out folds."""
    tp = fp = fn = 0
    P, N = [], []
    for s, (sc, y, thr) in out_score.items():
        if subset is not None and s not in subset:
            continue
        pred = sc >= thr
        tp += int((pred & (y == 1)).sum())
        fp += int((pred & (y == 0)).sum())
        fn += int((~pred & (y == 1)).sum())
        P.append(sc[y == 1])
        N.append(sc[y == 0])
    if not P:
        return float("nan"), float("nan"), float("nan"), 0
    P, N = np.concatenate(P), np.concatenate(N)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return prec, rec, af.auc(P, N), len(P)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--group", default="device",
                    help="positive group to fit ('device', 'all', ...)")
    ap.add_argument("--feats", default=",".join(DEFAULT_FEATS))
    ap.add_argument("--global-z", action="store_true",
                    help="standardise across all sessions instead of per session")
    a = ap.parse_args()
    feats = [f.strip() for f in a.feats.split(",") if f.strip()]

    sids = sorted(p.stem for p in af.SERIES_LABELS.glob("*.npz"))
    per, ys, gs = {}, {}, {}
    for sid in sids:
        try:
            f, y, g = af.features(sid)
        except Exception as e:  # noqa: BLE001
            print(f"{sid}: SKIPPED ({e})")
            continue
        if y.sum() == 0 or (~y).sum() == 0:
            print(f"{sid}: no both-class labels ({int(y.sum())}/{int((~y).sum())})")
            continue
        per[sid], ys[sid], gs[sid] = f, y, g

    if a.group != "all":
        per, ys = af.restrict(per, ys, gs, a.group)
    sids = sorted(per)
    npos = sum(int(ys[s].sum()) for s in sids)
    nneg = sum(int((~ys[s]).sum()) for s in sids)
    print(f"\ngroup={a.group}  sessions={len(sids)}  pos={npos}  neg={nneg}")
    print(f"features ({len(feats)}): {', '.join(feats)}")
    print(f"standardisation: {'GLOBAL' if a.global_z else 'per session'}")
    print(f"parameters fitted: {len(feats) + 1}  ->  {npos / (len(feats) + 1):.1f}"
          " positives per parameter")

    for k in feats:
        nan = np.concatenate([~np.isfinite(per[s][k]) for s in sids]).mean()
        if nan > 0.02:
            print(f"  note: {k} is nan on {nan:.0%} of rows (training-median imputed)")

    lams = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
    out, chosen = loso_scores(per, ys, sids, feats, not a.global_z, lams)

    print("\n=== leave-one-SESSION-out, held-out rows only ===")
    print(f"{'model':<34}{'prec':>7}{'recall':>8}{'AUC':>7}")
    p, r, auc_, _ = pr(out)
    print(f"{'weighted combiner':<34}{p:7.2f}{r:8.2f}{auc_:7.2f}")

    # Baseline 1: equal-weight z-sum, signs from the pooled direction.
    eq = {}
    for held in sids:
        tr = [s for s in sids if s != held]
        Xtr, ytr, _ = prep(per, ys, tr, feats, not a.global_z)
        Xte, yte, _ = prep(per, ys, [held], feats, not a.global_z)
        Xtr, Xte = impute(Xtr, Xte)
        sg = np.array([1.0 if af.auc(Xtr[ytr == 1, j], Xtr[ytr == 0, j]) >= 0.5
                       else -1.0 for j in range(Xtr.shape[1])])
        eq[held] = ((Xte * sg).sum(1), yte, youden((Xtr * sg).sum(1), ytr))
    p, r, auc_, _ = pr(eq)
    print(f"{'equal-weight z-sum':<34}{p:7.2f}{r:8.2f}{auc_:7.2f}")

    # Baseline 2: every single feature under the identical protocol.
    best = None
    for j, k in enumerate(feats):
        one = {}
        for held in sids:
            tr = [s for s in sids if s != held]
            Xtr, ytr, _ = prep(per, ys, tr, [k], not a.global_z)
            Xte, yte, _ = prep(per, ys, [held], [k], not a.global_z)
            Xtr, Xte = impute(Xtr, Xte)
            sg = 1.0 if af.auc(Xtr[ytr == 1, 0], Xtr[ytr == 0, 0]) >= 0.5 else -1.0
            one[held] = (Xte[:, 0] * sg, yte, youden(Xtr[:, 0] * sg, ytr))
        p, r, auc_, _ = pr(one)
        print(f"{'  single: ' + k:<34}{p:7.2f}{r:8.2f}{auc_:7.2f}")
        if best is None or (np.isfinite(auc_) and auc_ > best[1]):
            best = (k, auc_)

    print("\n=== the same combiner, split by capture regime ===")
    print("If these two rows disagree, the combiner fitted the regime.")
    print(f"{'regime':<34}{'prec':>7}{'recall':>8}{'AUC':>7}{'  n pos':>8}")
    old = {s for s in sids if s not in NEW_REGIME}
    new = {s for s in sids if s in NEW_REGIME}
    for name, sub in (("ordinary captures", old), ("infinite-abilities demos", new)):
        p, r, auc_, n = pr(out, sub)
        print(f"{name:<34}{p:7.2f}{r:8.2f}{auc_:7.2f}{n:8d}")

    print("\n=== weights each fold chose (per-session z units) ===")
    print(f"{'held out':<14}{'lambda':>8}  " + "".join(f"{k[:11]:>12}" for k in feats))
    for held, lam, w in chosen:
        print(f"{held[:12]:<14}{lam:8.1f}  " + "".join(f"{v:12.2f}" for v in w))
    W = np.array([w for _, _, w in chosen])
    print(f"{'sign agreement':<14}{'':>8}  "
          + "".join(f"{max((W[:, j] > 0).mean(), (W[:, j] < 0).mean()):12.0%}"
                    for j in range(W.shape[1])))
    print("\nA weight whose SIGN flips between folds is not a weight, it is the")
    print("fold talking. Read that row before reading any headline above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
