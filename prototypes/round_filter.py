r"""Round win probability from stored events: a causal round-state filter.

    .\.venv\Scripts\python.exe prototypes\round_filter.py [--record] [--out DIR] [--boot N]

Why this exists
---------------
Stage 1 of the win-probability roadmap: the smallest end-to-end test. The
reference fit (`prototypes/winprob_reference.py`) scores round win
probability on Riot's exact state. This file asks what the same outcome model
scores when the state comes from reticle's stored events instead, with the
uncertainty those events carry, at the same instants. It decodes nothing and
reads no reader; it reads the death stream, the stored rounds, the roster
through its owner (`roster.resolve`) and in-game time through its owner
(`gametime`), and Riot's records for truth.

The state
---------
z = (allies alive, enemies alive), a 6 x 6 joint distribution, plus the plant
flag. Each instant's distribution is built forward from the round's start
using only claims observed at or before it (`t_ms`, the claim's observation
time), so the filter is causal in observation time.

Start. The roster read at `gametime`'s barrier drop, mapped per side through
P(Riot start count | read), counted on the other captured matches. An unread
start takes the Riot start marginal. (Admitted rounds start five against
five by construction: the reference drops rounds with an absent player.)

Claims. Every row of the death stream that could change a count is a claim:
`death_verdict` (classed below), `refused_entry`, `merged_entry` and
`inferred_death`. No claim carries a probability that its death happened, so
each class's outcome probabilities are measured against Riot on the OTHER
captured matches (leave one match out): kill-like claims are matched one to
one with Riot kills within `rgt.MATCH_TOL_MS` under the session's alignment,
and the claim's outcome is the matched victim's side (claimed side, the
other side, or no kill). A revive claim's outcome is whether Riot's living
sets show a revival on its side across it. An `inferred_death` (no instant;
it died in a capture stall) enters at the end of its window and is right when
an unmatched Riot kill of its side lies inside the window. A class with no
training claims enters as missing at random: it changes nothing and the
instant counts it (`unrated`). Refusals stay visible: a refused or
unresolved claim enters with its class's measured outcome probabilities, so
its instant is scored with that uncertainty, never dropped.

Classes, from stored fields only: `revive`; `entry_refused` (entry type
refused); `second_life`; `side_unknown`; `kill_unresolved` (victim status
not resolved); `kill_resolved`; `refused_entry`; `merged_entry`;
`inferred_death`.

Plant. The stored round table (`round-bounds`): planted when the plant time
precedes the instant. An unread plant (`spike_planted` null, or planted with
no time) mixes the flag with the Riot rate of planted-by-t on the other
matches.

Side. Riot's. Reticle has no owner for which team attacks; this is the one
input still taken from Riot, and the gap is stated, not hidden.

Outcome model. The reference's ridge logistic on alive, side and the plant
flag (no clock, no loadout), fitted on Riot's 1 s grid states, leave one
match out: `winprob_reference.lomo`. P(win) = sum over z of P(win | z) P(z).
The oracle is the same model on Riot's exact state at the same instants;
their difference is the observation cost.

Instants. Riot's 1 s grid (`winprob_reference.grid_states`) of the captured
matches, mapped to capture time by `rgt.fit_alignment` (the death stream's
own fit, so claims compare at `a_ms + gameTime`); the round table and roster
compare `rgt.MINIMAP_LAG_MS` later, as the reference does.

Result (0.1.0, 21 matches)
--------------------------
Every captured instant is scored
[metric:round_filter/riot_G#share_of_captured=1.0]. The filter scores
[metric:round_filter/riot_G#filter_nats=0.50747] nats against the oracle's
[metric:round_filter/riot_G#oracle_nats=0.50219]: an observation cost of
[metric:round_filter/riot_G#cost_nats=0.00528] nats, whose match-bootstrap
interval includes zero. The mixture beats plugging in the most probable state
by [metric:round_filter/riot_G#mixture_gain_nats=0.00217] nats. Resolved kill
claims decrement the claimed side on
[metric:round_filter/riot_G#claims_kill_resolved_first=0.993] of matches.
`results.json` carries the reliability bins, the refusal-touched instants
scored apart and where the most probable state goes wrong.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import riot_ground_truth as rgt  # noqa: E402
import winprob_reference as wr  # noqa: E402

VERSION = "round-filter-0.1.0"
STORE = wr.STORE
#: The reference outcome model the filter feeds: alive, side, plant flag.
SPEC = ["alive", "side", "flag"]
#: How long after the barrier drop a start read may come.
START_READ_MS = 3000.0
N = 6  # alive counts 0..5
CLASSES = ("kill_resolved", "kill_unresolved", "side_unknown", "second_life", "entry_refused",
           "refused_entry", "merged_entry", "inferred_death", "revive")
#: Classes whose claims a Riot kill can match one to one.
POOL = ("kill_resolved", "kill_unresolved", "side_unknown", "second_life", "entry_refused",
        "refused_entry", "merged_entry")
#: Classes that are not a resolved kill; an instant after one carries its uncertainty.
UNCERTAIN = ("kill_unresolved", "side_unknown", "entry_refused", "refused_entry", "inferred_death")
LN2 = math.log(2.0)


def _below_normal():
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


# ----------------------------------------------------------------- claims

def claim_class(r: dict) -> str | None:
    kind = r.get("kind")
    if kind == "refused_entry":
        return "refused_entry"
    if kind == "merged_entry":
        return "merged_entry"
    if kind == "inferred_death":
        return "inferred_death"
    if kind != "death_verdict":
        return None
    if r.get("is_revive"):
        return "revive"
    if (r.get("entry_type") or {}).get("status") == "refused":
        return "entry_refused"
    if r.get("is_second_life"):
        return "second_life"
    if r.get("side") not in ("ally", "enemy"):
        return "side_unknown"
    if r.get("status") != "resolved":
        return "kill_unresolved"
    return "kill_resolved"


def stored_claims(sid: str, why: Counter) -> list[dict]:
    """The death stream's count-changing rows, with class, side (0 ally, 1
    enemy, -1 unknown) and the time each enters the filter."""
    out = []
    path = STORE / "events" / "death" / f"{sid}.jsonl"
    versions = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            c = claim_class(r)
            if r.get("kind") == "inferred_death_refusal":
                why["claims_inferred_refusal_rows"] += 1
            if c is None:
                continue
            versions.add(r.get("death_adjudication_version"))
            side = {"ally": 0, "enemy": 1}.get(r.get("side"), -1)
            if c == "inferred_death":
                w = r.get("t_window_ms") or [None, None]
                t, win = w[1], w
            else:
                t, win = r.get("t_ms"), None
            if t is None:
                why[f"claims_no_time:{c}"] += 1
                continue
            out.append({"t": float(t), "cls": c, "side": side, "round_no": r.get("round_no"),
                        "window": win, "id": r.get("death_id")})
            why[f"claims:{c}"] += 1
    out.sort(key=lambda c: c["t"])
    return out, sorted(v for v in versions if v)


def riot_truth(sid: str, d: dict, frame: dict, adm_by_sid: dict) -> dict:
    """Riot's kills (store time, victim side) and revivals (store-time windows, side)."""
    team_of = {p["subject"]: p["teamId"] for p in d["match"]["players"]}
    me = frame["team"]
    a = frame["a_ms"]
    kills = [{"t": a + float(k["gameTime"]), "side": 0 if team_of.get(k["victim"]) == me else 1}
             for k in d["match"]["kills"]]
    revivals = []
    for rd in adm_by_sid.get(sid, []):
        if rd["rstart_game"] is None:
            continue
        prev_alive, prev_t = set(rd["team_of"]), 0.0
        for ks in rd["kstates"]:
            for s in ks["alive"] - prev_alive:
                revivals.append({"t0": a + rd["rstart_game"] + prev_t, "t1": a + rd["rstart_game"] + ks["t"],
                                 "side": 0 if team_of.get(s) == me else 1})
            prev_alive, prev_t = ks["alive"], ks["t"]
    return {"kills": kills, "revivals": revivals}


