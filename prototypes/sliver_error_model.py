r"""Does a measured pose and geometry error explain the three cone slivers, and only them?

    .\.venv\Scripts\python.exe prototypes\sliver_error_model.py [--samples 200] [--shifts 60] [--experiment e1|e2|e3]

The first experiment of [the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md);
the design, the predictions and the result are there. It reads stored data
only -- the minimap ROI crop cache, baked `(map, profile)` geometry, the stored
`ability_light` raw decisions and the player's grouping labels -- decodes no
video, and writes nothing to the store but one `metrics` row. E2 moves the ray
origin; E3 reads the teardrop with `teardrop_tip.py` (see the plan).

Three stages, each calling the owner rather than restating it:

1. **Pose.** `team_vision.TeamVision`, the owner of the chain
   (`minimap.self_icons` -> `cone.resolve_lobe` against `lighting.lit_mask` ->
   `track.Tracker`), driven over the crop cache: the principal track's position
   and its 200 ms window of lobe-resolved bearings, which the stored
   `team_vision` rows do not keep. The window is kept whole: where the track would
   REFUSE a bearing (resultant under 0.5), the window's spread is the
   uncertainty, not a gate.
2. **Calibration, on held-out frames** (every cached frame of `e78e75b2d191`
   more than 1.5 s from a sliver). Position jitter is the detection centre's
   residual about a +/-2 frame median. Facing error is the per-frame bearing
   against the bisector of the drawn light around the icon -- a witness the
   ring fit cannot see, although `resolve_lobe` saw it when choosing the lobe,
   so the flip rate measured here is a floor. BOXEDGE transparency is the lit
   rate of floor a ray reaches only through a box edge, scaled between the lit
   rate outside every cone and the lit rate inside the cone.
3. **Scoring.** For a component, O is the stored raw-lit floor in its box.
   Each of N samples draws a bearing from the window plus measured jitter, a
   lobe flip at the measured rate, a position offset at the measured jitter,
   and (model M2) opens each BOXEDGE segment at the measured transparency; it
   raycasts with `cone.raycast` and asks whether the cone covers half of O.
   E is the share of samples that do. The component is EXPLAINED at E >= 0.05:
   a measurement error at least that probable accounts for it. With fewer than
   3 raw-lit pixels there is no light to explain, and with no self pose there
   is no witness; both stay distinguishable refusals to explain.

Specificity is the time-shift null: the same sliver box and O, scored with the
poses of frames at least 3 s away. An explanation that any pose supplies is no
explanation. The sliver search `adjudication.ability.light_refusals` carried
until `ability-light-refusal-0.3.0` (grid search +/-2 px, +/-10 deg, two lobes,
over `labels != VOID` dilated by 1 px, on the series column `self_d`) is scored
against the same null; its geometric core is restated below ONLY as the
instrument that measured it, since it is no longer in the owner.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import cone, geometry, lighting, metrics, team_vision  # noqa: E402
from reticle.adjudication.ability import (LIGHT_REFUSAL_VERSION, _components,  # noqa: E402
                                         _labels, light_refusals)
from reticle.minimap import BOXEDGE, VOID  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

STORE = Path(DEFAULT_STORE)
VERSION = "sliver-error-model-0.3.0"
ABILITY = {"same_entity", "other_ability"}
DEMO = "e78e75b2d191"
SLIVERS = (36900.0, 40650.0, 43350.0)
HOLDOUT_MS = 1500.0          # calibration never sees a sliver's neighbourhood
SHIFT_MIN_MS = 3000.0        # a null pose is at least this far from the sliver
WINDOW_MS = 200.0            # track.Tracker's bearing window
POSE_TOL_MS = 40.0           # a cached frame within this of a component time
COVER = 0.5                  # a sample explains O when its cone covers half of it
PLAUSIBLE = 0.05             # explained when E >= this
MIN_O = 3                    # fewer raw-lit pixels: no light to explain
LIGHT_R = (12.0, 90.0)       # annulus for the light bisector
LIGHT_MIN_PX, LIGHT_MIN_R = 60, 0.7
PRE_WINDOW_MS = 2500.0       # tracker warm-up for a component outside the demo


def _below_normal() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def _signed_deg(a):
    return (np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0


def answers() -> dict[tuple, dict]:
    """Last row per key wins, as the labeller writes them."""
    out = {}
    for path in sorted((STORE / "labels" / "ability_grouping").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[(row["review_id"], row.get("component_id") or "")] = row
    return out


def group(answer: str) -> str:
    return ("ability" if answer in ABILITY else
            "viewcone" if answer == "viewcone_fragment" else "other")


class Session:
    """The baked references and the crop cache for one session."""

    def __init__(self, sid: str):
        self.sid = sid
        man = geometry.manifest(sid, STORE)
        self.capture = man["source"]["path"]
        prof = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        # The team-vision owner builds the chain's inputs; nothing here restates them.
        self.inputs, why = team_vision.load_inputs(STORE, sid, prof, w, h)
        if self.inputs is None or self.inputs.light is None:
            raise SystemExit(f"{sid}: no team-vision inputs ({why or 'no lighting reference'})")
        self.box = self.inputs.box
        self.floor, self.passable, self.ref = self.inputs.floor, self.inputs.passable, self.inputs.light
        with np.load(geometry.path_of(sid, STORE)) as z:
            self.labels = z["labels"].copy()
        self.boxedge = self.labels == BOXEDGE
        n, self.segments = cv2.connectedComponents(self.boxedge.astype(np.uint8), connectivity=8)
        self.n_segments = n - 1
        # Distance from each pixel to the nearest impassable one, for E2's side rule.
        self.clearance = cv2.distanceTransform(self.passable.astype(np.uint8), cv2.DIST_L2, 3)
        self.cache, why = RoiCache.load(STORE, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))
        frames = [json.loads(l) for l in (STORE / "events" / "ability_light" / f"{sid}.jsonl")
                  .read_text(encoding="utf-8").splitlines() if l.strip()]
        self.light = {float(r["t_ms"]): r for r in frames if r.get("kind") == "frame"}
        self.poses: dict[float, dict] = {}

    def crops(self, times):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples([float(t) for t in times], rois=["minimap"]):
            yield smp.t_ms, smp.frame[y0:y1, x0:x1]

    def run_chain(self, times, calib=None, holdout=()):
        """`team_vision.TeamVision` over `times`, in order, from a fresh chain.

        The stored product keeps each icon's gated bearing only, so the chain
        is driven here to read what the sampler needs and the product lacks:
        the principal track's 200 ms window and resultant.
        """
        chain = team_vision.TeamVision.from_inputs(self.inputs)
        for t, crop in self.crops(times):
            frame = chain.step(crop, t)
            raw = lighting.raw_lit(crop, self.ref)
            lit = lighting.clean_lit(raw, self.ref)
            dets = frame.selves
            pr = frame.principal
            rec = {"t": t, "pose": False, "widget": frame.widget}
            if pr is not None and frame.widget == "drawn":
                window = [d for tm, d in pr.history if t - tm <= WINDOW_MS]
                deg, res = pr.resolved_facing(WINDOW_MS)
                near = min(dets, key=lambda d: math.hypot(d["cx"] - pr.x, d["cy"] - pr.y),
                           default=None)
                rec.update(pose=True, x=float(pr.x), y=float(pr.y), window=window,
                           deg=deg, resultant=res,
                           det=(None if near is None else
                                (float(near["cx"]), float(near["cy"]), near.get("facing"),
                                 float(near.get("r") or 0.0))))
            self.poses[t] = rec
            if calib is not None and rec["pose"] and all(abs(t - h) > HOLDOUT_MS for h in holdout):
                calib.frame(self, rec, raw, lit)

    def pose_at(self, t: float) -> dict | None:
        if not self.poses:
            return None
        keys = np.fromiter(self.poses.keys(), float)
        k = float(keys[np.argmin(np.abs(keys - t))])
        return self.poses[k] if abs(k - t) <= POSE_TOL_MS else None

    def observed(self, t: float, box) -> tuple[np.ndarray | None, str | None]:
        """O: the stored raw-lit known floor in the box at the component's time."""
        fr = self.light.get(float(t))
        if fr is None or fr.get("raw_lit") is None:
            return None, "no_light_frame"
        raw = lighting.unpack_mask(fr["raw_lit"])
        bx, by, bw, bh = box
        m = np.zeros(raw.shape, bool)
        m[max(0, by):by + bh, max(0, bx):bx + bw] = True
        return raw & m & self.ref.known, None


