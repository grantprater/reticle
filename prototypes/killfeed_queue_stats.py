r"""The killfeed stack as a queue: lifetime, pitch, capacity, slides, from stored data.

    .\.venv\Scripts\python.exe prototypes\killfeed_queue_stats.py extract [SID ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_queue_stats.py stats [SID ...] [--record] [--list N]
    .\.venv\Scripts\python.exe prototypes\killfeed_queue_stats.py sheet SID T0 T1 OUT.png

`checks.track_entries` follows entries slot by slot; at bdfdcf009dba 674.0 s
an entry took another's misread divider and jumped two slots. A queue model
needs the stack's invariants first, and the entry tracks cannot measure the
invariants they are meant to obey. This harness therefore builds its own
instrument from the killfeed crop cache (`roi_cache`, the `hud` set; no
decode) and cross-checks it against the stored hud rows.

The instrument
--------------
`extract` reads every cached killfeed crop and keeps each run of plate rows:
a row profile of EITHER plate colour inside the row's own entry extent (the
reader's `_row_profile` without its both-colours test, which drops one-colour
revive entries), runs rejoined by `killfeed._join_split_runs`, the reader's
overlay mask applied. Each band keeps its rows, plate extent, per-column
green/red/white-text counts, and the mean V of its plate columns per row (for a
sub-pixel edge). Bands go to `<store>/analysis/killfeed-queue-20261002/bands/`.

`stats` links bands across 2 Hz samples by APPEARANCE, not position: the
plate's right edge within `RIGHT_TOL` px and a similarity of the green-minus-red
and white-text column profiles of at least `SIM_GATE`; the cheapest pair wins,
with a tie-break of 0.002 per px of vertical travel only, so identical entries
(two kills of one victim by one killer) fall to the nearer. An entry's
contentless plate one sample before (slide-in) or after (fade-out) is kept as
`blank_in` / `blank_out`.

A lifetime is CLEAN when the sample before the arrival and the two after the
expiry hold no band resembling the entry (similarity >= `GHOST_SIM`), the track
has no missing sample, no stall [domain:capture/stalled-capture], Esc menu or
Tab board sample falls in it, it is not at a session edge, and Riot's match
record (`<store>/external/riot`, aligned per session to these arrivals with
`riot_ground_truth.fit_alignment`) places a kill within `RIOT_TOL_MS` of the
arrival. The Riot gate is what keeps an entry that arrived while the killfeed
was hidden (a death-cam transition fades it out and back in) from reading as
a short life.

Rest positions are fitted as `FIRST + pitch * k` from sub-pixel top edges of
resting non-self entries (self entries wear a frame one row taller
[domain:killfeed/self-yellow-frame]).

What it measured (2026-10-02): the entry lifetime
[domain:killfeed/entry-lifetime], the rest pitch [domain:killfeed/slot-pitch],
the queue and its slides [domain:killfeed/stack-queue], and the round clear
[domain:killfeed/round-clear].

Not wired: a measurement harness; `checks.track_entries` keeps its own walk.
Predictions and outcome: `killfeed-queue-facts-20261002` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import pickle
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import killfeed as kf  # noqa: E402
from reticle.ability_coverage import _jsonl as _read_rows  # noqa: E402
from reticle.geometry import manifest as _stored_manifest  # noqa: E402
from reticle.screen import _runs  # noqa: E402

QUEUE_STATS_VERSION = "killfeed-queue-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "killfeed-queue-20261002"
STEP_MS = 500.0
#: Band filters: an entry is right-aligned in the ROI and one plate tall.
#: A self-as-victim entry's plate colour stops at 420-460 inside the yellow
#: frame [domain:killfeed/self-yellow-frame], so the right edge gate is 415.
RIGHT_MIN, H_MIN, H_MAX, W_MIN = 415, 20, 40, 60
#: White text pixels in a band's text rows below which the plate is blank
#: (sliding in, fading out, or washed).
CONTENT_MIN = 60
RIGHT_TOL = 6
SEAM_TOL = 5
SIM_GATE = 0.5
GHOST_SIM = 0.3
MAX_GAP = 2
#: A run this far right that fails `valid` marks a sample the instrument
#: cannot vouch for.
JUNK_RIGHT = 300
RIOT_TOL_MS = 750.0
#: A conservative exclusion, not a measured clear: 5 entries vanished between
#: the samples 3.0 s and 2.5 s before a round's clock reset, yet 70 of 73
#: clean entries spanning that instant lived the full 10 samples (2026-10-02).
#: The round transition can cut an entry; its instant is unmeasured, so an
#: entry spanning start - 2.75 s leaves the lifetime fit.
PRE_START_MS = 2750.0
#: Rest-slot tolerance in px for "at rest" (a self entry's frame adds a row).
REST_TOL = 2.0
MATCH_MIN_MIN = 15.0


def _below_normal() -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.GetCurrentProcess.restype = ctypes.c_void_p
            k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00004000)
    except Exception:                                   # noqa: BLE001 -- best effort
        pass


def match_sessions() -> list[str]:
    out = []
    for p in sorted((STORE / "manifests").glob("*.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        if m["source"]["duration_ms"] / 60000.0 > MATCH_MIN_MIN:
            out.append(m["session_id"])
    return out


def session_manifest(sid: str) -> dict:
    m = _stored_manifest(sid, STORE)
    if m is None:
        raise FileNotFoundError(f"no manifest for {sid}")
    return m


# ------------------------------------------------------------------ extract

def _any_profile(green, red, usable):
    """`killfeed._row_profile` without the both-colours test."""
    plate = (green | red).astype(np.int32)
    rows = np.arange(plate.shape[0])
    total = plate.sum(axis=1)
    cum = plate.cumsum(axis=1)
    lo_n = np.maximum(1, np.ceil(kf.EXTENT_TRIM * total)).astype(np.int32)
    hi_n = np.maximum(1, np.ceil((1.0 - kf.EXTENT_TRIM) * total)).astype(np.int32)
    lo = (cum >= lo_n[:, None]).argmax(axis=1)
    hi = (cum >= hi_n[:, None]).argmax(axis=1)
    inside = cum[rows, hi] - cum[rows, lo] + plate[rows, lo]
    vis = usable.astype(np.int32).cumsum(axis=1)
    seen = (vis[rows, hi] - vis[rows, lo] + usable[rows, lo]).astype(np.float64)
    prof = np.divide(inside, seen, out=np.zeros(plate.shape[0]), where=seen > 0)
    prof[total < 40] = 0.0
    return prof


def frame_bands(img, usable) -> list[dict]:
    g, r, w = kf._plate_masks(img, usable)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    prof = _any_profile(g, r, usable)
    bands = []
    for a, z in kf._join_split_runs([(int(a), int(z)) for a, z in _runs(prof > kf.PLATE_ROW_FRAC)]):
        if z - a < 8:
            continue
        rows = slice(a, z)
        colshare = (g[rows] | r[rows]).mean(axis=0)
        pc = colshare >= 0.3
        cols = np.where(pc)[0]
        tr = slice(min(a + 6, z), max(a + 6, z - 6))
        vv = hsv[max(0, a - 4):min(len(prof), z + 4), :, 2].astype(np.float32)
        bands.append(dict(
            a=a, z=z, left=int(cols.min()) if len(cols) else -1,
            right=int(cols.max()) if len(cols) else -1,
            gcol=g[rows].sum(axis=0).astype(np.uint8), rcol=r[rows].sum(axis=0).astype(np.uint8),
            wtext=(w[tr] > 0).sum(axis=0).astype(np.uint8),
            vrow=(vv[:, pc].mean(axis=1) if pc.any() else np.zeros(len(vv))).astype(np.float32),
            v0=max(0, a - 4),
        ))
    return bands


def extract(sid: str) -> str:
    from reticle.roi_cache import RoiCache
    from reticle.profiles import get_profile
    m = session_manifest(sid)
    cache, why = RoiCache.load(STORE, m, get_profile(m["source_profile"]), "killfeed")
    if cache is None:
        return f"{sid} refused: {why}"
    mp = STORE / "masks" / f"{sid}.kf.npy"
    usable = np.load(mp) if mp.is_file() else None
    frames, t0 = [], time.time()
    for _fi, t, img in cache.crops("killfeed"):
        if img is None:
            frames.append((t, None))
            continue
        if usable is None:
            usable = np.ones(img.shape[:2], bool)
        frames.append((t, frame_bands(img, usable)))
    (OUT / "bands").mkdir(parents=True, exist_ok=True)
    with open(OUT / "bands" / f"{sid}.pkl", "wb") as fh:
        pickle.dump({"sid": sid, "frames": frames, "rect": cache.stored_rect("killfeed"),
                     "hz": cache.record.get("hz"), "version": QUEUE_STATS_VERSION}, fh)
    return f"{sid} {len(frames)} samples {time.time() - t0:.0f}s"


# ------------------------------------------------------------------ instrument

def valid(b) -> bool:
    h = b["z"] - b["a"]
    return b["right"] >= RIGHT_MIN and H_MIN <= h <= H_MAX and b["left"] < b["right"] - W_MIN


def content(b) -> bool:
    return int(b["wtext"].sum()) >= CONTENT_MIN


def _corr(u, v) -> float:
    u = u - u.mean()
    v = v - v.mean()
    d = float(np.sqrt((u * u).sum() * (v * v).sum()))
    return float((u * v).sum() / d) if d > 0 else 0.0


def seam(b):
    """The killer-to-victim plate boundary: `(column, left colour, right
    colour)` of the best two-colour step over the plate columns, or
    `(None, colour, colour)` for a one-colour (same-side) entry."""
    if "_seam" in b:
        return b["_seam"]
    h = max(1, b["z"] - b["a"])
    g = b["gcol"].astype(int)
    r = b["rcol"].astype(int)
    plate = (g + r) >= h / 3
    lab = np.where(g > r, 1, -1)[plate]
    cols = np.where(plate)[0]
    if len(cols) < 20:
        b["_seam"] = (None, 0, 0)
        return b["_seam"]
    best = None
    for left, right in ((1, -1), (-1, 1)):
        a = np.concatenate([[0], np.cumsum(lab == left)])
        z = np.concatenate([np.cumsum((lab == right)[::-1])[::-1], [0]])
        score = a + z
        k = int(score.argmax())
        if best is None or score[k] > best[0]:
            best = (int(score[k]), k, left, right)
    one = max(int((lab == 1).sum()), int((lab == -1).sum()))
    if best[0] - one < 15 or best[1] in (0, len(cols)):
        col = 1 if (lab == 1).sum() >= (lab == -1).sum() else -1
        b["_seam"] = (None, col, col)
    else:
        b["_seam"] = (int(cols[best[1] - 1]), best[2], best[3])
    return b["_seam"]


def same_entry(b, c) -> bool:
    """Hard identity gates: right edge, plate colours and their seam."""
    if abs(b["right"] - c["right"]) > RIGHT_TOL:
        return False
    sb, sc = seam(b), seam(c)
    if sb[1:] != sc[1:]:
        return False
    if (sb[0] is None) != (sc[0] is None):
        return False
    return sb[0] is None or abs(sb[0] - sc[0]) <= SEAM_TOL


def regular(b) -> bool:
    """A band whose rows are one whole plate (the self frame adds two)."""
    return 32 <= b["z"] - b["a"] <= 36


def sim(b, c) -> float:
    lo = 150
    s1 = b["gcol"][lo:].astype(float) - b["rcol"][lo:].astype(float)
    s2 = c["gcol"][lo:].astype(float) - c["rcol"][lo:].astype(float)
    return 0.5 * _corr(s1, s2) + 0.5 * _corr(b["wtext"][lo:].astype(float), c["wtext"][lo:].astype(float))


def soft_top(b) -> float | None:
    """Sub-pixel plate top: the integral of the plate-column V step (K3's
    estimator) over the rows a-3..a+3, flanks from a-4 and a+2..a+5."""
    v = b["vrow"].astype(float)
    k = b["a"] - b["v0"]
    if k < 4 or k + 6 > len(v):
        return None
    lo, hi = v[k - 4], float(np.median(v[k + 2:k + 6]))
    if abs(hi - lo) < 15:
        return None
    w = np.clip((v[k - 3:k + 4] - lo) / (hi - lo), 0, 1)
    return float(b["a"] + 4 - w.sum())


def track(frames) -> list[dict]:
    tracks, active = [], []
    for i, (t, bs) in enumerate(frames):
        if bs is None:
            continue
        cont = [b for b in bs if valid(b) and content(b)]
        pairs = []
        for ti, tr in enumerate(active):
            lb = tr["obs"][-1][2]
            for bi, b in enumerate(cont):
                if not same_entry(b, lb):
                    continue
                c = sim(b, lb)
                if c >= SIM_GATE:
                    pairs.append(((1 - c) + 0.002 * abs(b["a"] - lb["a"]), ti, bi))
        pairs.sort()
        ut, ub = set(), set()
        for _c, ti, bi in pairs:
            if ti in ut or bi in ub:
                continue
            ut.add(ti)
            ub.add(bi)
            active[ti]["obs"].append((i, t, cont[bi]))
        for bi, b in enumerate(cont):
            if bi not in ub:
                tr = {"id": len(tracks), "obs": [(i, t, b)], "blank_in": None, "blank_out": None}
                tracks.append(tr)
                active.append(tr)
        active = [tr for tr in active if i - tr["obs"][-1][0] <= MAX_GAP]
    for tr in tracks:
        i0, _, b0 = tr["obs"][0]
        il, _, bl = tr["obs"][-1]
        if i0 > 0 and frames[i0 - 1][1]:
            for pb in frames[i0 - 1][1]:
                if valid(pb) and not content(pb) and abs(pb["a"] - b0["a"]) <= 6:
                    tr["blank_in"] = i0 - 1
        if il + 1 < len(frames) and frames[il + 1][1]:
            for pb in frames[il + 1][1]:
                if (valid(pb) and not content(pb) and abs(pb["a"] - bl["a"]) <= 6
                        and abs(pb["right"] - bl["right"]) <= RIGHT_TOL):
                    tr["blank_out"] = il + 1
    return tracks


def frame_ok(frames, i) -> bool:
    """Sample i was read and holds no plate-coloured run that is not an
    entry (scenery in plate colours, a wipe, a cut band): a sample where the
    instrument can say an entry is absent."""
    if i < 0 or i >= len(frames) or frames[i][1] is None:
        return False
    return all(valid(c) for c in frames[i][1] if c["z"] - c["a"] >= 8 and c["right"] >= JUNK_RIGHT)


def ghost_at(frames, i, b) -> bool:
    """Does sample i hold a band resembling b anywhere (or is it unread)?"""
    if i < 0 or i >= len(frames) or frames[i][1] is None:
        return True
    for c in frames[i][1]:
        if valid(c) and content(c) and same_entry(c, b) and sim(c, b) >= GHOST_SIM:
            return True
    return False


# ------------------------------------------------------------------ context

def rounds(sid):
    import pyarrow.parquet as pq
    p = sorted(STORE.glob(f"l2/rounds/*/session={sid}/rounds.parquet"))
    return pq.read_table(p[0]).to_pylist() if p else []


def stall_spans(sid):
    import pyarrow.parquet as pq
    from reticle import stalls
    p = sorted(STORE.glob(f"l1/primitives/*/session={sid}/primitives.parquet"))
    if not p:
        return None
    t = pq.read_table(p[0], columns=["t_ms", "motion"])
    return stalls.spans(np.asarray(t["t_ms"]), np.asarray(t["motion"]))


def _rows_or_none(path: Path):
    """A stored stream's rows, or None when the session has no such stream."""
    return _read_rows(path) if path.is_file() else None


