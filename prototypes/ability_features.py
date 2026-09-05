"""Every temporal feature the series can carry, each scored on its own and per session.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_features.py
    .\\.venv\\Scripts\\python.exe prototypes\\ability_features.py --min-auc 0.70

Why the scoring is shaped like this
------------------------------------
the player asked for every tactic thrown at the problem. The way that has already
failed once here is the ranked corpus: many features, fitted together, on 254
label rows drawn from five ability classes and three agents, producing a
threshold that did not transfer. Adding more features to that protocol makes the
failure arrive faster, not slower.

So the bank is wide and the scoring is deliberately narrow:

* **each feature is scored ALONE.** No combination, no weights, nothing fitted.
  A feature that cannot separate by itself cannot be rescued by a fit at this n;
* **the statistic is AUC**, which is rank-based and threshold-free. There is no
  cutoff to overfit, and it is readable at n=6 in a way an accuracy is not;
* **the number that decides is PER SESSION, not pooled.** The failure mode of
  this project is a figure that holds on one population and dies on the next,
  and pooling hides exactly that. A feature is interesting when it separates on
  several sessions in the SAME direction, and a pooled AUC of 0.85 carried by
  one session is a warning, not a result;
* **`n` is printed beside every figure.** Positives run 6-10 per session.

AUC 0.5 is nothing. With six positives, the standard error is near 0.15, so a
single-session AUC below about 0.8 is inside the noise -- the per-session
CONSISTENCY is doing the work here, not any one value.

Sliced by `win_lo`/`win_hi`, always
------------------------------------
Every feature reads only its own query's window. Reading the shared axis instead
reported `detect` firing 75.5% at the median query and 75.7% at the max across
53 queries on 2026-09-04 -- uniformity that looks like a finding and is
arithmetic. On a 38-second clip the same mistake moved the median from 40.8% to
14.9%. This is not a subtlety; it is the difference between measuring an object
and measuring a clip.

RESULT, 2026-09-04: one feature transfers, and stacking makes it WORSE
-----------------------------------------------------------------------
27 positives against 176 negatives over four sessions (`a06f04a0059f` and
`5822b6646448` are all-positive and cannot be scored). Leave-one-session-out,
threshold fitted on the other three:

    gate                              precision   recall
    everything is positive (base)          0.13     1.00
    patch_range                            0.49     0.85
    autocorr1                              0.25     0.78
    self_d_med (inverted)                  0.24     0.78
    dark_med                               0.22     0.67
    patch_range AND autocorr1              0.47     0.67
    patch_range AND autocorr1 AND self_d   0.44     0.44

**`patch_range` alone is the result: 0.13 -> 0.49 precision, 3.8x, at 0.85
recall, on sessions whose threshold it never saw.** It is the median of
`g_max - g_min` inside the patch -- intra-patch CONTRAST, the Phase 2 feature
predicted to separate animating abilities from lit static cracks. It is also the
only feature that separates on all four sessions in the same direction.

**Combining raises PRECISION a long way and costs recall, and no combiner tried
wins on both.** The features that complement contrast are the ones weakly
correlated with it -- `n_runs` (0.26) and `cone_cond` (0.04) -- not the
amplitude siblings (`autocorr1` 0.50, `dark_p90` 0.55) tried first:

    combiner (all thresholds fitted leave-one-session-out)  prec  recall   F1
    patch_range alone                                       0.49    0.85  0.62
    AND n_runs                                              0.73    0.41  0.52
    AND cone_cond                                           0.80    0.15  0.25
    AND cone_cond AND n_runs                                 nan    0.00   nan
    soft z-sum + n_runs                                     0.54    0.74  0.62
    soft z-sum + n_runs + cone_cond                         0.35    0.78  0.48

AND-ing hard thresholds multiplies misses -- three of them delete every positive
-- and an equal-weight z-sum dilutes a strong feature with weak ones. What is
missing is a WEIGHTED combiner, and 27 positives will not support fitting one
without landing back in the ranked-corpus failure.

So: the complements are real, and the blocker is label volume rather than
feature design. The high-precision operating point is genuinely available if it
is wanted -- `patch_range AND n_runs` gives 0.73 precision at 0.41 recall, which
suits assisted labelling even though its F1 is worse.

Three things falsified, which is what the gate is for
------------------------------------------------------
* **the cone-coverage two-factor conditional fails AS A GATE, and that is not
  the same as failing.** `cone_cond` scores 0.40 pooled and agrees on 2 of 4
  sessions, so it cannot be a first-stage filter. But among the 47 candidates
  that PASS the `patch_range` gate (23 real, 24 false) it separates at 0.32
  (0.68 inverted) while correlating **0.04** with `patch_range` -- it is very
  nearly orthogonal to contrast, and it carries signal on exactly the cases
  contrast cannot resolve. The first version of this docstring called it
  falsified. That was wrong: a single-feature AUC cannot see a complement.
  `dark_lit_gap`, the same idea on raw darkness, scores 0.48;
* **noise normalisation HURTS.** `dark_z_p90` (0.63) is well below plain
  `dark_p90` (0.79). The early directional figure on 2026-09-04 -- pos/neg
  separation 1.36 -> 2.69 on five positives of one class -- does not survive
  scoring on four sessions. Recorded because it was reported;
* **`n_runs` is inverted** (0.37): real abilities produce FEWER contiguous
  detection runs than false positives, which fits objects that persist against
  fragments that flicker.

`self_d_med` is inverted and real: 0.07 AUC on `79a706a7ce4c` says abilities sit
much closer to the player than false positives do, which is what "the player
cast it" should look like. It is only 2 of 4 consistent -- `d95cfad5693a` runs
the other way -- so it is a lead, not a feature.

What is NOT in here
-------------------
Shape and colour features need the patch pixels, not the series, so they need a
decode pass and are not in this bank. The saturation probe on 2026-09-04 found
colour is strongly present for some ability classes (median 78-84 against a
floor of 0-4) and absent for others, and INVERTED on `79a706a7ce4c` where the
negatives were more saturated than the positives -- so colour belongs here as a
per-class feature and never as a gate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import ability_series as asr                                          # noqa: E402
import minimap_dynamic as md                                          # noqa: E402

STORE = Path.home() / "reticle-store"
SERIES_LABELS = STORE / "series-labels"


def auc(pos, neg) -> float:
    """Mann-Whitney AUC. Threshold-free, so there is nothing here to overfit."""
    pos = np.asarray(pos, float)
    neg = np.asarray(neg, float)
    pos = pos[np.isfinite(pos)]
    neg = neg[np.isfinite(neg)]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    allv = np.concatenate([pos, neg])
    r = np.argsort(np.argsort(allv)).astype(float) + 1
    # average ranks over ties, else ties inflate or deflate depending on order
    order = np.argsort(allv)
    s = allv[order]
    i = 0
    rr = r.copy()
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        if j > i:
            rr[order[i:j + 1]] = np.mean(r[order[i:j + 1]])
        i = j + 1
    rp = rr[:len(pos)].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _runs(b):
    """(number of contiguous True runs, longest run) over a boolean series."""
    if not b.any():
        return 0, 0
    d = np.diff(np.concatenate([[0], b.astype(np.int8), [0]]))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return len(starts), int((ends - starts).max())


def features(sid):
    """name -> value per query, plus the labels. Every window is the query's own."""
    qs, t_ms, F = asr.load(sid, SERIES_LABELS)
    sd_lo, _ = md.load_noise(sid)
    out: dict[str, list] = {}
    y_true, keep = [], []

    for i, q in enumerate(qs):
        if q.get("uncertain"):
            continue
        lo, hi = int(F["win_lo"][i]), int(F["win_hi"][i])
        if hi - lo < 4:
            continue
        sl = slice(lo, hi)
        dark = F["dark"][i, sl].astype(float)
        det = F["detect"][i, sl]
        cone = F["cone"][i, sl]
        gmax, gmin = F["g_max"][i, sl].astype(float), F["g_min"][i, sl].astype(float)
        ok = F["cone_ok"][sl]
        sdv = None
        if sd_lo is not None:
            yy, xx = int(q["y"]), int(q["x"])
            if 0 <= yy < sd_lo.shape[0] and 0 <= xx < sd_lo.shape[1]:
                sdv = max(float(sd_lo[yy, xx]), md.SD_FLOOR)

        f: dict[str, float] = {}
        f["dark_p90"] = float(np.percentile(dark, 90))
        f["dark_med"] = float(np.median(dark))
        f["dark_max"] = float(dark.max())
        f["dark_z_p90"] = f["dark_p90"] / sdv if sdv else float("nan")
        f["detect_frac"] = float(det.mean())

        idx = np.flatnonzero(det)
        if len(idx):
            span = idx[-1] - idx[0] + 1
            f["life_frac"] = span / len(det)
            f["persist"] = float(det[idx[0]:idx[-1] + 1].mean())
        else:
            f["life_frac"] = 0.0
            f["persist"] = 0.0
        n_runs, longest = _runs(det)
        f["n_runs"] = float(n_runs)
        f["longest_run"] = float(longest) / len(det)

        d1 = np.diff(dark)
        f["onset_step"] = float(d1.max()) if len(d1) else 0.0
        f["offset_step"] = float(-d1.min()) if len(d1) else 0.0
        f["dark_tvar"] = float(dark.std())
        f["patch_range"] = float(np.median(gmax - gmin))
        f["patch_range_sd"] = float((gmax - gmin).std())

        if len(dark) > 2 and dark.std() > 0:
            a = dark - dark.mean()
            f["autocorr1"] = float((a[:-1] @ a[1:]) / (a @ a))
        else:
            f["autocorr1"] = float("nan")

        # nan-aware: self_d is nan on frames with no self icon drawn, and a
        # plain median over a window containing one nan is nan for the whole
        # query -- which silently deleted this feature on every session.
        sdq = F["self_d"][i, sl]
        fin = sdq[np.isfinite(sdq)]
        f["self_d_med"] = float(np.median(fin)) if len(fin) else float("nan")
        f["self_d_min"] = float(fin.min()) if len(fin) else float("nan")

        c = cone & ok
        nc = (~cone) & ok
        f["cone_frac"] = float(c.mean())
        # The two-factor conditional. Plain correlation with the cone cannot
        # separate a crack from a device that is only VISIBLE when lit; the
        # difference between them is whether being lit predicts detection.
        f["cone_cond"] = (float(det[c].mean()) - float(det[nc].mean())
                          if c.sum() >= 3 and nc.sum() >= 3 else float("nan"))
        f["dark_lit_gap"] = (float(dark[c].mean()) - float(dark[nc].mean())
                             if c.sum() >= 3 and nc.sum() >= 3 else float("nan"))

        for k, v in f.items():
            out.setdefault(k, []).append(v)
        y_true.append(bool(q.get("true")))
        keep.append(i)

    return {k: np.array(v, float) for k, v in out.items()}, np.array(y_true, bool)


