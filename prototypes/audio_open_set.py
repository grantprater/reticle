r"""Ability events from audio alone: an ungated scan of the solo demos, frozen
on dev demos and tested once on the player's matches.

    .\.venv\Scripts\python.exe prototypes\audio_open_set.py scan
    .\.venv\Scripts\python.exe prototypes\audio_open_set.py score --scan DIR
    .\.venv\Scripts\python.exe prototypes\audio_open_set.py match-scan --score DIR
    .\.venv\Scripts\python.exe prototypes\audio_open_set.py match-score --match DIR

The wired matcher (`adjudication.ability_audio`, [owns:ability-audio] there)
chooses among the kit's four slots at a tray-gated own cast. This prototype
asks the open-set question instead: with no tray, where in the audio did the
player cast which ability?

**Candidate set.** A solo demo plays one agent; a match's player plays the
agent the identity arbiter names from the stored lineup
(`ability_audio_fit.gate_snapshot`, `player_agent_verdict`). The candidate
set is that agent's files: every game file the phase map
(`audio-phases-ability-states-gamedata-0.2.0`) assigns to exactly one of the
agent's abilities. A file shared by abilities, played by no ability's data,
or only by a refused or cancelled state witnesses no cast and is left out.
The full set of every agent is the later surprise path.

**Tracks.** The stored log-mel (audio-gate 0.1.0) whitened by the pooled
whitener of the current parameter set (`ABILITY_AUDIO_PARAMS_VERSION`); each
file's template is `ability_audio.template` of the game file (cached by the
demo audio census), whitened the same way; its track the lagged Pearson
correlation (`ability_audio.Corpus`). No tray, no census cast and no gate
enters a track.

**Scale.** Each file's track is scaled by its null: the live frames of the
dev demos of other agents (a histogram of HIST_BINS bins over [-1, 1]); 0 is
the null's median, 1 its 99.9th percentile. A match scan reuses the demo
scan's null.

**Detections and events** (rule EVENT_RULE). A detection is a local maximum
of a scaled track at or above the threshold, at least PEAK_GAP frames from a
higher one of the same file. One ability's detections, in time order, form
chains: consecutive detections at most JOIN_S apart. A chain's rank is its
detections' earliest phase (PHASE_RANK). An anchor is a chain of rank
OPENING_RANK or earlier (equip, targeting, charge, cast). A ranked chain
attaches to the latest earlier anchor of its ability with a lower rank that
started at most LIFE_S before it; attachments resolve to their first anchor,
and each root chain with its attached chains is one event. An event's time
is its first cast-or-later (or unphased) detection; an event of equip,
targeting and charge detections alone is an `equip` state event, reported
apart and never scored as a cast.

**Threshold families**, each with a threshold on the detections grouped:

* `max` -- every event;
* `cast` -- events holding an equip, targeting, charge or cast-phase
  detection;
* `agree` -- events holding detections of two or more distinct phases (the
  threshold applies to every detection before grouping);

each over every file (`all`) or with 3P-named files left out (`no3p`).
`seq-dev` tests a fourth on dev demos only, outside the choice: `seq`, each
ability's own sequence, an opening detection and, where the ability's game
data plays any file of a later phase (travel, bounce, impact, detonate,
activate, loop, ...), a detection of one.

**Scoring.** An event matches a cast of its slot when its time lies within
MATCH_S of the drop; events and casts pair one to one by
`scipy.optimize.linear_sum_assignment`, the most pairs first, then the least
total |event - drop|. An unmatched cast event is false. Cast-free audio is
the live audio farther than CASTFREE_S from every cast and tray drop.
Cross-demo false events are an agent's events on other agents' demos.

**Demo truth** (rule TRUTH_RULE, stated before the 0.3.0 rescore): a census
cast (`labels/demo_cast_class`) counts only when the tray and HUD say it was
one. Its tray drop is left out when the menu witness covers it (`reason`
`menu_open`) or another slot's tray drop lies within COINCIDENT_MS of it
(several slots at one sample instant: a menu, a reset or a shared pool, where
the tray cannot say which slot was cast; the census's own `coincident`
rule). Left-out drops are no casts: an event near one is false, and they
still bound cast-free audio.

**Match truth.** The gate's player casts (`ability_timeline.player_tray_casts`
through `ability_audio_fit.gate_snapshot`) on live frames of
`ability_audio_fit.match_session`: the tray channel, not audio.

**The demo split**, declared before any track was computed (predictions
`audio_open_set_ungated_demo_scan`): the demos sorted by id, even positions
dev, odd held. The held demos were seen under rules 0.1.0 and 0.2.0 before
later rules, so they are no clean test. The family and threshold are fixed on
dev: the most dev recall at no more than FF_PER_MIN unmatched events per
live minute. The clean test is the matches, scored once by `match-score`.

**Outputs.** Every command writes a new directory under the store's
`analysis/audio-open-set/` named by its versions and refuses an existing one;
`score` and `match-score` refuse detections whose parameter set is not the
current one.

Wire: no. A measurement; the tray-gated matcher stays the witness.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: The detections' version. 0.1.0 (analysis/audio-open-set-20261004) read
#: ability-audio-params-0.2.2; 0.2.0 stamps and checks the current set.
SCAN_VERSION = "audio-open-set-scan-0.2.0"
#: The event and scoring rule. 0.1.0 dated an event at its first detection;
#: 0.2.0 at its first cast-or-later detection; 0.3.0 groups by chains and
#: anchors (vectorised), pairs events and casts by assignment, and scores
#: against TRUTH_RULE.
RULE = "audio-open-set-0.3.0"
EVENT_RULE = RULE
TRUTH_RULE = "demo-truth-tray-only-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
OUT_ROOT = Path("analysis") / "audio-open-set"
PHASE_MAP = (Path("reference") / "ability-states"
             / "audio-phases-ability-states-gamedata-0.2.0.jsonl")
TEMPLATE_CACHE = (Path("analysis") / "demo-audio-census-20261004"
                  / "templates-ability-audio-ref-0.2.0.npz")
FEATURES = Path("analysis") / "audio-gate" / "0.1.0" / "features"
#: Detections kept by `scan` (scaled track).
DET_LEVEL = 0.8
#: Two peaks of one file's track closer than this (frames) are one.
PEAK_GAP = 50
#: Consecutive detections of one ability within this (s) form a chain.
JOIN_S = 2.0
#: A later-phase chain attaches to an anchor that started within this (s).
LIFE_S = 20.0
#: An event matches a cast whose drop lies within this of the event (s, event - drop).
MATCH_S = (-3.0, 3.0)
#: Cast-free audio lies outside this span around every cast and tray drop (s).
CASTFREE_S = (-3.0, 10.0)
#: Two tray drops of different slots closer than this (ms) share an instant
#: (`demo_audio_census.COINCIDENT_MS`).
COINCIDENT_MS = 50.0
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
#: Anchors and `cast`-family events need a phase this early or earlier.
OPENING_RANK = 2
#: A file played only by these phases marks no cast.
NOT_A_CAST = {"refused", "cancel"}
FAMILIES = ("max", "cast", "agree")
SUBSETS = ("all", "no3p")
SLOTS = ("C", "Q", "E", "X")
FPS = 100
#: The rank of an unphased detection: never an anchor, never attaches.
UNRANKED = 99


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


def new_dir(path: Path) -> Path:
    """Create `path`; refuse one that exists, so no run overwrites another."""
    path = Path(path)
    if path.exists():
        raise SystemExit(f"{path} exists: refusing to overwrite; pass a new --out")
    path.mkdir(parents=True)
    return path


def new_file(path: Path, text: str) -> Path:
    """Write `text` to a file that does not exist yet."""
    path = Path(path)
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(text)
    return path


def check_params(meta: dict, current: str | None = None) -> None:
    """Refuse detections built under another parameter set than the current one."""
    if current is None:
        from reticle.version import ABILITY_AUDIO_PARAMS_VERSION as current
    if meta.get("params") != current:
        raise SystemExit(f"detections read {meta.get('params')}, the current set is {current}: "
                         f"rescan")


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
    """(the file's phase label, its rank, whether it is an opening phase):
    the earliest ranked phase that plays it; 'none' with no rank when no
    phase word names its states."""
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


def file_table(files: dict[str, list[dict]], agents: list[str]) -> dict:
    """Per agent and file, flattened over `agents` in order: the arrays the
    vectorised rule reads, and each agent's offset."""
    rows = [f for a in agents for f in files.get(a, [])]
    off = np.cumsum([0] + [len(files.get(a, [])) for a in agents])
    phases = sorted({f["phase"] for f in rows}) or ["none"]
    persp = np.array([f["perspective"] for f in rows], dtype=object)
    opens = np.array([bool(f["opens"]) for f in rows], bool)
    slot = np.array([SLOTS.index(f["slot"]) for f in rows], np.int64)
    rank = np.array([UNRANKED if f["rank"] is None else f["rank"] for f in rows], np.int64)
    keep = {"all": np.ones(len(rows), bool), "no3p": persp != "3P",
            "3p": persp == "3P", "opening": opens, "later": ~opens}
    # Per subset and file: whether the file's ability (agent and slot) keeps
    # any file of a phase later than OPENING_RANK.
    ability = np.repeat(np.arange(len(agents)), np.diff(off)) * len(SLOTS) + slot
    later = (rank > OPENING_RANK) & (rank < UNRANKED)
    need = {k: (np.bincount(ability, weights=(m & later).astype(float),
                            minlength=len(agents) * len(SLOTS)) > 0)[ability]
            for k, m in keep.items()}
    return {"off": off[:-1], "n": off[-1], "slot": slot, "rank": rank,
            "opens": opens, "phase_names": phases,
            "phase": np.array([phases.index(f["phase"]) for f in rows], np.int64),
            "perspective": persp, "keep": keep, "need_later": need}


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
    from reticle.ability_audio_fit import REF_DIR
    from reticle.adjudication import ability_audio as aa
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


def kit_setup(store_root, agents: list[str]) -> tuple[dict, dict, dict, dict]:
    """(files per agent, whitened templates, whitener, template check)."""
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
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
    return files, W, wh, tcheck


def detect(C, live: np.ndarray, Ws: list, q: np.ndarray, xp) -> tuple:
    """(file index, frame, scaled value) of the detections of one kit on one corpus."""
    from reticle.ult_lines import to_host
    R = to_host(raw_tracks(C, Ws, xp))
    q50, q999 = q[:, :1], q[:, 1:]
    V = (R - q50) / np.maximum(q999 - q50, 1e-3)
    f, k = peaks(V, live[None, :] & (R > -1.0), DET_LEVEL)
    return f.astype(np.int32), k.astype(np.int32), V[f, k].astype(np.float32)


def scan(store_root, out_dir: Path | None = None) -> Path:
    from reticle.ability_audio_fit import demo_census_sessions, demo_session
    from reticle.adjudication import ability_audio as aa
    from reticle.ult_lines import array_module, release_gpu, to_host
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    t0 = time.time()
    store_root = Path(store_root)
    out_dir = new_dir(out_dir or store_root / OUT_ROOT / (
        f"{SCAN_VERSION}_{ABILITY_AUDIO_PARAMS_VERSION}"))
    xp = array_module()
    demos = demo_census_sessions(store_root)
    split = split_demos(demos)
    agents = sorted(set(demos.values()))
    files, W, wh, tcheck = kit_setup(store_root, agents)
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
    det = {k: [] for k in ("sid", "agent", "fidx", "frame", "v")}
    for si, sid in enumerate(sorted(demos)):
        C = aa.Corpus(sess[sid]["Xw"], MAX_LEN, xp)
        for ai, a in enumerate(agents):
            if not files[a]:
                continue
            f, k, v = detect(C, sess[sid]["live"], [W[x["flac"]] for x in files[a]], q[a], xp)
            det["sid"].append(np.full(len(f), si, np.int16))
            det["agent"].append(np.full(len(f), ai, np.int16))
            det["fidx"].append(f)
            det["frame"].append(k)
            det["v"].append(v)
        del C
        release_gpu(xp)
        print(f"detect {sid} {time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(out_dir / "detections.npz",
                        **{k: np.concatenate(v) for k, v in det.items()},
                        **{f"q__{a.replace('/', '_')}": q[a] for a in agents})
    from reticle.ability_audio_fit import demo_truth
    meta = {"version": SCAN_VERSION, "kind": "demos",
            "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
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
    new_file(out_dir / "provenance.json", json.dumps(meta, indent=1))
    return out_dir


# ---------------------------------------------------------------------------
# Events and scores (pure, vectorised)
# ---------------------------------------------------------------------------

EMPTY_EVENTS = {k: np.zeros(0, t) for k, t in (
    ("key", np.int64), ("slot", np.int64), ("frame", np.int64), ("cast", bool),
    ("score", np.float64), ("best", np.int64), ("nphase", np.int64), ("n", np.int64))}


def _block_first(keys: np.ndarray) -> np.ndarray:
    """Start index of each run of equal values in a sorted array."""
    return np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])


