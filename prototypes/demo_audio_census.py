r"""Which game sound files fire at which offsets around the solo demos' casts:
the observational side of modelling each ability's sound phases (cast,
in-flight, landing, activation, ongoing, expire).

    python prototypes/demo_audio_census.py [--out DIR] [--sids SID ...] [--cpu] [--replace]

Reads stored data only: the audio gate's log-mel of each demo
(`analysis/audio-gate/0.1.0/features/<sid>.npz`), the demo census
(`labels/demo_cast_class`, through `ability_audio_fit.demo_truth`), the
tray drops, the reference manifest (`ability-audio-ref-0.2.0`) and the
pooled whitener of the wired parameter set (`ABILITY_AUDIO_PARAMS_VERSION`).
Decodes no video and no capture audio; it decodes the game's reference FLACs
once and caches their raw templates beside the table.

**The candidate set is the demo's agent.** A solo demo plays one agent, so
every sound of that agent's manifest rows is scored -- every folder, the
unmapped ones included (Tejo Abil_X, Deadlock Abil_E, Neon Slide, Cypher
Abil_Q, Jett Grenade), movement and footsteps too -- and no other agent's.

**The score** is the owner's: `adjudication.ability_audio.class_tracks`,
one label per file, so each file's track is its whitened Pearson
correlation less its median over the demo's null frames, over the span to
their 99.9th percentile. Templates follow the owner's rule (`template`, the
first MAX_TEMPLATE_S of a clip's active span), so a long loop is matched by
its first 1.5 s.

**A fire.** A file fires on a cast when its track's maximum from PRE_S
before the tray time `t_ms` to POST_S after it reaches the file's fire
level: the height its peaks (PEAK_GAP apart) reach ALPHA times per window
on the pooled null, every live frame of the demos of OTHER agents (no sound
of this agent plays there). `ability_audio.threshold_at` sets it. The
brief's null, cast-free frames of the agent's own demos (live and
unexplained within EXPLAIN_S of any drop or census cast), is reported as
`null_rate_same`: the chance one cast-free window of the same demos fires.

**A stable offset.** Per file and slot, the fired casts' offsets (the
window's best peak); the largest cluster within STABLE_S; stable when it
holds two casts or more and at least half the fires. `_clean` and `_own`
take instead each cast's own fire, its best fired peak with no other cast
of the demo intervening between the cast and the peak
(`intervening`, NEAR_S of margin past the peak): that cast's sound may be
the one heard. Sounds still ringing from an earlier cast are not removed;
they scatter offsets instead. Casts that share their tray time with another
slot (several drops at one instant: a round reset, not a cast) are
`coincident`: kept in the counts, left out of offsets.

**A proposed phase** is a proposal, never a domain fact: timing first
(pre-drop or near the drop: cast; repeated peaks over ONGOING_S: ongoing),
the manifest's name role (projectile, impact, loop, end) as the tie-breaker
after the drop; `unknown` with the offset where neither decides. The
game-data mapping of files to phases is another task's; this table is its
observational check.

Outputs under `analysis/demo-audio-census-20261004/` (store): census.csv
(agent x slot x file), files.csv (per file: stable slots, shared, never
fires), casts.jsonl (per cast, every file's window maximum and peaks),
sova.json, summary.json, provenance.json, contact/<agent>.png.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reticle.ability_audio_fit import (MANIFEST, REF_DIR, REF_VERSION,  # noqa: E402
                                       demo_census_sessions, demo_session, demo_truth)
from reticle.adjudication import ability_audio as aa  # noqa: E402

VERSION = "demo-audio-census-0.1.0"
STORE = Path(os.environ.get("RETICLE_STORE", "C:/Users/grant/reticle-store"))
OUT = Path("analysis") / "demo-audio-census-20261004"
#: The window around the tray time (s).
PRE_S, POST_S = 2.0, 15.0
#: The pooled null's allowed fire probability per window.
ALPHA = 0.05
#: Two peaks of one track are one sound within this (frames).
PEAK_GAP = 50
#: Peaks recorded per cast and file at or above this score.
RECORD_MIN = 0.5
#: Fired offsets within this span (s) are one cluster.
STABLE_S = 1.0
#: Margin (s) past a peak within which another cast intervenes (`intervening`).
NEAR_S = 1.0
#: Casts of different slots within this (ms) are one instant.
COINCIDENT_MS = 50.0
#: Near the drop: a cast-phase offset span (s).
CAST_SPAN = (-1.5, 0.7)
#: Ongoing: at least this many fired peaks spanning ONGOING_S on a cast.
ONGOING_PEAKS, ONGOING_S = 3, 2.0
#: The manifest's name roles that name a phase.
ROLE_PHASE = {"projectile": "in-flight", "impact": "landing", "explode": "landing",
              "bounce": "landing", "loop": "ongoing", "end": "expire"}
PHASES = ("cast", "in-flight", "landing", "activation", "ongoing", "expire", "unknown")
SOVA_MISREAD = (("02cf738b1c8f", 15500.0), ("02cf738b1c8f", 18566.7), ("aab12e41dcfc", 38050.0))


def below_normal() -> None:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)   # Below Normal


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------

def window_lambda() -> float:
    """Fires per minute at which a window of PRE_S + POST_S fires with
    probability ALPHA under a Poisson null."""
    return -math.log(1.0 - ALPHA) / ((PRE_S + POST_S) / 60.0)


def rate_at(heights: np.ndarray, level: float, minutes: float) -> float:
    """Peaks at or above `level` per minute; nan without minutes."""
    if minutes <= 0:
        return float("nan")
    return float((np.asarray(heights) >= level).sum()) / minutes


def window_rate(lam: float) -> float:
    """The chance a window fires at `lam` peaks per minute."""
    return float("nan") if not np.isfinite(lam) else 1.0 - math.exp(-lam * (PRE_S + POST_S) / 60.0)


def coincident(casts: list[dict]) -> np.ndarray:
    """Per cast: another slot's cast lies within COINCIDENT_MS."""
    t = np.array([c["t_ms"] for c in casts], float)
    s = np.array([c["slot"] for c in casts])
    if not len(t):
        return np.zeros(0, bool)
    close = np.abs(t[:, None] - t[None, :]) < COINCIDENT_MS
    return (close & (s[:, None] != s[None, :])).any(1)


