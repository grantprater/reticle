r"""Per-source likelihood ratios for killfeed portrait scores.

    .\.venv\Scripts\python.exe prototypes\portrait_likelihood.py collect
    .\.venv\Scripts\python.exe prototypes\portrait_likelihood.py fit
    .\.venv\Scripts\python.exe prototypes\portrait_likelihood.py evaluate [--tau 0.9]

A portrait score is a histogram intersection against one of two reference
sources: the official agent art (`gallery`) or this session's own portraits of
deaths another channel named (`portrait_exemplars`). The two sit on different
scales, so comparing raw scores across sources lets a clean exemplar of one
agent outbid weak art of another (`exemplar-source-mismatch`).

`collect` reruns death adjudication in memory under the wired rule (E0) over
the 19 sessions with a stored lineup and keeps every followed view of an entry
role that the reference channels (`reliability.REFERENCE_CHANNELS`) name
without depending on another verdict and without disagreeing among
themselves. It drops every entity the player labelled in
`feed_portrait_uniform`: those labels are the held-out test. For each view it
stores the art score and the best exemplar score (never the entry's own) for
every agent the side admits. It also records E0's disagreements.

`fit` estimates, per source, the same-agent and different-agent score
distributions and a linear log likelihood ratio: two Gaussians with a common
within-class spread, per-agent means shrunk toward the pooled mean by
`SHRINK` entities. Each view is weighted by one over its entity's views, so a
long-followed entry counts once. `--exclude` leaves one session out.

`evaluate` replaces the raw-score margin with a posterior over the admitted
candidates (uniform prior; posterior of A = LR_A / sum LR): art alone first;
where art refuses, each candidate takes the better of its art and exemplar
LLR, and a name an exemplar decided depends on the exemplar's death. A name
needs posterior >= tau and a named, non-rival best. Calibration is refitted
leaving the scored session out. It scores the 146 labels and the corpus
disagreements against E0. Nothing is written but the prototype's own analysis
files. Predictions and outcome: `portrait-likelihood-calibration` in the
store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.adjudication import death as D  # noqa: E402
from reticle.adjudication import identity as I  # noqa: E402
from reticle.adjudication.reliability import REFERENCE_CHANNELS  # noqa: E402
from reticle.killfeed import KILLFEED_PORTRAIT_VERSION  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.store import Store  # noqa: E402

import label_feed_portraits as lfp  # noqa: E402

SIDS = ("043bafca271a 223d636bf8d2 3694746e4e54 5822b6646448 587c15b07779 59c70f1ef720 "
        "7010b3d62460 75a55a296d3b 96aa1ae9b96f 9acf02f98283 a06f04a0059f a1a995e6b19b "
        "b3b9defb6fd7 b7d24102a6f6 bdfdcf009dba bfad2778a372 c40d950031bb e37fdeca944f "
        "ff636d173b07").split()
STORE = Store()
ROWS = STORE.root / "analysis" / "portrait_likelihood_rows.json"
SHRINK = 10.0
SOURCES = ("art", "ex")


def labels():
    meta = {m["entity_id"]: m for m in json.loads(str(np.load(lfp.UNIFORM_PREP)["meta"]))}
    labs = {r["key"]: r["answer"] for r in lfp._labels(lfp.UNIFORM_KIND).values()
            if r["key"] in meta and not r["uncertain"] and r["class"] != "not_portrait"}
    return meta, labs


def adjudicate(sid, gallery):
    man = STORE.read_manifest(sid)
    date = man["ingested_at"][:10]
    portraits = STORE.read_events("killfeed_portrait", sid)
    res = D.adjudicate_session_deaths(
        sid, STORE.read_rounds(sid, date).to_pylist(), STORE.read_hud(sid, date),
        STORE.read_roster(sid, date), portraits, STORE.read_events("scoreboard", sid),
        load_lineup(sid, STORE.root), gallery, source_version=KILLFEED_PORTRAIT_VERSION,
        second_life=D.stored_second_life(portraits, KILLFEED_PORTRAIT_VERSION),
        weapon_observations=STORE.read_events("killfeed_weapon", sid))
    return res, portraits


def outcomes(sid, res):
    """Every verdict's agent and the disagreements, keyed by entity."""
    got, dis = {}, {}
    for r in res["rounds"]:
        for v in r["verdicts"]:
            for key in ("identity", "killer_identity"):
                ver = v.metadata.get(key) or {}
                if not ver.get("entity_id"):
                    continue
                got[ver["entity_id"]] = ver.get("agent")
                if ver.get("status") == "disagreement":
                    dis[ver["entity_id"]] = {c: row.get("agent") for c, row in ver["by_channel"].items()
                                             if row.get("agent")}
    return got, dis


