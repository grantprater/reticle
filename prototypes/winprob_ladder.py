r"""Round win probability fitted on the player's own competitive history.

    .\.venv\Scripts\python.exe prototypes\winprob_ladder.py prepare          # sets, admission, FIT-only LOMO
    .\.venv\Scripts\python.exe prototypes\winprob_ladder.py evaluate [--record] [--boot N]

Why this exists
---------------
`winprob_reference.py` fits the coarse-state ladder (gambler's ruin, alive
counts, loadout, side, map side, plant flag, clocks) on the 22 captured Riot
records only, leaving one match out. This file fits the same ladder where it
belongs, on the player's own uncaptured competitive history (HenrikDev v4,
`ladder-parse-0.2.0`, schema in docs/LADDER_SAMPLE.md), and scores it once on
held-out matches. It reuses the reference's event simulation, states, feature
groups, logistic fit and scores; only the v4 adapter, the economy credits
column, the CS prior and the rank bands are new.

Sets
----
FIT: parsed own-history matches, minus `captured`, minus any match whose id is
a Riot record's, minus the uncaptured kept-replay matches (the store's replay
manifest, `capture_session` null: held out for the final test, excluded from
everything), minus every match the ladder's fixed one-in-five hash split marks
`holdout` ("A match that evaluates a fitted model stays out of its fit").
E1: the 22 captured Riot records. E2: the `holdout` matches that are neither
captured nor kept replays. The two are scored apart and pooled.

The adapter
-----------
`v4_record` rebuilds Riot's record shape from the parsed tables, so
`winprob_reference.match_rounds` and `simulate` run unchanged. v4 rounds name
no attacking side; `attacker_team` assigns it (Red attacks rounds 0-11, Blue
12-23, overtime rounds alternate from Red), and a round whose planter is on
the other side is excluded (`side_rule_planter_mismatch`). AFK and penalty
flags come from the economy table; kill positions from `positions`.

Economy
-------
`load` is the reference's: living players' `loadout_value`, attacker minus
defender. `credits` is the living players' `remaining` (credits unspent after
the buy phase, Riot's `remaining`), attacker minus defender, over 10,000.

CS prior
--------
`<store>/external/cs/{kaggle_mm,esta}/states.parquet` (prototypes/cs_data.py):
start and non-deciding kill states, fitted with the comparable model (alive,
side, plant flag) and scored on the VALORANT K0 states (round starts plus kill
states). The shrinkage fit penalises lambda * |beta - beta_CS|^2, lambda chosen
by leave-one-match-out within the VALORANT subset.

Wire: no (notes/predictions.jsonl, task winprob-ladder-20261004). These fits
never feed a reader, a reader's threshold or anything shown during play.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import winprob_reference as wr  # noqa: E402

VERSION = "winprob-ladder-0.1.0"
STORE = wr.STORE
PARSED = STORE / "external" / "ladder" / "henrikdev" / "v4" / "parsed" / "ladder-parse-0.2.0"
CS_DIR = STORE / "external" / "cs"
REPLAYS = STORE / "external" / "replays" / "manifest.json"
OUT = STORE / "analysis" / "winprob-ladder-0.1.0-20261004"
REGULATION = 24
ECE_BINS = 10
LAMBDAS = (1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0)
CURVE_SIZES = (5, 10, 20, 40)
CURVE_REPS = 20
BANDS = {"bronze_silver": ("Bronze", "Silver"), "gold_platinum": ("Gold", "Platinum")}
BASE3 = ["alive", "load", "side"]
LADDER = {"M1_alive": ["alive"], "M2_alive_load": ["alive", "load"],
          "M3_alive_load_side": BASE3, "M4_alive_load_mapside": BASE3 + ["mapside"],
          "B0_gamblers_ruin": "gr", "B1_plant_flag": BASE3 + ["flag"],
          "B2_plant_flag_clock": BASE3 + ["flag", "clock"],
          "B3_phase_clock": {"pre": BASE3 + ["preclock"], "post": BASE3 + ["postclock"]}}
ECONOMY = {"E0_alive_side_flag": ["alive", "side", "flag"],
           "E1_load": ["alive", "load", "side", "flag"],
           "E2_credits": ["alive", "credits", "side", "flag"],
           "E3_load_credits": ["alive", "load", "credits", "side", "flag"]}
CS_SPEC = ["alive", "side", "flag"]
#: `match_rounds` counts these but admits the round.
NOT_EXCLUSIONS = ("plant_after_decision",)


# ----------------------------------------------------------------- adapter

def attacker_team(round_num: int) -> str:
    """The attacking team of a v4 round (0-based): Red attacks the first half,
    Blue the second, and overtime rounds alternate starting with Red."""
    if round_num < REGULATION // 2:
        return "Red"
    if round_num < REGULATION:
        return "Blue"
    return "Red" if (round_num - REGULATION) % 2 == 0 else "Blue"


def load_tables(parsed: Path = PARSED) -> dict[str, list[dict]]:
    import pyarrow.parquet as pq
    return {t: pq.read_table(parsed / f"{t}.parquet").to_pylist()
            for t in ("matches", "players", "rounds", "economy", "kills", "positions")}


def group(rows, *keys):
    out = defaultdict(list)
    for r in rows:
        out[tuple(r[k] for k in keys) if len(keys) > 1 else r[keys[0]]].append(r)
    return out


def v4_record(m: dict, players, rounds, econ, kills, pos, map_url: str) -> tuple[dict, Counter]:
    """A Riot-shaped record ({"match": ...}) for one parsed v4 match."""
    why = Counter()
    team_of = {p["player"]: p["team"] for p in players}
    locs = defaultdict(list)
    for p in pos:
        if p["event"] == "kill":
            locs[p["kill"]].append({"subject": p["player"],
                                    "location": {"x": p["x"], "y": p["y"]}})
    rk = [{"round": k["round"], "roundTime": k["time_in_round_ms"], "gameTime": k["time_in_match_ms"],
           "killer": k["killer"], "victim": k["victim"], "playerLocations": locs.get(k["kill"], [])}
          for k in kills]
    eco = group(econ, "round")
    rr = []
    for r in sorted(rounds, key=lambda r: r["round"]):
        n = r["round"]
        att = attacker_team(n)
        if r["planter"] is not None and team_of.get(r["planter"]) != att:
            why["side_rule_planter_mismatch"] += 1
            continue
        win = r["winning_team"]
        e = eco.get(n, [])
        rr.append({"roundNum": n, "roundResultCode": r["result"], "winningTeam": win,
                   "winningTeamRole": "Attacker" if win == att else "Defender",
                   "bombPlanter": r["planter"], "plantRoundTime": r["plant_ms"],
                   "plantLocation": ({"x": r["plant_x"], "y": r["plant_y"]}
                                     if r["plant_x"] is not None else None),
                   "bombDefuser": r["defuser"], "defuseRoundTime": r["defuse_ms"],
                   "playerStats": [{"subject": x["player"], "wasAfk": bool(x["was_afk"]),
                                    "wasPenalized": bool(x["received_penalty"])} for x in e],
                   "playerEconomies": [{"subject": x["player"], "loadoutValue": x["loadout_value"],
                                        "remaining": x["remaining"]} for x in e]})
    rec = {"match": {"matchInfo": {"matchId": m["match_id"], "mapId": map_url, "queueID": m["queue"]},
                     "players": [{"subject": s, "teamId": t} for s, t in team_of.items()],
                     "roundResults": rr, "kills": rk}}
    return rec, why


def credits_of(rec: dict) -> dict[int, dict[str, float]]:
    return {r["roundNum"]: {e["subject"]: float(e.get("remaining") or 0.0)
                            for e in r.get("playerEconomies") or ()}
            for r in rec["match"]["roundResults"]}


def kept_replay_ids(path: Path = REPLAYS) -> set[str]:
    """Match ids of the uncaptured kept replays (capture_session null)."""
    man = json.loads(path.read_text(encoding="utf-8"))
    return {Path(f["file"]).stem for f in man["files"] if not f.get("capture_session")}


def split_sets(matches: list[dict], riot_ids: set[str], kept: set[str]) -> tuple[dict, Counter]:
    """match_id -> "FIT" | "E2" | None, and the exclusion counts."""
    out, why = {}, Counter()
    for m in matches:
        mid = m["match_id"]
        if m["captured"] or mid in riot_ids:
            out[mid] = None
            why["captured"] += 1
        elif mid in kept:
            out[mid] = None
            why["kept_replay_final_test"] += 1
        elif m["holdout"]:
            out[mid] = "E2"
        else:
            out[mid] = "FIT"
    return out, why


# ----------------------------------------------------------------- rounds

def admit(records: dict[str, dict], sites=None) -> tuple[list[dict], Counter]:
    """Admitted rounds of `records` (sid -> Riot-shaped record) through the
    reference's `match_rounds`, each carrying `credits` beside `econ`."""
    rounds, why = [], Counter()
    for sid, d in sorted(records.items()):
        rs, w = wr.match_rounds(sid, d, None, sites or {})
        why.update(w)
        cr = credits_of(d)
        for r in rs:
            if r.get("admitted"):
                r["credits"] = cr.get(r["round"], {})
                rounds.append(r)
    return rounds, why


