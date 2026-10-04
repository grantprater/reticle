r"""Replay a stored session's crop cache through the live readers at real-time pace.

    .\.venv\Scripts\python.exe prototypes\live_load.py SESSION --level light
        [--seconds 150] [--start auto|SECONDS] [--priority below_normal|idle]
        [--threads 1] [--pace realtime|max] [--rate ally_icon=4] [--out FILE.json]

Why this exists, 2026-10-04
---------------------------
The player will let reticle run during play if it costs at most about a fifth
of his frame rate (the player, 2026-10-04 (chat)). Riot's rules bar showing
conclusions mid-match, so the case to measure is silent computation beside the
game (docs/WIN_PROBABILITY_RESEARCH.md section 2, branch
winprob-research-20261004). The frame-time cost can be measured only with the
game running, by the player (docs/FRAMETIME_PROTOCOL.md). This harness is the
load he runs beside it: the readers a live pass would run, fed the stored
crops at the pace the capture was recorded, so its CPU draw matches what a live
pass at that level would draw.

What it runs, per level (`LEVELS`; `--rate name=hz` overrides one rate)

    light   hud and killfeed at 2 Hz, ally_icon at 2 Hz, tray at 2 Hz,
            the audio witness at each round end
    medium  light, with ally_icon and the self position (minimap) at 5 Hz
    full    the scan's minimap rates: ally_icon and minimap at 15 Hz,
            minimap_dark at 4 Hz, ping at 10 Hz, plus the light set

`full` is not the whole production scan. `reticle scan` (`cli.py`) also runs
the roster reader at the HUD rate, the combat report reader at 1 Hz, the
lineup reader, the ability shape and icon readers (they need stored round
results as input) and, when asked, the scoreboard reader. No level runs any
of them, so every level understates a full scan's load.

Every window mixes round time with the gaps between rounds. The minimap crop
cache covers only round time, so the minimap readers idle in a gap while the
HUD readers keep running; `demand_cores` is an average over the whole window
and understates the load inside a round.

No owner answers "which readers does a live pass need" (`reticle ownership`
routes it to nothing live); the set is the brief's minimum plus the self
position and the scan's minimap readers at production rates. Each reader is
the one `scan` or `trial` builds, constructed by its owner's builder:
`hud_reader.HudReader`, `killfeed.KillfeedPortraitReader`,
`minimap.ally_icon_reader`, `cli._MinimapPass`, `minimap_dark.dark_reader`,
`ping.PingReader`; the tray reads `tray.slot_counts` on the minimap cache's
`hud_abilities` crop at the stored `tray_drop` step; the audio witness is
`ability_timeline.audio_cast_witness` over the round's stored drops and the
stored audio-gate features, named by the identity arbiter's agent through
`ability_state.player_agent_verdict`.

What it measures, and what it does not

* CPU per reader: `time.process_time` around each feed (Windows charges it in
  15.6 ms ticks, so a per-call figure is a tick-sampled estimate; the sums
  over hundreds of calls are what to read) and wall time in feed.
* `source`: reading the crop cache and pasting crops into a frame. A live
  pass would instead copy ROIs from a screen capture (Windows.Graphics.Capture);
  that cost is not measured here, and this one stands in for it.
* `demand_cores` = CPU seconds over the stored seconds replayed: the cores a
  pass at this level needs to keep pace. `pace` = stored seconds over wall
  seconds; below 1 the harness fell behind (it runs on one thread, serially).
* `system_busy`: the share of all logical CPUs busy during the run
  (`GetSystemTimes`), so a contended run says so.
* The audio witness reads the whole session's stored features on each call;
  its cost per round end is an upper bound on a live per-round witness, and
  the live log-mel extraction it would need is not measured.
* GPU time is not counted; `ult_lines.array_module` decides whether the audio
  witness runs on the GPU (`gpu` in the output).

It writes nothing to the store: readers accumulate rows in memory and are
dropped. `--out` refuses a path inside the store. Never decodes video or audio.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

LIVE_LOAD_VERSION = "live-load-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")

#: Reader rates (Hz) per level; audio fires at each round end, not at a rate.
LEVELS = {
    "light": {"hud": 2.0, "killfeed": 2.0, "ally_icon": 2.0, "tray": 2.0, "audio": 1},
    "medium": {"hud": 2.0, "killfeed": 2.0, "ally_icon": 5.0, "minimap": 5.0, "tray": 2.0,
               "audio": 1},
    "full": {"hud": 2.0, "killfeed": 2.0, "ally_icon": 15.0, "minimap": 15.0,
             "minimap_dark": 4.0, "ping": 10.0, "tray": 2.0, "audio": 1},
}
HUD_READERS = ("hud", "killfeed")
PRIORITY = {"below_normal": 0x4000, "idle": 0x40}


def _args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("session")
    p.add_argument("--level", choices=sorted(LEVELS), default="light")
    p.add_argument("--seconds", type=float, default=150.0,
                   help="stored seconds to replay (default 150)")
    p.add_argument("--start", default="auto",
                   help="session second to start at; auto: the first cached round's start")
    p.add_argument("--priority", choices=sorted(PRIORITY), default="below_normal")
    p.add_argument("--threads", type=int, default=1,
                   help="OpenCV and BLAS threads (default 1)")
    p.add_argument("--pace", choices=("realtime", "max"), default="realtime",
                   help="realtime sleeps to the capture's clock; max runs flat out")
    p.add_argument("--rate", action="append", default=[],
                   help="override one reader's rate, name=hz (repeatable)")
    p.add_argument("--no-audio", action="store_true", help="skip the round-end audio witness")
    p.add_argument("--out", default=None, help="write the result JSON here (never the store)")
    p.add_argument("--store", default=str(STORE))
    return p.parse_args(argv)


# Thread counts and priority before numpy, OpenCV or cupy load.
ARGS = _args() if __name__ == "__main__" else None
_THREADS = str(ARGS.threads if ARGS is not None else 1)
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = _THREADS
_k32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
if _k32 is not None:
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _k32.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    _k32.GetPriorityClass.restype = wintypes.DWORD


def set_priority(name: str) -> None:
    """Lower this process to `name`; never raises it above Below Normal."""
    if _k32 is not None:
        if not _k32.SetPriorityClass(_k32.GetCurrentProcess(), PRIORITY[name]):
            raise SystemExit(f"could not set priority {name}")


def priority_class() -> str | None:
    """The priority class this process runs at, read back from Windows."""
    if _k32 is None:
        return None
    got = _k32.GetPriorityClass(_k32.GetCurrentProcess())
    return {v: k for k, v in PRIORITY.items()}.get(got, hex(got))


set_priority(ARGS.priority if ARGS is not None else "below_normal")

import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class _FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def _ft(x: _FT) -> float:
    return ((x.hi << 32) | x.lo) / 1e7


def system_times() -> tuple[float, float] | None:
    """(busy, total) seconds summed over all logical CPUs since boot."""
    if _k32 is None:
        return None
    idle, kern, user = _FT(), _FT(), _FT()
    _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    total = _ft(kern) + _ft(user)               # kernel time includes idle
    return total - _ft(idle), total


def peak_working_set_mb() -> float | None:
    if _k32 is None:
        return None

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    f = ctypes.windll.psapi.GetProcessMemoryInfo
    f.argtypes = (wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD)
    if not f(_k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        return None
    return round(c.PeakWorkingSetSize / 2 ** 20, 1)


class TrayReader:
    """The tray's slot counts per sample (`tray.slot_counts`), kept in memory."""

    name = "tray"
    cv_threads = None

    def __init__(self, hz: float):
        self.hz, self.spans, self.rows = hz, None, []

    def feed(self, smp) -> None:
        from reticle import tray
        self.rows.append(tray.slot_counts(smp.frame))