def score_claims(claims: list[dict], truth: dict, tol: float) -> tuple[list[int], dict]:
    """Per claim its Riot outcome: for a known side 0 same, 1 other, 2 none;
    for an unknown side 0 ally, 1 enemy, 2 none; for a revive 0 revival on
    its side, 2 none. Also Riot kill recall."""
    out = [2] * len(claims)
    rk = truth["kills"]
    used, done = set(), set()
    # same side first, so a nearby kill of the other side never takes a
    # claim's own kill; then whatever is left, across sides
    for side in (0, 1, None):
        pool = [j for j, c in enumerate(claims)
                if c["cls"] in POOL and j not in done and (side is None or c["side"] == side)]
        ks = [i for i, k in enumerate(rk) if i not in used and (side is None or k["side"] == side)]
        pairs = rgt.match_times([rk[i]["t"] for i in ks], [claims[j]["t"] for j in pool], 0.0, tol_ms=tol)
        for ii, jj, _dt in pairs:
            i, j = ks[ii], pool[jj]
            used.add(i)
            done.add(j)
            vs, cs = rk[i]["side"], claims[j]["side"]
            out[j] = vs if cs < 0 else (0 if vs == cs else 1)
    for j, c in enumerate(claims):
        if c["cls"] == "inferred_death":
            lo, hi = c["window"]
            hit = next((i for i, k in enumerate(rk) if i not in used and k["side"] == c["side"]
                        and lo - tol <= k["t"] <= hi + tol), None)
            if hit is not None:
                used.add(hit)
                out[j] = 0
        elif c["cls"] == "revive":
            if any(v["side"] == c["side"] and v["t0"] - tol <= c["t"] <= v["t1"] + tol
                   for v in truth["revivals"]):
                out[j] = 0
    return out, {"riot_kills": len(rk), "riot_kills_matched": len(used)}