def attach_credits(S: list[dict], rounds: list[dict]) -> None:
    """Living players' credits per state, through the reference's `state_at`."""
    for s in S:
        rd = rounds[s["ri"]]
        c = wr.state_at(rd | {"econ": rd["credits"]}, s["t"] * 1000.0)
        s["acred"], s["dcred"] = c["aload"], c["dload"]


def state_sets(rounds: list[dict]) -> dict[str, wr.Data]:
    K = wr.kill_states(rounds)
    G = wr.grid_states(rounds)
    K0 = []
    for ri, rd in enumerate(rounds):
        s = wr.state_at(rd, 0.0)
        s["ri"] = ri
        K0.append(s)
    K0 += [dict(s) for s in K]
    for S in (K, G, K0):
        attach_credits(S, rounds)
    return {"K": wr.Data(K, rounds), "G": wr.Data(G, rounds), "K0": wr.Data(K0, rounds)}


# ----------------------------------------------------------------- fitting

def design(S, rounds, groups, maps):
    """The reference's columns plus `credits`."""
    base = [g for g in groups if g != "credits"]
    X, pen = wr.columns(S, rounds, base, maps)
    if "credits" in groups:
        c = np.array([s["acred"] - s["dcred"] for s in S], float) / 10000.0
        X = np.column_stack([X, c])
        pen = pen + [wr.RIDGE]
    return X, pen