def group_events(key, slot, frame, rank, opens, phase, v, family: str, fps: int = FPS,
                 rule: str = RULE, tie=None, need_later=None) -> dict:
    """Events from detections already thresholded and subset, as arrays.

    Every argument but `family` is one value per detection: `key` the
    group (a session, or a session and agent), `slot` 0-3, `rank` the
    file's phase rank (UNRANKED for none), `opens` whether the file's phase
    is OPENING_RANK or earlier, `phase` the phase id, `v` the scaled score;
    `tie` orders detections of one frame (the file index); `need_later`,
    for the `seq` family, whether the detection's ability plays any file of
    a phase later than OPENING_RANK in the game data. Returns per
    event its key, slot, frame, `cast` (False: an equip state event), best
    score, the index of its best detection, distinct phases and detection
    count, sorted by key and frame. The rule is the module docstring's."""
    key, slot, frame = (np.asarray(a, np.int64) for a in (key, slot, frame))
    rank, phase = np.asarray(rank, np.int64), np.asarray(phase, np.int64)
    opens, v = np.asarray(opens, bool), np.asarray(v, np.float64)
    n = len(frame)
    if n == 0:
        return {k: a.copy() for k, a in EMPTY_EVENTS.items()}
    tie = np.zeros(n, np.int64) if tie is None else np.asarray(tie, np.int64)
    gs = key * len(SLOTS) + slot
    o = np.lexsort((tie, frame, gs))
    gs_o, fr_o, rk_o = gs[o], frame[o], rank[o]
    # Chains.
    start = np.r_[True, (gs_o[1:] != gs_o[:-1]) | (np.diff(fr_o) > JOIN_S * fps)]
    chain = np.cumsum(start) - 1
    cs = np.flatnonzero(start)
    nc = len(cs)
    c_gs, c_t = gs_o[cs], fr_o[cs]
    c_rank = np.minimum.reduceat(rk_o, cs)
    # Attach each ranked chain to the latest earlier anchor of lower rank.
    idx = np.arange(nc)
    parent = np.full(nc, -1)
    for a in range(OPENING_RANK + 1):   # one pass per anchor rank, not per row
        last = np.maximum.accumulate(np.where(c_rank == a, idx, -1))
        prev = np.r_[-1, last[:-1]]
        ok = (prev >= 0) & (a < c_rank) & (c_rank < UNRANKED)
        p = np.where(ok, prev, 0)
        ok &= (c_gs[p] == c_gs) & (c_t - c_t[p] <= LIFE_S * fps)
        parent = np.where(ok & (prev > parent), prev, parent)
    root = np.where(parent >= 0, parent, idx)
    while True:   # pointer jumping: log2(chain depth) passes
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        root = nxt
    _u, ev = np.unique(root[chain], return_inverse=True)
    ev = ev.ravel()
    # Per event, detections in event order.
    o2 = np.lexsort((-v[o], ev))   # best detection first within each event
    det = o[o2]
    evs = ev[o2]
    first = _block_first(evs)
    cnt = np.diff(np.r_[first, len(evs)])
    fr_e = frame[det]
    big = np.iinfo(np.int64).max
    t_first = np.minimum.reduceat(fr_e, first)
    later = rank[det] >= OPENING_RANK   # UNRANKED counts as later
    t_cast = np.minimum.reduceat(np.where(later, fr_e, big), first)
    is_cast = t_cast < big
    if rule == "audio-open-set-0.1.0":
        t, is_cast = t_first, np.ones(len(first), bool)
    else:
        t = np.where(is_cast, t_cast, t_first)
    has_open = np.maximum.reduceat(opens[det].astype(np.int8), first).astype(bool)
    pairs = np.unique(evs * (int(phase.max()) + 1) + phase[det])
    nphase = np.bincount(pairs // (int(phase.max()) + 1), minlength=len(first))
    keep = np.ones(len(first), bool)
    if family == "cast":
        keep = has_open
    elif family == "agree":
        keep = nphase >= 2
    elif family == "seq":
        # The ability's own sequence: an opening detection, and a later-phase
        # one where the ability's game data plays any later-phase file.
        rk = rank[det]
        has_later = np.maximum.reduceat(((rk > OPENING_RANK) & (rk < UNRANKED))
                                        .astype(np.int8), first).astype(bool)
        need = (np.zeros(n, bool) if need_later is None
                else np.asarray(need_later, bool))[det[first]]
        keep = has_open & (has_later | ~need)
    out = {"key": key[det[first]], "slot": slot[det[first]], "frame": t, "cast": is_cast,
           "score": v[det[first]], "best": det[first], "nphase": nphase, "n": cnt}
    out = {k: np.asarray(a)[keep] for k, a in out.items()}
    s = np.lexsort((out["frame"], out["key"]))
    return {k: a[s] for k, a in out.items()}


def match(ev_slot, ev_frame, c_slot, c_frame, fps: int = FPS,
          window=MATCH_S) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(event index, cast index, event - drop in s): same slot, inside
    `window`, one to one, the most pairs and then the least total |dt|
    (`scipy.optimize.linear_sum_assignment`)."""
    from scipy.optimize import linear_sum_assignment
    ev_slot, ev_frame = np.asarray(ev_slot), np.asarray(ev_frame, np.int64)
    c_slot, c_frame = np.asarray(c_slot), np.asarray(c_frame, np.int64)
    none = (np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0))
    if not len(ev_slot) or not len(c_slot):
        return none
    dt = (ev_frame[:, None] - c_frame[None, :]) / fps
    ok = (ev_slot[:, None] == c_slot[None, :]) & (dt >= window[0]) & (dt <= window[1])
    r, c = np.flatnonzero(ok.any(1)), np.flatnonzero(ok.any(0))
    if not len(r):
        return none
    sub = ok[np.ix_(r, c)]
    cost = np.where(sub, np.abs(dt[np.ix_(r, c)]), 1e6)
    ri, cj = linear_sum_assignment(cost)
    k = sub[ri, cj]
    ei, ci = r[ri[k]], c[cj[k]]
    s = np.argsort(np.abs(dt[ei, ci]), kind="stable")
    return ei[s], ci[s], dt[ei, ci][s]


def castfree_mask(n: int, live: np.ndarray, times_s, fps: int = FPS,
                  span=CASTFREE_S) -> np.ndarray:
    """Live frames outside `span` around every time given."""
    t = np.asarray(times_s, np.float64)
    a = np.maximum(((t + span[0]) * fps).astype(np.int64), 0)
    b = np.minimum(((t + span[1]) * fps).astype(np.int64), n)
    k = b > a
    d = np.zeros(n + 1, np.int64)
    np.add.at(d, a[k], 1)
    np.add.at(d, b[k], -1)
    return np.asarray(live, bool)[:n] & (np.cumsum(d)[:n] == 0)


def keep_file(f: dict, subset: str) -> bool:
    return subset == "all" or (subset == "no3p" and f["perspective"] != "3P") or \
        (subset == "3p" and f["perspective"] == "3P") or \
        (subset == "opening" and f["opens"]) or (subset == "later" and not f["opens"])


def demo_truth_rule(casts: list[dict], drops: list[dict]) -> np.ndarray:
    """TRUTH_RULE: per census cast, whether it counts. A cast is left out
    when its tray drop (same slot, same time) carries the menu witness's
    refusal `menu_open`, or another slot's drop lies within COINCIDENT_MS."""
    if not casts:
        return np.zeros(0, bool)
    ct = np.array([c["t_ms"] for c in casts], np.float64)
    cs = np.array([c["slot"] for c in casts])
    if not drops:
        return np.ones(len(casts), bool)
    dt_ = np.array([d["t_ms"] for d in drops], np.float64)
    ds = np.array([d["slot"] for d in drops])
    menu = np.array([d.get("reason") == "menu_open" for d in drops])
    same = (np.abs(ct[:, None] - dt_[None, :]) < 1.0) & (cs[:, None] == ds[None, :])
    other = (np.abs(ct[:, None] - dt_[None, :]) < COINCIDENT_MS) & (cs[:, None] != ds[None, :])
    return ~((same & menu[None, :]).any(1) | other.any(1))


def evaluate(D: dict, family: str, subset: str, theta: float, sids: list[str],
             cross: bool = True, rule: str = RULE) -> dict:
    """Scores of one family, subset and threshold over `sids`. `D` (from
    `load`) holds the detections as arrays, the file table, and per session
    its live and cast-free masks, agent, casts and left-out drops."""
    det, ft = D["det"], D["ft"]
    sidx = np.array([D["sidx"][s] for s in sids], np.int64)
    sel = np.zeros(len(D["sids"]), bool)
    sel[sidx] = True
    base = sel[det["sid"]] & (det["v"] >= theta) & ft["keep"][subset][det["gfi"]]
    m = base & det["own"]
    g = det["gfi"][m]
    E = group_events(det["sid"][m], ft["slot"][g], det["frame"][m], ft["rank"][g],
                     ft["opens"][g], ft["phase"][g], det["v"][m], family, rule=rule,
                     tie=det["fidx"][m], need_later=ft["need_later"][subset][g])
    best_g = g[E["best"]] if len(E["best"]) else np.zeros(0, np.int64)
    bounds = np.searchsorted(E["key"], np.r_[sidx, sidx + 1].reshape(2, -1))
    rows = {}
    for si, sid, lo, hi in zip(sidx, sids, bounds[0], bounds[1]):   # per session
        cast_ev = np.flatnonzero(E["cast"][lo:hi]) + lo
        eq_ev = np.flatnonzero(~E["cast"][lo:hi]) + lo
        tr = D["truth"][sid]
        ei, ci, dt = match(E["slot"][cast_ev], E["frame"][cast_ev], tr["slot"], tr["frame"])
        unmatched = np.setdiff1d(np.arange(len(cast_ev)), ei)
        fe = cast_ev[unmatched]
        live, cf = D["live"][sid], D["castfree"][sid]
        n = len(live)
        bg = best_g[cast_ev[ei]]
        eq_then = 0
        if len(eq_ev) and len(tr["slot"]):
            d = tr["frame"][None, :] - E["frame"][eq_ev][:, None]
            eq_then = int(((E["slot"][eq_ev][:, None] == tr["slot"][None, :])
                           & (d >= 0) & (d <= 10 * FPS)).any(1).sum())
        near_left_out = 0
        lo_ = D["left_out"].get(sid)
        if lo_ is not None and len(lo_["frame"]) and len(fe):
            d = (E["frame"][fe][:, None] - lo_["frame"][None, :]) / FPS
            near_left_out = int(((E["slot"][fe][:, None] == lo_["slot"][None, :])
                                 & (d >= MATCH_S[0]) & (d <= MATCH_S[1])).any(1).sum())
        hit_slots = tr["slot"][ci]
        rows[sid] = {"agent": D["agent_of"][sid], "casts": int(len(tr["slot"])),
                     "hit": int(len(ei)),
                     "hits": [[SLOTS[s], round(float(x), 3), ft["phase_names"][p], str(q)]
                              for s, x, p, q in zip(hit_slots.tolist(), dt.tolist(),
                                                    ft["phase"][bg].tolist(),
                                                    ft["perspective"][bg].tolist())],
                     "miss_slots": [SLOTS[s] for s in np.delete(tr["slot"], ci).tolist()],
                     "slots": [SLOTS[s] for s in tr["slot"].tolist()],
                     "equip": int(len(eq_ev)), "equip_then_cast": eq_then,
                     "false": int(len(fe)),
                     "false_castfree": int(cf[np.minimum(E["frame"][fe], n - 1)].sum()),
                     "false_near_left_out": near_left_out,
                     "live_min": float(live.sum()) / (60.0 * FPS),
                     "castfree_min": float(cf.sum()) / (60.0 * FPS)}
    if cross:
        # Each agent's detector over every other agent's session in `sids`.
        agents_in = np.zeros(len(D["agents"]), bool)
        agents_in[[D["agents"].index(D["agent_of"][s]) for s in sids]] = True
        mx = base & ~det["own"] & agents_in[det["agent"]]
        gx = det["gfi"][mx]
        nA = len(D["agents"])
        Ex = group_events(det["sid"][mx].astype(np.int64) * nA + det["agent"][mx],
                          ft["slot"][gx], det["frame"][mx], ft["rank"][gx], ft["opens"][gx],
                          ft["phase"][gx], det["v"][mx], family, rule=rule, tie=det["fidx"][mx],
                          need_later=ft["need_later"][subset][gx])
        n_x = np.bincount((Ex["key"] % nA)[Ex["cast"]], minlength=nA)
        live_min = np.array([D["live"][s].sum() / (60.0 * FPS) for s in sids])
        ag = np.array([D["agents"].index(D["agent_of"][s]) for s in sids])
        seen = set()
        for sid, a in zip(sids, ag.tolist()):   # per session: the first of its agent
            if a in seen:
                rows[sid].update(cross_false=0, cross_min=0.0)
                continue
            seen.add(a)
            rows[sid].update(cross_false=int(n_x[a]), cross_min=float(live_min[ag != a].sum()))
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
           "false_near_left_out": s("false_near_left_out"),
           "equip": s("equip"), "equip_then_cast": s("equip_then_cast")}
    if r and "cross_false" in r[0]:
        out.update(cross_false=s("cross_false"), cross_min=s("cross_min"),
                   cross_per_min=s("cross_false") / max(s("cross_min"), 1e-9))
    dts = np.array([h[1] for x in r for h in x["hits"]], np.float64)
    out["abs_dt_median"] = float(np.median(np.abs(dts))) if len(dts) else None
    out["dt_median"] = float(np.median(dts)) if len(dts) else None
    return out


