r"""Causal per-frame binding of ally fits to the five ally slots.

    .\.venv\Scripts\python.exe prototypes\entity_state.py score SESSION ... --pool NAME --binding causal

Stage 2 of [docs/ENTITY_STATE.md](../docs/ENTITY_STATE.md) (section 2,
"Identity enters through the arbiter"), as a prototype beside
`prototypes/entity_state.py`, which calls it when `--binding causal` is
given; `--binding post_round` keeps the stage 1 path so both are scored. Not
wired (`"wire": "no"` in the store's `notes/predictions.jsonl`). It reads
STORED rows only: the `ally_icon` icon and frame rows, the `ping` and
`spike` events, the `tray_kit` rows, the lineup and the baked geometry's
labels. It decodes nothing and reads no crop.

The assignment
--------------
At each frame `t`, every ally fit of that frame (each `ally_icon` icon row,
refused or not, and the self fit when it is not bound directly) goes to one
of the open teammate slots or to its own non-player column, by one
`track.assign` (`scipy.optimize.linear_sum_assignment`, the
`track-continuation` owner's solver) over

    cost[f, s] = motion[f, s] - W_ID * clip(llr[f, agent(s)], LLR_CLIP)
    cost[f, np_f] = log(A_map) + K_NP - sum(bonus[reason] for f's reasons)

* `motion[f, s]`: the slot's belief at `t` from what was bound before `t`:
  a Gaussian per square metre round the slot's last bound fit,
  `0.5 (d / sigma)^2 + log(2 pi sigma^2)`, `sigma = R / 2` and
  `R = v_max (t - t_bound) + r_fit` (the reach radius, so the region's edge
  sits at two sigma); `log(A_map)` (uniform over the map) for a slot with no
  fit since its round opened.
* `llr[f, a]`: the fit's own portrait log ratio for agent `a` over the
  teammates the arbiter names (`identity.rendered_art_scores`, the
  `agent-identity` owner), read only for a fit the reader did not refuse.
  Only the fit's own frame enters: evidence available at `t`, never pooled
  forward. A slot's agent is the arbiter's lineup verdict; the prior is
  weighed once (results declare `rests_on`).
* Non-player reasons, each from a stored owner: `off_map` (the fit's centre
  lies more than one icon radius from every non-void cell of the baked
  `(map, profile)` labels, `minimap.VOID`), `ability_glyph` (the reader
  refused the ring as `interior_is_map`, which `round_entity` calls a
  barrier), `not_a_teammate` (`identity.teammate_fit_refusal`: the portrait
  fits none of the teammates' rendered art), `ping` (an active `ping`
  entity within two icon radii), `spike` (a dropped spike glyph the `spike`
  reader accepted within two icon radii, in the last second). A fit the
  assignment leaves to its non-player column with none of these is
  `duplicate` when it lies within two icon radii of a bound fit of the
  frame, else `unexplained`.

No fit opens a slot; a slot no fit binds keeps its belief and grows its
reach. One fit binds one slot at most (the solver's one-to-one), checked.

Self fits
---------
While the player's slot is open the self fit binds to it directly (the self
channel). After the player's death the self icon draws the spectated
teammate [domain:minimap/self-icon-shows-spectated]: the self fit binds to
the slot of the agent whose kit the tray shows then
(`adjudication.tray_kit.stored_kit_witness`, `kit_agents_at` with no
lookahead), `rests_on` that witness, whose span agents are pooled over each
whole span (a post-round `tray_kit` verdict, disclosed). A self fit off the
map binds no spectated slot; it enters the assignment with its `off_map`
reason. Where no current `tray_kit` row names a teammate's kit, the
self fit enters the assignment as an ordinary fit with no portrait term
(`via_spectated`), and the gap is counted.

Witnessed bindings
------------------
A binding anchors a reach region only when a witness names it: the self
channel, the spectating witness, or a portrait margin of at least the
rendered-art table's `margin_min` over every other open teammate slot's
agent. Every other binding is `fit_unnamed` (`entity_state.beliefs`).
Exclusivity (the fit lies in this slot's reach region and in no other open
slot's, every other open slot being anchored, and its portrait names no
other slot) is recorded as code 4 and anchors nothing: on the dev sessions
it carried wrong anchors forward.

Chains
------
Each slot carries its chain's portrait evidence: the decayed sum of the log
ratios of the fits bound to it (`DECAY` a frame). When the evidence of the
open teammate chains names a different chain-to-slot assignment, by at
least `SWAP_MIN` nats over the current one, the chains move: each slot
takes the motion state and evidence of the chain its evidence names. Frames
already bound stay as published; the move changes only what follows.

Outcome (2026-10-04, entity-binding-0.1.1)
------------------------------------------
Developed on the dev sessions only (`3694746e4e54`, `a06f04a0059f`,
`bdfdcf009dba`, `9acf02f98283`): chains, the relocation cap and the
chain-confirmed portrait witness came from the dev misses; the parameters
were fixed in an amendment row before the held-out score. Dev (0.1.0):
[metric:entity_state/riot_pool@dev4_causal#calibration=0.9657] against the
post-round [metric:entity_state/riot_pool@dev4_post_round#calibration=0.9521].
The held-out six, a second look, scored once, then rescored once after
the 0.1.1 correction of a causal leak a review found (the spectating witness
read `tray_kit` spans 100 ms ahead; off-map self fits could bind the
spectated slot), a correction and not a third look:
[metric:entity_state/riot_pool@heldout6es_causal#calibration=0.9689]
(post-round [metric:entity_state/riot_pool@heldout6es_post_round#calibration=0.9355]),
short of the 0.97 gate; the 8 kill instants the death owner's next-round
stamp closes are among the misses. By kind: fit
[metric:entity_state/riot_pool@heldout6es_causal#fit_calibration=0.9801],
fit_unnamed [metric:entity_state/riot_pool@heldout6es_causal#fit_unnamed_calibration=0.9711],
reach [metric:entity_state/riot_pool@heldout6es_causal#reach_calibration=0.9524]
(median radius [metric:entity_state/riot_pool@heldout6es_causal#reach_radius_m_median=9.81] m),
crowd [metric:entity_state/riot_pool@heldout6es_causal#crowd_calibration=0.973].
By session it runs from
[metric:entity_state/riot_pool@heldout6es_causal#59c70f1ef720.calibration=0.9471]
to [metric:entity_state/riot_pool@heldout6es_causal#043bafca271a.calibration=0.9889].
A bound fit lies within 8 m of the truth on
[metric:entity_state/riot_pool@heldout6es_causal#fit_bound_share=0.7615] of
living-teammate instants, against the ring fits'
[metric:entity_state/riot_pool@heldout6es_causal#ring_located_share=0.7121];
no frame binds one fit to two slots. The replay's every drawn frame (0.1.0, before the correction):
[metric:entity_state/replay@9acf02f98283_causal#calibration=0.9722]
(post-round [metric:entity_state/replay@9acf02f98283_post_round#calibration=0.944]).

Non-player fits on the held-out six, by reason: `ability_glyph`
[metric:entity_state/riot_pool@heldout6es_causal#non_player_ability_glyph=18743],
`unexplained` [metric:entity_state/riot_pool@heldout6es_causal#non_player_unexplained=7290],
`off_map` [metric:entity_state/riot_pool@heldout6es_causal#non_player_off_map=1492],
`ping` [metric:entity_state/riot_pool@heldout6es_causal#non_player_ping=1376],
`duplicate` [metric:entity_state/riot_pool@heldout6es_causal#non_player_duplicate=596],
`not_a_teammate` [metric:entity_state/riot_pool@heldout6es_causal#non_player_not_a_teammate=71],
`spike` [metric:entity_state/riot_pool@heldout6es_causal#non_player_spike=51].
The binding costs a median
[metric:entity_state/riot_pool@heldout6es_causal#cost_us_per_frame_median=152.2] us
a frame and at most
[metric:entity_state/riot_pool@heldout6es_causal#cost_us_per_frame_max=174.88],
a Python loop over frames with one solver call each.

Six held-out misses viewed in the minimap crop cache: a ring fit on an
enemy icon of the same agent while the teammate stood stacked under
another; a real icon explained away as a ping drawn beside it; an icon the
reader never fitted while the slot took a fit on an ability line; a swap
the chain evidence had not yet moved; a spectating witness that named the
wrong teammate; a fit on bare floor beside an ability drawing. Most need a
second channel to refuse the fit (the enemy reader, the ability readers),
cross-referenced before any cost is tuned.

Follow-ups for the next confirmation set (the held-out six are spent; new
matches from 2026-10-05), none tuned here: the ping bonus (6 nats within two
icon radii) explains real teammates away as pings; portrait evidence counts
twice, in the per-frame cost and in the chain sum; a chain-confirmed
portrait witness can be confidently wrong.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from pathlib import Path

import numpy as np

STORE = Path.home() / "reticle-store"

#: 0.1.0 (2026-10-04): the causal binding as pre-registered (store
#: `notes/predictions.jsonl`, task entity-binding-20261004).
#: 0.1.1 (2026-10-04): the causal-leak correction: the spectating witness
#: reads `kit_agents_at` with no lookahead, and a self fit off the map binds
#: no spectated slot; no cost or parameter changed.
ENTITY_BINDING_VERSION = "entity-binding-0.1.1"

#: Weight of the portrait log ratio against the motion term, and its clip:
#: one fit's portrait never outweighs a motion surprise of more than
#: `W_ID * LLR_CLIP` nats.
W_ID = 1.0
LLR_CLIP = 4.0
#: A chain's portrait evidence decays by this factor a frame (half-life about
#: one second at 15 Hz), and chains move between slots only when the move
#: gains at least SWAP_MIN nats of it.
DECAY = 0.955
SWAP_MIN = 6.0
#: A portrait witness anchors only when its chain's evidence names its slot
#: by at least this many nats over every other open teammate slot.
CHAIN_MIN = 3.0
#: A relocation (a fit far outside the slot's region, observations win):
#: its motion cost is capped at a uniform-over-the-map binding plus this.
K_RELOC = 3.0
#: The non-player column's price over a uniform-over-the-map binding, in nats.
K_NP = 3.0
#: What each stored non-player reason takes off that price.
NP_BONUS = {"off_map": 50.0, "ability_glyph": 50.0, "not_a_teammate": 4.0, "ping": 6.0,
            "spike": 6.0}
NP_REASONS = ("off_map", "ability_glyph", "not_a_teammate", "ping", "spike")
#: Every non-player bucket, the two the assignment leaves last included.
NP_BUCKETS = NP_REASONS + ("duplicate", "unexplained")

#: How each fit was bound (u1); entity_state's HOW_* codes 1-4 stay theirs.
HOW_SELF, HOW_SPECTATE, HOW_ASSIGNED, HOW_ASSIGNED_SPECTATED = 1, 6, 7, 8
WITNESS_SELF, WITNESS_SPECTATE, WITNESS_PORTRAIT, WITNESS_EXCLUSIVE = 1, 2, 3, 4
#: A fit whose own portrait names its slot while its chain's evidence does not.
WITNESS_PORTRAIT_UNCONFIRMED = 5
#: The witness codes that anchor a reach region. Exclusivity is recorded and
#: anchors nothing: it rests on every other slot's anchor being right.
ANCHORING = (WITNESS_SELF, WITNESS_SPECTATE, WITNESS_PORTRAIT)


def params() -> dict:
    return {"version": ENTITY_BINDING_VERSION, "W_ID": W_ID, "LLR_CLIP": LLR_CLIP, "K_NP": K_NP,
            "NP_BONUS": dict(NP_BONUS), "DECAY": DECAY, "SWAP_MIN": SWAP_MIN, "CHAIN_MIN": CHAIN_MIN, "K_RELOC": K_RELOC}


# ----------------------------------------------------------------- stored inputs

def _ref_name(agent, refs: dict) -> str | None:
    """The rendered-art table's key for a lineup agent name ('KAY/O' -> 'KAY_O')."""
    if agent is None:
        return None
    c = str(agent).strip().lower().replace("/", "").replace("_", "")
    return next((k for k in refs if k.lower().replace("_", "") == c), None)


