r"""Round outcomes read from the Tab scoreboard's history strip, checked against
the stored scoreline.

    .\.venv\Scripts\python.exe prototypes\scoreboard_round_marks.py read [--out SAMPLES.jsonl]
    .\.venv\Scripts\python.exe prototypes\scoreboard_round_marks.py stats
    .\.venv\Scripts\python.exe prototypes\scoreboard_round_marks.py report [--json OUT.json] [--record]
    .\.venv\Scripts\python.exe prototypes\scoreboard_round_marks.py montage OUT.png KIND [N] [--report OUT.json]

`read` takes the first sample the slab test reads open in each 10 s of each
lineup session, reads its `center` crop from the `hud` roi cache (frame x
883-1037, y 486-594 at 1920x1080; no decode, no model), fits the column
lattice of `prototypes/scoreboard_strip.py`, and classifies every visible
column on each marker line. It writes one row per sample to the store's
`notes/scoreboard-round-marks-samples.jsonl`: the strip verdict, the lattice
pitch and phase (so each column's frame x is known), and per column its
index, frame x, the class on each line, the `current` flag and the counts
behind them. The rows carry no score: the reader never sees the rounds.
`stats` prints the per-cell count distributions the constants rest on.

`report` joins the rows with the rounds `reticle.rounds.build_rounds` derives
from the stored scoreline and scores the ledger's predictions M1-M5 (task
`scoreboard-round-marks`). It fits the column-to-round offsets (one before
the half, one after) per session twice: on the icon columns alone, as M1
states, and on every visible column, where a column showing no icon before
its round is decided counts too; it reports every tied pair. Every other
count is taken under the predicted offsets, over all samples and again over
the samples outside a post-round period (`live_`). `--record` writes the
metric row `scoreboard/round-marks@all-sessions`; `montage` draws samples or
the report's disagreements.

What the crop shows (inspected 2026-09-27, 48 crops from ten sessions, then
measured). The columns in view are match rounds 11 and 12, a separator
column, then rounds 13 to 17 [domain:hud/scoreboard-round-history-strip]. A
played column carries the winner's icon, teal on the upper (ally) line or
red on the lower (enemy) line, in one of several shapes (a crossed
square, a pincer, an hourglass), and a black dot on the loser's line; an
unplayed column carries a black dot on both. The separator is two thin pale
ticks, from the ally block to the upper line and from the lower line to the
enemy block, with no dot. Pale yellow triangles above and below one column
mark the current round. Each line carries one yellow dot, on the column of
round 13 plus the other team's total. The strip records a round when the
next round begins, not when the scoreline increments. The board opens only
while the player holds Tab [domain:hud/scoreboard-tab-hold].

Rule, per visible column (centre inside the crop) and per line, first match:
  `ally_icon` / `enemy_icon`: at least ICON_MIN_PX teal (or red) pixels, by
      the strip prototype's colour rule, in a CELL_HALF window on the line,
      and at most RING_MAX_FRAC as many in the ring out to RING_HALF, so a
      teal wall or a coloured end-screen block is not an icon; both colours
      at once is `other`;
  `separator`: a one- or two-pixel vertical line at least SEP_CONTRAST
      brighter than the band on either side (median over the SEP_ROWS of the
      two ticks, and at least SEP_MIN_FRAC of those rows); it outranks the
      dot tests because its bright ticks make the dark-dot test read a
      shadow beside them and the lower tick, one row under the line, passes
      the yellow test (found from the class counts per column, which put
      yellow on column 2's lower line 305 times, not from the rounds);
  `yellow`: at least YELLOW_MIN_PX pixels within DOT_HALF + 1 of the line
      that are YELLOW_CONTRAST brighter than their 9x9 mean with blue at
      least YELLOW_TINT under both red and green (a warm bright spot);
  `black`: a spot DARK_CONTRAST darker than its 9x9 mean within DOT_HALF;
  `other`: at least ICON_MIN_PX teal or red pixels that fail the ring test;
  `unreadable`: none of the above over a band darker than MIN_BACKGROUND,
      where a black dot cannot show;
  `empty`: nothing found.
A sample whose strip the witness does not read present gets no columns.
A column carries `current` when a triangle window above the upper line or
below the lower one holds at least TRI_MIN_PX yellow pixels and its flanks
at most a quarter as many: the local player's yellow row outline runs the
full width just above the strip.

Column index. Column 0 is the lattice column nearest frame x COL0_X, and
column c lies at phase + c * pitch. COL0_X sits between the two measured
phases (884.0 on the 21.6 px sessions, 892.4 on `b3b9defb6fd7` at 22.4 px),
so a phase jitter under 4 px cannot move an index.

Constants and why (counts from `stats` on the full read; none from rounds):
  COL0_X = 888: see above.
  CELL_HALF = 7: a 15 px window around an icon about 12 px across
      (`docs/SCOREBOARD_PRESENCE.md`); the lines lie 24 px apart (`ROW_Y`),
      so the upper and lower windows never meet.
  RING_HALF = 11: the ring ends short of the neighbouring icon, whose edge
      lies about 15 px from the column centre at a 21.6 px pitch.
  ICON_MIN_PX = 12: of the line cells read, [metric:scoreboard/round-marks@all-sessions#px_colour_12_plus=5143] hold
      at least 12 teal or red pixels and only [metric:scoreboard/round-marks@all-sessions#px_colour_1_to_11=104] hold
      1 to 11; the rest hold none.
  RING_MAX_FRAC = 0.5: a lone icon's ring is empty, a coloured block's full.
  DOT_HALF = 2: the tolerance for a dot's offset from the fitted lattice.
  YELLOW_MIN_PX = 3: the strip prototype's smallest yellow blob.
  YELLOW_TINT = 10: the strip prototype asks green over blue by 25 and red
      over blue by 20. Two pale dots in the inspection zooms read 183,178,164
      and 175,190,164 RGB and each failed one of those tests; 10 passes both,
      and the black dots and grey world specks carry no tint.
  SEP_CONTRAST = 12, SEP_MIN_FRAC = 0.7, SEP_ROWS: the ticks run from 16
      rows above the upper line to 4 above it and from 4 to 15 rows below the
      lower line; [metric:scoreboard/round-marks@all-sessions#px_sep_frac_high=1922] columns hold a line on 0.9 of those
      rows or more and [metric:scoreboard/round-marks@all-sessions#px_sep_frac_mid=269] on 0.4 to 0.9.
  TRI_MIN_PX = 4, TRI_ROWS, TRI_HALF, TRI_FLANK: the windows cover rows 12
      to 17 above the upper line and 11 to 17 below the lower one, 11 px
      wide, where the triangles sit in the inspection montages; the flanks
      run out to 10 px either side.

Outcome: see `docs/SCOREBOARD_ROUND_MARKS.md` and the metric row
`scoreboard/round-marks@all-sessions`.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prototypes import scoreboard_strip as strip  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

MARKS_VERSION = "scoreboard-round-marks-0.1.0"
SAMPLES = DEFAULT_STORE / "notes" / "scoreboard-round-marks-samples.jsonl"
SAMPLE_EVERY_MS = 10_000

COL0_X = 888.0
CELL_HALF, RING_HALF = 7, 11
ICON_MIN_PX = 12
RING_MAX_FRAC = 0.5
DOT_HALF = 2
YELLOW_MIN_PX = 3
YELLOW_TINT = 10
SEP_CONTRAST = 12
SEP_MIN_FRAC = 0.7
SEP_ROWS = ((-16, -4), (4, 15))
TRI_MIN_PX = 4
TRI_ROWS = ((-17, -12), (11, 17))
TRI_HALF, TRI_FLANK = 5, 10

CLASSES = ("black", "ally_icon", "enemy_icon", "yellow", "separator", "other", "empty",
           "unreadable")


def _masks(crop: np.ndarray) -> dict:
    """The strip prototype's colour rules over the whole crop."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    loc = cv2.blur(g, (strip.BLUR, strip.BLUR))
    b, gg, r = (crop[:, :, k].astype(np.int16) for k in range(3))
    return {
        "g": g,
        "dark": loc - g,
        "yellow": (((g - loc) >= strip.YELLOW_CONTRAST) & ((gg - b) >= YELLOW_TINT)
                   & ((r - b) >= YELLOW_TINT)),
        "teal": ((gg - r) >= strip.ICON_OVER) & ((b - r) >= strip.ICON_OVER2),
        "red": ((r - gg) >= strip.ICON_OVER) & ((r - b) >= strip.ICON_OVER2),
    }


