r"""The self fit on the spike glyph: class the runs, and guard the pick.

    .\.venv\Scripts\python.exe prototypes\prior_self.py replay <sid> [<sid> ...]
    .\.venv\Scripts\python.exe prototypes\prior_self.py measure <sid> [<sid> ...]
    .\.venv\Scripts\python.exe prototypes\prior_self.py sheets <sid> [<sid> ...]
    .\.venv\Scripts\python.exe prototypes\prior_self.py record <sid> [<sid> ...]

`replay` refits the self candidates (about 3 min a session at Idle, one
thread); `measure` and `record` read the replay and stored rows; `sheets`
draws crop strips round each run. The player's labels come from
`prototypes/label_prior_self.py`.

Experiment 2 of docs/PRIOR_DRIVEN_READERS.md (section 3, item 2), run as
`prior-self-0.1.0`, pre-registered in the store's `notes/predictions.jsonl`
(task `prior-self-20260929`). It reads the lossless 15 Hz minimap crop cache
and stored rows; it decodes no video and writes only under
`analysis/prior-self-20260929/`.

**What the audit measured, and what it did not.** The audit
(`prior-audit-20260929`) paired the spike reader's 1 Hz dropped glyphs with
`ally_icon`'s stored self, the best-coverage fit of each frame, which no prior
chooses. `pick_self`'s track is `l1/minimap`. `ally-icon-0.4.0` stores no
raw self candidates, so `replay` refits `minimap.self_icons` on every cached
frame, exactly as `cli._MinimapPass.feed` does, and replays `pick_self` on
them; `measure` first checks that replay against `l1/minimap` (R2).

**The guarded pick** (`pick_guarded`) takes `minimap.pick_self_declared`'s
choice and its `rests_on`. When the choice sits on an accepted spike glyph
(`spike.on_glyph`, asked, not restated), it looks for a candidate the
teardrop confirms (`teardrop.fit_teardrop` reads the ring and lobe) and
takes it, off the glyph before on it; with none it refuses with
`on_spike_glyph_unconfirmed`. The glyphs come from the stored `spike-0.2.0`
rows: a dropped glyph from either 1 Hz sample beside the frame, within
`HOLD_MS` (a dropped glyph does not move until picked up), a carried glyph
only on the sample's own frame, where the row stores the icons `on_glyph`
pairs it with. A 1 Hz full-search audit (`audit`), fixed in advance on the
cache's frame grid and blind to the prior and the guard, is stored apart.

`wire: no` until the player has seen the classing and the before and after.
"""
from __future__ import annotations

import argparse
import bisect
import ctypes
import gzip
import json
import os
import sys
import time
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import geometry, spike, teardrop  # noqa: E402
from reticle.minimap import (FIT_ERR_PX, floor_mask, pick_self_declared,  # noqa: E402
                             self_icons, slab_mask, widget_drawn, widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

#: 0.2.0: no dropped glyph held across a pickup or a drop (`Glyphs.at`);
#: guard 6 stops the self track at the player's death (`run_guarded`);
#: second-life deaths no longer count as his death (`player_deaths`).
VERSION = "prior-self-0.2.0"
STORE = Store()
OUT = STORE.root / "analysis" / "prior-self-20260929"
#: A dropped glyph read at a 1 Hz spike sample holds for frames this near it,
#: from the samples on either side: a dropped glyph does not move until
#: picked up, and a sample that misses it (a portrait over it) leaves the
#: frames beside it guarded by the other. At the nearest sample alone (500
#: ms) the replay of a06f04a0059f locked on the glyph at 668.5 s, where the
#: 669 s sample did not read it.
HOLD_MS = 1000.0
#: A carried glyph holds only on the sample's own frame: it moves with its carrier.
SAME_FRAME_MS = 34.0
#: The audit's cadence, in cache frames: one full search a second at 15 Hz,
#: plus the first frame of every cache span. Fixed before any outcome.
AUDIT_EVERY = 15
#: Two picks agree within this, scale-1.0 px: the pair budget `2 * FIT_ERR_PX`.
AGREE_PX = 2.0 * FIT_ERR_PX


def idle() -> None:
    """Idle priority for this process, as the machine's rules ask."""
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    cv2.setNumThreads(1)


def _date(man: dict) -> str:
    from reticle.cli import _date_of
    return _date_of(man)


def spike_rows(sid: str) -> list[dict]:
    rows = [r for r in STORE.read_events("spike", sid) if r.get("kind") == "frame"]
    return sorted(rows, key=lambda r: r["t_ms"])


class Glyphs:
    """The accepted glyphs the stored spike rows hold for a frame's instant."""

    def __init__(self, rows: list[dict], rule: str = "0.2.0"):
        self.rows = rows
        self.t = [r["t_ms"] for r in rows]
        self.rule = rule

    @staticmethod
    def _carried(r: dict) -> bool:
        return r.get("reason") is None and any(
            g["state"] == "carried" for g in spike.accepted(r.get("glyphs") or []))

    def at(self, t_ms: float) -> tuple[list[dict], list[dict], float | None]:
        """`(glyphs, icons, sample_t)`: accepted glyphs held at `t_ms` and the
        row's stored icons (carried-glyph frames only).

        Rule 0.1.0 holds a dropped glyph from either neighbour sample. Rule
        0.2.0 (the default) holds it from a neighbour only when the other
        neighbour reads no carried glyph: across a pickup or a drop the old
        dropped glyph lies under the new carrier, and 0.1.0 put it on his own
        fit (a06f04a0059f 1480.13 s, 0.4 s before he died carrying it)."""
        k = bisect.bisect_left(self.t, t_ms)
        gl, icons, near_t = [], [], None
        pair = [j for j in (k - 1, k) if 0 <= j < len(self.t)]
        for j in pair:
            if abs(self.t[j] - t_ms) > HOLD_MS:
                continue
            r = self.rows[j]
            if near_t is None or abs(r["t_ms"] - t_ms) < abs(near_t - t_ms):
                near_t = r["t_ms"]
            if r.get("reason") is not None:
                continue
            same = abs(r["t_ms"] - t_ms) <= SAME_FRAME_MS
            other = [o for o in pair if o != j]
            crossed = (self.rule != "0.1.0" and not same
                       and any(self._carried(self.rows[o]) for o in other))
            for g in spike.accepted(r.get("glyphs") or []):
                if g["state"] != "dropped" and not same:
                    continue
                if g["state"] == "dropped" and crossed:
                    continue
                if any(abs(g["cx"] - o["cx"]) <= 2 and abs(g["cy"] - o["cy"]) <= 2 for o in gl):
                    continue
                gl.append(g)
            if same:
                icons = r.get("icons") or []
        return gl, icons, near_t


def _open(sid: str):
    man = STORE.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    mm, why = RoiCache.load(STORE.root, man, prof, "minimap")
    if mm is None:
        raise SystemExit(f"{sid}: no minimap crop cache ({why})")
    med = geometry.reference_static(sid, STORE.root)
    sd = geometry.stability(sid, STORE.root, med.shape[:2])
    ctx = {"floor": floor_mask(med, sd=sd), "slab": slab_mask(med, sd=sd),
           "sgray": cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)}
    return man, mm, ctx


