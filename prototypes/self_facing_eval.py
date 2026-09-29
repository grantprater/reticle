r"""Score the teardrop facing and the ring fit's facing against the player's facing labels.

    .\.venv\Scripts\python.exe prototypes\self_facing_eval.py [--labels PATH] [--json PATH]

The scorer for `label_self_facing.py` (E4 of [the statistical
adjudicator](../docs/STATISTICAL_ADJUDICATOR.md)). For every labelled item it
recomputes the readers from the minimap crop cache (no decode), so it scores
the code as it stands, not the readings taken when the items were drawn:

- `teardrop`: `teardrop_tip.fit` from the self detector's best fit;
- `ring`: that detection's raw facing (`minimap.self_icons`), as E4 read it;
- `light`: E4's light-fitted facing, taken from `readings.json` as the items
  were drawn, since recomputing it needs the baked light at every frame.

Per reader and stratum it prints the median absolute error against the
player's facing, the flip rate (error above 90 degrees), the share within 10
and 20 degrees, and the median signed error. A label whose clicked centre lies
more than `ELSEWHERE_PX` from the ring marks another icon than the one asked
about and is reported apart. `cant_tell` stays out of scoring; `not_self`
counts against the item's stratum, which for `refused` says whether the
teardrop was right to refuse.

It writes to the store only with `--record` (one `metrics` row); `--json` writes
the per-item table.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import label_self_facing as lsf  # noqa: E402
import sliver_error_model as sem  # noqa: E402

VERSION = "self-facing-eval-0.1.0"
ELSEWHERE_PX = 8.0
READERS = ("teardrop", "ring", "light")


def readings(store: Path, index: list[dict], answers: dict) -> list[dict]:
    """One row per answered item: the label, the stratum and each reader's facing."""
    import teardrop_tip as tt
    pool = json.loads((lsf.items_dir(store) / "readings.json").read_text(encoding="utf-8"))["pool"]
    light = {lsf.item_key(r["session"], r["t_ms"]): r.get("light_deg") for p in pool.values() for r in p}
    rows = []
    by_sid = defaultdict(list)
    for it in index:
        if it["key"] in answers:
            by_sid[it["session"]].append(it)
    for sid, its in by_sid.items():
        s = sem.Session(sid)
        its.sort(key=lambda it: it["t_ms"])
        for it, (t, crop) in zip(its, s.crops([it["t_ms"] for it in its])):
            a = answers[it["key"]]
            det = tt.self_start(crop, s.floor)
            tf = tt.fit(crop, det["cx"], det["cy"]) if det else {"read": False, "reason": "no_self_detection"}
            row = {"key": it["key"], "session": sid, "t_ms": it["t_ms"], "stratum": it["stratum"],
                   "answer": a["answer"], "label_deg": a.get("facing_deg"),
                   "teardrop": tf["deg"] if tf.get("read") else None,
                   "teardrop_reason": None if tf.get("read") else tf.get("reason"),
                   "ring": det.get("facing") if det else None, "light": light.get(it["key"])}
            if a.get("centre_x") is not None:
                row["centre_off_px"] = float(np.hypot(a["centre_x"] - it["ring_x"], a["centre_y"] - it["ring_y"]))
                if tf.get("read"):
                    row["centre_vs_teardrop_px"] = float(np.hypot(a["centre_x"] - tf["x"], a["centre_y"] - tf["y"]))
            rows.append(row)
    return rows


def summary(errs) -> dict:
    e = np.abs(np.asarray(errs, float))
    if not len(e):
        return {"n": 0}
    return {"n": int(len(e)), "median_abs_deg": float(np.median(e)), "flip": float(np.mean(e > 90)),
            "within10": float(np.mean(e <= 10)), "within20": float(np.mean(e <= 20)),
            "median_signed_deg": float(np.median(sem._signed_deg(errs)))}