def live_readers(store, manifest: dict, rates: dict) -> tuple[dict, dict]:
    """The readers a level runs, by name, and their setup seconds."""
    from types import SimpleNamespace

    from reticle.passes import SessionContext
    from reticle.profiles import get_profile

    profile = get_profile(manifest["source_profile"])
    ctx = SessionContext(store=store, manifest=manifest, profile=profile)
    out, setup = {}, {}
    for name, hz in rates.items():
        if name == "audio":
            continue
        t0 = time.perf_counter()
        if name == "hud":
            from reticle.hud_reader import HudReader
            r = HudReader(store, manifest, profile,
                          SimpleNamespace(hz=hz, min_confidence=0.82, min_margin=0.05))
        elif name == "killfeed":
            from reticle.trial import _killfeed_reader
            r = _killfeed_reader(ctx)
            r.hz = hz
        elif name == "ally_icon":
            from reticle.minimap import ally_icon_reader
            r = ally_icon_reader(ctx, hz=hz)
        elif name == "minimap":
            from reticle.cli import _MinimapPass
            r = _MinimapPass(store, manifest, profile, None, SimpleNamespace(minimap_hz=hz))
        elif name == "minimap_dark":
            from reticle.minimap_dark import dark_reader
            r = dark_reader(ctx, None, hz=hz)
            if r is None:
                print("minimap_dark: the baked geometry has no lighting reference; skipped")
                continue
        elif name == "ping":
            from reticle.minimap import minimap_roi_px
            from reticle.ping import PingReader
            r = PingReader(floor=ctx.floor(), box=minimap_roi_px(profile, *ctx.wh),
                           sgray=ctx.sgray(), hz=hz, spans=None)
        elif name == "tray":
            r = TrayReader(hz)
        else:
            raise SystemExit(f"unknown reader {name!r}")
        out[name] = r
        setup[name] = round(time.perf_counter() - t0, 2)
    return out, setup


