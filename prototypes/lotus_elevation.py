r"""Which occluders block the self cone standing and jumping, at the largest
minimap settings, on one Lotus and one Split clip (neither ingested).

    .\.venv\Scripts\python.exe prototypes\lotus_elevation.py [--clip split] extract
    ... witness | occluders | events | summarize [--record] | sheets
    ... placement [--record] | corner [--record]

The decode (20 Hz lossless crops of the fixed widget ROI, a small grey main
view, mono audio) ran once per clip from a scratch script; every step here
reads the store's `analysis/{lotus,split}-elevation-20260930/`. Map values
come only from the baked `valorant-16x9-bigmap` geometry.

Widget. Both clips draw the bigmap profile unchanged: scale
[metric:lotus_elevation/placement@2026-09-30_13-25-33#scale_median=1.0],
corner ([metric:lotus_elevation/placement@2026-09-30_13-25-33#corner_x=15.0],
[metric:lotus_elevation/placement@2026-09-30_13-25-33#corner_y=15.0])
[domain:capture/largest-settings-widget]. The map is painted only inside the
widget ring; Split's far B corner lies outside it
([metric:lotus_elevation/ring@2026-09-30_13-37-46#region0_px=500] baked px)
and Lotus loses a small corner
([metric:lotus_elevation/ring@2026-09-30_13-25-33#outside_px=122] px)
[domain:capture/largest-scaling-shows-whole-map-belief]. A self in the cut
corner is drawn as a blue triangle on the ring
[domain:minimap/off-widget-self-marker]; `marker` finds its apex fixed at
map-up while the facing turns, off the ring radial by about 60 degrees.

Jump witness. The first-person camera's vertical motion
(`cv2.phaseCorrelate` on the small main view): a rise of at least 5 px with
the mouse still that comes back is a jump; one that stays up is a step-up.
The audio corroborates it (takeoff near -60 dB, landing
[metric:lotus_elevation/heights@2026-09-30_13-25-33#landing_db_min=-48.7] to
[metric:lotus_elevation/heights@2026-09-30_13-25-33#landing_db_max=-45.4] dB
on Lotus); the drawn light is never a witness of its own switch.

Heights. Eye height = floor + state offset; an occluder blocks iff the eye is
below its top [domain:minimap/boxes-block-unless-raised]. `summarize` writes
one inequality row per (jump, occluder, state) and the class per caster
floor to `domain/heights/<geometry>.toml`. The light switches whole: on the
mound every flipped pixel lights in one frame at takeoff and goes dark in one
frame at landing (the flip timelines in the metrics row).
The C Mound is short, and its standing shadow starts at an undrawn crest
[metric:lotus_elevation/heights@2026-09-30_13-25-33#mound_crest_frac_min=0.344]
to [metric:lotus_elevation/heights@2026-09-30_13-25-33#mound_crest_frac_max=0.41]
of the way across, not at the shade edge
[domain:minimap/floor-shade-is-elevation]. Split's far-left B box is short
from the raised plant zone and tall from below its stairs; the zone carries no
shade and a notch in its west edge (x
[metric:lotus_elevation/split@2026-09-30_13-37-46#notch_x0=53]-[metric:lotus_elevation/split@2026-09-30_13-37-46#notch_x1=60])
marks the stairs [domain:minimap/heaven-sees-over-area]. Vertical abilities
lift a caster higher still [domain:abilities/jett-updraft-lifts-above-jump]
[domain:abilities/waylay-vertical-lifts-above-jump]
[domain:abilities/raze-satchel-lifts-above-jump]; neither clip tests them.

Occluder witnesses. `ray_hits` takes each ray's first drawn occluder pixel
with only the void closed, because the baked `occ` holds some box outlines
and the mound's dotted edge as WALL; a small box far from the caster is read
from the flip pixels in a window round it instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "2"

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import cone, geometry, lighting  # noqa: E402
from reticle.minimap import floor_mask, self_icons, slab_mask, widget_drawn, widget_scale  # noqa: E402
from reticle.teardrop import SelfConeReader  # noqa: E402

cv2.setNumThreads(2)
VERSION = "lotus-elevation-0.1.0"
VID = "C:/Users/grant/Videos/2026-09-30 13-25-33.mp4"
SESSION = "2026-09-30_13-25-33"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "lotus-elevation-20260930"
KEY = geometry.key("lotus", "valorant-16x9-bigmap")

#: The two clips at the largest minimap settings. `use` swaps the module's
#: clip constants; every step reads them at call time.
CLIPS = {
    "lotus": {"VID": VID, "SESSION": SESSION, "OUT": OUT, "KEY": KEY},
    "split": {"VID": "C:/Users/grant/Videos/2026-09-30 13-37-46.mp4", "SESSION": "2026-09-30_13-37-46",
              "OUT": STORE / "analysis" / "split-elevation-20260930",
              "KEY": geometry.key("split", "valorant-16x9-bigmap")},
}
CLIP = "lotus"


def use(clip: str):
    global VID, SESSION, OUT, KEY, CLIP
    c = CLIPS[clip]
    VID, SESSION, OUT, KEY, CLIP = c["VID"], c["SESSION"], c["OUT"], c["KEY"], clip


def idle():
    """IDLE priority for this process, checked."""
    if os.name != "nt":
        os.nice(19)
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.GetPriorityClass.argtypes = [wintypes.HANDLE]
    h = k.GetCurrentProcess()
    k.SetPriorityClass(h, 0x40)
    if k.GetPriorityClass(h) != 0x40:
        raise SystemExit("idle priority did not take")


class Geo:
    """The baked `(map, profile)` arrays, the only map values this reads."""

    def __init__(self):
        with np.load(geometry.path(KEY)) as z:
            self.static = z["static"].copy()
            self.labels = z["labels"].copy()
            self.occ = z["occ"].copy()
            self.box_id = z["box_id"].copy()
            self.shade_step = z["shade_step"].copy()
            self.shade_kind = z["shade_kind"].copy()
            self.sd = z["sd_lo"].copy()
            self.light = lighting.reference(z)
        self.sgray = cv2.cvtColor(self.static, cv2.COLOR_BGR2GRAY).astype(np.float64)
        self.floor = floor_mask(self.static, sd=self.sd)
        self.slab = slab_mask(self.static, sd=self.sd)
        self.walls_only = cone.passable_from(self.labels, self.floor, self.occ, boxes_block=False)
        self.passable = cone.passable_from(self.labels, self.floor, self.occ)
        self.scale = widget_scale(self.static.shape[1])


def crops():
    z = np.load(OUT / "roi_crops.npz")
    return z["t"], z["minimap"]


def extract():
    """Per frame: widget drawn, the self pose (teardrop owner), the drawn light."""
    g = Geo()
    ts, mm = crops()
    reader = SelfConeReader(scale=g.scale)
    rows, lits, raws = [], [], []
    prev = None
    for t, crop in zip(ts, mm):
        drawn = bool(widget_drawn(crop, g.sgray, g.floor))
        row = {"t": float(t), "drawn": drawn}
        lit = np.zeros(g.floor.shape, bool)
        raw = np.zeros(g.floor.shape, bool)
        if drawn:
            selves = self_icons(crop, g.floor, require_facing=False, support=g.slab)
            if selves:
                if prev is not None:
                    d = min(selves, key=lambda s: np.hypot(s["cx"] - prev[0], s["cy"] - prev[1]))
                else:
                    d = max(selves, key=lambda s: s.get("cov", 0))
                pose = reader.read(crop, d["cx"], d["cy"])
                row.update(ring_x=float(d["cx"]), ring_y=float(d["cy"]), x=pose["x"], y=pose["y"],
                           deg=pose["deg"], origin=pose["origin"], ncc=pose.get("ncc"),
                           reason=pose.get("reason") or pose.get("facing_reason"))
                prev = (pose["x"], pose["y"])
            raw = lighting.raw_lit(crop, g.light)
            lit = lighting.clean_lit(raw, g.light)
        rows.append(row)
        lits.append(lit)
        raws.append(raw)
    np.savez_compressed(OUT / "frames.npz", lit=np.packbits(np.array(lits), axis=-1),
                        raw=np.packbits(np.array(raws), axis=-1), shape=np.array(g.floor.shape))
    (OUT / "frames.json").write_text(json.dumps({"version": VERSION, "key": KEY, "rows": rows}))
    n = sum(1 for r in rows if r.get("deg") is not None)
    print(f"{len(rows)} frames, {sum(r['drawn'] for r in rows)} drawn, {n} with a teardrop facing")


def load_frames():
    rows = json.loads((OUT / "frames.json").read_text())["rows"]
    z = np.load(OUT / "frames.npz")
    h, w = z["shape"]
    lit = np.unpackbits(z["lit"], axis=-1)[..., :w].astype(bool)
    raw = np.unpackbits(z["raw"], axis=-1)[..., :w].astype(bool)
    return rows, lit, raw


#: The self audio circle's radius on this widget: the bigmap Lotus footstep
#: circle, measured on 5822b6646448, whose placement this clip shares exactly.
AUDIO_R = 108.45


def rim_score(dg, cx, cy, r, n=180):
    """Median over rays of the rim's grey minus the mean of 4 px either side."""
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rs = np.array([r - 4, r, r + 4])
    xs = (cx + np.outer(np.cos(ang), rs)).astype(np.float32)
    ys = (cy + np.outer(np.sin(ang), rs)).astype(np.float32)
    v = cv2.remap(dg, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float("nan"))
    with np.errstate(all="ignore"):
        return float(np.nanmedian(v[:, 1] - 0.5 * (v[:, 0] + v[:, 2])))


