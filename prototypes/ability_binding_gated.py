r"""Retry tray-cast binding with a death-gated witness and confounders removed.

    .\.venv\Scripts\python.exe prototypes\ability_binding_gated.py collect
    .\.venv\Scripts\python.exe prototypes\ability_binding_gated.py report
    .\.venv\Scripts\python.exe prototypes\ability_binding_gated.py montage OUT.png

Purpose. `ability_mined_references.py` bound 157 of 643 clean tray casts to a
new minimap candidate near the player, against 219 of 1233 cast-free
controls, and its mined references scored at chance. Two faults were named:
the witness (226 of the clean casts fall after the player's death, so they
are spectated teammates' casts, `tray_suspect_reasons.py`) and confounders
near the player (teammate icons, death X markers, map texture). This reruns
the same join on the same stored windows after removing both.

Step 1, witness. Casts keep only drops `tray_suspect_reasons.gated(...,
live_only=True)` calls clean. Controls pass the same death rule
(`tray_suspect_reasons.after_death`) and must fall in the live phase.

Step 2, confounders, each from a channel that already sees it:
`ally` -- a stored `ally_icon` icon or `round_entity` piece (ally, barrier,
self families) within its radius + ALLY_PAD of the candidate in at least
half the frames of its first ONSET_S; `death` -- the candidate appears within
DEATH_PRE_S before to DEATH_POST_S after a stored death verdict and within
DEATH_PX of the dying ally's last `round_entity` position (the player's last
self position for the player's own death); `death_time` reports the same
window with no location, an upper bound; `static` -- the same patch-minus-map
pattern already sits at the candidate's place in STATIC_N cached frames of
the same round before its onset, away from every tray drop. Removal happens
before the join, so a window can gain a binding as well as lose one.

Step 3. `ability_mined_references.evaluate` runs unchanged on the filtered
windows (its split, references and scores), through its module-level
`load`, `persistent` and `bound`.

Outcome (2026-09-26, falsified; 19 sessions). Death gate: casts bind
106/420 (0.25), controls 171/952 (0.18), unchanged from 157/643 vs 219/1233.
Of 3268 persistent candidates the stored ally channels flag 60, located
death markers 88 and texture 274 (131 unknown); among gated bindings they
remove ally 8 casts / 5 controls, death 1 / 2, texture 10 / 9. The time-only
death window would remove 47 / 56 and so does not separate. After all gates
casts bind 95/420 (0.23), controls 160/952 (0.17). Held out, the rebuilt
references pick the bound object 4/13 (chance 5.2), name its slot within the
kit 15/27 (chance 7.9, but always guessing each agent's commonest slot scores
17/27), and separate bound from control candidates at AUC 0.58 (response
0.56). The montage of bound objects shows enemy agent icons, enemy ability
markers, "?" last-seen marks, site letters and bare map, with a few orange
Blaze lines: no ability appearance recurs. The confounders the tray join
admits are mostly objects no gate here names, so tray casts do not label
minimap abilities; the player must.

Inputs: the work caches of `ability_mined_references` and
`tray_suspect_reasons` (15 Hz minimap roi cache, no decode), stored
`ally_icon`, `round_entity` and `death` events. Nothing is written to the
store. Predictions and outcome: task `ability-binding-gated` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import bisect
import json
import pickle
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_mined_references as amr  # noqa: E402
import tray_suspect_reasons as tsr  # noqa: E402

STORE = amr.STORE
WORK = Path(tempfile.gettempdir()) / "ability_binding_gated"
ALLY_PAD = 5.0
ONSET_S = 0.6
DEATH_PRE_S = 2.5
DEATH_POST_S = 1.0
DEATH_PX = 25.0
STATIC_N = 6
STATIC_GAP_S = 3.0
STATIC_COS = 0.8
GATES = ("ally", "death", "static")


def events(kind: str, sid: str):
    p = STORE / "events" / kind / f"{sid}.jsonl"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        yield json.loads(line)


class Pieces:
    """Stored ally icons and round-entity pieces per frame time (crop pixels)."""

    def __init__(self, sid: str):
        by = defaultdict(list)
        self.self_at = {}
        for r in events("ally_icon", sid):
            if r["kind"] == "icon":
                by[r["t_ms"]].append((r["cx"], r["cy"], r.get("r") or 9))
            elif r["kind"] == "frame" and r.get("self"):
                self.self_at[r["t_ms"]] = r["self"][:2]
        self.last = {}  # (round_no, agent) -> [(t_ms, x, y)]
        ent = {}
        obs = []
        for r in events("round_entity", sid):
            if r["kind"] == "observation" and r.get("x") is not None:
                by[r["t_ms"]].append((r["x"], r["y"], 9))
                obs.append((r["entity_id"], r["t_ms"], r["x"], r["y"]))
            elif r["kind"] == "entity" and r.get("agent"):
                ent[r["id"]] = (r["round_no"], r["agent"])
        for eid, t, x, y in obs:
            if eid in ent:
                self.last.setdefault(ent[eid], []).append((t, x, y))
        self.t = sorted(by)
        self.by = by
        self.st = sorted(self.self_at)

    def frames(self, t0_ms, t1_ms):
        i, j = bisect.bisect_left(self.t, t0_ms), bisect.bisect_right(self.t, t1_ms)
        return [self.by[t] for t in self.t[i:j]]

    def position_before(self, key, t_ms):
        """Last stored position of a round entity (round_no, agent) at or before t."""
        pts = [p for p in self.last.get(key, []) if p[0] <= t_ms]
        return max(pts)[1:] if pts else None

    def self_before(self, t_ms):
        i = bisect.bisect_right(self.st, t_ms) - 1
        return self.self_at[self.st[i]] if i >= 0 and t_ms - self.st[i] < 5000 else None


def death_marks(sid: str, pieces: Pieces) -> list[tuple]:
    """(t_s, xy or None) for every stored death verdict; xy is the victim's last place."""
    out = []
    for r in events("death", sid):
        if r["kind"] != "death_verdict":
            continue
        t = r["t_ms"]
        xy = None
        if (r.get("metadata") or {}).get("is_player_death"):
            xy = pieces.self_before(t)
        elif r.get("side") == "ally" and r.get("victim"):
            xy = pieces.position_before((r.get("round_no"), r["victim"]), t + DEATH_POST_S * 1000)
        out.append((t / 1000.0, xy))
    return out


