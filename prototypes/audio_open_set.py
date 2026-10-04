r"""Ability events from audio alone: an ungated scan of the solo demos.

    .\.venv\Scripts\python.exe prototypes\audio_open_set.py scan [--out DIR]
    .\.venv\Scripts\python.exe prototypes\audio_open_set.py score [--out DIR] [--json OUT]

The wired matcher (`adjudication.ability_audio`, [owns:ability-audio] there)
chooses among the kit's four slots at a tray-gated own cast. This prototype
asks the open-set question instead: with no tray, where in a demo's audio
did the player cast which ability?

**Candidate set.** A solo demo plays one agent, so the candidate set is that
agent's files: every game file the phase map
(`audio-phases-ability-states-gamedata-0.2.0`) assigns to exactly one of the
agent's abilities. A file shared by abilities, played by no ability's data,
or only by a refused or cancelled state witnesses no cast and is left out.
The full set of every agent is the later surprise path.

**Tracks.** The demo's stored log-mel (audio-gate 0.1.0) whitened by the
pooled whitener of `ability-audio-params-0.2.2`; each file's template is
`ability_audio.template` of the game file (cached by the demo audio census,
`analysis/demo-audio-census-20261004/templates-ability-audio-ref-0.2.0.npz`),
whitened the same way; its track the lagged Pearson correlation
(`ability_audio.Corpus`). No tray, no census cast and no gate enters a track.

**Scale.** Each file's track is scaled by its null: the live frames of the
dev demos of other agents, where the file's ability is never cast (a
histogram of HIST_BINS bins over [-1, 1]); 0 is the null's median, 1 its
99.9th percentile. The null uses no label but the demo's agent.

**Detections and events.** A detection is a local maximum of a scaled track
at or above the threshold, at least PEAK_GAP frames from a higher one of the
same file. One ability's detections, in time order, group into events by the
game data's phase order (PHASE_RANK): a detection joins the latest event of
its ability when it falls within JOIN_S of that event's last detection, or
when its phase is later than the event's first and no earlier than its
latest, within LIFE_S of the event's start; else it opens an event. An
event's time is its first detection.

**Threshold families**, each with a threshold on the detections grouped:

* `max` -- every event;
* `cast` -- only an equip, targeting, charge or cast-phase file opens an
  event; later phases only join one;
* `agree` -- an event needs detections of two or more phases;

each over every file (`all`) or with 3P-named files left out (`no3p`): the
player's own casts play the 1P files.

**Scoring** against the demo census (`ability_audio_fit.demo_truth`): an
event matches a census cast of its slot when its time lies within MATCH_S
of the drop; each cast and each event match once, nearest first. An
unmatched event is false. Cast-free audio is the live audio farther than
CASTFREE_S from every census cast and tray drop. Cross-demo false events are
an agent's events on other agents' demos, where it is never cast.

**The split**, declared before any track was computed (predictions
`audio_open_set_ungated_demo_scan`): the demos sorted by id, even positions
dev, odd held. The family and threshold are fixed on dev: the most dev
recall at no more than FF_PER_MIN unmatched events per live minute of the
dev demos' own audio.

`scan` writes the detections (every file of every demo agent on every demo,
at DET_LEVEL and above) with their null scales and provenance to the store's
`analysis/audio-open-set-20261004/`; it decodes no video and no capture
audio, and decodes a game file only where the census cache lacks it. `eval`
reads them and prints and writes the report; it is pure over the stored
detections.

Wire: no. A first measurement; the tray-gated matcher stays the witness.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VERSION = "audio-open-set-0.2.0"
#: The detections' version: `scan` wrote them under 0.1.0.
SCAN_VERSION = "audio-open-set-0.1.0"
#: The event rule `score` applies (see `group_events`).
RULE = VERSION
STORE = Path("C:/Users/grant/reticle-store")
OUT = Path("analysis") / "audio-open-set-20261004"
PHASE_MAP = (Path("reference") / "ability-states"
             / "audio-phases-ability-states-gamedata-0.2.0.jsonl")
TEMPLATE_CACHE = (Path("analysis") / "demo-audio-census-20261004"
                  / "templates-ability-audio-ref-0.2.0.npz")
FEATURES = Path("analysis") / "audio-gate" / "0.1.0" / "features"
#: Detections kept by `scan` (scaled track).
DET_LEVEL = 0.8
#: Two peaks of one file's track closer than this (frames) are one.
PEAK_GAP = 50
#: A detection joins its ability's latest event within this of its last detection (s).
JOIN_S = 2.0
#: A later phase joins an event within this of its start (s).
LIFE_S = 20.0
#: An event matches a cast whose drop lies within this of the event (s, event - drop).
MATCH_S = (-3.0, 3.0)
#: Cast-free audio lies outside this span around every cast and tray drop (s).
CASTFREE_S = (-3.0, 10.0)
#: The dev operating point: unmatched events per live minute of own-demo audio.
FF_PER_MIN = 1.0
#: The null histogram's bins over Pearson [-1, 1].
HIST_BINS = 4000
#: The longest template (frames): `ability_audio.MAX_TEMPLATE_S`.
MAX_LEN = 150
#: The thresholds the families sweep.
THETAS = np.round(np.arange(0.8, 8.01, 0.1), 2)
#: The game data's phase families in their order through an ability's life.
PHASE_RANK = {"equip": 0, "targeting": 1, "charge": 1, "cast": 2, "travel": 3,
              "bounce": 4, "impact": 4, "detonate": 5, "activate": 5, "possess": 5,
              "loop": 6, "recall": 7, "destroyed": 7, "end": 8, "unequip": 8}
#: Phases that open an event in the `cast` family.
OPENING_RANK = 2
#: A file played only by these phases marks no cast.
NOT_A_CAST = {"refused", "cancel"}
FAMILIES = ("max", "cast", "agree")
SUBSETS = ("all", "no3p")
SLOTS = ("C", "Q", "E", "X")


def below_normal() -> None:
    """Below Normal priority for this process (Windows), else nice 10."""
    try:
        if os.name == "nt":
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                    0x4000)
        else:
            os.nice(10)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# The candidate files
# ---------------------------------------------------------------------------

def perspective(row: dict) -> str:
    """'1P', '3P' or 'any': the media name's perspective, else the playing
    states' perspective flags when they all name one side."""
    if row.get("media_name_perspective") in ("1P", "3P"):
        return row["media_name_perspective"]
    flags = {str(s[5]).rstrip("?") for s in row.get("states") or []}
    flags = {"3P" if f.startswith("3P") else f for f in flags}
    if flags == {"1P"}:
        return "1P"
    if flags == {"3P"}:
        return "3P"
    return "any"


