r"""What sampling rate does minimap ally identity need?

    .\.venv\Scripts\python.exe prototypes\minimap_fidelity.py SID ... \
        --icons-store SCRATCH --out DIR [--write-stores DIR] [--rates 15 5 2]
    .\.venv\Scripts\python.exe prototypes\minimap_fidelity.py --report DIR
    .\.venv\Scripts\python.exe prototypes\minimap_fidelity.py --sheet DIR --pair 15 2

Measured, not wired. Reading, not decoding, is the cost that scales with rate.

**The streams.** `AllyIconReader` reads each frame alone, so one pass over
the 15 Hz minimap crop cache holds every lower rate: the 5 and 2 Hz streams
are the rows at the cached times nearest each decode instant, as
`roi_cache.nearest_times` picks them for a reader that declares
`cache_resample = "nearest"` (the asked spans and the clip from the stream's
coverage row). The rates therefore see the same pixels on the same frames;
only the frames kept differ, and every comparison is paired. `--icons-store`
names the scratch store the 15 Hz pass wrote; without it the real store's
stream is read (it may be stale).

**The builds.** Per rate the round entities are built twice with the inputs
`reticle lifetimes` gives `round_entities.session_lifetimes` (rounds, roster,
lineup, gallery, rendered portrait references, menu witness):

* the production build, with the stored death verdicts, which also bar a
  dead teammate from the pieces seen while dead; `--write-stores` writes its
  `round_entity` rows and the subset `ally_icon` stream per rate;
* the independent build, without deaths, scored against the killfeed: a
  teammate death (the player's own excluded: he draws no ally icon) that
  exactly one ally segment ends within [-500, +700] ms of names that segment;
  a second window moves the early edge back one sampling step, since a slower
  rate last sees the dying icon up to one step earlier.

**The measures, per round.** Ally segments and pieces, named share, the
player's `labels/death_icon` answers, and the invariant checks: pieces of one
segment named differently (a swap the Viterbi split found), one agent on two
icons in a frame, one agent's pieces overlapping in time, reachability
breaks between consecutive observations of one named teammate (`RUN_PX` over
the interval plus `REFIT_SEPARATION_PX` and twice `FIT_ERR_PX`, all scaled),
births far from every recent track end and every icon, teammate deaths with
no segment ending near them, frames holding more ally icons than the roster
licenses, pieces the dead-teammate bar touched, refusal reasons and endings.
`--report` bootstraps rounds (paired across rates) and matches each flagged
violation across rates (same round, within 1 s, same agent or within 30 px),
so what one rate flags and another misses is listed; `--sheet` draws those
from the crop cache. Agreement between rates is consistency, not accuracy:
the sheets and the labels are the check.

Results: docs/ALLY_RATE.md. Predictions and outcomes: `minimap-fidelity`
(2026-09-25) and `ally-rate-20260929` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.cli import _date_of  # noqa: E402
from reticle.minimap import FIT_ERR_PX, RUN_PX, minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import nearest_times  # noqa: E402
from reticle.round_entities import _roster_window, ally_dead_intervals, session_lifetimes  # noqa: E402
from reticle.round_lifetimes import (OCCLUSION_RADIUS_PX, REFIT_SEPARATION_PX,  # noqa: E402
                                     ally_capacity)
from reticle.rounds import build_rounds  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
RATES = (15.0, 5.0, 2.0)
DEATH_WINDOW_MS = (500.0, 700.0)
GAP_MS = 200.0
#: A birth this long after the round's first ally frame is mid-round.
SPAWN_MS = 3000.0
#: Track ends this recent can explain a birth.
BIRTH_LOOKBACK_MS = 3000.0
#: Violations at two rates are one when this close in time.
MATCH_MS = 1000.0
MATCH_PX = 30.0
#: A labelled icon is sought in the rate's nearest frame within this.
LABEL_DT_MS = 300.0


# ---------------------------------------------------------------- streams --

def rate_times(events: list[dict], hz: float) -> set[float]:
    """The frame times a `hz` nearest resample keeps from a 15 Hz stream; at
    the stream's own rate, every frame (`roi_cache.resamples` is False)."""
    t = sorted(e["t_ms"] for e in events if e.get("kind") == "frame")
    if hz >= float(events[0].get("hz") or 0):
        return set(t)
    clip = events[0].get("spans_clip")
    if clip and clip.get("spans_asked"):
        asked, held = clip["spans_asked"], clip["spans_read"]
    else:                               # no clip recorded: the stream's own runs
        held, a = [], t[0]
        for p, q in zip(t, t[1:]):
            if q - p > GAP_MS:
                held.append((a, p))
                a = q
        held.append((a, t[-1]))
        asked = held
    return set(nearest_times(t, asked, held, 1.0 / hz))


