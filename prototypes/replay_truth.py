r"""VALORANT replay files as external truth for evaluation.

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
`<store>/analysis/replay-truth-20261005/<session>.json`   `score`'s 0.2.0 report
(0.1.0's reports stay in `analysis/replay-truth-20261004/`)

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

`score` aligns replay time to capture time through STORED events only (replay
kills against the stored deaths' first killfeed sample, as `riot_ground_truth`
aligns Riot's kills; the stored round starts are the independent
cross-check) and maps world positions into baked widget pixels through
`riot_ground_truth.MapFrame` (valorant-api's map constants, the geometry's
`shade_fit`); `--geometry` names another baked npz, so one capture scores
before and after a geometry rebuild. 0.2.0 scores per frame and per track:

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
import hashlib
import json
import math
import subprocess
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

REPLAY_TRUTH_VERSION = "replay-truth-0.2.0"
STORE = Path.home() / "reticle-store"
REPLAYS = src.replays_dir(STORE)
VRFKIT_DIR = STORE / "tools" / "vrfkit"
VRFKIT_EXE = VRFKIT_DIR / "target" / "release" / "vrfkit.exe"
PARSED = src.parsed_root(STORE)
ANALYSIS = STORE / "analysis" / "replay-truth-20261005"

#: The stored minimap streams sample at 15 Hz; track minutes count frames of this grid.
GRID_HZ = 15.0
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
BELOW_NORMAL = 0x00004000


# ----------------------------------------------------------------- helpers

def _below_normal() -> None:
    rg._below_normal()


_stats = src.sample_stats


def _ang_deg(a, b):
    """Absolute angular difference in degrees, elementwise, in [0, 180]."""
    d = np.mod(np.asarray(a, float) - np.asarray(b, float), 360.0)
    return np.minimum(d, 360.0 - d)


def _ang_rad(a, b):
    d = np.mod(np.asarray(a, float) - np.asarray(b, float), 2 * math.pi)
    return np.minimum(d, 2 * math.pi - d)


# ----------------------------------------------------------------- parse

def _run(cmd: list[str], cwd: Path | None = None, out: Path | None = None) -> dict:
    """Run one command at Below Normal priority, single-threaded, and time it."""
    env = {**__import__("os").environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "RAYON_NUM_THREADS": "1"}
    t0 = time.time()
    flags = BELOW_NORMAL if sys.platform == "win32" else 0
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=flags)
    if out is not None:
        out.write_text(p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else ""),
                       encoding="utf-8")
    return {"cmd": cmd, "exit": p.returncode, "seconds": round(time.time() - t0, 2),
            "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-800:]}


def _git_head(d: Path) -> str:
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def _toolchain() -> dict:
    out = {}
    for tool in ("rustc", "cargo"):
        exe = Path.home() / ".cargo" / "bin" / f"{tool}.exe"
        out[tool] = subprocess.run([str(exe), "-V"], capture_output=True,
                                   text=True).stdout.strip() if exe.is_file() else None
    return out


def parse_replay(vrf: Path, force: bool = False) -> dict:
    """vrfkit validate + export + spike carrier for one preserved replay."""
    vrf = Path(vrf)
    match = vrf.stem
    d = parsed_dir(match)
    prov_p = d / "provenance.json"
    if prov_p.is_file() and not force:
        return json.loads(prov_p.read_text(encoding="utf-8"))
    d.mkdir(parents=True, exist_ok=True)
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    digest = sha256(vrf)
    man = json.loads((REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    want = next((f["sha256"] for f in man["files"] if f["file"] == vrf.name), None)
    steps = {}
    steps["validate"] = _run([str(VRFKIT_EXE), "validate", str(vrf)], out=d / "validate.txt")
    steps["export"] = _run([str(VRFKIT_EXE), "export", str(vrf), "--out", str(d / "export")],
                           out=d / "export.txt")
    if steps["export"]["exit"] == 0:
        steps["spike_carrier"] = _run(
            [sys.executable, str(VRFKIT_DIR / "tools" / "extract_spike_carrier.py"),
             "--export", str(d / "export"), "--out", str(d / "spike_carrier.parquet")],
            cwd=VRFKIT_DIR / "tools", out=d / "spike_carrier.txt")
    prov = {"kind": "vrfkit-parse", "replay_truth_version": REPLAY_TRUTH_VERSION,
            "input": str(vrf).replace("\\", "/"), "input_sha256": digest,
            "input_sha256_matches_manifest": digest == want,
            "vrfkit": {"version": VRFKIT_VERSION, "commit": _git_head(VRFKIT_DIR),
                       "exe": str(VRFKIT_EXE).replace("\\", "/"),
                       "exe_sha256": sha256(VRFKIT_EXE)},
            "toolchain": _toolchain(), "python": sys.version.split()[0],
            "priority": "Below Normal (creationflags 0x4000)",
            "started_utc": started,
            "finished_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "steps": steps}
    prov_p.write_text(json.dumps(prov, indent=1), encoding="utf-8")
    return prov


# ----------------------------------------------------------------- load

# ----------------------------------------------------------------- check

def riot_record(match: str) -> dict | None:
    p = STORE / "external" / "riot" / f"{match}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# ----------------------------------------------------------------- wrap

#: How far before Riot's game start a capture may begin, and the slack after
#: the game ends, when the capture file's name gives its local start time.
WRAP_EARLY_MS = 15 * 60 * 1000.0
WRAP_LATE_MS = 5 * 60 * 1000.0


def _capture_start_local_ms(capture_path: str) -> float | None:
    """The capture's start from its file name (`YYYY-MM-DD HH-MM-SS.mp4`, the
    recorder's local time) as epoch ms, or None when the name has no stamp."""
    stem = Path(str(capture_path).replace("\\", "/")).stem
    try:
        return _dt.datetime.strptime(stem[:19], "%Y-%m-%d %H-%M-%S").timestamp() * 1000.0
    except ValueError:
        return None


def wrap_record(raw: bytes, prov: dict, match: str, session: str, capture_path: str,
                replay_session: str | None, wrapped_sessions: dict[str, str]) -> dict:
    """One fetched match-details body as `riot_ground_truth`'s wrapped record.

    `raw` is `riot-pd-v1/raw/<match>.json` byte for byte and `prov` its
    sidecar; `replay_session` is the capture session the replay manifest names
    for this match (None when it names none); `wrapped_sessions` maps each
    session already wrapped in `external/riot/` to its match. Returns
    `{"record": ...}` or `{"refused": reason}`: a body whose sha256 differs
    from the sidecar's, a record of another match, a session another record
    already holds, a replay that names another session, or a capture whose
    name puts its start outside the game's span."""
    digest = hashlib.sha256(raw).hexdigest()
    if prov.get("body_sha256") != digest:
        return {"refused": "raw_sha256_differs_from_provenance"}
    rec = json.loads(raw.decode("utf-8"))
    info = rec.get("matchInfo") or {}
    if info.get("matchId") != match:
        return {"refused": f"record_is_match:{info.get('matchId')}"}
    if wrapped_sessions.get(session) not in (None, match):
        return {"refused": f"session_already_wrapped:{wrapped_sessions[session]}"}
    if replay_session not in (None, session):
        return {"refused": f"replay_names_session:{replay_session}"}
    start, length = info.get("gameStartMillis"), info.get("gameLengthMillis")
    cap = _capture_start_local_ms(capture_path)
    delta = None
    if cap is not None and start is not None:
        delta = cap - float(start)
        if not (-WRAP_EARLY_MS <= delta <= float(length or 0) + WRAP_LATE_MS):
            return {"refused": f"capture_outside_game:{delta / 1000.0:.0f}s"}
    probe = {"session_id": session, "capture": capture_path,
             "fetched_at": prov.get("fetched_at"),
             "wrapped_by": REPLAY_TRUTH_VERSION,
             "raw": f"external/riot-pd-v1/raw/{match}.json", "raw_sha256": digest,
             "capture_minus_game_start_s": None if delta is None else round(delta / 1000.0, 1)}
    return {"record": {"probe": probe, "match": rec}}


