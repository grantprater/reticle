r"""The player's performance across a match, against his team and his lobby.

    .\.venv\Scripts\python.exe prototypes\match_arc.py run [--set captured|history] [--boot N] [--record] [--chart]
    .\.venv\Scripts\python.exe prototypes\match_arc.py chat-cost [--record]

`"wire": "no"`: a consumer analysis that answers one coaching question (does
the player decline over a match, beyond his team and lobby?) from stored
match records. It decides nothing in the pipeline, and nothing in `reticle/`
reads it.

What it reads
-------------
Nothing it computes from pixels, a reader, a tracker or an adjudicator. The
per-player, per-round table is `player_profile.features`' `pr` (kills, deaths,
deaths to enemies, first kill and first death of the round, damage to enemies,
round won, side by the rounds owner's rule, buy band by the team's mean
loadout), built from the Riot match records (`riot_ground_truth.riot_records`)
and the player's HenrikDev history through `ladder_fetch.parse_matches`, the
owner of that schema; `player_profile.load` applies its exclusions (unrated
records, kept replays without a capture) and pseudonymises every peer. The
player is the parsed `is_owner` row (`ladder_fetch.owner_accounts` merged with
`riot_ground_truth.identify_player`). This module adds only arrangements of
those rows: the score before each round, the time of each player's first kill
or death, and his position at the round's first kill (the record's
`playerLocations`, the victim's own location for the victim).

Two match sets
--------------
`captured` (the default): competitive Riot records whose capture session is a
match session, a manifest capture longer than `MATCH_MIN_S`. `history`: the
player's own competitive matches in the HenrikDev store (`has_owner`), none of
them captured. The held-out replay (`replay_layer.HELD_OUT`) has no Riot record
and never enters; `d3dcfb182ab1` has a replay but no Riot record, and the
replay layer's `rounds` table carries no round winner, so it is left out
rather than joined from a second source.

What it measures, and the choices
---------------------------------
Groups: the player (`owner`), his four teammates (`mates`), the five enemies
(`enemies`), his nine lobby peers (`peers`), and the whole lobby (`lobby`).
Regulation rounds are 0-23; overtime is reported apart.

- Contrasts: rounds 1-3 against 4-24 (`early_late`) and the first half
  against the second (`half`); the per-round slope over 0-23 (`slope`). Each
  is reported raw (ratio of summed values) and adjusted: least squares within
  each player-match (match fixed effects) on the period, the buy band
  (pistol, eco, force; full is the base) and the attacking side. The score
  before a round is no control: it is the sum of the match's earlier rounds,
  so within a match it carries the outcome being measured, and adding it
  (clipped to +-`SCORE_CLIP`) moved the peers' round-win share, 0.5 by
  construction, by -0.10 from rounds 1-3 to 4-24 on the captured set. Score
  state enters only the tilt proxy, a contrast between teammates in the same
  rounds. The cleanest contrast is the player's change against his
  teammates': they share his rounds, buy band, side and score.
- Differences between groups (owner minus mates, minus enemies, minus peers)
  use the same bootstrap draw, so their intervals are the difference's own.
- Intervals: percentile, 95%, resampling matches with replacement
  (`BOOT` draws, `SEED`). Demeaning within a player-match is unchanged by a
  match weight, so each draw reweights stored per-match cross-products.
- Regression to the mean: player-matches split at their group's median
  damage per round in rounds 1-3; the change from rounds 1-3 to 4-24 in each
  half of the split, and unsplit. A decline only after strong starts, with a
  matching rise after weak ones, is regression, not decline.
- Enemy adaptation: the duel share kills / (kills + deaths to enemies), the
  player's change against his teammates' change.
- Impatience: the time of a player's first kill or death in a round (the
  record's round time), its per-round slope against the peers'.
- Predictability: the distance between a player's position at the round's
  first kill and his position at the previous same-half round's first kill;
  a repeat is a distance under `REPEAT_CM`, a choice. Its slope over the half,
  and the first-death rate after a repeat against after none.
- Tilt proxy: the player minus his teammates in damage per round, when his
  team trails by `BEHIND` or more against otherwise.

Not measured: focus (the execution readers are not built), annoyance (no
reader counts chat; see `chat-cost`).

Output: `<store>/analysis/match-arc-20261007/` (JSON per set, the chart).
The console prints aggregates only; peers appear only pooled.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import player_profile as pp  # noqa: E402
import riot_ground_truth as rgt  # noqa: E402
from reticle import metrics  # noqa: E402
from reticle.rounds import HALF_ROUNDS  # noqa: E402

VERSION = "match-arc-0.1.0"
STORE = pp.STORE
OUT = STORE / "analysis" / "match-arc-20261007"
#: A match session is a manifest capture longer than 15 minutes, the corpus's rule.
MATCH_MIN_S = 900.0
REG_ROUNDS = 2 * HALF_ROUNDS
EARLY = 3
SCORE_CLIP = 5
BEHIND = 3
REPEAT_CM = 1000.0
BOOT = 2000
SEED = 20261007
GROUPS = ("owner", "mates", "enemies", "peers", "lobby")
METRICS = ("dmg", "kd", "surv", "fk", "fd", "won", "kills", "deaths")


# ----------------------------------------------------------------- data

def match_sessions(store: Path = STORE) -> dict[str, float]:
    """Session id -> capture minutes, for manifest captures over `MATCH_MIN_S`."""
    out = {}
    for p in sorted((Path(store) / "manifests").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        ms = (d.get("source") or {}).get("duration_ms") or 0.0
        if ms / 1000.0 > MATCH_MIN_S:
            out[d["session_id"]] = ms / 60000.0
    return out


ROWS_SQL = f"""
with fe as (
  select match_id, round, p player, min(time_in_round_ms) t from (
    select match_id, round, killer p, time_in_round_ms from k where xk
    union all select match_id, round, victim p, time_in_round_ms from k where xk)
  group by 1, 2, 3),