def choose(D, sids, ff=FF_PER_MIN, rule: str = RULE) -> tuple[dict, list[dict]]:
    """The dev choice: per family and subset the least threshold whose
    unmatched events per live minute are at most `ff`; then the most recall,
    ties to the fewer false events."""
    table = []
    for fam in FAMILIES:
        for sub in SUBSETS:
            for th in THETAS:
                p = pooled(evaluate(D, fam, sub, float(th), sids, cross=False, rule=rule))
                if p["false_per_min"] <= ff:
                    table.append({"family": fam, "subset": sub, "theta": float(th), **p})
                    break
    best = max(table, key=lambda r: (r["recall"], -r["false_per_min"]))
    return best, table


def tray_drops(store_root, sid: str) -> list[dict]:
    p = Path(store_root) / "events" / "tray_drop" / f"{sid}.jsonl"
    return [r for r in (json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
                        if x.strip()) if r.get("kind") == "drop"]


def _casts(rows: list[dict]) -> dict:
    return {"slot": np.array([SLOTS.index(r["slot"]) for r in rows], np.int64),
            "frame": np.array([int(r["t_ms"] / 10.0) for r in rows], np.int64)}


def detections(scan_dir: Path, meta: dict, own_of: dict) -> dict:
    """The stored detections as arrays, with each one's global file index
    and whether its agent is its session's (`own_of`: sid -> agent)."""
    with np.load(Path(scan_dir) / "detections.npz") as z:
        det = {k: z[k].astype(np.int64) if k != "v" else z[k].astype(np.float64)
               for k in ("sid", "agent", "fidx", "frame", "v")}
    agents = meta["agents"]
    ft = file_table(meta["files"], agents)
    det["gfi"] = ft["off"][det["agent"]] + det["fidx"]
    own_a = np.array([agents.index(own_of[s]) if own_of.get(s) in agents else -1
                      for s in meta["sids"]], np.int64)
    det["own"] = det["agent"] == own_a[det["sid"]]
    return {"det": det, "ft": ft}