def replay(sid: str, limit: int | None = None) -> Path:
    """Refit the self candidates on every cached frame; store them with the
    held glyphs, each candidate's `on_glyph`, and the teardrop where the
    guard or the audit will ask for it."""
    man, mm, ctx = _open(sid)
    gly = Glyphs(spike_rows(sid))
    times = mm.holds()
    if limit:
        times = times[:limit]
    x0, y0, x1, y1 = mm.rect_of("minimap")
    sc = widget_scale(x1 - x0)
    spans = mm.record.get("spans") or [[times[0], times[-1]]]
    first = set()
    for a, b in spans:
        k = bisect.bisect_left(times, a)
        if k < len(times) and times[k] <= b:
            first.add(times[k])
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{sid}.replay.jsonl.gz"
    t0 = time.perf_counter()
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "coverage", "session": sid, "version": VERSION,
                             "widget_scale": sc, "frames": len(times),
                             "roi_cache_version": mm.record.get("version"),
                             "spike_version": "spike-0.2.0", "hold_ms": HOLD_MS,
                             "audit_every": AUDIT_EVERY,
                             "teardrop_version": teardrop.TEARDROP_VERSION}) + "\n")
        for i, smp in enumerate(mm.samples(times, rois=["minimap"])):
            crop = smp.frame[y0:y1, x0:x1]
            row = {"t": round(smp.t_ms, 3), "f": int(smp.frame_idx)}
            if not widget_drawn(crop, ctx["sgray"], ctx["floor"]):
                row["drawn"] = False
                fh.write(json.dumps(row) + "\n")
                continue
            cands = self_icons(crop, ctx["floor"], require_facing=False, support=ctx["slab"])
            glyphs, gicons, gt = gly.at(smp.t_ms)
            on = [spike.on_glyph(c["cx"], c["cy"], glyphs, sc, icons=gicons) for c in cands]
            audit = (i % AUDIT_EVERY == 0) or smp.t_ms in first
            need = audit or any(o is not None for o in on)
            row["c"] = []
            for c, o in zip(cands, on):
                e = {"x": round(c["cx"], 2), "y": round(c["cy"], 2), "r": int(c["r"]),
                     "cov": round(c["cov"], 4)}
                if o is not None:
                    e["g"] = [o["cx"], o["cy"], o["state"]]
                if need:
                    tf = teardrop.fit_teardrop(crop, c["cx"], c["cy"], scale=sc)
                    e["td"] = round(float(tf.get("ncc") or 0.0), 3)
                    if tf.get("read"):
                        e["tdxy"] = [round(tf["x"], 2), round(tf["y"], 2)]
                row["c"].append(e)
            if glyphs:
                row["gl"] = [[g["cx"], g["cy"], g["state"]] for g in glyphs]
                row["gt"] = gt
            if audit:
                row["audit"] = True
            fh.write(json.dumps(row) + "\n")
            n += 1
            if n % 2000 == 0:
                print(f"  {sid} {n}/{len(times)} {time.perf_counter() - t0:.0f}s", flush=True)
    print(f"{sid}: {len(times)} frames in {time.perf_counter() - t0:.0f}s -> {path}")
    return path


def load_replay(sid: str) -> tuple[dict, list[dict]]:
    with gzip.open(OUT / f"{sid}.replay.jsonl.gz", "rt", encoding="utf-8") as fh:
        head = json.loads(fh.readline())
        rows = [json.loads(line) for line in fh]
    return head, rows


# ------------------------------------------------------------------ pickers

def run_stored(rows: list[dict], sc: float, step_ms: float) -> list[dict]:
    """`pick_self` as `cli._MinimapPass.feed` calls it, declared."""
    prev = prev_t = None
    out = []
    for r in rows:
        if r.get("drawn") is False:
            out.append({"t": r["t"], "xy": None, "rests_on": "widget_not_drawn"})
            continue
        dt = step_ms if prev_t is None else r["t"] - prev_t
        cands = [{"cx": c["x"], "cy": c["y"], "cov": c["cov"]} for c in r["c"]]
        p = pick_self_declared(cands, prev, dt, sc)
        if p["xy"] is not None:
            prev, prev_t = p["xy"], r["t"]
        out.append({"t": r["t"], **p})
    return out


def pick_guarded(r: dict, prev, dt_ms: float, sc: float) -> dict:
    """One frame's guarded pick: `pick_self_declared`, then the glyph guard."""
    cands = [{"cx": c["x"], "cy": c["y"], "cov": c["cov"]} for c in r["c"]]
    p = pick_self_declared(cands, prev, dt_ms, sc)
    if p["xy"] is None or "g" not in r["c"][p["index"]]:
        return {**p, "guard": "clear"}
    # The choice sits on a glyph: a witness must confirm a candidate.
    ok = [i for i, c in enumerate(r["c"]) if c.get("tdxy") is not None]
    off = [i for i in ok if "g" not in r["c"][i]]
    on = [i for i in ok if "g" in r["c"][i]]

    def nearest(ix):
        if prev is None:
            return max(ix, key=lambda i: r["c"][i]["cov"])
        return min(ix, key=lambda i: np.hypot(r["c"][i]["x"] - prev[0], r["c"][i]["y"] - prev[1]))

    g = r["c"][p["index"]]["g"]
    if off:
        i = nearest(off)
        return {"xy": (r["c"][i]["x"], r["c"][i]["y"]), "index": i,
                "rests_on": "teardrop_off_glyph", "guard": "moved_off_glyph",
                "glyph": g, "was": p["rests_on"]}
    if on:
        i = nearest(on)
        return {"xy": (r["c"][i]["x"], r["c"][i]["y"]), "index": i,
                "rests_on": "teardrop_on_glyph", "guard": "confirmed_on_glyph",
                "glyph": g, "was": p["rests_on"]}
    return {"xy": None, "index": None, "rests_on": p["rests_on"], "guard": "refused",
            "reason": "on_spike_glyph_unconfirmed", "glyph": g, "refused_xy": p["xy"]}