def witness():
    """Three candidate jump witnesses, none of them the light: the camera's
    vertical motion in the first-person view, the audio envelope, and the
    self audio circle's rim at the self centre."""
    rows, _, _ = load_frames()
    g = Geo()
    z = np.load(OUT / "mainview_small.npz")
    mv = z["gray"].astype(np.float32)
    win = cv2.createHanningWindow(mv.shape[1:][::-1], cv2.CV_32F)
    dx, dy, resp = [0.0], [0.0], [1.0]
    for a, b in zip(mv[:-1], mv[1:]):
        (sx, sy), r = cv2.phaseCorrelate(a, b, win)
        dx.append(sx); dy.append(sy); resp.append(r)
    ts, mm = crops()
    rim = []
    for r, crop in zip(rows, mm):
        if r.get("x") is None:
            rim.append(float("nan")); continue
        dg = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
                              - g.sgray.astype(np.float32), (0, 0), 0.7)
        rim.append(max(rim_score(dg, r["x"], r["y"], AUDIO_R + d) for d in (-2, 0, 2)))
    import wave
    with wave.open(str(OUT / "audio_mono24k.wav")) as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    hop = sr // 100
    env = np.sqrt(np.convolve(a * a, np.ones(hop) / hop, "same")[::hop])
    np.savez(OUT / "witness.npz", t=ts, cam_dx=np.array(dx), cam_dy=np.array(dy), cam_resp=np.array(resp),
             rim=np.array(rim), env=env, env_hz=100)
    print("witness saved")


#: A jump in the first-person view: the scene moves down (camera up) by at
#: least RISE_MIN small-view px within RISE_WIN frames of the onset, with the
#: mouse still (|dx| <= STILL_DX), and comes back to within LAND_TOL of where
#: it started. A rise that never comes back is a step up onto something.
ONSET_DY, STILL_DX, RISE_MIN, RISE_WIN, LAND_TOL, AIR_MAX = 1.0, 1.5, 5.0, 8, 1.0, 20


def jumps(w):
    """`[{onset, land, kind}]` in frame indices, from the camera alone."""
    dy, dx = w["cam_dy"], w["cam_dx"]
    out, i, n = [], 1, len(dy)
    while i < n - RISE_WIN:
        if dy[i] >= ONSET_DY and np.all(np.abs(dx[i:i + 3]) <= STILL_DX):
            c = np.cumsum(dy[i:i + AIR_MAX + 1])
            pk = int(np.argmax(c[:RISE_WIN + 1]))
            if c[pk] >= RISE_MIN:
                back = [k for k in range(pk, len(c)) if c[k] <= LAND_TOL]
                if back:
                    out.append({"onset": i, "land": i + back[0], "kind": "jump", "rise": float(c[pk])})
                    i += back[0] + 1
                    continue
                out.append({"onset": i, "land": None, "kind": "step_up", "rise": float(c[pk])})
                i += AIR_MAX
                continue
        i += 1
    return out


def frame_states(n, js, pad=2):
    """Per frame: `air` strictly between onset and landing, `ground` at least
    `pad` frames from any jump or step, else `transition`."""
    st = np.array(["ground"] * n, dtype=object)
    for j in js:
        a = j["onset"]
        b = j["land"] if j["land"] is not None else j["onset"] + AIR_MAX
        st[max(0, a - pad):min(n, b + pad + 1)] = "transition"
        if j["kind"] == "jump":
            st[a + 1:b] = "air"
    return st


#: The mound on C: the rung-1 region round (131, 313) in the baked frame.
MOUND_SEED = (131, 313)
#: Rung regions smaller than this are paint specks, not platforms.
RUNG_MIN_PX = 30
#: Beyond an occluder, a frame decides only on at least this many classifiable pixels.
MIN_BEYOND = 30
LIT_HI, LIT_LO = 0.8, 0.2


def occluder_ids(g: Geo):
    """The baked boxes, plus each raised shade region as an occluder of its
    own (a platform's edge is a step a ray may or may not pass). A rung
    region that overlaps a baked box takes the box's id: one object. Walls
    stay closed everywhere but on the mound, whose dotted outline `occ` holds
    as WALL although it is the edge of a slope; there the region is opened
    with a 2 px margin and the light decides."""
    bid = g.box_id.astype(np.int32).copy()
    passable = g.walls_only.copy()
    names = {int(b): f"box{int(b)}" for b in np.unique(bid) if b}
    k = np.ones((5, 5), np.uint8)
    for v in sorted(set(np.unique(g.shade_step)) - {0}):
        n, lab, st, _ = cv2.connectedComponentsWithStats((g.shade_step == v).astype(np.uint8), connectivity=4)
        for c in range(1, n):
            if st[c, 4] < RUNG_MIN_PX:
                continue
            m = lab == c
            grown = cv2.dilate(m.astype(np.uint8), k).astype(bool) & (g.labels != 0)
            over = np.unique(bid[grown & (bid > 0) & (bid < 1000)])
            rid = int(over[0]) if len(over) else 1000 + int(v) * 100 + c
            names[rid] = (f"{names[rid]}+rung{int(v)}_{c}" if len(over) else f"rung{int(v)}_{c}")
            bid[grown & (bid == 0)] = rid
            if CLIP == "lotus" and m[MOUND_SEED[1], MOUND_SEED[0]]:
                passable |= grown & g.floor
    return bid, passable, names


def occluders(record: bool = False):
    rows, lit, raw = load_frames()
    g = Geo()
    w = np.load(OUT / "witness.npz")
    js = jumps(w)
    st = frame_states(len(rows), js)
    bid, passable, names = occluder_ids(g)
    known = g.light.known
    obs = []
    for i, r in enumerate(rows):
        if r.get("deg") is None or st[i] == "transition":
            continue
        blocked, beyond = cone.box_crossings(passable, bid, r["x"], r["y"], r["deg"])
        own = int(bid[int(round(r["y"])), int(round(r["x"]))])
        for b, m in beyond.items():
            m = m & known
            nb = int(m.sum())
            if nb < MIN_BEYOND:
                continue
            f = float((lit[i] & m).sum()) / nb
            obs.append({"frame": i, "t": r["t"], "state": st[i], "occluder": names.get(b, str(b)), "id": b,
                        "caster_x": round(r["x"], 1), "caster_y": round(r["y"], 1),
                        "caster_rung": int(g.shade_step[int(round(r["y"])), int(round(r["x"]))]),
                        "caster_on": names.get(own) if own else None,
                        "n_beyond": nb, "lit_frac": round(f, 3),
                        "blocked": None if LIT_LO < f < LIT_HI else bool(f <= LIT_LO)})
    (OUT / "observations.json").write_text(json.dumps({"version": VERSION, "jumps": js, "rows": obs}))
    print(f"{len(js)} camera events: " + ", ".join(
        f"{rows[j['onset']]['t']:.2f}-{rows[j['land']]['t']:.2f}" if j["land"] else f"{rows[j['onset']]['t']:.2f} step-up"
        for j in js))
    print(f"{len(obs)} occluder-frame observations")
    return js, obs