class Calibration:
    """Error statistics from held-out frames; no sliver frame enters."""

    def __init__(self):
        self.cx, self.cy, self.t = [], [], []
        self.frame_err, self.track_err = [], []
        self.leak = defaultdict(float)
        self.frames = []          # (x, y, deg, packed raw_lit) for the per-segment pass
        self.frame_t = []         # each entry of `frames`, its time (E3 joins the read tip)

    def frame(self, s: Session, rec: dict, raw: np.ndarray, lit: np.ndarray) -> None:
        det = rec["det"]
        if det is None:
            return
        cx, cy, f, r = det
        self.cx.append(cx), self.cy.append(cy), self.t.append(rec["t"])
        h, w = lit.shape
        yy, xx = np.mgrid[0:h, 0:w]
        d = np.hypot(xx - cx, yy - cy)
        ring = lit & s.ref.known & (d >= max(LIGHT_R[0], 1.5 * r)) & (d <= LIGHT_R[1])
        if ring.sum() >= LIGHT_MIN_PX:
            ang = np.arctan2(yy[ring] - cy, xx[ring] - cx)
            c, sn = np.cos(ang).mean(), np.sin(ang).mean()
            if math.hypot(c, sn) >= LIGHT_MIN_R:
                phi = math.degrees(math.atan2(sn, c))
                if f is not None:
                    self.frame_err.append(float(_signed_deg(f - phi)))
                if rec["deg"] is not None and rec["resultant"] >= 0.5:
                    self.track_err.append(float(_signed_deg(rec["deg"] - phi)))
        # BOXEDGE transparency: lit rate of floor reached only through a box edge.
        if rec["deg"] is None or rec["resultant"] < 0.5:
            return
        x, y, deg = rec["x"], rec["y"], rec["deg"]
        self.frames.append((x, y, deg, np.packbits(raw), r))
        self.frame_t.append(rec["t"])
        shut = cone.raycast(s.passable, x, y, deg, visible=s.floor)
        opened = cone.raycast(s.floor, x, y, deg, visible=s.floor)
        k = s.ref.known
        extra = opened & ~shut & k & ~s.boxedge
        inside = shut & k
        base = k & ~opened & (d <= 150)
        for name, m in (("extra", extra), ("inside", inside), ("base", base)):
            self.leak[name + "_n"] += float(m.sum())
            self.leak[name + "_lit"] += float((m & raw).sum())

    def result(self) -> dict:
        cx, cy = np.array(self.cx), np.array(self.cy)
        order = np.argsort(self.t)
        cx, cy, t = cx[order], cy[order], np.array(self.t)[order]
        res = []
        for i in range(2, len(t) - 2):
            if t[i + 2] - t[i - 2] > 5 * 70.0:      # contiguous 15 Hz frames only
                continue
            res.append(cx[i] - np.median(cx[i - 2:i + 3]))
            res.append(cy[i] - np.median(cy[i - 2:i + 3]))
        res = np.array(res)
        # Centres are whole pixels, so a median absolute residual collapses to 0;
        # the RMS of residuals within 5 px (a larger one is a track switch) does not.
        core = res[np.abs(res) <= 5.0]
        sigma_pos = float(np.sqrt(np.mean(core ** 2))) if len(core) else float("nan")
        fe = np.array(self.frame_err)
        flip = np.abs(fe) > 90.0
        within = fe[~flip]
        sigma_deg = float(1.4826 * np.median(np.abs(within - np.median(within)))) if len(within) else float("nan")
        te = np.array(self.track_err)
        L = self.leak
        rate = {k: (L[k + "_lit"] / L[k + "_n"] if L[k + "_n"] else float("nan"))
                for k in ("extra", "inside", "base")}
        q = (rate["extra"] - rate["base"]) / (rate["inside"] - rate["base"])
        return {
            "frames_pos": int(len(self.cx)), "sigma_pos_px": sigma_pos,
            "pos_residual_p90_px": float(np.percentile(np.abs(res), 90)) if len(res) else None,
            "frames_facing": int(len(fe)), "flip_rate": float(flip.mean()) if len(fe) else None,
            "facing_bias_deg": float(np.median(within)) if len(within) else None,
            "sigma_deg": sigma_deg,
            "track_frames": int(len(te)),
            "track_flip_rate": float((np.abs(te) > 90).mean()) if len(te) else None,
            "track_abs_err_median_deg": float(np.median(np.abs(te[np.abs(te) <= 90]))) if len(te) else None,
            "leak_rates": rate, "boxedge_q": float(min(1.0, max(0.0, q))),
            "leak_px": {k: L[k + "_n"] for k in ("extra", "inside", "base")},
        }


class Model:
    def __init__(self, cal: dict, geometry_noise: bool, n: int, seed: int = 20260928,
                 q_segment: dict | None = None, origin: str = "centre"):
        self.origin = origin              # E2: "centre", "side" or "teardrop"
        self.sp, self.sd, self.flip = cal["sigma_pos_px"], cal["sigma_deg"], cal["flip_rate"]
        self.q = cal["boxedge_q"] if geometry_noise else 0.0
        self.q_segment = q_segment or {}     # segment id -> its own held-out transparency
        self.n = n
        self.seed = seed

    def explain(self, s: Session, pose: dict | None, O: np.ndarray) -> float | None:
        """E: the share of sampled poses (and geometries) whose cone covers half of O."""
        if pose is None or not pose["pose"] or not pose["window"]:
            return None
        rng = np.random.default_rng(self.seed)
        ys, xs = np.nonzero(O)
        reach = int(np.hypot(xs - pose["x"], ys - pose["y"]).max() + 6)
        need = COVER * len(xs)
        win = np.array(pose["window"], float)
        hits = 0
        for _ in range(self.n):
            deg = rng.choice(win) + rng.normal(0.0, self.sd)
            if rng.random() < self.flip:
                deg += 180.0
            x = pose["x"] + rng.normal(0.0, self.sp)
            y = pose["y"] + rng.normal(0.0, self.sp)
            passable = s.passable
            if self.q > 0 and s.n_segments:
                q = np.full(s.n_segments, self.q)
                for sid_, qs in self.q_segment.items():
                    q[sid_ - 1] = qs
                opened = np.flatnonzero(rng.random(s.n_segments) < q) + 1
                if len(opened):
                    passable = passable | np.isin(s.segments, opened)
            x, y = place_origin(s, self.origin, x, y, deg, pose["det"][3] if pose.get("det") else 0.0,
                                3.0 * self.sp)
            m = cone.raycast(passable, x, y, deg % 360.0, visible=s.floor, max_r=reach + 10)
            hits += int(m[ys, xs].sum() >= need)
        return hits / self.n