def wrap_riot(match: str, session: str, write: bool = False, store: Path = STORE) -> dict:
    """`wrap MATCH SESSION`: wrap a fetched record into `external/riot/`.

    Reads `external/riot-pd-v1/raw/<match>.json` and its provenance sidecar,
    checks them (`wrap_record`), and with `write` creates
    `external/riot/<match>.json`; it never overwrites a wrapped file."""
    from reticle.store import Store

    pd = Path(store) / "external" / "riot-pd-v1"
    raw_p, prov_p = pd / "raw" / f"{match}.json", pd / "provenance" / f"{match}.json"
    out_p = Path(store) / "external" / "riot" / f"{match}.json"
    if not raw_p.is_file() or not prov_p.is_file():
        return {"match": match, "refused": "no_fetched_record"}
    if out_p.is_file():
        return {"match": match, "refused": "already_wrapped", "path": str(out_p)}
    man = Store(store).read_manifest(session)
    rep = json.loads((Path(store) / "external" / "replays" / "manifest.json")
                     .read_text(encoding="utf-8"))
    entry = next((f for f in rep["files"] if Path(f["file"]).stem == match), None)
    wrapped = {sid: d["match"]["matchInfo"]["matchId"]
               for sid, d in rg.riot_records(Path(store)).items()}
    res = wrap_record(raw_p.read_bytes(), json.loads(prov_p.read_text(encoding="utf-8")),
                      match, session, man["source"]["path"],
                      (entry or {}).get("capture_session"), wrapped)
    if "refused" in res:
        return {"match": match, **res}
    out = {"match": match, "session": session, "path": str(out_p), "written": False,
           "probe": res["record"]["probe"]}
    if write:
        with out_p.open("x", encoding="utf-8") as f:
            json.dump(res["record"], f)
        out["written"] = True
    return out


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

def _rows(path: Path, needle: str | None = None):
    """Stream JSONL rows, skipping lines without `needle` before parsing."""
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if needle and needle not in line:
                continue
            if line.strip():
                yield json.loads(line)


def _assign(frame_ids, D, gate):
    """One-to-one obs->truth assignment within each frame, nearest first.

    `D` is (n_obs, n_truth) distances (NaN where the truth is absent). Two
    vectorised rounds: every observation takes its nearest truth; where two in
    one frame take the same truth the nearer keeps it, and the loser takes its
    nearest truth still free in that frame. Returns (truth index or -1, dist)."""
    n, k = D.shape
    Dm = np.where(np.isfinite(D), D, np.inf)
    j = np.argmin(Dm, axis=1)
    d = Dm[np.arange(n), j]
    ok = d <= gate
    key = frame_ids.astype(np.int64) * 64 + j
    o = np.lexsort((d, key))
    first = np.ones(n, bool)
    ks = key[o]
    first[1:] = ks[1:] != ks[:-1]
    win = np.zeros(n, bool)
    win[o] = first
    keep = ok & win
    lose = ok & ~win
    res_j = np.where(keep, j, -1)
    res_d = np.where(keep, d, np.nan)
    if lose.any():
        # only frames holding a loser need their taken set
        taken = defaultdict(set)
        sel = keep & np.isin(frame_ids, np.unique(frame_ids[lose]))
        for f, jj in zip(frame_ids[sel], j[sel]):
            taken[int(f)].add(int(jj))
        for i in np.flatnonzero(lose):
            free = [c for c in np.argsort(Dm[i]) if c not in taken[int(frame_ids[i])]
                    and Dm[i, c] <= gate]
            if free:
                c = int(free[0])
                taken[int(frame_ids[i])].add(c)
                res_j[i], res_d[i] = c, Dm[i, c]
    return res_j, res_d


def session_context(sid: str, geometry: Path | None = None) -> dict:
    """`reticle.replay_source.session_context` (the replay, player, teams,
    agents, the clock offset `a` fitted on stored deaths, the stored rounds
    and the baked `MapFrame`), plus this scorer's version and its 8 m teammate
    gate in widget px. `score` and `replay_abilities` both use it."""
    ctx = src.capture_replay_context(sid, geometry, STORE)
    ctx["out"]["replay_truth_version"] = REPLAY_TRUTH_VERSION
    if "refused" in ctx["out"]:
        return ctx
    ctx["gate"] = rg.GATE_M * 100.0 * ctx["mf"].px_per_unit
    ctx["out"]["gate_px"] = round(ctx["gate"], 2)
    return ctx


#: Miss classes, assigned in this fixed order: the first that holds names the
#: miss (the M0 design of `minimap-replay-plan-20261005`).
MISS_CLASSES = ("widget_absent", "stacked", "under_stored_occluder", "edge", "isolated")
#: A facing error above this many degrees is a flip: the icon read backwards.
FLIP_DEG = 135.0
#: A wrong name this soon after its teammate left a stack counts as stack-born.
STACK_LEAVE_MS = 1000.0
#: The minimap lags (ms) a lag scan tries in place of `rg.MINIMAP_LAG_MS`.
LAG_SCAN_MS = tuple(range(-1000, 501, 50))
#: How far the nearest row of a slower occluder stream may lie from the frame
#: it stands for: half its step (`ability_glyph` 2 Hz, `minimap_dark` 4 Hz,
#: `spike` 15 Hz).
DISC_TOL_MS, DARK_TOL_MS, SPIKE_TOL_MS = 250.0, 125.0, 34.0


def classify_misses(flags: dict) -> np.ndarray:
    """One class per missed truth frame: the first of `MISS_CLASSES` whose
    boolean array in `flags` holds there, else `isolated`. A class absent from
    `flags` never holds."""
    n = len(next(iter(flags.values()))) if flags else 0
    names = MISS_CLASSES[:-1]
    conds = [np.asarray(flags[k], bool) if k in flags else np.zeros(n, bool) for k in names]
    if n == 0:
        return np.array([], dtype=object)
    return np.select(conds, list(names), default=MISS_CLASSES[-1]).astype(object)


def track_metrics(life, t, ent, n_obs: int, hz: float = GRID_HZ, flag=None) -> dict:
    """Identity switches, fragments and IDF1 of stored tracks against truth lives.

    One row per living truth frame: `life` (a truth life: one player in one
    round), `t` (its frame time, ms) and `ent` (the stored entity matched to
    it, -1 where none was). A switch is a matched frame whose entity differs
    from its life's previous matched frame; a fragment is a maximal run of a
    life's consecutive rows matched to one entity, which a miss or a switch
    ends; an entity run is a run a switch ends but a miss does not. IDF1 pairs lives with entities one to one (scipy's Hungarian
    solver) to maximise co-matched frames: 2 IDTP / (T + P), T the truth rows
    and P the `n_obs` stored observations of the class. `flag`, a boolean per
    row, counts the switches whose row it marks (`switches_flagged`)."""
    from scipy.optimize import linear_sum_assignment

    life = np.asarray(life, np.int64)
    t = np.asarray(t, float)
    ent = np.asarray(ent, np.int64)
    o = np.lexsort((t, life))
    life, t, ent = life[o], t[o], ent[o]
    m = ent >= 0
    lm, em = life[m], ent[m]
    sw = (lm[1:] == lm[:-1]) & (em[1:] != em[:-1])
    switches = int(np.sum(sw))
    flagged = None if flag is None else int(np.sum(sw & np.asarray(flag, bool)[o][m][1:]))
    new_life = np.r_[True, life[1:] != life[:-1]] if life.size else np.zeros(0, bool)
    prev = np.r_[-1, ent[:-1]] if ent.size else np.zeros(0, np.int64)
    fragments = int(np.sum(m & (new_life | (prev != ent))))
    # runs of one entity a switch ends but a miss does not
    lm_new = np.r_[True, lm[1:] != lm[:-1]] if lm.size else np.zeros(0, bool)
    entity_runs = int(np.sum(lm_new | np.r_[True, em[1:] != em[:-1]])) if lm.size else 0
    idtp = 0.0
    if m.any():
        ul, li = np.unique(lm, return_inverse=True)
        ue, ei = np.unique(em, return_inverse=True)
        C = np.zeros((ul.size, ue.size))
        np.add.at(C, (li, ei), 1.0)
        r, c = linear_sum_assignment(-C)
        idtp = float(C[r, c].sum())
    minutes = t.size / hz / 60.0
    lives_matched = int(np.unique(lm).size)
    return {"truth_frames": int(t.size), "matched_frames": int(m.sum()),
            "truth_minutes": round(minutes, 2), "lives": int(np.unique(life).size),
            "lives_matched": lives_matched, "entities": int(np.unique(em).size),
            "switches": switches, "switches_flagged": flagged,
            "switches_per_truth_minute": round(switches / minutes, 3) if minutes else None,
            "fragments": fragments,
            "fragments_per_matched_life": round(fragments / lives_matched, 3) if lives_matched else None,
            "entity_runs": entity_runs,
            "entity_runs_per_matched_life": (round(entity_runs / lives_matched, 3)
                                             if lives_matched else None),
            "idtp": int(idtp), "observations": int(n_obs),
            "idf1": round(2.0 * idtp / (t.size + n_obs), 4) if (t.size + n_obs) else None,
            "id_precision": round(idtp / n_obs, 4) if n_obs else None,
            "id_recall": round(idtp / t.size, 4) if t.size else None}


