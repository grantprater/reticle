r"""Crowds: a bounded region teammates hide in, resolved when they emerge.

    .\.venv\Scripts\python.exe prototypes\crowd_region.py replay 9acf02f98283 [--record]
    .\.venv\Scripts\python.exe prototypes\crowd_region.py riot 3694746e4e54 a06f04a0059f bdfdcf009dba [--record]

The player's proposal (2026-10-04): "Can we not just have a rough bounded
'crowded' area that we then wait for icons to emerge from?" Today
`stack_fit` fits every frame whose ring fits fall short of the roster; it
costs about three fifths of the ally-icon reader's CPU. This prototype asks
what a crowd region gives and loses instead, over STORED rows only: the
`round_entity` observations and entities (the owners `round_lifetimes` and
`adjudication.identity` decided them), the `ally_icon` frame and icon rows,
the roster, the rounds and the death verdicts. It decodes no video, reads no
crop and changes no reader.

The crowd (`track_crowds`)
--------------------------
* **Opening.** An ally entity seen in the last frames vanishes for
  `VANISH_MS` while the roster still licenses more teammates than the frame's
  ring fits show (`round_lifetimes.ally_capacity` over `roster_window`, the
  owner's rule, asked per frame), and its last position lies within `JOIN_R`
  icon radii of a visible icon (an ally ring fit or the self fit): it hid
  under that icon. A visible icon whose ring-fit blob covers more than
  `BLOB_K` times the session's median isolated-icon area opens a crowd of
  unknown extra members (`blob`), with no hidden member named.
* **Region.** The convex hull of the crowd's visible anchors plus
  `MARGIN_R` icon radii. Anchors are the visible icons within `JOIN_R` radii
  of last frame's anchors; two crowds whose anchors meet merge. A crowd whose
  anchors all vanish keeps its last region for `ANCHORLESS_MS`, then closes
  with its members `lost`.
* **Members.** Each hidden member keeps its entry track: the entity id, the
  name `adjudication.identity` stored for it, the entry time and place. While
  hidden its position is the region, set-valued, `rests_on` that entry track;
  never a point. No more members hide than the roster's shortfall (capacity
  less the frame's ring fits); past it the longest-hidden end
  `count_restored`, seen again as some other entity.
* **Emergence.** A new entity first seen within the region (+`EMERGE_R`
  radii), or a hidden entity the tracker owner continued, emerges. Emergers
  of one crowd within `EMERGE_WINDOW_MS` are assigned jointly to its hidden
  members (`assign_emergers`, `scipy.optimize.linear_sum_assignment` over
  name agreement); one unnamed emerger against one unclaimed member is an
  elimination, and two or more are refused as a tie with the alternatives
  listed. Each emerger's name is then decided by the arbiter
  (`adjudication.identity.AgentIdentityArbiter`) over two claims: the stored
  entity verdict, and the crowd's claim, which `depends_on` the member's
  entry track, so it never counts as an independent witness.
* **Deaths.** A stored death verdict whose victim is a hidden member's name
  ends that member (`death_named`); the killfeed names who.
* **Opportunity for the joint stack fit** (fixed in advance in the store's
  `notes/predictions.jsonl`, task `crowd-region-20261004`): a death within
  `OPP_DEATH_MS` inside a region or naming a member, a spike plant within
  `OPP_DEATH_MS` while a crowd holds, the `PRE_EMERGE_MS` before an emergence
  the assignment refused or miscounted, and every `AUDIT_EVERY`-th crowd
  frame, an audit stored apart.

Scoring
-------
`replay` scores one capture against replay truth (`prototypes/replay_truth.py`,
evaluation only): whether each hidden member's true position lies in its
region, the region's area in m2, identity at emergence (right, wrong,
refused, against the replay's agent at the emerger's place), and how long
members stay unresolved.

`riot` scores the fixed handful at Riot kill instants
(`prototypes/riot_ground_truth.py`): the tracker runs on the ring fits alone
(the stored `stack_fit` members removed, as if the search never ran), and
each stacked living ally the ring fits miss is checked against the stored
stack-fit members and against the crowd regions. It prices the frames the
opportunity gate would skip with the ally-icon profile's stage costs, and
measures the stack members' facing against Riot's view angle (what a crowd
gives up).

Truth never feeds the tracker: `track_crowds` reads stored streams only.

Outcome (2026-10-04, crowd-region-0.2.0)
----------------------------------------
On 9acf02f98283 (development: 0.2.0's two rules were chosen there), a hidden
member's true position lies inside its region on
[metric:crowd_region/replay@9acf02f98283#containment=0.7841] of member-frames
(as fixed in advance, 0.1.0 gave
[metric:crowd_region/replay_dev@9acf02f98283#containment_0_1_0=0.6698]); the
region is one anchor's disc nearly always,
[metric:crowd_region/replay@9acf02f98283#region_m2_median=109.4] m2, a 12 m
circle, under Ascent's median callout spacing of
[metric:coaching_callouts/ascent@a06f04a0059f#nn_m_median=16.6] m. Members
stay hidden briefly: median
[metric:crowd_region/replay@9acf02f98283#unresolved_s_median=0.58] s, p90
[metric:crowd_region/replay@9acf02f98283#unresolved_s_p90=2.12] s; most
episodes end when the roster's shortfall closes. Named emergers are right on
[metric:crowd_region/replay@9acf02f98283#emergence_right_share=0.9016]; the
stored verdict does nearly all of that, and elimination named 3, 1 right.

On the fixed handful at Riot kill instants, of
[metric:crowd_region/riot_pool@fixed3#ring_missed=87] stacked living allies
the ring fits miss, stored stack-fit members match
[metric:crowd_region/riot_pool@fixed3#stack_matched=16] and a crowd region
contains [metric:crowd_region/riot_pool@fixed3#crowd_contains=34] (its member
list names the ally in [metric:crowd_region/riot_pool@fixed3#crowd_name_listed=13]);
[metric:crowd_region/riot_pool@fixed3#neither=47] are in neither, mostly
teammates whose track never entered a crowd. The opportunity gate skips
[metric:crowd_region/riot_pool@fixed3#skipped_share=0.925] of the frames
stack_fit ran on, but keeps only
[metric:crowd_region/riot_pool@fixed3#stack_matched_on_opportunity=3] of the 16
matches. Stack members' facing lies within 30 deg of Riot's view on
[metric:crowd_region/riot_pool@fixed3#stack_facing_within_30=0.625] of
[metric:crowd_region/riot_pool@fixed3#stack_facing_n=16].
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: 0.1.0 (2026-10-04): as fixed in advance (`JOIN_R` 4, no count rule):
#: [metric:crowd_region/replay_dev@9acf02f98283#containment_0_1_0=0.6698].
#: 0.2.0: a vanished entity hides only under an icon it overlaps (`JOIN_R` 2,
#: one icon diameter), and no more members hide than the roster's shortfall
#: (`track_crowds` step 4b); both chosen on 9acf02f98283, so its scores are
#: development scores and the fixed handful is the held-out check.
CROWD_REGION_VERSION = "crowd-region-0.2.0"
STORE = Path.home() / "reticle-store"
ANALYSIS = STORE / "analysis" / "crowd-region-20261004"
#: Where the stored streams are read; `--events-from` points it at a copy, so a
#: corpus rerun rewriting the store mid-run cannot mix revisions.
EVENTS = STORE / "events"

#: An entity unseen this long has vanished.
VANISH_MS = 200.0
#: A vanished entity joins a visible icon's crowd within this many icon radii
#: (one icon diameter: the icons overlap); anchors stay a crowd's within the
#: same distance.
JOIN_R = 2.0
#: The region's margin past the anchors' hull, in icon radii: a hidden icon's
#: centre lies within one diameter of the icon it hides under.
MARGIN_R = 2.0
#: A new entity this many radii past the region's margin is an emerger.
EMERGE_R = 2.0
#: Emergers of one crowd this close in time are assigned jointly.
EMERGE_WINDOW_MS = 1000.0
#: A crowd whose anchors all vanished keeps its region this long.
ANCHORLESS_MS = 3000.0
#: A blob larger than this times the session's median isolated-icon area opens
#: a crowd of unknown extra members.
BLOB_K = 1.5
#: Opportunity windows for the joint stack fit (fixed in advance).
OPP_DEATH_MS = 1000.0
PRE_EMERGE_MS = 500.0
AUDIT_EVERY = 15
#: Anchors kept per region row (padding for the vectorised containment test).
K_MAX = 6
#: The ally-icon reader's profile (workflow ally-icon-speed, 9 windows x 300
#: cached frames): mean ms per frame and stack_fit's share of it.
PROFILE_MEAN_MS = 98.1
PROFILE_STACK_SHARE = 0.595


def _below_normal() -> None:
    """Below Normal priority: the player's own jobs share this CPU."""
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:                                   # noqa: BLE001 -- best effort
        pass