def fit_centered(X, y, w, pen, centre=None):
    """Ridge logistic with the penalty centred on `centre` (zero: `fit_logit`)."""
    if centre is None:
        return wr.fit_logit(X, y, w, pen)
    beta = np.array(centre, float)
    P = np.diag(pen)
    for _ in range(200):
        p = wr.sig(X @ beta)
        g = X.T @ (w * (p - y)) + P @ (beta - centre)
        H = X.T @ ((w * p * (1 - p))[:, None] * X) + P + 1e-9 * np.eye(len(beta))
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-10:
            return beta
    raise ValueError("centred logistic fit did not converge")


def phases(spec, S):
    planted = np.array([s["planted"] for s in S], bool)
    if isinstance(spec, list):
        return {"all": (spec, np.ones(len(S), bool))}
    return {"pre": (spec["pre"], ~planted), "post": (spec["post"], planted)}


def fit_predict(F: wr.Data, spec, maps, E: wr.Data):
    """P(attackers win) on every state of `E`, from one fit on all of `F`."""
    if spec == "gr":
        return wr.lomo(F, "gr", maps, eval_D=E)[0], {}
    p = np.full(len(E.S), np.nan)
    coefs = {}
    fph, eph = phases(spec, F.S), phases(spec, E.S)
    for ph, (groups, fm) in fph.items():
        em = eph[ph][1]
        Sf = [s for s, k in zip(F.S, fm) if k]
        X, pen = design(Sf, F.rounds, groups, maps)
        beta = wr.fit_logit(X, F.y[fm], F.w[fm], pen)
        coefs[ph] = beta.round(4).tolist()
        if em.any():
            Xe, _ = design([s for s, k in zip(E.S, em) if k], E.rounds, groups, maps)
            p[em] = wr.sig(Xe @ beta)
    return p, coefs


def concat(*Ds: wr.Data) -> wr.Data:
    """One Data over several (each keeps its own rounds; ri re-based)."""
    rounds, S = [], []
    for D in Ds:
        off = len(rounds)
        rounds += D.rounds
        S += [s | {"ri": s["ri"] + off} for s in D.S]
    return wr.Data(S, rounds)


# ----------------------------------------------------------------- scores