def reflag(rows: list[dict], gly: "Glyphs", sc: float) -> list[dict]:
    """The replay's rows with each candidate's `on_glyph` asked again under
    `gly`'s hold rule. The teardrop stays the replay's: a rule that holds no
    more glyphs than the replay's asks for no teardrop it did not fit."""
    out = []
    for r in rows:
        if r.get("drawn") is False or not r.get("c"):
            out.append(r)
            continue
        glyphs, icons, gt = gly.at(r["t"])
        cs = []
        for c in r["c"]:
            c = {k: v for k, v in c.items() if k != "g"}
            o = spike.on_glyph(c["x"], c["y"], glyphs, sc, icons=icons)
            if o is not None:
                c["g"] = [o["cx"], o["cy"], o["state"]]
            cs.append(c)
        nr = {**r, "c": cs}
        nr.pop("gl", None)
        if glyphs:
            nr["gl"] = [[g["cx"], g["cy"], g["state"]] for g in glyphs]
            nr["gt"] = gt
        out.append(nr)
    return out


def run_guarded(rows: list[dict], sc: float, step_ms: float, dead=None) -> list[dict]:
    """The guarded pick over a session. With `dead` (guard 6, `dead_after`),
    a frame after the player's death is null with reason `player_dead`, and
    the prior expires there: the view spectates, and the yellow icon is not
    his (run prior-self-b-20260929)."""
    prev = prev_t = None
    out = []
    for r in rows:
        if r.get("drawn") is False:
            out.append({"t": r["t"], "xy": None, "rests_on": "widget_not_drawn"})
            continue
        if dead is not None and dead(r["t"]):
            out.append({"t": r["t"], "xy": None, "rests_on": "player_dead",
                        "guard": "player_dead"})
            prev = prev_t = None
            continue
        dt = step_ms if prev_t is None else r["t"] - prev_t
        p = pick_guarded(r, prev, dt, sc)
        if p["xy"] is not None:
            prev, prev_t = p["xy"], r["t"]
        out.append({"t": r["t"], **p})
    return out


def run_audit(rows: list[dict]) -> list[dict]:
    """The full search on the fixed cadence: best coverage, no prior, no guard."""
    out = []
    for r in rows:
        if not r.get("audit"):
            continue
        cs = r.get("c") or []
        best = max(cs, key=lambda c: c["cov"]) if cs else None
        out.append({"t": r["t"], "xy": (best["x"], best["y"]) if best else None,
                    "on_glyph": bool(best and "g" in best)})
    return out


# ------------------------------------------------------------------ stored rows

def ally_self(sid: str) -> dict[float, list]:
    """`ally_icon`'s stored self per frame: the best-coverage fit, no prior."""
    out = {}
    for line in (STORE.root / "events" / "ally_icon" / f"{sid}.jsonl").open(encoding="utf-8"):
        if '"kind":"frame"' in line:
            r = json.loads(line)
            if r.get("self"):
                out[r["t_ms"]] = r["self"]
    return out


def l1_self(sid: str) -> dict[float, tuple]:
    """`l1/minimap`'s self: `pick_self`'s stored track (NULL rows left out)."""
    man = STORE.read_manifest(sid)
    tb = STORE.read_minimap(sid, _date(man))
    t, x, y = (tb.column(c).to_pylist() for c in ("t_ms", "self_x", "self_y"))
    return {a: (b, c) for a, b, c in zip(t, x, y) if b is not None}


def nearest(d: dict, keys: list, t: float, tol: float = 70.0):
    k = bisect.bisect_left(keys, t)
    best = None
    for j in (k - 1, k):
        if 0 <= j < len(keys) and abs(keys[j] - t) <= tol and (
                best is None or abs(keys[j] - t) < abs(best - t)):
            best = keys[j]
    return None if best is None else d[best]


def rounds(sid: str) -> list[dict]:
    man = STORE.read_manifest(sid)
    tb = STORE.read_rounds(sid, _date(man))
    return tb.to_pylist() if tb is not None else []


def player_deaths(sid: str) -> list[float]:
    """Instants the killfeed shows the player dying (`kf_player_death`), as
    the death owner stored them. A second-life death (`is_second_life`, a
    Run It Back body) is left out: the player lives on after it."""
    out = []
    for line in (STORE.root / "events" / "death" / f"{sid}.jsonl").open(encoding="utf-8"):
        if '"kf_player_death":true' in line:
            r = json.loads(line)
            if not r.get("is_second_life"):
                out.append(r["t_ms"])
    return sorted(out)


def dead_after(sid: str):
    """`dead(t)`: the killfeed showed the player die in the round that holds
    `t` (the last round started at or before it), before `t`."""
    starts = sorted((rd["t_start_ms"], rd["round_no"]) for rd in rounds(sid))
    deaths = player_deaths(sid)

    def dead(t: float) -> bool:
        k = bisect.bisect_right([a for a, _ in starts], t) - 1
        t0 = starts[k][0] if k >= 0 else float("-inf")
        return any(t0 <= d <= t for d in deaths)
    return dead


def runs_of(samples: list[dict], key: str) -> list[dict]:
    """Consecutive 1 Hz samples whose `key` is truthy; a sample with no
    reading (`key` None) neither extends nor breaks a run, as in the audit."""
    runs, cur = [], None
    for s in samples:
        v = s.get(key)
        if v is None:
            continue
        if v:
            if cur is None:
                cur = {"t0": s["t"], "t1": s["t"], "n": 0, "glyph": v}
            cur["t1"], cur["n"] = s["t"], cur["n"] + 1
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    return runs


