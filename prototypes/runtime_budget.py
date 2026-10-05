r"""The real-time budget: what each reader costs per second of play, from stored usage.

    .\.venv\Scripts\python.exe prototypes\runtime_budget.py [--record] [--json OUT]

Reads stored data only: the manifests, the stored rounds, `notes/usage.jsonl`
(`reticle/usage.py`'s scan and command records), `notes/metrics.jsonl`, and
`live_load`'s logs under `analysis/live-load-0.1.0-20261004/`. It decodes
nothing and runs no reader. `--record` appends the `runtime_budget/*` rows
(session `corpus-21`); `--json` refuses a path inside the store.

The question
------------
The player accepts about a 20% FPS cost for analysis during play, nothing
shown mid-match, post-round and post-game work allowed after
(docs/FRAMETIME_PROTOCOL.md). A level passes the protocol when both FPS costs
are at most 20% AND the load harness keeps pace on one Below Normal thread
(stored over wall seconds at least 0.98, call lateness p95 at most 1 s). The
FPS cost needs the player's session and is unmeasured. The pace and lag rules
are computable: the mean live load must stay under 980 ms of CPU per second of
play, and the load inside a round under 1000, since a round lasts far longer
than the 1 s of lateness the lag rule allows.

Method
------
Matches are sessions longer than 15 minutes with stored rounds:
[metric:runtime_budget/live@corpus-21#matches=21] of them,
[metric:runtime_budget/live@corpus-21#rounds=439] rounds,
[metric:runtime_budget/live@corpus-21#play_h=12.19] h of play
(0f08b3dc3777 is long but has neither rounds nor a HUD scan). For each match
and reader, the latest completed whole-capture scan gives the mean call (feed
wall), a p95 call estimated from the usage histogram (the bucket above 100 ms
is open, so its tail is modelled as an exponential excess; an estimate, not a
measured percentile), and the gate: frames fed over rate times capture, the
share of play the reader is offered a frame. Mean ms per second of play =
mean call x live rate x gate; inside a round the gate is open.

Usage wall is not one-thread CPU: the scans ran with a 4- or 12-thread
OpenCV pool beside other load. `live_load` measured one-thread CPU per call
on 043bafca271a (capture `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`);
over the usage wall of the same reader on that session it gives cpu/wall
[metric:runtime_budget/readers@corpus-21#killfeed_portrait_cpu_over_wall=1.17]
(killfeed) to [metric:runtime_budget/readers@corpus-21#ping_cpu_over_wall=1.82]
(ping), and each reader is charged the larger of wall and calibrated CPU. One
session calibrates all 21; `ability` and `ability_icon` (5 matches),
`combat_report` (1) and `tray` (`live_load` only) carry no calibration.

Results, 2026-10-04 (runtime-budget-0.1.0)
-----------------------------------------
Live: feeds the minimap and HUD state while it is visible. Charged CPU ms per
second of play, mean over matches; the gate is the share of play it reads.

    ally_icon      15 Hz  [metric:runtime_budget/readers@corpus-21#ally_icon_ms_per_s=850.0]
                   p95 match [metric:runtime_budget/readers@corpus-21#ally_icon_p95_ms_per_s=1593.2],
                   in a round [metric:runtime_budget/readers@corpus-21#ally_icon_in_round_ms_per_s=1568.3],
                   gate [metric:runtime_budget/readers@corpus-21#ally_icon_open_share=0.54],
                   calls over 100 ms [metric:runtime_budget/readers@corpus-21#ally_icon_over_100ms_share=0.167]
    killfeed       2 Hz   [metric:runtime_budget/readers@corpus-21#killfeed_portrait_ms_per_s=132.9]
    ability_icon   2 Hz   [metric:runtime_budget/readers@corpus-21#ability_icon_ms_per_s=100.5]
    minimap (self) 15 Hz  [metric:runtime_budget/readers@corpus-21#minimap_ms_per_s=88.5]
    hud            2 Hz   [metric:runtime_budget/readers@corpus-21#hud_ms_per_s=70.4]
    ability        2 Hz   [metric:runtime_budget/readers@corpus-21#ability_ms_per_s=63.6]
    scoreboard     2 Hz   [metric:runtime_budget/readers@corpus-21#scoreboard_ms_per_s=58.4]
    minimap_dark   4 Hz   [metric:runtime_budget/readers@corpus-21#minimap_dark_ms_per_s=52.7]
    ping           10 Hz  [metric:runtime_budget/readers@corpus-21#ping_ms_per_s=28.7]
    combat_report  1 Hz   [metric:runtime_budget/readers@corpus-21#combat_report_ms_per_s=10.6]
    tray, roster   2 Hz   [metric:runtime_budget/readers@corpus-21#tray_ms_per_s=1.0],
                          [metric:runtime_budget/readers@corpus-21#roster_ms_per_s=0.9]

Total [metric:runtime_budget/live@corpus-21#live_ms_per_s=1458.2] ms/s
(p95 match [metric:runtime_budget/live@corpus-21#live_p95_ms_per_s=2308.5]),
inside a round [metric:runtime_budget/live@corpus-21#live_in_round_ms_per_s=2308.4]
(p95 match [metric:runtime_budget/live@corpus-21#live_in_round_p95_ms_per_s=3949.9]);
the minimap set [metric:runtime_budget/live@corpus-21#minimap_ms_per_s=1184.0],
the HUD set [metric:runtime_budget/live@corpus-21#hud_ms_per_s=274.3]. Today's
live set needs [metric:runtime_budget/live@corpus-21#mean_share_of_one_thread=1.46]
threads on average and
[metric:runtime_budget/live@corpus-21#in_round_share_of_one_thread=2.31] inside
a round: it fails both computable rules. The harness agrees: its `full`
level demanded 1.48 cores on a 120 s window (`full_bn.json` beside the
`live_load` logs).

Gated on opportunity. The minimap readers run only inside their spans (gates
above). The killfeed panel holds an entry in
[metric:killfeed_panel/gate-projection#open_share=0.2642] of HUD samples, but
the reader reads every sample; an empty panel costs
[metric:killfeed_prior/cost@5822b6646448#ms_portrait_reader_0_entries=5.25] ms
and one entry [metric:killfeed_prior/cost@5822b6646448#ms_portrait_reader_1_entry=55.77].
The scoreboard is open in [metric:scoreboard/openings@all-sessions#open_fraction=0.322]
of samples; an open read costs
[metric:scoreboard/speed-batch@a06f04a0059f#ms_open_mean_cur=55.2] ms and a
closed check [metric:scoreboard/speed-batch@a06f04a0059f#ms_closed_mean_cur=15.0],
so per opening it costs [metric:runtime_budget/live@corpus-21#scoreboard_ms_per_s=55.9]
ms/s, [metric:runtime_budget/live@corpus-21#scoreboard_open_ms_per_s=35.5] of it
in open reads, and [metric:runtime_budget/live@corpus-21#scoreboard_gated_ms_per_s=40.5]
with the strip test as its closed gate. The audio witness runs once per round
end: [metric:runtime_budget/post@corpus-21#audio_ms_per_round_end=1953.0] ms, an
upper bound ([metric:runtime_budget/live@corpus-21#audio_ms_per_s=19.5] ms/s).

Post-round and post-game: the stored-data commands, each match's latest run,
CPU. Per round they need
[metric:runtime_budget/post@corpus-21#post_round_cpu_s=25.0] s of CPU with the
audio witness, against a median gap between rounds of
[metric:runtime_budget/post@corpus-21#round_gap_s_median=7.5] s: they do not fit
the gap. Spread over the next round
([metric:runtime_budget/post@corpus-21#round_s_median=86.5] s) they add
[metric:runtime_budget/post@corpus-21#post_round_over_next_round_ms_per_s=289.5]
ms/s. The largest are `spike`
([metric:runtime_budget/post@corpus-21#spike_cpu_s_per_match=203.6] s per match,
11 matches) and `round-outcome`
([metric:runtime_budget/post@corpus-21#round_outcome_cpu_s_per_match=114.3]).
After the game, `vision` takes
[metric:runtime_budget/post@corpus-21#vision_cpu_s_per_match=1135.4] s of CPU,
of [metric:runtime_budget/post@corpus-21#post_game_cpu_s=1307.7] in all.

The five largest live costs
---------------------------
1. `ally_icon` buys teammates' positions and names. Against Riot truth over the
   21 matches it matched [metric:riot_truth/minimap/all#reader_matched=7647] of
   [metric:riot_truth/minimap/all#riot_allies=10445] living teammates at kill
   frames and named [metric:riot_truth/minimap/all#id_right=6561] right,
   [metric:riot_truth/minimap/all#id_wrong=792] wrong. Cheapest cut: 15 to 5
   Hz. On the player's labels 5 Hz names
   [metric:ally_rate/labels@five-sessions#right_5=40] of
   [metric:ally_rate/labels@five-sessions#labels=57] as 15 Hz does
   ([metric:ally_rate/labels@five-sessions#right_15=40]; wrong
   [metric:ally_rate/labels@five-sessions#wrong_5=1] against
   [metric:ally_rate/labels@five-sessions#wrong_15=0]) for
   [metric:ally_rate/speed@a06f04a0059f#speedup_cpu=1.74] times less CPU:
   saves [metric:runtime_budget/top5@corpus-21#rank1_saving_ms_per_s=361.5] ms/s.
   Prior-first `ally-prior-0.2.0` costs at most
   [metric:ally_prior/riot_pool@heldout6#priced_share_max=0.3852] of the full
   reader and locates [metric:ally_prior/riot_pool@heldout6#located_share=0.8678]
   of held-out teammates against the ring fits'
   [metric:ally_prior/riot_pool@heldout6#ring_located_share=0.7968]: saves
   [metric:runtime_budget/top5@corpus-21#rank1_then_saving_ms_per_s=522.6] ms/s.
2. `killfeed_portrait` buys every kill: recall
   [metric:riot_truth/deaths#recall=0.9955], victims right
   [metric:riot_truth/deaths#victim_right_of_named=0.9988] and weapons
   [metric:riot_truth/deaths#weapon_right_of_named=0.9997] of those named.
   Cheapest cut: read a non-empty panel only when it changed;
   [metric:killfeed_prior/derived@eight#unchanged_share_nonempty=0.567] of
   non-empty samples are unchanged. Saves at most
   [metric:runtime_budget/top5@corpus-21#rank2_saving_ms_per_s=70.3] ms/s (the
   change test that replaces the read is unpriced).
3. `ability_icon` buys ability icons on the minimap: it finds
   [metric:ability_icons/bench@player-labels#hits=123] of
   [metric:ability_icons/bench@player-labels#targets=151] labelled targets.
   Cheapest cut: verify a tracked icon
   ([metric:ability_detection/icon-verify@223d636bf8d2#verify_ms=3.2] ms) instead
   of proposing afresh ([metric:ability_detection/icon-verify@223d636bf8d2#full_ms=47.3]);
   the corpus cost model prices tracking at
   [metric:ability_detection/cost-model@corpus-21#icons_tracked_min=29.6] of
   [metric:ability_detection/cost-model@corpus-21#icons_full_min=54.6] minutes:
   saves [metric:runtime_budget/top5@corpus-21#rank3_saving_ms_per_s=46.0] ms/s.
4. `minimap` buys the player's own position: median error
   [metric:riot_truth/minimap/all#self_err_px_median=1.3] px, p95
   [metric:riot_truth/minimap/all#self_err_px_p95=11.5]. Cheapest cut: 15 to 5
   Hz, [metric:runtime_budget/top5@corpus-21#rank4_saving_ms_per_s=59.0] ms/s;
   its accuracy at 5 Hz is unmeasured.
5. `hud` buys the round clock, score and credits: every round winner right,
   [metric:riot_truth/rounds#winner_right=439] of
   [metric:riot_truth/rounds#riot_rounds=439]. It marks no usage steps, so no
   cut can be priced; mark its steps first.

The four priced cuts leave
[metric:runtime_budget/top5@corpus-21#after_cuts_ms_per_s=921.5] ms/s, or
[metric:runtime_budget/top5@corpus-21#after_best_cuts_ms_per_s=760.4] with
prior-first teammates: both under the pace rule. Inside a round they leave
[metric:runtime_budget/top5@corpus-21#after_best_cuts_in_round_ms_per_s=1126.9],
still over one thread. The next cut defers work rather than speeding it: nothing
is shown mid-match, so a reader whose crops are cached live can read them after
the round. The crop caches cost
[metric:runtime_budget/live@corpus-21#roi_cache_minimap_ms_per_s=3.57] ms/s
(minimap) and [metric:runtime_budget/live@corpus-21#roi_cache_scoreboard_ms_per_s=1.66]
(scoreboard); deferring the two ability readers and the scoreboard's open reads
would bring the round under one thread, at the price of post-round time the
gap does not hold.

The entity-state design and the prior-first prototype
-----------------------------------------------------
One update of ten fixed slot beliefs costs
[metric:entity_state_probe/update_cost#median_us=73.2] us
([metric:entity_state_probe/update_cost#p95_us=102.6] p95),
[metric:runtime_budget/live@corpus-21#entity_state_ms_per_s=1.1] ms/s at 15 Hz:
nothing against the readers. What it changes is what the readers must do: a
slot's predicted position turns `ally_icon` into the prior-first reader (cut 1,
up to the 0.3852 share), lets `killfeed_portrait` and `roster` read only when a
slot predicts an event (cut 2), and lets `minimap` and `ability_icon` verify
rather than search. Only the update cost and the ally prototype's price are
measured; the rest is the design's claim.

What this does not measure
--------------------------
The FPS cost (the player's session); screen capture, which the harness stands
in for with crop-cache reads; GPU time; per-second percentiles (usage keeps
per-call histograms, not per-second traces, so p95 here is over matches or
over calls); accuracy at the cut rates beyond the ally labels; the change
test that would replace killfeed reads. The calibration rests on one session
whose scan ran beside other load.
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import json
import os
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

RUNTIME_BUDGET_VERSION = "runtime-budget-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
REPO = Path(__file__).resolve().parents[1]
LIVE_LOAD_DIR = "analysis/live-load-0.1.0-20261004"
#: The session `live_load` replayed; its single-thread CPU per call
#: calibrates the usage wall times of the same readers.
CALIBRATION_SESSION = "043bafca271a"
#: A match runs longer than 15 minutes and has stored rounds.
MATCH_MIN_S = 900.0
#: `live_load` reader names that differ from the scan's.
LIVE_LOAD_NAMES = {"killfeed": "killfeed_portrait"}

#: Every reader a live pass would run, at the rate the brief and
#: `live_load.LEVELS["full"]` name; `state` is the screen state it feeds, and
#: `phase` says when it must run. `gate` is how often it is offered a frame:
#: `spans` (the scan's own round-time spans, measured as fed over rate times
#: capture), `always`, or `opening` (only while its widget is on screen).
LIVE = {
    "ally_icon": {"hz": 15.0, "state": "minimap", "gate": "spans"},
    "minimap": {"hz": 15.0, "state": "minimap", "gate": "spans"},
    "ping": {"hz": 10.0, "state": "minimap", "gate": "spans"},
    "minimap_dark": {"hz": 4.0, "state": "minimap", "gate": "spans"},
    "ability": {"hz": 2.0, "state": "minimap", "gate": "spans"},
    "ability_icon": {"hz": 2.0, "state": "minimap", "gate": "spans"},
    "hud": {"hz": 2.0, "state": "hud", "gate": "always"},
    "killfeed_portrait": {"hz": 2.0, "state": "hud", "gate": "always"},
    "roster": {"hz": 2.0, "state": "hud", "gate": "always"},
    "combat_report": {"hz": 1.0, "state": "hud", "gate": "always"},
    "scoreboard": {"hz": 2.0, "state": "hud", "gate": "opening"},
}
#: Readers `live_load` timed that write no usage feed row.
LIVE_LOAD_ONLY = {"tray": {"hz": 2.0, "state": "hud"}}
#: Crop-cache writers: not readers; their cost is the price of deferring a
#: reader's work to after the round.
CACHE_WRITERS = ("roi_cache:minimap", "roi_cache:scoreboard", "roi_cache:killfeed_panel",
                 "roi_cache:hud")
#: Stored-data commands by when they can run. Each reads stored observations
#: only, so none needs the screen; a per-round one fits after its round.
POST_ROUND = ("deaths", "lifetimes", "assists", "ult-cast", "combat-report", "tray",
              "ability-state", "spike", "round-outcome", "rounds", "segment", "smokes",
              "enemy-tracks", "ability-shapes")
POST_GAME = ("vision", "self-icon", "tray-kit")
#: One Below Normal thread: the protocol's pace rule (stored over wall seconds
#: at least 0.98) and lag rule (p95 lateness at most 1 s) hold only while
#: the live load stays under one core.
ONE_THREAD_MS_PER_S = 1000.0
PACE_MIN = 0.98


def below_normal() -> None:
    """Lower this process to Below Normal on Windows; elsewhere do nothing."""
    if sys.platform == "win32":
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)


# --------------------------------------------------------------------------- pure

def bucket_quantile_ms(buckets, upper_ns, max_ns: int, q: float,
                       total_ns: float | None = None) -> float | None:
    """The q-quantile of one reader's call times from its usage histogram, ms.

    Buckets are `[0, u0), [u0, u1), ..., [u_last, max]`. Inside a closed
    bucket the quantile is interpolated linearly. The open last bucket is
    modelled as an exponential excess over `u_last` whose mean is what
    `total_ns` leaves after the closed buckets at their midpoints, capped at
    `max_ns`; without `total_ns` it returns the bucket's lower edge, a lower
    bound. An estimate, not a measured percentile. None for no calls.
    """
    counts = np.asarray(buckets, dtype=np.float64)
    n = counts.sum()
    if n <= 0:
        return None
    upper = np.asarray(upper_ns, np.float64)
    edges = np.concatenate(([0.0], upper))
    cum = np.cumsum(counts)
    target = q * n
    i = min(int(np.searchsorted(cum, target, side="left")), len(counts) - 1)
    before = cum[i - 1] if i else 0.0
    frac = (target - before) / counts[i] if counts[i] else 0.0
    if i < len(counts) - 1:
        lo, hi = edges[i], min(edges[i + 1], max(float(max_ns), edges[i]))
        return float(lo + frac * (hi - lo)) / 1e6
    lo = upper[-1]
    if total_ns is None or counts[-1] <= 0:
        return float(lo) / 1e6
    mids = (edges[:-1] + upper) / 2.0
    open_mean = (float(total_ns) - float((counts[:-1] * mids).sum())) / counts[-1]
    excess = min(max(open_mean, lo), float(max_ns)) - lo
    got = lo + excess * -np.log(max(1.0 - frac, 1e-12))
    return float(min(got, float(max_ns))) / 1e6


def open_bucket_share(buckets) -> float | None:
    """The share of calls above the histogram's last edge (100 ms)."""
    counts = np.asarray(buckets, dtype=np.float64)
    return float(counts[-1] / counts.sum()) if counts.sum() else None