def _box(a: np.ndarray, x: float, y: float, half: int) -> np.ndarray:
    h, w = a.shape[:2]
    x0, x1 = max(0, int(round(x)) - half), min(w, int(round(x)) + half + 1)
    y0, y1 = max(0, int(round(y)) - half), min(h, int(round(y)) + half + 1)
    return a[y0:y1, x0:x1]


def _separator(g: np.ndarray, xc: float, rows: tuple[int, int]) -> tuple[float, float]:
    """The best vertical line within DOT_HALF + 1 of `xc`: its median contrast
    over the rows between the ally block and the upper line and between the
    lower line and the enemy block (the separator's two ticks), and the
    fraction of those rows where it is at least SEP_CONTRAST."""
    h, w = g.shape
    ys = [y for ry, (a, b) in zip(rows, SEP_ROWS) for y in range(max(0, ry + a), min(h, ry + b + 1))]
    best = (0.0, 0.0)
    for x in range(int(round(xc)) - DOT_HALF - 1, int(round(xc)) + DOT_HALF + 2):
        if x - 3 < 0 or x + 4 >= w:
            continue
        line = np.maximum(g[ys, x], g[ys, x + 1])  # a line may straddle two columns
        side = np.maximum(g[ys, x - 3], g[ys, x + 4])
        c = line - side
        cand = (float(np.median(c)), float((c >= SEP_CONTRAST).mean()))
        if cand > best:
            best = cand
    return best


