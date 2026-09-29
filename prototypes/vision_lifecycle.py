r"""Why the lifecycle gate withholds cones the drawn light confirms (E8).

    .\.venv\Scripts\python.exe prototypes\vision_lifecycle.py replay [SID ...]
    .\.venv\Scripts\python.exe prototypes\vision_lifecycle.py reasons [SID ...]
    .\.venv\Scripts\python.exe prototypes\vision_lifecycle.py study [SID ...] --which studied|heldout|heldout2
    .\.venv\Scripts\python.exe prototypes\vision_lifecycle.py sheets [SID ...]
    .\.venv\Scripts\python.exe prototypes\vision_lifecycle.py report [SID ...] [--record]

Task `vision-lifecycle-20260929`, E8 of
[the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md). E7 found
that `minimap_lifecycle` quarantines a large share of the light team vision
misses. `team_vision` computes the lifecycle's `adjudication` rows and stores
only each icon's `eligible` flag, so the reason is unread. This replays the
chain in memory, reads it, and prototypes a gate change
(`CorroboratedLifecycle`: the roster and the player's death, never the
light) with the stored-row schema it proposed, now promoted to
`minimap_lifecycle.adjudication_record` (lifecycle 0.3.0, which also wires
the gate; this file measured it against 0.2.0).
Default sessions: 5822b6646448 (Lotus) and c40d950031bb (Ascent, 331 px).

**study** scores the stored gate, the gate off, and the gate variants against
E7's `all` witness (`team_vision_errors.frame_errors`, whose cones and light
it reuses), on E7's windows (`studied`, the design set) or on windows between
them (`heldout`, `heldout2`), and gives each quarantined icon's cone a light
verdict (`light_verdict`). **sheets** draws quarantined icons from the studied
frames into the store's `analysis/vision-lifecycle-20260929/`. **report**
prints the tables, writes the proposed adjudication rows to `--work`, and
with `--record` one `metrics` row.

**The light is evidence only for scoring.** No gate here reads it, so a cone
a gate releases is scored against a witness the gate never saw.

**replay** runs `team_vision.TeamVision` over a session's whole minimap crop
cache, in time order, with `masks=False` (the lifecycle reads no mask), and
keeps every adjudication row with what the lifecycle saw when it decided: the
live anchors of the icon's role, the boundary flag, and the icon's own last
row. It checks the instrument: each recomputed icon's `eligible` must equal
the stored `team-vision-0.3.0` row's at the same frame. The replay goes to
`--work` as a pickle; nothing is written to the store.

**reasons** gives every quarantined row one ENTRY cause, fixed before the
run, read at the frame its key first went ineligible; the rows after it
inherit it (a quarantined key has no anchor of its own, so it stays
quarantined until it walks within reach of another entity's anchor):

    ambiguous       two or more anchors of its role could be its parent
    jump            its own key was eligible within the gap budget, and no
                    anchor admits the step: the tracker kept the track (a
                    refit, `track.refit_of`, or its own slack) where the
                    lifecycle's motion law refused it
    gap_reborn      an eligible row of its role ended within walking reach
                    of this point, but longer ago than the gap budget
                    (500 ms): the anchor expired while the icon was unseen
    gap_same_key    as gap_reborn, but the tracker kept the SAME key across
                    the gap
    far             no eligible row of its role, of any age, can reach it:
                    a birth with no origin event (round start, revive) or a
                    false icon

That taxonomy failed: `gap_reborn` took nearly every entry, because the last
eligible row of a role, minutes old, is always within walking reach. The
report uses `mechanism`, read from the same stored view: `no_live_anchor_of_role`
(no eligible row of the icon's role in the last 500 ms, while another role's
anchor keeps the boundary shut), `beyond_reach` (live anchors of its role, none
admits it), `ambiguous`, `jump`.

It decodes no video; it reads the crop cache and stored rows only, runs at
Idle priority on one thread, and writes to the store only the sheets, and
with `--record` one metrics row.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, stalls, team_vision  # noqa: E402
from reticle.minimap_lifecycle import ROLE_MOTION, adjudication_record  # noqa: E402,F401  (promoted)
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from reticle.track import CLASSES, admits, association_tolerance  # noqa: E402

VERSION = "vision-lifecycle-0.1.0"
STORE = Path(DEFAULT_STORE)
SESSIONS = ("5822b6646448", "c40d950031bb")
TAGS = {"5822b6646448": "lotus", "c40d950031bb": "c40d", "e78e75b2d191": "e78e"}
WORK = Path(tempfile.gettempdir()) / "vision-lifecycle"
ENTRY = ("ambiguous", "jump", "gap_same_key", "gap_reborn", "far")


def idle() -> None:
    # The handle types matter: with ctypes' default int the call returned
    # without effect and the process stayed at Normal.
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)      # IDLE_PRIORITY_CLASS
    except Exception:
        pass
    cv2.setNumThreads(1)


def _log(msg):
    print(msg, flush=True)


def session_inputs(sid: str):
    man = geometry.manifest(sid, STORE)
    prof = get_profile(man["source_profile"])
    w, h = int(man["source"]["width"]), int(man["source"]["height"])
    inputs, why = team_vision.load_inputs(STORE, sid, prof, w, h)
    if inputs is None:
        raise SystemExit(f"{sid}: {why}")
    inputs.stalls = stalls.for_session(Store(STORE), sid, man["ingested_at"][:10])
    cache, why = RoiCache.load(STORE, man, prof, "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no minimap crop cache ({why})")
    return man, inputs, cache


def stored_rows(sid: str) -> dict:
    """The stored team_vision frame rows' icons, by time (masks dropped)."""
    out = {}
    with open(Store(STORE).events_path("team_vision", sid), encoding="utf-8") as f:
        for ln in f:
            if '"kind":"frame"' not in ln[:200]:
                continue
            r = json.loads(ln)
            out[float(r["t_ms"])] = {"widget": r["widget"], "icons": [
                {k: ic.get(k) for k in ("role", "track_id", "x", "y", "facing", "eligible",
                                        "casts", "interpolated")}
                for ic in r.get("icons") or []]}
    return out


