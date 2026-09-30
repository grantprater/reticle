r"""Ask the player what each drawn line segment of the baked Ascent static is.

    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py map
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py score
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py preview
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py sorter [--v2] [--record]
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py queue
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py notes --spec <store json>
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py occluders [--record]
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py predict --key lotus__valorant-16x9-bigmap
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py sample --key lotus__valorant-16x9-bigmap
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label --key lotus__valorant-16x9-bigmap
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py heldout --key lotus__valorant-16x9-bigmap [--record]

The Lotus held-out test (raised-edges-0.3.0). `predict` writes the frozen sorter's class counts
on a key with no answers; the prediction row is task `line-sorter-0.3-lotus-20260930` in the
store's `notes/predictions.jsonl`. `sample` draws 40 of that key's 0.3.0 segments (connectors
excluded), stratified across the predicted classes and three length bins with a fixed seed, and
writes `<store>/labels/raised_edge_segment/<key>.sample.json` before any answer exists. `label`
on a key with a sample asks exactly those segments in the sample's order, numbered n/40, with the
same view and keys as the Ascent pass. `heldout` scores the answers against the frozen prediction
once they exist, and refuses if the prediction does not precede the first answer. Segments on the
Lotus C Mound are reported apart [domain:minimap/floor-shade-is-elevation].

`sorter` scores 0.3.0's four classes (wall, box, ramp_or_elevation_line, other); `--v2` scores
0.2.0's two, after checking that 0.2.0 still derives each answered segment's shown class. The
Ascent answers name 0.2.0 segments, so 0.3.0 sorts those segments on its own per-pixel reading.

Why. `raised_edges.py` splits the static's lines by what lies directly beyond
them: void on one side (a wall) or plain floor on both (a raised edge, which
marks a ramp or elevation change that does not affect vision
[domain:minimap/raised-edge-lines]). The rule is the player's rule of thumb,
checked at four named places only. This asks the player about every segment,
so the rule can be scored.

Sample. Every wall and raised-edge segment `raised_edges.segments` finds on the
key (default the 465 px `ascent__valorant-16x9-bigmap`), shuffled by a hash of
its signature. Nothing is seeded.

The first pass (raised-edges-0.1.0) asked about 8-connected pieces, which
followed the line network round whole rooms; the player answered unsure on
such outlines. Its answers stay in `<store>/labels/raised_edge/<key>.jsonl`,
which this tool only reads. `map` carries an old answer to a segment only
where every pixel of the segment lies inside one old piece the player called
wall or ramp; an unsure old piece means "not a line piece", never an answer.
Every mapping is listed in `<store>/analysis/raised-edges-20260930/
mapped_<key>.json`; mapped segments are not asked again, and the scores keep
them apart from direct answers.

What it shows. Left: the baked static round the segment, native pixels at an
integer zoom (about 540 px across), the segment ringed by one yellow box, the
same for every class, with magenta ticks at its two ends. Right: the whole map
at 1.5x with the same box, for place. The derived class, the shade rungs and
the shade-heaven candidates are never shown.

Classes: 1 wall (blocks vision), 2 ramp or elevation line (vision crosses),
3 box outline, 4 heaven edge (a platform's edge), 5 other drawn mark,
0 other, U unsure (kept out of scoring). A back, Q or Esc save and quit.

Answers go to `<store>/labels/raised_edge_segment/<key>.jsonl`, one row per
answer, the last row for a segment winning; the tool resumes where it stopped.
Predictions and outcome: `drawn-areas-edges-20260930` in the store's
`notes/predictions.jsonl`.

After the pass. `sorter` scores the derived class against the direct answers,
one row per segment (the last answer wins), with precision and recall.
`queue` rebuilds the labeller's first-session order, so a number the player
quotes ("n/221") names a segment; it stops if the label file's answer order
disagrees. `notes` resolves such numbered notes, paraphrased in a store spec,
to `<key>.notes.jsonl` beside the labels. `occluders` counts the baked
occluder pixels on the segments the player called non-occluding; it changes
no geometry. Series `raised-edge-sorter` and `raised-edge-occluders`.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raised_edges as RE  # noqa: E402

KIND_V1 = "raised_edge"                 # the 0.1.0 piece answers: read only
KIND = "raised_edge_segment"
CLASSES = {1: "wall", 2: "ramp_or_elevation_line", 3: "box_outline", 4: "heaven_edge",
           5: "other_mark", 0: "other"}
#: Old answers that carry to a segment wholly inside the old piece.
MAPPABLE = ("wall", "ramp_or_elevation_line")
#: The left tile is about TILE_PX wide: a window of at least WINDOW_MIN px (scale 1.0) round the
#: segment, MARGIN px clear of it, at an integer zoom of at least 3 (native pixels, nearest).
TILE_PX, WINDOW_MIN, MARGIN, CTX_ZOOM = 540, 60, 14, 1.5
#: The ring's colour says nothing about the class: every segment gets the same ring.
RING = (0, 230, 255)
TICK = (255, 0, 255)


def _label_path(key: str, kind: str = KIND) -> Path:
    d = RE.STORE / "labels" / kind
    if kind == KIND:
        d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.jsonl"


def _labels(key: str, kind: str = KIND) -> dict:
    p = _label_path(key, kind)
    out = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["piece"]] = r
    return out


def piece_signature(key: str, p: dict) -> str:
    """A 0.1.0 piece's name: its key and bounding box (the baked static does not move)."""
    return f"{key}:{p['x']},{p['y']},{p['w']},{p['h']}"


def signature(key: str, s: dict) -> str:
    """A segment's name: its key and its two skeleton ends."""
    (ax, ay), (bx, by) = s["end_a"], s["end_b"]
    return f"{key}:seg:{ax},{ay}-{bx},{by}"


