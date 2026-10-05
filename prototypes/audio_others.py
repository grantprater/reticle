r"""Can the game's own ability sounds witness casts by OTHER players?

    .\.venv\Scripts\python.exe prototypes\audio_others.py inventory
    .\.venv\Scripts\python.exe prototypes\audio_others.py scan [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\audio_others.py report [--record] [--json OUT]
                                                         [--sightlines PY]

What it asks
------------
The ability cast coverage survey (`prototypes/ability_coverage.py`, ledger
`ability_coverage/*`) witnesses the player's own casts well and other
players' casts poorly; enemy smokes are not drawn on the minimap. The audio
witness (`reticle.adjudication.ability_audio`, owner `ability-audio`) scores
only the player's tray drops. This prototype runs the same whitened matched
filter over the whole stored audio for every ability of every agent the
match's lineup names, both sides, and scores what it hears against the
replay's timed casts (one match) and Riot's match totals (the rest).

Reuse, not restatement
----------------------
* frames, live and null masks: `ability_timeline.audio_session` with no
  gate rows and no kit (every live frame, not only the player's kit);
* the whitener: the pooled one stored in WHITENER_FROM (`fit_whitener`'s
  `mu`, `P`, `ar`; the same arrays for every agent of that set);
* references: `ability_audio_fit.references` (the wired rule: display name
  to tray slot, movement, end-phase, unmapped and shared files left out, a
  shared release is its phase group's class), decoded by
  `ability_audio.reference_logmel`, cut by `template` and whitened by
  `whiten_template`;
* tracks: `ability_audio.class_tracks` (lagged Pearson, normalised per
  template by the null's median and 99.9th percentile, class = maximum);
  a side-variant track per slot rides on its `extra`;
* peaks: `scipy.signal.find_peaks` with `ability_audio.PEAK_GAP`, as
  `false_fire_peaks` takes them.

Candidate set
-------------
The lineup owner's agents (`lineup.load_lineup`, both sides): the match's
context allows those ten. Every other agent seen in any lineup is scored too,
but only as a NULL: its templates over a match it is absent from give false
alarms by construction (`absent-agent null`), which sets each class's
threshold. Riot records and the replay are evaluation truth only: they never
set a threshold, a template or a candidate.

The pre-registered rule (predictions `audio-others-20261004`)
--------------------------------------------------------------
* peaks above FLOOR on live frames, PEAK_GAP apart, are stored per session
  (`scan`); a class's DETECTIONS at threshold t are its peaks >= t merged
  when closer than MERGE_S, each at its first peak;
* the threshold per (agent, class) is the least grid level at which the
  agent's detections on DEV-half matches it is absent from stay at or under
  NULL_FF_PER_MIN per live minute (the half: `dev_half`, sha256 parity of
  the session id); the HELD half's absent-agent rate is the false-alarm
  score (A2);
* a detection pairs one to one with the nearest cast of that agent whose
  tray key the class names, within [-PAIR_PRE_S, +PAIR_POST_S] of the cast
  (a phase group's class names each member key);
* recall counts casts at live frames (the player alive in a live phase);
  casts while the player is dead or in a dead phase are counted apart;
* distance: the caster's replay position less the player's at the cast,
  3D, metres, bins of DIST_BIN_M; line of sight, where a sightline table is
  passed (`--sightlines`, branch engagement-reach-20261004, read only), by
  its `los_near`.

The side question
-----------------
A few abilities ship separate "Ally" and "Enemy" files (by name token,
`side_token`). Where a slot has both, the scan keeps one extra track per
token; a detection's vote is the token whose track is higher at the
detection's first peak. Whether the vote tells the caster's side is
measured, never assumed: on the replay match by paired casts, and on every
match where the agent plays one side only.

Outputs
-------
`<store>/analysis/audio-others-20261004/` holds the template bank, one peak
file per session and the report; the ledger rows are `audio_others/*`.
Decodes no capture video or audio; decodes only the game's reference files
(`ability-audio-ref-0.2.0`). Nothing in `reticle/` reads this file.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

AUDIO_OTHERS_VERSION = "audio-others-proto-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "audio-others-20261004"
#: The parameter set whose pooled whitener the scan reuses.
WHITENER_FROM = "ability-audio-params-0.2.8"
#: Peaks at or above this normalised level are stored (1.0 is the null's
#: 99.9th percentile per template).
FLOOR = 0.5
#: Detections of one class closer than this merge into one, at the first.
MERGE_S = 3.0
#: A detection pairs with a cast from PAIR_PRE_S before to PAIR_POST_S after.
PAIR_PRE_S, PAIR_POST_S = 1.0, 3.0
#: The dev threshold's false-alarm budget on absent-agent matches.
NULL_FF_PER_MIN = 0.5
#: The threshold grid.
GRID_STEP, GRID_MAX = 0.02, 12.0
#: Distance bins (m) and the acceptance bars.
DIST_BIN_M = 10.0
A1_NEAR_M, A1_SHARE, A1_MIN_ABILITIES, A1_MIN_CASTS = 20.0, 1.0 / 3.0, 10, 3
A2_FA_PER_MIN = 1.0
#: The side tokens a reference file's name may carry.
SIDE_TOKEN = re.compile(r"(?i)(ally|enemy)")
SIDES = ("ally", "enemy")
REPLAY_SESSION = "9acf02f98283"
REPLAY_MATCH = "b03fecd3-8d80-4e6c-bae0-ac2ec0344567"
#: The replay cast record's slot byte (as `ability_coverage` checks it on Riot).
REPLAY_SLOT = {3: "Grenade", 4: "Ability1", 5: "Ability2", 9: "Ultimate"}


def _below_normal() -> None:
    """Windows BELOW_NORMAL_PRIORITY_CLASS for this process; elsewhere nice 10."""
    try:
        if os.name == "nt":
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
        else:
            os.nice(10)
    except Exception:
        pass


# ----------------------------------------------------------------- pure rules

def dev_half(sid: str) -> bool:
    """The fixed split: a session is dev when its id's sha256 is even."""
    return int(hashlib.sha256(sid.encode("utf-8")).hexdigest(), 16) % 2 == 0