def subset(events: list[dict], keep: set[float], hz: float) -> list[dict]:
    """The coverage row (at `hz`), the kept frames and their icons."""
    frames = [e for e in events if e.get("kind") == "frame" and e["t_ms"] in keep]
    idx = {f["frame_idx"] for f in frames}
    cov = {**events[0], "hz": hz, "subset_of_hz": events[0].get("hz"),
           "subset_rule": "roi_cache.nearest_times"}
    return [cov] + frames + [e for e in events if e.get("kind") == "icon" and e["frame_idx"] in idx]


def inputs(sid: str) -> dict:
    """What `reticle lifetimes` passes `session_lifetimes`, from the real store."""
    from reticle.adjudication.identity import load_ally_portrait_references, load_identity_gallery
    from reticle.lineup import load_lineup
    from reticle.menu import stored_menu

    man = STORE.read_manifest(sid)
    date = _date_of(man)
    roster = None
    if STORE.has_roster(sid, date):
        t = STORE.read_roster(sid, date)
        roster = {"t_ms": t.column("t_ms").to_pylist(), "alive_ally": t.column("alive_ally").to_pylist()}
    box = minimap_roi_px(get_profile(man["source_profile"]), int(man["source"]["width"]),
                         int(man["source"]["height"]))
    lineup = load_lineup(sid, STORE.root)
    menu, _ = stored_menu(STORE, sid)
    return {"manifest": man, "rounds": build_rounds(STORE.read_hud(sid, date)), "roster": roster,
            "deaths": STORE.read_events("death", sid) if STORE.has_events("death", sid) else None,
            "scale": widget_scale(box[2] - box[0]), "box": box, "lineup": lineup,
            "references": load_ally_portrait_references(STORE.root) if lineup else None,
            "gallery": load_identity_gallery(STORE.root) if lineup else None,
            "menu": menu.at if menu is not None else None,
            "player": ((lineup or {}).get("player") or {}).get("agent")}


def rate_entities(sid: str, events: list[dict], inp: dict, with_deaths: bool, revision: str | None):
    return session_lifetimes(sid, events, inp["rounds"], inp["scale"], inp["roster"], revision,
                             deaths=inp["deaths"] if with_deaths else None, lineup=inp["lineup"],
                             gallery=inp["gallery"], references=inp["references"], menu=inp["menu"])


# --------------------------------------------------------------- measures --

def _parse(rows: list[dict]):
    ents = {e["id"]: e for e in rows if e.get("kind") == "entity" and e.get("family") == "ally"}
    obs = defaultdict(list)            # piece -> [(t, x, y)]
    frames = defaultdict(list)         # (round, t) -> [(piece, x, y)]
    selfs = defaultdict(list)          # round -> [(t, x, y)]
    for o in rows:
        if o.get("kind") != "observation":
            continue
        if o.get("family") == "self":
            selfs[o["round_no"]].append((o["t_ms"], o["x"], o["y"]))
        elif o.get("entity_id") in ents:
            obs[o["entity_id"]].append((o["t_ms"], o["x"], o["y"]))
            frames[(o["round_no"], o["t_ms"])].append((o["entity_id"], o["x"], o["y"]))
    for k in obs:
        obs[k].sort()
    return ents, obs, frames, selfs


def _seg(e: dict) -> str:
    return e.get("segment_id") or e["id"]


def _segments(ents, obs):
    """segment -> {"round", "pieces" (in order), "first", "last", "agent" (last piece's)}"""
    segs = {}
    for pid, e in ents.items():
        if not obs.get(pid):
            continue
        s = segs.setdefault(_seg(e), {"round": e["round_no"], "pieces": []})
        s["pieces"].append((e.get("piece_index", 0), pid))
    for s in segs.values():
        s["pieces"] = [p for _, p in sorted(s["pieces"])]
        s["first"] = obs[s["pieces"][0]][0]
        s["last"] = obs[s["pieces"][-1]][-1]
        s["agent"] = ents[s["pieces"][-1]].get("agent")
    return segs


def teammate_deaths(inp: dict) -> list[dict]:
    return [d for d in inp["deaths"] or () if d.get("kind") == "death_verdict"
            and d.get("side") == "ally" and d.get("victim") and d.get("victim") != inp["player"]
            and not d.get("is_revive") and not d.get("is_second_life")]


def death_identity(rows, inp, widen_ms: float = 0.0) -> tuple[dict, list[dict]]:
    """{round: Counter} of killfeed identity for segment ends (independent
    build), and one row per teammate death. `widen_ms` moves the window's
    early edge back: a slower rate's last look falls up to one step earlier."""
    ents, obs, _, _ = _parse(rows)
    segs = _segments(ents, obs)
    lo, hi = DEATH_WINDOW_MS
    lo += widen_ms
    out, per = defaultdict(Counter), []
    for d in teammate_deaths(inp):
        t, a, rno = float(d["t_ms"]), d["victim"], d.get("round_no")
        c = out[rno]
        c["deaths"] += 1
        ends = [s for s in segs.values() if s["round"] == rno and t - lo <= s["last"][0] <= t + hi]
        if len(ends) != 1:
            k = "unbound_none" if not ends else "unbound_many"
            c[k] += 1
            per.append({"death_id": d.get("death_id"), "round": rno, "victim": a, "result": k})
            continue
        c["bound"] += 1
        got = ends[0]["agent"]
        k = "seg_right" if got == a else "seg_none" if got is None else "seg_wrong"
        c[k] += 1
        per.append({"death_id": d.get("death_id"), "round": rno, "victim": a, "result": k,
                    "got": got, "end_ms": ends[0]["last"][0] - t})
    return out, per