def _mapped_path(key: str) -> Path:
    return RE.OUT / f"mapped_{key}.json"


def _mapped(key: str) -> dict:
    p = _mapped_path(key)
    if not p.is_file():
        return {}
    return {m["segment"]: m for m in json.loads(p.read_text(encoding="utf-8"))["mappings"]}


#: The segmentation each key's answers were given on. Ascent's 465 px answers name 0.2.0
#: segments, so its labeller, queue and notes keep 0.2.0; every other key uses the current sorter.
VERSION_FOR_KEY = {"ascent__valorant-16x9-bigmap": RE.VERSION_V2}


def seg_version(key: str) -> str:
    return VERSION_FOR_KEY.get(key, RE.VERSION)


def _classified(key: str, version: str | None = None) -> dict:
    version = version or seg_version(key)
    r = RE.classify(key, version)
    heavens = RE.shade_heavens(r)
    RE.annotate_pieces(r, heavens)
    RE.segments(r)
    if version != RE.VERSION_V2:
        RE.sort_all(r)
    RE.annotate_pieces(r, heavens, "segments", "_sid")
    return r


def _items(key: str, version: str | None = None) -> tuple[dict, list[dict]]:
    """The segments offered to the player, hash-sorted: 0.2.0's wall and raised-edge segments, or
    0.3.0's sorted segments and fragments (connectors take their neighbours' class and are not
    asked about)."""
    version = version or seg_version(key)
    r = _classified(key, version)
    if version == RE.VERSION_V2:
        items = [dict(s, piece=signature(key, s)) for s in r["segments"] if s["cls"] in ("wall", "raised_edge")]
    else:
        items = [dict(s, piece=signature(key, s)) for s in r["segments"]
                 if not s.get("connector") and s.get("cls3") in RE.SORT_CLASSES]
    items.sort(key=lambda p: hashlib.sha1(p["piece"].encode()).hexdigest())
    return r, items


def cmd_map(key: str) -> dict:
    """Carry the 0.1.0 answers to the segments wholly inside the pieces they were given on."""
    r, items = _items(key)
    old = _labels(key, KIND_V1)
    by_id = {p["id"]: piece_signature(key, p) for p in r["pieces"]}
    missing = sorted(set(old) - set(by_id.values()))
    if missing:
        raise SystemExit(f"{len(missing)} answered pieces are not reproduced by classify: {missing[:3]}")
    mappings, not_mapped = [], Counter()
    for s in items:
        ids = np.unique(r["_pid"][r["_sid"] == s["id"]])
        inside = len(ids) == 1 and ids[0] != 0
        sig = by_id.get(int(ids[0])) if inside else None
        ans = old.get(sig) if sig else None
        if not inside:
            not_mapped["spans_pieces_or_none"] += 1
        elif ans is None:
            not_mapped["piece_unanswered"] += 1
        elif ans["class"] == "unsure":
            not_mapped["piece_unsure_not_a_line_piece"] += 1
        elif ans["class"] not in MAPPABLE:
            not_mapped[f"piece_{ans['class']}"] += 1
        else:
            mappings.append({"segment": s["piece"], "segment_id": s["id"], "from_piece": sig,
                             "class": ans["class"], "answered_at": ans["at"], "by": "mapped",
                             "segment_px": s["px"], "segment_derived_class": s["cls"]})
    out = {"version": RE.VERSION, "key": key, "segments": len(items), "mapped": len(mappings),
           "not_mapped": dict(not_mapped), "old_answers": dict(Counter(v["class"] for v in old.values())),
           "rule": "a segment takes an old answer only when every pixel of it lies in one old piece "
                   "answered wall or ramp_or_elevation_line; unsure means not a line piece",
           "mappings": mappings}
    RE.OUT.mkdir(parents=True, exist_ok=True)
    _mapped_path(key).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "mappings"}, indent=1))
    for m in mappings:
        print(f"  {m['segment']}  <-  {m['from_piece']}  {m['class']}")
    return out


