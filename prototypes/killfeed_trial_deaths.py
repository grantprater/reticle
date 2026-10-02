r"""Deaths from a killfeed reader trial, adjudicated in memory; writes outside the store.

    .\.venv\Scripts\python.exe prototypes\killfeed_trial_deaths.py SESSION --out DIR
    .\.venv\Scripts\python.exe prototypes\riot_ground_truth.py SESSION --deaths-from DIR --no-minimap --no-status

A killfeed reader change moves two inputs of the death owner at once: the HUD
table's entry masks (`hud` reader) and the portrait, weapon and name streams
(`killfeed` reader). This reruns both readers on the ROI crop cache
(`reticle.trial.run`, `--from cache`: no decode), puts their rows in place of
the stored ones at the frames they read, runs `cli.death_streams` over the
result and writes the `death` rows to `DIR/events/death/SESSION.jsonl`, where
the Riot scorer's `--deaths-from` reads them. The store is read, never
written. A frame the cache refuses keeps its stored row; the count is printed.

Run it once on the code before a reader change and once after; both runs go
through the same path, so the difference is the change's.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _below_normal() -> None:
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "4")
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            # Untyped, the pseudo-handle reaches SetPriorityClass truncated
            # and the call fails with ERROR_INVALID_HANDLE, silently.
            k.GetCurrentProcess.restype = ctypes.c_void_p
            k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            k.GetPriorityClass.argtypes = [ctypes.c_void_p]
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)   # BELOW_NORMAL
            print(f"priority class {k.GetPriorityClass(k.GetCurrentProcess()):#x}")
        else:
            os.nice(10)
    except Exception:                                   # noqa: BLE001 -- best effort
        pass


def merged_hud(stored, rows: list[dict]):
    """The stored HUD table with the trial's rows in place at their frames."""
    import pyarrow as pa
    by_t = {float(r["t_ms"]): r for r in rows}
    cols = stored.to_pydict()
    hit = 0
    for i, t in enumerate(cols["t_ms"]):
        r = by_t.get(float(t))
        if r is None:
            continue
        hit += 1
        for c, v in r.items():
            if c in cols:
                cols[c][i] = list(v) if isinstance(v, tuple) else v
    return pa.Table.from_pydict(cols, schema=stored.schema), hit


def merged_events(stored: list[dict], trial: list[dict], at: set[float]) -> list[dict]:
    """Stored observation rows outside the trial's frames, plus every trial row."""
    keep = [r for r in stored if "t_ms" in r and float(r["t_ms"]) not in at
            and r.get("kind") not in ("coverage", "summary")]
    return sorted(keep + trial, key=lambda r: float(r.get("t_ms", -1.0)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("session")
    ap.add_argument("--out", required=True, help="directory outside the store")
    ap.add_argument("--windows", default="all", choices=("all", "occupied"))
    args = ap.parse_args(argv)
    _below_normal()
    from reticle.cli import death_streams
    from reticle.store import Store
    from reticle.trial import run

    store = Store()
    out = Path(args.out).resolve()
    if Path(store.root).resolve() in [out, *out.parents]:
        raise SystemExit("--out must lie outside the store")
    man = store.read_manifest(args.session)
    sid = man["session_id"]
    hud_t = run(store, man, reader="hud", source="cache", windows=args.windows)
    kf_t = run(store, man, reader="killfeed", source="cache", windows=args.windows)
    hud, hit = merged_hud(store.read_hud(sid, man["ingested_at"][:10]), hud_t["rows"]["hud"])
    at = {float(r["t_ms"]) for r in hud_t["rows"]["hud"]}
    kat = set()
    for rows in kf_t["rows"].values():
        kat |= {float(r["t_ms"]) for r in rows if "t_ms" in r}
    kat |= {float(t) for t in at}
    streams = {s: merged_events(store.read_events(s, sid) or [], kf_t["rows"][s], kat)
               for s in ("killfeed_portrait", "killfeed_weapon", "killfeed_name")}
    d = death_streams(store, man, hud=hud, portraits=streams["killfeed_portrait"],
                      weapons=streams["killfeed_weapon"], names=streams["killfeed_name"])
    p = out / "events" / "death" / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in [d["head"]] + d["rows"] + d["collisions"]:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"{sid}: hud {hud_t['frames']} frames read ({hit} replaced; refused "
          f"{hud_t['refused']}), killfeed {kf_t['frames']} frames (refused {kf_t['refused']}); "
          f"{len(d['rows']) - d['head']['revives']} deaths, {d['head']['revives']} revives -> {p}")
    print(f"  hud diff {hud_t['diff']['hud']['columns'] if 'columns' in hud_t['diff']['hud'] else ''}")
    for s, df in kf_t["diff"].items():
        print(f"  {s}: {df['same']} same, {df['only_trial']} only trial, {df['only_stored']} only stored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