def place_origin(s: Session, how: str, x: float, y: float, deg: float, r: float,
                 radius: float) -> tuple[float, float]:
    """E2: where the eye is, given a drawn centre and bearing.

    `centre` keeps the fitted centre. `side` applies only when the centre lies
    within a pixel of an impassable pixel: it moves the origin to the passable
    pixel within `radius` that lies furthest along the bearing -- the open side
    of a one-pixel line. `teardrop` is the player's spec
    [domain:minimap/cone-rays-stop-at-first-edge]: the fitted radius along the
    bearing. Neither lets a ray pass an edge; each only moves where it starts.
    """
    if how == "teardrop":
        a = math.radians(deg)
        return x + r * math.cos(a), y + r * math.sin(a)
    if how != "side":
        return x, y
    h, w = s.passable.shape
    ix, iy = int(round(x)), int(round(y))
    if not (0 <= ix < w and 0 <= iy < h) or s.clearance[iy, ix] > 1.5:
        return x, y
    k = int(math.ceil(radius))
    dy, dx = np.mgrid[-k:k + 1, -k:k + 1]
    keep = np.hypot(dx, dy) <= radius
    px, py = ix + dx[keep], iy + dy[keep]
    ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    px, py = px[ok], py[ok]
    ok = s.passable[py, px]
    if not ok.any():
        return x, y
    px, py = px[ok], py[ok]
    a = math.radians(deg)
    j = int(np.argmax((px - x) * math.cos(a) + (py - y) * math.sin(a)))
    return float(px[j]), float(py[j])


def required_error(s: Session, pose: dict, O: np.ndarray, passable: np.ndarray) -> dict | None:
    """EXPLORATORY, not pre-registered: the smallest error that explains O.

    Formulation A of the design as a diagnostic. For offsets of 0-4 px from the
    pose, the cone aimed at O's centroid either covers half of O or does not;
    occlusion does not depend on the bearing within the wedge. At the smallest
    offset that covers it, the facing error needed is the angle from the nearest
    window bearing to the set of bearings whose wedge still holds O.
    """
    ys, xs = np.nonzero(O)
    cx, cy = float(xs.mean()), float(ys.mean())
    reach = int(np.hypot(xs - pose["x"], ys - pose["y"]).max() + 10)
    for r in np.arange(0.0, 4.01, 0.5):
        best = None
        for a in (range(0, 360, 15) if r > 0 else (0,)):
            x = pose["x"] + r * math.cos(math.radians(a))
            y = pose["y"] + r * math.sin(math.radians(a))
            phi = math.degrees(math.atan2(cy - y, cx - x))
            m = cone.raycast(passable, x, y, phi % 360.0, visible=s.floor, max_r=reach)
            if m[ys, xs].sum() < COVER * len(xs):
                continue
            span = float(np.abs(_signed_deg(np.degrees(np.arctan2(ys - y, xs - x)) - phi)).max())
            slack = max(0.0, cone.CONE_HALF_ANGLE_DEG - span)
            need = min(max(0.0, abs(float(_signed_deg(b - phi))) - slack) for b in pose["window"])
            if best is None or need < best["facing_deg"]:
                best = {"offset_px": float(r), "facing_deg": round(need, 1),
                        "bearing_to_O": round(phi % 360.0, 1)}
        if best is not None:
            return best
    return None


def blockers(s: Session, pose: dict, O: np.ndarray) -> list[int]:
    """E1b: the BOXEDGE segments whose opening alone lets the cone reach half of O.

    The bearing is aimed at O's centroid from the track position, so this asks
    about the map, not the facing.
    """
    ys, xs = np.nonzero(O)
    phi = math.degrees(math.atan2(ys.mean() - pose["y"], xs.mean() - pose["x"])) % 360.0
    reach = int(np.hypot(xs - pose["x"], ys - pose["y"]).max() + 6)
    sy, sx = np.nonzero(s.boxedge)
    near = np.hypot(sx - pose["x"], sy - pose["y"]) <= reach
    found = []
    for seg in sorted(set(s.segments[sy[near], sx[near]].tolist())):
        m = cone.raycast(s.passable | (s.segments == seg), pose["x"], pose["y"], phi,
                         visible=s.floor, max_r=reach)
        if m[ys, xs].sum() >= COVER * len(xs):
            found.append(int(seg))
    return found


def segment_transparency(s: Session, cal: "Calibration", C: dict, segs) -> dict:
    """E1b: each segment's own transparency on the held-out frames, by E1's ratio."""
    rate = C["leak_rates"]
    acc = {seg: [0.0, 0.0] for seg in segs}
    k = s.ref.known
    shape = s.passable.shape
    for x, y, deg, packed, _r in cal.frames:
        raw = np.unpackbits(packed, count=shape[0] * shape[1]).reshape(shape).astype(bool)
        shut = cone.raycast(s.passable, x, y, deg, visible=s.floor)
        for seg in segs:
            opened = cone.raycast(s.passable | (s.segments == seg), x, y, deg, visible=s.floor)
            extra = opened & ~shut & k & ~s.boxedge
            acc[seg][0] += float(extra.sum())
            acc[seg][1] += float((extra & raw).sum())
    out = {}
    for seg, (n, lit) in acc.items():
        q = None
        if n >= 200:
            q = ((lit / n) - rate["base"]) / (rate["inside"] - rate["base"])
            q = float(min(1.0, max(0.0, q)))
        out[seg] = {"reach_px": int(n), "q": q}
    return out