def match_sessions(durations_s: dict, round_counts: dict) -> list[str]:
    """Sessions longer than `MATCH_MIN_S` with stored rounds, sorted."""
    return sorted(s for s, d in durations_s.items()
                  if d > MATCH_MIN_S and round_counts.get(s, 0) > 0)


def latest_feeds(scans: list[dict], sessions) -> dict:
    """{(session, reader): feed record} from each session's latest completed
    whole-capture scan that ran the reader (`until_s` null)."""
    keep = set(sessions)
    out = {}
    for row in sorted(scans, key=lambda r: r.get("recorded_at", "")):
        if (row.get("kind") != "vod_scan" or row.get("session_id") not in keep
                or row.get("status", "completed") != "completed"
                or row.get("until_s") is not None):
            continue
        logical = (row.get("contention") or {}).get("logical_cpus")
        other = (row.get("contention") or {}).get("other_cpu_ns")
        for name, r in row["readers"].items():
            if not r["feed"]["count"]:
                continue
            out[(row["session_id"], name)] = {
                **r, "bucket_upper_ns": row.get("bucket_upper_ns"),
                "cv_pass": (row.get("cv_threads") or {}).get("pass"),
                "source": row.get("source"), "recorded_at": row.get("recorded_at"),
                "other_load": (other / (row["pass_ns"] * logical)
                               if other is not None and logical and row.get("pass_ns") else None)}
    return out


