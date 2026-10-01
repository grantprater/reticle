r"""How accurate and how clean are the minimap ally portrait crops?

    .\.venv\Scripts\python.exe prototypes\portrait_crop_audit.py collect [--windows 4] [--frames 60] [SID ...]
    .\.venv\Scripts\python.exe prototypes\portrait_crop_audit.py labels
    .\.venv\Scripts\python.exe prototypes\portrait_crop_audit.py report [--record]
    .\.venv\Scripts\python.exe prototypes\portrait_crop_audit.py sheets

Question. The player believes accurately cropped icons are the main obstacle
to minimap identity. This measures the crop the reader makes today
(`AllyIconReader`, ally-icon-0.6.0: the teardrop's centre, then
`ally_portrait.align_icon` and the disc of 0.75 `DISC_R`) on the minimap crop
cache of the 21 match sessions. It decodes no video; the reader is run on
cached frames, since 18 of the 21 stored streams predate the teardrop centre.

Centre jitter (`collect`). Seeded windows of consecutive cached frames, clear
of capture stalls. A run starts at a described icon and lasts while a witness
INDEPENDENT of the fit says the icon stood still, in a disc of radius 2r
about the first frame's centre:

* `pixel`: at most 1% of the disc's pixels differ from the run's first frame
  by more than `T_PIX` grey levels (max over BGR). `T_PIX` = 10 sits above the
  1-4 level noise mode of icon-free slab windows (pilot on 5822b6646448 and
  223d636bf8d2); 6 and 16 are reported beside it.
* `key`: at most 1% of the disc's pixels flip the teal/self key; light and
  neighbours round the icon may change.

The fit nearest the anchor within half a radius is the run's fit on each
frame; its centre and facing deviate from the run's median. A deviation in
aligned pixels is a native one times `UPS * W_REF / width`, and the share of
disc pixels that change 3x3 grid cell under it is counted as `_grid` bins them.

Contamination (`collect`, `labels`). For each described icon on every fifth
frame, the aligned crop's disc less keyed pixels (what the features read) is
split by cause: inside another shaped fit's footprint (ally or self channel,
past `MIN_ICON_SEPARATION_PX`) or an enemy track observation's (`neighbour`);
within one native pixel of the keyed ring (`fringe`, the ring's antialiasing;
a keyed component reaching outside the disc is ring, one wholly inside it is
portrait art, `keyed_art`; the keyed share itself is removed rather than
contaminating); pale teal joined to the ring that the key misses
(`faint_ring`, the one-pixel ring at 331 px over a light floor); inside an
accepted spike glyph's triangle (`glyph`); and pixels that match the baked
map (`map`) or its lit state (`cone`), less the rate at which other
portraits' disc pixels match the same place (chance, eight donors from other
sessions). The ring's inner edge, fitted along 32 rays, gives the ring centre
against the crop centre in the facing frame. Static values come from baked
geometry only [domain:capture/session-pixels-are-not-the-map].

Identity (`labels`). Each of the player's death-icon labels
(`<store>/labels/death_icon`, read only) is re-read on its cached frame; the
nearest described icon is scored by `rendered_art_scores` over the label's
four teammates, and its contamination is set against right and wrong. The
facing labels' centres (`ally_facing_331_20260929`, `icon_facing_20260928`)
measure the centre's accuracy against the player.

Result (2026-10-01, 21 match sessions, four seeded 60-frame windows each).

* Jitter is a fraction of a pixel. Under the pixel witness the centre's
  p95 deviation is [metric:portrait_crop_audit/jitter_pixel_331@match21#dev_p95_native=0.0884]
  native px at 331 and [metric:portrait_crop_audit/jitter_pixel_465@match21#dev_p95_native=0.0625]
  at 465; under the key witness [metric:portrait_crop_audit/jitter_key_331@match21#dev_p95_native=0.1768]
  and [metric:portrait_crop_audit/jitter_key_465@match21#dev_p95_native=0.0884]. Facing p95 is
  [metric:portrait_crop_audit/jitter_key_331@match21#facing_p95_deg=1.3133] degrees at worst. The
  share of disc pixels that change 3x3 cell averages
  [metric:portrait_crop_audit/jitter_key_331@match21#cell_change_mean=0.0121] at 331 and
  [metric:portrait_crop_audit/jitter_key_465@match21#cell_change_mean=0.0039] at 465; the best
  guess leaves the run's modal agent on
  [metric:portrait_crop_audit/jitter_key_331@match21#identity_flip_share=0.0155] of 331 frames and
  none at 465. The teardrop centre moves in 1/16 px steps on
  [metric:portrait_crop_audit/jitter_pixel_331@match21#teardrop_moved_share=0.3925] of still
  331 frames, the ring's integer centre on
  [metric:portrait_crop_audit/jitter_pixel_331@match21#ring_moved_share=0.0528]. The two worst
  key runs at 331 are a described icon on empty floor beside a teal wall.
* Contamination is a 331 px problem, and the ring is its cause. The median
  disc is [metric:portrait_crop_audit/contamination_331@match21#total_p50=0.0994] foreign at 331
  and [metric:portrait_crop_audit/contamination_465@match21#total_p50=0.0224] at 465. At 331 the
  ring's inner edge lies [metric:portrait_crop_audit/contamination_331@match21#ring_inner_R_p50_aligned=10.1321]
  aligned px from the crop centre against the disc's 9, and the disc reaches
  the ring on [metric:portrait_crop_audit/contamination_331@match21#share_disc_reaches_ring=0.5521]
  of crops ([metric:portrait_crop_audit/contamination_465@match21#share_disc_reaches_ring=0.0047] at
  465); the ring's centre sits [metric:portrait_crop_audit/contamination_331@match21#ring_along_p50_native=0.4265]
  native px toward the lobe from the teardrop's centre at 331 and
  [metric:portrait_crop_audit/contamination_465@match21#ring_along_p50_native=-0.2617] at 465.
  Ring fringe averages [metric:portrait_crop_audit/contamination_331@match21#fringe_mean=0.0538]
  and the unkeyed faint ring [metric:portrait_crop_audit/contamination_331@match21#faint_ring_mean=0.0317]
  at 331. Neighbours cover 10% of the disc on
  [metric:portrait_crop_audit/contamination_331@match21#neighbour_share_ge_10pct=0.0] of 331 crops
  and [metric:portrait_crop_audit/contamination_465@match21#neighbour_share_ge_10pct=0.0017] at 465;
  the spike glyph touches [metric:portrait_crop_audit/contamination_331@match21#glyph_share_any=0.0298]
  and [metric:portrait_crop_audit/contamination_465@match21#glyph_share_any=0.0617], covering a
  quarter or more of the disc when it does. Cone light does not brighten the
  portrait: when the annulus brightens by a median
  [metric:portrait_crop_audit/jitter_key_465@match21#cone_annulus_delta_p50=12.5552] grey levels the
  disc moves [metric:portrait_crop_audit/jitter_key_465@match21#cone_disc_delta_p50=-0.0035]; the
  `cone` matches mark the ring's pale blend and bright skin.
* Identity barely depends on it. On the player's death-icon labels the best
  guess is right on [metric:portrait_crop_audit/labels@match21#accuracy=0.9714] of
  [metric:portrait_crop_audit/labels@match21#read=140]; wrong guesses are dirtier (median
  [metric:portrait_crop_audit/labels@match21#wrong_total_p50=0.2357] against
  [metric:portrait_crop_audit/labels@match21#right_total_p50=0.0734]), but only
  [metric:portrait_crop_audit/labels@match21#wrong=4] are wrong, and
  [metric:portrait_crop_audit/labels@match21#right_share_ge_10pct=0.4118] of right guesses carry
  10% or more. The teardrop lies within 1 px of the player's centre on
  [metric:portrait_crop_audit/labels@match21#centre_within_1px_331=0.5806] at 331 and
  [metric:portrait_crop_audit/labels@match21#centre_within_1px_465=0.76] at 465.

Outputs go to `<store>/analysis/portrait-crop-audit-20261001/` (summary and
contact sheets); intermediate pickles to the temp directory. Predictions and
outcome: `portrait-crop-audit-20261001` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import ally_portrait as ap  # noqa: E402
from reticle import geometry, lighting, stalls  # noqa: E402
from reticle.adjudication.identity import rendered_art_scores  # noqa: E402
from reticle.minimap import (ALLY_COV_MIN, ALLY_INNER_MAX,  # noqa: E402
                             MIN_ICON_SEPARATION_PX, ally_icon_reader, portrait_key,
                             widget_scale)
from reticle.passes import SessionContext  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.spike import SEED_Y, _base_down, spike_yellowness  # noqa: E402
from reticle.store import Store  # noqa: E402

cv2.setNumThreads(1)
STORE = Store()
TASK = "portrait-crop-audit-20261001"
OUT = STORE.root / "analysis" / TASK
WORK = Path(tempfile.gettempdir()) / "portrait_crop_audit"
MATCH_MIN_MS = 15 * 60 * 1000
T_PIX, T_SENS = 10, (6, 16)
STILL_FRAC = KEY_FRAC = 0.01
GAP_MS = 120.0
MIN_RUN = 5
SUB = 5
ENEMY_R = 10.0           # an enemy icon's footprint radius at scale 1.0, native px
MAP_DE, CHROMA, LIT_SD, LIT_MIN = 12.0, 10.0, 2.5, 6.0
FAINT_H, FAINT_S, FAINT_V = (68, 94), 35, 110   # OpenCV HSV: pale teal ring
CAUSES = ("neighbour", "fringe", "faint_ring", "glyph", "map", "cone")


def lower_priority() -> None:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)   # Below Normal


def match_sessions() -> list[str]:
    root = STORE.root / "roi_cache" / "minimap" / "roi-cache-0.1.0"
    out = []
    for p in sorted(root.glob("*.json")):
        sid = p.name.split(".")[0]
        man = STORE.read_manifest(sid)
        if float(man["source"]["duration_ms"]) > MATCH_MIN_MS:
            out.append(sid)
    return out


# ------------------------------------------------------------------ reading

class Session:
    """One session's reader, cache, baked statics and side inputs."""

    def __init__(self, sid: str):
        self.sid = sid
        self.man = STORE.read_manifest(sid)
        prof = get_profile(self.man["source_profile"])
        ctx = SessionContext(store=STORE, manifest=self.man, profile=prof)
        self.reader = ally_icon_reader(ctx)
        self.cache, why = RoiCache.load(STORE.root, self.man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap cache ({why})")
        self.static = self.reader.static
        with np.load(geometry.path_of(sid, STORE.root)) as z:
            self.light = lighting.reference(z)
        self.stalls = stalls.for_session(STORE, sid, self.man["ingested_at"][:10])
        self.enemies = defaultdict(list)
        for e in STORE.read_events("enemy_track", sid):
            if e.get("kind") == "observation" and e.get("x") is not None:
                self.enemies[int(round(float(e["t_ms"])))].append((float(e["x"]), float(e["y"])))
        x0, y0, x1, y1 = self.reader.box
        self.width = x1 - x0
        self.s = ap.UPS * ap.W_REF / self.width          # aligned px per native px
        self.sc = widget_scale(self.width)
        if self.light is not None:
            L = self.light
            self.lmaps = (np.dstack([L.lo, L.hi, L.sd_lo]).astype(np.float32),
                          np.dstack([L.sd_hi, L.known.astype(np.float32),
                                     lighting.crossing(L)]).astype(np.float32))

    def enemies_at(self, t: float) -> list[tuple[float, float]]:
        out = []
        for k in range(int(round(t)) - 40, int(round(t)) + 41):
            out += self.enemies.get(k, [])
        return out

    def read(self, ts) -> list[dict]:
        """The reader's output on each cached frame of `ts`, with the crop."""
        r = self.reader
        x0, y0, x1, y1 = r.box
        out = []
        for smp in self.cache.samples(list(ts), rois=["minimap"]):
            r.icons.clear()
            r.candidates.clear()
            r.frames.clear()
            r.feed(smp)
            out.append({"t": float(smp.t_ms), "fidx": int(smp.frame_idx),
                        "crop": smp.frame[y0:y1, x0:x1].copy(),
                        "icons": [dict(i) for i in r.icons],
                        "cands": [dict(c) for c in r.candidates]})
        return out


def pick_windows(sess: Session, n_windows: int, n_frames: int) -> list[list[float]]:
    held = np.asarray(sess.cache.holds(), float)
    rng = np.random.default_rng(int(sess.sid[:8], 16))
    used, out = np.zeros(len(held), bool), []
    for _ in range(n_windows * 40):
        if len(out) >= n_windows or len(held) < n_frames:
            break
        i = int(rng.integers(0, len(held) - n_frames))
        seg = held[i:i + n_frames]
        if used[i:i + n_frames].any() or np.diff(seg).max() > GAP_MS:
            continue
        if any(stalls.stalled_at(sess.stalls, float(t)) for t in seg):
            continue
        used[i:i + n_frames] = True
        out.append([float(t) for t in seg])
    return out


# ------------------------------------------------------------------- jitter

def _patch(crop, ax, ay, R):
    h, w = crop.shape[:2]
    if ax - R < 0 or ay - R < 0 or ax + R >= w or ay + R >= h:
        return None
    return crop[ay - R:ay + R + 1, ax - R:ax + R + 1]


def _discs(R, r):
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    d = np.hypot(xx, yy)
    return d <= R, d <= 0.6 * r, (d >= 1.25 * r) & (d <= R)


def _described(f):
    return [(i, ic) for i, ic in enumerate(f["icons"]) if ic.get("reason") is None]


def _nearest(f, ax, ay, tol):
    best = None
    for i, ic in _described(f):
        d = float(np.hypot(ic["cx"] - ax, ic["cy"] - ay))
        if d <= tol and (best is None or d < best[0]):
            best = (d, i, ic)
    return best


def _fit_row(ic):
    ring = ic.get("ring") or {}
    pose = ic.get("pose") or {}
    return {"cx": float(ic["cx"]), "cy": float(ic["cy"]), "r": int(ic["r"]),
            "facing": None if ic.get("facing") is None else float(ic["facing"]),
            "ring_cx": ring.get("cx"), "ring_cy": ring.get("cy"),
            "origin": pose.get("origin"), "ncc": pose.get("ncc"),
            "features": ic.get("portrait_features")}


def runs_in_window(sess: Session, frames: list[dict], mode: str) -> list[dict]:
    """Stationary runs by one witness (`pixel` or `key`); see the module doc."""
    covered = [set() for _ in frames]
    out = []
    for k, f in enumerate(frames):
        for ii, ic in _described(f):
            if ii in covered[k]:
                continue
            ax, ay, r = int(round(ic["cx"])), int(round(ic["cy"])), int(ic["r"])
            R = 2 * r
            p0 = _patch(f["crop"], ax, ay, R)
            if p0 is None:
                continue
            win, port, ann = _discs(R, r)
            k0 = portrait_key(p0)
            p0i = p0.astype(np.int16)
            seq = [{"j": k, "fit": _fit_row(ic), "idx": ii, "identical": True,
                    "changed": {T: 0.0 for T in (T_PIX,) + T_SENS}, "key_flip": 0.0,
                    "disc_changed": 0.0, "ann_changed": 0.0}]
            j = k + 1
            while j < len(frames):
                pj = _patch(frames[j]["crop"], ax, ay, R)
                if pj is None:
                    break
                d = np.abs(pj.astype(np.int16) - p0i).max(2)
                changed = {T: float((d[win] > T).mean()) for T in (T_PIX,) + T_SENS}
                kj = portrait_key(pj)
                flip = float((kj != k0)[win].mean())
                still = (changed[T_PIX] <= STILL_FRAC if mode == "pixel" else flip <= KEY_FRAC)
                if not still:
                    break
                free = ~(kj | k0)
                pm, am = port & free, ann & free
                sd = pj.astype(np.int16).mean(2) - p0i.mean(2)       # signed grey change
                hit = _nearest(frames[j], ax, ay, 0.5 * r)
                seq.append({"j": j, "fit": None if hit is None else _fit_row(hit[2]),
                            "idx": None if hit is None else hit[1],
                            "identical": bool((d == 0).all()), "changed": changed,
                            "key_flip": flip,
                            "disc_changed": float((d[pm] > T_PIX).mean()) if pm.any() else None,
                            "ann_changed": float((d[am] > T_PIX).mean()) if am.any() else None,
                            "disc_delta": float(sd[pm].mean()) if pm.any() else None,
                            "ann_delta": float(sd[am].mean()) if am.any() else None})
                j += 1
            for e in seq:
                if e["idx"] is not None:
                    covered[e["j"]].add(e["idx"])
            if len(seq) < MIN_RUN:
                continue
            half = 22
            imgs = []
            for e in seq:
                c = frames[e["j"]]["crop"]
                pad = cv2.copyMakeBorder(c, half, half, half, half, cv2.BORDER_CONSTANT)
                imgs.append(cv2.imencode(".png", pad[ay:ay + 2 * half + 1, ax:ax + 2 * half + 1])[1])
            out.append({"sid": sess.sid, "mode": mode, "width": sess.width, "s": sess.s,
                        "anchor": (ax, ay), "r": r, "t0": frames[k]["t"],
                        "t": [frames[e["j"]]["t"] for e in seq], "frames": seq,
                        "patches": imgs, "half": half})
    return out


# ------------------------------------------------------------ contamination

def _aligned_maps(sess: Session, cx: float, cy: float):
    st = ap.align_icon(sess.static, cx, cy, sess.width)
    if sess.light is None:
        return st, None, None
    a = ap.align_icon(sess.lmaps[0], cx, cy, sess.width)
    b = ap.align_icon(sess.lmaps[1], cx, cy, sess.width)
    return st, a, b


def _map_cone(img_lab, g, st, a, b):
    """Masks of aligned pixels matching the baked map (unlit) and its lit state."""
    st_lab = cv2.cvtColor(st, cv2.COLOR_BGR2Lab).astype(np.float32)
    de = np.linalg.norm(img_lab - st_lab, axis=2)
    chroma = np.linalg.norm(img_lab[..., 1:] - st_lab[..., 1:], axis=2)
    bare = st.sum(2) > 0
    mp = bare & (de <= MAP_DE)
    if a is None:
        return mp, np.zeros_like(mp)
    lo, hi, sd_lo = a[..., 0], a[..., 1], a[..., 2]
    sd_hi, known, cross = b[..., 0], b[..., 1] > 0.5, b[..., 2]
    cone = (known & (g > cross) & (np.abs(g - hi) <= np.maximum(LIT_SD * sd_hi, LIT_MIN))
            & (chroma <= CHROMA) & ~mp)
    return mp, cone


def _glyph_mask(g, cx, cy, s, sc, shape):
    L = g["side"] * sc
    Rc = L / np.sqrt(3.0)
    down = _base_down(g["state"])
    k = 1.0 if down else -1.0
    pts = [(g["cx"], g["cy"] - k * Rc), (g["cx"] - L / 2, g["cy"] + k * Rc / 2),
           (g["cx"] + L / 2, g["cy"] + k * Rc / 2)]
    c = (ap.SIDE - 1) / 2
    poly = np.array([[(x - cx) * s + c, (y - cy) * s + c] for x, y in pts], np.float32)
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.round(poly * 16).astype(np.int32)], 1, lineType=cv2.LINE_8, shift=4)
    return m > 0


