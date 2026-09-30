r"""Bake the sorted line classes into each (map, profile) geometry npz, for `reticle.occluders`.

    .\.venv\Scripts\python.exe prototypes\line_classes.py bake --all [--dry-run]
    .\.venv\Scripts\python.exe prototypes\line_classes.py bake KEY
    .\.venv\Scripts\python.exe prototypes\line_classes.py stamp KEY

line-classes-1.0.0. The builder half of occluders-2.0.0 (`reticle/occluders.py`, which reads
what this writes and owns [owns:map-occluders]). The player approved rebuilding the baked
occluders from the line labels and the sorter on 2026-09-30.

What it writes, additively, as `map_shade` does (every other array is written back unchanged):

    line_cls           uint8  per line pixel of `occluders.lines`: wall, box, ramp, other, unread
    line_src           uint8  where the class came from (`occluders.SRC_*`)
    line_hints         str    JSON: box-height hints, each with its source
    lines_meta         str    JSON: version, validation status, counts, the label files read
    lines_static_sha   str    `occluders.static_sha` of the static the classes were read from
    lines_built_by     str    `stamp(key)`: this file, the sorter, the labeller, the owner's line
                              rule, and every label, note and heights file the key reads
    lines_version      str    LINES_VERSION

A key the sanity rule refuses gets `lines_refused` (the reason) and no `line_cls`, so its table
keeps occluders-1's rule and says so.

The classes, in order of authority:

1. the player's direct segment answers (`labels/raised_edge_segment/<key>.jsonl`, the last answer
   per segment winning), each answer's class mapped by the sorter's `PLAYER_TO_SORT`, over the
   segmentation the answer was given on (0.2.0 on Ascent 465 px, 0.3.0 on Lotus 465 px); an
   `unsure` answer overrides nothing;
2. the player's 0.1.0 piece answers carried to 0.2.0 segments (`mapped_<key>.json`), where no
   direct answer names the pixel;
3. the frozen sorter (raised-edges-0.3.0): segments, connectors (rule G) and fragments;
4. a line pixel nothing claims takes the nearest classed line pixel's class within
   NEAREST_PX (map-zoom px), else it stays UNREAD.

Height hints. The player's `tall_box` notes (`<key>.notes.jsonl`) are `segment` hints of class
tall; the heights files (`domain/heights/<key>.toml`, `[[occluder]]` rows) are `bbox` hints of
their class (short, tall, by_floor with `class_by_floor`, or does_not_block). `occluders.apply_lines`
decides which boxes a hint names. Nothing else gives a height: every other box is unknown.

Validation. Ascent 465 px and Lotus 465 px carry the player's answers
([metric:raised-edge-sorter/segments-0.3.0@ascent__valorant-16x9-bigmap#agree=209] of 221 on
Ascent, [metric:raised-edge-sorter/heldout-0.3.0@lotus__valorant-16x9-bigmap#agree=35] of 40
held out on Lotus). Every other key is UNVALIDATED: the sorter's invariants were tuned on Ascent
and tested once on Lotus, and `lines_meta` says so on each such key.

Sanity rule, fixed before any unvalidated key was baked: a key is refused when more than
REFUSE_WALL_OPEN_SHARE of the line pixels occluders-1 called WALL become non-occluding (most
walls turned into ramps). A key whose colour cut falsifies invariant C (more than 1% of its void
passed or its terrain refused) is flagged in `lines_meta`, not refused.

Reads baked geometry, label files and the heights files only; never a session's pixels, never a
video [domain:capture/session-pixels-are-not-the-map].
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import label_raised_edges as LRE  # noqa: E402
import raised_edges as RE  # noqa: E402
from reticle import geometry, metrics, occluders as O  # noqa: E402

LINES_VERSION = "line-classes-1.0.0"
ROOT = Path(__file__).resolve().parents[1]
HEIGHTS_DIR = ROOT / "domain" / "heights"
#: An unclaimed line pixel takes the nearest classed line pixel's class within this (map-zoom px).
NEAREST_PX = 2.0
#: The sanity rule: refuse a key when more than this share of occluders-1's WALL line px opens.
REFUSE_WALL_OPEN_SHARE = 0.5
#: Invariant C's falsifier: a colour cut passing more than this share of void or refusing more
#: than this share of terrain.
CUT_FALSIFY = 0.01
#: The keys the player's answers validate, and the runs that measured them.
VALIDATED = {
    "ascent__valorant-16x9-bigmap": "the player's 221 segment answers: raised-edge-sorter/segments-0.3.0 agree 209",
    "lotus__valorant-16x9-bigmap": "the player's 40 held-out answers: raised-edge-sorter/heldout-0.3.0 agree 35",
}
SORT_CODE = {"wall": O.LINE_WALL, "box": O.LINE_BOX, "ramp_or_elevation_line": O.LINE_RAMP,
             "other": O.LINE_OTHER}


def _norm(p: Path) -> bytes:
    """A file's bytes with line endings normalised, so a checkout's CRLF does not restamp."""
    return p.read_bytes().replace(b"\r\n", b"\n") if p.is_file() else b"<absent>"


def inputs(key: str) -> dict:
    """Every file this key's classes rest on, by role."""
    lab = RE.STORE / "labels" / LRE.KIND
    return {"labels": lab / f"{key}.jsonl", "notes": lab / f"{key}.notes.jsonl",
            "sample": lab / f"{key}.sample.json", "mapped": LRE._mapped_path(key),
            "heights": HEIGHTS_DIR / f"{key}.toml"}