def feed_cost(feed: dict, duration_s: float, live_hz: float) -> dict:
    """One session's per-call and per-second cost of one reader at `live_hz`.

    `open_share` is the gate: frames fed over the scan rate times the capture,
    the share of play seconds the reader is offered a frame. Mean ms per
    second of play is the mean call times the live rate times that share.
    `over_100ms_share` is the share of calls in the histogram's open bucket.
    """
    f = feed["feed"]
    calls = f["count"]
    fed = feed.get("fed") or calls
    mean_call = f["total_ns"] / calls / 1e6
    p95_call = bucket_quantile_ms(f["buckets"], feed["bucket_upper_ns"], f["max_ns"], 0.95,
                                  f["total_ns"])
    open_share = min(1.0, fed / (feed["hz"] * duration_s)) if feed.get("hz") else 1.0
    return {"calls": calls, "mean_call_ms": mean_call, "p95_call_ms": p95_call,
            "over_100ms_share": open_bucket_share(f["buckets"]),
            "open_share": open_share,
            "ms_per_s": mean_call * live_hz * open_share,
            "other_load": feed.get("other_load"), "cv_pass": feed.get("cv_pass")}


def across(values) -> dict:
    """Mean, median and p95 over matches."""
    a = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if not a.size:
        return {"n": 0, "mean": None, "median": None, "p95": None}
    return {"n": int(a.size), "mean": float(a.mean()), "median": float(np.median(a)),
            "p95": float(np.percentile(a, 95))}