def side_token(name: str) -> str | None:
    """'ally' or 'enemy' where a reference file's name carries one token of
    that side only; None for neither or both."""
    toks = {m.lower() for m in SIDE_TOKEN.findall(Path(name).name)}
    return next(iter(toks)) if len(toks) == 1 else None


def canon(name) -> str | None:
    """One spelling per agent: `KAY/O`, `KAY_O` and `kay/o` agree."""
    if name is None:
        return None
    return " ".join(str(name).replace("/", "_").replace("-", " ").casefold().split())


def detections(frames, values, thr: float, merge_frames: int) -> np.ndarray:
    """Frames of the detections at threshold `thr`: the peaks at or above it,
    sorted, merged where the gap to the previous is under `merge_frames`, each
    detection at its first peak. Vectorised."""
    f = np.sort(np.asarray(frames, np.int64)[np.asarray(values, float) >= thr])
    if not len(f):
        return f
    return f[np.concatenate([[True], np.diff(f) >= merge_frames])]


def detection_index(frames, values, thr: float, merge_frames: int) -> np.ndarray:
    """Indices (into `frames`) of the first peak of each detection, as
    `detections` forms them."""
    frames = np.asarray(frames, np.int64)
    idx = np.flatnonzero(np.asarray(values, float) >= thr)
    idx = idx[np.argsort(frames[idx], kind="stable")]
    if not len(idx):
        return idx
    return idx[np.concatenate([[True], np.diff(frames[idx]) >= merge_frames])]


def threshold_for(null: list[tuple[np.ndarray, np.ndarray]], live_min: float,
                  ff_per_min: float = NULL_FF_PER_MIN, merge_frames: int = 300,
                  grid=None) -> float | None:
    """The least grid level t such that at every grid level >= t the
    detections over the null sessions ((frames, values) per session) number
    at most `ff_per_min` per live minute. None without live minutes."""
    if live_min <= 0:
        return None
    grid = np.arange(FLOOR, GRID_MAX + 1e-9, GRID_STEP) if grid is None else np.asarray(grid)
    budget = ff_per_min * live_min
    counts = np.array([sum(len(detections(f, v, t, merge_frames)) for f, v in null)
                       for t in grid])
    ok = counts <= budget
    # the monotone envelope from the top: every higher level also within budget
    tail = np.flip(np.logical_and.accumulate(np.flip(ok)))
    if not tail.any():
        return None
    return float(grid[np.argmax(tail)])


def pair(det_s, truth_s, pre: float = PAIR_PRE_S, post: float = PAIR_POST_S
         ) -> list[tuple[int, int, float]]:
    """One-to-one pairs (det index, truth index, det - truth) of detections
    lying from `pre` before to `post` after a truth time, nearest first."""
    d = np.asarray(det_s, float)
    t = np.asarray(truth_s, float)
    if not len(d) or not len(t):
        return []
    dt = d[:, None] - t[None, :]
    ii, jj = np.nonzero((dt >= -pre) & (dt <= post))
    order = np.argsort(np.abs(dt[ii, jj]), kind="stable")
    ui, uj, out = set(), set(), []
    for k in order:
        i, j = int(ii[k]), int(jj[k])
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        out.append((i, j, float(dt[i, j])))
    return out


def distance_bin(d_m) -> np.ndarray:
    """The lower edge (m) of each distance's DIST_BIN_M bin; NaN stays NaN."""
    d = np.asarray(d_m, float)
    return np.floor(d / DIST_BIN_M) * DIST_BIN_M


def side_vote(ally_v, enemy_v) -> np.ndarray:
    """'ally', 'enemy' or None per detection: the token whose track is higher."""
    a = np.asarray(ally_v, float)
    e = np.asarray(enemy_v, float)
    out = np.full(a.shape, None, object)
    ok = np.isfinite(a) & np.isfinite(e) & (a != e)
    out[ok & (a > e)] = "ally"
    out[ok & (e > a)] = "enemy"
    return out


def class_keys(cls: str, groups: dict[str, list[str]]) -> list[str]:
    """The tray keys a class names: a phase group's members, else itself."""
    return list(groups.get(cls, [cls]))


# ----------------------------------------------------------------- the bank

def whitener(store: Path = STORE) -> dict:
    """The pooled whitener of WHITENER_FROM and its digest. Every agent of the
    set carries the same arrays (`fit_whitener` is pooled); this checks it."""
    from reticle.adjudication import ability_audio as aa
    prov = json.loads((aa.params_path(store, WHITENER_FROM) / "provenance.json")
                      .read_text(encoding="utf-8"))
    ws = []
    for agent in prov["agents"]:
        p, why = aa.load_params(store, WHITENER_FROM, agent)
        if p is None:
            raise SystemExit(why)
        ws.append((p["mu"], p["P"], p["ar"]))
    mu, P, ar = ws[0]
    for m2, P2, a2 in ws[1:]:
        if not (np.array_equal(mu, m2) and np.array_equal(P, P2) and np.array_equal(ar, a2)):
            raise SystemExit(f"{WHITENER_FROM}: the whitener is not pooled")
    h = hashlib.sha256(np.ascontiguousarray(mu).tobytes() + np.ascontiguousarray(P).tobytes()
                       + np.ascontiguousarray(ar).tobytes()).hexdigest()
    return {"mu": mu, "P": P, "ar": ar, "sha256": h, "version": WHITENER_FROM}


def manifest_agent(agent: str, store: Path = STORE) -> str:
    """The reference manifest's spelling of a lineup agent."""
    from reticle import ability_audio_fit as fit
    names = {json.loads(x)["agent"] for x in (store / fit.MANIFEST).read_text(
        encoding="utf-8").splitlines() if x.strip()}
    return next((n for n in names if canon(n) == canon(agent)), agent)