def wired_rule_explains(s: Session, series, t: float, box) -> bool:
    """The geometric core of `light_refusals`'s sliver path, at the series pose of `t`."""
    idx = int(np.argmin(np.abs(series["t_ms"] - t)))
    sx, sy, sd = (float(series[k][0, idx]) for k in ("self_x", "self_y", "self_d"))
    if np.isnan(sd):
        return False
    rel = cv2.dilate((s.labels != VOID).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    bx, by, bw, bh = box
    win = (slice(max(0, by), by + bh), slice(max(0, bx), bx + bw))
    for lobe in (sd, (sd + 180.0) % 360.0):
        for dx in (-2.0, 0.0, 2.0):
            for dy in (-2.0, 0.0, 2.0):
                for dd in (-10.0, 0.0, 10.0):
                    if cone.raycast(rel, sx + dx, sy + dy, (lobe + dd) % 360.0)[win].mean() >= 0.20:
                        return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--shifts", type=int, default=60)
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "sliver-error-model")
    ap.add_argument("--experiment", choices=("e1", "e2", "e3"), default="e1",
                    help="e1: noise and box-edge transparency (with E1b); e2: the origin's side; "
                         "e3: the read teardrop tip")
    args = ap.parse_args(argv)
    _below_normal()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.experiment == "e3":
        return main_e3(args)
    if args.experiment == "e2":
        return main_e2(args)

    comps = {c["component_id"]: c for c in _components(STORE, _labels(STORE))}
    rows = [r for r in answers().values()
            if r.get("component_id") in comps and r.get("t_ms") is not None and not r.get("unsure")]
    by_sid = defaultdict(list)
    for r in rows:
        by_sid[r["session_id"]].append(r)

    # Baseline: the wired owner's decisions on the same components.
    owner = light_refusals(STORE, [comps[r["component_id"]] for r in rows])
    baseline = defaultdict(lambda: [0, 0])
    for r in rows:
        g = group(r["answer"])
        baseline[g][0] += owner.get(r["component_id"], {}).get("status") == "refused"
        baseline[g][1] += 1
    print("baseline light_refusals (refused/n):", {g: tuple(v) for g, v in baseline.items()})

    # Stage 1 and 2: the demo's pose chain over every cached frame, calibrating on held-out ones.
    sessions = {sid: Session(sid) for sid in by_sid}
    demo = sessions[DEMO]
    cal = Calibration()
    demo.run_chain(demo.cache_t, calib=cal, holdout=SLIVERS)
    C = cal.result()
    print("calibration:", json.dumps(C, indent=1))
    for sid, s in sessions.items():
        if sid == DEMO:
            continue
        for t in sorted({float(r["t_ms"]) for r in by_sid[sid]}):
            ts = s.cache_t[(s.cache_t >= t - PRE_WINDOW_MS) & (s.cache_t <= t + POSE_TOL_MS)]
            s.run_chain(ts)

    models = {"M0_point": None, "M1_pose": Model(C, False, args.samples),
              "M2_pose_geometry": Model(C, True, args.samples)}

    def point(s, pose, O):
        if pose is None or not pose["pose"] or pose["deg"] is None:
            return None
        ys, xs = np.nonzero(O)
        m = cone.raycast(s.passable, pose["x"], pose["y"], pose["deg"] % 360.0, visible=s.floor)
        return float(m[ys, xs].sum() >= COVER * len(xs))

    # Stage 3: every labelled component.
    results = []
    for r in rows:
        s = sessions[r["session_id"]]
        c = comps[r["component_id"]]
        t = float(r["t_ms"])
        box = c.get("box") or [int(r["x"]) - 6, int(r["y"]) - 6, 12, 12]
        O, why = s.observed(t, box)
        pose = s.pose_at(t)
        row = {"session": s.sid, "t_ms": t, "x": r["x"], "y": r["y"], "box": box,
               "answer": r["answer"], "group": group(r["answer"]),
               "sliver": s.sid == DEMO and t in SLIVERS,
               "owner": owner.get(r["component_id"], {}).get("status"),
               "o_px": None if O is None else int(O.sum()),
               "pose": None if pose is None else {k: pose.get(k) for k in ("x", "y", "deg", "resultant", "window")}}
        if O is None:
            row["status"] = why
        elif O.sum() < MIN_O:
            row["status"] = "no_light"
        elif pose is None or not pose["pose"]:
            row["status"] = "no_pose"
        else:
            row["status"] = "scored"
            row["E"] = {"M0_point": point(s, pose, O)}
            for name, m in models.items():
                if m is not None:
                    row["E"][name] = m.explain(s, pose, O)
        results.append(row)

    # Specificity: the time-shift null on the three slivers.
    series = np.load(STORE / "series" / f"{DEMO}.npz")
    null = {}
    posed = [t for t, p in sorted(demo.poses.items()) if p["pose"] and p["window"]]
    for row in (x for x in results if x["sliver"]):
        t = row["t_ms"]
        far = [u for u in posed if abs(u - t) >= SHIFT_MIN_MS]
        pick = [far[i] for i in np.linspace(0, len(far) - 1, min(args.shifts, len(far))).astype(int)]
        O, _ = demo.observed(t, row["box"])
        out = {"n": len(pick)}
        for name in ("M1_pose", "M2_pose_geometry"):
            vals = [models[name].explain(demo, demo.poses[u], O) for u in pick]
            vals = np.array([v for v in vals if v is not None])
            true = (row.get("E") or {}).get(name)
            out[name] = {"explained_rate": float((vals >= PLAUSIBLE).mean()),
                         "true_E": true,
                         "true_percentile": (float((vals < true).mean()) if true is not None else None)}
        wired = [wired_rule_explains(demo, series, u, row["box"]) for u in pick]
        out["wired_rule"] = {"explained_rate": float(np.mean(wired)),
                             "true": wired_rule_explains(demo, series, t, row["box"])}
        pose = demo.pose_at(t)
        out["required"] = {
            "pose_window": pose["window"],
            "G0_as_built": required_error(demo, pose, O, demo.passable),
            "G1_boxedges_open": required_error(demo, pose, O, demo.floor),
            "G2_walls_open": required_error(demo, pose, O, demo.labels != VOID)}
        null[t] = out

    # Report.
    def tally(name, g, sliver=None):
        xs = [x for x in results if x["group"] == g and (sliver is None or x["sliver"] == sliver)]
        sc = [x for x in xs if x["status"] == "scored"]
        statuses = defaultdict(int)
        for x in xs:
            statuses[x["status"]] += 1
        return {"n": len(xs), "scored": len(sc),
                "explained": sum((x["E"][name] or 0) >= PLAUSIBLE for x in sc),
                "statuses": dict(sorted(statuses.items()))}

    summary = {}
    for name in ("M0_point", "M1_pose", "M2_pose_geometry"):
        summary[name] = {"slivers": tally(name, "viewcone", True),
                         "lit_viewcones": tally(name, "viewcone", False),
                         "abilities": tally(name, "ability"),
                         "other": tally(name, "other")}
    print(json.dumps(summary, indent=1))
    for row in results:
        if row["sliver"] or row["group"] == "viewcone":
            p = row["pose"] or {}
            print(f"  {'SLIVER' if row['sliver'] else 'lit   '} {row['t_ms']/1000:6.2f}s box={row['box']} "
                  f"O={row['o_px']} owner={row['owner']} status={row['status']} "
                  f"pose=({p.get('x') or float('nan'):.1f},{p.get('y') or float('nan'):.1f}) "
                  f"deg={p.get('deg')} R={p.get('resultant')} E={row.get('E')}")
    print("null:", json.dumps(null, indent=1))
    (args.out / "results.json").write_text(json.dumps(
        {"version": VERSION, "calibration": C, "summary": summary, "null": {str(k): v for k, v in null.items()},
         "baseline": {g: list(v) for g, v in baseline.items()}, "rows": results}, indent=1, default=str),
        encoding="utf-8")
    print("wrote", args.out / "results.json")

    sl = summary["M2_pose_geometry"]["slivers"]
    metrics.record(
        "sliver_error_model", part="grouping-labels", session="all-labelled",
        values={
            "sigma_pos_px": round(C["sigma_pos_px"], 2), "sigma_deg": round(C["sigma_deg"], 1),
            "flip_rate": round(C["flip_rate"], 3), "boxedge_q": round(C["boxedge_q"], 3),
            "facing_frames": C["frames_facing"],
            "slivers_explained_m0": summary["M0_point"]["slivers"]["explained"],
            "slivers_explained_m1": summary["M1_pose"]["slivers"]["explained"],
            "slivers_explained_m2": sl["explained"],
            "lit_viewcones_explained_m2": summary["M2_pose_geometry"]["lit_viewcones"]["explained"],
            "lit_viewcones_scored": summary["M2_pose_geometry"]["lit_viewcones"]["scored"],
            "abilities_explained_m2": summary["M2_pose_geometry"]["abilities"]["explained"],
            "abilities_n": summary["M2_pose_geometry"]["abilities"]["n"],
            "null_m2_max_rate": round(max(v["M2_pose_geometry"]["explained_rate"] for v in null.values()), 3),
            "null_wired_min_rate": round(min(v["wired_rule"]["explained_rate"] for v in null.values()), 3),
            "null_wired_max_rate": round(max(v["wired_rule"]["explained_rate"] for v in null.values()), 3),
            "e_m2_36900": null[SLIVERS[0]]["M2_pose_geometry"]["true_E"],
            "e_m2_40650": null[SLIVERS[1]]["M2_pose_geometry"]["true_E"],
            "e_m2_43350": null[SLIVERS[2]]["M2_pose_geometry"]["true_E"],
            "null_m2_40650": round(null[SLIVERS[1]]["M2_pose_geometry"]["explained_rate"], 3),
            "null_m2_43350": round(null[SLIVERS[2]]["M2_pose_geometry"]["explained_rate"], 3),
            "abilities_scored": summary["M2_pose_geometry"]["abilities"]["scored"],
            "lit_viewcones_n": summary["M2_pose_geometry"]["lit_viewcones"]["n"],
            "track_abs_err_median_deg": round(C["track_abs_err_median_deg"], 1),
            "owner_viewcones_refused": baseline["viewcone"][0],
            "owner_abilities_refused": baseline["ability"][0]},
        deps={"prototype": VERSION, "lighting": lighting.LIGHTING_VERSION,
              "cone_half_angle": cone.CONE_HALF_ANGLE_DEG,
              "light_refusal": LIGHT_REFUSAL_VERSION,
              "labels": "labels/ability_grouping last row per key, unsure excluded",
              "samples": args.samples, "shifts": args.shifts, "plausible": PLAUSIBLE, "cover": COVER},
        context={"sessions": sorted(by_sid), "slivers": list(SLIVERS), "calibration_session": DEMO})

    # Formulation A's diagnostic, exploratory: the smallest offset that explains each sliver.
    def offset(t, g):
        got = null[t]["required"][g]
        return -1.0 if got is None else got["offset_px"]       # -1: none up to 4 px
    metrics.record(
        "sliver_error_model", part="required-error", session=DEMO,
        values={f"{g.split('_')[0].lower()}_offset_px_{int(t)}": offset(t, g)
                for t in SLIVERS for g in ("G0_as_built", "G1_boxedges_open", "G2_walls_open")},
        deps={"prototype": VERSION, "cone_half_angle": cone.CONE_HALF_ANGLE_DEG, "cover": COVER,
              "offsets": "0-4 px in 0.5 px steps, 24 directions"},
        context={"meaning": "-1 means no offset up to 4 px explains the sliver",
                 "geometries": "g0 as built, g1 BOXEDGE passable, g2 every non-void label passable"})

    # E1b, pre-registered after E1's outcome: each blocker segment's own transparency.
    e1b, blockers_all = {}, set()
    for row in (x for x in results if x["sliver"]):
        t = row["t_ms"]
        pose = demo.pose_at(t)
        O, _ = demo.observed(t, row["box"])
        i = int(np.argmin(np.abs(series["t_ms"] - t)))
        e1b[t] = {"blockers": blockers(demo, pose, O),
                  "series_offset_px": round(math.hypot(float(series["self_x"][0, i]) - pose["x"],
                                                       float(series["self_y"][0, i]) - pose["y"]), 1)}
        blockers_all |= set(e1b[t]["blockers"])
    qs = segment_transparency(demo, cal, C, sorted(blockers_all))
    measured = {seg: v["q"] for seg, v in qs.items() if v["q"] is not None}
    m3 = Model(C, True, args.samples, q_segment=measured)
    changed = defaultdict(int)
    for row in results:
        if row["status"] != "scored":
            continue
        s = sessions[row["session"]]
        if s is demo:
            O, _ = s.observed(row["t_ms"], row["box"])
            row["E"]["M3_segment"] = m3.explain(s, s.pose_at(row["t_ms"]), O)
        else:                       # segments are the demo map's; elsewhere M3 is M2
            row["E"]["M3_segment"] = row["E"]["M2_pose_geometry"]
        if not row["sliver"] and ((row["E"]["M3_segment"] >= PLAUSIBLE)
                                  != (row["E"]["M2_pose_geometry"] >= PLAUSIBLE)):
            changed[row["group"]] += 1
    for row in (x for x in results if x["sliver"]):
        t = row["t_ms"]
        far = [u for u in posed if abs(u - t) >= SHIFT_MIN_MS]
        pick = [far[i] for i in np.linspace(0, len(far) - 1, min(args.shifts, len(far))).astype(int)]
        O, _ = demo.observed(t, row["box"])
        vals = np.array([v for v in (m3.explain(demo, demo.poses[u], O) for u in pick) if v is not None])
        true = row["E"]["M3_segment"]
        e1b[t].update(q={seg: qs[seg] for seg in e1b[t]["blockers"]}, E_m3=true,
                      null_rate=float((vals >= PLAUSIBLE).mean()),
                      true_percentile=float((vals < true).mean()))
    m3_sum = {"slivers": tally("M3_segment", "viewcone", True),
              "lit_viewcones": tally("M3_segment", "viewcone", False),
              "abilities": tally("M3_segment", "ability"), "changed_vs_m2": dict(changed)}
    print("E1b:", json.dumps({str(k): v for k, v in e1b.items()}, indent=1, default=str))
    print("E1b summary:", json.dumps(m3_sum, indent=1))
    (args.out / "results_e1b.json").write_text(json.dumps(
        {"version": VERSION, "segments": {str(k): v for k, v in qs.items()},
         "slivers": {str(k): v for k, v in e1b.items()}, "summary": m3_sum}, indent=1, default=str),
        encoding="utf-8")
    ordered = [e1b[t] for t in SLIVERS]
    qb = [v["q"] for v in qs.values() if v["q"] is not None]
    metrics.record(
        "sliver_error_model", part="segment-transparency", session=DEMO,
        values={"blockers_found": sum(1 for v in ordered if v["blockers"]),
                "blockers_measured": len(qb),
                "blocker_q_min": round(min(qb), 2) if qb else None,
                "blocker_q_max": round(max(qb), 2) if qb else None,
                "global_q": round(C["boxedge_q"], 2),
                "e_m3_36900": round(ordered[0]["E_m3"], 3), "e_m3_40650": round(ordered[1]["E_m3"], 3),
                "e_m3_43350": round(ordered[2]["E_m3"], 3),
                "slivers_explained_m3": m3_sum["slivers"]["explained"],
                "null_rate_max_m3": round(max(v["null_rate"] for v in ordered), 3),
                "true_percentile_min_m3": round(min(v["true_percentile"] for v in ordered), 3),
                "changed_vs_m2": sum(changed.values()),
                "series_offset_px_min": min(v["series_offset_px"] for v in ordered),
                "series_offset_px_max": max(v["series_offset_px"] for v in ordered)},
        deps={"prototype": VERSION, "lighting": lighting.LIGHTING_VERSION,
              "cone_half_angle": cone.CONE_HALF_ANGLE_DEG, "samples": args.samples,
              "shifts": args.shifts, "reach_px_min": 200},
        context={"blockers": {str(t): e1b[t]["blockers"] for t in SLIVERS}, "holdout_ms": HOLDOUT_MS})
    return 0