def board_present(sid):
    rows = _rows_or_none(STORE / "events" / "scoreboard_presence" / f"{sid}.jsonl")
    return None if rows is None else {r["t_ms"] for r in rows if r.get("kind") == "sample" and r.get("present")}


def menu_open(sid):
    rows = _rows_or_none(STORE / "events" / "menu_open" / f"{sid}.jsonl")
    return None if rows is None else {r["t_ms"] for r in rows if r.get("kind") == "open"}


def riot_kill_times(sid, arrivals_ms):
    """Riot kills of this session aligned to these arrivals (slope 1)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import riot_ground_truth as rgt
    recs = rgt.riot_records(STORE)
    if sid not in recs:
        return None, None
    g = sorted(k["gameTime"] for k in recs[sid]["match"]["kills"])
    al = rgt.fit_alignment(g, arrivals_ms)
    if al is None:
        return None, None
    return sorted(al["a_ms"] + x for x in g), al


def stored_hud(sid):
    """Stored per-sample killfeed rows, only when the hud stream is at the
    current HUD_VERSION; else None and the version found."""
    import pyarrow.parquet as pq
    from reticle.version import HUD_VERSION
    p = sorted(STORE.glob(f"l1/hud/*/session={sid}/hud.parquet"))
    if not p:
        return None, None
    ver = (pq.read_schema(p[0]).metadata or {}).get(b"hud_version", b"").decode()
    if ver != HUD_VERSION:
        return None, ver
    t = pq.read_table(p[0], columns=["t_ms", "kf_entry_mask", "kf_entries"])
    return dict(zip(t["t_ms"].to_pylist(), t["kf_entry_mask"].to_pylist())), ver


# ------------------------------------------------------------------ stats

def slot_f(top, first, pitch):
    return (top - first) / pitch


def session_stats(sid, first, pitch, acc, listing):
    d = pickle.load(open(OUT / "bands" / f"{sid}.pkl", "rb"))
    frames = d["frames"]
    n = len(frames)
    times = [t for t, _ in frames]
    path = session_manifest(sid)["source"]["path"]
    trs = track(frames)
    real = [tr for tr in trs if len(tr["obs"]) >= 3]
    rs = rounds(sid)
    stl = stall_spans(sid) or []
    bd = board_present(sid) or set()
    mn = menu_open(sid) or set()
    riot, al = riot_kill_times(sid, [tr["obs"][0][1] for tr in real])
    acc["riot_align"][sid] = None if al is None else {
        "a_ms": round(al["a_ms"], 1), "matched": al["matched"], "n_riot": al["n_riot"],
        "mad_ms": round(al["residual_mad_ms"], 1)}

    def stalled(t0, t1):
        return any(s["t_start_ms"] <= t1 and s["t_end_ms"] >= t0 for s in stl)

    def flagged(i0, i1):
        ts = [times[k] for k in range(max(0, i0), min(n, i1 + 1))]
        return any(t in bd for t in ts), any(t in mn for t in ts)

    bounds = []
    for r in rs:
        for nm in ("t_end_ms", "t_close_ms"):
            if r.get(nm) is not None:
                bounds.append((r[nm], nm))
        if r.get("t_start_ms"):
            bounds.append((r["t_start_ms"] - PRE_START_MS, "pre_start_ms"))

    # per-sample occupancy by real tracks
    occ = collections.defaultdict(list)          # i -> [(top, track)]
    reg = set()                                  # (i, track id) read as one whole plate
    for tr in real:
        for i, t, b in tr["obs"]:
            occ[i].append((b["a"], tr))
            if regular(b):
                reg.add((i, id(tr)))

    # ---- Q2 pitch: resting sub-pixel tops
    for tr in real:
        for i, t, b in tr["obs"]:
            h = b["z"] - b["a"]
            if not (32 <= h <= 35):            # the self frame makes 36
                continue
            s = soft_top(b)
            if s is None:
                continue
            acc["tops"].append(s)

    # ---- Q1 lifetimes
    for tr in real:
        o = tr["obs"]
        i0, il = o[0][0], o[-1][0]
        b0, bl = o[0][2], o[-1][2]
        gaps = (il - i0 + 1) - len(o)
        nobs = il - i0 + 1
        why = []
        if i0 == 0 or il >= n - 3:
            why.append("session_edge")
        if gaps:
            why.append("gap")
        if ghost_at(frames, i0 - 1, b0):
            why.append("arrival_unseen")
        elif not frame_ok(frames, i0 - 1):
            why.append("arrival_junk")
        if ghost_at(frames, il + 1, bl) or ghost_at(frames, il + 2, bl):
            why.append("expiry_unseen")
        elif not (frame_ok(frames, il + 1) and frame_ok(frames, il + 2)):
            why.append("expiry_junk")
        if stalled(times[max(0, i0 - 1)], times[min(n - 1, il + 1)]):
            why.append("stall")
        fb, fm = flagged(i0 - 1, il + 1)
        rec_board = fb
        if fm:
            why.append("menu")
        rd = None
        if riot is not None:
            t0 = o[0][1]
            k = bisect.bisect_left(riot, t0 - RIOT_TOL_MS - STEP_MS)
            near = [x for x in riot[k:k + 6] if abs(t0 - x) <= RIOT_TOL_MS + STEP_MS]
            rd = min((t0 - x for x in near), key=abs) if near else None
            if rd is None or abs(rd) > RIOT_TOL_MS:
                why.append("no_riot_kill")
        else:
            why.append("no_riot_record")
        bnd = [nm for v, nm in bounds if o[0][1] - STEP_MS <= v <= o[-1][1] + STEP_MS]
        rec = {"sid": sid, "t0": o[0][1] / 1000, "t1": o[-1][1] / 1000, "n": nobs,
               "blank_in": tr["blank_in"] is not None, "blank_out": tr["blank_out"] is not None,
               "slot0": round(slot_f(b0["a"], first, pitch), 2),
               "slot1": round(slot_f(bl["a"], first, pitch), 2),
               "why": why, "board": rec_board, "bounds": bnd, "riot_dt": rd, "path": path}
        acc["lives"].append(rec)
        if riot is not None and rd is not None:
            acc["riot_dt"].append(rd)

    # ---- per-transition queue checks (Q1 own timer, Q4, Q5)
    lastidx = {}
    for tr in real:
        for i, t, b in tr["obs"]:
            pass
    for i in range(n - 2):
        if not (frame_ok(frames, i) and frame_ok(frames, i + 1) and frame_ok(frames, i + 2)):
            acc["transitions_junk"] += 1
            continue
        t0, t1 = times[i], times[i + 1]
        if stalled(t0, times[i + 2]) or t0 in mn or t1 in mn:
            continue
        here = sorted(occ.get(i, []), key=lambda x: x[0])
        nxt = {id(tr): top for top, tr in occ.get(i + 1, [])}
        nxt2 = {id(tr) for top, tr in occ.get(i + 2, [])}
        acc["transitions"] += 1
        acc["count_hist"][len(here)] += 1
        if here and len(here) >= acc["max_count"][0]:
            if len(here) > acc["max_count"][0]:
                acc["max_count"] = (len(here), [])
            acc["max_count"][1].append((sid, t0 / 1000, path))
        viol = []
        gone = []
        for top, tr in here:
            if id(tr) in nxt:
                if (i, id(tr)) not in reg or (i + 1, id(tr)) not in reg:
                    acc["dy_irregular"] += 1
                    continue
                dy = nxt[id(tr)] - top
                acc["dy"][int(round(dy))] += 1
                if dy > REST_TOL:
                    viol.append(("moved_down", tr, round(dy)))
            elif id(tr) not in nxt2 and not ghost_at(frames, i + 1, tr["obs"][-1][2]):
                gone.append((top, tr))
        # R1 order kept
        surv = [(top, nxt[id(tr)], tr) for top, tr in here if id(tr) in nxt]
        survr = [x for x in surv if (i, id(x[2])) in reg and (i + 1, id(x[2])) in reg]
        for (ta, na, a), (tb, nb, b) in zip(survr, survr[1:]):
            if nb < na - REST_TOL:
                viol.append(("passed", b, round(nb - na)))
        # R5 FIFO: a vanished entry with a surviving entry above it
        for top, tr in gone:
            above = [x for x in surv if x[0] < top - 10]
            if above:
                viol.append(("lower_expired_first", tr, len(above)))
            acc["expiry_slot"][int(round(slot_f(top, first, pitch)))] += 1
        # Q4 holes: after each expiry, what do the entries below do next?
        for top, tr in gone:
            below = [x for x in survr if x[0] > top + 10]
            for ta, na, b in below:
                dy = na - ta
                cls = ("hole" if abs(dy) <= REST_TOL else
                       "risen" if abs(dy + pitch) <= REST_TOL or abs(dy + 2 * pitch) <= REST_TOL else
                       "mid" if dy < 0 else "down")
                acc["after_expiry"][cls] += 1
            if below:
                # samples the hole persists after this expiry
                b = below[0][2]
                k, cnt = i + 1, 0
                start = below[0][0]
                while k < n:
                    pos = [x[0] for x in occ.get(k, []) if x[1] is b and (k, id(b)) in reg]
                    if not pos or abs(pos[0] - start) > REST_TOL:
                        break
                    cnt += 1
                    k += 1
                acc["hole_runs"][cnt] += 1
        # R3 rise only into vacated space
        empty_above_slots = None
        for ta, na, b in survr:
            rise = (ta - na) / pitch
            if rise > 0.5:
                vac = len([1 for top, tr in gone if top < ta])
                slot_now = slot_f(ta, first, pitch)
                occupied_above = len([1 for x in here if x[0] < ta - 10])
                holes = max(0, int(round(slot_now)) - occupied_above)
                if round(rise) > vac + holes:
                    viol.append(("rise_without_space", b, round(rise, 2)))
        # R4 arrivals at the bottom
        for top, tr in occ.get(i + 1, []):
            if tr["obs"][0][0] == i + 1 and tr["blank_in"] is None:
                lower = [x for x in surv if x[1] > top + 10]
                if lower:
                    viol.append(("arrived_above", tr, len(lower)))
                acc["arrival_slot"][int(round(slot_f(top, first, pitch)))] += 1
        # rest/mid census
        for top, tr in here:
            if (i, id(tr)) not in reg:
                acc["irregular"] += 1
                continue
            k = slot_f(top, first, pitch)
            off = abs(top - (first + pitch * round(k)))
            acc["rest" if off <= REST_TOL else "midslide"] += 1
        if viol:
            acc["violations"].append({"sid": sid, "t": t0 / 1000, "path": path,
                                      "rules": [(v[0], round(v[1]["obs"][0][1] / 1000, 1), v[2]) for v in viol]})

    # ---- cross-check against the stored rows (hud-0.17.0 only)
    hud, ver = stored_hud(sid)
    acc["hud_versions"][sid] = ver
    if hud is not None:
        agree = tot = 0
        for i in range(n):
            if frames[i][1] is None or times[i] not in hud:
                continue
            mine = 0
            for top, tr in occ.get(i, []):
                mine |= 1 << max(0, min(kf.MAX_SLOTS - 1, int(round(slot_f(top, first, pitch)))))
            st = hud[times[i]] or 0
            tot += 1
            agree += int(mine == st)
            if mine != st:
                acc["hud_disagree"].append((sid, times[i] / 1000, mine, st))
        acc["hud_agree"][sid] = (agree, tot)
    return len(real)


def fit_pitch(tops):
    """Rest positions FIRST + pitch*k by least squares on per-slot medians."""
    tops = np.asarray(tops)
    k0 = np.round((tops - kf.FIRST_Y) / 39.0)
    ks, meds, ns = [], [], []
    for k in sorted(set(k0.astype(int))):
        v = tops[k0 == k]
        v = v[np.abs(v - np.median(v)) <= 1.5]
        if len(v) >= 10:
            ks.append(k)
            meds.append(float(np.median(v)))
            ns.append(len(v))
    A = np.vstack([np.ones(len(ks)), ks]).T
    (first, pitch), *_ = np.linalg.lstsq(A, np.array(meds), rcond=None)
    return float(first), float(pitch), list(zip(ks, meds, ns))


def stats(sids, record=False, list_n=40):
    acc = {"tops": [], "lives": [], "riot_dt": [], "riot_align": {}, "transitions": 0, "transitions_junk": 0,
           "count_hist": collections.Counter(), "max_count": (0, []), "dy": collections.Counter(),
           "expiry_slot": collections.Counter(), "after_expiry": collections.Counter(),
           "hole_runs": collections.Counter(), "arrival_slot": collections.Counter(),
           "rest": 0, "midslide": 0, "irregular": 0, "dy_irregular": 0, "violations": [], "hud_versions": {}, "hud_agree": {},
           "hud_disagree": []}
    # pass 1: pitch from resting tops (independent of the slot assignment)
    for sid in sids:
        d = pickle.load(open(OUT / "bands" / f"{sid}.pkl", "rb"))
        for t, bs in d["frames"]:
            for b in bs or []:
                if valid(b) and content(b) and 32 <= b["z"] - b["a"] <= 35:
                    s = soft_top(b)
                    if s is not None:
                        acc["tops"].append(s)
    first, pitch, per_slot = fit_pitch(acc["tops"])
    acc["tops"] = []
    print(f"rest fit: first {first:.3f} pitch {pitch:.3f}; per slot (k, median, n): "
          + ", ".join(f"({k}, {m:.2f}, {c})" for k, m, c in per_slot))
    for sid in sids:
        session_stats(sid, first, pitch, acc, list_n)
    return summarise(acc, sids, first, pitch, per_slot, record, list_n)


def summarise(acc, sids, first, pitch, per_slot, record, list_n):
    lives = acc["lives"]
    clean = [r for r in lives if not r["why"]]
    nb = [r for r in clean if not r["bounds"]]
    nh = collections.Counter(r["n"] for r in nb)
    out = {}
    print(f"\nQ1 lifetime: {len(lives)} tracks, {len(clean)} clean, {len(nb)} clean away from a round boundary")
    print("  content samples per clean entry:", sorted(nh.items()))
    why = collections.Counter(w for r in lives for w in r["why"])
    print("  exclusions:", why.most_common())
    if nb:
        ns = np.array([r["n"] for r in nb], float)
        L = 0.5 * ns.mean()
        top2 = sum(c for _k, c in nh.most_common(2)) / len(nb)
        out.update(life_n=len(nb), life_mean_s=round(L, 3), life_two_bins_share=round(top2, 4),
                   life_min_samples=int(ns.min()), life_max_samples=int(ns.max()))
        print(f"  E[n] x 0.5 s = {L:.3f} s; two commonest counts hold {top2:.3f}")
        (k1, c1), (k2, c2) = sorted(nh.most_common(2))
        if k2 == k1 + 1:
            # n takes floor and ceil of L / 0.5 under a uniform sampling phase
            L2 = 0.5 * (k1 + c2 / (c1 + c2))
            se = 0.5 * float(np.sqrt(c2 / (c1 + c2) * c1 / (c1 + c2) / (c1 + c2)))
            print(f"  two-count estimate: L = 0.5 x ({k1} + {c2}/{c1 + c2}) = {L2:.3f} s (binomial SE {se:.3f} s)")
            out.update(life_lo_n=k1, life_lo_count=c1, life_hi_count=c2, life_L_s=round(L2, 3), life_L_se_s=round(se, 4))
        odd = [r for r in nb if r["n"] not in dict(nh.most_common(2))]
        print("  outside the two commonest counts:")
        for r in odd[:list_n]:
            print(f"    {r['sid']} {r['t0']:.1f}-{r['t1']:.1f} n={r['n']} slots {r['slot0']}->{r['slot1']} riot_dt {r['riot_dt']} {r['path']}")
    for grp in ("t_end_ms", "t_close_ms", "pre_start_ms"):
        g = [r for r in clean if grp in r["bounds"]]
        print(f"  clean entries spanning a round {grp}: {len(g)}; counts {sorted(collections.Counter(r['n'] for r in g).items())}")
    # boundary census without the riot/ghost gates
    for grp in ("t_end_ms", "t_close_ms", "pre_start_ms"):
        g = [r for r in lives if grp in r["bounds"] and "session_edge" not in r["why"] and "gap" not in r["why"]]
        print(f"  all gap-free entries spanning a round {grp}: {len(g)}; counts {sorted(collections.Counter(r['n'] for r in g).items())}")
        out[f"span_{grp[:-3]}_n"] = len(g)
        out[f"span_{grp[:-3]}_full"] = sum(1 for r in g if r["n"] >= 9)
    rd = np.array(acc["riot_dt"])
    if len(rd):
        print(f"  arrival minus aligned Riot kill: n {len(rd)}, p05 {np.percentile(rd, 5):.0f} p50 {np.median(rd):.0f} "
              f"p95 {np.percentile(rd, 95):.0f} ms; beyond {RIOT_TOL_MS:.0f} ms: {(np.abs(rd) > RIOT_TOL_MS).sum()}")
    print(f"  blank slide-in seen on {sum(r['blank_in'] for r in clean)} / {len(clean)} clean; "
          f"blank fade-out on {sum(r['blank_out'] for r in clean)}")

    print(f"\nQ2 pitch {pitch:.3f} px, first rest top {first:.3f} (ROI rows; reader PITCH {kf.PITCH}, FIRST_Y {kf.FIRST_Y})")
    resid = [m - (first + pitch * k) for k, m, c in per_slot]
    print("  per-slot residuals:", [round(x, 3) for x in resid])
    out.update(pitch_px=round(pitch, 3), first_top_px=round(first, 3),
               pitch_max_resid_px=round(max(abs(x) for x in resid), 3), pitch_slots=len(per_slot))

    mc, where = acc["max_count"]
    print(f"\nQ3 most entries at once: {mc}, at {len(where)} samples; first few: {where[:8]}")
    print("  entries per sample:", sorted(acc["count_hist"].items()))
    print("  expiry slot:", sorted(acc["expiry_slot"].items()), " arrival slot:", sorted(acc["arrival_slot"].items()))
    out.update(max_count=mc, max_count_samples=len(where))

    tot = acc["rest"] + acc["midslide"]
    print(f"\nQ4 entry-samples at rest {acc['rest']}, mid-slide {acc['midslide']} ({acc['midslide'] / max(1, tot):.4f}); "
          f"irregular band {acc['irregular']}, pairs skipped as irregular {acc['dy_irregular']}")
    print("  vertical travel between samples (px: count):", sorted(acc["dy"].items()))
    print("  entries below an expiry, next sample:", dict(acc["after_expiry"]))
    hr = acc["hole_runs"]
    nh_ = sum(hr.values())
    mean_hold = sum(k * v for k, v in hr.items()) / max(1, nh_)
    print(f"  samples the stack below stays put after an expiry: {sorted(hr.items())}; mean {mean_hold:.3f} -> delay ~ {0.5 * mean_hold:.3f} s")
    out.update(midslide_share=round(acc["midslide"] / max(1, tot), 4), entry_samples=tot,
               hold_mean_samples=round(mean_hold, 3), hold_delay_s=round(0.5 * mean_hold, 3),
               expiries_with_below=nh_)

    v = acc["violations"]
    print(f"\nQ5 queue model over {acc['transitions']} transitions ({acc['transitions_junk']} skipped for an unreadable sample): "
          f"{len(v)} with a violation ({len(v) / max(1, acc['transitions']):.4f})")
    rc = collections.Counter(r[0] for x in v for r in x["rules"])
    print("  by rule:", rc.most_common())
    for x in v[:list_n]:
        print(f"    {x['sid']} {x['t']:.1f} {x['rules']} {x['path']}")
    out.update(transitions=acc["transitions"], violating_transitions=len(v),
               **{f"viol_{k}": c for k, c in rc.items()})

    print("\nstored hud rows (current HUD_VERSION only):", {s: a for s, a in acc["hud_agree"].items()})
    print("  versions found:", collections.Counter(acc["hud_versions"].values()))
    ag = sum(a for a, t in acc["hud_agree"].values())
    tt = sum(t for a, t in acc["hud_agree"].values())
    if tt:
        out.update(hud_slot_agree=round(ag / tt, 4), hud_sessions=len(acc["hud_agree"]))
    json.dump({"out": out, "violations": v, "lives": lives, "riot_align": acc["riot_align"], "max_count_at": where,
               "hud_disagree": acc["hud_disagree"][:2000]},
              open(OUT / "summary.json", "w"), indent=1, default=str)
    if record:
        from reticle import metrics
        deps = {"killfeed_queue": QUEUE_STATS_VERSION, "sim_gate": SIM_GATE, "ghost_sim": GHOST_SIM,
                "riot_tol_ms": RIOT_TOL_MS, "rest_tol": REST_TOL, "source": "roi_cache hud killfeed crops"}
        ctx = {"sessions": sorted(sids), "n_sessions": len(sids),
               "hud_versions": sorted({str(x) for x in acc["hud_versions"].values()})}
        metrics.record("killfeed_queue", part="stack", session="match21",
                       values={k: v for k, v in out.items() if isinstance(v, (int, float))},
                       deps=deps, context=ctx)
        print("recorded killfeed_queue/stack@match21")
    return out


def sheet(sid, t0, t1, out_png, cols=4):
    from reticle.roi_cache import RoiCache
    from reticle.profiles import get_profile
    m = session_manifest(sid)
    cache, _ = RoiCache.load(STORE, m, get_profile(m["source_profile"]), "killfeed")
    tiles = []
    for _fi, t, img in cache.crops("killfeed"):
        if t0 * 1000 <= t <= t1 * 1000 and img is not None:
            im = img.copy()
            cv2.putText(im, f"{t / 1000:.1f}", (5, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            tiles.append(im)
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(out_png, np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("sids", nargs="*")
    s = sub.add_parser("stats")
    s.add_argument("sids", nargs="*")
    s.add_argument("--record", action="store_true")
    s.add_argument("--list", type=int, default=40)
    h = sub.add_parser("sheet")
    h.add_argument("sid")
    h.add_argument("t0", type=float)
    h.add_argument("t1", type=float)
    h.add_argument("out")
    a = ap.parse_args(argv)
    _below_normal()
    if a.cmd == "extract":
        for sid in a.sids or match_sessions():
            if not (OUT / "bands" / f"{sid}.pkl").exists():
                print(extract(sid), flush=True)
    elif a.cmd == "stats":
        sids = a.sids or [s for s in match_sessions() if (OUT / "bands" / f"{s}.pkl").exists()]
        stats(sids, a.record, a.list)
    else:
        sheet(a.sid, a.t0, a.t1, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
