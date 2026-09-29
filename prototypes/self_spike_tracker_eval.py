r"""Score the joint self and spike tracker (minimap-0.8.0) before it is wired.

    .\.venv\Scripts\python.exe prototypes\self_spike_tracker_eval.py replay <sid> [<sid> ...]
    .\.venv\Scripts\python.exe prototypes\self_spike_tracker_eval.py score
    .\.venv\Scripts\python.exe prototypes\self_spike_tracker_eval.py track <sid> [<sid> ...]
    .\.venv\Scripts\python.exe prototypes\self_spike_tracker_eval.py record <sid> [<sid> ...]

`replay` drives `cli._MinimapPass` -- the reader `scan` runs, with its
`icon_prior.SelfTracker` -- over every frame of the session's 15 Hz minimap
crop cache and writes its `l1/minimap` table and `minimap_prior` events into
a scratch store under the store's `analysis/self-spike-20260929/scratch/`;
it decodes no video and writes nothing else. `score` reads those tables
against the player's 34 labels (`labels/prior_self/answers.jsonl`, drawn by
`prototypes/label_prior_self.py`), under the same definitions
`prototypes/prior_self.py score_labels` used for the 1 Hz-row guard, so the
numbers compare. `track` measures the carried case, the dropped glyph's
cheap check, the audit's agreement, the surprises and guard 6 (the four
dead runs) from the scratch tables and the stored death, rounds, roster,
spike and ally rows.

Run as `self-spike-eval-0.1.0` under task `self-spike-20260929`,
pre-registered in the store's `notes/predictions.jsonl`. `wire: no`: it
scores the reader; `reticle/icon_prior.py` is what the pipeline runs.
"""
from __future__ import annotations

import argparse
import bisect
import ctypes
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import spike, teardrop  # noqa: E402
from reticle.adjudication import spectate  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.version import MINIMAP_VERSION  # noqa: E402

VERSION = "self-spike-eval-0.1.0"
RUN_ID = "self-spike-20260929"
STORE = Store()
OUT = STORE.root / "analysis" / "self-spike-20260929"
SCRATCH = OUT / "scratch"
PRIOR = STORE.root / "analysis" / "prior-self-20260929"
#: As `prototypes/prior_self.py`: a point is kept within this many icon
#: radii of the player's click, and he stands on the spike within it of the
#: glyph.
ON_SPIKE_RADII = 1.5
#: The four runs of five seconds or more classed dead (prior-self-20260929).
DEAD_RUNS = (("a06f04a0059f", 1528.0, 1536.0), ("a06f04a0059f", 1851.0, 1855.0),
             ("a06f04a0059f", 2220.0, 2226.0), ("223d636bf8d2", 944.5, 950.5))


def idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    cv2.setNumThreads(1)


def _date(man: dict) -> str:
    from reticle.cli import _date_of
    return _date_of(man)


def replay(sid: str, window=None) -> None:
    from reticle.cli import _FP, _MinimapPass
    man = STORE.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    mm, why = RoiCache.load(STORE.root, man, prof, "minimap")
    if mm is None:
        raise SystemExit(f"{sid}: no minimap crop cache ({why})")
    if float(mm.record["hz"]) != 15.0:
        raise SystemExit(f"{sid}: cache at {mm.record['hz']} Hz, not 15")
    args = SimpleNamespace(minimap_hz=15.0)
    mp = _MinimapPass(STORE, man, prof, None, args)
    mp.frames_from = mm.record["version"]
    t0 = time.perf_counter()
    times = mm.holds()
    root = SCRATCH
    if window:
        times = [t for t in times if window[0] * 1000 <= t <= window[1] * 1000]
        root = OUT / "smoke"
    for i, smp in enumerate(mm.samples(times, rois=["minimap"])):
        mp.feed(smp)
        if i and i % 3000 == 0:
            print(f"  {sid} {i}/{len(times)} {time.perf_counter() - t0:.0f}s", flush=True)
    out = Store(root)
    path = out.write_minimap(mp.rows, _FP(man["source"], sid), prof.name, _date(man),
                             frames_from=mp.frames_from)
    ev = out.write_events("minimap_prior", sid, mp.prior_events(sid))
    print(f"{sid}: {len(mp.rows)} rows in {time.perf_counter() - t0:.0f}s -> {path}, {ev}")