def opening_cost(hz: float, open_share: float, ms_open: float, ms_closed: float,
                 gate_ms: float | None = None) -> dict:
    """A reader offered every frame that does its work only while its widget is
    open: today's cost, and the cost with a cheaper closed-frame gate."""
    now = hz * (open_share * ms_open + (1 - open_share) * ms_closed)
    gated = (hz * (open_share * ms_open + (1 - open_share) * gate_ms)
             if gate_ms is not None else None)
    return {"ms_per_s": now, "gated_ms_per_s": gated,
            "open_ms_per_s": hz * open_share * ms_open}


def change_only_saving(ms_per_s: float, open_share: float, empty_ms: float, hz: float,
                       unchanged_share_nonempty: float) -> float:
    """Upper bound on the ms per second saved by reading a non-empty panel only
    when it changed: the unchanged share of non-empty reads, at the non-empty
    mean call (the verify that replaces it is not priced)."""
    nonempty_ms = (ms_per_s / hz - (1 - open_share) * empty_ms) / max(open_share, 1e-9)
    return hz * open_share * unchanged_share_nonempty * max(0.0, nonempty_ms)


def budget(live_ms_per_s: float, in_round_ms_per_s: float) -> dict:
    """The protocol's computable limits: one Below Normal thread keeps pace at
    a mean under `PACE_MIN` of a core, and stays under 1 s late only while
    the load inside a round is under one core (a round runs far longer than
    the 1 s of lateness the lag rule allows, so the gaps cannot repay it)."""
    return {"one_thread_ms_per_s": ONE_THREAD_MS_PER_S,
            "mean_share": live_ms_per_s / ONE_THREAD_MS_PER_S,
            "in_round_share": in_round_ms_per_s / ONE_THREAD_MS_PER_S,
            "pace_ok": live_ms_per_s <= PACE_MIN * ONE_THREAD_MS_PER_S,
            "in_round_ok": in_round_ms_per_s <= ONE_THREAD_MS_PER_S}


# --------------------------------------------------------------------------- store

