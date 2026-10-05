r"""How many Tab scoreboard frames each opening needs, measured on stored rows.

    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py pixels --out DIR [SID ...]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py eval --out DIR [--record]
    .\.venv\Scripts\python.exe prototypes\scoreboard_reads.py crops --out DIR [--n 6]

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
the stored streams; `crops` writes the cached frames behind the first
disagreements for inspection.

Owns nothing: a measurement. Wire: no (the player decides on the numbers).
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
#: The cached crop shrunk this many times (INTER_AREA) before differencing.
DIFF_SCALE = 4
#: Frame rows the two five-row blocks can reach: the strip's marker lines
#: (`scoreboard_strip.ROW_Y`) less and plus the gap to each block and the
#: tallest block the reader accepts (`scoreboard.MAX_BLOCK_H`).


def board_y() -> tuple[int, int]:
    from reticle import scoreboard as sb, scoreboard_strip as st
    return (st.ROW_Y[0] - sb.STRIP_ALLY_GAP - sb.MAX_BLOCK_H,
            st.ROW_Y[1] + sb.STRIP_ENEMY_GAP + sb.MAX_BLOCK_H)


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
    if rule == "all":
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
    if rule == "e":
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

    def run_of(t):
        for r in runs:
            if r["t_first_ms"] - 500 <= t <= r["t_last_ms"] + 500:
                return r["run"]
        return None
    key = lambda c: (run_of(c["t_start_ms"]), c["team"], c["display_row"])  # noqa: E731
    gk = {}
    for c in got["credits"]:
        gk.setdefault(key(c), c)
    cr, ident, details = Counter(), Counter(), []
    for c in base["credits"]:
        g = gk.get(key(c))
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
    """The thinning procedure, run on a COPY: remux the kept frames' FFV1
    packets of a session's scoreboard cache into `dst` (a directory outside
    the store) without decoding, and write the index and record a thinned
    cache would carry. Every FFV1 frame is a key frame, so a packet stands
    alone; packets are renumbered so a kept frame's position in the new file
    is its index row's offset column.

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
    with av.open(str(CACHE / f"{sid}.r0.mkv")) as src, av.open(str(out_path), "w") as out:
        s_in = src.streams.video[0]
        s_out = out.add_stream_from_template(s_in)
        n_out, n_in = 0, 0
        for pkt in src.demux(s_in):
            if pkt.size == 0:
                continue
            if n_in in keep_pos:
                step = pkt.duration or 1
                pkt.pts = pkt.dts = n_out * step
                pkt.stream = s_out
                out.mux(pkt)
                n_out += 1
            n_in += 1
    new_idx = idx[pos].copy()
    new_idx[:, 3] = np.arange(len(pos))
    np.save(dst / f"{sid}.idx.npy", new_idx)
    record = {**rec, "frames": len(pos), "bytes": out_path.stat().st_size,
              "thinned": {"tool": READS_VERSION, "frames_before": int(len(idx)),
                          "frames_kept": len(pos)}}
    (dst / f"{sid}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"frames_before": int(len(idx)), "frames_kept": len(pos),
            "bytes_before": int((CACHE / f"{sid}.r0.mkv").stat().st_size),
            "bytes_after": int(out_path.stat().st_size), "packets_in": n_in}


def check_thin_copy(sid: str, dst: Path, sample: int = 12) -> dict:
    """Read `sample` kept frames back from the thinned copy through OpenCV
    and compare them, bit for bit, with the same frames of the stored cache."""
    new_idx = np.load(dst / f"{sid}.idx.npy")
    old_idx = np.load(CACHE / f"{sid}.idx.npy")
    old_pos = {int(f): i for i, f in enumerate(old_idx[:, 1])}
    picks = np.linspace(0, len(new_idx) - 1, min(sample, len(new_idx))).astype(int)
    a, b = _cap(dst / f"{sid}.r0.mkv"), _cap(CACHE / f"{sid}.r0.mkv")
    same = 0
    try:
        for j in picks:
            a.set(cv2.CAP_PROP_POS_FRAMES, int(new_idx[j, 3]))
            b.set(cv2.CAP_PROP_POS_FRAMES, old_pos[int(new_idx[j, 1])])
            ok1, x = a.read()
            ok2, y = b.read()
            same += bool(ok1 and ok2 and np.array_equal(x, y))
    finally:
        a.release()
        b.release()
    return {"checked": len(picks), "identical": same}


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
    return {"sid": sid, "split": split(sid), "s": s, "runs": runs, "states": states,
            "audit": audit, "enemy": enemy, "diffs": diffs, "labels": labels,
            "frame_pos": frame_pos, "sizes": np.array(px["packet_sizes"], np.int64),
            "cache_frames": len(idx)}