def context(d_tsr: dict, t: float, deaths: list[float]) -> dict:
    """rel_death and phase for an arbitrary time, as `tray_suspect_reasons.drops` gives a drop."""
    si = next((i for i, (a, b) in enumerate(d_tsr["spans"]) if a / 1000 <= t <= b / 1000), None)
    if si is None:
        return {"rel_death": None, "phase": "outside"}
    sa, sb = d_tsr["spans"][si]
    rnd = next((r for r in d_tsr["rounds"] if r["t_start_ms"] <= sa + 1000 < r["t_close_ms"] + 1),
               None)
    t_end = rnd["t_end_ms"] / 1000.0 if rnd else sb / 1000.0
    dth = [x for x in deaths if sa / 1000.0 <= x <= sb / 1000.0]
    phase = "barrier" if t < sa / 1000.0 + 1.0 else "live" if t <= t_end else "post_round"
    return {"rel_death": float(t - dth[0]) if dth else None, "phase": phase, "span": (sa, sb)}


def is_ally(c: dict, pieces: Pieces, sc: float) -> bool:
    fr = pieces.frames(c["t_on"] * 1000, (c["t_on"] + ONSET_S) * 1000)
    if not fr:
        return False
    hit = sum(any(np.hypot(c["cx"] - x, c["cy"] - y) < (r + ALLY_PAD) * sc for x, y, r in f)
              for f in fr)
    return hit >= 0.5 * len(fr)


