r"""Event-level acceptance: what an owning layer emits, scored per question against replay truth.

This file is the start of the one acceptance harness, QUESTION_ACCEPTANCE.md
build step B7, begun early (task `event-harness-20261007`). AGENTS.md:
acceptance scores the events a layer emits; a reader's own score is only a
diagnostic, reported beside; a new scorer extends this file and never adds
another prototype. B7's episode derivations (T1, T2, T2g, matching; QA1-QA3)
join it as subcommands.

It owns evaluation only and changes no reader or lane code. It reuses the
truth join and does not restate it:

* the draw truth is `t1_draw_rule.RealDrawMatch(rule="T1d")`;
* the (sample, enemy) pairs and the extras are `enemy_lane_check.build_sets`;
* each track's lane outcome is `real_reader_schedule.track_outcome`, the
  sorting `RealMatch.enemy_reads` applies (`identity_abstained`,
  `agent_not_on_enemy_team`, `named`);
* the extras' classes are `teardrop_refusals.class_extras`; the true false
  accepts are its `TRUE_FA` (ping, x_mark, other);
* the round bootstrap is `teardrop_refusals`' (`N_BOOT`, `SEED`); pooled
  intervals resample rounds within each match and add the matches.

**`lane --tag TAG [SESSION ...]`** scores the enemy lane. It runs
`reticle.enemy_tracks.build`, pure over stored rows, on the tagged reader
arm's `minimap_object` rows
(`<store>/analysis/teardrop-refusals-20261007/<TAG>/<SESSION>.jsonl`) with
the store's rounds, death verdicts, lineup and portrait references, and
writes the tracks to `<store>/analysis/question-acceptance/<TAG>/enemy_track/`.
It never reads the stored `enemy_track` stream: the truth join reads the built
tracks in its place (`teardrop_refusals._Redirect.streams`). It reports:

* (a) the reader's true false accepts by lane outcome: `no_track` (the icon
  joined no track), `identity_abstained`, `agent_not_on_enemy_team`,
  `named_duplicate` (named an enemy, and another icon of the same frame
  carries a track of the same name) and `named`; the counts sum to the
  reader's true false accepts (checked on every run), and a named find whose
  track also holds icons T1d places on a drawn living enemy is counted apart
  (it joined a real enemy's track rather than starting its own);
* (b) per question the lane serves, the emitted tracks' accuracy beside the
  reader's: drawn-enemy presence by named slot (a T1d-drawn enemy has an icon
  in that frame whose track is named him), and position by named slot (that
  icon within `NEAR_CM` of his truth xy), each as recall over the T1d pairs
  beside the reader's hit rate (any icon within `NEAR_CM`); and as precision
  over the accepted icons beside the reader's icon precision (an icon within
  `NEAR_CM` of a drawn living enemy).

First measurement (the `pgb` arm, rows QH in the prediction ledger): of the
reader's pooled true false accepts
[metric:question_acceptance/lane/pgb@dev3#false_accepts=167], the lane
names [metric:question_acceptance/lane/pgb@dev3#fa_named=157] and leaves
[metric:question_acceptance/lane/pgb@dev3#fa_identity_abstained=10]
unnamed; none is named off the enemy team or duplicated in its frame. The
named-slot presence recall is
[metric:question_acceptance/lane/pgb@dev3#lane_presence=0.5677] beside the
reader's hit rate of [metric:question_acceptance/lane/pgb@dev3#reader_hit=0.6077].

**`--reality off|on|paired`** (0.2.0, task `detection-reality-20261007`)
is the arm switch for `round_lifetimes.detection_reality`. `off` builds the
lane without glyph verdicts, so every track is `unassessed` and nothing is
refused: the 0.1.0 measurement. `on` hands `enemy_tracks.build` the glyph
owner's verdicts, adjudicated in memory from the stored `ability_glyph` rows
(`adjudication.ability_glyph.disc_verdicts(compute=True)`; nothing is written
to the store), and a refused track's finds take the outcome
`reality_refused`, counted by reason. `paired` runs both and reports, per
question, the difference on minus off with a paired round bootstrap: the
same resampled rounds score both arms.

First paired measurement (pgb): the rule refused
[metric:question_acceptance/lane/pgb/reality@dev3#fa_reality_refused=79] of
the true false accepts, all Tejo's Stealth Drone on c817691bcd15
[domain:abilities/tejo-stealth-drone-enemy-minimap-icon]; pooled presence
precision rose by
[metric:question_acceptance/lane/pgb/reality-paired@dev3#lane_presence_precision_diff=0.0075]
and presence recall moved by
[metric:question_acceptance/lane/pgb/reality-paired@dev3#lane_presence_diff=-0.0003].
9acf02f98283 stayed unassessed: its stored `ability_glyph` rows predate the
current glyph bank, and the glyph owner refuses stale rows.

Stored rows and replay truth only; no decode, rescan or trial. The held-out
capture (cea8ecbc94ab) is refused. Not wired (`"wire": "no"` on its rows in
`notes/predictions.jsonl`): an evaluation.

    python prototypes/question_acceptance.py lane --tag pgb [SESSION ...] [--pings b1]
        [--reality off|on|paired] [--record]
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

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import teardrop_refusals as tr  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "question-acceptance-0.2.0"
TASK = "event-harness-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "question-acceptance"
DEV = tr.DEV
NEAR_CM = tr.NEAR_CM
#: The lane outcomes of a find, in report order.
OUTCOMES = ("no_track", "reality_refused", "identity_abstained", "agent_not_on_enemy_team",
            "named_duplicate", "named")
#: Outcomes the lane drops (the track is no entity, or carries no enemy-team name).
DROPPED = ("reality_refused", "identity_abstained", "agent_not_on_enemy_team")
#: The `--reality` arms and the folder suffix each writes under.
ARMS = {"off": "", "on": "_reality"}


# ----------------------------------------------------------------- pure parts

def icon_outcomes(icon_p, icon_eid, icon_subj, track_out: dict) -> np.ndarray:
    """Each icon's lane outcome (`OUTCOMES`).

    `icon_p`: the icon's frame position; `icon_eid`: the track its
    observation joined, or None; `icon_subj`: the enemy subject its track is
    named (-1 when dropped); `track_out`: each track's
    `real_reader_schedule.track_outcome`. A named icon is `named_duplicate`
    when another icon of its frame carries a track named the same subject."""
    p = np.asarray(icon_p, np.int64)
    subj = np.asarray(icon_subj, np.int64)
    out = np.array([("no_track" if e is None else track_out[e]) for e in icon_eid], dtype=object)
    named = subj >= 0
    if named.any():
        code = p[named] * (int(subj.max()) + 1) + subj[named]
        _u, inv, cnt = np.unique(code, return_inverse=True, return_counts=True)
        dup = np.zeros(p.size, bool)
        dup[np.flatnonzero(named)] = cnt[inv] > 1
        out[dup & (out == "named")] = "named_duplicate"
    return out


def lane_questions(ks, ic, pair_k, pair_j, icon_p, icon_subj, icon_x, icon_y, X, Y, drawn, alive,
                   p_of, near_cm: float = NEAR_CM) -> dict:
    """Per pair and per accepted icon, whether the emitted tracks answer.

    Pairs (`pair_k`, `pair_j`) are the T1d-drawn (sample, enemy) pairs; the
    accepted icons on valid samples are `ks` (sample) and `ic` (icon index).
    Returns boolean arrays: `pair_named` (an icon of that frame is named j),
    `pair_named_pos` (and within `near_cm` of j's truth), `icon_named`
    (the icon's track is named an enemy), `icon_named_drawn` (that enemy is
    drawn and alive at the sample), `icon_named_pos` (and within `near_cm`),
    and `icon_err_cm` (named icon to its enemy's truth, NaN otherwise)."""
    ks = np.asarray(ks, np.int64)
    ic = np.asarray(ic, np.int64)
    S = X.shape[0]
    subj = np.asarray(icon_subj, np.int64)[ic]
    named = subj >= 0
    sj = np.where(named, subj, 0)
    err = np.hypot(np.asarray(icon_x)[ic] - X[sj, ks], np.asarray(icon_y)[ic] - Y[sj, ks])
    err = np.where(named & np.isfinite(err), err, np.nan)
    on = named & drawn[sj, ks] & alive[sj, ks]
    pos = on & (err <= near_cm)
    # pairs: the (frame, subject) codes the named icons cover
    fp = np.asarray(icon_p, np.int64)[ic]
    code_named = np.unique(fp[named] * S + subj[named])
    pk = np.asarray(pair_k, np.int64)
    pj = np.asarray(pair_j, np.int64)
    pf = np.asarray(p_of, np.int64)[pk]
    pc = pf * S + pj
    pair_named = np.isin(pc, code_named)
    # position: an icon named j in that frame within near_cm of j's truth at the pair's sample
    pair_pos = np.zeros(pk.size, bool)
    if pk.size and named.any():
        order = np.argsort(fp[named] * S + subj[named], kind="stable")
        codes = (fp[named] * S + subj[named])[order]
        ix = np.asarray(icon_x)[ic][named][order]
        iy = np.asarray(icon_y)[ic][named][order]
        lo = np.searchsorted(codes, pc, side="left")
        hi = np.searchsorted(codes, pc, side="right")
        n = hi - lo
        rep = np.repeat(np.arange(pk.size), n)
        idx = np.arange(rep.size) - np.repeat(np.cumsum(n) - n, n) + np.repeat(lo, n)
        d = np.hypot(ix[idx] - X[pj[rep], pk[rep]], iy[idx] - Y[pj[rep], pk[rep]])
        ok = np.where(np.isfinite(d), d <= near_cm, False)
        pair_pos[rep[ok]] = True
    return {"pair_named": pair_named, "pair_named_pos": pair_pos, "icon_named": named,
            "icon_named_drawn": on, "icon_named_pos": pos, "icon_err_cm": err}


# ----------------------------------------------------------------- bootstrap

def _boot_pooled(per_match: list[tuple[np.ndarray, np.ndarray | None]]) -> list:
    """95% interval of a pooled sum (den None) or share, rounds resampled
    within each match and the matches added (`teardrop_refusals` N_BOOT, SEED)."""
    rng = np.random.default_rng(tr.SEED)
    num = np.zeros(tr.N_BOOT)
    den = np.zeros(tr.N_BOOT)
    for a, b in per_match:
        idx = rng.integers(0, len(a), (tr.N_BOOT, len(a)))
        num += a[idx].sum(1)
        if b is not None:
            den += b[idx].sum(1)
    if per_match and per_match[0][1] is None:
        return [int(np.percentile(num, 2.5)), int(np.percentile(num, 97.5))]
    s = num / np.maximum(den, 1)
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def _boot_pooled_diff(per_match: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]) -> list:
    """95% interval of a paired difference of pooled shares, arm A minus arm
    B: each replicate resamples a match's rounds once and scores both arms on
    them (`teardrop_refusals` N_BOOT, SEED). Each item is (num A, den A,
    num B, den B) per round of one match."""
    rng = np.random.default_rng(tr.SEED)
    na, da, nb, db = (np.zeros(tr.N_BOOT) for _ in range(4))
    for a1, b1, a2, b2 in per_match:
        idx = rng.integers(0, len(a1), (tr.N_BOOT, len(a1)))
        na += a1[idx].sum(1)
        da += b1[idx].sum(1)
        nb += a2[idx].sum(1)
        db += b2[idx].sum(1)
    d = na / np.maximum(da, 1) - nb / np.maximum(db, 1)
    return [round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)]


