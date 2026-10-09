r"""The scored sessions, the extras' classes and the store redirect.

Moved from `prototypes/teardrop_refusals.py` on 2026-10-09 (task
`harness-t1d-20261009`). `DEV`, `NEW` and `SCORED` name the sessions the
harness reads; `refuse` refuses every other session and the held-out match.
`class_extras` classes each extra (`visible_undrawn`, `enemy_3_8m`,
`dead_enemy`, then `ping`, `x_mark` and `other`, the true false accepts
`TRUE_FA`). `_point_store(tag)` points the harness modules' `STORE` at a
tagged reread's rows (`_Redirect`); every other input is the store's own.
"""
from __future__ import annotations

import ctypes
import json
import math
from pathlib import Path

import numpy as np

from reticle.acceptance import N_BOOT, NEAR_CM, OFFSET_CM, SEED  # noqa: F401
from reticle.store import DEFAULT_STORE


#: 0.2.0 (task teardrop-confusers-20261007): `pings`, `--pings`.
#: 0.3.0 (task teardrop-review-fixes-20261007): `--ping-own-px`,
#: `--no-owner-gate`, `gate`.
#: 0.4.0 (task teardrop-new-sessions-20261009): `refuse` admits `SCORED`, the
#: development matches and the 2026-10-07 replay captures.
VERSION = "teardrop-refusals-0.4.0"
TASK = "teardrop-refusals-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
DEV = ("9acf02f98283", "c817691bcd15", "d3dcfb182ab1")
#: The 2026-10-07 replay captures, whose inputs are current (`reticle plan`).
NEW = ("cadaadeb2d8b", "066741deafe5", "9912c382130b")
#: The sessions this task and `question_acceptance` read: one definition.
SCORED = DEV + NEW
HELD_OUT = "cea8ecbc94ab"


def _idle() -> None:
    """Idle priority, one thread (the machine's compute rules; no psutil)."""
    try:
        # The pseudo-handle is a 64-bit HANDLE; without argtypes ctypes passes
        # it as a 32-bit int, the call fails (ERROR_INVALID_HANDLE) and the
        # process stays at Normal.
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40):
            raise OSError(ctypes.get_last_error())
    except Exception:
        pass
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        pass


def refuse(sid: str) -> None:
    if sid == HELD_OUT:
        raise SystemExit(f"{sid}: the held-out match is never read by this task")
    if sid not in SCORED:
        raise SystemExit(f"{sid}: neither a development match nor a 2026-10-07 replay capture")


def rows_path(tag: str, sid: str) -> Path:
    return (STORE / "events" / "minimap_object" / f"{sid}.jsonl" if tag == "stored"
            else OUT / tag / f"{sid}.jsonl")


def ping_path(ptag: str, sid: str) -> Path:
    return OUT / ptag / "ping" / f"{sid}.jsonl"


class _Redirect(type(Path())):
    """A store root whose `events/minimap_object` is another folder, and whose
    other `events/<stream>` folders named in `streams` are others too
    (`question_acceptance` points `enemy_track` at the tracks it built)."""

    target: Path | None = None
    streams: dict = {}

    def with_segments(self, *segs):
        p = type(self)(*segs)
        if len(p.parts) >= 2 and p.parts[-2] == "events" and Path(*p.parts[:-2]) == STORE:
            if p.parts[-1] == "minimap_object" and _Redirect.target is not None:
                return Path(_Redirect.target)
            if p.parts[-1] in _Redirect.streams:
                return Path(_Redirect.streams[p.parts[-1]])
        return p


def _point_store(tag: str):
    """Point the scoring prototypes' STORE at the tag's rows."""
    from . import sets as elc
    from . import schedule as rrs
    from . import clock as rt
    from . import draw as tdr

    _Redirect.target = None if tag == "stored" else rows_path(tag, DEV[0]).parent
    root = _Redirect(STORE)
    for m in (elc, rrs, rt, tdr):
        m.STORE = root


def _pings(sid: str, ptag: str | None = None) -> np.ndarray:
    """Confirmed pings (t0, t1, x, y) in capture ms and widget px: the stored
    stream, or with `ptag` that `pings` reread."""
    p = STORE / "events" / "ping" / f"{sid}.jsonl" if ptag is None else ping_path(ptag, sid)
    on, out = {}, []
    if p.is_file():
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("event_kind") == "entity_state":
                on[r["entity_id"]] = (r["t_ms"], r["position"])
            elif r.get("event_kind") == "entity_deleted" and r["entity_id"] in on:
                t0, (x, y) = on.pop(r["entity_id"])
                out.append((t0, r["t_ms"], x, y))
    return np.asarray(out, float).reshape(-1, 4)


#: The extras classes that are true false accepts (no living enemy near).
TRUE_FA = ("ping", "x_mark", "other")


def class_extras(sid: str, tag: str, R: dict, ptag: str | None = None) -> list[dict]:
    """`R["extras"]` (from `enemy_lane_check.build_sets`), each with its class
    `cls` (the module docstring's extras classes) from the tag's rows and the
    confirmed pings (the stored stream, or with `ptag` that reread)."""
    from reticle import minimap_objects as mo

    scale = float(R["info"]["scale"])
    pings = _pings(sid, ptag)
    frames = {}
    want = {e["frame_idx"] for e in R["extras"]}
    for line in rows_path(tag, sid).open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("kind") == "frame" and r["frame_idx"] in want:
            frames[r["frame_idx"]] = r
    near_px = mo.ICON_PX * scale
    out = []
    for e in R["extras"]:
        d = e["nearest_enemy_m"]
        alive = e["nearest_enemy_alive"]
        x, y = e["icon_px"]
        if alive and d is not None and d * 100 <= NEAR_CM:
            c = "visible_undrawn"
        elif alive and d is not None and d * 100 <= OFFSET_CM:
            c = "enemy_3_8m"
        elif not alive and d is not None and d * 100 <= NEAR_CM:
            c = "dead_enemy"
        else:
            t = e["t_cap"]
            on = (pings[:, 0] <= t) & (t <= pings[:, 1]) if pings.size else np.zeros(0, bool)
            fr = frames.get(e["frame_idx"], {})
            xs = [(q["x"], q["y"]) for col in ("blue", "red")
                  for q in (fr.get("x_marks") or {}).get(col, [])]
            if on.any() and np.hypot(pings[on, 2] - x, pings[on, 3] - y).min() <= near_px:
                c = "ping"
            elif any(math.hypot(a - x, b - y) <= mo.X_OWN_PX * scale for a, b in xs):
                c = "x_mark"
            else:
                c = "other"
        out.append(dict(e, cls=c))
    return out