def is_death(c: dict, marks: list[tuple], sc: float, located: bool) -> bool:
    for t, xy in marks:
        if not (t - DEATH_PRE_S <= c["t_on"] <= t + DEATH_POST_S):
            continue
        if not located:
            return True
        if xy is not None and np.hypot(c["cx"] - xy[0], c["cy"] - xy[1]) < DEATH_PX * sc:
            return True
    return False


def snap(cache, times_s) -> list[float]:
    """The cached frame times (ms) nearest each wanted time (s), without repeats."""
    t = np.unique(np.asarray(cache.t_ms, float))
    i = np.searchsorted(t, np.asarray(times_s, float) * 1000.0).clip(1, len(t) - 1)
    near = np.where(np.abs(t[i - 1] - np.asarray(times_s) * 1000.0)
                    < np.abs(t[i] - np.asarray(times_s) * 1000.0), t[i - 1], t[i])
    return [float(x) for x in dict.fromkeys(near.tolist())]


def static_score(ctx, cache, c: dict, span, drop_t: list[float]) -> float | None:
    """Share of cast-free frames before onset, same round, holding the candidate's pattern."""
    t0, t1 = span[0] / 1000 + 1.0, c["t_on"] - 1.5
    if t1 - t0 < 1.0:
        return None
    want = [t for t in np.linspace(t0, t1, 4 * STATIC_N)
            if all(abs(t - d) >= STATIC_GAP_S for d in drop_t)]
    if len(want) < 3:
        return None
    want = [want[i] for i in np.linspace(0, len(want) - 1, min(STATIC_N, len(want))).astype(int)]
    ref = c["desc"][: amr.PATCH * amr.PATCH * 3]
    nr = np.linalg.norm(ref)
    hits = n = 0
    for smp in cache.samples(snap(cache, want), rois=["minimap"]):
        d = ctx.descriptor(ctx.crop(smp.frame), c["cx"], c["cy"])
        if d is None:
            continue
        p = d[: amr.PATCH * amr.PATCH * 3]
        n += 1
        hits += (np.linalg.norm(p) >= 0.5 * nr) and amr.cos(p, ref) >= STATIC_COS
    return hits / n if n else None


def collect_session(sid: str, d_amr: dict, d_tsr: dict) -> dict:
    """Per-candidate gate flags for every persistent candidate, plus cast/control gating."""
    drops = [dict(r, sid=sid) for r in tsr.drops(d_tsr)]
    clean = {(round(r["t"], 3), r["slot"]) for r in tsr.gated(drops, live_only=True)
             if not r["suspect_gated"]}
    deaths = tsr.player_deaths(sid)
    ctrl_ok = []
    for r in d_amr["controls"]:
        cx = context(d_tsr, r["t"], deaths)
        ctrl_ok.append(cx["phase"] == "live" and not tsr.after_death(cx))
    pieces = Pieces(sid)
    marks = death_marks(sid, pieces)
    _man, cache = amr.open_cache(sid)
    ctx = amr.MapContext(sid, cache)
    drop_t = [r["t"] for r in drops]
    flags = {}
    for grp, rows in (("casts", d_amr["casts"]), ("controls", d_amr["controls"])):
        for wi, w in enumerate(rows):
            keep = {id(x) for x in amr.persistent(w)}
            for ci, c in enumerate(w.get("cands", [])):
                if id(c) not in keep:
                    continue
                span = context(d_tsr, c["t_on"], deaths).get("span")
                st = static_score(ctx, cache, c, span, drop_t) if span else None
                flags[(grp, wi, ci)] = {
                    "ally": is_ally(c, pieces, ctx.sc),
                    "death": is_death(c, marks, ctx.sc, True),
                    "death_time": is_death(c, marks, ctx.sc, False),
                    "static_score": st, "static": st is not None and st >= 0.5}
    return {"sid": sid, "cast_clean": [(round(r["t"], 3), r["slot"]) in clean
                                       for r in d_amr["casts"]],
            "ctrl_ok": ctrl_ok, "flags": flags, "n_clean_gated": len(clean),
            "marks_located": sum(xy is not None for _t, xy in marks), "marks": len(marks)}


