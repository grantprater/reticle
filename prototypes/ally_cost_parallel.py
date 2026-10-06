"""Does the ally-icon reader scale across processes? (ally-cost-diag-0.1.0, not wired)

Runs `ally_cost_diag.py SID --only WINDOW` in 1, then 2, then 3 concurrent
processes (each the same window, each single-threaded at idle priority) and
reports each run's wall, the per-process CPU per frame, the throughput in
frames per wall second, and the machine's load from processes this driver
did not start (`GetSystemTimes`, over the feeding phase).

    python prototypes/ally_cost_parallel.py SID --window rand0 --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
#: Seconds every process gets to build its reader and load its frames.
SETUP_S = 150.0


def _system_times():
    """(idle, kernel, user) in 100 ns ticks summed over all logical CPUs;
    kernel includes idle."""
    import ctypes
    from ctypes import wintypes
    i, k, u = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
    return f(i), f(k), f(u)


def run(sid: str, window: str, k: int, out: Path) -> dict:
    files = [out / f"par{k}_{i}.jsonl" for i in range(k)]
    for f in files:
        f.unlink(missing_ok=True)
    env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1"}
    start_at = time.time() + SETUP_S
    procs = [subprocess.Popen([sys.executable, str(HERE / "ally_cost_diag.py"), sid,
                               "--only", window, "--out", str(f),
                               "--start-at", str(start_at)], env=env)
             for f in files]
    time.sleep(max(0.0, start_at - time.time()))
    s0 = _system_times()
    t0 = time.perf_counter()
    while any(p.poll() is None for p in procs):
        time.sleep(0.5)
    wall = time.perf_counter() - t0
    s1 = _system_times()
    idle, kern, user = (b - a for a, b in zip(s0, s1))
    busy = 1.0 - idle / max(kern + user, 1)
    recs = [json.loads(f.read_text().splitlines()[-1]) for f in files]
    frames = sum(r["frames"] for r in recs)
    n = os.cpu_count()
    feed_s = [r["wall_ms_per_frame"] * r["frames"] / 1e3 for r in recs]
    return {"processes": k, "wall_after_start_s": round(wall, 1), "frames": frames,
            "feed_wall_s": [round(x, 1) for x in feed_s],
            "frames_per_feed_wall_s": round(frames / max(feed_s), 2),
            "cpu_ms_per_frame": [r["cpu_ms_per_frame"] for r in recs],
            "wall_ms_per_frame": [r["wall_ms_per_frame"] for r in recs],
            "system_busy_pct": round(100 * busy, 1),
            "others_busy_logical_cpus_est": round(busy * n - k, 2),
            "note": f"GetSystemTimes over {n} logical CPUs from the common start to the last "
                    f"exit, ours included; others = busy CPUs less k (an upper bound: our "
                    f"processes finish at different times)"}


def _idle() -> None:
    """Idle priority for this process (Windows `IDLE_PRIORITY_CLASS`);
    children inherit it."""
    import ctypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    if not k.SetPriorityClass(k.GetCurrentProcess(), 0x40):
        raise OSError("SetPriorityClass failed")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session")
    ap.add_argument("--window", default="rand0")
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    _idle()
    args.out.mkdir(parents=True, exist_ok=True)
    for k in range(1, args.max + 1):
        print(json.dumps(run(args.session, args.window, k, args.out)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