def label_scores(rows, labels: list[dict], scale: float) -> list[dict]:
    """Each death_icon label against the rate's nearest frame and icon."""
    ents, obs, frames, _ = _parse(rows)
    times = defaultdict(list)
    for (rno, t) in frames:
        times[rno].append(t)
    allt = np.array(sorted({t for (_, t) in frames}))
    out = []
    for lab in labels:
        t = float(lab["t_ms"])
        res = {"key": lab["key"], "answer": lab["answer"]}
        if not len(allt):
            out.append({**res, "result": "no_frame"})
            continue
        j = int(np.argmin(np.abs(allt - t)))
        tf = float(allt[j])
        if abs(tf - t) > LABEL_DT_MS:
            out.append({**res, "result": "no_frame"})
            continue
        cands = [(math.hypot(x - lab["cx"], y - lab["cy"]), pid) for (rno, tt), lst in frames.items()
                 if tt == tf for pid, x, y in lst]
        tol = 3.0 * float(lab.get("r") or 8) + RUN_PX * scale * abs(tf - t) / 1000.0
        cands = [c for c in cands if c[0] <= tol]
        if not cands:
            out.append({**res, "result": "no_icon", "dt_ms": tf - t})
            continue
        got = ents[min(cands)[1]].get("agent")
        out.append({**res, "result": "right" if got == lab["answer"] else "unnamed" if got is None
                    else "wrong", "got": got, "dt_ms": tf - t})
    return out


