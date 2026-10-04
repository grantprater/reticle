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

The owner of round state
------------------------
`reticle ownership "round state win probability"` names `coaching-state`
(`reticle.coaching`, `observed_states`): reticle's answer to "what state was
the round in, and what does that predict?". Its docstring states its rule;
this file does not restate it. `round_filter` is a CANDIDATE to promote into
that owner, not a second owner: it answers the same question with a
distribution over alive counts built from the death stream's claims rather
than a point state. Promotion is one step: move the filter into
`reticle/coaching.py` as a producer beside `observed_states` (or as the state
`observed_states` hands its model), with the claim-class outcome rates stored
as a versioned table measured on audit samples rather than recomputed here
against Riot, the attacking side read from a reticle owner rather than Riot,
and `ownership.toml`'s `coaching-state` entry listing it in `produces`. Until
then it stays an experiment (`"wire": "no"`).

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
one with Riot kills within `rgt.MATCH_TOL_MS` (same side first, then across
sides) under the death-claim fit, and the claim's outcome is the matched
victim's side (claimed side, the other side, or no kill). That fit only pairs
a claim with its kill; where the instants sit is the alignment's business,
below. A revive claim's outcome is whether Riot's living sets show a revival
on its side across it. An `inferred_death` (no instant; it died in a capture
stall) enters at the end of its window and is right when it pairs, one to one
(`scipy.optimize.linear_sum_assignment`), with an unmatched Riot kill of its
side inside the window. A class with no training claims enters as missing at
random: it changes nothing and the instant counts it (`unrated`). Refusals
stay visible: a refused or unresolved claim enters with its class's measured
outcome probabilities, so its instant is scored with that uncertainty, never
dropped.

Classes, from stored fields only: `revive`; `entry_refused` (entry type
refused); `second_life`; `side_unknown`; `kill_unresolved` (victim status
not resolved); `kill_resolved`; `refused_entry`; `merged_entry`;
`inferred_death`.

Plant. The stored round table (`round-bounds`): planted when the plant time
precedes the instant. An unread plant (`spike_planted` null, or planted with
no time) mixes the flag with the Riot rate of planted-by-t on the other
matches.

Side. Riot's. Reticle reads which scoreline side is the player's
(`round-bounds`), not which team attacks; this is the one input still taken
from Riot, and the gap is stated, not hidden.

Outcome model. The reference's ridge logistic on alive, side and the plant
flag (no clock, no loadout), fitted on Riot's 1 s grid states, leave one
match out: `winprob_reference.lomo`. P(win) = sum over z of P(win | z) P(z).
The oracle is the same model on Riot's exact state at the same instants;
their difference is the observation cost.

Instants and the two alignments
-------------------------------
Riot's 1 s grid (`winprob_reference.grid_states`) of the captured matches,
placed in capture time two ways, both scored:

* `clock` (0.2.0, the honest one). `rgt.fit_alignment` pairs Riot's round
  starts with `gametime`'s barrier drops (`t_live_ms`, read from the HUD
  clock), evidence independent of the death claims. Claims, the round table
  and the plant all compare at the Riot instant itself, so a claim the
  killfeed shows late reaches the filter late, as it would live.
* `deaths` (0.1.0). `rgt.fit_alignment` of Riot kills on the same death
  claims the filter consumes; claims compare at `a_ms + gameTime` and the
  round table `rgt.MINIMAP_LAG_MS` earlier. The fit absorbs the killfeed's
  render and sampling lag, so every claim reaches the filter as its kill
  happens and the cost leaves that lag out.

`results.json` stores each session's two offsets and their difference. The
clock alignment carries its own uncertainty: `gametime` places the barrier
drop from the first live clock read, so it sits about half a displayed
second early if the HUD shows the floor second and late if it shows the
ceiling, and no domain fact says which. `clock_floor` and `clock_ceil` move
every instant `CLOCK_HALF_DIGIT_MS` later and earlier to bracket it.