def _ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def match_sums(D: wr.Data, p) -> tuple[np.ndarray, list[str]]:
    """Per evaluation match: [w, w*ll, w*brier, per-bin w, w*p, w*y ...]."""
    sids = sorted(set(D.match.tolist()))
    idx = {s: i for i, s in enumerate(sids)}
    mi = np.array([idx[s] for s in D.match])
    b = np.minimum((np.clip(p, 0, 1) * ECE_BINS).astype(int), ECE_BINS - 1)
    w, y = D.w, D.y
    cols = [w, w * _ll(y, p), w * (np.clip(p, 1e-6, 1 - 1e-6) - y) ** 2]
    for k in range(ECE_BINS):
        on = (b == k).astype(float)
        cols += [w * on, w * on * p, w * on * y]
    M = np.zeros((len(sids), len(cols)))
    for j, c in enumerate(cols):
        M[:, j] = np.bincount(mi, weights=c, minlength=len(sids))
    return M, sids


def _from_sums(T: np.ndarray) -> np.ndarray:
    """[logloss, brier, ece] per row of summed match vectors."""
    T = np.atleast_2d(T)
    W = T[:, 0]
    bins = T[:, 3:].reshape(len(T), ECE_BINS, 3)
    bw = bins[:, :, 0]
    gap = np.abs(bins[:, :, 1] - bins[:, :, 2]) / np.maximum(bw, 1e-12)
    ece = (bw * gap).sum(axis=1) / W
    return np.column_stack([T[:, 1] / W, T[:, 2] / W, ece])


def boot_draws(n: int, boot: int, seed: int = 0) -> np.ndarray:
    """(boot, n) multiplicities of a match-cluster bootstrap."""
    rng = np.random.default_rng(seed)
    d = rng.integers(0, n, (boot, n))
    C = np.zeros((boot, n))
    np.add.at(C, (np.arange(boot)[:, None], d), 1.0)
    return C


def evaluate_scores(D: wr.Data, p, boot: int) -> dict:
    """Round-weighted log loss, Brier and ECE with match-bootstrap 95% intervals,
    the per-state log loss and a 10-bin reliability table."""
    M, sids = match_sums(D, p)
    point = _from_sums(M.sum(axis=0))[0]
    draws = _from_sums(boot_draws(len(sids), boot) @ M)
    lo, hi = np.quantile(draws, [0.025, 0.975], axis=0)
    tot = M.sum(axis=0)[3:].reshape(ECE_BINS, 3)
    rel = [{"bin": [k / ECE_BINS, (k + 1) / ECE_BINS], "round_weight": round(float(tot[k, 0]), 2),
            "predicted": round(float(tot[k, 1] / tot[k, 0]), 4),
            "observed": round(float(tot[k, 2] / tot[k, 0]), 4)}
           for k in range(ECE_BINS) if tot[k, 0] > 0]
    out = {"n_states": int(len(p)), "n_rounds": int(len(set(D.ri.tolist()))), "n_matches": len(sids),
           "logloss_nats_per_state": round(float(_ll(D.y, p).mean()), 5),
           "reliability10": rel}
    for j, k in enumerate(("logloss_nats", "brier", "ece")):
        out[k] = round(float(point[j]), 5)
        out[f"{k}_ci95"] = [round(float(lo[j]), 5), round(float(hi[j]), 5)]
    return out


# ----------------------------------------------------------------- CS

def cs_data(source: str) -> wr.Data:
    """CS start and non-deciding kill states as reference states (attacker = T)."""
    import pyarrow.parquet as pq
    t = pq.read_table(CS_DIR / source / "states.parquet",
                      columns=["match", "round", "event", "atk_alive", "def_alive", "planted",
                               "atk_win", "deciding"]).to_pydict()
    rounds, ri_of, S = [], {}, []
    for m, r, ev, a, d, pl, win, dec in zip(*t.values()):
        if ev not in ("start", "kill") or dec or not (0 <= a <= 5 and 0 <= d <= 5) or a + d == 0:
            continue
        key = (m, r)
        if key not in ri_of:
            ri_of[key] = len(rounds)
            rounds.append({"sid": f"{source}:{m}", "y": int(bool(win)), "map": "cs"})
        S.append({"ri": ri_of[key], "t": 0.0, "a": int(a), "d": int(d), "aload": 0.0, "dload": 0.0,
                  "planted": bool(pl), "tp": 0.0 if pl else None})
    return wr.Data(S, rounds)


def matrices(D: wr.Data, spec, maps):
    X, pen = design(D.S, D.rounds, spec, maps)
    return X, D.y, D.w, D.match, np.array(pen)