def invariants(rows, inp: dict) -> tuple[dict, list[dict]]:
    """Per-round counts and the flagged events of the production build."""
    ents, obs, frames, selfs = _parse(rows)
    segs = _segments(ents, obs)
    sc = inp["scale"]
    tol = (REFIT_SEPARATION_PX + 2 * FIT_ERR_PX) * sc
    rt = (inp["roster"] or {}).get("t_ms", [])
    ra = (inp["roster"] or {}).get("alive_ally", [])
    per = defaultdict(Counter)
    ev: list[dict] = []

    def flag(kind, rno, t, **kw):
        ev.append({"kind": kind, "round": rno, "t_ms": t, **kw})

    by_round = defaultdict(list)
    for sid_, s in segs.items():
        by_round[s["round"]].append((sid_, s))
    for pid, e in ents.items():
        rno = e["round_no"]
        c = per[rno]
        c["pieces"] += 1
        c["pieces_named"] += bool(e.get("agent"))
        c["obs"] += len(obs.get(pid, ()))
        c["obs_named"] += len(obs.get(pid, ())) if e.get("agent") else 0
        if e.get("identity_barred"):
            c["barred_pieces"] += 1
        if not e.get("agent") and e.get("identity_reason"):
            c["refused:" + str(e["identity_reason"]).split(":")[0].split(" ")[0][:40]] += 1
        if e.get("piece_index", 0) == e.get("pieces_of_segment", 1) - 1:
            c["end:" + str(e.get("end_reason"))[:40]] += 1
    for rno, lst in by_round.items():
        c = per[rno]
        c["segments"] += len(lst)
        # swaps: one segment, pieces named differently
        for sid_, s in lst:
            names = [ents[p].get("agent") for p in s["pieces"]]
            for a, b, p in zip(names, names[1:], s["pieces"][1:]):
                if a and b and a != b:
                    t, x, y = obs[p][0]
                    flag("swap", rno, t, agent=b, prev=a, x=x, y=y, piece=p)
        # one agent's pieces overlapping in time
        named = defaultdict(list)
        for sid_, s in lst:
            for p in s["pieces"]:
                if ents[p].get("agent"):
                    named[ents[p]["agent"]].append((obs[p][0][0], obs[p][-1][0], p))
        for a, iv in named.items():
            iv.sort()
            for i in range(len(iv)):
                for j in range(i + 1, len(iv)):
                    if iv[j][0] < iv[i][1]:
                        t = iv[j][0]
                        _, x, y = obs[iv[j][2]][0]
                        flag("overlap", rno, t, agent=a, x=x, y=y, pieces=[iv[i][2], iv[j][2]],
                             overlap_ms=min(iv[i][1], iv[j][1]) - iv[j][0])
        # reachability: consecutive observations of one named teammate
        for a, iv in named.items():
            pts = sorted((t, x, y, p) for _, _, p in iv for t, x, y in obs[p])
            for (t0, x0, y0, p0), (t1, x1, y1, p1) in zip(pts, pts[1:]):
                dt = t1 - t0
                if dt <= 0:
                    continue
                d = math.hypot(x1 - x0, y1 - y0)
                if d > RUN_PX * sc * dt / 1000.0 + tol:
                    flag("reach", rno, t1, agent=a, x=x1, y=y1, x0=x0, y0=y0, t0=t0, d_px=round(d, 1),
                         dt_ms=dt, across="within_piece" if p0 == p1 else
                         "within_segment" if _seg(ents[p0]) == _seg(ents[p1]) else "handoff")
        # births far from every recent track end and every icon
        allobs = sorted((t, x, y, sid_) for sid_, s in lst for p in s["pieces"] for t, x, y in obs[p])
        start = min((t for t, _, _, _ in allobs), default=0)
        for sid_, s in lst:
            tb, xb, yb = s["first"]
            if tb < start + SPAWN_MS:
                continue
            ok = any(0 < tb - o["last"][0] <= BIRTH_LOOKBACK_MS and math.hypot(
                o["last"][1] - xb, o["last"][2] - yb) <= RUN_PX * sc * (tb - o["last"][0]) / 1000 + tol
                for k, o in lst if k != sid_)
            near = OCCLUSION_RADIUS_PX * sc
            ok = ok or any(tb - 1000 <= t <= tb and k != sid_ and math.hypot(x - xb, y - yb) <= near
                           for t, x, y, k in allobs)
            ok = ok or any(tb - 1000 <= t <= tb and math.hypot(x - xb, y - yb) <= near
                           for t, x, y in selfs.get(rno, ()))
            if not ok:
                flag("orphan_birth", rno, tb, x=xb, y=yb, segment=sid_,
                     agent=ents[s["pieces"][0]].get("agent"))
    # teammate deaths with no segment ending near them
    lo, hi = DEATH_WINDOW_MS
    for d in teammate_deaths(inp):
        t, rno = float(d["t_ms"]), d.get("round_no")
        ends = [s for _, s in by_round.get(rno, ()) if t - lo <= s["last"][0] <= t + hi]
        per[rno]["teammate_deaths"] += 1
        if not ends:
            flag("death_no_end", rno, t, agent=d["victim"])
    # the dead-teammate bar: named observations inside their own dead interval
    ends_ = {r["round_no"]: r["t_end_ms"] for r in inp["rounds"]}
    dead = ally_dead_intervals(inp["deaths"], ends_, rt, ra)
    for pid, e in ents.items():
        a, rno = e.get("agent"), e["round_no"]
        for s0, s1, _ in (dead.get(rno) or {}).get(a, ()):
            for t, x, y in obs[pid]:
                if s0 <= t <= s1:
                    flag("named_while_dead", rno, t, agent=a, x=x, y=y)
                    break
    # one agent on two icons in a frame; more icons than the roster licenses
    self_t = {(rno, t) for rno, lst in selfs.items() for t, _, _ in lst}
    for (rno, t), lst in frames.items():
        per[rno]["frames"] += 1
        names = Counter(ents[p].get("agent") for p, _, _ in lst if ents[p].get("agent"))
        for a, n in names.items():
            if n > 1:
                flag("dup_frame", rno, t, agent=a)
        cap = ally_capacity(_roster_window(rt, ra, t) if rt else None, (rno, t) in self_t)
        if cap is not None and len(lst) > cap:
            p, x, y = lst[0]
            flag("over_capacity", rno, t, x=x, y=y, n=len(lst), cap=cap)
    episodes = merge_episodes(ev)
    for e in ev:
        per[e["round"]][e["kind"] + "_raw"] += 1
    for e in episodes:
        per[e["round"]][e["kind"]] += 1
    return {r: dict(c) for r, c in per.items()}, episodes


def merge_episodes(ev: list[dict]) -> list[dict]:
    """Flags of one kind, round and agent less than `MATCH_MS` apart are one
    episode (its first flag, with `n` flags and `until_ms`), so a rate that
    looks more often does not count one event more often."""
    out, last = [], {}
    for e in sorted(ev, key=lambda e: (e["kind"], str(e["round"]), str(e.get("agent")), e["t_ms"])):
        k = (e["kind"], e["round"], e.get("agent"))
        cur = last.get(k)
        if cur is not None and e["t_ms"] - cur["until_ms"] <= MATCH_MS:
            cur["n"] += 1
            cur["until_ms"] = e["t_ms"]
            continue
        cur = {**e, "n": 1, "until_ms": e["t_ms"]}
        last[k] = cur
        out.append(cur)
    return out


def round4_oracle(rows) -> dict:
    ents, obs, _, _ = _parse(rows)
    named = Counter(e.get("agent") for e in ents.values() if e["round_no"] == 4 and e.get("agent"))
    oracle = {"Breach", "Deadlock", "Reyna", "Miks"}
    return {"named": dict(named), "outside_oracle": sorted(set(named) - oracle),
            "oracle_named": len(set(named) & oracle)}


