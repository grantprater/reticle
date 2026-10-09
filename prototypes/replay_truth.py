r"""VALORANT replay files as external truth for evaluation.

Moved into the acceptance harness on 2026-10-09 (`reticle/harness/clock.py`,
task `harness-t1d-20261009`): the lag constants, `capture_to_replay` and the
stream loaders. This file imports them back.

    .\.venv\Scripts\python.exe prototypes\replay_truth.py parse REPLAY.vrf [REPLAY.vrf ...]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py wrap MATCH SESSION [--write]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py check MATCH [--record]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py score SESSION [--geometry NPZ] [--out NAME] [--record]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py handcheck SESSION [--n 3] [--geometry NPZ]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py survey [--record]

What this is, and what it is not
--------------------------------
An in-client replay (`.vrf`) is the server's recording of a match: every
player's position and view at about 128 Hz, plus the server's own event list
(kills, round starts, plant, defuse). vrfkit (yakisoba0728/vrfkit,
Apache-2.0, built from source under `<store>/tools/vrfkit`, see its NOTES.md)
decodes it into Parquet tables. The player approved building and running it on
2026-10-04 after hearing the Terms of Service exposure.

Replay positions, like Riot's match records (`prototypes/riot_ground_truth.py`),
never feed anything shown during play; under the use policy in
`docs/EXTERNAL_GROUND_TRUTH.md` they may fit reader parameters, thresholds and
models offline, with scoring matches held out from the fit, and win-probability
and coaching baselines and priors. This module uses them for evaluation only.
Nothing in `reticle/` reads this file or its outputs, and
a score here rests on the replay; it says how far the stored streams agree
with the server, not how a reader should decide.

Store layout (never in this repository: account ids stay in the store)
----------------------------------------------------------------------
`<store>/external/replays/<match>.vrf`              the preserved copies (read only)
`<store>/external/replays/parsed/vrfkit-<ver>/<match>/`
    `export/`                vrfkit's tables and manifest.json
    `spike_carrier.parquet`  vrfkit's tools/extract_spike_carrier.py
    `validate.txt`           vrfkit validate's report
    `provenance.json`        vrfkit commit, toolchain, input sha256, commands, times
    `check.json`             `check`: the replay against Riot's record
`<store>/external/riot/<match>.json`                `wrap`'s output, `riot_ground_truth`'s input
`<store>/analysis/replay-truth-20261006-lag/<session>.json`   `score`'s 0.4.0 report, beside
    `<session>_replay-truth-0.3.0.json`, 0.3.0 rerun on the same stored streams
(0.3.0's first reports stay in `analysis/replay-truth-20261006/`, 0.2.0's in
`analysis/replay-truth-20261005/`, 0.1.0's in `analysis/replay-truth-20261004/`)

The commands
------------
`parse` runs vrfkit (validate, export, spike carrier) at Below Normal priority.

`wrap` turns a record the player's fetch kit saved
(`external/riot-pd-v1/raw/<match>.json`, `prototypes/riot_match_fetch.py`)
into the `{"probe", "match"}` file `riot_ground_truth.riot_records` reads,
naming the capture session. It refuses a body whose sha256 differs from its
sidecar, a record of another match, a session already wrapped, a replay
manifest that names another session, and a capture whose file name puts its
start outside the game; it never overwrites. Without `--write` it only checks.

`check` tests the parse against Riot's match-details record before anything
trusts it: kills by killer, victim and time; every listed player's 2D position
and view angle at Riot's kill and plant instants; round starts, plants and
defuses. Riot's clock runs about 10.1 s ahead of the replay's and drifts, so
each kill is timed by its own paired replay death, and plants and defuses by
the paired kills' offset interpolated. It also states what the position
stream holds (sample rate per player, height, the park slot).

`score` lives in the one harness since 2026-10-09
(`question_acceptance.py replay-score`, `question_acceptance.replay_score`,
harness step 9), which also joins the report's phantoms to every replay
entity. This command and `score()` forward to it; the report still goes to
`--out` here. The report, unchanged:

`score` aligns replay time to capture time through STORED events only (replay
kills against the stored deaths' first killfeed sample, as `riot_ground_truth`
aligns Riot's kills; the stored round starts are the independent
cross-check). 0.4.0 keeps the fit's slope (`capture_to_replay`): the capture
clock gains about 1e-4 on the replay's, which a slope-1 offset turned into a
lag drifting some 200 ms across a match. It reads the player at `SELF_LAG_MS`
and every other player at `REMOTE_LAG_MS`, 50 ms later: the capture draws
remote players later than the player (`prototypes/minimap_lag.py`) and maps world positions into baked widget pixels through
`riot_ground_truth.MapFrame` (valorant-api's map constants, the geometry's
`shade_fit`); `--geometry` names another baked npz, so one capture scores
before and after a geometry rebuild. 0.3.0 first names the player from the
replay (`replay_source.replay_self_pick`, the pipeline's owner since
2026-10-06): the replay player whose path the stored self-icon track
(`ally_icon`'s `self`) follows. Riot's record, when present, keeps naming the
player and the replay's pick is the cross-check
(`self_identity.riot_cross_check`); without it the replay's verdict is used,
and the self fit below then `rests_on` the track that chose it. It scores per
frame and per track:

- the denominator is `ally_icon`'s frame grid inside the minimap crop cache's
  spans (`roi_cache`) with the widget drawn; frames outside the spans or with
  the widget absent are counted apart and enter no share;
- teammates (`round_entity`, families ally and self): a living teammate frame
  is located when one-to-one assignment within 8 m gives it an observation;
  a phantom is an observation with no living teammate within 8 m; recall,
  error and the share within an icon radius, per class (self, ally, pooled);
- names: the entity's agent against the replay's, and how many wrong names
  sit in a stack or within 1 s of leaving one;
- tracks: identity switches per truth minute, fragments per life and IDF1
  (`track_metrics`), a life being one teammate in one round;
- misses: each missed teammate frame takes the first class of
  `MISS_CLASSES` that holds (`classify_misses`), with each cover's rate on
  located frames beside it;
- the self fit (`ally_icon`), with a lag scan and an affine refit;
- enemies: `minimap_object` icons (located, phantoms; recall is not scored,
  since whether the minimap must draw a foe is unknown) and `enemy_track`'s
  names and tracks;
- facing per class (self and ally from `team_vision`, ally from `ally_icon`'s
  teardrop, enemy from `minimap_object`): median and p90 error, the share
  above 135 degrees and a lag scan; the report's `stamps` name every stream
  version scored.

`handcheck` prints a few scored frames with each living teammate's replay
position, every step of its mapping to widget pixels and the stored reading
nearest it, for checking the arithmetic by hand.

`survey` summarises every parsed replay and runs the self-consistency checks
that need no Riot record.

Agreement is consistency, not accuracy; disagreements are stored beside the
agreements, never averaged away.

Format facts this file rests on
-------------------------------
The container [domain:replay/vrf-container], the per-patch scramble vrfkit
undoes [domain:replay/vrf-values-scrambled-per-patch], the 128 Hz position
stream and its gaps [domain:replay/vrf-position-stream]
[domain:replay/vrf-tick-pattern], Riot's drifting clock offset
[domain:replay/vrf-riot-clock], Riot's view angle as replay yaw
[domain:replay/vrf-yaw-is-view-radians], `roundStarted` as the buy phase's
start [domain:replay/vrf-round-started-opens-buy-phase], and the crossed map
axes [domain:replay/vrf-minimap-axes-cross].
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import riot_ground_truth as rg  # noqa: E402
from reticle import replay_source as src  # noqa: E402
# The replay reader, the clock and the map transform live in the pipeline
# (`reticle.replay_source`) since 2026-10-05; these names stay for callers.
from reticle.replay_source import (MAX_GAP_MS, PARK_RADIUS, PARK_X, PARK_Z,  # noqa: E402,F401
                                   VRFKIT_VERSION, Replay, facing_px_deg, parsed_dir,
                                   to_px)
from reticle.replay_source import file_sha256 as sha256  # noqa: E402,F401
from reticle.replay_source import frames_to_replay as _frames_to_replay  # noqa: E402

# Moved into the acceptance harness (`reticle/harness/clock.py`, task
# harness-t1d-20261009); these names stay for this module's callers.
from reticle.harness.clock import (  # noqa: E402,F401
    _ang_deg, _default, _facing_block, _facing_lag_scan, _near_points, _rows, _stamp, _stats,
    _under_dark, ANALYSIS, capture_to_replay, classify_misses, DARK_TOL_MS, DISC_TOL_MS, FLIP_DEG,
    GRID_HZ, LAG_SCAN_MS, load_ally_icon, load_enemy_track, load_minimap_object, load_occluders,
    load_round_entity, load_team_vision, MISS_CLASSES, REMOTE_LAG_MS, REPLAY_TRUTH_VERSION,
    SELF_LAG_MS, session_context, SPIKE_TOL_MS, STACK_LEAVE_MS, STORE, track_metrics)

REPLAYS = src.replays_dir(STORE)
PARSED = src.parsed_root(STORE)


#: `check`'s position tolerance in world units (cm). Riot stores integer
#: positions at its own server sample; one 7.8 ms tick at a 675 cm/s run is
#: 5 units, so a miss beyond 100 units is a timing or identity error.
POS_TOL_UNITS = 100.0
#: Candidate readings of Riot's viewRadians against replay yaw (degrees, UE
#: rotator: from +x toward +y). The data chooses; every candidate is reported.
YAW_CONVENTIONS = {
    "yaw": lambda r: r,
    "-yaw": lambda r: -r,
    "yaw+pi/2": lambda r: r + math.pi / 2,
    "yaw-pi/2": lambda r: r - math.pi / 2,
    "pi/2-yaw": lambda r: math.pi / 2 - r,
    "yaw+pi": lambda r: r + math.pi,
}


# ----------------------------------------------------------------- helpers

def _below_normal() -> None:
    rg._below_normal()


def _ang_rad(a, b):
    d = np.mod(np.asarray(a, float) - np.asarray(b, float), 2 * math.pi)
    return np.minimum(d, 2 * math.pi - d)


# ----------------------------------------------------------------- parse, wrap

# Keeping, parsing and wrapping a replay belong to the pipeline
# (`reticle.replay_keep`, `reticle replay-keep SESSION`) since 2026-10-05;
# `parse` and `wrap` here call the same definitions.
from reticle.replay_keep import parse_replay, wrap_record, wrap_riot  # noqa: E402,F401


# ----------------------------------------------------------------- check

def riot_record(match: str) -> dict | None:
    p = STORE / "external" / "riot" / f"{match}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def stream_facts(rp: Replay) -> dict:
    """What the position stream holds: rate per player, height, park slot."""
    steps, per_sec = [], []
    rs = rp.round_starts()
    for s in rp.subjects:
        P = rp.players[s]
        if P["t"].size < 2:
            continue
        steps.append(np.diff(P["t"]))
        # samples in each living second of this player
        if rs.size:
            grid = np.arange(rs[0], rp.duration_ms - 1000.0, 1000.0)
            al = rp.alive(s, grid + 1000.0) & rp.alive(s, grid)
            cnt = np.searchsorted(P["t"], grid + 1000.0) - np.searchsorted(P["t"], grid)
            per_sec.append(cnt[al])
    st = np.concatenate(steps) if steps else np.array([])
    ps = np.concatenate(per_sec) if per_sec else np.array([])
    z = np.concatenate([rp.players[s]["z"] for s in rp.subjects])
    return {"movement_rows": rp.movement_rows, "park_rows": rp.park_rows,
            "rows_without_player": rp.unjoined_rows,
            "players_with_movement": sum(1 for s in rp.subjects if rp.players[s]["t"].size),
            "players": len(rp.subjects),
            "step_ms": _stats(st, 2),
            "step_ms_share": {k: round(float(np.mean(st == v)), 4) if st.size else None
                              for k, v in (("0", 0), ("7", 7), ("8", 8))} |
                             {"over_250": round(float(np.mean(st > 250)), 5) if st.size else None},
            "living_seconds": int(ps.size),
            "samples_per_living_second": _stats(ps, 1),
            "living_seconds_ge_100_samples": round(float(np.mean(ps >= 100)), 4) if ps.size else None,
            "living_seconds_ge_120_samples": round(float(np.mean(ps >= 120)), 4) if ps.size else None,
            "z_cm": _stats(z, 1), "z_present": bool(np.isfinite(z).any() and np.ptp(z) > 0)}


def check(match: str) -> dict:
    """The replay against Riot's record (kills, positions, facing, rounds)."""
    rp = Replay(match)
    out = {"match": match, "replay_truth_version": REPLAY_TRUTH_VERSION,
           "stream": stream_facts(rp)}
    d = riot_record(match)
    if d is None:
        out["riot"] = {"refused": "no_riot_record"}
        return out
    m = d["match"]
    kills = sorted(m["kills"], key=lambda k: k["gameTime"])
    rk = rp.group("characterDeath")
    out["kills"] = {"riot": len(kills), "replay": len(rk),
                    "replay_unresolved_ids": sum(1 for e in rk if not e["killer"] or not e["victim"])}
    # pair in time order: the most pairs within a 1.5 s window of the median offset
    rt = np.array([e["t"] for e in rk])
    gt = np.array([k["gameTime"] for k in kills], float)
    off0 = float(np.median(gt[:min(len(gt), len(rt))] - rt[:min(len(gt), len(rt))]))
    pairs = rg.align_in_order(list(gt - off0), list(rt), tol_ms=1500.0)
    out["kills"]["paired"] = len(pairs)
    killer_ok = victim_ok = 0
    conflicts = []
    offs = []
    for i, j in pairs:
        k, e = kills[i], rk[j]
        kk = e["killer"] == k["killer"]
        vv = e["victim"] == k["victim"]
        killer_ok += kk
        victim_ok += vv
        offs.append(k["gameTime"] - e["t"])
        if not (kk and vv):
            conflicts.append({"riot_game_ms": k["gameTime"], "replay_ms": e["t"],
                              "killer_agrees": kk, "victim_agrees": vv})
    offs = np.array(offs)
    out["kills"].update(killer_agree=killer_ok, victim_agree=victim_ok,
                        disagreements=conflicts,
                        riot_minus_replay_ms=_stats(offs, 1),
                        offset_min_ms=float(offs.min()) if offs.size else None,
                        offset_max_ms=float(offs.max()) if offs.size else None)
    pk = np.array([kills[i]["gameTime"] for i, _ in pairs], float)
    o = np.argsort(pk)
    pk, offs_s = pk[o], offs[o]

    def to_replay(g):
        """Riot game ms -> replay ms by the paired kills' offset, interpolated."""
        return np.asarray(g, float) - np.interp(g, pk, offs_s)

    # positions and facing at each paired kill: the replay death's own time
    rows = []
    for i, j in pairs:
        k = kills[i]
        t_r = rk[j]["t"]
        for p in k["playerLocations"]:
            rows.append(("kill", k["round"], t_r, p["subject"], p["location"]["x"],
                         p["location"]["y"], p.get("viewRadians")))
        if k.get("victimLocation"):
            rows.append(("victim", k["round"], t_r, k["victim"], k["victimLocation"]["x"],
                         k["victimLocation"]["y"], None))
    # round zero per Riot round: gameTime - roundTime of its kills
    r0 = {}
    for k in kills:
        r0.setdefault(k["round"], []).append(k["gameTime"] - k["roundTime"])
    r0 = {r: float(np.median(v)) for r, v in r0.items()}
    plants, defuses = [], []
    for rr in m["roundResults"]:
        r = rr["roundNum"]
        if r not in r0:
            continue
        for kind, tkey, lkey, store in (("plant", "plantRoundTime", "plantPlayerLocations", plants),
                                        ("defuse", "defuseRoundTime", "defusePlayerLocations",
                                         defuses)):
            if rr.get(tkey) and (rr.get(lkey) or rr.get(kind + "Location")):
                g = r0[r] + rr[tkey]
                t_r = float(to_replay([g])[0])
                store.append({"round": r, "riot_game_ms": g, "replay_ms_from_riot": t_r})
                for p in rr.get(lkey) or []:
                    rows.append((kind, r, t_r, p["subject"], p["location"]["x"],
                                 p["location"]["y"], p.get("viewRadians")))
    pos = {}
    by_kind = defaultdict(list)
    fac = defaultdict(list)
    worst = []
    for kind, r, t_r, s, x, y, vr in rows:
        if s not in rp.players:
            by_kind[kind].append(np.nan)
            continue
        q = rp.sample(s, [t_r])
        dd = math.hypot(q["x"][0] - x, q["y"][0] - y)
        by_kind[kind].append(dd)
        if np.isfinite(dd) and dd > POS_TOL_UNITS and len(worst) < 60:
            worst.append({"kind": kind, "round": r, "replay_ms": t_r, "dist_cm": round(dd, 1)})
        if vr is not None and np.isfinite(q["yaw"][0]):
            for name, fn in YAW_CONVENTIONS.items():
                fac[name].append(float(_ang_rad(fn(math.radians(q["yaw"][0])), vr)))
    for kind, v in by_kind.items():
        a = np.asarray(v, float)
        pos[kind] = {"dist_cm": _stats(a, 1), "unread": int(np.sum(~np.isfinite(a))),
                     "within_tol": round(float(np.mean(a[np.isfinite(a)] <= POS_TOL_UNITS)), 4)
                     if np.isfinite(a).any() else None}
    out["positions"] = {"tolerance_cm": POS_TOL_UNITS, **pos, "beyond_tolerance": worst}
    best = min(fac, key=lambda n: np.median(fac[n])) if fac else None
    out["facing"] = {"best_convention": best,
                     "by_convention_rad": {n: _stats(v, 4) for n, v in fac.items()},
                     "within_0_05_rad": round(float(np.mean(np.asarray(fac[best]) <= 0.05)), 4)
                     if best else None}
    # round starts: Riot round zero minus the replay's roundStarted, mapped by offset
    rs = rp.round_starts()
    rs_riot = rs + np.interp(rs, pk - offs_s, offs_s)   # replay -> riot ms
    rows_r = []
    for r, z in sorted(r0.items()):
        if r < rs.size:
            rows_r.append({"round": r, "riot_zero_minus_round_started_ms":
                           round(float(z - rs_riot[r]), 1)})
    dz = np.array([x["riot_zero_minus_round_started_ms"] for x in rows_r])
    out["rounds"] = {"replay_round_started": int(rs.size), "riot_rounds": len(m["roundResults"]),
                     "riot_zero_minus_round_started_ms": _stats(dz[1:], 1) if dz.size > 1 else None,
                     "first_round_ms": float(dz[0]) if dz.size else None, "per_round": rows_r}

    def match_events(riot_rows, group):
        ev = np.array([e["t"] for e in rp.group(group)])
        res = []
        for x in riot_rows:
            if ev.size == 0:
                res.append(None)
                continue
            j = int(np.argmin(np.abs(ev - x["replay_ms_from_riot"])))
            res.append(float(ev[j] - x["replay_ms_from_riot"]))
        a = np.array([v for v in res if v is not None])
        return {"riot": len(riot_rows), "replay": int(ev.size),
                "replay_minus_riot_ms": _stats(a, 1),
                "within_250ms": int(np.sum(np.abs(a) <= 250)) if a.size else 0}
    out["plants"] = match_events(plants, "spikePlanted")
    out["defuses"] = match_events(defuses, "spikeDefused")
    out["ults"] = Counter(e["group"] for e in rp.events)
    return out


