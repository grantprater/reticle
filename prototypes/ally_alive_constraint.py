r"""Bar dead teammates from ally pieces, and measure what the names become.

    .\.venv\Scripts\python.exe prototypes\ally_alive_constraint.py diagnose [SID ...]
    .\.venv\Scripts\python.exe prototypes\ally_alive_constraint.py measure [SID ...]
    .\.venv\Scripts\python.exe prototypes\ally_alive_constraint.py grids OUT_DIR SIDECAR [N]

Why. `ally-track-stitching` found icons on pieces the arbiter named for a
killfeed victim more than 700 ms after the death, on a fifth of ally deaths.
`identity.assign_ally_pieces` names pieces WITHOUT deaths, so nothing keeps a
dead teammate's name off a living teammate's piece.

Input. `ally_rendered_art_eval.entities` (the wired `session_lifetimes`,
rendered-art references, deaths=None) with `identity.assign_ally_pieces`
wrapped: the wrapper calls the owner unchanged on the owner's own input
(`base`), then once per dead-interval variant on the same input with each
piece's claims stripped of the teammates dead at any of its observations.
The owner draws a piece's admissible names from the keys of its icons'
`evidence.scores` and reads `S[p][a]` only for admissible `a`, so stripping
a key is exactly an admissibility input; an `admissible={piece: names}`
argument would be the owner-side form. Deaths are the ally `death_verdict`s;
a teammate is dead in a round from the death plus the variant's offset until
a revive entry (`is_revive`) names them, minus `WINDOW_MS[1]` of slack
[domain:rounds/resurrection-mechanics]. Variants: `after700` starts at
+700 ms (the stitch check's tolerance); `lead500` at -500 ms (the icon lead).
Cached in %TEMP%; no store writes, no decode.

`diagnose`: per non-revived death with late icons on victim-named `base`
pieces, whether the pieces' summed evidence ranks the victim first (the art)
or not (the assignment), the victim's gap, the alive teammates, whether the
victim was the piece's only positive alive option, whether another
teammate's last named icon ends at the death (a misread victim), and the
second-life agents separately.

`measure`: per variant, late-icon deaths, labels (`<store>/labels/death_icon`)
right/wrong/refused, frames naming one agent twice, pieces renamed.

`grids`: blind grids of icons whose piece name changes under `after700`
(`claude_icon_labels` layout with portrait references); old and new names go
only to SIDECAR, outside OUT_DIR.

Predictions and outcome: `ally-alive-constraint` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import copy
import json
import pickle
import random
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.adjudication import identity  # noqa: E402
from reticle.adjudication.identity import (load_ally_portrait_references,  # noqa: E402
                                           load_identity_gallery)
from reticle.lineup import load_lineup  # noqa: E402

import ally_rendered_art_eval as ev  # noqa: E402

STORE = ev.STORE
WORK = Path(tempfile.gettempdir()) / "reticle_ally_alive_constraint"
HI = ev.WINDOW_MS[1]
VARIANTS = {"after700": HI, "lead500": -ev.WINDOW_MS[0]}
SECOND_LIFE = {"Phoenix", "Sage", "Clove", "KAY/O", "KAY_O"}
_OWNER = identity.assign_ally_pieces


def dead_intervals(verdicts, offset):
    """{(round, agent): [(start, end)]}: dead from death + offset until a
    revive entry naming the agent (less HI of slack), else the round's end."""
    out = defaultdict(list)
    revs = [(float(v["t_ms"]), v["victim"], v.get("round_no")) for v in verdicts if v.get("is_revive")]
    for v in verdicts:
        if v.get("is_revive"):
            continue
        t, a, r = float(v["t_ms"]), v["victim"], v.get("round_no")
        end = min([tr for tr, ar, rr in revs if ar == a and rr == r and tr > t] or [np.inf])
        out[(r, a)].append((t + offset, end - HI))
    return out


