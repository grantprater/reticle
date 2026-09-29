r"""Score `team_vision`'s team cones against the drawn light joined to the team's icons.

    .\.venv\Scripts\python.exe prototypes\team_vision_eval.py --arm NAME
    .\.venv\Scripts\python.exe prototypes\team_vision_eval.py --compare BEFORE AFTER [--record]

The measurement behind `team-vision-0.5.0`, which casts every teammate's cone
from the ally teardrop's centre along its facing (`reticle.teardrop.
IconPoseReader`), as 0.3.0 cast the self cone. `vision_origin_eval.py` scored
the self cone alone; teammates are a team signal, so this scores the union.

**The chain is the owner's.** Each arm drives `team_vision.TeamVision` over
the frames as the code on disk has it and keeps the frame's cast cones:
`observable` (the eligible union, what `reticle vision` stores as the team's
vision), `observable_all` (every tracked bearing), and, where the frame
reports each cone's source (`VisionFrame.origins`), the eligible union less
the cones a ring fit or a track supplied (`teardrop_only`), which is what the
chain would cast if it refused to fall back.

**The witness does not move between arms.** Every team icon is placed from
the pixels alone: the self icon by `teardrop_tip.fit` from its best
detection, each ally detection (`icon_teardrop.detections`) by the ally
teardrop at the widget's scale where it reads and by a disc of the detector's
radius where it does not. The light is `lighting.raw_lit` on known floor
within `cone_origin.R_EVAL` px of any icon, outside every icon's footprint
(`cone_origin._footprint`, grown by `cone_origin.PAD`); the witness keeps the
lit components that touch a `cone_origin.JOIN_PX` band round any footprint.
It uses no facing. Precision is the share of cone pixels in the region that
the witness holds; recall the share of the witness the cones cover; both pool
pixels over frames, and a frame that casts nothing counts its light in recall.

Frames are `vision_origin_eval`'s: e78e75b2d191's held-out odd 3 s blocks
outside the sliver neighbourhoods, through one chain; 5822b6646448's twenty
6 s windows through `team_vision.at` with a 10 s warm-up. Frames need at
least `cone_origin.MIN_LIT` witness pixels; consecutive identical witnesses
collapse. It reads the minimap crop cache only, decodes no video, and writes
to the store only with `--record` (one `metrics` row).

**Never let an arm choose a facing with the light this witness is built
from.** `cone.resolve_lobe` picks each ring-fit lobe by its lit share on the
same drawn light, so an arm that resolves lobes gets, per cone, the better of
two opposite cones on this metric whatever the true facing; the score
rewards the choice, not the facing. On 331 px widgets the ring fit's raw
axis is close enough that the choice is all that matters, and the ring arm
beat the teardrop there (E11 of docs/STATISTICAL_ADJUDICATOR.md). `--variant`
runs the chain with one factor changed: `ring-lobe` (0.4.0's ally cones:
ring-fit centre and lobe-resolved facing, ungated self teardrop, fallback
on), `ring-raw` (the same with no light in the lobe), `td-lobe` (the
teardrop's facing, flipped wherever the light prefers its reverse) and
`no-self-gate` (0.5.0 without the 331 px self facing gate). `--matched`
scores those factors on the same ally detections, cone by cone, and the self
teardrop and its reverse by NCC bin.

**Predictions** (2026-09-29, before the after arm ran): on both sessions the
eligible union's F1 under 0.4.0 is at least 0.3.0's, and Lotus's rises by at
least 0.02, since the ally ring's lobe-resolved facing errs a median 27
degrees and flips on a tenth of the labels where the teardrop errs 2.5 and
never flips; ally precision rises; pooled recall moves by under 0.03. The
falsifier is a lower F1 on either session.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import cone_origin as co  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import teardrop_tip as tt  # noqa: E402
import vision_origin_eval as voe  # noqa: E402
from reticle import cone, lighting, metrics  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "team-vision-eval-0.3.0"
#: `ncc60` and the like: the eligible teardrop cones whose fit reads at that
#: NCC or more, which is what the chain casts with no fallback and a cast gate
#: there (the tracker and the lifecycle read no facing).
NCC_GATES = (0.55, 0.6, 0.65, 0.7)
UNIONS = ("eligible", "all", "teardrop_only") + tuple(f"ncc{int(round(t * 100))}" for t in NCC_GATES)


class Sess:
    """What the chain and the witness need for any session with baked geometry, a
    lighting reference and a minimap crop cache (`sliver_error_model.Session`
    also wants stored ability-light rows, which 331 px sessions lack)."""

    def __init__(self, sid: str):
        from reticle import geometry, team_vision
        from reticle.profiles import get_profile
        from reticle.roi_cache import RoiCache
        self.sid = sid
        man = geometry.manifest(sid, sem.STORE)
        prof = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        self.inputs, why = team_vision.load_inputs(sem.STORE, sid, prof, w, h)
        if self.inputs is None or self.inputs.light is None:
            raise SystemExit(f"{sid}: no team-vision inputs ({why or 'no lighting reference'})")
        self.box = self.inputs.box
        self.floor, self.passable, self.ref = self.inputs.floor, self.inputs.passable, self.inputs.light
        self.cache, why = RoiCache.load(sem.STORE, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))

    def crops(self, times):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples([float(t) for t in times], rois=["minimap"]):
            yield smp.t_ms, smp.frame[y0:y1, x0:x1]


#: `teardrop` grows each read icon's own teardrop into its footprint (E4's
#: witness); `disc` uses a disc of the apex's reach, so no facing enters the
#: witness at all.
FOOTPRINT = "teardrop"


def icons_of(s, crop) -> list[dict]:
    """Every team icon's footprint seed, from the pixels alone: `{"x", "y", "deg"|None, "r"}`.

    The self icon is `reticle.teardrop.fit_teardrop` from its best detection
    at the widget's scale (at scale 1.0, `teardrop_tip.fit`), each ally the
    ally teardrop at that scale, or its detection where the shape is unread.
    """
    from reticle.teardrop import fit_teardrop
    out = []
    sc = widget_scale(crop.shape[1])
    det = tt.self_start(crop, s.floor)
    if det is not None:
        tf = fit_teardrop(crop, det["cx"], det["cy"], scale=sc)
        if tf.get("read"):
            out.append({"x": tf["x"], "y": tf["y"], "deg": tf["deg"], "role": "self", "sc": sc})
    key = it_.CLASSES["ally"].key(crop)
    for d in it_.detections(crop, "ally", s):
        f = it_.fit(None, "ally", d["cx"], d["cy"], key=key, scale=sc)
        if f.get("read"):
            out.append({"x": f["x"], "y": f["y"], "deg": f["deg"], "role": "ally", "sc": sc})
        else:
            out.append({"x": d["cx"], "y": d["cy"], "deg": None, "r": float(d["r"]), "role": "ally",
                        "sc": sc})
    return out


def footprints(shape, icons) -> np.ndarray:
    """The icons' own pixels: `cone_origin._footprint`'s teardrop at the widget's
    scale, grown by PAD, or with `FOOTPRINT` `disc` (or no facing) a disc."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    fp = np.zeros(shape, bool)
    for ic in icons:
        sc = ic["sc"]
        if ic["deg"] is not None and FOOTPRINT == "teardrop":
            fp |= tt.render(xx - ic["x"], yy - ic["y"], math.radians(ic["deg"]), r_in=0.0,
                            r_out=tt.R_OUT * sc + co.PAD, L_=tt.L * sc + co.PAD, edge=1.0) > 0
        elif FOOTPRINT == "disc":
            fp |= np.hypot(xx - ic["x"], yy - ic["y"]) <= tt.L * sc + co.PAD
        else:
            fp |= np.hypot(xx - ic["x"], yy - ic["y"]) <= ic["r"] + co.PAD
    return fp