def window_peaks(track: np.ndarray, frame: int, fps: int = aa.FPS,
                 record_min: float = RECORD_MIN) -> dict:
    """The window's maximum, its offset (s) and every peak at or above
    `record_min` as (offset s, score), the window clipped to the track."""
    n = len(track)
    lo, hi = max(0, frame - int(PRE_S * fps)), min(n, frame + int(POST_S * fps))
    seg = np.asarray(track[lo:hi], np.float32)
    if not len(seg):
        return {"max": None, "at": None, "peaks": [], "span": [lo, hi]}
    k = int(np.argmax(seg))
    pk, _ = find_peaks(seg, height=record_min, distance=PEAK_GAP)
    return {"max": round(float(seg[k]), 3), "at": round((lo + k - frame) / fps, 2),
            "peaks": [[round((lo + p - frame) / fps, 2), round(float(seg[p]), 3)] for p in pk],
            "span": [round((lo - frame) / fps, 2), round((hi - frame) / fps, 2)]}


def intervening(others, t_ms: float, at: float) -> list[str]:
    """The slots of other casts (slot, t_ms) between the cast at `t_ms` and
    its peak at offset `at` (s), with NEAR_S of margin beyond the peak."""
    out = set()
    for sl, t in others:
        d = (t - t_ms) / 1000.0
        if (at >= 0 and 0 < d <= at + NEAR_S) or (at < 0 and at - NEAR_S <= d < 0):
            out.add(sl)
    return sorted(out)


def largest_cluster(offsets, span: float = STABLE_S) -> tuple[int, list[float]]:
    """The most offsets within `span` of each other, and those offsets."""
    o = np.sort(np.asarray(offsets, float))
    if not len(o):
        return 0, []
    j = np.searchsorted(o, o + span + 1e-9, side="right")
    i = int(np.argmax(j - np.arange(len(o))))
    return int(j[i] - i), o[i:j[i]].tolist()


def propose_phase(stable: bool, med: float | None, role: str | None, ongoing: bool,
                  n_fired: int) -> tuple[str, str]:
    """(phase, evidence) from a stable offset, the repeat of fired peaks and
    the manifest's name role; never a fact."""
    if n_fired == 0:
        return "unknown", "never fires on this slot"
    if not stable:
        return "unknown", f"fires on {n_fired} cast(s) at no stable offset"
    rp = ROLE_PHASE.get(role or "")
    if ongoing:
        return "ongoing", f"repeated fires over >= {ONGOING_S:g} s on >= 2 casts from +{med:.1f} s"
    if med <= CAST_SPAN[1]:
        pre = " (before the drop: equip or windup)" if med < -0.3 else ""
        return "cast", f"stable offset {med:+.2f} s{pre}"
    if rp and rp != "cast":
        return rp, f"stable offset {med:+.2f} s after the drop; name role '{role}'"
    return "unknown", f"stable offset {med:+.2f} s after the drop; the name gives no role"


