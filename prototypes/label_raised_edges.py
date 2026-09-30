r"""Ask the player what each drawn line segment of the baked Ascent static is.

    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py map
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py score
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py preview
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py sorter [--record]
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py queue
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py notes --spec <store json>
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py occluders [--record]

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


def _classified(key: str) -> dict:
    r = RE.classify(key)
    heavens = RE.shade_heavens(r)
    RE.annotate_pieces(r, heavens)
    RE.segments(r)
    RE.annotate_pieces(r, heavens, "segments", "_sid")
    return r


def _items(key: str) -> tuple[dict, list[dict]]:
    r = _classified(key)
    items = [dict(s, piece=signature(key, s)) for s in r["segments"] if s["cls"] in ("wall", "raised_edge")]
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


def label(key: str) -> int:
    import tkinter as tk

    r, items = _items(key)
    done = _labels(key)
    mapped = _mapped(key)
    if not _mapped_path(key).is_file():
        raise SystemExit("run `map` first, so segments the player already answered are not asked again")
    order = [p for p in items if p["piece"] not in done and p["piece"] not in mapped]
    print(f"{len(items)} segments on {key}: {len(mapped)} carry an old answer, "
          f"{len([p for p in items if p['piece'] in done])} answered here, {len(order)} to ask", flush=True)
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
        info.configure(text=(
            f"{state['k'] + 1}/{len(order)}   {key}   the line inside the yellow box, between the magenta ticks\n"
            "1 wall (blocks vision)   2 ramp or elevation line (vision crosses)   3 box outline\n"
            "4 heaven edge   5 other drawn mark   0 other   U unsure   A back   Q quit"))

    def write(cls):
        p = order[state["k"]]
        row = {"key": p["piece"], "piece": p["piece"], "geometry_key": key, "class": cls,
               "uncertain": cls == "unsure", "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
               "end_a": p["end_a"], "end_b": p["end_b"], "px": p["px"], "shape": p["shape"],
               "derived_class": p["cls"], "heavens": p["heavens"], "ramp_near_share": p["ramp_near_share"],
               "compared_against_derived": False, "version": RE.VERSION, "by": "player",
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


def sorter(key: str, record: bool = False) -> dict:
    """Confusion of the sorter's derived class against the player's direct segment answers.

    Reads the label file only (each row carries the derived class it was shown with). One row per
    segment: the last answer wins, as the labeller documents, so a segment the player went back
    to counts once. Unsure answers stay out."""
    p = _label_path(key)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    last = _labels(key)
    versions = sorted({v["version"] for v in last.values()})
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
    ap.add_argument("cmd", choices=["map", "label", "score", "preview", "sorter", "queue", "notes", "occluders"])
    ap.add_argument("--key", default=RE.KEYS[0])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--spec", help="notes: the JSON list of {n, subclass, note} in the store")
    a = ap.parse_args()
    if a.cmd in ("sorter", "queue", "notes", "occluders"):
        _lower_priority()
        cv2.setNumThreads(1)
        if a.cmd == "sorter":
            sorter(a.key, a.record)
        elif a.cmd == "queue":
            order = queue(a.key)
            for i, p in enumerate(order, 1):
                print(f"{i:3d}/{len(order)}  {p['piece']}  {p['cls']}")
        elif a.cmd == "notes":
            notes(a.key, Path(a.spec))
        else:
            occluder_change(a.key, a.record)
        raise SystemExit(0)
    if a.cmd == "preview":                     # write the first three tiles, for checking the page
        r, items = _items(a.key)
        mapped = _mapped(a.key)
        todo = [p for p in items if p["piece"] not in mapped]
        RE.OUT.mkdir(parents=True, exist_ok=True)
        for p in todo[:3]:
            cv2.imwrite(str(RE.OUT / f"label_preview_seg_{p['id']}.png"), _tile(r, p))
        print(len(items), "segments;", len(todo), "not mapped; previews in", RE.OUT)
        raise SystemExit(0)
    if a.cmd == "map":
        cmd_map(a.key)
        raise SystemExit(0)
    raise SystemExit(label(a.key) if a.cmd == "label" else (score(a.key) and 0))