def contamination(sess: Session, f: dict, ic: dict) -> dict:
    """The disc's pixels by cause, for one described icon on one frame."""
    s, sc = sess.s, sess.sc
    cx, cy = float(ic["cx"]), float(ic["cy"])
    img = ap.align_icon(f["crop"], cx, cy, sess.width)
    keyed = portrait_key(img)
    rg = ap._region(ap.SIDE, ap.DISC_R)
    disc = rg["disc"]
    U = ap._unkeyed(disc, keyed)
    c = rg["c"]
    xn = cx + (rg["xx"] - c) / s
    yn = cy + (rg["yy"] - c) / s
    nb = np.zeros_like(disc)
    sep = MIN_ICON_SEPARATION_PX * sc
    others = []
    for o in f["cands"]:
        if o["cov"] < ALLY_COV_MIN or o["inner"] > ALLY_INNER_MAX:
            continue
        if np.hypot(o["cx"] - cx, o["cy"] - cy) < sep:
            continue
        others.append((o["cx"], o["cy"], o["r"] + 1.0, o["channel"]))
    for ex, ey in sess.enemies_at(f["t"]):
        if np.hypot(ex - cx, ey - cy) < 3 * ENEMY_R * sc:
            others.append((ex, ey, ENEMY_R * sc + 1.0, "enemy"))
    kinds = Counter()
    for ox, oy, orad, ch in others:
        inside = np.hypot(xn - ox, yn - oy) <= orad
        if (inside & U).any():
            kinds[ch] += int((inside & U).sum())
        nb |= inside
    # The key also catches portrait art drawn in teal or yellow (hair, a
    # weapon's glow). A keyed component that reaches outside the disc is the
    # ring, its lobe or a neighbour's; one wholly inside it is art.
    n_cc, lbl = cv2.connectedComponents(keyed.astype(np.uint8), connectivity=8)
    outside = np.hypot(rg["xx"] - c, rg["yy"] - c) > 0.75 * ap.DISC_R + 0.5
    ring_ids = set(np.unique(lbl[outside & keyed])) - {0}
    ring_key = np.isin(lbl, list(ring_ids)) & keyed
    art_key = keyed & ~ring_key
    rad = max(1, int(np.ceil(s)))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1, 2 * rad + 1))
    fringe = cv2.dilate(ring_key.astype(np.uint8), ker) > 0
    # At 331 px the ring is about one native pixel wide and blends with the
    # map beneath it; the key misses its paler arcs. A faint ring pixel is
    # teal at lower saturation, in a teal component that reaches outside the
    # disc (with the keyed ring).
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    soft = ((hsv[..., 0] >= FAINT_H[0]) & (hsv[..., 0] <= FAINT_H[1])
            & (hsv[..., 1] >= FAINT_S) & (hsv[..., 2] >= FAINT_V)) | ring_key
    n2, lbl2 = cv2.connectedComponents(soft.astype(np.uint8), connectivity=8)
    ring_ids2 = set(np.unique(lbl2[outside & soft])) - {0}
    ring_all = np.isin(lbl2, list(ring_ids2)) & soft
    faint = ring_all & ~keyed & ~fringe
    glyphs = {}
    for o in f["cands"]:
        for g in o.get("spike_glyphs") or ():
            glyphs[(g["cx"], g["cy"])] = g
    gm = np.zeros_like(disc)
    for g in glyphs.values():
        gm |= _glyph_mask(g, cx, cy, s, sc, disc.shape)
    img_lab = cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float32)
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    st, a, b = _aligned_maps(sess, cx, cy)
    mp, cone = _map_cone(img_lab, grey, st, a, b)
    n = float(U.sum())
    # The glyph is keyed too (yellow), so its antialiased edge would read as
    # ring fringe: fringe pixels within one native pixel of an accepted
    # glyph's triangle count as glyph.
    gzone = cv2.dilate(gm.astype(np.uint8), ker) > 0
    masks = {"neighbour": nb & U, "fringe": fringe & ~gzone & U, "faint_ring": faint & U,
             "glyph": (gm | (fringe & gzone)) & U, "map": mp & U, "cone": cone & U}
    frac = {k: float(v.sum()) / n for k, v in masks.items()}
    geom = (masks["neighbour"] | masks["fringe"] | masks["faint_ring"] | masks["glyph"])
    light_only = (masks["map"] | masks["cone"]) & ~geom
    yel = spike_yellowness(img) >= SEED_Y
    ring_off = _ring_offset(ring_all, c)
    return {"ring_off": ring_off, "facing": ic.get("facing"),"sid": sess.sid, "t": f["t"], "width": sess.width, "cx": cx, "cy": cy,
            "r": int(ic["r"]), "n_disc": int(disc.sum()), "n_unkeyed": int(n),
            "keyed": float((disc & keyed).sum()) / disc.sum(),
            "keyed_ring": float((disc & ring_key).sum()) / disc.sum(),
            "keyed_art": float((disc & art_key).sum()) / disc.sum(), "frac": frac,
            "neighbour_kinds": {k: v / n for k, v in kinds.items()},
            "geom": float(geom.sum()) / n,
            "light_only": float(light_only.sum()) / n,
            "light_all": float((masks["map"] | masks["cone"]).sum()) / n,
            "yellow_unkeyed": float((yel & U).sum()) / n,
            "glyphs": len(glyphs),
            "features": ic.get("portrait_features"),
            "img": cv2.imencode(".png", img)[1],
            "st": cv2.imencode(".png", st)[1],
            "lm": (None if a is None else np.dstack([a, b]).astype(np.float16)),
            "U": np.packbits(U), "geom_mask": np.packbits(geom),
            "art_key": np.packbits(art_key & disc),
            "masks": {k: np.packbits(v) for k, v in masks.items()}}