def build_bank(agent: str, W: dict, plays: dict, store: Path = STORE) -> dict:
    """An agent's whitened templates under the wired reference rule, with each
    file's class, side token and perspective, and the phase groups' members."""
    from reticle import ability_audio_fit as fit
    from reticle.adjudication import ability_audio as aa
    m_agent = manifest_agent(agent, store)
    refs, rule = fit.references(store, m_agent, plays)
    meta = {json.loads(x)["flac"]: json.loads(x) for x in (store / fit.MANIFEST).read_text(
        encoding="utf-8").splitlines() if x.strip()}
    temps, rows = [], []
    for r in refs:
        T = aa.template(aa.reference_logmel(store / fit.REF_DIR / r["flac"]))
        if T is None:
            continue
        temps.append(aa.whiten_template(T, W["P"], W["ar"]))
        rows.append({"flac": r["flac"], "class": r["class"], "ability": r["ability"],
                     "side": side_token(r["flac"]),
                     "perspective": (meta.get(r["flac"]) or {}).get("perspective")})
    kept = {x["flac"] for x in rows}
    groups = {g["name"]: list(g["members"]) for g in
              fit.phase_groups(m_agent, [r for r in refs if r["flac"] in kept], rule["kit"])}
    return {"agent": agent, "manifest_agent": m_agent, "templates": temps, "rows": rows,
            "kit": rule["kit"], "groups": groups,
            "slots_without_reference": rule["slots_without_reference"]}


def bank_labels(bank: dict) -> tuple[list[str], dict[str, list[int]]]:
    """(per-template labels, extra tracks): each template's label is its class;
    a class with both side tokens gets `<class>|ally` and `<class>|enemy`."""
    labels = [r["class"] for r in bank["rows"]]
    extra = {}
    for cls in sorted(set(labels)):
        by = {s: [i for i, r in enumerate(bank["rows"]) if r["class"] == cls and r["side"] == s]
              for s in SIDES}
        if all(by.values()):
            for s in SIDES:
                extra[f"{cls}|{s}"] = by[s]
    return labels, extra


def bank_path(agent: str, W: dict) -> Path:
    return OUT / f"bank-{W['sha256'][:12]}" / f"{canon(agent).replace(' ', '_')}.npz"


def load_bank(agent: str, W: dict, plays_fn, store: Path = STORE) -> dict:
    """The cached bank of an agent, built once per whitener."""
    p = bank_path(agent, W)
    if p.is_file():
        z = np.load(p, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        lens = z["lens"]
        cuts = np.concatenate([[0], np.cumsum(lens)])
        meta["templates"] = [z["T"][a:b] for a, b in zip(cuts[:-1], cuts[1:])]
        return meta
    b = build_bank(agent, W, plays_fn(), store)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in b.items() if k != "templates"}
    meta.update(whitener=W["version"], whitener_sha256=W["sha256"],
                built_by=AUDIO_OTHERS_VERSION)
    T = np.concatenate(b["templates"]) if b["templates"] else np.zeros((0, len(W["mu"])), np.float32)
    np.savez(p, T=T.astype(np.float32), lens=np.array([t.shape[0] for t in b["templates"]], int),
             meta=json.dumps(meta))
    return b


# ----------------------------------------------------------------- sessions

def riot_sessions(store: Path = STORE) -> dict[str, dict]:
    import riot_ground_truth as rg
    return rg.riot_records(store)


def lineup_sides(sid: str, store: Path = STORE) -> dict[str, list[str]] | None:
    """{side: agents} from the lineup owner, or None where no lineup is stored."""
    from reticle.lineup import load_lineup
    lu = load_lineup(sid, store)
    if not lu:
        return None
    return {k: [x.get("agent") if isinstance(x, dict) else x for x in v]
            for k, v in (lu.get("sides") or {}).items()}


def inventory(store: Path = STORE) -> dict:
    """Which Riot-recorded sessions hold stored audio and a lineup; for one
    without audio, its capture and the extraction it would need."""
    from reticle.ability_timeline import AUDIO_GATE_DIR
    from reticle.store import Store
    st = Store(store)
    out = {}
    for sid in sorted(riot_sessions(store)):
        g = store / AUDIO_GATE_DIR
        f, lab = g / "features" / f"{sid}.npz", g / "labels" / f"{sid}.json"
        row = {"features": f.is_file(), "labels": lab.is_file(), "dev": dev_half(sid)}
        if f.is_file():
            with np.load(f, allow_pickle=True) as z:
                row["audio_min"] = round(len(z["ok"]) / 6000.0, 2)
        sides = lineup_sides(sid, store)
        row["lineup"] = sides
        if not (row["features"] and row["labels"]):
            try:
                man = st.read_manifest(sid)
                row["capture"] = man["source"].get("path")
                row["capture_samples_5hz"] = man.get("n_samples")
                row["capture_min"] = round((man.get("n_samples") or 0) / 5.0 / 60.0, 1)
            except Exception as e:  # a session the store never ingested
                row["capture"] = f"no manifest: {e}"
        out[sid] = row
    return out


def session_audio(sid: str, store: Path = STORE):
    """The stored audio of a session for every player's casts: no gate rows,
    no kit (`ability_timeline.audio_session`)."""
    from reticle.ability_timeline import audio_session
    return audio_session(store, sid, [], None, None)


# ----------------------------------------------------------------- the scan

def session_peaks(Xw, s: dict, banks: dict[str, dict], xp=np) -> dict:
    """Every agent's class peaks over one whitened session: per (agent, class)
    the peak frames and values at or above FLOOR on live frames, PEAK_GAP
    apart, and, per side-variant class, both side tracks' maxima within half
    a second of each peak. One `class_tracks` call per agent."""
    from scipy.signal import find_peaks

    from reticle.adjudication import ability_audio as aa
    live = s["live"]
    half = aa.FPS // 2
    out = {}
    for agent, b in banks.items():
        if not b["templates"]:
            continue
        labels, extra = bank_labels(b)
        tr = aa.class_tracks(Xw, b["templates"], labels, s["bg"], xp, extra=extra)
        for cls in sorted(set(labels)):
            t = np.where(live, tr[cls], -1e3).astype(np.float32)
            pk, props = find_peaks(t, height=FLOOR, distance=aa.PEAK_GAP)
            row = {"frame": pk.astype(np.int32), "value": props["peak_heights"].astype(np.float32)}
            for sd in SIDES:
                k = f"{cls}|{sd}"
                if k in tr:
                    row[sd] = aa.range_max(tr[k], pk - half, pk + half + 1)
            out[(agent, cls)] = row
    return out


