r"""How many Tab scoreboard frames each opening needs, measured on stored rows.

    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py pixels --out DIR [SID ...]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py pixels --cols --out DIR [SID ...]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py calibrate --out DIR
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py eval --out DIR [--record]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py posthoc --out DIR [--record]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py crops --out DIR [--n 6]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py thin-check --rule on --out COPYDIR SID
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py migrate --out DIR [--replace] [--record] [SID ...]

The player (2026-10-04): "It probably literally only needs one read per
scoreboard opening honestly". The scoreboard crop cache holds every 2 Hz
sample the round-history strip witness reads present or unreadable, plus one
sample either side (`roi_cache.scoreboard_gate`). This prototype asks which
of those frames the stored consumers need, and writes nothing to the store
but ledger rows (`scoreboard_reads/*`).

**An opening** is a run of strip samples reading present or unreadable (the
cache gate's verdicts, `roi_cache.SCOREBOARD_GATE_VERDICTS`), joined across
one-sample holes by the owner's `adjudication.scoreboard.presence_runs`.
It asks the strip witness only, never the slab test or a row: a cache rule
must rest on the opportunity, not the reader's outcome.

**The rules** (fixed before measuring; `RULES`), per opening of on-samples
`s_0 .. s_{n-1}`:

* `a`  the first frame after the animation, by a fixed delay: `s_1` when
  n >= 2, else `s_0`. `a0` (always `s_0`) is the diagnostic that shows what
  the delay buys.
* `b`  the middle sample `s_{n//2}`;  `c`  the last, `s_{n-1}`;  `d`  a + c.
* `e`  a, plus every later sample whose mean absolute grey difference to the
  previous on-sample exceeds `theta`. The difference is taken over the
  table's columns (`scoreboard.table_columns`) and the rows the two blocks
  can reach (`BOARD_Y`), shrunk by `DIFF_SCALE` with INTER_AREA. `theta`
  maximises Youden's J for "the stored per-frame state changed" on the dev
  half of the matches (`split`, a fixed hash), and the held half is scored
  once.
* `e_cal`, `e_cred` (added after the pre-registration, before any held
  result): rule `e` with theta chosen on the dev half by `calibrate` as the
  smallest frame count whose outputs all equal all frames' (else the fewest
  changed outputs), over the whole table or over the credits column bins
  (`credit_bins`, from `pixels --cols`).
* `on` (post-hoc, after the held half was scored; `posthoc`): every
  on-sample, dropping only the cache gate's one-sample margins.

**Re-adjudication.** For each rule the session's stored `scoreboard` rows are
thinned to the selected frames (`thin_rows`, in memory; the stored stream is
never touched) and every consumer is asked again through its owner:
`identity.board_side_sets` over `scoreboard_openings` (the lineup's board
sets), `reconciliation.adjudicate_scoreboard_credits` (credits and the local
row), `death.scoreboard_death_claims` per stored round with the board-alive
audit's contradictions (the death witness), and
`combat_report.scoreboard_bound` per round (the kill and death increments the
combat report binds). Each output is compared with the same call on all
frames.

`pixels` reads the scoreboard crop cache (FFV1, no capture decode) once per
session and stores the per-sample differences in DIR; `eval` reads them and
the stored streams; `calibrate` fixes the variants' thresholds on the dev
half first; `crops` writes the cached frames behind the first
disagreements for inspection.

**The migration** (`migrate`, approved by the player 2026-10-05: thin by
rule `on`). New captures are gated at margin 0 (`roi_cache.SCOREBOARD_GATE_MARGIN`);
each stored margin-1 cache is re-encoded from itself, no capture decoded,
by `roi_cache.thin_cache` into `MIGRATE_DIR`, and replaces the stored cache
only where every check passes (`migrate_session`): the stored gate is the
margin-1 gate of the stored strip rows, the margin-0 gate keeps exactly
rule `on`'s frames, every kept frame reads back bit for bit, `RoiCache`
serves the copy with `thinned_out` and `outside_gate` refusals, and every
consumer output above equals all frames'. A failed session keeps its cache.
This is the one command here that writes the store beyond ledger rows.

Owns nothing: a measurement and a one-time migration. Wire: no (the player
decides on the numbers).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle.adjudication.scoreboard import (board_presence, presence_runs,  # noqa: E402
                                             scoreboard_openings)
from reticle.roi_cache import SCOREBOARD_GATE_VERDICTS  # noqa: E402

READS_VERSION = "scoreboard-reads-0.1.0"
STORE = Path(os.environ.get("RETICLE_STORE", "C:/Users/grant/reticle-store"))
CACHE = STORE / "roi_cache" / "scoreboard" / "roi-cache-0.1.0"
RULES = ("all", "a0", "a", "b", "c", "d", "e")
#: Rule `e` with dev-calibrated thresholds, added after the pre-registration
#: and before any held-half result (`calibrate`): `e_cal` differences the
#: whole table, `e_cred` only the credits column bins (`CREDIT_BINS`).
VARIANTS = ("e_cal", "e_cred")
#: The table's columns cut into this many equal bins for the per-column
#: differences (`pixels --cols`).
NBINS = 24
#: Rules added after the held half was scored (`posthoc`), labelled so in
#: every output: `on` keeps every on-sample of every opening and drops only
#: the cache gate's one-sample margins.
POST_HOC = ("on",)
#: The cached crop shrunk this many times (INTER_AREA) before differencing.
DIFF_SCALE = 4
#: Frame rows the two five-row blocks can reach: the strip's marker lines
#: (`scoreboard_strip.ROW_Y`) less and plus the gap to each block and the
#: tallest block the reader accepts (`scoreboard.MAX_BLOCK_H`).


def board_y() -> tuple[int, int]:
    from reticle import scoreboard as sb, scoreboard_strip as st
    return (st.ROW_Y[0] - sb.STRIP_ALLY_GAP - sb.MAX_BLOCK_H,
            st.ROW_Y[1] + sb.STRIP_ENEMY_GAP + sb.MAX_BLOCK_H)


def credit_span() -> tuple[float, float]:
    """The credits digits' columns as a fraction of the table width: every
    credit layout's pens on both cards (`scoreboard.BOARD_PENS`), the last
    one cell (two digit advances) wide."""
    from reticle import scoreboard as sb
    pens = [p for card in sb.BOARD_PENS.values() for lay in card["credits"] for p in lay]
    return min(pens) / sb.TABLE_W, (max(pens) + 16.0) / sb.TABLE_W


def credit_bins() -> list[int]:
    """The column bins (`NBINS` over `table_columns`) that can hold the
    credits cell: `credit_span` of the table width, widened by
    `FRAME_SEARCH`, the reader's frame fit either side of `table_columns`.
    A dimmed (dead) row dims this cell too."""
    from reticle import scoreboard as sb
    slack = sb.FRAME_SEARCH / sb.TABLE_W
    lo, hi = credit_span()
    lo, hi = lo - slack, hi + slack
    return [k for k in range(NBINS) if (k + 1) / NBINS > lo and k / NBINS < hi]


def below_normal() -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


def split(sid: str) -> str:
    """`dev` or `held`, by a fixed hash of the session id."""
    h = int(hashlib.sha1(f"scoreboard_reads:{sid}".encode()).hexdigest(), 16)
    return "dev" if h % 2 == 0 else "held"


# ------------------------------------------------------------------ openings

def strip_runs(board_rows: list[dict], strip_rows: list[dict]) -> list[dict]:
    """Openings by the strip witness alone: runs of samples whose strip
    verdict opens the cache gate, joined across one-sample holes by
    `presence_runs`. Each carries `frames`, its on-samples' frame indices,
    and `times`, in order."""
    samples = board_presence(board_rows, strip_rows)["samples"]
    on = lambda s: s["strip"] in SCOREBOARD_GATE_VERDICTS  # noqa: E731
    out = []
    for k, run in enumerate(presence_runs(samples, on)):
        seg = [s for s in samples[run["a"]:run["z"] + 1] if on(s)]
        out.append({"run": k, "frames": [int(s["frame_idx"]) for s in seg],
                    "times": [float(s["t_ms"]) for s in seg],
                    "t_first_ms": run["t_first_ms"], "t_last_ms": run["t_last_ms"]})
    return out


def select(frames: list[int], rule: str, diffs: dict | None = None,
           theta: float | None = None) -> list[int]:
    """The frames of one opening a rule keeps (`RULES`). `diffs` maps a
    frame to its difference from the previous on-sample (rule `e`)."""
    n = len(frames)
    if not n:
        return []
    a = 1 if n >= 2 else 0
    if rule in ("all", "on"):
        return list(frames)
    if rule == "a0":
        return [frames[0]]
    if rule == "a":
        return [frames[a]]
    if rule == "b":
        return [frames[n // 2]]
    if rule == "c":
        return [frames[-1]]
    if rule == "d":
        return sorted({frames[a], frames[-1]})
    if rule in ("e",) + VARIANTS:
        if theta is None or diffs is None:
            raise ValueError("rule e needs the differences and theta")
        keep = [frames[a]]
        for f in frames[a + 1:]:
            d = diffs.get(f)
            if d is not None and d > theta:
                keep.append(f)
        return keep
    raise ValueError(f"no rule {rule!r}; have {RULES}")


def thin_rows(rows: list[dict], keep: set[int]) -> list[dict]:
    """The stored scoreboard rows a cache holding only `keep` would give:
    coverage rows stay, per-frame rows only at kept frames."""
    return [r for r in rows if r.get("frame_idx") is None or int(r["frame_idx"]) in keep]


# ------------------------------------------------------------------ pixels

def _cap(path: Path):
    cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    if not cap.isOpened():
        raise ValueError(f"cannot open {path}")
    return cap


def small_frames(sid: str, keep_times: set[float] | None = None):
    """(t_ms, frame_idx, small grey board) for each cached frame, in cache
    order: the table's columns over `board_y` rows, shrunk by DIFF_SCALE."""
    from reticle.scoreboard import strip_rect, table_columns
    rec = json.loads((CACHE / f"{sid}.json").read_text(encoding="utf-8"))
    idx = np.load(CACHE / f"{sid}.idx.npy")
    x0r, y0r, _, _ = rec["rects"][0]
    w, h = rec["wh"]
    tx0, tx1 = table_columns(strip_rect(rec["profile"], w, h))
    y0, y1 = board_y()
    cap = _cap(CACHE / f"{sid}.r0.mkv")
    try:
        for t, f, _k, n, _ in idx:
            ok, crop = cap.read()
            if not ok:
                raise ValueError(f"{sid}: cache ended before frame {int(n)}")
            if keep_times is not None and float(t) not in keep_times:
                continue
            g = cv2.cvtColor(crop[y0 - y0r:y1 - y0r, tx0 - x0r:tx1 - x0r], cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (g.shape[1] // DIFF_SCALE, g.shape[0] // DIFF_SCALE),
                           interpolation=cv2.INTER_AREA)
            yield float(t), int(f), g.astype(np.float32)
    finally:
        cap.release()


def session_diffs(sid: str, runs: list[dict]) -> dict[int, float]:
    """Per on-sample after a run's first, the mean absolute grey difference
    to the run's previous on-sample."""
    prev_of = {}
    for r in runs:
        for p, f in zip(r["frames"], r["frames"][1:]):
            prev_of[f] = p
    want = {f for r in runs for f in r["frames"]}
    smalls = {}
    for _t, f, g in small_frames(sid):
        if f in want:
            smalls[f] = g
    return {f: float(np.mean(np.abs(smalls[f] - smalls[p])))
            for f, p in prev_of.items() if f in smalls and p in smalls}


def session_bin_diffs(sid: str, runs: list[dict]) -> dict[int, list[float]]:
    """As `session_diffs`, per column bin: the mean absolute grey difference
    in each of `NBINS` equal column bins of the table."""
    prev_of = {}
    for r in runs:
        for p, f in zip(r["frames"], r["frames"][1:]):
            prev_of[f] = p
    want = {f for r in runs for f in r["frames"]}
    smalls = {}
    for _t, f, g in small_frames(sid):
        if f in want:
            smalls[f] = g
    out = {}
    for f, p in prev_of.items():
        if f in smalls and p in smalls:
            d = np.abs(smalls[f] - smalls[p])
            out[f] = [round(float(c.mean()), 4) for c in np.array_split(d, NBINS, axis=1)]
    return out


def diff_maps(px: dict, cols: dict | None) -> dict[str, dict[int, float]]:
    """The difference each rule-e variant thresholds, per frame."""
    full = {int(k): v for k, v in px["diffs"].items()}
    out = {"e": full, "e_cal": full}
    if cols is not None:
        cb = credit_bins()
        out["e_cred"] = {int(k): float(np.mean([v[i] for i in cb]))
                         for k, v in cols["bins"].items()}
    return out


# ------------------------------------------------------------------ loading

def load(sid: str) -> dict:
    from reticle.store import Store
    st = Store(STORE)
    man = st.read_manifest(sid)
    date = man["ingested_at"][:10]
    board = st.read_events("scoreboard", sid)
    strip = st.read_events("scoreboard_strip", sid)
    deaths = [r for r in st.read_events("death", sid) if r.get("kind") == "death_verdict"]
    rounds = st.read_rounds(sid, date).to_pylist()
    return {"sid": sid, "board": board, "strip": strip, "deaths": deaths, "rounds": rounds,
            "hud": st.read_hud(sid, date), "roster": st.read_roster(sid, date)}


def enemy_named(sid: str) -> list[str]:
    from reticle.adjudication.identity import side_candidates
    from reticle.lineup import load_lineup
    lineup = load_lineup(sid, STORE) or {}
    return side_candidates((lineup.get("sides") or {}).get("enemy", []))["named"]


# ------------------------------------------------------------------ consumers

def lineup_sets(rows: list[dict]) -> dict:
    from reticle.adjudication.identity import board_side_sets
    sets = board_side_sets(scoreboard_openings(rows))
    return {side: {"agents": v["agents"], "reason": v["reason"], "openings": len(v["openings"])}
            for side, v in sets.items()}


def credits(rows: list[dict]) -> list[dict]:
    from reticle.reconciliation import adjudicate_scoreboard_credits
    return [{k: r[k] for k in ("t_start_ms", "t_end_ms", "team", "display_row", "credits",
                               "credit_status", "player_id", "identity_status")}
            for r in adjudicate_scoreboard_credits(rows)]


def _by_channel(v: dict) -> list:
    by = ((v.get("metadata") or {}).get("identity") or {}).get("by_channel") or {}
    return [[ch, row["agent"]] for ch, row in by.items()
            if row.get("agent") and ch != "scoreboard_dim"]


def death_claims(rows: list[dict], s: dict, audit) -> list[dict]:
    """The scoreboard death witness per stored death, asked of
    `scoreboard_death_claims` round by round as `adjudicate_session_deaths`
    asks it, with the stored verdicts standing in for the first pass."""
    from reticle.adjudication.death import scoreboard_death_claims
    from reticle.reconciliation import contradicted_openings
    out = []
    by_round = defaultdict(list)
    for v in s["deaths"]:
        by_round[v.get("round_no")].append(v)
    for r in s["rounds"]:
        entries = sorted(by_round.get(r["round_no"], []), key=lambda v: (v["t_ms"], v.get("slot") or 0))
        if not entries:
            continue
        a, z = r["t_start_ms"], r.get("t_close_ms") or r["t_end_ms"]
        openings = scoreboard_openings([x for x in rows if a <= float(x.get("t_ms", -1)) <= z])
        claims = scoreboard_death_claims(
            entries, openings, {i: v.get("victim") for i, v in enumerate(entries)},
            {i for i, v in enumerate(entries) if v.get("is_second_life")},
            contradicted_openings(audit(openings)),
            {i: _by_channel(v) for i, v in enumerate(entries)})
        for v, c in zip(entries, claims):
            ev = c.get("evidence") or {}
            kp = next((w.get("agent") for w in v.get("witnesses") or []
                       if w.get("channel") == "killfeed_portrait"), None)
            out.append({"death_id": v["death_id"], "t_ms": v["t_ms"], "side": v.get("side"),
                        "killfeed_portrait": kp,
                        "agent": c["agent"], "reason": c["reason"],
                        "before": (ev.get("opening_before") or {}).get("frame_idx"),
                        "after": (ev.get("opening_after") or {}).get("frame_idx")})
    return out


def kd_bounds(rows: list[dict], s: dict, enemy: list[str]) -> list[dict]:
    from reticle.adjudication.combat_report import scoreboard_bound
    board = [{"t": r["t_ms"], "agent": r.get("portrait_agent_best"),
              "kills": r.get("kills"), "deaths": r.get("deaths")}
             for r in rows if r.get("kind") == "row_observation" and r.get("team") == "enemy"
             and r.get("portrait_agent_best")]
    out = []
    for r in s["rounds"]:
        died, killed = scoreboard_bound(board, enemy, r["t_start_ms"], r["t_end_ms"],
                                        r.get("t_close_ms") or r["t_end_ms"])
        out.append({"round_no": r["round_no"], "died": sorted(died), "killed": sorted(killed)})
    return out


def stored_dim(s: dict) -> dict[str, str | None]:
    """The stored death verdicts' own scoreboard_dim witness, per death: the
    instrument check on `death_claims`."""
    out = {}
    for v in s["deaths"]:
        w = next((w for w in v.get("witnesses") or [] if w.get("channel") == "scoreboard_dim"), None)
        out[v["death_id"]] = None if w is None else w.get("agent")
    return out


# ------------------------------------------------------------------ comparison

def _cmp(base, got) -> str:
    """same / lost / gained / changed / both_refused for one named-or-None output."""
    if base == got:
        return "same" if base is not None else "both_refused"
    if got is None:
        return "lost"
    if base is None:
        return "gained"
    return "changed"


def credit_match(c: dict, cands: list[dict]) -> dict | None:
    """The thinned run's credit row for all frames' row `c`: the same team
    and display row whose [t_start, t_end] overlaps `c`'s most, else None.
    `adjudicate_scoreboard_credits` groups reads by a time gap, so thinning
    can move a group's start into another strip run; matching by overlap
    keeps that shift from counting as a lost credit."""
    best, best_ov = None, -1.0
    for g in cands:
        ov = min(c["t_end_ms"], g["t_end_ms"]) - max(c["t_start_ms"], g["t_start_ms"])
        if ov >= 0 and ov > best_ov:
            best, best_ov = g, ov
    return best


def compare(base: dict, got: dict, runs: list[dict]) -> dict:
    """Every downstream output of one rule against all frames'."""
    out = {}
    sides = Counter()
    for side in ("ally", "enemy"):
        b, g = base["lineup"][side], got["lineup"][side]
        sides[_cmp(tuple(b["agents"] or ()) or None, tuple(g["agents"] or ()) or None)] += 1
        if b["reason"] != g["reason"]:
            sides["reason_changed"] += 1
    out["lineup"] = dict(sides)

    by_row = defaultdict(list)
    for c in got["credits"]:
        by_row[(c["team"], c["display_row"])].append(c)
    cr, ident, details = Counter(), Counter(), []
    for c in base["credits"]:
        g = credit_match(c, by_row[(c["team"], c["display_row"])])
        v = _cmp(c["credits"], None if g is None else g["credits"])
        cr[v] += 1
        if v in ("changed", "lost", "gained") and len(details) < 40:
            details.append({"t_ms": c["t_start_ms"], "t_end_ms": c["t_end_ms"], "kind": v,
                            "rule_t_ms": None if g is None else g["t_start_ms"],
                            "team": c["team"], "row": c["display_row"],
                            "all": c["credits"], "rule": None if g is None else g["credits"],
                            "all_status": c["credit_status"],
                            "rule_status": None if g is None else g["credit_status"]})
        if c["player_id"] is not None or (g and g["player_id"] is not None):
            ident[_cmp(c["player_id"], None if g is None else g["player_id"])] += 1
    out["credits"], out["local_row"], out["credit_examples"] = dict(cr), dict(ident), details

    gd = {d["death_id"]: d for d in got["deaths"]}
    dc, dd = Counter(), []
    for d in base["deaths"]:
        g = gd[d["death_id"]]
        v = _cmp(d["agent"], g["agent"])
        if v == "both_refused" and d["reason"] != g["reason"]:
            v = "refusal_reason_changed"
        dc[v] += 1
        if v in ("lost", "gained", "changed"):
            kp = d["killfeed_portrait"]
            named = d["agent"] if v == "lost" else g["agent"]
            dc[f"{v}_vs_killfeed_" + ("none" if kp is None else
                                       "agree" if named == kp else "disagree")] += 1
        if v not in ("same", "both_refused"):
            dd.append({"death_id": d["death_id"], "t_ms": d["t_ms"], "side": d["side"],
                       "kind": v, "killfeed_portrait": d["killfeed_portrait"],
                       "all": [d["agent"], d["reason"], d["before"], d["after"]],
                       "rule": [g["agent"], g["reason"], g["before"], g["after"]]})
    out["deaths"], out["death_examples"] = dict(dc), dd

    gb = {r["round_no"]: r for r in got["kd"]}
    kc = Counter()
    for r in base["kd"]:
        g = gb[r["round_no"]]
        kc["same" if (r["died"], r["killed"]) == (g["died"], g["killed"]) else "changed"] += 1
    out["kd_bound"] = dict(kc)
    out["accepted_openings"] = got["accepted"]
    out["runs_with_accepted"] = got["runs_with_accepted"]
    return out


def outputs(rows: list[dict], s: dict, audit, enemy: list[str], runs: list[dict]) -> dict:
    ops = scoreboard_openings(rows)
    acc = {int(o["frame_idx"]) for o in ops if o["accepted"]}
    return {"lineup": lineup_sets(rows), "credits": credits(rows),
            "deaths": death_claims(rows, s, audit), "kd": kd_bounds(rows, s, enemy),
            "accepted": len(acc),
            "runs_with_accepted": sum(1 for r in runs if acc & set(r["frames"]))}


# ------------------------------------------------------------------ field changes

FIELDS = ("kills", "deaths", "assists", "credits", "dim", "is_player", "agent")


def frame_states(rows: list[dict]) -> dict[int, dict]:
    """Per frame with an accepted opening, (team, agent) -> the row's fields;
    a frame whose opening is refused maps to None."""
    raw = {r["observation_key"]: r for r in rows if r.get("kind") == "row_observation"}
    out = {}
    for o in scoreboard_openings(rows):
        f = int(o["frame_idx"])
        if not o["accepted"]:
            out[f] = None
            continue
        st = {}
        for s in o["rows"]:
            r = raw[s["observation_key"]]
            st[(s["team"], s["agent"])] = {
                "kills": r.get("kills"), "deaths": r.get("deaths"), "assists": r.get("assists"),
                "credits": r.get("credits_candidate"), "dim": s["dim"],
                "is_player": bool(r.get("is_player")), "display_row": s["display_row"]}
        out[f] = st
    return out


def field_changes(states: dict[int, dict | None], runs: list[dict]) -> dict:
    """In how many openings each field differs between the first and last
    accepted frame (a value read on both), and how many have two."""
    n2, changed = 0, Counter()
    for r in runs:
        acc = [f for f in r["frames"] if states.get(f)]
        if len(acc) < 2:
            continue
        n2 += 1
        first, last = states[acc[0]], states[acc[-1]]
        if set(first) != set(last):
            changed["agent"] += 1
        hit = set()
        for k in set(first) & set(last):
            for fld in FIELDS[:-1]:
                a, b = first[k][fld], last[k][fld]
                if a is not None and b is not None and a != b:
                    hit.add(fld)
        changed.update(hit)
        if hit or set(first) != set(last):
            changed["any"] += 1
    return {"openings_with_two_accepted": n2, **{f: changed.get(f, 0) for f in FIELDS + ("any",)}}


def pair_labels(states: dict[int, dict | None], runs: list[dict]) -> dict[int, bool]:
    """Per on-sample after a run's first: did the stored state change from
    the previous on-sample (acceptance, or any field of an accepted pair)?"""
    out = {}
    for r in runs:
        for p, f in zip(r["frames"], r["frames"][1:]):
            a, b = states.get(p), states.get(f)
            if (a is None) != (b is None):
                out[f] = True
            elif a is None:
                out[f] = False
            else:
                out[f] = set(a) != set(b) or any(
                    a[k][fld] != b[k][fld] for k in set(a) & set(b) for fld in FIELDS[:-1]
                    if a[k][fld] is not None and b[k][fld] is not None)
    return out


def youden_theta(d: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """The threshold on `d` (fire when d > theta) maximising TPR - FPR."""
    cand = np.unique(np.quantile(d, np.linspace(0.0, 0.995, 400)))
    pos, neg = max(1, int(y.sum())), max(1, int((~y).sum()))
    fire = d[None, :] > cand[:, None]
    j = (fire & y[None, :]).sum(1) / pos - (fire & ~y[None, :]).sum(1) / neg
    k = int(np.argmax(j))
    return float(cand[k]), float(j[k])


# ------------------------------------------------------------------ bytes

def packet_sizes(sid: str) -> np.ndarray:
    """Each cached frame's FFV1 packet size in bytes, by demuxing (no decode)."""
    import av
    with av.open(str(CACHE / f"{sid}.r0.mkv")) as c:
        return np.array([p.size for p in c.demux(video=0) if p.size], np.int64)


def thin_copy(sid: str, keep_frames: set[int], dst: Path) -> dict:
    """The thinning procedure, run on a COPY: decode a session's scoreboard
    cache (FFV1, one thread), re-encode only the kept frames as FFV1 level 3
    `bgr0` (the cache writer's settings, `roi_cache`) into `dst`, a directory
    outside the store, and write the index and record a thinned cache would
    carry. The cache's FFV1 carries a key frame every 12 frames and its other
    frames depend on the coder state before them, so packets cannot be
    remuxed alone (a remux left most kept frames undecodable); FFV1 is
    lossless, so a re-encode keeps every kept frame's pixels. A kept frame's
    position in the new file is its index row's offset column.

    The record keeps its gate and gains `thinned`: the rule, the frames before
    and kept. `RoiCache.refusal` would then say `thinned_out` for a time inside
    the gate that the rule dropped (today it says `not_cached`)."""
    import av
    dst.mkdir(parents=True, exist_ok=True)
    rec = json.loads((CACHE / f"{sid}.json").read_text(encoding="utf-8"))
    idx = np.load(CACHE / f"{sid}.idx.npy")
    pos = [i for i, f in enumerate(idx[:, 1].astype(int)) if int(f) in keep_frames]
    keep_pos = set(pos)
    out_path = dst / f"{sid}.r0.mkv"
    n_in = n_out = 0
    with av.open(str(CACHE / f"{sid}.r0.mkv")) as src, av.open(str(out_path), "w") as out:
        s_in = src.streams.video[0]
        s_in.codec_context.thread_count = 1
        s_out = out.add_stream("ffv1", rate=30)
        s_out.width, s_out.height = s_in.codec_context.width, s_in.codec_context.height
        s_out.pix_fmt = "bgr0"
        s_out.options = {"level": "3"}
        s_out.codec_context.thread_count = 1
        for frame in src.decode(s_in):
            if n_in in keep_pos:
                frame.pts = n_out
                for pkt in s_out.encode(frame):
                    out.mux(pkt)
                n_out += 1
            n_in += 1
        for pkt in s_out.encode(None):
            out.mux(pkt)
    new_idx = idx[pos].copy()
    new_idx[:, 3] = np.arange(len(pos))
    np.save(dst / f"{sid}.idx.npy", new_idx)
    record = {**rec, "frames": len(pos), "bytes": out_path.stat().st_size,
              "thinned": {"tool": READS_VERSION, "frames_before": int(len(idx)),
                          "frames_kept": len(pos)}}
    (dst / f"{sid}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"frames_before": int(len(idx)), "frames_kept": len(pos), "frames_written": n_out,
            "bytes_before": int((CACHE / f"{sid}.r0.mkv").stat().st_size),
            "bytes_after": int(out_path.stat().st_size), "frames_decoded": n_in}


def check_thin_copy(sid: str, dst: Path) -> dict:
    """Read every frame of the thinned copy back through OpenCV, beside the
    stored cache read in order, and compare each kept frame bit for bit."""
    new_idx = np.load(dst / f"{sid}.idx.npy")
    old_idx = np.load(CACHE / f"{sid}.idx.npy")
    keep = set(new_idx[:, 1].astype(int))
    a, b = _cap(CACHE / f"{sid}.r0.mkv"), _cap(dst / f"{sid}.r0.mkv")
    same = differ = 0
    try:
        for row in old_idx:
            ok1, x = a.read()
            if int(row[1]) in keep:
                ok2, y = b.read()
                if ok1 and ok2 and np.array_equal(x, y):
                    same += 1
                else:
                    differ += 1
        extra = b.read()[0]
    finally:
        a.release()
        b.release()
    return {"checked": len(new_idx), "identical": same, "different": differ,
            "extra_frames": bool(extra)}


def reader_cost(sids: list[str]) -> dict:
    """The scoreboard reader's time per closed and per open frame, from each
    session's latest stored scan usage (`notes/usage.jsonl`) and the stored
    coverage row of the same scan: a non-negative least-squares fit of feed time against
    the closed and open frame counts, over the sessions whose usage fed as
    many frames as the coverage offered."""
    from reticle.store import Store
    st = Store(STORE)
    latest = {}
    for line in (STORE / "notes" / "usage.jsonl").open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rd = (r.get("readers") or {}).get("scoreboard") or {}
        feed = rd.get("feed") or {}
        if r.get("session_id") in sids and feed.get("total_ns"):
            latest[r["session_id"]] = (feed, r.get("pipeline"), r.get("contention") or {})
    X, y, used = [], [], []
    for sid, (feed, _pipe, _cont) in sorted(latest.items()):
        cov = next((r for r in st.read_events_kind("scoreboard", sid, "coverage")), None)
        if cov is None or cov.get("frames_offered") != feed["count"]:
            continue
        X.append([cov["frames_offered"] - cov["frames_open"], cov["frames_open"]])
        y.append(feed["total_ns"] / 1e6)
        used.append(sid)
    X, y = np.array(X, float), np.array(y, float)
    from scipy.optimize import nnls
    (closed_ms, open_ms), _ = nnls(X, y)
    return {"sessions": len(used), "closed_ms": float(closed_ms), "open_ms": float(open_ms),
            "mean_ms": float(y.sum() / X.sum()),
            "frames": int(X.sum()), "open_frames": int(X[:, 1].sum())}


# ------------------------------------------------------------------ commands

def sessions() -> list[str]:
    return sorted(p.stem for p in CACHE.glob("*.json"))


def cmd_pixels(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from reticle.store import Store
    st = Store(STORE)
    for sid in args.sessions or sessions():
        if args.cols:
            dst = out / f"{sid}.cols.json"
            if dst.is_file():
                continue
            t0 = time.time()
            runs = strip_runs(st.read_events("scoreboard", sid),
                              st.read_events("scoreboard_strip", sid))
            bins = session_bin_diffs(sid, runs)
            dst.write_text(json.dumps({"sid": sid, "nbins": NBINS,
                                       "bins": {str(k): v for k, v in bins.items()}}),
                           encoding="utf-8")
            print(f"{sid}: {len(bins)} binned differences, {time.time() - t0:.0f}s", flush=True)
            continue
        dst = out / f"{sid}.pixels.json"
        if dst.is_file():
            continue
        t0 = time.time()
        runs = strip_runs(st.read_events("scoreboard", sid), st.read_events("scoreboard_strip", sid))
        diffs = session_diffs(sid, runs)
        sizes = packet_sizes(sid)
        dst.write_text(json.dumps({"sid": sid, "diffs": {str(k): v for k, v in diffs.items()},
                                   "packet_sizes": sizes.tolist()}), encoding="utf-8")
        print(f"{sid}: {len(diffs)} differences, {len(sizes)} packets, {time.time() - t0:.0f}s",
              flush=True)
    return 0


def evaluate_session(sid: str, out: Path) -> dict:
    from reticle.reconciliation import board_alive_auditor
    s = load(sid)
    px = json.loads((out / f"{sid}.pixels.json").read_text(encoding="utf-8"))
    diffs = {int(k): v for k, v in px["diffs"].items()}
    runs = strip_runs(s["board"], s["strip"])
    states = frame_states(s["board"])
    audit = board_alive_auditor(s["hud"], s["roster"])
    enemy = enemy_named(sid)
    idx = np.load(CACHE / f"{sid}.idx.npy")
    frame_pos = {int(f): i for i, f in enumerate(idx[:, 1])}
    labels = pair_labels(states, runs)
    cols_path = out / f"{sid}.cols.json"
    cols = json.loads(cols_path.read_text(encoding="utf-8")) if cols_path.is_file() else None
    return {"sid": sid, "split": split(sid), "s": s, "runs": runs, "states": states,
            "audit": audit, "enemy": enemy, "diffs": diffs, "labels": labels,
            "dmaps": diff_maps(px, cols),
            "frame_pos": frame_pos, "sizes": np.array(px["packet_sizes"], np.int64),
            "cache_frames": len(idx)}


def n_differ(c: dict) -> dict:
    """The downstream outputs one rule changed against all frames, by kind,
    from `compare`: a lineup side, an opening row's credits or local-row
    identity, a death claim (agent or refusal reason), a round's K/D bound."""
    got = {"lineup": sum(c["lineup"].get(k, 0) for k in ("lost", "gained", "changed",
                                                         "reason_changed")),
           "credits": sum(c["credits"].get(k, 0) for k in ("lost", "gained", "changed")),
           "local_row": sum(c["local_row"].get(k, 0) for k in ("lost", "gained", "changed")),
           "deaths": sum(c["deaths"].get(k, 0) for k in ("lost", "gained", "changed",
                                                         "refusal_reason_changed")),
           "kd": c["kd_bound"].get("changed", 0)}
    got["total"] = sum(got.values())
    # Outputs all frames named and the rule did not, or named otherwise; a
    # rule naming what all frames refused (gained) is not a loss.
    got["lost"] = (sum(c["lineup"].get(k, 0) for k in ("lost", "changed"))
                   + sum(c[f].get(k, 0) for f in ("credits", "local_row", "deaths")
                         for k in ("lost", "changed")) + got["kd"])
    return got


def keep_frames(e: dict, rule: str, theta: float | None) -> list[int]:
    dm = e["dmaps"].get(rule) if rule in ("e",) + VARIANTS else None
    return sorted({f for r in e["runs"] for f in select(r["frames"], rule, dm, theta)})


def run_rules(e: dict, thetas: dict[str, float]) -> dict:
    s, runs = e["s"], e["runs"]
    base = outputs(s["board"], s, e["audit"], e["enemy"], runs)
    res = {"stored_dim_check": Counter(), "rules": {}}
    sd = stored_dim(s)
    for d in base["deaths"]:
        res["stored_dim_check"][_cmp(sd.get(d["death_id"]), d["agent"])] += 1
    for rule in RULES[1:] + VARIANTS:
        if rule in ("e",) + VARIANTS and (rule not in e["dmaps"] or rule not in thetas):
            continue
        keep = keep_frames(e, rule, thetas.get(rule))
        rows = thin_rows(s["board"], set(keep))
        got = outputs(rows, s, e["audit"], e["enemy"], runs)
        pos = [e["frame_pos"][f] for f in keep if f in e["frame_pos"]]
        cmp_ = compare(base, got, runs)
        res["rules"][rule] = {"frames": len(keep), "frames_in_cache": len(pos),
                              "bytes": int(e["sizes"][pos].sum()) if pos else 0,
                              "differ": n_differ(cmp_), **cmp_}
    res["base"] = {"accepted": base["accepted"], "runs_with_accepted": base["runs_with_accepted"],
                   "credits_resolved": sum(c["credits"] is not None for c in base["credits"]),
                   "credit_rows": len(base["credits"]),
                   "deaths_named": sum(d["agent"] is not None for d in base["deaths"]),
                   "deaths": len(base["deaths"]), "lineup": base["lineup"]}
    res["stored_dim_check"] = dict(res["stored_dim_check"])
    return res


def _merge(acc: dict, part: dict) -> dict:
    for k, v in part.items():
        if isinstance(v, dict):
            _merge(acc.setdefault(k, {}), v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            acc[k] = acc.get(k, 0) + v
    return acc


def dev_youden(evs: list[dict]) -> tuple[float, float, int, int]:
    d, y = [], []
    for e in evs:
        if e["split"] != "dev":
            continue
        for f, lab in e["labels"].items():
            if f in e["diffs"]:
                d.append(e["diffs"][f])
                y.append(lab)
    theta, jbest = youden_theta(np.array(d), np.array(y, bool))
    return theta, jbest, len(d), int(np.sum(y))


def cmd_calibrate(args) -> int:
    """Rule e's threshold on the dev half only: for each variant, sweep
    theta over the dev differences' quantiles and keep the smallest frame
    count whose outputs all equal all frames' (else the fewest changed
    outputs, then the fewest frames). Writes calibration.json."""
    out = Path(args.out)
    evs = [evaluate_session(sid, out) for sid in sessions() if split(sid) == "dev"]
    bases = {e["sid"]: outputs(e["s"]["board"], e["s"], e["audit"], e["enemy"], e["runs"])
             for e in evs}
    theta_y, jbest, npairs, nchanged = dev_youden(evs)
    cal = {"version": READS_VERSION, "dev_sessions": [e["sid"] for e in evs],
           "youden": {"theta": theta_y, "j": jbest, "pairs": npairs, "changed": nchanged},
           "credit_bins": credit_bins(), "nbins": NBINS, "curves": {}, "chosen": {}}
    on = sum(len(r["frames"]) for e in evs for r in e["runs"])
    for var in VARIANTS:
        if any(var not in e["dmaps"] for e in evs):
            continue
        allv = np.concatenate([np.fromiter(e["dmaps"][var].values(), float) for e in evs])
        grid = sorted({0.0, *np.round(np.quantile(allv, np.linspace(0.02, 0.98, 49)), 4).tolist(),
                       float(allv.max()) + 1.0})
        curve = []
        for th in grid:
            frames, dif = 0, Counter()
            for e in evs:
                keep = keep_frames(e, var, th)
                got = outputs(thin_rows(e["s"]["board"], set(keep)), e["s"], e["audit"],
                              e["enemy"], e["runs"])
                frames += len(keep)
                dif.update(n_differ(compare(bases[e["sid"]], got, e["runs"])))
            curve.append({"theta": th, "frames": frames, **{k: dif.get(k, 0) for k in
                          ("total", "lost", "lineup", "credits", "local_row", "deaths", "kd")}})
            print(f"{var} theta {th:8.3f} frames {frames:6d} differ {dict(dif)}", flush=True)
        best = min(curve, key=lambda c: (c["total"], c["frames"]))
        cal["curves"][var] = curve
        cal["chosen"][var] = {"theta": best["theta"], "frames": best["frames"],
                              "differ": best["total"], "on_samples": on}
    (out / "calibration.json").write_text(json.dumps(cal, indent=1), encoding="utf-8")
    print(json.dumps({"youden": cal["youden"], "chosen": cal["chosen"]}))
    return 0


def cmd_eval(args) -> int:
    out = Path(args.out)
    below_normal()
    cal = json.loads((out / "calibration.json").read_text(encoding="utf-8"))
    evs = []
    for sid in sessions():
        if args.half != "all" and split(sid) != args.half:
            continue
        t0 = time.time()
        evs.append(evaluate_session(sid, out))
        print(f"loaded {sid} ({evs[-1]['split']}) {time.time() - t0:.0f}s", flush=True)
    # Openings and their lengths, and field changes.
    lengths, per_match, changes = [], {}, {}
    holds = {}
    for e in evs:
        lengths += [len(r["frames"]) for r in e["runs"]]
        per_match[e["sid"]] = len(e["runs"])
        changes[e["sid"]] = field_changes(e["states"], e["runs"])
        ops = scoreboard_openings(e["s"]["board"], strip_rows=e["s"]["strip"])
        holds[e["sid"]] = len({o["hold"] for o in ops if o.get("hold") is not None})
    # Theta on the dev half (the pre-registered Youden rule), and the
    # calibrated variants' thetas, all fixed by `calibrate` before this run.
    if args.half == "held":
        y = cal["youden"]
        theta, jbest, npairs, nchanged = y["theta"], y["j"], y["pairs"], y["changed"]
    else:
        theta, jbest, npairs, nchanged = dev_youden(evs)
    if abs(theta - cal["youden"]["theta"]) > 1e-9:
        raise SystemExit(f"Youden theta {theta} differs from calibration's {cal['youden']['theta']}")
    thetas = {"e": theta, **{v: c["theta"] for v, c in cal["chosen"].items()}}
    print(f"thetas {thetas} (Youden J {jbest:.3f} on {npairs} dev pairs, {nchanged} changed)")
    per = {}
    for e in evs:
        t0 = time.time()
        per[e["sid"]] = run_rules(e, thetas)
        print(f"rules {e['sid']} {time.time() - t0:.0f}s", flush=True)
    by_match = {}
    for e in evs:
        ls = [len(r["frames"]) for r in e["runs"]]
        by_match[e["sid"]] = {"split": e["split"], "openings": len(ls),
                              "samples": int(sum(ls)), "median": float(np.median(ls)),
                              "p90": float(np.quantile(ls, 0.9)), "max": int(max(ls)),
                              "single": int(sum(1 for x in ls if x == 1)),
                              "cache_frames": e["cache_frames"],
                              "cache_bytes": int(e["sizes"].sum())}
    summary = {"version": READS_VERSION, "half_run": args.half, "theta": theta,
               "thetas": thetas, "youden_j": jbest,
               "dev_pairs": npairs, "dev_pairs_changed": nchanged,
               "openings_per_match": per_match, "holds_per_match": holds,
               "by_match": by_match,
               "length_quantiles": {str(q): float(np.quantile(lengths, q))
                                    for q in (0.1, 0.25, 0.5, 0.75, 0.9, 0.99)},
               "length_mean": float(np.mean(lengths)), "openings": len(lengths),
               "single_sample_openings": int(sum(1 for x in lengths if x == 1)),
               "cache_frames": sum(e["cache_frames"] for e in evs),
               "cache_bytes": int(sum(int(e["sizes"].sum()) for e in evs)),
               "on_samples": sum(len(r["frames"]) for e in evs for r in e["runs"])}
    summary["reader_cost"] = reader_cost([e["sid"] for e in evs])
    tot = Counter()
    for v in changes.values():
        tot.update(v)
    summary["field_changes"] = dict(tot)
    summary["field_changes_by_session"] = changes
    summary["rules_by_session"] = {
        sid: {rule: {"frames": r["frames"], "differ": r["differ"]} for rule, r in p["rules"].items()}
        for sid, p in per.items()}
    for half in ("dev", "held", "all"):
        acc = {}
        for e in evs:
            if half != "all" and e["split"] != half:
                continue
            _merge(acc, {k: v for k, v in per[e["sid"]].items()
                         if k in ("rules", "base", "stored_dim_check")})
        summary[half] = acc
    examples = {sid: {rule: {"deaths": r["death_examples"][:20], "credits": r["credit_examples"][:10]}
                      for rule, r in p["rules"].items()} for sid, p in per.items()}
    lineup = {sid: {rule: r["lineup"] for rule, r in p["rules"].items()} for sid, p in per.items()}
    sfx = "" if args.half == "all" else f"-{args.half}"
    (out / f"summary{sfx}.json").write_text(json.dumps(summary, indent=1, default=str),
                                            encoding="utf-8")
    (out / f"examples{sfx}.json").write_text(json.dumps(examples, indent=1, default=str),
                                             encoding="utf-8")
    (out / f"lineup{sfx}.json").write_text(json.dumps(lineup, indent=1, default=str),
                                           encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("theta", "openings", "length_quantiles",
                                              "field_changes", "cache_frames", "cache_bytes")}))
    if args.record:
        if args.half != "all":
            raise SystemExit("--record needs the full run (--half all)")
        record_summary(summary, cal)
    return 0


def cmd_posthoc(args) -> int:
    """Score the post-hoc rules (`POST_HOC`) on every session, after the
    held half was seen; written apart (posthoc.json) and recorded with
    `post_hoc` true."""
    out = Path(args.out)
    acc = {"dev": {}, "held": {}}
    for sid in sessions():
        e = evaluate_session(sid, out)
        base = outputs(e["s"]["board"], e["s"], e["audit"], e["enemy"], e["runs"])
        for rule in POST_HOC:
            keep = keep_frames(e, rule, None)
            got = outputs(thin_rows(e["s"]["board"], set(keep)), e["s"], e["audit"],
                          e["enemy"], e["runs"])
            pos = [e["frame_pos"][f] for f in keep if f in e["frame_pos"]]
            c = compare(base, got, e["runs"])
            _merge(acc[e["split"]], {rule: {"frames": len(keep), "frames_in_cache": len(pos),
                                            "bytes": int(e["sizes"][pos].sum()),
                                            "cache_frames": e["cache_frames"],
                                            "cache_bytes": int(e["sizes"].sum()),
                                            "differ": n_differ(c), "credits": c["credits"],
                                            "deaths": c["deaths"], "kd_bound": c["kd_bound"],
                                            "lineup": c["lineup"], "local_row": c["local_row"]}})
        print(f"posthoc {sid} ({e['split']})", flush=True)
    (out / "posthoc.json").write_text(json.dumps(acc, indent=1), encoding="utf-8")
    print(json.dumps(acc))
    if args.record:
        from reticle import metrics
        deps = {"tool": READS_VERSION, "rules": "post-hoc: " + ",".join(POST_HOC),
                "split": "sha1 scoreboard_reads parity"}
        for half, rules in acc.items():
            for rule, r in rules.items():
                metrics.record("scoreboard_reads", part=f"posthoc-{rule}", session=f"{half}-half",
                               deps=deps, context={"post_hoc": True},
                               values={"frames": r["frames"], "cache_frames": r["cache_frames"],
                                       "gb": round(r["bytes"] / 1e9, 3),
                                       "cache_gb": round(r["cache_bytes"] / 1e9, 3),
                                       "outputs_differ": r["differ"]["total"],
                                       "outputs_lost": r["differ"]["lost"],
                                       "deaths_lost": r["deaths"].get("lost", 0),
                                       "credits_lost": r["credits"].get("lost", 0),
                                       "credits_gained": r["credits"].get("gained", 0)})
    return 0


def record_summary(summary: dict, cal: dict) -> None:
    from reticle import metrics
    deps = {"tool": READS_VERSION,
            "rules": "a0,a,b,c,d,e fixed 2026-10-04; e_cal,e_cred dev-calibrated",
            "split": "sha1 scoreboard_reads parity"}
    for var, curve in cal["curves"].items():
        ch = cal["chosen"][var]
        metrics.record("scoreboard_reads", part=f"calibration-{var}", session="dev-half",
                       deps=deps, values={"theta": ch["theta"], "frames": ch["frames"],
                                          "differ": ch["differ"], "on_samples": ch["on_samples"],
                                          "curve_points": len(curve)},
                       context={"curve": [[c["theta"], c["frames"], c["total"]] for c in curve],
                                "credit_bins": cal["credit_bins"]})
    fc = summary["field_changes"]
    n2 = max(1, fc["openings_with_two_accepted"])
    metrics.record("scoreboard_reads", part="openings", session="all-sessions", deps=deps,
                   values={"openings": summary["openings"],
                           "median_samples": summary["length_quantiles"]["0.5"],
                           "p90_samples": summary["length_quantiles"]["0.9"],
                           "openings_with_two_accepted": fc["openings_with_two_accepted"],
                           **{f"changed_{f}_frac": round(fc[f] / n2, 4) for f in FIELDS + ("any",)},
                           "cache_frames": summary["cache_frames"],
                           "cache_gb": round(summary["cache_bytes"] / 1e9, 3),
                           "theta": round(summary["theta"], 4)})
    for half in ("held", "dev"):
        for rule, r in summary[half]["rules"].items():
            base = summary[half]["base"]
            dth = r.get("deaths", {})
            vals = {"frames": r["frames"], "gb": round(r["bytes"] / 1e9, 3),
                    "outputs_differ": r["differ"]["total"],
                    "deaths_same": dth.get("same", 0), "deaths_lost": dth.get("lost", 0),
                    "deaths_gained": dth.get("gained", 0), "deaths_changed": dth.get("changed", 0),
                    "deaths_named_all": base["deaths_named"],
                    "credits_same": r["credits"].get("same", 0),
                    "credits_lost": r["credits"].get("lost", 0),
                    "credits_gained": r["credits"].get("gained", 0),
                    "credits_changed": r["credits"].get("changed", 0),
                    "credits_resolved_all": base["credits_resolved"],
                    "lineup_same": r["lineup"].get("same", 0),
                    "lineup_changed": sum(r["lineup"].get(k, 0) for k in ("lost", "gained", "changed")),
                    "kd_changed": r["kd_bound"].get("changed", 0),
                    "kd_rounds": sum(r["kd_bound"].values())}
            metrics.record("scoreboard_reads", part=f"rule-{rule}", session=f"{half}-half",
                           deps=deps, values=vals,
                           context={"theta": round(summary["thetas"].get(rule, 0.0), 4)})


def _write_frames(sid: str, frames: set[int], prefix: str, out: Path) -> list[str]:
    """Write the cached crops at `frames` (board rows only) as PNG in `out`.

    `board_y` gives frame rows; the crop starts at the cache rect's top, so
    the slice subtracts it, as `small_frames` does."""
    rec = json.loads((CACHE / f"{sid}.json").read_text(encoding="utf-8"))
    idx = np.load(CACHE / f"{sid}.idx.npy")
    y0r = rec["rects"][0][1]
    y0, y1 = board_y()
    names = []
    cap = _cap(CACHE / f"{sid}.r0.mkv")
    try:
        for _t, f, _k, _n, _ in idx:
            ok, crop = cap.read()
            if ok and int(f) in frames:
                name = f"{prefix}_f{int(f)}.png"
                cv2.imwrite(str(out / name), crop[max(0, y0 - y0r):y1 - y0r])
                names.append(name)
    finally:
        cap.release()
    return names


def cmd_crops(args) -> int:
    """Write the cached frames behind the first `--n` disagreements of rule
    `--rule`, deaths first then credits, alternating sessions: for a death
    the openings each side bracketed it with, for a credit the first frame of
    the all-frames opening and the frame the rule read."""
    out = Path(args.out)
    ex = json.loads((out / "examples.json").read_text(encoding="utf-8"))
    deaths = [(sid, "death", d) for sid, r in ex.items() for d in r.get(args.rule, {}).get("deaths", [])
              if d.get("kind") in ("lost", "gained", "changed")]
    credit = [(sid, "credit", d) for sid, r in ex.items() for d in r.get(args.rule, {}).get("credits", [])]
    picked = deaths[: (args.n + 1) // 2] + credit[: args.n // 2]
    for sid, kind, d in picked:
        idx = np.load(CACHE / f"{sid}.idx.npy")
        if kind == "death":
            frames = {x for x in d["all"][2:] + d["rule"][2:] if x is not None}
        else:
            ts = {d["t_ms"], d["t_end_ms"], d.get("rule_t_ms")}
            frames = {int(f) for t, f, *_ in idx if float(t) in ts}
        names = _write_frames(sid, frames, f"{args.rule}_{kind}_{sid}_{int(d['t_ms'])}", out)
        print(json.dumps({"sid": sid, "kind": kind, **d, "crops": names}))
    return 0


def cmd_thin_check(args) -> int:
    """Run the thinning procedure on a copy in `--out` and read it back."""
    from reticle.store import Store
    out = Path(args.out).resolve()
    if CACHE.resolve() in out.parents or out == CACHE.resolve():
        raise SystemExit("thin-check writes a copy; give an --out outside the cache")
    st = Store(STORE)
    runs = strip_runs(st.read_events("scoreboard", args.session),
                      st.read_events("scoreboard_strip", args.session))
    if args.rule in ("a", "b", "c", "d") + POST_HOC:
        keep = {f for r in runs for f in select(r["frames"], args.rule)}
    else:
        px_dir = Path(args.pixels)
        cal = json.loads((px_dir / "calibration.json").read_text(encoding="utf-8"))
        px = json.loads((px_dir / f"{args.session}.pixels.json").read_text(encoding="utf-8"))
        cp = px_dir / f"{args.session}.cols.json"
        dm = diff_maps(px, json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else None)
        theta = cal["youden"]["theta"] if args.rule == "e" else cal["chosen"][args.rule]["theta"]
        keep = {f for r in runs for f in select(r["frames"], args.rule, dm[args.rule], theta)}
    got = thin_copy(args.session, keep, out / "thinned")
    got.update(check_thin_copy(args.session, out / "thinned"))
    print(json.dumps(got))
    if args.record:
        from reticle import metrics
        metrics.record("scoreboard_reads", part=f"thin-check-{args.rule}", session=args.session,
                       deps={"tool": READS_VERSION, "procedure": "decode, re-encode kept frames FFV1 level 3 bgr0"},
                       values=got, context={"post_hoc": args.rule in POST_HOC, "copy": True})
    return 0


# ------------------------------------------------------------------ migration

#: Where `migrate` writes each thinned cache before it replaces the stored one.
MIGRATE_DIR = CACHE.parent / f"{CACHE.name}.thinning"
#: Free bytes the store's drive keeps through a migration.
MIN_FREE = 15e9
#: Every this many held times one is asked of both caches through
#: `RoiCache.samples`, so the thinned file is read with seeks.
SEEK_EVERY = 5


def _gate_core(g: dict | None) -> dict | None:
    """A gate record without the `rule` name, which records written before it
    lack: what two gates must share to be the same gate."""
    return None if g is None else {k: v for k, v in g.items() if k != "rule"}


def load_checks(sid: str, src: Path, dst: Path, man: dict, strip_rows: list[dict]) -> dict:
    """The thinned cache in `dst` read through `RoiCache` beside the stored
    one in `src`: it loads, holds exactly its index times, refuses every
    dropped time as `thinned_out` and every strip sample outside the old gate
    as `outside_gate`, and every `SEEK_EVERY`th held time yields the stored
    cache's pixels."""
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    prof = get_profile(man["source_profile"])
    new, why = RoiCache._open(dst, man, prof)
    old, why_old = RoiCache._open(src, man, prof)
    if new is None or old is None:
        return {"ok": False, "load": why or why_old}
    held = new.holds()
    dropped = sorted(set(old.holds()) - set(held))
    before = old.record["gate"]["spans"]
    from reticle.roi_cache import spans_mask
    st = np.array(sorted(float(r["t_ms"]) for r in strip_rows if r.get("kind") == "sample"))
    outside = st[~spans_mask(st, before)] if len(st) else st
    ref = Counter(new.refusal(t) for t in dropped)
    ref_held = Counter(new.refusal(t) for t in held)
    ref_out = Counter(new.refusal(float(t)) for t in outside)
    asked = held[::SEEK_EVERY]
    seek_same = sum(np.array_equal(a.frame, b.frame) and a.frame_idx == b.frame_idx
                    for a, b in zip(new.samples(asked), old.samples(asked)))
    out = {"held": len(held), "dropped": len(dropped),
           "refusal_dropped": dict(ref), "refusal_held": dict(ref_held),
           "refusal_outside_old_gate": dict(ref_out), "seek_asked": len(asked),
           "seek_same": int(seek_same)}
    out["ok"] = (ref == Counter({"thinned_out": len(dropped)})
                 and ref_held == Counter({None: len(held)})
                 and ref_out == Counter({"outside_gate": len(outside)})
                 and seek_same == len(asked))
    return out


def consumer_checks(sid: str, kept: set[int]) -> dict:
    """Every consumer output (`outputs`) on the stored rows thinned to the
    frames the thinned cache holds, against all frames: `ok` only where none
    differs (`n_differ` total 0, gains included)."""
    from reticle.reconciliation import board_alive_auditor
    s = load(sid)
    runs = strip_runs(s["board"], s["strip"])
    audit = board_alive_auditor(s["hud"], s["roster"])
    enemy = enemy_named(sid)
    base = outputs(s["board"], s, audit, enemy, runs)
    got = outputs(thin_rows(s["board"], kept), s, audit, enemy, runs)
    c = compare(base, got, runs)
    d = n_differ(c)
    return {"ok": d["total"] == 0, "differ": d, "lineup": c["lineup"], "credits": c["credits"],
            "local_row": c["local_row"], "deaths": c["deaths"], "kd_bound": c["kd_bound"],
            "credit_examples": c["credit_examples"][:8], "death_examples": c["death_examples"][:8]}


def _swap_in(sid: str, src: Path, dst: Path) -> list[tuple[Path, Path]]:
    """Move the stored cache files aside (`.pre-thin`) and the thinned ones
    into `src`; returns (stored, aside) pairs for `_restore`."""
    names = [f"{sid}.json", f"{sid}.idx.npy", f"{sid}.r0.mkv"]
    aside = []
    for n in names:
        if (src / n).is_file():
            os.replace(src / n, src / f"{n}.pre-thin")
            aside.append((src / n, src / f"{n}.pre-thin"))
    for n in names:
        if (dst / n).is_file():
            os.replace(dst / n, src / n)
    return aside


def _restore(aside: list[tuple[Path, Path]]) -> None:
    for path, back in aside:
        os.replace(back, path)


def migrate_session(sid: str, replace: bool) -> dict:
    """Thin one session's scoreboard cache to rule `on` beside the store
    (`MIGRATE_DIR`), check it, and with `replace` put it in place of the
    stored cache. Every check must pass before the stored cache is touched:
    the stored gate is the margin-1 strip gate the stored strip rows give,
    the margin-0 gate keeps exactly rule `on`'s frames, every kept frame
    reads back bit for bit, `RoiCache` serves it with the right refusals, and
    every consumer output equals all frames'. A failed session keeps its
    cache and its thinned copy is removed."""
    import shutil
    from reticle.roi_cache import (compare_thinned, scoreboard_gate, spans_mask,
                                   stored_record, thin_cache)
    from reticle.store import Store
    st = Store(STORE)
    rec = stored_record(STORE, sid, "scoreboard")
    res = {"sid": sid, "frames_before": rec.get("frames"),
           "bytes_before": int((CACHE / f"{sid}.r0.mkv").stat().st_size)
           if (CACHE / f"{sid}.r0.mkv").is_file() else 0, "replaced": False}
    if rec.get("thinned") is not None:
        return {**res, "status": "already_thinned"}
    strip, board = st.read_events("scoreboard_strip", sid), st.read_events("scoreboard", sid)
    old_gate, why = scoreboard_gate(strip, margin=1)
    if old_gate is None or _gate_core(old_gate) != _gate_core(rec.get("gate")):
        return {**res, "status": "failed", "failed": "stored_gate",
                "why": why or "the stored gate is not the margin-1 gate of the stored strip rows"}
    gate, why = scoreboard_gate(strip)
    idx = np.load(CACHE / f"{sid}.idx.npy")
    gate_frames = set(idx[spans_mask(idx[:, 0], gate["spans"]), 1].astype(int).tolist())
    on_frames = {f for r in strip_runs(board, strip) for f in select(r["frames"], "on")}
    res["frames_rule_on"] = len(on_frames)
    if gate_frames != on_frames:
        return {**res, "status": "failed", "failed": "gate_is_not_rule_on",
                "only_gate": len(gate_frames - on_frames), "only_rule": len(on_frames - gate_frames)}
    free = shutil.disk_usage(STORE).free
    if free - res["bytes_before"] < MIN_FREE:
        return {**res, "status": "failed", "failed": "disk", "free": free}
    try:
        res.update(thin_cache(CACHE, sid, gate, MIGRATE_DIR, f"{READS_VERSION} migrate"))
        res["bits"] = compare_thinned(CACHE, MIGRATE_DIR, sid)
        b = res["bits"]
        bits_ok = (b["index_ok"] and not b["extra_frames"] and b["different"] == 0
                   and b["identical"] == b["checked"] == res["frames_kept"])
        man = st.read_manifest(sid)
        res["load"] = load_checks(sid, CACHE, MIGRATE_DIR, man, strip)
        kept = set(np.load(MIGRATE_DIR / f"{sid}.idx.npy")[:, 1].astype(int).tolist())
        res["consumers"] = consumer_checks(sid, kept)
        failed = [k for k, ok in (("bits", bits_ok), ("load", res["load"]["ok"]),
                                  ("consumers", res["consumers"]["ok"])) if not ok]
        if failed:
            return {**res, "status": "failed", "failed": ",".join(failed)}
        if not replace:
            return {**res, "status": "checked"}
        aside = _swap_in(sid, CACHE, MIGRATE_DIR)
        try:
            from reticle.profiles import get_profile
            from reticle.roi_cache import RoiCache
            got, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "scoreboard")
            if (got is None or got.record.get("thinned") is None
                    or got.holds() != sorted(float(t) for t in idx[spans_mask(idx[:, 0],
                                                                              gate["spans"]), 0])):
                raise RuntimeError(f"the swapped cache does not load as thinned: {why}")
        except Exception:
            for n in (f"{sid}.json", f"{sid}.idx.npy", f"{sid}.r0.mkv"):
                if (CACHE / n).is_file():
                    os.replace(CACHE / n, MIGRATE_DIR / n)
            _restore(aside)
            raise
        for _path, back in aside:
            back.unlink()
        res["replaced"] = True
        return {**res, "status": "replaced"}
    finally:
        for n in (f"{sid}.json", f"{sid}.idx.npy", f"{sid}.r0.mkv", f"{sid}.r0.part.mkv"):
            (MIGRATE_DIR / n).unlink(missing_ok=True)


def cmd_migrate(args) -> int:
    """Thin each session's stored scoreboard cache to rule `on`, one session
    at a time (`migrate_session`), and record a ledger row per session and
    one for the run."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid in args.sessions or sessions():
        t0 = time.time()
        r = migrate_session(sid, args.replace)
        r["seconds"] = round(time.time() - t0, 1)
        rows.append(r)
        (out / f"{sid}.migrate.json").write_text(json.dumps(r, indent=1, default=str),
                                                 encoding="utf-8")
        print(json.dumps({k: r.get(k) for k in ("sid", "status", "failed", "frames_before",
                                                "frames_kept", "bytes_before", "bytes_after",
                                                "seconds")}), flush=True)
        if args.record:
            from reticle import metrics
            c = r.get("consumers") or {}
            metrics.record("scoreboard_reads",
                           part="migrate-on" if args.replace else "migrate-check-on", session=sid,
                           deps={"tool": READS_VERSION, "rule": "on",
                                 "procedure": "roi_cache.thin_cache, FFV1 level 3 bgr0"},
                           context={"status": r["status"], "failed": r.get("failed"),
                                    "differ": c.get("differ"), "credits": c.get("credits"),
                                    "load": {k: v for k, v in (r.get("load") or {}).items()
                                             if k != "ok"}},
                           values={"frames_before": r.get("frames_before") or 0,
                                   "frames_kept": r.get("frames_kept") or 0,
                                   "bytes_before": r.get("bytes_before") or 0,
                                   "bytes_after": r.get("bytes_after") or 0,
                                   "replaced": int(bool(r.get("replaced"))),
                                   "outputs_differ": (c.get("differ") or {}).get("total", 0)})
    done = [r for r in rows if r.get("replaced")]
    passed = [r for r in rows if r["status"] in ("checked", "replaced")]
    total = {"sessions": len(rows), "passed": len(passed), "replaced": len(done),
             "failed": sum(r["status"] == "failed" for r in rows),
             "bytes_all": sum(r["bytes_before"] for r in rows),
             "bytes_freed": sum(r["bytes_before"] - r.get("bytes_after", 0) for r in done),
             "bytes_freed_if_passed_replaced": sum(r["bytes_before"] - r.get("bytes_after", 0)
                                                   for r in passed),
             "bytes_freed_if_all_replaced": sum(r["bytes_before"] - r.get("bytes_after", 0)
                                                for r in rows if "bytes_after" in r)}
    print(json.dumps(total))
    if args.record:
        from reticle import metrics
        metrics.record("scoreboard_reads", part="migrate-on" if args.replace else "migrate-check-on",
                       session=f"corpus-{len(rows)}",
                       deps={"tool": READS_VERSION, "rule": "on"},
                       values={**total, "gb_freed": round(total["bytes_freed"] / 1e9, 3),
                               "gb_freed_if_passed_replaced":
                                   round(total["bytes_freed_if_passed_replaced"] / 1e9, 3)},
                       context={"failed_sessions": [r["sid"] for r in rows
                                                    if r["status"] == "failed"]})
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pixels")
    a.add_argument("--out", required=True)
    a.add_argument("--cols", action="store_true",
                   help="per-column-bin differences instead (NAME.cols.json)")
    a.add_argument("sessions", nargs="*")
    ph = sub.add_parser("posthoc")
    ph.add_argument("--out", required=True)
    ph.add_argument("--record", action="store_true")
    k = sub.add_parser("calibrate")
    k.add_argument("--out", required=True)
    b = sub.add_parser("eval")
    b.add_argument("--out", required=True)
    b.add_argument("--half", default="all", choices=("all", "dev", "held"))
    b.add_argument("--record", action="store_true")
    c = sub.add_parser("crops")
    c.add_argument("--out", required=True)
    c.add_argument("--rule", default="a")
    c.add_argument("--n", type=int, default=6)
    t = sub.add_parser("thin-check")
    t.add_argument("--out", required=True)
    t.add_argument("--rule", default="d", choices=("a", "b", "c", "d", "e") + VARIANTS + POST_HOC)
    t.add_argument("--record", action="store_true")
    t.add_argument("--pixels", help="the pixels/calibrate output directory (rule e)")
    t.add_argument("session")
    m = sub.add_parser("migrate")
    m.add_argument("--out", required=True, help="per-session check results (JSON)")
    m.add_argument("--replace", action="store_true",
                   help="put each checked thinned cache in place of the stored one")
    m.add_argument("--record", action="store_true")
    m.add_argument("sessions", nargs="*")
    args = p.parse_args(argv)
    below_normal()
    return {"pixels": cmd_pixels, "calibrate": cmd_calibrate, "eval": cmd_eval,
            "posthoc": cmd_posthoc,
            "crops": cmd_crops,
            "thin-check": cmd_thin_check, "migrate": cmd_migrate}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