def reach_of(row: dict, a: dict, t: float, sc: float) -> dict:
    """How far anchor `a` is from `row` against the role's motion law
    (`track.admits` with `association_tolerance`, the lifecycle's own test)."""
    motion = CLASSES[ROLE_MOTION.get(row["role"], "static")]
    dt = (t - a["t_ms"]) / 1000.0
    dist = math.hypot(row["x"] - a["x"], row["y"] - a["y"])
    slack = association_tolerance(sc, r_a=row.get("r"), r_b=a.get("r"))
    walk = motion.max_px_s * sc * dt if motion.max_px_s else 0.0
    ok = admits(motion, max(0.0, dist - slack), dt, sc)[0]
    return {"dist": round(dist, 2), "dt_ms": round(t - a["t_ms"], 1),
            "excess": round(dist - slack - walk, 2), "ok": bool(ok),
            "entity": a["entity_id"], "key": a["observation_key"]}


def nearest_anchors(row: dict, t: float, live: list, sc: float, n: int = 3) -> list:
    return sorted((reach_of(row, a, t, sc) for a in live if a["role"] == row["role"]),
                  key=lambda d: d["excess"])[:n]


class Witness:
    """Wraps a `Lifecycle.step` and keeps what it saw at each decision."""

    def __init__(self, lifecycle):
        self.lc = lifecycle
        self._step = lifecycle.step
        lifecycle.step = self.step
        self.frames: list[dict] = []
        #: The last eligible row per (role, entity), of any age.
        self.last_eligible: dict = {}

    def step(self, frame, events=()):
        t = frame["t_ms"]
        live = [a for a in self.lc.anchors if t - a["t_ms"] <= self.lc.max_gap_ms]
        boundary = self.lc.boundary or not live
        before = dict(self.lc.known)
        rows = self._step(frame, events)
        # The lifecycle's own input, kept so a gate variant replays from it
        # with no pixels: adjudication stays pure over stored observations.
        inp = {"t_ms": t, "widget": frame["widget"],
               "light_budget": frame.get("light_budget"),
               "observations": [{k: o.get(k) for k in ("role", "track_id", "x", "y", "r",
                                                       "position_state", "light_support",
                                                       "facing")}
                                for o in frame.get("observations", [])]}
        rec = {"t": t, "widget": frame["widget"], "boundary": boundary, "rows": [],
               "input": inp}
        for row in rows:
            r = {k: row[k] for k in ("observation_key", "x", "y", "r", "role", "entity_id",
                                     "state", "eligible", "light_state", "conflict",
                                     "alternatives", "reason")}
            if not row["eligible"]:
                r["seen"] = self._seen(row, t, live, before)
            rec["rows"].append(r)
        for row in rows:
            if row["eligible"]:
                self.last_eligible[(row["role"], row["entity_id"])] = row
        obs = {f"{o['role']}:{o['track_id']}": o for o in frame.get("observations", [])}
        for r in rec["rows"]:
            o = obs.get(r["observation_key"]) or {}
            r["light_support"] = o.get("light_support")
        self.frames.append(rec)
        return rows

    def _seen(self, row, t, live, before):
        """What the lifecycle had to go on when it refused this row."""
        sc = self.lc.scale

        def reach(a):
            return reach_of(row, a, t, sc)

        anchors = nearest_anchors(row, t, live, sc, n=3)
        old = before.get(row["observation_key"])
        own = None
        if old is not None:
            own = {"eligible": bool(old["eligible"]), "state": old["state"],
                   "dt_ms": round(t - old["t_ms"], 1),
                   "dist": round(math.hypot(row["x"] - old["x"], row["y"] - old["y"]), 2)}
        # The nearest eligible row of the role ever seen, past the gap budget too.
        ever = sorted((reach(a) for (role, _e), a in self.last_eligible.items()
                       if role == row["role"]), key=lambda d: d["excess"])
        return {"anchors": anchors[:3], "own": own, "ever": ever[:2]}


