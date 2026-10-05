r"""Score the gold-only tray drop's witness rules against Riot's cast counts.

    .\.venv\Scripts\python.exe prototypes\tray_gold_eval.py [SID ...] [--cache DIR] [--record]

`reticle/tray.py` fires a drop read from gold halves alone only where a
second witness saw the spend (`tray.gold_witness`): the restock countdown,
the slot icon, or, since tray-0.4.0, the spent half reading gold on
`GOLD_PERSIST_MIN` readable samples in a row (`persisted`). This prototype
reruns that choice per rule: persistence off (the countdown and icon only)
and `GOLD_PERSIST_MIN` = 2, 3 and 4. For each it counts the gold-only drops
and the refused ones, fires the drops (`tray.drops`), gates them
(`ability_timeline.player_tray_casts`) and scores the player's own casts
against Riot's per ability: covered is min(ours, Riot's), beyond is the
excess (`score_slots`).

Inputs. The tray samples, the countdown reads, the icon witness and the
icon brightness are read from the `minimap` crop cache by the pass
`reticle tray` runs (`cli._tray_samples`, `_tray_icon_witness`,
`_gold_witness`), held in memory, never written to the store: on
2026-10-05 the store held tray-0.4.0 rows for 3 of the 21 sessions, so the
stored drop and countdown rows cannot stand for the rest. The cast gate's
inputs (rounds, deaths, kit, menu) are the stored ones
(`stored_gate_inputs`); Riot's match records are evaluation truth only.
Decodes no video. `--cache` keeps each session's pass on disk for reruns.

Each rule calls the owners: `tray.gold_witness` reads the module's
`GOLD_PERSIST_MIN`, so a rule sets it for its call (`persist_min`) and
restores it. No witness or gate rule is restated here.

The eye checks (`EYE`) are the gold-persist-20261005 outcome row's labels
of the 20 drops the countdown and icon refused, carried as data; `--record`
joins them to the computed candidates for the run-length and switch counts.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TRAY_GOLD_EVAL_VERSION = "tray-gold-eval-0.1.0"
STORE = Path.home() / "reticle-store"
#: The Riot-paired match sessions the tray is scored on (`metric:tray/*@riot-21`).
SESSIONS = ("043bafca271a", "223d636bf8d2", "3694746e4e54", "4f207c0c4e39", "5822b6646448",
            "587c15b07779", "59c70f1ef720", "7010b3d62460", "75a55a296d3b", "96aa1ae9b96f",
            "9acf02f98283", "a06f04a0059f", "a1a995e6b19b", "b3b9defb6fd7", "b7d24102a6f6",
            "bdfdcf009dba", "bfad2778a372", "c40d950031bb", "c62c2b06bcfb", "e37fdeca944f",
            "ff636d173b07")
SLOTS = ("C", "Q", "E", "X")
RIOT_SLOT = {"C": "Grenade", "Q": "Ability1", "E": "Ability2", "X": "Ultimate"}
#: The witness rules: a name and the `GOLD_PERSIST_MIN` it runs with; None
#: turns persistence off (the countdown and icon witnesses only).
RULES = (("off", None), ("k2", 2), ("k3", 3), ("k4", 4))
#: By-eye labels of the 20 gold-only drops the countdown and icon refused,
#: keyed (session, slot, t_s to 0.1 s): `false` a gold misread, `real` a spent
#: gold charge, `switch` a kit switch or round reset over a real gold half,
#: `uncertain`. From the tray crops of the gold-persist-20261005 outcome row
#: in the store's `notes/predictions.jsonl`.
EYE = {
    ("043bafca271a", "C", 1335.0): "false", ("a1a995e6b19b", "Q", 1298.0): "false",
    ("c62c2b06bcfb", "E", 216.5): "false", ("ff636d173b07", "E", 2052.0): "false",
    ("587c15b07779", "E", 1140.0): "real", ("7010b3d62460", "E", 1531.0): "real",
    ("a06f04a0059f", "E", 429.1): "real", ("ff636d173b07", "E", 1052.5): "real",
    ("4f207c0c4e39", "E", 1776.0): "real", ("7010b3d62460", "E", 1348.0): "real",
    ("c40d950031bb", "E", 928.5): "real", ("a1a995e6b19b", "E", 743.0): "uncertain",
    ("587c15b07779", "E", 1233.5): "switch", ("5822b6646448", "E", 355.1): "switch",
    ("b3b9defb6fd7", "E", 299.1): "switch", ("bdfdcf009dba", "E", 320.6): "switch",
    ("bfad2778a372", "E", 1136.0): "switch", ("bdfdcf009dba", "C", 1102.5): "switch",
    ("bdfdcf009dba", "E", 1102.5): "switch", ("e37fdeca944f", "C", 434.1): "switch",
}


def score_slots(ours: dict, riot: dict) -> dict:
    """Per slot, `{"riot", "covered", "beyond"}`: covered is the lesser of our
    cast count and Riot's, beyond is ours over Riot's. A slot absent from
    `ours` counts zero; the slots are Riot's."""
    out = {}
    for k, r in riot.items():
        n = int(ours.get(k, 0))
        out[k] = {"riot": int(r), "covered": min(n, int(r)), "beyond": max(0, n - int(r))}
    return out


