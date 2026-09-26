r"""What are the ally minimap pieces the arbiter cannot name? A blind sample.

    .\.venv\Scripts\python.exe prototypes\unnamed_piece_grids.py grids OUT_DIR [--sidecar PATH]
    .\.venv\Scripts\python.exe prototypes\unnamed_piece_grids.py score ANSWERS.json [--sidecar PATH]

Why. Stored ally round entities (`round-entity-0.8.0`) are pieces named per
round by `identity.assign_ally_pieces`. About 2900 of 7900 across the 19
sessions with a lineup carry no name, only an `identity_reason`; the
stitching prototype (`prototypes/ally_track_stitch.py`) found unnamed pieces
and fifth concurrent icons keep rounds above four tracks, and one fifth icon
it viewed was an ability device. An upstream fix to the ally icon detector
needs to know what these pieces show.

Sample. The unnamed pieces of each reason family -- `constraints leave no
teammate`, `no scored icon`, `alive_constraint`, `track margin`,
`not_a_teammate` -- `PER_REASON` each, round-robin over sessions in a fixed
hashed order, plus `CONTROLS` named pieces as a control. All are shuffled
together by a hash, so a control is indistinguishable in the grid.

What it shows. One icon per piece: the observation in the middle of the
piece, cut exactly as `label_death_icons.Crops.get` cuts it (the stored
`ally_icon` event's `cx`, `cy` ringed, from the lossless minimap cache; no
decode), with the match's four teammates' minimap portrait art under the
tile as `claude_icon_labels._ref_row` draws it. Grids of 24.

Blindness. OUT_DIR holds only the grids and `items.json` (item number,
teammates in alphabetical order). The sidecar -- session, capture path,
piece id, reason, named or not, the arbiter's name, size -- lives outside
OUT_DIR (default: `<OUT_DIR>_sidecar.json`).

`score` reads answers {"<item>": "<teammate>" | "not_portrait" |
"other_agent" | "unsure"} and tabulates them by reason family; for named
controls it counts whether a teammate answer matches the arbiter's name.
Nothing is written to the store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_icon_labels as C  # noqa: E402
import label_death_icons as L  # noqa: E402
import minimap_identity_calibration as mic  # noqa: E402

PER_REASON, CONTROLS, PER_GRID, COLS = 30, 20, 24, 6
FAMILIES = ("constraints leave no teammate", "no scored icon", "alive_constraint",
            "track margin", "not_a_teammate")
ANSWERS = ("not_portrait", "other_agent", "unsure")


def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def reason_family(reason: str | None) -> str:
    """The reason's stable prefix: the text before ':' or before its first number."""
    if not reason:
        return "none"
    if ":" in reason:
        return reason.split(":", 1)[0]
    return re.sub(r"\s*[\d.]+.*$", "", reason)


def _pieces(sid: str) -> list[dict]:
    """Ally pieces of a session with their size and middle observation."""
    ents, obs = {}, defaultdict(list)
    for e in L.STORE.read_events("round_entity", sid):
        if e.get("family") != "ally":
            continue
        if e.get("kind") == "entity":
            ents[e["id"]] = e
        elif e.get("kind") == "observation":
            obs[e["entity_id"]].append((float(e["t_ms"]), e["observation_key"]))
    out = []
    for pid, e in ents.items():
        o = sorted(obs.get(pid, []))
        if not o:
            continue
        out.append({"sid": sid, "piece": pid, "round": e["round_no"], "agent": e.get("agent"),
                    "reason": e.get("identity_reason"),
                    "family": "NAMED" if e.get("agent") else reason_family(e.get("identity_reason")),
                    "observations": len(o), "duration_ms": round(o[-1][0] - o[0][0], 1),
                    "keys": [k for _, k in o], "version": e.get("round_entity_version")})
    return out


def pick_pieces() -> list[dict]:
    """PER_REASON pieces per family and CONTROLS named ones, round-robin over sessions."""
    sids = sorted(p.stem for p in mic.WORK.glob("*.pkl"))
    data = mic.load_sessions(sids, mic.WORK)
    pools = defaultdict(lambda: defaultdict(list))
    for sid in sids:
        for p in _pieces(sid):
            p["mates"] = sorted(data[sid]["candidates"])
            pools[p["family"]][sid].append(p)
    chosen = []
    for fam, want in [(f, PER_REASON) for f in FAMILIES] + [("NAMED", CONTROLS)]:
        by_sid = pools.get(fam, {})
        for v in by_sid.values():
            v.sort(key=lambda p: _h(p["piece"]))
        order = sorted(by_sid, key=lambda s: _h(fam + s))
        got, i = [], 0
        while len(got) < want and any(i < len(by_sid[s]) for s in order):
            for s in order:
                if i < len(by_sid[s]) and len(got) < want:
                    got.append(by_sid[s][i])
            i += 1
        chosen += got
    chosen.sort(key=lambda p: _h("blind:" + p["piece"]))
    return chosen


