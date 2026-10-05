r"""Score the player-cast gate against Riot's cast counts, dev and held apart.

    .\.venv\Scripts\python.exe prototypes\own_cast_gate_eval.py --cache DIR [SID ...]
        [--drops DIR] [--half dev|held] [--second-lives FILE] [--json OUT] [--record]
    .\.venv\Scripts\python.exe prototypes\own_cast_gate_eval.py --reread-second-lives OUT SID ...

The gate (`ability_timeline.player_tray_casts`) judges which tray drops are
the player's casts; Riot's match records count the player's casts per
ability, as evaluation truth only. Per session and ability, covered is the
lesser of ours and Riot's, beyond is ours over Riot's
(`tray_gold_eval.score_slots`). The 21 Riot-paired matches split by a rule
fixed before measuring: sha1 of `own-cast-gate:` and the session, even = dev
(`half`). Rules are chosen on dev; held is reported apart.

Inputs. The drops are `reticle tray`'s pass over the `minimap` crop cache
(`tray_gold_eval._pass`, its gold witness `cli._gold_witness`, then
`tray.drops`), held in memory or kept under `--cache`, never written to the
store; the restock numeral reads are that pass's. The other gate inputs are
the stored ones (`stored_gate_inputs`), with one exception: the player's own
ult lines are `own_line_times` over the stored `ult_cast` rows at their
stored version. The gate itself uses only lines at ULT_CAST_VERSION
(`stored_own_lines`); this evaluation takes the stored ones because the
lines that rest on nothing are selected by score alone, and ult-cast-0.6.0
changed only how tray casts bind, not that selection. Decodes no video.

Runs. `gate` is the gate over those inputs; `no_lines` drops the own lines;
with `--second-lives FILE`, `reread` replaces the stored second lives with
the file's (`--reread-second-lives` writes it: `killfeed_portrait` re-read at
the current version from the crop cache by `reticle.trial`, in memory). The
gate's rules are called, never restated.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OWN_CAST_GATE_EVAL_VERSION = "own-cast-gate-eval-0.1.0"
STORE = Path.home() / "reticle-store"


def half(sid: str) -> str:
    """The session's half of the split fixed before measuring."""
    h = int(hashlib.sha1(("own-cast-gate:" + sid).encode()).hexdigest(), 16)
    return "dev" if h % 2 == 0 else "held"


def drops_of(store, sid: str, cache_dir: Path, drops_dir: Path) -> tuple[list[dict], list[dict]]:
    """(the drops `tray.drops` fires on `reticle tray`'s pass, the pass's
    numeral reads), kept under `drops_dir` keyed by TRAY_VERSION."""
    import tray_gold_eval as tge
    from reticle import tray
    from reticle.cli import _gold_witness
    from reticle.version import TRAY_VERSION
    f = drops_dir / f"{sid}.{TRAY_VERSION}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    cache, ts, counts, clean, real, segs, icons, reads = tge._pass(store, sid, cache_dir)
    witness, _unw = _gold_witness(cache, ts, counts, clean, real, segs, icons, reads)
    out = (tray.drops(ts, counts, clean, segs, icons, witness), reads)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(pickle.dumps(out))
    return out


def gate_runs(store, sid: str, cache_dir: Path, drops_dir: Path,
              second_lives: dict | None) -> dict:
    """{run: the gate's rows} for one session (see the module docstring)."""
    from reticle.ability_timeline import own_line_times, player_tray_casts, stored_gate_inputs
    from reticle.adjudication.ult_cast import player_agent
    from reticle.lineup import load_lineup
    drops, reads = drops_of(store, sid, cache_dir, drops_dir)
    man = store.read_manifest(sid)
    date = man["ingested_at"][:10]
    rounds = store.read_rounds(sid, date).to_pylist()
    gate, _stamps = stored_gate_inputs(store, sid, date, rounds,
                                       player_agent(load_lineup(sid, store.root), sid))
    gate["own_lines_ms"] = own_line_times(store.read_events("ult_cast", sid))
    gate["countdown_reads"] = reads
    runs = {"gate": {}, "no_lines": {"own_lines_ms": []}}
    if second_lives is not None:
        # A session the file leaves out keeps its stored second lives.
        runs["reread"] = ({"second_lives_ms": second_lives[sid]["second_lives_ms"]}
                          if sid in second_lives else {})
    out = {}
    for name, over in runs.items():
        g = {**gate, **over}
        kw = {k: v for k, v in g.items() if k not in ("phase_of", "player_deaths_ms")}
        out[name] = player_tray_casts([dict(d) for d in drops], g["phase_of"], rounds,
                                      g["player_deaths_ms"], **kw)
    return out


def score(results: dict, truth: dict) -> dict:
    """{run: {half: {riot, covered, beyond}}} over the sessions scored."""
    from tray_gold_eval import score_slots
    tot = {}
    for sid, runs in results.items():
        for name, rows in runs.items():
            cast = Counter(r["slot"] for r in rows if r["player_cast"])
            t = tot.setdefault(name, {}).setdefault(half(sid), Counter())
            for v in score_slots(cast, truth[sid]["casts"]).values():
                t.update(v)
    return {n: {h: dict(c) for h, c in hs.items()} for n, hs in tot.items()}


