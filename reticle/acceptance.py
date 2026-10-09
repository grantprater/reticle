r"""The acceptance harness core: emitted finds scored against every replay entity.

[owns:replay-truth-under] Which replay entity lies under a vision find. This
module is the core of the one acceptance harness (docs/QUESTION_ACCEPTANCE.md,
build step B7), promoted from `prototypes/question_acceptance.py` on
2026-10-09 (task `harness-promote-20261009`). Replay data is evaluation truth
only: it scores a find and never feeds a reader, a gate, a threshold, a prior
or an adjudicator. The `evaluation` layer of `architecture.toml` sits above
every pipeline layer, so no reader, tracker, lane or consumer may import it;
only the command surface calls it.

Every function here is pure over the arrays it is handed. The caller loads:

* T0, the replay layer's ten players and their ability children
  (`reticle.episodes.from_replay_layer`, its `children` a `ChildTable`);
* the truth grid `M` over T0: sample times `G` (replay ms), `G_round`, the
  players' world cm `X`, `Y` (subject by sample), subjects `sid`, the enemy
  and ally rows `ei`, `ci`, the player `me`, `agent` by subject, the store's
  `rounds` (`round`, `t_next`), `cap`, `tl0` (T0) and `to_rep(t_cap, lag)`;
* the join `J` (`alive`, `drawn` per subject and sample, the find samples
  `ks`, icons `ic`) and the lane's emitted rows `E`.

The grid, the T1d draw rule and the commands live beside this module in
`reticle/harness/` (task `harness-t1d-20261009`): `harness.draw.RealDrawMatch
(rule="T1d")` builds the grid, `harness.sets.build_sets` the join, and
`harness.commands` runs every subcommand of `reticle acceptance` in process;
`prototypes/question_acceptance.py` is a thin wrapper over them.

The join (`join_entities`): players at the find's grid sample (alive only);
every joinable `child:` entity of T0 within `WINDOW_MS` of the find's frame
on the replay clock and inside its life (`child_life`); truth marks
(`mark_truth`) while the frame lies in their window; one to one per frame
key by distance within `NEAR_CM` (`assign_per_frame`), round by round; two
entity classes within `AMBIG_CM` make a find `ambiguous`. Outcomes
(`CLASS_OUTCOMES`): `right_entity`, `other_entity:<key>`, `undrawn_truth`,
`nothing_there:<derivation>`, `coverage_gap:<class>:<reason>`, `ambiguous`.
Intervals resample rounds (`N_BOOT`, `SEED`); pooled intervals resample
rounds within each match and add the matches (`boot_pooled`).

Every document the harness writes carries `ACCEPTANCE_VERSION` beside the
command's own stamp.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

ACCEPTANCE_VERSION = "acceptance-0.1.0"

#: A find within NEAR_CM of an entity can be that entity's (world cm).
NEAR_CM = 300.0
#: A living enemy 3 to 8 m from a find on nothing explains it (`enemy_3_8m`).
OFFSET_CM = 800.0
#: Round-bootstrap replicates and seed.
N_BOOT = 4000
SEED = 20261007

#: The lane outcomes of a find, in report order.
OUTCOMES = ("no_track", "reality_refused", "identity_abstained", "agent_not_on_enemy_team",
            "named_duplicate", "named")
#: Outcomes the lane drops (the track is no entity, or carries no enemy-team name).
DROPPED = ("reality_refused", "identity_abstained", "agent_not_on_enemy_team")

#: Time window: the find's frame at t_rep +- WINDOW_MS, keeping the nearest.
#: The remote-render delay lies in a band of [30, 200] ms
#: (`t1_draw_rule.RENDER_BAND_MS`, [domain:capture/minimap-remote-player-lag]):
#: half that width (85 ms) plus one 15 Hz frame (67 ms).
WINDOW_MS = 150.0
WINDOW_STEP_MS = 25.0
#: A child's scoring life is [open, close + LIFE_TAIL_MS] unless its class has
#: a measured onset and tail; the tail is unmeasured for children (each row
#: says `life_window_unmeasured`).
LIFE_TAIL_MS = 600.0
#: Measured (onset, tail) ms by (actor class, owner side): the stored
#: `ability_shape` ring of the player's own Recon Bolt is drawn from a median
#: 315.5 ms after the bolt opens to 108.8 ms before it closes (15 bolts,
#: `prototypes/replay_abilities.py`, 9acf02f98283). Another side's bolt is
#: unmeasured and takes the default; no window is borrowed by analogy.
MEASURED_LIFE = {("GameObject_Hunter_Q_SonarBolt_C", "self"): (315.5, -108.8)}
#: Mapped classes the join leaves out, with the reason the coverage report prints.
NOT_JOINED = {"BombEquippable_C": "the layer holds only the spike item's spawn tick; a carried or "
                                  "dropped spike's place is not decoded, and its spawn would place it falsely"}
#: Two entity classes within AMBIG_CM of one find make it `ambiguous`.
AMBIG_CM = 100.0
#: An enemy "?" lasts 3.0 s and fades over 1.0 s [domain:minimap/last-known-mark-widget-lifetime].
Q_MARK_MS = 4000.0
#: The class-aware outcomes of a find, in report order.
CLASS_OUTCOMES = ("right_entity", "other_entity", "undrawn_truth", "nothing_there", "coverage_gap",
                  "ambiguous")


# ----------------------------------------------------------------- bootstrap

def boot_share(rounds, num, den, n: int = N_BOOT, seed: int = SEED) -> list:
    """95% interval of a share, rounds resampled."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rounds), (n, len(rounds)))
    s = num[idx].sum(1) / np.maximum(den[idx].sum(1), 1)
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def boot_count(rounds, cnt, n: int = N_BOOT, seed: int = SEED) -> list:
    """95% interval of a count, rounds resampled."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rounds), (n, len(rounds)))
    s = cnt[idx].sum(1)
    return [int(np.percentile(s, 2.5)), int(np.percentile(s, 97.5))]


def boot_pooled(per_match: list[tuple[np.ndarray, np.ndarray | None]]) -> list:
    """95% interval of a pooled sum (den None) or share, rounds resampled
    within each match and the matches added."""
    rng = np.random.default_rng(SEED)
    num = np.zeros(N_BOOT)
    den = np.zeros(N_BOOT)
    for a, b in per_match:
        idx = rng.integers(0, len(a), (N_BOOT, len(a)))
        num += a[idx].sum(1)
        if b is not None:
            den += b[idx].sum(1)
    if per_match and per_match[0][1] is None:
        return [int(np.percentile(num, 2.5)), int(np.percentile(num, 97.5))]
    s = num / np.maximum(den, 1)
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def boot_pooled_diff(per_match: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]) -> list:
    """95% interval of a paired difference of pooled shares, arm A minus arm
    B: each replicate resamples a match's rounds once and scores both arms on
    them. Each item is (num A, den A, num B, den B) per round of one match."""
    rng = np.random.default_rng(SEED)
    na, da, nb, db = (np.zeros(N_BOOT) for _ in range(4))
    for a1, b1, a2, b2 in per_match:
        idx = rng.integers(0, len(a1), (N_BOOT, len(a1)))
        na += a1[idx].sum(1)
        da += b1[idx].sum(1)
        nb += a2[idx].sum(1)
        db += b2[idx].sum(1)
    d = na / np.maximum(da, 1) - nb / np.maximum(db, 1)
    return [round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)]


def round_index(ri: dict, rounds_of, missing: int = -1) -> np.ndarray:
    """`ri[r]` for each round number in `rounds_of`, `missing` where absent."""
    r = np.asarray(rounds_of, np.int64)
    if not ri or not r.size:
        return np.full(r.size, missing, np.int64)
    keys = np.array(sorted(ri), np.int64)
    vals = np.array([ri[k] for k in keys], np.int64)
    i = np.clip(np.searchsorted(keys, r), 0, keys.size - 1)
    return np.where(keys[i] == r, vals[i], missing)


# ----------------------------------------------------------------- the lane (pure parts)

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


def median_or_none(v):
    v = [x for x in v if x is not None]
    return None if not v else float(np.median(v))


def dist_summary(v) -> dict:
    """n, median, p90 and max of distances in metres (None left out)."""
    v = np.asarray([x for x in v if x is not None], float)
    if not v.size:
        return {"n": 0}
    return {"n": int(v.size), "median_m": round(float(np.median(v)), 3),
            "p90_m": round(float(np.percentile(v, 90)), 3), "max_m": round(float(v.max()), 3)}


def score_lane(sid: str, M, R: dict, J: dict, E: dict, ext: list, summary: dict, why_refused: dict, *,
               tag: str, version: str, ptag, reality: str, true_fa) -> tuple[dict, list, dict, np.ndarray]:
    """The enemy lane of one session against T1d: (a) the reader's true false
    accepts (extras of a `true_fa` class) by lane outcome and (b) per
    question the emitted tracks' recall and precision beside the reader's.
    Returns the result document, the false-accept rows, the per-round arrays
    and each icon's lane outcome."""
    pairs = R["pairs"]
    rounds = sorted({r["round"] for r in pairs} | {r["round"] for r in R["extras"]})
    ri = {rn: i for i, rn in enumerate(rounds)}
    nr = len(rounds)

    # (a) the reader's true false accepts by lane outcome
    out_icon = icon_outcomes(E["icon_p"], E["icon_eid"], E["icon_subj"], E["track_outcome"])
    fa = [e for e in ext if e["cls"] in true_fa]
    fa_r = round_index(ri, [e["round"] for e in fa])
    fa_o = np.array([str(out_icon[e["icon"]]) for e in fa], dtype=object)
    by = {o: np.bincount(fa_r[fa_o == o], minlength=nr).astype(float) if fa else np.zeros(nr)
          for o in OUTCOMES}
    fa_rows = []
    for e, o in zip(fa, fa_o):
        eid = E["icon_eid"][e["icon"]]
        fa_rows.append({**{k: e[k] for k in ("round", "k", "frame_idx", "t_cap", "icon_px", "cls", "icon",
                                             "nearest_enemy_m")},
                        "outcome": str(o), "track": eid, "agent": E["track_agent"].get(eid),
                        "track_observations": E["track_obs"].get(eid),
                        "reality_reason": why_refused.get(eid)})
    fa_n = np.bincount(fa_r, minlength=nr).astype(float) if fa else np.zeros(nr)
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
    in_real_m = np.array([r["outcome"].startswith("named") and bool(r["track_real_icons"]) for r in fa_rows],
                         bool)
    in_real = np.bincount(fa_r[in_real_m], minlength=nr).astype(float) if fa else np.zeros(nr)

    # (b) questions
    S = M.X.shape[0]
    pk = np.array([r["k"] for r in pairs], np.int64)
    pj = np.array([r["j"] for r in pairs], np.int64)
    Q = lane_questions(J["ks"], J["ic"], pk, pj, E["icon_p"], E["icon_subj"], E["icon_x"], E["icon_y"],
                       M.X, M.Y, J["drawn"], J["alive"], J["p_of"])
    pr = round_index(ri, [r["round"] for r in pairs])
    hit = np.array([r["set"] == "hit" for r in pairs], bool)
    ir = round_index(ri, np.asarray(M.G_round)[np.asarray(J["ks"], np.int64)])
    if (ir < 0).any():
        raise SystemExit(f"{sid}: an accepted icon's round has no pair or extra")
    ext_icon = np.bincount(round_index(ri, [e["round"] for e in R["extras"]]),
                           minlength=nr).astype(float) if R["extras"] else np.zeros(nr)

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
    res = {"session": sid, "tag": tag, "version": version, "acceptance_version": ACCEPTANCE_VERSION,
           "rule": "T1d", "pings_from": ptag or "store",
           "reality": reality, "detection_reality": summary.get("detection_reality"),
           "detection_reality_version": summary.get("detection_reality_version"),
           "fa_reality_refused_by_reason": dict(refused_by),
           "rounds": nr, "tracks": summary["tracks"], "track_identity": summary["identity"],
           "enemy_track_version": summary["enemy_track_version"],
           "minimap_object_version": summary["minimap_object_version"],
           "lineup_version": summary["lineup_version"],
           "death_adjudication_version": summary["death_adjudication_version"],
           "drops": E["drops"],
           "false_accepts": int(fa_n.sum()), "false_accepts_ci": boot_count(rounds, fa_n),
           "fa_by_outcome": {o: int(v.sum()) for o, v in by.items()},
           "fa_by_outcome_ci": {o: boot_count(rounds, v) for o, v in by.items()},
           "fa_dropped_share": round(float(sum(by[o].sum() for o in DROPPED)) / max(fa_n.sum(), 1), 4),
           "fa_dropped_share_ci": boot_share(rounds, sum(by[o] for o in DROPPED), fa_n),
           "fa_named_in_real_track": int(in_real.sum()),
           "fa_named_in_real_track_ci": boot_count(rounds, in_real),
           "fa_track_obs_median": median_or_none([r["track_observations"] for r in fa_rows]),
           "track_obs_median": median_or_none(list(E["track_obs"].values())),
           "questions": {}, "pairs": int(pk.size), "icons_valid": int(J["ks"].size),
           "named_frames": int(fr_named.size), "dup_frames": int(fr_dup.size),
           "dup_frame_share": round(fr_dup.size / max(fr_named.size, 1), 4),
           "named_err_m_median": None if not err.size else round(float(np.nanmedian(err)) / 100, 3)}
    for q, (a, b) in nums.items():
        res["questions"][q] = {"value": round(float(a.sum() / max(b.sum(), 1)), 4),
                               "ci": boot_share(rounds, a, b), "num": int(a.sum()), "den": int(b.sum())}
    per_round_arrays = {"fa": fa_n, "by": by, "nums": nums, "in_real": in_real, "rounds": rounds,
                        "ri": ri, "nr": nr}
    return res, fa_rows, per_round_arrays, out_icon