# ----------------------------------------------------------------- the lane

def build_lane(sid: str, tag: str, reality: str = "off") -> tuple[Path, dict]:
    """`enemy_tracks.build` over the tag's rows, written under OUT; returns
    the folder's file and the summary row. `reality` "on" hands the build the
    glyph owner's verdicts, adjudicated in memory from stored rows."""
    from reticle import enemy_tracks
    from reticle.adjudication.ability_glyph import disc_verdicts
    from reticle.adjudication.identity import load_ally_portrait_references
    from reticle.lineup import load_lineup
    from reticle.store import Store

    store = Store(STORE)
    with tr.rows_path(tag, sid).open(encoding="utf-8") as f:
        rows = [json.loads(ln) for ln in f if ln.strip()]
    man = store.read_manifest(sid)
    rounds = store.read_rounds(sid, man["ingested_at"][:10])
    if rounds is None:
        raise SystemExit(f"{sid}: no stored rounds")
    glyph = disc_verdicts(store, sid, compute=True) if reality == "on" else None
    if reality == "on" and glyph.get("skipped"):
        # the glyph owner refuses (stale or missing rows): every track is
        # `unassessed` with the reason, as production would leave it
        print(f"{sid}: reality arm unassessed: {glyph['skipped']}", flush=True)
    res = enemy_tracks.build(sid, rows, rounds.to_pylist(), store.read_events("death", sid) or [],
                             load_lineup(sid, store.root), load_ally_portrait_references(store.root),
                             glyph=glyph)
    p = OUT / tag / f"enemy_track{ARMS[reality]}" / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in res["rows"]:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    os.replace(tmp, p)
    return p, res["rows"][0]