def agreement(s: Session, cal: "Calibration", radius: float) -> dict:
    """E2's held-out witness: how the drawn light agrees with the cone per origin.

    Precision is the raw-lit share of the cone's known floor, pooled; recall is
    the share of raw-lit known floor within 90 px of the icon the cone covers,
    averaged over frames with at least 50 such pixels, split by whether the
    fitted centre lies within a pixel of an impassable pixel.
    """
    shape = s.passable.shape
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    k = s.ref.known
    pooled = {o: [0.0, 0.0] for o in ("centre", "side", "teardrop")}
    recall = {(o, g): [] for o in pooled for g in ("near", "clear", "far")}
    for x, y, deg, packed, r in cal.frames:
        raw = np.unpackbits(packed, count=shape[0] * shape[1]).reshape(shape).astype(bool)
        dist = np.hypot(xx - x, yy - y)
        lit = raw & k & (dist <= 90.0)
        # EXPLORATORY, added after R4 failed: the icon's own disc and the floor
        # beside it are lit and sit behind a teardrop apex, so recall is also
        # read only on lit floor more than three icon radii out.
        far_lit = lit & (dist > 3.0 * max(r, 1.0))
        ix, iy = int(round(x)), int(round(y))
        near = bool(s.clearance[min(max(iy, 0), shape[0] - 1), min(max(ix, 0), shape[1] - 1)] <= 1.5)
        for o in pooled:
            ox, oy = place_origin(s, o, x, y, deg, r, radius)
            m = cone.raycast(s.passable, ox, oy, deg % 360.0, visible=s.floor)
            pooled[o][0] += float((m & k).sum())
            pooled[o][1] += float((m & k & raw).sum())
            if lit.sum() >= 50:
                recall[(o, "near" if near else "clear")].append(float((m & lit).sum() / lit.sum()))
            if far_lit.sum() >= 50:
                recall[(o, "far")].append(float((m & far_lit).sum() / far_lit.sum()))
    out = {"frames": len(cal.frames)}
    for o, (n, hit) in pooled.items():
        out[f"precision_{o}"] = hit / n if n else None
        for g in ("near", "clear", "far"):
            v = recall[(o, g)]
            out[f"recall_{o}_{g}"] = float(np.mean(v)) if v else None
            out[f"frames_{g}"] = len(v)
    return out