def stamp(key: str) -> str:
    """This file, the sorter, the labeller, the owner's line and shape rules, and the key's label,
    note, sample, carried-answer and heights files: `lines_built_by`."""
    h = hashlib.sha256()
    for p in (Path(__file__), Path(RE.__file__), Path(LRE.__file__)):
        h.update(_norm(p))
    h.update(metrics.fingerprint(O.lines, O.classify, O.seal_diagonals, O._fill, O.line_mask).encode())
    for role, p in sorted(inputs(key).items()):
        h.update(role.encode() + _norm(p))
    return h.hexdigest()


def _answers(key: str) -> tuple[dict, str | None]:
    """The player's last answer per segment signature, and the segmentation they were given on."""
    last = LRE._labels(key) if LRE._label_path(key).is_file() else {}
    versions = sorted({v["version"] for v in last.values()})
    if len(versions) > 1:
        raise SystemExit(f"{key}: answers on more than one segmentation: {versions}")
    return last, (versions[0] if versions else None)


def _seg_masks(r: dict, key: str) -> dict:
    return {LRE.signature(key, s): r["_sid"] == s["id"] for s in r["segments"]}


def read(key: str) -> dict:
    """The key's per-pixel line classes, sources and height hints. Pure over stored files."""
    t0 = time.time()
    r = LRE._classified(key, RE.VERSION)               # the frozen 0.3.0 reading, sorted
    line, sid = r["_line"], r["_sid"]
    if not np.array_equal(line, O.line_mask(r["_static"], r["_labels"])):
        raise SystemExit(f"{key}: the sorter's line mask is not the owner's")
    cls = np.zeros(line.shape, np.uint8)
    src = np.zeros(line.shape, np.uint8)
    for s in r["segments"]:
        c = s.get("cls3")
        if c is None:
            continue
        m = sid == s["id"]
        cls[m] = SORT_CODE[c]
        src[m] = O.SRC_CONNECTOR if s.get("connector") else O.SRC_FRAGMENT if s.get("fragment") else O.SRC_SEGMENT
    sorter_cls = cls.copy()
    # unclaimed line pixels: the nearest classed line pixel's class, within NEAREST_PX
    zm = float(r["scale"])
    todo = line & (cls == 0)
    if todo.any() and (cls > 0).any():
        dist, lab = cv2.distanceTransformWithLabels((cls == 0).astype(np.uint8), cv2.DIST_L2, 5,
                                                    labelType=cv2.DIST_LABEL_PIXEL)
        zy, zx = np.nonzero(cls > 0)
        lut = np.zeros(lab.max() + 1, np.uint8)
        lut[lab[zy, zx]] = cls[zy, zx]
        near = todo & (dist <= NEAREST_PX * zm)
        cls[near], src[near] = lut[lab[near]], O.SRC_NEAREST
    left = line & (cls == 0)
    cls[left], src[left] = O.LINE_UNREAD, O.SRC_UNREAD
    # the player's answers override
    last, ver = _answers(key)
    mapped = LRE._mapped(key)
    label_rows = {"direct": 0, "direct_unsure": 0, "carried": 0}
    disagree = Counter()
    player = np.zeros(line.shape, np.uint8)
    if last or mapped:
        seg_ver = ver or LRE.seg_version(key)
        r_seg = r if seg_ver == RE.VERSION else LRE._classified(key, seg_ver)
        masks = _seg_masks(r_seg, key)
        for k, m in mapped.items():
            if k not in masks:
                raise SystemExit(f"{key}: carried answer {k} is not reproduced by {seg_ver}")
            if k in last:
                continue                            # a direct answer wins
            mm = masks[k] & line
            c = SORT_CODE[RE.PLAYER_TO_SORT[m["class"]]]
            player[mm], src[mm] = c, O.SRC_CARRIED
            label_rows["carried"] += 1
        for k, a in last.items():
            if k not in masks:
                raise SystemExit(f"{key}: answered segment {k} is not reproduced by {seg_ver}")
            if a["class"] == "unsure":
                label_rows["direct_unsure"] += 1
                continue
            mm = masks[k] & line
            c = SORT_CODE[RE.PLAYER_TO_SORT[a["class"]]]
            player[mm], src[mm] = c, O.SRC_PLAYER
            label_rows["direct"] += 1
        over = player > 0
        for a, b in zip(sorter_cls[over], player[over]):
            if a != b:
                disagree[f"{O.LINE_NAMES.get(int(a), 'unclaimed')}->{O.LINE_NAMES[int(b)]}"] += 1
        cls[over] = player[over]
    hints = height_hints(key, r_seg if (last or mapped) else r)
    counts = {O.LINE_NAMES[c]: int((cls == c).sum()) for c in O.LINE_NAMES}
    srcs = {O.SRC_NAMES[c]: int((src == c).sum()) for c in O.SRC_NAMES}
    cuts = r["cuts"]
    c_falsified = (cuts.get("void_pass", 0) > CUT_FALSIFY) or (1 - cuts.get("terrain_pass", 1) > CUT_FALSIFY)
    return {"key": key, "cls": cls, "src": src, "hints": hints, "line_px": int(line.sum()),
            "counts": counts, "sources": srcs, "label_rows": label_rows,
            "label_px": int((src == O.SRC_PLAYER).sum() + (src == O.SRC_CARRIED).sum()),
            "label_overrides_px": dict(disagree), "zoom": r["zoom"], "cuts": cuts,
            "invariant_c_falsified": bool(c_falsified), "gap_px": r["gap_px"],
            "segments": sum(1 for s in r["segments"] if not s.get("connector")),
            "connectors": len(r["connectors"]), "seconds": round(time.time() - t0, 1),
            "_static": r["_static"], "_labels": r["_labels"], "_line": line}