# ----------------------------------------------------------------- filter

def _shift(P: np.ndarray, axis: int, step: int) -> np.ndarray:
    """Move every count on `axis` by `step` (-1 a death, +1 a revive); mass that
    cannot move (no one left to die, nobody to revive past five) stays."""
    Q = np.zeros_like(P)
    src = [slice(None)] * 2
    dst = [slice(None)] * 2
    if step < 0:
        src[axis], dst[axis] = slice(1, None), slice(0, -1)
        keep = [slice(None)] * 2
        keep[axis] = slice(0, 1)
    else:
        src[axis], dst[axis] = slice(0, -1), slice(1, None)
        keep = [slice(None)] * 2
        keep[axis] = slice(-1, None)
    Q[tuple(dst)] += P[tuple(src)]
    Q[tuple(keep)] += P[tuple(keep)]
    return Q


def apply_claim(P: np.ndarray, c: dict, probs: np.ndarray | None) -> np.ndarray:
    """One claim's transition, with its class's measured outcome probabilities."""
    if probs is None:
        return P
    p0, p1, p2 = probs
    if c["cls"] == "revive":
        if c["side"] < 0:
            return P
        return p0 * _shift(P, c["side"], +1) + (1.0 - p0) * P
    if c["side"] < 0:  # absolute: ally, enemy, none
        return p0 * _shift(P, 0, -1) + p1 * _shift(P, 1, -1) + p2 * P
    s = c["side"]
    return p0 * _shift(P, s, -1) + p1 * _shift(P, 1 - s, -1) + p2 * P


def loo_rates(counts: dict, sid: str) -> dict:
    """Per class, outcome probabilities from every captured match but `sid`;
    None where the other matches hold no claim of the class."""
    out = {}
    for c in CLASSES:
        tot = np.zeros(3)
        for s, cc in counts.items():
            if s != sid:
                tot += cc.get(c, np.zeros(3))
        out[c] = (tot / tot.sum()) if tot.sum() > 0 else None
    return out


# ----------------------------------------------------------------- main