# ----------------------------------------------------------------- truth under a find (pure parts)

def entity_key(family: str, agent, ability) -> str:
    """The class key of a truth entity: `family:agent:ability`, `-` for a
    missing part. Ambiguity and recall count by this key."""
    return f"{family}:{agent or '-'}:{ability or '-'}"


def child_family(mapped, agent, side_rel) -> str:
    """`ability_enemy`, `ability_ally`, `spike`, `ult_orb`, or `unmapped`."""
    if mapped is None:
        return "unmapped"
    m = str(mapped)
    if m == "ult orb":
        return "ult_orb"
    if "spike" in m:
        return "spike"
    return f"ability_{side_rel}" if side_rel in ("ally", "enemy") else "ability_unknown_side"


def short_reason(reason) -> str:
    """An unmapped reason without its lists (`instigator chain ends at [...]`)."""
    if reason is None:
        return "-"
    s = str(reason).split("[")[0].strip(" ,;:")
    return s.replace(" at", "").replace(":", "").strip() or "-"


def child_life(cls, side_rel, t_open, t_close, round_end, measured: dict, tail_ms: float = None):
    """Each child's scoring life [lo, hi] in replay ms and its flag.

    A class with a measured onset and tail (`measured[(class, side_rel)]`)
    takes them; every other class is [open, close + tail_ms], flagged
    `life_window_unmeasured`. A child the layer never closed is held to the
    end of its round (`close_unseen`)."""
    tail_ms = LIFE_TAIL_MS if tail_ms is None else tail_ms
    t_open = np.asarray(t_open, float)
    t_close = np.asarray(t_close, float)
    round_end = np.asarray(round_end, float)
    close = np.where(np.isfinite(t_close), t_close, round_end)
    lo = t_open.copy()
    hi = close + tail_ms
    unseen = ~np.isfinite(t_close)
    flag = np.where(unseen, "life_window_unmeasured,close_unseen", "life_window_unmeasured").astype(object)
    if measured and t_open.size:
        cs = np.array([str(c) for c in cls], dtype=object)
        ss = np.array([str(s) for s in side_rel], dtype=object)
        for (c, s), m in measured.items():
            sel = (cs == c) & (ss == s)
            if sel.any():
                lo[sel] = t_open[sel] + m[0]
                hi[sel] = close[sel] + m[1]
                flag[sel] = np.where(unseen[sel], "measured,close_unseen", "measured")
    return lo, hi, flag


def child_window_dist(position, c, t, fx, fy, lo, hi, window_ms: float = None, step_ms: float = None):
    """Per (child `c[i]`, find time `t[i]`, find xy): the nearest the child
    comes to the find within t +- window_ms while inside its life [lo, hi]
    (the find's own child: `lo[c[i]]`). `position(c, t)` gives the child's
    world xy. Returns (distance cm, the offset ms it was taken at); NaN where
    the child is never live in the window."""
    window_ms = WINDOW_MS if window_ms is None else window_ms
    step_ms = WINDOW_STEP_MS if step_ms is None else step_ms
    c = np.asarray(c, np.int64)
    t = np.asarray(t, float)
    off = np.arange(-window_ms, window_ms + 1e-9, step_ms)
    n = c.size
    if n == 0:
        return np.zeros(0), np.zeros(0)
    T = t[:, None] + off[None, :]
    live = (T >= np.asarray(lo)[c][:, None]) & (T <= np.asarray(hi)[c][:, None])
    cc = np.repeat(c, off.size)
    x, y = position(cc, T.ravel())
    d = np.hypot(x.reshape(n, -1) - np.asarray(fx)[:, None], y.reshape(n, -1) - np.asarray(fy)[:, None])
    d = np.where(live & np.isfinite(d), d, np.inf)
    j = np.argmin(d, axis=1)
    best = d[np.arange(n), j]
    return np.where(np.isfinite(best), best, np.nan), np.where(np.isfinite(best), off[j], np.nan)


def assign_per_frame(frame_ids, D, gate):
    """One-to-one obs->truth assignment within each frame, nearest first.

    `D` is (n_obs, n_truth) distances (NaN where the truth is absent), at
    most 64 truth columns per frame id. Two vectorised rounds: every
    observation takes its nearest truth; where two in one frame take the
    same truth the nearer keeps it, and the loser takes its nearest truth
    still free in that frame. The losers resolve in order, each taking from
    what the one before left (sequential by definition; they are few).
    Returns (truth index or -1, dist). Moved from `replay_truth._assign`."""
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


def assign_one_to_one(frame, D, gate: float):
    """`assign_per_frame` over any number of truth columns: it keys a
    frame's column as `frame * 64 + column`, so the frame ids are spread by
    the column count."""
    frame = np.asarray(frame, np.int64)
    if D.shape[0] == 0:
        return np.zeros(0, np.int64), np.zeros(0)
    spread = int(np.ceil(max(D.shape[1], 1) / 64.0))
    j, d = assign_per_frame(frame * spread, D, gate)
    return np.asarray(j, np.int64), np.asarray(d, float)


def ambiguous_classes(D, keys, within_cm: float = None) -> list:
    """Per find (row of D), the distinct class keys of the columns within
    `within_cm`, sorted; a find whose list holds two or more is `ambiguous`."""
    within_cm = AMBIG_CM if within_cm is None else within_cm
    D = np.asarray(D, float)
    n = D.shape[0]
    keys = np.asarray(keys, dtype=object)
    if not n or not keys.size:
        return [[] for _ in range(n)]
    near = np.where(np.isfinite(D), D <= within_cm, False)
    uk, inv = np.unique(keys.astype(str), return_inverse=True)
    hot = np.zeros((n, uk.size), bool)
    r, c = np.nonzero(near)
    hot[r, inv[c]] = True
    rr, cc = np.nonzero(hot)
    cnt = np.bincount(rr, minlength=n)
    parts = np.split(uk[cc], np.cumsum(cnt)[:-1])
    return [p.tolist() for p in parts]


def outcome_of(kind: str, *, ambiguous: bool, assigned: bool, side_rel=None, drawn=None,
               subj_named=None, subj_truth=None, key=None, cls=None, unmapped_reason=None,
               derivation=None) -> tuple[str, str]:
    """A find's class-aware outcome (`CLASS_OUTCOMES`) and its full label.

    `kind`: `player` or `child` for an assigned find, else None. A find on a
    drawn living enemy is `right_entity` (`name_right` when its track names
    him, `name_wrong` when it names another, `unnamed` when none); on an
    undrawn living enemy, `undrawn_truth`; on any other live entity,
    `other_entity:<key>`, or `coverage_gap:<class>:<reason>` for an
    unmapped actor; on none, `nothing_there:<derivation>`."""
    if ambiguous:
        return "ambiguous", "ambiguous"
    if not assigned:
        return "nothing_there", f"nothing_there:{derivation or 'none'}"
    if kind == "player" and side_rel == "enemy":
        if not drawn:
            return "undrawn_truth", "undrawn_truth"
        if subj_named is None or subj_named < 0:
            return "right_entity", "right_entity:unnamed"
        return "right_entity", ("right_entity:name_right" if subj_named == subj_truth
                                else "right_entity:name_wrong")
    if kind == "child" and key is not None and key.startswith("unmapped:"):
        return "coverage_gap", f"coverage_gap:{cls}:{short_reason(unmapped_reason)}"
    return "other_entity", f"other_entity:{key}"


def nothing_derivation(fx, fy, ft, kills, swaps, ping, near_3_8m, held=None,
                       near_cm: float = None, near_name: str = "enemy_3_8m") -> np.ndarray:
    """For finds on no live entity, the first derivation that explains them:
    `held_by_nearer_find` (an entity lies within `near_cm`, but the
    one-to-one join gave it to a nearer find of the same sample: a duplicate),
    `kill_x` (a death earlier in the round within `near_cm` of the victim's
    place: the X [domain:minimap/death-mark-persistence]), `question_swap`
    (within `near_cm` of a T1d swap's place while the "?" lasts
    [domain:minimap/last-known-mark-widget-lifetime]), `ping` (the extras'
    ping class), `enemy_3_8m` (a living enemy 3-8 m away), else `none`.

    `kills` and `swaps`: arrays (n, 4) of (t_from, t_to, x, y) in the find's
    clock and world cm; `ping`, `near_3_8m`: booleans per find."""
    near_cm = NEAR_CM if near_cm is None else near_cm
    fx, fy, ft = (np.asarray(a, float) for a in (fx, fy, ft))
    out = np.array(["none"] * fx.size, dtype=object)

    def hit(ev):
        ev = np.asarray(ev, float).reshape(-1, 4)
        if ev.size == 0 or fx.size == 0:
            return np.zeros(fx.size, bool)
        on = (ft[:, None] >= ev[None, :, 0]) & (ft[:, None] <= ev[None, :, 1])
        d = np.hypot(fx[:, None] - ev[None, :, 2], fy[:, None] - ev[None, :, 3])
        return (on & (d <= near_cm)).any(axis=1)

    held = np.zeros(fx.size, bool) if held is None else np.asarray(held, bool)
    for name, m in ((near_name, np.asarray(near_3_8m, bool)), ("ping", np.asarray(ping, bool)),
                    ("question_swap", hit(swaps)), ("kill_x", hit(kills)), ("held_by_nearer_find", held)):
        out[m] = name                       # later assignments take precedence
    return out


def claim_outcome(desc, *, ambiguous: bool, claimed: bool, drawn=None, name_claim=None,
                  name_truth=None, derivation=None) -> tuple[str, str]:
    """A find's class-aware outcome (`CLASS_OUTCOMES`) where the find claims
    an entity kind and, perhaps, a name.

    `desc`: the entity the join assigned (None: none); `claimed`: it is of
    the kind the find claims (a teammate, a smoke, an ability child, a death
    X of the claimed side, a "?"). On the claimed kind the find is
    `right_entity` (`name_right` or `name_wrong` by the claimed name against
    the truth's, `unnamed` when the find claims none), or `undrawn_truth`
    where the draw rule says the entity is not drawn (`drawn` False). Any
    other entity is `other_entity:<key>`, or `coverage_gap:<class>:<reason>`
    for an unmapped actor; none is `nothing_there:<derivation>`."""
    if ambiguous:
        return "ambiguous", "ambiguous"
    if desc is None:
        return "nothing_there", f"nothing_there:{derivation or 'none'}"
    if claimed:
        if drawn is False:
            return "undrawn_truth", "undrawn_truth"
        if name_claim is None:
            return "right_entity", "right_entity:unnamed"
        return "right_entity", ("right_entity:name_right" if name_claim == name_truth
                                else "right_entity:name_wrong")
    if desc["kind"] == "child" and str(desc["key"]).startswith("unmapped:"):
        return "coverage_gap", f"coverage_gap:{desc['entity_class']}:{short_reason(desc.get('unmapped_reason'))}"
    return "other_entity", f"other_entity:{desc['key']}"


def drawn_by_fact(facts: dict, agent, ability, side_rel) -> tuple[str, list]:
    """Whether `domain/abilities.toml` says this ability draws on the
    player's minimap from its owner's side (`self`, `ally` or `enemy`):
    `yes`, `no` or `unknown`, with the facts read. The facts are matched by
    subject and fact id alone:

    * `enemy`: a `*-enemy-minimap-*` fact says yes;
    * `self` (the player's own): a `*-minimap-*` fact without `enemy` says
      yes, `*-no-minimap-*` or `*-minimap-none` says no (the demo census
      read the caster's own minimap);
    * `ally` (a teammate's): only a `*-minimap-everyone` fact says yes; the
      caster's-own-minimap facts are not borrowed.

    Nothing is inferred from another ability or another side
    [domain:abilities/ability-rules-are-unique]."""
    if not agent or not ability:
        return "unknown", []

    def norm(s):
        return "".join(ch for ch in str(s).lower() if ch.isalnum())

    want = norm(agent) + ":" + norm(ability)
    mine = [f for f in facts.values() if f.domain == "abilities" and ":" in (f.subject or "")
            and norm(f.subject.split(":", 1)[0]) + ":" + norm(f.subject.split(":", 1)[1]) == want
            and "minimap" in f.id]
    no_ids = [f.key for f in mine if "no-minimap" in f.id or f.id.endswith("minimap-none")]
    if side_rel == "enemy":
        yes = [f.key for f in mine if "enemy-minimap" in f.id and f.key not in no_ids]
        return ("yes", yes) if yes else ("unknown", [])
    if side_rel == "self":
        if no_ids:
            return "no", no_ids
        yes = [f.key for f in mine if "enemy" not in f.id]
        return ("yes", yes) if yes else ("unknown", [])
    yes = [f.key for f in mine if f.id.endswith("minimap-everyone")]
    return ("yes", yes) if yes else ("unknown", [])


