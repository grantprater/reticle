"""Where my judgement is reliable, and when that has stopped being true.

    .\\.venv\\Scripts\\python.exe -m reticle.judgement
    .\\.venv\\Scripts\\python.exe -m reticle.judgement --domain minimap

What this is, and what it is not
-------------------------------
Grant asked for something resembling a model of intuition. This is the honest
half of that, and the naming matters: **intuition is a fast prior, and what makes
one usable is knowing where it holds.** A confident guess with an unknown error
rate is worth nothing; the same guess with a measured error rate is worth a
great deal, because you can decide whether to act on it or go and look. So this
does not model judgement. It models judgement's RELIABILITY, per domain, over
time -- which is the part that can actually be measured from
`notes/predictions.jsonl`.

Three questions, in increasing order of how hard they are to answer:

1. **How good is the judgement?** Accuracy per domain, and more importantly the
   CALIBRATION GAP -- accuracy minus mean stated confidence. Being right 60% of
   the time is fine; being right 60% of the time while claiming 0.9 is the
   defect, and it is a different defect from being wrong.
2. **Is the domain even predictable?** A domain whose outcomes ALTERNATE is
   noise: the thing being predicted is irreducible and more effort will not
   help. A domain whose outcomes CLUSTER has structure, and a run of wrongs is a
   model defect worth chasing. The runs test separates these, and the repo's
   own convention already says to do it by hand -- *repeat an observation to see
   whether the outcome varies; varies = irreducible, stop.*
3. **Has the regime changed?** This is the one Grant's intuition pointed at.
   Human memory over-weights emotionally volatile events, and the useful reading
   of that is not "novel" -- noise is maximally novel, which is exactly how
   onset-sampling failed -- but **"the rules just changed here."** A domain that
   went from 5% wrong to 40% wrong has had its assumptions lapse underneath it,
   and every expensive failure in this project has that shape: the death screen
   where `usable()` silently stopped applying, buy phase against live play, the
   halftime side swap, 4:2:0 chroma. Each looked like ordinary noise until
   somebody looked. **Sample where the error rate CHANGES, not where it is
   high** -- a stable 30% teaches nothing new, a jump to 30% is a boundary.

Why this can be trusted more than novelty sampling
--------------------------------------------------
Because it is defined on the MODEL's behaviour rather than the input's
strangeness. A maximally novel flicker moves no belief and scores nothing here;
a familiar-looking frame that broke a confident prediction scores highly. That
is the difference that made "go to the WRONG ones first" outperform every
sampling heuristic tried this session.

The honest limit: n is tiny
---------------------------
At the time of writing the whole log is a few dozen rows, and a per-domain
change point needs observations on BOTH sides of the split. This module refuses
rather than guesses: it reports `underpowered` whenever a side would fall below
`MIN_SIDE`, and it Bonferroni-corrects the change-point p-value for the number
of splits tested, because taking the best of many splits is a biased search and
an uncorrected p there would manufacture regime changes out of noise. **A tool
for detecting when a model has gone stale is worthless if it will invent one.**
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

STORE = Path.home() / "reticle-store"
LOG = STORE / "notes" / "predictions.jsonl"

#: A change point needs this many scored outcomes on each side. Below it the
#: split is not evidence, it is arithmetic.
MIN_SIDE = 5
#: Corrected p below this is reported as a regime change.
ALPHA = 0.05
#: |z| above this on the runs test is called clustered / alternating.
RUNS_Z = 1.64

SCORED = ("right", "wrong")


def load(path: Path | None = None) -> list[dict]:
    """Rows in file order, which is time order -- the log is append-only."""
    p = Path(path) if path else LOG
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact on [[a, b], [c, d]]. Exact, so small n is fine."""
    n = a + b + c + d
    if n == 0:
        return 1.0
    r1, r2, c1 = a + b, c + d, a + c

    def p(x: int) -> float:
        return (math.comb(r1, x) * math.comb(r2, c1 - x)) / math.comb(n, c1)

    lo, hi = max(0, c1 - r2), min(r1, c1)
    p0 = p(a)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= p0 + 1e-12))


