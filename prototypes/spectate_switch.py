r"""The death-camera period: the player's killfeed death to the spectate switch.

    .\.venv\Scripts\python.exe prototypes\spectate_switch.py measure <sid> [<sid> ...]
    .\.venv\Scripts\python.exe prototypes\spectate_switch.py record <sid> [<sid> ...]

Reads stored rows only (`l1/minimap`, `ally_icon`, `death`, the rounds
table) and decodes nothing. For each killfeed death of the player
(`adjudication.spectate.player_deaths`, the death owner's verdicts) it asks
the owner, `adjudication.spectate.switch_after`, when the yellow icon jumped
onto a teammate and moved with that teammate, and reports the time from the
death to that switch; where the widget was absent in between (the death
screen or the full map), the switch waits on the widget and the case is
counted apart. It also counts the rounds where the switch fires with no
stored death of the player (the fallback, prediction S3), and where the
yellow icon sits between the death and the switch (S2).

Run as `spectate-switch-0.1.0` under task `self-spike-20260929`; the numbers
back `domain/minimap.toml`'s `death-camera-period`. `wire: no`: it measures,
and `adjudication.spectate` is the owner the pipeline asks.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.adjudication import spectate  # noqa: E402
from reticle.minimap import minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "spectate-switch-0.1.0"
RUN_ID = "self-spike-20260929"
STORE = Store()
OUT = STORE.root / "analysis" / "self-spike-20260929"


def _date(man: dict) -> str:
    from reticle.cli import _date_of
    return _date_of(man)


def measure(sid: str) -> dict:
    man = STORE.read_manifest(sid)
    date = _date(man)
    box = minimap_roi_px(get_profile(man["source_profile"]), int(man["source"]["width"]),
                         int(man["source"]["height"]))
    sc = widget_scale(box[2] - box[0])
    tb = STORE.read_minimap(sid, date)
    rows = sorted(tb.select(["t_ms", "self_x", "self_y", "widget_drawn"]).to_pylist(),
                  key=lambda r: r["t_ms"])
    selves = [(r["t_ms"], r["self_x"], r["self_y"]) for r in rows]
    T = [r["t_ms"] for r in rows]
    mates = spectate.stored_teammates(STORE, sid)
    deaths = STORE.read_events("death", sid)
    rounds = STORE.read_rounds(sid, date).to_pylist()
    ivs = spectate.player_dead_intervals(deaths, rounds, selves, mates, sc,
                                         spectate.stored_roster(STORE, sid, date))
    cases = []
    for iv in ivs:
        if iv.rests_on != "killfeed_death":
            continue
        a = bisect.bisect_left(T, iv.t0_ms)
        k = a - 1
        while k >= 0 and rows[k]["self_x"] is None:
            k -= 1
        last = None if k < 0 else (rows[k]["self_x"], rows[k]["self_y"])
        end = iv.switch_ms if iv.switch_ms is not None else min(iv.t1_ms, iv.t0_ms + 20000)
        seg = [r for r in rows[a:] if r["t_ms"] < end]
        absent = sum(r["widget_drawn"] is False for r in seg)
        pts = [r for r in seg if r["self_x"] is not None]
        still = (None if last is None or not pts else
                 sum(np.hypot(r["self_x"] - last[0], r["self_y"] - last[1])
                     <= spectate.TEAMMATE_PX * sc for r in pts) / len(pts))
        cases.append({"round_no": iv.round_no, "death_s": round(iv.t0_ms / 1000, 2),
                      "switch_s": None if iv.switch_ms is None else round(iv.switch_ms / 1000, 2),
                      "period_s": (None if iv.switch_ms is None
                                   else round((iv.switch_ms - iv.t0_ms) / 1000, 2)),
                      "absent_frames_before": absent, "points_before": len(pts),
                      "share_at_last_place": None if still is None else round(still, 3),
                      "t1_why": iv.t1_why})
    fallback = [iv.row() for iv in ivs if iv.rests_on == "spectate_switch"]
    drawn = [c for c in cases if c["absent_frames_before"] == 0]
    found = [c["period_s"] for c in drawn if c["period_s"] is not None]
    res = {"session": sid, "version": VERSION, "spectate_version": spectate.SPECTATE_VERSION,
           "widget_scale": sc, "player_deaths": len(cases),
           "deaths_widget_drawn_throughout": len(drawn),
           "switch_found_widget_drawn": len(found),
           "period_s_median": round(float(np.median(found)), 2) if found else None,
           "period_s_q25": round(float(np.percentile(found, 25)), 2) if found else None,
           "period_s_q75": round(float(np.percentile(found, 75)), 2) if found else None,
           "periods_s": sorted(found),
           "deaths_with_widget_absent": len(cases) - len(drawn),
           "switch_found_after_absent": sum(c["period_s"] is not None for c in cases
                                            if c["absent_frames_before"]),
           "share_at_last_place_median": (round(float(np.median(
               [c["share_at_last_place"] for c in drawn if c["share_at_last_place"] is not None])), 3)
               if any(c["share_at_last_place"] is not None for c in drawn) else None),
           "fallback_rounds": len(fallback), "fallback": fallback, "cases": cases}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{sid}.spectate_switch.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def record_run(sid: str) -> None:
    from reticle import metrics
    m = json.loads((OUT / f"{sid}.spectate_switch.json").read_text(encoding="utf-8"))
    deps = {"script": metrics.fingerprint(measure, spectate.switch_after,
                                          spectate.player_dead_intervals,
                                          JUMP_PX=spectate.JUMP_PX, TEAMMATE_PX=spectate.TEAMMATE_PX,
                                          HOLD_MS=spectate.HOLD_MS, HOLD_FRAC=spectate.HOLD_FRAC),
            "version": VERSION, "spectate": spectate.SPECTATE_VERSION}
    values = {k: v for k, v in m.items() if not isinstance(v, (list, dict))
              and k not in ("session", "version", "spectate_version")}
    metrics.record("spectate_switch", part="death-camera", session=sid, values=values, deps=deps,
                   note="stored l1/minimap, ally_icon, death and rounds; no decode", run_id=RUN_ID)
    print(f"{sid}: recorded")


def pooled(sids: list[str]) -> dict:
    ms = [json.loads((OUT / f"{s}.spectate_switch.json").read_text(encoding="utf-8")) for s in sids]
    per = [p for m in ms for p in m["periods_s"]]
    return {"sessions": sids, "player_deaths": sum(m["player_deaths"] for m in ms),
            "deaths_widget_drawn_throughout": sum(m["deaths_widget_drawn_throughout"] for m in ms),
            "switch_found_widget_drawn": len(per),
            "period_s_median": round(float(np.median(per)), 2),
            "period_s_q25": round(float(np.percentile(per, 25)), 2),
            "period_s_q75": round(float(np.percentile(per, 75)), 2),
            "period_s_min": min(per), "period_s_max": max(per),
            "fallback_rounds": sum(m["fallback_rounds"] for m in ms)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["measure", "record", "pooled"])
    ap.add_argument("sessions", nargs="+")
    a = ap.parse_args(argv)
    if a.what == "pooled":
        res = pooled(a.sessions)
        print(json.dumps(res, indent=1))
        from reticle import metrics
        metrics.record("spectate_switch", part="death-camera-pooled", session="+".join(a.sessions),
                       values={k: v for k, v in res.items() if k != "sessions"},
                       deps={"version": VERSION, "spectate": spectate.SPECTATE_VERSION},
                       note="pooled over the sessions' measure files", run_id=RUN_ID)
        return 0
    for sid in a.sessions:
        if a.what == "measure":
            res = measure(sid)
            print(json.dumps({k: v for k, v in res.items() if k != "cases"}, indent=1))
            for c in res["cases"]:
                print("  ", c)
        else:
            record_run(sid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