#: Standing frames for a jump: ground frames this close before the onset (or
#: after the landing) whose pose matches the pose at the onset.
STAND_WIN, POSE_PX, POSE_DEG = 25, 1.5, 5.0
#: An occluder is classed on a jump when at least this share of its known
#: beyond pixels agree on one outcome.
CLASS_SHARE = 0.6


def _same_pose(a, b):
    return (a.get("deg") is not None and b.get("deg") is not None
            and np.hypot(a["x"] - b["x"], a["y"] - b["y"]) <= POSE_PX
            and abs((a["deg"] - b["deg"] + 180) % 360 - 180) <= POSE_DEG)


def jump_events():
    """Per camera jump: the standing and in-air light at one pose, split by
    the first occluder each ray crosses (`cone.box_crossings`)."""
    rows, lit, _ = load_frames()
    g = Geo()
    w = np.load(OUT / "witness.npz")
    js = jumps(w)
    st = frame_states(len(rows), js)
    bid, passable, names = occluder_ids(g)
    known = g.light.known
    env = 20 * np.log10(w["env"] + 1e-5)
    out = []
    for j in js:
        if j["kind"] != "jump":
            continue
        a, b = j["onset"], j["land"]
        ref = rows[a - 1]
        stand = [i for i in list(range(max(0, a - STAND_WIN), a - 1)) + list(range(b + 2, min(len(rows), b + STAND_WIN)))
                 if st[i] == "ground" and _same_pose(rows[i], ref)]
        air = [i for i in range(a + 1, b) if _same_pose(rows[i], ref)]
        ev = {"onset_t": rows[a]["t"], "land_t": rows[b]["t"], "rise": j["rise"],
              "caster": [round(ref["x"], 1), round(ref["y"], 1), round(ref["deg"], 1)] if ref.get("deg") is not None else None,
              "caster_rung": int(g.shade_step[int(round(ref["y"])), int(round(ref["x"]))]),
              "n_stand": len(stand), "n_air": len(air),
              "takeoff_db": float(env[int(rows[a]["t"] * 100):int(rows[a]["t"] * 100) + 25].max()),
              "landing_db": float(env[int(rows[b]["t"] * 100) - 10:int(rows[b]["t"] * 100) + 30].max()),
              "occluders": {}}
        if ref.get("deg") is None or len(stand) < 3 or len(air) < 3:
            ev["refused"] = "pose_changed_or_too_few_frames"
            out.append(ev)
            continue
        S = lit[stand].mean(0)
        A = lit[air].mean(0)
        blocked, beyond = cone.box_crossings(passable, bid, ref["x"], ref["y"], ref["deg"])
        flip = (S <= LIT_LO) & (A >= LIT_HI)
        dark = (S <= LIT_LO) & (A <= LIT_LO)
        both = (S >= LIT_HI) & (A >= LIT_HI)
        loss = (S >= LIT_HI) & (A <= LIT_LO)
        regions = {"direct": blocked}
        regions.update({names.get(k, str(k)): m for k, m in beyond.items()})
        for name, m in regions.items():
            m = m & known
            n = int(m.sum())
            if n < MIN_BEYOND:
                continue
            c = {"n": n, "flip": round(float((m & flip).sum()) / n, 3),
                 "dark": round(float((m & dark).sum()) / n, 3),
                 "lit": round(float((m & both).sum()) / n, 3),
                 "loss": round(float((m & loss).sum()) / n, 3)}
            if name != "direct":
                share = {"short": c["flip"], "tall": c["dark"], "no_block": c["lit"]}
                k = max(share, key=share.get)
                c["class"] = k if share[k] >= CLASS_SHARE else "mixed"
                fm = m & flip
                if fm.sum() >= MIN_BEYOND:
                    c["flip_timeline"] = [round(float((lit[i] & fm).sum()) / fm.sum(), 2)
                                          for i in range(a - 2, b + 3)]
            ev["occluders"][name] = c
        hits = ray_hits(ev, S, A, g)
        ev["hits"] = {}
        for k, gr in hits.items():
            px = np.array(gr.pop("hit_px"))
            gr["class"] = classify_group(gr)
            gr["hit_centre"] = [round(float(v), 1) for v in px.mean(0)]
            ev["hits"][k] = gr
        out.append(ev)
    (OUT / "jump_events.json").write_text(json.dumps({"version": VERSION, "events": out}, indent=1))
    return out


def mound_rays(events=None):
    """Where the standing shadow starts along each ray that crosses the mound:
    as a fraction of the ray's path across the mound's rung-1 region (0 at
    entry, 1 at exit), and whether a baked line or a rung edge lies within
    1.5 px of that start."""
    rows, lit, _ = load_frames()
    g = Geo()
    events = events or json.loads((OUT / "jump_events.json").read_text())["events"]
    n, lab = cv2.connectedComponents((g.shade_step == 1).astype(np.uint8), connectivity=4)
    mound = lab == lab[MOUND_SEED[1], MOUND_SEED[0]]
    line = (g.occ > 0)
    edge = cv2.morphologyEx(mound.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)).astype(bool)
    near = lambda m: cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4, 4))).astype(bool)
    near_line, near_edge = near(line), near(edge)
    out = []
    for ev in events:
        if "refused" in ev or "rung1_44" not in ev["occluders"]:
            continue
        cx, cy, deg = ev["caster"]
        a = int(round(ev["onset_t"] * 20)); b = int(round(ev["land_t"] * 20))
        stand = [i for i in range(max(0, a - STAND_WIN), a - 1) if _same_pose(rows[i], rows[a - 1])]
        S, A = lit[stand].mean(0), lit[a + 1:b].mean(0)
        flip = (S <= LIT_LO) & (A >= LIT_HI)
        fr, at_line, at_edge, span = [], 0, 0, []
        for th in np.radians(deg + np.linspace(-cone.CONE_HALF_ANGLE_DEG, cone.CONE_HALF_ANGLE_DEG, 240)):
            d = np.arange(0, 300, 0.5)
            xi = np.rint(cx + d * np.cos(th)).astype(int); yi = np.rint(cy + d * np.sin(th)).astype(int)
            ok = (xi >= 0) & (xi < g.floor.shape[1]) & (yi >= 0) & (yi < g.floor.shape[0])
            d, xi, yi = d[ok], xi[ok], yi[ok]
            inside = mound[yi, xi]
            fl = flip[yi, xi]
            if not inside.any() or not fl.any():
                continue
            d_in, d_out = d[inside][0], d[inside][-1]
            k = int(np.argmax(fl))
            if d[k] < d_in - 1:
                continue
            fr.append(float((d[k] - d_in) / max(1.0, d_out - d_in)))
            span.append(float(d_out - d_in))
            at_line += bool(near_line[yi[k], xi[k]])
            at_edge += bool(near_edge[yi[k], xi[k]])
        if fr:
            out.append({"onset_t": ev["onset_t"], "caster": ev["caster"], "rays": len(fr),
                        "start_frac_median": round(float(np.median(fr)), 3),
                        "start_frac_iqr": [round(float(np.percentile(fr, 25)), 3), round(float(np.percentile(fr, 75)), 3)],
                        "start_at_line_share": round(at_line / len(fr), 3),
                        "start_at_rung_edge_share": round(at_edge / len(fr), 3),
                        "mound_span_median_px": round(float(np.median(span)), 1)})
    return out


#: Rays per cone for the first-hit table, and the samples a ray's immediate
#: beyond segment needs before it is classed.
RAY_N, RAY_MIN_SAMPLES, SKIP_PX, WALL_CELL = 240, 6, 3.0, 8


def mound_mask(g: Geo, grow: int = 2) -> np.ndarray:
    if CLIP != "lotus":
        return np.zeros(g.floor.shape, bool)
    _, lab = cv2.connectedComponents((g.shade_step == 1).astype(np.uint8), connectivity=4)
    m = lab == lab[MOUND_SEED[1], MOUND_SEED[0]]
    return cv2.dilate(m.astype(np.uint8), np.ones((2 * grow + 1,) * 2, np.uint8)).astype(bool)