# ----------------------------------------------------------------- score


# One-to-one obs->truth assignment within each frame, nearest first: the
# acceptance core owns it since 2026-10-09 (task `harness-promote-20261009`).
from reticle.acceptance import assign_per_frame as _assign  # noqa: E402,F401


# Which replay player is the capturing player belongs to the pipeline
# (`reticle.replay_source`, `[owns:replay-self]`) since 2026-10-06; these
# names stay for the report's head.
from reticle.replay_source import (SELF_ID_MARGIN, SELF_ID_MIN_FRAMES,  # noqa: E402,F401
                                   SELF_ID_MIN_SHARE, SELF_ID_RADIUS_M)
# The living players' widget px, the owner's sampler (`replay_source`).
from reticle.replay_source import living_widget_px as truth_px  # noqa: E402


def score(sid: str, geometry: Path | None = None) -> dict:
    """`question_acceptance.replay_score`: the scorer moved into the one
    harness (step 9, task harness-step9-20261009); this name stays for
    callers."""
    import question_acceptance as qa
    return qa.replay_score(sid, geometry)


# ----------------------------------------------------------------- hand check

def handcheck(sid: str, n: int = 3, geometry: Path | None = None) -> dict:
    """`n` scored frames, spread evenly through the match, with every living
    teammate's replay position, each step of its mapping to widget px
    (`game_to_uv`, art px, the shade_fit affine) and the stored readings
    nearest it (`round_entity`, `ally_icon`'s self fit), for checking the
    arithmetic by hand."""
    from reticle import roi_cache

    ctx = session_context(sid, geometry)
    if "refused" in ctx["out"]:
        return ctx["out"]
    rp, mf, clock = ctx["rp"], ctx["mf"], ctx["clock"]
    mates, agent, me = ctx["allies"], ctx["agent"], ctx["me"]
    AI = ctx["AI"]
    rec = roi_cache.stored_record(STORE, sid, "minimap")
    sc = roi_cache.spans_mask(AI["t_ms"], (rec or {}).get("spans") or []) & AI["drawn"]
    idx, ts = AI["frame_idx"][sc], AI["t_ms"][sc]
    RE = load_round_entity(sid)
    pick = [int(round(x)) for x in np.linspace(0, idx.size - 1, n + 2)[1:-1]]
    frames = []
    for p_ in pick:
        # move forward to a frame with at least three living teammates
        while p_ < idx.size - 1:
            t_rep = float(capture_to_replay([ts[p_]], *clock, REMOTE_LAG_MS)[0])
            if sum(bool(rp.alive(s, [t_rep])[0]) for s in mates) >= 3:
                break
            p_ += 15
        t_rep = float(capture_to_replay([ts[p_]], *clock, REMOTE_LAG_MS)[0])
        t_self = float(capture_to_replay([ts[p_]], *clock, SELF_LAG_MS)[0])
        m = RE["frame_idx"] == idx[p_]
        obs = [[round(float(x), 2), round(float(y), 2), str(f)] for x, y, f
               in zip(RE["x"][m], RE["y"][m], RE["family"][m])]
        rows = []
        for s in mates:
            t_s = t_self if s == me else t_rep
            if not rp.alive(s, [t_s])[0]:
                continue
            q = rp.sample(s, [t_s])
            x, y = float(q["x"][0]), float(q["y"][0])
            u, v = rg.game_to_uv(x, y, mf.m, mf.swap)
            ax = u * mf.art_hw[1] - 0.5 - mf.crop[0]
            ay = v * mf.art_hw[0] - 0.5 - mf.crop[1]
            px, py = mf.to_px(x, y)
            near = min(obs, key=lambda o: math.hypot(o[0] - px, o[1] - py)) if obs else None
            rows.append({"agent": agent.get(s), "self": s == me, "world_cm": [round(x, 1), round(y, 1)],
                         "uv": [round(u, 6), round(v, 6)], "art_px_in_crop": [round(ax, 2), round(ay, 2)],
                         "widget_px": [round(px, 2), round(py, 2)], "nearest_round_entity": near,
                         "dist_px": None if near is None else round(math.hypot(near[0] - px, near[1] - py), 2)})
        frames.append({"frame_idx": int(idx[p_]), "capture_ms": float(ts[p_]),
                       "replay_ms": round(t_rep, 1),
                       "ally_icon_self": [None if not np.isfinite(AI["self_x"][sc][p_]) else
                                          float(AI["self_x"][sc][p_]),
                                          None if not np.isfinite(AI["self_y"][sc][p_]) else
                                          float(AI["self_y"][sc][p_])],
                       "round_entity": obs, "teammates": rows})
    return {"session": sid, "clock": ctx["out"]["clock"],
            "map": {k: mf.m[k] for k in ("xMultiplier", "yMultiplier", "xScalarToAdd",
                                         "yScalarToAdd")},
            "swap": mf.swap, "art_hw": list(mf.art_hw), "crop_x0_y0_h_w": list(mf.crop),
            "affine": mf.aff, "geometry": ctx["out"].get("geometry"), "frames": frames}