def witness(s, crop, icons):
    """`(region, joined light)` round every team icon, or None when no icon is placed."""
    import cv2
    if not icons:
        return None
    h, w = s.passable.shape
    yy, xx = np.mgrid[0:h, 0:w]
    near = np.zeros((h, w), bool)
    for ic in icons:
        near |= np.hypot(xx - ic["x"], yy - ic["y"]) <= co.R_EVAL * ic["sc"]
    fp = footprints((h, w), icons)
    region = near & s.ref.known & ~fp
    raw = lighting.raw_lit(crop, s.ref)
    lit = (raw & region).astype(np.uint8)
    band = cv2.dilate(fp.astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * co.JOIN_PX + 1,) * 2)) > 0
    n, lab = cv2.connectedComponents(lit, connectivity=8)
    keep = np.unique(lab[band & (lit > 0)])
    keep = keep[keep > 0]
    wit = np.isin(lab, keep) if len(keep) else np.zeros((h, w), bool)
    return region, wit


def unions(s, fr) -> dict:
    """The frame's cast cones as masks, per union, and per role for the eligible one."""
    shape = s.passable.shape
    empty = np.zeros(shape, bool)
    if fr.widget != "drawn" or fr.observable is None:
        return {u: empty for u in UNIONS} | {"self": empty, "ally": empty, "sources": {}}
    out = {"eligible": fr.observable, "all": fr.observable_all}
    origins = getattr(fr, "origins", None) or []
    poses = getattr(fr, "poses", None) or []
    gated = {thr: [] for thr in NCC_GATES}
    keep = []
    by_role = {"self": empty.copy(), "ally": empty.copy()}
    sources: dict[str, int] = {}
    cones = fr.cones or []
    for i, ((role, tr), (_x, _y, adj, _c)) in enumerate(zip(fr.tracked, fr.adjudicated_resolved)):
        if adj is None or i >= len(cones) or cones[i] is None:
            continue
        src = source_of(fr, i, role, origins)
        sources[src] = sources.get(src, 0) + 1
        by_role[role] |= cones[i]
        if src == "teardrop/teardrop":
            keep.append(cones[i])
            ncc = (poses[i] or {}).get("ncc") if i < len(poses) else None
            for thr in NCC_GATES:
                if ncc is not None and ncc >= thr:
                    gated[thr].append(cones[i])
    out["teardrop_only"] = cone.union(keep, shape) if keep else empty
    for thr in NCC_GATES:
        out[f"ncc{int(round(thr * 100))}"] = cone.union(gated[thr], shape) if gated[thr] else empty
    return out | by_role | {"sources": sources}


