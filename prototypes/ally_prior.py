r"""Prior-first teammate reading: every ally icon continues from the last frame.

    .\.venv\Scripts\python.exe prototypes\ally_prior.py calibrate bdfdcf009dba
    .\.venv\Scripts\python.exe prototypes\ally_prior.py replay 9acf02f98283 [--record]
    .\.venv\Scripts\python.exe prototypes\ally_prior.py riot SESSION [SESSION ...] --pool NAME [--record]
    .\.venv\Scripts\python.exe prototypes\ally_prior.py price SESSION [--record]

Add `--events-from <copy of store/events>` before the command to read a
frozen copy of the stored streams.

Not wired (`"wire": "no"` in the store's `notes/predictions.jsonl`):
`AllyIconReader` (`reticle/minimap.py`) still searches every drawn frame.
This file simulates what a reader that starts from its prior would read,
lose and cost, on stored rows and the minimap crop cache, no decode.

The design (the player, 2026-10-04): "shouldn't the blob approach just be
based on priors? The only case where a blob could 'appear' would be if an
ability is cast or someone teleports, otherwise we basically see it
coming." AGENTS.md's rule: continue the prior; widen the search only on
surprise. Allies are always drawn on the minimap, so each one continues.

Per frame
---------
* **The key.** The reader's per-frame teal key (`minimap.ally_mask` on the
  floor), already paid by the reader; nothing here restates it.
* **The cheap check, per held teammate.** Two cues, vectorised over the
  teammates: `ally_rate`'s soft teal change (`Windows`, `teardrop.tealness`
  of 3x3-blurred windows, mean |dT| over a `DISC_R`-radius disc against the
  window of the last local fit, cut at `TAU`) and the icon-pose owner's ring
  presence (`teardrop.ring_cover` on the key at the predicted place, the
  last fit plus its motion, cut at `COVER_CUT`). Unchanged pixels hold the
  last pose: the teammate is `held`, `rests_on` its last fit. Changed pixels
  or a missing ring ask for a local fit.
* **A local fit** links the stored ring fits within `LINK_R` radii of the
  fired teammates' predictions (one assignment, `linear_sum_assignment`);
  the stored row stands for what the reader's prior-seeded fit returns. A
  fired teammate with no fit there is `cover` when the key still covers its
  predicted ring (team colour confirms it; no ring fit is needed to keep a
  track), else `predicted`, carried up to `CARRY_MS` from its last
  confirmation (`ally_rate`'s loss: a teammate missing from one read was
  dropped instead of carried), then lost.
* **Crowds** form when predicted icons come within one icon diameter
  (`2 r_out`) of each other or of the self fit: the members are exactly the
  tracks that converged, known from the prior, never searched. The crowd is
  one blob of the key (blurred and cut as `crowd_blob.FrameBlobs` does, in
  the crowd's own window); members' positions are the region, `rests_on`
  their entry fit; no per-member pose. The blob's centroid carries the
  members' predictions.
* **Separation.** The cheap split test on the crowd's blob (`elong` at one
  frame, the detector with the largest excess over chance in crowd-blob
  0.3.0, or two pieces, or the self fit parting) asks for local fits in the
  crowd's window. Emergers are assigned to members by continuity (the
  member's entry place carried with the blob and its entry heading against
  the emerger's bearing); `adjudication.identity`'s arbiter names each from
  the continuity claim (`depends_on` the member's entry entity, `rests_on`
  its entry fit) and the stored verdict of the fit's entity. An ambiguous
  continuity abstains; refusals stay refusals.
* **Surprise.** Keyed cells (the key shrunk with `INTER_AREA` to cells of
  one outer radius) that no prediction, crowd window, self fit or
  suppressed region explains are a surprise; only a surprise reads the
  frame in full (the stored ring fits). A fit no track continues spawns a
  track when the roster capacity licenses it (the owner
  `round_lifetimes.ally_capacity`, the round's last read carried forward
  when unread) and its blob's mass lies in the session's band (isolated
  ring fits' 5th-95th percentile, `crowd_blob.isolated_mass`); a surprise
  with no ring fit is non-ally teal (a barrier, an ability), suppressed for
  `SUPPRESS_MS`. Each spawn is explained against the round's start, the
  widget's return, a reacquired track and the stored ally casts and revives
  (`ult_cast`, `tray_drop`, `ability_state`, the death owner's
  `interval_revives`), or counted unexplained.
* **The audit.** A full read (ring fits and the stored stack fit) every
  `AUDIT_MS` at a fixed phase, stored apart; it never updates the prior.

Which abilities move or create an ally icon is not recorded as a fact:
`domain/abilities.toml` [domain:abilities/movement-abilities-are-dashes-and-teleports]
lists no teleports ("no list is recorded here"); the mechanics sheet's
candidates (wiki tag Teleport; each waits for the player) are
`TELEPORT_CANDIDATES`. The revives are recorded
[domain:rounds/resurrection-mechanics].

Scoring (truth is evaluation only; the reader reads pixels and stored rows)
--------------------------------------------------------------------------
`riot`: every living ally at each Riot kill instant: carried by the prior
(position error, name right), in a crowd region (strict and within one
radius, member set right), refused (located but unnamed) or lost; phantom
tracks with no Riot ally within one radius or the gate; the share of
frames that read nothing beyond the cheap check. The stored ring fits alone
are the baseline. `replay`: the same over every frame of a capture with a
replay, and the surprise log.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crowd_blob as cb  # noqa: E402  (pixels, blobs, isolated mass, split tests)
import crowd_region as v1  # noqa: E402  (stored-row Session, truth contexts)
from ally_rate import DISC_R, Windows  # noqa: E402  (the teal-change cue)

#: 0.1.0 (2026-10-04): the design fixed in the store's `notes/predictions.jsonl`
#: (task crowd-blobsplit-20261004, prior-first) before any truth was read.
#: 0.2.0 (development on the dev Riot handful, after its scores): a fit
#: the full roster blocks continues the track its stored verdict names, else
#: a weak prior, else the stalest held track; 0.1.0 tried only weak priors,
#: and 63 of 151 lost allies there had a stored ring fit the prior left.
ALLY_PRIOR_VERSION = "ally-prior-0.2.0"
STORE = v1.STORE
ANALYSIS = STORE / "analysis" / "ally-prior-20261004"

#: The teal-change cut (`ally_rate.TAU_HEAD`).
TAU = 0.10
#: Ring presence: `teardrop.ring_cover` (all bins, the key at 0.5) at or
#: above this share confirms a teammate (`calibrate` on bdfdcf009dba).
COVER_CUT = 0.15
#: A local fit links a stored ring fit within this many icon radii.
LINK_R = 2.5
#: A teammate unconfirmed this long is lost.
CARRY_MS = 1000.0
#: A gap between drawn frames longer than this reads the frame in full.
GAP_MS = 250.0
#: One icon diameter, in outer radii: predictions this close form a crowd.
CROWD_D_R = 2.0
#: A crowd's window: its members' box padded by this many outer radii.
WIN_PAD_R = 3.0
#: Surprise cells: keyed share of a one-outer-radius cell at or above this
#: (`calibrate`); a cell within EXPLAIN_R outer radii of a prediction, the
#: self fit or a crowd is explained.
CELL_LEVEL = 0.16
EXPLAIN_R = 2.0
#: Non-ally teal (a surprise with no ring fit) is suppressed this long.
SUPPRESS_MS = 3000.0
#: The fixed-in-advance audit (`ally_rate.AUDIT_MS`, its phase).
AUDIT_MS = 2070.0
AUDIT_PHASE_MS = 1100.0
#: A held split condition asks again for local fits every this many frames.
SPLIT_REFIRE = 5
#: Continuity: a member's heading weighs this much against its carried
#: place (in outer radii), and an assignment whose runner-up costs less
#: than MARGIN more abstains.
HEADING_W = 1.0
MARGIN = 0.5
#: A held teammate unfitted this long may give its place to a fit with no
#: prior when the roster is full (0.2.0).
STALE_MS = 3000.0
#: Surprise explanations: a spawn this close to the round's start, a
#: reacquired track lost this recently, an ally cast this recently.
SPAWN_MS = 3000.0
REACQ_MS = 5000.0
CAST_MS = 4000.0
#: Abilities that may move or create an ally icon, as candidates only
#: (docs/ABILITY_MECHANICS_SHEET.md, wiki tag Teleport or "returns to the
#: marker"; none recorded as a fact) and the recorded revives
#: [domain:rounds/resurrection-mechanics]. Only ultimates have a stored
#: cast for a teammate (`ult_cast`); a teammate's basic abilities have none.
TELEPORT_CANDIDATES = {"Omen": ("Shrouded Step", "From the Shadows"),
                       "Yoru": ("GATECRASH", "DIMENSIONAL DRIFT"),
                       "Chamber": ("Rendezvous",), "Phoenix": ("Run it Back",),
                       "Waylay": ("Crosscut",)}
REVIVE_AGENTS = ("Sage", "Phoenix", "Clove", "KAY/O")
STATUSES = ("fit", "held", "cover", "predicted", "crowd")


def _below_normal() -> None:
    cb._below_normal()


# ----------------------------------------------------------------- pixels

def reader_key(px: cb.Pixels, crop: np.ndarray) -> np.ndarray:
    """The ally-icon reader's per-frame teal key on the floor, as float."""
    from reticle.minimap import ally_mask
    return (ally_mask(crop) & px.floor).astype(np.float32)


