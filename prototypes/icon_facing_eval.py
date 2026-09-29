r"""Score the teardrop and the ring fit's facing on ally and enemy icons against the player's labels.

    .\.venv\Scripts\python.exe prototypes\icon_facing_eval.py [--labels PATH] [--json PATH]
        [--exclude PATH] [--record]

The scorer for `label_icon_facing.py`. For every labelled item it recomputes
the readers from the minimap crop cache (no decode), so it scores the code as
it stands, not the readings taken when the items were drawn. It finds the
item's detection again (the class's detector, nearest the stored detector
centre, within `MATCH_PX`) and reads:

- `teardrop`: `icon_teardrop.fit` for the item's class;
- `ring`: that detection's raw facing, as `minimap.fit_ring` reads it;
- `ring_lobe` (allies only): the ring facing after `cone.resolve_lobe` on the
  frame's lit mask, as `team_vision` 0.3.0 handed it to the tracker. Enemy
  light is not drawn, so enemies have no such reader;
- `wired`: what the wired consumers cast per frame since `team-vision-0.5.0`,
  the promoted reader at the widget's scale (`teardrop.IconPoseReader`) and,
  for allies where it is unread and `team_vision.RING_FALLBACK` holds, the
  `ring_lobe` facing.

Per class, reader and stratum it prints the median absolute error against
the player's facing, the flip rate (error above 90 degrees), the share within
10 and 20 degrees, and the median signed error. A label whose clicked centre
lies more than `ELSEWHERE_PX` from the ring marks another icon than the one
asked about, and one ringed in another class's colour (`colour_at`: the red
key catches teammates) is another class; both are reported apart. `cant_tell` stays out of scoring;
`not_icon` answers are counted per stratum and per teardrop verdict, which
says whether the teardrop was right to refuse.

`--exclude` names a JSON file whose `keys` list items to leave out of every
count, such as the items that look like ability glyphs rather than agent
icons (the store's `labels/icon_facing_20260928/ability_candidates.json`).
The label file is never edited; the exclusion lives beside it and names who
proposed it and whether the player confirmed it.

It writes to the store only with `--record` (one `metrics` row, part `labels`,
or `labels-excl` with `--exclude`); `--json` writes the per-item table.

`--set ally_facing_331_20260929` scores the 331 px ally set instead
(`label_icon_facing.py`), from the readings frozen in the set's hidden
`manifest.json` when the items were drawn: the teardrop, the ring fit's raw
facing and its lobe. It prints each reader's median error, flip rate and
within-10/20 shares over all items, per stratum (`flip`, `agree`), per
session and per NCC tercile, and on the flip stratum which reader lies
nearer the player's facing. `--record` writes part `labels-331`.
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

# 0.3.0: the `wired` reader, what the wired consumers cast per frame.
VERSION = "icon-facing-eval-0.3.0"
ELSEWHERE_PX = 8.0
MATCH_PX = 3.0
READERS = ("teardrop", "ring", "ring_lobe", "wired")


def readings(index: list[dict], answers: dict) -> list[dict]:
    """One row per answered item: the label, the stratum and each reader's facing."""
    from reticle import cone, lighting
    from reticle.minimap import widget_scale
    from reticle.teardrop import IconPoseReader
    from reticle.team_vision import RING_FALLBACK
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
            # What the wired consumer casts this frame: the promoted reader at
            # the widget's scale (`teardrop.IconPoseReader`), and for allies
            # `team_vision`'s ring-fit fallback, the lobe the light resolves.
            wired = None
            if det is not None:
                pose = IconPoseReader(cls, widget_scale(crop.shape[1])).read(crop, det["cx"], det["cy"])
                wired = pose["deg"] if pose["deg"] is not None else (lobe if RING_FALLBACK else None)
            row = {"key": it["key"], "session": sid, "t_ms": it["t_ms"], "cls": cls,
                   "stratum": it["stratum"], "stacked": it.get("stacked", False),
                   "answer": a["answer"], "label_deg": a.get("facing_deg"),
                   "teardrop": tf["deg"] if tf.get("read") else None,
                   "teardrop_reason": None if tf.get("read") else tf.get("reason"),
                   "ring": det.get("facing") if det else None,
                   "ring_lobe": lobe, "wired": wired}
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