def _cell(m: dict, xc: float, ry: int, background: float) -> dict:
    """One line of one column: the class and the counts it rests on."""
    nt = int(_box(m["teal"], xc, ry, CELL_HALF).sum())
    nr = int(_box(m["red"], xc, ry, CELL_HALF).sum())
    rt = int(_box(m["teal"], xc, ry, RING_HALF).sum()) - nt
    rr = int(_box(m["red"], xc, ry, RING_HALF).sum()) - nr
    ny = int(_box(m["yellow"], xc, ry, DOT_HALF + 1).sum())
    dk = float(_box(m["dark"], xc, ry, DOT_HALF).max())
    teal = nt >= ICON_MIN_PX and rt <= RING_MAX_FRAC * nt
    red = nr >= ICON_MIN_PX and rr <= RING_MAX_FRAC * nr
    if teal and red:
        cls = "other"
    elif teal:
        cls = "ally_icon"
    elif red:
        cls = "enemy_icon"
    elif ny >= YELLOW_MIN_PX:
        cls = "yellow"
    elif dk >= strip.DARK_CONTRAST:
        cls = "black"
    elif nt >= ICON_MIN_PX or nr >= ICON_MIN_PX:
        cls = "other"
    elif background < strip.MIN_BACKGROUND:
        cls = "unreadable"
    else:
        cls = "empty"
    return {"cls": cls, "teal": nt, "red": nr, "ring_teal": rt, "ring_red": rr,
            "yellow": ny, "dark": round(dk, 1)}