def save_peaks(sid: str, peaks: dict, s: dict, meta: dict) -> Path:
    d = OUT / "peaks"
    d.mkdir(parents=True, exist_ok=True)
    arrays, keys = {}, []
    for i, ((agent, cls), r) in enumerate(sorted(peaks.items())):
        keys.append([agent, cls])
        for k, v in r.items():
            arrays[f"{i}__{k}"] = v
    arrays["live_bits"] = np.packbits(s["live"].astype(bool))
    arrays["n_frames"] = np.array(len(s["live"]))
    p = d / f"{sid}.npz"
    np.savez_compressed(p, keys=json.dumps(keys), meta=json.dumps(meta), **arrays)
    return p


def load_peaks(sid: str) -> tuple[dict, np.ndarray, dict] | None:
    p = OUT / "peaks" / f"{sid}.npz"
    if not p.is_file():
        return None
    z = np.load(p, allow_pickle=False)
    keys = json.loads(str(z["keys"]))
    out = {}
    for i, (agent, cls) in enumerate(keys):
        out[(agent, cls)] = {k.split("__", 1)[1]: z[k] for k in z.files if k.startswith(f"{i}__")}
    n = int(z["n_frames"])
    live = np.unpackbits(z["live_bits"], count=n).astype(bool)
    return out, live, json.loads(str(z["meta"]))


def scan(sids: list[str], store: Path = STORE) -> dict:
    """Peaks of every lineup agent seen in any session, over each session's
    stored audio; GPU where `ult_lines.array_module` finds one."""
    from reticle import ability_audio_fit as fit
    from reticle.adjudication import ability_audio as aa
    from reticle.ult_lines import array_module
    _below_normal()
    xp = array_module()
    W = whitener(store)
    inv = inventory(store)
    agents = sorted({a for r in inv.values() if r["lineup"] for v in r["lineup"].values()
                     for a in v if a}, key=canon)
    plays_cache = {}

    def plays():
        if "p" not in plays_cache:
            plays_cache["p"] = fit.montage_plays(store)
        return plays_cache["p"]

    t0 = time.time()
    banks = {a: load_bank(a, W, plays, store) for a in agents}
    bank_s = time.time() - t0
    print(f"banks: {len(banks)} agents, {sum(len(b['templates']) for b in banks.values())} "
          f"templates ({bank_s:.0f} s)", flush=True)
    cost = {}
    for sid in sids or [s for s, r in inv.items() if r["features"] and r["labels"]]:
        s, why = session_audio(sid, store)
        if s is None:
            print(sid, "no audio:", why)
            continue
        c0 = time.process_time()
        w0 = time.time()
        Xw = aa.whiten_frames(s["X"], W["mu"], W["P"], W["ar"])
        w1 = time.time()
        peaks = session_peaks(Xw, s, banks, xp)
        w2 = time.time()
        audio_min = len(s["X"]) / (60.0 * aa.FPS)
        meta = {"version": AUDIO_OTHERS_VERSION, "whitener": W["version"],
                "whitener_sha256": W["sha256"], "stamps": s["stamps"],
                "live_min": s["live_min"], "audio_min": audio_min,
                "agents": agents, "templates": sum(len(b["templates"]) for b in banks.values()),
                "xp": xp.__name__, "whiten_s": w1 - w0, "tracks_s": w2 - w1,
                "cpu_s": time.process_time() - c0, "floor": FLOOR, "peak_gap": aa.PEAK_GAP}
        save_peaks(sid, peaks, s, meta)
        cost[sid] = meta
        print(f"{sid}: {audio_min:.1f} audio min, live {s['live_min']:.1f}, whiten "
              f"{w1 - w0:.1f} s, tracks {w2 - w1:.1f} s ({xp.__name__}), cpu "
              f"{meta['cpu_s']:.1f} s", flush=True)
        del Xw, peaks
    return {"banks_s": bank_s, "cost": cost}


# ----------------------------------------------------------------- truth

def load_catalogue(store: Path = STORE):
    import ability_coverage as ac
    return ac.Catalogue.load(store)


def key_of_slot(cat, agent: str, riot_slot: str) -> str | None:
    """The tray key of an agent's Riot slot, from the wiki harvest."""
    return next((k for (a, k), s in cat.by_key.items()
                 if a == canon(agent) and s == riot_slot), None)


def replay_casts(store: Path = STORE, sightlines_py: str | None = None) -> dict:
    """The replay's casts of all ten players on REPLAY_SESSION in capture time,
    with the caster's side, tray key, distance to the player and the
    player's state; line of sight where a sightline table is given."""
    import ability_coverage as ac
    import replay_abilities as ra
    import riot_ground_truth as rg
    sess, cat = ac.load_sessions([REPLAY_SESSION], store)
    sess = sess[0]
    players = {p["subject"]: p for p in sess["players"]}
    me = next(p["subject"] for p in sess["players"] if p["side"] == "self")
    stored = json.loads((store / "analysis" / "replay-abilities-20261004" /
                         f"{REPLAY_SESSION}.json").read_text(encoding="utf-8"))
    a = float(stored["align"]["a_ms"])
    ex = ra.Export(REPLAY_MATCH)
    rp = ex.rp
    rows = []
    for c in ex.casts()["casts"]:
        slot = REPLAY_SLOT.get(c["slot"])
        p = players.get(c["subject"])
        if slot is None or p is None or c["t_ms"] is None:
            continue
        rows.append({"subject": c["subject"], "agent": p["agent"], "side": p["side"],
                     "slot": slot, "key": key_of_slot(cat, p["agent"], slot),
                     "t_rep": float(c["t_ms"]), "t_cap_ms": float(c["t_ms"]) + a,
                     "location": c.get("location")})
    t = np.array([r["t_rep"] for r in rows])
    lis = rp.sample(me, t)
    alive = rp.alive(me, t)
    cx, cy, cz = (np.full(len(rows), np.nan) for _ in range(3))
    for sub in {r["subject"] for r in rows}:
        m = np.array([r["subject"] == sub for r in rows])
        q = rp.sample(sub, t[m])
        cx[m], cy[m], cz[m] = q["x"], q["y"], q["z"]
    loc = np.array([r["location"] if r["location"] else [np.nan] * 3 for r in rows], float)
    miss = ~np.isfinite(cx)
    cx[miss], cy[miss], cz[miss] = loc[miss, 0], loc[miss, 1], loc[miss, 2]
    d = np.sqrt((cx - lis["x"]) ** 2 + (cy - lis["y"]) ** 2 + (cz - lis["z"]) ** 2) / 100.0
    los = np.full(len(rows), None, object)
    los_basis = "not measured: no --sightlines module given"
    if sightlines_py:
        try:
            spec = importlib.util.spec_from_file_location("sightlines_branch", sightlines_py)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            d_riot = riot_sessions(store)[REPLAY_SESSION]
            ref = rg.Reference(store / "external" / "valorant-api", fetch=False)
            mname = ref.map_of(d_riot["match"]["matchInfo"]["mapId"])["displayName"]
            sl = mod.load(mname.lower(), store)
            if sl is None:
                los_basis = f"no 2D sightline table for {mname}"
            else:
                ok = np.isfinite(cx) & np.isfinite(lis["x"])
                v = sl.los_near(np.stack([cx[ok], cy[ok]], 1), np.stack([lis["x"][ok], lis["y"][ok]], 1))
                los[ok] = v
                los_basis = f"{sl.version} {sl.key} los_near (2D, one-cell tolerance)"
        except Exception as e:  # the branch module is optional and read only
            los_basis = f"sightlines unavailable: {type(e).__name__}: {e}"
    for i, r in enumerate(rows):
        r.update(dist_m=None if not np.isfinite(d[i]) else float(d[i]),
                 listener_alive=bool(alive[i]), los=los[i])
    return {"casts": rows, "align_a_ms": a, "me": me, "los_basis": los_basis,
            "players": sess["players"]}