def ring_cover_at(key: np.ndarray, xs, ys, r_in: float, r_out: float) -> np.ndarray:
    """The icon-pose owner's ring presence at each place (all bins)."""
    from reticle.teardrop import ring_cover
    return np.asarray([ring_cover(key, float(x), float(y), 0.0, r_in, r_out, away_deg=0.0)
                       for x, y in zip(xs, ys)], float)


class Cells:
    """The key shrunk to cells of one outer radius (`INTER_AREA`)."""

    def __init__(self, shape, r_out: float):
        H, W = shape
        g = max(1, int(round(r_out)))          # a whole number of pixels: the fast path
        self.g = g
        self.nx, self.ny = max(1, W // g), max(1, H // g)
        self.sx = self.sy = float(g)
        gx = (np.arange(self.nx) + 0.5) * g
        gy = (np.arange(self.ny) + 0.5) * g
        self.gy, self.gx = np.meshgrid(gy, gx, indexing="ij")

    def of(self, key: np.ndarray) -> np.ndarray:
        g = self.g
        return cv2.resize(key[:self.ny * g, :self.nx * g], (self.nx, self.ny),
                          interpolation=cv2.INTER_AREA)

    def near(self, xs, ys, r: float) -> np.ndarray:
        """Cells whose centre lies within `r` of any point."""
        m = np.zeros(self.gx.shape, bool)
        if len(xs):
            P = np.stack([np.asarray(xs, float), np.asarray(ys, float)], 1)
            d2 = ((self.gx[..., None] - P[:, 0]) ** 2 + (self.gy[..., None] - P[:, 1]) ** 2)
            m = (d2 <= r * r).any(axis=-1)
        return m


def window_blob(px: cb.Pixels, key: np.ndarray, box, at) -> dict | None:
    """The blob of the key (blurred, cut once, as `crowd_blob.FrameBlobs`)
    in a window, nearest `at`: its filled mask, centroid, mass, pieces of
    at least `piece` mass in the window, elongation and outline."""
    H, W = key.shape
    x0, y0, x1, y1 = (int(max(0, box[0])), int(max(0, box[1])),
                      int(min(W, box[2])), int(min(H, box[3])))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    C = key[y0:y1, x0:x1]
    D = cv2.GaussianBlur(C, (0, 0), px.sigma)
    M = (D > px.level["mask"]).astype(np.uint8)
    n, lbl, st, cen = cv2.connectedComponentsWithStats(M, connectivity=8)
    if n < 2:
        return None
    on = C > 0
    mass = np.bincount(lbl[on], weights=C[on], minlength=n)
    ax, ay = at[0] - x0, at[1] - y0
    d = np.hypot(cen[1:, 0] - ax, cen[1:, 1] - ay)
    # the label under `at`, else the nearest centroid within two outer radii
    lx, ly = int(np.clip(round(ax), 0, x1 - x0 - 1)), int(np.clip(round(ay), 0, y1 - y0 - 1))
    j = int(lbl[ly, lx])
    if j == 0:
        j = int(np.argmin(d)) + 1
        if d[j - 1] > 2 * px.shape.r_out:
            return None
    m = cb.filled(lbl, j)
    mo = cv2.moments(m, binaryImage=True)
    el = float(cb.elongation(mo["mu20"], mo["mu02"], mo["mu11"])) if mo["m00"] > 0 else 1.0
    return {"j": j, "mask": m, "x0": x0, "y0": y0, "cx": float(cen[j, 0] + x0),
            "cy": float(cen[j, 1] + y0), "mass": float(mass[j]), "masses": mass[1:],
            "elong": el, "box": [int(st[j, 0] + x0), int(st[j, 1] + y0),
                                 int(st[j, 0] + st[j, 2] + x0), int(st[j, 1] + st[j, 3] + y0)]}


def outline(b: dict) -> np.ndarray | None:
    cs, _h = cv2.findContours(b["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    return (max(cs, key=cv2.contourArea).reshape(-1, 2)
            + np.array([b["x0"], b["y0"]])).astype(np.float32)


# ----------------------------------------------------------------- stored rows

def stored_casts(sid: str) -> dict:
    """Ally ultimate casts (`ult_cast`), the player's own drops (`tray_drop`,
    `ability_state` verdicts) and revive instants from the death owner."""
    ev = v1.EVENTS
    out = {"ult": [], "own": [], "revive": []}
    p = ev / "ult_cast" / f"{sid}.jsonl"
    if not p.exists():
        p = STORE / "events" / "ult_cast" / f"{sid}.jsonl"
    for r in v1._rows(p, '"cast"'):
        if r.get("kind") == "cast" and r.get("side") == "ally":
            out["ult"].append((float(r["t_ms"]), r.get("agent")))
    for name in ("tray_drop", "ability_state"):
        p = STORE / "events" / name / f"{sid}.jsonl"
        if p.exists():
            for r in v1._rows(p):
                if r.get("kind") in ("drop", "verdict") and r.get("t_ms") is not None:
                    out["own"].append((float(r["t_ms"]), r.get("slot")))
    p = ev / "death" / f"{sid}.jsonl"
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for line in f:
                for m in re.finditer(r'"interval_revives":\[([^\]]*)\]', line):
                    out["revive"] += [float(v) for v in m.group(1).split(",") if v.strip()]
    out["revive"] = sorted(set(out["revive"]))
    return out


def barrier_rows(sid: str) -> dict:
    """frame_idx -> (x, y) of the reader's own barrier rows (`family`
    barrier: the spawn barriers its ring search refuses every frame)."""
    out = defaultdict(list)
    for r in v1._rows(v1.EVENTS / "ally_icon" / f"{sid}.jsonl", '"family":"barrier"'):
        if r.get("kind") == "icon" and r.get("family") == "barrier":
            out[int(r["frame_idx"])].append((float(r["cx"]), float(r["cy"])))
    return out


# ----------------------------------------------------------------- the reader

class Track:
    __slots__ = ("id", "x", "y", "vx", "vy", "t_fit", "t_conf", "key", "e", "name", "ref",
                 "crowd", "entry", "status", "born", "how")

    def __init__(self, tid, x, y, t, key, e, name, ref, how):
        self.id, self.x, self.y, self.vx, self.vy = tid, x, y, 0.0, 0.0
        self.t_fit = self.t_conf = self.born = t
        self.key, self.e, self.name, self.ref, self.how = key, e, name, ref, how
        self.crowd, self.entry, self.status = None, None, "fit"

    def fit(self, x, y, t, key, e, ref):
        dt = (t - self.t_fit) / 1000.0
        if 0 < dt <= 0.5:
            self.vx, self.vy = (x - self.x) / dt, (y - self.y) / dt
        else:
            self.vx = self.vy = 0.0
        self.x, self.y, self.t_fit, self.t_conf, self.key, self.e, self.ref = x, y, t, t, key, e, ref
        self.status = "fit"

    def predict(self, t, cap_px):
        dt = (t - self.t_fit) / 1000.0
        dx, dy = self.vx * dt, self.vy * dt
        n = math.hypot(dx, dy)
        if n > cap_px:
            dx, dy = dx * cap_px / n, dy * cap_px / n
        return self.x + dx, self.y + dy


def run_session(S, px: cb.Pixels, iso: dict, *, S_all=None, timing: bool = True,
                rounds=None) -> dict:
    """The prior-first reader over one session's rounds. Returns per-frame
    track rows, crowd rows, surprises, emergences, audits, decisions,
    guards and cost."""
    from reticle.adjudication.identity import AgentIdentityArbiter, identity_claim
    from reticle.round_lifetimes import ally_capacity, roster_window

    r_out, r_in = px.shape.r_out, px.shape.r_in
    r = float(S.r)
    link = LINK_R * r
    crowd_d = CROWD_D_R * r_out
    win = Windows(int(math.ceil(DISC_R * r)))
    cells = None
    slab = px.slab.astype(np.float32)
    idx = cb.frame_clock(S, px)
    fpos = np.searchsorted(S.ob_f, S.fr_f, side="left")
    fend = np.searchsorted(S.ob_f, S.fr_f, side="right")
    if S_all is not None:
        apos = np.searchsorted(S_all.ob_f, S.fr_f, side="left")
        aend = np.searchsorted(S_all.ob_f, S.fr_f, side="right")
    band = (iso["p05"], iso["p95"])
    piece_mass = cb.SPLIT_PIECE * iso["mass"]
    casts = stored_casts(S.sid)
    barriers = barrier_rows(S.sid)
    deaths = sorted((d for d in S.deaths if d.get("side") == "ally"), key=lambda d: d["t_ms"])
    d_t = np.asarray([d["t_ms"] for d in deaths], float)
    rows, crowd_rows, surprises, emergences, audits = [], [], [], [], []
    decisions = Counter()
    frame_kind = {}
    guard = Counter()
    over = []
    cost = defaultdict(float)
    nid = [0]
    for rd in (rounds or S.rounds):
        t0r, t1r = rd["t_start_ms"], rd["t_end_ms"]
        ks = idx[(S.fr_t[idx] >= t0r) & (S.fr_t[idx] <= t1r)]
        if not ks.size:
            continue
        tracks: list[Track] = []
        lost: list[Track] = []
        crowds: dict[str, dict] = {}
        suppress: list[tuple[np.ndarray, float]] = []
        cap_last = None
        prev_t = None
        audit_next = t0r + AUDIT_PHASE_MS
        crop_iter = px.crops(S.fr_t[ks])
        for k in ks:
            _tc, crop = next(crop_iter)
            t = float(S.fr_t[k])
            fidx = int(S.fr_f[k])
            T = [time.perf_counter()]
            key = reader_key(px, crop)
            if cells is None:
                cells = Cells(key.shape, r_out)
            T.append(time.perf_counter())                                 # key
            a, b = fpos[k], fend[k]
            sf = S.ob_self[a:b]
            fx, fy = S.ob_x[a:b][~sf], S.ob_y[a:b][~sf]
            fe, fk = S.ob_e[a:b][~sf], S.ob_key[a:b][~sf]
            self_xy = ((float(S.ob_x[a:b][sf][0]), float(S.ob_y[a:b][sf][0]))
                       if sf.any() else None)
            self_key = S.ob_key[a:b][sf][0] if sf.any() else None
            cap = ally_capacity(roster_window(S.roster_t, S.roster_a, t), self_xy is not None)
            cap_read = cap is not None
            if cap_read:
                cap_last = (cap, t)
            elif cap_last is not None:
                cap = cap_last[0]          # carried, resting on the last read
            used = np.zeros(fx.size, bool)          # stored fits a track took this frame
            kind = "cheap"
            gap = prev_t is not None and t - prev_t > GAP_MS
            # deaths the killfeed names end that teammate's track
            if d_t.size and prev_t is not None:
                lo, hi = np.searchsorted(d_t, [prev_t, t], side="right")
                for d in deaths[lo:hi]:
                    for tr in list(tracks):
                        if tr.name is not None and tr.name == d.get("victim"):
                            _end(tr, tracks, crowds, lost, t, "death_named")
            # ---- the cheap check on teammates outside crowds
            free = [tr for tr in tracks if tr.crowd is None]
            fired = np.zeros(len(free), bool)
            if free and not gap:
                lx = np.asarray([tr.x for tr in free])
                ly = np.asarray([tr.y for tr in free])
                now = win.teal(crop, lx, ly)
                fired = win.score(now, np.stack([tr.ref for tr in free])) > TAU
            T.append(time.perf_counter())                                 # cue
            for tr, f_ in zip(free, fired):
                if not f_:
                    tr.status, tr.t_conf = "held", t
            # ---- local fits for the fired
            q = np.flatnonzero(fired)
            if q.size:
                kind = "local"
                decisions["local_fit_icons"] += int(q.size)
                pr = np.asarray([free[i].predict(t, link) for i in q])
                if fx.size:
                    Dm = np.hypot(pr[:, None, 0] - fx[None], pr[:, None, 1] - fy[None])
                    big = 1e6
                    Dg = np.where(Dm <= link, Dm, big)
                    ri, ci = linear_sum_assignment(Dg)
                    ok = Dg[ri, ci] < big
                    ri, ci = ri[ok], ci[ok]
                else:
                    ri = ci = np.zeros(0, int)
                got = set()
                for i_, j_ in zip(ri.tolist(), ci.tolist()):
                    tr = free[q[i_]]
                    ref = win.teal(crop, fx[j_:j_ + 1], fy[j_:j_ + 1])[0]
                    tr.fit(float(fx[j_]), float(fy[j_]), t, fk[j_], int(fe[j_]), ref)
                    _rename(tr, S, int(fe[j_]))
                    used[j_] = True
                    got.add(int(q[i_]))
                miss = [free[i_] for i_ in q.tolist() if i_ not in got]
                T.append(time.perf_counter())                             # local
                if miss:
                    # changed pixels and no fit: the owner's ring presence at the
                    # prediction keeps the teammate (team colour), else it is carried
                    pr = [tr.predict(t, link) for tr in miss]
                    cover = ring_cover_at(key, [p_[0] for p_ in pr], [p_[1] for p_ in pr],
                                          r_in, r_out)
                    for tr, cv_ in zip(miss, cover):
                        if cv_ >= COVER_CUT:
                            tr.status, tr.t_conf = "cover", t
                        else:
                            tr.status = "predicted"
                        if t - tr.t_conf > CARRY_MS:
                            _end(tr, tracks, crowds, lost, t, "lost")
            else:
                T.append(time.perf_counter())
            T.append(time.perf_counter())                                 # cover
            # ---- crowds: the blob, the split test, emergence
            for cid in list(crowds):
                c = crowds[cid]
                mem = [tr for tr in tracks if tr.crowd == cid]
                if len(mem) < 1:
                    del crowds[cid]
                    continue
                pad = WIN_PAD_R * r_out
                bx = c["box"]
                box = (bx[0] - pad, bx[1] - pad, bx[2] + pad, bx[3] + pad)
                blob = window_blob(px, key, box, (c["cx"], c["cy"]))
                self_in = self_xy is not None and math.hypot(self_xy[0] - c["cx"],
                                                             self_xy[1] - c["cy"]) <= crowd_d
                T.append(time.perf_counter())
                cost["crowd_blobs"] += T[-1] - T[-2]
                if blob is None and not self_in:
                    # the blob is gone: members carried, then lost
                    for tr in mem:
                        tr.crowd, tr.status = None, "predicted"
                        tr.x, tr.y, tr.vx, tr.vy, tr.t_fit = c["cx"], c["cy"], 0.0, 0.0, t
                    crowd_rows.append({"crowd": cid, "t": t, "fidx": fidx, "end": "vanished"})
                    del crowds[cid]
                    continue
                if blob is not None:
                    c["cx"], c["cy"], c["box"] = blob["cx"], blob["cy"], blob["box"]
                    c["mass"] = blob["mass"]
                    for tr in mem:
                        tr.t_conf = t
                elif self_in:
                    c["cx"], c["cy"] = self_xy
                    for tr in mem:
                        tr.t_conf = t
                # the split test (cheap): elongation at one frame, two pieces, the self parting
                pieces = int((blob["masses"] >= piece_mass).sum()) if blob is not None else 0
                cond = (blob is not None and (blob["elong"] > px.elong_level or pieces >= 2))
                # the test fires as its condition rises, and again every
                # SPLIT_REFIRE frames while it holds (a slow parting)
                c["run"] = c.get("run", 0) + 1 if cond else 0
                split = cond and (c["run"] - 1) % SPLIT_REFIRE == 0
                self_parted = c["self"] and not self_in
                c["self_off"] = c.get("self_off", 0) + 1 if self_parted else 0
                split = split or c["self_off"] >= cb.SELF_HOLD
                if c["self_off"] >= cb.SELF_HOLD:
                    c["self"] = False
                T.append(time.perf_counter())
                cost["split_tests"] += T[-1] - T[-2]
                poly = outline(blob) if blob is not None else None
                T.append(time.perf_counter())
                cost["outlines"] += T[-1] - T[-2]
                crowd_rows.append({"crowd": cid, "t": t, "fidx": fidx, "cx": c["cx"], "cy": c["cy"],
                                   "poly": poly, "self": bool(c["self"]),
                                   "members": [tr.id for tr in mem],
                                   "names": [tr.name for tr in mem], "split": bool(split)})
                if split:
                    kind = "split"
                    decisions["split_tests_fired"] += 1
                    em = _emerge(c, mem, fx, fy, fe, fk, used, t, fidx, S, win, crop, crowd_d,
                                 r_out, emergences, AgentIdentityArbiter, identity_claim)
                    decisions["local_fit_icons"] += em
                # one member left and no self: the crowd dissolves into its track,
                # at the nearest free fit or, failing one, the blob (team colour)
                mem = [tr for tr in tracks if tr.crowd == cid]
                if not mem or (len(mem) == 1 and not c["self"]):
                    for tr in mem:
                        _dissolve(tr, c, fx, fy, fe, fk, used, t, S, win, crop, link)
                    crowd_rows.append({"crowd": cid, "t": t, "fidx": fidx, "end": "dissolved"})
                    del crowds[cid]
                T.append(time.perf_counter())
                cost["emergence"] += T[-1] - T[-2]
            T.append(time.perf_counter())
            # ---- crowd formation: predictions within one diameter (and the self)
            free = [tr for tr in tracks if tr.crowd is None]
            if free:
                P = np.asarray([tr.predict(t, link) for tr in free])
                if len(free) > 1:
                    Dm = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])
                    np.fill_diagonal(Dm, np.inf)
                else:
                    Dm = np.full((1, 1), np.inf)
                near_self = (np.hypot(P[:, 0] - self_xy[0], P[:, 1] - self_xy[1]) <= crowd_d
                             if self_xy is not None else np.zeros(len(free), bool))
                # joins: a free teammate inside a crowd's blob box
                for i_, tr in enumerate(free):
                    for cid, c in crowds.items():
                        if math.hypot(P[i_, 0] - c["cx"], P[i_, 1] - c["cy"]) <= crowd_d:
                            _enter(tr, c, P[i_], t, S, self_key)
                            break
                free2 = [i_ for i_, tr in enumerate(free) if tr.crowd is None]
                adj = (Dm <= crowd_d)
                seen = set()
                for i_ in free2:
                    if i_ in seen:
                        continue
                    comp, stack_ = [], [i_]
                    while stack_:
                        u = stack_.pop()
                        if u in seen or free[u].crowd is not None:
                            continue
                        seen.add(u)
                        comp.append(u)
                        stack_ += [v for v in np.flatnonzero(adj[u]).tolist() if v not in seen]
                    if len(comp) >= 2 or (len(comp) == 1 and near_self[comp[0]]):
                        cid = f"{S.sid}:R{rd['round_no']}:P{nid[0]:03d}"
                        nid[0] += 1
                        xs_ = [P[u, 0] for u in comp] + ([self_xy[0]] if near_self[comp].any() else [])
                        ys_ = [P[u, 1] for u in comp] + ([self_xy[1]] if near_self[comp].any() else [])
                        c = {"id": cid, "onset": t, "cx": float(np.mean(xs_)), "cy": float(np.mean(ys_)),
                             "box": [min(xs_) - r_out, min(ys_) - r_out, max(xs_) + r_out,
                                     max(ys_) + r_out], "self": bool(near_self[comp].any())}
                        crowds[cid] = c
                        for u in comp:
                            _enter(free[u], c, P[u], t, S, self_key)
                        crowd_rows.append({"crowd": cid, "t": t, "fidx": fidx, "opened": True,
                                           "members": [free[u].id for u in comp]})
            T.append(time.perf_counter())
            cost["formation"] += T[-1] - T[-2]
            # ---- surprise: keyed cells nothing explains; only then a full read
            G = cells.of(key * slab)
            pts = [(tr.x, tr.y) for tr in tracks if tr.crowd is None]
            pts += [tr.predict(t, link) for tr in tracks if tr.crowd is None]
            pts += [(c["cx"], c["cy"]) for c in crowds.values()]
            if self_xy is not None:
                pts.append(self_xy)
            pts += barriers.get(fidx, [])
            expl = cells.near([p_[0] for p_ in pts], [p_[1] for p_ in pts], EXPLAIN_R * r_out)
            for c in crowds.values():
                bx = c["box"]
                expl |= ((cells.gx >= bx[0] - r_out) & (cells.gx <= bx[2] + r_out)
                         & (cells.gy >= bx[1] - r_out) & (cells.gy <= bx[3] + r_out))
            suppress = [(m_, u_) for m_, u_ in suppress if u_ > t]
            for m_, _u in suppress:
                expl |= m_
            hot = (G >= CELL_LEVEL) & ~expl
            T.append(time.perf_counter())
            cost["surprise_cells"] += T[-1] - T[-2]
            first = prev_t is None
            if first or gap or hot.any():
                why = "round_start" if first else "gap" if gap else "unexplained_teal"
                kind = "surprise"
                decisions["full_reads"] += 1
                decisions["full_" + why] += 1
                _full_read(S, px, key, tracks, crowds, lost, fx, fy, fe, fk, used, t, fidx, why,
                           hot, cells, cap, cap_last, band, win, crop, rd, casts, surprises,
                           suppress, guard, nid, t0r, link, emergences)
            T.append(time.perf_counter())
            cost["surprise_read"] += T[-1] - T[-2]
            # ---- the roster cap: never more tracks than the capacity licenses
            # (a read capacity evicts the stalest, longest unfitted first; a
            # carried one never evicts)
            if cap is not None and len(tracks) > cap:
                guard["over_capacity_frames"] += 1
                if len(over) < 40:
                    over.append((round(t), cap, cap_last[1] if cap_last else None,
                                 [(tr.name, tr.status, tr.crowd is not None, round(tr.born))
                                  for tr in tracks]))
                if cap_read:
                    for tr in sorted(tracks, key=lambda tr: tr.t_fit)[:len(tracks) - cap]:
                        guard["capacity_evicted"] += 1
                        _end(tr, tracks, crowds, lost, t, "evicted_capacity")
            # ---- the audit, stored apart
            if t >= audit_next:
                audit_next += AUDIT_MS * max(1, math.floor((t - audit_next) / AUDIT_MS) + 1)
                audits.append(_audit(S_all if S_all is not None else S,
                                     (apos[k], aend[k]) if S_all is not None else (a, b),
                                     tracks, crowds, t, fidx, r, link))
            frame_kind[fidx] = kind
            decisions[kind] += 1
            for tr in tracks:
                st_ = "crowd" if tr.crowd is not None else tr.status
                x_, y_ = (tr.predict(t, link) if st_ in ("cover", "predicted")
                          else (tr.x, tr.y))
                rows.append((fidx, t, tr.id, tr.name, x_, y_, STATUSES.index(st_),
                             tr.crowd or "", tr.key))
            if timing:
                cost["key"] += T[1] - T[0]
                cost["cue"] += T[2] - T[1]
                cost["local"] += T[3] - T[2]
                cost["cover"] += T[4] - T[3]
                cost["frames"] += 1
            prev_t = t
        for tr in list(tracks):
            _end(tr, tracks, crowds, lost, t1r, "round_end")
    return {"rows": rows, "crowd_rows": crowd_rows, "surprises": surprises,
            "emergences": emergences, "audits": audits, "decisions": dict(decisions),
            "frame_kind": frame_kind, "guard": dict(guard), "cost_s": dict(cost),
            "frames": int(idx.size), "r": r, "r_out": r_out, "iso": iso, "over_capacity": over}