def _lands_on(xy, glyphs, sc, dropped_only=True, chebyshev=None):
    """The glyph an xy lands on, asked of the owner (`spike.on_glyph`), or by
    the audit's unscaled Chebyshev test where `chebyshev` gives its px."""
    if xy is None:
        return None
    gl = [g for g in glyphs if g.get("reason") is None
          and (g["state"] == "dropped" or not dropped_only)]
    if chebyshev is not None:
        for g in gl:
            if abs(xy[0] - g["cx"]) <= chebyshev and abs(xy[1] - g["cy"]) <= chebyshev:
                return g
        return None
    return spike.on_glyph(xy[0], xy[1], gl, sc)


def measure(sid: str) -> dict:
    """Every number the report quotes for one session, from stored rows and
    the replay."""
    head, rows = load_replay(sid)
    sc = head["widget_scale"]
    step_ms = 1000.0 / 15.0
    sp = spike_rows(sid)
    al = ally_self(sid)
    alk = sorted(al)
    l1 = l1_self(sid)
    l1k = sorted(l1)
    stored = run_stored(rows, sc, step_ms)
    guarded = run_guarded(rows, sc, step_ms)
    audit = run_audit(rows)
    rt = [r["t"] for r in rows]
    res = {"session": sid, "widget_scale": sc}

    # R1: the audit, reproduced (ally_icon self, 4 px Chebyshev, dropped glyphs).
    # Also the owner's test, and pick_self's stored track (l1), and the replays.
    def at(track, t):
        k = bisect.bisect_left(rt, t - 40)
        if k < len(rt) and abs(rt[k] - t) <= 70:
            return track[k].get("xy")
        return None

    samples = []
    n_with, on_audit = 0, 0
    for r in sp:
        gl = [g for g in r.get("glyphs") or [] if g.get("reason") is None and g["state"] == "dropped"]
        s = {"t": r["t_ms"], "glyph": bool(gl)}
        if gl:
            # The audit's pairing, kept exactly: the first stored frame at or
            # after t - 40 ms, taken within 70 ms.
            k = bisect.bisect_left(alk, r["t_ms"] - 40)
            a = al[alk[k]] if k < len(alk) and abs(alk[k] - r["t_ms"]) <= 70 else None
            if a is not None:
                n_with += 1
                hit = _lands_on(a, gl, sc, chebyshev=4)
                on_audit += hit is not None
                s["ally_cheb"] = hit is not None and [hit["cx"], hit["cy"]]
                s["ally_owner"] = (_lands_on(a, gl, sc) is not None) and True
            else:
                s["ally_cheb"] = s["ally_owner"] = None
            b = nearest(l1, l1k, r["t_ms"])
            s["l1_owner"] = None if b is None else (_lands_on(b, gl, sc) is not None)
            s["l1_cheb"] = None if b is None else (_lands_on(b, gl, sc, chebyshev=4) is not None)
            for name, tr in (("stored", stored), ("guarded", guarded)):
                # A replayed frame with no pick breaks a run: the track is
                # not on the glyph there, whether it refused or found nothing.
                xy = at(tr, r["t_ms"])
                s[name] = False if xy is None else (_lands_on(xy, gl, sc) is not None)
            s["refused"] = (at(stored, r["t_ms"]) is not None and at(guarded, r["t_ms"]) is None)
        else:
            s.update({k: False for k in ("ally_cheb", "ally_owner", "l1_owner", "l1_cheb",
                                         "stored", "guarded")})
        samples.append(s)
    dead = dead_after(sid)
    res["R1"] = {"samples_with_dropped_glyph": n_with, "self_on_glyph": on_audit}
    for key in ("ally_cheb", "ally_owner", "l1_cheb", "l1_owner", "stored", "guarded"):
        rr = runs_of(samples, key)
        res[f"runs_{key}"] = {"on_samples": sum(bool(s.get(key)) for s in samples),
                              "on_samples_alive": sum(bool(s.get(key)) and not dead(s["t"])
                                                      for s in samples),
                              "runs_ge_5s_alive": sum(x["n"] >= 5 and not dead(x["t0"])
                                                      for x in rr),
                              "read_samples": sum(s.get(key) is not None and s["glyph"] for s in samples),
                              "runs": len(rr), "runs_ge_5s": sum(x["n"] >= 5 for x in rr),
                              "longest_s": max((x["n"] for x in rr), default=0)}
    res["_samples"] = samples

    # R2: the replay of pick_self against l1/minimap.
    agree = both = 0
    worst = []
    for r, p in zip(rows, stored):
        b = l1.get(r["t"])
        if b is None:
            b = nearest(l1, l1k, r["t"], tol=10)
        if b is None or p.get("xy") is None:
            continue
        both += 1
        d = float(np.hypot(b[0] - p["xy"][0], b[1] - p["xy"][1]))
        agree += d <= 0.5
        if d > 0.5:
            worst.append((r["t"], round(d, 1)))
    res["R2"] = {"both": both, "within_0.5px": agree,
                 "rate": round(agree / both, 4) if both else None, "first_disagreements": worst[:10]}

    # The declared rules on the stored rule's picks.
    from collections import Counter
    res["rests_on_stored"] = dict(Counter(p["rests_on"] for p in stored))
    res["widened_stored"] = sum(bool(p.get("widened")) for p in stored)
    res["guard"] = dict(Counter(p.get("guard", "n/a") for p in guarded))
    res["rests_on_guarded"] = dict(Counter(p["rests_on"] for p in guarded))

    # Points lost and moved: guarded against stored, frame by frame.
    lost_near = lost_far = moved = gained = 0
    lost_alive, confirmed = [], {"alive": 0, "dead": 0}
    from collections import Counter as _C
    lost_kind, lost_at_glyph_s = _C(), set()
    ix_of = {r["t"]: i for i, r in enumerate(rows)}
    for r, a, b in zip(rows, stored, guarded):
        if b.get("guard") == "confirmed_on_glyph":
            confirmed["dead" if dead(r["t"]) else "alive"] += 1
        if a.get("xy") is not None and b.get("xy") is None:
            near_g = any("g" in c for c in r.get("c") or [])
            if near_g:
                lost_near += 1
            else:
                lost_far += 1
            if not dead(r["t"]):
                lost_alive.append(r["t"])
                # Where the guarded track stands within a second either side:
                # away from the glyph, the refused point was a jump onto it;
                # at it, the player may stand on the spike and the refusal
                # may cost a real point.
                g = b.get("glyph")
                i = ix_of[r["t"]]
                near = [p["xy"] for p in guarded[max(0, i - 15):i + 16] if p.get("xy") is not None]
                if not near:
                    lost_kind["no_track_within_1s"] += 1
                elif g is not None and min(np.hypot(x - g[0], y - g[1]) for x, y in near) <= \
                        3 * spike.ON_GLYPH_PX * sc:
                    lost_kind["track_at_glyph"] += 1
                    lost_at_glyph_s.add(round(r["t"] / 1000))
                else:
                    lost_kind["track_elsewhere"] += 1
        elif a.get("xy") is None and b.get("xy") is not None:
            gained += 1
        elif a.get("xy") is not None and b.get("xy") is not None and \
                np.hypot(a["xy"][0] - b["xy"][0], a["xy"][1] - b["xy"][1]) > AGREE_PX * sc:
            moved += 1
    res["points"] = {"stored": sum(p.get("xy") is not None for p in stored),
                     "guarded": sum(p.get("xy") is not None for p in guarded),
                     "lost_on_glyph_frames": lost_near, "lost_elsewhere": lost_far,
                     "moved": moved, "gained": gained,
                     "lost_while_alive": len(lost_alive),
                     "lost_while_alive_by_track": dict(lost_kind),
                     "lost_at_glyph_s": sorted(lost_at_glyph_s),
                     "lost_while_alive_s": sorted({round(t / 1000) for t in lost_alive}),
                     "confirmed_on_glyph_frames": confirmed}

    # A1: the audit against the guarded and the stored picks.
    ix = {r["t"]: i for i, r in enumerate(rows)}
    dis_g = dis_s = n_a = 0
    for a in audit:
        i = ix[a["t"]]
        g, s = guarded[i].get("xy"), stored[i].get("xy")
        if a["xy"] is None or g is None:
            continue
        n_a += 1
        dis_g += np.hypot(a["xy"][0] - g[0], a["xy"][1] - g[1]) > AGREE_PX * sc
        if s is not None:
            dis_s += np.hypot(a["xy"][0] - s[0], a["xy"][1] - s[1]) > AGREE_PX * sc
    res["A1"] = {"audit_rows": len(audit), "compared": n_a, "disagree_guarded": int(dis_g),
                 "disagree_stored": int(dis_s),
                 "audit_on_glyph": sum(a["on_glyph"] for a in audit)}

    # T1 inputs: teardrop scores of candidates on a glyph and of audit picks off one.
    on_td, off_td = [], []
    for r in rows:
        for c in r.get("c") or []:
            if "td" not in c:
                continue
            (on_td if "g" in c else off_td).append(c["td"])
    res["teardrop"] = {"on_glyph_n": len(on_td),
                       "on_glyph_read": int(sum(v >= teardrop.MIN_NCC for v in on_td)),
                       "off_glyph_n": len(off_td),
                       "off_glyph_read": int(sum(v >= teardrop.MIN_NCC for v in off_td))}
    res["_stored"], res["_guarded"], res["_rows"] = stored, guarded, rows
    return res


