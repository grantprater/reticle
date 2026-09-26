r"""Is Claude a usable labeller for minimap ally icons? A blind test.

    .\.venv\Scripts\python.exe prototypes\claude_icon_labels.py grids OUT_DIR
    .\.venv\Scripts\python.exe prototypes\claude_icon_labels.py score ANSWERS.json

Why. Coverage, not the descriptor, limits minimap ally identity
(`minimap-identity-clean-labels`): ten agents have no mined reference. A
labeller that can name any track, not only a death-bound one, would close
that. Before Claude labels anything, it is scored like any witness.

`grids` cuts the same 150 icons the player labelled
(`prototypes/label_death_icons.py`: one ringed icon from each sampled
death-bound segment's last 2 s, from the minimap cache, 4x) into grids of 30,
each tile numbered with the match's four teammates, and writes `items.json`
(item number, teammates). It writes nothing that reveals the player's answer,
the killfeed victim or the reader's guess, so a labeller given only OUT_DIR is
blind.

`score` compares an answers file -- {"<item>": "<agent>" | "not_portrait" |
"other_agent" | "unsure"} -- with the player's labels: agreement on the
player's certain answers, per class and per agent, and where they differ.
Predictions and outcome: `claude-icon-labels` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import label_death_icons as L  # noqa: E402

PER_GRID, COLS = 30, 6
TILE = 2 * L.HALF * L.ZOOM + L.ZOOM          # the labeller's crop size
TEXT_H = 34


def grids(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    items = L.sample(150)
    crops = L.Crops()
    tiles, meta = {}, []
    for n, u in sorted(enumerate(items), key=lambda p: p[1]["sid"]):
        big, _ = crops.get(u["sid"], u["show"])
        tiles[n] = (big, u["mates"])
    for n, u in enumerate(items):
        meta.append({"item": n + 1, "teammates": u["mates"]})
    for g in range(0, len(items), PER_GRID):
        cells = []
        for n in range(g, min(g + PER_GRID, len(items))):
            big, mates = tiles[n]
            cell = np.full((TILE + TEXT_H, TILE, 3), 24, np.uint8)
            cell[TEXT_H:TEXT_H + big.shape[0], :big.shape[1]] = big
            cv2.putText(cell, f"#{n + 1}", (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            cv2.putText(cell, " ".join(f"{i + 1}{a[:6]}" for i, a in enumerate(mates)), (3, 29),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.33, (200, 230, 255), 1)
            cells.append(cell)
        while len(cells) % COLS:
            cells.append(np.zeros_like(cells[0]))
        rows = [np.hstack(cells[i:i + COLS]) for i in range(0, len(cells), COLS)]
        cv2.imwrite(str(out / f"grid_{g // PER_GRID + 1}.png"), np.vstack(rows))
    (out / "items.json").write_text(json.dumps(meta, indent=0), encoding="utf-8")
    print(f"{len(items)} items in {(len(items) + PER_GRID - 1) // PER_GRID} grids -> {out}")


def score(answers_path: Path) -> dict:
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    items = L.sample(150)
    labs = L._labels()
    c, per, diffs = Counter(), {}, []
    for n, u in enumerate(items):
        lab = labs.get(u["key"])
        if lab is None or lab["uncertain"]:
            continue
        truth = lab["answer"] if lab["class"] == "agent" else lab["class"]
        got = answers.get(str(n + 1), "missing")
        if got == "unsure":
            c["claude unsure"] += 1
            continue
        ok = got == truth
        c["agree" if ok else "differ"] += 1
        p = per.setdefault(truth, Counter())
        p["agree" if ok else "differ"] += 1
        if not ok:
            diffs.append((n + 1, truth, got))
    decided = c["agree"] + c["differ"]
    out = {"player_certain": sum(c.values()), "counts": dict(c),
           "agreement": round(c["agree"] / max(1, decided), 3),
           "per_truth": {k: dict(v) for k, v in sorted(per.items())}, "differences": diffs}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    cmd, arg = sys.argv[1], Path(sys.argv[2])
    grids(arg) if cmd == "grids" else score(arg)