# ----------------------------------------------------------------- the join

def player_desc(M, j: int) -> dict:
    """The truth description of player row `j` of the grid."""
    side = "enemy" if j in set(M.ei.tolist()) else "ally"
    ag = M.agent.get(M.sid[j])
    return {"entity_id": f"player:{M.sid[j]}", "kind": "player", "entity_class": "player",
            "family": f"player_{side}", "agent": ag, "ability": None, "tray_key": None,
            "owner": M.sid[j], "side_rel": side, "key": entity_key(f"player_{side}", ag, None),
            "amb_key": f"player_{side}"}


def child_desc(ct, c: int, me: str) -> dict:
    """The truth description of child `c` of T0's `ChildTable`."""
    C = ct.cols
    fam = child_family(C["mapped"][c], C["agent"][c], C["side_rel"][c])
    ab = C["ability"][c] if C["ability"][c] is not None else C["mapped"][c]
    # the spike and the ult orbs are one class whoever holds or owns them
    key = (f"unmapped:{C['cls'][c]}" if fam == "unmapped" else
           entity_key(fam, None if fam in ("spike", "ult_orb") else C["agent"][c], ab))
    side = C["side_rel"][c]
    return {"entity_id": C["entity_id"][c], "kind": "child", "entity_class": C["cls"][c], "family": fam,
            "agent": C["agent"][c], "ability": ab, "tray_key": C["tray_key"][c], "owner": C["subject"][c],
            "side_rel": side, "fact_side": "self" if C["subject"][c] is not None and C["subject"][c] == me
            else side, "key": key, "amb_key": key, "unmapped_reason": C["unmapped_reason"][c]}


def _round_end_of(M, rounds_of, offset: int = 0, missing=np.inf) -> np.ndarray:
    """The end (`t_next`) of each round number in `rounds_of` + offset."""
    end_of = {r["round"]: r["t_next"] for r in M.rounds}
    return np.array([end_of.get(int(r) + offset, missing) for r in rounds_of], float)


def death_and_swap_marks(M, J) -> tuple[np.ndarray, np.ndarray]:
    """Truth derivations on the grid's clock: each death's X (t_from, t_to,
    x, y: from the last living sample to the round's end, at the victim's
    last living place) and each T1d swap's "?" (from the first undrawn
    sample of a living enemy, for `Q_MARK_MS` or until he is drawn again, at
    his last drawn place)."""
    A = np.asarray(J["alive"], bool)
    D = np.asarray(J["drawn"], bool)
    G, Rn = M.G, M.G_round
    same = np.r_[False, Rn[1:] == Rn[:-1]]
    r_end = _round_end_of(M, Rn)
    j, k = np.nonzero(A[:, :-1] & ~A[:, 1:] & same[None, 1:])
    k = k + 1
    kills = np.stack([G[k - 1], r_end[k], M.X[j, k - 1], M.Y[j, k - 1]], 1) if k.size else np.zeros((0, 4))
    # "?" marks: drawn at k-1, undrawn and alive at k, same round
    j2, k2 = np.nonzero(D[:, :-1] & ~D[:, 1:] & A[:, 1:] & same[None, 1:])
    k2 = k2 + 1
    if not k2.size:
        return kills, np.zeros((0, 4))
    K = G.size
    nxt = np.where(D, np.arange(K)[None, :], K)
    nxt = np.minimum.accumulate(nxt[:, ::-1], axis=1)[:, ::-1]        # next drawn sample at or after k
    back = nxt[j2, k2]
    t_back = np.where(back < K, G[np.minimum(back, K - 1)], np.inf)
    t_to = np.minimum(np.minimum(G[k2] + Q_MARK_MS, t_back), r_end[k2])
    swaps = np.stack([G[k2], t_to, M.X[j2, k2 - 1], M.Y[j2, k2 - 1]], 1)
    return kills, swaps


def mark_truth(M, J) -> dict:
    """The marks the replay implies, on the grid's clock, as columns for
    `join_entities`: each death's X at the victim's last living place from
    his last living sample to the round's end
    [domain:minimap/death-mark-persistence], an ally's always drawn
    [domain:minimap/ally-death-mark], an enemy's drawn where T1d drew him at
    his last living sample (`t1_draw_rule.DrawRule.dead_mark`,
    [domain:minimap/enemy-death-mark]); and each T1d swap's "?" as
    `death_and_swap_marks` places it. One row per mark (tens per match)."""
    A = np.asarray(J["alive"], bool)
    D = np.asarray(J["drawn"], bool)
    G, Rn = M.G, M.G_round
    same = np.r_[False, Rn[1:] == Rn[:-1]]
    r_end = _round_end_of(M, Rn)
    ei = set(M.ei.tolist())
    K = G.size
    j, k = np.nonzero(A[:, :-1] & ~A[:, 1:] & same[None, 1:])
    k = k + 1
    # the X's last sample: the last of its round
    last_of = {int(r): int(i_) for i_, r in enumerate(Rn)}
    cols = {"t_from": [], "t_to": [], "x": [], "y": [], "round": [], "k_from": [], "k_to": [], "desc": []}

    def add(t_from, t_to, x, y, rnd, k_from, k_to, desc):
        for a, v in (("t_from", t_from), ("t_to", t_to), ("x", x), ("y", y), ("round", rnd), ("k_from", k_from),
                     ("k_to", k_to), ("desc", desc)):
            cols[a].append(v)

    for jj, kk in zip(j.tolist(), k.tolist()):
        side = "enemy" if jj in ei else "ally"
        fam = f"death_x_{side}"
        drawn = bool(D[jj, kk - 1]) if side == "enemy" else True
        ag = M.agent.get(M.sid[jj])
        add(float(G[kk - 1]), float(r_end[kk]), float(M.X[jj, kk - 1]), float(M.Y[jj, kk - 1]), int(Rn[kk]),
            kk - 1, last_of[int(Rn[kk])],
            {"entity_id": f"death_x:{M.sid[jj]}:{kk}", "kind": "mark", "entity_class": "death_x", "family": fam,
             "agent": ag, "ability": None, "tray_key": None, "owner": M.sid[jj], "side_rel": side,
             "key": entity_key(fam, None, None), "amb_key": fam, "drawn": drawn,
             "recall_key": (f"{fam} (always drawn)" if side == "ally" else
                            f"{fam} ({'T1d drawn' if drawn else 'T1d undrawn'} at death)")})
    j2, k2 = np.nonzero(D[:, :-1] & ~D[:, 1:] & A[:, 1:] & same[None, 1:])
    k2 = k2 + 1
    if k2.size:
        nxt = np.where(D, np.arange(K)[None, :], K)
        nxt = np.minimum.accumulate(nxt[:, ::-1], axis=1)[:, ::-1]
        back = nxt[j2, k2]
        t_back = np.where(back < K, G[np.minimum(back, K - 1)], np.inf)
        t_to = np.minimum(np.minimum(G[k2] + Q_MARK_MS, t_back), r_end[k2])
        k_to = np.searchsorted(G, t_to, side="right") - 1
        for jj, kk, tt, kt in zip(j2.tolist(), k2.tolist(), t_to.tolist(), k_to.tolist()):
            ag = M.agent.get(M.sid[jj])
            # a "?" stands for its enemy, who stands at its place when it
            # appears: it shares the enemy players' ambiguity class, and the
            # join's distance decides between the mark and a player
            add(float(G[kk]), float(tt), float(M.X[jj, kk - 1]), float(M.Y[jj, kk - 1]), int(Rn[kk]), kk,
                max(int(kt), kk),
                {"entity_id": f"question:{M.sid[jj]}:{kk}", "kind": "mark", "entity_class": "last_known",
                 "family": "question_enemy", "agent": ag, "ability": None, "tray_key": None, "owner": M.sid[jj],
                 "side_rel": "enemy", "key": entity_key("question_enemy", None, None), "amb_key": "player_enemy",
                 "drawn": True, "recall_key": "question_enemy (T1d swap)"})
    out = {a: np.asarray(v, float if a in ("t_from", "t_to", "x", "y") else np.int64) for a, v in cols.items()
           if a != "desc"}
    out["desc"] = cols["desc"]
    return out


def join_entities(M, alive, ks, t_rep, fx, fy, frame_key=None, marks: dict | None = None) -> dict:
    """The truth join, for any finds: find i at grid sample `ks[i]`, frame
    time `t_rep[i]` on the replay clock, world cm (`fx`, `fy`). Players are
    taken at the sample (alive only); every joinable `child:` entity within
    `WINDOW_MS` of the frame and inside its life; `marks` (`mark_truth`)
    while the frame lies in [t_from - WINDOW_MS, t_to + WINDOW_MS]. One to
    one by distance within `NEAR_CM` per `frame_key` (default: the sample),
    round by round.

    Returns `col_kind` (`player`, `child`, `mark` or None), `col_idx`,
    `dist`, `win_dt`, `amb_keys`, `held`, the child descriptions and lives,
    and `Dp` (find to each player, NaN where dead)."""
    ct = M.tl0.children
    if ct is None:
        raise SystemExit(f"{M.cap}: T0 carries no children (episodes.from_replay_layer)")
    ks = np.asarray(ks, np.int64)
    t_rep = np.asarray(t_rep, float)
    fx = np.asarray(fx, float)
    fy = np.asarray(fy, float)
    fk = ks if frame_key is None else np.asarray(frame_key, np.int64)
    n = ks.size
    S = M.X.shape[0]
    alive = np.asarray(alive, bool)
    Dp = np.hypot(M.X[:, ks].T - fx[:, None], M.Y[:, ks].T - fy[:, None])
    Dp = np.where(alive[:, ks].T & np.isfinite(Dp), Dp, np.nan)
    # children: life, then the pairs whose life meets the find's window
    C = ct.cols
    rnd = np.asarray(C["round"], float)
    r_end = np.full(rnd.size, np.nan)
    fin = np.isfinite(rnd)
    r_end[fin] = _round_end_of(M, rnd[fin].astype(np.int64), offset=1, missing=np.nan)   # 1-based: layer round + 1
    me = M.me
    side_f = np.array([("self" if s is not None and s == me else sr) for s, sr in zip(C["subject"], C["side_rel"])],
                      dtype=object)
    lo, hi, flag = child_life(C["cls"], side_f, C["t_open"], C["t_close"], r_end, MEASURED_LIFE)
    has_pos = (C["n_ticks"] > 0) | np.isfinite(C["spawn_x"])
    joinable = np.isfinite(lo) & np.isfinite(hi) & has_pos & ~np.isin(C["cls"].astype(str), list(NOT_JOINED))
    cj = np.flatnonzero(joinable)
    fpair, cpair = [], []
    for a in range(0, n, 512):
        b = min(n, a + 512)
        m = (lo[cj][None, :] <= t_rep[a:b, None] + WINDOW_MS) & (hi[cj][None, :] >= t_rep[a:b, None] - WINDOW_MS)
        f_, c_ = np.nonzero(m)
        fpair.append(f_ + a)
        cpair.append(cj[c_])
    fpair = np.concatenate(fpair) if fpair else np.zeros(0, np.int64)
    cpair = np.concatenate(cpair) if cpair else np.zeros(0, np.int64)
    dch, dt = child_window_dist(ct.position, cpair, t_rep[fpair], fx[fpair], fy[fpair], lo, hi)
    # one-to-one per frame key, round by round (a round's children and marks only)
    descs_c = {}
    col_kind = np.full(n, None, dtype=object)
    col_idx = np.full(n, -1, np.int64)
    dist = np.full(n, np.nan)
    win_dt = np.full(n, np.nan)
    amb_keys = [[] for _ in range(n)]
    held = np.zeros(n, bool)          # unassigned, yet an entity lies within NEAR_CM: a nearer find holds it
    pkeys = [player_desc(M, j)["amb_key"] for j in range(S)]
    rn = M.G_round[ks]
    for r in np.unique(rn):
        fi = np.flatnonzero(rn == r)                 # sorted
        sel = np.isin(fpair, fi)
        cs = np.unique(cpair[sel])                   # sorted
        mi = np.zeros(0, np.int64) if marks is None else np.flatnonzero(marks["round"] == r)
        W = S + cs.size + mi.size
        Dg = np.full((fi.size, W), np.nan)
        Dg[:, :S] = Dp[fi]
        Tg = np.full((fi.size, W), np.nan)
        if sel.any():
            rr = np.searchsorted(fi, fpair[sel])
            cc = S + np.searchsorted(cs, cpair[sel])
            Dg[rr, cc] = dch[sel]
            Tg[rr, cc] = dt[sel]
        if mi.size:
            on = ((t_rep[fi][:, None] >= marks["t_from"][mi][None, :] - WINDOW_MS)
                  & (t_rep[fi][:, None] <= marks["t_to"][mi][None, :] + WINDOW_MS))
            dm = np.hypot(fx[fi][:, None] - marks["x"][mi][None, :], fy[fi][:, None] - marks["y"][mi][None, :])
            Dg[:, S + cs.size:] = np.where(on & np.isfinite(dm), dm, np.nan)
        for c in cs.tolist():
            if c not in descs_c:
                descs_c[c] = child_desc(ct, c, me)
        keys = pkeys + [descs_c[c]["amb_key"] for c in cs.tolist()] + \
            ([marks["desc"][int(q)]["amb_key"] for q in mi] if mi.size else [])
        jj, dd = assign_one_to_one(fk[fi], Dg, NEAR_CM)
        amb = ambiguous_classes(Dg, keys)
        for i, f in enumerate(fi.tolist()):
            amb_keys[f] = amb[i]
        cand = np.where(np.isfinite(Dg), Dg <= NEAR_CM, False).any(axis=1)
        un = jj < 0
        held[fi[un]] = cand[un]
        got = ~un
        fg, jg = fi[got], jj[got]
        dist[fg] = dd[got]
        is_p = jg < S
        is_c = (jg >= S) & (jg < S + cs.size)
        is_m = jg >= S + cs.size
        col_kind[fg[is_p]] = "player"
        col_idx[fg[is_p]] = jg[is_p]
        col_kind[fg[is_c]] = "child"
        col_idx[fg[is_c]] = cs[jg[is_c] - S]
        win_dt[fg[is_c]] = Tg[np.flatnonzero(got)[is_c], jg[is_c]]
        col_kind[fg[is_m]] = "mark"
        col_idx[fg[is_m]] = mi[jg[is_m] - S - cs.size]
    return {"Dp": Dp, "lo": lo, "hi": hi, "flag": flag, "joinable": joinable, "descs_c": descs_c,
            "col_kind": col_kind, "col_idx": col_idx, "dist": dist, "win_dt": win_dt, "amb_keys": amb_keys,
            "held": held}