def file_phase(phases: list[str]) -> tuple[str, int | None, bool]:
    """(the file's phase label, its rank, whether it may open an event): the
    earliest ranked phase that plays it; 'none' with no rank when no phase
    word names its states."""
    ranked = sorted((PHASE_RANK[p], p) for p in phases if p in PHASE_RANK)
    if not ranked:
        return "none", None, False
    return ranked[0][1], ranked[0][0], ranked[0][0] <= OPENING_RANK


def kit_files(rows: list[dict], agent: str) -> list[dict]:
    """The agent's candidate files, sorted by path: those the phase map
    assigns to exactly one of the agent's C, Q, E, X abilities, less files
    played only by refused or cancelled states."""
    out = []
    for r in rows:
        ab = r.get("abilities") or []
        if len(ab) != 1:
            continue
        a, slot, ability = ab[0].split(":", 2)
        if a != agent or slot not in SLOTS:
            continue
        phases = list(r.get("phases") or [])
        if phases and set(phases) <= NOT_A_CAST:
            continue
        label, rank, opens = file_phase(phases)
        out.append({"flac": r["flac"], "slot": slot, "ability": ability, "phases": phases,
                    "phase": label, "rank": rank, "opens": opens,
                    "perspective": perspective(r)})
    return sorted(out, key=lambda f: f["flac"])


def load_phase_map(store_root) -> list[dict]:
    p = Path(store_root) / PHASE_MAP
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def split_demos(sids) -> dict[str, list[str]]:
    """The declared split: sorted by id, even positions dev, odd held."""
    s = sorted(set(sids))
    return {"dev": s[0::2], "held": s[1::2]}


# ---------------------------------------------------------------------------
# Null scale
# ---------------------------------------------------------------------------