def lane(sid: str, tag: str, ptag: str | None, reality: str = "off") -> dict:
    import enemy_lane_check as elc
    import t1_draw_rule as tdr

    tr.refuse(sid)
    t0 = time.perf_counter()
    p_et, summary = build_lane(sid, tag, reality)
    with p_et.open(encoding="utf-8") as f:
        why_refused = {r["id"]: r.get("reality_reason") for r in map(json.loads, f)
                       if r.get("kind") == "entity" and r.get("reality_status") == "refused"}
    tr._point_store(tag)
    tr._Redirect.streams = {"enemy_track": p_et.parent}
    M = tdr.RealDrawMatch(sid, rule="T1d")
    R = elc.build_sets(sid, M=M)
    J = R["join"]
    E = J["reads"]
    if E["stamp"].get("enemy_track_version") != summary["enemy_track_version"] or \
            E["tracks"] != summary["tracks"]:
        raise SystemExit(f"{sid}: the join read other tracks than the ones built ({E['stamp']})")
    ext = tr.class_extras(sid, tag, R, ptag)
    pairs = R["pairs"]
    rounds = sorted({r["round"] for r in pairs} | {r["round"] for r in R["extras"]})
    ri = {rn: i for i, rn in enumerate(rounds)}
    nr = len(rounds)

    # (a) the reader's true false accepts by lane outcome
    out_icon = icon_outcomes(E["icon_p"], E["icon_eid"], E["icon_subj"], E["track_outcome"])
    fa = [e for e in ext if e["cls"] in tr.TRUE_FA]
    by = {o: np.zeros(nr) for o in OUTCOMES}
    fa_rows = []
    for e in fa:
        o = str(out_icon[e["icon"]])
        by[o][ri[e["round"]]] += 1
        eid = E["icon_eid"][e["icon"]]
        fa_rows.append({**{k: e[k] for k in ("round", "k", "frame_idx", "t_cap", "icon_px", "cls", "icon",
                                             "nearest_enemy_m")},
                        "outcome": o, "track": eid, "agent": E["track_agent"].get(eid),
                        "track_observations": E["track_obs"].get(eid),
                        "reality_reason": why_refused.get(eid)})
    fa_n = np.zeros(nr)
    for e in fa:
        fa_n[ri[e["round"]]] += 1
    # a diagnostic: does a find's track also hold icons T1d places on a drawn
    # living enemy (it joined a real enemy's track), or only extras (its own)?
    extra_icons = np.unique([e["icon"] for e in R["extras"]]).astype(np.int64)
    u_all = np.unique(J["ic"])
    real = u_all[~np.isin(u_all, extra_icons)]
    real_of = Counter(e for e in E["icon_eid"][real] if e is not None)
    for r in fa_rows:
        r["track_real_icons"] = real_of.get(r["track"], 0) if r["track"] is not None else None
    if sum(v.sum() for v in by.values()) != fa_n.sum():
        raise SystemExit(f"{sid}: the outcomes do not sum to the false accepts")
    in_real = np.zeros(nr)
    for e, r in zip(fa, fa_rows):
        in_real[ri[e["round"]]] += r["outcome"].startswith("named") and bool(r["track_real_icons"])

    # (b) questions
    S = M.X.shape[0]
    pk = np.array([r["k"] for r in pairs], np.int64)
    pj = np.array([r["j"] for r in pairs], np.int64)
    Q = lane_questions(J["ks"], J["ic"], pk, pj, E["icon_p"], E["icon_subj"], E["icon_x"], E["icon_y"],
                       M.X, M.Y, J["drawn"], J["alive"], J["p_of"])
    pr = np.array([ri[r["round"]] for r in pairs], np.int64)
    hit = np.array([r["set"] == "hit" for r in pairs], bool)
    ir = np.array([ri.get(int(M.G_round[k]), -1) for k in J["ks"]], np.int64)
    if (ir < 0).any():
        raise SystemExit(f"{sid}: an accepted icon's round has no pair or extra")
    ext_icon = np.zeros(nr)
    for e in R["extras"]:
        ext_icon[ri[e["round"]]] += 1

    def per_round(mask, rr):
        return np.bincount(rr[mask], minlength=nr).astype(float)

    nums = {
        "reader_hit": (per_round(hit, pr), per_round(np.ones_like(hit), pr)),
        "lane_presence": (per_round(Q["pair_named"], pr), per_round(np.ones_like(hit), pr)),
        "lane_position": (per_round(Q["pair_named_pos"], pr), per_round(np.ones_like(hit), pr)),
        "reader_icon_precision": (per_round(np.ones(ir.size, bool), ir) - ext_icon,
                                  per_round(np.ones(ir.size, bool), ir)),
        "lane_named_share": (per_round(Q["icon_named"], ir), per_round(np.ones(ir.size, bool), ir)),
        "lane_presence_precision": (per_round(Q["icon_named_drawn"], ir), per_round(Q["icon_named"], ir)),
        "lane_position_precision": (per_round(Q["icon_named_pos"], ir), per_round(Q["icon_named"], ir)),
    }
    # same-agent duplicates in one frame, over frames holding a named icon
    # (each icon once: two samples can join one frame)
    u_ic = np.unique(J["ic"])
    fp = np.asarray(E["icon_p"], np.int64)[u_ic]
    sj = np.asarray(E["icon_subj"], np.int64)[u_ic]
    nm = sj >= 0
    fr_named = np.unique(fp[nm])
    code, cnt = np.unique(fp[nm] * S + sj[nm], return_counts=True)
    fr_dup = np.unique(code[cnt > 1] // S)
    err = Q["icon_err_cm"][Q["icon_named_drawn"]]
    refused_by = Counter(r["reality_reason"] for r in fa_rows if r["outcome"] == "reality_refused")
    res = {"session": sid, "tag": tag, "version": VERSION, "rule": "T1d", "pings_from": ptag or "store",
           "reality": reality, "detection_reality": summary.get("detection_reality"),
           "detection_reality_version": summary.get("detection_reality_version"),
           "fa_reality_refused_by_reason": dict(refused_by),
           "rounds": nr, "tracks": summary["tracks"], "track_identity": summary["identity"],
           "enemy_track_version": summary["enemy_track_version"],
           "minimap_object_version": summary["minimap_object_version"],
           "lineup_version": summary["lineup_version"],
           "death_adjudication_version": summary["death_adjudication_version"],
           "drops": E["drops"],
           "false_accepts": int(fa_n.sum()), "false_accepts_ci": tr._boot_count(rounds, fa_n),
           "fa_by_outcome": {o: int(v.sum()) for o, v in by.items()},
           "fa_by_outcome_ci": {o: tr._boot_count(rounds, v) for o, v in by.items()},
           "fa_dropped_share": round(float(sum(by[o].sum() for o in DROPPED)) / max(fa_n.sum(), 1), 4),
           "fa_dropped_share_ci": tr._boot_share(rounds, sum(by[o] for o in DROPPED), fa_n),
           "fa_named_in_real_track": int(in_real.sum()),
           "fa_named_in_real_track_ci": tr._boot_count(rounds, in_real),
           "fa_track_obs_median": _median([r["track_observations"] for r in fa_rows]),
           "track_obs_median": _median(list(E["track_obs"].values())),
           "questions": {}, "pairs": int(pk.size), "icons_valid": int(J["ks"].size),
           "named_frames": int(fr_named.size), "dup_frames": int(fr_dup.size),
           "dup_frame_share": round(fr_dup.size / max(fr_named.size, 1), 4),
           "named_err_m_median": None if not err.size else round(float(np.nanmedian(err)) / 100, 3),
           "secs": round(time.perf_counter() - t0, 1)}
    for q, (a, b) in nums.items():
        res["questions"][q] = {"value": round(float(a.sum() / max(b.sum(), 1)), 4),
                               "ci": tr._boot_share(rounds, a, b), "num": int(a.sum()), "den": int(b.sum())}
    stored = tr.OUT / tag / f"score_{sid}.json"
    res["reader_score_file"] = None
    if stored.is_file():
        s = json.loads(stored.read_text(encoding="utf-8"))
        res["reader_score_file"] = {"false_accepts": s["false_accepts"], "hits": s["hits"],
                                    "hit_rate": s["hit_rate"], "pings_from": s.get("pings_from")}
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / tag / f"fa{ARMS[reality]}_{sid}.jsonl", "w", encoding="utf-8") as f:
        for r in fa_rows:
            f.write(json.dumps(r) + "\n")
    res["_per_round"] = {"fa": fa_n, "by": by, "nums": nums, "in_real": in_real, "rounds": rounds}
    return res