def load(scan_dir: Path, store_root, truth_rule: bool = True) -> tuple[dict, dict]:
    """The demo scan's detections and the demos' truth (TRUTH_RULE unless
    `truth_rule` is False), refused unless the scan read the current set."""
    from reticle.ability_audio_fit import demo_truth
    meta = json.loads((Path(scan_dir) / "provenance.json").read_text(encoding="utf-8"))
    check_params(meta)
    sids = meta["sids"]
    agent_of = {sid: meta["demos"][sid]["agent"] for sid in sids}
    D = detections(scan_dir, meta, agent_of)
    D.update(sids=sids, sidx={s: i for i, s in enumerate(sids)}, agents=meta["agents"],
             agent_of=agent_of, live={}, castfree={}, truth={}, left_out={})
    for sid in sids:
        with np.load(Path(store_root) / FEATURES / f"{sid}.npz", allow_pickle=True) as fz:
            live = fz["ok"][:meta["demos"][sid]["n"]].astype(bool)
        drops = tray_drops(store_root, sid)
        census = demo_truth(store_root, sid)
        keep = demo_truth_rule(census, drops) if truth_rule else np.ones(len(census), bool)
        D["live"][sid] = live
        D["truth"][sid] = _casts([c for c, k in zip(census, keep) if k])
        D["left_out"][sid] = _casts([c for c, k in zip(census, keep) if not k])
        D["castfree"][sid] = castfree_mask(len(live), live, [c["t_ms"] / 1000.0 for c in census]
                                           + [d["t_ms"] / 1000.0 for d in drops])
    return D, meta


