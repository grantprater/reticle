"""Ask, in the `glance` grammar, which `other_red` minimap marks are Cypher cams.

    .\\.venv\\Scripts\\python.exe prototypes\\glance_cams.py a06f04a0059f [--n 12] [--controls 4]

Why this question
-----------------
`LOBE_MIN_FRAC` exists in `minimap_ring_fit` to stop a cam passing the motion
filter, and **the cam case is UNTESTED** -- nothing in the label set says which
`other_red` marks are cams. It is the smallest live perceptual question in the
repo, which makes it the right first load for the encoding rather than a fifth
attempt at something already stuck.

Where the controls come from, and what they do and do not prove
--------------------------------------------------------------
Grant's `labels/minimap/<session>.jsonl` holds 79 `enemy` and 31 `question`
marks alongside the 144 `other_red` ones, all placed by him, all placed BEFORE
this question was asked. They are planted here as controls.

Be honest about what that buys. Controls drawn from a different population
establish a **floor, not a ceiling**: hitting them says the reader can resolve
an enemy icon from a question mark at this magnification, which is the failure
mode worth ruling out first. It does NOT say the reader can separate a cam from
some other red furniture, because Grant never marked that distinction -- that is
precisely what is unknown. Compare `0 of 55 hand-marked icons have aspect >=
2.0`, a perfect measurement over the wrong population.

So the output of this script is **a proposal, not a label**. If the sheet comes
back VALID, its `cam` answers are worth putting to Grant in a labelling pass; if
it comes back VOID, the honest conclusion is that this question cannot be
answered by eye at 6x and the next move is a labeller, not a threshold.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import glance                                        # noqa: E402

STORE = Path.home() / "reticle-store"

# The closed set. `other` is the escape hatch: `cam` and `enemy` are CLAIMS, and
# forcing a red thing that is neither into one of them poisons the class -- the
# same reason `label_dynamic` carries `7 = other`.
CLASSES = ["cam", "enemy", "question-mark", "death-mark", "other"]

# Grant's mark kinds, mapped onto the answer vocabulary. Only these two are
# usable as controls; `other_red` is the open question by definition.
CONTROL_TRUTH = {"enemy": "enemy", "question": "question-mark"}


def load_marks(session: str):
    p = STORE / "labels" / "minimap" / f"{session}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    open_q, controls = [], []
    for r in rows:
        roi = r.get("roi")
        for m in r.get("marks", []):
            rec = {"t_ms": r["t_ms"], "x": m["x"], "y": m["y"], "roi": roi,
                   "kind": m["kind"]}
            if m["kind"] == "other_red":
                open_q.append(rec)
            elif m["kind"] in CONTROL_TRUTH:
                controls.append(rec)
    return open_q, controls


def build_items(session: str, picks, half: int):
    """Read one frame per pick and crop the minimap ROI. Seeks in time order."""
    man = json.loads((STORE / "manifests" / f"{session}.json").read_text(encoding="utf-8"))
    path = man["source"]["path"]
    fps = man["source"]["fps"]
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {path}")

    items, missed = [], 0
    for p in sorted(picks, key=lambda d: d["t_ms"]):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(p["t_ms"] / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            missed += 1
            continue
        rx, ry, rw, rh = p["roi"]
        crop = frame[ry:ry + rh, rx:rx + rw]
        x, y = int(p["x"]), int(p["y"])
        items.append(glance.Item(
            image=crop,
            box=(x - half, y - half, 2 * half, 2 * half),
            key=f"t={p['t_ms']} x={x} y={y}",
            truth=CONTROL_TRUTH.get(p["kind"]),
            note=f"{p['t_ms'] / 1000:.0f}s",
        ))
    cap.release()
    if missed:
        print(f"warning: {missed} frame(s) would not decode")
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=12, help="open other_red items")
    ap.add_argument("--controls", type=int, default=4)
    ap.add_argument("--zoom", type=int, default=6)
    ap.add_argument("--half", type=int, default=8, help="half-box in source px")
    ap.add_argument("--pad", type=int, default=16)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--dir", default=None)
    a = ap.parse_args(argv)

    open_q, controls = load_marks(a.session)
    print(f"{len(open_q)} other_red marks, {len(controls)} usable controls")
    rng = random.Random(a.seed if a.seed is not None else 0xCA3)
    picks = rng.sample(open_q, min(a.n, len(open_q)))
    # Draw controls across BOTH kinds, so a reader cannot pass by guessing one.
    by_kind: dict = {}
    for c in controls:
        by_kind.setdefault(c["kind"], []).append(c)
    per = max(1, a.controls // max(1, len(by_kind)))
    for kind, pool in by_kind.items():
        picks += rng.sample(pool, min(per, len(pool)))

    items = build_items(a.session, picks, a.half)
    sheet = glance.present(
        items,
        question=(f"{a.session} minimap, red marks. What is the ringed thing? "
                  "A Cypher cam is a small perfect circle."),
        classes=CLASSES, zoom=a.zoom, pad=a.pad, cols=a.cols,
        truth_source=f"grant, labels/minimap/{a.session}.jsonl (enemy + question marks)",
        domain="minimap", seed=a.seed)
    png = sheet.write(Path(a.dir) if a.dir else None)

    print(f"\n{png}")
    print(f"sheet {sheet.sheet_id}: {len(items)} items, "
          f"{sheet.manifest['n_controls']} controls, {a.zoom}x")
    print("PREDICT BEFORE YOU LOOK, then:")
    print(f"  python -m reticle.glance answer {sheet.sheet_id} "
          f"--confidence 0.7 --answers 01=cam,02=enemy,...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
