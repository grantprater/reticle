r"""An icon's facing from two witnesses of one facing: the icon's own readers and the drawn cone light.

    .\.venv\Scripts\python.exe prototypes\facing_fusion.py [--record] [--sheet] [--json PATH]

The player (2026-09-29), on E11's finding that `team-vision-0.4.0` chose the
ring fit's lobe by the light and then scored it against that light: "That
was to some extent intended, though not in precisely that way. The vision
cone was meant to inform the ally icon orientation and vice versa". So the
drawn light and the icon's orientation are two witnesses of one facing, and
each should inform the other. This prototype fuses them without the circular
scoring E11 found: the light enters the facing here, and the facing is scored
only against the player's labels.

**The prior** (`prior`) is the icon's own readers, which read the icon's
pixels and no light:

- the teardrop (`reticle.teardrop.fit_icon`, the owner, at
  `minimap.widget_scale`; the self teardrop through the same function with
  the self radii and key): its NCC at every `GRID_DEG` facing about its
  fitted centre, `KAPPA_TD` nats per unit of NCC. So the teardrop's own
  `margin` sets how firmly it holds its lobe;
- the tip highlight (`prototypes/tip_highlight.read`, `tip-highlight-0.1.0`,
  read at the class detector's centre, so no teardrop output enters it): a
  von Mises of spread `HL_SIGMA_DEG` about its angle, mixed with `HL_OUT`
  uniform mass for its stack failures (a neighbour's rim lends a second tip).
  The highlight reads the same lobe as the teardrop, by brightness rather
  than shape; they are not independent, so its weight is modest.

**The evidence** (`light_loglik`) is the drawn light the cone at each facing
would explain, read so that the icon cannot score itself:

- the light is `lighting.raw_lit` on known floor within `cone_origin.R_EVAL`
  px (scaled) of the icon, joined to the icon: lit components that touch a
  `cone_origin.JOIN_PX` band round its footprint (E4's joined witness);
- EXCLUDED: every team icon's footprint (a disc of the apex's reach, grown
  by `cone_origin.PAD`; no facing enters it), which E11 found made about a
  third of the old chooser's lit pixels; the cones the neighbouring team
  icons cast along their own teardrop facing (their prior, never this
  icon's fused answer); pixels nearer a team icon whose teardrop gives no
  facing than to this icon, whose light cannot be attributed; and lit pixels
  not joined to this icon, which are neither its light nor its darkness;
- each cone is `cone.raycast` from the teardrop's centre with the geometry's
  walls and boxes (`team_vision.load_inputs`' `passable`), so light a wall
  hides is not asked for;
- the cone is split into `N_SECTORS` angular sectors, the unit of spatial
  correlation (one wall shades a whole sector); a sector with at least
  `SECTOR_MIN_PX` comparable pixels contributes its lit share `f` as
  `TEMPER * (f log(P_LIT/P_BG) + (1-f) log((1-P_LIT)/(1-P_BG)))`: the
  Bernoulli log-likelihood ratio of "this cone is drawn here" against
  background light, tempered because adjacent sectors still share blobs.

**The posterior** is prior plus evidence on the `GRID_DEG` grid. The fusion
flips the teardrop's lobe only where the posterior mass on the far half
(over 90 degrees from the teardrop) exceeds a half, and then reports the
posterior's circular mean within `REFINE_DEG` of the far half's peak;
otherwise it keeps the teardrop's angle. `fusion_adjust` also moves the
angle within the kept lobe (the same mean round the global peak), reported
beside it. Every item stores its lobe log-odds per witness and every
disagreement between them, and the fused facing declares `rests_on` the
light it used. A teardrop that refuses stays unread (`null` with its
reason); the fusion does not guess a facing it did not have.

**The constants were set before any label was scored** and are logged with
the predictions (`facing-fusion-20260929` rows of the store's
`notes/predictions.jsonl`): `P_LIT` 0.6 and `P_BG` 0.2 soften E11's
label-aimed and reversed cone precision (0.721 and 0.137 on the 331 px
labels, a pooled rate, so the 331 px set is not wholly independent of
them); `TEMPER` 1/3 counts a 12-sector cone as four independent looks.

**The other direction, measured only** (`missing_cones`): on the labelled
frames, the joined team light that no team cone explains (cast along the
fused facing for the labelled icon and the teardrop's elsewhere), split by
whether its nearest team icon has a facing. Light beside an icon with no
facing is a candidate for a missing cone.

**Scoring** is on the player's labels only, never on the light: E6's ally
labels (465 px), the Lotus self labels (5822b6646448, with the Ascent
controls apart) and `ally_facing_331_20260929` (331 px), with
`tip_highlight`'s filters. Every reader is recomputed from the crop cache at
the labelled frames; the 331 px manifest's frozen readings are compared,
not used. Arms: `teardrop`, `highlight`, `prior` (teardrop and highlight, no
light), `light_lobe` (the teardrop's axis, lobe by the excluded light alone),
`light_lobe_raw` (the same by `cone.resolve_lobe` on `lighting.lit_mask`,
the icon's own pixels counted: E10's `td-lobe`), `fusion_nohl` (teardrop and
light), `fusion` and `fusion_adjust`. `--record` writes one `metrics` row per
set (series `facing_fusion_eval`); `--sheet` writes the decision sheets to
the store's `analysis/facing-fusion-20260929/`. Crop cache only; no decode.
Not wired: nothing in `reticle/` reads it.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402
import cone_origin as co  # noqa: E402
import icon_facing_eval as ife  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import label_icon_facing as lif  # noqa: E402
import label_self_facing as lsf  # noqa: E402
import teardrop_tip as tt  # noqa: E402
import tip_highlight as th  # noqa: E402
from reticle import cone, lighting  # noqa: E402
from reticle import teardrop as td  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "facing-fusion-0.1.0"
GRID_DEG = 5.0
KAPPA_TD = 20.0        # nats per unit of teardrop NCC
HL_SIGMA_DEG = 12.0    # the highlight's spread where it reads the right tip
HL_OUT = 0.15          # the highlight's uniform outlier mass (stacks)
P_LIT = 0.6            # a drawn cone's comparable pixels read lit
P_BG = 0.2             # background light elsewhere
N_SECTORS = 12
TEMPER = 1.0 / 3.0
SECTOR_MIN_PX = 5.0    # comparable pixels per sector at widget scale 1.0 (scaled by area)
REFINE_DEG = 20.0
OUT = sem.STORE / "analysis" / "facing-fusion-20260929"
GRID = np.arange(0.0, 360.0, GRID_DEG)
SELF_CLASS = td.IconClass("self", td.yellowness, td.R_IN, td.R_OUT, td.L, td.MIN_NCC, 0.0, 0.0)
ARMS = ("teardrop", "highlight", "prior", "light_lobe", "light_lobe_raw", "fusion_nohl", "fusion",
        "fusion_adjust")
SESSION_PATHS = {
    "5822b6646448": "C:/Users/grant/Videos/2026-08-26 12-38-38.mp4",
    "a06f04a0059f": "C:/Users/grant/Videos/2026-08-26 09-56-37.mp4",
    "e78e75b2d191": "C:/Users/grant/Videos/2026-09-03 19-16-07.mp4",
    "c40d950031bb": "C:/Users/grant/Videos/2026-08-24 18-27-17.mp4",
    "223d636bf8d2": "C:/Users/grant/Videos/2026-08-23 20-09-01.mp4",
}


def _lse(v) -> float:
    v = np.asarray(v, float)
    m = float(v.max())
    return m + math.log(float(np.exp(v - m).sum()))


# ---------------------------------------------------------------- the icon's own readers

def icon_class(cls: str) -> td.IconClass:
    return SELF_CLASS if cls == "self" else td.ICON_CLASSES[cls]


def fit(crop, cls: str, cx: float, cy: float, sc: float, key=None) -> dict:
    """The owner's teardrop at the widget's scale, with its NCC at every `GRID` facing about its centre."""
    c = icon_class(cls)
    key = c.key(crop) if key is None else key
    f = td.fit_icon(None, c, cx, cy, scale=sc, key=key)
    if "x" not in f:
        return f
    r_in, r_out, L_, edge = c.r_in * sc, c.r_out * sc, c.L * sc, td.EDGE * sc
    px, py, obs = td._window(key, f["x"], f["y"], L_ + td.WINDOW * sc)
    ths = np.radians(GRID)
    f["profile"] = td._correlation(obs, td.render(px[None, :] - f["x"], py[None, :] - f["y"], ths[:, None],
                                                  r_in, r_out, L_, edge)).astype(float)
    return f


def team_icons(s, crop, sc: float) -> list[dict]:
    """Every team icon in the frame: `{"role", "cx", "cy", "x", "y", "deg"|None, "fit"}`.

    The self icon from its best detection, each ally from `icon_teardrop.detections`;
    `x`, `y` is the teardrop's centre where it reads, else the detector's.
    """
    out = []
    det = tt.self_start(crop, s.floor)
    if det is not None:
        f = fit(crop, "self", det["cx"], det["cy"], sc)
        out.append(_icon("self", det, f))
    key = td.tealness(crop)
    for d in it_.detections(crop, "ally", s):
        out.append(_icon("ally", d, fit(crop, "ally", d["cx"], d["cy"], sc, key=key)))
    return out


def _icon(role, det, f) -> dict:
    read = bool(f.get("read"))
    return {"role": role, "cx": float(det["cx"]), "cy": float(det["cy"]),
            "x": float(f["x"]) if read else float(det["cx"]), "y": float(f["y"]) if read else float(det["cy"]),
            "deg": float(f["deg"]) if read else None, "fit": f}


def hl_loglik(hl_deg) -> np.ndarray:
    """The highlight's log-likelihood over `GRID`, zero where it is unread."""
    if hl_deg is None:
        return np.zeros(len(GRID))
    k = 1.0 / math.radians(HL_SIGMA_DEG) ** 2
    d = np.radians(GRID - hl_deg)
    vm = np.exp(k * (np.cos(d) - 1.0)) / (2 * math.pi * np.i0(k) * math.exp(-k)) * math.radians(GRID_DEG)
    return np.log((1 - HL_OUT) * vm + HL_OUT / len(GRID))