def replay(sid: str, log=_log) -> dict:
    """The chain over the whole crop cache; every adjudication row with its view."""
    man, inputs, cache = session_inputs(sid)
    x0, y0, x1, y1 = inputs.box
    vision = team_vision.TeamVision.from_inputs(inputs, distance_diagnostics=False)
    wit = Witness(vision.lifecycle)
    stored = stored_rows(sid)
    times = sorted({float(t) for t in cache.t_ms})
    check = Counter()
    t0 = time.time()
    icons = {}
    for n, smp in enumerate(cache.samples(times, rois=["minimap"])):
        fr = vision.step(smp.frame[y0:y1, x0:x1], smp.t_ms, masks=False)
        st = stored.get(float(smp.t_ms))
        mine = []
        for (role, tr), (x, y, deg, _c) in zip(fr.tracked, fr.resolved):
            mine.append({"role": role, "track_id": int(tr.tid), "x": float(x), "y": float(y),
                         "facing": None if deg is None else float(deg),
                         "eligible": f"{role}:{tr.tid}" in fr.eligible,
                         "observed": tr.t_ms == smp.t_ms, "born_ms": float(tr.born_t_ms)})
        icons[float(smp.t_ms)] = mine
        if st is None:
            check["no_stored_row"] += 1
        elif st["widget"] != fr.widget:
            check["widget_differs"] += 1
        else:
            a = sorted((i["role"], i["track_id"], i["eligible"]) for i in mine)
            b = sorted((i["role"], i["track_id"], i["eligible"]) for i in st["icons"])
            check["eligible_equal" if a == b else "eligible_differs"] += 1
        if (n + 1) % 2000 == 0:
            log(f"  {sid}: {n + 1}/{len(times)} frames, {time.time() - t0:.0f} s")
    log(f"{sid}: replayed {len(times)} frames in {time.time() - t0:.0f} s; check {dict(check)}")
    return {"sid": sid, "version": VERSION, "frames": wit.frames, "icons": icons,
            "check": dict(check), "scale": vision.scale, "width": x1 - x0,
            "capture": man["source"]["path"]}


def load_replay(sid: str, work: Path = WORK) -> dict:
    with open(work / f"{sid}.replay.pkl", "rb") as f:
        return pickle.load(f)


def entry_cause(seen: dict, state: str) -> str:
    """The entry cause of a quarantine, by the rules in the module docstring."""
    if state == "ambiguous_continuation":
        return "ambiguous"
    own = seen.get("own")
    if own and own["eligible"] and own["dt_ms"] <= 500.0:
        return "jump"
    ever = seen.get("ever") or []
    if ever and ever[0]["ok"]:
        return "gap_same_key" if own and own["eligible"] else "gap_reborn"
    return "far"


def mechanism(seen: dict, state: str) -> str:
    """The refusal read from what the lifecycle saw, after the run.

    The pre-registered `gap_reborn` proved vacuous: the last eligible row of a
    role, minutes old, is always within walking reach. What decided each
    refusal is whether a LIVE anchor (under 500 ms) of the icon's role existed.
    """
    if state == "ambiguous_continuation":
        return "ambiguous"
    own = seen.get("own")
    if own and own["eligible"] and own["dt_ms"] <= 500.0:
        return "jump"
    return "beyond_reach" if seen.get("anchors") else "no_live_anchor_of_role"


def reasons(rep: dict) -> list[dict]:
    """Every quarantined row with its entry cause; inherited rows name their entry."""
    entry_of = {}
    out = []
    for fr in rep["frames"]:
        for r in fr["rows"]:
            key = r["observation_key"]
            if r["eligible"]:
                entry_of.pop(key, None)
                continue
            if key not in entry_of:
                entry_of[key] = {"t": fr["t"], "cause": entry_cause(r["seen"], r["state"]),
                                 "mechanism": mechanism(r["seen"], r["state"]),
                                 "state": r["state"], "seen": r["seen"]}
                inherited = False
            else:
                inherited = True
            e = entry_of[key]
            out.append({"t": fr["t"], "key": key, "role": r["role"], "x": r["x"], "y": r["y"],
                        "state": r["state"], "reason": r["reason"], "cause": e["cause"],
                        "mechanism": e["mechanism"],
                        "entry_t": e["t"], "entry_state": e["state"], "inherited": inherited,
                        "light_state": r["light_state"], "seen": r["seen"],
                        "entry_seen": e["seen"]})
    return out


# ------------------------------------------------------------ the gate change

#: Roster reads this far before an instant stand with the one in force at the
#: window's start; the largest stands, because the count drops at a death
#: while the dying teammate's icon may still show (`round_entities`'s lag,
#: used causally here: no read after the instant).
ROSTER_LAG_MS = 500.0
UNEXPLAINED = ("unexplained_appearance", "unlit_unexplained_appearance")


class Witnesses:
    """The stored channels the gate change asks, for one session.

    `alive_ally` is the roster's count of living allies, the player included
    (owner `roster`, question `alive-count`); `player_deaths` are the stored
    death verdicts the killfeed marks as the player's own
    (`adjudication.death`, `kf_player_death`); `round_starts` are the HUD's
    round bounds (`rounds.build_rounds`). None of them reads the minimap's
    light, so a cone they release is scored against the light independently.
    """

    def __init__(self, sid: str):
        from reticle.rounds import build_rounds
        st = Store(STORE)
        date = geometry.manifest(sid, STORE)["ingested_at"][:10]
        self.rt, self.ra = [], []
        if st.has_roster(sid, date):
            t = st.read_roster(sid, date)
            self.rt, self.ra = t.column("t_ms").to_pylist(), t.column("alive_ally").to_pylist()
        rounds = [r for r in build_rounds(st.read_hud(sid, date)) if r.get("t_start_ms") is not None]
        self.round_starts = sorted(r["t_start_ms"] for r in rounds)
        self.round_no = {r["t_start_ms"]: r["round_no"] for r in rounds}
        # Each verdict carries the round the death adjudicator put it in: a
        # killfeed entry of the last round's end can fall after the HUD's next
        # round start, and a time test alone put it in the new round. A death
        # the adjudicator calls a second life (Run It Back) is not a death:
        # the player returns, and on Lotus the self icon drew light 5 s later.
        self.player_deaths = sorted(
            (float(r["t_ms"]), r["death_id"], r.get("round_no")) for r in st.read_events("death", sid)
            if r.get("kind") == "death_verdict" and r.get("kf_player_death")
            and not r.get("is_second_life"))

    def roster(self, t: float) -> list:
        """Reads in [t - ROSTER_LAG_MS, t] with the one in force before them."""
        import bisect
        lo = max(0, bisect.bisect_right(self.rt, t - ROSTER_LAG_MS) - 1)
        hi = bisect.bisect_right(self.rt, t)
        return [(self.rt[i], self.ra[i]) for i in range(lo, hi)]

    def round_start(self, t: float):
        import bisect
        i = bisect.bisect_right(self.round_starts, t) - 1
        return self.round_starts[i] if i >= 0 else None

    def player_died_since(self, t0: float, t: float):
        """The player's killfeed death in the round starting at `t0`, before `t`."""
        rn = self.round_no.get(t0)
        return next((d for d in self.player_deaths if d[2] == rn and d[0] <= t), None)


