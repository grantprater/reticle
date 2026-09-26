r"""Name ally tracks, not icons: split impure segments, then assign per round.

    .\.venv\Scripts\python.exe prototypes\ally_track_identity.py loso
    .\.venv\Scripts\python.exe prototypes\ally_track_identity.py run [SID ...]

Purpose. Per-icon rendered-art claims (`identity.claims_from_ally_icons` with
the baked table) name the player's labelled icons well, but round entities
built on them still name one agent on two icons in 11% of frames: the
per-frame assignment constrains icon claims, not tracks, and continuity swaps
teammates mid-segment. This tests naming tracks instead.

`loso` (step 0) refits the rendered-art calibration leaving each session out,
as `ally_portrait_calibration.run_fit` fits it on all sessions, renders the
table with `ally_portrait.build_references` into a temporary root, and scores
the held-out session's labelled icons with its own fit. Fold `all` is the
instrument check: it must reproduce the stored table's calls.

`run` (steps 1-3):
1. Round entities are rebuilt in memory without deaths
   (`ally_rendered_art_eval.entities`). Each ally segment's icons carry the
   owner's per-icon log ratios over the four teammates (the claim's
   `evidence.scores`). A Viterbi over the teammates with a switch penalty of
   `SWITCH` x `margin_min` cuts the segment where the best agent changes and
   stays changed; each run is a piece.
2. Per round, pieces co-observed in a frame form components; an exact branch
   and bound maximises the summed log ratios of named pieces (unnamed = 0)
   under: co-observed pieces take distinct agents; where a self icon is
   observed, named pieces in a frame number at most `alive_ally - 1`, taking
   the largest roster count within 500 ms (`_cap_at`); variant (b) only: no piece
   observed after its agent's last killfeed death of the round is that agent.
   A named piece is refused when the best solution with it named otherwise
   comes within `margin_min` of the optimum (its max-marginal gap).
3. Measures labels by piece, segments at killfeed deaths (variant a; the
   binding rule of `ally_rendered_art_eval.segments`), frames naming one
   agent twice, pieces per round, and everything per widget width, against
   the current entities' names. `montage` draws renamed or refused pieces.

Caches go to %TEMP%; no store writes, no decode. Predictions and outcome:
`ally-track-identity` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import pickle
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import ally_portrait as ap  # noqa: E402
from reticle.adjudication.identity import (claims_from_ally_icons,  # noqa: E402
                                           load_ally_portrait_references,
                                           load_identity_gallery)
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import portrait_key  # noqa: E402
from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION  # noqa: E402

import ally_rendered_art_eval as ev  # noqa: E402

STORE = ev.STORE
WORK = Path(tempfile.gettempdir()) / "reticle_ally_track_identity"
SWITCH = 5.0          # Viterbi switch penalty, in units of the per-icon margin gate
ROSTER_LAG_MS = 500.0  # roster count window either side of a frame
MAX_NODES = 400_000   # search nodes per solve before it keeps its best


# ---------------------------------------------------------------- step 0

def _fit_cal(bank, art, train) -> dict:
    """`ally_portrait_calibration.run_fit` restricted to `train` sessions."""
    import ally_icon_separability as asep
    import ally_portrait_calibration as apc
    import minimap_feature_bank as fb
    p = fb.fit_renderer(bank, art, train)
    rend = {a: ap.portrait_features(img, asep.key_mask(img))
            for a in bank.agents if a in art for img in [fb.rendered_image(art[a], p)]}
    var, gap, refs = {}, {}, {}
    for f in ap.FAMILIES:
        M, v, _, _ = bank.fit(f, train)
        Ra = np.full_like(M, np.nan)
        for a, x in rend.items():
            Ra[bank.aix[a]] = x[f]
        both = np.isfinite(M[:, 0]) & np.isfinite(Ra[:, 0])
        gap[f] = ((Ra[both] - M[both]) ** 2).mean(0) + 1e-6
        var[f], refs[f] = v, Ra
    tv = {f: var[f] + gap[f] for f in ap.FAMILIES}
    margins = []
    for s in train:
        rows, S = apc.scores(bank, refs, tv, s)
        cs = [c for c in fb.cands_of(bank, s) if np.isfinite(S[0, c])]
        for r, sc in zip(rows, S):
            order = sorted(cs, key=lambda c: -sc[c])
            if len(order) >= 2 and order[0] == r[2]:
                margins.append(sc[order[0]] - sc[order[1]])
    return {"version": "loso", "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
            "q": p["q"], "sigma": p["sigma"], "dy": p["dy"], "err": p["err"],
            "bg": [float(v) for v in p["bg"]], "W": np.asarray(p["W"]).tolist(),
            "var": {f: var[f].tolist() for f in ap.FAMILIES},
            "gap": {f: gap[f].tolist() for f in ap.FAMILIES},
            "margin_min": float(np.percentile(margins, 5))}


def _table(cal: dict, tag: str) -> dict:
    """Render the reference table for `cal` with the reticle builder, in a temp root."""
    root = WORK / "loso" / tag
    d = root.joinpath(*ap.REFERENCE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    (d / ap.CALIBRATION_FILE).write_text(json.dumps(cal), encoding="utf-8")
    art = root / "reference" / "assets" / "agents"
    if not art.exists():
        art.mkdir(parents=True)
        for p in (STORE.root / "reference" / "assets" / "agents").glob("*_minimap_portrait.png"):
            shutil.copyfile(p, art / p.name)
    return ap.build_references(root, portrait_key)


def run_loso() -> dict:
    import minimap_feature_bank as fb
    bank, art, labs = fb.Bank(), fb.load_art(), ev.labels()
    gallery = load_identity_gallery(STORE.root)
    by_sid = defaultdict(list)
    for k in labs:
        by_sid[k.split(":")[0]].append(k)
    out, total = {}, Counter()
    folds = ["all"] + sorted(by_sid)
    for fold in folds:
        sids = sorted(by_sid) if fold == "all" else [fold]
        train = list(bank.sids) if fold == "all" else [s for s in bank.sids if s != fold]
        table = _table(_fit_cal(bank, art, train), fold)
        c = Counter()
        for sid in sids:
            icons = [e for e in STORE.read_events("ally_icon", sid) if e.get("kind") == "icon"]
            claims = claims_from_ally_icons(icons, load_lineup(sid, STORE.root), gallery=gallery,
                                            session_id=sid, references=table)
            c += ev.per_icon(sid, claims, labs)
        out[fold] = {k: v for k, v in c.items() if k.startswith("lab_") and "source" not in k}
        out[fold]["margin_min"] = round(table["margin_min"], 3)
        out[fold]["in_train"] = fold in bank.sids
        if fold != "all":
            total += c
        print(fold, out[fold], flush=True)
    out["loso_total"] = {k: v for k, v in total.items() if "source" not in k}
    print("loso_total", out["loso_total"])
    return out


# ---------------------------------------------------------------- steps 1-3

def _self_times(events) -> list[float]:
    return sorted(e["t_ms"] for e in events if e.get("kind") == "frame" and e.get("self"))


def session_data(sid: str) -> dict | None:
    """Entities without deaths, per-icon scores, deaths, roster; cached in %TEMP%."""
    path = WORK / "sessions" / f"{sid}.pkl"
    if path.exists():
        d = pickle.loads(path.read_bytes())
        if "self_t" not in d:
            d["self_t"] = _self_times(STORE.read_events("ally_icon", sid))
            path.write_bytes(pickle.dumps(d))
        return d
    events = STORE.read_events("ally_icon", sid)
    lineup = load_lineup(sid, STORE.root)
    if not events or not lineup:
        return None
    man = STORE.read_manifest(sid)
    gallery = load_identity_gallery(STORE.root)
    refs = load_ally_portrait_references(STORE.root)
    rows = ev.entities(sid, man, events, lineup, gallery, refs)
    icons = [e for e in events if e.get("kind") == "icon"]
    claims = claims_from_ally_icons(icons, lineup, gallery=gallery, session_id=sid,
                                    references=refs)
    scores, named = {}, Counter()
    for cl in claims:
        s = (cl.get("evidence") or {}).get("scores")
        if s:
            k = cl["entity_id"].rsplit(":ally_icon:", 1)[-1]
            scores[k] = (s, cl.get("agent"))
            named[tuple(sorted(s))] += 1
    ents = {e["id"]: e for e in rows if e.get("kind") == "entity" and e.get("family") == "ally"}
    obs = defaultdict(list)
    for o in rows:
        if o.get("kind") == "observation" and o.get("entity_id") in ents:
            obs[o["entity_id"]].append((o["t_ms"], o["observation_key"]))
    date = ev._date_of(man)
    roster = None
    if STORE.has_roster(sid, date):
        t = STORE.read_roster(sid, date)
        roster = (t.column("t_ms").to_pylist(), t.column("alive_ally").to_pylist())
    deaths = [(float(v["t_ms"]), v["victim"], v.get("round_no"))
              for v in STORE.read_events("death", sid)
              if v.get("kind") == "death_verdict" and v.get("side") == "ally" and v.get("victim")]
    d = {"sid": sid, "width": ev.widget_width(man),
         "names": list(named.most_common(1)[0][0]) if named else [],
         "ents": {i: {"round": e["round_no"], "agent": e.get("agent")} for i, e in ents.items()},
         "obs": {i: sorted(v) for i, v in obs.items()}, "scores": scores,
         "roster": roster, "deaths": deaths, "self_t": _self_times(events)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(d))
    return d


def viterbi(E: np.ndarray, penalty: float) -> list[int]:
    """Best state path over rows of log-ratio emissions, `penalty` per switch."""
    n, k = E.shape
    V, back = E[0].copy(), np.zeros((n, k), int)
    for t in range(1, n):
        stay, j = V, int(np.argmax(V))
        move = V[j] - penalty
        back[t] = np.where(stay >= move, np.arange(k), j)
        V = np.maximum(stay, move) + E[t]
    path = [int(np.argmax(V))]
    for t in range(n - 1, 0, -1):
        path.append(int(back[t][path[-1]]))
    return path[::-1]


def pieces_of(d: dict, split: bool, gate: float) -> list[dict]:
    names = d["names"]
    out = []
    for eid, ob in d["obs"].items():
        E = np.array([[d["scores"][k][0].get(a, 0.0) if k in d["scores"] else 0.0
                       for a in names] for _, k in ob])
        path = viterbi(E, SWITCH * gate) if split and len(names) > 1 else [0] * len(ob)
        cuts = [0] + [i for i in range(1, len(path)) if path[i] != path[i - 1]] + [len(path)]
        for j in range(len(cuts) - 1):
            lo, hi = cuts[j], cuts[j + 1]
            out.append({"id": f"{eid}#{j}", "entity": eid, "round": d["ents"][eid]["round"],
                        "stored": d["ents"][eid]["agent"], "t": [t for t, _ in ob[lo:hi]],
                        "keys": [k for _, k in ob[lo:hi]], "S": E[lo:hi].sum(0),
                        "pieces_of_segment": len(cuts) - 1})
    return out


def _cap_at(roster, self_t, t, default):
    """Named ally pieces allowed at `t`: alive_ally less the player, as
    `round_lifetimes` subtracts self only when a self icon is observed; the
    largest count within `ROSTER_LAG_MS` stands, because the roster drops at a
    death while the dying teammate's icon may still show."""
    if not roster or t not in self_t:
        return default
    ts, al = roster
    lo = max(0, int(np.searchsorted(ts, t - ROSTER_LAG_MS, side="right")) - 1)
    hi = int(np.searchsorted(ts, t + ROSTER_LAG_MS, side="right"))
    vals = [v for v in al[lo:hi] if v is not None]
    return default if not vals else max(0, int(max(vals)) - 1)