def source_scores(view, admitted, gallery, exemplars, exclude):
    """Each source's best shift-penalised score for every admitted agent."""
    art = I._portrait_scores(view.get("composition"), admitted, gallery,
                             shifts=view.get("shifts"))
    ex = I._portrait_scores(view.get("composition"), admitted, {}, exemplars, exclude,
                            shifts=view.get("shifts"))
    n = Counter(x["agent"] for x in exemplars if x.get("entry_t_ms") != exclude)
    return art, ex, {a: n.get(a, 0) for a in admitted}


def collect_rows():
    meta, _ = labels()
    gallery = I.load_identity_gallery(STORE.root)
    rows, dis_all, t0 = [], {}, time.time()
    for sid in SIDS:
        res, portraits = adjudicate(sid, gallery)
        by_key = {p["observation_key"]: p for p in portraits if p.get("kind") == "portrait_observation"}
        lineup = load_lineup(sid, STORE.root)
        entries = [e for x in res["rounds"] for e in x["entries"]]
        verdicts = [v for x in res["rounds"] for v in x["verdicts"]]
        exemplars = D.portrait_exemplars(verdicts, entries)
        _, dis = outcomes(sid, res)
        dis_all.update(dis)
        for e, v in zip(entries, verdicts):
            for key, ck in (("identity", "claim"), ("killer_identity", "killer_claim")):
                ver, claim = v.metadata.get(key) or {}, e.get(ck) or {}
                if not ver.get("entity_id") or ver["entity_id"] in meta:
                    continue
                refs = {c["agent"] for c in ver.get("claims", []) if c["channel"] in REFERENCE_CHANNELS
                        and c["agent"] and not c.get("depends_on")}
                if len(refs) != 1:
                    continue
                truth = next(iter(refs))
                ev = claim.get("evidence") or {}
                split = I.side_candidates(lineup.get("sides", {}).get(ev.get("side"), []))
                admitted = sorted({a for a in split["named"] + split["rivals"] if a})
                if truth not in admitted:
                    continue
                views = [by_key.get(o.get("observation_key")) for o in ev.get("observations", [])]
                views = [p for p in views if p is not None and p.get("composition") is not None]
                for p in views:
                    art, ex, n = source_scores(p, admitted, gallery, exemplars, float(e["t_ms"]))
                    rows.append({"session_id": sid, "entity_id": ver["entity_id"], "truth": truth,
                                 "channels": sorted({c["channel"] for c in ver["claims"]
                                                     if c["channel"] in REFERENCE_CHANNELS and c["agent"]}),
                                 "views": len(views), "admitted": admitted, "art": art, "ex": ex, "ex_n": n,
                                 "status": ver.get("status"), "said": ver.get("agent")})
        print(sid, len(rows), f"{time.time() - t0:.0f} s", flush=True)
    ROWS.write_text(json.dumps({"rows": rows, "e0_disagreements": dis_all}))
    print("rows", len(rows), "entities", len({r["entity_id"] for r in rows}))


def pairs(rows, source, exclude=None):
    """(agent, score, same, weight) per scored (view, candidate)."""
    out = []
    for r in rows:
        if r["session_id"] == exclude:
            continue
        for agent, s in r[source].items():
            out.append((agent, float(s), agent == r["truth"], 1.0 / r["views"]))
    return out


