"""Sweep track-acceptance rules against dumped windows, without the video.

    .\\.venv\\Scripts\\python.exe prototypes\\enemy_teacher_sweep.py <dump.jsonl>...

`enemy_teacher.py --dump` writes every track in every labelled window with each
member's features. A full decode pass is 85 seconds per corpus, which is more
than enough to make sweeping against the video a bad habit -- so this reads the
dump, exactly as `segment` recomputes spans from stored L1 rather than reopening
the capture.

The first pass here is DIAGNOSTIC, not a sweep: the rule "accept a track if any
member passes the shipped gates" buys recall and halves precision, and the
question is what separates the tracks it wrongly accepts from the ones it
rightly does. Sweeping before knowing that is how two full parameter sweeps got
spent on two inert constants.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def body_box(px, py):
    return (px - 55, py - 25, px + 55, py + 135)


def hits(px, py, box):
    x, y, bw, bh = box[:4]
    bx0, by0, bx1, by1 = body_box(px, py)
    return not (x > bx1 or x + bw < bx0 or y > by1 or y + bh < by0)


def load(paths):
    wins = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                w = json.loads(line)
                w["src"] = Path(p).stem
                wins.append(w)
    return wins


def centre_member(tr, centre):
    for m in tr["members"]:
        if m["i"] == centre:
            return m
    return None


def stats(tr):
    """Candidate discriminators, all computed from the track as a whole."""
    g = [m for m in tr["members"] if m["gated"]]
    areas = [m["area_closed"] for m in tr["members"]]
    return {
        "len": tr["len"],
        "n_gated": len(g),
        "max_gated_area": max((m["area_closed"] for m in g), default=0.0),
        "max_area": max(areas, default=0.0),
        "max_bh": max((m["bh"] for m in tr["members"]), default=0.0),
        "min_top1": min((m["frag_top1"] for m in tr["members"]), default=1.0),
        "max_top_mean": max((m["top_mean"] for m in tr["members"]), default=0.0),
    }


def accept(tr, mintrack, min_gated, min_gated_area):
    if tr["len"] < mintrack:
        return False
    g = [m for m in tr["members"] if m["gated"]]
    if len(g) < min_gated:
        return False
    return max((m["area_closed"] for m in g), default=0.0) >= min_gated_area


def score(wins, rule):
    tp = fn = fp = 0
    for w in wins:
        dets = []
        for tr in w["tracks"]:
            if not rule(tr):
                continue
            m = centre_member(tr, w["centre"])
            if m is not None:
                dets.append(m["box"])
        players = [(m["x"], m["y"]) for m in w["marks"] if m["kind"] == "player"]
        others = [(m["x"], m["y"]) for m in w["marks"]
                  if m["kind"] in ("corpse", "deployable", "revealed")]
        used = set()
        for (px, py) in players:
            j = next((j for j, d in enumerate(dets)
                      if j not in used and hits(px, py, d)), None)
            if j is None:
                fn += 1
            else:
                tp += 1
                used.add(j)
        for (px, py) in others:
            j = next((j for j, d in enumerate(dets)
                      if j not in used and hits(px, py, d)), None)
            if j is not None:
                used.add(j)
        fp += len(dets) - len(used)
    return tp, fn, fp


def diagnose(wins):
    """Split accepted tracks by whether their centre member hits a player."""
    good, bad = [], []
    for w in wins:
        players = [(m["x"], m["y"]) for m in w["marks"] if m["kind"] == "player"]
        nontgt = [(m["x"], m["y"]) for m in w["marks"]
                  if m["kind"] in ("corpse", "deployable", "revealed")]
        for tr in w["tracks"]:
            if not accept(tr, 3, 1, 0.0):
                continue
            m = centre_member(tr, w["centre"])
            if m is None:
                continue
            s = stats(tr)
            if any(hits(px, py, m["box"]) for px, py in players):
                good.append(s)
            elif any(hits(px, py, m["box"]) for px, py in nontgt):
                continue                     # neither credited nor penalised
            else:
                bad.append(s)
    keys = ("len", "n_gated", "max_gated_area", "max_area", "max_bh",
            "min_top1", "max_top_mean")
    print(f"\naccepted tracks: {len(good)} hit a labelled enemy, {len(bad)} did not")
    print(f"  {'feature':16s} {'enemy median':>13s} {'other median':>13s} "
          f"{'separation':>11s}")
    for k in keys:
        a = np.array([s[k] for s in good], float)
        b = np.array([s[k] for s in bad], float)
        if not len(a) or not len(b):
            continue
        # Best achievable (kept enemies - kept others) over every cut on this
        # feature alone. The same statistic the eval's feature table used, so
        # the numbers are comparable to frag_top1's 49.2%.
        cuts = np.unique(np.concatenate([a, b]))
        best = max(max((a >= c).mean() - (b >= c).mean(),
                       (a <= c).mean() - (b <= c).mean()) for c in cuts)
        print(f"  {k:16s} {np.median(a):13.1f} {np.median(b):13.1f} "
              f"{best*100:10.1f}%")


FIT_KEYS = ("len", "n_gated", "max_gated_area", "max_area", "max_bh",
            "min_top1", "max_top_mean")


def _design(tr):
    s = stats(tr)
    v = [s[k] for k in FIT_KEYS]
    # Areas and heights span two orders of magnitude and a linear model in them
    # is dominated by the tail; the logs are what make the small end separable,
    # and the small end is where every remaining miss lives.
    return np.array(v + [np.log1p(s["max_gated_area"]), np.log1p(s["max_area"]),
                         np.log1p(s["max_bh"])], float)


def _irls(X, y, iters=60, lam=1.0):
    """Ridge-penalised logistic regression, closed form per iteration.

    No new dependency: the student has to run inside a four-dep project, so the
    fit does too. The intercept is left unpenalised.
    """
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        W = np.maximum(p * (1 - p), 1e-6)
        z = X @ b + (y - p) / W
        A = X.T @ (X * W[:, None]) + lam * np.eye(X.shape[1])
        A[-1, -1] -= lam
        b = np.linalg.solve(A, X.T @ (W * z))
    return b


def fit_and_test(wins, by_src):
    """Fit the track score on one map and score it on the OTHER.

    Cross-map is the only honest split available. Fitting and testing on the
    same corpus reports a best-cut-over-a-continuum on 46 enemies, and the eval
    docstring already records that some of its feature table is noise fitted to
    exactly that sample.
    """
    if len(by_src) < 2:
        print("\nneed two corpora to cross-validate; skipping the fit")
        return
    for tr_src in sorted(by_src):
        te_src = [s for s in sorted(by_src) if s != tr_src]
        train, test = by_src[tr_src], [w for s in te_src for w in by_src[s]]
        X, y = [], []
        for w in train:
            pl = [(m["x"], m["y"]) for m in w["marks"] if m["kind"] == "player"]
            nt = [(m["x"], m["y"]) for m in w["marks"]
                  if m["kind"] in ("corpse", "deployable", "revealed")]
            for tr in w["tracks"]:
                if not accept(tr, 3, 1, 0.0):
                    continue
                m = centre_member(tr, w["centre"])
                if m is None or any(hits(px, py, m["box"]) for px, py in nt):
                    continue
                X.append(_design(tr))
                y.append(int(any(hits(px, py, m["box"]) for px, py in pl)))
        X, y = np.array(X), np.array(y, float)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        Xn = np.hstack([(X - mu) / sd, np.ones((len(X), 1))])
        b = _irls(Xn, y)

        def sc(tr):
            return float(np.append((_design(tr) - mu) / sd, 1.0) @ b)

        allsc = sorted(sc(tr) for w in test for tr in w["tracks"]
                       if accept(tr, 3, 1, 0.0))
        print(f"\n  fit on {tr_src}, test on {'+'.join(te_src)} "
              f"({len(X)} train tracks, {int(y.sum())} positive)")
        print(f"    {'cut':>6s}  {'TP':>4s} {'FN':>4s} {'FP':>5s}   "
              f"{'recall':>7s} {'prec':>7s}")
        for q in (0, 10, 20, 30, 40, 50, 60, 70, 80):
            c = allsc[int(q / 100 * (len(allsc) - 1))] if allsc else 0.0
            tp, fn, fp = score(test, lambda tr, c=c: accept(tr, 3, 1, 0.0) and sc(tr) >= c)
            print(f"    p{q:>5d}  {tp:4d} {fn:4d} {fp:5d}   "
                  f"{tp/max(tp+fn,1)*100:6.1f}% {tp/max(tp+fp,1)*100:6.1f}%")


def floor_sweep(wins, by_src):
    """How far can `AREA` come down with persistence as the safety net?

    This is the README's standing "start here", and it has never been measured:
    `track_filter()` at len>=3 costs no recall and removes 27% of false
    positives, so it looks like exactly the net a lower floor needs. The pairing
    was measured separately and never together.

    Approximated from the dump rather than re-proposed: a track is accepted if
    it contains a shipped-quality member (the safety net) and its centre member
    clears `floor` (the lowered threshold). Linking still used every blob down
    to area 8, so this is a slight over-estimate of what re-proposing at
    `floor` would link -- it can only flatter the lower floors, which is the
    safe direction for a result that comes out negative.
    """
    print("\nAREA floor with persistence as the net (shipped floor is 120)")
    for src in sorted(by_src) + (["ALL"] if len(by_src) > 1 else []):
        ws = wins if src == "ALL" else by_src[src]
        print(f"\n  --- {src} ---")
        print(f"    {'floor':>6s}  {'TP':>4s} {'FN':>4s} {'FP':>5s}   "
              f"{'recall':>7s} {'prec':>7s}")
        for floor in (8, 20, 40, 60, 80, 100, 120, 160):
            def rule(tr, floor=floor):
                if not accept(tr, 3, 1, 0.0):
                    return False
                m = centre_member(tr, tr["_centre"])
                return m is not None and m["area_closed"] >= floor
            for w in ws:                       # carry the centre into the rule
                for tr in w["tracks"]:
                    tr["_centre"] = w["centre"]
            tp, fn, fp = score(ws, rule)
            print(f"    {floor:6d}  {tp:4d} {fn:4d} {fp:5d}   "
                  f"{tp/max(tp+fn,1)*100:6.1f}% {tp/max(tp+fp,1)*100:6.1f}%")


BLOB_KEYS = ("area_raw", "area_closed", "bw", "bh", "aspect",
             "frag_top1", "fragments", "frag_valid",
             "hue_axis", "sat_med", "ast_med", "top_mean", "top_max",
             "hollow_frac", "hollow_valid", "seal21")


def _blob_design(m):
    v = [m[k] for k in BLOB_KEYS]
    # Size spans two orders of magnitude; the logs are what let the small end
    # separate, and the small end is where every remaining miss lives.
    return np.array(v + [np.log1p(m["area_raw"]), np.log1p(m["area_closed"]),
                         np.log1p(m["bh"]), np.log1p(m["bw"])], float)


def blob_fit(wins, by_src, persist=True):
    """Replace the AND-chain of gates with ONE calibrated score per blob.

    This is the actual proposition. The shipped detector is a conjunction: a
    blob with textbook hue, textbook frag_top1 and textbook aspect still dies at
    `AREA >= 120`, because every gate is an independent veto. A score lets the
    other evidence speak for it -- and lets a 40 px orange scenery fragment die
    where a 40 px blob with a textbook rim survives, which no single lowered
    floor can do.

    Fitted on one map and scored on the other. With 46 and 65 enemies, a
    same-corpus number would be a best-cut-over-a-continuum and worth nothing.
    """
    if len(by_src) < 2:
        print("\nneed two corpora to cross-validate; skipping")
        return
    print(f"\nblob-level fitted score{' + persistence len>=3' if persist else ''}, "
          f"cross-map")
    for tr_src in sorted(by_src):
        te_src = [s for s in sorted(by_src) if s != tr_src]
        train, test = by_src[tr_src], [w for s in te_src for w in by_src[s]]
        X, y = [], []
        for w in train:
            pl = [(m["x"], m["y"]) for m in w["marks"] if m["kind"] == "player"]
            nt = [(m["x"], m["y"]) for m in w["marks"]
                  if m["kind"] in ("corpse", "deployable", "revealed")]
            for tr in w["tracks"]:
                if persist and tr["len"] < 3:
                    continue
                m = centre_member(tr, w["centre"])
                if m is None or any(hits(px, py, m["box"]) for px, py in nt):
                    continue
                X.append(_blob_design(m))
                y.append(int(any(hits(px, py, m["box"]) for px, py in pl)))
        X, y = np.array(X), np.array(y, float)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        b = _irls(np.hstack([(X - mu) / sd, np.ones((len(X), 1))]), y)

        def sc(m):
            return float(np.append((_blob_design(m) - mu) / sd, 1.0) @ b)

        def rule(tr, cut):
            if persist and tr["len"] < 3:
                return False
            m = centre_member(tr, tr["_centre"])
            return m is not None and sc(m) >= cut
        for w in test:
            for tr in w["tracks"]:
                tr["_centre"] = w["centre"]
        allsc = sorted(sc(centre_member(tr, w["centre"])) for w in test
                       for tr in w["tracks"]
                       if centre_member(tr, w["centre"]) is not None
                       and not (persist and tr["len"] < 3))
        print(f"\n  fit on {tr_src}, test on {'+'.join(te_src)} "
              f"({len(X)} train blobs, {int(y.sum())} positive)")
        print(f"    {'cut':>6s}  {'TP':>4s} {'FN':>4s} {'FP':>5s}   "
              f"{'recall':>7s} {'prec':>7s}")
        for q in (0, 20, 40, 55, 65, 75, 82, 88, 93):
            c = allsc[int(q / 100 * (len(allsc) - 1))] if allsc else 0.0
            tp, fn, fp = score(test, lambda tr, c=c: rule(tr, c))
            print(f"    p{q:>5d}  {tp:4d} {fn:4d} {fp:5d}   "
                  f"{tp/max(tp+fn,1)*100:6.1f}% {tp/max(tp+fp,1)*100:6.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dumps", nargs="+")
    ap.add_argument("--blob", action="store_true", help="blob-level fitted score")
    ap.add_argument("--fit", action="store_true", help="cross-map fitted score")
    ap.add_argument("--floor", action="store_true", help="sweep the AREA floor")
    args = ap.parse_args()
    wins = load(args.dumps)
    by_src = {}
    for w in wins:
        by_src.setdefault(w["src"], []).append(w)
    print(f"{len(wins)} windows from {', '.join(sorted(by_src))}")

    diagnose(wins)

    print("\nrule sweep (mintrack / min gated members / min gated area)")
    for src in sorted(by_src) + ["ALL"]:
        ws = wins if src == "ALL" else by_src[src]
        print(f"\n  --- {src} ---")
        print(f"    {'rule':>18s}  {'TP':>4s} {'FN':>4s} {'FP':>5s}   "
              f"{'recall':>7s} {'prec':>7s}")
        for mt, mg, ma in ((3, 1, 0), (3, 1, 200), (3, 1, 400), (3, 1, 800),
                           (3, 2, 0), (3, 2, 200), (3, 2, 400), (3, 2, 800),
                           (3, 3, 400), (5, 2, 400), (5, 3, 400)):
            tp, fn, fp = score(ws, lambda tr, mt=mt, mg=mg, ma=ma: accept(tr, mt, mg, ma))
            print(f"    {f'{mt}/{mg}/{ma}':>18s}  {tp:4d} {fn:4d} {fp:5d}   "
                  f"{tp/max(tp+fn,1)*100:6.1f}% {tp/max(tp+fp,1)*100:6.1f}%")

    if args.floor:
        floor_sweep(wins, by_src)
    if args.blob:
        blob_fit(wins, by_src)
    if args.fit:
        print("\nfitted track score, cross-map")
        fit_and_test(wins, by_src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
