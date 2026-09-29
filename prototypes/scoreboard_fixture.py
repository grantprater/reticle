r"""Score the scoreboard reader on the store fixture `fixtures/scoreboard_edges`.

    .\.venv\Scripts\python.exe prototypes\scoreboard_fixture.py score OUT.json [--fixture DIR] [--ref REV] [--roi]
    .\.venv\Scripts\python.exe prototypes\scoreboard_fixture.py sheets SCORE.json OUTDIR [--fixture DIR] [--per 4]
    .\.venv\Scripts\python.exe prototypes\scoreboard_fixture.py crop OUTDIR [--fixture DIR]

The fixture holds decoded Tab boards as lossless PNG crops of the frame, one
per board, with `index.jsonl` naming each board's session, frame, group and
split. `manifest.json` gives the crop box in frame pixels (x1 and y1
exclusive); a fixture without one holds rows 150-899 at full width, as the
first decode wrote it (docs/SCOREBOARD_PRESENCE.md, "The table's frame").

`score` pastes each crop at its frame position into a black 1920x1080 frame
and feeds it to `scoreboard.ScoreboardReader`, so every board gets the
reader's samples and row observations, portrait scores included, and the
openings gate's verdict (`adjudication.scoreboard.scoreboard_openings`).
`--ref REV` reads each board also with `reticle/scoreboard.py` as committed at
REV, loaded beside the current module. `--roi` reads each board again after
blanking every pixel outside `scoreboard.reader_roi`: equal reads are the
invariance the ROI claims. It also records, per board, whether the row test's
row set moves when only the table's columns count (`table_columns`).

`sheets` draws each board whose current read differs from the reference read
as a pair, the reference left and the current right, each cropped to the
reader's ROI, with the table's edges and every row drawn.

`crop` writes the fixture cropped to the reader's ROI (lossless PNG, box in
the manifest), after checking each written crop reads back bit for bit.

No video decode. One process, one thread, Idle priority.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"
if os.name == "nt":
    _k32 = ctypes.windll.kernel32
    _k32.GetCurrentProcess.restype = ctypes.c_void_p       # a 64-bit pseudo-handle
    _k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _k32.SetPriorityClass(_k32.GetCurrentProcess(), 0x40)   # IDLE_PRIORITY_CLASS
else:
    os.setpriority(os.PRIO_PROCESS, 0, 19)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import scoreboard as sb  # noqa: E402
from reticle.adjudication.scoreboard import scoreboard_openings  # noqa: E402
from reticle.decode import Sample  # noqa: E402
from reticle.version import SCOREBOARD_VERSION  # noqa: E402

STORE = Path.home() / "reticle-store"
FIXTURE = STORE / "fixtures" / "scoreboard_edges"
FRAME_WH = (1920, 1080)
FULL_WIDTH_BOX = {"x0": 0, "y0": 150, "x1": 1920, "y1": 900}


def load_fixture(fixture: Path) -> tuple[dict, list[dict]]:
    man = fixture / "manifest.json"
    box = json.loads(man.read_text(encoding="utf-8"))["crop"] if man.exists() else FULL_WIDTH_BOX
    with open(fixture / "index.jsonl", encoding="utf-8") as f:
        index = [json.loads(line) for line in f if line.strip()]
    return box, index


def paste(fixture: Path, row: dict, box: dict) -> np.ndarray:
    crop = cv2.imread(str(fixture / row["file"]), cv2.IMREAD_UNCHANGED)
    assert crop is not None and crop.shape[:2] == (box["y1"] - box["y0"], box["x1"] - box["x0"]), row["file"]
    frame = np.zeros((FRAME_WH[1], FRAME_WH[0], 3), np.uint8)
    frame[box["y0"]:box["y1"], box["x0"]:box["x1"]] = crop
    return frame


_PROFILES: dict[str, str] = {}


def profile_of(session: str) -> str:
    if session not in _PROFILES:
        man = STORE / "manifests" / f"{session}.json"
        _PROFILES[session] = json.loads(man.read_text(encoding="utf-8"))["source_profile"]
    return _PROFILES[session]


def load_ref(rev: str):
    """`reticle/scoreboard.py` at `rev`, imported as a sibling of the current
    module so its relative imports resolve to today's package."""
    src = subprocess.run(["git", "show", f"{rev}:reticle/scoreboard.py"], cwd=ROOT,
                         check=True, capture_output=True).stdout
    path = Path(tempfile.mkdtemp(prefix="sb_ref_")) / "scoreboard_ref.py"
    path.write_bytes(src)
    name = "reticle._scoreboard_ref"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    # The copy imports today's version.py; name it by the version at `rev`.
    ver = subprocess.run(["git", "show", f"{rev}:reticle/version.py"], cwd=ROOT,
                         check=True, capture_output=True, text=True).stdout
    mod.REF_VERSION = next(line.split('"')[1] for line in ver.splitlines()
                           if line.startswith("SCOREBOARD_VERSION ="))
    return mod


