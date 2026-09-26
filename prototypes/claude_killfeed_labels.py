r"""Is Claude a usable labeller for killfeed portraits? A blind test.

    .\.venv\Scripts\python.exe prototypes\claude_killfeed_labels.py grids OUT_DIR [--n N] [--set uniform|diff] [--keys KEYS.json]
    .\.venv\Scripts\python.exe prototypes\claude_killfeed_labels.py score ANSWERS.json [--set uniform|diff] [--keys KEYS.json]

Why. On minimap icons Claude agreed with the player on 0.972 of decided items
when shown the candidates' own art (`prototypes/claude_icon_labels.py`). The
killfeed has a larger open question: `prototypes/match_name_assignment.py`
differs from the resolved stored death verdicts on names the player's labels
do not cover (93 when measured; 178 roles, 102 killers and 76 victims, on
the store of 2026-09-26). Victim claims carry no view keys, so a victim is
framed at the killer claim's views with the role swapped: one entry, one row. This asks whether Claude can be scored as a witness there.

`--set uniform` shows the player's uniform killer sample
(`label_feed_portraits.py --uniform`) exactly as the player's tool framed it:
the killfeed row with the portrait boxed in green (cut to a 500 px window
round the box, since the whole 1100 px row is unreadable in a grid) and the
portrait enlarged. `--set diff` frames, with that tool's own `prep`, one middle
followed view of every entry role where the assignment names a different agent
than the resolved stored verdict, and writes each item's key, the stored name
and the assignment's name to `--keys`, a file that must lie outside OUT_DIR.

Under each tile are the killfeed portrait art of the entry side's candidates
(`identity.side_candidates` over the lineup: named slots and refused slots'
best guesses), numbered as the names line is. `items.json` holds only item
numbers and candidate names, so a labeller given only OUT_DIR is blind.

`score` reads {"<item>": "<agent>" | "not_portrait" | "other_agent" |
"unsure"}. Uniform: agreement with the player's certain answers on decided
items, the unsure share, per agent, and the differences. Diff: per item,
whether the answer agrees with the stored verdict, the assignment, or neither.
"""
from __future__ import annotations

import argparse
import functools
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import label_feed_portraits as lfp  # noqa: E402
import match_name_assignment as mna  # noqa: E402
from reticle.adjudication.identity import side_candidates  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
ART = STORE.root / "reference" / "assets" / "agents"
DIFF_PREP_NAME = "blind_killfeed_diff_crops.npz"
PER_GRID, COLS = 20, 4
WIN = 500                   # band window width
FACE_ZOOM = 3               # a 34-38 px portrait becomes ~110 px
TEXT_H, REF_W, REF_H = 40, 92, 46
BG = 24


@functools.lru_cache(maxsize=None)
def _lineup(sid: str) -> dict:
    """One `load_lineup` per session (it re-reads the scoreboard: ~10-30 s)."""
    return load_lineup(sid, STORE.root) or {}


def _cached_lineup(sid, _root=None):
    return _lineup(sid)


@functools.lru_cache(maxsize=None)
def _deaths(sid: str) -> dict:
    return {v["death_id"]: v for v in STORE.read_events("death", sid)
            if v.get("kind") == "death_verdict"}


def candidates(sid: str, death_id: str, role: str) -> list[str]:
    """The entry side's admissible agents: the side's named slots and refused
    slots' best guesses, sorted; the match's ten when the side is unknown."""
    v = _deaths(sid).get(death_id) or {}
    side = v.get("side") if role == "victim" else mna.OTHER.get(v.get("side"))
    lu = _lineup(sid)
    if side in (lu.get("sides") or {}):
        split = side_candidates(lu["sides"][side])
        return sorted(set(split["named"] + [a for a in split["rivals"] if a]))
    return sorted({r["agent"] for s in (lu.get("sides") or {}).values() for r in s if r.get("agent")})