def solve(comp, dom, S, edges, tight, cap, floor=-np.inf):
    """Exact max of summed scores over named pieces; None scores 0.
    Returns (score, pick, exact); pick is None when nothing beats `floor`."""
    order = sorted(comp, key=lambda p: -max([S[p][a] for a in dom[p]] + [0.0]))
    ub = [max([S[p][a] for a in dom[p]] + [0.0]) for p in order]
    rest = np.concatenate([np.cumsum(ub[::-1])[::-1], [0.0]])
    best = {"score": floor, "pick": None}
    pick, count, nodes = {}, Counter(), [0]

    def visit(i, score):
        nodes[0] += 1
        if score + rest[i] <= best["score"] + 1e-9 or nodes[0] > MAX_NODES:
            return
        if i == len(order):
            best["score"], best["pick"] = score, dict(pick)
            return
        p = order[i]
        taken = {pick[q] for q in edges[p] if pick.get(q) is not None}
        for a in sorted(dom[p], key=lambda a: -S[p][a]):
            if S[p][a] <= 0 or a in taken or any(count[f] + 1 > cap[f] for f in tight[p]):
                continue
            pick[p] = a
            for f in tight[p]:
                count[f] += 1
            visit(i + 1, score + S[p][a])
            for f in tight[p]:
                count[f] -= 1
        pick[p] = None
        visit(i + 1, score)
        del pick[p]

    visit(0, 0.0)
    return best["score"], best["pick"], nodes[0] <= MAX_NODES