def _rename(tr: Track, S, e: int) -> None:
    """A fit's stored entity verdict names the track where it names anyone;
    otherwise the track keeps its name, resting on its earlier fit."""
    a = S.agent[e]
    if a is not None:
        tr.name = a


def _enter(tr: Track, c: dict, P, t, S, self_key) -> None:
    tr.crowd = c["id"]
    tr.entry = {"x": float(P[0]), "y": float(P[1]), "t": t, "key": tr.key,
                "entity": S.ent_ids[tr.e] if tr.e >= 0 else None, "vx": tr.vx, "vy": tr.vy,
                "cx": c["cx"], "cy": c["cy"], "self_key": self_key if c.get("self") else None}


def _end(tr: Track, tracks, crowds, lost, t, how) -> None:
    if tr in tracks:
        tracks.remove(tr)
        tr.status = how
        tr.t_conf = t
        tr.crowd = None
        lost.append(tr)


def _dissolve(tr: Track, c, fx, fy, fe, fk, used, t, S, win, crop, link) -> None:
    free_ = np.flatnonzero(~used)
    tr.crowd = None
    if free_.size:
        d = np.hypot(fx[free_] - c["cx"], fy[free_] - c["cy"])
        j = int(np.argmin(d))
        if d[j] <= link:
            jj = int(free_[j])
            tr.fit(float(fx[jj]), float(fy[jj]), t, fk[jj], int(fe[jj]),
                   win.teal(crop, fx[jj:jj + 1], fy[jj:jj + 1])[0])
            _rename(tr, S, int(fe[jj]))
            used[jj] = True
            return
    tr.x, tr.y, tr.vx, tr.vy, tr.t_fit, tr.t_conf = c["cx"], c["cy"], 0.0, 0.0, t, t
    tr.ref = win.teal(crop, [c["cx"]], [c["cy"]])[0]
    tr.status = "cover"