def fit(rows, exclude=None):
    """Per source: pooled and per-agent class means, a common spread."""
    table = {}
    for source in SOURCES:
        ps = pairs(rows, source, exclude)
        cls = {}
        for same in (True, False):
            sel = [(a, s, w) for a, s, t, w in ps if t == same]
            w = np.array([x[2] for x in sel]); s = np.array([x[1] for x in sel])
            mu = float((w * s).sum() / w.sum())
            per = defaultdict(lambda: [0.0, 0.0])
            for a, x, wt in sel:
                per[a][0] += wt * x; per[a][1] += wt
            agents = {a: {"n": n, "mean": (sx + SHRINK * mu) / (n + SHRINK), "raw": sx / n}
                      for a, (sx, n) in per.items()}
            var = float((w * (s - np.array([agents[a]["mean"] for a, _, _ in sel])) ** 2).sum() / w.sum())
            cls[same] = {"mu": mu, "var": var, "n": float(w.sum()), "agents": agents,
                         "median": float(np.median(s)) if s.size else math.nan}
        sd2 = (cls[True]["var"] * cls[True]["n"] + cls[False]["var"] * cls[False]["n"]) / (
            cls[True]["n"] + cls[False]["n"])
        table[source] = {"same": cls[True], "diff": cls[False], "var": sd2}
    return table


def llr(table, source, agent, score):
    t = table[source]
    ms = t["same"]["agents"].get(agent, {}).get("mean", t["same"]["mu"])
    md = t["diff"]["agents"].get(agent, {}).get("mean", t["diff"]["mu"])
    return (ms - md) / t["var"] * (score - (ms + md) / 2.0)


def posterior(llrs):
    if not llrs:
        return {}
    top = max(llrs.values())
    z = {a: math.exp(v - top) for a, v in llrs.items()}
    s = sum(z.values())
    return {a: v / s for a, v in z.items()}


def report(rows):
    table = fit(rows)
    for source in SOURCES:
        t = table[source]
        print(f"{source}: same median {t['same']['median']:.3f} mean {t['same']['mu']:.3f} "
              f"(n {t['same']['n']:.0f} entities) diff median {t['diff']['median']:.3f} mean {t['diff']['mu']:.3f} "
              f"common sd {math.sqrt(t['var']):.3f}")
        agents = sorted(t["same"]["agents"].items(), key=lambda kv: kv[1]["raw"])
        print("   same-agent raw mean by agent (n):",
              ", ".join(f"{a} {v['raw']:.2f} ({v['n']:.0f})" for a, v in agents))
        agents = sorted(t["diff"]["agents"].items(), key=lambda kv: -kv[1]["raw"])
        print("   diff-agent raw mean by agent (n):",
              ", ".join(f"{a} {v['raw']:.2f} ({v['n']:.0f})" for a, v in agents[:10]))
        for same in (True, False):
            s = np.array([x[1] for x in pairs(rows, source) if x[2] == same])
            print(f"   {'same' if same else 'diff'} quantiles 10/25/50/75/90:",
                  np.round(np.quantile(s, [.1, .25, .5, .75, .9]), 3).tolist())
    # Per-agent medians of same-agent art score (P2), unweighted over views.
    by = defaultdict(list)
    for a, s, same, _ in pairs(rows, "art"):
        if same:
            by[a].append(s)
    print("art same-agent median by agent:",
          ", ".join(f"{a} {np.median(v):.3f} ({len(v)})" for a, v in sorted(by.items(), key=lambda kv: np.median(kv[1]))))
    # Pooled vs per-agent: held-out view accuracy of the top-LLR candidate.
    for per_agent in (False, True):
        right = total = 0
        for sid in SIDS:
            tab = fit(rows, exclude=sid)
            if not per_agent:
                pooled(tab)
            for r in (r for r in rows if r["session_id"] == sid):
                l = {a: llr(tab, "art", a, s) for a, s in r["art"].items()}
                if not l:
                    continue
                total += 1 / r["views"]
                right += (max(l, key=l.get) == r["truth"]) / r["views"]
        print(f"art top-LLR held-out accuracy, {'per-agent' if per_agent else 'pooled'}: "
              f"{right:.1f} of {total:.1f} entities ({right / total:.3f})")
    return table