def height_hints(key: str, r_seg: dict) -> list[dict]:
    """The player's tall-box notes as `segment` hints; the heights file's occluders as `bbox`
    hints. Every hint names its source."""
    out = []
    np_ = inputs(key)["notes"]
    if np_.is_file():
        masks = {LRE.signature(key, s): r_seg["_sid"] == s["id"] for s in r_seg["segments"]}
        for row in (json.loads(x) for x in np_.read_text(encoding="utf-8").splitlines() if x.strip()):
            if row["subclass"] != "tall_box":
                continue
            if row["key"] not in masks:
                raise SystemExit(f"{key}: noted segment {row['key']} is not reproduced")
            ys, xs = np.nonzero(masks[row["key"]])
            out.append({"id": f"note:{row['key'].split(':seg:')[1]}", "kind": "segment", "class": "tall",
                        "px": [[int(x), int(y)] for x, y in zip(xs, ys)],
                        "source": f"labels/{LRE.KIND}/{key}.notes.jsonl queue {row['queue_n']} "
                                  f"({row['by']}, {row['note_date']})",
                        "note": row["note"]})
    hp = inputs(key)["heights"]
    if hp.is_file():
        data = tomllib.loads(hp.read_text(encoding="utf-8"))
        for oc in data.get("occluder", []):
            out.append({"id": f"heights:{oc['id']}", "kind": "bbox", "class": oc["class"],
                        "bbox": [int(v) for v in oc["bbox"]],
                        "class_by_floor": oc.get("class_by_floor", {}),
                        "source": f"domain/heights/{key}.toml [[occluder]] {oc['id']} ({oc.get('version', '')}, "
                                  f"{oc.get('source', '')})", "where": oc.get("where", "")})
    return out