def off_map_mask(sid: str, r_px: float) -> tuple[np.ndarray, float]:
    """(H, W) True where a fit's centre lies more than `r_px` from every
    non-void cell of the baked labels, and the map's non-void area in px."""
    from scipy.ndimage import distance_transform_edt

    from reticle import geometry
    from reticle.minimap import VOID
    with np.load(geometry.path_of(sid, STORE)) as z:
        lab = z["labels"]
    void = lab == VOID
    return distance_transform_edt(void) > r_px, float((~void).sum())


def load_fits(sid: str, S, slots: list[dict], player_slot, to_m, r_px: float) -> dict:
    """Every stored ally fit of the session's frames, as flat arrays in frame
    order, with its portrait log ratios per slot and its non-player reasons.

    The self fit of each frame (the `ally_icon` frame row's `self`) comes
    last in its frame, flagged `is_self`."""
    from reticle.adjudication import identity
    from reticle.store import Store

    st = Store(STORE)
    F = S.fr_t.size
    fpos_of = {int(f): i for i, f in enumerate(S.fr_f)}
    refs = identity.load_ally_portrait_references(STORE)
    names, col = [], []
    for k, s in enumerate(slots):
        if k == player_slot:
            continue
        n = _ref_name(s.get("agent"), (refs or {}).get("agents", {}))
        if n is not None:
            names.append(n)
            col.append(k)
    rows = {"fpos": [], "cx": [], "cy": [], "reason": [], "key": [], "self": [], "llr": [],
            "not_mate": []}
    nofeat = Counter()
    tf = (refs or {}).get("teammate_fit")
    fv = (refs or {}).get("features_version")
    for r in st.read_events("ally_icon", sid):
        k = r.get("kind")
        if k == "icon":
            fp = fpos_of.get(int(r["frame_idx"]))
            if fp is None:
                continue
            llr = np.zeros(5)
            nm = False
            feats = r.get("portrait_features")
            if r.get("reason") is None and feats and refs and len(names) >= 2 \
                    and r.get("portrait_features_version") == fv:
                sc = identity.rendered_art_scores(feats, names, refs)
                if sc is not None:
                    llr[col] = [sc[n] for n in names]
                fit = identity.rendered_art_fit(feats, names, refs)
                if fit is not None:
                    nm = identity.teammate_fit_refusal([fit[0]], tf)[0] is not None
            else:
                nofeat[r.get("reason") or "no_features"] += 1
            rows["fpos"].append(fp)
            rows["cx"].append(float(r["cx"]))
            rows["cy"].append(float(r["cy"]))
            rows["reason"].append(r.get("reason"))
            rows["key"].append(r["observation_key"])
            rows["self"].append(False)
            rows["llr"].append(llr)
            rows["not_mate"].append(nm)
        elif k == "frame" and r.get("self") is not None:
            fp = fpos_of.get(int(r["frame_idx"]))
            if fp is None:
                continue
            rows["fpos"].append(fp)
            rows["cx"].append(float(r["self"][0]))
            rows["cy"].append(float(r["self"][1]))
            rows["reason"].append(None)
            rows["key"].append(f"{sid}:{r['frame_idx']}:self")
            rows["self"].append(True)
            rows["llr"].append(np.zeros(5))
            rows["not_mate"].append(False)
    fpos = np.asarray(rows["fpos"], np.int64)
    is_self = np.asarray(rows["self"], bool)
    o = np.lexsort((is_self, fpos))
    cx = np.asarray(rows["cx"], float)[o]
    cy = np.asarray(rows["cy"], float)[o]
    fpos, is_self = fpos[o], is_self[o]
    reason = np.asarray(rows["reason"], object)[o]
    llr = np.asarray(rows["llr"], float).reshape(-1, 5)[o]
    not_mate = np.asarray(rows["not_mate"], bool)[o]
    key = np.asarray(rows["key"], object)[o]
    mx, my = to_m(cx, cy)
    t = S.fr_t[fpos]
    # non-player reasons
    off, map_px = off_map_mask(sid, r_px)
    H, W = off.shape
    xi = np.clip(np.round(cx).astype(int), 0, W - 1)
    yi = np.clip(np.round(cy).astype(int), 0, H - 1)
    # the self fit too: off the map it draws no teammate, spectated or not
    flags = {"off_map": off[yi, xi],
             "ability_glyph": (reason == "interior_is_map") & ~is_self,
             "not_a_teammate": not_mate & ~is_self}
    near = 2.0 * r_px
    ping = np.zeros(cx.size, bool)
    open_ping = {}
    pings = []
    for r in sorted(st.read_events("ping", sid), key=lambda r: float(r["t_ms"])):
        if r.get("event_kind") == "entity_state" and r.get("position"):
            open_ping[r["entity_id"]] = (float(r["t_ms"]), r["position"])
        elif r.get("event_kind") == "entity_deleted" and r["entity_id"] in open_ping:
            t0, p = open_ping.pop(r["entity_id"])
            pings.append((t0, float(r["t_ms"]), p[0], p[1]))
    pings += [(t0, np.inf, p[0], p[1]) for t0, p in open_ping.values()]
    for t0, t1, px, py in pings:
        ping |= (t >= t0) & (t <= t1) & (np.hypot(cx - px, cy - py) <= near)
    flags["ping"] = ping & ~is_self
    spk = [(float(r["t_ms"]), g["cx"], g["cy"]) for r in st.read_events("spike", sid)
           if r.get("kind") == "frame" for g in (r.get("glyphs") or [])
           if g.get("state") == "dropped" and g.get("reason") is None]
    spike = np.zeros(cx.size, bool)
    if spk:
        ts = np.asarray([s[0] for s in spk])
        o2 = np.argsort(ts, kind="stable")
        ts = ts[o2]
        sx = np.asarray([s[1] for s in spk], float)[o2]
        sy = np.asarray([s[2] for s in spk], float)[o2]
        # the latest accepted glyph sample at or before each fit, within its 1 s step
        j = np.searchsorted(ts, t, side="right") - 1
        jc = np.clip(j, 0, None)
        same_t = ts[jc]
        # every glyph of that sample instant
        for d in range(0, 3):
            jj = np.clip(jc - d, 0, None)
            ok = (j - d >= 0) & (ts[jj] == same_t) & (t - same_t <= 1000.0)
            spike |= ok & (np.hypot(cx - sx[jj], cy - sy[jj]) <= near)
    flags["spike"] = spike & ~is_self
    start = np.searchsorted(fpos, np.arange(F + 1))
    return {"fpos": fpos, "start": start, "cx": cx, "cy": cy, "x": mx, "y": my, "t": t,
            "is_self": is_self, "reason": reason, "llr": llr, "key": key, "flags": flags,
            "map_px": map_px, "ref_names": names, "ref_cols": col,
            "margin_min": (refs or {}).get("margin_min"), "llr_unread": dict(nofeat),
            "references_version": (refs or {}).get("version")}


