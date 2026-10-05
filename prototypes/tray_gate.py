r"""Whether the ability tray's crops could take a gated cache, projected from
stored rows; writes nothing but ledger rows (`tray_gate/*`).

    .\.venv\Scripts\python.exe prototypes\tray_gate.py [--record] [SID ...]

The player (2026-10-05) asked whether the tray can take a dynamic cache like
the killfeed panel strip (`roi_cache.killfeed_panel_gate`). The tray is the
profile ROI `hud_abilities`, the second rectangle of the `minimap` crop set
(`roi_cache.CACHE_SETS`): written at the minimap rate over each round's
spans, its own FFV1 file (`*.r1.mkv`). It is not in the `hud` set.

**The gate** (fixed before measuring): a cache gate rests on an opportunity
from another channel, never on the tray's own changes. The opportunity is
the player alive in a round: inside a stored round, from `MARGIN_MS` before
its start to `MARGIN_MS` after its close (the buy phase included), less each
span the death owner's ally verdicts say the player is dead
(`round_entities.player_dead_spans`, the player's agent from the lineup),
shrunk by `MARGIN_MS` at both ends. While the player is dead the tray shows
the spectated teammate's kit.

**The projection**, per match (the sessions with a scoreboard cache, the 21
matches): the tray samples the cache holds and the share the gate keeps; the
same on the 2 Hz grid the tray readers read (`roi_cache.grid_times` at 0.5 s
on each cache span, as `reticle tray`, `tray-kit`, `menu` and
`ability-state` read it); the tray file's bytes, and the bytes a gated set
would take at the kept share (each frame weighed alike: no packet is read);
and the stored tray-derived rows at times the gate drops, per stream: a
consumer reading a gated set would lose them.

It reads the minimap set's record and index and the files' sizes, never a
frame. Owns nothing: a measurement. Wire: no (the player decides).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOOL_VERSION = "tray-gate-0.1.0"
STORE = Path(os.environ.get("RETICLE_STORE", "C:/Users/grant/reticle-store"))
#: Slack either side of the gate's edges: two 2 Hz samples, for the death
#: owner's time and the round boundaries.
MARGIN_MS = 1000.0
#: The tray readers' grid, seconds (`reticle tray --step` and the others).
GRID_S = 0.5
#: The tray-derived streams and the time each row is judged at.
STREAMS = ("tray_drop", "tray_countdown", "tray_kit", "tray_kit_identity", "ability_state",
           "menu_open", "ult_cast")


def matches() -> list[str]:
    from reticle.roi_cache import cache_dir
    return sorted(p.stem for p in cache_dir(STORE, "scoreboard").glob("*.json"))


def alive_spans(rounds: list[dict], deaths: list[dict], player: str | None,
               margin: float = MARGIN_MS) -> tuple[list[list[float]], list[list[float]]]:
    """(open spans, dead spans): each round from `margin` before its start to
    `margin` after its close, less the player's dead spans shrunk by
    `margin`; both sorted."""
    from reticle.round_entities import player_dead_spans
    live, dead = [], []
    for r in sorted(rounds, key=lambda r: r["t_start_ms"]):
        a = float(r["t_start_ms"]) - margin
        z = float(r.get("t_close_ms") or r["t_end_ms"]) + margin
        ally = [d for d in deaths if d.get("round_no") == r["round_no"] and d.get("side") == "ally"]
        cuts = [(s + margin, e - margin) for _d, s, e in
                player_dead_spans(ally, player, float(r.get("t_close_ms") or r["t_end_ms"]))]
        cuts = [(s, e) for s, e in cuts if e > s]
        dead += [[s, e] for s, e in cuts]
        x = a
        for s, e in cuts:
            if s > x:
                live.append([x, s])
            x = max(x, e)
        if z > x:
            live.append([x, z])
    merged: list[list[float]] = []
    for s, e in sorted(live):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged, dead


def row_time(stream: str, r: dict) -> float | None:
    """The time a stored row stands at: the drop an ult cast binds, a claim's
    observation, else the row's own time."""
    if stream == "ult_cast":
        t = (r.get("drop") or {}).get("t_drop_ms")
        return None if t is None else float(t)
    if stream == "ability_state" and r.get("kind") == "claim":
        return None if r.get("witness") != "tray_fill" else float(r["observed_at_ms"])
    t = r.get("t_ms")
    return None if t is None else float(t)


