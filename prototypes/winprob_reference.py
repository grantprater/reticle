r"""Round win probability: one recorded reference fit on Riot's match records.

    .\.venv\Scripts\python.exe prototypes\winprob_reference.py [--record] [--out DIR] [--boot N]
    .\.venv\Scripts\python.exe prototypes\winprob_reference.py --no-store   # Riot-only parts

Why this exists
---------------
Five research lenses fitted round win probability as scratch work and judged
position, plant and clock fidelity from linear fits at kill instants. Nothing
recorded those fits. This file is the single reference: it fits the model
ladder on Riot's records (`<store>/external/riot/*.json`, read through
`prototypes/riot_ground_truth.py`), validates by leaving one match out, and
writes every number to `<out>/results.json` and, with `--record`, to the
metrics log. It decodes nothing and reads no reader; the observed-state part
reads stored streams (`roster`, `hud`, the round table, `round_entity`) and
asks their owners (`roster.resolve`, `menu.stored_menu`).

Rounds admitted
---------------
Every round of the 22 records except: surrendered rounds (no play), rounds
in which Riot flags a player `wasAfk` or `wasPenalized`, rounds with a player
absent from the first kill's living set, and rounds whose event simulation
names a winner Riot does not. Overtime and the unrated matches stay in; the
sensitivity block refits without them.

The event simulation
--------------------
Kills in `roundTime` order update each side's living set; a subject Riot lists
among the living after its own earlier death was revived. Before a plant a
side with nobody alive loses; after it only the defenders' wipe ends the
round. A plant counts if it lands before the decision. The round timer
(`gametime.ROUND_LIVE_CLOCK_MS`) ends an unplanted round for the defenders,
the fuse (`gametime.SPIKE_FUSE_MS`) a planted one for the attackers, and a
defuse for the defenders. The 7 s defuse and its 3.5 s half are no domain
fact; they enter only as post-plant features.

States
------
K: just after each kill that neither decides the round nor follows its
decision (simultaneous kills collapse to one state). G: a 1 s grid from
`roundTime` 0 to the decision. F: a 0.1 s grid, for the alive-lag test only.
Each round weighs 1, shared equally among its states.

Models
------
Ridge logistic regressions in the attacker's frame: P(attackers win). Alive
features are antisymmetric (a-d, (a-d)/(a+d)), so a model without the side
column predicts 0.5 at equal counts; `side` is the attacker intercept and
`mapside` a per-map shrunk deviation from it. The phase model fits pre-plant
and post-plant states separately, each with its own clock features. The
gambler's-ruin baseline is a/(a+d), clipped to [0.01, 0.99], fitted to
nothing.

Positions
---------
At K, Riot's `playerLocations` give both teams. On G only reticle's own ally
positions exist (`round_entity`, families ally and self), placed in game
units through `riot_ground_truth.MapFrame` and timed through its
`fit_alignment` plus `MINIMAP_LAG_MS`. Features are coarse: allies within
`NEAR_CM` of a site (or of the planted spike), their mean distance to it, and
allies farther than `ISOLATED_CM` from every other ally. Site centres are
valorant-api's callouts, independent of the match data.

Post hoc parts
--------------
Written after the predicted run, and flagged `post_hoc` in the results:
X1 (the phase split without clocks) and X2 (one model with the plant flag
and phase-masked clocks), asked once the phase model lost to the flag; the
endgame subsets (last 10 s of the fuse, last 20 s of the round); K0 (kill
states plus each round's opening state), to reconcile with the earlier
lenses' figures; and `frame` positions, after `window` positions counted a
re-identified track twice (30% of captured instants held more ally entities
than Riot's living allies).

Observed states
---------------
The same model, fitted on Riot states, is scored on the captured matches'
G instants twice: with Riot's inputs and with reticle's (alive from
`roster.resolve` with the menu witness, plant from the stored round table,
clock from the HUD), as-of joins no older than `ASOF_MS`. Side stays Riot's;
reticle has no loadout, so the observed model carries none.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import riot_ground_truth as rgt  # noqa: E402
from reticle.gametime import ROUND_LIVE_CLOCK_MS, SPIKE_FUSE_MS  # noqa: E402

VERSION = "winprob-reference-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
#: External, no domain fact: full defuse and the half checkpoint.
DEFUSE_MS = 7000.0
HALF_DEFUSE_MS = 3500.0
RIDGE = 1.0
SIDE_PEN = 0.01
NEAR_CM = 2000.0
ISOLATED_CM = 3000.0
#: Position observation window around a grid instant, and as-of staleness.
POS_TOL_MS = 500.0
FRAME_TOL_MS = 250.0
ASOF_MS = 1500.0
LAGS_S = (0.25, 0.5, 1.0, 2.0, 5.0)
LN2 = math.log(2.0)


# ----------------------------------------------------------------- rounds

def site_centres(ref: rgt.Reference) -> dict[str, dict[str, tuple[float, float]]]:
    out = {}
    for url, m in ref.maps.items():
        s = {c["superRegionName"]: (c["location"]["x"], c["location"]["y"])
             for c in (m.get("callouts") or []) if c.get("regionName") == "Site"}
        if s:
            out[url] = s
    return out


def simulate(kills, plant, defuse, att, team_of):
    """(decision, kill states, notes) for one round's events."""
    alive = set(team_of)
    dead_at = {}
    events = [(k["roundTime"], 0, "kill", k) for k in kills]
    if plant is not None:
        events.append((plant, 1, "plant", None))
    if defuse is not None:
        events.append((defuse, 2, "defuse", None))
    events.sort(key=lambda e: (e[0], e[1]))
    decided, planted_at = None, None
    kstates, notes = [], Counter()

    def counts():
        a = sum(1 for s in alive if team_of[s] == att)
        return a, len(alive) - a

    for t, _o, kind, k in events:
        if decided is None:
            if planted_at is None and t > ROUND_LIVE_CLOCK_MS:
                decided = (float(ROUND_LIVE_CLOCK_MS), False, "timeout")
            elif planted_at is not None and t > planted_at + SPIKE_FUSE_MS:
                decided = (planted_at + SPIKE_FUSE_MS, True, "detonation")
        if decided is not None:
            notes[f"after_decision_{kind}"] += 1
            continue
        if kind == "kill":
            v = k["victim"]
            alive.discard(v)
            dead_at.setdefault(v, t)
            listed = {p["subject"] for p in k.get("playerLocations") or ()}
            for s in listed - alive - {v}:
                if s in dead_at and dead_at[s] < t - 500:
                    alive.add(s)
                    del dead_at[s]
                    notes["revived"] += 1
            a, d = counts()
            dec = None
            if planted_at is None and a == 0:
                dec = (float(t), False, "elimination")
            elif d == 0:
                dec = (float(t), True, "elimination")
            kstates.append({"t": float(t), "a": a, "d": d, "alive": set(alive),
                            "planted": planted_at is not None, "deciding": dec is not None,
                            "locs": k.get("playerLocations") or []})
            decided = dec
        elif kind == "plant":
            planted_at = float(t)
        else:
            decided = (float(t), False, "defuse")
    if decided is None:
        decided = ((planted_at + SPIKE_FUSE_MS, True, "detonation") if planted_at is not None
                   else (float(ROUND_LIVE_CLOCK_MS), False, "timeout"))
    return decided, planted_at, kstates, notes