#: What the spectating witness rests on, declared with every result.
SPECTATE_RESTS_ON = ("tray_kit spectating witness (kit_agents_at lookahead 0 ms; each span's agent "
                     "pooled over the whole span: a post-round tray_kit verdict)")


def spectated_slots(sid: str, S, slots: list[dict], player_agent) -> dict:
    """(F,) slot index of the teammate whose kit the tray shows at each frame,
    -1 where it shows the player's kit or none, from the stored `tray_kit`
    rows (`stored_kit_witness`, `kit_agents_at`), with the witness's reason
    when it gives nothing.

    Causal per instant: a span holds from its first sample on
    (`lookahead_ms=0`, never the owner's default `KIT_LOOKAHEAD_MS`). Each
    span's agent, though, is the `tray_kit` arbiter's verdict pooled over the
    whole span, a post-round verdict; `rests_on` discloses it."""
    from reticle.adjudication.tray_kit import kit_agents_at, same_agent, stored_kit_witness
    from reticle.store import Store
    F = S.fr_t.size
    out = np.full(F, -1, np.int64)
    w = stored_kit_witness(Store(STORE).read_events("tray_kit", sid), agent=player_agent)
    if w.get("reason") or not w["spans"]:
        return {"slot": out, "reason": w.get("reason") or "no_spans", "version": w.get("version"),
                "rests_on": SPECTATE_RESTS_ON}
    agents = kit_agents_at(S.fr_t, w["spans"], lookahead_ms=0.0)
    by = {}
    for k, s in enumerate(slots):
        if s.get("agent"):
            by[str(s["agent"]).strip().lower().replace("/", "").replace("_", "")] = k
    for i, a in enumerate(agents):
        if a is None or same_agent(a, player_agent):
            continue
        k = by.get(str(a).strip().lower().replace("/", "").replace("_", ""))
        if k is not None:
            out[i] = k
    return {"slot": out, "reason": None, "version": w.get("version"), "own_basis": w.get("own_basis"),
            "rests_on": SPECTATE_RESTS_ON}