def source_of(fr, i: int, role: str, origins) -> str:
    """`origin/facing` of cone `i`: the frame's own record where it keeps one."""
    rec = None
    poses = getattr(fr, "poses", None)
    if poses:
        rec = poses[i]
    elif role == "self":
        rec = getattr(fr, "self_cone", None)
    if rec is not None:
        return f"{rec.get('origin')}/{rec.get('facing')}"
    return f"{origins[i][2] if i < len(origins) else 'ring_fit'}/track"


def arm(sid: str) -> dict:
    s = Sess(sid)
    rows, prev, why = [], None, {}
    for t, crop, fr in voe.frames_of(s, sid):
        icons = icons_of(s, crop)
        got = witness(s, crop, icons)
        if got is None:
            why["no_icon"] = why.get("no_icon", 0) + 1
            continue
        region, wit = got
        key = (int(wit.sum()), tuple(sorted((round(i["x"], 2), round(i["y"], 2)) for i in icons)))
        if key == prev:
            continue
        prev = key
        if int(wit.sum()) < co.MIN_LIT:
            why["little_light"] = why.get("little_light", 0) + 1
            continue
        u = unions(s, fr)
        row = {"t": t, "lit": int(wit.sum()), "sources": u["sources"],
               "icons": len(icons), "allies_placed": sum(1 for i in icons if i["role"] == "ally")}
        for name in UNIONS + ("self", "ally"):
            m = u[name]
            row[name] = {"hits": int((m & wit).sum()), "n": int((m & region).sum())}
        rows.append(row)
    return {"rows": rows, "why": why}