# ----------------------------------------------------------------- report

def _absent(inv: dict) -> dict[str, set[str]]:
    """{session: canonical agents present} from the lineup owner."""
    return {sid: {canon(a) for v in (r["lineup"] or {}).values() for a in v if a}
            for sid, r in inv.items() if r["lineup"]}


def thresholds(loaded: dict, present: dict[str, set[str]], merge: int) -> dict:
    """Per (agent, class): the dev threshold on dev absent-agent matches, and
    its held absent-agent false-alarm rate per live minute."""
    keys = sorted({k for pk, _l, _m in loaded.values() for k in pk})
    out = {}
    for agent, cls in keys:
        dev, held = [], []
        dev_min = held_min = 0.0
        for sid, (pk, live, meta) in loaded.items():
            if canon(agent) in present.get(sid, set()) or (agent, cls) not in pk:
                continue
            r = pk[(agent, cls)]
            if dev_half(sid):
                dev.append((r["frame"], r["value"]))
                dev_min += meta["live_min"]
            else:
                held.append((r["frame"], r["value"]))
                held_min += meta["live_min"]
        thr = threshold_for(dev, dev_min, NULL_FF_PER_MIN, merge)
        n_held = (sum(len(detections(f, v, thr, merge)) for f, v in held)
                  if thr is not None else None)
        out[(agent, cls)] = {"thr": thr, "dev_null_min": round(dev_min, 2),
                             "held_null_min": round(held_min, 2), "held_fa": n_held,
                             "held_fa_per_min": (round(n_held / held_min, 4)
                                                 if thr is not None and held_min > 0 else None)}
    return out


def evaluate_replay(rc: dict, pk: dict, live: np.ndarray, thr: dict, banks_meta: dict,
                    merge: int, fps: int) -> dict:
    """Per (agent, class) on the replay match: recall of other players' live
    casts, false alarms per live minute, and each cast's paired state."""
    casts = rc["casts"]
    n = len(live)
    for c in casts:
        k = int(c["t_cap_ms"] / 1000.0 * fps)
        c["live"] = bool(0 <= k < n and live[k])
        c["detected"] = False
        c["det_class"] = None
    live_min = float(live.sum()) / (60.0 * fps)
    per = {}
    present = {canon(c["agent"]) for c in casts}
    for (agent, cls), r in sorted(pk.items()):
        if canon(agent) not in present:
            continue
        t = thr.get((agent, cls), {}).get("thr")
        if t is None:
            continue
        keys = class_keys(cls, banks_meta[agent]["groups"])
        idx = detection_index(r["frame"], r["value"], t, merge)
        det_s = r["frame"][idx] / fps
        tru = [i for i, c in enumerate(casts) if canon(c["agent"]) == canon(agent)
               and c["key"] in keys]
        prs = pair(det_s, [casts[i]["t_cap_ms"] / 1000.0 for i in tru])
        paired_det = {i for i, _j, _d in prs}
        for i, j, dt in prs:
            c = casts[tru[j]]
            c["detected"] = True
            c.setdefault("det_classes", []).append(cls)
            c["det_class"] = c["det_class"] or cls
            if "ally" in r:
                vote = side_vote(r["ally"][[idx[i]]], r["enemy"][[idx[i]]])[0]
                if vote is not None:
                    c.setdefault("side_votes", []).append(vote)
        live_o = [i for i in tru if casts[i]["live"] and casts[i]["side"] != "self"]
        per[(agent, cls)] = {
            "agent": agent, "class": cls, "keys": keys, "thr": t, "detections": int(len(idx)),
            "paired": len(prs), "unpaired": int(len(idx) - len(paired_det)),
            "fa_per_min": round((len(idx) - len(paired_det)) / live_min, 4) if live_min else None,
            "truth": len(tru), "truth_live_others": len(live_o),
            "dt_median_s": (round(float(np.median([d for _i, _j, d in prs])), 3) if prs else None)}
    return {"per_class": per, "live_min": live_min}


def ability_rows(casts: list[dict]) -> dict:
    """Per (agent, key): other players' live casts, detected, and within
    A1_NEAR_M; the A1 verdict counts these."""
    rows = {}
    for c in casts:
        if c["side"] == "self" or not c["live"] or c["key"] is None:
            continue
        r = rows.setdefault((c["agent"], c["key"]), {"casts": 0, "detected": 0, "near": 0,
                                                     "near_detected": 0, "by_side": Counter()})
        r["casts"] += 1
        r["detected"] += c["detected"]
        r["by_side"][f"{c['side']}.casts"] += 1
        r["by_side"][f"{c['side']}.detected"] += c["detected"]
        if c["dist_m"] is not None and c["dist_m"] < A1_NEAR_M:
            r["near"] += 1
            r["near_detected"] += c["detected"]
    return rows


