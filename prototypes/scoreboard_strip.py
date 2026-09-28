r"""The round-history strip as an independent witness of the open Tab scoreboard.

Ported (2026-09-27): `reticle/scoreboard_strip.py` is the reader now, with this
file's rule and constants unchanged; `reticle strip` stores its verdict at
every cached frame and `reticle openings` reconciles it with the slab test.
This file imports the reader from there and stays the experiment record.

    .\.venv\Scripts\python.exe prototypes\scoreboard_strip.py score [--out SAMPLES.jsonl]
    .\.venv\Scripts\python.exe prototypes\scoreboard_strip.py report [--json OUT.json]
    .\.venv\Scripts\python.exe prototypes\scoreboard_strip.py montage OUT.png KIND [N]

`score` reads every hole with its two neighbours, every single-sample run
with its two neighbours, and a seeded sample of 40 open and 60 closed samples
outside any run per session (8139 centre crops on the 19 lineup sessions),
and writes one row per sample with its verdict and evidence to the store's
`notes/scoreboard-strip-samples.jsonl`, disagreements included. `report`
counts them.

Purpose. `reticle.scoreboard.read_scoreboard` opens the board on its two
translucent team slabs. Between the blocks the game draws two lines of round
markers [domain:hud/scoreboard-round-history-strip]; this reads them from the
`center` crop of the `hud` roi cache (frame x 883-1037, y 486-594 at
1920x1080), with no decode and no model, and scores the verdict against the
slab test's stored rows (ledger task `scoreboard-presence`, S1 and S2).

What the crop shows (inspected 2026-09-27, open samples of six sessions).
The ally block's last row fills crop y 0-22 and the enemy block's first row
starts at crop y 83; between them lies a dark translucent band. Its two
marker lines sit at crop y 41 and 65 (frame 527 and 551), one column every
21.7 px on most sessions (22.4 px on `b3b9defb6fd7`, whose columns also sit
at another phase), so the crop holds seven or eight columns. Every column
carries a mark in each line: a dark dot (a 2x2 core near grey 20 on a band
near grey 60), a pale yellow-green dot (3x3, BGR about 150,190,185), or a
round-result icon about 12 px across, teal on the upper (ally) line and red on
the lower (enemy) line. One column may instead hold a thin pale vertical
separator. The white crosshair sits at crop (77, 54), between the lines.

Rule. Find dark dots (a compact spot at least DARK_CONTRAST darker than its
9x9 mean), yellow dots and icons whose centres lie within ROW_TOL of a
marker line. Fit one column lattice (pitch in PITCH_RANGE, phase free) that
puts the most marks in distinct (line, column) cells within ALIGN_TOL. The
strip is `present` when the lattice fills at least MIN_CELLS cells, at least
MIN_PER_LINE on each line and MIN_PAIRED columns on both lines: two lines of
marks in register, 24 px apart, which world texture does not draw. It is
`unreadable` when the crop is missing, or when it is not present and the
band is darker than MIN_BACKGROUND, so a dark dot could not show; it is
`absent` otherwise. Every verdict carries its reason and its counts.

Revision 0.2.0. Version 0.1.0 called a dark band `unreadable` only when it
held no yellow dot or icon. Of the 42 seeded open samples it called absent,
and the open samples beside holes and single-sample runs, 31 carried stored
slab rows at the full board's place (ally block ending near frame y 509,
table starting near x 572); a montage of all 31 showed a real board each
time, 23 of them over a band darker than MIN_BACKGROUND, where the dark dots
vanish and only yellow dots and icons remain. A yellow dot on a black band
is not evidence of absence, so a dark band now reads `unreadable` whatever
else it holds. The other eight: world detail behind the translucent band
along one line (an edge, fire, a character) that joins or drowns its dots
(five), a player card (name, 150, weapon icons) drawn over the strip (two),
and a yellow outline drawn across it (one).

Constants and why:
  ROW_Y = (527, 551), ROW_TOL = 3: the measured lines; the tolerance allows
      a board still settling and the dot's own 2 px size.
  PITCH_RANGE = (20.5, 23.5): brackets both measured pitches (21.7, 22.4).
  ALIGN_TOL = 2.0: a dot centre lands within 0.6 px of its column on clean
      boards; 2 px allows icons, whose centres are less exact.
  DARK_CONTRAST = 15: clean dots are 35-45 grey levels below the band; this
      keeps dots on a board still fading in.
  DARK_MAX_AREA = 12, DARK_MAX_SIDE = 4: a dot's core is 2x2 to 3x3.
  YELLOW_*: brighter than the band by 40 and blue under green and red by 25
      and 20, measured on three yellow dots of two sessions.
  ICON_*: teal (green and blue over red by 50 and 40) or red (red over green
      and blue by 50 and 40), 15-220 px, 6-16 px on a side.
  MIN_CELLS = 6, MIN_PER_LINE = 2, MIN_PAIRED = 2: a full crop holds about
      14 cells; six in register on two lines is far above what chance
      alignment of scattered specks produces, and still reads a board whose
      band is half washed out.
  MIN_BACKGROUND = 24: a dark dot needs DARK_CONTRAST of room above black.

Outcome: see `docs/SCOREBOARD_PRESENCE.md` and the metric row
`scoreboard/strip-witness@all-sessions`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

WITNESS_VERSION = "scoreboard-strip-0.2.0"
# The reader, ported to `reticle.scoreboard_strip` on 2026-09-27 and imported
# here, so the prototype's commands keep running on the one rule. Its 0.2.0
# is the port's scoreboard-strip-0.1.0; the samples file stays valid.
from reticle.scoreboard_strip import (  # noqa: E402,F401
    ALIGN_TOL, BLUR, DARK_CONTRAST, DARK_MAX_AREA, DARK_MAX_SIDE, ICON_AREA, ICON_OVER,
    ICON_OVER2, ICON_SIDE, MIN_BACKGROUND, MIN_CELLS, MIN_PAIRED, MIN_PER_LINE, PITCH_RANGE,
    PITCH_STEP, ROI, ROW_TOL, ROW_Y, YELLOW_AREA, YELLOW_CONTRAST, YELLOW_G_OVER_B,
    YELLOW_MAX_SIDE, YELLOW_R_OVER_B, read_strip)


# --- stored samples -------------------------------------------------------

class Session:
    """One session's centre crops in frame order and the slab test's verdicts."""

    def __init__(self, store: Store, sid: str):
        man = store.read_manifest(sid)
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "hud")
        if cache is None:
            raise SystemExit(f"{sid}: no hud crop cache ({why})")
        self.sid, self.cache = sid, cache
        self.rect = cache.rect_of(ROI)
        k = cache.record["rects"].index(self.rect)
        rows = np.where(cache.rect == k)[0]
        rows = rows[np.argsort(cache.frame_idx[rows], kind="stable")]
        self.rows = rows
        self.frames = cache.frame_idx[rows]
        self.t_ms = cache.t_ms[rows]
        # Per open frame, where the slab test put the board: the ally block's
        # bottom and the table's left edge.
        self.board: dict[int, tuple[int, int]] = {}
        for r in store.read_events("scoreboard", sid):
            if r.get("kind") != "row_observation":
                continue
            f = int(r["frame_idx"])
            bottom, x0 = self.board.get(f, (-1, r["table_x0"]))
            if r["team"] == "ally":
                bottom = max(bottom, int(r["row_y1"]))
            self.board[f] = (bottom, x0)
        self.is_open = np.array([int(f) in self.board for f in self.frames])
        self._fh = None

    def crop(self, i: int) -> np.ndarray | None:
        if self._fh is None:
            self._fh = open(self.cache.blob, "rb")
        j = self.rows[i]
        self._fh.seek(int(self.cache.offset[j]))
        buf = self._fh.read(int(self.cache.length[j]))
        return cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)

    def runs(self):
        """Runs of open samples joined across one-sample holes: (first, last,
        holes), as the `scoreboard/openings` metric counts them."""
        o, n, out, i = self.is_open, len(self.is_open), [], 0
        while i < n:
            if not o[i]:
                i += 1
                continue
            a = j = i
            holes = []
            while True:
                while j + 1 < n and o[j + 1]:
                    j += 1
                if j + 2 < n and not o[j + 1] and o[j + 2]:
                    holes.append(j + 1)
                    j += 2
                    continue
                break
            out.append((a, j, holes))
            i = j + 1
        return out

    def distance_to_open(self) -> np.ndarray:
        n = len(self.is_open)
        opens = np.where(self.is_open)[0]
        if not len(opens):
            return np.full(n, 10 ** 9)
        pos = np.arange(n)
        ins = np.searchsorted(opens, pos)
        lo = opens[np.clip(ins - 1, 0, len(opens) - 1)]
        hi = opens[np.clip(ins, 0, len(opens) - 1)]
        return np.minimum(np.abs(pos - lo), np.abs(pos - hi))


def lineup_sessions(store: Store) -> list[str]:
    return sorted(p.stem for p in (store.root / "lineups").glob("*.json"))


def plan(sess: Session, rng: random.Random, n_open: int, n_closed: int) -> dict[int, set]:
    """Which samples to read and in what roles: every hole, every single-sample
    run with its two neighbours, and a seeded sample of open and of closed
    samples outside any run."""
    roles: dict[int, set] = defaultdict(set)
    runs = sess.runs()
    in_run = np.zeros(len(sess.is_open), bool)
    for a, z, holes in runs:
        in_run[a:z + 1] = True
        for h in holes:
            roles[h].add("hole")
            roles[h - 1].add("hole_before")
            roles[h + 1].add("hole_after")
        if a == z:
            roles[a].add("single")
            for nb, tag in ((a - 1, "single_before"), (a + 1, "single_after")):
                if 0 <= nb < len(sess.is_open):
                    roles[nb].add(tag)
    opens = [int(i) for i in np.where(sess.is_open)[0]]
    closed = [int(i) for i in np.where(~in_run)[0]]
    for i in rng.sample(opens, min(n_open, len(opens))):
        roles[i].add("open")
    for i in rng.sample(closed, min(n_closed, len(closed))):
        roles[i].add("closed_out")
    return roles


def cmd_score(args) -> None:
    store = Store(args.store)
    rng = random.Random(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for sid in lineup_sessions(store):
            sess = Session(store, sid)
            dist = sess.distance_to_open()
            for i, roles in sorted(plan(sess, rng, args.open, args.closed).items()):
                got = read_strip(sess.crop(i), sess.rect)
                fh.write(json.dumps({
                    "session_id": sid, "frame_idx": int(sess.frames[i]),
                    "t_ms": float(sess.t_ms[i]), "slab_open": bool(sess.is_open[i]),
                    "distance_to_open": int(dist[i]), "roles": sorted(roles),
                    "witness_version": WITNESS_VERSION, **got}) + "\n")
                n += 1
            print(f"{sid}: {len(sess.is_open)} samples", flush=True)
    print(f"{n} samples scored -> {out}")


#: Where the slab test puts a fully expanded board at 1920x1080: the median
#: ally-block bottom and table left edge of the open samples the witness reads
#: present. A slab-open sample far from both did not find the board's slabs.
BOARD_ALLY_BOTTOM, BOARD_X0, BOARD_TOL = 509, 572, 6
#: A present verdict with at most this many cells or paired columns sits at
#: the rule's margin; the summary counts them apart.
WEAK_CELLS, WEAK_PAIRED = 8, 3


def summarise_samples(store: Store, rows: list[dict]) -> dict:
    """Every count the write-up quotes, in total and per session."""
    by_key = {(r["session_id"], r["frame_idx"]): r for r in rows}
    present = lambda r: r is not None and r["verdict"] == "present"  # noqa: E731
    per: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        c, v = per[r["session_id"]], r["verdict"]
        roles = set(r["roles"])
        if v == "present":
            side = "slab_open" if r["slab_open"] else "slab_closed"
            c[f"present_{side}"] += 1
            c[f"present_{side}_outline"] += r.get("outline_y") is not None
        groups = [g for g in ("open", "closed_out", "hole", "single") if g in roles]
        if "closed_out" in roles:
            groups.append("far" if r["distance_to_open"] >= 5 else "near")
        # A present verdict at the rule's margin: both false presents found by
        # eye on closed samples far from any open one were of this kind.
        weak = v == "present" and (r["cells"] <= WEAK_CELLS or r["paired"] <= WEAK_PAIRED)
        for g in groups:
            c[f"{g}_{v}"] += 1
            c[f"{g}_present_weak"] += weak
        if "hole" in roles:
            nb = [by_key.get((r["session_id"], r["frame_idx"] + d)) for d in (-30, 30)]
            if v == "absent" and all(present(x) for x in nb):
                c["hole_closed_between_boards"] += 1
        if "single" in roles:
            nb =[by_key.get((r["session_id"], r["frame_idx"] + d)) for d in (-30, 30)]
            ext = any(present(x) for x in nb)
            c["singles_extended"] += ext
            c["singles_board_seen_once"] += (v == "present") and not ext
    geo = Counter()
    pop = Counter()
    for sid in sorted(per):
        sess = Session(store, sid)
        runs = sess.runs()
        in_run = np.zeros(len(sess.is_open), bool)
        for a, z, _ in runs:
            in_run[a:z + 1] = True
        dist = sess.distance_to_open()
        pop["closed_out"] += int((~in_run).sum())
        pop["far"] += int((~in_run & (dist >= 5)).sum())
        pop["near"] += int((~in_run & (dist < 5)).sum())
        for r in rows:
            if r["session_id"] != sid or not r["slab_open"]:
                continue
            bottom, x0 = sess.board[r["frame_idx"]]
            at = abs(bottom - BOARD_ALLY_BOTTOM) <= BOARD_TOL and abs(x0 - BOARD_X0) <= BOARD_TOL
            geo[f"slab_open_{r['verdict']}"] += 1
            geo[f"slab_open_{r['verdict']}_at_board"] += at
    tot = Counter()
    for c in per.values():
        tot.update(c)
    frac = lambda a, b: round(a / b, 4) if b else None  # noqa: E731
    n = {k: sum(tot[f"{k}_{v}"] for v in ("present", "absent", "unreadable"))
         for k in ("open", "closed_out", "far", "near", "hole", "single")}
    out = {"sessions": len(per), "samples_scored": len(rows)}
    for k in n:
        out[f"{k}_n"] = n[k]
        for v in ("present", "absent", "unreadable"):
            out[f"{k}_{v}"] = tot[f"{k}_{v}"]
        out[f"{k}_present_frac"] = frac(tot[f"{k}_present"], n[k])
        out[f"{k}_present_weak"] = tot[f"{k}_present_weak"]
    out["far_present_frac_of_readable"] = frac(tot["far_present"], n["far"] - tot["far_unreadable"])
    out["hole_closed_between_boards"] = tot["hole_closed_between_boards"]
    for side in ("slab_open", "slab_closed"):
        out[f"present_{side}"] = tot[f"present_{side}"]
        out[f"present_{side}_outline"] = tot[f"present_{side}_outline"]
    out["singles_extended"] = tot["singles_extended"]
    out["singles_extended_frac"] = frac(tot["singles_extended"], n["single"])
    out["singles_board_seen_once"] = tot["singles_board_seen_once"]
    out["singles_board_seen_once_frac"] = frac(tot["singles_board_seen_once"], n["single"])
    for k, v in sorted(geo.items()):
        out[k] = v
    out["closed_out_population"] = pop["closed_out"]
    out["far_population"] = pop["far"]
    out["near_population"] = pop["near"]
    # An extrapolation from the seeded sample, not a count, and without the
    # margin presents, so it leans low.
    out["est_board_samples_slab_closed"] = int(round(
        pop["far"] * (tot["far_present"] - tot["far_present_weak"]) / max(1, n["far"])
        + pop["near"] * (tot["near_present"] - tot["near_present_weak"]) / max(1, n["near"])))
    out["per_session"] = {s: dict(sorted(c.items())) for s, c in sorted(per.items())}
    return out


def cmd_report(args) -> None:
    store = Store(args.store)
    rows = [json.loads(l) for l in Path(args.samples).read_text(encoding="utf-8").splitlines() if l]
    versions = {r["witness_version"] for r in rows}
    if versions != {WITNESS_VERSION}:
        raise SystemExit(f"samples scored by {sorted(versions)}, not {WITNESS_VERSION}: rescore")
    out = summarise_samples(store, rows)
    for k, v in out.items():
        if k != "per_session":
            print(f"{k} = {v}")
    for s, c in out["per_session"].items():
        g = lambda k: "/".join(str(c.get(f"{k}_{v}", 0)) for v in ("present", "absent", "unreadable"))  # noqa: E731
        print(f"{s} open {g('open')} far {g('far')} near {g('near')} hole {g('hole')} "
              f"single {g('single')} extended {c.get('singles_extended', 0)} "
              f"seen_once {c.get('singles_board_seen_once', 0)}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")


def cmd_montage(args) -> None:
    """Crops from a scored samples file, `KIND` a role or `open_absent`,
    `closed_present` or `hole_absent`, labelled with the verdict."""
    store = Store(args.store)
    rows = [json.loads(l) for l in Path(args.samples).read_text(encoding="utf-8").splitlines() if l]
    want = {
        "open_absent": lambda r: "open" in r["roles"] and r["verdict"] != "present",
        "closed_present": lambda r: "closed_out" in r["roles"] and r["verdict"] == "present",
        "hole_absent": lambda r: "hole" in r["roles"] and r["verdict"] != "present",
        "hole_present": lambda r: "hole" in r["roles"] and r["verdict"] == "present",
        "far_present": lambda r: ("closed_out" in r["roles"] and r["distance_to_open"] >= 5
                                  and r["verdict"] == "present"),
        "single_absent": lambda r: "single" in r["roles"] and r["verdict"] != "present",
        "neighbour_present": lambda r: (("single_before" in r["roles"] or "single_after" in r["roles"])
                                        and r["verdict"] == "present"),
    }.get(args.kind, lambda r: args.kind in r["roles"])
    pick = [r for r in rows if want(r)]
    random.Random(args.seed).shuffle(pick)
    pick = pick[:args.n]
    tiles, sessions = [], {}
    for r in pick:
        sess = sessions.get(r["session_id"]) or Session(store, r["session_id"])
        sessions[r["session_id"]] = sess
        i = int(np.searchsorted(sess.frames, r["frame_idx"]))
        crop = sess.crop(i)
        big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        lab = np.zeros((34, big.shape[1], 3), np.uint8)
        cv2.putText(lab, f"{r['session_id'][:6]} {r['t_ms'] / 1000:.1f}s slab={'O' if r['slab_open'] else 'C'}",
                    (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        cv2.putText(lab, f"{r['verdict'][:4]} c{r.get('cells')} p{r.get('paired')} {r.get('reason') or ''}"[:44],
                    (3, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        tiles.append(cv2.copyMakeBorder(np.vstack([lab, big]), 2, 2, 2, 2,
                                        cv2.BORDER_CONSTANT, value=(0, 200, 255)))
    if not tiles:
        raise SystemExit(f"no samples of kind {args.kind}")
    per = 4
    while len(tiles) % per:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[j:j + per]) for j in range(0, len(tiles), per)])
    cv2.imwrite(args.out, grid)
    print(f"{len(pick)} crops -> {args.out}")


def _idle() -> None:
    """Run at Idle priority on Windows; the CPU is shared with longer jobs."""
    if os.name == "nt":
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)
    cv2.setNumThreads(1)


def main(argv=None) -> None:
    _idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--out", default=str(DEFAULT_STORE / "notes" / "scoreboard-strip-samples.jsonl"))
    s.add_argument("--open", type=int, default=40, help="open samples per session")
    s.add_argument("--closed", type=int, default=60, help="closed samples outside runs per session")
    s.add_argument("--seed", type=int, default=20260927)
    s.set_defaults(fn=cmd_score)
    rp = sub.add_parser("report")
    rp.add_argument("--samples", default=str(DEFAULT_STORE / "notes" / "scoreboard-strip-samples.jsonl"))
    rp.add_argument("--json", default=None, help="also write the summary here")
    rp.set_defaults(fn=cmd_report)
    m = sub.add_parser("montage")
    m.add_argument("out")
    m.add_argument("kind")
    m.add_argument("n", type=int, nargs="?", default=16)
    m.add_argument("--samples", default=str(DEFAULT_STORE / "notes" / "scoreboard-strip-samples.jsonl"))
    m.add_argument("--seed", type=int, default=7)
    m.set_defaults(fn=cmd_montage)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
