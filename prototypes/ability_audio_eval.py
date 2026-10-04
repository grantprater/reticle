r"""Fit and evaluate the audio witness (`adjudication.ability_audio`) on the
separability probe's split, through the wired code.

    .\.venv\Scripts\python.exe prototypes\ability_audio_eval.py --gate OUT.json
    .\.venv\Scripts\python.exe prototypes\ability_audio_eval.py --fit ROOT --gate-in G.json
    .\.venv\Scripts\python.exe prototypes\ability_audio_eval.py --eval ROOT --gate-in G.json --json OUT

`--gate` computes the gate's verdicts (`ability_timeline.player_tray_casts`,
with the kit witness's spans) once per session from the stored streams and
writes them with the stream stamps it read, so the fit and the evaluation
read one stored state while other runs rewrite the store. `--fit` fits a
parameter set (`ABILITY_AUDIO_PARAMS_VERSION`) under ROOT (the store, or a
scratch root while developing) on the dev sessions only; `--eval` scores the
held sessions through `ability_timeline.audio_cast_witness` with the set
under ROOT. Decodes no video and no capture audio; the fit decodes the game's
reference files.

The split is the probe's (2026-10-03): Sova and Skye by session, Iso by the
time halves of its one session. Iso's identity verdict on 4f207c0c4e39 is a
disagreement (ability_tray against self_icon), so the arbiter names no
agent and production refuses every drop there; this evaluation supplies Iso,
as the probe did, and says so in its output. Iso's log-mel and labels exist
only in a scratch directory (`--iso-audio`), unstamped.

The references are the store's manifest (`ability-audio-ref-0.2.0`) mapped by
the ability's display name to the tray slot (`lineup.abilities_for`):

* a row whose folder is movement or footsteps (`Mvmnt`, `Movement`, `FS_*`)
  is no ability's cast and is left out;
* a row the manifest leaves unmapped is left out (`--unmapped out`, the
  default) or made a `none` reference (`--unmapped none`). On Sova and Skye
  the unmapped rows are ties between the kit's own abilities, and the dev
  casts say whose: Skye's `Guide_Taz_*` files fire on Trailblazer casts and
  Sova's `SuperBolt_OnBeam_Fire*` on Hunter's Fury, so as `none` they refuse
  true casts (held Sova 40/58, Skye 28/56). The evidence maps (EVIDENCE) name them by their file-name token, checked
  against dev casts only (`--no-evidence-maps` leaves them out);
* Reyna's unmapped `Abil_E` rows are Dismiss (E), the player's belief of
  2026-10-03 (basis `player_belief_20261003`); the manifest is not rewritten.

Compute: single-threaded BLAS, Below Normal priority, the GPU for the FFTs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from reticle.adjudication import ability_audio as aa  # noqa: E402

STORE = Path("C:/Users/grant/reticle-store")
REF_DIR = STORE / "reference" / "game-files" / "audio"
MANIFEST = REF_DIR / "manifest-0.2.0.jsonl"
ISO = "4f207c0c4e39"
SPLIT = {
    "Sova": {"dev": ["043bafca271a", "3694746e4e54", "75a55a296d3b", "9acf02f98283"],
             "held": ["223d636bf8d2", "59c70f1ef720", "96aa1ae9b96f", "c40d950031bb"]},
    "Skye": {"dev": ["b3b9defb6fd7", "bdfdcf009dba", "e37fdeca944f"],
             "held": ["b7d24102a6f6", "bfad2778a372"]},
    "Iso": {"dev": [f"{ISO}:first"], "held": [f"{ISO}:second"]},
}
#: The agent each session's player plays where the arbiter names none.
SUPPLIED = {ISO: ("Iso", "the arbiter's verdict is a disagreement (ability_tray Iso, "
                         "self_icon Phoenix); the probe and the player name Iso")}
#: Folders whose files are movement, not a cast.
MOVEMENT = ("Mvmnt", "Movement")
#: The player's belief of 2026-10-03: Reyna's unmapped Abil_E folder is Dismiss.
BELIEF = {("Reyna", "Abil_E"): ("Dismiss", "player_belief_20261003")}
#: Unmapped rows mapped on evidence (2026-10-03): (agent, folder, file-name
#: prefixes, ability, basis). The name's token says the ability, and on the
#: dev sessions alone the files fire only on that ability's casts
#: (`ability_audio_eval` none-file diagnostic); held casts never chose them.
EVIDENCE = [
    ("Skye", "Abil_E", ("Guide_Taz_", "Guide_AbilE_", "Guide_Abil_E_Attack"), "Trailblazer",
     "player_20261003+name_token_taz+dev_cooccurrence_20261003"),
    ("Sova", "Abil_X", ("Hunter_S0_AB_X_SuperBolt_OnBeam_",), "Hunter's Fury",
     "name_token_onbeam+dev_cooccurrence_20261003"),
]
#: What the fit does with a row the manifest leaves unmapped.
UNMAPPED_RULE = {"none": "unmapped rows are `none` references",
                 "out": "unmapped rows are left out: their ability is unknown, so they "
                        "witness neither a slot nor its absence"}
#: The probe's held top-1 (whitened), the floor this must meet.
PROBE_TOP1 = {"Sova": (42, 58), "Skye": (53, 56), "Iso": (11, 13)}
#: The slots the probe referenced (Sova had no Owl Drone file).
PROBE_SLOTS = {"Sova": "QEX", "Skye": "CQEX", "Iso": "CQEX"}


def idle():
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def sid_of(name):
    return name.split(":")[0]


# ---------------------------------------------------------------------------
# The gate, once
# ---------------------------------------------------------------------------

def gate_all(out: Path):
    from reticle import cli
    from reticle.ability_timeline import player_tray_casts, stored_gate_inputs
    from reticle.adjudication.ability_state import player_agent_verdict
    from reticle.adjudication.ult_cast import DROP_FIELDS
    from reticle.lineup import load_lineup
    from reticle.store import Store
    store = Store(STORE)
    res = {}
    for agent, sp in SPLIT.items():
        for name in sp["dev"] + sp["held"]:
            sid = sid_of(name)
            if sid in res:
                continue
            man = store.read_manifest(sid)
            date = cli._date_of(man)
            stored = store.read_events("tray_drop", sid)
            cov = next((r for r in stored if r.get("kind") == "coverage"), {})
            drops = [{k: r[k] for k in DROP_FIELDS if k in r} for r in stored
                     if r.get("kind") == "drop"]
            rounds = store.read_rounds(sid, date).to_pylist()
            verdict = player_agent_verdict(load_lineup(sid, store.root), sid)
            who, why = verdict["agent"], "identity arbiter"
            if who is None and sid in SUPPLIED:
                who, why = SUPPLIED[sid]
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
    out.write_text(json.dumps(res, indent=0), encoding="utf-8")


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def references(agent: str, unmapped: str = "out", evidence: bool = True) -> tuple[list[dict], dict]:
    """The agent's reference rows with their class (a tray slot or `none`),
    and the counts of what the rule kept and left out."""
    from reticle.lineup import abilities_for
    kit = abilities_for(agent, str(STORE))
    slot_of = {v: k for k, v in kit.items()}
    out, why = [], Counter()
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
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
            belief = next((v for (a, f), v in BELIEF.items()
                           if a == agent and f in parts), None)
            if belief:
                ability, basis = belief
        if ability is None and evidence:
            name = r["flac"].split("/")[-1]
            hit = next((e for e in EVIDENCE if e[0] == agent and e[1] in parts
                        and name.startswith(e[2])), None)
            if hit:
                ability, basis = hit[3], hit[4]
        if ability is None and unmapped == "out":
            why["unmapped_left_out"] += 1
            continue
        cls = slot_of.get(ability) if ability else aa.NONE
        if cls is None:
            why[f"not_in_kit:{ability}"] += 1
            continue
        why[f"{cls}:{basis}"] += 1
        out.append({"flac": r["flac"], "class": cls, "ability": ability, "basis": basis})
    unreferenced = sorted(set(kit) - {o["class"] for o in out})
    return out, {"kit": kit, "counts": dict(sorted(why.items())),
                 "slots_without_reference": unreferenced}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def session(name: str, gate: dict, iso_audio: Path | None):
    from reticle.ability_timeline import audio_session
    sid = sid_of(name)
    g = gate[sid]
    where = {}
    if sid == ISO:
        where = {"features_path": iso_audio / "features" / f"{sid}.npz",
                 "labels_path": iso_audio / "labels" / f"{sid}.json"}
        n = len(np.load(where["features_path"])["ok"])
        mid = n / (2 * aa.FPS)
        where["span_s"] = (0.0, mid) if name.endswith(":first") else (mid, n / aa.FPS)
    s, why = audio_session(STORE, sid, g["rows"], g["agent"], g["kit_spans"],
                           features_path=where.get("features_path"),
                           labels_path=where.get("labels_path"), span_s=where.get("span_s"))
    if s is None:
        raise SystemExit(f"{name}: {why}")
    return s, where


def fit(root: Path, gate: dict, iso_audio: Path, xp, unmapped: str = "out",
        evidence: bool = True):
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION
    agents, ref_rule = {}, {}
    for agent, sp in SPLIT.items():
        t0 = time.time()
        dev = [(n, *session(n, gate, iso_audio)) for n in sp["dev"]]
        Xbg = np.concatenate([s["X"][s["bg"]] for _n, s, _w in dev])
        mu, P, cond = aa.fit_band_whitener(Xbg)
        # The AR pairs never cross a session: a False frame between them.
        Y = np.concatenate([np.vstack([(s["X"] - mu) @ P, np.zeros((1, len(mu)))])
                            for _n, s, _w in dev])
        M = np.concatenate([np.concatenate([s["bg"], [False]]) for _n, s, _w in dev])
        ar = aa.fit_ar2(Y, M)
        refs, rule = references(agent, unmapped, evidence)
        temps, labels, files = [], [], []
        for r in refs:
            T = aa.template(aa.reference_logmel(REF_DIR / r["flac"]))
            if T is None:
                continue
            temps.append(aa.whiten_template(T, P, ar))
            labels.append(r["class"])
            files.append({"flac": r["flac"], "ability": r["ability"], "basis": r["basis"]})
        # Thresholds: one false fire per live minute over the dev sessions.
        peaks, live_min = {}, 0.0
        for _n, s, _w in dev:
            tr = aa.class_tracks(aa.whiten_frames(s["X"], mu, P, ar), temps, labels, s["bg"], xp)
            for c, v in tr.items():
                peaks.setdefault(c, []).append(aa.false_fire_peaks(v, s["live"], s["code"]))
            live_min += s["live_min"]
        thr = {c: aa.threshold_at(v, live_min) for c, v in peaks.items() if c != aa.NONE}
        agents[agent] = {
            "mu": mu, "P": P, "ar": ar, "templates": temps, "labels": labels, "files": files,
            "slots": rule["kit"], "thresholds": thr,
            "dev": [{"name": n, "path": gate[sid_of(n)]["path"],
                     "span_s": w.get("span_s"), "stamps": {**gate[sid_of(n)]["stamps"], **s["stamps"]},
                     "agent_basis": gate[sid_of(n)]["agent_basis"]} for n, s, w in dev],
            "fit": {"bg_frames": int(len(Xbg)), "band_condition": round(cond, 1),
                    "ar2": [round(float(a), 5) for a in ar], "live_min": round(live_min, 2),
                    "templates": len(temps), "by_class": dict(Counter(labels)),
                    "reference_rule_counts": rule["counts"],
                    "slots_without_reference": rule["slots_without_reference"]}}
        print(f"{agent}: bg {len(Xbg)} frames, cond {cond:.0f}, AR {np.round(ar, 4)}, "
              f"{len(temps)} templates {dict(Counter(labels))}, thresholds "
              f"{ {k: round(v, 3) for k, v in thr.items()} } ({time.time() - t0:.0f} s)", flush=True)
        ref_rule[agent] = rule["counts"]
    prov = {"ability_audio_version": ABILITY_AUDIO_VERSION,
            "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fitted_by": "prototypes/ability_audio_eval.py --fit",
            "reference": {"manifest": MANIFEST.relative_to(STORE).as_posix(),
                          "ref_version": "ability-audio-ref-0.2.0",
                          "rule": "by the ability's display name to the tray slot "
                                  "(lineup.abilities_for); movement and footstep folders "
                                  "left out",
                          "unmapped": UNMAPPED_RULE[unmapped],
                          "beliefs": [{"agent": a, "folder": f, "ability": v[0], "basis": v[1]}
                                      for (a, f), v in BELIEF.items()],
                          "evidence_maps": ([{"agent": e[0], "folder": e[1], "prefixes": list(e[2]),
                                              "ability": e[3], "basis": e[4]} for e in EVIDENCE]
                                            if evidence else [])},
            "split": {a: {"dev": v["dev"], "held": v["held"]} for a, v in SPLIT.items()},
            "split_basis": "the separability probe's split (2026-10-03); Iso by time halves "
                           "of its one session",
            "whitening": {"shrink": aa.SHRINK, "eig_floor": aa.EIG_FLOOR,
                          "ar_min_run": aa.AR_MIN_RUN, "bands_hz": [aa.BAND_LO, aa.BAND_HI]},
            "template_rule": {"active_db": aa.ACTIVE_DB, "floor_db": aa.TEMPLATE_DB,
                              "max_s": aa.MAX_TEMPLATE_S},
            "candidate_rule": "the player's kit slots with references, and `none`",
            "threshold_rule": f"{aa.THRESHOLD_FF_PER_MIN} false fire per live minute on the "
                              f"dev sessions' unexplained live frames, peaks "
                              f"{aa.PEAK_GAP} frames apart"}
    d = aa.save_params(root, ABILITY_AUDIO_PARAMS_VERSION, agents, prov)
    print("params ->", d)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(root: Path, gate: dict, iso_audio: Path, xp) -> dict:
    from reticle.ability_timeline import audio_cast_witness
    from reticle.version import ABILITY_AUDIO_PARAMS_VERSION
    out = {}
    for agent, sp in SPLIT.items():
        params, why = aa.load_params(root, ABILITY_AUDIO_PARAMS_VERSION, agent)
        if params is None:
            raise SystemExit(why)
        rows, ffs, held_min, per = [], {}, 0.0, {}
        for name in sp["held"]:
            sid = sid_of(name)
            s, where = session(name, gate, iso_audio)
            g = gate[sid]
            res = audio_cast_witness(root, sid, g["rows"], g["agent"], g["kit_spans"],
                                     params=params, session=s, xp=xp)
            scored = [r for r in res["rows"] if r.get("best") is not None]
            rows += scored
            for c, v in res["tracks"].items():
                ffs.setdefault(c, []).append(aa.false_fire_peaks(v, s["live"], s["code"]))
            held_min += s["live_min"]
            per[name] = {"casts": len(scored), "live_min": round(s["live_min"], 2),
                         "stamps": {**g["stamps"], **s["stamps"]}, "agent_basis": g["agent_basis"]}
        classes = sorted({c for r in rows for c in r["scores"]})
        slots = [c for c in classes if c != aa.NONE]
        ref = [r for r in rows if r["slot"] in slots]
        top_with_none = sum(r["best"] == r["slot"] for r in ref)
        argmax_slots = lambda r: max(slots, key=lambda c: r["scores"][c])
        top_slots = sum(argmax_slots(r) == r["slot"] for r in ref)
        probe = [r for r in ref if r["slot"] in PROBE_SLOTS[agent]]
        det = {}
        for c in slots:
            hv = np.array([r["scores"][c] for r in rows if r["slot"] == c])
            thr = params["thresholds"].get(c)
            fv = np.concatenate(ffs.get(c, [np.zeros(0)]))
            hthr = aa.threshold_at(ffs.get(c, []), held_min)
            det[c] = {"held_n": int(len(hv)), "dev_threshold": None if thr is None else round(thr, 3),
                      "held_recall_at_dev_threshold": (None if thr is None or not len(hv)
                                                       else round(float((hv >= thr).mean()), 3)),
                      "held_ff_per_min_at_dev_threshold": (None if thr is None else round(
                          float((fv >= thr).sum()) / max(held_min, 1e-9), 3)),
                      "held_roc_recall_at_1ff": (None if hthr is None or not len(hv)
                                                 else round(float((hv >= hthr).mean()), 3))}
        out[agent] = {
            "held": per, "held_live_min": round(held_min, 2), "classes": classes,
            "params": {"version": params["version"], "ar2": params["fit"]["ar2"],
                       "templates": params["fit"]["by_class"], "thresholds": params["thresholds"]},
            "held_casts": dict(Counter(r["slot"] for r in rows)),
            "top1_probe_slots_argmax": f"{sum(argmax_slots(r) == r['slot'] for r in probe)}/{len(probe)}",
            "top1_probe_slots_with_none": f"{sum(r['best'] == r['slot'] for r in probe)}/{len(probe)}",
            "probe_top1": "%d/%d" % PROBE_TOP1[agent],
            "top1_referenced_argmax": f"{top_slots}/{len(ref)}",
            "top1_referenced_with_none": f"{top_with_none}/{len(ref)}",
            "per_slot_with_none": {c: f"{sum(r['best'] == c for r in ref if r['slot'] == c)}/"
                                      f"{sum(r['slot'] == c for r in ref)}" for c in slots},
            "confusion_best": {c: dict(Counter(r["best"] for r in ref if r["slot"] == c))
                               for c in slots},
            "verdicts": dict(Counter("right" if r["verdict"] == r["slot"] else
                                     "wrong" if r["verdict"] else f"refused:{r['reason']}"
                                     for r in ref)),
            "margin_median": round(float(np.median([r["margin"] for r in ref])), 3) if ref else None,
            "detection": det}
        print(agent, json.dumps({k: out[agent][k] for k in (
            "held_casts", "top1_probe_slots_argmax", "top1_probe_slots_with_none", "probe_top1",
            "top1_referenced_with_none", "verdicts", "per_slot_with_none")}), flush=True)
        for c, v in det.items():
            print("   ", c, v, flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", type=Path)
    ap.add_argument("--gate-in", type=Path)
    ap.add_argument("--fit", type=Path)
    ap.add_argument("--eval", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--iso-audio", type=Path)
    ap.add_argument("--unmapped", choices=sorted(UNMAPPED_RULE), default="out")
    ap.add_argument("--no-evidence-maps", action="store_true")
    a = ap.parse_args()
    idle()
    if a.gate:
        gate_all(a.gate)
        return
    from reticle import ult_lines
    xp = ult_lines.array_module()
    gate = json.loads(a.gate_in.read_text(encoding="utf-8"))
    if a.fit:
        fit(a.fit, gate, a.iso_audio, xp, a.unmapped, not a.no_evidence_maps)
    if a.eval:
        res = evaluate(a.eval, gate, a.iso_audio, xp)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