def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_store(store: Path) -> dict:
    import pyarrow.parquet as pq
    durations, rounds = {}, {}
    for f in glob.glob(str(store / "manifests" / "*.json")):
        m = json.loads(Path(f).read_text(encoding="utf-8"))
        durations[m["session_id"]] = m["source"]["duration_ms"] / 1000.0
    for sid in durations:
        paths = glob.glob(str(store / "l2" / "rounds" / "date=*" / f"session={sid}"
                              / "rounds.parquet"))
        if paths:
            rounds[sid] = pq.read_table(paths[0], columns=["round_no", "t_start_ms",
                                                           "t_end_ms"]).to_pylist()
    usage = _load_jsonl(store / "notes" / "usage.jsonl")
    metrics = _load_jsonl(store / "notes" / "metrics.jsonl")
    live = {}
    for f in glob.glob(str(store / LIVE_LOAD_DIR / "*.json")):
        live[Path(f).stem] = json.loads(Path(f).read_text(encoding="utf-8"))
    return {"durations": durations, "rounds": rounds, "usage": usage, "metrics": metrics,
            "live_load": live}


def metric(rows: list[dict], series: str, session: str, field: str):
    """The latest pass row's value of `tool/part@session#field`."""
    tool, _, part = series.partition("/")
    got = None
    for r in rows:
        if (r.get("tool") == tool and (r.get("part") or "") == part
                and (r.get("session") or "") == session and r.get("status") == "pass"):
            got = r["values"].get(field, got)
    return got


# --------------------------------------------------------------------------- analysis