# ---------------------------------------------------------------- the light

def evidence(s, crop, target: dict, icons: list[dict], sc: float) -> dict:
    """`{"lit", "comp", "excl_*"}`: the light joined to `target` and the pixels it may be scored on."""
    h, w = s.passable.shape
    yy, xx = np.mgrid[0:h, 0:w]
    dist_t = np.hypot(xx - target["x"], yy - target["y"])
    reach = co.R_EVAL * sc
    near = dist_t <= reach
    fp = np.zeros((h, w), bool)
    for ic in icons:
        fp |= np.hypot(xx - ic["x"], yy - ic["y"]) <= td.L * sc + co.PAD
    own = dist_t <= td.L * sc + co.PAD
    raw = lighting.raw_lit(crop, s.ref)
    base = near & s.ref.known & ~fp
    lit = (raw & base).astype(np.uint8)
    band = cv2.dilate(own.astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * co.JOIN_PX + 1,) * 2)) > 0
    _n, lab = cv2.connectedComponents(lit, connectivity=8)
    keep = np.unique(lab[band & (lit > 0)])
    keep = keep[keep > 0]
    joined = np.isin(lab, keep) if len(keep) else np.zeros((h, w), bool)
    neigh = np.zeros((h, w), bool)
    vor = np.zeros((h, w), bool)
    for ic in icons:
        if ic is target:
            continue
        if math.hypot(ic["x"] - target["x"], ic["y"] - target["y"]) > 2 * reach:
            continue
        if ic["deg"] is not None:
            neigh |= cone.raycast(s.passable, ic["x"], ic["y"], ic["deg"], visible=s.floor,
                                  max_r=int(3 * reach) + 2)
        else:
            vor |= np.hypot(xx - ic["x"], yy - ic["y"]) < dist_t
    stray = (lit > 0) & ~joined
    comp = base & ~neigh & ~vor & ~stray
    return {"lit": joined & comp, "comp": comp, "raw_lit_near": int((raw & near).sum()),
            "excl_footprint_lit": int((raw & near & s.ref.known & fp).sum()),
            "excl_neighbour_lit": int((joined & neigh).sum()), "excl_unattributed_lit": int((joined & vor).sum()),
            "excl_stray_lit": int((stray & ~neigh & ~vor).sum()), "joined_lit": int((joined & comp).sum())}