def total(scored: list[dict]) -> dict:
    """The sum of `score_slots` results over sessions and slots."""
    tot = Counter()
    for s in scored:
        for v in s.values():
            tot.update(v)
    return {k: tot[k] for k in ("riot", "covered", "beyond")}


@contextlib.contextmanager
def persist_min(k):
    """Run `tray.gold_witness` with `GOLD_PERSIST_MIN` = k (None: never)."""
    from reticle import tray
    old = tray.GOLD_PERSIST_MIN
    tray.GOLD_PERSIST_MIN = math.inf if k is None else k
    try:
        yield
    finally:
        tray.GOLD_PERSIST_MIN = old


def eye_key(sid: str, cand: dict) -> tuple:
    return (sid, cand["slot"], round(cand["t_ms"] / 1000.0, 1))


def _pass(store, sid: str, cache_dir: Path | None) -> tuple:
    """(minimap cache, ts, counts, clean, real, segs, icons, reads) of the
    pass `reticle tray` runs, from `cache_dir` when it holds them."""
    import numpy as np
    from reticle.cli import _tray_icon_witness, _tray_samples
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle import tray_countdown
    man = store.read_manifest(sid)
    cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no minimap crop cache ({why})")
    f = cache_dir / f"{sid}.npz" if cache_dir else None
    if f is not None and f.exists():
        z = np.load(f)
        reads = json.loads(f.with_suffix(".reads.json").read_text())
        return (cache, list(z["ts"]), z["counts"], z["clean"], z["real"], z["segs"],
                z["icons"], reads)
    cov = [r for r in store.read_events("tray_drop", sid) if r.get("kind") == "coverage"]
    step = cov[0]["step_s"] if cov else 0.5
    ts, counts, clean, real, segs, reads = _tray_samples(
        cache, step, segments=True, countdown=True,
        countdown_font=tray_countdown.store_font(store.root))
    icons, _ask, _stamp = _tray_icon_witness(cache, store.root, ts, counts, clean, segs)
    counts, clean = np.asarray(counts, float), np.asarray(clean, bool)
    real, segs = np.asarray(real, bool), np.asarray(segs, np.float32)
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(f, ts=np.asarray(ts), counts=counts, clean=clean, real=real,
                            segs=segs, icons=np.asarray(icons, bool))
        f.with_suffix(".reads.json").write_text(json.dumps(reads))
    return cache, ts, counts, clean, real, segs, np.asarray(icons, bool), reads