def per_agent(H: dict, paths: dict) -> dict:
    out: dict = {}
    for sid, r in H.items():
        a = out.setdefault(r["agent"], {})
        for k in ("casts", "hit", "false", "live_min", "false_castfree", "castfree_min",
                  "cross_false", "cross_min"):
            a[k] = a.get(k, 0) + r.get(k, 0)
        a.setdefault("dts", []).extend(round(h[1], 2) for h in r["hits"])
        a.setdefault("sessions", []).append({"sid": sid, "path": paths.get(sid)})
    for a in out.values():
        a["recall"] = a["hit"] / max(a["casts"], 1)
        a["false_per_min"] = a["false"] / max(a["live_min"], 1e-9)
        a["cross_per_min"] = a["cross_false"] / max(a["cross_min"], 1e-9)
    return out


def report(scan_dir: Path, store_root, rule: str = RULE) -> dict:
    D, meta = load(scan_dir, store_root)
    dev, held = meta["split"]["dev"], meta["split"]["held"]
    best, table = choose(D, dev, rule=rule)
    fam, sub, th = best["family"], best["subset"], best["theta"]
    H = evaluate(D, fam, sub, th, held, rule=rule)
    Dv = evaluate(D, fam, sub, th, dev, rule=rule)
    paths = {s: meta["demos"][s]["path"] for s in meta["sids"]}
    slot = {s: {"casts": sum(r["slots"].count(s) for r in H.values()),
                "hit": sum(1 for r in H.values() for h in r["hits"] if h[0] == s)} for s in SLOTS}
    abl = {s2: {"dev": pooled(evaluate(D, fam, s2, th, dev, cross=False, rule=rule)),
                "held": pooled(evaluate(D, fam, s2, th, held, cross=False, rule=rule))}
           for s2 in ("all", "no3p", "3p", "opening", "later")}
    held_of = []
    for r in table:
        p = pooled(evaluate(D, r["family"], r["subset"], r["theta"], held, rule=rule))
        held_of.append({"family": r["family"], "subset": r["subset"], "theta": r["theta"],
                        "dev_recall": r["recall"], "dev_false_per_min": r["false_per_min"],
                        "held_recall": p["recall"], "held_false_per_min": p["false_per_min"],
                        "held_cross_per_min": p["cross_per_min"]})
    left = {s: int(len(D["left_out"][s]["slot"])) for s in meta["sids"]
            if len(D["left_out"][s]["slot"])}
    return {"version": rule, "truth_rule": TRUTH_RULE, "detections": meta["version"],
            "params": meta["params"], "scan_dir": Path(scan_dir).as_posix(),
            "detections_built": meta["built_at"], "choice": best,
            "truth_left_out": left, "dev_table": table, "families_on_held": held_of,
            "dev": pooled(Dv), "held": pooled(H), "held_per_agent": per_agent(H, paths),
            "held_per_slot": slot,
            "held_decided_by_phase": dict(Counter(h[2] for r in H.values() for h in r["hits"])),
            "held_decided_by_perspective": dict(Counter(h[3] for r in H.values()
                                                        for h in r["hits"])),
            "ablations": abl,
            "rule": {"match_s": MATCH_S, "castfree_s": CASTFREE_S, "join_s": JOIN_S,
                     "life_s": LIFE_S, "ff_per_min": FF_PER_MIN,
                     "coincident_ms": COINCIDENT_MS}}