def ray_hits(ev, S, A, g: Geo, mound=None):
    """Every occluder a cone meets, from the drawn light, with nothing closed
    but the void: each ray's FIRST drawn occluder pixel (a baked wall or box
    pixel, or the mound region), and the light on the immediate stretch
    beyond it, up to the next occluder pixel. A ray whose stretch is dark
    standing and lit in the air passed that occluder only when jumping.
    Rays are grouped by what they hit: `box<id>`, `mound`, or a wall cell
    `wall@x,y` (WALL_CELL px)."""
    mound = mound_mask(g) if mound is None else mound
    cx, cy, deg = ev["caster"]
    h, w = g.floor.shape
    occ, known = g.occ, g.light.known
    solid = g.labels != 0
    flip = (S <= LIT_LO) & (A >= LIT_HI)
    dark = (S <= LIT_LO) & (A <= LIT_LO)
    both = (S >= LIT_HI) & (A >= LIT_HI)
    groups = {}
    for th in np.radians(deg + np.linspace(-cone.CONE_HALF_ANGLE_DEG, cone.CONE_HALF_ANGLE_DEG, RAY_N)):
        d = np.arange(0, 320, 0.5)
        xi = np.rint(cx + d * np.cos(th)).astype(int); yi = np.rint(cy + d * np.sin(th)).astype(int)
        ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        d, xi, yi = d[ok], xi[ok], yi[ok]
        inside = np.logical_and.accumulate(solid[yi, xi])
        d, xi, yi = d[inside], xi[inside], yi[inside]
        hit = ((occ[yi, xi] > 0) | mound[yi, xi]) & (d > SKIP_PX)
        if not hit.any():
            continue
        k = int(np.argmax(hit))
        hx, hy = xi[k], yi[k]
        if mound[hy, hx]:
            key, obj = "mound", mound
        elif occ[hy, hx] == 2:
            key = f"box{int(g.box_id[hy, hx])}"
            obj = g.box_id == g.box_id[hy, hx]
        else:
            key = f"wall@{hx // WALL_CELL * WALL_CELL},{hy // WALL_CELL * WALL_CELL}"
            obj = occ == 1
        # The stretch beyond: after leaving the object, up to the next occluder pixel.
        on = obj[yi[k:], xi[k:]]
        leave = k + (int(np.argmin(on)) if not on.all() else len(on))
        rest = hit[leave:]
        stop = leave + (int(np.argmax(rest)) if rest.any() else len(rest))
        if key == "mound":
            leave = k              # the mound is a slope: its own surface is part of the stretch
        sx, sy = xi[leave:stop], yi[leave:stop]
        kn = known[sy, sx]
        if kn.sum() < RAY_MIN_SAMPLES:
            continue
        f, dk, lt = flip[sy, sx][kn].mean(), dark[sy, sx][kn].mean(), both[sy, sx][kn].mean()
        cls = ("passes_jumping" if f >= CLASS_SHARE else "blocks_both" if dk >= CLASS_SHARE
               else "passes_standing" if lt >= CLASS_SHARE else "mixed")
        gr = groups.setdefault(key, {"rays": 0, "passes_jumping": 0, "blocks_both": 0,
                                     "passes_standing": 0, "mixed": 0, "hit_px": []})
        gr["rays"] += 1
        gr[cls] += 1
        gr["hit_px"].append([int(hx), int(hy)])
    return groups


def classify_group(gr):
    """short: blocks standing, passes jumping; tall: blocks both; none: passes
    standing. Needs 5 rays and 70% of them on one side."""
    blk = gr["passes_jumping"] + gr["blocks_both"]
    if gr["rays"] < 5:
        return "unconstrained"
    if gr["passes_standing"] >= 0.7 * gr["rays"]:
        return "does_not_block"
    if blk >= 0.7 * gr["rays"]:
        if gr["passes_jumping"] >= 0.7 * blk:
            return "short"
        if gr["blocks_both"] >= 0.7 * blk:
            return "tall"
    return "mixed"


SHEET_Z = 3          # native pixels, enlarged by nearest-neighbour only
SHEET_HALF = 80      # baked px either side of the caster


def _outline(img, mask, col, z):
    m = cv2.resize(mask.astype(np.uint8), None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    cnts, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, col, 1)