def truth_px(rp, mf, subs, t_rep):
    """(n, k) widget px, image-degree facing and a living mask for subjects
    `subs` at replay times `t_rep`; NaN where dead or unsampled."""
    t_rep = np.asarray(t_rep, float)
    n, k = t_rep.size, len(subs)
    X, Y, YAW = (np.full((n, k), np.nan) for _ in range(3))
    L = np.zeros((n, k), bool)
    for c, s in enumerate(subs):
        q = rp.sample(s, t_rep)
        live = rp.alive(s, t_rep) & np.isfinite(q["x"])
        px, py = to_px(mf, q["x"], q["y"])
        L[:, c] = live
        X[:, c] = np.where(live, px, np.nan)
        Y[:, c] = np.where(live, py, np.nan)
        YAW[:, c] = np.where(live, facing_px_deg(mf, q["x"], q["y"], q["yaw"]), np.nan)
    return X, Y, YAW, L


def _stamp(row: dict, *keys) -> dict:
    return {k: row.get(k) for k in keys if row.get(k) is not None}


def load_ally_icon(sid: str) -> dict:
    """`ally_icon` frames (index, time, widget drawn, self fit) and icons
    (frame, centre, teardrop facing)."""
    f_i, f_t, f_d, f_sx, f_sy = [], [], [], [], []
    i_f, i_t, i_x, i_y, i_fac = [], [], [], [], []
    stamp = {}
    for r in _rows(STORE / "events" / "ally_icon" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "frame":
            f_i.append(r["frame_idx"])
            f_t.append(r["t_ms"])
            f_d.append(bool(r.get("widget_drawn")))
            s_ = r.get("self")
            f_sx.append(s_[0] if s_ else np.nan)
            f_sy.append(s_[1] if s_ else np.nan)
        elif k == "icon":
            i_f.append(r["frame_idx"])
            i_t.append(r["t_ms"])
            i_x.append(r["cx"])
            i_y.append(r["cy"])
            i_fac.append(np.nan if r.get("facing") is None else r["facing"])
        elif k == "coverage":
            stamp = _stamp(r, "ally_icon_version", "teardrop_version", "icon_teardrop_version",
                           "stack_fit_version", "candidate_revision")
    o = np.argsort(np.asarray(f_i), kind="stable")
    return {"frame_idx": np.asarray(f_i, np.int64)[o], "t_ms": np.asarray(f_t, float)[o],
            "drawn": np.asarray(f_d, bool)[o], "self_x": np.asarray(f_sx, float)[o],
            "self_y": np.asarray(f_sy, float)[o],
            "icon_frame": np.asarray(i_f, np.int64), "icon_t": np.asarray(i_t, float),
            "icon_x": np.asarray(i_x, float), "icon_y": np.asarray(i_y, float),
            "icon_facing": np.asarray(i_fac, float), "stamp": stamp}


def load_round_entity(sid: str) -> dict:
    """`round_entity` teammate observations (family ally or self) with their
    entity's id and agent."""
    ents, stamp = {}, {}
    o_f, o_t, o_x, o_y, o_e, o_fam = [], [], [], [], [], []
    for r in _rows(STORE / "events" / "round_entity" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "observation" and r.get("family") in ("ally", "self"):
            o_f.append(r["frame_idx"])
            o_t.append(r["t_ms"])
            o_x.append(r["x"])
            o_y.append(r["y"])
            o_e.append(r.get("entity_id"))
            o_fam.append(r["family"])
        elif k == "entity":
            ents[r["id"]] = r.get("agent")
        elif k == "coverage":
            stamp = _stamp(r, "round_entity_version", "round_lifetime_version",
                           "agent_identity_version", "ally_icon_revision") | {
                "inputs": r.get("inputs")}
    codes = {e: i for i, e in enumerate(sorted({e for e in o_e if e}))}
    return {"frame_idx": np.asarray(o_f, np.int64), "t_ms": np.asarray(o_t, float),
            "x": np.asarray(o_x, float), "y": np.asarray(o_y, float),
            "entity": np.asarray([codes.get(e, -1) for e in o_e], np.int64),
            "agent": np.asarray([ents.get(e) for e in o_e], dtype=object),
            "family": np.asarray(o_fam, dtype=object), "stamp": stamp}


def load_team_vision(sid: str) -> dict:
    """`team_vision` frames' widget state and its self and ally icons with a facing."""
    f_i, f_w = [], []
    i_f, i_t, i_x, i_y, i_fac, i_role = [], [], [], [], [], []
    stamp = {}
    for r in _rows(STORE / "events" / "team_vision" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "frame":
            f_i.append(r["frame_idx"])
            f_w.append(r.get("widget"))
            for ic in r.get("icons") or []:
                if ic.get("role") in ("ally", "self") and ic.get("facing") is not None:
                    i_f.append(r["frame_idx"])
                    i_t.append(r["t_ms"])
                    i_x.append(ic["x"])
                    i_y.append(ic["y"])
                    i_fac.append(ic["facing"])
                    i_role.append(ic["role"])
        elif k == "coverage":
            stamp = _stamp(r, "team_vision_version", "teardrop_version", "track_version",
                           "lifecycle_version")
    return {"frame_idx": np.asarray(f_i, np.int64), "widget": np.asarray(f_w, dtype=object),
            "icon_frame": np.asarray(i_f, np.int64), "icon_t": np.asarray(i_t, float),
            "icon_x": np.asarray(i_x, float), "icon_y": np.asarray(i_y, float),
            "icon_facing": np.asarray(i_fac, float), "icon_role": np.asarray(i_role, dtype=object),
            "stamp": stamp}


def load_minimap_object(sid: str) -> dict:
    """`minimap_object` frames (index, time, refusal) and enemy icons."""
    f_i, f_t, f_r = [], [], []
    e_f, e_t, e_x, e_y, e_fac = [], [], [], [], []
    stamp = {}
    for r in _rows(STORE / "events" / "minimap_object" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "frame":
            f_i.append(r["frame_idx"])
            f_t.append(r["t_ms"])
            f_r.append(r.get("reason"))
            if r.get("reason") is None:
                for e in r.get("enemies") or []:
                    e_f.append(r["frame_idx"])
                    e_t.append(r["t_ms"])
                    e_x.append(e["x"])
                    e_y.append(e["y"])
                    e_fac.append(e["facing"] if e.get("facing") is not None
                                 and e.get("facing_reason") is None else np.nan)
        elif k == "coverage":
            stamp = _stamp(r, "minimap_object_version", "teardrop_version", "geometry_key")
    return {"frame_idx": np.asarray(f_i, np.int64), "t_ms": np.asarray(f_t, float),
            "reason": np.asarray(f_r, dtype=object),
            "enemy_frame": np.asarray(e_f, np.int64), "enemy_t": np.asarray(e_t, float),
            "enemy_x": np.asarray(e_x, float), "enemy_y": np.asarray(e_y, float),
            "enemy_facing": np.asarray(e_fac, float), "stamp": stamp}


def load_enemy_track(sid: str) -> dict | None:
    """`enemy_track` observations with their entity's id and agent, or None."""
    p = STORE / "events" / "enemy_track" / f"{sid}.jsonl"
    if not p.is_file():
        return None
    ents, stamp = {}, {}
    o_f, o_t, o_x, o_y, o_e = [], [], [], [], []
    for r in _rows(p):
        k = r.get("kind")
        if k == "observation":
            o_f.append(r["frame_idx"])
            o_t.append(r["t_ms"])
            o_x.append(r["x"])
            o_y.append(r["y"])
            o_e.append(r.get("entity_id"))
        elif k == "entity":
            ents[r["id"]] = r.get("agent")
        elif k == "summary":
            stamp = _stamp(r, "enemy_track_version", "minimap_object_version",
                           "agent_identity_version", "lineup_version")
    codes = {e: i for i, e in enumerate(sorted({e for e in o_e if e}))}
    return {"frame_idx": np.asarray(o_f, np.int64), "t_ms": np.asarray(o_t, float),
            "x": np.asarray(o_x, float), "y": np.asarray(o_y, float),
            "entity": np.asarray([codes.get(e, -1) for e in o_e], np.int64),
            "agent": np.asarray([ents.get(e) for e in o_e], dtype=object), "stamp": stamp}


def load_occluders(sid: str) -> dict:
    """Stored things that can cover an icon: pings (active spans), accepted
    spike glyphs, ability glyph discs and `minimap_dark`'s grey-dark masks
    (smoke-like cover; its `occluded` mask marks teammate icons themselves,
    so it is not read), plus each frame's widget state where a witness other
    than `ally_icon` reads it."""
    ev = STORE / "events"
    pings = defaultdict(dict)
    for r in _rows(ev / "ping" / f"{sid}.jsonl"):
        p = pings[r["entity_id"]]
        if r.get("state") == "active" and r.get("position"):
            p["t0"], p["x"], p["y"] = float(r["t_ms"]), *map(float, r["position"])
        elif r.get("event_kind") == "entity_deleted":
            p["t1"] = float(r["t_ms"])
    ping = np.array([[p["t0"], p.get("t1", p["t0"] + 1000.0 * 8), p["x"], p["y"]]
                     for p in pings.values() if "t0" in p], float).reshape(-1, 4)
    sg = []
    for r in _rows(ev / "spike" / f"{sid}.jsonl", '"kind":"frame"'):
        for g in r.get("glyphs") or []:
            if g.get("reason") is None:
                sg.append((r["t_ms"], g["cx"], g["cy"], 0.5 * float(g.get("side") or 0.0)))
    discs = []
    for r in _rows(ev / "ability_glyph" / f"{sid}.jsonl", '"kind":"disc"'):
        discs.append((r["t_ms"], r["cx"], r["cy"], float(r.get("r") or 0.0)))
    dark_t, dark_m, dark_drawn = [], [], []
    stamps = {}
    for r in _rows(ev / "minimap_dark" / f"{sid}.jsonl"):
        if r.get("kind") == "frame":
            dark_t.append(r["t_ms"])
            dark_drawn.append(bool(r.get("widget_drawn")))
            dark_m.append(r.get("grey_dark") if r.get("reason") is None else None)
        elif r.get("kind") == "coverage":
            stamps["minimap_dark"] = r.get("minimap_dark_version")
    sg = np.array(sorted(sg), float).reshape(-1, 4)
    discs = np.array(sorted(discs), float).reshape(-1, 4)
    o = np.argsort(np.asarray(dark_t, float), kind="stable")
    return {"ping": ping, "spike_glyph": sg, "disc": discs,
            "dark_t": np.asarray(dark_t, float)[o], "dark_drawn": np.asarray(dark_drawn, bool)[o],
            "dark_mask": [dark_m[i] for i in o], "stamps": stamps}


def _near_points(t, x, y, pts, tol_ms, reach):
    """Per query (t, x, y), whether a point row (t, x, y, radius) of `pts`
    (sorted by t) lies within `tol_ms` and within `reach` + its radius."""
    hit = np.zeros(np.asarray(t).shape, bool)
    if pts.size == 0 or hit.size == 0:
        return hit
    lo = np.searchsorted(pts[:, 0], t - tol_ms, side="left")
    hi = np.searchsorted(pts[:, 0], t + tol_ms, side="right")
    for k in range(int((hi - lo).max(initial=0))):
        i = lo + k
        ok = i < hi
        ii = np.clip(i, 0, len(pts) - 1)
        d = np.hypot(pts[ii, 1] - x, pts[ii, 2] - y)
        hit |= ok & (d <= reach + pts[ii, 3])
    return hit


def _under_dark(t, x, y, occ, reach):
    """Per query, whether the nearest `minimap_dark` frame within
    `DARK_TOL_MS` marks grey-dark floor within `reach` px."""
    from reticle.lighting import unpack_mask

    hit = np.zeros(np.asarray(t).shape, bool)
    dt = occ["dark_t"]
    if dt.size == 0 or hit.size == 0:
        return hit
    j = np.clip(np.searchsorted(dt, t), 1, dt.size - 1) if dt.size > 1 else np.zeros(t.shape, int)
    if dt.size > 1:
        j = np.where(np.abs(dt[j - 1] - t) <= np.abs(dt[j] - t), j - 1, j)
    ok = np.abs(dt[j] - t) <= DARK_TOL_MS
    r = int(math.ceil(reach))
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    keep = dx ** 2 + dy ** 2 <= reach ** 2
    dx, dy = dx[keep], dy[keep]
    for u in np.unique(j[ok]):
        packed = occ["dark_mask"][u]
        if not packed:
            continue
        m = unpack_mask(packed)
        sel = np.flatnonzero(ok & (j == u))
        xs = np.clip(np.rint(x[sel])[:, None] + dx[None, :], 0, m.shape[1] - 1).astype(int)
        ys = np.clip(np.rint(y[sel])[:, None] + dy[None, :], 0, m.shape[0] - 1).astype(int)
        hit[sel] = m[ys, xs].any(axis=1)
    return hit


def _facing_block(err) -> dict:
    e = np.asarray(err, float)
    e = e[np.isfinite(e)]
    return {"n": int(e.size), "err_deg": _stats(e),
            "flip_share": round(float(np.mean(e > FLIP_DEG)), 4) if e.size else None,
            "within_30deg": round(float(np.mean(e <= 30.0)), 4) if e.size else None}


def _facing_lag_scan(rp, mf, subj, t_cap, fac, a) -> dict:
    """Median facing error per minimap lag in `LAG_SCAN_MS`, the pairs fixed."""
    subj = np.asarray(subj, dtype=object)
    scan = {}
    for L in LAG_SCAN_MS:
        err = np.full(t_cap.size, np.nan)
        for s in set(subj.tolist()):
            m = subj == s
            q = rp.sample(s, _frames_to_replay(t_cap[m], a, L))
            err[m] = _ang_deg(facing_px_deg(mf, q["x"], q["y"], q["yaw"]), fac[m])
        scan[int(L)] = round(float(np.nanmedian(err)), 3) if np.isfinite(err).any() else None
    ok = {k: v for k, v in scan.items() if v is not None}
    return {"median_err_deg_by_lag_ms": scan, "best_lag_ms": min(ok, key=ok.get) if ok else None}


def score(sid: str, geometry: Path | None = None) -> dict:
    """Score one capture's stored minimap streams against its replay (0.2.0).

    The denominator is the `ally_icon` frame grid restricted to the minimap
    crop cache's spans (`roi_cache`) and to frames where `ally_icon` reads the
    widget drawn; frames outside the spans or with the widget absent are
    counted apart and never enter a share. Within it: teammates per frame
    (`round_entity` observations, located within 8 m one to one, phantoms with
    no living teammate within 8 m), names, tracks (switches, fragments, IDF1),
    each missed teammate frame's class (`MISS_CLASSES`, in order), the self
    fit, enemies (`minimap_object`, names through `enemy_track`) and facing per
    class with a lag scan. `geometry` overrides the baked geometry
    (`session_context`)."""
    from reticle import roi_cache

    ctx = session_context(sid, geometry)
    out = ctx["out"]
    if "refused" in out:
        return out
    rp, mf, a, me, team = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"], ctx["team"]
    allies, foes, agent = ctx["allies"], ctx["foes"], ctx["agent"]
    cm_per_px, gate = ctx["cm_per_px"], ctx["gate"]
    H, W = mf.widget_shape
    r_icon = float(mf.icon_px)
    lag = rg.MINIMAP_LAG_MS
    rs = rp.round_starts()
    out["r_icon_px"] = round(r_icon, 3)
    stamps = {}

    # -- the denominator: ally_icon's frames inside the crop cache, widget drawn
    AI = load_ally_icon(sid)
    stamps["ally_icon"] = AI["stamp"]
    rec = roi_cache.stored_record(STORE, sid, "minimap")
    spans = (rec or {}).get("spans") or []
    in_sp = roi_cache.spans_mask(AI["t_ms"], spans)
    sc = in_sp & AI["drawn"]
    S_idx, S_t = AI["frame_idx"][sc], AI["t_ms"][sc]
    S_rep = _frames_to_replay(S_t, a, lag)
    n = int(S_idx.size)
    out["frames"] = {
        "rule": "ally_icon frames inside the minimap crop cache's spans with widget_drawn",
        "ally_icon_frames": int(AI["t_ms"].size), "outside_cache_spans": int((~in_sp).sum()),
        "in_spans_widget_absent": int((in_sp & ~AI["drawn"]).sum()), "scored": n,
        "cache": None if rec is None else {"version": rec.get("version"), "hz": rec.get("hz"),
                                           "spans": len(spans)}}

    def rows_of(fi):
        fi = np.asarray(fi, np.int64)
        if n == 0:
            return np.zeros(fi.shape, np.int64), np.zeros(fi.shape, bool)
        k = np.clip(np.searchsorted(S_idx, fi), 0, n - 1)
        return k, S_idx[k] == fi

    mates = list(allies)
    c_me = mates.index(me)
    TX, TY, TYAW, TL = truth_px(rp, mf, mates, S_rep)
    rnd = np.searchsorted(rs, S_rep, side="right") - 1
    # truth-side context per (frame, teammate)
    dd = np.hypot(TX[:, :, None] - TX[:, None, :], TY[:, :, None] - TY[:, None, :])
    dd[:, np.arange(len(mates)), np.arange(len(mates))] = np.inf
    stacked = TL & (np.nanmin(np.where(np.isfinite(dd), dd, np.inf), axis=2) <= 2.0 * r_icon)
    edge = TL & ((TX < r_icon) | (TX > W - 1 - r_icon) | (TY < r_icon) | (TY > H - 1 - r_icon))
    # time since each teammate was last stacked (frames in time order)
    last_st = np.where(stacked, S_t[:, None], -np.inf)
    last_st = np.maximum.accumulate(last_st, axis=0)
    since_stack = S_t[:, None] - last_st

    # -- teammates: round_entity observations
    RE = load_round_entity(sid)
    stamps["round_entity"] = RE["stamp"]
    k, ok = rows_of(RE["frame_idx"])
    rows = k[ok]
    ox, oy, eid = RE["x"][ok], RE["y"][ok], RE["entity"][ok]
    fam, oname = RE["family"][ok], RE["agent"][ok]
    D = np.hypot(TX[rows] - ox[:, None], TY[rows] - oy[:, None])
    j, dist = _assign(rows, D, gate)
    hit = j >= 0
    nearest = np.min(np.where(np.isfinite(D), D, np.inf), axis=1) if D.size else np.zeros(0)
    phantom = ~(nearest <= gate)
    G = np.zeros(TL.shape, bool)          # located by any observation
    G[rows[hit], j[hit]] = True
    M = np.full(TL.shape, -1, np.int64)   # the located observation's entity
    M[rows[hit], j[hit]] = eid[hit]
    obs_class = np.where(fam == "self", "self", "ally")
    truth_cls = np.array(["self" if c == c_me else "ally" for c in range(len(mates))])
    tm = {"observations": int(RE["x"].size), "observations_outside_scored_frames": int((~ok).sum()),
          "observations_scored": int(ok.sum()),
          "observations_without_entity": int(np.sum(eid < 0))}

    def mate_block(cols, obs_mask):
        live = TL[:, cols]
        got = G[:, cols]
        hm = hit & obs_mask
        return {"living_truth_frames": int(live.sum()), "matched": int(got.sum()),
                "recall": round(float(got.sum() / max(1, live.sum())), 4),
                "observations": int(obs_mask.sum()), "phantom": int((phantom & obs_mask).sum()),
                "phantom_share": round(float((phantom & obs_mask).sum() / max(1, obs_mask.sum())), 4),
                "duplicate": int((~hit & ~phantom & obs_mask).sum()),
                "err_px": _stats(dist[hm]), "err_cm": _stats(dist[hm] * cm_per_px, 0),
                "within_r_icon": round(float(np.mean(dist[hm] <= r_icon)), 4) if hm.any() else None}

    all_cols = list(range(len(mates)))
    ally_cols = [c for c in all_cols if c != c_me]
    tm["pooled"] = mate_block(all_cols, np.ones(hit.shape, bool))
    tm["self"] = mate_block([c_me], obs_class == "self")
    tm["ally"] = mate_block(ally_cols, obs_class == "ally")
    tm["family_vs_truth"] = {f"{o_}->{t_}": int(np.sum(hit & (obs_class == o_) & (truth_cls[np.clip(j, 0, None)] == t_)))
                             for o_ in ("self", "ally") for t_ in ("self", "ally")}

    # names: the entity's agent against the replay's
    truth_agent = np.array([agent.get(mates[c]) if c >= 0 else None for c in j], dtype=object)
    named = hit & np.array([g is not None for g in oname], bool)
    right = named & np.array([rg.canon(g) == rg.canon(t_) for g, t_ in zip(oname, truth_agent)], bool)
    wrong = named & ~right
    jc = np.clip(j, 0, None)
    w_stacked = stacked[rows, jc] & wrong
    w_left = wrong & ~w_stacked & (since_stack[rows, jc] <= STACK_LEAVE_MS)
    wrong_pairs = Counter((t_, g) for t_, g, w in zip(truth_agent, oname, wrong) if w)
    tm["names"] = {"named": int(named.sum()), "right": int(right.sum()), "wrong": int(wrong.sum()),
                   "refused": int((hit & ~named).sum()),
                   "agreement": round(float(right.sum() / named.sum()), 4) if named.any() else None,
                   "wrong_share": round(float(wrong.sum() / named.sum()), 4) if named.any() else None,
                   "wrong_stacked": int(w_stacked.sum()),
                   "wrong_within_1s_of_leaving_stack": int(w_left.sum()),
                   "wrong_stack_share": (round(float((w_stacked | w_left).sum() / wrong.sum()), 4)
                                         if wrong.any() else None),
                   "unnamed_reason": None if named.any() else "no located observation's entity names an agent",
                   "wrong_pairs_truth_got": [[t_, g, c] for (t_, g), c in wrong_pairs.most_common(12)]}

    # tracks: one truth life is one teammate in one replay round
    # a second observation the one-to-one pass left beside a teammate
    dup = ~hit & ~phantom
    dupm = np.zeros(TL.shape, bool)
    if dup.any():
        dupm[rows[dup], np.argmin(np.where(np.isfinite(D[dup]), D[dup], np.inf), axis=1)] = True
    tr, tc = np.nonzero(TL)
    life = tc * 1000 + rnd[tr]
    tm["tracks"] = {}
    for name, cols, om in (("pooled", all_cols, np.ones(hit.shape, bool)),
                           ("self", [c_me], obs_class == "self"),
                           ("ally", ally_cols, obs_class == "ally")):
        sel = np.isin(tc, cols)
        tm["tracks"][name] = track_metrics(life[sel], S_t[tr[sel]], M[tr[sel], tc[sel]],
                                           int(om.sum()), flag=stacked[tr[sel], tc[sel]])
        tm["tracks"][name]["switches_beside_duplicate"] = track_metrics(
            life[sel], S_t[tr[sel]], M[tr[sel], tc[sel]], int(om.sum()),
            flag=dupm[tr[sel], tc[sel]])["switches_flagged"]
        tm["tracks"][name]["switches_stacked_or_duplicate"] = track_metrics(
            life[sel], S_t[tr[sel]], M[tr[sel], tc[sel]], int(om.sum()),
            flag=(stacked | dupm)[tr[sel], tc[sel]])["switches_flagged"]
    tm["tracks"]["switches_flagged_means"] = "the teammate is stacked at the switch frame"
    tm["tracks"]["switches_beside_duplicate_means"] = ("another observation the one-to-one pass "
                                                       "left within 8 m lies nearest this "
                                                       "teammate at the switch frame")

    # misses: every living truth frame no observation located, one class each
    mr, mc = np.nonzero(TL & ~G)
    occ = load_occluders(sid)
    TV = load_team_vision(sid)
    MO = load_minimap_object(sid)
    stamps["team_vision"] = TV["stamp"]
    stamps["minimap_object"] = MO["stamp"]
    stamps["minimap_dark"] = occ["stamps"].get("minimap_dark")
    absent_fi = set(TV["frame_idx"][TV["widget"] == "not_drawn"].tolist())
    absent_fi |= set(MO["frame_idx"][MO["reason"] == "widget_not_drawn"].tolist())
    dk = np.clip(np.searchsorted(occ["dark_t"], S_t), 0, max(occ["dark_t"].size - 1, 0))
    if occ["dark_t"].size:
        dark_absent = (np.abs(occ["dark_t"][dk] - S_t) <= 1.0) & ~occ["dark_drawn"][dk]
    else:
        dark_absent = np.zeros(n, bool)
    frame_absent = np.isin(S_idx, list(absent_fi)) | dark_absent
    mx, my, mt = TX[mr, mc], TY[mr, mc], S_t[mr]
    # a ping holds a span, not an instant: active from t0 to t1
    ph = np.zeros(mr.size, bool)
    for t0, t1, px, py in occ["ping"]:
        ph |= (mt >= t0) & (mt <= t1) & (np.hypot(mx - px, my - py) <= r_icon)
    under = {"ping": ph}
    under["spike_glyph"] = _near_points(mt, mx, my, occ["spike_glyph"], SPIKE_TOL_MS, r_icon)
    under["ability_glyph"] = _near_points(mt, mx, my, occ["disc"], DISC_TOL_MS, r_icon)
    under["minimap_dark"] = _under_dark(mt, mx, my, occ, r_icon)
    any_under = np.zeros(mr.size, bool)
    for v in under.values():
        any_under |= v
    # the same tests on located frames: how often cover sits near a teammate
    # the stream did locate, so a miss class is read against its base rate
    lr, lc = np.nonzero(TL & G)
    lx, ly, lt = TX[lr, lc], TY[lr, lc], S_t[lr]
    lp = np.zeros(lr.size, bool)
    for t0, t1, px, py in occ["ping"]:
        lp |= (lt >= t0) & (lt <= t1) & (np.hypot(lx - px, ly - py) <= r_icon)
    base = {"ping": lp,
            "spike_glyph": _near_points(lt, lx, ly, occ["spike_glyph"], SPIKE_TOL_MS, r_icon),
            "ability_glyph": _near_points(lt, lx, ly, occ["disc"], DISC_TOL_MS, r_icon),
            "minimap_dark": _under_dark(lt, lx, ly, occ, r_icon)}
    base_any = np.zeros(lr.size, bool)
    for v in base.values():
        base_any |= v
    cls = classify_misses({"widget_absent": frame_absent[mr], "stacked": stacked[mr, mc],
                           "under_stored_occluder": any_under, "edge": edge[mr, mc]})
    # minimap_dark's grey-dark floor lies within r_icon of most located
    # teammates too (`occluder_share_located`), so the same order without it
    # is reported beside the fixed rule, never in its place
    no_dark = under["ping"] | under["spike_glyph"] | under["ability_glyph"]
    cls_nd = classify_misses({"widget_absent": frame_absent[mr], "stacked": stacked[mr, mc],
                              "under_stored_occluder": no_dark, "edge": edge[mr, mc]})

    def miss_block(mask, cls=cls):
        c = Counter(cls[mask].tolist())
        tot = int(mask.sum())
        return {"missed": tot, **{f"{k}": int(c.get(k, 0)) for k in MISS_CLASSES},
                "shares": {k: round(c.get(k, 0) / tot, 4) if tot else None for k in MISS_CLASSES}}
    tm["misses"] = {"order": list(MISS_CLASSES),
                    "pooled": miss_block(np.ones(mr.size, bool)),
                    "self": miss_block(mc == c_me), "ally": miss_block(mc != c_me),
                    "pooled_without_minimap_dark": miss_block(np.ones(mr.size, bool), cls_nd),
                    "occluder_kinds_any_order": {k: int(v.sum()) for k, v in under.items()},
                    "occluder_share_missed": {k: round(float(v.mean()), 4) if v.size else None
                                              for k, v in (under | {"any": any_under}).items()},
                    "occluder_share_located": {k: round(float(v.mean()), 4) if v.size else None
                                               for k, v in (base | {"any": base_any}).items()},
                    "stacked_share_located": round(float(stacked[lr, lc].mean()), 4) if lr.size else None,
                    "rules": {"widget_absent": "team_vision widget not_drawn, minimap_object "
                                               "widget_not_drawn or minimap_dark widget_drawn false "
                                               "at the frame",
                              "stacked": "another living teammate (or the self) within 2 r_icon",
                              "under_stored_occluder": "an active ping within r_icon; an accepted "
                                                       "spike glyph or ability glyph disc within "
                                                       "r_icon plus its radius; grey-dark "
                                                       "minimap_dark floor within r_icon",
                              "edge": "within r_icon of the widget's border",
                              "isolated": "none of the above"}}
    out["teammates"] = tm

    # -- the self fit (ally_icon), within the scored frames
    fx, fy = AI["self_x"][sc], AI["self_y"][sc]
    q = rp.sample(me, S_rep)
    me_live = TL[:, c_me]
    sx, sy = to_px(mf, q["x"], q["y"])
    has = np.isfinite(fx)
    e_self = np.hypot(sx - fx, sy - fy)
    m_ = has & me_live
    selfo = {"self_fits": int(has.sum()), "self_fits_player_alive": int(m_.sum()),
             "self_fits_player_dead": int((has & ~me_live).sum()),
             "living_frames": int(me_live.sum()),
             "located_within_gate": int(np.sum(m_ & (e_self <= gate))),
             "recall": round(float(np.sum(m_ & (e_self <= gate)) / max(1, me_live.sum())), 4),
             "err_px": _stats(e_self[m_]), "err_cm": _stats(e_self[m_] * cm_per_px, 0),
             "beyond_gate": int(np.sum(e_self[m_] > gate))}
    scan = {}
    for L in LAG_SCAN_MS:
        qq = rp.sample(me, _frames_to_replay(S_t[m_], a, L))
        px, py = to_px(mf, qq["x"], qq["y"])
        scan[int(L)] = round(float(np.nanmedian(np.hypot(px - fx[m_], py - fy[m_]))), 3) if m_.any() else None
    selfo["lag_scan_median_px"] = scan
    okscan = {k_: v for k_, v in scan.items() if v is not None}
    selfo["best_lag_ms"] = min(okscan, key=okscan.get) if okscan else None
    w = m_ & (e_self <= gate)
    if w.sum() > 20:
        A = np.column_stack([q["x"][w], q["y"][w], np.ones(w.sum())])
        cx, *_ = np.linalg.lstsq(A, fx[w], rcond=None)
        cy, *_ = np.linalg.lstsq(A, fy[w], rcond=None)
        res = np.hypot(A @ cx - fx[w], A @ cy - fy[w])
        selfo["affine_fit_on_self"] = {"n": int(w.sum()), "residual_px": _stats(res),
                                       "baked_transform_err_px": _stats(e_self[w]),
                                       "coef_x": [round(float(c), 6) for c in cx],
                                       "coef_y": [round(float(c), 6) for c in cy]}
    out["self"] = selfo

    # -- enemies: minimap_object icons, names through enemy_track
    out["enemies"] = score_enemies(sid, rp, mf, a, foes, agent, gate, cm_per_px, r_icon, MO, rs,
                                   stamps)

    # -- facing per class
    fac = {}
    # self: team_vision's self icon against the player
    kk, okk = rows_of(TV["icon_frame"])
    sel = okk & (TV["icon_role"] == "self")
    rr = kk[sel]
    d_ = np.hypot(TX[rr, c_me] - TV["icon_x"][sel], TY[rr, c_me] - TV["icon_y"][sel])
    good = np.isfinite(d_) & (d_ <= gate)
    err = _ang_deg(TYAW[rr, c_me], TV["icon_facing"][sel])[good]
    fac["self_team_vision"] = {**_facing_block(err), "source": "team_vision role self",
                               **_facing_lag_scan(rp, mf, [me] * int(good.sum()),
                                                  TV["icon_t"][sel][good],
                                                  TV["icon_facing"][sel][good], a)}

    def ally_facing(fr, fx_, fy_, ff, ft, source):
        kk2, ok2 = rows_of(fr)
        ok2 &= np.isfinite(ff)
        r2 = kk2[ok2]
        D2 = np.hypot(TX[r2][:, ally_cols] - fx_[ok2][:, None], TY[r2][:, ally_cols] - fy_[ok2][:, None])
        j2, _d2 = _assign(r2, D2, gate)
        h2 = j2 >= 0
        cols = np.asarray(ally_cols)[np.clip(j2, 0, None)]
        e2 = _ang_deg(TYAW[r2, cols], ff[ok2])[h2]
        subj = [mates[c] for c in cols[h2]]
        return {**_facing_block(e2), "icons": int(ok2.sum()), "located": int(h2.sum()),
                "source": source,
                **_facing_lag_scan(rp, mf, subj, ft[ok2][h2], ff[ok2][h2], a)}

    fac["ally_ally_icon"] = ally_facing(AI["icon_frame"], AI["icon_x"], AI["icon_y"],
                                        AI["icon_facing"], AI["icon_t"],
                                        "ally_icon icon teardrop facing, non-self teammates")
    am = TV["icon_role"] == "ally"
    fac["ally_team_vision"] = ally_facing(TV["icon_frame"][am], TV["icon_x"][am], TV["icon_y"][am],
                                          TV["icon_facing"][am], TV["icon_t"][am],
                                          "team_vision role ally")
    fac["enemy_minimap_object"] = out["enemies"].pop("_facing", None)
    out["facing"] = fac

    # -- spike: the HUD marker and the minimap glyph against the replay's carrier
    out["spike"] = score_spike(sid, rp, mf, a, allies, foes, team, me)
    out["stamps"] = stamps
    out["agents"] = None   # never written: subjects stay in the store
    return out


def score_enemies(sid, rp, mf, a, foes, agent, gate, cm_per_px, r_icon, MO, rs, stamps) -> dict:
    """`minimap_object` enemy icons against the replay's living foes, and
    `enemy_track`'s names and tracks.

    An icon is located when one-to-one assignment within 8 m gives it a
    living foe; a phantom has no living foe within 8 m. Recall is not scored:
    whether the minimap must draw a foe is unknown here. `enemy_track`
    observations are located the same way and their entity's agent compared
    with the replay's; track metrics count only located observations."""
    lag = rg.MINIMAP_LAG_MS
    read = MO["reason"] == None  # noqa: E711 (object array)
    out = {"frames": int(MO["frame_idx"].size), "frames_read": int(read.sum()),
           "frames_refused": dict(Counter(r for r in MO["reason"].tolist() if r is not None)),
           "icons": int(MO["enemy_x"].size)}
    if MO["enemy_x"].size:
        t_rep = _frames_to_replay(MO["enemy_t"], a, lag)
        X, Y, YAW, _L = truth_px(rp, mf, foes, t_rep)
        D = np.hypot(X - MO["enemy_x"][:, None], Y - MO["enemy_y"][:, None])
        j, dist = _assign(MO["enemy_frame"], D, gate)
        hit = j >= 0
        nearest = np.min(np.where(np.isfinite(D), D, np.inf), axis=1)
        phantom = ~(nearest <= gate)
        out.update(matched=int(hit.sum()), phantom=int(phantom.sum()),
                   phantom_share=round(float(phantom.mean()), 4),
                   duplicate=int((~hit & ~phantom).sum()),
                   err_px=_stats(dist[hit]), err_cm=_stats(dist[hit] * cm_per_px, 0),
                   within_r_icon=round(float(np.mean(dist[hit] <= r_icon)), 4) if hit.any() else None)
        ff = MO["enemy_facing"]
        fh = hit & np.isfinite(ff)
        jc = np.clip(j, 0, None)
        e = _ang_deg(YAW[np.arange(j.size), jc], ff)[fh]
        out["_facing"] = {**_facing_block(e), "source": "minimap_object enemy teardrop",
                          **_facing_lag_scan(rp, mf, [foes[c] for c in jc[fh]], MO["enemy_t"][fh],
                                             ff[fh], a)}
    ET = load_enemy_track(sid)
    if ET is None:
        out["enemy_track"] = {"refused": "no_stored_enemy_track"}
        return out
    stamps["enemy_track"] = ET["stamp"]
    t_rep = _frames_to_replay(ET["t_ms"], a, lag)
    X, Y, _YAW, _L = truth_px(rp, mf, foes, t_rep)
    D = np.hypot(X - ET["x"][:, None], Y - ET["y"][:, None])
    j, dist = _assign(ET["frame_idx"], D, gate)
    hit = j >= 0
    nearest = np.min(np.where(np.isfinite(D), D, np.inf), axis=1) if D.size else np.zeros(0)
    phantom = ~(nearest <= gate)
    truth_agent = np.array([agent.get(foes[c]) if c >= 0 else None for c in j], dtype=object)
    named = hit & np.array([g is not None for g in ET["agent"]], bool)
    right = named & np.array([rg.canon(g) == rg.canon(t_) for g, t_ in zip(ET["agent"], truth_agent)],
                             bool)
    wrong_pairs = Counter((t_, g) for t_, g, w in zip(truth_agent, ET["agent"], named & ~right) if w)
    rnd = np.searchsorted(rs, t_rep, side="right") - 1
    life = np.clip(j, 0, None) * 1000 + rnd
    trk = track_metrics(life[hit], ET["t_ms"][hit], ET["entity"][hit], int(ET["x"].size))
    # truth frames are only the located ones (drawn-ness is unknown): IDF1 and
    # id_recall would read as precision, so only id_precision stands
    for k in ("idf1", "id_recall", "truth_frames", "truth_minutes", "switches_per_truth_minute"):
        trk.pop(k, None)
    mins = hit.sum() / GRID_HZ / 60.0
    trk["switches_per_located_minute"] = round(trk["switches"] / mins, 3) if mins else None
    out["enemy_track"] = {"observations": int(ET["x"].size), "matched": int(hit.sum()),
                          "phantom": int(phantom.sum()),
                          "phantom_share": round(float(phantom.mean()), 4) if phantom.size else None,
                          "err_px": _stats(dist[hit]),
                          "names": {"named": int(named.sum()), "right": int(right.sum()),
                                    "wrong": int((named & ~right).sum()),
                                    "refused": int((hit & ~named).sum()),
                                    "agreement": (round(float(right.sum() / named.sum()), 4)
                                                  if named.any() else None),
                                    "wrong_pairs_truth_got": [[t_, g, c] for (t_, g), c
                                                              in wrong_pairs.most_common(8)]},
                          "tracks": trk}
    return out


def score_spike(sid, rp, mf, a, allies, foes, team, me) -> dict:
    import pyarrow.parquet as pq

    p = rp.dir / "spike_carrier.parquet"
    if not p.is_file():
        return {"refused": "no_replay_spike_carrier"}
    iv = pq.read_table(p).to_pylist()
    held = [r for r in iv if r["holder_kind"] in ("player", "proxy") and r["carrier_subject"]]
    f0 = np.array([r["from_ms"] for r in held], float)
    f1 = np.array([r["to_ms"] if r["to_ms"] is not None else np.inf for r in held], float)
    who = np.array([r["carrier_subject"] for r in held], dtype=object)

    def carrier_at(t):
        t = np.asarray(t, float)
        k = np.searchsorted(f0, t, side="right") - 1
        ok = (k >= 0) & (t < f1[np.clip(k, 0, None)])
        return np.where(ok, who[np.clip(k, 0, None)], None)

    s_t, s_slot, s_glyph = [], [], []
    for r in _rows(STORE / "events" / "spike" / f"{sid}.jsonl", '"kind":"frame"'):
        if r.get("reason") is not None:
            continue
        s_t.append(r["t_ms"])
        s_slot.append((r.get("marker") or {}).get("slot"))
        g = [x for x in r.get("glyphs") or [] if x.get("reason") is None]
        s_glyph.append(g)
    if not s_t:
        return {"refused": "no_spike_frames"}
    s_t = np.array(s_t)
    t_rep = _frames_to_replay(s_t, a, rg.MINIMAP_LAG_MS)
    car = carrier_at(t_rep)
    ally_car = np.array([c is not None and team.get(c) == team[me] for c in car])
    foe_car = np.array([c is not None and team.get(c) != team[me] for c in car])
    marker = np.array([s is not None for s in s_slot])
    out = {"frames": int(s_t.size),
           "marker_vs_ally_carrier": {"both": int((marker & ally_car).sum()),
                                      "marker_only": int((marker & ~ally_car).sum()),
                                      "carrier_only": int((~marker & ally_car).sum()),
                                      "neither": int((~marker & ~ally_car).sum())},
           "frames_enemy_carries": int(foe_car.sum())}
    # carried glyph position against the carrier
    errs, kinds = [], Counter()
    gx, gy, gt, gc = [], [], [], []
    for t, gl, c in zip(t_rep, s_glyph, car):
        for g in gl:
            kinds[(g["state"], "ally" if c in allies else "foe" if c in foes else "none")] += 1
            if g["state"] == "carried" and c is not None:
                gx.append(g["cx"])
                gy.append(g["cy"])
                gt.append(t)
                gc.append(c)
    if gx:
        gx, gy, gt = np.array(gx, float), np.array(gy, float), np.array(gt)
        tx, ty = np.full(gt.size, np.nan), np.full(gt.size, np.nan)
        for s in set(gc):
            m = np.array([c == s for c in gc])
            q = rp.sample(s, gt[m])
            tx[m], ty[m] = to_px(mf, q["x"], q["y"])
        errs = np.hypot(tx - gx, ty - gy)
    out["glyph_state_by_replay_carrier"] = {f"{k[0]}|{k[1]}": n for k, n in sorted(kinds.items())}
    out["carried_glyph_err_px"] = _stats(errs) if len(errs) else None
    # stored per-round carrier_seen against the replay's rounds with an allied carrier
    rs = rp.round_starts()
    rounds_ally = set()
    for r in held:
        if team.get(r["carrier_subject"]) == team[me]:
            rounds_ally.add(int(np.searchsorted(rs, r["from_ms"], side="right")))
    stored = [r for r in _rows(STORE / "events" / "spike_carrier" / f"{sid}.jsonl", '"kind":"round"')]
    seen = {r["round_no"] for r in stored if r.get("carrier_seen")}
    out["rounds"] = {"replay_ally_carrier_rounds": len(rounds_ally),
                     "stored_carrier_seen_rounds": len(seen),
                     "seen_and_ally_carrier": len(seen & rounds_ally),
                     "seen_without_ally_carrier": sorted(seen - rounds_ally),
                     "ally_carrier_not_seen": sorted(rounds_ally - seen)}
    return out


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
    rp, mf, a = ctx["rp"], ctx["mf"], ctx["a"]
    mates, agent, me = ctx["allies"], ctx["agent"], ctx["me"]
    AI = load_ally_icon(sid)
    rec = roi_cache.stored_record(STORE, sid, "minimap")
    sc = roi_cache.spans_mask(AI["t_ms"], (rec or {}).get("spans") or []) & AI["drawn"]
    idx, ts = AI["frame_idx"][sc], AI["t_ms"][sc]
    RE = load_round_entity(sid)
    pick = [int(round(x)) for x in np.linspace(0, idx.size - 1, n + 2)[1:-1]]
    frames = []
    for p_ in pick:
        # move forward to a frame with at least three living teammates
        while p_ < idx.size - 1:
            t_rep = float(_frames_to_replay([ts[p_]], a, rg.MINIMAP_LAG_MS)[0])
            if sum(bool(rp.alive(s, [t_rep])[0]) for s in mates) >= 3:
                break
            p_ += 15
        t_rep = float(_frames_to_replay([ts[p_]], a, rg.MINIMAP_LAG_MS)[0])
        m = RE["frame_idx"] == idx[p_]
        obs = [[round(float(x), 2), round(float(y), 2), str(f)] for x, y, f
               in zip(RE["x"][m], RE["y"][m], RE["family"][m])]
        rows = []
        for s in mates:
            if not rp.alive(s, [t_rep])[0]:
                continue
            q = rp.sample(s, [t_rep])
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
    return {"session": sid, "a_ms": a, "lag_ms": rg.MINIMAP_LAG_MS,
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


def record_score(s: dict) -> list[str]:
    from reticle import metrics
    geo = s.get("geometry") or {}
    deps = {"replay_truth": REPLAY_TRUTH_VERSION, "vrfkit": VRFKIT_VERSION,
            "minimap_lag_ms": s["minimap_lag_ms"], "gate_m": rg.GATE_M, "max_gap_ms": MAX_GAP_MS,
            "geometry": geo.get("path"), "shade_fit": geo.get("shade_fit"),
            "stamps": s.get("stamps")}
    T, S, E, F = s["teammates"], s["self"], s["enemies"], s["facing"]
    P, MS = T["pooled"], T["misses"]["pooled"]["shares"]
    ET = E.get("enemy_track") or {}

    def fv(cls, key):
        b = F.get(cls) or {}
        if key in ("median", "p90"):
            return (b.get("err_deg") or {}).get(key)
        return b.get(key)
    v = {"align_offset_ms": round(s["align"]["a_ms"], 1),
         "align_mad_ms": round(s["align"]["residual_mad_ms"], 1),
         "align_matched": s["align"]["matched"],
         "frames_scored": s["frames"]["scored"],
         "frames_outside_spans": s["frames"]["outside_cache_spans"],
         "frames_in_spans_widget_absent": s["frames"]["in_spans_widget_absent"],
         "self_err_px_median": (S["err_px"] or {}).get("median"),
         "self_err_px_p90": (S["err_px"] or {}).get("p90"),
         "self_err_cm_median": (S["err_cm"] or {}).get("median"),
         "self_err_cm_p90": (S["err_cm"] or {}).get("p90"),
         "self_recall": S["recall"], "self_best_lag_ms": S["best_lag_ms"],
         "self_affine_residual_px_median":
             ((S.get("affine_fit_on_self") or {}).get("residual_px") or {}).get("median"),
         "self_baked_err_px_median":
             ((S.get("affine_fit_on_self") or {}).get("baked_transform_err_px") or {}).get("median"),
         "mate_recall": P["recall"], "mate_phantom_share": P["phantom_share"],
         "mate_self_recall": T["self"]["recall"], "mate_ally_recall": T["ally"]["recall"],
         "ally_err_px_median": (P["err_px"] or {}).get("median"),
         "ally_err_px_p90": (P["err_px"] or {}).get("p90"),
         "ally_err_cm_median": (P["err_cm"] or {}).get("median"),
         "mate_within_r_icon": P["within_r_icon"],
         "ally_id_agreement": T["names"]["agreement"],
         "mate_wrong_name_share": T["names"]["wrong_share"],
         "mate_wrong_name_stack_share": T["names"]["wrong_stack_share"],
         **{f"miss_{k}_share": MS[k] for k in MISS_CLASSES},
         "mate_switches_per_min": T["tracks"]["pooled"]["switches_per_truth_minute"],
         "mate_ally_switches_per_min": T["tracks"]["ally"]["switches_per_truth_minute"],
         "mate_fragments_per_life": T["tracks"]["pooled"]["fragments_per_matched_life"],
         "mate_idf1": T["tracks"]["pooled"]["idf1"],
         "mate_self_idf1": T["tracks"]["self"]["idf1"],
         "mate_ally_idf1": T["tracks"]["ally"]["idf1"],
         "enemy_icons": E.get("icons"), "enemy_phantom_share": E.get("phantom_share"),
         "enemy_err_px_median": (E.get("err_px") or {}).get("median"),
         "enemy_track_id_agreement": (ET.get("names") or {}).get("agreement"),
         "enemy_track_id_precision": (ET.get("tracks") or {}).get("id_precision"),
         **{f"facing_{c}_{k}": fv(c, k)
            for c in ("self_team_vision", "ally_ally_icon", "ally_team_vision",
                      "enemy_minimap_object")
            for k in ("median", "p90", "flip_share", "best_lag_ms")}}
    metrics.record("replay_truth", part="score", session=s["session"], values=v, deps=deps)
    return [f"[metric:replay_truth/score@{s['session']}#{key}={val}]" for key, val in v.items()]


# ----------------------------------------------------------------- main

def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Counter):
        return dict(o)
    raise TypeError(type(o))


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
        s = score(args.session, args.geometry)
        ANALYSIS.mkdir(parents=True, exist_ok=True)
        (ANALYSIS / (args.out or f"{args.session}.json")).write_text(
            json.dumps(s, indent=1, default=_default), encoding="utf-8")
        print(json.dumps(s, indent=1, default=_default)[:12000])
        if args.record and "refused" not in s:
            print("\n".join(record_score(s)))
        return 0
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