fk2 as (
  select match_id, round, kill, victim, victim_x, victim_y from (
    select *, row_number() over (partition by match_id, round
      order by time_in_round_ms, kill) rn from k where xk) where rn = 1),
op as (
  select f.match_id, f.round, p.player, p.x, p.y from fk2 f
  join t_positions p on p.match_id = f.match_id and p.kill = f.kill
   and p.event = 'kill'
  union all select match_id, round, victim, victim_x, victim_y from fk2),
sc as (
  select r.match_id, r.round, t.team,
    count(*) filter (where r2.winning_team = t.team) own,
    count(*) filter (where r2.winning_team is not null and r2.winning_team <> t.team) opp
  from rnd r join (select distinct match_id, team from pr) t using (match_id)
  left join rnd r2 on r2.match_id = r.match_id and r2.round < r.round
  group by 1, 2, 3),
ow as (select match_id, any_value(team) team from t_players where is_owner group by 1)
select pr.match_id, pr.round, pr.player, (pr.player in (
         select player from t_players o where o.match_id = pr.match_id and o.is_owner)) is_owner,
  (pr.team = ow.team) mate, pr.side = 'attack' attack, pr.buy, pr.won, pr.kills,
  pr.deaths, pr.deaths_x, pr.fk, pr.fd, pr.dmg, sc.own, sc.opp, fe.t t_eng,
  op.x ox, op.y oy