def gate(per, ys, keys, signs):
    """Leave-one-SESSION-out precision/recall for an AND of per-feature thresholds.

    The threshold is picked on the other sessions and applied unseen, because a
    threshold picked on the session it is scored on is the ranked corpus exactly.
    Youden's J on the training sessions, which does not need a cost ratio.
    """
    tp = fp = fn = 0
    rows = []
    for held in per:
        cuts = []
        for k, sg in zip(keys, signs):
            tr_v = np.concatenate([per[s][k] * sg for s in per if s != held])
            tr_y = np.concatenate([ys[s] for s in per if s != held])
            m = np.isfinite(tr_v)
            tr_v, tr_y = tr_v[m], tr_y[m]
            best, bj = None, -2.0
            for c in np.unique(tr_v):
                pred = tr_v >= c
                if tr_y.sum() == 0 or (~tr_y).sum() == 0:
                    continue
                j = pred[tr_y].mean() - pred[~tr_y].mean()
                if j > bj:
                    best, bj = float(c), j
            cuts.append(best)
        v = np.ones(len(ys[held]), bool)
        for k, sg, c in zip(keys, signs, cuts):
            x = per[held][k] * sg
            v &= np.where(np.isfinite(x), x >= c, False)
        y = ys[held]
        t, f, n = int((v & y).sum()), int((v & ~y).sum()), int((~v & y).sum())
        tp += t
        fp += f
        fn += n
        rows.append((held, t, f, n, int(y.sum())))
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return prec, rec, rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-auc", type=float, default=0.0,
                    help="only print features reaching this |AUC-0.5|+0.5 pooled")
    ap.add_argument("--gate", action="store_true",
                    help="leave-one-session-out precision/recall for feature gates")
    a = ap.parse_args()

    sids = sorted(p.stem for p in SERIES_LABELS.glob("*.npz"))
    per, ys, names = {}, {}, None
    for sid in sids:
        try:
            f, y = features(sid)
        except Exception as e:  # noqa: BLE001
            print(f"{sid}: SKIPPED ({e})")
            continue
        if y.sum() == 0 or (~y).sum() == 0:
            print(f"{sid}: no both-class labels ({int(y.sum())} pos / {int((~y).sum())} neg)")
            continue
        per[sid], ys[sid] = f, y
        names = sorted(f) if names is None else names

    if not per:
        print("nothing to score")
        return 1

    print("AUC per session, then pooled. 0.50 is nothing; >0.5 means the feature is")
    print("HIGHER on real abilities. n = positives/negatives.\n")
    hdr = f"{'feature':<16}" + "".join(f"{s[:6]:>9}" for s in per) + f"{'POOLED':>9}{'  consistent':>13}"
    print(hdr)
    print(f"{'n pos/neg':<16}" + "".join(f"{str(int(ys[s].sum()))+'/'+str(int((~ys[s]).sum())):>9}"
                                        for s in per) + "")
    print("-" * len(hdr))

    rank = []
    for k in names:
        row, pool_p, pool_n = [], [], []
        for s in per:
            v, y = per[s][k], ys[s]
            row.append(auc(v[y], v[~y]))
            pool_p.append(v[y])
            pool_n.append(v[~y])
        pooled = auc(np.concatenate(pool_p), np.concatenate(pool_n))
        good = [r for r in row if np.isfinite(r)]
        # "consistent" = how many sessions land on the same side as the pooled sign
        side = 1 if pooled >= 0.5 else -1
        cons = sum(1 for r in good if (1 if r >= 0.5 else -1) == side and abs(r - 0.5) > 0.1)
        rank.append((abs(pooled - 0.5), cons, k, row, pooled, len(good)))

    for _, cons, k, row, pooled, ngood in sorted(rank, reverse=True):
        if abs(pooled - 0.5) + 0.5 < a.min_auc:
            continue
        print(f"{k:<16}" + "".join(f"{r:9.2f}" if np.isfinite(r) else "        -" for r in row)
              + f"{pooled:9.2f}" + f"{cons:>8}/{ngood}")

    print("\nRead the last column first. A pooled AUC with only one or two sessions")
    print("agreeing is the ranked-corpus failure in miniature -- it means one")
    print("population is carrying the figure.")

    if a.gate:
        # Sign: +1 where real abilities score HIGHER, -1 where they score lower.
        cands = [
            (["patch_range"], [1]),
            (["autocorr1"], [1]),
            (["dark_med"], [1]),
            (["self_d_med"], [-1]),
            (["patch_range", "autocorr1"], [1, 1]),
            (["patch_range", "self_d_med"], [1, -1]),
            (["patch_range", "autocorr1", "self_d_med"], [1, 1, -1]),
            (["patch_range", "autocorr1", "dark_med"], [1, 1, 1]),
        ]
        print("\n=== leave-one-SESSION-out gate: threshold fitted on the other three ===")
        print(f"{'gate':<44}{'prec':>7}{'recall':>8}   per-session tp/fp/fn")
        for keys, signs in cands:
            p, r, rows = gate(per, ys, keys, signs)
            detail = " ".join(f"{s[:6]}:{t}/{f}/{n}" for s, t, f, n, _ in rows)
            print(f"{' AND '.join(keys):<44}{p:7.2f}{r:8.2f}   {detail}")
        print("\nBaseline: marking EVERYTHING a positive gives precision"
              f" {sum(int(ys[s].sum()) for s in per) / sum(len(ys[s]) for s in per):.2f}"
              " at recall 1.00.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