def _stats(x, nd=2) -> dict | None:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if not x.size:
        return None
    return {"n": int(x.size), "median": round(float(np.median(x)), nd),
            "p10": round(float(np.percentile(x, 10)), nd),
            "p90": round(float(np.percentile(x, 90)), nd), "mean": round(float(x.mean()), nd)}


def _rows(path: Path, needle: str | None = None):
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if needle and needle not in line:
                continue
            if line.strip():
                yield json.loads(line)


# ----------------------------------------------------------------- stored data

class Session:
    """One session's stored streams as arrays (no decode, no crop).

    The `ally_icon` icon rows (blob area, stack origin, facing) join the
    `round_entity` observations by observation key only where the stored
    `round_entity` was built from that same `ally_icon` version; otherwise
    the join is refused (`ally_icon_stale`), blob-opened crowds are off and
    the frames serve only as the clock. The self fit's presence comes from
    the `round_entity` self observations either way."""

    def __init__(self, sid: str, drop_stack: bool = False):
        from reticle.store import Store

        self.sid = sid
        st = Store(STORE)
        self.manifest = st.read_manifest(sid)
        date = self.manifest["ingested_at"][:10]
        self.rounds = st.read_rounds(sid, date).to_pylist()
        rt = st.read_roster(sid, date)
        self.roster_t = [float(v) for v in rt.column("t_ms").to_pylist()]
        self.roster_a = rt.column("alive_ally").to_pylist()
        # ally_icon: frames (clock, drawn, self, stack_reason) and icon rows
        fr = {"f": [], "t": [], "drawn": [], "self": [], "ran": [], "has_reason": []}
        icon = {}
        for r in _rows(EVENTS / "ally_icon" / f"{sid}.jsonl"):
            k = r.get("kind")
            if k == "coverage":
                self.ally_icon_version = r.get("ally_icon_version")
                self.stack_fit_version = r.get("stack_fit_version")
            elif k == "frame":
                fr["f"].append(r["frame_idx"])
                fr["t"].append(r["t_ms"])
                fr["drawn"].append(bool(r.get("widget_drawn")))
                fr["self"].append(r.get("self") is not None)
                fr["has_reason"].append("stack_reason" in r)
                fr["ran"].append("stack_reason" in r and r["stack_reason"] is None
                                 and bool(r.get("widget_drawn")))
            elif k == "icon":
                icon[r["observation_key"]] = (r.get("area"), r.get("origin") == "stack_fit",
                                              r.get("facing"), r.get("r"))
        o = np.argsort(fr["f"], kind="stable")
        self.fr_f = np.asarray(fr["f"], np.int64)[o]
        self.fr_t = np.asarray(fr["t"], float)[o]
        self.fr_drawn = np.asarray(fr["drawn"], bool)[o]
        self.fr_self = np.asarray(fr["self"], bool)[o]
        self.fr_ran = np.asarray(fr["ran"], bool)[o]
        self.stack_recorded = bool(np.any(np.asarray(fr["has_reason"])))
        # round_entity: ally and self observations, entities
        ents, ob = {}, defaultdict(list)
        for r in _rows(EVENTS / "round_entity" / f"{sid}.jsonl"):
            k = r.get("kind")
            if k == "coverage":
                self.round_entity_inputs = r.get("inputs") or {}
                self.ally_icon_stale = (self.round_entity_inputs.get("ally_icon")
                                        != self.ally_icon_version)
                if self.ally_icon_stale:
                    icon = {}
            elif k == "entity" and r.get("family") in ("ally", "self"):
                ents[r["id"]] = r
            elif k == "observation" and r.get("family") in ("ally", "self"):
                ik = icon.get(r["observation_key"])
                is_stack = bool(ik and ik[1])
                if drop_stack and is_stack:
                    continue
                if r.get("entity_id") is None:
                    # an observation the tracker owner bound to no entity
                    self.unbound = getattr(self, "unbound", 0) + 1
                    continue
                ob["f"].append(r["frame_idx"])
                ob["t"].append(r["t_ms"])
                ob["e"].append(r["entity_id"])
                ob["x"].append(r["x"])
                ob["y"].append(r["y"])
                ob["self"].append(r["family"] == "self")
                ob["stack"].append(is_stack)
                ob["area"].append(np.nan if not ik or ik[0] is None else float(ik[0]))
                ob["facing"].append(np.nan if not ik or ik[2] is None else float(ik[2]))
                ob["key"].append(r["observation_key"])
        self.ents = ents
        self.ent_ids = sorted({*ob["e"]})
        code = {e: i for i, e in enumerate(self.ent_ids)}
        o = np.lexsort((np.asarray(ob["t"]), np.asarray(ob["f"])))
        self.ob_f = np.asarray(ob["f"], np.int64)[o]
        self.ob_t = np.asarray(ob["t"], float)[o]
        self.ob_e = np.asarray([code[e] for e in ob["e"]], np.int64)[o]
        self.ob_x = np.asarray(ob["x"], float)[o]
        self.ob_y = np.asarray(ob["y"], float)[o]
        self.ob_self = np.asarray(ob["self"], bool)[o]
        self.ob_stack = np.asarray(ob["stack"], bool)[o]
        self.ob_area = np.asarray(ob["area"], float)[o]
        self.ob_facing = np.asarray(ob["facing"], float)[o]
        self.ob_key = np.asarray(ob["key"], object)[o]
        self.agent = np.asarray([(ents.get(e) or {}).get("agent") for e in self.ent_ids], object)
        self.icon = icon
        self.fr_self = np.isin(self.fr_f, self.ob_f[self.ob_self])
        # the icon radius the reader measured, and one icon's blob area
        rs = [v[3] for v in icon.values() if v[3]]
        #: 6 px on the 331 px widget, scaled with it, where no icon row is joined
        self.r = float(np.median(rs)) if rs else None
        if self.r is None:
            from reticle import geometry
            with np.load(geometry.path_of(sid, STORE)) as z:
                self.r = 6.0 * z["labels"].shape[1] / 331.0
        self.blob_area = self._isolated_area()
        # deaths: the death owner's verdicts (victim named by the killfeed)
        self.deaths = [d for d in _rows(EVENTS / "death" / f"{sid}.jsonl",
                                        '"death_verdict"') if d.get("kind") == "death_verdict"]

    def _isolated_area(self) -> float | None:
        """Median blob area of ally ring fits with no other icon within 4 radii."""
        m = ~self.ob_self & np.isfinite(self.ob_area)
        f, x, y = self.ob_f, self.ob_x, self.ob_y
        # nearest other observation in the same frame, vectorised by frame blocks
        u, start = np.unique(f, return_index=True)
        cnt = np.diff(np.append(start, f.size))
        k = int(cnt.max()) if cnt.size else 0
        if k < 1:
            return None
        rank = np.arange(f.size) - np.repeat(start, cnt)
        blk = np.repeat(np.arange(u.size), cnt)
        X = np.full((u.size, k), np.nan)
        Y = np.full((u.size, k), np.nan)
        X[blk, rank], Y[blk, rank] = x, y
        D = np.hypot(X[blk] - x[:, None], Y[blk] - y[:, None])
        D[np.arange(f.size), rank] = np.inf
        nn = np.nanmin(np.where(np.isfinite(D), D, np.inf), axis=1)
        iso = m & (nn > 4 * self.r)
        return float(np.median(self.ob_area[iso])) if iso.any() else None