def project(sid: str) -> dict:
    from reticle.adjudication.ult_cast import player_agent
    from reticle.lineup import load_lineup
    from reticle.roi_cache import cache_dir, grid_times, spans_mask
    from reticle.store import Store
    st = Store(STORE)
    man = st.read_manifest(sid)
    d = cache_dir(STORE, "minimap")
    rec = json.loads((d / f"{sid}.json").read_text(encoding="utf-8"))
    idx = np.load(d / f"{sid}.idx.npy")
    k = list(rec.get("rois") or ("minimap", "hud_abilities")).index("hud_abilities")
    t = np.unique(idx[idx[:, 2] == k, 0])
    grid = np.array(sorted({x for a, b in (rec.get("spans") or [[t[0], t[-1]]])
                            for x in grid_times(t, float(a), float(b), GRID_S)}))
    rounds = st.read_rounds(sid, man["ingested_at"][:10]).to_pylist()
    deaths = [r for r in st.read_events("death", sid) if r.get("kind") == "death_verdict"]
    lineup = load_lineup(sid, STORE)
    player = player_agent(lineup, sid)
    live, dead = alive_spans(rounds, deaths, player)
    keep, keep_g = spans_mask(t, live), spans_mask(grid, live)
    in_dead = spans_mask(t, dead)
    sizes = {f"r{i}": (d / f"{sid}.r{i}.mkv").stat().st_size
             for i in range(len(rec["rects"])) if (d / f"{sid}.r{i}.mkv").is_file()}
    tray_bytes = int(sizes.get(f"r{k}", 0))
    rows = {}
    for s in STREAMS:
        got = Counter()
        try:
            stored = st.read_events(s, sid)
        except Exception:  # a stream this session never wrote
            stored = []
        for r in stored:
            if r.get("kind") == "coverage":
                continue
            x = row_time(s, r)
            if x is None:
                continue
            kind = r.get("kind") or "row"
            if s == "menu_open":
                if r.get("feature") != "close_button":
                    continue            # the tab strip is read off the hud set
                kind = "close_button"
            if s == "tray_drop" and r.get("player_cast"):
                got["player_cast_total"] += 1
            got[f"{kind}_total"] += 1
            if not spans_mask([x], live)[0]:
                got[f"{kind}_dropped"] += 1
                if s == "tray_drop" and r.get("player_cast"):
                    got["player_cast_dropped"] += 1
                if spans_mask([x], dead)[0]:
                    got[f"{kind}_dropped_dead"] += 1
        rows[s] = dict(got)
    return {"sid": sid, "player_agent": player, "rounds": len(rounds),
            "player_deaths": len(dead), "hz": rec["hz"],
            "tray_samples": int(len(t)), "kept": int(keep.sum()),
            "dropped_dead": int((~keep & in_dead).sum()),
            "grid_samples": int(len(grid)), "grid_kept": int(keep_g.sum()),
            "tray_bytes": tray_bytes, "set_bytes": int(sum(sizes.values())),
            "rows": rows}


def total(parts: list[dict]) -> dict:
    s = lambda k: sum(p[k] for p in parts)  # noqa: E731
    n, kept, g, gk, tb = s("tray_samples"), s("kept"), s("grid_samples"), s("grid_kept"), s("tray_bytes")
    rows: dict[str, Counter] = {}
    for p in parts:
        for st, c in p["rows"].items():
            rows.setdefault(st, Counter()).update(c)
    gated = tb * kept / max(n, 1)
    return {"matches": len(parts), "tray_samples": n, "kept": kept,
            "kept_share": round(kept / max(n, 1), 4),
            "dropped_dead_share": round(s("dropped_dead") / max(n, 1), 4),
            "grid_samples": g, "grid_kept": gk, "grid_kept_share": round(gk / max(g, 1), 4),
            "set_gb": round(s("set_bytes") / 1e9, 3), "tray_gb": round(tb / 1e9, 3),
            "tray_share_of_set": round(tb / max(s("set_bytes"), 1), 4),
            "gated_tray_gb": round(gated / 1e9, 3),
            "saved_gb_gate": round((tb - gated) / 1e9, 3),
            "grid_tray_gb": round(tb * g / max(n, 1) / 1e9, 3),
            "gated_grid_tray_gb": round(tb * gk / max(n, 1) / 1e9, 3),
            "players_unnamed": sum(p["player_agent"] is None for p in parts),
            "rows": {k: dict(v) for k, v in rows.items()}}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--record", action="store_true")
    p.add_argument("--out", help="write per-match JSON here")
    p.add_argument("sessions", nargs="*")
    args = p.parse_args(argv)
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    parts = [project(sid) for sid in (args.sessions or matches())]
    tot = total(parts)
    if args.out:
        Path(args.out).write_text(json.dumps({"parts": parts, "total": tot}, indent=1),
                                  encoding="utf-8")
    print(json.dumps(tot, indent=1))
    if args.record:
        from reticle import metrics
        deps = {"tool": TOOL_VERSION, "margin_ms": MARGIN_MS, "grid_s": GRID_S,
                "gate": "player alive in a stored round (rounds + death verdicts), buy phase in",
                "bytes": "tray file size times the kept share; no packet read"}
        vals = {k: v for k, v in tot.items() if k != "rows"}
        rows = tot["rows"]
        for st in STREAMS:
            for key, v in sorted(rows.get(st, {}).items()):
                vals[f"{st}__{key}"] = v
        metrics.record("tray_gate", part="projection", session=f"corpus-{len(parts)}",
                       deps=deps, values=vals, note="stored rows and file sizes only, no frame read",
                       context={"per_match": [{k: p[k] for k in ("sid", "tray_samples", "kept",
                                                                  "grid_samples", "grid_kept",
                                                                  "tray_bytes")}
                                              for p in parts]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