def main_e2(args) -> int:
    """E2: does placing the eye on the open side of a one-pixel line explain the slivers?"""
    comps = {c["component_id"]: c for c in _components(STORE, _labels(STORE))}
    rows = [r for r in answers().values()
            if r.get("component_id") in comps and r.get("t_ms") is not None
            and not r.get("unsure") and r["session_id"] == DEMO and group(r["answer"]) == "viewcone"]
    demo = Session(DEMO)
    cal = Calibration()
    demo.run_chain(demo.cache_t, calib=cal, holdout=SLIVERS)
    C = cal.result()
    radius = 3.0 * C["sigma_pos_px"]
    print(f"calibration: sigma_pos {C['sigma_pos_px']:.2f} px, facing {C['sigma_deg']:.1f} deg, "
          f"flip {C['flip_rate']:.3f}; side radius {radius:.2f} px")
    arms = {o: Model(C, False, args.samples, origin=o) for o in ("centre", "side", "teardrop")}
    posed = [t for t, p in sorted(demo.poses.items()) if p["pose"] and p["window"]]
    slivers, lit_ok = {}, defaultdict(int)
    for r in rows:
        t = float(r["t_ms"])
        box = comps[r["component_id"]].get("box")
        O, why = demo.observed(t, box)
        pose = demo.pose_at(t)
        if O is None or O.sum() < MIN_O or pose is None or not pose["pose"]:
            continue
        E = {o: m.explain(demo, pose, O) for o, m in arms.items()}
        if t not in SLIVERS:
            for o, e in E.items():
                lit_ok[o] += int(e is not None and e >= PLAUSIBLE)
            lit_ok["scored"] += 1
            continue
        far = [u for u in posed if abs(u - t) >= SHIFT_MIN_MS]
        pick = [far[i] for i in np.linspace(0, len(far) - 1, min(args.shifts, len(far))).astype(int)]
        out = {"E": E, "near_line": bool(demo.clearance[int(round(pose["y"])), int(round(pose["x"]))] <= 1.5)}
        for o in ("side", "teardrop"):
            vals = np.array([v for v in (arms[o].explain(demo, demo.poses[u], O) for u in pick)
                             if v is not None])
            out[f"null_rate_{o}"] = float((vals >= PLAUSIBLE).mean())
            out[f"true_percentile_{o}"] = float((vals < E[o]).mean())
        slivers[t] = out
        print(f"sliver {t / 1000:.2f}s: {json.dumps(out)}")
    agree = agreement(demo, cal, radius)
    print("lit viewcones explained:", dict(lit_ok))
    print("held-out agreement:", json.dumps(agree, indent=1))
    (args.out / "results_e2.json").write_text(json.dumps(
        {"version": VERSION, "calibration": C, "slivers": {str(k): v for k, v in slivers.items()},
         "lit_viewcones": dict(lit_ok), "agreement": agree}, indent=1), encoding="utf-8")
    vals = {"side_radius_px": round(radius, 2),
            "lit_viewcones_scored": lit_ok["scored"],
            "lit_viewcones_centre": lit_ok["centre"], "lit_viewcones_side": lit_ok["side"],
            "lit_viewcones_teardrop": lit_ok["teardrop"],
            "frames_near": agree["frames_near"], "frames_clear": agree["frames_clear"],
            "frames_far": agree["frames_far"]}
    for t in SLIVERS:
        v = slivers.get(t)
        if v is None:
            continue
        for o in ("centre", "side", "teardrop"):
            vals[f"e_{o}_{int(t)}"] = round(v["E"][o], 3)
        for o in ("side", "teardrop"):
            vals[f"null_{o}_{int(t)}"] = round(v[f"null_rate_{o}"], 3)
            vals[f"pct_{o}_{int(t)}"] = round(v[f"true_percentile_{o}"], 3)
        vals[f"near_line_{int(t)}"] = int(v["near_line"])
    for key in ("precision_centre", "precision_side", "precision_teardrop",
                "recall_centre_near", "recall_side_near", "recall_teardrop_near",
                "recall_centre_clear", "recall_side_clear", "recall_teardrop_clear",
                "recall_centre_far", "recall_side_far", "recall_teardrop_far"):
        vals[key] = None if agree[key] is None else round(agree[key], 3)
    for o in ("side", "teardrop"):
        vals[f"slivers_explained_{o}"] = sum(1 for v in slivers.values() if v["E"][o] >= PLAUSIBLE)
    metrics.record(
        "sliver_error_model", part="origin-side", session=DEMO, values=vals,
        deps={"prototype": VERSION, "lighting": lighting.LIGHTING_VERSION,
              "cone_half_angle": cone.CONE_HALF_ANGLE_DEG, "samples": args.samples,
              "shifts": args.shifts, "plausible": PLAUSIBLE, "cover": COVER,
              "fact": "minimap/cone-rays-stop-at-first-edge"},
        context={"holdout_ms": HOLDOUT_MS, "arms": ["centre", "side", "teardrop"]})
    return 0


def _light_bisector(s: Session, lit: np.ndarray, cx: float, cy: float, r_inner: float):
    """E1's light witness: the circular mean bearing of lit floor in an annulus, or None."""
    h, w = lit.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - cx, yy - cy)
    ring = lit & s.ref.known & (d >= r_inner) & (d <= LIGHT_R[1])
    if ring.sum() < LIGHT_MIN_PX:
        return None
    ang = np.arctan2(yy[ring] - cy, xx[ring] - cx)
    c, sn = np.cos(ang).mean(), np.sin(ang).mean()
    return math.degrees(math.atan2(sn, c)) if math.hypot(c, sn) >= LIGHT_MIN_R else None


def _robust_sd(v) -> float | None:
    v = np.asarray(v, float)
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if len(v) else None


def read_tips(s: Session) -> dict[float, dict]:
    """E3: the teardrop read from every cached frame, with the ring fit it started from."""
    import teardrop_tip as tt
    out = {}
    for t, crop in s.crops(s.cache_t):
        det = tt.self_start(crop, s.floor)
        if det is None:
            out[t] = {"read": False, "reason": "no_self_detection"}
            continue
        f = tt.fit(crop, det["cx"], det["cy"])
        f.update(ring_x=float(det["cx"]), ring_y=float(det["cy"]), ring_r=float(det["r"]),
                 ring_deg=det.get("facing"))
        raw = lighting.raw_lit(crop, s.ref)
        lit = lighting.clean_lit(raw, s.ref)
        f["phi_e1"] = _light_bisector(s, lit, det["cx"], det["cy"], max(LIGHT_R[0], 1.5 * det["r"]))
        if "x" in f:
            f["phi_tip"] = _light_bisector(s, lit, f["x"], f["y"], tt.L + 2.0)
        out[t] = f
    return out


