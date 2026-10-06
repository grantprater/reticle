r"""VALORANT replay files as external truth for evaluation.

    .\.venv\Scripts\python.exe prototypes\replay_truth.py parse REPLAY.vrf [REPLAY.vrf ...]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py check MATCH [--record]
    .\.venv\Scripts\python.exe prototypes\replay_truth.py score SESSION [--record]
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
`<store>/analysis/replay-truth-20261004/<session>.json`   `score`'s report

The four commands
-----------------
`parse` runs vrfkit (validate, export, spike carrier) at Below Normal priority.

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
cross-check), maps world positions into baked widget pixels through
`riot_ground_truth.MapFrame` (valorant-api's map constants, the geometry's
`shade_fit`), and scores the stored streams of one capture: the self fit
(`ally_icon`), allied observations and their names (`round_entity`), cone
facings (`team_vision`), the spike (`spike`, `spike_carrier`), and enemy
sightings where a stream exists. Each stream reports its error (median and p90,
widget px and world cm), its identity agreement where it names anyone, and its
coverage: the share of the replay's living player-ticks it observes.

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

REPLAY_TRUTH_VERSION = "replay-truth-0.1.0"
STORE = Path.home() / "reticle-store"
REPLAYS = STORE / "external" / "replays"
VRFKIT_DIR = STORE / "tools" / "vrfkit"
VRFKIT_EXE = VRFKIT_DIR / "target" / "release" / "vrfkit.exe"
VRFKIT_VERSION = "0.2.5"
PARSED = REPLAYS / "parsed" / f"vrfkit-{VRFKIT_VERSION}"
ANALYSIS = STORE / "analysis" / "replay-truth-20261004"

#: Hidden or unspawned pawns park here (vrfkit tools/minimap.py: x -50,879..
#: -49,091, z -49,920..-49,785); judged on x and z, since a fall crosses that z.
PARK_X, PARK_Z, PARK_RADIUS = -50000.0, -49900.0, 2000.0
#: The longest gap between two movement samples a position is interpolated
#: across; a wider gap reads as no position (NaN), never a guess.
MAX_GAP_MS = 250.0
#: The stored minimap streams sample at 15 Hz; coverage counts ticks of this grid.
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


def _stats(x, nd=2) -> dict | None:
    """n, median, p90, p95, mean and max of a numeric sample (NaNs dropped)."""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    q = np.percentile(a, [50, 90, 95])
    return {"n": int(a.size), "median": round(float(q[0]), nd), "p90": round(float(q[1]), nd),
            "p95": round(float(q[2]), nd), "mean": round(float(a.mean()), nd),
            "max": round(float(a.max()), nd)}


def _ang_deg(a, b):
    """Absolute angular difference in degrees, elementwise, in [0, 180]."""
    d = np.mod(np.asarray(a, float) - np.asarray(b, float), 360.0)
    return np.minimum(d, 360.0 - d)


def _ang_rad(a, b):
    d = np.mod(np.asarray(a, float) - np.asarray(b, float), 2 * math.pi)
    return np.minimum(d, 2 * math.pi - d)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parsed_dir(match: str) -> Path:
    return PARSED / match


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

class Replay:
    """One vrfkit export as numpy arrays: per-player tracks and the event list.

    `players[subject]` holds `t` (replay ms), `x`, `y`, `z` (cm) and `yaw`
    (degrees) over every pawn the player owned, sorted by time, park-slot rows
    removed. `events` holds the server's event list with killer and victim
    resolved to subjects through `character_net_guids`.
    """

    def __init__(self, match: str):
        import pyarrow.parquet as pq

        self.match = match
        self.dir = parsed_dir(match)
        ex = self.dir / "export"
        self.manifest = json.loads((ex / "manifest.json").read_text(encoding="utf-8"))
        self.guid_subject = {}
        self.subjects = []
        for p in self.manifest.get("players") or []:
            s = p.get("subject")
            if not s:
                continue
            self.subjects.append(s)
            for g in (p.get("character_net_guids") or [p.get("character_net_guid")]):
                if g:
                    self.guid_subject[int(g)] = s
        mv = pq.read_table(ex / "movement.parquet",
                           columns=["time_ms", "character_net_guid", "pos_x", "pos_y", "pos_z",
                                    "yaw", "pitch", "timestamp"])
        g = mv["character_net_guid"].to_numpy().astype(np.int64)
        t = mv["time_ms"].to_numpy().astype(np.float64)
        x = mv["pos_x"].to_numpy().astype(np.float64)
        y = mv["pos_y"].to_numpy().astype(np.float64)
        z = mv["pos_z"].to_numpy().astype(np.float64)
        yaw = mv["yaw"].to_numpy().astype(np.float64)
        self.movement_rows = int(t.size)
        park = (np.abs(x - PARK_X) <= PARK_RADIUS) & (np.abs(z - PARK_Z) <= PARK_RADIUS)
        self.park_rows = int(park.sum())
        self.raw = {"g": g, "t": t, "x": x, "y": y, "z": z, "park": park}
        self.players = {}
        for s in self.subjects:
            gs = [k for k, v in self.guid_subject.items() if v == s]
            m = np.isin(g, gs) & ~park
            o = np.argsort(t[m], kind="stable")
            self.players[s] = {"t": t[m][o], "x": x[m][o], "y": y[m][o], "z": z[m][o],
                               "yaw": yaw[m][o]}
        self.unjoined_rows = int((~np.isin(g, list(self.guid_subject))).sum())
        ev = pq.read_table(ex / "events.parquet").to_pylist()
        self.events = []
        for r in ev:
            e = {"group": r.get("group"), "t": float(r.get("time1") or 0.0),
                 "metadata": r.get("metadata"), "word0": r.get("word0"), "word1": r.get("word1")}
            if e["group"] == "characterDeath":
                e["killer"] = self.guid_subject.get(r.get("word0"))
                e["victim"] = self.guid_subject.get(r.get("word1"))
            self.events.append(e)
        self.events.sort(key=lambda e: e["t"])
        self.duration_ms = float(self.manifest.get("duration_ms") or
                                 max(e["t"] for e in self.events))

    # -- events
    def group(self, name: str) -> list[dict]:
        return [e for e in self.events if e["group"] == name]

    def round_starts(self) -> np.ndarray:
        return np.array([e["t"] for e in self.group("roundStarted")], float)

    def map_url(self) -> str | None:
        for k in ("level_names_and_times", "levelNamesAndTimes"):
            v = self.manifest.get(k) or (self.manifest.get("replay_info") or {}).get(k)
            if v:
                return v[0]["name"] if isinstance(v[0], dict) else v[0]
        hdr = self.manifest.get("header") or {}
        for k in ("level_names_and_times", "levelNamesAndTimes"):
            if hdr.get(k):
                v = hdr[k]
                return v[0]["name"] if isinstance(v[0], dict) else v[0]
        return None

    def loadouts(self) -> dict:
        """subject -> characterId, from the header's playerLoadouts JSON."""
        gsd = self.manifest.get("game_specific_data")
        if gsd is None:
            gsd = (self.manifest.get("header") or {}).get("game_specific_data")
        out = {}

        def walk(o):
            if isinstance(o, str):
                try:
                    walk(json.loads(o))
                except ValueError:
                    pass
            elif isinstance(o, dict):
                if "subject" in o and "characterId" in o:
                    out[o["subject"]] = o["characterId"]
                elif "Subject" in o and "CharacterID" in o:
                    out[o["Subject"]] = o["CharacterID"]
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(gsd)
        return out

    # -- positions
    def sample(self, s: str, t) -> dict:
        """Position and yaw of player `s` at replay times `t` (vectorised).

        Linear between the bracketing samples when both lie within
        `MAX_GAP_MS` of each other; NaN otherwise. Yaw comes from the nearer
        sample (an angle is not interpolated across a wrap)."""
        P = self.players[s]
        t = np.atleast_1d(np.asarray(t, float))
        n = P["t"].size
        out = {k: np.full(t.shape, np.nan) for k in ("x", "y", "z", "yaw")}
        if n < 2:
            return out
        i = np.clip(np.searchsorted(P["t"], t, side="right"), 1, n - 1)
        t0, t1 = P["t"][i - 1], P["t"][i]
        ok = (t >= t0) & (t <= t1) & ((t1 - t0) <= MAX_GAP_MS)
        span = np.where(t1 > t0, t1 - t0, 1.0)
        w = np.clip((t - t0) / span, 0.0, 1.0)
        for k in ("x", "y", "z"):
            v = P[k][i - 1] * (1 - w) + P[k][i] * w
            out[k] = np.where(ok, v, np.nan)
        near = np.where(w < 0.5, i - 1, i)
        out["yaw"] = np.where(ok, P["yaw"][near], np.nan)
        return out

    def alive(self, s: str, t) -> np.ndarray:
        """True where `s` is alive by the event list: after a round start and
        before that round's death of `s` (a revive is not modelled)."""
        t = np.atleast_1d(np.asarray(t, float))
        rs = self.round_starts()
        if rs.size == 0:
            return np.zeros(t.shape, bool)
        r_idx = np.searchsorted(rs, t, side="right") - 1
        alive = r_idx >= 0
        deaths = np.array([e["t"] for e in self.group("characterDeath") if e.get("victim") == s])
        if deaths.size:
            d_round = np.searchsorted(rs, deaths, side="right") - 1
            # earliest death per round
            first = {}
            for r, dt in zip(d_round, deaths):
                first[int(r)] = min(first.get(int(r), np.inf), float(dt))
            fd = np.array([first.get(int(r), np.inf) for r in range(rs.size)])
            alive &= ~(t >= fd[np.clip(r_idx, 0, rs.size - 1)])
        return alive


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