def assign_pieces(d: dict, pieces: list[dict], use_deaths: bool, gate: float) -> dict:
    """Per round and co-observation component, the exact assignment and each
    named piece's max-marginal gap; refusal under `gate`."""
    names = d["names"]
    S = {p["id"]: dict(zip(names, p["S"])) for p in pieces}
    frames = defaultdict(set)
    for p in pieces:
        for t in p["t"]:
            frames[(p["round"], t)].add(p["id"])
    self_t = set(d["self_t"])
    cap = {f: _cap_at(d["roster"], self_t, f[1], len(names)) for f in frames}
    edges, tight = defaultdict(set), defaultdict(list)
    for f, ids in frames.items():
        for a in ids:
            edges[a] |= ids - {a}
            if len(ids) > cap[f]:
                tight[a].append(f)
    last_death = {}
    for t, v, rn in d["deaths"]:
        last_death[(rn, v)] = max(t, last_death.get((rn, v), -1.0))
    dom = {}
    for p in pieces:
        dom[p["id"]] = [a for a in names if not use_deaths or
                        (p["round"], a) not in last_death or
                        max(p["t"]) <= last_death[(p["round"], a)]]
    out, inexact = {}, 0
    by_round = defaultdict(list)
    for p in pieces:
        by_round[p["round"]].append(p["id"])
    for ids in by_round.values():
        seen = set()
        for s in ids:
            if s in seen:
                continue
            comp, stack = [], [s]
            seen.add(s)
            while stack:
                u = stack.pop()
                comp.append(u)
                for v in edges[u]:
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            opt, pick, exact = solve(comp, dom, S, edges, tight, cap)
            inexact += not exact
            for p in comp:
                a = pick.get(p)
                if a is None:
                    out[p] = {"agent": None, "reason": "no admissible teammate with positive evidence"
                              if not any(S[p][x] > 0 for x in dom[p]) else
                              "constraints leave no teammate", "gap": None}
                    continue
                alt = {**dom, p: [x for x in dom[p] if x != a]}
                sc, apick, _ = solve(comp, alt, S, edges, tight, cap, floor=opt - gate)
                if apick is None:
                    out[p] = {"agent": a, "reason": None, "gap": None}
                else:
                    out[p] = {"agent": None, "best": a, "gap": round(opt - sc, 3),
                              "reason": f"track margin {opt - sc:.3f} < {gate:.3f}; "
                                        f"runner-up {apick.get(p)}"}
    return {"pick": out, "inexact": inexact, "frames": frames}