def window_spans(spans, a: float, b: float) -> list[tuple[float, float]]:
    return [(max(a, s0), min(b, s1)) for s0, s1 in spans if s1 > a and s0 < b]


def schedule(caches: dict, readers: dict, a: float, b: float, rates: dict,
             with_audio: bool):
    """(time ms, source, reader names) in time order over [a, b] ms.

    Each reader reads the first cached time at or after each point of its own
    grid, restarted at each cached span (`roi_cache.grid_times`), as `scan`
    resamples a cache slower than its own rate."""
    from reticle.roi_cache import grid_times
    by: dict[tuple[float, str], list[str]] = {}
    for name, r in readers.items():
        src = "hud" if name in HUD_READERS else "minimap"
        c = caches[src]
        held = c.record.get("spans") or [(float(np.min(c.t_ms)), float(np.max(c.t_ms)))]
        for s0, s1 in window_spans(held, a, b):
            for t in grid_times(c.t_ms, s0, s1, 1.0 / float(r.hz)):
                by.setdefault((t, src), []).append(name)
    ev = [(t, src, names) for (t, src), names in by.items()]
    if with_audio and "minimap" in caches:
        for s0, s1 in caches["minimap"].record.get("spans") or []:
            if a <= s1 <= b:
                ev.append((float(s1), "audio", [f"{s0}:{s1}"]))
    return sorted(ev, key=lambda e: (e[0], e[1]))


def audio_inputs(store_root: Path, sid: str) -> dict:
    """The stored drops and the arbiter's agent the witness reads (setup, untimed)."""
    from reticle.adjudication.ability_state import player_agent_verdict
    from reticle.lineup import load_lineup
    drops = [json.loads(x) for x in
             (store_root / "events" / "tray_drop" / f"{sid}.jsonl").read_text(
                 encoding="utf-8").splitlines() if x.strip()]
    drops = [r for r in drops if r.get("kind") == "drop"]
    agent = player_agent_verdict(load_lineup(sid, store_root), sid)
    return {"drops": drops, "agent": agent.get("agent"), "agent_status": agent.get("status")}