def _ring_offset(ring_key: np.ndarray, c: float, n: int = 32) -> dict | None:
    """Where the ring's inner edge sits about the crop centre (aligned px).

    Along each of `n` rays the inner edge is the first ring-key pixel. A
    circle whose centre lies at d gives r(theta) = R + d cos(theta - phi),
    and the ring centre lies at d from the crop centre. None when fewer than
    three quarters of the rays meet the ring (the lobe or a gap)."""
    rs, us = [], []
    rmax = 1.6 * ap.DISC_R
    for k in range(n):
        th = 2 * np.pi * k / n
        u = (np.cos(th), np.sin(th))
        hit = None
        for rr in np.arange(2.0, rmax, 0.25):
            x, y = int(round(c + rr * u[0])), int(round(c + rr * u[1]))
            if not (0 <= x < ring_key.shape[1] and 0 <= y < ring_key.shape[0]):
                break
            if ring_key[y, x]:
                hit = rr
                break
        if hit is not None:
            rs.append(hit)
            us.append(u)
    if len(rs) < 0.75 * n:
        return None
    rs, us = np.array(rs), np.array(us)
    # Least squares for r = R + dx cos + dy sin over the rays found.
    A = np.column_stack([np.ones(len(rs)), us[:, 0], us[:, 1]])
    R, dx, dy = np.linalg.lstsq(A, rs, rcond=None)[0]
    resid = rs - A @ np.array([R, dx, dy])
    return {"R": float(R), "dx": float(dx), "dy": float(dy), "rays": len(rs),
            "resid": float(np.sqrt(np.mean(resid ** 2)))}