def evaluate(store, sid: str, riot: dict, cache_dir: Path | None = None) -> dict:
    """One session under every rule: `{rule: {"candidates", "refused",
    "gold_only_cast", "slots"}}` and its gold-only candidates (`cases`)."""
    from reticle import tray
    from reticle.ability_timeline import player_tray_casts, stored_gate_inputs
    from reticle.adjudication.ult_cast import player_agent
    from reticle.cli import _gold_witness
    from reticle.lineup import load_lineup
    cache, ts, counts, clean, real, segs, icons, reads = _pass(store, sid, cache_dir)
    man = store.read_manifest(sid)
    date = man["ingested_at"][:10]
    table = store.read_rounds(sid, date)
    if table is None:
        raise SystemExit(f"{sid}: no rounds table; the cast gate needs one")
    rounds = table.to_pylist()
    gate, _stamps = stored_gate_inputs(store, sid, date, rounds,
                                       player_agent(load_lineup(sid, store.root), sid))
    out, cases = {}, {}
    for name, k in RULES:
        with persist_min(k):
            witness, unwitnessed = _gold_witness(cache, ts, counts, clean, real, segs, icons,
                                                 reads)
        drops = tray.drops(ts, counts, clean, segs, icons, witness)
        rows = player_tray_casts(
            drops, gate["phase_of"], rounds, gate["player_deaths_ms"], agent=gate["agent"],
            second_lives_ms=gate["second_lives_ms"], revives_ms=gate["revives_ms"],
            report_deaths=gate["report_deaths"], kit_changes_ms=gate["kit_changes_ms"],
            kit_returns_ms=gate["kit_returns_ms"], menu_at=gate["menu_at"],
            kit_spans=gate["kit_spans"])
        cast = Counter(r["slot"] for r in rows if r["player_cast"])
        gold_cast = {(r["t_ms"], r["slot"]) for r in rows if r["player_cast"] and "witness" in r}
        for key, w in witness.items():
            c = cases.setdefault(key, {"session": sid, "slot": key[1], "t_ms": key[0],
                                       "gold_run": w["gold_run"]})
            c[name] = {"witnessed": w["witnessed"], "by": w["by"], "cast": key in gold_cast}
        out[name] = {"candidates": len(witness), "refused": len(unwitnessed),
                     "gold_only_cast": len(gold_cast), "slots": score_slots(cast, riot)}
    return {"rules": out, "cases": [cases[k] for k in sorted(cases)]}


def riot_casts() -> dict:
    """{session: {slot: Riot's cast count for the local player}}."""
    import ability_coverage as ac
    import riot_ground_truth as rg
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    recs = rg.riot_records(STORE)
    ident = rg.identify_player(recs, STORE)
    out = {}
    for sid, d in recs.items():
        if sid not in ident:
            continue
        idn = rg.resolve_lineup_player(d, ident[sid], ref)
        me = next(p for p in ac.riot_players(d, idn["subject"], ref.agent) if p["side"] == "self")
        out[sid] = {"agent": me["agent"], "casts": {k: me["casts"][RIOT_SLOT[k]] for k in SLOTS}}
    return out


def summarise(results: dict) -> dict:
    """Per rule, the totals over sessions; and the eye-joined counts at k2."""
    summ = {}
    for name, _k in RULES:
        rs = [r["rules"][name] for r in results.values()]
        summ[name] = {"candidates": sum(r["candidates"] for r in rs),
                      "refused": sum(r["refused"] for r in rs),
                      "gold_only_cast": sum(r["gold_only_cast"] for r in rs),
                      **total([r["slots"] for r in rs])}
    cases = [c for r in results.values() for c in r["cases"]]
    refused_off = [c for c in cases if not c["off"]["witnessed"]]
    eye = {id(c): EYE.get(eye_key(c["session"], c)) for c in refused_off}
    admitted = [c for c in refused_off if c["k2"]["witnessed"]]
    runs = lambda lab: [c["gold_run"] for c in refused_off if eye[id(c)] == lab]
    summ["eye"] = {
        "labelled": sum(v is not None for v in eye.values()),
        "unlabelled": [eye_key(c["session"], c) for c in refused_off if eye[id(c)] is None],
        "false_readings": len(runs("false")),
        "false_reading_run_max": max(runs("false"), default=None),
        "real_refused_run_min": min(runs("real"), default=None),
        "eye_real_gate_passed": sum(eye[id(c)] == "real" and c["k2"]["cast"]
                                    for c in refused_off),
        "admitted_kit_or_round_switch": sum(eye[id(c)] == "switch" for c in admitted),
        "admitted_gate_passed": sum(c["k2"]["cast"] for c in admitted),
        "admitted_gate_passed_false": sum(c["k2"]["cast"] and eye[id(c)] == "false"
                                          for c in admitted)}
    return summ