def runs(outcomes: list[int]) -> tuple[int, float, float] | None:
    """Runs test. Returns (n_runs, expected, z); z<0 means CLUSTERED.

    Clustered outcomes mean the thing has structure and a run of wrongs is a
    model defect. Alternating outcomes mean the thing is irreducible, and the
    convention says to log it `aleatoric` and stop rather than tune.
    """
    n = len(outcomes)
    n1 = sum(outcomes)
    n0 = n - n1
    if n1 == 0 or n0 == 0 or n < 4:
        return None
    r = 1 + sum(1 for i in range(1, n) if outcomes[i] != outcomes[i - 1])
    exp = 2 * n1 * n0 / n + 1
    var = 2 * n1 * n0 * (2 * n1 * n0 - n) / (n * n * (n - 1))
    if var <= 0:
        return None
    return r, exp, (r - exp) / math.sqrt(var)


def change_point(outcomes: list[int], min_side: int = MIN_SIDE):
    """Best split of a 0/1 sequence, with the search corrected for.

    Returns None when underpowered. Otherwise a dict with the split index, the
    rates either side, the raw Fisher p and the Bonferroni-corrected p. Taking
    the best of many splits is a biased search, so the raw p is not reportable
    on its own -- correcting it is what stops this manufacturing regimes.
    """
    n = len(outcomes)
    splits = [k for k in range(min_side, n - min_side + 1)]
    if not splits:
        return None
    best = None
    for k in splits:
        lo, hi = outcomes[:k], outcomes[k:]
        a, b = sum(lo), len(lo) - sum(lo)
        c, d = sum(hi), len(hi) - sum(hi)
        p = _fisher(a, b, c, d)
        if best is None or p < best["p_raw"]:
            best = {"k": k, "p_raw": p,
                    "before": sum(lo) / len(lo), "after": sum(hi) / len(hi),
                    "n_before": len(lo), "n_after": len(hi)}
    best["n_splits"] = len(splits)
    best["p"] = min(1.0, best["p_raw"] * len(splits))
    best["changed"] = best["p"] <= ALPHA
    return best


def analyse(rows: list[dict], domain: str) -> dict:
    """Everything this module knows about one domain."""
    rs = [r for r in rows if r.get("domain") == domain]
    scored = [r for r in rs if r.get("outcome") in SCORED]
    o = [1 if r["outcome"] == "right" else 0 for r in scored]
    conf = [float(r.get("confidence", 0)) for r in scored]
    ct = len(rs) - len(scored)
    out = {
        "domain": domain, "n": len(rs), "n_scored": len(o),
        "cant_tell": ct / len(rs) if rs else 0.0,
        "acc": (sum(o) / len(o)) if o else None,
        "mean_conf": (sum(conf) / len(conf)) if conf else None,
        "last": rs[-1].get("when") if rs else None,
        "runs": runs(o),
        "change": change_point(o),
    }
    out["gap"] = (out["acc"] - out["mean_conf"]
                  if out["acc"] is not None and out["mean_conf"] is not None else None)
    return out


def verdict(a: dict) -> str:
    """One line saying what to DO about this domain."""
    if a["n_scored"] < 4:
        return "too few scored predictions to say anything"
    if a["change"] and a["change"]["changed"]:
        d = a["change"]
        arrow = "worse" if d["after"] < d["before"] else "better"
        return (f"REGIME CHANGE at #{d['k']}: {d['before']:.0%} -> {d['after']:.0%} "
                f"({arrow}); the old calibration is stale, re-measure before trusting it")
    rt = a["runs"]
    if rt and rt[2] >= RUNS_Z:
        return ("outcomes ALTERNATE more than chance -- looks irreducible; "
                "log it aleatoric and stop tuning")
    if rt and rt[2] <= -RUNS_Z:
        return ("outcomes CLUSTER -- there is structure here, and a run of "
                "wrongs is a model defect worth chasing")
    if a["gap"] is not None and a["gap"] <= -0.25:
        return f"OVERCONFIDENT by {abs(a['gap']):.2f} -- fix the confidence, not the resolution"
    if a["gap"] is not None and a["gap"] >= 0.25:
        return f"UNDERCONFIDENT by {a['gap']:.2f} -- claim more, or ask finer questions"
    return "calibrated, no regime change detected"