class Board:
    """One module's ScoreboardReader per profile, reset for every board."""

    def __init__(self, module, version: str = SCOREBOARD_VERSION):
        self.module, self.readers, self.version = module, {}, version

    def read(self, frame: np.ndarray, row: dict) -> dict:
        prof = profile_of(row["session"])
        if prof not in self.readers:
            self.readers[prof] = self.module.ScoreboardReader(prof, icons_root=STORE)
        reader = self.readers[prof]
        reader.rows, reader.samples = [], []
        reader.frames_offered = reader.frames_open = 0
        reader.feed(Sample(int(row["frame_idx"]), float(row["t_ms"]), frame))
        events = reader.events(row["session"])
        rows = [e for e in events if e["kind"] == "row_observation"]
        sample = next(e for e in events if e["kind"] == "sample")
        openings = scoreboard_openings(events)
        gate = openings[0] if openings else None
        return {"version": self.version,
                "open": sample["open"], "reason": sample["reason"], "anchor": sample["anchor"],
                "strip": sample["strip"], "confirm": sample["confirm"],
                "x0": rows[0]["table_x0"] if rows else None,
                "x1": rows[0]["table_x1"] if rows else None,
                "rows": [[r["team"], r["row_y0"], r["row_y1"], r["kills"], r["deaths"],
                          r["assists"], r["credits"], r["is_player"]] for r in rows],
                "portraits": [[r.get("portrait_agent_best"), r.get("portrait_agent_score")]
                              for r in rows],
                "observations": [{k: v for k, v in r.items()
                                  if k not in ("scoreboard_version", "observation_key")}
                                 for r in rows],
                "gate": None if gate is None else {"accepted": gate["accepted"],
                                                   "reason": gate["reason"]}}


def row_sets_move(frame: np.ndarray, rect) -> dict:
    """Whether a frame row passes the row test differently when only the
    table's columns count, per colour."""
    g_all, r_all = sb._slabs(frame)
    g_tab, r_tab = sb._slabs(frame, sb.table_columns(rect))
    out = {}
    for name, a, b in (("green", g_all, g_tab), ("red", r_all, r_tab)):
        pa, pb = a.sum(axis=1) > sb.MIN_TABLE_W, b.sum(axis=1) > sb.MIN_TABLE_W
        out[name] = int((pa != pb).sum())
    return out