def reread_second_lives(out: Path, sids: list[str]) -> None:
    """Write {sid: second lives} from `killfeed_portrait` re-read at the
    current version from the crop cache (`reticle.trial`, in memory)."""
    from reticle import trial
    from reticle.adjudication.death import stored_second_life
    from reticle.killfeed import KILLFEED_PORTRAIT_VERSION
    from reticle.rounds import player_death_times, player_second_life_times
    from reticle.store import Store
    store = Store(STORE)
    res = json.loads(out.read_text()) if out.exists() else {}
    for sid in sids:
        if sid in res:
            continue
        man = store.read_manifest(sid)
        r = trial.run(store, man, "killfeed", source="cache", windows="occupied")
        rows = r["rows"]["killfeed_portrait"]
        badges = stored_second_life(rows, KILLFEED_PORTRAIT_VERSION)
        hud = store.read_hud(sid, man["ingested_at"][:10])
        res[sid] = {"version": rows[0].get("killfeed_portrait_version") if rows else None,
                    "observations": len(badges or []),
                    "second_lives_ms": player_second_life_times(hud, badges),
                    "deaths_ms": player_death_times(hud), "frames": r["frames"],
                    "refused": r["refused"], "seconds": r["seconds"]}
        print(sid, res[sid]["version"], res[sid]["second_lives_ms"], flush=True)
        out.write_text(json.dumps(res))


def record_gate_eval(summ: dict, sessions: list[str], second_lives: Path | None) -> dict:
    """One metrics row, series tray/own-cast-gate@riot-21."""
    from reticle import metrics
    from reticle.version import (PLAYER_CAST_VERSION, TRAY_COUNTDOWN_VERSION, TRAY_VERSION,
                                 ULT_CAST_VERSION)
    values = {}
    for name, hs in summ.items():
        for h, t in hs.items():
            values[f"{name}_{h}_covered"] = t["covered"]
            values[f"{name}_{h}_beyond"] = t["beyond"]
            values[f"{h}_riot"] = t["riot"]
    return metrics.record(
        "tray", part="own-cast-gate", session="riot-21", values=values,
        deps={"player_cast_version": PLAYER_CAST_VERSION, "tray_version": TRAY_VERSION,
              "tray_countdown_version": TRAY_COUNTDOWN_VERSION,
              "ult_cast_version": ULT_CAST_VERSION,
              "own_cast_gate_eval_version": OWN_CAST_GATE_EVAL_VERSION},
        context={"sessions": sessions,
                 "split": "sha1('own-cast-gate:'+sid) parity, even = dev",
                 "script": "prototypes/own_cast_gate_eval.py --cache DIR --record"
                           + (" --second-lives FILE" if second_lives else ""),
                 "runs": {"gate": "the gate over the inputs the module docstring names",
                          "no_lines": "the same with no own ult lines",
                          "reread": "the same with second lives from --reread-second-lives"},
                 "lines": "own_line_times over the stored ult_cast rows at their stored "
                          "version (score-selected lines; ult-cast-0.6.0 changed only tray binding)",
                 "inputs": "reticle tray's pass over the minimap crop cache, held in memory; "
                           "stored gate inputs otherwise; no decode, no store write",
                 "truth": "Riot match records stats.abilityCasts (own subject), evaluation only"},
        log_path=STORE / "notes" / "metrics.jsonl")


def main(argv=None) -> int:
    import tray_gold_eval as tge
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--cache", type=Path, help="keep each session's tray pass and drops here")
    ap.add_argument("--drops", type=Path, help="keep the fired drops here (default: CACHE/drops)")
    ap.add_argument("--half", choices=("dev", "held"), help="score this half only")
    ap.add_argument("--second-lives", type=Path, help="a --reread-second-lives file")
    ap.add_argument("--reread-second-lives", type=Path, metavar="OUT")
    ap.add_argument("--json", type=Path, help="write the per-drop rows here")
    ap.add_argument("--record", action="store_true", help="append the metrics row")
    args = ap.parse_args(argv)
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                0x4000)
    except (AttributeError, OSError):
        pass
    if args.reread_second_lives:
        reread_second_lives(args.reread_second_lives, args.sessions)
        return 0
    if args.cache is None:
        raise SystemExit("--cache is required: the drops come from reticle tray's cached pass")
    from reticle.store import Store
    store = Store(STORE)
    sids = [s for s in (args.sessions or tge.SESSIONS) if args.half in (None, half(s))]
    truth = tge.riot_casts()
    lives = json.loads(args.second_lives.read_text()) if args.second_lives else None
    results = {}
    for sid in sids:
        t0 = time.perf_counter()
        results[sid] = gate_runs(store, sid, args.cache, args.drops or args.cache / "drops", lives)
        print(sid, truth[sid]["agent"], half(sid), f"{time.perf_counter() - t0:.1f}s",
              flush=True)
    summ = score(results, truth)
    for name, hs in summ.items():
        for h, t in sorted(hs.items()):
            print(f"{name} {h}: covered {t['covered']} of {t['riot']}, beyond {t['beyond']}")
    if args.json:
        keep = ("t_ms", "slot", "from", "to", "forced", "reason", "player_cast", "kit_end_ms",
                "undone_deaths", "numeral", "refused_as", "line_ms", "pool_gold_drop")
        args.json.write_text(json.dumps(
            {sid: {"half": half(sid), "riot": truth[sid]["casts"],
                   "runs": {n: [{k: r[k] for k in keep if k in r} for r in rows]
                            for n, rows in runs.items()}}
             for sid, runs in results.items()}, default=float))
    if args.record:
        if args.half or sorted(sids) != sorted(tge.SESSIONS):
            raise SystemExit("--record scores the riot-21 set, both halves")
        row = record_gate_eval(summ, list(tge.SESSIONS), args.second_lives)
        print("recorded", json.dumps(row["values"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
