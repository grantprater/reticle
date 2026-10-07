r"""Whether the teardrop readers fit the player's facing labels better at the map's scale.

Task `one-transform-readers-20261007` (rows OT in the store's
`notes/predictions.jsonl`). Every map-drawn size is a base value times
`geometry.MapScale.scale` (widget scale x map zoom). The player's facing
labels on 331 px widgets were taken while the readers fitted the teardrop
at the widget scale alone (0.712 there, against the map's 0.637), and the
per-size tables in `reticle/teardrop.py` (`SELF_FACING_GATES`,
`LABELLED_SCALES`) were set from those fits.

* `facing` -- every labelled item of the 331 px sets (`self_facing_331_20260929`,
  `ally_facing_331_20260929`, `enemy_facing_331_20260929`) and the 465 px sets
  (`self_facing_lotus_20260928`, `icon_facing_20260928`), refitted from the
  minimap roi_cache at the ring the item was drawn at, once at the widget
  scale and once at the map's scale: the class's teardrop
  (`teardrop.fit_teardrop` for the self icon, `teardrop.fit_icon` for
  teammates and enemies). Per set and scale: the share read, the facing's
  median error against the player's and its flip rate (error over 90
  degrees), the centre's median distance from the player's clicked centre,
  and, for the self sets, the flip rate in NCC bands, which is what a facing
  gate is set from. The player's clicked tip-to-centre distance is an
  independent witness of the icon's drawn size: its median ratio between the
  331 px and 465 px sets is the icon's scale.
* `record` -- the `facing` table into the metrics ledger, series
  `one_transform_check`, part `facing/<set>/<scale>`.
* `truth SESSION --rows DIR --tag TAG` -- `replay_truth.score` with its
  `ally_icon` stream read from a `reticle trial --reader ally_icon
  --rows-out DIR` folder: the self fit against the replay and the
  teammates' teardrop facing, written to `OUT/truth_<TAG>_<SESSION>.json`.

Labels are the player's; the roi_cache only; no decode. The held-out capture
(cea8ecbc94ab) is refused. Not wired (`"wire": "no"`): an evaluation; the
change it measures is in `reticle/teardrop.py` and its callers.

    python prototypes/one_transform_check.py facing [--json OUT]
    python prototypes/one_transform_check.py record
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "one-transform-check-0.1.0"
TASK = "one-transform-readers-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
HELD_OUT = "cea8ecbc94ab"
SETS = {"self_facing_331_20260929": "self", "ally_facing_331_20260929": "ally",
        "enemy_facing_331_20260929": "enemy", "self_facing_lotus_20260928": "self",
        "icon_facing_20260928": None}
#: NCC bands the self flip rate is read in (a facing gate's candidates).
BANDS = ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 1.01))


def _idle() -> None:
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        pass


def _err(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _labels(name: str) -> list[dict]:
    p = STORE / "labels" / f"{name}.jsonl"
    rows = [json.loads(ln) for ln in p.open(encoding="utf-8")]
    rows = [r for r in rows if r.get("answer") == "facing" and r["session"] != HELD_OUT]
    for r in rows:
        r.setdefault("cls", SETS[name])
    return rows


def _crops(sid: str, ts: list[float]):
    """`{t_ms: crop}` from the minimap roi_cache at the held times nearest
    `ts`, the held times, and the widget and map scales."""
    from reticle import geometry
    from reticle import minimap_objects as mo
    from reticle.minimap import widget_scale
    from reticle.store import Store

    if sid == HELD_OUT:
        raise SystemExit(f"{sid}: the held-out match is never read by this task")
    ctx, why = mo.object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(f"{sid}: {why}")
    cache = ctx["cache"]
    x0, y0, x1, y1 = cache.rect_of("minimap")
    held = np.asarray(cache.holds(), float)
    want = sorted({float(held[np.argmin(np.abs(held - t))]) for t in ts})
    out = {}
    for smp in cache.samples(want, rois=["minimap"]):
        out[float(smp.t_ms)] = smp.frame[y0:y1, x0:x1].copy()
    ms = geometry.map_scale_of(sid, STORE)
    return out, held, widget_scale(x1 - x0), (None if ms is None else ms.scale)


def facing_table(json_out: str | None = None) -> int:
    from reticle import teardrop

    _idle()
    items = []
    for name in SETS:
        for r in _labels(name):
            items.append({**r, "set": name})
    by_sid: dict[str, list[dict]] = {}
    for r in items:
        by_sid.setdefault(r["session"], []).append(r)
    rows = []
    for sid, rs in sorted(by_sid.items()):
        crops, held, ws, mz = _crops(sid, [r["t_ms"] for r in rs])
        for r in rs:
            t = float(held[np.argmin(np.abs(held - r["t_ms"]))])
            crop = crops.get(t)
            tip = math.hypot(r["tip_x"] - r["centre_x"], r["tip_y"] - r["centre_y"])
            row = {"set": r["set"], "session": sid, "cls": r["cls"], "key": r["key"],
                   "dt_ms": round(t - r["t_ms"], 1), "tip_px": round(tip, 2),
                   "widget_scale": round(ws, 4), "map_scale": None if mz is None else round(mz, 4)}
            for tag, s in (("widget", ws), ("map", mz)):
                if crop is None or s is None:
                    row[tag] = None
                    continue
                if r["cls"] == "self":
                    f = teardrop.fit_teardrop(crop, r["ring_x"], r["ring_y"], scale=s)
                else:
                    f = teardrop.fit_icon(crop, r["cls"], r["ring_x"], r["ring_y"], scale=s)
                got = {"read": bool(f.get("read")), "ncc": f.get("ncc")}
                if "x" in f and f.get("deg") is not None:
                    got.update(err=round(_err(float(f["deg"]), float(r["facing_deg"])), 2),
                               centre_px=round(math.hypot(f["x"] - r["centre_x"],
                                                          f["y"] - r["centre_y"]), 2))
                row[tag] = got
            rows.append(row)
    table = summarise(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facing_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                           encoding="utf-8")
    (OUT / "facing.json").write_text(json.dumps(table, indent=1), encoding="utf-8")
    if json_out:
        Path(json_out).write_text(json.dumps(table, indent=1), encoding="utf-8")
    print(json.dumps(table, indent=1))
    return 0


def summarise(rows: list[dict]) -> dict:
    out = {"version": VERSION, "sets": {}}
    for name in SETS:
        rs = [r for r in rows if r["set"] == name]
        if not rs:
            continue
        d = {"n": len(rs), "tip_px_median": round(float(np.median([r["tip_px"] for r in rs])), 3)}
        for tag in ("widget", "map"):
            got = [r[tag] for r in rs if r.get(tag)]
            rd = [g for g in got if g["read"] and "err" in g]
            anyf = [g for g in got if "err" in g]
            e = {"read_share": round(len(rd) / max(len(got), 1), 4),
                 "n_read": len(rd)}
            if rd:
                err = np.array([g["err"] for g in rd])
                e.update(err_median=round(float(np.median(err)), 2),
                         flip_share=round(float((err > 90).mean()), 4),
                         within20=round(float((err <= 20).mean()), 4),
                         centre_px_median=round(float(np.median([g["centre_px"] for g in rd])), 3),
                         ncc_median=round(float(np.median([g["ncc"] for g in rd])), 4))
            if rs[0]["cls"] == "self" and anyf:
                bands = {}
                for lo, hi in BANDS:
                    b = [g for g in anyf if g.get("ncc") is not None and lo <= g["ncc"] < hi]
                    bands[f"{lo:.2f}-{min(hi, 1.0):.2f}"] = {
                        "n": len(b), "flips": int(sum(g["err"] > 90 for g in b))}
                e["ncc_bands"] = bands
            d[tag] = e
        out["sets"][name] = d
    small = [out["sets"][n]["tip_px_median"] for n in out["sets"] if "331" in n]
    big = [out["sets"][n]["tip_px_median"] for n in out["sets"] if "331" not in n]
    if small and big:
        out["tip_ratio_331_over_465"] = round(float(np.median(small) / np.median(big)), 4)
    return out


def record_metrics() -> int:
    from reticle.metrics import record as rec

    table = json.loads((OUT / "facing.json").read_text(encoding="utf-8"))
    for name, d in table["sets"].items():
        for tag in ("widget", "map"):
            e = d.get(tag) or {}
            vals = {k: v for k, v in e.items() if isinstance(v, (int, float))}
            for band, b in (e.get("ncc_bands") or {}).items():
                vals[f"band{band}.n"], vals[f"band{band}.flips"] = b["n"], b["flips"]
            vals["tip_px_median"] = d["tip_px_median"]
            rec("one_transform_check", part=f"facing/{name}/{tag}", session="labels",
                values=vals, deps={"version": VERSION},
                context={"task": TASK}, note="the player's facing labels refitted from the roi_cache")
    for f in sorted(OUT.glob("pings_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tag, e in d.items():
            if isinstance(e, dict):
                rec("one_transform_check", part=f"pings/{tag}", session=d["session"],
                    values={"confirmed": e["confirmed"], "in_rounds": e["in_rounds"],
                            "in_rounds_ci_lo": e["in_rounds_ci"][0],
                            "in_rounds_ci_hi": e["in_rounds_ci"][1]},
                    deps={"version": VERSION, "ping_version": e["version"]},
                    context={"task": TASK, "boot": "4000 round resamples"},
                    note="confirmed pings of a teardrop_refusals.py pings reread")
    for f in sorted(OUT.glob("smokes_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tag in ("widget", "map"):
            e = d[tag]
            rec("one_transform_check", part=f"smokes/{tag}", session=d["session"],
                values={"births": e["births"], "in_rounds": e["in_rounds"],
                        "in_rounds_ci_lo": e["in_rounds_ci"][0],
                        "in_rounds_ci_hi": e["in_rounds_ci"][1], "scale": e["scale"]},
                deps={"version": VERSION, "minimap_dark_version": d["minimap_dark_version"]},
                context={"task": TASK}, note="adjudication.smokes.tracks over stored minimap_dark")
    for f in sorted(OUT.glob("truth_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        s_, fa = d["self"], d["facing_ally_ally_icon"]
        rec("one_transform_check", part=f"truth/{d['tag']}", session=d["session"],
            values={"self_fits": s_["self_fits"], "self_recall": s_["recall"],
                    "self_err_px_median": s_["err_px"]["median"],
                    "self_err_px_p90": s_["err_px"]["p90"],
                    "self_err_cm_median": s_["err_cm"]["median"],
                    "ally_facing_n": fa["n"], "ally_facing_err_median": fa["err_deg"]["median"],
                    "ally_facing_flip_share": fa["flip_share"]},
            deps={"version": VERSION, **(d.get("ally_icon_stamp") or {})},
            context={"task": TASK}, note="replay_truth.score over a reticle trial ally_icon reread")
    if "tip_ratio_331_over_465" in table:
        rec("one_transform_check", part="facing/tip_ratio", session="labels",
            values={"ratio": table["tip_ratio_331_over_465"]}, deps={"version": VERSION},
            context={"task": TASK}, note="median clicked tip-to-centre distance, 331 px sets over 465 px sets")
    return 0


class _Redirect(type(Path())):
    """A store root whose `events/ally_icon` is another folder (a trial's rows)."""

    target: Path | None = None

    def with_segments(self, *segs):
        p = type(self)(*segs)
        if _Redirect.target is not None and p.parts[-2:] == ("events", "ally_icon") \
                and Path(*p.parts[:-2]) == STORE:
            return Path(_Redirect.target)
        return p


def truth(sid: str, rows_dir: str, tag: str) -> int:
    """`replay_truth.score` with its `ally_icon` stream read from a trial's
    `--rows-out` folder: the self fit against the replay (recall, error) and
    the teammates' teardrop facing (`ally_ally_icon`). Teammate positions
    rest on the stored `round_entity`, which no trial rebuilds, so they are
    not reported."""
    sys.path.insert(0, str(HERE))
    import replay_truth as rt

    _idle()
    if sid == HELD_OUT:
        raise SystemExit(f"{sid}: the held-out match is never read by this task")
    _Redirect.target = Path(rows_dir) / "events" / "ally_icon"
    rt.STORE = _Redirect(STORE)
    got = rt.score(sid)
    keep = {"tag": tag, "session": sid, "rows": rows_dir, "version": VERSION,
            "ally_icon_stamp": (got.get("stamps") or {}).get("ally_icon"),
            "self": got.get("self"), "frames": got.get("frames"),
            "facing_ally_ally_icon": (got.get("facing") or {}).get("ally_ally_icon")}
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"truth_{tag}_{sid}.json"
    p.write_text(json.dumps(keep, indent=1, default=float), encoding="utf-8")
    print(json.dumps(keep, indent=1, default=float)[:4000])
    return 0


PING_DIR = STORE / "analysis" / "teardrop-refusals-20261007"


def ping_counts(sid: str, tags: list[str], boot: int = 4000, seed: int = 20261007) -> dict:
    """Confirmed pings per kind in each `teardrop_refusals.py pings` reread
    (`PING_DIR/<tag>/ping/<sid>.jsonl`), with a 95% interval from a bootstrap
    over the stored rounds (a ping belongs to the round its first frame lies in)."""
    from reticle.cli import _date_of
    from reticle.store import Store

    st = Store(STORE)
    rounds = st.read_rounds(sid, _date_of(st.read_manifest(sid))).to_pylist()
    edges = np.array([[r["t_start_ms"], r["t_end_ms"]] for r in rounds], float)
    out = {"session": sid, "rounds": len(rounds)}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rounds), (boot, len(rounds)))
    for tag in tags:
        p = PING_DIR / tag / "ping" / f"{sid}.jsonl"
        per = np.zeros(len(rounds))
        kinds: dict = {}
        version = None
        for ln in p.open(encoding="utf-8"):
            e = json.loads(ln)
            if e.get("kind") == "coverage":
                version = e.get("ping_version")
                continue
            if e.get("event_kind") != "entity_state":
                continue
            version = version or e.get("producer_version")
            t = float(e["t_ms"])
            k = (e.get("metadata") or {}).get("kind")
            kinds[k] = kinds.get(k, 0) + 1
            j = np.flatnonzero((edges[:, 0] <= t) & (t <= edges[:, 1]))
            if j.size:
                per[j[0]] += 1
        s = per[idx].sum(1)
        out[tag] = {"version": version, "confirmed": int(sum(kinds.values())),
                    "in_rounds": int(per.sum()),
                    "in_rounds_ci": [int(np.percentile(s, 2.5)), int(np.percentile(s, 97.5))],
                    "by_kind": kinds}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"pings_{sid}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))
    return out