def record_summary(res: dict, excluded: Path | None) -> None:
    """One `metrics` row: each class, reader and stratum, and the answer counts."""
    from reticle import metrics
    values = {"items": res["items"]}
    for cls, c in res["classes"].items():
        values[f"{cls}_items"] = c["items"]
        for a, n in c["answers"].items():
            values[f"{cls}_answer_{a}"] = n
        values[f"{cls}_elsewhere"] = c["elsewhere"]
        values[f"{cls}_other_colour"] = sum(c["other_colour"].values())
        for v, a in c["answers_by_teardrop"].items():
            for k, n in a.items():
                values[f"{cls}_teardrop_{v}_{k}"] = n
        for name, d in c["readers"].items():
            for st, v in d.items():
                values[f"{cls}_{name}_{st}_n"] = v["n"]
                values[f"{cls}_{name}_{st}_unread"] = v["unread"]
                for k in ("median_abs_deg", "flip", "within10", "within20", "median_signed_deg"):
                    if k in v:
                        values[f"{cls}_{name}_{st}_{k}"] = round(v[k], 3)
    deps = {"prototype": VERSION, "reader": it_.VERSION, "labels": Path(res["labels"]).name,
            "elsewhere_px": ELSEWHERE_PX, "match_px": MATCH_PX}
    context = {}
    if excluded is not None:
        deps["exclude"] = excluded.name
        context["excluded"] = res["excluded"]
    metrics.record("icon_facing_eval", part="labels-excl" if excluded is not None else "labels",
                   session="+".join(lif.SESSIONS), values=values, deps=deps, context=context)


# ---------------------------------------------------------------- the 331 px ally set

#: `ELSEWHERE_PX` at the 331 px widget's scale (331 / 465 of it).
ELSEWHERE_331_PX = 6.0
READERS_331 = ("teardrop", "ring", "ring_lobe")


def rows_331(manifest: list[dict], answers: dict) -> list[dict]:
    """One row per answered item: the label and the readings frozen in the hidden manifest."""
    rows = []
    for m in manifest:
        a = answers.get(m["key"])
        if a is None:
            continue
        row = {"key": m["key"], "session": m["session"], "t_ms": m["t_ms"], "stratum": m["stratum"],
               "ncc": m["ncc"], "ncc_bin": m["ncc_bin"], "stacked": m.get("stacked", False),
               "answer": a["answer"], "label_deg": a.get("facing_deg"),
               "teardrop": m["teardrop_deg"], "ring": m["ring_deg"], "ring_lobe": m["ring_lobe_deg"]}
        if a.get("centre_x") is not None:
            row["centre_off_px"] = float(np.hypot(a["centre_x"] - m["ring_x"], a["centre_y"] - m["ring_y"]))
            row["centre_vs_teardrop_px"] = float(np.hypot(a["centre_x"] - m["teardrop_x"],
                                                          a["centre_y"] - m["teardrop_y"]))
            row["centre_vs_ring_px"] = float(np.hypot(a["centre_x"] - m["det_x"], a["centre_y"] - m["det_y"]))
        for name in READERS_331:
            if row["label_deg"] is not None and row[name] is not None:
                row[f"{name}_err"] = float(sem._signed_deg(row[name] - row["label_deg"]))
        rows.append(row)
    return rows


def score_331(rows: list[dict], n_items: int) -> dict:
    here = [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= ELSEWHERE_331_PX]
    out = {"version": VERSION, "items": n_items, "answered": len(rows),
           "answers": dict(Counter(r["answer"] for r in rows)),
           "elsewhere": sum(r["answer"] == "facing" and r.get("centre_off_px", 0.0) > ELSEWHERE_331_PX
                            for r in rows),
           "by_stratum_answers": {k: dict(Counter(r["answer"] for r in rows if r["stratum"] == k))
                                  for k in sorted({r["stratum"] for r in rows})},
           "readers": {}}
    groups = {"all": here}
    for k in sorted({r["stratum"] for r in here}):
        groups[k] = [r for r in here if r["stratum"] == k]
    for sid in sorted({r["session"] for r in here}):
        groups[sid] = [r for r in here if r["session"] == sid]
    for b in sorted({r["ncc_bin"] for r in here}):
        groups[f"ncc_t{b}"] = [r for r in here if r["ncc_bin"] == b]
        groups[f"flip_ncc_t{b}"] = [r for r in here if r["ncc_bin"] == b and r["stratum"] == "flip"]
    for name in READERS_331:
        out["readers"][name] = {g: summary([r[f"{name}_err"] for r in sub if f"{name}_err" in r])
                                for g, sub in groups.items()}
    # Where the readers disagree, which one the player sides with.
    flips = [r for r in here if r["stratum"] == "flip" and "teardrop_err" in r and "ring_lobe_err" in r]
    out["flip_sides"] = {"n": len(flips),
                         "teardrop": sum(abs(r["teardrop_err"]) < abs(r["ring_lobe_err"]) for r in flips),
                         "ring_lobe": sum(abs(r["ring_lobe_err"]) < abs(r["teardrop_err"]) for r in flips),
                         "neither_within_45": sum(min(abs(r["teardrop_err"]), abs(r["ring_lobe_err"])) > 45
                                                  for r in flips)}
    for k in ("centre_off_px", "centre_vs_teardrop_px", "centre_vs_ring_px"):
        v = [r[k] for r in here if k in r]
        out[k + "_median"] = float(np.median(v)) if v else None
    return out