def tip_precision(tips: dict, times) -> dict:
    """E3 T1-T4: readability, jitter on stationary frames, light agreement, ring-fit bias.

    Jitter is a frame's residual about the median of its +/-2 frame window; a frame
    is stationary when every fitted centre in the window lies within 0.75 px of the
    window's median. The minimap often repeats an image across cached frames, so
    consecutive identical fits collapse to one sample first (E3's first run, without
    that, measured a jitter of exactly zero), and a window may then span 600 ms.
    Facing jitter still includes the player's own turning, so it bounds the
    reader's noise from above; `_rms20` is the RMS of residuals within 20 degrees.
    """
    det = [t for t in times if tips[t].get("reason") != "no_self_detection"]
    read = sorted(t for t in det if tips[t]["read"])
    out = {"frames_detected": len(det), "frames_read": len(read),
           "read_rate": len(read) / len(det) if det else None}

    def key(t):
        return round(tips[t]["x"], 3), round(tips[t]["y"], 3), round(tips[t]["deg"], 2)
    distinct = [t for i, t in enumerate(read) if i == 0 or key(t) != key(read[i - 1])]
    out["frames_distinct"] = len(distinct)
    T = np.array(distinct)
    X = np.array([tips[t]["x"] for t in distinct])
    Y = np.array([tips[t]["y"] for t in distinct])
    D = np.array([tips[t]["deg"] for t in distinct])
    TX = np.array([tips[t]["tip_x"] for t in distinct])
    TY = np.array([tips[t]["tip_y"] for t in distinct])
    RD = np.array([np.nan if tips[t]["ring_deg"] is None else tips[t]["ring_deg"] for t in distinct])
    fac, fac_all, tipres, ring_fac = [], [], [], []
    for i in range(2, len(T) - 2):
        if T[i + 2] - T[i - 2] > 600.0:
            continue
        sl = slice(i - 2, i + 3)
        still = max(np.hypot(X[sl] - np.median(X[sl]), Y[sl] - np.median(Y[sl]))) <= 0.75
        r_ = float(-np.median(_signed_deg(D[sl] - D[i])))   # this frame about the window's median
        fac_all.append(r_)
        if still:
            fac.append(r_)
            tipres.append(math.hypot(TX[i] - np.median(TX[sl]), TY[i] - np.median(TY[sl])))
            if not np.isnan(RD[sl]).any():
                ring_fac.append(float(-np.median(_signed_deg(RD[sl] - RD[i]))))
    def rms20(v):
        v = np.asarray(v, float)
        v = v[np.abs(v) <= 20.0]
        return float(np.sqrt(np.mean(v ** 2))) if len(v) else None
    out.update(stationary_frames=len(fac), facing_jitter_deg=_robust_sd(fac),
               facing_jitter_rms20_deg=rms20(fac), facing_jitter_all_rms20_deg=rms20(fac_all),
               facing_jitter_all_deg=_robust_sd(fac_all),
               tip_jitter_rms_px=float(np.sqrt(np.mean(np.square(tipres)))) if tipres else None,
               ring_facing_jitter_deg=_robust_sd(ring_fac), ring_stationary_frames=len(ring_fac))
    # T3: the light witness. `phi_tip` is taken about the teardrop's centre beyond
    # its apex; the ring facing is scored against it too, and against E1's `phi_e1`.
    e_tip = [_signed_deg(tips[t]["deg"] - tips[t]["phi_tip"]) for t in read
             if tips[t].get("phi_tip") is not None]
    e_ring = [_signed_deg(tips[t]["ring_deg"] - tips[t]["phi_tip"]) for t in read
              if tips[t].get("phi_tip") is not None and tips[t]["ring_deg"] is not None]
    e_e1 = [_signed_deg(tips[t]["ring_deg"] - tips[t]["phi_e1"]) for t in det
            if tips[t].get("phi_e1") is not None and tips[t]["ring_deg"] is not None]
    for name, e in (("tip", e_tip), ("ring", e_ring), ("ring_e1", e_e1)):
        e = np.array(e, float)
        within = e[np.abs(e) <= 90.0]
        out[f"light_frames_{name}"] = int(len(e))
        out[f"light_flip_{name}"] = float((np.abs(e) > 90).mean()) if len(e) else None
        out[f"light_spread_{name}_deg"] = _robust_sd(within)
        out[f"light_bias_{name}_deg"] = float(np.median(within)) if len(within) else None
    # T4: where the ring fit sits against the teardrop's centre, over every read frame.
    D = np.array([tips[t]["deg"] for t in read])
    RD = np.array([np.nan if tips[t]["ring_deg"] is None else tips[t]["ring_deg"] for t in read])
    off = np.array([(tips[t]["ring_x"] - tips[t]["x"], tips[t]["ring_y"] - tips[t]["y"]) for t in read])
    dist = np.hypot(off[:, 0], off[:, 1])
    cosv = [(ox * math.cos(math.radians(d)) + oy * math.sin(math.radians(d))) / dd
            for (ox, oy), d, dd in zip(off, D, dist) if dd > 0.5]
    ok = ~np.isnan(RD)
    out.update(ring_offset_median_px=float(np.median(dist)),
               ring_offset_cos_median=float(np.median(cosv)) if cosv else None,
               ring_flip_vs_tip=float(np.mean(np.abs(_signed_deg(RD[ok] - D[ok])) > 90)))
    return out


AXIS_PX = (0, 4, 8, 11, 14, 18)   # E3b: origin offsets along the read facing


def agreement_e3(s: Session, cal: "Calibration", tips: dict) -> dict:
    """E3 T5: E2's held-out witness with the read tip, every arm on the same frames.

    `centre` is E2's baseline (track position and resolved bearing); `tip` casts
    from the read apex along the read facing; `tip_facing` from the teardrop's
    centre along the read facing; `centre_tipdeg` from the track position along
    the read facing. `far` excludes the icon's own glow: lit floor beyond three
    ring radii of the track and beyond 4 px of the read apex.

    EXPLORATORY (E3b, logged after the apex arm failed): `axis_<d>` casts from
    the teardrop's centre moved `d` px along the read facing, to find where the
    drawn light puts the eye between the centre (0) and the apex (`L`).
    """
    shape = s.passable.shape
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    k = s.ref.known
    arms = ("centre", "tip", "tip_facing", "centre_tipdeg") + tuple(f"axis_{d}" for d in AXIS_PX)
    pooled = {o: [0.0, 0.0] for o in arms}
    recall = {(o, g): [] for o in arms for g in ("near", "clear", "far", "all")}
    dropped = 0
    for (x, y, deg, packed, r), t in zip(cal.frames, cal.frame_t):
        tf = tips.get(t)
        if tf is None or not tf.get("read"):
            dropped += 1
            continue
        raw = np.unpackbits(packed, count=shape[0] * shape[1]).reshape(shape).astype(bool)
        dist = np.hypot(xx - x, yy - y)
        lit = raw & k & (dist <= 90.0)
        far_lit = lit & (np.hypot(xx - tf["tip_x"], yy - tf["tip_y"]) > 4.0) & (dist > 3.0 * max(r, 1.0))
        ix, iy = int(round(x)), int(round(y))
        near = bool(s.clearance[min(max(iy, 0), shape[0] - 1), min(max(ix, 0), shape[1] - 1)] <= 1.5)
        pose = {"centre": (x, y, deg), "tip": (tf["tip_x"], tf["tip_y"], tf["deg"]),
                "tip_facing": (tf["x"], tf["y"], tf["deg"]), "centre_tipdeg": (x, y, tf["deg"])}
        a = math.radians(tf["deg"])
        for d in AXIS_PX:
            pose[f"axis_{d}"] = (tf["x"] + d * math.cos(a), tf["y"] + d * math.sin(a), tf["deg"])
        for o, (ox, oy, d) in pose.items():
            m = cone.raycast(s.passable, ox, oy, d % 360.0, visible=s.floor)
            pooled[o][0] += float((m & k).sum())
            pooled[o][1] += float((m & k & raw).sum())
            if lit.sum() >= 50:
                recall[(o, "near" if near else "clear")].append(float((m & lit).sum() / lit.sum()))
                recall[(o, "all")].append(float((m & lit).sum() / lit.sum()))
            if far_lit.sum() >= 50:
                recall[(o, "far")].append(float((m & far_lit).sum() / far_lit.sum()))
    out = {"frames": len(cal.frames) - dropped, "dropped_unread": dropped}
    for o, (n, hit) in pooled.items():
        out[f"precision_{o}"] = hit / n if n else None
        for g in ("near", "clear", "far", "all"):
            v = recall[(o, g)]
            out[f"recall_{o}_{g}"] = float(np.mean(v)) if v else None
            out[f"frames_{g}"] = len(v)
    return out


