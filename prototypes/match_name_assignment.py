r"""Name each killfeed player once per match, not each entry.

    .\.venv\Scripts\python.exe prototypes\match_name_assignment.py [SID ...]

Stage 4 of the inference architecture (`docs/BEHAVIOUR_MODEL_DESIGN.md`),
killfeed half, measured and not wired. A killfeed name is one player for the
match (`prototypes/killfeed_name_continuity.py`: two crops of one name on one
plate side are one player), so the entries of one name share one agent.

Each entry role's evidence is the official-art log likelihood ratio of every
admitted agent (`identity.portrait_llr` over `identity._portrait_scores`),
the mean over the views death adjudication followed. Exemplars are left out:
they rest on other channels' verdicts, and pooling them would count those
witnesses again. A cluster's evidence is the sum over its entries.

On each side the largest clusters (at least `MIN_CLUSTER` roles, at most one
per agent) take the side's agents one-to-one -- the ally side without the
player's own agent, whose entries print "Me" -- and a cluster is named when
its marginal over every injective assignment reaches `POSTERIOR_MIN`. A
smaller cluster, a fragment of a name the cut split, takes its own posterior.
Refused lineup slots enter as rivals under their best guess and never take
the name (`identity.side_candidates`); a side with a blind slot names nothing.

The check is the player's 146 uniform killer labels and the stored death
verdicts. Predictions and outcome: `match-name-assignment` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import killfeed_name_continuity as K  # noqa: E402
import label_feed_portraits as lfp  # noqa: E402
from reticle.adjudication import reliability  # noqa: E402
from reticle.adjudication.identity import (  # noqa: E402
    _portrait_scores, load_identity_gallery, portrait_llr, side_candidates)
from reticle.lineup import load_lineup  # noqa: E402

MIN_CLUSTER = 5
#: Version switches: the other reference channels as factors, and roles with
#: no name crop as their own fragments.
CHANNELS = True
UNCLUSTERED = True
POSTERIOR_MIN = 0.9
#: The ratio an agent takes in a view whose references it lacks.
FLOOR_LLR = -10.0
OTHER = {"ally": "enemy", "enemy": "ally"}


def _views(verdict: dict) -> list[tuple[float, int]]:
    """The (t_ms, slot) views death adjudication bound to the entry, from the
    killer claim's observation keys (`sid:frame:slot:role`)."""
    meta = verdict.get("metadata") or {}
    return sorted({(float(o["t_ms"]), int(o["observation_key"].split(":")[2]))
                   for c in (meta.get("killer_identity") or {}).get("claims", [])
                   if c["channel"] == "killfeed_portrait"
                   for o in (c.get("evidence") or {}).get("observations", [])
                   if o.get("observation_key")})


def channel_llr(table: dict, channel: str, agent: str, k: int) -> float:
    """The log ratio one channel's claim gives the agent it names, among `k`
    admitted agents: right with its reliability-table mean m, and wrong
    evenly over the others, so log(m (k - 1) / (1 - m))."""
    b = table["agents"].get(f"{channel}:{agent}") or table["channels"][channel]
    m = b["mean"]
    return float(np.log(m * max(1, k - 1) / (1.0 - m)))