def _median(v):
    v = [x for x in v if x is not None]
    return None if not v else float(np.median(v))


def _print(res: dict) -> None:
    q = res["questions"]
    print(f"{res['session']} {res['tag']} reality {res['reality']}: true false accepts {res['false_accepts']} "
          f"{res['false_accepts_ci']} (teardrop_refusals score: "
          f"{(res.get('reader_score_file') or {}).get('false_accepts')}); refused by reason "
          f"{res['fa_reality_refused_by_reason']}", flush=True)
    for o in OUTCOMES:
        print(f"   {o:24s} {res['fa_by_outcome'][o]:5d} {res['fa_by_outcome_ci'][o]}", flush=True)
    print(f"   dropped share {res['fa_dropped_share']} {res['fa_dropped_share_ci']}; named in a track holding "
          f"T1d-placed icons {res['fa_named_in_real_track']} {res['fa_named_in_real_track_ci']}; "
          f"FA track obs median {res['fa_track_obs_median']} (all tracks {res['track_obs_median']})", flush=True)
    for name in q:
        print(f"   {name:26s} {q[name]['value']:.4f} {q[name]['ci']} ({q[name]['num']}/{q[name]['den']})", flush=True)
    print(f"   duplicate frames {res['dup_frames']}/{res['named_frames']} = {res['dup_frame_share']}; "
          f"named error median {res['named_err_m_median']} m; {res['secs']} s", flush=True)