class CorroboratedLifecycle:
    """`minimap_lifecycle.Lifecycle` with a second witness for an unexplained
    appearance of a team icon. The stock rules run first and unchanged; only
    a row they refuse as an unexplained appearance can be admitted, and only
    on a channel that does not read the minimap:

    * **ally, by the roster** (`roster_admitted`): the roster licenses
      `round_lifetimes.ally_capacity` ally icons (the living allies less the
      player, only where the player's icon is observed), and every ally
      observed this frame, quarantined or not, fits inside it. A frame with
      more allies than the roster licenses admits none: one of them is not a
      teammate, and the count cannot say which.
    * **self, by the player being alive** (`alive_admitted`): the self tracker
      reports one principal (`track.Tracker.principal`), and the player is
      alive, by the roster reading all five allies alive or by no killfeed
      death of the player's since the round began.

    An admitted row keeps its refused state in `refused_as` and names its
    evidence in `admitted_by`; it becomes an anchor, so the key continues
    from then on. Nothing earlier is rewritten: the evidence precedes the
    promotion. The light is not consulted.
    """

    def __init__(self, witnesses: Witnesses, scale=1.0, ally=True, self_=True,
                 after_death=False):
        from reticle.minimap_lifecycle import Lifecycle
        self.lc = Lifecycle(scale=scale)
        self.w, self.ally, self.self_ = witnesses, ally, self_
        self.after_death = after_death
        self.max_gap_ms = self.lc.max_gap_ms

    def step(self, frame, events=()):
        from reticle.round_lifetimes import ally_capacity
        t = frame["t_ms"]
        live = [a for a in self.lc.anchors if t - a["t_ms"] <= self.lc.max_gap_ms]
        before = dict(self.lc.known)
        rows = self.lc.step(frame, events)
        if not rows:
            return rows
        for r in rows:
            # The stock refusal, named: which rule refused it and the nearest
            # live anchor of its role (`reason_code`, `nearest_anchor`).
            if r["eligible"]:
                continue
            near = nearest_anchors(r, t, live, self.lc.scale, n=1)
            old = before.get(r["observation_key"])
            own = None if old is None else {"eligible": bool(old["eligible"]),
                                            "dt_ms": t - old["t_ms"]}
            r["reason_code"] = mechanism({"anchors": near, "own": own}, r["state"])
            if old is not None and not old["eligible"]:
                # A quarantined key is no anchor, so it cannot continue itself.
                base = old.get("reason_code") or "unknown"
                r["reason_code"] = base if base.startswith("persisting:") else "persisting:" + base
            r["nearest_anchor"] = near[0] if near else None
        self_seen = any(r["role"] == "self" for r in rows)
        allies = [r for r in rows if r["role"] == "ally"]
        reads = self.w.roster(t)
        cap = ally_capacity([a for _t, a in reads], self_seen)
        for r in rows:
            if r["eligible"] or r["state"] not in UNEXPLAINED:
                continue
            why = None
            if r["role"] == "ally" and self.ally:
                if cap is None:
                    r["reason"] = ("roster unread or player's icon unobserved; "
                                   "origin or continuity needs corroboration")
                elif len(allies) > cap:
                    r["reason"] = (f"{len(allies)} allies observed, roster licenses {cap}; "
                                   "origin or continuity needs corroboration")
                else:
                    why = {"rule": "roster_capacity", "capacity": cap,
                           "allies_observed": len(allies),
                           "roster_reads": [[float(a), b] for a, b in reads]}
            elif r["role"] == "self" and self.self_:
                five = [a for _t, a in reads if a is not None]
                t0 = self.w.round_start(t)
                died = self.w.player_died_since(t0, t) if t0 is not None else None
                if five and max(five) >= 5:
                    why = {"rule": "roster_all_alive", "roster_reads": [[float(a), b] for a, b in reads]}
                elif t0 is not None and died is None:
                    why = {"rule": "no_player_death_this_round", "round_start_ms": t0}
                elif died is not None and self.after_death and five and max(five) >= 1:
                    # UNCONFIRMED MECHANIC, a variant only: after the player's
                    # death the yellow icon is taken to be the spectated
                    # teammate, a teammate whose cone is team vision.
                    why = {"rule": "spectated_teammate_assumed", "death_id": died[1],
                           "roster_reads": [[float(a), b] for a, b in reads]}
                else:
                    r["reason"] = ("player may be dead (" + (f"killfeed death {died[1]}" if died
                                   else "round unknown") + "); origin or continuity needs corroboration")
            if why is None:
                continue
            r.update(refused_as=r["state"], state="corroborated_appearance", eligible=True,
                     admitted_by=why, reason=None)
            self.lc.anchors.append(r)
        return rows