def census(ct, joinable, flag, me, facts, fact_cache) -> dict:
    """Per child class key in this match: children, side, scored or not and
    why, the drawn-ness fact, and the life flag."""
    out = {}
    for c in range(ct.n):
        d = child_desc(ct, c, me)
        e = out.setdefault(d["key"], {"family": d["family"], "agent": d["agent"], "ability": d["ability"],
                                      "classes": set(), "children": 0, "joined": 0, "not_joined": Counter(),
                                      "life": set(), "sides": set(), "tray_keys": set()})
        e["classes"].add(str(d["entity_class"]))
        e["tray_keys"].add(str(d["tray_key"]))
        e["sides"].add(str(d["fact_side"]))
        e["children"] += 1
        e["life"].add(str(flag[c]))
        if joinable[c]:
            e["joined"] += 1
        else:
            cls = str(d["entity_class"])
            e["not_joined"][NOT_JOINED.get(cls) or ("no open time" if not np.isfinite(ct.cols["t_open"][c])
                                                    else "no position")] += 1
    for key, e in out.items():
        fk = (e["agent"], e["ability"], sorted(e["sides"])[0])
        if fk not in fact_cache:
            fact_cache[fk] = drawn_by_fact(facts, *fk)
        e["drawn_by_fact"] = fact_cache[fk][0]
        for s in ("classes", "life", "sides", "tray_keys"):
            e[s] = sorted(e[s])
        e["not_joined"] = dict(e["not_joined"])
    for side in ("enemy", "ally"):
        out[f"player_{side}"] = {"family": f"player_{side}", "agent": None, "ability": None,
                                 "classes": ["player"], "children": 0, "joined": 5, "not_joined": {},
                                 "life": ["lives"], "sides": [side], "tray_keys": [], "drawn_by_fact": "n/a"}
    return out


def _fact(fact_cache: dict, facts: dict, fk: tuple):
    if fk not in fact_cache:
        fact_cache[fk] = drawn_by_fact(facts, *fk)
    return fact_cache[fk]


def truth_under_rows(sid: str, M, J: dict, E: dict, ext: list, *, remote_lag_ms: float, ping_of,
                     facts: dict) -> dict:
    """Every find of the enemy lane (accepted icon on a valid sample) with
    the truth entity under it: players through T1d's join at the find's
    sample, every replay child within `WINDOW_MS` of the find's frame on the
    replay clock and inside its life; one to one per sample by distance
    within `NEAR_CM`. One row per find.

    `ping_of(nf, p, t_cap)`: for the finds `nf` on nothing (their frame
    positions `p[nf]`, capture times `t_cap[nf]`), whether each is a ping by
    the extras' own rule; `facts`: `reticle.domain.load()`. The caller adds
    the census's claimers and the instrument control."""
    MO = E["MO"]
    ks = np.asarray(J["ks"], np.int64)
    ic = np.asarray(J["ic"], np.int64)
    n = ks.size
    p = np.asarray(E["icon_p"], np.int64)[ic]
    t_cap = np.asarray(MO["t_ms"], float)[p]
    t_rep = np.asarray(M.to_rep(t_cap, remote_lag_ms), float)
    fx = np.asarray(E["icon_x"], float)[ic]
    fy = np.asarray(E["icon_y"], float)[ic]
    G_ = join_entities(M, J["alive"], ks, t_rep, fx, fy)
    Dp, lo, hi, flag, joinable = G_["Dp"], G_["lo"], G_["hi"], G_["flag"], G_["joinable"]
    descs_c, col_kind, col_idx, dist = G_["descs_c"], G_["col_kind"], G_["col_idx"], G_["dist"]
    win_dt, amb_keys, held = G_["win_dt"], G_["amb_keys"], G_["held"]
    ct, me = M.tl0.children, M.me
    # derivations for finds on nothing
    kills, swaps = death_and_swap_marks(M, J)
    nothing = col_kind == None  # noqa: E711
    foe = np.array(sorted(set(M.ei.tolist())), np.int64)
    d_foe = Dp[:, foe] if foe.size else np.full((n, 0), np.nan)
    near38 = np.where(np.isfinite(d_foe), (d_foe > NEAR_CM) & (d_foe <= OFFSET_CM), False).any(axis=1)
    ping = np.zeros(n, bool)
    nf = np.flatnonzero(nothing)
    if nf.size:
        ping[nf] = np.asarray(ping_of(nf, p, t_cap), bool)
    deriv = np.full(n, None, dtype=object)
    deriv[nothing] = nothing_derivation(fx[nothing], fy[nothing], M.G[ks][nothing], kills, swaps,
                                        ping[nothing], near38[nothing], held[nothing])
    fact_cache = {}
    old_cls = {(int(e["k"]), int(e["icon"])): e["cls"] for e in ext}
    subj = np.asarray(E["icon_subj"], np.int64)[ic]
    drawn = np.asarray(J["drawn"], bool)
    rows = []
    for f in range(n):
        k = int(ks[f])
        if col_kind[f] == "player":
            d = player_desc(M, int(col_idx[f]))
            dr = bool(drawn[col_idx[f], k]) if d["side_rel"] == "enemy" else None
            fact, facts_read, life = "n/a", [], None
        elif col_kind[f] == "child":
            d = descs_c[int(col_idx[f])]
            dr = None
            fact, facts_read = _fact(fact_cache, facts, (d["agent"], d["ability"], d["fact_side"]))
            life = flag[int(col_idx[f])]
        else:
            d, dr, fact, facts_read, life = None, None, None, [], None
        o, label = outcome_of(col_kind[f], ambiguous=len(amb_keys[f]) >= 2, assigned=d is not None,
                              side_rel=d and d["side_rel"], drawn=dr, subj_named=int(subj[f]),
                              subj_truth=int(col_idx[f]) if col_kind[f] == "player" else None,
                              key=d and d["key"], cls=d and d["entity_class"],
                              unmapped_reason=d and d.get("unmapped_reason"), derivation=deriv[f])
        rows.append({"session": sid, "round": int(M.G_round[k]), "k": k, "frame_idx": int(MO["frame_idx"][p[f]]),
                     "t_cap": round(float(t_cap[f]), 1), "t_rep_frame": round(float(t_rep[f]), 1),
                     "t_rep_sample": round(float(M.G[k]), 1), "icon": int(ic[f]),
                     "icon_px": [round(float(MO["enemy_x"][ic[f]]), 1), round(float(MO["enemy_y"][ic[f]]), 1)],
                     "old_class": old_cls.get((k, int(ic[f])), "hit"),
                     "entity_id": d and d["entity_id"], "entity_class": d and d["entity_class"],
                     "family": d and d["family"], "agent": d and d["agent"], "ability": d and d["ability"],
                     "tray_key": d and d["tray_key"], "owner": d and d["owner"], "side_rel": d and d["side_rel"],
                     "dist_m": None if not np.isfinite(dist[f]) else round(float(dist[f]) / 100, 3),
                     "window_dt_ms": None if not np.isfinite(win_dt[f]) else float(win_dt[f]),
                     "life": life, "t1d_drawn": dr, "drawn_by_fact": fact, "drawn_facts": facts_read,
                     "ambiguous_keys": amb_keys[f] if len(amb_keys[f]) >= 2 else [],
                     "derivation": deriv[f], "outcome": o, "label": label})
    cen = census(ct, joinable, flag, me, facts, fact_cache)
    return {"rows": rows, "ks": ks, "ic": ic, "t_rep": t_rep, "col_kind": col_kind, "col_idx": col_idx,
            "lo": lo, "hi": hi, "joinable": joinable, "census": cen, "descs_c": descs_c}


def _child_keys(ct, cs, me: str, key_of=None) -> np.ndarray:
    """The class key of each child in `cs`, one description per distinct child."""
    cs = np.asarray(cs, np.int64)
    if not cs.size:
        return np.zeros(0, dtype=object)
    u, inv = np.unique(cs, return_inverse=True)
    key_of = key_of or (lambda d: d["key"])
    ku = np.array([key_of(child_desc(ct, int(c), me)) for c in u], dtype=object)
    return ku[inv]


def _pair_covered(den_k, den_c, got, width: int) -> np.ndarray:
    """Whether each (sample, column) pair is in `got`, a set of such pairs."""
    den_k = np.asarray(den_k, np.int64)
    den_c = np.asarray(den_c, np.int64)
    if not got or not den_k.size:
        return np.zeros(den_k.size, bool)
    g = np.array(sorted(got), np.int64).reshape(-1, 2)
    return np.isin(den_k * width + den_c, g[:, 0] * width + g[:, 1])


def _children_in_life(G_, VK, tv, cs) -> tuple[np.ndarray, np.ndarray]:
    """(sample, child) pairs: each of the samples `VK` (frame replay times
    `tv`) inside each child of `cs`'s life."""
    o = np.argsort(tv, kind="stable")
    VK, tv = np.asarray(VK, np.int64)[o], np.asarray(tv, float)[o]
    a = np.searchsorted(tv, G_["lo"][cs], side="left")
    b = np.searchsorted(tv, G_["hi"][cs], side="right")
    cnt = np.maximum(b - a, 0)
    rep = np.repeat(np.arange(cs.size), cnt)
    idx = np.arange(rep.size) - np.repeat(np.cumsum(cnt) - cnt, cnt) + np.repeat(a, cnt)
    return VK[idx], cs[rep]