def slot_stats(fires: list[dict]) -> dict:
    """Per file and slot: fired offsets (non-coincident casts), clusters,
    stability, ongoing; `fires` holds per cast {fired, at, near_other,
    own_fired, own_at, coincident, n_fire_peaks, fire_span}: `at` is the
    window's best peak, `own_at` the best fired peak no other cast precedes
    (`intervening`), the basis of the `_clean` columns."""
    use = [f for f in fires if not f["coincident"]]
    fired = [f for f in use if f["fired"]]
    offs = [f["at"] for f in fired]
    clean = [f["own_at"] for f in use if f["own_fired"]]
    k, cl = largest_cluster(offs)
    kc, clc = largest_cluster(clean)
    stable = k >= 2 and k * 2 >= len(offs)
    stable_c = kc >= 2 and kc * 2 >= len(clean)
    ongoing = sum(1 for f in fired if f["n_fire_peaks"] >= ONGOING_PEAKS
                  and f["fire_span"] >= ONGOING_S) >= 2
    q = np.percentile(offs, [25, 50, 75]) if offs else [np.nan] * 3
    return {"n_casts": len(fires), "n_coincident": len(fires) - len(use), "n_used": len(use),
            "n_fired": len(fired), "hit_rate": round(len(fired) / len(use), 3) if use else None,
            "n_fired_own": len(clean),
            "hit_rate_own": round(len(clean) / len(use), 3) if use else None,
            "offsets_own": [round(o, 2) for o in clean],
            "offsets": [round(o, 2) for o in offs],
            "median_offset": None if not offs else round(float(q[1]), 2),
            "iqr": None if not offs else round(float(q[2] - q[0]), 2),
            "range": None if not offs else round(float(max(offs) - min(offs)), 2),
            "k_in": k, "cluster_median": round(float(np.median(cl)), 2) if cl else None,
            "stable": bool(stable), "k_in_clean": kc,
            "cluster_median_clean": round(float(np.median(clc)), 2) if clc else None,
            "stable_clean": bool(stable_c), "ongoing": bool(ongoing),
            "near_other": sorted({s for f in fired for s in f["near_other"]})}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def agent_rows(store_root, agent: str) -> list[dict]:
    """Every manifest row of `agent`, with a duplicate-content pointer."""
    rows, first = [], {}
    for line in (Path(store_root) / MANIFEST).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("agent") == agent:
                rows.append({"flac": r["flac"], "folder": r.get("folder") or "",
                             "ability": r.get("ability"), "map_basis": r.get("map_basis"),
                             "role": r.get("role"), "codename": r.get("codename"),
                             "events": [e.split("/")[-1] for e in (r.get("events") or [])],
                             "dup_of": first.setdefault(r["sha256"], r["flac"])})
    for r in rows:
        if r["dup_of"] == r["flac"]:
            r["dup_of"] = ""
    return rows


def raw_templates(store_root, flacs: list[str], cache: Path) -> dict[str, np.ndarray | None]:
    """{flac: the owner's raw template (`template(reference_logmel)`) or None
    for a silent clip}, cached in `cache` (keyed by path; the reference set
    is versioned, REF_VERSION)."""
    have: dict[str, np.ndarray | None] = {}
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as z:
            names = list(z["names"])
            lens = z["lens"]
            T = z["T"]
            cuts = np.concatenate([[0], np.cumsum(lens)])
            for n, a, b in zip(names, cuts[:-1], cuts[1:]):
                have[str(n)] = T[a:b] if b > a else None
    todo = [f for f in flacs if f not in have]
    for i, f in enumerate(todo):
        have[f] = aa.template(aa.reference_logmel(Path(store_root) / REF_DIR / f))
        if i % 200 == 0:
            print(f"  decoded {i + 1}/{len(todo)} reference files", flush=True)
    if todo:
        names = sorted(have)
        nb = int(aa.BMASK.sum())
        lens = np.array([0 if have[n] is None else len(have[n]) for n in names], int)
        T = np.concatenate([have[n] for n in names if have[n] is not None]
                           or [np.zeros((0, nb), np.float32)]).astype(np.float32)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp.npz")
        np.savez(tmp, names=np.array(names), lens=lens, T=T)
        os.replace(tmp, cache)
    return have