def restrict(pieces, dead):
    """The owner's input with each piece's dead teammates' scores removed."""
    out = {}
    for pid, p in pieces.items():
        bar = {a for (r, a), iv in dead.items() if r == p["round"]
               for t in p["t"] for s, e in iv if s < t < e}
        if not bar:
            out[pid] = p
            continue
        q = dict(p)
        q["claims"] = []
        for c in p["claims"]:
            c = copy.deepcopy(c)
            sc = (c.get("evidence") or {}).get("scores")
            if sc:
                c["evidence"]["scores"] = {a: v for a, v in sc.items() if a not in bar}
            q["claims"].append(c)
        out[pid] = q
    return out


def session(sid: str) -> dict | None:
    path = WORK / f"{sid}.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    events = STORE.read_events("ally_icon", sid)
    lineup = load_lineup(sid, STORE.root)
    if not events or not lineup:
        return None
    verdicts = [v for v in STORE.read_events("death", sid)
                if v.get("kind") == "death_verdict" and v.get("side") == "ally" and v.get("victim")]
    cap = {}

    def wrapped(pieces, frames, capacity=None, *, teammate_fit=None):
        base = _OWNER(pieces, frames, capacity, teammate_fit=teammate_fit)
        cap["base"] = base
        for name, off in VARIANTS.items():
            cap[name] = _OWNER(restrict(pieces, dead_intervals(verdicts, off)), frames, capacity,
                               teammate_fit=teammate_fit)
        cap["pieces"], cap["frames"] = pieces, frames
        return base

    identity.assign_ally_pieces = wrapped
    try:
        man = STORE.read_manifest(sid)
        ev.entities(sid, man, events, lineup, load_identity_gallery(STORE.root),
                    load_ally_portrait_references(STORE.root))
    finally:
        identity.assign_ally_pieces = _OWNER
    if "base" not in cap:
        return None
    pieces = {}
    for pid, p in cap["pieces"].items():
        keys = [c["entity_id"].rsplit(":ally_icon:", 1)[-1] for c in p["claims"]]
        if len(keys) != len(p["t"]):
            raise RuntimeError(f"{sid} {pid}: {len(keys)} claims for {len(p['t'])} icons")
        pieces[pid] = {"round": p["round"], "obs": list(zip(p["t"], keys)),
                       "icon_scores": [(c.get("evidence") or {}).get("scores") or {}
                                       for c in p["claims"]]}
    names = sorted({a for v in cap["base"].values() for a in v["evidence_sum"]})
    d = {"sid": sid, "names": names, "pieces": pieces, "frames": cap["frames"],
         "verdicts": verdicts, **{k: cap[k] for k in ("base", *VARIANTS)}}
    WORK.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(d))
    return d


def late_deaths(d, naming):
    """Non-revived deaths and the late icons on victim-named pieces."""
    revs = [(float(v["t_ms"]), v["victim"], v.get("round_no")) for v in d["verdicts"] if v.get("is_revive")]
    for v in d["verdicts"]:
        if v.get("is_revive"):
            continue
        t, a, r = float(v["t_ms"]), v["victim"], v.get("round_no")
        revived = any(ar == a and rr == r and tr > t for tr, ar, rr in revs)
        late = {pid: [o for o in p["obs"] if o[0] > t + HI] for pid, p in d["pieces"].items()
                if p["round"] == r and naming[pid]["agent"] == a}
        yield t, a, r, revived, {k: v for k, v in late.items() if v}


def alive_at(d, r, t, offset=HI):
    dead = dead_intervals(d["verdicts"], offset)
    return {a for a in d["names"]
            if not any(s < t < e for s, e in dead.get((r, a), []))}