def run_lane(sessions: list[str], tag: str, ptag: str | None, record: bool,
             reality: str = "off") -> int:
    if reality == "paired":
        return run_paired(sessions, tag, ptag, record)
    for sid in sessions:
        tr.refuse(sid)
    per = [lane(sid, tag, ptag, reality) for sid in sessions]
    _, doc = _pool_lane(per, tag)
    _write_doc(doc, sessions, tag, reality)
    if record:
        _record(doc)
    return 0


def _pool_lane(per: list[dict], tag: str) -> tuple[list[dict], dict]:
    """Print each session's result and the pooled one; returns the per-round
    arrays (popped from the results) and the document."""
    for r in per:
        _print(r)
    pooled = None
    if len(per) > 1:
        fa = [r["_per_round"]["fa"] for r in per]
        pooled = {"sessions": [r["session"] for r in per], "false_accepts": int(sum(a.sum() for a in fa)),
                  "false_accepts_ci": _boot_pooled([(a, None) for a in fa]),
                  "fa_by_outcome": {o: int(sum(r["_per_round"]["by"][o].sum() for r in per)) for o in OUTCOMES},
                  "fa_by_outcome_ci": {o: _boot_pooled([(r["_per_round"]["by"][o], None) for r in per])
                                       for o in OUTCOMES},
                  "questions": {}}
        dropped = [sum(r["_per_round"]["by"][o] for o in DROPPED) for r in per]
        pooled["fa_dropped_share"] = round(float(sum(d.sum() for d in dropped)) / max(pooled["false_accepts"], 1), 4)
        pooled["fa_dropped_share_ci"] = _boot_pooled(list(zip(dropped, fa)))
        inr = [r["_per_round"]["in_real"] for r in per]
        pooled["fa_named_in_real_track"] = int(sum(a.sum() for a in inr))
        pooled["fa_named_in_real_track_ci"] = _boot_pooled([(a, None) for a in inr])
        for q in per[0]["questions"]:
            a = [r["_per_round"]["nums"][q][0] for r in per]
            b = [r["_per_round"]["nums"][q][1] for r in per]
            pooled["questions"][q] = {"value": round(float(sum(x.sum() for x in a) / max(sum(x.sum() for x in b), 1)), 4),
                                      "ci": _boot_pooled(list(zip(a, b))),
                                      "num": int(sum(x.sum() for x in a)), "den": int(sum(x.sum() for x in b))}
        pooled["dup_frames"] = sum(r["dup_frames"] for r in per)
        pooled["named_frames"] = sum(r["named_frames"] for r in per)
        pooled["dup_frame_share"] = round(pooled["dup_frames"] / max(pooled["named_frames"], 1), 4)
        print(f"pooled {tag}: true false accepts {pooled['false_accepts']} {pooled['false_accepts_ci']}", flush=True)
        for o in OUTCOMES:
            print(f"   {o:24s} {pooled['fa_by_outcome'][o]:5d} {pooled['fa_by_outcome_ci'][o]}", flush=True)
        print(f"   dropped share {pooled['fa_dropped_share']} {pooled['fa_dropped_share_ci']}; named in a track "
              f"holding T1d-placed icons {pooled['fa_named_in_real_track']} {pooled['fa_named_in_real_track_ci']}",
              flush=True)
        for name, v in pooled["questions"].items():
            print(f"   {name:26s} {v['value']:.4f} {v['ci']} ({v['num']}/{v['den']})", flush=True)
        print(f"   duplicate frames {pooled['dup_frames']}/{pooled['named_frames']} = {pooled['dup_frame_share']}",
              flush=True)
    arrays = [r.pop("_per_round") for r in per]
    doc = {"tag": tag, "version": VERSION, "boot": f"{tr.N_BOOT} round resamples, seed {tr.SEED}",
           "reality": per[0]["reality"] if per else None,
           "sessions": {r["session"]: r for r in per}, "pooled": pooled}
    if pooled:
        pooled["fa_reality_refused_by_reason"] = dict(sum(
            (Counter(r["fa_reality_refused_by_reason"]) for r in per), Counter()))
    return arrays, doc


