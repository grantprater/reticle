"""Smokes on the minimap: births, lifetimes and censored ends from stored masks.

Pure over `minimap_dark` rows: no frame is decoded here. A smoke is a grey
dark region that persists; each is a track with a birth, a last sighting and an
end that is either OBSERVED (the disc was seen clear) or CENSORED (the widget
vanished, the disc was covered, or the capture ended before it was seen clear).
A censored end is an interval, never a point: a missing frame is not evidence
that a smoke persisted or ended.

Three rules, each from a failure seen on `a06f04a0059f` on 2026-09-24
---------------------------------------------------------------------
* **A birth is a component of at least `AREA_MIN_REF` px** (scaled to the
  widget) of grey dark floor not already inside a live track.
* **After birth a track is judged by the dark share of its own disc,** not by
  finding its component again. A smoke's hatched texture keeps its component
  near the area floor, and re-detection split one smoke into three tracks.
* **Covered is not gone.** A disc mostly under an icon, a frame with no
  widget, or a gap in sampling ages nothing and censors the end if it comes
  last; a disc not visible in the sample before its birth has a censored onset.

On four match rounds this kept six tracks, all smokes, with observed ends of
18.0 s against the Miks disc's 18.2 s [domain:abilities/miks-smoke-minimap-disc].
Smokes are not yet named. Only the player's team's smokes are drawn
[domain:abilities/enemy-smokes-not-on-minimap], and a smoke can be attributed
only by a lone team smoke agent, the player's own tray, or its lifetime
[domain:abilities/smoke-attribution]; that is the next step.

Owns [owns:minimap-smoke].
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..lighting import unpack_mask
from ..minimap import widget_scale
from ..version import SMOKE_VERSION

#: Smallest birth component on the reference widget, as `lighting.MIN_BLOB_PX`.
AREA_MIN_REF = 150
#: A component larger than this share of the known floor is the widget changing
#: (a menu overlay dims every pixel), not an object; the frame is unobserved.
GLOBAL_FRAC = 0.05
#: Dark share of a track's disc at which it is present.
PRESENT_FRAC = 0.3
#: A disc with less than this share visible is covered, not read.
VISIBLE_MIN = 0.3
#: The disc read for presence, as a share of the birth radius.
DISC_FRAC = 0.7
#: Clear this long, all observed, ends a track.
GONE_S = 1.0
#: Shortest track kept.
MIN_LIFE_S = 1.0
#: A gap between stored rows longer than this many sample periods is unobserved
#: time, the rule `adjudication.phases` applies to its own traces. The scan
#: samples only active spans, and a span that ended mid-smoke read as its end.
MAX_GAP_PERIODS = 3.0


def tracks(rows: list[dict], known: np.ndarray) -> list[dict]:
    """Smoke tracks from one session's `minimap_dark` rows, in time order."""
    frames = sorted((r for r in rows if r.get("kind") == "frame"), key=lambda r: r["t_ms"])
    head = next((r for r in rows if r.get("kind") == "coverage"), {})
    hz = float(head.get("hz") or 4.0)
    gone_n = max(1, math.ceil(GONE_S * hz))
    H, W = known.shape
    YY, XX = np.ogrid[:H, :W]
    sc = widget_scale(W)
    area_min = AREA_MIN_REF * sc * sc
    open_k = np.ones((3, 3), np.uint8)
    live: list[dict] = []
    done: list[dict] = []
    period_ms = 1000.0 / hz
    prev_t: float | None = None
    prev_occ: np.ndarray | None = None      # None: the previous sample was unobserved
    prev_gd: np.ndarray | None = None

    def close(tr, status, bound_ms):
        tr["end_status"] = status
        tr["end_bound_ms"] = bound_ms
        done.append(tr)

    def unobserved(t):
        for tr in live:
            tr["unseen_after"] = t
            tr["samples_unobserved"] += 1

    for f in frames:
        t = float(f["t_ms"])
        gap = prev_t is not None and t - prev_t > MAX_GAP_PERIODS * period_ms
        prev_t = t
        if gap:
            unobserved(t)
            prev_occ = None
        if f.get("widget_drawn") is not True:
            unobserved(t)
            prev_occ = None
            continue
        gd = unpack_mask(f["grey_dark"])
        occ = unpack_mask(f["occluded"])
        dk = cv2.morphologyEx((gd & ~occ).astype(np.uint8), cv2.MORPH_OPEN, open_k)
        n, _, st, cen = cv2.connectedComponentsWithStats(dk, 8)
        if any(st[i, 4] > GLOBAL_FRAC * known.sum() for i in range(1, n)):
            unobserved(t)
            prev_occ = None
            continue
        for tr in live:
            disc = ((XX - tr["cx"]) ** 2 + (YY - tr["cy"]) ** 2 <= (DISC_FRAC * tr["r"]) ** 2) & known
            seen = disc & ~occ
            if seen.sum() < VISIBLE_MIN * max(1, disc.sum()):
                tr["unseen_after"] = t
                tr["samples_unobserved"] += 1
            elif gd[seen].mean() >= PRESENT_FRAC:
                tr.update(last_ms=t, miss=0)
                tr["samples_present"] += 1
                tr.pop("unseen_after", None)
            else:
                tr["miss"] += 1
        for tr in [tr for tr in live if tr["miss"] >= gone_n]:
            live.remove(tr)
            censored = tr.get("unseen_after", -1.0) > tr["last_ms"]
            close(tr, "censored:unobserved" if censored else "observed", t)
        for i in range(1, n):
            a = int(st[i, 4])
            if a < area_min:
                continue
            cx, cy = float(cen[i][0]), float(cen[i][1])
            if any(math.hypot(cx - tr["cx"], cy - tr["cy"]) <= max(8.0 * sc, tr["r"]) for tr in live):
                continue
            r = math.sqrt(a / math.pi)
            # An onset is observed only if the previous sample SAW this disc
            # clear. A smoke first counted as a teammate walks off it, or after a
            # gap, was there before its birth, merely too covered to be born.
            disc = ((XX - cx) ** 2 + (YY - cy) ** 2 <= (DISC_FRAC * r) ** 2) & known
            onset_seen = False
            if prev_occ is not None:
                prev_seen = disc & ~prev_occ
                onset_seen = (prev_seen.sum() >= VISIBLE_MIN * max(1, disc.sum())
                              and prev_gd[prev_seen].mean() < PRESENT_FRAC)
            live.append({"first_ms": t, "last_ms": t, "cx": cx, "cy": cy, "r": r,
                         "birth_area": a, "miss": 0, "samples_present": 1,
                         "samples_unobserved": 0,
                         "onset_status": "observed" if onset_seen else "censored:unobserved"})
        prev_occ, prev_gd = occ, gd
    for tr in live:
        close(tr, "censored:capture_end", None)
    out = []
    for i, tr in enumerate(sorted(done, key=lambda d: d["first_ms"])):
        life = (tr["last_ms"] - tr["first_ms"]) / 1000.0
        if life < MIN_LIFE_S:
            continue
        out.append({"track": i, "first_ms": tr["first_ms"], "last_ms": tr["last_ms"],
                    "life_s": round(life, 3), "onset_status": tr["onset_status"],
                    "end_status": tr["end_status"],
                    "end_bound_ms": tr["end_bound_ms"],
                    "cx": round(tr["cx"], 1), "cy": round(tr["cy"], 1), "r": round(tr["r"], 1),
                    "birth_area": tr["birth_area"], "samples_present": tr["samples_present"],
                    "samples_unobserved": tr["samples_unobserved"]})
    return out


def events(session_id: str, rows: list[dict], known: np.ndarray) -> list[dict]:
    """`smoke` rows: one coverage row, then one row per track."""
    src = next((r for r in rows if r.get("kind") == "coverage"), {})
    got = tracks(rows, known)
    common = {"session_id": session_id, "smoke_version": SMOKE_VERSION,
              "minimap_dark_version": src.get("minimap_dark_version"),
              "geometry_key": src.get("geometry_key")}
    head = {**common, "kind": "coverage", "tracks": len(got),
            "observed_ends": sum(t["end_status"] == "observed" for t in got)}
    return [head] + [{**common, "kind": "track", **t} for t in got]