def seq_dev(score_dir: Path, store_root, rule: str = RULE) -> dict:
    """Dev demos only: the `seq` family (each ability's own sequence from the
    game data's phase map) beside the frozen choice, at the choice's subset
    and threshold, and at seq's own dev operating point."""
    rep = json.loads((Path(score_dir) / "report.json").read_text(encoding="utf-8"))
    D, meta = load(Path(rep["scan_dir"]), store_root)
    dev, c = meta["split"]["dev"], rep["choice"]
    out = {"version": rule, "score_dir": Path(score_dir).as_posix(), "choice": c,
           "split": "dev demos only", "at_choice": {}, "own_point": {}}
    for fam in (c["family"], "cast", "agree", "seq"):
        out["at_choice"][fam] = pooled(evaluate(D, fam, c["subset"], c["theta"], dev,
                                                cross=False, rule=rule))
    for sub in SUBSETS:
        for th in THETAS:
            p = pooled(evaluate(D, "seq", sub, float(th), dev, cross=False, rule=rule))
            if p["false_per_min"] <= FF_PER_MIN:
                out["own_point"][sub] = {"theta": float(th), **p}
                break
    return out


def print_report(rep: dict) -> None:
    c = rep["choice"]
    print(f"dev choice: family {c['family']} subset {c['subset']} theta {c['theta']} "
          f"dev recall {c['hit']}/{c['casts']} false/min {c['false_per_min']:.2f}")
    if "families_on_held" in rep:
        print("family subset theta | dev recall false/min | held recall false/min cross/min")
        for r in rep["families_on_held"]:
            print(f"{r['family']:5} {r['subset']:4} {r['theta']:.1f} | {r['dev_recall']:.2f} "
                  f"{r['dev_false_per_min']:.2f} | {r['held_recall']:.2f} "
                  f"{r['held_false_per_min']:.2f} {r['held_cross_per_min']:.2f}")
    h = rep["held"]
    print(f"held: recall {h['hit']}/{h['casts']} ({h['recall']:.2f}); false {h['false']} in "
          f"{h['live_min']:.1f} min ({h['false_per_min']:.2f}/min); cast-free false "
          f"{h['false_castfree']} in {h['castfree_min']:.1f} min "
          f"({h['false_castfree_per_min']:.2f}/min); near a left-out drop "
          f"{h['false_near_left_out']}; cross {h.get('cross_false')} in "
          f"{h.get('cross_min', 0):.1f} min; |dt| median "
          f"{h['abs_dt_median']}, dt median {h['dt_median']}; equip state events {h['equip']}, "
          f"{h['equip_then_cast']} followed by a same-slot cast within 10 s")
    print("agent | recall | false/min | cast-free false/min | cross/min | dt (s)")
    for a, r in sorted(rep["held_per_agent"].items()):
        cf = r["false_castfree"] / r["castfree_min"] if r["castfree_min"] > 0 else float("nan")
        print(f"{a:9} {r['hit']}/{r['casts']} {r['false_per_min']:.2f} {cf:.2f} "
              f"({r['false_castfree']} in {r['castfree_min']:.2f} min) "
              f"{r['cross_per_min']:.2f} {r['dts']}")
    for k, v in rep.get("ablations", {}).items():
        print(f"ablation {k:7}: dev {v['dev']['hit']}/{v['dev']['casts']} "
              f"{v['dev']['false_per_min']:.2f}/min | held {v['held']['hit']}/{v['held']['casts']} "
              f"{v['held']['false_per_min']:.2f}/min")