def cone_term(s, x, y, deg, ev, sc) -> tuple[float, dict]:
    """The tempered sector log-likelihood ratio of a cone at `deg` from `(x, y)`, and its counts."""
    reach = co.R_EVAL * sc
    m = cone.raycast(s.passable, x, y, deg, visible=s.floor, max_r=int(reach) + 2) & ev["comp"]
    ys, xs = np.nonzero(m)
    if not len(ys):
        return 0.0, {"n": 0, "lit": 0, "sectors": 0}
    rel = td._signed_deg(np.degrees(np.arctan2(ys - y, xs - x)) - deg)
    half = cone.CONE_HALF_ANGLE_DEG
    b = np.clip(((rel + half) / (2 * half) * N_SECTORS).astype(int), 0, N_SECTORS - 1)
    litv = ev["lit"][ys, xs]
    n_s = np.bincount(b, minlength=N_SECTORS)
    l_s = np.bincount(b, weights=litv.astype(float), minlength=N_SECTORS)
    ok = n_s >= SECTOR_MIN_PX * sc * sc
    f = l_s[ok] / n_s[ok]
    a, c = math.log(P_LIT / P_BG), math.log((1 - P_LIT) / (1 - P_BG))
    ll = float(TEMPER * (f * a + (1 - f) * c).sum())
    return ll, {"n": int(len(ys)), "lit": int(litv.sum()), "sectors": int(ok.sum())}


def light_loglik(s, target, ev, sc) -> np.ndarray:
    return np.array([cone_term(s, target["x"], target["y"], float(g), ev, sc)[0] for g in GRID])


# ---------------------------------------------------------------- the posterior

def lobe_logodds(ll: np.ndarray, deg: float) -> float:
    """log P(within 90 degrees of `deg`) - log P(beyond), under the grid log-weights `ll`."""
    fwd = np.abs(td._signed_deg(GRID - deg)) <= 90.0
    return _lse(ll[fwd]) - _lse(ll[~fwd])


def refine(ll: np.ndarray, mask: np.ndarray) -> float:
    """Circular mean of the posterior within `REFINE_DEG` of its peak inside `mask`."""
    i = int(np.argmax(np.where(mask, ll, -np.inf)))
    near = mask & (np.abs(td._signed_deg(GRID - GRID[i])) <= REFINE_DEG)
    p = np.exp(ll[near] - ll[near].max())
    a = np.radians(GRID[near])
    return float(math.degrees(math.atan2((p * np.sin(a)).sum(), (p * np.cos(a)).sum())))