def measure_budget(data: dict) -> dict:
    durations = data["durations"]
    rounds = {s: len(r) for s, r in data["rounds"].items()}
    matches = match_sessions(durations, rounds)
    scans = [r for r in data["usage"] if r.get("kind") == "vod_scan"]
    feeds = latest_feeds(scans, matches)
    M = data["metrics"]

    # CPU calibration: live_load's single-thread CPU per call over the usage
    # wall per call of the same reader on the same session.
    full = data["live_load"].get("full_bn") or {}
    calib = {}
    for name, r in (full.get("by_reader") or {}).items():
        reader = LIVE_LOAD_NAMES.get(name, name)
        feed = feeds.get((CALIBRATION_SESSION, reader))
        if feed and r.get("calls"):
            wall = feed["feed"]["total_ns"] / feed["feed"]["count"] / 1e6
            calib[reader] = {"cpu_ms_per_call": r["cpu_ms_per_call"], "usage_wall_ms": wall,
                             "cpu_over_wall": r["cpu_ms_per_call"] / wall}

    readers = {}
    by_session: dict[str, dict[str, float]] = {s: {} for s in matches}
    in_round_by_session: dict[str, dict[str, float]] = {s: {} for s in matches}
    for name, spec in LIVE.items():
        per = {s: feed_cost(feeds[(s, name)], durations[s], spec["hz"])
               for s in matches if (s, name) in feeds}
        if not per:
            continue
        ratio = calib.get(name, {}).get("cpu_over_wall")
        k = max(1.0, ratio or 1.0)      # charge the larger of wall and calibrated CPU
        for s, c in per.items():
            by_session[s][name] = c["ms_per_s"] * k
            in_round_by_session[s][name] = (c["mean_call_ms"] * spec["hz"] * k
                                            if spec["gate"] == "spans" else c["ms_per_s"] * k)
        ms = across(c["ms_per_s"] for c in per.values())
        readers[name] = {
            **spec, "sessions": len(per),
            "mean_call_ms": across(c["mean_call_ms"] for c in per.values()),
            "p95_call_ms": across(c["p95_call_ms"] for c in per.values()),
            "over_100ms_share": across(c["over_100ms_share"] for c in per.values()),
            "open_share": across(c["open_share"] for c in per.values()),
            "ms_per_s": ms,
            "other_load": across(c["other_load"] for c in per.values()),
            "cpu_over_wall": ratio,
            "charged_ms_per_s": ms["mean"] * k,
            "charged_p95_ms_per_s": ms["p95"] * k,
            "charged_in_round_ms_per_s": across(in_round_by_session[s][name]
                                                for s in per)["mean"],
        }

    # The price of deferring: the crop-cache writers at their scan rates.
    cache = {}
    for name in CACHE_WRITERS:
        per = [feed_cost(feeds[(s, name)], durations[s], feeds[(s, name)]["hz"])
               for s in matches if (s, name) in feeds]
        if per:
            cache[name] = {"sessions": len(per), "hz": feeds[next(
                (s, name) for s in matches if (s, name) in feeds)]["hz"],
                "mean_call_ms": across(c["mean_call_ms"] for c in per)["mean"],
                "ms_per_s": across(c["ms_per_s"] for c in per)["mean"]}

    # Readers only live_load timed (no usage feed): one session, CPU per call.
    for name, spec in LIVE_LOAD_ONLY.items():
        r = (full.get("by_reader") or {}).get(name)
        if r:
            v = r["cpu_ms_per_call"] * spec["hz"]
            readers[name] = {**spec, "gate": "always", "sessions": 1,
                             "mean_call_ms": {"n": 1, "mean": r["cpu_ms_per_call"]},
                             "ms_per_s": {"n": 1, "mean": v, "p95": v}, "cpu_over_wall": None,
                             "charged_ms_per_s": v, "charged_p95_ms_per_s": v,
                             "charged_in_round_ms_per_s": v}

    # Scoreboard per opening: stored open share and per-call costs by state.
    sb_open = metric(M, "scoreboard/openings", "all-sessions", "open_fraction")
    sb_ms_open = metric(M, "scoreboard/speed-batch", "a06f04a0059f", "ms_open_mean_cur")
    sb_ms_closed = metric(M, "scoreboard/speed-batch", "a06f04a0059f", "ms_closed_mean_cur")
    strip_s = metric(M, "scoreboard/strip", "all-sessions", "wall_s")
    strip_n = metric(M, "scoreboard/strip", "all-sessions", "frames")
    strip_ms = strip_s * 1000.0 / strip_n if strip_s and strip_n else None
    scoreboard = (opening_cost(LIVE["scoreboard"]["hz"], sb_open, sb_ms_open, sb_ms_closed,
                               strip_ms) if None not in (sb_open, sb_ms_open, sb_ms_closed)
                  else None)

    # Killfeed: the share of HUD samples with an entry and the cost by entries.
    kf_open = metric(M, "killfeed_panel/gate-projection", "", "open_share")
    kf_empty = metric(M, "killfeed_prior/cost", "5822b6646448", "ms_portrait_reader_0_entries")
    kf_unchanged = metric(M, "killfeed_prior/derived", "eight", "unchanged_share_nonempty")

    # Audio witness at each round end (post-round): live_load's one call.
    audio = (full.get("by_reader") or {}).get("audio")
    play_s = sum(durations[s] for s in matches)
    n_rounds = sum(rounds[s] for s in matches)
    audio_ms_per_s = (audio["cpu_ms_per_call"] * n_rounds / play_s) if audio else None

    # Post-round and post-game commands: each match's latest completed run.
    cmds = {}
    for row in sorted((r for r in data["usage"] if r.get("kind") == "command"
                       and r.get("session_id") in set(matches)
                       and r.get("status") == "completed"),
                      key=lambda r: r.get("recorded_at", "")):
        cmds[(row["session_id"], row["command"])] = row
    post = {}
    for (sid, cmd), row in cmds.items():
        cpu = row.get("cpu_ns") if row.get("cpu_ns") is not None else row["wall_ns"]
        post.setdefault(cmd, {})[sid] = cpu / 1e9
    post_summary = {}
    for cmd, by in post.items():
        phase = ("post_round" if cmd in POST_ROUND else
                 "post_game" if cmd in POST_GAME else "other")
        per_round = [v / rounds[s] for s, v in by.items()]
        post_summary[cmd] = {"phase": phase, "sessions": len(by),
                             "cpu_s_per_match": across(by.values()),
                             "cpu_s_per_round": across(per_round)}
    gaps, round_s = [], []
    for s in matches:
        rr = sorted(data["rounds"][s], key=lambda r: r["round_no"])
        for a, b in zip(rr, rr[1:]):
            if a["t_end_ms"] is not None and b["t_start_ms"] is not None:
                gaps.append((b["t_start_ms"] - a["t_end_ms"]) / 1000.0)
        round_s += [(r["t_end_ms"] - r["t_start_ms"]) / 1000.0 for r in rr
                    if r["t_end_ms"] is not None and r["t_start_ms"] is not None]
    post_round_cpu = sum(v["cpu_s_per_round"]["median"] for v in post_summary.values()
                         if v["phase"] == "post_round" and v["cpu_s_per_round"]["n"])
    post_game_cpu = sum(v["cpu_s_per_match"]["median"] for v in post_summary.values()
                        if v["phase"] == "post_game" and v["cpu_s_per_match"]["n"])
    if audio:
        post_round_cpu += audio["cpu_ms_per_call"] / 1000.0

    # The live total, the load inside a round, and the budget.
    live = readers
    total = sum(r["charged_ms_per_s"] for r in live.values())
    # Per match: readers a match never ran add their corpus mean, so every
    # match carries the whole live set.
    def per_match(table, field):
        out = []
        for s in matches:
            out.append(sum(table[s].get(n, r[field]) for n, r in live.items()))
        return across(out)
    total_matches = per_match(by_session, "charged_ms_per_s")
    in_round_matches = per_match(in_round_by_session, "charged_in_round_ms_per_s")
    total_p95 = total_matches["p95"]
    in_round = sum(r["charged_in_round_ms_per_s"] for r in live.values())
    minimap_total = sum(r["charged_ms_per_s"] for r in live.values() if r["state"] == "minimap")
    hud_total = sum(r["charged_ms_per_s"] for r in live.values() if r["state"] == "hud")
    # The entity-state belief (ten fixed slots) per update, at the minimap rate.
    es_us = metric(M, "entity_state_probe/update_cost", "", "median_us")
    es_p95 = metric(M, "entity_state_probe/update_cost", "", "p95_us")
    entity_state = ({"median_us": es_us, "p95_us": es_p95,
                     "ms_per_s_at_15hz": es_us * LIVE["minimap"]["hz"] / 1000.0}
                    if es_us is not None else None)

    ranked = sorted(live.items(), key=lambda kv: -kv[1]["charged_ms_per_s"])
    return {"version": RUNTIME_BUDGET_VERSION, "matches": matches, "n_matches": len(matches),
            "excluded_long_sessions": sorted(s for s, d in durations.items()
                                             if d > MATCH_MIN_S and s not in matches),
            "play_s": play_s, "rounds": n_rounds, "calibration": calib,
            "readers": readers, "scoreboard": scoreboard,
            "killfeed": {"open_share": kf_open, "empty_ms": kf_empty,
                         "unchanged_share_nonempty": kf_unchanged},
            "audio_ms_per_s": audio_ms_per_s,
            "audio_ms_per_round_end": audio["cpu_ms_per_call"] if audio else None,
            "post": post_summary, "post_round_cpu_s": post_round_cpu,
            "post_game_cpu_s": post_game_cpu,
            "round_gap_s": across(gaps), "round_s": across(round_s),
            "live_ms_per_s": total, "live_p95_ms_per_s": total_p95,
            "live_in_round_ms_per_s": in_round,
            "live_in_round_p95_ms_per_s": in_round_matches["p95"],
            "minimap_ms_per_s": minimap_total, "hud_ms_per_s": hud_total,
            "entity_state": entity_state, "cache_writers": cache,
            "budget": budget(total, in_round),
            "harness_demand_cores": {k: v.get("demand_cores")
                                     for k, v in data["live_load"].items()},
            "ranked": [n for n, _ in ranked]}