def lomo_lambda(X, y, w, m, pen, centre, lams) -> float:
    """The prior strength with the lowest leave-one-match-out log loss."""
    sids = np.unique(m)
    best, arg = np.inf, None
    for lam in lams:
        tot, wt = 0.0, 0.0
        for s in sids:
            tr = m != s
            b = fit_centered(X[tr], y[tr], w[tr], np.full(len(pen), lam), centre)
            te = ~tr
            tot += float(np.sum(w[te] * _ll(y[te], wr.sig(X[te] @ b))))
            wt += float(w[te].sum())
        if tot / wt < best:
            best, arg = tot / wt, lam
    return arg


def learning_curve(F: wr.Data, E: wr.Data, priors: dict[str, np.ndarray], boot: int,
                   sizes=CURVE_SIZES, reps=CURVE_REPS, seed=0) -> dict:
    """VALORANT-only against CS-prior shrinkage fits on random FIT subsets."""
    X, y, w, m, pen = matrices(F, CS_SPEC, [])
    Xe, ye, we, me, _ = matrices(E, CS_SPEC, [])
    esids = sorted(set(me.tolist()))
    eidx = np.searchsorted(np.array(esids), me)
    fsids = np.array(sorted(set(m.tolist())))
    rng = np.random.default_rng(seed)
    out = {}

    def per_match(beta):
        ll = we * _ll(ye, wr.sig(Xe @ beta))
        return np.bincount(eidx, weights=ll, minlength=len(esids))

    W = np.bincount(eidx, weights=we, minlength=len(esids))
    plan = [(n, reps) for n in sizes if n < len(fsids)] + [(len(fsids), 1)]
    for n, r in plan:
        rows = {"val_only": [], **{k: [] for k in priors}}
        lams = {k: [] for k in priors}
        for _ in range(r):
            pick = rng.choice(fsids, n, replace=False) if n < len(fsids) else fsids
            k = np.isin(m, pick)
            rows["val_only"].append(per_match(wr.fit_logit(X[k], y[k], w[k], list(pen))))
            for name, b0 in priors.items():
                lam = lomo_lambda(X[k], y[k], w[k], m[k], pen, b0, LAMBDAS)
                lams[name].append(lam)
                rows[name].append(per_match(fit_centered(X[k], y[k], w[k], np.full(len(pen), lam), b0)))
        A = {k: np.array(v) for k, v in rows.items()}          # (reps, eval matches)
        blk = {"n_matches": int(n), "reps": int(r),
               "val_only_nats": round(float(A["val_only"].sum(1).mean() / W.sum()), 5)}
        rng_b = np.random.default_rng(seed + n)
        C = boot_draws(len(esids), boot, seed + n)               # eval-match multiplicities
        R = rng_b.integers(0, r, (boot, r))                      # subset resamples
        for name in priors:
            diff = A["val_only"] - A[name]                         # positive: the prior helps
            point = diff.sum(1).mean() / W.sum()
            dm = diff[R].mean(axis=1)                              # (boot, eval matches)
            bd = (dm * C).sum(1) / (C @ W)
            lo, hi = np.quantile(bd, [0.025, 0.975])
            blk[name] = {"nats": round(float(A[name].sum(1).mean() / W.sum()), 5),
                         "gain_nats": round(float(point), 5),
                         "gain_ci95": [round(float(lo), 5), round(float(hi), 5)],
                         "lambda": dict(Counter(lams[name]))}
        out[str(n) if n < len(fsids) else "all"] = blk
        print("curve", n, {k: v for k, v in blk.items()}, flush=True)
    return out


# ----------------------------------------------------------------- rank bands