def boot_ci(D, vals: np.ndarray, boot: int) -> list[float]:
    """Match-block bootstrap 95% interval of a round-weighted mean."""
    sids = sorted(set(D.match.tolist()))
    idx = np.searchsorted(np.array(sids), D.match)
    g = np.column_stack([np.bincount(idx, D.w * vals, len(sids)), np.bincount(idx, D.w, len(sids))])
    draws = np.random.default_rng(0).integers(0, len(sids), (boot, len(sids)))
    tot = g[draws].sum(axis=1)
    lo, hi = np.quantile(tot[:, 0] / tot[:, 1], [0.025, 0.975])
    return [round(float(lo), 5), round(float(hi), 5)]


def scored(D, p, boot: int) -> dict:
    s = wr.scores(D, p)
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    ll = -(D.y * np.log(pc) + (1 - D.y) * np.log(1 - pc))
    s["logloss_nats_ci95"] = boot_ci(D, ll, boot)
    s["logloss_bits_ci95"] = [round(v / LN2, 5) for v in s["logloss_nats_ci95"]]
    s["brier_ci95"] = boot_ci(D, (pc - D.y) ** 2, boot)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(STORE / "analysis" / "round-filter-0.1.0-20261004"))
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
    t0 = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    why = Counter()

    import pyarrow.parquet as pq
    from reticle.store import Store
    from reticle import roster as _roster, menu as _menu, gametime as _gametime, stalls as _stalls

    ref = rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
    records = rgt.riot_records(STORE)
    sites = wr.site_centres(ref)
    rounds = []
    for sid, d in sorted(records.items()):
        rs, w = wr.match_rounds(sid, d, ref, sites)
        rounds += rs
    adm = [r for r in rounds if r.get("admitted")]
    maps = sorted({r["map"] for r in adm})
    G = wr.Data(wr.grid_states(adm), adm)
    frames = wr.capture_frames(adm, ref, records, out_dir, why)
    adm_by_sid = defaultdict(list)
    for rd in adm:
        adm_by_sid[rd["sid"]].append(rd)
    store = Store(STORE)

    # ---- claims, scored against Riot per match
    claims, counts, recall, stamps, kill_t = {}, {}, {}, {}, {}
    for sid, fr in frames.items():
        cl, dver = stored_claims(sid, why)
        truth = riot_truth(sid, records[sid], fr, adm_by_sid)
        out, rc = score_claims(cl, truth, rgt.MATCH_TOL_MS)
        cc = defaultdict(lambda: np.zeros(3))
        for c, o in zip(cl, out):
            c["riot"] = o
            cc[c["cls"]][o] += 1
        claims[sid], counts[sid], recall[sid] = cl, dict(cc), rc
        kill_t[sid] = np.sort([k["t"] for k in truth["kills"]])
        stamps[sid] = {"death": dver}
    pooled = {c: np.sum([counts[s].get(c, np.zeros(3)) for s in counts], axis=0).astype(int).tolist()
              for c in CLASSES}

    # ---- per captured instant: stored round, start, claims, plant
    cap = np.array([G.rounds[s["ri"]]["sid"] in frames for s in G.S])
    gi = np.flatnonzero(cap)
    # Riot start counts (ally, enemy) per admitted round, for the start map
    start_truth = {}
    for ri, rd in enumerate(adm):
        if rd["sid"] in frames:
            s0 = wr.state_at(rd, 0.0)
            ally_att = frames[rd["sid"]]["team"] == rd["att_team"]
            start_truth[ri] = (s0["a"], s0["d"]) if ally_att else (s0["d"], s0["a"])
    # Riot plant rate by grid second, per match, for unread plants
    gt_s = np.array([s["t"] for s in G.S])
    gp = np.array([s["planted"] for s in G.S], float)
    tbin = np.round(gt_s).astype(int)
    nb = int(tbin.max()) + 1

    def plant_rate(sid):
        k = G.match != sid
        n = np.bincount(tbin[k], minlength=nb)
        p = np.bincount(tbin[k], gp[k], minlength=nb)
        marg = p.sum() / n.sum()
        return np.where(n > 0, p / np.maximum(n, 1), marg)

    rows = []  # one per covered instant
    start_pairs = defaultdict(list)  # sid -> [(read_ally, read_enemy, true_ally, true_enemy)]
    sessions = {}
    for sid in sorted(frames):
        fr = frames[sid]
        man = fr["man"]
        date = man["ingested_at"][:10]
        rt_tab = store.read_rounds(sid, date).to_pylist() if store.rounds_path(sid, date).exists() else []
        if not rt_tab or not store.hud_path(sid, date).exists() or not store.roster_path(sid, date).exists():
            why["session_without_rounds_hud_or_roster"] += 1
            continue
        hud = pq.read_table(store.hud_path(sid, date))
        roster = pq.read_table(store.roster_path(sid, date))
        menu, mwhy = _menu.stored_menu(store, sid)
        ally, enemy = _roster.resolve(hud, roster, menu=menu.at if menu else None)
        gt = _gametime.build_session_gametime(sid, hud, rt_tab, stall_list=_stalls.for_session(store, sid, date))
        live = {s.round_no: s.t_live_ms for s in gt.schedules}
        rtm = np.asarray(roster.column("t_ms").to_numpy(zero_copy_only=False), float)
        A = np.array([np.nan if v is None else v for v in ally], float)
        E = np.array([np.nan if v is None else v for v in enemy], float)
        stamps[sid].update({"roster": (roster.schema.metadata or {}).get(b"roster_version", b"").decode(),
                            "menu": mwhy, "rounds": rt_tab[0]["round_version"],
                            "gametime": _gametime.GAMETIME_VERSION})
        starts = np.array([r["t_start_ms"] for r in rt_tab])
        ends = np.array([r["t_close_ms"] if r["t_close_ms"] is not None else r["t_end_ms"] for r in rt_tab])
        # the start read per stored round: the first two-sided roster read after the barrier drop
        start_read = {}
        for r in rt_tab:
            tl = live.get(r["round_no"])
            k = int(np.searchsorted(rtm, tl)) if tl is not None else len(rtm)
            hi = int(np.searchsorted(rtm, tl + START_READ_MS, "right")) if tl is not None else k
            ok = np.flatnonzero(~np.isnan(A[k:hi]) & ~np.isnan(E[k:hi]))
            start_read[r["round_no"]] = ((int(A[k + ok[0]]), int(E[k + ok[0]]), float(rtm[k + ok[0]]))
                                         if ok.size else None)
        sessions[sid] = {"rt_tab": rt_tab, "starts": starts, "ends": ends, "start_read": start_read}
        idx = gi[G.match[gi] == sid]
        ts_feed = np.array([fr["a_ms"] + (G.rounds[G.S[i]["ri"]]["rstart_game"] or np.nan) for i in idx]) \
            + gt_s[idx] * 1000.0
        ts_hud = ts_feed + rgt.MINIMAP_LAG_MS
        k = np.searchsorted(starts, ts_hud, "right") - 1
        inside = (k >= 0) & (ts_hud <= ends[np.clip(k, 0, None)]) & ~np.isnan(ts_feed)
        why["cover_no_round_start"] += int(np.isnan(ts_feed).sum())
        why["cover_no_stored_round"] += int((~inside & ~np.isnan(ts_feed)).sum())
        rows += list(zip([sid] * int(inside.sum()), idx[inside].tolist(), ts_feed[inside].tolist(),
                         ts_hud[inside].tolist(), k[inside].tolist()))
        # start pairs for the start map: the stored round of each Riot round's first instant
        first = {}
        for i, kk in zip(idx[inside].tolist()[::-1], k[inside].tolist()[::-1]):
            first[G.S[i]["ri"]] = kk
        for ri, kk in sorted(first.items()):
            sr = start_read.get(rt_tab[kk]["round_no"])
            start_pairs[sid].append((sr[0] if sr else None, sr[1] if sr else None, *start_truth[ri]))

    def start_dist(sid, read):
        """Per side P(true start | read) from the other matches; the marginal
        where the read is missing or unseen."""
        out = []
        for side in (0, 1):
            pairs = [(p[side], p[2 + side]) for s, ps in start_pairs.items() if s != sid for p in ps]
            marg = np.bincount([t for _r, t in pairs], minlength=N)[:N].astype(float)
            r = read[side] if read else None
            cond = np.bincount([t for rr, t in pairs if rr == r and r is not None], minlength=N)[:N].astype(float)
            v = cond if cond.sum() > 0 else marg
            out.append(v / v.sum())
        return np.outer(out[0], out[1])

    # ---- the filter: per (session, stored round), distributions after each claim
    n_rows = len(rows)
    dist = np.zeros((n_rows, N, N))
    p_plant = np.zeros(n_rows)
    flags = Counter()
    unc = np.zeros(n_rows, bool)
    unrated = np.zeros(n_rows, int)
    plant_unread = np.zeros(n_rows, bool)
    start_basis = Counter()
    by_round = defaultdict(list)
    for j, (sid, i, tf, th, kk) in enumerate(rows):
        by_round[(sid, kk)].append(j)
    rates_cache, prate_cache = {}, {}
    for (sid, kk), js in by_round.items():
        if sid not in rates_cache:
            rates_cache[sid] = loo_rates(counts, sid)
            prate_cache[sid] = plant_rate(sid)
        rates = rates_cache[sid]
        sr = sessions[sid]["rt_tab"][kk]
        read = sessions[sid]["start_read"].get(sr["round_no"])
        start_basis["roster_read" if read else "riot_marginal"] += 1
        P = start_dist(sid, read)
        cl = [c for c in claims[sid] if c["round_no"] == sr["round_no"]]
        seq, tt, u_seq, r_seq = [P], [], [False], [0]
        for c in cl:
            pr = rates[c["cls"]]
            P = apply_claim(P, c, pr)
            seq.append(P)
            tt.append(c["t"])
            u_seq.append(u_seq[-1] or c["cls"] in UNCERTAIN)
            r_seq.append(r_seq[-1] + (pr is None))
        js = np.array(js)
        tf = np.array([rows[j][2] for j in js])
        th = np.array([rows[j][3] for j in js])
        m = np.searchsorted(np.array(tt), tf, "right")
        dist[js] = np.stack(seq)[m]
        unc[js] = np.array(u_seq)[m]
        unrated[js] = np.array(r_seq)[m]
        # plant: the stored table, or the Riot rate where it is unread
        sp, pt = sr["spike_planted"], sr["plant_t_ms"]
        if sp is None or (sp and pt is None):
            plant_unread[js] = True
            p_plant[js] = prate_cache[sid][tbin[[rows[j][1] for j in js]]]
        else:
            p_plant[js] = (bool(sp) & (pt is not None) & (th >= (pt if pt is not None else np.inf))).astype(float)

    # ---- expand each instant into its states and apply the outcome model
    inst = np.array([r[1] for r in rows])
    ally_att = np.array([frames[rows[j][0]]["team"] == G.rounds[G.S[rows[j][1]]["ri"]]["att_team"]
                         for j in range(n_rows)])
    ia, ie = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    ia, ie = ia.ravel(), ie.ravel()
    flat = dist.reshape(n_rows, -1)
    W = np.concatenate([flat * (1 - p_plant)[:, None], flat * p_plant[:, None]], axis=1)
    jj, cc = np.nonzero(W > 1e-12)
    wt = W[jj, cc]
    cell = cc % (N * N)
    planted = cc >= N * N
    xa = np.where(ally_att[jj], ia[cell], ie[cell])
    xd = np.where(ally_att[jj], ie[cell], ia[cell])
    keys = ("t", "a", "d", "aload", "dload", "planted", "tp", "ri")
    S_exp = [dict(zip(keys, v)) for v in zip(gt_s[inst[jj]].tolist(), xa.tolist(), xd.tolist(),
                                            [0.0] * len(jj), [0.0] * len(jj), planted.tolist(),
                                            [None] * len(jj), [G.S[i]["ri"] for i in inst[jj]])]
    Dexp = wr.Data(S_exp, adm)
    p_exp, coef = wr.lomo(G, SPEC, maps, eval_D=Dexp)
    p_obs = np.bincount(jj, wt * p_exp, n_rows) / np.bincount(jj, wt, n_rows)
    # MAP plug-in: the single most probable state
    best = np.argmax(W, axis=1)
    bcell = best % (N * N)
    S_map = [dict(zip(keys, v)) for v in zip(gt_s[inst].tolist(),
                                            np.where(ally_att, ia[bcell], ie[bcell]).tolist(),
                                            np.where(ally_att, ie[bcell], ia[bcell]).tolist(),
                                            [0.0] * n_rows, [0.0] * n_rows, (best >= N * N).tolist(),
                                            [None] * n_rows, [G.S[i]["ri"] for i in inst])]
    p_map, _ = wr.lomo(G, SPEC, maps, eval_D=wr.Data(S_map, adm))

    # ---- oracle and scores on the same instants
    covered = np.zeros(len(G.S), bool)
    covered[inst] = True
    order = np.argsort(inst)  # G.subset keeps G's order
    Gc = G.subset(covered)
    p_obs_c, p_map_c = p_obs[order], p_map[order]
    p_true, _ = wr.lomo(G, SPEC, maps, eval_D=Gc)
    # state agreement with Riot (ally, enemy)
    ta = np.array([s["a"] for s in Gc.S])
    td = np.array([s["d"] for s in Gc.S])
    aa = ally_att[order]
    t_ally, t_enemy = np.where(aa, ta, td), np.where(aa, td, ta)
    dist_c = dist[order]
    p_true_state = dist_c[np.arange(len(order)), t_ally, t_enemy]
    map_cell = np.argmax(dist_c.reshape(len(order), -1), axis=1)
    rp = np.array([s["planted"] for s in Gc.S])
    # how far each wrong most-probable state lies from a Riot kill (store time)
    tf_c = np.array([rows[j][2] for j in order])
    sid_c = [rows[j][0] for j in order]
    near = np.full(len(order), np.inf)
    for sid in frames:
        m = np.array([s == sid for s in sid_c])
        if m.any() and len(kill_t[sid]):
            k = np.clip(np.searchsorted(kill_t[sid], tf_c[m]), 1, len(kill_t[sid]) - 1)
            near[m] = np.minimum(np.abs(kill_t[sid][k] - tf_c[m]), np.abs(kill_t[sid][k - 1] - tf_c[m]))
    wrong = map_cell != t_ally * N + t_enemy
    R = {"version": VERSION, "reference_version": wr.VERSION, "spec": SPEC,
         "riot_digest": wr.digest((STORE / "external" / "riot").glob("*.json")),
         "constants": {"MATCH_TOL_MS": rgt.MATCH_TOL_MS, "MINIMAP_LAG_MS": rgt.MINIMAP_LAG_MS,
                       "START_READ_MS": START_READ_MS, "RIDGE": wr.RIDGE},
         "captured_matches": len(frames), "stamps": stamps,
         "coverage": {"captured_states": int(cap.sum()), "covered_states": int(len(rows)),
                      "share_of_captured": round(len(rows) / max(int(cap.sum()), 1), 4),
                      "detail": {k: v for k, v in why.items() if k.startswith("cover_")}},
         "claims": {"rows": {k: v for k, v in why.items() if k.startswith("claims")},
                    "riot_outcomes_pooled": pooled,
                    "outcome_columns": "known side: [same, other, none]; side_unknown: [ally, enemy, none]; "
                                       "revive: [revival on its side, -, none]",
                    "riot_kills": sum(r["riot_kills"] for r in recall.values()),
                    "riot_kills_matched": sum(r["riot_kills_matched"] for r in recall.values())},
         "start_basis": dict(start_basis),
         "start_pairs": {s: Counter(f"{p[0]}/{p[1]}->{p[2]}/{p[3]}" for p in ps) for s, ps in start_pairs.items()},
         "refusals": {"instants_after_uncertain_claim": int(unc.sum()),
                      "instants_with_unrated_claim": int((unrated > 0).sum()),
                      "instants_plant_unread": int(plant_unread.sum()),
                      "instants_any": int((unc | (unrated > 0) | plant_unread).sum())},
         "state": {"mean_p_on_riot_state": round(float(p_true_state.mean()), 4),
                   "map_alive_right": int(np.sum(~wrong)),
                   "map_alive_wrong": int(wrong.sum()),
                   "map_wrong_within_1s_of_riot_kill": int(np.sum(wrong & (near <= 1000.0))),
                   "map_wrong_within_3s_of_riot_kill": int(np.sum(wrong & (near <= 3000.0))),
                   "plant_right": int(np.sum((p_plant[order] > 0.5) == rp)),
                   "plant_late": int(np.sum((p_plant[order] <= 0.5) & rp)),
                   "plant_early": int(np.sum((p_plant[order] > 0.5) & ~rp))},
         "model_coef_full": coef}
    R["filter"] = scored(Gc, p_obs_c, args.boot)
    R["oracle"] = scored(Gc, p_true, args.boot)
    R["map_plugin"] = scored(Gc, p_map_c, args.boot)
    R["observation_cost"] = wr.compare(Gc, p_obs_c, p_true, args.boot)
    R["mixture_vs_map"] = wr.compare(Gc, p_map_c, p_obs_c, args.boot)
    # the instants a refusal touches, scored apart (never dropped from the totals)
    flag_any = (unc | (unrated > 0) | plant_unread)[order]
    if flag_any.sum() >= 20:
        Gf = Gc.subset(flag_any)
        R["refusal_instants"] = {"states": int(flag_any.sum()),
                                 "filter": wr.scores(Gf, p_obs_c[flag_any], w=Gc.w[flag_any])["logloss_nats"],
                                 "oracle": wr.scores(Gf, p_true[flag_any], w=Gc.w[flag_any])["logloss_nats"]}
    R["elapsed_s"] = round(time.time() - t0, 1)
    (out_dir / "results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: R[k] for k in ("coverage", "claims", "start_basis", "refusals", "state",
                                        "observation_cost", "mixture_vs_map")}, indent=1, default=str))
    for k in ("filter", "oracle", "map_plugin"):
        print(k, {x: R[k][x] for x in ("logloss_nats", "logloss_nats_ci95", "logloss_bits", "brier",
                                       "brier_ci95", "n_states")}, R[k]["reliability"])
    print("wrote", out_dir / "results.json", R["elapsed_s"], "s")
    if args.record:
        record_metrics(R)