def death_icon_labels(sid: str) -> list[dict]:
    p = STORE.root / "labels" / "death_icon" / f"{sid}.jsonl"
    if not p.is_file():
        return []
    rows = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            rows[r["key"]] = r                       # last write wins
    return [r for r in rows.values() if r.get("class") == "agent" and not r.get("uncertain")
            and r.get("answer")]


# ------------------------------------------------------------------- run --

def _first_stamp(path: Path):
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        row = json.loads(f.readline() or "{}")
    return row.get("scoreboard_version") or row.get("version")


def run_session(sid: str, icons_store: Store, out: Path, rates, write_stores: Path | None) -> dict:
    events = icons_store.read_events("ally_icon", sid)
    if not events:
        raise SystemExit(f"{sid}: no ally_icon events in {icons_store.root}")
    inp = inputs(sid)
    labels = death_icon_labels(sid)
    res = {"session_id": sid, "stream": {k: events[0].get(k) for k in (
        "ally_icon_version", "hz", "candidate_revision", "frames_from")}, "rates": {},
        # the lineup names only unrefused slots; a scoreboard rescan moves it
        "lineup_ally": [[s.get("agent"), s.get("best_guess"), s.get("reason")]
                        for s in ((inp["lineup"] or {}).get("sides") or {}).get("ally", [])],
        "scoreboard_stamp": _first_stamp(STORE.events_path("scoreboard", sid))}
    for hz in rates:
        t0 = time.perf_counter()
        keep = rate_times(events, hz)
        sub = subset(events, keep, hz)
        rev = None
        if write_stores is not None:
            st = Store(write_stores / f"hz{hz:g}")
            path = st.write_events("ally_icon", sid, sub)
            rev = hashlib.sha256(path.read_bytes()).hexdigest()
        prod = rate_entities(sid, sub, inp, True, rev)
        indep = rate_entities(sid, sub, inp, False, rev)
        if write_stores is not None:
            Store(write_stores / f"hz{hz:g}").write_events("round_entity", sid, prod)
        per, ev = invariants(prod, inp)
        di, drows = death_identity(indep, inp)
        dw, _ = death_identity(indep, inp, widen_ms=1000.0 / hz)
        rr = {"frames": len(keep), "build_s": round(time.perf_counter() - t0, 1),
              "per_round": per, "events": ev,
              "death_identity": {r: dict(c) for r, c in di.items()}, "death_rows": drows,
              "death_identity_wide": {r: dict(c) for r, c in dw.items()},
              "labels_prod": label_scores(prod, labels, inp["scale"]),
              "labels_indep": label_scores(indep, labels, inp["scale"])}
        if sid == "a06f04a0059f":
            rr["round4"] = {"prod": round4_oracle(prod), "indep": round4_oracle(indep)}
        res["rates"][f"{hz:g}"] = rr
        print(sid, f"{hz:g} Hz", len(keep), "frames", rr["build_s"], "s", flush=True)
    (out / f"fidelity_{sid}.json").write_text(json.dumps(res), encoding="utf-8")
    return res


# ---------------------------------------------------------------- report --

def _units(results: list[dict], rates) -> list[tuple]:
    return sorted({(r["session_id"], int(k)) for r in results
                   for k in r["rates"][f"{rates[0]:g}"]["per_round"] if str(k).isdigit()})


def _round_sum(res_by_sid, sid, hz, rno, key, src="per_round"):
    rr = res_by_sid[sid]["rates"][f"{hz:g}"]
    d = rr[src].get(str(rno)) or rr[src].get(rno) or {}
    return float(d.get(key, 0))