def _emerge(c, mem, fx, fy, fe, fk, used, t, fidx, S, win, crop, crowd_d, r_out, emergences,
            Arbiter, identity_claim, js=None, apart=None) -> int:
    """Local fits in the crowd's window assigned to its members by continuity
    and named by the arbiter. Returns how many fits it read. A full read
    passes its own fits beside the crowd (`js`, `apart`)."""
    if js is None:
        bx = c["box"]
        pad = r_out * 2
        inw = ((fx >= bx[0] - pad) & (fx <= bx[2] + pad) & (fy >= bx[1] - pad)
               & (fy <= bx[3] + pad) & ~used)
        js = np.flatnonzero(inw)
        if js.size < 2 or len(mem) < 1:
            # one fit parts nothing: a lone member dissolves the crowd instead
            return int(js.size)
        # an emerger: a fit apart (one diameter) from every other fit in the window
        Dj = np.hypot(fx[js][:, None] - fx[js][None], fy[js][:, None] - fy[js][None])
        np.fill_diagonal(Dj, np.inf)
        apart = Dj.min(axis=1) > crowd_d
    if not js.size or not len(mem) or not apart.any():
        return int(js.size)
    # continuity cost: the member's entry place carried with the blob, and its heading
    cost = np.zeros((len(mem), js.size))
    for i, tr in enumerate(mem):
        en = tr.entry
        px_ = en["x"] + (c["cx"] - en["cx"])
        py_ = en["y"] + (c["cy"] - en["cy"])
        d = np.hypot(fx[js] - px_, fy[js] - py_) / r_out
        sp = math.hypot(en["vx"], en["vy"])
        if sp > 1e-6:
            bx_, by_ = fx[js] - c["cx"], fy[js] - c["cy"]
            nb = np.hypot(bx_, by_) + 1e-6
            cosang = (bx_ * en["vx"] + by_ * en["vy"]) / (nb * sp)
            d = d + HEADING_W * (1.0 - cosang)
        cost[i] = d
    ri, ci = linear_sum_assignment(cost)
    best = cost[ri, ci].sum()
    margin = math.inf
    if len(mem) >= 2 and js.size >= 2:
        # the runner-up: the cheapest assignment that changes any pair
        alt = []
        for i_, j_ in zip(ri, ci):
            C2 = cost.copy()
            C2[i_, j_] = 1e6
            r2, c2 = linear_sum_assignment(C2)
            alt.append(C2[r2, c2].sum())
        margin = min(alt) - best
    for i_, j_ in zip(ri.tolist(), ci.tolist()):
        jj = int(js[j_])
        if not apart[j_]:
            continue
        tr = mem[i_]
        en = tr.entry
        ent = S.ent_ids[int(fe[jj])]
        ambiguous = bool(margin < MARGIN)
        ar = Arbiter()
        ar.add(identity_claim(ent, S.agent[int(fe[jj])], channel="round_entity_verdict",
                              observed_at_ms=t,
                              reason=None if S.agent[int(fe[jj])] else "entity_unnamed"))
        ar.add(identity_claim(
            ent, None if ambiguous else tr.name, channel="prior_continuity", observed_at_ms=t,
            reason=("ambiguous_continuity" if ambiguous else
                    None if tr.name else "member_unnamed"),
            source_version=ALLY_PRIOR_VERSION,
            depends_on=[en["entity"]] if en["entity"] else None,
            evidence={"crowd": c["id"], "rests_on": en["key"], "margin": round(float(margin), 3)
                      if math.isfinite(margin) else None,
                      "cost": round(float(cost[i_, j_]), 3)}))
        v = ar.verdict()[0]
        emergences.append({"crowd": c["id"], "t": t, "fidx": fidx, "x": float(fx[jj]),
                           "y": float(fy[jj]), "track": tr.id, "member_name": tr.name,
                           "stored_agent": S.agent[int(fe[jj])], "agent": v["agent"],
                           "status": v["status"], "reason": v.get("reason"),
                           "ambiguous": ambiguous, "rests_on": en["key"],
                           "depends_on": [en["entity"]] if en["entity"] else []})
        ref = win.teal(crop, fx[jj:jj + 1], fy[jj:jj + 1])[0]
        tr.fit(float(fx[jj]), float(fy[jj]), t, fk[jj], int(fe[jj]), ref)
        tr.name = v["agent"]
        tr.crowd = None
        used[jj] = True
    return int(js.size)