def _ref_row(names: list[str], width: int) -> np.ndarray:
    """The candidates' killfeed portrait art on the tile background, numbered."""
    row = np.full((REF_H + 16, width, 3), BG, np.uint8)
    step = width // max(5, len(names))
    for i, a in enumerate(names):
        im = cv2.imread(str(ART / f"{a}_killfeed_portrait.png"), cv2.IMREAD_UNCHANGED)
        x = i * step + (step - REF_W) // 2
        cv2.putText(row, f"{i + 1}", (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        if im is None:
            continue
        if im.shape[2] == 4:
            alpha = im[:, :, 3:4].astype(np.float32) / 255
            im = (im[:, :, :3] * alpha + BG * (1 - alpha)).astype(np.uint8)
        row[16:16 + REF_H, x:x + REF_W] = cv2.resize(im, (REF_W, REF_H), interpolation=cv2.INTER_AREA)
    return row


def tile(n: int, band: np.ndarray, face: np.ndarray, ring: list[int], names: list[str]) -> np.ndarray:
    """The player's view: the row with the portrait boxed, and the portrait enlarged."""
    band = band.copy()
    x0, y0, x1, y1 = ring
    cv2.rectangle(band, (x0 - 2, y0 - 2), (x1 + 1, y1 + 1), (64, 255, 64), 2)
    # The row ends at a victim's portrait: keep the ring and the row before it.
    a = int(np.clip(min(max(0, x0 - 150), max(0, x1 + 30 - WIN)), 0, band.shape[1] - WIN))
    band = band[:, a:a + WIN]
    big = cv2.resize(face, None, fx=FACE_ZOOM, fy=FACE_ZOOM, interpolation=cv2.INTER_CUBIC)
    head = np.full((TEXT_H, WIN, 3), BG, np.uint8)
    cv2.putText(head, f"#{n}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(head, "  ".join(f"{i + 1} {x}" for i, x in enumerate(names)), (4, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 230, 255), 1)
    body = np.full((big.shape[0], WIN, 3), BG, np.uint8)
    body[:, :big.shape[1]] = big
    gap = np.full((6, WIN, 3), BG, np.uint8)
    return np.vstack([head, band, gap, body, _ref_row(names, WIN), gap])


def _write_grids(out: Path, tiles: list[np.ndarray], meta: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for g in range(0, len(tiles), PER_GRID):
        cells = tiles[g:g + PER_GRID]
        while len(cells) % COLS:
            cells.append(np.zeros_like(cells[0]))
        sep = np.full((cells[0].shape[0], 8, 3), 70, np.uint8)
        rows = [np.hstack([c for t in cells[i:i + COLS] for c in (t, sep)][:-1])
                for i in range(0, len(cells), COLS)]
        hsep = np.full((8, rows[0].shape[1], 3), 70, np.uint8)
        cv2.imwrite(str(out / f"grid_{g // PER_GRID + 1}.png"),
                    np.vstack([c for r in rows for c in (r, hsep)][:-1]))
    (out / "items.json").write_text(json.dumps(meta, indent=0), encoding="utf-8")
    print(f"{len(meta)} items in {(len(meta) + PER_GRID - 1) // PER_GRID} grids -> {out}")


def uniform_items(n: int | None) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    z = np.load(lfp.UNIFORM_PREP)
    meta = json.loads(str(z["meta"]))[:n]
    return z["bands"], z["faces"], meta


def _killer_views(v: dict) -> list[tuple[str, float]]:
    """The killer claim's followed view keys, in time order."""
    return sorted({(o["observation_key"], float(o["t_ms"]))
                   for c in ((v.get("metadata") or {}).get("killer_identity") or {}).get("claims", [])
                   if c["channel"] == "killfeed_portrait"
                   for o in (c.get("evidence") or {}).get("observations", []) if o.get("observation_key")},
                  key=lambda p: p[1])


def diff_roles() -> list[dict]:
    """Every entry role where the assignment names an agent and the resolved
    stored verdict names another, with the verdict's middle portrait view."""
    out = []
    for sid in mna.K.SIDS:
        got = mna.assign_names(sid)
        for did, v in _deaths(sid).items():
            for role, key in (("killer", "killer_identity"), ("victim", "identity")):
                ver = (v.get("metadata") or {}).get(key) or {}
                x = got.get((did, role))
                if ver.get("status") != "resolved" or not x or not x["agent"] or x["agent"] == ver.get("agent"):
                    continue
                obs = [o["observation_key"] for c in ver.get("claims", []) if c["channel"] == "killfeed_portrait"
                       for o in (c.get("evidence") or {}).get("observations", []) if o.get("observation_key")]
                if not obs and role == "victim":
                    # Victim claims carry no view keys; the victim shares the
                    # killer's entry (`sid:frame:slot:role`), so swap the role.
                    obs = [k.rsplit(":", 1)[0] + ":victim" for k, _t in _killer_views(v)]
                out.append({"session_id": sid, "entity_id": ver.get("entity_id") or f"{did}:{role}",
                            "death_id": did, "role": role, "stored": ver.get("agent"),
                            "assignment": x["agent"], "assignment_kind": x["kind"], "p": x["p"],
                            "observation_key": obs[len(obs) // 2] if obs else None})
        print(f"{sid}: {len(out)} differing roles so far", flush=True)
    return out


def diff_items(prep_path: Path) -> tuple[np.ndarray, np.ndarray, list[dict], list[dict]]:
    """Frame the differing roles with `label_feed_portraits.prep` (the player's
    crop code), passing it no name; return crops, blind meta and the keys."""
    roles = diff_roles()
    print(f"{len(roles)} differing roles; {sum(r['observation_key'] is None for r in roles)} have no portrait view")
    blind = [{k: r[k] for k in ("session_id", "entity_id", "death_id", "role", "observation_key")}
             for r in roles if r["observation_key"]]
    lfp.population = lambda: blind
    lfp.load_lineup = _cached_lineup
    lfp.prep(len(blind), prep_path, uniform=False)
    z = np.load(prep_path)
    meta = json.loads(str(z["meta"]))
    by = {r["entity_id"]: r for r in roles}
    return z["bands"], z["faces"], meta, [by[m["entity_id"]] for m in meta]


def grids(out: Path, n: int | None, which: str, keys_path: Path | None) -> None:
    mna.load_lineup = _cached_lineup
    if which == "uniform":
        bands, faces, meta = uniform_items(n)
        keys = None
    else:
        if keys_path is None or out.resolve() in keys_path.resolve().parents:
            raise SystemExit("--set diff needs --keys outside OUT_DIR")
        bands, faces, meta, keys = diff_items(keys_path.with_name(DIFF_PREP_NAME))
        order = list(range(len(meta)))
        random.Random(lfp.SEED).shuffle(order)
        order = order[:n]
        bands, faces = bands[order], faces[order]
        meta, keys = [meta[i] for i in order], [keys[i] for i in order]
    tiles, items = [], []
    for i, m in enumerate(meta):
        names = candidates(m["session_id"], m["death_id"], m["role"])
        tiles.append(tile(i + 1, bands[i], faces[i], m["ring"], names))
        items.append({"item": i + 1, "candidates": names})
    _write_grids(out, tiles, items)
    if keys is not None:
        side = {str(i + 1): {**k, "candidates": items[i]["candidates"]} for i, k in enumerate(keys)}
        keys_path.write_text(json.dumps(side, indent=1), encoding="utf-8")
        print(f"keys -> {keys_path}")


def score_uniform(answers: dict, n: int | None) -> dict:
    _b, _f, meta = uniform_items(n)
    labs = lfp._labels(lfp.UNIFORM_KIND)
    c, per, diffs = Counter(), defaultdict(Counter), []
    for i, m in enumerate(meta):
        lab = labs.get(m["entity_id"])
        if lab is None or lab["uncertain"]:
            continue
        truth = lab["answer"] if lab["class"] == "agent" else lab["class"]
        got = answers.get(str(i + 1), "missing")
        if got in ("unsure", "missing"):
            c[f"claude {got}"] += 1
            continue
        ok = got == truth
        c["agree" if ok else "differ"] += 1
        per[truth]["agree" if ok else "differ"] += 1
        if not ok:
            diffs.append((i + 1, truth, got))
    decided = c["agree"] + c["differ"]
    certain = sum(c.values())
    return {"player_certain": certain, "counts": dict(c),
            "agreement": round(c["agree"] / max(1, decided), 3),
            "unsure_share": round(c["claude unsure"] / max(1, certain), 3),
            "per_truth": {k: dict(v) for k, v in sorted(per.items())}, "differences": diffs}


def score_diff(answers: dict, keys_path: Path) -> dict:
    keys = json.loads(keys_path.read_text(encoding="utf-8"))
    per, tally = {}, Counter()
    for item, k in keys.items():
        got = answers.get(item, "missing")
        if got in ("unsure", "missing", "not_portrait", "other_agent"):
            side = got
        else:
            side = "stored" if got == k["stored"] else "assignment" if got == k["assignment"] else "neither"
        tally[side] += 1
        tally[f"{k['assignment_kind']}:{side}"] += 1
        per[item] = {"answer": got, "agrees_with": side, "stored": k["stored"],
                     "assignment": k["assignment"], "kind": k["assignment_kind"],
                     "session_id": k["session_id"], "death_id": k["death_id"], "role": k["role"]}
    return {"items": len(keys), "tally": dict(tally), "per_item": per}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["grids", "score"])
    ap.add_argument("path", type=Path)
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--set", dest="which", choices=["uniform", "diff"], default="uniform")
    ap.add_argument("--keys", type=Path, default=None, help="diff set: the sidecar of item keys")
    args = ap.parse_args()
    if args.cmd == "grids":
        grids(args.path, args.n, args.which, args.keys)
        return 0
    answers = json.loads(args.path.read_text(encoding="utf-8"))
    if args.which == "uniform":
        out = score_uniform(answers, args.n)
    else:
        if args.keys is None:
            raise SystemExit("--set diff needs --keys")
        out = score_diff(answers, args.keys)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