def corroborated_run(rep: dict, **kw) -> dict:
    return gate_run(rep, CorroboratedLifecycle(Witnesses(rep["sid"]), scale=rep["scale"], **kw))


# ------------------------------------------------------------ gates and scores

def gate_run(rep: dict, lifecycle) -> dict:
    """Drive `lifecycle` over the replay's stored lifecycle inputs, in order.

    Returns `{t: {key: row}}`. No pixels: the inputs are what the chain
    handed the lifecycle, so the stock `Lifecycle` must reproduce the replay.
    """
    out = {}
    for fr in rep["frames"]:
        rows = lifecycle.step(fr["input"])
        out[fr["t"]] = {r["observation_key"]: r for r in rows}
    return out


def eligible_sets(gated: dict) -> dict:
    return {t: {k for k, r in rows.items() if r["eligible"]} for t, rows in gated.items()}


def heldout_plan(cache_t, step: int = 2, windows: int = 20, window_s: float = 6.0,
                 offsets=(0.0,)):
    """6 s windows at `offsets` of E7's spacing (E7's own sit at 0.5), so none
    overlaps them. `heldout` is offset 0; `heldout2`, added when `heldout` left
    only three changed Lotus windows, is offsets 0.25 and 0.75."""
    T = np.unique(np.asarray(cache_t, float))
    span = T[-1] - T[0]
    out = []
    for j, off in enumerate(offsets):
        for w in range(windows):
            t0 = T[0] + (w + off) * span / windows
            sel = T[(T >= t0) & (T < t0 + window_s * 1000.0)]
            out.extend((j * windows + w, float(t)) for t in sel[::step])
    return out


def studied_plan(cache_t, step: int = 2):
    import team_vision_errors as tve
    return tve.plan_of(tve._Times(None, np.unique(np.asarray(cache_t, float))), step)


CONFIRM = 0.5      # a cone is confirmed when this share of it is lit (logged before the run)
MIN_EXCL_PX = 30   # the exclusive share is read only on this many pixels or more


