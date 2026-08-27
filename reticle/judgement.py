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
import time
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



# --------------------------------------------------------------------------
# stake: what it costs to be wrong, which is not the same as how often you are
# --------------------------------------------------------------------------
#
# Grant: predicting a file's word count has a different salience to predicting
# whether your ontology was correct. It does, and the first attempt to show it
# ran the WRONG TEST -- accuracy by level, which found nothing (value 0.55,
# ontology 0.67) because accuracy was never the point. Stake is what it costs to
# be wrong, and cost was not in the log at all. That absence is the gap this
# closes.
#
# The evidence for the ordering is consequence, not error rate. Two wrong
# ontology claims from this log:
#
#     "the bomb sites are correctly classified"      -> sites were 93% VOID,
#                                                       the searchable mask broke
#     "the label class list is complete at six"      -> six labeller restarts
#
# against a wrong value claim from the same day, "plant rate lands 40-60%",
# whose cost was editing a number. Same log, same `wrong`, orders of magnitude
# apart.
#
#: LEVEL is a priori and nearly SYNTACTIC -- readable off the claim's grammar,
#: which is what stops it being quietly under-rated for claims about to fail.
LEVELS = {
    "value": "X is N -- a number, a count, a threshold. Wrong: one number is wrong",
    "mechanism": "X works because Y. Wrong: a class of approaches is wrong",
    "ontology": "X is a kind of Y. Wrong: every measurement in those categories "
                "is wrong, INCLUDING the ones that looked right",
    "instrument": "this tool measures X. Wrong: all data it produced is suspect",
}
LEVEL_WEIGHT = {"value": 1, "mechanism": 2, "ontology": 4, "instrument": 4}

#: COST is a posteriori, ordinal, and anchored to things that actually happened
#: here -- an absolute scale in minutes would be false precision and would not
#: survive comparison across sessions of different length.
COST = {
    "none": (0, "noted and moved on -- 'plant rate lands 40-60%'"),
    "minutes": (1, "a number requoted or an edit -- PLANT_MIN_MS=20s, 2 missed plants"),
    "hours": (2, "work built then retracted -- onset sampling"),
    "session": (3, "a session's direction wasted -- the searchable mask, derived five times"),
    "sessions": (4, "multiple sessions, or a SHIPPED number invalidated -- seeding "
                    "minimap_agent made a measured 93% circular"),
}