def class_lane(sid: str, M, J: dict, E: dict, R: dict, under: dict, out_icon, ri: dict, nr: int, rounds: list,
               why_refused: dict, *, remote_lag_ms: float, true_fa) -> tuple[dict, dict]:
    """The class-aware lane of one session: each find's outcome
    (`CLASS_OUTCOMES`) and label counted per round, the old classes beside
    them, recall per enemy-side class with its own denominator, distance
    distributions and the coverage report. Adds the lane's naming to
    `under["rows"]` in place; the caller adds `under["instrument"]`."""
    rows = under["rows"]
    n = len(rows)
    for r in rows:
        eid = E["icon_eid"][r["icon"]]
        r["lane_outcome"] = str(out_icon[r["icon"]])
        r["track"] = eid
        r["track_agent"] = E["track_agent"].get(eid) if eid is not None else None
        r["reality_reason"] = why_refused.get(eid)
    rr = round_index(ri, [r["round"] for r in rows])
    top = np.array([r["outcome"] for r in rows], dtype=object)
    lab = np.array([r["label"] for r in rows], dtype=object)

    def per_round(mask):
        return np.bincount(rr[np.asarray(mask, bool)], minlength=nr).astype(float)

    by_out = {o: per_round(top == o) for o in CLASS_OUTCOMES}
    by_lab = {lb: per_round(lab == lb) for lb in sorted(set(lab.tolist()))}
    if sum(v.sum() for v in by_out.values()) != n:
        raise SystemExit(f"{sid}: the class-aware outcomes do not sum to the finds")
    old = np.array([r["old_class"] for r in rows], dtype=object)
    fa = np.isin(old, list(true_fa))
    lane_o = np.array([r["lane_outcome"] for r in rows], dtype=object)
    cross = Counter((o, t) for o, t in zip(old.tolist(), top.tolist()))
    # recall per enemy-side class, each with its own denominator
    rec = {}
    ks, ci = under["ks"], under["col_idx"]
    kind = under["col_kind"]
    ok = ~np.isin(top, ["ambiguous"])
    S = M.X.shape[0]
    sp = ok & (kind == "player")
    pairs = R["pairs"]
    pk = np.array([p_["k"] for p_ in pairs], np.int64)
    pj = np.array([p_["j"] for p_ in pairs], np.int64)
    pr = round_index(ri, [p_["round"] for p_ in pairs])
    hitp = np.isin(pk * S + pj, ks[sp].astype(np.int64) * S + ci[sp])
    rec["player_enemy:drawn (T1d)"] = (np.bincount(pr[hitp], minlength=nr).astype(float),
                                       np.bincount(pr, minlength=nr).astype(float))
    ct = M.tl0.children
    vk = np.flatnonzero(J["valid"])
    MO = E["MO"]
    tv = np.asarray(M.to_rep(np.asarray(MO["t_ms"], float)[J["p_of"][vk]], remote_lag_ms), float)
    joinable = under["joinable"]
    enemy_c = np.flatnonzero(joinable & (ct.cols["side_rel"] == "enemy"))
    den_k, den_c = _children_in_life(under, vk, tv, enemy_c)
    sel = ok & (kind == "child")
    got_c = np.unique(ks[sel].astype(np.int64) * (ct.n + 1) + ci[sel])
    covered = np.isin(den_k.astype(np.int64) * (ct.n + 1) + den_c, got_c)
    den_r = round_index(ri, np.asarray(M.G_round)[den_k])
    keep = den_r >= 0
    keys = _child_keys(ct, den_c, M.me)
    for key in sorted(set(keys.tolist())):
        m = keep & (keys == key)
        rec[key] = (np.bincount(den_r[m & covered], minlength=nr).astype(float),
                    np.bincount(den_r[m], minlength=nr).astype(float))
    fact_of = {r["label"]: r["drawn_by_fact"] for r in rows if r["outcome"] == "other_entity"}
    dists = {o_: dist_summary([r["dist_m"] for r in rows if r["outcome"] == o_])
             for o_ in ("right_entity", "other_entity", "undrawn_truth", "coverage_gap", "ambiguous")}
    dists["other_entity_child_in_life"] = dist_summary([r["dist_m"] for r in rows if r["outcome"] == "other_entity"
                                                        and r["family"] not in ("player_ally",)])
    dists["true_fa_other_entity"] = dist_summary([r["dist_m"] for r, f in zip(rows, fa) if f
                                                  and r["outcome"] == "other_entity"])
    cen = under["census"]
    gap = Counter(r["label"] for r in rows if r["outcome"] == "coverage_gap")
    doc = {"finds": n, "outcomes": {o_: int(v.sum()) for o_, v in by_out.items()},
           "outcomes_ci": {o_: boot_count(rounds, v) for o_, v in by_out.items()},
           "labels": {lb: int(v.sum()) for lb, v in sorted(by_lab.items(), key=lambda kv: -kv[1].sum())},
           "labels_ci": {lb: boot_count(rounds, v) for lb, v in by_lab.items()},
           "drawn_by_fact": fact_of,
           "true_fa": int(fa.sum()),
           "true_fa_labels": dict(Counter(lab[fa].tolist()).most_common()),
           "true_fa_outcomes": dict(Counter(top[fa].tolist()).most_common()),
           "refused_labels": dict(Counter(lab[lane_o == "reality_refused"].tolist()).most_common()),
           "old_x_new": {f"{a_}|{b_}": v for (a_, b_), v in sorted(cross.items())},
           "ambiguous_keys": dict(Counter(" + ".join(r["ambiguous_keys"]) for r in rows
                                          if r["outcome"] == "ambiguous").most_common(15)),
           "recall": {k_: {"value": round(float(a_.sum() / max(b_.sum(), 1)), 4),
                           "ci": boot_share(rounds, a_, b_), "num": int(a_.sum()), "den": int(b_.sum()),
                           "drawn_by_fact": (cen.get(k_) or {}).get("drawn_by_fact")}
                      for k_, (a_, b_) in rec.items()},
           "distances": dists, "instrument": under.get("instrument"),
           "coverage": {"gap_finds_by_class": dict(gap.most_common()),
                        "census": cen,
                        "not_joined": {k_: e["not_joined"] for k_, e in cen.items() if e["not_joined"]}}}
    per = {"out": by_out, "lab": by_lab, "rec": rec}
    return doc, per


def pool_classes(per: list[dict], arrays: list[dict]) -> dict:
    """The class-aware lane pooled over sessions: rounds resampled within
    each match and the matches added."""
    cs = [r["classes"] for r in per]
    pa = [a["classes"] for a in arrays]
    out = {"finds": sum(c["finds"] for c in cs),
           "outcomes": {o: sum(c["outcomes"][o] for c in cs) for o in CLASS_OUTCOMES},
           "outcomes_ci": {o: boot_pooled([(a["out"][o], None) for a in pa]) for o in CLASS_OUTCOMES}}
    labs = sorted({lb for c in cs for lb in c["labels"]})
    z = [np.zeros(len(a["out"][CLASS_OUTCOMES[0]])) for a in pa]
    out["labels"] = dict(sorted({lb: sum(c["labels"].get(lb, 0) for c in cs) for lb in labs}.items(),
                                key=lambda kv: -kv[1]))
    out["labels_ci"] = {lb: boot_pooled([(a["lab"].get(lb, zz), None) for a, zz in zip(pa, z)]) for lb in labs}
    out["drawn_by_fact"] = {k: v for c in cs for k, v in c["drawn_by_fact"].items()}
    out["true_fa"] = sum(c["true_fa"] for c in cs)
    for k in ("true_fa_labels", "true_fa_outcomes", "refused_labels", "ambiguous_keys", "old_x_new"):
        out[k] = dict(sum((Counter(c[k]) for c in cs), Counter()).most_common())
    keys = sorted({k for a in pa for k in a["rec"]})
    out["recall"] = {}
    for k in keys:
        items = [a["rec"].get(k, (zz, zz)) for a, zz in zip(pa, z)]
        num = sum(x[0].sum() for x in items)
        den = sum(x[1].sum() for x in items)
        fact = next((c["recall"][k].get("drawn_by_fact") for c in cs if k in c["recall"]), None)
        out["recall"][k] = {"value": round(float(num / max(den, 1)), 4), "ci": boot_pooled(items),
                            "num": int(num), "den": int(den), "drawn_by_fact": fact}
    dist_keys = cs[0]["distances"].keys()
    out["distances"] = {"note": "per session in sessions[*].classes.distances"}
    out["distances"].update({k: [c["distances"][k] for c in cs] for k in dist_keys})
    cen = {}
    for c in cs:
        for k, e in c["coverage"]["census"].items():
            m = cen.setdefault(k, {"children": 0, "claimed_by": set(), "scored": set(), "drawn_by_fact": set(),
                                   "not_joined": Counter()})
            m["children"] += e["children"]
            m["claimed_by"] |= set(e.get("claimed_by") or [])
            m["scored"].add(e.get("scored"))
            m["drawn_by_fact"].add(e["drawn_by_fact"])
            m["not_joined"].update(e["not_joined"])
    for m in cen.values():
        m["claimed_by"] = sorted(m["claimed_by"])
        m["scored"] = " | ".join(sorted(m["scored"]))
        m["drawn_by_fact"] = "/".join(sorted(m["drawn_by_fact"]))
        m["not_joined"] = dict(m["not_joined"])
    out["coverage"] = {"gap_finds_by_class": dict(sum((Counter(c["coverage"]["gap_finds_by_class"]) for c in cs),
                                                      Counter()).most_common()),
                       "census": cen, "not_joined": {k: m["not_joined"] for k, m in cen.items() if m["not_joined"]}}
    out["instrument"] = {c_["session"]: c_["classes"]["instrument"] for c_ in per}
    return out


# ----------------------------------------------------------------- other owners' finds

def frame_samples(G, t_rep, ok, half_step_ms: float) -> np.ndarray:
    """Per frame, its grid sample: the nearest within `half_step_ms` of its
    replay time, where `ok` (read, live, inside the capture's spans); one
    frame per sample, the nearest. -1 for a frame that joins none."""
    G = np.asarray(G, float)
    t_rep = np.asarray(t_rep, float)
    out = np.full(t_rep.size, -1, np.int64)
    if not t_rep.size or G.size < 2:
        return out
    i = np.clip(np.searchsorted(G, t_rep), 1, G.size - 1)
    k = np.where(np.abs(G[i - 1] - t_rep) <= np.abs(G[i] - t_rep), i - 1, i)
    dt = np.abs(G[k] - t_rep)
    idx = np.flatnonzero(np.asarray(ok, bool) & (dt <= half_step_ms))
    if idx.size:
        o = idx[np.lexsort((dt[idx], k[idx]))]
        first = np.r_[True, k[o][1:] != k[o][:-1]]
        out[o[first]] = k[o[first]]
    return out


def score_finds(sid: str, M, J: dict, F: dict, facts: dict, fact_cache: dict, *, claimed, name_of=None,
                drawn_of=None, marks=None, near_side: str = "enemy", frame_key=None) -> tuple[list, dict]:
    """Every find of `F` against every replay entity (`join_entities`),
    with its outcome (`claim_outcome`). `F`: arrays `k` (grid sample),
    `t_cap`, `t_rep`, `fx`, `fy` (world cm), `px`, `py`, `claim` (the
    claimed name, or None), and `meta` (a dict per find, copied to its row).
    `claimed(desc)`: the entity is of the kind the find claims;
    `name_of(desc)`: its name in the claim's spelling; `drawn_of(desc, k)`:
    whether the draw rule draws it (None: not decided)."""
    ks = np.asarray(F["k"], np.int64)
    n = ks.size
    G_ = join_entities(M, J["alive"], ks, F["t_rep"], F["fx"], F["fy"], frame_key=frame_key, marks=marks)
    kills, swaps = death_and_swap_marks(M, J)
    nothing = G_["col_kind"] == None  # noqa: E711
    if near_side == "enemy":
        side = np.asarray(M.ei, np.int64)
    else:
        side = np.array([j for j in M.ci if M.sid[j] != M.me], np.int64)
    d = G_["Dp"][:, side] if side.size else np.full((n, 0), np.nan)
    near38 = np.where(np.isfinite(d), (d > NEAR_CM) & (d <= OFFSET_CM), False).any(axis=1)
    deriv = np.full(n, None, dtype=object)
    if nothing.any():
        deriv[nothing] = nothing_derivation(np.asarray(F["fx"])[nothing], np.asarray(F["fy"])[nothing],
                                            M.G[ks][nothing], kills, swaps, np.zeros(int(nothing.sum()), bool),
                                            near38[nothing], G_["held"][nothing], near_name=f"{near_side}_3_8m")
    rows = []
    for f in range(n):
        kind, idx = G_["col_kind"][f], int(G_["col_idx"][f])
        fact, facts_read, life = None, [], None
        if kind == "player":
            desc = player_desc(M, idx)
            if M.sid[idx] == M.me:
                desc = {**desc, "family": "player_self", "key": entity_key("player_self", desc["agent"], None)}
            fact = "n/a"
        elif kind == "child":
            desc = G_["descs_c"][idx]
            fact, facts_read = _fact(fact_cache, facts, (desc["agent"], desc["ability"], desc["fact_side"]))
            life = G_["flag"][idx]
        elif kind == "mark":
            desc = marks["desc"][idx]
            fact = "n/a"
        else:
            desc = None
        is_claimed = desc is not None and bool(claimed(desc))
        dr = drawn_of(desc, int(ks[f])) if (is_claimed and drawn_of is not None) else None
        nt = name_of(desc) if (is_claimed and name_of is not None) else None
        amb = G_["amb_keys"][f]
        o, label = claim_outcome(desc, ambiguous=len(amb) >= 2, claimed=is_claimed, drawn=dr,
                                 name_claim=F["claim"][f], name_truth=nt, derivation=deriv[f])
        k = int(ks[f])
        rows.append({"session": sid, "round": int(M.G_round[k]), "k": k,
                     "t_cap": round(float(F["t_cap"][f]), 1), "t_rep_frame": round(float(F["t_rep"][f]), 1),
                     "t_rep_sample": round(float(M.G[k]), 1),
                     "px": [round(float(F["px"][f]), 1), round(float(F["py"][f]), 1)], "claim": F["claim"][f],
                     **(F["meta"][f] if F.get("meta") is not None else {}),
                     "entity_id": desc and desc["entity_id"], "entity_class": desc and desc["entity_class"],
                     "family": desc and desc["family"], "agent": desc and desc["agent"],
                     "ability": desc and desc["ability"], "tray_key": desc and desc["tray_key"],
                     "owner": desc and desc["owner"], "side_rel": desc and desc["side_rel"],
                     "truth_name": nt,
                     "dist_m": None if not np.isfinite(G_["dist"][f]) else round(float(G_["dist"][f]) / 100, 3),
                     "window_dt_ms": None if not np.isfinite(G_["win_dt"][f]) else float(G_["win_dt"][f]),
                     "life": life, "drawn": dr, "drawn_by_fact": fact, "drawn_facts": facts_read,
                     "ambiguous_keys": amb if len(amb) >= 2 else [], "derivation": deriv[f],
                     "outcome": o, "label": label})
    return rows, G_