def top_changes(a: dict, M: list[dict]) -> list[dict]:
    """The five largest live costs, what each buys, and the cheapest cut."""
    R = a["readers"]
    out = []

    def add(name, buys, change, saving_ms, then=None, then_ms=None):
        r = R[name]
        out.append({"reader": name, "ms_per_s": r["charged_ms_per_s"],
                    "in_round_ms_per_s": r["charged_in_round_ms_per_s"], "buys": buys,
                    "change": change, "saving_ms_per_s": saving_ms,
                    "saving_share": (saving_ms / r["charged_ms_per_s"]
                                     if saving_ms is not None and r["charged_ms_per_s"]
                                     else None),
                    "then": then, "then_saving_ms_per_s": then_ms})

    speed = metric(M, "ally_rate/speed", "a06f04a0059f", "speedup_cpu")
    price = metric(M, "ally_prior/riot_pool", "heldout6", "priced_share_max")
    kf = a["killfeed"]
    sb = a["scoreboard"]
    icon_full = metric(M, "ability_detection/cost-model", "corpus-21", "icons_full_min")
    icon_tracked = metric(M, "ability_detection/cost-model", "corpus-21", "icons_tracked_min")
    for name in a["ranked"][:5]:
        r = R[name]
        ms = r["charged_ms_per_s"]
        if name == "ally_icon":
            add(name, "teammate positions and names on the minimap",
                "rate 15 to 5 Hz (same labelled names)",
                ms * (1 - 1 / speed) if speed else None,
                "prior-first ally-prior-0.2.0 at its priced share of the full reader",
                ms * (1 - price) if price else None)
        elif name == "killfeed_portrait":
            add(name, "every kill's victim, killer and weapon",
                "read a non-empty panel only when it changed (prior-first)",
                change_only_saving(r["ms_per_s"]["mean"], kf["open_share"], kf["empty_ms"],
                                   r["hz"], kf["unchanged_share_nonempty"])
                * max(1.0, r.get("cpu_over_wall") or 1.0)
                if None not in (kf["open_share"], kf["empty_ms"], kf["unchanged_share_nonempty"])
                else None)
        elif name == "scoreboard":
            add(name, "credits, KDA and agents per opening",
                "cache the crop while open and read it after the round",
                ms - (sb["ms_per_s"] - sb["open_ms_per_s"]) if sb else None)
        elif name == "ability_icon":
            add(name, "ability icons on the minimap",
                "verify tracked icons instead of proposing every frame",
                ms * (1 - icon_tracked / icon_full) if icon_full and icon_tracked else None)
        elif name == "ability":
            add(name, "ability shapes on the minimap", "share the icon gate; unmeasured", None)
        elif name == "hud":
            add(name, "round clock, score and credits", "mark steps first; unmeasured", None)
        elif name == "minimap":
            add(name, "the player's own position and facing",
                "rate 15 to 5 Hz; unmeasured for accuracy", ms * (1 - 5 / 15))
        else:
            add(name, "", "unmeasured", None)
    return out


def ledger_values(a: dict, changes: list[dict]) -> dict[str, dict]:
    """Flat numeric rows for `metrics.record`, one per part."""
    def r4(x):
        return None if x is None else round(float(x), 4)
    readers = {}
    for n, r in a["readers"].items():
        key = n.replace(":", "_")
        readers[f"{key}_ms_per_s"] = r4(r["charged_ms_per_s"])
        readers[f"{key}_p95_ms_per_s"] = r4(r["charged_p95_ms_per_s"])
        readers[f"{key}_in_round_ms_per_s"] = r4(r["charged_in_round_ms_per_s"])
        if (r.get("over_100ms_share") or {}).get("mean") is not None:
            readers[f"{key}_over_100ms_share"] = r4(r["over_100ms_share"]["mean"])
        if r.get("mean_call_ms", {}).get("mean") is not None:
            readers[f"{key}_call_ms"] = r4(r["mean_call_ms"]["mean"])
        if r.get("p95_call_ms", {}).get("mean") is not None:
            readers[f"{key}_p95_call_ms"] = r4(r["p95_call_ms"]["mean"])
        if r.get("open_share", {}).get("mean") is not None:
            readers[f"{key}_open_share"] = r4(r["open_share"]["mean"])
        if r.get("cpu_over_wall") is not None:
            readers[f"{key}_cpu_over_wall"] = r4(r["cpu_over_wall"])
    live = {"matches": a["n_matches"], "rounds": a["rounds"], "play_h": r4(a["play_s"] / 3600),
            "live_ms_per_s": r4(a["live_ms_per_s"]),
            "live_p95_ms_per_s": r4(a["live_p95_ms_per_s"]),
            "live_in_round_ms_per_s": r4(a["live_in_round_ms_per_s"]),
            "live_in_round_p95_ms_per_s": r4(a["live_in_round_p95_ms_per_s"]),
            "minimap_ms_per_s": r4(a["minimap_ms_per_s"]), "hud_ms_per_s": r4(a["hud_ms_per_s"]),
            "mean_share_of_one_thread": r4(a["budget"]["mean_share"]),
            "in_round_share_of_one_thread": r4(a["budget"]["in_round_share"]),
            "pace_ok": int(a["budget"]["pace_ok"]), "in_round_ok": int(a["budget"]["in_round_ok"]),
            "audio_ms_per_s": r4(a["audio_ms_per_s"])}
    if a["scoreboard"]:
        live.update({f"scoreboard_{k}": r4(v) for k, v in a["scoreboard"].items()})
    if a["entity_state"]:
        live["entity_state_ms_per_s"] = r4(a["entity_state"]["ms_per_s_at_15hz"])
    for name, c in a["cache_writers"].items():
        live[f"{name.replace(':', '_')}_ms_per_s"] = r4(c["ms_per_s"])
    post = {"post_round_cpu_s": r4(a["post_round_cpu_s"]),
            "post_game_cpu_s": r4(a["post_game_cpu_s"]),
            "round_gap_s_median": r4(a["round_gap_s"]["median"]),
            "round_s_median": r4(a["round_s"]["median"]),
            "audio_ms_per_round_end": r4(a["audio_ms_per_round_end"]),
            "post_round_over_next_round_ms_per_s": r4(
                1000 * a["post_round_cpu_s"] / a["round_s"]["median"])}
    for cmd, v in a["post"].items():
        if v["cpu_s_per_match"]["median"] is not None:
            post[f"{cmd.replace('-', '_')}_cpu_s_per_match"] = r4(v["cpu_s_per_match"]["median"])
    top = {}
    for i, c in enumerate(changes, 1):
        top[f"rank{i}_ms_per_s"] = r4(c["ms_per_s"])
        top[f"rank{i}_saving_ms_per_s"] = r4(c["saving_ms_per_s"])
        if c["then_saving_ms_per_s"] is not None:
            top[f"rank{i}_then_saving_ms_per_s"] = r4(c["then_saving_ms_per_s"])
    cuts = sum(c["saving_ms_per_s"] or 0 for c in changes)
    best = sum(max(c["saving_ms_per_s"] or 0, c["then_saving_ms_per_s"] or 0) for c in changes)
    top["after_cuts_ms_per_s"] = r4(a["live_ms_per_s"] - cuts)
    top["after_best_cuts_ms_per_s"] = r4(a["live_ms_per_s"] - best)
    # Inside a round each cut saves its share of the reader's in-round load.
    top["after_best_cuts_in_round_ms_per_s"] = r4(a["live_in_round_ms_per_s"] - sum(
        c["in_round_ms_per_s"] * max(c["saving_share"] or 0,
                                     (c["then_saving_ms_per_s"] or 0) / c["ms_per_s"])
        for c in changes))
    return {"live": live, "readers": readers, "post": post, "top5": top}