def _write_doc(doc: dict, sessions: list[str], tag: str, reality: str, kind: str = "lane") -> None:
    # the development set writes lane_TAG[_reality].json; any other set names its sessions
    name = (f"{kind}_{tag}{ARMS.get(reality, '_' + reality)}" if sorted(sessions) == sorted(DEV) else
            f"{kind}_{tag}{ARMS.get(reality, '_' + reality)}_{'_'.join(sessions)}")
    (OUT / f"{name}.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")


def run_paired(sessions: list[str], tag: str, ptag: str | None, record: bool) -> int:
    """Both arms, and per question the paired difference on minus off with a
    round bootstrap that resamples the same rounds for both arms."""
    for sid in sessions:
        tr.refuse(sid)
    arms = {}
    for arm in ("off", "on"):
        per = [lane(sid, tag, ptag, arm) for sid in sessions]
        arrays, doc = _pool_lane(per, tag)
        _write_doc(doc, sessions, tag, arm)
        arms[arm] = (arrays, doc)
    (a_off, d_off), (a_on, d_on) = arms["off"], arms["on"]
    for x, y in zip(a_off, a_on):
        if x["rounds"] != y["rounds"]:
            raise SystemExit("the arms resample different rounds; a paired bootstrap needs one set")
    diff = {"sessions": {}, "pooled": {}}
    questions = list(d_on["sessions"][sessions[0]]["questions"])
    for q in questions:
        for i, sid in enumerate(sessions):
            a1, b1 = a_on[i]["nums"][q]
            a2, b2 = a_off[i]["nums"][q]
            v = d_on["sessions"][sid]["questions"][q]["value"] - d_off["sessions"][sid]["questions"][q]["value"]
            diff["sessions"].setdefault(sid, {})[q] = {"diff": round(v, 4),
                                                       "ci": _boot_pooled_diff([(a1, b1, a2, b2)])}
        if len(sessions) > 1:
            v = d_on["pooled"]["questions"][q]["value"] - d_off["pooled"]["questions"][q]["value"]
            diff["pooled"][q] = {"diff": round(v, 4), "ci": _boot_pooled_diff(
                [(a_on[i]["nums"][q][0], a_on[i]["nums"][q][1], a_off[i]["nums"][q][0], a_off[i]["nums"][q][1])
                 for i in range(len(sessions))])}
    print("paired on - off (same resampled rounds):", flush=True)
    for scope, block in [(sid, diff["sessions"][sid]) for sid in sessions] + [("pooled", diff["pooled"])]:
        for q, v in block.items():
            print(f"   {scope:13s} {q:26s} {v['diff']:+.4f} {v['ci']}", flush=True)
    doc = {"tag": tag, "version": VERSION, "boot": f"{tr.N_BOOT} round resamples, seed {tr.SEED}, paired",
           "sessions": sessions, "diff": diff,
           "fa_by_outcome": {"off": (d_off["pooled"] or d_off["sessions"][sessions[0]])["fa_by_outcome"],
                             "on": (d_on["pooled"] or d_on["sessions"][sessions[0]])["fa_by_outcome"]}}
    _write_doc(doc, sessions, tag, "paired", kind="paired")
    if record:
        _record(d_off)
        _record(d_on, arm="reality")
        _record_paired(doc)
    return 0