def band_coefs(F: wr.Data, strata: dict[str, str], spec, boot: int, seed: int = 0) -> dict:
    """Per band, the coefficients of `spec` and their match-bootstrap draws;
    the difference (gold_platinum - bronze_silver) with 95% intervals."""
    X, y, w, m, pen = matrices(F, spec, [])
    out, draws = {}, {}
    for bi, (band, names) in enumerate(BANDS.items()):
        k = np.array([strata.get(s) in names for s in m])
        Xb, yb, wb, mb = X[k], y[k], w[k], m[k]
        sids = np.array(sorted(set(mb.tolist())))
        rows_of = [np.flatnonzero(mb == s) for s in sids]
        beta = wr.fit_logit(Xb, yb, wb, list(pen))
        rng = np.random.default_rng(seed + bi)
        B = []
        for _ in range(boot):
            idx = np.concatenate([rows_of[j] for j in rng.integers(0, len(sids), len(sids))])
            B.append(wr.fit_logit(Xb[idx], yb[idx], wb[idx], list(pen)))
        draws[band] = np.array(B)
        lo, hi = np.quantile(draws[band], [0.025, 0.975], axis=0)
        out[band] = {"matches": int(len(sids)), "rounds": int(round(float(wb.sum()))),
                     "coef": beta.round(4).tolist(),
                     "ci95": [[round(float(a), 4), round(float(b), 4)] for a, b in zip(lo, hi)]}
    a, b = list(BANDS)
    D = draws[b] - draws[a]
    lo, hi = np.quantile(D, [0.025, 0.975], axis=0)
    diff = np.array(out[b]["coef"]) - np.array(out[a]["coef"])
    out["difference"] = {"coef": diff.round(4).tolist(),
                         "ci95": [[round(float(x), 4), round(float(z), 4)] for x, z in zip(lo, hi)],
                         "excludes_zero": [bool(x > 0 or z < 0) for x, z in zip(lo, hi)]}
    out["columns"] = column_names(spec)
    return out


def column_names(spec) -> list[str]:
    names = {"alive": ["alive_diff_5", "alive_diff_ratio"], "load": ["load_diff_10k"],
             "credits": ["credits_diff_10k"], "side": ["side"], "flag": ["planted"]}
    return [n for g in spec if g != "credits" for n in names[g]] + (names["credits"] if "credits" in spec else [])


# ----------------------------------------------------------------- main

