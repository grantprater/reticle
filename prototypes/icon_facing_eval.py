r"""Score the teardrop and the ring fit's facing on ally and enemy icons against the player's labels.

    .\.venv\Scripts\python.exe prototypes\icon_facing_eval.py [--labels PATH] [--json PATH]

The scorer for `label_icon_facing.py`. For every labelled item it recomputes
the readers from the minimap crop cache (no decode), so it scores the code as
it stands, not the readings taken when the items were drawn. It finds the
item's detection again (the class's detector, nearest the stored detector
centre, within `MATCH_PX`) and reads:

- `teardrop`: `icon_teardrop.fit` for the item's class;
- `ring`: that detection's raw facing, as `minimap.fit_ring` reads it;
- `ring_lobe` (allies only): the ring facing after `cone.resolve_lobe` on the
  frame's lit mask, as `team_vision` hands it to the tracker. Enemy light is
  not drawn, so enemies have no such reader.

Per class, reader and stratum it prints the median absolute error against
the player's facing, the flip rate (error above 90 degrees), the share within
10 and 20 degrees, and the median signed error. A label whose clicked centre
lies more than `ELSEWHERE_PX` from the ring marks another icon than the one
asked about, and one ringed in another class's colour (`colour_at`: the red
key catches teammates) is another class; both are reported apart. `cant_tell` stays out of scoring;
`not_icon` answers are counted per stratum and per teardrop verdict, which
says whether the teardrop was right to refuse.

It writes nothing to the store; `--json` writes the per-item table.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import icon_teardrop as it_  # noqa: E402
import label_icon_facing as lif  # noqa: E402

VERSION = "icon-facing-eval-0.1.0"
ELSEWHERE_PX = 8.0
MATCH_PX = 3.0
READERS = ("teardrop", "ring", "ring_lobe")


def readings(index: list[dict], answers: dict) -> list[dict]:
    """One row per answered item: the label, the stratum and each reader's facing."""
    from reticle import cone, lighting
    rows = []
    by_sid = defaultdict(list)
    for it in index:
        if it["key"] in answers:
            by_sid[it["session"]].append(it)
    for sid, its in by_sid.items():
        s = sem.Session(sid)
        crops = dict(s.crops(sorted({it["t_ms"] for it in its})))
        for it in its:
            crop = crops[it["t_ms"]]
            a = answers[it["key"]]
            cls = it["cls"]
            dets = it_.detections(crop, cls, s)
            det = min(dets, key=lambda d: math.hypot(d["cx"] - it["det_x"], d["cy"] - it["det_y"]),
                      default=None)
            if det is not None and math.hypot(det["cx"] - it["det_x"], det["cy"] - it["det_y"]) > MATCH_PX:
                det = None
            if det is None:
                tf = {"read": False, "reason": "detection_lost"}
            else:
                tf = it_.fit(crop, cls, det["cx"], det["cy"])
            lobe = None
            if det is not None and cls == "ally" and det.get("facing") is not None:
                lit = lighting.lit_mask(crop, s.ref)
                lobe = cone.resolve_lobe(s.passable, lit, [dict(det)], visible=s.floor)[0].get("facing")
            row = {"key": it["key"], "session": sid, "t_ms": it["t_ms"], "cls": cls,
                   "stratum": it["stratum"], "stacked": it.get("stacked", False),
                   "answer": a["answer"], "label_deg": a.get("facing_deg"),
                   "teardrop": tf["deg"] if tf.get("read") else None,
                   "teardrop_reason": None if tf.get("read") else tf.get("reason"),
                   "ring": det.get("facing") if det else None,
                   "ring_lobe": lobe}
            if a.get("centre_x") is not None:
                row["label_colour"] = colour_at(crop, a["centre_x"], a["centre_y"])
                row["centre_off_px"] = float(np.hypot(a["centre_x"] - it["ring_x"], a["centre_y"] - it["ring_y"]))
                if tf.get("read"):
                    row["centre_vs_teardrop_px"] = float(np.hypot(a["centre_x"] - tf["x"], a["centre_y"] - tf["y"]))
                if det is not None:
                    row["centre_vs_ring_px"] = float(np.hypot(a["centre_x"] - det["cx"], a["centre_y"] - det["cy"]))
            rows.append(row)
    return rows


def colour_at(crop: np.ndarray, x: float, y: float) -> str:
    """Which key rings the player's clicked centre: `ally`, `enemy` or `self`.

    The enemy detector's red key also catches teammates, and the player
    answers for the icon he sees; a label whose ring is another class's
    colour is scored apart (`other_colour`), not against the item's class.
    Mean key over the annulus 8.5-11.5 px round the click, which holds the
    ring at every class's radius.
    """
    import teardrop_tip as tt
    h, w = crop.shape[:2]
    x0, x1, y0, y1 = max(0, int(x) - 12), min(w, int(x) + 13), max(0, int(y) - 12), min(h, int(y) + 13)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rho = np.hypot(xx - x, yy - y)
    band = (rho >= 8.5) & (rho <= 11.5)
    sub = crop[y0:y1, x0:x1]
    keys = {"ally": it_.tealness(sub), "enemy": it_.redness(sub), "self": tt.yellowness(sub)}
    return max(keys, key=lambda k: float(keys[k][band].mean()) if band.any() else 0.0)