VARIANTS = ("ring-lobe", "ring-raw", "td-lobe", "no-self-gate")


def apply_variant(name: str) -> None:
    """Patch `team_vision.TeamVision` (and the self gate) for one `--variant`, in process."""
    from reticle import team_vision, teardrop
    tv = team_vision.TeamVision

    class _RingOnly:
        def read(self, crop, cx, cy):
            return {"x": float(cx), "y": float(cy), "deg": None, "origin": "ring_fit",
                    "ncc": None, "reason": "variant_ring_only"}

    class _SelfUngated(teardrop.SelfConeReader):
        def read(self, crop, cx, cy):
            tf = teardrop.fit_teardrop(crop, cx, cy, scale=self.scale)
            if tf.get("read"):
                return {"x": float(tf["x"]), "y": float(tf["y"]), "deg": float(tf["deg"]),
                        "origin": "teardrop", "ncc": float(tf["ncc"])}
            return {"x": float(cx), "y": float(cy), "deg": None, "origin": "ring_fit",
                    "ncc": tf.get("ncc"), "reason": tf.get("reason")}

    if name in ("ring-lobe", "ring-raw"):
        init = tv.__init__

        def ring_init(self, *a, **kw):
            kw["ring_fallback"] = True
            init(self, *a, **kw)
            self.ally_pose_reader = _RingOnly()
            self.self_cone_reader = _SelfUngated(scale=self.scale)
        tv.__init__ = ring_init
        if name == "ring-raw":
            tv._resolve_fallback = lambda self, lit, dets: dets
    elif name == "td-lobe":
        def every_lobe(self, lit, dets):
            idx = [i for i, d in enumerate(dets) if d.get("facing") is not None]
            out = list(dets)
            for i, e in zip(idx, cone.resolve_lobe(self.passable, lit, [dets[i] for i in idx],
                                                   visible=self.floor)):
                out[i] = e
            return out
        tv._resolve_fallback = every_lobe
    elif name == "no-self-gate":
        teardrop.labelled_scale = lambda scale: True
    else:
        raise SystemExit(f"unknown variant {name!r}")


SELF_BINS = ((0.0, 0.55, "self_lt55"), (0.55, 0.6, "self_55_60"), (0.6, 0.7, "self_60_70"),
             (0.7, 1.01, "self_ge70"))