def make_claim(table, tau):
    """A drop-in for `identity.claim_from_killfeed_portrait` deciding on a posterior."""
    original = I.claim_from_killfeed_portrait

    def claim(observation, *, entity_id, candidates, gallery, rivals=(),
              source_version="killfeed-portrait", margin_min=I.PORTRAIT_MARGIN_MIN,
              exemplars=(), exclude_entry=None):
        base = original(observation, entity_id=entity_id, candidates=candidates, gallery=gallery,
                        rivals=rivals, source_version=source_version, margin_min=margin_min)
        stored = str(observation.get("reason") or "").strip()
        if stored or (observation.get("composition") is None and not observation.get("shifts")):
            return base
        admitted = sorted({a for a in list(candidates) + list(rivals) if a})
        barred = {r for r in rivals if r}
        art, ex, _ = source_scores(observation, admitted, gallery, list(exemplars), exclude_entry)
        l_art = {a: llr(table, "art", a, s) for a, s in art.items()}

        def decide(l):
            p = posterior(l)
            if not p:
                return None, "portrait_no_comparable_candidate", p
            best = max(p, key=p.get)
            if best in barred:
                return None, f"portrait_best_is_refused_slot {best}", p
            if len(p) == 1:
                return None, "portrait_single_candidate", p
            if p[best] < tau:
                return None, f"portrait_posterior {p[best]:.3f} below {tau}", p
            return best, None, p

        agent, reason, p = decide(l_art)
        depends, used = None, "art"
        if agent is None and exemplars and reason and reason.startswith("portrait_posterior"):
            l_ex = {a: llr(table, "ex", a, s) for a, s in ex.items()}
            l = {a: max(v, l_ex.get(a, -math.inf)) for a, v in l_art.items()}
            agent, reason, p = decide(l)
            used = "art+exemplar"
            if agent is not None and l_ex.get(agent, -math.inf) > l_art[agent]:
                src = {}
                I._portrait_scores(observation.get("composition"), [agent], {}, exemplars,
                                   exclude_entry, src, shifts=observation.get("shifts"))
                if agent in src:
                    depends = [src[agent]["label_entity"]]
        out = dict(base)
        out["agent"], out["reason"] = agent, reason
        out["depends_on"] = depends or []
        out["evidence"] = dict(base.get("evidence") or {},
                               posterior={a: round(v, 4) for a, v in sorted(p.items())},
                               likelihood_source=used)
        return out

    return claim


def pooled(table):
    """The same table with every agent at the pooled class means."""
    for src in SOURCES:
        for cls in ("same", "diff"):
            table[src][cls]["agents"] = {}
    return table


def evaluate(tau, per_agent=False):
    data = json.loads(ROWS.read_text())
    rows, e0_dis = data["rows"], data["e0_disagreements"]
    meta, labs = labels()
    gallery = I.load_identity_gallery(STORE.root)
    got, dis, t0 = {}, {}, time.time()
    for sid in SIDS:
        tab = fit(rows, exclude=sid)
        D.claim_from_killfeed_portrait = make_claim(tab if per_agent else pooled(tab), tau)
        res, _ = adjudicate(sid, gallery)
        g, d = outcomes(sid, res)
        got.update(g); dis.update(d)
        print(sid, f"{time.time() - t0:.0f} s", flush=True)
    tally, wrong = Counter(), []
    for key, truth in labs.items():
        a = got.get(key)
        tally["right" if a == truth else "unnamed" if a is None else "wrong"] += 1
        if a not in (None, truth):
            wrong.append((key, truth, a))
    print("labels", dict(tally), "coverage", round(tally["right"] / len(labs), 3), "wrong", wrong)
    print("disagreements E0", len(e0_dis), "L", len(dis))
    for k in sorted(set(e0_dis) - set(dis)):
        print("  removed", k, e0_dis[k], "->", got.get(k))
    for k in sorted(set(dis) - set(e0_dis)):
        print("  created", k, dis[k])
    out = STORE.root / "analysis" / f"portrait_likelihood_eval_tau{tau}{'_agent' if per_agent else ''}.json"
    out.write_text(json.dumps({"labels": dict(tally), "wrong": wrong, "disagreements": dis,
                               "e0_disagreements": e0_dis}, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("collect", "fit", "evaluate"))
    ap.add_argument("--tau", type=float, default=0.9)
    ap.add_argument("--per-agent", action="store_true")
    args = ap.parse_args()
    if args.cmd == "collect":
        collect_rows()
    elif args.cmd == "fit":
        report(json.loads(ROWS.read_text())["rows"])
    else:
        evaluate(args.tau, args.per_agent)
