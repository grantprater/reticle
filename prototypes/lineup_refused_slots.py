r"""Fill the lineup's refused slots from match-long evidence over all 29 agents.

    .\.venv\Scripts\python.exe prototypes\lineup_refused_slots.py audit
    .\.venv\Scripts\python.exe prototypes\lineup_refused_slots.py widen [killfeed,icons]

Why. Every identity stage admits only the lineup's agents
(`identity.side_candidates`). Claude's blind killfeed test differed from the
player on 13 of 150 uniform killer labels, and 12 of the 13 were agents
outside the item's candidates: the lineup had refused or misnamed the slot
that agent held. A refused slot is a surprise, so the search widens there and
only there: the lineup's named slots stay as the prior, and each refused slot
is scored over the full 29-agent gallery.

`audit` counts refused slots and their margins and reasons, and lists each
true agent (the player's uniform killfeed killer labels, killer side the
opposite of the death verdict's victim side; the player's minimap death-icon
labels, ally side) that the lineup neither names nor guesses, with its rank
in the top bar's own scores.

`widen` adds three witnesses the lineup never used, each weighed once:
(a) killfeed portraits pooled per name cluster (`killfeed_name_continuity`),
official-art ratios `identity.portrait_llr` over 29 agents, plus each
independent reference claim (`reliability.REFERENCE_CHANNELS`, which includes
`killfeed_weapon`) at its measured reliability (`match_name_assignment`);
(b) ally minimap icons, `identity.rendered_art_scores` over 29 agents, as a
mixture over the side's teammates, one mean per round (a round's icons are
one set of views, not independent draws). Per side, every set of new agents
the refused slots could hold is scored: the side's big name clusters (at
least `mna.MIN_CLUSTER` roles) take agents of named + new one-to-one, summed
over injective assignments; icons add their mixture likelihood. The top
bar's scores never enter the likelihood; they only place the chosen agents
in slots. A new agent is named when its marginal over sets reaches
`POSTERIOR_MIN`; otherwise the slot stays refused with the reason.

The scoreboard rows were written under an older `SCOREBOARD_VERSION`; for
measurement `load_lineup` runs with the version pinned in memory to each
session's stored stamp (`_pinned_lineup`). Caches go to %TEMP%.

Outcome. The finding was an instrument fault. With the board pinned, every
side is board-constrained, no slot is refused, and one labelled agent of 146
falls outside the candidates. With the board dropped, the widening names 66
of 68 refused slots and recovers 30 of 43 labelled agents, but 8 of its names
fall outside the board's set, each at p >= 0.99 (Clove read as Deadlock four
times): summed art ratios are overconfident across 29 agents. The player's
own "Me" roles are excluded; counting them as teammates was the first run's
bug. Predictions and outcome: `lineup-refused-slots` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import itertools
import json
import os
import pickle
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import killfeed_name_continuity as K  # noqa: E402
import label_feed_portraits as lfp  # noqa: E402
import match_name_assignment as mna  # noqa: E402
from reticle import version as _version  # noqa: E402
from reticle.adjudication import reliability  # noqa: E402
from reticle.adjudication.identity import (  # noqa: E402
    load_ally_portrait_references, load_identity_gallery, rendered_art_scores,
    side_candidates)
from reticle.lineup import load_lineup  # noqa: E402

STORE = K.STORE
CACHE = Path(tempfile.gettempdir()) / "reticle_lineup_refused_slots"
POSTERIOR_MIN = 0.9
OTHER = mna.OTHER


def _pinned_lineup(sid: str) -> dict:
    """`load_lineup` with the scoreboard version pinned to the stored stamp."""
    f = CACHE / f"lineup_{sid}.pkl"
    if f.is_file():
        return pickle.loads(f.read_bytes())
    keep = _version.SCOREBOARD_VERSION
    stored = STORE.events_version("scoreboard", sid)
    try:
        if stored:
            _version.SCOREBOARD_VERSION = stored
        got = load_lineup(sid, STORE.root) or {}
    finally:
        _version.SCOREBOARD_VERSION = keep
    CACHE.mkdir(exist_ok=True)
    f.write_bytes(pickle.dumps(got))
    return got


def sessions() -> list[str]:
    return sorted(p.stem for p in (STORE.root / "lineups").glob("*.json"))


def capture(sid: str) -> str:
    m = STORE.root / "manifests" / f"{sid}.json"
    try:
        return json.loads(m.read_text(encoding="utf-8"))["source"]["path"]
    except (OSError, KeyError, ValueError):
        return "?"


def truth(sid: str) -> dict[str, dict[str, int]]:
    """{side: {agent: labels}} from the player's uniform killer and minimap labels."""
    out = defaultdict(Counter)
    deaths = {v["death_id"]: v for v in STORE.read_events("death", sid)
              if v.get("kind") == "death_verdict"}
    for lab in lfp._labels(lfp.UNIFORM_KIND).values():
        if lab["session_id"] != sid or lab["class"] != "agent" or lab["uncertain"]:
            continue
        side = OTHER.get((deaths.get(lab["death_id"]) or {}).get("side"))
        if side:
            out[side][lab["answer"]] += 1
    p = STORE.root / "labels" / "death_icon" / f"{sid}.jsonl"
    if p.is_file():
        last = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
        for row in last.values():
            if row.get("class") == "agent" and not row.get("uncertain") and row.get("answer"):
                out["ally"][row["answer"]] += 1
    return {s: dict(c) for s, c in out.items()}