def assigned(rows, G_, kind: str) -> set:
    """(sample, column) of the finds the join gave an entity of `kind`, ambiguous finds left out."""
    ck = np.asarray(G_["col_kind"], dtype=object)
    amb = np.array([r["outcome"] == "ambiguous" for r in rows], bool)
    sel = np.flatnonzero((ck == kind) & ~amb) if len(rows) else np.zeros(0, np.int64)
    return {(rows[i]["k"], int(G_["col_idx"][i])) for i in sel.tolist()}


def recall_players(M, J, VK, js, got: set, ri: dict, nr: int) -> tuple[np.ndarray, np.ndarray]:
    """Recall over (sample, player) pairs: samples `VK`, players `js` alive there."""
    VK = np.asarray(VK, np.int64)
    num, den = np.zeros(nr), np.zeros(nr)
    alive = np.asarray(J["alive"], bool)
    S = alive.shape[0]
    for j in js:
        kk = VK[alive[j, VK]]
        r = round_index(ri, np.asarray(M.G_round)[kk])
        if (r < 0).any():
            raise KeyError(f"a sample's round is not among the scored rounds ({sorted(ri)[:3]}...)")
        hit = _pair_covered(kk, np.full(kk.size, int(j)), got, S)
        den += np.bincount(r, minlength=nr)
        num += np.bincount(r[hit], minlength=nr) if hit.any() else 0
    return num, den


def recall_children(M, G_, VK, tv, select: np.ndarray, got: set, ri: dict, nr: int, key_of) -> dict:
    """Recall per child class over (sample, live child) pairs, as
    `class_lane` counts them: the valid samples `VK` (frame replay times
    `tv`) inside each selected joinable child's life."""
    ct = M.tl0.children
    cs = np.flatnonzero(G_["joinable"] & np.asarray(select, bool))
    den_k, den_c = _children_in_life(G_, VK, tv, cs)
    covered = _pair_covered(den_k, den_c, got, ct.n + 1)
    den_r = round_index(ri, np.asarray(M.G_round)[den_k])
    keep = den_r >= 0
    keys = _child_keys(ct, den_c, M.me, key_of)
    out = {}
    for key in sorted(set(keys.tolist())):
        m = keep & (keys == key)
        out[key] = (np.bincount(den_r[m & covered], minlength=nr).astype(float),
                    np.bincount(den_r[m], minlength=nr).astype(float))
    return out


def recall_marks(marks: dict, valid: np.ndarray, got_marks: set, ri: dict, nr: int) -> dict:
    """Recall per mark class over the truth marks whose window holds a valid sample."""
    cs = np.r_[0, np.cumsum(np.asarray(valid, bool))]
    out = {}
    for q, d in enumerate(marks["desc"]):
        a, b = int(marks["k_from"][q]), int(marks["k_to"][q])
        if cs[b + 1] - cs[a] <= 0 or int(marks["round"][q]) not in ri:
            continue
        num, den = out.setdefault(d["recall_key"], (np.zeros(nr), np.zeros(nr)))
        r = ri[int(marks["round"][q])]
        den[r] += 1
        num[r] += q in got_marks
    return out


def hold_duplicate_marks(rows: list, col_kind, col_idx) -> None:
    """A truth mark is one object: where the per-sample join gave one mark
    to two or more finds (a mark born twice, a "?" read twice), the nearest
    keeps it and each other becomes `nothing_there:held_by_nearer_find`,
    naming the mark it repeats (`duplicate_of`). In place."""
    by = defaultdict(list)
    for i, r in enumerate(rows):
        if col_kind[i] == "mark" and r["outcome"] != "ambiguous":
            by[int(col_idx[i])].append(i)
    for idx in by.values():
        if len(idx) < 2:
            continue
        keep = min(idx, key=lambda i: (rows[i]["dist_m"], rows[i]["t_cap"]))
        for i in idx:
            if i == keep:
                continue
            r = rows[i]
            r["duplicate_of"] = r["entity_id"]
            for k in ("entity_id", "entity_class", "family", "agent", "ability", "tray_key", "owner", "side_rel",
                      "truth_name", "drawn"):
                r[k] = None
            r["derivation"] = "held_by_nearer_find"
            r["outcome"], r["label"] = "nothing_there", "nothing_there:held_by_nearer_find"


def summarize_rows(rows_by_session: dict) -> dict:
    """The class-aware outcomes and labels of stored find rows (a lane's
    `classes_SID.jsonl`, a step's `SID.jsonl`), recomputed from storage: per
    session over the rounds that hold a find, and pooled (rounds resampled
    within each match, the matches added). Recall needs the truth pairs, which
    the rows do not hold, so none is reported. Counts equal the run that wrote
    the rows; intervals resample only rounds holding a find."""
    per, arrays = [], []
    for sid, rows in rows_by_session.items():
        rounds = sorted({r["round"] for r in rows})
        doc, arr = step_summary(rows, {}, rounds, None)
        doc.update({"session": sid, "rounds": len(rounds)})
        per.append({"session": sid, "classes": doc})
        arrays.append({"classes": arr})
    out = {"acceptance_version": ACCEPTANCE_VERSION, "boot": f"{N_BOOT} round resamples, seed {SEED}",
           "rounds": "rounds holding a find", "sessions": {p["session"]: p["classes"] for p in per}}
    out["pooled"] = pool_classes(per, arrays) if len(per) > 1 else None
    return out


def step_summary(rows: list, rec: dict, rounds: list, census: dict | None, extra: dict | None = None) -> tuple:
    """One session's step document in `class_lane`'s shape (so `pool_classes`
    pools it) and its per-round arrays; the outcomes must sum to the finds."""
    ri = {r: i for i, r in enumerate(rounds)}
    nr = len(rounds)
    n = len(rows)
    rr = round_index(ri, [r["round"] for r in rows])
    if (rr < 0).any():
        raise KeyError("a find's round is not among the scored rounds")
    top = np.array([r["outcome"] for r in rows], dtype=object)
    lab = np.array([r["label"] for r in rows], dtype=object)

    def per_round(mask):
        return np.bincount(rr[np.asarray(mask, bool)], minlength=nr).astype(float) if n else np.zeros(nr)

    by_out = {o: per_round(top == o) for o in CLASS_OUTCOMES}
    by_lab = {lb: per_round(lab == lb) for lb in sorted(set(lab.tolist()))}
    if sum(v.sum() for v in by_out.values()) != n:
        raise SystemExit("the class-aware outcomes do not sum to the finds")
    fact_of = {r["label"]: r["drawn_by_fact"] for r in rows if r["outcome"] == "other_entity"}
    gap = Counter(r["label"] for r in rows if r["outcome"] == "coverage_gap")
    cen = census or {}
    doc = {"finds": n, "outcomes": {o: int(v.sum()) for o, v in by_out.items()},
           "outcomes_ci": {o: boot_count(rounds, v) for o, v in by_out.items()} if nr else {},
           "labels": {lb: int(v.sum()) for lb, v in sorted(by_lab.items(), key=lambda kv: -kv[1].sum())},
           "labels_ci": {lb: boot_count(rounds, v) for lb, v in by_lab.items()},
           "drawn_by_fact": fact_of, "true_fa": 0, "true_fa_labels": {}, "true_fa_outcomes": {},
           "refused_labels": {}, "old_x_new": {},
           "ambiguous_keys": dict(Counter(" + ".join(r["ambiguous_keys"]) for r in rows
                                          if r["outcome"] == "ambiguous").most_common(15)),
           "recall": {k: {"value": round(float(a.sum() / max(b.sum(), 1)), 4), "ci": boot_share(rounds, a, b),
                          "num": int(a.sum()), "den": int(b.sum()),
                          "drawn_by_fact": (cen.get(k.rsplit(" (", 1)[0]) or {}).get("drawn_by_fact")}
                      for k, (a, b) in rec.items()},
           "distances": {o: dist_summary([r["dist_m"] for r in rows if r["outcome"] == o])
                         for o in ("right_entity", "other_entity", "undrawn_truth", "coverage_gap", "ambiguous")},
           "instrument": {},
           "coverage": {"gap_finds_by_class": dict(gap.most_common()), "census": cen,
                        "not_joined": {k: e["not_joined"] for k, e in cen.items() if e.get("not_joined")}}}
    if extra:
        doc.update(extra)
    return doc, {"out": by_out, "lab": by_lab, "rec": rec}


# ----------------------------------------------------------------- the ability lane
#
# docs/ABILITY_ENTITIES.md section 2.10, step 2: the `ability` lane's emitted
# children of the player scored per class against the replay's casts of the
# player and the actors those casts spawned. Pure over what the caller hands
# in: the lane's entity rows, the truth casts in capture time, every other
# player's casts (so a find on another real cast is that cast's, never a false
# open), the player's deaths and the round bounds.

#: A child pairs with a truth cast whose time lies within this many ms of its
#: open interval: `replay_abilities.CAST_GATE_MS`, the gate the harness pairs
#: stored casts with replay casts by.
ABILITY_OPEN_GATE_MS = 2000.0
#: A truth instance ended by its owner's death, or at the round barrier, when
#: its last actor closes within this many ms of that instant. The truth's end
#: cause is otherwise `other`: lifetime expiry, destruction or recall, which
#: the replay's actors do not tell apart.
ABILITY_END_TOL_MS = 1000.0
#: The outcome of each find, in report order (section 2.10's vocabulary);
#: `coverage_gap` carries the unmapped cast's slot.
ABILITY_OUTCOMES = ("right_entity", "coverage_gap", "right_entity:kind_wrong", "other_entity",
                    "nothing_there")
#: The truth end cause a child's end basis predicts.
ABILITY_END_CAUSE = {"lifetime_expiry": "other", "round_barrier": "round_end",
                     "owner_death": "owner_death"}


def ability_key(name) -> str:
    """An ability's comparison key: its subject's ability part (`sova:recon
    bolt`) or a display name, casefolded to letters and digits."""
    import re
    s = str(name or "")
    s = s.split(":", 1)[1] if ":" in s else s
    return re.sub(r"[^0-9a-z]", "", s.casefold())


#: The slot sides an ability find is scored on (`slot_state.SIDES`), and the
#: group of finds no witness bound to a slot.
ABILITY_SIDES = ("self", "team", "enemy")
ABILITY_UNBOUND = "unbound"


def ability_find_side(e: dict, self_key: str | None) -> str:
    """A lane entity's slot side: `self` where its owner slot is the player's,
    `team` another ally slot, `enemy` an enemy slot, else `unbound`."""
    player = e.get("player")
    if not player:
        return ABILITY_UNBOUND
    if self_key is not None and player == self_key:
        return "self"
    return "enemy" if e.get("side") == "enemy" else "team" if e.get("side") == "ally" else ABILITY_UNBOUND


def ability_lane_finds(entities: list[dict], held: frozenset = frozenset(),
                       self_key: str | None = None, objects: frozenset = frozenset()) -> list[dict]:
    """The lane's ability instances as finds: key, round, ability key, open
    and end intervals, end basis, slot side (`ability_find_side`; every find
    is `self` where no `self_key` is given, as in step 2), and whether the row
    was withheld stale (`held`, entity ids from the ledger). `objects` are
    the keys of spawned-object nodes, which are no instances; their scorer is
    `score_ability_objects`."""
    out = []
    for e in entities:
        if e.get("family") != "ability_object" or e["entity_id"] in objects:
            continue
        life = e["lifetime"]
        out.append({"key": e["entity_id"], "round": int(e["round"]), "ability": ability_key(e["kind"]),
                    "kind": e["kind"], "open_lo": float(life["began"]["lo_ms"]),
                    "open_hi": float(life["began"]["hi_ms"]),
                    "end_hi": float(life["ended"]["hi_ms"]), "end_basis": life["ended"]["basis"],
                    "side": "self" if self_key is None else ability_find_side(e, self_key),
                    "held": e["entity_id"] in held})
    return out