def summary(errs) -> dict:
    e = np.abs(np.asarray(errs, float))
    if not len(e):
        return {"n": 0}
    return {"n": int(len(e)), "median_abs_deg": float(np.median(e)), "flip": float(np.mean(e > 90)),
            "within10": float(np.mean(e <= 10)), "within20": float(np.mean(e <= 20)),
            "median_signed_deg": float(np.median(sem._signed_deg(errs)))}


def score(rows: list[dict]) -> dict:
    here = [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= ELSEWHERE_PX
            and r.get("label_colour", r["cls"]) == r["cls"]]
    out = {"version": VERSION, "items": len(rows), "classes": {}}
    for cls in ("ally", "enemy"):
        mine = [r for r in rows if r["cls"] == cls]
        h = [r for r in here if r["cls"] == cls]
        c = {"items": len(mine), "answers": dict(Counter(r["answer"] for r in mine)),
             "elsewhere": sum(r["answer"] == "facing" and r.get("centre_off_px", 0.0) > ELSEWHERE_PX
                              for r in mine),
             "other_colour": dict(Counter(r["label_colour"] for r in mine if r["answer"] == "facing"
                                          and r.get("label_colour", cls) != cls)),
             "by_stratum_answers": {k: dict(Counter(r["answer"] for r in mine if r["stratum"] == k))
                                    for k in sorted({r["stratum"] for r in mine})},
             # Was the teardrop right to refuse? Answers split by its verdict.
             "answers_by_teardrop": {v: dict(Counter(r["answer"] for r in mine
                                                     if (r["teardrop"] is not None) == (v == "read")))
                                     for v in ("read", "refused")},
             "refusal_reasons": dict(Counter(r["teardrop_reason"] for r in mine if r["teardrop"] is None)),
             "readers": {}}
        strata = ["all"] + sorted({r["stratum"] for r in h}) + ["stacked_any"]
        for name in READERS:
            if name == "ring_lobe" and cls != "ally":
                continue
            c["readers"][name] = {}
            for st in strata:
                sub = (h if st == "all" else [r for r in h if r["stacked"]] if st == "stacked_any"
                       else [r for r in h if r["stratum"] == st])
                errs = [float(sem._signed_deg(r[name] - r["label_deg"])) for r in sub if r[name] is not None]
                d = summary(errs)
                d["unread"] = sum(r[name] is None for r in sub)
                c["readers"][name][st] = d
        for k in ("centre_vs_teardrop_px", "centre_vs_ring_px"):
            v = [r[k] for r in h if k in r]
            c[k + "_median"] = float(np.median(v)) if v else None
        out["classes"][cls] = c
    return out


def show(res: dict) -> None:
    for cls, c in res["classes"].items():
        print(f"\n== {cls}: {c['items']} answered items {c['answers']}; clicked another icon: {c['elsewhere']}; "
              f"ringed in another class's colour: {c['other_colour']}")
        for st, a in c["by_stratum_answers"].items():
            print(f"  {st:9s} {a}")
        print(f"  answers where the teardrop reads: {c['answers_by_teardrop']['read']}; "
              f"refuses: {c['answers_by_teardrop']['refused']} {c['refusal_reasons']}")
        print(f"\n  {'reader':9s} {'stratum':11s} {'n':>3s} {'unread':>6s} {'med|e|':>7s} {'flip':>5s} "
              f"{'<=10':>5s} {'<=20':>5s} {'bias':>6s}")
        for name, d in c["readers"].items():
            for st, v in d.items():
                if not v["n"]:
                    print(f"  {name:9s} {st:11s} {0:3d} {v['unread']:6d}")
                    continue
                print(f"  {name:9s} {st:11s} {v['n']:3d} {v['unread']:6d} {v['median_abs_deg']:7.1f} "
                      f"{v['flip']:5.2f} {v['within10']:5.2f} {v['within20']:5.2f} {v['median_signed_deg']:6.1f}")
        print(f"  clicked centre vs teardrop centre, median px: {c['centre_vs_teardrop_px_median']}; "
              f"vs ring centre: {c['centre_vs_ring_px_median']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(sem.STORE))
    ap.add_argument("--labels", help="answers file (default: the store's labels/" + lif.NAME + ".jsonl)")
    ap.add_argument("--json", type=Path, help="write the per-item rows and the summary here")
    args = ap.parse_args(argv)
    sem._below_normal()
    store = Path(args.store)
    path = Path(args.labels) if args.labels else lif.labels_path(store)
    answers = lif.load_answers(path)
    if not answers:
        print(f"no labels in {path}")
        return 1
    index = json.loads((lif.items_dir(store) / "index.json").read_text(encoding="utf-8"))["items"]
    rows = readings(index, answers)
    res = score(rows)
    res["labels"] = str(path)
    show(res)
    if args.json:
        args.json.write_text(json.dumps({"summary": res, "rows": rows}, indent=1), encoding="utf-8")
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