def matched(sid: str, every: int = 2) -> dict:
    """Cone by cone on the same detections, scored against the witness.

    Every `every`-th frame of `cone_origin.windows` with enough witness light.
    For each ally detection whose teardrop reads and whose ring fit has a
    facing: `td_td` (teardrop centre and facing, 0.5.0's cone), `ring_lobe`
    (ring-fit centre, lobe resolved by `lighting.lit_mask`, 0.4.0's per-frame
    input), `ring_td`, `td_lobe`, `ring_raw` (the ring's facing, no light) and
    `td_rev` (the teardrop's reverse), pooled over all such detections and
    split by whether the teardrop and the lobe differ by more than 90 degrees.
    Unread teardrops score `ring_lobe` and `ring_raw` apart. The self
    teardrop (`teardrop_tip.self_start`, ungated) and its reverse are pooled
    by NCC bin. Returns `{"frames", "acc": {bucket: {cone: [hits, n, cones]}}}`.
    """
    from reticle.minimap import ally_icons, widget_drawn
    from reticle.teardrop import IconPoseReader, fit_teardrop
    s = Sess(sid)
    sc = widget_scale(s.box[2] - s.box[0])
    rdr = IconPoseReader("ally", sc)
    half = cone.CONE_HALF_ANGLE_DEG
    times = sorted(float(t) for _, sel in co.windows(s) for t in sel)[::every]
    acc: dict = {}
    frames = 0

    def add(bucket, k, m, region, wit):
        a = acc.setdefault(bucket, {}).setdefault(k, [0, 0, 0])
        a[0] += int((m & wit).sum())
        a[1] += int((m & region).sum())
        a[2] += 1

    def ray(x, y, deg):
        return cone.raycast(s.passable, x, y, deg, half, s.floor)

    for _t, crop in s.crops(times):
        if not widget_drawn(crop, s.inputs.sgray, s.floor):
            continue
        got = witness(s, crop, icons_of(s, crop))
        if got is None or int(got[1].sum()) < co.MIN_LIT:
            continue
        region, wit = got
        frames += 1
        sd = tt.self_start(crop, s.floor)
        if sd is not None:
            f = fit_teardrop(crop, sd["cx"], sd["cy"], scale=sc)
            if f.get("read"):
                b = next(tag for lo, hi, tag in SELF_BINS if lo <= f["ncc"] < hi)
                add(b, "td", ray(f["x"], f["y"], f["deg"]), region, wit)
                add(b, "rev", ray(f["x"], f["y"], f["deg"] + 180.0), region, wit)
        lit = lighting.lit_mask(crop, s.ref)
        dets = ally_icons(crop, s.floor, require_facing=False, support=s.inputs.slab,
                          static=s.inputs.static)
        for d, e in zip(dets, cone.resolve_lobe(s.passable, lit, dets, visible=s.floor)):
            if e.get("facing") is None:
                continue
            p = rdr.read(crop, d["cx"], d["cy"])
            if p["deg"] is None:
                add("unread", "ring_lobe", ray(d["cx"], d["cy"], e["facing"]), region, wit)
                add("unread", "ring_raw", ray(d["cx"], d["cy"], d["facing"]), region, wit)
                continue
            split = "agree" if abs(float(sem._signed_deg(p["deg"] - e["facing"]))) <= 90.0 else "disagree"
            cones = {"td_td": (p["x"], p["y"], p["deg"]), "ring_lobe": (d["cx"], d["cy"], e["facing"]),
                     "ring_td": (d["cx"], d["cy"], p["deg"]), "td_lobe": (p["x"], p["y"], e["facing"]),
                     "ring_raw": (d["cx"], d["cy"], d["facing"]),
                     "td_rev": (p["x"], p["y"], p["deg"] + 180.0)}
            for k, (x, y, deg) in cones.items():
                m = ray(x, y, deg)
                for bucket in ("all", split):
                    add(bucket, k, m, region, wit)
    return {"sid": sid, "frames": frames, "acc": acc}


NCC_BINS = (0.5, 0.6, 0.7, 0.8, 1.01)