def _full_read(S, px, key, tracks, crowds, lost, fx, fy, fe, fk, used, t, fidx, why, hot, cells,
               cap, cap_last, band, win, crop, rd, casts, surprises, suppress, guard, nid, t0r,
               link, emergences) -> None:
    """A surprise reads the frame in full (the stored ring fits): fits no
    track holds reattach a recently lost track or spawn one, under the
    roster cap and the mass band; a hot region with no fit is non-ally."""
    from reticle.adjudication.identity import AgentIdentityArbiter, identity_claim
    free_fit = np.flatnonzero(~used)
    r_out = px.shape.r_out
    # fits beside a crowd (its box padded three outer radii) are its members:
    # one off its centre by more than an outer radius emerges from it by
    # continuity; the rest are inside, where nothing is searched
    for c in crowds.values():
        bx, pad = c["box"], 3 * r_out
        near = ((fx[free_fit] >= bx[0] - pad) & (fx[free_fit] <= bx[2] + pad)
                & (fy[free_fit] >= bx[1] - pad) & (fy[free_fit] <= bx[3] + pad))
        js = free_fit[near]
        if js.size:
            mem = [tr for tr in tracks if tr.crowd == c["id"]]
            apart = np.hypot(fx[js] - c["cx"], fy[js] - c["cy"]) > r_out
            _emerge(c, mem, fx, fy, fe, fk, used, t, fidx, S, win, crop, 2 * r_out, r_out,
                    emergences, AgentIdentityArbiter, identity_claim, js=js, apart=apart)
        free_fit = free_fit[~near]
    # fits already near a held track are that track's (a full read refreshes them)
    for tr in tracks:
        if tr.crowd is not None or not free_fit.size:
            continue
        d = np.hypot(fx[free_fit] - tr.x, fy[free_fit] - tr.y)
        j = int(np.argmin(d))
        if d[j] <= link:
            jj = int(free_fit[j])
            tr.fit(float(fx[jj]), float(fy[jj]), t, fk[jj], int(fe[jj]),
                   win.teal(crop, fx[jj:jj + 1], fy[jj:jj + 1])[0])
            _rename(tr, S, int(fe[jj]))
            used[jj] = True
            free_fit = free_fit[free_fit != jj]
    # hot cells with no fit: non-ally teal, suppressed
    if hot is not None and hot.any():
        n, lbl = cv2.connectedComponents(hot.astype(np.uint8), connectivity=8)
        for q in range(1, n):
            m = lbl == q
            xs, ys = cells.gx[m], cells.gy[m]
            has = free_fit.size and (np.hypot(fx[free_fit][:, None] - xs[None],
                                              fy[free_fit][:, None] - ys[None])
                                     <= cells.sx * 1.5).any()
            if not has:
                guard["non_ally_teal"] += 1
            # every hot region read in full waits SUPPRESS_MS before it asks
            # again; a teammate it held is explained by its track meanwhile
            grown = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            suppress.append((grown, t + SUPPRESS_MS))
    for jj in free_fit.tolist():
        x, y = float(fx[jj]), float(fy[jj])
        # the mass band: the fit's blob mass in one icon's window
        b = window_blob(px, key, (x - 2 * px.shape.r_out, y - 2 * px.shape.r_out,
                                  x + 2 * px.shape.r_out, y + 2 * px.shape.r_out), (x, y))
        mass = b["mass"] if b is not None else 0.0
        if mass < band[0]:
            guard["mass_band_low"] += 1
            continue
        if cap is not None and len(tracks) >= cap:
            # the roster holds no room: a fit with no prior means one of the
            # held teammates is wrong; the weakest prior that can continue
            # it (a crowd member or a carried teammate, the stored verdict's
            # name first, else the nearest) takes it by continuity
            if _reassign(S, tracks, crowds, fx, fy, fe, fk, used, jj, t, fidx, win, crop,
                         r_out, emergences):
                guard["capacity_reassigned"] += 1
            else:
                guard["capacity_refused"] += 1
            continue
        name = S.agent[int(fe[jj])]
        # explain the spawn
        exp = _explain(t, x, y, name, why, lost, casts, t0r)
        nid[0] += 1
        tr = Track(f"{S.sid}:T{nid[0]:04d}", x, y, t, fk[jj], int(fe[jj]), name,
                   win.teal(crop, fx[jj:jj + 1], fy[jj:jj + 1])[0], exp["why"])
        tracks.append(tr)
        used[jj] = True
        surprises.append({"t": t, "fidx": fidx, "x": x, "y": y, "agent": name, "trigger": why,
                          "round": rd["round_no"], "mass_ratio": round(mass / band[1], 3)
                          if band[1] else None, **exp,
                          "capacity": cap, "capacity_rests_on_t": None if cap_last is None
                          else cap_last[1]})


def _reassign(S, tracks, crowds, fx, fy, fe, fk, used, jj, t, fidx, win, crop, r_out,
              emergences) -> bool:
    from reticle.adjudication.identity import AgentIdentityArbiter, identity_claim
    x, y = float(fx[jj]), float(fy[jj])
    ag = S.agent[int(fe[jj])]
    # 0.2.0: the track the stored verdict names, wherever it is held; else a
    # weak prior; else the stalest track, unfitted for STALE_MS
    cand = [tr for tr in tracks if ag is not None and tr.name == ag]
    cand = cand or [tr for tr in tracks
                    if tr.crowd is not None or tr.status in ("predicted", "cover")]
    cand = cand or [tr for tr in tracks if t - tr.t_fit >= STALE_MS]
    if not cand:
        return False

    def where(tr):
        if tr.crowd is not None and tr.crowd in crowds:
            return crowds[tr.crowd]["cx"], crowds[tr.crowd]["cy"]
        return tr.x, tr.y
    named = [tr for tr in cand if ag is not None and tr.name == ag]
    pick = min(named or cand, key=lambda tr: math.hypot(where(tr)[0] - x, where(tr)[1] - y))
    if pick.crowd is not None and pick.crowd in crowds:
        _emerge(crowds[pick.crowd], [pick], fx, fy, fe, fk, used, t, fidx, S, win, crop,
                2 * r_out, r_out, emergences, AgentIdentityArbiter, identity_claim,
                js=np.asarray([jj]), apart=np.ones(1, bool))
        return True
    pick.fit(x, y, t, fk[jj], int(fe[jj]), win.teal(crop, fx[jj:jj + 1], fy[jj:jj + 1])[0])
    _rename(pick, S, int(fe[jj]))
    used[jj] = True
    return True


def _explain(t, x, y, name, why, lost, casts, t0r) -> dict:
    """Why a teammate appeared with no prior: the round's start, the widget's
    return, a reacquired track (this reader's own loss), an ally cast or a
    revive, or unexplained."""
    if why == "round_start" or t - t0r <= SPAWN_MS:
        return {"why": "round_start"}
    if why == "gap":
        return {"why": "widget_return"}
    re_ = [tr for tr in lost if tr.status == "lost" and t - tr.t_conf <= REACQ_MS
           and (name is None or tr.name in (None, name))]
    if re_:
        tr = min(re_, key=lambda tr: math.hypot(tr.x - x, tr.y - y))
        return {"why": "reacquired", "lost_track": tr.id, "lost_ms": round(t - tr.t_conf),
                "lost_d_px": round(math.hypot(tr.x - x, tr.y - y), 1)}
    for tc, ag in casts["ult"]:
        if 0 <= t - tc <= CAST_MS and ag in set(TELEPORT_CANDIDATES) | set(REVIVE_AGENTS):
            return {"why": "ally_ult_cast", "cast_t": tc, "cast_agent": ag,
                    "candidate_only": ag in TELEPORT_CANDIDATES}
    for tv in casts["revive"]:
        if 0 <= t - tv <= CAST_MS:
            return {"why": "revive", "revive_t": tv}
    for tc, slot in casts["own"]:
        if 0 <= t - tc <= CAST_MS:
            return {"why": "own_cast_nearby", "cast_t": tc, "slot": slot}
    return {"why": "unexplained"}