def report(out: Path, rates=RATES, reps: int = 2000, seed: int = 0, sessions=None) -> dict:
    """`sessions` restricts the report (written as report_<n>.json); the
    violation matching runs on the whole set only."""
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("fidelity_*.json"))]
    if sessions:
        results = [r for r in results if r["session_id"] in sessions]
    by = {r["session_id"]: r for r in results}
    units = _units(results, rates)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(units), size=(reps, len(units)))

    def table(num_fn, den_fn):
        """Point estimate, CI and paired differences of a ratio of per-round sums."""
        N = {h: np.array([num_fn(s, h, r) for s, r in units]) for h in rates}
        D = {h: np.array([den_fn(s, h, r) for s, r in units]) for h in rates}
        pt = {h: N[h].sum() / max(1e-9, D[h].sum()) for h in rates}
        bs = {h: N[h][draws].sum(1) / np.maximum(1e-9, D[h][draws].sum(1)) for h in rates}
        row = {f"{h:g}": [round(pt[h], 4), round(float(np.percentile(bs[h], 2.5)), 4),
                          round(float(np.percentile(bs[h], 97.5)), 4)] for h in rates}
        for a, b in ((15.0, 5.0), (15.0, 2.0), (5.0, 2.0)):
            if a in rates and b in rates:
                dd = bs[a] - bs[b]
                row[f"{a:g}-{b:g}"] = [round(pt[a] - pt[b], 4), round(float(np.percentile(dd, 2.5)), 4),
                                       round(float(np.percentile(dd, 97.5)), 4)]
        row["sums"] = {f"{h:g}": [N[h].sum(), D[h].sum()] for h in rates}
        return row

    one = lambda s, h, r: 1.0
    pr = lambda key: (lambda s, h, r: _round_sum(by, s, h, r, key))
    di = lambda key: (lambda s, h, r: _round_sum(by, s, h, r, key, "death_identity"))
    seg_scored = lambda s, h, r: _round_sum(by, s, h, r, "seg_right", "death_identity") + _round_sum(
        by, s, h, r, "seg_wrong", "death_identity")
    rep = {"units": len(units), "sessions": sorted(by),
           "segments_per_round": table(pr("segments"), one),
           "pieces_per_round": table(pr("pieces"), one),
           "named_obs_share": table(pr("obs_named"), pr("obs")),
           "named_piece_share": table(pr("pieces_named"), pr("pieces")),
           "death_segment_right_of_scored": table(di("seg_right"), seg_scored),
           "death_segment_right_of_deaths": table(di("seg_right"), di("deaths")),
           "death_bound_share": table(di("bound"), di("deaths")),
           "death_unbound_none_share": table(di("unbound_none"), di("deaths")),
           "death_unbound_many_share": table(di("unbound_many"), di("deaths"))}
    dw = lambda key: (lambda s, h, r: _round_sum(by, s, h, r, key, "death_identity_wide"))
    if all("death_identity_wide" in r["rates"][f"{h:g}"] for r in results for h in rates):
        rep["wide_death_segment_right_of_scored"] = table(dw("seg_right"), lambda s, h, r: _round_sum(
            by, s, h, r, "seg_right", "death_identity_wide") + _round_sum(by, s, h, r, "seg_wrong",
                                                                   "death_identity_wide"))
        rep["wide_death_segment_right_of_deaths"] = table(dw("seg_right"), dw("deaths"))
        rep["wide_death_bound_share"] = table(dw("bound"), dw("deaths"))
    rep["lineups"] = {r["session_id"]: {"scoreboard": r.get("scoreboard_stamp"),
                                        "ally": r.get("lineup_ally")} for r in results}
    kinds = sorted({e["kind"] for r in results for rr in r["rates"].values() for e in rr["events"]})
    rep["violations_per_round"] = {k: table(pr(k), one) for k in kinds}
    rep["checks_per_round"] = {k: table(pr(k), one) for k in sorted(
        {k for r in results for rr in r["rates"].values() for d in rr["per_round"].values() for k in d
         if k.startswith(("refused:", "end:", "barred"))})}
    # labels: each label a unit, paired across rates
    for which in ("labels_prod", "labels_indep"):
        rows = {h: [x for r in results for x in r["rates"][f"{h:g}"][which]] for h in rates}
        n = len(rows[rates[0]])
        rep[which] = {f"{h:g}": dict(Counter(x["result"] for x in rows[h])) for h in rates}
        if n:
            ld = rng.integers(0, n, size=(reps, n))
            R = {h: np.array([x["result"] == "right" for x in rows[h]], float) for h in rates}
            for a, b in ((15.0, 5.0), (15.0, 2.0)):
                dd = R[a][ld].sum(1) - R[b][ld].sum(1)
                rep[which][f"{a:g}-{b:g}_right"] = [int(R[a].sum() - R[b].sum()),
                                                    float(np.percentile(dd, 2.5)),
                                                    float(np.percentile(dd, 97.5))]
            rep[which]["changed"] = [
                {"key": x["key"], "answer": x["answer"],
                 **{f"{h:g}": rows[h][i].get("got") or rows[h][i]["result"] for h in rates}}
                for i, x in enumerate(rows[rates[0]])
                if len({rows[h][i]["result"] + str(rows[h][i].get("got")) for h in rates}) > 1]
    # deaths every rate binds to one segment end: identity on a common set
    dr = {h: {(r["session_id"], x["death_id"]): x for r in results
              for x in r["rates"][f"{h:g}"]["death_rows"]} for h in rates}
    common = sorted(k for k in dr[rates[0]] if all(
        dr[h].get(k, {}).get("result", "").startswith("seg_") for h in rates))
    if common:
        R = {h: np.array([dr[h][k]["result"] == "seg_right" for k in common], float) for h in rates}
        cd = rng.integers(0, len(common), size=(reps, len(common)))
        rep["death_common"] = {"n": len(common), **{f"{h:g}": int(R[h].sum()) for h in rates}}
        for a, b in ((15.0, 5.0), (15.0, 2.0), (5.0, 2.0)):
            dd = (R[a][cd].sum(1) - R[b][cd].sum(1)) / len(common)
            rep["death_common"][f"{a:g}-{b:g}"] = [round((R[a].sum() - R[b].sum()) / len(common), 4),
                                                   round(float(np.percentile(dd, 2.5)), 4),
                                                   round(float(np.percentile(dd, 97.5)), 4)]
    if "a06f04a0059f" in by:
        rep["round4"] = {f"{h:g}": by["a06f04a0059f"]["rates"][f"{h:g}"].get("round4") for h in rates}
    rep["matching"] = match_violations(results, rates, out) if not sessions else {}
    rep["build_s"] = {f"{h:g}": round(sum(r["rates"][f"{h:g}"]["build_s"] for r in results), 1)
                      for h in rates}
    name = "report.json" if not sessions else f"report_{'_'.join(sorted(by))}.json"
    (out / name).write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    return rep