def show_331(res: dict) -> None:
    print(f"\n== 331 px allies: {res['answered']} of {res['items']} items answered {res['answers']}; "
          f"clicked another icon (> {ELSEWHERE_331_PX} px from the ring): {res['elsewhere']}")
    for st, a in res["by_stratum_answers"].items():
        print(f"  {st:9s} {a}")
    print(f"\n  {'reader':9s} {'group':15s} {'n':>3s} {'med|e|':>7s} {'flip':>5s} {'<=10':>5s} {'<=20':>5s} "
          f"{'bias':>6s}")
    for name, d in res["readers"].items():
        for g, v in d.items():
            if not v["n"]:
                print(f"  {name:9s} {g:15s} {0:3d}")
                continue
            print(f"  {name:9s} {g:15s} {v['n']:3d} {v['median_abs_deg']:7.1f} {v['flip']:5.2f} "
                  f"{v['within10']:5.2f} {v['within20']:5.2f} {v['median_signed_deg']:6.1f}")
    fs = res["flip_sides"]
    print(f"\n  flip stratum, nearer the label: teardrop {fs['teardrop']}, ring_lobe {fs['ring_lobe']} "
          f"of {fs['n']}; neither within 45 deg: {fs['neither_within_45']}")
    print(f"  clicked centre, median px: from the ring {res['centre_off_px_median']}, "
          f"from the teardrop {res['centre_vs_teardrop_px_median']}, "
          f"from the ring fit {res['centre_vs_ring_px_median']}")


def record_331(res: dict) -> None:
    from reticle import metrics
    values = {"items": res["items"], "answered": res["answered"], "elsewhere": res["elsewhere"]}
    for a, n in res["answers"].items():
        values[f"answer_{a}"] = n
    for name, d in res["readers"].items():
        for g, v in d.items():
            values[f"{name}_{g}_n"] = v["n"]
            for k in ("median_abs_deg", "flip", "within10", "within20", "median_signed_deg"):
                if k in v:
                    values[f"{name}_{g}_{k}"] = round(v[k], 3)
    for k, n in res["flip_sides"].items():
        values[f"flip_sides_{k}"] = n
    metrics.record("icon_facing_eval", part="labels-331", session="+".join(lif.QUOTA_331),
                   values=values, deps={"prototype": VERSION, "labels": Path(res["labels"]).name,
                                        "manifest": lif.VERSION_331, "elsewhere_px": ELSEWHERE_331_PX})


def main_331(args, store: Path) -> int:
    idir = lif.items_dir(store, lif.SET_331)
    path = Path(args.labels) if args.labels else lif.labels_path(store, lif.SET_331)
    answers = lif.load_answers(path)
    if not answers:
        print(f"no labels in {path}")
        return 1
    manifest = json.loads(Path(args.manifest or idir / "manifest.json").read_text(encoding="utf-8"))["items"]
    rows = rows_331(manifest, answers)
    unknown = sorted(set(answers) - {m["key"] for m in manifest})
    if unknown:
        print(f"{len(unknown)} labelled keys are not in the manifest: {unknown[:3]}")
    res = score_331(rows, len(manifest))
    res["labels"] = str(path)
    show_331(res)
    if args.record:
        record_331(res)
    if args.json:
        args.json.write_text(json.dumps({"summary": res, "rows": rows}, indent=1), encoding="utf-8")
        print("wrote", args.json)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(sem.STORE))
    ap.add_argument("--set", choices=lif.SETS, default=lif.NAME,
                    help=f"item set; {lif.SET_331} scores the readings frozen in its hidden manifest")
    ap.add_argument("--manifest", type=Path, help=f"{lif.SET_331}: manifest file (default: the set's own)")
    ap.add_argument("--labels", help="answers file (default: the store's labels/" + lif.NAME + ".jsonl)")
    ap.add_argument("--json", type=Path, help="write the per-item rows and the summary here")
    ap.add_argument("--exclude", type=Path, help="JSON file whose `keys` list items left out of scoring")
    ap.add_argument("--record", action="store_true", help="record the summary as one metrics row")
    args = ap.parse_args(argv)
    sem._below_normal()
    store = Path(args.store)
    if args.set == lif.SET_331:
        return main_331(args, store)
    path = Path(args.labels) if args.labels else lif.labels_path(store)
    answers = lif.load_answers(path)
    if not answers:
        print(f"no labels in {path}")
        return 1
    index = json.loads((lif.items_dir(store) / "index.json").read_text(encoding="utf-8"))["items"]
    excluded = []
    if args.exclude:
        drop = set(json.loads(args.exclude.read_text(encoding="utf-8"))["keys"])
        excluded = sorted(k for k in drop if k in answers)
        answers = {k: v for k, v in answers.items() if k not in drop}
        print(f"excluding {len(excluded)} of {len(drop)} listed items ({args.exclude})")
    rows = readings(index, answers)
    res = score(rows)
    res["labels"] = str(path)
    res["excluded"] = excluded
    show(res)
    if args.record:
        record_summary(res, args.exclude)
    if args.json:
        args.json.write_text(json.dumps({"summary": res, "rows": rows}, indent=1), encoding="utf-8")
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