def decide(td_deg: float, ll: np.ndarray) -> tuple[float, float]:
    """`(facing, lobe log-odds)`: the teardrop's angle unless the far half holds more mass."""
    lo = lobe_logodds(ll, td_deg)
    if lo >= 0:
        return td_deg, lo
    return refine(ll, np.abs(td._signed_deg(GRID - td_deg)) > 90.0), lo


def fuse(s, crop, row: dict, cls: str, sc: float) -> dict:
    """Every arm's facing for one labelled icon, its witnesses' lobe log-odds and disagreements."""
    icons = team_icons(s, crop, sc)
    cands = [ic for ic in icons if ic["role"] == ("self" if cls == "self" else "ally")]
    target = min(cands, key=lambda ic: math.hypot(ic["cx"] - row["det_cx"], ic["cy"] - row["det_cy"]),
                 default=None)
    # One self icon a frame: its best detection is the target, as `self_facing_eval` seeds it.
    if (target is not None and cls != "self"
            and math.hypot(target["cx"] - row["det_cx"], target["cy"] - row["det_cy"]) > 3.0 * max(sc, 1.0)):
        target = None
    if target is None:
        f = fit(crop, cls, row["det_cx"], row["det_cy"], sc)
        target = _icon(cls, {"cx": row["det_cx"], "cy": row["det_cy"]}, f)
        target["unmatched"] = True
        icons.append(target)
    f = target["fit"]
    out = {"teardrop": target["deg"], "teardrop_reason": None if f.get("read") else f.get("reason", "no_fit"),
           "ncc": f.get("ncc"), "margin": f.get("margin"), "highlight": row.get("highlight"),
           "td_x": target["x"], "td_y": target["y"], "neighbours": len(icons) - 1,
           "neighbours_unread": sum(ic["deg"] is None for ic in icons if ic is not target),
           "unmatched": bool(target.get("unmatched"))}
    for a in ARMS[2:]:
        out[a] = None
    if target["deg"] is None:
        return out
    tdd = target["deg"]
    l_td = KAPPA_TD * f["profile"]
    l_hl = hl_loglik(row.get("highlight"))
    ev = evidence(s, crop, target, icons, sc)
    l_light = light_loglik(s, target, ev, sc)
    prior = l_td + l_hl
    post = prior + l_light
    out["prior"], lo_prior = decide(tdd, prior)
    out["fusion_nohl"], lo_nohl = decide(tdd, l_td + l_light)
    out["fusion"], lo_post = decide(tdd, post)
    out["fusion_adjust"] = (refine(post, np.ones(len(GRID), bool)) if lo_post >= 0 else out["fusion"])
    # The light alone on the teardrop's axis: the cones at its facing and its reverse.
    t_f, c_f = cone_term(s, target["x"], target["y"], tdd, ev, sc)
    t_r, c_r = cone_term(s, target["x"], target["y"], tdd + 180.0, ev, sc)
    out["light_lobe"] = tdd if t_f >= t_r else float(td._signed_deg(tdd + 180.0))
    lit_old = lighting.lit_mask(crop, s.ref)
    got = cone.resolve_lobe(s.passable, lit_old, [{"cx": target["x"], "cy": target["y"], "facing": tdd}],
                            visible=s.floor)[0]
    out["light_lobe_raw"] = float(td._signed_deg(got["facing"]))
    hl_lo = None
    if row.get("highlight") is not None:
        hl_lo = 1.0 if abs(float(td._signed_deg(row["highlight"] - tdd))) <= 90.0 else -1.0
    out.update({
        "lo_teardrop": lobe_logodds(l_td, tdd), "lo_highlight": lobe_logodds(l_hl, tdd) if hl_lo else None,
        "lo_prior": lo_prior, "lo_light": lobe_logodds(l_light, tdd) if np.ptp(l_light) > 0 else 0.0,
        "lo_post": lo_post, "lo_nohl": lo_nohl, "light_fwd": t_f, "light_rev": t_r,
        "cone_fwd": c_f, "cone_rev": c_r, "evidence": {k: v for k, v in ev.items() if k not in ("lit", "comp")},
        "lit_old_fwd_rev": got.get("lobe_score"),
        "rests_on": ["teardrop", "tip_highlight", "drawn_light"] if np.ptp(l_light) > 0
        else ["teardrop", "tip_highlight"],
        "_curves": {"prior": prior, "light": l_light, "post": post},
        "_ev": ev, "_icons": icons, "_target": target})
    # Every disagreement between the witnesses, in lobes: + holds the teardrop's.
    sides = {"teardrop": 1, "highlight": hl_lo,
             "light": None if out["lo_light"] == 0 else (1 if out["lo_light"] > 0 else -1)}
    out["disagreements"] = [f"{a}~{b}" for a, b in (("teardrop", "highlight"), ("teardrop", "light"),
                                                    ("highlight", "light"))
                            if sides[a] is not None and sides[b] is not None and sides[a] != sides[b]]
    out["fused_flipped"] = lo_post < 0
    return out


