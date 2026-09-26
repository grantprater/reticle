r"""What sampling rate does minimap ally identity need?

    .\.venv\Scripts\python.exe prototypes\minimap_fidelity.py [SID ...]

Measured, not wired. Reading, not decoding, is the cost that scales with
rate: one session's live rounds decode in about 3 min whatever the rate, while
the ally icon reader took 527 s for its 18038 frames at 15 Hz.

A lower rate is a subset of the 15 Hz frames, so each rate here decimates the
stored 15 Hz `ally_icon` events (every k-th frame, the count restarting at
each gap, as a decode over spans restarts its stride) and rebuilds the round
entities in memory with `round_entities.session_lifetimes`. Deaths are NOT
passed in: its death linkage names a segment from the death, which would make
the check below circular.

The check is the killfeed, an independent witness
(`prototypes/minimap_identity_at_death.py`): a segment that alone ends within
[-500, +700] ms of an ally death with a named victim is that victim. Per rate
it reports segment and per-icon identity at those deaths, ally entities per
round, and the share of frames that name one agent on two icons
[domain:rounds/agent-uniqueness]. Predictions and outcome:
`minimap-fidelity` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.adjudication.identity import load_identity_gallery  # noqa: E402
from reticle.cli import _date_of  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.round_entities import session_lifetimes  # noqa: E402
from reticle.rounds import build_rounds  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
RATES = (15.0, 7.5, 5.0, 3.0, 2.0)
DEATH_WINDOW_MS = (500.0, 700.0)
GAP_MS = 200.0


def decimate(events: list[dict], k: int) -> list[dict]:
    """Every k-th frame of a 15 Hz stream, restarting at each gap."""
    times = sorted({e["t_ms"] for e in events if e.get("kind") in ("frame", "icon")})
    keep, n, last = set(), 0, None
    for t in times:
        if last is not None and t - last > GAP_MS:
            n = 0
        if n % k == 0:
            keep.add(t)
        n, last = n + 1, t
    return [e for e in events if e.get("kind") not in ("frame", "icon") or e["t_ms"] in keep]


def build_entities(sid: str, events: list[dict]) -> list[dict]:
    man = STORE.read_manifest(sid)
    date = _date_of(man)
    rounds = build_rounds(STORE.read_hud(sid, date))
    roster = None
    if STORE.has_roster(sid, date):
        t = STORE.read_roster(sid, date)
        roster = {"t_ms": t.column("t_ms").to_pylist(), "alive_ally": t.column("alive_ally").to_pylist()}
    box = minimap_roi_px(get_profile(man["source_profile"]), int(man["source"]["width"]),
                         int(man["source"]["height"]))
    lineup = load_lineup(sid, STORE.root)
    return session_lifetimes(sid, events, rounds, widget_scale(box[2] - box[0]), roster,
                             None, deaths=None, lineup=lineup,
                             gallery=load_identity_gallery(STORE.root) if lineup else None)


def score(sid: str, rows: list[dict], icon_best: dict) -> Counter:
    ents = {e["id"]: e for e in rows if e.get("kind") == "entity" and e.get("family") == "ally"}
    obs, frames = defaultdict(list), defaultdict(list)
    for o in rows:
        if o.get("kind") == "observation" and o.get("entity_id") in ents:
            obs[o["entity_id"]].append((o["t_ms"], o["observation_key"]))
            frames[o["t_ms"]].append(ents[o["entity_id"]].get("agent"))
    for k in obs:
        obs[k].sort()
    c = Counter()
    lo, hi = DEATH_WINDOW_MS
    for v in STORE.read_events("death", sid):
        if v.get("kind") != "death_verdict" or v.get("side") != "ally" or not v.get("victim"):
            continue
        t, a = float(v["t_ms"]), v["victim"]
        c["deaths"] += 1
        ends = [e for e in obs if t - lo <= obs[e][-1][0] <= t + hi]
        if len(ends) != 1:
            continue
        e = ends[0]
        c["bound"] += 1
        got = ents[e].get("agent")
        c["seg_right" if got == a else "seg_none" if got is None else "seg_wrong"] += 1
        for tt, key in obs[e]:
            if tt >= obs[e][-1][0] - 2000 and icon_best.get(key):
                c["icon_right" if icon_best[key] == a else "icon_wrong"] += 1
    c["ally_entities"] += len(ents)
    c["rounds"] += len({e["round_no"] for e in ents.values()})
    c["frames"] += len(frames)
    c["dup_frames"] += sum(1 for names in frames.values()
                           if any(n > 1 for n in Counter(x for x in names if x).values()))
    return c


def icon_best_guess(sid: str, events: list[dict]) -> dict:
    from reticle.adjudication.identity import claims_from_ally_icons
    icons = [e for e in events if e.get("kind") == "icon"]
    claims = claims_from_ally_icons(icons, load_lineup(sid, STORE.root),
                                    gallery=load_identity_gallery(STORE.root), session_id=sid)
    return {c["entity_id"].rsplit(":ally_icon:", 1)[-1]: (c.get("evidence") or {}).get("best_guess")
            for c in claims}


def main(sids: list[str], raw_out: str | None = None) -> dict:
    """Per-rate totals over `sids`; `raw_out` also writes the raw counts, so
    groups of sessions run apart can be summed."""
    total = {r: Counter() for r in RATES}
    for sid in sids:
        events = STORE.read_events("ally_icon", sid)
        if not events or float(events[0].get("hz") or 0) != 15.0:
            print(sid, "skipped: no 15 Hz ally_icon events", flush=True)
            continue
        if not load_lineup(sid, STORE.root):
            print(sid, "skipped: no stored lineup, so no teammates to name", flush=True)
            continue
        best = icon_best_guess(sid, events)
        for r in RATES:
            t0 = time.perf_counter()
            c = score(sid, build_entities(sid, decimate(events, round(15.0 / r))), best)
            c["seconds"] += time.perf_counter() - t0
            total[r] += c
        print(sid, "done", flush=True)
    if raw_out:
        import json
        Path(raw_out).write_text(json.dumps({str(r): dict(c) for r, c in total.items()}), encoding="utf-8")
    return summarise(total)


def summarise(total: dict) -> dict:
    out = {}
    for r, c in total.items():
        seg = c["seg_right"] + c["seg_wrong"]
        out[r] = {"deaths": c["deaths"], "bound": c["bound"],
                  "segment_right": f"{c['seg_right']}/{seg} ({c['seg_right'] / max(1, seg):.3f})",
                  "segment_unnamed": c["seg_none"],
                  "icon_right": round(c["icon_right"] / max(1, c["icon_right"] + c["icon_wrong"]), 3),
                  "ally_entities_per_round": round(c["ally_entities"] / max(1, c["rounds"]), 1),
                  "dup_frame_share": round(c["dup_frames"] / max(1, c["frames"]), 4),
                  "frames": c["frames"]}
        print(r, "Hz", out[r], flush=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--raw-out")
    ap.add_argument("--sum", nargs="+", help="raw count files to add up and report")
    a = ap.parse_args()
    if a.sum:
        import json
        total = {r: Counter() for r in RATES}
        for f in a.sum:
            for r, c in json.loads(Path(f).read_text(encoding="utf-8")).items():
                total[float(r)] += Counter(c)
        summarise(total)
    else:
        main(a.sids or sorted(p.stem for p in (STORE.root / "roi_cache" / "minimap"
                                              / "roi-cache-0.1.0").glob("*.json")), a.raw_out)