def match_rounds(sid: str, d: dict, ref, sites) -> tuple[list[dict], Counter]:
    m = d["match"]
    mi = m["matchInfo"]
    team_of = {p["subject"]: p["teamId"] for p in m["players"]}
    kills_by = defaultdict(list)
    for k in m["kills"]:
        kills_by[k["round"]].append(k)
    out, why = [], Counter()
    for r in sorted(m["roundResults"], key=lambda r: r["roundNum"]):
        n = r["roundNum"]
        rec = {"sid": sid, "map": mi["mapId"].rsplit("/", 1)[-1], "map_url": mi["mapId"],
               "round": n, "ot": n >= 24, "unrated": mi["queueID"] != "competitive",
               "result": r.get("roundResultCode")}
        if r.get("roundResultCode") == "Surrendered":
            why["surrendered"] += 1
            continue
        teams = sorted(set(team_of.values()))
        win = r["winningTeam"]
        att = win if r["winningTeamRole"] == "Attacker" else next(t for t in teams if t != win)
        rec["att_team"], rec["y"] = att, int(win == att)
        if any(p.get("wasAfk") or p.get("wasPenalized") for p in r["playerStats"]):
            why["afk_or_penalized"] += 1
            continue
        kills = sorted(kills_by[n], key=lambda k: (k["roundTime"], k["gameTime"]))
        if kills:
            listed = {p["subject"] for p in kills[0].get("playerLocations") or ()}
            if not listed:
                why["note_first_kill_lists_nobody"] += 1
            elif set(team_of) - listed - {kills[0]["victim"]}:
                why["absent_player"] += 1
                continue
        plant = r.get("plantRoundTime") if r.get("bombPlanter") else None
        defuse = r.get("defuseRoundTime") if r.get("bombDefuser") else None
        side_of = {s: (1 if t == att else 0) for s, t in team_of.items()}
        dec, planted_at, kst, notes = simulate(kills, plant, defuse, att,
                                               {s: t for s, t in team_of.items()})
        why.update({f"note_{k}": v for k, v in notes.items()})
        if bool(dec[1]) != bool(rec["y"]):
            why["simulation_disagrees"] += 1
            rec["sim_disagrees"] = {"sim": dec, "riot": r.get("roundResultCode")}
            out.append(rec | {"admitted": False})
            continue
        if plant is not None and planted_at is None:
            why["plant_after_decision"] += 1
        econ = {e["subject"]: float(e.get("loadoutValue") or 0.0)
                for e in r.get("playerEconomies") or ()}
        rstart = statistics.median(k["gameTime"] - k["roundTime"] for k in kills) if kills else None
        rec.update(admitted=True, t_dec=dec[0], dec_kind=dec[2], planted_at=planted_at,
                   plant_loc=(r.get("plantLocation") or {}) if planted_at is not None else None,
                   kills=kills, kstates=kst, econ=econ, side_of=side_of, team_of=team_of,
                   rstart_game=rstart, sites=sites.get(mi["mapId"]))
        out.append(rec)
    return out, why


# ----------------------------------------------------------------- states

def state_at(rd: dict, t_ms: float, lag_ms: float = 0.0) -> dict:
    """The Riot state at roundTime `t_ms`; alive counts as of `t_ms - lag_ms`."""
    ta = t_ms - lag_ms
    alive = set(rd["team_of"])
    for ks in rd["kstates"]:
        if ks["t"] <= ta:
            alive = ks["alive"]
        else:
            break
    att = rd["att_team"]
    a = sum(1 for s in alive if rd["team_of"][s] == att)
    al = sum(rd["econ"].get(s, 0.0) for s in alive if rd["team_of"][s] == att)
    dl = sum(rd["econ"].get(s, 0.0) for s in alive if rd["team_of"][s] != att)
    planted = rd["planted_at"] is not None and rd["planted_at"] <= t_ms
    return {"t": t_ms / 1000.0, "a": a, "d": len(alive) - a, "aload": al, "dload": dl,
            "planted": planted, "tp": (rd["planted_at"] / 1000.0) if planted else None}


def kill_states(rounds) -> list[dict]:
    out = []
    for ri, rd in enumerate(rounds):
        ks = [k for k in rd["kstates"] if not k["deciding"] and k["t"] < rd["t_dec"]]
        # simultaneous kills collapse to the last
        keep = [k for i, k in enumerate(ks) if i + 1 == len(ks) or ks[i + 1]["t"] != k["t"]]
        for k in keep:
            s = state_at(rd, k["t"])
            s.update(ri=ri, locs=k["locs"])
            out.append(s)
    return out


def grid_states(rounds, step_ms=1000.0, lag_ms=0.0) -> list[dict]:
    out = []
    for ri, rd in enumerate(rounds):
        t = 0.0
        while t < rd["t_dec"]:
            s = state_at(rd, t, lag_ms)
            s["ri"] = ri
            out.append(s)
            t += step_ms
    return out


# ----------------------------------------------------------------- features