def brief(rep: dict) -> None:
    """The report as one line per measure: point (95% CI) per rate and paired differences."""
    f = lambda v: f"{v[0]:.3f} ({v[1]:.3f}, {v[2]:.3f})"

    def row(name, t):
        print(f"{name[:34]:34s}", " | ".join(f"{k}: {f(t[k])}" for k in t if k != "sums"),
              "| sums", {k: [round(x) for x in v] for k, v in t["sums"].items()})
    print("rounds", rep["units"], rep["sessions"], "build_s", rep["build_s"])
    for k, t in rep.items():
        if isinstance(t, dict) and "sums" in t:
            row(k, t)
    for group in ("violations_per_round", "checks_per_round"):
        print("--", group)
        for k, t in rep[group].items():
            row(k, t)
    for w in ("labels_prod", "labels_indep"):
        print(w, {k: v for k, v in rep[w].items() if k != "changed"})
        for c in rep[w].get("changed", []):
            print("   ", c)
    print("death_common", rep.get("death_common"))
    print("round4", json.dumps(rep.get("round4")))
    print("lineups", json.dumps(rep.get("lineups")))
    for pair, d in rep["matching"].items():
        print("matching", pair, {k: (v.get("matched", 0), v.get("unmatched", 0)) for k, v in d.items()})


def _same(a: dict, b: dict, scale: float) -> bool:
    if a["round"] != b["round"] or abs(a["t_ms"] - b["t_ms"]) > MATCH_MS:
        return False
    if a.get("agent") and b.get("agent"):
        return a["agent"] == b["agent"]
    if "x" in a and "x" in b:
        return math.hypot(a["x"] - b["x"], a["y"] - b["y"]) <= MATCH_PX * scale
    return True


def match_violations(results, rates, out_dir: Path) -> dict:
    """For each rate pair and kind: flagged at A and matched at B, or not."""
    out = {}
    for r in results:
        sid = r["session_id"]
        scale = inputs_scale(sid)
        for a in rates:
            for b in rates:
                if a == b:
                    continue
                ea, eb = r["rates"][f"{a:g}"]["events"], r["rates"][f"{b:g}"]["events"]
                idx = defaultdict(list)
                for e in eb:
                    idx[(e["kind"], e["round"])].append(e)
                for e in ea:
                    hit = any(_same(e, f, scale) for f in idx[(e["kind"], e["round"])])
                    e["unmatched_at"] = [x for x in e.get("unmatched_at", []) if x != f"{b:g}"]
                    c = out.setdefault(f"{a:g}_vs_{b:g}", {}).setdefault(e["kind"], Counter())
                    c["matched" if hit else "unmatched"] += 1
                    if not hit:
                        e.setdefault("unmatched_at", []).append(f"{b:g}")
        (out_dir / f"fidelity_{sid}.json").write_text(json.dumps(r), encoding="utf-8")
    return {k: {kk: dict(vv) for kk, vv in v.items()} for k, v in out.items()}


_SCALES: dict = {}


def inputs_scale(sid: str) -> float:
    if sid not in _SCALES:
        man = STORE.read_manifest(sid)
        box = minimap_roi_px(get_profile(man["source_profile"]), int(man["source"]["width"]),
                             int(man["source"]["height"]))
        _SCALES[sid] = widget_scale(box[2] - box[0])
    return _SCALES[sid]


# ----------------------------------------------------------------- sheet --