def diagnose(sids) -> dict:
    c, rows = Counter(), []
    for sid in sids:
        d = session(sid)
        if d is None:
            continue
        base = d["base"]
        last = defaultdict(float)
        for pid, p in d["pieces"].items():
            a = base[pid]["agent"]
            if a:
                last[(p["round"], a)] = max(last[(p["round"], a)], p["obs"][-1][0])
        for t, a, r, revived, late in late_deaths(d, base):
            if revived:
                c["revived_deaths_with_late" if late else "revived_deaths"] += 1
                continue
            c["deaths"] += 1
            if not late:
                continue
            c["deaths_late"] += 1
            c["deaths_late_second_life" if a in SECOND_LIFE else "deaths_late_other"] += 1
            if a in SECOND_LIFE:
                c["deaths_late_" + a] += 1
            art = asg = only = 0
            for pid, obs in late.items():
                ev_ = base[pid]["evidence_sum"]
                n = len(obs)
                if ev_ and max(ev_, key=ev_.get) == a:
                    art += n
                else:
                    asg += n
                al = alive_at(d, r, obs[0][0]) - {a}
                pos = [x for x in al if ev_.get(x, 0) > 0]
                only += n * (not pos)
                c["late_pieces"] += 1
                c["late_piece_gap_ge_gate" if (base[pid]["gap"] is None) else "late_piece_gap_set"] += 1
                c[f"late_piece_alive_others_{len(al)}"] += 1
            icon_victim = sum(1 for pid, obs in late.items()
                              for (tt, k), s in zip(d["pieces"][pid]["obs"], d["pieces"][pid]["icon_scores"])
                              if tt > t + HI and s and max(s, key=s.get) == a)
            n_late = sum(len(o) for o in late.values())
            c["late_icons"] += n_late
            c["late_icons_icon_best_is_victim"] += icon_victim
            c["late_icons_piece_best_is_victim"] += art
            c["late_icons_piece_best_not_victim"] += asg
            c["late_icons_victim_only_positive_alive"] += only
            c["deaths_late_mostly_art" if art > asg else "deaths_late_mostly_assignment"] += 1
            others_end = [b for b in d["names"] if b != a and t - ev.WINDOW_MS[0] <= last.get((r, b), -1) <= t + HI]
            c["deaths_late_other_name_ends_at_death"] += bool(others_end)
            rows.append({"sid": sid, "round": r, "t": t, "victim": a, "late": n_late,
                         "art": art, "assign": asg, "others_end": others_end})
    out = dict(sorted(c.items()))
    print(json.dumps(out, indent=1))
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "diagnose.json").write_text(json.dumps({"counts": out, "rows": rows}, indent=0), encoding="utf-8")
    return out