def pose_check(sid: str, every: int = 3, times=None) -> dict:
    """Per icon, the teardrop's facing against the ring fit's after the light
    resolves its lobe (`cone.resolve_lobe`, 0.3.0's per-frame input), by NCC.

    Every `every`-th cached frame of `cone_origin.windows`. Per detection: the
    promoted reader at the widget's scale (`SelfConeReader` for the best self
    fit by coverage, `IconPoseReader` for each ally), the ring fit's raw and
    lobe-resolved facing, and where the two facings differ by more than 90
    degrees, the light's verdict: the lit share (`cone.compare_evidence`) of
    each facing's cone from the teardrop's centre, so only the facing differs.

    `times` replaces the windows' frames (`label_icon_facing`'s 331 px set
    draws its pool from the round-live frames). Each row carries the
    detection's centre (`det_x`, `det_y`, `r`) and the reader's (`x`, `y`).
    """
    from reticle import cone as cone_mod
    from reticle.minimap import ally_icons, self_icons, widget_drawn
    from reticle.teardrop import IconPoseReader
    s = Sess(sid)
    sc = widget_scale(s.box[2] - s.box[0])
    class _SelfFit:
        """The self teardrop's own read, before `SelfConeReader`'s facing gate,
        which this check measures and so must not apply."""

        def read(self, crop, cx, cy):
            from reticle.teardrop import fit_teardrop
            f = fit_teardrop(crop, cx, cy, scale=sc)
            if f.get("read"):
                return {"x": f["x"], "y": f["y"], "deg": f["deg"], "origin": "teardrop", "ncc": f["ncc"]}
            return {"x": cx, "y": cy, "deg": None, "origin": "ring_fit", "ncc": f.get("ncc"),
                    "reason": f.get("reason")}

    readers = {"self": _SelfFit(), "ally": IconPoseReader("ally", sc)}
    if times is None:
        times = sorted(float(t) for _, sel in co.windows(s) for t in sel)[::every]
    rows = []
    for t, crop in s.crops(times):
        if not widget_drawn(crop, s.inputs.sgray, s.floor):
            continue
        lit = lighting.lit_mask(crop, s.ref)
        selves = self_icons(crop, s.floor, require_facing=False, support=s.inputs.slab)
        dets = {"self": sorted(selves, key=lambda d: -d["cov"])[:1],
                "ally": ally_icons(crop, s.floor, require_facing=False, support=s.inputs.slab,
                                   static=s.inputs.static)}
        for role, ds in dets.items():
            lobed = cone_mod.resolve_lobe(s.passable, lit, ds, visible=s.floor, known=s.ref.known)
            for d, e in zip(ds, lobed):
                p = readers[role].read(crop, d["cx"], d["cy"])
                row = {"t": t, "role": role, "origin": p["origin"], "ncc": p.get("ncc"),
                       "reason": p.get("reason"), "deg": p["deg"], "ring": d.get("facing"),
                       "lobe": e.get("facing"), "offset": math.hypot(p["x"] - d["cx"], p["y"] - d["cy"]),
                       "x": float(p["x"]), "y": float(p["y"]), "det_x": float(d["cx"]),
                       "det_y": float(d["cy"]), "r": float(d.get("r", 0.0))}
                if p["deg"] is not None and e.get("facing") is not None:
                    row["dis"] = abs(float(sem._signed_deg(p["deg"] - e["facing"])))
                    if row["dis"] > 90.0:
                        sh = []
                        for deg in (p["deg"], e["facing"]):
                            m = cone_mod.raycast(s.passable, p["x"], p["y"], deg,
                                                 cone_mod.CONE_HALF_ANGLE_DEG, s.floor)
                            sh.append(cone_mod.compare_evidence(m, lit, s.ref.known)["lit_share"])
                        row["lit_teardrop"], row["lit_lobe"] = sh
                rows.append(row)
    return {"sid": sid, "width": int(s.box[2] - s.box[0]), "rows": rows}


def pose_summary(res: dict) -> dict:
    out = {"width": res["width"]}
    for role in ("self", "ally"):
        rs = [r for r in res["rows"] if r["role"] == role]
        read = [r for r in rs if r["origin"] == "teardrop"]
        both = [r for r in read if "dis" in r]
        flips = [r for r in both if r["dis"] > 90.0]
        judged = [r for r in flips if r.get("lit_teardrop") is not None and r.get("lit_lobe") is not None]
        o = {"n": len(rs), "read_rate": round(len(read) / len(rs), 3) if rs else None,
             "refused": dict(Counter(r["reason"] for r in rs if r["origin"] != "teardrop")),
             "ncc_q": (np.percentile([r["ncc"] for r in read], [10, 25, 50]).round(3).tolist()
                       if read else None),
             "offset_px_median": round(float(np.median([r["offset"] for r in read])), 2) if read else None,
             "over90_vs_lobe": round(len(flips) / len(both), 3) if both else None,
             "light_prefers_teardrop": (round(float(np.mean([r["lit_teardrop"] > r["lit_lobe"]
                                                               for r in judged])), 3) if judged else None),
             "judged": len(judged), "bins": {}}
        for lo, hi in zip(NCC_BINS[:-1], NCC_BINS[1:]):
            b = [r for r in both if lo <= r["ncc"] < hi]
            bf = [r for r in b if r["dis"] > 90.0]
            bj = [r for r in bf if r.get("lit_teardrop") is not None and r.get("lit_lobe") is not None]
            o["bins"][f"{lo:.1f}"] = {"n": len(b), "over90": round(len(bf) / len(b), 3) if b else None,
                                      "light_prefers_teardrop": (round(float(np.mean(
                                          [r["lit_teardrop"] > r["lit_lobe"] for r in bj])), 3)
                                          if bj else None), "judged": len(bj)}
        out[role] = o
    return out