def score(args) -> int:
    fixture = Path(args.fixture)
    box, index = load_fixture(fixture)
    cur = Board(sb)
    ref = None
    if args.ref:
        mod = load_ref(args.ref)
        ref = Board(mod, mod.REF_VERSION)
    boards = []
    for i, row in enumerate(index):
        frame = paste(fixture, row, box)
        rect = sb.strip_rect(profile_of(row["session"]), *FRAME_WH)
        got = {"file": row["file"], "session": row["session"], "frame_idx": row["frame_idx"],
               "group": row.get("group"), "split": row.get("split"), "cur": cur.read(frame, row)}
        if ref is not None:
            got["ref"] = ref.read(frame, row)
        if rect is not None:
            got["row_sets_move"] = row_sets_move(frame, rect)
        if args.roi:
            if rect is None:
                got["roi"] = None
            else:
                x0, y0, x1, y1 = sb.reader_roi(rect, FRAME_WH[1])
                blank = np.zeros_like(frame)
                blank[y0:y1, x0:x1] = frame[y0:y1, x0:x1]
                got["roi"] = cur.read(blank, row)
                got["roi_box"] = [x0, y0, x1, y1]
        boards.append(got)
        if i % 50 == 0:
            print(i, flush=True)
    summary = {"boards": len(boards), "reader": SCOREBOARD_VERSION,
               "cur_open": sum(b["cur"]["open"] for b in boards),
               "cur_accepted": sum(bool(b["cur"]["gate"] and b["cur"]["gate"]["accepted"])
                                   for b in boards)}
    if args.roi:
        summary["roi_equal"] = sum(b["roi"] is not None and b["roi"] == b["cur"] for b in boards)
    if ref is not None:
        changed = [b for b in boards if _read_key(b["ref"]) != _read_key(b["cur"])]
        summary.update({
            "ref": args.ref, "ref_version": boards[0]["ref"]["version"] if boards else None,
            "ref_open": sum(b["ref"]["open"] for b in boards),
            "ref_accepted": sum(bool(b["ref"]["gate"] and b["ref"]["gate"]["accepted"])
                                for b in boards),
            "changed": len(changed),
            "changed_row_sets_equal": sum(1 for b in changed
                                          if not any(b.get("row_sets_move", {}).values()))})
    Path(args.out).write_text(json.dumps({"fixture": str(fixture), "box": box,
                                          "summary": summary, "boards": boards}),
                              encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def _read_key(read: dict) -> tuple:
    """What a read says, without portrait descriptors: the verdict, edges and rows."""
    return (read["open"], read["reason"], read["anchor"], read["confirm"],
            read["x0"], read["x1"], json.dumps(read["rows"]))


def _placed(read: dict) -> tuple:
    """Where a read puts the table: open or not, its edges and its rows."""
    return (read["open"], read["x0"], read["x1"], json.dumps(read["rows"]))


def _draw_read(panel: np.ndarray, read: dict, ox: int, oy: int, title: str) -> np.ndarray:
    img = panel.copy()
    h = img.shape[0]
    if read["open"]:
        for x in (read["x0"], read["x1"]):
            cv2.line(img, (x - ox, 0), (x - ox, h - 1), (255, 255, 0), 1)
        for team, y0, y1, k, d, a, *_ in read["rows"]:
            colour = (0, 255, 0) if team == "ally" else (0, 0, 255)
            cv2.rectangle(img, (read["x0"] - ox, y0 - oy), (read["x1"] - ox, y1 - oy), colour, 1)
            cv2.putText(img, f"{k}/{d}/{a}", (read["x1"] - ox - 70, y0 - oy + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, colour, 1, cv2.LINE_AA)
    gate = read["gate"]
    verdict = ("open" if read["open"] else f"closed {read['reason']}")
    verdict += f" {read['anchor']}"
    if gate is not None:
        verdict += " gate " + ("ACCEPT" if gate["accepted"] else str(gate["reason"]))
    for j, text in enumerate((title, verdict)):
        cv2.putText(img, text, (4, 16 + 18 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, text, (4, 16 + 18 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def sheets(args) -> int:
    data = json.loads(Path(args.score).read_text(encoding="utf-8"))
    fixture = Path(args.fixture)
    box, _ = load_fixture(fixture)
    index = {r["file"]: r for r in load_fixture(fixture)[1]}
    changed = [b for b in data["boards"] if "ref" in b and _read_key(b["ref"]) != _read_key(b["cur"])]
    if args.placed_only:
        # Only boards whose verdict, edges or rows moved; a change of reason,
        # anchor or confirmation alone places every row where it was.
        changed = [b for b in changed if _placed(b["ref"]) != _placed(b["cur"])]
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    pairs = []
    for b in changed:
        frame = paste(fixture, index[b["file"]], box)
        rect = sb.strip_rect(profile_of(b["session"]), *FRAME_WH)
        x0, _, x1, _ = sb.reader_roi(rect, FRAME_WH[1])
        # A read reaching past the ROI is drawn whole: widen to show it.
        xs = [v for r in (b["ref"], b["cur"]) if r["open"] for v in (r["x0"], r["x1"])]
        x0, x1 = min([x0, *xs]), max([x1, *xs]) + 1
        y0, y1 = box["y0"], box["y1"]
        panel = frame[y0:y1, x0:x1]
        tag = f"{b['file'][:-4]} {b['group']}"
        left = _draw_read(panel, b["ref"], x0, y0, f"{b['ref']['version']} {tag}")
        right = _draw_read(panel, b["cur"], x0, y0, f"{b['cur']['version']}")
        pair = np.hstack([left, np.full((panel.shape[0], 6, 3), 255, np.uint8), right])
        pairs.append((b["file"], pair))
    per = int(args.per)
    names = []
    for k in range(0, len(pairs), per):
        group = pairs[k:k + per]
        w = max(p.shape[1] for _, p in group)
        rows = [np.pad(p, ((0, 6), (0, w - p.shape[1]), (0, 0)), constant_values=255) for _, p in group]
        sheet = np.vstack(rows)
        if args.scale != 1.0:
            sheet = cv2.resize(sheet, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA)
        name = out / f"scoreboard_rows_changed_{k // per:02d}.png"
        cv2.imwrite(str(name), sheet)
        names.append({"sheet": name.name, "boards": [f for f, _ in group]})
    (out / "scoreboard_rows_changed.json").write_text(json.dumps(names, indent=1), encoding="utf-8")
    print(len(changed), "changed boards on", len(names), "sheets in", out)
    return 0


def crop(args) -> int:
    fixture = Path(args.fixture)
    box, index = load_fixture(fixture)
    rects = {sb.strip_rect(profile_of(r["session"]), *FRAME_WH) for r in index}
    rois = {sb.reader_roi(rect, FRAME_WH[1]) for rect in rects if rect is not None}
    if None in rects or len(rois) != 1:
        raise SystemExit(f"one reader ROI expected over the fixture's profiles, got {rois} {rects}")
    rx0, _, rx1, _ = rois.pop()
    new = {"x0": max(rx0, box["x0"]), "y0": box["y0"], "x1": min(rx1, box["x1"]), "y1": box["y1"]}
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=False)
    for row in index:
        frame = paste(fixture, row, box)
        part = np.ascontiguousarray(frame[new["y0"]:new["y1"], new["x0"]:new["x1"]])
        cv2.imwrite(str(out / row["file"]), part, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        back = cv2.imread(str(out / row["file"]), cv2.IMREAD_UNCHANGED)
        if back is None or not np.array_equal(back, part):
            raise SystemExit(f"{row['file']} does not read back bit for bit")
    with open(fixture / "index.jsonl", encoding="utf-8") as src, \
            open(out / "index.jsonl", "w", encoding="utf-8", newline="\n") as dst:
        dst.write(src.read())
    manifest = {
        "fixture": "scoreboard_edges", "crop": new, "frame_wh": list(FRAME_WH),
        "format": "PNG, lossless, BGR uint8",
        "load": "paste each crop at frame[y0:y1, x0:x1] of a black 1920x1080 frame",
        "roi": f"scoreboard.reader_roi at {SCOREBOARD_VERSION}, cut to the decoded rows",
        "note": (f"crop box in frame pixels, x1 and y1 exclusive: frame x {new['x0']}-{new['x1'] - 1}, "
                 f"rows {new['y0']}-{new['y1'] - 1}. Cropped from the full-width decode of "
                 "2026-09-28 (rows 150-899); pixels inside the box are byte-identical to it.")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote", len(index), "boards to", out, "box", new)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("out")
    s.add_argument("--fixture", default=str(FIXTURE))
    s.add_argument("--ref", help="a git revision whose reticle/scoreboard.py reads each board too")
    s.add_argument("--roi", action="store_true", help="read each board again inside reader_roi only")
    s.set_defaults(fn=score)
    s = sub.add_parser("sheets")
    s.add_argument("score")
    s.add_argument("outdir")
    s.add_argument("--fixture", default=str(FIXTURE))
    s.add_argument("--per", default=4)
    s.add_argument("--scale", type=float, default=0.75)
    s.add_argument("--placed-only", action="store_true",
                   help="only boards whose verdict, edges or rows moved")
    s.set_defaults(fn=sheets)
    s = sub.add_parser("crop")
    s.add_argument("outdir")
    s.add_argument("--fixture", default=str(FIXTURE))
    s.set_defaults(fn=crop)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
