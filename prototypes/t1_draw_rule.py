r"""The minimap's enemy draw rule on replay truth, corrected: persistence, smokes, death.

Task `t1-draw-rule-20261007` (rows TD1 in the store's
`notes/predictions.jsonl`). `coaching_questions.Match.drawn` (T1) draws an
enemy while a living capture-team player saw him within the last 1000 ms.
`enemy_lane_check` found that rule draws enemies the game does not: after
death, through smokes, and too long after the last sight. This prototype
measures the persistence and builds the corrected rule as a named option;
T1 stays the default of every `Match` and reproduces exactly.

**Persistence** (`persist`). Instances are stored `minimap_object` "?"
marks whose replaced icon sits in the read frame immediately before the
mark's first frame: the one-frame swap of [domain:minimap/last-known-mark-timing].
The enemy is the living truth enemy nearest the replaced icon (within
`NEAR_CM`, the next at least `NEAR_CM` farther). The swap's replay time is
the two frames' midpoint through `replay_truth.capture_to_replay` with the
killfeed clock and `REMOTE_LAG_MS` (replay-truth-0.4.0); the last sight is
the last instant any living capture-team player sees him (`episodes.sight`,
then the smoke filter below), refined from the 16 Hz grid to `FINE_MS`. The
persistence is swap less last sight; negative where sight outlasts the swap.

**Smokes** (`smokes`). Replay-layer children of the classes in `SMOKES`, each
a sphere at its spawn point with its own radius, delay and duration, read
from its ability's game-data fact or, where the fact is silent, the named
game file (never by analogy [domain:abilities/ability-rules-are-unique]). A
sight ray (eye to body centre, or eye to eye, as `episodes.sight` casts them)
whose segment passes within a live sphere's radius is blocked; both teams'
smokes block. `UNMODELLED` lists the vision blockers left out and why.

**Death.** A dead enemy is never drawn as an icon. `dead_mark` is its own
state: the enemy dead in the round after being drawn at his last living
sample [domain:minimap/enemy-death-mark].

**Rules** (`RULES`): `T1` (the old rule), `T1a` (alive only), `T1s` (alive,
smoke-blocked sight, P 1000 ms), `T1p` (alive, measured P, no smoke), `T1d`
(alive, smoke-blocked sight, measured P). `T1d` is the corrected rule; its P
is the median over the swaps the reader check keeps (`_clean`), and
`T1d_raw` takes the median over every swap, the registered design, which
reader misses of still-drawn icons pull down.

    python prototypes/t1_draw_rule.py smokes [MATCH ...]
    python prototypes/t1_draw_rule.py persist [SESSION ...]
    python prototypes/t1_draw_rule.py lane [SESSION ...] [--rules T1,T1a,...]
    python prototypes/t1_draw_rule.py truth [MATCH ...] [--rule T1d]
    python prototypes/t1_draw_rule.py report [--rule T1d]
    python prototypes/t1_draw_rule.py record

Stored data and replay truth only; no pixel is read. The held-out capture
(cea8ecbc94ab, replay bd7efa02) is refused by name. Outputs:
`<store>/analysis/t1-draw-rule-20261007/`. Not wired (`"wire": "no"`): an
evaluation over replay truth.
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

import coaching_questions as cq  # noqa: E402
import enemy_lane_check as elc  # noqa: E402
import real_reader_schedule as rrs  # noqa: E402
import replay_truth as rt  # noqa: E402
from reticle import episodes as ep  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "t1-draw-rule-0.1.0"
TASK = "t1-draw-rule-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
DEV = elc.DEV
NEAR_CM = 300.0
FINE_MS = 1000.0 / 128.0
LOOKBACK_MS = 5000.0       # a last sight further back is no instance (`no_sight`)
SWAP_MAX_MS = 100.0        # the icon frame and the "?" frame are consecutive read frames
BACK_MS = 2000.0           # instrument check: an icon read again at the "?" this soon
RENDER_BAND_MS = (30.0, 200.0)   # docs/RENDER_DELAY.md: the remote delay's band, prior 50 ms
RENDER_PRIOR_MS = 50.0
GF = "reference/game-files/release-13.06-shipping-18-5590001/ability-states/ShooterGame/Content/Characters"

#: class -> (ability, radius cm, delay ms, duration ms or None for "to the
#: child's close", source). Radius is the class's vision-blocking sphere.
SMOKES = {
    "Zone_Wraith_4_Smoke_C": ("omen:dark cover", 410.0, 300.0, 14700.0,
                              "game_data/omen-dark-cover-game-data"),
    "GameObject_Sarge_4_Smoke_ProductionNEW_C": ("brimstone:sky smoke", 410.0, 1000.0, 19250.0,
                                                 "game_data/brimstone-sky-smoke-game-data"),
    "GameObject_Rift_E_SmokeZone_C": ("astra:nebula", 475.0, 0.0, 15000.0,
                                      "game_data/astra-nebula-dissipate-game-data"),
    "GameObject_Rift_E_SmokeZone_Fake_C": (
        "astra:dissipate", 475.0, 0.0, 1750.0,
        "game_data/astra-nebula-dissipate-game-data (dissipate smoke duration); radius and delay: "
        f"{GF}/Rift/S0/Ability_E/GameObject_Rift_E_SmokeZone_Fake.json VisionBlockingSphere_GEN_VARIABLE "
        "RelativeScale3D 475 x 1 cm, SmokeDelayTime 0.0"),
    "GameObject_Smonk_NewSmoke_C": ("clove:ruse", 410.0, 1000.0, 13500.0, "game_data/clove-ruse-game-data"),
    "GameObject_Smonk_NewSmoke_PDS_C": (
        "clove:ruse after death", 410.0, 1000.0, 5500.0,
        "game_data/clove-ruse-game-data (post death smoke duration); "
        f"{GF}/Smonk/S0/Ability_E/MapTargetSmoke/GameObject_Smonk_NewSmoke_PDS.json: Super "
        "GameObject_Smonk_NewSmoke_C, overrides SmokeDuration only, so radius and delay are inherited"),
    "GameObject_Wushu_4_SmokeZone_C": (
        "jett:cloudburst", 335.0, 0.0, 2500.0,
        "game_data/jett-cloudburst-game-data; delay: "
        f"{GF}/Wushu/S0/Ability_4/GameObject_Wushu_4_SmokeZone.json Default__ SmokeDelayTime 0.0"),
    "GameObject_Iris_E_Smoke_C": ("miks:waveform", 410.0, 1000.0, 16250.0, "game_data/miks-waveform-game-data"),
    "GameObject_Pandemic_4_SmokeZone_C": (
        "viper:poison cloud", 470.0, 600.0, None,
        "game_data/viper-poison-cloud-game-data (smoke sphere radius, delay); the cloud toggles "
        "[domain:abilities/viper-poison-cloud-toggle], so it lasts to the zone child's close"),
    "Zone_Gumshoe_Q_Cage_C": (
        "cypher:cyber cage", 345.0, 350.0, 6400.0,
        "game_data/cypher-cyber-cage-game-data (cage radius, deploy, sustain); blocks minimap vision: "
        f"{GF}/Gumshoe/S0/Ability_Q/Zone_Gumshoe_Q_Cage.json carries a MinimapVisionConesBlockerCircle"),
}
#: Vision blockers seen in the replay layers and left out, with the reason.
UNMODELLED = {
    "Zone_Gumshoe_4_Cage_C": "a cage-like zone under an older build's class name (mapped to Trapwire); no 13.06 file values for this class",
    "GameObject_Phoenix_Q_FlameWallManager_Production_C": "Phoenix Blaze: a wall; the facts give its duration, not its shape",
    "GameObject_Pandemic_E_SmokeScreenManager_C": "Viper Toxic Screen: a wall; the facts give point spacing, not the wall's extent or toggling",
    "Patch_Pandemic_X_Circular_C": "Viper's Pit: blocks minimap cones (file) but no radius fact",
    "GameObject_Rift_X_GlobalWall_C": "Astra Cosmic Divide: a wall; no shape fact",
    "GameObject_Thorne_E_Wall_Segment_Fortifying_C": "Sage Barrier Orb: wall segments; no segment size fact",
    "GameObject_Sequoia_4_MovingCover_C": "Iso Contingency: a moving wall; no shape fact",
    "GameObject_Sequoia_4_MovingCover_Slower_C": "Iso Contingency: a moving wall; no shape fact",
}


def refuse(name: str) -> None:
    rrs.refuse(name)


def _log(msg: str) -> None:
    print(msg, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run.log").open("a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


# ----------------------------------------------------------------- smokes

def smoke_table(key: str) -> tuple[np.ndarray, list[dict]]:
    """Live smoke spheres of one match: rows (t_on, t_off, x, y, z, r) in
    replay ms and cm, sorted by t_on; and one dict per row (class, team)."""
    from reticle.replay_layer import load
    L = load(key)
    E = L.entities
    rows, meta = [], []
    for i in range(len(E["entity_id"])):
        c = E["class"][i]
        if c not in SMOKES:
            continue
        _ab, r, delay, dur, _src = SMOKES[c]
        a, b = E["t_open_rep"][i], E["t_close_rep"][i]
        x, y, z = E["spawn_x"][i], E["spawn_y"][i], E["spawn_z"][i]
        if a is None or x is None or not np.isfinite(a):
            continue
        on = float(a) + delay
        close = float(b) if b is not None and np.isfinite(b) else np.inf
        off = min(close, on + dur) if dur is not None else close
        if not np.isfinite(off) or off <= on:
            continue
        rows.append((on, off, float(x), float(y), float(z), r))
        meta.append({"class": c, "team": E["team"][i], "side_rel": E["side_rel"][i], "agent": E["agent"][i]})
    if not rows:
        return np.zeros((0, 6)), []
    o = np.argsort([r[0] for r in rows], kind="stable")
    return np.asarray(rows, float)[o], [meta[k] for k in o]


def seg_sphere(a: np.ndarray, b: np.ndarray, c: np.ndarray, r: float) -> np.ndarray:
    """True where segment a -> b (rows of xyz) passes within r of point c."""
    d = b - a
    L2 = (d * d).sum(-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.clip(((c - a) * d).sum(-1) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
    p = a + u[:, None] * d
    return ((p - c) ** 2).sum(-1) <= r * r


def smoke_filter(sees: np.ndarray, smp: dict, t: np.ndarray, occ, smokes: np.ndarray) -> np.ndarray:
    """`episodes.sight`'s answer with live smoke spheres blocking its rays.

    For each pair seen at a sample, each of the two rays `episodes.sight`
    casts (eye to body centre, eye to eye) is tested against the smokes live
    then. Both blocked: unseen. One blocked: seen only if the other target
    is in the frustum and clear of the map, asked of `episodes.frustum` and
    `occ.blocked` as `episodes.sight` asks them."""
    from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM
    out = sees.copy()
    if smokes.size == 0:
        return out
    I, J, K = np.nonzero(sees)
    if I.size == 0:
        return out
    o = np.argsort(K, kind="stable")
    I, J, K = I[o], J[o], K[o]
    tk = np.asarray(t, float)[K]
    X, Y, Z = smp["x"], smp["y"], smp["z"]
    eye = np.stack([X[I, K], Y[I, K], Z[I, K] + EYE_ABOVE_CENTRE_CM], 1)
    cen = np.stack([X[J, K], Y[J, K], Z[J, K]], 1)
    eyj = cen + np.array([0.0, 0.0, EYE_ABOVE_CENTRE_CM])
    bc = np.zeros(I.size, bool)
    be = np.zeros(I.size, bool)
    for on, off, x, y, z, r in smokes:
        lo, hi = np.searchsorted(tk, on, "left"), np.searchsorted(tk, off, "right")
        if hi <= lo:
            continue
        c = np.array([x, y, z])
        s = slice(lo, hi)
        bc[s] |= seg_sphere(eye[s], cen[s], c, r)
        be[s] |= seg_sphere(eye[s], eyj[s], c, r)
    both = bc & be
    out[I[both], J[both], K[both]] = False
    one = np.flatnonzero(bc ^ be)
    if one.size:
        tgt = np.where(bc[one, None], eyj[one], cen[one])
        ok = ep.frustum(smp["yaw"][I[one], K[one]], smp["pitch"][I[one], K[one]], tgt - eye[one],
                        ep.PARAMS["HFOV_DEG"])
        q = np.flatnonzero(ok)
        if q.size:
            ok[q] = ~occ.blocked(eye[one[q]], tgt[q])
        out[I[one], J[one], K[one]] = ok
    return out


# ----------------------------------------------------------------- rules

RULES = {
    "T1": {"alive": False, "smoke": False, "p_ms": None},
    "T1a": {"alive": True, "smoke": False, "p_ms": None},
    "T1s": {"alive": True, "smoke": True, "p_ms": None},
    "T1p": {"alive": True, "smoke": False, "p_ms": "smoke_clean"},
    "T1d": {"alive": True, "smoke": True, "p_ms": "smoke_clean"},
    "T1d_raw": {"alive": True, "smoke": True, "p_ms": "smoke"},
}


def measured_p_ms(which: str = "smoke_clean") -> float:
    """The measured persistence a rule uses: the pooled median of `persist`
    (`smoke_clean`: the swaps the reader check keeps; `smoke`: every
    measured swap, the registered design), rounded to the 16 Hz sight grid."""
    p = OUT / "persistence_summary.json"
    if not p.is_file():
        raise SystemExit("run `persist` first: no measured persistence")
    v = json.loads(p.read_text(encoding="utf-8"))["pooled"][which]["median_ms"]
    return float(round(v / cq.SIGHT_MS) * cq.SIGHT_MS)


class DrawRule:
    """A Match mixin: `drawn` follows `self.rule` (T1 by default, exactly
    `Match.drawn`); `dead_mark` is the X state, never drawn."""

    def __init__(self, key: str, rule: str = "T1", **kw):
        self.rule = rule
        super().__init__(key, **kw)
        self.smokes, self.smoke_meta = smoke_table(self.tl0.match)
        self._sees_s = None
        self._alive_g = None
        self._p_meas = None

    def sees_smoked(self) -> np.ndarray:
        if self._sees_s is None:
            smp = {"x": self.X, "y": self.Y, "z": self.Z, "yaw": self.YAW, "pitch": self.PITCH}
            self._sees_s = smoke_filter(self.sees, smp, self.G, self.occ, self.smokes)
        return self._sees_s

    def alive_grid(self) -> np.ndarray:
        if self._alive_g is None:
            self._alive_g = self.tl0._alive_fn(self.G)
        return self._alive_g

    def drawn(self, C: str, p_ms: float = cq.P_MS, sees=None) -> np.ndarray:
        R = RULES[self.rule]
        if self.rule == "T1":
            return super().drawn(C, p_ms, sees)
        if R["p_ms"] is not None:
            self._p_meas = measured_p_ms(R["p_ms"])
            p_ms = self._p_meas
        out = super().drawn(C, p_ms, self.sees_smoked() if R["smoke"] else None)
        if R["alive"]:
            out &= self.alive_grid()
        return out

    def dead_mark(self, C: str) -> np.ndarray:
        """dead_mark[j, k]: enemy j of team C's foes lies dead at k after being
        drawn (this rule) at his last living sample in the round."""
        al = self.alive_grid()
        dr = self.drawn(C)
        out = np.zeros_like(dr)
        for rn in np.unique(self.G_round):
            sl = np.flatnonzero(self.G_round == rn)
            for j in np.flatnonzero(self.team != C):
                a = al[j, sl]
                if a.all() or not a.any():
                    continue
                k0 = np.flatnonzero(a)[-1]
                if dr[j, sl[k0]]:
                    out[j, sl[k0 + 1:]] = ~a[k0 + 1:]
        return out


class DrawMatch(DrawRule, cq.Match):
    pass


class RealDrawMatch(DrawRule, rrs.RealMatch):
    pass


# ----------------------------------------------------------------- persistence

def _swaps(sid: str) -> tuple[list[dict], Counter]:
    """One-frame icon -> "?" swaps from the stored minimap_object rows."""
    refuse(sid)
    frames, head = [], None
    with (STORE / "events" / "minimap_object" / f"{sid}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("kind") == "frame":
                frames.append(r)
            elif r.get("kind") == "coverage":
                head = r
    scale = float(head["scale"])
    ICON_PX = float(head["parameters"]["ICON_PX"])
    t_all = np.array([r["t_ms"] for r in frames], float)
    by_t = {round(r["t_ms"], 1): r for r in frames}
    seen, out, why = set(), [], Counter()
    for n, r in enumerate(frames):
        if r.get("reason") is not None:
            continue
        for q in r.get("questions") or []:
            key = (q["icon_key"], round(q["onset_ms"], 1))
            if key in seen:
                continue
            seen.add(key)
            i_on = int(np.argmin(np.abs(t_all - q["onset_ms"])))
            if i_on == 0 or abs(t_all[i_on - 1] - q["icon_last_ms"]) > 0.5:
                why["not_one_frame"] += 1
                continue
            if q["onset_ms"] - q["icon_last_ms"] > SWAP_MAX_MS:
                why["frame_gap"] += 1
                continue
            tk, ix = q["icon_key"].split(":")
            g = by_t.get(round(float(tk), 1))
            if g is None or g.get("reason") is not None:
                why["icon_frame_missing"] += 1
                continue
            e = (g.get("enemies") or [])[int(ix)]
            # instrument checks: a refused enemy candidate at the "?" in its
            # first frame (a reader miss of a still-drawn icon), and how soon an
            # icon is read there again
            f_on = frames[i_on]
            near = ICON_PX * scale
            ref = [x for x in f_on.get("refused") or [] if x["cls"] == "enemy"
                   and np.hypot(x["x"] - q["x"], x["y"] - q["y"]) <= near]
            back = None
            for h in frames[i_on + 1:]:
                if h["t_ms"] - q["onset_ms"] > BACK_MS:
                    break
                if h.get("reason") is None and any(np.hypot(z["x"] - q["x"], z["y"] - q["y"]) <= near
                                                   for z in h.get("enemies") or []):
                    back = h["t_ms"] - q["onset_ms"]
                    break
            out.append({"icon_t": float(q["icon_last_ms"]), "q_t": float(q["onset_ms"]),
                        "icon_px": (float(e["x"]), float(e["y"])), "q_px": (float(q["x"]), float(q["y"])),
                        "refused_enemy_at_q": [x["reason"].split(" ")[0] for x in ref],
                        "icon_back_ms": None if back is None else round(back, 1)})
    why["one_frame_swaps"] = len(out)
    return out, why


def _fine_last(M, C: str, j: int, t_a: float, t_b: float, smoke: bool) -> float:
    """Last instant in [t_a, t_b] (t_a seen) at which a living C player sees
    enemy j, on a FINE_MS grid."""
    t = np.arange(t_a, t_b + 1e-6, FINE_MS)
    smp = M.tl0.sample(t)
    s = ep.sight(smp, M.slots, M.occ, ep.PARAMS["HFOV_DEG"])
    if smoke:
        s = smoke_filter(s, smp, t, M.occ, M.smokes)
    ci = np.flatnonzero(M.team == C)
    v = s[ci, j].any(axis=0)
    k = np.flatnonzero(v)
    return float(t[k[-1]]) if k.size else float(t_a)


def persist_match(sid: str) -> tuple[list[dict], dict]:
    from reticle.replay_source import to_px
    import entity_state as es
    refuse(sid)
    t0 = time.time()
    M = RealDrawMatch(sid, rule="T1")
    C = M.C
    ci, ei = M.ci, M.ei
    sw, why = _swaps(sid)
    (mf, to_m, _mpp), _w = es.world_frame(sid)
    upm = es.units_per_m()
    vis = {"geom": M.sees[ci].any(axis=0), "smoke": M.sees_smoked()[ci].any(axis=0)}
    rows = []
    for s in sw:
        t_icon = float(M.to_rep(s["icon_t"], rt.REMOTE_LAG_MS))
        t_sw = float(M.to_rep(0.5 * (s["icon_t"] + s["q_t"]), rt.REMOTE_LAG_MS))
        half = 0.5 * (s["q_t"] - s["icon_t"])
        smp = M.tl0.sample(np.array([t_icon]))
        mx, my = to_m(np.array([s["icon_px"][0]]), np.array([s["icon_px"][1]]))
        d = np.hypot(smp["x"][ei, 0] - mx[0] * upm, smp["y"][ei, 0] - my[0] * upm)
        d = np.where(np.isfinite(d) & smp["alive"][ei, 0], d, np.inf)
        o = np.argsort(d)
        rec = {"session": sid, "icon_t_cap": s["icon_t"], "q_t_cap": s["q_t"], "t_swap_rep": round(t_sw, 1),
               "half_frame_ms": round(half, 1), "refused_enemy_at_q": s["refused_enemy_at_q"],
               "icon_back_ms": s["icon_back_ms"]}
        if not np.isfinite(d[o[0]]) or d[o[0]] > NEAR_CM:
            rows.append(dict(rec, status="no_enemy_within_3m",
                             nearest_m=None if not np.isfinite(d[o[0]]) else round(float(d[o[0]]) / 100, 2)))
            continue
        if d.size > 1 and d[o[1]] < d[o[0]] + NEAR_CM:
            rows.append(dict(rec, status="ambiguous_enemy"))
            continue
        j = int(ei[o[0]])
        rec.update(j=j, agent=M.agent.get(M.sid[j]), icon_to_enemy_m=round(float(d[o[0]]) / 100, 2))
        if not M.tl0._alive_fn(np.array([t_sw]))[j, 0]:
            rows.append(dict(rec, status="dead_at_swap"))
            continue
        k = int(np.searchsorted(M.G, t_sw, side="right") - 1)
        if k < 0 or abs(M.G[k] - t_sw) > cq.SIGHT_MS:
            rows.append(dict(rec, status="outside_grid"))
            continue
        rn = M.G_round[k]
        rec["round"] = int(rn)
        out = dict(rec, status="measured")
        for name, V in vis.items():
            v = V[j]
            if v[k]:
                # sight outlasts the swap: the end of the run holding k
                e = k
                while e + 1 < v.size and v[e + 1] and M.G_round[e + 1] == rn:
                    e += 1
                t_end = _fine_last(M, C, j, M.G[e], M.G[min(e + 1, v.size - 1)], name == "smoke")
                out[f"{name}_ms"] = round(t_sw - t_end, 1)
                out[f"{name}_seen_at_swap"] = True
                continue
            kk = np.flatnonzero(v[:k + 1] & (M.G_round[:k + 1] == rn))
            if kk.size == 0 or t_sw - M.G[kk[-1]] > LOOKBACK_MS:
                out[f"{name}_ms"] = None
                out[f"{name}_why"] = "no_sight_within_5s"
                continue
            kl = int(kk[-1])
            t_end = _fine_last(M, C, j, M.G[kl], M.G[kl + 1], name == "smoke")
            out[f"{name}_ms"] = round(t_sw - t_end, 1)
            out[f"{name}_seen_at_swap"] = False
            if name == "smoke":
                # how sight ended: was the enemy in the last seer's frustum after it?
                t2 = np.array([t_end + FINE_MS])
                sp = M.tl0.sample(t2)
                from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM
                live = [i for i in ci if sp["alive"][i, 0]]
                inf = []
                for i in live:
                    dvec = np.array([sp["x"][j, 0] - sp["x"][i, 0], sp["y"][j, 0] - sp["y"][i, 0],
                                     sp["z"][j, 0] - sp["z"][i, 0] - EYE_ABOVE_CENTRE_CM])
                    inf.append(bool(ep.frustum(sp["yaw"][i, 0], sp["pitch"][i, 0], dvec[None, :],
                                               ep.PARAMS["HFOV_DEG"])[0]))
                out["in_some_frustum_after"] = any(inf)
                out["geom_still_seen"] = bool(vis["geom"][j, min(kl + 1, v.size - 1)])
        rows.append(out)
    info = {"session": sid, "team": C, "swaps": dict(why), "secs": round(time.time() - t0, 1),
            "smokes": len(M.smokes), "remote_lag_ms": rt.REMOTE_LAG_MS, "clock": M.clock}
    return rows, info


def _dist(v) -> dict:
    v = np.asarray([x for x in v if x is not None], float)
    if v.size == 0:
        return {"n": 0}
    return {"n": int(v.size), "median_ms": round(float(np.median(v)), 1),
            "p25_ms": round(float(np.percentile(v, 25)), 1), "p75_ms": round(float(np.percentile(v, 75)), 1),
            "p10_ms": round(float(np.percentile(v, 10)), 1), "p90_ms": round(float(np.percentile(v, 90)), 1),
            "share_negative": round(float((v < 0).mean()), 4),
            "share_le_50": round(float((v <= RENDER_PRIOR_MS).mean()), 4),
            "share_le_200": round(float((v <= RENDER_BAND_MS[1]).mean()), 4)}


#: Post hoc instrument filter, chosen after the first match's negatives were
#: read: a "?" with a refused enemy candidate at it in its first frame, or with
#: an icon read there again within CLEAN_BACK_MS, is likely the reader missing
#: a still-drawn icon (enemy_lane_check: teardrop refusals), not a swap.
CLEAN_BACK_MS = 250.0


def _clean(r: dict) -> bool:
    b = r.get("icon_back_ms")
    return not r.get("refused_enemy_at_q") and not (b is not None and b <= CLEAN_BACK_MS)


def _boot_median(v, n=2000, seed=20261007):
    v = np.asarray([x for x in v if x is not None], float)
    if v.size < 3:
        return None
    rng = np.random.default_rng(seed)
    b = np.median(v[rng.integers(0, v.size, (n, v.size))], axis=1)
    return [round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1)]


def run_persist(sessions: list[str]) -> int:
    cq._idle()
    OUT.mkdir(parents=True, exist_ok=True)
    allr, infos = [], {}
    for sid in sessions:
        rows, info = persist_match(sid)
        (OUT / f"persistence_{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                                                       encoding="utf-8")
        infos[sid] = info
        allr += rows
        _log(f"{sid}: persist {json.dumps(info)} status {dict(Counter(r['status'] for r in rows))}")
    summ = {"version": VERSION, "remote_lag_ms": rt.REMOTE_LAG_MS, "per_match": {}, "info": infos}
    for sid in sessions:
        m = [r for r in allr if r["session"] == sid and r["status"] == "measured"]
        summ["per_match"][sid] = {
            "status": dict(Counter(r["status"] for r in allr if r["session"] == sid)),
            "smoke": dict(_dist([r.get("smoke_ms") for r in m]), median_ci=_boot_median([r.get("smoke_ms") for r in m])),
            "geom": dict(_dist([r.get("geom_ms") for r in m]), median_ci=_boot_median([r.get("geom_ms") for r in m])),
            "smoke_clean": dict(_dist([r.get("smoke_ms") for r in m if _clean(r)]),
                                median_ci=_boot_median([r.get("smoke_ms") for r in m if _clean(r)])),
            "no_sight_smoke": sum(r.get("smoke_why") == "no_sight_within_5s" for r in m)}
    m = [r for r in allr if r["status"] == "measured"]
    pos = [r for r in m if r.get("smoke_ms") is not None and not r.get("smoke_seen_at_swap")]
    summ["pooled"] = {
        "status": dict(Counter(r["status"] for r in allr)),
        "smoke": dict(_dist([r.get("smoke_ms") for r in m]), median_ci=_boot_median([r.get("smoke_ms") for r in m])),
        "geom": dict(_dist([r.get("geom_ms") for r in m]), median_ci=_boot_median([r.get("geom_ms") for r in m])),
        "smoke_clean": dict(_dist([r.get("smoke_ms") for r in m if _clean(r)]),
                            median_ci=_boot_median([r.get("smoke_ms") for r in m if _clean(r)])),
        "geom_clean": dict(_dist([r.get("geom_ms") for r in m if _clean(r)])),
        "reader_check": dict(Counter(("refused_at_q" if r["refused_enemy_at_q"] else "no_refusal") + "|"
                                     + ("icon_back_le_250" if r["icon_back_ms"] is not None
                                        and r["icon_back_ms"] <= CLEAN_BACK_MS else "no_quick_return")
                                     + "|" + ("neg" if (r.get("smoke_ms") or 0) < 0 else "pos") for r in m)),
        "smoke_frustum_exit": dict(_dist([r["smoke_ms"] for r in pos if not r.get("in_some_frustum_after")])),
        "smoke_occluded_in_frustum": dict(_dist([r["smoke_ms"] for r in pos if r.get("in_some_frustum_after")])),
        "smoke_geom_still_seen": dict(_dist([r["smoke_ms"] for r in pos if r.get("geom_still_seen")]))}
    (OUT / "persistence_summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    print(json.dumps({k: summ[k] for k in ("per_match", "pooled")}, indent=1))
    return 0


# ----------------------------------------------------------------- the lane population

def run_lane(sessions: list[str], rules: list[str]) -> int:
    """enemy_lane_check's population (live read frames, dev matches) under
    each rule: drawn share, pair hit rate, extras rate; old and new."""
    cq._idle()
    out = {}
    for sid in sessions:
        refuse(sid)
        M = RealDrawMatch(sid, rule="T1")
        out[sid] = {}
        for rule in rules:
            M.rule = rule
            R = elc.build_sets(sid, M=M)
            P = R["pairs"]
            nh = sum(r["set"] == "hit" for r in P)
            nm = sum(r["set"] == "miss" for r in P)
            info = R["info"]
            dm = None
            if rule != "T1":
                dmk = M.dead_mark(M.C)
                dm = round(float(dmk[M.ei].any(axis=0).mean()), 4)
            out[sid][rule] = {"drawn_share": round(info["samples"]["t1_any"], 4),
                              "drawn_share_alive": round(info["samples"]["t1_any_alive"], 4),
                              "real_share": round(info["samples"]["real_any"], 4),
                              "hits": nh, "misses": nm, "hit_rate": round(nh / max(nh + nm, 1), 4),
                              "hit_rate_ci": elc._ci(nh, nh + nm),
                              "extras": info["extras"], "icons": info["icons_valid"],
                              "extras_rate": round(info["extras"] / max(info["icons_valid"], 1), 4),
                              "dead_mark_any_share_of_grid": dm,
                              "valid_live_samples": info["samples"]["valid_live_samples"],
                              "p_ms": measured_p_ms(RULES[rule]["p_ms"]) if RULES[rule]["p_ms"] else cq.P_MS}
            _log(f"{sid} {rule}: {json.dumps(out[sid][rule])}")
    p = OUT / "lane.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    for sid, v in out.items():
        old.setdefault(sid, {}).update(v)
    p.write_text(json.dumps(old, indent=1), encoding="utf-8")
    return 0


# ----------------------------------------------------------------- the truth sweep

TRUTH_ARMS = ["Lp0.5-250w5", "Lp1-250w5"]


def run_truth(keys: list[str], rule: str) -> int:
    """Gate onset and the degrade sweep (TRUTH_ARMS) on the replays under
    one rule; rows appended to truth_<rule>.jsonl and gate_<rule>.jsonl."""
    cq._idle()
    OUT.mkdir(parents=True, exist_ok=True)
    for key in keys:
        if key.startswith(cq.HELD_OUT_PREFIX):
            raise SystemExit("the held-out replay is never read")
        t0 = time.time()
        M = DrawMatch(key, rule=rule)
        tl = M.tl0
        rows = ep.read_episodes(tl.match)
        eps = [r for r in rows if r.get("row") == "episode"]
        team_of = {s.slot_id: s.team for s in tl.slots}
        idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
        go = cq.gate_onset_rows(M, key, tl, eps, team_of, idx)
        with (OUT / f"gate_{rule}.jsonl").open("a", encoding="utf-8") as f:
            for r in go:
                f.write(json.dumps(r, default=cq._jd) + "\n")
        sh = {C: float(M.drawn(C)[M.team != C].any(axis=0).mean()) for C in M.teams}
        cq.degrade_match(key, TRUTH_ARMS, OUT / f"truth_{rule}.jsonl", match_cls=lambda _k: M)
        _log(f"truth {rule} {key[:8]}: gate rows {len(go)}, drawn share {sh}, smokes {len(M.smokes)}, "
             f"{time.time() - t0:.0f} s")
    return 0


def truth_report(rule: str) -> dict:
    go = [json.loads(x) for x in (OUT / f"gate_{rule}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    rows = [json.loads(x) for x in (OUT / f"truth_{rule}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    P = cq.pooled(rows)
    keep = ("opening_first_seer", "spacing_death", "spacing_5m", "first_sight_support", "duel_C", "contact_C",
            "engagement_C", "trade_C", "execute_C", "rotation_C", "lurk_C")
    arms = {a: {"share": round(P[a]["share"], 4), "frame_share": round(P[a]["frame_share"], 4),
                "vs_T1": {q: P[a]["vs_T1"][q]["agree"] for q in keep if q in P[a]["vs_T1"]},
                "vs_T0": {q: P[a]["vs_T0"][q]["agree"] for q in keep if q in P[a]["vs_T0"]}}
            for a in TRUTH_ARMS if a in P}
    t1 = {q: P["T1"]["vs_T0"][q]["agree"] for q in keep if q in P.get("T1", {}).get("vs_T0", {})}
    shares = [r["drawn_share_of_live_grid"] for r in rows if r["arm"] == "T1"]
    return {"rule": rule, "matches": len({r["match"] for r in rows}), "gate_onset": cq.gate_onset_summary(go),
            "arms": arms, "T1_vs_T0": t1, "drawn_share_mean": round(float(np.mean(shares)), 4) if shares else None}


def run_smokes(keys: list[str]) -> int:
    """Census: smokes modelled and vision blockers left out, per match."""
    from reticle.replay_layer import load
    tot, left = Counter(), Counter()
    for key in keys:
        refuse(key)
        S, meta = smoke_table(key)
        for m in meta:
            tot[(m["class"], m["agent"])] += 1
        E = load(key).entities
        for c in E["class"]:
            if c in UNMODELLED:
                left[c] += 1
    out = {"modelled": {f"{c}|{a}": n for (c, a), n in sorted(tot.items())},
           "unmodelled": {c: {"children": n, "why": UNMODELLED[c]} for c, n in sorted(left.items())},
           "rules": {c: {"ability": v[0], "radius_m": v[1] / 100, "delay_s": v[2] / 1000,
                         "duration_s": None if v[3] is None else v[3] / 1000, "source": v[4]}
                     for c, v in SMOKES.items()}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "smokes.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def record_metrics() -> int:
    """Record the persistence, the lane comparison and the truth sweep in the
    metrics ledger, series `t1_draw_rule` (the old series stand untouched)."""
    from reticle.metrics import record as rec
    deps = {"version": VERSION, "episodes": ep.EPISODES_VERSION, "replay_truth": rt.REPLAY_TRUTH_VERSION,
            "remote_lag_ms": rt.REMOTE_LAG_MS, "smokes": sorted(SMOKES), "hfov_deg": ep.PARAMS["HFOV_DEG"]}
    ps = json.loads((OUT / "persistence_summary.json").read_text(encoding="utf-8"))
    for sid, v in list(ps["per_match"].items()) + [("dev3", ps["pooled"])]:
        vals = {}
        for k in ("smoke", "geom", "smoke_clean"):
            for a, b in v.get(k, {}).items():
                if isinstance(b, list):
                    vals[f"{k}.{a}_lo"], vals[f"{k}.{a}_hi"] = b
                elif b is not None:
                    vals[f"{k}.{a}"] = b
        rec("t1_draw_rule", part="persistence", session=sid, values=vals, deps=deps,
            context={"task": TASK, "status": v.get("status")},
            note="enemy icon -> '?' swap less the last smoke-blocked truth sight (ms); clean drops swaps with a "
                 "refused enemy at the '?' or an icon read there again within 250 ms")
    lane = json.loads((OUT / "lane.json").read_text(encoding="utf-8"))
    for sid, rules in lane.items():
        for rule, x in rules.items():
            rec("t1_draw_rule", part=f"lane/{rule}", session=sid,
                values={k: x[k] for k in ("drawn_share", "real_share", "hit_rate", "hits", "misses",
                                          "extras_rate", "extras", "icons", "p_ms")},
                deps=dict(deps, rule=RULES[rule]), context={"task": TASK, "population": "enemy_lane_check live read frames"})
    for rule in ("T1", "T1d"):
        if not (OUT / f"truth_{rule}.jsonl").is_file():
            continue
        R = truth_report(rule)
        sess = "pooled17" if R["matches"] >= 17 else f"pooled{R['matches']}"
        g = R["gate_onset"]
        rec("t1_draw_rule", part=f"truth/{rule}/gate_onset", session=sess,
            values={k: g[k] for k in ("n", "open_0", "open_250", "open_500", "local_open", "lead_ms_p50",
                                      "lead_ms_p10")},
            deps=dict(deps, rule=RULES[rule]), context={"task": TASK, "matches": R["matches"]})
        for arm, o in R["arms"].items():
            vals = {"share": o["share"], "frame_share": o["frame_share"]}
            vals.update({f"vs_T1.{q}": a for q, a in o["vs_T1"].items()})
            vals.update({f"vs_T0.{q}": a for q, a in o["vs_T0"].items()})
            rec("t1_draw_rule", part=f"truth/{rule}/{arm}", session=sess, values=vals,
                deps=dict(deps, rule=RULES[rule], arm=cq.ARMS[arm]), context={"task": TASK, "matches": R["matches"]})
        (OUT / f"truth_report_{rule}.json").write_text(json.dumps(R, indent=1), encoding="utf-8")
        print(json.dumps(R, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("smokes")
    a.add_argument("keys", nargs="*")
    b = sub.add_parser("persist")
    b.add_argument("sessions", nargs="*")
    c = sub.add_parser("lane")
    c.add_argument("sessions", nargs="*")
    c.add_argument("--rules", default="T1,T1a,T1s,T1p,T1d")
    d = sub.add_parser("truth")
    d.add_argument("keys", nargs="*")
    d.add_argument("--rule", default="T1d")
    e = sub.add_parser("report")
    e.add_argument("--rule", default="T1d")
    sub.add_parser("record")
    args = ap.parse_args(argv)
    if args.cmd == "record":
        return record_metrics()
    if args.cmd == "smokes":
        return run_smokes(args.keys or cq.replay_matches())
    if args.cmd == "persist":
        return run_persist(args.sessions or list(DEV))
    if args.cmd == "lane":
        return run_lane(args.sessions or list(DEV), args.rules.split(","))
    if args.cmd == "truth":
        return run_truth(args.keys or cq.replay_matches(), args.rule)
    print(json.dumps(truth_report(args.rule), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