Result (0.2.0, 21 matches)
--------------------------
Every captured instant is scored under every alignment
[metric:round_filter/riot_G/clock#share_of_captured=1.0]. The oracle scores
[metric:round_filter/riot_G/clock#oracle_nats=0.50219] nats.

The honest cost is the clock's, because its alignment never reads the claims
it scores: [metric:round_filter/riot_G/clock#cost_nats=0.01536] nats,
bracketed by the display convention between
[metric:round_filter/riot_G/clock_floor#cost_nats=0.0101] and
[metric:round_filter/riot_G/clock_ceil#cost_nats=0.02055]. The 0.1.0
alignment reproduces 0.1.0's [metric:round_filter/riot_G/deaths#cost_nats=0.00528]
exactly; it is a floor, since its fit sets the killfeed lag to zero. The death
fit sits a median [metric:round_filter/riot_G/clock#deaths_minus_clock_median_ms=974.5]
ms after the clock alignment over 21 sessions: the killfeed's render and
sampling lag plus the drop's display bias.

Under `clock`, the most probable state is wrong on
[metric:round_filter/riot_G/clock#map_wrong=3814] instants;
[metric:round_filter/riot_G/clock#map_wrong_1s_after_kill=2246] of them lie
within 1 s after a Riot kill (the claim not yet observed) and
[metric:round_filter/riot_G/clock#map_wrong_1s_before_kill=389] within 1 s
before one. The mixture beats plugging in the most probable state by
[metric:round_filter/riot_G/clock#mixture_gain_nats=0.002] nats, an interval
that includes zero. Resolved kill claims decrement the claimed side on
[metric:round_filter/riot_G/clock#claims_kill_resolved_first=0.993] of
resolved kill claims (a share of claims, not of matches). Of the Riot kills in
admitted rounds, [metric:round_filter/riot_G/clock#riot_kills_admitted_matched=3269]
of [metric:round_filter/riot_G/clock#riot_kills_admitted=3293] have a matched
claim.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import riot_ground_truth as rgt  # noqa: E402
import winprob_reference as wr  # noqa: E402

VERSION = "round-filter-0.2.0"
STORE = wr.STORE
#: The reference outcome model the filter feeds: alive, side, plant flag.
SPEC = ["alive", "side", "flag"]
#: How long after the barrier drop a start read may come.
START_READ_MS = 3000.0
N = 6  # alive counts 0..5
CLASSES = ("kill_resolved", "kill_unresolved", "side_unknown", "second_life", "entry_refused",
           "refused_entry", "merged_entry", "inferred_death", "revive")
CI = {c: i for i, c in enumerate(CLASSES)}
#: Classes whose claims a Riot kill can match one to one.
POOL = ("kill_resolved", "kill_unresolved", "side_unknown", "second_life", "entry_refused",
        "refused_entry", "merged_entry")
#: Classes that are not a resolved kill; an instant after one carries its uncertainty.
UNCERTAIN = ("kill_unresolved", "side_unknown", "entry_refused", "refused_entry", "inferred_death")
POOL_I = np.array([CI[c] for c in POOL])
UNCERTAIN_I = np.array([CI[c] for c in UNCERTAIN])
#: `clock` places instants by gametime's barrier drops; `clock_floor` and `clock_ceil` move them
#: half a displayed second later and earlier (see the docstring); `deaths` is 0.1.0's fit.
ALIGNMENTS = ("clock", "clock_floor", "clock_ceil", "deaths")
#: Half of one displayed clock second: the barrier drop's phase bias under either display convention.
CLOCK_HALF_DIGIT_MS = 500.0
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


def stored_claims(sid: str, why: Counter) -> tuple[dict, list[str]]:
    """The death stream's count-changing rows as arrays, in time order: `t`
    (the time each enters the filter), `cls` (index into CLASSES), `side`
    (0 ally, 1 enemy, -1 unknown), `round_no` (-1 unread) and an inferred
    death's window `lo`, `hi` (NaN otherwise)."""
    t, cls, side, rno, lo, hi = [], [], [], [], [], []
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
            if c == "inferred_death":
                w = r.get("t_window_ms") or [None, None]
                tt, w0, w1 = w[1], w[0], w[1]
            else:
                tt, w0, w1 = r.get("t_ms"), None, None
            if tt is None:
                why[f"claims_no_time:{c}"] += 1
                continue
            t.append(float(tt))
            cls.append(CI[c])
            side.append({"ally": 0, "enemy": 1}.get(r.get("side"), -1))
            rno.append(-1 if r.get("round_no") is None else int(r["round_no"]))
            lo.append(np.nan if w0 is None else float(w0))
            hi.append(np.nan if w1 is None else float(w1))
            why[f"claims:{c}"] += 1
    o = np.argsort(np.asarray(t, float), kind="stable")
    C = {"t": np.asarray(t, float)[o], "cls": np.asarray(cls, int)[o], "side": np.asarray(side, int)[o],
         "round_no": np.asarray(rno, int)[o], "lo": np.asarray(lo, float)[o], "hi": np.asarray(hi, float)[o]}
    return C, sorted(v for v in versions if v)


def riot_truth(d: dict, team: str, rounds_of_sid: list[dict]) -> dict:
    """Riot's kills (game time, victim side, in an admitted round) and
    revivals (round-relative game-time windows, side)."""
    team_of = {p["subject"]: p["teamId"] for p in d["match"]["players"]}
    kills = d["match"]["kills"]
    admitted = {rd["round"] for rd in rounds_of_sid}
    kg = np.array([float(k["gameTime"]) for k in kills])
    ks = np.array([0 if team_of.get(k["victim"]) == team else 1 for k in kills], int)
    kadm = np.array([k["round"] in admitted for k in kills], bool)
    g0, g1, gs = [], [], []
    for rd in rounds_of_sid:
        if rd["rstart_game"] is None:
            continue
        prev_alive, prev_t = set(rd["team_of"]), 0.0
        for kst in rd["kstates"]:
            for s in kst["alive"] - prev_alive:
                g0.append(rd["rstart_game"] + prev_t)
                g1.append(rd["rstart_game"] + kst["t"])
                gs.append(0 if team_of.get(s) == team else 1)
            prev_alive, prev_t = kst["alive"], kst["t"]
    return {"kg": kg, "ks": ks, "k_admitted": kadm,
            "rg0": np.asarray(g0, float), "rg1": np.asarray(g1, float), "rs": np.asarray(gs, int)}


def score_claims(C: dict, truth: dict, a_ms: float, tol: float) -> tuple[np.ndarray, dict]:
    """Per claim its Riot outcome: for a known side 0 same, 1 other, 2 none;
    for an unknown side 0 ally, 1 enemy, 2 none; for a revive 0 revival on
    its side, 2 none. Riot times sit at `a_ms + gameTime`. Also kill recall,
    over every Riot kill and over the kills of admitted rounds."""
    n = len(C["t"])
    out = np.full(n, 2, int)
    kt, ks = a_ms + truth["kg"], truth["ks"]
    used = np.zeros(len(kt), bool)
    done = np.zeros(n, bool)
    in_pool = np.isin(C["cls"], POOL_I)
    # same side first, so a nearby kill of the other side never takes a
    # claim's own kill; then whatever is left, across sides
    for side in (0, 1, None):
        cm = in_pool & ~done & ((C["side"] == side) if side is not None else True)
        km = ~used & ((ks == side) if side is not None else True)
        pool, kidx = np.flatnonzero(cm), np.flatnonzero(km)
        pairs = rgt.match_times(kt[kidx].tolist(), C["t"][pool].tolist(), 0.0, tol_ms=tol)
        if not pairs:
            continue
        pr = np.asarray([(i, j) for i, j, _dt in pairs], int)
        i, j = kidx[pr[:, 0]], pool[pr[:, 1]]
        used[i] = True
        done[j] = True
        vs, cs = ks[i], C["side"][j]
        out[j] = np.where(cs < 0, vs, np.where(vs == cs, 0, 1))
    # inferred deaths: one to one with an unused kill of their side in their window
    inf = np.flatnonzero(C["cls"] == CI["inferred_death"])
    if inf.size and kt.size:
        M = (~used[None, :] & (ks[None, :] == C["side"][inf, None])
             & (kt[None, :] >= C["lo"][inf, None] - tol) & (kt[None, :] <= C["hi"][inf, None] + tol))
        if M.any():
            r, c = linear_sum_assignment(np.where(M, np.abs(kt[None, :] - C["hi"][inf, None]), 1e12))
            ok = M[r, c]
            out[inf[r[ok]]] = 0
            used[c[ok]] = True
    # revives: a Riot revival on their side spans the claim
    rv = np.flatnonzero(C["cls"] == CI["revive"])
    if rv.size and truth["rs"].size:
        tr = C["t"][rv, None]
        hit = ((truth["rs"][None, :] == C["side"][rv, None])
               & (a_ms + truth["rg0"][None, :] - tol <= tr) & (tr <= a_ms + truth["rg1"][None, :] + tol))
        out[rv[hit.any(axis=1)]] = 0
    adm = truth["k_admitted"]
    return out, {"riot_kills": int(len(kt)), "riot_kills_matched": int(used.sum()),
                 "riot_kills_admitted": int(adm.sum()), "riot_kills_admitted_matched": int((used & adm).sum())}


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


def apply_claim(P: np.ndarray, cls: int, side: int, probs: np.ndarray | None) -> np.ndarray:
    """One claim's transition, with its class's measured outcome probabilities."""
    if probs is None:
        return P
    p0, p1, p2 = probs
    if cls == CI["revive"]:
        if side < 0:
            return P
        return p0 * _shift(P, side, +1) + (1.0 - p0) * P
    if side < 0:  # absolute: ally, enemy, none
        return p0 * _shift(P, 0, -1) + p1 * _shift(P, 1, -1) + p2 * P
    return p0 * _shift(P, side, -1) + p1 * _shift(P, 1 - side, -1) + p2 * P


def loo_rates(counts: np.ndarray, k: int) -> list:
    """Per class, outcome probabilities from every captured match but match
    `k` (`counts` is matches x classes x 3); None where the other matches
    hold no claim of the class."""
    tot = counts.sum(axis=0) - counts[k]
    s = tot.sum(axis=1)
    return [(tot[c] / s[c]) if s[c] > 0 else None for c in range(len(CLASSES))]


# ----------------------------------------------------------------- scoring

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


def nearest_signed(x: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Signed distance from each `x` to its nearest `ref` (x - ref); inf when `ref` is empty."""
    if not len(ref):
        return np.full(len(x), np.inf)
    k = np.searchsorted(ref, x)
    lo, hi = ref[np.clip(k - 1, 0, len(ref) - 1)], ref[np.clip(k, 0, len(ref) - 1)]
    return np.where(np.abs(x - lo) <= np.abs(x - hi), x - lo, x - hi)


# ----------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(STORE / "analysis" / "round-filter-0.2.0-20261004"))
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
    sids = sorted(frames)
    SI = {s: k for k, s in enumerate(sids)}
    store = Store(STORE)

    # per admitted round and per G state, as arrays (G.S is the reference's dict API)
    rstart = np.array([np.nan if rd["rstart_game"] is None else rd["rstart_game"] for rd in adm], float)
    att_r = np.array([rd["att_team"] for rd in adm])
    rsid = np.array([rd["sid"] for rd in adm])
    gt_s = np.array([s["t"] for s in G.S], float)
    gp = np.array([s["planted"] for s in G.S], float)
    g_a = np.array([s["a"] for s in G.S], int)
    g_d = np.array([s["d"] for s in G.S], int)
    tg = rstart[G.ri] + gt_s * 1000.0  # Riot game time of each instant (NaN: no round start)
    tbin = np.round(gt_s).astype(int)
    nb = int(tbin.max()) + 1
    cap = np.isin(G.match, sids)
    gi = np.flatnonzero(cap)
    team_s = np.array([frames[s]["team"] for s in sids])

    # ---- claims, scored against Riot per match (identity pairing under the death fit)
    claims, recall, stamps, kill_g = {}, {}, {}, {}
    counts = np.zeros((len(sids), len(CLASSES), 3))
    for sid in sids:
        fr = frames[sid]
        C, dver = stored_claims(sid, why)
        truth = riot_truth(records[sid], fr["team"], [rd for rd in adm if rd["sid"] == sid])
        out, rc = score_claims(C, truth, fr["a_ms"], rgt.MATCH_TOL_MS)
        C["riot"] = out
        np.add.at(counts[SI[sid]], (C["cls"], out), 1)
        claims[sid], recall[sid] = C, rc
        kill_g[sid] = np.sort(truth["kg"])
        stamps[sid] = {"death": dver}
    pooled = {c: counts[:, CI[c]].sum(axis=0).astype(int).tolist() for c in CLASSES}

    # Riot start counts (ally, enemy) per admitted round, for the start map
    s0a = np.array([wr.state_at(rd, 0.0)["a"] for rd in adm], int)
    s0d = np.array([wr.state_at(rd, 0.0)["d"] for rd in adm], int)
    r_ally_att = np.isin(rsid, sids) & (team_s[np.searchsorted(sids, rsid).clip(0, len(sids) - 1)] == att_r)
    st_ally, st_enemy = np.where(r_ally_att, s0a, s0d), np.where(r_ally_att, s0d, s0a)

    def plant_rate(sid):
        k = G.match != sid
        n = np.bincount(tbin[k], minlength=nb)
        p = np.bincount(tbin[k], gp[k], minlength=nb)
        marg = p.sum() / n.sum()
        return np.where(n > 0, p / np.maximum(n, 1), marg)

    # ---- per session: stored rounds, roster start reads, gametime, and the clock alignment
    sessions, align = {}, {}
    for sid in sids:
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
        starts = np.array([r["t_start_ms"] for r in rt_tab], float)
        ends = np.array([r["t_close_ms"] if r["t_close_ms"] is not None else r["t_end_ms"] for r in rt_tab], float)
        # the start read per stored round: the first two-sided roster read after the barrier drop
        tl = np.array([np.nan if live.get(r["round_no"]) is None else live[r["round_no"]] for r in rt_tab], float)
        k0 = np.where(np.isnan(tl), len(rtm), np.searchsorted(rtm, np.nan_to_num(tl)))
        k1 = np.where(np.isnan(tl), k0, np.searchsorted(rtm, np.nan_to_num(tl) + START_READ_MS, "right"))
        two = np.flatnonzero(~np.isnan(A) & ~np.isnan(E))
        f = np.searchsorted(two, k0)
        ok = (f < len(two)) & (two[np.clip(f, 0, max(len(two) - 1, 0))] < k1) if len(two) else np.zeros(len(tl), bool)
        jr = two[np.clip(f, 0, max(len(two) - 1, 0))] if len(two) else np.zeros(len(tl), int)
        sr_a = np.where(ok, A[jr] if len(A) else np.nan, np.nan)
        sr_e = np.where(ok, E[jr] if len(E) else np.nan, np.nan)
        sessions[sid] = {"rt_tab": rt_tab, "starts": starts, "ends": ends, "sr_a": sr_a, "sr_e": sr_e,
                         "round_no": np.array([r["round_no"] for r in rt_tab], int)}
        # clock alignment: Riot round starts against gametime's barrier drops
        rs_sid = rstart[(rsid == sid) & ~np.isnan(rstart)]
        al = rgt.fit_alignment(rs_sid.tolist(), [s.t_live_ms for s in gt.schedules])
        align[sid] = {"a_deaths_ms": round(fr["a_ms"], 1),
                      "a_clock_ms": None if al is None else round(al["a_ms"], 1),
                      "deaths_minus_clock_ms": None if al is None else round(fr["a_ms"] - al["a_ms"], 1),
                      "clock_rounds_matched": None if al is None else al["matched"],
                      "riot_rounds": int(rs_sid.size),
                      "clock_residual_mad_ms": None if al is None else round(al["residual_mad_ms"], 1)}
    offsets = {"deaths": {s: frames[s]["a_ms"] for s in sessions},
               "clock": {s: align[s]["a_clock_ms"] for s in sessions if align[s]["a_clock_ms"] is not None}}
    offsets["clock_floor"] = {s: a + CLOCK_HALF_DIGIT_MS for s, a in offsets["clock"].items()}
    offsets["clock_ceil"] = {s: a - CLOCK_HALF_DIGIT_MS for s, a in offsets["clock"].items()}
    lag = np.array([v["deaths_minus_clock_ms"] for v in align.values() if v["deaths_minus_clock_ms"] is not None])
    rates = [loo_rates(counts, k) for k in range(len(sids))]
    prates = {s: plant_rate(s) for s in sessions}

    R = {"version": VERSION, "reference_version": wr.VERSION, "spec": SPEC,
         "riot_digest": wr.digest((STORE / "external" / "riot").glob("*.json")),
         "constants": {"MATCH_TOL_MS": rgt.MATCH_TOL_MS, "MINIMAP_LAG_MS": rgt.MINIMAP_LAG_MS,
                       "START_READ_MS": START_READ_MS, "RIDGE": wr.RIDGE,
                       "CLOCK_HALF_DIGIT_MS": CLOCK_HALF_DIGIT_MS},
         "captured_matches": len(frames), "stamps": stamps,
         "claims": {"rows": {k: v for k, v in why.items() if k.startswith("claims")},
                    "riot_outcomes_pooled": pooled,
                    "outcome_columns": "known side: [same, other, none]; side_unknown: [ally, enemy, none]; "
                                       "revive: [revival on its side, -, none]",
                    **{k: sum(r[k] for r in recall.values()) for k in
                       ("riot_kills", "riot_kills_matched", "riot_kills_admitted", "riot_kills_admitted_matched")}},
         "alignment": {"per_session": align,
                       "deaths_minus_clock_ms": {"sessions": int(lag.size),
                                                 "median": round(float(np.median(lag)), 1) if lag.size else None,
                                                 "quartiles": ([round(float(q), 1) for q in np.quantile(lag, [0.25, 0.75])]
                                                               if lag.size else None)}},
         "by_alignment": {}}
    coefs = {}
    for name in ALIGNMENTS:
        blk, coefs[name] = run_alignment(name, offsets[name], G, adm, maps, gi, tg, gt_s, g_a, g_d, gp, tbin,
                                         sids, SI, team_s, att_r, st_ally, st_enemy, sessions, claims, rates,
                                         prates, kill_g, cap, args.boot)
        R["by_alignment"][name] = blk
    R["model_coef_full"] = coefs["clock"]
    R["elapsed_s"] = round(time.time() - t0, 1)
    (out_dir / "results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"claims": R["claims"], "alignment": R["alignment"]["deaths_minus_clock_ms"]}, indent=1))
    for name, blk in R["by_alignment"].items():
        print("==", name, json.dumps({k: blk[k] for k in ("coverage", "refusals", "state", "observation_cost",
                                                          "mixture_vs_map")}, default=str))
        for k in ("filter", "oracle", "map_plugin"):
            print("  ", k, {x: blk[k][x] for x in ("logloss_nats", "logloss_nats_ci95", "logloss_bits", "brier",
                                                   "n_states")})
    print("wrote", out_dir / "results.json", R["elapsed_s"], "s")
    if args.record:
        record_results(R)


def run_alignment(name, off, G, adm, maps, gi, tg, gt_s, g_a, g_d, gp, tbin, sids, SI, team_s, att_r,
                  st_ally, st_enemy, sessions, claims, rates, prates, kill_g, cap, boot):
    """Place every captured instant under one alignment, run the filter, and score it."""
    hud_shift = rgt.MINIMAP_LAG_MS if name == "deaths" else 0.0
    cover = Counter()
    parts = []  # per session: (session index, G index, claim time, round-table time, stored round)
    start_pairs = {}
    for sid in sessions:
        idx = gi[G.match[gi] == sid]
        if sid not in off:
            cover["cover_no_alignment"] += len(idx)
            continue
        S = sessions[sid]
        ts_feed = off[sid] + tg[idx]
        ts_hud = ts_feed + hud_shift
        k = np.searchsorted(S["starts"], ts_hud, "right") - 1
        inside = (k >= 0) & (ts_hud <= S["ends"][np.clip(k, 0, None)]) & ~np.isnan(ts_feed)
        cover["cover_no_round_start"] += int(np.isnan(ts_feed).sum())
        cover["cover_no_stored_round"] += int((~inside & ~np.isnan(ts_feed)).sum())
        ii, kk = idx[inside], k[inside]
        parts.append((np.full(ii.size, SI[sid]), ii, ts_feed[inside], ts_hud[inside], kk))
        # start pairs: the stored round of each Riot round's first instant
        u, first = np.unique(G.ri[ii], return_index=True)
        start_pairs[sid] = np.column_stack([S["sr_a"][kk[first]], S["sr_e"][kk[first]],
                                            st_ally[u], st_enemy[u]])
    r_s, r_i, r_tf, r_th, r_k = (np.concatenate(c) for c in zip(*parts))
    n_rows = r_i.size

    def start_dist(sid, read):
        """Per side P(true start | read) from the other matches; the marginal
        where the read is missing or unseen."""
        P = np.vstack([v for s, v in start_pairs.items() if s != sid])
        out = []
        for side in (0, 1):
            true = P[:, 2 + side].astype(int)
            marg = np.bincount(true, minlength=N)[:N].astype(float)
            r = read[side]
            cond = (np.bincount(true[P[:, side] == r], minlength=N)[:N].astype(float)
                    if not np.isnan(r) else np.zeros(N))
            v = cond if cond.sum() > 0 else marg
            out.append(v / v.sum())
        return np.outer(out[0], out[1])

    # ---- the filter: per (session, stored round), distributions after each claim
    dist = np.zeros((n_rows, N, N))
    p_plant = np.zeros(n_rows)
    unc = np.zeros(n_rows, bool)
    unrated = np.zeros(n_rows, int)
    plant_unread = np.zeros(n_rows, bool)
    start_basis = Counter()
    key = r_s * 10000 + r_k
    order_k = np.argsort(key, kind="stable")
    _, b0 = np.unique(key[order_k], return_index=True)
    for js in np.split(order_k, b0[1:]):
        si, kk = int(r_s[js[0]]), int(r_k[js[0]])
        sid = sids[si]
        S = sessions[sid]
        sr = S["rt_tab"][kk]
        read = (S["sr_a"][kk], S["sr_e"][kk])
        start_basis["riot_marginal" if np.isnan(read[0]) else "roster_read"] += 1
        P = start_dist(sid, read)
        C = claims[sid]
        cm = np.flatnonzero(C["round_no"] == sr["round_no"])
        rt = rates[si]
        seq = [P]
        for c in cm:  # the recursion is sequential; each step is a 6 x 6 array op
            P = apply_claim(P, int(C["cls"][c]), int(C["side"][c]), rt[C["cls"][c]])
            seq.append(P)
        u_seq = np.concatenate([[False], np.logical_or.accumulate(np.isin(C["cls"][cm], UNCERTAIN_I))])
        r_seq = np.concatenate([[0], np.cumsum([rt[c] is None for c in C["cls"][cm]], dtype=int)])
        m = np.searchsorted(C["t"][cm], r_tf[js], "right")
        dist[js] = np.stack(seq)[m]
        unc[js] = u_seq[m]
        unrated[js] = r_seq[m]
        # plant: the stored table, or the Riot rate where it is unread
        sp, pt = sr["spike_planted"], sr["plant_t_ms"]
        if sp is None or (sp and pt is None):
            plant_unread[js] = True
            p_plant[js] = prates[sid][tbin[r_i[js]]]
        else:
            p_plant[js] = (bool(sp) & (pt is not None) & (r_th[js] >= (pt if pt is not None else np.inf))).astype(float)

    # ---- expand each instant into its states and apply the outcome model
    ally_att = team_s[r_s] == att_r[G.ri[r_i]]
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
    zeros = [0.0] * len(jj)
    S_exp = [dict(zip(keys, v)) for v in zip(gt_s[r_i[jj]].tolist(), xa.tolist(), xd.tolist(), zeros, zeros,
                                            planted.tolist(), [None] * len(jj), G.ri[r_i[jj]].tolist())]
    p_exp, coef = wr.lomo(G, SPEC, maps, eval_D=wr.Data(S_exp, adm))
    p_obs = np.bincount(jj, wt * p_exp, n_rows) / np.bincount(jj, wt, n_rows)
    # MAP plug-in: the single most probable state
    best = np.argmax(W, axis=1)
    bcell = best % (N * N)
    zeros = [0.0] * n_rows
    S_map = [dict(zip(keys, v)) for v in zip(gt_s[r_i].tolist(),
                                            np.where(ally_att, ia[bcell], ie[bcell]).tolist(),
                                            np.where(ally_att, ie[bcell], ia[bcell]).tolist(), zeros, zeros,
                                            (best >= N * N).tolist(), [None] * n_rows, G.ri[r_i].tolist())]
    p_map, _ = wr.lomo(G, SPEC, maps, eval_D=wr.Data(S_map, adm))

    # ---- oracle and scores on the same instants
    covered = np.zeros(len(G.S), bool)
    covered[r_i] = True
    order = np.argsort(r_i)  # G.subset keeps G's order
    Gc = G.subset(covered)
    p_obs_c, p_map_c = p_obs[order], p_map[order]
    p_true, _ = wr.lomo(G, SPEC, maps, eval_D=Gc)
    # state agreement with Riot (ally, enemy)
    gc = r_i[order]
    aa = ally_att[order]
    t_ally, t_enemy = np.where(aa, g_a[gc], g_d[gc]), np.where(aa, g_d[gc], g_a[gc])
    dist_c = dist[order]
    p_true_state = dist_c[np.arange(len(order)), t_ally, t_enemy]
    map_cell = np.argmax(dist_c.reshape(len(order), -1), axis=1)
    rp = gp[gc].astype(bool)
    # signed distance from each instant to its nearest Riot kill, in this alignment's capture time
    tf_c, s_c = r_tf[order], r_s[order]
    near = np.full(len(order), np.inf)
    for sid in sessions:
        if sid in off:
            m = s_c == SI[sid]
            near[m] = nearest_signed(tf_c[m], off[sid] + kill_g[sid])
    wrong = map_cell != t_ally * N + t_enemy
    an = np.abs(near)
    blk = {"alignment": name,
           "coverage": {"captured_states": int(cap.sum()), "covered_states": int(n_rows),
                        "share_of_captured": round(n_rows / max(int(cap.sum()), 1), 4), "detail": dict(cover)},
           "start_basis": dict(start_basis),
           "start_pairs": {s: {("None" if r[0] < 0 else str(int(r[0]))) + "/"
                               + ("None" if r[1] < 0 else str(int(r[1])))
                               + f"->{int(r[2])}/{int(r[3])}": int(n)
                               for r, n in zip(*np.unique(np.nan_to_num(v, nan=-1), axis=0, return_counts=True))}
                           for s, v in start_pairs.items()},
           "refusals": {"instants_after_uncertain_claim": int(unc.sum()),
                        "instants_with_unrated_claim": int((unrated > 0).sum()),
                        "instants_plant_unread": int(plant_unread.sum()),
                        "instants_any": int((unc | (unrated > 0) | plant_unread).sum())},
           "state": {"mean_p_on_riot_state": round(float(p_true_state.mean()), 4),
                     "map_alive_right": int(np.sum(~wrong)),
                     "map_alive_wrong": int(wrong.sum()),
                     "map_wrong_within_1s_of_riot_kill": int(np.sum(wrong & (an <= 1000.0))),
                     "map_wrong_within_1s_after_kill": int(np.sum(wrong & (near >= 0) & (near <= 1000.0))),
                     "map_wrong_within_1s_before_kill": int(np.sum(wrong & (near < 0) & (near >= -1000.0))),
                     "map_wrong_within_3s_of_riot_kill": int(np.sum(wrong & (an <= 3000.0))),
                     "plant_right": int(np.sum((p_plant[order] > 0.5) == rp)),
                     "plant_late": int(np.sum((p_plant[order] <= 0.5) & rp)),
                     "plant_early": int(np.sum((p_plant[order] > 0.5) & ~rp))}}
    blk["filter"] = scored(Gc, p_obs_c, boot)
    blk["oracle"] = scored(Gc, p_true, boot)
    blk["map_plugin"] = scored(Gc, p_map_c, boot)
    blk["observation_cost"] = wr.compare(Gc, p_obs_c, p_true, boot)
    blk["mixture_vs_map"] = wr.compare(Gc, p_map_c, p_obs_c, boot)
    # the instants a refusal touches, scored apart (never dropped from the totals)
    flag_any = (unc | (unrated > 0) | plant_unread)[order]
    if flag_any.sum() >= 20:
        Gf = Gc.subset(flag_any)
        blk["refusal_instants"] = {"states": int(flag_any.sum()),
                                   "filter": wr.scores(Gf, p_obs_c[flag_any], w=Gc.w[flag_any])["logloss_nats"],
                                   "oracle": wr.scores(Gf, p_true[flag_any], w=Gc.w[flag_any])["logloss_nats"]}
    return blk, coef


def record_results(R: dict):
    from reticle import metrics
    deps = {"tool_version": R["version"], "reference_version": R["reference_version"],
            "riot_digest": R["riot_digest"], "spec": "+".join(R["spec"]), **R["constants"],
            "stamps": sorted({json.dumps(v, sort_keys=True) for v in R["stamps"].values()})}
    ctx = {"captured_matches": R["captured_matches"]}
    for name, B in R["by_alignment"].items():
        vals = {"covered_states": B["coverage"]["covered_states"],
                "captured_states": B["coverage"]["captured_states"],
                "share_of_captured": B["coverage"]["share_of_captured"],
                "cost_nats": B["observation_cost"]["improvement_nats"],
                "cost_bits": B["observation_cost"]["improvement_bits"],
                "mixture_gain_nats": B["mixture_vs_map"]["improvement_nats"],
                "refusal_instants": B["refusals"]["instants_any"],
                "mean_p_on_riot_state": B["state"]["mean_p_on_riot_state"],
                "map_wrong": B["state"]["map_alive_wrong"],
                "map_wrong_1s_after_kill": B["state"]["map_wrong_within_1s_after_kill"],
                "map_wrong_1s_before_kill": B["state"]["map_wrong_within_1s_before_kill"]}
        for k in ("riot_kills", "riot_kills_matched", "riot_kills_admitted", "riot_kills_admitted_matched"):
            vals[k] = R["claims"][k]
        if R["alignment"]["deaths_minus_clock_ms"]["median"] is not None:
            vals["deaths_minus_clock_median_ms"] = R["alignment"]["deaths_minus_clock_ms"]["median"]
        ci = {"cost_nats": B["observation_cost"]["ci95_nats"],
              "mixture_gain_nats": B["mixture_vs_map"]["ci95_nats"]}
        for k in ("filter", "oracle", "map_plugin"):
            vals[f"{k}_nats"] = B[k]["logloss_nats"]
            vals[f"{k}_bits"] = B[k]["logloss_bits"]
            vals[f"{k}_brier"] = B[k]["brier"]
            ci[f"{k}_nats"] = B[k]["logloss_nats_ci95"]
            ci[f"{k}_brier"] = B[k]["brier_ci95"]
        for c, v in R["claims"]["riot_outcomes_pooled"].items():
            vals[f"claims_{c}_n"] = int(sum(v))
            if sum(v):
                vals[f"claims_{c}_first"] = round(v[0] / sum(v), 4)
        metrics.record("round_filter", part=f"riot_G/{name}", values=vals, deps={**deps, "alignment": name},
                       context=ctx, ci=ci)
        print(f"recorded round_filter/riot_G/{name}")


if __name__ == "__main__":
    main()