def _frames_to_replay(t_cap, a_ms: float, lag_ms: float):
    """Capture ms of a stored minimap frame -> the replay ms it shows."""
    return np.asarray(t_cap, float) - a_ms - lag_ms


def to_px(mf, x, y):
    """`MapFrame.to_px`, vectorised over arrays: same constants, same affine."""
    u, v = rg.game_to_uv(np.asarray(x, float), np.asarray(y, float), mf.m, mf.swap)
    h0, w0 = mf.art_hw
    ax = u * w0 - 0.5 - mf.crop[0]
    ay = v * h0 - 0.5 - mf.crop[1]
    A = mf.aff
    return A[0][0] * ax + A[0][1] * ay + A[0][2], A[1][0] * ax + A[1][1] * ay + A[1][2]


def facing_px_deg(mf, x, y, yaw_deg):
    """A world yaw as image degrees (y down), `MapFrame.facing_deg` vectorised."""
    th = np.radians(yaw_deg)
    x0, y0 = to_px(mf, x, y)
    x1, y1 = to_px(mf, x + 100.0 * np.cos(th), y + 100.0 * np.sin(th))
    return np.mod(np.degrees(np.arctan2(y1 - y0, x1 - x0)), 360.0)


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


def session_context(sid: str) -> dict:
    """What every scorer of one capture needs, built once from STORED events.

    The replay, the player and teams (Riot's record), the agents
    (playerLoadouts), the replay-to-capture offset `a` fitted on replay kills
    against the stored deaths, the stored rounds and the baked `MapFrame`.
    `ctx["out"]` is the report's head; a refusal sets `ctx["out"]["refused"]`
    and leaves the later keys out. `score` and `replay_abilities` both use it.
    """
    from reticle.store import Store

    store = Store(STORE)
    man = store.read_manifest(sid)
    recs = rg.riot_records(STORE)
    d = recs.get(sid)
    rep = json.loads((REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    entry = next((f for f in rep["files"] if f.get("capture_session") == sid), None)
    if entry is None:
        return {"out": {"session": sid, "refused": "no_replay_for_session"}}
    match = Path(entry["file"]).stem
    rp = Replay(match)
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    out = {"session": sid, "capture": man["source"]["path"], "profile": man["source_profile"],
           "replay_truth_version": REPLAY_TRUTH_VERSION, "vrfkit": VRFKIT_VERSION,
           "minimap_lag_ms": rg.MINIMAP_LAG_MS}
    # who is the player, and the teams: Riot's record (external, like the replay)
    ident = rg.identify_player(recs, STORE).get(sid, {}) if d else {}
    me = ident.get("subject")
    team = {p["subject"]: p["teamId"] for p in d["match"]["players"]} if d else {}
    out["player_basis"] = ident.get("basis")
    out["team_source"] = "riot_record" if d else None
    if me is None or not team:
        out["refused"] = "no_player_or_team"
        return {"out": out}
    allies = [s for s in rp.subjects if team.get(s) == team[me]]
    foes = [s for s in rp.subjects if s in team and team[s] != team[me]]
    agent = {s: ref.agent(c) for s, c in rp.loadouts().items()}
    out["allies"] = [agent.get(s) for s in allies]

    # -- alignment: replay kills against stored deaths (killfeed first sample)
    deaths = rg.stored_deaths(STORE, sid)
    kill_like, _second = rg.split_deaths(deaths)
    st = [float(r["t_ms"]) for r in kill_like]
    rk = [e["t"] for e in rp.group("characterDeath")]
    al = rg.fit_alignment(rk, st)
    a = al["a_ms"]
    out["align"] = {k: v for k, v in al.items() if k != "pairs"}
    # the independent cross-check: stored round starts against roundStarted
    date = man["ingested_at"][:10]
    rounds = store.read_rounds(sid, date).to_pylist() if store.rounds_path(sid, date).exists() else []
    rs = rp.round_starts()
    if rounds and rs.size:
        t0 = np.array([r["t_start_ms"] for r in rounds], float)
        cand = rs + a
        dd = t0[:, None] - cand[None, :]
        j = np.argmin(np.abs(dd), axis=1)
        diff = dd[np.arange(t0.size), j]
        out["align"]["stored_round_start_minus_replay_ms"] = _stats(diff, 1)
        out["align"]["stored_round_start_rows"] = [
            {"round_no": r["round_no"], "source": r["start_source"], "diff_ms": round(float(x), 1)}
            for r, x in zip(rounds, diff)]
        src = np.array([r["start_source"] for r in rounds])
        out["align"]["stored_round_start_by_source"] = {
            k: {**_stats(diff[src == k], 1), "within_1s": int(np.sum(np.abs(diff[src == k]) <= 1000))}
            for k in sorted(set(src))}
        pl = np.array([e["t"] for e in rp.group("spikePlanted")]) + a
        sp = np.array([r["plant_t_ms"] for r in rounds if r.get("plant_t_ms")], float)
        if pl.size and sp.size:
            dp = sp[:, None] - pl[None, :]
            jp = np.argmin(np.abs(dp), axis=1)
            out["align"]["stored_plant_minus_replay_ms"] = _stats(dp[np.arange(sp.size), jp], 1)

    mf, why = rg.map_frame_for(sid, man, ref, {"match": {"matchInfo": {"mapId": rp.map_url()}}},
                               STORE)
    if mf is None:
        out["refused"] = f"map_frame:{why}"
        return {"out": out}
    # the vectorised transform must reproduce MapFrame.to_px
    probe = [(0.0, 0.0), (1234.0, -5678.0), (-4000.0, 3000.0)]
    vx, vy = to_px(mf, [p[0] for p in probe], [p[1] for p in probe])
    assert max(math.hypot(vx[i] - mf.to_px(*p)[0], vy[i] - mf.to_px(*p)[1])
               for i, p in enumerate(probe)) < 1e-6
    cm_per_px = 1.0 / mf.px_per_unit
    gate = rg.GATE_M * 100.0 * mf.px_per_unit
    H, W = mf.widget_shape
    out["px_per_m"] = round(mf.px_per_unit * 100.0, 3)
    out["gate_px"] = round(gate, 2)
    out["widget"] = [int(W), int(H)]
    return {"out": out, "store": store, "man": man, "rp": rp, "ref": ref, "me": me,
            "team": team, "allies": allies, "foes": foes, "agent": agent, "a": a,
            "rounds": rounds, "rs": rs, "mf": mf, "cm_per_px": cm_per_px, "gate": gate}


def score(sid: str) -> dict:
    ctx = session_context(sid)
    out = ctx["out"]
    if "refused" in out:
        return out
    rp, mf, a, me, team = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"], ctx["team"]
    allies, foes, agent, rs = ctx["allies"], ctx["foes"], ctx["agent"], ctx["rs"]
    cm_per_px, gate = ctx["cm_per_px"], ctx["gate"]
    H, W = mf.widget_shape

    def truth_at(subs, t_rep):
        """(n, k) px arrays and alive mask for subjects `subs` at replay times."""
        n, k = t_rep.size, len(subs)
        X, Y = np.full((n, k), np.nan), np.full((n, k), np.nan)
        YAW = np.full((n, k), np.nan)
        for c, s in enumerate(subs):
            q = rp.sample(s, t_rep)
            live = rp.alive(s, t_rep)
            px, py = to_px(mf, q["x"], q["y"])
            X[:, c] = np.where(live, px, np.nan)
            Y[:, c] = np.where(live, py, np.nan)
            YAW[:, c] = np.where(live, facing_px_deg(mf, q["x"], q["y"], q["yaw"]), np.nan)
        return X, Y, YAW

    # replay grid of living ally ticks, for coverage
    rs0 = rs[0] if rs.size else 0.0
    grid = np.arange(rs0, rp.duration_ms, 1000.0 / GRID_HZ)
    live_grid = np.stack([rp.alive(s, grid) & np.isfinite(rp.sample(s, grid)["x"])
                          for s in allies], axis=1)
    out["coverage_denominator"] = {"ally_living_ticks": int(live_grid.sum()),
                                   "ally_living_seconds": round(live_grid.sum() / GRID_HZ, 1),
                                   "self_living_seconds":
                                       round(live_grid[:, allies.index(me)].sum() / GRID_HZ, 1)}

    def tick_of(t_rep):
        return np.rint((np.asarray(t_rep) - rs0) * GRID_HZ / 1000.0).astype(np.int64)

    # -- self (ally_icon's self fit)
    fr_t, fr_x, fr_y, fr_id, fr_drawn = [], [], [], [], []
    for r in _rows(STORE / "events" / "ally_icon" / f"{sid}.jsonl", '"kind":"frame"'):
        fr_id.append(r["frame_idx"])
        fr_t.append(r["t_ms"])
        fr_drawn.append(bool(r.get("widget_drawn")))
        s_ = r.get("self")
        fr_x.append(s_[0] if s_ else np.nan)
        fr_y.append(s_[1] if s_ else np.nan)
    fr_t, fr_x, fr_y = np.array(fr_t), np.array(fr_x), np.array(fr_y)
    fr_drawn = np.array(fr_drawn)
    t_rep = _frames_to_replay(fr_t, a, rg.MINIMAP_LAG_MS)
    q = rp.sample(me, t_rep)
    me_live = rp.alive(me, t_rep) & np.isfinite(q["x"])
    sx, sy = to_px(mf, q["x"], q["y"])
    has = np.isfinite(fr_x) & fr_drawn
    e_self = np.hypot(sx - fr_x, sy - fr_y)
    m_ = has & me_live
    selfo = {"frames": int(fr_t.size), "frames_drawn": int(fr_drawn.sum()),
             "self_fits": int(has.sum()), "self_fits_player_alive": int(m_.sum()),
             "self_fits_player_dead": int((has & ~me_live).sum()),
             "err_px": _stats(e_self[m_]), "err_cm": _stats(e_self[m_] * cm_per_px, 0),
             "beyond_gate": int(np.sum(e_self[m_] > gate))}
    # a self fit beyond the gate: does it sit on another living ally instead?
    far = m_ & (e_self > gate)
    if far.any():
        others = [s for s in allies if s != me]
        Xo, Yo, _ = truth_at(others, t_rep[far])
        dn = np.nanmin(np.where(np.isfinite(Xo), np.hypot(Xo - fr_x[far][:, None],
                                                          Yo - fr_y[far][:, None]), np.inf), axis=1)
        selfo["beyond_gate_on_other_ally"] = int(np.sum(dn <= gate))
    drawn_alive = fr_drawn & me_live
    selfo["fit_share_while_alive_and_drawn"] = round(float(np.sum(m_ & (e_self <= gate))
                                                           / max(1, drawn_alive.sum())), 4)
    c_me = allies.index(me)
    sc = tick_of(t_rep[m_][e_self[m_] <= gate])
    sc = sc[(sc >= 0) & (sc < grid.size)]
    sc = sc[live_grid[sc, c_me]]
    selfo["coverage"] = round(np.unique(sc).size / max(1, int(live_grid[:, c_me].sum())), 4)
    # lag scan on the self fit: is the -450 ms minimap lag right for this capture?
    scan = {}
    for L in np.arange(-1000.0, 501.0, 50.0):
        tr = _frames_to_replay(fr_t[m_], a, L)
        qq = rp.sample(me, tr)
        px, py = to_px(mf, qq["x"], qq["y"])
        scan[int(L)] = round(float(np.nanmedian(np.hypot(px - fr_x[m_], py - fr_y[m_]))), 3)
    selfo["lag_scan_median_px"] = scan
    selfo["best_lag_ms"] = min(scan, key=scan.get)
    # world -> px: an affine fitted on the self points, against the baked transform
    w = m_ & (e_self <= gate)
    if w.sum() > 20:
        A = np.column_stack([q["x"][w], q["y"][w], np.ones(w.sum())])
        cx, *_ = np.linalg.lstsq(A, fr_x[w], rcond=None)
        cy, *_ = np.linalg.lstsq(A, fr_y[w], rcond=None)
        res = np.hypot(A @ cx - fr_x[w], A @ cy - fr_y[w])
        selfo["affine_fit_on_self"] = {"n": int(w.sum()), "residual_px": _stats(res),
                                       "baked_transform_err_px": _stats(e_self[w]),
                                       "coef_x": [round(float(c), 6) for c in cx],
                                       "coef_y": [round(float(c), 6) for c in cy]}
    out["self"] = selfo

    # -- allies (round_entity observations, family ally/self)
    ents = {}
    o_t, o_f, o_x, o_y, o_e = [], [], [], [], []
    for r in _rows(STORE / "events" / "round_entity" / f"{sid}.jsonl"):
        k = r.get("kind")
        if k == "entity":
            ents[r["id"]] = r
        elif k == "observation" and r.get("family") in ("ally", "self"):
            o_t.append(r["t_ms"])
            o_f.append(r["frame_idx"])
            o_x.append(r["x"])
            o_y.append(r["y"])
            o_e.append(r.get("entity_id"))
    o_t, o_f, o_x, o_y = map(np.array, (o_t, o_f, o_x, o_y))
    t_rep = _frames_to_replay(o_t, a, rg.MINIMAP_LAG_MS)
    X, Y, _ = truth_at(allies, t_rep)
    D = np.hypot(X - o_x[:, None], Y - o_y[:, None])
    j, dist = _assign(o_f, D, gate)
    hit = j >= 0
    got = np.array([(ents.get(e) or {}).get("agent") for e in o_e], dtype=object)
    truth_agent = np.array([agent.get(allies[c]) if c >= 0 else None for c in j], dtype=object)
    named = hit & np.array([g is not None for g in got])
    right = named & np.array([rg.canon(g) == rg.canon(t) for g, t in zip(got, truth_agent)])
    wrong_pairs = Counter((t, g) for t, g, n, r_ in zip(truth_agent, got, named, right)
                          if n and not r_)
    # truth allies per observed frame: matched, missed (stacked/outside), phantom
    fu, inv = np.unique(o_f, return_index=True)
    Xf, Yf, _ = truth_at(allies, t_rep[inv])
    truth_n = int(np.isfinite(Xf).sum())
    inside = np.isfinite(Xf) & (Xf >= 0) & (Xf < W) & (Yf >= 0) & (Yf < H)
    cov_t = tick_of(t_rep[hit])
    okc = (cov_t >= 0) & (cov_t < grid.size)
    lv = live_grid[cov_t[okc], j[hit][okc]]
    covered = np.unique(cov_t[okc][lv] * 16 + j[hit][okc][lv]).size
    out["allies_round_entity"] = {
        "observations": int(o_t.size), "frames": int(fu.size), "truth_allies_in_frames": truth_n,
        "truth_outside_widget": int((np.isfinite(Xf) & ~inside).sum()),
        "matched": int(hit.sum()), "phantom": int((~hit).sum()),
        "missed_in_frames": truth_n - int(hit.sum()),
        "err_px": _stats(dist[hit]), "err_cm": _stats(dist[hit] * cm_per_px, 0),
        "identity": {"named": int(named.sum()), "right": int(right.sum()),
                     "wrong": int((named & ~right).sum()), "refused": int((hit & ~named).sum()),
                     "agreement": round(float(right.sum() / max(1, named.sum())), 4),
                     "wrong_pairs_truth_got": [[t, g, n] for (t, g), n in wrong_pairs.most_common(12)]},
        "coverage": round(covered / max(1, int(live_grid.sum())), 4),
        "coverage_ticks": covered,
        # the stream reads only its cached spans; within the frames it read:
        "matched_share_of_truth_in_frames": round(float(hit.sum() / max(1, truth_n)), 4)}

    # -- facing (team_vision icons with a facing, self and allies)
    v_t, v_f, v_x, v_y, v_fac, v_role = [], [], [], [], [], []
    for r in _rows(STORE / "events" / "team_vision" / f"{sid}.jsonl", '"kind":"frame"'):
        for ic in r.get("icons") or []:
            if ic.get("role") not in ("ally", "self") or ic.get("facing") is None:
                continue
            v_t.append(r["t_ms"])
            v_f.append(r["frame_idx"])
            v_x.append(ic["x"])
            v_y.append(ic["y"])
            v_fac.append(ic["facing"])
            v_role.append(ic["role"])
    v_t, v_f, v_x, v_y, v_fac = map(np.array, (v_t, v_f, v_x, v_y, v_fac))
    v_role = np.array(v_role)
    if v_t.size:
        t_rep = _frames_to_replay(v_t, a, rg.MINIMAP_LAG_MS)
        X, Y, YAW = truth_at(allies, t_rep)
        D = np.hypot(X - v_x[:, None], Y - v_y[:, None])
        j, dist = _assign(v_f, D, gate)
        hit = j >= 0
        fe = _ang_deg(YAW[np.arange(j.size), np.clip(j, 0, None)], v_fac)
        fe = np.where(hit, fe, np.nan)
        cov_t = tick_of(t_rep[hit])
        okc = (cov_t >= 0) & (cov_t < grid.size)
        lv = live_grid[cov_t[okc], j[hit][okc]]
        out["facing_team_vision"] = {
            "icons_with_facing": int(v_t.size), "matched": int(hit.sum()),
            "err_deg": _stats(fe), "within_30deg": round(float(np.nanmean(fe[hit] <= 30)), 4),
            "self_err_deg": _stats(fe[hit & (v_role == "self")]),
            "ally_err_deg": _stats(fe[hit & (v_role == "ally")]),
            "pos_err_px": _stats(dist[hit]),
            "coverage": round(np.unique(cov_t[okc][lv] * 16 + j[hit][okc][lv]).size
                              / max(1, int(live_grid.sum())), 4)}

    # -- enemies: a stored enemy stream, if this session has one
    enemy_paths = [STORE / "events" / s / f"{sid}.jsonl" for s in ("minimap_object", "enemy_track")]
    if not any(p.is_file() for p in enemy_paths):
        foe_ticks = sum(int((rp.alive(s, grid) & np.isfinite(rp.sample(s, grid)["x"])).sum())
                        for s in foes)
        out["enemies"] = {"refused": "no_stored_enemy_stream (minimap_object, enemy_track)",
                          "coverage": 0.0, "enemy_living_seconds": round(foe_ticks / GRID_HZ, 1)}
    else:
        out["enemies"] = score_enemies(sid, rp, mf, a, foes, grid, gate, cm_per_px)

    # -- spike: the HUD marker and the minimap glyph against the replay's carrier
    out["spike"] = score_spike(sid, rp, mf, a, allies, foes, team, me)
    out["agents"] = None   # never written: subjects stay in the store
    return out


def score_enemies(sid, rp, mf, a, foes, grid, gate, cm_per_px) -> dict:
    """Stored enemy icons (minimap_object frames) against the replay's foes."""
    e_t, e_f, e_x, e_y = [], [], [], []
    for r in _rows(STORE / "events" / "minimap_object" / f"{sid}.jsonl", '"kind":"frame"'):
        if r.get("reason") is not None:
            continue
        for e in r.get("enemies") or []:
            e_t.append(r["t_ms"])
            e_f.append(r["frame_idx"])
            e_x.append(e["x"])
            e_y.append(e["y"])
    if not e_t:
        return {"refused": "no_enemy_rows", "coverage": 0.0}
    e_t, e_f, e_x, e_y = map(np.array, (e_t, e_f, e_x, e_y))
    t_rep = _frames_to_replay(e_t, a, rg.MINIMAP_LAG_MS)
    X = np.full((t_rep.size, len(foes)), np.nan)
    Y = X.copy()
    for c, s in enumerate(foes):
        q = rp.sample(s, t_rep)
        px, py = to_px(mf, q["x"], q["y"])
        live = rp.alive(s, t_rep)
        X[:, c], Y[:, c] = np.where(live, px, np.nan), np.where(live, py, np.nan)
    j, dist = _assign(e_f, np.hypot(X - e_x[:, None], Y - e_y[:, None]), gate)
    hit = j >= 0
    return {"icons": int(e_t.size), "matched": int(hit.sum()), "unmatched": int((~hit).sum()),
            "err_px": _stats(dist[hit]), "err_cm": _stats(dist[hit] * cm_per_px, 0)}


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
    deps = {"replay_truth": REPLAY_TRUTH_VERSION, "vrfkit": VRFKIT_VERSION,
            "minimap_lag_ms": s["minimap_lag_ms"], "gate_m": rg.GATE_M, "max_gap_ms": MAX_GAP_MS}
    A, S = s["allies_round_entity"], s["self"]
    F = s.get("facing_team_vision") or {}
    v = {"align_offset_ms": round(s["align"]["a_ms"], 1),
         "align_mad_ms": round(s["align"]["residual_mad_ms"], 1),
         "align_matched": s["align"]["matched"],
         "self_err_px_median": S["err_px"]["median"], "self_err_px_p90": S["err_px"]["p90"],
         "self_err_cm_median": S["err_cm"]["median"], "self_err_cm_p90": S["err_cm"]["p90"],
         "self_coverage": S["coverage"], "self_best_lag_ms": S["best_lag_ms"],
         "ally_err_px_median": A["err_px"]["median"], "ally_err_px_p90": A["err_px"]["p90"],
         "ally_err_cm_median": A["err_cm"]["median"], "ally_err_cm_p90": A["err_cm"]["p90"],
         "ally_matched": A["matched"], "ally_phantom": A["phantom"],
         "ally_id_right": A["identity"]["right"], "ally_id_wrong": A["identity"]["wrong"],
         "ally_id_refused": A["identity"]["refused"], "ally_id_agreement": A["identity"]["agreement"],
         "ally_coverage": A["coverage"],
         "facing_err_deg_median": (F.get("err_deg") or {}).get("median"),
         "facing_err_deg_p90": (F.get("err_deg") or {}).get("p90"),
         "facing_coverage": F.get("coverage"),
         "enemy_coverage": s["enemies"].get("coverage")}
    metrics.record("replay_truth", part="score", session=s["session"], values=v, deps=deps)
    return [f"[metric:replay_truth/score#{key}={val}]" for key, val in v.items()]


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
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("survey")
    p.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
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
        s = score(args.session)
        ANALYSIS.mkdir(parents=True, exist_ok=True)
        (ANALYSIS / f"{args.session}.json").write_text(json.dumps(s, indent=1, default=_default),
                                                      encoding="utf-8")
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