def pool(rows, name: str) -> dict:
    h = sum(r[name]["hits"] for r in rows)
    n = sum(r[name]["n"] for r in rows)
    lit = sum(r["lit"] for r in rows)
    return {"frames": len(rows), "precision": h / n if n else None,
            "recall": h / lit if lit else None, "f1": 2 * h / (n + lit) if (n + lit) else None}


def main(argv=None) -> int:
    global FOOTPRINT
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arm", help="run the code on disk and save it under this name")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="score two saved arms on their common frames")
    ap.add_argument("--record", action="store_true", help="with --compare: one metrics row")
    ap.add_argument("--out", type=Path, default=Path(sem.tempfile.gettempdir()) / "team-vision-eval")
    ap.add_argument("--sessions", nargs="+", default=[sem.DEMO, voe.LOTUS])
    ap.add_argument("--pose-check", nargs="+", metavar="SID",
                    help="the teardrop's facing against the light-resolved ring fit, by NCC")
    ap.add_argument("--footprint", choices=("teardrop", "disc"), default=FOOTPRINT,
                    help="the witness's icon footprint (see FOOTPRINT)")
    ap.add_argument("--variant", choices=VARIANTS,
                    help="with --arm: the chain with one factor changed (see the module docstring)")
    ap.add_argument("--label", default="",
                    help="with --compare --record: a suffix naming the comparison in the metric part")
    ap.add_argument("--matched", nargs="+", metavar="SID",
                    help="cone by cone on the same detections: facing and centre sources, "
                         "and the self teardrop against its reverse by NCC")
    ap.add_argument("--no-fallback", action="store_true",
                    help="with --arm: the chain casts nothing where the teardrop is unread "
                         "(`TeamVision(ring_fallback=False)`)")
    args = ap.parse_args(argv)
    sem._below_normal()
    args.out.mkdir(parents=True, exist_ok=True)
    FOOTPRINT = args.footprint
    if args.pose_check:
        for sid in args.pose_check:
            res = pose_check(sid)
            (args.out / f"pose_{sid}.json").write_text(json.dumps(res), encoding="utf-8")
            summ = pose_summary(res)
            print(sid, json.dumps(summ), flush=True)
            if args.record:
                from reticle.version import ICON_TEARDROP_VERSION, TEARDROP_VERSION
                values = {"width": summ["width"]}
                for role in ("self", "ally"):
                    o = summ[role]
                    values.update({f"{role}_n": o["n"], f"{role}_read_rate": o["read_rate"],
                                   f"{role}_ncc_median": o["ncc_q"][2] if o["ncc_q"] else None,
                                   f"{role}_over90": o["over90_vs_lobe"]})
                    for lo, b in o["bins"].items():
                        tag = lo.replace(".", "")
                        values[f"{role}_ncc{tag}_n"] = b["n"]
                        if b["over90"] is not None:
                            values[f"{role}_ncc{tag}_over90"] = b["over90"]
                metrics.record("team_vision_eval", part="pose-check", session=sid, values=values,
                               deps={"prototype": VERSION, "teardrop": TEARDROP_VERSION,
                                     "icon_teardrop": ICON_TEARDROP_VERSION, "every": 3,
                                     "witness": "minimap.fit_ring facing after cone.resolve_lobe "
                                                "(known-aware); agreement, not accuracy"},
                               note="teardrop facing against the ring fit's lobe-resolved facing, by NCC")
        return 0
    if args.matched:
        for sid in args.matched:
            res = matched(sid)
            (args.out / f"matched_{sid}.json").write_text(json.dumps(res), encoding="utf-8")
            values = {"frames": res["frames"]}
            for bucket, cones in res["acc"].items():
                for k, (h, n, c) in cones.items():
                    values[f"{bucket}_{k}_cones"] = c
                    if n:
                        values[f"{bucket}_{k}_precision"] = round(h / n, 4)
            print(sid, json.dumps(values, indent=1), flush=True)
            if args.record:
                from reticle.version import ICON_TEARDROP_VERSION, TEARDROP_VERSION
                metrics.record("team_vision_eval", part="matched", session=sid, values=values,
                               deps={"prototype": VERSION, "witness": co.VERSION, "footprint": FOOTPRINT,
                                     "lighting": lighting.LIGHTING_VERSION, "every": 2,
                                     "teardrop": TEARDROP_VERSION, "icon_teardrop": ICON_TEARDROP_VERSION},
                               note="cone by cone on the same ally detections; self teardrop and "
                                    "reverse by NCC; precision against the joined team light")
        return 0
    if args.variant:
        apply_variant(args.variant)
    if args.no_fallback:
        from reticle import team_vision
        base = team_vision.TeamVision.from_inputs.__func__
        team_vision.TeamVision.from_inputs = classmethod(
            lambda cls, inputs, origin_events=(), **kw: base(cls, inputs, origin_events,
                                                             ring_fallback=False, **kw))
    if args.arm:
        res = {sid: arm(sid) for sid in args.sessions}
        (args.out / f"{args.arm}.json").write_text(json.dumps(res), encoding="utf-8")
        for sid, r in res.items():
            print(args.arm, sid, {u: pool(r["rows"], u) for u in UNIONS}, "skipped", r["why"], flush=True)
    if args.compare:
        nb, na = args.compare
        b = json.loads((args.out / f"{nb}.json").read_text(encoding="utf-8"))
        a = json.loads((args.out / f"{na}.json").read_text(encoding="utf-8"))
        values = {}
        for sid in args.sessions:
            tag = {sem.DEMO: "e78e", voe.LOTUS: "lotus"}.get(sid, sid[:4])
            rb = {r["t"]: r for r in b[sid]["rows"]}
            ra = {r["t"]: r for r in a[sid]["rows"]}
            common = sorted(set(rb) & set(ra))
            for arm_name, rows in (("before", [rb[t] for t in common]), ("after", [ra[t] for t in common])):
                for u in UNIONS + ("self", "ally"):
                    if rows and u not in rows[0]:
                        continue          # an arm saved before this union existed
                    p = pool(rows, u)
                    print(sid, arm_name, u, {k: (round(v, 4) if isinstance(v, float) else v)
                                             for k, v in p.items()})
                    for k in ("precision", "recall", "f1"):
                        if p[k] is not None and (u in ("eligible", "teardrop_only") or k == "precision"):
                            values[f"{tag}_{arm_name}_{u}_{k}"] = round(float(p[k]), 4)
                srcs: dict[str, int] = {}
                for r in rows:
                    for k, v in r["sources"].items():
                        srcs[k] = srcs.get(k, 0) + v
                print(sid, arm_name, "cone sources", srcs)
                for k, v in srcs.items():
                    values[f"{tag}_{arm_name}_src_{k.replace('/', '_')}"] = v
            values[f"{tag}_frames"] = len(common)
            values[f"{tag}_witness_changed"] = sum(1 for t in common if ra[t]["lit"] != rb[t]["lit"])
        print(json.dumps(values, indent=1))
        if args.record:
            from reticle.version import ICON_TEARDROP_VERSION, TEAM_VISION_VERSION
            metrics.record("team_vision_eval", part=f"joined-team-light-{FOOTPRINT}"
                           + (f"-{args.label}" if args.label else ""),
                           session="+".join(args.sessions), values=values,
                           deps={"prototype": VERSION, "witness": co.VERSION, "reader": it_.VERSION,
                                 "footprint": FOOTPRINT,
                                 "lighting": lighting.LIGHTING_VERSION, "before": nb, "after": na,
                                 "team_vision": TEAM_VISION_VERSION, "icon_teardrop": ICON_TEARDROP_VERSION,
                                 "warmup_ms_lotus": voe.WARMUP_MS})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