def sanity(key: str, rd: dict, arrays: dict) -> dict:
    """The refusal rule against occluders-1's table on this key: the share of its WALL line
    pixels the classes open, and the share of its occluding line pixels they keep."""
    occ1, _, _ = O.classify(arrays["static"], arrays["labels"])
    line, cls = rd["_line"], rd["cls"]
    wall1 = line & (occ1 == O.WALL)
    opened = np.isin(cls, (O.LINE_RAMP, O.LINE_OTHER))
    share = float((wall1 & opened).sum()) / max(1, int(wall1.sum()))
    occl1 = line & (occ1 > 0)
    return {"old_wall_line_px": int(wall1.sum()), "old_wall_line_opened_px": int((wall1 & opened).sum()),
            "old_wall_line_opened_share": round(share, 4),
            "old_occluding_line_px": int(occl1.sum()),
            "old_occluding_line_opened_share": round(float((occl1 & opened).sum()) / max(1, int(occl1.sum())), 4),
            "refused": share > REFUSE_WALL_OPEN_SHARE}


def bake_key(key: str, store: Path = RE.STORE, write: bool = True) -> dict:
    """Read one key's classes and write them into its npz (or `lines_refused`)."""
    p = geometry.path(key, store)
    with np.load(p, allow_pickle=False) as z:
        arrays = {k: z[k].copy() for k in z.files}
    rd = read(key)
    if not np.array_equal(rd["_static"], arrays["static"]):
        raise SystemExit(f"{key}: the sorter read another static than {p}")
    sn = sanity(key, rd, arrays)
    val = VALIDATED.get(key)
    meta = {"version": LINES_VERSION, "sorter": RE.VERSION, "key": key,
            "validation": {"status": "labels" if val else "unvalidated",
                           "by": val or ("no player answers on this key; the sorter's invariants were "
                                         "tuned on Ascent 465 px and held out once on Lotus 465 px")},
            "line_px": rd["line_px"], "counts": rd["counts"], "sources": rd["sources"],
            "label_rows": rd["label_rows"], "label_px": rd["label_px"],
            "label_overrides_px": rd["label_overrides_px"], "zoom": rd["zoom"], "cuts": rd["cuts"],
            "invariant_c_falsified": rd["invariant_c_falsified"], "gap_px": rd["gap_px"],
            "sanity": sn, "refuse_rule": f"old WALL line px opened > {REFUSE_WALL_OPEN_SHARE}",
            "hints": [{k: v for k, v in h.items() if k != "px"} for h in rd["hints"]],
            "inputs": {k: str(v) for k, v in inputs(key).items() if v.is_file()},
            "params": {"nearest_px": NEAREST_PX, **RE.sort_params()},
            "baked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    for k in ("line_cls", "line_src", "line_hints", "lines_meta", "lines_static_sha", "lines_built_by",
              "lines_version", "lines_refused"):
        arrays.pop(k, None)
    arrays.update(lines_meta=np.array(json.dumps(meta)), lines_built_by=np.array(stamp(key)),
                  lines_version=np.array(LINES_VERSION), lines_static_sha=np.array(O.static_sha(arrays["static"])))
    if sn["refused"]:
        arrays["lines_refused"] = np.array(
            f"{sn['old_wall_line_opened_share']} of occluders-1's wall line px would open "
            f"(rule: > {REFUSE_WALL_OPEN_SHARE}); {LINES_VERSION}")
    else:
        arrays.update(line_cls=rd["cls"], line_src=rd["src"], line_hints=np.array(json.dumps(rd["hints"])))
    if write:
        tmp = p.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(p)
    return dict(meta, seconds=rd["seconds"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["bake", "stamp"])
    ap.add_argument("key", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="write each key's meta JSON here")
    a = ap.parse_args(argv)
    LRE._lower_priority()
    cv2.setNumThreads(1)
    keys = sorted(q.stem for q in (RE.STORE / "geometry").glob("*.npz")) if a.all else [a.key]
    if a.cmd == "stamp":
        for k in keys:
            print(k, stamp(k))
        return 0
    res = {}
    for k in keys:
        m = bake_key(k, write=not a.dry_run)
        res[k] = m
        sn = m["sanity"]
        print(f"{k}: {m['validation']['status']}; line px {m['line_px']} {m['counts']}; labels "
              f"{m['label_px']} px; old wall line opened {sn['old_wall_line_opened_share']}"
              f"{' REFUSED' if sn['refused'] else ''}; C falsified {m['invariant_c_falsified']}; "
              f"{m['seconds']} s" + (" (dry run)" if a.dry_run else ""), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