def report(a: dict, changes: list[dict]) -> str:
    L = [f"{RUNTIME_BUDGET_VERSION}: {a['n_matches']} matches, {a['rounds']} rounds, "
         f"{a['play_s'] / 3600:.2f} h of play; excluded {a['excluded_long_sessions']}"]
    L.append("reader               state    Hz  sess  call ms (p95)  open   ms/s mean  p95  "
             ">100ms cpu/wall  charged in-round")
    for n in a["ranked"]:
        r = a["readers"][n]
        c, p = r.get("mean_call_ms", {}), r.get("p95_call_ms", {})
        L.append(f"{n:20s} {r['state']:8s} {r['hz']:4.0f} {r['sessions']:4d} "
                 f"{c.get('mean') or 0:7.2f} ({p.get('mean') or 0:6.1f}) "
                 f"{(r.get('open_share') or {}).get('mean') or 1:5.2f} "
                 f"{r['ms_per_s']['mean']:8.1f} {r['ms_per_s'].get('p95') or 0:6.1f} "
                 f"{(r.get('over_100ms_share') or {}).get('mean') or 0:6.3f} "
                 f"{r['cpu_over_wall'] or 0:6.2f} {r['charged_ms_per_s']:8.1f} "
                 f"{r['charged_in_round_ms_per_s']:8.1f}")
    b = a["budget"]
    L.append(f"live total {a['live_ms_per_s']:.0f} ms/s mean (p95 match {a['live_p95_ms_per_s']:.0f}),"
             f" in-round {a['live_in_round_ms_per_s']:.0f} (p95 match "
             f"{a['live_in_round_p95_ms_per_s']:.0f});"
             f" minimap {a['minimap_ms_per_s']:.0f}, HUD {a['hud_ms_per_s']:.0f};"
             f" one thread = {b['one_thread_ms_per_s']:.0f}: pace_ok {b['pace_ok']},"
             f" in-round ok {b['in_round_ok']}")
    L.append(f"entity state: {a['entity_state']}")
    L.append("crop-cache writers (the price of deferring): " + ", ".join(
        f"{k} {v['hz']:g} Hz {v['mean_call_ms']:.2f} ms/call {v['ms_per_s']:.2f} ms/s "
        f"({v['sessions']} matches)" for k, v in a["cache_writers"].items()))
    L.append(f"scoreboard per opening: {a['scoreboard']}")
    L.append(f"killfeed: {a['killfeed']}")
    L.append(f"audio witness {a['audio_ms_per_round_end']} ms per round end "
             f"({a['audio_ms_per_s']:.2f} ms/s)")
    L.append(f"post-round CPU {a['post_round_cpu_s']:.1f} s per round (median round "
             f"{a['round_s']['median']:.0f} s, gap {a['round_gap_s']['median']:.1f} s); "
             f"post-game CPU {a['post_game_cpu_s']:.0f} s per match")
    for cmd, v in sorted(a["post"].items(), key=lambda kv: -(kv[1]["cpu_s_per_match"]["median"]
                                                             or 0)):
        L.append(f"   {cmd:15s} {v['phase']:10s} {v['sessions']:3d} matches  "
                 f"{v['cpu_s_per_match']['median']:7.1f} s/match  "
                 f"{v['cpu_s_per_round']['median']:6.2f} s/round")
    L.append(f"calibration on {CALIBRATION_SESSION}: " + ", ".join(
        f"{k} {v['cpu_over_wall']:.2f}" for k, v in a["calibration"].items()))
    L.append(f"harness demand_cores: {a['harness_demand_cores']}")
    for c in changes:
        L.append(f"top: {c['reader']:18s} {c['ms_per_s']:7.1f} ms/s  buys {c['buys']}; "
                 f"{c['change']}: saves {c['saving_ms_per_s'] or 0:.1f} ms/s"
                 + (f"; then {c['then']}: saves {c['then_saving_ms_per_s']:.1f} ms/s"
                    if c["then_saving_ms_per_s"] is not None else ""))
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--store", default=str(STORE))
    p.add_argument("--record", action="store_true", help="append runtime_budget/* ledger rows")
    p.add_argument("--json", default=None, help="write the full analysis here (not the store)")
    args = p.parse_args(argv)
    below_normal()
    store = Path(args.store)
    data = load_store(store)
    a = measure_budget(data)
    changes = top_changes(a, data["metrics"])
    print(report(a, changes))
    rows = ledger_values(a, changes)
    if args.json:
        out = Path(args.json).resolve()
        if store.resolve() in out.parents:
            raise SystemExit("--json refuses a path inside the store")
        out.write_text(json.dumps({"analysis": a, "changes": changes, "ledger": rows},
                                  indent=1, default=str), encoding="utf-8")
    if args.record:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from reticle import metrics
        deps = {"runtime_budget": RUNTIME_BUDGET_VERSION, "live_load": "live-load-0.1.0",
                "usage": "scan-usage-4"}
        for part, values in rows.items():
            metrics.record("runtime_budget", part=part, session="corpus-21", values=values,
                           deps=deps, context={"matches": a["matches"],
                                               "calibration_session": CALIBRATION_SESSION})
            print(" ".join(f"[metric:runtime_budget/{part}@corpus-21#{k}={v}]"
                           for k, v in values.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