def record_gold_eval(summ: dict, sessions: list[str]) -> dict:
    """One metrics row, series tray/gold-persist-eval@riot-21."""
    from reticle import metrics
    from reticle.version import (PLAYER_CAST_VERSION, TRAY_COUNTDOWN_VERSION,
                                 TRAY_SEGMENT_VERSION, TRAY_VERSION)
    off, k2, e = summ["off"], summ["k2"], summ["eye"]
    values = {"gold_only_candidates": k2["candidates"], "refused_before": off["refused"],
              "refused_after": k2["refused"], "newly_admitted": off["refused"] - k2["refused"],
              "riot_casts": k2["riot"], "covered_before": off["covered"],
              "covered_after": k2["covered"], "excess_before": off["beyond"],
              "excess_after": k2["beyond"],
              **{f"covered_k{k}": summ[f"k{k}"]["covered"] for k in (2, 3, 4)},
              **{f"excess_k{k}": summ[f"k{k}"]["beyond"] for k in (2, 3, 4)},
              **{f"refused_k{k}": summ[f"k{k}"]["refused"] for k in (2, 3, 4)},
              **{k: e[k] for k in ("false_readings", "false_reading_run_max",
                                   "real_refused_run_min", "eye_real_gate_passed",
                                   "admitted_kit_or_round_switch", "admitted_gate_passed",
                                   "admitted_gate_passed_false")}}
    return metrics.record(
        "tray", part="gold-persist-eval", session="riot-21", values=values,
        deps={"tray_version": TRAY_VERSION, "tray_segment_version": TRAY_SEGMENT_VERSION,
              "player_cast_version": PLAYER_CAST_VERSION,
              "tray_countdown_version": TRAY_COUNTDOWN_VERSION,
              "tray_gold_eval_version": TRAY_GOLD_EVAL_VERSION},
        context={"sessions": sessions, "script": "prototypes/tray_gold_eval.py --record",
                 "in_sample": True, "rules": {n: k for n, k in RULES},
                 "inputs": "the minimap crop cache through reticle tray's pass, held in "
                           "memory; stored gate inputs; no decode, no store write",
                 "truth": "Riot match records stats.abilityCasts (own subject), evaluation only",
                 "eye": "labels of the 20 refused drops from the gold-persist-20261005 "
                        "outcome row"},
        log_path=STORE / "notes" / "metrics.jsonl")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="*", default=list(SESSIONS))
    ap.add_argument("--cache", type=Path, help="keep each session's tray pass here")
    ap.add_argument("--record", action="store_true", help="append the metrics row")
    ap.add_argument("--json", type=Path, help="write the per-session results here")
    args = ap.parse_args(argv)
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                0x4000)
    except (AttributeError, OSError):
        pass
    from reticle.store import Store
    store = Store(STORE)
    truth = riot_casts()
    results = {}
    for sid in args.sessions:
        t0 = time.perf_counter()
        results[sid] = evaluate(store, sid, truth[sid]["casts"], args.cache)
        r = results[sid]["rules"]
        print(sid, truth[sid]["agent"], " ".join(
            f"{n}:{r[n]['candidates']}/{r[n]['refused']}" for n, _k in RULES),
            f"{time.perf_counter() - t0:.0f}s", flush=True)
    summ = summarise(results)
    for name, _k in RULES:
        s = summ[name]
        print(f"{name}: gold-only {s['candidates']}, refused {s['refused']}, "
              f"covered {s['covered']} of {s['riot']}, beyond Riot {s['beyond']}")
    print("eye", json.dumps(summ["eye"]))
    if args.json:
        args.json.write_text(json.dumps({"summary": summ, "sessions": results}, indent=1))
    if args.record:
        if sorted(args.sessions) != sorted(SESSIONS):
            raise SystemExit("--record scores the riot-21 set only")
        if summ["eye"]["unlabelled"]:
            raise SystemExit(f"refused drops without an eye label: {summ['eye']['unlabelled']}")
        row = record_gold_eval(summ, list(SESSIONS))
        print("recorded", json.dumps(row["values"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