def smoke_births(sid: str, boot: int = 4000, seed: int = 20261007) -> dict:
    """`adjudication.smokes.tracks` over the stored `minimap_dark` rows at
    the widget's scale and at the map's: smoke births with a 95% interval
    from a bootstrap over the stored rounds. Only the adjudication's birth
    area and dedup radius move here; the stored rows' icon occluders were
    read at the widget's scale (minimap-dark-0.1.0), which a rerun of the
    reader over the cache would move too."""
    from reticle import geometry, lighting
    from reticle.adjudication import smokes
    from reticle.cli import _date_of
    from reticle.menu import stored_menu
    from reticle.minimap import widget_scale
    from reticle.store import Store

    _idle()
    if sid == HELD_OUT:
        raise SystemExit(f"{sid}: the held-out match is never read by this task")
    st = Store(STORE)
    rows = st.read_events("minimap_dark", sid)
    with np.load(geometry.path_of(sid, STORE)) as z:
        ref = lighting.reference(z)
    menu, _stamp = stored_menu(st, sid)
    rounds = st.read_rounds(sid, _date_of(st.read_manifest(sid))).to_pylist()
    edges = np.array([[r["t_start_ms"], r["t_end_ms"]] for r in rounds], float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rounds), (boot, len(rounds)))
    out = {"session": sid, "minimap_dark_version": rows[0].get("minimap_dark_version"),
           "rounds": len(rounds)}
    W = ref.known.shape[1]
    for tag, s in (("widget", widget_scale(W)), ("map", geometry.drawn_scale(sid, STORE, W)[0])):
        got = smokes.tracks(rows, ref.known, menu.at if menu is not None else None, s)
        per = np.zeros(len(rounds))
        for t in got:
            j = np.flatnonzero((edges[:, 0] <= t["first_ms"]) & (t["first_ms"] <= edges[:, 1]))
            if j.size:
                per[j[0]] += 1
        sb = per[idx].sum(1)
        out[tag] = {"scale": round(float(s), 4), "births": len(got), "in_rounds": int(per.sum()),
                    "in_rounds_ci": [int(np.percentile(sb, 2.5)), int(np.percentile(sb, 97.5))],
                    "observed_ends": sum(t["end_status"] == "observed" for t in got)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"smokes_{sid}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("facing")
    p.add_argument("--json")
    sub.add_parser("record")
    p = sub.add_parser("truth")
    p.add_argument("session")
    p.add_argument("--rows", required=True)
    p.add_argument("--tag", required=True)
    p = sub.add_parser("pings")
    p.add_argument("session")
    p.add_argument("--tags", required=True)
    p = sub.add_parser("smokes")
    p.add_argument("session")
    a = ap.parse_args(argv)
    if a.cmd == "smokes":
        smoke_births(a.session)
        return 0
    if a.cmd == "pings":
        ping_counts(a.session, a.tags.split(","))
        return 0
    if a.cmd == "facing":
        return facing_table(a.json)
    if a.cmd == "truth":
        return truth(a.session, a.rows, a.tag)
    return record_metrics()


if __name__ == "__main__":
    raise SystemExit(main())