def a1_verdict(rows: dict) -> dict:
    ok = [k for k, r in rows.items() if r["near"] >= A1_MIN_CASTS
          and r["near_detected"] / r["near"] >= A1_SHARE]
    elig = [k for k, r in rows.items() if r["near"] >= A1_MIN_CASTS]
    return {"abilities_meeting": len(ok), "eligible": len(elig), "holds": len(ok) >= A1_MIN_ABILITIES,
            "meeting": sorted(f"{a}:{k}" for a, k in ok)}


def distance_curve(casts: list[dict]) -> dict:
    """Recall of other players' live casts per distance bin, and with line of
    sight apart where measured."""
    out = {}
    for c in casts:
        if c["side"] == "self" or not c["live"] or c["key"] is None or c["dist_m"] is None:
            continue
        b = int(distance_bin(c["dist_m"]))
        r = out.setdefault(b, Counter())
        r["casts"] += 1
        r["detected"] += c["detected"]
        r[f"{c['side']}.casts"] += 1
        r[f"{c['side']}.detected"] += c["detected"]
        r["chance"] += c.get("chance", 0.0)
        if c["los"] is not None:
            tag = "los" if c["los"] else "no_los"
            r[f"{tag}.casts"] += 1
            r[f"{tag}.detected"] += c["detected"]
    return {b: dict(v, recall=round(v["detected"] / v["casts"], 4),
                    chance=round(v["chance"] / v["casts"], 4)) for b, v in sorted(out.items())}


def chance_floor(casts: list[dict], per_class: dict, banks_meta: dict) -> None:
    """Each cast's chance of a pairing by a false alarm alone (`chance`, set in
    place): 1 - prod over the classes naming its key of exp(-rate * window),
    the rate each class's unpaired detections per live minute on this match,
    the window PAIR_PRE_S + PAIR_POST_S. Added after the pre-registration, as a
    reading aid; it moves no verdict."""
    win_min = (PAIR_PRE_S + PAIR_POST_S) / 60.0
    rate = defaultdict(float)
    for (agent, cls), v in per_class.items():
        for k in class_keys(cls, banks_meta[agent]["groups"]):
            rate[(canon(agent), k)] += v["fa_per_min"] or 0.0
    for c in casts:
        c["chance"] = float(1.0 - np.exp(-rate[(canon(c["agent"]), c["key"])] * win_min))


def riot_compare(loaded: dict, inv: dict, thr: dict, banks_meta: dict, cat, merge: int,
                 store: Path = STORE) -> tuple[list[dict], dict]:
    """Per match and (agent, class): detections against Riot's per-player
    totals, the sides apart where the agent plays one side only; and the
    side vote's agreement with that side. Live minutes beside each."""
    import ability_coverage as ac
    import riot_ground_truth as rg
    recs = riot_sessions(store)
    ref = rg.Reference(store / "external" / "valorant-api", fetch=False)
    ident = rg.identify_player(recs, store)
    rows, votes = [], Counter()
    for sid, (pk, live, meta) in sorted(loaded.items()):
        d = recs.get(sid)
        idn = rg.resolve_lineup_player(d, ident[sid], ref) if d else {}
        if not idn.get("subject"):
            continue
        players = ac.riot_players(d, idn["subject"], ref.agent)
        for (agent, cls), r in sorted(pk.items()):
            ps = [p for p in players if canon(p["agent"]) == canon(agent)]
            t = thr.get((agent, cls), {}).get("thr")
            if not ps or t is None:
                continue
            keys = class_keys(cls, banks_meta[agent]["groups"])
            slots = [cat.by_key.get((canon(agent), k)) for k in keys]
            riot = sum(p["casts"][s] for p in ps for s in slots if s)
            idx = detection_index(r["frame"], r["value"], t, merge)
            sides = sorted({"ally" if p["side"] in ("self", "ally") else "enemy" for p in ps})
            rows.append({"session": sid, "dev": dev_half(sid), "agent": agent, "class": cls,
                         "keys": keys, "sides": sides, "players": len(ps),
                         "self": any(p["side"] == "self" for p in ps),
                         "riot": riot, "detections": int(len(idx)),
                         "live_min": round(meta["live_min"], 2)})
            if "ally" in r and len(sides) == 1:
                v = side_vote(r["ally"][idx], r["enemy"][idx])
                for x in v:
                    votes[(agent, cls, sides[0], x)] += 1
    return rows, votes


def gain_rows(loaded: dict, thr: dict, banks_meta: dict, cat, merge: int,
              store: Path = STORE) -> list[dict]:
    """Casts gained over today's coverage: the coverage survey's tally of the
    stored channels, then again with this prototype's detections added as one
    more channel (a per-round union, capped at Riot's count). Agents on both
    sides stay unresolved, the arbiter's question."""
    import ability_coverage as ac
    from reticle.adjudication.ability_audio import FPS
    from reticle.rounds import round_containing
    from reticle.store import Store
    sessions, _cat = ac.load_sessions(sorted(loaded), store)
    st = Store(store)
    acc = {}
    for s in sessions:
        if "refused" in s:
            continue
        sid = s["session"]
        man = st.read_manifest(sid)
        table = st.read_rounds(sid, man["ingested_at"][:10])
        rounds = table.to_pylist() if table is not None else []

        def round_of(t, rounds=rounds):
            r = round_containing(t, rounds)
            return r["round_no"] if r else None

        pk = loaded[sid][0]
        w = []
        side_of = {}
        for p in s["players"]:
            side_of.setdefault(canon(p["agent"]), set()).add(
                "ally" if p["side"] in ("self", "ally") else "enemy")
        for (agent, cls), r in pk.items():
            t = thr.get((agent, cls), {}).get("thr")
            sides = side_of.get(canon(agent))
            keys = class_keys(cls, banks_meta[agent]["groups"])
            if t is None or not sides or len(keys) != 1:
                continue
            slot = cat.by_key.get((canon(agent), keys[0]))
            side = next(iter(sides)) if len(sides) == 1 else "both"
            for f in detections(r["frame"], r["value"], t, merge):
                w.append(ac._w("audio_others", side, agent, slot, f * 1000.0 / FPS,
                               ("audio_others", agent, cls, int(f))))
        base = s["tally"]["cells"]
        new = ac.tally(s["witnesses"] + w, s["players"], round_of)["cells"]
        sub = {p["subject"]: p for p in s["players"]}
        for key, cell in new.items():
            p = sub[key[0]]
            if p["side"] == "self":
                continue
            a = acc.setdefault((p["side"], p["agent"], key[1]), Counter())
            a["riot"] += cell["riot"]
            a["today"] += min(base[key]["any"], cell["riot"])
            a["with_audio"] += min(cell["any"], cell["riot"])
            a["audio_alone"] += min(cell["channels"].get("audio_others", 0), cell["riot"])
            a["detections"] += cell["channels"].get("audio_others", 0)
        # the false alarms each one-side class should give here: its held
        # absent-agent rate times this match's live minutes
        live_min = loaded[sid][2]["live_min"]
        for (agent, cls), r in pk.items():
            sides = side_of.get(canon(agent))
            keys = class_keys(cls, banks_meta[agent]["groups"])
            v = thr.get((agent, cls), {})
            if not sides or len(sides) != 1 or len(keys) != 1 or v.get("held_fa_per_min") is None:
                continue
            slot = cat.by_key.get((canon(agent), keys[0]))
            ps = [p for p in s["players"] if canon(p["agent"]) == canon(agent)
                  and p["side"] != "self"]
            if not ps:
                continue
            acc.setdefault((ps[0]["side"], ps[0]["agent"], slot), Counter())[
                "expected_false"] += v["held_fa_per_min"] * live_min
    out = []
    for (side, agent, slot), a in acc.items():
        g = a["with_audio"] - a["today"]
        out.append({"side": side, "agent": agent, "slot": slot, "ability": cat.name(agent, slot),
                    **a, "expected_false": round(a["expected_false"], 1), "gained": g,
                    "gained_net": round(max(0.0, g - a["expected_false"]), 1)})
    return sorted(out, key=lambda r: (-r["gained_net"], -r["gained"], r["side"], str(r["agent"]),
                                      r["slot"]))