class TipModel:
    """E3: E for a cone cast along the read facing, with its measured jitter.

    `origin` is `tip` (the read apex) or `centre` (the teardrop's centre, E3b).
    """

    def __init__(self, sigma_px: float, sigma_deg: float, n: int, seed: int = 20260928,
                 origin: str = "tip"):
        self.sp, self.sd, self.n, self.seed = sigma_px, sigma_deg, n, seed
        self.kx, self.ky = ("tip_x", "tip_y") if origin == "tip" else ("x", "y")

    def explain(self, s: Session, tf: dict | None, O: np.ndarray) -> float | None:
        if tf is None or not tf.get("read"):
            return None
        rng = np.random.default_rng(self.seed)
        ys, xs = np.nonzero(O)
        reach = int(np.hypot(xs - tf[self.kx], ys - tf[self.ky]).max() + 6)
        need = COVER * len(xs)
        hits = 0
        for _ in range(self.n):
            deg = tf["deg"] + rng.normal(0.0, self.sd)
            x = tf[self.kx] + rng.normal(0.0, self.sp)
            y = tf[self.ky] + rng.normal(0.0, self.sp)
            m = cone.raycast(s.passable, x, y, deg % 360.0, visible=s.floor, max_r=reach + 10)
            hits += int(m[ys, xs].sum() >= need)
        return hits / self.n


def main_e3(args) -> int:
    """E3: read the teardrop tip from pixels, then retest the cone and the slivers."""
    import teardrop_tip as tt
    comps = {c["component_id"]: c for c in _components(STORE, _labels(STORE))}
    rows = [r for r in answers().values()
            if r.get("component_id") in comps and r.get("t_ms") is not None
            and not r.get("unsure") and r["session_id"] == DEMO and group(r["answer"]) == "viewcone"]
    demo = Session(DEMO)
    cal = Calibration()
    demo.run_chain(demo.cache_t, calib=cal, holdout=SLIVERS)
    C = cal.result()
    tips = read_tips(demo)
    held = [t for t in sorted(tips) if all(abs(t - h) > HOLDOUT_MS for h in SLIVERS)]
    P = tip_precision(tips, held)
    print("precision:", json.dumps(P, indent=1))
    # Per-axis position noise from the tip's RMS radial residual.
    sp = P["tip_jitter_rms_px"] / math.sqrt(2.0)
    sd = P["facing_jitter_rms20_deg"]
    tip_model = TipModel(sp, sd, args.samples)
    tipc_model = TipModel(sp, sd, args.samples, origin="centre")
    centre = Model(C, False, args.samples, origin="centre")
    teardrop = Model(C, False, args.samples, origin="teardrop")
    read_t = np.array([t for t in sorted(tips) if tips[t].get("read")])

    def tip_at(t):
        u = float(read_t[np.argmin(np.abs(read_t - t))])
        return tips[u] if abs(u - t) <= POSE_TOL_MS else None

    slivers, lit_ok = {}, defaultdict(int)
    for r in rows:
        t = float(r["t_ms"])
        O, why = demo.observed(t, comps[r["component_id"]].get("box"))
        if O is None or O.sum() < MIN_O:
            continue
        pose, tf = demo.pose_at(t), tip_at(t)
        posed = pose is not None and pose["pose"] and pose["window"]
        E = {"tip": tip_model.explain(demo, tf, O), "tip_facing": tipc_model.explain(demo, tf, O),
             "centre": centre.explain(demo, pose, O) if posed else None,
             "teardrop_e2": teardrop.explain(demo, pose, O) if posed else None}
        if t not in SLIVERS:
            for o, e in E.items():
                lit_ok[o + "_scored"] += int(e is not None)
                lit_ok[o] += int(e is not None and e >= PLAUSIBLE)
            continue
        far = [float(u) for u in read_t if abs(u - t) >= SHIFT_MIN_MS]
        pick = [far[i] for i in np.linspace(0, len(far) - 1, min(args.shifts, len(far))).astype(int)]
        out = {"E": E, "tip": None if tf is None else {k: tf[k] for k in ("tip_x", "tip_y", "deg", "ncc")},
               "track_deg": pose["deg"] if posed else None}
        for o, m in (("tip", tip_model), ("tip_facing", tipc_model)):
            vals = np.array([m.explain(demo, tips[u], O) for u in pick], float)
            out[f"null_rate_{o}"] = float((vals >= PLAUSIBLE).mean())
            out[f"true_percentile_{o}"] = None if E[o] is None else float((vals < E[o]).mean())
        slivers[t] = out
        print(f"sliver {t / 1000:.2f}s: {json.dumps(out)}")
    agree = agreement_e3(demo, cal, tips)
    print("lit viewcones explained:", dict(lit_ok))
    print("held-out agreement:", json.dumps(agree, indent=1))
    (args.out / "results_e3.json").write_text(json.dumps(
        {"version": VERSION, "tip_version": tt.VERSION, "calibration": C, "precision": P,
         "slivers": {str(k): v for k, v in slivers.items()}, "lit_viewcones": dict(lit_ok),
         "agreement": agree}, indent=1), encoding="utf-8")
    vals = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in {**P, **agree}.items()}
    for k, v in lit_ok.items():
        vals[f"lit_viewcones_{k}"] = v
    for t in SLIVERS:
        v = slivers.get(t)
        if v is None:
            continue
        for o, e in v["E"].items():
            vals[f"e_{o}_{int(t)}"] = None if e is None else round(e, 3)
        for o in ("tip", "tip_facing"):
            vals[f"null_{o}_{int(t)}"] = round(v[f"null_rate_{o}"], 3)
            vals[f"pct_{o}_{int(t)}"] = (None if v[f"true_percentile_{o}"] is None
                                         else round(v[f"true_percentile_{o}"], 3))
        if v["tip"]:
            vals[f"tip_deg_{int(t)}"] = round(v["tip"]["deg"], 1)
        if v["track_deg"] is not None:
            vals[f"track_deg_{int(t)}"] = round(v["track_deg"], 1)
    for o in ("tip", "tip_facing"):
        vals[f"slivers_explained_{o}"] = sum(1 for v in slivers.values()
                                             if v["E"][o] is not None and v["E"][o] >= PLAUSIBLE)
    metrics.record(
        "sliver_error_model", part="teardrop-tip", session=DEMO, values=vals,
        deps={"prototype": VERSION, "reader": tt.VERSION, "lighting": lighting.LIGHTING_VERSION,
              "cone_half_angle": cone.CONE_HALF_ANGLE_DEG, "samples": args.samples,
              "shifts": args.shifts, "plausible": PLAUSIBLE, "cover": COVER,
              "shape": {"r_in": tt.R_IN, "r_out": tt.R_OUT, "L": tt.L, "min_ncc": tt.MIN_NCC},
              "fact": "minimap/cone-rays-stop-at-first-edge"},
        context={"holdout_ms": HOLDOUT_MS,
                 "arms": ["centre", "tip", "tip_facing", "centre_tipdeg", "teardrop_e2"],
                 "exploratory": "E3b: tip_facing at the slivers and axis_<d> arms, logged after the tip arm failed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