# ---------------------------------------------------------------- the other direction

def missing_cones(s, crop, rows_here: list[dict], sc: float) -> dict:
    """Joined team light no team cone explains, by whether its nearest icon has a facing."""
    icons = team_icons(s, crop, sc)
    fused = {}
    for r in rows_here:
        t = r.get("_target")
        if t is not None and r.get("fusion") is not None:
            fused[(round(t["x"], 2), round(t["y"], 2))] = r["fusion"]
    if not icons:
        return {}
    h, w = s.passable.shape
    yy, xx = np.mgrid[0:h, 0:w]
    near = np.zeros((h, w), bool)
    fp = np.zeros((h, w), bool)
    cones = np.zeros((h, w), bool)
    for ic in icons:
        near |= np.hypot(xx - ic["x"], yy - ic["y"]) <= co.R_EVAL * sc
        fp |= np.hypot(xx - ic["x"], yy - ic["y"]) <= td.L * sc + co.PAD
        deg = fused.get((round(ic["x"], 2), round(ic["y"], 2)), ic["deg"])
        if deg is not None:
            cones |= cone.raycast(s.passable, ic["x"], ic["y"], deg, visible=s.floor)
    raw = lighting.raw_lit(crop, s.ref)
    lit = (raw & near & s.ref.known & ~fp).astype(np.uint8)
    band = cv2.dilate(fp.astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * co.JOIN_PX + 1,) * 2)) > 0
    _n, lab = cv2.connectedComponents(lit, connectivity=8)
    keep = np.unique(lab[band & (lit > 0)])
    keep = keep[keep > 0]
    joined = np.isin(lab, keep) if len(keep) else np.zeros((h, w), bool)
    un = (joined & ~cones).astype(np.uint8)
    n, lab2, stats, cents = cv2.connectedComponentsWithStats(un, connectivity=8)
    out = {"joined": int(joined.sum()), "unexplained": int(un.sum()), "blobs_faced": 0, "blobs_unfaced": 0,
           "px_faced": 0, "px_unfaced": 0}
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        if a < 20 * sc * sc:
            continue
        ys, xs = np.nonzero(lab2 == i)
        d = [float(np.min(np.hypot(xs - ic["x"], ys - ic["y"]))) for ic in icons]
        ic = icons[int(np.argmin(d))]
        k = "faced" if ic["deg"] is not None else "unfaced"
        out[f"blobs_{k}"] += 1
        out[f"px_{k}"] += a
    return out


# ---------------------------------------------------------------- the label sets

def _sessions():
    import team_vision_eval as tve
    cache = {}

    def get(sid):
        if sid not in cache:
            cache[sid] = tve.Sess(sid)
        return cache[sid]
    return get


def run_set(rows: list[dict], cls_of, sess) -> None:
    for i, r in enumerate(rows):
        s = sess(r["session"])
        crop = r["_crop"]
        sc = widget_scale(crop.shape[1])
        got = fuse(s, crop, r, cls_of(r), sc)
        r["teardrop_frozen"] = r.get("teardrop")
        r["teardrop_owner"] = got.pop("teardrop")
        r.update({k: v for k, v in got.items() if k != "highlight"})
        r["teardrop"] = r["teardrop_owner"]
        r["scale"] = sc
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(rows)}", flush=True)


def err(r, name):
    if r.get(name) is None or r.get("label_deg") is None:
        return None
    return float(td._signed_deg(r[name] - r["label_deg"]))


def summarise(rows: list[dict]) -> dict:
    out = {}
    for name in ARMS:
        errs = [e for e in (err(r, name) for r in rows) if e is not None]
        d = ife.summary(errs)
        d["unread"] = sum(r.get(name) is None for r in rows)
        if name != "teardrop":
            both = [r for r in rows if err(r, name) is not None and err(r, "teardrop") is not None]
            d["fixed"] = sum(abs(err(r, "teardrop")) > 90 and abs(err(r, name)) <= 90 for r in both)
            d["broken"] = sum(abs(err(r, "teardrop")) <= 90 and abs(err(r, name)) > 90 for r in both)
            d["changed"] = sum(abs(float(td._signed_deg(r[name] - r["teardrop"]))) > 90 for r in both)
        out[name] = d
    out["teardrop"]["flips_n"] = sum(1 for r in rows if (e := err(r, "teardrop")) is not None and abs(e) > 90)
    return out


def _print(title: str, res: dict) -> None:
    print(f"\n== {title}")
    print(f"  {'arm':15s} {'n':>3s} {'unread':>6s} {'med|e|':>7s} {'flip':>5s} {'fixed':>5s} {'broke':>5s} "
          f"{'moved':>5s}")
    for name, v in res.items():
        if not v.get("n"):
            print(f"  {name:15s} {0:3d} {v['unread']:6d}")
            continue
        print(f"  {name:15s} {v['n']:3d} {v['unread']:6d} {v['median_abs_deg']:7.2f} {v['flip']:5.3f} "
              f"{v.get('fixed', ''):>5} {v.get('broken', ''):>5} {v.get('changed', ''):>5}")