def columns(S: list[dict], rounds, groups: list[str], maps: list[str]) -> tuple[np.ndarray, list[float]]:
    cols, pen = [], []

    def add(v, p=RIDGE):
        cols.append(np.asarray(v, dtype=float))
        pen.append(p)

    a = np.array([s["a"] for s in S], float)
    d = np.array([s["d"] for s in S], float)
    t = np.array([s["t"] for s in S], float)
    planted = np.array([1.0 if s["planted"] else 0.0 for s in S])
    tp = np.array([s["tp"] if s["tp"] is not None else np.nan for s in S], float)
    rem_round = np.clip(ROUND_LIVE_CLOCK_MS / 1000.0 - t, 0, None)
    rem_spike = np.where(planted > 0, np.clip(SPIKE_FUSE_MS / 1000.0 - (t - np.nan_to_num(tp)), 0, None), 0.0)
    for g in groups:
        if g == "alive":
            add((a - d) / 5.0)
            add((a - d) / np.maximum(a + d, 1.0))
        elif g == "load":
            add((np.array([s["aload"] for s in S]) - np.array([s["dload"] for s in S])) / 10000.0)
        elif g == "side":
            add(np.ones(len(S)), SIDE_PEN)
        elif g == "mapside":
            mp = [rounds[s["ri"]]["map"] for s in S]
            for m in maps:
                add([1.0 if x == m else 0.0 for x in mp])
        elif g == "flag":
            add(planted)
        elif g == "clock":
            add(np.where(planted > 0, rem_spike, rem_round) / 100.0)
        elif g in ("preclock", "preclock_m"):
            # `_m`: masked to pre-plant states, for one shared model (post hoc)
            k = (1.0 - planted) if g.endswith("_m") else 1.0
            add(k * rem_round / 100.0)
            add(k * np.clip(20.0 - rem_round, 0, None) / 20.0)
        elif g in ("postclock", "postclock_m"):
            k = planted if g.endswith("_m") else 1.0
            late7 = k * (rem_spike < DEFUSE_MS / 1000.0).astype(float)
            a0 = k * (a == 0).astype(float)
            add(k * rem_spike / 45.0)
            add(late7)
            add(k * (rem_spike < HALF_DEFUSE_MS / 1000.0).astype(float))
            add(a0)
            add(a0 * late7)
        elif g in ("pos_riot", "pos_ally"):
            for k in POS_KEYS[g]:
                add([s[k] for s in S])
        else:
            raise ValueError(g)
    return np.column_stack(cols), pen


POS_KEYS = {"pos_riot": ("att_near", "def_near", "att_md", "def_md"),
            "pos_ally": ("ally_near_att", "ally_md_att", "ally_iso_att",
                         "ally_near_def", "ally_md_def", "ally_iso_def")}


def sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_logit(X, y, w, pen):
    beta = np.zeros(X.shape[1])
    P = np.diag(pen)
    for _ in range(200):
        p = sig(X @ beta)
        g = X.T @ (w * (p - y)) + P @ beta
        H = X.T @ ((w * p * (1 - p))[:, None] * X) + P + 1e-9 * np.eye(len(beta))
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-10:
            return beta
    raise ValueError("logistic fit did not converge")


class Data:
    def __init__(self, S, rounds):
        self.S, self.rounds = S, rounds
        self.ri = np.array([s["ri"] for s in S])
        self.y = np.array([rounds[s["ri"]]["y"] for s in S], float)
        self.match = np.array([rounds[s["ri"]]["sid"] for s in S])
        n = Counter(self.ri.tolist())
        self.w = np.array([1.0 / n[r] for r in self.ri])
        self.post = np.array([s["planted"] for s in S], bool)

    def subset(self, mask):
        return Data([s for s, k in zip(self.S, mask) if k], self.rounds)


def lomo(D: Data, spec, maps, eval_D: Data | None = None, eval_override=None):
    """Held-out P(attackers win) per state of `eval_D` (default `D`).

    `spec` is a list of feature groups, a dict {"pre": [...], "post": [...]}
    for the phase model, or "gr". `eval_override` substitutes the states
    whose features are scored (same length and order as `eval_D.S`)."""
    E = eval_D or D
    ES = eval_override if eval_override is not None else E.S
    if spec == "gr":
        a = np.array([s["a"] for s in ES], float)
        d = np.array([s["d"] for s in ES], float)
        return np.clip(a / np.maximum(a + d, 1.0), 0.01, 0.99), {}
    p = np.full(len(ES), np.nan)
    coefs = {}
    phases = ({"all": (spec, np.ones(len(D.S), bool), np.ones(len(ES), bool))} if isinstance(spec, list)
              else {"pre": (spec["pre"], ~D.post, ~np.array([s["planted"] for s in ES], bool)),
                    "post": (spec["post"], D.post, np.array([s["planted"] for s in ES], bool))})
    for ph, (groups, trmask, evmask) in phases.items():
        Xtr, pen = columns([s for s, k in zip(D.S, trmask) if k], D.rounds, groups, maps)
        Xev, _ = columns([s for s, k in zip(ES, evmask) if k], E.rounds, groups, maps) \
            if evmask.any() else (None, None)
        ytr, wtr, mtr = D.y[trmask], D.w[trmask], D.match[trmask]
        mev = E.match[evmask]
        pev = np.full(int(evmask.sum()), np.nan)
        for sid in sorted(set(mev.tolist())):
            tr = mtr != sid
            beta = fit_logit(Xtr[tr], ytr[tr], wtr[tr], pen)
            k = mev == sid
            pev[k] = sig(Xev[k] @ beta)
        p[evmask] = pev
        coefs[ph] = fit_logit(Xtr, ytr, wtr, pen).round(4).tolist()
    return p, coefs


def scores(D: Data, p, w=None) -> dict:
    w = D.w if w is None else w
    y = D.y
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    ll = -(y * np.log(pc) + (1 - y) * np.log(1 - pc))
    out = {"n_states": int(len(y)), "n_rounds": int(len(set(D.ri.tolist()))),
           "n_matches": int(len(set(D.match.tolist()))),
           "logloss_nats": round(float(np.average(ll, weights=w)), 5),
           "logloss_bits": round(float(np.average(ll, weights=w)) / LN2, 5),
           "brier": round(float(np.average((pc - y) ** 2, weights=w)), 5),
           "logloss_nats_per_state": round(float(ll.mean()), 5),
           "reliability": []}
    for lo in np.arange(0, 1, 0.2):
        k = (p >= lo) & ((p < lo + 0.2) if lo < 0.79 else (p <= 1.0))
        if k.any():
            out["reliability"].append({"bin": [round(float(lo), 1), round(float(lo) + 0.2, 1)],
                                       "states": int(k.sum()), "round_weight": round(float(w[k].sum()), 2),
                                       "predicted": round(float(np.average(p[k], weights=w[k])), 4),
                                       "observed": round(float(np.average(y[k], weights=w[k])), 4)})
    return out


