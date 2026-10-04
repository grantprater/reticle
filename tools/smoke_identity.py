r"""Smokes come out identical when `minimap_dark` rides the ability pass.

    .\.venv\Scripts\python.exe tools\smoke_identity.py a06f04a0059f c40d950031bb [--out DIR]

The acceptance of stage 2 of `docs/ABILITY_DETECTION.md` (section 7). Per
session it runs two passes over the minimap crop cache, decoding nothing and
writing nothing into the store:

1. the unified pass: `minimap_dark` beside the ability readers
   (`ability_scan`, `ability_icons`), as `reticle scan SID --only ability`
   builds them;
2. `minimap_dark` alone, as `reticle scan SID --only minimap_dark --from
   cache` builds it.

Identity 1: the two passes' `minimap_dark` rows are byte-identical, and
`adjudication.smokes` over them gives the same tracks.

Identity 2: against the stored rows, which a video decode wrote, the masks
are identical at every instant both grids hold, the track counts agree, and
every track's first and last sighting lies within one 4 Hz sample (250 ms)
of its stored match. Each exception is listed by track, with whether the
stored instant is one the cache grid holds at all.

The unified pass's rows go to `--out` (default the store's
`analysis/smoke-identity-<date>/`), never over the stored rows. Each pass's
wall time is printed and kept in the summary, so the run doubles as the
pass's cost measurement. Single-threaded, at Below Normal priority.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import geometry, lighting  # noqa: E402
from reticle.adjudication.smokes import events as smoke_events  # noqa: E402
from reticle.menu import stored_menu  # noqa: E402
from reticle.passes import SessionContext, run_cached  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import choose_source, declare_set  # noqa: E402
from reticle.store import Store  # noqa: E402

#: One 4 Hz sample, the tolerance on a track's first and last sighting.
TOL_MS = 250.0


def below_normal() -> None:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    else:
        os.nice(10)


def _context(store, sid):
    from reticle.cli import _active_spans, _date_of, _live_phase_at, _live_round_spans
    man = store.read_manifest(sid)
    date = _date_of(man)
    profile = get_profile(man["source_profile"])
    spans = _active_spans(store, sid, date)
    ctx = SessionContext(store=store, manifest=man, profile=profile, spans=spans)

    def live_rounds():
        try:
            return _live_round_spans(store, sid, date), None
        except SystemExit as exc:
            return None, str(exc)
    return ctx, man, profile, spans, _live_phase_at(store, sid, date)[0], live_rounds


def run_pass(store, sid, with_ability: bool, extra=None) -> dict:
    """One cache-fed pass; its readers, frames and wall seconds."""
    from reticle.ability_icons import icon_reader
    from reticle.ability_scan import shape_reader
    from reticle.minimap_dark import dark_reader
    ctx, man, profile, spans, phase_at, live_rounds = _context(store, sid)
    floor, sgray = ctx.floor(), ctx.sgray()
    dp = dark_reader(ctx, spans, floor=floor, sgray=sgray)
    declare_set(dp, "minimap", profile, ctx.wh)
    readers = [dp]
    if with_ability:
        from reticle.ability_candidates import values_digest
        from reticle.cli import _ability_supply, _date_of
        supply, why = _ability_supply(store, sid, _date_of(man))
        bp = shape_reader(ctx, spans, phase_at=phase_at, floor=floor, sgray=sgray,
                          supply=supply, supply_reason=why, values=values_digest())
        declare_set(bp, "minimap", profile, ctx.wh)
        readers.append(bp)
        ip = icon_reader(ctx, spans, phase_at=phase_at, floor=floor, sgray=sgray)
        declare_set(ip, "minimap", profile, ctx.wh)
        readers.append(ip)
        for make in extra or ():
            r = make(ctx, spans, phase_at, floor)
            declare_set(r, "minimap", profile, ctx.wh)
            readers.append(r)
    cache, why, notes = choose_source(store.root, man, profile, readers, "cache", live_rounds)
    if cache is None:
        raise SystemExit(f"{sid}: no minimap crop cache feeds the pass ({why})")
    t0 = time.perf_counter()
    n = run_cached(ctx, readers, cache)
    return {"readers": readers, "frames": n, "wall_s": time.perf_counter() - t0, "why": why}


def _line(r: dict) -> str:
    return json.dumps(r, sort_keys=True, separators=(",", ":"))


def _tracks(sid, rows, store):
    with np.load(geometry.path_of(sid, store.root)) as z:
        ref = lighting.reference(z)
    menu, stamp = stored_menu(store, sid)
    return smoke_events(sid, rows, ref.known, menu.at if menu is not None else None, stamp)[1:]


def _match(stored, cached):
    """Each stored track's nearest cached track by place and first sighting."""
    out = []
    for s in stored:
        best = min(cached, key=lambda c: (np.hypot(c["cx"] - s["cx"], c["cy"] - s["cy"]) / 5.0
                                          + abs(c["first_ms"] - s["first_ms"]) / 1000.0),
                   default=None)
        out.append((s, best))
    return out