def pooled_whitener(store_root, version: str) -> dict:
    """The parameter set's pooled whitener (identical for every agent since
    ability-audio-params-0.2.0); refuses a set whose agents differ."""
    prov = json.loads((aa.params_path(store_root, version) / "provenance.json")
                      .read_text(encoding="utf-8"))
    ps = [aa.load_params(store_root, version, a)[0] for a in prov["agents"]]
    for p in ps[1:]:
        if not (np.array_equal(p["mu"], ps[0]["mu"]) and np.array_equal(p["P"], ps[0]["P"])
                and np.array_equal(p["ar"], ps[0]["ar"])):
            raise ValueError(f"{version}: the agents' whiteners differ; no pooled whitener")
    return {"mu": ps[0]["mu"], "P": ps[0]["P"], "ar": ps[0]["ar"], "version": version,
            "check": {a: {"files": p["files"], "templates": p["templates"]}
                      for a, p in zip(prov["agents"], ps)}}


def capture_path(store_root, sid: str) -> str | None:
    p = Path(store_root) / "manifests" / f"{sid}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["source"].get("path")


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------

def build_census(store_root, out: Path, sids=None, xp=np, params_version=None) -> dict:
    from reticle.lineup import abilities_for
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    t0 = time.time()
    store_root = Path(store_root)
    params_version = params_version or ABILITY_AUDIO_PARAMS_VERSION
    demos = demo_census_sessions(store_root)
    if sids:
        demos = {s: a for s, a in demos.items() if s in set(sids)}
    agents = sorted(set(demos.values()))
    rows = {a: agent_rows(store_root, a) for a in agents}
    raw = raw_templates(store_root, sorted({r["flac"] for a in agents for r in rows[a]}),
                        out / f"templates-{REF_VERSION}.npz")
    wh = pooled_whitener(store_root, params_version)
    W = {f: (None if t is None else aa.whiten_template(t, wh["P"], wh["ar"]))
         for f, t in raw.items()}
    # Instrument check: the owner's stored templates for the files it kept.
    diffs = [float(np.abs(W[f] - T).max()) for c in wh["check"].values()
             for f, T in zip((x["flac"] for x in c["files"]), c["templates"])
             if W.get(f) is not None]
    tcheck = {"compared": len(diffs), "max_abs_diff": max(diffs) if diffs else None}
    print(f"templates: {sum(v is not None for v in W.values())} of {len(W)}; "
          f"owner check {tcheck}", flush=True)

    files_of = {a: [r["flac"] for r in rows[a] if W[r["flac"]] is not None] for a in agents}
    pool = {a: [] for a in agents}          # per agent: per demo [files, peaks] heights
    pool_min = Counter()
    same = {a: [] for a in agents}
    same_min = Counter()
    cast_rows = []
    for sid, own in demos.items():
        s = demo_session(store_root, sid)
        Xw = aa.whiten_frames(s["X"], wh["mu"], wh["P"], wh["ar"])
        n = len(Xw)
        all3 = np.full(n, 3, np.int8)
        live_min = float(s["live"].sum()) / (60.0 * aa.FPS)
        bg_min = float(s["bg"].sum()) / (60.0 * aa.FPS)
        truth = demo_truth(store_root, sid)
        coin = coincident(truth)
        for a in agents:
            fl = files_of[a]
            if not fl:
                continue
            tr = aa.class_tracks(Xw, [W[f] for f in fl], fl, s["bg"], xp=xp)
            if a != own:
                pool[a].append([aa.false_fire_peaks(tr[f], s["live"], all3, PEAK_GAP)
                                for f in fl])
                pool_min[a] += live_min
                continue
            same[a].append([aa.false_fire_peaks(tr[f], s["live"], s["code"], PEAK_GAP)
                            for f in fl])
            same_min[a] += bg_min
            for c, co in zip(truth, coin):
                fr = int(c["t_ms"] / 1000.0 * aa.FPS)
                cast_rows.append({"sid": sid, "agent": a, "slot": c["slot"], "key": c["key"],
                                  "t_ms": c["t_ms"], "coincident": bool(co),
                                  "others": [(o["slot"], o["t_ms"]) for o in truth
                                             if abs(o["t_ms"] - c["t_ms"]) >= COINCIDENT_MS],
                                  "files": {f: window_peaks(tr[f], fr) for f in fl},
                                  "tracks": {f: tr[f][max(0, fr - int(PRE_S * aa.FPS)):
                                                       fr + int(POST_S * aa.FPS)]
                                             for f in fl},
                                  "pad": max(0, int(PRE_S * aa.FPS) - fr)})
        print(f"{sid} {own}: {n} frames, {len(truth)} casts, {time.time() - t0:.0f}s", flush=True)

    lam = window_lambda()
    level, nulls = {}, {}
    for a in agents:
        for i, f in enumerate(files_of[a]):
            ph = np.concatenate([d[i] for d in pool[a]]) if pool[a] else np.zeros(0)
            sh = np.concatenate([d[i] for d in same[a]]) if same[a] else np.zeros(0)
            h = aa.threshold_at([ph], pool_min[a], lam)
            level[f] = h
            ls, lp = rate_at(sh, h, same_min[a]), rate_at(ph, h, pool_min[a])
            nulls[f] = {"fire_level": round(h, 3) if h is not None else None,
                        "lam_same_per_min": round(ls, 3), "lam_pool_per_min": round(lp, 3),
                        "null_rate_same": round(window_rate(ls), 3),
                        "null_rate_pool": round(window_rate(lp), 3),
                        "same_min": round(same_min[a], 2), "pool_min": round(pool_min[a], 2)}

    # Per cast and file: fired, the near-other test, the fired peaks' span.
    fires = defaultdict(list)                   # (agent, slot, flac) -> per cast
    for c in cast_rows:
        for f, wp in c["files"].items():
            h = level[f]
            fired = wp["max"] is not None and h is not None and wp["max"] >= h
            at = wp["at"]
            near = intervening(c["others"], c["t_ms"], at) if fired else []
            fp = [p for p in wp["peaks"] if p[1] >= (h if h is not None else np.inf)]
            # The cast's own fire: its highest fired peak with no other cast between.
            own = [p for p in fp if not intervening(c["others"], c["t_ms"], p[0])]
            own_at = max(own, key=lambda p: p[1])[0] if own else None
            wp["fired"] = bool(fired)
            wp["own_at"] = own_at
            fires[(c["agent"], c["slot"], f)].append(
                {"fired": bool(fired), "at": at, "near_other": near, "coincident": c["coincident"],
                 "own_fired": own_at is not None, "own_at": own_at,
                 "n_fire_peaks": len(fp),
                 "fire_span": (fp[-1][0] - fp[0][0]) if len(fp) > 1 else 0.0,
                 "key": c["key"]})

    census, files = [], []
    for a in agents:
        kit = abilities_for(a, str(store_root))
        slots = sorted({c["slot"] for c in cast_rows if c["agent"] == a})
        for r in rows[a]:
            f = r["flac"]
            per_slot = {}
            for sl in slots:
                st = slot_stats(fires.get((a, sl, f), []))
                med = st["cluster_median_clean"] if st["stable_clean"] else st["cluster_median"]
                phase, ev = propose_phase(st["stable_clean"] or st["stable"], med, r["role"],
                                          st["ongoing"], st["n_fired"])
                if st["stable"] and not st["stable_clean"]:
                    ev += f"; another cast intervenes before every stable fire ({', '.join(st['near_other'])})"
                row = {"agent": a, "slot": sl, "ability": kit.get(sl), "file": f,
                       "folder": r["folder"], "manifest_ability": r["ability"],
                       "map_basis": r["map_basis"], "role": r["role"], "dup_of": r["dup_of"],
                       "silent": W.get(f) is None, **{k: v for k, v in st.items()},
                       **nulls.get(f, {}), "phase": phase, "evidence": ev}
                census.append(row)
                per_slot[sl] = row
            stab = [sl for sl, x in per_slot.items() if x["stable_clean"]]
            fired_any = any(x["n_fired"] for x in per_slot.values())
            best = max(per_slot.values(), key=lambda x: (x["stable_clean"], x["stable"],
                                                         x["hit_rate"] or 0), default=None)
            files.append({"agent": a, "file": f, "folder": r["folder"],
                          "manifest_ability": r["ability"], "map_basis": r["map_basis"],
                          "role": r["role"], "dup_of": r["dup_of"], "silent": W.get(f) is None,
                          "stable_slots": stab, "shared": len(stab) >= 2,
                          "never_fires": not fired_any,
                          "best_slot": best["slot"] if best and best["n_fired"] else None,
                          "best_ability": best["ability"] if best and best["n_fired"] else None,
                          "best_phase": best["phase"] if best else "unknown",
                          "best_offset": (best["cluster_median_clean"]
                                          if best["cluster_median_clean"] is not None
                                          else best["cluster_median"])
                          if best and best["n_fired"] else None,
                          "fire_level": nulls.get(f, {}).get("fire_level"),
                          "null_rate_same": nulls.get(f, {}).get("null_rate_same")})

    prov = {"version": VERSION, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "built_by": "prototypes/demo_audio_census.py", "params": params_version,
            "ability_audio_version": __import__("reticle.version", fromlist=["x"]).ABILITY_AUDIO_VERSION,
            "ref_version": REF_VERSION, "features": "analysis/audio-gate/0.1.0/features",
            "demos": {s: {"agent": a, "path": capture_path(store_root, s)} for s, a in demos.items()},
            "rule": {"window_s": [-PRE_S, POST_S], "alpha": ALPHA, "peak_gap_frames": PEAK_GAP,
                     "fires_per_min_at_level": round(lam, 4), "stable_s": STABLE_S,
                     "near_s": NEAR_S, "coincident_ms": COINCIDENT_MS, "cast_span_s": CAST_SPAN,
                     "pooled_null": "every live frame of the demos of other agents",
                     "same_null": "live frames of the agent's own demos unexplained within "
                                  "EXPLAIN_S of any drop or census cast"},
            "template_check": tcheck, "seconds": round(time.time() - t0, 1)}
    return {"census": census, "files": files, "casts": cast_rows, "prov": prov,
            "level": level}