def filtered(d_amr: dict, g: dict, gates=GATES) -> dict:
    """A copy of the session's windows: gated casts clean, gated controls, confounders dropped."""
    def keep(grp, wi, w):
        out = dict(w)
        if "cands" in w:
            out["cands"] = [c for ci, c in enumerate(w["cands"])
                            if not any(g["flags"].get((grp, wi, ci), {}).get(k) for k in gates)]
        return out
    casts = [dict(keep("casts", i, w), suspect=not ok)
             for i, (w, ok) in enumerate(zip(d_amr["casts"], g["cast_clean"]))]
    ctrl = [keep("controls", i, w) for i, (w, ok) in enumerate(zip(d_amr["controls"], g["ctrl_ok"]))
            if ok]
    return {**d_amr, "casts": casts, "controls": ctrl}


def rates(data: dict) -> dict:
    """Bound clean casts per agent:slot:ability and bound controls, as 'b/n'."""
    per = defaultdict(lambda: [0, 0])
    for d in data.values():
        for r in d["casts"]:
            if not r["suspect"]:
                k = f"{d['agent']}:{r['slot']}:{d['kit'].get(r['slot'])}"
                per[k][0] += 1
                per[k][1] += amr.bound(r) is not None
    n = sum(v[0] for v in per.values())
    b = sum(v[1] for v in per.values())
    ctrl = [r for d in data.values() for r in d["controls"]]
    cb = sum(amr.bound(r) is not None for r in ctrl)
    return {"casts": f"{b}/{n}", "cast_rate": round(b / max(1, n), 3),
            "controls": f"{cb}/{len(ctrl)}", "control_rate": round(cb / max(1, len(ctrl)), 3),
            "per_ability": {k: f"{v[1]}/{v[0]}" for k, v in sorted(per.items())}}


def removed(orig: dict, data: dict, gate: str) -> dict:
    """Bindings of the gated windows (no confounder removal) the gate's candidates made."""
    out = Counter()
    for sid, d in orig.items():
        for grp in ("casts", "controls"):
            for w in d[grp]:
                if grp == "casts" and w["suspect"]:
                    continue
                b = amr.bound(w)
                if b is not None and b.get("_gate", {}).get(gate):
                    out[grp] += 1
    return dict(out)


def load_gated(work: Path):
    amr_data = amr.load(amr.WORK)
    gates = {f.stem: pickle.loads(f.read_bytes()) for f in sorted(work.glob("*.pkl"))}
    return {s: d for s, d in amr_data.items() if s in gates}, gates


def report(work: Path) -> dict:
    amr_data, gates = load_gated(work)
    orig = {s: {**d, "casts": [dict(r) for r in d["casts"]]} for s, d in amr_data.items()}
    out = {"sessions": len(gates), "original": rates(orig)}
    step1 = {s: filtered(d, gates[s], gates=()) for s, d in amr_data.items()}
    out["step1_death_gated"] = rates(step1)
    # Tag each candidate with its flags so a binding can say which gate would remove it.
    for s, d in step1.items():
        for grp in ("casts", "controls"):
            idx = range(len(amr_data[s][grp]))
            src = [i for i in idx if grp == "casts" or gates[s]["ctrl_ok"][i]]
            for w, wi in zip(d[grp], src):
                w["cands"] = [dict(c, _gate=gates[s]["flags"].get((grp, wi, ci), {}))
                              for ci, c in enumerate(w.get("cands", []))]
    out["step2_bound_removed_by"] = {g: removed(step1, step1, g)
                                     for g in ("ally", "death", "death_time", "static")}
    fl = [f for g in gates.values() for f in g["flags"].values()]
    out["step2_candidates_flagged"] = {"persistent": len(fl),
                                       **{k: sum(bool(f[k]) for f in fl)
                                          for k in ("ally", "death", "death_time", "static")},
                                       "static_unknown": sum(f["static_score"] is None for f in fl)}
    out["death_marks_located"] = f"{sum(g['marks_located'] for g in gates.values())}/" \
                                 f"{sum(g['marks'] for g in gates.values())}"
    for name, gs in (("step2_ally", ("ally",)), ("step2_ally_death", ("ally", "death")),
                     ("step2_all", GATES)):
        out[name] = rates({s: filtered(d, gates[s], gs) for s, d in amr_data.items()})
    final = {s: filtered(d, gates[s], GATES) for s, d in amr_data.items()}
    amr.load = lambda _work: final
    ev = amr.evaluate(work)
    out["step3"] = {k: ev.get(k) for k in ("references", "labels", "held_pick_in_window",
                                            "held_kit", "held_bound_vs_control_auc", "tau")}
    # Kit chance: each held label scored among its own agent's references.
    refs = [tuple(k.split(":")) for k in ev.get("references", [])]
    kit = Counter(a for a, _s in refs)
    out["step3"]["held_kit_chance"] = round(sum(
        v["held"] / kit[a] for k, v in ev.get("labels", {}).items()
        for a, s in [tuple(k.split(":"))] if (a, s) in refs and kit[a] >= 2), 1)
    return out


