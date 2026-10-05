r"""Decision value on the stored Riot records: the S0 pilot and fight reach.

    .\.venv\Scripts\python.exe prototypes\decision_value.py pilot [--record] [--boot 101]
    .\.venv\Scripts\python.exe prototypes\decision_value.py reach [--record] [--shuffles 20]

Why this exists
---------------
`docs/COACHING_DECISION_VALUE.md` designs coaching that prices a decision
through the transition it changes and values the transition with the coarse
round model V(z) of `prototypes/winprob_reference.py`. Section 7 names the
first experiment, trade spacing on the 22 captured Riot records (`pilot`).
`reach` asks the next question: whether who can JOIN a fight, read on the
2D sightline map (`prototypes/sightlines.py`), predicts the fight better than
who stands near it. Weapons and utility are left out.

Development set only
--------------------
Everything here fits and scores on the 22 captured Riot records
(`<store>/external/riot/`), leaving one match out. They never enter a
production fit. The 14 uncaptured matches whose replays are kept
(`<store>/external/replays/manifest.json`, entries with no capture session)
are held out: any record among them is dropped and counted (none is, since
those matches were never captured). The player's own HenrikDev history is
not read.

Rounds and kill instants
------------------------
Rounds are `winprob_reference.match_rounds`' admitted rounds; a kill instant
is a kill before the round's decision. The living set after a kill is the
event simulation's (`simulate`, revives included); positions are that kill's
`playerLocations` (which never list the victim) and `victimLocation`.

pilot (S0, section 7 as written)
--------------------------------
Episodes open at every kill instant for every living player with a living
teammate; the player's episodes (`identify_player` then
`resolve_lineup_player`) are the subset the card would show. Context: the
nearest living teammate's distance (m). Outcomes within `N_MS` = 10 s
compete: dies untraded; dies and his killer dies to his team within
`TRADE_MS` = 5 s; survives (a later death, or one after the round's decision,
is survival). An episode whose death is followed by the victim alive again in
the round (revived) is removed. z = own and enemy alive, loadout difference,
own side attacking, planted. A multinomial logistic (survive reference;
`scipy.optimize`, ridge `RIDGE` on all but intercepts) fits outcomes on z,
distance and the player's offset (his indicator on each outcome's
intercept), leaving one match out for scores and refitting on 101 match
resamples for intervals. Delta V comes from winprob_reference's B1 model
(alive, load, side, flag) fitted with the episode's match left out; c_ref is
the band's median distance at the same (own, enemy) alive counts. P4 reads
reticle's stored `round_entity` stream (families ally and self) at the
player's episode instants, one stored frame within `FRAME_TOL_MS` of the
aligned capture time.

reach (label-symmetric fight features)
--------------------------------------
A fight is a development-set gun kill between opposite teams; its label is
"the attacking side's duelist won". Every feature is built per side S,
around S's duelist dS facing the other duelist dO, over S's OTHER living
players (both duelists excluded), never centred on killer or victim:

- swing(s): others whose walk to the nearest cell that sees dO is <= s m;
- trade(t): the same at t m;
- node(graph): others in the same or an adjacent region as dS or dO;
- radius(r): others within r m of dS (the comparison).

"Sees dO" uses `Sightlines.vis_near` (a one-cell tolerance; the gate,
`sightlines.py gate`, measured why). Each family adds its attacker and
defender counts to a baseline logistic (alive terms, planted, pre-plant
round-time bins). A position-shuffle null permutes each side's other
players' positions among fights of the same map, side and count, so the
alive counts the baseline reads are unchanged.

The plant model fits the round winner at the plant from alive counts and
plant time, plus each side's players within t m of a cell that sees the
spike and the defenders' mean path distance to it (`plantPlayerLocations`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
from scipy.optimize import minimize  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import riot_ground_truth as rgt  # noqa: E402
import sightlines as sl  # noqa: E402
import winprob_reference as wr  # noqa: E402

VERSION = "decision-value-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
OUT = STORE / "analysis" / "decision-value-20261004"
N_MS = 10000.0
TRADE_MS = 5000.0
RIDGE = 1.0
FRAME_TOL_MS = wr.FRAME_TOL_MS
SLOTS = 10
MAXK = 40
#: The reach grids, chosen on development log loss.
SWING_S = (0.0, 2.0, 4.0)
TRADE_T = (5.0, 10.0, 15.0, 20.0)
RADIUS_R = (5.0, 10.0, 15.0, 20.0, 30.0)
GRAPHS = ("callout", "sight")
PLANT_T = (5.0, 10.0, 15.0, 20.0)
#: Pre-plant round-time bin edges (s).
TIME_BINS = (20.0, 40.0, 70.0)
OUTCOMES = ("survives", "dies_untraded", "dies_traded")


def _below_normal() -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:  # noqa: BLE001 -- best effort
        pass


def source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


# ----------------------------------------------------------------- data

def held_out_ids() -> set:
    man = json.loads((STORE / "external" / "replays" / "manifest.json").read_text(encoding="utf-8"))
    return {f["file"].rsplit(".", 1)[0] for f in man["files"] if not f.get("capture_session")}


class Dev:
    """The development set as padded per-round kill arrays (round, kill, slot).

    `records` (Riot-shaped, keyed by a match key) and `me` (key -> the
    player's subject) replace the 22 captured records and their player
    identification; `prototypes/engagement_reach.py` passes the player's
    HenrikDev history this way."""

    def __init__(self, records: dict | None = None, me: dict | None = None):
        self.ref = rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
        records = rgt.riot_records(STORE) if records is None else records
        held = held_out_ids()
        self.held_excluded = sorted(s for s, d in records.items() if d["match"]["matchInfo"]["matchId"] in held)
        self.records = {s: d for s, d in records.items() if s not in self.held_excluded}
        ident = rgt.identify_player(self.records, STORE) if me is None else {}
        sites = wr.site_centres(self.ref)
        self.why = Counter()
        rounds = []
        self.me, self.basis = {}, {}
        for sid, d in sorted(self.records.items()):
            if me is None:
                idn = rgt.resolve_lineup_player(d, ident.get(sid, {}), self.ref)
            else:
                idn = {"subject": me.get(sid), "basis": "owner_flag"}
            self.me[sid], self.basis[sid] = idn.get("subject"), idn.get("basis")
            rs, w = wr.match_rounds(sid, d, self.ref, sites)
            rounds += [r for r in rs if r.get("admitted")]
            self.why.update(w)
        self.rounds = rounds
        R = len(rounds)
        self.R = R
        self.sid = np.array([r["sid"] for r in rounds])
        self.map = np.array([self.ref.map_of(r["map_url"])["displayName"].lower() for r in rounds])
        self.t_dec = np.array([r["t_dec"] for r in rounds], float)
        self.planted_at = np.array([r["planted_at"] if r["planted_at"] is not None else np.nan
                                    for r in rounds], float)
        self.y_round = np.array([r["y"] for r in rounds], int)
        # slots: each match's players in record order
        self.subjects = {}
        att = np.zeros((R, SLOTS), bool)
        econ = np.zeros((R, SLOTS))
        me_slot = np.full(R, -1)
        for ri, r in enumerate(rounds):
            subs = [p["subject"] for p in self.records[r["sid"]]["match"]["players"]]
            self.subjects[ri] = subs
            for j, s in enumerate(subs[:SLOTS]):
                att[ri, j] = r["team_of"][s] == r["att_team"]
                econ[ri, j] = r["econ"].get(s, 0.0)
            me = self.me[r["sid"]]
            me_slot[ri] = subs.index(me) if me in subs else -1
        self.att, self.econ, self.me_slot = att, econ, me_slot
        # kills before the decision, padded to MAXK
        nk = np.zeros(R, int)
        kt = np.full((R, MAXK), np.nan)
        killer = np.full((R, MAXK), -1)
        victim = np.full((R, MAXK), -1)
        weapon = np.zeros((R, MAXK), bool)
        alive = np.zeros((R, MAXK, SLOTS), bool)
        pos = np.full((R, MAXK, SLOTS, 2), np.nan)
        for ri, r in enumerate(rounds):
            idx = {s: j for j, s in enumerate(self.subjects[ri])}
            ks = r["kstates"]
            for k, (kill, st) in enumerate(zip(r["kills"], ks)):
                if k >= MAXK:
                    self.why["kills_over_maxk"] += 1
                    break
                kt[ri, k] = kill["roundTime"]
                killer[ri, k] = idx.get(kill["killer"], -1)
                victim[ri, k] = idx.get(kill["victim"], -1)
                weapon[ri, k] = ((kill.get("finishingDamage") or {}).get("damageType")) == "Weapon"
                for s in st["alive"]:
                    alive[ri, k, idx[s]] = True
                for p in kill.get("playerLocations") or ():
                    if p["subject"] in idx:
                        pos[ri, k, idx[p["subject"]]] = (p["location"]["x"], p["location"]["y"])
                vl = kill.get("victimLocation")
                if vl and kill["victim"] in idx:
                    pos[ri, k, idx[kill["victim"]]] = (vl["x"], vl["y"])
                nk[ri] = k + 1
        self.nk, self.kt, self.killer, self.victim = nk, kt, killer, victim
        self.weapon, self.alive, self.pos = weapon, alive, pos
        self.valid = np.arange(MAXK)[None, :] < nk[:, None]
        self.alive_before = alive.copy()
        rr, kk = np.nonzero(self.valid & (victim >= 0))
        self.alive_before[rr, kk, victim[rr, kk]] = True
        self.planted = self.valid & (kt >= self.planted_at[:, None])

    def deaths(self):
        """Per (round, kill): traded within TRADE_MS, and whether the victim
        is alive again later in the round (revived)."""
        v, kr, t = self.victim, self.killer, self.kt
        later = np.arange(MAXK)[None, :, None] > np.arange(MAXK)[None, None, :]   # [j, k]: j after k
        # traded: some later kill j within TRADE_MS kills k's killer, by k's victim's team
        same = (v[:, :, None] == kr[:, None, :]) & (kr[:, None, :] >= 0)
        vteam_att = np.take_along_axis(self.att, np.clip(v, 0, None), 1)
        jkiller_att = np.take_along_axis(self.att, np.clip(kr, 0, None), 1)
        team_ok = jkiller_att[:, :, None] == vteam_att[:, None, :]
        dt = t[:, :, None] - t[:, None, :]
        trade = (same & team_ok & later & (dt <= TRADE_MS) & (dt >= 0)
                 & self.valid[:, :, None] & self.valid[:, None, :]).any(axis=1)
        # revived: the victim listed alive at a later kill
        # va[r, j, k] = alive after kill j of kill k's victim
        va = np.take_along_axis(self.alive, np.clip(v, 0, None)[:, None, :].repeat(MAXK, 1), 2)
        revived = (va & later & self.valid[:, :, None]).any(axis=1) & (v >= 0)
        return trade & (v >= 0), revived


# ----------------------------------------------------------------- multinomial logistic

def mn_fit(X, y, K, pen, w=None):
    """Multinomial logistic, class 0 the reference; returns (p, K-1) coefs."""
    n, p = X.shape
    w = np.ones(n) if w is None else w
    Y = np.eye(K)[y][:, 1:]
    P = np.asarray(pen, float)

    def f(b):
        B = b.reshape(p, K - 1)
        Z = X @ B
        zmax = np.maximum(Z.max(1), 0.0)
        lse = zmax + np.log(np.exp(-zmax) + np.exp(Z - zmax[:, None]).sum(1))
        ll = (w * ((Y * Z).sum(1) - lse)).sum()
        pr = np.exp(Z - lse[:, None])
        g = X.T @ (w[:, None] * (Y - pr))
        obj = -ll + 0.5 * (P[:, None] * B * B).sum()
        return obj, (-g + P[:, None] * B).ravel()

    r = minimize(f, np.zeros(p * (K - 1)), jac=True, method="L-BFGS-B",
                 options={"maxiter": 2000, "gtol": 1e-8})
    return r.x.reshape(p, K - 1)


def mn_prob(X, B):
    Z = np.column_stack([np.zeros(len(X)), X @ B])
    Z -= Z.max(1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(1, keepdims=True)


def ll_rows(P, y):
    return -np.log(np.clip(P[np.arange(len(y)), y], 1e-9, 1.0))


def cluster_ci(diff, groups, boot=2000, seed=0):
    """Mean of per-row `diff`, and a match-cluster bootstrap 95% interval."""
    u, inv = np.unique(groups, return_inverse=True)
    s = np.bincount(inv, weights=diff, minlength=len(u))
    c = np.bincount(inv, minlength=len(u)).astype(float)
    rng = np.random.default_rng(seed)
    dr = rng.integers(0, len(u), (boot, len(u)))
    r = s[dr].sum(1) / c[dr].sum(1)
    lo, hi = np.quantile(r, [0.025, 0.975])
    return {"mean": round(float(s.sum() / c.sum()), 5), "ci95": [round(float(lo), 5), round(float(hi), 5)],
            "matches_better": int((s > 0).sum()), "matches": int(len(u))}


# ----------------------------------------------------------------- V(z)

class Value:
    """winprob_reference's B1 model (alive, load, side, flag), one fit per
    left-out match; V in the attacker's frame."""
    GROUPS = ["alive", "load", "side", "flag"]

    def __init__(self, dev: Dev):
        K = wr.Data(wr.kill_states(dev.rounds), dev.rounds)
        X, self.pen = wr.columns(K.S, K.rounds, self.GROUPS, [])
        self.beta = {sid: wr.fit_logit(X[K.match != sid], K.y[K.match != sid], K.w[K.match != sid], self.pen)
                     for sid in sorted(set(K.match.tolist()))}

    def v(self, sid_arr, a, d, aload, dload, planted):
        S = [{"a": float(x), "d": float(y), "t": 0.0, "planted": bool(p), "tp": 0.0 if p else None,
              "aload": float(al), "dload": float(dl)} for x, y, p, al, dl in zip(a, d, planted, aload, dload)]
        X, _ = wr.columns(S, None, self.GROUPS, [])
        out = np.empty(len(S))
        for sid in np.unique(sid_arr):
            k = sid_arr == sid
            out[k] = wr.sig(X[k] @ self.beta[sid])
        # terminal states
        out = np.where((np.asarray(a) == 0) & ~np.asarray(planted, bool), 0.0, out)
        out = np.where((np.asarray(d) == 0), 1.0, out)
        return out


# ----------------------------------------------------------------- pilot

def episodes(dev: Dev):
    """Every (round, kill, slot) episode with its context and outcome."""
    trade, revived = dev.deaths()
    R = dev.R
    ok = dev.valid[:, :, None] & dev.alive & ~np.isnan(dev.pos[..., 0])
    same_team = dev.att[:, None, :, None] == dev.att[:, None, None, :]              # (R,1,S,S)
    d = np.linalg.norm(dev.pos[:, :, :, None, :] - dev.pos[:, :, None, :, :], axis=-1) / sl.UNITS_PER_M
    mate = same_team & ok[:, :, None, :] & ~np.eye(SLOTS, dtype=bool)[None, None]
    dn = np.where(mate, d, np.inf).min(-1)                                          # (R,K,S)
    has_mate = np.isfinite(dn)
    E = ok & has_mate
    ri, ki, si = np.nonzero(E)
    # outcome: the slot's first death after kill ki within N_MS and before the decision
    later = np.arange(MAXK)[None, :] > ki[:, None]
    tt = dev.kt[ri]
    dies = (dev.victim[ri] == si[:, None]) & later & (tt <= dev.kt[ri, ki][:, None] + N_MS) \
        & (tt < dev.t_dec[ri][:, None]) & dev.valid[ri]
    first = np.where(dies.any(1), dies.argmax(1), -1)
    y = np.zeros(len(ri), int)
    has = first >= 0
    y[has] = np.where(trade[ri[has], first[has]], 2, 1)
    rev = np.zeros(len(ri), bool)
    rev[has] = revived[ri[has], first[has]]
    own_att = dev.att[ri, si]
    al = dev.alive[ri, ki]
    own_m = al & (dev.att[ri] == own_att[:, None])
    en_m = al & ~(dev.att[ri] == own_att[:, None])
    ep = {"ri": ri, "ki": ki, "si": si, "y": y, "revived": rev, "dist": dn[ri, ki, si],
          "own": own_m.sum(1), "enemy": en_m.sum(1),
          "own_load": (dev.econ[ri] * own_m).sum(1), "enemy_load": (dev.econ[ri] * en_m).sum(1),
          "own_att": own_att, "planted": dev.planted[ri, ki], "sid": dev.sid[ri],
          "is_me": si == dev.me_slot[ri], "t": dev.kt[ri, ki], "econ_self": dev.econ[ri, si]}
    keep = ~rev
    return {k: v[keep] for k, v in ep.items()}, int(rev.sum())


def z_cols(ep, with_dist: bool, dist=None):
    n = len(ep["y"])
    cols = [np.ones(n), (ep["own"] - ep["enemy"]) / 5.0, ep["own"] / 5.0,
            (ep["own_load"] - ep["enemy_load"]) / 10000.0, ep["own_att"].astype(float),
            ep["planted"].astype(float), ep["is_me"].astype(float)]
    pen = [0.0, RIDGE, RIDGE, RIDGE, RIDGE, RIDGE, 0.0]
    if with_dist:
        cols.append((ep["dist"] if dist is None else dist) / 10.0)
        pen.append(RIDGE)
    return np.column_stack(cols), pen


ME_COL = 6
DIST_COL = 7


def lomo_mn(ep, X, pen):
    P = np.zeros((len(ep["y"]), 3))
    for sid in np.unique(ep["sid"]):
        k = ep["sid"] == sid
        B = mn_fit(X[~k], ep["y"][~k], 3, pen)
        P[k] = mn_prob(X[k], B)
    return P


def power_recount(dev: Dev) -> dict:
    """The design's power counts, recomputed from the raw records the same
    way (all kills of all rounds; alive = playerLocations), for comparison."""
    n_inst = n_inst_m = deaths = deaths_m = traded = 0
    for sid, d in dev.records.items():
        me = dev.me[sid]
        team = {p["subject"]: p["teamId"] for p in d["match"]["players"]}
        kills = sorted(d["match"]["kills"], key=lambda k: (k["round"], k["roundTime"]))
        for k in kills:
            alive = {p["subject"] for p in k.get("playerLocations") or ()} - {k["victim"]}
            if me in alive:
                n_inst += 1
                n_inst_m += any(team[s] == team[me] for s in alive - {me})
            if k["victim"] == me:
                deaths += 1
                if any(team[s] == team[me] for s in alive):
                    deaths_m += 1
                    traded += any(j["round"] == k["round"] and j["victim"] == k["killer"]
                                  and 0 <= j["roundTime"] - k["roundTime"] <= TRADE_MS
                                  and team.get(j["killer"]) == team[me] for j in kills)
    return {"kill_instants_player_alive": n_inst, "kill_instants_player_alive_with_teammate": n_inst_m,
            "player_deaths": deaths, "deaths_with_living_teammate": deaths_m, "traded_5s_of_those": traded}


def death_quartiles(dev: Dev, trade, who: np.ndarray | None):
    """Trade rate by quartile of the victim's nearest-teammate distance at his death."""
    rr, kk = np.nonzero(dev.valid & (dev.victim >= 0))
    v = dev.victim[rr, kk]
    vp = dev.pos[rr, kk, v]
    mates = dev.alive[rr, kk] & (dev.att[rr] == dev.att[rr, v][:, None]) & ~np.isnan(dev.pos[rr, kk, :, 0])
    dd = np.linalg.norm(dev.pos[rr, kk] - vp[:, None, :], axis=-1) / sl.UNITS_PER_M
    dn = np.where(mates, dd, np.inf).min(1)
    ok = np.isfinite(dn) & ~np.isnan(vp[:, 0])
    if who is not None:
        ok &= v == who[rr]
    dn, tr = dn[ok], trade[rr[ok], kk[ok]]
    q = np.quantile(dn, [0.25, 0.75])
    near, far = tr[dn <= q[0]].mean(), tr[dn >= q[1]].mean()
    return {"deaths": int(ok.sum()), "traded": int(tr.sum()), "q25_m": round(float(q[0]), 1),
            "q75_m": round(float(q[1]), 1), "near_rate": round(float(near), 4), "far_rate": round(float(far), 4),
            "ratio": round(float(near / far), 2) if far > 0 else None}


def stored_allies(sid: str, cache: Path):
    """(t_ms, family 0 ally / 1 self, x_px, y_px, version) from round_entity, cached."""
    cp = cache / f"allies_{sid}.npz"
    if cp.is_file():
        z = np.load(cp)
        return z["t"], z["f"], z["x"], z["y"], str(z["version"])
    path = STORE / "events" / "round_entity" / f"{sid}.jsonl"
    t, f, x, y, ver = [], [], [], [], set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if '"kind":"observation"' not in line:
                continue
            if '"family":"ally"' not in line and '"family":"self"' not in line:
                continue
            r = json.loads(line)
            if r.get("x") is None or r.get("y") is None:
                continue
            ver.add(r.get("round_entity_version"))
            t.append(float(r["t_ms"]))
            f.append(1 if r["family"] == "self" else 0)
            x.append(float(r["x"]))
            y.append(float(r["y"]))
    o = np.argsort(np.asarray(t), kind="stable")
    arr = [np.asarray(v)[o] for v in (t, f, x, y)]
    version = ",".join(sorted(v for v in ver if v))
    cache.mkdir(parents=True, exist_ok=True)
    np.savez(cp, t=arr[0], f=arr[1], x=arr[2], y=arr[3], version=np.array(version))
    return (*arr, version)


def reticle_distances(dev: Dev, ep, mask, why: Counter):
    """Nearest stored ally's distance (m) at the masked episodes; NaN where no
    ally is placed. Self from the stored self icon, else Riot's position."""
    frames = wr.capture_frames(dev.rounds, dev.ref, dev.records, OUT / "cache", why)
    idx = np.flatnonzero(mask)
    out = np.full(len(ep["y"]), np.nan)
    self_src = Counter()
    versions = {}
    for sid in np.unique(ep["sid"][idx]):
        fr = frames.get(sid)
        ii = idx[ep["sid"][idx] == sid]
        if fr is None or fr["mf"] is None:
            why["p4_no_frame"] += len(ii)
            continue
        t, f, x, y, ver = stored_allies(sid, OUT / "cache")
        versions[sid] = ver
        to_game = wr.px_to_game(fr["mf"])
        rstart = np.array([dev.rounds[r]["rstart_game"] if dev.rounds[r]["rstart_game"] is not None else np.nan
                           for r in ep["ri"][ii]])
        ts = fr["a_ms"] + rgt.MINIMAP_LAG_MS + rstart + ep["t"][ii]
        k = np.clip(np.searchsorted(t, ts), 1, len(t) - 1)
        tf = np.where(np.abs(t[k - 1] - ts) <= np.abs(t[k] - ts), t[k - 1], t[k])
        good = np.abs(tf - ts) <= FRAME_TOL_MS
        lo = np.searchsorted(t, tf, "left")
        hi = np.searchsorted(t, tf, "right")
        for j, e in enumerate(ii):  # per episode: a handful of stored icons each
            if not good[j]:
                why["p4_no_frame_within_tol"] += 1
                continue
            sl_ = slice(lo[j], hi[j])
            fam = f[sl_]
            pts = np.array([to_game(px, py) for px, py in zip(x[sl_], y[sl_])]).reshape(-1, 2)
            allies = pts[fam == 0]
            if not len(allies):
                why["p4_no_ally"] += 1
                continue
            me = pts[fam == 1]
            if len(me):
                p0 = me[0]
                self_src["stored_self"] += 1
            else:
                p0 = dev.pos[ep["ri"][e], ep["ki"][e], ep["si"][e]]
                self_src["riot_self"] += 1
            out[e] = np.linalg.norm(allies - p0[None, :], axis=1).min() / sl.UNITS_PER_M
    return out, dict(self_src), versions


def pilot(args) -> dict:
    t0 = time.time()
    dev = Dev()
    V = Value(dev)
    ep, n_rev = episodes(dev)
    trade, _rev = dev.deaths()
    res = {"version": VERSION, "source": source_hash(), "held_out_excluded": len(dev.held_excluded),
           "records": len(dev.records), "admitted_rounds": dev.R,
           "identification": dict(Counter(dev.basis.values())),
           "power_recount": power_recount(dev),
           "episodes": {"all": int(len(ep["y"])), "player": int(ep["is_me"].sum()), "revived_removed": n_rev,
                        "outcomes_all": dict(zip(OUTCOMES, np.bincount(ep["y"], minlength=3).tolist())),
                        "outcomes_player": dict(zip(OUTCOMES, np.bincount(ep["y"][ep["is_me"]], minlength=3).tolist()))}}
    print(json.dumps(res, indent=1))
    X0, pen0 = z_cols(ep, False)
    X1, pen1 = z_cols(ep, True)
    P0 = lomo_mn(ep, X0, pen0)
    P1 = lomo_mn(ep, X1, pen1)
    l0, l1 = ll_rows(P0, ep["y"]), ll_rows(P1, ep["y"])
    me = ep["is_me"]
    res["P2"] = {"z_only_nats": round(float(l0.mean()), 5), "z_dist_nats": round(float(l1.mean()), 5),
                 "improvement": cluster_ci(l0 - l1, ep["sid"]),
                 "player_episodes": cluster_ci((l0 - l1)[me], ep["sid"][me])}
    # full fit and 101 match-bootstrap refits
    B = mn_fit(X1, ep["y"], 3, pen1)
    sids = np.unique(ep["sid"])
    rng = np.random.default_rng(1)
    boots = []
    for _b in range(args.boot):
        pick = rng.choice(sids, len(sids), replace=True)
        rows = np.concatenate([np.flatnonzero(ep["sid"] == s) for s in pick])
        boots.append(mn_fit(X1[rows], ep["y"][rows], 3, pen1))
    boots = np.array(boots)

    def ci(a):
        return [round(float(v), 4) for v in np.quantile(a, [0.025, 0.975])]
    q_all = death_quartiles(dev, trade, None)
    q_me = death_quartiles(dev, trade, dev.me_slot)
    res["P1"] = {"dist_slope_untraded_per_10m": round(float(B[DIST_COL, 0]), 4),
                 "ci95": ci(boots[:, DIST_COL, 0]),
                 "dist_slope_traded_per_10m": round(float(B[DIST_COL, 1]), 4),
                 "ci95_traded": ci(boots[:, DIST_COL, 1]),
                 "quartiles_all": q_all, "quartiles_player": q_me}
    res["P3"] = {"offset_untraded": round(float(B[ME_COL, 0]), 4), "ci95_untraded": ci(boots[:, ME_COL, 0]),
                 "offset_traded": round(float(B[ME_COL, 1]), 4), "ci95_traded": ci(boots[:, ME_COL, 1])}
    # D and M, priced with Delta V
    dv = delta_v(dev, ep, V)
    band = ~me
    key = ep["own"] * 10 + ep["enemy"]
    ref_d = np.full(len(key), np.nan)
    for kk in np.unique(key):
        m = band & (key == kk)
        if m.any():
            ref_d[key == kk] = np.median(ep["dist"][m])
    ref_d = np.where(np.isnan(ref_d), np.median(ep["dist"][band]), ref_d)

    def dm(Bm):
        Xb, _ = z_cols(ep, True)
        Xb[:, ME_COL] = 0.0
        Xr, _ = z_cols(ep, True, ref_d)
        Xr[:, ME_COL] = 0.0
        Xm = Xb.copy()
        Xm[:, ME_COL] = 1.0
        Pb, Pr, Pm = mn_prob(Xb, Bm), mn_prob(Xr, Bm), mn_prob(Xm, Bm)
        return ((Pb - Pr) * dv).sum(1), ((Pm - Pb) * dv).sum(1)
    D, M = dm(B)
    DB = np.array([dm(b)[0][me] for b in boots])
    MB = np.array([dm(b)[1][me] for b in boots])
    agree_d = (np.sign(DB) == np.sign(D[me])[None, :]).mean(0)
    res["D_M"] = {"player_episodes": int(me.sum()),
                  "mean_D_wp": round(float(D[me].mean()), 5), "ci95_mean_D": ci(DB.mean(1)),
                  "mean_M_wp": round(float(M[me].mean()), 5), "ci95_mean_M": ci(MB.mean(1)),
                  "confident_share_D_0.83": round(float((agree_d >= 0.83).mean()), 4),
                  "c_ref": "band median nearest-teammate distance at the same own and enemy alive counts",
                  "propensity_guard": "not built (S2)"}
    # P4: reticle's stored teammate positions at the player's episode instants
    why = Counter()
    rd, self_src, versions = reticle_distances(dev, ep, me, why)
    placed = me & ~np.isnan(rd)
    res["P4"] = {"stream": "round_entity (families ally, self)",
                 "versions": sorted(set(versions.values())),
                 "player_episodes": int(me.sum()), "placed": int(placed.sum()),
                 "share_placed": round(float(placed.sum() / max(1, me.sum())), 4),
                 "self_source": self_src, "why": dict(why)}
    # second line: the player's deaths with a living teammate
    dth = me & (ep["y"] > 0)
    rd_death = death_instant_share(dev, trade, why)
    res["P4"]["deaths_line"] = rd_death
    # model on reticle positions vs record positions, at placed episodes
    if placed.any():
        Pr = np.zeros((len(ep["y"]), 3))
        Xr, _ = z_cols(ep, True, np.where(placed, rd, ep["dist"]))
        for sid in np.unique(ep["sid"][placed]):
            k = ep["sid"] == sid
            Bk = mn_fit(X1[~k], ep["y"][~k], 3, pen1)
            Pr[k] = mn_prob(Xr[k], Bk)
        lr = ll_rows(Pr, ep["y"])
        res["P4"]["record_nats"] = round(float(l1[placed].mean()), 5)
        res["P4"]["reticle_nats"] = round(float(lr[placed].mean()), 5)
        res["P4"]["reticle_minus_record"] = cluster_ci((lr - l1)[placed], ep["sid"][placed])
        res["P4"]["dist_abs_err_median_m"] = round(float(np.median(np.abs(rd - ep["dist"])[placed])), 2)
    del dth
    res["verdicts"] = {
        "P1": bool(res["P1"]["dist_slope_untraded_per_10m"] > 0 and res["P1"]["ci95"][0] > 0
                   and (q_all["ratio"] or 0) >= 2.0),
        "P1_quartile_band": "held" if (q_all["ratio"] or 0) >= 2.0 else ("fails" if (q_all["ratio"] or 0) < 1.5 else "between"),
        "P2": bool(res["P2"]["improvement"]["mean"] >= 0.01 and res["P2"]["improvement"]["ci95"][0] > 0),
        "P3": bool(res["P3"]["ci95_untraded"][0] <= 0 <= res["P3"]["ci95_untraded"][1]
                   and res["P3"]["ci95_traded"][0] <= 0 <= res["P3"]["ci95_traded"][1]),
        "P4_share": bool(res["P4"]["share_placed"] >= 0.70),
        "P4_model": bool(abs(res["P4"].get("reticle_minus_record", {}).get("mean", 1.0)) <= 0.005)}
    res["seconds"] = round(time.time() - t0, 1)
    print(json.dumps({k: res[k] for k in ("P1", "P2", "P3", "D_M", "P4", "verdicts")}, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pilot.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if args.record:
        record_pilot(res)
    return res


def death_instant_share(dev: Dev, trade, why: Counter) -> dict:
    """P4's second line: at the player's deaths with a living teammate, the
    share where reticle places at least one living ally."""
    rr, kk = np.nonzero(dev.valid & (dev.victim >= 0) & (dev.victim == dev.me_slot[:, None]))
    v = dev.victim[rr, kk]
    mates = dev.alive[rr, kk] & (dev.att[rr] == dev.att[rr, v][:, None])
    ok = mates.any(1)
    rr, kk, v = rr[ok], kk[ok], v[ok]
    ep = {"ri": rr, "ki": kk, "si": v, "sid": dev.sid[rr], "t": dev.kt[rr, kk], "y": np.zeros(len(rr), int)}
    rd, _src, _ver = reticle_distances(dev, ep, np.ones(len(rr), bool), why)
    return {"deaths_with_living_teammate": int(len(rr)), "placed": int((~np.isnan(rd)).sum()),
            "share_placed": round(float((~np.isnan(rd)).mean()), 4) if len(rr) else None}


def delta_v(dev: Dev, ep, V: Value) -> np.ndarray:
    """(n, 3) change in the episode side's win probability per outcome."""
    own_att = ep["own_att"]
    a = np.where(own_att, ep["own"], ep["enemy"])
    d = np.where(own_att, ep["enemy"], ep["own"])
    al = np.where(own_att, ep["own_load"], ep["enemy_load"])
    dl = np.where(own_att, ep["enemy_load"], ep["own_load"])
    pl = ep["planted"]
    sid = ep["sid"]
    v0 = V.v(sid, a, d, al, dl, pl)
    mean_enemy = ep["enemy_load"] / np.maximum(ep["enemy"], 1)
    # untraded: own side loses the player
    a1 = a - own_att
    d1 = d - ~own_att
    al1 = al - np.where(own_att, ep["econ_self"], 0.0)
    dl1 = dl - np.where(~own_att, ep["econ_self"], 0.0)
    v1 = V.v(sid, a1, d1, al1, dl1, pl)
    # traded: both sides lose one
    a2 = a1 - ~own_att
    d2 = d1 - own_att
    al2 = al1 - np.where(~own_att, mean_enemy, 0.0)
    dl2 = dl1 - np.where(own_att, mean_enemy, 0.0)
    v2 = V.v(sid, a2, d2, al2, dl2, pl)
    sgn = np.where(own_att, 1.0, -1.0)
    return np.column_stack([np.zeros(len(a)), sgn * (v1 - v0), sgn * (v2 - v0)])


def record_pilot(res: dict) -> None:
    from reticle import metrics
    vals = {"episodes": res["episodes"]["all"], "player_episodes": res["episodes"]["player"],
            "revived_removed": res["episodes"]["revived_removed"],
            "P1.slope_untraded_per_10m": res["P1"]["dist_slope_untraded_per_10m"],
            "P1.quartile_ratio_all": res["P1"]["quartiles_all"]["ratio"],
            "P1.quartile_ratio_player": res["P1"]["quartiles_player"]["ratio"],
            "P2.z_only_nats": res["P2"]["z_only_nats"], "P2.z_dist_nats": res["P2"]["z_dist_nats"],
            "P2.improvement_nats": res["P2"]["improvement"]["mean"],
            "P3.offset_untraded": res["P3"]["offset_untraded"], "P3.offset_traded": res["P3"]["offset_traded"],
            "D.mean_wp": res["D_M"]["mean_D_wp"], "M.mean_wp": res["D_M"]["mean_M_wp"],
            "D.confident_share": res["D_M"]["confident_share_D_0.83"],
            "P4.share_placed": res["P4"]["share_placed"],
            "P4.deaths_share_placed": res["P4"]["deaths_line"]["share_placed"]}
    if "reticle_minus_record" in res["P4"]:
        vals["P4.reticle_minus_record_nats"] = res["P4"]["reticle_minus_record"]["mean"]
    vals.update({f"recount.{k}": v for k, v in res["power_recount"].items()})
    ci = {"P1.slope_untraded_per_10m": res["P1"]["ci95"], "P2.improvement_nats": res["P2"]["improvement"]["ci95"],
          "P3.offset_untraded": res["P3"]["ci95_untraded"], "P3.offset_traded": res["P3"]["ci95_traded"],
          "D.mean_wp": res["D_M"]["ci95_mean_D"], "M.mean_wp": res["D_M"]["ci95_mean_M"]}
    if "reticle_minus_record" in res["P4"]:
        ci["P4.reticle_minus_record_nats"] = res["P4"]["reticle_minus_record"]["ci95"]
    metrics.record("decision_value", part="pilot", values=vals, ci=ci,
                   deps={"version": VERSION, "source": res["source"], "value_model": wr.VERSION + " B1",
                         "N_ms": N_MS, "trade_ms": TRADE_MS, "ridge": RIDGE, "boot": 101,
                         "p4_stream": res["P4"]["stream"], "p4_versions": res["P4"]["versions"]},
                   context={"set": "development: 22 captured Riot records, admitted rounds",
                            "held_out_excluded": res["held_out_excluded"]},
                   note="S0 pilot of docs/COACHING_DECISION_VALUE.md section 7; leave one match out")


# ----------------------------------------------------------------- reach

class Fights:
    """Development-set gun kills between opposite teams, with each side's
    duelist and other living players."""

    def __init__(self, dev: Dev):
        ok = dev.valid & dev.weapon & (dev.killer >= 0) & (dev.victim >= 0)
        rr, kk = np.nonzero(ok)
        kl, vi = dev.killer[rr, kk], dev.victim[rr, kk]
        opp = dev.att[rr, kl] != dev.att[rr, vi]
        pk = dev.pos[rr, kk, kl]
        have = opp & ~np.isnan(pk[:, 0]) & ~np.isnan(dev.pos[rr, kk, vi, 0])
        rr, kk, kl, vi = rr[have], kk[have], kl[have], vi[have]
        self.dropped = int((~have).sum())
        self.rr, self.kk = rr, kk
        self.map = dev.map[rr]
        self.sid = dev.sid[rr]
        self.y = dev.att[rr, kl].astype(float)          # the attacking duelist won
        before = dev.alive_before[rr, kk]
        self.a = (before & dev.att[rr]).sum(1)
        self.d = (before & ~dev.att[rr]).sum(1)
        self.planted = dev.planted[rr, kk]
        self.t = dev.kt[rr, kk] / 1000.0
        att_duel = np.where(dev.att[rr, kl], kl, vi)
        def_duel = np.where(dev.att[rr, kl], vi, kl)
        self.duel = {"att": att_duel, "def": def_duel}
        P = dev.pos[rr, kk]                                # (F, 10, 2)
        self.P = P
        self.side_mask = {}
        for side in ("att", "def"):
            m = before & (dev.att[rr] if side == "att" else ~dev.att[rr])
            m[np.arange(len(rr)), kl] = False
            m[np.arange(len(rr)), vi] = False
            m &= ~np.isnan(P[..., 0])
            self.side_mask[side] = m
        self.n = len(rr)

    def baseline(self):
        a, d = self.a.astype(float), self.d.astype(float)
        cols = [np.ones(self.n), (a - d) / 5.0, (a - d) / np.maximum(a + d, 1.0), self.planted.astype(float)]
        pre = ~self.planted
        for lo in TIME_BINS:
            cols.append((pre & (self.t >= lo)).astype(float))
        pen = [0.0] + [RIDGE] * (len(cols) - 1)
        return np.column_stack(cols), pen


def reach_features(F: Fights, P=None, loader=None, graphs=GRAPHS) -> dict:
    """Per side, the other players' reach measures: walk metres to the nearest
    cell seeing the opposing duelist, region adjacency, and distance to the
    own duelist. Returns arrays (F, 10) with inf / False where no player.
    `loader(map)` gives the map's table (default `sightlines.load`); a map
    it returns None for keeps inf / False."""
    P = F.P if P is None else P
    loader = sl.load if loader is None else loader
    out = {side: {"reach": np.full((F.n, SLOTS), np.inf), "eu": np.full((F.n, SLOTS), np.inf),
                  "node_callout": np.zeros((F.n, SLOTS), bool), "node_sight": np.zeros((F.n, SLOTS), bool)}
           for side in ("att", "def")}
    for mname in np.unique(F.map):
        S = loader(mname)
        if S is None:
            continue
        fm = np.flatnonzero(F.map == mname)
        for side, other in (("att", "def"), ("def", "att")):
            ds = F.duel[side][fm]
            do = F.duel[other][fm]
            pS = F.P[fm, ds]          # duelists keep their real positions
            pO = F.P[fm, do]
            cS = S.cells(pS)[0]
            cO = S.cells(pO)[0]
            vis = S.vis_near(pO)      # (f, N)
            m = F.side_mask[side][fm]
            fi, sj = np.nonzero(m)
            pts = P[fm[fi], sj]
            cp = S.cells(pts)[0]
            rch = np.empty(len(fi))
            for b0 in range(0, len(fi), 1024):
                b = slice(b0, b0 + 1024)
                rch[b] = S.reach_m(cp[b], vis[fi[b]])
            o = out[side]
            o["reach"][fm[fi], sj] = rch
            o["eu"][fm[fi], sj] = np.linalg.norm(pts - pS[fi], axis=1) / sl.UNITS_PER_M
            for g in graphs:
                o[f"node_{g}"][fm[fi], sj] = S.near_region(g, cp, cS[fi]) | S.near_region(g, cp, cO[fi])
    return out


def family_cols(feat: dict, family: str, param) -> np.ndarray:
    cols = []
    for side in ("att", "def"):
        f = feat[side]
        if family in ("swing", "trade"):
            v = (f["reach"] <= param).sum(1)
        elif family == "node":
            v = f[f"node_{param}"].sum(1)
        elif family == "radius":
            v = (f["eu"] <= param).sum(1)
        else:
            raise ValueError(family)
        cols.append(v / 4.0)
    return np.column_stack(cols)


def lomo_logit(X, y, groups, pen):
    p = np.zeros(len(y))
    for g in np.unique(groups):
        k = groups == g
        beta = wr.fit_logit(X[~k], y[~k], np.ones(int((~k).sum())), pen)
        p[k] = wr.sig(X[k] @ beta)
    return p


def bin_ll(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def shuffle_positions(F: Fights, rng) -> np.ndarray:
    """Each side's other players' positions permuted among fights of the same
    map, side and count; duelists untouched."""
    P = F.P.copy()
    for side in ("att", "def"):
        m = F.side_mask[side]
        cnt = m.sum(1)
        for mname in np.unique(F.map):
            for c in np.unique(cnt):
                fr = np.flatnonzero((F.map == mname) & (cnt == c))
                if len(fr) < 2 or c == 0:
                    continue
                perm = rng.permutation(fr)
                src = F.P[perm][m[perm]].reshape(len(fr), c, 2)
                dst_rows = np.repeat(fr, c)
                dst_cols = np.nonzero(m[fr])[1]
                P[dst_rows, dst_cols] = src.reshape(-1, 2)
    return P


def reach(args) -> dict:
    t0 = time.time()
    dev = Dev()
    F = Fights(dev)
    Xb, penb = F.baseline()
    y = F.y
    pb = lomo_logit(Xb, y, F.sid, penb)
    lb = bin_ll(pb, y)
    feat = reach_features(F)
    grid = {"swing": SWING_S, "trade": TRADE_T, "node": GRAPHS, "radius": RADIUS_R}
    res = {"version": VERSION, "source": source_hash(), "held_out_excluded": len(dev.held_excluded),
           "fights": F.n, "fights_dropped_no_position": F.dropped, "matches": int(len(np.unique(F.sid))),
           "attacker_duel_win_rate": round(float(y.mean()), 4),
           "baseline_nats": round(float(lb.mean()), 5), "families": {}, "chosen": {}}
    best_ll = {}
    for fam, params in grid.items():
        res["families"][fam] = {}
        for prm in params:
            X = np.column_stack([Xb, family_cols(feat, fam, prm)])
            pen = penb + [RIDGE, RIDGE]
            p = lomo_logit(X, y, F.sid, pen)
            lf = bin_ll(p, y)
            beta = wr.fit_logit(X, y, np.ones(len(y)), pen)
            res["families"][fam][str(prm)] = {"nats": round(float(lf.mean()), 5),
                                              "improvement": cluster_ci(lb - lf, F.sid),
                                              "coef_att": round(float(beta[-2]), 4),
                                              "coef_def": round(float(beta[-1]), 4),
                                              "mean_att": round(float(X[:, -2].mean() * 4), 3),
                                              "mean_def": round(float(X[:, -1].mean() * 4), 3)}
            if fam not in best_ll or lf.mean() < best_ll[fam][0]:
                best_ll[fam] = (lf.mean(), prm, lf)
        res["chosen"][fam] = best_ll[fam][1]
    # node: the better graph is the chosen region graph
    # the player's claim: sightline families against the radius
    for fam in ("swing", "trade", "node"):
        res[f"{fam}_vs_radius"] = cluster_ci(best_ll["radius"][2] - best_ll[fam][2], F.sid)
    # position-shuffle null at the chosen parameters
    rng = np.random.default_rng(11)
    null = defaultdict(list)
    for _i in range(args.shuffles):
        Ps = shuffle_positions(F, rng)
        fs = reach_features(F, Ps)
        for fam in grid:
            X = np.column_stack([Xb, family_cols(fs, fam, res["chosen"][fam])])
            p = lomo_logit(X, y, F.sid, penb + [RIDGE, RIDGE])
            null[fam].append(float((lb - bin_ll(p, y)).mean()))
    res["shuffle_null"] = {fam: {"mean": round(float(np.mean(v)), 5),
                                 "p95": round(float(np.quantile(v, 0.95)), 5),
                                 "observed": round(float((lb - best_ll[fam][2]).mean()), 5),
                                 "share_null_ge_observed": round(float(np.mean(np.array(v) >= (lb - best_ll[fam][2]).mean())), 3),
                                 "n": len(v)}
                           for fam, v in null.items()}
    res["plant"] = plant_model(dev, args)
    res["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(res, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reach.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if args.record:
        record_reach(res)
    return res


def plant_features(dev: Dev, loader=None) -> dict:
    """Per planted round with `plantPlayerLocations`: alive counts and plant
    time at the plant, the winner, and each listed player's walk metres to a
    cell that sees the spike (`reach_m`) and path metres to the spike's cell
    (`path_m`), with `is_att` and `present` masks (n, 10). Maps the loader
    returns None for keep inf."""
    loader = sl.load if loader is None else loader
    rows = []
    for ri, rd in enumerate(dev.rounds):
        if rd["planted_at"] is None:
            continue
        rr = next(r for r in dev.records[rd["sid"]]["match"]["roundResults"] if r["roundNum"] == rd["round"])
        locs = rr.get("plantPlayerLocations") or []
        pl = rr.get("plantLocation")
        if not locs or not pl:
            continue
        rows.append((ri, locs, (pl["x"], pl["y"])))
    n = len(rows)
    ri = np.array([r[0] for r in rows])
    st = [wr.state_at(dev.rounds[i], dev.rounds[i]["planted_at"]) for i in ri]
    a = np.array([s["a"] for s in st], float)
    d = np.array([s["d"] for s in st], float)
    tp = np.array([dev.rounds[i]["planted_at"] for i in ri]) / 1000.0
    y = dev.y_round[ri].astype(float)
    sid = dev.sid[ri]
    reach_m = np.full((n, SLOTS), np.inf)
    path_m = np.full((n, SLOTS), np.inf)
    is_att = np.zeros((n, SLOTS), bool)
    present = np.zeros((n, SLOTS), bool)
    # flat (planted row, slot, x, y, attacker) of every listed player
    fj, fs, fxy, fatt = [], [], [], []
    for j, (r_i, locs, _pl) in enumerate(rows):  # parse: one record's listed players
        r0 = dev.rounds[r_i]
        idx = {s_: k for k, s_ in enumerate(dev.subjects[r_i])}
        for p in locs:
            if p["subject"] in idx:
                fj.append(j)
                fs.append(idx[p["subject"]])
                fxy.append((p["location"]["x"], p["location"]["y"]))
                fatt.append(r0["team_of"][p["subject"]] == r0["att_team"])
    fj, fs = np.array(fj, np.int64), np.array(fs, np.int64)
    fxy, fatt = np.array(fxy, float).reshape(-1, 2), np.array(fatt, bool)
    is_att[fj, fs] = fatt
    present[fj, fs] = True
    spike_all = np.array([r[2] for r in rows], float).reshape(-1, 2)
    for mname in np.unique(dev.map[ri]):
        S = loader(mname)
        if S is None:
            continue
        fm = np.flatnonzero(dev.map[ri] == mname)
        cs = S.cells(spike_all[fm])[0]
        vis = S.vis_near(spike_all[fm])
        local = np.full(n, -1, np.int64)
        local[fm] = np.arange(len(fm))
        k = np.flatnonzero(local[fj] >= 0)
        cp = S.cells(fxy[k])[0]
        li = local[fj[k]]
        for b0 in range(0, len(k), 1024):
            b = slice(b0, b0 + 1024)
            reach_m[fj[k[b]], fs[k[b]]] = S.reach_m(cp[b], vis[li[b]])
        path_m[fj[k], fs[k]] = S.dist_m(cp, cs[li])
    return {"ri": ri, "n": n, "a": a, "d": d, "tp": tp, "y": y, "sid": sid, "map": dev.map[ri],
            "reach_m": reach_m, "path_m": path_m, "is_att": is_att, "present": present}


def plant_model(dev: Dev, args) -> dict:
    """Round winner at the plant: alive counts and plant time, plus reach to
    the spike's sightlines and the defenders' mean path distance."""
    pf = plant_features(dev)
    n, a, d, tp, y, sid = pf["n"], pf["a"], pf["d"], pf["tp"], pf["y"], pf["sid"]
    reach_m, path_m, is_att, present = pf["reach_m"], pf["path_m"], pf["is_att"], pf["present"]
    deff = present & ~is_att
    md = np.where(deff, np.minimum(path_m, 150.0), 0.0).sum(1) / np.maximum(deff.sum(1), 1)
    base = [np.ones(n), (a - d) / 5.0, (a - d) / np.maximum(a + d, 1.0), tp / 100.0]
    Xb = np.column_stack(base)
    penb = [0.0, RIDGE, RIDGE, RIDGE]
    lb = bin_ll(lomo_logit(Xb, y, sid, penb), y)
    out = {"planted_rounds": n, "baseline_nats": round(float(lb.mean()), 5), "by_t": {}}
    Xd = np.column_stack([Xb, md / 50.0])
    ld = bin_ll(lomo_logit(Xd, y, sid, penb + [RIDGE]), y)
    out["def_mean_path"] = {"nats": round(float(ld.mean()), 5), "improvement": cluster_ci(lb - ld, sid),
                            "mean_m": round(float(md.mean()), 1)}
    best = None
    for t in PLANT_T:
        cols = [((reach_m <= t) & is_att & present).sum(1) / 5.0, ((reach_m <= t) & deff).sum(1) / 5.0]
        X = np.column_stack([Xb] + cols + [md / 50.0])
        pen = penb + [RIDGE] * 3
        lt = bin_ll(lomo_logit(X, y, sid, pen), y)
        out["by_t"][str(t)] = {"nats": round(float(lt.mean()), 5), "improvement": cluster_ci(lb - lt, sid)}
        if best is None or lt.mean() < best[0]:
            best = (lt.mean(), t, X, pen)
    out["chosen_t"] = best[1]
    X, pen = best[2], best[3]
    beta = wr.fit_logit(X, y, np.ones(n), pen)
    sids = np.unique(sid)
    rng = np.random.default_rng(3)
    bs = []
    for _b in range(101):
        pick = rng.choice(sids, len(sids), replace=True)
        rows_b = np.concatenate([np.flatnonzero(sid == s) for s in pick])
        bs.append(wr.fit_logit(X[rows_b], y[rows_b], np.ones(len(rows_b)), pen))
    bs = np.array(bs)
    names = ["intercept", "alive_diff", "alive_ratio", "plant_time", "att_reach", "def_reach", "def_mean_path_per_50m"]
    out["coefficients"] = {nm: {"beta": round(float(b), 4),
                                "ci95": [round(float(v), 4) for v in np.quantile(bs[:, i], [0.025, 0.975])]}
                           for i, (nm, b) in enumerate(zip(names, beta))}
    return out


def record_reach(res: dict) -> None:
    from reticle import metrics
    vals = {"fights": res["fights"], "baseline_nats": res["baseline_nats"]}
    ci = {}
    for fam, d in res["families"].items():
        for prm, b in d.items():
            vals[f"{fam}@{prm}.improvement_nats"] = b["improvement"]["mean"]
            ci[f"{fam}@{prm}.improvement_nats"] = b["improvement"]["ci95"]
    for fam in ("swing", "trade", "node"):
        vals[f"{fam}_vs_radius.nats"] = res[f"{fam}_vs_radius"]["mean"]
        ci[f"{fam}_vs_radius.nats"] = res[f"{fam}_vs_radius"]["ci95"]
    for fam, b in res["shuffle_null"].items():
        vals[f"null:{fam}.mean"] = b["mean"]
        vals[f"null:{fam}.p95"] = b["p95"]
    pm = res["plant"]
    vals.update({"plant.rounds": pm["planted_rounds"], "plant.baseline_nats": pm["baseline_nats"],
                 "plant.def_mean_path.improvement_nats": pm["def_mean_path"]["improvement"]["mean"],
                 "plant.chosen_t": pm["chosen_t"],
                 "plant.best.improvement_nats": pm["by_t"][str(pm["chosen_t"])]["improvement"]["mean"],
                 "plant.coef.def_mean_path_per_50m": pm["coefficients"]["def_mean_path_per_50m"]["beta"]})
    ci["plant.coef.def_mean_path_per_50m"] = pm["coefficients"]["def_mean_path_per_50m"]["ci95"]
    ci["plant.best.improvement_nats"] = pm["by_t"][str(pm["chosen_t"])]["improvement"]["ci95"]
    metrics.record("decision_value", part="reach", values=vals, ci=ci,
                   deps={"version": VERSION, "source": res["source"], "sightlines": sl.VERSION,
                         "grids": {"swing": SWING_S, "trade": TRADE_T, "radius": RADIUS_R, "plant_t": PLANT_T},
                         "ridge": RIDGE, "time_bins": TIME_BINS},
                   context={"set": "development: 22 captured Riot records, admitted rounds, gun kills",
                            "chosen": res["chosen"], "held_out_excluded": res["held_out_excluded"]},
                   note="label-symmetric reach features; leave one match out; parameters chosen on this log loss")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pilot")
    p.add_argument("--record", action="store_true")
    p.add_argument("--boot", type=int, default=101)
    r = sub.add_parser("reach")
    r.add_argument("--record", action="store_true")
    r.add_argument("--shuffles", type=int, default=20)
    args = ap.parse_args(argv)
    _below_normal()
    if args.cmd == "pilot":
        pilot(args)
    else:
        reach(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