def role_evidence(sid: str, lineup: dict, gallery: dict, table: dict | None = None) -> dict:
    """{(death_id, role): {agent: log likelihood ratio}}: the mean official-art
    ratio over the followed views, plus each independent reference channel's
    claim (`reliability.REFERENCE_CHANNELS`, no `depends_on`) at its measured
    reliability when `table` is given. Each factor is attached once."""
    rows = {(float(r["t_ms"]), r["slot"], r["role"]): r
            for r in K.STORE.read_events("killfeed_portrait", sid)
            if r.get("kind") == "portrait_observation"}
    out = {}
    for v in K.STORE.read_events("death", sid):
        if v.get("kind") != "death_verdict" or v.get("is_revive"):
            continue
        for role in ("killer", "victim"):
            side = v["side"] if role == "victim" else OTHER.get(v["side"])
            split = side_candidates(lineup["sides"].get(side, []))
            if split["blind"] or side is None:
                continue
            admitted = split["named"] + split["rivals"]
            per = []
            for t, slot in _views(v):
                r = rows.get((t, slot, role))
                if (r is None or r.get("reason") or r.get("composition") is None
                        or ("ally" if r.get("ally") else "enemy") != side):
                    continue
                s = _portrait_scores(r["composition"], admitted, gallery, shifts=r.get("shifts"))
                per.append({a: portrait_llr("art", s[a]) if a in s else FLOOR_LLR for a in admitted})
            llr = ({a: float(np.mean([p[a] for p in per])) for a in admitted} if per
                   else {a: 0.0 for a in admitted})
            key = "killer_identity" if role == "killer" else "identity"
            said = [c for c in ((v.get("metadata") or {}).get(key) or {}).get("claims", [])
                    if table and c["channel"] in reliability.REFERENCE_CHANNELS
                    and c.get("agent") in llr and not c.get("depends_on")]
            for c in said:
                llr[c["agent"]] += channel_llr(table, c["channel"], c["agent"], len(admitted))
            if per or said:
                out[(v["death_id"], role)] = llr
    return out


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def assign_names(sid: str) -> dict:
    """{(death_id, role): {"agent", "p", "cluster", "n", "kind"}} for every
    clustered, non-"Me" role on both sides."""
    lineup = load_lineup(sid, K.STORE.root)
    gallery = load_identity_gallery(K.STORE.root)
    ev = role_evidence(sid, lineup, gallery, reliability.load(K.STORE.root) if CHANNELS else None)
    player = (lineup.get("player") or {}).get("agent")
    items, me = {}, set()
    for it in K.load(sid):
        if it["me"]:
            me.add((it["death_id"], it["role"]))
        else:
            items.setdefault((it["death_id"], it["role"]), it)
    out = {}
    # "Me" prints on the player's own entries; the lineup owns the player's agent.
    for k in me:
        out[k] = {"agent": player, "p": None, "best": player, "cluster": None, "n": len(me),
                  "kind": "me", "team": "ally"}
    sides = {(v["death_id"], role): (v["side"] if role == "victim" else OTHER.get(v["side"]))
             for v in K.STORE.read_events("death", sid) if v.get("kind") == "death_verdict"
             for role in ("killer", "victim")}
    for team in ("ally", "enemy"):
        split = side_candidates(lineup["sides"].get(team, []))
        if split["blind"]:
            continue
        agents = [a for a in split["named"] + split["rivals"] if not (team == "ally" and a == player)]
        barred = set(split["rivals"])
        keys = [k for k, it in items.items() if it["team"] == team]
        cl = K.clusters([items[k] for k in keys])
        cl = sorted(([keys[i] for i in c] for c in cl), key=len, reverse=True)
        # A role with no name crop stands alone on its own evidence.
        if UNCLUSTERED:
            cl += [[k] for k in ev if k not in items and k not in me and sides.get(k) == team]
        L = np.array([[sum(ev[k][a] for k in c if k in ev) for a in agents] for c in cl])
        big = [i for i, c in enumerate(cl) if len(c) >= MIN_CLUSTER][:len(agents)]
        marg = np.zeros((len(big), len(agents)))
        if big:
            perms = list(itertools.permutations(range(len(agents)), len(big)))
            tot = np.array([sum(L[big[j], p[j]] for j in range(len(big))) for p in perms])
            w = _softmax(tot)
            for p, wp in zip(perms, w):
                for j in range(len(big)):
                    marg[j, p[j]] += wp
        for i, c in enumerate(cl):
            if i in big:
                post, kind = marg[big.index(i)], "assigned"
            else:
                post, kind = _softmax(L[i]), "fragment"
            if not any(k in ev for k in c):
                post = np.zeros(len(agents))
            j = int(np.argmax(post))
            name = agents[j] if post[j] >= POSTERIOR_MIN and agents[j] not in barred else None
            for k in c:
                out[k] = {"agent": name, "p": round(float(post[j]), 4), "best": agents[j],
                          "cluster": i, "n": len(c), "kind": kind, "team": team}
    return out


def main(sids: list[str]) -> dict:
    meta = {m["entity_id"]: m for m in json.loads(str(np.load(lfp.UNIFORM_PREP)["meta"]))}
    labs = {r["key"]: r["answer"] for r in lfp._labels(lfp.UNIFORM_KIND).values()
            if r["key"] in meta and not r["uncertain"] and r["class"] != "not_portrait"}
    got, stored, dis = {}, {}, []
    for sid in sids:
        a = assign_names(sid)
        for (did, role), x in a.items():
            got[f"{did}:killer" if role == "killer" else did] = x
        for v in K.STORE.read_events("death", sid):
            if v.get("kind") != "death_verdict":
                continue
            for role, key in (("killer", "killer_identity"), ("victim", "identity")):
                ver = (v.get("metadata") or {}).get(key) or {}
                eid = f"{v['death_id']}:killer" if role == "killer" else v["death_id"]
                stored[eid] = ver
                if ver.get("status") == "disagreement":
                    dis.append(eid)
        print(sid, Counter(x["kind"] + ("" if x["agent"] else "-refused") for x in a.values()), flush=True)
    # Labels: the stored verdict's entity ids end in ":killer" for killers.
    tally, wrong = Counter(), []
    for k, truth in labs.items():
        x = got.get(k)
        name = x["agent"] if x else None
        tally["right" if name == truth else "unnamed" if name is None else "wrong"] += 1
        if name not in (None, truth):
            wrong.append((k, truth, name, x["kind"], x["n"], x["p"]))
    agree = Counter()
    for k, ver in stored.items():
        x = got.get(k)
        if ver.get("status") == "resolved" and x and x["agent"]:
            agree["agree" if x["agent"] == ver.get("agent") else "differ"] += 1
    settled = Counter()
    for k in dis:
        x = got.get(k)
        chans = {c.get("agent") for c in stored[k].get("claims", []) if c.get("agent")}
        settled["unnamed" if not x or not x["agent"] else
                "a witness's name" if x["agent"] in chans else "another name"] += 1
    res = {"labels": dict(tally), "coverage": round(tally["right"] / max(1, len(labs)), 3),
           "wrong": wrong, "agreement_with_resolved": dict(agree),
           "agreement_rate": round(agree["agree"] / max(1, sum(agree.values())), 4),
           "disagreements": len(dis), "disagreements_settled": dict(settled)}
    print(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    main(sys.argv[1:] or K.SIDS)