def record_metrics(R: dict):
    from reticle import metrics
    deps = {"tool_version": R["version"], "reference_version": R["reference_version"],
            "riot_digest": R["riot_digest"], "spec": "+".join(R["spec"]), **R["constants"],
            "stamps": sorted({json.dumps(v, sort_keys=True) for v in R["stamps"].values()})}
    ctx = {"captured_matches": R["captured_matches"]}
    vals = {"covered_states": R["coverage"]["covered_states"],
            "captured_states": R["coverage"]["captured_states"],
            "share_of_captured": R["coverage"]["share_of_captured"],
            "cost_nats": R["observation_cost"]["improvement_nats"],
            "cost_bits": R["observation_cost"]["improvement_bits"],
            "mixture_gain_nats": R["mixture_vs_map"]["improvement_nats"],
            "riot_kills": R["claims"]["riot_kills"], "riot_kills_matched": R["claims"]["riot_kills_matched"],
            "refusal_instants": R["refusals"]["instants_any"],
            "mean_p_on_riot_state": R["state"]["mean_p_on_riot_state"]}
    ci = {"cost_nats": R["observation_cost"]["ci95_nats"],
          "mixture_gain_nats": R["mixture_vs_map"]["ci95_nats"]}
    for k in ("filter", "oracle", "map_plugin"):
        vals[f"{k}_nats"] = R[k]["logloss_nats"]
        vals[f"{k}_bits"] = R[k]["logloss_bits"]
        vals[f"{k}_brier"] = R[k]["brier"]
        ci[f"{k}_nats"] = R[k]["logloss_nats_ci95"]
        ci[f"{k}_brier"] = R[k]["brier_ci95"]
    for c, v in R["claims"]["riot_outcomes_pooled"].items():
        vals[f"claims_{c}_n"] = int(sum(v))
        if sum(v):
            vals[f"claims_{c}_first"] = round(v[0] / sum(v), 4)
    metrics.record("round_filter", part="riot_G", values=vals, deps=deps, context=ctx, ci=ci)
    print("recorded round_filter/riot_G")


if __name__ == "__main__":
    main()