def run_rules(e: dict, theta: float) -> dict:
    s, runs = e["s"], e["runs"]
    base = outputs(s["board"], s, e["audit"], e["enemy"], runs)
    res = {"stored_dim_check": Counter(), "rules": {}}
    sd = stored_dim(s)
    for d in base["deaths"]:
        res["stored_dim_check"][_cmp(sd.get(d["death_id"]), d["agent"])] += 1
    for rule in RULES[1:]:
        keep = sorted({f for r in runs for f in select(r["frames"], rule, e["diffs"], theta)})
        rows = thin_rows(s["board"], set(keep))
        got = outputs(rows, s, e["audit"], e["enemy"], runs)
        pos = [e["frame_pos"][f] for f in keep if f in e["frame_pos"]]
        res["rules"][rule] = {"frames": len(keep), "frames_in_cache": len(pos),
                              "bytes": int(e["sizes"][pos].sum()) if pos else 0,
                              **compare(base, got, runs)}
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


def cmd_eval(args) -> int:
    out = Path(args.out)
    below_normal()
    evs = []
    for sid in sessions():
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
    # Theta on the dev half.
    d, y = [], []
    for e in evs:
        if e["split"] != "dev":
            continue
        for f, lab in e["labels"].items():
            if f in e["diffs"]:
                d.append(e["diffs"][f])
                y.append(lab)
    theta, jbest = youden_theta(np.array(d), np.array(y, bool))
    print(f"theta {theta:.3f} (Youden J {jbest:.3f} on {len(d)} dev pairs, {int(np.sum(y))} changed)")
    per = {}
    for e in evs:
        t0 = time.time()
        per[e["sid"]] = run_rules(e, theta)
        print(f"rules {e['sid']} {time.time() - t0:.0f}s", flush=True)
    summary = {"version": READS_VERSION, "theta": theta, "youden_j": jbest,
               "dev_pairs": len(d), "dev_pairs_changed": int(np.sum(y)),
               "openings_per_match": per_match, "holds_per_match": holds,
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
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (out / "examples.json").write_text(json.dumps(examples, indent=1, default=str), encoding="utf-8")
    (out / "lineup.json").write_text(json.dumps(lineup, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("theta", "openings", "length_quantiles",
                                              "field_changes", "cache_frames", "cache_bytes")}))
    if args.record:
        record(summary)
    return 0


def record(summary: dict) -> None:
    from reticle import metrics
    deps = {"tool": READS_VERSION, "rules": "a0,a,b,c,d,e fixed 2026-10-04",
            "split": "sha1 scoreboard_reads parity"}
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
                           deps=deps, values=vals, context={"theta": round(summary["theta"], 4)})


def _write_frames(sid: str, frames: set[int], prefix: str, out: Path) -> list[str]:
    """Write the cached crops at `frames` (board rows only) as PNG in `out`."""
    idx = np.load(CACHE / f"{sid}.idx.npy")
    y0, y1 = board_y()
    names = []
    cap = _cap(CACHE / f"{sid}.r0.mkv")
    try:
        for _t, f, _k, _n, _ in idx:
            ok, crop = cap.read()
            if ok and int(f) in frames:
                name = f"{prefix}_f{int(f)}.png"
                cv2.imwrite(str(out / name), crop[y0:y1])
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
    keep = {f for r in runs for f in select(r["frames"], args.rule)}
    got = thin_copy(args.session, keep, out / "thinned")
    got.update(check_thin_copy(args.session, out / "thinned"))
    print(json.dumps(got))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pixels")
    a.add_argument("--out", required=True)
    a.add_argument("sessions", nargs="*")
    b = sub.add_parser("eval")
    b.add_argument("--out", required=True)
    b.add_argument("--record", action="store_true")
    c = sub.add_parser("crops")
    c.add_argument("--out", required=True)
    c.add_argument("--rule", default="a")
    c.add_argument("--n", type=int, default=6)
    t = sub.add_parser("thin-check")
    t.add_argument("--out", required=True)
    t.add_argument("--rule", default="d", choices=("a", "b", "c", "d"))
    t.add_argument("session")
    args = p.parse_args(argv)
    below_normal()
    return {"pixels": cmd_pixels, "eval": cmd_eval, "crops": cmd_crops,
            "thin-check": cmd_thin_check}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