def hist_index(r, xp=np):
    """Bin of each Pearson value in HIST_BINS bins over [-1, 1]."""
    return xp.clip(((r + 1.0) * (HIST_BINS / 2.0)).astype(xp.int64), 0, HIST_BINS - 1)


def hist_quantiles(h: np.ndarray, qs=(0.5, 0.999)) -> np.ndarray:
    """Per row of a histogram stack [F, HIST_BINS], each quantile as its
    bin's centre; NaN for an empty row."""
    h = np.asarray(h, np.float64)
    tot = h.sum(1, keepdims=True)
    cdf = np.cumsum(h, 1) / np.maximum(tot, 1)
    centres = (np.arange(HIST_BINS) + 0.5) * (2.0 / HIST_BINS) - 1.0
    out = np.stack([centres[np.argmax(cdf >= q, axis=1)] for q in qs], 1)
    out[tot[:, 0] == 0] = np.nan
    return out


# ---------------------------------------------------------------------------
# Tracks and detections
# ---------------------------------------------------------------------------

def kit_templates(store_root, flacs: list[str], wh: dict) -> dict:
    """{flac: whitened template or None}: the census cache's raw templates
    (`ability_audio.template`), a game file decoded only when missing."""
    from reticle.adjudication import ability_audio as aa
    from reticle.ability_audio_fit import REF_DIR
    raw = {}
    with np.load(Path(store_root) / TEMPLATE_CACHE, allow_pickle=False) as z:
        cuts = np.concatenate([[0], np.cumsum(z["lens"])])
        T = z["T"]
        for n, a, b in zip(z["names"], cuts[:-1], cuts[1:]):
            raw[str(n)] = T[a:b] if b > a else None
    out = {}
    for f in flacs:
        t = raw[f] if f in raw else aa.template(aa.reference_logmel(Path(store_root) / REF_DIR / f))
        out[f] = None if t is None else aa.whiten_template(t, wh["P"], wh["ar"])
    return out


def pooled_whitener(store_root, version: str) -> dict:
    """The set's pooled whitener; refuses a set whose agents' whiteners differ."""
    from reticle.adjudication import ability_audio as aa
    prov = json.loads((aa.params_path(store_root, version) / "provenance.json")
                      .read_text(encoding="utf-8"))
    ps = [aa.load_params(store_root, version, a)[0] for a in prov["agents"]]
    for p in ps[1:]:
        if not all(np.array_equal(p[k], ps[0][k]) for k in ("mu", "P", "ar")):
            raise ValueError(f"{version}: the agents' whiteners differ")
    return {"mu": ps[0]["mu"], "P": ps[0]["P"], "ar": ps[0]["ar"], "version": version,
            "check": [(f["flac"], t) for p in ps for f, t in zip(p["files"], p["templates"])]}


def raw_tracks(C, Ws: list, xp=np):
    """[F, N] Pearson tracks of the whitened templates on corpus `C`, on
    the device; -1 where a template overruns the end."""
    return xp.stack([C.track(W) for W in Ws])


def peaks(V: np.ndarray, valid: np.ndarray, level: float, gap: int = PEAK_GAP):
    """(file, frame) of each local maximum of each row of V at or above
    `level` on valid frames, no higher value of its row within `gap`."""
    from scipy.ndimage import maximum_filter1d
    Vm = np.where(valid, V, -np.inf).astype(np.float32)
    M = maximum_filter1d(Vm, size=2 * gap + 1, axis=1, mode="constant", cval=-np.inf)
    f, k = np.nonzero((Vm >= level) & (Vm == M))
    if len(f):
        # A plateau keeps its first frame.
        keep = np.ones(len(f), bool)
        keep[1:] = ~((f[1:] == f[:-1]) & (k[1:] - k[:-1] <= gap))
        f, k = f[keep], k[keep]
    return f, k