def score(sid: str, plan, gates: dict, keep_icons: bool = True, log=_log) -> list[dict]:
    """Per frame: team counts against E7's `all` witness for each gate, and per
    uncast-by-gate icon its cone's lit share.

    `gates` maps a name to `{t: set(eligible keys)}`. E7's `frame_errors` builds
    the witness, the region and every icon's cone at its stored origin and
    facing; a gate only chooses which cones join the union.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import team_vision_errors as tve
    from reticle import cone, lighting
    s = tve.Sess(sid, times_wanted=[t for _w, t in plan])
    s.load_smokes(plan)
    win = {t: w for w, t in plan}
    rows, t0 = [], time.time()
    for t, crop in s.crops([t for _w, t in plan]):
        t = float(t)
        row = s.vision.get(t)
        if row is None or row["widget"] != "drawn" or row.get("observable") is None:
            continue
        a = tve.frame_errors(s, t, crop, row, keep=True)
        m = a["_m"]
        icons = m["casters"] + m["uncast"]
        shape = s.passable.shape
        foot = cone.union([c["fp"] for c in icons], shape)
        region = s.ref.known & s.floor & ~foot
        W = m["W_all"]
        keys = {}
        for ic in row.get("icons") or []:
            keys[(ic["role"], round(ic["x"], 3), round(ic["y"], 3))] = f"{ic['role']}:{ic['track_id']}"
        for c in icons:
            c["key"] = keys.get((c["role"], round(c["x"], 3), round(c["y"], 3)))
        prod = cone.union([c["cone"] for c in icons if c.get("cone") is not None
                           and c["why"] is None], shape) & region
        rec = {"t": t, "w": win[t], "e7_prod": a["prod"]["team_all"], "gates": {}, "icons": []}
        for name, elig in gates.items():
            e = elig.get(t, set())
            P = cone.union([c["cone"] for c in icons if c.get("cone") is not None
                            and c["key"] in e], shape) & region
            tp = int((P & W).sum())
            rec["gates"][name] = (tp, int(P.sum()) - tp, int(W.sum()) - tp)
        if keep_icons:
            for c in icons:
                if c.get("cone") is None or c["key"] is None:
                    continue
                cm = c["cone"] & region
                n = int(cm.sum())
                ex = cm & ~prod
                nx = int(ex.sum())
                rec["icons"].append({
                    "key": c["key"], "role": c["role"], "x": c["x"], "y": c["y"],
                    "deg": c["deg"], "cast_prod": c["why"] is None,
                    "cone_px": n, "lit": int((cm & W).sum()),
                    "excl_px": nx, "excl_lit": int((ex & W).sum())})
        rows.append(rec)
        if len(rows) % 100 == 0:
            log(f"  {sid}: scored {len(rows)} frames, {time.time() - t0:.0f} s")
    return rows


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else float("nan")
    return p, r, f


def gate_stats(rows, name, n_boot=1000, seed=20260929) -> dict:
    """F1, precision, recall summed over frames, and a window bootstrap of F1
    and of its difference from the stored gate."""
    by_w = defaultdict(lambda: np.zeros(3, float))
    base_w = defaultdict(lambda: np.zeros(3, float))
    for r in rows:
        by_w[r["w"]] += r["gates"][name]
        base_w[r["w"]] += r["gates"]["stored"]
    ws = sorted(by_w)
    tot, base = sum(by_w.values()), sum(base_w.values())
    p, rc, f = prf(*tot)
    f0 = prf(*base)[2]
    rng = np.random.default_rng(seed)
    fs, ds = [], []
    for _ in range(n_boot):
        pick = rng.choice(len(ws), size=len(ws), replace=True)
        g = sum(by_w[ws[i]] for i in pick)
        b = sum(base_w[ws[i]] for i in pick)
        fs.append(prf(*g)[2])
        ds.append(prf(*g)[2] - prf(*b)[2])
    return {"f1": f, "precision": p, "recall": rc, "df1": f - f0,
            "f1_lo": float(np.nanpercentile(fs, 2.5)), "f1_hi": float(np.nanpercentile(fs, 97.5)),
            "df1_lo": float(np.nanpercentile(ds, 2.5)), "df1_hi": float(np.nanpercentile(ds, 97.5)),
            "frames": len(rows), "windows": len(ws)}


def replay_gates(rep: dict) -> dict:
    """The stored gate (the replay's eligible keys) and the gate off (every icon)."""
    stored, off = {}, {}
    for t, icons in rep["icons"].items():
        stored[t] = {f"{i['role']}:{i['track_id']}" for i in icons if i["eligible"]}
        off[t] = {f"{i['role']}:{i['track_id']}" for i in icons}
    return {"stored": stored, "off": off}


def light_verdict(ic: dict) -> str:
    """confirmed / contradicted / partial, on the exclusive pixels where there
    are enough of them, else on the whole cone."""
    if ic["excl_px"] >= MIN_EXCL_PX:
        share = ic["excl_lit"] / ic["excl_px"]
    elif ic["cone_px"]:
        share = ic["lit"] / ic["cone_px"]
    else:
        return "no_cone"
    return "confirmed" if share >= CONFIRM else "contradicted" if share < 0.1 else "partial"


def outcome(row: dict | None) -> str:
    """What the corroborated gate did with a row the stock gate refused."""
    if row is None:
        return "absent"
    if row["eligible"]:
        return "admitted:" + row["admitted_by"]["rule"] if row.get("admitted_by") else "eligible"
    why = row.get("reason") or ""
    return ("kept:player_may_be_dead" if why.startswith("player may be dead") else
            "kept:roster_unread" if why.startswith("roster unread") else
            "kept:over_capacity" if "roster licenses" in why else
            "kept:" + row["state"])


def study(sid: str, work: Path, which: str = "studied", log=_log) -> dict:
    """Reasons on every replayed frame; the gates and the light on a plan's frames.

    `studied` is E7's frames (twenty 6 s windows, every 2nd frame);
    `heldout` is twenty other 6 s windows (`heldout_plan`).
    """
    rep = load_replay(sid, work)
    rs = reasons(rep)
    times = sorted(rep["icons"])
    plan = (studied_plan(times) if which == "studied" else
            heldout_plan(times) if which == "heldout" else
            heldout_plan(times, offsets=(0.25, 0.75)))
    gates = replay_gates(rep)
    cor = corroborated_run(rep)
    gates["corroborated"] = eligible_sets(cor)
    gates["ally_only"] = eligible_sets(corroborated_run(rep, self_=False))
    gates["self_only"] = eligible_sets(corroborated_run(rep, ally=False))
    gates["spectated"] = eligible_sets(corroborated_run(rep, after_death=True))
    rows = score(sid, plan, gates, log=log)
    by_t = defaultdict(dict)
    for r in rs:
        by_t[r["t"]][r["key"]] = r
    joined = []
    for rec in rows:
        for ic in rec["icons"]:
            q = by_t.get(rec["t"], {}).get(ic["key"])
            if q is None or ic["cast_prod"]:
                continue
            joined.append({**{k: q[k] for k in ("t", "key", "role", "cause", "state",
                                                  "inherited", "entry_t", "light_state")},
                           **{k: ic[k] for k in ("cone_px", "lit", "excl_px", "excl_lit")},
                           "light": light_verdict(ic), "w": rec["w"],
                           "gate": outcome(cor.get(rec["t"], {}).get(ic["key"]))})
    stats = {g: gate_stats(rows, g) for g in gates}
    return {"which": which, "reasons": rs, "scored": rows, "joined": joined, "stats": stats}


# ------------------------------------------------------------------ sheets

def sheet(sid: str, picks: list, path: Path, zoom: int = 3, half: int = 40) -> str | None:
    """One tile per `(t, key, text)`: the crop round the icon, and beside it the
    drawn light (cyan), the product's cones (green outline), and the icon's own
    would-be cone at its stored origin and facing (red outline), its icon ringed."""
    if not picks:
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import team_vision_errors as tve
    from reticle import cone
    s = tve.Sess(sid, times_wanted=[p[0] for p in picks])
    tiles = []
    crops = dict(s.crops(sorted({p[0] for p in picks})))
    for t, key, text in picks:
        crop, row = crops.get(t), s.vision.get(t)
        if crop is None or row is None:
            continue
        a = tve.frame_errors(s, t, crop, row, keep=True)
        m = a["_m"]
        icons = m["casters"] + m["uncast"]
        keys = {(ic["role"], round(ic["x"], 3), round(ic["y"], 3)): f"{ic['role']}:{ic['track_id']}"
                for ic in row["icons"]}
        me = next((c for c in icons if keys.get((c["role"], round(c["x"], 3), round(c["y"], 3))) == key), None)
        if me is None:
            continue
        base = (cv2.cvtColor(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) * 0.5).astype(np.uint8)
        ov = base.copy()
        ov[~s.floor] = (70, 45, 45)
        ov[m["W_all"]] = (230, 200, 60)
        prod = cone.union([c["cone"] for c in m["casters"]], s.passable.shape)
        for msk, col in ((prod, (60, 200, 60)),
                         (me.get("cone") if me.get("cone") is not None else np.zeros_like(prod),
                          (40, 40, 255))):
            cnt, _ = cv2.findContours(msk.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(ov, cnt, -1, col, 1)
        cv2.circle(ov, (int(round(me["x"])), int(round(me["y"]))), 9, (40, 40, 255), 1)
        h, w = crop.shape[:2]
        x0 = int(np.clip(me["x"] - half, 0, max(0, w - 2 * half)))
        y0 = int(np.clip(me["y"] - half, 0, max(0, h - 2 * half)))
        box = (slice(y0, y0 + 2 * half), slice(x0, x0 + 2 * half))
        im = np.concatenate([crop[box], np.full((2 * half, 2, 3), 255, np.uint8), ov[box]], axis=1)
        im = cv2.resize(im, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        tiles.append(tve.label(im, f"{t / 1000:.2f}s {key} {text}"))
    if not tiles:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), tve.grid(tiles, cols=3))
    return str(path)


SHEET_GROUPS = (
    ("ally_released_confirmed", "ally", ("admitted:", "eligible"), ("confirmed",)),
    ("ally_released_not_confirmed", "ally", ("admitted:", "eligible"), ("contradicted", "partial")),
    ("ally_kept", "ally", ("kept:",), ("confirmed", "partial", "contradicted", "no_cone")),
    ("self_released", "self", ("admitted:", "eligible"), ("confirmed", "partial", "contradicted")),
    ("self_kept_confirmed", "self", ("kept:",), ("confirmed",)),
    ("self_kept_not_confirmed", "self", ("kept:",), ("contradicted", "partial", "no_cone")),
)


def sheets_for(sid: str, st: dict, out: Path, n: int = 6) -> list[str]:
    """Per group, up to `n` quarantined icons from distinct windows, largest cones first."""
    written = []
    for name, role, gates, lights in SHEET_GROUPS:
        cand = [j for j in st["joined"] if j["role"] == role and j["light"] in lights
                and any(j["gate"].startswith(g) for g in gates)]
        cand.sort(key=lambda j: -j["cone_px"])
        seen, picks = set(), []
        for j in cand:
            if j["w"] in seen:
                continue
            seen.add(j["w"])
            share = j["excl_lit"] / j["excl_px"] if j["excl_px"] >= MIN_EXCL_PX else \
                (j["lit"] / j["cone_px"] if j["cone_px"] else float("nan"))
            picks.append((j["t"], j["key"], f"{j['gate']} {j['light']} {share:.2f}"))
            if len(picks) >= n:
                break
        p = sheet(sid, picks, out / f"{sid}_{name}.png")
        if p:
            written.append(p)
    return written


# ------------------------------------------------------------------ report

def report(sid: str, work: Path, values: dict, log=_log) -> None:
    """The reason table, the light split, the gate's outcomes and the F1s;
    writes the proposed adjudication rows to `work` and fills `values`."""
    tag = TAGS.get(sid, sid[:4])
    rep = load_replay(sid, work)
    rs = reasons(rep)
    n_rows = len(rs)
    ent = [r for r in rs if not r["inherited"]]
    values[f"{tag}_quarantined_rows"] = n_rows
    values[f"{tag}_quarantine_entries"] = len(ent)
    values[f"{tag}_inherited_share"] = round(1 - len(ent) / max(1, n_rows), 4)
    values[f"{tag}_reason_strings"] = len({r["reason"] for r in rs})
    log(f"\n{sid}: {n_rows} quarantined rows, {len(ent)} entries, "
        f"{values[f'{tag}_inherited_share']:.3f} inherited; distinct stored reasons "
        f"{values[f'{tag}_reason_strings']}; instrument {rep['check']}")
    tab = Counter((r["role"], r["mechanism"]) for r in rs)
    etab = Counter((r["role"], r["mechanism"]) for r in ent)
    for (role, mech), n in sorted(tab.items(), key=lambda kv: -kv[1]):
        values[f"{tag}_{role}_{mech}_rows"] = n
        values[f"{tag}_{role}_{mech}_entries"] = etab[(role, mech)]
        log(f"  {role:5s} {mech:24s} rows {n:6d} ({n / n_rows:.3f})  entries {etab[(role, mech)]:5d}")
    mech_of = {(r["t"], r["key"]): r["mechanism"] for r in rs}
    for which in ("studied", "heldout", "heldout2"):
        p = work / f"{sid}.{which}.pkl"
        if not p.is_file():
            continue
        with open(p, "rb") as f:
            st = pickle.load(f)
        if which == "studied":
            lt = Counter((j["role"], mech_of.get((j["t"], j["key"])), j["light"]) for j in st["joined"])
            lc = Counter(j["light"] for j in st["joined"])
            with_cone = sum(v for k, v in lc.items() if k != "no_cone")
            values[f"{tag}_studied_quarantined_icons"] = len(st["joined"])
            values[f"{tag}_studied_confirmed_share"] = round(lc["confirmed"] / max(1, with_cone), 4)
            for k in ("confirmed", "partial", "contradicted", "no_cone"):
                values[f"{tag}_studied_light_{k}"] = lc[k]
            log(f"  studied frames: {len(st['joined'])} quarantined icons; light {dict(lc)}; "
                f"confirmed share of those with a cone {values[f'{tag}_studied_confirmed_share']:.3f}")
            for k, n in sorted(lt.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2])):
                log(f"    {k[0]:5s} {str(k[1]):24s} {k[2]:12s} {n:5d}")
            gt = Counter((j["role"], j["gate"].split(":")[0] if j["gate"] != "eligible" else "admitted",
                          j["light"]) for j in st["joined"])
            for k, n in sorted(gt.items()):
                values[f"{tag}_studied_{k[0]}_{k[1]}_{k[2]}"] = n
                log(f"    gate {k[0]:5s} {k[1]:9s} {k[2]:12s} {n:5d}")
        for g, v in st["stats"].items():
            for k in ("f1", "precision", "recall", "df1", "df1_lo", "df1_hi"):
                values[f"{tag}_{which}_{g}_{k}"] = round(float(v[k]), 4)
            values[f"{tag}_{which}_frames"] = v["frames"]
            log(f"  {which:8s} {g:13s} F1 {v['f1']:.4f} P {v['precision']:.4f} R {v['recall']:.4f} "
                f"dF1 {v['df1']:+.4f} [{v['df1_lo']:+.4f}, {v['df1_hi']:+.4f}] ({v['frames']} frames)")
    cor = corroborated_run(rep)
    out = Counter()
    path = work / f"{sid}.adjudication.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for t in sorted(cor):
            rows = cor[t]
            if not rows:
                continue
            recs = [adjudication_record(r) for r in rows.values()]
            f.write(json.dumps({"t_ms": t, "adjudication": recs}) + "\n")
            for r in rows.values():
                if r.get("refused_as"):
                    out["admitted:" + r["admitted_by"]["rule"]] += 1
                elif not r["eligible"]:
                    out["kept:" + outcome(r).split(":", 1)[1]] += 1
    for k, n in out.items():
        values[f"{tag}_gate_{k.replace(':', '_')}"] = n
    log(f"  corroborated gate, whole session: {dict(out)}; rows -> {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("replay", "reasons", "study", "sheets", "report"))
    ap.add_argument("--record", action="store_true", help="report: one metrics row")
    ap.add_argument("--out", type=Path, default=STORE / "analysis" / "vision-lifecycle-20260929")
    ap.add_argument("sessions", nargs="*", default=list(SESSIONS))
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--which", choices=("studied", "heldout", "heldout2"), default="studied")
    args = ap.parse_args(argv)
    idle()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.cmd == "report":
        values = {}
        for sid in args.sessions:
            report(sid, args.work, values)
        (args.work / "summary.json").write_text(json.dumps(values, indent=1), encoding="utf-8")
        if args.record:
            from reticle import metrics
            from reticle.minimap_lifecycle import LIFECYCLE_VERSION
            from reticle.version import TEAM_VISION_VERSION
            metrics.record("vision_lifecycle", part="gate", session="+".join(args.sessions),
                           values=values,
                           deps={"prototype": VERSION, "team_vision": TEAM_VISION_VERSION,
                                 "lifecycle": LIFECYCLE_VERSION,
                                 "witness": "team-vision-errors-0.1.0 all",
                                 "confirm": CONFIRM, "min_excl_px": MIN_EXCL_PX,
                                 "roster_lag_ms": ROSTER_LAG_MS, "step": 2},
                           context={"captures": {s: geometry.manifest(s, STORE)["source"]["path"]
                                                 for s in args.sessions}})
            print("recorded metrics row vision_lifecycle/gate")
        return 0
    for sid in args.sessions:
        if args.cmd == "replay":
            rep = replay(sid)
            with open(args.work / f"{sid}.replay.pkl", "wb") as f:
                pickle.dump(rep, f, protocol=pickle.HIGHEST_PROTOCOL)
        elif args.cmd == "sheets":
            with open(args.work / f"{sid}.studied.pkl", "rb") as f:
                st = pickle.load(f)
            for p in sheets_for(sid, st, args.out):
                print("sheet", p)
        elif args.cmd == "study":
            st = study(sid, args.work, args.which)
            with open(args.work / f"{sid}.{args.which}.pkl", "wb") as f:
                pickle.dump(st, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(sid, args.which, "quarantined icons on scored frames", len(st["joined"]))
            if args.which == "studied":
                tab = Counter((j["role"], j["cause"], j["gate"], j["light"]) for j in st["joined"])
                for k in sorted(tab):
                    print(f"  {k[0]:5s} {k[1]:11s} {k[2]:32s} {k[3]:12s} {tab[k]:5d}")
            for g, v in st["stats"].items():
                print(f"  {g:13s} F1 {v['f1']:.4f} P {v['precision']:.4f} R {v['recall']:.4f} "
                      f"dF1 {v['df1']:+.4f} [{v['df1_lo']:+.4f}, {v['df1_hi']:+.4f}]")
        else:
            rep = load_replay(sid, args.work)
            rs = reasons(rep)
            tab = Counter((r["role"], r["cause"]) for r in rs)
            ent = Counter((r["role"], r["cause"]) for r in rs if not r["inherited"])
            print(sid, "quarantined rows", len(rs), "check", rep["check"])
            for k in sorted(tab):
                print(f"  {k[0]:5s} {k[1]:13s} rows {tab[k]:6d}  entries {ent[k]:5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