def side_sets(lineup: dict, side: str) -> tuple[list[str], list[str]]:
    split = side_candidates((lineup.get("sides") or {}).get(side, []))
    return split["named"], [a for a in split["rivals"] if a]


def audit() -> dict:
    out = {}
    for sid in sessions():
        lu = _pinned_lineup(sid)
        names = (lu.get("scores") or {}).get("names") or []
        tr = truth(sid)
        rows = {}
        for side in ("ally", "enemy"):
            named, rivals = side_sets(lu, side)
            refused = [{"slot": r["slot"], "guess": r.get("best_guess"), "margin": r.get("margin"),
                        "reason": r.get("reason")}
                       for r in lu["sides"].get(side, []) if not r.get("agent")]
            mat = np.asarray((lu.get("scores") or {}).get(side) or [[0.0] * len(names)] * 5, float)
            missing = []
            for a, n in sorted((tr.get(side) or {}).items()):
                if a in named or a in rivals:
                    continue
                j = names.index(a) if a in names else None
                ranks = ([int((mat[r["slot"]] > mat[r["slot"], j]).sum()) + 1 for r in refused]
                         if j is not None else [])
                missing.append({"agent": a, "labels": n, "best_rank_in_refused_slots":
                                min(ranks) if ranks else None,
                                "rank_per_refused_slot": ranks})
            wrong_named = [a for a in named if tr.get(side) and a not in tr[side]]
            rows[side] = {"named": named, "refused": refused, "missing": missing,
                          "named_unseen_in_labels": wrong_named,
                          "board": ((lu.get("board") or {}).get(side) or {}).get("agents"),
                          "board_reason": ((lu.get("board") or {}).get(side) or {}).get("reason")}
        out[sid] = {"capture": capture(sid), "version": lu.get("version"), "sides": rows}
    return out


def top_bar(lu: dict) -> dict:
    """The lineup as the top bar alone read it: the board's constraint removed."""
    return {**lu, "sides": lu.get("top_bar_sides") or lu.get("sides") or {}}


def _cached(name: str, fn):
    f = CACHE / name
    if f.is_file():
        return pickle.loads(f.read_bytes())
    got = fn()
    CACHE.mkdir(exist_ok=True)
    f.write_bytes(pickle.dumps(got))
    return got


def killfeed_evidence(sid: str, agents: list[str]) -> dict:
    """{(death_id, role): {agent: llr}} over all agents (`mna.role_evidence`)."""
    wide = {"sides": {s: [{"slot": i, "agent": a} for i, a in enumerate(agents)]
                      for s in ("ally", "enemy")}}
    return _cached(f"kf_{sid}.pkl", lambda: mna.role_evidence(
        sid, wide, load_identity_gallery(STORE.root), reliability.load(STORE.root)))


ICON_HZ = 1.0          # icons kept per second: neighbouring frames repeat one view
ROUND_BIN_MS = 60_000  # one mean per bin; a proxy for a round's set of views