def build_report(store: Path = STORE, sightlines_py: str | None = None) -> dict:
    from reticle.adjudication.ability_audio import FPS
    inv = inventory(store)
    loaded = {}
    for sid in inv:
        got = load_peaks(sid)
        if got is not None:
            loaded[sid] = got
    present = _absent(inv)
    merge = int(round(MERGE_S * FPS))
    thr = thresholds(loaded, present, merge)
    W = whitener(store)
    agents = sorted({a for _sid, (pk, _l, _m) in loaded.items() for a, _c in pk}, key=canon)
    banks_meta = {}
    for a in agents:
        p = bank_path(a, W)
        banks_meta[a] = json.loads(str(np.load(p, allow_pickle=False)["meta"]))
    cat = load_catalogue(store)
    # A2: every class's held absent-agent rate
    held = [v["held_fa_per_min"] for v in thr.values() if v["held_fa_per_min"] is not None]
    a2 = {"classes": len(held), "max": max(held) if held else None,
          "median": float(np.median(held)) if held else None,
          "below_bar": int(sum(h < A2_FA_PER_MIN for h in held)),
          "holds": bool(held) and all(h < A2_FA_PER_MIN for h in held)}
    rep = {"version": AUDIO_OTHERS_VERSION, "sessions": sorted(loaded),
           "dev": sorted(s for s in loaded if dev_half(s)),
           "held": sorted(s for s in loaded if not dev_half(s)),
           "inventory": inv, "thresholds": {f"{a}|{c}": v for (a, c), v in thr.items()},
           "A2": a2}
    if REPLAY_SESSION in loaded:
        rc = replay_casts(store, sightlines_py)
        pk, live, _meta = loaded[REPLAY_SESSION]
        ev = evaluate_replay(rc, pk, live, thr, banks_meta, merge, FPS)
        chance_floor(rc["casts"], ev["per_class"], banks_meta)
        rows = ability_rows(rc["casts"])
        dets = sum(v["detections"] for v in ev["per_class"].values())
        prd = sum(v["paired"] for v in ev["per_class"].values())
        rep["replay"] = {
            "session": REPLAY_SESSION, "align_a_ms": rc["align_a_ms"], "los_basis": rc["los_basis"],
            "live_min": ev["live_min"], "detections": dets, "paired": prd,
            "precision": round(prd / dets, 4) if dets else None,
            "casts": Counter(f"{c['side']}.{'live' if c['live'] else 'not_live'}" for c in rc["casts"]),
            "per_class": {f"{a}|{c}": v for (a, c), v in ev["per_class"].items()},
            "per_ability": {f"{a}|{k}": dict(v, by_side=dict(v["by_side"]),
                                             recall=round(v["detected"] / v["casts"], 4),
                                             near_recall=(round(v["near_detected"] / v["near"], 4)
                                                          if v["near"] else None))
                            for (a, k), v in sorted(rows.items())},
            "A1": a1_verdict(rows), "distance": distance_curve(rc["casts"]),
            "side_votes": dict(Counter(f"{c['agent']}|{c['key']}|{c['side']}|{v}"
                                       for c in rc["casts"] for v in c.get("side_votes", []))),
            "by_side": {sd: {"casts": sum(1 for c in rc["casts"] if c["side"] == sd and c["live"]),
                             "detected": sum(1 for c in rc["casts"] if c["side"] == sd and c["live"]
                                             and c["detected"])}
                        for sd in ("self", "ally", "enemy")}}
    rows, votes = riot_compare(loaded, inv, thr, banks_meta, cat, merge, store)
    rep["riot"] = rows
    rep["side_votes_one_side"] = {"|".join(map(str, k)): v for k, v in sorted(votes.items(), key=str)}
    agree = sum(n for (_a, _c, side, vote), n in votes.items() if vote == side)
    voted = sum(n for (_a, _c, _s, vote), n in votes.items() if vote is not None)
    rep["side_agreement"] = {"agree": agree, "voted": voted,
                             "share": round(agree / voted, 4) if voted else None}
    rep["gain"] = gain_rows(loaded, thr, banks_meta, cat, merge, store)
    cost = [m for _pk, _l, m in loaded.values()]
    am = sum(m["audio_min"] for m in cost)
    rep["cost"] = {"audio_min": round(am, 1), "templates": cost[0]["templates"] if cost else None,
                   "xp": sorted({m["xp"] for m in cost}),
                   "tracks_s_per_audio_min": round(sum(m["tracks_s"] for m in cost) / am, 3) if am else None,
                   "whiten_s_per_audio_min": round(sum(m["whiten_s"] for m in cost) / am, 3) if am else None,
                   "cpu_s_per_audio_min": round(sum(m["cpu_s"] for m in cost) / am, 3) if am else None}
    return rep


