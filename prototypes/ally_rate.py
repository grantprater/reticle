r"""Opportunity-gated reduced-rate reading of teammates' minimap icons: a simulation.

    .\.venv\Scripts\python.exe prototypes\ally_rate.py simulate SESSION [SESSION ...] --out DIR
    .\.venv\Scripts\python.exe prototypes\ally_rate.py riot SESSION [SESSION ...] --out DIR
    .\.venv\Scripts\python.exe prototypes\ally_rate.py truth SESSION --out DIR
    .\.venv\Scripts\python.exe prototypes\ally_rate.py cpu --profile PROFILE.json --out DIR

Not wired (`"wire": "no"` in `notes/predictions.jsonl`): `AllyIconReader`
(`reticle/minimap.py`, owner of `ally-candidates`) still reads every drawn
frame. This file asks what a gate would save and lose before anyone builds a
gated reader.

The gate
--------
A teammate still and out of contact need not be read at 15 Hz. The gate reads
a teammate on a frame when an INPUT says something may have changed near it,
never the reader's own outcome:

* its soft teal-key change: `teardrop.tealness` (the `icon-pose` owner's
  ally key) of a 3x3 Gaussian-blurred window round its last read pose, mean
  |dT| over a disc of `DISC_R` icon radii, against the window of its last
  read; scored softly and cut once, at `tau`;
* a killfeed death (`death_verdict.t_ms`, an observation time) under
  `DEATH_HOLD_MS` old reads every teammate;
* a ping onset (`ping.t_ms`) under `PING_HOLD_MS` old within `PING_PX` of a
  teammate reads that teammate;
* a fixed base rate reads every teammate (1, 2 or 5 Hz), as does a gap in
  the stream or the widget's return.

A local read takes the stored icon nearest the held pose within `LINK_PX`;
when none lies there the search widens to a full read of the frame (a
surprise). A teammate the gate skips is carried forward as `predicted`, with
`rests_on` naming the observation it was last read in; it is never an
observation. A teammate that appears away from every held pose waits for the
next full read.

An audit reads in full every `AUDIT_MS` at a fixed phase (`AUDIT_PHASE_MS`),
decided in advance; its reads are stored apart and never update the gate, so
they measure what the gate misses without biasing it.

What it simulates on
--------------------
The stored 15 Hz `ally_icon` rows stand for what the reader returns when it
reads; the minimap crop cache (`roi_cache`, no decode of the capture) supplies
the cue's pixels. Barrier rows pass through unchanged; the self fit stays at
15 Hz (it is not a teammate). `riot` scores the gated rows at Riot's kill
instants through `riot_ground_truth.score_minimap`; `truth` scores them over
every living teammate tick against a parsed replay (`replay_truth`,
evaluation truth only, never an input); `cpu` prices each frame's decision
with a profile's per-frame stage cycles.

Outputs (`--out`, outside the repository): `<sid>.sim.pkl` per session and
`riot.json`, `truth.json`, `cpu.json`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import pickle
import sys
import time
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle.minimap import minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.teardrop import tealness  # noqa: E402

ALLY_RATE_VERSION = "ally-rate-0.1.0"
STORE = Path.home() / "reticle-store"

#: Cue disc radius, in icon radii (the row's `r`, session median).
DISC_R = 1.6
#: Teal-change cut sweep; the headline is TAU_HEAD (chosen by eye on one
#: 300-frame slice of 3694746e4e54, logged in the prediction row).
TAUS = (0.06, 0.10, 0.15)
TAU_HEAD = 0.10
BASES_HZ = (1.0, 2.0, 5.0)
DEATH_HOLD_MS = 1500.0
PING_HOLD_MS = 1000.0
#: Widget px at scale 1.0.
PING_PX = 30.0
LINK_PX = 15.0
#: A gap longer than this between stored frames forces a full read.
GAP_MS = 100.0
#: 2.07 s, not a multiple of any base period, so the audit's phase drifts
#: through each base cycle and samples every staleness evenly (a 2.0 s audit
#: always landed 133 ms after a base read).
AUDIT_MS = 2070.0
AUDIT_PHASE_MS = 1100.0
#: Audit disagreement cuts: position at scale 1.0 (px) and facing (degrees).
AUDIT_POS_PX = 2.0
AUDIT_FAC_DEG = 15.0


def _below_normal() -> None:
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)
    cv2.setNumThreads(1)


def variants() -> list[dict]:
    """Every gate the simulation runs in one pass; `cue` False is the base rate alone."""
    out = []
    for b in BASES_HZ:
        out.append({"name": f"base{b:g}_nocue", "base_hz": b, "tau": math.inf, "death": False,
                    "ping": False})
        for tau in TAUS:
            for death in (True, False):
                out.append({"name": f"base{b:g}_tau{tau:g}_{'death' if death else 'nodeath'}",
                            "base_hz": b, "tau": tau, "death": death, "ping": True})
    return out


# ----------------------------------------------------------------- stored rows

def _lines(path: Path, needle: str):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if needle in line:
                yield json.loads(line)


def load_rows(sid: str) -> dict:
    """The stored ally_icon frames and icon rows as arrays (one pass over the file)."""
    p = STORE / "events" / "ally_icon" / f"{sid}.jsonl"
    fr_t, fr_i, fr_d = [], [], []
    ic = {k: [] for k in ("f", "x", "y", "r", "fac", "reason", "barrier", "key")}
    cov = None
    with p.open(encoding="utf-8") as f:
        for line in f:
            if '"kind":"frame"' in line or '"kind": "frame"' in line:
                r = json.loads(line)
                fr_t.append(float(r["t_ms"]))
                fr_i.append(int(r["frame_idx"]))
                fr_d.append(bool(r.get("widget_drawn")))
            elif '"kind":"icon"' in line or '"kind": "icon"' in line:
                r = json.loads(line)
                ic["f"].append(int(r["frame_idx"]))
                ic["x"].append(float(r["cx"]))
                ic["y"].append(float(r["cy"]))
                ic["r"].append(float(r.get("r") or np.nan))
                ic["fac"].append(np.nan if r.get("facing") is None else float(r["facing"]))
                ic["reason"].append(r.get("reason"))
                ic["barrier"].append(r.get("family") == "barrier")
                ic["key"].append(r.get("observation_key"))
            elif '"kind":"coverage"' in line:
                cov = json.loads(line)
    o = np.argsort(fr_t, kind="stable")
    rows = {"t": np.array(fr_t)[o], "f": np.array(fr_i)[o], "drawn": np.array(fr_d)[o],
            "version": (cov or {}).get("ally_icon_version"), "mtime": p.stat().st_mtime}
    for k in ("f", "x", "y", "r", "fac"):
        ic[k] = np.array(ic[k])
    ic["barrier"] = np.array(ic["barrier"])
    ic["reason"] = np.array(ic["reason"], dtype=object)
    ic["key"] = np.array(ic["key"], dtype=object)
    o = np.argsort(ic["f"], kind="stable")
    for k in ic:
        ic[k] = ic[k][o]
    rows["icons"] = ic
    u, s = np.unique(ic["f"], return_index=True)
    e = np.append(s[1:], ic["f"].size)
    rows["span"] = {int(a): (int(b), int(c)) for a, b, c in zip(u, s, e)}
    return rows


def cue_inputs(sid: str) -> dict:
    """Death and ping observation times: inputs from other channels, not this reader's outcome."""
    import riot_ground_truth as rg

    deaths = np.sort(np.array([float(r["t_ms"]) for r in rg.stored_deaths(STORE, sid)
                               if r.get("t_ms") is not None]))
    pings = [r for r in _lines(STORE / "events" / "ping" / f"{sid}.jsonl", '"t_ms"')
             if r.get("frame") == "widget" and r.get("x") is not None]
    return {"deaths": deaths,
            "ping_t": np.array([float(r["t_ms"]) for r in pings]),
            "ping_xy": np.array([(float(r["x"]), float(r["y"])) for r in pings]).reshape(-1, 2)}