def _metric_values(r: dict) -> tuple[dict, dict]:
    vals, ci = {"false_accepts": r["false_accepts"], "fa_dropped_share": r["fa_dropped_share"],
                "dup_frame_share": r["dup_frame_share"],
                "fa_named_in_real_track": r["fa_named_in_real_track"]}, {}
    ci["false_accepts"] = r["false_accepts_ci"]
    ci["fa_named_in_real_track"] = r["fa_named_in_real_track_ci"]
    ci["fa_dropped_share"] = r["fa_dropped_share_ci"]
    for o in OUTCOMES:
        vals[f"fa_{o}"] = r["fa_by_outcome"][o]
        ci[f"fa_{o}"] = r["fa_by_outcome_ci"][o]
    for q, v in r["questions"].items():
        vals[q] = v["value"]
        ci[q] = v["ci"]
    return vals, ci


def _record_paired(doc: dict) -> None:
    from reticle.metrics import record as rec
    vals = {f"{q}_diff": v["diff"] for q, v in doc["diff"]["pooled"].items()}
    ci = {f"{q}_diff": v["ci"] for q, v in doc["diff"]["pooled"].items()}
    rec("question_acceptance", part=f"lane/{doc['tag']}/reality-paired", session="dev3", values=vals, ci=ci,
        deps={"version": VERSION, "rule": "T1d"},
        context={"task": "detection-reality-20261007", "boot": doc["boot"], "sessions": doc["sessions"]},
        note="detection_reality on minus off, per question, pooled over the development matches; "
             "one set of resampled rounds scores both arms")


