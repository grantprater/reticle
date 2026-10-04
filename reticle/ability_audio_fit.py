r"""Fit and evaluate the audio witness's parameter set from stored audio,
through the wired scorer (`adjudication.ability_audio`, which owns the
ownership entry `ability-audio`; this module is its fit tool).

    reticle ability-audio-fit --gate G.json [--supply SID=AGENT] [--audio-dir DIR]
    reticle ability-audio-fit --gate-in G.json --fit ROOT [--audio-dir DIR]
    reticle ability-audio-fit --gate-in G.json --eval ROOT [--json OUT] [--audio-dir DIR]

`--gate` computes the gate's verdicts (`ability_timeline.player_tray_casts`,
with the kit witness's spans) once per session with stored audio-gate
labels, and writes them with the stream stamps it read, so the fit and the
evaluation read one stored state while other runs rewrite the store. The
player's agent is the identity arbiter's; `--supply SID=AGENT` names it for
a session where the arbiter names none, and the snapshot records that basis.
`--audio-dir` names directories holding `features/<sid>.npz` and
`labels/<sid>.json` for sessions whose log-mel the store lacks; their stamps
say so. Decodes no video and no capture audio; the fit decodes the game's
reference files.

**The split** is `ability_audio.split_sessions`, declared before scoring:
per agent the sessions sorted by id, even positions dev and odd held; an
agent with one session split at its frame midpoint. Demos are always held.

**One whitener** is fitted on the background of every agent's dev sessions
(`ability_audio.fit_whitener`), so an agent with no own match (Omen,
Deadlock) is scored zero-shot from the game's files. **Thresholds** are each
class's level at one false fire per live minute over every dev session.

**The references** are the store's manifest (`ability-audio-ref-0.2.0`)
mapped by the ability's display name to the tray slot
(`lineup.abilities_for`), less:

* movement and footstep folders (`Mvmnt`, `Movement`, `FS_*`), no cast;
* rows the manifest leaves unmapped, unless the player's belief (BELIEF) or
  dev evidence (EVIDENCE) names their ability;
* shared files: a file whose sound event the ability montages of two or
  more abilities play (`ability_audio.shared_reference_mask`, over the
  montage export MONTAGES). On build `release-13.06-shipping-18-5590001`
  only Sova's Shock Bolt and Recon Bolt equips share events
  [domain:abilities/sova-bolt-equips-share-sounds].

It replaces the split, the reference rule and the fit that lived in
`prototypes/ability_audio_eval.py` (`ability-audio-params-0.1.1`); that
script now passes this command the probe's inputs.

`--eval` scores the dev and held sessions of the set's split, the
player-verified casts (`labels/tray_object`) inside them, and the demos
(`labels/demo_cast_class`) with stored log-mel, and calibrates the margin to
P(right) on dev (`calibrate_margin`), judged on held.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

#: The reference table and its version, under the store root.
REF_DIR = Path("reference") / "game-files" / "audio"
MANIFEST = REF_DIR / "manifest-0.2.0.jsonl"
REF_VERSION = "ability-audio-ref-0.2.0"
#: The ability montages exported from the game, under the store root.
MONTAGE_BUILD = "release-13.06-shipping-18-5590001"
MONTAGES = (Path("reference") / "game-files" / MONTAGE_BUILD / "ability-anims"
            / "manifest-montages.jsonl")
#: The player's verified casts and the demos' cast census, under the store root.
VERIFIED_DIR = Path("labels") / "tray_object"
DEMO_DIR = Path("labels") / "demo_cast_class"
#: Folders whose files are movement, not a cast.
MOVEMENT = ("Mvmnt", "Movement")
#: The player's belief of 2026-10-03: Reyna's unmapped Abil_E folder is Dismiss.
BELIEF = {("Reyna", "Abil_E"): ("Dismiss", "player_belief_20261003")}
#: Unmapped rows mapped on evidence (2026-10-03): (agent, folder, file-name
#: prefixes, ability, basis). The name's token says the ability, and on dev
#: sessions alone the files fire only on that ability's casts.
EVIDENCE = [
    ("Skye", "Abil_E", ("Guide_Taz_", "Guide_AbilE_", "Guide_Abil_E_Attack"), "Trailblazer",
     "player_20261003+name_token_taz+dev_cooccurrence_20261003"),
    ("Sova", "Abil_X", ("Hunter_S0_AB_X_SuperBolt_OnBeam_",), "Hunter's Fury",
     "name_token_onbeam+dev_cooccurrence_20261003"),
]
#: Calibration: an agent's own margin fit needs this many right and wrong dev casts.
CALIB_MIN = 3
#: The P(right) at which a verdict counts as accepted in the report.
ACCEPT_P = 0.95


def sid_of(name: str) -> str:
    return name.split(":")[0]


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def montage_plays(store_root) -> dict[str, set]:
    """{"<codename>|<event>": the abilities whose montages play it}, from the
    montage export: an ability is the montage's `_S0_<token>_` (a slot
    token) or else its `Ability_<folder>`."""
    root = Path(store_root)
    base = (root / MONTAGES).parent
    plays: dict[str, set] = {}
    for line in (root / MONTAGES).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        m = re.match(r"ShooterGame/Content/Characters/([^/]+)/S0/Ability_([^/]+)/", r["game_path"])
        if not m or not r.get("output"):
            continue
        t = re.search(r"_S0_([A-Za-z0-9]+)_", r["game_path"].split("/")[-1])
        tok = t.group(1) if t and len(t.group(1)) <= 2 else m.group(2)
        text = (base / r["output"]).read_text(encoding="utf-8")
        for ev in set(re.findall(r"(Play_[A-Za-z0-9_]+)", text)):
            plays.setdefault(f"{m.group(1)}|{ev}", set()).add(tok)
    return plays


def references(store_root, agent: str, plays: dict[str, set]) -> tuple[list[dict], dict]:
    """The agent's reference rows with their class (a tray slot), and what
    the rule kept and left out."""
    from .adjudication.ability_audio import shared_reference_mask
    from .lineup import abilities_for
    root = Path(store_root)
    kit = abilities_for(agent, str(root))
    slot_of = {v: k for k, v in kit.items()}
    out, why = [], Counter()
    for line in (root / MANIFEST).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("agent") != agent:
            continue
        parts = (r.get("folder") or "").split("/")
        if parts[0] in MOVEMENT or any(p.startswith("FS_") for p in parts):
            why["movement_left_out"] += 1
            continue
        ability, basis = r.get("ability"), r.get("map_basis")
        if ability is None:
            belief = next((v for (a, f), v in BELIEF.items() if a == agent and f in parts), None)
            if belief:
                ability, basis = belief
        if ability is None:
            name = r["flac"].split("/")[-1]
            hit = next((e for e in EVIDENCE if e[0] == agent and e[1] in parts
                        and name.startswith(e[2])), None)
            if hit:
                ability, basis = hit[3], hit[4]
        if ability is None:
            why["unmapped_left_out"] += 1
            continue
        cls = slot_of.get(ability)
        if cls is None:
            why[f"not_in_kit:{ability}"] += 1
            continue
        out.append({"flac": r["flac"], "class": cls, "ability": ability, "basis": basis,
                    "events": [f"{r.get('codename')}|{e.split('/')[-1]}"
                               for e in (r.get("events") or [])]})
    keep = shared_reference_mask([o["events"] for o in out], plays)
    shared = [o["flac"] for o, k in zip(out, keep) if not k]
    out = [o for o, k in zip(out, keep) if k]
    why["shared_left_out"] += len(shared)
    for o in out:
        why[f"{o['class']}:{o['basis']}"] += 1
    return out, {"kit": kit, "counts": dict(sorted(why.items())), "shared_files": shared,
                 "slots_without_reference": sorted(set(kit) - {o["class"] for o in out})}


# ---------------------------------------------------------------------------
# The gate, once
# ---------------------------------------------------------------------------

def gate_snapshot(store, sids: list[str], supplied: dict[str, str]) -> dict:
    """Per session the gate's rows, the player's agent and its basis, the
    kit spans and the stamps read."""
    from .ability_timeline import player_tray_casts, stored_gate_inputs
    from .adjudication.ability_state import player_agent_verdict
    from .adjudication.ult_cast import DROP_FIELDS
    from .lineup import load_lineup
    res = {}
    for sid in sids:
        man = store.read_manifest(sid)
        date = man["ingested_at"][:10]   # the store's session date (cli._date_of)
        stored = store.read_events("tray_drop", sid)
        cov = next((r for r in stored if r.get("kind") == "coverage"), {})
        drops = [{k: r[k] for k in DROP_FIELDS if k in r} for r in stored
                 if r.get("kind") == "drop"]
        rounds = store.read_rounds(sid, date).to_pylist()
        verdict = player_agent_verdict(load_lineup(sid, store.root), sid)
        who, why = verdict["agent"], "identity arbiter"
        if who is None and sid in supplied:
            who, why = supplied[sid], f"supplied on the command line; the arbiter names none " \
                                      f"({verdict.get('status')})"
        if who is None:
            print(f"{sid}: the arbiter names no agent -- left out")
            continue
        gate, stamps = stored_gate_inputs(store, sid, date, rounds, who)
        rows = player_tray_casts(drops, rounds=rounds, **gate)
        res[sid] = {"agent": who, "agent_basis": why, "arbiter_agent": verdict["agent"],
                    "path": man["source"].get("path"),
                    "stamps": {**stamps, "tray_drop": cov.get("tray_version")},
                    "kit_spans": gate["kit_spans"],
                    "rows": [{"t_ms": r["t_ms"], "slot": r["slot"],
                              "player_cast": r["player_cast"], "reason": r["reason"]}
                             for r in rows]}
        print(sid, who, "drops", len(rows), "casts", sum(r["player_cast"] for r in rows),
              flush=True)
    return res


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def audio_paths(store_root, sid: str, audio_dirs) -> dict:
    """The log-mel and labels of a session: the store's, else the first
    `audio_dirs` entry holding them; {} where the store has them."""
    from .ability_timeline import AUDIO_GATE_DIR
    if (Path(store_root) / AUDIO_GATE_DIR / "features" / f"{sid}.npz").is_file():
        return {}
    for d in audio_dirs or ():
        fp = Path(d) / "features" / f"{sid}.npz"
        if fp.is_file():
            return {"features_path": fp, "labels_path": Path(d) / "labels" / f"{sid}.json"}
    return {}


def verified_casts(store_root) -> dict[str, list[dict]]:
    """{session: the player's verified casts}: time and slot."""
    out: dict[str, list[dict]] = {}
    for f in sorted((Path(store_root) / VERIFIED_DIR).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out.setdefault(r["session_id"], []).append(
                    {"t_ms": float(r["t_drop_s"]) * 1000.0, "slot": r["slot"], "key": r["key"]})
    return out


def match_session(store_root, name: str, gate: dict, audio_dirs=(), verified=None):
    """(the stored audio of a match session or half, None) or (None, why)."""
    from .ability_timeline import audio_session
    from .adjudication.ability_audio import FPS
    sid = sid_of(name)
    g = gate[sid]
    where = audio_paths(store_root, sid, audio_dirs)
    if ":" in name:
        from .ability_timeline import AUDIO_GATE_DIR
        fp = where.get("features_path") or (Path(store_root) / AUDIO_GATE_DIR / "features"
                                            / f"{sid}.npz")
        with np.load(fp, allow_pickle=True) as z:
            n = len(z["ok"])
        mid = n / (2 * FPS)
        where["span_s"] = (0.0, mid) if name.endswith(":first") else (mid, n / FPS)
    s, why = audio_session(store_root, sid, g["rows"], g["agent"], g["kit_spans"],
                           features_path=where.get("features_path"),
                           labels_path=where.get("labels_path"), span_s=where.get("span_s"))
    if s is None:
        return None, why
    lo, hi = where.get("span_s") or (0.0, np.inf)
    s["span_s"] = where.get("span_s")
    s["verified"] = [dict(v, frame=int(v["t_ms"] / 1000.0 * FPS))
                     for v in (verified or {}).get(sid, []) if lo <= v["t_ms"] / 1000.0 < hi]
    return s, None


def demo_truth(store_root, sid: str) -> list[dict]:
    """A demo's census casts, one per key."""
    rows, seen = [], set()
    p = Path(store_root) / DEMO_DIR / f"{sid}.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["key"] not in seen:
                seen.add(r["key"])
                rows.append({"t_ms": float(r["t_ms"]), "slot": r["slot"], "key": r["key"],
                             "agent": r["agent"]})
    return rows


def demo_census_sessions(store_root, audio_dirs=()) -> dict[str, str]:
    """{demo session: its agent} for every demo census with stored log-mel."""
    from .ability_timeline import AUDIO_GATE_DIR
    out = {}
    for p in sorted((Path(store_root) / DEMO_DIR).glob("*.jsonl")):
        sid = p.stem
        has = ((Path(store_root) / AUDIO_GATE_DIR / "features" / f"{sid}.npz").is_file()
               or any((Path(d) / "features" / f"{sid}.npz").is_file() for d in audio_dirs or ()))
        truth = demo_truth(store_root, sid)
        if has and truth:
            out[sid] = truth[0]["agent"]
    return out


def demo_session(store_root, sid: str, audio_dirs=()):
    """A demo's stored audio: every frame with audio is live; the null
    frames are live and unexplained by a drop or a census cast; the casts
    are the census's; every tray drop bounds a cast's window."""
    from .ability_timeline import AUDIO_GATE_DIR, features_stamp
    from .adjudication.ability_audio import FPS, explained, session_frames
    root = Path(store_root)
    fp = root / AUDIO_GATE_DIR / "features" / f"{sid}.npz"
    if not fp.is_file():
        fp = audio_paths(root, sid, audio_dirs).get("features_path")
    z = np.load(fp, allow_pickle=True)
    med = z["med"] if "med" in z.files else np.median(z["L"].astype(np.float32), axis=0)
    X = session_frames(z["L"], med)
    n = len(X)
    live = z["ok"][:n].astype(bool)
    drops = [r for r in (json.loads(x) for x in (root / "events" / "tray_drop" / f"{sid}.jsonl")
                         .read_text(encoding="utf-8").splitlines() if x.strip())
             if r.get("kind") == "drop"]
    truth = demo_truth(root, sid)
    code = explained(n, [d["t_ms"] / 1000.0 for d in drops] + [t["t_ms"] / 1000.0 for t in truth],
                     [], [])
    return {"X": X, "live": live, "code": code, "bg": live & (code == 3),
            "casts": [{"t_ms": t["t_ms"], "slot": t["slot"], "frame": int(t["t_ms"] / 1000.0 * FPS)}
                      for t in truth],
            "neighbours": np.array([int(d["t_ms"] / 1000.0 * FPS) for d in drops], int),
            "verified": [], "live_min": float(live.sum()) / (60.0 * FPS),
            "stamps": {"audio_features": features_stamp(z, fp), "features_path": Path(fp).as_posix(),
                       "tray_drop": "events/tray_drop"}}


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------

def fit_params(store_root, out_root, gate: dict, audio_dirs=(), agents=None, xp=np) -> Path:
    """Fit and save a parameter set (`ABILITY_AUDIO_PARAMS_VERSION`) under
    `out_root`: one whitener over every dev session, each agent's
    references whitened by it, and each class's threshold over every dev
    session. `agents` defaults to the gate's agents and the demos'."""
    from .adjudication import ability_audio as aa
    from .version import ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION
    root = Path(store_root)
    split = aa.split_sessions(_sessions_by_agent(gate))
    dev = sorted(n for sp in split.values() for n in sp["dev"])
    agents = sorted(agents or set(split) | set(demo_census_sessions(root, audio_dirs).values()))

    def dev_sessions():
        for n in dev:
            s, why = match_session(root, n, gate, audio_dirs)
            if s is None:
                raise SystemExit(f"{n}: {why}")
            yield n, s

    t0 = time.time()
    stamps = {}

    def pairs():
        for n, s in dev_sessions():
            stamps[n] = {**gate[sid_of(n)]["stamps"], **s["stamps"]}
            yield s["X"], s["bg"]

    W = aa.fit_whitener(pairs())
    print(f"whitener: {len(dev)} dev sessions, {W['bg_frames']} null frames, cond "
          f"{W['cond']:.0f}, AR {np.round(W['ar'], 4)} ({time.time() - t0:.0f} s)", flush=True)
    plays = montage_plays(root)
    per = {}
    for agent in agents:
        refs, rule = references(root, agent, plays)
        temps, labels, files = [], [], []
        for r in refs:
            T = aa.template(aa.reference_logmel(root / REF_DIR / r["flac"]))
            if T is None:
                continue
            temps.append(aa.whiten_template(T, W["P"], W["ar"]))
            labels.append(r["class"])
            files.append({"flac": r["flac"], "ability": r["ability"], "basis": r["basis"]})
        per[agent] = {"temps": temps, "labels": labels, "files": files, "rule": rule,
                      "peaks": {}}
        print(f"{agent}: {len(temps)} templates {dict(Counter(labels))}, "
              f"shared left out {len(rule['shared_files'])}", flush=True)
    live_min = 0.0
    for n, s in dev_sessions():
        t1 = time.time()
        Xw = aa.whiten_frames(s["X"], W["mu"], W["P"], W["ar"])
        for agent, a in per.items():
            if not a["temps"]:
                continue
            for c, v in aa.class_tracks(Xw, a["temps"], a["labels"], s["bg"], xp).items():
                a["peaks"].setdefault(c, []).append(aa.false_fire_peaks(v, s["live"], s["code"]))
        live_min += s["live_min"]
        print(f"  thresholds: {n} ({time.time() - t1:.0f} s)", flush=True)
    agents_out = {}
    for agent, a in per.items():
        if not a["temps"]:
            print(f"{agent}: no references -- no parameters")
            continue
        thr = {c: aa.threshold_at(v, live_min) for c, v in a["peaks"].items() if c != aa.NONE}
        agents_out[agent] = {
            "mu": W["mu"], "P": W["P"], "ar": W["ar"], "templates": a["temps"],
            "labels": a["labels"], "files": a["files"], "slots": a["rule"]["kit"],
            "thresholds": thr,
            "dev": [{"name": n, "path": gate[sid_of(n)]["path"], "stamps": stamps.get(n),
                     "agent": gate[sid_of(n)]["agent"],
                     "agent_basis": gate[sid_of(n)]["agent_basis"]} for n in dev],
            "fit": {"whitener": "pooled", "bg_frames": W["bg_frames"],
                    "band_condition": round(W["cond"], 1),
                    "ar2": [round(float(x), 5) for x in W["ar"]], "live_min": round(live_min, 2),
                    "templates": len(a["temps"]), "by_class": dict(Counter(a["labels"])),
                    "reference_rule_counts": a["rule"]["counts"],
                    "shared_files": a["rule"]["shared_files"],
                    "slots_without_reference": a["rule"]["slots_without_reference"],
                    "own_dev_sessions": split.get(agent, {}).get("dev", [])}}
        print(f"{agent}: thresholds { {k: round(v, 3) for k, v in thr.items()} }", flush=True)
    prov = {"ability_audio_version": ABILITY_AUDIO_VERSION,
            "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fitted_by": "reticle ability-audio-fit --fit",
            "reference": {"manifest": MANIFEST.as_posix(), "ref_version": REF_VERSION,
                          "rule": "by the ability's display name to the tray slot "
                                  "(lineup.abilities_for); movement and footstep folders "
                                  "left out; unmapped rows left out unless a belief or an "
                                  "evidence map names them",
                          "shared_rule": "a file whose sound event the ability montages of two "
                                         "or more abilities play is left out "
                                         "(ability_audio.shared_reference_mask)",
                          "montages": {"manifest": MONTAGES.as_posix(), "build": MONTAGE_BUILD},
                          "beliefs": [{"agent": a, "folder": f, "ability": v[0], "basis": v[1]}
                                      for (a, f), v in BELIEF.items()],
                          "evidence_maps": [{"agent": e[0], "folder": e[1], "prefixes": list(e[2]),
                                             "ability": e[3], "basis": e[4]} for e in EVIDENCE]},
            "split": split,
            "split_basis": "ability_audio.split_sessions: per agent the sessions sorted by id, "
                           "even positions dev, odd held; one session split at its frame "
                           "midpoint; demos always held",
            "whitening": {"pooled_over": dev, "shrink": aa.SHRINK, "eig_floor": aa.EIG_FLOOR,
                          "ar_min_run": aa.AR_MIN_RUN, "bands_hz": [aa.BAND_LO, aa.BAND_HI]},
            "template_rule": {"active_db": aa.ACTIVE_DB, "floor_db": aa.TEMPLATE_DB,
                              "max_s": aa.MAX_TEMPLATE_S},
            "candidate_rule": "the player's kit slots with references",
            "threshold_rule": f"{aa.THRESHOLD_FF_PER_MIN} false fire per live minute over every "
                              f"dev session's unexplained live frames, peaks {aa.PEAK_GAP} "
                              f"frames apart",
            "gate": {sid: {"agent": g["agent"], "agent_basis": g["agent_basis"]}
                     for sid, g in gate.items()}}
    d = aa.save_params(out_root, ABILITY_AUDIO_PARAMS_VERSION, agents_out, prov)
    print("params ->", d)
    return d


def _sessions_by_agent(gate: dict) -> dict[str, list[str]]:
    by: dict[str, list[str]] = {}
    for sid, g in gate.items():
        by.setdefault(g["agent"], []).append(sid)
    return by


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def logistic(x: np.ndarray, y: np.ndarray, l2: float = 1e-3, iters: int = 50) -> np.ndarray:
    """[w0, w1] of P(y) = 1 / (1 + exp(-(w0 + w1 x))), Newton's method with
    a small ridge."""
    X = np.stack([np.ones_like(x), x], 1)
    w = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.eye(2)
        w -= np.linalg.solve(H, X.T @ (p - y) + l2 * w)
    return w


def reliability_bins(p: np.ndarray, y: np.ndarray, bins=(0, .5, .8, .9, .95, .99, 1.0001)):
    """(expected calibration error, [[lo, hi, n, mean P, share right]])."""
    e, rel = 0.0, []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        if m.any():
            e += m.sum() * abs(p[m].mean() - y[m].mean())
            rel.append([lo, round(hi, 2), int(m.sum()), round(float(p[m].mean()), 3),
                        round(float(y[m].mean()), 3)])
    return e / max(len(p), 1), rel


def calibrate_margin(rows_by_agent: dict[str, list[dict]]) -> dict:
    """Margin (best referenced class over the runner-up) -> P(right),
    fitted on dev casts: an agent's own fit where its dev casts hold
    CALIB_MIN right and wrong, else the fit pooled over every agent's dev
    casts. Judged on held casts and demos; the LLR is logit(P) less the
    logit of the pooled dev accuracy (natural log)."""
    def xy(rows):
        rows = [r for r in rows if r["referenced"]]
        return (np.array([r["margin_ref"] for r in rows], float),
                np.array([r["best_ref"] == r["slot"] for r in rows], float))
    dev = {a: xy([r for r in rows if r["kind"] == "dev"]) for a, rows in rows_by_agent.items()}
    dev = {a: v for a, v in dev.items() if len(v[0])}
    xs = np.concatenate([v[0] for v in dev.values()])
    ys = np.concatenate([v[1] for v in dev.values()])
    w_pool, prior = logistic(xs, ys), float(ys.mean())
    out = {"pooled": {"w": np.round(w_pool, 3).tolist(), "dev_n": int(len(ys)),
                      "dev_right": int(ys.sum())}}
    allp, ally = [], []
    for a, rows in rows_by_agent.items():
        own = a in dev and (dev[a][1] == 0).sum() >= CALIB_MIN and (dev[a][1] == 1).sum() >= CALIB_MIN
        w = logistic(*dev[a]) if own else w_pool
        for k in ("held", "demo"):
            x, y = xy([r for r in rows if r["kind"] == k])
            if not len(x):
                continue
            p = np.clip(1 / (1 + np.exp(-(w[0] + w[1] * x))), 1e-6, 1 - 1e-6)
            e, rel = reliability_bins(p, y)
            llr = np.log(p / (1 - p)) - np.log(prior / (1 - prior))
            acc = p >= ACCEPT_P
            out.setdefault(a, {})[k] = {
                "basis": "agent" if own else "pooled", "w": np.round(w, 3).tolist(),
                "n": int(len(y)), "ece": round(float(e), 3), "reliability": rel,
                f"accepted_p{int(ACCEPT_P * 100)}": f"{int(y[acc].sum())}/{int(acc.sum())}",
                "llr_median_right": (round(float(np.median(llr[y == 1])), 2)
                                     if (y == 1).any() else None),
                "llr_median_wrong": (round(float(np.median(llr[y == 0])), 2)
                                     if (y == 0).any() else None)}
            if k == "held":
                allp.append(p), ally.append(y)
    if allp:
        p, y = np.concatenate(allp), np.concatenate(ally)
        e, rel = reliability_bins(p, y)
        out["all_held"] = {"n": int(len(y)), "ece": round(float(e), 3), "reliability": rel,
                           f"accepted_p{int(ACCEPT_P * 100)}":
                               f"{int(y[p >= ACCEPT_P].sum())}/{int((p >= ACCEPT_P).sum())}"}
    return out


def _score_rows(kind, name, casts, tracks, neighbours, classes, thresholds):
    """Rows for `casts` scored on `tracks`: every class's score, the
    verdict, and the argmax and margin over the referenced classes."""
    from .adjudication.ability_audio import NONE, cast_scores, identify
    if not casts:
        return []
    sc = cast_scores(tracks, [c["frame"] for c in casts], classes, neighbours=neighbours)
    ids = identify(sc, classes, thresholds)
    ref = [c for c in classes if c != NONE]
    out = []
    for c, v, row in zip(casts, ids, sc):
        s = {k: float(x) for k, x in zip(classes, row)}
        o = sorted((s[k] for k in ref), reverse=True)
        out.append({"kind": kind, "name": name, "t_ms": c["t_ms"], "slot": c["slot"],
                    "referenced": c["slot"] in ref,
                    "best_ref": max(ref, key=lambda k: s[k]),
                    "margin_ref": o[0] - o[1] if len(o) > 1 else float("nan"),
                    "verdict": v["verdict"], "reason": v["reason"],
                    "scores": {k: round(x, 4) for k, x in s.items()}})
    return out


def evaluate_params(store_root, params_root, gate: dict, audio_dirs=(), agents=None, xp=np) -> dict:
    """Score the set's dev and held sessions, their verified casts and the
    demos; per agent the argmax top-1 over referenced casts and the
    verdicts per kind, the misses, and the calibration."""
    from .ability_timeline import audio_cast_witness
    from .adjudication import ability_audio as aa
    from .version import ABILITY_AUDIO_PARAMS_VERSION
    root = Path(store_root)
    verified = verified_casts(root)
    demos = demo_census_sessions(root, audio_dirs)
    prov = json.loads((aa.params_path(params_root, ABILITY_AUDIO_PARAMS_VERSION)
                       / "provenance.json").read_text(encoding="utf-8"))
    split = prov["split"]
    agents = sorted(agents or prov["agents"])
    rows_by_agent, out = {}, {}
    for agent in agents:
        params, why = aa.load_params(params_root, ABILITY_AUDIO_PARAMS_VERSION, agent)
        if params is None:
            print(f"{agent}: {why}")
            continue
        rows = []
        sp = split.get(agent, {"dev": [], "held": []})
        for kind in ("dev", "held"):
            for name in sp[kind]:
                s, why = match_session(root, name, gate, audio_dirs, verified)
                if s is None:
                    print(f"{name}: {why}")
                    continue
                g = gate[sid_of(name)]
                res = audio_cast_witness(root, sid_of(name), g["rows"], g["agent"],
                                         g["kit_spans"], params=params, session=s, xp=xp)
                tracks = res["tracks"]
                classes = res["coverage"]["candidate_set"]["classes"]
                rows += _score_rows(kind, name, s["casts"], tracks, s["neighbours"], classes,
                                    params["thresholds"])
                rows += _score_rows(f"{kind}_verified", name, s["verified"], tracks,
                                    s["neighbours"], classes, params["thresholds"])
        for sid, a in demos.items():
            if a != agent:
                continue
            s = demo_session(root, sid, audio_dirs)
            Xw = aa.whiten_frames(s["X"], params["mu"], params["P"], params["ar"])
            tracks = aa.class_tracks(Xw, params["templates"], params["labels"], s["bg"], xp)
            classes = sorted(tracks, key=lambda c: "CQEX".find(c) if c != aa.NONE else 9)
            rows += _score_rows("demo", sid, s["casts"], tracks, s["neighbours"], classes,
                                params["thresholds"])
        rows_by_agent[agent] = rows
        summ = {}
        for kind in ("dev", "held", "dev_verified", "held_verified", "demo"):
            r = [x for x in rows if x["kind"] == kind and x["referenced"]]
            if not r:
                continue
            v = Counter("right" if x["verdict"] == x["slot"] else "wrong" if x["verdict"]
                        else "refused" for x in r)
            summ[kind] = {"top1": f"{sum(x['best_ref'] == x['slot'] for x in r)}/{len(r)}",
                          "right": v["right"], "wrong": v["wrong"], "refused": v["refused"],
                          "unreferenced": sum(x["kind"] == kind and not x["referenced"]
                                              for x in rows)}
        out[agent] = {"summary": summ, "split": sp,
                      "demos": sorted(s for s, a in demos.items() if a == agent),
                      "misses": [x for x in rows if x["kind"] in ("held", "held_verified", "demo")
                                 and x["referenced"] and x["best_ref"] != x["slot"]]}
        print(agent, json.dumps(summ), flush=True)
    cal = calibrate_margin(rows_by_agent)
    print("calibration all held", json.dumps(cal.get("all_held")), flush=True)
    return {"params": prov["version"], "agents": out, "calibration": cal,
            "rows": {a: r for a, r in rows_by_agent.items()}}


def main(args) -> int:
    """`reticle ability-audio-fit`."""
    import os

    from . import ult_lines
    from .store import Store
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)   # Below Normal
    from .ability_timeline import AUDIO_GATE_DIR
    store = Store(args.store)
    dirs = [Path(d) for d in args.audio_dir or ()]
    if args.gate:
        supplied = dict(s.split("=", 1) for s in args.supply or ())
        sids = sorted(p.stem for p in (store.root / AUDIO_GATE_DIR / "labels").glob("*.json"))
        sids += sorted({p.stem for d in dirs for p in (d / "labels").glob("*.json")} - set(sids))
        res = gate_snapshot(store, sids, supplied)
        Path(args.gate).write_text(json.dumps(res, indent=0), encoding="utf-8")
        print("gate ->", args.gate)
        return 0
    if not args.gate_in:
        print("--fit and --eval read a gate snapshot: pass --gate-in (made by --gate)")
        return 2
    gate = json.loads(Path(args.gate_in).read_text(encoding="utf-8"))
    xp = ult_lines.array_module()
    if args.fit:
        fit_params(store.root, Path(args.fit), gate, dirs, args.agent, xp)
    if args.eval:
        res = evaluate_params(store.root, Path(args.eval), gate, dirs, args.agent, xp)
        if args.json:
            Path(args.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0