def _audit(SA, span, tracks, crowds, t, fidx, r, link) -> dict:
    """A full read (ring fits and the stored stack fit) against the prior,
    stored apart: fits no track or crowd holds, tracks no fit lies near."""
    a, b = span
    sf = SA.ob_self[a:b]
    x, y = SA.ob_x[a:b][~sf], SA.ob_y[a:b][~sf]
    stk = SA.ob_stack[a:b][~sf]
    P = [(tr.x, tr.y) for tr in tracks if tr.crowd is None]
    P += [(c["cx"], c["cy"]) for c in crowds.values()]
    P = np.asarray(P, float).reshape(-1, 2)
    if x.size and P.size:
        D = np.hypot(x[:, None] - P[None, :, 0], y[:, None] - P[None, :, 1])
        unheld = D.min(axis=1) > link
        far = D.min(axis=0) > link
    else:
        unheld = np.ones(x.size, bool)
        far = np.ones(P.shape[0], bool)
    return {"t": t, "fidx": fidx, "fits": int(x.size), "stack_fits": int(stk.sum()),
            "unheld_fits": int(unheld.sum()), "unheld_stack_fits": int((unheld & stk).sum()),
            "held_without_fit": int(far.sum()), "tracks": len(tracks), "crowds": len(crowds)}


# ----------------------------------------------------------------- calibration

def calibrate(sid: str, n: int = 300) -> dict:
    """The presence and surprise cuts from the reader's own ring fits (no
    truth): `ring_cover` and the cell level at isolated ring fits and at the
    same fits moved 2.5 radii (the floor beside an icon)."""
    S = v1.Session(sid)
    px = cb.Pixels(sid)
    barriers = barrier_rows(sid)
    idx = cb.frame_clock(S, px)
    pick = idx[np.unique(np.linspace(0, idx.size - 1, n).astype(int))]
    a = np.searchsorted(S.ob_f, S.fr_f[pick], side="left")
    b = np.searchsorted(S.ob_f, S.fr_f[pick], side="right")
    t_of = {round(float(S.fr_t[k]), 3): q for q, k in enumerate(pick)}
    at, off, cell_at, cell_off, cell_bg = [], [], [], [], []
    cells = None
    slab = px.slab.astype(np.float32)
    for t, crop in px.crops(S.fr_t[pick]):
        q = t_of[round(t, 3)]
        i, j = a[q], b[q]
        x, y, sf = S.ob_x[i:j], S.ob_y[i:j], S.ob_self[i:j]
        key = reader_key(px, crop)
        if cells is None:
            cells = Cells(key.shape, px.shape.r_out)
        G = cells.of(key * slab)
        allx, ally_ = x, y
        x, y = x[~sf], y[~sf]
        if not x.size:
            continue
        D = np.hypot(allx[:, None] - x[None], ally_[:, None] - y[None])
        iso = (np.sort(D, axis=0)[1] if allx.size > 1 else np.full(x.size, np.inf)) > 4 * S.r
        for xi, yi in zip(x[iso], y[iso]):
            at.append(ring_cover_at(key, [xi], [yi], px.shape.r_in, px.shape.r_out)[0])
            gi = min(cells.ny - 1, int(yi / cells.sy))
            gj = min(cells.nx - 1, int(xi / cells.sx))
            cell_at.append(float(G[max(0, gi - 1):gi + 2, max(0, gj - 1):gj + 2].max()))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                xo, yo = xi + dx * 2.5 * S.r, yi + dy * 2.5 * S.r
                off.append(ring_cover_at(key, [xo], [yo], px.shape.r_in, px.shape.r_out)[0])
        bar = barriers.get(int(S.fr_f[pick[q]]), [])
        near = cells.near(list(allx) + [b_[0] for b_ in bar], list(ally_) + [b_[1] for b_ in bar],
                          EXPLAIN_R * px.shape.r_out)
        cell_bg.append(float(G[~near & (cells.gx >= 0)].max()) if (~near).any() else 0.0)
    at, off, cell_at, cell_bg = map(np.asarray, (at, off, cell_at, cell_bg))
    out = {"session": sid, "isolated_fits": int(at.size)}
    for cut in (0.05, 0.1, 0.15, 0.2, 0.3):
        out[f"cover_{cut}"] = {"fit_confirmed": round(float((at >= cut).mean()), 4),
                               "beside_confirmed": round(float((off >= cut).mean()), 4)}
    for lv in (0.08, 0.12, 0.16, 0.2, 0.25):
        out[f"cell_{lv}"] = {"fit_hot": round(float((cell_at >= lv).mean()), 4),
                             "frames_with_unexplained_hot": round(float((cell_bg >= lv).mean()), 4)}
    return out


# ----------------------------------------------------------------- scoring

def _setup(sid: str):
    S = v1.Session(sid, drop_stack=True)
    S_all = v1.Session(sid)
    px = cb.Pixels(sid)
    idx = cb.frame_clock(S, px)
    iso = cb.isolated_mass(S, px, idx, n=300)
    m = iso["mass"]
    # the band's low edge: the isolated 5th percentile (one icon's lightest)
    if iso.get("p05") is None:
        iso["p05"] = cb.MIN_MASS * m
    return S, S_all, px, iso


def _rows_by_frame(R) -> dict:
    by = defaultdict(list)
    for row in R["rows"]:
        by[row[0]].append(row)
    return by


def _crowds_by_frame(R) -> dict:
    by = defaultdict(list)
    for c in R["crowd_rows"]:
        if c.get("poly") is not None or c.get("cx") is not None:
            by[c["fidx"]].append(c)
    return by


def cheap_share(R) -> float:
    k = Counter(R["frame_kind"].values())
    return round(k.get("cheap", 0) / max(1, sum(k.values())), 4)


def score_riot(sid: str) -> dict:
    """Every living ally at each Riot kill instant against the prior-first
    reader, and the stored ring fits alone as the baseline."""
    import riot_ground_truth as rg
    t0 = time.time()
    S, S_all, px, iso = _setup(sid)
    R = run_session(S, px, iso, S_all=S_all)
    ctx = v1.riot_context(sid)
    mf = ctx["mf"]
    gate = rg.GATE_M * 100.0 * mf.px_per_unit
    r_icon = float(mf.icon_px)
    m_per_px = 1.0 / (mf.px_per_unit * 100.0)
    want = np.asarray([ctx["a"] + k["gameTime"] + rg.MINIMAP_LAG_MS for k in ctx["kills"]])
    fi = np.clip(np.searchsorted(S.fr_t, want), 1, S.fr_t.size - 1)
    fi = np.where(np.abs(S.fr_t[fi - 1] - want) <= np.abs(S.fr_t[fi] - want), fi - 1, fi)
    ok_f = (np.abs(S.fr_t[fi] - want) <= rg.FRAME_TOL_MS) & S.fr_drawn[fi]
    rows_f, crowds_f = _rows_by_frame(R), _crowds_by_frame(R)
    dying_at = defaultdict(list)
    for k in ctx["kills"]:
        dying_at[(k["round"], k["gameTime"])].append(k)
    c = Counter()
    err_m, out_rows = [], []
    for k, f_i, okk in zip(ctx["kills"], fi, ok_f):
        if not okk:
            c["kill_no_frame"] += 1
            continue
        fidx = int(S.fr_f[f_i])
        if fidx not in R["frame_kind"]:
            c["kill_frame_off_clock"] += 1
            continue
        locs = rg.truth_locations(k, dying_at)
        allies = [s for s in locs if ctx["who"][s]["teamId"] == ctx["team"]
                  and s != ctx["me"] and not locs[s].get("victim_added")]
        if not allies:
            continue
        Tp = [mf.to_px(locs[s]["location"]["x"], locs[s]["location"]["y"]) for s in allies]
        tr_rows = rows_f.get(fidx, [])
        free = [rw for rw in tr_rows if STATUSES[rw[6]] != "crowd"]
        pairs = rg.greedy_pairs([tuple(p) for p in Tp], [(rw[4], rw[5]) for rw in free], gate)
        hit = {i: (j, d) for i, j, d in pairs}
        # baseline: the stored ring fits alone, and with the stored stack fit
        a_, b_ = np.searchsorted(S_all.ob_f, [fidx, fidx + 1])
        sf = S_all.ob_self[a_:b_]
        ox, oy, ost = S_all.ob_x[a_:b_][~sf], S_all.ob_y[a_:b_][~sf], S_all.ob_stack[a_:b_][~sf]
        ring = [(x, y) for x, y, s_ in zip(ox, oy, ost) if not s_]
        ring_hit = {i for i, _j, _d in rg.greedy_pairs([tuple(p) for p in Tp], ring, gate)}
        both_hit = {i for i, _j, _d in rg.greedy_pairs([tuple(p) for p in Tp],
                                                      list(zip(ox, oy)), gate)}
        regs = crowds_f.get(fidx, [])
        me_dead = ctx["me"] not in locs or bool(locs[ctx["me"]].get("victim_added"))
        self_xy = ((float(S_all.ob_x[a_:b_][sf][0]), float(S_all.ob_y[a_:b_][sf][0]))
                   if sf.any() else None)
        for i, s in enumerate(allies):
            truth_agent = ctx["agent_of"].get(s)
            if me_dead and self_xy is not None and i not in hit and \
                    math.hypot(Tp[i][0] - self_xy[0], Tp[i][1] - self_xy[1]) <= gate:
                # the self icon draws the spectated teammate [domain:minimap/self-icon-shows-spectated]
                c["spectated_at_self"] += 1
                continue
            c["living_allies"] += 1
            c["ring_located"] += int(i in ring_hit)
            c["ring_stack_located"] += int(i in both_hit)
            if i in hit:
                j, d = hit[i]
                rw = free[j]
                c["carried"] += 1
                c["carried_" + STATUSES[rw[6]]] += 1
                err_m.append(d * m_per_px)
                if rw[3] is None:
                    c["carried_refused"] += 1
                elif rg.canon(rw[3]) == rg.canon(truth_agent):
                    c["carried_name_right"] += 1
                else:
                    c["carried_name_wrong"] += 1
                c["carried_within_r"] += int(d <= r_icon)
                continue
            x, y = Tp[i]
            strict = [g for g in regs if g.get("poly") is not None
                      and cb.inside_any([g["poly"]], x, y, 0.0)]
            near = strict or [g for g in regs if (g.get("poly") is not None
                                                  and cb.inside_any([g["poly"]], x, y, r_icon))
                              or math.hypot(g["cx"] - x, g["cy"] - y) <= 2 * r_icon]
            if near:
                g = near[0]
                c["crowd_within_r"] += 1
                c["crowd_strict"] += int(bool(strict))
                names = [n for n in g["names"] if n is not None]
                c["crowd_member_set_right"] += int(any(rg.canon(n) == rg.canon(truth_agent)
                                                       for n in names))
                c["crowd_member_unnamed"] += int(len(names) < len(g["names"]))
                continue
            c["lost"] += 1
            out_rows.append({"fidx": fidx, "agent": truth_agent, "x": x, "y": y,
                             "ring": i in ring_hit, "stack": i in both_hit})
        # phantoms: carried tracks with no teammate Riot draws at this instant
        # (the player and this instant's victims included) within r / the gate
        Tall = [mf.to_px(locs[s_]["location"]["x"], locs[s_]["location"]["y"]) for s_ in locs
                if ctx["who"][s_]["teamId"] == ctx["team"]]
        for j, rw in enumerate(free):
            d = min((math.hypot(rw[4] - p[0], rw[5] - p[1]) for p in Tall), default=math.inf)
            c["tracks_at_kills"] += 1
            c["phantom_r"] += int(d > r_icon)
            c["phantom_gate"] += int(d > gate)
    out = {"session": sid, "capture": S.manifest["source"]["path"],
           "ally_prior_version": ALLY_PRIOR_VERSION, "events_from": str(v1.EVENTS),
           "ally_icon_version": S.ally_icon_version,
           "round_entity_ally_icon": S.round_entity_inputs.get("ally_icon"),
           "ally_icon_stale": S.ally_icon_stale, "kill_instants": dict(c),
           "position_error_m": v1._stats(np.asarray(err_m), 2),
           "cheap_frame_share": cheap_share(R), "decisions": R["decisions"],
           "guard": R["guard"], "frames": R["frames"], "iso": iso,
           "surprises": dict(Counter(s_["why"] for s_ in R["surprises"])),
           "emergence": dict(Counter(e["status"] for e in R["emergences"])),
           "audit": _audit_sum(R["audits"]), "cost_us_per_frame": _cost(R),
           "lost_rows": out_rows, "seconds": round(time.time() - t0, 1)}
    write_rows(sid, R)
    return out