def ability_truth_instances(casts: list[dict], actors: list[dict], deaths_ms, barriers_ms,
                            gate_ms: float = ABILITY_OPEN_GATE_MS,
                            tol_ms: float = ABILITY_END_TOL_MS) -> list[dict]:
    """Each truth cast of the player (`{t_ms, ability, slot}` in capture ms;
    ability None where the replay's slot maps to none) with its end: the last
    close among the player's actors of that ability that open within
    `gate_ms` after it and before the ability's next cast, or None where no
    actor opens; and the end's cause, `owner_death`, `round_end` or `other`."""
    deaths = np.sort(np.asarray(list(deaths_ms), float))
    bars = np.sort(np.asarray(list(barriers_ms), float))
    out = []
    # Per ability, the casts' and the actors' times sorted once; each cast
    # slices the actors that open in its window (ROUNDSCOPE).
    cast_t = defaultdict(list)
    for c in casts:
        cast_t[ability_key(c["ability"])].append(float(c["t_ms"]))
    cast_t = {k: np.sort(np.asarray(v, float)) for k, v in cast_t.items()}
    act = defaultdict(list)
    for a in actors:
        act[ability_key(a["ability"])].append(a)
    act = {k: sorted(v, key=lambda a: float(a["open_ms"])) for k, v in act.items()}
    act_t = {k: np.asarray([float(a["open_ms"]) for a in v], float) for k, v in act.items()}
    for c in sorted(casts, key=lambda c: float(c["t_ms"])):
        t, ab = float(c["t_ms"]), ability_key(c["ability"])
        ct = cast_t[ab]
        k = int(np.searchsorted(ct, t, side="right"))
        stop = float(ct[k]) if k < ct.size else np.inf
        at = act_t.get(ab, np.zeros(0))
        lo = int(np.searchsorted(at, t - 200.0, side="left"))
        hi = int(np.searchsorted(at, min(t + gate_ms, stop), side="right"))
        mine = act.get(ab, [])[lo:hi]
        closes = [float(a["close_ms"]) for a in mine if a.get("close_ms") is not None]
        end = max(closes) if closes else None
        cause = None
        if end is not None:
            near_d = deaths[(deaths >= t) & (np.abs(deaths - end) <= tol_ms)]
            near_b = bars[np.abs(bars - end) <= tol_ms]
            cause = "owner_death" if near_d.size else "round_end" if near_b.size else "other"
        out.append({"t_ms": t, "ability": ab if c["ability"] else None, "raw": c["ability"],
                    "slot": c.get("slot"), "end_ms": end, "end_cause": cause, "actors": len(mine)})
    return out


def _near_casts(items: list[dict], times: np.ndarray, f: dict, gate_ms: float) -> list[int]:
    """Indices of `items` (sorted by `times`) within `gate_ms` of a find's open
    interval: one sorted slice, never a walk of every item."""
    lo = int(np.searchsorted(times, f["open_lo"] - gate_ms, side="left"))
    hi = int(np.searchsorted(times, f["open_hi"] + gate_ms, side="right"))
    return list(range(lo, hi))


def _gap(f: dict, t: float) -> float:
    """Distance (ms) from a truth time to a find's open interval; 0 inside."""
    return max(f["open_lo"] - t, t - f["open_hi"], 0.0)


def pair_ability(finds: list[dict], truth: list[dict], gate_ms: float = ABILITY_OPEN_GATE_MS):
    """One-to-one pairs of finds and truth casts of the same ability, nearest
    first, within `gate_ms` of the find's open interval: (find index, truth index)."""
    order = sorted(range(len(truth)), key=lambda j: float(truth[j]["t_ms"]))
    times = np.asarray([float(truth[j]["t_ms"]) for j in order], float)
    cand = []
    for i, f in enumerate(finds):
        near = [order[k] for k in _near_casts(truth, times, f, gate_ms)]
        cand += [(_gap(f, truth[j]["t_ms"]), i, j) for j in near
                 if truth[j]["ability"] == f["ability"]]
    cand.sort()
    used_i, used_j, out = set(), set(), []
    for _g, i, j in cand:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        out.append((i, j))
    return out


def _ms_summary(v) -> dict:
    v = np.asarray([x for x in v if x is not None], float)
    if not v.size:
        return {"n": 0}
    return {"n": int(v.size), "median_ms": round(float(np.median(v)), 1),
            "abs_p90_ms": round(float(np.percentile(np.abs(v), 90)), 1)}


def score_ability_lane(finds: list[dict], truth: list[dict], others: list[dict], round_starts,
                       gate_ms: float = ABILITY_OPEN_GATE_MS) -> tuple[dict, dict]:
    """Per class (the player's ability) and over all classes: open recall of
    the truth casts, false opens, each find's outcome against every cast the
    replay holds, open and end time error, and agreement of the find's end
    basis with the truth end's cause. Intervals resample rounds.

    `others` are the other players' casts (`{t_ms, ability, agent}`); a find
    no own cast pairs is `right_entity:kind_wrong` where an own cast of
    another ability lies within the gate, `other_entity` where another
    player's cast of its ability does, else `nothing_there`. A truth cast
    whose slot maps to no ability is a coverage gap, never a miss of a class.
    Returns (document, per-class per-round arrays for `pool_ability_lane`)."""
    starts = np.sort(np.asarray(list(round_starts), float))
    rounds_of = lambda t: int(np.searchsorted(starts, t, side="right"))
    mapped = [dict(tr) for tr in truth if tr["ability"]]
    finds = [dict(f) for f in finds]
    gaps = Counter(f"coverage_gap:slot_unmapped:{tr.get('slot')}" for tr in truth if not tr["ability"])
    for f in finds:
        f["_r"] = rounds_of(f["open_hi"])
    for tr in mapped:
        tr["_r"] = rounds_of(tr["t_ms"])
    rounds = sorted({f["_r"] for f in finds} | {tr["_r"] for tr in mapped})
    ri = {r: i for i, r in enumerate(rounds)}
    nr = len(rounds)
    pairs = pair_ability(finds, mapped, gate_ms)
    fi = {i: j for i, j in pairs}
    tj = {j: i for i, j in pairs}
    by_t = lambda xs: sorted(xs, key=lambda x: float(x["t_ms"]))
    unmapped = by_t(tr for tr in truth if not tr["ability"])
    mapped_t, others_t = by_t(mapped), by_t(others)
    times = {id(xs): np.asarray([float(x["t_ms"]) for x in xs], float)
             for xs in (unmapped, mapped_t, others_t)}
    outcome = []
    for i, f in enumerate(finds):
        # Each find slices the sorted casts near its open (ROUNDSCOPE).
        gap = [unmapped[k] for k in _near_casts(unmapped, times[id(unmapped)], f, gate_ms)]
        own = _near_casts(mapped_t, times[id(mapped_t)], f, gate_ms)
        oth = [others_t[k] for k in _near_casts(others_t, times[id(others_t)], f, gate_ms)]
        if i in fi:
            outcome.append("right_entity")
        elif gap:
            outcome.append(f"coverage_gap:slot_unmapped:{gap[0].get('slot')}")
        elif own:
            outcome.append("right_entity:kind_wrong")
        elif any(ability_key(o["ability"]) == f["ability"] for o in oth):
            outcome.append("other_entity")
        else:
            outcome.append("nothing_there")

    def per_round(idx, items):
        a = np.zeros(nr)
        for k in idx:
            a[ri[items[k]["_r"]]] += 1
        return a

    def block(cls) -> tuple[dict, dict]:
        fs = [i for i, f in enumerate(finds) if cls is None or f["ability"] == cls]
        ts = [j for j, tr in enumerate(mapped) if cls is None or tr["ability"] == cls]
        hit = [j for j in ts if j in tj]
        # A find on an own cast whose slot maps to no ability is that cast's
        # coverage gap, never a false open.
        false = [i for i in fs if i not in fi and not outcome[i].startswith("coverage_gap")]
        num, den = per_round(hit, mapped), per_round(ts, mapped)
        fnum, fden = per_round(false, finds), per_round(fs, finds)
        open_err = [finds[tj[j]]["open_hi"] - mapped[j]["t_ms"] for j in hit]
        end_err, agree, conf = [], [], Counter()
        for j in hit:
            f, tr = finds[tj[j]], mapped[j]
            if tr["end_ms"] is None:
                conf[f"{f['end_basis']}|no_truth_actor"] += 1
                continue
            end_err.append(f["end_hi"] - tr["end_ms"])
            conf[f"{f['end_basis']}|{tr['end_cause']}"] += 1
            want = ABILITY_END_CAUSE.get(f["end_basis"])
            agree.append(want == tr["end_cause"] if want else
                         abs(f["end_hi"] - tr["end_ms"]) <= ABILITY_END_TOL_MS)
        doc = {"truth": len(ts), "finds": len(fs), "paired": len(hit),
               "held_stale_finds": sum(finds[i]["held"] for i in fs),
               "recall": round(len(hit) / len(ts), 4) if ts else None,
               "recall_ci": boot_share(rounds, num, den) if ts and nr else None,
               "false_opens": len(false),
               "false_open_share": round(len(false) / len(fs), 4) if fs else None,
               "false_open_ci": boot_share(rounds, fnum, fden) if fs and nr else None,
               "outcomes": dict(Counter(outcome[i] for i in fs)),
               "open_error": _ms_summary(open_err), "end_error": _ms_summary(end_err),
               "end_cause": dict(sorted(conf.items())),
               "end_cause_agreement": round(sum(agree) / len(agree), 4) if agree else None,
               "end_cause_n": len(agree)}
        return doc, {"num": num, "den": den, "fnum": fnum, "fden": fden,
                     "agree": sum(agree), "agree_n": len(agree), "open_err": open_err,
                     "end_err": end_err}

    classes = sorted({f["ability"] for f in finds} | {tr["ability"] for tr in mapped})
    per, arrays = {}, {}
    for cls in classes:
        per[cls], arrays[cls] = block(cls)
    allb, arrays["_all"] = block(None)
    doc = {"acceptance_version": ACCEPTANCE_VERSION, "gate_ms": gate_ms,
           "end_tol_ms": ABILITY_END_TOL_MS, "boot": f"{N_BOOT} round resamples, seed {SEED}",
           "rounds": nr, "classes": per, "all": allb, "coverage_gaps": dict(gaps),
           "outcome_of": {f["key"]: o for f, o in zip(finds, outcome)}}
    return doc, arrays


#: A spawned-object node pairs with a truth actor of its class whose open lies
#: within this many ms of the node's open interval.
ABILITY_OBJECT_GATE_MS = ABILITY_OPEN_GATE_MS


def object_class_key(name) -> str:
    """A spawned object's class key: the actor class without the `_C` suffix,
    casefolded (`Pawn_Gumshoe_E_PossessableCamera_C` -> the sheet's stem)."""
    s = str(name or "")
    return (s[:-2] if s.endswith("_C") else s).casefold()


def truth_end_cause(end_ms, deaths_ms, barriers_ms, open_ms, tol_ms: float = ABILITY_END_TOL_MS):
    """A truth actor's end cause: `owner_death` where its close lies within
    `tol_ms` of an owner death after its open, `round_end` within `tol_ms`
    of a barrier, else `other`; None where it never closes."""
    if end_ms is None:
        return None
    d = np.asarray(list(deaths_ms), float)
    b = np.asarray(list(barriers_ms), float)
    if d.size and np.any((d >= open_ms) & (np.abs(d - end_ms) <= tol_ms)):
        return "owner_death"
    if b.size and np.any(np.abs(b - end_ms) <= tol_ms):
        return "round_end"
    return "other"