def _values(res: dict, prefix: str = "") -> dict:
    out = {}
    for name, v in res.items():
        out[f"{prefix}{name}_n"] = v.get("n", 0)
        out[f"{prefix}{name}_unread"] = v["unread"]
        for k in ("median_abs_deg", "flip", "within10", "fixed", "broken", "changed", "flips_n"):
            if k in v:
                out[f"{prefix}{name}_{k}"] = round(v[k], 4) if isinstance(v[k], float) else v[k]
    return out


def witness_counts(rows: list[dict], prefix: str = "") -> dict:
    """How often each pair of witnesses disagrees on the lobe, and who the label sides with."""
    out = {}
    c = Counter(d for r in rows for d in r.get("disagreements", []))
    for k in ("teardrop~highlight", "teardrop~light", "highlight~light"):
        out[f"{prefix}disagree_{k.replace('~', '_vs_')}"] = c.get(k, 0)
    lab = [r for r in rows if r.get("lo_light") not in (None, 0.0) and r.get("label_deg") is not None]
    right = [abs(float(td._signed_deg((r["teardrop"] if r["lo_light"] > 0 else r["teardrop"] + 180) - r["label_deg"]))) <= 90
             for r in lab]
    out[f"{prefix}light_lobe_with_evidence_n"] = len(lab)
    out[f"{prefix}light_lobe_with_evidence_right"] = int(sum(right))
    raw_right = [abs(float(td._signed_deg(r["light_lobe_raw"] - r["label_deg"]))) <= 90 for r in rows
                 if r.get("light_lobe_raw") is not None and r.get("label_deg") is not None]
    out[f"{prefix}light_lobe_raw_right"] = int(sum(raw_right))
    out[f"{prefix}light_lobe_raw_n"] = len(raw_right)
    out[f"{prefix}no_light_evidence"] = sum(1 for r in rows if r.get("lo_light") == 0.0)
    return out


def e6_rows(store: Path) -> list[dict]:
    return [r for r in th.e6_scored(th.e6_rows(store)) if r["cls"] == "ally"]


def self_rows(store: Path) -> list[dict]:
    return th.self_scored(th.self_rows(store))


def rows_331(store: Path) -> list[dict]:
    rows, _all = th.rows_331(store)
    return th.scored_331(rows)


# ---------------------------------------------------------------- the sheet

def _strip(curves: dict, label, tdd, w: int, hgt: int = 90) -> np.ndarray:
    """Prior (cyan), light (orange) and posterior (white) over angle, each min-max scaled; label green, teardrop blue."""
    img = np.zeros((hgt, w, 3), np.uint8)
    cols = {"prior": (255, 255, 0), "light": (0, 165, 255), "post": (255, 255, 255)}
    xs = (GRID / 360.0 * (w - 1)).astype(int)
    for k, v in curves.items():
        v = np.asarray(v, float)
        if np.ptp(v) <= 0:
            continue
        y = (hgt - 4 - (v - v.min()) / np.ptp(v) * (hgt - 8)).astype(int)
        cv2.polylines(img, [np.stack([xs, y], 1).astype(np.int32)], False, cols[k], 1)
    for deg, col in ((label, (0, 255, 0)), (tdd, (255, 128, 0))):
        if deg is not None:
            x = int((deg % 360.0) / 360.0 * (w - 1))
            cv2.line(img, (x, 0), (x, hgt - 1), col, 1)
    return img