def measure(d, pieces, res, labs) -> Counter:
    c = Counter()
    pick = res["pick"]
    by_key = {k: p for p in pieces for k in p["keys"]}
    for k, r in labs.items():
        p = by_key.get(k)
        if p is None or not k.startswith(d["sid"]):
            continue
        a, ans = pick[p["id"]]["agent"], r["answer"]
        c["lab_n"] += 1
        c["lab_right" if a == ans else "lab_refused" if a is None else "lab_wrong"] += 1
        st = p["stored"]
        c["cur_right" if st == ans else "cur_none" if st is None else "cur_wrong"] += 1
        best = d["names"][int(np.argmax(p["S"]))] if d["names"] else None
        c["piece_best_right"] += best == ans
    lo, hi = ev.WINDOW_MS
    for t, v, _ in d["deaths"]:
        ends = [p for p in pieces if t - lo <= max(p["t"]) <= t + hi]
        if len(ends) != 1 or max(ends[0]["t"]) > t - ev.LEAD_MS:
            continue
        a = pick[ends[0]["id"]]["agent"]
        c["seg_bound"] += 1
        c["seg_right" if a == v else "seg_none" if a is None else "seg_wrong"] += 1
        st = ends[0]["stored"]
        c["cur_seg_right" if st == v else "cur_seg_none" if st is None else "cur_seg_wrong"] += 1
    stored = {p["id"]: p["stored"] for p in pieces}
    for f, ids in res["frames"].items():
        got = [pick[i]["agent"] for i in ids if pick[i]["agent"]]
        c["frames"] += 1
        c["dup_frames"] += len(got) != len(set(got))
        cur = [stored[i] for i in ids if stored[i]]
        c["cur_dup_frames"] += len(cur) != len(set(cur))
    per_round = Counter(p["round"] for p in pieces)
    named_round = Counter(p["round"] for p in pieces if pick[p["id"]]["agent"])
    c["rounds"] += len(per_round)
    c["pieces"] += len(pieces)
    c["named_pieces"] += sum(named_round.values())
    c["refused_by_gap"] += sum(1 for v in pick.values() if v.get("gap") is not None)
    c["inexact"] += res["inexact"]
    return c, list(per_round.values())