# ----------------------------------------------------------------- the cue

class Windows:
    """Teal-key windows round a set of centres, in one gather and one blur.

    Each window is padded by one pixel so the 3x3 blur of the stacked windows
    never mixes two windows inside the scored disc."""

    def __init__(self, radius: int):
        self.R = radius
        P = radius + 1
        d = np.arange(-P, P + 1)
        self.dy, self.dx = np.meshgrid(d, d, indexing="ij")
        self.side = 2 * P + 1
        inner = (self.dx[1:-1, 1:-1] ** 2 + self.dy[1:-1, 1:-1] ** 2) <= radius ** 2
        self.disc = inner.astype(np.float32)
        self.n = float(self.disc.sum())

    def teal(self, crop: np.ndarray, xs, ys) -> np.ndarray:
        """(k, side-2, side-2) tealness of the blurred windows centred at (xs, ys)."""
        k = len(xs)
        if k == 0:
            return np.zeros((0, self.side - 2, self.side - 2), np.float32)
        H, W = crop.shape[:2]
        cx = np.rint(np.asarray(xs, float)).astype(int)
        cy = np.rint(np.asarray(ys, float)).astype(int)
        yi = np.clip(cy[:, None, None] + self.dy[None], 0, H - 1)
        xi = np.clip(cx[:, None, None] + self.dx[None], 0, W - 1)
        win = crop[yi, xi].reshape(k * self.side, self.side, 3)
        blur = cv2.GaussianBlur(win, (3, 3), 0.8, borderType=cv2.BORDER_REPLICATE)
        t = tealness(blur).reshape(k, self.side, self.side)
        return t[:, 1:-1, 1:-1]

    def score(self, now: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """Mean |dT| over the disc, per window: the soft change, cut once by the caller."""
        return (np.abs(now - ref) * self.disc).sum(axis=(1, 2)) / self.n


# ----------------------------------------------------------------- one gate

class Gate:
    """One variant's state over a session, frame by frame."""

    def __init__(self, v: dict, sc: float, win: Windows):
        self.v, self.sc, self.win = v, sc, win
        self.held = None          # dict of arrays: x, y, fac, reason, key(src idx), ref
        self.out = []             # (frame, src icon idx or -1, x, y, fac, reason, status, rests_on idx)
        self.c = Counter()
        self.audit = Counter()
        self.audit_pos, self.audit_fac = [], []
        self.decision = {}        # frame_idx -> (kind, n_held, n_read)
        self.prev_base = None

    def _full(self, f, idx, crop, rows):
        ic = rows["icons"]
        self.held = {"x": ic["x"][idx].copy(), "y": ic["y"][idx].copy(), "fac": ic["fac"][idx].copy(),
                     "reason": ic["reason"][idx].copy(), "src": idx.copy(),
                     "ref": self.win.teal(crop, ic["x"][idx], ic["y"][idx])}
        for i in idx:
            self.out.append((f, int(i), ic["x"][i], ic["y"][i], ic["fac"][i], ic["reason"][i],
                             "observed", -1))

    def step(self, f, t, gap, idx, crop, rows, cues, audit_frame):
        """`idx`: indices of this frame's stored teammate rows (barriers excluded)."""
        v, ic = self.v, rows["icons"]
        tick = math.floor(t * v["base_hz"] / 1000.0)
        base = tick != self.prev_base
        self.prev_base = tick
        death = v["death"] and cues["death_open"]
        H = self.held
        if base or gap or death or H is None:
            why = ("gap" if gap or H is None else "base" if base else "death")
            self.c["full_" + why] += 1
            n_h = 0 if H is None else int(H["x"].size)
            self._full(f, idx, crop, rows)
            self.decision[f] = ("full", n_h, len(idx))
            return
        if H["x"].size == 0:
            # nothing held: a teammate who appears waits for the base rate
            if audit_frame:
                self._audit(idx, ic, np.zeros(0, bool))
            self.c["none_empty"] += 1
            self.decision[f] = ("none", 0, 0)
            return
        # the cue, per held teammate
        now = self.win.teal(crop, H["x"], H["y"])
        s = self.win.score(now, H["ref"])
        fire = s > v["tau"]
        if v["ping"] and cues["ping_xy"].shape[0]:
            d = np.hypot(H["x"][:, None] - cues["ping_xy"][None, :, 0],
                         H["y"][:, None] - cues["ping_xy"][None, :, 1])
            fire |= (d <= PING_PX * self.sc).any(axis=1)
        if audit_frame:
            self._audit(idx, ic, ~fire)
        k = np.flatnonzero(fire)
        if k.size:
            if idx.size == 0:
                self.c["surprise_full"] += 1
                self._full(f, idx, crop, rows)
                self.decision[f] = ("full", int(H["x"].size), 0)
                return
            D = np.hypot(H["x"][k][:, None] - ic["x"][idx][None], H["y"][k][:, None] - ic["y"][idx][None])
            big = 1e6
            Dg = np.where(D <= LINK_PX * self.sc, D, big)
            ri, ci = linear_sum_assignment(Dg)
            ok = Dg[ri, ci] < big
            if ok.sum() < k.size:
                # a fired teammate with no icon near its pose: widen to a full read
                self.c["surprise_full"] += 1
                self._full(f, idx, crop, rows)
                self.decision[f] = ("full", int(H["x"].size), len(idx))
                return
            hk, src = k[ri], idx[ci]
            H["x"][hk], H["y"][hk] = ic["x"][src], ic["y"][src]
            H["fac"][hk], H["reason"][hk] = ic["fac"][src], ic["reason"][src]
            H["src"][hk] = src
            H["ref"][hk] = self.win.teal(crop, ic["x"][src], ic["y"][src])
        read = np.zeros(H["x"].size, bool)
        read[k] = True
        for j in range(H["x"].size):
            self.out.append((f, int(H["src"][j]) if read[j] else -1, H["x"][j], H["y"][j], H["fac"][j],
                             H["reason"][j], "observed" if read[j] else "predicted",
                             -1 if read[j] else int(H["src"][j])))
        self.c["partial" if k.size else "none"] += 1
        self.c["teammate_read"] += int(k.size)
        self.c["teammate_carried"] += int(H["x"].size - k.size)
        self.decision[f] = ("partial" if k.size else "none", int(H["x"].size), int(k.size))

    def _audit(self, idx, ic, carried):
        """A full read stored apart: where the carried teammates really are."""
        H = self.held
        self.audit["frames"] += 1
        self.audit["carried"] += int(carried.sum())
        self.audit["stored_icons"] += int(idx.size)
        if idx.size:
            # stored icons no held pose (read or carried) lies near: appearances the gate has not seen
            Da = np.hypot(H["x"][:, None] - ic["x"][idx][None], H["y"][:, None] - ic["y"][idx][None])
            self.audit["stored_unheld"] += int(idx.size if Da.shape[0] == 0 else
                                               (Da.min(axis=0) > LINK_PX * self.sc).sum())
        if not carried.any():
            return
        if idx.size == 0:
            self.audit["carried_no_icon"] += int(carried.sum())
            return
        D = np.hypot(H["x"][carried][:, None] - ic["x"][idx][None], H["y"][carried][:, None] - ic["y"][idx][None])
        j = np.argmin(D, axis=1)
        d = D[np.arange(D.shape[0]), j]
        near = d <= LINK_PX * self.sc
        self.audit["carried_no_icon"] += int((~near).sum())
        self.audit["carried_moved"] += int((near & (d > AUDIT_POS_PX * self.sc)).sum())
        fa, fb = H["fac"][carried][near], ic["fac"][idx][j[near]]
        df = np.abs((fb - fa + 180.0) % 360.0 - 180.0)
        okf = np.isfinite(df)
        self.audit["carried_facing_read"] += int(okf.sum())
        self.audit["carried_turned"] += int((df[okf] > AUDIT_FAC_DEG).sum())
        self.audit_pos.extend(d[near].tolist())
        self.audit_fac.extend(df[okf].tolist())


# ----------------------------------------------------------------- simulate

def simulate(sid: str, out_dir: Path, limit: int | None = None) -> dict:
    store = Store(str(STORE))
    man = store.read_manifest(sid)
    pf = get_profile(man["source_profile"])
    cache, why = RoiCache.load(store.root, man, pf, "minimap")
    if cache is None:
        return {"session": sid, "refused": f"no_minimap_cache:{why}"}
    box = minimap_roi_px(pf, int(man["source"]["width"]), int(man["source"]["height"]))
    if cache.widget is not None:
        box = tuple(cache.rect_of("minimap"))
    sc = widget_scale(box[2] - box[0])
    rows = load_rows(sid)
    ic = rows["icons"]
    r_med = float(np.nanmedian(ic["r"][~ic["barrier"]]))
    win = Windows(int(math.ceil(DISC_R * r_med)))
    cues = cue_inputs(sid)
    V = variants()
    gates = [Gate(v, sc, win) for v in V]
    t_all, f_all, drawn = rows["t"], rows["f"], rows["drawn"]
    if limit:
        t_all, f_all, drawn = t_all[:limit], f_all[:limit], drawn[:limit]
    by_t = {float(t): (int(f), bool(d)) for t, f, d in zip(t_all, f_all, drawn)}
    want = [float(t) for t, d in zip(t_all, drawn) if d]
    x0, y0, x1, y1 = box
    prev_t, prev_drawn = -1e18, False
    n = 0
    seen = set()
    bench = []                     # crops + held state for timing the headline cue
    head = next(i for i, v in enumerate(V) if v["base_hz"] == 2.0 and v["tau"] == TAU_HEAD and v["death"])
    t0 = time.process_time()
    for smp in cache.samples(want, rois=("minimap",)):
        t = float(smp.t_ms)
        f, _d = by_t[t]
        seen.add(f)
        crop = smp.frame[y0:y1, x0:x1]
        sp = rows["span"].get(f)
        idx = np.arange(*sp) if sp else np.zeros(0, int)
        idx = idx[~ic["barrier"][idx]] if idx.size else idx
        gap = (t - prev_t) > GAP_MS or not prev_drawn
        di = np.searchsorted(cues["deaths"], t, side="right")
        death_open = di > 0 and t - cues["deaths"][di - 1] < DEATH_HOLD_MS
        pm = (cues["ping_t"] <= t) & (t - cues["ping_t"] < PING_HOLD_MS)
        cz = {"death_open": bool(death_open), "ping_xy": cues["ping_xy"][pm]}
        audit_frame = math.floor((t - AUDIT_PHASE_MS) / AUDIT_MS) != math.floor(
            (prev_t - AUDIT_PHASE_MS) / AUDIT_MS)
        if len(bench) < 600 and gates[head].held is not None and gates[head].held["x"].size:
            bench.append((crop.copy(), gates[head].held["x"].copy(), gates[head].held["y"].copy(),
                          gates[head].held["ref"].copy()))
        for g in gates:
            g.step(f, t, gap, idx, crop, rows, cz, audit_frame)
        prev_t, prev_drawn = t, True
        n += 1
    wall_cpu = time.process_time() - t0
    # the headline cue's own CPU: 5 repeats over the benched frames, median
    reps = []
    for _ in range(5):
        # 10 sweeps per repeat: process_time ticks at 15.6 ms on Windows
        a = time.process_time()
        for _sweep in range(10):
            for crop, xs, ys, ref in bench:
                win.score(win.teal(crop, xs, ys), ref) > TAU_HEAD
        reps.append((time.process_time() - a) / max(1, 10 * len(bench)) * 1000.0)
    res = {"session": sid, "ally_rate_version": ALLY_RATE_VERSION, "ally_icon_version": rows["version"],
           "rows_mtime": rows["mtime"], "widget_scale": sc, "box": list(box), "icon_r_median": r_med,
           "window_radius": win.R, "drawn_frames_read": n, "frames_rows": int(t_all.size),
           "drawn_rows": int(drawn.sum()), "deaths": int(cues["deaths"].size),
           "pings": int(cues["ping_t"].size), "pass_cpu_s": round(wall_cpu, 1),
           "cue_ms_per_frame": {"median": round(float(np.median(reps)), 4), "reps": [round(x, 4) for x in reps],
                                "frames": len(bench),
                                "held_per_frame": round(float(np.mean([b[1].size for b in bench])), 2)
                                if bench else None},
           "variants": {}}
    sims = {}
    for v, g in zip(V, gates):
        dec = Counter(k for k, _h, _r in g.decision.values())
        held = sum(h for _k, h, _r in g.decision.values() if _k != "full")
        rd = sum(r for _k, _h, r in g.decision.values() if _k != "full")
        rows_full = sum(r for _k, _h, r in g.decision.values() if _k == "full")
        res["variants"][v["name"]] = {
            **v, "frames": dict(dec), "counts": dict(g.c), "audit": dict(g.audit),
            "audit_pos_px": _q(g.audit_pos), "audit_fac_deg": _q(g.audit_fac),
            "teammate_frames_read_share": round((rd + rows_full) / max(1, held + rows_full), 4),
            "teammate_frames_on_gated_frames_read_share": round(rd / max(1, held), 4)}
        sims[v["name"]] = {"out": g.out, "decision": g.decision}
    res["variants"] = {k: {**d, "tau": (None if d["tau"] == math.inf else d["tau"])}
                       for k, d in res["variants"].items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{sid}.sim.pkl").open("wb") as fh:
        pickle.dump({"meta": res, "sims": sims, "seen": seen,
                     "icons": {k: rows["icons"][k] for k in ("f", "x", "y", "fac", "reason", "barrier", "key")}},
                    fh, protocol=pickle.HIGHEST_PROTOCOL)
    return res


def _q(a, nd=2):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    q = np.percentile(a, [50, 90, 99])
    return {"n": int(a.size), "median": round(float(q[0]), nd), "p90": round(float(q[1]), nd),
            "p99": round(float(q[2]), nd), "mean": round(float(a.mean()), nd)}


def load_sim(out_dir: Path, sid: str) -> dict:
    with (out_dir / f"{sid}.sim.pkl").open("rb") as fh:
        return pickle.load(fh)


def gated_icons(sim: dict, name: str) -> dict:
    """frame_idx -> [(x, y, reason, facing)] for one variant, barriers passed through."""
    ic = sim["icons"]
    out = {}
    for f, _src, x, y, fac, reason, _st, _ro in sim["sims"][name]["out"]:
        out.setdefault(f, []).append((float(x), float(y), reason, None if not np.isfinite(fac) else float(fac)))
    bi = np.flatnonzero(ic["barrier"])
    for i in bi:
        f = int(ic["f"][i])
        if f in sim["seen"]:
            out.setdefault(f, []).append((float(ic["x"][i]), float(ic["y"][i]), ic["reason"][i],
                                          None if not np.isfinite(ic["fac"][i]) else float(ic["fac"][i])))
    return out


# ----------------------------------------------------------------- riot

def riot(sids: list[str], out_dir: Path) -> dict:
    """Riot kill instants: the gated rows through `riot_ground_truth.score_minimap`."""
    import riot_ground_truth as rg

    captured = {}
    orig_score = rg.score_minimap

    def capture(*a, **kw):
        captured[a[0]] = (a, kw)
        return orig_score(*a, **kw)

    rg.score_minimap = capture
    try:
        with redirect_stdout(StringIO()):
            rg.main(list(sids) + ["--offline", "--no-status"])
    finally:
        rg.score_minimap = orig_score
    orig_rows = rg.minimap_rows
    res = {}
    for sid in sids:
        if sid not in captured:
            res[sid] = {"refused": "no_minimap_score"}
            continue
        sim = load_sim(out_dir, sid)
        a, kw = captured[sid]
        per = {}
        names = ["stored_15hz"] + list(sim["sims"])
        for name in names:
            G = None if name == "stored_15hz" else gated_icons(sim, name)

            def patched(store_root, s, want, tol, _G=G):
                fr, sb, fac, obs, ents, en, icons = orig_rows(store_root, s, want, tol)
                if _G is not None:
                    icons = {f: _G.get(f, []) for f in fr if f in sim["seen"]} | {
                        f: v for f, v in icons.items() if f not in sim["seen"]}
                return fr, sb, fac, obs, ents, en, icons

            rg.minimap_rows = patched
            try:
                m = orig_score(*a, **kw)
            finally:
                rg.minimap_rows = orig_rows
            fac = m.get("reader_facing_samples") or {}
            conv = min(fac, key=lambda c: np.median(fac[c]) if fac[c] else 999) if fac else None
            per[name] = {"kill_frames": m.get("kill_frames"), "riot_allies": m.get("riot_allies"),
                         "reader_matched": m.get("reader_matched"),
                         "reader_matched_any": m.get("reader_matched_any"),
                         "reader_icons": m.get("reader_icons"),
                         "reader_pos_err_px": m.get("reader_pos_err_px"),
                         "facing_convention": conv,
                         "reader_facing_deg": _q(fac.get(conv, [])) if conv else None}
        res[sid] = per
    return res


# ----------------------------------------------------------------- truth

def truth(sid: str, out_dir: Path) -> dict:
    """Every living teammate tick on the stream's drawn frames, against the replay."""
    import replay_truth as rt
    import riot_ground_truth as rg

    store = Store(str(STORE))
    man = store.read_manifest(sid)
    recs = rg.riot_records(STORE)
    d = recs.get(sid)
    rep = json.loads((rt.REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    entry = next((f for f in rep["files"] if f.get("capture_session") == sid), None)
    if entry is None or d is None:
        return {"session": sid, "refused": "no_replay_or_riot_record"}
    rp = rt.Replay(Path(entry["file"]).stem)
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    me = rg.identify_player(recs, STORE).get(sid, {}).get("subject")
    team = {p["subject"]: p["teamId"] for p in d["match"]["players"]}
    mates = [s for s in rp.subjects if team.get(s) == team[me] and s != me]
    kill_like, _ = rg.split_deaths(rg.stored_deaths(STORE, sid))
    al = rg.fit_alignment([e["t"] for e in rp.group("characterDeath")],
                          [float(r["t_ms"]) for r in kill_like])
    a = al["a_ms"]
    mf, why = rg.map_frame_for(sid, man, ref, {"match": {"matchInfo": {"mapId": rp.map_url()}}}, STORE)
    if mf is None:
        return {"session": sid, "refused": f"map_frame:{why}"}
    gate = rg.GATE_M * 100.0 * mf.px_per_unit
    cm_per_px = 1.0 / mf.px_per_unit
    H, W = mf.widget_shape
    sim = load_sim(out_dir, sid)
    rows = load_rows(sid)
    seen = np.array(sorted(sim["seen"]))
    t_of = dict(zip(rows["f"].tolist(), rows["t"].tolist()))
    ft = np.array([t_of[f] for f in seen])
    t_rep = rt._frames_to_replay(ft, a, rg.MINIMAP_LAG_MS)
    X = np.full((seen.size, len(mates)), np.nan)
    Y, YAW = X.copy(), X.copy()
    for c, s in enumerate(mates):
        q = rp.sample(s, t_rep)
        live = rp.alive(s, t_rep) & np.isfinite(q["x"])
        px, py = rt.to_px(mf, q["x"], q["y"])
        X[:, c] = np.where(live, px, np.nan)
        Y[:, c] = np.where(live, py, np.nan)
        YAW[:, c] = np.where(live, rt.facing_px_deg(mf, q["x"], q["y"], q["yaw"]), np.nan)
    inside = np.isfinite(X) & (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
    fpos = {int(f): i for i, f in enumerate(seen)}
    res = {"session": sid, "ally_icon_version": rows["version"], "align": {k: v for k, v in al.items() if k != "pairs"},
           "gate_px": round(gate, 2), "cm_per_px": round(cm_per_px, 3), "drawn_frames": int(seen.size),
           "living_teammate_ticks": int(np.isfinite(X).sum()),
           "living_teammate_ticks_inside": int(inside.sum()), "variants": {}}
    names = ["stored_15hz"] + list(sim["sims"])
    ic = sim["icons"]
    for name in names:
        if name == "stored_15hz":
            keep = np.isin(ic["f"], seen) & ~ic["barrier"] & np.array([r is None for r in ic["reason"]])
            of, ox, oy, ofa = ic["f"][keep], ic["x"][keep], ic["y"][keep], ic["fac"][keep]
            ost = np.array(["observed"] * int(keep.sum()))
        else:
            o = [r for r in sim["sims"][name]["out"] if r[5] is None]
            of = np.array([r[0] for r in o], int)
            ox = np.array([r[2] for r in o], float)
            oy = np.array([r[3] for r in o], float)
            ofa = np.array([r[4] for r in o], float)
            ost = np.array([r[6] for r in o])
        rix = np.array([fpos[int(f)] for f in of], int)
        D = np.hypot(X[rix] - ox[:, None], Y[rix] - oy[:, None])
        j, dist = rt._assign(of, D, gate)
        hit = j >= 0
        fe = rt._ang_deg(YAW[rix, np.clip(j, 0, None)], ofa)
        fe = np.where(hit & np.isfinite(ofa), fe, np.nan)
        pred = ost == "predicted"
        res["variants"][name] = {
            "rows": int(of.size), "predicted_rows": int(pred.sum()),
            "matched": int(hit.sum()), "phantom": int((~hit).sum()),
            "matched_share_of_living_inside": round(float(hit.sum() / max(1, inside.sum())), 4),
            "err_px": _q(dist[hit]), "err_cm": _q(dist[hit] * cm_per_px, 0),
            "err_px_predicted": _q(dist[hit & pred]), "err_px_observed": _q(dist[hit & ~pred]),
            "facing_deg": _q(fe), "facing_deg_predicted": _q(fe[pred])}
    return res


# ----------------------------------------------------------------- cpu

CYC_STEPS_TEAMMATE = ("step:portrait", "step:baseline", "step:descriptors")


def cpu(profile: Path, out_dir: Path) -> dict:
    """Price each profiled frame by its gate decision, from the profile's stage cycles.

    full or audit frame: its feed. Partly read frame, conservative: its feed
    less the skipped teammates' share of the ally pose (`step:pose` less
    `teardrop.fit_self`), portrait, baseline-disc and descriptor stages; every
    other stage (stack_fit, the spike glyph, the candidate search) still runs.
    Optimistic: the read share of everything after the widget and masks.
    Frame with no read: `widget_drawn` plus the measured cue."""
    P = json.loads(Path(profile).read_text(encoding="utf-8"))
    hz = {r["sid"]: r["cycles"] / (r["thread_ns"] / 1e6) for r in P}     # cycles per ms
    sims = {}
    res = {"windows": [], "variants": {}}
    acc = {}
    for w in P:
        sid = w["sid"]
        if sid not in sims:
            sims[sid] = load_sim(out_dir, sid)
        sim = sims[sid]
        cpm = hz[sid]
        rows_t = load_rows(sid) if "t2f" not in sim else None
        if rows_t is not None:
            sim["t2f"] = dict(zip(rows_t["t"].tolist(), rows_t["f"].tolist()))
        cue = sim["meta"]["cue_ms_per_frame"]["median"]
        audit_f = None
        for name, s in sim["sims"].items():
            dec = s["decision"]
            tot = {"full15": 0.0, "cons": 0.0, "opt": 0.0, "n": 0, "missing": 0}
            prev_t = None
            for fr in w["frames"]:
                st = fr["st"]
                F = st.get("feed", [0])[0] / cpm
                wd = st.get("minimap.widget_drawn", [0])[0] / cpm
                masks = st.get("step:masks", [0])[0] / cpm
                pose = (st.get("step:pose", [0])[0] - st.get("teardrop.fit_self", [0])[0]) / cpm
                team = pose + sum(st.get(k, [0])[0] for k in CYC_STEPS_TEAMMATE) / cpm
                f = sim["t2f"].get(fr["t_ms"])
                tot["full15"] += F
                tot["n"] += 1
                aud = prev_t is not None and math.floor((fr["t_ms"] - AUDIT_PHASE_MS) / AUDIT_MS) != \
                    math.floor((prev_t - AUDIT_PHASE_MS) / AUDIT_MS)
                prev_t = fr["t_ms"]
                if f is None or f not in dec or not fr["drawn"]:
                    tot["missing"] += int(f not in dec)
                    tot["cons"] += F
                    tot["opt"] += F
                    continue
                kind, n_h, n_r = dec[f]
                if kind == "full" or aud:
                    c_cons = c_opt = F
                elif kind == "none":
                    c_cons = c_opt = wd + cue
                else:
                    skip = (n_h - n_r) / max(1, n_h)
                    c_cons = F - team * skip + cue
                    c_opt = wd + masks + (F - wd - masks) * (n_r / max(1, n_h)) + cue
                tot["cons"] += c_cons
                tot["opt"] += c_opt
            key = (name, sid, w["kind"])
            acc[key] = tot
    for (name, sid, kind), tot in acc.items():
        d = res["variants"].setdefault(name, {"full15": 0.0, "cons": 0.0, "opt": 0.0, "n": 0, "by_window": {}})
        for k in ("full15", "cons", "opt", "n"):
            d[k] += tot[k]
        d["by_window"][f"{sid}:{kind}"] = {
            "ms_per_frame_15hz": round(tot["full15"] / tot["n"], 2),
            "ms_per_frame_cons": round(tot["cons"] / tot["n"], 2),
            "ms_per_frame_opt": round(tot["opt"] / tot["n"], 2), "missing": tot["missing"]}
    for name, d in res["variants"].items():
        d["ms_per_frame_15hz"] = round(d.pop("full15") / d["n"], 2)
        d["ms_per_frame_cons"] = round(d.pop("cons") / d["n"], 2)
        d["ms_per_frame_opt"] = round(d.pop("opt") / d["n"], 2)
        d["saving_cons"] = round(1 - d["ms_per_frame_cons"] / d["ms_per_frame_15hz"], 4)
        d["saving_opt"] = round(1 - d["ms_per_frame_opt"] / d["ms_per_frame_15hz"], 4)
    return res


# ----------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("simulate")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None, help="first N stored frames only (a smoke run)")
    p = sub.add_parser("riot")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("truth")
    p.add_argument("session")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("cpu")
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    _below_normal()
    if args.cmd == "simulate":
        for sid in args.sessions:
            r = simulate(sid, args.out, args.limit)
            (args.out / f"{sid}.sim.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
            print(json.dumps({k: v for k, v in r.items() if k != "variants"}, default=str), flush=True)
    elif args.cmd == "riot":
        r = riot(args.sessions, args.out)
        (args.out / "riot.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    elif args.cmd == "truth":
        r = truth(args.session, args.out)
        (args.out / "truth.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    elif args.cmd == "cpu":
        r = cpu(args.profile, args.out)
        (args.out / "cpu.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