def _tile(r: dict, p: dict) -> np.ndarray:
    st = r["_static"]
    h, w = st.shape[:2]
    m = int(round(MARGIN * r["scale"]))
    side = max(p["w"], p["h"]) + 2 * m
    side = max(side, int(round(WINDOW_MIN * r["scale"])))
    cx, cy = p["x"] + p["w"] // 2, p["y"] + p["h"] // 2
    x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
    x1, y1 = min(w, x0 + side), min(h, y0 + side)
    z = max(3, TILE_PX // side)
    big = cv2.resize(st[y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    bx0, by0 = (p["x"] - x0) * z - 5, (p["y"] - y0) * z - 5
    bx1, by1 = (p["x"] + p["w"] - x0) * z + 4, (p["y"] + p["h"] - y0) * z + 4
    cv2.rectangle(big, (bx0, by0), (bx1, by1), RING, 2)
    for ex, ey in (p["end_a"], p["end_b"]):     # ticks just outside the box at each end
        tx, ty = int((ex - x0 + 0.5) * z), int((ey - y0 + 0.5) * z)
        tx = min(max(tx, bx0 - 12), bx1 + 12)
        ty = min(max(ty, by0 - 12), by1 + 12)
        if p["w"] >= p["h"]:
            cv2.line(big, (tx, by0 - 14), (tx, by0 - 6), TICK, 2)
        else:
            cv2.line(big, (bx0 - 14, ty), (bx0 - 6, ty), TICK, 2)
    ctx = cv2.resize(st, None, fx=CTX_ZOOM, fy=CTX_ZOOM, interpolation=cv2.INTER_AREA)
    cv2.rectangle(ctx, (int(x0 * CTX_ZOOM), int(y0 * CTX_ZOOM)), (int(x1 * CTX_ZOOM), int(y1 * CTX_ZOOM)), RING, 2)
    H = max(big.shape[0], ctx.shape[0])
    pad = lambda a: np.vstack([a, np.zeros((H - a.shape[0], a.shape[1], 3), np.uint8)])  # noqa: E731
    return np.hstack([pad(big), np.zeros((H, 8, 3), np.uint8), pad(ctx)])


def label(key: str, close_after: int = 0) -> int:
    import tkinter as tk

    version = seg_version(key)
    r, items = _items(key)
    done = _labels(key)
    sample = _sample(key)
    if sample is not None:
        # a held-out sample: ask its segments in its fixed order, numbered k/len(sample)
        by = {p["piece"]: p for p in items}
        missing = [x["piece"] for x in sample["items"] if x["piece"] not in by]
        if missing:
            raise SystemExit(f"{len(missing)} sampled segments are not reproduced by {version}: {missing[:3]}")
        full = [by[x["piece"]] for x in sample["items"]]
        mapped = {}
    else:
        mapped = _mapped(key)
        if not _mapped_path(key).is_file():
            raise SystemExit("run `map` first, so segments the player already answered are not asked again")
        full = [p for p in items if p["piece"] not in mapped]
    order = [p for p in full if p["piece"] not in done]
    number = {p["piece"]: i for i, p in enumerate(full, 1)}
    print(f"{len(items)} segments on {key}: {len(mapped)} carry an old answer, "
          f"{len([p for p in full if p['piece'] in done])} answered here, {len(order)} to ask", flush=True)
    if not order:
        return 0
    root = tk.Tk()
    root.title("What is the line in the yellow box?")
    panel = tk.Label(root)
    panel.pack()
    info = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    info.pack(fill="x")
    state = {"k": 0, "img": None}

    def show():
        if state["k"] >= len(order):
            root.destroy()
            return
        p = order[state["k"]]
        img = tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", _tile(r, p))[1].tobytes()))
        state["img"] = img                       # keep a reference, or Tk blanks it
        panel.configure(image=img)
        n_shown = number[p["piece"]] if sample is not None else state["k"] + 1
        n_all = len(full) if sample is not None else len(order)
        info.configure(text=(
            f"{n_shown}/{n_all}   {key}   the line inside the yellow box, between the magenta ticks\n"
            "1 wall (blocks vision)   2 ramp or elevation line (vision crosses)   3 box outline\n"
            "4 heaven edge   5 other drawn mark   0 other   U unsure   A back   Q quit"))

    def write(cls):
        p = order[state["k"]]
        row = {"key": p["piece"], "piece": p["piece"], "geometry_key": key, "class": cls,
               "uncertain": cls == "unsure", "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
               "end_a": p["end_a"], "end_b": p["end_b"], "px": p["px"], "shape": p["shape"],
               "derived_class": p["cls"] if version == RE.VERSION_V2 else p["cls3"],
               "heavens": p["heavens"], "ramp_near_share": p["ramp_near_share"],
               "compared_against_derived": False, "version": version, "by": "player",
               "sample": sample["id"] if sample is not None else None,
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(_label_path(key), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        state["k"] += 1
        show()

    for i, cls in CLASSES.items():
        root.bind(str(i), lambda e, cls=cls: write(cls))
    root.bind("u", lambda e: write("unsure"))
    root.bind("a", lambda e: (state.update(k=max(0, state["k"] - 1)), show()))
    root.bind("q", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())
    show()
    if close_after:
        # a check that the window opens and draws one segment: no key is bound, nothing is written
        for i in list(CLASSES) + ["u", "a"]:
            root.unbind(str(i))
        root.after(close_after, root.destroy)
    root.mainloop()
    return 0


def _conf(rows) -> dict:
    conf = defaultdict(Counter)
    for derived, cls in rows:
        conf[derived][cls] += 1
    return {k: dict(c) for k, c in conf.items()}


def _agreement(rows) -> dict:
    """Wall against ramp: the derived wall / raised-edge split on the answers that are one of the two."""
    pairs = [(d, c) for d, c in rows if c in MAPPABLE and d in ("wall", "raised_edge")]
    ok = sum((d == "wall") == (c == "wall") for d, c in pairs)
    return {"n": len(pairs), "agree": ok, "share": round(ok / len(pairs), 3) if pairs else None}


def score(key: str) -> dict:
    """The player's classes against the derived class: the 0.1.0 pieces, the segments answered
    directly, and the segments carrying a mapped answer, each apart."""
    old = list(_labels(key, KIND_V1).values())
    old_rows = [(v["derived_class"], v["class"]) for v in old if v["class"] != "unsure"]
    out = {"key": key,
           "pieces_0_1_0": {"answers": len(old), "unsure": sum(v["class"] == "unsure" for v in old),
                            "derived_vs_player": _conf(old_rows), "wall_vs_ramp": _agreement(old_rows)}}
    seg = [v for v in _labels(key).values()]
    seg_rows = [(v["derived_class"], v["class"]) for v in seg if v["class"] != "unsure"]
    out["segments_direct"] = {"answers": len(seg), "unsure": sum(v["class"] == "unsure" for v in seg),
                              "derived_vs_player": _conf(seg_rows), "wall_vs_ramp": _agreement(seg_rows)}
    mp = list(_mapped(key).values())
    mp_rows = [(m["segment_derived_class"], m["class"]) for m in mp]
    out["segments_mapped"] = {"answers": len(mp), "derived_vs_player": _conf(mp_rows),
                              "wall_vs_ramp": _agreement(mp_rows)}
    print(json.dumps(out, indent=1))
    return out


def _lower_priority() -> None:
    """Below Normal, checked: the handle types are declared (see `audio_bank._lower_priority`)."""
    if sys.platform != "win32":
        return
    import ctypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    if not k.SetPriorityClass(k.GetCurrentProcess(), 0x4000) or k.GetPriorityClass(k.GetCurrentProcess()) != 0x4000:
        raise SystemExit("could not lower this process to Below Normal priority")


#: The sorter's two classes against the player's: `raised_edge` means "a ramp or elevation line"
#: [domain:minimap/raised-edge-lines], so it is scored against that class, and again against every
#: class that is not a wall. The player's other classes have no derived counterpart.
DERIVED_FOR = {"wall": "wall", "raised_edge": "ramp_or_elevation_line"}


def _pr(pairs, pred, truth) -> dict:
    tp = sum(d == pred and truth(c) for d, c in pairs)
    np_ = sum(d == pred for d, _ in pairs)
    nt = sum(truth(c) for _, c in pairs)
    return {"tp": tp, "predicted": np_, "true": nt,
            "precision": round(tp / np_, 4) if np_ else None, "recall": round(tp / nt, 4) if nt else None}


def sorter_v2(key: str, record: bool = False) -> dict:
    """Confusion of the 0.2.0 sorter's derived class against the player's direct segment answers.

    Reads the label file (each row carries the derived class it was shown with), and checks that
    `raised_edges.classify(..., VERSION_V2)` still derives the same class for every answered
    segment. One row per segment: the last answer wins, as the labeller documents, so a segment
    the player went back to counts once. Unsure answers stay out."""
    p = _label_path(key)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    last = _labels(key)
    versions = sorted({v["version"] for v in last.values()})
    if versions == [RE.VERSION_V2]:
        _, items = _items(key, RE.VERSION_V2)
        now = {q["piece"]: q["cls"] for q in items}
        diff = [k for k, v in last.items() if now.get(k) != v["derived_class"]]
        print(f"0.2.0 recomputed: {len(last) - len(diff)}/{len(last)} answered segments derive the class they were shown with")
        if diff:
            raise SystemExit(f"0.2.0 does not reproduce: {diff[:3]}")
    pairs = [(v["derived_class"], v["class"]) for v in last.values() if v["class"] != "unsure"]
    player = sorted({c for _, c in pairs}, key=lambda c: (-sum(x == c for _, x in pairs), c))
    derived = sorted({d for d, _ in pairs})
    table = {c: {d: sum(1 for x, y in pairs if x == d and y == c) for d in derived} for c in player}
    per = {"wall": _pr(pairs, "wall", lambda c: c == "wall"),
           "raised_edge_as_ramp": _pr(pairs, "raised_edge", lambda c: c == "ramp_or_elevation_line"),
           "raised_edge_as_not_wall": _pr(pairs, "raised_edge", lambda c: c != "wall")}
    agree = sum((d == "wall") == (c == "wall") for d, c in pairs)
    out = {"key": key, "versions": versions, "rows": len(rows), "segments": len(last),
           "redone_rows": len(rows) - len(last), "unsure": sum(v["class"] == "unsure" for v in last.values()),
           "scored": len(pairs), "player_classes": dict(Counter(c for _, c in pairs)),
           "derived_classes": dict(Counter(d for d, _ in pairs)), "confusion_player_by_derived": table,
           "per_class": per, "wall_vs_not_wall_agree": agree,
           "wall_vs_not_wall_share": round(agree / len(pairs), 4) if pairs else None}
    w = max(len(c) for c in player) + 2
    print(f"{key}: {out['rows']} rows, {out['segments']} segments (last answer wins), {out['scored']} scored")
    print("player \\ derived".ljust(w) + "".join(d.rjust(13) for d in derived) + "total".rjust(8))
    for c in player:
        print(c.ljust(w) + "".join(str(table[c][d]).rjust(13) for d in derived) + str(sum(table[c].values())).rjust(8))
    for name, v in per.items():
        print(f"  {name:26s} precision {v['precision']} ({v['tp']}/{v['predicted']})"
              f"  recall {v['recall']} ({v['tp']}/{v['true']})")
    print(f"  wall vs not wall agree {agree}/{len(pairs)} = {out['wall_vs_not_wall_share']}")
    if record:
        vals = {"rows": out["rows"], "segments": out["segments"], "redone_rows": out["redone_rows"],
                "scored": out["scored"], "wall_vs_not_wall_share": out["wall_vs_not_wall_share"]}
        for c in player:
            for d in derived:
                vals[f"n_{c}_as_{d}"] = table[c][d]
        for name, v in per.items():
            vals[f"{name}_precision"], vals[f"{name}_recall"] = v["precision"], v["recall"]
        RE.metrics.record("raised-edge-sorter", part="segments", session=key, values=vals,
                          deps={"sorter_version": versions, "labels": str(p.relative_to(RE.STORE)),
                                "label_rows": len(rows)},
                          context={"derived_for": DERIVED_FOR, "rule": "last answer per segment wins; unsure out"},
                          note="player's direct segment answers only; the 13 carried 0.1.0 answers are scored by `score`")
        print("recorded")
    return out


# --- the 0.3.0 sorter, scored; the Lotus held-out sample and its frozen prediction -----------------

def _mound(key: str) -> np.ndarray:
    """The Lotus C Mound's pixels, grown 2 px, from `lotus_elevation.mound_mask` (its owner); empty
    on any other key. Its segments are reported apart: the mound's elevation is close to unique
    [domain:minimap/floor-shade-is-elevation]."""
    if not key.startswith("lotus__"):
        return np.zeros(RE.load(key)["static"].shape[:2], bool)
    import types
    import lotus_elevation as LE
    g = RE.load(key)
    return LE.mound_mask(types.SimpleNamespace(floor=g["shade_step"] >= 0, shade_step=g["shade_step"]))


def _sorted_answers(key: str) -> tuple[list[dict], list[dict], str]:
    """The player's last answer per segment, each with the 0.3.0 class of that segment. The
    segment is rebuilt with the segmentation its answer was given on (the rows' `version`): 0.2.0
    segments are sorted by the 0.3.0 rule on 0.3.0's per-pixel reading; 0.3.0 segments carry their
    class. Returns (answers, rows, segmentation version)."""
    p = _label_path(key)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    last = _labels(key)
    versions = sorted({v["version"] for v in last.values()})
    if len(versions) != 1:
        raise SystemExit(f"answers on more than one segmentation: {versions}")
    ver = versions[0]
    mound = _mound(key)
    if ver == RE.VERSION_V2:
        r_seg = _classified(key, RE.VERSION_V2)
        r3 = RE.classify(key, RE.VERSION)
        closed = RE.closed_boxes(r3)
        by = {}
        for s in r_seg["segments"]:
            m = r_seg["_sid"] == s["id"]
            by[signature(key, s)] = dict(s, **RE.sort_segment(r3, m, s["skeleton_px"], s["shape"], closed),
                                         mound=bool((m & mound).any()))
    else:
        r3 = _classified(key, ver)
        by = {signature(key, s): dict(s, mound=bool(((r3["_sid"] == s["id"]) & mound).any()))
              for s in r3["segments"]}
    out = []
    for k, v in last.items():
        if k not in by:
            raise SystemExit(f"answered segment {k} is not reproduced by {ver}")
        out.append(dict(v, cls3=by[k]["cls3"], mound=by[k]["mound"], length=by[k].get("length")))
    return out, rows, ver


def _table(ans: list[dict]) -> dict:
    """The four-class confusion (player class mapped by PLAYER_TO_SORT), per-class precision and
    recall, and agreement, over answers that are not unsure."""
    pairs = [(a["cls3"], RE.PLAYER_TO_SORT[a["class"]]) for a in ans if a["class"] != "unsure"]
    cl = RE.SORT_CLASSES
    table = {c: {d: sum(1 for x, y in pairs if x == d and y == c) for d in cl} for c in cl}
    per = {c: _pr(pairs, c, lambda t, c=c: t == c) for c in cl}
    agree = sum(d == c for d, c in pairs)
    wall = sum((d == "wall") == (c == "wall") for d, c in pairs)
    return {"scored": len(pairs), "agree": agree, "agree_share": round(agree / len(pairs), 4) if pairs else None,
            "wall_vs_not_wall_agree": wall,
            "wall_vs_not_wall_share": round(wall / len(pairs), 4) if pairs else None,
            "confusion_player_by_sorter": table, "per_class": per}


def _print_table(name: str, t: dict) -> None:
    cl = RE.SORT_CLASSES
    print(f"{name}: {t['scored']} scored, agree {t['agree']}/{t['scored']} = {t['agree_share']}, "
          f"wall vs not wall {t['wall_vs_not_wall_agree']}/{t['scored']}")
    print("  player \\ 0.3.0".ljust(26) + "".join(c[:6].rjust(8) for c in cl) + "total".rjust(8))
    for c in cl:
        row = t["confusion_player_by_sorter"][c]
        print(f"  {c:24s}" + "".join(str(row[d]).rjust(8) for d in cl) + str(sum(row.values())).rjust(8))
    for c, v in t["per_class"].items():
        print(f"    {c:24s} precision {v['precision']} ({v['tp']}/{v['predicted']})  recall {v['recall']} ({v['tp']}/{v['true']})")


def sorter(key: str, record: bool = False, v2: bool = False) -> dict:
    """Score the sorter against the player's segment answers: 0.2.0 with `v2` (the old two-class
    table), else 0.3.0's four classes. C Mound segments are scored apart as well as in the whole."""
    if v2:
        return sorter_v2(key, record)
    ans, rows, ver = _sorted_answers(key)
    whole = _table(ans)
    out = {"key": key, "sorter": RE.VERSION, "segmentation": ver, "rows": len(rows), "segments": len(ans),
           "unsure": sum(a["class"] == "unsure" for a in ans), "whole": whole}
    print(f"{key}: {len(rows)} rows, {len(ans)} segments (last answer wins), segments from {ver}, sorter {RE.VERSION}")
    _print_table("whole", whole)
    if any(a["mound"] for a in ans):
        out["c_mound"] = _table([a for a in ans if a["mound"]])
        out["without_c_mound"] = _table([a for a in ans if not a["mound"]])
        _print_table("C Mound", out["c_mound"])
        _print_table("without C Mound", out["without_c_mound"])
    if record:
        vals = {"rows": len(rows), "segments": len(ans), "scored": whole["scored"], "agree": whole["agree"],
                "agree_share": whole["agree_share"], "wall_vs_not_wall_agree": whole["wall_vs_not_wall_agree"],
                "wall_vs_not_wall_share": whole["wall_vs_not_wall_share"]}
        for c, row in whole["confusion_player_by_sorter"].items():
            for d, n in row.items():
                vals[f"n_{c}_as_{d}"] = n
        for c, v in whole["per_class"].items():
            vals[f"{c}_precision"], vals[f"{c}_recall"] = v["precision"], v["recall"]
        RE.metrics.record("raised-edge-sorter", part="segments-0.3.0", session=key, values=vals,
                          deps={"sorter_version": RE.VERSION, "segmentation": ver,
                                "labels": str(_label_path(key).relative_to(RE.STORE)), "label_rows": len(rows),
                                "params": RE.sort_params()},
                          context={"player_to_sort": RE.PLAYER_TO_SORT,
                                   "rule": "last answer per segment wins; unsure out"},
                          note="0.3.0 four-class sorter on the player's direct segment answers")
        print("recorded")
    return out


#: The held-out sample: its size, seed, and length bins (skeleton px, map-zoom units).
SAMPLE_N, SAMPLE_SEED = 40, 20260930
LENGTH_BINS = ((0, RE.BOX_SIDE_MAX), (RE.BOX_SIDE_MAX, 30), (30, 10 ** 6))
PREDICTION_TASK = "line-sorter-0.3-lotus-20260930"


def _sample_path(key: str) -> Path:
    return RE.STORE / "labels" / KIND / f"{key}.sample.json"


def _sample(key: str) -> dict | None:
    p = _sample_path(key)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def predict(key: str = RE.LOTUS_KEY) -> dict:
    """The frozen sorter's class counts on `key`, before any answer exists there, written to
    `<store>/analysis/raised-edges-20260930/predict_<key>.json`."""
    if _label_path(key).is_file():
        raise SystemExit(f"{_label_path(key)} exists: a prediction must precede the answers")
    r, items = _items(key, RE.VERSION)
    mound = _mound(key)
    out = {"key": key, "sorter": RE.VERSION, "zoom": r["zoom"], "cuts": r["cuts"], "gaps": r["gap_px"],
           "segments": len(items),
           "by_class": dict(Counter(p["cls3"] for p in items)),
           "by_shape": dict(Counter(p["shape"] for p in items)),
           "by_class_and_length": {c: [sum(1 for p in items if p["cls3"] == c and lo < p["skeleton_px"] / r["scale"] <= hi)
                                       for lo, hi in LENGTH_BINS] for c in RE.SORT_CLASSES},
           "c_mound_segments": sum(int(((r["_sid"] == p["id"]) & mound).any()) for p in items),
           "connectors": [{k: c[k] for k in ("shape", "x", "y", "w", "h", "px", "joins", "fit_resid", "radius", "cls3")
                           if k in c} for c in r["connectors"]],
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    RE.OUT.mkdir(parents=True, exist_ok=True)
    (RE.OUT / f"predict_{key}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "connectors"}, indent=1))
    return out


def make_sample(key: str = RE.LOTUS_KEY) -> dict:
    """Draw SAMPLE_N segments stratified across the frozen sorter's classes and LENGTH_BINS, with a
    fixed seed, and write the list to `<store>/labels/raised_edge_segment/<key>.sample.json`
    before any answer exists. Each class gets an equal share (a class with fewer segments gives
    its spare places to the others); inside a class, the length bins take turns. Refuses to
    overwrite an existing sample."""
    if _sample_path(key).is_file():
        raise SystemExit(f"{_sample_path(key)} exists; a sample is drawn once")
    if _label_path(key).is_file():
        raise SystemExit(f"{_label_path(key)} exists: the sample must precede the answers")
    r, items = _items(key, RE.VERSION)
    rng = np.random.default_rng(SAMPLE_SEED)
    strata = {}
    for c in RE.SORT_CLASSES:
        for b, (lo, hi) in enumerate(LENGTH_BINS):
            pool = [p for p in items if p["cls3"] == c and lo < p["skeleton_px"] / r["scale"] <= hi]
            strata[(c, b)] = [pool[i] for i in rng.permutation(len(pool))]
    classes = [c for c in RE.SORT_CLASSES if any(strata[(c, b)] for b in range(len(LENGTH_BINS)))]
    quota = dict.fromkeys(classes, 0)
    avail = {c: sum(len(strata[(c, b)]) for b in range(len(LENGTH_BINS))) for c in classes}
    left = SAMPLE_N
    while left and any(quota[c] < avail[c] for c in classes):
        for c in classes:
            if left and quota[c] < avail[c]:
                quota[c] += 1
                left -= 1
    chosen = []
    for c in classes:
        taken, b = 0, 0
        while taken < quota[c]:
            s = strata[(c, b % len(LENGTH_BINS))]
            if s:
                p = s.pop(0)
                chosen.append(dict(p, stratum=f"{c}/{LENGTH_BINS[b % len(LENGTH_BINS)]}"))
                taken += 1
            b += 1
    order = [chosen[i] for i in rng.permutation(len(chosen))]
    mound = _mound(key)
    sample = {"id": f"{key}:{RE.VERSION}:seed{SAMPLE_SEED}:n{len(order)}", "key": key, "sorter": RE.VERSION,
              "seed": SAMPLE_SEED, "n": len(order), "length_bins": LENGTH_BINS, "quota": quota,
              "population": avail, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "items": [{"n": i, "piece": p["piece"], "cls3": p["cls3"], "stratum": p["stratum"],
                         "shape": p["shape"], "skeleton_px": p["skeleton_px"], "x": p["x"], "y": p["y"],
                         "w": p["w"], "h": p["h"],
                         "c_mound": bool(((r["_sid"] == p["id"]) & mound).any())}
                        for i, p in enumerate(order, 1)]}
    _sample_path(key).parent.mkdir(parents=True, exist_ok=True)
    _sample_path(key).write_text(json.dumps(sample, indent=1), encoding="utf-8")
    print(f"wrote {_sample_path(key)}: {len(order)} segments, quota {quota} of {avail}")
    for x in sample["items"]:
        print(f"  {x['n']:2d}/{len(order)}  {x['piece'].split(':seg:')[1]:18s} {x['stratum']:32s} {x['shape']}"
              + ("  C Mound" if x["c_mound"] else ""))
    return sample


def _prediction(task: str = PREDICTION_TASK) -> dict:
    p = RE.STORE / "notes" / "predictions.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    got = [r for r in rows if r.get("task") == task and r.get("kind") == "prediction"]
    if not got:
        raise SystemExit(f"no prediction {task} in {p}")
    return got[0]


def heldout(key: str = RE.LOTUS_KEY, record: bool = False) -> dict:
    """Score the frozen sorter on the held-out sample once the player's answers exist, and
    compare each clause of the frozen prediction (`PREDICTION_TASK`) with the result. The
    prediction's timestamp must precede every answer. C Mound segments are reported apart."""
    if not _label_path(key).is_file():
        raise SystemExit(f"no answers yet: run `label --key {key}` first")
    pred = _prediction()
    last = _labels(key)
    from datetime import datetime
    # answers carry local wall-clock time; the prediction an aware UTC time
    first = min(datetime.fromisoformat(v["at"]).astimezone() for v in last.values())
    if not datetime.fromisoformat(pred["ts"]) < first:
        raise SystemExit(f"the prediction ({pred['ts']}) does not precede the first answer ({first.isoformat()})")
    sample = _sample(key)
    ids = {x["piece"] for x in sample["items"]}
    ans, rows, ver = _sorted_answers(key)
    ans = [a for a in ans if a["piece"] in ids]
    if ver != pred["sorter"]:
        raise SystemExit(f"answers were given on {ver}, the prediction froze {pred['sorter']}")
    t = _table(ans)
    res = {"answered": len(ans), "of": sample["n"], "whole": t}
    got = {"agree_share": t["agree_share"], "box_recall": t["per_class"]["box"]["recall"],
           "ramp_precision": t["per_class"]["ramp_or_elevation_line"]["precision"]}
    verdict = {}
    for name, cl in pred["clauses"].items():
        v = got[name]
        verdict[name] = {"predicted": cl["predicted"], "fail_below": cl["fail_below"], "got": v,
                         "result": None if v is None else ("fail" if v < cl["fail_below"] else "pass")}
    res["verdict"] = verdict
    print(f"{key}: {len(ans)}/{sample['n']} sampled segments answered; prediction {pred['task']} at {pred['ts']}")
    _print_table("held-out sample", t)
    if any(a["mound"] for a in ans):
        res["c_mound"] = _table([a for a in ans if a["mound"]])
        res["without_c_mound"] = _table([a for a in ans if not a["mound"]])
        _print_table("C Mound", res["c_mound"])
        _print_table("without C Mound", res["without_c_mound"])
    for name, v in verdict.items():
        print(f"  {name:16s} predicted {v['predicted']}  fail below {v['fail_below']}  got {v['got']}  -> {v['result']}")
    if record:
        vals = {"answered": len(ans), "scored": t["scored"], "agree": t["agree"], **got}
        for c, row in t["confusion_player_by_sorter"].items():
            for d, n in row.items():
                vals[f"n_{c}_as_{d}"] = n
        RE.metrics.record("raised-edge-sorter", part="heldout-0.3.0", session=key, values=vals,
                          deps={"sorter_version": RE.VERSION, "sample": sample["id"], "prediction": pred["task"]},
                          context={"verdict": verdict}, note="frozen 0.3.0 on the player's held-out Lotus sample")
        print("recorded")
    return res


def queue(key: str, r: dict | None = None, items: list | None = None) -> list[dict]:
    """The labeller's first-session queue: the hash-sorted segments less the carried answers, as
    `label` built it before any direct answer existed. The number the labeller showed was the
    1-based index into this list ("n/221"; going back re-showed the same index).

    Checked, not assumed: the label file's first answers per segment must come in this order, or
    the numbering is ambiguous and this stops."""
    if items is None:
        r, items = _items(key)
    mapped = _mapped(key)
    order = [p for p in items if p["piece"] not in mapped]
    seen, first = set(), []
    for line in _label_path(key).read_text(encoding="utf-8").splitlines():
        if line.strip():
            k = json.loads(line)["piece"]
            if k not in seen:
                seen.add(k)
                first.append(k)
    if first != [p["piece"] for p in order][:len(first)]:
        raise SystemExit("the label file's answer order is not the queue order: the numbering is ambiguous")
    return order


NOTE_SUBCLASSES = ("diagonal_wall", "diagonal_box", "circular_box", "tall_box", "heaven_hell_edge",
                   "overhang_start", "stepped_boxes")


def notes(key: str, spec: Path) -> list[dict]:
    """Resolve the player's notes, given by queue number, to segment keys.

    `spec` (kept in the store, never the repo) is a JSON list of {"n", "subclass", "note"}; the note
    is a paraphrase. Writes `<store>/labels/raised_edge_segment/<key>.notes.jsonl`, one row per note,
    with the player's class and the sorter's call beside it."""
    order = queue(key)
    last = _labels(key)
    out = []
    for s in json.loads(Path(spec).read_text(encoding="utf-8")):
        if s["subclass"] not in NOTE_SUBCLASSES:
            raise SystemExit(f"unknown subclass {s['subclass']}")
        p = order[s["n"] - 1]
        ans = last[p["piece"]]
        out.append({"key": p["piece"], "geometry_key": key, "queue_n": s["n"], "queue_len": len(order),
                    "subclass": s["subclass"], "note": s["note"], "player_class": ans["class"],
                    "derived_class": p["cls"], "answered_at": ans["at"], "x": p["x"], "y": p["y"], "w": p["w"],
                    "h": p["h"], "end_a": p["end_a"], "end_b": p["end_b"], "px": p["px"],
                    "note_date": s.get("date", ""), "version": RE.VERSION, "by": "player (paraphrased)"})
    dst = _label_path(key).with_suffix(".notes.jsonl")
    dst.write_text("".join(json.dumps(x) + "\n" for x in out), encoding="utf-8")
    for x in out:
        print(f"  {x['queue_n']:3d}  {x['key'].split(':seg:')[1]:18s} {x['subclass']:17s} "
              f"player {x['player_class']:22s} sorter {x['derived_class']}")
    print("wrote", dst)
    return out


#: The proposal measured, not applied: these player classes would stop occluding light.
NON_OCCLUDING = ("ramp_or_elevation_line", "heaven_edge", "other")


def occluder_change(key: str, record: bool = False) -> dict:
    """How many baked occluder pixels lie on the segments the player called non-occluding.

    Reads baked geometry and the label files; changes nothing. A noted segment's subclass
    (`<key>.notes.jsonl`) gets its own row, so the overhang-start line and the heaven-hell edge
    stay apart from the plain `other` answers. `ring_occ_px` counts occluder pixels within one
    pixel of a group's segments that belong to no segment of the group: they would still stop a
    ray unless removed with it."""
    r = _classified(key)
    occ = RE.load(key)["occ"]
    sid = r["_sid"]
    by_piece = {signature(key, s): s for s in r["segments"]}
    note_sub = {}
    npath = _label_path(key).with_suffix(".notes.jsonl")
    if npath.is_file():
        for line in npath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line)
                note_sub[x["key"]] = x["subclass"]
    groups = defaultdict(list)
    for k, v in _labels(key).items():
        if v["class"] in NON_OCCLUDING:
            groups[note_sub.get(k, v["class"]) if v["class"] == "other" else v["class"]].append(k)
    for k, m in _mapped(key).items():
        if m["class"] in NON_OCCLUDING:
            groups[f"{m['class']}_carried_0_1_0"].append(k)
    kernel = np.ones((3, 3), np.uint8)
    rows, total = {}, np.zeros(occ.shape, bool)
    for g, keys in sorted(groups.items()):
        m = np.isin(sid, [by_piece[k]["id"] for k in keys])
        ring = (cv2.dilate(m.astype(np.uint8), kernel) > 0) & ~m & (occ > 0) & (sid == 0)
        rows[g] = {"segments": len(keys), "px": int(m.sum()), "occ_wall_px": int((m & (occ == 1)).sum()),
                   "occ_box_px": int((m & (occ == 2)).sum()), "ring_occ_px": int(ring.sum())}
        total |= m
    out = {"key": key, "groups": rows, "total_px": int(total.sum()), "total_occ_px": int((total & (occ > 0)).sum()),
           "baked_occ_px": int((occ > 0).sum()), "baked_wall_px": int((occ == 1).sum()),
           "baked_box_px": int((occ == 2).sum())}
    out["total_ring_occ_px"] = int(((cv2.dilate(total.astype(np.uint8), kernel) > 0) & ~total & (occ > 0)
                                    & (sid == 0)).sum())
    out["share_of_baked_occ"] = round(out["total_occ_px"] / out["baked_occ_px"], 4)
    print(f"{key}: baked occluders {out['baked_occ_px']} px ({out['baked_wall_px']} wall, {out['baked_box_px']} box)")
    for g, v in rows.items():
        print(f"  {g:40s} {v['segments']:3d} seg  {v['px']:4d} px  wall {v['occ_wall_px']:4d}  box {v['occ_box_px']:3d}"
              f"  ring {v['ring_occ_px']}")
    print(f"  total {out['total_occ_px']} occluder px = {out['share_of_baked_occ']} of the baked occluders;"
          f" {out['total_ring_occ_px']} unclaimed occluder px beside them")
    if record:
        vals = {"total_occ_px": out["total_occ_px"], "baked_occ_px": out["baked_occ_px"],
                "total_ring_occ_px": out["total_ring_occ_px"],
                "share_of_baked_occ": out["share_of_baked_occ"]}
        for g, v in rows.items():
            for f, n in v.items():
                vals[f"{g}_{f}"] = n
        RE.metrics.record("raised-edge-occluders", part="non-occluding-proposal", session=key, values=vals,
                          deps={"version": RE.VERSION, "occluders": RE.occluders.occluder_stamp(),
                                "classes": list(NON_OCCLUDING)},
                          context={"applied": False}, note="measured only; baked geometry unchanged")
        print("recorded")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["map", "label", "score", "preview", "sorter", "queue", "notes", "occluders",
                                    "predict", "sample", "heldout"])
    ap.add_argument("--key", default=RE.KEYS[0])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--v2", action="store_true", help="sorter: score raised-edges-0.2.0, the old two classes")
    ap.add_argument("--spec", help="notes: the JSON list of {n, subclass, note} in the store")
    ap.add_argument("--close-after", type=int, default=0,
                    help="label: close the window after this many ms, writing nothing (a check that it opens)")
    a = ap.parse_args()
    _lower_priority()
    cv2.setNumThreads(1)
    if a.cmd in ("sorter", "queue", "notes", "occluders", "predict", "sample", "heldout"):
        if a.cmd == "sorter":
            sorter(a.key, a.record, a.v2)
        elif a.cmd == "queue":
            order = queue(a.key)
            for i, p in enumerate(order, 1):
                print(f"{i:3d}/{len(order)}  {p['piece']}  {p['cls']}")
        elif a.cmd == "notes":
            notes(a.key, Path(a.spec))
        elif a.cmd == "predict":
            predict(a.key)
        elif a.cmd == "sample":
            make_sample(a.key)
        elif a.cmd == "heldout":
            heldout(a.key, a.record)
        else:
            occluder_change(a.key, a.record)
        raise SystemExit(0)
    if a.cmd == "preview":                     # write the first three tiles, for checking the page
        r, items = _items(a.key)
        smp = _sample(a.key)
        if smp is not None:
            by = {p["piece"]: p for p in items}
            todo = [by[x["piece"]] for x in smp["items"]]
        else:
            mapped = _mapped(a.key)
            todo = [p for p in items if p["piece"] not in mapped]
        RE.OUT.mkdir(parents=True, exist_ok=True)
        for p in todo[:3]:
            cv2.imwrite(str(RE.OUT / f"label_preview_{a.key}_seg_{p['id']}.png"), _tile(r, p))
        print(len(items), "segments;", len(todo), "to ask; previews in", RE.OUT)
        raise SystemExit(0)
    if a.cmd == "map":
        cmd_map(a.key)
        raise SystemExit(0)
    raise SystemExit(label(a.key, a.close_after) if a.cmd == "label" else (score(a.key) and 0))
