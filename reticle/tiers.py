"""The fast verification tier: a few sessions with known answers, in minutes.

The middle tier between the unit tests and a corpus run (player, 2026-09-23),
and the default sanity check after a change. `reticle verify --tier fast` runs
the checks declared in `FAST`, in order, and prints each one's number beside
its known answer and that answer's source.

Every check reads storage and the crop cache only; nothing here decodes video
or writes to the store. Two kinds of check are kept apart:

* **accuracy** compares the current code's answer with a known answer from the
  player or a source-verified label: the player's cast census and grouping
  labels on the Omen demo, `checks.KNOWN_KD`, and the round 4 fixture's oracle.
  The pipeline's own stored output is never the known answer.
* **consistency** reruns a reader on a bounded slice and diffs it against the
  stored rows (`trial`). Agreement says only that the stored rows reproduce
  under the current code, which is what the accuracy checks that read them
  assume; it says nothing about whether they are right.

Stamp-aware. Readers whose input fits in the crop cache (the tray, the dark
regions on the minimap) are recomputed with the current code, and every
adjudication is recomputed from its stored inputs. A check that must read
stored reader rows compares their stamp with the code's first; a stored stamp
the code has moved past reports STALE, with the command that refreshes it,
never PASS.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

OMEN_DEMO = "e78e75b2d191"
MATCH = "a06f04a0059f"
#: Round 4 of `MATCH`, the slice the round 4 fixture covers
#: (`tests/test_round_identity_e2e.py` asserts these bounds).
ROUND4_MS = (232000.0, 351000.0)

#: A recomputed tray drop matches a labelled cast in the same slot within this.
DROP_TOL_MS = 1000.0
#: A smoke track matches a labelled disc when its centre lies within this.
DISC_TOL_PX = 12.0
#: A Dark Cover's disc shows 2-4 s after the tray drop, its target icon from
#: 0.5 s [domain:abilities/omen-dark-cover-minimap-phases]; a track born in
#: this window after a labelled drop is that cast's.
SMOKE_BIRTH_MS = (500.0, 4500.0)

PASS, FAIL, STALE = "PASS", "FAIL", "STALE"


@dataclass(frozen=True)
class Check:
    id: str
    session: str
    kind: str            # "accuracy" or "consistency"
    source: str          # where the known answer comes from
    run: Callable        # (store) -> dict with status, measured, known, detail


def _result(status: str, measured, known, detail: str = "") -> dict:
    return {"status": status, "measured": measured, "known": known, "detail": detail}


def _label_file(store, name: str, sid: str) -> list[dict]:
    path = store.root / "labels" / name / f"{sid}.jsonl"
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _minimap_cache(store, sid: str):
    from .profiles import get_profile
    from .roi_cache import RoiCache
    man = store.read_manifest(sid)
    cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
    return man, cache, why


# --------------------------------------------------------------------------- Omen demo

def omen_player_casts(store) -> list[dict]:
    """The player's answers in the demo cast census: one row per cast the
    player named after comparing its montage with the derived reading."""
    return [r for r in _label_file(store, "demo_cast_class", OMEN_DEMO) if r.get("by") == "player"]


def match_drops(drops: list[dict], casts: list[dict], tol_ms: float = DROP_TOL_MS) -> dict:
    """Each labelled cast to the nearest unused drop in its slot within `tol_ms`."""
    used: set[int] = set()
    missed = []
    for c in sorted(casts, key=lambda c: c["t_ms"]):
        best = None
        for i, d in enumerate(drops):
            if i in used or d["slot"] != c["slot"]:
                continue
            dt = abs(float(d["t_ms"]) - float(c["t_ms"]))
            if dt <= tol_ms and (best is None or dt < best[1]):
                best = (i, dt)
        if best is None:
            missed.append(f"{c['slot']}@{c['t_ms'] / 1000:.1f}s")
        else:
            used.add(best[0])
    extra = [f"{d['slot']}@{d['t_ms'] / 1000:.1f}s" for i, d in enumerate(drops) if i not in used]
    return {"found": len(casts) - len(missed), "missed": missed, "extra": extra}


def check_omen_tray(store) -> dict:
    from . import tray
    from .cli import _tray_samples
    casts = omen_player_casts(store)
    if not casts:
        return _result(FAIL, None, None, "no player labels in labels/demo_cast_class")
    _, cache, why = _minimap_cache(store, OMEN_DEMO)
    if cache is None:
        return _result(STALE, None, len(casts), f"no minimap crop cache ({why})")
    ts, counts, clean, _ = _tray_samples(cache, 0.5)
    drops = tray.drops(ts, np.asarray(counts, float), np.asarray(clean, bool))
    m = match_drops(drops, casts)
    ok = not m["missed"] and not m["extra"]
    detail = (f"missed {m['missed'] or 'none'}; drops no label names {m['extra'] or 'none'}")
    return _result(PASS if ok else FAIL, f"{m['found']}/{len(casts)} casts, "
                   f"{len(m['extra'])} unlabelled drops", f"{len(casts)} casts", detail)


def dark_cover_discs(store, tol_px: float = DISC_TOL_PX) -> list[tuple[float, float]]:
    """Centres of the Dark Cover discs the player grouped as one entity,
    in minimap crop pixels, one per cluster of labelled components."""
    pts = [(float(r["x"]), float(r["y"])) for r in _label_file(store, "ability_grouping", OMEN_DEMO)
           if r.get("by") == "human" and r.get("ability_id") == "omen:dark cover"
           and r.get("answer") == "same_entity"]
    clusters: list[list[tuple[float, float]]] = []
    for p in pts:
        for c in clusters:
            if np.hypot(p[0] - c[0][0], p[1] - c[0][1]) <= tol_px:
                c.append(p)
                break
        else:
            clusters.append([p])
    return [tuple(np.mean(c, axis=0).tolist()) for c in clusters]


def omen_smoke_tracks(store) -> tuple[list[dict] | None, str]:
    """Smoke tracks on the Omen demo from `minimap_dark` recomputed on the
    crop cache at `scan`'s 4 Hz, then `adjudication.smokes`. Writes nothing."""
    from . import geometry, lighting
    from .adjudication.smokes import events as smoke_events
    from .cli import _cache_grid
    from .minimap import minimap_roi_px
    from .minimap_dark import DarkRegionReader
    from .passes import SessionContext
    from .profiles import get_profile

    man, cache, why = _minimap_cache(store, OMEN_DEMO)
    if cache is None:
        return None, f"no minimap crop cache ({why})"
    profile = get_profile(man["source_profile"])
    ctx = SessionContext(store=store, manifest=man, profile=profile)
    with np.load(geometry.path_of(OMEN_DEMO, store.root)) as z:
        ref = lighting.reference(z)
    if ref is None:
        return None, "geometry has no lighting reference"
    reader = DarkRegionReader(floor=ctx.floor(), sgray=ctx.sgray(), static=ctx.map_reference(),
                              ref=ref, box=minimap_roi_px(profile, *ctx.wh), hz=4.0)
    t = cache.t_ms
    for smp in cache.samples(_cache_grid(t, float(np.min(t)), float(np.max(t)), 1 / reader.hz),
                             rois="minimap"):
        reader.feed(smp)
    rows = [json.loads(json.dumps(r, allow_nan=False))
            for r in reader.events(OMEN_DEMO, geometry.key_of(OMEN_DEMO, store.root))]
    return smoke_events(OMEN_DEMO, rows, ref.known)[1:], ""