def _middle_icon_crop(crops: L.Crops, p: dict):
    """The middle observation's crop; the nearest cached icon if the middle is missing."""
    keys, mid = p["keys"], len(p["keys"]) // 2
    for j in sorted(range(len(keys)), key=lambda j: abs(j - mid))[:20]:
        k = keys[j]
        try:
            big, ic = crops.get(p["sid"], k)
            return big, k, float(ic["t_ms"])
        except (KeyError, StopIteration):
            continue
    return None, None, None


def build_grids(out: Path, sidecar: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    items = pick_pieces()
    crops, tiles, side, missing = L.Crops(), {}, [], Counter()
    for n, p in sorted(enumerate(items), key=lambda q: q[1]["sid"]):
        big, key, t = _middle_icon_crop(crops, p)
        if big is None:
            missing[p["family"]] += 1
        tiles[n] = (big, key, t)
    kept = [n for n in range(len(items)) if tiles[n][0] is not None]
    meta = []
    for i, n in enumerate(kept, 1):
        p, (_, key, t) = items[n], tiles[n]
        meta.append({"item": i, "teammates": p["mates"]})
        man = L.STORE.read_manifest(p["sid"])
        side.append({"item": i, "session": p["sid"], "capture": man["source"]["path"],
                     "piece": p["piece"], "round": p["round"], "family": p["family"],
                     "identity_reason": p["reason"], "named": p["agent"] is not None,
                     "agent": p["agent"], "observations": p["observations"],
                     "duration_ms": p["duration_ms"], "shown_key": key, "shown_t_ms": t,
                     "version": p["version"]})
    for g in range(0, len(kept), PER_GRID):
        cells = []
        for i in range(g, min(g + PER_GRID, len(kept))):
            big = tiles[kept[i]][0]
            mates = items[kept[i]]["mates"]
            cell = np.full((C.TILE + C.TEXT_H, C.TILE, 3), 24, np.uint8)
            cell[C.TEXT_H:C.TEXT_H + big.shape[0], :big.shape[1]] = big
            cv2.putText(cell, f"#{i + 1}", (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            cv2.putText(cell, " ".join(f"{j + 1}{a[:6]}" for j, a in enumerate(mates)), (3, 29),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.33, (200, 230, 255), 1)
            cells.append(np.vstack([cell, C._ref_row(mates, cell.shape[1])]))
        while len(cells) % COLS:
            cells.append(np.zeros_like(cells[0]))
        rows = [np.hstack(cells[j:j + COLS]) for j in range(0, len(cells), COLS)]
        cv2.imwrite(str(out / f"grid_{g // PER_GRID + 1}.png"), np.vstack(rows))
    (out / "items.json").write_text(json.dumps(meta, indent=0), encoding="utf-8")
    sidecar.write_text(json.dumps(side, indent=1), encoding="utf-8")
    fams = Counter(s["family"] for s in side)
    print(json.dumps({"items": len(side), "grids": (len(side) + PER_GRID - 1) // PER_GRID,
                      "by_family": dict(fams), "no_crop": dict(missing),
                      "out": str(out), "sidecar": str(sidecar)}, indent=1))


def tabulate(answers_path: Path, sidecar: Path) -> dict:
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    side = json.loads(sidecar.read_text(encoding="utf-8"))
    by, control = defaultdict(Counter), Counter()
    for s in side:
        a = answers.get(str(s["item"]), "missing")
        cls = a if a in ANSWERS or a == "missing" else "teammate"
        by[s["family"]][cls] += 1
        if s["named"] and cls == "teammate":
            control["match" if a == s["agent"] else "differ"] += 1
        elif s["named"]:
            control[cls] += 1
    out = {"by_family": {f: dict(c) for f, c in sorted(by.items())},
           "named_control": dict(control)}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["grids", "score"])
    ap.add_argument("path", type=Path)
    ap.add_argument("--sidecar", type=Path)
    a = ap.parse_args()
    if a.cmd == "grids":
        build_grids(a.path, a.sidecar or a.path.with_name(a.path.name + "_sidecar.json"))
    else:
        tabulate(a.path, a.sidecar or Path(str(a.path.parent)) / "blind_unnamed_sidecar.json")