def read_marks(crop: np.ndarray | None, rect) -> dict:
    """The strip verdict for one centre crop and, where the strip is present,
    every visible column's class on each line, with its frame x."""
    got = strip.read_strip(crop, rect)
    ev = {k: got.get(k) for k in ("verdict", "reason", "background", "cells", "pitch", "phase")}
    if got["verdict"] != "present":
        return {**ev, "columns": []}
    x0, y0 = int(rect[0]), int(rect[1])
    rows = tuple(y - y0 for y in strip.ROW_Y)
    pitch, phase = float(got["pitch"]), float(got["phase"])
    c0 = round((COL0_X - phase) / pitch)
    m = _masks(crop)
    h, w = crop.shape[:2]
    cols = []
    for c in range(-3, 12):
        x = phase + (c0 + c) * pitch
        xc = x - x0
        if not 0 <= xc <= w - 1:
            continue
        up = _cell(m, xc, rows[0], got["background"])
        lo = _cell(m, xc, rows[1], got["background"])
        sep, sep_frac = _separator(m["g"], xc, rows)
        is_sep = sep >= SEP_CONTRAST and sep_frac >= SEP_MIN_FRAC
        # The separator's bright ticks raise the 9x9 mean beside them, so the
        # dark-dot test reads their shadow as a dot, and the lower tick,
        # warmed by the enemy block behind it, starts one row under the line
        # and passes the yellow test; the separator carries no dot, so it
        # outranks both (inspected on 12 crops of 12 sessions).
        for cell in (up, lo):
            if is_sep and cell["cls"] in ("yellow", "black", "empty", "unreadable"):
                cell["cls"] = "separator"
        # Triangle pixels in the column, and in its flanks: the local
        # player's yellow row outline runs the full width just above.
        xi = int(round(xc))
        tri, flank = [], []
        for ry, (a, b) in zip(rows, TRI_ROWS):
            band = m["yellow"][max(0, ry + a):ry + b + 1]
            tri.append(int(band[:, max(0, xi - TRI_HALF):xi + TRI_HALF + 1].sum()))
            flank.append(int(band[:, max(0, xi - TRI_FLANK):max(0, xi - TRI_HALF - 1)].sum()
                             + band[:, xi + TRI_HALF + 2:xi + TRI_FLANK + 1].sum()))
        cols.append({"c": c, "x": round(x, 1), "upper": up["cls"], "lower": lo["cls"],
                     "current": any(t >= TRI_MIN_PX and f <= t // 4 for t, f in zip(tri, flank)),
                     "tri": tri, "tri_flank": flank,
                     "sep": round(sep, 1), "sep_frac": round(sep_frac, 2),
                     "u": {k: v for k, v in up.items() if k != "cls"},
                     "l": {k: v for k, v in lo.items() if k != "cls"}})
    return {**ev, "columns": cols}


def column_team(col: dict) -> str | None:
    """The team a column's icons name: `ally`, `enemy`, `both`, or None."""
    icons = {col["upper"], col["lower"]}
    a, e = "ally_icon" in icons, "enemy_icon" in icons
    return "both" if a and e else "ally" if a else "enemy" if e else None


# --- sampling ---------------------------------------------------------------

def pick(sess: strip.Session) -> list[int]:
    """The first slab-open sample in each SAMPLE_EVERY_MS of the session."""
    seen, out = set(), []
    for i in np.where(sess.is_open)[0]:
        b = int(sess.t_ms[i] // SAMPLE_EVERY_MS)
        if b not in seen:
            seen.add(b)
            out.append(int(i))
    return out


def cmd_read(args) -> None:
    store = Store(args.store)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for sid in strip.lineup_sessions(store):
            sess = strip.Session(store, sid)
            idx = pick(sess)
            if args.limit:  # evenly spaced over the session, for a trial
                idx = idx[::max(1, len(idx) // args.limit)][:args.limit]
            for i in idx:
                got = read_marks(sess.crop(i), sess.rect)
                fh.write(json.dumps({
                    "session_id": sid, "frame_idx": int(sess.frames[i]), "t_ms": float(sess.t_ms[i]),
                    "marks_version": MARKS_VERSION, "witness_version": strip.WITNESS_VERSION,
                    **got}) + "\n")
                n += 1
            print(f"{sid}: {len(idx)} samples", flush=True)
    print(f"{n} samples -> {out}")


def cmd_stats(args) -> None:
    """Distributions of the per-cell counts, for choosing the constants from
    the pixels alone."""
    rows = [json.loads(l) for l in Path(args.samples).read_text(encoding="utf-8").splitlines() if l]
    feats = defaultdict(list)
    for r in rows:
        for col in r["columns"]:
            for side in ("u", "l"):
                for k, v in col[side].items():
                    feats[f"{side}_{k}"].append(v)
            feats["sep"].append(col["sep"])
            feats["sep_frac"].append(col["sep_frac"])
            feats["tri_max"].append(max(col["tri"]))
    edges = {"teal": [0, 1, 4, 8, 12, 16, 20, 30, 40, 60, 80, 120, 170, 250],
             "red": [0, 1, 4, 8, 12, 16, 20, 30, 40, 60, 80, 120, 170, 250],
             "yellow": [0, 1, 2, 3, 4, 6, 10, 20, 50], "dark": [-50, 0, 5, 10, 15, 20, 30, 40, 60, 100],
             "sep": [-50, 0, 4, 8, 12, 16, 20, 30, 60, 200], "sep_frac": [0, .2, .4, .6, .7, .8, .9, 1.01],
             "tri_max": [0, 1, 2, 4, 6, 10, 20, 50, 200]}
    for k, v in sorted(feats.items()):
        base = k.split("_", 1)[1] if k[:2] in ("u_", "l_") else k
        base = base.replace("ring_", "")
        e = edges.get(base, [0, 1, 4, 8, 16, 32, 64, 128, 256])
        h, _ = np.histogram(np.clip(v, e[0], e[-1] - 1e-6), bins=e)
        print(f"{k:14s} n={len(v)} " + " ".join(f"[{a},{b}):{c}" for a, b, c in zip(e, e[1:], h)))
    cls = Counter()
    for r in rows:
        for col in r["columns"]:
            cls[(col["c"], "u", col["upper"])] += 1
            cls[(col["c"], "l", col["lower"])] += 1
    for c in sorted({k[0] for k in cls}):
        for side in ("u", "l"):
            print(c, side, {k[2]: v for k, v in cls.items() if k[0] == c and k[1] == side})


# --- scoring against the stored scoreline -----------------------------------

class Rounds:
    """One session's rounds from `reticle.rounds.build_rounds` over the stored
    HUD reads, keyed by match round (the score before it, plus one)."""

    def __init__(self, store: Store, sid: str):
        import pyarrow.parquet as pq
        from reticle.rounds import build_rounds
        man = store.read_manifest(sid)
        date = (man.get("ingested_at") or "")[:10]
        rs = build_rounds(pq.read_table(store.hud_path(sid, date)), None)
        self.rounds = rs
        self.winner = {r["left_before"] + r["right_before"] + 1: ("ally" if r["won"] else "enemy")
                       for r in rs}
        self.ends = np.array([r["t_end_ms"] for r in rs])
        self.first_before = (rs[0]["left_before"], rs[0]["right_before"]) if rs else (0, 0)

    def state(self, t: float) -> dict:
        """Rounds decided, each team's total and the nearest stored round end
        at media time `t`, and whether `t` lies in a post-round period (from
        a round's end to the next round's start, the buy-phase snap
        [domain:rounds/post-round-period]) or after the last stored end."""
        done = [i for i, r in enumerate(self.rounds) if r["t_end_ms"] <= t]
        post, nxt = False, None
        if done:
            k = done[-1]
            r = self.rounds[k]
            ally = r["score_us"] + int(r["won"])
            enemy = r["score_them"] + int(not r["won"])
            if k + 1 < len(self.rounds):
                nxt = self.rounds[k + 1]
                post = t < nxt["t_start_ms"]
        else:
            ally, enemy = self.first_before
        d = np.abs(self.ends - t) if len(self.ends) else np.array([1e12])
        after = bool(len(self.ends) and t > self.ends[-1])
        return {"decided": ally + enemy, "ally": ally, "enemy": enemy,
                "near_end_ms": float(d.min()), "post_round": bool(post), "after_last": after,
                "live": not post and not after,
                "to_next_start_ms": None if nxt is None or nxt["start_source"] != "clock_reset"
                else float(t - nxt["t_start_ms"])}


def round_of(c: int, o1: int, o2: int) -> int | None:
    """Column c's round under offsets (o1 before the half, o2 after it), or
    None for a column between the halves."""
    if c + o1 <= 12:
        return c + o1
    if c + o2 >= 13:
        return c + o2
    return None


#: The offsets M2 predicts: column c holds round c + 11 before the half and
#: c + 10 after it; column 2 is the separator.
PRED_O1, PRED_O2 = 11, 10
#: A sample this close to a stored round end may show the board a moment
#: before or after the score changed.
NEAR_END_MS = 2000


def expected_team(c: int, o1: int, o2: int, st: dict, winner: dict) -> str | None:
    """What column c should show under offsets (o1, o2) in state `st`: the
    stored winner of its round once decided, None (no icon) before that or
    between the halves or off the strip, `unknown` for a decided round the
    store lacks."""
    r = round_of(c, o1, o2)
    if r is None or r < 1 or r > st["decided"]:
        return None
    return winner.get(r, "unknown")


def fit_offsets(obs: list[tuple[int, str | None, dict, dict]], icons_only: bool):
    """Every (o1, o2) with the most agreement over `obs` = (column, team read,
    state, winner-by-round). `icons_only` scores only columns read as an
    icon, as M1 states; otherwise every visible column, so a column that
    shows no icon before its round is decided counts too. Returns the best
    (agree, scored) and the offsets that tie at it."""
    scores = {}
    for o1 in range(-4, 26):
        for o2 in range(o1 - 3, o1 + 1):
            agree = n = 0
            for c, team, st, win in obs:
                if icons_only and team is None:
                    continue
                exp = expected_team(c, o1, o2, st, win)
                if exp == "unknown":
                    continue
                n += 1
                agree += team == exp
            scores[(o1, o2)] = (agree, n)
    best = max(scores.values(), key=lambda s: (s[0] / max(1, s[1]), s[0]))
    ties = sorted(k for k, v in scores.items() if v == best)
    return best, ties


def summarise(store: Store, rows: list[dict]) -> tuple[dict, list[dict]]:
    """Every number the write-up quotes, and the disagreeing cells."""
    by_sid = defaultdict(list)
    for r in rows:
        by_sid[r["session_id"]].append(r)
    tot = Counter()
    per = {}
    bad: list[dict] = []
    cls_by_c = Counter()
    for sid, rs in sorted(by_sid.items()):
        rd = Rounds(store, sid)
        c = Counter()
        c["samples"] = len(rs)
        obs = []
        states = {}
        for r in rs:
            st = rd.state(r["t_ms"])
            states[r["frame_idx"]] = st
            c[f"verdict_{r['verdict']}"] += 1
            if r["verdict"] == "present":
                obs += [(col["c"], column_team(col), st, rd.winner) for col in r["columns"]]
        (ia, inn), iti = fit_offsets(obs, icons_only=True)
        (fa, fn), fti = fit_offsets(obs, icons_only=False)
        fits = {"icons_best": [ia, inn], "icons_ties": iti, "full_best": [fa, fn], "full_ties": fti}
        c["icons_fit_agree"], c["icons_fit_n"] = ia, inn
        c["full_fit_agree"], c["full_fit_n"] = fa, fn
        c["icons_fit_pred_among_ties"] = int((PRED_O1, PRED_O2) in iti)
        c["full_fit_pred_unique"] = int(fti == [(PRED_O1, PRED_O2)])
        # Everything below under the predicted offsets.
        for r in rs:
            if r["verdict"] != "present":
                continue
            st = states[r["frame_idx"]]
            near = st["near_end_ms"] <= NEAR_END_MS

            def add(key, v=1, _live=st["live"]):
                c[key] += int(v)
                if _live:
                    c["live_" + key] += int(v)
            add("present_samples")
            cur = st["decided"] + 1
            by_round = {}
            for col in r["columns"]:
                cls_by_c[(col["c"], "upper", col["upper"])] += 1
                cls_by_c[(col["c"], "lower", col["lower"])] += 1
                for cell in (col["u"], col["l"]):
                    n_col = max(cell["teal"], cell["red"])
                    c["px_cells"] += 1
                    c["px_colour_1_to_11"] += 1 <= n_col < ICON_MIN_PX
                    c["px_colour_12_plus"] += n_col >= ICON_MIN_PX
                c["px_cols"] += 1
                c["px_sep_frac_mid"] += 0.4 <= col["sep_frac"] < 0.9
                c["px_sep_frac_high"] += col["sep_frac"] >= 0.9
                rnd = round_of(col["c"], PRED_O1, PRED_O2)
                by_round[rnd] = col
                team = column_team(col)
                rec = {"session_id": sid, "frame_idx": r["frame_idx"], "t_ms": r["t_ms"], "c": col["c"],
                       "round": rnd, "decided": st["decided"], "ally": st["ally"], "enemy": st["enemy"],
                       "upper": col["upper"], "lower": col["lower"], "near_end": near,
                       "near_end_ms": st["near_end_ms"], "after_last": st["after_last"]}
                if rnd is None:
                    add("sep_cols")
                    add("sep_cols_separator", col["upper"] == "separator" and col["lower"] == "separator")
                    add("sep_cols_icon", team is not None)
                    continue
                exp = expected_team(col["c"], PRED_O1, PRED_O2, st, rd.winner)
                # M1: icon columns
                if team is not None:
                    v = ("icon_unplayed" if exp is None else "unknown_round" if exp == "unknown"
                         else "agree" if team == exp else "disagree")
                    add(f"pred_icon_{v}")
                    add(f"pred_icon_{v}_near", near)
                    if v in ("icon_unplayed", "disagree"):
                        bad.append({**rec, "why": v, "stored": exp})
                # recall over played rounds in view, and the loser's line
                if exp in ("ally", "enemy"):
                    add("played_cols")
                    add("played_cols_icon", team is not None)
                    add("played_cols_icon_right", team == exp)
                    if team is None:
                        add("played_no_icon_near", near)
                        bad.append({**rec, "why": "no_icon_played", "stored": exp})
                    loser = col["lower"] if exp == "ally" else col["upper"]
                    add(f"loser_line_{loser}")
                # M5: unplayed columns
                if exp is None:
                    add("unplayed_cols")
                    add("unplayed_cols_icon", team is not None)
                    add(f"unplayed_upper_{col['upper']}")
                    add(f"unplayed_lower_{col['lower']}")
                    if not near:
                        add("unplayed_cols_far")
                        add("unplayed_cols_far_icon", team is not None)
                # M3: yellow cells
                for line, cls in (("upper", col["upper"]), ("lower", col["lower"])):
                    if cls != "yellow":
                        continue
                    other = st["enemy"] if line == "upper" else st["ally"]
                    own = st["ally"] if line == "upper" else st["enemy"]
                    at_other, at_own = rnd == 13 + other, rnd == 13 + own
                    add("yellow_cells")
                    add(f"yellow_cells_{line}")
                    add("yellow_at_13_plus_other", at_other)
                    add(f"yellow_at_13_plus_other_{line}", at_other)
                    add("yellow_at_13_plus_own", at_own)
                    add("yellow_only_13_plus_other", at_other and not at_own)
                    add("yellow_only_13_plus_own", at_own and not at_other)
                    add("yellow_at_current", rnd == cur)
                    add("yellow_at_other_total_col", rnd == other)
                    add("yellow_at_own_total_col", rnd == own)
                    if not at_other:
                        add("yellow_off_near", near)
                        bad.append({**rec, "why": f"yellow_{line}_off", "stored": 13 + other})
                # M4: triangles
                if col["current"]:
                    add("current_cols")
                    add("current_at_current", rnd == cur)
                    add("current_at_next", rnd == cur + 1)
                    if rnd != cur:
                        add("current_off_near", near)
                        bad.append({**rec, "why": "triangle_off", "stored": cur})
            # When the strip records the round the scoreline last decided,
            # against the next round's stored start (its clock reset).
            rel = st["to_next_start_ms"]
            if rel is not None and st["decided"] in by_round and st["decided"] in rd.winner:
                b = ("before_3s" if rel < -3000 else "last_3s" if rel < 0 else "after")
                col = by_round[st["decided"]]
                c[f"decided_col_{b}"] += 1
                c[f"decided_col_{b}_icon"] += column_team(col) == rd.winner[st["decided"]]
                c[f"decided_col_{b}_triangles"] += col["current"]
            # the yellow dot and triangles, where the rule puts them in view
            for line, other in (("upper", st["enemy"]), ("lower", st["ally"])):
                if 13 + other in by_round:
                    add("yellow_expected_in_view")
                    add("yellow_expected_read", by_round[13 + other][line] == "yellow")
            if cur in by_round:
                add("current_in_view")
                add("current_in_view_read", by_round[cur]["current"])
        per[sid] = (c, fits)
        tot.update(c)
    frac = lambda a, b: round(a / b, 4) if b else None  # noqa: E731
    out: dict = {"sessions": len(by_sid), "samples": len(rows)}
    for k in sorted(tot):
        out[k] = tot[k]
    for pre in ("", "live_"):
        g = lambda k: tot[pre + k]  # noqa: E731
        n_icon = g("pred_icon_agree") + g("pred_icon_disagree") + g("pred_icon_icon_unplayed")
        out[pre + "pred_icon_n"] = n_icon
        out[pre + "pred_icon_n_with_sep"] = n_icon + g("sep_cols_icon")
        out[pre + "pred_agree_frac"] = frac(g("pred_icon_agree"), n_icon)
        out[pre + "pred_agree_frac_with_sep"] = frac(g("pred_icon_agree"), n_icon + g("sep_cols_icon"))
        out[pre + "played_icon_frac"] = frac(g("played_cols_icon"), g("played_cols"))
        out[pre + "played_icon_right_frac"] = frac(g("played_cols_icon_right"), g("played_cols"))
        out[pre + "unplayed_far_icon_frac"] = frac(g("unplayed_cols_far_icon"), g("unplayed_cols_far"))
        out[pre + "unplayed_icon_frac"] = frac(g("unplayed_cols_icon"), g("unplayed_cols"))
        out[pre + "sep_separator_frac"] = frac(g("sep_cols_separator"), g("sep_cols"))
        out[pre + "yellow_13_plus_other_frac"] = frac(g("yellow_at_13_plus_other"), g("yellow_cells"))
        out[pre + "yellow_expected_read_frac"] = frac(g("yellow_expected_read"), g("yellow_expected_in_view"))
        out[pre + "current_at_current_frac"] = frac(g("current_at_current"), g("current_cols"))
        out[pre + "current_in_view_read_frac"] = frac(g("current_in_view_read"), g("current_in_view"))
    per_frac = [frac(c["pred_icon_agree"], c["pred_icon_agree"] + c["pred_icon_disagree"]
                     + c["pred_icon_icon_unplayed"] + c["sep_cols_icon"])
                for c, _ in per.values()
                if c["pred_icon_agree"] + c["pred_icon_disagree"] + c["pred_icon_icon_unplayed"] >= 20]
    out["pred_agree_frac_min_session"] = min(per_frac)
    out["sessions_with_20_icon_cols"] = len(per_frac)
    out["sessions_icons_fit_pred_among_ties"] = tot["icons_fit_pred_among_ties"]
    out["sessions_full_fit_pred_unique"] = tot["full_fit_pred_unique"]
    out["sessions_icons_fit_pred_unique"] = sum(1 for _, f in per.values()
                                                if f["icons_ties"] == [(PRED_O1, PRED_O2)])
    out["sessions_full_fit_other_unique"] = sum(
        1 for _, f in per.values() if len(f["full_ties"]) == 1 and f["full_ties"] != [(PRED_O1, PRED_O2)])
    out["sessions_full_fit_tied"] = sum(1 for _, f in per.values() if len(f["full_ties"]) > 1)
    for b in ("before_3s", "last_3s", "after"):
        out[f"decided_col_{b}_icon_frac"] = frac(tot[f"decided_col_{b}_icon"], tot[f"decided_col_{b}"])
    out["icons_fit_agree_frac"] = frac(tot["icons_fit_agree"], tot["icons_fit_n"])
    out["full_fit_agree_frac"] = frac(tot["full_fit_agree"], tot["full_fit_n"])
    out["per_session"] = {s: {**dict(sorted(c.items())), **f} for s, (c, f) in per.items()}
    out["classes_by_column"] = {f"{c}_{line}_{cls}": v for (c, line, cls), v in sorted(cls_by_c.items())}
    return out, bad


def metric_values(out: dict) -> dict:
    """The summary flattened to the numbers the write-up may cite: every
    total, and per session the samples read present, the icon columns under
    the predicted offsets and those naming the stored winner, and the number
    of offset pairs tied at the best full-column fit."""
    vals = {k: v for k, v in out.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for sid, c in out["per_session"].items():
        n = (c.get("pred_icon_agree", 0) + c.get("pred_icon_disagree", 0)
             + c.get("pred_icon_icon_unplayed", 0) + c.get("sep_cols_icon", 0))
        vals[f"s_{sid}_present"] = c.get("verdict_present", 0)
        vals[f"s_{sid}_icon_cols"] = n
        vals[f"s_{sid}_icon_agree"] = c.get("pred_icon_agree", 0)
        vals[f"s_{sid}_full_fit_ties"] = len(c["full_ties"])
        vals[f"s_{sid}_icons_fit_ties"] = len(c["icons_ties"])
        vals[f"s_{sid}_icons_fit_pred_best"] = int([PRED_O1, PRED_O2] in [list(t) for t in c["icons_ties"]])
    return vals


def cmd_report(args) -> None:
    store = Store(args.store)
    rows = [json.loads(l) for l in Path(args.samples).read_text(encoding="utf-8").splitlines() if l]
    versions = {r["marks_version"] for r in rows}
    if versions != {MARKS_VERSION}:
        raise SystemExit(f"samples read by {sorted(versions)}, not {MARKS_VERSION}: reread")
    out, bad = summarise(store, rows)
    for k, v in out.items():
        if k not in ("per_session", "classes_by_column"):
            print(f"{k} = {v}")
    for s, c in out["per_session"].items():
        def ties(t):
            return t if len(t) <= 3 else f"{len(t)} tied"
        n_icon = (c.get("pred_icon_agree", 0) + c.get("pred_icon_disagree", 0)
                  + c.get("pred_icon_icon_unplayed", 0))
        print(f"{s} present {c.get('verdict_present', 0)}/{c['samples']} "
              f"icons-fit {c['icons_best'][0]}/{c['icons_best'][1]} {ties(c['icons_ties'])} "
              f"full-fit {c['full_best'][0]}/{c['full_best'][1]} {ties(c['full_ties'])} | pred: "
              f"icon {c.get('pred_icon_agree', 0)}/{n_icon} "
              f"played {c.get('played_cols_icon_right', 0)}/{c.get('played_cols', 0)} "
              f"yellow {c.get('yellow_at_13_plus_other', 0)}/{c.get('yellow_cells', 0)} "
              f"current {c.get('current_at_current', 0)}/{c.get('current_cols', 0)}")
    print(Counter(b["why"] for b in bad))
    if args.record:
        from reticle import metrics
        from reticle.roi_cache import ROI_CACHE_VERSION
        row = metrics.record(
            tool="scoreboard", part="round-marks", session="all-sessions",
            values=metric_values(out),
            deps={"roi_cache_version": ROI_CACHE_VERSION, "strip_prototype_version": "0.2.0"},
            context={"marks_version": MARKS_VERSION, "samples": str(args.samples),
                     "sample_every_ms": SAMPLE_EVERY_MS, "sessions": out["sessions"],
                     "rounds": "reticle.rounds.build_rounds over the stored HUD reads",
                     "offsets_predicted": [PRED_O1, PRED_O2], "near_end_ms": NEAR_END_MS},
            status="pass")
        print(f"recorded scoreboard/round-marks@all-sessions ({len(row['values'])} values)")
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": out, "disagreements": bad}, indent=1),
                                   encoding="utf-8")


def cmd_montage(args) -> None:
    """Crops from a report's disagreement list (KIND one or more `why`s,
    comma-separated, taken in turn) or from the samples (KIND `present`),
    with the columns ticked and the disagreeing one marked red."""
    store = Store(args.store)
    rng = random.Random(args.seed)
    if args.kind == "present":
        rows = [json.loads(l) for l in Path(args.samples).read_text(encoding="utf-8").splitlines() if l]
        pick_ = [r for r in rows if r["verdict"] == "present"]
        rng.shuffle(pick_)
        pick_ = pick_[:args.n]
    else:
        bad = json.loads(Path(args.report).read_text(encoding="utf-8"))["disagreements"]
        pools = []
        for kind in args.kind.split(","):
            pool = [b for b in bad if b["why"] == kind]
            rng.shuffle(pool)
            pools.append(pool)
        pick_ = []
        while len(pick_) < args.n and any(pools):
            for pool in pools:
                if pool and len(pick_) < args.n:
                    pick_.append(pool.pop())
    rows = {(r["session_id"], r["frame_idx"]): r for r in
            (json.loads(l) for l in Path(args.samples).read_text(encoding="utf-8").splitlines() if l)}
    tiles, sessions = [], {}
    scale = 3
    for p in pick_:
        sid = p["session_id"]
        sess = sessions.get(sid) or strip.Session(store, sid)
        sessions[sid] = sess
        r = rows[(sid, p["frame_idx"])]
        i = int(np.searchsorted(sess.frames, p["frame_idx"]))
        crop = sess.crop(i)
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        x0 = sess.rect[0]
        for col in r["columns"]:
            x = int((col["x"] - x0) * scale)
            hit = "c" in p and col["c"] == p["c"]
            cv2.line(big, (x, 0), (x, 10 if hit else 5), (0, 0, 255) if hit else (0, 255, 0), 2 if hit else 1)
            cv2.putText(big, str(col["c"]), (x - 3, big.shape[0] - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (0, 0, 255) if hit else (255, 255, 255))
        lab = np.zeros((34, big.shape[1], 3), np.uint8)
        line1 = f"{sid[:6]} {p['t_ms'] / 1000:.0f}s"
        if "why" in p:
            line1 += f" {p['why']} c{p['c']} rd{p['round']}"
            line2 = f"dec{p['decided']} {p['ally']}-{p['enemy']} u:{p['upper'][:5]} l:{p['lower'][:5]} st:{p['stored']}"
        else:
            line2 = " ".join(f"{col['c']}{col['upper'][0]}{col['lower'][0]}" for col in r["columns"])
        cv2.putText(lab, line1, (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255))
        cv2.putText(lab, line2[:60], (3, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255))
        tiles.append(cv2.copyMakeBorder(np.vstack([lab, big]), 2, 2, 2, 2, cv2.BORDER_CONSTANT,
                                        value=(0, 200, 255)))
    if not tiles:
        raise SystemExit(f"no rows of kind {args.kind}")
    per = 3
    while len(tiles) % per:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[j:j + per]) for j in range(0, len(tiles), per)])
    cv2.imwrite(args.out, grid)
    print(f"{len(pick_)} crops -> {args.out}")


def main(argv=None) -> None:
    strip._idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("read")
    s.add_argument("--out", default=str(SAMPLES))
    s.add_argument("--limit", type=int, default=0, help="samples per session (0: all)")
    s.set_defaults(fn=cmd_read)
    st = sub.add_parser("stats")
    st.add_argument("--samples", default=str(SAMPLES))
    st.set_defaults(fn=cmd_stats)
    rp = sub.add_parser("report")
    rp.add_argument("--samples", default=str(SAMPLES))
    rp.add_argument("--json", default=None)
    rp.add_argument("--record", action="store_true", help="write the metric row")
    rp.set_defaults(fn=cmd_report)
    m = sub.add_parser("montage")
    m.add_argument("out")
    m.add_argument("kind")
    m.add_argument("n", type=int, nargs="?", default=12)
    m.add_argument("--samples", default=str(SAMPLES))
    m.add_argument("--report", default=None)
    m.add_argument("--seed", type=int, default=7)
    m.set_defaults(fn=cmd_montage)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