#: The four runs of five seconds or more classed dead (prior-self-20260929):
#: (session, first and last 1 Hz sample, s).
DEAD_RUNS = (("a06f04a0059f", 1528.0, 1536.0), ("a06f04a0059f", 1851.0, 1855.0),
             ("a06f04a0059f", 2220.0, 2226.0), ("223d636bf8d2", 944.5, 950.5))


def measure_b(sid: str) -> dict:
    """The carried case and guard 6, rule 0.1.0 against 0.2.0."""
    from collections import Counter

    from reticle.adjudication.spike_carrier import frame_state
    head, rows0 = load_replay(sid)
    sc = head["widget_scale"]
    step = 1000.0 / 15.0
    sp = spike_rows(sid)
    dead = dead_after(sid)
    stored = run_stored(rows0, sc, step)
    rules = {"0.1.0": reflag(rows0, Glyphs(sp, "0.1.0"), sc),
             "0.2.0": reflag(rows0, Glyphs(sp, "0.2.0"), sc)}
    # Carrier frames: within 500 ms of a sample whose carried glyph sits under
    # the self fit, as the carrier owner reads it.
    carrier_t = [r["t_ms"] for r in sp if frame_state(r, sc)["carrier_channel"] == "self"]
    ct = sorted(carrier_t)

    def carrying(t):
        k = bisect.bisect_left(ct, t)
        return any(0 <= j < len(ct) and abs(ct[j] - t) <= 500 for j in (k - 1, k))

    # Pickup and drop instants: a self-carrier sample beside one without.
    edges = [r["t_ms"] for a, r in zip(sp, sp[1:])
             if (frame_state(a, sc)["carrier_channel"] == "self")
             != (frame_state(r, sc)["carrier_channel"] == "self")]
    res = {"session": sid, "version": VERSION, "carrier_samples": len(ct)}
    for name, rows in rules.items():
        g = run_guarded(rows, sc, step)
        c = Counter()
        near_edge = 0
        for r, a, b in zip(rows, stored, g):
            if not carrying(r["t"]) or a.get("xy") is None:
                continue
            c["frames"] += 1
            kind = b.get("guard", "clear")
            c[kind] += 1
            if kind != "clear":
                c[f"{kind}:{(b.get('glyph') or [None, None, '?'])[2]}"] += 1
                near_edge += any(abs(e - r["t"]) <= 1000 for e in edges)
        c["misfire_within_1s_of_pickup_or_drop"] = near_edge
        res[f"carrier_{name}"] = dict(c)
        # The dropped-glyph samples the rule guards (the 1 Hz on-glyph count).
        on = 0
        for s in sp:
            gl = [x for x in s.get("glyphs") or [] if x.get("reason") is None
                  and x["state"] == "dropped"]
            if not gl:
                continue
            k = bisect.bisect_left([r["t"] for r in rows], s["t_ms"] - 40)
            if k < len(rows) and abs(rows[k]["t"] - s["t_ms"]) <= 70:
                on += any("g" in cc for cc in rows[k].get("c") or [])
        res[f"dropped_samples_with_a_flagged_candidate_{name}"] = on
    # Guard 6 on rule 0.2.0.
    rows = rules["0.2.0"]
    g2 = run_guarded(rows, sc, step)
    g6 = run_guarded(rows, sc, step, dead=dead)
    runs = []
    for s, t0, t1 in DEAD_RUNS:
        if s != sid:
            continue
        ix = [i for i, r in enumerate(rows) if t0 * 1000 - 100 <= r["t"] <= t1 * 1000 + 100]
        count = lambda tr: {"points": sum(tr[i].get("xy") is not None for i in ix),  # noqa: E731
                            "on_glyph": sum(tr[i].get("xy") is not None and any(
                                "g" in c and (c["x"], c["y"]) == tuple(tr[i]["xy"])
                                for c in rows[i].get("c") or []) for i in ix)}
        runs.append({"run": [t0, t1], "frames": len(ix), "dead_frames": sum(dead(rows[i]["t"]) for i in ix),
                     "stored": count(stored), "guarded": count(g2), "guard6": count(g6)})
    res["dead_runs"] = runs
    alive_lost = sum(1 for r, a, b in zip(rows, g2, g6)
                     if a.get("xy") is not None and b.get("xy") is None and not dead(r["t"]))
    res["guard6"] = {"frames_dead": sum(1 for r in rows if r.get("drawn") is not False and dead(r["t"])),
                     "points_before": sum(p.get("xy") is not None for p in g2),
                     "points_after": sum(p.get("xy") is not None for p in g6),
                     "points_removed_while_dead": sum(1 for r, a, b in zip(rows, g2, g6)
                                                     if a.get("xy") is not None and b.get("xy") is None
                                                     and dead(r["t"])),
                     "points_lost_while_alive": alive_lost}
    (OUT / f"{sid}.measure_b.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


#: An item's player stands ON the spike when his click lies within this many
#: icon radii (`teardrop.R_OUT` x scale) of the glyph's centroid: his icon
#: then overlaps the glyph. Chosen before scoring, from the icon's size.
ON_SPIKE_RADII = 1.5


def score_labels() -> dict:
    """The player's `labels/prior_self` answers against the guard, once.

    Each item is scored under the rule it was drawn with (0.1.0) and under
    0.2.0 with guard 6. A kept point is within `ON_SPIKE_RADII` icon radii of
    his click; the glyph's candidate is confirmed where the teardrop reads."""
    from collections import Counter
    index = {r["key"]: r for r in json.loads(
        (OUT / "label_items" / "index.json").read_text(encoding="utf-8"))}
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
            head, rows = load_replay(sid)
            sc = head["widget_scale"]
            r2 = reflag(rows, Glyphs(spike_rows(sid), "0.2.0"), sc)
            dead = dead_after(sid)
            cache[sid] = (sc, rows, dead, run_stored(rows, sc, 1000 / 15),
                          run_guarded(rows, sc, 1000 / 15),
                          run_guarded(r2, sc, 1000 / 15, dead=dead),
                          {r["t"]: i for i, r in enumerate(rows)})
        sc, rows, dead, st, g1, g2, ti = cache[sid]
        i = ti[it["t_ms"]]
        R = teardrop.R_OUT * sc
        click = (a["x"], a["y"]) if a["answer"] == "here" else None
        glyph = (it["gx"], it["gy"])
        d = lambda p, q: None if p is None or q is None else float(np.hypot(p[0] - q[0], p[1] - q[1]))  # noqa: E731
        on_spike = a["answer"] == "on_spike" or (click is not None and d(click, glyph) <= ON_SPIKE_RADII * R)
        gc = [c for c in rows[i].get("c") or [] if "g" in c]
        items.append({
            "key": key, "stratum": it["stratum"], "answer": a["answer"],
            "killfeed_dead": dead(it["t_ms"]), "on_spike": on_spike,
            "click_to_glyph_radii": None if click is None else round(d(click, glyph) / R, 2),
            "stored_kept": click is not None and (d(st[i].get("xy"), click) or 1e9) <= ON_SPIKE_RADII * R,
            "g1": g1[i].get("guard"), "g1_kept": click is not None and (d(g1[i].get("xy"), click) or 1e9) <= ON_SPIKE_RADII * R,
            "g2": g2[i].get("guard", "clear"), "g2_kept": click is not None and (d(g2[i].get("xy"), click) or 1e9) <= ON_SPIKE_RADII * R,
            "g1_point": g1[i].get("xy") is not None, "g2_point": g2[i].get("xy") is not None,
            "teardrop_on_glyph_reads": bool(gc) and any(c.get("tdxy") is not None for c in gc)})
    here = [x for x in items if x["answer"] == "here"]
    spike_items = [x for x in items if x["on_spike"] and x["answer"] == "here"]
    alive_here = [x for x in here if not x["killfeed_dead"]]
    res = {
        "items": len(items), "answers": dict(Counter(x["answer"] for x in items)),
        "by_stratum": {s: dict(Counter(x["answer"] for x in items if x["stratum"] == s))
                       for s in sorted({x["stratum"] for x in items})},
        "on_spike_here": len(spike_items),
        "on_spike_teardrop_reads": sum(x["teardrop_on_glyph_reads"] for x in spike_items),
        "on_spike_kept_0.1.0": sum(x["g1_kept"] for x in spike_items),
        "on_spike_kept_stored": sum(x["stored_kept"] for x in spike_items),
        "alive_here": len(alive_here),
        "alive_here_kept_stored": sum(x["stored_kept"] for x in alive_here),
        "alive_here_kept_0.1.0": sum(x["g1_kept"] for x in alive_here),
        "alive_here_kept_0.2.0": sum(x["g2_kept"] for x in alive_here),
        "alive_here_wrong_point_stored": sum(not x["stored_kept"] for x in alive_here),
        "alive_here_wrong_point_0.1.0": sum(x["g1_point"] and not x["g1_kept"] for x in alive_here),
        "alive_here_wrong_point_0.2.0": sum(x["g2_point"] and not x["g2_kept"] for x in alive_here),
        "killfeed_dead_items": sum(x["killfeed_dead"] for x in items),
        "killfeed_dead_answers": dict(Counter(x["answer"] for x in items if x["killfeed_dead"])),
        "killfeed_alive_but_dead_answer": [x["key"] for x in items
                                           if not x["killfeed_dead"] and x["answer"] == "dead_spectating"],
        "detail": items}
    (OUT / "label_scores.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def run_context(sid: str, res: dict, run: dict) -> dict:
    """What the stored rows say round one run: round, side, plant, the
    player's death, the carrier before it, and the replay's candidates."""
    t0, t1 = run["t0"], run["t1"]
    ctx = {"t0_s": round(t0 / 1000, 1), "t1_s": round(t1 / 1000, 1), "n": run["n"]}
    for rd in rounds(sid):
        if rd["t_start_ms"] <= t0 <= (rd["t_end_ms"] or t0) + 5000:
            ctx.update(round=rd["round_no"], side=rd["player_side"],
                       plant_s=None if rd["plant_t_ms"] is None else round(rd["plant_t_ms"] / 1000, 1),
                       round_end_s=round(rd["t_end_ms"] / 1000, 1) if rd["t_end_ms"] else None)
            break
    d = [x for x in player_deaths(sid) if x <= t1 + 1000]
    ctx["player_died_s"] = round(d[-1] / 1000, 1) if d and d[-1] >= t0 - 60000 else None
    ctx["dead_at_start"] = dead_after(sid)(t0)
    # The carrier in the 15 s before the run: the roster marker's slot and
    # the channel under a carried glyph (`spike_carrier.frame_state`).
    from reticle.adjudication.spike_carrier import frame_state
    before = [r for r in spike_rows(sid) if t0 - 15000 <= r["t_ms"] < t0]
    states = [frame_state(r, res["widget_scale"]) for r in before]
    ctx["carrier_before"] = [(round(s["t_ms"] / 1000), s["glyph"], s["carrier_channel"], s["slot"])
                             for s in states if s["glyph"] == "carried" or s["slot"] is not None][-3:]
    # The replay inside the run: frames with a self candidate off every glyph,
    # and how often the teardrop reads on and off the glyph.
    rows = [r for r in res["_rows"] if t0 - 100 <= r["t"] <= t1 + 100 and r.get("c") is not None]
    off = [r for r in rows if any("g" not in c for c in r["c"])]
    ctx["frames"] = len(rows)
    ctx["frames_with_off_glyph_candidate"] = len(off)
    tds_on = [c["td"] for r in rows for c in r["c"] if "g" in c and "td" in c]
    tds_off = [c["td"] for r in rows for c in r["c"] if "g" not in c and "td" in c]
    ctx["teardrop_on_glyph_read"] = f"{sum(v >= teardrop.MIN_NCC for v in tds_on)}/{len(tds_on)}"
    ctx["teardrop_off_glyph_read"] = f"{sum(v >= teardrop.MIN_NCC for v in tds_off)}/{len(tds_off)}"
    return ctx


# ------------------------------------------------------------------ sheets

#: Panel geometry: the whole widget, then two zooms without marks.
FULL_W, ZOOM_W, ZOOM_HALF = 260, 170, 26
#: Shorter runs sampled per session, beside every run of five seconds or more.
SHORT_SAMPLE = 3


def _zoom(crop, cx, cy, sc):
    h = int(round(ZOOM_HALF * sc))
    H, W = crop.shape[:2]
    x0, y0 = int(round(cx)) - h, int(round(cy)) - h
    pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT, value=(40, 40, 40))
    win = pad[y0 + h:y0 + 3 * h + 1, x0 + h:x0 + 3 * h + 1]
    return cv2.resize(win, (ZOOM_W, ZOOM_W), interpolation=cv2.INTER_NEAREST)


def _strip_panel(crop, row, l1xy, glyph, sc, t_s, tag):
    """One second: the widget with marks, the glyph unmarked, and the best
    candidate off the glyph unmarked."""
    k = FULL_W / crop.shape[1]
    full = cv2.resize(crop, (FULL_W, int(round(crop.shape[0] * k))), interpolation=cv2.INTER_AREA)
    P = lambda x, y: (int(round(x * k)), int(round(y * k)))  # noqa: E731
    cv2.circle(full, P(*glyph), 9, (255, 255, 255), 1)
    off = None
    for c in row.get("c") or []:
        col = (0, 200, 0) if c.get("tdxy") is not None else (255, 200, 0)
        cv2.circle(full, P(c["x"], c["y"]), 5, col, 1)
        if "g" not in c and (off is None or c["cov"] > off["cov"]):
            off = c
    if l1xy is not None:
        x, y = P(*l1xy)
        cv2.line(full, (x - 4, y), (x + 4, y), (255, 0, 255), 1)
        cv2.line(full, (x, y - 4), (x, y + 4), (255, 0, 255), 1)
    zg = _zoom(crop, glyph[0], glyph[1], sc)
    zo = _zoom(crop, off["x"], off["y"], sc) if off is not None else np.full_like(zg, 30)
    body = np.full((max(full.shape[0], ZOOM_W), FULL_W + 2 * ZOOM_W + 8, 3), 20, np.uint8)
    body[:full.shape[0], :FULL_W] = full
    body[:ZOOM_W, FULL_W + 4:FULL_W + 4 + ZOOM_W] = zg
    body[:ZOOM_W, FULL_W + 8 + ZOOM_W:] = zo
    head = np.full((18, body.shape[1], 3), 0, np.uint8)
    cv2.putText(head, f"{t_s:.1f}s {tag}", (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (230, 230, 230), 1, cv2.LINE_AA)
    return np.vstack([head, body])


def sheets(sid: str) -> None:
    """A strip per run of five seconds or more and per sampled shorter run,
    at 1 Hz from two seconds before to two after. Marks: white ring the
    glyph, magenta cross `l1/minimap`'s self (pick_self as stored), green
    ring a candidate the teardrop reads, orange one it does not. The two
    zooms are unmarked: the glyph, and the best candidate off it."""
    import random
    m = json.loads((OUT / f"{sid}.measure.json").read_text(encoding="utf-8"))
    head, rows = load_replay(sid)
    sc = head["widget_scale"]
    man, mm, _ctx = _open(sid)
    x0, y0, x1, y1 = mm.rect_of("minimap")
    l1 = l1_self(sid)
    l1k = sorted(l1)
    held = [r["t"] for r in rows]
    long_, short = {}, {}
    for key in ("ally_cheb", "l1_owner"):
        for c in m["runs"][key]:
            k = (c["t0_s"], c["t1_s"])
            # One sheet per stretch: a run mostly inside one already drawn is
            # the same stretch found by the other track.
            if any(min(b, k[1]) - max(a, k[0]) + 1 >= 0.8 * (k[1] - k[0] + 1)
                   for a, b in list(long_) + list(short)):
                continue
            (long_ if c["n"] >= 5 else short)[k] = (key, c)
    rng = random.Random(20260929)
    # Every shorter run with the player alive (the case a refusal could
    # cost), plus a fixed random sample of the rest.
    alive = [k for k in sorted(short) if not short[k][1].get("dead_at_start")]
    rest = [k for k in sorted(short) if k not in alive]
    pick = sorted(alive + rng.sample(rest, min(SHORT_SAMPLE, len(rest))))
    sp = spike_rows(sid)
    todo = [(k, *long_[k], "long") for k in sorted(long_)] + [(k, *short[k], "short") for k in pick]
    # Where the guard refused a point while the player was alive: the cost.
    secs = [s for s in m["points"].get("lost_while_alive_s") or []
            if not any(a - 2 <= s <= b + 2 for (a, b), *_ in todo)]
    groups: list[list[int]] = []
    for s in secs:
        if groups and s - groups[-1][-1] <= 3:
            groups[-1].append(s)
        else:
            groups.append([s])
    for g in groups:
        todo.append(((float(g[0]), float(g[-1])), "lost", {"n": 0}, "lost"))
    index = []
    for (t0s, t1s), key, c, kind in todo:
        near = [r for r in sp if t0s * 1000 - 1100 <= r["t_ms"] <= t1s * 1000 + 1100]
        gl = [g for r in near for g in spike.accepted(r.get("glyphs") or []) if g["state"] == "dropped"]
        if not gl:
            continue
        glyph = (float(np.median([g["cx"] for g in gl])), float(np.median([g["cy"] for g in gl])))
        want = np.arange(t0s * 1000 - 2000, t1s * 1000 + 2001, 1000.0)
        ts = set()
        for w in want:
            j = min(len(held) - 1, bisect.bisect_left(held, w))
            if abs(held[j] - w) <= 600:
                ts.add(held[j])
        ts = sorted(ts)
        byt = {r["t"]: r for r in rows}
        panels = []
        for smp in mm.samples(ts, rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            r = byt.get(round(smp.t_ms, 3)) or {}
            a = nearest(l1, l1k, smp.t_ms)
            inrun = t0s * 1000 - 100 <= smp.t_ms <= t1s * 1000 + 100
            panels.append(_strip_panel(crop, r, a, glyph, sc, smp.t_ms / 1000,
                                 "RUN" if inrun else ""))
        if not panels:
            continue
        w = max(p.shape[1] for p in panels)
        hh = max(p.shape[0] for p in panels)
        panels = [cv2.copyMakeBorder(p, 0, hh - p.shape[0], 0, w - p.shape[1],
                                     cv2.BORDER_CONSTANT, value=(20, 20, 20)) for p in panels]
        if len(panels) % 2:
            panels.append(np.full_like(panels[0], 20))
        grid = np.vstack([np.hstack([panels[i], np.full((hh, 6, 3), 60, np.uint8), panels[i + 1]])
                          for i in range(0, len(panels), 2)])
        title = np.full((22, grid.shape[1], 3), 0, np.uint8)
        txt = (f"{sid} run {t0s:.0f}-{t1s:.0f}s ({kind}, {key}) round {c.get('round')} "
               f"side {c.get('side')} plant {c.get('plant_s')} died {c.get('player_died_s')}")
        cv2.putText(title, txt, (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
                    cv2.LINE_AA)
        path = OUT / "sheets" / f"{sid}_{int(t0s)}s_{kind}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), np.vstack([title, grid]))
        index.append({"session": sid, "t0_s": t0s, "t1_s": t1s, "kind": kind, "found_by": key,
                      "sheet": str(path), **{k: c.get(k) for k in ("n", "round", "side", "plant_s",
                                                                  "player_died_s", "carrier_before")}})
        print("sheet", path)
    (OUT / "sheets" / f"{sid}.index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")


def record_run(sid: str) -> None:
    """The session's figures as run `prior-self-20260929` in the metrics log."""
    from reticle import metrics
    m = json.loads((OUT / f"{sid}.measure.json").read_text(encoding="utf-8"))
    deps = {"script": metrics.fingerprint(pick_guarded, run_stored, run_guarded, run_audit,
                                          measure, Glyphs, pick_self_declared,
                                          HOLD_MS=HOLD_MS, AUDIT_EVERY=AUDIT_EVERY),
            "version": VERSION, "spike": "spike-0.2.0", "ally_icon": "ally-icon-0.4.0",
            "minimap": "minimap-0.7.0", "teardrop": teardrop.TEARDROP_VERSION}
    parts = {"audit-reproduced": m["R1"],
             "replay-vs-l1": {k: m["R2"][k] for k in ("both", "within_0.5px")},
             "points": {k: v for k, v in m["points"].items() if not isinstance(v, (list, dict))},
             "audit-cadence": m["A1"], "teardrop": m["teardrop"]}
    for key in ("ally_cheb", "l1_owner", "stored", "guarded"):
        parts[f"on-glyph-{key.replace('_', '-')}"] = m[f"runs_{key}"]
    for part, values in parts.items():
        metrics.record("prior_self", part=part, session=sid, values=values, deps=deps,
                       note="stored rows and the 15 Hz minimap crop cache; no decode",
                       run_id="prior-self-20260929")
    print(f"{sid}: recorded {len(parts)} parts")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["replay", "measure", "sheets", "record", "measure_b", "score"])
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    idle()
    for sid in a.sessions:
        if a.what == "replay":
            replay(sid, a.limit)
        elif a.what == "measure":
            res = measure(sid)
            out = {k: v for k, v in res.items() if not k.startswith("_")}
            runs = {}
            for key in ("ally_cheb", "l1_owner", "stored", "guarded"):
                runs[key] = [run_context(sid, res, r) for r in runs_of(res["_samples"], key)]
            out["runs"] = runs
            (OUT / f"{sid}.measure.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
            print(json.dumps({k: v for k, v in out.items() if k != "runs"}, indent=1))
            for key, rr in runs.items():
                print(f"-- runs {key}")
                for c in rr:
                    if c["n"] >= 3:
                        print("  ", c)
        elif a.what == "sheets":
            sheets(sid)
        elif a.what == "record":
            record_run(sid)
        elif a.what == "measure_b":
            print(json.dumps(measure_b(sid), indent=1))
        elif a.what == "score":
            print(json.dumps({k: v for k, v in score_labels().items() if k != "detail"}, indent=1))
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