def check(store, sid, out_dir: Path) -> dict:
    uni = run_pass(store, sid, with_ability=True)
    print(f"{sid}: unified pass {uni['frames']} frames in {uni['wall_s']:.1f} s", flush=True)
    alone = run_pass(store, sid, with_ability=False)
    print(f"{sid}: minimap_dark alone {alone['frames']} frames in {alone['wall_s']:.1f} s",
          flush=True)
    gkey = geometry.key_of(sid, store.root)
    u_rows = uni["readers"][0].events(sid, gkey)
    a_rows = alone["readers"][0].events(sid, gkey)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{sid}.minimap_dark.unified.jsonl", "w", encoding="utf-8") as f:
        for r in u_rows:
            f.write(_line(r) + "\n")
    # Identity 1: the same reader alone, byte for byte, and its tracks.
    same_bytes = len(u_rows) == len(a_rows) and all(
        _line(a) == _line(b) for a, b in zip(u_rows, a_rows))
    u_tr, a_tr = _tracks(sid, u_rows, store), _tracks(sid, a_rows, store)
    same_tracks = [_line(t) for t in u_tr] == [_line(t) for t in a_tr]
    # Identity 2: the stored, decoded rows.
    st_rows = store.read_events("minimap_dark", sid)
    st_frames = {r["frame_idx"]: r for r in st_rows[1:]}
    shared = same = 0
    differ = []
    for r in u_rows[1:]:
        s = st_frames.get(r["frame_idx"])
        if s is None:
            continue
        shared += 1
        if all(r.get(k) == s.get(k) for k in ("widget_drawn", "grey_dark", "occluded")):
            same += 1
        else:
            differ.append(r["t_ms"])
    st_tr = _tracks(sid, st_rows, store)
    held = {float(r["t_ms"]) for r in u_rows[1:]}
    exceptions = []
    for s, c in _match(st_tr, u_tr):
        if c is None:
            exceptions.append({"track": s["track"], "stored": [s["first_ms"], s["last_ms"]],
                               "cached": None})
            continue
        d0, d1 = c["first_ms"] - s["first_ms"], c["last_ms"] - s["last_ms"]
        if abs(d0) > TOL_MS or abs(d1) > TOL_MS:
            exceptions.append({
                "track": s["track"], "stored": [s["first_ms"], s["last_ms"]],
                "cached": [c["first_ms"], c["last_ms"]], "d_first_ms": d0, "d_last_ms": d1,
                "stored_first_in_cache_grid": float(s["first_ms"]) in held,
                "stored_last_in_cache_grid": float(s["last_ms"]) in held})
    res = {"session": sid, "unified_wall_s": round(uni["wall_s"], 1),
           "unified_frames": uni["frames"], "alone_wall_s": round(alone["wall_s"], 1),
           "identity1": {"rows": len(u_rows), "bytes_identical": same_bytes,
                         "tracks": len(u_tr), "tracks_identical": same_tracks},
           "identity2": {"shared_instants": shared, "masks_identical": same,
                         "differ_at_ms": differ[:20], "tracks_cache": len(u_tr),
                         "tracks_stored": len(st_tr),
                         "within_250": len(st_tr) - len(exceptions), "exceptions": exceptions},
           "ability_rows": {"gate": len(uni["readers"][1].gate_rows),
                            "gated": uni["readers"][1].n_gated,
                            "surprise": len(uni["readers"][1].shape_rows),
                            "walls": len(uni["readers"][1].wall_rows),
                            "supply": uni["readers"][1].supply_reason or "built",
                            "icon_samples": len(uni["readers"][2].rows),
                            "icon_read": sum(r["reason"] is None for r in uni["readers"][2].rows),
                            "icon_candidates": sum(len(r["candidates"] or ())
                                                   for r in uni["readers"][2].rows)}}
    res["holds"] = bool(same_bytes and same_tracks and shared and same == shared
                        and len(u_tr) == len(st_tr)
                        and all(not (e.get("stored_first_in_cache_grid", False)
                                     and abs(e.get("d_first_ms", 0)) > TOL_MS)
                                and not (e.get("stored_last_in_cache_grid", False)
                                         and abs(e.get("d_last_ms", 0)) > TOL_MS)
                                for e in exceptions))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--store", default=None)
    a = ap.parse_args(argv)
    below_normal()
    store = Store(a.store) if a.store else Store()
    out = a.out or store.root / "analysis" / f"smoke-identity-{time.strftime('%Y%m%d')}"
    results = []
    for sid in a.sessions:
        res = check(store, sid, out)
        results.append(res)
        print(json.dumps(res, indent=1, default=str), flush=True)
    (out / "summary.json").write_text(json.dumps(results, indent=1, default=str),
                                      encoding="utf-8")
    print("HOLDS" if all(r["holds"] for r in results) else "FAILS")
    return 0 if all(r["holds"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