# ---------------------------------------------------------------------------
# Sova
# ---------------------------------------------------------------------------

SPANS = {"cast": (-1.5, 0.7), "post": (0.7, 5.0), "late": (5.0, 15.0)}


def sova_report(res: dict) -> dict:
    """Per Sova bolt cast and file: the best peak in each span, whether it
    fires and which casts intervene before it; per file its own fires (no
    other cast between the bolt and the peak) on each bolt cast; and the
    files whose own fires land on one bolt only (`separating`), with how
    many of the three casts the matcher misread as Recon they cover."""
    level = res["level"]
    bolts = [c for c in res["casts"] if c["agent"] == "Sova" and c["slot"] in ("Q", "E")]
    out = {"casts": [], "files": {}}
    for c in bolts:
        row = {"sid": c["sid"], "slot": c["slot"], "t_s": round(c["t_ms"] / 1000.0, 2),
               "misread_as_recon": any(c["sid"] == s and abs(c["t_ms"] - t) < 100
                                       for s, t in SOVA_MISREAD), "fires": {}}
        for f, wp in c["files"].items():
            for span, (a, b) in SPANS.items():
                pk = [p for p in wp["peaks"] if a <= p[0] < b]
                if not pk:
                    continue
                best = max(pk, key=lambda p: p[1])
                if level[f] is not None and best[1] >= level[f]:
                    iv = intervening(c["others"], c["t_ms"], best[0])
                    row["fires"].setdefault(span, []).append([f, best[0], best[1], iv])
                    d = out["files"].setdefault(f, {"Q": Counter(), "E": Counter()})
                    # A fire counts as the bolt's own only when no other cast intervenes.
                    d[c["slot"]][span if not iv else span + "_after_other"] += 1
        out["casts"].append(row)
    # Own fires (no other cast between the bolt and the peak), per file.
    own = defaultdict(dict)
    for c, r in zip(bolts, out["casts"]):
        lab = f"{c['slot']} {c['sid']} {c['t_ms'] / 1000.0:.2f}"
        for f, wp in c["files"].items():
            if wp.get("own_at") is not None:
                own[f][lab] = wp["own_at"]
    labs = [f"{c['slot']} {c['sid']} {c['t_ms'] / 1000.0:.2f}" for c in bolts]
    mis = [lab for lab, r in zip(labs, out["casts"]) if r["misread_as_recon"]]
    sep = []
    for f, d in own.items():
        q = {k: v for k, v in d.items() if k.startswith("Q ")}
        e = {k: v for k, v in d.items() if k.startswith("E ")}
        if (len(q) >= 2 and not e) or (len(e) >= 2 and not q):
            sep.append({"file": f, "fires_on": "Shock Bolt" if q else "Recon Bolt",
                        "shock_fires": len(q), "of_shock": sum(x.startswith("Q ") for x in labs),
                        "recon_fires": len(e), "of_recon": sum(x.startswith("E ") for x in labs),
                        "on_misread": sum(m in d for m in mis), "of_misread": len(mis),
                        "own_offsets": d})
    out["files"] = {f: {k: dict(v) for k, v in d.items()} for f, d in out["files"].items()}
    out["own_fires"] = {f: d for f, d in sorted(own.items()) if len(d) >= 2}
    out["separating"] = sorted(sep, key=lambda x: (-max(x["shock_fires"], x["recon_fires"]),
                                                   -x["on_misread"], x["file"]))
    return out