def scratch_rows(sid: str) -> list[dict]:
    man = STORE.read_manifest(sid)
    tb = Store(SCRATCH).read_minimap(sid, _date(man))
    meta = tb.schema.metadata or {}
    if meta.get(b"minimap_version", b"").decode() != MINIMAP_VERSION:
        raise SystemExit(f"{sid}: scratch table is not {MINIMAP_VERSION}; replay it")
    return sorted(tb.to_pylist(), key=lambda r: r["t_ms"])


def stored_rows(sid: str) -> list[dict]:
    man = STORE.read_manifest(sid)
    return sorted(STORE.read_minimap(sid, _date(man)).to_pylist(), key=lambda r: r["t_ms"])


def row_at(rows: list[dict], T: list[float], t: float, tol: float = 20.0):
    k = bisect.bisect_left(T, t - tol)
    if k < len(T) and abs(T[k] - t) <= tol:
        return rows[k]
    return None


def dead_fn(sid: str):
    """`dead(t)` from the owner: inside one of the player's dead intervals
    (killfeed deaths only, as prior-self-0.2.0's guard 6)."""
    man = STORE.read_manifest(sid)
    ivs = spectate.player_dead_intervals(STORE.read_events("death", sid),
                                         STORE.read_rounds(sid, _date(man)).to_pylist())
    ix = spectate.DeadIndex(ivs)
    return lambda t: ix.at(t) is not None