# ----------------------------------------------------------------- the causal loop

def causal_bind(t_ms: np.ndarray, fits: dict, open_: np.ndarray, seg_start: np.ndarray,
                player_slot, spect: np.ndarray, *, r_fit: float, v_max: float,
                log_area: float, r_dup_m: float, margin_min: float | None) -> dict:
    """Bind every frame's fits to slots, frame by frame, from what was bound
    before (module docstring). Returns (5, F) X, Y, has, how, wit, obs (the
    fit's flat index), the non-player bucket per fit and counts."""
    from reticle import track

    F = t_ms.size
    X = np.full((5, F), np.nan)
    Y = np.full((5, F), np.nan)
    has = np.zeros((5, F), bool)
    how = np.zeros((5, F), np.uint8)
    wit = np.zeros((5, F), np.uint8)
    obs = np.full((5, F), -1, np.int64)
    n_fits = fits["x"].size
    np_bucket = np.full(n_fits, "", object)
    bound_to = np.full(n_fits, -1, np.int64)
    fx, fy = fits["x"], fits["y"]
    llr = np.clip(fits["llr"], -LLR_CLIP, LLR_CLIP)
    bonus = np.zeros(n_fits)
    for r in NP_REASONS:
        bonus += np.where(fits["flags"][r], NP_BONUS[r], 0.0)
    np_cost = log_area + K_NP - bonus
    start = fits["start"]
    is_self = fits["is_self"]
    off_map = fits["flags"]["off_map"]
    mates = np.asarray([k != player_slot for k in range(5)])
    # per-slot state: last bound fit (any binding) for the motion prior
    px = np.zeros(5)
    py = np.zeros(5)
    tb = np.full(5, np.nan)
    E = np.zeros((5, 5))                                  # chain (row) evidence for slot (col)
    c = Counter()
    seg_prev = -1
    t0 = time.process_time()
    for k in range(F):
        if seg_start[k] != seg_prev:                      # a round opened: no slot is anchored
            tb[:] = np.nan
            E[:] = 0.0
            seg_prev = seg_start[k]
        op = open_[:, k]
        tb[~op] = np.nan                                  # a closed slot forgets its anchor
        E *= DECAY
        E[~op] = 0.0
        a, b = int(start[k]), int(start[k + 1])
        if a == b:
            continue
        idx = np.arange(a, b)
        free = op & mates
        # the self fit: bound directly while the player lives, or to the spectated slot
        sidx = idx[is_self[idx]]
        if sidx.size:
            i = int(sidx[0])
            target = None
            if player_slot is not None and op[player_slot]:
                target, h, w = player_slot, HOW_SELF, WITNESS_SELF
            elif off_map[i]:                              # background art: no teammate drawn
                c["self_off_map"] += 1
            elif spect[k] >= 0 and op[spect[k]] and free[spect[k]]:
                target, h, w = int(spect[k]), HOW_SPECTATE, WITNESS_SPECTATE
                c["self_spectate_bound"] += 1
            if target is not None:
                X[target, k], Y[target, k] = fx[i], fy[i]
                has[target, k] = True
                how[target, k], wit[target, k] = h, w
                obs[target, k] = i
                bound_to[i] = target
                px[target], py[target], tb[target] = fx[i], fy[i], t_ms[k]
                free[target] = False
                idx = idx[idx != i]
            else:
                c["self_offered_to_assignment"] += 1
        if not idx.size:
            continue
        cols = np.flatnonzero(free)
        n = idx.size
        cost = np.full((n, cols.size + n), np.inf)
        dt = (t_ms[k] - tb[cols]) / 1000.0
        anch = np.isfinite(tb[cols])
        R = v_max * np.where(anch, dt, 0.0) + r_fit
        sig = R / 2.0
        d = np.hypot(fx[idx][:, None] - px[cols][None, :], fy[idx][:, None] - py[cols][None, :])
        motion = np.where(anch[None, :], np.minimum(0.5 * (d / sig[None, :]) ** 2
                                                    + np.log(2 * np.pi * sig[None, :] ** 2),
                                                    log_area + K_RELOC), log_area)
        cost[:, :cols.size] = motion - W_ID * llr[idx][:, cols]
        cost[np.arange(n), cols.size + np.arange(n)] = np_cost[idx]
        got = track.assign(cost)
        inside = anch[None, :] & (d <= R[None, :])
        for r_, j in enumerate(got):
            i = int(idx[r_])
            if j < 0 or j >= cols.size:
                continue
            s = int(cols[j])
            X[s, k], Y[s, k] = fx[i], fy[i]
            has[s, k] = True
            obs[s, k] = i
            bound_to[i] = s
            how[s, k] = HOW_ASSIGNED_SPECTATED if is_self[i] else HOW_ASSIGNED
            others = np.delete(np.arange(cols.size), j)
            w = 0
            lead = (fits["llr"][i, s] - fits["llr"][i, cols[others]].max()
                    if others.size and fits["llr"][i].any() else 0.0)
            if margin_min is not None and lead >= margin_min:
                w = WITNESS_PORTRAIT
            elif (inside[r_, j] and anch[others].all() and not inside[r_, others].any()
                  and (margin_min is None or lead > -margin_min)):
                w = WITNESS_EXCLUSIVE
            wit[s, k] = w
            c[f"witness_{w}"] += 1
        for r_, j in enumerate(got):
            if j >= 0 and j < cols.size:
                continue
            i = int(idx[r_])
            why = next((r for r in NP_REASONS if fits["flags"][r][i]), None)
            if why is None:
                bx = X[:, k][has[:, k]]
                by_ = Y[:, k][has[:, k]]
                dup = bx.size and np.hypot(bx - fx[i], by_ - fy[i]).min() <= r_dup_m
                why = "duplicate" if dup else "unexplained"
            np_bucket[i] = why
        # the motion prior moves to this frame's bindings
        b_now = has[:, k]
        px[b_now], py[b_now], tb[b_now] = X[b_now, k], Y[b_now, k], t_ms[k]
        # each chain's portrait evidence, decayed; a chain whose evidence names
        # another slot's agent moves there (its motion state and evidence go
        # with it); the frames already bound stay where they were published
        ob = obs[:, k]
        lit = b_now & mates & (ob >= 0)
        if lit.any():
            E[lit] += llr[ob[lit]]
        cand = np.flatnonzero(op & mates)
        # a portrait witness stands only where its chain's evidence agrees
        pw = np.flatnonzero(wit[:, k] == WITNESS_PORTRAIT)
        if pw.size and cand.size >= 2:
            for s in pw:
                rest = cand[cand != s]
                if E[s, s] - E[s, rest].max() < CHAIN_MIN:
                    wit[s, k] = WITNESS_PORTRAIT_UNCONFIRMED
                    c["witness_3_unconfirmed"] += 1
        if cand.size >= 2:
            sub = E[np.ix_(cand, cand)]
            if (np.argmax(sub, axis=1) != np.arange(cand.size)).any():
                got = track.assign(-sub)
                gain = sub[np.arange(cand.size), got].sum() - np.trace(sub)
                if gain >= SWAP_MIN and sorted(got) == list(range(cand.size)):
                    dest = cand[np.asarray(got)]
                    px[dest], py[dest], tb[dest] = px[cand].copy(), py[cand].copy(), tb[cand].copy()
                    E[dest] = E[cand].copy()
                    c["chain_moves"] += int((dest != cand).sum())
                    c["chain_swaps"] += 1
    loop_s = time.process_time() - t0
    # B3: no frame binds one fit to two slots
    o = obs[obs >= 0]
    c["fit_bound_twice"] = int(o.size - np.unique(o).size)
    c["fits"] = int(n_fits)
    c["fits_bound"] = int((bound_to >= 0).sum())
    c["fits_offered"] = int(n_fits)
    fl = fits["flags"]
    return {"X": X, "Y": Y, "has": has, "how": how, "wit": wit, "obs": obs,
            "np_bucket": np_bucket, "bound_to": bound_to, "counts": dict(c),
            "np_by_reason": dict(Counter(b for b in np_bucket if b)),
            "flag_counts": {r: int(fl[r].sum()) for r in NP_REASONS},
            "loop_cpu_s": loop_s}
