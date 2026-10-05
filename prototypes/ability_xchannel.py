r"""Which stored channels witness which players' ability casts, are their
errors independent, and what does a combined witness reach?

    .\.venv\Scripts\python.exe prototypes\ability_xchannel.py inventory
    .\.venv\Scripts\python.exe prototypes\ability_xchannel.py report [--record] [--json OUT]
                                                              [--los 2d|3d|none]

Why
---
The entity-state design opens an ability child of its caster on cast
evidence (`docs/ENTITY_STATE.md`, section 9). The coverage survey
(`ability_coverage`, ledger `ability_coverage/*`) witnesses the player's own
casts well and other players' poorly; `audio_others` (ledger
`audio_others/*`) hears other players' casts within about 30 m at replay
precision near 0.35. The player's bar is the EFFECT of an ability (what it
hit, assisted, missed), not the fine place of every mark. This file asks,
from stored rows only, how the channels together witness other players'
casts and their effects.

The channels (reuse, not restatement)
-------------------------------------
* every channel of `ability_coverage.session_witnesses` (tray, audio,
  ult_cast, minimap_shape, minimap_fit, smoke, killfeed, assist_icon), with
  that file's units and slot rules;
* `audio_others`: the stored peaks (`audio_others.load_peaks`) at each
  (agent, class)'s dev threshold (`audio_others.thresholds`), merged as
  `audio_others.detections` merges them. The caster's SIDE comes from the
  lineup owner (`audio_others.lineup_sides`): an agent the lineup places on
  one side takes that side; an agent on both sides (a mirror) takes `both`
  and names two candidate players, which only the identity arbiter may
  split. A phase group class (Sova's `Q+E`) names each of its slots.

Riot's records and the replay are evaluation truth only: they score, they
never set a threshold, a side or a candidate. The replay match
(9acf02f98283, `audio_others.replay_casts`) gives every player's timed casts
and positions; Riot's per-player match totals score the count level.

Scoring on the replay match
---------------------------
A witness names candidate CELLS (subject, slot): one for a resolved side,
two for a mirror, none where no Riot player of that side plays the agent
(`unresolved`). Cast channels pair one to one with a cast in a candidate
cell, nearest first, inside the channel's window (`WINDOW_S`). Effect
channels (`killfeed`, `assist_icon`) pair one to one with the latest such
cast at most `EFFECT_LOOKBACK_S` before the witness (and `EFFECT_AFTER_S`
after, for a stamp that leads). Per (agent, slot, side): casts, live casts,
each channel's hits, recall, and per (agent, slot) each channel's witnesses,
paired witnesses (precision) and the median offset.

Independence
------------
Only channels that can witness another player and hold stored rows on the
session take part (`present_channels`): a stream the store lacks is no
witness, never a miss. Per channel pair (A, B), over the casts both could
witness (`opportunity`: other players' casts in classes the channel names,
`vocab`, the (agent, slot) pairs it witnessed anywhere in the corpus;
audio_others: the classes with a threshold; the killfeed only the casts
that killed, a Riot ability kill paired to the latest prior cast of that
killer and slot): the 2x2 table of misses, P(miss A), P(miss A | miss B),
the odds ratio and Fisher's exact test (`scipy.stats.fisher_exact`), pooled
and per stratum (`cast_strata`: distance bin `DIST_STRATA_M`, 2D line of
sight from the sightline tables, the listener's live state, the caster's
side), and the Mantel-Haenszel odds ratio over the distance strata.
`miss_by_cause` tests each channel's hits against each stratum: two
channels whose misses follow one stratum share a cause.

`cell_independence` was added AFTER the pre-registration, because the
replay match holds only one testable pair: the same test over every
session's (player, slot) cells of other players, a channel missing a cell
where it resolves none of its Riot casts. Its shared causes are side, agent
and match, not time; X2 is judged on the replay only.

Combination (pre-registered, predictions `ability-xchannel-20261005`)
--------------------------------------------------------------------
Rules per (agent, slot) of other players: each single channel; `today`
(every channel but audio_others: today's coverage); `union` (the per-round
largest channel count, as `ability_coverage.tally` forms `any`);
`hi_union` (the union of the channels whose DEV count precision reaches
`PREC_BAR` for that class); `agree` (every non-audio witness, plus an
audio_others detection only where another channel witnesses the same cell
within `AGREE_S`, or an effect within `EFFECT_LOOKBACK_S` after it in the
same round). The dev half (`audio_others.dev_half`) picks per class the rule with the most casts
covered among rules whose dev precision reaches `PREC_BAR`, else the most
precise rule; the held half scores it. Count precision is covered /
witnessed (covered = min(witnessed, Riot) per cell), an UPPER bound; the
audio share is corrected by `audio_others`' held absent-agent false-alarm
rate (expected false = rate x live minutes; for `agree`, times the chance a
random time falls within another witness's window), and the precision
reported is the smaller of the two.

X1: held precision >= PREC_BAR for at least X1_MIN_CLASSES classes with at
least X1_MIN_RIOT held Riot casts, each with held recall above its best
single channel. X2: at least one channel pair with Fisher p < 0.05 and
P(miss A | miss B) > P(miss A).

Effects
-------
Riot's ability kills by other players (`ability_coverage.riot_ability_kills`'
slot rule), placed in capture time by `riot_ground_truth.fit_alignment`
over the stored deaths: the share a stored ability kill of that player and
slot witnesses within `KILL_TOL_S` (one witness per death,
`stored_ability_kills`), the share with a cast witness (any non-effect
channel; and without audio_others) of that cell up to 60 s and 10 s before,
the share either explains, and the CHANCE FLOOR: the kills a random
placement of the cell's audio detections would explain
(1 - exp(-n x lookback / live seconds) per kill). The assist panel's ability
icons of other players: the share with a cast witness before them, with the
same floor.

Outputs: `<store>/analysis/ability-xchannel-20261005/report.json` and ledger
rows `ability_xchannel/*`. Decodes nothing; writes no stream. Nothing in
`reticle/` reads this file.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ABILITY_XCHANNEL_VERSION = "ability-xchannel-proto-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "ability-xchannel-20261005"
REPLAY_SESSION = "9acf02f98283"
REPLAY_MATCH = "b03fecd3-8d80-4e6c-bae0-ac2ec0344567"
RIOT_SLOTS = ("Grenade", "Ability1", "Ability2", "Ultimate")
#: (pre, post) seconds a cast channel's witness may lie from the cast:
#: audio_others' own pairing window; the coverage survey's 2 s (3 s ult).
WINDOW_S = {"audio_others": (1.0, 3.0), "ult_cast": (3.0, 3.0)}
DEFAULT_WINDOW_S = (2.0, 2.0)
EFFECT_CHANNELS = ("killfeed", "assist_icon")
EFFECT_LOOKBACK_S = 60.0
EFFECT_AFTER_S = 1.0
#: An audio detection agrees with another cast witness this close.
AGREE_S = 3.0
#: A Riot kill pairs with a killfeed witness this close (capture time).
KILL_TOL_S = 3.0
DIST_STRATA_M = (0.0, 20.0, 40.0)
PREC_BAR = 0.8
X1_MIN_CLASSES, X1_MIN_RIOT = 10, 5
FISHER_P = 0.05
OTHER_SIDES = ("ally", "enemy")


def _below_normal() -> None:
    """Windows BELOW_NORMAL_PRIORITY_CLASS for this process; elsewhere nice 10."""
    try:
        if os.name == "nt":
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
        else:
            os.nice(10)
    except Exception:
        pass


def canon(name) -> str | None:
    if name is None:
        return None
    return " ".join(str(name).replace("/", "_").replace("-", " ").casefold().split())


# ----------------------------------------------------------------- pure rules

def candidate_cells(w: dict, players: list[dict]) -> list[tuple[str, str]]:
    """The (subject, slot) cells a witness may name: per slot it names, each
    player of its side and agent ('both' takes either side; an ally of the
    player's agent is the player). Empty when no player or slot fits."""
    slots = [s for s in (w.get("slots") or [w.get("slot")]) if s in RIOT_SLOTS]
    side = w.get("side")
    if side == "self":
        sides = ("self",)
    elif side == "ally":
        sides = ("self", "ally")
    elif side == "enemy":
        sides = ("enemy",)
    elif side == "both":
        sides = ("self", "ally", "enemy")
    else:
        return []
    subs = [p["subject"] for p in players
            if p["side"] in sides and canon(p["agent"]) == canon(w.get("agent"))]
    return [(s, sl) for s in subs for sl in slots]


def pair_witnesses(wit: list[tuple[float, set]], casts: list[tuple[float, tuple]],
                   pre: float, post: float) -> list[tuple[int, int, float]]:
    """One-to-one (witness index, cast index, witness - cast) pairs: a
    witness at time t with candidate cells C pairs with a cast (t', cell)
    when cell is in C and -pre <= t - t' <= post; nearest first."""
    cand = []
    for i, (t, cells) in enumerate(wit):
        for j, (tc, cell) in enumerate(casts):
            dt = t - tc
            if cell in cells and -pre <= dt <= post:
                cand.append((abs(dt), i, j, dt))
    cand.sort()
    ui, uj, out = set(), set(), []
    for _a, i, j, dt in cand:
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        out.append((i, j, dt))
    return out


def miss_table(miss_a, miss_b) -> dict:
    """2x2 table of two channels' misses over the same casts, with P(miss A),
    P(miss A | miss B), P(miss A | hit B), the odds ratio and Fisher's
    two-sided exact p (None where a margin is empty)."""
    from scipy.stats import fisher_exact
    a = np.asarray(miss_a, bool)
    b = np.asarray(miss_b, bool)
    t = np.array([[int((a & b).sum()), int((a & ~b).sum())],
                  [int((~a & b).sum()), int((~a & ~b).sum())]])
    n = int(t.sum())
    out = {"n": n, "table": t.tolist(),
           "p_miss_a": round(float(a.mean()), 4) if n else None,
           "p_miss_b": round(float(b.mean()), 4) if n else None,
           "p_miss_a_given_miss_b": round(t[0, 0] / b.sum(), 4) if b.sum() else None,
           "p_miss_a_given_hit_b": round(t[0, 1] / (~b).sum(), 4) if (~b).sum() else None,
           "odds_ratio": None, "fisher_p": None}
    if n and t.sum(0).all() and t.sum(1).all():
        orr, p = fisher_exact(t, alternative="two-sided")
        out["odds_ratio"] = None if not np.isfinite(orr) else round(float(orr), 4)
        out["odds_ratio_inf"] = bool(np.isinf(orr))
        out["fisher_p"] = round(float(p), 5)
    return out


def mh_odds_ratio(tables) -> float | None:
    """The Mantel-Haenszel common odds ratio over 2x2 tables [[a, b], [c, d]]:
    sum(a d / n) / sum(b c / n); None when the denominator is zero."""
    num = den = 0.0
    for t in tables:
        (a, b), (c, d) = t
        n = a + b + c + d
        if n:
            num += a * d / n
            den += b * c / n
    return round(num / den, 4) if den else None


def correlated(m: dict) -> bool:
    """X2's test on one table: Fisher p < FISHER_P and a miss of B raises A's."""
    return (m.get("fisher_p") is not None and m["fisher_p"] < FISHER_P
            and m["p_miss_a_given_miss_b"] is not None and m["p_miss_a"] is not None
            and m["p_miss_a_given_miss_b"] > m["p_miss_a"])


def count_score(cells: list[tuple[int, int]]) -> dict:
    """Over (witnessed, riot) cells: covered (sum of min), witnessed, Riot,
    recall and the count precision (covered / witnessed, an upper bound)."""
    w = sum(c[0] for c in cells)
    r = sum(c[1] for c in cells)
    cov = sum(min(c) for c in cells)
    return {"witnessed": w, "riot": r, "covered": cov,
            "recall": round(cov / r, 4) if r else None,
            "precision_bound": round(cov / w, 4) if w else None}


def precision_estimate(score: dict, expected_false: float) -> float | None:
    """The smaller of the count bound and 1 - expected_false / witnessed."""
    if not score["witnessed"]:
        return None
    nul = 1.0 - expected_false / score["witnessed"]
    return round(min(score["precision_bound"], nul), 4)


def choose_rule(dev: dict[str, dict], bar: float = PREC_BAR) -> str | None:
    """The dev rule: among rules whose precision estimate reaches `bar`, the
    one covering most casts (ties: higher precision, then name); else the
    most precise rule (ties: more covered). None without any witnessed rule."""
    ok = [(r, s) for r, s in dev.items() if s.get("precision") is not None]
    if not ok:
        return None
    good = [(r, s) for r, s in ok if s["precision"] >= bar]
    if good:
        return sorted(good, key=lambda x: (-x[1]["covered"], -x[1]["precision"], x[0]))[0][0]
    return sorted(ok, key=lambda x: (-x[1]["precision"], -x[1]["covered"], x[0]))[0][0]


def per_round_max(witness_rounds: list[tuple[object, str]]) -> int:
    """The union count: per round the largest count of one channel, summed."""
    per = defaultdict(Counter)
    for rnd, ch in witness_rounds:
        per[rnd][ch] += 1
    return sum(max(c.values()) for c in per.values() if c)


def agree_keep(audio_t, other, audio_rounds=None, agree_s: float = AGREE_S,
               lookback_s: float = EFFECT_LOOKBACK_S) -> list[bool]:
    """Per audio detection time (s): kept when another channel's witness of
    the same cell (`other`: (t, channel) or (t, channel, round)) lies within
    `agree_s` (cast channels), or an effect witness lies 0..`lookback_s`
    after it, in the same round where both rounds are known."""
    a = np.asarray(audio_t, float)
    if not len(a) or not len(other):
        return [False] * len(a)
    to = np.array([o[0] for o in other], float)
    eff = np.array([o[1] in EFFECT_CHANNELS for o in other])
    ro = np.array([o[2] if len(o) > 2 else None for o in other], object)
    ra = np.array(audio_rounds if audio_rounds is not None else [None] * len(a), object)
    dt = to[None, :] - a[:, None]
    near = np.where(eff[None, :], (dt >= 0.0) & (dt <= lookback_s), np.abs(dt) <= agree_s)
    known = (ra[:, None] != None) & (ro[None, :] != None)  # noqa: E711 (object arrays)
    same = ~known | (ra[:, None] == ro[None, :])
    return [bool(x) for x in (near & same).any(1)]


def stratum_of(dist_m, edges=DIST_STRATA_M) -> str:
    if dist_m is None or not np.isfinite(dist_m):
        return "unknown"
    i = int(np.searchsorted(np.asarray(edges), dist_m, side="right")) - 1
    lo = edges[i]
    hi = edges[i + 1] if i + 1 < len(edges) else None
    return f"{int(lo)}-{int(hi)}m" if hi is not None else f"{int(lo)}m+"


# ----------------------------------------------------------------- stored channels

def _ao():
    import audio_others as ao
    return ao


def audio_context(store: Path = STORE) -> dict:
    """audio_others' stored peaks, dev thresholds and bank metadata."""
    ao = _ao()
    from reticle.adjudication.ability_audio import FPS
    inv = ao.inventory(store)
    loaded = {sid: got for sid in inv if (got := ao.load_peaks(sid)) is not None}
    merge = int(round(ao.MERGE_S * FPS))
    thr = ao.thresholds(loaded, ao._absent(inv), merge)
    W = ao.whitener(store)
    agents = sorted({a for _s, (pk, _l, _m) in loaded.items() for a, _c in pk}, key=canon)
    banks = {a: json.loads(str(np.load(ao.bank_path(a, W), allow_pickle=False)["meta"]))
             for a in agents}
    return {"inv": inv, "loaded": loaded, "merge": merge, "thr": thr, "banks": banks, "fps": FPS}


def audio_witnesses(sid: str, ctx: dict, cat) -> list[dict]:
    """audio_others detections of the lineup's agents as witnesses, the side
    from the lineup owner (`both` for a mirror)."""
    ao = _ao()
    got = ctx["loaded"].get(sid)
    sides = (ctx["inv"].get(sid) or {}).get("lineup")
    if got is None or not sides:
        return []
    pk, _live, _meta = got
    side_of = defaultdict(set)
    for sd, agents in sides.items():
        for a in agents:
            if a:
                side_of[canon(a)].add(sd)
    out = []
    for (agent, cls), r in pk.items():
        sd = side_of.get(canon(agent))
        t = ctx["thr"].get((agent, cls), {}).get("thr")
        if not sd or t is None:
            continue
        side = next(iter(sd)) if len(sd) == 1 else "both"
        keys = ao.class_keys(cls, ctx["banks"][agent]["groups"])
        slots = [cat.by_key.get((canon(agent), k)) for k in keys]
        slots = [s for s in slots if s]
        if not slots:
            continue
        for f in ao.detections(r["frame"], r["value"], t, ctx["merge"]):
            out.append({"channel": "audio_others", "side": side, "agent": agent,
                        "slot": slots[0] if len(slots) == 1 else None, "slots": slots,
                        "t_ms": float(f) * 1000.0 / ctx["fps"], "cls": cls,
                        "key": ("audio_others", agent, cls, int(f)), "ability": None})
    return out


def inventory(store: Path = STORE) -> dict:
    """Per Riot-recorded session: stored rows per channel stream, and the
    witnesses of OTHER players' casts each channel gives there."""
    import ability_coverage as ac
    sessions, cat = ac.load_sessions(None, store)
    ctx = audio_context(store)
    ev = store / "events"
    streams = ("ability_state", "ult_cast", "ult_line", "ability_shape", "ability_fit",
               "ability_wall", "smoke_owner", "death", "assist", "killfeed_assist",
               "ability_icon", "ability_gate", "enemy_track", "round_entity", "minimap_object")
    out = {}
    for s in sessions:
        sid = s["session"]
        row = {"streams": {n: (ev / n / f"{sid}.jsonl").is_file() for n in streams},
               "audio_others_peaks": sid in ctx["loaded"]}
        if "refused" in s:
            row["refused"] = s["refused"]
            out[sid] = row
            continue
        w = s["witnesses"] + audio_witnesses(sid, ctx, cat)
        c = Counter()
        for x in w:
            c[f"{x['channel']}.{x['side']}"] += 1
        row["witnesses"] = dict(sorted(c.items()))
        out[sid] = row
    return out


# ----------------------------------------------------------------- replay

def replay_truth(store: Path = STORE, los: str = "2d") -> dict:
    """The replay's casts (`audio_others.replay_casts`), each with 2D or 3D
    line of sight between caster and player from the sightline tables (read
    only), and the listener's live state from the stored audio frames."""
    ao = _ao()
    import replay_abilities as ra
    import riot_ground_truth as rg
    rc = ao.replay_casts(store)
    casts = rc["casts"]
    basis = "not measured"
    if los in ("2d", "3d") and casts:
        try:
            import sightlines as sl_mod
            d_riot = ao.riot_sessions(store)[REPLAY_SESSION]
            ref = rg.Reference(store / "external" / "valorant-api", fetch=False)
            mname = ref.map_of(d_riot["match"]["matchInfo"]["mapId"])["displayName"].lower()
            sl = sl_mod.load(mname, store, kind=los)
            if sl is None:
                basis = f"no {los} sightline table for {mname}"
            else:
                rp = ra.Export(REPLAY_MATCH).rp
                t = np.array([c["t_rep"] for c in casts])
                me = rp.sample(rc["me"], t)
                cx, cy = np.full(len(casts), np.nan), np.full(len(casts), np.nan)
                for sub in {c["subject"] for c in casts}:
                    m = np.array([c["subject"] == sub for c in casts])
                    q = rp.sample(sub, t[m])
                    cx[m], cy[m] = q["x"], q["y"]
                loc = np.array([c["location"] if c["location"] else [np.nan] * 3 for c in casts], float)
                miss = ~np.isfinite(cx)
                cx[miss], cy[miss] = loc[miss, 0], loc[miss, 1]
                ok = np.isfinite(cx) & np.isfinite(me["x"])
                v = sl.los_near(np.stack([cx[ok], cy[ok]], 1), np.stack([me["x"][ok], me["y"][ok]], 1))
                vals = np.full(len(casts), None, object)
                vals[ok] = [bool(x) for x in v]
                for c, x in zip(casts, vals):
                    c["los"] = x
                basis = f"{getattr(sl, 'version', '?')} {getattr(sl, 'key', mname)} los_near ({los})"
        except Exception as e:  # read only and optional
            basis = f"sightlines unavailable: {type(e).__name__}: {e}"
    got = ao.load_peaks(REPLAY_SESSION)
    from reticle.adjudication.ability_audio import FPS
    live = got[1] if got else None
    for c in casts:
        k = int(c["t_cap_ms"] / 1000.0 * FPS)
        c["live"] = bool(live is not None and 0 <= k < len(live) and live[k])
    rc["los_basis"] = basis
    return rc


def riot_kills_capture(sid: str, d: dict, players: list[dict], store: Path = STORE) -> dict:
    """Riot's ability kills of a session as (killer, slot, capture ms), placed
    by `fit_alignment` against the stored kill-like deaths; the alignment's
    stamp beside."""
    import ability_coverage as ac
    import riot_ground_truth as rg
    deaths = rg.stored_deaths(store, sid)
    kill_like, _second = rg.split_deaths(deaths)
    kills = sorted(d["match"]["kills"], key=lambda k: k["gameTime"])
    if not kill_like:
        return {"kills": [], "align": None}
    al = rg.fit_alignment([k["gameTime"] for k in kills], [float(r["t_ms"]) for r in kill_like])
    a = al["a_ms"]
    agent = {p["subject"]: p["agent"] for p in players}
    out = []
    for k in kills:
        if k.get("killer") == k.get("victim"):
            continue
        fd = k.get("finishingDamage") or {}
        slot = None
        if fd.get("damageType") == "Ability":
            slot = {"GrenadeAbility": "Grenade"}.get(fd.get("damageItem"), fd.get("damageItem"))
        elif rg.ult_kill_kind(k, rg.asset_agent(agent.get(k["killer"]))):
            slot = "Ultimate"
        if slot in RIOT_SLOTS:
            out.append({"killer": k["killer"], "slot": slot, "t_cap_ms": a + float(k["gameTime"]),
                        "round": k.get("round"), "victim": k.get("victim")})
    # the slot rule is the coverage survey's; check the counts agree with it
    check = ac.riot_ability_kills(d, players)
    assert sum(check.values()) == len(out), (sid, sum(check.values()), len(out))
    return {"kills": out, "align": {k: v for k, v in al.items() if k != "pairs"}}


def score_replay(sess: dict, rc: dict, aw: list[dict], cat, vocab: dict) -> dict:
    """Per channel and class on the replay match: hits, recall, precision,
    offsets; per cast the hit channels; and the independence tables."""
    players = sess["players"]
    side_of = {p["subject"]: p["side"] for p in players}
    agent_of = {p["subject"]: p["agent"] for p in players}
    casts = [c for c in rc["casts"] if c["slot"] in RIOT_SLOTS]
    tc = [(c["t_cap_ms"] / 1000.0, (c["subject"], c["slot"])) for c in casts]
    for c in casts:
        c["hits"] = {}
    wits = sess["witnesses"] + aw
    by_ch = defaultdict(list)
    for w in wits:
        if w["t_ms"] is None:
            continue
        by_ch[w["channel"]].append(w)
    per_cls = {}
    for ch, ws in sorted(by_ch.items()):
        wl = [(w["t_ms"] / 1000.0, set(candidate_cells(w, players))) for w in ws]
        if ch in EFFECT_CHANNELS:
            # nearest first within the lookback: the latest cast before the effect
            prs = pair_witnesses(wl, tc, pre=EFFECT_AFTER_S, post=EFFECT_LOOKBACK_S)
        else:
            pre, post = WINDOW_S.get(ch, DEFAULT_WINDOW_S)
            prs = pair_witnesses(wl, tc, pre=pre, post=post)
        paired_w = {}
        for i, j, dt in prs:
            casts[j]["hits"][ch] = round(dt, 3)
            paired_w[i] = dt
            if ch == "audio_others":
                ws[i]["_cast"] = j
        for i, (w, (_t, cells)) in enumerate(zip(ws, wl)):
            ags = {canon(agent_of[s]) for s, _sl in cells}
            sls = {sl for _s, sl in cells}
            if not cells:
                k = ("unresolved", w.get("agent"), w.get("slot"))
            else:
                k = (next(iter(ags)) if len(ags) == 1 else "multi",
                     "|".join(sorted(sls)))
            r = per_cls.setdefault((ch,) + k, {"witnesses": 0, "paired": 0, "dt": []})
            r["witnesses"] += 1
            if i in paired_w:
                r["paired"] += 1
                r["dt"].append(paired_w[i])
    # the agree rule, timed: an audio detection is admitted where another
    # channel's witness of a shared candidate cell agrees (`agree_keep`)
    agree = Counter()
    round_of = sess.get("round_of") or (lambda t: None)
    for w in by_ch.get("audio_others", []):
        cells = set(candidate_cells(w, players))
        other = [(x["t_ms"] / 1000.0, ch, round_of(x["t_ms"])) for ch, xs in by_ch.items()
                 if ch != "audio_others" for x in xs if cells & set(candidate_cells(x, players))]
        keep = agree_keep([w["t_ms"] / 1000.0], other, [round_of(w["t_ms"])])[0]
        agree["audio_detections"] += 1
        agree["admitted"] += keep
        agree["admitted_paired"] += keep and "_cast" in w
        if keep and "_cast" in w:
            casts[w["_cast"]]["agree_audio"] = True
    agree["precision_admitted"] = (round(agree["admitted_paired"] / agree["admitted"], 4)
                                   if agree["admitted"] else None)
    for c in casts:
        c["agree_hit"] = bool(set(c["hits"]) - {"audio_others"}) or bool(c.get("agree_audio"))
    # recall per (agent, slot, side)
    rec = {}
    for c in casts:
        k = (c["agent"], c["slot"], c["side"])
        r = rec.setdefault(k, {"casts": 0, "live": 0, "hits": Counter(), "live_hits": Counter(),
                               "any": 0, "any_cast": 0, "agree": 0})
        r["casts"] += 1
        r["live"] += c["live"]
        for ch in c["hits"]:
            r["hits"][ch] += 1
            r["live_hits"][ch] += c["live"]
        r["any"] += bool(c["hits"])
        r["any_cast"] += bool(set(c["hits"]) - set(EFFECT_CHANNELS))
        r["agree"] += c["agree_hit"]
    prec = {}
    for (ch, a, sl), r in per_cls.items():
        prec[f"{ch}|{a}|{sl}"] = {"witnesses": r["witnesses"], "paired": r["paired"],
                                   "precision": round(r["paired"] / r["witnesses"], 4),
                                   "dt_median_s": (round(float(np.median(r["dt"])), 3)
                                                   if r["dt"] else None)}
    chans = sorted(by_ch)
    tot = {}
    for ch in chans:
        ws = sum(v["witnesses"] for k, v in prec.items() if k.startswith(ch + "|"))
        pw = sum(v["paired"] for k, v in prec.items() if k.startswith(ch + "|"))
        el = [c for c in casts if c["side"] in OTHER_SIDES
              and (canon(c["agent"]), c["slot"]) in vocab.get(ch, set())]
        tot[ch] = {"witnesses": ws, "paired": pw, "precision": round(pw / ws, 4) if ws else None,
                   "other_casts_in_vocab": len(el),
                   "other_hits": sum(ch in c["hits"] for c in el),
                   "recall_in_vocab": (round(sum(ch in c["hits"] for c in el) / len(el), 4)
                                       if el else None),
                   "by_side": {sd: {"casts": sum(c["side"] == sd for c in casts),
                                    "hits": sum(c["side"] == sd and ch in c["hits"] for c in casts)}
                               for sd in ("self", "ally", "enemy")}}
    for ws in by_ch.values():
        for w in ws:
            w.pop("_cast", None)
    return {"casts": casts, "recall": rec, "precision": prec, "channels": tot,
            "side_of": side_of, "agree": dict(agree)}


def cast_strata(c: dict) -> dict[str, str]:
    """The strata a cast falls in: distance bin, line of sight, the
    listener's live state and the caster's side."""
    return {"dist": stratum_of(c.get("dist_m")), "los": str(c.get("los")),
            "live": str(bool(c.get("live"))), "side": c["side"]}


def opportunity(ch: str, casts: list[dict], vocab: dict, kill_casts: set) -> list[dict]:
    """The casts a channel could witness: other players' casts in its
    vocabulary; for the killfeed, only those that killed."""
    el = [c for c in casts if c["side"] in OTHER_SIDES
          and (canon(c["agent"]), c["slot"]) in vocab.get(ch, set())]
    if ch == "killfeed":
        el = [c for c in el if id(c) in kill_casts]
    return el


def independence(casts: list[dict], vocab: dict, kill_casts: set, channels) -> dict:
    """Pairwise miss tables over the casts both channels could witness (each
    channel's `opportunity`): pooled, per stratum (`cast_strata`), and the
    Mantel-Haenszel odds ratio over the distance strata. `channels` are the
    channels that can witness another player and hold rows on the session."""
    chans = sorted(channels)
    out = {}
    for ia, a in enumerate(chans):
        for b in chans[ia + 1:]:
            if {a, b} <= set(EFFECT_CHANNELS):
                continue
            ob = {id(c) for c in opportunity(b, casts, vocab, kill_casts)}
            el = [c for c in opportunity(a, casts, vocab, kill_casts) if id(c) in ob]
            row = {"n": len(el)}
            if len(el) < 4:
                row["refused"] = "fewer_than_4_shared_opportunities"
                out[f"{a}~{b}"] = row
                continue
            ma = np.array([a not in c["hits"] for c in el])
            mb = np.array([b not in c["hits"] for c in el])
            row["pooled"] = miss_table(ma, mb)
            row["strata"] = {}
            st = [cast_strata(c) for c in el]
            for key in ("dist", "los", "live", "side"):
                v = np.array([s[key] for s in st])
                for s in sorted(set(v)):
                    row["strata"][f"{key}:{s}"] = miss_table(ma[v == s], mb[v == s])
            row["mh_odds_ratio_distance"] = mh_odds_ratio(
                [x["table"] for k, x in row["strata"].items()
                 if k.startswith("dist:") and k != "dist:unknown"])
            row["correlated"] = correlated(row["pooled"])
            row["correlated_in"] = sorted(k for k, v in row["strata"].items() if correlated(v))
            out[f"{a}~{b}"] = row
    return out


def miss_by_cause(casts: list[dict], vocab: dict, kill_casts: set, channels) -> dict:
    """Per channel: its opportunities and hits per stratum, and the test of
    hit against stratum (`scipy.stats.chi2_contingency` over the strata
    with a cast; Fisher's exact test where there are two). A channel whose
    misses depend on the same stratum as another's shares a cause with it."""
    from scipy.stats import chi2_contingency, fisher_exact
    out = {}
    for ch in sorted(channels):
        el = opportunity(ch, casts, vocab, kill_casts)
        res = {"opportunities": len(el), "hits": sum(ch in c["hits"] for c in el)}
        for key in ("dist", "los", "live", "side"):
            r = defaultdict(Counter)
            for c in el:
                s = cast_strata(c)[key]
                r[s]["casts"] += 1
                r[s]["hits"] += ch in c["hits"]
            rows = {k: dict(x, recall=round(x["hits"] / x["casts"], 4)) for k, x in sorted(r.items())}
            known = [k for k in rows if k not in ("unknown", "None")]
            t = np.array([[rows[k]["hits"], rows[k]["casts"] - rows[k]["hits"]] for k in known])
            p = None
            if len(known) >= 2 and t.sum(0).all():
                p = (fisher_exact(t)[1] if len(known) == 2 else chi2_contingency(t)[1])
            res[key] = {"strata": rows, "p": None if p is None else round(float(p), 5)}
        out[ch] = res
    return out


def cell_independence(sessions: list[dict], vocab: dict, present: dict, channels) -> dict:
    """Supplementary, added after the pre-registration: the same pairwise
    test over every session's (player, slot) cells of other players with at
    least one Riot cast, where both channels hold rows on the session and
    both name the class; a channel MISSES a cell when it resolves none of
    the cell's casts. The killfeed's opportunities are the cells with a Riot
    ability kill. Shared causes here are side, agent and match, not time."""
    rows = []
    for s in sessions:
        cw = cell_witnesses(s, s["audio_w"])
        kills = s["kills"]
        for p in s["players"]:
            if p["side"] not in OTHER_SIDES:
                continue
            for slot in RIOT_SLOTS:
                if not p["casts"][slot]:
                    continue
                n = Counter(w[1] for w in cw.get((p["subject"], slot), []))
                rows.append({"session": s["session"], "side": p["side"],
                             "cls": (canon(p["agent"]), slot), "n": n,
                             "kill": kills.get((p["subject"], slot), 0) > 0})
    chans = sorted(channels)
    out = {}
    for ia, a in enumerate(chans):
        for b in chans[ia + 1:]:
            if {a, b} <= set(EFFECT_CHANNELS):
                continue
            el = [r for r in rows if a in present[r["session"]] and b in present[r["session"]]
                  and r["cls"] in vocab.get(a, set()) and r["cls"] in vocab.get(b, set())
                  and ("killfeed" not in (a, b) or r["kill"])]
            if len(el) < 4:
                out[f"{a}~{b}"] = {"n": len(el), "refused": "fewer_than_4_cells"}
                continue
            ma = np.array([not r["n"][a] for r in el])
            mb = np.array([not r["n"][b] for r in el])
            row = {"n": len(el), "pooled": miss_table(ma, mb), "strata": {}}
            sd = np.array([r["side"] for r in el])
            for s in sorted(set(sd)):
                row["strata"][f"side:{s}"] = miss_table(ma[sd == s], mb[sd == s])
            row["correlated"] = correlated(row["pooled"])
            row["correlated_in"] = sorted(k for k, v in row["strata"].items() if correlated(v))
            out[f"{a}~{b}"] = row
    return out


# ----------------------------------------------------------------- count level

def cell_witnesses(sess: dict, aw: list[dict]) -> dict:
    """Per (subject, slot) cell: the witnesses that resolve to it alone, as
    (t_ms, channel, round)."""
    import ability_coverage as ac  # noqa: F401  (the session dict is its)
    players = sess["players"]
    out = defaultdict(list)
    for w in sess["witnesses"] + aw:
        cells = candidate_cells(w, players)
        if len(cells) != 1:
            continue
        out[cells[0]].append((w["t_ms"], w["channel"], sess["round_of"](w["t_ms"])
                              if w["t_ms"] is not None else None))
    return out


def rule_count(rule: str, ws: list[tuple], hi: set | None = None) -> tuple[int, int]:
    """(count, audio count) a rule gives one cell's witnesses."""
    if rule == "union":
        sel = ws
    elif rule == "today":
        sel = [w for w in ws if w[1] != "audio_others"]
    elif rule == "hi_union":
        sel = [w for w in ws if w[1] in (hi or set())]
    elif rule == "agree":
        other = [(w[0] / 1000.0, w[1], w[2]) for w in ws
                 if w[1] != "audio_others" and w[0] is not None]
        aud = [w for w in ws if w[1] == "audio_others"]
        keep = agree_keep([w[0] / 1000.0 for w in aud], other, [w[2] for w in aud])
        sel = [w for w in ws if w[1] != "audio_others"] + [w for w, k in zip(aud, keep) if k]
    else:
        sel = [w for w in ws if w[1] == rule]
    n = per_round_max([(w[2], w[1]) for w in sel])
    # the audio share of the count: per round the audio count where it is the max
    per = defaultdict(Counter)
    for w in sel:
        per[w[2]][w[1]] += 1
    na = sum(c["audio_others"] for c in per.values()
             if c.get("audio_others") and c["audio_others"] >= max(c.values()))
    return n, na


def count_level(sessions: list[dict], ctx: dict, cat, single_channels: list[str]) -> dict:
    """Per (agent, slot) of other players and half: each rule's count score
    with the null-corrected precision; the dev choice and its held score."""
    ao = _ao()
    rules = list(single_channels) + ["today", "union", "hi_union", "agree"]
    acc = {}  # (half, agent, slot, rule) -> [cells], expected_false
    today = defaultdict(lambda: [0, 0])
    for s in sessions:
        sid = s["session"]
        half = "dev" if ao.dev_half(sid) else "held"
        aw = s["audio_w"]
        cw = cell_witnesses(s, aw)
        live_min = ctx["loaded"][sid][2]["live_min"] if sid in ctx["loaded"] else 0.0
        # the audio false alarms per cell: each class's held absent-agent rate
        rate_cell = defaultdict(float)
        for (agent, cls), v in ctx["thr"].items():
            r = v.get("held_fa_per_min")
            if r is None:
                continue
            keys = ao.class_keys(cls, ctx["banks"][agent]["groups"])
            slots = [cat.by_key.get((canon(agent), k)) for k in keys]
            if len(slots) != 1 or not slots[0]:
                continue
            for p in s["players"]:
                if canon(p["agent"]) == canon(agent):
                    rate_cell[(p["subject"], slots[0])] += r
        for p in s["players"]:
            if p["side"] not in OTHER_SIDES:
                continue
            for slot in RIOT_SLOTS:
                cell = (p["subject"], slot)
                ws = cw.get(cell, [])
                riot = p["casts"][slot]
                today_n = per_round_max([(w[2], w[1]) for w in ws if w[1] != "audio_others"])
                t = today[(half, p["side"])]
                t[0] += min(today_n, riot)
                t[1] += riot
                ef_all = rate_cell.get(cell, 0.0) * live_min
                for rule in rules:
                    if rule == "hi_union":
                        continue
                    n, na = rule_count(rule, ws)
                    ef = 0.0
                    if rule in ("audio_others", "union") and na:
                        ef = min(ef_all, na)
                    elif rule == "agree" and na:
                        # chance a random audio false alarm falls in an agreeing window
                        other = [w for w in ws if w[1] != "audio_others"]
                        span_s = sum(EFFECT_LOOKBACK_S if w[1] in EFFECT_CHANNELS else 2 * AGREE_S
                                     for w in other)
                        frac = min(1.0, span_s / max(1.0, live_min * 60.0))
                        ef = min(ef_all * frac, na)
                    a = acc.setdefault((half, canon(p["agent"]), p["agent"], slot, rule),
                                       {"cells": [], "ef": 0.0, "side_cells": defaultdict(list)})
                    a["cells"].append((n, riot))
                    a["side_cells"][p["side"]].append((n, riot))
                    a["ef"] += ef
                acc.setdefault((half, canon(p["agent"]), p["agent"], slot, "_ws"),
                               {"cells": [], "ef": 0.0, "side_cells": defaultdict(list)}
                               )["cells"].append((ws, riot, rate_cell.get(cell, 0.0) * live_min))
    classes = sorted({(k[1], k[2], k[3]) for k in acc}, key=lambda x: (x[0], x[2]))
    seen, out = set(), []
    for ca, agent, slot in classes:
        if (ca, slot) in seen:
            continue
        seen.add((ca, slot))
        row = {"agent": agent, "slot": slot, "ability": cat.name(agent, slot), "dev": {}, "held": {}}
        for half in ("dev", "held"):
            for rule in rules:
                if rule == "hi_union":
                    continue
                a = acc.get((half, ca, agent, slot, rule))
                if a is None:
                    continue
                sc = count_score(a["cells"])
                sc["expected_false_audio"] = round(a["ef"], 2)
                sc["precision"] = precision_estimate(sc, a["ef"])
                sc["by_side"] = {sd: count_score(v) for sd, v in a["side_cells"].items()}
                row[half][rule] = sc
        # hi_union: the channels whose DEV precision reaches the bar
        hi = {r for r in single_channels
              if (row["dev"].get(r) or {}).get("precision") is not None
              and row["dev"][r]["precision"] >= PREC_BAR}
        row["hi_channels"] = sorted(hi)
        for half in ("dev", "held"):
            a = acc.get((half, ca, agent, slot, "_ws"))
            if a is None:
                continue
            cells, ef = [], 0.0
            sides = defaultdict(list)
            for ws, riot, efc in a["cells"]:
                n, na = rule_count("hi_union", ws, hi)
                cells.append((n, riot))
                ef += min(efc, na) if na else 0.0
            sc = count_score(cells)
            sc["expected_false_audio"] = round(ef, 2)
            sc["precision"] = precision_estimate(sc, ef)
            row[half]["hi_union"] = sc
        dev_ok = {r: s for r, s in row["dev"].items() if s["witnessed"]}
        row["choice"] = choose_rule(dev_ok)
        held = row["held"]
        single = [held[r]["recall"] for r in single_channels
                  if r in held and held[r]["recall"] is not None and held[r]["witnessed"]]
        row["held_best_single_recall"] = max(single) if single else 0.0
        ch = held.get(row["choice"]) if row["choice"] else None
        row["held_choice"] = ch
        riot_held = held.get("union", {}).get("riot", 0)
        row["x1_pass"] = bool(ch and ch["precision"] is not None and ch["precision"] >= PREC_BAR
                              and riot_held >= X1_MIN_RIOT
                              and (ch["recall"] or 0) > row["held_best_single_recall"])
        out.append(row)
    tot = {f"{h}.{sd}": {"today_covered": v[0], "riot": v[1]} for (h, sd), v in sorted(today.items())}
    return {"classes": out, "today": tot}


def gain_totals(classes: list[dict], half: str = "held") -> dict:
    """Per side on one half: Riot, today's covered (`today`, every channel
    but audio_others), the chosen rule's covered (today's where a class has
    no choice), gained, the audio false alarms the chosen rule admits, and
    the net gain as an unclipped range (`gained - expected_false`, and
    `gained * (1 - expected_false / witnessed)`)."""
    out = defaultdict(Counter)
    for r in classes:
        today = (r[half].get("today") or {}).get("by_side") or {}
        ch = r["choice"] if r["choice"] in r[half] else "today"
        sc = r[half].get(ch) or {}
        chosen = sc.get("by_side") or {}
        tot_w = sc.get("witnessed") or 0
        for sd in set(today) | set(chosen):
            o = out[sd]
            t = today.get(sd, {})
            c = chosen.get(sd, t)
            o["riot"] += c.get("riot", 0)
            o["today_covered"] += t.get("covered", 0)
            o["chosen_covered"] += c.get("covered", 0)
            o["chosen_witnessed"] += c.get("witnessed", 0)
            share = c.get("witnessed", 0) / tot_w if tot_w else 0.0
            o["expected_false"] += (sc.get("expected_false_audio") or 0.0) * share
    res = {}
    for sd, o in sorted(out.items()):
        g = o["chosen_covered"] - o["today_covered"]
        ef = o["expected_false"]
        w = o["chosen_witnessed"]
        res[sd] = dict(o, expected_false=round(ef, 1), gained=g,
                       net_unclipped=round(g - ef, 1),
                       net_prop=round(g * (1.0 - ef / w), 1) if w else 0.0,
                       recall_today=round(o["today_covered"] / o["riot"], 4) if o["riot"] else None,
                       recall_chosen=round(o["chosen_covered"] / o["riot"], 4) if o["riot"] else None)
    return res


# ----------------------------------------------------------------- effects

def stored_ability_kills(sid: str, cat, store: Path = STORE) -> list[dict]:
    """Every stored ability kill (death verdicts of weapon category ability,
    revives and second lives out) as a killfeed witness, one per death:
    `ability_coverage.witnesses_killfeed` applied row by row, so its one
    per (round, killer, ability) rule does not merge them."""
    import ability_coverage as ac
    rows = ac._rows(store / "events" / "death" / f"{sid}.jsonl")
    return [w for r in rows for w in ac.witnesses_killfeed([r], cat) if w.get("kill")]


def effects(sessions: list[dict], cat, store: Path = STORE,
            lookbacks=(EFFECT_LOOKBACK_S, 10.0)) -> dict:
    """Riot's other-player ability kills explained by a stored ability kill
    of that player and slot within KILL_TOL_S, and by a cast witness of that
    cell up to each lookback before (all cast channels; without audio_others;
    and the count a random placement of the cell's audio detections would
    explain, the chance floor). The assist panel's other-player ability icons
    with a cast witness before them, the same way."""
    import riot_ground_truth as rg
    recs = rg.riot_records(store)
    tot = Counter()
    chance = Counter()
    per_cls = defaultdict(Counter)
    for s in sessions:
        sid = s["session"]
        rk = riot_kills_capture(sid, recs[sid], s["players"], store)
        side = {p["subject"]: p["side"] for p in s["players"]}
        agent = {p["subject"]: p["agent"] for p in s["players"]}
        cw = cell_witnesses(s, s["audio_w"])
        kf = defaultdict(list)
        for w in stored_ability_kills(sid, cat, store):
            cells = candidate_cells(w, s["players"])
            if len(cells) == 1 and w["t_ms"] is not None:
                kf[cells[0]].append(w["t_ms"] / 1000.0)
        live_s = max(1.0, s.get("live_min", 0.0) * 60.0)
        for k in rk["kills"]:
            if side[k["killer"]] not in OTHER_SIDES:
                continue
            cell = (k["killer"], k["slot"])
            ws = [w for w in cw.get(cell, []) if w[0] is not None]
            t = k["t_cap_ms"] / 1000.0
            got = {"kills": True,
                   "killfeed": any(abs(x - t) <= KILL_TOL_S for x in kf.get(cell, []))}
            n_audio = sum(w[1] == "audio_others" for w in ws)
            for lb in lookbacks:
                tag = f"{int(lb)}s"
                prior = [w for w in ws if w[1] not in EFFECT_CHANNELS and 0 <= t - w[0] / 1000.0 <= lb]
                got[f"cast_witness_{tag}"] = bool(prior)
                got[f"cast_witness_no_audio_{tag}"] = any(w[1] != "audio_others" for w in prior)
                got[f"either_{tag}"] = got["killfeed"] or bool(prior)
                chance[f"kill.audio_chance_{tag}"] += 1.0 - float(np.exp(-n_audio * lb / live_s))
            c = per_cls[(agent[k["killer"]], k["slot"])]
            for n, v in got.items():
                tot[f"kill.{n}"] += v
                tot[f"kill.{side[k['killer']]}.{n}"] += v
                c[n] += v
        for (sub, slot), ws in cw.items():
            if side.get(sub) not in OTHER_SIDES:
                continue
            n_audio = sum(w[1] == "audio_others" for w in ws)
            for w in ws:
                if w[1] != "assist_icon" or w[0] is None:
                    continue
                t = w[0] / 1000.0
                tot["assist.icons"] += 1
                tot[f"assist.{side[sub]}.icons"] += 1
                for lb in lookbacks:
                    tag = f"{int(lb)}s"
                    prior = [x for x in ws if x[1] not in EFFECT_CHANNELS and x[0] is not None
                             and 0 <= t - x[0] / 1000.0 <= lb]
                    tot[f"assist.cast_witness_{tag}"] += bool(prior)
                    tot[f"assist.cast_witness_no_audio_{tag}"] += any(x[1] != "audio_others"
                                                                      for x in prior)
                    chance[f"assist.audio_chance_{tag}"] += 1.0 - float(np.exp(-n_audio * lb / live_s))
    out = dict(tot)
    out.update({k: round(v, 1) for k, v in chance.items()})
    for k, base in (("kill", tot["kill.kills"]), ("assist", tot["assist.icons"])):
        for n in list(tot):
            if n.startswith(f"{k}.") and n.count(".") == 1 and base and n not in ("kill.kills", "assist.icons"):
                out[f"{n}.share"] = round(tot[n] / base, 4)
    out["per_class"] = {f"{a}|{sl}": dict(v) for (a, sl), v in sorted(per_cls.items(), key=str)}
    return out


# ----------------------------------------------------------------- report

def vocabulary(sessions: list[dict], ctx: dict, cat) -> dict:
    """Per channel: the (agent, slot) classes it witnessed (resolved to one
    cell) on any session; audio_others: the classes with a threshold."""
    ao = _ao()
    v = defaultdict(set)
    for s in sessions:
        for w in s["witnesses"]:
            if w["slot"] in RIOT_SLOTS and w.get("agent"):
                v[w["channel"]].add((canon(w["agent"]), w["slot"]))
    for (agent, cls), x in ctx["thr"].items():
        if x.get("thr") is None:
            continue
        for k in ao.class_keys(cls, ctx["banks"][agent]["groups"]):
            sl = cat.by_key.get((canon(agent), k))
            if sl:
                v["audio_others"].add((canon(agent), sl))
    return dict(v)


#: The streams behind each channel that can witness another player's cast;
#: tray, audio and minimap_shape witness the player's own casts only.
OTHER_CHANNEL_STREAMS = {"ult_cast": ("ult_cast",), "killfeed": ("death",),
                         "assist_icon": ("assist",), "smoke": ("smoke_owner",),
                         "minimap_fit": ("ability_fit", "ability_wall")}


def present_channels(sid: str, streams: dict, ctx: dict) -> set[str]:
    """The channels able to witness another player that hold stored rows on
    a session: a missing stream is no witness, never a miss."""
    out = {ch for ch, names in OTHER_CHANNEL_STREAMS.items() if any(streams.get(n) for n in names)}
    if sid in ctx["loaded"]:
        out.add("audio_others")
    return out


def build_report(store: Path = STORE, los: str = "2d") -> dict:
    import ability_coverage as ac
    from reticle.rounds import round_containing
    from reticle.store import Store
    t0 = time.time()
    sessions_all, cat = ac.load_sessions(None, store)
    ctx = audio_context(store)
    st = Store(store)
    sessions = []
    for s in sessions_all:
        if "refused" in s:
            continue
        man = st.read_manifest(s["session"])
        table = st.read_rounds(s["session"], man["ingested_at"][:10])
        rounds = table.to_pylist() if table is not None else []

        def round_of(t, rounds=rounds):
            r = round_containing(t, rounds)
            return r["round_no"] if r else None

        s["round_of"] = round_of
        s["audio_w"] = audio_witnesses(s["session"], ctx, cat)
        got = ctx["loaded"].get(s["session"])
        s["live_min"] = got[2]["live_min"] if got else 0.0
        sessions.append(s)
    vocab = vocabulary(sessions, ctx, cat)
    present = {s["session"]: present_channels(s["session"], s["streams"], ctx) for s in sessions}
    rep = {"version": ABILITY_XCHANNEL_VERSION, "sessions": [s["session"] for s in sessions],
           "refused": {s["session"]: s["refused"] for s in sessions_all if "refused" in s},
           "dev": [s["session"] for s in sessions if _ao().dev_half(s["session"])],
           "held": [s["session"] for s in sessions if not _ao().dev_half(s["session"])],
           "vocab": {k: sorted("|".join(x) for x in v) for k, v in vocab.items()}}
    # inventory of witnesses per channel and side
    inv = defaultdict(Counter)
    for s in sessions:
        for w in s["witnesses"] + s["audio_w"]:
            inv[w["channel"]][f"{w['side']}"] += 1
        for ch in {w["channel"] for w in s["witnesses"] + s["audio_w"]}:
            inv[ch]["sessions_with_rows"] += 1
    rep["witness_inventory"] = {k: dict(v) for k, v in sorted(inv.items())}
    # replay
    rp = next((s for s in sessions if s["session"] == REPLAY_SESSION), None)
    if rp is not None:
        rc = replay_truth(store, los)
        sc = score_replay(rp, rc, rp["audio_w"], cat, vocab)
        recs = _ao().riot_sessions(store)
        rk = riot_kills_capture(REPLAY_SESSION, recs[REPLAY_SESSION], rp["players"], store)
        casts = sc["casts"]
        kill_casts = set()
        kill_rows = []
        for k in rk["kills"]:
            prior = [c for c in casts if (c["subject"], c["slot"]) == (k["killer"], k["slot"])
                     and 0 <= k["t_cap_ms"] - c["t_cap_ms"] <= EFFECT_LOOKBACK_S * 1000.0]
            if prior:
                c = max(prior, key=lambda c: c["t_cap_ms"])
                kill_casts.add(id(c))
                kill_rows.append({"agent": c["agent"], "slot": c["slot"], "side": c["side"],
                                  "lag_s": round((k["t_cap_ms"] - c["t_cap_ms"]) / 1000.0, 2),
                                  "hits": sorted(c["hits"])})
            else:
                kill_rows.append({"killer_side": sc["side_of"].get(k["killer"]), "slot": k["slot"],
                                  "no_prior_cast": True})
        rep["replay"] = {
            "session": REPLAY_SESSION, "los_basis": rc["los_basis"], "align_a_ms": rc["align_a_ms"],
            "kill_align": rk["align"],
            "casts": dict(Counter(f"{c['side']}.{'live' if c['live'] else 'not_live'}" for c in casts)),
            "channels": sc["channels"],
            "recall": {f"{a}|{sl}|{sd}": dict(v, hits=dict(v["hits"]), live_hits=dict(v["live_hits"]))
                       for (a, sl, sd), v in sorted(sc["recall"].items(), key=str)},
            "precision": sc["precision"],
            "channels_present": sorted(present[REPLAY_SESSION]),
            "agree": sc["agree"],
            "independence": independence(casts, vocab, kill_casts, present[REPLAY_SESSION]),
            "miss_by_cause": miss_by_cause(casts, vocab, kill_casts, present[REPLAY_SESSION]),
            "kills": kill_rows,
            "any_other": {"casts": sum(c["side"] in OTHER_SIDES for c in casts),
                          "hit": sum(c["side"] in OTHER_SIDES and bool(c["hits"]) for c in casts),
                          "hit_cast_channel": sum(c["side"] in OTHER_SIDES and bool(
                              set(c["hits"]) - set(EFFECT_CHANNELS)) for c in casts)}}
        ind = rep["replay"]["independence"]
        x2 = [k for k, v in ind.items() if v.get("correlated") or v.get("correlated_in")]
        rep["X2"] = {"holds": bool(x2),
                     "pairs": {k: ind[k]["correlated_in"] + (["pooled"] if ind[k]["correlated"] else [])
                               for k in x2},
                     "testable": sorted(k for k, v in ind.items() if "pooled" in v
                                        and v["pooled"]["fisher_p"] is not None)}
    singles = sorted({w["channel"] for s in sessions for w in s["witnesses"] + s["audio_w"]}
                     - {"tray", "audio", "minimap_shape"})
    cl = count_level(sessions, ctx, cat, singles)
    rep["count_level"] = cl
    passing = [f"{r['agent']}|{r['slot']}" for r in cl["classes"] if r["x1_pass"]]
    rep["X1"] = {"holds": len(passing) >= X1_MIN_CLASSES, "classes_passing": passing,
                 "n_passing": len(passing),
                 "eligible": sum(1 for r in cl["classes"]
                                 if r["held"].get("union", {}).get("riot", 0) >= X1_MIN_RIOT)}
    rep["gain_held"] = gain_totals(cl["classes"], "held")
    rep["gain_dev"] = gain_totals(cl["classes"], "dev")
    other_capable = set().union(*present.values())
    rep["cell_independence"] = cell_independence(sessions, vocab, present, other_capable)
    rep["effects"] = effects(sessions, cat, store)
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def record_ledger(rep: dict) -> list[str]:
    from reticle import metrics
    deps = {"version": ABILITY_XCHANNEL_VERSION,
            "code": metrics.fingerprint(candidate_cells, pair_witnesses, miss_table, mh_odds_ratio,
                                        correlated, count_score, precision_estimate, choose_rule,
                                        per_round_max, agree_keep, stratum_of, audio_witnesses,
                                        score_replay, independence, rule_count, count_level,
                                        gain_totals, effects, cast_strata, opportunity,
                                        miss_by_cause, cell_independence, cell_witnesses,
                                        present_channels, stored_ability_kills, riot_kills_capture,
                                        WINDOW_S=WINDOW_S, AGREE_S=AGREE_S, PREC_BAR=PREC_BAR,
                                        EFFECT_LOOKBACK_S=EFFECT_LOOKBACK_S)}
    ctx = {"sessions": len(rep["sessions"]), "dev": rep["dev"], "held": rep["held"]}
    out = []
    rp = rep.get("replay")

    def kk(s):
        """A ledger field part the `[metric:...]` citation form can name."""
        return (str(s).replace(" ", "_").replace("/", "_").replace("|", ":")
                .replace("~", "-vs-").replace("+", "plus"))

    if rp:
        v = {}
        for ch, x in rp["channels"].items():
            for f in ("witnesses", "paired", "precision", "other_casts_in_vocab", "other_hits",
                      "recall_in_vocab"):
                v[f"{ch}.{f}"] = x[f]
            for sd, y in x["by_side"].items():
                v[f"{ch}.{sd}.casts"] = y["casts"]
                v[f"{ch}.{sd}.hits"] = y["hits"]
        for f, n in rp["any_other"].items():
            v[f"any_other.{f}"] = n
        for f, n in rp["agree"].items():
            v[f"agree.{f}"] = n
        metrics.record("ability_xchannel", part="replay", session=REPLAY_SESSION, values=v,
                       deps=deps, context=dict(ctx, los_basis=rp["los_basis"]))
        out.append(f"ability_xchannel/replay@{REPLAY_SESSION}")
        vi = {}
        for scope, tabs in (("replay", rp["independence"]), ("cells", rep["cell_independence"])):
            for pair_, x in tabs.items():
                vi[f"{scope}.{kk(pair_)}.n"] = x["n"]
                if "pooled" not in x:
                    continue
                p = x["pooled"]
                for f in ("p_miss_a", "p_miss_b", "p_miss_a_given_miss_b", "odds_ratio", "fisher_p"):
                    vi[f"{scope}.{kk(pair_)}.{f}"] = p[f]
                if "mh_odds_ratio_distance" in x:
                    vi[f"{scope}.{kk(pair_)}.mh_or_distance"] = x["mh_odds_ratio_distance"]
                vi[f"{scope}.{kk(pair_)}.correlated"] = int(bool(x["correlated"] or x["correlated_in"]))
                for s, y in x["strata"].items():
                    vi[f"{scope}.{kk(pair_)}.{kk(s)}.n"] = y["n"]
                    vi[f"{scope}.{kk(pair_)}.{kk(s)}.fisher_p"] = y["fisher_p"]
        for ch, x in rp["miss_by_cause"].items():
            vi[f"cause.{ch}.opportunities"] = x["opportunities"]
            vi[f"cause.{ch}.hits"] = x["hits"]
            for key in ("dist", "los", "live", "side"):
                vi[f"cause.{ch}.{key}.p"] = x[key]["p"]
                for s, y in x[key]["strata"].items():
                    vi[f"cause.{ch}.{key}.{kk(s)}.casts"] = y["casts"]
                    vi[f"cause.{ch}.{key}.{kk(s)}.hits"] = y["hits"]
        vi["X2_holds"] = int(rep["X2"]["holds"])
        metrics.record("ability_xchannel", part="independence", session=REPLAY_SESSION,
                       values=vi, deps=deps, context=ctx)
        out.append(f"ability_xchannel/independence@{REPLAY_SESSION}")
    vc = {"X1_holds": int(rep["X1"]["holds"]), "X1_passing": rep["X1"]["n_passing"],
          "X1_eligible": rep["X1"]["eligible"]}
    for r in rep["count_level"]["classes"]:
        k = kk(f"{r['agent']}:{r['slot']}")
        if r["choice"]:
            vc[f"{k}.choice_{r['choice']}"] = 1
        h = r["held_choice"]
        if h:
            vc[f"{k}.held_recall"] = h["recall"]
            vc[f"{k}.held_precision"] = h["precision"]
        vc[f"{k}.held_best_single_recall"] = r["held_best_single_recall"]
    for half in ("held", "dev"):
        for sd, x in rep[f"gain_{half}"].items():
            for f, n in x.items():
                vc[f"{half}.{sd}.{f}"] = round(n, 4) if isinstance(n, float) else n
    for k, x in rep["count_level"]["today"].items():
        vc[f"today.{k}.covered"] = x["today_covered"]
        vc[f"today.{k}.riot"] = x["riot"]
    metrics.record("ability_xchannel", part="combined", values=vc, deps=deps, context=ctx)
    out.append("ability_xchannel/combined")
    ve = {k: v for k, v in rep["effects"].items() if not isinstance(v, dict)}
    metrics.record("ability_xchannel", part="effects", values=ve, deps=deps, context=ctx)
    out.append("ability_xchannel/effects")
    return out


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory")
    rp = sub.add_parser("report")
    rp.add_argument("--record", action="store_true")
    rp.add_argument("--json", type=Path)
    rp.add_argument("--los", choices=("2d", "3d", "none"), default="2d")
    a = ap.parse_args(argv)
    _below_normal()
    if a.cmd == "inventory":
        print(json.dumps(inventory(), indent=1, default=_default))
        return 0
    rep = build_report(los=a.los)
    path = a.json or OUT / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep, indent=1, default=_default), encoding="utf-8")
    print("report ->", path, f"({rep['seconds']} s)")
    if a.record:
        print("ledger:", record_ledger(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