# ---------------------------------------------------------------------------
# Contact sheets (display code: nearest-neighbour enlargement only)
# ---------------------------------------------------------------------------

def contact_sheet(res: dict, agent: str, path: Path, max_rows: int = 90) -> int:
    """One PNG per agent: rows are the files that fire on any cast (most
    fires first, cut at `max_rows`), columns the casts, each cell the
    track from -PRE_S to +POST_S over the file's fire level (white >= 1),
    the drop at the red line. Returns the rows drawn."""
    import cv2
    casts = sorted([c for c in res["casts"] if c["agent"] == agent],
                   key=lambda c: (c["slot"], c["sid"], c["t_ms"]))
    if not casts:
        return 0
    level = res["level"]
    nf = Counter()
    for c in casts:
        for f, wp in c["files"].items():
            nf[f] += int(wp.get("fired", False))
    order = sorted([f for f in nf if nf[f]], key=lambda f: (-nf[f], f))[:max_rows]
    L = int((PRE_S + POST_S) * aa.FPS)
    cw, rh, lw, th = 170, 9, 330, 34
    img = np.full((th + rh * max(1, len(order)) + 14, lw + cw * len(casts), 3), 255, np.uint8)
    for j, c in enumerate(casts):
        x0 = lw + j * cw
        lab = f"{c['slot']} {c['sid'][:6]} {c['t_ms'] / 1000:.1f}s" + (" co" if c["coincident"] else "")
        cv2.putText(img, lab, (x0 + 3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 0, 0), 1, cv2.LINE_AA)
        for i, f in enumerate(order):
            t = np.full(L, np.nan, np.float32)
            seg = c["tracks"][f]
            t[c["pad"]:c["pad"] + len(seg)] = seg[:L - c["pad"]]
            # Over the fire level: dark under half of it, white at it and above.
            v = np.clip((np.nan_to_num(t / max(level[f] or 1.0, 1e-3), nan=0.0) - 0.5) / 0.5, 0, 1)
            row = cv2.resize((v * 255).astype(np.uint8)[None, :], (cw - 4, rh - 1),
                             interpolation=cv2.INTER_NEAREST)
            col = cv2.applyColorMap(row, cv2.COLORMAP_INFERNO)
            y = th + i * rh
            img[y:y + rh - 1, x0 + 2:x0 + cw - 2] = col
        xz = x0 + 2 + int(PRE_S * aa.FPS * (cw - 4) / L)
        cv2.line(img, (xz, th - 4), (xz, th + rh * len(order)), (0, 0, 255), 1)
        for _sl, t_o in c["others"]:
            d = (t_o - c["t_ms"]) / 1000.0
            if -PRE_S <= d < POST_S:   # another cast of the demo: a green tick
                xo = x0 + 2 + int((PRE_S + d) * aa.FPS * (cw - 4) / L)
                cv2.line(img, (xo, th - 8), (xo, th - 1), (0, 160, 0), 2)
                cv2.putText(img, _sl, (xo + 2, th - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.28,
                            (0, 120, 0), 1, cv2.LINE_AA)
        for sec in (5, 10):
            xs = x0 + 2 + int((PRE_S + sec) * aa.FPS * (cw - 4) / L)
            cv2.line(img, (xs, th - 3), (xs, th - 1), (0, 0, 0), 1)
        cv2.putText(img, "-2  0    5    10   15s", (x0 + 2, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.3,
                    (80, 80, 80), 1, cv2.LINE_AA)
    for i, f in enumerate(order):
        name = f.split("/", 1)[-1].replace(" (SFX)", "").replace(".flac", "")
        cv2.putText(img, f"{nf[f]} {name[:58]}", (3, th + i * rh + rh - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.27, (0, 0, 0), 1, cv2.LINE_AA)
    nzero = len({f for c in casts for f in c["files"]}) - len([f for f in nf if nf[f]])
    cv2.putText(img, f"{agent}: {len(order)} of {sum(1 for f in nf if nf[f])} firing files shown; "
                     f"{nzero} never fire", (3, img.shape[0] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                (0, 0, 0), 1, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return len(order)


# ---------------------------------------------------------------------------
# Summary and writing
# ---------------------------------------------------------------------------

def summarize(res: dict) -> dict:
    cen, fil = res["census"], res["files"]
    agents = sorted({r["agent"] for r in fil})
    per = {}
    for a in agents:
        cs = [c for c in res["casts"] if c["agent"] == a]
        fa = [f for f in fil if f["agent"] == a]
        per[a] = {"casts": len(cs), "coincident": sum(c["coincident"] for c in cs),
                  "files": len(fa), "silent": sum(f["silent"] for f in fa),
                  "fire_on_any": sum(not f["never_fires"] for f in fa),
                  "stable_offset": sum(bool(f["stable_slots"]) for f in fa),
                  "shared": sum(f["shared"] for f in fa),
                  "phases": dict(Counter(f["best_phase"] for f in fa if f["stable_slots"]))}
    # C1: a mapped file of the slot fires in the cast span on >= half the casts.
    c1 = []
    for (a, sl), rows in _group(cen, ("agent", "slot")).items():
        n = rows[0]["n_used"]
        if n < 2:
            continue
        ab = rows[0]["ability"]
        hit = _cast_span_hits(res, a, sl, ab)
        c1.append({"agent": a, "slot": sl, "n": n, "casts_with_cast_span_fire": hit,
                   "holds": hit * 2 >= n})
    return {"per_agent": per, "files": len(fil),
            "never_fires": sum(f["never_fires"] for f in fil),
            "silent": sum(f["silent"] for f in fil),
            "stable_offset_files": sum(bool(f["stable_slots"]) for f in fil),
            "shared_files": [f["file"] for f in fil if f["shared"]],
            "C1": {"pairs": len(c1), "holds": sum(x["holds"] for x in c1), "rows": c1}}


def _group(rows, keys):
    g = defaultdict(list)
    for r in rows:
        g[tuple(r[k] for k in keys)].append(r)
    return g


def _cast_span_hits(res, agent, slot, ability) -> int:
    """Non-coincident casts of the slot on which some file the manifest maps
    to the slot's ability has its own fire in CAST_SPAN."""
    mapped = {r["file"] for r in res["files"] if r["agent"] == agent
              and r["manifest_ability"] == ability}
    n = 0
    for c in res["casts"]:
        if c["agent"] != agent or c["slot"] != slot or c["coincident"]:
            continue
        n += any(c["files"][f].get("own_at") is not None
                 and CAST_SPAN[0] <= c["files"][f]["own_at"] <= CAST_SPAN[1]
                 for f in mapped if f in c["files"])
    return n


def write(res: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cols = list(res["census"][0].keys())
    with open(out / "census.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in res["census"]:
            w.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()})
    cols = list(res["files"][0].keys())
    with open(out / "files.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in res["files"]:
            w.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()})
    with open(out / "casts.jsonl", "w", encoding="utf-8") as fh:
        for c in res["casts"]:
            fh.write(json.dumps({k: v for k, v in c.items() if k not in ("tracks", "pad")}) + "\n")
    sova = sova_report(res)
    (out / "sova.json").write_text(json.dumps(sova, indent=1), encoding="utf-8")
    summ = summarize(res)
    (out / "summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps(res["prov"], indent=1), encoding="utf-8")
    for a in summ["per_agent"]:
        contact_sheet(res, a, out / "contact" / f"{a.replace('/', '_')}.png")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--out", help="output directory (default <store>/" + OUT.as_posix() + ")")
    ap.add_argument("--sids", nargs="*")
    ap.add_argument("--cpu", action="store_true", help="numpy, not cupy")
    ap.add_argument("--replace", action="store_true",
                    help="rewrite an existing table (a derived table, recomputable)")
    a = ap.parse_args(argv)
    below_normal()
    out = Path(a.out) if a.out else Path(a.store) / OUT
    if (out / "census.csv").exists() and not a.replace:
        print(f"{out / 'census.csv'} exists; pass --replace to rebuild it")
        return 2
    if a.cpu:
        xp = np
    else:
        from reticle.ult_lines import array_module
        xp = array_module()
    res = build_census(a.store, out, a.sids, xp=xp)
    write(res, out)
    print(f"wrote {out} in {res['prov']['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