def _unpack(bits) -> np.ndarray:
    return np.unpackbits(bits)[:ap.SIDE * ap.SIDE].reshape(ap.SIDE, ap.SIDE).astype(bool)


def finalise(rows: list[dict], pool_rows: list[dict] | None = None, donors: int = 8) -> None:
    """Chance-correct the map and cone matches, in place.

    A portrait pixel can match the baked map by colour alone. The chance rate
    at one crop's place is how often OTHER portraits' disc pixels (same widget
    size, other sessions where possible) match that place's map; a crop's
    `total` adds its unexplained map and cone matches less that rate."""
    rng = np.random.default_rng(7)
    pool_rows = rows if pool_rows is None else pool_rows
    by_w = _group(range(len(pool_rows)), lambda i: pool_rows[i]["width"])
    cache = {}

    def lab_grey(i):
        if i not in cache:
            img = cv2.imdecode(pool_rows[i]["img"], cv2.IMREAD_COLOR)
            cache[i] = (cv2.cvtColor(img, cv2.COLOR_BGR2Lab).astype(np.float32),
                        cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32),
                        _unpack(pool_rows[i]["U"]))
        return cache[i]
    for r in rows:
        pool = ([j for j in by_w[r["width"]] if pool_rows[j]["sid"] != r["sid"]]
                or [j for j in by_w[r["width"]] if pool_rows[j] is not r])
        st = cv2.imdecode(r["st"], cv2.IMREAD_COLOR)
        lm = r.get("lm")
        a = b = None
        if lm is not None:
            lm = lm.astype(np.float32)
            a, b = lm[..., :3], lm[..., 3:]
        ch = []
        for j in rng.choice(pool, size=min(donors, len(pool)), replace=False):
            L, g, Uj = lab_grey(int(j))
            m2, c2 = _map_cone(L, g, st, a, b)
            ch.append(float(((m2 | c2) & Uj).sum()) / max(1, Uj.sum()))
        r["chance"] = float(np.mean(ch)) if ch else 0.0
        r["total"] = r["geom"] + min(r["light_only"], max(0.0, r["light_all"] - r["chance"]))


# ------------------------------------------------------------------ collect