def sheet(rows: list[dict], path: Path, zoom: int = 3, per_row: int = 4) -> Path:
    """Each item: the light scored (yellow: lit evidence, dim blue: comparable unlit, red: a
    neighbour's predicted cone), label (green), teardrop (blue), highlight (magenta), fusion
    (white); a strip of prior, light and posterior over angle beneath."""
    tiles = []
    for r in rows:
        crop = r["_crop"]
        sc = r["scale"]
        t = r.get("_target")
        cx, cy = (t["x"], t["y"]) if t else (r["det_cx"], r["det_cy"])
        half = int(co.R_EVAL * sc) + 4
        ix, iy = int(round(cx)), int(round(cy))
        pad = cv2.copyMakeBorder(crop, half, half, half, half, cv2.BORDER_CONSTANT)
        sub = pad[iy:iy + 2 * half + 1, ix:ix + 2 * half + 1].copy()
        ev = r.get("_ev")
        if ev is not None:
            hh, ww = crop.shape[:2]
            ov = np.zeros((hh, ww, 3), np.uint8)
            ov[ev["comp"] & ~ev["lit"]] = (90, 40, 0)
            ov[ev["lit"]] = (0, 200, 255)
            excl = np.zeros((hh, ww), bool)
            for ic in r["_icons"]:
                if ic is not t and ic["deg"] is not None and math.hypot(ic["x"] - cx, ic["y"] - cy) < 2 * half:
                    excl |= cone.raycast(r["_sess"].passable, ic["x"], ic["y"], ic["deg"], visible=r["_sess"].floor,
                                         max_r=3 * half)
            ov[excl & ~ev["comp"]] = (0, 0, 160)
            ovp = cv2.copyMakeBorder(ov, half, half, half, half, cv2.BORDER_CONSTANT)[iy:iy + 2 * half + 1,
                                                                                       ix:ix + 2 * half + 1]
            m = ovp.any(axis=2)
            sub[m] = (0.45 * sub[m] + 0.55 * ovp[m]).astype(np.uint8)
        big = cv2.resize(sub, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        o = (int((cx - ix + half + 0.5) * zoom), int((cy - iy + half + 0.5) * zoom))
        ln = half * zoom * 0.55
        for name, col, wd in (("label_deg", (0, 255, 0), 3), ("teardrop", (255, 128, 0), 2),
                              ("highlight", (255, 0, 255), 1), ("fusion", (255, 255, 255), 1)):
            deg = r.get(name)
            if deg is None:
                continue
            a = math.radians(deg)
            cv2.arrowedLine(big, o, (int(o[0] + ln * math.cos(a)), int(o[1] + ln * math.sin(a))), col, wd,
                            tipLength=0.1)
        et, ef, eh = err(r, "teardrop"), err(r, "fusion"), err(r, "highlight")
        lines = [f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s {r.get('cls', '')} ncc {r.get('ncc') or 0:.2f} "
                 f"mg {r.get('margin') or 0:.2f}",
                 f"err td {'-' if et is None else f'{et:+.0f}'} fu {'-' if ef is None else f'{ef:+.0f}'} "
                 f"hl {'-' if eh is None else f'{eh:+.0f}'}",
                 f"LO td {r.get('lo_teardrop') or 0:+.1f} hl {r.get('lo_highlight') or 0:+.1f} "
                 f"light {r.get('lo_light') or 0:+.1f} post {r.get('lo_post') or 0:+.1f}"]
        bad = ef is not None and abs(ef) > 90
        for k, s_ in enumerate(lines):
            cv2.putText(big, s_, (4, 16 + 16 * k), 0, 0.45, (0, 0, 255) if (bad and k == 1) else (255, 255, 255), 1)
        strip = _strip(r.get("_curves", {}), r.get("label_deg"), r.get("teardrop"), big.shape[1])
        tiles.append(np.vstack([big, strip]))
    if not tiles:
        return path
    H = max(tl.shape[0] for tl in tiles)
    W = max(tl.shape[1] for tl in tiles)
    tiles = [cv2.copyMakeBorder(tl, 0, H - tl.shape[0], 0, W - tl.shape[1] + 4, cv2.BORDER_CONSTANT,
                                value=(40, 40, 40)) for tl in tiles]
    while len(tiles) % per_row:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)])
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), grid)
    return path