def _audit_sum(A) -> dict:
    c = Counter()
    for a in A:
        for k, v in a.items():
            if k not in ("t", "fidx"):
                c[k] += v
    c["audits"] = len(A)
    return dict(c)


def _cost(R) -> dict:
    c = R["cost_s"]
    nf = max(1, c.get("frames", 0))
    out = {k: round(v / nf * 1e6, 1) for k, v in c.items() if k != "frames"}
    # the full read's stored rows cost nothing here; `price` charges it from usage
    out["total_without_key"] = round(sum(v for k, v in c.items()
                                         if k not in ("frames", "key", "surprise_read"))
                                     / nf * 1e6, 1)
    return out


def score_replay(sid: str) -> dict:
    """Every living ally on every frame of a capture with a replay
    (evaluation only): carried (position error), in a crowd, or lost; the
    stored ring fits alone as the baseline; the surprise log."""
    import riot_ground_truth as rg
    t0 = time.time()
    S, S_all, px, iso = _setup(sid)
    R = run_session(S, px, iso, S_all=S_all)
    ctx = v1.replay_context(sid)
    mf = ctx["mf"]
    gate = rg.GATE_M * 100.0 * mf.px_per_unit
    r_icon = float(mf.icon_px)
    m_per_px = 1.0 / (mf.px_per_unit * 100.0)
    fr = np.asarray(sorted(R["frame_kind"]))
    pos = np.searchsorted(S.fr_f, fr)
    t = S.fr_t[pos]
    X, Y = v1.truth_px(ctx, t)
    me = ctx["allies"].index(ctx["me"]) if ctx["me"] in ctx["allies"] else None
    me_dead = ~np.isfinite(X[:, me]) if me is not None else np.zeros(t.size, bool)
    Xa, Ya = X.copy(), Y.copy()                  # every drawn teammate, the player too
    if me is not None:
        X[:, me] = np.nan
        Y[:, me] = np.nan
    rows_f, crowds_f = _rows_by_frame(R), _crowds_by_frame(R)
    c = Counter()
    err = []
    for q, f in enumerate(fr.tolist()):
        live = np.flatnonzero(np.isfinite(X[q]))
        if not live.size:
            continue
        Tp = [(X[q, j], Y[q, j]) for j in live]
        free = [rw for rw in rows_f.get(f, []) if STATUSES[rw[6]] != "crowd"]
        pairs = rg.greedy_pairs(Tp, [(rw[4], rw[5]) for rw in free], gate)
        hit = {i: (j, d) for i, j, d in pairs}
        a_, b_ = np.searchsorted(S.ob_f, [f, f + 1])
        sf = S.ob_self[a_:b_]
        ring = list(zip(S.ob_x[a_:b_][~sf], S.ob_y[a_:b_][~sf]))
        ring_hit = {i for i, _j, _d in rg.greedy_pairs(Tp, ring, gate)}
        self_xy = (float(S.ob_x[a_:b_][sf][0]), float(S.ob_y[a_:b_][sf][0])) if sf.any() else None
        regs = crowds_f.get(f, [])
        for i, (x, y) in enumerate(Tp):
            if me_dead[q] and self_xy is not None and i not in hit and \
                    math.hypot(x - self_xy[0], y - self_xy[1]) <= gate:
                c["spectated_at_self"] += 1
                continue
            c["ally_frames"] += 1
            c["ring_located"] += int(i in ring_hit)
            if i in hit:
                j, d = hit[i]
                c["carried"] += 1
                c["carried_" + STATUSES[free[j][6]]] += 1
                c["carried_within_r"] += int(d <= r_icon)
                err.append(d * m_per_px)
                continue
            strict = any(g.get("poly") is not None and cb.inside_any([g["poly"]], x, y, 0.0)
                         for g in regs)
            near = strict or any((g.get("poly") is not None
                                  and cb.inside_any([g["poly"]], x, y, r_icon))
                                 or math.hypot(g["cx"] - x, g["cy"] - y) <= 2 * r_icon
                                 for g in regs)
            c["crowd_strict"] += int(strict)
            c["crowd_within_r"] += int(near)
            c["lost"] += int(not near)
        la = np.flatnonzero(np.isfinite(Xa[q]))
        for rw in free:
            d = min((math.hypot(rw[4] - Xa[q, j], rw[5] - Ya[q, j]) for j in la),
                    default=math.inf)
            c["track_frames"] += 1
            c["phantom_r"] += int(d > r_icon)
            c["phantom_gate"] += int(d > gate)
    out = {"session": sid, "capture": S.manifest["source"]["path"],
           "ally_prior_version": ALLY_PRIOR_VERSION, "events_from": str(v1.EVENTS),
           "ally_icon_version": S.ally_icon_version,
           "round_entity_ally_icon": S.round_entity_inputs.get("ally_icon"),
           "ally_icon_stale": S.ally_icon_stale, "frames_scored": int(fr.size),
           "counts": dict(c), "position_error_m": v1._stats(np.asarray(err), 2),
           "cheap_frame_share": cheap_share(R), "decisions": R["decisions"],
           "guard": R["guard"], "iso": iso,
           "surprises": dict(Counter(s_["why"] for s_ in R["surprises"])),
           "surprise_triggers": dict(Counter(s_["trigger"] for s_ in R["surprises"])),
           "emergence": dict(Counter(e["status"] for e in R["emergences"])),
           "audit": _audit_sum(R["audits"]), "cost_us_per_frame": _cost(R),
           "seconds": round(time.time() - t0, 1)}
    # identity at emergence against the replay's agent at the emerger's place
    E = R["emergences"]
    if E:
        et = np.asarray([e["t"] for e in E])
        Xe, Ye = v1.truth_px(ctx, et)
        Dm = np.hypot(Xe - np.asarray([e["x"] for e in E])[:, None],
                      Ye - np.asarray([e["y"] for e in E])[:, None])
        Dm = np.where(np.isfinite(Dm), Dm, np.inf)
        jj = Dm.argmin(axis=1)
        dd = Dm[np.arange(et.size), jj]
        tru = [ctx["agents"][j] if d_ <= gate else None for j, d_ in zip(jj, dd)]

        def outcome(names):
            return dict(Counter("no_truth" if tr is None else "refused" if n is None else
                                "right" if rg.canon(n) == rg.canon(tr) else "wrong"
                                for n, tr in zip(names, tru)))
        out["emergence_identity"] = {"arbiter": outcome([e["agent"] for e in E]),
                                     "stored_verdict_only": outcome([e["stored_agent"] for e in E]),
                                     "continuity_only": outcome([None if e["ambiguous"] else
                                                                 e["member_name"] for e in E])}
    write_rows(sid, R)
    return out