# ---------------------------------------------------------------------------
# The match test
# ---------------------------------------------------------------------------

def match_scan(store_root, score_dir: Path, out_dir: Path | None = None) -> Path:
    """Detections of the player's agent's kit on every match session the
    current parameter set's gate names, scaled by the demo scan's null;
    the gate snapshot beside them. Decodes nothing."""
    from reticle.ability_audio_fit import gate_snapshot, match_session
    from reticle.adjudication import ability_audio as aa
    from reticle.store import Store
    from reticle.ult_lines import array_module, release_gpu
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    t0 = time.time()
    store_root = Path(store_root)
    rep = json.loads((Path(score_dir) / "report.json").read_text(encoding="utf-8"))
    scan_dir = Path(rep["scan_dir"])
    smeta = json.loads((scan_dir / "provenance.json").read_text(encoding="utf-8"))
    check_params(smeta)
    out_dir = new_dir(out_dir or store_root / OUT_ROOT / (
        f"match-{SCAN_VERSION}_{ABILITY_AUDIO_PARAMS_VERSION}"))
    pprov = json.loads((aa.params_path(store_root, ABILITY_AUDIO_PARAMS_VERSION)
                        / "provenance.json").read_text(encoding="utf-8"))
    sids = sorted(pprov["gate"])
    gate = gate_snapshot(Store(store_root), sids, {})
    new_file(out_dir / "gate.json", json.dumps(gate, indent=0))
    agents = sorted({g["agent"] for g in gate.values()})
    files, W, wh, tcheck = kit_setup(store_root, agents)
    with np.load(scan_dir / "detections.npz") as z:
        q = {a: z[f"q__{a.replace('/', '_')}"] for a in agents}
    for a in agents:   # the demo null and this kit must name the same files
        if [f["flac"] for f in files[a]] != [f["flac"] for f in smeta["files"][a]]:
            raise SystemExit(f"{a}: the kit differs from the demo scan's")
    xp = array_module()
    det = {k: [] for k in ("sid", "agent", "fidx", "frame", "v")}
    sessions = {}
    for si, sid in enumerate(sorted(gate)):   # one session at a time
        s, why = match_session(store_root, sid, gate)
        if s is None:
            print(f"{sid}: {why}", flush=True)
            continue
        a = gate[sid]["agent"]
        C = aa.Corpus(aa.whiten_frames(s["X"], wh["mu"], wh["P"], wh["ar"]), MAX_LEN, xp)
        f, k, v = detect(C, s["live"], [W[x["flac"]] for x in files[a]], q[a], xp)
        del C
        release_gpu(xp)
        det["sid"].append(np.full(len(f), si, np.int16))
        det["agent"].append(np.full(len(f), agents.index(a), np.int16))
        det["fidx"].append(f)
        det["frame"].append(k)
        det["v"].append(v)
        np.save(out_dir / f"live-{sid}.npy", s["live"])
        sessions[sid] = {"agent": a, "path": gate[sid]["path"], "n": int(len(s["live"])),
                         "live_min": float(s["live"].sum()) / (60.0 * FPS),
                         "casts": s["casts"], "stamps": {k2: str(v2) for k2, v2 in
                                                         s.get("stamps", {}).items()}}
        print(f"match {sid} {a}: {len(f)} detections, {len(s['casts'])} casts "
              f"{time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(out_dir / "detections.npz",
                        **{k: np.concatenate(v) for k, v in det.items()})
    meta = {"version": SCAN_VERSION, "kind": "matches",
            "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "built_by": "prototypes/audio_open_set.py match-scan",
            "params": ABILITY_AUDIO_PARAMS_VERSION, "phase_map": PHASE_MAP.as_posix(),
            "templates": TEMPLATE_CACHE.as_posix(), "template_check": tcheck,
            "null_from": scan_dir.as_posix(), "score_dir": Path(score_dir).as_posix(),
            "device": xp.__name__, "candidate_set": "the player's agent (gate_snapshot: "
            "player_agent_verdict of the stored lineup), its single-ability kit files",
            "params_split": pprov["split"],
            "rule": {"det_level": DET_LEVEL, "peak_gap": PEAK_GAP},
            "agents": agents, "sids": sorted(gate), "sessions": sessions, "files": files,
            "seconds": round(time.time() - t0, 1)}
    new_file(out_dir / "provenance.json", json.dumps(meta, indent=1))
    return out_dir


def load_matches(match_dir: Path, store_root) -> tuple[dict, dict]:
    match_dir = Path(match_dir)
    meta = json.loads((match_dir / "provenance.json").read_text(encoding="utf-8"))
    check_params(meta)
    gate = json.loads((match_dir / "gate.json").read_text(encoding="utf-8"))
    sids = [s for s in meta["sids"] if s in meta["sessions"]]
    agent_of = {s: gate[s]["agent"] for s in meta["sids"]}
    D = detections(match_dir, meta, agent_of)
    D.update(sids=meta["sids"], sidx={s: i for i, s in enumerate(meta["sids"])},
             agents=meta["agents"], agent_of=agent_of, live={}, castfree={}, truth={},
             left_out={})
    for sid in sids:
        live = np.load(match_dir / f"live-{sid}.npy")
        drops = [r["t_ms"] / 1000.0 for r in gate[sid]["rows"]]
        D["live"][sid] = live
        D["truth"][sid] = _casts(meta["sessions"][sid]["casts"])
        D["castfree"][sid] = castfree_mask(len(live), live, drops)
    meta["scored"] = sids
    return D, meta