def collect_runs(sids: list[str], n_windows: int, n_frames: int) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    for sid in sids:
        t0 = time.time()
        sess = Session(sid)
        windows = pick_windows(sess, n_windows, n_frames)
        runs, rows, nframes = [], [], 0
        for ts in windows:
            frames = sess.read(ts)
            nframes += len(frames)
            for mode in ("pixel", "key"):
                runs += runs_in_window(sess, frames, mode)
            for f in frames[::SUB]:
                for _i, ic in _described(f):
                    rows.append(contamination(sess, f, ic))
        (WORK / f"{sid}.pkl").write_bytes(pickle.dumps(
            {"sid": sid, "width": sess.width, "windows": windows, "frames": nframes,
             "runs": runs, "rows": rows}))
        print(f"{sid} w{sess.width} windows {len(windows)} frames {nframes} runs "
              f"{Counter(r['mode'] for r in runs)} rows {len(rows)} "
              f"{time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------------- labels

def _audit_label_rows(name: str) -> list[dict]:
    p = STORE.root / "labels" / name
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    out = {}
    for fp in files:
        for line in fp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return list(out.values())


def _nearest_any(f, x, y, tol):
    best = None
    for i, ic in _described(f):
        d = float(np.hypot(ic["cx"] - x, ic["cy"] - y))
        if d <= tol and (best is None or d < best[0]):
            best = (d, i, ic)
    return best


def _frame_at(sess: Session, t: float):
    held = np.asarray(sess.cache.holds(), float)
    i = int(np.argmin(np.abs(held - t)))
    if abs(held[i] - t) > 40:
        return None
    got = sess.read([float(held[i])])
    return got[0] if got else None


def labels() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    refs = ap.load_references(STORE.root)
    death = [r for r in _audit_label_rows("death_icon") if r["class"] in ("agent", "not_portrait")]
    facing = [dict(r, size=331) for r in _audit_label_rows("ally_facing_331_20260929.jsonl")
              if r.get("cls") == "ally" and r.get("answer") == "facing"]
    facing += [dict(r, size=465) for r in _audit_label_rows("icon_facing_20260928.jsonl")
               if r.get("cls") == "ally" and r.get("answer") == "facing"]
    by_sid = defaultdict(lambda: ([], []))
    for r in death:
        by_sid[r["session_id"]][0].append(r)
    for r in facing:
        by_sid[r["session"]][1].append(r)
    out_death, out_centre = [], []
    for sid in sorted(by_sid):
        sess = Session(sid)
        tol = 0.8 * MIN_ICON_SEPARATION_PX * sess.sc
        for r in by_sid[sid][0]:
            f = _frame_at(sess, float(r["t_ms"]))
            hit = None if f is None else _nearest_any(f, float(r["cx"]), float(r["cy"]), tol)
            row = {"key": r["key"], "sid": sid, "class": r["class"], "answer": r.get("answer"),
                   "teammates": r["teammates"], "width": sess.width,
                   "reason": None if hit else ("no_frame" if f is None else "no_described_icon")}
            if hit:
                ic = hit[2]
                con = contamination(sess, f, ic)
                sc = rendered_art_scores(ic.get("portrait_features"), r["teammates"], refs)
                best = max(sc, key=sc.get) if sc else None
                srt = sorted(sc.values(), reverse=True) if sc else []
                row.update({"dist": hit[0], "best": best,
                            "margin": srt[0] - srt[1] if len(srt) > 1 else None,
                            "contam": con})
            out_death.append(row)
        for r in by_sid[sid][1]:
            f = _frame_at(sess, float(r["t_ms"]))
            hit = None if f is None else _nearest_any(f, float(r["ring_x"]), float(r["ring_y"]), tol)
            row = {"key": r["key"], "sid": sid, "size": r["size"], "width": sess.width,
                   "found": hit is not None}
            if hit:
                ic = hit[2]
                ring = ic.get("ring") or {}
                row.update({"dx": ic["cx"] - r["centre_x"], "dy": ic["cy"] - r["centre_y"],
                            "ring_dx": (ring.get("cx", ic["cx"]) - r["centre_x"]),
                            "ring_dy": (ring.get("cy", ic["cy"]) - r["centre_y"]),
                            "origin": (ic.get("pose") or {}).get("origin")})
            out_centre.append(row)
        print(sid, "death", len(by_sid[sid][0]), "centre", len(by_sid[sid][1]), flush=True)
    (WORK / "labels.pkl").write_bytes(pickle.dumps({"death": out_death, "centre": out_centre}))


# ------------------------------------------------------------------- report

def _circ_dev(deg):
    a = np.radians(np.asarray(deg, float))
    m = np.degrees(np.arctan2(np.sin(a).mean(), np.cos(a).mean()))
    return np.abs((np.asarray(deg, float) - m + 180) % 360 - 180)


def cell_change(dx: float, dy: float) -> float:
    """The share of the disc's content that lands in another 3x3 grid cell
    when the fitted centre moves by (dx, dy) aligned px over a still icon.

    Each disc pixel then samples the content at its position plus (dx, dy),
    bilinearly, as `align_icon` resamples; the share is the interpolation
    weight drawn from source pixels that `_grid` bins into another cell."""
    rg = ap._region(ap.SIDE, ap.DISC_R)
    c, R = rg["c"], rg["R"]
    d = rg["disc"]
    x, y = rg["xx"][d].astype(int), rg["yy"][d].astype(int)

    def cell(u):
        return np.clip(((u - (c - 0.75 * R)) / (1.5 * R) * 3).astype(int), 0, 2)
    x0, y0 = np.floor(x + dx).astype(int), np.floor(y + dy).astype(int)
    fx, fy = (x + dx) - x0, (y + dy) - y0
    cx, cy = cell(x), cell(y)
    moved = np.zeros(len(x))
    for ix, wx in ((0, 1 - fx), (1, fx)):
        for iy, wy in ((0, 1 - fy), (1, fy)):
            other = (cell(x0 + ix) != cx) | (cell(y0 + iy) != cy)
            moved += wx * wy * other
    return float(moved.mean())


def _pct(v, qs=(50, 90, 95, 99)):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return {f"p{q}": round(float(np.percentile(v, q)), 4) for q in qs} if len(v) else {}


def _teammates() -> dict[str, list[str]]:
    out = {}
    for r in _audit_label_rows("death_icon"):
        out.setdefault(r["session_id"], r["teammates"])
    return out


def jitter_summary(runs: list[dict], refs, mates) -> dict:
    res = {}
    for (mode, width), group in sorted(_group(runs, lambda r: (r["mode"], r["width"])).items()):
        dev, dev_al, fdev, ring_moved, td_moved, cells, nonident = [], [], [], 0, 0, [], 0
        n_fit, n_frames, lost = 0, 0, 0
        famratio = defaultdict(list)
        flips, flip_n = 0, 0
        cone_pairs = []
        run_max = []
        sens = {T: [0, 0, []] for T in T_SENS}
        for run in group:
            fits = [e["fit"] for e in run["frames"] if e["fit"] is not None]
            n_frames += len(run["frames"])
            lost += sum(e["fit"] is None for e in run["frames"])
            for e in run["frames"][1:]:
                if e["ann_changed"] is not None and e["disc_changed"] is not None:
                    cone_pairs.append((e["ann_changed"], e["disc_changed"],
                                       e["ann_delta"], e["disc_delta"]))
            if len(fits) < MIN_RUN:
                continue
            xs = np.array([f["cx"] for f in fits])
            ys = np.array([f["cy"] for f in fits])
            mx, my = np.median(xs), np.median(ys)
            d = np.hypot(xs - mx, ys - my)
            dev += list(d)
            dev_al += list(d * run["s"])
            ch = [e["changed"] for e in run["frames"] if e["fit"] is not None]
            for T in T_SENS:
                ok = np.array([c.get(T, c.get(str(T), 1.0)) <= STILL_FRAC for c in ch])
                sens[T][0] += int(ok.sum())
                sens[T][1] += len(ok)
                sens[T][2] += list(d[ok])
            run_max.append(float(d.max()))
            nonident += sum(not e["identical"] for e in run["frames"] if e["fit"] is not None)
            n_fit += len(fits)
            for x, y in zip(xs, ys):
                cells.append(cell_change((x - mx) * run["s"], (y - my) * run["s"]))
            fac = [f["facing"] for f in fits if f["facing"] is not None]
            if len(fac) >= 2:
                fdev += list(_circ_dev(fac))
            rx = [(f["ring_cx"], f["ring_cy"]) for f in fits if f["ring_cx"] is not None]
            if rx:
                ring_moved += sum(p != rx[0] for p in rx)
            td_moved += int(np.sum((xs != xs[0]) | (ys != ys[0])))
            feats = [f["features"] for f in fits if f["features"]]
            if refs and len(feats) >= MIN_RUN:
                for fam, var in refs["variance"].items():
                    F = np.array([x[fam] for x in feats], float)
                    famratio[fam].append(float((F.var(0) / np.asarray(var, float)).mean()))
                names = mates.get(run["sid"])
                if names:
                    g = []
                    for x in feats:
                        sc = rendered_art_scores(x, names, refs)
                        g.append(max(sc, key=sc.get) if sc else None)
                    mode_g = Counter(g).most_common(1)[0][0]
                    flips += sum(x != mode_g for x in g)
                    flip_n += len(g)
        cp = np.array(cone_pairs) if cone_pairs else np.zeros((0, 4))
        lit = cp[cp[:, 0] > 0.10] if len(cp) else cp
        # Light adds brightness: if it reached the portrait, the disc would
        # brighten with the annulus. Noise from a re-encoded block has no sign.
        bright, dim = lit[lit[:, 2] > 5] if len(lit) else lit, lit[lit[:, 2] < -5] if len(lit) else lit
        corr = (float(np.corrcoef(lit[:, 2], lit[:, 3])[0, 1])
                if len(lit) > 5 and lit[:, 3].std() > 0 and lit[:, 2].std() > 0 else None)
        res[f"{mode}@{width}"] = {
            "runs": len(group), "frames": n_frames, "fits": n_fit, "lost_frames": lost,
            "nonidentical_fit_frames": nonident,
            "dev_native": _pct(dev), "dev_aligned": _pct(dev_al),
            "dev_native_mean": round(float(np.mean(dev)), 4) if dev else None,
            "run_max_native": _pct(run_max),
            "sensitivity": {f"T{T}": {"frames_still_share": round(v[0] / max(1, v[1]), 4),
                                      "dev_native": _pct(v[2], (50, 95, 99))}
                            for T, v in sens.items()},
            "facing_dev_deg": _pct(fdev),
            "teardrop_moved_share": round(td_moved / max(1, n_fit), 4),
            "ring_moved_share": round(ring_moved / max(1, n_fit), 4),
            "cell_change_mean": round(float(np.mean(cells)), 4) if cells else None,
            "cell_change": _pct(cells),
            "feature_var_over_ref": {k: _pct(v, (50, 90)) for k, v in famratio.items()},
            "identity_flip_share": round(flips / flip_n, 4) if flip_n else None,
            "identity_flip_frames": flip_n,
            "cone_test": {"frames_annulus_changed_gt10pct": int(len(lit)),
                          "disc_still_share": (round(float((lit[:, 1] <= 0.01).mean()), 4)
                                               if len(lit) else None),
                          "disc_changed": _pct(lit[:, 1]) if len(lit) else {},
                          "frames_annulus_brightened_gt5": int(len(bright)),
                          "disc_delta_when_annulus_brightened": _pct(bright[:, 3], (10, 50, 90)) if len(bright) else {},
                          "annulus_delta_when_brightened": _pct(bright[:, 2], (10, 50, 90)) if len(bright) else {},
                          "disc_delta_when_annulus_dimmed": _pct(dim[:, 3], (10, 50, 90)) if len(dim) else {},
                          "corr_annulus_disc_delta": None if corr is None else round(corr, 4)},
        }
    return res


def _group(xs, key):
    g = defaultdict(list)
    for x in xs:
        g[key(x)].append(x)
    return g


def ring_offset_summary(group: list[dict]) -> dict:
    """The ring's centre against the crop centre, native px, in the facing frame.

    `along` is positive toward the lobe's tip; `margin` is the aligned px
    between the descriptor disc's edge and the ring's inner edge on the
    ring's near side (negative: the disc reaches the ring)."""
    rows = [r for r in group if r.get("ring_off") and r["ring_off"]["resid"] <= 1.5
            and r.get("facing") is not None]
    if not rows:
        return {"crops": 0}
    s = ap.UPS * ap.W_REF / group[0]["width"]
    along, across, mag, margin, R = [], [], [], [], []
    for r in rows:
        o = r["ring_off"]
        f = np.deg2rad(float(r["facing"]))
        along.append((o["dx"] * np.cos(f) + o["dy"] * np.sin(f)) / s)
        across.append((-o["dx"] * np.sin(f) + o["dy"] * np.cos(f)) / s)
        mag.append(np.hypot(o["dx"], o["dy"]) / s)
        margin.append(o["R"] - np.hypot(o["dx"], o["dy"]) - 0.75 * ap.DISC_R)
        R.append(o["R"])
    return {"crops": len(rows), "of": len(group), "scale": round(float(s), 4),
            "along_native": _pct(along, (10, 50, 90)), "across_native": _pct(across, (10, 50, 90)),
            "offset_native": _pct(mag, (50, 90)),
            "inner_R_aligned": _pct(R, (10, 50, 90)),
            "margin_aligned": _pct(margin, (10, 50, 90)),
            "share_disc_reaches_ring": round(float(np.mean(np.array(margin) < 0)), 4)}


def contamination_summary(rows: list[dict]) -> dict:
    res = {}
    for width, group in sorted(_group(rows, lambda r: r["width"]).items()):
        tot = [r["total"] for r in group]
        out = {"crops": len(group), "sessions": len({r["sid"] for r in group}),
               "total": _pct(tot, (50, 75, 90, 95)),
               "total_mean": round(float(np.mean(tot)), 4),
               "share_total_ge_10pct": round(float(np.mean(np.array(tot) >= 0.10)), 4),
               "keyed": _pct([r["keyed"] for r in group], (50, 90)),
               "keyed_mean": round(float(np.mean([r["keyed"] for r in group])), 4),
               "keyed_ring_mean": round(float(np.mean([r["keyed_ring"] for r in group])), 4),
               "keyed_art_mean": round(float(np.mean([r["keyed_art"] for r in group])), 4),
               "share_keyed_art_ge_5pct": round(float(np.mean([r["keyed_art"] >= 0.05
                                                               for r in group])), 4),
               "light_all_mean": round(float(np.mean([r["light_all"] for r in group])), 4),
               "chance_mean": round(float(np.mean([r["chance"] for r in group])), 4),
               "light_excess_mean": round(float(np.mean([max(0.0, r["light_all"] - r["chance"])
                                                         for r in group])), 4)}
        for k in CAUSES:
            v = np.array([r["frac"][k] for r in group])
            out[k] = {"mean": round(float(v.mean()), 4), "share_any": round(float((v > 0).mean()), 4),
                      "share_ge_10pct": round(float((v >= 0.10).mean()), 4), **_pct(v, (50, 90, 99))}
        kinds = Counter()
        for r in group:
            for k, v in r["neighbour_kinds"].items():
                kinds[k] += v >= 0.10
        out["neighbour_ge_10pct_by_channel"] = dict(kinds)
        out["ring_offset"] = ring_offset_summary(group)
        res[str(width)] = out
    return res


def label_summary(lab: dict) -> dict:
    death = lab["death"]
    agents = [r for r in death if r["class"] == "agent"]
    read = [r for r in agents if r.get("best")]
    right = [r for r in read if r["best"] == r["answer"]]
    wrong = [r for r in read if r["best"] != r["answer"]]

    def stats(rs):
        t = [r["contam"]["total"] for r in rs]
        return {"n": len(rs), "total": _pct(t, (25, 50, 75, 90)),
                "share_ge_10pct": round(float(np.mean(np.array(t) >= 0.10)), 4) if t else None,
                **{k: round(float(np.mean([r["contam"]["frac"][k] for r in rs])), 4) for k in CAUSES},
                "keyed": round(float(np.mean([r["contam"]["keyed"] for r in rs])), 4) if rs else None}
    out = {"labels": len(death), "agent_labels": len(agents), "read": len(read),
           "unread": dict(Counter(r["reason"] for r in agents if not r.get("best"))),
           "right": len(right), "wrong": len(wrong),
           "accuracy": round(len(right) / len(read), 4) if read else None,
           "right_contam": stats(right), "wrong_contam": stats(wrong)}
    tot = np.array([r["contam"]["total"] for r in read])
    ok = np.array([r["best"] == r["answer"] for r in read])
    if len(read) >= 9:
        q = np.quantile(tot, [1 / 3, 2 / 3])
        bins = np.digitize(tot, q)
        out["accuracy_by_tercile"] = [{"lo": round(float(tot[bins == b].min()), 4),
                                       "hi": round(float(tot[bins == b].max()), 4),
                                       "n": int((bins == b).sum()),
                                       "accuracy": round(float(ok[bins == b].mean()), 4)}
                                      for b in range(3)]
        clean = tot < 0.05
        out["accuracy_clean_lt5pct"] = {"n": int(clean.sum()),
                                        "accuracy": round(float(ok[clean].mean()), 4) if clean.any() else None}
        # Mann-Whitney AUC: P(contamination of a wrong guess > a right one).
        a, b = tot[~ok], tot[ok]
        if len(a) and len(b):
            gt = (a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean()
            out["auc_wrong_more_contaminated"] = round(float(gt), 4)
    for width in sorted({r["width"] for r in read}):
        rs = [r for r in read if r["width"] == width]
        out[f"accuracy@{width}"] = {"n": len(rs), "accuracy": round(float(np.mean(
            [r["best"] == r["answer"] for r in rs])), 4)}
    notp = [r for r in death if r["class"] == "not_portrait" and r.get("contam")]
    out["not_portrait"] = {"n": len(notp), "total": _pct([r["contam"]["total"] for r in notp], (50,))}
    cen = {}
    for size in (331, 465):
        rs = [r for r in lab["centre"] if r["size"] == size and r["found"]]
        if not rs:
            continue
        d = np.hypot([r["dx"] for r in rs], [r["dy"] for r in rs])
        dr = np.hypot([r["ring_dx"] for r in rs], [r["ring_dy"] for r in rs])
        cen[str(size)] = {"n": len(rs), "labels": sum(r["size"] == size for r in lab["centre"]),
                          "teardrop_err": _pct(d, (50, 90)),
                          "teardrop_within_1px": round(float((d <= 1.0).mean()), 4),
                          "ring_err": _pct(dr, (50, 90)),
                          "bias_dx": round(float(np.mean([r["dx"] for r in rs])), 3),
                          "bias_dy": round(float(np.mean([r["dy"] for r in rs])), 3),
                          "origins": dict(Counter(r["origin"] for r in rs))}
    out["centre_accuracy"] = cen
    return out


def load_work():
    runs, rows, meta = [], [], {}
    for p in sorted(WORK.glob("*.pkl")):
        if p.stem == "labels":
            continue
        d = pickle.loads(p.read_bytes())
        runs += d["runs"]
        rows += d["rows"]
        meta[d["sid"]] = {"width": d["width"], "frames": d["frames"], "windows": len(d["windows"])}
    lab = pickle.loads((WORK / "labels.pkl").read_bytes()) if (WORK / "labels.pkl").exists() else None
    return runs, rows, meta, lab


def report(record: bool) -> dict:
    runs, rows, meta, lab = load_work()
    refs = ap.load_references(STORE.root)
    finalise(rows)
    if lab:
        finalise([r["contam"] for r in lab["death"] if r.get("contam")], rows)
    out = {"task": TASK, "sessions": meta,
           "settings": {"T_PIX": T_PIX, "STILL_FRAC": STILL_FRAC, "KEY_FRAC": KEY_FRAC,
                        "MIN_RUN": MIN_RUN, "SUB": SUB},
           "jitter": jitter_summary(runs, refs, _teammates()),
           "contamination": contamination_summary(rows),
           "labels": label_summary(lab) if lab else None}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    if record:
        _record(out)
    return out


def _record(out: dict) -> None:
    from reticle import metrics
    from reticle.version import ALLY_ICON_VERSION, ALLY_PORTRAIT_FEATURES_VERSION
    deps = {"ally_icon_version": ALLY_ICON_VERSION,
            "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION,
            "T_PIX": T_PIX, "STILL_FRAC": STILL_FRAC, "KEY_FRAC": KEY_FRAC}
    ctx = {"sessions": len(out["sessions"]), "prototype": "prototypes/portrait_crop_audit.py"}
    for key, j in out["jitter"].items():
        mode, width = key.split("@")
        metrics.record("portrait_crop_audit", part=f"jitter_{mode}_{width}", session="match21", deps=deps, context=ctx,
                       values={"runs": j["runs"], "fits": j["fits"],
                               "dev_p50_native": j["dev_native"].get("p50"),
                               "dev_p95_native": j["dev_native"].get("p95"),
                               "dev_p95_aligned": j["dev_aligned"].get("p95"),
                               "facing_p95_deg": j["facing_dev_deg"].get("p95"),
                               "cell_change_mean": j["cell_change_mean"],
                               "teardrop_moved_share": j["teardrop_moved_share"],
                               "ring_moved_share": j["ring_moved_share"],
                               "identity_flip_share": j["identity_flip_share"],
                               "cone_disc_still_share": j["cone_test"]["disc_still_share"],
                               "cone_disc_delta_p50": j["cone_test"]["disc_delta_when_annulus_brightened"].get("p50"),
                               "cone_annulus_delta_p50": j["cone_test"]["annulus_delta_when_brightened"].get("p50")})
    for width, c in out["contamination"].items():
        metrics.record("portrait_crop_audit", part=f"contamination_{width}", session="match21", deps=deps, context=ctx,
                       values={"crops": c["crops"], "total_p50": c["total"]["p50"],
                               "total_p90": c["total"]["p90"], "total_mean": c["total_mean"],
                               "share_total_ge_10pct": c["share_total_ge_10pct"],
                               "keyed_mean": c["keyed_mean"],
                               **{f"{k}_mean": c[k]["mean"] for k in CAUSES},
                               **{f"{k}_share_ge_10pct": c[k]["share_ge_10pct"] for k in CAUSES},
                               "glyph_share_any": c["glyph"]["share_any"],
                               "ring_offset_crops": c["ring_offset"].get("crops"),
                               "ring_along_p50_native": c["ring_offset"].get("along_native", {}).get("p50"),
                               "ring_offset_p50_native": c["ring_offset"].get("offset_native", {}).get("p50"),
                               "ring_inner_R_p50_aligned": c["ring_offset"].get("inner_R_aligned", {}).get("p50"),
                               "share_disc_reaches_ring": c["ring_offset"].get("share_disc_reaches_ring")})
    lab = out["labels"]
    if lab:
        vals = {"read": lab["read"], "accuracy": lab["accuracy"],
                "wrong": lab["wrong"],
                "wrong_share_ge_10pct": lab["wrong_contam"]["share_ge_10pct"],
                "right_share_ge_10pct": lab["right_contam"]["share_ge_10pct"],
                "wrong_total_p50": lab["wrong_contam"]["total"].get("p50"),
                "right_total_p50": lab["right_contam"]["total"].get("p50"),
                "auc_wrong_more_contaminated": lab.get("auc_wrong_more_contaminated"),
                "accuracy_clean_lt5pct": lab.get("accuracy_clean_lt5pct", {}).get("accuracy"),
                "clean_lt5pct_n": lab.get("accuracy_clean_lt5pct", {}).get("n")}
        for size, c in lab["centre_accuracy"].items():
            vals[f"centre_within_1px_{size}"] = c["teardrop_within_1px"]
            vals[f"centre_err_p50_{size}"] = c["teardrop_err"].get("p50")
        metrics.record("portrait_crop_audit", part="labels", session="match21", deps=deps, context=ctx, values=vals)


# ------------------------------------------------------------------- sheets

def _txt(img, s, y=10, col=(255, 255, 255)):
    cv2.putText(img, s, (2, y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, col, 1, cv2.LINE_AA)


def _run_tile(run, k, Z=5):
    e = run["frames"][k]
    p = cv2.imdecode(run["patches"][k], cv2.IMREAD_COLOR)
    big = cv2.resize(p, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
    h = run["half"]
    ax, ay = run["anchor"]

    def at(x, y):
        return (int(round((x - ax + h + 0.5) * Z)), int(round((y - ay + h + 0.5) * Z)))
    cv2.drawMarker(big, at(ax, ay), (0, 255, 0), cv2.MARKER_CROSS, 8, 1)
    if e["fit"] is not None:
        cv2.circle(big, at(e["fit"]["cx"], e["fit"]["cy"]), 2, (0, 0, 255), -1)
        cv2.circle(big, at(e["fit"]["cx"], e["fit"]["cy"]),
                   int(0.75 * ap.DISC_R / run["s"] * Z), (255, 0, 255), 1)
        if e["fit"]["facing"] is not None:
            a = np.radians(e["fit"]["facing"])
            c = at(e["fit"]["cx"], e["fit"]["cy"])
            cv2.line(big, c, (int(c[0] + 30 * np.cos(a)), int(c[1] + 30 * np.sin(a))), (0, 200, 255), 1)
    return big


def sheets() -> None:
    runs, rows, meta, lab = load_work()
    finalise(rows)
    if lab:
        finalise([r["contam"] for r in lab["death"] if r.get("contam")], rows)
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for (mode, width), group in sorted(_group(runs, lambda r: (r["mode"], r["width"])).items()):
        scored = []
        for run in group:
            fits = [e["fit"] for e in run["frames"] if e["fit"] is not None]
            if len(fits) < MIN_RUN:
                continue
            xs = np.array([f["cx"] for f in fits])
            ys = np.array([f["cy"] for f in fits])
            d = np.hypot(xs - np.median(xs), ys - np.median(ys))
            scored.append((float(d.max()), run, np.median(xs), np.median(ys)))
        scored.sort(key=lambda x: -x[0])
        lines = []
        for dmax, run, mx, my in scored[:8]:
            n = len(run["frames"])
            pick = sorted(set(np.linspace(0, n - 1, min(n, 10)).astype(int)))
            tiles = []
            for k in pick:
                t = _run_tile(run, k)
                e = run["frames"][k]
                lab_s = ("lost" if e["fit"] is None else
                         f"{np.hypot(e['fit']['cx'] - mx, e['fit']['cy'] - my):.2f}px "
                         f"{'' if e['fit']['facing'] is None else int(e['fit']['facing'])}")
                _txt(t, lab_s)
                tiles.append(t)
            row = np.hstack(tiles + [np.zeros_like(tiles[0])] * (10 - len(tiles)))
            head = np.zeros((14, row.shape[1], 3), np.uint8)
            _txt(head, f"{run['sid']} t={run['t0'] / 1000:.1f}s {mode} run of {n} max {dmax:.2f} native px",
                 y=11, col=(0, 255, 255))
            lines += [head, row]
        if lines:
            p = OUT / f"jitter_worst_{mode}_{width}.png"
            cv2.imwrite(str(p), np.vstack(lines))
            written.append(p)
    # BGR: neighbour magenta, fringe yellow, glyph orange, map blue, cone
    # cyan, keyed art red, faint ring green.
    colours = {"neighbour": (255, 0, 255), "fringe": (0, 255, 255), "glyph": (0, 128, 255),
               "map": (255, 128, 0), "cone": (255, 255, 0), "keyed_art": (0, 0, 255),
               "faint_ring": (0, 255, 0)}

    def crop_tile(r, causes, Z=5):
        img = cv2.imdecode(r["img"], cv2.IMREAD_COLOR)
        big = cv2.resize(img, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
        over = big.copy()
        for k in causes:
            m = _unpack(r["art_key"] if k == "keyed_art" else r["masks"][k])
            mb = cv2.resize(m.astype(np.uint8), None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST) > 0
            over[mb] = colours[k]
        big = cv2.addWeighted(big, 0.55, over, 0.45, 0)
        c = int((ap.SIDE - 1) / 2 * Z + Z / 2)
        cv2.circle(big, (c, c), int(0.75 * ap.DISC_R * Z), (255, 255, 255), 1)
        side = np.hstack([cv2.resize(img, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST), big])
        _txt(side, f"{r['sid'][:6]} {r['t'] / 1000:.1f}s w{r['width']}", y=10)
        val = {**r["frac"], "keyed_art": r["keyed_art"]}
        _txt(side, " ".join(f"{k[:2]}{val[k]:.2f}" for k in causes) + f" tot{r['total']:.2f}",
             y=side.shape[0] - 4)
        return side

    def grid(tiles, cols=4):
        if not tiles:
            return None
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])

    for k in CAUSES + ("keyed_art",):
        val = (lambda r: r["keyed_art"]) if k == "keyed_art" else (lambda r, k=k: r["frac"][k])
        top = sorted(rows, key=lambda r: -val(r))[:16]
        top = [r for r in top if val(r) > 0]
        g = grid([crop_tile(r, [k]) for r in top])
        if g is not None:
            p = OUT / f"contamination_{k}.png"
            cv2.imwrite(str(p), g)
            written.append(p)
    rng = np.random.default_rng(20261001)
    for width in sorted({r["width"] for r in rows}):
        rs = [r for r in rows if r["width"] == width]
        pick = rng.choice(len(rs), size=min(24, len(rs)), replace=False)
        g = grid([crop_tile(rs[i], list(CAUSES) + ["keyed_art"]) for i in pick])
        p = OUT / f"contamination_random_{width}.png"
        cv2.imwrite(str(p), g)
        written.append(p)
    if lab:
        wrong = [r for r in lab["death"] if r["class"] == "agent" and r.get("best")
                 and r["best"] != r["answer"]]
        wrong.sort(key=lambda r: -r["contam"]["total"])
        tiles = []
        for r in wrong[:24]:
            t = crop_tile(r["contam"], list(CAUSES) + ["keyed_art"])
            _txt(t, f"saw {r['answer']} read {r['best']}", y=22, col=(0, 255, 255))
            tiles.append(t)
        g = grid(tiles)
        if g is not None:
            p = OUT / "labels_wrong.png"
            cv2.imwrite(str(p), g)
            written.append(p)
    for p in written:
        print(p)


def main() -> int:
    lower_priority()
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("cmd", choices=("collect", "labels", "report", "sheets"))
    ap_.add_argument("sids", nargs="*")
    ap_.add_argument("--windows", type=int, default=4)
    ap_.add_argument("--frames", type=int, default=60)
    ap_.add_argument("--record", action="store_true")
    a = ap_.parse_args()
    if a.cmd == "collect":
        collect_runs(a.sids or match_sessions(), a.windows, a.frames)
    elif a.cmd == "labels":
        labels()
    elif a.cmd == "report":
        report(a.record)
    else:
        sheets()
    return 0


if __name__ == "__main__":
    sys.exit(main())