def compare(D: Data, pa, pb, boot: int, w=None) -> dict:
    """Log-loss improvement of b over a (positive = b better), with a
    match-cluster bootstrap 95% interval."""
    w = D.w if w is None else w
    y = D.y

    def ll(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    diff = ll(pa) - ll(pb)
    sids = sorted(set(D.match.tolist()))
    g = np.array([[float(np.sum(w[D.match == s] * diff[D.match == s])),
                   float(np.sum(w[D.match == s]))] for s in sids])
    rng = np.random.default_rng(0)
    draws = rng.integers(0, len(g), (boot, len(g)))
    tot = g[draws].sum(axis=1)
    r = tot[:, 0] / tot[:, 1]
    lo, hi = np.quantile(r, [0.025, 0.975])
    m = float(g[:, 0].sum() / g[:, 1].sum())
    return {"improvement_nats": round(m, 5), "improvement_bits": round(m / LN2, 5),
            "ci95_nats": [round(float(lo), 5), round(float(hi), 5)],
            "matches_better": int(np.sum(g[:, 0] > 0)), "matches": len(sids)}


# ----------------------------------------------------------------- positions

def riot_pos_features(S, rounds):
    """Both teams' coarse positions at kill states, from Riot's playerLocations."""
    for s in S:
        rd = rounds[s["ri"]]
        sites = list((rd["sites"] or {}).values())
        tgt = None
        if s["planted"] and rd["plant_loc"]:
            tgt = [(rd["plant_loc"]["x"], rd["plant_loc"]["y"])]
        near = {1: 0, 0: 0}
        dist = {1: [], 0: []}
        for p in s["locs"]:
            side = rd["side_of"].get(p["subject"])
            if side is None:
                continue
            x, y = p["location"]["x"], p["location"]["y"]
            dd = min(math.hypot(x - u, y - v) for u, v in (tgt or sites)) if (tgt or sites) else 0.0
            near[side] += dd <= NEAR_CM
            dist[side].append(dd)
        s.update(att_near=near[1] / 5.0, def_near=near[0] / 5.0,
                 att_md=(statistics.fmean(dist[1]) / 5000.0) if dist[1] else 0.0,
                 def_md=(statistics.fmean(dist[0]) / 5000.0) if dist[0] else 0.0)


def ally_positions(sid: str, cache_dir: Path):
    """(t_ms, entity, x_px, y_px) arrays of ally and self observations, cached."""
    cp = cache_dir / f"positions_{sid}.npz"
    if cp.is_file():
        z = np.load(cp, allow_pickle=False)
        return z["t"], z["e"], z["x"], z["y"], str(z["version"])
    path = STORE / "events" / "round_entity" / f"{sid}.jsonl"
    t, e, x, y, ver = [], [], [], [], set()
    ids = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if '"kind":"observation"' not in line or ('"family":"ally"' not in line
                                                       and '"family":"self"' not in line):
                continue
            r = json.loads(line)
            if r.get("x") is None or r.get("y") is None:
                continue
            ver.add(r.get("round_entity_version"))
            t.append(float(r["t_ms"]))
            e.append(ids.setdefault(r["entity_id"], len(ids)))
            x.append(float(r["x"]))
            y.append(float(r["y"]))
    o = np.argsort(np.asarray(t), kind="stable")
    arr = [np.asarray(v)[o] for v in (t, e, x, y)]
    version = ",".join(sorted(v for v in ver if v))
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(cp, t=arr[0], e=arr[1], x=arr[2], y=arr[3], version=np.array(version))
    return (*arr, version)


def px_to_game(mf):
    p0 = np.array(mf.to_px(0.0, 0.0))
    J = np.column_stack([np.array(mf.to_px(1000.0, 0.0)) - p0,
                         np.array(mf.to_px(0.0, 1000.0)) - p0]) / 1000.0
    Ji = np.linalg.inv(J)
    return lambda px, py: Ji @ (np.array([px, py]) - p0)


def capture_frames(rounds, ref, records, cache_dir: Path, why: Counter) -> dict:
    """Per captured session: alignment offset, map transform, my team."""
    from reticle.store import Store
    store = Store(STORE)
    ident = rgt.identify_player(records, STORE)
    out = {}
    for sid in sorted({rd["sid"] for rd in rounds}):
        if not (STORE / "events" / "round_entity" / f"{sid}.jsonl").is_file():
            why[f"no_round_entity:{sid}"] += 1
            continue
        d = records[sid]
        idn = rgt.resolve_lineup_player(d, ident.get(sid, {}), ref)
        me = idn.get("subject")
        team = {p["subject"]: p["teamId"] for p in d["match"]["players"]}.get(me)
        if team is None:
            why[f"no_player:{sid}"] += 1
            continue
        deaths = rgt.stored_deaths(STORE, sid)
        kill_like, _ = rgt.split_deaths(deaths)
        al = rgt.fit_alignment([k["gameTime"] for k in d["match"]["kills"]],
                               [float(r["t_ms"]) for r in kill_like])
        if al is None:
            why[f"no_alignment:{sid}"] += 1
            continue
        man = store.read_manifest(sid)
        mf, mwhy = rgt.map_frame_for(sid, man, ref, d, STORE)
        out[sid] = {"a_ms": al["a_ms"], "matched": al["matched"], "n_riot": al["n_riot"],
                    "mad_ms": al["residual_mad_ms"], "team": team, "basis": idn.get("basis"),
                    "mf": mf, "mf_reason": mwhy, "man": man}
    return out


def ally_pos_features(G: Data, frames, cache_dir: Path, why: Counter, mode: str = "window"):
    """Attach reticle ally-position features to G states; returns the mask of
    states whose every living ally was observed (full coverage).

    `window` (0.1.0, as predicted) takes each entity's nearest observation
    within `POS_TOL_MS`; a track that changes its entity id inside the window
    then counts twice. `frame` (post hoc) takes every ally and self
    observation of the single stored frame nearest the instant, within
    `FRAME_TOL_MS`, so one icon counts once."""
    full = np.zeros(len(G.S), bool)
    cover = Counter()
    by_sid = defaultdict(list)
    for i, s in enumerate(G.S):
        by_sid[G.rounds[s["ri"]]["sid"]].append(i)
    versions = {}
    for sid, idx in by_sid.items():
        fr = frames.get(sid)
        if fr is None or fr["mf"] is None:
            cover["no_frame"] += len(idx)
            continue
        t, e, x, y, ver = ally_positions(sid, cache_dir)
        versions[sid] = ver
        to_game = px_to_game(fr["mf"])
        for i in idx:
            s = G.S[i]
            rd = G.rounds[s["ri"]]
            if rd["rstart_game"] is None:
                cover["no_round_start"] += 1
                continue
            ts = fr["a_ms"] + rgt.MINIMAP_LAG_MS + rd["rstart_game"] + s["t"] * 1000.0
            if mode == "frame":
                k = int(np.searchsorted(t, ts))
                near = [kk for kk in (k - 1, k) if 0 <= kk < len(t) and abs(t[kk] - ts) <= FRAME_TOL_MS]
                tf = min((t[kk] for kk in near), key=lambda v: abs(v - ts)) if near else None
                lo = int(np.searchsorted(t, tf, "left")) if tf is not None else 0
                hi = int(np.searchsorted(t, tf, "right")) if tf is not None else 0
            else:
                lo = int(np.searchsorted(t, ts - POS_TOL_MS, "left"))
                hi = int(np.searchsorted(t, ts + POS_TOL_MS, "right"))
            best = {}
            if hi > lo:
                dts = np.abs(t[lo:hi] - ts)
                for j in np.argsort(dts, kind="stable")[::-1]:
                    best[int(e[lo + j])] = (float(dts[j]), float(x[lo + j]), float(y[lo + j]))
            ally_side = 1 if fr["team"] == rd["att_team"] else 0
            n_alive = s["a"] if ally_side else s["d"]
            pts = [to_game(px, py) for _dt, px, py in best.values()]
            s["ally_n_obs"], s["ally_n_alive"] = len(pts), n_alive
            if len(pts) == n_alive and n_alive > 0:
                full[i] = True
                cover["full"] += 1
            elif len(pts) > n_alive:
                cover["more_than_alive"] += 1
            elif pts:
                cover["partial"] += 1
            else:
                cover["none"] += 1
            sites = list((rd["sites"] or {}).values())
            tgt = ([(rd["plant_loc"]["x"], rd["plant_loc"]["y"])]
                   if s["planted"] and rd["plant_loc"] else sites)
            dd = [min(math.hypot(p[0] - u, p[1] - v) for u, v in tgt) for p in pts] if tgt else []
            iso = 0
            for k, p in enumerate(pts):
                others = [math.hypot(p[0] - q[0], p[1] - q[1]) for m2, q in enumerate(pts) if m2 != k]
                iso += bool(others) and min(others) > ISOLATED_CM
            near = sum(v <= NEAR_CM for v in dd) / 5.0
            md = (statistics.fmean(dd) / 5000.0) if dd else 0.0
            for side, suf in ((1, "att"), (0, "def")):
                on = ally_side == side
                s[f"ally_near_{suf}"] = near if on else 0.0
                s[f"ally_md_{suf}"] = md if on else 0.0
                s[f"ally_iso_{suf}"] = (iso / 5.0) if on else 0.0
    why.update({f"pos_cover_{mode}_{k}": v for k, v in cover.items()})
    return full, versions


# ----------------------------------------------------------------- observed

def reticle_inputs_at_states(G: Data, frames, why: Counter):
    """Per G state of a captured match: reticle's observed state or None."""
    import pyarrow.parquet as pq
    from reticle.store import Store
    from reticle import roster as _roster
    from reticle import menu as _menu
    store = Store(STORE)
    obs = [None] * len(G.S)
    cover = Counter()
    by_sid = defaultdict(list)
    for i, s in enumerate(G.S):
        by_sid[G.rounds[s["ri"]]["sid"]].append(i)
    stamps = {}
    for sid, idx in by_sid.items():
        fr = frames.get(sid)
        if fr is None:
            cover["no_capture_frame"] += len(idx)
            continue
        man = fr["man"]
        date = man["ingested_at"][:10]
        rp = store.roster_path(sid, date)
        if not rp.exists() or not store.hud_path(sid, date).exists():
            cover["no_roster_or_hud"] += len(idx)
            continue
        hud = pq.read_table(store.hud_path(sid, date))
        roster = pq.read_table(rp)
        menu, mwhy = _menu.stored_menu(store, sid)
        ally, enemy = _roster.resolve(hud, roster, menu=menu.at if menu else None)
        rt = roster.column("t_ms").to_pylist()
        ht = hud.column("t_ms").to_pylist()
        clock = hud.column("clock_ms").to_pylist()
        rounds_tab = store.read_rounds(sid, date).to_pylist() if store.rounds_path(sid, date).exists() else []
        meta = roster.schema.metadata or {}
        stamps[sid] = {"roster": meta.get(b"roster_version", b"").decode(), "menu": mwhy,
                       "hud": (hud.schema.metadata or {}).get(b"hud_version", b"").decode(),
                       "rounds": rounds_tab[0]["round_version"] if rounds_tab else None}
        for i in idx:
            s = G.S[i]
            rd = G.rounds[s["ri"]]
            if rd["rstart_game"] is None:
                cover["no_round_start"] += 1
                continue
            base = fr["a_ms"] + rgt.MINIMAP_LAG_MS + rd["rstart_game"]
            ts = base + s["t"] * 1000.0
            j = bisect.bisect_right(rt, ts) - 1
            if j < 0 or ts - rt[j] > ASOF_MS or ally[j] is None or enemy[j] is None:
                cover["alive_unread"] += 1
                continue
            sr = next((r for r in rounds_tab
                       if r["t_start_ms"] <= ts <= (r["t_close_ms"] or r["t_end_ms"])), None)
            if sr is None or sr["spike_planted"] is None or (sr["spike_planted"] and sr["plant_t_ms"] is None):
                cover["plant_unread"] += 1
                continue
            planted = bool(sr["spike_planted"]) and sr["plant_t_ms"] <= ts
            h = bisect.bisect_right(ht, ts) - 1
            if planted:
                t_obs = None
            else:
                if h < 0 or ts - ht[h] > ASOF_MS or clock[h] is None:
                    cover["clock_unread"] += 1
                    continue
                t_obs = ROUND_LIVE_CLOCK_MS / 1000.0 - clock[h] / 1000.0
            ally_att = fr["team"] == rd["att_team"]
            a, d = (ally[j], enemy[j]) if ally_att else (enemy[j], ally[j])
            tp = None
            if planted:
                # the spike clock runs from the observed plant instant
                t_obs = s["t"]
                tp = (sr["plant_t_ms"] - base) / 1000.0
            cover["observed"] += 1
            obs[i] = {"ri": s["ri"], "t": t_obs, "a": int(a), "d": int(d), "aload": 0.0, "dload": 0.0,
                      "planted": planted, "tp": tp}
    why.update({f"obs_cover_{k}": v for k, v in cover.items()})
    return obs, stamps


# ----------------------------------------------------------------- main

def digest(paths) -> str:
    h = hashlib.sha1()
    for p in sorted(paths):
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:12]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(STORE / "analysis" / "winprob-reference-20261004"))
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--cache", default=None, help="position cache directory (default: --out)")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--no-store", action="store_true", help="Riot-only parts (a)-(c), lag, K positions")
    args = ap.parse_args(argv)
    try:  # Below Normal priority on Windows; threads are capped by the caller's env
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass
    t0 = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
    records = rgt.riot_records(STORE)
    sites = site_centres(ref)
    rounds, why = [], Counter()
    for sid, d in sorted(records.items()):
        rs, w = match_rounds(sid, d, ref, sites)
        rounds += rs
        why.update(w)
    adm = [r for r in rounds if r.get("admitted")]
    maps = sorted({r["map"] for r in adm})
    R = {"version": VERSION, "riot_files": len(records),
         "riot_digest": digest((STORE / "external" / "riot").glob("*.json")),
         "constants": {"ROUND_LIVE_CLOCK_MS": ROUND_LIVE_CLOCK_MS, "SPIKE_FUSE_MS": SPIKE_FUSE_MS,
                       "DEFUSE_MS": DEFUSE_MS, "HALF_DEFUSE_MS": HALF_DEFUSE_MS, "RIDGE": RIDGE,
                       "NEAR_CM": NEAR_CM, "ISOLATED_CM": ISOLATED_CM, "POS_TOL_MS": POS_TOL_MS,
                       "ASOF_MS": ASOF_MS, "MINIMAP_LAG_MS": rgt.MINIMAP_LAG_MS},
         "admission": {"rounds_listed": sum(len(d["match"]["roundResults"]) for d in records.values()),
                       "admitted": len(adm), "excluded": dict(why),
                       "admitted_ot": sum(r["ot"] for r in adm),
                       "admitted_unrated": sum(r["unrated"] for r in adm),
                       "unrated_matches": sorted({r["sid"] for r in adm if r["unrated"]}),
                       "sim_disagrees": [{"sid": r["sid"], "round": r["round"] + 1, **r["sim_disagrees"]}
                                         for r in rounds if r.get("sim_disagrees")],
                       "sim_agree_rate": round(len(adm) / max(1, len(adm) + why["simulation_disagrees"]), 4),
                       "attacker_win_rate": round(statistics.fmean(r["y"] for r in adm), 4),
                       "decisions": dict(Counter(r["dec_kind"] for r in adm))}}
    # site centres checked against Riot plant locations
    sd = []
    for r in adm:
        if r["plant_loc"] and r["sites"]:
            sd.append(min(math.hypot(r["plant_loc"]["x"] - u, r["plant_loc"]["y"] - v)
                          for u, v in r["sites"].values()) / 100.0)
    R["site_check_m"] = {"plants": len(sd), "median": round(statistics.median(sd), 2),
                         "p95": round(float(np.quantile(sd, 0.95)), 2)} if sd else None
    print(json.dumps(R["admission"], indent=1, default=str)[:3000])

    K = Data(kill_states(adm), adm)
    G = Data(grid_states(adm), adm)
    base3 = ["alive", "load", "side"]
    phase = {"pre": base3 + ["preclock"], "post": base3 + ["postclock"]}
    ladder = {"M1_alive": ["alive"], "M2_alive_load": ["alive", "load"],
              "M3_alive_load_side": base3, "M4_alive_load_mapside": base3 + ["mapside"],
              "B0_gamblers_ruin": "gr", "B1_plant_flag": base3 + ["flag"],
              "B2_plant_flag_clock": base3 + ["flag", "clock"], "B3_phase_clock": phase}
    for name, D in (("K", K), ("G", G)):
        P, block = {}, {}
        for mname, spec in ladder.items():
            P[mname], coef = lomo(D, spec, maps)
            block[mname] = scores(D, P[mname]) | {"coef_full": coef}
            print(name, mname, block[mname]["logloss_nats"], block[mname]["brier"], flush=True)
        steps = [("M1_alive", "M2_alive_load"), ("M2_alive_load", "M3_alive_load_side"),
                 ("M3_alive_load_side", "M4_alive_load_mapside"), ("M1_alive", "B0_gamblers_ruin"),
                 ("M3_alive_load_side", "B1_plant_flag"), ("B1_plant_flag", "B2_plant_flag_clock"),
                 ("B1_plant_flag", "B3_phase_clock"), ("B2_plant_flag_clock", "B3_phase_clock")]
        block["steps"] = {f"{a}->{b}": compare(D, P[a], P[b], args.boot) for a, b in steps}
        post = D.post
        if post.any():
            Dp = D.subset(post)
            block["post_plant_only"] = {m: scores(Dp, P[m][post])["logloss_nats"]
                                        for m in ("M3_alive_load_side", "B1_plant_flag",
                                                  "B2_plant_flag_clock", "B3_phase_clock")}
            block["post_plant_only"]["B1->B3"] = compare(Dp, P["B1_plant_flag"][post],
                                                         P["B3_phase_clock"][post], args.boot,
                                                         w=D.w[post])
            block["post_plant_only"]["share_of_round_weight"] = round(float(D.w[post].sum() / D.w.sum()), 4)
        # post hoc (written after B3 lost to B1): is it the split or the clock?
        ph = {}
        for mname, spec in (("X1_phase_no_clock", {"pre": base3, "post": base3}),
                            ("X2_flag_shared_masked_clock", base3 + ["flag", "preclock_m", "postclock_m"])):
            P[mname], coef = lomo(D, spec, maps)
            ph[mname] = scores(D, P[mname]) | {"coef_full": coef}
            ph[f"B1_plant_flag->{mname}"] = compare(D, P["B1_plant_flag"], P[mname], args.boot)
        rem_s = np.array([(SPIKE_FUSE_MS / 1000.0 - (s["t"] - s["tp"])) if s["planted"]
                          else (ROUND_LIVE_CLOCK_MS / 1000.0 - s["t"]) for s in D.S])
        for lab, m in (("post_plant_last_10s", D.post & (rem_s < 10.0)),
                       ("pre_plant_last_20s", ~D.post & (rem_s < 20.0))):
            if m.sum() >= 20:
                Dm = D.subset(m)
                ph[lab] = {"states": int(m.sum()), "rounds": int(len(set(D.ri[m].tolist()))),
                           **{k: scores(Dm, P[k][m], w=D.w[m])["logloss_nats"]
                              for k in ("B1_plant_flag", "B3_phase_clock", "X2_flag_shared_masked_clock")},
                           "B1->X2": compare(Dm, P["B1_plant_flag"][m], P["X2_flag_shared_masked_clock"][m],
                                             args.boot, w=D.w[m])}
        block["post_hoc"] = ph
        print(name, "post hoc", {k: v.get("logloss_nats", v) if isinstance(v, dict) else v
                                 for k, v in ph.items()}, flush=True)
        R[name] = block
        if name == "K":
            PK = P
        else:
            PG = P

    # K0: the kill states plus each round's opening state (post hoc, to
    # reconcile with the earlier lenses' kill-instant figure)
    K0S = []
    for ri, rd in enumerate(adm):
        s = state_at(rd, 0.0)
        s["ri"] = ri
        K0S.append(s)
    K0 = Data(K0S + [dict(s) for s in K.S], adm)
    R["K0_with_round_start"] = {}
    for mname in ("M1_alive", "M2_alive_load", "M3_alive_load_side"):
        p, _ = lomo(K0, ladder[mname], maps)
        sc = scores(K0, p)
        R["K0_with_round_start"][mname] = {k: sc[k] for k in ("logloss_nats", "logloss_bits",
                                                             "logloss_nats_per_state", "brier", "n_states")}
    print("K0", R["K0_with_round_start"], flush=True)

    # sensitivity: without overtime, without the unrated matches
    sens = {}
    for label, keep in (("no_ot", lambda r: not r["ot"]), ("no_unrated", lambda r: not r["unrated"]),
                        ("no_ot_no_unrated", lambda r: not r["ot"] and not r["unrated"])):
        for name, D in (("K", K), ("G", G)):
            m = np.array([keep(D.rounds[s["ri"]]) for s in D.S])
            Ds = D.subset(m)
            pa, _ = lomo(Ds, ["alive"], maps)
            pb, _ = lomo(Ds, base3, maps)
            pc, _ = lomo(Ds, phase, maps)
            sens[f"{label}/{name}"] = {"M1": scores(Ds, pa)["logloss_nats"],
                                       "M3": scores(Ds, pb)["logloss_nats"],
                                       "B3": scores(Ds, pc)["logloss_nats"],
                                       "n_rounds": int(len(set(Ds.ri.tolist())))}
    R["sensitivity"] = sens
    print("sensitivity", sens, flush=True)

    # alive lag on a 0.1 s grid; the model is fitted on G, scored on F
    F = Data(grid_states(adm, 100.0), adm)
    lag = {}
    for mname in ("M3_alive_load_side", "B3_phase_clock"):
        p0, _ = lomo(G, ladder[mname], maps, eval_D=F)
        s0 = scores(F, p0)
        lag[mname] = {"F_logloss_nats": s0["logloss_nats"], "F_logloss_bits": s0["logloss_bits"],
                      "F_states": s0["n_states"]}
        for L in LAGS_S:
            FL = grid_states(adm, 100.0, lag_ms=L * 1000.0)
            pL, _ = lomo(G, ladder[mname], maps, eval_D=F, eval_override=FL)
            c = compare(F, pL, p0, args.boot)
            lag[mname][f"lag_{L}s"] = {"cost_bits": c["improvement_bits"], "cost_nats": c["improvement_nats"],
                                       "ci95_bits": [round(v / LN2, 5) for v in c["ci95_nats"]]}
        print("lag", mname, lag[mname], flush=True)
    R["alive_lag"] = lag

    # positions at kills, Riot's playerLocations, both teams
    riot_pos_features(K.S, adm)
    PKpos = {}
    for bname, base in (("M3_alive_load_side", base3), ("B1_plant_flag", base3 + ["flag"])):
        pp, coef = lomo(K, base + ["pos_riot"], maps)
        PKpos[bname] = {"with_pos": scores(K, pp)["logloss_nats"], "coef_full": coef,
                        "step": compare(K, PK[bname], pp, args.boot)}
    pp, coef = lomo(K, {"pre": phase["pre"] + ["pos_riot"], "post": phase["post"] + ["pos_riot"]}, maps)
    PKpos["B3_phase_clock"] = {"with_pos": scores(K, pp)["logloss_nats"], "coef_full": coef,
                               "step": compare(K, PK["B3_phase_clock"], pp, args.boot)}
    R["K_positions_riot"] = PKpos
    print("K positions", {k: v["step"] for k, v in PKpos.items()}, flush=True)

    if not args.no_store:
        cache_dir = Path(args.cache) if args.cache else out_dir
        frames = capture_frames(adm, ref, records, cache_dir, why)
        R["capture_frames"] = {sid: {k: v for k, v in f.items() if k not in ("mf", "man")}
                               for sid, f in frames.items()}
        # positions on G, reticle allies: `window` as predicted, `frame` post hoc
        cap = np.array([G.rounds[s["ri"]]["sid"] in frames for s in G.S])
        for mode, key in (("window", "G_positions_ally"), ("frame", "G_positions_ally_frame")):
            full, pver = ally_pos_features(G, frames, cache_dir, why, mode)
            R["positions_versions"] = pver
            Gc = G.subset(full)
            # base: the best Riot-state G model (B1), chosen before any position fit
            pos_spec = ladder["B1_plant_flag"] + ["pos_ally"]
            pb, _ = lomo(Gc, ladder["B1_plant_flag"], maps)
            pp, coef = lomo(Gc, pos_spec, maps)
            R[key] = {
                "mode": mode, "post_hoc": mode == "frame",
                "coverage": {"captured_states": int(cap.sum()), "full_states": int(full.sum()),
                             "full_share_of_captured": round(float(full.sum() / max(cap.sum(), 1)), 4),
                             "detail": {k: v for k, v in why.items() if k.startswith(f"pos_cover_{mode}_")}},
                "base_B1": scores(Gc, pb), "with_pos": scores(Gc, pp), "coef_full": coef,
                "step": compare(Gc, pb, pp, args.boot)}
            # lurker subset: a living ally farther than ISOLATED_CM from every other
            iso = np.array([(s.get("ally_iso_att", 0) + s.get("ally_iso_def", 0)) > 0 for s in Gc.S])
            if iso.any():
                Gi = Gc.subset(iso)
                R[key]["isolated_ally_states"] = {
                    "states": int(iso.sum()), "share_round_weight": round(float(Gc.w[iso].sum() / Gc.w.sum()), 4),
                    "base_B1": scores(Gi, pb[iso], w=Gc.w[iso])["logloss_nats"],
                    "with_pos": scores(Gi, pp[iso], w=Gc.w[iso])["logloss_nats"],
                    "step": compare(Gi, pb[iso], pp[iso], args.boot, w=Gc.w[iso])}
            print("G positions", mode, R[key]["coverage"], R[key]["step"], flush=True)

        # observation cost
        obs, stamps = reticle_inputs_at_states(G, frames, why)
        R["observed_stamps"] = stamps
        have = np.array([o is not None for o in obs])
        Go = G.subset(have)
        Oobs = [o for o in obs if o is not None]
        no_load = {"pre": ["alive", "side", "preclock"], "post": ["alive", "side", "postclock"]}
        flag_clock = ["alive", "side", "flag", "clock"]
        blk = {"coverage": {"captured_states": int(cap.sum()), "observed_states": int(have.sum()),
                            "share_of_captured": round(float(have.sum() / max(cap.sum(), 1)), 4),
                            "detail": {k: v for k, v in why.items() if k.startswith("obs_cover_")}}}
        for mname, spec in (("O_alive_side_flag_clock", flag_clock), ("O_alive_side_phase", no_load)):
            # fit on all Riot G states (LOMO), score on the observed subset twice
            p_true, _ = lomo(G, spec, maps, eval_D=Go)
            # the observed plant flag picks the phase model that scores the state
            p_obs, _ = lomo(G, spec, maps, eval_D=Go, eval_override=Oobs)
            blk[mname] = {"riot_inputs": scores(Go, p_true), "observed_inputs": scores(Go, p_obs),
                          "cost": compare(Go, p_obs, p_true, args.boot)}
        # agreement of the observed inputs with Riot's
        agree = Counter()
        for s, o in zip(Go.S, Oobs):
            agree["alive_both_right"] += (s["a"], s["d"]) == (o["a"], o["d"])
            agree["att_alive_off"] += s["a"] != o["a"]
            agree["def_alive_off"] += s["d"] != o["d"]
            agree["plant_right"] += s["planted"] == o["planted"]
            agree["plant_late"] += s["planted"] and not o["planted"]
            agree["plant_early"] += o["planted"] and not s["planted"]
            if not s["planted"] and not o["planted"]:
                agree["clock_compared"] += 1
                agree["clock_within_1s"] += abs(s["t"] - o["t"]) <= 1.0
        blk["agreement"] = dict(agree)
        R["observed"] = blk
        print("observed", blk["coverage"], blk["O_alive_side_phase"]["cost"], dict(agree), flush=True)

    R["elapsed_s"] = round(time.time() - t0, 1)
    (out_dir / "results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    print("wrote", out_dir / "results.json", R["elapsed_s"], "s")
    if args.record:
        record_results(R)


def record_results(R: dict):
    from reticle import metrics
    deps = {"tool_version": VERSION, "riot_digest": R["riot_digest"], **R["constants"]}
    ctx = {"admitted_rounds": R["admission"]["admitted"], "riot_files": R["riot_files"]}
    for name in ("K", "G"):
        vals = {}
        for m, b in R[name].items():
            if isinstance(b, dict) and "logloss_nats" in b:
                vals[f"{m}.nats"] = b["logloss_nats"]
                vals[f"{m}.bits"] = b["logloss_bits"]
                vals[f"{m}.brier"] = b["brier"]
                vals[f"{m}.states"] = b["n_states"]
        for k, c in R[name]["steps"].items():
            vals[f"step:{k}.nats"] = c["improvement_nats"]
        for k, b in R[name].get("post_hoc", {}).items():
            if "logloss_nats" in b:
                vals[f"post_hoc:{k}.nats"] = b["logloss_nats"]
            elif "improvement_nats" in b:
                vals[f"post_hoc:{k}.nats"] = b["improvement_nats"]
        if name == "K":
            for m, b in R["K0_with_round_start"].items():
                vals[f"K0:{m}.nats"] = b["logloss_nats"]
                vals[f"K0:{m}.nats_per_state"] = b["logloss_nats_per_state"]
        metrics.record("winprob_reference", part=f"riot_{name}", values=vals, deps=deps, context=ctx,
                       ci={f"step:{k}.nats": c["ci95_nats"] for k, c in R[name]["steps"].items()})
    lag = {f"{m}.{k}.bits": v["cost_bits"] for m, b in R["alive_lag"].items()
           for k, v in b.items() if k.startswith("lag_")}
    metrics.record("winprob_reference", part="alive_lag", values=lag, deps=deps, context=ctx)
    kp = {f"{m}.step.nats": b["step"]["improvement_nats"] for m, b in R["K_positions_riot"].items()}
    metrics.record("winprob_reference", part="positions_K_riot", values=kp, deps=deps, context=ctx,
                   ci={f"{m}.step.nats": b["step"]["ci95_nats"] for m, b in R["K_positions_riot"].items()})
    for gk in ("G_positions_ally", "G_positions_ally_frame"):
        if gk not in R:
            continue
        g = R[gk]
        metrics.record("winprob_reference", part=f"positions_G_ally/{g['mode']}",
                       values={"step.nats": g["step"]["improvement_nats"],
                               "full_states": g["coverage"]["full_states"],
                               "base.nats": g["base_B1"]["logloss_nats"],
                               "with_pos.nats": g["with_pos"]["logloss_nats"]},
                       deps=deps | {"positions": sorted(set(R["positions_versions"].values()))},
                       context=ctx, ci={"step.nats": g["step"]["ci95_nats"]})
    if "observed" in R:
        o = R["observed"]
        vals = {"observed_states": o["coverage"]["observed_states"],
                "share_of_captured": o["coverage"]["share_of_captured"]}
        for m in ("O_alive_side_flag_clock", "O_alive_side_phase"):
            b = o[m]
            vals[f"{m}.riot_inputs.nats"] = b["riot_inputs"]["logloss_nats"]
            vals[f"{m}.observed_inputs.nats"] = b["observed_inputs"]["logloss_nats"]
            vals[f"{m}.cost.nats"] = b["cost"]["improvement_nats"]
        metrics.record("winprob_reference", part="observed_cost", values=vals,
                       ci={f"{m}.cost.nats": o[m]["cost"]["ci95_nats"]
                           for m in ("O_alive_side_flag_clock", "O_alive_side_phase")},
                       deps=deps | {"stamps": sorted({json.dumps(v, sort_keys=True)
                                                      for v in R["observed_stamps"].values()})},
                       context=ctx)
    print("recorded winprob_reference parts")


if __name__ == "__main__":
    main()
