r"""Does the viewcone light the teardrop's tip? A test of the player's hypothesis.

    .\.venv\Scripts\python.exe prototypes\tip_cone.py [--record] [--sheet]

The player saw each icon's tip drawn lighter than its rim
[domain:minimap/icon-tip-highlight], faint on enemies
[domain:minimap/enemy-rim-faint-at-small-widget], and then proposed
(2026-09-29): "The vision cone may be accentuating the brightness even more on
allies". Teammates and the self cast a cone from near the icon's centre along
the facing [domain:minimap/cone-origin-near-centre]; enemies cast none. If the
icon art is see-through, or its antialiased tip blends with the lit floor
beyond it, the cone adds light where the tip is, and `tip_highlight.py`
(which read allies to 7 degrees and failed on enemies) partly reads the cone.

**Zones come from the shape, not the hue.** Each labelled icon's centre is the
owner's teardrop fit (`teardrop.fit_icon` / `fit_teardrop`), its facing the
player's label, and its silhouette `teardrop.render` at the class radii scaled
by `minimap.widget_scale`. Signed distance `d` to that silhouette splits the
pixels: TIP (inside, the outer half of the lobe), RIM (inside, 100 degrees or
more from the facing: outside the cone's half-angle and the lobe's tangent),
LOBE_INT (at least a pixel inside the lobe), BG_FWD (1-4 px outside, within 40
degrees of the facing: the cone just past the tip) and BG_BACK (the same band
130 degrees or more away). Brightness is grey luma.

**The tests.** `tip_excess` is TIP's median less RIM's; `cone_lift` BG_FWD's
less BG_BACK's. Rays along the label, its reverse and both perpendiculars give
the tip's peak, the rims' peaks and the cone just beyond the apex (C1). The
lobe's transparency is the within-icon slope of LOBE_INT pixels on the baked
static beneath them, walls and floor alike (C2); the cone's share of the tip
excess is that slope times the lift under the tip. Cone-absent controls are
chosen before any brightness is read, by the owner's raycast
(`cone.raycast` over the baked passable): the cone reaches under
`CTRL_REACH` of BG_FWD (C3). Enemies carry no cone (C4). Predictions are the
`tip-cone-test-20260929` rows of `notes/predictions.jsonl`. Crop cache only.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tip_highlight as th  # noqa: E402
from reticle import cone, lighting, teardrop as td  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "tip-cone-test-0.1.0"
TIP_FRAC = 0.5          # TIP: the outer half of the lobe beyond the ring
RIM_DEG = 100.0         # RIM: this far or further from the facing
FWD_DEG, BACK_DEG = 40.0, 130.0
BAND = (1.0, 4.0)       # BG bands, px outside the silhouette at scale 1.0
CTRL_REACH = 0.2        # a cone-absent control: the raycast reaches under this share of BG_FWD
MARGIN = 3.0            # C1: grey levels the tip must clear
INT_PX = 0.5            # tip_int / rim_int: this far inside the silhouette at scale 1.0
OUT = th.sem.STORE / "analysis" / "tip-cone-20260929"

_SESS: dict = {}


def _sess(sid):
    if sid not in _SESS:
        import team_vision_eval as tve
        _SESS[sid] = tve.Sess(sid)
    return _SESS[sid]


th._sess = _sess     # one session object per session, shared with the loaders


def radii(cls):
    if cls == "self":
        return td.R_IN, td.R_OUT, td.L
    c = td.ICON_CLASSES[cls]
    return c.r_in, c.r_out, c.L


def fit_centre(crop, cls, cx0, cy0, s):
    f = (td.fit_teardrop(crop, cx0, cy0, scale=s) if cls == "self"
         else td.fit_icon(crop, cls, cx0, cy0, scale=s))
    return f


def _bilinear(img, x, y):
    return cv2.remap(img, np.float32(x)[None, :], np.float32(y)[None, :], cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)[0]


def measure(crop, cls, cx, cy, deg, sess) -> dict:
    """Zones, rays and controls for one icon at centre `(cx, cy)` facing `deg` (image degrees)."""
    s = widget_scale(crop.shape[1])
    r_in, r_out, L = (v * s for v in radii(cls))
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = g.shape
    R = int(math.ceil(L + BAND[1] * s + 3))
    x0, x1, y0, y1 = max(0, int(cx) - R), min(w, int(cx) + R + 2), max(0, int(cy) - R), min(h, int(cy) + R + 2)
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    dx, dy = xx - cx, yy - cy
    th_ = math.radians(deg)
    big = 1.0e4
    d = (0.5 - td.render(dx, dy, th_, r_in, r_out, L, big)) * big       # signed distance, <0 inside
    # Outside the teardrop's OUTER edge: the portrait hole is outside `d` too, and never background.
    d_out = (0.5 - td.render(dx, dy, th_, 0.0, r_out, L, big)) * big
    u = dx * math.cos(th_) + dy * math.sin(th_)
    rho = np.hypot(dx, dy)
    ang = np.degrees(np.arccos(np.clip(u / np.maximum(rho, 1e-6), -1, 1)))
    inside = d <= 0
    z = {
        "tip": inside & (u >= r_out + TIP_FRAC * (L - r_out)),
        "rim": inside & (ang >= RIM_DEG),
        "lobe_int": (d <= -1.0 * s) & (u > r_out),
        # the same zones kept off the silhouette's edge, where no background can blend in
        "tip_int": (d <= -INT_PX * s) & (u >= r_out + TIP_FRAC * (L - r_out)),
        "rim_int": (d <= -INT_PX * s) & (ang >= RIM_DEG),
        "bg_fwd": (d_out >= BAND[0] * s) & (d_out <= BAND[1] * s) & (ang <= FWD_DEG),
        "bg_back": (d_out >= BAND[0] * s) & (d_out <= BAND[1] * s) & (ang >= BACK_DEG),
    }
    sub = g[y0:y1, x0:x1]
    med = {k: (float(np.median(sub[m])) if m.any() else None) for k, m in z.items()}
    n = {k: int(m.sum()) for k, m in z.items()}
    out = {"n_" + k: v for k, v in n.items()}
    out.update({"y_" + k: v for k, v in med.items()})
    out["tip_excess"] = None if med["tip"] is None or med["rim"] is None else med["tip"] - med["rim"]
    out["cone_lift"] = None if med["bg_fwd"] is None or med["bg_back"] is None else med["bg_fwd"] - med["bg_back"]
    out["int_excess"] = (None if med["tip_int"] is None or med["rim_int"] is None
                         else med["tip_int"] - med["rim_int"])
    out["lobe_excess"] = (None if med["lobe_int"] is None or med["rim_int"] is None
                          else med["lobe_int"] - med["rim_int"])
    out["tip_minus_fwd"] = None if med["tip"] is None or med["bg_fwd"] is None else med["tip"] - med["bg_fwd"]

    # Rays (C1).
    step = 0.5
    t = np.arange(0.0, L + 6.0 * s, step)

    def ray(a_deg):
        a = math.radians(a_deg)
        return _bilinear(g, cx + t * math.cos(a), cy + t * math.sin(a))
    fwd, rev, p1, p2 = ray(deg), ray(deg + 180), ray(deg + 90), ray(deg - 90)
    sel = lambda lo, hi: (t >= lo) & (t <= hi)  # noqa: E731
    out["ray_tip_peak"] = float(fwd[sel(r_out, L)].max())
    out["ray_rim_rev"] = float(rev[sel(r_in, r_out + 0.5 * s)].max())
    out["ray_rim_perp"] = float(0.5 * (p1[sel(r_in, r_out + 0.5 * s)].max() + p2[sel(r_in, r_out + 0.5 * s)].max()))
    out["ray_cone_beyond"] = float(np.median(fwd[sel(L + 2 * s, L + 5 * s)]))
    out["ray_bg_rev"] = float(np.median(rev[sel(r_out + 2 * s, r_out + 5 * s)]))
    out["c1_intrinsic"] = bool(out["ray_tip_peak"] > max(out["ray_rim_rev"], out["ray_cone_beyond"]) + MARGIN)
    out["_rays"] = {"t": t, "fwd": fwd, "rev": rev, "p1": p1, "p2": p2}

    # The baked static under the lobe (C2) and the reference lift under the tip.
    inp = sess.inputs
    st = cv2.cvtColor(inp.static, cv2.COLOR_BGR2GRAY).astype(np.float32)[y0:y1, x0:x1]
    m = z["lobe_int"]
    out["_lobe_pairs"] = (sub[m].astype(np.float64), st[m].astype(np.float64))
    lit_raw = lighting.raw_lit(crop, inp.light)[y0:y1, x0:x1]
    known = inp.light.known[y0:y1, x0:x1]
    kf = z["bg_fwd"] & known
    kb = z["bg_back"] & known
    out["lit_fwd"] = float(lit_raw[kf].mean()) if kf.any() else None
    out["known_fwd"] = float(kf.sum() / max(1, z["bg_fwd"].sum()))
    out["lit_back"] = float(lit_raw[kb].mean()) if kb.any() else None
    kt = z["tip"] & known
    out["ref_lift_tip"] = float(np.median((inp.light.hi - inp.light.lo)[y0:y1, x0:x1][kt])) if kt.any() else None

    # The owner's raycast along the label: does the cone exist past the tip? (C3, a priori)
    cm = cone.raycast(inp.passable, cx, cy, deg)[y0:y1, x0:x1]
    out["reach_fwd"] = float(cm[z["bg_fwd"]].mean()) if z["bg_fwd"].any() else None
    out["_zones"] = {k: (np.nonzero(v)[1] + x0, np.nonzero(v)[0] + y0) for k, v in z.items()}
    return out


def within_slope(pairs) -> tuple[float | None, int]:
    """Pooled within-icon slope of observed luma on the static beneath it (icon means removed)."""
    xs, ys = [], []
    for obs, st in pairs:
        if len(obs) < 3 or np.ptp(st) < 1:
            continue
        xs.append(st - st.mean())
        ys.append(obs - obs.mean())
    if not xs:
        return None, 0
    x, y = np.concatenate(xs), np.concatenate(ys)
    return float((x * y).sum() / max((x * x).sum(), 1e-9)), len(xs)


def line_diff(pairs, min_contrast=30.0) -> tuple[float | None, float | None, int]:
    """Per icon with lobe pixels over a baked line: observed and static (line - floor), medians."""
    obs_d, st_d = [], []
    for obs, st in pairs:
        line = st >= np.median(st) + min_contrast
        if line.sum() < 1 or (~line).sum() < 3:
            continue
        obs_d.append(float(np.median(obs[line]) - np.median(obs[~line])))
        st_d.append(float(np.median(st[line]) - np.median(st[~line])))
    if not obs_d:
        return None, None, 0
    return float(np.median(obs_d)), float(np.median(st_d)), len(obs_d)


def perm_p(a, b, n=4000, seed=0):
    """Two-sided permutation p for a difference in medians; None under 3 per side."""
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if len(a) < 3 or len(b) < 3:
        return None
    obs = abs(np.median(a) - np.median(b))
    allv = np.asarray(a + b, dtype=float)
    rng = np.random.default_rng(seed)
    hit = 0
    for _ in range(n):
        p = rng.permutation(allv)
        hit += abs(np.median(p[:len(a)]) - np.median(p[len(a):])) >= obs - 1e-9
    return float((hit + 1) / (n + 1))


def _md(v):
    v = [x for x in v if x is not None]
    return float(np.median(v)) if v else None


def summarise(items) -> dict:
    ok = [m for m in items if m.get("tip_excess") is not None]
    out = {"n": len(ok), "n_all": len(items)}
    for k in ("tip_excess", "int_excess", "lobe_excess", "n_tip_int", "n_rim_int", "cone_lift", "tip_minus_fwd",
              "y_tip", "y_rim", "y_tip_int", "y_rim_int", "y_lobe_int", "y_bg_fwd", "y_bg_back",
              "ray_tip_peak", "ray_rim_rev", "ray_rim_perp", "ray_cone_beyond", "ray_bg_rev",
              "lit_fwd", "lit_back", "ref_lift_tip", "reach_fwd", "hl_body_frac", "hl_edge_frac",
              "hl_outside_frac"):
        out["median_" + k] = _md([m.get(k) for m in ok])
    out["c1_intrinsic_frac"] = float(np.mean([m["c1_intrinsic"] for m in ok])) if ok else None
    beta, nb = within_slope([m["_lobe_pairs"] for m in ok])
    out["lobe_slope_on_static"], out["lobe_slope_icons"] = beta, nb
    ld, sd, nl = line_diff([m["_lobe_pairs"] for m in ok])
    out["line_obs_diff"], out["line_static_diff"], out["line_icons"] = ld, sd, nl
    # across items: lobe interior level against the cone just past it
    a = [(np.median(m["_lobe_pairs"][0]), m["y_bg_fwd"]) for m in ok
         if len(m["_lobe_pairs"][0]) and m.get("y_bg_fwd") is not None]
    if len(a) >= 5:
        A = np.asarray(a)
        out["across_slope_lobe_on_fwd"] = float(np.polyfit(A[:, 1], A[:, 0], 1)[0])
    # the cone's share of the tip excess, if the lobe were as see-through as `beta` says
    lift = _md([None if m.get("ref_lift_tip") is None or m.get("lit_fwd") is None
                else m["ref_lift_tip"] * m["lit_fwd"] for m in ok])
    out["median_lift_under_tip"] = lift
    if beta is not None and lift is not None and out["median_tip_excess"]:
        out["cone_share"] = float(max(beta, 0.0) * lift / out["median_tip_excess"])
    # C3: controls chosen by the raycast, before brightness
    ctrl = [m for m in ok if m.get("reach_fwd") is not None and m["reach_fwd"] < CTRL_REACH]
    rest = [m for m in ok if m.get("reach_fwd") is not None and m["reach_fwd"] >= CTRL_REACH]
    out["n_ctrl"], out["n_cone"] = len(ctrl), len(rest)
    for k in ("tip_excess", "int_excess", "lobe_excess", "y_tip", "y_lobe_int", "y_rim", "y_bg_fwd", "y_bg_back"):
        out[f"ctrl_median_{k}"] = _md([m[k] for m in ctrl])
        out[f"cone_median_{k}"] = _md([m[k] for m in rest])
    out["ctrl_perm_p"] = perm_p([m["tip_excess"] for m in ctrl], [m["tip_excess"] for m in rest])
    out["ctrl_perm_p_int"] = perm_p([m["int_excess"] for m in ctrl], [m["int_excess"] for m in rest])
    # the same split by the drawn light past the tip (an observation, not a priori)
    dark = [m for m in ok if m.get("lit_fwd") is not None and m["lit_fwd"] < CTRL_REACH]
    litm = [m for m in ok if m.get("lit_fwd") is not None and m["lit_fwd"] >= 0.5]
    out["n_unlit_fwd"], out["n_lit_fwd"] = len(dark), len(litm)
    out["unlit_fwd_median_tip_excess"] = _md([m["tip_excess"] for m in dark])
    out["lit_fwd_median_tip_excess"] = _md([m["tip_excess"] for m in litm])
    if len(ok) >= 5:
        A = np.asarray([(m["cone_lift"], m["tip_excess"]) for m in ok if m["cone_lift"] is not None])
        out["slope_excess_on_cone_lift"] = float(np.polyfit(A[:, 0], A[:, 1], 1)[0])
        out["corr_excess_cone_lift"] = float(np.corrcoef(A[:, 0], A[:, 1])[0, 1])
        # decomposed: does the tip follow the background past it, and the rim the background behind it?
        T = np.asarray([(m["y_bg_fwd"], m["y_tip"]) for m in ok if m["y_bg_fwd"] is not None])
        Rr = np.asarray([(m["y_bg_back"], m["y_rim"]) for m in ok if m["y_bg_back"] is not None])
        out["slope_tip_on_fwd"] = float(np.polyfit(T[:, 0], T[:, 1], 1)[0])
        out["slope_rim_on_back"] = float(np.polyfit(Rr[:, 0], Rr[:, 1], 1)[0])
        Ti = np.asarray([(m["y_bg_fwd"], m["y_tip_int"]) for m in ok
                         if m["y_bg_fwd"] is not None and m["y_tip_int"] is not None])
        if len(Ti) >= 5:
            out["slope_tip_int_on_fwd"] = float(np.polyfit(Ti[:, 0], Ti[:, 1], 1)[0])
        # On floor only (the drawn light is defined there): the tip against the lit share past it.
        fl = [m for m in ok if m.get("lit_fwd") is not None and m["known_fwd"] >= 0.7]
        out["n_floor_fwd"] = len(fl)
        if len(fl) >= 5 and np.ptp([m["lit_fwd"] for m in fl]) > 0.3:
            X = np.asarray([m["lit_fwd"] for m in fl])
            for name, key in (("tip", "y_tip"), ("tip_int", "y_tip_int"), ("lobe_int", "y_lobe_int"),
                              ("rim", "y_rim"), ("excess", "tip_excess")):
                Y = np.asarray([m[key] if m[key] is not None else np.nan for m in fl])
                k = ~np.isnan(Y)
                out[f"floor_{name}_per_lit"] = float(np.polyfit(X[k], Y[k], 1)[0])
            if out["median_tip_excess"]:
                out["cone_share_floor"] = float(max(out["floor_tip_per_lit"], 0.0) * float(np.median(X))
                                                / out["median_tip_excess"])
        if lift is not None and out["median_tip_excess"]:
            out["cone_share_across"] =float(max(out["slope_tip_on_fwd"], 0.0) * lift / out["median_tip_excess"])
    return out


# ---------------------------------------------------------------- items

def labelled(store):
    """`{group: [item]}`, each item `{session, t_ms, cls, deg, deg_src, det, crop, width}`."""
    groups = {}
    e6 = th.e6_scored(th.e6_rows(store))
    for cls in ("ally", "enemy"):
        groups[f"{cls}-465"] = [dict(session=r["session"], t_ms=r["t_ms"], cls=cls, deg=r["label_deg"],
                                     deg_src="label", det=(r["det_cx"], r["det_cy"]), crop=r["_crop"])
                                for r in e6 if r["cls"] == cls]
    ss = th.self_scored(th.self_rows(store))
    groups["self-465"] = [dict(session=r["session"], t_ms=r["t_ms"], cls="self", deg=r["label_deg"],
                               deg_src="label", det=(r["det_cx"], r["det_cy"]), crop=r["_crop"]) for r in ss]
    r331, all331 = th.rows_331(store)
    groups["ally-331"] = [dict(session=r["session"], t_ms=r["t_ms"], cls="ally", deg=r["label_deg"],
                               deg_src="label", det=(r["det_cx"], r["det_cy"]), crop=r["_crop"])
                          for r in th.scored_331(r331)]
    # 331 px enemies: no labels; the enemy detector on the manifest's frames, faced by the owner's fit
    import icon_teardrop as it_
    en, seen = [], set()
    for m in all331:
        k = (m["session"], float(m["t_ms"]))
        if k in seen:
            continue
        seen.add(k)
        crop = m["_crop"]
        s = widget_scale(crop.shape[1])
        for dd in it_.detections(crop, "enemy", _sess(m["session"])):
            f = td.fit_icon(crop, "enemy", dd["cx"], dd["cy"], scale=s)
            if f.get("read"):
                en.append(dict(session=m["session"], t_ms=m["t_ms"], cls="enemy", deg=f["deg"],
                               deg_src="teardrop", det=(dd["cx"], dd["cy"]), crop=crop))
    groups["enemy-331"] = en
    return groups


def run_group(items):
    out, skipped = [], 0
    for it in items:
        crop = it["crop"]
        s = widget_scale(crop.shape[1])
        f = fit_centre(crop, it["cls"], *it["det"], s)
        if "x" not in f:
            skipped += 1
            continue
        m = measure(crop, it["cls"], f["x"], f["y"], it["deg"], _sess(it["session"]))
        # Where the tip-highlight reader's kept pixels lie: the lobe's body or its edge?
        hl = th.read(crop, it["cls"], *it["det"], s)
        if hl["pts"]:
            r_in, r_out, L = (v * s for v in radii(it["cls"]))
            P = np.asarray(hl["pts"], dtype=np.float64)
            dd = (0.5 - td.render(P[:, 0] - f["x"], P[:, 1] - f["y"], math.radians(it["deg"]),
                                  r_in, r_out, L, 1.0e4)) * 1.0e4
            m["hl_body_frac"] = float(np.mean(dd <= -INT_PX * s))
            m["hl_edge_frac"] = float(np.mean(np.abs(dd) < INT_PX * s))
            m["hl_outside_frac"] = float(np.mean(dd >= INT_PX * s))
        m.update(session=it["session"], t_ms=it["t_ms"], cls=it["cls"], deg=it["deg"], cx=f["x"], cy=f["y"],
                 width=crop.shape[1], _crop=crop, fit_read=bool(f.get("read")))
        out.append(m)
    return out, skipped


# ---------------------------------------------------------------- the sheet

COL = {"lobe_int": (255, 255, 255), "tip": (255, 0, 255), "rim": (255, 128, 0), "bg_fwd": (0, 255, 255),
       "bg_back": (0, 128, 255)}


def tile(m, zoom=None, half=None):
    s = widget_scale(m["width"])
    half = half or int(round(26 * s))
    zoom = zoom or int(round(9 / s))
    crop, cx, cy = m["_crop"], m["cx"], m["cy"]
    ix, iy = int(round(cx)), int(round(cy))
    p = np.zeros((2 * half + 1, 2 * half + 1, 3), np.uint8)
    y0, x0 = iy - half, ix - half
    sub = crop[max(0, y0):iy + half + 1, max(0, x0):ix + half + 1]
    p[max(0, -y0):max(0, -y0) + sub.shape[0], max(0, -x0):max(0, -x0) + sub.shape[1]] = sub
    raw = cv2.resize(p, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    ann = raw.copy()

    def to(x, y):
        return (int((x - x0 + 0.5) * zoom), int((y - y0 + 0.5) * zoom))
    for k, c in COL.items():
        xs, ys = m["_zones"][k]
        for x, y in zip(xs, ys):
            cv2.circle(ann, to(x, y), max(1, zoom // 6), c, -1)
    t = m["_rays"]["t"]
    for a, c in ((m["deg"], (0, 255, 0)), (m["deg"] + 180, (200, 200, 200)), (m["deg"] + 90, (120, 120, 120)),
                 (m["deg"] - 90, (120, 120, 120))):
        r = math.radians(a)
        e = (cx + t[-1] * math.cos(r), cy + t[-1] * math.sin(r))
        cv2.line(ann, to(cx, cy), to(*e), c, 1)
    lab = f"{m['session'][:4]} {m['t_ms'] / 1000:.1f}s {m['cls']} {m['width']}px"
    cv2.putText(raw, lab, (3, 13), 0, 0.42, (255, 255, 255), 1)
    fmt = lambda v: "-" if v is None else f"{v:+.0f}"  # noqa: E731
    cv2.putText(ann, f"exc {fmt(m['tip_excess'])} lift {fmt(m['cone_lift'])}", (3, 13), 0, 0.42, (255, 255, 255), 1)
    rf = m.get("reach_fwd")
    cv2.putText(ann, f"reach {'-' if rf is None else f'{rf:.2f}'} {'INTR' if m['c1_intrinsic'] else 'mix'}",
                (3, ann.shape[0] - 5), 0, 0.42, (0, 255, 0) if m["c1_intrinsic"] else (0, 0, 255), 1)
    return np.hstack([raw, ann, np.zeros((raw.shape[0], 4, 3), np.uint8)])


def sheet(results, path, per_group=6, per_row=3):
    blocks = []
    for name, ms in results.items():
        ms = [m for m in ms if m.get("tip_excess") is not None]
        if not ms:
            continue
        ctrl = [m for m in ms if m.get("reach_fwd") is not None and m["reach_fwd"] < CTRL_REACH]
        rest = [m for m in ms if m not in ctrl]
        pick = ctrl[:2] + rest[::max(1, len(rest) // max(1, per_group - len(ctrl[:2])))][:per_group - len(ctrl[:2])]
        tiles = [tile(m) for m in pick]
        H = max(t_.shape[0] for t_ in tiles)
        W = max(t_.shape[1] for t_ in tiles)
        tiles = [cv2.copyMakeBorder(t_, 0, H - t_.shape[0], 0, W - t_.shape[1], cv2.BORDER_CONSTANT) for t_ in tiles]
        while len(tiles) % per_row:
            tiles.append(np.zeros_like(tiles[0]))
        blocks.append(np.vstack([np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)]))
    W = max(b.shape[1] for b in blocks)
    blocks = [cv2.copyMakeBorder(b, 0, 6, 0, W - b.shape[1], cv2.BORDER_CONSTANT, value=(40, 40, 40)) for b in blocks]
    grid = np.vstack(blocks)
    key = np.zeros((22, W, 3), np.uint8)
    cv2.putText(key, "left raw | right: lobe body white, tip magenta, rim blue, cone-past-tip yellow, back bg orange; "
                "label ray green, reverse light grey, perpendiculars grey", (4, 15), 0, 0.45, (255, 255, 255), 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack([key, grid]))
    return path


def line_sheet(results, path, per_group=3):
    """Lobes that lie over a baked line: the crop beside the baked static, for the transparency test."""
    tiles = []
    for name, ms in results.items():
        picked = 0
        for m in ms:
            obs, st = m["_lobe_pairs"]
            if len(st) < 4 or (st >= np.median(st) + 30).sum() < 1 or picked >= per_group:
                continue
            s = widget_scale(m["width"])
            half, zoom = int(round(24 * s)), int(round(10 / s))
            ix, iy = int(round(m["cx"])), int(round(m["cy"]))
            row = []
            for img in (m["_crop"], _sess(m["session"]).inputs.static):
                p = np.zeros((2 * half + 1, 2 * half + 1, 3), np.uint8)
                y0, x0 = iy - half, ix - half
                sub = img[max(0, y0):iy + half + 1, max(0, x0):ix + half + 1]
                p[max(0, -y0):max(0, -y0) + sub.shape[0], max(0, -x0):max(0, -x0) + sub.shape[1]] = sub
                row.append(cv2.resize(p, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST))
            t_ = np.hstack(row)
            cv2.putText(t_, f"{name} {m['session'][:4]} {m['t_ms'] / 1000:.1f}s: crop | baked static", (3, 14), 0,
                        0.45, (255, 255, 255), 1)
            tiles.append(t_)
            picked += 1
    if not tiles:
        return path
    W = max(t_.shape[1] for t_ in tiles)
    tiles = [cv2.copyMakeBorder(t_, 0, 4, 0, W - t_.shape[1], cv2.BORDER_CONSTANT) for t_ in tiles]
    per_row = 3
    while len(tiles) % per_row:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)])
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), grid)
    return path


def profiles_plot(results, path):
    """Median luma along the label ray and its reverse, per group, against radius in r_out units."""
    rows = []
    for name, ms in results.items():
        ms = [m for m in ms if m.get("tip_excess") is not None]
        if not ms:
            continue
        s = widget_scale(ms[0]["width"])
        _, r_out, L = (v * s for v in radii(ms[0]["cls"]))
        grid = np.linspace(0, 1.6, 65)
        fw = np.median([np.interp(grid * L, m["_rays"]["t"], m["_rays"]["fwd"]) for m in ms], axis=0)
        rv = np.median([np.interp(grid * L, m["_rays"]["t"], m["_rays"]["rev"]) for m in ms], axis=0)
        rows.append((name, grid, fw, rv, r_out / L))
    return rows


# ---------------------------------------------------------------- main

def _clean(d):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items() if v is not None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true", help="one metrics row per group (series tip_cone_test)")
    ap.add_argument("--sheet", action="store_true", help="write the sheet to " + str(OUT))
    args = ap.parse_args(argv)
    th._idle()
    store = th.sem.STORE
    groups = labelled(store)
    results, summ = {}, {}
    for name, items in groups.items():
        ms, skipped = run_group(items)
        results[name] = ms
        sm = summarise(ms)
        sm["unfit"] = skipped
        summ[name] = sm
        print(f"\n== {name}: {sm['n']} measured of {len(items)} ({skipped} unfit)")
        for k, v in sm.items():
            if v is not None and k not in ("n",):
                print(f"   {k:32s} {v:.3f}" if isinstance(v, float) else f"   {k:32s} {v}")
    print("\n== median luma along the label ray (fwd) and its reverse (rev), radius in units of L")
    for name, grid, fw, rv, ro in profiles_plot(results, None):
        idx = [np.argmin(abs(grid - x)) for x in (0.3, ro, 0.75, 0.9, 1.0, 1.15, 1.3, 1.5)]
        print(f"   {name:10s} r/L " + " ".join(f"{grid[i]:5.2f}" for i in idx))
        print(f"   {'':10s} fwd " + " ".join(f"{fw[i]:5.0f}" for i in idx))
        print(f"   {'':10s} rev " + " ".join(f"{rv[i]:5.0f}" for i in idx))
    if args.record:
        from reticle import metrics
        deps = {"prototype": VERSION, "teardrop": td.ICON_TEARDROP_VERSION, "self_teardrop": td.TEARDROP_VERSION,
                "lighting": lighting.LIGHTING_VERSION, "tip_frac": TIP_FRAC, "rim_deg": RIM_DEG,
                "fwd_deg": FWD_DEG, "back_deg": BACK_DEG, "band": list(BAND), "ctrl_reach": CTRL_REACH}
        for name, sm in summ.items():
            sids = sorted({m["session"] for m in results[name]})
            if not sids:
                continue
            metrics.record("tip_cone_test", part=name, session="+".join(sids), values=_clean(sm), deps=deps,
                           context={"widget_px": results[name][0]["width"],
                                    "facing": "label" if not name.startswith("enemy-331") else "teardrop"})
        print("recorded tip_cone_test rows")
    if args.sheet:
        print("wrote", sheet(results, OUT / "sheet.png"))
        print("wrote", line_sheet(results, OUT / "sheet_lobe_on_line.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