def report(rows: list[dict], only: str | None = None) -> str:
    if not rows:
        return "no predictions log yet"
    doms = sorted({r.get("domain", "?") for r in rows})
    if only:
        doms = [d for d in doms if d == only]
        if not doms:
            return f"no rows for domain {only!r}"

    out = [f"{len(rows)} predictions across {len(doms)} domains"
           f"   (change point needs {MIN_SIDE} scored either side)", ""]
    out.append(f"{'domain':<12} {'n':>4} {'acc':>6} {'conf':>6} {'gap':>6} "
               f"{'ct':>5} {'runs z':>7}  last")
    for d in doms:
        a = analyse(rows, d)
        acc = f"{a['acc']:.2f}" if a["acc"] is not None else "--"
        mc = f"{a['mean_conf']:.2f}" if a["mean_conf"] is not None else "--"
        gap = f"{a['gap']:+.2f}" if a["gap"] is not None else "--"
        rz = f"{a['runs'][2]:+.2f}" if a["runs"] else "--"
        out.append(f"{d:<12} {a['n']:>4} {acc:>6} {mc:>6} {gap:>6} "
                   f"{a['cant_tell']:>4.0%} {rz:>7}  {a['last'] or '--'}")

    out += ["", "Verdicts -- what to do about each:"]
    for d in doms:
        a = analyse(rows, d)
        out.append(f"  {d:<12} {verdict(a)}")
        c = a["change"]
        if c and not c["changed"] and a["n_scored"] >= 2 * MIN_SIDE:
            out.append(f"  {'':<12}   best split #{c['k']} "
                       f"{c['before']:.0%}->{c['after']:.0%} "
                       f"p={c['p']:.2f} after correcting for {c['n_splits']} splits "
                       f"-- not evidence")
        elif not c:
            out.append(f"  {'':<12}   underpowered for a change point "
                       f"({a['n_scored']} scored, need {2 * MIN_SIDE})")

    out += ["",
            "gap = accuracy minus mean stated confidence; negative is overconfidence.",
            "runs z: negative = outcomes cluster (structure, chase the run of wrongs),",
            "        positive = outcomes alternate (irreducible, stop tuning).",
            "A regime change means the old calibration no longer describes this domain,",
            "which is worth more than a high error rate: a stable 30% teaches nothing new."]
    return "\n".join(out)


def _self_test() -> int:
    """A change detector that never fires is as useless as one that always does.

    Three cases, and both error directions matter:

    * a REAL change must be caught -- otherwise this is a null-returning stub;
    * pure noise must not manufacture one, at roughly the nominal rate. This is
      the check the Bonferroni correction exists for: without it, taking the
      best of many splits finds a "regime change" in coin flips constantly;
    * too little data must return None rather than a guess.
    """
    import random

    real = [1] * 15 + [0] * 15
    c = change_point(real)
    assert c and c["changed"], c
    assert abs(c["k"] - 15) <= 2, c
    print(f"  real change (15 right then 15 wrong): caught at #{c['k']}, "
          f"{c['before']:.0%}->{c['after']:.0%}, p={c['p']:.4f}")

    rng = random.Random(4)
    trials, fired = 2000, 0
    raw_fired = 0
    for _ in range(trials):
        seq = [rng.randint(0, 1) for _ in range(30)]
        cc = change_point(seq)
        if cc and cc["changed"]:
            fired += 1
        if cc and cc["p_raw"] <= ALPHA:
            raw_fired += 1
    print(f"  pure noise n=30, {trials} trials: corrected fires "
          f"{fired / trials:.1%} (target <= {ALPHA:.0%}), "
          f"UNcorrected would fire {raw_fired / trials:.1%}")
    assert fired / trials <= ALPHA, "false-positive rate above nominal"
    assert raw_fired > fired, "correction is doing nothing"

    assert change_point([1] * 4 + [0] * 4) is None
    print("  underpowered (n=8): returns None, as it must")

    r = runs([1, 0] * 10)
    assert r and r[2] > RUNS_Z, r
    r2 = runs([1] * 10 + [0] * 10)
    assert r2 and r2[2] < -RUNS_Z, r2
    print(f"  runs test: alternating z={r[2]:+.2f}, clustered z={r2[2]:+.2f}")
    print("self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    print(report(load(Path(a.log) if a.log else None), a.domain))
    return 0


if __name__ == "__main__":
    sys.exit(main())