def score() -> dict:
    index = {r["key"]: r for r in json.loads(
        (PRIOR / "label_items" / "index.json").read_text(encoding="utf-8"))}
    answers = {}
    for line in (STORE.root / "labels" / "prior_self" / "answers.jsonl").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            answers[r["key"]] = r
    cache, items = {}, []
    for key, a in answers.items():
        it = index[key]
        sid = it["session"]
        if sid not in cache:
            new, old = scratch_rows(sid), stored_rows(sid)
            cache[sid] = (new, [r["t_ms"] for r in new], old, [r["t_ms"] for r in old],
                          dead_fn(sid))
        new, nt, old, ot, dead = cache[sid]
        sc = it["widget_scale"]
        R = teardrop.R_OUT * sc
        click = (a["x"], a["y"]) if a["answer"] == "here" else None
        glyph = (it["gx"], it["gy"])
        d = lambda p, q: (None if p is None or q is None  # noqa: E731
                          else float(np.hypot(p[0] - q[0], p[1] - q[1])))
        rn, ro = row_at(new, nt, it["t_ms"]), row_at(old, ot, it["t_ms"])
        pn = None if rn is None or rn["self_x"] is None else (rn["self_x"], rn["self_y"])
        po = None if ro is None or ro["self_x"] is None else (ro["self_x"], ro["self_y"])
        on_spike = a["answer"] == "on_spike" or (click is not None and d(click, glyph) <= ON_SPIKE_RADII * R)
        kept = lambda p: click is not None and (d(p, click) or 1e9) <= ON_SPIKE_RADII * R  # noqa: E731
        items.append({"key": key, "stratum": it["stratum"], "answer": a["answer"],
                      "killfeed_dead": dead(it["t_ms"]), "on_spike": on_spike,
                      "found_new": rn is not None,
                      "new_point": pn is not None, "new_kept": kept(pn),
                      "new_to_click_radii": None if pn is None or click is None else round(d(pn, click) / R, 2),
                      "new_rests_on": None if rn is None else rn["self_rests_on"],
                      "new_reason": None if rn is None else rn["self_reason"],
                      "new_masked": None if rn is None else rn["self_glyph_masked"],
                      "new_spike": None if rn is None else [rn["spike_state"], rn["spike_rests_on"]],
                      "l1_point": po is not None, "l1_kept": kept(po)})
    here = [x for x in items if x["answer"] == "here"]
    spike_items = [x for x in here if x["on_spike"]]
    alive_here = [x for x in here if not x["killfeed_dead"]]
    wrong = [x for x in alive_here if not x["l1_kept"]]
    res = {"version": VERSION, "minimap": MINIMAP_VERSION, "items": len(items),
           "answers": dict(Counter(x["answer"] for x in items)),
           "matched_frames": sum(x["found_new"] for x in items),
           "on_spike_here": len(spike_items),
           "on_spike_kept_new": sum(x["new_kept"] for x in spike_items),
           "on_spike_kept_l1": sum(x["l1_kept"] for x in spike_items),
           "alive_here": len(alive_here),
           "alive_here_kept_new": sum(x["new_kept"] for x in alive_here),
           "alive_here_kept_l1": sum(x["l1_kept"] for x in alive_here),
           "l1_wrong_alive_here": len(wrong),
           "l1_wrong_now_kept": sum(x["new_kept"] for x in wrong),
           "l1_wrong_now_null": sum(not x["new_point"] for x in wrong),
           "l1_wrong_still_wrong": sum(x["new_point"] and not x["new_kept"] for x in wrong),
           "alive_here_wrong_point_new": sum(x["new_point"] and not x["new_kept"] for x in alive_here),
           "killfeed_dead_items": sum(x["killfeed_dead"] for x in items),
           "detail": items}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "label_scores.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def track(sid: str) -> dict:
    """The carried case, the glyph's cheap check, the audit, the surprises and
    guard 6, from the scratch tables and stored rows."""
    from reticle.adjudication.spike_carrier import frame_state
    man = STORE.read_manifest(sid)
    new = scratch_rows(sid)
    T = [r["t_ms"] for r in new]
    old = stored_rows(sid)
    ot = [r["t_ms"] for r in old]
    sp = sorted((r for r in STORE.read_events("spike", sid) if r.get("kind") == "frame"),
                key=lambda r: r["t_ms"])
    from reticle.minimap import minimap_roi_px, widget_scale
    box = minimap_roi_px(get_profile(man["source_profile"]), int(man["source"]["width"]),
                         int(man["source"]["height"]))
    sc = widget_scale(box[2] - box[0])
    res = {"session": sid, "version": VERSION, "minimap": MINIMAP_VERSION, "frames": len(new),
           "drawn": sum(r["widget_drawn"] is True for r in new)}
    res["self_rests_on"] = dict(Counter(r["self_rests_on"] for r in new if r["widget_drawn"]))
    res["self_reason"] = dict(Counter(r["self_reason"] for r in new if r["self_reason"]))
    res["points_new"] = sum(r["self_x"] is not None for r in new)
    res["points_l1"] = sum(r["self_x"] is not None for r in old)
    res["spike_rests_on"] = dict(Counter((r["spike_state"], r["spike_rests_on"]) for r in new
                                         if r["widget_drawn"]).most_common())
    res["spike_rests_on"] = {f"{a}:{b}": n for (a, b), n in res["spike_rests_on"].items()}
    dropped = [r for r in new if r["spike_state"] == "dropped"]
    res["dropped_frames"] = len(dropped)
    res["dropped_checked_at_prior"] = sum(r["spike_rests_on"] == "prior" for r in dropped)
    res["dropped_held_unverified"] = sum(r["spike_rests_on"] == "prior_held" for r in dropped)
    res["self_glyph_masked_points"] = sum(bool(r["self_glyph_masked"]) for r in new)
    res["self_carries_spike_points"] = sum(bool(r["self_carries_spike"]) for r in new)

    # The carried case: frames within 500 ms of a spike sample whose carried
    # glyph the owner puts under the self fit (`frame_state`).
    ct = sorted(r["t_ms"] for r in sp if frame_state(r, sc)["carrier_channel"] == "self")

    def carrying(t):
        k = bisect.bisect_left(ct, t)
        return any(0 <= j < len(ct) and abs(ct[j] - t) <= 500 for j in (k - 1, k))
    car = [r for r in new if r["widget_drawn"] and carrying(r["t_ms"])]
    lost = []
    for r in car:
        o = row_at(old, ot, r["t_ms"])
        if r["self_x"] is None and o is not None and o["self_x"] is not None:
            lost.append(r)
    res["carrier_frames"] = len(car)
    res["carrier_frames_flagged"] = sum(bool(r["self_carries_spike"]) for r in car)
    res["carrier_frames_refused_on_carried_glyph"] = sum(r["self_reason"] == "on_carried_glyph"
                                                         for r in car)
    res["carrier_frames_point_lost_vs_l1"] = len(lost)
    res["carrier_frames_moved_vs_l1"] = sum(
        1 for r in car if r["self_x"] is not None and (o := row_at(old, ot, r["t_ms"])) is not None
        and o["self_x"] is not None
        and np.hypot(o["self_x"] - r["self_x"], o["self_y"] - r["self_y"]) > 4 * sc)

    # The points that moved or vanished against the stored l1 track.
    moved = gone = gained = 0
    for r in new:
        o = row_at(old, ot, r["t_ms"])
        if o is None:
            continue
        a, b = r["self_x"] is not None, o["self_x"] is not None
        if a and b and np.hypot(o["self_x"] - r["self_x"], o["self_y"] - r["self_y"]) > 4 * sc:
            moved += 1
        gone += b and not a
        gained += a and not b
    res["vs_l1"] = {"moved_over_4px": moved, "lost": gone, "gained": gained}

    # The audit against the gated track, stored apart.
    ev = Store(SCRATCH).read_events("minimap_prior", sid)
    audits = [e for e in ev if e.get("kind") == "audit"]
    agree = n = 0
    for a in audits:
        r = row_at(new, T, a["t_ms"], tol=1)
        if r is None or a["self"] is None or r["self_x"] is None:
            continue
        n += 1
        agree += np.hypot(a["self"][0] - r["self_x"], a["self"][1] - r["self_y"]) <= 4 * sc
    res["audit"] = {"rows": len(audits), "compared": n, "agree_within_4px": int(agree)}
    res["surprises"] = dict(Counter(e["surprise"] for e in ev if e.get("kind") == "surprise"))

    # Guard 6 from the owner: the four dead runs and the points it removes.
    date = _date(man)
    ivs = spectate.player_dead_intervals(STORE.read_events("death", sid),
                                         STORE.read_rounds(sid, date).to_pylist(),
                                         [(r["t_ms"], r["self_x"], r["self_y"]) for r in new],
                                         spectate.stored_teammates(STORE, sid), sc,
                                         spectate.stored_roster(STORE, sid, date))
    ix = spectate.DeadIndex(ivs)
    dead = [r for r in new if r["self_x"] is not None and ix.at(r["t_ms"]) is not None]
    res["guard6"] = {"intervals": len(ivs),
                     "by_rests_on": dict(Counter(iv.rests_on for iv in ivs)),
                     "points_before": res["points_new"],
                     "points_removed_while_dead": len(dead),
                     "spectated_points": sum(ix.at(r["t_ms"]).spectated(r["t_ms"]) for r in dead)}
    runs = []
    for s, t0, t1 in DEAD_RUNS:
        if s != sid:
            continue
        rr = [r for r in new if t0 * 1000 - 100 <= r["t_ms"] <= t1 * 1000 + 100]
        runs.append({"run": [t0, t1], "frames": len(rr),
                     "points": sum(r["self_x"] is not None for r in rr),
                     "points_after_guard6": sum(r["self_x"] is not None and ix.at(r["t_ms"]) is None
                                                for r in rr)})
    res["dead_runs"] = runs
    (OUT / f"{sid}.track.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _sampled_ally_reader(sid: str):
    from reticle.minimap import AllyIconReader, floor_mask, minimap_roi_px, slab_mask
    from reticle import geometry
    man = STORE.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    mm, why = RoiCache.load(STORE.root, man, prof, "minimap")
    med = geometry.reference_static(sid, STORE.root)
    sd = geometry.stability(sid, STORE.root, med.shape[:2])
    box = minimap_roi_px(prof, int(man["source"]["width"]), int(man["source"]["height"]))
    rd = AllyIconReader(floor_mask(med, sd=sd), slab_mask(med, sd=sd), med, box)
    return man, mm, rd


#: The ally side is sampled at every `ALLY_EVERY`-th frame the replay holds a
#: dropped glyph on: the reader holds no state across frames, so a subset
#: reads as the full pass would at those frames.
ALLY_EVERY = 5


def ally(sid: str) -> dict:
    """A1 and A3: the ally reader (ally-icon-0.6.0) on the frames holding a
    dropped glyph and on the spike reader's 1 Hz samples, against the stored
    ally_icon rows and the roster marker."""
    from reticle.adjudication.minimap_candidates import accepted, ally_decisions
    man, mm, rd = _sampled_ally_reader(sid)
    new = scratch_rows(sid)
    drop = [r for r in new if r["spike_state"] == "dropped"][::ALLY_EVERY]
    glyph_at = {r["t_ms"]: (r["spike_x"], r["spike_y"]) for r in drop}
    sp = sorted((r for r in STORE.read_events("spike", sid) if r.get("kind") == "frame"
                 and r.get("marker")), key=lambda r: r["t_ms"])
    H = mm.holds()
    samp = sorted({H[min(len(H) - 1, bisect.bisect_left(H, r["t_ms"]))] for r in sp
                   if abs(H[min(len(H) - 1, bisect.bisect_left(H, r["t_ms"]))] - r["t_ms"]) <= 40})
    times = sorted(set(glyph_at) | set(samp))
    for smp in mm.samples(times, rois=["minimap"]):
        rd.feed(smp)
    rows = rd.candidate_rows(sid)
    dec = ally_decisions(rows)
    kept = accepted(rows, dec)
    by_t: dict[float, list] = {}
    for c in kept:
        by_t.setdefault(c["t_ms"], []).append(c)
    # Stored ally_icon (the version in the store) at the same frames.
    stored: dict[float, list] = {}
    sv = None
    for r in STORE.read_events("ally_icon", sid):
        if r.get("kind") == "coverage":
            sv = r.get("ally_icon_version")
        if r.get("kind") == "icon" and r["t_ms"] in glyph_at and r.get("family", "ally") == "ally" \
                and not r.get("reason"):
            stored.setdefault(r["t_ms"], []).append(r)
    stored_self = {r["t_ms"]: r["self"] for r in STORE.read_events("ally_icon", sid)
                   if r.get("kind") == "frame" and r["t_ms"] in glyph_at and r.get("self")}
    man_sc = rows[0]["widget_scale"] if rows else 1.0
    core, near = spike.CORE_PX * man_sc, spike.ON_GLYPH_PX * man_sc
    res = {"session": sid, "version": VERSION, "stored_ally_icon": sv, "dropped_frames": len(drop)}
    cnt = Counter()
    examples = []
    for t, (gx, gy) in glyph_at.items():
        def d(x, y):
            return float(np.hypot(x - gx, y - gy))
        for c in by_t.get(t, []):
            k = c["channel"]
            dd = d(c["cx"], c["cy"])
            cnt[f"new_{k}_core"] += dd <= core
            cnt[f"new_{k}_on"] += core < dd <= near
            if dd <= near and len(examples) < 12:
                examples.append({"t_ms": t, "channel": k, "cx": c["cx"], "cy": c["cy"],
                                 "glyph": [gx, gy], "d": round(dd, 1)})
        for c in stored.get(t, []):
            dd = d(c["cx"], c["cy"])
            cnt["stored_ally_core"] += dd <= core
            cnt["stored_ally_on"] += core < dd <= near
        s = stored_self.get(t)
        if s is not None:
            dd = d(s[0], s[1])
            cnt["stored_self_core"] += dd <= core
            cnt["stored_self_on"] += core < dd <= near
    res["A1"] = dict(cnt)
    res["A1_examples"] = examples
    # A3: the carrier flag on the 1 Hz samples against the roster marker.
    flags = Counter()
    frames = {f["t_ms"]: f for f in rd.frames}
    for r in sp:
        t = H[min(len(H) - 1, bisect.bisect_left(H, r["t_ms"]))]
        f = frames.get(t)
        if f is None or not f.get("widget_drawn"):
            continue
        marker = (r.get("marker") or {}).get("slot") is not None
        carriers = [c for c in by_t.get(t, []) if c.get("carries_spike")]
        flag = bool(carriers) or bool(f.get("self_carries_spike"))
        flags[f"marker_{marker}_flag_{flag}"] += 1
        if flag:
            flags["flag_self" if f.get("self_carries_spike") else "flag_ally"] += 1
    res["A3"] = dict(flags)
    both = flags["marker_True_flag_True"] + flags["marker_False_flag_False"]
    tot = sum(v for k, v in flags.items() if k.startswith("marker_"))
    res["A3"]["agree_share"] = round(both / tot, 4) if tot else None
    (OUT / f"{sid}.ally.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def count_ally_past_death(sid: str) -> dict:
    """A2: stored round_entity ally segments that continue past the killfeed
    death of the agent a piece of them is named."""
    rows = STORE.read_events("round_entity", sid)
    ver = rows[0].get("round_entity_version") if rows else None
    deaths = [d for d in STORE.read_events("death", sid) if d.get("kind") == "death_verdict"
              and d.get("side") == "ally" and d.get("victim") and not d.get("is_second_life")
              and not d.get("is_revive") and not d.get("kf_player_death")]
    ents = [r for r in rows if r.get("kind") == "entity" and r.get("family") == "ally"]
    by_seg: dict[str, list] = {}
    for e in ents:
        by_seg.setdefault(e.get("segment_id") or e["id"], []).append(e)
    obs = Counter()
    seg_obs: dict[str, list] = {}
    for r in rows:
        if r.get("kind") == "observation" and r.get("family") == "ally":
            seg_obs.setdefault(r.get("segment_id") or r["entity_id"], []).append(r["t_ms"])
    past = []
    for d in deaths:
        t, a, rn = float(d["t_ms"]), d["victim"], d.get("round_no")
        for seg, pieces in by_seg.items():
            if pieces[0].get("round_no") != rn or not any(p.get("agent") == a for p in pieces):
                continue
            ts = [x for x in seg_obs.get(seg, []) if x > t + 1000.0]
            named_after = [p for p in pieces if p.get("agent") == a
                           and (p.get("last_seen_ms") or 0) > t + 1000.0]
            if ts:
                past.append({"death_ms": t, "agent": a, "round_no": rn, "segment": seg,
                             "observations_after": len(ts),
                             "named_piece_past_death": bool(named_after)})
                obs["observations_after"] += len(ts)
    res = {"session": sid, "round_entity_version": ver, "ally_deaths": len(deaths),
           "segments_past_death": len(past),
           "observations_past_death": obs["observations_after"],
           "named_pieces_past_death": sum(p["named_piece_past_death"] for p in past),
           "cases": past}
    (OUT / f"{sid}.ally_deaths.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def record_run(sids: list[str]) -> None:
    from reticle import icon_prior, metrics
    deps = {"script": metrics.fingerprint(score, track, replay),
            "tracker": metrics.fingerprint(icon_prior.SelfTracker, icon_prior.GlyphTrack,
                                           icon_prior.annotate, icon_prior.IconTrack,
                                           spike.verify_glyph, spike.glyph_footprint,
                                           HOLD_UNVERIFIED_MS=icon_prior.HOLD_UNVERIFIED_MS,
                                           AUDIT_EVERY=icon_prior.AUDIT_EVERY),
            "version": VERSION, "minimap": MINIMAP_VERSION}
    lab = json.loads((OUT / "label_scores.json").read_text(encoding="utf-8"))
    metrics.record("self_spike", part="labels", session="a06f04a0059f+5822b6646448+223d636bf8d2",
                   values={k: v for k, v in lab.items() if not isinstance(v, (list, dict))
                           and k not in ("version", "minimap")},
                   deps=deps, note="scratch minimap-0.8.0 replay from the crop cache; no decode",
                   run_id=RUN_ID)
    for sid in sids:
        m = json.loads((OUT / f"{sid}.track.json").read_text(encoding="utf-8"))
        flat = {k: v for k, v in m.items() if not isinstance(v, (list, dict))
                and k not in ("session", "version", "minimap")}
        for part in ("vs_l1", "audit", "guard6"):
            flat.update({f"{part}_{k}": v for k, v in m[part].items() if not isinstance(v, dict)})
        metrics.record("self_spike", part="track", session=sid, values=flat, deps=deps,
                       note="scratch minimap-0.8.0 replay from the crop cache; no decode",
                       run_id=RUN_ID)
        for part, name in (("ally", "ally"), ("ally-deaths", "ally_deaths")):
            p = OUT / f"{sid}.{name}.json"
            if not p.is_file():
                continue
            m = json.loads(p.read_text(encoding="utf-8"))
            vals = {k: v for k, v in m.items() if not isinstance(v, (list, dict))
                    and k not in ("session", "version")}
            for sub in ("A1", "A3"):
                vals.update({f"{sub}_{k}": v for k, v in (m.get(sub) or {}).items()})
            metrics.record("self_spike", part=part, session=sid, values=vals, deps=deps,
                           note="ally-icon-0.6.0 on sampled cached frames, stored rows; no decode",
                           run_id=RUN_ID)
        print(f"{sid}: recorded")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["replay", "score", "track", "record", "ally", "ally_deaths"])
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--window", nargs=2, type=float, help="replay only these seconds, into analysis/.../smoke")
    a = ap.parse_args(argv)
    idle()
    if a.what == "score":
        print(json.dumps({k: v for k, v in score().items() if k != "detail"}, indent=1))
        return 0
    if a.what == "record":
        record_run(a.sessions)
        return 0
    for sid in a.sessions:
        if a.what == "replay":
            replay(sid, a.window)
        elif a.what == "ally":
            print(json.dumps(ally(sid), indent=1))
        elif a.what == "ally_deaths":
            res = count_ally_past_death(sid)
            print(json.dumps({k: v for k, v in res.items() if k != "cases"}, indent=1))
        else:
            print(json.dumps(track(sid), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