def record(claim, *, domain, confidence, level, outcome=None, rests_on=(),
           cost=None, retrospective=False, by="claude", log_path=None, **extra):
    """Append one prediction. `level` is required, and validated.

    Requiring `level` at write time is the whole point: it is cheap, it is
    syntactic, and it cannot be assigned after the outcome is known without
    that being visible in the file.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {sorted(LEVELS)}, got {level!r}")
    if cost is not None and cost not in COST:
        raise ValueError(f"cost must be one of {sorted(COST)}, got {cost!r}")
    row = {"when": time.strftime("%Y-%m-%d"), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "domain": domain, "claim": claim, "confidence": confidence,
           "outcome": outcome, "retrospective": retrospective,
           "level": level, "rests_on": list(rests_on), "cost": cost,
           "by": by, **extra}
    log = Path(log_path) if log_path else LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + chr(10))
    return row


def stake(row) -> float:
    """Raw stake for one row: level weight x (1 + things resting on it).

    Deliberately crude. It is a PRIOR to be replaced: once enough rows carry an
    observed `cost`, fit `level x rests_on -> cost` from history and use that
    instead, exactly as the calibration table replaced asking how confident I
    felt. Until then this is an ordering, not a measurement.
    """
    return LEVEL_WEIGHT.get(row.get("level", "value"), 1) * (1 + len(row.get("rests_on") or ()))


def stake_ranked(rows) -> list[tuple[float, float, dict]]:
    """(stake, percentile, row), highest first.

    Reported as a PERCENTILE WITHIN THIS LOG, never as an absolute. Grant's
    point, and it is the right resolution rather than a dodge: there is no
    universal unit of importance, and none is needed, because every decision
    this feeds -- what to check first, what to re-measure -- is a RANKING.
    Human status being relative is the same observation; comparison is cheap and
    well-defined where an absolute scale is neither.
    """
    scored = [(stake(r), r) for r in rows]
    if not scored:
        return []
    vals = sorted(v for v, _ in scored)
    out = []
    for v, r in scored:
        pct = sum(1 for x in vals if x <= v) / len(vals)
        out.append((v, pct, r))
    return sorted(out, key=lambda t: -t[0])


def by_level(rows) -> str:
    """Accuracy AND observed cost per level. The second column is the point."""
    seen = {}
    for r in rows:
        if r.get("outcome") in SCORED:
            seen.setdefault(r.get("level", "unlabelled"), []).append(r)
    if not seen:
        return "no levelled rows yet -- pass level= to judgement.record()"
    out = [f"{'level':<12} {'n':>4} {'acc':>6} {'gap':>7} {'mean cost':>10}  worst"]
    for lv in sorted(seen, key=lambda k: -LEVEL_WEIGHT.get(k, 0)):
        rs = seen[lv]
        right = sum(1 for r in rs if r["outcome"] == "right")
        mc = sum(float(r.get("confidence", 0)) for r in rs) / len(rs)
        costs = [COST[r["cost"]][0] for r in rs if r.get("cost") in COST]
        worst = max((r for r in rs if r.get("cost") in COST),
                    key=lambda r: COST[r["cost"]][0], default=None)
        acc = right / len(rs)
        cs = f"{sum(costs) / len(costs):.1f}" if costs else "--"
        out.append(f"{lv:<12} {len(rs):>4} {acc:>6.2f} {acc - mc:>+7.2f} {cs:>10}  "
                   f"{(worst['claim'][:44] if worst else '')}")
    out.append("")
    out.append("acc is NOT the interesting column. A wrong `value` claim costs a")
    out.append("requote; a wrong `ontology` claim invalidates every measurement")
    out.append("expressed in those categories, including the ones that looked right.")
    return chr(10).join(out)


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

    lv = by_level(rows)
    if "no levelled rows" not in lv:
        out += ["", "By LEVEL of claim -- what it costs to be wrong:", ""]
        out += ["  " + l for l in lv.splitlines()]
        top = [t for t in stake_ranked([r for r in rows if r.get("level")])
               if (t[2].get("rests_on") or [])][:5]
        if top:
            out += ["", "Highest stake (percentile within this log):"]
            for v, pct, r in top:
                out.append(f"  {v:5.1f}  p{pct * 100:3.0f}  [{r['level']:<10}] "
                           f"{r['claim'][:52]}")

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

    import tempfile
    tmp = Path(tempfile.gettempdir()) / "judgement-selftest.jsonl"
    if tmp.exists():
        tmp.unlink()
    record("a value claim", domain="t", confidence=0.7, level="value",
           outcome="wrong", cost="none", log_path=tmp)
    record("an ontology claim", domain="t", confidence=0.9, level="ontology",
           outcome="wrong", cost="sessions", rests_on=["a", "b"], log_path=tmp)
    got = load(tmp)
    assert len(got) == 2 and got[1]["level"] == "ontology", got
    assert stake(got[1]) > stake(got[0]), "ontology with 2 dependents must outrank a bare value claim"
    for bad in (dict(level="vibes"), dict(level="value", cost="ages")):
        try:
            record("x", domain="t", confidence=0.5, outcome="wrong",
                   log_path=tmp, **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {bad}")
    ranked = stake_ranked(got)
    assert ranked[0][2]["level"] == "ontology" and ranked[0][1] == 1.0, ranked
    tmp.unlink()
    print(f"  stake: ontology+2 deps = {stake(got[1]):.0f} vs bare value "
          f"= {stake(got[0]):.0f}; bad level and bad cost both refused")
    print("self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--levels", action="store_true",
                    help="only the by-level view")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.levels:
        print(by_level(load(Path(a.log) if a.log else None)))
        return 0
    print(report(load(Path(a.log) if a.log else None), a.domain))
    return 0


if __name__ == "__main__":
    sys.exit(main())