def halves(D: dict, meta: dict, names: list[str]) -> tuple[dict, list[str]]:
    """`D` restricted to the units `names` (a session, or `sid:first` /
    `sid:second`, its frame halves): detections, live frames and casts
    outside a half are dropped."""
    det = D["det"]
    keep = np.zeros(len(det["sid"]), bool)
    out = dict(D, live=dict(D["live"]), castfree=dict(D["castfree"]), truth=dict(D["truth"]))
    sids = []
    for name in names:
        sid, _, half = name.partition(":")
        if sid not in D["live"]:
            continue
        n = len(D["live"][sid])
        lo, hi = {"": (0, n), "first": (0, n // 2), "second": (n // 2, n)}[half]
        m = (det["sid"] == D["sidx"][sid]) & (det["frame"] >= lo) & (det["frame"] < hi)
        keep |= m
        span = np.zeros(n, bool)
        span[lo:hi] = True
        out["live"][sid] = D["live"][sid] & span
        out["castfree"][sid] = D["castfree"][sid] & span
        t = D["truth"][sid]
        k = (t["frame"] >= lo) & (t["frame"] < hi)
        out["truth"][sid] = {"slot": t["slot"][k], "frame": t["frame"][k]}
        sids.append(sid)
    out["det"] = {k: a[keep] for k, a in det.items()}
    return out, sids


def match_report(match_dir: Path, store_root, rule: str = RULE) -> dict:
    """Score the frozen dev choice once on the matches: own-agent cast
    recall against the gate's tray casts, unmatched events per live minute,
    cast-free false events and the time offset; every session, and the
    parameter set's held units apart."""
    D, meta = load_matches(match_dir, store_root)
    rep = json.loads((Path(meta["score_dir"]) / "report.json").read_text(encoding="utf-8"))
    c = rep["choice"]
    sids = meta["scored"]
    paths = {s: meta["sessions"][s]["path"] for s in sids}
    A = evaluate(D, c["family"], c["subset"], c["theta"], sids, cross=False, rule=rule)
    held_units = sorted(u for v in meta["params_split"].values() for u in v["held"])
    Dh, hs = halves(D, meta, held_units)
    Hh = evaluate(Dh, c["family"], c["subset"], c["theta"], hs, cross=False, rule=rule)
    fams = [{"family": r["family"], "subset": r["subset"], "theta": r["theta"],
             **{k: v for k, v in pooled(evaluate(D, r["family"], r["subset"], r["theta"], sids,
                                                 cross=False, rule=rule)).items()
                if k in ("hit", "casts", "recall", "false_per_min", "abs_dt_median")}}
            for r in rep["dev_table"]]
    return {"version": rule, "detections": meta["version"], "params": meta["params"],
            "match_dir": Path(match_dir).as_posix(), "score_dir": meta["score_dir"],
            "choice": c, "candidate_set": meta["candidate_set"],
            "all": pooled(A), "all_per_agent": per_agent(A, paths),
            "params_held_units": held_units, "params_held": pooled(Hh),
            "per_session": {s: {k: v for k, v in r.items() if k != "hits"}
                            | {"path": paths[s], "dts": [h[1] for h in r["hits"]]}
                            for s, r in A.items()},
            "families_dev_fixed_on_matches": fams,
            "decided_by_phase": dict(Counter(h[2] for r in A.values() for h in r["hits"]))}


def print_match_report(rep: dict) -> None:
    c = rep["choice"]
    print(f"frozen: family {c['family']} subset {c['subset']} theta {c['theta']}")
    for k in ("all", "params_held"):
        h = rep[k]
        print(f"{k}: recall {h['hit']}/{h['casts']} ({h['recall']:.2f}); false {h['false']} in "
              f"{h['live_min']:.1f} min ({h['false_per_min']:.2f}/min); cast-free false "
              f"{h['false_castfree']} in {h['castfree_min']:.1f} min "
              f"({h['false_castfree_per_min']:.2f}/min); |dt| median {h['abs_dt_median']}, "
              f"dt median {h['dt_median']}; equip events {h['equip']}")
    for a, r in sorted(rep["all_per_agent"].items()):
        print(f"{a:9} {r['hit']}/{r['casts']} ({r['recall']:.2f}) false/min "
              f"{r['false_per_min']:.2f}")
    for r in rep["families_dev_fixed_on_matches"]:
        print(f"  {r['family']:5} {r['subset']:4} {r['theta']:.1f}: {r['hit']}/{r['casts']} "
              f"false/min {r['false_per_min']:.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("scan", "score", "match-scan", "match-score", "seq-dev"))
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--scan", default=None, help="score: the demo scan directory")
    ap.add_argument("--score", default=None, help="match-scan: the demo score directory")
    ap.add_argument("--match", default=None, help="match-score: the match scan directory")
    ap.add_argument("--out", default=None, help="a new output directory")
    a = ap.parse_args(argv)
    below_normal()
    store = Path(a.store)
    if a.cmd == "scan":
        print(scan(store, Path(a.out) if a.out else None))
        return 0
    if a.cmd == "match-scan":
        print(match_scan(store, Path(a.score), Path(a.out) if a.out else None))
        return 0
    if a.cmd == "score":
        scan_dir = Path(a.scan)
        rep = report(scan_dir, store)
        out = new_dir(Path(a.out) if a.out else scan_dir / f"score-{RULE}_{TRUTH_RULE}")
        print_report(rep)
    elif a.cmd == "seq-dev":
        rep = seq_dev(Path(a.score), store)
        out = new_dir(Path(a.out) if a.out else Path(a.score) / f"seq-dev-{RULE}")
        for k, v in rep["at_choice"].items():
            print(f"at choice {k:5}: dev {v['hit']}/{v['casts']} false {v['false']} "
                  f"({v['false_per_min']:.2f}/min)")
        for k, v in rep["own_point"].items():
            print(f"seq {k} own point theta {v['theta']}: {v['hit']}/{v['casts']} "
                  f"{v['false_per_min']:.2f}/min")
    else:
        rep = match_report(Path(a.match), store)
        out = new_dir(Path(a.out) if a.out else Path(a.match) / f"score-{RULE}")
        print_match_report(rep)
    rep["written_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    print(new_file(out / "report.json", json.dumps(rep, indent=1, default=float)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