def run_tracks(sids) -> dict:
    labs = ev.labels()
    gate = load_ally_portrait_references(STORE.root)["margin_min"]
    configs = (("nosplit_a", False, False), ("split_a", True, False), ("split_b", True, True))
    total, rounds_n = defaultdict(Counter), defaultdict(list)
    splits = Counter()
    for sid in sids:
        d = session_data(sid)
        if d is None:
            print(sid, "skipped: no events or no lineup", flush=True)
            continue
        for name, split, deaths in configs:
            pieces = pieces_of(d, split, gate)
            if split and not deaths:
                segs = {p["entity"]: p["pieces_of_segment"] for p in pieces}
                big = [e for e in segs if len(d["obs"][e]) >= 10]
                splits["segments"] += len(segs)
                splits["segments_10plus"] += len(big)
                splits["split_10plus"] += sum(segs[e] > 1 for e in big)
                splits["split_any"] += sum(n > 1 for n in segs.values())
            res = assign_pieces(d, pieces, deaths, gate)
            c, pr = measure(d, pieces, res, labs)
            total[name] += c
            total[f"{name}@{d['width']}"] += c
            rounds_n[name] += pr
            if name == "split_b":
                (WORK / "assign").mkdir(parents=True, exist_ok=True)
                (WORK / "assign" / f"{sid}.pkl").write_bytes(pickle.dumps(
                    {"pieces": pieces, "pick": res["pick"], "names": d["names"]}))
        print(sid, d["width"], dict(total["split_a"]), flush=True)
    out = {k: dict(sorted(v.items())) for k, v in sorted(total.items())}
    for k, v in rounds_n.items():
        out[k]["pieces_per_round_median"] = float(np.median(v))
    out["splits"] = dict(splits)
    print(json.dumps(out, indent=1))
    (WORK / "run.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def montage(n: int = 12) -> str:
    """Pieces variant (b) renames (named, and differs from the current entity
    name) or refuses by track margin: first, middle and last icon of each."""
    import cv2
    from label_death_icons import Crops
    rows, rng = [], np.random.default_rng(0)
    for p in sorted((WORK / "assign").glob("*.pkl")):
        a = pickle.loads(p.read_bytes())
        for pc in a["pieces"]:
            v = a["pick"][pc["id"]]
            if len(pc["keys"]) >= 3 and ((v["agent"] and v["agent"] != pc["stored"])
                                         or v.get("gap") is not None):
                rows.append((p.stem, pc, v))
    pick = [rows[i] for i in sorted(rng.choice(len(rows), min(n, len(rows)), replace=False))]
    crops, tiles = Crops(), []
    for sid, pc, v in pick:
        ks = [pc["keys"][0], pc["keys"][len(pc["keys"]) // 2], pc["keys"][-1]]
        ims = [crops.get(sid, k)[0] for k in ks]
        strip = np.hstack(ims)
        bar = np.zeros((22, strip.shape[1], 3), np.uint8)
        txt = (f"{sid[:6]} {pc['id'].split(':')[-1]} n={len(pc['keys'])} "
               f"cur={pc['stored']} new={v['agent'] or 'REFUSED ' + str(v.get('best'))}")
        cv2.putText(bar, txt, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        tiles.append(np.vstack([bar, strip]))
        print(txt, v.get("reason"))
    w = max(t.shape[1] for t in tiles)
    img = np.vstack([cv2.copyMakeBorder(t, 0, 2, 0, w - t.shape[1], cv2.BORDER_CONSTANT)
                     for t in tiles])
    out = WORK / "montage.png"
    cv2.imwrite(str(out), img)
    print(out, img.shape, "of", len(rows), "renamed or refused pieces")
    return str(out)


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("step", choices=("loso", "run", "montage"))
    a.add_argument("sids", nargs="*")
    args = a.parse_args()
    if args.step == "loso":
        run_loso()
    elif args.step == "run":
        run_tracks(args.sids or sorted(p.stem for p in
                                (STORE.root / "events" / "ally_icon").glob("*.jsonl")))
    else:
        montage()


if __name__ == "__main__":
    main()