# ----------------------------------------------------------------- survey

def survey() -> dict:
    """Every parsed replay: map, build, rounds, and the Riot-free checks."""
    rep = json.loads((REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for f in rep["files"]:
        match = Path(f["file"]).stem
        d = parsed_dir(match)
        row = {"match": match, "map": f["map"].rsplit("/", 1)[-1],
               "build": f["build"]["branch"].rsplit("+", 1)[-1], "recorded_utc": f["recorded_utc"],
               "length_ms": f["length_ms"], "riot_record": bool(f.get("riot_record")),
               "capture_session": f.get("capture_session")}
        prov_p = d / "provenance.json"
        if not prov_p.is_file():
            row["refused"] = "not_parsed"
            rows.append(row)
            continue
        prov = json.loads(prov_p.read_text(encoding="utf-8"))
        row["validate_exit"] = prov["steps"]["validate"]["exit"]
        row["export_exit"] = prov["steps"]["export"]["exit"]
        row["export_seconds"] = prov["steps"]["export"]["seconds"]
        row["input_sha256_matches_manifest"] = prov["input_sha256_matches_manifest"]
        if row["export_exit"] != 0:
            rows.append(row)
            continue
        rp = Replay(match)
        q = rp.manifest.get("quality") or {}
        row["content_blocks_lost"] = q.get("content_blocks_lost")
        g = Counter(e["group"] for e in rp.events)
        row["events"] = dict(g)
        row["rounds"] = g.get("roundStarted", 0)
        deaths = rp.group("characterDeath")
        row["deaths_resolved"] = sum(1 for e in deaths if e["killer"] and e["victim"])
        row["deaths"] = len(deaths)
        # the replay's own event counts against the probe's independent reader
        row["events_match_probe"] = {k: g.get(k, 0) == v for k, v in f["event_groups"].items()}
        sf = stream_facts(rp)
        row["players"] = sf["players"]
        row["players_with_movement"] = sf["players_with_movement"]
        row["step_ms_median"] = (sf["step_ms"] or {}).get("median")
        row["living_seconds_ge_100_samples"] = sf["living_seconds_ge_100_samples"]
        # every victim's track ends or parks at its death: a sample within 1 s before it
        near = 0
        for e in deaths:
            if e["victim"] in rp.players:
                P = rp.players[e["victim"]]["t"]
                k = np.searchsorted(P, e["t"])
                near += bool(k > 0 and e["t"] - P[k - 1] <= 1000.0)
        row["victims_tracked_at_death"] = near
        # positions inside the map's minimap square (valorant-api constants)
        try:
            ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
            mi = ref.maps.get(rp.map_url())
            if mi and mi.get("xMultiplier"):
                xs = np.concatenate([rp.players[s]["x"] for s in rp.subjects])
                ys = np.concatenate([rp.players[s]["y"] for s in rp.subjects])
                u, v = rg.game_to_uv(xs, ys, mi, True)
                row["share_inside_minimap"] = round(float(np.mean((u >= 0) & (u <= 1) &
                                                                  (v >= 0) & (v <= 1))), 5)
        except SystemExit:
            row["share_inside_minimap"] = None
        row["passes"] = bool(row["validate_exit"] == 0 and row["content_blocks_lost"] == 0
                             and row["deaths_resolved"] == row["deaths"]
                             and row["players_with_movement"] == row["players"] == 10
                             and all(row["events_match_probe"].values())
                             and (row.get("share_inside_minimap") or 0) >= 0.99)
        rows.append(row)
    return {"replay_truth_version": REPLAY_TRUTH_VERSION, "vrfkit": VRFKIT_VERSION,
            "replays": rows,
            "parsed": sum(1 for r in rows if r.get("export_exit") == 0),
            "passing": sum(1 for r in rows if r.get("passes"))}


# ----------------------------------------------------------------- metrics

def record_check(c: dict) -> list[str]:
    from reticle import metrics
    deps = {"replay_truth": REPLAY_TRUTH_VERSION, "vrfkit": VRFKIT_VERSION,
            "pos_tol_cm": POS_TOL_UNITS, "max_gap_ms": MAX_GAP_MS}
    k, p, f, r = c["kills"], c["positions"], c["facing"], c["rounds"]
    v = {"riot_kills": k["riot"], "replay_deaths": k["replay"], "paired": k["paired"],
         "killer_agree": k["killer_agree"], "victim_agree": k["victim_agree"],
         "offset_median_ms": k["riot_minus_replay_ms"]["median"],
         "offset_min_ms": k["offset_min_ms"], "offset_max_ms": k["offset_max_ms"],
         "kill_pos_median_cm": p["kill"]["dist_cm"]["median"],
         "kill_pos_p95_cm": p["kill"]["dist_cm"]["p95"],
         "kill_pos_within_tol": p["kill"]["within_tol"], "kill_pos_n": p["kill"]["dist_cm"]["n"],
         "plant_pos_median_cm": (p.get("plant") or {}).get("dist_cm", {}).get("median"),
         "victim_pos_median_cm": (p.get("victim") or {}).get("dist_cm", {}).get("median"),
         "facing_best": f["best_convention"],
         "facing_median_rad": f["by_convention_rad"][f["best_convention"]]["median"],
         "facing_within_0_05": f["within_0_05_rad"],
         "round_started": r["replay_round_started"],
         "round_zero_minus_started_median_ms": (r["riot_zero_minus_round_started_ms"] or {}).get("median"),
         "plants_within_250": c["plants"]["within_250ms"], "plants_riot": c["plants"]["riot"],
         "defuses_within_250": c["defuses"]["within_250ms"], "defuses_riot": c["defuses"]["riot"],
         "step_ms_median": c["stream"]["step_ms"]["median"],
         "samples_per_living_second_median": c["stream"]["samples_per_living_second"]["median"],
         "living_seconds_ge_100": c["stream"]["living_seconds_ge_100_samples"]}
    metrics.record("replay_truth", part="check", session=c["match"][:8], values=v, deps=deps)
    return [f"[metric:replay_truth/check#{key}={val}]" for key, val in v.items()]


# ----------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse")
    p.add_argument("replays", nargs="+", type=Path)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("check")
    p.add_argument("match")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("score")
    p.add_argument("session")
    p.add_argument("--geometry", type=Path, default=None,
                   help="a baked geometry npz in place of the session's own")
    p.add_argument("--out", default=None, help="report file name (default SESSION.json)")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("survey")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("handcheck")
    p.add_argument("session")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--geometry", type=Path, default=None)
    p = sub.add_parser("wrap")
    p.add_argument("match")
    p.add_argument("session")
    p.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
    if args.cmd == "handcheck":
        print(json.dumps(handcheck(args.session, args.n, args.geometry), indent=1, default=_default))
        return 0
    if args.cmd == "wrap":
        res = wrap_riot(args.match, args.session, args.write)
        print(json.dumps(res, indent=1))
        return 0 if "refused" not in res else 2
    if args.cmd == "parse":
        for v in args.replays:
            prov = parse_replay(v, args.force)
            print(json.dumps({"input": prov["input"], "sha_ok": prov["input_sha256_matches_manifest"],
                              **{k: (s["exit"], s["seconds"]) for k, s in prov["steps"].items()}}))
        return 0
    if args.cmd == "check":
        c = check(args.match)
        (parsed_dir(args.match) / "check.json").write_text(
            json.dumps(c, indent=1, default=_default), encoding="utf-8")
        print(json.dumps({k: v for k, v in c.items() if k != "positions"}, indent=1,
                         default=_default)[:6000])
        print(json.dumps(c.get("positions", {}), default=_default)[:3000])
        if args.record and "kills" in c:
            print("\n".join(record_check(c)))
        return 0
    if args.cmd == "score":
        # the scorer is the harness's (`question_acceptance.py replay-score`)
        import question_acceptance as qa
        argv = ["replay-score", args.session, "--legacy-out", args.out or f"{args.session}.json"]
        argv += ["--geometry", str(args.geometry)] if args.geometry else []
        argv += ["--record-score"] if args.record else []
        return qa.main(argv)
    if args.cmd == "survey":
        sv = survey()
        (PARSED / "survey.json").write_text(json.dumps(sv, indent=1, default=_default),
                                            encoding="utf-8")
        for r in sv["replays"]:
            print(json.dumps({k: r.get(k) for k in ("match", "map", "build", "rounds", "deaths",
                                                    "deaths_resolved", "validate_exit",
                                                    "content_blocks_lost", "share_inside_minimap",
                                                    "living_seconds_ge_100_samples", "passes")}))
        print(f"parsed {sv['parsed']}, passing {sv['passing']}")
        if args.record:
            from reticle import metrics
            metrics.record("replay_truth", part="survey",
                           values={"parsed": sv["parsed"], "passing": sv["passing"]},
                           deps={"replay_truth": REPLAY_TRUTH_VERSION, "vrfkit": VRFKIT_VERSION})
            print(" ".join(f"[metric:replay_truth/survey#{k}={sv[k]}]"
                           for k in ("parsed", "passing")))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