def build(tables=None):
    """FIT, E1, E2 rounds and the admission counts. Scores nothing."""
    ref = wr.rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
    url_of = {m["uuid"]: url for url, m in ref.maps.items()}
    T = tables or load_tables()
    riot = wr.rgt.riot_records(STORE)
    riot_ids = {d["match"]["matchInfo"]["matchId"] for d in riot.values()}
    kept = kept_replay_ids()
    role, excl = split_sets(T["matches"], riot_ids, kept)
    by = {k: group(T[k], "match_id") for k in ("players", "rounds", "economy", "kills", "positions")}
    recs = {"FIT": {}, "E2": {}}
    why = {"FIT": Counter(), "E2": Counter(), "E1": Counter()}
    strata = {}
    for m in T["matches"]:
        r = role[m["match_id"]]
        if r is None:
            continue
        mid = m["match_id"]
        rec, w = v4_record(m, by["players"][mid], by["rounds"][mid], by["economy"][mid],
                           by["kills"][mid], by["positions"][mid], url_of[m["map_id"]])
        why[r].update(w)
        recs[r][mid] = rec
        strata[mid] = m["stratum"]
    sets = {}
    for r in ("FIT", "E2"):
        sets[r], w = admit(recs[r])
        why[r].update(w)
    sets["E1"], w = admit(riot)
    why["E1"].update(w)
    listed = {"FIT": sum(len(d["match"]["roundResults"]) for d in recs["FIT"].values()) + why["FIT"]["side_rule_planter_mismatch"],
              "E2": sum(len(d["match"]["roundResults"]) for d in recs["E2"].values()) + why["E2"]["side_rule_planter_mismatch"],
              "E1": sum(len(d["match"]["roundResults"]) for d in riot.values())}
    adm = {k: {"matches": len({r["sid"] for r in v}), "rounds_listed": listed[k], "admitted": len(v),
               "excluded": {a: b for a, b in why[k].items() if a not in NOT_EXCLUSIONS and not a.startswith("note_")},
               "notes": {a: b for a, b in why[k].items() if a in NOT_EXCLUSIONS or a.startswith("note_")},
               "attacker_win_rate": round(float(np.mean([r["y"] for r in v])), 4)}
           for k, v in sets.items()}
    adm["split"] = {"parsed_matches": len(T["matches"]), **dict(excl),
                    "kept_replays_uncaptured": len(kept),
                    "kept_replays_in_parsed": len(kept & {m["match_id"] for m in T["matches"]}),
                    "FIT_matches": sum(v == "FIT" for v in role.values()),
                    "E2_matches": sum(v == "E2" for v in role.values()),
                    "E1_matches": len(riot)}
    return sets, adm, strata


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=("prepare", "evaluate"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--band-boot", type=int, default=1000)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    try:  # Below Normal priority on Windows
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sets, adm, strata = build()
    print(json.dumps(adm, indent=1), flush=True)
    data = {k: state_sets(v) for k, v in sets.items()}
    maps = sorted({r["map"] for r in sets["FIT"]})
    R = {"version": VERSION, "reference": wr.VERSION, "admission": adm, "maps_fit": maps,
         "states": {k: {n: len(D.S) for n, D in v.items()} for k, v in data.items()}}
    F = data["FIT"]
    # leave one match out within FIT: no evaluation match is read
    fl = {}
    for name in ("K", "G"):
        blk = {}
        for mname, spec in LADDER.items():
            p, _ = wr.lomo(F[name], spec, maps)
            blk[mname] = {k: v for k, v in wr.scores(F[name], p).items() if k != "reliability"}
            print("FIT lomo", name, mname, blk[mname]["logloss_nats"], flush=True)
        fl[name] = blk
    R["fit_lomo"] = fl
    if args.stage == "prepare":
        R["elapsed_s"] = round(time.time() - t0, 1)
        (out / "prepare.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
        print("wrote", out / "prepare.json")
        return
    ref_res = json.loads((STORE / "analysis" / "winprob-reference-0.2.0-20261004" / "results.json")
                         .read_text(encoding="utf-8"))
    R["reference_lomo_22"] = {n: {m: ref_res[n][m]["logloss_nats"] for m in LADDER} for n in ("K", "G")}
    evals = {"E1": lambda n: data["E1"][n], "E2": lambda n: data["E2"][n],
             "pooled": lambda n: concat(data["E1"][n], data["E2"][n])}
    ev = {}
    for name in ("G", "K"):
        for ek, get in evals.items():
            E = get(name)
            P, blk = {}, {}
            for mname, spec in {**LADDER, **ECONOMY}.items():
                P[mname], coef = fit_predict(F[name], spec, maps, E)
                blk[mname] = evaluate_scores(E, P[mname], args.boot) | {"coef_fit": coef}
            steps = [("B0_gamblers_ruin", "B1_plant_flag"), ("M1_alive", "M2_alive_load"),
                     ("M3_alive_load_side", "B1_plant_flag"), ("B1_plant_flag", "B3_phase_clock"),
                     ("M3_alive_load_side", "M4_alive_load_mapside"),
                     ("E0_alive_side_flag", "E1_load"), ("E0_alive_side_flag", "E2_credits"),
                     ("E0_alive_side_flag", "E3_load_credits"), ("E1_load", "E3_load_credits")]
            blk["steps"] = {f"{a}->{b}": wr.compare(E, P[a], P[b], args.boot) for a, b in steps}
            ev[f"{ek}_{name}"] = blk
            print("eval", ek, name, {m: blk[m]["logloss_nats"] for m in P},
                  blk["steps"]["B0_gamblers_ruin->B1_plant_flag"], flush=True)
    R["evaluation"] = ev
    # CS transfer on K0 states
    cs = {}
    priors = {}
    for src in ("kaggle_mm", "esta"):
        C = cs_data(src)
        X, y, w, _m, pen = matrices(C, CS_SPEC, [])
        beta = wr.fit_logit(X, y, w, list(pen))
        priors[src] = beta
        cs[src] = {"rounds": len(C.rounds), "states": len(C.S), "coef": beta.round(4).tolist()}
        for ek, get in evals.items():
            E = get("K0")
            p = wr.sig(matrices(E, CS_SPEC, [])[0] @ beta)
            pv, _ = fit_predict(F["K0"], CS_SPEC, [], E)
            cs[src][ek] = {"cs_only": evaluate_scores(E, p, args.boot),
                           "val_only_all_fit": evaluate_scores(E, pv, args.boot)["logloss_nats"],
                           "val_minus_cs": wr.compare(E, p, pv, args.boot)}
        print("cs", src, cs[src]["coef"], {k: cs[src][k]["cs_only"]["logloss_nats"] for k in evals}, flush=True)
    Xv, yv, wv, _m, penv = matrices(F["K0"], CS_SPEC, [])
    cs["valorant_fit_coef"] = wr.fit_logit(Xv, yv, wv, list(penv)).round(4).tolist()
    cs["columns"] = column_names(CS_SPEC)
    cs["curve_pooled"] = learning_curve(F["K0"], evals["pooled"]("K0"), priors, args.boot)
    R["cs_transfer"] = cs
    # rank bands on FIT
    R["rank_bands"] = {"G_B1": band_coefs(F["G"], strata, LADDER["B1_plant_flag"], args.band_boot),
                       "K_B1": band_coefs(F["K"], strata, LADDER["B1_plant_flag"], args.band_boot)}
    print("bands", json.dumps(R["rank_bands"]["G_B1"]), flush=True)
    R["elapsed_s"] = round(time.time() - t0, 1)
    (out / "results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    print("wrote", out / "results.json", R["elapsed_s"], "s")
    if args.record:
        record_results(R)


def record_results(R: dict):
    from reticle import metrics
    deps = {"tool_version": VERSION, "reference": R["reference"], "parse": PARSED.name,
            "RIDGE": wr.RIDGE, "ECE_BINS": ECE_BINS}
    ctx = {"fit_matches": R["admission"]["FIT"]["matches"], "fit_rounds": R["admission"]["FIT"]["admitted"]}
    a = R["admission"]
    vals = {f"{k}.{f}": a[k][f] for k in ("FIT", "E1", "E2") for f in ("matches", "rounds_listed", "admitted")}
    vals.update({f"{k}.excluded.{r}": n for k in ("FIT", "E1", "E2") for r, n in a[k]["excluded"].items()})
    vals.update({f"split.{k}": v for k, v in a["split"].items()})
    metrics.record("winprob", part="own_admission", values=vals, deps=deps, context=ctx)
    for name, blk in R["fit_lomo"].items():
        metrics.record("winprob", part=f"own_fit_lomo/{name}",
                       values={f"{m}.nats": b["logloss_nats"] for m, b in blk.items()}
                       | {f"{m}.brier": b["brier"] for m, b in blk.items()},
                       deps=deps, context=ctx)
    for key, blk in R["evaluation"].items():
        vals, ci = {}, {}
        for m, b in blk.items():
            if m == "steps":
                continue
            for f in ("logloss_nats", "brier", "ece"):
                vals[f"{m}.{f}"] = b[f]
                ci[f"{m}.{f}"] = b[f"{f}_ci95"]
            vals[f"{m}.states"] = b["n_states"]
        for s, c in blk["steps"].items():
            vals[f"step:{s}.nats"] = c["improvement_nats"]
            ci[f"step:{s}.nats"] = c["ci95_nats"]
        metrics.record("winprob", part=f"own_eval/{key}", values=vals, ci=ci, deps=deps, context=ctx)
    cs = R["cs_transfer"]
    vals, ci = {}, {}
    for src in ("kaggle_mm", "esta"):
        vals[f"{src}.rounds"] = cs[src]["rounds"]
        for ek in ("E1", "E2", "pooled"):
            b = cs[src][ek]
            vals[f"{src}.{ek}.cs_only.nats"] = b["cs_only"]["logloss_nats"]
            vals[f"{src}.{ek}.val_only.nats"] = b["val_only_all_fit"]
            vals[f"{src}.{ek}.val_minus_cs.nats"] = b["val_minus_cs"]["improvement_nats"]
            ci[f"{src}.{ek}.val_minus_cs.nats"] = b["val_minus_cs"]["ci95_nats"]
    metrics.record("winprob", part="cs_transfer", values=vals, ci=ci, deps=deps, context=ctx)
    vals, ci = {}, {}
    for n, b in cs["curve_pooled"].items():
        vals[f"n{n}.val_only.nats"] = b["val_only_nats"]
        for src in ("kaggle_mm", "esta"):
            vals[f"n{n}.{src}.gain.nats"] = b[src]["gain_nats"]
            ci[f"n{n}.{src}.gain.nats"] = b[src]["gain_ci95"]
    metrics.record("winprob", part="cs_curve", values=vals, ci=ci, deps=deps, context=ctx)
    for key, blk in R["rank_bands"].items():
        vals, ci = {}, {}
        for i, c in enumerate(blk["columns"]):
            for band in BANDS:
                vals[f"{band}.{c}"] = blk[band]["coef"][i]
            vals[f"diff.{c}"] = blk["difference"]["coef"][i]
            ci[f"diff.{c}"] = blk["difference"]["ci95"][i]
        vals.update({f"{band}.matches": blk[band]["matches"] for band in BANDS})
        metrics.record("winprob", part=f"rank_bands/{key}", values=vals, ci=ci, deps=deps, context=ctx)
    print("recorded winprob parts")


if __name__ == "__main__":
    main()