def _record(doc: dict, arm: str | None = None) -> None:
    from reticle.metrics import record as rec
    tag = doc["tag"] + (f"/{arm}" if arm else "")
    for sid, r in doc["sessions"].items():
        vals, ci = _metric_values(r)
        ctl = []
        if r.get("reader_score_file"):
            ctl.append({"name": "reader false accepts reproduce teardrop_refusals score",
                        "observed": r["false_accepts"], "expected": r["reader_score_file"]["false_accepts"],
                        "tol": 0})
        rec("question_acceptance", part=f"lane/{tag}", session=sid, values=vals, ci=ci, controls=ctl,
            deps={"version": VERSION, "rule": "T1d", "enemy_track_version": r["enemy_track_version"],
                  "minimap_object_version": r["minimap_object_version"], "lineup_version": r["lineup_version"],
                  "death_adjudication_version": r["death_adjudication_version"], "pings_from": r["pings_from"]},
            context={"task": TASK, "boot": doc["boot"], "rounds": r["rounds"], "tracks": r["tracks"],
                     "drops": r["drops"]},
            note="enemy_tracks.build over the tag's minimap_object rows; true false accepts (T1d extras "
                 "ping+x_mark+other) by the lane outcome of the track each joined; questions: reader hit "
                 "rate and icon precision beside named-slot presence/position recall and precision")
    if doc["pooled"]:
        vals, ci = _metric_values(doc["pooled"])
        rec("question_acceptance", part=f"lane/{tag}", session="dev3", values=vals, ci=ci,
            deps={"version": VERSION, "rule": "T1d"}, context={"task": TASK, "boot": doc["boot"],
                                                               "sessions": doc["pooled"]["sessions"]},
            note="pooled over the development matches; rounds resampled within each match")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lane", help="the enemy lane's emitted tracks against T1d")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", default="b1",
                   help="the teardrop_refusals ping reread classing the extras (the tag's score used b1)")
    p.add_argument("--reality", choices=("off", "on", "paired"), default="off",
                   help="the detection_reality arm: off (no glyph verdicts), on, or both paired")
    p.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    tr._idle()
    return run_lane(a.sessions or list(DEV), a.tag, a.pings, a.record, a.reality)


if __name__ == "__main__":
    raise SystemExit(main())