def sheet(out: Path, a: float, b: float, per_kind: int = 8, seed: int = 0,
          stores: Path | None = None) -> list[Path]:
    """Contact sheets of violations flagged at `a` and unmatched at `b`: the
    cached minimap at t-500, t and t+500 ms (for a reachability break: the
    earlier look, the flagged look and 500 ms on), the flagged point ringed
    red, the earlier point magenta, and each 15 Hz production observation's
    name in yellow when `stores` holds the `--write-stores` output."""
    import cv2

    from reticle.roi_cache import RoiCache

    rng = np.random.default_rng(seed)
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("fidelity_*.json"))]
    names: dict = {}
    if stores is not None:
        for r in results:
            rows = Store(stores / "hz15").read_events("round_entity", r["session_id"])
            agent = {e["id"]: e.get("agent") for e in rows if e.get("kind") == "entity"}
            got = names.setdefault(r["session_id"], defaultdict(list))
            for o in rows:
                if o.get("kind") == "observation" and o.get("family") == "ally":
                    got[o["t_ms"]].append((o["x"], o["y"], agent.get(o["entity_id"])))
    picks = defaultdict(list)
    for r in results:
        for e in r["rates"][f"{a:g}"]["events"]:
            if f"{b:g}" in e.get("unmatched_at", ()) and "x" in e:
                picks[e["kind"]].append((r["session_id"], e))
    paths = []
    for kind, lst in sorted(picks.items()):
        chosen = [lst[i] for i in sorted(rng.choice(len(lst), min(per_kind, len(lst)), replace=False))]
        tiles = []
        for sid, e in chosen:
            man = STORE.read_manifest(sid)
            prof = get_profile(man["source_profile"])
            cache, why = RoiCache.load(STORE.root, man, prof, "minimap")
            if cache is None:
                continue
            box = minimap_roi_px(prof, int(man["source"]["width"]), int(man["source"]["height"]))
            ts = cache.t_ms
            want = []
            # a reachability break: the earlier look, the flagged look, 500 ms on
            at_t = ([e["t0"], e["t_ms"], e["t_ms"] + 500.0] if "t0" in e else
                    [e["t_ms"] - 500.0, e["t_ms"], e["t_ms"] + 500.0])
            for tt in at_t:
                j = int(np.argmin(np.abs(ts - tt)))
                want.append(float(ts[j]))
            got = {s.t_ms: s.frame for s in cache.samples(sorted(set(want)), rois=["minimap"])}
            row = []
            for t in want:
                fr = got.get(t)
                if fr is None:
                    continue
                crop = fr[box[1]:box[3], box[0]:box[2]]
                px, py = e["x"], e["y"]
                qx, qy = e.get("x0", px), e.get("y0", py)
                half = int(max(60.0, math.hypot(px - qx, py - qy) / 2 + 40))
                mx, my = int(round((px + qx) / 2)), int(round((py + qy) / 2))
                pad = cv2.copyMakeBorder(crop, half, half, half, half, cv2.BORDER_CONSTANT)
                c = pad[my:my + 2 * half, mx:mx + 2 * half]
                k = 360.0 / (2 * half)
                c = cv2.resize(c, (360, 360), interpolation=cv2.INTER_NEAREST)
                at = lambda x, y: (int((x - mx + half) * k), int((y - my + half) * k))
                cv2.circle(c, at(px, py), int(12 * k), (0, 0, 255), 1)
                if "x0" in e:
                    cv2.circle(c, at(qx, qy), int(12 * k), (255, 0, 255), 1)
                for x, y, name in names.get(sid, {}).get(t, ()):
                    u, v = at(x, y)
                    if 0 <= u < 360 and 0 <= v < 360:
                        cv2.putText(c, (name or "?")[:4], (u - 12, v + int(14 * k)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                canvas = c
                cv2.putText(canvas, f"{t - e['t_ms']:+.0f} ms", (4, 352), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (255, 255, 255), 1)
                row.append(canvas)
            if not row:
                continue
            strip = np.hstack(row + [np.zeros((360, 360, 3), np.uint8)] * (3 - len(row)))
            head = np.zeros((40, strip.shape[1], 3), np.uint8)
            txt = (f"{sid} R{e['round']} {e['t_ms'] / 1000:.2f}s {kind} {e.get('agent') or ''} "
                   f"{e.get('prev') or ''} {e.get('across') or ''} d={e.get('d_px', '')} "
                   f"dt={e.get('dt_ms', '')}")
            cv2.putText(head, txt[:110], (4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(np.vstack([head, strip]))
        if tiles:
            p = out / f"sheet_{kind}_{a:g}_not_{b:g}.png"
            cv2.imwrite(str(p), np.vstack(tiles))
            (out / f"sheet_{kind}_{a:g}_not_{b:g}.json").write_text(
                json.dumps([{"session_id": s, **e} for s, e in chosen], indent=1), encoding="utf-8")
            paths.append(p)
    return paths


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--icons-store", help="store holding the 15 Hz ally_icon streams (scratch)")
    ap.add_argument("--out", help="directory for per-session results")
    ap.add_argument("--write-stores", help="write per-rate ally_icon and round_entity streams here")
    ap.add_argument("--rates", nargs="+", type=float, default=list(RATES))
    ap.add_argument("--report", help="aggregate the per-session results in this directory")
    ap.add_argument("--sheet", help="draw contact sheets from the results in this directory")
    ap.add_argument("--pair", nargs=2, type=float, default=[15.0, 2.0])
    a = ap.parse_args()
    if a.report:
        brief(report(Path(a.report), tuple(a.rates), sessions=a.sids or None))
    elif a.sheet:
        for p in sheet(Path(a.sheet), *a.pair,
                       stores=Path(a.write_stores) if a.write_stores else None):
            print(p)
    else:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        src = Store(a.icons_store) if a.icons_store else STORE
        for sid in a.sids:
            run_session(sid, src, out, tuple(a.rates),
                        Path(a.write_stores) if a.write_stores else None)