def measure(sids) -> dict:
    labs = ev.labels()
    tot = {k: Counter() for k in ("base", *VARIANTS)}
    ren = {k: Counter() for k in VARIANTS}
    for sid in sids:
        d = session(sid)
        if d is None:
            continue
        key_piece = {k: pid for pid, p in d["pieces"].items() for _, k in p["obs"]}
        for name in tot:
            nm, c = d[name], tot[name]
            for t, a, r, revived, late in late_deaths(d, nm):
                tag = "revived_" if revived else ""
                c[tag + "deaths"] += 1
                c[tag + "deaths_late"] += bool(late)
                c[tag + "late_icons"] += sum(len(o) for o in late.values())
            for k, lab in labs.items():
                if k in key_piece:
                    got = nm[key_piece[k]]["agent"]
                    c["lab_" + ("right" if got == lab["answer"] else "refused" if got is None else "wrong")] += 1
            for f, ids in d["frames"].items():
                n = Counter(nm[i]["agent"] for i in ids if nm[i]["agent"])
                c["frames_twice"] += any(v > 1 for v in n.values())
            c["named_pieces"] += sum(1 for v in nm.values() if v["agent"])
            c["named_obs"] += sum(len(d["pieces"][p]["obs"]) for p, v in nm.items() if v["agent"])
            if name in ren:
                for pid, v in nm.items():
                    old, new = d["base"][pid]["agent"], v["agent"]
                    if old != new:
                        k = ("named_to_other" if old and new else "named_to_refused" if old
                             else "refused_to_named")
                        ren[name][k] += 1
                        ren[name][k + "_obs"] += len(d["pieces"][pid]["obs"])
    out = {k: dict(sorted(v.items())) for k, v in tot.items()}
    for k, v in ren.items():
        out[k]["renamed"] = dict(sorted(v.items()))
    print(json.dumps(out, indent=1))
    (WORK / "measure.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def grids(sids, out: Path, sidecar: Path, n: int = 120) -> None:
    """One icon per renamed piece (a post-death one when the old name's
    death precedes it), in `claude_icon_labels` grids with references."""
    import cv2
    import claude_icon_labels as G
    import label_death_icons as L
    cand = []
    for sid in sids:
        d = session(sid)
        if d is None:
            continue
        deaths = {(v.get("round_no"), v["victim"]): float(v["t_ms"]) for v in d["verdicts"]
                  if not v.get("is_revive")}
        for pid, v in d["after700"].items():
            old, new = d["base"][pid]["agent"], v["agent"]
            if old == new:
                continue
            p = d["pieces"][pid]
            td = deaths.get((p["round"], old))
            post = [o for o in p["obs"] if td is not None and o[0] > td + HI]
            t, k = (post or p["obs"])[len(post or p["obs"]) // 2]
            cand.append({"sid": sid, "key": k, "t_ms": t, "piece": pid, "round": p["round"],
                         "old": old, "new": new, "post_death": bool(post), "n_obs": len(p["obs"]),
                         "evidence_sum": d["base"][pid]["evidence_sum"], "mates": d["names"]})
    random.Random(7).shuffle(cand)
    cand.sort(key=lambda u: not u["post_death"])      # post-death icons first
    items = cand[:n]
    random.Random(11).shuffle(items)
    out.mkdir(parents=True, exist_ok=True)
    crops, cells, meta, side = L.Crops(), {}, [], []
    for i, u in sorted(enumerate(items), key=lambda p: p[1]["sid"]):
        big, _ = crops.get(u["sid"], u["key"])
        cell = np.full((G.TILE + G.TEXT_H, G.TILE, 3), 24, np.uint8)
        cell[G.TEXT_H:G.TEXT_H + big.shape[0], :big.shape[1]] = big
        cv2.putText(cell, f"#{i + 1}", (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.putText(cell, " ".join(f"{j + 1}{a[:6]}" for j, a in enumerate(u["mates"])), (3, 29),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.33, (200, 230, 255), 1)
        cells[i] = np.vstack([cell, G._ref_row(u["mates"], cell.shape[1])])
    for i, u in enumerate(items):
        meta.append({"item": i + 1, "teammates": u["mates"]})
        side.append({"item": i + 1, **u})
    order = [cells[i] for i in range(len(items))]
    for g in range(0, len(order), G.PER_GRID):
        cs = order[g:g + G.PER_GRID]
        while len(cs) % G.COLS:
            cs.append(np.zeros_like(cs[0]))
        rows = [np.hstack(cs[i:i + G.COLS]) for i in range(0, len(cs), G.COLS)]
        cv2.imwrite(str(out / f"grid_{g // G.PER_GRID + 1}.png"), np.vstack(rows))
    (out / "items.json").write_text(json.dumps(meta, indent=0), encoding="utf-8")
    sidecar.write_text(json.dumps(side, indent=0), encoding="utf-8")
    print(f"{len(items)} of {len(cand)} renamed pieces ({sum(u['post_death'] for u in items)} "
          f"post-death icons) -> {out}; names in {sidecar}")


def main() -> None:
    cmd, rest = sys.argv[1], sys.argv[2:]
    all_sids = sorted(p.stem for p in (STORE.root / "events" / "round_entity").glob("*.jsonl"))
    if cmd == "grids":
        grids(all_sids, Path(rest[0]), Path(rest[1]), int(rest[2]) if len(rest) > 2 else 120)
        return
    sids = rest or all_sids
    for sid in sids:
        session(sid)
    diagnose(sids) if cmd == "diagnose" else measure(sids)


if __name__ == "__main__":
    main()