def notable(rows: list[dict]) -> list[dict]:
    """Flipped and borderline items: a teardrop or fusion flip, a lobe change, a witness
    disagreement, or a posterior within 2 nats of even."""
    out = []
    for r in rows:
        et, ef = err(r, "teardrop"), err(r, "fusion")
        if ((et is not None and abs(et) > 90) or (ef is not None and abs(ef) > 90) or r.get("fused_flipped")
                or r.get("disagreements") or (r.get("lo_post") is not None and abs(r["lo_post"]) < 2.0)):
            out.append(r)
    return out


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    global TEMPER, OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true", help="one metrics row per label set")
    ap.add_argument("--sheet", action="store_true", help="write decision sheets to " + str(OUT))
    ap.add_argument("--json", type=Path, help="per-item rows (default: the store's analysis dir)")
    ap.add_argument("--sets", default="465,self,331")
    ap.add_argument("--temper", type=float, help="post hoc: override TEMPER; recorded under part suffix -posthoc")
    args = ap.parse_args(argv)
    posthoc = ""
    if args.temper is not None:
        TEMPER, posthoc = args.temper, f"-posthoc-t{args.temper:g}"
        OUT = OUT / posthoc.lstrip("-")
    th._idle()
    store = sem.STORE
    from reticle import metrics
    sess = _sessions()
    deps = {"prototype": VERSION, "teardrop": td.ICON_TEARDROP_VERSION, "highlight": th.VERSION,
            "grid_deg": GRID_DEG, "kappa_td": KAPPA_TD, "hl_sigma_deg": HL_SIGMA_DEG, "hl_out": HL_OUT,
            "p_lit": P_LIT, "p_bg": P_BG, "n_sectors": N_SECTORS, "temper": round(TEMPER, 4),
            "sector_min_px": SECTOR_MIN_PX, "lighting": lighting.LIGHTING_VERSION}
    sets = args.sets.split(",")
    dump, all_rows = {}, {}
    if "465" in sets:
        rows = e6_rows(store)
        print(f"E6 allies, 465 px: {len(rows)} scored", flush=True)
        run_set(rows, lambda r: "ally", sess)
        all_rows["465"] = rows
    if "self" in sets:
        rows = self_rows(store)
        print(f"self labels: {len(rows)} scored", flush=True)
        run_set(rows, lambda r: "self", sess)
        all_rows["self"] = rows
    if "331" in sets:
        rows = rows_331(store)
        print(f"331 px allies: {len(rows)} scored", flush=True)
        run_set(rows, lambda r: "ally", sess)
        all_rows["331"] = rows
    for r in (r for v in all_rows.values() for r in v):
        r["_sess"] = sess(r["session"])

    records = []
    frozen = {}
    for k, rows in all_rows.items():
        fz = [abs(float(td._signed_deg(r["teardrop"] - r["teardrop_frozen"]))) for r in rows
              if r.get("teardrop") is not None and r.get("teardrop_frozen") is not None]
        frozen[k] = {"recomputed_vs_stored_teardrop_n": len(fz),
                     "recomputed_vs_stored_teardrop_max_deg": round(max(fz), 3) if fz else None,
                     "recomputed_vs_stored_read_changed": sum((r.get("teardrop") is None)
                                                              != (r.get("teardrop_frozen") is None) for r in rows)}
        print(f"{k}: the recomputed teardrop against the stored reading: {frozen[k]}")
    if "465" in all_rows:
        rows = all_rows["465"]
        res = summarise(rows)
        _print(f"E6 allies, 465 px ({len(rows)})", res)
        vals = _values(res, "ally_") | witness_counts(rows, "ally_")
        records.append(("labels-465", "+".join(lif.SESSIONS), vals | frozen["465"], lif.labels_path(store).name))
    if "self" in all_rows:
        rows = all_rows["self"]
        vals = {}
        for name, sub in (("lotus", [r for r in rows if r["session"] == lsf.LOTUS]),
                          ("control", [r for r in rows if r["session"] != lsf.LOTUS])):
            res = summarise(sub)
            _print(f"self, {name} ({len(sub)})", res)
            vals |= _values(res, f"{name}_") | witness_counts(sub, f"{name}_")
        records.append(("self", f"{lsf.LOTUS}+controls", vals | frozen["self"], lsf.labels_path(store).name))
    if "331" in all_rows:
        rows = all_rows["331"]
        res = summarise(rows)
        _print(f"331 px allies ({len(rows)})", res)
        vals = _values(res) | witness_counts(rows)
        for st in ("flip", "agree"):
            rs = summarise([r for r in rows if r["stratum"] == st])
            vals |= _values(rs, f"{st}_")
        records.append(("labels-331", "+".join(lif.QUOTA_331), vals | frozen["331"],
                        lif.labels_path(store, lif.SET_331).name))

    # The other direction: light no team cone explains, on the labelled frames.
    mc_tot = Counter()
    frames = {}
    for key, rows in all_rows.items():
        for r in rows:
            frames.setdefault((r["session"], float(r["t_ms"])), []).append(r)
    for (sid, t), rs in frames.items():
        crop = rs[0]["_crop"]
        got = missing_cones(sess(sid), crop, rs, widget_scale(crop.shape[1]))
        mc_tot.update(got)
        mc_tot["frames"] += 1
    print(f"\n== light no team cone explains, {mc_tot['frames']} labelled frames: {dict(mc_tot)}")
    mc = {f"missing_{k}": int(v) for k, v in mc_tot.items()}

    for part, session, vals, labels in records:
        print(f"{part}: {len(vals)} values")
        if args.record:
            metrics.record("facing_fusion_eval", part=part + posthoc, session=session, values=vals,
                           deps=dict(deps, labels=labels))
    if args.record and not posthoc:
        metrics.record("facing_fusion_eval", part="missing-cones", session="+".join(sorted({s for s, _ in frames})),
                       values=mc, deps=deps)

    OUT.mkdir(parents=True, exist_ok=True)
    jp = args.json or OUT / "items.json"
    clean = {k: [{kk: vv for kk, vv in r.items() if not kk.startswith("_")} for r in v] for k, v in all_rows.items()}
    jp.write_text(json.dumps({"version": VERSION, "deps": deps, "sets": clean}, indent=1, default=str),
                  encoding="utf-8")
    print("wrote", jp)
    dis = [dict(set=k, key=r["key"], session=r["session"], t_ms=r["t_ms"], disagreements=r["disagreements"],
                teardrop=r["teardrop"], highlight=r.get("highlight"), fusion=r.get("fusion"),
                lo_teardrop=r.get("lo_teardrop"), lo_highlight=r.get("lo_highlight"), lo_light=r.get("lo_light"),
                lo_post=r.get("lo_post"), rests_on=r.get("rests_on"), label_deg=r.get("label_deg"))
           for k, v in all_rows.items() for r in v if r.get("disagreements")]
    (OUT / "disagreements.json").write_text(json.dumps({"version": VERSION, "items": dis}, indent=1, default=str),
                                            encoding="utf-8")
    print("wrote", OUT / "disagreements.json", len(dis), "items")
    if args.sheet:
        for k, v in all_rows.items():
            print("wrote", sheet(notable(v), OUT / f"sheet_{k}.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