def score(rows: list[dict]) -> dict:
    here = [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= ELSEWHERE_PX]
    out = {"version": VERSION, "items": len(rows),
           "answers": dict(Counter(r["answer"] for r in rows)),
           "elsewhere": sum(r["answer"] == "facing" and r.get("centre_off_px", 0.0) > ELSEWHERE_PX for r in rows),
           "by_stratum_answers": {k: dict(Counter(r["answer"] for r in rows if r["stratum"] == k))
                                  for k in sorted({r["stratum"] for r in rows})},
           "readers": {}}
    strata = ["all_lotus"] + sorted({r["stratum"] for r in here})
    for name in READERS:
        out["readers"][name] = {}
        for st in strata:
            sub = [r for r in here if (r["session"] == lsf.LOTUS if st == "all_lotus" else r["stratum"] == st)]
            errs = [float(sem._signed_deg(r[name] - r["label_deg"])) for r in sub if r[name] is not None]
            d = summary(errs)
            d["unread"] = sum(r[name] is None for r in sub)
            out["readers"][name][st] = d
    # Which witness does the player side with where teardrop and light disagree?
    out["sides"] = {}
    for st in ("flip", "disagree"):
        dis = [r for r in here if r["stratum"] == st and r["teardrop"] is not None and r["light"] is not None]
        out["sides"][st] = dict(Counter(
            "teardrop" if abs(sem._signed_deg(r["teardrop"] - r["label_deg"]))
            < abs(sem._signed_deg(r["light"] - r["label_deg"])) else "light" for r in dis))
    offs = [r["centre_vs_teardrop_px"] for r in here if "centre_vs_teardrop_px" in r]
    out["centre_click_vs_teardrop_px_median"] = float(np.median(offs)) if offs else None
    return out


def show(res: dict) -> None:
    print(f"{res['items']} answered items: {res['answers']}; clicked another icon: {res['elsewhere']}")
    for st, c in res["by_stratum_answers"].items():
        print(f"  {st:9s} {c}")
    print(f"\n{'reader':9s} {'stratum':10s} {'n':>3s} {'unread':>6s} {'med|e|':>7s} {'flip':>5s} "
          f"{'<=10':>5s} {'<=20':>5s} {'bias':>6s}")
    for name, d in res["readers"].items():
        for st, v in d.items():
            if not v["n"]:
                print(f"{name:9s} {st:10s} {0:3d} {v['unread']:6d}")
                continue
            print(f"{name:9s} {st:10s} {v['n']:3d} {v['unread']:6d} {v['median_abs_deg']:7.1f} {v['flip']:5.2f} "
                  f"{v['within10']:5.2f} {v['within20']:5.2f} {v['median_signed_deg']:6.1f}")
    print(f"\nwhere teardrop and light disagree, the label is nearer: {res['sides']}")
    print(f"clicked centre vs teardrop centre, median px: {res['centre_click_vs_teardrop_px_median']}")


def record_summary(res: dict) -> None:
    """One `metrics` row: each reader per stratum, and which side the label takes."""
    import teardrop_tip as tt
    from reticle import metrics
    values = {}
    for name, d in res["readers"].items():
        for st, v in d.items():
            values[f"{name}_{st}_n"] = v["n"]
            values[f"{name}_{st}_unread"] = v["unread"]
            for k in ("median_abs_deg", "flip", "within10", "within20", "median_signed_deg"):
                if k in v:
                    values[f"{name}_{st}_{k}"] = round(v[k], 3)
    for st, c in res["sides"].items():
        for who, n in c.items():
            values[f"sides_{st}_{who}"] = n
    values["sides_teardrop"] = sum(c.get("teardrop", 0) for c in res["sides"].values())
    values["sides_n"] = sum(sum(c.values()) for c in res["sides"].values())
    values["elsewhere"] = res["elsewhere"]
    if res["centre_click_vs_teardrop_px_median"] is not None:
        values["centre_click_vs_teardrop_px_median"] = round(res["centre_click_vs_teardrop_px_median"], 3)
    metrics.record("self_facing_eval", part="labels", session=f"{lsf.LOTUS}+controls", values=values,
                   deps={"prototype": VERSION, "reader": tt.VERSION, "labels": Path(res["labels"]).name,
                         "elsewhere_px": ELSEWHERE_PX})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(sem.STORE))
    ap.add_argument("--labels", help="answers file (default: the store's labels/" + lsf.NAME + ".jsonl)")
    ap.add_argument("--json", type=Path, help="write the per-item rows and the summary here")
    ap.add_argument("--record", action="store_true", help="record the summary as one metrics row")
    args = ap.parse_args(argv)
    sem._below_normal()
    store = Path(args.store)
    path = Path(args.labels) if args.labels else lsf.labels_path(store)
    answers = lsf.load_answers(path)
    if not answers:
        print(f"no labels in {path}")
        return 1
    index = json.loads((lsf.items_dir(store) / "index.json").read_text(encoding="utf-8"))["items"]
    rows = readings(store, index, answers)
    res = score(rows)
    res["labels"] = str(path)
    show(res)
    if args.record:
        record_summary(res)
    if args.json:
        args.json.write_text(json.dumps({"summary": res, "rows": rows}, indent=1), encoding="utf-8")
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