def check_omen_smokes(store) -> dict:
    discs = dark_cover_discs(store)
    drops = [float(c["t_ms"]) for c in omen_player_casts(store) if c.get("ability") == "Dark Cover"]
    if not discs or not drops:
        return _result(FAIL, None, None, "no Dark Cover labels")
    tracks, why = omen_smoke_tracks(store)
    if tracks is None:
        return _result(STALE, None, len(discs), why)
    lo, hi = SMOKE_BIRTH_MS
    matched, missed = set(), []
    for x, y in discs:
        hit = next((i for i, tr in enumerate(tracks) if i not in matched
                    and np.hypot(tr["cx"] - x, tr["cy"] - y) <= DISC_TOL_PX
                    and any(lo <= tr["first_ms"] - d <= hi for d in drops)), None)
        if hit is None:
            missed.append(f"({x:.0f},{y:.0f})")
        else:
            matched.add(hit)
    extra = [f"({tr['cx']:.0f},{tr['cy']:.0f}) from {tr['first_ms'] / 1000:.1f}s"
             for i, tr in enumerate(tracks) if i not in matched]
    got = "; ".join(f"({tr['cx']:.0f},{tr['cy']:.0f}) {tr['first_ms'] / 1000:.1f}-"
                    f"{tr['last_ms'] / 1000:.1f}s" for tr in tracks)
    ok = not missed and not extra
    return _result(PASS if ok else FAIL, f"{len(matched)}/{len(discs)} discs, "
                   f"{len(extra)} other tracks", f"{len(discs)} discs",
                   f"tracks {got or 'none'}; missed {missed or 'none'}")


# --------------------------------------------------------------------------- a06f04a0059f

def _stored_stamps(store, sid: str, date: str) -> dict[str, tuple[str | None, str]]:
    """(stored stamp, current stamp) for each stored reader stream the
    match's accuracy checks read."""
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .version import COMBAT_REPORT_VERSION, HUD_VERSION
    hud = store.read_hud(sid, date)
    meta = (hud.schema.metadata or {}) if hud is not None else {}
    return {"hud": ((meta.get(b"hud_version") or b"").decode() or None, HUD_VERSION),
            "killfeed_portrait": (store.events_version("killfeed_portrait", sid),
                                  KILLFEED_PORTRAIT_VERSION),
            "combat_report": (store.events_version("combat_report", sid), COMBAT_REPORT_VERSION)}