from pr join ow using (match_id)
left join sc on sc.match_id = pr.match_id and sc.round = pr.round and sc.team = pr.team
left join fe on fe.match_id = pr.match_id and fe.round = pr.round and fe.player = pr.player
left join op on op.match_id = pr.match_id and op.round = pr.round and op.player = pr.player
order by pr.match_id, pr.player, pr.round
"""


def load_rows(store: Path = STORE) -> dict:
    """Every player-round of the player's matches as numpy columns, with the
    match set each match belongs to and the counts behind the selection."""
    D = pp.load(store)
    c = pp.connect(D["tables"])
    pp.features(c)
    rel = c.execute(ROWS_SQL)
    names = [d[0] for d in rel.description]
    cols = list(zip(*rel.fetchall()))
    R = {n: np.array(v) for n, v in zip(names, cols)}
    M = c.execute("select match_id, source, has_owner, captured from t_matches").fetchall()
    src = {m: s for m, s, _h, _c in M}
    sess = {d["match"]["matchInfo"]["matchId"]: s for s, d in rgt.riot_records(store).items()}
    msess = match_sessions(store)
    captured = {m for m, s in src.items() if s == "riot" and sess.get(m) in msess}
    history = {m for m, s, h, _c in M if s == "ladder" and h}
    D["c"] = c
    return {"rows": R, "captured": captured, "history": history, "sessions": sess,
            "match_sessions": msess, "counts": D["counts"], "side_check": pp.side_check(c, D["riot_roles"])}


def prepare(R: dict, keep: set[str]) -> dict:
    """The rows of one match set, typed, with groups and derived columns."""
    m = np.isin(R["match_id"], np.array(sorted(keep), dtype=object))
    X = {k: v[m] for k, v in R.items()}
    mids, mi = np.unique(X["match_id"], return_inverse=True)
    pk = np.char.add(X["match_id"].astype(str), X["player"].astype(str))
    _u, pi = np.unique(pk, return_inverse=True)
    own = X["is_owner"].astype(bool)
    mate = X["mate"].astype(bool) & ~own
    g = {"owner": own, "mates": mate, "enemies": ~X["mate"].astype(bool),
         "peers": ~own, "lobby": np.ones(own.size, bool)}
    f = lambda k: np.array([np.nan if v is None else v for v in X[k]], float)  # noqa: E731
    deaths, deaths_x, kills = f("deaths"), f("deaths_x"), f("kills")
    rnd = X["round"].astype(int)
    out = {"mi": mi, "pi": pi, "n_match": len(mids), "round": rnd, "g": g,
           "attack": X["attack"].astype(bool), "buy": X["buy"].astype(str),
           "dmg": f("dmg"), "kills": kills, "deaths": deaths, "deaths_x": deaths_x,
           "kd": kills - deaths, "surv": (deaths == 0).astype(float),
           "fk": f("fk"), "fd": f("fd"), "won": f("won"),
           "diff": np.clip(f("own") - f("opp"), -SCORE_CLIP, SCORE_CLIP),
           "behind": (f("opp") - f("own")) >= BEHIND,
           "t_eng": f("t_eng") / 1000.0, "ox": f("ox"), "oy": f("oy")}
    out["d_lag"] = repeat_distance(out)
    return out


def repeat_distance(S: dict) -> np.ndarray:
    """Distance (cm) from a player's position at the round's first kill to his
    position at the previous round of the same half, NaN where either is
    missing or the round opens a half or lies in overtime."""
    r = S["round"]
    half = np.where(r < HALF_ROUNDS, 0, np.where(r < REG_ROUNDS, 1, -1))
    o = np.lexsort((r, half, S["pi"]))
    d = np.full(r.size, np.nan)
    same = np.r_[False, (S["pi"][o][1:] == S["pi"][o][:-1]) & (half[o][1:] == half[o][:-1])
                 & (half[o][1:] >= 0) & (r[o][1:] == r[o][:-1] + 1)]
    dx = np.r_[np.nan, np.diff(S["ox"][o])]
    dy = np.r_[np.nan, np.diff(S["oy"][o])]
    d[o] = np.where(same, np.hypot(dx, dy), np.nan)
    return d


# ----------------------------------------------------------------- bootstrap

def weights(n: int, boot: int, seed: int = SEED) -> np.ndarray:
    """Row 0 the full sample; rows 1.. multinomial match counts."""
    rng = np.random.default_rng(seed)
    return np.vstack([np.ones(n), rng.multinomial(n, np.full(n, 1.0 / n), size=boot)])


def ci(v: np.ndarray) -> list[float]:
    v = v[1:][np.isfinite(v[1:])]
    if not v.size:
        return [float("nan")] * 2
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def ratio(W, mi, n, y, sel) -> np.ndarray:
    """Weighted mean of y over `sel`, per bootstrap draw."""
    ok = sel & np.isfinite(y)
    num = np.bincount(mi[ok], y[ok], n)
    den = np.bincount(mi[ok], None, n).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (W @ num) / (W @ den)


def demean(v: np.ndarray, pi: np.ndarray) -> np.ndarray:
    s = np.bincount(pi, v)
    c = np.bincount(pi).astype(float)
    return v - (s / np.maximum(c, 1))[pi]


def design(S: dict, sel: np.ndarray, period: np.ndarray, controls: bool) -> np.ndarray:
    cols = [period[sel].astype(float)]
    if controls:
        b = S["buy"][sel]
        cols += [(b == "pistol").astype(float), (b == "eco").astype(float),
                 (b == "force").astype(float), S["attack"][sel].astype(float)]
    return np.column_stack(cols)


def fe_coef(W, S, y, sel, period, controls=True) -> np.ndarray:
    """The period coefficient within player-matches, per bootstrap draw."""
    sel = sel & np.isfinite(y) & np.isfinite(period)
    pi = np.unique(S["pi"][sel], return_inverse=True)[1]
    X = design(S, sel, period, controls)
    X = np.column_stack([demean(X[:, j], pi) for j in range(X.shape[1])])
    yy = demean(y[sel], pi)
    keep = np.flatnonzero(X.std(0) > 1e-12)
    if 0 not in keep:
        return np.full(W.shape[0], np.nan)
    X = X[:, keep]
    k, n, mi = X.shape[1], S["n_match"], S["mi"][sel]
    XtX = np.zeros((n, k, k))
    np.add.at(XtX, mi, X[:, :, None] * X[:, None, :])
    Xty = np.zeros((n, k))
    np.add.at(Xty, mi, X * yy[:, None])
    A = np.einsum("bm,mij->bij", W, XtX) + 1e-9 * np.eye(k)
    rhs = np.einsum("bm,mi->bi", W, Xty)
    return np.linalg.solve(A, rhs[..., None])[:, 0, 0]


# ----------------------------------------------------------------- analyses

def summarise(v: np.ndarray, nd: int = 4) -> dict:
    return {"est": round(float(v[0]), nd), "ci": [round(x, nd) for x in ci(v)]}


def contrasts(S: dict, W: np.ndarray) -> dict:
    """Raw and adjusted period contrasts per metric, group and group difference."""
    r, reg = S["round"], S["round"] < REG_ROUNDS
    periods = {"early_late": (r >= EARLY).astype(float),
               "half": (r >= HALF_ROUNDS).astype(float),
               "slope": r.astype(float)}
    out = {}
    for met in METRICS:
        y = S[met]
        for pname, per in periods.items():
            raw, adj = {}, {}
            for gname in GROUPS:
                sel = reg & S["g"][gname]
                if gname in ("lobby", "peers") and met in ("kd", "won") or                         gname in ("mates", "enemies") and met == "won":
                    continue
                adj[gname] = fe_coef(W, S, y, sel, per)
                if pname != "slope":
                    a = ratio(W, S["mi"], S["n_match"], y, sel & (per == 0))
                    b = ratio(W, S["mi"], S["n_match"], y, sel & (per == 1))
                    raw[gname] = (a, b)
            res = {}
            for gname, v in adj.items():
                res[gname] = {"adjusted": summarise(v)}
                if gname in raw:
                    a, b = raw[gname]
                    res[gname].update({"before": summarise(a), "after": summarise(b),
                                       "raw_change": summarise(b - a)})
            for other in ("mates", "enemies", "peers"):
                if other in adj and met != "won":
                    res[f"owner_minus_{other}"] = {"adjusted": summarise(adj["owner"] - adj[other])}
                    if pname != "slope":
                        (a0, b0), (a1, b1) = raw["owner"], raw[other]
                        res[f"owner_minus_{other}"]["raw_change"] = summarise((b0 - a0) - (b1 - a1))
            out[f"{met}.{pname}"] = res
    return out


def duel_share(S: dict, W: np.ndarray) -> dict:
    """kills / (kills + deaths to enemies), by half and early/late, owner vs mates."""
    r, reg = S["round"], S["round"] < REG_ROUNDS
    k, d = S["kills"], S["deaths_x"]
    out = {}
    for pname, per in {"early_late": r >= EARLY, "half": r >= HALF_ROUNDS}.items():
        ch = {}
        for gname in ("owner", "mates", "enemies"):
            sel = reg & S["g"][gname]
            v = []
            for p in (False, True):
                s = sel & (per == p)
                num = W @ np.bincount(S["mi"][s], k[s], S["n_match"])
                den = W @ np.bincount(S["mi"][s], k[s] + d[s], S["n_match"])
                v.append(num / den)
            ch[gname] = v
        res = {g: {"before": summarise(a), "after": summarise(b), "change": summarise(b - a)}
               for g, (a, b) in ch.items()}
        res["owner_minus_mates"] = {"change": summarise((ch["owner"][1] - ch["owner"][0])
                                                        - (ch["mates"][1] - ch["mates"][0]))}
        out[pname] = res
    return out


def rtm(S: dict, W: np.ndarray, met: str = "dmg") -> dict:
    """Change from rounds 1-3 to 4-24 per player-match, split at the group's
    median early value."""
    reg = S["round"] < REG_ROUNDS
    y = S[met]
    out = {}
    for gname in ("owner", "mates", "enemies", "peers"):
        sel = reg & S["g"][gname] & np.isfinite(y)
        pi = S["pi"][sel]
        e = S["round"][sel] < EARLY
        npi = pi.max() + 1
        es = np.bincount(pi[e], y[sel][e], npi) / np.maximum(np.bincount(pi[e], None, npi), 1)
        ls = np.bincount(pi[~e], y[sel][~e], npi) / np.maximum(np.bincount(pi[~e], None, npi), 1)
        has = (np.bincount(pi[e], None, npi) > 0) & (np.bincount(pi[~e], None, npi) > 0)
        pm = np.zeros(npi, int)
        pm[pi] = S["mi"][sel]
        med = np.median(es[has])
        res = {"median_early": round(float(med), 2),
               "corr_early_late": round(float(np.corrcoef(es[has], ls[has])[0, 1]), 4)}
        for name, m in (("all", has), ("strong_start", has & (es > med)),
                        ("weak_start", has & (es <= med))):
            num = W @ np.bincount(pm[m], (ls - es)[m], S["n_match"])
            den = W @ np.bincount(pm[m], None, S["n_match"]).astype(float)
            res[name] = {"n": int(m.sum()), "late_minus_early": summarise(num / den, 2)}
        out[gname] = res
    return out


def impatience(S: dict, W: np.ndarray) -> dict:
    """Slope of the time of first kill or death over round index."""
    reg = S["round"] < REG_ROUNDS
    sl = {g: fe_coef(W, S, S["t_eng"], reg & S["g"][g], S["round"].astype(float))
          for g in ("owner", "mates", "peers")}
    res = {g: {"slope_s_per_round": summarise(v)} for g, v in sl.items()}
    res["owner_minus_peers"] = {"slope_s_per_round": summarise(sl["owner"] - sl["peers"])}
    res["owner_minus_mates"] = {"slope_s_per_round": summarise(sl["owner"] - sl["mates"])}
    for g in ("owner", "peers"):
        res[g]["mean_s"] = summarise(ratio(W, S["mi"], S["n_match"], S["t_eng"], reg & S["g"][g]), 2)
    return res


def predictability(S: dict, W: np.ndarray) -> dict:
    """Repeat-position slope over the half and first deaths after repeats."""
    reg = S["round"] < REG_ROUNDS
    d = S["d_lag"]
    rep = np.where(np.isfinite(d), (d < REPEAT_CM).astype(float), np.nan)
    rih = (S["round"] % HALF_ROUNDS).astype(float)
    out = {"coverage": {g: round(float(np.isfinite(d[reg & S["g"][g]]).mean()), 4)
                        for g in ("owner", "peers")}}
    sl = {g: fe_coef(W, S, rep, reg & S["g"][g], rih, controls=False) for g in ("owner", "peers")}
    out["repeat_share"] = {g: summarise(ratio(W, S["mi"], S["n_match"], rep, reg & S["g"][g]))
                           for g in ("owner", "peers")}
    out["repeat_slope_per_round"] = {g: summarise(v) for g, v in sl.items()}
    out["repeat_slope_per_round"]["owner_minus_peers"] = summarise(sl["owner"] - sl["peers"])
    pun = {}
    for g in ("owner", "peers"):
        sel = reg & S["g"][g] & np.isfinite(rep)
        a = ratio(W, S["mi"], S["n_match"], S["fd"], sel & (rep == 1))
        b = ratio(W, S["mi"], S["n_match"], S["fd"], sel & (rep == 0))
        pun[g] = a - b
        out.setdefault("first_death_after_repeat_minus_none", {})[g] = summarise(a - b)
    out["first_death_after_repeat_minus_none"]["owner_minus_peers"] = summarise(pun["owner"] - pun["peers"])
    return out


def tilt(S: dict, W: np.ndarray) -> dict:
    """Owner minus mates damage per round when his team trails by `BEHIND`+ vs not."""
    reg = S["round"] < REG_ROUNDS
    res = {}
    for name, m in (("behind", S["behind"]), ("not_behind", ~S["behind"])):
        o = ratio(W, S["mi"], S["n_match"], S["dmg"], reg & m & S["g"]["owner"])
        t = ratio(W, S["mi"], S["n_match"], S["dmg"], reg & m & S["g"]["mates"])
        res[name] = {"owner_minus_mates_dmg": summarise(o - t, 2),
                     "owner_rounds": int((reg & m & S["g"]["owner"]).sum())}
    return res


def overtime(S: dict, W: np.ndarray) -> dict:
    ot = S["round"] >= REG_ROUNDS
    out = {"ot_rounds_owner": int((ot & S["g"]["owner"]).sum())}
    for met in ("dmg", "kd"):
        o = ratio(W, S["mi"], S["n_match"], S[met], ot & S["g"]["owner"])
        t = ratio(W, S["mi"], S["n_match"], S[met], ot & S["g"]["mates"])
        out[met] = {"owner": summarise(o, 2), "mates": summarise(t, 2),
                    "owner_minus_mates": summarise(o - t, 2)}
    return out


def curves(S: dict, W: np.ndarray) -> dict:
    """Per regulation round index: mean of each chart metric per group, bands."""
    out = {}
    for met, groups in (("dmg", ("owner", "mates", "lobby")), ("surv", ("owner", "mates", "lobby")),
                        ("won", ("owner",))):
        out[met] = {}
        for g in groups:
            est, lo, hi, n = [], [], [], []
            for r in range(REG_ROUNDS):
                sel = S["g"][g] & (S["round"] == r)
                v = ratio(W, S["mi"], S["n_match"], S[met], sel)
                est.append(float(v[0]))
                a, b = ci(v)
                lo.append(a)
                hi.append(b)
                n.append(int(len(np.unique(S["mi"][sel]))))
            out[met][g] = {"est": est, "lo": lo, "hi": hi, "n_matches": n}
    return out


def arc(S: dict, boot: int = BOOT) -> dict:
    W = weights(S["n_match"], boot)
    return {"n_matches": S["n_match"],
            "owner_rounds": int(S["g"]["owner"].sum()),
            "owner_regulation_rounds": int((S["g"]["owner"] & (S["round"] < REG_ROUNDS)).sum()),
            "contrasts": contrasts(S, W), "duel_share": duel_share(S, W), "rtm": rtm(S, W),
            "impatience": impatience(S, W), "predictability": predictability(S, W),
            "tilt": tilt(S, W), "overtime": overtime(S, W), "curves": curves(S, W)}


# ----------------------------------------------------------------- record

HEADLINE = (
    ("dmg.early_late", ("owner", "mates", "enemies", "lobby", "owner_minus_peers", "owner_minus_mates")),
    ("dmg.half", ("owner", "mates", "enemies", "lobby", "owner_minus_peers", "owner_minus_mates")),
    ("dmg.slope", ("owner", "mates", "lobby", "owner_minus_peers")),
    ("kd.early_late", ("owner", "mates", "owner_minus_mates", "owner_minus_enemies")),
    ("kd.half", ("owner", "mates", "owner_minus_mates", "owner_minus_enemies")),
    ("surv.half", ("owner", "mates", "lobby", "owner_minus_peers")),
    ("surv.early_late", ("owner", "mates", "lobby", "owner_minus_peers")),
    ("won.early_late", ("owner",)),
    ("won.half", ("owner",)),
    ("fd.half", ("owner", "owner_minus_peers")),
    ("fk.half", ("owner", "owner_minus_peers")),
)


def flat(A: dict) -> tuple[dict, dict]:
    vals, cis = {}, {}

    def put(k, s):
        vals[k] = s["est"]
        cis[k] = s["ci"]
    for key, groups in HEADLINE:
        for g in groups:
            e = A["contrasts"][key].get(g)
            if e:
                put(f"{key}.{g}.adj", e["adjusted"])
                if "raw_change" in e:
                    put(f"{key}.{g}.raw", e["raw_change"])
                if "before" in e:
                    put(f"{key}.{g}.before", e["before"])
                    put(f"{key}.{g}.after", e["after"])
    for p in ("early_late", "half"):
        put(f"duel.{p}.owner_minus_mates", A["duel_share"][p]["owner_minus_mates"]["change"])
        put(f"duel.{p}.owner", A["duel_share"][p]["owner"]["change"])
    for g in ("owner", "peers"):
        for s in ("all", "strong_start", "weak_start"):
            put(f"rtm.{g}.{s}", A["rtm"][g][s]["late_minus_early"])
    put("impatience.owner_minus_peers", A["impatience"]["owner_minus_peers"]["slope_s_per_round"])
    put("impatience.owner", A["impatience"]["owner"]["slope_s_per_round"])
    pr = A["predictability"]
    put("repeat.slope.owner_minus_peers", pr["repeat_slope_per_round"]["owner_minus_peers"])
    put("repeat.punish.owner_minus_peers", pr["first_death_after_repeat_minus_none"]["owner_minus_peers"])
    put("repeat.share.owner", pr["repeat_share"]["owner"])
    for k in ("behind", "not_behind"):
        put(f"tilt.{k}", A["tilt"][k]["owner_minus_mates_dmg"])
    vals["n_matches"] = A["n_matches"]
    vals["owner_regulation_rounds"] = A["owner_regulation_rounds"]
    return vals, cis


def record_run(name: str, A: dict, ctx: dict) -> None:
    vals, cis = flat(A)
    metrics.record("match_arc", part=name, session="", values=vals,
                   deps={"version": VERSION, "player_profile": pp.VERSION, "boot": BOOT,
                         "seed": SEED, "early": EARLY, "repeat_cm": REPEAT_CM},
                   context=ctx, ci=cis,
                   note="player vs team vs lobby across the match; stored match records")


# ----------------------------------------------------------------- chart

def _hex(h: str, a: int = 255) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) + (a,)


def chart(sets: dict, path: Path) -> None:
    """Rows: damage per round, survival, the team's round wins; one column per
    match set. Drawn with Pillow (the venv carries no plotting library) at
    twice the size and shrunk by area averaging."""
    from PIL import Image, ImageDraw, ImageFont
    K = 2
    col = {"owner": "#2a78d6", "mates": "#eb6834", "lobby": "#1baf7a", "team": "#4a3aa7"}
    lab = {"owner": "You", "mates": "Your 4 teammates", "lobby": "Whole lobby (all 10)",
           "team": "Your team (bottom row)"}
    rows = [("dmg", "Damage dealt per round"), ("surv", "Share of rounds survived"),
            ("won", "Share of rounds your team won")]
    font = lambda n: ImageFont.truetype("C:/Windows/Fonts/arial.ttf", n * K)  # noqa: E731
    bold = lambda n: ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", n * K)  # noqa: E731
    pw, ph, ml, mr, mt, mb, top = 560, 230, 60, 20, 44, 34, 92
    Wd = (ml + pw + mr) * len(sets)
    Ht = top + (mt + ph + mb) * len(rows) + 30
    img = Image.new("RGBA", (Wd * K, Ht * K), _hex("#fcfcfb"))
    d = ImageDraw.Draw(img)
    ink, ink2, grid = _hex("#0b0b0b"), _hex("#52514e"), _hex("#e6e5e0")
    d.text((14 * K, 10 * K), "Your performance across the match, against your team and your lobby",
           font=bold(17), fill=ink)
    d.text((14 * K, 36 * K), "Lines: mean per round of the match. Bands: 95% interval, resampling whole "
           "matches. Grey: rounds 1-3. Dashed: the side switch.", font=font(12), fill=ink2)
    lx = 14
    for g in ("owner", "mates", "lobby", "team"):
        d.line([(lx * K, 70 * K), ((lx + 22) * K, 70 * K)], fill=_hex(col[g]), width=3 * K)
        d.text(((lx + 28) * K, 62 * K), lab[g], font=font(13), fill=ink)
        lx += 40 + int(d.textlength(lab[g], font=font(13)) / K)
    for j, (sname, A) in enumerate(sets.items()):
        x0 = j * (ml + pw + mr) + ml
        for i, (met, title) in enumerate(rows):
            y0 = top + i * (mt + ph + mb) + mt
            C = A["curves"][met]
            if met == "won":
                C = {"team": C["owner"]}
            vals = np.concatenate([np.array(C[g][k], float) for g in C for k in ("lo", "hi")])
            vals = vals[np.isfinite(vals)]
            lo, hi = {"surv": (0.0, 0.6), "won": (0.2, 0.8)}.get(met) or (float(vals.min()),
                                                                         float(vals.max()))
            if met == "dmg":
                lo, hi = 20 * np.floor(lo / 20), 20 * np.ceil(hi / 20)
            X = lambda r: (x0 + (r - 0.5) / REG_ROUNDS * pw) * K  # noqa: E731
            Y = lambda v: (y0 + ph - (v - lo) / (hi - lo) * ph) * K  # noqa: E731
            d.rectangle([X(0.5), y0 * K, X(EARLY + 0.5), (y0 + ph) * K], fill=_hex("#ecebe7"))
            step = 20 if met == "dmg" else 0.1
            t = lo
            while t <= hi + 1e-9:
                d.line([(x0 * K, Y(t)), ((x0 + pw) * K, Y(t))], fill=grid, width=K)
                txt = f"{t:.0f}" if met == "dmg" else f"{t:.0%}"
                d.text(((x0 - 8) * K - d.textlength(txt, font=font(11)), Y(t) - 7 * K), txt,
                       font=font(11), fill=ink2)
                t += step
            for yy in range(int(y0), int(y0 + ph), 8):
                d.line([(X(HALF_ROUNDS + 0.5), yy * K), (X(HALF_ROUNDS + 0.5), (yy + 4) * K)],
                       fill=_hex("#8a8984"), width=K)
            for r in range(1, REG_ROUNDS + 1, 3):
                d.text((X(r) - 4 * K, (y0 + ph + 6) * K), str(r), font=font(11), fill=ink2)
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            for g, cv in C.items():
                e, l, h = (np.array(cv[k], float) for k in ("est", "lo", "hi"))
                l, h = np.clip(l, lo, hi), np.clip(h, lo, hi)
                ok = np.isfinite(l) & np.isfinite(h)
                rr = np.arange(1, REG_ROUNDS + 1)[ok]
                poly = [(X(r), Y(v)) for r, v in zip(rr, h[ok])] +                        [(X(r), Y(v)) for r, v in zip(rr[::-1], l[ok][::-1])]
                if len(poly) > 2:
                    ld.polygon(poly, fill=_hex(col[g], 40))
            img.alpha_composite(layer)
            d = ImageDraw.Draw(img)
            for g, cv in C.items():
                e = np.array(cv["est"], float)
                pts = [(X(r + 1), Y(v)) for r, v in enumerate(e) if np.isfinite(v)]
                d.line(pts, fill=_hex(col[g]), width=2 * K, joint="curve")
                for px, py in pts:
                    d.ellipse([px - 3 * K, py - 3 * K, px + 3 * K, py + 3 * K], fill=_hex(col[g]),
                              outline=_hex("#fcfcfb"), width=K)
            head = f"{title}" + (f"   ({sname}, {A['n_matches']} matches)" if i == 0 else "")
            d.text((x0 * K, (y0 - 26) * K), head, font=bold(13), fill=ink)
            if i == len(rows) - 1:
                d.text((x0 * K, (y0 + ph + 20) * K), "Round of the match (regulation, 1-24)",
                       font=font(11), fill=ink2)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").resize((Wd, Ht), Image.Resampling.BOX).save(path)


# ----------------------------------------------------------------- chat cost

def chat_cost(store: Path = STORE, record_it: bool = False) -> dict:
    """What reading chat activity would cost, from manifests, cache records and
    the recorded scan timings; reads no pixels."""
    msess = match_sessions(store)
    have, gone = [], []
    for sid, mins in msess.items():
        d = json.loads((Path(store) / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
        (gone if d.get("video_retired") or not Path(d["source"]["path"]).is_file() else have).append(
            (sid, round(mins, 1)))
    rects = {}
    for p in (Path(store) / "roi_cache").glob("*/roi-cache-*/*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("session_id") in msess:
            rects.setdefault(d.get("roi"), set()).update(tuple(r) for r in d.get("rects", []))
    # does any stored rectangle reach the lower-left quarter, where the chat box sits?
    lower_left = {k: [r for r in v if r[0] < 960 and r[3] > 540 and r[1] < 1080 and r[2] > 0
                      and r[0] < 600] for k, v in rects.items()}
    rows = [json.loads(l) for l in (Path(store) / "notes" / "metrics.jsonl").open(encoding="utf-8")
            if '"scan_usage"' in l]
    decode = []
    for r in rows:
        if r.get("part", "").startswith(("roi_cache:killfeed_panel/video", "roi_cache:scoreboard/video")):
            sid = r.get("session")
            if sid in msess:
                decode.append(r["values"]["source_s"] / msess[sid])
    hud = [r["values"].get("feed_s_roi_cache_hud") / msess[r["session"]] for r in rows
           if "roi_cache:hud" in r.get("part", "") and r.get("session") in msess
           and r["values"].get("feed_s_roi_cache_hud")]
    out = {"match_sessions": len(msess), "with_video": have, "retired": len(gone),
           "cached_rects_lower_left": {k: sorted(v) for k, v in lower_left.items()},
           "standalone_decode_s_per_capture_min": round(float(np.median(decode)), 2) if decode else None,
           "decode_samples": len(decode),
           "hud_crop_feed_s_per_capture_min": round(float(np.median(hud)), 3) if hud else None,
           "with_video_minutes": round(sum(m for _s, m in have), 1)}
    if record_it and out["standalone_decode_s_per_capture_min"] is not None:
        metrics.record("match_arc", part="chat_cost", session="",
                       values={"match_sessions": out["match_sessions"], "with_video": len(have),
                               "retired": len(gone),
                               "decode_s_per_min": out["standalone_decode_s_per_capture_min"],
                               "hud_crop_s_per_min": out["hud_crop_feed_s_per_capture_min"],
                               "with_video_minutes": out["with_video_minutes"]},
                       deps={"version": VERSION, "match_min_s": MATCH_MIN_S},
                       context={"decode_samples": len(decode)},
                       note="chat box decode cost from manifests and recorded scan timings")
    return out


# ----------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", choices=("captured", "history", "both"), default="both")
    r.add_argument("--boot", type=int, default=BOOT)
    r.add_argument("--record", action="store_true")
    r.add_argument("--chart", action="store_true")
    cc = sub.add_parser("chat-cost")
    cc.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "chat-cost":
        print(json.dumps(chat_cost(record_it=a.record), indent=1))
        return 0
    L = load_rows()
    names = ("captured", "history") if a.set == "both" else (a.set,)
    res = {}
    for name in names:
        S = prepare(L["rows"], L[name])
        A = arc(S, a.boot)
        res[name] = A
        OUT.mkdir(parents=True, exist_ok=True)
        meta = {"version": VERSION, "set": name, "counts": L["counts"], "side_check": L["side_check"],
                "match_sessions": len(L["match_sessions"]),
                "sessions": sorted(L["sessions"][m] for m in L[name] if m in L["sessions"])}
        (OUT / f"match-arc-{name}.json").write_text(json.dumps({**meta, **A}, indent=1),
                                                    encoding="utf-8")
        print(f"{name}: {A['n_matches']} matches, {A['owner_regulation_rounds']} player regulation"
              f" rounds -> {OUT / f'match-arc-{name}.json'}")
        if a.record:
            record_run(name, A, {"matches": A["n_matches"], "sessions": len(meta["sessions"])})
    if a.chart:
        p = OUT / "match-arc-chart.png"
        chart({("captured matches" if k == "captured" else "your other competitive matches"): v
               for k, v in res.items()}, p)
        print(f"chart -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