def montage(work: Path, out_png: Path, n: int = 10) -> None:
    """Bound objects per ability after all gates: 41 px crops at onset + 0.4 s."""
    amr_data, gates = load_gated(work)
    final = {s: filtered(d, gates[s], GATES) for s, d in amr_data.items()}
    by = defaultdict(list)
    for s, d in final.items():
        for r in d["casts"]:
            b = None if r["suspect"] else amr.bound(r)
            if b is not None:
                by[f"{d['agent']}:{r['slot']}:{d['kit'].get(r['slot'])}"].append((s, b))
    rng = np.random.default_rng(3)
    rows = []
    for k in sorted(by):
        pick = [by[k][i] for i in sorted(rng.choice(len(by[k]), min(n, len(by[k])),
                                                    replace=False))]
        tiles = []
        for s, b in pick:
            _man, cache = amr.open_cache(s)
            x0, y0, _x1, _y1 = cache.rect_of("minimap")
            smp = next(iter(cache.samples(snap(cache, [b["t_on"] + 0.4]), rois=["minimap"])), None)
            x, y = int(b["cx"]) + x0, int(b["cy"]) + y0
            img = np.zeros((41, 41, 3), np.uint8)
            if smp is not None:
                p = smp.frame[max(0, y - 20):y + 21, max(0, x - 20):x + 21]
                img[:p.shape[0], :p.shape[1]] = p
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            cv2.drawMarker(img, (41, 41), (0, 255, 0), cv2.MARKER_CROSS, 8, 1)
            tiles.append(img)
        tiles += [np.zeros_like(tiles[0])] * (n - len(tiles))
        lab = np.zeros((14, 82 * n, 3), np.uint8)
        cv2.putText(lab, f"{k} n={len(by[k])}", (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (255, 255, 255), 1)
        rows.append(np.vstack([lab, np.hstack(tiles)]))
    cv2.imwrite(str(out_png), np.vstack(rows))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "report", "montage"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    if a.cmd == "collect":
        amr_data = amr.load(amr.WORK)
        for sid in a.args or sorted(amr_data):
            f = a.work / f"{sid}.pkl"
            t = tsr.WORK / f"{sid}.pkl"
            if f.exists() or not t.exists():
                continue
            g = collect_session(sid, amr_data[sid], pickle.loads(t.read_bytes()))
            f.write_bytes(pickle.dumps(g))
            print(sid, g["n_clean_gated"], sum(g["ctrl_ok"]), len(g["flags"]),
                  dict(Counter(k for fl in g["flags"].values() for k in GATES if fl[k])),
                  flush=True)
    elif a.cmd == "report":
        print(json.dumps(report(a.work), indent=1, default=str))
    else:
        montage(a.work, Path(a.args[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