def score_ability_objects(nodes: list[dict], actors: list[dict], round_starts,
                          gate_ms: float = ABILITY_OBJECT_GATE_MS) -> tuple[dict, dict]:
    """Spawned-object nodes per class against the replay's actors of that
    class (section 2.10): open recall over the truth actors (any node, and
    witnessed nodes only), nodes no actor pairs, open and end error, and
    agreement of the node's end basis with the actor's end cause.

    `nodes`: `{key, cls, side, agent, exists, open_lo, open_hi, end_hi,
    end_basis}`; `actors`: `{cls, side, agent, open_ms, close_ms, end_cause}`,
    the classes of the spawn tree only. A node pairs one to one, nearest
    first, with an actor of its class, side and agent whose open lies within
    `gate_ms` of the node's open interval. Intervals resample rounds."""
    starts = np.sort(np.asarray(list(round_starts), float))
    rounds_of = lambda t: int(np.searchsorted(starts, t, side="right"))
    nodes = [dict(n) for n in nodes]
    actors = [dict(a) for a in actors]
    for n in nodes:
        n["_r"] = rounds_of(n["open_hi"])
    for a in actors:
        a["_r"] = rounds_of(a["open_ms"])
    rounds = sorted({n["_r"] for n in nodes} | {a["_r"] for a in actors})
    ri = {r: i for i, r in enumerate(rounds)}
    nr = len(rounds)

    def same(n, a):
        return n["cls"] == a["cls"] and n["side"] == a["side"] and \
            str(n.get("agent") or "").casefold() == str(a.get("agent") or "").casefold()

    def pairs_of(keep):
        order = sorted(range(len(actors)), key=lambda j: actors[j]["open_ms"])
        times = np.asarray([actors[j]["open_ms"] for j in order], float)
        cand = []
        for i, n in enumerate(nodes):
            if not keep(n):
                continue
            f = {"open_lo": n["open_lo"], "open_hi": n["open_hi"]}
            for k in _near_casts(actors, times, f, gate_ms):
                j = order[k]
                if same(n, actors[j]):
                    cand.append((_gap(f, actors[j]["open_ms"]), i, j))
        cand.sort()
        ui, uj, out = set(), set(), {}
        for _g, i, j in cand:
            if i in ui or j in uj:
                continue
            ui.add(i)
            uj.add(j)
            out[j] = i
        return out

    pair_any = pairs_of(lambda n: True)
    pair_seen = pairs_of(lambda n: n["exists"] == "witnessed")

    def per_round(idx, items):
        a = np.zeros(nr)
        for k in idx:
            a[ri[items[k]["_r"]]] += 1
        return a

    def block(key) -> tuple[dict, dict]:
        ns = [i for i, n in enumerate(nodes) if key is None or (n["side"], n["cls"]) == key]
        ts = [j for j, a in enumerate(actors) if key is None or (a["side"], a["cls"]) == key]
        hit = [j for j in ts if j in pair_any]
        seen_hit = [j for j in ts if j in pair_seen]
        paired_nodes = set(pair_any.values())
        lone = [i for i in ns if i not in paired_nodes]
        open_err, end_err, agree, conf = [], [], [], Counter()
        for j in hit:
            n, a = nodes[pair_any[j]], actors[j]
            open_err.append(n["open_hi"] - a["open_ms"])
            if a["close_ms"] is None:
                conf[f"{n['end_basis']}|no_truth_close"] += 1
                continue
            end_err.append(n["end_hi"] - a["close_ms"])
            conf[f"{n['end_basis']}|{a['end_cause']}"] += 1
            want = ABILITY_END_CAUSE.get(n["end_basis"])
            agree.append(want == a["end_cause"] if want else
                         abs(n["end_hi"] - a["close_ms"]) <= ABILITY_END_TOL_MS)
        num, den = per_round(hit, actors), per_round(ts, actors)
        fnum, fden = per_round(lone, nodes), per_round(ns, nodes)
        doc = {"truth": len(ts), "finds": len(ns), "paired": len(hit),
               "witnessed_finds": sum(nodes[i]["exists"] == "witnessed" for i in ns),
               "witnessed_paired": len(seen_hit),
               "recall": round(len(hit) / len(ts), 4) if ts else None,
               "recall_ci": boot_share(rounds, num, den) if ts and nr else None,
               "witnessed_recall": round(len(seen_hit) / len(ts), 4) if ts else None,
               "false_opens": len(lone),
               "false_open_share": round(len(lone) / len(ns), 4) if ns else None,
               "false_open_ci": boot_share(rounds, fnum, fden) if ns and nr else None,
               "open_error": _ms_summary(open_err), "end_error": _ms_summary(end_err),
               "end_cause": dict(sorted(conf.items())),
               "end_cause_agreement": round(sum(agree) / len(agree), 4) if agree else None,
               "end_cause_n": len(agree)}
        return doc, {"num": num, "den": den, "fnum": fnum, "fden": fden, "agree": sum(agree),
                     "agree_n": len(agree), "open_err": open_err, "end_err": end_err}

    keys = sorted({(n["side"], n["cls"]) for n in nodes} | {(a["side"], a["cls"]) for a in actors})
    per, arrays = {}, {}
    for k in keys:
        name = f"{k[0]}|{k[1]}"
        per[name], arrays[name] = block(k)
    allb, arrays["_all"] = block(None)
    return {"acceptance_version": ACCEPTANCE_VERSION, "gate_ms": gate_ms,
            "boot": f"{N_BOOT} round resamples, seed {SEED}", "rounds": nr,
            "classes": per, "all": allb}, arrays


def pool_ability_lane(arrays: list[dict]) -> dict:
    """The sessions' per-class blocks pooled: recall and false-open share with
    intervals that resample rounds within each match and add the matches."""
    classes = sorted({c for a in arrays for c in a})
    out = {}
    for cls in classes:
        got = [a[cls] for a in arrays if cls in a]
        num = sum(float(g["num"].sum()) for g in got)
        den = sum(float(g["den"].sum()) for g in got)
        fnum = sum(float(g["fnum"].sum()) for g in got)
        fden = sum(float(g["fden"].sum()) for g in got)
        ag, agn = sum(g["agree"] for g in got), sum(g["agree_n"] for g in got)
        oe = [x for g in got for x in g["open_err"]]
        ee = [x for g in got for x in g["end_err"]]
        use = [g for g in got if g["num"].size]
        out[cls] = {"truth": int(den), "finds": int(fden), "paired": int(num),
                    "recall": round(num / den, 4) if den else None,
                    "recall_ci": boot_pooled([(g["num"], g["den"]) for g in use]) if den and use else None,
                    "false_opens": int(fnum),
                    "false_open_share": round(fnum / fden, 4) if fden else None,
                    "false_open_ci": (boot_pooled([(g["fnum"], g["fden"]) for g in use])
                                      if fden and use else None),
                    "open_error": _ms_summary(oe), "end_error": _ms_summary(ee),
                    "end_cause_agreement": round(ag / agn, 4) if agn else None, "end_cause_n": agn}
    return out


# ----------------------------------------------------------------- slot regions against replay truth

#: A slot's fit lies on its own player, another player or nothing, within
#: this many metres of a living player's replay place (`NEAR_CM`).
SLOT_NEAR_M = NEAR_CM / 100.0
#: The outcomes of a slot's fit, in report order. The scorer joins players
#: only: an ability child, the spike or an ult orb under a fit is not
#: joined, so a fit on one reads `nothing_there` (each report says so).
SLOT_FIT_OUTCOMES = ("right_entity", "same_side", "other_side", "nothing_there")
SLOT_NOT_JOINED = ("ability children, the spike and the ult orbs: this scorer pairs each slot with "
                   "its own replay player and checks fits against players only")


def _round_counts(rr: np.ndarray, nr: int, mask) -> np.ndarray:
    return np.bincount(rr[np.asarray(mask, bool)], minlength=nr).astype(float)


def _quantiles(v) -> dict:
    """n, median, p10 and p90 of the finite values."""
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not v.size:
        return {"n": 0}
    p10, med, p90 = np.percentile(v, (10, 50, 90))
    return {"n": int(v.size), "median": round(float(med), 2), "p10": round(float(p10), 2),
            "p90": round(float(p90), 2)}


def slot_fit_outcomes(fx, fy, own_x, own_y, side_x, side_y, other_x, other_y,
                      near_m: float = SLOT_NEAR_M) -> np.ndarray:
    """Each fit's outcome (index into `SLOT_FIT_OUTCOMES`): its own player
    within `near_m`, else another living player of its side, else a living
    player of the other side, else nothing. Positions in metres; `side_*`
    (the slot's side, its own player left out) and `other_*` are (rows,
    players) with NaN where none lives."""
    def near(px, py):
        d = np.hypot(np.asarray(px, float) - np.asarray(fx, float)[:, None],
                     np.asarray(py, float) - np.asarray(fy, float)[:, None])
        return (np.where(np.isfinite(d), d, np.inf) <= near_m).any(axis=1)
    own = np.hypot(np.asarray(own_x, float) - fx, np.asarray(own_y, float) - fy) <= near_m
    return np.where(own, 0, np.where(near(side_x, side_y), 1, np.where(near(other_x, other_y), 2, 3)))


def slot_region_scores(Q: dict, SF: dict, kinds: dict, *, unbounded: tuple) -> dict:
    """One session's slot beliefs against replay truth, with per-round arrays
    for pooling (`pool_slot_regions`).

    `Q` holds one row per (frame, living truth player with a slot): `round`
    (index into the session's `n_rounds` scored rounds), `inside` (the truth
    lies in the slot's region and the slot is open), `kind` (the belief's
    code), `area` (m^2, NaN where the region is the map or the slot is
    closed), `R` (the region's radius, m), `drawn` (the T1d rule draws the
    player there) and `fit_out` (`slot_fit_outcomes`, -1 without a fit).
    `SF` holds one row per open slot-frame on the scored frames: `round`,
    `kind`, `slot`. `kinds` maps codes to names; `unbounded` names the kinds
    whose region is the whole map.

    Calibration is the share of rows whose truth lies inside; the lane's
    coverage, the share whose slot holds a fit; unanchored, the share of
    open slot-frames whose region is the whole map. Intervals resample
    rounds (`boot_share`)."""
    nr = int(Q["n_rounds"])
    rounds = list(range(nr))
    code = {v: k for k, v in kinds.items()}
    arr = {}

    def share(name, rr, num, den):
        a, b = _round_counts(rr, nr, num & den), _round_counts(rr, nr, den)
        arr[name] = (a, b)
        return {"value": round(float(a.sum() / b.sum()), 4) if b.sum() else None,
                "ci": boot_share(rounds, a, b) if b.sum() else None,
                "num": int(a.sum()), "den": int(b.sum())}

    rr = np.asarray(Q["round"], np.int64)
    kind = np.asarray(Q["kind"], np.int64)
    inside = np.asarray(Q["inside"], bool)
    drawn = np.asarray(Q["drawn"], bool)
    fit = kind == code["fit"]
    unb = np.isin(kind, [code[k] for k in unbounded])
    one = np.ones(rr.size, bool)
    out = {"rows": int(rr.size), "rounds": nr,
           "calibration": share("calibration", rr, inside, one),
           "calibration_anchored": share("calibration_anchored", rr, inside, ~unb),
           "calibration_drawn": share("calibration_drawn", rr, inside, drawn),
           "calibration_undrawn": share("calibration_undrawn", rr, inside, ~drawn),
           "lane_coverage": share("lane_coverage", rr, fit, one),
           "lane_coverage_drawn": share("lane_coverage_drawn", rr, fit, drawn),
           "by_kind": {}}
    area = np.asarray(Q["area"], float)
    R = np.asarray(Q["R"], float)
    for c, name in kinds.items():
        m = kind == c
        if m.any():
            out["by_kind"][name] = {**share(f"kind_{name}", rr, inside, m),
                                    "rows_share": round(float(m.mean()), 4),
                                    "area_m2": _quantiles(area[m]), "radius_m": _quantiles(R[m])}
    out["area_m2_bounded"] = _quantiles(area[~unb])
    # the median region over every open row, the map counted as the largest
    # region: "map" where unbounded rows are at least half of them
    am = np.where(unb, np.inf, area)
    am = am[~np.isnan(am)]
    med = float(np.median(am)) if am.size else None
    out["area_m2_median_map_counted"] = (None if med is None else
                                         "map" if not np.isfinite(med) else round(med, 2))
    fo = np.asarray(Q["fit_out"], np.int64)
    out["fit_outcomes"] = {o: share(f"fit_{o}", rr, fo == i, fit) for i, o in enumerate(SLOT_FIT_OUTCOMES)}
    out["fit_not_joined"] = SLOT_NOT_JOINED
    srr = np.asarray(SF["round"], np.int64)
    skind = np.asarray(SF["kind"], np.int64)
    sslot = np.asarray(SF["slot"], np.int64)
    sun = np.isin(skind, [code[k] for k in unbounded])
    out["unanchored"] = share("unanchored", srr, sun, np.ones(srr.size, bool))
    out["unanchored_by_slot"] = {int(s): share(f"unanchored_slot{int(s)}", srr, sun, sslot == s)
                                 for s in np.unique(sslot)}
    out["open_kinds"] = {kinds[int(c)]: int((skind == c).sum()) for c in np.unique(skind)}
    return {"doc": out, "arrays": arr}


def pool_slot_regions(per: list[dict]) -> dict:
    """`slot_region_scores` pooled over sessions: each share summed, its
    interval resampling rounds within each match and adding the matches
    (`boot_pooled`)."""
    if not per:
        return {}
    out = {}
    for name in sorted(set.intersection(*(set(p["arrays"]) for p in per))):
        pm = [p["arrays"][name] for p in per]
        a = sum(float(x[0].sum()) for x in pm)
        b = sum(float(x[1].sum()) for x in pm)
        out[name] = {"value": round(a / b, 4) if b else None, "ci": boot_pooled(pm) if b else None,
                     "num": int(a), "den": int(b)}
    return out