def scan(store_root, out_dir: Path) -> Path:
    from reticle.ability_audio_fit import demo_census_sessions, demo_session
    from reticle.adjudication import ability_audio as aa
    from reticle.ult_lines import array_module, release_gpu, to_host
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    t0 = time.time()
    xp = array_module()
    store_root = Path(store_root)
    demos = demo_census_sessions(store_root)
    split = split_demos(demos)
    agents = sorted(set(demos.values()))
    rows = load_phase_map(store_root)
    files = {a: kit_files(rows, a) for a in agents}
    wh = pooled_whitener(store_root, ABILITY_AUDIO_PARAMS_VERSION)
    W = kit_templates(store_root, sorted({f["flac"] for a in agents for f in files[a]}), wh)
    # Instrument check: the owner's stored templates for the files both hold.
    diffs = [float(np.abs(W[f] - T).max()) for f, T in wh["check"]
             if W.get(f) is not None and W[f].shape == T.shape]
    tcheck = {"compared": len(diffs), "max_abs_diff": max(diffs) if diffs else None}
    print(f"templates check {tcheck}", flush=True)
    for a in agents:
        files[a] = [f for f in files[a] if W[f["flac"]] is not None]
    sess = {}
    for sid in demos:
        s = demo_session(store_root, sid)
        sess[sid] = {"Xw": aa.whiten_frames(s["X"], wh["mu"], wh["P"], wh["ar"]),
                     "live": s["live"]}

    # Pass 1: each file's null over the dev demos of other agents.
    hist = {a: np.zeros((len(files[a]), HIST_BINS), np.int64) for a in agents}
    null_min = Counter()
    for sid in split["dev"]:
        C = aa.Corpus(sess[sid]["Xw"], MAX_LEN, xp)
        live = xp.asarray(sess[sid]["live"])
        for a in agents:
            if a == demos[sid] or not files[a]:
                continue
            R = raw_tracks(C, [W[f["flac"]] for f in files[a]], xp)
            ok = live[None, :] & (R > -1.0)
            idx = hist_index(R, xp) + xp.arange(len(R))[:, None] * HIST_BINS
            hist[a] += to_host(xp.bincount(idx[ok], minlength=len(R) * HIST_BINS)
                               ).reshape(len(R), HIST_BINS)
            null_min[a] += float(sess[sid]["live"].sum()) / (60.0 * aa.FPS)
        del C
        release_gpu(xp)
        print(f"null {sid} {time.time() - t0:.0f}s", flush=True)
    q = {a: hist_quantiles(hist[a]) for a in agents}

    # Pass 2: detections of every agent's files on every demo.
    det = defaultdict(list)
    for si, sid in enumerate(sorted(demos)):
        C = aa.Corpus(sess[sid]["Xw"], MAX_LEN, xp)
        live = sess[sid]["live"]
        for ai, a in enumerate(agents):
            if not files[a]:
                continue
            R = to_host(raw_tracks(C, [W[f["flac"]] for f in files[a]], xp))
            q50, q999 = q[a][:, :1], q[a][:, 1:]
            V = (R - q50) / np.maximum(q999 - q50, 1e-3)
            f, k = peaks(V, live[None, :] & (R > -1.0), DET_LEVEL)
            det["sid"].append(np.full(len(f), si, np.int16))
            det["agent"].append(np.full(len(f), ai, np.int16))
            det["fidx"].append(f.astype(np.int32))
            det["frame"].append(k.astype(np.int32))
            det["v"].append(V[f, k].astype(np.float32))
        del C
        release_gpu(xp)
        print(f"detect {sid} {time.time() - t0:.0f}s", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / "detections.npz",
                        **{k: np.concatenate(v) for k, v in det.items()},
                        **{f"q__{a.replace('/', '_')}": q[a] for a in agents})
    from reticle.ability_audio_fit import demo_truth
    meta = {"version": SCAN_VERSION, "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "built_by": "prototypes/audio_open_set.py scan",
            "params": ABILITY_AUDIO_PARAMS_VERSION, "phase_map": PHASE_MAP.as_posix(),
            "templates": TEMPLATE_CACHE.as_posix(), "template_check": tcheck,
            "features": FEATURES.as_posix(), "device": xp.__name__,
            "rule": {"det_level": DET_LEVEL, "peak_gap": PEAK_GAP, "hist_bins": HIST_BINS,
                     "null": "live frames of the dev demos of other agents"},
            "split": split, "agents": agents, "sids": sorted(demos),
            "demos": {sid: {"agent": demos[sid],
                            "path": json.loads((store_root / "manifests" / f"{sid}.json")
                                               .read_text(encoding="utf-8"))["source"].get("path"),
                            "n": int(len(sess[sid]["live"])),
                            "live_min": float(sess[sid]["live"].sum()) / (60.0 * aa.FPS)}
                      for sid in sorted(demos)},
            "null_min": dict(null_min),
            "files": files, "seconds": round(time.time() - t0, 1),
            "truth_rows": {sid: len(demo_truth(store_root, sid)) for sid in demos}}
    (out_dir / "provenance.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return out_dir


# ---------------------------------------------------------------------------
# Events and scores (pure)
# ---------------------------------------------------------------------------

def group_events(dets: list[tuple[int, int, float]], files: list[dict], family: str,
                 fps: int = 100, rule: str = RULE) -> list[dict]:
    """Events of one agent on one demo from detections (file index, frame,
    scaled value) already thresholded and subset. Per ability, in time
    order, a detection joins the latest event (JOIN_S, or a later phase
    within LIFE_S) or opens one; `cast` lets only opening files open,
    `agree` keeps events with two or more phases.

    Rule 0.1.0 dates every event at its first detection, state `cast`.
    Rule 0.2.0 dates it at its first cast-or-later (or unphased)
    detection; an event of equip, targeting and charge detections alone
    is an `equip` state event, dated at its first detection."""
    by_slot = defaultdict(list)
    for d in sorted(dets, key=lambda d: (d[1], d[0])):
        by_slot[files[d[0]]["slot"]].append(d)
    events = []
    for slot, ds in by_slot.items():
        cur = None
        for fi, k, v in ds:
            meta = files[fi]
            r = meta["rank"]
            joins = cur is not None and (
                k - cur["last"] <= JOIN_S * fps
                or (r is not None and cur["open_rank"] is not None and r > cur["open_rank"]
                    and r >= cur["max_rank"] and k - cur["t"] <= LIFE_S * fps))
            if joins:
                cur["dets"].append((fi, k, v))
                cur["last"] = k
                if r is not None:
                    cur["max_rank"] = max(cur["max_rank"], r)
                continue
            if family == "cast" and not meta["opens"]:
                continue
            cur = {"slot": slot, "t": k, "last": k, "open_rank": r,
                   "max_rank": r if r is not None else -1, "dets": [(fi, k, v)]}
            events.append(cur)
    out = []
    for e in events:
        ph = Counter()
        best = max(e["dets"], key=lambda d: d[2])
        for fi, _k, _v in e["dets"]:
            ph[files[fi]["phase"]] += 1
        if family == "agree" and len(ph) < 2:
            continue
        later = [k for fi, k, _v in e["dets"]
                 if files[fi]["rank"] is None or files[fi]["rank"] >= OPENING_RANK]
        if rule == "audio-open-set-0.1.0":
            state, t = "cast", e["t"]
        else:
            state, t = ("cast", min(later)) if later else ("equip", e["t"])
        out.append({"slot": e["slot"], "frame": t, "state": state, "score": float(best[2]),
                    "best_phase": files[best[0]]["phase"],
                    "best_perspective": files[best[0]]["perspective"],
                    "phases": dict(ph), "n": len(e["dets"])})
    return sorted(out, key=lambda e: e["frame"])


def match(events: list[dict], casts: list[dict], fps: int = 100,
          window=MATCH_S) -> list[tuple[int, int, float]]:
    """(event index, cast index, event - drop in s) pairs: same slot,
    inside `window`, nearest first, each once."""
    pairs = []
    for i, e in enumerate(events):
        for j, c in enumerate(casts):
            if e["slot"] != c["slot"]:
                continue
            dt = (e["frame"] - c["frame"]) / fps
            if window[0] <= dt <= window[1]:
                pairs.append((abs(dt), i, j, dt))
    used_e, used_c, out = set(), set(), []
    for _a, i, j, dt in sorted(pairs):
        if i in used_e or j in used_c:
            continue
        used_e.add(i)
        used_c.add(j)
        out.append((i, j, dt))
    return out


def castfree_mask(n: int, live: np.ndarray, times_s, fps: int = 100,
                  span=CASTFREE_S) -> np.ndarray:
    """Live frames outside `span` around every time given."""
    m = np.asarray(live, bool).copy()
    for t in times_s:
        a = max(int((t + span[0]) * fps), 0)
        b = min(int((t + span[1]) * fps), n)
        if b > a:
            m[a:b] = False
    return m


def keep_file(f: dict, subset: str) -> bool:
    return subset == "all" or (subset == "no3p" and f["perspective"] != "3P") or \
        (subset == "3p" and f["perspective"] == "3P") or \
        (subset == "opening" and f["opens"]) or (subset == "later" and not f["opens"])


def evaluate(D: dict, truth: dict, family: str, subset: str, theta: float,
             sids: list[str], cross: bool = True, rule: str = RULE) -> dict:
    """Scores of one family, subset and threshold over `sids`. `D` holds
    per (agent, sid) the detection list, the files, and per sid its live
    mask, agent and tray drops; `truth` per sid the census casts."""
    rows = {}
    for sid in sids:
        a = D["agent_of"][sid]
        files = D["files"][a]
        dets = [d for d in D["dets"].get((a, sid), [])
                if d[2] >= theta and keep_file(files[d[0]], subset)]
        ev_all = group_events(dets, files, family, rule=rule)
        ev = [e for e in ev_all if e["state"] == "cast"]
        eq = [e for e in ev_all if e["state"] == "equip"]
        casts = truth[sid]
        m = match(ev, casts)
        matched_e = {i for i, _j, _dt in m}
        live = D["live"][sid]
        cf = castfree_mask(len(live), live, [c["frame"] / 100.0 for c in casts]
                           + [f / 100.0 for f in D["drops"][sid]])
        false = [e for i, e in enumerate(ev) if i not in matched_e]
        rows[sid] = {"agent": a, "casts": len(casts), "hit": len(m),
                     "hits": [(casts[j]["slot"], dt, ev[i]["best_phase"], ev[i]["best_perspective"])
                              for i, j, dt in m],
                     "miss_slots": [casts[j]["slot"] for j in range(len(casts))
                                    if j not in {jj for _i, jj, _dt in m}],
                     "slots": [c["slot"] for c in casts],
                     "equip": len(eq),
                     "equip_then_cast": sum(any(c["slot"] == e["slot"] and 0 <= c["frame"] - e["frame"] <= 1000
                                                for c in casts) for e in eq),
                     "false": len(false), "false_castfree": sum(bool(cf[min(e["frame"], len(cf) - 1)])
                                                              for e in false),
                     "live_min": float(live.sum()) / 6000.0, "castfree_min": float(cf.sum()) / 6000.0}
        if cross and a not in {rr["agent"] for s2, rr in rows.items() if s2 != sid}:
            # Once per agent: its detector over every other agent's demo in `sids`.
            n_x, min_x = 0, 0.0
            for other in sids:
                if D["agent_of"][other] == a:
                    continue
                dx = [d for d in D["dets"].get((a, other), [])
                      if d[2] >= theta and keep_file(files[d[0]], subset)]
                n_x += sum(e["state"] == "cast" for e in group_events(dx, files, family, rule=rule))
                min_x += float(D["live"][other].sum()) / 6000.0
            rows[sid].update(cross_false=n_x, cross_min=min_x)
        elif cross:
            rows[sid].update(cross_false=0, cross_min=0.0)
    return rows


def pooled(rows: dict) -> dict:
    r = list(rows.values())
    s = lambda k: sum(x[k] for x in r)  # noqa: E731
    out = {"casts": s("casts"), "hit": s("hit"),
           "recall": s("hit") / max(s("casts"), 1),
           "false": s("false"), "live_min": s("live_min"),
           "false_per_min": s("false") / max(s("live_min"), 1e-9),
           "false_castfree": s("false_castfree"), "castfree_min": s("castfree_min"),
           "false_castfree_per_min": s("false_castfree") / max(s("castfree_min"), 1e-9),
           "equip": s("equip"), "equip_then_cast": s("equip_then_cast")}
    if r and "cross_false" in r[0]:
        out.update(cross_false=s("cross_false"), cross_min=s("cross_min"),
                   cross_per_min=s("cross_false") / max(s("cross_min"), 1e-9))
    dts = [abs(h[1]) for x in r for h in x["hits"]]
    out["abs_dt_median"] = float(np.median(dts)) if dts else None
    out["dt_median"] = float(np.median([h[1] for x in r for h in x["hits"]])) if dts else None
    return out


def choose(D, truth, sids, ff=FF_PER_MIN, rule: str = RULE) -> tuple[dict, list[dict]]:
    """The dev choice: per family and subset the least threshold whose
    unmatched events per live minute are at most `ff`; then the most recall,
    ties to the fewer false events."""
    table = []
    for fam in FAMILIES:
        for sub in SUBSETS:
            for th in THETAS:
                p = pooled(evaluate(D, truth, fam, sub, float(th), sids, cross=False, rule=rule))
                if p["false_per_min"] <= ff:
                    table.append({"family": fam, "subset": sub, "theta": float(th), **p})
                    break
    best = max(table, key=lambda r: (r["recall"], -r["false_per_min"]))
    return best, table


def load(out_dir: Path, store_root) -> tuple[dict, dict, dict]:
    from reticle.ability_audio_fit import demo_truth
    meta = json.loads((out_dir / "provenance.json").read_text(encoding="utf-8"))
    z = np.load(out_dir / "detections.npz")
    sids, agents = meta["sids"], meta["agents"]
    dets = defaultdict(list)
    for si, ai, f, k, v in zip(z["sid"], z["agent"], z["fidx"], z["frame"], z["v"]):
        dets[(agents[ai], sids[si])].append((int(f), int(k), float(v)))
    live, drops = {}, {}
    for sid in sids:
        with np.load(Path(store_root) / FEATURES / f"{sid}.npz", allow_pickle=True) as fz:
            live[sid] = fz["ok"][:meta["demos"][sid]["n"]].astype(bool)
        dr = [json.loads(x) for x in (Path(store_root) / "events" / "tray_drop" / f"{sid}.jsonl")
              .read_text(encoding="utf-8").splitlines() if x.strip()]
        drops[sid] = [int(r["t_ms"] / 10.0) for r in dr if r.get("kind") == "drop"]
    D = {"dets": dets, "files": meta["files"], "live": live, "drops": drops,
         "agent_of": {sid: meta["demos"][sid]["agent"] for sid in sids}}
    truth = {sid: [{"slot": t["slot"], "frame": int(t["t_ms"] / 10.0)}
                   for t in demo_truth(store_root, sid)] for sid in sids}
    return D, truth, meta


def report(out_dir: Path, store_root, rule: str = RULE) -> dict:
    D, truth, meta = load(out_dir, store_root)
    dev, held = meta["split"]["dev"], meta["split"]["held"]
    best, table = choose(D, truth, dev, rule=rule)
    fam, sub, th = best["family"], best["subset"], best["theta"]
    H = evaluate(D, truth, fam, sub, th, held, rule=rule)
    Dv = evaluate(D, truth, fam, sub, th, dev, rule=rule)
    per_agent = defaultdict(dict)
    for sid, r in H.items():
        a = per_agent[r["agent"]]
        for k in ("casts", "hit", "false", "live_min", "false_castfree", "castfree_min",
                  "cross_false", "cross_min"):
            a[k] = a.get(k, 0) + r[k]
        a.setdefault("dts", []).extend(round(h[1], 2) for h in r["hits"])
        a.setdefault("sessions", []).append({"sid": sid, "path": meta["demos"][sid]["path"]})
    for a in per_agent.values():
        a["recall"] = a["hit"] / max(a["casts"], 1)
        a["false_per_min"] = a["false"] / max(a["live_min"], 1e-9)
        a["cross_per_min"] = a["cross_false"] / max(a["cross_min"], 1e-9)
    slot = {s: {"casts": sum(r["slots"].count(s) for r in H.values()),
                "hit": sum(1 for r in H.values() for h in r["hits"] if h[0] == s)} for s in SLOTS}
    decide = Counter(h[2] for r in H.values() for h in r["hits"])
    decide_p = Counter(h[3] for r in H.values() for h in r["hits"])
    # Ablations at the chosen family and threshold.
    abl = {}
    for s2 in ("all", "no3p", "3p", "opening", "later"):
        abl[s2] = {"dev": pooled(evaluate(D, truth, fam, s2, th, dev, cross=False, rule=rule)),
                   "held": pooled(evaluate(D, truth, fam, s2, th, held, cross=False, rule=rule))}
    # The dev-fixed operating point of every family, scored on held.
    held_of = []
    for r in table:
        p = pooled(evaluate(D, truth, r["family"], r["subset"], r["theta"], held, rule=rule))
        held_of.append({"family": r["family"], "subset": r["subset"], "theta": r["theta"],
                        "dev_recall": r["recall"], "dev_false_per_min": r["false_per_min"],
                        "held_recall": p["recall"], "held_false_per_min": p["false_per_min"],
                        "held_cross_per_min": p["cross_per_min"]})
    rep = {"version": rule, "detections": meta["version"], "detections_built": meta["built_at"],
           "choice": best,
           "dev_table": table, "families_on_held": held_of,
           "dev": pooled(Dv), "held": pooled(H), "held_per_agent": dict(per_agent),
           "held_per_slot": slot, "held_decided_by_phase": dict(decide),
           "held_decided_by_perspective": dict(decide_p), "ablations": abl,
           "rule": {"match_s": MATCH_S, "castfree_s": CASTFREE_S, "join_s": JOIN_S,
                    "life_s": LIFE_S, "ff_per_min": FF_PER_MIN}}
    return rep


def print_report(rep: dict) -> None:
    c = rep["choice"]
    print(f"dev choice: family {c['family']} subset {c['subset']} theta {c['theta']} "
          f"dev recall {c['hit']}/{c['casts']} false/min {c['false_per_min']:.2f}")
    print("family subset theta | dev recall false/min | held recall false/min cross/min")
    for r in rep["families_on_held"]:
        print(f"{r['family']:5} {r['subset']:4} {r['theta']:.1f} | {r['dev_recall']:.2f} "
              f"{r['dev_false_per_min']:.2f} | {r['held_recall']:.2f} {r['held_false_per_min']:.2f} "
              f"{r['held_cross_per_min']:.2f}")
    h = rep["held"]
    print(f"held: recall {h['hit']}/{h['casts']} ({h['recall']:.2f}); false {h['false']} in "
          f"{h['live_min']:.1f} min ({h['false_per_min']:.2f}/min); cast-free false "
          f"{h['false_castfree']} in {h['castfree_min']:.1f} min "
          f"({h['false_castfree_per_min']:.2f}/min); cross-demo {h['cross_false']} in "
          f"{h['cross_min']:.1f} min ({h['cross_per_min']:.2f}/min); |dt| median "
          f"{h['abs_dt_median']}, dt median {h['dt_median']}; equip state events {h['equip']}, "
          f"{h['equip_then_cast']} followed by a same-slot cast within 10 s")
    print("agent | recall | false/min | cast-free false/min | cross/min | dt (s)")
    for a, r in sorted(rep["held_per_agent"].items()):
        cf = r["false_castfree"] / r["castfree_min"] if r["castfree_min"] > 0 else float("nan")
        print(f"{a:9} {r['hit']}/{r['casts']} {r['false_per_min']:.2f} {cf:.2f} "
              f"({r['false_castfree']} in {r['castfree_min']:.2f} min) "
              f"{r['cross_per_min']:.2f} {r['dts']}")
    print("held per slot", rep["held_per_slot"])
    print("held decided by phase", rep["held_decided_by_phase"])
    print("held decided by perspective", rep["held_decided_by_perspective"])
    for k, v in rep["ablations"].items():
        print(f"ablation {k:7}: dev {v['dev']['hit']}/{v['dev']['casts']} "
              f"{v['dev']['false_per_min']:.2f}/min | held {v['held']['hit']}/{v['held']['casts']} "
              f"{v['held']['false_per_min']:.2f}/min")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("scan", "score"))
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--rule", default=RULE, choices=("audio-open-set-0.1.0", "audio-open-set-0.2.0"))
    a = ap.parse_args(argv)
    below_normal()
    out = Path(a.out) if a.out else Path(a.store) / OUT
    if a.cmd == "scan":
        print(scan(a.store, out))
        return 0
    rep = report(out, a.store, a.rule)
    print_report(rep)
    js = Path(a.json) if a.json else out / f"report-{a.rule}.json"
    js.write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print(js)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
