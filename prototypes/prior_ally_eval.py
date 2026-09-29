r"""Score the player's blind labels of the ally track-window re-search: presence only.

    .\.venv\Scripts\python.exe prototypes\prior_ally_eval.py [--record]

`prototypes/label_prior_ally.py` showed the player 60 places, blind: fits the
re-search recovered (`recovered`), icons the reader kept (`ordinary`), and
places with no teammate (`control`), and asked whether a teammate's icon sat
under the ring. This joins his answers (`labels/prior_ally/<session>.jsonl`,
last row per key) to the batch index and reports, per kind, the share he
called a teammate with a Wilson 95% interval. `unsure` is kept out of the
share; `other` counts as not a teammate, as the labeller says.

Presence only. He marked no centres, so the fits' positions are not scored;
his remark that most real teammates sat close to a correct bounding is a
qualitative note (~/reticle-notes/DOMAIN.md), not a measurement.

Reads stored rows only; writes nothing unless `--record` (a `metrics` row).
Unwired (`"wire": "no"`, task `prior-ally-20260929` in the store's
`notes/predictions.jsonl`, P7).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import label_prior_ally as lpa  # noqa: E402
from reticle.metrics import wilson  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "prior-ally-eval-0.1.0"
KINDS = ("recovered", "ordinary", "control")
#: P7 as logged before the labels: recovered >= 0.80 teammate, control
#: <= 0.10, ordinary >= 0.95, unsure excluded.
P7 = {"recovered": (">=", 0.80), "control": ("<=", 0.10), "ordinary": (">=", 0.95)}


def load(store_root: Path) -> list[dict]:
    index = json.loads((lpa.out_dir(store_root) / "index.json").read_text(encoding="utf-8"))
    answers = lpa.load_answers(store_root, sorted({it["session_id"] for it in index}))
    return [{**it, "label": answers.get(it["key"])} for it in index]


def table(items: list[dict], by=lambda it: it["kind"]) -> dict:
    out = {}
    for it in items:
        g = out.setdefault(by(it), Counter())
        lab = it["label"]
        if lab is None:
            g["unanswered"] += 1
        elif lab["answer"] == "unsure":
            g["unsure"] += 1
        else:
            g["n"] += 1
            g["teammate"] += lab["answer"] == "teammate"
            g["other"] += lab["answer"] == "other"
    for g in out.values():
        g["share"] = g["teammate"] / g["n"] if g["n"] else float("nan")
        g["lo"], g["hi"] = wilson(g["teammate"], g["n"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    except Exception:
        pass
    root = Path(args.store)
    items = load(root)
    tab = table(items)
    print(f"{'kind':10s} {'n':>3s} {'teammate':>8s} {'share':>6s}  95% interval   unsure  other  P7")
    held = {}
    for kind in KINDS:
        g = tab.get(kind, Counter())
        op, bound = P7[kind]
        ok = (g["share"] >= bound) if op == ">=" else (g["share"] <= bound)
        held[kind] = bool(ok)
        print(f"{kind:10s} {g['n']:3d} {g['teammate']:8d} {g['share']:6.3f}  "
              f"[{g['lo']:.3f}, {g['hi']:.3f}]  {g['unsure']:6d} {g['other']:6d}  "
              f"{op} {bound:.2f}: {'held' if ok else 'failed'}")
    print("\nper session")
    for key, g in sorted(table(items, lambda it: (it["kind"], it["session_id"])).items()):
        print(f"  {key[0]:10s} {key[1]}  {g['teammate']}/{g['n']}  [{g['lo']:.2f}, {g['hi']:.2f}]")
    print("\nrecovered, by what the window relaxed")
    rec = [it for it in items if it["kind"] == "recovered"]
    for key, g in sorted(table(rec, lambda it: "+".join(it["source"]["fit"]["relaxed"])).items()):
        print(f"  {key:40s} {g['teammate']}/{g['n']}")
    print("\nrecovered, by time since the track's last fit")
    for key, g in sorted(table(rec, lambda it: "dt<0.5s" if it["source"]["dt_s"] < 0.5
                               else "dt>=0.5s").items()):
        print(f"  {key:10s} {g['teammate']}/{g['n']}")
    print("\ndisagreements with the kind (for the sheets)")
    for it in items:
        lab = it["label"]
        if lab is None or lab["answer"] == "unsure":
            continue
        tm = lab["answer"] == "teammate"
        if (it["kind"] == "control" and tm) or (it["kind"] == "ordinary" and not tm):
            print(f"  {it['kind']:9s} {it['session_id']} t={it['t_ms'] / 1000:.2f}s "
                  f"({it['x']:.0f},{it['y']:.0f}) answered {lab['answer']}  image {it['image']}")
    centres = sum(1 for it in items if it["label"] and it["label"].get("centre"))
    print(f"\ncentres marked: {centres} (position is not scored)")
    if args.record:
        from reticle import metrics
        values = {}
        for kind in KINDS:
            g = tab.get(kind, Counter())
            values.update({f"{kind}_n": g["n"], f"{kind}_teammate": g["teammate"],
                           f"{kind}_share": round(g["share"], 4),
                           f"{kind}_unsure": g["unsure"]})
        metrics.record("prior_ally_eval", part="blind-presence", session="a06f04a0059f+5822b6646448",
                       values=values,
                       ci={f"{k}_share": [round(tab[k]["lo"], 4), round(tab[k]["hi"], 4)]
                           for k in KINDS if k in tab},
                       deps={"script": VERSION, "batch": lpa.BATCH, "class_set": lpa.CLASS_SET,
                             "search": "ally-prior-search-0.2.0 recovered rows"},
                       note="player's blind labels, presence only; no centres marked",
                       run_id="prior-ally-b-20260929")
        print("recorded metrics prior_ally_eval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