def replay(args) -> dict:
    import cv2

    from reticle import ult_lines
    from reticle.ability_timeline import audio_cast_witness
    from reticle.passes import _feed
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store

    cv2.setNumThreads(int(args.threads))
    store = Store(Path(args.store))
    sid = args.session
    manifest = store.read_manifest(sid)
    profile = get_profile(manifest["source_profile"])
    rates = dict(LEVELS[args.level])
    for kv in args.rate:
        k, _, v = kv.partition("=")
        if k not in rates:
            raise SystemExit(f"--rate {kv}: {k} is not in level {args.level}")
        rates[k] = float(v)
    if args.no_audio:
        rates.pop("audio", None)

    caches = {}
    for src in ("hud", "minimap"):
        c, why = RoiCache.load(store.root, manifest, profile, src)
        if c is None:
            raise SystemExit(f"{sid}: no usable {src} crop cache ({why})")
        caches[src] = c
    spans = caches["minimap"].record.get("spans") or []
    start_s = (float(spans[0][0]) / 1000.0 if args.start == "auto" else float(args.start))
    a, b = start_s * 1000.0, (start_s + float(args.seconds)) * 1000.0

    t_setup = time.perf_counter()
    readers, setup = live_readers(store, manifest, rates)
    audio = audio_inputs(store.root, sid) if "audio" in rates else None
    xp = ult_lines.array_module()
    events = schedule(caches, readers, a, b, rates, audio is not None)
    setup_s = time.perf_counter() - t_setup

    # One lazy reader per cache, in time order; each yields only its wanted times.
    want_t = {src: sorted({t for t, s, _ in events if s == src}) for src in caches}
    rois = {"hud": None, "minimap": ["minimap", "hud_abilities"]}
    gens = {src: caches[src].samples(want_t[src], rois=rois[src]) for src in caches}

    names = list(readers) + (["audio"] if audio is not None else [])
    cost = {n: {"calls": 0, "cpu_s": 0.0, "wall_s": 0.0} for n in names + ["source"]}
    lags, missing = [], 0
    sys0, cpu0 = system_times(), time.process_time()
    wall0 = time.perf_counter()
    for t, src, who in events:
        due = wall0 + (t - a) / 1000.0
        if args.pace == "realtime":
            now = time.perf_counter()
            if due > now:
                time.sleep(due - now)
        if src == "audio":
            s0, s1 = (float(x) for x in who[0].split(":"))
            rows = [r for r in audio["drops"] if s0 <= float(r["t_ms"]) <= s1]
            c0, w0 = time.process_time(), time.perf_counter()
            audio_cast_witness(store.root, sid, rows, audio["agent"], None,
                               xp=xp, span_s=(s0 / 1000.0, s1 / 1000.0))
            k = cost["audio"]
            k["calls"] += 1
            k["cpu_s"] += time.process_time() - c0
            k["wall_s"] += time.perf_counter() - w0
            lags.append(time.perf_counter() - due)
            continue
        c0, w0 = time.process_time(), time.perf_counter()
        smp = next(gens[src], None)
        k = cost["source"]
        k["calls"] += 1
        k["cpu_s"] += time.process_time() - c0
        k["wall_s"] += time.perf_counter() - w0
        if smp is None or float(smp.t_ms) != t:
            missing += 1
            if smp is None:
                continue
        for name in who:
            c0, w0 = time.process_time(), time.perf_counter()
            _feed(readers[name], smp, None)
            k = cost[name]
            k["calls"] += 1
            k["cpu_s"] += time.process_time() - c0
            k["wall_s"] += time.perf_counter() - w0
        lags.append(time.perf_counter() - due)
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    sys1 = system_times()
    replayed = (b - a) / 1000.0
    busy = (None if sys0 is None else
            round((sys1[0] - sys0[0]) / max(1e-9, sys1[1] - sys0[1]), 3))
    lag = np.asarray(lags) if lags else np.zeros(1)
    for n, k in cost.items():
        k["cpu_s"], k["wall_s"] = round(k["cpu_s"], 3), round(k["wall_s"], 3)
        k["cpu_ms_per_call"] = round(1000 * k["cpu_s"] / k["calls"], 2) if k["calls"] else None
        k["demand_cores"] = round(k["cpu_s"] / replayed, 4)
    return {
        "version": LIVE_LOAD_VERSION, "session_id": sid, "level": args.level, "rates": rates,
        "window_s": [round(a / 1000, 3), round(b / 1000, 3)], "pace_mode": args.pace,
        "priority": args.priority, "priority_read_back": priority_class(), "threads": int(args.threads),
        "gpu": getattr(xp, "__name__", str(xp)),
        "audio_agent": None if audio is None else [audio["agent"], audio["agent_status"]],
        "setup_s": round(setup_s, 1), "reader_setup_s": setup,
        "events": len(events), "missing_frames": missing,
        "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
        "demand_cores": round(cpu / replayed, 4),
        "cores_while_running": round(cpu / wall, 4),
        "share_of_logical_cpus": round(cpu / wall / (os.cpu_count() or 1), 4),
        "pace": round(replayed / wall, 3),
        "lag_s": {"p50": round(float(np.percentile(lag, 50)), 3),
                  "p95": round(float(np.percentile(lag, 95)), 3),
                  "max": round(float(lag.max()), 3),
                  "over_1s": int((lag > 1.0).sum())},
        "system_busy": busy, "logical_cpus": os.cpu_count(),
        "peak_working_set_mb": peak_working_set_mb(),
        "by_reader": cost,
    }


def main() -> int:
    args = ARGS
    if args.out is not None:
        out = Path(args.out).resolve()
        if Path(args.store).resolve() in out.parents:
            raise SystemExit("--out: this harness never writes the store")
    res = replay(args)
    text = json.dumps(res, indent=1)
    print(text)
    if args.out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