def icon_evidence(sid: str, agents: list[str]) -> list[np.ndarray]:
    """Per time bin, the (icons x agents) rendered-art ratios of ally icons."""
    def build():
        refs = load_ally_portrait_references(STORE.root)
        bins, last = defaultdict(list), {}
        for e in STORE.read_events("ally_icon", sid):
            if e.get("kind") != "icon" or e.get("reason") or not e.get("portrait_features"):
                continue
            sec = int(e["t_ms"] * ICON_HZ / 1000)
            if last.get(e["index"]) == sec:
                continue
            last[e["index"]] = sec
            s = rendered_art_scores(e["portrait_features"], agents, refs)
            if s:
                bins[int(e["t_ms"] // ROUND_BIN_MS)].append([s[a] for a in agents])
        return [np.asarray(v) for v in bins.values()]
    return _cached(f"icons_{sid}.pkl", build)


def _lse(x, axis=None):
    m = np.max(x, axis=axis, keepdims=True)
    return (m + np.log(np.exp(x - m).sum(axis=axis, keepdims=True))).squeeze(axis)


def widen_side(sid: str, lu: dict, side: str, agents: list[str], sources=("killfeed", "icons")) -> dict:
    """Name the side's refused top-bar slots over every agent the side does not name."""
    rows = lu["sides"].get(side, [])
    refused = [r for r in rows if not r.get("agent")]
    named = [r["agent"] for r in rows if r.get("agent")]
    player = (lu.get("player") or {}).get("agent")
    if not refused:
        return {"named": named, "new": [], "slots": []}
    pool = [a for a in agents if a not in named]
    ix = {a: i for i, a in enumerate(agents)}
    ev = killfeed_evidence(sid, agents) if "killfeed" in sources else {}
    sides = {(v["death_id"], role): (v["side"] if role == "victim" else OTHER.get(v["side"]))
             for v in STORE.read_events("death", sid) if v.get("kind") == "death_verdict"
             for role in ("killer", "victim")}
    items, me = {}, set()
    for it in K.load(sid):
        if it["me"]:
            me.add((it["death_id"], it["role"]))  # the player's own: the lineup owns it
        elif it["team"] == side:
            items.setdefault((it["death_id"], it["role"]), it)
    keys = list(items)
    cl = sorted(([keys[i] for i in c] for c in K.clusters([items[k] for k in keys])),
                key=len, reverse=True)
    cap = N - (1 if side == "ally" else 0)
    big = [c for c in cl if len(c) >= mna.MIN_CLUSTER and any(k in ev for k in c)][:cap]
    in_big = {k for c in big for k in c}
    Lbig = np.array([[sum(ev[k][a] for k in c if k in ev) for a in agents] for c in big]) \
        if big else np.zeros((0, len(agents)))
    frag = np.array([[ev[k][a] for a in agents] for k in ev
                     if k not in in_big and k not in me and sides.get(k) == side]) \
        if ev and FRAGMENTS else np.zeros((0, len(agents)))
    icons = icon_evidence(sid, agents) if (side == "ally" and "icons" in sources) else []
    combos = list(itertools.combinations(pool, len(refused)))
    score = np.zeros(len(combos))
    for n, new in enumerate(combos):
        S = [a for a in named + list(new) if not (side == "ally" and a == player)]
        cols = [ix[a] for a in S]
        tot = 0.0
        if len(big):
            B = Lbig[:, cols]
            perms = np.array(list(itertools.permutations(range(len(cols)), len(big))))
            tot += float(_lse(B[np.arange(len(big))[None], perms].sum(1)))
        if len(frag):
            tot += float((_lse(frag[:, cols], axis=1) - np.log(len(cols))).sum())
        for b in icons:
            tot += float(np.mean(_lse(b[:, cols], axis=1) - np.log(len(cols))))
        score[n] = tot
    w = np.exp(score - score.max())
    w /= w.sum()
    marg = Counter()
    for p, new in zip(w, combos):
        for a in new:
            marg[a] += float(p)
    best = marg.most_common(len(refused))
    names = (lu.get("scores") or {}).get("names") or []
    mat = np.asarray((lu.get("scores") or {}).get(side) or [], float)
    # The top bar places the chosen agents in slots; it never weighs WHO.
    order = list(range(len(refused)))
    if mat.size and all(a in names for a, _ in best):
        from reticle.track import assign
        cost = [[-float(mat[r["slot"], names.index(a)]) for a, _ in best] for r in refused]
        order = assign(cost)
    slots = []
    for r, j in zip(refused, order):
        a, p = best[j]
        slots.append({"slot": r["slot"], "agent": a if p >= POSTERIOR_MIN else None,
                      "best_guess": a, "p": round(p, 4), "top_bar_guess": r.get("best_guess"),
                      "reason": None if p >= POSTERIOR_MIN else
                      f"marginal {p:.3f} below {POSTERIOR_MIN} over {len(pool)} agents"})
    return {"named": named, "new": [s["agent"] for s in slots if s["agent"]], "slots": slots,
            "big_clusters": len(big), "fragments": int(len(frag)), "icon_bins": len(icons)}


N = 5
#: Roles outside the big name clusters as mixture terms over the side.
FRAGMENTS = os.environ.get("LRS_FRAGMENTS", "1") == "1"


def _item_side(sid: str, death_id: str, role: str) -> str | None:
    v = {d["death_id"]: d for d in STORE.read_events("death", sid)
         if d.get("kind") == "death_verdict"}.get(death_id) or {}
    return v.get("side") if role == "victim" else OTHER.get(v.get("side"))


def widen_main(sources=("killfeed", "icons")) -> dict:
    agents = (_pinned_lineup(sessions()[0]).get("scores") or {})["names"]
    res, tally = {}, Counter()
    for sid in sessions():
        lu = _pinned_lineup(sid)
        tb = top_bar(lu)
        tr = truth(sid)
        res[sid] = {}
        for side in ("ally", "enemy"):
            got = widen_side(sid, tb, side, agents, sources)
            board = set(((lu.get("board") or {}).get(side) or {}).get("agents") or [])
            seen = set(tr.get(side) or {})
            tb_named = set(got["named"])
            for s in got["slots"]:
                tally["refused"] += 1
                a = s["agent"]
                if a is None:
                    tally["still_refused"] += 1
                    continue
                tally["named"] += 1
                tally["named_in_board" if a in board else "named_not_in_board"] += 1
                if a in seen:
                    tally["named_labelled_true"] += 1
            for a in seen - tb_named:
                tally["labelled_true_unnamed_by_top_bar"] += 1
                if a in got["new"]:
                    tally["recovered"] += 1
            res[sid][side] = {**got, "board": sorted(board), "truth": sorted(seen)}
    # Candidate coverage of the uniform killer labels.
    import claude_killfeed_labels as C
    _b, _f, meta = C.uniform_items(None)
    labs = lfp._labels(lfp.UNIFORM_KIND)
    items = os.environ.get("BLIND_ITEMS")  # the blind test's items.json, to compare
    shown = json.loads(Path(items).read_text()) if items else None
    cov = Counter()
    for i, m in enumerate(meta):
        lab = labs.get(m["entity_id"])
        if not lab or lab["uncertain"] or lab["class"] != "agent":
            continue
        cov["certain_agent"] += 1
        sid, side = m["session_id"], _item_side(m["session_id"], m["death_id"], m["role"])
        lu = _pinned_lineup(sid)
        tb = top_bar(lu)
        sets = {"top_bar": side_sets(tb, side) if side else ([], []),
                "board": side_sets(lu, side) if side else ([], [])}
        w = res[sid].get(side) or {}
        sets["widened"] = (sets["top_bar"][0] + (w.get("new") or []),
                           [s["top_bar_guess"] for s in w.get("slots", []) if not s["agent"]])
        for k, (named, rivals) in sets.items():
            cov[f"{k}_covered"] += lab["answer"] in named + rivals
        if shown:
            cov["shown_covered"] += lab["answer"] in shown[i]["candidates"]
            cov["shown_equals_top_bar"] += sorted(shown[i]["candidates"]) == sorted(
                set(sets["top_bar"][0] + sets["top_bar"][1]))
    out = {"sources": list(sources), "tally": dict(tally), "coverage": dict(cov), "sessions": res}
    (CACHE / f"widen_{'_'.join(sources)}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"sources": sources, "tally": dict(tally), "coverage": dict(cov)}))
    return out


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "audit"
    if cmd == "audit":
        got = audit()
        n_ref = sum(len(s["refused"]) for v in got.values() for s in v["sides"].values())
        n_miss = sum(len(s["missing"]) for v in got.values() for s in v["sides"].values())
        print(f"refused slots {n_ref}; missing true agents {n_miss}")
        for sid, v in got.items():
            for side, s in v["sides"].items():
                if s["missing"] or s["refused"]:
                    print(sid, side, "named", s["named"],
                          "refused", [(r["guess"], r["margin"]) for r in s["refused"]],
                          "MISSING", [(m["agent"], m["labels"], m["rank_per_refused_slot"])
                                      for m in s["missing"]],
                          "board", s["board"] or s["board_reason"])
        (CACHE / "audit.json").write_text(json.dumps(got, indent=1))
    elif cmd == "widen":
        widen_main(tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("killfeed", "icons"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