def record_ledger(rep: dict) -> list[str]:
    from reticle import metrics
    deps = {"version": AUDIO_OTHERS_VERSION, "whitener": WHITENER_FROM,
            "code": metrics.fingerprint(detections, detection_index, threshold_for, pair,
                                        side_vote, thresholds, evaluate_replay, ability_rows,
                                        a1_verdict, distance_curve, chance_floor, riot_compare, gain_rows,
                                        session_peaks, bank_labels, FLOOR=FLOOR, MERGE_S=MERGE_S,
                                        PAIR_PRE_S=PAIR_PRE_S, PAIR_POST_S=PAIR_POST_S,
                                        NULL_FF_PER_MIN=NULL_FF_PER_MIN)}
    ctx = {"sessions": len(rep["sessions"]), "dev": rep["dev"], "held": rep["held"]}
    out = []
    a2 = rep["A2"]
    metrics.record("audio_others", part="null", values={
        "classes": a2["classes"], "held_fa_per_min_max": a2["max"],
        "held_fa_per_min_median": a2["median"], "below_bar": a2["below_bar"],
        "A2_holds": int(a2["holds"])}, deps=deps, context=ctx)
    out.append("audio_others/null")
    rp = rep.get("replay")
    if rp:
        v = {"live_min": round(rp["live_min"], 2), "detections": rp["detections"],
             "paired": rp["paired"], "A1_meeting": rp["A1"]["abilities_meeting"],
             "A1_eligible": rp["A1"]["eligible"], "A1_holds": int(rp["A1"]["holds"])}
        for sd, x in rp["by_side"].items():
            v[f"{sd}.casts"] = x["casts"]
            v[f"{sd}.detected"] = x["detected"]
        for b, x in rp["distance"].items():
            v[f"dist{b}.casts"] = x["casts"]
            v[f"dist{b}.detected"] = x["detected"]
            v[f"dist{b}.chance"] = x["chance"]
            for sd in ("ally", "enemy"):
                if f"{sd}.casts" in x:
                    v[f"dist{b}.{sd}.casts"] = x[f"{sd}.casts"]
                    v[f"dist{b}.{sd}.detected"] = x[f"{sd}.detected"]
            for tag in ("los", "no_los"):
                if f"{tag}.casts" in x:
                    v[f"dist{b}.{tag}.casts"] = x[f"{tag}.casts"]
                    v[f"dist{b}.{tag}.detected"] = x[f"{tag}.detected"]
        metrics.record("audio_others", part="replay", session=REPLAY_SESSION, values=v,
                       deps=deps, context=dict(ctx, los_basis=rp["los_basis"]))
        out.append(f"audio_others/replay@{REPLAY_SESSION}")
        va = {}
        for k, x in rp["per_ability"].items():
            kk = k.replace(" ", "_").replace("/", "_").replace("|", ":")
            va[f"{kk}.casts"] = x["casts"]
            va[f"{kk}.detected"] = x["detected"]
            va[f"{kk}.near"] = x["near"]
            va[f"{kk}.near_detected"] = x["near_detected"]
        for k, x in rp["per_class"].items():
            kk = k.replace(" ", "_").replace("/", "_").replace("|", ":")
            va[f"{kk}.fa_per_min"] = x["fa_per_min"]
        metrics.record("audio_others", part="replay_abilities", session=REPLAY_SESSION,
                       values=va, deps=deps, context=ctx)
        out.append(f"audio_others/replay_abilities@{REPLAY_SESSION}")
    g = {}
    for r in rep["gain"]:
        if r["gained_net"] <= 0:
            continue
        k = f"{r['side']}:{r['agent']}:{r['slot']}".replace(" ", "_").replace("/", "_")
        g[f"{k}.gained"] = r["gained"]
        g[f"{k}.gained_net"] = r["gained_net"]
        g[f"{k}.expected_false"] = r["expected_false"]
        g[f"{k}.riot"] = r["riot"]
        g[f"{k}.today"] = r["today"]
    tot = Counter()
    for r in rep["gain"]:
        tot[f"{r['side']}.riot"] += r["riot"]
        tot[f"{r['side']}.today"] += r["today"]
        tot[f"{r['side']}.with_audio"] += r["with_audio"]
        tot[f"{r['side']}.gained_net"] += r["gained_net"]
    metrics.record("audio_others", part="gain", values={**dict(tot), **g}, deps=deps, context=ctx)
    out.append("audio_others/gain")
    metrics.record("audio_others", part="cost", values={k: v for k, v in rep["cost"].items()
                                                        if not isinstance(v, list)},
                   deps=deps, context=dict(ctx, xp=rep["cost"]["xp"]))
    out.append("audio_others/cost")
    sv = Counter({"agree": rep["side_agreement"]["agree"], "voted": rep["side_agreement"]["voted"]})
    for k, n in rep["side_votes_one_side"].items():
        a_, c_, side, vote = k.split("|")
        sv[f"{a_.replace('/', '_')}:{c_}.{side}.vote_{vote}"] += n
    metrics.record("audio_others", part="side", values=dict(sv), deps=deps, context=ctx)
    out.append("audio_others/side")
    return out


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory")
    sp = sub.add_parser("scan")
    sp.add_argument("sessions", nargs="*")
    rp = sub.add_parser("report")
    rp.add_argument("--record", action="store_true")
    rp.add_argument("--json", type=Path)
    rp.add_argument("--sightlines", help="the branch's prototypes/sightlines.py (read only)")
    a = ap.parse_args(argv)
    _below_normal()
    if a.cmd == "inventory":
        print(json.dumps(inventory(), indent=1, default=_default))
    elif a.cmd == "scan":
        res = scan(a.sessions)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"scan-cost-{time.strftime('%Y%m%dT%H%M%S')}.json").write_text(
            json.dumps(res, indent=1, default=_default), encoding="utf-8")
    else:
        rep = build_report(sightlines_py=a.sightlines)
        path = a.json or OUT / "report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rep, indent=1, default=_default), encoding="utf-8")
        print("report ->", path)
        if a.record:
            print("ledger:", record_ledger(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