def _crop_zoom(base, win, z):
    x0, y0, x1, y1 = win
    return cv2.resize(base[y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST).copy()


def sheets(events=None, stem=None):
    """One native-pixel sheet per jump: standing and in-air frames, the
    baked walls/boxes/rungs, the cone's edge rays, each crossed occluder's
    beyond region and the drawn light; and the flip map."""
    rows, lit, _ = load_frames()
    ts, mm = crops()
    g = Geo()
    bid, passable, names = occluder_ids(g)
    events = events or json.loads((OUT / "jump_events.json").read_text())["events"]
    stem = stem or CLIP
    fstate = frame_states(len(rows), jumps(np.load(OUT / "witness.npz")))
    paths = []
    z = SHEET_Z
    for ev in events:
        if "refused" in ev or ev["caster"] is None:
            continue
        cx, cy, deg = ev["caster"]
        h, w = g.floor.shape
        a = int(round(ev["onset_t"] * 20)); b = int(round(ev["land_t"] * 20))
        fs, fa = a - 3, (a + b) // 2
        stand_idx = [i for i in range(max(0, a - STAND_WIN), a - 1)
                     if fstate[i] == "ground" and _same_pose(rows[i], rows[a - 1])]
        q = max(1, (b - a) // 4)
        air_idx = list(range(a + q, b - q + 1))
        S, A = lit[stand_idx].mean(0), lit[air_idx].mean(0)
        # Centre the window between the caster and what the jump changed (or
        # 40 px ahead of the caster when nothing flipped), so the occluder is in view.
        fy_, fx_ = np.nonzero((S <= LIT_LO) & (A >= LIT_HI) & g.light.known)
        if len(fx_) >= MIN_BEYOND:
            mx, my = (cx + np.median(fx_)) / 2, (cy + np.median(fy_)) / 2
        else:
            mx, my = cx + 40 * np.cos(np.radians(deg)), cy + 40 * np.sin(np.radians(deg))
        x0 = int(np.clip(mx - SHEET_HALF, 0, w - 2 * SHEET_HALF)); y0 = int(np.clip(my - SHEET_HALF, 0, h - 2 * SHEET_HALF))
        win = (x0, y0, x0 + 2 * SHEET_HALF, y0 + 2 * SHEET_HALF)
        _, beyond = cone.box_crossings(passable, bid, cx, cy, deg)
        tiles = []
        for fi, lab in ((fs, "standing"), (fa, "in air")):
            raw_p = _crop_zoom(mm[fi], win, z)
            cv2.putText(raw_p, f"{lab} {rows[fi]['t']:.2f}s", (4, 14), 0, 0.45, (0, 255, 255), 1)
            ov = _crop_zoom(mm[fi], win, z)
            litp = _crop_zoom(lit[fi].astype(np.uint8), win, z) > 0
            ov[litp] = (0.55 * ov[litp] + 0.45 * np.array([0, 200, 0])).astype(np.uint8)
            sub = lambda m: m[win[1]:win[3], win[0]:win[2]]
            _outline(ov, sub(g.occ == 1), (0, 0, 255), z)
            _outline(ov, sub((g.occ == 2)), (255, 128, 0), z)
            _outline(ov, sub(g.shade_step > 0), (0, 255, 255), z)
            for k, m in beyond.items():
                if (m & g.light.known).sum() >= MIN_BEYOND:
                    _outline(ov, sub(m), (255, 0, 255), z)
            for s in (-1, 1):
                th = np.radians(deg + s * cone.CONE_HALF_ANGLE_DEG)
                p0 = (int((cx - win[0]) * z), int((cy - win[1]) * z))
                p1 = (int((cx - win[0] + 400 * np.cos(th)) * z), int((cy - win[1] + 400 * np.sin(th)) * z))
                cv2.line(ov, p0, p1, (255, 255, 0), 1)
            cv2.putText(ov, "light green, wall red, box blue, rung yellow", (4, 14), 0, 0.4, (255, 255, 255), 1)
            cv2.putText(ov, "beyond-occluder magenta, cone edges cyan", (4, 28), 0, 0.4, (255, 255, 255), 1)
            tiles.append(np.hstack([raw_p, ov]))
        fl = cv2.cvtColor(cv2.cvtColor(_crop_zoom(g.static, win, z), cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) // 2
        fp = lambda m: _crop_zoom(m.astype(np.uint8), win, z) > 0
        cast = cone.raycast(passable, cx, cy, deg) & g.light.known
        fl[fp((S <= LIT_LO) & (A >= LIT_HI) & g.light.known)] = (0, 255, 0)
        fl[fp((S <= LIT_LO) & (A <= LIT_LO) & cast)] = (0, 0, 200)
        fl[fp((S >= LIT_HI) & (A >= LIT_HI) & g.light.known)] = (170, 170, 170)
        fl[fp((S >= LIT_HI) & (A <= LIT_LO) & g.light.known)] = (255, 0, 255)
        cv2.putText(fl, "in the open cone: flip (dark standing, lit jumping) green; dark both red; lit both grey", (4, 14), 0, 0.4, (255, 255, 255), 1)
        y = 30
        for k, c in ev["occluders"].items():
            if k == "direct":
                continue
            cv2.putText(fl, f"{k}: {c.get('class')} flip {c['flip']:.2f} dark {c['dark']:.2f} lit {c['lit']:.2f} n {c['n']}",
                        (4, y), 0, 0.38, (0, 255, 255), 1)
            y += 14
        for k, c in sorted(ev.get("hits", {}).items(), key=lambda kv: -kv[1]["rays"]):
            if c["rays"] >= 5:
                cv2.putText(fl, f"first hit {k}: {c['class']} (rays {c['rays']}: jump-only {c['passes_jumping']}, "
                            f"both dark {c['blocks_both']}, both lit {c['passes_standing']})", (4, y), 0, 0.33, (0, 255, 255), 1)
                y += 13
        info = np.zeros_like(fl)
        for li, line in enumerate([f"jump {ev['onset_t']:.2f}-{ev['land_t']:.2f}s (camera witness)",
                                   f"caster ({cx:.1f}, {cy:.1f}) facing {deg:.1f} deg, rung {ev['caster_rung']}",
                                   f"standing frames {ev['n_stand']}, in-air frames {ev['n_air']}",
                                   f"takeoff {ev['takeoff_db']:.0f} dB, landing {ev['landing_db']:.0f} dB",
                                   f"geometry {KEY} (baked); {VERSION}",
                                   f"source {Path(VID).name} (not ingested)"]):
            cv2.putText(info, line, (6, 20 + 18 * li), 0, 0.45, (255, 255, 255), 1)
        tiles.append(np.hstack([fl, info]))
        sheet = np.vstack(tiles)
        p = OUT / f"sheet_{stem}_{ev['onset_t']:.2f}.png"
        cv2.imwrite(str(p), sheet)
        paths.append(p)
    return paths


#: The occluders the clip tests, located by hand from the sheets and the baked
#: arrays (bbox x0, y0, x1, y1 in baked px). `hits` names the first-hit ray
#: groups (`ray_hits`) that witness each one; the mound is read by
#: `mound_rays`, and the spawn box by the flip pixels inside `near`, because
#: its beyond stretch is 3 rays wide at that range.
OCCLUDERS = [
    {"id": "c-mound", "where": "C Mound", "bbox": [111, 297, 150, 330],
     "baked": "shade rung 1 region; dotted outline baked as WALL; no line at the crest",
     "witness": "mound", "jumps": [18.4, 22.0, 25.0, 28.7]},
    {"id": "spawn-mid-box", "where": "Attacker Side Spawn, the box mid-room", "bbox": [241, 355, 251, 363],
     "baked": "BOX (box_id 8) with a rung-1 top; outline partly WALL",
     "witness": "flip", "near": [233, 340, 262, 372], "jumps": [43.45, 45.65, 47.65, 49.45, 51.25]},
    {"id": "c-lobby-corner-box", "where": "C Lobby, the box at the wall end by the door", "bbox": [142, 348, 151, 357],
     "baked": "BOX (box_id 60) with a rung-1 top; outline WALL",
     "witness": "hits", "hits": ["wall@136,344", "wall@136,352", "box60"], "jumps": [32.4]},
    {"id": "c-lobby-rect-box", "where": "C Lobby, the box at the raised rectangle's lower left", "bbox": [178, 373, 184, 392],
     "baked": "BOX on right and bottom (box_id 63-65), WALL on the left edge",
     "witness": "hits", "hits": ["wall@176,376", "wall@176,384", "box64", "box65"], "jumps": [34.95, 37.35]},
    {"id": "c-lobby-rect-edge", "where": "C Lobby, the raised rectangle's left edge line", "bbox": [176, 352, 178, 372],
     "baked": "WALL line; the rectangle is shade rung 1 (a step-up platform)",
     "witness": "hits", "hits": ["wall@176,352", "wall@176,360", "wall@176,368"], "jumps": [34.95, 37.35]},
]


#: Split, the clip at the same settings. Caster floors are named by where the
#: caster stood: `b-raised` is the B plant zone east of its west-edge notch
#: (x 53-60, y 169-188), `b-below-stairs` the floor west of it; the player
#: named both, and the camera rose 8.6 small-view px (a step-up, 42.05 s) as
#: the self icon crossed the notch.
SPLIT_OCCLUDERS = [
    {"id": "b-far-left-box", "where": "B Site, the box/platform at the far left, by B Back", "bbox": [17, 175, 37, 185],
     "baked": "BOX (box_id 17) with a rung-1 top; outline partly WALL",
     "witness": "flip", "near": [17, 175, 37, 185],
     "jumps": [[32.0, "b-raised"], [33.3, "b-raised"], [34.65, "b-raised"], [35.95, "b-raised"],
               [37.2, "b-raised"], [43.4, "b-raised"], [41.3, "b-below-stairs"], [47.85, "b-below-stairs"]]},
    {"id": "b-lower-box", "where": "B Site, the small box at the corridor's upper edge, seen from the lower floor",
     "bbox": [79, 204, 88, 214], "baked": "BOX (box_id 2) with a rung-1 top; outline partly WALL",
     "witness": "hits", "hits": ["box2"], "jumps": [[58.75, "b-lower-left"]]},
    {"id": "b-corridor-east-line", "where": "B Site, the white line at the corridor's east end", "bbox": [120, 216, 121, 231],
     "baked": "WALL line; no shade", "witness": "hits", "hits": ["wall@120,216", "wall@120,224"],
     "jumps": [[58.75, "b-lower-left"]]},
]
OCCLUDERS_BY_CLIP = {"lotus": OCCLUDERS, "split": SPLIT_OCCLUDERS}
#: The caster floors each table names, and how each was located.
FLOORS = {
    "lotus": {"rung0": "unshaded floor (shade rung 0) at the caster; every Lotus jump was from it"},
    "split": {
        "b-raised": "B plant zone east of the notch in its west edge (x 53-60, y 169-188); located by the player, "
                    "bounded by the notch and the step-up the camera shows at 42.05 s; no shade marks it",
        "b-below-stairs": "floor west of the notch, x 49-52 at y 177-179; the player's 'below the stairs'",
        "b-lower-left": "unshaded floor at (34, 216), south-west of the plant zone"},
}
#: A flip witness decides on at least this many known pixels in its window.
FLIP_MIN_PX = 20


def summarize(record: bool = False):
    """The per-occluder class table and one inequality row per (jump, occluder,
    state): eye = floor + state offset, and an occluder blocks iff eye < top."""
    rows, lit, _ = load_frames()
    g = Geo()
    evs = {round(e["onset_t"], 2): e for e in json.loads((OUT / "jump_events.json").read_text())["events"]}
    mr = {round(m["onset_t"], 2): m for m in mound_rays(list(evs.values()))}
    fstate = frame_states(len(rows), jumps(np.load(OUT / "witness.npz")))
    table, ineq = [], []
    for oc in OCCLUDERS_BY_CLIP[CLIP]:
        per = []
        for t in oc["jumps"]:
            t, floor = (t, "rung0") if isinstance(t, (int, float)) else t
            ev = evs[round(t, 2)]
            a = int(round(ev["onset_t"] * 20)); b = int(round(ev["land_t"] * 20))
            rec = {"t": ev["onset_t"], "land_t": ev["land_t"], "caster": ev["caster"], "caster_floor": floor}
            if oc["witness"] == "mound":
                m = mr[round(t, 2)]
                rec.update(stand_blocked=True, jump_blocked=False, rays=m["rays"],
                           crest_frac=m["start_frac_median"], start_at_line=m["start_at_line_share"],
                           start_at_rung_edge=m["start_at_rung_edge_share"])
            elif oc["witness"] == "flip":
                st = [i for i in range(max(0, a - STAND_WIN), a - 1)
                      if fstate[i] == "ground" and _same_pose(rows[i], rows[a - 1])]
                # The middle half of the air: the light switches when the eye
                # crosses the top, which may be frames after takeoff.
                q = max(1, (b - a) // 4)
                S, A = lit[st].mean(0), lit[a + q:b - q + 1].mean(0)
                x0, y0, x1, y1 = oc["near"]
                win = np.zeros_like(g.light.known); win[y0:y1 + 1, x0:x1 + 1] = True
                kn = g.light.known & win
                fm = (S <= LIT_LO) & (A >= LIT_HI) & kn
                fl = int(fm.sum())
                if fl:
                    tl = [float((lit[i] & fm).sum()) / fl for i in range(a, b + 1)]
                    rec["lit_air_share"] = round(sum(v >= LIT_HI for v in tl) / (b - a), 3)
                    rec["lit_from_frame"] = next(k for k, v in enumerate(tl) if v >= LIT_HI)
                    rec["dark_before_landing_frames"] = next(k for k, v in enumerate(tl[::-1]) if v >= LIT_HI)
                dk = int(((S <= LIT_LO) & (A <= LIT_LO) & kn).sum())
                ls = int(((S >= LIT_HI) & (A <= LIT_LO) & kn).sum())
                sb, jb = ((True, False) if fl >= FLIP_MIN_PX else (True, True) if dk >= FLIP_MIN_PX
                          else (None, None))
                rec.update(stand_blocked=sb, jump_blocked=jb, flip_px=fl, dark_both_px=dk, loss_px=ls)
            else:
                grs = [ev["hits"][k] for k in oc["hits"] if k in ev["hits"]]
                c = {k: sum(gr[k] for gr in grs) for k in ("rays", "passes_jumping", "blocks_both", "passes_standing", "mixed")}
                cls = classify_group(c)
                rec.update(c, ray_class=cls,
                           stand_blocked=None if cls in ("mixed", "unconstrained") else cls != "does_not_block",
                           jump_blocked=None if cls in ("mixed", "unconstrained") else cls == "tall")
            per.append(rec)
            for state in ("standing", "jumping"):
                blk = rec["stand_blocked" if state == "standing" else "jump_blocked"]
                ineq.append({"map": CLIP, "geometry": KEY, "occluder": oc["id"], "caster_floor": floor,
                             "state": state, "blocked": blk,
                             "t": ev["onset_t"] if state == "jumping" else round(ev["onset_t"] - 0.15, 2),
                             "caster": ev["caster"], "source": SESSION, "version": VERSION})
        classes = {}
        for floor in dict.fromkeys(r["caster_floor"] for r in per):
            sub = [r for r in per if r["caster_floor"] == floor]
            sb = {r["stand_blocked"] for r in sub}; jb = {r["jump_blocked"] for r in sub}
            classes[floor] = ("short" if sb == {True} and jb == {False} else "tall" if sb == {True} and jb == {True}
                              else "does_not_block" if sb == {False} else "mixed")
        cls = next(iter(classes.values())) if len(set(classes.values())) == 1 else "by_floor"
        table.append({**{k: oc[k] for k in ("id", "where", "bbox", "baked")}, "class": cls,
                      "class_by_floor": classes, "jumps": per})
    out = {"version": VERSION, "geometry": KEY, "source": SESSION, "capture": VID,
           "n_boxes_baked": int(len(np.unique(g.box_id)) - 1), "occluders": table, "inequalities": ineq}
    (OUT / "heights.json").write_text(json.dumps(out, indent=1))
    with (OUT / "inequalities.jsonl").open("w", encoding="utf-8") as fh:
        for r in ineq:
            fh.write(json.dumps(r) + chr(10))
    if record:
        record_run(out, evs, mr)
    return out


def clipped_corner(record: bool = False):
    """Where the widget cuts the map: the drawn ring (the widget boundary,
    [domain:minimap/widget-ring]) fitted in the baked static over its left
    half, the baked map pixels outside it, and the blue edge marker that
    stands in for the self icon in frames with no self pose."""
    rows, _, _ = load_frames()
    ts, mm = crops()
    g = Geo()
    sg = cv2.GaussianBlur(g.sgray.astype(np.float32), (0, 0), 0.8)
    h, w = sg.shape
    ang = np.linspace(np.pi * 0.55, np.pi * 1.45, 400)

    def score(cx, cy, r):
        def samp(rr):
            return cv2.remap(sg, (cx + rr * np.cos(ang)).astype(np.float32)[None],
                             (cy + rr * np.sin(ang)).astype(np.float32)[None], cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)[0]
        with np.errstate(all="ignore"):
            return float(np.nanmedian(samp(r) - 0.5 * (samp(r - 2.5) + samp(r + 2.5))))

    best = max((score(x, y, r), x, y, r) for x in np.arange(215, 252, 1.0)
               for y in np.arange(235, 280, 1.0) for r in np.arange(200, 245, 1.0))
    _, cx, cy, r = best
    best = max((score(x, y, rr), x, y, rr) for x in np.arange(cx - 1, cx + 1.01, 0.25)
               for y in np.arange(cy - 1, cy + 1.01, 0.25) for rr in np.arange(r - 1, r + 1.01, 0.25))
    s, cx, cy, r = best
    tri = []
    for i, row in enumerate(rows):
        if row.get("deg") is not None:
            continue
        im = mm[i].astype(int)
        m = (im[..., 0] > 170) & (im[..., 2] < 90) & (im[..., 0] - im[..., 1] > 60)
        n, lab, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8))
        if n > 1:
            k = 1 + int(np.argmax(st[1:, 4]))
            if st[k, 4] >= 15:
                x, y = cen[k]
                tri.append({"t": row["t"], "x": round(float(x), 1), "y": round(float(y), 1), "px": int(st[k, 4]),
                            "d_ring": round(float(np.hypot(x - cx, y - cy) - r), 2)})
    yy, xx = np.mgrid[:h, :w]
    outside = (g.labels != 0) & (np.hypot(xx - cx, yy - cy) > r)
    n, lab, st, cen = cv2.connectedComponentsWithStats(outside.astype(np.uint8))
    regions = [{"bbox": [int(st[k, 0]), int(st[k, 1]), int(st[k, 0] + st[k, 2] - 1), int(st[k, 1] + st[k, 3] - 1)],
                "px": int(st[k, 4])} for k in range(1, n) if st[k, 4] >= 20]
    absent = [r_["t"] for r_ in rows if r_.get("deg") is None]
    out = {"ring": {"cx": float(cx), "cy": float(cy), "r": float(r), "score": s}, "triangles": tri,
           "outside_regions": regions, "n_absent": len(absent)}
    (OUT / "clipped_corner.json").write_text(json.dumps(out, indent=1))
    np.save(OUT / "outside_ring_mask.npy", outside)
    if record:
        from reticle import metrics
        v = {"ring_cx": round(float(cx), 2), "ring_cy": round(float(cy), 2), "ring_r": round(float(r), 2),
             "outside_px": int(outside.sum()), "n_regions": len(regions), "n_marker": len(tri), "n_absent": len(absent)}
        for k, q in enumerate(sorted(regions, key=lambda q: -q["px"])):
            v.update({f"region{k}_px": q["px"], f"region{k}_x0": q["bbox"][0], f"region{k}_y0": q["bbox"][1],
                      f"region{k}_x1": q["bbox"][2], f"region{k}_y1": q["bbox"][3]})
        metrics.record(Path(__file__).stem, part="ring", session=SESSION, values=v,
                       deps={"version": VERSION, "geometry": KEY}, context={"capture": VID},
                       note="widget ring fitted in the baked static; baked map pixels outside it")
    return out


def b_zone_notch():
    """Split's B plant zone (the olive fill of the baked static, x < 200) and
    the notch in its west edge: the rows whose westmost zone pixel lies east of
    the zone's westmost column. Also the zone's shade rungs."""
    g = Geo()
    s = g.static.astype(int)
    ol = (s[..., 2] - s[..., 0] > 20) & (s[..., 1] - s[..., 0] > 20)
    ol[:, 200:] = False
    n, lab, st, _ = cv2.connectedComponentsWithStats(ol.astype(np.uint8))
    z = lab == 1 + int(np.argmax(st[1:, 4]))
    x_min = int(np.nonzero(z.any(0))[0].min())
    rows_ = [y for y in range(z.shape[0]) if z[y].any()]
    west = {y: int(np.nonzero(z[y])[0].min()) for y in rows_}
    notch = [y for y in rows_ if x_min < west[y] <= x_min + 12]
    return {"zone_px": int(z.sum()), "zone_rung0_share": round(float((g.shade_step[z] == 0).mean()), 3),
            "notch_x0": x_min, "notch_x1": max(west[y] for y in notch) - 1,
            "notch_y0": min(notch), "notch_y1": max(notch)}


def record_run(out, evs, mr):
    from reticle import metrics
    if CLIP == "split":
        cc = json.loads((OUT / "clipped_corner.json").read_text())
        occ = {o["id"]: o for o in out["occluders"]}
        box = occ["b-far-left-box"]["jumps"]
        d = [q["d_ring"] for q in cc["triangles"]]
        big = max(cc["outside_regions"], key=lambda q: q["px"])
        v = {"ring_cx": round(cc["ring"]["cx"], 2), "ring_cy": round(cc["ring"]["cy"], 2), "ring_r": round(cc["ring"]["r"], 2),
             "n_absent": cc["n_absent"], "n_marker": len(d),
             "marker_t_first": cc["triangles"][0]["t"], "marker_t_last": cc["triangles"][-1]["t"],
             "marker_minus_ring_min": min(d), "marker_minus_ring_max": max(d),
             "cut_b_px": big["px"], "cut_b_x0": big["bbox"][0], "cut_b_y0": big["bbox"][1],
             "cut_b_x1": big["bbox"][2], "cut_b_y1": big["bbox"][3],
             "cut_total_px": sum(q["px"] for q in cc["outside_regions"]),
             "box_flip_px_raised_min": min(r["flip_px"] for r in box if r["caster_floor"] == "b-raised"),
             "box_flip_px_below_max": max(r["flip_px"] for r in box if r["caster_floor"] == "b-below-stairs"),
             "box_lit_air_share_min": min(r["lit_air_share"] for r in box if r["caster_floor"] == "b-raised"),
             "box_lit_air_share_max": max(r["lit_air_share"] for r in box if r["caster_floor"] == "b-raised"),
             **b_zone_notch(),
             "n_jumps": len([e for e in evs.values() if "refused" not in e])}
        for k, o in occ.items():
            for f, c in o["class_by_floor"].items():
                v[f"class_{k}@{f}"] = c
        metrics.record(Path(__file__).stem, part="split", session=SESSION, values=v,
                       deps={"version": VERSION, "geometry": KEY},
                       context={"capture": VID, "rate_hz": 20}, note="Split at the largest settings; not ingested")
        return
    js = [e for e in evs.values() if "refused" not in e]
    m = list(mr.values())
    occ = {o["id"]: o for o in out["occluders"]}
    v = {"n_jumps": len(js),
         "takeoff_db_max": round(max(e["takeoff_db"] for e in js), 1),
         "takeoff_db_min": round(min(e["takeoff_db"] for e in js), 1),
         "landing_db_max": round(max(e["landing_db"] for e in js), 1),
         "landing_db_min": round(min(e["landing_db"] for e in js), 1),
         "mound_crest_frac_min": min(x["start_frac_median"] for x in m),
         "mound_crest_frac_max": max(x["start_frac_median"] for x in m),
         "mound_start_at_line_max": max(x["start_at_line_share"] for x in m),
         "mound_start_at_edge_max": max(x["start_at_rung_edge_share"] for x in m),
         "spawn_box_flip_px_min": min(r["flip_px"] for r in occ["spawn-mid-box"]["jumps"]),
         "spawn_box_flip_px_max": max(r["flip_px"] for r in occ["spawn-mid-box"]["jumps"]),
         "n_constrained": len(out["occluders"]), "n_boxes_baked": out["n_boxes_baked"]}
    for e in js:
        v[f"flip_timeline_{e['onset_t']:.2f}"] = next((c["flip_timeline"] for c in e["occluders"].values()
                                                       if "flip_timeline" in c), None)
    for k, o in occ.items():
        v[f"class_{k}"] = o["class"]
    metrics.record("lotus_elevation", part="heights", session=SESSION, values=v,
                   deps={"version": VERSION, "geometry": KEY},
                   context={"capture": VID, "rate_hz": 20, "witness": "camera vertical motion (phase correlation)"},
                   note="standing vs jumping self light per occluder; capture not ingested, session is the file stem")


HEIGHTS_DIR = Path(__file__).resolve().parents[1] / "domain" / "heights"


def _tv(v):
    """One TOML value (str, bool, int, float, list); None has no TOML form and
    is written as the string "unread"."""
    if v is None:
        return '"unread"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(round(v, 3) if isinstance(v, float) else v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_tv(x) for x in v) + "]"
    return json.dumps(str(v))


def write_table(heights=None, path=None):
    """Write the per-occluder height classes and the inequality rows as a data
    table beside the facts: `domain/heights/<geometry>.toml`. Regenerated from
    `heights.json`; later clips append rows from their own runs."""
    h = heights or json.loads((OUT / "heights.json").read_text())
    path = Path(path) if path else HEIGHTS_DIR / f"{h['geometry']}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    L = [f"# Occluder heights on {h['geometry']}: DATA, not facts (domain/*.toml globs no subdirectory).",
         "# Model: caster eye height = floor elevation + a state offset (standing < jumping < boosted);",
         "# an occluder blocks a ray iff the eye is below the occluder's top. Each [[inequality]] is one",
         "# observed block or pass; each [[occluder]] carries the class the rows imply per caster floor:",
         "# short = blocks standing, passes jumping; tall = blocks both; does_not_block = passes standing.",
         "# bbox is x0, y0, x1, y1 in baked px. Written by prototypes/lotus_elevation.py write_table;",
         f"# version {h['version']}; source {h['source']} ({h['capture']}, not ingested).",
         f"# {h['n_boxes_baked']} baked boxes; every box not listed is unconstrained.", ""]
    for k, v in FLOORS.get(CLIP, {}).items():
        L += ["[[floor]]", f"id = {_tv(k)}", f"located = {_tv(v)}", ""]
    for o in h["occluders"]:
        L += ["[[occluder]]", f"id = {_tv(o['id'])}", f"where = {_tv(o['where'])}", f"bbox = {_tv(o['bbox'])}",
              f"baked = {_tv(o['baked'])}", f"class = {_tv(o['class'])}",
              "class_by_floor = {" + ", ".join(f"{_tv(k)} = {_tv(v)}" for k, v in o["class_by_floor"].items()) + "}",
              f"jumps = {_tv([r['t'] for r in o['jumps']])}", f"source = {_tv(h['source'])}",
              f"version = {_tv(h['version'])}", ""]
    for r in h["inequalities"]:
        L += ["[[inequality]]"] + [f"{k} = {_tv(r[k])}" for k in
                                   ("occluder", "caster_floor", "state", "blocked", "t", "caster", "source", "version")] + [""]
    path.write_text("\n".join(L), encoding="utf-8", newline="\n")
    return path


def placement(record: bool = False, step: int = 50):
    """The widget's placement from stored crops against the baked static
    (`widget_frame.fit_crop`), and the baked map's margin to the widget edge:
    a map drawn whole leaves a margin on every side."""
    from reticle import widget_frame
    ts, mm = crops()
    g = Geo()
    fits = [widget_frame.fit_crop(g.static, mm[i], (15, 15)) for i in range(0, len(ts), step)]
    ok = [f for f in fits if f is not None]
    corner = np.median([np.asarray(f["affine"])[:, 2] for f in ok], axis=0)
    ys, xs = np.nonzero(g.labels != 0)
    h, w = g.labels.shape
    v = {"n_fit": len(ok), "n_tried": len(fits),
         "ncc_median": round(float(np.median([f["ncc"] for f in ok])), 3),
         "scale_median": round(float(np.median([f["scale"] for f in ok])), 3),
         "rotation": int(np.median([f["rotation"] for f in ok])),
         "corner_x": round(float(corner[0]), 1), "corner_y": round(float(corner[1]), 1),
         "widget_w": int(w), "widget_h": int(h),
         "map_margin_min_px": int(min(xs.min(), ys.min(), w - 1 - xs.max(), h - 1 - ys.max()))}
    print(v)
    if record:
        from reticle import metrics
        metrics.record(Path(__file__).stem, part="placement", session=SESSION, values=v,
                       deps={"version": VERSION, "geometry": KEY,
                             "widget_frame": widget_frame.WIDGET_FRAME_VERSION},
                       context={"capture": VID, "crops": f"every {step}th stored 20 Hz crop"},
                       note="new largest minimap settings; capture not ingested, session is the file stem")
    return v


def marker_direction(record: bool = False):
    """Which way the off-widget self marker points: the bearing to the self,
    or the self's facing (the player's two readings, 2026-09-30 (chat)).

    The triangle is near equilateral, so its rotation is read mod 120 degrees
    from the third complex moment of its mask, and the vertex nearest map-up
    is reported (`apex_up`, image degrees, 270 = up). The rows' width from top
    to bottom says which vertex is the apex. The facing witness in a gap is
    the last teardrop facing plus the camera's integrated horizontal motion,
    scaled by a fit of teardrop turns against camera motion on posed frames;
    its 1 s error on posed stretches is reported beside it. The bearing
    witness is the ring radial through the marker (the nearest ring point to
    an off-widget self)."""
    rows, _, _ = load_frames()
    ts, mm = crops()
    cc = json.loads((OUT / "clipped_corner.json").read_text())
    cx, cy = cc["ring"]["cx"], cc["ring"]["cy"]
    w = np.load(OUT / "witness.npz")
    # A frame whose phase correlation found no peak (response under 0.1; one
    # frame at 54.80 s reads 716 px at response 0) carries no motion reading;
    # it counts as no turn and is reported, never integrated.
    bad = w["cam_resp"] < 0.1
    dx = np.where(bad, 0.0, w["cam_dx"])
    wrap = lambda a: (a + 180) % 360 - 180
    pairs = [(wrap(b["deg"] - a["deg"]), dx[i]) for i, (a, b) in enumerate(zip(rows[:-1], rows[1:]), 1)
             if a.get("deg") is not None and b.get("deg") is not None and abs(wrap(b["deg"] - a["deg"])) < 30]
    pd, pc = np.array(pairs).T
    k = float((pd * pc).sum() / (pc * pc).sum())
    chk = []
    for a in range(0, len(rows) - 20, 20):
        seg = rows[a:a + 21]
        if all(r.get("deg") is not None for r in seg):
            chk.append((wrap(seg[-1]["deg"] - seg[0]["deg"]), float(dx[a + 1:a + 21].sum() * k)))
    chk = np.array(chk)
    gaps, cur = [], []
    for i, r in enumerate(rows):
        if r.get("deg") is None:
            cur.append(i)
        elif cur:
            gaps.append(cur); cur = []
    out = []
    for g in [g for g in gaps + [cur] if len(g) >= 5 and rows[g[0] - 1].get("deg") is not None]:
        fac, recs, cum = rows[g[0] - 1]["deg"], [], 0.0
        for i in g:
            cum += dx[i] * k
            im = mm[i].astype(int)
            m = (im[..., 0] > 170) & (im[..., 2] < 90) & (im[..., 0] - im[..., 1] > 60)
            n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
            if n < 2 or st[1 + int(np.argmax(st[1:, 4])), 4] < 15:
                continue
            b = lab == 1 + int(np.argmax(st[1:, 4]))
            ys, xs = np.nonzero(b)
            z = (xs - xs.mean()) + 1j * (ys - ys.mean())
            m3 = (np.angle((z ** 3).sum(), deg=True) / 3) % 120
            wid = b[np.nonzero(b.any(1))[0]].sum(1)
            recs.append({"t": rows[i]["t"], "apex_up": 240 + m3, "top_w": float(wid[:3].mean()),
                         "bottom_w": float(wid[-3:].mean()),
                         "radial": float(np.degrees(np.arctan2(ys.mean() - cy, xs.mean() - cx)) % 360),
                         "facing": fac + cum})
        ap_ = np.array([q["apex_up"] for q in recs])
        fp = np.array([q["facing"] for q in recs])
        out.append({"t0": rows[g[0]]["t"], "t1": rows[g[-1]]["t"], "n": len(recs), "last_facing": fac,
                    "no_motion_frames": int(bad[g].sum()), "end_facing": float(fp[-1] % 360),
                    "next_teardrop": rows[g[-1] + 1].get("deg") if g[-1] + 1 < len(rows) else None,
                    "apex_up_median": float(np.median(ap_)), "apex_span": float(ap_.max() - ap_.min()),
                    "facing_span": float(fp.max() - fp.min()),
                    "facing_1s_max": float(max([abs(fp[j + 20] - fp[j]) for j in range(len(fp) - 20)]
                                               or [abs(fp[-1] - fp[0])])),
                    "radial_min": min(q["radial"] for q in recs), "radial_max": max(q["radial"] for q in recs),
                    "top_w": float(np.median([q["top_w"] for q in recs])),
                    "bottom_w": float(np.median([q["bottom_w"] for q in recs])), "frames": recs})
    res = {"version": VERSION, "calib_deg_per_px": k, "check_1s_n": len(chk),
           "check_1s_median_err": float(np.median(np.abs(chk[:, 1] - chk[:, 0]))),
           "check_1s_corr": float(np.corrcoef(chk[:, 0], chk[:, 1])[0, 1]), "gaps": out}
    (OUT / "marker_direction.json").write_text(json.dumps(res, indent=1))
    for q in out:
        print({kk: (round(v, 1) if isinstance(v, float) else v) for kk, v in q.items() if kk != "frames"})
    print({kk: round(v, 2) for kk, v in res.items() if isinstance(v, float)})
    if record:
        from reticle import metrics
        v = {"check_1s_median_err": round(res["check_1s_median_err"], 1), "check_1s_corr": round(res["check_1s_corr"], 2),
             "apex_span_max": round(max(q["apex_span"] for q in out), 1),
             "facing_1s_max": round(max(q["facing_1s_max"] for q in out), 1),
             "radial_min": round(min(q["radial_min"] for q in out), 1),
             "radial_max": round(max(q["radial_max"] for q in out), 1),
             "apex_up_min": round(min(q["apex_up_median"] for q in out), 1),
             "apex_up_max": round(max(q["apex_up_median"] for q in out), 1),
             "top_w": round(max(q["top_w"] for q in out), 1), "bottom_w": round(min(q["bottom_w"] for q in out), 1),
             "n_marker": sum(q["n"] for q in out),
             "facing_span_max": round(max(q["facing_span"] for q in out), 1),
             "gap2_end_facing": round(out[-1]["end_facing"], 1),
             "gap2_next_teardrop": round(out[-1]["next_teardrop"], 1),
             "no_motion_frames": sum(q["no_motion_frames"] for q in out)}
        metrics.record(Path(__file__).stem, part="marker", session=SESSION, values=v,
                       deps={"version": VERSION, "geometry": KEY}, context={"capture": VID},
                       note="off-widget self marker direction against the ring radial and the camera-integrated facing")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "witness", "occluders", "events", "sheets", "summarize",
                                    "placement", "corner", "marker"])
    ap.add_argument("--clip", choices=sorted(CLIPS), default="lotus")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    idle()
    use(a.clip)
    steps = {"occluders": occluders, "summarize": summarize, "placement": placement, "corner": clipped_corner,
             "marker": marker_direction}
    if a.cmd in steps:
        steps[a.cmd](a.record)
    else:
        {"extract": extract, "witness": witness, "events": jump_events, "sheets": sheets}[a.cmd]()


if __name__ == "__main__":
    main()