def match_kd(store, sid: str = MATCH) -> tuple[tuple[int, int] | None, str]:
    """The player's K/D from the combat report verdict, with the rounds
    rebuilt from the stored HUD reads by the current `rounds.build_rounds`."""
    from .adjudication.combat_report import events as report_events
    from .adjudication.death import stored_second_life
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .rounds import build_rounds, player_death_times

    man = store.read_manifest(sid)
    date = man["ingested_at"][:10]
    stale = {k: v for k, v in _stored_stamps(store, sid, date).items() if v[0] != v[1]}
    if stale:
        return None, "stored " + ", ".join(f"{k} {a} != code {b}" for k, (a, b) in stale.items()) \
            + f" -- refresh with `reticle scan {sid} --only hud` / `--only combat_report`"
    hud = store.read_hud(sid, date)
    second_life = stored_second_life(store.read_events("killfeed_portrait", sid),
                                     KILLFEED_PORTRAIT_VERSION)
    rounds = build_rounds(hud, second_life)
    head = report_events(sid, store.read_events("combat_report", sid), rounds,
                         player_death_times(hud))[0]
    return (head["kills_verdict"], head["deaths_verdict"]), (
        f"{len(rounds)} rounds rebuilt, {head['verdict_from_killfeed']} from the killfeed")


def check_match_kd(store) -> dict:
    from .checks import KNOWN_KD
    known = KNOWN_KD[MATCH]
    kd, detail = match_kd(store)
    if kd is None:
        return _result(STALE, None, f"{known[0]}/{known[1]}", detail)
    return _result(PASS if tuple(kd) == tuple(known) else FAIL, f"{kd[0]}/{kd[1]}",
                   f"{known[0]}/{known[1]}", detail)


def _trial_check(reader: str, stamp_stream: str):
    def run(store) -> dict:
        from .trial import run as trial_run
        man = store.read_manifest(MATCH)
        stored, current = _stored_stamps(store, MATCH, man["ingested_at"][:10])[stamp_stream]
        res = trial_run(store, man, reader=reader, source="cache", windows="all",
                        between=ROUND4_MS)
        same = sum(d["same"] for d in res["diff"].values())
        differ = sum(d["only_trial"] + d["only_stored"] for d in res["diff"].values())
        detail = f"{res['frames']} frames; " + "; ".join(
            f"{s} {d['same']} same, {d['only_trial']} only trial, {d['only_stored']} only stored"
            for s, d in res["diff"].items())
        if stored != current:
            return _result(STALE, f"{same} rows same, {differ} differ", "0 differ",
                           f"stored {stamp_stream} {stored} != code {current}; {detail}")
        return _result(PASS if differ == 0 else FAIL, f"{same} rows same, {differ} differ",
                       "0 differ", detail)
    return run


_SUMMARY = re.compile(r"Ran (\d+) tests? in")


def check_round4_fixture(store) -> dict:
    """The round 4 fixture test, run as its own process: the fixture helpers
    live in `prototypes/`, which `reticle/` never imports."""
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                           "-p", "test_round_identity_e2e.py"],
                          cwd=root, capture_output=True, text=True)
    tail = proc.stderr.strip().splitlines()
    ran = next((int(m.group(1)) for line in tail if (m := _SUMMARY.search(line))), None)
    last = tail[-1] if tail else ""
    skipped = int(m.group(1)) if (m := re.search(r"skipped=(\d+)", last)) else 0
    ok = proc.returncode == 0 and ran is not None and skipped == 0
    return _result(PASS if ok else FAIL, f"{ran} tests: {last}", "all pass, none skipped",
                   "" if ok else "\n".join(tail[-12:]))


FAST: tuple[Check, ...] = (
    Check("omen-demo/tray-casts", OMEN_DEMO, "accuracy",
          "the player's cast census answers, labels/demo_cast_class (by player)",
          check_omen_tray),
    Check("omen-demo/dark-cover-smokes", OMEN_DEMO, "accuracy",
          "the player's grouping labels (omen:dark cover, same_entity) and census E casts",
          check_omen_smokes),
    Check("match/known-kd", MATCH, "accuracy",
          "checks.KNOWN_KD, the end screen and match history (player, 2026-08-25)",
          check_match_kd),
    Check("match/round4-identity-fixture", MATCH, "accuracy",
          "tests/test_round_identity_e2e.py oracle, source-verified by the player",
          check_round4_fixture),
    Check("match/round4-killfeed-reproduces", MATCH, "consistency",
          "stored killfeed_portrait/weapon/name rows (a baseline, not a known answer)",
          _trial_check("killfeed", "killfeed_portrait")),
    Check("match/round4-hud-reproduces", MATCH, "consistency",
          "the stored HUD table (a baseline, not a known answer)",
          _trial_check("hud", "hud")),
)

TIERS = {"fast": FAST}


def run(store, tier: str = "fast", only: str | None = None) -> list[dict]:
    """Run every check in `tier` (or the one named `only`); one dict each."""
    out = []
    for c in TIERS[tier]:
        if only and c.id != only:
            continue
        t0 = time.perf_counter()
        try:
            r = c.run(store)
        except Exception as e:   # a crash is a finding, reported beside the rest
            r = _result(FAIL, None, None, f"raised {type(e).__name__}: {e}")
        out.append({"id": c.id, "session": c.session, "kind": c.kind, "source": c.source,
                    "seconds": round(time.perf_counter() - t0, 1), **r})
    return out