def write_rows(sid: str, R: dict) -> Path:
    """The reader's output in event form: `ally_track` rows (status, and
    `rests_on` the fit a held, covered or predicted teammate continues),
    `ally_crowd` rows (members by track, positions the region),
    `ally_surprise`, `ally_emergence`, and `ally_audit` apart."""
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    path = ANALYSIS / f"prior_{sid}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        def put(kind, row):
            f.write(json.dumps({"kind": kind, "session_id": sid,
                                "ally_prior_version": ALLY_PRIOR_VERSION, **row},
                               default=cb._default, separators=(",", ":")) + "\n")
        for (fidx, t, tid, name, x, y, st, cid, key) in R["rows"]:
            stn = STATUSES[st]
            put("ally_track", {"frame_idx": fidx, "t_ms": t, "track": tid, "agent": name,
                               "status": stn,
                               "position": {"region": cid} if cid else
                               {"x": round(x, 2), "y": round(y, 2)},
                               "observation_key": key if stn == "fit" else None,
                               "rests_on": None if stn == "fit" else key})
        for g in R["crowd_rows"]:
            put("ally_crowd", {**{k: v for k, v in g.items() if k != "poly"},
                               "outline": None if g.get("poly") is None
                               else np.round(g["poly"], 1)})
        for s_ in R["surprises"]:
            put("ally_surprise", s_)
        for e in R["emergences"]:
            put("ally_emergence", e)
        for a in R["audits"]:
            put("ally_audit", a)
    return path


# ----------------------------------------------------------------- price

def price(sid: str, R_cost: dict, decisions: dict, frames: int) -> dict:
    """The prior-first reader's CPU against the full reader's stored usage
    (`reticle usage`): every frame pays the widget, the key and the cheap
    check; a local fit pays one icon's ring search share and pose; a full
    read pays the reader without stack_fit; the audit pays the reader with
    the vectorised stack_fit."""
    from reticle import usage
    rows = [r_ for r_ in usage.load(STORE, sid) if r_.get("kind") != "command"
            and (r_.get("readers") or {}).get("ally_icon")]
    if not rows:
        return {"session": sid, "reason": "no_stored_usage"}
    u = rows[-1]
    a = u["readers"]["ally_icon"]
    steps = a.get("steps") or {}
    n = a["feed"]["count"]

    def s_(k):
        return steps.get(k, {}).get("total_ns", 0) / 1e9

    feed = a["feed"]["total_ns"] / 1e9
    stack = s_("stack_fit")
    vec_feed = feed - stack + stack * cb.VECTORISED_STACK_FIT
    no_stack = feed - stack
    always = (s_("widget") + s_("masks") + s_("other") + s_("barriers")) / n
    icons_n = max(1, steps.get("pose/refine", {}).get("count", 1))
    per_icon = (s_("icons") + s_("pose") + s_("descriptors")) / icons_n
    cheap = R_cost.get("total_without_key", 0.0) * 1e-6
    nf = max(1, frames)
    local = decisions.get("local_fit_icons", 0) / nf * per_icon
    full = decisions.get("full_reads", 0) / nf * (no_stack / n)
    audit = (1000.0 / AUDIT_MS) / 15.0 * (vec_feed / n)
    total = always + cheap + local + full + audit
    return {"session": sid, "usage_run": u.get("run_id"), "frames_fed": n,
            "reader_ms_per_frame": round(feed / n * 1e3, 2),
            "reader_vectorised_ms_per_frame": round(vec_feed / n * 1e3, 2),
            "always_ms": round(always * 1e3, 3), "cheap_check_ms": round(cheap * 1e3, 3),
            "local_fit_ms_per_icon": round(per_icon * 1e3, 3), "local_ms": round(local * 1e3, 3),
            "full_read_ms": round(full * 1e3, 3), "audit_ms": round(audit * 1e3, 3),
            "prior_first_ms_per_frame": round(total * 1e3, 2),
            "share_of_vectorised_reader": round(total / (vec_feed / n), 4)}


# ----------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events-from", type=Path, default=None,
                    help="read the stored streams from this copy of <store>/events")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("calibrate")
    p.add_argument("session")
    p.add_argument("--n", type=int, default=300)
    p = sub.add_parser("replay")
    p.add_argument("session")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("riot")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--pool", required=True)
    p.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
    if args.events_from:
        v1.EVENTS = args.events_from
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    deps = {"ally_prior": ALLY_PRIOR_VERSION}
    if args.cmd == "calibrate":
        out = calibrate(args.session, args.n)
        (ANALYSIS / f"calibrate_{args.session}.json").write_text(json.dumps(out, indent=1),
                                                                encoding="utf-8")
        print(json.dumps(out, indent=1))
        return 0
    if args.cmd == "replay":
        s = score_replay(args.session)
        s["price"] = price(args.session, s["cost_us_per_frame"], s["decisions"],
                           s["frames_scored"])
        (ANALYSIS / f"replay_{args.session}.json").write_text(
            json.dumps(s, indent=1, default=cb._default), encoding="utf-8")
        print(json.dumps(s, indent=1, default=cb._default))
        if args.record:
            from reticle import metrics
            c = s["counts"]
            n = max(1, c.get("ally_frames", 0))
            v = {"located_share": round((c.get("carried", 0) + c.get("crowd_within_r", 0)) / n, 4),
                 "carried_share": round(c.get("carried", 0) / n, 4),
                 "crowd_within_r_share": round(c.get("crowd_within_r", 0) / n, 4),
                 "crowd_strict_share": round(c.get("crowd_strict", 0) / n, 4),
                 "lost_share": round(c.get("lost", 0) / n, 4),
                 "ring_located_share": round(c.get("ring_located", 0) / n, 4),
                 "phantom_r_share": round(c.get("phantom_r", 0) / max(1, c.get("track_frames", 0)), 4),
                 "phantom_gate_share": round(c.get("phantom_gate", 0)
                                             / max(1, c.get("track_frames", 0)), 4),
                 "position_error_median_m": (s["position_error_m"] or {}).get("median"),
                 "cheap_frame_share": s["cheap_frame_share"],
                 "surprises_unexplained": s["surprises"].get("unexplained", 0),
                 "surprises": sum(s["surprises"].values()),
                 "cost_us_per_frame": s["cost_us_per_frame"]["total_without_key"],
                 "prior_first_ms_per_frame": s["price"].get("prior_first_ms_per_frame")}
            metrics.record("ally_prior", part="replay", session=args.session, values=v,
                           deps={**deps, "ally_icon": s["ally_icon_version"]})
            print(" ".join(f"[metric:ally_prior/replay@{args.session}#{k}={x}]"
                           for k, x in v.items()))
        return 0
    if args.cmd == "riot":
        pool = Counter()
        sums = []
        for sid in args.sessions:
            s = score_riot(sid)
            s["price"] = price(sid, s["cost_us_per_frame"], s["decisions"], s["frames"])
            (ANALYSIS / f"riot_{sid}.json").write_text(json.dumps(s, indent=1, default=cb._default),
                                                       encoding="utf-8")
            print(json.dumps({k: v for k, v in s.items() if k != "lost_rows"}, indent=1,
                             default=cb._default))
            ki = s["kill_instants"]
            pool.update({k: v for k, v in ki.items()})
            pool["cheap_frames"] += round(s["cheap_frame_share"] * s["frames"])
            pool["frames"] += s["frames"]
            pool["surprises"] += sum(s["surprises"].values())
            pool["surprises_unexplained"] += s["surprises"].get("unexplained", 0)
            sums.append(s)
        n = max(1, pool["living_allies"])
        v = {"living_allies": pool["living_allies"],
             "located_share": round((pool["carried"] + pool["crowd_within_r"]) / n, 4),
             "carried_share": round(pool["carried"] / n, 4),
             "carried_name_right_share": round(pool["carried_name_right"]
                                               / max(1, pool["carried"]), 4),
             "crowd_within_r_share": round(pool["crowd_within_r"] / n, 4),
             "crowd_strict_share": round(pool["crowd_strict"] / n, 4),
             "crowd_member_set_right": pool["crowd_member_set_right"],
             "refused": pool["carried_refused"],
             "lost_share": round(pool["lost"] / n, 4),
             "ring_located_share": round(pool["ring_located"] / n, 4),
             "ring_stack_located_share": round(pool["ring_stack_located"] / n, 4),
             "phantom_r_share": round(pool["phantom_r"] / max(1, pool["tracks_at_kills"]), 4),
             "phantom_gate_share": round(pool["phantom_gate"] / max(1, pool["tracks_at_kills"]), 4),
             "cheap_frame_share": round(pool["cheap_frames"] / max(1, pool["frames"]), 4),
             "surprises": pool["surprises"], "surprises_unexplained": pool["surprises_unexplained"]}
        (ANALYSIS / f"riot_pool_{args.pool}.json").write_text(
            json.dumps({"sessions": args.sessions, "pool": dict(pool), "values": v}, indent=1),
            encoding="utf-8")
        print(json.dumps(v, indent=1))
        if args.record:
            from reticle import metrics
            metrics.record("ally_prior", part="riot_pool", session=args.pool, values=v,
                           deps=deps, context={"sessions": args.sessions})
            print(" ".join(f"[metric:ally_prior/riot_pool@{args.pool}#{k}={x}]"
                           for k, x in v.items()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