# ----------------------------------------------------------------- geometry

def hull_area_perimeter(pts: np.ndarray) -> tuple[float, float]:
    """Area and perimeter of the convex hull of a few points."""
    import cv2
    if len(pts) < 2:
        return 0.0, 0.0
    if len(pts) == 2:
        return 0.0, 2.0 * float(np.hypot(*(pts[0] - pts[1])))
    h = cv2.convexHull(pts.astype(np.float32))
    return float(cv2.contourArea(h)), float(cv2.arcLength(h, True))


def region_distance(px, py, A) -> np.ndarray:
    """Distance from points (n,) to the convex hull of anchors A (n, K, 2)
    padded with NaN: zero inside. The hull of a planar point set is the union
    of its points' triangles, so the distance is the least over points,
    segments and triangles, all vectorised."""
    n, K, _ = A.shape
    P = np.stack([px, py], axis=1)[:, None, :]
    d = np.nanmin(np.where(np.isfinite(A[..., 0]),
                           np.hypot(A[..., 0] - P[..., 0], A[..., 1] - P[..., 1]), np.inf), axis=1)
    ii, jj = np.triu_indices(K, 1)
    if ii.size:
        a, b = A[:, ii], A[:, jj]
        ab = b - a
        L2 = (ab ** 2).sum(-1)
        t = np.clip(((P - a) * ab).sum(-1) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
        q = a + t[..., None] * ab
        ds = np.hypot(*(q - P).transpose(2, 0, 1))
        ds = np.where(np.isfinite(ds), ds, np.inf)
        d = np.minimum(d, ds.min(axis=1))
    if K >= 3:
        from itertools import combinations
        tri = np.asarray(list(combinations(range(K), 3)))
        a, b, c = A[:, tri[:, 0]], A[:, tri[:, 1]], A[:, tri[:, 2]]

        def cross(o, u, v):
            return (u[..., 0] - o[..., 0]) * (v[..., 1] - o[..., 1]) - \
                   (u[..., 1] - o[..., 1]) * (v[..., 0] - o[..., 0])
        s1, s2, s3 = cross(a, b, P), cross(b, c, P), cross(c, a, P)
        inside = ((s1 >= 0) & (s2 >= 0) & (s3 >= 0)) | ((s1 <= 0) & (s2 <= 0) & (s3 <= 0))
        inside &= np.isfinite(s1) & np.isfinite(s2) & np.isfinite(s3)
        d = np.where(inside.any(axis=1), 0.0, d)
    return d


# ----------------------------------------------------------------- tracker

def assign_emergers(em_names: list, members: list[dict]) -> list[dict]:
    """Joint assignment of emergers to a crowd's hidden members.

    `em_names` holds each emerger's stored name (None when the arbiter left
    its entity unnamed). Named emergers take the member of that name; then
    one unnamed emerger against one unclaimed member is an elimination, and
    any other count is refused with the alternatives listed. Returns one row
    per emerger: `member` (index or None), `how`, `alternatives`."""
    from scipy.optimize import linear_sum_assignment

    n, m = len(em_names), len(members)
    out = [{"member": None, "how": None, "alternatives": []} for _ in range(n)]
    if m == 0:
        for r in out:
            r["how"] = "no_hidden_member"
        return out
    mn = np.asarray([mb["agent"] for mb in members], object)
    en = np.asarray(em_names, object)
    named = np.asarray([e is not None for e in em_names])
    match = (en[:, None] == mn[None, :]) & named[:, None]
    # cost: 0 for the member of the emerger's name; 1 for an unnamed emerger;
    # 3 for a named emerger against another name (a surprise, kept)
    C = np.where(match, 0.0, np.where(named[:, None], 3.0, 1.0))
    ri, ci = linear_sum_assignment(C)
    taken = set()
    for i, j in zip(ri, ci):
        if match[i, j]:
            out[i].update(member=int(j), how="name")
            taken.add(int(j))
    free = [j for j in range(m) if j not in taken]
    rest = [i for i in range(n) if out[i]["member"] is None]
    for i in rest:
        if named[i]:
            out[i].update(how="name_not_member",
                          alternatives=[members[j]["agent"] for j in free])
    unnamed = [i for i in rest if not named[i]]
    if len(unnamed) == 1 and len(free) == 1:
        out[unnamed[0]].update(member=free[0], how="elimination")
    else:
        for i in unnamed:
            out[i].update(how="tie" if len(free) > 1 else "no_free_member",
                          alternatives=[members[j]["agent"] for j in free])
    return out


def track_crowds(S: Session, join_r: float = JOIN_R, count_rule: bool = True) -> dict:
    """Crowds over one session's stored rows: region rows (one per crowd per
    frame), member rows (one per hidden member per frame), emergences,
    member episodes and the opportunity frames for the joint stack fit."""
    from reticle.adjudication.identity import AgentIdentityArbiter, identity_claim
    from reticle.round_lifetimes import ally_capacity, roster_window

    r = S.r
    join, margin, emerge = join_r * r, MARGIN_R * r, MARGIN_R * r + EMERGE_R * r
    blob_min = None if S.blob_area is None else BLOB_K * S.blob_area
    fpos = np.searchsorted(S.ob_f, S.fr_f, side="left")
    fend = np.searchsorted(S.ob_f, S.fr_f, side="right")
    region_rows, member_rows, emergences, episodes = [], [], [], []
    opp = defaultdict(set)          # frame_idx -> reasons
    crowd_frame_n = 0
    deaths = sorted(S.deaths, key=lambda d: d["t_ms"])
    d_t = np.asarray([d["t_ms"] for d in deaths], float)
    plants = np.asarray([rd["plant_t_ms"] for rd in S.rounds if rd.get("plant_t_ms")], float)
    for rd in S.rounds:
        t0, t1 = rd["t_start_ms"], rd["t_end_ms"]
        sel = np.flatnonzero((S.fr_t >= t0) & (S.fr_t <= t1) & S.fr_drawn)
        last = {}        # entity -> (t, x, y)
        seen = set()     # entities seen this round
        status = {}      # entity -> visible | hidden | gone | dead
        crowds = {}      # cid -> crowd
        hidden_in = {}   # entity -> cid
        next_cid = [0]
        prev_t = None

        def new_crowd(t, anchors, xy, kind):
            cid = f"{S.sid}:R{rd['round_no']}:C{next_cid[0]:03d}"
            next_cid[0] += 1
            crowds[cid] = {"id": cid, "onset": t, "anchors": dict(zip(anchors, xy)),
                           "hidden": {}, "kind": kind, "anchorless_since": None,
                           "pending": [], "frames": 0, "merged_from": []}
            return crowds[cid]

        def end_member(c, e, t, how, extra=None):
            mb = c["hidden"].pop(e)
            hidden_in.pop(e, None)
            episodes.append({**mb, "crowd": c["id"], "end_t": t, "end": how,
                             "unresolved_ms": t - mb["onset"], **(extra or {})})

        for k in sel:
            fidx, t = int(S.fr_f[k]), float(S.fr_t[k])
            a, b = fpos[k], fend[k]
            ids, xs, ys = S.ob_e[a:b], S.ob_x[a:b], S.ob_y[a:b]
            selfs, areas = S.ob_self[a:b], S.ob_area[a:b]
            vis = {int(e): (float(x), float(y)) for e, x, y in zip(ids, xs, ys)}
            n_ally = int((~selfs).sum())
            cap = ally_capacity(roster_window(S.roster_t, S.roster_a, t), bool(S.fr_self[k]))
            short = cap is not None and n_ally < cap
            # 1. hidden entities the tracker owner continued: emergence by continuity
            for e in [e for e in vis if e in hidden_in]:
                c = crowds[hidden_in[e]]
                c["pending"].append({"e": e, "t": t, "fidx": fidx, "xy": vis[e],
                                     "continued": True})
                c["hidden"][e]["claimed_by_continuity"] = True
            # 2. new entities near a crowd with hidden members: emergers
            for e in [e for e in vis if e not in seen]:
                best, bd = None, np.inf
                for c in crowds.values():
                    if not c["hidden"] or not c["anchors"]:
                        continue
                    A = np.asarray(list(c["anchors"].values()), float)[None, :K_MAX]
                    d = float(region_distance(np.array([vis[e][0]]), np.array([vis[e][1]]), A)[0])
                    if d <= emerge and d < bd:
                        best, bd = c, d
                if best is not None:
                    best["pending"].append({"e": e, "t": t, "fidx": fidx, "xy": vis[e],
                                            "continued": False})
            for e, xy in vis.items():
                last[e] = (t, *xy)
                seen.add(e)
                if status.get(e) != "hidden":
                    status[e] = "visible"
            # 3. anchors: last frame's anchors still visible, plus visible icons near them
            for c in crowds.values():
                prev = np.asarray(list(c["anchors"].values()), float).reshape(-1, 2)
                keep = {}
                for e, xy in vis.items():
                    if e in c["hidden"]:
                        continue
                    if e in c["anchors"] or (prev.size and np.min(np.hypot(prev[:, 0] - xy[0],
                                                                          prev[:, 1] - xy[1])) <= join):
                        keep[e] = xy
                if keep:
                    c["anchors"], c["anchorless_since"] = keep, None
                elif c["anchorless_since"] is None:
                    c["anchorless_since"] = t
            # 4. vanished entities: hide in the nearest visible icon's crowd
            for e, (tl, x, y) in list(last.items()):
                if status.get(e) != "visible" or e in vis or t - tl < VANISH_MS:
                    continue
                if not short or not vis:
                    status[e] = "gone"
                    continue
                cand = [(np.hypot(v[0] - x, v[1] - y), ve) for ve, v in vis.items()]
                dmin, ve = min(cand)
                if dmin > join:
                    status[e] = "gone"
                    continue
                c = next((c for c in crowds.values() if ve in c["anchors"]), None)
                if c is None:
                    c = new_crowd(t, [ve], [vis[ve]], "hidden")
                c["hidden"][e] = {"entity": S.ent_ids[e], "agent": S.agent[e], "onset": tl,
                                  "entry_xy": [round(x, 2), round(y, 2)], "entry_t": tl,
                                  "entry_anchor": S.ent_ids[ve], "e": e,
                                  "entry_gap_px": round(float(dmin), 2),
                                  "entry_anchor_self": bool(selfs[ids == ve].any()),
                                  "entry_anchor_area": float(np.nanmax(areas[ids == ve],
                                                                       initial=np.nan))}
                hidden_in[e] = c["id"]
                status[e] = "hidden"
            # 4b. the count: no more members hide than the roster's shortfall;
            # past it, the longest hidden were seen again as other entities
            if count_rule and cap is not None:
                hid = sorted(((mb["onset"], c["id"], e) for c in crowds.values()
                              for e, mb in c["hidden"].items()))
                for _on, cid, e in hid[:max(0, len(hid) - max(0, cap - n_ally))]:
                    end_member(crowds[cid], e, t, "count_restored")
                    status[e] = "gone"
            # 5. blob-opened crowds: an anchor whose blob is wider than one icon
            if blob_min is not None:
                big = [int(ids[i]) for i in np.flatnonzero(np.nan_to_num(areas) > blob_min)]
                for e in big:
                    if not any(e in c["anchors"] for c in crowds.values()):
                        new_crowd(t, [e], [vis[e]], "blob")
            # 6. merges: crowds sharing an anchor or with anchors within `join`
            cl = list(crowds.values())
            for i in range(len(cl)):
                for j in range(i + 1, len(cl)):
                    ci, cj = cl[i], cl[j]
                    if ci["id"] not in crowds or cj["id"] not in crowds:
                        continue
                    pi = np.asarray(list(ci["anchors"].values()), float).reshape(-1, 2)
                    pj = np.asarray(list(cj["anchors"].values()), float).reshape(-1, 2)
                    if not (pi.size and pj.size):
                        continue
                    dd = np.hypot(pi[:, None, 0] - pj[None, :, 0], pi[:, None, 1] - pj[None, :, 1])
                    if dd.min() <= join:
                        keep_c, drop_c = (ci, cj) if ci["onset"] <= cj["onset"] else (cj, ci)
                        keep_c["anchors"].update(drop_c["anchors"])
                        keep_c["hidden"].update(drop_c["hidden"])
                        keep_c["pending"] += drop_c["pending"]
                        keep_c["merged_from"].append(drop_c["id"])
                        if drop_c["hidden"]:
                            keep_c["kind"] = "hidden"
                        for e in drop_c["hidden"]:
                            hidden_in[e] = keep_c["id"]
                        del crowds[drop_c["id"]]
            # 7. deaths the killfeed names: a hidden member of that name ends
            if d_t.size:
                lo, hi = np.searchsorted(d_t, [prev_t if prev_t is not None else t - 1, t],
                                         side="right")
                for d in deaths[lo:hi]:
                    for c in crowds.values():
                        for e, mb in list(c["hidden"].items()):
                            if (mb["agent"] is not None and d.get("side") == "ally"
                                    and d.get("victim") == mb["agent"]):
                                end_member(c, e, t, "death_named",
                                           {"death_t_ms": d["t_ms"], "victim": d.get("victim")})
                                status[e] = "dead"
            # 8. resolve emergers whose window closed (or that cover every hidden member)
            for c in crowds.values():
                if not c["pending"]:
                    continue
                first = min(p["t"] for p in c["pending"])
                if t - first < EMERGE_WINDOW_MS and len(c["pending"]) < len(c["hidden"]):
                    continue
                pend, c["pending"] = c["pending"], []
                members = list(c["hidden"].values())
                cont = [p for p in pend if p["continued"]]
                fresh = [p for p in pend if not p["continued"]]
                # continued entities keep their own entry track
                for p in cont:
                    e = p["e"]
                    if e not in c["hidden"]:
                        continue
                    mb = c["hidden"][e]
                    emergences.append(_emergence(S, c, p, mb, "continuity", [], AgentIdentityArbiter,
                                                 identity_claim))
                    end_member(c, e, p["t"], "emerged", {"how": "continuity"})
                    status[e] = "visible"
                members = list(c["hidden"].values())
                if fresh:
                    asg = assign_emergers([S.agent[p["e"]] for p in fresh], members)
                    failed = False
                    for p, g in zip(fresh, asg):
                        mb = members[g["member"]] if g["member"] is not None else None
                        emergences.append(_emergence(S, c, p, mb, g["how"], g["alternatives"],
                                                     AgentIdentityArbiter, identity_claim))
                        if mb is not None and mb["e"] in c["hidden"]:
                            end_member(c, mb["e"], p["t"], "emerged",
                                       {"how": g["how"], "emerger": S.ent_ids[p["e"]]})
                            status[mb["e"]] = "gone"
                        else:
                            failed = True
                    if failed:
                        for p in fresh:
                            m = (S.fr_t >= p["t"] - PRE_EMERGE_MS) & (S.fr_t <= p["t"])
                            for f in S.fr_f[m]:
                                opp[int(f)].add("emergence_failed")
            # 9. close crowds: anchorless too long, or nothing hidden and no blob
            for cid in list(crowds):
                c = crowds[cid]
                if c["anchorless_since"] is not None and t - c["anchorless_since"] > ANCHORLESS_MS:
                    for e in list(c["hidden"]):
                        end_member(c, e, t, "lost")
                        status[e] = "gone"
                    del crowds[cid]
                    continue
                big = blob_min is not None and any(
                    np.nan_to_num(areas[ids == e]).max(initial=0) > blob_min
                    for e in c["anchors"] if e in vis)
                if not c["hidden"] and not c["pending"] and not big:
                    del crowds[cid]
            # 10. record region and member rows; opportunities
            if crowds:
                crowd_frame_n += 1
                if crowd_frame_n % AUDIT_EVERY == 0:
                    opp[fidx].add("audit")
                if plants.size and np.min(np.abs(plants - t)) <= OPP_DEATH_MS:
                    opp[fidx].add("spike_plant")
            for c in crowds.values():
                A = np.asarray(list(c["anchors"].values()), float).reshape(-1, 2)[:K_MAX]
                area, per = hull_area_perimeter(A)
                c["frames"] += 1
                pad = np.full((K_MAX, 2), np.nan)
                pad[:len(A)] = A
                region_rows.append({"crowd": c["id"], "fidx": fidx, "t": t, "kind": c["kind"],
                                    "anchors": pad, "n_anchors": len(A),
                                    "anchorless": c["anchorless_since"] is not None,
                                    "hidden": len(c["hidden"]),
                                    "area_px2": area + per * margin + math.pi * margin ** 2})
                names = {mb["agent"] for mb in c["hidden"].values()}
                for e, mb in c["hidden"].items():
                    member_rows.append({"crowd": c["id"], "fidx": fidx, "t": t, "e": e,
                                        "anchors": pad, "anchorless": c["anchorless_since"]
                                        is not None, "region_row": len(region_rows) - 1})
                if d_t.size and A.size:
                    near = np.flatnonzero(np.abs(d_t - t) <= OPP_DEATH_MS)
                    for i in near:
                        d = deaths[i]
                        loc = d.get("location")
                        inside = False
                        if loc:
                            inside = float(region_distance(np.array([loc[0]]), np.array([loc[1]]),
                                                           pad[None])[0]) <= margin
                        if inside or (d.get("side") == "ally" and d.get("victim") in names):
                            opp[fidx].add("death")
            prev_t = t
        # round end: whatever is still hidden is censored
        for c in crowds.values():
            for e in list(c["hidden"]):
                end_member(c, e, t1, "round_end")
            for p in c["pending"]:
                emergences.append(_emergence(S, c, p, None, "round_end", [], AgentIdentityArbiter,
                                             identity_claim))
    return {"regions": region_rows, "members": member_rows, "emergences": emergences,
            "episodes": episodes, "opportunity": {k: sorted(v) for k, v in opp.items()},
            "crowd_frames": crowd_frame_n, "r_px": r, "margin_px": margin,
            "blob_area_px": S.blob_area}


def _emergence(S, c, p, mb, how, alternatives, Arbiter, identity_claim) -> dict:
    """One emerger's identity: the arbiter over the stored entity verdict and
    the crowd's claim (which depends on the member's entry track)."""
    ent_id = S.ent_ids[p["e"]]
    stored = S.agent[p["e"]]
    ar = Arbiter()
    ar.add(identity_claim(ent_id, stored, channel="round_entity_verdict",
                          observed_at_ms=p["t"],
                          reason=None if stored else "entity_unnamed",
                          source_version=(S.ents.get(ent_id) or {}).get("round_entity_version")))
    crowd_agent = mb["agent"] if mb is not None else None
    ar.add(identity_claim(
        ent_id, crowd_agent, channel="crowd_membership", observed_at_ms=p["t"],
        reason=None if crowd_agent else (how if mb is None else "member_unnamed"),
        source_version=CROWD_REGION_VERSION,
        depends_on=[mb["entity"]] if mb is not None else None,
        evidence={"crowd": c["id"], "how": how, "alternatives": alternatives,
                  "members": [m["agent"] for m in c["hidden"].values()],
                  "rests_on": mb["entity"] if mb is not None else None}))
    v = ar.verdict()[0]
    return {"crowd": c["id"], "fidx": p["fidx"], "t": p["t"], "x": p["xy"][0], "y": p["xy"][1],
            "entity": ent_id, "stored_agent": stored, "crowd_agent": crowd_agent,
            "member_entity": mb["entity"] if mb is not None else None, "how": how,
            "alternatives": alternatives, "agent": v["agent"], "status": v["status"],
            "reason": v["reason"], "continued": p["continued"]}


# ----------------------------------------------------------------- truth: replay

def replay_context(sid: str):
    """Replay truth for `sid` (evaluation only): the replay, map frame,
    capture->replay alignment, allies and their agents."""
    import replay_truth as rt
    import riot_ground_truth as rg
    from reticle.store import Store

    store = Store(STORE)
    man = store.read_manifest(sid)
    recs = rg.riot_records(STORE)
    d = recs.get(sid)
    rep = json.loads((rt.REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    entry = next(f for f in rep["files"] if f.get("capture_session") == sid)
    rp = rt.Replay(Path(entry["file"]).stem)
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    ident = rg.identify_player(recs, STORE).get(sid, {})
    me = ident.get("subject")
    team = {p["subject"]: p["teamId"] for p in d["match"]["players"]}
    allies = [s for s in rp.subjects if team.get(s) == team[me]]
    agent = {s: ref.agent(c) for s, c in rp.loadouts().items()}
    kill_like, _ = rg.split_deaths(rg.stored_deaths(STORE, sid))
    al = rg.fit_alignment([e["t"] for e in rp.group("characterDeath")],
                          [float(r["t_ms"]) for r in kill_like])
    mf, why = rg.map_frame_for(sid, man, ref, {"match": {"matchInfo": {"mapId": rp.map_url()}}},
                               STORE)
    assert mf is not None, why
    return {"rp": rp, "mf": mf, "a": al["a_ms"], "allies": allies,
            "agents": [agent.get(s) for s in allies], "me": me, "lag": rg.MINIMAP_LAG_MS}


def truth_px(ctx, t_cap):
    """(n, k) truth px of the allies at capture times, NaN where dead or unknown."""
    import replay_truth as rt
    rp, mf = ctx["rp"], ctx["mf"]
    t_rep = rt._frames_to_replay(t_cap, ctx["a"], ctx["lag"])
    k = len(ctx["allies"])
    X, Y = np.full((t_rep.size, k), np.nan), np.full((t_rep.size, k), np.nan)
    for c, s in enumerate(ctx["allies"]):
        q = rp.sample(s, t_rep)
        live = rp.alive(s, t_rep)
        px, py = rt.to_px(mf, q["x"], q["y"])
        X[:, c] = np.where(live, px, np.nan)
        Y[:, c] = np.where(live, py, np.nan)
    return X, Y


def entity_truth(S: Session, ctx) -> np.ndarray:
    """Each entity's truth ally: the majority over its observations' one-to-one
    assignment to truth within the replay gate (-1 where none)."""
    import replay_truth as rt
    import riot_ground_truth as rg
    gate = rg.GATE_M * 100.0 * ctx["mf"].px_per_unit
    X, Y = truth_px(ctx, S.ob_t)
    D = np.hypot(X - S.ob_x[:, None], Y - S.ob_y[:, None])
    j, _ = rt._assign(S.ob_f, D, gate)
    k = len(ctx["allies"])
    ok = j >= 0
    M = np.zeros((len(S.ent_ids), k), np.int64)
    np.add.at(M, (S.ob_e[ok], j[ok]), 1)
    best = M.argmax(axis=1)
    return np.where(M.max(axis=1) > 0, best, -1), j


def score_replay(sid: str, S: Session | None = None, ctx=None, **kw) -> dict:
    import riot_ground_truth as rg
    t0 = time.time()
    S = S or Session(sid)
    R = track_crowds(S, **kw)
    ctx = ctx or replay_context(sid)
    m_per_px = 1.0 / (ctx["mf"].px_per_unit * 100.0)
    ent_truth, ob_truth = entity_truth(S, ctx)
    out = {"session": sid, "capture": S.manifest["source"]["path"],
           "crowd_region_version": CROWD_REGION_VERSION, "ally_icon_version": S.ally_icon_version,
           "ally_icon_stale": S.ally_icon_stale, "round_entity_inputs": S.round_entity_inputs,
           "events_from": str(EVENTS),
           "r_px": round(S.r, 2), "margin_px": R["margin_px"], "m_per_px": round(m_per_px, 4),
           "blob_area_px": S.blob_area, "crowd_frames": R["crowd_frames"],
           "drawn_frames": int(S.fr_drawn.sum()), "crowds": len({g["crowd"] for g in R["regions"]}),
           "params": {"join_r": kw.get("join_r", JOIN_R), "count_rule": kw.get("count_rule", True),
                      "margin_r": MARGIN_R}}
    # (1) containment: hidden members' true positions against their region
    M = R["members"]
    if M:
        t = np.asarray([m["t"] for m in M])
        e = np.asarray([m["e"] for m in M])
        A = np.stack([m["anchors"] for m in M])
        anchorless = np.asarray([m["anchorless"] for m in M])
        X, Y = truth_px(ctx, t)
        js = ent_truth[e]
        has = js >= 0
        tx = np.where(has, X[np.arange(t.size), np.clip(js, 0, None)], np.nan)
        ty = np.where(has, Y[np.arange(t.size), np.clip(js, 0, None)], np.nan)
        live = np.isfinite(tx)
        d = region_distance(np.nan_to_num(tx), np.nan_to_num(ty), A)
        inside = live & (d <= R["margin_px"])
        out["containment"] = {
            "member_frames": int(t.size), "truth_unassigned_entity": int((~has).sum()),
            "truth_dead_or_unknown": int((has & ~live).sum()), "scored": int(live.sum()),
            "inside": int(inside.sum()),
            "share": round(float(inside.sum() / max(1, live.sum())), 4),
            "share_anchored": round(float((inside & ~anchorless).sum()
                                          / max(1, (live & ~anchorless).sum())), 4),
            "share_anchorless": round(float((inside & anchorless).sum()
                                            / max(1, (live & anchorless).sum())), 4),
            "outside_by_m": _stats((d[live & ~inside] - R["margin_px"]) * m_per_px),
            "share_by_margin_r": {str(k): round(float((live & (d <= k * S.r)).sum()
                                                      / max(1, live.sum())), 4)
                                  for k in (1, 1.5, 2, 3, 4)}}
        # the members' true spread: does a teammate stand where the crowd says?
    # (2) region size
    G = R["regions"]
    if G:
        ar = np.asarray([g["area_px2"] for g in G]) * m_per_px ** 2
        hid = np.asarray([g["hidden"] for g in G])
        kind = np.asarray([g["kind"] for g in G])
        out["region_m2"] = {"all": _stats(ar, 1), "with_hidden": _stats(ar[hid > 0], 1),
                            "blob_only": _stats(ar[kind == "blob"], 1),
                            "equivalent_diameter_m": _stats(2 * np.sqrt(ar[hid > 0] / math.pi), 1)}
        out["region_rows"] = {"hidden": int((hid > 0).sum()), "blob": int((kind == "blob").sum())}
    # (3) identity at emergence, against the replay's agent at the emerger's place
    E = R["emergences"]
    if E:
        gate = rg.GATE_M * 100.0 * ctx["mf"].px_per_unit
        et = np.asarray([x["t"] for x in E])
        ex = np.asarray([x["x"] for x in E])
        ey = np.asarray([x["y"] for x in E])
        X, Y = truth_px(ctx, et)
        D = np.hypot(X - ex[:, None], Y - ey[:, None])
        Dm = np.where(np.isfinite(D), D, np.inf)
        jj = Dm.argmin(axis=1)
        dd = Dm[np.arange(et.size), jj]
        srt = np.sort(Dm, axis=1)
        amb = (srt[:, 1] - srt[:, 0] < 2.0 * 100.0 * ctx["mf"].px_per_unit) if Dm.shape[1] > 1 \
            else np.zeros(et.size, bool)
        tru = np.asarray([ctx["agents"][j] if d_ <= gate else None for j, d_ in zip(jj, dd)],
                         object)

        def outcome(names):
            o = []
            for n, tr, a_ in zip(names, tru, amb):
                if tr is None:
                    o.append("no_truth")
                elif a_:
                    o.append("ambiguous")
                elif n is None:
                    o.append("refused")
                else:
                    o.append("right" if rg.canon(n) == rg.canon(tr) else "wrong")
            return np.asarray(o)
        crowd_o = outcome([x["agent"] for x in E])
        stored_o = outcome([x["stored_agent"] for x in E])
        how = np.asarray([x["how"] for x in E])
        status = np.asarray([x["status"] for x in E])

        def tally(o, m=None):
            m = np.ones(o.size, bool) if m is None else m
            c = Counter(o[m].tolist())
            named = c["right"] + c["wrong"]
            return {**dict(c), "named_right_share": round(c["right"] / max(1, named), 4),
                    "refused_share_of_scored": round(c["refused"] / max(1, named + c["refused"]), 4)}
        out["emergence"] = {
            "emergers": len(E), "by_how": dict(Counter(how.tolist())),
            "arbiter_status": dict(Counter(status.tolist())),
            "crowd_and_arbiter": tally(crowd_o), "stored_verdict_only": tally(stored_o),
            "by_how_outcome": {h: tally(crowd_o, how == h) for h in sorted(set(how.tolist()))},
            "elimination_gain": {
                "stored_refused_crowd_right": int(((stored_o == "refused") & (crowd_o == "right")).sum()),
                "stored_refused_crowd_wrong": int(((stored_o == "refused") & (crowd_o == "wrong")).sum()),
                "stored_wrong_crowd_refused": int(((stored_o == "wrong") & (crowd_o == "refused")).sum()),
                "stored_right_crowd_refused": int(((stored_o == "right") & (crowd_o == "refused")).sum())},
            "examples_wrong": [{k: E[i][k] for k in ("t", "entity", "stored_agent", "crowd_agent",
                                                     "how", "status")} | {"truth": tru[i]}
                               for i in np.flatnonzero(crowd_o == "wrong")[:10]]}
    # (4) unresolved spans
    P = R["episodes"]
    if P:
        un = np.asarray([p["unresolved_ms"] for p in P]) / 1000.0
        end = np.asarray([p["end"] for p in P])
        out["unresolved_s"] = {"episodes": len(P), "by_end": dict(Counter(end.tolist())),
                               "all": _stats(un), **{h: _stats(un[end == h])
                                                     for h in sorted(set(end.tolist()))}}
    out["opportunity_frames"] = dict(Counter(r_ for v in R["opportunity"].values() for r_ in v))
    out["opportunity_frames_any"] = len(R["opportunity"])
    out["seconds"] = round(time.time() - t0, 1)
    return out


# ----------------------------------------------------------------- truth: Riot

def riot_context(sid: str):
    import riot_ground_truth as rg
    from reticle.store import Store
    store = Store(STORE)
    man = store.read_manifest(sid)
    recs = rg.riot_records(STORE)
    d = recs[sid]
    ident = rg.identify_player(recs, STORE).get(sid, {})
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    m = d["match"]
    who = {p["subject"]: p for p in m["players"]}
    agent_of = {s: ref.agent(p["characterId"]) for s, p in who.items()}
    me = ident.get("subject")
    my_team = who[me]["teamId"]
    kill_like, _ = rg.split_deaths(rg.stored_deaths(STORE, sid))
    kills = sorted(m["kills"], key=lambda k: k["gameTime"])
    al = rg.fit_alignment([k["gameTime"] for k in kills], [float(r["t_ms"]) for r in kill_like])
    mf, why = rg.map_frame_for(sid, man, ref, d, STORE)
    assert mf is not None, why
    return {"kills": kills, "a": al["a_ms"], "mf": mf, "who": who, "agent_of": agent_of,
            "me": me, "team": my_team}


def score_riot(sid: str) -> dict:
    """At Riot kill instants: stacked living allies the ring fits miss, against
    stored stack-fit members and against the crowd regions built without them;
    the CPU the opportunity gate saves; stack members' facing against Riot."""
    import riot_ground_truth as rg
    t0 = time.time()
    S_all = Session(sid)
    S = Session(sid, drop_stack=True)
    R = track_crowds(S)
    ctx = riot_context(sid)
    mf = ctx["mf"]
    gate = rg.GATE_M * 100.0 * mf.px_per_unit
    m_per_px = 1.0 / (mf.px_per_unit * 100.0)
    out = {"session": sid, "capture": S.manifest["source"]["path"],
           "crowd_region_version": CROWD_REGION_VERSION, "ally_icon_version": S.ally_icon_version,
           "stack_fit_version": S.stack_fit_version, "r_px": round(S.r, 2),
           "ally_icon_stale": S.ally_icon_stale, "events_from": str(EVENTS),
           "m_per_px": round(m_per_px, 4), "crowd_frames": R["crowd_frames"]}
    # frame of each kill instant (the minimap shows the game ~450 ms late)
    want = np.asarray([ctx["a"] + k["gameTime"] + rg.MINIMAP_LAG_MS for k in ctx["kills"]])
    fi = np.clip(np.searchsorted(S.fr_t, want), 1, S.fr_t.size - 1)
    fi = np.where(np.abs(S.fr_t[fi - 1] - want) <= np.abs(S.fr_t[fi] - want), fi - 1, fi)
    ok_f = (np.abs(S.fr_t[fi] - want) <= rg.FRAME_TOL_MS) & S.fr_drawn[fi]
    regions_by_f = defaultdict(list)
    for g in R["regions"]:
        regions_by_f[g["fidx"]].append(g)
    opp_f = set(R["opportunity"])
    names_by_crowd = defaultdict(set)
    for mrow in R["members"]:
        names_by_crowd[(mrow["crowd"], mrow["fidx"])].add(S.agent[mrow["e"]])
    c = Counter()
    stack_err, fac = [], defaultdict(list)
    dying_at = defaultdict(list)
    for k in ctx["kills"]:
        dying_at[(k["round"], k["gameTime"])].append(k)
    for k, f_i, okk in zip(ctx["kills"], fi, ok_f):
        if not okk:
            c["kill_no_frame"] += 1
            continue
        fidx = int(S.fr_f[f_i])
        locs = rg.truth_locations(k, dying_at)
        allies = [s for s in locs if ctx["who"][s]["teamId"] == ctx["team"]
                  and not locs[s].get("victim_added")]
        if not allies:
            continue
        T = np.asarray([mf.to_px(locs[s]["location"]["x"], locs[s]["location"]["y"])
                        for s in allies])
        DD = np.hypot(T[:, None, 0] - T[None, :, 0], T[:, None, 1] - T[None, :, 1])
        np.fill_diagonal(DD, np.inf)
        stacked = DD.min(axis=1) < 2 * mf.icon_px
        a_, b_ = np.searchsorted(S_all.ob_f, [fidx, fidx + 1])
        ox, oy = S_all.ob_x[a_:b_], S_all.ob_y[a_:b_]
        ost, oe = S_all.ob_stack[a_:b_], S_all.ob_e[a_:b_]
        ofac = S_all.ob_facing[a_:b_]
        ring = [(x, y) for x, y, s_ in zip(ox, oy, ost) if not s_]
        rp = rg.greedy_pairs([tuple(p) for p in T], ring, gate)
        ring_hit = {i for i, _j, _d in rp}
        stk_idx = np.flatnonzero(ost)
        sp = rg.greedy_pairs([tuple(p) for i, p in enumerate(T) if i not in ring_hit],
                             [(ox[j], oy[j]) for j in stk_idx], gate)
        free = [i for i in range(len(allies)) if i not in ring_hit]
        stk_hit = {free[i]: (stk_idx[j], d_) for i, j, d_ in sp}
        regs = regions_by_f.get(fidx, [])
        for i, s in enumerate(allies):
            if not stacked[i]:
                continue
            c["stacked_allies"] += 1
            c["stacked_on_opportunity"] += int(fidx in opp_f)
            if i in ring_hit:
                c["ring_matched"] += 1
                continue
            c["ring_missed"] += 1
            truth_agent = ctx["agent_of"].get(s)
            if i in stk_hit:
                j, d_ = stk_hit[i]
                c["stack_matched"] += 1
                # would the opportunity gate have run the search on this frame?
                c["stack_matched_on_opportunity"] += int(fidx in opp_f)
                stack_err.append(d_ * m_per_px)
                name = S_all.agent[oe[j]]
                c["stack_named_" + ("refused" if name is None else
                                    "right" if rg.canon(name) == rg.canon(truth_agent)
                                    else "wrong")] += 1
                if np.isfinite(ofac[j]) and locs[s].get("viewRadians") is not None:
                    for cn, fn in rg.FACING_CONVENTIONS.items():
                        td = mf.facing_deg(locs[s]["location"]["x"], locs[s]["location"]["y"],
                                           fn(locs[s]["viewRadians"]))
                        fac[cn].append(rg.angle_err(td, float(ofac[j])))
            inside = None
            for g in regs:
                dd = float(region_distance(np.array([T[i, 0]]), np.array([T[i, 1]]),
                                           g["anchors"][None])[0])
                if dd <= R["margin_px"]:
                    inside = g
                    break
            if inside is None:
                c["crowd_missed"] += 1
                c["neither_" + ("stack" if i in stk_hit else "none")] += 1
                continue
            c["crowd_contains"] += 1
            c["crowd_kind_" + inside["kind"]] += 1
            names = names_by_crowd.get((inside["crowd"], fidx), set())
            c["crowd_member_name_" + ("unknown" if not names else
                                      "listed" if any(rg.canon(n) == rg.canon(truth_agent)
                                                      for n in names if n) else "absent")] += 1
            if i in stk_hit:
                c["both_stack_and_crowd"] += 1
            c["crowd_area_m2_sum"] += inside["area_px2"] * m_per_px ** 2
    miss = max(1, c["ring_missed"])
    out["kill_instants"] = dict(c)
    out["kill_instants"]["stack_match_share_of_ring_missed"] = round(c["stack_matched"] / miss, 4)
    out["kill_instants"]["crowd_contain_share_of_ring_missed"] = round(c["crowd_contains"] / miss, 4)
    out["kill_instants"]["crowd_mean_area_m2"] = round(c["crowd_area_m2_sum"] / max(1, c["crowd_contains"]), 1)
    out["stack_err_m"] = _stats(stack_err)
    fac_s = {cn: _stats(v, 1) for cn, v in fac.items()}
    best = min(fac_s, key=lambda cn: fac_s[cn]["median"]) if fac_s else None
    out["stack_facing"] = None if best is None else {
        "convention": best, "err_deg": fac_s[best], "samples": [round(v, 1) for v in fac[best]],
        "within_30": round(float(np.mean(np.asarray(fac[best]) <= 30)), 4)}
    # CPU: the frames stack_fit ran on, against the opportunity frames
    ran = S.fr_ran
    crowd_f = {g["fidx"] for g in R["regions"]}
    opp = R["opportunity"]
    in_crowd = np.isin(S.fr_f, list(crowd_f))
    in_opp = np.isin(S.fr_f, list(opp))
    keep = ran & in_opp
    n_ran = int(ran.sum())
    skipped = 1.0 - keep.sum() / max(1, n_ran)
    stack_ms = PROFILE_MEAN_MS * PROFILE_STACK_SHARE
    out["cpu"] = {"drawn_frames": int(S.fr_drawn.sum()), "stack_ran": n_ran,
                  "stack_ran_in_crowd": int((ran & in_crowd).sum()),
                  "stack_ran_outside_crowd": int((ran & ~in_crowd).sum()),
                  "crowd_frames": int(in_crowd.sum()), "opportunity_frames": int(in_opp.sum()),
                  "stack_kept": int(keep.sum()),
                  "kept_by_reason": dict(Counter(r_ for f in S.fr_f[keep] for r_ in opp[int(f)])),
                  "skipped_share": round(float(skipped), 4),
                  "saved_ms_per_frame": round(float(skipped * stack_ms), 1),
                  "saved_share_of_reader": round(float(skipped * PROFILE_STACK_SHARE), 4),
                  "priced_with": {"mean_ms": PROFILE_MEAN_MS, "stack_share": PROFILE_STACK_SHARE}}
    # (d) what a crowd gives up: stack members' facings stored on this session
    out["stack_members_stored"] = int(S_all.ob_stack.sum())
    out["stack_members_with_facing"] = int((S_all.ob_stack & np.isfinite(S_all.ob_facing)).sum())
    E = R["emergences"]
    out["emergence_how"] = dict(Counter(x["how"] for x in E))
    P = R["episodes"]
    if P:
        un = np.asarray([p["unresolved_ms"] for p in P]) / 1000.0
        out["unresolved_s"] = _stats(un)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("replay")
    p.add_argument("session")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("riot")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--record", action="store_true")
    ap.add_argument("--events-from", type=Path, default=None,
                    help="read the stored streams from this copy of <store>/events")
    args = ap.parse_args(argv)
    _below_normal()
    global EVENTS
    if args.events_from:
        EVENTS = args.events_from
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    deps = {"crowd_region": CROWD_REGION_VERSION}
    if args.cmd == "replay":
        s = score_replay(args.session)
        (ANALYSIS / f"replay_{args.session}.json").write_text(
            json.dumps(s, indent=1, default=_default), encoding="utf-8")
        print(json.dumps(s, indent=1, default=_default))
        if args.record:
            from reticle import metrics
            v = {"containment": s["containment"]["share"],
                 "region_m2_median": s["region_m2"]["with_hidden"]["median"],
                 "region_m2_p90": s["region_m2"]["with_hidden"]["p90"],
                 "emergence_right_share": s["emergence"]["crowd_and_arbiter"]["named_right_share"],
                 "emergence_refused_share": s["emergence"]["crowd_and_arbiter"]["refused_share_of_scored"],
                 "unresolved_s_median": s["unresolved_s"]["all"]["median"],
                 "unresolved_s_p90": s["unresolved_s"]["all"]["p90"]}
            metrics.record("crowd_region", part="replay", session=args.session, values=v,
                           deps={**deps, "ally_icon": s["ally_icon_version"]})
            print(" ".join(f"[metric:crowd_region/replay@{args.session}#{k}={x}]"
                           for k, x in v.items()))
        return 0
    if args.cmd == "riot":
        for sid in args.sessions:
            s = score_riot(sid)
            (ANALYSIS / f"riot_{sid}.json").write_text(json.dumps(s, indent=1, default=_default),
                                                       encoding="utf-8")
            print(json.dumps(s, indent=1, default=_default))
            if args.record:
                from reticle import metrics
                ki = s["kill_instants"]
                v = {"ring_missed": ki.get("ring_missed", 0),
                     "stack_match_share": ki["stack_match_share_of_ring_missed"],
                     "crowd_contain_share": ki["crowd_contain_share_of_ring_missed"],
                     "skipped_share": s["cpu"]["skipped_share"],
                     "saved_share_of_reader": s["cpu"]["saved_share_of_reader"],
                     "stack_facing_within_30": (s["stack_facing"] or {}).get("within_30")}
                metrics.record("crowd_region", part="riot", session=sid, values=v,
                               deps={**deps, "ally_icon": s["ally_icon_version"],
                                     "stack_fit": s["stack_fit_version"]})
                print(" ".join(f"[metric:crowd_region/riot@{sid}#{k}={x}]" for k, x in v.items()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
